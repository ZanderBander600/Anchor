"""Refinance & Capital Events V1 Stage 2 -- where the persisted analysis meets
the accepted Stage 1 refinance results.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 8.1,
12.5, 14, 15.2, 15.3 and 16.2 (ratified); that document governs on any
discrepancy.

Three narrow jobs, and no calculation. Nothing here sizes, schedules, settles,
sums or compares a money value; every figure is the accepted Stage 1 engine's,
carried through unchanged.

1. **Which valuations a structure consumes, and for which scope** (R-C, R-R).
   Only an LTV-enabled event references a valuation, and it depends on the
   value of its own exact scope. A DSCR-only, fixed-only or fixed-plus-DSCR
   event holds no reference, so it can never name one.
2. **The evidence gate's typed reason** (Section 15.2; Stage 1 record item 10;
   review correction). The evidence-aware authority presents a withheld
   analyst-supplied cell as having no value, so the frozen engine reports its
   generic ``valuation_unavailable``. Which of those the evidence gate caused is
   a typed fact -- the event, its scope, its referenced timepoint and the
   blocked Units -- and this module classifies from those facts alone. It then
   rebuilds, from typed objects, every analyst-facing message that restates the
   event: the event's own, its LTV capacity's, the positions of its scope, its
   unexecuted replacement and Common Equity's. **No message is read, parsed or
   edited:** Stage 1's prose can change without changing any classification
   here, and an event or position this does not concern is returned untouched.
   No amount, status, identity or order changes, and an amount the analyst
   typed is never reported.
3. **The primary return namespace** (R-P, Section 16.2). Every response that
   carries returns for a refinance-bearing variant says, as a typed fact, which
   namespace is primary. The presentation layer then decides nothing
   economically.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from ..capital_structure.contracts import CapitalStructure, PositionScope, ScopeKind
from ..capital_structure.events import CapitalStructureWithEvents, RefinanceEvent
from ..capital_structure.execution_contracts import (
    PositionResultStatus,
    PositionReturns,
    StructuredCapitalResult,
)
from ..capital_structure.funding import valuation_scope
from ..capital_structure.refinance_contracts import (
    ConstraintKind,
    RefinanceResult,
    RefinanceStatus,
    RefinanceUnavailableReason,
    RefinancedCapitalResult,
    UnexecutedPosition,
)
from .valuation_views import scope_evidence_blocked

# =============================================================================
# 1. Consumed valuations: LTV only, exact scope
# =============================================================================


def refinance_valuation_scopes(capital_structure: CapitalStructure) -> tuple[tuple[str, PositionScope], ...]:
    """``(timepoint_id, event scope)`` for every LTV-enabled refinance event,
    in ``event_id`` order. Empty for a structure with no event, and for every
    event that does not size by LTV -- which is what keeps a DSCR-only
    refinance independent of every valuation definition, result and evidence
    approval (INV-18)."""

    if not isinstance(capital_structure, CapitalStructureWithEvents):
        return ()
    return tuple(
        (event.valuation.timepoint_id, event.scope)
        for event in sorted(capital_structure.events, key=lambda item: item.event_id)
        if event.sizing.max_ltv is not None and event.valuation is not None
    )


def refinance_valuation_timepoints(capital_structure: CapitalStructure) -> tuple[str, ...]:
    """Every valuation timepoint an LTV-enabled refinance event references,
    sorted. Only an event whose ``event.sizing.max_ltv is not None`` names one."""

    return tuple(sorted({timepoint_id for timepoint_id, _ in refinance_valuation_scopes(capital_structure)}))


# =============================================================================
# 2. The evidence gate's typed reason, and the messages rebuilt from it
# =============================================================================

_NOT_EXECUTED = frozenset({RefinanceStatus.UNAVAILABLE, RefinanceStatus.NOT_EXECUTABLE})


def _whose_value(scope: PositionScope) -> str:
    """The scope whose analyst-supplied value the gate withheld, named
    without any identity."""

    if scope.kind is ScopeKind.UNIT:
        return "this Unit's analyst-supplied value"
    return "the analyst-supplied value of at least one of the Investment's Units"


def evidence_message(event: RefinanceEvent, *, valuation_label: str) -> str:
    """The event's and its LTV capacity's analyst-facing sentence."""

    return (
        f"'{event.label}' sizes by LTV, but in the valuation '{valuation_label}' {_whose_value(event.scope)} has "
        "no approved Evidence Reference. That amount is not used, and it is never read as zero or replaced by the "
        "purchase price."
    )


def _position_message(event: RefinanceEvent, restated: RefinanceResult) -> str:
    return (
        f"Not reported: its cash after model month {restated.model_month} depends on '{event.label}', which did "
        f"not execute for this variant. {restated.unavailable_message}"
    )


def _common_equity_message(not_executed: tuple[RefinanceResult, ...]) -> str:
    names = ", ".join(f"'{result.label}'" for result in not_executed)
    sentences = [
        f"Common Equity is not reported: refinance {names} did not execute for this variant, so the cash after it "
        "is unknowable. Property, Business Plan and project results are unaffected.",
        *(result.unavailable_message for result in not_executed if result.unavailable_message),
    ]
    return " ".join(sentences)


def _classified(
    result: RefinanceResult,
    event: RefinanceEvent,
    *,
    withheld: Mapping[str, Mapping[str, str]],
    valuation_labels: Mapping[str, str],
) -> RefinanceResult | None:
    """The event's result with ``evidence_not_approved`` stated, or ``None``
    when the evidence gate did not cause any of its unavailability.

    Typed facts only: the event sizes by LTV; the evidence gate withheld a cell
    its **exact scope** depends on (its own Unit's, or any member's for the
    Investment); and the engine reported that LTV capacity unavailable for want
    of the value -- ``valuation_unavailable``, which only the LTV capacity
    produces. The event itself is restated only when that same reason is the
    one it reports; a retirement or other reason that preceded it is kept."""

    reference = event.valuation
    if event.sizing.max_ltv is None or reference is None or result.sizing is None:
        return None
    scope_kind, unit_id = valuation_scope(event.scope)
    if not scope_evidence_blocked(
        withheld, timepoint_id=reference.timepoint_id, scope_kind=scope_kind, unit_id=unit_id
    ):
        return None
    ltv = next((capacity for capacity in result.sizing.capacities if capacity.kind is ConstraintKind.MAX_LTV), None)
    if ltv is None or ltv.unavailable_reason is not RefinanceUnavailableReason.VALUATION_UNAVAILABLE:
        return None
    message = evidence_message(event, valuation_label=valuation_labels.get(reference.timepoint_id, "referenced"))
    capacities = tuple(
        replace(
            capacity,
            unavailable_reason=RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED,
            unavailable_message=message,
        )
        if capacity is ltv
        else capacity
        for capacity in result.sizing.capacities
    )
    restated = replace(result, sizing=replace(result.sizing, capacities=capacities))
    if result.unavailable_reason is RefinanceUnavailableReason.VALUATION_UNAVAILABLE:
        restated = replace(
            restated,
            unavailable_reason=RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED,
            unavailable_message=message,
        )
    return restated


def with_evidence_not_approved(
    result: StructuredCapitalResult,
    *,
    capital_structure: CapitalStructure,
    withheld: Mapping[str, Mapping[str, str]],
    valuation_labels: Mapping[str, str],
) -> StructuredCapitalResult:
    """``result`` with ``evidence_not_approved`` stated wherever the evidence
    gate, and not another fact, left an LTV capacity unknowable -- and every
    message that restates such an event rebuilt from typed objects.

    ``withheld`` is the P7.10 evidence gate's own finding, by ``timepoint_id``
    then ``unit_id``. A result with no refinance, or no event the gate
    affected, is returned as the very same object.

    What is rebuilt, and why exactly that: Stage 1 restates a non-executed
    event's sentence in the positions of **that event's own scope**, in **its
    unexecuted replacement** and in **Common Equity**; an Investment position
    blocked by a Unit event and an upstream Investment event carry sentences
    that name no event's reason, and are left as they are."""

    if not isinstance(result, RefinancedCapitalResult) or not withheld:
        return result
    if not isinstance(capital_structure, CapitalStructureWithEvents):
        return result
    events = {event.event_id: event for event in capital_structure.events}

    restated: dict[str, RefinanceResult] = {}
    for event_result in result.capital_events:
        event = events.get(event_result.event_id)
        if event is None:
            continue
        classified = _classified(event_result, event, withheld=withheld, valuation_labels=valuation_labels)
        if classified is not None:
            restated[event_result.event_id] = classified
    if not restated:
        return result

    # Only an event whose *own* reason became evidence_not_approved changes what
    # the messages that restate it say.
    reason_changed = {
        event_id
        for event_id, event_result in restated.items()
        if event_result.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    }
    capital_events = tuple(restated.get(item.event_id, item) for item in result.capital_events)
    by_scope = {events[event_id].scope: event_id for event_id in reason_changed}

    def _position(position: PositionReturns) -> PositionReturns:
        event_id = by_scope.get(position.scope)
        if event_id is None or position.status is not PositionResultStatus.REFINANCE_UNAVAILABLE:
            return position
        return replace(position, unavailable_message=_position_message(events[event_id], restated[event_id]))

    def _unexecuted(position: UnexecutedPosition) -> UnexecutedPosition:
        if position.event_id not in reason_changed:
            return position
        return replace(
            position,
            unavailable_message=_position_message(events[position.event_id], restated[position.event_id]),
        )

    common_equity = result.common_equity
    not_executed = tuple(item for item in capital_events if item.status in _NOT_EXECUTED)
    if reason_changed & {item.event_id for item in not_executed} and common_equity.cash_flows is None:
        common_equity = replace(common_equity, unavailable_message=_common_equity_message(not_executed))

    return replace(
        result,
        capital_events=capital_events,
        positions=tuple(_position(position) for position in result.positions),
        unexecuted_positions=tuple(_unexecuted(position) for position in result.unexecuted_positions),
        common_equity=common_equity,
    )


# =============================================================================
# 3. The primary return namespace (R-P)
# =============================================================================


class ReturnNamespace(StrEnum):
    """The return namespaces a refinance-bearing variant reports (Sections 12.1
    and 12.5).

    - ``COMMON_EQUITY_AFTER_CAPITAL_STRUCTURE``: the primary current
      underwritten equity return, refinance included.
    - ``PARTNER``: the primary investor return, where a Partnership exists.
    - ``ACQUISITION_FINANCING_REFERENCE``: the Project levered figures -- the
      acquisition loan held through sale, excluding every later capital event.
      A labeled reference only, never a headline."""

    COMMON_EQUITY_AFTER_CAPITAL_STRUCTURE = "common_equity_after_capital_structure"
    PARTNER = "partner"
    ACQUISITION_FINANCING_REFERENCE = "acquisition_financing_reference"


class PrimaryReturnStatus(StrEnum):
    """Whether the primary equity namespace has figures for this variant. When
    it does not, that state *is* the primary answer (Section 12.5 rule 6); the
    acquisition-only figures never stand in for it."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class PrimaryReturnView:
    """The server's typed statement of which return namespace is primary for
    one refinance-bearing variant.

    ``primary_equity_namespace`` is always Common Equity after Capital
    Structure. ``primary_investor_namespace`` is ``PARTNER`` exactly when the
    variant resolves a Partnership, else ``None``. ``reference_namespace`` is the
    acquisition-financing reference, which ``reference_excludes_capital_events``
    states excludes every later capital event.

    ``status`` is the primary equity namespace's own availability, read from
    the Common Equity result; ``unavailable_reason`` and ``unavailable_message``
    are its typed reason and analyst-facing sentence, and are ``None`` exactly
    when it is available. ``capital_event_ids`` and ``executed_event_ids`` name
    every configured event and those that executed, in the result's economic
    order. No figure is carried: every figure is already on the result."""

    primary_equity_namespace: ReturnNamespace
    primary_investor_namespace: ReturnNamespace | None
    reference_namespace: ReturnNamespace
    reference_excludes_capital_events: bool
    status: PrimaryReturnStatus
    unavailable_reason: str | None
    unavailable_message: str | None
    capital_event_ids: tuple[str, ...]
    executed_event_ids: tuple[str, ...]


def primary_return_view(
    result: StructuredCapitalResult, *, partnership_resolved: bool
) -> PrimaryReturnView | None:
    """The primary-return facts of a refinance-bearing result, or ``None`` for
    a result with no capital event -- whose responses stay byte-identical.

    The status reads the typed Common Equity state only (``cash_flows`` present
    or not) and never a message; the acquisition-only figures are never
    consulted, so they cannot become the primary answer."""

    if not isinstance(result, RefinancedCapitalResult) or not result.capital_events:
        return None
    equity = result.common_equity
    available = equity.cash_flows is not None
    return PrimaryReturnView(
        primary_equity_namespace=ReturnNamespace.COMMON_EQUITY_AFTER_CAPITAL_STRUCTURE,
        primary_investor_namespace=ReturnNamespace.PARTNER if partnership_resolved else None,
        reference_namespace=ReturnNamespace.ACQUISITION_FINANCING_REFERENCE,
        reference_excludes_capital_events=True,
        status=PrimaryReturnStatus.AVAILABLE if available else PrimaryReturnStatus.UNAVAILABLE,
        unavailable_reason=None
        if available or equity.unavailable_reason is None
        else equity.unavailable_reason.value,
        unavailable_message=None if available else equity.unavailable_message,
        capital_event_ids=tuple(event.event_id for event in result.capital_events),
        executed_event_ids=tuple(
            event.event_id for event in result.capital_events if event.status is RefinanceStatus.EXECUTED
        ),
    )


__all__ = [
    "PrimaryReturnStatus",
    "PrimaryReturnView",
    "ReturnNamespace",
    "primary_return_view",
    "evidence_message",
    "refinance_valuation_scopes",
    "refinance_valuation_timepoints",
    "with_evidence_not_approved",
]
