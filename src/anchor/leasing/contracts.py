"""Sprint D Gates D1.0/D1.1 -- Lease-Level contracts.

Restates
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Section 4 (Domain Contracts) exactly; that document governs on any
discrepancy. Like ``anchor.engine.contracts``, this module performs no
calculation and no I/O of its own -- it only describes the shape of a
Lease-Level deal's inputs.

These are vocabulary and invariants only. Nothing here computes anything: a
monthly rent, an annual aggregate, a rollover, an NOI and a return all belong
to D1.2 (base-rent timeline), D1.3 (property aggregation) and later phases.
``ModelMonth`` (D1.1) describes one canonical month but is built solely by
``anchor.leasing.calendar.build_model_months``.

The three entities mirror the D0 entity decisions (Section 4.1):

- ``LeaseLevelPropertyInputs`` -- a small scalar record, not an entity graph.
- ``Suite`` -- a first-class entity. A suite persists across leases; it is
  what rolls over (D2), what sits vacant, and what will carry a market-rent
  override (D2).
- ``Lease`` -- a first-class entity, separate from ``Suite``. One suite has
  many leases over time.

There is deliberately **no** ``Tenant`` entity (Section 4.1): a tenant matters
financially only via credit and multi-suite rollup, neither of which is in
competition scope, and a merged Tenant/Lease entity could not represent the
speculative successor lease the D2 rollover engine creates with no known
tenant. ``Lease.tenant_name`` is nullable precisely for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class EscalationBasis(StrEnum):
    """When a lease's contractual escalation applies (D0 Section 6.2).

    ``LEASE_ANNIVERSARY`` means each 12-month anniversary of **rent
    commencement** -- never of the analysis start and never of the calendar
    year. Acquisition does not reset a lease's escalation clock, so an
    in-place lease acquired midway through its term stays on its correct
    contractual step.

    D1 supports exactly these two members. ``CALENDAR_YEAR`` and fixed
    ``$/SF`` bumps are documented D2+ additive extensions (D0 Section 6.6);
    neither is declared here, so neither can be constructed or silently
    assumed.
    """

    NONE = "none"
    LEASE_ANNIVERSARY = "lease_anniversary"


class LeaseType(StrEnum):
    """The lease's expense-recovery structure (D0 Section 16.1).

    **Captured in D1, economically inert until D3.** It is required in D1
    rather than deferred so the analyst confronts it once, with the document
    in hand, rather than having it inferred later (D0 Section 20).
    """

    NNN = "nnn"
    GROSS = "gross"
    MODIFIED_GROSS = "modified_gross"


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelMonth:
    """One canonical monthly period of the Lease-Level projection
    (D0 Section 4.7).

    Carries **both** identities so a monthly figure can be audited against a
    real calendar without re-deriving it from array position -- the guarantee
    guardrail G-M9 enforces and failure mode FM-4 exists to catch.

    ``period_index`` is the 1-based sequential model month: Month 1 is the
    calendar month containing ``analysis_start_date``. Zero-based financial
    period numbering is deliberately never exposed.

    ``month_start`` is the first calendar day of that month -- a plain
    ``date``, never a timestamp, never timezone-aware, never a display label.
    Presentation such as "Jan-27" belongs to the frontend.

    ``hold_year`` is derived from ``period_index``, never from the calendar
    year: ``((period_index - 1) // 12) + 1``. With an analysis start of
    2027-07-01, Hold Year 1 runs Jul-2027 through Jun-2028. The twelve forward
    exit months carry ``hold_year == H + 1``.

    ``is_forward_exit_month`` marks the twelve months ``12H+1 .. 12H+12`` that
    form the forward exit-NOI window (D0 Section 17.1), so that window can be
    identified without being recomputed anywhere else.

    Built only by ``anchor.leasing.calendar.build_model_months``; like every
    other contract in this module it performs no calculation of its own.
    """

    period_index: int
    month_start: date
    hold_year: int
    is_forward_exit_month: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseMonthlySchedule:
    """One lease's canonical monthly contractual base-rent series
    (D0 Section 4.7).

    ``months`` is the exact ``ModelMonth`` tuple the schedule was built
    against -- a reference to the one canonical timeline, never a second
    representation of it. Carrying it here is what makes every rent figure
    auditable to a real calendar month without the caller having to keep the
    two aligned by hand. ``contractual_base_rent[i]`` is the rent for
    ``months[i]``, and the two tuples always share a length.

    ``contractual_base_rent`` is **gross** contractual rent in dollars per
    month. In D1 nothing reduces it; from D2 it stays gross and free rent is
    reported as its own separate line, never netted into this one.

    ``first_rent_period`` / ``last_rent_period`` are the first and last
    canonical periods **within this schedule's window** in which the lease is
    contractually active, or ``None`` when the lease is active in no modeled
    month at all. They are defined by contractual activity, not by a non-zero
    figure: a zero-rent lease is active and reports real periods.

    Note the distinction from ``rent.lease_rent_periods``, which returns the
    lease's *raw, unclamped* periods -- possibly negative, possibly past the
    horizon. Those drive escalation; these describe the window.

    ``occupied_area`` (D1.3) is the square footage this lease occupies in each
    month: ``leased_area_sf`` while contractually active, ``0.0`` otherwise.
    It is **state**, not flow, so it is never summed across months. Crucially
    it is derived from contractual *activity*, never from rent dollars -- a
    zero-rent lease occupies its suite exactly like any other, which is why
    ``contractual_base_rent > 0`` must never be used as an occupancy test.

    The D2/D3 fields D0 lists on this contract -- ``free_rent``,
    ``expense_recoveries``, ``tenant_improvements``, ``leasing_commissions``,
    ``occupancy_factor`` -- are deliberately not declared yet, following the
    same rule applied to ``Lease``: a gate declares only what it can actually
    produce.

    Built only by ``anchor.leasing.rent.build_lease_monthly_schedule``; this
    dataclass performs no calculation of its own.
    """

    lease_id: str
    suite_id: str
    months: tuple[ModelMonth, ...]
    contractual_base_rent: tuple[float, ...]
    occupied_area: tuple[float, ...]
    first_rent_period: int | None
    last_rent_period: int | None

    def __post_init__(self) -> None:
        expected = len(self.months)
        for name, series in (
            ("contractual_base_rent", self.contractual_base_rent),
            ("occupied_area", self.occupied_area),
        ):
            if len(series) != expected:
                raise ValueError(
                    f"LeaseMonthlySchedule requires one {name} figure per "
                    f"model month; got {len(series)} for {expected} months."
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class PropertyRentRollSchedule:
    """The canonical monthly property rent roll (D0 Section 4.7) -- the D1
    deliverable.

    One row per canonical month, for the whole property. ``months`` is the
    same ``ModelMonth`` tuple every constituent ``LeaseMonthlySchedule`` was
    built against: one timeline, shared by reference, never rebuilt per lease.

    ``lease_schedules`` is retained deliberately. Property rent in March is
    auditable back to the individual leases that produced it -- monthly
    schedules are first-class outputs, not scratch work discarded after
    aggregation (guardrail G-M1).

    **Flow.** ``contractual_base_rent`` is the property's gross contractual
    base rent per month, the deterministic sum of the lease-level figures.
    Annual totals are derived from this series by
    ``anchor.leasing.aggregation.aggregate_flow_to_annual`` and by nothing
    else -- there is no independent annual rent formula anywhere.

    **State.** ``occupied_area``, ``vacant_area`` and ``physical_occupancy``
    are point-in-time values. They are never summed across months; their
    annual forms are an explicit year-end snapshot or an explicit average
    (D0 Section 5.7). ``occupied + vacant == rentable_area_sf`` holds in every
    month.

    Deliberately absent: NOI, recoveries, other income, operating expenses,
    market rent, rollover, TI, LC, free rent, debt, and every return metric.
    None exists in D1.

    Built only by
    ``anchor.leasing.aggregation.build_property_rent_roll_schedule``; this
    dataclass performs no calculation of its own.
    """

    months: tuple[ModelMonth, ...]
    lease_schedules: tuple[LeaseMonthlySchedule, ...]
    contractual_base_rent: tuple[float, ...]
    occupied_area: tuple[float, ...]
    vacant_area: tuple[float, ...]
    physical_occupancy: tuple[float, ...]

    def __post_init__(self) -> None:
        expected = len(self.months)
        for name, series in (
            ("contractual_base_rent", self.contractual_base_rent),
            ("occupied_area", self.occupied_area),
            ("vacant_area", self.vacant_area),
            ("physical_occupancy", self.physical_occupancy),
        ):
            if len(series) != expected:
                raise ValueError(
                    f"PropertyRentRollSchedule requires one {name} figure per "
                    f"model month; got {len(series)} for {expected} months."
                )
        for schedule in self.lease_schedules:
            if schedule.months != self.months:
                raise ValueError(
                    f"lease schedule {schedule.lease_id!r} was built against a "
                    "different month sequence; every schedule in a property "
                    "rent roll must share one canonical timeline."
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseLevelPropertyInputs:
    """The property-level scalars a Lease-Level deal needs (D0 Section 4.2).

    ``analysis_start_date`` is the single anchor for month identity (D1.1)
    and, later, for market-rent growth (D2). It must be the **first day of a
    calendar month**: it is the origin of every month index, and a mid-month
    origin would make every subsequent month a mid-month band, silently
    converting D1's whole-month recognition into an unstated proration
    convention. That requirement is enforced by
    ``anchor.leasing.validation``, not by this dataclass -- consistent with
    every other Anchor contract, which describes shape and leaves domain
    rules to its validator.

    ``rentable_area_sf`` is the **total rentable (leasable) area represented
    by this rent roll** -- the area that can be leased to a tenant and that
    every ``Suite`` collectively accounts for. It is the denominator for
    physical occupancy (D1.3) and for the D1.3 area invariant
    ``occupied + vacant == rentable_area_sf``.

    It is explicitly **not** gross building area, gross floor area, an
    arbitrary property square footage, or building area inclusive of
    non-rentable common area. Anchor requires that
    ``sum(suite_area_sf) == rentable_area_sf`` exactly (D1 implementation
    clarification, ``anchor.leasing.validation``): every rentable square foot
    must be accounted for by a suite, and vacant space is represented as a
    ``Suite`` with no lease -- never as area left outside the suite schedule.
    Common area is therefore never inferred from a residual, because there is
    no residual.

    Deliberately absent: ``property_name``, ``address``, ``property_type``,
    ``year_built``. Those are ``DealContext``
    (``anchor.ingestion.contracts``) -- informational, never engine inputs.

    Deliberately absent: ``hold_period``. The hold period lives on
    ``AcquisitionTerms`` and is passed as a parameter to the D1.1/D1.3
    schedule builders, exactly as ``build_detailed_operating_projection``
    already receives it. Duplicating it here would create a second place for
    the same assumption to disagree with itself.
    """

    analysis_start_date: date
    rentable_area_sf: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Suite:
    """One leasable space (D0 Section 4.3).

    ``suite_id`` is **financial**, not merely informational: it is the key
    binding a lease to the space that rolls over in D2, and the unit at which
    vacancy, downtime and occupancy are computed. A ``suite_id`` typo is a
    validation ERROR, not a cosmetic issue.

    ``suite_area_sf`` is this suite's **rentable (leasable) area**, in the
    same basis as ``LeaseLevelPropertyInputs.rentable_area_sf``, which the
    suites must sum to exactly. Deliberately out of scope for D1-D3: load
    factors, usable-versus-rentable area, common-area allocation, and
    partial-suite leasing. One suite is one leasable unit.

    A **vacant suite is a ``Suite`` with no lease covering a given month** --
    never a synthetic "vacant lease" row. A suite carrying no lease at all is
    valid in D1: it carries area, participates in rentable-area
    reconciliation, and contributes zero contractual base rent and its full
    area to vacancy. That is precisely how vacant space must be represented,
    rather than by omitting it from the rent roll.

    The D2 market-rent override fields (``market_rent_psf``,
    ``market_leasing_override``) are deliberately not declared at D1.0. They
    are additive at D2 and adding them now would put unused market-leasing
    vocabulary into a gate whose stated scope excludes it.
    """

    suite_id: str
    suite_area_sf: float
    suite_label: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Lease:
    """One contractual lease on one suite (D0 Section 4.4).

    **Dates.** ``rent_commencement_date`` is the first date base rent is
    owed and must be the first day of a calendar month.
    ``lease_expiration_date`` is the **inclusive** last date base rent is
    owed and must be the last day of a calendar month; the month containing
    it is fully paid. ``lease_start_date`` is the possession date --
    informational only, never entering any economic calculation, and
    therefore deliberately **not** month-alignment-validated (D0
    Section 5.5).

    **Rent.** ``base_rent_psf`` is annual base rent per square foot
    (``$/SF/year``) **as of ``rent_commencement_date``** -- the single D1
    rent convention (D0 Section 6.3). A rent roll stating a total annual rent
    is normalized at the analyst-approval boundary
    (``base_rent_psf = annual_rent / leased_area_sf``), never inside the
    engine, so there is exactly one rent representation and one code path.

    **Escalation.** ``escalation_pct`` is a fixed annual rate and
    ``escalation_basis`` says whether and from when it applies. Together with
    ``rent_commencement_date`` they carry everything D1.2 needs to compute
    escalation from the lease's **true contractual chronology**: the raw,
    unclamped commencement date is retained here, so an in-place lease
    commenced before ``analysis_start_date`` can be placed on its correct
    contractual step rather than restarted at step zero.

    **``leased_area_sf``** must equal the suite's ``suite_area_sf`` in D1-D3
    (D0 Section 4.4.1) -- one suite is one leasable unit, and a physically
    subdivided suite is modeled as two ``Suite`` rows. It is nonetheless kept
    as an explicit field because it is what a rent roll states and what rent
    and (later) TI are computed from; relaxing the equality later is then a
    validation change rather than a contract change.

    **Escalation coherence.** ``escalation_basis = NONE`` means the rent
    never steps, so ``escalation_pct`` must be exactly ``0.0``. A non-zero
    percentage paired with ``NONE`` is a validation ERROR rather than a
    silently ignored value: the two readings ("flat" versus "3% that someone
    forgot to switch on") differ materially, and Anchor does not guess which
    the analyst meant.

    **Deliberately not declared at D1.0**: ``free_rent_months`` and
    ``recovery_basis`` (D2/D3, like ``Suite``'s market-rent overrides), and
    ``origin``. D0 Section 4.4 marks ``origin`` as *derived* and phases it to
    **D2**; D1 has no mechanism for constructing successor economics, so a
    ``SUCCESSOR`` lease is a financially impossible state at this gate.
    Declaring the field now would make that impossible state representable
    purely for future convenience. D2 introduces it together with the
    rollover engine that can actually produce one.
    """

    lease_id: str
    suite_id: str
    leased_area_sf: float
    rent_commencement_date: date
    lease_expiration_date: date
    base_rent_psf: float
    escalation_pct: float
    escalation_basis: EscalationBasis
    lease_type: LeaseType
    tenant_name: str | None = None
    lease_start_date: date | None = None
