"""Tests for the Phase 7 deterministic sensitivity layer
(``anchor.analysis.sensitivity``).

Covers one-way and two-way sensitivity, and confirms this layer never
duplicates financial calculation: every scenario must go through
``analyze_acquisition``.
"""

from __future__ import annotations

import pytest

from anchor.analysis import (
    SUPPORTED_ASSUMPTIONS,
    SUPPORTED_METRICS,
    OneWaySensitivityResult,
    TwoWaySensitivityResult,
    UnknownAssumptionError,
    UnknownMetricError,
    run_one_way_sensitivity,
    run_two_way_sensitivity,
)
from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition
from anchor.validation import InputValidationError

GOLDEN_INPUTS = AcquisitionInputs(
    purchase_price=50_000_000.0,
    current_noi=2_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.055,
    ltv=0.65,
    interest_rate=0.0525,
    amortization=30,
)


# =============================================================================
# One-way sensitivity
# =============================================================================


def test_one_way_returns_correct_scenario_count() -> None:
    result = run_one_way_sensitivity(
        GOLDEN_INPUTS,
        assumption="exit_cap_rate",
        values=(0.045, 0.05, 0.055, 0.06, 0.065),
        metric="levered_irr",
    )

    assert isinstance(result, OneWaySensitivityResult)
    assert len(result.assumption_values) == 5
    assert len(result.metric_values) == 5


def test_one_way_does_not_mutate_original_inputs() -> None:
    original = GOLDEN_INPUTS

    run_one_way_sensitivity(
        GOLDEN_INPUTS,
        assumption="exit_cap_rate",
        values=(0.045, 0.05, 0.06, 0.065),
        metric="levered_irr",
    )

    assert GOLDEN_INPUTS == original
    assert GOLDEN_INPUTS.exit_cap_rate == 0.055


def test_one_way_baseline_reproduces_base_analysis() -> None:
    base_results = analyze_acquisition(GOLDEN_INPUTS)

    result = run_one_way_sensitivity(
        GOLDEN_INPUTS,
        assumption="exit_cap_rate",
        values=(0.05, 0.06),
        metric="levered_irr",
    )

    assert result.baseline_assumption_value == GOLDEN_INPUTS.exit_cap_rate
    assert result.baseline_metric_value == pytest.approx(base_results.levered_irr)


@pytest.mark.parametrize("assumption", SUPPORTED_ASSUMPTIONS)
def test_one_way_supports_every_supported_assumption(assumption: str) -> None:
    baseline_value = getattr(GOLDEN_INPUTS, assumption)
    result = run_one_way_sensitivity(
        GOLDEN_INPUTS,
        assumption=assumption,
        values=(baseline_value, baseline_value * 1.1 if baseline_value else 0.01),
        metric="levered_irr",
    )

    assert result.assumption == assumption
    assert len(result.metric_values) == 2


@pytest.mark.parametrize("metric", SUPPORTED_METRICS)
def test_one_way_supports_every_supported_metric(metric: str) -> None:
    result = run_one_way_sensitivity(
        GOLDEN_INPUTS,
        assumption="exit_cap_rate",
        values=(0.05, 0.055, 0.06),
        metric=metric,
    )

    assert result.metric == metric
    assert len(result.metric_values) == 3


def test_one_way_exit_cap_scenario_matches_direct_engine_call() -> None:
    result = run_one_way_sensitivity(
        GOLDEN_INPUTS,
        assumption="exit_cap_rate",
        values=(0.05,),
        metric="levered_irr",
    )

    direct_inputs = AcquisitionInputs(
        purchase_price=GOLDEN_INPUTS.purchase_price,
        current_noi=GOLDEN_INPUTS.current_noi,
        occupancy=GOLDEN_INPUTS.occupancy,
        noi_growth=GOLDEN_INPUTS.noi_growth,
        hold_period=GOLDEN_INPUTS.hold_period,
        exit_cap_rate=0.05,
        ltv=GOLDEN_INPUTS.ltv,
        interest_rate=GOLDEN_INPUTS.interest_rate,
        amortization=GOLDEN_INPUTS.amortization,
    )
    expected = analyze_acquisition(direct_inputs).levered_irr

    assert result.metric_values[0] == pytest.approx(expected)


def test_one_way_propagates_none_metric_values() -> None:
    zero_leverage_inputs = AcquisitionInputs(
        purchase_price=GOLDEN_INPUTS.purchase_price,
        current_noi=GOLDEN_INPUTS.current_noi,
        occupancy=GOLDEN_INPUTS.occupancy,
        noi_growth=GOLDEN_INPUTS.noi_growth,
        hold_period=GOLDEN_INPUTS.hold_period,
        exit_cap_rate=GOLDEN_INPUTS.exit_cap_rate,
        ltv=0.0,
        interest_rate=GOLDEN_INPUTS.interest_rate,
        amortization=GOLDEN_INPUTS.amortization,
    )

    result = run_one_way_sensitivity(
        zero_leverage_inputs,
        assumption="exit_cap_rate",
        values=(0.05, 0.06),
        metric="headline_dscr",
    )

    assert result.baseline_metric_value is None
    assert result.metric_values == (None, None)


def test_one_way_invalid_assumption_name_raises() -> None:
    with pytest.raises(UnknownAssumptionError):
        run_one_way_sensitivity(
            GOLDEN_INPUTS,
            assumption="occupancy",
            values=(0.9,),
            metric="levered_irr",
        )


def test_one_way_invalid_metric_name_raises() -> None:
    with pytest.raises(UnknownMetricError):
        run_one_way_sensitivity(
            GOLDEN_INPUTS,
            assumption="exit_cap_rate",
            values=(0.05,),
            metric="cash_on_cash",
        )


def test_one_way_invalid_scenario_value_raises_input_validation_error() -> None:
    with pytest.raises(InputValidationError):
        run_one_way_sensitivity(
            GOLDEN_INPUTS,
            assumption="exit_cap_rate",
            values=(0.05, -0.01),
            metric="levered_irr",
        )


def test_one_way_deterministic_repeated_call() -> None:
    first = run_one_way_sensitivity(
        GOLDEN_INPUTS,
        assumption="ltv",
        values=(0.55, 0.6, 0.65, 0.7, 0.75),
        metric="levered_irr",
    )
    second = run_one_way_sensitivity(
        GOLDEN_INPUTS,
        assumption="ltv",
        values=(0.55, 0.6, 0.65, 0.7, 0.75),
        metric="levered_irr",
    )

    assert first == second


# =============================================================================
# Two-way sensitivity
# =============================================================================


def test_two_way_returns_exact_matrix_dimensions() -> None:
    result = run_two_way_sensitivity(
        GOLDEN_INPUTS,
        row_assumption="noi_growth",
        row_values=(0.01, 0.02, 0.03, 0.04, 0.05),
        column_assumption="exit_cap_rate",
        column_values=(0.045, 0.05, 0.055, 0.06, 0.065),
        metric="levered_irr",
    )

    assert isinstance(result, TwoWaySensitivityResult)
    assert len(result.matrix) == 5
    assert all(len(row) == 5 for row in result.matrix)


def test_two_way_cell_indexing_matches_row_and_column_values() -> None:
    row_values = (0.01, 0.03, 0.05)
    column_values = (0.05, 0.055, 0.06)

    result = run_two_way_sensitivity(
        GOLDEN_INPUTS,
        row_assumption="noi_growth",
        row_values=row_values,
        column_assumption="exit_cap_rate",
        column_values=column_values,
        metric="levered_irr",
    )

    for row_index, noi_growth in enumerate(row_values):
        for column_index, exit_cap_rate in enumerate(column_values):
            scenario_inputs = AcquisitionInputs(
                purchase_price=GOLDEN_INPUTS.purchase_price,
                current_noi=GOLDEN_INPUTS.current_noi,
                occupancy=GOLDEN_INPUTS.occupancy,
                noi_growth=noi_growth,
                hold_period=GOLDEN_INPUTS.hold_period,
                exit_cap_rate=exit_cap_rate,
                ltv=GOLDEN_INPUTS.ltv,
                interest_rate=GOLDEN_INPUTS.interest_rate,
                amortization=GOLDEN_INPUTS.amortization,
            )
            expected = analyze_acquisition(scenario_inputs).levered_irr
            assert result.matrix[row_index][column_index] == pytest.approx(expected)


def test_two_way_baseline_cell_reproduces_base_analysis() -> None:
    base_results = analyze_acquisition(GOLDEN_INPUTS)

    result = run_two_way_sensitivity(
        GOLDEN_INPUTS,
        row_assumption="noi_growth",
        row_values=(0.01, 0.02, 0.03, 0.04, 0.05),
        column_assumption="exit_cap_rate",
        column_values=(0.045, 0.05, 0.055, 0.06, 0.065),
        metric="levered_irr",
    )

    row_index = result.row_values.index(GOLDEN_INPUTS.noi_growth)
    column_index = result.column_values.index(GOLDEN_INPUTS.exit_cap_rate)

    assert result.baseline_row_value == GOLDEN_INPUTS.noi_growth
    assert result.baseline_column_value == GOLDEN_INPUTS.exit_cap_rate
    assert result.baseline_metric_value == pytest.approx(base_results.levered_irr)
    assert result.matrix[row_index][column_index] == pytest.approx(
        base_results.levered_irr
    )


def test_two_way_does_not_mutate_original_inputs() -> None:
    original = GOLDEN_INPUTS

    run_two_way_sensitivity(
        GOLDEN_INPUTS,
        row_assumption="interest_rate",
        row_values=(0.04, 0.05, 0.06),
        column_assumption="ltv",
        column_values=(0.55, 0.65, 0.75),
        metric="levered_irr",
    )

    assert GOLDEN_INPUTS == original


def test_two_way_invalid_row_assumption_raises() -> None:
    with pytest.raises(UnknownAssumptionError):
        run_two_way_sensitivity(
            GOLDEN_INPUTS,
            row_assumption="hold_period",
            row_values=(4, 5, 6),
            column_assumption="exit_cap_rate",
            column_values=(0.05, 0.06),
            metric="levered_irr",
        )


def test_two_way_invalid_column_assumption_raises() -> None:
    with pytest.raises(UnknownAssumptionError):
        run_two_way_sensitivity(
            GOLDEN_INPUTS,
            row_assumption="exit_cap_rate",
            row_values=(0.05, 0.06),
            column_assumption="amortization",
            column_values=(20, 30),
            metric="levered_irr",
        )


def test_two_way_same_row_and_column_assumption_rejected() -> None:
    with pytest.raises(ValueError):
        run_two_way_sensitivity(
            GOLDEN_INPUTS,
            row_assumption="exit_cap_rate",
            row_values=(0.05, 0.06),
            column_assumption="exit_cap_rate",
            column_values=(0.05, 0.06),
            metric="levered_irr",
        )


def test_two_way_invalid_scenario_value_raises_input_validation_error() -> None:
    with pytest.raises(InputValidationError):
        run_two_way_sensitivity(
            GOLDEN_INPUTS,
            row_assumption="ltv",
            row_values=(0.5, 1.5),
            column_assumption="exit_cap_rate",
            column_values=(0.05, 0.06),
            metric="levered_irr",
        )


def test_two_way_deterministic_repeated_call() -> None:
    kwargs = dict(
        row_assumption="interest_rate",
        row_values=(0.0425, 0.0475, 0.0525, 0.0575, 0.0625),
        column_assumption="ltv",
        column_values=(0.55, 0.6, 0.65, 0.7, 0.75),
        metric="headline_dscr",
    )

    first = run_two_way_sensitivity(GOLDEN_INPUTS, **kwargs)
    second = run_two_way_sensitivity(GOLDEN_INPUTS, **kwargs)

    assert first == second
