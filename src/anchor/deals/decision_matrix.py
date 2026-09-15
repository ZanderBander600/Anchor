"""Phase 7 Gate P7.5 -- the Decision Matrix service.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
7.5 and 14.1; that document governs on any discrepancy.

The one place the hidden one-unit Investment's Strategies and Scenarios become a
Strategy x Scenario matrix::

    the Investment's Strategies and Scenarios          (``store``), each axis
            |                                          led by its implicit Base
    every (Strategy, Scenario) pair
            |
    ``variants.analyze_variant``      Base -> Strategy -> Scenario -> validation
            |                         -> the existing engine, with the P7.4
            |                         fingerprint-guarded cache
    ``variants.inspect_variant_inputs``   the hold period that actually ran
            |
    ``decision.comparison``           the read-only cross-cell figures

**One coherent package (DC-7).** A matrix is one comparison of one economic
state. The economic source-state token is captured before the first cell and
again after the last; if it moved, the request is a conflict and nothing is
returned. The token covers the Base Deal (through its existing financial
fingerprint, Business Plan included), the Investment's unit membership, and
each Strategy's overlays and each Scenario's overrides by stable id -- and
nothing else: names, descriptions, list order and timestamps never reach it, so
a rename during a run is not a conflict. Each cell also keeps its own check
that its analysis and its inspected inputs share a fingerprint.

**One engine path.** Every cell is ``analyze_variant``, the P7.4 variant
authority, which already owns resolution, fingerprints and caching. This module
resolves nothing and computes nothing. It never calls an engine entry point.

**An invalid variant is one cell (DC-2).** The typed validation errors a
variant can raise -- Strategy, Scenario and Lease-Level validation -- become
that cell's reasons, in the validators' own words, and every other cell
stands. Anything else is not a financial finding: a missing row, a structural
refusal or a programming error propagates and fails the request visibly. It is
never reported as an invalid variant.

**Nothing is stored.** The matrix is derived on request. The only rows it can
touch are the P7.4 variant cache rows ``analyze_variant`` itself maintains.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from ..analysis import LeaseValidationError
from ..analysis.contracts import LeaseLevelAcquisitionResults
from ..analysis.scenario import (
    ResolvedDetailedInputs,
    ResolvedLeaseLevelInputs,
    ResolvedQuickInputs,
    ScenarioValidationError,
)
from ..analysis.strategy import BASE_SCENARIO_ID, BASE_STRATEGY_ID, StrategyValidationError
from ..contracts import OperatingMode
from ..decision.comparison import (
    INVESTMENT_PROJECT_METRIC_CATALOG,
    AxisMember,
    CellInput,
    CellIssue,
    CellIssueSource,
    DecisionMatrix,
    compare_decision_matrix,
)
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults
from . import store
from .contracts import InvestmentScenario, InvestmentStrategy, InvestmentStructureError
from .investment_variants import (
    InvestmentVariantIssue,
    InvestmentVariantIssueSource,
    InvestmentVariantValidationError,
    analyze_investment_variant,
    inspect_investment_variant_inputs,
    investment_base_fingerprint,
)
from .variants import (
    ResolvedScenarioInputs,
    VariantResults,
    analyze_variant,
    inspect_variant_inputs,
    variant_fingerprint,
)

#: How the implicit Base on each axis is named in the package. Presentation
#: only: never an id, never financial.
BASE_STRATEGY_NAME = "Base Strategy"
BASE_SCENARIO_NAME = "Base Scenario"


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionMatrixReport:
    """The Decision Matrix of one hidden Investment: its one unit, that unit's
    operating mode, and the comparison package."""

    investment_id: str
    unit_id: str
    operating_mode: OperatingMode
    matrix: DecisionMatrix


class DecisionMatrixConflictError(RuntimeError):
    """The saved underwriting changed while the matrix was being analysed, so
    one cell's result and the inputs read beside it no longer belong to one
    state. Nothing is reported; the analyst runs the matrix again."""


def _project_results(results: VariantResults) -> AcquisitionResults:
    """The Project ``AcquisitionResults`` of any mode's result envelope. It
    selects a field and computes nothing."""

    match results:
        case AcquisitionResults():
            return results
        case DetailedAcquisitionResults():
            return results.results
        case LeaseLevelAcquisitionResults():
            return results.results
        case _:
            raise TypeError(f"Not a variant result: {type(results).__qualname__}.")


def _hold_period(resolved: ResolvedScenarioInputs) -> int:
    """The hold period the variant ran with, read off its resolved inputs."""

    match resolved:
        case ResolvedQuickInputs():
            return resolved.inputs.hold_period
        case ResolvedDetailedInputs() | ResolvedLeaseLevelInputs():
            return resolved.terms.hold_period
        case _:
            raise TypeError(f"Not resolved variant inputs: {type(resolved).__qualname__}.")


def _invalid(strategy_id: str, scenario_id: str, issues: tuple[CellIssue, ...]) -> CellInput:
    return CellInput(
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        results=None,
        source_fingerprint=None,
        cache_status=None,
        hold_period=None,
        issues=issues,
    )


def _cell(
    investment_id: str, strategy_id: str, scenario_id: str, db_path: Path | None
) -> CellInput:
    """One variant through the P7.4 authority. The three typed validation
    errors make the cell invalid; every other failure propagates."""

    try:
        analysis = analyze_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
    except StrategyValidationError as error:
        return _invalid(
            strategy_id,
            scenario_id,
            tuple(
                CellIssue(
                    source=CellIssueSource.STRATEGY,
                    code=issue.code.value,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in error.issues
            ),
        )
    except ScenarioValidationError as error:
        return _invalid(
            strategy_id,
            scenario_id,
            tuple(
                CellIssue(
                    source=CellIssueSource.SCENARIO,
                    code=issue.code.value,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in error.issues
            ),
        )
    except LeaseValidationError as error:
        return _invalid(
            strategy_id,
            scenario_id,
            tuple(
                CellIssue(
                    source=CellIssueSource.LEASE_LEVEL,
                    code=issue.code.value,
                    message=issue.message,
                    field=issue.path,
                )
                for issue in error.result.errors
            ),
        )

    try:
        inputs = inspect_variant_inputs(investment_id, strategy_id, scenario_id, db_path=db_path)
    except (StrategyValidationError, ScenarioValidationError) as error:
        raise DecisionMatrixConflictError(
            "The saved underwriting changed while the decision matrix was running. Run it again."
        ) from error
    if inputs.source_fingerprint != analysis.source_fingerprint:
        raise DecisionMatrixConflictError(
            "The saved underwriting changed while the decision matrix was running. Run it again."
        )
    return CellInput(
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        results=_project_results(analysis.results),
        source_fingerprint=analysis.source_fingerprint,
        cache_status=analysis.cache_status.value,
        hold_period=_hold_period(inputs.resolved),
    )


def _order_free(value: object) -> object:
    """``value`` with every list put in one canonical order. Every list inside a
    Strategy overlay or a Scenario override set is a set whose order carries no
    economic meaning (P-7): operating outcomes, Business Plan items, overrides.
    Nothing here reads a value's meaning; it only orders."""

    if isinstance(value, dict):
        return {str(key): _order_free(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_order_free(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def economic_state_token(
    *,
    hidden: bool,
    unit_ids: Iterable[str],
    base_fingerprint: str,
    strategies: Iterable[InvestmentStrategy],
    scenarios: Iterable[InvestmentScenario],
) -> str:
    """The economic source state one matrix is defined by, as a sha256 digest.

    It reads the Base Deal's existing financial fingerprint, the Investment's
    unit membership, and each Strategy's id and overlays and each Scenario's id
    and overrides -- nothing else. A Strategy or Scenario name or description,
    the order of either list, and every timestamp never reach it. It is never
    persisted and is not a financial fingerprint: it only proves that the state
    did not move during one request."""

    payload = {
        "investment": {"hidden": hidden, "units": sorted(unit_ids)},
        "base": base_fingerprint,
        "strategies": sorted(
            (
                [record.strategy.strategy_id, _order_free([asdict(o) for o in record.strategy.overlays])]
                for record in strategies
            ),
            key=lambda entry: str(entry[0]),
        ),
        "scenarios": sorted(
            (
                [record.scenario.scenario_id, _order_free([asdict(o) for o in record.scenario.overrides])]
                for record in scenarios
            ),
            key=lambda entry: str(entry[0]),
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class _SourceState:
    """One read of everything a matrix is defined by, and its token."""

    token: str
    unit_id: str
    strategies: tuple[InvestmentStrategy, ...]
    scenarios: tuple[InvestmentScenario, ...]


def _source_state(investment_id: str, db_path: Path | None) -> _SourceState:
    """Reads the Investment, its Strategies and Scenarios, and the Base Deal's
    fingerprint through the existing variant authority (Base x Base), and
    tokenizes their economic content."""

    investment = store.get_investment(investment_id, db_path=db_path)
    strategies = tuple(store.list_strategies(investment_id, db_path=db_path))
    scenarios = tuple(store.list_scenarios(investment_id, db_path=db_path))
    if len(investment.units) != 1:
        raise store.PersistedDealDataError(
            f"Investment {investment_id!r} does not hold exactly one unit."
        )
    base_fingerprint = variant_fingerprint(
        investment_id, BASE_STRATEGY_ID, BASE_SCENARIO_ID, db_path=db_path
    ).source_fingerprint
    return _SourceState(
        token=economic_state_token(
            hidden=investment.hidden,
            unit_ids=[unit.unit_id for unit in investment.units],
            base_fingerprint=base_fingerprint,
            strategies=strategies,
            scenarios=scenarios,
        ),
        unit_id=investment.units[0].unit_id,
        strategies=strategies,
        scenarios=scenarios,
    )


def analyze_decision_matrix(
    investment_id: str, *, db_path: Path | None = None
) -> DecisionMatrixReport:
    """The Strategy x Scenario matrix of the hidden Investment: the implicit
    Base Strategy and every persisted Strategy, each under the implicit Base
    Scenario and every persisted Scenario. Each axis is in its stored
    presentation order, Base first.

    The economic source state is read before the first cell and again after
    the last. If it moved, ``DecisionMatrixConflictError``: one package is never
    a mix of two states."""

    if not store.get_investment(investment_id, db_path=db_path).hidden:
        raise InvestmentStructureError(
            f"Investment {investment_id!r} is a visible Investment. Its Decision Matrix "
            "consolidates its Units: use the Investment Decision Matrix."
        )
    before = _source_state(investment_id, db_path)
    strategy_axis = (
        AxisMember(id=BASE_STRATEGY_ID, name=BASE_STRATEGY_NAME, is_base=True),
        *(
            AxisMember(id=record.strategy.strategy_id, name=record.strategy.name, is_base=False)
            for record in before.strategies
        ),
    )
    scenario_axis = (
        AxisMember(id=BASE_SCENARIO_ID, name=BASE_SCENARIO_NAME, is_base=True),
        *(
            AxisMember(id=record.scenario.scenario_id, name=record.scenario.name, is_base=False)
            for record in before.scenarios
        ),
    )
    cells = [
        _cell(investment_id, strategy.id, scenario.id, db_path)
        for strategy in strategy_axis
        for scenario in scenario_axis
    ]
    after = _source_state(investment_id, db_path)
    if after.token != before.token:
        raise DecisionMatrixConflictError(
            "The saved underwriting, strategies or scenarios changed while the decision "
            "matrix was running. Run it again."
        )
    deal = store.get_deal(before.unit_id, db_path=db_path)
    return DecisionMatrixReport(
        investment_id=investment_id,
        unit_id=deal.id,
        operating_mode=deal.operating_mode,
        matrix=compare_decision_matrix(strategies=strategy_axis, scenarios=scenario_axis, cells=cells),
    )


# =============================================================================
# Phase 7 Gate P7.6 -- the Decision Matrix of a visible Investment
#
# The same comparison, over a visible Investment's variants. Every cell runs the
# visible Investment variant pathway (``investment_variants``): every Unit
# through the existing engine, then consolidation, so each cell's Project
# metrics are the consolidated Investment's (``ConsolidatedResults``), never one
# arbitrary Unit's. Delta, Worst Case and Range are the unchanged P7.5
# cross-cell figures of ``anchor.decision.comparison``, and its Minimum DSCR is
# the Aggregate DSCR, labelled as such.
#
# One invalid variant is one invalid cell, with every issue's Unit named in its
# location; a variant is never consolidated over only its valid Units. The whole
# run is bracketed by the same economic state token, whose Base fingerprint is
# the visible Investment's own.
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentMatrixUnit:
    """One Unit of a visible Investment's matrix, with its operating mode."""

    unit_id: str
    operating_mode: OperatingMode


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentDecisionMatrixReport:
    """The Decision Matrix of one visible Investment: its Units, in ``unit_id``
    order, and the comparison package of its consolidated variants."""

    investment_id: str
    units: tuple[InvestmentMatrixUnit, ...]
    matrix: DecisionMatrix


_INVESTMENT_ISSUE_SOURCES = {
    InvestmentVariantIssueSource.STRATEGY: CellIssueSource.STRATEGY,
    InvestmentVariantIssueSource.SCENARIO: CellIssueSource.SCENARIO,
    InvestmentVariantIssueSource.LEASE_LEVEL: CellIssueSource.LEASE_LEVEL,
    InvestmentVariantIssueSource.INVESTMENT: CellIssueSource.INVESTMENT,
}


def _unit_located(issue: InvestmentVariantIssue) -> str | None:
    """The issue's location, rooted at its Unit when it has one, so a matrix
    cell never hides which Unit made the variant invalid."""

    if issue.unit_id is None:
        return issue.field
    root = f"units[{issue.unit_id}]"
    return root if issue.field is None else f"{root}.{issue.field}"


def _investment_cell(
    investment_id: str, strategy_id: str, scenario_id: str, db_path: Path | None
) -> CellInput:
    """One visible Investment variant through the P7.6 pathway. Its typed
    validation error makes the cell invalid; every other failure propagates."""

    try:
        analysis = analyze_investment_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
    except InvestmentVariantValidationError as error:
        return _invalid(
            strategy_id,
            scenario_id,
            tuple(
                CellIssue(
                    source=_INVESTMENT_ISSUE_SOURCES[issue.source],
                    code=issue.code,
                    message=issue.message,
                    field=_unit_located(issue),
                )
                for issue in error.issues
            ),
        )

    try:
        inputs = inspect_investment_variant_inputs(
            investment_id, strategy_id, scenario_id, db_path=db_path
        )
    except InvestmentVariantValidationError as error:
        raise DecisionMatrixConflictError(
            "The saved underwriting changed while the decision matrix was running. Run it again."
        ) from error
    if inputs.source_fingerprint != analysis.source_fingerprint:
        raise DecisionMatrixConflictError(
            "The saved underwriting changed while the decision matrix was running. Run it again."
        )
    return CellInput(
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        results=analysis.consolidated_results,
        source_fingerprint=analysis.source_fingerprint,
        cache_status=analysis.cache_status.value,
        hold_period=analysis.hold_period,
    )


def _investment_source_state(investment_id: str, db_path: Path | None) -> _SourceState:
    """The visible Investment's economic source state: its membership, its
    Base fingerprint (every Unit, the transaction price, the costs' economics
    and its plan), and each Strategy's and Scenario's economic content --
    never a name, a label, a kind, an ordinal or a timestamp."""

    investment = store.get_visible_investment(investment_id, db_path=db_path)
    strategies = tuple(store.list_strategies(investment_id, db_path=db_path))
    scenarios = tuple(store.list_scenarios(investment_id, db_path=db_path))
    return _SourceState(
        token=economic_state_token(
            hidden=False,
            unit_ids=[membership.unit_id for membership in investment.units],
            base_fingerprint=investment_base_fingerprint(investment_id, db_path=db_path),
            strategies=strategies,
            scenarios=scenarios,
        ),
        unit_id="",
        strategies=strategies,
        scenarios=scenarios,
    )


def analyze_investment_decision_matrix(
    investment_id: str, *, db_path: Path | None = None
) -> InvestmentDecisionMatrixReport:
    """The Strategy x Scenario matrix of a visible Investment: the implicit
    Base Strategy and every persisted Strategy, each under the implicit Base
    Scenario and every persisted Scenario, with each cell's consolidated
    Project metrics. Each axis is in its stored presentation order, Base first.

    Bracketed by the economic source state exactly as the one-unit matrix is:
    if it moved, ``DecisionMatrixConflictError``."""

    before = _investment_source_state(investment_id, db_path)
    strategy_axis = (
        AxisMember(id=BASE_STRATEGY_ID, name=BASE_STRATEGY_NAME, is_base=True),
        *(
            AxisMember(id=record.strategy.strategy_id, name=record.strategy.name, is_base=False)
            for record in before.strategies
        ),
    )
    scenario_axis = (
        AxisMember(id=BASE_SCENARIO_ID, name=BASE_SCENARIO_NAME, is_base=True),
        *(
            AxisMember(id=record.scenario.scenario_id, name=record.scenario.name, is_base=False)
            for record in before.scenarios
        ),
    )
    cells = [
        _investment_cell(investment_id, strategy.id, scenario.id, db_path)
        for strategy in strategy_axis
        for scenario in scenario_axis
    ]
    after = _investment_source_state(investment_id, db_path)
    if after.token != before.token:
        raise DecisionMatrixConflictError(
            "The saved underwriting, strategies or scenarios changed while the decision "
            "matrix was running. Run it again."
        )
    investment = store.get_visible_investment(investment_id, db_path=db_path)
    units = tuple(
        InvestmentMatrixUnit(unit_id=deal.id, operating_mode=deal.operating_mode)
        for deal in (
            store.get_deal(unit_id, db_path=db_path)
            for unit_id in sorted(membership.unit_id for membership in investment.units)
        )
    )
    return InvestmentDecisionMatrixReport(
        investment_id=investment_id,
        units=units,
        matrix=compare_decision_matrix(
            strategies=strategy_axis,
            scenarios=scenario_axis,
            cells=cells,
            catalog=INVESTMENT_PROJECT_METRIC_CATALOG,
        ),
    )
