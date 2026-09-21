"""Phase 7 Gate P7.10 Stage 1 -- the deterministic valuation layer.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` is the authority.

The package answers two questions and no others:

1. what is one Unit, and one contemporaneous Investment, worth at one
   analyst-approved valuation timepoint of one resolved Analysis Variant; and
2. what dollars does an existing ``PctOfValue`` funding rule resolve to.

Everything it returns is a reporting value except the reserved, read-only
system Exit view, which is the existing D6 terminal result read unchanged.
Nothing here produces a cash flow, a sale proceed, a Strategy, a Scenario, a
consolidation, a Capital Structure, a position return or a Partnership figure.

Stage 1 is pure and deterministic: no persistence, migration, schema version,
API route, memo record, AI grounding, PDF or frontend surface belongs to it.
"""

from __future__ import annotations

from .contracts import (
    AnalystValue,
    DirectCap,
    ExitValuationView,
    FundingResolutionStatus,
    InvestmentValuationResult,
    ResolvedValuationFunding,
    UnitValuationInstruction,
    UnitValuationResult,
    UnresolvedFundingReason,
    UnresolvedFundingRequirement,
    ValuationAvailability,
    ValuationError,
    ValuationFundingResolution,
    ValuationIssue,
    ValuationIssueCode,
    ValuationKind,
    ValuationMethod,
    ValuationMethodKind,
    ValuationScopeKind,
    ValuationTimepoint,
    ValuationUnavailableReason,
    ValuationUnitInputs,
    ValuationValidationError,
    ValuationVariantInputs,
)
from .engine import (
    exit_model_month,
    forward_noi_at,
    investment_exit_view,
    resolve_investment_valuation,
    require_hold_year_end,
    resolve_unit_valuation,
    timepoint_month_reason,
    unit_exit_view,
    unit_inputs,
    variant_inputs,
)
from .funding import ValuationAuthority, resolve_pct_of_value_funding, valuation_authority
from .validation import require_valid_valuation_timepoint, validate_valuation_timepoint

__all__ = [
    "AnalystValue",
    "DirectCap",
    "ExitValuationView",
    "FundingResolutionStatus",
    "InvestmentValuationResult",
    "ResolvedValuationFunding",
    "UnitValuationInstruction",
    "UnitValuationResult",
    "UnresolvedFundingReason",
    "UnresolvedFundingRequirement",
    "ValuationAuthority",
    "ValuationAvailability",
    "ValuationError",
    "ValuationFundingResolution",
    "ValuationIssue",
    "ValuationIssueCode",
    "ValuationKind",
    "ValuationMethod",
    "ValuationMethodKind",
    "ValuationScopeKind",
    "ValuationTimepoint",
    "ValuationUnavailableReason",
    "ValuationUnitInputs",
    "ValuationValidationError",
    "ValuationVariantInputs",
    "exit_model_month",
    "forward_noi_at",
    "investment_exit_view",
    "require_hold_year_end",
    "require_valid_valuation_timepoint",
    "resolve_investment_valuation",
    "resolve_pct_of_value_funding",
    "resolve_unit_valuation",
    "timepoint_month_reason",
    "unit_exit_view",
    "unit_inputs",
    "valuation_authority",
    "validate_valuation_timepoint",
    "variant_inputs",
]
