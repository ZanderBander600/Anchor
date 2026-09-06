"""Sprint D Gate D4.1 -- canonical monthly property expenses and the pool.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 10, 11 and 12 (and D0 Section 13.2) exactly; those documents govern
on any discrepancy.

Two responsibilities, in one direction:

1. **Project the five fixed property operating expense lines** onto the
   canonical monthly Lease-Level timeline, growing them in annual steps on
   analysis-start anniversaries.
2. **Construct the authoritative monthly recoverable expense pool** from those
   completed monthly dollars -- the series D3 has consumed as an injected
   input since D3.1, closing HD-D3-8.

**The dependency is one-way and that is what makes the model solvable.**

```
fixed property expenses  ->  recoverable expense pool  ->  (D3) tenant recoveries
```

Nothing here reads rent, recovery revenue, EGI, a management fee or NOI. The
pool depends only on the five fixed lines and ``expense_growth``, which is why
D0 Section 16.4's eight-step per-month order is not merely a convention that
happens to work but the single topological order of an acyclic graph: there is
no edge from the management fee back to the pool, so no fixed-point solve, no
iteration and no circular reference exists anywhere (D4 Section 13).

**This module performs no occupancy arithmetic and cannot.** A fully vacant
building still pays its taxes, insurance and utilities, so the fixed-expense
builder takes no ``Suite``, no ``Lease``, no occupied area and no occupancy
ratio -- the vacancy independence is structural, visible in the signature,
rather than a rule someone must remember (D4 Section 25.2, FM-D4-14).

**Deliberately absent, all of it later work:** the management fee (D4.3, and
its absence from the pool is load-bearing), other income, credit loss, EGI,
NOI, TI, LC, CapEx, the annual adapter, exit NOI, and every acquisition, debt
and return integration. Recovery *revenue* is D3's and is never computed here:
this module stops at the property-level pool of dollars **eligible** for
reimbursement and says nothing about which tenant reimburses what.
"""

from __future__ import annotations

from math import inf

from ..engine.contracts import ensure_finite
from .contracts import (
    LeaseLevelOperatingInputs,
    ModelMonth,
    MonthlyPropertyExpenseSchedule,
    RecoverableExpensePool,
)
from .validation import (
    require_valid_lease_level_operating_inputs,
    require_valid_recoverable_expense_ratio,
)


_MONTHS_PER_YEAR = 12

#: The five eligible fixed property operating expense lines, in the exact
#: order ``MonthlyPropertyExpenseSchedule`` declares them and in which
#: ``fixed_operating_expenses`` accumulates them. Named once, here, so the
#: projection, the total and the pool cannot disagree about which lines exist
#: -- adding a sixth eligible category would be one edit, reviewed, rather
#: than three edits that might drift (failure modes FM-D4-6, FM-D4-32).
#:
#: The management fee is **not** a member and never will be: it is
#: percentage-derived from EGI, and its exclusion is what breaks the
#: recoveries/fee circularity (D0 Section 16.3, D3 Section 3.2).
FIXED_EXPENSE_LINES: tuple[str, ...] = (
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "other_operating_expenses",
)


def _growth_factor(growth: float, exponent: int) -> float:
    """Return ``(1 + growth) ** exponent``.

    **Mirrors ``anchor.engine.operating_projection._growth_factor`` exactly**,
    which itself mirrors ``anchor.engine.noi._growth_factor``, for the same
    reason: CPython's ``float ** int`` raises ``OverflowError`` instead of
    returning ``inf`` when the mathematical result exceeds double precision.
    Since ``expense_growth > -1`` is guaranteed by the input domain, the base
    is always positive, so an overflow can only mean the true result is
    unrepresentably large and positive; it is surfaced as ``inf`` here so
    ``ensure_finite`` can catch and reject it explicitly, exactly as both
    engine producers already do.

    **This is a deliberate, reviewed duplication (HD-D4-1, approved).** D0
    Section 13.1 preferred extracting a shared helper, but ``anchor.leasing``
    may import only ``anchor.contracts`` and ``anchor.engine.contracts``, and
    ``anchor.engine.operating_projection`` is on the forbidden-import list --
    so the shared helper cannot live where D0 assumed without either putting
    arithmetic into a contracts module that performs none, or widening an
    architecture guardrail during the very gate obliged to prove Detailed
    bit-identical. D0 Section 13.1's own stated fallback was taken instead,
    which leaves Detailed **untouched** and makes G-2 trivially true.

    The condition attached to that approval is that duplication must never
    become drift: ``annual_expense_amount`` below is proven **bit/hex
    identical** to the Detailed annual amount for identical inputs
    (guardrail G-D4-5), and exactly one Lease-Level implementation of this
    formula exists (G-D4-6).
    """

    try:
        return (1 + growth) ** exponent
    except OverflowError:
        return inf


def annual_expense_amount(
    *, year_1_amount: float, expense_growth: float, model_year: int
) -> float:
    """Return one fixed expense line's annual amount in ``model_year``.

    ```
    AnnualAmount_y = Year1Amount * (1 + expense_growth) ** (y - 1)
    ```

    ``model_year`` is ``ModelMonth.hold_year`` -- ``1..H`` for hold months and
    ``H + 1`` for the twelve forward exit months -- so growth steps on
    **analysis-start anniversaries**, never on calendar January
    (FM-D4-12). With a July analysis start, model month 13 is the following
    July and is the first month at the Year-2 rate; the January in between
    changes nothing.

    Year 1 is the base year: the exponent is ``0`` and the factor is exactly
    ``1.0``, so ``AnnualAmount_1`` is ``year_1_amount`` bit for bit.

    **The single Lease-Level implementation of fixed-expense growth**
    (guardrail G-D4-6). ``build_property_expense_schedule`` calls it and
    ``build_recoverable_expense_pool`` deliberately does not -- the pool is
    built from the *completed* schedule, so no second growth calculation can
    drift from this one (FM-D4-40).

    **Operand order is load-bearing.** ``anchor.engine.operating_projection``
    computes ``detailed_inputs.property_taxes * expense_factor`` where
    ``expense_factor = _growth_factor(expense_growth, year_index)`` and
    ``year_index = year - 1``. This function performs the identical single
    multiplication of the identical two operands in the identical order, which
    is why the two are bit/hex identical rather than merely close. Reordering
    the multiply, folding the ``/ 12`` in early, or accumulating year over year
    would each be a different float computation.

    No monthly compounding: the exponent is a whole model year, and there is
    no ``(1 + g) ** (1/12)`` and no ``g / 12`` anywhere (FM-D4-11).
    """

    return year_1_amount * _growth_factor(expense_growth, model_year - 1)


def _require_canonical_months(months: tuple[ModelMonth, ...]) -> None:
    """Assert ``months`` is a canonical ``ModelMonth`` timeline.

    A construction-boundary assertion against a programming error, in the same
    spirit as ``calendar.projection_month_count``'s guard and
    ``market.build_property_market_rent_schedules``' anchor check -- **not** a
    second validation authority, and it re-checks no domain
    ``anchor.leasing.validation`` owns.

    It restates exactly the invariants ``build_model_months`` already
    guarantees and ``ModelMonth`` already documents: 1-based sequential
    ``period_index`` matching array position, and
    ``hold_year == ((period_index - 1) // 12) + 1``. Checking them here is what
    makes a hand-built, duplicated or reordered month tuple fail loudly
    instead of silently producing a plausible expense schedule whose growth
    steps land in the wrong months.
    """

    if not months:
        raise ValueError(
            "months must be the canonical ModelMonth timeline; got an empty "
            "sequence."
        )

    for position, month in enumerate(months):
        expected_index = position + 1
        if month.period_index != expected_index:
            raise ValueError(
                f"months[{position}] carries period_index "
                f"{month.period_index}, expected {expected_index}; the "
                "canonical timeline is 1-based, sequential and gap-free."
            )
        expected_hold_year = (expected_index - 1) // _MONTHS_PER_YEAR + 1
        if month.hold_year != expected_hold_year:
            raise ValueError(
                f"months[{position}] carries hold_year {month.hold_year}, "
                f"expected {expected_hold_year}; expense growth steps on the "
                "model anniversary derived from period_index."
            )


def build_property_expense_schedule(
    operating_inputs: LeaseLevelOperatingInputs,
    *,
    months: tuple[ModelMonth, ...],
) -> MonthlyPropertyExpenseSchedule:
    """Project the five fixed property expense lines onto the canonical months.

    **Validates first, then calculates.** This is a property-level entry point
    taking raw inputs, so it calls
    ``require_valid_lease_level_operating_inputs`` and raises
    ``LeaseValidationError`` on any error rather than quietly projecting a
    schedule from a negative tax bill or a growth rate that would flip sign
    every year. It adds no rule of its own -- there is exactly one leasing
    validation authority.

    **One timeline.** ``months`` is the canonical ``ModelMonth`` tuple the D1-D3
    projection already uses, taken by reference and returned unchanged on the
    result, so a pool built from this schedule shares month *identity* with
    every lease schedule and the recovery builders' alignment checks pass. This
    function never builds a second calendar and never derives months from
    ``analysis_start_date`` and ``hold_period`` itself -- doing so is how two
    subtly different timelines come to exist.

    For each canonical month ``m`` and each of the five lines:

    ```
    AnnualAmount_y  = Year1Amount * (1 + expense_growth) ** (y - 1)
    MonthlyAmount_m = AnnualAmount_y / 12.0        where y = months[m].hold_year
    ```

    **Annual first, then divide.** The division happens after the annual amount
    exists, matching the accepted convention (D0 Section 13.2). Growing a
    pre-divided ``Year1Amount / 12`` would be a different sequence of float
    operations and is not what the convention says.

    **Level allocation inside each model year, deliberately.** No tax
    seasonality, no insurance renewal month, no utility seasonality, no
    true-up, no accrual or reversal, no cash-payment calendar (D4
    Section 10.5). This changes nothing at annual aggregation -- the only
    resolution any downstream consumer sees -- and the monthly display of an
    evenly spread expense is honest about being an accrual.

    **The forward exit window is projected too.** ``months`` spans ``12H + 12``
    entries and the final twelve carry ``hold_year == H + 1``, so they receive
    the genuinely grown Year-``H+1`` expenses rather than a frozen Hold-Year-``H``
    figure (FM-D4-9 in the D4.1 mutation set). D4.1 computes no exit NOI; it
    only makes sure the expenses that gate will need are right.

    **Occupancy cannot reach this calculation.** There is no suite, lease,
    occupied area, vacant area or occupancy parameter in this signature, so a
    fully vacant building's expenses are bit-identical to a fully leased one's
    (D4 Section 25.2). Nothing is multiplied by occupancy or by
    ``1 - vacancy``, and there is no gross-up.

    Pure and deterministic: no I/O, no mutation, no ``set`` or ``dict``
    iteration contributing to any figure.
    """

    require_valid_lease_level_operating_inputs(operating_inputs)
    _require_canonical_months(months)

    projected: dict[str, list[float]] = {name: [] for name in FIXED_EXPENSE_LINES}
    fixed_operating_expenses: list[float] = []

    for month in months:
        model_year = month.hold_year
        total = 0.0
        for name in FIXED_EXPENSE_LINES:
            annual = ensure_finite(
                f"{name}[{month.period_index}] annual",
                annual_expense_amount(
                    year_1_amount=getattr(operating_inputs, name),
                    expense_growth=operating_inputs.expense_growth,
                    model_year=model_year,
                ),
            )
            monthly = ensure_finite(
                f"{name}[{month.period_index}]", annual / _MONTHS_PER_YEAR
            )
            projected[name].append(monthly)
            total += monthly
        fixed_operating_expenses.append(
            ensure_finite(
                f"fixed_operating_expenses[{month.period_index}]", total
            )
        )

    return MonthlyPropertyExpenseSchedule(
        months=months,
        property_taxes=tuple(projected["property_taxes"]),
        insurance=tuple(projected["insurance"]),
        utilities=tuple(projected["utilities"]),
        repairs_maintenance=tuple(projected["repairs_maintenance"]),
        other_operating_expenses=tuple(projected["other_operating_expenses"]),
        fixed_operating_expenses=tuple(fixed_operating_expenses),
    )


def build_recoverable_expense_pool(
    expenses: MonthlyPropertyExpenseSchedule,
    *,
    recoverable_expense_ratio: float,
) -> RecoverableExpensePool:
    """Construct the authoritative monthly recoverable expense pool (HD-D3-8).

    ```
    RecoverablePool_m = recoverable_expense_ratio * fixed_operating_expenses_m
    ```

    where ``fixed_operating_expenses_m`` is the completed sum of exactly the
    five eligible lines. That is D0 Section 16.3's
    ``(TotalOpex_m - ManagementFee_m) * recoverable_expense_ratio`` with the
    difference expanded to the five lines it equals by construction, and the
    **expanded form is the one implemented** (D4 Section 12.1): it never
    computes a total only to subtract a component back out, it cannot pick up a
    future sixth expense line without an explicit decision, and at this gate no
    management fee exists to subtract in the first place.

    **This closes the D3/D4 seam.** Since D3.1, every recovery builder has
    taken a ``RecoverableExpensePool`` as an injected input, and
    ``RecoverableExpensePool``'s own docstring names D4 as the owner of its
    construction. This is that owner. The **existing, unmodified** D3 contract
    is returned -- no ``D4RecoverableExpensePool`` and no parallel pool type
    exists -- carrying ``expenses.months`` **by reference**, so the month
    identity checks throughout ``recoveries.py`` pass rather than merely the
    length checks.

    **Built from the completed schedule, never recomputed.** This function
    performs no expense growth of its own and never calls
    ``annual_expense_amount``: there is one property expense authority, and a
    second growth calculation here is exactly how the pool would come to
    disagree with the expense line it is supposed to be a fraction of
    (FM-D4-40).

    **One global ratio, not category ratios.** The D4 competition model applies
    a single ``recoverable_expense_ratio`` to the total eligible pool. There is
    no tax ratio, insurance ratio, utility ratio or CAM ratio; per-category
    recoverability is HD-D3-5 and stays deferred, and when it arrives the pool
    becomes a sum of category pools with no consumer affected.

    **Eligibility.** Included: property taxes, insurance, utilities, repairs
    and maintenance, other fixed operating expenses. Excluded: the management
    fee (D0 Section 16.3 -- circularity and market practice), capital
    expenditures, TI, LC, debt service, acquisition costs, financing fees and
    disposition costs. None of the excluded items appears in
    ``MonthlyPropertyExpenseSchedule`` at all, so the exclusion is structural
    rather than a subtraction someone must remember to perform.

    **The pool is property-level eligibility, not tenant revenue.** It is the
    total dollars *eligible* for reimbursement. What each tenant actually
    reimburses -- `NNN` first-dollar, `GROSS` zero, `MODIFIED_GROSS` above an
    explicit stop, each scaled by pro-rata share and economic responsibility --
    is D3's, computed in ``recoveries.py``, and nothing of the kind is
    calculated here.

    ``recoverable_expenses[i] >= 0`` holds automatically: every fixed line is
    ``>= 0`` by validated domain and the ratio is in ``[0, 1]``.
    """

    require_valid_recoverable_expense_ratio(recoverable_expense_ratio)

    recoverable_expenses = tuple(
        ensure_finite(
            f"recoverable_expenses[{month.period_index}]",
            recoverable_expense_ratio * fixed_m,
        )
        for month, fixed_m in zip(expenses.months, expenses.fixed_operating_expenses)
    )

    return RecoverableExpensePool(
        months=expenses.months, recoverable_expenses=recoverable_expenses
    )
