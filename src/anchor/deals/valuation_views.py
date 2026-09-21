"""Phase 7 Gate P7.10 Stage 2 -- the persisted valuation meets the Stage 1
engine.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 5, 6,
6.1, 6.2, 8, 10 and 16, under the ratified P7 authority in
``P7_COMPETITION_DECISION_ARCHITECTURE.md``; those documents govern on any
discrepancy.

The one place a *persisted* valuation definition meets the accepted Stage 1
valuation authority::

    the analyst's stored definitions           ``store.list_valuation_timepoints``
            |
    the evidence gate (Section 8)              an analyst-supplied value whose
            |                                  Evidence Reference is missing or
            |                                  unapproved does not resolve
            v
    ``resolve_investment_valuation``           Stage 1, unchanged: the values
            |                                  and the typed unavailable reasons
            v
    the Stage 2 view                           the structured available /
                                               unavailable representation

**Stage 1 is read, never reproduced.** Every value, every forward NOI, every
typed unavailable reason and the whole Section 5.5 aggregation come from
``anchor.valuation``. This module adds no arithmetic: search it for an operator
and there is none on a money value. When the evidence gate blocks a Unit, the
Investment view is unavailable -- it is never re-summed from the Units that did
resolve, because Section 5.5 already says a partial portfolio sum is not the
Investment value.

**The evidence gate is Stage 2's own** (Section 8; R-D). Stage 1 validates that
an analyst-supplied value *names* an Evidence Reference; whether that reference
exists and is **approved** is a persisted fact Stage 1 cannot see. An
unapproved source never produces a value here, and the amount the analyst typed
is deliberately not reported -- presenting it would be exactly the "silently
upgraded to a fact" Section 8 forbids.

**Closing-only execution is unchanged** (Section 6.1). This module builds the
authority a ``PctOfValue`` funding is sized from, at whatever model month the
funding and the timepoint share. The P7.8 executor downstream still funds
positions at closing only, and nothing here relaxes it: a later Stabilized or
Custom valuation resolves to a real reporting value that no funding event can
presently consume. That is a product limitation with a named reason, never a
zero and never a fallback to the purchase price.

**Never cached.** No valuation result is stored. A view is recomputed from the
stored definitions and the current variant on every request, so a value can
never be served from a state that has moved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..contracts import AcquisitionTerms
from ..engine.contracts import AcquisitionResults
from ..memo.availability import (
    AvailabilityStatus,
    UnavailableReasonCode,
    UnavailableState,
    evidence_not_approved,
    funding_unresolved,
    investment_unavailable,
    unit_unavailable,
)
from ..memo.contracts import MemoEvidenceReference
from ..valuation.contracts import (
    AnalystValue,
    ExitValuationView,
    InvestmentValuationResult,
    UnitValuationResult,
    ValuationAvailability,
    ValuationKind,
    ValuationScopeKind,
    ValuationTimepoint,
    ValuationVariantInputs,
)
from ..valuation.engine import resolve_investment_valuation, unit_inputs, variant_inputs
from ..valuation.funding import ValuationAuthority, valuation_authority
from .fingerprint import fingerprint_valuation_definitions, fingerprint_valuation_results


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceBlockedUnit:
    """One Unit whose analyst-supplied value has no approved source, and the
    finding.

    ``detail`` keeps "this Investment does not hold" and "the analyst has not
    approved" apart: collapsing them would tell an analyst to approve something
    that is not there."""

    unit_id: str
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceBlockedValuation:
    """One valuation definition the evidence gate withheld, and the Units that
    caused it.

    A tuple of frozen records rather than a mapping, like every other collection
    on an analysis contract: it serialises through ``dataclasses.asdict``, and
    its order is canonical by ``unit_id`` rather than by insertion."""

    timepoint_id: str
    units: tuple[EvidenceBlockedUnit, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitValuationView:
    """One Unit's value at one timepoint, as Stage 2 exposes it.

    ``result`` is Stage 1's own record, carried through unchanged so the
    operands stay inspectable. ``unavailable`` is the structured representation
    of why there is no value, and is ``None`` exactly when the Unit resolved.

    ``analyst_supplied`` is copied from Stage 1 and is always shown, so no
    reader can mistake an analyst's own number for an Anchor valuation
    (Section 5.4)."""

    unit_id: str
    status: AvailabilityStatus
    value: float | None
    analyst_supplied: bool
    forward_noi: float | None
    cap_rate: float | None
    evidence_id: str | None
    result: UnitValuationResult
    unavailable: UnavailableState | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationView:
    """One authored valuation timepoint, resolved against one Analysis Variant.

    ``value`` is the Investment's contemporaneous value and exists only when
    every member Unit resolved (Section 5.5). It is never a partial sum, never
    zero-filled and never the purchase price.

    ``unavailable`` carries the typed reason when there is none, and
    ``unit_views`` always names every Unit and its own outcome, so an incomplete
    Investment says exactly which Unit blocked it and why."""

    timepoint_id: str
    kind: ValuationKind
    label: str
    model_month: int
    scope_kind: ValuationScopeKind
    status: AvailabilityStatus
    value: float | None
    unit_views: tuple[UnitValuationView, ...]
    unavailable: UnavailableState | None
    result: InvestmentValuationResult


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationViewSet:
    """Every valuation view of one Analysis Variant, with the two P7.10
    identities (Section 10).

    ``definition_fingerprint`` is the authored definitions' identity, excluding
    labels and display order. ``result_fingerprint`` layers the variant and the
    resolved values on top of it, so a changed cap rate and a changed Strategy
    are distinguishable causes of staleness.

    ``exit_view`` is the reserved, read-only system Exit view (R-B): the
    existing D6 terminal result, read unchanged. It is not a stored definition
    and never becomes one."""

    investment_id: str
    strategy_id: str
    scenario_id: str
    hold_period: int
    views: tuple[ValuationView, ...]
    exit_view: ExitValuationView | None
    unit_exit_views: tuple[ExitValuationView, ...]
    variant_source_fingerprint: str
    definition_fingerprint: str
    result_fingerprint: str

    def find(self, timepoint_id: str) -> ValuationView | None:
        for view in self.views:
            if view.timepoint_id == timepoint_id:
                return view
        return None


# =============================================================================
# Variant inputs
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationUnitSource:
    """One Unit's resolved terms and completed results, as the caller already
    holds them.

    Passed in rather than loaded, because the caller -- the structured variant
    service -- has already resolved and analysed this Unit. Re-loading it here
    would create a second resolution pathway and could read a state that moved
    between the two."""

    unit_id: str
    terms: AcquisitionTerms
    results: AcquisitionResults


def build_variant_inputs(
    *, investment_id: str, units: Iterable[ValuationUnitSource]
) -> ValuationVariantInputs:
    """The Stage 1 variant inputs for one Investment, built from completed
    results. Nothing is recalculated: ``unit_inputs`` copies, and
    ``variant_inputs`` canonicalises by ``unit_id``."""

    return variant_inputs(
        investment_id=investment_id,
        units=tuple(
            unit_inputs(unit_id=source.unit_id, terms=source.terms, results=source.results)
            for source in units
        ),
    )


# =============================================================================
# The evidence gate (Section 8; R-D)
# =============================================================================


def _evidence_problem(
    method: AnalystValue, evidence: Mapping[str, MemoEvidenceReference]
) -> str | None:
    """Why this analyst-supplied value's Evidence Reference cannot support it,
    or ``None``.

    Two distinct findings, kept distinct: a reference that does not exist, and
    one that exists and the analyst has not approved. Collapsing them would tell
    an analyst to approve something that is not there."""

    found = evidence.get(method.evidence_id)
    if found is None:
        return "this Investment does not hold"
    if not found.approved:
        return "the analyst has not approved"
    return None


def evidence_blocked_units(
    timepoint: ValuationTimepoint, evidence: Mapping[str, MemoEvidenceReference]
) -> dict[str, str]:
    """The Units of one definition whose analyst-supplied value has no approved
    source, with the finding for each, in ``unit_id`` order.

    A ``DIRECT_CAP`` instruction is never blocked: it cites no source because it
    states none -- its operands are the variant's own forward NOI and the
    analyst's cap rate, both already visible."""

    blocked: dict[str, str] = {}
    for instruction in sorted(timepoint.unit_instructions, key=lambda item: item.unit_id):
        method = instruction.method
        if not isinstance(method, AnalystValue):
            continue
        problem = _evidence_problem(method, evidence)
        if problem is not None:
            blocked[instruction.unit_id] = problem
    return blocked


def evidence_blocked_timepoints(
    timepoints: Iterable[ValuationTimepoint], evidence: Mapping[str, MemoEvidenceReference]
) -> dict[str, dict[str, str]]:
    """Every definition with at least one evidence-blocked Unit, by
    ``timepoint_id``. Used both to build the views and to keep a blocked
    valuation out of the funding authority."""

    blocked: dict[str, dict[str, str]] = {}
    for timepoint in timepoints:
        units = evidence_blocked_units(timepoint, evidence)
        if units:
            blocked[timepoint.timepoint_id] = units
    return blocked


def blocked_records(
    blocked: Mapping[str, Mapping[str, str]]
) -> tuple[EvidenceBlockedValuation, ...]:
    """The evidence-gate findings as frozen records, canonical by
    ``timepoint_id`` then ``unit_id``, for reporting on an analysis contract."""

    return tuple(
        EvidenceBlockedValuation(
            timepoint_id=timepoint_id,
            units=tuple(
                EvidenceBlockedUnit(unit_id=unit_id, detail=blocked[timepoint_id][unit_id])
                for unit_id in sorted(blocked[timepoint_id])
            ),
        )
        for timepoint_id in sorted(blocked)
    )


# =============================================================================
# Resolution
# =============================================================================


def _unit_view(
    result: UnitValuationResult,
    *,
    timepoint: ValuationTimepoint,
    blocked: Mapping[str, str],
) -> UnitValuationView:
    """One Unit's Stage 2 view.

    The evidence gate is applied *over* Stage 1's result rather than instead of
    it: a blocked Unit reports ``EVIDENCE_NOT_APPROVED`` and no value, whatever
    amount the definition states. Nothing recomputes the Unit -- the gate only
    ever removes a value, never produces one."""

    problem = blocked.get(result.unit_id)
    if problem is not None:
        return UnitValuationView(
            unit_id=result.unit_id,
            status=AvailabilityStatus.UNAVAILABLE,
            value=None,
            analyst_supplied=True,
            forward_noi=None,
            cap_rate=None,
            evidence_id=result.evidence_id,
            result=result,
            unavailable=evidence_not_approved(
                timepoint_id=timepoint.timepoint_id,
                unit_id=result.unit_id,
                evidence_id=result.evidence_id or "",
                model_month=timepoint.model_month,
                detail=problem,
            ),
        )
    if result.status is ValuationAvailability.AVAILABLE:
        return UnitValuationView(
            unit_id=result.unit_id,
            status=AvailabilityStatus.AVAILABLE,
            value=result.value,
            analyst_supplied=result.analyst_supplied,
            forward_noi=result.forward_noi,
            cap_rate=result.cap_rate,
            evidence_id=result.evidence_id,
            result=result,
            unavailable=None,
        )
    return UnitValuationView(
        unit_id=result.unit_id,
        status=AvailabilityStatus.UNAVAILABLE,
        value=None,
        analyst_supplied=result.analyst_supplied,
        forward_noi=None,
        cap_rate=None,
        evidence_id=result.evidence_id,
        result=result,
        unavailable=unit_unavailable(result, timepoint_id=timepoint.timepoint_id),
    )


def resolve_view(
    timepoint: ValuationTimepoint,
    *,
    variant: ValuationVariantInputs,
    evidence: Mapping[str, MemoEvidenceReference],
) -> ValuationView:
    """One definition resolved against one variant, as a Stage 2 view.

    Stage 1 does the work. This adds exactly two things: the evidence gate, and
    the structured representation of whatever Stage 1 reported.

    **The Investment value is Stage 1's, or there is none.** When no Unit is
    evidence-blocked, ``value`` is Stage 1's own ``result.value``, character for
    character -- not re-added here. When any Unit is blocked, there is no
    Investment value at all; the Units that did resolve are never summed into
    one (Section 5.5)."""

    result = resolve_investment_valuation(timepoint, variant=variant)
    blocked = evidence_blocked_units(timepoint, evidence)
    unit_views = tuple(
        _unit_view(unit, timepoint=timepoint, blocked=blocked) for unit in result.unit_results
    )

    if blocked:
        named = ", ".join(f"{unit_id!r}" for unit_id in sorted(blocked))
        unavailable = UnavailableState(
            status=AvailabilityStatus.UNAVAILABLE,
            reason_code=UnavailableReasonCode.EVIDENCE_NOT_APPROVED,
            reason=(
                f"Investment {variant.investment_id!r} has no value at valuation timepoint "
                f"{timepoint.timepoint_id!r}: the analyst-supplied value for {named} has no approved Evidence "
                "Reference. A partial sum of the Units that do have a value is never the Investment value."
            ),
            scope_kind=ValuationScopeKind.INVESTMENT.value,
            scope_id=variant.investment_id,
            model_month=timepoint.model_month,
            timepoint_id=timepoint.timepoint_id,
        )
        status, value = AvailabilityStatus.UNAVAILABLE, None
    elif result.status is ValuationAvailability.AVAILABLE:
        unavailable, status, value = None, AvailabilityStatus.AVAILABLE, result.value
    else:
        unavailable = investment_unavailable(result)
        status, value = AvailabilityStatus.UNAVAILABLE, None

    return ValuationView(
        timepoint_id=timepoint.timepoint_id,
        kind=timepoint.kind,
        label=timepoint.label,
        model_month=timepoint.model_month,
        scope_kind=ValuationScopeKind.INVESTMENT,
        status=status,
        value=value,
        unit_views=unit_views,
        unavailable=unavailable,
        result=result,
    )


def resolve_views(
    timepoints: Sequence[ValuationTimepoint],
    *,
    variant: ValuationVariantInputs,
    evidence: Mapping[str, MemoEvidenceReference],
) -> tuple[ValuationView, ...]:
    """Every authored definition resolved against one variant, in the order
    given -- which is the analyst's display order. Presentation order only: no
    fingerprint and no funding reads it."""

    return tuple(resolve_view(timepoint, variant=variant, evidence=evidence) for timepoint in timepoints)


# =============================================================================
# The funding authority (Section 6; R-E)
# =============================================================================


def funding_authority(
    *,
    investment_id: str,
    views: Iterable[ValuationView],
    blocked: Mapping[str, Mapping[str, str]],
) -> ValuationAuthority:
    """The Stage 1 authority a ``PctOfValue`` funding is sized from.

    **An evidence-blocked valuation is withheld** (Section 6, "if the
    definition, forward NOI, evidence, unit membership, or valuation is missing
    or invalid, the Funding Requirement remains unresolved with a typed
    reason"). It is left out of the authority entirely rather than offered with
    a value, so no position can be funded from an amount whose source the
    analyst has not approved.

    The Stage 1 reason that withholding produces is ``TIMEPOINT_NOT_FOUND``,
    which would be misleading on its own -- the timepoint *is* authored. Stage 2
    never shows it: ``funding_unavailable`` below knows which timepoints were
    withheld and reports ``EVIDENCE_NOT_APPROVED`` instead, which is the
    specific reason Section 6.2 requires.

    Every other unavailable valuation is passed through with its own Stage 1
    result, so its typed reason survives to the analyst unchanged."""

    return valuation_authority(
        investment_id=investment_id,
        valuations=tuple(
            view.result for view in views if view.timepoint_id not in blocked
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class FundingState:
    """One ``PctOfValue`` funding rule's state, as Stage 2 exposes it
    (Section 6.2).

    This is the Stage 2 obligation at its sharpest. The accepted Stage 1
    executor refuses an unresolved ``PctOfValue`` with a typed
    ``CapitalStructureExecutionError`` -- a real, specific refusal, and
    deliberately not relaxed here. But a refusal an analyst meets only by trying
    to run an analysis is not the "structured unavailable / N/A representation
    on the API surface" Section 6.2 requires, so the same states are *also*
    reported here, read-only and ahead of time, with the specific reason.

    ``amount`` is present exactly when the funding resolved. When it did not,
    ``unavailable`` says why and there is no amount anywhere in the record: a
    percentage of an unknown value is unknown, and it is never read as zero,
    estimated, or sized from the purchase price."""

    event_id: str
    position_id: str
    timepoint_id: str
    model_month: int
    pct: float
    status: AvailabilityStatus
    amount: float | None
    unavailable: UnavailableState | None


def funding_unavailable(
    requirement: object,
    *,
    blocked: Mapping[str, Mapping[str, str]],
) -> UnavailableState:
    """One unresolved ``PctOfValue`` funding as the structured representation
    (Section 6.2).

    When the timepoint was withheld by the evidence gate, the reason reported is
    ``EVIDENCE_NOT_APPROVED`` and names the Units concerned -- never the
    ``TIMEPOINT_NOT_FOUND`` the authority's absence would otherwise imply.

    In every case the state carries **no amount**: the advance itself is
    unknown, and ``UnavailableState`` has no field that could hold a number.
    A percentage of an unknown value is unknown, and it is never read as zero,
    estimated, resized or filled in from the purchase price."""

    timepoint_id = getattr(requirement, "timepoint_id", None)
    units = blocked.get(timepoint_id or "")
    if units is None:
        return funding_unresolved(requirement)  # type: ignore[arg-type]
    named = ", ".join(repr(unit_id) for unit_id in sorted(units))
    return UnavailableState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=UnavailableReasonCode.EVIDENCE_NOT_APPROVED,
        reason=(
            f"Funding event {getattr(requirement, 'event_id', None)!r} of "
            f"{getattr(requirement, 'position_id', None)!r} is a percentage of the value at valuation timepoint "
            f"{timepoint_id!r}, whose analyst-supplied value for {named} has no approved Evidence Reference. The "
            "funding is left unresolved and is never read as zero, estimated, or sized from the acquisition price."
        ),
        scope_kind=getattr(getattr(requirement, "scope_kind", None), "value", None),
        scope_id=getattr(requirement, "unit_id", None) or getattr(requirement, "position_id", None),
        model_month=getattr(requirement, "model_month", None),
        timepoint_id=timepoint_id,
    )


# =============================================================================
# Identity (Section 10)
# =============================================================================


def view_fingerprints(
    *,
    timepoints: Sequence[ValuationTimepoint],
    views: Sequence[ValuationView],
    variant_source_fingerprint: str,
) -> tuple[str, str]:
    """The valuation-definition and valuation-result fingerprints of one
    variant.

    The definition digest reads the authored definitions only, so it is the same
    under every Strategy and Scenario; the result digest layers the variant and
    the resolved values on top. That separation is what lets a stale memo say
    *which* of the two moved."""

    definition_fingerprint = fingerprint_valuation_definitions(timepoints)
    return definition_fingerprint, fingerprint_valuation_results(
        variant_source_fingerprint=variant_source_fingerprint,
        valuation_definition_fingerprint=definition_fingerprint,
        results=[view.result for view in views],
    )


def view_set(
    *,
    investment_id: str,
    strategy_id: str,
    scenario_id: str,
    hold_period: int,
    timepoints: Sequence[ValuationTimepoint],
    views: Sequence[ValuationView],
    exit_view: ExitValuationView | None,
    unit_exit_views: Sequence[ExitValuationView],
    variant_source_fingerprint: str,
) -> ValuationViewSet:
    """Assemble one variant's complete valuation surface and its two
    identities."""

    definition_fingerprint, result_fingerprint = view_fingerprints(
        timepoints=timepoints, views=views, variant_source_fingerprint=variant_source_fingerprint
    )
    return ValuationViewSet(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        hold_period=hold_period,
        views=tuple(views),
        exit_view=exit_view,
        unit_exit_views=tuple(unit_exit_views),
        variant_source_fingerprint=variant_source_fingerprint,
        definition_fingerprint=definition_fingerprint,
        result_fingerprint=result_fingerprint,
    )


def funding_states(
    *,
    capital_structure: object,
    authority: ValuationAuthority | None,
    blocked: Mapping[str, Mapping[str, str]],
) -> tuple[FundingState, ...]:
    """Every ``PctOfValue`` funding rule the structure states, resolved through
    the Stage 1 sizing authority and reported in the Stage 2 representation.

    Read-only and side-effect free: it sizes nothing that the executor does not
    already size the same way, and it writes nothing. Its whole purpose is to
    let the product show an analyst *why* a value-sized funding cannot be
    sized, before they run an analysis that would refuse.

    With no authority at all -- an Investment that defines no valuation -- every
    rule is unavailable for the reason the Stage 1 funding layer gives: the
    timepoint is not defined, and no other timepoint is used in its place."""

    from ..capital_structure.contracts import PctOfValue
    from ..capital_structure.funding import valuation_scope
    from ..valuation.contracts import FundingResolutionStatus
    from ..valuation.funding import resolve_pct_of_value_funding, valuation_authority

    if not hasattr(capital_structure, "positions"):
        return ()
    resolved_authority = authority or valuation_authority(investment_id="", valuations=())
    states: list[FundingState] = []
    for position in capital_structure.positions:
        for event in position.funding:
            rule = event.amount_rule
            if not isinstance(rule, PctOfValue):
                continue
            scope_kind, unit_id = valuation_scope(position.scope)
            resolution = resolve_pct_of_value_funding(
                event_id=event.event_id,
                position_id=position.position_id,
                event_model_month=event.model_month,
                timepoint_id=rule.timepoint_id,
                pct=rule.pct,
                scope_kind=scope_kind,
                unit_id=unit_id,
                authority=resolved_authority,
            )
            if resolution.status is FundingResolutionStatus.RESOLVED:
                states.append(
                    FundingState(
                        event_id=event.event_id,
                        position_id=position.position_id,
                        timepoint_id=rule.timepoint_id,
                        model_month=event.model_month,
                        pct=float(rule.pct),
                        status=AvailabilityStatus.AVAILABLE,
                        amount=resolution.amount,  # type: ignore[union-attr]
                        unavailable=None,
                    )
                )
                continue
            states.append(
                FundingState(
                    event_id=event.event_id,
                    position_id=position.position_id,
                    timepoint_id=rule.timepoint_id,
                    model_month=event.model_month,
                    pct=float(rule.pct),
                    status=AvailabilityStatus.UNAVAILABLE,
                    amount=None,
                    unavailable=funding_unavailable(resolution, blocked=blocked),
                )
            )
    return tuple(
        sorted(states, key=lambda state: (state.position_id, state.event_id))
    )


def consumed_valuations(
    *, views: Iterable[ValuationView], timepoint_ids: Iterable[str]
) -> dict[str, InvestmentValuationResult]:
    """The resolved valuations a Capital Structure's ``PctOfValue`` rules name,
    by ``timepoint_id``.

    Only those a rule actually consumes (Section 6). A report-only timepoint no
    position reads is deliberately absent: it changes valuation and memo
    freshness, and not the structured financial identity. A named timepoint the
    Investment does not define is simply not present -- the funding reports that
    itself, and an absence is never hashed as though it were a value."""

    wanted = set(timepoint_ids)
    return {
        view.timepoint_id: view.result for view in views if view.timepoint_id in wanted
    }
