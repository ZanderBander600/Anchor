"""Underwriting V2 Gate 2 -- acquisition costs, financing fee, disposition
costs (docs/underwriting_v2_financial_conventions.md).

Proves, by direct differential comparison against a common baseline deal,
exactly which AcquisitionResults fields each of the three transaction-cost
inputs does and does not affect -- not just that the engine still runs.
CapEx and interest-only debt are explicitly not implemented yet (Gate 3+);
every test here leaves annual_capex_reserve and io_period at their neutral
default.
"""

from __future__ import annotations

import math

import pytest

from anchor.contracts import AcquisitionInputs
from anchor.engine import AcquisitionResults, analyze_acquisition

BASE_KWARGS: dict[str, object] = dict(
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


def make_inputs(**overrides: object) -> AcquisitionInputs:
    return AcquisitionInputs(**(BASE_KWARGS | overrides))  # type: ignore[arg-type]


BASELINE_INPUTS = make_inputs()
BASELINE = analyze_acquisition(BASELINE_INPUTS)


# =============================================================================
# 1/2 -- acquisition costs and financing fees never change loan_amount.
# =============================================================================


def test_acquisition_cost_pct_does_not_change_loan_amount() -> None:
    result = analyze_acquisition(make_inputs(acquisition_cost_pct=0.02))

    assert result.loan_amount == BASELINE.loan_amount


def test_financing_fee_pct_does_not_change_loan_amount() -> None:
    result = analyze_acquisition(make_inputs(financing_fee_pct=0.01))

    assert result.loan_amount == BASELINE.loan_amount


# =============================================================================
# 3 -- financing fees never touch the unlevered series (unlevered means no
# debt, so no debt-related cost belongs there).
# =============================================================================


def test_financing_fee_pct_does_not_affect_unlevered_cash_flows_or_irr() -> None:
    result = analyze_acquisition(make_inputs(financing_fee_pct=0.01))

    assert result.unlevered_cash_flows == BASELINE.unlevered_cash_flows
    assert result.unlevered_irr == BASELINE.unlevered_irr


# =============================================================================
# 4 -- disposition costs never change the gross exit_value.
# =============================================================================


def test_disposition_cost_pct_does_not_change_gross_exit_value() -> None:
    result = analyze_acquisition(make_inputs(disposition_cost_pct=0.025))

    assert result.exit_value == BASELINE.exit_value


# =============================================================================
# 5/6 -- none of the three cost fields touch NOI, going-in cap rate, debt
# service, remaining balance, or DSCR.
# =============================================================================


@pytest.mark.parametrize(
    ("field_id", "value"),
    [
        ("acquisition_cost_pct", 0.02),
        ("financing_fee_pct", 0.01),
        ("disposition_cost_pct", 0.025),
    ],
)
def test_transaction_costs_do_not_change_noi_or_going_in_cap_rate(
    field_id: str, value: float
) -> None:
    result = analyze_acquisition(make_inputs(**{field_id: value}))

    assert result.noi_by_year == BASELINE.noi_by_year
    assert result.exit_noi == BASELINE.exit_noi
    assert result.going_in_cap_rate == BASELINE.going_in_cap_rate


@pytest.mark.parametrize(
    ("field_id", "value"),
    [
        ("acquisition_cost_pct", 0.02),
        ("financing_fee_pct", 0.01),
        ("disposition_cost_pct", 0.025),
    ],
)
def test_transaction_costs_do_not_change_debt_service_or_dscr(
    field_id: str, value: float
) -> None:
    result = analyze_acquisition(make_inputs(**{field_id: value}))

    assert result.monthly_debt_service == BASELINE.monthly_debt_service
    assert result.annual_debt_service == BASELINE.annual_debt_service
    assert result.remaining_loan_balance == BASELINE.remaining_loan_balance
    assert result.dscr_by_year == BASELINE.dscr_by_year
    assert result.headline_dscr == BASELINE.headline_dscr


# =============================================================================
# 7 -- acquisition costs reduce both levered and unlevered T=0 cash flow,
# and increase initial equity, by exactly the cost.
# =============================================================================


def test_acquisition_cost_pct_reduces_both_t0_cash_flows_by_exactly_the_cost() -> None:
    inputs = make_inputs(acquisition_cost_pct=0.02)
    result = analyze_acquisition(inputs)
    expected_cost = inputs.purchase_price * inputs.acquisition_cost_pct

    assert result.acquisition_costs == expected_cost
    assert result.financing_fee == 0.0
    assert result.unlevered_cash_flows[0] == BASELINE.unlevered_cash_flows[0] - expected_cost
    assert result.levered_cash_flows[0] == BASELINE.levered_cash_flows[0] - expected_cost
    assert result.initial_equity == BASELINE.initial_equity + expected_cost
    # No other cash-flow-series entry is touched.
    assert result.unlevered_cash_flows[1:] == BASELINE.unlevered_cash_flows[1:]
    assert result.levered_cash_flows[1:] == BASELINE.levered_cash_flows[1:]


# =============================================================================
# 8 -- financing fees affect only the levered T=0 cash flow (and initial
# equity); the unlevered series is untouched (see test 3 above too).
# =============================================================================


def test_financing_fee_pct_reduces_only_levered_t0_cash_flow() -> None:
    inputs = make_inputs(financing_fee_pct=0.01)
    result = analyze_acquisition(inputs)
    expected_fee = result.loan_amount * inputs.financing_fee_pct

    assert result.financing_fee == expected_fee
    assert result.acquisition_costs == 0.0
    assert result.unlevered_cash_flows[0] == BASELINE.unlevered_cash_flows[0]
    assert result.levered_cash_flows[0] == BASELINE.levered_cash_flows[0] - expected_fee
    assert result.initial_equity == BASELINE.initial_equity + expected_fee


# =============================================================================
# 9 -- disposition costs reduce both levered and unlevered terminal
# economics by exactly the cost; net_sale_proceeds absorbs the same
# reduction (remaining_loan_balance is untouched, per test 6 above).
# =============================================================================


def test_disposition_cost_pct_reduces_both_terminal_cash_flows_by_exactly_the_cost() -> None:
    inputs = make_inputs(disposition_cost_pct=0.025)
    result = analyze_acquisition(inputs)
    expected_disposition_costs = result.exit_value * inputs.disposition_cost_pct
    # Matches the engine's own left-to-right evaluation order
    # (exit_value - disposition_costs - remaining_loan_balance) exactly, so
    # this is an exact-equality check rather than an approximate one --
    # "baseline minus cost" would reorder the subtraction and risk a
    # last-bit IEEE-754 mismatch unrelated to any real discrepancy.
    expected_net_sale_proceeds = (
        result.exit_value - expected_disposition_costs - result.remaining_loan_balance
    )
    expected_lcf_h = (
        result.noi_by_year[-1]
        - result.annual_debt_service[-1]
        + expected_net_sale_proceeds
    )

    assert result.disposition_costs == expected_disposition_costs
    assert result.net_sale_proceeds == expected_net_sale_proceeds
    assert result.unlevered_cash_flows[-1] == (
        BASELINE.unlevered_cash_flows[-1] - expected_disposition_costs
    )
    assert result.levered_cash_flows[-1] == expected_lcf_h
    # T=0 and every intermediate operating year are untouched.
    assert result.unlevered_cash_flows[:-1] == BASELINE.unlevered_cash_flows[:-1]
    assert result.levered_cash_flows[:-1] == BASELINE.levered_cash_flows[:-1]


# =============================================================================
# Combined case -- all three nonzero at once. Proves the three effects
# compose additively rather than interacting.
# =============================================================================


def test_combined_transaction_costs_compose_additively() -> None:
    inputs = make_inputs(
        acquisition_cost_pct=0.02,
        financing_fee_pct=0.01,
        disposition_cost_pct=0.025,
    )
    result = analyze_acquisition(inputs)

    expected_acquisition_costs = inputs.purchase_price * 0.02
    expected_financing_fee = result.loan_amount * 0.01
    expected_disposition_costs = result.exit_value * 0.025

    assert result.acquisition_costs == expected_acquisition_costs
    assert result.financing_fee == expected_financing_fee
    assert result.disposition_costs == expected_disposition_costs

    # Sources & uses: initial_equity absorbs both T=0 cost terms.
    assert result.initial_equity == (
        inputs.purchase_price
        - result.loan_amount
        + expected_acquisition_costs
        + expected_financing_fee
    )

    # T=0: unlevered absorbs only acquisition costs; levered absorbs both,
    # via the expanded initial_equity.
    assert result.unlevered_cash_flows[0] == -(
        inputs.purchase_price + expected_acquisition_costs
    )
    assert result.levered_cash_flows[0] == -result.initial_equity
    assert result.levered_cash_flows[0] == (
        BASELINE.levered_cash_flows[0] - expected_acquisition_costs - expected_financing_fee
    )

    # T=H: both series absorb disposition costs, and nothing else moved.
    # (Matches the engine's own left-to-right subtraction order -- see the
    # comment in the dedicated disposition-cost test above.)
    assert result.unlevered_cash_flows[-1] == (
        BASELINE.unlevered_cash_flows[-1] - expected_disposition_costs
    )
    assert result.net_sale_proceeds == (
        result.exit_value - expected_disposition_costs - result.remaining_loan_balance
    )

    # Debt/NOI side is completely untouched by any of the three.
    assert result.loan_amount == BASELINE.loan_amount
    assert result.noi_by_year == BASELINE.noi_by_year
    assert result.annual_debt_service == BASELINE.annual_debt_service
    assert result.dscr_by_year == BASELINE.dscr_by_year
    assert result.exit_value == BASELINE.exit_value


# =============================================================================
# Zero-cost boundary -- explicit 0 (not just omitted/default) for all three,
# alongside the still-unimplemented CapEx/IO fields, must exactly reproduce
# the baseline (itself already proven equal to the V1-only engine by
# tests/test_underwriting_v2_gate1_compatibility.py).
# =============================================================================


def test_explicit_zero_transaction_costs_reproduce_the_baseline_exactly() -> None:
    inputs = make_inputs(
        acquisition_cost_pct=0.0,
        financing_fee_pct=0.0,
        disposition_cost_pct=0.0,
        annual_capex_reserve=0.0,
        io_period=0,
    )

    result = analyze_acquisition(inputs)

    assert result == BASELINE
    assert result.acquisition_costs == 0.0
    assert result.financing_fee == 0.0
    assert result.disposition_costs == 0.0


def test_baseline_matches_the_frozen_v1_golden_case() -> None:
    """Ties this Gate 2 baseline to the actual frozen V1 golden-case
    numbers (docs/phase_2_deterministic_engine.md), not just internal
    self-consistency with the other tests in this file."""

    assert BASELINE.loan_amount == 32_500_000.0
    assert BASELINE.initial_equity == 17_500_000.0
    assert BASELINE.levered_irr == pytest.approx(0.07913030056780745, rel=0.0, abs=1e-9)
    assert BASELINE.unlevered_irr == pytest.approx(0.062414943980353854, rel=0.0, abs=1e-9)
    assert BASELINE.equity_multiple == pytest.approx(1.44288913123241, rel=0.0, abs=1e-9)
    assert BASELINE.acquisition_costs == 0.0
    assert BASELINE.financing_fee == 0.0
    assert BASELINE.disposition_costs == 0.0


# =============================================================================
# 100%-boundary cases -- each cost input at its validated upper bound (1.0),
# individually and combined, must still leave the engine mathematically
# defined: every AcquisitionResults field finite, no exception, no NaN.
# IRR/equity multiple may legitimately become None under these extreme
# (if unrealistic) inputs per the existing frozen None/"N/A" conventions --
# that is a defined outcome, not a failure.
# =============================================================================


def _assert_all_float_fields_are_finite(result: AcquisitionResults) -> None:
    scalar_fields = (
        result.going_in_cap_rate,
        result.loan_amount,
        result.acquisition_costs,
        result.financing_fee,
        result.initial_equity,
        result.monthly_debt_service,
        result.remaining_loan_balance,
        result.exit_noi,
        result.exit_value,
        result.disposition_costs,
        result.net_sale_proceeds,
    )
    for value in scalar_fields:
        assert math.isfinite(value)
    for series in (
        result.annual_debt_service,
        result.noi_by_year,
        result.unlevered_cash_flows,
        result.levered_cash_flows,
    ):
        for value in series:
            assert math.isfinite(value)
    for dscr in result.dscr_by_year:
        assert dscr is None or math.isfinite(dscr)


def test_acquisition_cost_pct_at_100_percent_remains_mathematically_defined() -> None:
    result = analyze_acquisition(make_inputs(acquisition_cost_pct=1.0))

    _assert_all_float_fields_are_finite(result)
    assert result.acquisition_costs == BASELINE_INPUTS.purchase_price
    assert result.loan_amount == BASELINE.loan_amount


def test_financing_fee_pct_at_100_percent_remains_mathematically_defined() -> None:
    result = analyze_acquisition(make_inputs(financing_fee_pct=1.0))

    _assert_all_float_fields_are_finite(result)
    assert result.financing_fee == result.loan_amount
    assert result.loan_amount == BASELINE.loan_amount


def test_disposition_cost_pct_at_100_percent_remains_mathematically_defined() -> None:
    result = analyze_acquisition(make_inputs(disposition_cost_pct=1.0))

    _assert_all_float_fields_are_finite(result)
    assert result.disposition_costs == result.exit_value
    # The entire gross sale price is consumed by disposition costs, so net
    # sale proceeds fall by exactly exit_value relative to baseline.
    assert result.net_sale_proceeds == BASELINE.net_sale_proceeds - result.exit_value


def test_all_three_transaction_costs_at_100_percent_remains_mathematically_defined() -> None:
    result = analyze_acquisition(
        make_inputs(
            acquisition_cost_pct=1.0,
            financing_fee_pct=1.0,
            disposition_cost_pct=1.0,
        )
    )

    _assert_all_float_fields_are_finite(result)
    assert result.acquisition_costs == BASELINE_INPUTS.purchase_price
    assert result.financing_fee == result.loan_amount
    assert result.disposition_costs == result.exit_value
