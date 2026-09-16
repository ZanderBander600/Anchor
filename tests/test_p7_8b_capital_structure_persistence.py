"""Phase 7 Gate P7.8B -- Capital Structure persistence, at the store.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 15.1-15.2
and the Section 21 record (Q3, Q4), and
``docs/architecture/P7_8_PRODUCT_INTEGRATION.md``. Every row count is read from
the database directly, never through the store under test.

- **Opt-in only.** Reads never materialize an Investment; the first non-empty
  save does, and clearing the last structure releases the Deal again.
- **Marker semantics.** No Strategy row means *inherit the Base structure*; a
  Strategy row with no position means *explicitly no structured capital*. The
  two are different states from the wire down to the table and back.
- **Typed and exact.** Every field of every P7.7 contract round-trips through
  its own column, floats bit-identically.
- **Fail closed.** Stored data that cannot recreate its authoritative contract
  raises; it is never repaired and never read as an empty structure.
- **Whole-structure atomic replacement.** A refused save leaves the previous
  stack exactly as it was.

The schema-v10 -> v11 migration oracle lives with the compatibility oracles
(``tests/test_p7_8_compatibility_oracle.py``), which build a real v10 database
from the ``a9f9b09`` tree and prove the six tables appear empty, no legacy row
moves and every recorded response stays identical.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from _p7_2_fixtures import P7_8_TABLES, create_deal, execute, rows, table_names  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, member, quick_deal  # type: ignore[import-not-found]
from _p7_7_fixtures import fee, funding, unit_scope  # type: ignore[import-not-found]
from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain
from anchor.capital_structure.contracts import (
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureValidationError,
    DebtTerms,
    FixedAmount,
    FundingEvent,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    PositionScope,
    PreferredEquityTerms,
    ScopeKind,
    ShortfallResolution,
)
from anchor.deals import store
from anchor.deals.contracts import DealNotFoundError, InvestmentStructureError
from anchor.deals.position_identity import (
    PositionIdentityConflictError,
    PositionIdentityIssueCode,
)
from anchor.deals.store import PersistedCapitalStructureDataError

EMPTY = CapitalStructure(positions=())
INVESTMENT_SCOPE = PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


# =============================================================================
# Builders -- every class, both scopes, every amount rule and both term variants
# =============================================================================


def senior(unit_id: str, *, priority: int = 2) -> CapitalPosition:
    return CapitalPosition(
        position_id="senior-a",
        name="Senior Loan",
        position_class=PositionClass.SENIOR_DEBT,
        priority=priority,
        scope=unit_scope(unit_id),
        funding=(funding("senior-f", rule=PctOfPrice(pct=0.55)),),
        terms=DebtTerms(
            interest_rate=0.0625,
            amortization=30,
            io_period=2,
            maturity_month=84,
            fees=(fee("senior-fee", amount=12_345.67),),
            current_pay_rate=0.0625,
            pik_rate=0.0,
        ),
        shortfall_resolution=ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
    )


def mezz(unit_id: str, **overrides: Any) -> CapitalPosition:
    stated: dict[str, Any] = {
        "position_id": "mezz-a",
        "name": "Mezzanine",
        "position_class": PositionClass.MEZZANINE_DEBT,
        "priority": 3,
        "scope": unit_scope(unit_id),
        "funding": (funding("mezz-f", rule=FixedAmount(amount=1_234_567.89)),),
        "terms": DebtTerms(
            interest_rate=0.1225,
            amortization=25,
            io_period=1,
            maturity_month=48,
            fees=(),
            current_pay_rate=0.1225,
            pik_rate=0.0,
        ),
        "shortfall_resolution": ShortfallResolution.UNRESOLVED,
    }
    stated.update(overrides)
    return CapitalPosition(**stated)


def preferred(unit_id: str, **overrides: Any) -> CapitalPosition:
    stated: dict[str, Any] = {
        "position_id": "pref-a",
        "name": "Preferred Equity",
        "position_class": PositionClass.PREFERRED_EQUITY,
        "priority": 4,
        "scope": unit_scope(unit_id),
        "funding": (funding("pref-f", rule=FixedAmount(amount=750_000.5)),),
        "terms": PreferredEquityTerms(
            preferred_rate=0.13,
            current_pay_rate=0.08,
            accrual_permitted=True,
            accrual_convention=AccrualConvention.ANNUAL_COMPOUND,
            redemption_month=60,
        ),
        "shortfall_resolution": ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
    }
    stated.update(overrides)
    return CapitalPosition(**stated)


def marker(unit_id: str | None = None, *, position_id: str = "common-a") -> CapitalPosition:
    return CapitalPosition(
        position_id=position_id,
        name="Common Equity",
        position_class=PositionClass.COMMON_EQUITY,
        priority=9,
        scope=INVESTMENT_SCOPE if unit_id is None else unit_scope(unit_id),
        funding=(),
        terms=None,
        shortfall_resolution=None,
    )


def full(unit_id: str) -> CapitalStructure:
    return CapitalStructure(
        positions=(senior(unit_id), mezz(unit_id), preferred(unit_id), marker(unit_id))
    )


def overlay(structure: CapitalStructure) -> InvestmentStrategyOverlay:
    return InvestmentStrategyOverlay(
        domain=StrategyDomain.CAPITAL_STRUCTURE, content=structure
    )


def capital_rows(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {table: rows(db, table) for table in P7_8_TABLES}


EMPTY_ROWS = dict.fromkeys(P7_8_TABLES, [])


# =============================================================================
# The schema
# =============================================================================


def test_a_fresh_store_is_schema_11_with_six_empty_capital_tables(db: Path) -> None:
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    columns = {
        table: [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        for table in P7_8_TABLES
    }
    connection.close()

    assert version == 11
    assert set(P7_8_TABLES) <= table_names(db)
    assert capital_rows(db) == EMPTY_ROWS
    assert columns == {
        "capital_structures": ["structure_id", "investment_id", "owner_kind", "owner_id"],
        "capital_positions": [
            "structure_id", "position_id", "ordinal", "name", "position_class", "priority",
            "scope_kind", "scope_unit_id", "shortfall_resolution",
        ],
        "capital_funding_events": [
            "structure_id", "position_id", "event_id", "model_month", "sequence", "amount_rule",
            "amount", "pct", "timepoint_id",
        ],
        "capital_position_fees": [
            "structure_id", "position_id", "fee_id", "description", "amount", "model_month",
            "sequence",
        ],
        "capital_debt_terms": [
            "structure_id", "position_id", "interest_rate", "amortization", "io_period",
            "maturity_month", "current_pay_rate", "pik_rate",
        ],
        "capital_preferred_terms": [
            "structure_id", "position_id", "preferred_rate", "current_pay_rate",
            "accrual_permitted", "accrual_convention", "redemption_month",
        ],
    }


def test_one_structure_per_owner_at_the_persistence_layer(db: Path) -> None:
    """One owner states at most one structure, enforced by SQLite as well as by
    the lifecycle: a second row for the same owner is unwritable."""

    store.list_deals(db_path=db)
    execute(db, "INSERT INTO capital_structures VALUES ('s1', 'i1', 'base', 'i1')")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        execute(db, "INSERT INTO capital_structures VALUES ('s2', 'i1', 'base', 'i1')")


def test_a_position_id_is_owner_scoped_and_repeats_across_structures(db: Path) -> None:
    """The same ``position_id`` is *meant* to appear in the Base structure and in
    a Strategy's own -- that is what makes POSITION(position_id) a comparison --
    so the key is (structure, position), never the position alone."""

    store.list_deals(db_path=db)
    execute(db, "INSERT INTO capital_structures VALUES ('s1', 'i1', 'base', 'i1')")
    execute(db, "INSERT INTO capital_structures VALUES ('s2', 'i1', 'strategy', 'st1')")
    values = "'mezz-a', 0, 'Mezz', 'mezzanine_debt', 2, 'unit', 'u1', 'unresolved'"
    execute(db, f"INSERT INTO capital_positions VALUES ('s1', {values})")
    execute(db, f"INSERT INTO capital_positions VALUES ('s2', {values})")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        execute(db, f"INSERT INTO capital_positions VALUES ('s1', {values})")


# =============================================================================
# The hidden Deal opt-in lifecycle
# =============================================================================


def test_reading_a_standalone_deals_structure_creates_nothing(db: Path) -> None:
    deal = create_deal("quick", db)

    investment_id, structure = store.read_deal_capital_structure(deal.id, db_path=db)

    assert (investment_id, structure) == (None, EMPTY)
    assert rows(db, "investments") == []
    assert capital_rows(db) == EMPTY_ROWS


def test_saving_an_empty_structure_for_a_standalone_deal_creates_nothing(db: Path) -> None:
    deal = create_deal("quick", db)

    assert store.set_deal_capital_structure(deal.id, EMPTY, db_path=db) == (None, EMPTY)
    assert rows(db, "investments") == []
    assert capital_rows(db) == EMPTY_ROWS


def test_the_first_non_empty_save_materializes_the_hidden_wrapper(db: Path) -> None:
    deal = create_deal("quick", db)

    investment_id, saved = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)

    assert investment_id is not None and saved == full(deal.id)
    assert [row[0] for row in rows(db, "investment_units")] == [investment_id]
    assert len(rows(db, "capital_positions")) == 4
    assert store.get_investment(investment_id, db_path=db).hidden is True


def test_clearing_the_last_structure_releases_the_deal(db: Path) -> None:
    """P-11: empty advanced structure leaves no state behind. The Deal is a
    plain standalone Deal again, unchanged."""

    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)

    assert store.set_deal_capital_structure(deal.id, EMPTY, db_path=db) == (None, EMPTY)
    assert rows(db, "investments") == [] and rows(db, "investment_units") == []
    assert capital_rows(db) == EMPTY_ROWS
    assert store.get_deal(deal.id, db_path=db) == deal


def test_a_wrapper_holding_a_scenario_survives_clearing_its_structure(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None
    store.create_scenario(investment_id, name="Downside", db_path=db)

    store.set_deal_capital_structure(deal.id, EMPTY, db_path=db)

    assert len(rows(db, "investments")) == 1
    assert store.get_base_capital_structure(investment_id, db_path=db) == EMPTY


def test_deleting_the_deal_takes_its_hidden_wrapper_and_every_capital_row(db: Path) -> None:
    deal = create_deal("quick", db)
    store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)

    store.delete_deal(deal.id, db_path=db)

    assert rows(db, "investments") == [] and capital_rows(db) == EMPTY_ROWS
    with pytest.raises(DealNotFoundError):
        store.get_deal(deal.id, db_path=db)


def test_a_unit_of_a_visible_investment_is_refused_its_own_structure(db: Path) -> None:
    """One owner type (Section 15.1): a Unit never holds a second structure, and
    the refusal says where the Investment's own lives."""

    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)

    with pytest.raises(InvestmentStructureError, match="Unit of a visible Investment"):
        store.read_deal_capital_structure(first.id, db_path=db)
    with pytest.raises(InvestmentStructureError):
        store.set_deal_capital_structure(first.id, full(first.id), db_path=db)
    assert store.get_base_capital_structure(investment.id, db_path=db) == EMPTY


# =============================================================================
# Round trips -- typed, exact, canonical
# =============================================================================


def test_every_class_scope_rule_and_term_variant_round_trips_exactly(db: Path) -> None:
    deal = create_deal("quick", db)
    investment = create_investment(db, deal)
    structure = CapitalStructure(
        positions=(
            senior(deal.id),
            mezz(deal.id),
            preferred(deal.id),
            CapitalPosition(
                position_id="inv-pref",
                name="Investment Preferred",
                position_class=PositionClass.PREFERRED_EQUITY,
                priority=1,
                scope=INVESTMENT_SCOPE,
                funding=(
                    funding("inv-pref-f", rule=PctOfPrice(pct=0.1)),
                    funding("inv-pref-f2", sequence=2, rule=FixedAmount(amount=10.5)),
                ),
                terms=PreferredEquityTerms(
                    preferred_rate=0.11,
                    current_pay_rate=0.11,
                    accrual_permitted=False,
                    accrual_convention=None,
                    redemption_month=60,
                ),
                shortfall_resolution=ShortfallResolution.UNRESOLVED,
            ),
            marker(),
        )
    )

    store.set_base_capital_structure(investment.id, structure, db_path=db)

    assert store.get_base_capital_structure(investment.id, db_path=db) == structure


def test_values_round_trip_bit_identically(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None

    stored = store.get_base_capital_structure(investment_id, db_path=db)

    by_id = {position.position_id: position for position in stored.positions}
    debt = by_id["senior-a"].terms
    assert isinstance(debt, DebtTerms)
    assert debt.interest_rate == 0.0625 and debt.fees[0].amount == 12_345.67
    assert isinstance(debt.amortization, int) and isinstance(debt.maturity_month, int)
    rule = by_id["mezz-a"].funding[0].amount_rule
    assert isinstance(rule, FixedAmount) and rule.amount == 1_234_567.89
    pref = by_id["pref-a"].terms
    assert isinstance(pref, PreferredEquityTerms)
    assert pref.preferred_rate == 0.13 and pref.accrual_permitted is True
    assert pref.accrual_convention is AccrualConvention.ANNUAL_COMPOUND
    assert by_id["common-a"].terms is None and by_id["common-a"].shortfall_resolution is None


def test_a_pct_of_value_funding_round_trips_although_no_gate_values_it(db: Path) -> None:
    """Persistence represents every current P7.7 contract, so a structure that
    holds one is stored and restored exactly. Nothing values it: the executor
    still refuses it, and the authoring API never writes one."""

    deal = create_deal("quick", db)
    investment = create_investment(db, deal)
    valued = mezz(
        deal.id,
        funding=(
            FundingEvent(
                event_id="mezz-f",
                model_month=0,
                sequence=1,
                amount_rule=PctOfValue(timepoint_id="stabilized", pct=0.25),
            ),
        ),
    )
    structure = CapitalStructure(positions=(valued,))

    store.set_base_capital_structure(investment.id, structure, db_path=db)

    assert store.get_base_capital_structure(investment.id, db_path=db) == structure


def test_the_structure_survives_closing_and_reopening_the_database(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None

    connection = sqlite3.connect(db)
    connection.close()

    assert store.get_base_capital_structure(investment_id, db_path=db) == full(deal.id)


# =============================================================================
# Marker semantics -- inherit, explicit empty, and none
# =============================================================================


def test_a_strategy_states_no_structure_and_inherits_the_base(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None

    record = store.create_strategy(investment_id, name="Inherit", db_path=db)

    assert record.strategy.root_overlays == ()
    assert rows(db, "capital_structures") == [
        row for row in rows(db, "capital_structures") if row[2] == "base"
    ]


def test_a_strategy_states_an_explicit_empty_structure(db: Path) -> None:
    """The distinction the whole gate turns on: a marker with no position is
    'this Strategy deliberately uses no structured capital', which is not
    'inherit the Base structure'."""

    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None

    record = store.create_strategy(
        investment_id, name="No structure", root_overlays=(overlay(EMPTY),), db_path=db
    )
    reread = store.get_strategy(investment_id, record.strategy.strategy_id, db_path=db)

    assert reread.strategy.root_overlays == (overlay(EMPTY),)
    owners = sorted(row[2] for row in rows(db, "capital_structures"))
    assert owners == ["base", "strategy"]
    assert len([row for row in rows(db, "capital_positions") if row[0]]) == 4


def test_the_base_marker_is_never_stored_empty(db: Path) -> None:
    """Clearing the Base structure removes its marker. An empty Base marker is
    therefore never written -- and a database that holds one is corrupt, not an
    empty Base."""

    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None
    store.create_scenario(investment_id, name="Downside", db_path=db)
    store.set_base_capital_structure(investment_id, EMPTY, db_path=db)

    assert rows(db, "capital_structures") == []
    execute(
        db,
        "INSERT INTO capital_structures VALUES ('fake', ?, 'base', ?)",
        (investment_id, investment_id),
    )
    with pytest.raises(PersistedCapitalStructureDataError, match="no position"):
        store.get_base_capital_structure(investment_id, db_path=db)


def test_updating_a_strategy_without_root_overlays_returns_it_to_inheriting(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None
    record = store.create_strategy(
        investment_id,
        name="Own",
        root_overlays=(overlay(CapitalStructure(positions=(mezz(deal.id),))),),
        db_path=db,
    )

    updated = store.update_strategy(
        investment_id, record.strategy.strategy_id, name="Own", db_path=db
    )

    assert updated.strategy.root_overlays == ()
    assert [row[2] for row in rows(db, "capital_structures")] == ["base"]


# =============================================================================
# Whole-structure atomic replacement
# =============================================================================


def test_a_refused_save_leaves_the_previous_stack_exactly_as_it_was(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None
    before = capital_rows(db)

    duplicated = CapitalStructure(positions=(mezz(deal.id), mezz(deal.id)))
    with pytest.raises(CapitalStructureValidationError):
        store.set_base_capital_structure(investment_id, duplicated, db_path=db)

    assert capital_rows(db) == before
    assert store.get_base_capital_structure(investment_id, db_path=db) == full(deal.id)


def test_a_replacement_removes_every_row_of_the_previous_structure(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None

    store.set_base_capital_structure(
        investment_id, CapitalStructure(positions=(mezz(deal.id),)), db_path=db
    )

    assert len(rows(db, "capital_positions")) == 1
    assert rows(db, "capital_preferred_terms") == [] and rows(db, "capital_position_fees") == []
    assert len(rows(db, "capital_structures")) == 1


# =============================================================================
# Fail closed
# =============================================================================


@pytest.mark.parametrize(
    ("sql", "match"),
    [
        ("UPDATE capital_positions SET position_class = 'junk'", "position_class"),
        ("UPDATE capital_positions SET scope_kind = 'portfolio'", "scope_kind"),
        ("UPDATE capital_positions SET shortfall_resolution = 'maybe'", "shortfall_resolution"),
        ("UPDATE capital_funding_events SET amount_rule = 'pct_of_moon'", "amount rule"),
        ("UPDATE capital_funding_events SET amount = NULL", "funding, whose columns"),
        ("UPDATE capital_preferred_terms SET accrual_convention = 'weekly'", "accrual_convention"),
        ("DELETE FROM capital_debt_terms", "carries no debt terms"),
    ],
)
def test_malformed_stored_data_raises_rather_than_reading_as_something_else(
    db: Path, sql: str, match: str
) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None

    execute(db, sql)

    with pytest.raises(PersistedCapitalStructureDataError, match=match):
        store.get_base_capital_structure(investment_id, db_path=db)


def test_an_orphaned_child_row_never_implies_a_position(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None
    structure_id = rows(db, "capital_structures")[0][0]

    execute(
        db,
        "INSERT INTO capital_funding_events VALUES (?, 'ghost', 'ghost-f', 0, 1, 'fixed_amount', 1.0, NULL, NULL)",
        (structure_id,),
    )

    with pytest.raises(PersistedCapitalStructureDataError, match="ghost"):
        store.get_base_capital_structure(investment_id, db_path=db)


def test_a_stored_structure_that_no_longer_validates_fails_closed(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None

    execute(db, "UPDATE capital_positions SET priority = -1 WHERE position_id = 'mezz-a'")

    with pytest.raises(PersistedCapitalStructureDataError, match="does not validate"):
        store.get_base_capital_structure(investment_id, db_path=db)


# =============================================================================
# One position identity across an Investment (P-8)
# =============================================================================


def test_the_same_position_id_may_not_change_class_across_structures(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(
        deal.id, CapitalStructure(positions=(mezz(deal.id),)), db_path=db
    )
    assert investment_id is not None

    conflicting = preferred(deal.id, position_id="mezz-a", priority=3)
    with pytest.raises(PositionIdentityConflictError) as refused:
        store.create_strategy(
            investment_id,
            name="Recut",
            root_overlays=(overlay(CapitalStructure(positions=(conflicting,))),),
            db_path=db,
        )

    (issue,) = refused.value.issues
    assert issue.code is PositionIdentityIssueCode.POSITION_CLASS_CONFLICT
    assert issue.position_id == "mezz-a"
    assert rows(db, "strategies") == []


def test_the_same_position_id_may_not_change_scope_across_structures(db: Path) -> None:
    deal = create_deal("quick", db)
    investment = create_investment(db, deal)
    store.set_base_capital_structure(
        investment.id, CapitalStructure(positions=(mezz(deal.id),)), db_path=db
    )

    with pytest.raises(PositionIdentityConflictError) as refused:
        store.create_strategy(
            investment.id,
            name="Holdco",
            root_overlays=(
                overlay(CapitalStructure(positions=(mezz(deal.id, scope=INVESTMENT_SCOPE),))),
            ),
            db_path=db,
        )

    (issue,) = refused.value.issues
    assert issue.code is PositionIdentityIssueCode.POSITION_SCOPE_CONFLICT


def test_the_same_instrument_may_differ_in_every_other_term(db: Path) -> None:
    """Terms, funding, priority, the name and the resolution are exactly what a
    Strategy is for. Only the class and the scope are identity."""

    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(
        deal.id, CapitalStructure(positions=(mezz(deal.id),)), db_path=db
    )
    assert investment_id is not None
    recut = mezz(
        deal.id,
        name="Mezzanine (stretch)",
        priority=5,
        funding=(funding("mezz-f", rule=FixedAmount(amount=2_000_000.0)),),
        terms=DebtTerms(
            interest_rate=0.15,
            amortization=30,
            io_period=3,
            maturity_month=60,
            fees=(fee("mezz-fee", amount=25_000.0),),
            current_pay_rate=0.15,
            pik_rate=0.0,
        ),
        shortfall_resolution=ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
    )

    record = store.create_strategy(
        investment_id,
        name="Stretch",
        root_overlays=(overlay(CapitalStructure(positions=(recut,))),),
        db_path=db,
    )

    assert record.strategy.root_overlays[0].content.positions == (recut,)


# =============================================================================
# Lifecycle across Strategies, Investments and Units
# =============================================================================


def test_deleting_a_strategy_deletes_only_its_own_structure(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, full(deal.id), db_path=db)
    assert investment_id is not None
    record = store.create_strategy(
        investment_id,
        name="Own",
        root_overlays=(overlay(CapitalStructure(positions=(mezz(deal.id),))),),
        db_path=db,
    )

    store.delete_strategy(investment_id, record.strategy.strategy_id, db_path=db)

    assert [row[2] for row in rows(db, "capital_structures")] == ["base"]
    assert store.get_base_capital_structure(investment_id, db_path=db) == full(deal.id)


def test_deleting_an_investment_deletes_every_structure_and_releases_its_deals(db: Path) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)
    store.set_base_capital_structure(
        investment.id, CapitalStructure(positions=(mezz(first.id),)), db_path=db
    )
    store.create_strategy(
        investment.id,
        name="Own",
        root_overlays=(overlay(CapitalStructure(positions=(mezz(first.id, priority=4),))),),
        db_path=db,
    )

    store.delete_investment(investment.id, db_path=db)

    assert capital_rows(db) == EMPTY_ROWS
    assert store.get_deal(first.id, db_path=db) == first
    assert store.get_deal(second.id, db_path=db) == second


def test_a_unit_a_capital_position_is_scoped_to_cannot_be_removed(db: Path) -> None:
    """P7.6's Unit-removal safety, extended: the refusal names the position and
    the structure by their display names, never by an opaque id, and nothing is
    deleted or reassigned."""

    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)
    store.set_base_capital_structure(
        investment.id, CapitalStructure(positions=(mezz(second.id),)), db_path=db
    )
    store.create_strategy(
        investment.id,
        name="Value-Add",
        root_overlays=(
            overlay(CapitalStructure(positions=(mezz(second.id, priority=4),))),
        ),
        db_path=db,
    )
    before = capital_rows(db)

    with pytest.raises(InvestmentStructureError) as refused:
        store.remove_investment_unit(investment.id, second.id, db_path=db)

    message = str(refused.value)
    assert "Capital Structure position 'Mezzanine'" in message
    assert "the Base Capital Structure" in message
    assert "Strategy 'Value-Add'" in message
    assert second.id not in message.replace(f"Unit {second.id!r}", "")
    assert capital_rows(db) == before
    assert len(store.get_visible_investment(investment.id, db_path=db).units) == 2


def test_removing_the_references_lets_the_unit_go(db: Path) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)
    store.set_base_capital_structure(
        investment.id, CapitalStructure(positions=(mezz(second.id),)), db_path=db
    )

    store.set_base_capital_structure(
        investment.id, CapitalStructure(positions=(mezz(first.id),)), db_path=db
    )
    remaining = store.remove_investment_unit(
        investment.id, second.id, transaction_price=first.inputs.purchase_price, db_path=db
    )

    assert [membership.unit_id for membership in remaining.units] == [first.id]
    assert store.get_deal(second.id, db_path=db) == second


# =============================================================================
# Promotion
# =============================================================================


def test_promotion_keeps_the_structures_and_their_position_ids(db: Path) -> None:
    deal = quick_deal(db, name="A")
    second = quick_deal(db, name="B")
    investment_id, _ = store.set_deal_capital_structure(
        deal.id, CapitalStructure(positions=(mezz(deal.id),)), db_path=db
    )
    assert investment_id is not None
    record = store.create_strategy(
        investment_id,
        name="Own",
        root_overlays=(overlay(CapitalStructure(positions=(mezz(deal.id, priority=4),))),),
        db_path=db,
    )

    store.promote_hidden_investment(
        investment_id,
        name="Portfolio",
        transaction_price=deal.inputs.purchase_price + second.inputs.purchase_price,
        units=(member(deal.id, ordinal=0), member(second.id, ordinal=1)),
        business_plan=store.get_deal(deal.id, db_path=db).business_plan.__class__(),
        db_path=db,
    )

    assert store.get_base_capital_structure(investment_id, db_path=db).positions[0].position_id == "mezz-a"
    kept = store.get_strategy(investment_id, record.strategy.strategy_id, db_path=db)
    assert kept.strategy.root_overlays[0].content.positions[0].position_id == "mezz-a"


def test_promotion_refuses_a_unit_scoped_common_equity_marker(db: Path) -> None:
    """A hidden one-unit executor names its residual at Unit scope; a visible
    Investment's residual is the Investment's. Promotion never rewrites a stored
    financial contract, so it refuses and says what to change."""

    deal = quick_deal(db, name="A")
    second = quick_deal(db, name="B")
    investment_id, _ = store.set_deal_capital_structure(
        deal.id, CapitalStructure(positions=(mezz(deal.id), marker(deal.id))), db_path=db
    )
    assert investment_id is not None
    before = capital_rows(db)

    with pytest.raises(InvestmentStructureError) as refused:
        store.promote_hidden_investment(
            investment_id,
            name="Portfolio",
            transaction_price=deal.inputs.purchase_price + second.inputs.purchase_price,
            units=(member(deal.id, ordinal=0), member(second.id, ordinal=1)),
            business_plan=store.get_deal(deal.id, db_path=db).business_plan.__class__(),
            db_path=db,
        )

    message = str(refused.value)
    assert "Common Equity" in message and "Investment scope" in message
    assert capital_rows(db) == before
    assert store.get_investment(investment_id, db_path=db).hidden is True
