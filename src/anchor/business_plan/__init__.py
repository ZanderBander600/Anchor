"""Anchor Phase 6 Business Plan -- owner-level capital economics inputs.

Gate D6.1. Governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md``,
which is authoritative on any discrepancy.

D5 forecasts the property; the Business Plan models the cost of executing the
plan. It is mode-agnostic, separate from ``AcquisitionTerms`` and every
operating-mode input, and resolved once into the generic engine contract
``anchor.engine.contracts.OwnerCapitalSchedule``::

    BusinessPlan -> validation -> resolve_business_plan -> OwnerCapitalSchedule

**Dependency direction.** This package may import the calculation-free
``anchor.engine.contracts`` and nothing else under ``anchor``. The engine, the
leasing layer and every other package must not import this one; the engine
will consume only the resolved ``OwnerCapitalSchedule``.

**Unwired at D6.1.** No acquisition-analysis path consumes a Business Plan
yet, so no D5 financial output moves. D6.2 owns the engine bridge. The
boundary is enforced by ``tests/test_business_plan_architecture.py``.

``OwnerCapitalSchedule`` is deliberately **not** re-exported here: it is an
engine contract and is imported from ``anchor.engine.contracts``.
"""

from __future__ import annotations

from .contracts import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseHoldTreatment,
    OwnerExpenseItem,
)
from .resolver import owner_expense_hold_treatments, resolve_business_plan
from .validation import (
    BusinessPlanIssueCode,
    BusinessPlanValidationError,
    BusinessPlanValidationIssue,
    BusinessPlanValidationResult,
    require_valid_business_plan,
    validate_business_plan,
)

__all__ = [
    # contracts
    "BusinessPlan",
    "CapitalItemCategory",
    "CapitalPlanItem",
    "OwnerExpenseCategory",
    "OwnerExpenseHoldTreatment",
    "OwnerExpenseItem",
    # resolver
    "resolve_business_plan",
    "owner_expense_hold_treatments",
    # validation
    "BusinessPlanIssueCode",
    "BusinessPlanValidationError",
    "BusinessPlanValidationIssue",
    "BusinessPlanValidationResult",
    "validate_business_plan",
    "require_valid_business_plan",
]
