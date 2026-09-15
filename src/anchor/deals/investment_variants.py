"""Phase 7 Gate P7.6 -- the visible Investment variant pathway.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
7.5, 8, 9, 10, 11 and 15.4; that document governs on any discrepancy.

The one place a visible Investment's variant meets the deterministic engine::

    the visible Investment + every Unit's current Deal          (``store``)
            |
    Strategy and Scenario stage 1, over the member Units       one contract
            |
    per Unit, ascending ``unit_id``:  the Strategy's and Scenario's own
            |   overlays and overrides for that Unit, through the EXISTING
            |   P7.4 / P7.1 resolution and final validators
            |   (``variants.resolve_variant_inputs``)
    Investment rules on the resolved Units: the common timeline (CON-1) and
            |   the price allocation (PP-2)
    per Unit: the existing D6 entry point for its mode         unchanged results
            |
    the Investment Business Plan (``resolve_business_plan``, for H) and the
            |   transaction costs
    ``anchor.consolidation.consolidate``                        ConsolidatedResults

**One engine (P-1).** Every Unit runs exactly the analysis it would run alone,
through the path the hidden one-unit Investment already uses; nothing here is a
second resolver, a second engine or a portfolio engine. Consolidation happens
after every Unit engine and never writes back upstream.

**No Unit is dropped.** A Strategy applies to the whole membership; each Unit
receives only the overlays and overrides that name it, and an overlay or
override on a non-member is refused (stage 1), never ignored. There is no
UNIT_SELECTION.

**One invalid Unit is one invalid variant.** Any Strategy, Scenario, final
validator, Lease-Level, timeline, allocation or Investment-input issue makes the
whole variant invalid, with every issue's Unit named. No partial consolidation
of the valid Units is ever returned.

**Fingerprint the resolved inputs (Section 15.4).** A visible Investment
variant's source fingerprint hashes, sorted by ``unit_id``, each Unit's
existing resolved-input fingerprint and its economic timing, plus the
transaction price, the transaction costs' economics (amount and model month)
and the Investment Business Plan when it is non-empty. Names, labels, kinds,
ordinals, cost descriptions and categories, Strategy and Scenario naming and
timestamps never reach it. The hidden one-unit Investment keeps its P7.2-P7.5
fingerprints: it never enters this module.

**Recomputed, never cached (Q14).** A visible Investment variant is recomputed
deterministically on every request and reports ``BYPASSED``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..analysis import LeaseValidationError
from ..analysis.contracts import LeaseLevelAcquisitionResults
from ..analysis.scenario import (
    ResolvedDetailedInputs,
    ResolvedLeaseLevelInputs,
    ResolvedQuickInputs,
    ScenarioDefinition,
    ScenarioValidationError,
    validate_investment_scenario,
)
from ..analysis.strategy import (
    BASE_SCENARIO_ID,
    BASE_STRATEGY_ID,
    StrategyDefinition,
    StrategyValidationError,
    validate_investment_strategy,
)
from ..business_plan import BusinessPlan, resolve_business_plan
from ..consolidation import ConsolidatedResults, ConsolidationUnit, consolidate
from ..contracts import OperatingMode
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults
from ..investment import (
    InvestmentTransactionCost,
    InvestmentUnitMembership,
    UnitEconomicFacts,
    validate_investment_inputs,
    validate_variant_economics,
)
from . import store
from .contracts import Deal, VisibleInvestment
from .fingerprint import _fingerprint_json, _with_business_plan
from .variants import (
    ResolvedScenarioInputs,
    VariantCacheStatus,
    VariantResults,
    _analyze_resolved,
    fingerprint_resolved_inputs,
    resolve_variant_inputs,
)

#: The top-level key of a visible Investment variant's fingerprint payload. No
#: Unit fingerprint payload has it, so the two can never collide.
_INVESTMENT_KEY = "investment"


# =============================================================================
# Issues -- the invalid-variant contract
# =============================================================================


class InvestmentVariantIssueSource(StrEnum):
    """Which layer found a visible Investment variant invalid."""

    STRATEGY = "strategy"
    SCENARIO = "scenario"
    LEASE_LEVEL = "lease_level"
    INVESTMENT = "investment"


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentVariantIssue:
    """One deterministic reason a visible Investment variant is invalid, in its
    validator's own words, with the Unit it concerns where there is one."""

    source: InvestmentVariantIssueSource
    code: str
    message: str
    unit_id: str | None = None
    field: str | None = None


class InvestmentVariantValidationError(ValueError):
    """An invalid visible Investment variant: one ordered collection of
    ``InvestmentVariantIssue``. Nothing is consolidated for it."""

    def __init__(self, issues: Iterable[InvestmentVariantIssue]) -> None:
        ordered_issues = tuple(issues)
        if not ordered_issues:
            raise ValueError("InvestmentVariantValidationError requires at least one issue.")
        self.issues = ordered_issues
        super().__init__("\n".join(issue.message for issue in ordered_issues))


# =============================================================================
# The variant contracts
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitVariantInputs:
    """What one Unit of the variant runs: its resolved existing contracts and
    their existing resolved-input fingerprint."""

    unit_id: str
    operating_mode: OperatingMode
    source_fingerprint: str
    resolved: ResolvedScenarioInputs


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentVariantInputs:
    """What exactly a visible Investment variant runs (ST-4): every Unit's
    resolved inputs in ``unit_id`` order, the Investment-level inputs, the
    common hold, and the variant's source fingerprint. Nothing here is a
    result."""

    investment_id: str
    strategy_id: str
    scenario_id: str
    source_fingerprint: str
    hold_period: int
    transaction_price: float
    business_plan: BusinessPlan
    transaction_costs: tuple[InvestmentTransactionCost, ...]
    units: tuple[UnitVariantInputs, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentVariantFingerprint:
    investment_id: str
    strategy_id: str
    scenario_id: str
    source_fingerprint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitVariantResult:
    """One Unit's complete result envelope, exactly as its mode produces it:
    ``AcquisitionResults`` (Quick), ``DetailedAcquisitionResults`` or
    ``LeaseLevelAcquisitionResults`` -- never flattened."""

    unit_id: str
    operating_mode: OperatingMode
    source_fingerprint: str
    results: VariantResults


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentVariantAnalysis:
    """One analysed visible Investment variant: every Unit's own result, in
    ``unit_id`` order, and the consolidated project economics.
    ``cache_status`` is always ``BYPASSED``: it is recomputed."""

    investment_id: str
    strategy_id: str
    scenario_id: str
    source_fingerprint: str
    cache_status: VariantCacheStatus
    hold_period: int
    unit_results: tuple[UnitVariantResult, ...]
    consolidated_results: ConsolidatedResults


# =============================================================================
# The fingerprint
# =============================================================================


def fingerprint_investment_variant(
    *,
    memberships: Iterable[InvestmentUnitMembership],
    unit_fingerprints: Mapping[str, str],
    transaction_price: float,
    business_plan: BusinessPlan,
    transaction_costs: Iterable[InvestmentTransactionCost],
) -> str:
    """The financial source fingerprint of a visible Investment variant.

    Reads, from each membership, only its ``unit_id`` and economic timing, with
    that Unit's resolved-input fingerprint; from each transaction cost only its
    amount and model month; the transaction price; and the Investment Business
    Plan through the D6.5 rule (the empty plan adds nothing). Every list is
    sorted by value, so no presentation order reaches it."""

    payload: dict[str, Any] = {
        _INVESTMENT_KEY: {
            "units": sorted(
                [
                    membership.unit_id,
                    unit_fingerprints[membership.unit_id],
                    membership.acquisition_month,
                    membership.disposition_month,
                ]
                for membership in memberships
            ),
            "transaction_price": float(transaction_price),
            "transaction_costs": sorted(
                [cost.model_month, float(cost.amount)] for cost in transaction_costs
            ),
        }
    }
    return _fingerprint_json(_with_business_plan(payload, business_plan))


# =============================================================================
# Loading and resolution
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class _InvestmentRoot:
    """The visible Investment and every Unit's current Deal, in ``unit_id``
    order."""

    investment: VisibleInvestment
    deals: tuple[Deal, ...]


def _load_root(investment_id: str, db_path: Path | None) -> _InvestmentRoot:
    investment = store.get_visible_investment(investment_id, db_path=db_path)
    deals = tuple(
        store.get_deal(membership.unit_id, db_path=db_path)
        for membership in sorted(investment.units, key=lambda membership: membership.unit_id)
    )
    return _InvestmentRoot(investment=investment, deals=deals)


def _load_recipe(
    investment_id: str, strategy_id: str, scenario_id: str, db_path: Path | None
) -> tuple[_InvestmentRoot, StrategyDefinition | None, ScenarioDefinition | None]:
    """The root, and the persisted Strategy and Scenario the keys name -- each
    proven to belong to ``investment_id`` -- or ``None`` for a reserved Base
    key."""

    root = _load_root(investment_id, db_path)
    strategy = (
        None
        if strategy_id == BASE_STRATEGY_ID
        else store.get_strategy(investment_id, strategy_id, db_path=db_path).strategy
    )
    scenario = (
        None
        if scenario_id == BASE_SCENARIO_ID
        else store.get_scenario(investment_id, scenario_id, db_path=db_path).scenario
    )
    return root, strategy, scenario


def _strategy_of_unit(strategy: StrategyDefinition | None, unit_id: str) -> StrategyDefinition | None:
    """The Strategy as one Unit sees it: its own overlays, none of another's."""

    if strategy is None:
        return None
    return replace(
        strategy, overlays=tuple(overlay for overlay in strategy.overlays if overlay.unit_id == unit_id)
    )


def _scenario_of_unit(scenario: ScenarioDefinition | None, unit_id: str) -> ScenarioDefinition | None:
    """The Scenario as one Unit sees it: its own overrides, none of another's."""

    if scenario is None:
        return None
    return replace(
        scenario,
        overrides=tuple(override for override in scenario.overrides if override.unit_id == unit_id),
    )


def _resolved_facts(unit: UnitVariantInputs) -> UnitEconomicFacts:
    """The resolved facts the Investment-level rules read, off the resolved
    contracts of the Unit's own mode."""

    resolved = unit.resolved
    match resolved:
        case ResolvedQuickInputs():
            price, hold, start = resolved.inputs.purchase_price, resolved.inputs.hold_period, None
        case ResolvedDetailedInputs():
            price, hold, start = resolved.terms.purchase_price, resolved.terms.hold_period, None
        case ResolvedLeaseLevelInputs():
            price, hold = resolved.terms.purchase_price, resolved.terms.hold_period
            start = resolved.property_inputs.analysis_start_date
        case _:
            raise TypeError(f"Not resolved variant inputs: {type(resolved).__qualname__}.")
    return UnitEconomicFacts(
        unit_id=unit.unit_id,
        operating_mode=unit.operating_mode,
        purchase_price=price,
        hold_period=hold,
        analysis_start_date=start,
    )


def _investment_issues(issues: Iterable[Any]) -> list[InvestmentVariantIssue]:
    return [
        InvestmentVariantIssue(
            source=InvestmentVariantIssueSource.INVESTMENT,
            code=issue.code.value,
            message=issue.message,
            unit_id=issue.unit_id,
            field=issue.field,
        )
        for issue in issues
    ]


def _resolve_units(
    root: _InvestmentRoot,
    strategy: StrategyDefinition | None,
    scenario: ScenarioDefinition | None,
) -> tuple[UnitVariantInputs, ...]:
    """Base -> Strategy -> Scenario -> validation for every Unit, then the
    Investment-level rules on the resolved Units. Raises
    ``InvestmentVariantValidationError`` with every issue found, each with its
    Unit; returns nothing partial."""

    unit_modes = {deal.id: deal.operating_mode for deal in root.deals}
    issues: list[InvestmentVariantIssue] = []
    if strategy is not None:
        issues.extend(
            InvestmentVariantIssue(
                source=InvestmentVariantIssueSource.STRATEGY,
                code=issue.code.value,
                message=issue.message,
                unit_id=issue.unit_id,
                field=issue.field,
            )
            for issue in validate_investment_strategy(strategy, unit_modes=unit_modes)
        )
    if scenario is not None:
        issues.extend(
            InvestmentVariantIssue(
                source=InvestmentVariantIssueSource.SCENARIO,
                code=issue.code.value,
                message=issue.message,
                unit_id=issue.unit_id,
                field=issue.field,
            )
            for issue in validate_investment_scenario(scenario, unit_modes=unit_modes)
        )
    if issues:
        raise InvestmentVariantValidationError(issues)

    units: list[UnitVariantInputs] = []
    for deal in root.deals:
        try:
            resolved = resolve_variant_inputs(
                deal, _strategy_of_unit(strategy, deal.id), _scenario_of_unit(scenario, deal.id)
            )
        except StrategyValidationError as error:
            issues.extend(
                InvestmentVariantIssue(
                    source=InvestmentVariantIssueSource.STRATEGY,
                    code=issue.code.value,
                    message=issue.message,
                    unit_id=issue.unit_id or deal.id,
                    field=issue.field,
                )
                for issue in error.issues
            )
        except ScenarioValidationError as error:
            issues.extend(
                InvestmentVariantIssue(
                    source=InvestmentVariantIssueSource.SCENARIO,
                    code=issue.code.value,
                    message=issue.message,
                    unit_id=issue.unit_id or deal.id,
                    field=issue.field,
                )
                for issue in error.issues
            )
        else:
            units.append(
                UnitVariantInputs(
                    unit_id=deal.id,
                    operating_mode=deal.operating_mode,
                    source_fingerprint=fingerprint_resolved_inputs(resolved),
                    resolved=resolved,
                )
            )
    if issues:
        raise InvestmentVariantValidationError(issues)

    investment = root.investment
    issues.extend(
        _investment_issues(
            validate_investment_inputs(
                name=investment.name,
                transaction_price=investment.transaction_price,
                memberships=investment.units,
                business_plan=investment.business_plan,
                transaction_costs=investment.transaction_costs,
            )
        )
    )
    issues.extend(
        _investment_issues(
            validate_variant_economics(
                [_resolved_facts(unit) for unit in units],
                transaction_price=investment.transaction_price,
            )
        )
    )
    if issues:
        raise InvestmentVariantValidationError(issues)
    return tuple(units)


def _source_fingerprint(root: _InvestmentRoot, units: Iterable[UnitVariantInputs]) -> str:
    investment = root.investment
    return fingerprint_investment_variant(
        memberships=investment.units,
        unit_fingerprints={unit.unit_id: unit.source_fingerprint for unit in units},
        transaction_price=investment.transaction_price,
        business_plan=investment.business_plan,
        transaction_costs=investment.transaction_costs,
    )


def investment_base_fingerprint(investment_id: str, *, db_path: Path | None = None) -> str:
    """The Base x Base fingerprint of the visible Investment's stored inputs,
    without judging whether they form a valid variant -- the economic state a
    Decision Matrix run is bracketed by. Read-only."""

    root = _load_root(investment_id, db_path)
    return _source_fingerprint(
        root,
        [
            UnitVariantInputs(
                unit_id=deal.id,
                operating_mode=deal.operating_mode,
                source_fingerprint=fingerprint_resolved_inputs(resolve_variant_inputs(deal, None, None)),
                resolved=resolve_variant_inputs(deal, None, None),
            )
            for deal in root.deals
        ],
    )


# =============================================================================
# The public pathway
# =============================================================================


def inspect_investment_variant_inputs(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> InvestmentVariantInputs:
    """Resolved-input inspection (ST-4) of a visible Investment variant.
    Read-only; it calculates nothing."""

    root, strategy, scenario = _load_recipe(investment_id, strategy_id, scenario_id, db_path)
    units = _resolve_units(root, strategy, scenario)
    investment = root.investment
    return InvestmentVariantInputs(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        source_fingerprint=_source_fingerprint(root, units),
        hold_period=_resolved_facts(units[0]).hold_period,
        transaction_price=investment.transaction_price,
        business_plan=investment.business_plan,
        transaction_costs=investment.transaction_costs,
        units=units,
    )


def investment_variant_fingerprint(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> InvestmentVariantFingerprint:
    """The current source fingerprint of a visible Investment variant.
    Read-only."""

    root, strategy, scenario = _load_recipe(investment_id, strategy_id, scenario_id, db_path)
    units = _resolve_units(root, strategy, scenario)
    return InvestmentVariantFingerprint(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        source_fingerprint=_source_fingerprint(root, units),
    )


def _project_results(results: VariantResults) -> AcquisitionResults:
    match results:
        case AcquisitionResults():
            return results
        case DetailedAcquisitionResults():
            return results.results
        case LeaseLevelAcquisitionResults():
            return results.results
        case _:
            raise TypeError(f"Not a variant result: {type(results).__qualname__}.")


def _consolidation_unit(fact: UnitEconomicFacts, results: VariantResults) -> ConsolidationUnit:
    """What consolidation reads of one Unit: its resolved price and hold, its
    project results and -- only where its result contract exposes it -- its
    year-end area state."""

    occupied: tuple[float, ...] | None = None
    vacant: tuple[float, ...] | None = None
    if isinstance(results, LeaseLevelAcquisitionResults):
        occupied = results.annual_projection.occupied_area_at_year_end
        vacant = results.annual_projection.vacant_area_at_year_end
    return ConsolidationUnit(
        unit_id=fact.unit_id,
        purchase_price=fact.purchase_price,
        hold_period=fact.hold_period,
        results=_project_results(results),
        occupied_area_at_year_end=occupied,
        vacant_area_at_year_end=vacant,
    )


def analyze_investment_variant(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> InvestmentVariantAnalysis:
    """Analyse a visible Investment variant: every Unit through the existing
    engine on its resolved inputs, then consolidation.

    Raises ``InvestmentVariantValidationError`` when the variant is invalid --
    including a Lease-Level Unit the engine refuses -- with every issue's Unit
    named. Always recomputed; never cached."""

    root, strategy, scenario = _load_recipe(investment_id, strategy_id, scenario_id, db_path)
    units = _resolve_units(root, strategy, scenario)

    unit_results: list[UnitVariantResult] = []
    issues: list[InvestmentVariantIssue] = []
    for unit in units:
        try:
            results = _analyze_resolved(unit.resolved)
        except LeaseValidationError as error:
            issues.extend(
                InvestmentVariantIssue(
                    source=InvestmentVariantIssueSource.LEASE_LEVEL,
                    code=issue.code.value,
                    message=issue.message,
                    unit_id=unit.unit_id,
                    field=issue.path,
                )
                for issue in error.result.errors
            )
        else:
            unit_results.append(
                UnitVariantResult(
                    unit_id=unit.unit_id,
                    operating_mode=unit.operating_mode,
                    source_fingerprint=unit.source_fingerprint,
                    results=results,
                )
            )
    if issues:
        raise InvestmentVariantValidationError(issues)

    investment = root.investment
    facts = [_resolved_facts(unit) for unit in units]
    hold_period = facts[0].hold_period
    consolidated = consolidate(
        [
            _consolidation_unit(fact, result.results)
            for fact, result in zip(facts, unit_results, strict=True)
        ],
        transaction_price=investment.transaction_price,
        investment_owner_capital=resolve_business_plan(
            investment.business_plan, hold_period=hold_period
        ),
        transaction_costs=investment.transaction_costs,
    )
    return InvestmentVariantAnalysis(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        source_fingerprint=_source_fingerprint(root, units),
        cache_status=VariantCacheStatus.BYPASSED,
        hold_period=hold_period,
        unit_results=tuple(unit_results),
        consolidated_results=consolidated,
    )
