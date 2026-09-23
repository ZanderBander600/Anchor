"""Phase 7 Gate P7.7 -- the Capital Structure contracts.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
3 (P-4, P-7, P-8, P-9, P-11, P-14, P-15), 12 and 14, and the Section 21 record
(Q12, Q13, Q16, Q21); that document governs on any discrepancy. The P7.7
implementation decisions are recorded in
``docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md``. Like
``anchor.engine.contracts``, this module performs no calculation of its own.

Three groups of contracts:

- **Authored positions** (``CapitalPosition`` inside a ``CapitalStructure``):
  the permanent typed core that later gates author, persist and execute. Shape
  only: ``anchor.capital_structure.validation`` holds every rule, following the
  repository's contract/validator split. P7.7 executes no authored position.
- **The legacy acquisition loan** (``LegacyAcquisitionLoan``): each Unit's
  existing acquisition loan, read off its completed ``AcquisitionResults`` and
  presented as that Unit's priority-1 senior debt. Never authored, never
  persisted, never recomputed.
- **Results**: the ``FundingRequirement`` a contractual shortfall produces, the
  named cash authorities of the pre-capital-structure handoff, and what the
  foundation facades return.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from ..contracts import AcquisitionTerms
from ..engine.contracts import AcquisitionResults

#: The reserved prefix of every adapted acquisition-loan identity, completed by
#: the Unit's ``unit_id``. No authored position, funding event or fee may use
#: it (``validation``), so an adapted loan can never be mistaken for an authored
#: position. It is never written to storage.
LEGACY_ACQUISITION_LOAN_ID_PREFIX = "legacy-acquisition-loan:"

#: The acquisition loan's rank in its Unit's scope: the most senior.
LEGACY_ACQUISITION_LOAN_PRIORITY = 1

#: D6 Section 4: a hold year is twelve model months.
MONTHS_PER_HOLD_YEAR = 12


# =============================================================================
# Authored positions
# =============================================================================


class PositionClass(StrEnum):
    """What kind of claim a Capital Position is (Section 12.2, CS-2).

    No class carries a formula in P7.7. The only executable senior debt is each
    Unit's existing acquisition loan, read through the legacy adapter."""

    SENIOR_DEBT = "senior_debt"
    MEZZANINE_DEBT = "mezzanine_debt"
    PREFERRED_EQUITY = "preferred_equity"
    COMMON_EQUITY = "common_equity"


class ScopeKind(StrEnum):
    """The one scope mechanism (CS-3): a single Unit, or the whole Investment.
    There is no portfolio-specific or mixed-use-specific scope."""

    UNIT = "unit"
    INVESTMENT = "investment"


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionScope:
    """Where a position's claim sits: ``UNIT`` with exactly one nonblank
    ``unit_id``, or ``INVESTMENT`` with none.

    Structural subordination (CS-4) follows from the scope alone. A Unit-scoped
    position is paid from that Unit's cash. An Investment-scoped position is
    paid only from cash that has cleared every Unit-scoped position of every
    Unit. Shape only."""

    kind: ScopeKind
    unit_id: str | None


class ShortfallResolution(StrEnum):
    """How a contractual claim that the available cash cannot meet is satisfied
    (P-14, CS-7 FR-2; the P7.7 Section 21.3 decision). Exactly two ship.

    - ``COMMON_EQUITY_CONTRIBUTION``: the claim is paid in full; the shortfall
      is met by an additional common-equity contribution of exactly the
      shortfall. **This is not a global rule.** In P7.7 only the legacy
      acquisition loan states it, because it is that loan's frozen D6
      treatment (FR-5).
    - ``UNRESOLVED``: only the available cash is paid; the rest of the claim
      stays unpaid, and every figure downstream of it is incomplete.

    **There is no default.** Every position that can face a contractual
    shortfall names its resolution, and none is inferred. Reserve draws,
    protective advances, PIK cures, cash traps and default remedies are later,
    separately ratified mechanisms."""

    COMMON_EQUITY_CONTRIBUTION = "common_equity_contribution"
    UNRESOLVED = "unresolved"


class AccrualConvention(StrEnum):
    """How unpaid preferred return accrues, where the terms permit accrual
    (FR-4, Q21). Always explicit, never assumed; extensible by ratification."""

    SIMPLE = "simple"
    ANNUAL_COMPOUND = "annual_compound"


@dataclass(frozen=True, slots=True, kw_only=True)
class FixedAmount:
    """A funding of exactly ``amount`` nominal dollars."""

    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PctOfPrice:
    """A funding of ``pct`` of the purchase price of the position's scope."""

    pct: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PctOfValue:
    """A funding of ``pct`` of the value at the valuation timepoint
    ``timepoint_id`` (Section 11.3). Representable now. Valuation timepoints
    arrive in a later gate, so nothing values this rule in P7.7."""

    timepoint_id: str
    pct: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceProceeds:
    """Refinance & Capital Events V1 (Section 6.6): the funding of a
    replacement debt position, sized by the refinance event
    ``capital_event_id`` at that event's model month. It states no amount: the
    event's enabled constraints decide it for each variant, and it is valid
    only on the one funding event of the position that event names as its
    replacement."""

    capital_event_id: str


FundingAmountRule = FixedAmount | PctOfPrice | PctOfValue | RefinanceProceeds


@dataclass(frozen=True, slots=True, kw_only=True)
class FundingEvent:
    """One timed funding of a position (Section 12.2; CS-8).

    - ``event_id``: stable, opaque and nonblank. It is unique across every
      funding event and fee of a Capital Structure, which share one
      capital-event namespace.
    - ``model_month``: the D6 Section 4 model month; ``0`` is closing. No
      annual period is built into the contract.
    - ``sequence``: the explicit order among one position's events in the same
      model month (P-7). It is never inferred from list position.
    - ``amount_rule``: ``FixedAmount``, ``PctOfPrice`` or ``PctOfValue``."""

    event_id: str
    model_month: int
    sequence: int
    amount_rule: FundingAmountRule


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionFee:
    """One fee of a position, at a model month. A financing cost belongs to its
    position and is never an Investment transaction cost (TC-4).
    ``description`` is reporting only; no fee kind alters a calculation."""

    fee_id: str
    description: str
    amount: float
    model_month: int
    sequence: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DebtTerms:
    """The typed terms of a debt position (Section 12.2). Structural only in
    P7.7: nothing sizes, amortizes or pays a ``DebtTerms`` position yet.

    - ``interest_rate``: the annual contract rate.
    - ``amortization`` and ``io_period``: whole years, exactly as on
      ``AcquisitionTerms``, so that a later debt position reuses the unchanged
      ``anchor.engine.debt`` functions through thin wrappers.
    - ``maturity_month``: the legal maturity, as a model month.
    - ``fees``: the position's own fees.
    - ``current_pay_rate`` and ``pik_rate``: the cash-pay and the accruing
      portions of the coupon. How they combine is a later gate's convention;
      a positive ``pik_rate`` is the only way these terms permit accrual."""

    interest_rate: float
    amortization: int
    io_period: int
    maturity_month: int
    fees: tuple[PositionFee, ...]
    current_pay_rate: float
    pik_rate: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PreferredEquityTerms:
    """The typed terms of a preferred equity position (Section 12.2, FR-4,
    Q21). Structural only in P7.7: no preferred return is paid or accrued.

    ``accrual_permitted`` is explicit. When it is ``True``, the
    ``accrual_convention`` must be named, because there is no default. When it
    is ``False``, there is no convention, and accrual is never inferred."""

    preferred_rate: float
    current_pay_rate: float
    accrual_permitted: bool
    accrual_convention: AccrualConvention | None
    redemption_month: int


PositionTerms = DebtTerms | PreferredEquityTerms


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalPosition:
    """One authored source of capital with a claim on the cash (Sections 6 and
    12.2). Shape only; ``validation`` holds every rule:

    - ``position_id``: stable, opaque, nonblank and unique. It never uses the
      reserved legacy prefix.
    - ``name``: analyst display text. It never reaches a calculation.
    - ``position_class`` and ``terms``, paired exactly: debt classes carry
      ``DebtTerms``, preferred equity carries ``PreferredEquityTerms``, and
      common equity carries none, because its economics are the Partnership's
      (Section 13).
    - ``priority``: the explicit rank within the scope; lower is more senior.
      It is unique within a scope and never inferred from list order (P-7).
    - ``scope``: ``UNIT(unit_id)`` or ``INVESTMENT``.
    - ``funding``: one or more timed events for a claim-bearing position, and
      none for common equity, which is the residual.
    - ``shortfall_resolution``: required and explicit for every claim-bearing
      position. It is ``None`` only for common equity, which has no
      contractual claim to fall short on. No default exists.

    P7.7 executes no authored position."""

    position_id: str
    name: str
    position_class: PositionClass
    priority: int
    scope: PositionScope
    funding: tuple[FundingEvent, ...]
    terms: PositionTerms | None
    shortfall_resolution: ShortfallResolution | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalStructure:
    """A set of authored positions. The empty structure is today's behavior:
    each Unit's acquisition loan and the residual common equity (P-11).

    ``positions`` is presentation-ordered only. The economic order is scope,
    then priority (``validation.economic_order``). Not persisted in P7.7."""

    positions: tuple[CapitalPosition, ...]


# =============================================================================
# Deterministic issues
# =============================================================================


class CapitalStructureIssueCode(StrEnum):
    """Stable, machine-readable reasons a Capital Structure is invalid, or is
    refused by the P7.7 executor (``UNSUPPORTED_POSITION``)."""

    INVALID_STRUCTURE = "invalid_structure"
    INVALID_POSITION = "invalid_position"
    INVALID_POSITION_ID = "invalid_position_id"
    RESERVED_IDENTITY = "reserved_identity"
    DUPLICATE_POSITION_ID = "duplicate_position_id"
    INVALID_NAME = "invalid_name"
    UNKNOWN_POSITION_CLASS = "unknown_position_class"
    INVALID_PRIORITY = "invalid_priority"
    DUPLICATE_PRIORITY = "duplicate_priority"
    INVALID_SCOPE = "invalid_scope"
    FOREIGN_UNIT_SCOPE = "foreign_unit_scope"
    INVALID_FUNDING = "invalid_funding"
    INVALID_FUNDING_EVENT = "invalid_funding_event"
    INVALID_AMOUNT_RULE = "invalid_amount_rule"
    INVALID_FEE = "invalid_fee"
    DUPLICATE_EVENT_ID = "duplicate_event_id"
    DUPLICATE_EVENT_ORDER = "duplicate_event_order"
    CLASS_TERMS_MISMATCH = "class_terms_mismatch"
    INVALID_DEBT_TERMS = "invalid_debt_terms"
    INVALID_PREFERRED_EQUITY_TERMS = "invalid_preferred_equity_terms"
    MISSING_SHORTFALL_RESOLUTION = "missing_shortfall_resolution"
    INVALID_SHORTFALL_RESOLUTION = "invalid_shortfall_resolution"
    INVESTMENT_SENIOR_DEBT_WITH_ACQUISITION_LOAN = "investment_senior_debt_with_acquisition_loan"
    UNSUPPORTED_POSITION = "unsupported_position"
    #: Refinance & Capital Events V1 (Section 15.1), appended so every
    #: pre-existing member keeps its place: authoring faults wholly inside a
    #: Capital Structure that carries a refinance event, or a ``RefinanceProceeds``
    #: funding. None of them can arise from a structure without either.
    INVALID_CAPITAL_EVENT = "invalid_capital_event"
    UNSUPPORTED_CAPITAL_EVENT_KIND = "unsupported_capital_event_kind"
    EVENT_MONTH_NOT_HOLD_YEAR_END = "event_month_not_hold_year_end"
    UNSUPPORTED_EVENT_SEQUENCE = "unsupported_event_sequence"
    DUPLICATE_CAPITAL_EVENT_ID = "duplicate_capital_event_id"
    MULTIPLE_REFINANCES_IN_SCOPE = "multiple_refinances_in_scope"
    NO_RETIRING_POSITION = "no_retiring_position"
    RETIRING_POSITION_NOT_FOUND = "retiring_position_not_found"
    RETIRING_POSITION_DUPLICATED = "retiring_position_duplicated"
    RETIRING_POSITION_SCOPE_MISMATCH = "retiring_position_scope_mismatch"
    RETIRING_POSITION_NOT_DEBT = "retiring_position_not_debt"
    REPLACEMENT_POSITION_NOT_FOUND = "replacement_position_not_found"
    REPLACEMENT_POSITION_NOT_DEBT = "replacement_position_not_debt"
    REPLACEMENT_SCOPE_MISMATCH = "replacement_scope_mismatch"
    REPLACEMENT_FUNDING_MISMATCH = "replacement_funding_mismatch"
    ORPHANED_REFINANCE_PROCEEDS = "orphaned_refinance_proceeds"
    REPLACEMENT_PRIORITY_NOT_SUCCESSOR = "replacement_priority_not_successor"
    REPLACEMENT_MATURITY_TOO_EARLY = "replacement_maturity_too_early"
    REPLACEMENT_FEE_TIMING = "replacement_fee_timing"
    NO_SIZING_CONSTRAINT = "no_sizing_constraint"
    INVALID_FIXED_CAP = "invalid_fixed_cap"
    INVALID_MAX_LTV = "invalid_max_ltv"
    INVALID_MIN_DSCR = "invalid_min_dscr"
    VALUATION_REFERENCE_REQUIRED = "valuation_reference_required"
    VALUATION_REFERENCE_UNUSED = "valuation_reference_unused"
    DSCR_ZERO_FIRST_YEAR_SERVICE = "dscr_zero_first_year_service"
    INVALID_RETIRING_LENDER_FEE_RECIPIENT = "invalid_retiring_lender_fee_recipient"
    INVALID_COST_LINE = "invalid_cost_line"


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalStructureIssue:
    """One deterministic reason. ``position_id`` names the position concerned
    where one is identifiable; ``field`` locates the finding within it."""

    code: CapitalStructureIssueCode
    message: str
    position_id: str | None = None
    field: str | None = None

    def __str__(self) -> str:
        return self.message


def _issue_tuple(issues: Iterable[CapitalStructureIssue], error: str) -> tuple[CapitalStructureIssue, ...]:
    ordered = tuple(issues)
    if not ordered:
        raise ValueError(f"{error} requires at least one issue.")
    if not all(isinstance(issue, CapitalStructureIssue) for issue in ordered):
        raise TypeError("issues must contain only CapitalStructureIssue instances.")
    return ordered


class CapitalStructureValidationError(ValueError):
    """An invalid Capital Structure: one ordered collection of
    ``CapitalStructureIssue``. Nothing is analysed for it, and nothing is
    repaired."""

    def __init__(self, issues: Iterable[CapitalStructureIssue]) -> None:
        self.issues = _issue_tuple(issues, "CapitalStructureValidationError")
        super().__init__("\n".join(issue.message for issue in self.issues))


class UnsupportedCapitalPositionError(ValueError):
    """A valid Capital Structure holding an authored position that P7.7 does not
    execute. The executor fails closed: nothing is ignored, and nothing is
    partially analysed. One ``UNSUPPORTED_POSITION`` issue per position, in
    economic order."""

    def __init__(self, issues: Iterable[CapitalStructureIssue]) -> None:
        self.issues = _issue_tuple(issues, "UnsupportedCapitalPositionError")
        super().__init__("\n".join(issue.message for issue in self.issues))


class CapitalStructureError(RuntimeError):
    """The foundation was handed incoherent completed results, or a claim it
    cannot settle: a result that does not span the hold its terms state, Units
    that are not the ones consolidated, or a claim without an explicit
    resolution. Reaching this is a programming error, never an analyst
    finding. It is not a ``ValueError``, so no caller can mistake it for an
    invalid Capital Structure."""


# =============================================================================
# Funding Requirements
# =============================================================================


class TimingBasis(StrEnum):
    """How honestly a period is timed (CS-8).

    - ``MODEL_MONTH``: an exact contractual model month (D6 Section 4).
    - ``HOLD_YEAR``: an annual availability bucket. Hold year ``y`` spans model
      months ``12(y-1)+1 .. 12y``; the cash available within it is known only
      annually. A shortfall reported here never claims an exact month."""

    MODEL_MONTH = "model_month"
    HOLD_YEAR = "hold_year"


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelMonthPeriod:
    """An exact contractual model month; ``0`` is closing."""

    basis: ClassVar[TimingBasis] = TimingBasis.MODEL_MONTH
    model_month: int


@dataclass(frozen=True, slots=True, kw_only=True)
class HoldYearPeriod:
    """An annual availability bucket: hold year ``hold_year`` (``>= 1``)."""

    basis: ClassVar[TimingBasis] = TimingBasis.HOLD_YEAR
    hold_year: int


ClaimPeriod = ModelMonthPeriod | HoldYearPeriod


class FundingRequirementStatus(StrEnum):
    """Whether a Funding Requirement's resolution satisfied the claim."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractualClaim:
    """One claim due to one position in one period, with the eligible cash
    already stated: what ``foundation.settle_claim`` settles. The caller finds
    the cash; settlement never discovers NOI, owner cash flow or debt service.

    - ``claim_due``: the contractual amount due; finite and ``>= 0``.
    - ``cash_available``: the eligible cash available to this claim; finite and
      ``>= 0``, because only nonnegative cash can service a claim.
    - ``shortfall_resolution``: required, with no default."""

    position_id: str
    scope: PositionScope
    period: ClaimPeriod
    claim_due: float
    cash_available: float
    shortfall_resolution: ShortfallResolution


@dataclass(frozen=True, slots=True, kw_only=True)
class FundingRequirement:
    """A contractual claim the eligible cash could not meet (FR-1): claim
    shortfall reporting. It is not the D6 Net Additional Equity Requirement,
    which reports every negative Equity Cash Flow year whatever its cause.

    - ``requirement_id``: deterministic provenance,
      ``<position_id>/<basis>/<period>``.
    - ``claim_amount``: the contractual claim due in ``period``.
    - ``cash_available``: the eligible cash that was available to it.
    - ``claim_paid_from_cash``: equal to ``cash_available`` (all of it went to
      the claim).
    - ``amount``: the shortfall, ``claim_amount - cash_available``, ``> 0``.
    - ``equity_contribution``: the shortfall under
      ``COMMON_EQUITY_CONTRIBUTION``; ``0.0`` otherwise. Never invented.
    - ``unpaid_claim_amount``: ``0.0`` once resolved; the shortfall while
      unresolved. Never written off.
    - ``resolution``, ``status`` and a deterministic ``explanation``."""

    requirement_id: str
    position_id: str
    scope: PositionScope
    period: ClaimPeriod
    claim_amount: float
    cash_available: float
    claim_paid_from_cash: float
    amount: float
    equity_contribution: float
    unpaid_claim_amount: float
    resolution: ShortfallResolution
    status: FundingRequirementStatus
    explanation: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimSettlement:
    """What happened to one ``ContractualClaim``.

    ``claim_paid`` is the total paid on the claim: all of it unless the
    shortfall is unresolved. ``funding_requirement`` is ``None`` when the
    eligible cash covered the claim."""

    claim: ContractualClaim
    claim_paid: float
    claim_paid_from_cash: float
    equity_contribution: float
    unpaid_claim_amount: float
    funding_requirement: FundingRequirement | None


# =============================================================================
# The legacy acquisition loan
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacyAcquisitionLoan:
    """One Unit's existing acquisition loan, adapted as that Unit's priority-1
    senior debt (Section 12.4). Read only: ``AcquisitionTerms``,
    ``anchor.engine.debt`` and ``AcquisitionResults`` keep owning it.

    **Financial figures come from ``AcquisitionResults``, the one authority**,
    and are never recomputed: ``loan_amount`` (also the closing ``funding``
    event), the ``financing_fee`` (a closing fee), ``annual_debt_service`` and
    ``remaining_loan_balance``.

    **Descriptive only, from ``AcquisitionTerms``**: ``interest_rate``,
    ``amortization``, ``io_period`` and ``hold_period``.

    ``modeled_payoff_month`` is ``12 x hold_period``: the model month of the
    modeled sale, when Anchor repays whatever balance remains. It is **not**
    the loan's legal maturity. The acquisition model records no maturity, so
    there is deliberately no maturity field. There are no ``current_pay_rate``
    or ``pik_rate`` fields either: the acquisition model states no such terms,
    and none is fabricated.

    ``shortfall_resolution`` is always ``COMMON_EQUITY_CONTRIBUTION``. Debt
    service is always paid, and a negative Levered Owner Cash Flow is
    common equity's (FR-5). That is this loan's own term, never a default for
    any other position."""

    position_id: str
    position_class: PositionClass
    scope: PositionScope
    priority: int
    shortfall_resolution: ShortfallResolution
    funding: FundingEvent
    financing_fee: PositionFee
    loan_amount: float
    annual_debt_service: tuple[float, ...]
    remaining_loan_balance: float
    modeled_payoff_month: int
    interest_rate: float
    amortization: int
    io_period: int
    hold_period: int


# =============================================================================
# The pre-capital-structure handoff: named cash authorities
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitCashAuthority:
    """One Unit's existing cash authorities, named for where each sits relative
    to its acquisition loan (Section 12.4, the P7.7 handoff invariant). Each is
    the completed result's own series, passed through; nothing is derived.

    - ``pre_acquisition_debt_cash_flows``: ``AcquisitionResults.unlevered_cash_flows``.
      Property and Business Plan economics before any financing. Its ``t >= 1``
      entries are the cash available to the acquisition loan's claims; the
      final one includes the pre-debt sale cash, Gross Exit Value less
      Disposition Costs.
    - ``post_acquisition_debt_cash_flows``: ``AcquisitionResults.levered_cash_flows``.
      After the acquisition loan, applied exactly once. Today's Common Equity
      Cash Flow.
    - ``owner_cash_flow_after_acquisition_debt_by_year`` and
      ``net_sale_proceeds_after_acquisition_debt``: the Levered Owner Cash Flow
      and Net Sale Proceeds. A later Unit-scoped junior position reads these
      (CS-6), never the pre-debt series, so the acquisition loan is never
      subtracted twice."""

    unit_id: str
    pre_acquisition_debt_cash_flows: tuple[float, ...]
    post_acquisition_debt_cash_flows: tuple[float, ...]
    owner_cash_flow_after_acquisition_debt_by_year: tuple[float, ...]
    net_sale_proceeds_after_acquisition_debt: float


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentScopeCashAuthority:
    """The only cash an Investment-scoped position may read: what has cleared
    every Unit-scoped position of every Unit and the Investment-level channels
    (CS-4, CS-6). Today that is ``ConsolidatedResults``' levered figures, which
    are downstream of each Unit's acquisition loan, its Business Plan, the
    Investment Business Plan and the transaction costs.

    There is deliberately no unlevered field. An Investment-scoped position
    never starts from ``ConsolidatedResults.unlevered_cash_flows`` while Unit
    acquisition loans exist."""

    unit_ids: tuple[str, ...]
    cash_flows_after_unit_positions: tuple[float, ...]
    owner_cash_flow_after_unit_positions_by_year: tuple[float, ...]
    net_sale_proceeds_after_unit_positions: float


# =============================================================================
# Facade inputs and results
# =============================================================================


class CapitalStructureStatus(StrEnum):
    """Whether the Capital Structure economics are complete.

    ``UNRESOLVED_FUNDING`` (incomplete): at least one Funding Requirement is
    unresolved. Upstream Property, Business Plan and consolidated project
    results stay valid; what depends on the unpaid claim is not reported."""

    COMPLETE = "complete"
    UNRESOLVED_FUNDING = "unresolved_funding"
    #: Refinance & Capital Events V1 (Section 15.4), appended: a configured
    #: refinance could not execute for this variant (unavailable or not
    #: executable), so the Common Equity after it is unknowable. Upstream
    #: results stay valid.
    REFINANCE_UNAVAILABLE = "refinance_unavailable"


class CommonEquityUnavailableReason(StrEnum):
    """Why the Common Equity Cash Flow is not reported (P-9). Later position
    returns downstream of the same point report N/A with this reason."""

    UNRESOLVED_FUNDING_REQUIREMENT = "unresolved_funding_requirement"
    #: Refinance & Capital Events V1 (Section 6.8), appended.
    REFINANCE_UNAVAILABLE = "refinance_unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class CommonEquityOutcome:
    """The residual after a Capital Structure: the Common Equity Cash Flow, or
    ``None`` with a deterministic reason naming every unresolved requirement.
    Never zero-filled, never partial."""

    status: CapitalStructureStatus
    common_equity_cash_flows: tuple[float, ...] | None
    unavailable_reason: CommonEquityUnavailableReason | None
    unavailable_message: str | None
    unresolved_requirement_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalStructureUnit:
    """One Unit as the Investment facade receives it: its ``unit_id``, the
    *resolved* ``AcquisitionTerms`` its engine ran with, and its completed
    ``AcquisitionResults``."""

    unit_id: str
    terms: AcquisitionTerms
    results: AcquisitionResults


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitCapitalStructureResult:
    """The Capital Structure foundation of one completed Unit: its adapted
    acquisition loan (``None`` without one), the loan's Funding Requirements,
    its named cash authorities and the Common Equity Cash Flow."""

    unit_id: str
    status: CapitalStructureStatus
    legacy_acquisition_loan: LegacyAcquisitionLoan | None
    funding_requirements: tuple[FundingRequirement, ...]
    cash_authority: UnitCashAuthority
    common_equity_cash_flows: tuple[float, ...] | None
    common_equity_unavailable_reason: CommonEquityUnavailableReason | None
    common_equity_unavailable_message: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentCapitalStructureResult:
    """The Capital Structure foundation of a visible Investment. Every adapted
    loan is Unit-scoped, in ascending ``unit_id`` order; every Funding
    Requirement is its own Unit's; and the Common Equity Cash Flow is read at
    the Investment-scope cash authority."""

    unit_ids: tuple[str, ...]
    status: CapitalStructureStatus
    legacy_acquisition_loans: tuple[LegacyAcquisitionLoan, ...]
    funding_requirements: tuple[FundingRequirement, ...]
    unit_cash_authorities: tuple[UnitCashAuthority, ...]
    investment_cash_authority: InvestmentScopeCashAuthority
    common_equity_cash_flows: tuple[float, ...] | None
    common_equity_unavailable_reason: CommonEquityUnavailableReason | None
    common_equity_unavailable_message: str | None
