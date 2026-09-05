"""Sprint D Gate D3.1 -- tenant expense-recovery revenue.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d3-recovery-conventions.md``
Sections 3, 4, 5.0-5.2 and 7 exactly, and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Section 16; those documents govern on any discrepancy.

**The one question this gate answers.** For a known lease in a suite and a
canonical month: *given the recoverable property expense pool for that month,
how much does this tenant reimburse?* For `NNN` and `GROSS` only.

**Recovery is revenue** (D0 Section 10.2, D3 Section 1.2). It sits on its own
line above EGI and is never a reduction to contractual base rent, never a
reduction to property operating expenses, never a negative expense, and never a
leasing cost. Nothing in this module nets a recovery against anything.

**The D3/D4 seam is the reason this module is small.** It consumes an injected
``RecoverableExpensePool`` and does **not** project operating expenses, convert
the engine's annual figures to monthly, apply expense growth, apply
``recoverable_expense_ratio``, inspect the management fee, or model expense
categories. D4 owns constructing the pool; D3 owns what the tenant does with it.
There is deliberately no shadow expense engine here, which is what D0
Section 13.1 warns against and what keeps ``anchor.leasing`` free of a second,
drifting copy of Detailed's expense formulas.

**Recovery cannot depend on rent.** No function below reads ``base_rent_psf``,
``contractual_base_rent``, ``cash_base_rent``, ``free_rent`` or any cash factor.
An active lease paying zero rent still owes its full share, and a base-rent
concession therefore cannot silently eliminate a reimbursement -- which is what
makes D2's free rent safe to connect at D3.4 (D3 Section 8, failure mode
FM-D3-3).

**Deliberately absent, all of it later work:** `MODIFIED_GROSS`, the expense
stop and `RecoveryBasis` (D3.2); successor recovery assumptions (D3.3); expected
and recursive recoveries (D3.4); property aggregation and annual totals (D3.5);
and every downstream integration, which is D4's.
"""

from __future__ import annotations

from math import isfinite

from ..engine.contracts import ensure_finite
from .contracts import (
    Lease,
    LeaseMonthlySchedule,
    LeaseRecoverySchedule,
    LeaseType,
    RecoverableExpensePool,
)


def tenant_pro_rata_share(
    *, leased_area_sf: float, rentable_area_sf: float
) -> float:
    """Return the fraction of the recoverable pool this lease is liable for.

    ```
    share = leased_area_sf / rentable_area_sf
    ```

    D3 Section 4.1. Both figures are **rentable area on the identical basis**
    (D0 Section 4.2.1): the lease's own ``leased_area_sf`` over the property's
    ``LeaseLevelPropertyInputs.rentable_area_sf``.

    The denominator is deliberately **not** gross building area, occupied area,
    the currently-leased area of the property, a recovered-area figure, a market
    area, or anything derived from physical occupancy. Using occupied area would
    be a silent gross-up, which D3 Section 4.2 defers; using a gross figure
    would inflate every share. Either is failure mode **FM-D3-6**.

    **This denominator is unusually safe in Anchor**, because D1 made the area
    reconciliation exact: ``sum(suite_area_sf) == rentable_area_sf`` is a
    ``RENTABLE_AREA_NOT_RECONCILED`` **ERROR**, and vacant space is a ``Suite``
    with no lease rather than a residual. So across a fully-leased property the
    shares sum to exactly ``1.0``, and the property can never recover more than
    the pool.

    **No override exists in D3.1.** HD-D3-6 leaves an explicit contractual share
    for a later gate, so the area quotient is the only denominator and there is
    no precedence rule to get wrong.

    ``rentable_area_sf > 0`` is guaranteed by validation, so the division is
    always defined; the guard here is a construction-boundary assertion against
    a programming error, not a second validation authority.
    """

    if not isfinite(leased_area_sf) or not isfinite(rentable_area_sf):
        raise ValueError(
            "pro-rata share requires finite areas; got "
            f"leased_area_sf={leased_area_sf!r}, "
            f"rentable_area_sf={rentable_area_sf!r}."
        )
    if rentable_area_sf <= 0:
        raise ValueError(
            f"rentable_area_sf must be greater than 0; got {rentable_area_sf!r}."
        )

    return ensure_finite(
        "tenant_pro_rata_share", leased_area_sf / rentable_area_sf
    )


def lease_responsibility_factors(
    schedule: LeaseMonthlySchedule, *, leased_area_sf: float
) -> tuple[float, ...]:
    """Return a known lease's economic responsibility factor, month by month.

    ```
    O_m = 1.0   while the lease is contractually active in m
    O_m = 0.0   before commencement and after expiration
    ```

    **Derived from the authoritative D1 schedule, not re-derived from dates.**
    ``LeaseMonthlySchedule.occupied_area`` already carries exactly the
    contractual-activity state this needs -- ``leased_area_sf`` while active and
    ``0.0`` otherwise -- so this reads it rather than writing a second
    commencement/expiration formula that could drift from D1's. There remains
    one notion of "is this lease active in this month" in the package.

    **Never derived from rent dollars.** A zero-rent lease is a real, active
    lease and is fully responsible for its share of expenses, so testing
    ``contractual_base_rent > 0`` would silently drop it. D1 makes the same
    distinction for occupancy and for the same reason.

    Because D1 requires both lease dates to be **month-aligned**, a known
    in-place lease has **no fractional responsibility month**: this returns only
    ``0.0`` or ``1.0``. Fractional values are a successor concept, arising from
    a downtime boundary, and reach the arithmetic through
    ``monthly_expense_recovery`` at D3.3/D3.4 rather than from here.
    """

    if leased_area_sf <= 0 or not isfinite(leased_area_sf):
        raise ValueError(
            f"leased_area_sf must be a finite positive area; got "
            f"{leased_area_sf!r}."
        )

    return tuple(
        1.0 if occupied > 0.0 else 0.0 for occupied in schedule.occupied_area
    )


def monthly_expense_recovery(
    *,
    lease_type: LeaseType,
    tenant_recoverable_expense_share: float,
    responsibility_factor: float,
) -> float:
    """Return one lease's expense-recovery revenue for one month, in dollars.

    **The single authoritative recovery formula in the package.** Every schedule
    and every later gate reaches it, so ``factor × share × pool`` exists in one
    place and cannot be re-spelled slightly differently in a builder, an
    aggregation or a test.

    ```
    NNN:    recovery_m = O_m × tenant_recoverable_expense_share_m
    GROSS:  recovery_m = 0.0
    ```

    where ``tenant_recoverable_expense_share_m = share × P_m`` (D3 Section 5.0).

    **`NNN` is first-dollar**: no expense stop, no base year, no deductible, no
    cap, no administrative fee, no gross-up. Each of those is either D3 Section
    6.5-deferred or belongs to `MODIFIED_GROSS`.

    **`GROSS` is an explicit branch, not `NNN` with a zero factor.** The
    distinction is economically meaningful -- a Gross tenant reimburses nothing
    because of *what its lease says*, not because its share or its
    responsibility happens to be zero -- and collapsing the two would make
    ``lease_type`` unreadable in the code that most depends on it. A Gross
    lease returns ``0.0`` whatever its share, its pool or its responsibility.

    **`MODIFIED_GROSS` is refused, explicitly.** It is D3.2's, and it needs an
    explicit contractual basis that does not exist as a field yet. It is
    deliberately **not** treated as Gross, not treated as NNN, and not returned
    as a silent zero: a silent zero would under-recover every Modified Gross
    lease in a rent roll while looking like a computed answer.

    **The responsibility factor scales the full-month obligation**, computed
    first (D3 Section 7.1.1). At D3.1 the obligation is linear in the factor so
    the ordering is not yet observable, but the shape is fixed now because at
    D3.2 it becomes load-bearing: for `MODIFIED_GROSS`, scaling the expense
    share instead of the obligation would compare a partial month's share
    against a whole month's stop (failure mode FM-D3-19).

    Accepting a **fractional** factor is the D3.3/D3.4 seam. This module never
    imports ``rollover``; a successor's ``successor_occupancy_factor`` is simply
    a valid value for this parameter when a later gate passes one.
    """

    if not isfinite(responsibility_factor):
        raise ValueError(
            f"responsibility_factor must be finite; got {responsibility_factor!r}."
        )
    if not 0.0 <= responsibility_factor <= 1.0:
        raise ValueError(
            f"responsibility_factor {responsibility_factor!r} must be between "
            "0 and 1 inclusive; it is a fraction of a month, not a multiplier."
        )

    if lease_type is LeaseType.GROSS:
        return 0.0

    if lease_type is LeaseType.MODIFIED_GROSS:
        raise ValueError(
            "MODIFIED_GROSS expense recovery is not implemented at D3.1; it "
            "requires an explicit contractual recovery basis, which D3.2 "
            "introduces. Refusing rather than returning zero, which would "
            "silently under-recover."
        )

    if lease_type is not LeaseType.NNN:
        raise ValueError(f"unsupported lease type for recovery: {lease_type!r}.")

    if not isfinite(tenant_recoverable_expense_share):
        raise ValueError(
            "tenant_recoverable_expense_share must be finite; got "
            f"{tenant_recoverable_expense_share!r}."
        )

    full_month_recovery = tenant_recoverable_expense_share
    return ensure_finite(
        "monthly_expense_recovery", responsibility_factor * full_month_recovery
    )


def build_lease_recovery_schedule(
    lease: Lease,
    *,
    schedule: LeaseMonthlySchedule,
    pool: RecoverableExpensePool,
    rentable_area_sf: float,
) -> LeaseRecoverySchedule:
    """Return one known lease's canonical monthly expense-recovery revenue.

    **Precondition: the inputs are already validated.** This follows the
    boundary every other builder in this package established -- call
    ``anchor.leasing.validation.require_valid_recovery_inputs`` first.
    Re-validating here would create a second validation authority whose
    behaviour could drift from the first.

    ``schedule`` is the lease's own authoritative D1 monthly schedule, from
    ``rent.build_lease_monthly_schedule``. It supplies contractual activity and
    nothing else: this function reads ``occupied_area`` and never a rent series,
    so recovery cannot depend on what the lease pays.

    **Month identity is checked, not just length.** The pool and the lease
    schedule must have been built against the *same* canonical ``ModelMonth``
    tuple. A pool from a different projection would zip cleanly by length and
    produce a plausible, wrong answer, so the mismatch is refused. There is one
    timeline; nothing here builds a second, pads, truncates, or repeats a last
    value.

    The three series returned are, in order of derivation:

    1. ``economic_responsibility_factor`` -- from D1 contractual activity;
    2. ``tenant_recoverable_expense_share`` -- ``share × P_m``, retained for
       audit and reported even for a `GROSS` lease, where the tenant owes none
       of it;
    3. ``expense_recovery`` -- through the single authoritative formula.

    Pure and deterministic: no I/O, no mutation. The lease, its schedule and the
    pool are read and never written.
    """

    if schedule.lease_id != lease.lease_id:
        raise ValueError(
            f"schedule belongs to lease {schedule.lease_id!r}, not to "
            f"{lease.lease_id!r}; a recovery schedule must describe its own "
            "lease."
        )
    if schedule.months != pool.months:
        raise ValueError(
            "the lease schedule and the recoverable expense pool were built "
            "against different month sequences; both must share one canonical "
            "timeline."
        )

    months = pool.months
    share = tenant_pro_rata_share(
        leased_area_sf=lease.leased_area_sf, rentable_area_sf=rentable_area_sf
    )
    factors = lease_responsibility_factors(
        schedule, leased_area_sf=lease.leased_area_sf
    )

    tenant_share: list[float] = []
    recovery: list[float] = []

    for position in range(len(months)):
        month_share = ensure_finite(
            "tenant_recoverable_expense_share",
            share * pool.recoverable_expenses[position],
        )
        tenant_share.append(month_share)
        recovery.append(
            monthly_expense_recovery(
                lease_type=lease.lease_type,
                tenant_recoverable_expense_share=month_share,
                responsibility_factor=factors[position],
            )
        )

    return LeaseRecoverySchedule(
        lease_id=lease.lease_id,
        suite_id=lease.suite_id,
        lease_type=lease.lease_type,
        months=months,
        tenant_pro_rata_share=share,
        economic_responsibility_factor=factors,
        tenant_recoverable_expense_share=tuple(tenant_share),
        expense_recovery=tuple(recovery),
    )
