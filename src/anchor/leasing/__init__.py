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
    Lease,
    LeaseLevelPropertyInputs,
    LeaseMonthlySchedule,
    LeaseType,
    ModelMonth,
    PropertyRentRollSchedule,
    Suite,
)
from .rent import build_lease_monthly_schedule
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
