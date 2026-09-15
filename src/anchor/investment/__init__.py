"""Anchor Phase 7 Gate P7.6 -- Investment-level inputs.

Governed by ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md``, which
is authoritative on any discrepancy.

A visible Investment is one negotiated transaction over one or more Underwriting
Units, each an existing Deal, unchanged. This package describes what the
Investment states beyond its Units -- the transaction price, each Unit's
membership (presentation and economic timing), the transaction costs -- and
validates it, together with the Investment-level rules a variant's resolved
Units must meet (the common timeline, CON-1, and the price allocation, PP-2).

**Dependency direction.** Pure contracts and validation: it imports the
calculation-free ``anchor.contracts`` and ``anchor.business_plan`` and nothing
that stores, routes or calculates. The consolidation layer consumes it; nothing
here consumes a result.
"""

from __future__ import annotations

from .contracts import (
    ALLOCATION_TOLERANCE,
    SUPPORTED_ACQUISITION_MONTH,
    SUPPORTED_TRANSACTION_COST_MONTH,
    InvestmentIssue,
    InvestmentIssueCode,
    InvestmentTransactionCost,
    InvestmentUnitMembership,
    InvestmentValidationError,
    TransactionCostCategory,
    UnitKind,
)
from .validation import (
    UnitEconomicFacts,
    allocation_variance,
    validate_allocation,
    validate_common_timeline,
    validate_investment_business_plan,
    validate_investment_details,
    validate_investment_inputs,
    validate_transaction_costs,
    validate_unit_memberships,
    validate_variant_economics,
)

__all__ = [
    "ALLOCATION_TOLERANCE",
    "SUPPORTED_ACQUISITION_MONTH",
    "SUPPORTED_TRANSACTION_COST_MONTH",
    "InvestmentIssue",
    "InvestmentIssueCode",
    "InvestmentTransactionCost",
    "InvestmentUnitMembership",
    "InvestmentValidationError",
    "TransactionCostCategory",
    "UnitEconomicFacts",
    "UnitKind",
    "allocation_variance",
    "validate_allocation",
    "validate_common_timeline",
    "validate_investment_business_plan",
    "validate_investment_details",
    "validate_investment_inputs",
    "validate_transaction_costs",
    "validate_unit_memberships",
    "validate_variant_economics",
]
