"""Refinance & Capital Events V1 -- the capital-event authoring contracts.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 6.1 to
6.7 (ratified); that document governs on any discrepancy. Shapes only: no
calculation, no validation, no execution.

**Where events live.** A refinance belongs to the ``CAPITAL_STRUCTURE`` domain,
inside the same Capital Structure as its positions. It is carried by
``CapitalStructureWithEvents``, a ``CapitalStructure`` that also states its
events. A plain ``CapitalStructure`` states none, keeps exactly the fields it
always had, and therefore serializes, fingerprints and executes exactly as
before (Section 19). A structure with no event is never represented by the
subclass with an empty tuple: ``CapitalStructureWithEvents`` requires at least
one event, so "no refinance" has one representation.

**Identity is ``event_id``, never ``label``** (Section 6.1). The label is
presentation only and reaches no calculation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .contracts import CapitalStructure, PositionScope


class CapitalEventKind(StrEnum):
    """The capital-event kinds. V1 executes ``REFINANCE`` only; every other
    capital event is deferred (Section 5.2)."""

    REFINANCE = "refinance"


@dataclass(frozen=True, slots=True, kw_only=True)
class EventTiming:
    """When an event occurs (Section 6.2). ``model_month`` is ``12y`` for a
    whole hold year ``y >= 1``; ``sequence`` orders capital events of one scope
    at one model month, and V1 permits exactly ``1``."""

    model_month: int
    sequence: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthoredPositionRef:
    """A retiring authored debt position, by its stable ``position_id``."""

    position_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacyAcquisitionLoanRef:
    """A Unit's adapted acquisition loan, by the Unit it belongs to. The
    reserved identity string is never stored or referenced (P7.7 Section 5)."""

    unit_id: str


RetiringPositionRef = AuthoredPositionRef | LegacyAcquisitionLoanRef


@dataclass(frozen=True, slots=True, kw_only=True)
class FixedProceedsCap:
    """A cap on gross proceeds, in nominal dollars. A limit, never an
    instruction to borrow more than another enabled constraint allows."""

    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class MaxLtvConstraint:
    """The maximum combined debt through the replacement's rank, as a fraction
    of the contemporaneous value: ``0 < max_ltv <= 1``."""

    max_ltv: float


@dataclass(frozen=True, slots=True, kw_only=True)
class MinDscrConstraint:
    """The minimum coverage of forward NOI over the first-year scheduled
    service through the replacement's rank: ``min_dscr > 0``."""

    min_dscr: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceSizing:
    """The enabled constraints. An absent constraint is disabled and has no
    target; at least one must be present."""

    fixed_cap: FixedProceedsCap | None
    max_ltv: MaxLtvConstraint | None
    min_dscr: MinDscrConstraint | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceValuationRef:
    """The P7.10 valuation timepoint an LTV-enabled refinance consumes. Present
    exactly when ``max_ltv`` is (Section 6.5). The value is always resolved for
    the executing variant; nothing is copied into the event."""

    timepoint_id: str


class RefinanceCostKind(StrEnum):
    """An event cost other than a replacement lender fee (which is the
    replacement position's own ``DebtTerms.fees``)."""

    RETIRING_LENDER_FEE = "retiring_lender_fee"
    THIRD_PARTY_COST = "third_party_cost"


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceCostLine:
    """One fixed-dollar event cost at the event month (Section 6.7).
    ``recipient`` names one of the event's retiring positions for a
    ``RETIRING_LENDER_FEE`` and is ``None`` for a ``THIRD_PARTY_COST``.
    ``description`` is presentation only."""

    cost_id: str
    kind: RefinanceCostKind
    amount: float
    recipient: RetiringPositionRef | None
    description: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceEvent:
    """One refinance (Sections 6.1 and 6.3): it retires every ``retiring``
    debt position of ``scope`` at ``timing.model_month`` and funds the authored
    position ``replacement_position_id`` in the same scope by its
    ``RefinanceProceeds`` funding."""

    event_id: str
    kind: CapitalEventKind
    scope: PositionScope
    timing: EventTiming
    label: str
    retiring: tuple[RetiringPositionRef, ...]
    replacement_position_id: str
    sizing: RefinanceSizing
    valuation: RefinanceValuationRef | None
    costs: tuple[RefinanceCostLine, ...]


#: The V1 capital events. ``RefinanceEvent`` is the only member.
CapitalEvent = RefinanceEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalStructureWithEvents(CapitalStructure):
    """A Capital Structure that states capital events beside its positions.
    ``events`` is presentation-ordered only; the economic order of events is
    scope, then model month, then ``sequence``."""

    events: tuple[CapitalEvent, ...]


__all__ = [
    "AuthoredPositionRef",
    "CapitalEvent",
    "CapitalEventKind",
    "CapitalStructureWithEvents",
    "EventTiming",
    "FixedProceedsCap",
    "LegacyAcquisitionLoanRef",
    "MaxLtvConstraint",
    "MinDscrConstraint",
    "RefinanceCostKind",
    "RefinanceCostLine",
    "RefinanceEvent",
    "RefinanceSizing",
    "RefinanceValuationRef",
    "RetiringPositionRef",
]
