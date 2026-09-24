"""Refinance & Capital Events V1 Stage 2 -- where the persisted analysis meets
the accepted Stage 1 refinance results.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 8.1,
12.5, 14, 15.2 and 16.2 (ratified); that document governs on any discrepancy.

Three narrow jobs, and no calculation. Nothing here sizes, schedules, settles,
sums or compares a money value; every figure is the accepted Stage 1 engine's,
carried through unchanged.

1. **Which valuations a structure consumes** (R-C, R-R). Only an LTV-enabled
   event's reference is a consumed dependency. A DSCR-only, fixed-only or
   fixed-plus-DSCR event holds no reference, so it can never name one.
2. **The evidence gate's typed reason** (Section 15.2; Stage 1 record item 10).
   P7.10 Stage 2 withholds an evidence-blocked valuation from the authority the
   executor reads, so the frozen Stage 1 engine can only report that its
   timepoint was not found. That is untrue -- the timepoint is authored -- and
   Section 15.2 names the true reason, ``evidence_not_approved``. This module
   restates exactly that reason and its sentence on the typed fields that carry
   it. No amount, status, identity or order changes, and an amount the analyst
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

from ..capital_structure.contracts import CapitalStructure
from ..capital_structure.events import CapitalStructureWithEvents
from ..capital_structure.execution_contracts import StructuredCapitalResult
from ..capital_structure.refinance_contracts import (
    ConstraintKind,
    RefinanceResult,
    RefinanceStatus,
    RefinanceUnavailableReason,
    RefinancedCapitalResult,
)


# =============================================================================
# 1. Consumed valuations: LTV only
# =============================================================================


def refinance_valuation_timepoints(capital_structure: CapitalStructure) -> tuple[str, ...]:
    """Every valuation timepoint an LTV-enabled refinance event references,
    sorted. Empty for a structure with no event, and for every event that does
    not size by LTV -- which is what keeps a DSCR-only refinance independent of
    every valuation definition, result and evidence approval (INV-18)."""

    if not isinstance(capital_structure, CapitalStructureWithEvents):
        return ()
    return tuple(
        sorted(
            {
                event.valuation.timepoint_id
                for event in capital_structure.events
                if event.sizing.max_ltv is not None and event.valuation is not None
            }
        )
    )


# =============================================================================
# 2. The evidence gate's typed reason
# =============================================================================


def _evidence_message(label: str, valuation_label: str) -> str:
    return (
        f"'{label}' sizes by LTV, but the valuation '{valuation_label}' holds an analyst-supplied value without an "
        "approved Evidence Reference. That amount is not used, and it is never read as zero or replaced by the "
        "purchase price."
    )


def _restated(message: str | None, sentences: Mapping[str, str]) -> str | None:
    """``message`` with each withheld event's sentence restated. Every
    downstream refinance message that names a non-executed event carries that
    event's own sentence verbatim, so only that sentence is replaced."""

    if message is None:
        return None
    for old, new in sentences.items():
        message = message.replace(old, new)
    return message


def with_evidence_not_approved(
    result: StructuredCapitalResult,
    *,
    capital_structure: CapitalStructure,
    withheld: Mapping[str, Mapping[str, str]],
    valuation_labels: Mapping[str, str],
) -> StructuredCapitalResult:
    """``result`` with ``evidence_not_approved`` stated wherever the evidence
    gate, not a missing definition, left an LTV capacity unknowable.

    ``withheld`` is the P7.10 evidence gate's own finding by ``timepoint_id``:
    exactly the timepoints left out of the authority the executor read. A
    timepoint that is genuinely not defined is not in it and keeps
    ``timepoint_not_found``. A result with no refinance, or no withheld
    timepoint, is returned as the very same object."""

    if not isinstance(result, RefinancedCapitalResult) or not withheld:
        return result
    if not isinstance(capital_structure, CapitalStructureWithEvents):
        return result
    references = {
        event.event_id: event.valuation.timepoint_id
        for event in capital_structure.events
        if event.sizing.max_ltv is not None and event.valuation is not None
    }

    sentences: dict[str, str] = {}
    events: list[RefinanceResult] = []
    for event in result.capital_events:
        timepoint_id = references.get(event.event_id)
        if timepoint_id is None or timepoint_id not in withheld or event.sizing is None:
            events.append(event)
            continue
        message = _evidence_message(event.label, valuation_labels.get(timepoint_id, "the referenced valuation"))
        capacities = []
        for capacity in event.sizing.capacities:
            if (
                capacity.kind is ConstraintKind.MAX_LTV
                and capacity.unavailable_reason is RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND
            ):
                if capacity.unavailable_message:
                    sentences[capacity.unavailable_message] = message
                capacity = replace(
                    capacity,
                    unavailable_reason=RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED,
                    unavailable_message=message,
                )
            capacities.append(capacity)
        restated = replace(event, sizing=replace(event.sizing, capacities=tuple(capacities)))
        if event.unavailable_reason is RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND:
            restated = replace(
                restated,
                unavailable_reason=RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED,
                unavailable_message=message,
            )
        events.append(restated)
    if not sentences:
        return result

    return replace(
        result,
        capital_events=tuple(
            replace(event, unavailable_message=_restated(event.unavailable_message, sentences))
            if event.unavailable_reason is not RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
            else event
            for event in events
        ),
        positions=tuple(
            replace(position, unavailable_message=_restated(position.unavailable_message, sentences))
            for position in result.positions
        ),
        unexecuted_positions=tuple(
            replace(position, unavailable_message=_restated(position.unavailable_message, sentences) or "")
            for position in result.unexecuted_positions
        ),
        common_equity=replace(
            result.common_equity,
            unavailable_message=_restated(result.common_equity.unavailable_message, sentences),
        ),
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
    "refinance_valuation_timepoints",
    "with_evidence_not_approved",
]
