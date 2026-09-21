"""Phase 7 Gate P7.10 Stage 2 -- the structured unavailable / N/A adapter.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 6.1,
6.2 and 16; that document governs on any discrepancy. This module is the Stage 2
obligation Section 6.2 names, and nothing else.

**What Stage 1 stopped at.** Stage 1 is a pure engine layer with no API or
presentation surface, so it stops internal execution with the typed
``UnresolvedFundingRequirement`` and reports an unresolved valuation as a typed
``ValuationUnavailableReason``. Neither shape is a wire contract.

**What Stage 2 owes.** Every unresolved valuation and every value-sized funding
state exposed through Stage 2 becomes *one* structured representation carrying:

- a stable typed ``reason_code``;
- a specific analyst-facing ``reason`` naming this scope and this timepoint;
- the affected ``scope_kind`` / ``scope_id`` and ``model_month`` where one
  applies;
- the originating Stage 1 typed reason, preserved rather than flattened.

**What Stage 2 must never do.** No unavailable state here carries an amount, and
there is no code path in this module that can produce one: ``UnavailableState``
declares no numeric field at all, so a fabricated value, a zero collapse or a
purchase-price fallback is not merely forbidden -- it is unrepresentable.

**An expected absence is not an error.** Every state this module builds is a
successful, deterministic answer that the API returns with ``200``. It is never
a ``500``. The converse holds just as strictly: a real programming fault or a
corrupt row is *not* routed through here. ``ValuationError``,
``PersistedDealDataError`` and every other genuine defect keep failing as
errors, because turning a defect into an ordinary "N/A" would hide it from the
analyst and from us.

**N/A, Unavailable and Stale never share a meaning** (Section 16).
``AvailabilityStatus`` keeps them apart, and a stale state always names the
dependency classes that moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..valuation.contracts import (
    InvestmentValuationResult,
    UnitValuationResult,
    UnresolvedFundingReason,
    UnresolvedFundingRequirement,
    ValuationAvailability,
    ValuationScopeKind,
    ValuationUnavailableReason,
)


class AvailabilityStatus(StrEnum):
    """The three states the wire distinguishes (Section 16).

    They are not synonyms and are never collapsed:

    - ``AVAILABLE``: a real value exists and is current.
    - ``UNAVAILABLE``: no value exists, for a named reason. Nothing is shown.
    - ``STALE``: a value exists but the state it was computed against has since
      moved. The value is still readable, and is never presented as current."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


class UnavailableReasonCode(StrEnum):
    """The stable analyst-facing reason codes the wire carries (Section 16).

    The ten Section 16 states, plus the two Stage 1 timing reasons the contract
    names explicitly in Section 5.2 and decision R-B, which would otherwise have
    to be flattened into a less specific code:

    - ``NOT_AUTHORED``: no definition exists for the requested timepoint.
    - ``INCOMPLETE_UNITS``: at least one member Unit has no valid value at this
      model month, so the Investment has none. A partial portfolio sum is never
      presented as the Investment value.
    - ``NON_POSITIVE_FORWARD_NOI``: direct capitalisation has no meaning here.
      The NOI is not floored, smoothed or substituted.
    - ``EVIDENCE_NOT_APPROVED``: an analyst-supplied value names an Evidence
      Reference the analyst has not approved, so the value is not presented as
      a sourced amount.
    - ``VARIANT_INVALID``: the selected Analysis Variant does not resolve.
    - ``FUNDING_REQUIREMENT_UNRESOLVED``: a ``PctOfValue`` funding could not be
      sized. The advance itself is unknown; there is no amount to state.
    - ``RESULT_UNAVAILABLE``: an upstream result the memo cites is unavailable,
      carrying its own existing typed reason.
    - ``STALE_DEPENDENCY``: the state this was computed against has moved.
    - ``NOT_IMPLEMENTED_FOR_SCOPE``: the capability does not exist for this
      scope, and no other scope's figure is relabelled to fill the gap (R-I).
    - ``RESERVED_EXIT_MONTH``: the month asked for is the exit month, whose
      value is the reserved system Exit view and never a stored definition
      (R-B).
    - ``OUTSIDE_HOLD_HORIZON``: the month is beyond this variant's hold. The
      same definition may resolve under a longer hold.
    - ``UNIT_NOT_IN_VARIANT`` / ``UNIT_NOT_VALUED``: the definition and the
      variant disagree about the membership."""

    NOT_AUTHORED = "not_authored"
    INCOMPLETE_UNITS = "incomplete_units"
    NON_POSITIVE_FORWARD_NOI = "non_positive_forward_noi"
    EVIDENCE_NOT_APPROVED = "evidence_not_approved"
    VARIANT_INVALID = "variant_invalid"
    FUNDING_REQUIREMENT_UNRESOLVED = "funding_requirement_unresolved"
    RESULT_UNAVAILABLE = "result_unavailable"
    STALE_DEPENDENCY = "stale_dependency"
    NOT_IMPLEMENTED_FOR_SCOPE = "not_implemented_for_scope"
    RESERVED_EXIT_MONTH = "reserved_exit_month"
    OUTSIDE_HOLD_HORIZON = "outside_hold_horizon"
    UNIT_NOT_IN_VARIANT = "unit_not_in_variant"
    UNIT_NOT_VALUED = "unit_not_valued"


#: Every Stage 1 valuation reason, mapped to the wire code that states it.
#: Explicit and total: a reason with no entry raises rather than defaulting to a
#: vaguer code, so a new Stage 1 reason can never silently arrive on the wire as
#: something less specific than it is.
_VALUATION_REASON_CODES: dict[ValuationUnavailableReason, UnavailableReasonCode] = {
    ValuationUnavailableReason.NOT_AUTHORED: UnavailableReasonCode.NOT_AUTHORED,
    ValuationUnavailableReason.INCOMPLETE_UNITS: UnavailableReasonCode.INCOMPLETE_UNITS,
    ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI: UnavailableReasonCode.NON_POSITIVE_FORWARD_NOI,
    ValuationUnavailableReason.VARIANT_INVALID: UnavailableReasonCode.VARIANT_INVALID,
    ValuationUnavailableReason.UNIT_NOT_IN_VARIANT: UnavailableReasonCode.UNIT_NOT_IN_VARIANT,
    ValuationUnavailableReason.UNIT_NOT_VALUED: UnavailableReasonCode.UNIT_NOT_VALUED,
    ValuationUnavailableReason.OUTSIDE_HOLD_HORIZON: UnavailableReasonCode.OUTSIDE_HOLD_HORIZON,
    ValuationUnavailableReason.RESERVED_EXIT_MONTH: UnavailableReasonCode.RESERVED_EXIT_MONTH,
    ValuationUnavailableReason.NOT_IMPLEMENTED_FOR_SCOPE: UnavailableReasonCode.NOT_IMPLEMENTED_FOR_SCOPE,
}


class UnavailableAdapterError(Exception):
    """A state this adapter has no defined representation for.

    Raised rather than defaulted. A silently vaguer reason code would let a new
    Stage 1 condition reach an analyst as an existing, wrong explanation -- and
    an explanation the reader trusts is worse than none. This is a programming
    error and stays an error."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UnavailableState:
    """One expected, deterministic "there is no value here, and this is why".

    **It declares no amount.** There is deliberately no ``value``, ``amount``,
    ``scope_value`` or ``estimate`` field, so no caller -- present or future --
    can put a fabricated number, a zero or a purchase-price fallback into an
    unavailable state through this shape (Section 6.2).

    ``valuation_reason`` and ``funding_reason`` preserve the originating Stage 1
    typed reason beside the wire code, so the exact engine finding survives the
    trip to the analyst instead of being flattened into it."""

    status: AvailabilityStatus
    reason_code: UnavailableReasonCode
    reason: str
    scope_kind: str | None = None
    scope_id: str | None = None
    model_month: int | None = None
    timepoint_id: str | None = None
    valuation_reason: ValuationUnavailableReason | None = None
    funding_reason: UnresolvedFundingReason | None = None


def valuation_reason_code(reason: ValuationUnavailableReason) -> UnavailableReasonCode:
    """The wire code for one Stage 1 valuation reason.

    Total by construction: an unmapped reason raises rather than falling back to
    a vaguer code."""

    code = _VALUATION_REASON_CODES.get(reason)
    if code is None:
        raise UnavailableAdapterError(
            f"Valuation reason {reason!r} has no analyst-facing reason code. Add an explicit mapping rather than "
            "reporting it as a less specific state."
        )
    return code


def unit_unavailable(result: UnitValuationResult, *, timepoint_id: str) -> UnavailableState:
    """One Unit's unavailable valuation as the structured representation.

    The Stage 1 message is carried through verbatim: it already names the Unit,
    the model month and precisely why there is no value, and rewriting it here
    would create a second, drifting explanation."""

    if result.status is ValuationAvailability.AVAILABLE:
        raise UnavailableAdapterError(
            f"Unit {result.unit_id!r} resolved a value at timepoint {timepoint_id!r}; it has no unavailable state."
        )
    if result.unavailable_reason is None:  # pragma: no cover -- Stage 1 always names a reason
        raise UnavailableAdapterError(f"Unit {result.unit_id!r} is unavailable with no typed reason.")
    return UnavailableState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=valuation_reason_code(result.unavailable_reason),
        reason=result.unavailable_message or "",
        scope_kind=ValuationScopeKind.UNIT.value,
        scope_id=result.unit_id,
        model_month=result.model_month,
        timepoint_id=timepoint_id,
        valuation_reason=result.unavailable_reason,
    )


def investment_unavailable(result: InvestmentValuationResult) -> UnavailableState:
    """One Investment's unavailable valuation as the structured representation.

    An incomplete Investment keeps naming the exact Units and reasons that made
    it unavailable, because Stage 1's own message does; the Investment is never
    reported as a partial sum of the Units that did resolve."""

    if result.status is ValuationAvailability.AVAILABLE:
        raise UnavailableAdapterError(
            f"Valuation timepoint {result.timepoint_id!r} resolved a value; it has no unavailable state."
        )
    if result.unavailable_reason is None:  # pragma: no cover -- Stage 1 always names a reason
        raise UnavailableAdapterError(
            f"Valuation timepoint {result.timepoint_id!r} is unavailable with no typed reason."
        )
    return UnavailableState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=valuation_reason_code(result.unavailable_reason),
        reason=result.unavailable_message or "",
        scope_kind=result.scope_kind.value,
        scope_id=result.investment_id,
        model_month=result.model_month,
        timepoint_id=result.timepoint_id,
        valuation_reason=result.unavailable_reason,
    )


def not_authored(
    *, timepoint_id: str, investment_id: str, message: str | None = None
) -> UnavailableState:
    """A timepoint the Investment does not define. No nearby timepoint is
    substituted for it, and no value is inferred from the purchase price."""

    return UnavailableState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=UnavailableReasonCode.NOT_AUTHORED,
        reason=message
        or (
            f"Investment {investment_id!r} defines no valuation timepoint {timepoint_id!r}. No other timepoint is "
            "used in its place, and no value is inferred from the acquisition price."
        ),
        scope_id=investment_id,
        timepoint_id=timepoint_id,
        valuation_reason=ValuationUnavailableReason.NOT_AUTHORED,
    )


def evidence_not_approved(
    *, timepoint_id: str, unit_id: str, evidence_id: str, model_month: int, detail: str
) -> UnavailableState:
    """An analyst-supplied value whose Evidence Reference is missing or not
    approved (Section 8; R-D).

    The amount the analyst typed is deliberately *not* reported: an unsourced
    external value presented as a valuation is exactly the "silently upgraded to
    a fact" the contract forbids. The state names the evidence so the analyst
    can approve it, and carries no number."""

    return UnavailableState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=UnavailableReasonCode.EVIDENCE_NOT_APPROVED,
        reason=(
            f"Unit {unit_id!r} states an analyst-supplied value at model month {model_month} citing Evidence "
            f"Reference {evidence_id!r}, which {detail}. An analyst-supplied value is reported only against approved "
            "evidence; the stated amount is not shown, and no Anchor valuation is substituted for it."
        ),
        scope_kind=ValuationScopeKind.UNIT.value,
        scope_id=unit_id,
        model_month=model_month,
        timepoint_id=timepoint_id,
    )


def funding_unresolved(requirement: UnresolvedFundingRequirement) -> UnavailableState:
    """A ``PctOfValue`` funding whose dollars are unknowable (Sections 6, 6.2).

    This is the Stage 2 obligation at its sharpest. The advance itself is
    unknown, so there is no claim amount and no cash figure to state -- and
    ``UnavailableState`` has nowhere to put one even if a caller tried. The
    percentage the analyst authored is *not* reported as an amount; it is part
    of Stage 1's own message, which explains the authoring.

    A later Stabilized or Custom valuation that no funding event can consume
    reaches here as ``MODEL_MONTH_MISMATCH``: a product limitation with a named
    reason (Section 6.1), never a zero and never a fallback to the purchase
    price."""

    return UnavailableState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=UnavailableReasonCode.FUNDING_REQUIREMENT_UNRESOLVED,
        reason=requirement.message,
        scope_kind=requirement.scope_kind.value,
        scope_id=requirement.unit_id or requirement.position_id,
        model_month=requirement.model_month,
        timepoint_id=requirement.timepoint_id,
        valuation_reason=requirement.valuation_reason,
        funding_reason=requirement.reason,
    )


def variant_invalid(*, investment_id: str, strategy_id: str, scenario_id: str, detail: str) -> UnavailableState:
    """The selected Analysis Variant does not resolve, so nothing downstream of
    it has a value. The variant's own issues are the detail; no figure is
    computed from a variant that did not resolve."""

    return UnavailableState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=UnavailableReasonCode.VARIANT_INVALID,
        reason=(
            f"Strategy {strategy_id!r} x Scenario {scenario_id!r} does not resolve for Investment "
            f"{investment_id!r}, so it states no valuation and no result: {detail}"
        ),
        scope_id=investment_id,
    )


def not_implemented_for_scope(*, capability: str, scope_kind: str, scope_id: str) -> UnavailableState:
    """A capability that does not exist for this scope (R-I).

    Reported as unavailable and named, never filled in from a different scope:
    no Unit result is ever relabelled as an Investment result."""

    return UnavailableState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=UnavailableReasonCode.NOT_IMPLEMENTED_FOR_SCOPE,
        reason=(
            f"{capability} is not implemented for this scope. No result of another scope is presented in its place."
        ),
        scope_kind=scope_kind,
        scope_id=scope_id,
    )


def stale_dependency(*, detail: str, scope_id: str | None = None) -> UnavailableState:
    """A value that exists but was computed against state that has since moved.

    Distinct from ``UNAVAILABLE`` on purpose (Section 16): the figure is still
    readable and a published version still holds it, but nothing may present it
    as current."""

    return UnavailableState(
        status=AvailabilityStatus.STALE,
        reason_code=UnavailableReasonCode.STALE_DEPENDENCY,
        reason=detail,
        scope_id=scope_id,
    )
