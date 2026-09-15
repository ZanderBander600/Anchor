"""Phase 7 Gate P7.6 -- the Decision Matrix of a visible Investment.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 14.1
(DC-1 to DC-7). Every cell runs the visible Investment variant pathway, so its
Project metrics are the consolidated Investment's; Delta, Worst Case and Range
are the unchanged P7.5 figures over them; one invalid variant is one invalid
cell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
import _p7_4_fixtures as f4  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.deals import decision_matrix as service
from anchor.deals import store
from anchor.deals.contracts import InvestmentStructureError
from anchor.deals.decision_matrix import (
    DecisionMatrixConflictError,
    analyze_decision_matrix,
    analyze_investment_decision_matrix,
)
from anchor.deals.investment_variants import analyze_investment_variant
from anchor.decision.comparison import CellIssueSource, CellStatus, DecisionMetric, decision_matrix_fingerprint

from _p7_2_fixtures import override  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, detailed_deal, lease_level_deal, price, quick_deal  # type: ignore[import-not-found]

BASE = "base"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_6_matrix.db"


def _mixed(db: Path) -> tuple[Any, Any, Any, Any]:
    quick = quick_deal(db, business_plan=fx.business_plan())
    detailed, lease = detailed_deal(db), lease_level_deal(db)
    return quick, detailed, lease, create_investment(db, quick, detailed, lease)


def _cell(report: Any, strategy_id: str, scenario_id: str) -> Any:
    (cell,) = [c for c in report.matrix.cells if (c.strategy_id, c.scenario_id) == (strategy_id, scenario_id)]
    return cell


def _metric(cell: Any, metric: DecisionMetric) -> Any:
    (value,) = [m for m in cell.metrics if m.metric is metric]
    return value


def test_the_base_matrix_is_the_consolidated_investment(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)

    report = analyze_investment_decision_matrix(visible.id, db_path=db)

    (cell,) = report.matrix.cells
    consolidated = analyze_investment_variant(visible.id, BASE, BASE, db_path=db).consolidated_results
    assert cell.status is CellStatus.VALID and cell.results == consolidated
    assert _metric(cell, DecisionMetric.MIN_DSCR).value == consolidated.min_aggregate_dscr
    assert _metric(cell, DecisionMetric.LEVERED_IRR).value == consolidated.levered_irr
    assert [spec.label for spec in report.matrix.metrics][-1] == "Minimum Aggregate DSCR"
    assert [(unit.unit_id, unit.operating_mode.value) for unit in report.units] == sorted(
        (deal.id, deal.operating_mode.value) for deal in (quick, detailed, lease)
    )
    assert report.matrix.matrix_fingerprint == decision_matrix_fingerprint(
        report.matrix.perspective, [(BASE, BASE, cell.source_fingerprint)]
    )


def test_scenarios_and_strategies_use_the_unchanged_cross_cell_figures(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    down = store.create_scenario(visible.id, name="Downside", overrides=(
        override(quick.id, "exit_cap_rate", "add", 0.0075), override(lease.id, "market_rent_psf", "scale", 0.9),
    ), db_path=db)
    up = store.create_scenario(visible.id, name="Upside", overrides=(override(detailed.id, "expense_growth", "add", -0.01),), db_path=db)
    plan = store.create_strategy(visible.id, name="Renovate", overlays=(f4.plan_overlay(detailed.id, f4.renovation_plan()),), db_path=db)

    report = analyze_investment_decision_matrix(visible.id, db_path=db)

    assert len(report.matrix.cells) == 2 * 3 and all(cell.status is CellStatus.VALID for cell in report.matrix.cells)
    for strategy_id in (BASE, plan.strategy.strategy_id):
        values = {
            scenario_id: analyze_investment_variant(visible.id, strategy_id, scenario_id, db_path=db).consolidated_results.levered_irr
            for scenario_id in (BASE, down.scenario.scenario_id, up.scenario.scenario_id)
        }
        (delta,) = [d for d in _cell(report, strategy_id, down.scenario.scenario_id).deltas if d.metric is DecisionMetric.LEVERED_IRR]
        assert delta.value == values[down.scenario.scenario_id] - values[BASE]
        figures = next(f for f in report.matrix.strategy_figures if f.strategy_id == strategy_id)
        (worst,) = [w for w in figures.worst_cases if w.metric is DecisionMetric.LEVERED_IRR]
        (spread,) = [r for r in figures.ranges if r.metric is DecisionMetric.LEVERED_IRR]
        assert worst.value == min(values.values())
        assert spread.spread == max(values.values()) - min(values.values())


def test_different_common_horizons_omit_the_horizon_metrics(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    store.create_strategy(visible.id, name="Seven years", overlays=tuple(f4.disposition(d.id, 7) for d in (quick, detailed, lease)), db_path=db)

    report = analyze_investment_decision_matrix(visible.id, db_path=db)

    assert report.matrix.hold_periods == (5, 7)
    assert {omitted.metric for omitted in report.matrix.omitted_metrics} == {DecisionMetric.EXIT_VALUE, DecisionMetric.MIN_DSCR}
    assert "Minimum Aggregate DSCR" in report.matrix.omitted_metrics[0].message


def test_an_invalid_investment_variant_is_one_invalid_cell_naming_its_unit(db: Path) -> None:
    quick, detailed, lease, visible = _mixed(db)
    broken = store.create_strategy(visible.id, name="Bid more", overlays=(f4.acquisition(quick.id, purchase_price=price(quick) + 1_000.0),), db_path=db)
    risky = store.create_scenario(visible.id, name="Too optimistic", overrides=(override(lease.id, "renewal_probability", "add", 0.5),), db_path=db)

    report = analyze_investment_decision_matrix(visible.id, db_path=db)

    allocation = _cell(report, broken.strategy.strategy_id, BASE)
    assert allocation.status is CellStatus.INVALID and allocation.results is None
    assert [(i.source, i.code, i.field) for i in allocation.issues] == [(CellIssueSource.INVESTMENT, "allocation_mismatch", "transaction_price")]
    scenario_cell = _cell(report, BASE, risky.scenario.scenario_id)
    assert scenario_cell.status is CellStatus.INVALID
    assert all(i.source is CellIssueSource.SCENARIO and (i.field or "").startswith(f"units[{lease.id}]") for i in scenario_cell.issues)
    assert _cell(report, BASE, BASE).status is CellStatus.VALID
    assert report.matrix.matrix_fingerprint is None


def test_a_change_during_the_run_is_a_conflict(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, visible = _mixed(db)
    real = service.analyze_investment_variant

    def and_change(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        current = store.get_visible_investment(visible.id, db_path=db)
        store.update_visible_investment(visible.id, name=current.name, transaction_price=current.transaction_price + 0.001,
                                        business_plan=current.business_plan, transaction_costs=current.transaction_costs, db_path=db)
        return result

    monkeypatch.setattr(service, "analyze_investment_variant", and_change)
    with pytest.raises(DecisionMatrixConflictError):
        analyze_investment_decision_matrix(visible.id, db_path=db)


def test_the_one_unit_matrix_refuses_a_visible_investment_and_keeps_serving_hidden_ones(db: Path) -> None:
    _, _, _, visible = _mixed(db)
    with pytest.raises(InvestmentStructureError, match="Investment Decision Matrix"):
        analyze_decision_matrix(visible.id, db_path=db)
    hidden = store.create_scenario_for_deal(quick_deal(db).id, name="S", db_path=db)
    assert len(analyze_decision_matrix(hidden.investment_id, db_path=db).matrix.cells) == 2
    with pytest.raises(InvestmentStructureError):
        analyze_investment_decision_matrix(hidden.investment_id, db_path=db)


def test_the_matrix_routes(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    client = TestClient(api_module.app)
    _, _, _, visible = _mixed(db)

    response = client.post(f"/investments/{visible.id}/investment-decision-matrix")
    assert response.status_code == 200, response.text
    assert response.json()["matrix"]["cells"][0]["results"]["min_aggregate_dscr"] is not None
    assert client.post(f"/investments/{visible.id}/decision-matrix").status_code == 409
    assert client.post(f"/investments/{'0' * 32}/investment-decision-matrix").status_code == 404
