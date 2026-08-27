import math

import pytest

from anchor.contracts import AcquisitionInputs
from anchor.engine.contracts import CapitalStack, DebtSchedule, NonFiniteResultError
from anchor.engine.debt import (
    calculate_amortization_schedule,
    calculate_annual_debt_service,
    calculate_capital_stack,
    calculate_debt_schedule,
    calculate_discount_exponent,
    calculate_initial_equity,
    calculate_loan_amount,
    calculate_log_growth,
    calculate_monthly_debt_service,
    calculate_monthly_payment,
    calculate_monthly_rate,
    calculate_payment_denominator,
    calculate_rate_fraction,
    calculate_remaining_loan_balance,
    calculate_scheduled_payment_count,
)


# Stringent absolute tolerance for financial outputs, mirroring
# tests/test_engine_noi.py: rejects whole-dollar/cent rounding while
# tolerating ordinary IEEE-754 last-bit noise.
def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-6)


def make_inputs(**overrides: object) -> AcquisitionInputs:
    defaults = dict(
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
    defaults.update(overrides)
    return AcquisitionInputs(**defaults)  # type: ignore[arg-type]


# --- calculate_loan_amount --------------------------------------------------


def test_loan_amount_ltv_zero_is_zero() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=0.0)

    assert loan_amount == 0.0


def test_loan_amount_ltv_one_equals_purchase_price() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=1.0)

    assert loan_amount == 50_000_000.0


def test_loan_amount_ordinary_ltv_golden_case_exact_value() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=0.65)

    assert loan_amount == 32_500_000.0


def test_loan_amount_non_round_friendly_case_rejects_dollar_or_cent_rounding() -> None:
    # Regression: purchase_price and ltv chosen so loan_amount lands on a
    # sub-cent fractional dollar value. A future implementation that rounds
    # loan_amount to the nearest cent (7576543.15) or nearest dollar
    # (7576543.0) before returning it must fail this exact-equality check.
    loan_amount = calculate_loan_amount(purchase_price=12_345_678.91, ltv=0.6137)

    assert loan_amount == 7576543.147067


# --- calculate_initial_equity -----------------------------------------------


def test_initial_equity_ltv_zero_equals_purchase_price() -> None:
    initial_equity = calculate_initial_equity(purchase_price=50_000_000.0, loan_amount=0.0)

    assert initial_equity == 50_000_000.0


def test_initial_equity_ltv_one_is_zero() -> None:
    initial_equity = calculate_initial_equity(
        purchase_price=50_000_000.0, loan_amount=50_000_000.0
    )

    assert initial_equity == 0.0


def test_initial_equity_ordinary_ltv_golden_case_exact_value() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=0.65)
    initial_equity = calculate_initial_equity(
        purchase_price=50_000_000.0, loan_amount=loan_amount
    )

    assert initial_equity == 17_500_000.0


def test_initial_equity_non_round_friendly_case_rejects_dollar_or_cent_rounding() -> None:
    # Regression: mirrors the non-round loan_amount case above so a future
    # implementation that rounds initial_equity to the nearest cent
    # (4769135.76) or nearest dollar (4769136.0) fails this check.
    loan_amount = calculate_loan_amount(purchase_price=12_345_678.91, ltv=0.6137)
    initial_equity = calculate_initial_equity(
        purchase_price=12_345_678.91, loan_amount=loan_amount
    )

    assert initial_equity == 4769135.762933


# --- capital stack composition ----------------------------------------------


@pytest.mark.parametrize("ltv", [0.0, 1.0, 0.65])
def test_loan_amount_plus_initial_equity_equals_purchase_price(ltv: float) -> None:
    purchase_price = 50_000_000.0
    loan_amount = calculate_loan_amount(purchase_price=purchase_price, ltv=ltv)
    initial_equity = calculate_initial_equity(
        purchase_price=purchase_price, loan_amount=loan_amount
    )

    assert loan_amount + initial_equity == purchase_price


def test_calculate_capital_stack_returns_capital_stack_with_expected_field_values() -> None:
    inputs = make_inputs()

    result = calculate_capital_stack(inputs)

    assert isinstance(result, CapitalStack)
    assert result.loan_amount == 32_500_000.0
    assert result.initial_equity == 17_500_000.0


def test_calculate_capital_stack_ltv_zero() -> None:
    inputs = make_inputs(ltv=0.0)

    result = calculate_capital_stack(inputs)

    assert result.loan_amount == 0.0
    assert result.initial_equity == inputs.purchase_price


def test_calculate_capital_stack_ltv_one() -> None:
    inputs = make_inputs(ltv=1.0)

    result = calculate_capital_stack(inputs)

    assert result.loan_amount == inputs.purchase_price
    assert result.initial_equity == 0.0


def test_repeated_calls_with_same_inputs_produce_identical_capital_stack_results() -> None:
    inputs = make_inputs()

    first = calculate_capital_stack(inputs)
    second = calculate_capital_stack(inputs)

    assert first == second


# =============================================================================
# Phase 2B -- loan structure
# =============================================================================


def test_calculate_scheduled_payment_count() -> None:
    assert calculate_scheduled_payment_count(amortization=30) == 360
    assert calculate_scheduled_payment_count(amortization=1) == 12


def test_calculate_monthly_rate_ordinary_case() -> None:
    assert calculate_monthly_rate(interest_rate=0.0525) == strict(0.0043749999999999995)


def test_calculate_monthly_rate_zero_is_zero() -> None:
    assert calculate_monthly_rate(interest_rate=0.0) == 0.0


# =============================================================================
# Phase 2B -- monthly_debt_service (PMT) branch ordering
# =============================================================================


# --- Branch 1: zero loan amount ---------------------------------------------


def test_pmt_branch1_zero_loan_amount_is_zero() -> None:
    pmt = calculate_monthly_debt_service(
        loan_amount=0.0, interest_rate=0.0525, n_payments=360
    )

    assert pmt == 0.0


def test_pmt_branch1_zero_loan_amount_regression_ignores_ordinary_nonzero_rate() -> None:
    # Required zero-loan payment regression test: ltv = 0 (loan_amount = 0.0)
    # combined with an ordinary nonzero interest_rate must produce PMT = 0.0
    # via Branch 1, without ever reaching a positive-interest denominator, so
    # no 0 / 0 path is reachable regardless of the (nonzero) interest rate.
    for interest_rate in (0.0001, 0.0525, 1.0, 1e300):
        pmt = calculate_monthly_debt_service(
            loan_amount=0.0, interest_rate=interest_rate, n_payments=360
        )
        assert pmt == 0.0


# --- Branch 2: zero interest rate -------------------------------------------


def test_pmt_branch2_zero_interest_rate() -> None:
    pmt = calculate_monthly_debt_service(
        loan_amount=32_500_000.0, interest_rate=0.0, n_payments=360
    )

    assert pmt == strict(32_500_000.0 / 360)


# --- Branch 3b: ordinary positive interest ----------------------------------


def test_pmt_branch3b_ordinary_positive_interest_golden_case() -> None:
    pmt = calculate_monthly_debt_service(
        loan_amount=32_500_000.0, interest_rate=0.0525, n_payments=360
    )

    assert pmt == 179466.20319611699


def test_pmt_branch3b_very_large_but_finite_permitted_interest_is_finite() -> None:
    # No new upper bound is imposed on interest_rate; a very large but
    # ordinary finite rate must still resolve to a finite PMT without
    # substituting higher-precision arithmetic.
    pmt = calculate_monthly_debt_service(
        loan_amount=32_500_000.0, interest_rate=5.0, n_payments=360
    )

    assert math.isfinite(pmt)
    assert pmt > 0.0


def test_pmt_branch3b_naive_one_plus_rate_equals_one_regression() -> None:
    # Required very-small positive interest rate regression test: the annual
    # interest_rate is small enough that monthly_rate > 0.0 but naive
    # 1.0 + monthly_rate evaluates to exactly 1.0 under IEEE-754 double
    # precision. Branch 3b (not Branch 2) must be taken, no ZeroDivisionError
    # may occur, the stable log1p/expm1 formula must be used, the resulting
    # PMT must be finite, and PMT must approach loan_amount / N as the rate
    # approaches zero -- the rate itself is never silently coerced to 0.0.
    interest_rate = 1.2e-16
    monthly_rate = calculate_monthly_rate(interest_rate=interest_rate)

    assert monthly_rate > 0.0
    assert (1.0 + monthly_rate) == 1.0  # confirms the naive expression would fail

    pmt = calculate_monthly_debt_service(
        loan_amount=32_500_000.0, interest_rate=interest_rate, n_payments=360
    )

    assert math.isfinite(pmt)
    assert pmt == strict(32_500_000.0 / 360)


def test_pmt_branch3b_underflow_safe_numerator_regression() -> None:
    # Required underflow-safe PMT numerator regression test (Branch 3b):
    # loan_amount * monthly_rate underflows to exactly 0.0 under naive
    # multiply-then-divide evaluation, but the frozen divide-first order
    # (rate_fraction = r / payment_denominator, then PMT = loan_amount *
    # rate_fraction) yields a finite, nonzero PMT close to loan_amount / N.
    loan_amount = 1e-300
    interest_rate = 1.2e-24
    n_payments = 360

    monthly_rate = calculate_monthly_rate(interest_rate=interest_rate)
    assert monthly_rate == 9.999999999999999e-26
    assert loan_amount * monthly_rate == 0.0  # naive multiply-first underflows

    pmt = calculate_monthly_debt_service(
        loan_amount=loan_amount, interest_rate=interest_rate, n_payments=n_payments
    )

    assert pmt == 2.777777777777778e-303
    assert pmt != 0.0


# --- Branch 3a: monthly-rate underflow --------------------------------------


def test_pmt_branch3a_monthly_rate_underflow_regression() -> None:
    # Required positive-annual-rate, monthly-rate-underflow regression test:
    # interest_rate = 5e-324 (smallest positive representable float)
    # satisfies interest_rate > 0.0 while interest_rate / 12 == 0.0 purely
    # from IEEE-754 underflow. PMT must equal loan_amount / N exactly, with
    # no arithmetic exception, via the positive-rate numerical-limit case
    # (Branch 3a), not Branch 2.
    interest_rate = 5e-324
    loan_amount = 32_500_000.0
    n_payments = 360

    assert interest_rate > 0.0
    assert calculate_monthly_rate(interest_rate=interest_rate) == 0.0

    pmt = calculate_monthly_debt_service(
        loan_amount=loan_amount, interest_rate=interest_rate, n_payments=n_payments
    )

    assert pmt == 90277.77777777778
    assert pmt == loan_amount / n_payments


# =============================================================================
# Phase 2B -- Branch 3b numerically stable sub-step finiteness checks
# =============================================================================


def test_calculate_log_growth_raises_on_non_finite() -> None:
    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_log_growth(monthly_rate=math.inf)

    assert exc_info.value.field_name == "log_growth"


def test_calculate_payment_denominator_raises_on_non_finite() -> None:
    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_payment_denominator(discount_exponent=math.nan)

    assert exc_info.value.field_name == "payment_denominator"


def test_calculate_payment_denominator_raises_on_positive_infinity() -> None:
    with pytest.raises(NonFiniteResultError):
        calculate_payment_denominator(discount_exponent=math.inf)


def test_calculate_rate_fraction_raises_on_non_finite() -> None:
    # A zero payment_denominator with a positive monthly_rate divides to
    # +inf, which must be rejected rather than silently returned.
    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_rate_fraction(monthly_rate=0.0043749999999999995, payment_denominator=0.0)

    assert exc_info.value.field_name == "rate_fraction"


def test_calculate_discount_exponent_raises_on_nan() -> None:
    with pytest.raises(NonFiniteResultError):
        calculate_discount_exponent(n_payments=360, log_growth=math.nan)


def test_calculate_discount_exponent_ordinary_case_is_finite_and_negative() -> None:
    discount_exponent = calculate_discount_exponent(n_payments=360, log_growth=0.00436545750963998)

    assert discount_exponent == strict(-1.5715647034703928)
    assert discount_exponent < 0.0


# --- discount_exponent == -inf documented exception, both forms ------------


def test_discount_exponent_ordinary_float_overflow_produces_negative_infinity() -> None:
    # Form 1: N * log_growth overflows to +inf under ordinary float
    # multiplication (no exception); discount_exponent == -inf directly.
    monthly_rate = calculate_monthly_rate(interest_rate=1e300)
    log_growth = calculate_log_growth(monthly_rate=monthly_rate)
    n_payments = 3 * 10**305 * 12  # amortization = 3e305, still float-convertible

    discount_exponent = calculate_discount_exponent(
        n_payments=n_payments, log_growth=log_growth
    )

    assert discount_exponent == -math.inf

    payment_denominator = calculate_payment_denominator(discount_exponent=discount_exponent)
    assert payment_denominator == 1.0

    pmt = calculate_monthly_debt_service(
        loan_amount=32_500_000.0, interest_rate=1e300, n_payments=n_payments
    )
    assert math.isfinite(pmt)


def test_discount_exponent_overflow_error_on_huge_n_is_caught_and_mapped() -> None:
    # Form 2: N itself is too large to convert to float, raising a raw
    # OverflowError while computing -N * log_growth. This must be caught and
    # deterministically mapped to discount_exponent == -inf; the raw
    # OverflowError must never escape.
    monthly_rate = calculate_monthly_rate(interest_rate=1e300)
    log_growth = calculate_log_growth(monthly_rate=monthly_rate)
    n_payments = 10**400 * 12  # amortization = 10**400, far beyond float max

    with pytest.raises(OverflowError):
        float(n_payments)  # sanity check: fixture actually exceeds float range

    discount_exponent = calculate_discount_exponent(
        n_payments=n_payments, log_growth=log_growth
    )
    assert discount_exponent == -math.inf

    payment_denominator = calculate_payment_denominator(discount_exponent=discount_exponent)
    assert payment_denominator == 1.0

    pmt = calculate_monthly_debt_service(
        loan_amount=32_500_000.0, interest_rate=1e300, n_payments=n_payments
    )
    assert math.isfinite(pmt)


# =============================================================================
# Phase 2B -- monthly payment schedule
# =============================================================================


def test_calculate_monthly_payment_active_month_returns_pmt() -> None:
    assert calculate_monthly_payment(monthly_debt_service=179466.20319611699, month=1, n_payments=360) == 179466.20319611699
    assert calculate_monthly_payment(monthly_debt_service=179466.20319611699, month=360, n_payments=360) == 179466.20319611699


def test_calculate_monthly_payment_past_maturity_returns_zero() -> None:
    # Month N + 1 (and later) has Monthly Payment_t = 0, with no post-
    # maturity recurrence performed.
    assert calculate_monthly_payment(monthly_debt_service=179466.20319611699, month=361, n_payments=360) == 0.0


# =============================================================================
# Phase 2B -- annual debt service (chronological summation)
# =============================================================================


def test_annual_debt_service_golden_case_all_years_identical() -> None:
    # A = 30 > H = 5: every modeled year is fully within the amortization
    # period.
    ads = calculate_annual_debt_service(
        monthly_debt_service=179466.20319611699, n_payments=360, hold_period=5
    )

    assert ads == (
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
    )


def test_annual_debt_service_chronological_summation_regression_not_12_times_pmt() -> None:
    # Required regression: chronological addition of a Monthly Payment_t
    # value 12 times must be asserted directly, not the 12 * PMT shortcut,
    # because they differ in the last bits for this fixture.
    monthly_payment = 268729.3538605583
    naive_shortcut = 12 * monthly_payment

    ads = calculate_annual_debt_service(
        monthly_debt_service=monthly_payment, n_payments=360, hold_period=1
    )

    assert ads[0] == 3224752.2463267003
    assert ads[0] != naive_shortcut
    assert naive_shortcut == 3224752.2463267


def test_annual_debt_service_a_less_than_h_zero_after_maturity() -> None:
    # A < H: years 1..A have active PMT payments, years A+1..H are 0.0.
    ads = calculate_annual_debt_service(
        monthly_debt_service=100_000.0, n_payments=24, hold_period=4
    )

    assert ads == (1_200_000.0, 1_200_000.0, 0.0, 0.0)


def test_annual_debt_service_a_equals_h_every_year_active() -> None:
    ads = calculate_annual_debt_service(
        monthly_debt_service=100_000.0, n_payments=24, hold_period=2
    )

    assert ads == (1_200_000.0, 1_200_000.0)


def test_annual_debt_service_a_greater_than_h_every_modeled_year_active() -> None:
    ads = calculate_annual_debt_service(
        monthly_debt_service=100_000.0, n_payments=360, hold_period=2
    )

    assert ads == (1_200_000.0, 1_200_000.0)


def test_annual_debt_service_zero_leverage_is_all_zero() -> None:
    ads = calculate_annual_debt_service(
        monthly_debt_service=0.0, n_payments=360, hold_period=5
    )

    assert ads == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_annual_debt_service_length_equals_hold_period() -> None:
    ads = calculate_annual_debt_service(
        monthly_debt_service=100_000.0, n_payments=360, hold_period=7
    )

    assert len(ads) == 7


# =============================================================================
# Phase 2B -- amortization recurrence / remaining loan balance
# =============================================================================


GOLDEN_MONTHLY_RATE = 0.0043749999999999995
GOLDEN_PMT = 179466.20319611699
GOLDEN_LOAN_AMOUNT = 32_500_000.0
GOLDEN_N = 360


def test_amortization_schedule_golden_case_checkpoints() -> None:
    schedule = calculate_amortization_schedule(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        months_to_run=GOLDEN_N,
    )

    assert schedule[0] == 32462721.296803884  # month 1
    assert schedule[11] == 32041732.801682245  # month 12
    assert schedule[23] == 31558819.12881365  # month 24
    assert schedule[59] == 29948583.641211268  # month 60
    assert schedule[119] == 26633190.900727846  # month 120
    assert schedule[358] == 178684.4586894612  # month 359
    assert schedule[359] == 0.0  # month 360 (contractual maturity identity)


def test_amortization_schedule_month_13_boundary() -> None:
    schedule = calculate_amortization_schedule(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        months_to_run=13,
    )

    assert len(schedule) == 13
    assert schedule[11] == 32041732.801682245  # month 12 unchanged
    assert schedule[12] < schedule[11]  # month 13 continues amortizing


def test_amortization_schedule_length_matches_months_to_run() -> None:
    schedule = calculate_amortization_schedule(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        months_to_run=60,
    )

    assert len(schedule) == 60


def test_amortization_schedule_exact_maturity_is_zero_exactly() -> None:
    schedule = calculate_amortization_schedule(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        months_to_run=GOLDEN_N,
    )

    assert schedule[-1] == 0.0


def test_amortization_schedule_zero_rate_reduces_to_linear_paydown() -> None:
    loan_amount = 1_200_000.0
    n_payments = 12
    pmt = loan_amount / n_payments

    schedule = calculate_amortization_schedule(
        loan_amount=loan_amount,
        monthly_rate=0.0,
        monthly_debt_service=pmt,
        n_payments=n_payments,
        months_to_run=n_payments,
    )

    assert schedule[0] == strict(loan_amount - pmt)
    assert schedule[-1] == 0.0


def test_amortization_schedule_zero_leverage_is_all_zero_at_every_month() -> None:
    schedule = calculate_amortization_schedule(
        loan_amount=0.0,
        monthly_rate=0.0043749999999999995,
        monthly_debt_service=0.0,
        n_payments=360,
        months_to_run=60,
    )

    assert schedule == tuple(0.0 for _ in range(60))


def test_amortization_schedule_no_cent_rounding_before_maturity() -> None:
    # Regression: a future implementation that rounds pre-maturity balances
    # to the nearest cent must fail this exact-equality check.
    schedule = calculate_amortization_schedule(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        months_to_run=1,
    )

    assert schedule[0] == 32462721.296803884
    assert schedule[0] != round(schedule[0], 2)


def test_amortization_schedule_raises_on_non_finite_ending_balance() -> None:
    with pytest.raises(NonFiniteResultError):
        calculate_amortization_schedule(
            loan_amount=1e308,
            monthly_rate=1e300,
            monthly_debt_service=0.0,
            n_payments=1,
            months_to_run=1,
        )


# --- remaining_loan_balance ---------------------------------------------


def test_remaining_loan_balance_golden_case() -> None:
    remaining_loan_balance = calculate_remaining_loan_balance(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        hold_period=5,
    )

    assert remaining_loan_balance == 29948583.641211268


def test_remaining_loan_balance_a_less_than_h_is_fully_amortized_zero() -> None:
    # A < H: the loan reaches maturity before the sale date.
    remaining_loan_balance = calculate_remaining_loan_balance(
        loan_amount=100_000.0,
        monthly_rate=0.0,
        monthly_debt_service=100_000.0 / 24,
        n_payments=24,
        hold_period=4,
    )

    assert remaining_loan_balance == 0.0


def test_remaining_loan_balance_a_equals_h_is_exactly_zero_at_maturity() -> None:
    remaining_loan_balance = calculate_remaining_loan_balance(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        hold_period=30,
    )

    assert remaining_loan_balance == 0.0


def test_remaining_loan_balance_a_greater_than_h_uses_actual_recurrence() -> None:
    remaining_loan_balance = calculate_remaining_loan_balance(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        hold_period=5,
    )

    assert 0.0 < remaining_loan_balance < GOLDEN_LOAN_AMOUNT


def test_remaining_loan_balance_zero_leverage_is_zero() -> None:
    remaining_loan_balance = calculate_remaining_loan_balance(
        loan_amount=0.0,
        monthly_rate=0.0043749999999999995,
        monthly_debt_service=0.0,
        n_payments=360,
        hold_period=5,
    )

    assert remaining_loan_balance == 0.0


def test_remaining_loan_balance_closed_form_cross_check_within_tolerance() -> None:
    # Closed-form oracle, ordinary numerical range only (not authoritative):
    # B_m = L * (1 + r)^m - PMT * ((1 + r)^m - 1) / r
    r = GOLDEN_MONTHLY_RATE
    m = 60
    growth = (1 + r) ** m
    closed_form = GOLDEN_LOAN_AMOUNT * growth - GOLDEN_PMT * (growth - 1) / r

    remaining_loan_balance = calculate_remaining_loan_balance(
        loan_amount=GOLDEN_LOAN_AMOUNT,
        monthly_rate=GOLDEN_MONTHLY_RATE,
        monthly_debt_service=GOLDEN_PMT,
        n_payments=GOLDEN_N,
        hold_period=5,
    )

    assert remaining_loan_balance == pytest.approx(closed_form, rel=1e-9)


# =============================================================================
# Phase 2B -- non-finite propagation from calculate_monthly_debt_service
# =============================================================================


def test_pmt_branch3b_non_finite_log_growth_raises() -> None:
    with pytest.raises(NonFiniteResultError):
        calculate_monthly_debt_service(
            loan_amount=32_500_000.0, interest_rate=math.inf, n_payments=360
        )


# =============================================================================
# Phase 2B -- DebtSchedule orchestration
# =============================================================================


def test_calculate_debt_schedule_returns_debt_schedule_golden_case() -> None:
    inputs = make_inputs()

    result = calculate_debt_schedule(inputs)

    assert isinstance(result, DebtSchedule)
    assert result.monthly_debt_service == 179466.20319611699
    assert result.annual_debt_service == (
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
    )
    assert result.remaining_loan_balance == 29948583.641211268


def test_calculate_debt_schedule_ltv_zero() -> None:
    inputs = make_inputs(ltv=0.0)

    result = calculate_debt_schedule(inputs)

    assert result.monthly_debt_service == 0.0
    assert result.annual_debt_service == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert result.remaining_loan_balance == 0.0


def test_calculate_debt_schedule_a_less_than_h() -> None:
    inputs = make_inputs(amortization=3, hold_period=5)

    result = calculate_debt_schedule(inputs)

    assert result.annual_debt_service[3] == 0.0
    assert result.annual_debt_service[4] == 0.0
    assert result.remaining_loan_balance == 0.0


def test_calculate_debt_schedule_a_equals_h() -> None:
    inputs = make_inputs(amortization=5, hold_period=5)

    result = calculate_debt_schedule(inputs)

    assert result.remaining_loan_balance == 0.0


def test_repeated_calls_with_same_inputs_produce_identical_debt_schedule_results() -> None:
    inputs = make_inputs()

    first = calculate_debt_schedule(inputs)
    second = calculate_debt_schedule(inputs)

    assert first == second
