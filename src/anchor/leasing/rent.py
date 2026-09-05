"""Sprint D Gate D1.2 -- the contractual base-rent monthly timeline.

Restates
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 6.1 and 6.2 exactly; that document governs on any discrepancy.

**This is the only module in ``anchor.leasing`` permitted to perform rent
arithmetic.** ``calendar.py`` computes time, ``validation.py`` checks inputs,
``contracts.py`` describes shape; none of them may touch ``base_rent_psf`` or
``escalation_pct`` in an arithmetic expression. That boundary is enforced by
``tests/test_leasing_architecture.py``, which exempts this module by name.

Scope is deliberately one lease. Property aggregation, occupied and vacant
area, annual totals, rollover, free rent, TI, LC, recoveries and NOI all
belong to D1.3 and later gates. Nothing here sums two leases.
"""

from __future__ import annotations

from datetime import date

from ..engine.contracts import ensure_finite
from .calendar import month_index
from .contracts import EscalationBasis, Lease, LeaseMonthlySchedule, ModelMonth


_MONTHS_PER_YEAR = 12


def lease_rent_periods(lease: Lease, *, analysis_start: date) -> tuple[int, int]:
    """Return the lease's ``(first, last)`` rent periods -- **raw, unclamped**.

    Both are canonical model month indices. Either may be zero or negative
    (an in-place lease that commenced before acquisition) or may exceed the
    projection horizon (a lease running past it). **Neither is ever clamped**:
    the raw first period is what places an in-place lease on its correct
    contractual escalation step, and clamping it to Month 1 is exactly
    failure mode FM-5.

    ``lease_expiration_date`` is inclusive and month-aligned, so the month
    containing it is a paying month.

    ``lease_start_date`` (possession) is deliberately not consulted: it is
    informational and never enters an economic calculation.
    """

    first = month_index(lease.rent_commencement_date, analysis_start=analysis_start)
    last = month_index(lease.lease_expiration_date, analysis_start=analysis_start)
    return first, last


def escalation_period_index(
    *, period: int, raw_first_rent_period: int, basis: EscalationBasis
) -> int:
    """Return ``k``, the number of completed contract years at ``period``.

    ```
    basis = NONE               ->  k = 0 for every month
    basis = LEASE_ANNIVERSARY  ->  k = floor((period - raw_first_rent_period) / 12)
    ```

    The parameter is named ``raw_first_rent_period`` rather than
    ``first_rent_period`` so a caller cannot pass a window-clamped value
    without noticing. That single naming choice is what makes the FM-5 trap
    hard to fall into: acquisition must never reset a lease's escalation
    clock.

    Counted from **rent commencement**, never from the analysis start and
    never from the calendar year. A lease commencing 2025-04-01 escalates
    every April, whatever month the deal is acquired in.
    """

    if basis is EscalationBasis.NONE:
        return 0

    # Floor division, and `period >= raw_first_rent_period` for every active
    # month, so this is a non-negative count of completed contract years.
    return (period - raw_first_rent_period) // _MONTHS_PER_YEAR


def monthly_base_rent(
    *,
    base_rent_psf: float,
    leased_area_sf: float,
    escalation_pct: float,
    escalation_index: int,
) -> float:
    """Return one month's contractual base rent, in dollars.

    ```
    AnnualRentPSF        = base_rent_psf * (1 + escalation_pct) ** escalation_index
    ContractualBaseRent  = AnnualRentPSF * leased_area_sf / 12.0
    ```

    ``base_rent_psf`` is **$/SF/year**, so the division by 12 happens **once,
    last** -- never by converting to a monthly PSF first. The operation order
    is fixed and identical on every branch, so the same inputs always produce
    the same bits (D0 Section 6.1). No rounding, no quantization, no
    ``Decimal``: presentation formatting belongs to the display layer.

    ``escalation_index`` is the completed-contract-year count ``k`` from
    ``escalation_period_index`` -- **not** a model month index. D0's function
    sketch calls this parameter ``period_index``, but that name already means
    the 1-based canonical month everywhere else in this package, and reusing
    it here would invite precisely the FM-5 confusion the previous function
    exists to prevent. The arithmetic is unchanged; only the local parameter
    name differs from the sketch.

    Wrapped in ``ensure_finite``, so an escalation that overflows to infinity
    fails loudly rather than propagating a silent ``inf`` into a schedule --
    the same non-finite convention every existing Anchor calculator uses.
    """

    annual_rent_psf = base_rent_psf * (1 + escalation_pct) ** escalation_index
    return ensure_finite(
        "monthly_base_rent", annual_rent_psf * leased_area_sf / 12.0
    )


def build_lease_monthly_schedule(
    lease: Lease,
    *,
    analysis_start: date,
    months: tuple[ModelMonth, ...],
) -> LeaseMonthlySchedule:
    """Return one lease's exact contractual base rent for every canonical month.

    **Precondition: ``lease`` is already validated.** This follows Anchor's
    established engine boundary -- ``analyze_acquisition`` and
    ``build_detailed_operating_projection`` likewise consume
    already-validated contracts and perform no validation of their own. Call
    ``anchor.leasing.validation.require_valid_lease_level_inputs`` first;
    re-validating here would create a second validation authority whose
    behavior could drift from the first.

    A month is **active** when it lies within the lease's inclusive economic
    rent interval -- ``first_rent_period <= period_index <= last_rent_period``
    on the raw, unclamped periods. Active months carry contractual rent;
    every other month is exactly ``0.0``.

    That zero means only "contractual rent has not commenced" or "the
    contractual term has ended". It is **not** vacancy, downtime, or free
    rent, none of which exist in D1. Expiration stops rent: nothing here
    carries rent forward, infers a renewal or a month-to-month tenancy, reads
    a market rent, or creates a successor.

    A zero-rent lease is a real, valid lease -- its months are active and its
    rent is exactly ``0.0``. Zero rent is never reinterpreted as vacancy.

    The schedule spans exactly the ``months`` supplied and never invents a
    period beyond them, so a lease running past the projection horizon is
    simply computed only where the horizon reaches. The ``Lease`` itself is
    never truncated or mutated; nothing in this function mutates anything.
    """

    raw_first, raw_last = lease_rent_periods(lease, analysis_start=analysis_start)

    contractual_base_rent: list[float] = []
    active_periods: list[int] = []

    for month in months:
        period = month.period_index
        if not (raw_first <= period <= raw_last):
            contractual_base_rent.append(0.0)
            continue

        active_periods.append(period)
        contractual_base_rent.append(
            monthly_base_rent(
                base_rent_psf=lease.base_rent_psf,
                leased_area_sf=lease.leased_area_sf,
                escalation_pct=lease.escalation_pct,
                escalation_index=escalation_period_index(
                    period=period,
                    raw_first_rent_period=raw_first,
                    basis=lease.escalation_basis,
                ),
            )
        )

    return LeaseMonthlySchedule(
        lease_id=lease.lease_id,
        suite_id=lease.suite_id,
        months=months,
        first_rent_period=active_periods[0] if active_periods else None,
        last_rent_period=active_periods[-1] if active_periods else None,
        contractual_base_rent=tuple(contractual_base_rent),
    )
