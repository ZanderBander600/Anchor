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
from . import store
from .fingerprint import fingerprint_structured_source
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
    (FP-2)."""

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
    which is always recomputed."""

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


def structured_variant_fingerprint(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> StructuredVariantFingerprint:
    """Both fingerprints of one structured variant, without executing anything.

    The Project fingerprint comes from the existing per-root authority and is
    untouched by the Capital Structure; the structured one is that fingerprint
    plus the resolved structure's economics, and *is* that fingerprint when the
    structure is empty."""

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
    return StructuredVariantFingerprint(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        root_kind=root_kind,
        unit_ids=unit_ids,
        capital_structure=resolved.capital_structure,
        capital_structure_source=resolved.source,
        project_source_fingerprint=project_fingerprint,
        structured_source_fingerprint=fingerprint_structured_source(
            project_source_fingerprint=project_fingerprint,
            capital_structure=resolved.capital_structure,
        ),
    )


def _analyze_hidden_unit(
    investment_id: str,
    strategy_id: str,
    scenario_id: str,
    capital_structure: CapitalStructure,
    db_path: Path | None,
) -> tuple[StructuredCapitalResult, str, str, int, tuple[str, ...]]:
    """The hidden one-unit pathway: the existing variant analysis, then the
    P7.8A Unit executor on its completed results."""

    analysis = analyze_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
    inputs = inspect_variant_inputs(investment_id, strategy_id, scenario_id, db_path=db_path)
    if inputs.source_fingerprint != analysis.source_fingerprint:
        raise _conflict()
    terms = _resolved_terms(inputs.resolved)
    result = execute_unit_capital_structure(
        unit_id=analysis.unit_id,
        terms=terms,
        results=_project_results(analysis.results),
        capital_structure=capital_structure,
    )
    return (
        result,
        analysis.source_fingerprint,
        analysis.cache_status.value,
        terms.hold_period,
        (analysis.unit_id,),
    )


def _analyze_visible_investment(
    investment_id: str,
    strategy_id: str,
    scenario_id: str,
    capital_structure: CapitalStructure,
    db_path: Path | None,
) -> tuple[StructuredCapitalResult, str, str, int, tuple[str, ...]]:
    """The visible Investment pathway: the existing consolidated variant
    analysis, then the P7.8A Investment executor on every Unit's completed
    results and the completed consolidation. P7.6 is never reconstructed."""

    analysis = analyze_investment_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
    inputs = inspect_investment_variant_inputs(
        investment_id, strategy_id, scenario_id, db_path=db_path
    )
    if inputs.source_fingerprint != analysis.source_fingerprint:
        raise _conflict()
    units = tuple(
        CapitalStructureUnit(
            unit_id=unit_inputs.unit_id,
            terms=_resolved_terms(unit_inputs.resolved),
            results=_project_results(unit_result.results),
        )
        for unit_inputs, unit_result in zip(inputs.units, analysis.unit_results, strict=True)
    )
    result = execute_investment_capital_structure(
        units=units,
        consolidated=analysis.consolidated_results,
        capital_structure=capital_structure,
    )
    return (
        result,
        analysis.source_fingerprint,
        analysis.cache_status.value,
        analysis.hold_period,
        tuple(unit.unit_id for unit in units),
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
    are N/A with their reason, and its structural metrics stand."""

    root_kind = _root_kind(investment_id, db_path)
    resolved = resolve_variant_capital_structure(investment_id, strategy_id, db_path=db_path)
    analyze = (
        _analyze_hidden_unit
        if root_kind is StructuredRootKind.HIDDEN_UNIT
        else _analyze_visible_investment
    )
    result, project_fingerprint, cache_status, hold_period, unit_ids = analyze(
        investment_id, strategy_id, scenario_id, resolved.capital_structure, db_path
    )
    return StructuredVariantAnalysis(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        root_kind=root_kind,
        unit_ids=unit_ids,
        hold_period=hold_period,
        capital_structure=resolved.capital_structure,
        capital_structure_source=resolved.source,
        project_source_fingerprint=project_fingerprint,
        structured_source_fingerprint=fingerprint_structured_source(
            project_source_fingerprint=project_fingerprint,
            capital_structure=resolved.capital_structure,
        ),
        project_cache_status=cache_status,
        result=result,
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
