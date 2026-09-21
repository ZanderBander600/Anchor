"""Phase 7 Gate P7.8 -- the structured-position execution contracts.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
12.3, 12.6 and 14, and records the P7.8 implementation decisions of
``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md``; those documents
govern on any discrepancy. Like ``anchor.capital_structure.contracts``, this
module performs no calculation of its own.

Three groups:

- **Execution issues.** A structurally valid Capital Structure that the P7.8
  executor does not execute yet: a later funding month, a valuation-based
  amount, debt PIK, a partial-year preferred redemption. Such a contract is
  valid, never malformed, so these are not ``CapitalStructureIssue``\\ s.
- **Schedules.** The resolved funding, the contractual cash-flow events and the
  debt or preferred schedule of one authored position.
- **Results.** One ``PositionReturns`` per authored claim-bearing position, the
  ``CommonEquityReturns`` of the final residual, and the
  ``StructuredCapitalResult`` holding both. This is the position-returns
  namespace (Section 14): nothing here is appended to ``AcquisitionResults`` or
  ``ConsolidatedResults``, and ``AcquisitionResults.levered_irr`` keeps its
  meaning (NS-1).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..engine.contracts import IrrStatus
from .contracts import (
    AccrualConvention,
    CapitalPosition,
    CapitalStructureStatus,
    ClaimSettlement,
    CommonEquityUnavailableReason,
    FixedAmount,
    FundingRequirement,
    LegacyAcquisitionLoan,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    PositionScope,
    ScopeKind,
)

#: The over-funded closing tolerance, in nominal dollars. After every authored
#: closing funding and fee, the analysis root's closing Common Equity flow may
#: reach zero within this tolerance, never turn materially positive: no cash
#: reserve, closing distribution or recapitalization is inferred for excess
#: proceeds.
OVERFUNDED_CLOSING_TOLERANCE = 0.01

# =============================================================================
# Execution issues
# =============================================================================


class ExecutionIssueCode(StrEnum):
    """Stable reasons a structurally valid Capital Structure is not executed by
    the P7.8 executor. Each names a contract the P7.7 validator accepts and a
    later, separately ratified extension may execute."""

    UNSUPPORTED_AMOUNT_RULE = "unsupported_amount_rule"
    UNSUPPORTED_FUNDING_TIMING = "unsupported_funding_timing"
    UNSUPPORTED_FEE_TIMING = "unsupported_fee_timing"
    UNSUPPORTED_DEBT_PIK = "unsupported_debt_pik"
    UNSUPPORTED_DEBT_CURRENT_PAY = "unsupported_debt_current_pay"
    UNSUPPORTED_PREFERRED_CURRENT_PAY = "unsupported_preferred_current_pay"
    UNPERMITTED_PREFERRED_ACCRUAL = "unpermitted_preferred_accrual"
    UNSUPPORTED_REDEMPTION_TIMING = "unsupported_redemption_timing"
    UNSUPPORTED_SCOPE = "unsupported_scope"
    UNSUPPORTED_COMMON_EQUITY_SCOPE = "unsupported_common_equity_scope"
    MULTIPLE_COMMON_EQUITY_MARKERS = "multiple_common_equity_markers"
    CLAIM_BELOW_COMMON_EQUITY = "claim_below_common_equity"
    DUPLICATE_RESULT_EVENT_ID = "duplicate_result_event_id"
    OVERFUNDED_CLOSING = "overfunded_closing"
    #: P7.10 Stage 1, appended so every pre-existing member keeps its place: a
    #: ``PctOfValue`` funding the supplied valuation authority cannot size. The
    #: contract is well formed and the rule is executable -- this variant's
    #: value for that scope is unknowable, so the funding is left unresolved
    #: rather than read as zero. It cannot arise without a P7.10 authority.
    UNRESOLVED_VALUATION_FUNDING = "unresolved_valuation_funding"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionIssue:
    """One deterministic reason a valid contract is not executed.
    ``position_id`` names the position concerned where one is identifiable;
    ``field`` locates the finding within it."""

    code: ExecutionIssueCode
    message: str
    position_id: str | None = None
    field: str | None = None

    def __str__(self) -> str:
        return self.message


class CapitalStructureExecutionError(ValueError):
    """A valid Capital Structure that the executor does not execute: one
    ordered collection of ``ExecutionIssue``. Nothing is analysed, nothing is
    moved to a supported convention, and nothing is partially executed."""

    def __init__(self, issues: Iterable[ExecutionIssue]) -> None:
        ordered = tuple(issues)
        if not ordered:
            raise ValueError("CapitalStructureExecutionError requires at least one issue.")
        if not all(isinstance(issue, ExecutionIssue) for issue in ordered):
            raise TypeError("issues must contain only ExecutionIssue instances.")
        self.issues = ordered
        super().__init__("\n".join(issue.message for issue in ordered))


# =============================================================================
# Funding and events
# =============================================================================


class PriceBasisKind(StrEnum):
    """The acquisition price a percentage funding or a loan-to-price ratio is
    measured against. Only these two exist until valuation timepoints do: it is
    never an as-is, stabilized or market value."""

    UNIT_PURCHASE_PRICE = "unit_purchase_price"
    INVESTMENT_TRANSACTION_PRICE = "investment_transaction_price"


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceBasis:
    """A stated acquisition price: the Unit's resolved
    ``AcquisitionTerms.purchase_price`` or the Investment's
    ``ConsolidatedResults.transaction_price``."""

    kind: PriceBasisKind
    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedFundingEvent:
    """One authored ``FundingEvent`` resolved to dollars. ``price_basis`` is
    the basis a ``PctOfPrice`` rule used, and ``None`` for a ``FixedAmount``.

    P7.10 Stage 1 admits ``PctOfValue`` here, sized from a resolved valuation.
    Its ``price_basis`` is ``None``: a valuation is not an acquisition price,
    and reporting one as the other would be false. The rule itself carries the
    ``timepoint_id`` and ``pct`` it used, and the resolved valuation states the
    value; threading those operands onto this record is Stage 2 work, because
    a new field here would change every existing response."""

    event_id: str
    model_month: int
    sequence: int
    amount_rule: FixedAmount | PctOfPrice | PctOfValue
    price_basis: PriceBasis | None
    amount: float


class PositionCashFlowKind(StrEnum):
    """What one provider-side cash event is. The kind is explicit and is never
    inferred from list order."""

    FUNDING = "funding"
    FEE = "fee"
    SCHEDULED_DEBT_SERVICE = "scheduled_debt_service"
    BALLOON = "balloon"
    PREFERRED_CURRENT_PAY = "preferred_current_pay"
    PREFERRED_REDEMPTION = "preferred_redemption"


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionCashFlowEvent:
    """One contractual cash event of a position, from the provider's side:
    funding advanced is negative; a fee, a debt payment, a balloon, preferred
    current pay and a redemption are positive. Timed at an exact D6 model month;
    ``sequence`` orders events that share a month. A financial result event,
    not a UI event."""

    event_id: str
    position_id: str
    model_month: int
    sequence: int
    kind: PositionCashFlowKind
    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class DebtPositionSchedule:
    """The cash-pay schedule of one authored debt position, from the unchanged
    ``anchor.engine.debt`` functions.

    - ``principal``: the funded amount.
    - ``monthly_rate``, ``n_payments``, ``io_months``, ``io_payment`` and
      ``amortizing_payment``: exactly what those functions return for it.
    - ``maturity_month``: the legal contractual maturity, as stated; never
      rewritten.
    - ``scheduled_full_amortization_month``: ``io_months + n_payments``, when
      the unchanged amortization recurrence reaches exactly zero.
    - ``modeled_payoff_month``: the earliest modeled extinguishment,
      ``min(maturity_month, 12 x hold_period, scheduled_full_amortization_month)``.
      The position is outstanding through it and not after.
    - ``balance_at_payoff``: the remaining principal immediately before the
      balloon, after that month's scheduled payment; ``0.0`` when full
      amortization comes first, and then there is no balloon."""

    principal: float
    interest_rate: float
    monthly_rate: float
    n_payments: int
    io_months: int
    io_payment: float
    amortizing_payment: float
    maturity_month: int
    scheduled_full_amortization_month: int
    modeled_payoff_month: int
    balance_at_payoff: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PreferredAccrualYear:
    """One hold year of a preferred position: its current-pay claim and its
    contractual accrual. The accrual is the scheduled non-current-pay part of
    the preferred return, never a cure for unpaid current pay."""

    hold_year: int
    unreturned_principal: float
    current_pay: float
    beginning_accrued: float
    accrual: float
    ending_accrued: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PreferredPositionSchedule:
    """The schedule of one preferred position. ``accrual_rate`` is
    ``preferred_rate - current_pay_rate``. ``modeled_payoff_month`` is the
    redemption month, or the exit month when the stated redemption falls at or
    after it. ``balance_at_redemption`` is the unreturned principal plus the
    accrued preferred return, immediately before the redemption payment."""

    principal: float
    preferred_rate: float
    current_pay_rate: float
    accrual_rate: float
    accrual_convention: AccrualConvention | None
    redemption_month: int
    modeled_payoff_month: int
    years: tuple[PreferredAccrualYear, ...]
    balance_at_redemption: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ScheduledPosition:
    """One authored claim-bearing position, resolved and scheduled, before any
    cash is settled. ``events`` holds every contractual event in canonical order
    (model month, sequence, event id)."""

    position: CapitalPosition
    price_basis: PriceBasis
    funding: tuple[ResolvedFundingEvent, ...]
    funded_amount: float
    events: tuple[PositionCashFlowEvent, ...]
    debt_schedule: DebtPositionSchedule | None
    preferred_schedule: PreferredPositionSchedule | None
    modeled_payoff_month: int
    balance_at_maturity_or_exit: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionAnnualClaim:
    """Every contractual receipt of one position in one hold year, bundled into
    one claim, because cash availability is annual. ``component_event_ids``
    names the exact model-month events that formed it; ``settlement`` is what
    ``settle_claim`` did with it. At most one per position per hold year, so
    the Funding Requirement identity ``<position>/hold_year/<y>`` never
    collides."""

    position_id: str
    hold_year: int
    claim_due: float
    component_event_ids: tuple[str, ...]
    settlement: ClaimSettlement


# =============================================================================
# Results
# =============================================================================


class PositionResultStatus(StrEnum):
    """Whether a position's returns are complete.

    - ``COMPLETE``: every claim was paid in full.
    - ``UNRESOLVED_FUNDING``: one of its own claims left an unresolved Funding
      Requirement.
    - ``BLOCKED_BY_SENIOR_UNRESOLVED``: a claim senior to it -- in its scope, or
      in a Unit scope an Investment-scoped position depends on -- is unresolved,
      so its cash is unknowable and it is not settled at all."""

    COMPLETE = "complete"
    UNRESOLVED_FUNDING = "unresolved_funding"
    BLOCKED_BY_SENIOR_UNRESOLVED = "blocked_by_senior_unresolved"


class PositionUnavailableReason(StrEnum):
    """Why a position's returns are N/A (P-9)."""

    UNRESOLVED_FUNDING_REQUIREMENT = "unresolved_funding_requirement"
    SENIOR_UNRESOLVED_FUNDING_REQUIREMENT = "senior_unresolved_funding_requirement"


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionReturns:
    """The position returns of one authored debt or preferred position.

    **Identity and schedule.** Its identity, the resolved ``funding`` and
    ``funded_amount``, its debt or preferred schedule, its contractual
    ``cash_flow_events`` (every scheduled event, settled or not) and its
    ``annual_claims``: empty when blocked, and ending at its first unresolved
    claim when it has one, because no later year can be settled without an
    arrears or default convention. Its own Funding Requirements are also in
    ``funding_requirements``.

    **Returns** (``None`` unless ``status`` is ``COMPLETE``, with
    ``unavailable_reason`` and ``unavailable_message`` naming the
    ``blocking_requirement_ids``):

    - ``annual_cash_flows``: the provider series ``t = 0..H``, the
      canonical aggregation of the events into D6 annual periods;
    - ``irr`` / ``irr_status``: ``evaluate_irr`` on that series;
    - ``total_cash_received``: every positive receipt, fees included;
    - ``moic``: ``total_cash_received / funded_amount``, and ``profit``:
      ``total_cash_received - funded_amount``. A fee is never netted against
      the capital advanced.

    **Structure** (closing and contractual facts, reported whatever the cash
    settlement):

    - ``valuation_basis``: the acquisition price of the position's scope;
    - ``attachment_basis``: the funded capital structurally senior to it;
      ``detachment_basis`` = ``last_dollar_basis`` = attachment plus its own
      funded amount; ``attachment_ltv`` / ``detachment_ltv`` against the
      valuation basis, never capped;
    - ``debt_yield_through``: Year-1 NOI of the scope over the last-dollar
      basis;
    - ``coverage_by_year``: NOI of the scope over the cumulative current cash
      service through this position. ``None`` where that service is zero, and
      in every year after the position's modeled payoff year, when it is no
      longer outstanding. ``headline_coverage`` is Year 1 and
      ``minimum_coverage`` the lowest defined year;
    - ``modeled_payoff_month`` and ``balance_at_maturity_or_exit``."""

    position_id: str
    name: str
    position_class: PositionClass
    scope: PositionScope
    priority: int
    status: PositionResultStatus
    unavailable_reason: PositionUnavailableReason | None
    unavailable_message: str | None
    blocking_requirement_ids: tuple[str, ...]

    funding: tuple[ResolvedFundingEvent, ...]
    funded_amount: float
    debt_schedule: DebtPositionSchedule | None
    preferred_schedule: PreferredPositionSchedule | None
    modeled_payoff_month: int
    balance_at_maturity_or_exit: float
    cash_flow_events: tuple[PositionCashFlowEvent, ...]
    annual_claims: tuple[PositionAnnualClaim, ...]
    funding_requirements: tuple[FundingRequirement, ...]

    annual_cash_flows: tuple[float, ...] | None
    irr: float | None
    irr_status: IrrStatus | None
    total_cash_received: float | None
    moic: float | None
    profit: float | None

    valuation_basis: PriceBasis
    attachment_basis: float
    detachment_basis: float
    last_dollar_basis: float
    attachment_ltv: float | None
    detachment_ltv: float | None
    debt_yield_through: float | None
    coverage_by_year: tuple[float | None, ...]
    headline_coverage: float | None
    minimum_coverage: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CommonEquityReturns:
    """The residual after every executable claim: the Common Equity Cash Flow
    and its returns, measured on that final series with the existing
    ``anchor.engine.returns`` functions. It is the Common Equity IRR after
    structured positions, never the project levered IRR.

    ``position_id`` is the authored common-equity marker that names the
    residual, or ``None`` when the residual is implicit; nothing is fabricated.
    ``scope`` is the marker's scope, or the analysis root's. When any Funding
    Requirement is unresolved, ``cash_flows`` and every return are ``None``
    with the P7.7 reason and message."""

    position_id: str | None
    scope: PositionScope
    status: CapitalStructureStatus
    cash_flows: tuple[float, ...] | None
    unavailable_reason: CommonEquityUnavailableReason | None
    unavailable_message: str | None
    irr: float | None
    irr_status: IrrStatus | None
    equity_multiple: float | None
    total_equity_invested: float | None
    total_cash_returned: float | None
    total_profit: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredCapitalResult:
    """The structured Capital Structure economics of one standalone Unit
    (``analysis_scope`` ``UNIT``) or one visible Investment (``INVESTMENT``).

    - ``legacy_acquisition_loans``: each Unit's adapted acquisition loan, read
      only, in ascending ``unit_id`` order.
    - ``positions``: one ``PositionReturns`` per authored claim-bearing
      position, in economic order (every Unit scope, then the Investment
      scope; priority within a scope).
    - ``funding_requirements``: the legacy loans' requirements, then the
      authored positions', in that order.
    - ``common_equity``: the final residual.
    - ``status``: ``UNRESOLVED_FUNDING`` while any requirement is unresolved."""

    analysis_scope: ScopeKind
    unit_ids: tuple[str, ...]
    hold_period: int
    status: CapitalStructureStatus
    legacy_acquisition_loans: tuple[LegacyAcquisitionLoan, ...]
    positions: tuple[PositionReturns, ...]
    funding_requirements: tuple[FundingRequirement, ...]
    common_equity: CommonEquityReturns
