"""Phase 7 Gate P7.8B -- the structured Capital Structure variant service.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
3 (P-1, P-3, P-4), 7.5, 12 and 15.4, and the P7.8A decision record
``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md``; those documents
govern on any discrepancy.

The one place a *persisted* Capital Structure meets the P7.8A executor::

    the Project variant                       the existing authority, unchanged:
            |                                 Base -> Strategy -> Scenario ->
            |                                 validation -> the D6 engine (and,
            |                                 for a visible Investment, P7.6
            |                                 consolidation)
            v
    the resolved Capital Structure            the Investment's Base structure,
            |                                 replaced whole by the Strategy's
            |                                 own where it states one
            v
    execute_unit / execute_investment_capital_structure       StructuredCapitalResult

**Downstream only (P-4).** Nothing here re-runs, re-resolves or corrects a
Project result: the structured layer starts from the *completed* one. Editing a
Capital Structure therefore cannot change NOI, project cash flow, an
acquisition loan or a consolidated series, and cannot make a Project result
stale -- only the structured analysis and the Position perspective move.

**Two roots, one service.** A hidden one-unit Investment executes its Deal as a
standalone Unit, and a visible Investment executes every Unit scope and then the
Investment scope. The dispatch happens once, here; there is no second route
family, no second resolver and no second engine.

**One coherent read.** A variant's result and the inputs read beside it must
belong to one state. Each pathway analyses and then inspects, and refuses the
pair with ``StructuredVariantConflictError`` if the Project fingerprint moved
between the two -- the P7.5 Decision Matrix rule, applied to one variant.

**Recomputed, never cached (Q14).** P7.8B stores no structured result. A cached
Project result may still serve the upstream half, and its status is reported as
operational metadata; the structured half is always computed. A cache is an
optimization, never financial authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..analysis.contracts import LeaseLevelAcquisitionResults
from ..analysis.strategy import (
    BASE_STRATEGY_ID,
    StrategyDefinition,
    resolve_capital_structure,
    strategy_capital_structure,
)
from ..capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    CapitalStructureUnit,
    PctOfValue,
    PositionClass,
    PositionScope,
)
from ..capital_structure.execution import (
    execute_investment_capital_structure,
    execute_unit_capital_structure,
)
from ..capital_structure.execution_contracts import StructuredCapitalResult
from ..capital_structure.validation import economic_order
from ..contracts import AcquisitionTerms, acquisition_terms_from_inputs
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults
from ..valuation.contracts import InvestmentValuationResult, ValuationTimepoint
from ..valuation.funding import ValuationAuthority
from . import store
from .fingerprint import fingerprint_structured_source
from .valuation_views import (
    EvidenceBlockedValuation,
    ValuationUnitSource,
    ValuationView,
    blocked_records,
    build_variant_inputs,
    consumed_valuations,
    evidence_blocked_timepoints,
    funding_authority,
    resolve_views,
    view_fingerprints,
)
from .investment_variants import (
    analyze_investment_variant,
    inspect_investment_variant_inputs,
    investment_variant_fingerprint,
)
from .variants import ResolvedScenarioInputs, VariantResults, analyze_variant, inspect_variant_inputs, variant_fingerprint


class StructuredRootKind(StrEnum):
    """Which analysis root executes the structure.

    - ``HIDDEN_UNIT``: a hidden one-unit Investment. Its root is the Unit, so
      its positions are Unit-scoped and an authored Common Equity marker names
      the Unit's residual. The UI still calls it a Deal.
    - ``VISIBLE_INVESTMENT``: every Unit scope clears against its own Unit's
      cash, and the Investment scope then reads the consolidated residual."""

    HIDDEN_UNIT = "hidden_unit"
    VISIBLE_INVESTMENT = "visible_investment"


class CapitalStructureSource(StrEnum):
    """Where the executed structure came from: the Investment's Base structure,
    or this Strategy's own whole replacement."""

    BASE = "base"
    STRATEGY = "strategy"


class StructuredVariantConflictError(RuntimeError):
    """The saved underwriting changed while one structured variant was being
    analysed, so its result and the inputs read beside it no longer describe one
    state. Nothing is reported; the analyst runs it again."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedCapitalStructure:
    """The structure one variant executes, and which owner stated it."""

    capital_structure: CapitalStructure
    source: CapitalStructureSource


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredVariantFingerprint:
    """The two fingerprints of one structured variant, beside its identity.

    ``project_source_fingerprint`` is the existing Project variant fingerprint,
    unchanged and still the authority for the Project result and its cache.
    ``structured_source_fingerprint`` is that fingerprint plus the resolved
    structure's economics -- and, when the structure is empty, *exactly* it
    (FP-2).

    From P7.10 Stage 2 the structured fingerprint additionally covers any
    valuation a ``PctOfValue`` rule actually consumes (contract Section 6). A
    structure with no such rule -- which is every structure authored before that
    gate -- hashes exactly what it hashed at P7.8B."""

    investment_id: str
    strategy_id: str
    scenario_id: str
    root_kind: StructuredRootKind
    unit_ids: tuple[str, ...]
    capital_structure: CapitalStructure
    capital_structure_source: CapitalStructureSource
    project_source_fingerprint: str
    structured_source_fingerprint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredVariantAnalysis:
    """One analysed structured variant: the identity, both fingerprints, the
    resolved structure, and the P7.8A result.

    ``project_cache_status`` is operational metadata about the *Project* half
    (a cached Quick or Detailed result served, computed, or bypassed), never
    investment information and never a statement about the structured half,
    which is always recomputed.

    **This contract is a wire contract.** ``anchor.api`` serialises it field by
    field, so a field added here changes the pre-existing P7.8B analysis
    response for every caller. P7.10 Stage 2 therefore adds nothing to it: its
    valuation surface is ``StructuredValuationSurface`` below, reached by its
    own function and its own route."""

    investment_id: str
    strategy_id: str
    scenario_id: str
    root_kind: StructuredRootKind
    unit_ids: tuple[str, ...]
    hold_period: int
    capital_structure: CapitalStructure
    capital_structure_source: CapitalStructureSource
    project_source_fingerprint: str
    structured_source_fingerprint: str
    project_cache_status: str
    result: StructuredCapitalResult


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredValuationSurface:
    """The P7.10 Stage 2 valuation surface of one structured variant.

    Separate from ``StructuredVariantAnalysis`` on purpose. That contract is the
    P7.8B analysis response, serialised field by field by ``anchor.api``, and a
    field added to it would change the bytes every existing caller receives.

    ``views`` holds every authored valuation timepoint of this Investment,
    resolved against *this* variant -- available with a value, or unavailable
    with a typed reason and no value at all.

    ``evidence_blocked`` names the definitions the evidence gate withheld from
    the funding authority, so an unresolved ``PctOfValue`` funding is reported
    with the specific reason rather than a misleading "timepoint not found".

    ``consumed_timepoint_ids`` are the timepoints a ``PctOfValue`` rule actually
    names -- the ones that participate in the structured financial identity
    (Section 6). A report-only valuation is deliberately absent.

    ``valuation_definition_fingerprint`` and ``valuation_result_fingerprint``
    are the two Section 10 identities, computed here because this is where the
    authored definitions and the resolved results are both in hand. Computing
    them anywhere else would mean reading the definitions a second time, and a
    second read can see a different state."""

    investment_id: str
    strategy_id: str
    scenario_id: str
    unit_ids: tuple[str, ...]
    hold_period: int
    views: tuple[ValuationView, ...]
    evidence_blocked: tuple[EvidenceBlockedValuation, ...]
    consumed_timepoint_ids: tuple[str, ...]
    project_source_fingerprint: str
    structured_source_fingerprint: str
    valuation_definition_fingerprint: str
    valuation_result_fingerprint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionPerspective:
    """One addressable ``POSITION(position_id)`` perspective of an Investment.

    The union of the stable position ids in the Investment's Base structure and
    in every Strategy's own, with the class and scope that identity keeps
    everywhere (P-8, enforced at every save). ``name`` is presentation: the Base
    structure's name where it has one, else the first Strategy's, so the analyst
    never has to select a UUID.

    ``present_in_base`` and ``strategy_ids`` say where the position is actually
    present once each Strategy is resolved -- a Strategy that inherits the Base
    structure includes every Base position -- which is what makes a matrix cell
    "not applicable to this perspective" rather than invalid. No financial
    figure is computed here."""

    position_id: str
    name: str
    position_class: PositionClass
    scope: PositionScope
    is_common_equity_marker: bool
    present_in_base: bool
    strategy_ids: tuple[str, ...]


def _root_kind(investment_id: str, db_path: Path | None) -> StructuredRootKind:
    investment = store.get_investment(investment_id, db_path=db_path)
    return (
        StructuredRootKind.HIDDEN_UNIT
        if investment.hidden
        else StructuredRootKind.VISIBLE_INVESTMENT
    )


def _strategy(investment_id: str, strategy_id: str, db_path: Path | None) -> StrategyDefinition | None:
    """The persisted Strategy the key names, or ``None`` for the reserved
    implicit Base key."""

    if strategy_id == BASE_STRATEGY_ID:
        return None
    return store.get_strategy(investment_id, strategy_id, db_path=db_path).strategy


def resolve_variant_capital_structure(
    investment_id: str, strategy_id: str, *, db_path: Path | None = None
) -> ResolvedCapitalStructure:
    """The Capital Structure the variant executes: the Investment's Base
    structure, replaced **whole** by this Strategy's own where it states one
    (ST-2). Read-only, and it materializes nothing."""

    strategy = _strategy(investment_id, strategy_id, db_path)
    base = store.get_base_capital_structure(investment_id, db_path=db_path)
    own = strategy_capital_structure(strategy)
    return ResolvedCapitalStructure(
        capital_structure=resolve_capital_structure(base, strategy),
        source=CapitalStructureSource.BASE if own is None else CapitalStructureSource.STRATEGY,
    )


def _project_results(results: VariantResults) -> AcquisitionResults:
    """The Project ``AcquisitionResults`` inside any mode's envelope. It selects
    a field and computes nothing."""

    match results:
        case AcquisitionResults():
            return results
        case DetailedAcquisitionResults():
            return results.results
        case LeaseLevelAcquisitionResults():
            return results.results
        case _:
            raise TypeError(f"Not a variant result: {type(results).__qualname__}.")


def _resolved_terms(resolved: ResolvedScenarioInputs) -> AcquisitionTerms:
    """The ``AcquisitionTerms`` the variant ran with. A Quick Unit's are the
    existing projection of its inputs -- the same one the engine used -- and
    every other mode states them directly. Nothing is re-derived."""

    terms = getattr(resolved, "terms", None)
    if terms is None:
        return acquisition_terms_from_inputs(resolved.inputs)  # type: ignore[union-attr]
    return terms


def _conflict() -> StructuredVariantConflictError:
    return StructuredVariantConflictError(
        "The saved underwriting changed while the structured analysis was running. Run it again."
    )


# =============================================================================
# Phase 7 Gate P7.10 Stage 2 -- the persisted valuation seam
#
# ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 6, 6.1 and 6.2.
#
# P7.7 represents ``PctOfValue(timepoint_id, pct)``; P7.8 refuses to execute it
# without an authority; P7.10 Stage 1 built the authority and left *supplying*
# one to Stage 2. This is where the analyst's stored definitions become that
# authority, and it is the only place they do.
#
# **The closing-only boundary is untouched** (Section 6.1). The authority is
# offered for every timepoint the Investment defines; the P7.8 executor still
# funds positions at closing only. A later Stabilized or Custom valuation
# therefore resolves to a real reporting value that no funding event can
# consume -- a product limitation with a named reason, and never a zero or a
# fallback to the acquisition price.
#
# **A consumed valuation is an economic dependency** (Section 6). Only the
# timepoints a ``PctOfValue`` rule actually names reach the structured
# fingerprint; a report-only valuation moves memo freshness and deliberately
# not the underlying Acquisition analysis. A structure with no such rule hashes
# exactly what it hashed at P7.8B.
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class _ValuationContext:
    """One variant's resolved valuations, and what they mean for funding.

    ``timepoints`` is the exact definition set the views were resolved from,
    carried so the valuation identities are computed from the same read rather
    than from a second one that could see a different state."""

    timepoints: tuple[ValuationTimepoint, ...]
    views: tuple[ValuationView, ...]
    authority: ValuationAuthority | None
    blocked: Mapping[str, Mapping[str, str]]
    consumed: Mapping[str, InvestmentValuationResult]


def pct_of_value_timepoints(capital_structure: CapitalStructure) -> tuple[str, ...]:
    """Every valuation timepoint a ``PctOfValue`` funding rule names, sorted.

    Empty for every structure authored before P7.10, which is what keeps the
    structured fingerprint byte-identical for all of them."""

    return tuple(
        sorted(
            {
                event.amount_rule.timepoint_id
                for position in capital_structure.positions
                for event in position.funding
                if isinstance(event.amount_rule, PctOfValue)
            }
        )
    )


def _valuation_context(
    investment_id: str,
    strategy_id: str,
    scenario_id: str,
    capital_structure: CapitalStructure,
    units: Sequence[ValuationUnitSource],
    db_path: Path | None,
) -> _ValuationContext:
    """Resolve this Investment's stored valuation definitions against this
    variant's completed results.

    The Units are passed in rather than re-loaded: the caller has already
    resolved and analysed them, and resolving again could read a state that
    moved between the two reads.

    An Investment with no stored definition produces no view, no authority and
    no consumed valuation -- which is exactly its state before this gate, and is
    why every pre-P7.10 structure keeps its identity."""

    timepoints = store.list_valuation_timepoints(investment_id, db_path=db_path)
    if not timepoints:
        return _ValuationContext(
            timepoints=(), views=(), authority=None, blocked={}, consumed={}
        )
    evidence = {
        item.evidence_id: item
        for item in store.list_evidence_references(investment_id, db_path=db_path)
    }
    variant = build_variant_inputs(investment_id=investment_id, units=units)
    views = resolve_views(timepoints, variant=variant, evidence=evidence)
    blocked = evidence_blocked_timepoints(timepoints, evidence)
    return _ValuationContext(
        timepoints=timepoints,
        views=views,
        authority=funding_authority(investment_id=investment_id, views=views, blocked=blocked),
        blocked=blocked,
        consumed=consumed_valuations(
            views=views, timepoint_ids=pct_of_value_timepoints(capital_structure)
        ),
    )


def _structured_fingerprint(
    *,
    project_source_fingerprint: str,
    capital_structure: CapitalStructure,
    consumed: Mapping[str, InvestmentValuationResult],
) -> str:
    """The structured source fingerprint, with any consumed valuation in it.

    One helper so the fingerprint-only pathway and the analysis pathway cannot
    drift: a variant's reported identity must be the same whichever door the
    caller came through, or the P7.5 coherence check and the P7.9 Partnership
    fingerprint built on top of it would both be reading a different variant
    than they thought."""

    return fingerprint_structured_source(
        project_source_fingerprint=project_source_fingerprint,
        capital_structure=capital_structure,
        consumed_valuations=consumed,
    )


def structured_variant_fingerprint(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> StructuredVariantFingerprint:
    """Both fingerprints of one structured variant, without executing the
    Capital Structure.

    The Project fingerprint comes from the existing per-root authority and is
    untouched by the Capital Structure; the structured one is that fingerprint
    plus the resolved structure's economics, and *is* that fingerprint when the
    structure is empty.

    **When, and only when, a ``PctOfValue`` rule names a timepoint**, the
    valuation it consumes is part of that identity (Section 6), so this function
    resolves the Project variant to obtain it. That costs a Project analysis for
    those structures and nothing at all for every other one -- and it is not
    optional: an identity that differed between this function and
    ``analyze_structured_variant`` would silently mean two different variants."""

    root_kind = _root_kind(investment_id, db_path)
    resolved = resolve_variant_capital_structure(investment_id, strategy_id, db_path=db_path)
    if root_kind is StructuredRootKind.HIDDEN_UNIT:
        project = variant_fingerprint(investment_id, strategy_id, scenario_id, db_path=db_path)
        project_fingerprint, unit_ids = project.source_fingerprint, (project.unit_id,)
    else:
        investment = investment_variant_fingerprint(
            investment_id, strategy_id, scenario_id, db_path=db_path
        )
        project_fingerprint = investment.source_fingerprint
        unit_ids = tuple(
            sorted(
                membership.unit_id
                for membership in store.get_visible_investment(
                    investment_id, db_path=db_path
                ).units
            )
        )
    consumed: Mapping[str, InvestmentValuationResult] = {}
    if pct_of_value_timepoints(resolved.capital_structure):
        read = _variant_units(investment_id, strategy_id, scenario_id, db_path)
        consumed = _valuation_context(
            investment_id,
            strategy_id,
            scenario_id,
            resolved.capital_structure,
            read.units,
            db_path,
        ).consumed
    return StructuredVariantFingerprint(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        root_kind=root_kind,
        unit_ids=unit_ids,
        capital_structure=resolved.capital_structure,
        capital_structure_source=resolved.source,
        project_source_fingerprint=project_fingerprint,
        structured_source_fingerprint=_structured_fingerprint(
            project_source_fingerprint=project_fingerprint,
            capital_structure=resolved.capital_structure,
            consumed=consumed,
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class _VariantUnits:
    """One coherent read of a variant's Project half, for both roots.

    Factored out of the two analysis pathways so the valuation half and the
    execution half cannot read different states: both are built from *this* one
    read, whose analysis and inspection were already proven to agree.

    ``consolidated`` is the visible Investment's completed consolidation and is
    ``None`` for the hidden one-unit root, which has none."""

    project_source_fingerprint: str
    units: tuple[ValuationUnitSource, ...]
    hold_period: int
    cache_status: str
    consolidated: object | None


def _variant_units(
    investment_id: str, strategy_id: str, scenario_id: str, db_path: Path | None
) -> _VariantUnits:
    """Every Unit of this variant with its resolved terms and completed Project
    results.

    It analyses and then inspects, and refuses the pair with
    ``StructuredVariantConflictError`` if the Project fingerprint moved between
    the two -- the P7.5 coherence rule, unchanged and now applied once for both
    the Capital Structure and the valuations."""

    if _root_kind(investment_id, db_path) is StructuredRootKind.HIDDEN_UNIT:
        analysis = analyze_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
        inputs = inspect_variant_inputs(investment_id, strategy_id, scenario_id, db_path=db_path)
        if inputs.source_fingerprint != analysis.source_fingerprint:
            raise _conflict()
        terms = _resolved_terms(inputs.resolved)
        return _VariantUnits(
            project_source_fingerprint=analysis.source_fingerprint,
            units=(
                ValuationUnitSource(
                    unit_id=analysis.unit_id,
                    terms=terms,
                    results=_project_results(analysis.results),
                ),
            ),
            hold_period=terms.hold_period,
            cache_status=analysis.cache_status.value,
            consolidated=None,
        )

    investment_analysis = analyze_investment_variant(
        investment_id, strategy_id, scenario_id, db_path=db_path
    )
    inputs = inspect_investment_variant_inputs(
        investment_id, strategy_id, scenario_id, db_path=db_path
    )
    if inputs.source_fingerprint != investment_analysis.source_fingerprint:
        raise _conflict()
    return _VariantUnits(
        project_source_fingerprint=investment_analysis.source_fingerprint,
        units=tuple(
            ValuationUnitSource(
                unit_id=unit_inputs.unit_id,
                terms=_resolved_terms(unit_inputs.resolved),
                results=_project_results(unit_result.results),
            )
            for unit_inputs, unit_result in zip(
                inputs.units, investment_analysis.unit_results, strict=True
            )
        ),
        hold_period=investment_analysis.hold_period,
        cache_status=investment_analysis.cache_status.value,
        consolidated=investment_analysis.consolidated_results,
    )


def _execute_root(
    root_kind: StructuredRootKind,
    read: _VariantUnits,
    capital_structure: CapitalStructure,
    authority: ValuationAuthority | None,
) -> StructuredCapitalResult:
    """Run the P7.8A executor for whichever root this is, on the completed
    Project results already read.

    ``authority`` is the P7.10 valuation authority a ``PctOfValue`` funding is
    sized from, or ``None`` when this Investment defines no valuation at all --
    which is exactly the pre-P7.10 call, and is why every existing structure
    executes identically. The P7.8 closing-only funding window is unchanged in
    both cases."""

    if root_kind is StructuredRootKind.HIDDEN_UNIT:
        (unit,) = read.units
        return execute_unit_capital_structure(
            unit_id=unit.unit_id,
            terms=unit.terms,
            results=unit.results,
            capital_structure=capital_structure,
            valuations=authority,
        )
    return execute_investment_capital_structure(
        units=tuple(
            CapitalStructureUnit(unit_id=unit.unit_id, terms=unit.terms, results=unit.results)
            for unit in read.units
        ),
        consolidated=read.consolidated,  # type: ignore[arg-type]
        capital_structure=capital_structure,
        valuations=authority,
    )


def analyze_structured_variant(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> StructuredVariantAnalysis:
    """Analyse one structured variant end to end.

    Raises what each layer raises, and never blurs them: the Project layer's
    ``StrategyValidationError``, ``ScenarioValidationError``,
    ``LeaseValidationError`` or ``InvestmentVariantValidationError`` for an
    invalid Project variant; ``CapitalStructureValidationError`` for a structure
    that is not a valid contract for this analysis; and
    ``CapitalStructureExecutionError`` for a valid structure this Project state
    cannot execute (an over-funded closing, a convention P7.8 does not schedule).

    An **unresolved Funding Requirement is none of those**. It is a valid,
    deterministic economic result: the analysis succeeds, the position's returns
    are N/A with their reason, and its structural metrics stand. From P7.10
    Stage 2 that includes a ``PctOfValue`` funding whose valuation did not
    resolve: the analysis succeeds and the funding is reported unresolved with
    its specific reason, never as an error and never as zero."""

    root_kind = _root_kind(investment_id, db_path)
    resolved = resolve_variant_capital_structure(investment_id, strategy_id, db_path=db_path)
    read = _variant_units(investment_id, strategy_id, scenario_id, db_path)
    valuation = _valuation_context(
        investment_id, strategy_id, scenario_id, resolved.capital_structure, read.units, db_path
    )
    result = _execute_root(root_kind, read, resolved.capital_structure, valuation.authority)
    return StructuredVariantAnalysis(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        root_kind=root_kind,
        unit_ids=tuple(unit.unit_id for unit in read.units),
        hold_period=read.hold_period,
        capital_structure=resolved.capital_structure,
        capital_structure_source=resolved.source,
        project_source_fingerprint=read.project_source_fingerprint,
        structured_source_fingerprint=_structured_fingerprint(
            project_source_fingerprint=read.project_source_fingerprint,
            capital_structure=resolved.capital_structure,
            consumed=valuation.consumed,
        ),
        project_cache_status=read.cache_status,
        result=result,
    )


def analyze_structured_valuations(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> StructuredValuationSurface:
    """The P7.10 Stage 2 valuation surface of one structured variant.

    Its own function, and its own contract, deliberately: the P7.8B analysis
    response is a wire contract that predates this gate, and widening it would
    change every existing caller's bytes for a surface they did not ask for.

    It runs the same one coherent read and the same resolution as
    ``analyze_structured_variant`` -- there is no second pathway -- and reports
    the resolved views, the evidence-gate findings, and the two fingerprints the
    variant carries.

    Raises exactly what the structured analysis raises for an invalid variant.
    An unavailable valuation is not one of those: it is a successful, typed result."""

    resolved = resolve_variant_capital_structure(investment_id, strategy_id, db_path=db_path)
    read = _variant_units(investment_id, strategy_id, scenario_id, db_path)
    valuation = _valuation_context(
        investment_id, strategy_id, scenario_id, resolved.capital_structure, read.units, db_path
    )
    definition_fingerprint, result_fingerprint = view_fingerprints(
        timepoints=valuation.timepoints,
        views=valuation.views,
        variant_source_fingerprint=read.project_source_fingerprint,
    )
    return StructuredValuationSurface(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        unit_ids=tuple(unit.unit_id for unit in read.units),
        hold_period=read.hold_period,
        views=valuation.views,
        evidence_blocked=blocked_records(valuation.blocked),
        consumed_timepoint_ids=tuple(sorted(valuation.consumed)),
        project_source_fingerprint=read.project_source_fingerprint,
        structured_source_fingerprint=_structured_fingerprint(
            project_source_fingerprint=read.project_source_fingerprint,
            capital_structure=resolved.capital_structure,
            consumed=valuation.consumed,
        ),
        valuation_definition_fingerprint=definition_fingerprint,
        valuation_result_fingerprint=result_fingerprint,
    )


def position_perspectives(
    investment_id: str, *, db_path: Path | None = None
) -> tuple[PositionPerspective, ...]:
    """Every addressable Position perspective of the Investment: the union of
    the stable position ids its Base structure and its Strategies' own
    structures hold, in canonical economic order.

    The union, not an intersection: a position only one Strategy authors is
    still a perspective, and under the Strategies that do not hold it the matrix
    reports "not applicable to this perspective" rather than an absence of
    value. No financial metric is computed here."""

    structures = store.list_investment_capital_structures(investment_id, db_path=db_path)
    strategy_ids = [entry.strategy_id for entry in structures.strategies]
    inheriting = [
        record.strategy.strategy_id
        for record in store.list_strategies(investment_id, db_path=db_path)
        if record.strategy.strategy_id not in set(strategy_ids)
    ]

    named: dict[str, CapitalPosition] = {}
    in_base: set[str] = set()
    holders: dict[str, list[str]] = {}
    for position in structures.base.positions:
        named.setdefault(position.position_id, position)
        in_base.add(position.position_id)
        holders.setdefault(position.position_id, []).extend(inheriting)
    for entry in structures.strategies:
        for position in entry.capital_structure.positions:
            named.setdefault(position.position_id, position)
            holders.setdefault(position.position_id, []).append(entry.strategy_id)

    return tuple(
        PositionPerspective(
            position_id=position.position_id,
            name=position.name,
            position_class=position.position_class,
            scope=position.scope,
            is_common_equity_marker=position.position_class is PositionClass.COMMON_EQUITY,
            present_in_base=position.position_id in in_base,
            strategy_ids=tuple(sorted(set(holders.get(position.position_id, ())))),
        )
        for position in economic_order(named.values())
    )


def position_perspective(
    investment_id: str, position_id: str, *, db_path: Path | None = None
) -> PositionPerspective | None:
    """One Position perspective by id, or ``None`` when no stored structure of
    this Investment holds it."""

    for perspective in position_perspectives(investment_id, db_path=db_path):
        if perspective.position_id == position_id:
            return perspective
    return None


def resolved_position(
    capital_structure: CapitalStructure, position_id: str
) -> CapitalPosition | None:
    """The position ``position_id`` in one resolved structure, or ``None`` when
    that structure does not hold it -- which is exactly what makes a cell not
    applicable to the perspective, never zero and never invalid."""

    for position in capital_structure.positions:
        if position.position_id == position_id:
            return position
    return None
