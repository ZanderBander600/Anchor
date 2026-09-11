"""Phase 6 Gate D6.1 -- the Business Plan resolver.

Restates ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 4, 5,
13 and 19; that document governs on any discrepancy.

``resolve_business_plan`` is the single place a Business Plan becomes dollars.
It owns every item, the model-month to hold-year bucketing, the closing (``T0``)
classification, the post-hold classification and the owner-expense active-year
rule, and it hands the engine an ``OwnerCapitalSchedule`` that knows none of
them (Section 13).

**Pure and unwired.** No I/O, no clock, no randomness, and no knowledge of NOI,
debt, leasing, sensitivity or persistence. No acquisition-analysis path calls
this resolver at D6.1; D6.2 owns the engine wiring.

**Order independence.** Every total is a ``math.fsum``, which returns the
correctly rounded value of the *exact* sum of its inputs. The result therefore
does not depend on the order items are declared in, so two plans holding the
same items in different orders resolve to exactly equal schedules -- not
merely equal within tolerance -- with no sorting step. Descriptions and
categories are never read here, so they cannot move a figure either.
"""

from __future__ import annotations

from collections.abc import Iterable
from math import fsum, inf

from ..engine.contracts import NonFiniteResultError, OwnerCapitalSchedule
from .contracts import BusinessPlan, OwnerExpenseHoldTreatment, OwnerExpenseItem
from .validation import require_valid_business_plan

_MONTHS_PER_YEAR = 12


def _require_hold_period(hold_period: int) -> None:
    """A whole number of years, at least 1 -- Anchor's existing, unmodified
    hold-period convention, guarded here exactly as
    ``anchor.leasing.calendar.projection_month_count`` guards it."""

    if isinstance(hold_period, bool) or not isinstance(hold_period, int):
        raise TypeError(
            f"hold_period must be a whole number of years; got {hold_period!r}."
        )
    if hold_period < 1:
        raise ValueError(
            f"hold_period must be at least 1 year; got {hold_period!r}."
        )


def _hold_year_for_month(month: int) -> int:
    """Hold year of a model month ``>= 1``: months 1-12 are Year 1, 13-24 are
    Year 2, and ``12(y-1)+1 .. 12y`` is Year ``y`` (Section 4)."""

    return (month - 1) // _MONTHS_PER_YEAR + 1


def _active_years(item: OwnerExpenseItem, hold_period: int) -> range:
    """``[first_year .. last_year] ∩ [1 .. H]``, reading ``last_year = None``
    as ``H`` (Section 5, decision D16). Empty when the item starts after the
    hold."""

    effective_last_year = hold_period if item.last_year is None else item.last_year
    return range(item.first_year, min(effective_last_year, hold_period) + 1)


def _total(field_name: str, amounts: Iterable[float]) -> float:
    """The exact, order-independent sum of finite, validated amounts.

    ``fsum`` never returns a non-finite value from finite inputs: it raises
    ``OverflowError`` instead. That is surfaced as the engine's one non-finite
    convention, ``NonFiniteResultError``, rather than as a second one.
    """

    try:
        return fsum(amounts)
    except OverflowError as error:
        raise NonFiniteResultError(field_name, inf) from error


def resolve_business_plan(
    business_plan: BusinessPlan, *, hold_period: int
) -> OwnerCapitalSchedule:
    """Resolve a Business Plan into its ``OwnerCapitalSchedule`` for a hold
    of ``hold_period`` years.

    Capital items, by ``month`` (Section 4):

    - ``month == 0`` -> ``closing_project_capital``;
    - ``1 <= month <= 12H`` -> ``project_capital_by_year[y - 1]`` with
      ``y = ((month - 1) // 12) + 1``;
    - ``month > 12H`` -> ``post_hold_project_capital`` only. It never enters
      a hold year, including Year ``H`` (Section 19).

    Owner-expense items: each active year ``y`` in
    ``[first_year .. last_year] ∩ [1 .. H]`` (``None`` read as ``H``) receives
    exactly ``annual_amount`` in ``owner_expenses_by_year[y - 1]``. Years
    outside the hold have no financial effect and produce no post-hold total
    (Section 5).

    The empty plan resolves to all zeros: ``0.0`` closing, ``H`` zero years in
    each series and ``0.0`` post-hold.

    Raises ``TypeError`` or ``ValueError`` for an invalid ``hold_period`` and
    ``BusinessPlanValidationError`` for an invalid plan. Nothing is coerced.
    """

    _require_hold_period(hold_period)
    require_valid_business_plan(business_plan)

    last_hold_month = _MONTHS_PER_YEAR * hold_period

    closing: list[float] = []
    capital_by_year: list[list[float]] = [[] for _ in range(hold_period)]
    post_hold: list[float] = []
    for capital_item in business_plan.capital_items:
        month = capital_item.month
        if month == 0:
            closing.append(capital_item.amount)
        elif month <= last_hold_month:
            capital_by_year[_hold_year_for_month(month) - 1].append(
                capital_item.amount
            )
        else:
            post_hold.append(capital_item.amount)

    expenses_by_year: list[list[float]] = [[] for _ in range(hold_period)]
    for expense_item in business_plan.owner_expense_items:
        for year in _active_years(expense_item, hold_period):
            expenses_by_year[year - 1].append(expense_item.annual_amount)

    return OwnerCapitalSchedule(
        closing_project_capital=_total("closing_project_capital", closing),
        project_capital_by_year=tuple(
            _total(f"project_capital_by_year[{index}]", amounts)
            for index, amounts in enumerate(capital_by_year)
        ),
        owner_expenses_by_year=tuple(
            _total(f"owner_expenses_by_year[{index}]", amounts)
            for index, amounts in enumerate(expenses_by_year)
        ),
        post_hold_project_capital=_total("post_hold_project_capital", post_hold),
    )


def owner_expense_hold_treatments(
    business_plan: BusinessPlan, *, hold_period: int
) -> tuple[tuple[str, OwnerExpenseHoldTreatment], ...]:
    """Report how each owner-expense item's scheduled years relate to the hold.

    Returns one ``(item_id, treatment)`` pair per owner-expense item, in
    declared order. Item IDs are unique across the plan, so ``dict(...)`` of
    the result is an unambiguous lookup.

    Uses the same active-year rule as ``resolve_business_plan``:

    - no active year -> ``FULLY_OUTSIDE_HOLD``;
    - an explicit ``last_year`` after the hold -> ``PARTIALLY_OUTSIDE_HOLD``;
    - otherwise -> ``FULLY_INSIDE_HOLD``. That includes every ``None``-ended
      item starting within the hold, because ``None`` means "through the
      current hold".

    **Reporting only**: nothing here feeds ``OwnerCapitalSchedule``. Validates
    exactly as ``resolve_business_plan`` does.
    """

    _require_hold_period(hold_period)
    require_valid_business_plan(business_plan)

    treatments: list[tuple[str, OwnerExpenseHoldTreatment]] = []
    for item in business_plan.owner_expense_items:
        if not _active_years(item, hold_period):
            treatment = OwnerExpenseHoldTreatment.FULLY_OUTSIDE_HOLD
        elif item.last_year is not None and item.last_year > hold_period:
            treatment = OwnerExpenseHoldTreatment.PARTIALLY_OUTSIDE_HOLD
        else:
            treatment = OwnerExpenseHoldTreatment.FULLY_INSIDE_HOLD
        treatments.append((item.item_id, treatment))
    return tuple(treatments)
