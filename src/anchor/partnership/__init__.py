"""Anchor Phase 7 Gate P7.9 -- Partnership Waterfalls and Investor Returns.

Governed by ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` (ratified),
under ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 13
and 14, which are authoritative on any discrepancy.

One deterministic layer downstream of the Capital Structure::

    StructuredCapitalResult.common_equity  -->  Partnership  -->  partner returns

**Stage 1** (this package): the contracts, validation, allocation, hurdle
accounts, waterfall, catch-up, benchmark attribution and partner metrics. No
persistence, fingerprint, route, Strategy domain, decision perspective or UI.

**Dependency direction.** ``common_equity`` is the only module that reads
Capital Structure results; ``contracts`` imports two calculation-free shapes
from the Capital Structure contracts; ``metrics`` is the only importer of the
unchanged ``anchor.engine.returns`` functions. Nothing upstream imports this
package.
"""

from __future__ import annotations

from .common_equity import common_equity_input, execute_partnership
from .contracts import (
    SHARE_SUM_TOLERANCE,
    WATERFALL_AMOUNT_TOLERANCE,
    BenchmarkShare,
    CashFlowCadence,
    CatchUpPeriodRecord,
    CatchUpRecipient,
    CatchUpRecipientKind,
    CatchUpTerms,
    CommonEquityCashFlowInput,
    CommonEquityUnavailable,
    ContributionRule,
    EconomicAccount,
    ExplicitSplit,
    HurdleAccountRecord,
    HurdleCombinator,
    HurdleCondition,
    HurdleSubject,
    HurdleSubjectKind,
    HurdleTerms,
    IrrHurdle,
    MoicHurdle,
    MoicUnavailableReason,
    Partner,
    PartnerPeriodAmounts,
    PartnerResult,
    PartnerRole,
    PartnerShare,
    Partnership,
    PartnershipExecutionError,
    PartnershipExecutionIssue,
    PartnershipExecutionIssueCode,
    PartnershipIssue,
    PartnershipIssueCode,
    PartnershipResult,
    PartnershipStatus,
    PartnershipUnavailableReason,
    PartnershipValidationError,
    PartnerTierAmount,
    PeriodRecord,
    PeriodShares,
    ProRataByContribution,
    PromoteBenchmark,
    PromoteUnavailableReason,
    SimpleDistributionOrder,
    SplitRule,
    SplitShare,
    TierKind,
    TierRemaining,
    TierResult,
    TierSplit,
    WaterfallTier,
)
from .validation import require_valid_partnership, validate_partnership
from .waterfall import allocate_partnership

__all__ = [
    "SHARE_SUM_TOLERANCE",
    "WATERFALL_AMOUNT_TOLERANCE",
    "BenchmarkShare",
    "CashFlowCadence",
    "CatchUpPeriodRecord",
    "CatchUpRecipient",
    "CatchUpRecipientKind",
    "CatchUpTerms",
    "CommonEquityCashFlowInput",
    "CommonEquityUnavailable",
    "ContributionRule",
    "EconomicAccount",
    "ExplicitSplit",
    "HurdleAccountRecord",
    "HurdleCombinator",
    "HurdleCondition",
    "HurdleSubject",
    "HurdleSubjectKind",
    "HurdleTerms",
    "IrrHurdle",
    "MoicHurdle",
    "MoicUnavailableReason",
    "Partner",
    "PartnerPeriodAmounts",
    "PartnerResult",
    "PartnerRole",
    "PartnerShare",
    "Partnership",
    "PartnershipExecutionError",
    "PartnershipExecutionIssue",
    "PartnershipExecutionIssueCode",
    "PartnershipIssue",
    "PartnershipIssueCode",
    "PartnershipResult",
    "PartnershipStatus",
    "PartnershipUnavailableReason",
    "PartnershipValidationError",
    "PartnerTierAmount",
    "PeriodRecord",
    "PeriodShares",
    "ProRataByContribution",
    "PromoteBenchmark",
    "PromoteUnavailableReason",
    "SimpleDistributionOrder",
    "SplitRule",
    "SplitShare",
    "TierKind",
    "TierRemaining",
    "TierResult",
    "TierSplit",
    "WaterfallTier",
    "allocate_partnership",
    "common_equity_input",
    "execute_partnership",
    "require_valid_partnership",
    "validate_partnership",
]
