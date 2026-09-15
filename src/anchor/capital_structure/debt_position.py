"""Phase 7 Gate P7.8 -- the cash-pay schedule of an authored debt position.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section
12.4 ("New debt positions ... reuse ``debt.py``'s pure functions through thin
wrappers. ``debt.py`` stays byte-identical, and no debt formula is duplicated")
and the P7.8 decisions of ``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md``;
those documents govern on any discrepancy.

**A thin wrapper.** The payment count, monthly rate, interest-only months and
payment, the level payment, each month's payment and the amortization
recurrence all come from the unchanged ``anchor.engine.debt`` functions. This
module adds no debt formula: it only asks them for the months up to the modeled
payoff and turns their answers into timed events. It never sizes a loan: the
principal is the position's own resolved funding, so neither
``calculate_capital_stack`` nor ``calculate_debt_schedule`` is called, and no
``AcquisitionTerms`` is built.

**Cash pay only.** ``interest_rate`` is the total coupon and the rate the debt
functions use; the executor refuses PIK and a split current-pay rate first.
Senior and mezzanine debt share this one schedule: the class orders payment and
reporting, and never selects a formula.

**Payoff.** ``modeled_payoff_month = min(maturity_month, 12 x hold_period)``.
Each month up to it carries its scheduled payment; the remaining balance after
that month's payment is paid as the balloon, in the same month. The legal
``maturity_month`` is never rewritten.
"""

from __future__ import annotations

from ..engine.debt import (
    calculate_amortization_schedule,
    calculate_io_months,
    calculate_io_payment,
    calculate_monthly_debt_service,
    calculate_monthly_payment,
    calculate_monthly_rate,
    calculate_scheduled_payment_count,
)
from .contracts import MONTHS_PER_HOLD_YEAR, DebtTerms
from .execution_contracts import DebtPositionSchedule, PositionCashFlowEvent, PositionCashFlowKind

#: Within one model month, the scheduled payment precedes the balloon.
PAYMENT_SEQUENCE = 1
BALLOON_SEQUENCE = 2


def modeled_debt_payoff_month(*, maturity_month: int, hold_period: int) -> int:
    """Maturity when it falls within the hold, and the exit month otherwise."""

    return min(maturity_month, MONTHS_PER_HOLD_YEAR * hold_period)


def schedule_debt_position(
    *, position_id: str, principal: float, terms: DebtTerms, hold_period: int
) -> tuple[DebtPositionSchedule, tuple[PositionCashFlowEvent, ...]]:
    """The cash-pay schedule of one debt position of ``principal``, and its
    provider-side events after closing: each nonzero scheduled payment, and the
    balloon when a balance remains at the modeled payoff."""

    n_payments = calculate_scheduled_payment_count(amortization=terms.amortization)
    monthly_rate = calculate_monthly_rate(interest_rate=terms.interest_rate)
    io_months = calculate_io_months(io_period=terms.io_period)
    io_payment = calculate_io_payment(loan_amount=principal, monthly_rate=monthly_rate)
    amortizing_payment = calculate_monthly_debt_service(
        loan_amount=principal, interest_rate=terms.interest_rate, n_payments=n_payments
    )
    payoff_month = modeled_debt_payoff_month(maturity_month=terms.maturity_month, hold_period=hold_period)
    ending_balances = calculate_amortization_schedule(
        loan_amount=principal,
        monthly_rate=monthly_rate,
        monthly_debt_service=amortizing_payment,
        n_payments=n_payments,
        months_to_run=payoff_month,
        io_months=io_months,
        io_payment=io_payment,
    )
    balance_at_payoff = ending_balances[-1]

    events: list[PositionCashFlowEvent] = []
    for month in range(1, payoff_month + 1):
        payment = calculate_monthly_payment(
            monthly_debt_service=amortizing_payment,
            month=month,
            n_payments=n_payments,
            io_months=io_months,
            io_payment=io_payment,
        )
        if payment != 0.0:
            events.append(
                PositionCashFlowEvent(
                    event_id=f"{position_id}:{PositionCashFlowKind.SCHEDULED_DEBT_SERVICE.value}:{month}",
                    position_id=position_id,
                    model_month=month,
                    sequence=PAYMENT_SEQUENCE,
                    kind=PositionCashFlowKind.SCHEDULED_DEBT_SERVICE,
                    amount=payment,
                )
            )
    if balance_at_payoff != 0.0:
        events.append(
            PositionCashFlowEvent(
                event_id=f"{position_id}:{PositionCashFlowKind.BALLOON.value}:{payoff_month}",
                position_id=position_id,
                model_month=payoff_month,
                sequence=BALLOON_SEQUENCE,
                kind=PositionCashFlowKind.BALLOON,
                amount=balance_at_payoff,
            )
        )

    schedule = DebtPositionSchedule(
        principal=principal,
        interest_rate=terms.interest_rate,
        monthly_rate=monthly_rate,
        n_payments=n_payments,
        io_months=io_months,
        io_payment=io_payment,
        amortizing_payment=amortizing_payment,
        maturity_month=terms.maturity_month,
        modeled_payoff_month=payoff_month,
        balance_at_payoff=balance_at_payoff,
    )
    return schedule, tuple(events)
