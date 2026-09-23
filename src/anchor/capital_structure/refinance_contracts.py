"""Refinance & Capital Events V1 -- the refinance result contracts.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 6.8, 8.4,
11 and 15.2 (ratified); that document governs on any discrepancy. Shapes only.

**Additive by subclass, so nothing leaks.** Contract Section 6.8 adds the
refinance results, the Common Equity recurring / event decomposition and the
capital-event results to the structured result, "omitted from the wire and
from the fingerprint when no event exists". The API serializes every field of
every dataclass it is handed. So the additions live on two subclasses that are
produced **only** when a structure states a refinance:

- ``RefinancedCommonEquityReturns`` adds ``recurring_cash_flows`` and
  ``event_cash_flows`` to ``CommonEquityReturns``;
- ``RefinancedCapitalResult`` adds ``capital_events`` to
  ``StructuredCapitalResult``.

Every analysis without a refinance returns exactly the classes, fields and
values it returned before, which is how no-refinance byte parity holds by
construction rather than by a presentation filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .contracts import PositionClass, PositionScope
from .events import CapitalEventKind, RetiringPositionRef
from .execution_contracts import CommonEquityReturns, PositionUnavailableReason, StructuredCapitalResult
from ..valuation.contracts import ValuationAvailability, ValuationMethodKind, ValuationUnavailableReason

#: Constraint ties are decided within this relative tolerance of the executed
#: gross proceeds (Section 9.6). It absorbs floating-point representation only
#: -- nine orders of magnitude below a cent -- and never alters the proceeds.
BINDING_TIE_RELATIVE_TOLERANCE = 1e-9

#: A binding DSCR must be met by the executed schedule within this relative
#: tolerance (Section 9.3); anything less is an engine defect.
ACHIEVED_DSCR_RELATIVE_TOLERANCE = 1e-9


class RefinanceStatus(StrEnum):
    """What a configured refinance did for one variant (Sections 6.8, 8.4)."""

    EXECUTED = "executed"
    UNAVAILABLE = "unavailable"
    NOT_EXECUTABLE = "not_executable"
    BLOCKED = "blocked"


class RefinanceUnavailableReason(StrEnum):
    """Why a configured refinance did not execute for this variant (Section
    15.2). Each depends on a fact outside the Capital Structure, so the
    analysis succeeds and the event reports it."""

    EVENT_OUTSIDE_HOLD_HORIZON = "event_outside_hold_horizon"
    TIMEPOINT_NOT_FOUND = "timepoint_not_found"
    MODEL_MONTH_MISMATCH = "model_month_mismatch"
    SCOPE_NOT_COVERED = "scope_not_covered"
    VALUATION_UNAVAILABLE = "valuation_unavailable"
    EVIDENCE_NOT_APPROVED = "evidence_not_approved"
    FORWARD_NOI_UNAVAILABLE = "forward_noi_unavailable"
    NON_POSITIVE_FORWARD_NOI = "non_positive_forward_noi"
    RETIRING_POSITION_ABSENT = "retiring_position_absent"
    RETIRING_POSITION_NOT_OUTSTANDING = "retiring_position_not_outstanding"
    NON_POSITIVE_CAPACITY = "non_positive_capacity"
    UPSTREAM_UNRESOLVED_FUNDING = "upstream_unresolved_funding"


class ConstraintKind(StrEnum):
    """The sizing constraints, in canonical order (Section 6.4)."""

    FIXED_CAP = "fixed_cap"
    MAX_LTV = "max_ltv"
    MIN_DSCR = "min_dscr"


class ConstraintAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class BridgeDirection(StrEnum):
    """The sign of the net event cash: a Common Equity distribution, an
    explicit Common Equity contribution, or a computed zero (Section 11.1)."""

    DISTRIBUTION = "distribution"
    CONTRIBUTION = "contribution"
    ZERO = "zero"


class PayoffAuthority(StrEnum):
    """Where a retiring position's payoff came from (Section 10.2): its own
    accepted P7.8 schedule, or the engine's acquisition-debt balance service."""

    AUTHORED_SCHEDULE = "authored_schedule"
    ACQUISITION_DEBT_BALANCE_SERVICE = "acquisition_debt_balance_service"


@dataclass(frozen=True, slots=True, kw_only=True)
class FixedCapOperands:
    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class MaxLtvOperands:
    """``capacity = max_ltv x scope_value - continuing_senior_balance``."""

    max_ltv: float
    scope_value: float | None
    continuing_senior_balance: float


@dataclass(frozen=True, slots=True, kw_only=True)
class MinDscrOperands:
    """``service_capacity = forward_noi / min_dscr - continuing_senior_service``
    and ``capacity = service_capacity / first_year_service_per_dollar``."""

    min_dscr: float
    forward_noi: float | None
    continuing_senior_service: float
    service_capacity: float | None
    first_year_service_per_dollar: float


ConstraintOperands = FixedCapOperands | MaxLtvOperands | MinDscrOperands


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintCapacity:
    """One enabled constraint's capacity, or why it is unknowable. ``capacity``
    is ``None`` exactly when ``status`` is ``UNAVAILABLE``; it is never zero
    in place of unknown. A computed capacity may be ``<= 0``."""

    kind: ConstraintKind
    status: ConstraintAvailability
    capacity: float | None
    operands: ConstraintOperands
    unavailable_reason: RefinanceUnavailableReason | None
    unavailable_message: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SizingOutcome:
    """Every enabled capacity in canonical order, and the executed gross
    proceeds: the exact minimum when every capacity is available and that
    minimum is positive, else ``None``. ``binding`` lists every capacity within
    the tie tolerance of the proceeds; ``tie`` is ``len(binding) > 1``."""

    capacities: tuple[ConstraintCapacity, ...]
    gross_proceeds: float | None
    binding: tuple[ConstraintKind, ...]
    tie: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ValueDependency:
    """The value an LTV-enabled refinance consumed (Section 8.1): the resolved
    P7.10 cell for the exact event scope and month. Present exactly when LTV
    is enabled and the timepoint resolved to a cell of that scope."""

    timepoint_id: str
    scope: PositionScope
    model_month: int
    method: ValuationMethodKind | None
    analyst_supplied: bool | None
    status: ValuationAvailability
    value: float | None
    valuation_unavailable_reason: ValuationUnavailableReason | None


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiDependency:
    """The forward NOI a DSCR-enabled refinance consumed (Section 8.3): hold
    year ``forward_year`` of the event scope, from the variant's shared
    NOI-at-month authority. Present exactly when DSCR is enabled."""

    scope: PositionScope
    model_month: int
    forward_year: int
    status: ConstraintAvailability
    forward_noi: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RetiringPayoff:
    """One retiring position at the event month. ``scheduled_payment_at_m`` is
    ordinary year-``y`` service; ``payoff`` is the balance immediately after it,
    settled by the event. ``provider_cash_flows`` is the retiring provider's
    annual series ``t = 0..H`` for the acquisition loan, whose schedule P7.7
    reports only through the sale; an authored retiring position's series is
    its own ``PositionReturns.annual_cash_flows``, and this field is ``None``."""

    ref: RetiringPositionRef
    position_id: str
    scheduled_payment_at_m: float
    payoff: float
    payoff_authority: PayoffAuthority
    retiring_lender_fees: float
    provider_cash_flows: tuple[float, ...] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplacementFunding:
    """The replacement position's funding (Section 6.8)."""

    position_id: str
    funding_month: int
    gross_proceeds: float
    replacement_lender_fees: float
    first_service_month: int
    first_year_service: float
    achieved_ltv: float | None
    achieved_dscr: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceBridge:
    """The event audit bridge (Section 11.1):
    ``net_event_cash = gross_proceeds - payoffs - replacement_lender_fees
    - retiring_lender_fees - third_party_costs``."""

    gross_proceeds: float
    payoffs: float
    replacement_lender_fees: float
    retiring_lender_fees: float
    third_party_costs: float
    net_event_cash: float
    direction: BridgeDirection


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceResult:
    """One configured refinance for one variant. ``funding`` and ``bridge``
    exist only when ``EXECUTED``; ``sizing`` whenever capacities were
    attempted; ``unavailable_reason`` and ``unavailable_message`` otherwise.
    Nothing unknowable is zero."""

    event_id: str
    kind: CapitalEventKind
    label: str
    scope: PositionScope
    model_month: int
    hold_year: int
    status: RefinanceStatus
    value_dependency: ValueDependency | None
    noi_dependency: NoiDependency | None
    sizing: SizingOutcome | None
    payoffs: tuple[RetiringPayoff, ...] | None
    funding: ReplacementFunding | None
    bridge: RefinanceBridge | None
    unavailable_reason: RefinanceUnavailableReason | None
    unavailable_message: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinancedCommonEquityReturns(CommonEquityReturns):
    """Common Equity after a refinance: ``cash_flows`` is
    ``recurring_cash_flows + event_cash_flows``, where ``event_cash_flows``
    carries each executed event's net cash in its event year and ``0.0``
    elsewhere. All three are ``None`` together when Common Equity is
    unavailable. Recurring measures read ``recurring_cash_flows`` only."""

    recurring_cash_flows: tuple[float, ...] | None
    event_cash_flows: tuple[float, ...] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class UnexecutedPosition:
    """An authored position with no schedule at all for this variant: the
    replacement of a refinance that did not execute. Its principal is the
    event's gross proceeds, which are unknowable, so no schedule, return or
    structural metric exists -- and none is reported as zero."""

    position_id: str
    name: str
    position_class: PositionClass
    scope: PositionScope
    priority: int
    event_id: str
    unavailable_reason: PositionUnavailableReason
    unavailable_message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinancedCapitalResult(StructuredCapitalResult):
    """A structured result whose Capital Structure states refinance events:
    one ``RefinanceResult`` per event, in economic order (every Unit scope by
    ``unit_id``, then the Investment scope), and the replacement of each event
    that did not execute, which ``positions`` cannot hold without inventing a
    schedule."""

    capital_events: tuple[RefinanceResult, ...]
    unexecuted_positions: tuple[UnexecutedPosition, ...]


__all__ = [
    "ACHIEVED_DSCR_RELATIVE_TOLERANCE",
    "BINDING_TIE_RELATIVE_TOLERANCE",
    "BridgeDirection",
    "ConstraintAvailability",
    "ConstraintCapacity",
    "ConstraintKind",
    "ConstraintOperands",
    "FixedCapOperands",
    "MaxLtvOperands",
    "MinDscrOperands",
    "NoiDependency",
    "PayoffAuthority",
    "RefinanceBridge",
    "RefinanceResult",
    "RefinanceStatus",
    "RefinanceUnavailableReason",
    "RefinancedCapitalResult",
    "RefinancedCommonEquityReturns",
    "ReplacementFunding",
    "RetiringPayoff",
    "SizingOutcome",
    "UnexecutedPosition",
    "ValueDependency",
]
