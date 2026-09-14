"""Phase 7 Gate P7.2 -- the fingerprint-guarded variant cache (Q14).

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 7.5 and
15.2: a cached result is an optimization of a deterministic recomputation and
never financial authority.

- Quick and Detailed variants are cached, and a cached result is served only
  while its source fingerprint equals the fingerprint just recomputed from the
  current Scenario and the current Deal. A stale, corrupt, malformed,
  incompatible or missing row is a miss, recomputed through the D6 entry point.
- Lease-Level variants are recomputed every time and never read or write the
  cache (Q14, D5 decision A).
- Base x Base is never cached here: it is the Deal's own analysis.

Every served result is compared with an independent oracle: the P7.1
``analyze_*_acquisition_with_scenario`` wrapper run on the Deal's stored inputs.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from anchor.analysis.scenario import (
    analyze_detailed_acquisition_with_scenario,
    analyze_lease_level_acquisition_with_scenario,
    analyze_quick_acquisition_with_scenario,
)
from anchor.contracts import OperatingMode, UnsupportedOperatingModeError
from anchor.deals import SnapshotValidationError, store, variants
from anchor.deals.contracts import Deal, InvestmentScenario, ScenarioNotFoundError
from anchor.deals.variants import VariantCacheStatus
from anchor.engine.contracts import AcquisitionResults, DetailedAcquisitionResults, IrrStatus

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from _p7_2_fixtures import (  # type: ignore[import-not-found]
    MODES,
    analyze_deal,
    create_deal,
    deal_fingerprint,
    economic_override,
    execute,
    override,
    row_counts,
    rows,
    second_override,
    update_deal,
)

CACHED_MODES = ("quick", "detailed")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_2.db"


def _analyze(record: InvestmentScenario, db: Path) -> variants.ScenarioVariantAnalysis:
    return variants.analyze_scenario_variant(record.investment_id, record.scenario.scenario_id, db_path=db)


def _oracle(record: InvestmentScenario, db: Path) -> Any:
    """The P7.1 wrapper over the Deal as currently stored -- an independent
    path to the same D6 entry point."""

    deal = store.get_deal(store.get_investment(record.investment_id, db_path=db).units[0].unit_id, db_path=db)
    common = {"unit_id": deal.id, "scenario": record.scenario, "business_plan": deal.business_plan}
    if deal.operating_mode is OperatingMode.QUICK:
        return analyze_quick_acquisition_with_scenario(deal.inputs, **common)  # type: ignore[arg-type]
    if deal.operating_mode is OperatingMode.DETAILED:
        return analyze_detailed_acquisition_with_scenario(deal.terms, deal.detailed_operating_inputs, **common)  # type: ignore[arg-type]
    return analyze_lease_level_acquisition_with_scenario(
        deal.terms, deal.property_inputs, deal.suites, deal.leases,  # type: ignore[arg-type]
        market_leasing=deal.market_leasing, operating_inputs=deal.operating_inputs, **common,  # type: ignore[arg-type]
    )


def _scenario(mode: str, db: Path, *, business_plan: Any = None) -> tuple[Deal, InvestmentScenario]:
    deal = create_deal(mode, db, **({} if business_plan is None else {"business_plan": business_plan}))
    record = store.create_scenario_for_deal(
        deal.id, name="Downside", overrides=(economic_override(mode, deal.id),), db_path=db
    )
    return deal, record


# =============================================================================
# Quick and Detailed -- a current cache hit
# =============================================================================


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_a_miss_computes_and_caches_then_a_current_hit_is_served(db: Path, mode: str) -> None:
    _, record = _scenario(mode, db, business_plan=fx.business_plan())
    fingerprint = variants.scenario_variant_fingerprint(record.investment_id, record.scenario.scenario_id, db_path=db)

    first = _analyze(record, db)
    ((root, strategy, scenario_id, _, version, source, _),) = rows(db, "variant_snapshots")
    second = _analyze(record, db)

    assert (first.cache_status, second.cache_status) == (VariantCacheStatus.MISS, VariantCacheStatus.HIT)
    assert (root, strategy, scenario_id, version) == (
        record.investment_id, store._BASE_STRATEGY_ID, record.scenario.scenario_id, 1,
    )
    assert source == first.source_fingerprint == second.source_fingerprint == fingerprint.source_fingerprint
    assert first.results == second.results == _oracle(record, db)
    assert type(second.results) is (AcquisitionResults if mode == "quick" else DetailedAcquisitionResults)


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_a_hit_really_is_served_from_the_cache(db: Path, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _, record = _scenario(mode, db)
    expected = _analyze(record, db).results

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a current cache hit must not re-run the analysis")

    monkeypatch.setattr(variants, "_analyze_resolved", refuse)
    served = _analyze(record, db)

    assert served.cache_status is VariantCacheStatus.HIT
    assert served.results == expected


def test_a_cached_result_decodes_to_its_contract_types(db: Path) -> None:
    _, record = _scenario("detailed", db)
    _analyze(record, db)
    served = _analyze(record, db)

    assert served.cache_status is VariantCacheStatus.HIT
    assert isinstance(served.results, DetailedAcquisitionResults)
    assert type(served.results.results.levered_irr_status) is IrrStatus


# =============================================================================
# Stale, corrupt, malformed, incompatible and missing rows are misses
# =============================================================================


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_a_base_edit_makes_the_cached_row_stale(db: Path, mode: str) -> None:
    deal, record = _scenario(mode, db)
    before = _analyze(record, db)

    update_deal(deal, db, purchase_price=11_000_000.0)
    after = _analyze(record, db)

    assert after.cache_status is VariantCacheStatus.MISS
    assert after.source_fingerprint != before.source_fingerprint
    assert after.results != before.results
    assert after.results == _oracle(record, db)
    ((*_, source, _),) = rows(db, "variant_snapshots")
    assert source == after.source_fingerprint


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_an_economic_recipe_change_is_a_miss_and_a_display_only_change_is_a_hit(db: Path, mode: str) -> None:
    deal, record = _scenario(mode, db)
    key = (record.investment_id, record.scenario.scenario_id)
    _analyze(record, db)

    store.update_scenario(*key, name="Renamed", description="New words", overrides=(economic_override(mode, deal.id),), db_path=db)
    assert _analyze(record, db).cache_status is VariantCacheStatus.HIT

    store.update_scenario(*key, name="Renamed", overrides=(economic_override(mode, deal.id), second_override(mode, deal.id)), db_path=db)
    changed = _analyze(record, db)
    assert changed.cache_status is VariantCacheStatus.MISS
    assert changed.results == _oracle(store.get_scenario(*key, db_path=db), db)


def test_an_equivalent_recipe_keeps_its_cache(db: Path) -> None:
    """``ADD 0.005`` and ``SET base + 0.005`` resolve to the same inputs, so
    they are the same variant for the cache."""

    deal, record = _scenario("quick", db)
    _analyze(record, db)
    store.update_scenario(
        record.investment_id, record.scenario.scenario_id, name="Set",
        overrides=(override(deal.id, "exit_cap_rate", "set", fx.quick_inputs().exit_cap_rate + 0.005),),
        db_path=db,
    )
    assert _analyze(record, db).cache_status is VariantCacheStatus.HIT


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
    _, record = _scenario(mode, db)
    _analyze(record, db)
    column, value = _BROKEN_ROWS[case]
    execute(db, f"UPDATE variant_snapshots SET {column} = ?", (value,))

    served = _analyze(record, db)

    assert served.cache_status is VariantCacheStatus.MISS
    assert served.results == _oracle(record, db)
    assert _analyze(record, db).cache_status is VariantCacheStatus.HIT


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_a_missing_row_is_a_miss(db: Path, mode: str) -> None:
    _, record = _scenario(mode, db)
    _analyze(record, db)
    execute(db, "DELETE FROM variant_snapshots")

    assert _analyze(record, db).cache_status is VariantCacheStatus.MISS


def test_a_row_under_another_strategy_key_is_never_served(db: Path) -> None:
    _, record = _scenario("quick", db)
    _analyze(record, db)
    execute(db, "UPDATE variant_snapshots SET strategy_id = 'another'")

    assert _analyze(record, db).cache_status is VariantCacheStatus.MISS


# =============================================================================
# Lease-Level -- recomputed, never cached
# =============================================================================


def test_a_lease_level_variant_is_recomputed_every_time_and_never_cached(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, record = _scenario("lease_level", db)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a Lease-Level variant must never touch the cache")

    monkeypatch.setattr(store, "get_variant_snapshot", refuse)
    monkeypatch.setattr(store, "put_variant_snapshot", refuse)
    first, second = _analyze(record, db), _analyze(record, db)

    assert (first.cache_status, second.cache_status) == (VariantCacheStatus.BYPASSED,) * 2
    assert first.results == second.results == _oracle(record, db)
    assert row_counts(db)["variant_snapshots"] == 0


def test_a_lease_level_row_planted_in_the_cache_is_never_served(db: Path) -> None:
    """A row keyed exactly like a Lease-Level variant, carrying that variant's
    current fingerprint and a decodable payload, is still never read."""

    _, quick_record = _scenario("quick", db)
    _analyze(quick_record, db)
    ((*_, quick_snapshot, _, _, _),) = rows(db, "variant_snapshots")
    _, record = _scenario("lease_level", db)
    fingerprint = variants.scenario_variant_fingerprint(record.investment_id, record.scenario.scenario_id, db_path=db)
    execute(
        db, "INSERT INTO variant_snapshots VALUES (?, 'base', ?, ?, 1, ?, 'now')",
        (record.investment_id, record.scenario.scenario_id, quick_snapshot, fingerprint.source_fingerprint),
    )

    served = _analyze(record, db)

    assert served.cache_status is VariantCacheStatus.BYPASSED
    assert served.results == _oracle(record, db)


def test_the_store_refuses_to_cache_or_serve_a_lease_level_variant(db: Path) -> None:
    _, record = _scenario("lease_level", db)
    with pytest.raises(UnsupportedOperatingModeError):
        store.get_variant_snapshot(
            record.investment_id, record.scenario.scenario_id,
            operating_mode=OperatingMode.LEASE_LEVEL, expected_fingerprint="x", db_path=db,
        )
    result = _analyze(record, db).results
    with pytest.raises(UnsupportedOperatingModeError):
        store.put_variant_snapshot(
            record.investment_id, record.scenario.scenario_id, result,  # type: ignore[arg-type]
            source_fingerprint="x", db_path=db,
        )
    assert row_counts(db)["variant_snapshots"] == 0


# =============================================================================
# The store's own refusals
# =============================================================================


def test_the_store_caches_only_the_units_own_result_contract_for_an_owned_scenario(db: Path) -> None:
    _, quick = _scenario("quick", db)
    _, detailed = _scenario("detailed", db)
    detailed_result = _analyze(detailed, db).results
    quick_result = _analyze(quick, db).results

    with pytest.raises(SnapshotValidationError, match="caches AcquisitionResults"):
        store.put_variant_snapshot(quick.investment_id, quick.scenario.scenario_id, detailed_result, source_fingerprint="x", db_path=db)  # type: ignore[arg-type]
    with pytest.raises(SnapshotValidationError, match="non-empty source fingerprint"):
        store.put_variant_snapshot(quick.investment_id, quick.scenario.scenario_id, quick_result, source_fingerprint="", db_path=db)  # type: ignore[arg-type]
    with pytest.raises(ScenarioNotFoundError):
        store.put_variant_snapshot(quick.investment_id, detailed.scenario.scenario_id, quick_result, source_fingerprint="x", db_path=db)  # type: ignore[arg-type]


# =============================================================================
# Base x Base is never duplicated into the variant cache
# =============================================================================


@pytest.mark.parametrize("mode", CACHED_MODES)
def test_base_by_base_is_never_a_variant_row(db: Path, mode: str) -> None:
    """The ordinary analysis of a Deal -- its own snapshot -- is never copied
    into the variant cache, and a neutral Scenario is a Scenario row of its own,
    keyed by its own id, never by a reserved Base key."""

    deal = create_deal(mode, db)
    store.update_analysis_snapshot(
        deal.id, dataclasses.asdict(analyze_deal(deal)),
        financial_input_fingerprint=deal_fingerprint(deal), db_path=db,
    )
    snapshot_row = rows(db, "deals" if mode == "quick" else "detailed_deals")
    assert row_counts(db)["variant_snapshots"] == 0

    neutral = store.create_scenario_for_deal(deal.id, name="Neutral", db_path=db)
    other = store.create_scenario_for_deal(deal.id, name="Other", overrides=(economic_override(mode, deal.id),), db_path=db)
    _analyze(neutral, db)
    _analyze(other, db)

    keys = sorted((root, strategy, scenario_id) for root, strategy, scenario_id, *_ in rows(db, "variant_snapshots"))
    assert keys == sorted(
        (neutral.investment_id, store._BASE_STRATEGY_ID, record.scenario.scenario_id) for record in (neutral, other)
    )
    assert store._BASE_STRATEGY_ID not in {scenario_id for _, _, scenario_id in keys}
    assert rows(db, "deals" if mode == "quick" else "detailed_deals") == snapshot_row
    assert store.get_deal(deal.id, db_path=db).analysis_snapshot == analyze_deal(deal)


def test_deleting_a_scenario_deletes_its_cached_rows_and_an_update_leaves_them(db: Path) -> None:
    deal, record = _scenario("quick", db)
    other = store.create_scenario_for_deal(deal.id, name="Other", db_path=db)
    _analyze(record, db)
    _analyze(other, db)
    store.update_scenario(record.investment_id, record.scenario.scenario_id, name="Edited", overrides=(), db_path=db)
    assert row_counts(db)["variant_snapshots"] == 2

    store.delete_scenario(record.investment_id, record.scenario.scenario_id, db_path=db)

    assert [row[2] for row in rows(db, "variant_snapshots")] == [other.scenario.scenario_id]


@pytest.mark.parametrize("mode", MODES)
def test_the_analysis_is_the_ordinary_run_on_the_resolved_inputs(db: Path, mode: str) -> None:
    """The variant analysis returns the existing result contract, equal to the
    P7.1 wrapper's -- and, for a neutral Scenario, equal to the Deal's own
    ordinary analysis."""

    deal = create_deal(mode, db, business_plan=fx.business_plan())
    neutral = store.create_scenario_for_deal(deal.id, name="Neutral", db_path=db)
    assert _analyze(neutral, db).results == analyze_deal(deal)
