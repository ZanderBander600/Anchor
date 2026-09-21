"""Phase 7 Gate P7.8 -- closing funding and fees of an authored position.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
12.2 and 12.3 (CS-6) and the P7.8 decisions of
``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md``; those documents
govern on any discrepancy.

**Closing only.** Every executable funding event and fee is at model month 0
(the execution validator refuses any other month). A later funding month is
never moved to closing.

**Amount rules.** ``FixedAmount`` is its dollars. ``PctOfPrice`` is ``pct`` of
the scope's stated acquisition price: the Unit's resolved
``AcquisitionTerms.purchase_price``, or the Investment's
``ConsolidatedResults.transaction_price``. Never a second inferred value, an
exit value, NOI or an estimate.

**``PctOfValue`` at closing (P7.10 Stage 1, R-E).** The rule P7.7 represented
is now valued, against a ``ValuationAuthority`` the caller supplies: the funding
is ``pct`` of the value of the position's exact scope at the named timepoint,
and only where that timepoint shares the funding event's model month. Because
this executor funds at closing only -- the rule above, unchanged -- the only
executable ``PctOfValue`` is a closing one against a month-0 valuation. A later
timepoint still resolves as a reporting value; it simply cannot fund, and no
event is moved to closing to make it. No second
amount-rule shape exists, ``pct``'s own P7.7 validation is unchanged, and
nothing is sized from a value that did not resolve. With no authority supplied
the rule is refused exactly as before, so an analysis without P7.10 structure
behaves identically.

**Signs, provider side.** Funding advanced is negative and a fee received is
positive. Common equity sees the opposite: the funding is a closing source, and
the fee a closing use.
"""

from __future__ import annotations

from ..consolidation.contracts import ConsolidatedResults
from ..contracts import AcquisitionTerms
from ..engine.contracts import ensure_finite
from ..valuation.contracts import (
    UnresolvedFundingRequirement,
    ValuationFundingResolution,
    ValuationScopeKind,
)
from ..valuation.funding import ValuationAuthority, resolve_pct_of_value_funding
from .contracts import (
    CapitalPosition,
    CapitalStructureError,
    DebtTerms,
    FundingEvent,
    FixedAmount,
    PctOfPrice,
    PctOfValue,
    PositionScope,
    ScopeKind,
)
from .execution_contracts import (
    PositionCashFlowEvent,
    PositionCashFlowKind,
    PriceBasis,
    PriceBasisKind,
    ResolvedFundingEvent,
)


def unit_price_basis(terms: AcquisitionTerms) -> PriceBasis:
    """The Unit's resolved purchase price, as stated on its terms."""

    return PriceBasis(kind=PriceBasisKind.UNIT_PURCHASE_PRICE, amount=terms.purchase_price)


def investment_price_basis(consolidated: ConsolidatedResults) -> PriceBasis:
    """The Investment's stated transaction price."""

    return PriceBasis(kind=PriceBasisKind.INVESTMENT_TRANSACTION_PRICE, amount=consolidated.transaction_price)


def valuation_scope(scope: PositionScope) -> tuple[ValuationScopeKind, str | None]:
    """A position's scope as the valuation layer names it. A Unit-scoped
    position is valued by its own Unit; an Investment-scoped one by the
    Investment. No scope is widened or narrowed to find a value."""

    if scope.kind is ScopeKind.UNIT:
        if scope.unit_id is None:
            raise CapitalStructureError("A Unit-scoped position names no Unit.")
        return ValuationScopeKind.UNIT, scope.unit_id
    return ValuationScopeKind.INVESTMENT, None


def resolve_valuation_funding(
    position: CapitalPosition, event: FundingEvent, rule: PctOfValue, *, authority: ValuationAuthority
) -> ValuationFundingResolution:
    """One ``PctOfValue`` funding sized from ``authority``, or the typed
    unresolved Funding Requirement saying why it is unknowable. The one
    authority for this: the execution validator and the scheduler both call
    it, so neither can size a funding the other refused."""

    scope_kind, unit_id = valuation_scope(position.scope)
    return resolve_pct_of_value_funding(
        event_id=event.event_id,
        position_id=position.position_id,
        event_model_month=event.model_month,
        timepoint_id=rule.timepoint_id,
        pct=rule.pct,
        scope_kind=scope_kind,
        unit_id=unit_id,
        authority=authority,
    )


def _funding_order(event: FundingEvent) -> tuple[int, int, str]:
    return (event.model_month, event.sequence, event.event_id)


def resolve_funding(
    position: CapitalPosition, *, price_basis: PriceBasis, valuations: ValuationAuthority | None = None
) -> tuple[ResolvedFundingEvent, ...]:
    """Each funding event of ``position`` in dollars, in canonical order (model
    month, sequence, event id). Every event is resolved on its own; none is
    merged or dropped. Raises ``CapitalStructureError`` for a rule that is
    never executed here.

    ``valuations`` is the P7.10 authority a ``PctOfValue`` rule is sized from.
    ``None`` -- the default, and every caller without P7.10 structure -- keeps
    the rule refused exactly as before."""

    resolved: list[ResolvedFundingEvent] = []
    for event in sorted(position.funding, key=_funding_order):
        rule = event.amount_rule
        match rule:
            case FixedAmount():
                amount = ensure_finite(f"funding[{event.event_id}]", float(rule.amount))
                basis = None
            case PctOfPrice():
                amount = ensure_finite(f"funding[{event.event_id}]", rule.pct * price_basis.amount)
                basis = price_basis
            case PctOfValue():
                if valuations is None:
                    raise CapitalStructureError(
                        f"Funding event {event.event_id!r} is valued at a valuation timepoint, which this executor "
                        "never values; the execution validator refuses it first."
                    )
                resolution = resolve_valuation_funding(position, event, rule, authority=valuations)
                if isinstance(resolution, UnresolvedFundingRequirement):
                    raise CapitalStructureError(
                        f"Funding event {event.event_id!r} has no resolved value, so it is never scheduled: "
                        f"{resolution.message} The execution validator refuses it first."
                    )
                amount = ensure_finite(f"funding[{event.event_id}]", resolution.amount)
                basis = None
        resolved.append(
            ResolvedFundingEvent(
                event_id=event.event_id,
                model_month=event.model_month,
                sequence=event.sequence,
                amount_rule=rule,
                price_basis=basis,
                amount=amount,
            )
        )
    return tuple(resolved)


def funded_amount(resolved: tuple[ResolvedFundingEvent, ...]) -> float:
    """The gross capital advanced: the canonical-order sum of the resolved
    funding events. Fees never reduce it."""

    total = 0.0
    for event in resolved:
        total = total + event.amount
    return ensure_finite("funded_amount", total)


def closing_events(position: CapitalPosition, resolved: tuple[ResolvedFundingEvent, ...]) -> tuple[PositionCashFlowEvent, ...]:
    """The provider-side closing events: each funding advanced, negative, and
    each debt fee received, positive. Preferred equity carries no fee
    contract."""

    events = [
        PositionCashFlowEvent(
            event_id=event.event_id,
            position_id=position.position_id,
            model_month=event.model_month,
            sequence=event.sequence,
            kind=PositionCashFlowKind.FUNDING,
            amount=-event.amount,
        )
        for event in resolved
    ]
    if isinstance(position.terms, DebtTerms):
        events.extend(
            PositionCashFlowEvent(
                event_id=fee.fee_id,
                position_id=position.position_id,
                model_month=fee.model_month,
                sequence=fee.sequence,
                kind=PositionCashFlowKind.FEE,
                amount=ensure_finite(f"fee[{fee.fee_id}]", float(fee.amount)),
            )
            for fee in position.terms.fees
        )
    return tuple(events)
