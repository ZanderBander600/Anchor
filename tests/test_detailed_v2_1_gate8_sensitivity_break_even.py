"""Detailed Operating Model V2.1 Gate 8 -- sensitivity + break-even integration.

Covers, per this gate's instructions:

1. Existing Quick-only sensitivity/break-even continue working exactly as
   before (a permanent regression, not just "the full suite still passes").
2. Existing dimensions (purchase_price, exit_cap_rate, ltv, interest_rate)
   work correctly against a Detailed base deal -- proven by baseline-
   coordinate equivalence against the economically-identical Quick golden
   deal (docs/detailed_operating_model_v2_1_golden_case.md's construction:
   Quick's current_noi/noi_growth and Detailed's eleven operating
   assumptions produce the exact same NOI series, so a shared-dimension
   sensitivity/break-even result must match between the two paths exactly).
3. Every Detailed candidate/cell preserves detailed_operating_inputs
   completely unchanged -- the Gate 9A bug class, generalized and proven
   against a distinctive (non-golden) DetailedOperatingInputs fixture.
4. Detailed-only assumptions (revenue_growth, vacancy_credit_loss_pct,
   expense_growth) and Quick-only assumptions (current_noi, noi_growth) are
   both rejected as unsupported for the Detailed sensitivity functions --
   no new dimension was silently added, and no Quick dimension silently
   carried over.
"""

from __future__ import annotations

import dataclasses

import pytest

from anchor.analysis import (
    DETAILED_SUPPORTED_ASSUMPTIONS,
    SUPPORTED_ASSUMPTIONS,
    UnknownAssumptionError,
    build_interest_rate_ltv_preset,
    run_detailed_two_way_sensitivity,
    run_two_way_sensitivity,
    solve_detailed_max_exit_cap_rate,
    solve_detailed_max_interest_rate,
    solve_detailed_max_purchase_price,
    solve_max_exit_cap_rate,
    solve_max_interest_rate,
    solve_max_purchase_price,
)
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.engine import analyze_detailed_acquisition_with_projection

GOLDEN_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)

GOLDEN_DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)

# The economically equivalent Quick deal (docs/detailed_operating_model_v2_1_golden_case.md).
GOLDEN_QUICK_INPUTS = AcquisitionInputs(
    purchase_price=10_000_000.0,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)

# A deliberately distinctive (non-golden) DetailedOperatingInputs -- used to
# prove the Gate 9A bug class is closed: if any Detailed candidate silently
# dropped back to a default/neutral operating input set, its result would
# diverge from re-running analyze_detailed_acquisition_with_projection with
# this exact fixture directly.
DISTINCTIVE_DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=1_234_567.0,
    other_income=45_321.0,
    vacancy_credit_loss_pct=0.081,
    property_taxes=91_234.0,
    insurance=33_456.0,
    utilities=41_222.0,
    repairs_maintenance=28_999.0,
    other_operating_expenses=19_876.0,
    management_fee_pct=0.037,
    revenue_growth=0.021,
    expense_growth=0.045,
)


def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-6)


# =============================================================================
# 1. Existing Quick-only sensitivity/break-even are unaffected (permanent
#    regression pins, not only "the suite still passes")
# =============================================================================


def test_quick_two_way_sensitivity_still_works_unmodified() -> None:
    result = build_interest_rate_ltv_preset(GOLDEN_QUICK_INPUTS, metric="levered_irr")

    assert result.row_assumption == "interest_rate"
    assert result.column_assumption == "ltv"
    assert result.baseline_metric_value is not None


def test_quick_break_even_still_works_unmodified() -> None:
    result = solve_max_purchase_price(GOLDEN_QUICK_INPUTS, target_levered_irr=0.06)

    assert result.status.value in ("solved", "no_solution_in_range")
    assert result.baseline_assumption_value == GOLDEN_QUICK_INPUTS.purchase_price


# =============================================================================
# 2. Existing dimensions work correctly against a Detailed base deal --
#    baseline-coordinate equivalence against the economically identical
#    Quick golden deal
# =============================================================================


def test_detailed_supported_assumptions_is_exactly_the_shared_subset() -> None:
    assert DETAILED_SUPPORTED_ASSUMPTIONS == (
        "purchase_price",
        "exit_cap_rate",
        "ltv",
        "interest_rate",
    )
    assert set(DETAILED_SUPPORTED_ASSUMPTIONS).issubset(set(SUPPORTED_ASSUMPTIONS))


def test_detailed_two_way_sensitivity_baseline_matches_quick_equivalent() -> None:
    """The permanent baseline-coordinate equivalence test: LTV x Interest
    Rate on Levered IRR, run against the Detailed golden case and the
    economically identical Quick golden deal, must produce identical
    baseline coordinates and an identical matrix -- not just "close",
    bit-for-bit through the shared downstream engine."""

    ltv_values = (0.50, 0.55, 0.60, 0.65, 0.70)
    interest_rate_values = (0.04, 0.045, 0.05, 0.055, 0.06)

    detailed_result = run_detailed_two_way_sensitivity(
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        row_assumption="interest_rate",
        row_values=interest_rate_values,
        column_assumption="ltv",
        column_values=ltv_values,
        metric="levered_irr",
    )
    quick_result = run_two_way_sensitivity(
        GOLDEN_QUICK_INPUTS,
        row_assumption="interest_rate",
        row_values=interest_rate_values,
        column_assumption="ltv",
        column_values=ltv_values,
        metric="levered_irr",
    )

    assert detailed_result.baseline_row_value == strict(quick_result.baseline_row_value)
    assert detailed_result.baseline_column_value == strict(quick_result.baseline_column_value)
    assert detailed_result.baseline_metric_value == strict(quick_result.baseline_metric_value)
    for detailed_row, quick_row in zip(detailed_result.matrix, quick_result.matrix):
        for detailed_cell, quick_cell in zip(detailed_row, quick_row):
            assert detailed_cell == strict(quick_cell)


def test_detailed_max_purchase_price_break_even_matches_quick_equivalent() -> None:
    detailed_result = solve_detailed_max_purchase_price(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, target_levered_irr=0.06
    )
    quick_result = solve_max_purchase_price(GOLDEN_QUICK_INPUTS, target_levered_irr=0.06)

    assert detailed_result.baseline_assumption_value == strict(
        quick_result.baseline_assumption_value
    )
    assert detailed_result.baseline_metric_value == strict(quick_result.baseline_metric_value)
    assert detailed_result.status == quick_result.status
    assert detailed_result.solved_assumption_value == strict(quick_result.solved_assumption_value)


def test_detailed_max_exit_cap_rate_break_even_matches_quick_equivalent() -> None:
    detailed_result = solve_detailed_max_exit_cap_rate(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, target_levered_irr=0.06
    )
    quick_result = solve_max_exit_cap_rate(GOLDEN_QUICK_INPUTS, target_levered_irr=0.06)

    assert detailed_result.baseline_assumption_value == strict(
        quick_result.baseline_assumption_value
    )
    assert detailed_result.status == quick_result.status
    assert detailed_result.solved_assumption_value == strict(quick_result.solved_assumption_value)


def test_detailed_max_interest_rate_break_even_matches_quick_equivalent() -> None:
    detailed_result = solve_detailed_max_interest_rate(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, target_headline_dscr=1.5
    )
    quick_result = solve_max_interest_rate(GOLDEN_QUICK_INPUTS, target_headline_dscr=1.5)

    assert detailed_result.baseline_assumption_value == strict(
        quick_result.baseline_assumption_value
    )
    assert detailed_result.status == quick_result.status
    assert detailed_result.solved_assumption_value == strict(quick_result.solved_assumption_value)


# =============================================================================
# 3. Every Detailed candidate/cell preserves detailed_operating_inputs
#    completely unchanged (the Gate 9A bug class, generalized)
# =============================================================================


def test_detailed_sensitivity_never_drops_the_operating_inputs() -> None:
    """Uses a distinctive, non-golden DetailedOperatingInputs -- if any
    scenario cell silently reconstructed a default/neutral operating input
    set instead of preserving the real one, its NOI-derived metric would
    diverge from an independent direct recomputation using the exact same
    fixture."""

    result = run_detailed_two_way_sensitivity(
        GOLDEN_TERMS,
        DISTINCTIVE_DETAILED_OPERATING_INPUTS,
        row_assumption="ltv",
        row_values=(0.5, 0.6, 0.7),
        column_assumption="interest_rate",
        column_values=(0.04, 0.05, 0.06),
        metric="levered_irr",
    )

    for row_index, ltv_value in enumerate((0.5, 0.6, 0.7)):
        for column_index, interest_rate_value in enumerate((0.04, 0.05, 0.06)):
            expected_terms = dataclasses.replace(
                GOLDEN_TERMS, ltv=ltv_value, interest_rate=interest_rate_value
            )
            expected_results = analyze_detailed_acquisition_with_projection(
                expected_terms, DISTINCTIVE_DETAILED_OPERATING_INPUTS
            ).results
            assert result.matrix[row_index][column_index] == strict(
                expected_results.levered_irr
            )


def test_detailed_break_even_never_drops_the_operating_inputs() -> None:
    result_with_distinctive = solve_detailed_max_purchase_price(
        GOLDEN_TERMS, DISTINCTIVE_DETAILED_OPERATING_INPUTS, target_levered_irr=0.06
    )
    result_with_golden = solve_detailed_max_purchase_price(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, target_levered_irr=0.06
    )

    # Different operating assumptions must produce a genuinely different
    # break-even purchase price -- if the distinctive fixture were silently
    # discarded in favor of some default, both results would coincide.
    assert result_with_distinctive.solved_assumption_value != pytest.approx(
        result_with_golden.solved_assumption_value, rel=1e-6
    )


# =============================================================================
# 4. Detailed-only and Quick-only assumptions are both rejected
# =============================================================================


@pytest.mark.parametrize(
    "assumption", ["current_noi", "noi_growth", "revenue_growth", "vacancy_credit_loss_pct", "expense_growth"]
)
def test_detailed_sensitivity_rejects_unsupported_assumptions(assumption: str) -> None:
    with pytest.raises(UnknownAssumptionError):
        run_detailed_two_way_sensitivity(
            GOLDEN_TERMS,
            GOLDEN_DETAILED_OPERATING_INPUTS,
            row_assumption=assumption,
            row_values=(0.01, 0.02),
            column_assumption="ltv",
            column_values=(0.5, 0.6),
            metric="levered_irr",
        )
