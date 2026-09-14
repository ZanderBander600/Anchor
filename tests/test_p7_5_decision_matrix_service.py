"""Phase 7 Gate P7.5 -- the Decision Matrix service and routes, over a real
store.

Every cell is measured against the P7.4 variant authority run independently
for the same pair, and every row count is read from the database directly.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from anchor import api as api_module
from anchor.analysis.scenario import SCENARIO_TARGET_REGISTRY
from anchor.analysis.strategy import STRATEGY_OUTCOME_TARGETS
from anchor.contracts import OperatingMode
from anchor.decision.comparison import CellStatus, DecisionMetric, FigureReason
from anchor.deals import decision_matrix as service
from anchor.deals import store, variants
from anchor.deals.contracts import Deal, InvestmentScenario, InvestmentStrategy

import _p7_4_fixtures as f4  # type: ignore[import-not-found]
from _p7_2_fixtures import MODES, create_deal, override, update_deal  # type: ignore[import-not-found]

BASE = "base"
_SCENARIO_OVERRIDE = {
    "quick": ("exit_cap_rate", "add", 0.005),
    "detailed": ("vacancy_credit_loss_pct", "add", 0.02),
    "lease_level": ("market_rent_psf", "scale", 0.9),
}
_UPSIDE_OVERRIDE = {
    "quick": ("exit_cap_rate", "add", -0.0025),
    "detailed": ("revenue_growth", "add", 0.01),
    "lease_level": ("expense_growth", "add", -0.005),
}
_OUTCOME = {"quick": ("noi_growth", 0.04), "detailed": ("revenue_growth", 0.04), "lease_level": ("market_rent_psf", 42.0)}


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_5.db"


def _strategy(deal: Deal, db: Path, *overlays: Any, name: str = "Renovate") -> InvestmentStrategy:
    return store.create_strategy_for_deal(deal.id, name=name, overlays=overlays, db_path=db)


def _scenario(deal: Deal, db: Path, target: tuple[str, str, float], name: str = "Downside") -> InvestmentScenario:
    return store.create_scenario_for_deal(
        deal.id, name=name, description=None, overrides=(override(deal.id, *target),), db_path=db
    )


def _full(mode: str, db: Path) -> tuple[Deal, str, list[str], list[str]]:
    """A Deal with two Strategies and two Scenarios."""

    deal = create_deal(mode, db)
    first = _strategy(deal, db, f4.outcomes(deal.id, f4.outcome(*_OUTCOME[mode])), name="Hold / Lease-Up")
    second = _strategy(deal, db, f4.financing(deal.id), name="Recapitalize")
    down = _scenario(deal, db, _SCENARIO_OVERRIDE[mode])
    up = _scenario(deal, db, _UPSIDE_OVERRIDE[mode], name="Upside")
    return (
        deal,
        first.investment_id,
        [BASE, first.strategy.strategy_id, second.strategy.strategy_id],
        [BASE, down.scenario.scenario_id, up.scenario.scenario_id],
    )


def _project(results: Any) -> Any:
    return getattr(results, "results", results)


def _cell(matrix: Any, strategy_id: str, scenario_id: str) -> Any:
    (found,) = [c for c in matrix.cells if (c.strategy_id, c.scenario_id) == (strategy_id, scenario_id)]
    return found


# =============================================================================
# Every cell is the P7.4 variant authority
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_every_cell_is_the_p7_4_variant_of_that_pair(db: Path, mode: str) -> None:
    deal, investment_id, strategy_ids, scenario_ids = _full(mode, db)

    report = service.analyze_decision_matrix(investment_id, db_path=db)

    assert (report.investment_id, report.unit_id, report.operating_mode) == (investment_id, deal.id, OperatingMode(mode))
    assert [r.strategy_id for r in report.matrix.strategies] == strategy_ids
    assert [c.scenario_id for c in report.matrix.scenarios] == scenario_ids
    for strategy_id in strategy_ids:
        for scenario_id in scenario_ids:
            cell = _cell(report.matrix, strategy_id, scenario_id)
            oracle = variants.analyze_variant(investment_id, strategy_id, scenario_id, db_path=db)
            assert cell.status is CellStatus.VALID
            assert cell.results == _project(oracle.results), (strategy_id, scenario_id)
            assert cell.source_fingerprint == oracle.source_fingerprint
            assert cell.source_fingerprint == variants.variant_fingerprint(
                investment_id, strategy_id, scenario_id, db_path=db
            ).source_fingerprint


def test_all_four_kinds_of_cell_differ_where_their_inputs_differ(db: Path) -> None:
    deal, investment_id, strategy_ids, scenario_ids = _full("quick", db)
    matrix = service.analyze_decision_matrix(investment_id, db_path=db).matrix
    fingerprints = {
        (s, c): _cell(matrix, s, c).source_fingerprint for s in strategy_ids[:2] for c in scenario_ids[:2]
    }
    assert len(set(fingerprints.values())) == 4


def test_the_base_by_base_cell_is_the_deals_own_analysis(db: Path) -> None:
    deal, investment_id, _, _ = _full("quick", db)
    cell = _cell(service.analyze_decision_matrix(investment_id, db_path=db).matrix, BASE, BASE)
    from _p7_2_fixtures import analyze_deal, deal_fingerprint  # type: ignore[import-not-found]

    assert cell.results == analyze_deal(deal)
    assert cell.source_fingerprint == deal_fingerprint(deal)
    assert cell.cache_status == "bypassed"


def test_there_is_no_second_engine_path(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every cell's number comes from the one variant pathway: counting its
    engine seam counts every cell of a Lease-Level matrix, which is never
    cached."""

    _, investment_id, strategy_ids, scenario_ids = _full("lease_level", db)
    calls: list[Any] = []
    original = variants._analyze_resolved  # pyright: ignore[reportPrivateUsage]

    def counted(resolved: Any) -> Any:
        calls.append(resolved)
        return original(resolved)

    monkeypatch.setattr(variants, "_analyze_resolved", counted)
    matrix = service.analyze_decision_matrix(investment_id, db_path=db).matrix
    assert len(calls) == len(strategy_ids) * len(scenario_ids) == len(matrix.cells)


def test_lease_level_cells_are_recomputed_and_quick_cells_use_the_variant_cache(db: Path) -> None:
    _, investment_id, _, _ = _full("lease_level", db)
    matrix = service.analyze_decision_matrix(investment_id, db_path=db).matrix
    assert {c.cache_status for c in matrix.cells} == {"bypassed"}

    _, quick_investment, _, _ = _full("quick", tmp := db.with_name("quick.db"))
    first = service.analyze_decision_matrix(quick_investment, db_path=tmp).matrix
    second = service.analyze_decision_matrix(quick_investment, db_path=tmp).matrix
    non_base = [c for c in first.cells if (c.strategy_id, c.scenario_id) != (BASE, BASE)]
    assert {c.cache_status for c in non_base} == {"miss"}
    assert {c.cache_status for c in second.cells if (c.strategy_id, c.scenario_id) != (BASE, BASE)} == {"hit"}
    assert [c.results for c in first.cells] == [c.results for c in second.cells]


# =============================================================================
# Shapes: only Scenarios, only Strategies, both
# =============================================================================


def test_only_scenarios_is_one_base_strategy_row(db: Path) -> None:
    deal = create_deal("quick", db)
    down = _scenario(deal, db, _SCENARIO_OVERRIDE["quick"])
    matrix = service.analyze_decision_matrix(down.investment_id, db_path=db).matrix
    assert [r.strategy_id for r in matrix.strategies] == [BASE]
    assert [c.scenario_id for c in matrix.scenarios] == [BASE, down.scenario.scenario_id]
    assert matrix.cross_scenario_figures is True
    assert len(matrix.strategy_figures[0].worst_cases) == 7


def test_only_strategies_is_one_base_scenario_column_without_worst_or_range(db: Path) -> None:
    deal = create_deal("quick", db)
    record = _strategy(deal, db, f4.acquisition(deal.id))
    matrix = service.analyze_decision_matrix(record.investment_id, db_path=db).matrix
    assert [r.strategy_id for r in matrix.strategies] == [BASE, record.strategy.strategy_id]
    assert [c.scenario_id for c in matrix.scenarios] == [BASE]
    assert matrix.cross_scenario_figures is False
    assert all(f.worst_cases == () and f.ranges == () for f in matrix.strategy_figures)


# =============================================================================
# An invalid variant is one cell
# =============================================================================


def _invalid_pair(db: Path) -> tuple[str, str, str]:
    """A Strategy whose exit cap a Downside ADD pushes below zero: that one
    variant is invalid; Base x Downside and Strategy x Base are not."""

    deal = create_deal("quick", db)
    record = _strategy(deal, db, f4.outcomes(deal.id, f4.outcome("exit_cap_rate", 0.004)), name="Tight Exit")
    down = _scenario(deal, db, ("exit_cap_rate", "add", -0.005))
    return record.investment_id, record.strategy.strategy_id, down.scenario.scenario_id


def test_an_invalid_variant_stays_in_its_cell_with_the_validators_reason(db: Path) -> None:
    investment_id, strategy_id, down = _invalid_pair(db)
    with pytest.raises(ValueError):
        variants.analyze_variant(investment_id, strategy_id, down, db_path=db)

    matrix = service.analyze_decision_matrix(investment_id, db_path=db).matrix

    broken = _cell(matrix, strategy_id, down)
    assert broken.status is CellStatus.INVALID
    assert broken.results is None and broken.source_fingerprint is None
    assert broken.issues and broken.issues[0].source.value == "scenario"
    assert "exit_cap_rate" in " ".join(i.message for i in broken.issues)
    assert {(c.strategy_id, c.scenario_id) for c in matrix.cells if c.status is CellStatus.INVALID} == {(strategy_id, down)}
    (row,) = [f for f in matrix.strategy_figures if f.strategy_id == strategy_id]
    assert {w.reason for w in row.worst_cases} == {FigureReason.SCENARIO_INVALID}
    assert {r.reason for r in row.ranges} == {FigureReason.SCENARIO_INVALID}
    (base_row,) = [f for f in matrix.strategy_figures if f.strategy_id == BASE]
    assert all(w.value is not None for w in base_row.worst_cases)
    assert matrix.matrix_fingerprint is None


@pytest.mark.parametrize("failure", [RuntimeError("database is locked"), KeyError("x"), ValueError("not a validator")])
def test_an_unexpected_failure_is_never_an_invalid_variant(
    db: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    _, investment_id, _, _ = _full("quick", db)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(service, "analyze_variant", broken)
    with pytest.raises(type(failure)):
        service.analyze_decision_matrix(investment_id, db_path=db)


def test_a_concurrent_change_between_analysis_and_inspection_is_a_conflict(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, investment_id, _, _ = _full("quick", db)
    real = variants.inspect_variant_inputs

    def moved(*args: Any, **kwargs: Any) -> Any:
        return dataclasses.replace(real(*args, **kwargs), source_fingerprint="moved")

    monkeypatch.setattr(service, "inspect_variant_inputs", moved)
    with pytest.raises(service.DecisionMatrixConflictError):
        service.analyze_decision_matrix(investment_id, db_path=db)


# =============================================================================
# Horizons
# =============================================================================


def test_strategies_that_share_the_base_hold_compare_every_metric(db: Path) -> None:
    deal = create_deal("quick", db)
    record = _strategy(deal, db, f4.disposition(deal.id, 5))
    matrix = service.analyze_decision_matrix(record.investment_id, db_path=db).matrix
    assert len(matrix.metrics) == 7 and matrix.hold_periods == (5,)


def test_a_strategy_with_another_hold_omits_exit_value_and_minimum_dscr(db: Path) -> None:
    deal = create_deal("quick", db)
    record = _strategy(deal, db, f4.disposition(deal.id, 7), name="Long Hold")
    _scenario(deal, db, _SCENARIO_OVERRIDE["quick"])
    matrix = service.analyze_decision_matrix(record.investment_id, db_path=db).matrix
    assert matrix.hold_periods == (5, 7)
    assert DecisionMetric.EXIT_VALUE not in {s.metric for s in matrix.metrics}
    assert DecisionMetric.MIN_DSCR not in {s.metric for s in matrix.metrics}
    assert {o.metric for o in matrix.omitted_metrics} == {DecisionMetric.EXIT_VALUE, DecisionMetric.MIN_DSCR}
    assert {r.strategy_id: r.hold_period for r in matrix.strategies} == {BASE: 5, record.strategy.strategy_id: 7}


# =============================================================================
# The matrix fingerprint over a real store
# =============================================================================


def test_renaming_and_redescribing_never_move_the_matrix_fingerprint(db: Path) -> None:
    deal, investment_id, strategy_ids, scenario_ids = _full("quick", db)
    before = service.analyze_decision_matrix(investment_id, db_path=db).matrix.matrix_fingerprint
    assert before is not None

    strategy = store.get_strategy(investment_id, strategy_ids[1], db_path=db).strategy
    store.update_strategy(
        investment_id, strategy.strategy_id, name="Renamed", description="New words", overlays=strategy.overlays, db_path=db
    )
    scenario = store.get_scenario(investment_id, scenario_ids[1], db_path=db).scenario
    store.update_scenario(
        investment_id, scenario.scenario_id, name="Recession", description="Also new", overrides=scenario.overrides, db_path=db
    )

    after = service.analyze_decision_matrix(investment_id, db_path=db).matrix
    assert after.matrix_fingerprint == before
    assert [r.name for r in after.strategies][1] == "Renamed"


def test_an_economic_change_moves_the_matrix_fingerprint(db: Path) -> None:
    deal, investment_id, strategy_ids, _ = _full("quick", db)
    before = service.analyze_decision_matrix(investment_id, db_path=db).matrix.matrix_fingerprint

    strategy = store.get_strategy(investment_id, strategy_ids[2], db_path=db).strategy
    store.update_strategy(
        investment_id, strategy.strategy_id, name=strategy.name, description=None,
        overlays=(f4.financing(deal.id, ltv=0.5),), db_path=db,
    )
    assert service.analyze_decision_matrix(investment_id, db_path=db).matrix.matrix_fingerprint != before

    update_deal(store.get_deal(deal.id, db_path=db), db, purchase_price=13_000_000.0)
    assert service.analyze_decision_matrix(investment_id, db_path=db).matrix.matrix_fingerprint != before


# =============================================================================
# Nothing is stored
# =============================================================================


def test_the_matrix_stores_nothing_beyond_the_p7_4_variant_cache(db: Path) -> None:
    from _p7_2_fixtures import table_names  # type: ignore[import-not-found]

    _, investment_id, _, _ = _full("quick", db)
    before = f4.p7_row_counts(db)
    tables_before = table_names(db)

    service.analyze_decision_matrix(investment_id, db_path=db)

    after = f4.p7_row_counts(db)
    assert {t: n for t, n in after.items() if t != "variant_snapshots"} == {
        t: n for t, n in before.items() if t != "variant_snapshots"
    }
    # Quick: the eight non-Base-x-Base cells are cached, and nothing else.
    assert after["variant_snapshots"] - before["variant_snapshots"] == 8
    assert table_names(db) == tables_before


# =============================================================================
# The routes
# =============================================================================


@pytest.fixture
def client(db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    return TestClient(api_module.app)


def test_the_matrix_route_returns_the_package(client: TestClient, db: Path) -> None:
    _, investment_id, strategy_ids, scenario_ids = _full("detailed", db)
    response = client.post(f"/investments/{investment_id}/decision-matrix")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"investment_id", "unit_id", "operating_mode", "matrix"}
    matrix = body["matrix"]
    assert matrix["perspective"] == "project"
    assert [r["strategy_id"] for r in matrix["strategies"]] == strategy_ids
    assert [c["scenario_id"] for c in matrix["scenarios"]] == scenario_ids
    assert len(matrix["cells"]) == 9
    cell = matrix["cells"][1]
    assert set(cell) == {
        "strategy_id", "scenario_id", "status", "issues", "source_fingerprint", "cache_status",
        "hold_period", "results", "metrics", "deltas",
    }
    assert cell["results"]["levered_irr"] == cell["metrics"][0]["value"]
    assert matrix["metrics"][0] == {
        "metric": "levered_irr", "label": "Levered IRR", "unit": "rate",
        "direction": "higher_is_better", "horizon_dependent": False,
    }
    assert isinstance(matrix["matrix_fingerprint"], str)


def test_the_matrix_route_reports_an_invalid_variant_in_a_successful_response(client: TestClient, db: Path) -> None:
    investment_id, strategy_id, down = _invalid_pair(db)
    response = client.post(f"/investments/{investment_id}/decision-matrix")
    assert response.status_code == 200, response.text
    cells = {(c["strategy_id"], c["scenario_id"]): c for c in response.json()["matrix"]["cells"]}
    assert cells[(strategy_id, down)]["status"] == "invalid"
    assert cells[(strategy_id, down)]["results"] is None


def test_an_unknown_investment_is_a_404_and_a_get_is_refused(client: TestClient, db: Path) -> None:
    create_deal("quick", db)
    assert client.post(f"/investments/{'0' * 32}/decision-matrix").status_code == 404
    assert client.get(f"/investments/{'0' * 32}/decision-matrix").status_code == 405


def test_the_route_maps_a_concurrent_change_to_409(client: TestClient, db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, investment_id, _, _ = _full("quick", db)

    def conflict(*args: Any, **kwargs: Any) -> Any:
        raise service.DecisionMatrixConflictError("changed")

    monkeypatch.setattr(api_module, "analyze_decision_matrix", conflict)
    assert client.post(f"/investments/{investment_id}/decision-matrix").status_code == 409


def test_the_strategy_target_catalog_is_the_whitelist_with_the_registry_units(client: TestClient, db: Path) -> None:
    response = client.get("/strategy-targets")
    assert response.status_code == 200
    assert response.json() == {
        mode.value: [
            {"target": target.value, "units": SCENARIO_TARGET_REGISTRY[target].units}
            for target in STRATEGY_OUTCOME_TARGETS[mode]
        ]
        for mode in OperatingMode
    }
    assert [e["target"] for e in response.json()["quick"]] == ["exit_cap_rate", "noi_growth"]
    assert client.post("/strategy-targets", json={}).status_code == 405


def test_the_strategy_target_catalog_is_derived_at_request_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import MappingProxyType

    narrowed = MappingProxyType({**STRATEGY_OUTCOME_TARGETS, OperatingMode.QUICK: STRATEGY_OUTCOME_TARGETS[OperatingMode.QUICK][:1]})
    monkeypatch.setattr(api_module, "STRATEGY_OUTCOME_TARGETS", narrowed)
    assert [e["target"] for e in client.get("/strategy-targets").json()["quick"]] == ["exit_cap_rate"]


def test_reading_the_strategy_target_catalog_creates_nothing(client: TestClient, db: Path) -> None:
    create_deal("quick", db)
    client.get("/strategy-targets")
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


# =============================================================================
# One coherent package across the whole run (DC-7)
#
# The per-cell check only proves that one cell's analysis and its inspected
# inputs belong to one state. These tests change the economic state *between*
# cells: every earlier cell has already finished its analysis and its own
# check, and every later cell is internally self-consistent in the new state.
# Only the whole-run token can see that the package would mix two states.
# =============================================================================

_WHOLE_RUN_CONFLICT = "strategies or scenarios changed while the decision matrix was running"


def _between_cells(monkeypatch: pytest.MonkeyPatch, before_call: int, change: Any) -> list[tuple[str, str]]:
    """Runs ``change`` just before the ``before_call``-th cell (1-based) is
    analysed, after every earlier cell completed."""

    real = variants.analyze_variant
    calls: list[tuple[str, str]] = []

    def analyze(investment_id: str, strategy_id: str, scenario_id: str, **kwargs: Any) -> Any:
        calls.append((strategy_id, scenario_id))
        if len(calls) == before_call:
            change()
        return real(investment_id, strategy_id, scenario_id, **kwargs)

    monkeypatch.setattr(service, "analyze_variant", analyze)
    return calls


def _rename_strategy(db: Path, investment_id: str, strategy_id: str, *, overlays: Any = None) -> None:
    record = store.get_strategy(investment_id, strategy_id, db_path=db).strategy
    store.update_strategy(
        investment_id, strategy_id,
        name=record.name if overlays is not None else "Renamed mid-run",
        description=record.description if overlays is not None else "New words mid-run",
        overlays=record.overlays if overlays is None else overlays,
        db_path=db,
    )


def _rename_scenario(db: Path, investment_id: str, scenario_id: str, *, overrides: Any = None) -> None:
    record = store.get_scenario(investment_id, scenario_id, db_path=db).scenario
    store.update_scenario(
        investment_id, scenario_id,
        name=record.name if overrides is not None else "Renamed mid-run",
        description=record.description if overrides is not None else "New words mid-run",
        overrides=record.overrides if overrides is None else overrides,
        db_path=db,
    )


#: Each economic change, and the cell it lands before. The full Quick matrix is
#: 3 x 3, row-major: Base Strategy (cells 1-3), Strategy 1 (4-6), Strategy 2
#: (7-9). A deletion lands after the deleted row or column has already run, so
#: every remaining cell still resolves.
_CHANGES: dict[str, tuple[int, Any]] = {
    "base deal": (2, lambda db, deal, inv, s, c: update_deal(store.get_deal(deal.id, db_path=db), db, purchase_price=13_000_000.0)),
    "base business plan": (2, lambda db, deal, inv, s, c: update_deal(store.get_deal(deal.id, db_path=db), db, business_plan=f4.renovation_plan())),
    "strategy overlay": (2, lambda db, deal, inv, s, c: _rename_strategy(db, inv, s[2], overlays=(f4.financing(deal.id, ltv=0.5),))),
    "strategy added": (2, lambda db, deal, inv, s, c: store.create_strategy(inv, name="Late", description=None, overlays=(f4.acquisition(deal.id),), db_path=db)),
    "strategy deleted": (7, lambda db, deal, inv, s, c: store.delete_strategy(inv, s[1], db_path=db)),
    "scenario override": (2, lambda db, deal, inv, s, c: _rename_scenario(db, inv, c[2], overrides=(override(deal.id, "noi_growth", "set", 0.05),))),
    "scenario added": (2, lambda db, deal, inv, s, c: store.create_scenario(inv, name="Late", description=None, overrides=(override(deal.id, "exit_cap_rate", "add", 0.01),), db_path=db)),
    "scenario deleted": (9, lambda db, deal, inv, s, c: store.delete_scenario(inv, c[1], db_path=db)),
}


@pytest.mark.parametrize("change", sorted(_CHANGES))
def test_an_economic_change_between_cells_is_a_whole_matrix_conflict(
    db: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    deal, investment_id, strategy_ids, scenario_ids = _full("quick", db)
    before_call, mutate = _CHANGES[change]
    calls = _between_cells(
        monkeypatch, before_call, lambda: mutate(db, deal, investment_id, strategy_ids, scenario_ids)
    )

    with pytest.raises(service.DecisionMatrixConflictError, match=_WHOLE_RUN_CONFLICT):
        service.analyze_decision_matrix(investment_id, db_path=db)
    # Every cell ran and passed its own analysis-versus-inspection check: the
    # conflict is the whole-run token's, raised only after the last cell.
    assert len(calls) == 9


def test_without_the_whole_run_token_the_mixed_package_would_be_returned(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the per-cell check misses, made visible: with the token
    neutralized the request succeeds, and its Base x Base cell belongs to a
    Deal that no longer exists while every later cell belongs to the new one."""

    deal, investment_id, _, scenario_ids = _full("quick", db)
    _between_cells(
        monkeypatch, 2,
        lambda: update_deal(store.get_deal(deal.id, db_path=db), db, purchase_price=13_000_000.0),
    )
    monkeypatch.setattr(service, "economic_state_token", lambda **kwargs: "unchanged")

    matrix = service.analyze_decision_matrix(investment_id, db_path=db).matrix

    def current(scenario_id: str) -> str:
        return variants.variant_fingerprint(investment_id, BASE, scenario_id, db_path=db).source_fingerprint

    # Cell 1 is the old Deal; cell 2 onwards the new one -- one package, two states.
    assert _cell(matrix, BASE, BASE).source_fingerprint != current(BASE)
    assert _cell(matrix, BASE, scenario_ids[1]).source_fingerprint == current(scenario_ids[1])
    assert _cell(matrix, BASE, BASE).results.total_equity_invested != _cell(matrix, BASE, scenario_ids[1]).results.total_equity_invested
    assert {c.status for c in matrix.cells} == {CellStatus.VALID}


@pytest.mark.parametrize("rename", ["strategy", "scenario"])
def test_a_rename_during_the_run_is_not_a_conflict(
    db: Path, monkeypatch: pytest.MonkeyPatch, rename: str
) -> None:
    deal, investment_id, strategy_ids, scenario_ids = _full("quick", db)
    before = service.analyze_decision_matrix(investment_id, db_path=db).matrix.matrix_fingerprint

    def metadata_only() -> None:
        if rename == "strategy":
            _rename_strategy(db, investment_id, strategy_ids[1])
        else:
            _rename_scenario(db, investment_id, scenario_ids[1])

    calls = _between_cells(monkeypatch, 5, metadata_only)
    report = service.analyze_decision_matrix(investment_id, db_path=db)

    assert len(calls) == 9
    assert {c.status for c in report.matrix.cells} == {CellStatus.VALID}
    assert report.matrix.matrix_fingerprint == before


def test_the_economic_token_reads_economic_content_and_nothing_else(db: Path) -> None:
    deal, investment_id, _, _ = _full("quick", db)
    strategies = store.list_strategies(investment_id, db_path=db)
    scenarios = store.list_scenarios(investment_id, db_path=db)

    # A Strategy with several domains, several outcomes and several plan items,
    # so the order of every inner list can be permuted.
    rich = dataclasses.replace(
        strategies[0],
        strategy=dataclasses.replace(
            strategies[0].strategy,
            overlays=(
                f4.acquisition(deal.id),
                f4.plan_overlay(deal.id, f4.renovation_plan()),
                f4.outcomes(deal.id, f4.outcome("exit_cap_rate", 0.06), f4.outcome("noi_growth", 0.04)),
            ),
        ),
    )
    plan = f4.renovation_plan()
    permuted = dataclasses.replace(
        rich,
        strategy=dataclasses.replace(
            rich.strategy,
            overlays=(
                f4.outcomes(deal.id, f4.outcome("noi_growth", 0.04), f4.outcome("exit_cap_rate", 0.06)),
                f4.plan_overlay(deal.id, dataclasses.replace(plan, capital_items=tuple(reversed(plan.capital_items)))),
                f4.acquisition(deal.id),
            ),
        ),
    )
    records = [rich, *strategies[1:]]

    def token(**changes: Any) -> str:
        arguments: dict[str, Any] = {
            "hidden": True, "unit_ids": [deal.id], "base_fingerprint": "base-fp",
            "strategies": records, "scenarios": scenarios, **changes,
        }
        return service.economic_state_token(**arguments)

    reference = token()
    later = datetime(2030, 1, 1, tzinfo=timezone.utc)
    renamed_strategies = [
        dataclasses.replace(r, strategy=dataclasses.replace(r.strategy, name="Other", description="Other words"), updated_at=later)
        for r in records
    ]
    renamed_scenarios = [
        dataclasses.replace(r, scenario=dataclasses.replace(r.scenario, name="Other", description="Other words"), updated_at=later)
        for r in scenarios
    ]
    # Metadata and order never move it.
    assert token(strategies=renamed_strategies) == reference
    assert token(scenarios=renamed_scenarios) == reference
    assert token(strategies=list(reversed(records)), scenarios=list(reversed(scenarios))) == reference
    assert token(strategies=[permuted, *records[1:]]) == reference
    # Every economic input does.
    moved_overlay = dataclasses.replace(
        records[1], strategy=dataclasses.replace(records[1].strategy, overlays=(f4.financing(deal.id, ltv=0.5),))
    )
    moved_override = dataclasses.replace(
        scenarios[0],
        scenario=dataclasses.replace(scenarios[0].scenario, overrides=(override(deal.id, "exit_cap_rate", "add", 0.02),)),
    )
    added_strategy = dataclasses.replace(records[1], strategy=dataclasses.replace(records[1].strategy, strategy_id="another"))
    economic = {
        "base fingerprint": token(base_fingerprint="other-fp"),
        "unit membership": token(unit_ids=["other-unit"]),
        "visibility": token(hidden=False),
        "strategy overlay": token(strategies=[records[0], moved_overlay, *records[2:]]),
        "strategy removed": token(strategies=records[:-1]),
        "strategy added": token(strategies=[*records, added_strategy]),
        "scenario override": token(scenarios=[moved_override, *scenarios[1:]]),
        "scenario removed": token(scenarios=scenarios[:-1]),
    }
    assert {name: moved for name, moved in economic.items() if moved == reference} == {}
