"""Phase 7 Gate P7.10 Stage 2 -- the memo dependency ledger and its freshness.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 7.3,
9, 10 and 16, under the ratified P7 authority in
``P7_COMPETITION_DECISION_ARCHITECTURE.md``; those documents govern on any
discrepancy. Ratified decision R-H is the version model behind it.

**Layered identity, not one ambiguous hash** (Section 10). A published memo
version records one fingerprint per dependency *class* per scope, each computed
by the authority that already owns that state::

    INVESTMENT_MEMBERSHIP   which Units the Investment holds
    UNDERWRITING            each Unit's existing resolved-input fingerprint
    BUSINESS_PLAN           the Investment's and each Unit's authored plan
    STRATEGY / SCENARIO     the selected definitions' own economics
    PROJECT_VARIANT         the existing Project source fingerprint
    CAPITAL_STRUCTURE       the P7.8B structured source fingerprint
    PARTNERSHIP             the P7.9 Partnership source fingerprint, when one exists
    VALUATION_DEFINITIONS   the authored timepoints, without labels or order
    VALUATION_RESULTS       those definitions resolved against this variant
    DECISION_PERSPECTIVE    the selected perspective's identity
    EVIDENCE                the cited references' content
    MEMO_CONTENT            the authored memo itself

Nothing here computes a financial value or invents an identity. Every entry is
read from the existing authority for that domain, so a fingerprint has exactly
one implementation and two layers cannot drift.

**Overlapping is not duplicating.** ``BUSINESS_PLAN``, ``STRATEGY`` and
``SCENARIO`` all also move ``PROJECT_VARIANT``, because the ratified P7 identity
model folds them into the resolved inputs. They are recorded *beside* it, never
instead of it, so a stale package can say "the Business Plan changed" rather
than only "the underwriting changed". The report order puts the specific
statement first.

**Presentation never invalidates financial state.** A valuation label, a
valuation's display order, a Strategy's name and a Partnership's partner names
are excluded from every financial class by construction -- they are not in those
payloads at all. Reordering the evidence register does not move the evidence
digest either. Reordering *memo items* does move ``MEMO_CONTENT``, because
Section 10 says the explicit display order is part of the authored memo; it
moves no financial class.

**A historical version is always readable.** Freshness describes a version; it
never withholds, rewrites or silently refreshes one. A dependency that can no
longer be computed at all -- the Strategy was deleted, the variant no longer
resolves -- is reported as a named condition, not as an equality that quietly
fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis.strategy import BASE_SCENARIO_ID, BASE_STRATEGY_ID
from ..memo.contracts import (
    DEPENDENCY_REPORT_ORDER,
    DecisionPerspectiveKind,
    InvestmentMemoDraft,
    InvestmentMemoVersion,
    MemoDependency,
    MemoDependencyClass,
    MemoFreshness,
    MemoFreshnessReport,
    MemoStaleDependency,
    MemoVersionValuation,
    SelectedDecision,
)
from ..memo.publication import (
    PublicationContext,
    RequiredValuation,
    RequiredValuationReason,
    require_publishable,
)
from . import store
from .contracts import (
    DealNotFoundError,
    InvestmentNotFoundError,
    MemoNotFoundError,
    ScenarioNotFoundError,
    StrategyNotFoundError,
)
from .fingerprint import (
    fingerprint_business_plans,
    fingerprint_decision_perspective,
    fingerprint_evidence,
    fingerprint_investment_membership,
    fingerprint_memo_content,
    fingerprint_published_version,
    fingerprint_scenario_definition,
    fingerprint_strategy_definition,
    fingerprint_unit_underwriting,
    fingerprint_valuation_definitions,
)
from .partnership_variants import partner_perspectives, partnership_variant_fingerprint
from .refinance_integration import has_capital_events
from .refinance_presentation import event_reason_sentence, not_executed, unit_names_of
from .structured_variants import (
    StructuredValuationSurface,
    analyze_structured_valuations,
    analyze_structured_variant,
    position_perspectives,
    resolve_variant_capital_structure,
)

#: The scope id a whole-Investment dependency entry carries. ``''`` rather than
#: ``None`` so two whole-Investment entries of one class cannot both exist under
#: SQLite's NULL-in-primary-key behaviour.
WHOLE_INVESTMENT = ""


class MemoDependencyError(RuntimeError):
    """A dependency ledger that cannot be built at all. A programming error, not
    an analyst finding: the caller asked to publish or refresh something whose
    state does not exist."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoDependencySet:
    """One Investment's current dependency ledger for one selected cell, with
    the valuation surface it was read from.

    ``resolved`` is ``False`` when the selected variant does not currently
    resolve; ``detail`` then carries the variant's own reason. The ledger is
    still returned, holding the classes that *could* be computed, so a stale
    report can name what is unavailable rather than failing to describe it.

    ``surface`` is likewise kept where it could be read at all, even on an
    unresolved set: resolving valuations does not execute the structured
    positions, so a variant whose *execution* refuses still has a valuation
    surface, and that surface holds the typed reason a ``PctOfValue`` funding
    could not be sized."""

    investment_id: str
    selected: SelectedDecision
    dependencies: tuple[MemoDependency, ...]
    surface: StructuredValuationSurface | None
    resolved: bool
    detail: str = ""

    def by_key(self) -> dict[tuple[MemoDependencyClass, str], str]:
        return {
            (entry.dependency_class, entry.scope_id): entry.fingerprint
            for entry in self.dependencies
        }


# =============================================================================
# Reading the current state
# =============================================================================


def _unit_ids(investment_id: str, db_path: Path | None) -> tuple[str, ...]:
    investment = store.get_investment(investment_id, db_path=db_path)
    return tuple(sorted(unit.unit_id for unit in investment.units))


def _business_plans(investment_id: str, db_path: Path | None) -> dict[str, Any]:
    """The Investment's own Business Plan under ``''`` and each Unit's under its
    ``unit_id``.

    Typed loosely on purpose: this module reads plans off already-loaded
    records and hands them to the identity layer, which owns the contract and
    types it. Importing the Business Plan package here for an annotation alone
    would widen a boundary two guards deliberately keep narrow.

    A hidden one-unit wrapper has no Investment-level plan of its own -- it is
    not a visible Investment -- so only its Unit's plan participates. Nothing is
    fabricated for the missing one."""

    plans: dict[str, Any] = {}
    investment = store.get_investment(investment_id, db_path=db_path)
    if not investment.hidden:
        plans[WHOLE_INVESTMENT] = store.get_visible_investment(
            investment_id, db_path=db_path
        ).business_plan
    for unit_id in sorted(unit.unit_id for unit in investment.units):
        plans[unit_id] = store.get_deal(unit_id, db_path=db_path).business_plan
    return plans


def _unit_fingerprints(
    investment_id: str, selected: SelectedDecision, db_path: Path | None
) -> dict[str, str]:
    """Each member Unit's existing resolved-input fingerprint under the selected
    Strategy and Scenario.

    Read from the existing P7.2 / P7.6 authorities. This module computes none of
    them and redefines none of them; it only gives the collection a name so a
    stale memo can say which Unit's underwriting moved."""

    from .investment_variants import inspect_investment_variant_inputs
    from .variants import variant_fingerprint

    investment = store.get_investment(investment_id, db_path=db_path)
    if investment.hidden:
        found = variant_fingerprint(
            investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
        )
        return {found.unit_id: found.source_fingerprint}
    inputs = inspect_investment_variant_inputs(
        investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
    )
    return {unit.unit_id: unit.source_fingerprint for unit in inputs.units}


def _selected_strategy(investment_id: str, strategy_id: str, db_path: Path | None):
    """The persisted Strategy the key names, or ``None`` for the reserved
    implicit Base key."""

    if strategy_id == BASE_STRATEGY_ID:
        return None
    return store.get_strategy(investment_id, strategy_id, db_path=db_path).strategy


def _selected_scenario(investment_id: str, scenario_id: str, db_path: Path | None):
    if scenario_id == BASE_SCENARIO_ID:
        return None
    return store.get_scenario(investment_id, scenario_id, db_path=db_path).scenario


def perspective_exists(
    investment_id: str, selected: SelectedDecision, *, db_path: Path | None = None
) -> bool:
    """Whether the selected perspective is addressable on this Investment.

    ``PROJECT`` always is: it needs no scope. A ``POSITION`` or ``PARTNER``
    perspective must be one the Investment's structures or Partnerships actually
    hold -- naming one they do not is refused rather than answered with another
    stakeholder's figures."""

    if selected.perspective is DecisionPerspectiveKind.PROJECT:
        return True
    if selected.perspective is DecisionPerspectiveKind.POSITION:
        return any(
            item.position_id == selected.position_id
            for item in position_perspectives(investment_id, db_path=db_path)
        )
    return any(
        item.partner_id == selected.partner_id
        for item in partner_perspectives(investment_id, db_path=db_path)
    )


# =============================================================================
# The ledger
# =============================================================================


def _entry(
    dependency_class: MemoDependencyClass, fingerprint: str, *, scope_id: str = WHOLE_INVESTMENT
) -> MemoDependency:
    return MemoDependency(
        dependency_class=dependency_class, scope_id=scope_id, fingerprint=fingerprint
    )


def dependency_set(
    investment_id: str,
    selected: SelectedDecision,
    *,
    draft: InvestmentMemoDraft | None = None,
    db_path: Path | None = None,
) -> MemoDependencySet:
    """The Investment's current dependency ledger for one selected cell.

    Every entry is read from the authority that already owns it. Where the
    selected variant does not resolve, the classes that depend on it are simply
    absent and ``resolved`` is ``False`` with the variant's own reason -- an
    absent entry is never filled in with a placeholder digest, because a
    placeholder would compare equal to itself forever."""

    entries: list[MemoDependency] = [
        _entry(
            MemoDependencyClass.INVESTMENT_MEMBERSHIP,
            fingerprint_investment_membership(_unit_ids(investment_id, db_path)),
        ),
        _entry(
            MemoDependencyClass.BUSINESS_PLAN,
            fingerprint_business_plans(_business_plans(investment_id, db_path)),
        ),
        _entry(
            MemoDependencyClass.VALUATION_DEFINITIONS,
            fingerprint_valuation_definitions(
                store.list_valuation_timepoints(investment_id, db_path=db_path)
            ),
        ),
        _entry(
            MemoDependencyClass.DECISION_PERSPECTIVE,
            fingerprint_decision_perspective(
                perspective=selected.perspective.value,
                position_id=selected.position_id,
                partner_id=selected.partner_id,
            ),
        ),
    ]

    evidence = store.list_evidence_references(investment_id, db_path=db_path)
    cited = (
        evidence
        if draft is None
        else tuple(
            item for item in evidence if item.evidence_id in set(draft.cited_evidence_ids())
        )
    )
    entries.append(_entry(MemoDependencyClass.EVIDENCE, fingerprint_evidence(cited)))
    if draft is not None:
        entries.append(
            _entry(
                MemoDependencyClass.MEMO_CONTENT,
                fingerprint_memo_content(draft, evidence=cited),
            )
        )

    try:
        strategy = _selected_strategy(investment_id, selected.strategy_id, db_path)
        scenario = _selected_scenario(investment_id, selected.scenario_id, db_path)
    except (StrategyNotFoundError, ScenarioNotFoundError) as error:
        return MemoDependencySet(
            investment_id=investment_id,
            selected=selected,
            dependencies=tuple(entries),
            surface=None,
            resolved=False,
            detail=str(error),
        )
    entries.append(
        _entry(MemoDependencyClass.STRATEGY, fingerprint_strategy_definition(strategy))
    )
    entries.append(
        _entry(MemoDependencyClass.SCENARIO, fingerprint_scenario_definition(scenario))
    )

    # The valuation surface is read on its own, before anything that executes
    # the structured positions. Resolving a valuation does not execute them, so
    # the surface survives a variant whose execution refuses -- and it is
    # exactly that surface that says *why*, in the valuation's own typed words,
    # when a ``PctOfValue`` funding could not be sized. Folding the two reads
    # together would throw the specific reason away and leave publication with
    # nothing but "the variant does not resolve".
    try:
        surface = analyze_structured_valuations(
            investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
        )
    except (InvestmentNotFoundError, DealNotFoundError):
        raise
    except Exception as error:  # the variant is not even readable; say so in its own words
        return MemoDependencySet(
            investment_id=investment_id,
            selected=selected,
            dependencies=tuple(entries),
            surface=None,
            resolved=False,
            detail=str(error),
        )

    try:
        unit_fingerprints = _unit_fingerprints(investment_id, selected, db_path)
        partnership = partnership_variant_fingerprint(
            investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
        )
    except (InvestmentNotFoundError, DealNotFoundError):
        raise
    except Exception as error:  # the variant does not resolve; every layer says why in its own words
        return MemoDependencySet(
            investment_id=investment_id,
            selected=selected,
            dependencies=tuple(entries),
            surface=surface,
            resolved=False,
            detail=str(error),
        )

    entries.append(
        _entry(MemoDependencyClass.UNDERWRITING, fingerprint_unit_underwriting(unit_fingerprints))
    )
    entries.append(
        _entry(MemoDependencyClass.PROJECT_VARIANT, surface.project_source_fingerprint)
    )
    entries.append(
        _entry(MemoDependencyClass.CAPITAL_STRUCTURE, surface.structured_source_fingerprint)
    )
    if partnership.partnership_source_fingerprint is not None:
        entries.append(
            _entry(
                MemoDependencyClass.PARTNERSHIP, partnership.partnership_source_fingerprint
            )
        )
    entries.append(
        _entry(MemoDependencyClass.VALUATION_RESULTS, surface.valuation_result_fingerprint)
    )
    return MemoDependencySet(
        investment_id=investment_id,
        selected=selected,
        dependencies=tuple(
            sorted(entries, key=lambda item: (item.dependency_class.value, item.scope_id))
        ),
        surface=surface,
        resolved=True,
    )


# =============================================================================
# Freshness (Section 9)
# =============================================================================


def _stale_reason(dependency_class: MemoDependencyClass, scope_id: str, current: str | None) -> str:
    """One analyst-facing sentence for a dependency that no longer matches."""

    where = f" for {scope_id!r}" if scope_id else ""
    if current is None:
        return (
            f"The {dependency_class.value.replace('_', ' ')} this version was published against{where} can no "
            "longer be read at all -- the state it names has been removed, or the selected variant no longer "
            "resolves. The version's own content is unchanged and still readable."
        )
    return (
        f"The {dependency_class.value.replace('_', ' ')}{where} has changed since this version was published. "
        "The version still states what it stated; it is no longer current."
    )


def freshness(
    version: InvestmentMemoVersion, current: MemoDependencySet
) -> MemoFreshnessReport:
    """One published version's freshness against the current state (Section 9).

    A version is ``CURRENT`` only when every dependency it recorded still
    matches. Otherwise it is ``STALE`` with the changed classes named, in
    most-specific-first order.

    A dependency the current state cannot compute is stale with
    ``current_fingerprint = None``, never quietly equal and never an error: "the
    Strategy was deleted" is a real answer an analyst needs."""

    now = current.by_key()
    stale = [
        MemoStaleDependency(
            dependency_class=entry.dependency_class,
            scope_id=entry.scope_id,
            published_fingerprint=entry.fingerprint,
            current_fingerprint=now.get((entry.dependency_class, entry.scope_id)),
            reason=_stale_reason(
                entry.dependency_class,
                entry.scope_id,
                now.get((entry.dependency_class, entry.scope_id)),
            ),
        )
        for entry in version.dependencies
        if now.get((entry.dependency_class, entry.scope_id)) != entry.fingerprint
    ]
    order = {item: index for index, item in enumerate(DEPENDENCY_REPORT_ORDER)}
    stale.sort(key=lambda item: (order.get(item.dependency_class, 99), item.scope_id))
    return MemoFreshnessReport(
        version_id=version.version_id,
        version_number=version.version_number,
        freshness=MemoFreshness.CURRENT if not stale else MemoFreshness.STALE,
        stale_dependencies=tuple(stale),
    )


def version_freshness(
    investment_id: str, version: InvestmentMemoVersion, *, db_path: Path | None = None
) -> MemoFreshnessReport:
    """One published version's freshness, reading the current state itself."""

    draft = store.get_memo_draft(investment_id, db_path=db_path)
    return freshness(
        version,
        dependency_set(
            investment_id, version.selected_decision, draft=draft, db_path=db_path
        ),
    )


# =============================================================================
# Publication (Section 9; R-H)
# =============================================================================


def _version_valuations(
    draft: InvestmentMemoDraft, surface: StructuredValuationSurface | None
) -> tuple[MemoVersionValuation, ...]:
    """The valuation views a version freezes with itself.

    Every authored view is frozen, so the version keeps the whole surface its
    committee could see -- but each one records whether the memo *selected* it
    for inclusion and whether the resolved Capital Structure *consumed* it. That
    distinction is what a later reader needs to know which views the version was
    actually required to resolve, and it is frozen rather than recomputed
    because the draft's selection moves on afterwards.

    ``consumed`` is claimed only for a view whose **complete Investment value**
    a consumer read (review correction). A consumer of one Unit's cell did not
    consume the whole view -- the Investment value may even be unavailable --
    so that exact-scope fact is frozen in the consumption record instead.

    An unavailable view is frozen too, with its typed reason and **no value**:
    a version that cited "no value at this timepoint" keeps saying exactly that,
    and is never later read as zero."""

    if surface is None:
        return ()
    selected = set(draft.selected_valuation_timepoint_ids)
    consumed = whole_view_consumed_timepoints(surface)
    return tuple(
        MemoVersionValuation(
            timepoint_id=view.timepoint_id,
            kind=view.kind.value,
            label=view.label,
            model_month=view.model_month,
            scope_kind=view.scope_kind.value,
            status=view.status.value,
            value=view.value,
            unavailable_reason=(
                None if view.unavailable is None else view.unavailable.reason_code.value
            ),
            unavailable_message=None if view.unavailable is None else view.unavailable.reason,
            selected=view.timepoint_id in selected,
            consumed=view.timepoint_id in consumed,
        )
        for view in surface.views
    )


def _consumed_requirements(surface: StructuredValuationSurface | None) -> tuple:
    """The exact-scope values the selected Capital Structure consumes from a
    **defined** view, in canonical order. A requirement naming a timepoint the
    Investment does not define is not a publication dependency -- the P7.10
    ``PctOfValue`` rule, which an LTV refinance follows -- because its consumer
    already reports the typed absence itself."""

    if surface is None:
        return ()
    defined = {view.timepoint_id for view in surface.views}
    return tuple(item for item in surface.consumed_requirements if item.timepoint_id in defined)


def whole_view_consumed_timepoints(surface: StructuredValuationSurface | None) -> set[str]:
    """The defined timepoints whose complete Investment value a consumer read.
    Only these may be called consumed as a whole view (review correction)."""

    return {
        requirement.timepoint_id
        for requirement in _consumed_requirements(surface)
        if requirement.unit_id is None
    }


def _consumed_scopes(surface: StructuredValuationSurface | None) -> dict[tuple[str, str, str], tuple]:
    """The consumed requirements grouped by exact scope, each group keeping
    every consumer kind that reads it, in canonical order. Grouping never
    erases provenance: a scope a funding and a refinance both read is one
    dependency with two consumers."""

    grouped: dict[tuple[str, str, str], list] = {}
    for requirement in _consumed_requirements(surface):
        grouped.setdefault(requirement.scope_key(), []).append(requirement)
    return {key: tuple(grouped[key]) for key in sorted(grouped)}


def _scope_text(unit_id: str | None, db_path: Path | None) -> str:
    """The consumed scope as an analyst reads it: the Investment, or the Unit
    by its Deal name -- never an opaque identity."""

    from ..reporting.assembly import unit_display_name

    return "the Investment" if unit_id is None else unit_display_name(unit_id, db_path)


def _required_valuations(
    draft: InvestmentMemoDraft,
    surface: StructuredValuationSurface | None,
    *,
    db_path: Path | None = None,
) -> tuple[RequiredValuation, ...]:
    """The valuation views this draft is actually required to resolve.

    Two sources, and only two. A view the memo **selected** for inclusion must
    resolve **as a whole**, because the package would otherwise present a
    valuation with no value. A value the resolved Capital Structure
    **consumes** must resolve **at the exact scope its consumer reads** (P7.10
    Section 6 and R-E; Refinance V1 Section 14.3; review correction): a
    ``PctOfValue`` funding requires its position's scope, and an LTV-enabled
    refinance its event's scope -- one Unit's cell, or the complete Investment
    value. Another Unit's missing value or unapproved evidence is not this
    package's dependency, and does not block it.

    Everything else the analyst authored is exploratory. An unselected,
    unconsumed definition may sit unavailable indefinitely without blocking a
    memo that never leaned on it -- which is the correction Section 22 records:
    the earlier rule refused publication for any authored definition at all, and
    made an analyst delete their own working views to publish.

    Selection is read from the draft's explicit relationship, never inferred
    from display order, existence or recency. A selected definition the surface
    no longer holds is reported as ``NOT_AUTHORED`` rather than quietly dropped:
    it was selected, so its disappearance is a refusal. A selected view already
    requires every scope of itself, so a consumption of it adds nothing.

    A consumed requirement's refusal names what consumes it, typed
    (``consumers``), and its detail is rebuilt from typed facts only: the
    scope by its analyst-facing name and the reason code's analyst sentence.
    No upstream message, and so no opaque identity, is quoted."""

    if surface is None:
        return ()
    from ..memo.availability import AvailabilityStatus, UnavailableReasonCode
    from ..reporting.assembly import analyst_unavailable_sentence

    views = {view.timepoint_id: view for view in surface.views}
    selected = set(draft.selected_valuation_timepoint_ids)
    required: list[RequiredValuation] = []
    for timepoint_id in sorted(selected):
        view = views.get(timepoint_id)
        if view is None:
            required.append(
                RequiredValuation(
                    timepoint_id=timepoint_id,
                    reason=RequiredValuationReason.SELECTED,
                    available=False,
                    unavailable_reason=UnavailableReasonCode.NOT_AUTHORED.value,
                    unavailable_detail="No valuation definition exists for this timepoint.",
                )
            )
            continue
        required.append(
            RequiredValuation(
                timepoint_id=timepoint_id,
                reason=RequiredValuationReason.SELECTED,
                available=view.status is AvailabilityStatus.AVAILABLE,
                unavailable_reason=None if view.unavailable is None else view.unavailable.reason_code.value,
                unavailable_detail="" if view.unavailable is None else view.unavailable.reason,
            )
        )
    for (timepoint_id, _, unit_token), group in _consumed_scopes(surface).items():
        if timepoint_id in selected:
            continue
        view = views[timepoint_id]
        unit_id = unit_token or None  # '' is the Investment scope, as the key spells it
        if unit_id is None:  # the complete Investment value
            available = view.status is AvailabilityStatus.AVAILABLE
            state = view.unavailable
        else:
            cell = next((item for item in view.unit_views if item.unit_id == unit_id), None)
            available = cell is not None and cell.status is AvailabilityStatus.AVAILABLE
            state = None if cell is None else cell.unavailable
        code = None if available or state is None else state.reason_code.value
        detail = ""
        if not available:
            detail = (
                f"The value required is that of {_scope_text(unit_id, db_path)}. "
                f"{analyst_unavailable_sentence(code)}"
            )
        required.append(
            RequiredValuation(
                timepoint_id=timepoint_id,
                reason=RequiredValuationReason.CONSUMED,
                available=available,
                unavailable_reason=code,
                unavailable_detail=detail,
                consumers=tuple(sorted({item.consumer for item in group}, key=lambda kind: kind.value)),
                label=view.label,
            )
        )
    return tuple(required)


def unexecuted_refinances(
    investment_id: str, selected: SelectedDecision, *, db_path: Path | None = None
) -> tuple[str, ...]:
    """Why each refinance of the selected cell did not execute, in the
    analyst's words -- the one fact the refinance publication refusal reads
    (Refinance V1 Stage 3, which removed the temporary report gate).

    Empty for a structure with no capital event, which is never analysed here,
    and when every refinance executed. A Strategy whose Capital Structure does
    not resolve is not judged here: publication already refuses it for that
    reason. Once a refinance is known to be configured, the check fails
    closed: an analysis that cannot be read is a refusal, never a pass."""

    try:
        resolved = resolve_variant_capital_structure(investment_id, selected.strategy_id, db_path=db_path)
    except (InvestmentNotFoundError, DealNotFoundError):
        raise
    except Exception:  # noqa: BLE001 -- an unresolvable selection is refused on its own terms
        return ()
    if not has_capital_events(resolved.capital_structure):
        return ()
    try:
        analysis = analyze_structured_variant(
            investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
        )
    except (InvestmentNotFoundError, DealNotFoundError):
        raise
    except Exception:  # noqa: BLE001 -- fail closed: a refinance whose result cannot be read is never published
        return ("The refinance result of the selected analysis could not be determined, so it is not published.",)
    missed = not_executed(analysis.result)
    if not missed:
        return ()
    units = unit_names_of(tuple(analysis.result.unit_ids), db_path=db_path)
    labels = {
        timepoint.timepoint_id: timepoint.label
        for timepoint in store.list_valuation_timepoints(investment_id, db_path=db_path)
    }
    return tuple(
        f"“{event.label}” did not execute: "
        + (event_reason_sentence(event, unit_names=units, valuation_labels=labels) or "it has no result here.")
        for event in missed
    )


def publication_context(
    investment_id: str,
    draft: InvestmentMemoDraft,
    dependencies: MemoDependencySet,
    *,
    db_path: Path | None = None,
) -> PublicationContext:
    """Everything the publication rules need, gathered from the current state.

    This module reads; ``anchor.memo.publication`` judges. Keeping the judgment
    out of here is what stops a second, drifting set of prerequisites growing
    beside the ratified one."""

    selected = draft.selected_decision
    evidence = {
        item.evidence_id: item
        for item in store.list_evidence_references(investment_id, db_path=db_path)
    }
    if selected is None:
        return PublicationContext(
            strategy_exists=False,
            scenario_exists=False,
            perspective_exists=False,
            cell_resolves=False,
            cell_detail="",
            evidence=evidence,
            required_valuations=(),
        )
    try:
        _selected_strategy(investment_id, selected.strategy_id, db_path)
        strategy_exists = True
    except StrategyNotFoundError:
        strategy_exists = False
    try:
        _selected_scenario(investment_id, selected.scenario_id, db_path)
        scenario_exists = True
    except ScenarioNotFoundError:
        scenario_exists = False
    return PublicationContext(
        strategy_exists=strategy_exists,
        scenario_exists=scenario_exists,
        perspective_exists=perspective_exists(investment_id, selected, db_path=db_path),
        cell_resolves=dependencies.resolved,
        cell_detail=dependencies.detail,
        evidence=evidence,
        required_valuations=_required_valuations(draft, dependencies.surface, db_path=db_path),
        unexecuted_refinances=unexecuted_refinances(investment_id, selected, db_path=db_path),
    )


def publication_refusals_for(
    investment_id: str,
    draft: InvestmentMemoDraft,
    dependencies: MemoDependencySet | None,
    *,
    db_path: Path | None = None,
) -> tuple:
    """Every reason the draft may not be published right now, or ``()``.

    Read-only, and deliberately separate from publishing: the product disables
    the publish action with these reasons rather than letting an analyst
    discover them by failing (Section 14). It asks exactly the same rules
    ``publish`` asks, so the two can never disagree about whether a package is
    ready."""

    from ..memo.publication import publication_refusals

    resolved = dependencies if dependencies is not None else _unresolved_set(investment_id)
    return publication_refusals(
        draft, publication_context(investment_id, draft, resolved, db_path=db_path)
    )


def _unresolved_set(investment_id: str) -> MemoDependencySet:
    """The empty ledger for a draft that has not named a decision cell yet.
    Nothing is computed for it, because there is no variant to compute
    against."""

    return MemoDependencySet(
        investment_id=investment_id,
        selected=SelectedDecision(
            strategy_id="",
            scenario_id="",
            perspective=DecisionPerspectiveKind.PROJECT,
            position_id=None,
            partner_id=None,
        ),
        dependencies=(),
        surface=None,
        resolved=False,
    )


def publish(investment_id: str, *, db_path: Path | None = None) -> InvestmentMemoVersion:
    """Publish the Investment's draft as an immutable version (Section 9; R-H).

    Fails closed: every prerequisite is checked against the *current* state
    before anything is written, and a refusal raises ``PublicationRefusedError``
    with every specific reason. A partially complete or internally inconsistent
    decision package is never published.

    The store's single transaction then writes the version, its frozen content,
    its frozen evidence, the valuation views it cites, its whole dependency
    ledger **and the report artifact it is issued as** -- or none of them.

    **The report is assembled and rendered once, here** (Stage 4 Correction 1),
    from the same resolved state the prerequisites were checked against, and
    stored beside the version. Every later read returns those stored bytes, so a
    published decision document does not change when the underwriting, the
    Strategy, the Scenario, the Capital Structure, a valuation definition or
    this presentation code does. Producing an updated report means publishing a
    new version.

    If assembly or PDF rendering fails, the whole publication fails: the
    transaction rolls back and no version is left behind whose document could
    never be produced.

    The draft is left exactly as it was. Publishing copies; it does not consume,
    and it never edits an earlier version: republishing creates a new one."""

    draft = store.get_memo_draft(investment_id, db_path=db_path)
    if draft is None:
        raise MemoNotFoundError(investment_id)
    selected = draft.selected_decision
    dependencies = (
        _unresolved_set(investment_id)
        if selected is None
        else dependency_set(investment_id, selected, draft=draft, db_path=db_path)
    )
    require_publishable(
        draft, publication_context(investment_id, draft, dependencies, db_path=db_path)
    )

    cited = tuple(
        item
        for item in store.list_evidence_references(investment_id, db_path=db_path)
        if item.evidence_id in set(draft.cited_evidence_ids())
    )
    content_fingerprint = fingerprint_memo_content(draft, evidence=cited)
    published_fingerprint = fingerprint_published_version(
        memo_content_fingerprint=content_fingerprint,
        dependencies=[
            (entry.dependency_class.value, entry.scope_id, entry.fingerprint)
            for entry in dependencies.dependencies
        ],
    )
    # Imported here rather than at module scope: `anchor.reporting` reads this
    # module's own analysis seam, and a top-level import would make the two
    # circular. The publication path is the only thing in this module that
    # needs a report at all.
    from ..reporting.artifact import build_artifact
    from ..reporting.assembly import (
        analysis_for_selected_cell,
        build_version_package,
        export_filename,
    )
    from ..reporting.pdf import render_memo_pdf

    analysis = analysis_for_selected_cell(investment_id, selected, db_path=db_path)

    def _artifact(version: InvestmentMemoVersion):
        """The report this version is issued as, assembled and rendered inside
        the publication transaction so a failure leaves nothing behind."""

        package = build_version_package(investment_id, version, analysis, db_path=db_path)
        document = render_memo_pdf(package)
        return build_artifact(
            version.version_id,
            package,
            document,
            export_filename(package),
            _page_count(document),
        )

    version, _ = store.publish_memo_version(
        investment_id,
        draft=draft,
        evidence=cited,
        valuations=_version_valuations(draft, dependencies.surface),
        dependencies=dependencies.dependencies,
        memo_content_fingerprint=content_fingerprint,
        published_fingerprint=published_fingerprint,
        build_artifact=_artifact,
        # Schema 17 (review correction): the exact-scope values consumed and
        # what consumed each, frozen with the version beside the whole-view
        # ``consumed`` flag.
        consumed_valuations=_consumed_requirements(dependencies.surface),
        db_path=db_path,
    )
    return version


def _page_count(document: bytes) -> int:
    """How many pages the issued PDF has, read from the document itself.

    Recorded so a reader can tell at a glance whether the file they hold is the
    whole thing. Read with the library the project already depends on for PDF
    inspection; a document this cannot parse is refused here rather than stored
    as an artifact nobody can open."""

    import io

    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(document)).pages)
