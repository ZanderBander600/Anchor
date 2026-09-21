"""Phase 7 Gate P7.10 Stage 1 -- sizing a funding from a resolved valuation.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Section 6 and
the ratified decision R-E; that document governs on any discrepancy.

**One rule, activated -- not a new one.** P7.7 already represents
``PctOfValue(timepoint_id, pct)`` and P7.8 refuses to execute it. This module
values that existing rule. No second amount-rule shape is added, and
``PctOfValue``'s own validation stays exactly where P7.7 put it: ``pct`` finite,
greater than zero and at most one is checked by
``anchor.capital_structure.validation`` and is neither repeated nor relaxed
here.

**Direction.** This module knows nothing about Capital Structures. It reads a
resolved valuation and a position's scope, both passed in, so the dependency
runs one way: Capital Structure reads valuation, valuation reads the engine.

**Never zero.** A funding that does not resolve returns an
``UnresolvedFundingRequirement`` naming exactly why. It is never read as zero,
never estimated, never resized and never silently dropped: a percentage of an
unknown value is unknown, and a position funded by an unknown amount has
unknowable economics.

**No refinancing.** Sizing a closing funding from a valuation is not a
refinancing or a recapitalization. No later funding event, payoff, resizing or
proceeds distribution is introduced here; a future refinance gate may reuse
this same timepoint contract, and its cash-flow semantics need their own
ratification.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engine.contracts import ensure_finite
from .contracts import (
    InvestmentValuationResult,
    ResolvedValuationFunding,
    UnitValuationResult,
    UnresolvedFundingReason,
    UnresolvedFundingRequirement,
    ValuationAvailability,
    ValuationError,
    ValuationFundingResolution,
    ValuationScopeKind,
    ValuationUnavailableReason,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationAuthority:
    """Every resolved valuation of one Investment that a funding may consume.

    ``valuations`` is canonical by ``timepoint_id`` and holds at most one
    result per timepoint. A funding names a timepoint by id; an authority that
    does not hold it resolves nothing, and no nearby timepoint is substituted."""

    investment_id: str
    valuations: tuple[InvestmentValuationResult, ...]

    def find(self, timepoint_id: str) -> InvestmentValuationResult | None:
        for valuation in self.valuations:
            if valuation.timepoint_id == timepoint_id:
                return valuation
        return None


def valuation_authority(
    *, investment_id: str, valuations: tuple[InvestmentValuationResult, ...]
) -> ValuationAuthority:
    """The authority for one Investment, canonicalised by ``timepoint_id``.
    Two results for one timepoint are a programming error: a timepoint has one
    value per variant, and nothing here chooses between them."""

    ordered = tuple(sorted(valuations, key=lambda valuation: valuation.timepoint_id))
    identities = [valuation.timepoint_id for valuation in ordered]
    if len(set(identities)) != len(identities):
        raise ValuationError(
            f"Investment {investment_id!r} supplied two resolved valuations for one timepoint; a timepoint has one "
            "value per Analysis Variant."
        )
    return ValuationAuthority(investment_id=investment_id, valuations=ordered)


def _requirement(
    *,
    event_id: str,
    position_id: str,
    timepoint_id: str,
    scope_kind: ValuationScopeKind,
    unit_id: str | None,
    model_month: int,
    pct: float,
    reason: UnresolvedFundingReason,
    valuation_reason: ValuationUnavailableReason | None,
    message: str,
) -> UnresolvedFundingRequirement:
    return UnresolvedFundingRequirement(
        requirement_id=f"{position_id}/funding/{event_id}",
        event_id=event_id,
        position_id=position_id,
        timepoint_id=timepoint_id,
        scope_kind=scope_kind,
        unit_id=unit_id,
        model_month=model_month,
        pct=pct,
        reason=reason,
        valuation_reason=valuation_reason,
        message=message,
    )


def _scope_value(
    valuation: InvestmentValuationResult, *, scope_kind: ValuationScopeKind, unit_id: str | None
) -> tuple[float | None, UnresolvedFundingReason | None, ValuationUnavailableReason | None, str]:
    """The value of the position's exact scope, or why there is none.

    An Investment-scoped position takes a percentage of the Investment value,
    which exists only when every member Unit does. A Unit-scoped position takes
    a percentage of its own Unit's value: one other Unit missing a value does
    not make that Unit's own value unknown, and its own Unit missing one is
    never covered by the Investment total."""

    if scope_kind is ValuationScopeKind.INVESTMENT:
        if valuation.status is ValuationAvailability.AVAILABLE and valuation.value is not None:
            return valuation.value, None, None, ""
        return (
            None,
            UnresolvedFundingReason.VALUATION_UNAVAILABLE,
            valuation.unavailable_reason,
            valuation.unavailable_message or "",
        )

    if unit_id is None:
        raise ValuationError("A Unit-scoped funding names no Unit.")
    found: UnitValuationResult | None = next(
        (result for result in valuation.unit_results if result.unit_id == unit_id), None
    )
    if found is None:
        return (
            None,
            UnresolvedFundingReason.SCOPE_NOT_COVERED,
            None,
            f"Valuation timepoint {valuation.timepoint_id!r} does not value Unit {unit_id!r}, so it states no value "
            "of this position's scope. The Investment total is never used in its place.",
        )
    if found.status is ValuationAvailability.AVAILABLE and found.value is not None:
        return found.value, None, None, ""
    return (
        None,
        UnresolvedFundingReason.VALUATION_UNAVAILABLE,
        found.unavailable_reason,
        found.unavailable_message or "",
    )


def resolve_pct_of_value_funding(
    *,
    event_id: str,
    position_id: str,
    event_model_month: int,
    timepoint_id: str,
    pct: float,
    scope_kind: ValuationScopeKind,
    unit_id: str | None,
    authority: ValuationAuthority,
) -> ValuationFundingResolution:
    """Size one ``PctOfValue`` funding, or say exactly why it is unknowable.

    The funding resolves only when all of this holds (R-E):

    1. the named timepoint belongs to the same Investment as the funding;
    2. the funding event's model month is the timepoint's model month -- the
       two are never moved to meet;
    3. the valuation covers the position's exact scope;
    4. every value that scope requires is available.

    Then ``amount = pct * scope_value``. Otherwise the Funding Requirement is
    left unresolved with a typed reason, and no amount is reported."""

    valuation = authority.find(timepoint_id)
    if valuation is None:
        return _requirement(
            event_id=event_id,
            position_id=position_id,
            timepoint_id=timepoint_id,
            scope_kind=scope_kind,
            unit_id=unit_id,
            model_month=event_model_month,
            pct=pct,
            reason=UnresolvedFundingReason.TIMEPOINT_NOT_FOUND,
            valuation_reason=ValuationUnavailableReason.NOT_AUTHORED,
            message=(
                f"Funding event {event_id!r} of {position_id!r} is a percentage of the value at valuation timepoint "
                f"{timepoint_id!r}, which Investment {authority.investment_id!r} does not define. No other timepoint "
                "is used in its place."
            ),
        )
    if valuation.investment_id != authority.investment_id:
        return _requirement(
            event_id=event_id,
            position_id=position_id,
            timepoint_id=timepoint_id,
            scope_kind=scope_kind,
            unit_id=unit_id,
            model_month=event_model_month,
            pct=pct,
            reason=UnresolvedFundingReason.FOREIGN_INVESTMENT,
            valuation_reason=None,
            message=(
                f"Valuation timepoint {timepoint_id!r} belongs to Investment {valuation.investment_id!r} and cannot "
                f"size a funding of Investment {authority.investment_id!r}."
            ),
        )
    if valuation.model_month != event_model_month:
        return _requirement(
            event_id=event_id,
            position_id=position_id,
            timepoint_id=timepoint_id,
            scope_kind=scope_kind,
            unit_id=unit_id,
            model_month=event_model_month,
            pct=pct,
            reason=UnresolvedFundingReason.MODEL_MONTH_MISMATCH,
            valuation_reason=None,
            message=(
                f"Funding event {event_id!r} of {position_id!r} funds at model month {event_model_month}, and "
                f"valuation timepoint {timepoint_id!r} values at model month {valuation.model_month}. A funding is "
                "sized from a value of its own model month; neither is moved to the other, and no value is "
                "interpolated between them."
            ),
        )

    value, reason, valuation_reason, message = _scope_value(valuation, scope_kind=scope_kind, unit_id=unit_id)
    if value is None:
        if reason is None:  # pragma: no cover -- every unavailable path names a reason
            raise ValuationError(f"Funding event {event_id!r} reported no scope value and no reason.")
        scope = f"Unit {unit_id!r}" if scope_kind is ValuationScopeKind.UNIT else "the Investment"
        return _requirement(
            event_id=event_id,
            position_id=position_id,
            timepoint_id=timepoint_id,
            scope_kind=scope_kind,
            unit_id=unit_id,
            model_month=event_model_month,
            pct=pct,
            reason=reason,
            valuation_reason=valuation_reason,
            message=(
                f"Funding event {event_id!r} of {position_id!r} is a percentage of the value of {scope} at valuation "
                f"timepoint {timepoint_id!r}, which has no value: {message} The funding is left unresolved and is "
                "never read as zero."
            ),
        )

    return ResolvedValuationFunding(
        event_id=event_id,
        position_id=position_id,
        timepoint_id=timepoint_id,
        scope_kind=scope_kind,
        unit_id=unit_id,
        model_month=event_model_month,
        pct=pct,
        scope_value=value,
        amount=ensure_finite(f"pct_of_value[{event_id}]", pct * value),
    )
