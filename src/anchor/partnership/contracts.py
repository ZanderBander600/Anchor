"""Phase 7 Gate P7.9 -- the Partnership Waterfall and Investor Return contracts.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 3, 4, 5,
6 and 12 (ratified), under ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md``
Sections 13 and 14; those documents govern on any discrepancy. Like
``anchor.capital_structure.contracts``, this module performs no calculation.

Four groups:

- **Input**: the annual Common Equity Cash Flow the waterfall allocates. It
  carries no profit figure: Common Equity Total Profit is derived from the
  series (one authority).
- **Authored terms**: ``Partnership`` and its partners, benchmark, promote
  participants and waterfall tiers. No field that carries economics has a
  default; an empty tuple is a stated value.
- **Issues and errors**: structural (``PartnershipValidationError``) and
  execution (``PartnershipExecutionError``) refusals.
- **Results**: the partner-returns namespace (Section 14). Nothing here is
  appended to a project or position result.

The only upstream names imported are two calculation-free shapes from the
Capital Structure contracts: ``AccrualConvention`` (Q21, one extensible enum
everywhere) and ``CommonEquityUnavailableReason`` (the reason an unavailable
Partnership carries forward).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..capital_structure.contracts import AccrualConvention, CommonEquityUnavailableReason
from ..engine.contracts import IrrStatus

#: Section 5.1: a share table must sum to 1 within this tolerance.
SHARE_SUM_TOLERANCE = 1e-9

#: Section 6.1, in nominal dollars. A hurdle or catch-up capacity at or below it
#: is zero, a hurdle balance at or below it is satisfied, and partnership
#: profit at or below it keeps the catch-up domain closed. It guards
#: floating-point residue only and never rounds a reported figure.
WATERFALL_AMOUNT_TOLERANCE = 1e-6


# =============================================================================
# Input
# =============================================================================


class CashFlowCadence(StrEnum):
    """The cadence of the input series (PW-4). It is a property of the series,
    never of a tier. v1 executes ``ANNUAL`` only."""

    ANNUAL = "annual"


@dataclass(frozen=True, slots=True, kw_only=True)
class CommonEquityCashFlowInput:
    """The Common Equity Cash Flow a Partnership allocates.

    ``cash_flows[t]`` is period ``t``; for ``ANNUAL``, ``0`` is closing and
    ``t >= 1`` is hold year ``t`` (D6 Section 4). There is deliberately no
    profit field: Common Equity Total Profit is derived from this series."""

    cadence: CashFlowCadence
    cash_flows: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CommonEquityUnavailable:
    """The upstream Common Equity Cash Flow is not reported (P-9): an
    unresolved Funding Requirement. The Partnership is then unavailable with
    this reason, and nothing is zero-filled."""

    reason: CommonEquityUnavailableReason
    message: str
    requirement_ids: tuple[str, ...]


# =============================================================================
# Authored terms
# =============================================================================


class PartnerRole(StrEnum):
    """Reporting only. A role never selects a hurdle subject, a catch-up
    recipient or a promote participant."""

    LP = "lp"
    GP = "gp"
    CO_INVESTOR = "co_investor"


class ContributionRule(StrEnum):
    """Who funds a capital call. v1 executes ``PRO_RATA_BY_COMMITMENT`` only;
    other rules are later ratifications."""

    PRO_RATA_BY_COMMITMENT = "pro_rata_by_commitment"


class TierKind(StrEnum):
    HURDLE = "hurdle"
    CATCH_UP = "catch_up"
    RESIDUAL = "residual"


class HurdleSubjectKind(StrEnum):
    """Whose return a hurdle tests (Q20, Q1). Required; there is no default."""

    PARTNER = "partner"
    INVESTOR_CLASS = "investor_class"
    ECONOMIC_ACCOUNT = "economic_account"


class EconomicAccount(StrEnum):
    ALL_COMMON_EQUITY = "all_common_equity"


class HurdleCombinator(StrEnum):
    """``ALL``: the tier pays until every condition is met (the later / greater
    of). ``ANY``: until any condition is met (the earlier / lesser of)."""

    ALL = "all"
    ANY = "any"


class SimpleDistributionOrder(StrEnum):
    """How a subject distribution is applied to a ``SIMPLE`` account: accrued
    return first, or capital first. Required on ``SIMPLE`` only; no default."""

    ACCRUED_RETURN_FIRST = "accrued_return_first"
    CAPITAL_FIRST = "capital_first"


class CatchUpRecipientKind(StrEnum):
    """Who a catch-up tier catches up. There is deliberately no economic
    account: an all-partners recipient makes the target share meaningless."""

    PARTNER = "partner"
    INVESTOR_CLASS = "investor_class"


class SplitRule(StrEnum):
    """Which kind of split a tier states (reported on each tier result)."""

    EXPLICIT = "explicit"
    PRO_RATA_BY_CONTRIBUTION = "pro_rata_by_contribution"


@dataclass(frozen=True, slots=True, kw_only=True)
class Partner:
    """One partner. ``name`` is display only; ``role`` is reporting only;
    ``investor_class`` is a stable class token, economic wherever a hurdle
    subject or catch-up recipient names it."""

    partner_id: str
    name: str
    role: PartnerRole
    investor_class: str | None
    commitment_share: float


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkShare:
    partner_id: str
    share: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PromoteBenchmark:
    """The no-promote pro-rata ownership benchmark (PW-6, Q2): a literal table,
    one share per partner, never derived from or linked to commitments."""

    shares: tuple[BenchmarkShare, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SplitShare:
    partner_id: str
    share: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplicitSplit:
    """One share per partner, summing to 1."""

    shares: tuple[SplitShare, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProRataByContribution:
    """Split by cumulative actual partner contributions through the
    distributing period (Section 6.2). Executed in v1; a zero denominator when
    cash must be split is a deterministic refusal."""


TierSplit = ExplicitSplit | ProRataByContribution


@dataclass(frozen=True, slots=True, kw_only=True)
class HurdleSubject:
    """``PARTNER`` with ``partner_id``; ``INVESTOR_CLASS`` with
    ``investor_class``; ``ECONOMIC_ACCOUNT`` with ``account``. Exactly the
    field of its kind is stated. A multi-member subject has one aggregate
    account."""

    kind: HurdleSubjectKind
    partner_id: str | None
    investor_class: str | None
    account: EconomicAccount | None


@dataclass(frozen=True, slots=True, kw_only=True)
class IrrHurdle:
    """An IRR-type hurdle at annual ``rate`` under an explicit accrual
    convention. ``simple_distribution_order`` is required iff the convention is
    ``SIMPLE`` and refused otherwise."""

    condition_id: str
    rate: float
    accrual_convention: AccrualConvention
    simple_distribution_order: SimpleDistributionOrder | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MoicHurdle:
    """A multiple-of-contributions hurdle; ``multiple >= 1``. No accrual and no
    distribution order."""

    condition_id: str
    multiple: float


HurdleCondition = IrrHurdle | MoicHurdle


@dataclass(frozen=True, slots=True, kw_only=True)
class HurdleTerms:
    hurdle_subject: HurdleSubject
    conditions: tuple[HurdleCondition, ...]
    combinator: HurdleCombinator


@dataclass(frozen=True, slots=True, kw_only=True)
class CatchUpRecipient:
    """``PARTNER`` with ``partner_id``, or ``INVESTOR_CLASS`` with
    ``investor_class``."""

    kind: CatchUpRecipientKind
    partner_id: str | None
    investor_class: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CatchUpTerms:
    """The catch-up target. The catch-up **rate** is not stored: it is the
    recipient's aggregate share in the tier's explicit split (one authority)."""

    recipient: CatchUpRecipient
    target_profit_share: float


@dataclass(frozen=True, slots=True, kw_only=True)
class WaterfallTier:
    """One tier. ``sequence`` is the economic order (P-7); ``name`` is display
    only. ``hurdle`` is stated iff ``HURDLE``, ``catch_up`` iff ``CATCH_UP``."""

    tier_id: str
    name: str
    sequence: int
    kind: TierKind
    split: TierSplit
    hurdle: HurdleTerms | None
    catch_up: CatchUpTerms | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Partnership:
    """The Partnership terms of one analysis root.

    ``promote_participant_ids`` explicitly names the partners measured for
    Promote Earned; the empty tuple states that none is. Roles never imply
    participation."""

    partners: tuple[Partner, ...]
    contribution_rule: ContributionRule
    promote_benchmark: PromoteBenchmark
    promote_participant_ids: tuple[str, ...]
    tiers: tuple[WaterfallTier, ...]


# =============================================================================
# Issues and errors
# =============================================================================


class PartnershipIssueCode(StrEnum):
    """Stable reasons a Partnership contract is structurally invalid
    (Section 5.1)."""

    INVALID_PARTNERSHIP = "invalid_partnership"
    NO_PARTNERS = "no_partners"
    INVALID_PARTNER = "invalid_partner"
    BLANK_PARTNER_ID = "blank_partner_id"
    DUPLICATE_PARTNER_ID = "duplicate_partner_id"
    INVALID_ROLE = "invalid_role"
    INVALID_INVESTOR_CLASS = "invalid_investor_class"
    INVALID_SHARE = "invalid_share"
    SHARES_DO_NOT_SUM_TO_ONE = "shares_do_not_sum_to_one"
    INVALID_CONTRIBUTION_RULE = "invalid_contribution_rule"
    INVALID_BENCHMARK = "invalid_benchmark"
    BENCHMARK_PARTNER_SET_MISMATCH = "benchmark_partner_set_mismatch"
    INVALID_PROMOTE_PARTICIPANTS = "invalid_promote_participants"
    UNKNOWN_PROMOTE_PARTICIPANT = "unknown_promote_participant"
    DUPLICATE_PROMOTE_PARTICIPANT = "duplicate_promote_participant"
    NO_TIERS = "no_tiers"
    INVALID_TIER = "invalid_tier"
    DUPLICATE_TIER_ID = "duplicate_tier_id"
    INVALID_SEQUENCE = "invalid_sequence"
    DUPLICATE_SEQUENCE = "duplicate_sequence"
    RESIDUAL_COUNT = "residual_count"
    RESIDUAL_NOT_LAST = "residual_not_last"
    KIND_TERMS_MISMATCH = "kind_terms_mismatch"
    MISSING_SPLIT = "missing_split"
    INVALID_SPLIT = "invalid_split"
    SPLIT_PARTNER_SET_MISMATCH = "split_partner_set_mismatch"
    MISSING_HURDLE_SUBJECT = "missing_hurdle_subject"
    INVALID_HURDLE_SUBJECT = "invalid_hurdle_subject"
    UNKNOWN_SUBJECT_PARTNER = "unknown_subject_partner"
    EMPTY_INVESTOR_CLASS = "empty_investor_class"
    HURDLE_SUBJECT_HAS_NO_SHARE_IN_TIER = "hurdle_subject_has_no_share_in_tier"
    NO_CONDITIONS = "no_conditions"
    INVALID_CONDITION = "invalid_condition"
    DUPLICATE_CONDITION_ID = "duplicate_condition_id"
    INVALID_RATE = "invalid_rate"
    INVALID_MULTIPLE = "invalid_multiple"
    MISSING_ACCRUAL_CONVENTION = "missing_accrual_convention"
    MISSING_SIMPLE_DISTRIBUTION_ORDER = "missing_simple_distribution_order"
    UNEXPECTED_SIMPLE_DISTRIBUTION_ORDER = "unexpected_simple_distribution_order"
    INVALID_COMBINATOR = "invalid_combinator"
    INVALID_CATCH_UP_RECIPIENT = "invalid_catch_up_recipient"
    UNSUPPORTED_CATCH_UP_RECIPIENT = "unsupported_catch_up_recipient"
    CATCH_UP_REQUIRES_EXPLICIT_SPLIT = "catch_up_requires_explicit_split"
    INVALID_TARGET_PROFIT_SHARE = "invalid_target_profit_share"
    CATCH_UP_RATE_NOT_ABOVE_TARGET = "catch_up_rate_not_above_target"


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnershipIssue:
    """One deterministic reason. ``partner_id`` / ``tier_id`` locate it where
    identifiable; ``field`` names the finding within it."""

    code: PartnershipIssueCode
    message: str
    partner_id: str | None = None
    tier_id: str | None = None
    field: str | None = None

    def __str__(self) -> str:
        return self.message


class PartnershipValidationError(ValueError):
    """An invalid Partnership: one ordered collection of ``PartnershipIssue``.
    Nothing is allocated and nothing is repaired."""

    def __init__(self, issues: Iterable[PartnershipIssue]) -> None:
        ordered = tuple(issues)
        if not ordered:
            raise ValueError("PartnershipValidationError requires at least one issue.")
        if not all(isinstance(issue, PartnershipIssue) for issue in ordered):
            raise TypeError("issues must contain only PartnershipIssue instances.")
        self.issues = ordered
        super().__init__("\n".join(issue.message for issue in ordered))


class PartnershipExecutionIssueCode(StrEnum):
    """Stable reasons the v1 executor refuses to run (Section 5.2)."""

    UNSUPPORTED_CADENCE = "unsupported_cadence"
    UNSUPPORTED_CONTRIBUTION_RULE = "unsupported_contribution_rule"
    UNSUPPORTED_ACCRUAL_CONVENTION = "unsupported_accrual_convention"
    NO_CONTRIBUTIONS_FOR_PRO_RATA_SPLIT = "no_contributions_for_pro_rata_split"
    SUBJECT_WITHOUT_SPLIT_SHARE = "subject_without_split_share"
    INVALID_COMMON_EQUITY_SERIES = "invalid_common_equity_series"


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnershipExecutionIssue:
    code: PartnershipExecutionIssueCode
    message: str
    tier_id: str | None = None
    period: int | None = None

    def __str__(self) -> str:
        return self.message


class PartnershipExecutionError(ValueError):
    """A contract, or a contract over this series, that v1 does not execute.
    Nothing is moved to a supported convention and nothing is partially
    executed."""

    def __init__(self, issues: Iterable[PartnershipExecutionIssue]) -> None:
        ordered = tuple(issues)
        if not ordered:
            raise ValueError("PartnershipExecutionError requires at least one issue.")
        if not all(isinstance(issue, PartnershipExecutionIssue) for issue in ordered):
            raise TypeError("issues must contain only PartnershipExecutionIssue instances.")
        self.issues = ordered
        super().__init__("\n".join(issue.message for issue in ordered))


# =============================================================================
# Results
# =============================================================================


class PartnershipStatus(StrEnum):
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"


class PartnershipUnavailableReason(StrEnum):
    COMMON_EQUITY_UNAVAILABLE = "common_equity_unavailable"


class PromoteUnavailableReason(StrEnum):
    """Why ``promote_earned`` is not applicable (P-9): never shown as zero."""

    NOT_A_PROMOTE_PARTICIPANT = "not_a_promote_participant"


class MoicUnavailableReason(StrEnum):
    NO_CONTRIBUTIONS = "no_contributions"


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnerShare:
    partner_id: str
    share: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PeriodShares:
    """The shares a tier actually applied in one period."""

    period: int
    shares: tuple[PartnerShare, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnerTierAmount:
    tier_id: str
    sequence: int
    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnerPeriodAmounts:
    partner_id: str
    amounts: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class HurdleAccountRecord:
    """One hurdle condition's account in one period (Section 8).

    ``capacity_at_entry`` is ``None`` when the tier was not entered that period
    (no cash reached it). ``simple_distribution_order``,
    ``outstanding_capital`` and ``accrued_return`` are stated for ``SIMPLE``
    accounts only."""

    condition_id: str
    period: int
    opening_balance: float
    accrual: float
    subject_contributions: float
    subject_distributions_before_tier: float
    subject_distributions_from_tier: float
    subject_distributions_after_tier: float
    closing_balance: float
    capacity_at_entry: float | None
    satisfied_at_close: bool
    simple_distribution_order: SimpleDistributionOrder | None
    outstanding_capital: float | None
    accrued_return: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CatchUpPeriodRecord:
    """One period in which cash reached a catch-up tier (Section 9)."""

    period: int
    partnership_profit_at_entry: float
    recipient_profit_at_entry: float
    profit_domain_open: bool
    capacity_at_entry: float
    paid: float
    partnership_profit_at_exit: float
    recipient_profit_at_exit: float
    caught_up: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TierRemaining:
    tier_id: str
    sequence: int
    remaining: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PeriodRecord:
    """``total_contributions`` is ``max(-CECF_t, 0)`` and
    ``total_distributions`` is ``max(CECF_t, 0)``: the amounts allocated.
    ``remaining_after_tier`` lists every tier cash reached."""

    period: int
    common_equity_cash_flow: float
    total_contributions: float
    total_distributions: float
    remaining_after_tier: tuple[TierRemaining, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TierResult:
    """One tier's audit. Hurdle fields are stated for ``HURDLE`` tiers and
    catch-up fields for ``CATCH_UP`` tiers; ``catch_up_rate`` is derived from
    the explicit split. The tier's display name stays on the authored
    ``WaterfallTier``: names never enter a financial result (FP-1)."""

    tier_id: str
    sequence: int
    kind: TierKind
    split_rule: SplitRule
    shares_by_period: tuple[PeriodShares, ...]
    hurdle_subject: HurdleSubject | None
    subject_partner_ids: tuple[str, ...] | None
    combinator: HurdleCombinator | None
    catch_up_recipient: CatchUpRecipient | None
    recipient_partner_ids: tuple[str, ...] | None
    catch_up_rate: float | None
    target_profit_share: float | None
    amounts: tuple[float, ...]
    partner_amounts: tuple[PartnerPeriodAmounts, ...]
    conditions: tuple[HurdleAccountRecord, ...]
    catch_up_records: tuple[CatchUpPeriodRecord, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnerResult:
    """One partner's returns (the partner-returns namespace, Section 14). The
    partner's display name stays on the authored ``Partner``: names never enter
    a financial result (FP-1).

    **Cash and returns.** Per-period ``contributions`` and ``distributions``;
    ``net_cash_flows``; totals, ``profit``, ``irr`` / ``irr_status`` and
    ``moic`` from the unchanged ``anchor.engine.returns`` functions.

    **Benchmark decomposition** (Section 11, whole hold):
    ``capital_returned = min(D, C)``; ``profit_distributions`` is the rest; the
    same on the benchmark side. Signed ``distribution_difference`` =
    ``capital_return_difference`` + ``profit_distribution_difference``;
    ``distribution_advantage`` / ``distribution_disadvantage`` are its floors
    and are never promote.

    **Promote Earned** is ``max(profit_distribution_difference, 0)`` for a
    promote participant, else ``None`` with ``NOT_A_PROMOTE_PARTICIPANT``.
    ``promote_attribution_by_tier`` is signed per tier -- an individual tier may
    be negative -- and sums to ``promote_earned``; it is ``None`` for a
    non-participant.

    **Benchmark capital subordination** is
    ``max(-capital_return_difference, 0)``: own capital the benchmark would
    have returned and the waterfall did not."""

    partner_id: str
    role: PartnerRole
    investor_class: str | None
    commitment_share: float
    benchmark_share: float
    benchmark_equals_commitment: bool
    is_promote_participant: bool

    contributions: tuple[float, ...]
    distributions: tuple[float, ...]
    net_cash_flows: tuple[float, ...]
    total_contributions: float
    total_distributions: float
    profit: float
    irr: float | None
    irr_status: IrrStatus
    moic: float | None
    moic_unavailable_reason: MoicUnavailableReason | None

    benchmark_distributions: tuple[float, ...]
    total_benchmark_distributions: float
    capital_returned: float
    profit_distributions: float
    benchmark_capital_returned: float
    benchmark_profit_distributions: float
    distribution_difference: float
    distribution_advantage: float
    distribution_disadvantage: float
    capital_return_difference: float
    profit_distribution_difference: float
    promote_earned: float | None
    promote_unavailable_reason: PromoteUnavailableReason | None
    benchmark_capital_subordination: float

    distributions_by_tier: tuple[PartnerTierAmount, ...]
    capital_return_difference_by_tier: tuple[PartnerTierAmount, ...]
    profit_distribution_difference_by_tier: tuple[PartnerTierAmount, ...]
    promote_attribution_by_tier: tuple[PartnerTierAmount, ...] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnershipResult:
    """The Partnership economics of one analysis root.

    ``UNAVAILABLE`` when the upstream Common Equity Cash Flow is not reported:
    every figure is then ``None`` (never zero-filled), with the upstream reason
    and the unresolved requirement ids. ``cadence`` is always stated: v1
    allocates the annual series, available or not."""

    status: PartnershipStatus
    unavailable_reason: PartnershipUnavailableReason | None
    unavailable_message: str | None
    upstream_reason: CommonEquityUnavailableReason | None
    upstream_requirement_ids: tuple[str, ...]
    cadence: CashFlowCadence
    promote_participant_ids: tuple[str, ...]
    common_equity_cash_flows: tuple[float, ...] | None
    common_equity_total_profit: float | None
    partners: tuple[PartnerResult, ...] | None
    tiers: tuple[TierResult, ...] | None
    periods: tuple[PeriodRecord, ...] | None
