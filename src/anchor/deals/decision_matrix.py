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

from dataclasses import dataclass
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
    AxisMember,
    CellInput,
    CellIssue,
    CellIssueSource,
    DecisionMatrix,
    compare_decision_matrix,
)
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults
from . import store
from .variants import ResolvedScenarioInputs, VariantResults, analyze_variant, inspect_variant_inputs

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


def analyze_decision_matrix(
    investment_id: str, *, db_path: Path | None = None
) -> DecisionMatrixReport:
    """The Strategy x Scenario matrix of the hidden Investment: the implicit
    Base Strategy and every persisted Strategy, each under the implicit Base
    Scenario and every persisted Scenario. Each axis is in its stored
    presentation order, Base first."""

    investment = store.get_investment(investment_id, db_path=db_path)
    strategies = store.list_strategies(investment_id, db_path=db_path)
    scenarios = store.list_scenarios(investment_id, db_path=db_path)
    if len(investment.units) != 1:
        raise store.PersistedDealDataError(
            f"Investment {investment_id!r} does not hold exactly one unit."
        )

    strategy_axis = (
        AxisMember(id=BASE_STRATEGY_ID, name=BASE_STRATEGY_NAME, is_base=True),
        *(
            AxisMember(id=record.strategy.strategy_id, name=record.strategy.name, is_base=False)
            for record in strategies
        ),
    )
    scenario_axis = (
        AxisMember(id=BASE_SCENARIO_ID, name=BASE_SCENARIO_NAME, is_base=True),
        *(
            AxisMember(id=record.scenario.scenario_id, name=record.scenario.name, is_base=False)
            for record in scenarios
        ),
    )
    cells = [
        _cell(investment_id, strategy.id, scenario.id, db_path)
        for strategy in strategy_axis
        for scenario in scenario_axis
    ]
    deal = store.get_deal(investment.units[0].unit_id, db_path=db_path)
    return DecisionMatrixReport(
        investment_id=investment_id,
        unit_id=deal.id,
        operating_mode=deal.operating_mode,
        matrix=compare_decision_matrix(strategies=strategy_axis, scenarios=scenario_axis, cells=cells),
    )
