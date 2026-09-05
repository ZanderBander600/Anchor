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

Later D1 gates add, in order: canonical month identity (D1.1), the
contractual base-rent monthly timeline (D1.2), and the property rent-roll
schedule with annual aggregation derived from it (D1.3).
"""

from __future__ import annotations

from .contracts import (
    EscalationBasis,
    Lease,
    LeaseLevelPropertyInputs,
    LeaseOrigin,
    LeaseType,
    Suite,
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
    # contracts
    "EscalationBasis",
    "Lease",
    "LeaseLevelPropertyInputs",
    "LeaseOrigin",
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
