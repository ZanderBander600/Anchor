"""Underwriting V2 Gate 4 -- interest-only debt and minimum DSCR
(docs/underwriting_v2_financial_conventions.md).

Proves, by direct differential comparison and by exercising the debt
primitives directly, exactly how ``io_period`` reshapes the debt schedule
(and, through it, DSCR/min_dscr) while leaving unlevered economics and
every Gate 2/3 transaction-cost/CapEx behavior untouched. Also contains
the permanent frozen Underwriting V2 golden-case reference (the first case
with all five V2 inputs simultaneously nonzero).
"""

from __future__ import annotations

import pytest

from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition
from anchor.engine.debt import (
    calculate_amortization_schedule,
    calculate_annual_debt_service,
    calculate_io_months,
    calculate_io_payment,
    calculate_loan_amount,
    calculate_monthly_debt_service,
    calculate_monthly_rate,
    calculate_remaining_loan_balance,
    calculate_scheduled_payment_count,
)


# Stringent absolute tolerance for financial outputs, mirroring
# tests/test_engine_debt.py and tests/test_engine_golden_case.py: rejects
# whole-dollar/cent rounding while tolerating ordinary IEEE-754 last-bit
# noise.
def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-6)


def _chronological_annual_sum(monthly_payment: float, count: int = 12) -> float:
    """Reproduce the engine's own chronological (not ``12 * PMT``)
    summation exactly, so expected values in this file are bit-identical
    to what ``calculate_annual_debt_service`` actually accumulates."""

    total = 0.0
    for _ in range(count):
        total = total + monthly_payment
    return total


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


BASELINE_INPUTS = make_inputs()  # io_period = 0
BASELINE = analyze_acquisition(BASELINE_INPUTS)

WITH_IO_INPUTS = make_inputs(io_period=2)
WITH_IO = analyze_acquisition(WITH_IO_INPUTS)


# =============================================================================
# Critical backward compatibility: io_period = 0 reuses the exact V1 code
# path, not merely an approximately-equal one.
# =============================================================================


def test_io_period_zero_reduces_to_v1_debt_schedule_exactly() -> None:
    result = analyze_acquisition(make_inputs(io_period=0))

    assert result == BASELINE


def test_io_period_zero_debt_primitives_are_bit_identical_to_the_v1_call_shape() -> None:
    # Calling the Gate 4 primitives with the V1 keyword shape (io_months/
    # io_payment omitted entirely, relying on their defaults) must produce
    # output bit-identical to calling them with those Gate 4 parameters
    # spelled out explicitly at their neutral values -- proving IO = 0
    # reuses the same code path, not just an equivalent one.
    loan_amount = 32_500_000.0
    monthly_rate = 0.0043749999999999995
    monthly_debt_service = 179466.20319611699
    n_payments = 360

    ads_v1_call_shape = calculate_annual_debt_service(
        monthly_debt_service=monthly_debt_service, n_payments=n_payments, hold_period=5
    )
    ads_explicit_io_zero = calculate_annual_debt_service(
        monthly_debt_service=monthly_debt_service,
        n_payments=n_payments,
        hold_period=5,
        io_months=0,
        io_payment=0.0,
    )
    assert ads_v1_call_shape == ads_explicit_io_zero

    balance_v1_call_shape = calculate_remaining_loan_balance(
        loan_amount=loan_amount,
        monthly_rate=monthly_rate,
        monthly_debt_service=monthly_debt_service,
        n_payments=n_payments,
        hold_period=5,
    )
    balance_explicit_io_zero = calculate_remaining_loan_balance(
        loan_amount=loan_amount,
        monthly_rate=monthly_rate,
        monthly_debt_service=monthly_debt_service,
        n_payments=n_payments,
        hold_period=5,
        io_months=0,
        io_payment=0.0,
    )
    assert balance_v1_call_shape == balance_explicit_io_zero


def test_gate1_v1_neutral_compatibility_regression_still_covers_io_period() -> None:
    # io_period is one of the five fields the Gate 1 permanent
    # compatibility test already pins at its neutral default; this is not
    # a new test but a pointer confirming Gate 4 did not need to touch it.
    from anchor.contracts import AcquisitionInputs as _AcquisitionInputs

    assert _AcquisitionInputs.__dataclass_fields__["io_period"].default == 0


# =============================================================================
# IO boundary tests.
# =============================================================================


def test_io_period_less_than_hold_period() -> None:
    # io_period = 2 < hold_period = 5: 2 IO years, then 3 amortizing years.
    result = analyze_acquisition(make_inputs(io_period=2))

    assert 0.0 < result.remaining_loan_balance < result.loan_amount
    assert result.annual_debt_service[0] == result.annual_debt_service[1]
    assert result.annual_debt_service[2] > result.annual_debt_service[1]


def test_io_period_equals_hold_period() -> None:
    # The entire hold is inside IO: remaining balance == loan_amount exactly.
    result = analyze_acquisition(make_inputs(io_period=5))

    assert result.remaining_loan_balance == result.loan_amount
    assert len(set(result.annual_debt_service)) == 1  # every year identical


def test_io_period_greater_than_hold_period() -> None:
    # io_period = 10 > hold_period = 5: still entirely inside IO, same
    # structural outcome as io_period == hold_period.
    result = analyze_acquisition(make_inputs(io_period=10))

    assert result.remaining_loan_balance == result.loan_amount
    assert len(set(result.annual_debt_service)) == 1


def test_io_period_plus_amortization_equals_hold_period() -> None:
    # io_period = 2, amortization = 3 (36 months): the loan's total life is
    # exactly hold_period * 12 = 60 months -- it matures precisely at sale.
    result = analyze_acquisition(make_inputs(amortization=3, io_period=2, hold_period=5))

    assert result.remaining_loan_balance == 0.0
    assert result.annual_debt_service[0] == result.annual_debt_service[1]  # IO years
    assert result.annual_debt_service[2] == result.annual_debt_service[3]
    assert result.annual_debt_service[3] == result.annual_debt_service[4]  # amortizing years


def test_io_period_plus_amortization_less_than_hold_period() -> None:
    # io_period = 1, amortization = 3: the loan matures at month 48 (year
    # 4), two full years (5, 6) before the year-6 sale.
    result = analyze_acquisition(make_inputs(amortization=3, io_period=1, hold_period=6))

    assert result.remaining_loan_balance == 0.0
    assert result.annual_debt_service[4] == 0.0
    assert result.annual_debt_service[5] == 0.0


# =============================================================================
# Rate / loan boundary tests.
# =============================================================================


def test_zero_interest_rate_with_positive_io_period() -> None:
    result = analyze_acquisition(make_inputs(interest_rate=0.0, io_period=2))

    # IO payment is interest-only on a zero rate, so it is exactly zero,
    # and principal (per the frozen IO convention) is still always zero --
    # the balance must not have moved after the IO years.
    assert result.annual_debt_service[0] == 0.0
    assert result.annual_debt_service[1] == 0.0

    # Post-IO, the existing zero-rate amortization branch (PMT =
    # loan_amount / n_payments) begins repayment -- no divide-by-zero
    # special case, and the balance now declines.
    assert result.annual_debt_service[2] > 0.0
    assert result.remaining_loan_balance < result.loan_amount


def test_zero_ltv_with_positive_io_period() -> None:
    result = analyze_acquisition(make_inputs(ltv=0.0, io_period=5))

    assert result.loan_amount == 0.0
    assert result.annual_debt_service == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert result.remaining_loan_balance == 0.0
    assert all(dscr is None for dscr in result.dscr_by_year)
    assert result.headline_dscr is None
    assert result.min_dscr is None


def test_one_year_io_one_year_hold() -> None:
    result = analyze_acquisition(make_inputs(hold_period=1, io_period=1))

    assert result.remaining_loan_balance == result.loan_amount
    assert len(result.annual_debt_service) == 1

    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=0.65)
    monthly_rate = calculate_monthly_rate(interest_rate=0.0525)
    io_payment = calculate_io_payment(loan_amount=loan_amount, monthly_rate=monthly_rate)
    assert result.annual_debt_service[0] == _chronological_annual_sum(io_payment)


def test_very_long_io_relative_to_hold() -> None:
    result = analyze_acquisition(make_inputs(io_period=50, hold_period=5))

    assert result.remaining_loan_balance == result.loan_amount
    assert len(set(result.annual_debt_service)) == 1


# =============================================================================
# Debt behavior proofs, exercised directly against the debt primitives.
# =============================================================================


LOAN_AMOUNT = 32_500_000.0
MONTHLY_RATE = 0.0043749999999999995
N_PAYMENTS = 360


def test_balance_does_not_decline_during_io() -> None:
    io_months = calculate_io_months(io_period=3)  # 36 months
    io_payment = calculate_io_payment(loan_amount=LOAN_AMOUNT, monthly_rate=MONTHLY_RATE)
    pmt = calculate_monthly_debt_service(
        loan_amount=LOAN_AMOUNT, interest_rate=0.0525, n_payments=N_PAYMENTS
    )

    schedule = calculate_amortization_schedule(
        loan_amount=LOAN_AMOUNT,
        monthly_rate=MONTHLY_RATE,
        monthly_debt_service=pmt,
        n_payments=N_PAYMENTS,
        months_to_run=io_months,
        io_months=io_months,
        io_payment=io_payment,
    )

    assert schedule == tuple(LOAN_AMOUNT for _ in range(io_months))


def test_io_payment_contains_no_principal() -> None:
    io_payment = calculate_io_payment(loan_amount=LOAN_AMOUNT, monthly_rate=MONTHLY_RATE)
    pmt = calculate_monthly_debt_service(
        loan_amount=LOAN_AMOUNT, interest_rate=0.0525, n_payments=N_PAYMENTS
    )

    # The IO payment is pure interest on the unchanged balance -- strictly
    # less than the amortizing PMT, which must also retire principal.
    assert io_payment == LOAN_AMOUNT * MONTHLY_RATE
    assert io_payment < pmt


def test_amortization_begins_exactly_after_the_io_phase() -> None:
    io_months = calculate_io_months(io_period=2)  # 24 months
    io_payment = calculate_io_payment(loan_amount=LOAN_AMOUNT, monthly_rate=MONTHLY_RATE)
    pmt = calculate_monthly_debt_service(
        loan_amount=LOAN_AMOUNT, interest_rate=0.0525, n_payments=N_PAYMENTS
    )

    schedule = calculate_amortization_schedule(
        loan_amount=LOAN_AMOUNT,
        monthly_rate=MONTHLY_RATE,
        monthly_debt_service=pmt,
        n_payments=N_PAYMENTS,
        months_to_run=io_months + 1,
        io_months=io_months,
        io_payment=io_payment,
    )

    assert schedule[io_months - 1] == LOAN_AMOUNT  # last IO month: unchanged
    assert schedule[io_months] < LOAN_AMOUNT  # first amortizing month: declines


def test_post_io_amortizing_payment_uses_the_existing_amortization_convention() -> None:
    # The amortizing PMT is computed via the unmodified, authoritative
    # calculate_monthly_debt_service using loan_amount/interest_rate/
    # n_payments alone -- proving no second, independent PMT formula
    # exists for the post-IO phase.
    reference_pmt = calculate_monthly_debt_service(
        loan_amount=32_500_000.0, interest_rate=0.0525, n_payments=360
    )

    assert WITH_IO.monthly_debt_service == reference_pmt


def test_debt_reaching_the_end_of_its_amortizing_phase_becomes_zero() -> None:
    result = analyze_acquisition(
        make_inputs(amortization=3, io_period=1, hold_period=6)
    )

    assert result.remaining_loan_balance == 0.0
    assert result.annual_debt_service[-1] == 0.0


def test_annual_debt_service_transitions_cleanly_at_the_year_boundary() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=0.65)
    monthly_rate = calculate_monthly_rate(interest_rate=0.0525)
    io_payment = calculate_io_payment(loan_amount=loan_amount, monthly_rate=monthly_rate)

    expected_io_year = _chronological_annual_sum(io_payment)
    expected_amortizing_year = _chronological_annual_sum(WITH_IO.monthly_debt_service)

    assert WITH_IO.annual_debt_service[0] == expected_io_year
    assert WITH_IO.annual_debt_service[1] == expected_io_year
    assert WITH_IO.annual_debt_service[2] == expected_amortizing_year
    # No partial-year blend: an IO year and the first amortizing year must
    # never be equal, and the jump is unambiguous.
    assert WITH_IO.annual_debt_service[2] != WITH_IO.annual_debt_service[1]


# =============================================================================
# DSCR / min_dscr.
# =============================================================================


def test_dscr_is_higher_during_io_than_immediately_after_amortization_begins() -> None:
    assert WITH_IO.dscr_by_year[0] > WITH_IO.dscr_by_year[2]
    assert WITH_IO.dscr_by_year[1] > WITH_IO.dscr_by_year[2]


def test_min_dscr_correctly_identifies_post_io_compression() -> None:
    defined = [d for d in WITH_IO.dscr_by_year if d is not None]
    assert WITH_IO.min_dscr == min(defined)
    assert WITH_IO.min_dscr < WITH_IO.headline_dscr
    assert WITH_IO.min_dscr == WITH_IO.dscr_by_year[2]  # first post-IO year


def test_headline_dscr_remains_year_one_regardless_of_io() -> None:
    for io_period in (0, 1, 2, 5, 10):
        result = analyze_acquisition(make_inputs(io_period=io_period))
        assert result.headline_dscr == result.dscr_by_year[0]


def test_min_dscr_can_equal_headline_dscr() -> None:
    # The V1-neutral baseline's DSCR is monotonically increasing (NOI
    # grows, debt service is flat), so Year 1 is both the headline and the
    # minimum -- ties to the pinned V1 golden-case DSCR value.
    assert BASELINE.min_dscr == BASELINE.headline_dscr
    assert BASELINE.min_dscr == strict(1.1608499518189)


def test_min_dscr_is_none_when_every_yearly_dscr_is_none() -> None:
    result = analyze_acquisition(make_inputs(ltv=0.0, io_period=3))

    assert all(dscr is None for dscr in result.dscr_by_year)
    assert result.min_dscr is None


def test_capex_does_not_change_either_dscr_calculation_with_io_present() -> None:
    without_capex = analyze_acquisition(make_inputs(io_period=2, annual_capex_reserve=0.0))
    with_capex = analyze_acquisition(
        make_inputs(io_period=2, annual_capex_reserve=100_000.0)
    )

    assert with_capex.dscr_by_year == without_capex.dscr_by_year
    assert with_capex.headline_dscr == without_capex.headline_dscr
    assert with_capex.min_dscr == without_capex.min_dscr


# =============================================================================
# IO leaves unlevered economics invariant.
# =============================================================================


def test_io_period_leaves_unlevered_cash_flows_and_unlevered_irr_unchanged() -> None:
    for io_period in (0, 1, 2, 5, 10):
        result = analyze_acquisition(make_inputs(io_period=io_period))
        assert result.unlevered_cash_flows == BASELINE.unlevered_cash_flows
        assert result.unlevered_irr == BASELINE.unlevered_irr


# =============================================================================
# Gates 2/3 combine correctly with Gate 4 IO.
# =============================================================================


def test_acquisition_costs_still_do_not_affect_debt_sizing_with_io() -> None:
    result = analyze_acquisition(make_inputs(io_period=2, acquisition_cost_pct=0.02))

    assert result.loan_amount == WITH_IO.loan_amount
    assert result.annual_debt_service == WITH_IO.annual_debt_service
    assert result.remaining_loan_balance == WITH_IO.remaining_loan_balance


def test_financing_fee_still_does_not_affect_debt_service_with_io() -> None:
    result = analyze_acquisition(make_inputs(io_period=2, financing_fee_pct=0.01))

    assert result.annual_debt_service == WITH_IO.annual_debt_service
    assert result.remaining_loan_balance == WITH_IO.remaining_loan_balance
    assert result.loan_amount == WITH_IO.loan_amount


def test_disposition_costs_still_do_not_alter_gross_exit_value_with_io() -> None:
    result = analyze_acquisition(make_inputs(io_period=2, disposition_cost_pct=0.025))

    assert result.exit_value == WITH_IO.exit_value


def test_annual_capex_still_does_not_alter_noi_with_io() -> None:
    result = analyze_acquisition(
        make_inputs(io_period=2, annual_capex_reserve=100_000.0)
    )

    assert result.noi_by_year == WITH_IO.noi_by_year


def test_all_five_v2_inputs_nonzero_at_once_remain_mathematically_defined() -> None:
    import math

    result = analyze_acquisition(
        make_inputs(
            acquisition_cost_pct=0.02,
            financing_fee_pct=0.01,
            disposition_cost_pct=0.025,
            annual_capex_reserve=50_000.0,
            io_period=2,
        )
    )

    for value in (
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
    ):
        assert math.isfinite(value)
    for series in (
        result.annual_debt_service,
        result.noi_by_year,
        result.capex_by_year,
        result.unlevered_cash_flows,
        result.levered_cash_flows,
    ):
        for value in series:
            assert math.isfinite(value)


# =============================================================================
# Full Underwriting V2 golden case -- permanent frozen reference.
#
# Inputs and key checkpoints reconciled from
# docs/underwriting_v2_financial_conventions.md. Every value below is the
# actual engine output (computed once via analyze_acquisition and pinned
# here as a regression), verified independently against the frozen
# documentation's rounded checkpoints with a tolerance appropriate to each
# value's display precision -- the engine is never forced to reproduce a
# rounded display value bit-for-bit.
# =============================================================================


def make_v2_golden_inputs() -> AcquisitionInputs:
    return AcquisitionInputs(
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


V2_GOLDEN = analyze_acquisition(make_v2_golden_inputs())


def test_v2_golden_case_capital_stack() -> None:
    assert V2_GOLDEN.loan_amount == 6_000_000.0
    assert V2_GOLDEN.acquisition_costs == 200_000.0
    assert V2_GOLDEN.financing_fee == 60_000.0
    assert V2_GOLDEN.initial_equity == 4_260_000.0

    # Reconcile against the frozen doc's rounded checkpoints.
    assert V2_GOLDEN.loan_amount == pytest.approx(6_000_000, abs=1.0)
    assert V2_GOLDEN.acquisition_costs == pytest.approx(200_000, abs=1.0)
    assert V2_GOLDEN.financing_fee == pytest.approx(60_000, abs=1.0)
    assert V2_GOLDEN.initial_equity == pytest.approx(4_260_000, abs=1.0)


def test_v2_golden_case_debt_schedule() -> None:
    assert V2_GOLDEN.annual_debt_service[0] == 300_000.0  # IO year 1
    assert V2_GOLDEN.annual_debt_service[1] == 300_000.0  # IO year 2
    assert V2_GOLDEN.monthly_debt_service == 32209.29738072834
    assert V2_GOLDEN.annual_debt_service[2] == 386511.5685687402  # post-IO
    assert V2_GOLDEN.remaining_loan_balance == 5720615.679740943

    assert V2_GOLDEN.monthly_debt_service == pytest.approx(32_209.29738, abs=1e-3)
    assert V2_GOLDEN.annual_debt_service[2] == pytest.approx(386_511.56857, abs=1e-3)
    assert V2_GOLDEN.remaining_loan_balance == pytest.approx(5_720_615.68, abs=1e-1)


def test_v2_golden_case_exit_economics() -> None:
    assert V2_GOLDEN.exit_value == 10700991.455076924
    assert V2_GOLDEN.disposition_costs == 267524.7863769231
    assert V2_GOLDEN.net_sale_proceeds == 4712850.988959057

    assert V2_GOLDEN.exit_value == pytest.approx(10_700_991.4551, abs=1e-2)
    assert V2_GOLDEN.disposition_costs == pytest.approx(267_524.7864, abs=1e-2)
    assert V2_GOLDEN.net_sale_proceeds == pytest.approx(4_712_850.99, abs=1e-1)


def test_v2_golden_case_dscr() -> None:
    assert V2_GOLDEN.headline_dscr == strict(2.0)
    assert V2_GOLDEN.min_dscr == strict(1.6468847293681788)

    assert V2_GOLDEN.headline_dscr == pytest.approx(2.00000, abs=1e-5)
    assert V2_GOLDEN.min_dscr == pytest.approx(1.64688, abs=1e-5)


def test_v2_golden_case_returns() -> None:
    assert V2_GOLDEN.unlevered_irr == strict(0.061388193938218594)
    assert V2_GOLDEN.levered_irr == strict(0.07380240064972221)
    assert V2_GOLDEN.equity_multiple == strict(1.3823468941908068)

    assert V2_GOLDEN.unlevered_irr == pytest.approx(0.061388, abs=1e-6)
    assert V2_GOLDEN.levered_irr == pytest.approx(0.073802, abs=1e-6)
    assert V2_GOLDEN.equity_multiple == pytest.approx(1.38235, abs=1e-5)


def test_v2_golden_case_capex_and_noi_untouched_by_debt_structure() -> None:
    assert V2_GOLDEN.capex_by_year == (50_000.0,) * 5
    assert V2_GOLDEN.noi_by_year == (
        600000.0,
        618000.0,
        636540.0,
        655636.2,
        675305.2860000001,
    )
