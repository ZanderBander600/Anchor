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
from dataclasses import dataclass, replace

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
    UnresolvedFundingReason,
    ValuationUnavailableReason,
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationRequirement:
    """One exact-scope value a resolved Capital Structure consumes (P7.10
    Section 6, R-E; Refinance V1 Sections 8.1 and 14.1).

    ``UNIT`` names one Unit's cell at the timepoint; ``INVESTMENT`` names the
    complete Investment value, which exists only when every member Unit's does.
    A requirement never widens: a Unit consumer depends on its own cell alone,
    so another Unit's value, evidence or availability is not its dependency."""

    timepoint_id: str
    scope_kind: ValuationScopeKind
    unit_id: str | None

    def key(self) -> tuple[str, str, str]:
        return self.timepoint_id, self.scope_kind.value, self.unit_id or ""


def _withheld_cell(cell: UnitValuationResult, *, detail: str) -> UnitValuationResult:
    """One analyst-supplied cell whose Evidence Reference cannot support it:
    unavailable, with no value and no operand. The amount the analyst typed is
    never carried. P7.10's valuation reasons have no evidence member -- the
    evidence gate is Stage 2's own -- so the typed fact lives in the gate's
    ``blocked`` map, and this cell states only that it has no value, and why,
    in words."""

    return replace(
        cell,
        status=ValuationAvailability.UNAVAILABLE,
        value=None,
        forward_noi=None,
        cap_rate=None,
        unavailable_reason=None,
        unavailable_message=(
            f"The analyst-supplied value is not used: {detail} its Evidence Reference. It is never read as zero or "
            "replaced by another value."
        ),
    )


def gated_result(
    result: InvestmentValuationResult, *, blocked_units: Mapping[str, str]
) -> InvestmentValuationResult:
    """``result`` as the evidence gate lets consumers read it, cell by cell.

    Each evidence-blocked Unit cell is withheld; every other cell is Stage 1's
    own, unchanged. The Investment value exists only when every member Unit
    does (Section 5.5), so a withheld cell makes it unavailable -- never a
    partial sum of the cells that remain. A result the gate does not touch is
    returned as the very same object."""

    if not blocked_units:
        return result
    cells = tuple(
        _withheld_cell(cell, detail=blocked_units[cell.unit_id]) if cell.unit_id in blocked_units else cell
        for cell in result.unit_results
    )
    if result.status is not ValuationAvailability.AVAILABLE:
        return replace(result, unit_results=cells)
    return replace(
        result,
        status=ValuationAvailability.UNAVAILABLE,
        value=None,
        unit_results=cells,
        unavailable_reason=ValuationUnavailableReason.INCOMPLETE_UNITS,
        unavailable_message=(
            "The Investment has no value at this timepoint: the analyst-supplied value of at least one Unit has no "
            "approved Evidence Reference. A partial sum of the Units that do have a value is never the Investment value."
        ),
    )


def funding_authority(
    *,
    investment_id: str,
    views: Iterable[ValuationView],
    blocked: Mapping[str, Mapping[str, str]],
) -> ValuationAuthority:
    """The Stage 1 authority a ``PctOfValue`` funding and an LTV-sized
    refinance are sized from.

    **The evidence gate is exact-scope** (P7.10 Section 6 and R-E; Refinance
    V1 Section 8.1; review correction). Every authored timepoint is offered,
    each as ``gated_result`` presents it: a Unit whose analyst-supplied value
    has no approved source has no value, the Investment has none while any
    member Unit has none, and every other Unit cell keeps its value. A consumer
    reads exactly its own scope, so an unrelated Unit's evidence never makes
    another Unit's value unknown, and no position is ever funded or sized from
    an amount whose source the analyst has not approved.

    Every other unavailable valuation is passed through with its own Stage 1
    result, so its typed reason survives to the analyst unchanged."""

    return valuation_authority(
        investment_id=investment_id,
        valuations=tuple(
            gated_result(view.result, blocked_units=blocked.get(view.timepoint_id, {})) for view in views
        ),
    )


def scope_evidence_blocked(
    blocked: Mapping[str, Mapping[str, str]],
    *,
    timepoint_id: str,
    scope_kind: ValuationScopeKind,
    unit_id: str | None,
) -> dict[str, str]:
    """The evidence-blocked Units that the exact scope depends on, with each
    finding: that Unit alone for a Unit scope, every blocked member for the
    Investment scope. Empty when the scope's value does not depend on any
    withheld cell."""

    units = blocked.get(timepoint_id, {})
    if scope_kind is ValuationScopeKind.INVESTMENT:
        return dict(units)
    return {unit_id: units[unit_id]} if unit_id is not None and unit_id in units else {}


def funding_unavailable(
    requirement: object,
    *,
    blocked: Mapping[str, Mapping[str, str]],
) -> UnavailableState:
    """One unresolved ``PctOfValue`` funding as the structured representation
    (Section 6.2).

    When the evidence gate withheld a cell the funding's **exact scope**
    depends on, the reason reported is ``EVIDENCE_NOT_APPROVED`` and names the
    Units concerned: the position's own Unit for a Unit scope, the blocked
    members for the Investment scope. An unrelated Unit's evidence is never a
    reason here, because it never made this scope's value unknown.

    In every case the state carries **no amount**: the advance itself is
    unknown, and ``UnavailableState`` has no field that could hold a number.
    A percentage of an unknown value is unknown, and it is never read as zero,
    estimated, resized or filled in from the purchase price."""

    timepoint_id = getattr(requirement, "timepoint_id", None)
    scope_kind = getattr(requirement, "scope_kind", None)
    units = (
        scope_evidence_blocked(
            blocked,
            timepoint_id=timepoint_id or "",
            scope_kind=scope_kind,  # type: ignore[arg-type]
            unit_id=getattr(requirement, "unit_id", None),
        )
        if isinstance(scope_kind, ValuationScopeKind)
        and getattr(requirement, "reason", None) is UnresolvedFundingReason.VALUATION_UNAVAILABLE
        else {}
    )
    if not units:
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
