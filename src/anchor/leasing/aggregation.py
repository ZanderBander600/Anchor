"""Sprint D Gate D1.3 -- property rent-roll aggregation and annual derivation.

Restates
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 5.6, 5.7, 18.1 and 18.4 exactly; that document governs on any
discrepancy.

Two responsibilities, deliberately separate:

1. **Monthly property aggregation** -- combine the authoritative per-lease
   schedules into one canonical monthly property rent roll, and derive
   occupied and vacant rentable area from contractual activity.
2. **Annual derivation** -- reduce a canonical monthly series to annual
   figures, and nothing else. Annual values exist only as a view over
   monthly ones (guardrails G-M2, G-M3).

**This module performs no rent arithmetic.** It never reads
``Lease.base_rent_psf`` or ``Lease.escalation_pct``; it consumes finished
``LeaseMonthlySchedule`` values produced by ``rent.py``, which owns the single
contractual-rent formula. That separation is enforced by
``tests/test_leasing_architecture.py``, and it is what lets a future
rent-anchor date or explicit rent-step schedule change how a lease's monthly
values are derived without touching a line of property aggregation.

**D3.5 added property expense-recovery aggregation**, and it is a summation
layer only. Every structural decision -- lease type, expense stop, pro-rata
share, responsibility factor, renewal probability, recursion -- was made inside
each suite's own chain by D3.1-D3.4 and is final before it arrives here. This
module reprices nothing, applies no probability, consults no expense pool and
performs no gross-up.

Deliberately absent, all of it later work: credit loss, other income, operating
expenses, the management fee, EGI, NOI, CapEx, exit NOI, and every acquisition,
debt and return integration. Recovery is a **revenue** series and is never
netted against an expense here (D0 Section 10.2).
"""

from __future__ import annotations

from math import fsum
from typing import Iterable

from ..engine.contracts import ensure_finite
from .calendar import build_model_months, projection_month_count
from .contracts import (
    ExpectedRolloverRecovery,
    InitialVacancyRollover,
    InitialVacancyRolloverRecovery,
    Lease,
    LeaseLevelPropertyInputs,
    LeaseMonthlySchedule,
    LeaseRecoverySchedule,
    ModelMonth,
    PropertyOperatingSchedule,
    PropertyRecoverySchedule,
    PropertyRentRollSchedule,
    RecursiveRollover,
    RecursiveRolloverRecovery,
    Suite,
    SuiteOperatingProjection,
    SuiteRecoveryProjection,
)
from .rent import build_lease_monthly_schedule
from .validation import require_valid_lease_level_inputs


_MONTHS_PER_YEAR = 12


# =============================================================================
# Annual derivation
#
# Three functions, named for what they do, so a flow metric cannot be
# accidentally averaged and a state metric cannot be accidentally summed
# (D0 Section 5.7; failure modes FM-7 and FM-8). Every one of them takes a
# canonical MONTHLY series and nothing else -- there is no path by which an
# annual figure can be produced from raw lease assumptions.
# =============================================================================


def _hold_year_slice(monthly: tuple[float, ...], year: int) -> tuple[float, ...]:
    """Return the twelve monthly values belonging to 1-based hold ``year``.

    Hold year ``y`` spans canonical periods ``12(y-1)+1 .. 12y``, so its slice
    is positions ``12(y-1) .. 12y``. The year slices partition periods
    ``1 .. 12H`` exactly: no gap, no overlap (failure modes FM-2, FM-3).
    """

    start = (year - 1) * _MONTHS_PER_YEAR
    return monthly[start : start + _MONTHS_PER_YEAR]


def _require_full_projection(monthly: tuple[float, ...], hold_period: int) -> None:
    expected = projection_month_count(hold_period)
    if len(monthly) != expected:
        raise ValueError(
            f"a canonical monthly series for a {hold_period}-year hold must "
            f"have {expected} values; got {len(monthly)}."
        )


def aggregate_flow_to_annual(
    monthly: tuple[float, ...], *, hold_period: int
) -> tuple[float, ...]:
    """Sum a canonical monthly **flow** series into Hold Years 1..H.

    ```
    AnnualFlow_y = sum of MonthlyFlow_m for m in 12(y-1)+1 .. 12y
    ```

    Accumulated in strictly ascending period order. That ordering is a
    requirement, not a stylistic note: it mirrors
    ``calculate_annual_debt_service``'s explicit refusal of the ``12 * PMT``
    shortcut. Repeated IEEE-754 addition in a fixed order is reproducible,
    while the same values summed in a different order can differ in the last
    bits, and Anchor asserts golden cases at ``abs=1e-9``.

    Returns exactly ``hold_period`` values. The twelve forward exit months are
    **not** folded into a Year ``H+1`` entry here: D0's ``_by_year`` series are
    uniformly length ``H`` and the forward window is a separate scalar (the
    shape ``exit_noi`` takes at D4). Use
    ``aggregate_flow_over_forward_exit_window`` for it -- the months are never
    discarded, only reported separately.

    Only for flows -- rent, and later recoveries, expenses, NOI, TI, LC,
    CapEx. Summing a state metric such as occupied area is meaningless
    (FM-8); use one of the two functions below.
    """

    _require_full_projection(monthly, hold_period)

    annual: list[float] = []
    for year in range(1, hold_period + 1):
        total = 0.0
        for value in _hold_year_slice(monthly, year):
            total += value
        annual.append(total)
    return tuple(annual)


def aggregate_flow_over_forward_exit_window(
    monthly: tuple[float, ...], *, hold_period: int
) -> float:
    """Sum a canonical monthly flow over the forward exit window.

    Months ``12H+1 .. 12H+12`` -- the twelve months after the sale date, whose
    ``ModelMonth.hold_year`` is ``H + 1``. This is the same window and the same
    ascending summation D0 Section 17.1 defines for ``exit_noi`` at D4; only
    the metric differs.

    Returned as a scalar rather than appended to the annual series so that
    every ``_by_year`` tuple keeps its uniform length ``H``, and so a forward
    figure can never be mistaken for a hold-year one.
    """

    _require_full_projection(monthly, hold_period)

    total = 0.0
    for value in monthly[_MONTHS_PER_YEAR * hold_period :]:
        total += value
    return total


def snapshot_state_at_year_end(
    monthly: tuple[float, ...], *, hold_period: int
) -> tuple[float, ...]:
    """Take a canonical monthly **state** series at each hold year's final month.

    ``StateAtYearEnd_y = Monthly_(12y)``. Point-in-time, never summed.
    """

    _require_full_projection(monthly, hold_period)

    return tuple(
        monthly[year * _MONTHS_PER_YEAR - 1] for year in range(1, hold_period + 1)
    )


def average_state_over_year(
    monthly: tuple[float, ...], *, hold_period: int
) -> tuple[float, ...]:
    """Average a canonical monthly **state** series over each hold year.

    The arithmetic mean of the year's twelve values, summed in ascending
    period order and divided once. This is the economically meaningful annual
    form for occupancy -- average occupancy is what an analyst quotes -- and it
    is deliberately a different function, with a different name, from the
    flow sum, so the two can never be confused (FM-7, FM-8).
    """

    _require_full_projection(monthly, hold_period)

    averages: list[float] = []
    for year in range(1, hold_period + 1):
        total = 0.0
        for value in _hold_year_slice(monthly, year):
            total += value
        averages.append(total / _MONTHS_PER_YEAR)
    return tuple(averages)


# =============================================================================
# Monthly property aggregation
# =============================================================================


def build_property_rent_roll_schedule(
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    hold_period: int,
) -> PropertyRentRollSchedule:
    """Combine validated leases into one canonical monthly property rent roll.

    **Validates first, then calculates.** This is the public property entry
    point and it takes raw inputs, so it calls
    ``require_valid_lease_level_inputs`` and raises ``LeaseValidationError``
    on any error rather than silently aggregating a rent roll whose areas do
    not reconcile, whose same-suite leases overlap, or whose economic dates
    are not month-aligned. It adds no rule of its own -- there is exactly one
    leasing validation authority, and no second overlap algorithm here.

    Every lease's monthly values come from the authoritative
    ``build_lease_monthly_schedule`` (D1.2); this function contains no rent
    formula and never reads a rent assumption off a ``Lease``.

    **One timeline.** All lease schedules are built against the single
    ``ModelMonth`` tuple from ``build_model_months``, and
    ``PropertyRentRollSchedule`` rejects any schedule carrying a different
    sequence -- a mismatched horizon fails loudly rather than being silently
    zipped or truncated.

    **Deterministic order.** Leases are aggregated in their declared tuple
    order, months in ascending period order. No ``set`` or ``dict`` iteration
    contributes to any figure.

    **Occupancy is derived from contractual activity, never from dollars.**
    ``occupied_area`` sums the per-lease ``occupied_area`` series, each of
    which carries ``leased_area_sf`` exactly while its lease is contractually
    active. A zero-rent active lease therefore occupies its suite fully.
    Because validation forbids same-suite economic overlap, at most one lease
    per suite is active in any month, so this sum never double-counts.

    ``vacant_area = rentable_area_sf - occupied_area``, computed against the
    property's authoritative rentable area rather than by re-summing suites,
    which makes ``occupied + vacant == rentable_area_sf`` hold to within one
    unit in the last place. Vacancy arises exactly three ways -- a suite with
    no lease, a future lease not yet commenced, an expired lease -- and never
    from a vacancy percentage or a synthesized vacant lease, neither of which
    exists in Lease-Level.
    """

    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)

    require_valid_lease_level_inputs(
        property_inputs, suite_tuple, lease_tuple, hold_period=hold_period
    )

    months = build_model_months(
        analysis_start=property_inputs.analysis_start_date, hold_period=hold_period
    )

    lease_schedules: tuple[LeaseMonthlySchedule, ...] = tuple(
        build_lease_monthly_schedule(
            lease,
            analysis_start=property_inputs.analysis_start_date,
            months=months,
        )
        for lease in lease_tuple
    )

    rentable_area = property_inputs.rentable_area_sf

    contractual_base_rent: list[float] = []
    occupied_area: list[float] = []
    vacant_area: list[float] = []
    physical_occupancy: list[float] = []

    for position in range(len(months)):
        rent_total = 0.0
        occupied_total = 0.0
        for schedule in lease_schedules:
            rent_total += schedule.contractual_base_rent[position]
            occupied_total += schedule.occupied_area[position]

        contractual_base_rent.append(rent_total)
        occupied_area.append(occupied_total)
        vacant_area.append(rentable_area - occupied_total)
        # rentable_area_sf > 0 is guaranteed by validation, so this division
        # is always defined.
        physical_occupancy.append(occupied_total / rentable_area)

    return PropertyRentRollSchedule(
        months=months,
        lease_schedules=lease_schedules,
        contractual_base_rent=tuple(contractual_base_rent),
        occupied_area=tuple(occupied_area),
        vacant_area=tuple(vacant_area),
        physical_occupancy=tuple(physical_occupancy),
    )


# =============================================================================
# D3.5 -- property expense-recovery aggregation
#
# A summation layer. Every structural decision was made inside each suite's own
# chain by D3.1-D3.4 and is already final; nothing below reprices anything.
# =============================================================================


#: The authoritative D3 results a suite projection may be taken from. Each is a
#: *complete* canonical recovery series for one suite's lease chain; which one
#: applies is the caller's modelling decision, not a property-level rule.
_AUTHORITATIVE_RECOVERY_RESULTS = (
    "LeaseRecoverySchedule",
    "ExpectedRolloverRecovery",
    "RecursiveRolloverRecovery",
    "InitialVacancyRolloverRecovery",
)


def suite_recovery_projection(
    result: LeaseRecoverySchedule
    | ExpectedRolloverRecovery
    | RecursiveRolloverRecovery,
) -> SuiteRecoveryProjection:
    """Project an authoritative D3 result onto the aggregation boundary.

    **The single extraction seam**, so property aggregation has one input shape
    rather than one formula per result type. It **copies** an
    already-calculated dollar series and computes nothing:

    - `LeaseRecoverySchedule` (D3.1/D3.2) -- a known lease with no modelled
      rollover, ``expense_recovery``;
    - `ExpectedRolloverRecovery` (D3.4) -- one modelled rollover, the full
      chain ``expected_expense_recovery``;
    - `RecursiveRolloverRecovery` (D3.4) -- every successor generation, again
      the full chain ``expected_expense_recovery``;
    - `InitialVacancyRolloverRecovery` (D3.6) -- a suite that began **vacant**,
      whether it was underwritten as `MARKET_LEASE_UP` (its full chain from
      lease-up onward) or `HOLD_VACANT` (an explicit all-zero series). A
      hold-vacant suite therefore appears in the aggregation like any other,
      so deliberate vacancy stays visible rather than looking like a suite
      nobody underwrote.

    Both D3.4 results expose the **full chain**: the known lease's own
    recoveries plus its successors', which the contracts prove disjoint. Taking
    the successor-only series here would silently drop every month before the
    first expiration.
    """

    if isinstance(result, LeaseRecoverySchedule):
        return SuiteRecoveryProjection(
            suite_id=result.suite_id,
            months=result.months,
            expense_recovery=result.expense_recovery,
        )
    if isinstance(
        result,
        ExpectedRolloverRecovery
        | RecursiveRolloverRecovery
        | InitialVacancyRolloverRecovery,
    ):
        return SuiteRecoveryProjection(
            suite_id=result.suite_id,
            months=result.months,
            expense_recovery=result.expected_expense_recovery,
        )
    raise TypeError(
        f"{type(result).__name__} is not an authoritative D3 recovery result; "
        f"expected one of {', '.join(_AUTHORITATIVE_RECOVERY_RESULTS)}."
    )


def build_property_recovery_schedule(
    projections: Iterable[SuiteRecoveryProjection],
    *,
    months: tuple[ModelMonth, ...],
    rentable_area_sf: float,
    hold_period: int,
    suites: Iterable[Suite] | None = None,
    leases: Iterable[Lease] | None = None,
) -> PropertyRecoverySchedule:
    """Combine suite recovery projections into one canonical property schedule.

    ```
    PropertyRecovery_m = sum over included suites of SuiteRecovery_m
    ```

    **Validates first, then sums**, following the D1.3 property entry point.
    ``require_valid_property_recovery_inputs`` is the single authority for
    duplicate suites, unknown suites, missing schedules and month alignment;
    this function adds no rule of its own.

    **It contains no recovery formula.** No lease type is read, no expense stop
    applied, no responsibility factor derived, no probability weighted and no
    pool consulted. Each suite's dollars are final before they arrive.

    **Order-independent.** Projections are sorted by ``suite_id`` and each
    month is accumulated with ``math.fsum``, so two callers passing the same
    suites in different orders get **identical** figures rather than merely
    close ones.

    **No gross-up.** A Gross tenant's share, a Modified Gross tenant's
    below-stop amount and a vacant suite's share are simply not recovered, and
    are never redistributed onto the tenants who do pay (HD-D3-6, deferred).

    ``suites`` and ``leases`` are optional and enable completeness checking: a
    suite that has a lease should have a projection, and a projection for a
    suite the property does not contain is an error. A suite with **no** lease
    correctly has no projection -- it recovers zero, and Anchor never
    synthesizes a schedule for vacant space.

    Annual figures derive solely from the monthly series through
    ``aggregate_flow_to_annual``, with the forward exit window reported
    separately by ``aggregate_flow_over_forward_exit_window`` -- the same
    chronology D1 uses, and the same refusal to discard those months.

    Pure and deterministic: no I/O, no mutation.
    """

    from .validation import require_valid_property_recovery_inputs

    projection_tuple = tuple(projections)
    require_valid_property_recovery_inputs(
        projection_tuple,
        months=months,
        suites=None if suites is None else tuple(suites),
        leases=None if leases is None else tuple(leases),
    )

    # Deterministic order, so the accumulation cannot depend on the caller.
    ordered = sorted(projection_tuple, key=lambda p: p.suite_id)

    monthly = tuple(
        ensure_finite(
            "property expense_recovery",
            fsum(projection.expense_recovery[index] for projection in ordered),
        )
        for index in range(len(months))
    )

    return PropertyRecoverySchedule(
        months=months,
        rentable_area_sf=rentable_area_sf,
        hold_period=hold_period,
        suite_projections=tuple(ordered),
        expense_recovery=monthly,
        annual_expense_recovery=aggregate_flow_to_annual(
            monthly, hold_period=hold_period
        ),
        forward_exit_window_expense_recovery=(
            aggregate_flow_over_forward_exit_window(monthly, hold_period=hold_period)
        ),
    )


# =============================================================================
# D4.2 -- property leasing aggregation
#
# The same shape as D3.5 above, one layer over: a single extraction seam onto a
# neutral per-suite contract, then one deterministic property summation. Every
# structural and economic decision -- rent, escalation, market rent, downtime,
# free rent, TI, LC, renewal probability, recursion, initial vacancy -- was
# made inside each suite's own chain by D1-D3 and is final before it arrives
# here. This layer reprices nothing.
# =============================================================================


#: The authoritative **full-chain** leasing results a suite projection may be
#: taken from. Each describes one suite over the whole canonical window: an
#: occupied suite's own lease plus every expected successor generation, or an
#: initially vacant suite's vacancy months plus its first speculative tenant
#: plus every later generation.
#:
#: ``ExpectedRollover`` is deliberately **not** here even though it carries the
#: same field names. It is the first rollover only, so taking it would silently
#: drop every generation after the first -- and D2.6 proves recursion
#: reproduces it exactly when there is no second rollover, so nothing is lost
#: by requiring the complete result (D4 Section 2.10). A branch, a successor
#: contribution and a pure renewal or new-tenant series are excluded for the
#: same reason, one step more strongly: none of them is even a whole suite.
_AUTHORITATIVE_OPERATING_RESULTS = (
    "RecursiveRollover",
    "InitialVacancyRollover",
)


def suite_operating_projection(
    suite: Suite,
    result: RecursiveRollover | InitialVacancyRollover,
) -> SuiteOperatingProjection:
    """Project an authoritative full-chain leasing result onto the property
    boundary.

    **The single extraction seam** (D4 Section 29.1), so property aggregation
    has one input shape rather than one code path per suite kind. It **copies**
    already-calculated series and computes nothing: no rent, no escalation, no
    market rent, no downtime, no free-rent waterfall, no TI, no LC, no
    probability weighting, no recursion, no lease-up timing. Every one of those
    has exactly one owner further up, and each is final before it arrives.

    Exactly two sources, and both are complete chains:

    - `RecursiveRollover` (D2.6) -- an **occupied** suite: the known in-place
      lease's own economics, seeded once and unweighted, plus every expected
      successor generation through the end of the canonical window.
    - `InitialVacancyRollover` (D3.6) -- a suite **vacant at the analysis
      start**. Under `MARKET_LEASE_UP` that is the vacancy months as zeros,
      then the deterministic first speculative tenant, then every later
      generation; under `HOLD_VACANT` it is an explicit all-zero chain. A
      hold-vacant suite therefore appears in the property aggregation like any
      other, which is what keeps deliberate vacancy visible instead of looking
      like a suite nobody underwrote (D3.6).

    Both expose the ``expected_*`` series, and both are the **full** chain, so
    one mapping serves both and no strategy branch exists here at all.

    ``suite`` supplies the authoritative ``suite_area_sf`` -- the denominator
    every occupancy figure is ultimately measured against -- and is checked to
    be the suite the result actually describes, so a projection cannot pair one
    suite's economics with another's area.

    **Occupied area is carried, not derived.** ``expected_occupied_area_sf`` is
    D2/D3's authoritative physical output. It is never recomputed from rent,
    from ``expected_cash_rent_factor``, or from
    ``expected_successor_occupancy_factor`` -- that last is a month-equivalent
    *economic exposure* fraction, a different quantity under a different name,
    and publishing it as physical occupancy is failure mode FM-D2-19. In a
    fractional commencement month the tenant is in possession by month end, so
    the suite's physical area is fully occupied while its economic
    responsibility is a fraction.

    **Cash base rent is carried, not reconstructed.** It is copied straight
    from the chain, never rebuilt as ``contractual - free_rent``: in a
    fractional-downtime month those differ by the portion of the month during
    which nobody was in possession, and rebuilding it would recognise that
    portion as collected revenue (HD-D4-5, D4 Section 5.4).
    """

    if not isinstance(result, RecursiveRollover | InitialVacancyRollover):
        raise TypeError(
            f"{type(result).__name__} is not an authoritative full-chain "
            f"leasing result; expected one of "
            f"{', '.join(_AUTHORITATIVE_OPERATING_RESULTS)}. A branch, a "
            "successor contribution, a first-rollover-only result or a pure "
            "renewal or new-tenant series is not a whole suite."
        )

    if suite.suite_id != result.suite_id:
        raise ValueError(
            f"suite {suite.suite_id!r} was paired with a leasing result for "
            f"suite {result.suite_id!r}; a projection carries one suite's "
            "economics and that same suite's area."
        )

    return SuiteOperatingProjection(
        suite_id=result.suite_id,
        suite_area_sf=suite.suite_area_sf,
        months=result.months,
        contractual_base_rent=result.expected_contractual_base_rent,
        cash_base_rent=result.expected_cash_base_rent,
        free_rent=result.expected_free_rent,
        tenant_improvements=result.expected_tenant_improvements,
        leasing_commissions=result.expected_leasing_commissions,
        occupied_area_sf=result.expected_occupied_area_sf,
    )


#: The five monthly dollar series and the one monthly area series the property
#: aggregation sums, named once so a single loop produces all six from one
#: deterministic suite ordering. Splitting them across helpers is how suite
#: ordering and completeness rules come to differ between two figures that are
#: supposed to describe the same property.
_PROPERTY_OPERATING_SERIES = (
    "contractual_base_rent",
    "cash_base_rent",
    "free_rent",
    "tenant_improvements",
    "leasing_commissions",
    "occupied_area_sf",
)


def build_property_operating_schedule(
    projections: Iterable[SuiteOperatingProjection],
    suites: Iterable[Suite],
    *,
    months: tuple[ModelMonth, ...],
    rentable_area_sf: float,
    leases: Iterable[Lease] | None = None,
) -> PropertyOperatingSchedule:
    """Combine suite operating projections into one canonical property schedule.

    ```
    PropertySeries_m = sum over every suite of SuiteSeries_m
    ```

    for each of the five dollar series and the occupied-area series, then

    ```
    vacant_area_sf_m     = rentable_area_sf - occupied_area_sf_m
    physical_occupancy_m = occupied_area_sf_m / rentable_area_sf
    ```

    **Validates first, then sums**, following the D1.3 and D3.5 property entry
    points. ``require_valid_property_operating_inputs`` is the single authority
    for month alignment, duplicate suites, unknown suites, area mismatch and
    completeness; this function adds no rule of its own.

    **Every suite appears exactly once.** ``suites`` is required, not optional:
    at D4.2 there is no such thing as a suite with no leasing economics, so
    "this one may be omitted" is not a case. An occupied suite brings its
    chain, a `MARKET_LEASE_UP` suite its lease-up chain, and a `HOLD_VACANT`
    suite an explicit all-zero chain -- and that zero must be *present*, which
    is what keeps deliberate vacancy distinguishable from an omission (D3.6).

    **It contains no leasing formula.** No lease, no market rent, no
    escalation, no downtime, no free-rent assumption, no TI or LC rate and no
    renewal probability is read here. There is no property-level probability,
    no property-level threshold and no property-average anything: two occupied
    suites underwritten at different renewal probabilities simply contribute
    their own finished expected dollars.

    **Order-independent.** Projections are sorted by ``suite_id`` and each
    month is accumulated with ``math.fsum``, so callers passing the same suites
    in different orders get **identical** figures rather than merely close
    ones -- the same policy D3.5 established for recoveries.

    **Occupancy is computed once, from areas.** ``occupied_area_sf`` is summed
    -- areas add -- and divided by the property's authoritative
    ``rentable_area_sf`` a single time. Suite-level occupancy *ratios* are
    never averaged, and ``SuiteOperatingProjection`` deliberately declares
    none: a 90,000 SF suite fully let beside an empty 10,000 SF suite is 90%
    occupied, not 50%, and the mistake is unavailable rather than merely
    discouraged (D4 Section 16.1).

    ``physical_occupancy`` may be fractional for a probability-weighted chain.
    That is an *expected* physical occupancy over branch states whose own
    occupancy is integral (D2 HD-D2-2), and it is a different quantity from
    ``expected_successor_occupancy_factor``, which is never read here.

    **The whole canonical window is retained**, hold months and the twelve
    forward exit months alike. Rent, free rent, TI, LC and occupancy stay live
    past month ``12H`` because those are real leasing events; which of them is
    a seller cash flow is D4.4/D4.5's question, and answering it here would
    destroy the audit trail those gates need (D4 Section 21.3).

    **No annual figure is produced.** There is no ``hold_period`` parameter and
    no ``_by_year`` field: monthly is canonical, and the annual adapter is
    D4.4's.

    Pure and deterministic: no I/O, no mutation, no ``set`` or ``dict``
    iteration contributing to any figure.
    """

    from .validation import require_valid_property_operating_inputs

    projection_tuple = tuple(projections)
    suite_tuple = tuple(suites)

    require_valid_property_operating_inputs(
        projection_tuple,
        suite_tuple,
        months=months,
        leases=None if leases is None else tuple(leases),
    )

    # Deterministic order, so the accumulation cannot depend on the caller.
    ordered = sorted(projection_tuple, key=lambda projection: projection.suite_id)

    summed: dict[str, tuple[float, ...]] = {
        name: tuple(
            ensure_finite(
                f"property {name}",
                fsum(getattr(projection, name)[index] for projection in ordered),
            )
            for index in range(len(months))
        )
        for name in _PROPERTY_OPERATING_SERIES
    }

    occupied_area_sf = summed["occupied_area_sf"]
    # rentable_area_sf > 0 is guaranteed by D1 validation, so this division is
    # always defined. Computed once, from areas, at the property level.
    vacant_area_sf = tuple(
        ensure_finite("property vacant_area_sf", rentable_area_sf - occupied)
        for occupied in occupied_area_sf
    )
    physical_occupancy = tuple(
        ensure_finite("property physical_occupancy", occupied / rentable_area_sf)
        for occupied in occupied_area_sf
    )

    return PropertyOperatingSchedule(
        months=months,
        rentable_area_sf=rentable_area_sf,
        suite_projections=tuple(ordered),
        contractual_base_rent=summed["contractual_base_rent"],
        cash_base_rent=summed["cash_base_rent"],
        free_rent=summed["free_rent"],
        tenant_improvements=summed["tenant_improvements"],
        leasing_commissions=summed["leasing_commissions"],
        occupied_area_sf=occupied_area_sf,
        vacant_area_sf=vacant_area_sf,
        physical_occupancy=physical_occupancy,
    )
