"""Phase 7 Gate P7.5 -- the cross-cell decision figures, golden.

``anchor.decision.comparison`` over hand-set ``AcquisitionResults``: one real
engine result, with only the compared fields replaced, so every expected figure
is stated literally here and independently of the code under test.

The Base Strategy row is given different values from the Strategy under test,
so a Delta taken against the wrong row -- another Strategy rather than the same
Strategy's Base Scenario -- produces a different number and fails.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from anchor.analysis import analyze_quick_acquisition_with_business_plan
from anchor.business_plan import BusinessPlan
from anchor.decision.comparison import (
    PROJECT_METRIC_CATALOG,
    AxisMember,
    CellInput,
    CellIssue,
    CellIssueSource,
    CellStatus,
    DecisionComparisonError,
    DecisionMatrix,
    DecisionMetric,
    FigureReason,
    MetricDirection,
    OmissionReason,
    compare_decision_matrix,
)
from anchor.engine.contracts import AcquisitionResults, IrrStatus

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]

_REAL: AcquisitionResults = analyze_quick_acquisition_with_business_plan(
    fx.quick_inputs(), business_plan=BusinessPlan()
)

BASE = "base"
HOLD = "st-hold"
DOWN = "sc-down"
UP = "sc-up"

STRATEGIES = (
    AxisMember(id=BASE, name="Base Strategy", is_base=True),
    AxisMember(id=HOLD, name="Hold / Lease-Up", is_base=False),
)
SCENARIOS = (
    AxisMember(id=BASE, name="Base Scenario", is_base=True),
    AxisMember(id=DOWN, name="Downside", is_base=False),
    AxisMember(id=UP, name="Upside", is_base=False),
)

#: (levered IRR, Total Equity Invested) per cell. The Strategy under test has
#: Base 12% / Downside 9% / Upside 15% and TEI $10M / $12M / $9M. The Base
#: Strategy row is deliberately different.
_FIGURES = {
    (BASE, BASE): (0.20, 8_000_000.0),
    (BASE, DOWN): (0.14, 8_500_000.0),
    (BASE, UP): (0.26, 7_000_000.0),
    (HOLD, BASE): (0.12, 10_000_000.0),
    (HOLD, DOWN): (0.09, 12_000_000.0),
    (HOLD, UP): (0.15, 9_000_000.0),
}


def results(**fields: Any) -> AcquisitionResults:
    return dataclasses.replace(_REAL, **fields)


def valid(strategy_id: str, scenario_id: str, figures: AcquisitionResults, *, hold: int = 5, fingerprint: str | None = None) -> CellInput:
    return CellInput(
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        results=figures,
        source_fingerprint=fingerprint or f"fp-{strategy_id}-{scenario_id}",
        cache_status="miss",
        hold_period=hold,
    )


def invalid(strategy_id: str, scenario_id: str) -> CellInput:
    return CellInput(
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        results=None,
        source_fingerprint=None,
        cache_status=None,
        hold_period=None,
        issues=(
            CellIssue(
                source=CellIssueSource.SCENARIO,
                code="resolved_input_invalid",
                message="exit_cap_rate must be greater than 0.",
                field="exit_cap_rate",
            ),
        ),
    )


def golden_cells(**replacements: CellInput) -> list[CellInput]:
    cells = {
        key: valid(*key, results(levered_irr=irr, levered_irr_status=IrrStatus.DEFINED, total_equity_invested=tei))
        for key, (irr, tei) in _FIGURES.items()
    }
    for cell in replacements.values():
        cells[(cell.strategy_id, cell.scenario_id)] = cell
    return list(cells.values())


def compare(cells: list[CellInput], strategies: tuple[AxisMember, ...] = STRATEGIES, scenarios: tuple[AxisMember, ...] = SCENARIOS) -> DecisionMatrix:
    return compare_decision_matrix(strategies=strategies, scenarios=scenarios, cells=cells)


def cell_of(matrix: DecisionMatrix, strategy_id: str, scenario_id: str) -> Any:
    (found,) = [c for c in matrix.cells if (c.strategy_id, c.scenario_id) == (strategy_id, scenario_id)]
    return found


def delta(matrix: DecisionMatrix, strategy_id: str, scenario_id: str, metric: DecisionMetric) -> Any:
    (found,) = [d for d in cell_of(matrix, strategy_id, scenario_id).deltas if d.metric is metric]
    return found


def value(matrix: DecisionMatrix, strategy_id: str, scenario_id: str, metric: DecisionMetric) -> Any:
    (found,) = [m for m in cell_of(matrix, strategy_id, scenario_id).metrics if m.metric is metric]
    return found


def worst(matrix: DecisionMatrix, strategy_id: str, metric: DecisionMetric) -> Any:
    (row,) = [r for r in matrix.strategy_figures if r.strategy_id == strategy_id]
    (found,) = [w for w in row.worst_cases if w.metric is metric]
    return found


def spread(matrix: DecisionMatrix, strategy_id: str, metric: DecisionMetric) -> Any:
    (row,) = [r for r in matrix.strategy_figures if r.strategy_id == strategy_id]
    (found,) = [r for r in row.ranges if r.metric is metric]
    return found


IRR = DecisionMetric.LEVERED_IRR
TEI = DecisionMetric.TOTAL_EQUITY_INVESTED


# =============================================================================
# The Project catalog
# =============================================================================


def test_the_project_catalog_is_the_seven_ratified_metrics_in_order() -> None:
    assert [(s.metric.value, s.direction.value, s.horizon_dependent) for s in PROJECT_METRIC_CATALOG] == [
        ("levered_irr", "higher_is_better", False),
        ("unlevered_irr", "higher_is_better", False),
        ("equity_multiple", "higher_is_better", False),
        ("total_profit", "higher_is_better", False),
        ("total_equity_invested", "lower_is_better", False),
        ("exit_value", "higher_is_better", True),
        ("min_dscr", "higher_is_better", True),
    ]


def test_every_metric_is_the_acquisition_results_field_of_the_same_name() -> None:
    matrix = compare([valid(BASE, BASE, _REAL)], scenarios=SCENARIOS[:1], strategies=STRATEGIES[:1])
    for metric_value in matrix.cells[0].metrics:
        assert metric_value.value == getattr(_REAL, metric_value.metric.value), metric_value.metric


# =============================================================================
# Delta vs Base Scenario -- same Strategy, different Scenario
# =============================================================================


def test_delta_is_scenario_minus_the_same_strategys_base_scenario() -> None:
    matrix = compare(golden_cells())

    assert delta(matrix, HOLD, DOWN, IRR).value == 0.09 - 0.12
    assert delta(matrix, HOLD, DOWN, IRR).value == pytest.approx(-0.03, abs=1e-12)
    assert delta(matrix, HOLD, UP, IRR).value == pytest.approx(0.03, abs=1e-12)
    assert delta(matrix, BASE, DOWN, IRR).value == pytest.approx(0.14 - 0.20, abs=1e-12)
    assert delta(matrix, HOLD, DOWN, TEI).value == 2_000_000.0


def test_the_base_scenario_cell_is_the_baseline_with_a_zero_delta() -> None:
    matrix = compare(golden_cells())
    baseline = delta(matrix, HOLD, BASE, IRR)
    assert (baseline.value, baseline.is_baseline, baseline.reason) == (0.0, True, None)
    assert delta(matrix, HOLD, DOWN, IRR).is_baseline is False


def test_a_delta_is_never_taken_against_the_base_strategy() -> None:
    """The M1 mutant: 0.09 - 0.20 = -0.11 rather than -0.03."""

    matrix = compare(golden_cells())
    assert delta(matrix, HOLD, DOWN, IRR).value != pytest.approx(0.09 - 0.20)


def test_a_delta_records_the_two_cells_it_read() -> None:
    sources = delta(compare(golden_cells()), HOLD, DOWN, IRR).sources
    assert [(s.strategy_id, s.scenario_id, s.source_fingerprint) for s in sources] == [
        (HOLD, BASE, "fp-st-hold-base"),
        (HOLD, DOWN, "fp-st-hold-sc-down"),
    ]


# =============================================================================
# Worst Case across Scenarios
# =============================================================================


def test_worst_levered_irr_is_the_lowest_and_names_its_scenario() -> None:
    found = worst(compare(golden_cells()), HOLD, IRR)
    assert (found.value, found.scenario_id, found.scenario_name, found.direction) == (
        0.09, DOWN, "Downside", MetricDirection.HIGHER_IS_BETTER,
    )


def test_worst_total_equity_invested_is_the_highest() -> None:
    """The M2 mutant takes the minimum, $9M Upside."""

    found = worst(compare(golden_cells()), HOLD, TEI)
    assert (found.value, found.scenario_id, found.direction) == (12_000_000.0, DOWN, MetricDirection.LOWER_IS_BETTER)


def test_a_tie_goes_to_stable_scenario_identity_not_display_order() -> None:
    """Two Scenarios tie at the worst IRR. They are displayed ``sc-b`` first;
    identity order is ``sc-a`` first, and that is what Worst Case reports."""

    scenarios = (
        AxisMember(id=BASE, name="Base Scenario", is_base=True),
        AxisMember(id="sc-b", name="Recession", is_base=False),
        AxisMember(id="sc-a", name="Rate Shock", is_base=False),
    )
    irrs = {BASE: 0.12, "sc-b": 0.08, "sc-a": 0.08}
    cells = [valid(BASE, s, results(levered_irr=irr)) for s, irr in irrs.items()]
    found = worst(compare(cells, strategies=STRATEGIES[:1], scenarios=scenarios), BASE, IRR)
    assert (found.value, found.scenario_id) == (0.08, "sc-a")

    reordered = worst(compare(cells, strategies=STRATEGIES[:1], scenarios=(scenarios[0], scenarios[2], scenarios[1])), BASE, IRR)
    assert reordered.scenario_id == "sc-a"


def test_a_tie_with_the_base_scenario_goes_to_the_base_scenario() -> None:
    cells = [valid(BASE, s, results(levered_irr=irr)) for s, irr in {BASE: 0.09, DOWN: 0.09, UP: 0.15}.items()]
    found = worst(compare(cells, strategies=STRATEGIES[:1]), BASE, IRR)
    assert found.scenario_id == BASE


# =============================================================================
# Range across Scenarios
# =============================================================================


def test_range_is_the_spread_between_the_extremes_on_the_internal_scale() -> None:
    found = spread(compare(golden_cells()), HOLD, IRR)
    assert (found.minimum, found.minimum_scenario_id, found.maximum, found.maximum_scenario_id) == (
        0.09, DOWN, 0.15, UP,
    )
    assert found.spread == 0.15 - 0.09
    assert found.spread == pytest.approx(0.06, abs=1e-12)


def test_range_has_no_direction_and_is_the_same_for_tei() -> None:
    found = spread(compare(golden_cells()), HOLD, TEI)
    assert (found.minimum, found.minimum_scenario_id, found.maximum, found.maximum_scenario_id, found.spread) == (
        9_000_000.0, UP, 12_000_000.0, DOWN, 3_000_000.0,
    )


def test_worst_and_range_record_every_cell_of_the_row() -> None:
    matrix = compare(golden_cells())
    expected = [(HOLD, s, f"fp-{HOLD}-{s}") for s in (BASE, DOWN, UP)]
    for figure in (worst(matrix, HOLD, IRR), spread(matrix, HOLD, IRR)):
        assert [(s.strategy_id, s.scenario_id, s.source_fingerprint) for s in figure.sources] == expected


def test_worst_and_range_are_per_strategy_and_never_compare_strategies() -> None:
    matrix = compare(golden_cells())
    assert worst(matrix, BASE, IRR).value == 0.14
    assert worst(matrix, HOLD, IRR).value == 0.09
    assert {f.strategy_id for f in matrix.strategy_figures} == {BASE, HOLD}


# =============================================================================
# Invalid variants and figures the engine does not report
# =============================================================================


def test_one_invalid_scenario_stays_in_its_cell() -> None:
    matrix = compare(golden_cells(broken=invalid(HOLD, DOWN)))

    broken = cell_of(matrix, HOLD, DOWN)
    assert broken.status is CellStatus.INVALID and broken.results is None
    assert [i.message for i in broken.issues] == ["exit_cap_rate must be greater than 0."]
    assert value(matrix, HOLD, DOWN, IRR).reason is FigureReason.INVALID_VARIANT
    assert cell_of(matrix, HOLD, UP).status is CellStatus.VALID
    assert cell_of(matrix, BASE, DOWN).status is CellStatus.VALID
    # A Delta between two valid cells is still there.
    assert delta(matrix, HOLD, UP, IRR).value == pytest.approx(0.03, abs=1e-12)
    assert (delta(matrix, HOLD, DOWN, IRR).value, delta(matrix, HOLD, DOWN, IRR).reason) == (
        None, FigureReason.INVALID_VARIANT,
    )


def test_worst_and_range_never_skip_an_invalid_scenario() -> None:
    """The M3 mutant would report Worst 12% Base -- safer than the truth."""

    matrix = compare(golden_cells(broken=invalid(HOLD, DOWN)))
    for figure in (worst(matrix, HOLD, IRR), spread(matrix, HOLD, IRR), worst(matrix, HOLD, TEI)):
        assert figure.reason is FigureReason.SCENARIO_INVALID
        assert figure.unavailable_scenario_ids == (DOWN,)
        assert "Downside" in (figure.message or "")
        assert figure.sources == ()
    assert worst(matrix, HOLD, IRR).value is None and spread(matrix, HOLD, IRR).spread is None
    # The other Strategy's row is complete, so its figures stand.
    assert worst(matrix, BASE, IRR).value == 0.14


def test_an_invalid_base_scenario_leaves_no_delta_in_the_row() -> None:
    matrix = compare(golden_cells(broken=invalid(HOLD, BASE)))
    assert delta(matrix, HOLD, UP, IRR).reason is FigureReason.BASE_SCENARIO_INVALID
    assert delta(matrix, HOLD, UP, IRR).value is None
    assert delta(matrix, BASE, UP, IRR).value == pytest.approx(0.06, abs=1e-12)


def test_an_undefined_irr_is_na_everywhere_it_is_needed() -> None:
    undefined = valid(
        HOLD, DOWN, results(levered_irr=None, levered_irr_status=IrrStatus.MULTIPLE_SIGN_CHANGES, total_equity_invested=12_000_000.0)
    )
    matrix = compare(golden_cells(odd=undefined))

    cell_value = value(matrix, HOLD, DOWN, IRR)
    assert (cell_value.value, cell_value.reason, cell_value.irr_status) == (
        None, FigureReason.IRR_NOT_DEFINED, IrrStatus.MULTIPLE_SIGN_CHANGES,
    )
    assert (delta(matrix, HOLD, DOWN, IRR).value, delta(matrix, HOLD, DOWN, IRR).reason) == (
        None, FigureReason.IRR_NOT_DEFINED,
    )
    assert worst(matrix, HOLD, IRR).reason is FigureReason.SCENARIO_NOT_REPORTED
    assert spread(matrix, HOLD, IRR).reason is FigureReason.SCENARIO_NOT_REPORTED
    # Every other metric of that valid cell still reports.
    assert worst(matrix, HOLD, TEI).value == 12_000_000.0
    assert delta(matrix, HOLD, DOWN, TEI).value == 2_000_000.0


def test_an_undefined_base_irr_leaves_the_rows_deltas_na() -> None:
    undefined = valid(HOLD, BASE, results(levered_irr=None, levered_irr_status=IrrStatus.NO_POSITIVE_CASH_FLOW))
    matrix = compare(golden_cells(odd=undefined))
    assert delta(matrix, HOLD, UP, IRR).reason is FigureReason.BASE_SCENARIO_NOT_REPORTED
    assert delta(matrix, HOLD, BASE, IRR).value is None


def test_a_status_other_than_defined_is_never_a_value_even_with_a_number() -> None:
    odd = valid(BASE, BASE, results(levered_irr=0.11, levered_irr_status=IrrStatus.NUMERICAL_FAILURE))
    matrix = compare([odd], strategies=STRATEGIES[:1], scenarios=SCENARIOS[:1])
    assert value(matrix, BASE, BASE, IRR).value is None


def test_an_unreported_minimum_dscr_is_na_with_its_reason() -> None:
    no_debt = valid(BASE, BASE, results(min_dscr=None))
    matrix = compare([no_debt], strategies=STRATEGIES[:1], scenarios=SCENARIOS[:1])
    found = value(matrix, BASE, BASE, DecisionMetric.MIN_DSCR)
    assert (found.value, found.reason) == (None, FigureReason.NOT_REPORTED)


# =============================================================================
# Horizons
# =============================================================================


def _horizon_matrix(holds: dict[str, int]) -> DecisionMatrix:
    strategies = (STRATEGIES[0], STRATEGIES[1], AxisMember(id="st-reno", name="Renovate", is_base=False))
    cells = [valid(s.id, c.id, _REAL, hold=holds[s.id]) for s in strategies for c in SCENARIOS]
    return compare(cells, strategies=strategies)


def test_one_shared_hold_period_compares_all_seven_metrics() -> None:
    matrix = _horizon_matrix({BASE: 5, HOLD: 5, "st-reno": 5})
    assert [s.metric for s in matrix.metrics] == [s.metric for s in PROJECT_METRIC_CATALOG]
    assert matrix.omitted_metrics == () and matrix.hold_periods == (5,)


def test_different_hold_periods_compare_only_the_horizon_independent_metrics() -> None:
    """The M6 mutant would still expose Exit Value and Minimum DSCR."""

    matrix = _horizon_matrix({BASE: 5, HOLD: 7, "st-reno": 5})
    independent = [
        DecisionMetric.LEVERED_IRR, DecisionMetric.UNLEVERED_IRR, DecisionMetric.EQUITY_MULTIPLE,
        DecisionMetric.TOTAL_PROFIT, DecisionMetric.TOTAL_EQUITY_INVESTED,
    ]
    assert [s.metric for s in matrix.metrics] == independent
    assert [(o.metric, o.reason) for o in matrix.omitted_metrics] == [
        (DecisionMetric.EXIT_VALUE, OmissionReason.DIFFERENT_HOLD_PERIODS),
        (DecisionMetric.MIN_DSCR, OmissionReason.DIFFERENT_HOLD_PERIODS),
    ]
    assert matrix.omitted_metrics[0].message == (
        "Strategies use different hold periods (5 and 7 years). Exit Value and Minimum DSCR "
        "are not compared across different horizons."
    )
    assert matrix.hold_periods == (5, 7)
    for cell in matrix.cells:
        assert [m.metric for m in cell.metrics] == independent
        assert [d.metric for d in cell.deltas] == independent
    for row in matrix.strategy_figures:
        assert [w.metric for w in row.worst_cases] == independent
        assert [r.metric for r in row.ranges] == independent
    assert {r.strategy_id: r.hold_period for r in matrix.strategies} == {BASE: 5, HOLD: 7, "st-reno": 5}


def test_an_invalid_strategys_unresolved_hold_never_decides_the_horizon() -> None:
    strategies = STRATEGIES
    cells = [valid(BASE, c.id, _REAL, hold=5) for c in SCENARIOS] + [invalid(HOLD, c.id) for c in SCENARIOS]
    matrix = compare(cells, strategies=strategies)
    assert len(matrix.metrics) == 7 and matrix.hold_periods == (5,)
    assert {r.strategy_id: r.hold_period for r in matrix.strategies} == {BASE: 5, HOLD: None}


# =============================================================================
# Only Scenarios, only Strategies
# =============================================================================


def test_without_a_persisted_scenario_there_is_no_worst_or_range() -> None:
    cells = [valid(s.id, BASE, _REAL) for s in STRATEGIES]
    matrix = compare(cells, scenarios=SCENARIOS[:1])
    assert matrix.cross_scenario_figures is False
    assert all(r.worst_cases == () and r.ranges == () for r in matrix.strategy_figures)
    assert all(d.is_baseline for c in matrix.cells for d in c.deltas)


def test_with_only_scenarios_there_is_one_base_strategy_row() -> None:
    cells = [valid(BASE, c.id, _REAL) for c in SCENARIOS]
    matrix = compare(cells, strategies=STRATEGIES[:1])
    assert [r.strategy_id for r in matrix.strategies] == [BASE]
    assert [c.scenario_id for c in matrix.scenarios] == [BASE, DOWN, UP]
    assert matrix.cross_scenario_figures is True


def test_cells_are_row_major_in_presentation_order() -> None:
    matrix = compare(golden_cells())
    assert [(c.strategy_id, c.scenario_id) for c in matrix.cells] == [
        (s.id, c.id) for s in STRATEGIES for c in SCENARIOS
    ]


# =============================================================================
# The matrix fingerprint
# =============================================================================


def _renamed(members: tuple[AxisMember, ...]) -> tuple[AxisMember, ...]:
    return tuple(dataclasses.replace(m, name=f"{m.name} (renamed)") for m in members)


def test_names_never_reach_the_matrix_fingerprint() -> None:
    """The M7 mutant hashes display names too."""

    original = compare(golden_cells())
    renamed = compare(golden_cells(), strategies=_renamed(STRATEGIES), scenarios=_renamed(SCENARIOS))
    assert original.matrix_fingerprint is not None
    assert renamed.matrix_fingerprint == original.matrix_fingerprint


def test_display_order_never_reaches_the_matrix_fingerprint() -> None:
    original = compare(golden_cells())
    reordered = compare(
        list(reversed(golden_cells())),
        strategies=(STRATEGIES[1], STRATEGIES[0]),
        scenarios=(SCENARIOS[2], SCENARIOS[0], SCENARIOS[1]),
    )
    assert reordered.matrix_fingerprint == original.matrix_fingerprint


def test_the_same_cell_fingerprints_give_the_same_matrix_fingerprint() -> None:
    other_figures = [dataclasses.replace(c, results=_REAL) for c in golden_cells()]
    assert compare(other_figures).matrix_fingerprint == compare(golden_cells()).matrix_fingerprint


def test_an_economic_change_in_one_cell_moves_the_matrix_fingerprint() -> None:
    changed = valid(HOLD, UP, results(levered_irr=0.15), fingerprint="fp-changed")
    assert compare(golden_cells(c=changed)).matrix_fingerprint != compare(golden_cells()).matrix_fingerprint


def test_an_invalid_cell_leaves_the_matrix_without_a_fingerprint() -> None:
    matrix = compare(golden_cells(broken=invalid(HOLD, DOWN)))
    assert matrix.matrix_fingerprint is None
    assert matrix.matrix_fingerprint_reason == (
        "No matrix fingerprint: 1 variant is invalid, and every cell needs a current source fingerprint."
    )


# =============================================================================
# Structure is a programming error, never a financial finding
# =============================================================================


@pytest.mark.parametrize(
    "case",
    ["missing cell", "duplicate cell", "two bases", "no base", "results and issues", "results without hold"],
)
def test_an_incoherent_matrix_is_refused_as_a_programming_error(case: str) -> None:
    cells = golden_cells()
    strategies, scenarios = STRATEGIES, SCENARIOS
    if case == "missing cell":
        cells = cells[1:]
    elif case == "duplicate cell":
        cells = [*cells, cells[0]]
    elif case == "two bases":
        scenarios = (*SCENARIOS, AxisMember(id="other", name="Other", is_base=True))
    elif case == "no base":
        strategies = (dataclasses.replace(STRATEGIES[0], is_base=False), STRATEGIES[1])
    elif case == "results and issues":
        cells[0] = dataclasses.replace(cells[0], issues=invalid(BASE, BASE).issues)
    else:
        cells[0] = dataclasses.replace(cells[0], hold_period=None)
    with pytest.raises(DecisionComparisonError) as raised:
        compare(cells, strategies=strategies, scenarios=scenarios)
    assert not isinstance(raised.value, ValueError)
