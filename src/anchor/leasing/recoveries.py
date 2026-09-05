"""Sprint D Gate D3.1 -- tenant expense-recovery revenue.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d3-recovery-conventions.md``
Sections 3, 4, 5.0-5.2 and 7 exactly, and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Section 16; those documents govern on any discrepancy.

**The one question this gate answers.** For a known lease in a suite and a
canonical month: *given the recoverable property expense pool for that month,
how much does this tenant reimburse?* D3.1 answered it for `NNN` and `GROSS`;
D3.2 adds `MODIFIED_GROSS`, which reimburses only the part of its share that
exceeds an **explicit** contractual expense stop.

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

**Deliberately absent, all of it later work:** successor recovery assumptions
(D3.3); expected and recursive recoveries (D3.4); property aggregation and
annual totals (D3.5); and every downstream integration, which is D4's. Also
absent, and permanently so at this layer: any calendar or historical base year,
which D3 Section 6.2 rejected because Anchor cannot source the actuals it would
need, and any escalation of the stop, which D3 Section 6.3 fixed nominally.
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
    RecoveryBasis,
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


def monthly_expense_stop_dollars(
    *, expense_stop_psf: float, leased_area_sf: float
) -> float:
    """Return a Modified Gross lease's monthly expense stop, in **dollars**.

    ```
    monthly_expense_stop_dollars = expense_stop_psf × leased_area_sf / 12
    ```

    D3 Section 5.0 and 6.2. ``expense_stop_psf`` is stated in **``$/SF/YEAR``**
    -- the units a lease abstract uses -- and is converted to the tenant's own
    monthly dollar threshold here, **dividing by 12 once, last**, exactly as D1
    does for ``base_rent_psf``.

    **This conversion is why the comparison is dimensionally valid.** The
    Modified Gross clip subtracts this figure from the tenant's monthly share of
    the pool, and both are then tenant-level dollars per month. Subtracting a
    ``$/SF`` rate from pool dollars instead would not be a smaller number but a
    meaningless one, and because both are positive it would still produce a
    plausible-looking figure -- failure mode **FM-D3-18**.

    **The result is constant for the life of the lease.** The stop is nominally
    fixed (D3 Section 6.3, HD-D3-4): it does not grow with property expense
    growth, market rent growth or contractual rent escalation, and does not
    reset annually, on a lease anniversary, or at acquisition. There is
    deliberately no escalation parameter to supply. That fixity is what makes
    the structure economically interesting -- the pool grows past a stationary
    threshold, and recoveries emerge.

    The area is the lease's own ``leased_area_sf``, so the threshold scales with
    the space the tenant actually occupies, not with the building.
    """

    if not isfinite(expense_stop_psf):
        raise ValueError(
            f"expense_stop_psf must be finite; got {expense_stop_psf!r}."
        )
    if expense_stop_psf < 0:
        raise ValueError(
            f"expense_stop_psf {expense_stop_psf!r} must be greater than or "
            "equal to 0."
        )
    if not isfinite(leased_area_sf) or leased_area_sf <= 0:
        raise ValueError(
            f"leased_area_sf must be a finite positive area; got "
            f"{leased_area_sf!r}."
        )

    return ensure_finite(
        "monthly_expense_stop_dollars", expense_stop_psf * leased_area_sf / 12.0
    )


def monthly_expense_recovery(
    *,
    lease_type: LeaseType,
    tenant_recoverable_expense_share: float,
    responsibility_factor: float,
    monthly_stop_dollars: float | None = None,
) -> float:
    """Return one lease's expense-recovery revenue for one month, in dollars.

    **The single authoritative recovery formula in the package.** Every schedule
    and every later gate reaches it, so ``factor × share × pool`` exists in one
    place and cannot be re-spelled slightly differently in a builder, an
    aggregation or a test.

    ```
    NNN:             full_month = tenant_recoverable_expense_share_m
    GROSS:           recovery_m = 0.0
    MODIFIED_GROSS:  full_month = max(0, tenant_recoverable_expense_share_m
                                         − monthly_stop_dollars)

    recovery_m = O_m × full_month
    ```

    where ``tenant_recoverable_expense_share_m = share × P_m`` (D3 Section 5.0)
    and ``monthly_stop_dollars = expense_stop_psf × leased_area_sf / 12``.

    **Both terms inside the clip are tenant-level dollars per month.** That is
    the whole point of converting the stop first: the comparison is the tenant's
    share of this month's pool against the tenant's own monthly threshold, in
    the units a lease abstract states (failure mode FM-D3-18).

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
    first, and this is now load-bearing (D3 Section 7.1.1). For
    `MODIFIED_GROSS` the two orderings genuinely differ:

    ```
    O_m × max(0, share − stop)     <-- CORRECT
    max(0, O_m × share − stop)     <-- WRONG
    ```

    The wrong form compares a *partial* month's expense share against a *whole*
    month's stop, so it under-recovers in every fractional responsibility month
    and can report zero where the lease genuinely owes money. On the reference
    case -- a $40,000 share against a $20,000 stop at ``O_m = 0.75`` -- the
    correct form gives ``$15,000`` and the wrong one ``$10,000``. Failure mode
    **FM-D3-19**.

    **Below or exactly at the stop, recovery is exactly zero.** There is no
    negative reimbursement, no landlord credit, no carryforward and no
    cumulative annual true-up; each of those is a separate structure Anchor does
    not model. At exactly the stop the clip returns ``0.0`` on ordinary float
    arithmetic, with no tolerance applied to manufacture a positive result.

    **A zero stop is economically valid**, and makes a Modified Gross lease
    recover its full tenant share -- numerically identical to `NNN` for the same
    pool, share and factor. The lease is still Modified Gross: `lease_type`
    describes the contract, not the arithmetic that happens to coincide.

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
        # A stop supplied on a Gross lease is refused rather than ignored: *a
        # stop implies Modified Gross*, and consuming one here would make
        # `lease_type` unreliable as an economic discriminator (D3 Section 5.2).
        if monthly_stop_dollars is not None:
            raise ValueError(
                "a GROSS lease carries no expense stop; a lease with a "
                "contractual stop is MODIFIED_GROSS."
            )
        return 0.0

    if not isfinite(tenant_recoverable_expense_share):
        raise ValueError(
            "tenant_recoverable_expense_share must be finite; got "
            f"{tenant_recoverable_expense_share!r}."
        )

    if lease_type is LeaseType.NNN:
        if monthly_stop_dollars is not None:
            raise ValueError(
                "an NNN lease recovers from the first dollar and carries no "
                "expense stop; a lease with a contractual stop is "
                "MODIFIED_GROSS."
            )
        full_month_recovery = tenant_recoverable_expense_share

    elif lease_type is LeaseType.MODIFIED_GROSS:
        if monthly_stop_dollars is None:
            raise ValueError(
                "MODIFIED_GROSS recovery requires an explicit contractual "
                "expense stop. Anchor never infers one -- not from Hold Year 1, "
                "the analysis year, the acquisition year or the current "
                "expense schedule -- so this refuses rather than defaulting."
            )
        if not isfinite(monthly_stop_dollars):
            raise ValueError(
                f"monthly_stop_dollars must be finite; got "
                f"{monthly_stop_dollars!r}."
            )
        # The single economically operative clip in the package. Both operands
        # are tenant-level dollars per month.
        full_month_recovery = max(
            0.0, tenant_recoverable_expense_share - monthly_stop_dollars
        )

    else:
        raise ValueError(f"unsupported lease type for recovery: {lease_type!r}.")

    # The factor scales the finished obligation, never a term inside the clip.
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

    The series returned are, in order of derivation:

    1. ``economic_responsibility_factor`` -- from D1 contractual activity;
    2. ``tenant_recoverable_expense_share`` -- ``share × P_m``, **before** any
       stop, structure or factor. Its meaning is unchanged from D3.1: it is the
       tenant's raw arithmetic share, reported even for a `GROSS` lease that
       owes none of it and for a `MODIFIED_GROSS` lease whose stop consumes it;
    3. ``full_month_expense_recovery`` -- the obligation before responsibility,
       which is where the Modified Gross clip lands;
    4. ``expense_recovery`` -- the factor applied to that obligation, through
       the single authoritative formula.

    For a `MODIFIED_GROSS` lease the monthly stop is computed **once**, from the
    lease's own ``expense_stop_psf`` and area, because it is nominally fixed and
    neither input varies by month.

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

    # The stop is nominally fixed and the area does not vary, so this is a
    # scalar computed once. `None` for every structure that carries no stop.
    stop_dollars: float | None = None
    if lease.lease_type is LeaseType.MODIFIED_GROSS:
        if lease.recovery_basis is None or lease.expense_stop_psf is None:
            raise ValueError(
                f"lease {lease.lease_id!r} is MODIFIED_GROSS and carries no "
                "explicit contractual recovery basis; Anchor never infers one. "
                "Validate recovery inputs before building a schedule."
            )
        if lease.recovery_basis is not RecoveryBasis.EXPENSE_STOP_PSF:
            raise ValueError(
                f"recovery basis {lease.recovery_basis!r} is not implemented; "
                "D3 supports only EXPENSE_STOP_PSF."
            )
        stop_dollars = monthly_expense_stop_dollars(
            expense_stop_psf=lease.expense_stop_psf,
            leased_area_sf=lease.leased_area_sf,
        )
    elif lease.expense_stop_psf is not None or lease.recovery_basis is not None:
        raise ValueError(
            f"lease {lease.lease_id!r} is {lease.lease_type.value} but carries "
            "a recovery basis or expense stop; a lease with a contractual stop "
            "is MODIFIED_GROSS."
        )

    tenant_share: list[float] = []
    full_month: list[float] = []
    recovery: list[float] = []

    for position in range(len(months)):
        month_share = ensure_finite(
            "tenant_recoverable_expense_share",
            share * pool.recoverable_expenses[position],
        )
        tenant_share.append(month_share)
        # The obligation at full responsibility, then the factor -- computed by
        # the one authoritative formula, called twice so the audit series and
        # the recognised figure can never disagree about the clip.
        full_month.append(
            monthly_expense_recovery(
                lease_type=lease.lease_type,
                tenant_recoverable_expense_share=month_share,
                responsibility_factor=1.0,
                monthly_stop_dollars=stop_dollars,
            )
        )
        recovery.append(
            monthly_expense_recovery(
                lease_type=lease.lease_type,
                tenant_recoverable_expense_share=month_share,
                responsibility_factor=factors[position],
                monthly_stop_dollars=stop_dollars,
            )
        )

    return LeaseRecoverySchedule(
        lease_id=lease.lease_id,
        suite_id=lease.suite_id,
        lease_type=lease.lease_type,
        months=months,
        tenant_pro_rata_share=share,
        recovery_basis=lease.recovery_basis,
        expense_stop_psf=lease.expense_stop_psf,
        monthly_expense_stop_dollars=stop_dollars,
        economic_responsibility_factor=factors,
        tenant_recoverable_expense_share=tuple(tenant_share),
        full_month_expense_recovery=tuple(full_month),
        expense_recovery=tuple(recovery),
    )
