"""Anchor Phase 7 Gate P7.7 -- the Capital Structure foundation.

Governed by ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md``
Section 12, which is authoritative on any discrepancy, and recorded in
``docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md``.

One deterministic layer downstream of the engine and consolidation::

    each Unit: AcquisitionResults ---------+---> legacy acquisition-loan adapter
                                           |          (read only)
    the Investment: ConsolidatedResults ---+
                                           v
                                    Capital Structure  -->  Common Equity Cash Flow

P7.7 executes only each Unit's existing acquisition loan and the residual common
equity; the Common Equity Cash Flow is then exactly today's levered cash flow.

**Dependency direction.** This package imports the calculation-free result and
input contracts (``anchor.engine.contracts``, ``anchor.consolidation.contracts``,
``anchor.contracts``) and nothing that calculates: no engine entry point, no debt
or returns function, no mode, storage or route. Nothing upstream imports it.
"""

from __future__ import annotations

from .contracts import (
    LEGACY_ACQUISITION_LOAN_ID_PREFIX,
    LEGACY_ACQUISITION_LOAN_PRIORITY,
    MONTHS_PER_HOLD_YEAR,
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureError,
    CapitalStructureIssue,
    CapitalStructureIssueCode,
    CapitalStructureStatus,
    CapitalStructureUnit,
    CapitalStructureValidationError,
    ClaimPeriod,
    ClaimSettlement,
    CommonEquityOutcome,
    CommonEquityUnavailableReason,
    ContractualClaim,
    DebtTerms,
    FixedAmount,
    FundingAmountRule,
    FundingEvent,
    FundingRequirement,
    FundingRequirementStatus,
    HoldYearPeriod,
    InvestmentCapitalStructureResult,
    InvestmentScopeCashAuthority,
    LegacyAcquisitionLoan,
    ModelMonthPeriod,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    PositionFee,
    PositionScope,
    PositionTerms,
    PreferredEquityTerms,
    ScopeKind,
    ShortfallResolution,
    TimingBasis,
    UnitCapitalStructureResult,
    UnitCashAuthority,
    UnsupportedCapitalPositionError,
)
from .foundation import (
    analyze_investment_capital_structure,
    analyze_unit_capital_structure,
    annual_period_of_model_month,
    common_equity_outcome,
    investment_scope_cash_authority,
    settle_claim,
    unit_cash_authority,
)
from .legacy import (
    adapt_legacy_acquisition_loan,
    legacy_acquisition_loan_claims,
    legacy_acquisition_loan_id,
)
from .validation import economic_order, scope_order_key, validate_capital_structure

__all__ = [
    "LEGACY_ACQUISITION_LOAN_ID_PREFIX",
    "LEGACY_ACQUISITION_LOAN_PRIORITY",
    "MONTHS_PER_HOLD_YEAR",
    "AccrualConvention",
    "CapitalPosition",
    "CapitalStructure",
    "CapitalStructureError",
    "CapitalStructureIssue",
    "CapitalStructureIssueCode",
    "CapitalStructureStatus",
    "CapitalStructureUnit",
    "CapitalStructureValidationError",
    "ClaimPeriod",
    "ClaimSettlement",
    "CommonEquityOutcome",
    "CommonEquityUnavailableReason",
    "ContractualClaim",
    "DebtTerms",
    "FixedAmount",
    "FundingAmountRule",
    "FundingEvent",
    "FundingRequirement",
    "FundingRequirementStatus",
    "HoldYearPeriod",
    "InvestmentCapitalStructureResult",
    "InvestmentScopeCashAuthority",
    "LegacyAcquisitionLoan",
    "ModelMonthPeriod",
    "PctOfPrice",
    "PctOfValue",
    "PositionClass",
    "PositionFee",
    "PositionScope",
    "PositionTerms",
    "PreferredEquityTerms",
    "ScopeKind",
    "ShortfallResolution",
    "TimingBasis",
    "UnitCapitalStructureResult",
    "UnitCashAuthority",
    "UnsupportedCapitalPositionError",
    "adapt_legacy_acquisition_loan",
    "analyze_investment_capital_structure",
    "analyze_unit_capital_structure",
    "annual_period_of_model_month",
    "common_equity_outcome",
    "economic_order",
    "investment_scope_cash_authority",
    "legacy_acquisition_loan_claims",
    "legacy_acquisition_loan_id",
    "scope_order_key",
    "settle_claim",
    "unit_cash_authority",
    "validate_capital_structure",
]
