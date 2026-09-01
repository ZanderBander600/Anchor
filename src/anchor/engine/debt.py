"""Phase 2A/2B acquisition debt: capital stack, PMT, amortization, ADS.

Restates ``docs/financial_conventions.md`` "Loan and debt service" and
``docs/phase_2_deterministic_engine.md`` "Phase 2B -- Acquisition / Debt"
exactly; those documents govern on any discrepancy. No cash-flow assembly,
NOI forecasting, or return-metric logic belongs here.
"""

from __future__ import annotations

from math import expm1, inf, log1p, nan

from ..contracts import AcquisitionInputs
from .contracts import CapitalStack, DebtSchedule, NonFiniteResultError, ensure_finite


# --- Phase 2A: capital stack -------------------------------------------------


def calculate_loan_amount(*, purchase_price: float, ltv: float) -> float:
    loan_amount = purchase_price * ltv
    return ensure_finite("loan_amount", loan_amount)


def calculate_acquisition_costs(
    *, purchase_price: float, acquisition_cost_pct: float
) -> float:
    """Underwriting V2 Gate 2: ``acquisition_costs = purchase_price *
    acquisition_cost_pct``. Funded entirely by equity -- never affects
    ``loan_amount``, which continues to derive from ``purchase_price``
    alone."""

    acquisition_costs = purchase_price * acquisition_cost_pct
    return ensure_finite("acquisition_costs", acquisition_costs)


def calculate_financing_fee(*, loan_amount: float, financing_fee_pct: float) -> float:
    """Underwriting V2 Gate 2: ``financing_fee = loan_amount *
    financing_fee_pct``. Funded entirely by equity -- never affects
    ``loan_amount`` or any debt-service calculation. Naturally ``0.0``
    whenever ``loan_amount`` is ``0.0`` (e.g. ``ltv = 0``), with no special
    case required."""

    financing_fee = loan_amount * financing_fee_pct
    return ensure_finite("financing_fee", financing_fee)


def calculate_initial_equity(
    *,
    purchase_price: float,
    loan_amount: float,
    acquisition_costs: float = 0.0,
    financing_fee: float = 0.0,
) -> float:
    """``initial_equity = purchase_price - loan_amount + acquisition_costs
    + financing_fee``. At Gate 2 neutral defaults (both cost terms
    ``0.0``), this reduces to exactly the V1 formula
    ``purchase_price - loan_amount``."""

    initial_equity = purchase_price - loan_amount + acquisition_costs + financing_fee
    return ensure_finite("initial_equity", initial_equity)


def calculate_capital_stack(inputs: AcquisitionInputs) -> CapitalStack:
    """Compute the Phase 2A capital-stack basics, plus the Underwriting V2
    Gate 2 acquisition-cost/financing-fee terms, for one
    ``AcquisitionInputs``."""

    loan_amount = calculate_loan_amount(
        purchase_price=inputs.purchase_price, ltv=inputs.ltv
    )
    acquisition_costs = calculate_acquisition_costs(
        purchase_price=inputs.purchase_price,
        acquisition_cost_pct=inputs.acquisition_cost_pct,
    )
    financing_fee = calculate_financing_fee(
        loan_amount=loan_amount, financing_fee_pct=inputs.financing_fee_pct
    )
    initial_equity = calculate_initial_equity(
        purchase_price=inputs.purchase_price,
        loan_amount=loan_amount,
        acquisition_costs=acquisition_costs,
        financing_fee=financing_fee,
    )
    return CapitalStack(
        loan_amount=loan_amount,
        acquisition_costs=acquisition_costs,
        financing_fee=financing_fee,
        initial_equity=initial_equity,
    )


# --- Phase 2B: loan structure -------------------------------------------------


def calculate_scheduled_payment_count(*, amortization: int) -> int:
    """Return ``N = amortization * 12``, the total scheduled monthly payments."""

    return amortization * 12


def calculate_monthly_rate(*, interest_rate: float) -> float:
    """Return ``r = interest_rate / 12``.

    This is the monthly rate used throughout Phase 2B: both for selecting
    the ``PMT`` branch and for the amortization recurrence. A finite,
    non-negative ``interest_rate`` (the Phase 0 input domain) can never make
    this division non-finite; an extremely small positive ``interest_rate``
    can, however, underflow to exactly ``0.0`` (Branch 3a), which is finite
    by construction and not itself a failure.
    """

    monthly_rate = interest_rate / 12
    return ensure_finite("monthly_rate", monthly_rate)


# --- Phase 2B: PMT, Branch 3b numerically stable sub-steps -------------------


def calculate_log_growth(*, monthly_rate: float) -> float:
    """Return ``log1p(monthly_rate)`` -- ``ln(1 + r)`` evaluated stably."""

    log_growth = log1p(monthly_rate)
    return ensure_finite("log_growth", log_growth)


def calculate_discount_exponent(*, n_payments: int, log_growth: float) -> float:
    """Return ``-N * log_growth``.

    ``n_payments`` is an arbitrary-precision Python ``int`` that can exceed
    the magnitude any ``float`` can represent for an extreme but permitted
    ``amortization``. Converting such an ``int`` to ``float`` (required by
    the multiplication below) then raises a raw ``OverflowError`` -- this is
    the frozen Phase 2B numerical-boundary case, distinct from an ordinary
    float-multiplication overflow (which instead silently produces ``-inf``
    with no exception). Both forms deterministically resolve to
    ``discount_exponent = -inf`` here, per the documented exception; the
    raw ``OverflowError`` itself must never leak out of the engine.
    """

    try:
        discount_exponent = -n_payments * log_growth
    except OverflowError:
        if n_payments > 0 and log_growth > 0.0:
            return -inf
        raise NonFiniteResultError("discount_exponent", float("nan")) from None

    if discount_exponent == -inf:
        return discount_exponent
    return ensure_finite("discount_exponent", discount_exponent)


def calculate_payment_denominator(*, discount_exponent: float) -> float:
    """Return ``1 - (1 + r)^(-N)``, evaluated stably as ``-expm1(discount_exponent)``."""

    payment_denominator = -expm1(discount_exponent)
    return ensure_finite("payment_denominator", payment_denominator)


def calculate_rate_fraction(*, monthly_rate: float, payment_denominator: float) -> float:
    """Return ``r / payment_denominator``, the divide-first half of ``PMT``.

    Unlike IEEE-754 hardware division, Python's ``float / float`` raises
    ``ZeroDivisionError`` rather than returning a signed infinity when the
    denominator is exactly ``0.0``. That raw exception must never leak out
    of the engine, so it is translated to the same non-finite outcome an
    IEEE-754 division would have produced, which ``ensure_finite`` then
    rejects like any other non-finite result.
    """

    try:
        rate_fraction = monthly_rate / payment_denominator
    except ZeroDivisionError:
        if monthly_rate > 0.0:
            rate_fraction = inf
        elif monthly_rate < 0.0:
            rate_fraction = -inf
        else:
            rate_fraction = nan
    return ensure_finite("rate_fraction", rate_fraction)


def calculate_monthly_debt_service(
    *, loan_amount: float, interest_rate: float, n_payments: int
) -> float:
    """Return ``PMT`` via the three frozen, ordered branches.

    Branch 1 (zero loan amount), Branch 2 (zero interest rate), and Branch 3
    (positive interest rate, itself split into 3a -- monthly-rate underflow
    -- and 3b -- the numerically stable positive-rate formula) are checked
    in this fixed order. The first applicable branch determines ``PMT``;
    later branches are never evaluated once an earlier one applies.
    """

    # Branch 1 -- zero loan amount (frozen). Checked, and PMT = 0.0
    # returned, before any positive-rate denominator is evaluated,
    # regardless of interest_rate.
    if loan_amount == 0.0:
        return 0.0

    # Branch 2 -- zero interest rate (frozen).
    if interest_rate == 0.0:
        pmt = loan_amount / n_payments
        return ensure_finite("monthly_debt_service", pmt)

    # Branch 3 -- positive interest rate (interest_rate > 0.0 here).
    monthly_rate = calculate_monthly_rate(interest_rate=interest_rate)

    # Branch 3a -- monthly-rate underflow: interest_rate > 0.0 but the
    # derived monthly_rate underflows to exactly 0.0. This is the same
    # numerical value as Branch 2, reached for a different, documented
    # reason -- not a reclassification of the loan as zero-interest.
    if monthly_rate == 0.0:
        pmt = loan_amount / n_payments
        return ensure_finite("monthly_debt_service", pmt)

    # Branch 3b -- representable positive monthly rate.
    log_growth = calculate_log_growth(monthly_rate=monthly_rate)
    discount_exponent = calculate_discount_exponent(
        n_payments=n_payments, log_growth=log_growth
    )
    payment_denominator = calculate_payment_denominator(
        discount_exponent=discount_exponent
    )
    rate_fraction = calculate_rate_fraction(
        monthly_rate=monthly_rate, payment_denominator=payment_denominator
    )

    pmt = loan_amount * rate_fraction
    return ensure_finite("monthly_debt_service", pmt)


# --- Phase 2B: monthly payment schedule, ADS, amortization recurrence -------


def calculate_monthly_payment(
    *, monthly_debt_service: float, month: int, n_payments: int
) -> float:
    """Return ``Monthly Payment_t``: ``PMT`` for ``1 <= t <= N``, else ``0.0``."""

    return monthly_debt_service if month <= n_payments else 0.0


def calculate_annual_debt_service(
    *, monthly_debt_service: float, n_payments: int, hold_period: int
) -> tuple[float, ...]:
    """Return ``ADS_1 .. ADS_H`` by chronological monthly summation.

    Each ``ADS_y`` is accumulated by adding each of the 12 monthly
    ``Monthly Payment_t`` values for hold year ``y`` in chronological month
    order. This is never replaced by the algebraically equivalent
    ``12 * PMT`` shortcut, because repeated IEEE-754 addition and a single
    multiplication by 12 can differ in the last bits.
    """

    annual_debt_service = []
    month = 0
    for year in range(1, hold_period + 1):
        ads_y = 0.0
        for _ in range(12):
            month += 1
            payment_t = calculate_monthly_payment(
                monthly_debt_service=monthly_debt_service,
                month=month,
                n_payments=n_payments,
            )
            ads_y = ads_y + payment_t
        annual_debt_service.append(
            ensure_finite(f"annual_debt_service[{year - 1}]", ads_y)
        )
    return tuple(annual_debt_service)


def calculate_amortization_schedule(
    *,
    loan_amount: float,
    monthly_rate: float,
    monthly_debt_service: float,
    n_payments: int,
    months_to_run: int,
) -> tuple[float, ...]:
    """Return the ending balance after each month ``1 .. months_to_run``.

    Executes the frozen three-step per-month recurrence exactly as
    specified: ``Interest_t``, then ``Principal_t`` from that stored
    interest value, then ``Ending Balance_t`` from that stored principal
    value, only then carrying the ending balance forward. This must never
    be algebraically simplified to
    ``Beginning Balance_t * (1 + monthly_rate) - Payment_t``.

    At month ``N`` (contractual maturity), the frozen ``B_N := 0.0``
    identity is applied to the raw ending balance only after that raw value
    has passed its own finiteness check. This never applies to any month
    ``m < N``.
    """

    ending_balances = []
    beginning_balance = loan_amount
    for month in range(1, months_to_run + 1):
        payment_t = calculate_monthly_payment(
            monthly_debt_service=monthly_debt_service,
            month=month,
            n_payments=n_payments,
        )

        interest_t = beginning_balance * monthly_rate
        interest_t = ensure_finite(f"interest[{month}]", interest_t)

        principal_t = payment_t - interest_t
        principal_t = ensure_finite(f"principal[{month}]", principal_t)

        ending_balance_t = beginning_balance - principal_t
        ending_balance_t = ensure_finite(f"ending_balance[{month}]", ending_balance_t)

        if month == n_payments:
            ending_balance_t = 0.0

        ending_balances.append(ending_balance_t)
        beginning_balance = ending_balance_t

    return tuple(ending_balances)


def calculate_remaining_loan_balance(
    *,
    loan_amount: float,
    monthly_rate: float,
    monthly_debt_service: float,
    n_payments: int,
    hold_period: int,
) -> float:
    """Return ``B_exit = B_min(12H, N)``, the balance at the sale date."""

    months_to_run = min(hold_period * 12, n_payments)
    ending_balances = calculate_amortization_schedule(
        loan_amount=loan_amount,
        monthly_rate=monthly_rate,
        monthly_debt_service=monthly_debt_service,
        n_payments=n_payments,
        months_to_run=months_to_run,
    )
    return ensure_finite("remaining_loan_balance", ending_balances[-1])


def calculate_debt_schedule(inputs: AcquisitionInputs) -> DebtSchedule:
    """Compute the Phase 2B debt schedule for one ``AcquisitionInputs``."""

    loan_amount = calculate_loan_amount(
        purchase_price=inputs.purchase_price, ltv=inputs.ltv
    )
    n_payments = calculate_scheduled_payment_count(amortization=inputs.amortization)

    monthly_debt_service = calculate_monthly_debt_service(
        loan_amount=loan_amount,
        interest_rate=inputs.interest_rate,
        n_payments=n_payments,
    )
    annual_debt_service = calculate_annual_debt_service(
        monthly_debt_service=monthly_debt_service,
        n_payments=n_payments,
        hold_period=inputs.hold_period,
    )
    monthly_rate = calculate_monthly_rate(interest_rate=inputs.interest_rate)
    remaining_loan_balance = calculate_remaining_loan_balance(
        loan_amount=loan_amount,
        monthly_rate=monthly_rate,
        monthly_debt_service=monthly_debt_service,
        n_payments=n_payments,
        hold_period=inputs.hold_period,
    )

    return DebtSchedule(
        monthly_debt_service=monthly_debt_service,
        annual_debt_service=annual_debt_service,
        remaining_loan_balance=remaining_loan_balance,
    )
