"""Phase 7 Gate P7.9 Stage 2 -- Partnership persistence (schema v12).

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 17.2. The claims:

- **Typed, exact round trips.** Every Stage 1 fixture Partnership -- together
  every typed union -- is stored in typed columns and read back as an equal
  contract, floats bit for bit and authored order kept.
- **Stated, never defaulted.** The explicitly empty promote-participant set is
  distinct from a missing one, which is corrupt; so is a miscounted one.
- **Fail closed.** An unknown token, a row whose columns disagree with its own
  kind, an orphaned child row or a Partnership the Stage 1 validator refuses is a
  ``PersistedPartnershipDataError`` -- never "no Partnership".
- **Three marker states.** No Base row (none), no Strategy row (inherit), and a
  Strategy's explicit "no Partnership" are three different rows and answers.
- **Whole replacement and lifecycle** on every write path, and P-8 identity:
  the ``partner_id`` alone, with the name and role free to vary by Strategy.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import struct
from pathlib import Path
from typing import Any

import pytest

import _p7_9_fixtures as f  # type: ignore[import-not-found]
from _p7_2_fixtures import P7_9_TABLES, create_deal, execute, rows, table_names  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from _p7_8_fixtures import round_deal  # type: ignore[import-not-found]
from _p7_9_stage_2_fixtures import (  # type: ignore[import-not-found]
    all_fixture_partnerships,
    gp_as_lp,
    no_partnership_overlay,
    partnership_overlay,
    renamed,
    structured_deal,
    with_partner,
)
from anchor.analysis.strategy import NoPartnership, StrategyDomain
from anchor.deals import store
from anchor.deals.contracts import DealNotFoundError, InvestmentNotFoundError, InvestmentStructureError
from anchor.partnership import PartnershipIssueCode, PartnershipValidationError, PartnerRole

EMPTY = dict.fromkeys(P7_9_TABLES, [])

_ROUND_TRIPS = all_fixture_partnerships()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def partnership_rows(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {table: rows(db, table) for table in P7_9_TABLES}


def hidden(db: Path, partnership: Any = None) -> tuple[Any, str]:
    """A standalone Quick Deal opted in through a Scenario, with an optional
    Base Partnership."""

    deal = create_deal("quick", db)
    investment_id = store.create_scenario_for_deal(deal.id, name="Downside", db_path=db).investment_id
    if partnership is not None:
        store.set_base_partnership(investment_id, partnership, db_path=db)
    return deal, investment_id


def _bits(value: float) -> bytes:
    return struct.pack("<d", value)


def _float_bits(partnership: Any) -> list[bytes]:
    found: list[bytes] = []

    def walk(value: Any) -> None:
        if isinstance(value, float):
            found.append(_bits(value))
        elif dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                walk(getattr(value, field.name))
        elif isinstance(value, tuple):
            for item in value:
                walk(item)

    walk(partnership)
    return found


# =============================================================================
# Schema v12
# =============================================================================


def test_a_fresh_store_is_schema_12_with_eight_empty_partnership_tables(db: Path) -> None:
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    columns = {
        table: [(row[1], row[2]) for row in connection.execute(f"PRAGMA table_info({table})")]
        for table in P7_9_TABLES
    }
    connection.close()

    # AM1 added schema 13's two Asset Management tables; Asset Types 1 schema
    # 14's two classification tables; P7.10 Stage 2 schema 15's fourteen
    # valuation and Investment Memo tables. P7.9's own eight are unchanged by
    # all three, which is what this test is about.
    assert version == 15
    assert set(P7_9_TABLES) <= table_names(db)
    assert partnership_rows(db) == EMPTY
    assert {table: [name for name, _ in described] for table, described in columns.items()} == {
        "partnerships": [
            "partnership_id", "investment_id", "owner_kind", "owner_id", "has_partnership",
            "contribution_rule", "promote_participant_count",
        ],
        "partners": ["partnership_id", "partner_id", "ordinal", "name", "role", "investor_class", "commitment_share"],
        "partnership_benchmark_shares": ["partnership_id", "partner_id", "ordinal", "share"],
        "partnership_promote_participants": ["partnership_id", "partner_id", "ordinal"],
        "waterfall_tiers": [
            "partnership_id", "tier_id", "ordinal", "name", "sequence", "kind", "split_rule",
            "subject_kind", "subject_partner_id", "subject_investor_class", "subject_account", "combinator",
        ],
        "waterfall_tier_splits": ["partnership_id", "tier_id", "partner_id", "ordinal", "share"],
        "waterfall_hurdle_conditions": [
            "partnership_id", "tier_id", "condition_id", "ordinal", "condition_kind", "rate",
            "accrual_convention", "simple_distribution_order", "multiple",
        ],
        "waterfall_catch_up_terms": [
            "partnership_id", "tier_id", "recipient_kind", "recipient_partner_id",
            "recipient_investor_class", "target_profit_share",
        ],
    }
    for table, described in columns.items():
        assert {kind for _, kind in described} <= {"TEXT", "REAL", "INTEGER"}, table


def test_one_partnership_per_owner_at_the_persistence_layer(db: Path) -> None:
    store.list_deals(db_path=db)
    execute(db, "INSERT INTO partnerships VALUES ('p1', 'i', 'base', 'i', 1, 'pro_rata_by_commitment', 0)")
    with pytest.raises(sqlite3.IntegrityError):
        execute(db, "INSERT INTO partnerships VALUES ('p2', 'i', 'base', 'i', 1, 'pro_rata_by_commitment', 0)")
    with pytest.raises(sqlite3.IntegrityError):
        execute(db, "INSERT INTO partnerships VALUES ('p3', 'i', 'fund', 'j', 1, 'pro_rata_by_commitment', 0)")
    with pytest.raises(sqlite3.IntegrityError):
        execute(db, "INSERT INTO partnerships VALUES ('p4', 'i', 'strategy', 'k', 2, NULL, NULL)")


# =============================================================================
# Round trips
# =============================================================================


@pytest.mark.parametrize(("name", "terms"), _ROUND_TRIPS, ids=[name for name, _ in _ROUND_TRIPS])
def test_every_fixture_partnership_round_trips_exactly(db: Path, name: str, terms: Any) -> None:
    _, investment_id = hidden(db)

    saved = store.set_base_partnership(investment_id, terms, db_path=db)
    loaded = store.get_base_partnership(investment_id, db_path=db)

    assert saved == terms
    assert loaded == terms
    assert _float_bits(loaded) == _float_bits(terms)
    assert store.list_investment_partnerships(investment_id, db_path=db).base == terms


def test_the_fixtures_exercise_every_typed_union() -> None:
    from anchor.capital_structure.contracts import AccrualConvention
    from anchor.deals.partnership_codec import condition_kind, split_rule_kind
    from anchor.partnership import SimpleDistributionOrder

    splits, subjects, conditions, recipients, conventions, orders, participants = set(), set(), set(), set(), set(), set(), set()
    for _, terms in _ROUND_TRIPS:
        participants.add(len(terms.promote_participant_ids))
        for tier in terms.tiers:
            splits.add(split_rule_kind(tier.split))
            if tier.hurdle is not None:
                subjects.add(tier.hurdle.hurdle_subject.kind)
                for condition in tier.hurdle.conditions:
                    conditions.add(condition_kind(condition))
                    conventions.add(getattr(condition, "accrual_convention", None))
                    orders.add(getattr(condition, "simple_distribution_order", None))
            if tier.catch_up is not None:
                recipients.add(tier.catch_up.recipient.kind)
    assert {kind.value for kind in splits} == {"explicit", "pro_rata_by_contribution"}
    assert {kind.value for kind in subjects} == {"partner", "investor_class", "economic_account"}
    assert {kind.value for kind in conditions} == {"irr", "moic"}
    assert {kind.value for kind in recipients} == {"partner", "investor_class"}
    assert {AccrualConvention.SIMPLE, AccrualConvention.ANNUAL_COMPOUND} <= conventions
    assert set(SimpleDistributionOrder) <= orders
    assert {0, 1, 2} <= participants


def test_authored_order_is_kept_and_a_permutation_is_a_different_presentation(db: Path) -> None:
    _, investment_id = hidden(db)
    terms = f.f1_terms()
    permuted = dataclasses.replace(
        terms,
        partners=tuple(reversed(terms.partners)),
        tiers=tuple(reversed(terms.tiers)),
        promote_benchmark=dataclasses.replace(
            terms.promote_benchmark, shares=tuple(reversed(terms.promote_benchmark.shares))
        ),
    )

    store.set_base_partnership(investment_id, permuted, db_path=db)

    assert store.get_base_partnership(investment_id, db_path=db) == permuted


def test_the_explicit_empty_participant_set_round_trips_as_empty(db: Path) -> None:
    _, investment_id = hidden(db)
    terms = f.f1_terms(participants=())

    store.set_base_partnership(investment_id, terms, db_path=db)

    loaded = store.get_base_partnership(investment_id, db_path=db)
    assert loaded is not None and loaded.promote_participant_ids == ()
    ((count,),) = [row[-1:] for row in rows(db, "partnerships")]
    assert count == 0


def test_a_missing_participant_set_is_corrupt_never_empty(db: Path) -> None:
    _, investment_id = hidden(db, f.f1_terms(participants=()))
    execute(db, "UPDATE partnerships SET promote_participant_count = NULL")

    with pytest.raises(store.PersistedPartnershipDataError, match="missing"):
        store.get_base_partnership(investment_id, db_path=db)


@pytest.mark.parametrize("count", [0, 2])
def test_a_miscounted_participant_set_is_corrupt(db: Path, count: int) -> None:
    _, investment_id = hidden(db, f.f1_terms())  # one participant
    execute(db, "UPDATE partnerships SET promote_participant_count = ?", (count,))

    with pytest.raises(store.PersistedPartnershipDataError, match="participant"):
        store.get_base_partnership(investment_id, db_path=db)


def test_a_dropped_participant_row_is_corrupt(db: Path) -> None:
    _, investment_id = hidden(db, f.f12_terms())  # two participants
    execute(db, "DELETE FROM partnership_promote_participants WHERE partner_id = 'g2'")

    with pytest.raises(store.PersistedPartnershipDataError):
        store.get_base_partnership(investment_id, db_path=db)


# =============================================================================
# Fail closed
# =============================================================================

_CORRUPTIONS = [
    ("unknown-role", "UPDATE partners SET role = 'sponsor' WHERE partner_id = 'gp'"),
    ("unknown-contribution-rule", "UPDATE partnerships SET contribution_rule = 'gp_funds_overruns'"),
    ("missing-contribution-rule", "UPDATE partnerships SET contribution_rule = NULL"),
    ("unknown-tier-kind", "UPDATE waterfall_tiers SET kind = 'lookback' WHERE tier_id = 'promote_2'"),
    ("unknown-split-rule", "UPDATE waterfall_tiers SET split_rule = 'equal' WHERE tier_id = 'pref'"),
    ("pro-rata-with-split-rows", "UPDATE waterfall_tiers SET split_rule = 'pro_rata_by_contribution' WHERE tier_id = 'pref'"),
    ("unknown-subject-kind", "UPDATE waterfall_tiers SET subject_kind = 'fund' WHERE tier_id = 'pref'"),
    ("subject-columns-disagree", "UPDATE waterfall_tiers SET subject_investor_class = 'lp' WHERE tier_id = 'pref'"),
    ("subject-on-residual", "UPDATE waterfall_tiers SET subject_kind = 'partner' WHERE tier_id = 'promote_2'"),
    ("unknown-combinator", "UPDATE waterfall_tiers SET combinator = 'either' WHERE tier_id = 'pref'"),
    ("unknown-condition-kind", "UPDATE waterfall_hurdle_conditions SET condition_kind = 'npv' WHERE condition_id = 'pref-8'"),
    ("unknown-accrual-convention", "UPDATE waterfall_hurdle_conditions SET accrual_convention = 'continuous' WHERE condition_id = 'pref-8'"),
    ("unknown-simple-order", "UPDATE waterfall_hurdle_conditions SET simple_distribution_order = 'pro_rata' WHERE condition_id = 'pref-8'"),
    ("irr-with-a-multiple", "UPDATE waterfall_hurdle_conditions SET multiple = 1.5 WHERE condition_id = 'pref-8'"),
    ("irr-without-a-rate", "UPDATE waterfall_hurdle_conditions SET rate = NULL WHERE condition_id = 'pref-8'"),
    ("moic-kind-on-irr-columns", "UPDATE waterfall_hurdle_conditions SET condition_kind = 'moic' WHERE condition_id = 'pref-8'"),
    ("economic-account-recipient", "UPDATE waterfall_catch_up_terms SET recipient_kind = 'economic_account'"),
    ("recipient-columns-disagree", "UPDATE waterfall_catch_up_terms SET recipient_investor_class = 'gp'"),
    ("catch-up-row-on-residual", "UPDATE waterfall_catch_up_terms SET tier_id = 'promote_2'"),
    ("catch-up-without-terms", "DELETE FROM waterfall_catch_up_terms"),
    ("orphaned-split-row", "UPDATE waterfall_tier_splits SET tier_id = 'ghost' WHERE tier_id = 'pref' AND partner_id = 'gp'"),
    ("condition-on-catch-up", "UPDATE waterfall_hurdle_conditions SET tier_id = 'catch_up'"),
    ("shares-do-not-sum", "UPDATE partners SET commitment_share = 0.2 WHERE partner_id = 'gp'"),
    ("benchmark-share-dropped", "DELETE FROM partnership_benchmark_shares WHERE partner_id = 'gp'"),
    ("unknown-participant", "UPDATE partnership_promote_participants SET partner_id = 'ghost'"),
    ("explicit-none-flag-on-a-base", "UPDATE partnerships SET has_partnership = 0"),
]


@pytest.mark.parametrize(("name", "sql"), _CORRUPTIONS, ids=[name for name, _ in _CORRUPTIONS])
def test_a_corrupt_stored_partnership_fails_closed(db: Path, name: str, sql: str) -> None:
    _, investment_id = hidden(db, f.f1_terms())
    execute(db, sql)

    with pytest.raises(store.PersistedPartnershipDataError):
        store.get_base_partnership(investment_id, db_path=db)
    with pytest.raises(store.PersistedPartnershipDataError):
        store.list_investment_partnerships(investment_id, db_path=db)


def test_an_unknown_account_token_fails_closed(db: Path) -> None:
    _, investment_id = hidden(db, f.f5_terms(f.ALL_EQUITY))
    execute(db, "UPDATE waterfall_tiers SET subject_account = 'all_equity' WHERE subject_kind = 'economic_account'")

    with pytest.raises(store.PersistedPartnershipDataError, match="EconomicAccount"):
        store.get_base_partnership(investment_id, db_path=db)


def test_an_explicit_none_marker_that_holds_terms_is_corrupt(db: Path) -> None:
    _, investment_id = hidden(db)
    strategy = store.create_strategy(
        investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db
    )
    execute(
        db,
        "UPDATE partnerships SET promote_participant_count = 0 WHERE owner_id = ?",
        (strategy.strategy.strategy_id,),
    )

    with pytest.raises(store.PersistedPartnershipDataError, match="no Partnership"):
        store.get_strategy(investment_id, strategy.strategy.strategy_id, db_path=db)


def test_an_invalid_partnership_is_refused_and_writes_nothing(db: Path) -> None:
    deal, investment_id = hidden(db)
    before = partnership_rows(db)
    invalid = with_partner(f.f1_terms(), "gp", commitment_share=0.5)

    with pytest.raises(PartnershipValidationError) as refused:
        store.set_base_partnership(investment_id, invalid, db_path=db)
    assert PartnershipIssueCode.SHARES_DO_NOT_SUM_TO_ONE in {issue.code for issue in refused.value.issues}
    assert partnership_rows(db) == before

    with pytest.raises(PartnershipValidationError):
        store.set_deal_partnership(round_deal(db, name="Standalone").id, invalid, db_path=db)
    assert partnership_rows(db) == before


def test_an_invalid_strategy_partnership_is_a_strategy_issue_and_writes_nothing(db: Path) -> None:
    from anchor.analysis.strategy import StrategyIssueCode, StrategyValidationError

    _, investment_id = hidden(db)
    invalid = dataclasses.replace(f.f1_terms(), promote_participant_ids=("ghost",))

    with pytest.raises(StrategyValidationError) as refused:
        store.create_strategy(investment_id, name="Bad", root_overlays=(partnership_overlay(invalid),), db_path=db)

    (issue,) = refused.value.issues
    assert issue.code is StrategyIssueCode.INVALID_PARTNERSHIP
    assert issue.domain is StrategyDomain.PARTNERSHIP
    assert issue.source_code == PartnershipIssueCode.UNKNOWN_PROMOTE_PARTICIPANT.value
    assert store.list_strategies(investment_id, db_path=db) == []
    assert partnership_rows(db) == EMPTY


# =============================================================================
# Three marker states, and whole replacement
# =============================================================================


def test_inherit_explicit_none_and_replacement_are_three_different_rows(db: Path) -> None:
    _, investment_id = hidden(db, f.f1_terms())
    inherit = store.create_strategy(investment_id, name="Inherit", db_path=db)
    none = store.create_strategy(investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db)
    own = store.create_strategy(
        investment_id, name="Own", root_overlays=(partnership_overlay(f.f7_terms()),), db_path=db
    )

    owners = {row[3]: row[4] for row in rows(db, "partnerships")}
    assert inherit.strategy.strategy_id not in owners
    assert owners[none.strategy.strategy_id] == 0
    assert owners[own.strategy.strategy_id] == 1
    assert owners[investment_id] == 1

    assert inherit.strategy.root_overlays == ()
    assert [o.content for o in none.strategy.root_overlays] == [NoPartnership()]
    assert [o.content for o in own.strategy.root_overlays] == [f.f7_terms()]
    listed = store.list_investment_partnerships(investment_id, db_path=db)
    assert listed.base == f.f1_terms()
    assert [(entry.strategy_id, entry.partnership) for entry in listed.strategies] == [
        (none.strategy.strategy_id, None),
        (own.strategy.strategy_id, f.f7_terms()),
    ]


def test_a_strategy_states_capital_structure_and_partnership_in_declaration_order(db: Path) -> None:
    from _p7_9_stage_2_fixtures import capital_overlay, mezz_structure  # type: ignore[import-not-found]

    deal, investment_id = hidden(db)
    strategy = store.create_strategy(
        investment_id,
        name="Both",
        root_overlays=(partnership_overlay(f.f1_terms()), capital_overlay(mezz_structure(deal.id))),
        db_path=db,
    )
    assert [overlay.domain for overlay in strategy.strategy.root_overlays] == [
        StrategyDomain.CAPITAL_STRUCTURE,
        StrategyDomain.PARTNERSHIP,
    ]


def test_a_base_replacement_is_whole_and_clearing_leaves_no_row(db: Path) -> None:
    _, investment_id = hidden(db, f.f12_terms())

    store.set_base_partnership(investment_id, f.f1_terms(), db_path=db)
    assert store.get_base_partnership(investment_id, db_path=db) == f.f1_terms()
    assert {row[1] for row in rows(db, "partners")} == {"lp", "gp"}

    store.set_base_partnership(investment_id, None, db_path=db)
    assert store.get_base_partnership(investment_id, db_path=db) is None
    assert partnership_rows(db) == EMPTY


def test_a_strategy_update_replaces_whole_and_dropping_the_overlay_inherits_again(db: Path) -> None:
    _, investment_id = hidden(db, f.f1_terms())
    created = store.create_strategy(
        investment_id, name="Own", root_overlays=(partnership_overlay(f.f12_terms()),), db_path=db
    )
    strategy_id = created.strategy.strategy_id

    store.update_strategy(
        investment_id, strategy_id, name="Own", root_overlays=(partnership_overlay(f.f7_terms()),), db_path=db
    )
    assert [o.content for o in store.get_strategy(investment_id, strategy_id, db_path=db).strategy.root_overlays] == [
        f.f7_terms()
    ]
    assert {row[1] for row in rows(db, "partners")} == {"lp", "gp"}

    store.update_strategy(
        investment_id, strategy_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db
    )
    assert [o.content for o in store.get_strategy(investment_id, strategy_id, db_path=db).strategy.root_overlays] == [
        NoPartnership()
    ]

    store.update_strategy(investment_id, strategy_id, name="Inherit", db_path=db)
    assert store.get_strategy(investment_id, strategy_id, db_path=db).strategy.root_overlays == ()
    assert [row[3] for row in rows(db, "partnerships")] == [investment_id]


def test_a_rejected_strategy_update_leaves_the_previous_partnership(db: Path) -> None:
    _, investment_id = hidden(db)
    created = store.create_strategy(
        investment_id, name="Own", root_overlays=(partnership_overlay(f.f1_terms()),), db_path=db
    )
    before = partnership_rows(db)
    invalid = dataclasses.replace(f.f1_terms(), tiers=())

    from anchor.analysis.strategy import StrategyValidationError

    with pytest.raises(StrategyValidationError):
        store.update_strategy(
            investment_id,
            created.strategy.strategy_id,
            name="Own",
            root_overlays=(partnership_overlay(invalid),),
            db_path=db,
        )
    assert partnership_rows(db) == before


# =============================================================================
# One partner identity per Investment (P-8): the partner_id, and nothing else
# =============================================================================


def test_the_same_partner_id_may_hold_a_different_role_in_each_partnership(db: Path) -> None:
    """P-8 makes ``partner_id`` the stable identity. ``role`` is reporting-only
    presentation (Section 4.2): it selects no subject, recipient or
    participant, reaches no fingerprint, and may differ between the Base
    Partnership and each Strategy's own. Every write path accepts it."""

    deal, investment_id = hidden(db, f.f1_terms())
    as_lp = gp_as_lp(f.f1_terms())
    as_co_investor = with_partner(f.f1_terms(), "gp", role=PartnerRole.CO_INVESTOR)

    first = store.create_strategy(
        investment_id, name="GP as LP", root_overlays=(partnership_overlay(as_lp),), db_path=db
    ).strategy.strategy_id
    second = store.create_strategy(
        investment_id, name="GP as co-investor", root_overlays=(partnership_overlay(as_co_investor),), db_path=db
    ).strategy.strategy_id
    store.update_strategy(
        investment_id, second, name="GP as co-investor", root_overlays=(partnership_overlay(as_co_investor),), db_path=db
    )
    store.set_base_partnership(investment_id, f.f1_terms(), db_path=db)
    store.set_deal_partnership(deal.id, f.f1_terms(), db_path=db)

    listed = store.list_investment_partnerships(investment_id, db_path=db)
    roles = {
        "base": {p.partner_id: p.role for p in listed.base.partners},  # type: ignore[union-attr]
        **{
            entry.strategy_id: {p.partner_id: p.role for p in entry.partnership.partners}  # type: ignore[union-attr]
            for entry in listed.strategies
        },
    }
    assert roles["base"]["gp"] is PartnerRole.GP
    assert roles[first]["gp"] is PartnerRole.LP
    assert roles[second]["gp"] is PartnerRole.CO_INVESTOR
    # One identity throughout: the same id in every Partnership.
    assert {tuple(sorted(stated)) for stated in roles.values()} == {("gp", "lp")}


def test_a_varying_role_changes_no_economics(db: Path) -> None:
    """The waterfall never reads a role, so restating one changes no stored
    economics and no fingerprint."""

    from anchor.deals.fingerprint import fingerprint_partnership_source

    _, investment_id = hidden(db, f.f1_terms())
    digest = fingerprint_partnership_source(
        structured_source_fingerprint="a" * 64, partnership=f.f1_terms()
    )

    store.set_base_partnership(investment_id, gp_as_lp(f.f1_terms()), db_path=db)
    reloaded = store.get_base_partnership(investment_id, db_path=db)

    assert reloaded == gp_as_lp(f.f1_terms())
    assert fingerprint_partnership_source(
        structured_source_fingerprint="a" * 64, partnership=reloaded
    ) == digest


def test_what_a_strategy_varies_is_kept_whole(db: Path) -> None:
    """Name, role, commitment, benchmark, class, splits and participation may
    all differ per Strategy, and each statement is stored and read back whole."""

    _, investment_id = hidden(db, f.f1_terms())
    varied = renamed(
        with_partner(f.f7_terms(), "gp", investor_class="sponsor", role=PartnerRole.CO_INVESTOR)
    )
    created = store.create_strategy(
        investment_id, name="Varied", root_overlays=(partnership_overlay(varied),), db_path=db
    )
    store.update_strategy(
        investment_id,
        created.strategy.strategy_id,
        name="Varied again",
        root_overlays=(partnership_overlay(renamed(varied, " twice")),),
        db_path=db,
    )
    store.set_base_partnership(investment_id, renamed(f.f1_terms(), " again"), db_path=db)
    store.create_strategy(investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db)

    listed = store.list_investment_partnerships(investment_id, db_path=db)
    assert listed.base == renamed(f.f1_terms(), " again")
    assert [entry.partnership for entry in listed.strategies] == [renamed(varied, " twice"), None]


# =============================================================================
# Doors, opt-in and lifecycle
# =============================================================================


def test_reading_a_deals_partnership_materializes_nothing(db: Path) -> None:
    deal = round_deal(db, name="Deal")

    assert store.read_deal_partnership(deal.id, db_path=db) == (None, None)
    assert table_names(db) >= set(P7_9_TABLES)
    assert partnership_rows(db) == EMPTY
    assert rows(db, "investments") == []
    with pytest.raises(DealNotFoundError):
        store.read_deal_partnership("zzz-missing", db_path=db)


def test_the_first_save_materializes_the_wrapper_and_clearing_releases_it(db: Path) -> None:
    deal = round_deal(db, name="Deal")
    assert store.set_deal_partnership(deal.id, None, db_path=db) == (None, None)
    assert rows(db, "investments") == []

    investment_id, saved = store.set_deal_partnership(deal.id, f.f1_terms(), db_path=db)
    assert investment_id is not None and saved == f.f1_terms()
    assert store.read_deal_partnership(deal.id, db_path=db) == (investment_id, f.f1_terms())
    assert store.get_investment(investment_id, db_path=db).hidden

    assert store.set_deal_partnership(deal.id, None, db_path=db) == (None, None)
    assert rows(db, "investments") == [] and partnership_rows(db) == EMPTY


def test_a_wrapper_holding_a_partnership_survives_its_last_scenario(db: Path) -> None:
    deal, investment_id = hidden(db, f.f1_terms())
    (scenario,) = store.list_scenarios(investment_id, db_path=db)

    store.delete_scenario(investment_id, scenario.scenario.scenario_id, db_path=db)

    assert store.get_base_partnership(investment_id, db_path=db) == f.f1_terms()
    store.set_base_partnership(investment_id, None, db_path=db)
    with pytest.raises(InvestmentNotFoundError):
        store.get_investment(investment_id, db_path=db)
    assert store.read_deal_partnership(deal.id, db_path=db) == (None, None)


def test_a_visible_investments_unit_has_no_partnership_door(db: Path) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)
    store.set_base_partnership(investment.id, f.f1_terms(), db_path=db)

    with pytest.raises(InvestmentStructureError, match="Investment's Partnership"):
        store.read_deal_partnership(first.id, db_path=db)
    with pytest.raises(InvestmentStructureError):
        store.set_deal_partnership(first.id, f.f7_terms(), db_path=db)
    assert store.get_base_partnership(investment.id, db_path=db) == f.f1_terms()


def test_deleting_a_strategy_removes_only_its_own_partnership(db: Path) -> None:
    _, investment_id = hidden(db, f.f1_terms())
    own = store.create_strategy(
        investment_id, name="Own", root_overlays=(partnership_overlay(f.f12_terms()),), db_path=db
    )
    none = store.create_strategy(investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db)

    store.delete_strategy(investment_id, own.strategy.strategy_id, db_path=db)
    store.delete_strategy(investment_id, none.strategy.strategy_id, db_path=db)

    assert [row[3] for row in rows(db, "partnerships")] == [investment_id]
    assert {row[1] for row in rows(db, "partners")} == {"lp", "gp"}
    assert store.get_base_partnership(investment_id, db_path=db) == f.f1_terms()


def test_deleting_an_investment_removes_every_partnership_row_and_keeps_its_deal(db: Path) -> None:
    deal, investment_id = hidden(db, f.f1_terms())
    store.create_strategy(investment_id, name="Own", root_overlays=(partnership_overlay(f.f12_terms()),), db_path=db)
    other_deal, other_id = hidden(db, f.f7_terms())

    store.delete_investment(investment_id, db_path=db)

    assert store.get_deal(deal.id, db_path=db).id == deal.id
    assert {row[3] for row in rows(db, "partnerships")} == {other_id}
    assert store.get_base_partnership(other_id, db_path=db) == f.f7_terms()
    assert other_deal.id != deal.id


def test_deleting_a_deal_removes_its_wrapper_and_partnership_rows(db: Path) -> None:
    deal, investment_id = hidden(db, f.f1_terms())
    store.create_strategy(investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db)

    store.delete_deal(deal.id, db_path=db)

    assert partnership_rows(db) == EMPTY
    with pytest.raises(InvestmentNotFoundError):
        store.get_base_partnership(investment_id, db_path=db)


def test_deleting_a_visible_investment_removes_its_partnership(db: Path) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)
    store.set_base_partnership(investment.id, f.f1_terms(), db_path=db)
    store.create_strategy(investment.id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db)

    store.delete_investment(investment.id, db_path=db)

    assert partnership_rows(db) == EMPTY


def test_promotion_keeps_the_partnership_and_its_partner_ids(db: Path) -> None:
    from _p7_6_fixtures import member, price  # type: ignore[import-not-found]
    from anchor.business_plan import BusinessPlan

    deal, investment_id = partnership_only_deal(db)
    store.set_base_partnership(investment_id, f.f1_terms(), db_path=db)
    added = quick_deal(db, name="Added")

    store.promote_hidden_investment(
        investment_id,
        name="Promoted",
        transaction_price=price(deal) + price(added),
        units=(member(deal.id, ordinal=0), member(added.id, ordinal=1)),
        business_plan=BusinessPlan(),
        db_path=db,
    )

    assert not store.get_investment(investment_id, db_path=db).hidden
    assert store.get_base_partnership(investment_id, db_path=db) == f.f1_terms()


def partnership_only_deal(db: Path) -> tuple[Any, str]:
    """A Deal whose hidden wrapper holds only a Partnership."""

    deal = quick_deal(db, name="Promotable")
    investment_id, _ = store.set_deal_partnership(deal.id, f.f7_terms(), db_path=db)
    assert investment_id is not None
    return deal, investment_id


def test_the_capital_structure_and_partnership_doors_are_independent(db: Path) -> None:
    """Clearing the structure of a Deal whose wrapper still holds a Partnership
    keeps the wrapper, and the reverse."""

    deal, investment_id = structured_deal(db, f.f1_terms())
    from anchor.capital_structure import CapitalStructure

    store.set_deal_capital_structure(deal.id, CapitalStructure(positions=()), db_path=db)
    assert store.read_deal_partnership(deal.id, db_path=db) == (investment_id, f.f1_terms())

    store.set_deal_partnership(deal.id, None, db_path=db)
    assert store.read_deal_partnership(deal.id, db_path=db) == (None, None)
    with pytest.raises(InvestmentNotFoundError):
        store.get_investment(investment_id, db_path=db)
