"""Tests for the standard Phase 7 sensitivity presets
(``anchor.analysis.sensitivity`` preset builders)."""

from __future__ import annotations

import pytest

from anchor.analysis import (
    StandardSensitivityPresets,
    build_exit_cap_noi_growth_preset,
    build_interest_rate_ltv_preset,
    build_purchase_price_exit_cap_preset,
    build_standard_presets,
)
from anchor.contracts import AcquisitionInputs

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


def test_exit_cap_noi_growth_preset_generates_correct_values() -> None:
    result = build_exit_cap_noi_growth_preset(GOLDEN_INPUTS)

    assert result.row_assumption == "noi_growth"
    assert result.column_assumption == "exit_cap_rate"
    assert result.metric == "levered_irr"
    assert result.row_values == pytest.approx((0.01, 0.02, 0.03, 0.04, 0.05))
    assert result.column_values == pytest.approx((0.045, 0.05, 0.055, 0.06, 0.065))
    assert len(result.matrix) == 5
    assert all(len(row) == 5 for row in result.matrix)


def test_purchase_price_exit_cap_preset_generates_correct_values() -> None:
    result = build_purchase_price_exit_cap_preset(GOLDEN_INPUTS)

    assert result.row_assumption == "purchase_price"
    assert result.column_assumption == "exit_cap_rate"
    assert result.metric == "levered_irr"
    assert result.row_values == pytest.approx(
        (45_000_000.0, 47_500_000.0, 50_000_000.0, 52_500_000.0, 55_000_000.0)
    )
    assert result.column_values == pytest.approx((0.045, 0.05, 0.055, 0.06, 0.065))


def test_interest_rate_ltv_preset_generates_correct_values() -> None:
    result = build_interest_rate_ltv_preset(GOLDEN_INPUTS)

    assert result.row_assumption == "interest_rate"
    assert result.column_assumption == "ltv"
    assert result.metric == "levered_irr"
    assert result.row_values == pytest.approx((0.0425, 0.0475, 0.0525, 0.0575, 0.0625))
    assert result.column_values == pytest.approx((0.55, 0.6, 0.65, 0.7, 0.75))


def test_interest_rate_ltv_preset_supports_dscr_metric() -> None:
    result = build_interest_rate_ltv_preset(GOLDEN_INPUTS, metric="headline_dscr")

    assert result.metric == "headline_dscr"
    assert result.row_values == pytest.approx((0.0425, 0.0475, 0.0525, 0.0575, 0.0625))
    assert result.column_values == pytest.approx((0.55, 0.6, 0.65, 0.7, 0.75))


def test_basis_point_offsets_are_not_confused_with_percentage_points() -> None:
    """100 bps == 0.01 == 1 percentage point; the exit-cap offsets and the
    noi-growth offsets must both land on the same decimal deltas even though
    one is described in bps and the other in percentage points."""

    result = build_exit_cap_noi_growth_preset(GOLDEN_INPUTS)

    exit_cap_deltas = [
        round(value - GOLDEN_INPUTS.exit_cap_rate, 10) for value in result.column_values
    ]
    noi_growth_deltas = [
        round(value - GOLDEN_INPUTS.noi_growth, 10) for value in result.row_values
    ]

    assert exit_cap_deltas == [-0.01, -0.005, 0.0, 0.005, 0.01]
    assert noi_growth_deltas == [-0.02, -0.01, 0.0, 0.01, 0.02]


def test_purchase_price_offsets_are_percentages_of_baseline_not_decimal_shifts() -> None:
    result = build_purchase_price_exit_cap_preset(GOLDEN_INPUTS)

    ratios = [value / GOLDEN_INPUTS.purchase_price for value in result.row_values]

    assert ratios == pytest.approx([0.90, 0.95, 1.00, 1.05, 1.10])


def test_exit_cap_preset_omits_out_of_domain_candidates_without_clamping() -> None:
    near_zero_cap_inputs = AcquisitionInputs(
        purchase_price=GOLDEN_INPUTS.purchase_price,
        current_noi=GOLDEN_INPUTS.current_noi,
        occupancy=GOLDEN_INPUTS.occupancy,
        noi_growth=GOLDEN_INPUTS.noi_growth,
        hold_period=GOLDEN_INPUTS.hold_period,
        exit_cap_rate=0.004,
        ltv=GOLDEN_INPUTS.ltv,
        interest_rate=GOLDEN_INPUTS.interest_rate,
        amortization=GOLDEN_INPUTS.amortization,
    )

    result = build_exit_cap_noi_growth_preset(near_zero_cap_inputs)

    # exit_cap_rate must stay > 0: baseline - 100bps and - 50bps are both
    # <= 0 here and must be omitted, not clamped to some other value.
    assert all(value > 0 for value in result.column_values)
    assert len(result.column_values) < 5
    assert 0.004 in result.column_values


def test_ltv_preset_omits_out_of_domain_candidates_without_clamping() -> None:
    high_ltv_inputs = AcquisitionInputs(
        purchase_price=GOLDEN_INPUTS.purchase_price,
        current_noi=GOLDEN_INPUTS.current_noi,
        occupancy=GOLDEN_INPUTS.occupancy,
        noi_growth=GOLDEN_INPUTS.noi_growth,
        hold_period=GOLDEN_INPUTS.hold_period,
        exit_cap_rate=GOLDEN_INPUTS.exit_cap_rate,
        ltv=0.95,
        interest_rate=GOLDEN_INPUTS.interest_rate,
        amortization=GOLDEN_INPUTS.amortization,
    )

    result = build_interest_rate_ltv_preset(high_ltv_inputs)

    # ltv must stay <= 1: baseline + 5pp and +10pp both exceed 1 and must be
    # omitted, not clamped to 1.0.
    assert all(value <= 1.0 for value in result.column_values)
    assert len(result.column_values) < 5
    assert 0.95 in result.column_values


def test_build_standard_presets_returns_all_four_matrices() -> None:
    presets = build_standard_presets(GOLDEN_INPUTS)

    assert isinstance(presets, StandardSensitivityPresets)
    assert presets.exit_cap_noi_growth.metric == "levered_irr"
    assert presets.purchase_price_exit_cap.metric == "levered_irr"
    assert presets.interest_rate_ltv.metric == "levered_irr"
    assert presets.interest_rate_ltv_dscr.metric == "headline_dscr"
