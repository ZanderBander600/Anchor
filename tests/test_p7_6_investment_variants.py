"""Phase 7 Gate P7.6 -- the visible Investment variant pathway.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 7.5, 8,
9, 10, 11 and 15.4. Every Unit runs exactly the analysis it would run alone --
proven against each Deal's own analysis and the existing P7.4 per-Unit
resolution -- and the Investment is consolidated after all of them.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
import _p7_4_fixtures as f4  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.business_plan import BusinessPlan
from anchor.deals import store
from anchor.deals.investment_variants import (
    InvestmentVariantIssueSource,
    InvestmentVariantValidationError,
    analyze_investment_variant,
    fingerprint_investment_variant,
    inspect_investment_variant_inputs,
    investment_variant_fingerprint,
)
from anchor.deals.variants import (
    VariantCacheStatus,
    fingerprint_resolved_inputs,
    resolve_variant_inputs,
    variant_fingerprint,
)
from anchor.engine.contracts import IrrStatus
from anchor.investment import InvestmentIssueCode, TransactionCostCategory, UnitKind

from _p7_2_fixtures import analyze_deal, deal_fingerprint, override, rows  # type: ignore[import-not-found]
from _p7_6_fixtures import (  # type: ignore[import-not-found]
    cost,
    create_investment,
    deal_of,
    detailed_deal,
    investment_plan,
    lease_level_deal,
    member,
    price,
    quick_deal,
)

BASE = "base"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_6_variants.db"


def _mixed(db: Path) -> tuple[Any, Any, Any, Any]:
    quick = quick_deal(db, business_plan=fx.business_plan())
    detailed, lease = detailed_deal(db), lease_level_deal(db)
    return quick, detailed, lease, create_investment(db, lease, quick, detailed)


def _project(results: Any) -> Any:
    return getattr(results, "results", results)


# =============================================================================
# One engine: every Unit is its own standalone analysis
# =============================================================================


@pytest.mark.parametrize("mode", ["quick", "detailed", "lease_level"])
def test_a_visible_one_unit_investment_is_its_deals_analysis_bit_for_bit(db: Path, mode: str) -> None:
    deal = deal_of(mode, db, business_plan=fx.business_plan())
    visible = create_investment(db, deal)

    analysis = analyze_investment_variant(visible.id, BASE, BASE, db_path=db)
    standalone = analyze_deal(deal)
    unit, consolidated = _project(standalone), analysis.consolidated_results

    assert analysis.unit_results[0].results == standalone
    for name, analogue in (("levered_cash_flows", "levered_cash_flows"), ("unlevered_cash_flows", "unlevered_cash_flows"),
                           ("levered_irr", "levered_irr"), ("unlevered_irr", "unlevered_irr"), ("equity_multiple", "equity_multiple"),
                           ("initial_equity", "initial_equity"), ("aggregate_dscr_by_year", "dscr_by_year"),
                           ("total_equity_invested", "total_equity_invested"), ("going_in_cap_rate", "going_in_cap_rate")):
        assert repr(getattr(consolidated, name)) == repr(getattr(unit, analogue)), name
    assert analysis.cache_status is VariantCacheStatus.BYPASSED


@pytest.mark.parametrize("modes", [("quick", "quick"), ("detailed", "detailed"), ("lease_level", "lease_level"), ("quick", "detailed", "lease_level")])
def test_every_mode_combination_consolidates_units_that_are_unchanged_by_it(db: Path, modes: tuple[str, ...]) -> None:
    deals = [deal_of(mode, db, name=f"{mode}-{index}") for index, mode in enumerate(modes)]
    visible = create_investment(db, *reversed(deals))

    analysis = analyze_investment_variant(visible.id, BASE, BASE, db_path=db)

    assert [unit.unit_id for unit in analysis.unit_results] == sorted(deal.id for deal in deals)
    by_id = {deal.id: deal for deal in deals}
    for unit in analysis.unit_results:
        assert unit.results == analyze_deal(by_id[unit.unit_id])
        assert unit.operating_mode is by_id[unit.unit_id].operating_mode
        assert unit.source_fingerprint == deal_fingerprint(by_id[unit.unit_id])
    assert analysis.consolidated_results.unit_ids == tuple(sorted(by_id))
    assert analysis.hold_period == 5
    assert rows(db, "variant_snapshots") == []


# =============================================================================
# Multi-unit Strategies and Scenarios -- the existing per-Unit resolution
# =============================================================================


def test_a_multi_unit_strategy_hands_each_unit_its_own_overlays(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    overlays = (
        f4.acquisition(quick.id, purchase_price=price(quick) - 1_000_000.0, acquisition_cost_pct=0.02),
        f4.acquisition(detailed.id, purchase_price=price(detailed) + 1_000_000.0, acquisition_cost_pct=0.015),
        f4.plan_overlay(detailed.id, f4.renovation_plan()),
        f4.outcomes(lease.id, f4.outcome("market_rent_psf", 40.0)),
    )
    record = store.create_strategy(visible.id, name="Reallocate and renovate", overlays=overlays, db_path=db)

    inputs = inspect_investment_variant_inputs(visible.id, record.strategy.strategy_id, BASE, db_path=db)

    for unit in inputs.units:
        deal = store.get_deal(unit.unit_id, db_path=db)
        own = dataclasses.replace(record.strategy, overlays=tuple(o for o in record.strategy.overlays if o.unit_id == deal.id))
        assert unit.resolved == resolve_variant_inputs(deal, own, None)
    analysis = analyze_investment_variant(visible.id, record.strategy.strategy_id, BASE, db_path=db)
    assert analysis.consolidated_results.allocated_purchase_price == pytest.approx(visible.transaction_price)


def test_a_multi_unit_scenario_hands_each_unit_its_own_overrides(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    record = store.create_scenario(visible.id, name="Downside", overrides=(
        override(quick.id, "exit_cap_rate", "add", 0.005),
        override(lease.id, "market_rent_psf", "scale", 0.9),
        override(detailed.id, "expense_growth", "add", 0.01),
    ), db_path=db)

    inputs = inspect_investment_variant_inputs(visible.id, BASE, record.scenario.scenario_id, db_path=db)
    base = inspect_investment_variant_inputs(visible.id, BASE, BASE, db_path=db)

    for unit in inputs.units:
        deal = store.get_deal(unit.unit_id, db_path=db)
        own = dataclasses.replace(record.scenario, overrides=tuple(o for o in record.scenario.overrides if o.unit_id == deal.id))
        assert unit.resolved == resolve_variant_inputs(deal, None, own)
    assert all(a.source_fingerprint != b.source_fingerprint for a, b in zip(inputs.units, base.units, strict=True))
    assert inputs.source_fingerprint != base.source_fingerprint


def test_strategy_by_scenario_resolves_strategy_then_scenario_per_unit(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    strategy = store.create_strategy(visible.id, name="Tighter exit", overlays=(f4.outcomes(quick.id, f4.outcome("exit_cap_rate", 0.06)),), db_path=db)
    scenario = store.create_scenario(visible.id, name="Wider", overrides=(override(quick.id, "exit_cap_rate", "add", 0.005),), db_path=db)

    inputs = inspect_investment_variant_inputs(visible.id, strategy.strategy.strategy_id, scenario.scenario.scenario_id, db_path=db)

    (quick_unit,) = [unit for unit in inputs.units if unit.unit_id == quick.id]
    assert quick_unit.resolved.inputs.exit_cap_rate == pytest.approx(0.065)  # the Strategy's 6.0%, widened
    others = [unit for unit in inputs.units if unit.unit_id != quick.id]
    assert all(unit.source_fingerprint == deal_fingerprint(store.get_deal(unit.unit_id, db_path=db)) for unit in others)


# =============================================================================
# One invalid Unit is one invalid variant -- never a partial consolidation
# =============================================================================


def test_a_strategy_that_breaks_the_allocation_is_an_invalid_variant(db: Path) -> None:
    quick, _, _, visible = _mixed(db)
    record = store.create_strategy(visible.id, name="Bid more", overlays=(
        f4.acquisition(quick.id, purchase_price=price(quick) + 500_000.0, acquisition_cost_pct=0.02),
    ), db_path=db)

    with pytest.raises(InvestmentVariantValidationError) as error:
        analyze_investment_variant(visible.id, record.strategy.strategy_id, BASE, db_path=db)
    (issue,) = error.value.issues
    assert (issue.source, issue.code, issue.field) == (InvestmentVariantIssueSource.INVESTMENT, "allocation_mismatch", "transaction_price")
    assert store.get_visible_investment(visible.id, db_path=db).transaction_price == visible.transaction_price


def test_a_disposition_on_one_unit_breaks_the_common_timeline(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    one = store.create_strategy(visible.id, name="Hold one longer", overlays=(f4.disposition(lease.id, 7),), db_path=db)
    every = store.create_strategy(visible.id, name="Hold all longer", overlays=tuple(f4.disposition(d.id, 7) for d in (quick, detailed, lease)), db_path=db)

    with pytest.raises(InvestmentVariantValidationError) as error:
        analyze_investment_variant(visible.id, one.strategy.strategy_id, BASE, db_path=db)
    assert [issue.code for issue in error.value.issues] == [InvestmentIssueCode.HOLD_PERIOD_MISMATCH.value]
    assert analyze_investment_variant(visible.id, every.strategy.strategy_id, BASE, db_path=db).hold_period == 7


def test_a_scenario_invalid_for_one_unit_names_that_unit(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    record = store.create_scenario(visible.id, name="Too optimistic", overrides=(
        override(lease.id, "renewal_probability", "add", 0.5), override(quick.id, "exit_cap_rate", "add", 0.005),
    ), db_path=db)

    with pytest.raises(InvestmentVariantValidationError) as error:
        analyze_investment_variant(visible.id, BASE, record.scenario.scenario_id, db_path=db)
    assert {(issue.source, issue.unit_id) for issue in error.value.issues} == {(InvestmentVariantIssueSource.SCENARIO, lease.id)}


# =============================================================================
# The Investment-level channels, end to end
# =============================================================================


def test_transaction_costs_and_the_investment_plan_never_reach_a_unit(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    before = analyze_investment_variant(visible.id, BASE, BASE, db_path=db)

    store.update_visible_investment(
        visible.id, name=visible.name, transaction_price=visible.transaction_price, business_plan=investment_plan(),
        transaction_costs=(cost("fee", 100_000.0), cost("dd", 25_000.0, category=TransactionCostCategory.DUE_DILIGENCE)), db_path=db,
    )
    after = analyze_investment_variant(visible.id, BASE, BASE, db_path=db)

    assert after.unit_results == before.unit_results
    b, a = before.consolidated_results, after.consolidated_results
    assert a.initial_equity - b.initial_equity == pytest.approx(125_000.0 + 200_000.0)
    assert b.levered_cash_flows[0] - a.levered_cash_flows[0] == pytest.approx(325_000.0)
    for unchanged in ("loan_amount", "annual_debt_service", "noi_by_year", "property_cash_flow_by_year", "exit_value"):
        assert getattr(a, unchanged) == getattr(b, unchanged), unchanged
    assert a.levered_owner_cash_flow_by_year[1] == pytest.approx(b.levered_owner_cash_flow_by_year[1] - 375_000.0)


# =============================================================================
# Section 15.4 -- the visible Investment fingerprint
# =============================================================================


def _fingerprint(db: Path, investment_id: str, strategy_id: str = BASE, scenario_id: str = BASE) -> str:
    return investment_variant_fingerprint(investment_id, strategy_id, scenario_id, db_path=db).source_fingerprint


def test_presentation_metadata_never_moves_the_fingerprint(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    store.update_visible_investment(visible.id, name=visible.name, transaction_price=visible.transaction_price,
                                    business_plan=BusinessPlan(), transaction_costs=(cost("tc", 50_000.0),), db_path=db)
    original = _fingerprint(db, visible.id)

    store.update_investment_unit(visible.id, quick.id, label="Tower", unit_kind=UnitKind.COMPONENT, ordinal=9, db_path=db)
    store.update_investment_unit(visible.id, lease.id, label=None, unit_kind=UnitKind.PHASE, ordinal=0, db_path=db)
    store.update_visible_investment(visible.id, name="A new name", transaction_price=visible.transaction_price,
                                    business_plan=BusinessPlan(),
                                    transaction_costs=(cost("tc", 50_000.0, description="Renamed", category=TransactionCostCategory.OTHER),),
                                    db_path=db)
    assert _fingerprint(db, visible.id) == original

    store.update_visible_investment(visible.id, name="A new name", transaction_price=visible.transaction_price,
                                    business_plan=BusinessPlan(), transaction_costs=(cost("renamed-id", 50_000.0),), db_path=db)
    assert _fingerprint(db, visible.id) == original  # a cost's id is canonical order, never economics


@pytest.mark.parametrize(
    "change",
    [
        lambda db, v: store.update_visible_investment(v.id, name=v.name, transaction_price=v.transaction_price + 0.005,
                                                      business_plan=BusinessPlan(), transaction_costs=(), db_path=db),
        lambda db, v: store.update_visible_investment(v.id, name=v.name, transaction_price=v.transaction_price,
                                                      business_plan=BusinessPlan(), transaction_costs=(cost("tc", 50_000.01),), db_path=db),
        lambda db, v: store.update_visible_investment(v.id, name=v.name, transaction_price=v.transaction_price,
                                                      business_plan=investment_plan(), transaction_costs=(), db_path=db),
    ],
)
def test_economic_inputs_move_the_fingerprint(db: Path, change: Any) -> None:
    _, _, _, visible = _mixed(db)
    store.update_visible_investment(visible.id, name=visible.name, transaction_price=visible.transaction_price,
                                    business_plan=BusinessPlan(), transaction_costs=(cost("tc", 50_000.0),), db_path=db)
    original = _fingerprint(db, visible.id)
    change(db, visible)
    assert _fingerprint(db, visible.id) != original


def test_membership_moves_the_fingerprint_and_timing_is_economic(db: Path) -> None:
    first, second = quick_deal(db), quick_deal(db)
    visible = create_investment(db, first)
    one = _fingerprint(db, visible.id)
    store.add_investment_unit(visible.id, member(second.id), transaction_price=price(first) + price(second), db_path=db)
    assert _fingerprint(db, visible.id) != one

    memberships, fingerprints = [member("a")], {"a": "f"}
    common: dict[str, Any] = {"unit_fingerprints": fingerprints, "transaction_price": 1.0, "business_plan": BusinessPlan()}
    at_closing = fingerprint_investment_variant(memberships=memberships, transaction_costs=[cost("c", 1.0)], **common)
    assert fingerprint_investment_variant(memberships=memberships, transaction_costs=[cost("c", 1.0, model_month=12)], **common) != at_closing
    assert fingerprint_investment_variant(memberships=[member("a", acquisition_month=12)], transaction_costs=[cost("c", 1.0)], **common) != at_closing
    assert fingerprint_investment_variant(memberships=[member("a", disposition_month=48)], transaction_costs=[cost("c", 1.0)], **common) != at_closing


def test_the_empty_investment_plan_adds_nothing(db: Path) -> None:
    payload = {"investment": {"units": [["a", "f", 0, None]], "transaction_price": 1.0, "transaction_costs": []}}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert fingerprint_investment_variant(
        memberships=[member("a", label="L", kind=UnitKind.PHASE, ordinal=4)], unit_fingerprints={"a": "f"},
        transaction_price=1, business_plan=BusinessPlan(), transaction_costs=[],
    ) == expected


def test_resolved_fingerprints_revert_exactly(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    base = _fingerprint(db, visible.id)
    restating = store.create_strategy(visible.id, name="Hold as underwritten", overlays=tuple(f4.disposition(d.id, 5) for d in (quick, detailed, lease)), db_path=db)
    assert _fingerprint(db, visible.id, restating.strategy.strategy_id) == base

    scenario = store.create_scenario(visible.id, name="Wider", overrides=(override(quick.id, "exit_cap_rate", "add", 0.005),), db_path=db)
    moved = _fingerprint(db, visible.id, BASE, scenario.scenario.scenario_id)
    assert moved != base
    store.update_scenario(visible.id, scenario.scenario.scenario_id, name="Wider", overrides=(), db_path=db)
    assert _fingerprint(db, visible.id, BASE, scenario.scenario.scenario_id) == base
    assert inspect_investment_variant_inputs(visible.id, BASE, BASE, db_path=db).source_fingerprint == base


def test_a_hidden_one_unit_investment_keeps_its_deal_fingerprint(db: Path) -> None:
    deal = quick_deal(db, business_plan=fx.business_plan())
    record = store.create_scenario_for_deal(deal.id, name="S", db_path=db)
    assert variant_fingerprint(record.investment_id, BASE, BASE, db_path=db).source_fingerprint == deal_fingerprint(deal)
    visible = store.promote_hidden_investment(
        record.investment_id, name="P", transaction_price=price(deal), units=(member(deal.id),),
        business_plan=BusinessPlan(), db_path=db,
    )
    assert _fingerprint(db, visible.id) != deal_fingerprint(deal)  # a visible Investment hashes its own inputs too
    unit_fp = fingerprint_resolved_inputs(resolve_variant_inputs(deal, None, None))
    assert unit_fp == deal_fingerprint(deal)


# =============================================================================
# The routes
# =============================================================================


@pytest.fixture
def client(db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    return TestClient(api_module.app)


def test_the_variant_routes(client: TestClient, db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    base = f"/investments/{visible.id}/investment-variants/{BASE}/{BASE}"

    analysis = client.post(f"{base}/analysis")
    assert analysis.status_code == 200, analysis.text
    body = analysis.json()
    assert body["cache_status"] == "bypassed" and [u["unit_id"] for u in body["unit_results"]] == sorted([quick.id, detailed.id, lease.id])
    assert body["consolidated_results"]["levered_irr_status"] == IrrStatus.DEFINED.value
    assert client.get(f"{base}/fingerprint").json()["source_fingerprint"] == body["source_fingerprint"]
    inputs = client.get(f"{base}/inputs").json()
    assert inputs["source_fingerprint"] == body["source_fingerprint"] and len(inputs["units"]) == 3

    broken = store.create_strategy(visible.id, name="Bid more", overlays=(f4.acquisition(quick.id, purchase_price=price(quick) + 1.0),), db_path=db)
    refused = client.post(f"/investments/{visible.id}/investment-variants/{broken.strategy.strategy_id}/{BASE}/analysis")
    assert refused.status_code == 422 and refused.json()["detail"][0]["source"] == "investment"
    assert client.post(f"/investments/{visible.id}/investment-variants/{'0' * 32}/{BASE}/analysis").status_code == 404
    assert client.post(f"/investments/{visible.id}/variants/{BASE}/{BASE}/analysis").status_code == 409

    hidden = store.create_scenario_for_deal(quick_deal(db).id, name="S", db_path=db)
    assert client.post(f"/investments/{hidden.investment_id}/investment-variants/{BASE}/{BASE}/analysis").status_code == 409
    assert client.post(f"/investments/{hidden.investment_id}/variants/{BASE}/{BASE}/analysis").status_code == 200
