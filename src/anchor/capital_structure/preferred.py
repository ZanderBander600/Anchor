"""Phase 7 Gate P7.8 -- the schedule of a preferred equity position.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
12.2 and 12.3 (FR-4: preferred equity accrues only where its terms allow, under
the convention they name, Q21) and the P7.8 decisions of
``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md``; those documents
govern on any discrepancy.

**The rate split.** ``accrual_rate = preferred_rate - current_pay_rate``. The
execution validator requires ``0 <= current_pay_rate <= preferred_rate``, and
``accrual_permitted`` whenever ``accrual_rate > 0``.

**Annual, on the unreturned principal ``P``.** For each hold year ``y`` up to
redemption:

- current pay (a cash claim, paid at the year-end model month ``12y``):
  ``current_pay_rate x P``;
- accrual (not a cash claim before redemption), recognized at the year end:
  ``SIMPLE``: ``P x accrual_rate``; ``ANNUAL_COMPOUND``:
  ``(P + beginning_accrued) x accrual_rate``.

The accrual is the *scheduled* non-current-pay part of the preferred return. It
is never a cure: a current-pay shortfall is a Funding Requirement settled under
the position's own resolution, and is never added to it.

**Redemption.** At a hold-year end only (no partial year is prorated and no
monthly accrual exists): the stated month when it is ``12, 24, ...`` before the
exit, and the exit month when it falls at or after the exit. In that year
current pay comes first, then the year's accrual is recognized, and the
redemption pays ``P`` plus the resulting accrued balance. Nothing follows it.
"""

from __future__ import annotations

from .contracts import MONTHS_PER_HOLD_YEAR, AccrualConvention, CapitalStructureError, PreferredEquityTerms
from .execution_contracts import (
    PositionCashFlowEvent,
    PositionCashFlowKind,
    PreferredAccrualYear,
    PreferredPositionSchedule,
)

#: Within the redemption month, current pay precedes the redemption.
CURRENT_PAY_SEQUENCE = 1
REDEMPTION_SEQUENCE = 2


def modeled_redemption_month(*, redemption_month: int, hold_period: int) -> int | None:
    """The executable redemption month, or ``None`` for a partial-year
    redemption before the exit, which has no ratified convention."""

    exit_month = MONTHS_PER_HOLD_YEAR * hold_period
    if redemption_month >= exit_month:
        return exit_month
    if redemption_month % MONTHS_PER_HOLD_YEAR == 0:
        return redemption_month
    return None


def schedule_preferred_position(
    *, position_id: str, principal: float, terms: PreferredEquityTerms, hold_period: int
) -> tuple[PreferredPositionSchedule, tuple[PositionCashFlowEvent, ...]]:
    """The preferred schedule of ``principal`` and its provider-side events
    after closing: each nonzero year-end current pay, and the redemption."""

    payoff_month = modeled_redemption_month(redemption_month=terms.redemption_month, hold_period=hold_period)
    if payoff_month is None:
        raise CapitalStructureError(
            f"{position_id!r} redeems within a hold year; the execution validator refuses it first."
        )
    accrual_rate = terms.preferred_rate - terms.current_pay_rate
    if accrual_rate > 0.0 and not isinstance(terms.accrual_convention, AccrualConvention):
        raise CapitalStructureError(
            f"{position_id!r} would accrue without a stated convention; the execution validator refuses it first."
        )

    years: list[PreferredAccrualYear] = []
    events: list[PositionCashFlowEvent] = []
    accrued = 0.0
    for year in range(1, payoff_month // MONTHS_PER_HOLD_YEAR + 1):
        current_pay = terms.current_pay_rate * principal
        if accrual_rate <= 0.0:
            accrual = 0.0
        elif terms.accrual_convention is AccrualConvention.SIMPLE:
            accrual = principal * accrual_rate
        elif terms.accrual_convention is AccrualConvention.ANNUAL_COMPOUND:
            accrual = (principal + accrued) * accrual_rate
        else:  # pragma: no cover -- refused above.
            raise CapitalStructureError(f"Unknown accrual convention {terms.accrual_convention!r}.")
        ending = accrued + accrual
        years.append(
            PreferredAccrualYear(
                hold_year=year,
                unreturned_principal=principal,
                current_pay=current_pay,
                beginning_accrued=accrued,
                accrual=accrual,
                ending_accrued=ending,
            )
        )
        if current_pay != 0.0:
            month = MONTHS_PER_HOLD_YEAR * year
            events.append(
                PositionCashFlowEvent(
                    event_id=f"{position_id}:{PositionCashFlowKind.PREFERRED_CURRENT_PAY.value}:{month}",
                    position_id=position_id,
                    model_month=month,
                    sequence=CURRENT_PAY_SEQUENCE,
                    kind=PositionCashFlowKind.PREFERRED_CURRENT_PAY,
                    amount=current_pay,
                )
            )
        accrued = ending

    balance = principal + accrued
    events.append(
        PositionCashFlowEvent(
            event_id=f"{position_id}:{PositionCashFlowKind.PREFERRED_REDEMPTION.value}:{payoff_month}",
            position_id=position_id,
            model_month=payoff_month,
            sequence=REDEMPTION_SEQUENCE,
            kind=PositionCashFlowKind.PREFERRED_REDEMPTION,
            amount=balance,
        )
    )
    schedule = PreferredPositionSchedule(
        principal=principal,
        preferred_rate=terms.preferred_rate,
        current_pay_rate=terms.current_pay_rate,
        accrual_rate=accrual_rate,
        accrual_convention=terms.accrual_convention,
        redemption_month=terms.redemption_month,
        modeled_payoff_month=payoff_month,
        years=tuple(years),
        balance_at_redemption=balance,
    )
    return schedule, tuple(events)
