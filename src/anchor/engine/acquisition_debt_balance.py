"""Refinance & Capital Events V1 (R-M) -- the acquisition loan's balance at a
model month.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 10.2
(decision R-M); that document governs on any discrepancy.

``AcquisitionResults`` records the acquisition loan's remaining balance only at
the sale date. A refinance at hold-year end ``m`` needs the balance immediately
after the scheduled payment of month ``m``. This service answers that one
question, and it is the only place in Anchor that does.

**Owned by the debt engine, never by Capital Structure.** The P7.7 legacy
adapter still imports no debt function and still reads ``AcquisitionTerms``
descriptively only. The refinance layer calls this service with the resolved
``AcquisitionTerms`` that produced the ``AcquisitionResults`` it reconciles to.

**No formula of its own.** Every figure comes from the unchanged
``anchor.engine.debt`` functions, called with the same operands in the same
order as ``calculate_debt_schedule``: the loan amount, the level payment, the
interest-only phase and the frozen amortization recurrence. Nothing is
restated, simplified or rounded.

**Reconciled on every call, bit for bit.** Before a balance is returned, the
recomputed loan amount, monthly payment, the annual debt service of every hold
year through the event, and the sale-date balance reached through the same
recurrence must each equal the accepted ``AcquisitionResults`` figure exactly.
A mismatch means the terms given are not the terms that produced the results,
or an engine defect. It raises ``AcquisitionDebtBalanceReconciliationError``
naming the figure, and is never tolerated, adjusted or replaced.

Nothing here reads, writes or rebuilds ``AcquisitionResults``; it is compared,
never mutated. No-refinance execution never calls this service.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import AcquisitionTerms
from .contracts import AcquisitionResults
from .debt import (
    calculate_amortization_schedule,
    calculate_debt_schedule,
    calculate_io_months,
    calculate_io_payment,
    calculate_loan_amount,
    calculate_monthly_payment,
    calculate_monthly_rate,
    calculate_scheduled_payment_count,
)

MONTHS_PER_HOLD_YEAR = 12


class AcquisitionDebtBalanceReconciliationError(ValueError):
    """The recomputed acquisition-loan schedule does not reproduce the accepted
    ``AcquisitionResults`` bit for bit. ``figure`` names the first figure that
    disagrees. This is an engine defect or a terms/results mismatch, never an
    analyst finding, and it is never reconciled."""

    def __init__(self, figure: str, *, recomputed: object, accepted: object) -> None:
        self.figure = figure
        self.recomputed = recomputed
        self.accepted = accepted
        super().__init__(
            f"The acquisition loan's {figure} recomputed as {recomputed!r}, but the accepted result is {accepted!r}. "
            "The balance at the event month is not returned."
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionLoanBalance:
    """The acquisition loan at model month ``model_month``.

    - ``scheduled_payment_at_month``: the scheduled payment of that month,
      exactly as ``calculate_monthly_payment`` returns it;
    - ``balance_after_month``: the remaining principal immediately after that
      payment. ``0.0`` once the loan has fully amortized."""

    model_month: int
    loan_amount: float
    monthly_debt_service: float
    scheduled_payment_at_month: float
    balance_after_month: float


def _reconcile(figure: str, recomputed: object, accepted: object) -> None:
    if recomputed != accepted:
        raise AcquisitionDebtBalanceReconciliationError(figure, recomputed=recomputed, accepted=accepted)


def acquisition_loan_balance_after_month(
    *, terms: AcquisitionTerms, results: AcquisitionResults, model_month: int
) -> AcquisitionLoanBalance:
    """The acquisition loan's balance immediately after the scheduled payment
    of ``model_month``, reconciled bit for bit to ``results``.

    ``model_month`` must be a whole month in ``1 .. 12 x hold_period``: the
    loan exists from closing to the modeled sale and no further."""

    if isinstance(model_month, bool) or not isinstance(model_month, int):
        raise ValueError(f"model_month {model_month!r} must be a whole model month.")
    exit_month = MONTHS_PER_HOLD_YEAR * terms.hold_period
    if not 1 <= model_month <= exit_month:
        raise ValueError(f"model_month {model_month} is outside the loan's modeled life, months 1..{exit_month}.")

    loan_amount = calculate_loan_amount(purchase_price=terms.purchase_price, ltv=terms.ltv)
    _reconcile("loan amount", loan_amount, results.loan_amount)
    schedule = calculate_debt_schedule(terms)
    _reconcile("monthly debt service", schedule.monthly_debt_service, results.monthly_debt_service)
    event_year = (model_month - 1) // MONTHS_PER_HOLD_YEAR + 1
    for year in range(1, event_year + 1):
        _reconcile(
            f"Year {year} debt service",
            schedule.annual_debt_service[year - 1],
            results.annual_debt_service[year - 1],
        )

    n_payments = calculate_scheduled_payment_count(amortization=terms.amortization)
    monthly_rate = calculate_monthly_rate(interest_rate=terms.interest_rate)
    io_months = calculate_io_months(io_period=terms.io_period)
    io_payment = calculate_io_payment(loan_amount=loan_amount, monthly_rate=monthly_rate)
    loan_life = io_months + n_payments
    ending_balances = calculate_amortization_schedule(
        loan_amount=loan_amount,
        monthly_rate=monthly_rate,
        monthly_debt_service=schedule.monthly_debt_service,
        n_payments=n_payments,
        months_to_run=min(exit_month, loan_life),
        io_months=io_months,
        io_payment=io_payment,
    )
    _reconcile("sale-date remaining balance", ending_balances[-1], results.remaining_loan_balance)

    return AcquisitionLoanBalance(
        model_month=model_month,
        loan_amount=loan_amount,
        monthly_debt_service=schedule.monthly_debt_service,
        scheduled_payment_at_month=calculate_monthly_payment(
            monthly_debt_service=schedule.monthly_debt_service,
            month=model_month,
            n_payments=n_payments,
            io_months=io_months,
            io_payment=io_payment,
        ),
        balance_after_month=ending_balances[min(model_month, loan_life) - 1],
    )


__all__ = [
    "AcquisitionDebtBalanceReconciliationError",
    "AcquisitionLoanBalance",
    "acquisition_loan_balance_after_month",
]
