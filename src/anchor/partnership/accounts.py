"""Phase 7 Gate P7.9 -- hurdle accounts.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 8
(ratified; PW-3); that document governs on any discrepancy. Pure functions
over an immutable ``HurdleAccountState``.

- ``ANNUAL_COMPOUND``: ``B_t = B_(t-1) x (1 + r) + C - D``, with **no floor**.
  A negative balance is surplus above the hurdle; it carries forward and
  compounds, which preserves the cumulative IRR look-back identity.
- ``SIMPLE``: outstanding capital ``K`` (may be negative: excess returned) and
  accrued return ``A`` (never negative). Accrual is ``r x max(K, 0)``, never on
  accrued return. A distribution is applied in the condition's stated order.
- MOIC: ``B = m x cumulative C - cumulative D``; no accrual.

For an annual series, period ``0`` accrues nothing and each later period one
year. Cash dated ``t`` never accrues in period ``t``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .contracts import (
    AccrualConvention,
    WATERFALL_AMOUNT_TOLERANCE,
    HurdleCombinator,
    HurdleCondition,
    IrrHurdle,
    MoicHurdle,
    SimpleDistributionOrder,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class HurdleAccountState:
    """One condition's account. ``balance`` is what the subject is still owed
    (negative: surplus). ``outstanding_capital`` and ``accrued_return`` are the
    SIMPLE state; ``cumulative_*`` the MOIC state."""

    balance: float
    outstanding_capital: float
    accrued_return: float
    cumulative_contributions: float
    cumulative_distributions: float


def open_account() -> HurdleAccountState:
    return HurdleAccountState(
        balance=0.0,
        outstanding_capital=0.0,
        accrued_return=0.0,
        cumulative_contributions=0.0,
        cumulative_distributions=0.0,
    )


def _moic_balance(condition: MoicHurdle, contributions: float, distributions: float) -> float:
    return condition.multiple * contributions - distributions


def accrue(state: HurdleAccountState, condition: HurdleCondition) -> tuple[HurdleAccountState, float]:
    """One annual period of accrual on the opening state: ``(state, accrual)``."""

    if isinstance(condition, MoicHurdle):
        return state, 0.0
    if condition.accrual_convention is AccrualConvention.ANNUAL_COMPOUND:
        balance = state.balance * (1.0 + condition.rate)
        return replace(state, balance=balance), balance - state.balance
    accrual = condition.rate * max(0.0, state.outstanding_capital)
    accrued = state.accrued_return + accrual
    return replace(state, accrued_return=accrued, balance=state.outstanding_capital + accrued), accrual


def apply_contribution(state: HurdleAccountState, condition: HurdleCondition, amount: float) -> HurdleAccountState:
    """The subject contributed ``amount`` this period."""

    contributions = state.cumulative_contributions + amount
    if isinstance(condition, MoicHurdle):
        return replace(
            state,
            cumulative_contributions=contributions,
            balance=_moic_balance(condition, contributions, state.cumulative_distributions),
        )
    if condition.accrual_convention is AccrualConvention.ANNUAL_COMPOUND:
        return replace(state, cumulative_contributions=contributions, balance=state.balance + amount)
    capital = state.outstanding_capital + amount
    return replace(
        state,
        cumulative_contributions=contributions,
        outstanding_capital=capital,
        balance=capital + state.accrued_return,
    )


def apply_simple_distribution(
    capital: float, accrued: float, amount: float, order: SimpleDistributionOrder
) -> tuple[float, float]:
    """``(outstanding_capital, accrued_return)`` after a SIMPLE subject
    distribution of ``amount``, in the stated order. Any excess beyond both
    drives outstanding capital negative."""

    if order is SimpleDistributionOrder.ACCRUED_RETURN_FIRST:
        paid_accrued = min(amount, accrued)
        return capital - (amount - paid_accrued), accrued - paid_accrued
    paid_capital = min(amount, max(0.0, capital))
    paid_accrued = min(amount - paid_capital, accrued)
    return capital - paid_capital - (amount - paid_capital - paid_accrued), accrued - paid_accrued


def apply_distribution(state: HurdleAccountState, condition: HurdleCondition, amount: float) -> HurdleAccountState:
    """The subject received ``amount`` this period, from any tier."""

    distributions = state.cumulative_distributions + amount
    if isinstance(condition, MoicHurdle):
        return replace(
            state,
            cumulative_distributions=distributions,
            balance=_moic_balance(condition, state.cumulative_contributions, distributions),
        )
    if condition.accrual_convention is AccrualConvention.ANNUAL_COMPOUND:
        return replace(state, cumulative_distributions=distributions, balance=state.balance - amount)
    order = condition.simple_distribution_order
    assert isinstance(condition, IrrHurdle) and order is not None
    capital, accrued = apply_simple_distribution(state.outstanding_capital, state.accrued_return, amount, order)
    return replace(
        state,
        cumulative_distributions=distributions,
        outstanding_capital=capital,
        accrued_return=accrued,
        balance=capital + accrued,
    )


def is_satisfied(balance: float) -> bool:
    return balance <= WATERFALL_AMOUNT_TOLERANCE


def condition_capacity(balance: float, subject_share: float) -> float:
    """The tier cash that brings one condition's balance to zero: every tier
    dollar pays the subject ``subject_share``. The caller guarantees a positive
    share whenever the balance is outstanding."""

    if is_satisfied(balance):
        return 0.0
    capacity = balance / subject_share
    return 0.0 if capacity <= WATERFALL_AMOUNT_TOLERANCE else capacity


def combine_capacities(capacities: tuple[float, ...], combinator: HurdleCombinator) -> float:
    """``ALL``: pay until every condition is met (the largest capacity).
    ``ANY``: until any is met (the smallest)."""

    return max(capacities) if combinator is HurdleCombinator.ALL else min(capacities)
