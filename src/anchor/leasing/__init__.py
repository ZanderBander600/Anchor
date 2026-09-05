"""Anchor Lease-Level underwriting -- contractual lease domain.

Sprint D, Gate D1.0. Governed by
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``,
which is authoritative on any discrepancy.

Lease-Level is Anchor's third operating producer, alongside Quick
(``anchor.engine.noi``) and Detailed
(``anchor.engine.operating_projection``). It derives property operating
economics from individual suites and leases rather than from a single NOI
figure or a property-level revenue build.

**This package is deliberately isolated.** It imports nothing from
``anchor.engine.acquisition``, ``anchor.engine.debt``, ``anchor.engine.noi``,
``anchor.engine.returns``, ``anchor.engine.operating_projection``,
``anchor.ai``, ``anchor.deals``, ``anchor.ingestion``, or ``anchor.analysis``,
and nothing outside it imports this package yet. The connection into the
downstream acquisition/debt/returns engine is made at D4, in that direction
only. The boundary is enforced by ``tests/test_leasing_architecture.py``.

**What exists at D1.0: vocabulary and invariants.** This gate establishes
what a contractual lease *is* and when one is valid. It computes nothing --
no month index, no monthly rent, no annual aggregate, no NOI, no return. A
reader should be able to answer "what is a valid contractual lease in Anchor"
from this package without encountering a single rent calculation.

D1.1 adds the canonical monthly calendar: ``ModelMonth`` plus
``build_model_months``, which together give one trusted, auditable
representation of every modeled lease month -- sequential index, real calendar
month, hold year, and the twelve forward exit-NOI months, in a single
projection. Still no rent: calendar arithmetic is in scope, financial
arithmetic is not.

D1.2 adds the contractual base-rent monthly timeline: for one validated
lease, the exact dollar rent in every canonical month, on the lease's true
contractual chronology. ``rent.py`` is the only module permitted to perform
rent arithmetic.

D1.3 adds the property rent-roll schedule -- many leases across many suites
combined into one canonical monthly series, with occupied and vacant rentable
area derived from contractual activity -- and the annual aggregation derived
solely from those monthly values. There is no independent annual rent engine.

D2.1 adds the canonical monthly market-rent schedule: for each suite, the
market rent in ``$/SF/year`` in every canonical month, growing in annual steps
on ``analysis_start_date`` anniversaries, with the property-default /
suite-override precedence resolved once per suite. ``market.py`` is the only
module permitted to perform market-rent arithmetic, exactly as ``rent.py`` is
the only one permitted to perform contractual-rent arithmetic; neither reads
the other's fields. Market rent is an assumption **rate** about available
space -- it is not a successor lease, and nothing at D2.1 converts it into a
dollar cash flow. Rollover, renewal, downtime, free rent, TI, LC and
probability composition are D2.2 and later.

D2.2 adds the pure renewal rollover path: an expiring lease produces exactly
one renewal successor commencing the month after expiry, priced from the
canonical market-rent schedule at that month by D0 Section 24.3, with its own
integer term and its own contractual escalation running from its own
commencement. ``rollover.py`` owns the renewal branch but owns no rent
formula: market rent comes from ``market.py`` and contractual rent from
``rent.py``, because a successor is an ordinary contractual lease from the
moment it commences. This is conceptually the ``p = 1`` endpoint, but no
probability exists yet -- the new-tenant branch, downtime and free rent are
D2.3, TI and LC are D2.4, ``renewal_probability`` and expected-value
composition are D2.5, and recursion is D2.6.

D2.3 adds the pure new-tenant branch and the concession mechanics both
branches share. Downtime sets the successor's month-equivalent occupancy
factor -- ``floor(D)`` fully vacant periods, then ``1 - frac(D)`` at
commencement -- and free rent is then consumed against that occupancy by a
sequential waterfall, never as an independent multiplicative factor. Face rent
and cash rent are kept as separate series: neither concession reduces
contractual face rent, which D2.4's LC basis reads. Branch physical occupancy
stays integral and keeps that name; the fractional
``successor_occupancy_factor`` is a different quantity under a different name.
The renewal branch gains the same mechanics, and at zero downtime and zero free
rent reproduces the accepted D2.2 result exactly.

D2.4 adds each branch's tenant improvements and leasing commissions, both
strictly below NOI and neither touching a rent or occupancy series. TI is
``ti_psf x leased_area_sf``, recorded in full in the first canonical month with
``successor_occupancy_factor > 0``. LC is ``lc_pct`` times the successor's
**full-term** contractual face rent -- including escalations, gross of free
rent, untruncated by the projection horizon and unreduced by a fractional first
month -- recorded in the same month. That basis comes from
``rent.contractual_face_rent_over_full_term``, which reaches the one D1
monthly-rent formula, so no second escalation formula and no closed-form
shortcut exists anywhere.

D2.5 composes the two complete branches into their expected economics:
``Expected[m] = p * Renewal[m] + (1 - p) * NewTenant[m]``, applied **last**, to
finished monthly outcomes. No input parameter is ever weighted, no synthetic
successor lease exists, and no timing is averaged -- where the branches place a
cost in different months, both weighted events stand at their own real months.
Every expected dollar series is weighted from the corresponding branch dollar
series directly, never reconstructed from expected factors, because
``E[X * Y] != E[X] * E[Y]`` for branch-correlated quantities. Branch
``physical_occupancy`` stays integral; the composed fractional series is
``expected_occupancy`` / ``expected_occupied_area_sf``. Recursion is D2.6, and
the downstream below-NOI channel is D4.
"""

from __future__ import annotations

from .aggregation import (
    aggregate_flow_over_forward_exit_window,
    aggregate_flow_to_annual,
    average_state_over_year,
    build_property_rent_roll_schedule,
    snapshot_state_at_year_end,
)
from .calendar import (
    build_model_months,
    is_first_day_of_month,
    is_last_day_of_month,
    last_day_of_month,
    month_index,
    month_start_for_index,
    projection_month_count,
)
from .contracts import (
    EscalationBasis,
    ExpectedRollover,
    Lease,
    LeaseLevelPropertyInputs,
    LeaseMonthlySchedule,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketAssumptionSource,
    MarketLeasingAssumptions,
    MarketRentSchedule,
    ModelMonth,
    NewTenantBranch,
    PropertyRentRollSchedule,
    RenewalBranch,
    ResolvedMarketLeasing,
    Suite,
)
from .market import (
    build_market_rent_schedule,
    build_property_market_rent_schedules,
    market_growth_index,
    market_rent_psf_at_period,
    market_rent_psf_for_period,
    resolve_market_leasing,
)
from .leasing_costs import (
    leasing_commission_amount,
    leasing_cost_event_period,
    leasing_cost_event_series,
    tenant_improvement_amount,
)
from .rent import (
    build_lease_monthly_schedule,
    contractual_face_rent_over_full_term,
    lease_contractual_term_months,
)
from .rollover import (
    build_expected_rollover,
    build_new_tenant_branch,
    compose_expected_rollover,
    build_renewal_branch,
    build_renewal_successor_lease,
    build_successor_lease,
    free_rent_waterfall,
    maximum_consumable_free_rent_months,
    new_tenant_starting_rent_psf,
    renewal_commencement_period,
    renewal_starting_rent_psf,
    successor_commencement_period,
    successor_expiration_period,
    successor_occupancy_factors,
    weighted_outcome,
)
from .validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
    LeaseValidationIssue,
    LeaseValidationResult,
    require_valid_lease_level_inputs,
    validate_lease_level_inputs,
)

__all__ = [
    # calendar (D1.1)
    "ModelMonth",
    "build_model_months",
    "projection_month_count",
    "month_index",
    "month_start_for_index",
    "is_first_day_of_month",
    "is_last_day_of_month",
    "last_day_of_month",
    # rent (D1.2)
    "LeaseMonthlySchedule",
    "build_lease_monthly_schedule",
    # property aggregation (D1.3)
    "PropertyRentRollSchedule",
    "build_property_rent_roll_schedule",
    "aggregate_flow_to_annual",
    "aggregate_flow_over_forward_exit_window",
    "snapshot_state_at_year_end",
    "average_state_over_year",
    # market rent (D2.1)
    "MarketLeasingAssumptions",
    "MarketAssumptionSource",
    "ResolvedMarketLeasing",
    "MarketRentSchedule",
    "resolve_market_leasing",
    "market_growth_index",
    "market_rent_psf_for_period",
    "build_market_rent_schedule",
    "build_property_market_rent_schedules",
    "market_rent_psf_at_period",
    # renewal rollover (D2.2)
    "LeaseOrigin",
    "RenewalBranch",
    "renewal_commencement_period",
    "successor_expiration_period",
    "renewal_starting_rent_psf",
    "build_renewal_successor_lease",
    "build_renewal_branch",
    # new-tenant branch, downtime and free rent (D2.3)
    "NewTenantBranch",
    "build_new_tenant_branch",
    "build_successor_lease",
    "new_tenant_starting_rent_psf",
    "successor_commencement_period",
    "successor_occupancy_factors",
    "free_rent_waterfall",
    "maximum_consumable_free_rent_months",
    # leasing costs (D2.4)
    "LeasingCommissionMethod",
    "tenant_improvement_amount",
    "leasing_commission_amount",
    "leasing_cost_event_period",
    "leasing_cost_event_series",
    "contractual_face_rent_over_full_term",
    "lease_contractual_term_months",
    # expected-value composition (D2.5)
    "ExpectedRollover",
    "weighted_outcome",
    "compose_expected_rollover",
    "build_expected_rollover",
    # contracts
    "EscalationBasis",
    "Lease",
    "LeaseLevelPropertyInputs",
    "LeaseType",
    "Suite",
    # validation
    "LeaseIssueCode",
    "LeaseIssueSeverity",
    "LeaseValidationError",
    "LeaseValidationIssue",
    "LeaseValidationResult",
    "require_valid_lease_level_inputs",
    "validate_lease_level_inputs",
]
