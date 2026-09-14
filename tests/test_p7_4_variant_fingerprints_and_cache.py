"""Phase 7 Gate P7.4 -- resolved-input fingerprints and the variant cache for
Strategy variants.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 7.5 and
15.4 (FP-1, FP-2) and the Section 21 record (Q14, Q15): financial identity is
the fingerprint of the *resolved* inputs, never of the recipe, and a cached
result is an optimization of a deterministic recomputation, never authority.

Every fingerprint is measured against the existing per-mode fingerprint of the
Deal's own contracts, and every served result against the P7.4 analysis wrapper
run on the Deal as currently stored -- an independent path to the same D6 entry
point.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from anchor.analysis.scenario import ScenarioDefinition
from anchor.analysis.strategy import (
    StrategyValidationError,
    analyze_detailed_acquisition_with_strategy,
    analyze_lease_level_acquisition_with_strategy,
    analyze_quick_acquisition_with_strategy,
)
from anchor.business_plan import BusinessPlan
from anchor.contracts import OperatingMode, UnsupportedOperatingModeError
from anchor.deals import SnapshotValidationError, store, variants
from anchor.deals.contracts import Deal, InvestmentStrategy, ScenarioNotFoundError, StrategyNotFoundError
from anchor.deals.fingerprint import fingerprint_quick_inputs
from anchor.deals.variants import VariantCacheStatus

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
import _p7_4_fixtures as f4  # type: ignore[import-not-found]
from _p7_2_fixtures import (  # type: ignore[import-not-found]
    MODES,
    analyze_deal,
    create_deal,
    deal_fingerprint,
    economic_override,
    execute,
    override,
    rows,
    update_deal,
)

CACHED_MODES = ("quick", "detailed")
BASE = "base"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_4.db"


def _economic(mode: str, unit: str) -> tuple[Any, ...]:
    """A Strategy that changes the economics in every mode."""

    outcome = {"quick": ("noi_growth", 0.04), "detailed": ("revenue_growth", 0.04), "lease_level": ("market_rent_psf", 42.0)}[mode]
    return (
        f4.acquisition(unit, purchase_price={"quick": 11_000_000.0, "detailed": 16_500_000.0, "lease_level": 37_000_000.0}[mode]),
        f4.outcomes(unit, f4.outcome(*outcome)),
    )


def _base_overlays(deal: Deal) -> tuple[Any, ...]:
    """Every domain, each restating the Deal's own Base exactly."""

    terms: Any = deal.inputs if deal.operating_mode is OperatingMode.QUICK else deal.terms
    outcome = {
        OperatingMode.QUICK: f4.outcome("noi_growth", deal.inputs.noi_growth if deal.inputs else None),
        OperatingMode.DETAILED: f4.outcome(
            "revenue_growth", deal.detailed_operating_inputs.revenue_growth if deal.detailed_operating_inputs else None
        ),
        OperatingMode.LEASE_LEVEL: f4.outcome(
            "expense_growth", deal.operating_inputs.expense_growth if deal.operating_inputs else None
        ),
    }[deal.operating_mode]
    return (
        f4.acquisition(deal.id, purchase_price=terms.purchase_price, acquisition_cost_pct=terms.acquisition_cost_pct),
        f4.financing(
            deal.id, ltv=terms.ltv, interest_rate=terms.interest_rate, amortization=terms.amortization,
            io_period=terms.io_period, financing_fee_pct=terms.financing_fee_pct,
        ),
        f4.plan_overlay(deal.id, deal.business_plan),
        f4.outcomes(deal.id, f4.outcome("exit_cap_rate", terms.exit_cap_rate), outcome),
        f4.disposition(deal.id, terms.hold_period),
    )


def _strategy(deal: Deal, db: Path, *overlays: Any, name: str = "Strategy") -> InvestmentStrategy:
    return store.create_strategy_for_deal(deal.id, name=name, overlays=overlays, db_path=db)


def _fp(record: InvestmentStrategy, db: Path, scenario_id: str = BASE, strategy_id: str | None = None) -> str:
    return variants.variant_fingerprint(
        record.investment_id, strategy_id or record.strategy.strategy_id, scenario_id, db_path=db
    ).source_fingerprint


def _analyze(record: InvestmentStrategy, db: Path, scenario_id: str = BASE) -> variants.VariantAnalysis:
    return variants.analyze_variant(record.investment_id, record.strategy.strategy_id, scenario_id, db_path=db)


def _oracle(record: InvestmentStrategy, db: Path, scenario_id: str = BASE) -> Any:
    """The P7.4 wrapper over the Deal and the Strategy as currently stored."""

    deal = store.get_deal(store.get_investment(record.investment_id, db_path=db).units[0].unit_id, db_path=db)
    strategy = store.get_strategy(record.investment_id, record.strategy.strategy_id, db_path=db).strategy
    scenario: ScenarioDefinition | None = (
        None if scenario_id == BASE else store.get_scenario(record.investment_id, scenario_id, db_path=db).scenario
    )
    common = {"unit_id": deal.id, "strategy": strategy, "scenario": scenario, "business_plan": deal.business_plan}
    if deal.operating_mode is OperatingMode.QUICK:
        return analyze_quick_acquisition_with_strategy(deal.inputs, **common)  # type: ignore[arg-type]
    if deal.operating_mode is OperatingMode.DETAILED:
        return analyze_detailed_acquisition_with_strategy(deal.terms, deal.detailed_operating_inputs, **common)  # type: ignore[arg-type]
    return analyze_lease_level_acquisition_with_strategy(
        deal.terms, deal.property_inputs, deal.suites, deal.leases,  # type: ignore[arg-type]
        market_leasing=deal.market_leasing, operating_inputs=deal.operating_inputs, **common,  # type: ignore[arg-type]
    )


# =============================================================================
# Fingerprint oracles
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_base_by_base_is_the_deals_own_fingerprint(db: Path, mode: str) -> None:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    record = _strategy(deal, db, *_economic(mode, deal.id))
    assert variants.variant_fingerprint(record.investment_id, BASE, BASE, db_path=db).source_fingerprint == deal_fingerprint(deal)


@pytest.mark.parametrize("mode", MODES)
def test_base_strategy_by_a_neutral_scenario_is_the_deals_own_fingerprint(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    neutral = store.create_scenario_for_deal(deal.id, name="Neutral", db_path=db)
    fingerprint = variants.variant_fingerprint(neutral.investment_id, BASE, neutral.scenario.scenario_id, db_path=db)
    assert fingerprint.source_fingerprint == deal_fingerprint(deal)
    assert fingerprint.source_fingerprint == variants.scenario_variant_fingerprint(
        neutral.investment_id, neutral.scenario.scenario_id, db_path=db
    ).source_fingerprint


@pytest.mark.parametrize("mode", MODES)
def test_a_strategy_that_restates_base_exactly_carries_the_deals_own_fingerprint(db: Path, mode: str) -> None:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    record = _strategy(deal, db, *_base_overlays(deal))
    assert _fp(record, db) == deal_fingerprint(deal)


@pytest.mark.parametrize("mode", MODES)
def test_renaming_or_redescribing_a_strategy_never_moves_its_fingerprint(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    record = _strategy(deal, db, *_economic(mode, deal.id))
    before = _fp(record, db)
    assert before != deal_fingerprint(deal)

    store.update_strategy(record.investment_id, record.strategy.strategy_id, name="Renamed", overlays=_economic(mode, deal.id), db_path=db)
    assert _fp(record, db) == before
    store.update_strategy(
        record.investment_id, record.strategy.strategy_id, name="Renamed", description="Completely new words",
        overlays=_economic(mode, deal.id), db_path=db,
    )
    assert _fp(record, db) == before


def test_two_recipes_that_resolve_identically_share_a_fingerprint(db: Path) -> None:
    deal = create_deal("quick", db)
    price = 11_000_000.0
    lean = _strategy(deal, db, f4.acquisition(deal.id, purchase_price=price, acquisition_cost_pct=deal.inputs.acquisition_cost_pct))  # type: ignore[union-attr]
    verbose = _strategy(
        deal, db,
        f4.acquisition(deal.id, purchase_price=price, acquisition_cost_pct=deal.inputs.acquisition_cost_pct),  # type: ignore[union-attr]
        f4.outcomes(deal.id, f4.outcome("exit_cap_rate", deal.inputs.exit_cap_rate)),  # type: ignore[union-attr]
        f4.disposition(deal.id, deal.inputs.hold_period),  # type: ignore[union-attr]
        name="Verbose",
    )
    assert _fp(lean, db) == _fp(verbose, db) != deal_fingerprint(deal)


def test_an_exact_semantic_revert_restores_the_original_fingerprint(db: Path) -> None:
    deal = create_deal("detailed", db, business_plan=fx.business_plan())
    record = _strategy(deal, db, *_economic("detailed", deal.id))
    key = (record.investment_id, record.strategy.strategy_id)
    assert _fp(record, db) != deal_fingerprint(deal)

    store.update_strategy(*key, name="Reverted", overlays=_base_overlays(deal), db_path=db)
    assert _fp(record, db) == deal_fingerprint(deal)
    store.update_strategy(*key, name="Reverted", overlays=(), db_path=db)
    assert _fp(record, db) == deal_fingerprint(deal)


def test_scenario_metadata_never_moves_a_strategy_by_scenario_fingerprint(db: Path) -> None:
    deal = create_deal("quick", db)
    record = _strategy(deal, db, *_economic("quick", deal.id))
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", overrides=(economic_override("quick", deal.id),), db_path=db)
    before = _fp(record, db, scenario.scenario.scenario_id)

    store.update_scenario(
        scenario.investment_id, scenario.scenario.scenario_id, name="Recession", description="Words",
        overrides=(economic_override("quick", deal.id),), db_path=db,
    )
    assert _fp(record, db, scenario.scenario.scenario_id) == before


def test_strategy_and_scenario_recipes_that_resolve_identically_share_a_fingerprint(db: Path) -> None:
    deal = create_deal("quick", db)
    relative = _strategy(deal, db, f4.outcomes(deal.id, f4.outcome("exit_cap_rate", 0.06)))
    widened = store.create_scenario_for_deal(deal.id, name="Wider", overrides=(override(deal.id, "exit_cap_rate", "add", 0.005),), db_path=db)
    absolute = _strategy(deal, db, f4.outcomes(deal.id, f4.outcome("exit_cap_rate", 0.06 + 0.005)), name="Absolute")

    assert _fp(relative, db, widened.scenario.scenario_id) == _fp(absolute, db)
    assert _fp(relative, db, widened.scenario.scenario_id) != _fp(relative, db)


def test_overlay_and_outcome_insertion_order_never_moves_a_fingerprint(db: Path) -> None:
    deal = create_deal("lease_level", db, business_plan=fx.business_plan())
    overlays = (
        f4.acquisition(deal.id, purchase_price=37_000_000.0),
        f4.plan_overlay(deal.id, f4.renovation_plan()),
        f4.outcomes(deal.id, f4.outcome("market_rent_psf", 42.0), f4.outcome("expense_growth", 0.035)),
        f4.disposition(deal.id, 7),
    )
    forward = _strategy(deal, db, *overlays)
    backward = _strategy(
        deal, db, *reversed(overlays[:2]),
        f4.outcomes(deal.id, f4.outcome("expense_growth", 0.035), f4.outcome("market_rent_psf", 42.0)),
        overlays[3], name="Backward",
    )
    assert _fp(forward, db) == _fp(backward, db)


@pytest.mark.parametrize("mode", MODES)
def test_an_empty_plan_replacement_fingerprints_as_the_deal_with_an_empty_plan(db: Path, mode: str) -> None:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    no_overlay = _strategy(deal, db, f4.disposition(deal.id, deal.terms.hold_period if deal.terms else deal.inputs.hold_period))  # type: ignore[union-attr]
    emptied = _strategy(deal, db, f4.plan_overlay(deal.id, BusinessPlan()), name="Executes no plan")
    without_plan = dataclasses.replace(deal, business_plan=BusinessPlan())

    assert _fp(no_overlay, db) == deal_fingerprint(deal)
    assert _fp(emptied, db) == deal_fingerprint(without_plan)
    assert _fp(emptied, db) != _fp(no_overlay, db)


def test_a_replacement_plan_fingerprints_as_the_deal_with_that_plan(db: Path) -> None:
    deal = create_deal("quick", db, business_plan=fx.business_plan())
    record = _strategy(deal, db, f4.plan_overlay(deal.id, f4.renovation_plan()))
    assert _fp(record, db) == fingerprint_quick_inputs(deal.inputs, business_plan=f4.renovation_plan())  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", MODES)
def test_inspection_fingerprint_and_analysis_agree_on_one_fingerprint(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    record = _strategy(deal, db, *_economic(mode, deal.id))
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", overrides=(economic_override(mode, deal.id),), db_path=db)
    key = (record.investment_id, record.strategy.strategy_id, scenario.scenario.scenario_id)

    inspected = variants.inspect_variant_inputs(*key, db_path=db)
    assert inspected.source_fingerprint == variants.variant_fingerprint(*key, db_path=db).source_fingerprint
    assert inspected.source_fingerprint == variants.analyze_variant(*key, db_path=db).source_fingerprint
    assert inspected.source_fingerprint == variants.fingerprint_resolved_inputs(inspected.resolved)


def test_an_invalid_variant_has_no_fingerprint_it_is_refused(db: Path) -> None:
    deal = create_deal("quick", db)
    record = _strategy(deal, db, f4.acquisition(deal.id, purchase_price=-1.0))
    with pytest.raises(StrategyValidationError):
        _fp(record, db)
    with pytest.raises(StrategyValidationError):
        _analyze(record, db)
    assert rows(db, "variant_snapshots") == []


# =============================================================================
# Cache oracles -- Quick and Detailed
# =============================================================================


@pytest.mark.parametrize("mode", CACHED_MODES)
@pytest.mark.parametrize("with_scenario", [False, True], ids=["strategy-x-base", "strategy-x-scenario"])
def test_a_miss_computes_and_caches_then_a_current_hit_is_served(db: Path, mode: str, with_scenario: bool) -> None:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    record = _strategy(deal, db, *_economic(mode, deal.id))
    scenario_id = BASE
    if with_scenario:
        scenario_id = store.create_scenario_for_deal(
            deal.id, name="Downside", overrides=(economic_override(mode, deal.id),), db_path=db
        ).scenario.scenario_id

    first = _analyze(record, db, scenario_id)
    ((root, strategy_key, scenario_key, _, version, source, _),) = rows(db, "variant_snapshots")
    second = _analyze(record, db, scenario_id)

    assert (first.cache_status, second.cache_status) == (VariantCacheStatus.MISS, VariantCacheStatus.HIT)
    assert (root, strategy_key, scenario_key, version) == (record.investment_id, record.strategy.strategy_id, scenario_id, 1)
    assert source == first.source_fingerprint == second.source_fingerprint == _fp(record, db, scenario_id)
    assert first.results == second.results == _oracle(record, db, scenario_id)


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_a_hit_really_is_served_from_the_cache(db: Path, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    deal = create_deal(mode, db)
    record = _strategy(deal, db, *_economic(mode, deal.id))
    expected = _analyze(record, db).results

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a current cache hit must not re-run the analysis")

    monkeypatch.setattr(variants, "_analyze_resolved", refuse)
    served = _analyze(record, db)
    assert (served.cache_status, served.results) == (VariantCacheStatus.HIT, expected)


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_an_economic_change_is_a_stale_miss_and_a_rename_keeps_the_cache(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    record = _strategy(deal, db, *_economic(mode, deal.id))
    key = (record.investment_id, record.strategy.strategy_id)
    _analyze(record, db)

    store.update_strategy(*key, name="Renamed", description="New words", overlays=_economic(mode, deal.id), db_path=db)
    assert _analyze(record, db).cache_status is VariantCacheStatus.HIT

    store.update_strategy(*key, name="Renamed", overlays=(f4.disposition(deal.id, 3),), db_path=db)
    changed = _analyze(record, db)
    assert changed.cache_status is VariantCacheStatus.MISS
    assert changed.results == _oracle(record, db)


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_a_base_edit_makes_the_cached_strategy_variant_stale(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    record = _strategy(deal, db, f4.disposition(deal.id, 6))
    before = _analyze(record, db)

    update_deal(deal, db, exit_cap_rate=0.07)
    after = _analyze(record, db)

    assert after.cache_status is VariantCacheStatus.MISS
    assert after.source_fingerprint != before.source_fingerprint
    assert after.results == _oracle(record, db)


_BROKEN_ROWS = {
    "undecodable-json": ("snapshot", "{not json"),
    "malformed-payload": ("snapshot", json.dumps({"purchase_price": 1.0})),
    "wrong-contract": ("snapshot", json.dumps([1, 2, 3])),
    "incompatible-version": ("schema_version", 99),
    "stale-fingerprint": ("source_fingerprint", "0" * 64),
}


@pytest.mark.parametrize("mode", CACHED_MODES)
@pytest.mark.parametrize("case", sorted(_BROKEN_ROWS))
def test_a_broken_cached_row_is_a_miss_and_is_recomputed(db: Path, mode: str, case: str) -> None:
    deal = create_deal(mode, db)
    record = _strategy(deal, db, *_economic(mode, deal.id))
    _analyze(record, db)
    column, value = _BROKEN_ROWS[case]
    execute(db, f"UPDATE variant_snapshots SET {column} = ?", (value,))

    served = _analyze(record, db)
    assert served.cache_status is VariantCacheStatus.MISS
    assert served.results == _oracle(record, db)
    assert _analyze(record, db).cache_status is VariantCacheStatus.HIT


def test_a_row_under_another_variant_key_is_never_served(db: Path) -> None:
    deal = create_deal("quick", db)
    record = _strategy(deal, db, *_economic("quick", deal.id))
    other = _strategy(deal, db, f4.disposition(deal.id, 3), name="Other")
    _analyze(other, db)
    execute(db, "UPDATE variant_snapshots SET strategy_id = ?", (record.strategy.strategy_id,))
    execute(db, "UPDATE variant_snapshots SET scenario_id = 'another'")

    assert _analyze(record, db).cache_status is VariantCacheStatus.MISS


# =============================================================================
# Lease-Level -- recomputed, never cached
# =============================================================================


def test_a_lease_level_strategy_variant_is_recomputed_every_time_and_never_cached(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal = create_deal("lease_level", db)
    record = _strategy(deal, db, *_economic("lease_level", deal.id))
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", overrides=(economic_override("lease_level", deal.id),), db_path=db)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a Lease-Level variant must never touch the cache")

    for name in ("get_strategy_variant_snapshot", "put_strategy_variant_snapshot", "get_variant_snapshot", "put_variant_snapshot"):
        monkeypatch.setattr(store, name, refuse)
    for scenario_id in (BASE, scenario.scenario.scenario_id):
        first, second = _analyze(record, db, scenario_id), _analyze(record, db, scenario_id)
        assert (first.cache_status, second.cache_status) == (VariantCacheStatus.BYPASSED,) * 2
        assert first.results == second.results == _oracle(record, db, scenario_id)
    assert rows(db, "variant_snapshots") == []


def test_the_store_refuses_to_cache_or_serve_a_lease_level_strategy_variant(db: Path) -> None:
    deal = create_deal("lease_level", db)
    record = _strategy(deal, db, *_economic("lease_level", deal.id))
    with pytest.raises(UnsupportedOperatingModeError):
        store.get_strategy_variant_snapshot(
            record.investment_id, record.strategy.strategy_id, BASE,
            operating_mode=OperatingMode.LEASE_LEVEL, expected_fingerprint="x", db_path=db,
        )
    result = _analyze(record, db).results
    with pytest.raises(UnsupportedOperatingModeError):
        store.put_strategy_variant_snapshot(
            record.investment_id, record.strategy.strategy_id, BASE, result,  # type: ignore[arg-type]
            source_fingerprint="x", db_path=db,
        )
    assert rows(db, "variant_snapshots") == []


# =============================================================================
# Base x Base is never duplicated; the store's own refusals
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_base_by_base_is_the_ordinary_analysis_and_never_a_variant_row(db: Path, mode: str) -> None:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    record = _strategy(deal, db, *_economic(mode, deal.id))

    analysed = variants.analyze_variant(record.investment_id, BASE, BASE, db_path=db)

    assert analysed.cache_status is VariantCacheStatus.BYPASSED
    assert analysed.source_fingerprint == deal_fingerprint(deal)
    assert analysed.results == analyze_deal(deal)
    assert rows(db, "variant_snapshots") == []


def test_base_by_scenario_is_the_p7_2_variant_exactly(db: Path) -> None:
    deal = create_deal("detailed", db)
    _strategy(deal, db, *_economic("detailed", deal.id))
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", overrides=(economic_override("detailed", deal.id),), db_path=db)

    through_p7_2 = variants.analyze_scenario_variant(scenario.investment_id, scenario.scenario.scenario_id, db_path=db)
    through_p7_4 = variants.analyze_variant(scenario.investment_id, BASE, scenario.scenario.scenario_id, db_path=db)

    assert (through_p7_2.cache_status, through_p7_4.cache_status) == (VariantCacheStatus.MISS, VariantCacheStatus.HIT)
    assert through_p7_4.results == through_p7_2.results
    assert through_p7_4.source_fingerprint == through_p7_2.source_fingerprint
    assert [row[:3] for row in rows(db, "variant_snapshots")] == [(scenario.investment_id, BASE, scenario.scenario.scenario_id)]


def test_the_store_caches_only_owned_strategy_variants_of_the_units_own_contract(db: Path) -> None:
    deal = create_deal("quick", db)
    record = _strategy(deal, db, *_economic("quick", deal.id))
    other_deal = create_deal("quick", db)
    foreign = _strategy(other_deal, db, *_economic("quick", other_deal.id))
    foreign_scenario = store.create_scenario_for_deal(other_deal.id, name="Theirs", db_path=db)
    detailed_deal = create_deal("detailed", db)
    detailed_result = analyze_deal(detailed_deal)
    result = _analyze(record, db).results
    execute(db, "DELETE FROM variant_snapshots")
    key = record.investment_id

    with pytest.raises(StrategyNotFoundError):
        store.put_strategy_variant_snapshot(key, BASE, BASE, result, source_fingerprint="x", db_path=db)  # type: ignore[arg-type]
    with pytest.raises(StrategyNotFoundError):
        store.put_strategy_variant_snapshot(key, foreign.strategy.strategy_id, BASE, result, source_fingerprint="x", db_path=db)  # type: ignore[arg-type]
    with pytest.raises(ScenarioNotFoundError):
        store.put_strategy_variant_snapshot(
            key, record.strategy.strategy_id, foreign_scenario.scenario.scenario_id, result, source_fingerprint="x", db_path=db,  # type: ignore[arg-type]
        )
    with pytest.raises(SnapshotValidationError, match="caches AcquisitionResults"):
        store.put_strategy_variant_snapshot(key, record.strategy.strategy_id, BASE, detailed_result, source_fingerprint="x", db_path=db)  # type: ignore[arg-type]
    with pytest.raises(SnapshotValidationError, match="non-empty source fingerprint"):
        store.put_strategy_variant_snapshot(key, record.strategy.strategy_id, BASE, result, source_fingerprint="", db_path=db)  # type: ignore[arg-type]
    assert rows(db, "variant_snapshots") == []


def test_deleting_a_strategy_deletes_its_rows_and_a_scenario_deletes_its_rows_under_every_strategy(db: Path) -> None:
    deal = create_deal("quick", db)
    first = _strategy(deal, db, *_economic("quick", deal.id))
    second = _strategy(deal, db, f4.disposition(deal.id, 3), name="Second")
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", db_path=db)
    for record in (first, second):
        _analyze(record, db)
        _analyze(record, db, scenario.scenario.scenario_id)
    variants.analyze_scenario_variant(scenario.investment_id, scenario.scenario.scenario_id, db_path=db)
    assert len(rows(db, "variant_snapshots")) == 5

    store.delete_strategy(first.investment_id, first.strategy.strategy_id, db_path=db)
    assert sorted(row[1:3] for row in rows(db, "variant_snapshots")) == sorted(
        [(second.strategy.strategy_id, BASE), (second.strategy.strategy_id, scenario.scenario.scenario_id), (BASE, scenario.scenario.scenario_id)]
    )
    store.delete_scenario(scenario.investment_id, scenario.scenario.scenario_id, db_path=db)
    assert [row[1:3] for row in rows(db, "variant_snapshots")] == [(second.strategy.strategy_id, BASE)]
