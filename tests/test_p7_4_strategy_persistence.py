"""Phase 7 Gate P7.4 -- Strategy persistence and the generalized wrapper
lifecycle, at the store.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 8.2 and
15.1-15.2 and the Section 21 record (Q3, Q4). Every row count is read from the
database directly, never through the store under test.

- **Opt-in only.** Reads never materialize an Investment. A standalone Deal's
  first Strategy creates the hidden wrapper; a Deal whose Scenarios already
  created one reuses it.
- **Typed and whole.** Every domain round-trips exactly through its own table;
  the explicit empty Business Plan stays distinguishable from no overlay.
- **One lifecycle for two kinds of structure.** The wrapper collapses only when
  it holds neither a Strategy nor a Scenario.
- **Transactions.** Every multi-row operation rolls back whole.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from anchor.analysis.scenario import ScenarioTarget
from anchor.analysis.strategy import (
    StrategyDefinition,
    StrategyDomain,
    StrategyIssueCode,
    StrategyValidationError,
)
from anchor.business_plan import BusinessPlan
from anchor.contracts import OperatingMode
from anchor.deals import store
from anchor.deals.contracts import (
    DealNotFoundError,
    InvestmentNotFoundError,
    InvestmentStrategy,
    InvestmentStructureError,
    InvestmentUnit,
    StrategyNotFoundError,
)

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
import _p7_4_fixtures as f4  # type: ignore[import-not-found]
from _p7_2_fixtures import (  # type: ignore[import-not-found]
    MODES,
    analyze_deal,
    create_deal,
    deal_fingerprint,
    economic_override,
    execute,
    legacy_rows,
    rows,
    update_deal,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_4.db"


#: One strategy-specific operating outcome per mode.
_OUTCOME = {
    "quick": ("noi_growth", 0.04),
    "detailed": ("revenue_growth", 0.04),
    "lease_level": ("market_rent_psf", 42.0),
}


def _overlays(mode: str, unit: str) -> tuple[Any, ...]:
    """Every domain the mode supports, valid."""

    return (
        f4.disposition(unit, 7),
        f4.outcomes(unit, f4.outcome(*_OUTCOME[mode]), f4.outcome("exit_cap_rate", 0.06)),
        f4.plan_overlay(unit, f4.renovation_plan()),
        f4.financing(unit),
        f4.acquisition(unit),
    )


def _canonical(strategy_id: str, name: str, overlays: tuple[Any, ...], description: str | None = None) -> StrategyDefinition:
    """What a stored strategy reads back as: overlays in domain order, outcomes
    in registry order."""

    order = list(StrategyDomain)
    canonical = []
    for overlay in sorted(overlays, key=lambda o: (order.index(o.domain), o.unit_id)):
        if overlay.domain is StrategyDomain.OPERATING_OUTCOME:
            ranked = tuple(sorted(overlay.content.outcomes, key=lambda o: list(ScenarioTarget).index(o.target)))
            overlay = f4.outcomes(overlay.unit_id, *ranked)
        canonical.append(overlay)
    return StrategyDefinition(strategy_id=strategy_id, name=name, description=description, overlays=tuple(canonical))


def _state(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {**legacy_rows(db), **{table: rows(db, table) for table in f4.P7_TABLES}}


def _first(mode: str, db: Path, **kwargs: Any) -> tuple[Any, InvestmentStrategy]:
    deal = create_deal(mode, db, business_plan=kwargs.pop("business_plan", BusinessPlan()))
    overlays = kwargs.pop("overlays", _overlays(mode, deal.id))
    record = store.create_strategy_for_deal(deal.id, name=kwargs.pop("name", "Renovate"), overlays=overlays, db_path=db, **kwargs)
    return deal, record


# =============================================================================
# Schema v9
# =============================================================================


def test_a_fresh_store_is_schema_9_with_every_p7_table_empty(db: Path) -> None:
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()
    # P7.6 added schema 10's visible-Investment sidecars, P7.8B schema 11's
    # Capital Structure tables and P7.9 Stage 2 schema 12's Partnership tables;
    # P7.4's own eight are still empty.
    assert version == 12
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_at_most_one_overlay_per_domain_and_unit_at_the_persistence_layer(db: Path) -> None:
    store.list_deals(db_path=db)
    execute(db, "INSERT INTO strategy_acquisition_overlays VALUES ('s', 'u', 1.0, 0.0)")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        execute(db, "INSERT INTO strategy_acquisition_overlays VALUES ('s', 'u', 2.0, 0.0)")
    execute(db, "INSERT INTO strategy_operating_outcomes VALUES ('s', 'u', 'exit_cap_rate', 'set', 0.06)")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        execute(db, "INSERT INTO strategy_operating_outcomes VALUES ('s', 'u', 'exit_cap_rate', 'set', 0.07)")
    execute(db, "INSERT INTO strategy_business_plan_overlays VALUES ('s', 'u')")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        execute(db, "INSERT INTO strategy_business_plan_overlays VALUES ('s', 'u')")


# =============================================================================
# Opt-in only (Q4) -- lifecycle oracles 1 to 5
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_ordinary_deal_workflow_and_every_strategy_read_materialize_nothing(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    saved = update_deal(deal, db, hold_period=6)
    store.get_deal(deal.id, db_path=db)
    store.list_deals(db_path=db)
    analyze_deal(saved)
    deal_fingerprint(saved)
    copy = store.duplicate_deal(deal.id, db_path=db)
    assert store.list_deal_strategies(deal.id, db_path=db) == (None, [])
    assert store.list_deal_scenarios(deal.id, db_path=db) == (None, [])
    with pytest.raises(InvestmentNotFoundError):
        store.list_strategies("0" * 32, db_path=db)
    with pytest.raises(InvestmentNotFoundError):
        store.get_strategy("0" * 32, "1" * 32, db_path=db)
    store.delete_deal(copy.id, db_path=db)

    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_listing_the_strategies_of_an_unknown_deal_is_not_found(db: Path) -> None:
    with pytest.raises(DealNotFoundError):
        store.list_deal_strategies("0" * 32, db_path=db)
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


@pytest.mark.parametrize("mode", MODES)
def test_the_first_strategy_materializes_exactly_one_hidden_investment(db: Path, mode: str) -> None:
    deal, record = _first(mode, db)

    assert f4.p7_row_counts(db) == f4.counts(
        investments=1, investment_units=1, strategies=1,
        strategy_acquisition_overlays=1, strategy_financing_overlays=1, strategy_business_plan_overlays=1,
        strategy_capital_plan_items=2, strategy_owner_expense_items=1, strategy_operating_outcomes=2,
        strategy_disposition_overlays=1,
    )
    ((investment_id, is_hidden, *_),) = rows(db, "investments")
    assert (investment_id, is_hidden) == (record.investment_id, 1)
    assert store.get_investment(record.investment_id, db_path=db).units == (InvestmentUnit(unit_id=deal.id),)
    assert store.list_deal_strategies(deal.id, db_path=db) == (record.investment_id, [record])


def test_a_strategy_reuses_the_investment_its_deals_scenarios_created(db: Path) -> None:
    deal = create_deal("quick", db)
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", overrides=(economic_override("quick", deal.id),), db_path=db)
    record = store.create_strategy_for_deal(deal.id, name="Bid low", overlays=(f4.acquisition(deal.id),), db_path=db)

    assert record.investment_id == scenario.investment_id
    assert f4.p7_row_counts(db)["investments"] == 1


def test_a_scenario_reuses_the_investment_its_deals_strategy_created(db: Path) -> None:
    deal, record = _first("detailed", db)
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", overrides=(economic_override("detailed", deal.id),), db_path=db)

    assert scenario.investment_id == record.investment_id
    assert f4.p7_row_counts(db)["investments"] == 1
    assert store.list_deal_scenarios(deal.id, db_path=db) == (record.investment_id, [scenario])


def test_further_strategies_reuse_the_wrapper_and_list_in_creation_order(db: Path) -> None:
    deal, first = _first("quick", db)
    second = store.create_strategy_for_deal(deal.id, name="Second", db_path=db)
    third = store.create_strategy(first.investment_id, name="Third", overlays=(f4.disposition(deal.id, 3),), db_path=db)

    assert f4.p7_row_counts(db)["investments"] == 1
    assert [s.strategy.name for s in store.list_strategies(first.investment_id, db_path=db)] == ["Renovate", "Second", "Third"]
    assert second.investment_id == third.investment_id == first.investment_id
    assert len({first.strategy.strategy_id, second.strategy.strategy_id, third.strategy.strategy_id}) == 3


# =============================================================================
# Lifecycle oracles 6 to 10 -- the wrapper collapses only when it holds nothing
# =============================================================================


def test_deleting_the_final_strategy_keeps_a_wrapper_that_still_holds_a_scenario(db: Path) -> None:
    deal, record = _first("quick", db)
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", db_path=db)

    store.delete_strategy(record.investment_id, record.strategy.strategy_id, db_path=db)

    assert f4.p7_row_counts(db) == f4.counts(investments=1, investment_units=1, scenarios=1)
    assert store.get_scenario(record.investment_id, scenario.scenario.scenario_id, db_path=db) == store.get_scenario(
        scenario.investment_id, scenario.scenario.scenario_id, db_path=db
    )


def test_deleting_the_final_scenario_keeps_a_wrapper_that_still_holds_a_strategy(db: Path) -> None:
    deal, record = _first("lease_level", db)
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", db_path=db)

    store.delete_scenario(scenario.investment_id, scenario.scenario.scenario_id, db_path=db)

    assert f4.p7_row_counts(db)["investments"] == 1
    assert f4.p7_row_counts(db)["scenarios"] == 0
    assert store.get_strategy(record.investment_id, record.strategy.strategy_id, db_path=db) == record


@pytest.mark.parametrize("mode", MODES)
def test_deleting_the_final_strategy_with_no_scenario_collapses_the_wrapper(db: Path, mode: str) -> None:
    deal, record = _first(mode, db)
    before = store.get_deal(deal.id, db_path=db)

    store.delete_strategy(record.investment_id, record.strategy.strategy_id, db_path=db)

    assert f4.p7_row_counts(db) == f4.P7_EMPTY
    assert store.get_deal(deal.id, db_path=db) == before
    assert store.list_deal_strategies(deal.id, db_path=db) == (None, [])


def test_deleting_one_of_two_strategies_keeps_the_wrapper(db: Path) -> None:
    deal, record = _first("quick", db)
    other = store.create_strategy_for_deal(deal.id, name="Other", db_path=db)

    store.delete_strategy(record.investment_id, record.strategy.strategy_id, db_path=db)

    assert store.list_strategies(record.investment_id, db_path=db) == [store.get_strategy(other.investment_id, other.strategy.strategy_id, db_path=db)]
    assert f4.p7_row_counts(db) == f4.counts(investments=1, investment_units=1, strategies=1)


@pytest.mark.parametrize("mode", MODES)
def test_deleting_the_deal_leaves_no_strategy_scenario_cache_or_wrapper_orphan(db: Path, mode: str) -> None:
    from anchor.deals import variants

    deal, record = _first(mode, db)
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", overrides=(economic_override(mode, deal.id),), db_path=db)
    variants.analyze_variant(record.investment_id, record.strategy.strategy_id, scenario.scenario.scenario_id, db_path=db)
    variants.analyze_variant(record.investment_id, record.strategy.strategy_id, "base", db_path=db)
    variants.analyze_scenario_variant(record.investment_id, scenario.scenario.scenario_id, db_path=db)
    bystander = create_deal(mode, db, name="Bystander")
    if mode != "lease_level":
        assert f4.p7_row_counts(db)["variant_snapshots"] == 3

    store.delete_deal(deal.id, db_path=db)

    assert f4.p7_row_counts(db) == f4.P7_EMPTY
    with pytest.raises(DealNotFoundError):
        store.get_deal(deal.id, db_path=db)
    assert store.get_deal(bystander.id, db_path=db).name == "Bystander"


@pytest.mark.parametrize("mode", MODES)
def test_deleting_the_investment_releases_the_deal(db: Path, mode: str) -> None:
    deal, record = _first(mode, db)
    store.create_scenario_for_deal(deal.id, name="Downside", db_path=db)
    before = store.get_deal(deal.id, db_path=db)

    store.delete_investment(record.investment_id, db_path=db)

    assert f4.p7_row_counts(db) == f4.P7_EMPTY
    assert store.get_deal(deal.id, db_path=db) == before


def test_duplicating_a_deal_copies_no_strategy_scenario_or_wrapper(db: Path) -> None:
    deal, record = _first("quick", db)
    store.create_scenario_for_deal(deal.id, name="Downside", db_path=db)
    state = _state(db)

    copy = store.duplicate_deal(deal.id, db_path=db)

    assert store.list_deal_strategies(copy.id, db_path=db) == (None, [])
    assert store.list_deal_scenarios(copy.id, db_path=db) == (None, [])
    assert {t: rows(db, t) for t in f4.P7_TABLES} == {t: state[t] for t in f4.P7_TABLES}
    assert store.list_strategies(record.investment_id, db_path=db) == [record]


# =============================================================================
# Round trips -- typed, exact, canonical
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_every_domain_round_trips_exactly_in_canonical_order(db: Path, mode: str) -> None:
    deal, record = _first(mode, db, description="Renovate and hold")
    overlays = _overlays(mode, deal.id)

    assert record.strategy == _canonical(record.strategy.strategy_id, "Renovate", overlays, "Renovate and hold")
    assert store.get_strategy(record.investment_id, record.strategy.strategy_id, db_path=db) == record
    assert [o.domain for o in record.strategy.overlays] == [
        StrategyDomain.ACQUISITION,
        StrategyDomain.FINANCING,
        StrategyDomain.BUSINESS_PLAN,
        StrategyDomain.OPERATING_OUTCOME,
        StrategyDomain.DISPOSITION,
    ]


def test_values_round_trip_bit_identically_and_whole_years_stay_integers(db: Path) -> None:
    deal = create_deal("quick", db)
    record = store.create_strategy_for_deal(
        deal.id, name="Exact",
        overlays=(
            f4.acquisition(deal.id, purchase_price=9_512_345.678901234, acquisition_cost_pct=0.0123456789),
            f4.financing(deal.id, ltv=0.6123456789, amortization=25.0, io_period=3),
            f4.disposition(deal.id, 7.0),
        ),
        db_path=db,
    )
    acquisition, financing, disposition = (o.content for o in record.strategy.overlays)
    assert (acquisition.purchase_price, acquisition.acquisition_cost_pct) == (9_512_345.678901234, 0.0123456789)
    assert financing.ltv == 0.6123456789
    assert (financing.amortization, financing.io_period, disposition.hold_period) == (25, 3, 7)
    assert all(type(value) is int for value in (financing.amortization, financing.io_period, disposition.hold_period))


def test_an_explicit_empty_plan_and_no_plan_overlay_stay_distinguishable(db: Path) -> None:
    deal = create_deal("quick", db, business_plan=fx.business_plan())
    kept = store.create_strategy_for_deal(deal.id, name="No plan overlay", overlays=(f4.acquisition(deal.id),), db_path=db)
    emptied = store.create_strategy_for_deal(
        deal.id, name="Executes no plan", overlays=(f4.plan_overlay(deal.id, BusinessPlan()),), db_path=db,
    )

    assert rows(db, "strategy_business_plan_overlays") == [(emptied.strategy.strategy_id, deal.id)]
    assert rows(db, "strategy_capital_plan_items") == rows(db, "strategy_owner_expense_items") == []
    reopened_kept = store.get_strategy(kept.investment_id, kept.strategy.strategy_id, db_path=db).strategy
    reopened_emptied = store.get_strategy(emptied.investment_id, emptied.strategy.strategy_id, db_path=db).strategy
    assert StrategyDomain.BUSINESS_PLAN not in {o.domain for o in reopened_kept.overlays}
    (plan_overlay,) = reopened_emptied.overlays
    assert (plan_overlay.domain, plan_overlay.content) == (StrategyDomain.BUSINESS_PLAN, BusinessPlan())


def test_a_replacement_plan_keeps_its_row_order(db: Path) -> None:
    deal = create_deal("detailed", db)
    plan = f4.renovation_plan()
    record = store.create_strategy_for_deal(deal.id, name="Plan", overlays=(f4.plan_overlay(deal.id, plan),), db_path=db)
    assert record.strategy.overlays[0].content == plan
    assert [row[2] for row in rows(db, "strategy_capital_plan_items")] == ["reno-units", "reno-amenity"]


def test_outcome_tokens_are_stored_as_wire_tokens(db: Path) -> None:
    _, record = _first("quick", db)
    assert sorted((target, operation) for _, _, target, operation, _ in rows(db, "strategy_operating_outcomes")) == [
        ("exit_cap_rate", "set"), ("noi_growth", "set"),
    ]
    assert record.strategy.overlays[3].content.outcomes[0].target is ScenarioTarget.EXIT_CAP_RATE


# =============================================================================
# The contract on the way in -- nothing partial survives
# =============================================================================


@pytest.mark.parametrize(
    ("overlay", "code"),
    [
        (lambda u: f4.financing(u, amortization=None), StrategyIssueCode.INCOMPLETE_DOMAIN),
        (lambda u: f4.acquisition("zzz-foreign"), StrategyIssueCode.UNIT_NOT_IN_VARIANT),
        (lambda u: f4.outcomes(u, f4.outcome("market_rent_psf", 40.0)), StrategyIssueCode.UNSUPPORTED_TARGET),
        (lambda u: f4.outcomes(u, f4.outcome("exit_cap_rate", 0.005, "add")), StrategyIssueCode.INVALID_OPERATION),
    ],
    ids=["partial-financing", "foreign-unit", "target-not-for-mode", "relative-operation"],
)
def test_an_invalid_first_strategy_leaves_nothing_behind(db: Path, overlay: Any, code: StrategyIssueCode) -> None:
    deal = create_deal("quick", db)
    with pytest.raises(StrategyValidationError) as caught:
        store.create_strategy_for_deal(deal.id, name="Bad", overlays=(overlay(deal.id),), db_path=db)
    assert [issue.code for issue in caught.value.issues] == [code]
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_a_blank_name_is_refused_and_leaves_nothing_behind(db: Path) -> None:
    deal = create_deal("quick", db)
    with pytest.raises(StrategyValidationError):
        store.create_strategy_for_deal(deal.id, name="  ", db_path=db)
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_a_strategy_for_an_unknown_deal_is_not_found(db: Path) -> None:
    with pytest.raises(DealNotFoundError):
        store.create_strategy_for_deal("0" * 32, name="S", db_path=db)
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_structurally_valid_but_financially_invalid_strategies_are_stored(db: Path) -> None:
    """Variant validity is decided at resolution, where the Base and the
    Scenario are known -- never by refusing to store the strategy."""

    deal = create_deal("quick", db)
    record = store.create_strategy_for_deal(deal.id, name="Odd", overlays=(f4.acquisition(deal.id, purchase_price=-1.0),), db_path=db)
    assert record.strategy.overlays[0].content.purchase_price == -1.0


# =============================================================================
# Update and delete semantics
# =============================================================================


def test_an_update_keeps_the_id_and_replaces_the_overlay_set_whole(db: Path) -> None:
    deal, record = _first("quick", db)
    key = (record.investment_id, record.strategy.strategy_id)

    updated = store.update_strategy(*key, name="Hold only", description="Just hold", overlays=(f4.disposition(deal.id, 10),), db_path=db)

    assert updated.strategy == StrategyDefinition(
        strategy_id=record.strategy.strategy_id, name="Hold only", description="Just hold",
        overlays=(f4.disposition(deal.id, 10),),
    )
    assert f4.p7_row_counts(db) == f4.counts(investments=1, investment_units=1, strategies=1, strategy_disposition_overlays=1)
    assert updated.created_at == record.created_at


def test_an_invalid_update_leaves_the_previous_strategy_exactly_as_it_was(db: Path) -> None:
    deal, record = _first("quick", db)
    state = _state(db)
    with pytest.raises(StrategyValidationError):
        store.update_strategy(
            record.investment_id, record.strategy.strategy_id, name="Broken",
            overlays=(f4.financing(deal.id, ltv=None),), db_path=db,
        )
    assert _state(db) == state


def test_a_strategy_is_reachable_only_through_the_investment_that_owns_it(db: Path) -> None:
    _, mine = _first("quick", db)
    _, theirs = _first("quick", db)
    foreign = (mine.investment_id, theirs.strategy.strategy_id)
    state = _state(db)

    with pytest.raises(StrategyNotFoundError):
        store.get_strategy(*foreign, db_path=db)
    with pytest.raises(StrategyNotFoundError):
        store.update_strategy(*foreign, name="Hijack", db_path=db)
    with pytest.raises(StrategyNotFoundError):
        store.delete_strategy(*foreign, db_path=db)
    with pytest.raises(StrategyNotFoundError):
        store.get_strategy(mine.investment_id, "base", db_path=db)
    assert _state(db) == state


def test_a_visible_investment_is_refused_everywhere(db: Path) -> None:
    """Re-pinned at P7.6: once the wrapper is promoted to a visible Investment,
    its Strategies are managed through the Investment (P7.6 tests). Every
    Deal-scoped P7.4 path stays refused and changes nothing."""

    from anchor.business_plan import BusinessPlan

    from anchor.investment import InvestmentUnitMembership, UnitKind

    deal, record = _first("quick", db)
    assert deal.inputs is not None
    store.promote_hidden_investment(
        record.investment_id,
        name="Visible",
        transaction_price=deal.inputs.purchase_price,
        units=(
            InvestmentUnitMembership(
                unit_id=deal.id, ordinal=0, label=None, unit_kind=UnitKind.PROPERTY,
                acquisition_month=0, disposition_month=None,
            ),
        ),
        business_plan=BusinessPlan(),
        db_path=db,
    )
    key = (record.investment_id, record.strategy.strategy_id)
    state = _state(db)

    for call in (
        lambda: store.create_strategy_for_deal(deal.id, name="S", db_path=db),
        lambda: store.list_deal_strategies(deal.id, db_path=db),
        lambda: store.delete_deal(deal.id, db_path=db),
    ):
        with pytest.raises(InvestmentStructureError):
            call()
    assert _state(db) == state
    assert store.get_strategy(*key, db_path=db).strategy == record.strategy


# =============================================================================
# Fail closed on read
# =============================================================================


@pytest.mark.parametrize(
    "corruption",
    [
        "UPDATE strategy_operating_outcomes SET operation = 'add'",
        "UPDATE strategy_operating_outcomes SET target = 'purchase_price' WHERE target = 'noi_growth'",
        "UPDATE strategy_operating_outcomes SET target = 'market_rent_psf' WHERE target = 'noi_growth'",
        "UPDATE strategies SET name = '   '",
        "UPDATE strategy_financing_overlays SET unit_id = 'zzz-foreign'",
    ],
)
def test_a_stored_strategy_that_no_longer_validates_fails_closed(db: Path, corruption: str) -> None:
    _, record = _first("quick", db)
    execute(db, corruption)
    with pytest.raises(store.PersistedStrategyDataError) as caught:
        store.get_strategy(record.investment_id, record.strategy.strategy_id, db_path=db)
    assert caught.value.issues
    with pytest.raises(store.PersistedStrategyDataError):
        store.list_strategies(record.investment_id, db_path=db)


def test_a_plan_item_without_its_overlay_marker_is_corrupt(db: Path) -> None:
    _, record = _first("quick", db)
    execute(db, "DELETE FROM strategy_business_plan_overlays")
    with pytest.raises(store.PersistedDealDataError, match="no Business Plan overlay"):
        store.get_strategy(record.investment_id, record.strategy.strategy_id, db_path=db)


def test_an_undecodable_plan_item_is_corrupt(db: Path) -> None:
    _, record = _first("quick", db)
    execute(db, "UPDATE strategy_capital_plan_items SET category = 'contingency'")
    with pytest.raises(store.PersistedDealDataError, match="Business Plan overlay"):
        store.get_strategy(record.investment_id, record.strategy.strategy_id, db_path=db)


# =============================================================================
# Transactions -- every multi-row operation rolls back whole
# =============================================================================


def _fail_after(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    real = getattr(store, name)

    def failing(*args: Any, **kwargs: Any) -> Any:
        real(*args, **kwargs)
        raise RuntimeError(f"injected failure after {name}")

    monkeypatch.setattr(store, name, failing)


def test_a_failed_first_strategy_leaves_no_wrapper_and_no_partial_overlay(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal = create_deal("quick", db)
    _fail_after(monkeypatch, "_write_strategy_overlays")
    with pytest.raises(RuntimeError, match="injected"):
        store.create_strategy_for_deal(deal.id, name="S", overlays=_overlays("quick", deal.id), db_path=db)
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_a_failed_update_leaves_the_previous_strategy(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal, record = _first("quick", db)
    state = _state(db)
    _fail_after(monkeypatch, "_write_strategy_overlays")
    with pytest.raises(RuntimeError, match="injected"):
        store.update_strategy(record.investment_id, record.strategy.strategy_id, name="New", overlays=(f4.disposition(deal.id, 3),), db_path=db)
    assert _state(db) == state


def test_a_failed_delete_leaves_the_strategy(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal, record = _first("quick", db)
    store.create_strategy_for_deal(deal.id, name="Other", db_path=db)
    state = _state(db)
    _fail_after(monkeypatch, "_delete_strategy_overlay_rows")
    with pytest.raises(RuntimeError, match="injected"):
        store.delete_strategy(record.investment_id, record.strategy.strategy_id, db_path=db)
    assert _state(db) == state


def test_a_failed_wrapper_collapse_leaves_everything(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, record = _first("quick", db)
    state = _state(db)
    _fail_after(monkeypatch, "_delete_investment_rows")
    with pytest.raises(RuntimeError, match="injected"):
        store.delete_strategy(record.investment_id, record.strategy.strategy_id, db_path=db)
    assert _state(db) == state


def test_a_failed_deal_delete_leaves_the_deal_and_its_structure(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal, _ = _first("detailed", db)
    store.create_scenario_for_deal(deal.id, name="Downside", db_path=db)
    state = _state(db)
    _fail_after(monkeypatch, "_delete_investment_rows")
    with pytest.raises(RuntimeError, match="injected"):
        store.delete_deal(deal.id, db_path=db)
    assert _state(db) == state


def test_a_failed_investment_delete_leaves_everything(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal, record = _first("lease_level", db)
    store.create_scenario_for_deal(deal.id, name="Downside", db_path=db)
    state = _state(db)
    _fail_after(monkeypatch, "_delete_investment_rows")
    with pytest.raises(RuntimeError, match="injected"):
        store.delete_investment(record.investment_id, db_path=db)
    assert _state(db) == state


# =============================================================================
# The mode is the Deal's own
# =============================================================================


def test_a_strategy_is_validated_for_its_deals_own_mode(db: Path) -> None:
    for mode, allowed, refused in (
        ("quick", "noi_growth", "revenue_growth"),
        ("detailed", "vacancy_credit_loss_pct", "noi_growth"),
        ("lease_level", "renewal_probability", "vacancy_credit_loss_pct"),
    ):
        deal = create_deal(mode, db)
        store.create_strategy_for_deal(deal.id, name="Ok", overlays=(f4.outcomes(deal.id, f4.outcome(allowed, 0.05)),), db_path=db)
        with pytest.raises(StrategyValidationError):
            store.create_strategy_for_deal(deal.id, name="No", overlays=(f4.outcomes(deal.id, f4.outcome(refused, 0.05)),), db_path=db)
        assert store.get_deal(deal.id, db_path=db).operating_mode is OperatingMode(mode)
