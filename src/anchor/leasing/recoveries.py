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

from datetime import date
from math import fsum, isfinite

from ..engine.contracts import ensure_finite
from .contracts import (
    ExpectedRollover,
    ExpectedRolloverRecovery,
    Lease,
    LeaseMonthlySchedule,
    LeaseRecoverySchedule,
    LeaseType,
    MarketLeasingAssumptions,
    ModelMonth,
    RecoverableExpensePool,
    RecoveryBasis,
    RecoveryContributionAudit,
    RecursiveRollover,
    RecursiveRolloverRecovery,
    RolloverBranchKind,
    Suite,
    SuccessorContribution,
    SuccessorRecoverySchedule,
)
from .market import MarketRentSchedule
from .rollover import (
    build_successor_contribution,
    resolve_rollover_market_schedule,
    successor_state_lease_id_stem,
    weighted_outcome,
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
    stop_dollars, tenant_share, full_month, recovery = _recovery_series(
        lease_id=lease.lease_id,
        lease_type=lease.lease_type,
        recovery_basis=lease.recovery_basis,
        expense_stop_psf=lease.expense_stop_psf,
        leased_area_sf=lease.leased_area_sf,
        share=share,
        factors=factors,
        pool=pool,
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
        tenant_recoverable_expense_share=tenant_share,
        full_month_expense_recovery=full_month,
        expense_recovery=recovery,
    )


def _resolve_monthly_stop(
    *,
    lease_id: str,
    lease_type: LeaseType,
    recovery_basis: RecoveryBasis | None,
    expense_stop_psf: float | None,
    leased_area_sf: float,
) -> float | None:
    """Return the monthly stop in dollars, or ``None`` where none applies.

    The **one** place a contractual recovery basis is turned into a number.
    Both the in-place builder (D3.1/D3.2) and the successor builder (D3.3)
    reach it, so a known lease and a rollover successor cannot come to
    different conclusions about the same terms.

    The stop is nominally fixed and the area does not vary, so this is a
    scalar computed once rather than a series (HD-D3-4).
    """

    if lease_type is LeaseType.MODIFIED_GROSS:
        if recovery_basis is None or expense_stop_psf is None:
            raise ValueError(
                f"lease {lease_id!r} is MODIFIED_GROSS and carries no "
                "explicit contractual recovery basis; Anchor never infers one. "
                "Validate recovery inputs before building a schedule."
            )
        if recovery_basis is not RecoveryBasis.EXPENSE_STOP_PSF:
            raise ValueError(
                f"recovery basis {recovery_basis!r} is not implemented; "
                "D3 supports only EXPENSE_STOP_PSF."
            )
        return monthly_expense_stop_dollars(
            expense_stop_psf=expense_stop_psf,
            leased_area_sf=leased_area_sf,
        )

    if expense_stop_psf is not None or recovery_basis is not None:
        raise ValueError(
            f"lease {lease_id!r} is {lease_type.value} but carries "
            "a recovery basis or expense stop; a lease with a contractual stop "
            "is MODIFIED_GROSS."
        )
    return None


def _recovery_series(
    *,
    lease_id: str,
    lease_type: LeaseType,
    recovery_basis: RecoveryBasis | None,
    expense_stop_psf: float | None,
    leased_area_sf: float,
    share: float,
    factors: tuple[float, ...],
    pool: RecoverableExpensePool,
) -> tuple[float | None, tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """Return ``(monthly stop, tenant share, full-month obligation, recovery)``.

    **The single recovery calculation in the package.** An in-place lease and a
    rollover successor differ in exactly one input -- where the responsibility
    factor comes from -- so they share this body rather than each carrying a
    copy. A second implementation is how the two would drift, and how a branch
    would acquire its own quietly different Modified Gross clip.

    ``factors`` is supplied by the caller and never derived here: the in-place
    builder passes D1 contractual activity, the successor builder passes the
    branch's ``successor_occupancy_factor``.
    """

    if len(factors) != len(pool.months):
        raise ValueError(
            f"got {len(factors)} responsibility factors for "
            f"{len(pool.months)} model months; both must share one canonical "
            "timeline."
        )

    stop_dollars = _resolve_monthly_stop(
        lease_id=lease_id,
        lease_type=lease_type,
        recovery_basis=recovery_basis,
        expense_stop_psf=expense_stop_psf,
        leased_area_sf=leased_area_sf,
    )

    tenant_share: list[float] = []
    full_month: list[float] = []
    recovery: list[float] = []

    for position in range(len(pool.months)):
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
                lease_type=lease_type,
                tenant_recoverable_expense_share=month_share,
                responsibility_factor=1.0,
                monthly_stop_dollars=stop_dollars,
            )
        )
        recovery.append(
            monthly_expense_recovery(
                lease_type=lease_type,
                tenant_recoverable_expense_share=month_share,
                responsibility_factor=factors[position],
                monthly_stop_dollars=stop_dollars,
            )
        )

    return stop_dollars, tuple(tenant_share), tuple(full_month), tuple(recovery)


def build_successor_recovery_schedule(
    *,
    branch: RolloverBranchKind,
    successor_lease: Lease,
    months: tuple[ModelMonth, ...],
    successor_occupancy_factor: tuple[float, ...],
    commencement_period: int,
    successor_expiration_period: int,
    pool: RecoverableExpensePool,
    rentable_area_sf: float,
) -> SuccessorRecoverySchedule:
    """Return one **pure branch** successor's monthly recovery revenue (D3.3).

    **The pool is injected here, and only here.** No D2 builder takes a
    ``RecoverableExpensePool``: ``build_renewal_branch``,
    ``build_new_tenant_branch`` and ``build_recursive_rollover`` remain usable
    with no property expense input at all, exactly as they were at D2.6. D3
    consumes a *finished* D2 branch and adds recovery economics beside it; it
    never reaches back into rent (D3 Section 3.4, D0 Section 13.1). That
    boundary is what keeps the market-leasing engine independent of an expense
    schedule Anchor may not yet have.

    **The structure comes from the successor lease, which got it from its own
    branch's assumptions** (HD-D3-1, HD-D3-2). This function reads
    ``successor_lease.lease_type``, ``.recovery_basis`` and
    ``.expense_stop_psf`` -- the successor's own terms, resolved at
    construction. It receives no predecessor lease and cannot read one, which
    is what keeps future recovery economics path-independent and the D2.6
    merge key valid (D3 Section 10.2).

    **``successor_occupancy_factor`` is the responsibility factor**, taken
    from the branch unchanged. It is *not* ``physical_occupancy``: in the
    boundary month a fractional downtime creates, physical occupancy is the
    integral ``1`` while the successor is responsible for only part of the
    month. Using occupancy there would over-recover every fractional
    commencement (FM-D3-4). It is not ``cash_rent_factor`` either -- that
    carries free rent, which has no effect on an expense reimbursement
    (D2 Section 7.3, FM-D3-3).

    The arithmetic is the accepted D3.1/D3.2 formula, unchanged and shared:
    ``NNN`` recovers ``O_m × share × P_m`` from the first dollar, ``GROSS``
    recovers exactly ``0.0``, and ``MODIFIED_GROSS`` recovers
    ``O_m × max(0, share × P_m − stop)``. There is no branch-specific variant
    and no second clip.

    **Precondition: the inputs are already validated** -- call
    ``anchor.leasing.validation.require_valid_successor_recovery_assumptions``
    on the resolved assumptions first, as every other builder in this package
    expects.

    Pure and deterministic: no I/O, no mutation.
    """

    if months != pool.months:
        raise ValueError(
            "the branch and the recoverable expense pool were built against "
            "different month sequences; both must share one canonical "
            "timeline."
        )

    share = tenant_pro_rata_share(
        leased_area_sf=successor_lease.leased_area_sf,
        rentable_area_sf=rentable_area_sf,
    )
    stop_dollars, tenant_share, full_month, recovery = _recovery_series(
        lease_id=successor_lease.lease_id,
        lease_type=successor_lease.lease_type,
        recovery_basis=successor_lease.recovery_basis,
        expense_stop_psf=successor_lease.expense_stop_psf,
        leased_area_sf=successor_lease.leased_area_sf,
        share=share,
        factors=successor_occupancy_factor,
        pool=pool,
    )

    return SuccessorRecoverySchedule(
        branch=branch,
        suite_id=successor_lease.suite_id,
        successor_lease_id=successor_lease.lease_id,
        successor_lease_type=successor_lease.lease_type,
        commencement_period=commencement_period,
        successor_expiration_period=successor_expiration_period,
        months=months,
        tenant_pro_rata_share=share,
        recovery_basis=successor_lease.recovery_basis,
        expense_stop_psf=successor_lease.expense_stop_psf,
        monthly_expense_stop_dollars=stop_dollars,
        economic_responsibility_factor=successor_occupancy_factor,
        tenant_recoverable_expense_share=tenant_share,
        full_month_expense_recovery=full_month,
        expense_recovery=recovery,
    )


# =============================================================================
# D3.4 -- probability-weighted and recursive expected recovery
#
# Everything below composes finished branch dollars. It computes no recovery
# formula of its own, and owns no recursion: D2.5's `weighted_outcome` is the
# single weighting primitive and D2.6's `RecursiveRollover` is the single
# event state machine.
# =============================================================================


def _successor_recovery_from_contribution(
    contribution: SuccessorContribution,
    *,
    pool: RecoverableExpensePool,
    rentable_area_sf: float,
) -> SuccessorRecoverySchedule:
    """Price one successor contribution's recovery. The one adapter."""

    return build_successor_recovery_schedule(
        branch=contribution.branch,
        successor_lease=contribution.successor_lease,
        months=contribution.months,
        successor_occupancy_factor=contribution.successor_occupancy_factor,
        commencement_period=contribution.commencement_period,
        successor_expiration_period=contribution.successor_expiration_period,
        pool=pool,
        rentable_area_sf=rentable_area_sf,
    )


def _in_place_recovery(
    lease: Lease,
    *,
    schedule: LeaseMonthlySchedule,
    pool: RecoverableExpensePool,
    rentable_area_sf: float,
) -> LeaseRecoverySchedule:
    """The known lease's own recoveries, at probability ``1``.

    Deterministic, and never weighted. What a sitting tenant owes before its
    lease expires is contractual history, not a scenario -- multiplying it by
    ``p`` or ``1 - p`` would understate every month of it.
    """

    return build_lease_recovery_schedule(
        lease, schedule=schedule, pool=pool, rentable_area_sf=rentable_area_sf
    )


def _combined_chain(
    in_place: tuple[float, ...], successor: tuple[float, ...]
) -> tuple[float, ...]:
    """Add the known lease's recoveries to its successors'.

    A plain sum is correct **because the two are structurally disjoint**: the
    in-place lease's responsibility factor is zero once it expires, and every
    successor schedule is zero at or before that period. The contracts assert
    the disjointness rather than trusting it.
    """

    return tuple(
        ensure_finite("expected_expense_recovery", known + later)
        for known, later in zip(in_place, successor, strict=True)
    )


def build_expected_rollover_recovery(
    rollover: ExpectedRollover,
    *,
    expiring: Lease,
    pool: RecoverableExpensePool,
    rentable_area_sf: float,
) -> ExpectedRolloverRecovery:
    """Return one suite's **first-rollover** expected recovery (D3.4).

    Prices each branch's successor independently, then weights the finished
    dollars through D2.5's ``weighted_outcome`` -- the single probability
    primitive in the package. Reusing it rather than re-expressing
    ``p * r + (1 - p) * n`` is what guarantees the endpoint identities: at
    ``p = 1`` this returns the renewal recovery bit-identically and at
    ``p = 0`` the new-tenant recovery, because the primitive short-circuits
    both rather than relying on ``1.0 * x + 0.0 * y`` to behave.

    **Only dollars are weighted.** Each branch's lease type, recovery basis,
    expense stop, share and responsibility factor produced its own schedule
    first; none of them is ever averaged with the other branch's. That is not
    a stylistic preference: the Modified Gross clip is nonlinear, so weighting
    two stops and clipping once gives a genuinely different and wrong figure
    (FM-D3-10).

    **The pool is injected here.** ``build_expected_rollover`` neither takes
    nor needs one, so the D2 market-leasing engine stays usable with no
    property expense schedule in existence (D3 Section 3.4, D0 Section 13.1).

    ``expiring`` is the in-place lease the branches roll over, supplied because
    an ``ExpectedRollover`` retains its *schedule* but not the lease record
    whose structure prices it. It contributes **once**, unweighted.

    **Precondition: the inputs are already validated.** Pure and
    deterministic: no I/O, no mutation.
    """

    if rollover.months != pool.months:
        raise ValueError(
            "the expected rollover and the recoverable expense pool were built "
            "against different month sequences; both must share one canonical "
            "timeline."
        )
    if expiring.lease_id != rollover.expiring_lease_id:
        raise ValueError(
            f"lease {expiring.lease_id!r} is not the lease this rollover "
            f"expires ({rollover.expiring_lease_id!r}); expected recovery must "
            "describe its own chain."
        )

    renewal = build_successor_recovery_schedule(
        branch=RolloverBranchKind.RENEWAL,
        successor_lease=rollover.renewal_branch.successor_lease,
        months=rollover.months,
        successor_occupancy_factor=(
            rollover.renewal_branch.successor_occupancy_factor
        ),
        commencement_period=rollover.renewal_branch.commencement_period,
        successor_expiration_period=(
            rollover.renewal_branch.successor_expiration_period
        ),
        pool=pool,
        rentable_area_sf=rentable_area_sf,
    )
    new_tenant = build_successor_recovery_schedule(
        branch=RolloverBranchKind.NEW_TENANT,
        successor_lease=rollover.new_tenant_branch.successor_lease,
        months=rollover.months,
        successor_occupancy_factor=(
            rollover.new_tenant_branch.successor_occupancy_factor
        ),
        commencement_period=rollover.new_tenant_branch.commencement_period,
        successor_expiration_period=(
            rollover.new_tenant_branch.successor_expiration_period
        ),
        pool=pool,
        rentable_area_sf=rentable_area_sf,
    )

    known = _in_place_recovery(
        expiring,
        schedule=rollover.renewal_branch.expiring_schedule,
        pool=pool,
        rentable_area_sf=rentable_area_sf,
    )

    expected_successor = tuple(
        weighted_outcome(
            renewal_value,
            new_tenant_value,
            renewal_probability=rollover.renewal_probability,
        )
        for renewal_value, new_tenant_value in zip(
            renewal.expense_recovery, new_tenant.expense_recovery, strict=True
        )
    )

    return ExpectedRolloverRecovery(
        suite_id=rollover.suite_id,
        expiring_lease_id=rollover.expiring_lease_id,
        renewal_probability=rollover.renewal_probability,
        months=rollover.months,
        renewal_recovery=renewal,
        new_tenant_recovery=new_tenant,
        in_place_recovery=known,
        in_place_expense_recovery=known.expense_recovery,
        expected_successor_expense_recovery=expected_successor,
        expected_expense_recovery=_combined_chain(
            known.expense_recovery, expected_successor
        ),
    )


def build_recursive_rollover_recovery(
    rollover: RecursiveRollover,
    *,
    suite: Suite,
    analysis_start: date,
    property_defaults: MarketLeasingAssumptions,
    pool: RecoverableExpensePool,
    rentable_area_sf: float,
    market_schedule: MarketRentSchedule | None = None,
) -> RecursiveRolloverRecovery:
    """Return one suite's expected recovery across **all** generations (D3.4).

    **This function contains no recursion.** It walks
    ``rollover.transitions`` -- the authoritative event list D2.6 already
    produced -- and attaches recovery economics to each. Which expiration
    periods become states, which paths merge, how mass splits at an event, the
    processing order, when the walk stops and how much mass terminates are all
    D2.6's decisions, read here and never re-derived. There is exactly one
    event queue in production and it is not this one.

    A second state machine is the failure this design forecloses structurally.
    Two implementations that agree today and diverge after one change would
    give a plausible recovery figure with no authority able to say which was
    right.

    **Each transition's successor is rebuilt through the same D2 engine.**
    ``build_successor_contribution`` is called with that transition's own
    ``parent_expiration_period`` and ``branch``, the same suite, the same
    resolved assumptions and the same canonical months. D3.3 proved a
    successor's economics are a deterministic function of exactly those, so
    the rebuild is *the same object*, not an approximation -- which is why no
    commencement, term, market-pricing, free-rent, TI or LC formula is
    duplicated here. The identifier comes from the recursion's own
    ``successor_state_lease_id_stem`` and reaches no calculation.

    **Accumulation weights completed dollars only:**

    ```
    expected_successor_m = sum over transitions of  q_child x recovery_m
    ```

    where ``q_child`` is read from the transition. No lease type, basis, stop,
    share or responsibility factor is ever averaged.

    **Anti-double-counting.** Every accumulated series is successor-only and
    zero at or before its own parent's expiration, so a generation never
    re-counts its predecessor's months. The known in-place lease contributes
    **once**, unweighted, from ``rollover.initial_lease``.

    Recovery continues through the full ``12H + 12`` window, including the
    forward exit months: a later-generation successor recovering after the
    hold period is real revenue and is not truncated at a sale month. A child
    whose commencement lies beyond the horizon contributes zero rather than a
    fabricated month.

    **Precondition: the inputs are already validated.** Pure and
    deterministic: no I/O, no mutation, no sampling.
    """

    if rollover.months != pool.months:
        raise ValueError(
            "the recursive rollover and the recoverable expense pool were "
            "built against different month sequences; both must share one "
            "canonical timeline."
        )
    if rollover.suite_id != suite.suite_id:
        raise ValueError(
            f"the rollover describes suite {rollover.suite_id!r}, not "
            f"{suite.suite_id!r}; recovery must be priced for its own suite."
        )

    months = rollover.months
    count = len(months)
    schedule = resolve_rollover_market_schedule(
        suite,
        months=months,
        property_defaults=property_defaults,
        market_schedule=market_schedule,
    )

    known = _in_place_recovery(
        rollover.initial_lease,
        schedule=rollover.initial_schedule,
        pool=pool,
        rentable_area_sf=rentable_area_sf,
    )

    # One accumulator per canonical month. Contributions are added in the
    # authoritative transition order, so the sum is deterministic.
    expected_successor = [0.0] * count
    contributions: list[RecoveryContributionAudit] = []

    for transition in rollover.transitions:
        contribution = build_successor_contribution(
            suite=suite,
            analysis_start=analysis_start,
            months=months,
            market_schedule=schedule,
            parent_expiration_period=transition.parent_expiration_period,
            branch=transition.branch,
            lease_id_stem=successor_state_lease_id_stem(
                rollover.expiring_lease_id, transition.parent_expiration_period
            ),
        )
        recovery = _successor_recovery_from_contribution(
            contribution, pool=pool, rentable_area_sf=rentable_area_sf
        )

        mass = transition.probability_mass
        for index in range(count):
            expected_successor[index] += mass * recovery.expense_recovery[index]

        own_total = fsum(recovery.expense_recovery)
        contributions.append(
            RecoveryContributionAudit(
                parent_expiration_period=transition.parent_expiration_period,
                branch=transition.branch,
                probability_mass=mass,
                commencement_period=contribution.commencement_period,
                successor_expiration_period=(
                    contribution.successor_expiration_period
                ),
                commences_within_projection=(
                    contribution.commences_within_projection
                ),
                successor_lease_type=recovery.successor_lease_type,
                recovery_basis=recovery.recovery_basis,
                expense_stop_psf=recovery.expense_stop_psf,
                monthly_expense_stop_dollars=(
                    recovery.monthly_expense_stop_dollars
                ),
                in_window_expense_recovery=own_total,
                expected_expense_recovery_contribution=mass * own_total,
            )
        )

    expected_successor_series = tuple(
        ensure_finite("expected_successor_expense_recovery", value)
        for value in expected_successor
    )

    return RecursiveRolloverRecovery(
        suite_id=rollover.suite_id,
        expiring_lease_id=rollover.expiring_lease_id,
        renewal_probability=rollover.renewal_probability,
        months=months,
        rollover=rollover,
        in_place_recovery=known,
        in_place_expense_recovery=known.expense_recovery,
        expected_successor_expense_recovery=expected_successor_series,
        expected_expense_recovery=_combined_chain(
            known.expense_recovery, expected_successor_series
        ),
        contributions=tuple(contributions),
        # Mirrored from the authoritative result, never recomputed: D2.6
        # already proves mass conservation and a second algorithm could only
        # agree or manufacture a discrepancy.
        terminal_probability_mass=rollover.terminal_probability_mass,
    )
