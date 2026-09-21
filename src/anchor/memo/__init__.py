"""Phase 7 Gate P7.10 Stage 2 -- the Investment Memo domain.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` is the authority.

The package answers four questions and no others:

1. what shapes does an Investment Memo, its evidence, its immutable versions
   and the Investment Committee's separate decision have;
2. whether an authored memo or Evidence Reference is well formed;
3. how an unresolved valuation or value-sized funding state becomes the
   structured unavailable / N/A representation (the Stage 2 obligation in
   Section 6.2); and
4. whether a draft may become an immutable published version.

**Pure.** Nothing here reads a database, builds a fingerprint, resolves a
variant, formats a response or calls a model. Persistence lives in
``anchor.deals.store``, identity in ``anchor.deals.fingerprint``, resolution in
``anchor.deals.valuation_views`` and ``anchor.deals.memo_dependencies``, and the
wire in ``anchor.api``.

**No financial authority.** No shape here holds a calculated amount, and no
function here computes one. A memo cites the deterministic engine's results; it
never restates or recomputes them.

**No AI, no PDF, no frontend.** Stage 2 implements none of them. The analyst
recommendation and the Investment Committee decision are separate fields,
separate records and separate acts (R-F), and no code path in this gate writes
either on an analyst's behalf.
"""

from __future__ import annotations

from .availability import (
    AvailabilityStatus,
    UnavailableAdapterError,
    UnavailableReasonCode,
    UnavailableState,
    evidence_not_approved,
    funding_unresolved,
    investment_unavailable,
    not_authored,
    not_implemented_for_scope,
    stale_dependency,
    unit_unavailable,
    valuation_reason_code,
    variant_invalid,
)
from .contracts import (
    DEPENDENCY_REPORT_ORDER,
    FINANCIAL_DEPENDENCY_CLASSES,
    AnalystRecommendation,
    DecisionPerspectiveKind,
    EvidenceSourceKind,
    ExecutionComplexity,
    InvestmentCommitteeDecision,
    InvestmentCommitteeOutcome,
    InvestmentMemoDraft,
    InvestmentMemoVersion,
    MemoDependency,
    MemoDependencyClass,
    MemoError,
    MemoEvidenceReference,
    MemoFreshness,
    MemoFreshnessReport,
    MemoItem,
    MemoRiskItem,
    MemoSection,
    MemoStaleDependency,
    MemoTermItem,
    MemoVersionValuation,
    RiskSeverity,
    SelectedDecision,
    TermPriority,
)
from .publication import (
    PublicationContext,
    PublicationRefusal,
    PublicationRefusalCode,
    PublicationRefusedError,
    next_version_number,
    publication_refusals,
    require_publishable,
)
from .validation import (
    MemoIssue,
    MemoIssueCode,
    MemoValidationError,
    require_valid_evidence_reference,
    require_valid_memo_draft,
    validate_evidence_reference,
    validate_memo_draft,
    validate_memo_items,
    validate_memo_risk_items,
    validate_memo_term_items,
    validate_selected_decision,
)

__all__ = [
    "DEPENDENCY_REPORT_ORDER",
    "FINANCIAL_DEPENDENCY_CLASSES",
    "AnalystRecommendation",
    "AvailabilityStatus",
    "DecisionPerspectiveKind",
    "EvidenceSourceKind",
    "ExecutionComplexity",
    "InvestmentCommitteeDecision",
    "InvestmentCommitteeOutcome",
    "InvestmentMemoDraft",
    "InvestmentMemoVersion",
    "MemoDependency",
    "MemoDependencyClass",
    "MemoError",
    "MemoEvidenceReference",
    "MemoFreshness",
    "MemoFreshnessReport",
    "MemoIssue",
    "MemoIssueCode",
    "MemoItem",
    "MemoRiskItem",
    "MemoSection",
    "MemoStaleDependency",
    "MemoTermItem",
    "MemoValidationError",
    "MemoVersionValuation",
    "PublicationContext",
    "PublicationRefusal",
    "PublicationRefusalCode",
    "PublicationRefusedError",
    "RiskSeverity",
    "SelectedDecision",
    "TermPriority",
    "UnavailableAdapterError",
    "UnavailableReasonCode",
    "UnavailableState",
    "evidence_not_approved",
    "funding_unresolved",
    "investment_unavailable",
    "next_version_number",
    "not_authored",
    "not_implemented_for_scope",
    "publication_refusals",
    "require_publishable",
    "require_valid_evidence_reference",
    "require_valid_memo_draft",
    "stale_dependency",
    "unit_unavailable",
    "valuation_reason_code",
    "validate_evidence_reference",
    "validate_memo_draft",
    "validate_memo_items",
    "validate_memo_risk_items",
    "validate_memo_term_items",
    "validate_selected_decision",
    "variant_invalid",
]
