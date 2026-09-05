"""Sprint D Gate D1.0 -- Lease-Level input contracts.

Restates
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Section 4 (Domain Contracts) exactly; that document governs on any
discrepancy. Like ``anchor.engine.contracts``, this module performs no
calculation and no I/O of its own -- it only describes the shape of a
Lease-Level deal's inputs.

D1.0 is deliberately vocabulary and invariants only. Nothing here computes a
month index, a monthly rent, an annual aggregate, a rollover, an NOI, or a
return; those belong to D1.1 (month identity), D1.2 (base-rent timeline),
D1.3 (property aggregation) and later phases.

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

    The D0 planning document names this field ``property_area_sf`` while
    defining it as "Total rentable area" (D0 Section 4.2). The name is
    renamed here to match that stated meaning: a field called
    "property area" invites a gross building area, which would silently
    corrupt every occupancy figure derived from it.

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
