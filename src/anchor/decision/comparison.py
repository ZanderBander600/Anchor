"""Phase 7 Gate P7.5 -- the Strategy x Scenario decision comparison.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
3 (P-5, P-9), 7.4 (ST-5), 14.1 (DC-1 to DC-7) and 15.4, and its Section 21
record (Q19, Q22); that document governs on any discrepancy. P7.5 carries the
one Q16 approval for this gate's cross-cell scope: Delta vs Base Scenario, Worst
Case across Scenarios and Range across Scenarios, computed from completed
results. Nothing else.

**Read-only financially (P-5, DC-1).** This module consumes completed
``AcquisitionResults`` and never produces a financial figure of its own. It
imports result contracts only -- never ``anchor.engine.acquisition``,
``debt`` or ``returns`` -- and it reads no database and knows no route. Every
metric a cell shows is one existing ``AcquisitionResults`` field, selected. The
only arithmetic here is the approved cross-cell catalog:

- **Delta vs Base Scenario**: ``metric(S, C) - metric(S, Base Scenario)`` --
  the *same* Strategy under a different Scenario, never one Strategy against
  another. For a rate the difference is in rate points on the internal
  decimal scale (``0.09 - 0.12 = -0.03``); presentation writes it as
  percentage points, never as a relative change.
- **Worst Case across Scenarios**: for one Strategy and one metric, the least
  favourable value across the Base Scenario and every persisted Scenario --
  the lowest where higher is better, the *highest* Total Equity Invested.
- **Range across Scenarios**: the maximum less the minimum across the same
  cells. Dispersion only; it has no good or bad direction.

There is no probability, no expected value, no weighting, no score, no
ranking and no recommended Strategy (Q19, DC-6). Worst Case is per Strategy and
per metric; nothing compares Strategies with one another.

**Honest figures (P-9, DC-2).** A figure that cannot be computed honestly is
``None`` with a deterministic reason:

- a Delta needs its own cell and the same Strategy's Base Scenario cell, both
  valid and both reporting the metric -- and nothing else;
- a Worst Case or a Range needs *every* Scenario cell of the row valid and
  reporting the metric. An invalid Scenario is never skipped: leaving it out
  could make a Strategy look safer than it is.

An IRR is reported only when its ``IrrStatus`` is ``DEFINED``.

**Horizons (ST-5, DC-4).** When the analysed variants do not all share one hold
period, Exit Value and Minimum DSCR are omitted from the whole matrix with a
deterministic reason. Only the horizon-independent metrics are compared, and no
annual row is ever aligned across horizons.

**Stable order, never display order.** Ties go to the first cell in canonical
order -- the Base Scenario first, then Scenario ids ascending -- whatever order
the analyst sees. The matrix fingerprint canonicalizes the same way.

**The matrix fingerprint (Section 15.4) is not persisted.** It is a hash of
``(strategy_id, scenario_id, source_fingerprint)`` for every cell, in
canonical order. Names, descriptions and presentation order never reach it.
When any cell has no current source fingerprint -- an invalid variant -- the
matrix has none, with its reason.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..consolidation.contracts import ConsolidatedResults
from ..engine.contracts import AcquisitionResults, IrrStatus

#: What one cell's Project results are: a Unit's ``AcquisitionResults`` (the
#: hidden one-unit Investment) or, from P7.6, a visible Investment's
#: ``ConsolidatedResults``. Both are completed result contracts.
ProjectResults = AcquisitionResults | ConsolidatedResults

# =============================================================================
# The Project metric catalog
# =============================================================================


class DecisionPerspective(StrEnum):
    """Whose returns the matrix compares (DC-3). P7.5 has the Project
    perspective only; position and partner perspectives belong to later
    gates."""

    PROJECT = "project"


class DecisionMetric(StrEnum):
    """The Project metrics, each one existing ``AcquisitionResults`` field of
    the same name."""

    LEVERED_IRR = "levered_irr"
    UNLEVERED_IRR = "unlevered_irr"
    EQUITY_MULTIPLE = "equity_multiple"
    TOTAL_PROFIT = "total_profit"
    TOTAL_EQUITY_INVESTED = "total_equity_invested"
    EXIT_VALUE = "exit_value"
    MIN_DSCR = "min_dscr"


class MetricDirection(StrEnum):
    """Which end of a metric is adverse, for Worst Case only. Range has no
    direction."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class MetricUnit(StrEnum):
    """How a metric's value is stated. ``RATE`` is a decimal rate, so a Delta
    or a Range of a rate is in rate points on the same scale (``0.01`` is one
    percentage point). ``MULTIPLE`` is a ratio shown as ``1.85x``.
    ``CURRENCY`` is dollars."""

    RATE = "rate"
    MULTIPLE = "multiple"
    CURRENCY = "currency"


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricSpec:
    """One Project metric: its field, the analyst's label, how it is stated,
    which end is adverse, and whether it depends on the hold period."""

    metric: DecisionMetric
    label: str
    unit: MetricUnit
    direction: MetricDirection
    horizon_dependent: bool


#: The Project catalog, in display order.
PROJECT_METRIC_CATALOG: tuple[MetricSpec, ...] = (
    MetricSpec(
        metric=DecisionMetric.LEVERED_IRR,
        label="Levered IRR",
        unit=MetricUnit.RATE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=DecisionMetric.UNLEVERED_IRR,
        label="Unlevered IRR",
        unit=MetricUnit.RATE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=DecisionMetric.EQUITY_MULTIPLE,
        label="Equity Multiple",
        unit=MetricUnit.MULTIPLE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=DecisionMetric.TOTAL_PROFIT,
        label="Total Profit",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=DecisionMetric.TOTAL_EQUITY_INVESTED,
        label="Total Equity Invested",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.LOWER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=DecisionMetric.EXIT_VALUE,
        label="Exit Value",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=True,
    ),
    MetricSpec(
        metric=DecisionMetric.MIN_DSCR,
        label="Minimum DSCR",
        unit=MetricUnit.MULTIPLE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=True,
    ),
)

#: The Project catalog of a visible Investment (P7.6): the same metrics, read off
#: ``ConsolidatedResults``. Its DSCR is consolidated NOI over consolidated debt
#: service -- the Aggregate DSCR -- and is labelled as such, never as a Unit's.
INVESTMENT_PROJECT_METRIC_CATALOG: tuple[MetricSpec, ...] = tuple(
    MetricSpec(
        metric=spec.metric,
        label="Minimum Aggregate DSCR" if spec.metric is DecisionMetric.MIN_DSCR else spec.label,
        unit=spec.unit,
        direction=spec.direction,
        horizon_dependent=spec.horizon_dependent,
    )
    for spec in PROJECT_METRIC_CATALOG
)


def _reported(results: ProjectResults, metric: DecisionMetric) -> tuple[float | None, IrrStatus | None]:
    """The metric's one Project result field, and the IRR status that explains
    it where there is one. Explicit per metric: no reflection. A visible
    Investment's Minimum DSCR is its ``min_aggregate_dscr``."""

    match metric:
        case DecisionMetric.LEVERED_IRR:
            return results.levered_irr, results.levered_irr_status
        case DecisionMetric.UNLEVERED_IRR:
            return results.unlevered_irr, results.unlevered_irr_status
        case DecisionMetric.EQUITY_MULTIPLE:
            return results.equity_multiple, None
        case DecisionMetric.TOTAL_PROFIT:
            return results.total_profit, None
        case DecisionMetric.TOTAL_EQUITY_INVESTED:
            return results.total_equity_invested, None
        case DecisionMetric.EXIT_VALUE:
            return results.exit_value, None
        case DecisionMetric.MIN_DSCR:
            if isinstance(results, ConsolidatedResults):
                return results.min_aggregate_dscr, None
            return results.min_dscr, None


# =============================================================================
# Reasons
# =============================================================================


class FigureReason(StrEnum):
    """Why a figure is not available (DC-2)."""

    INVALID_VARIANT = "invalid_variant"
    IRR_NOT_DEFINED = "irr_not_defined"
    NOT_REPORTED = "not_reported"
    BASE_SCENARIO_INVALID = "base_scenario_invalid"
    BASE_SCENARIO_NOT_REPORTED = "base_scenario_not_reported"
    SCENARIO_INVALID = "scenario_invalid"
    SCENARIO_NOT_REPORTED = "scenario_not_reported"


class OmissionReason(StrEnum):
    """Why a catalog metric is not part of this matrix."""

    DIFFERENT_HOLD_PERIODS = "different_hold_periods"


class CellIssueSource(StrEnum):
    """Which validator found a variant invalid."""

    STRATEGY = "strategy"
    SCENARIO = "scenario"
    LEASE_LEVEL = "lease_level"
    INVESTMENT = "investment"


class CellStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class DecisionComparisonError(RuntimeError):
    """The comparison was handed an incoherent matrix -- a programming error,
    never a financial finding, so it is not a ``ValueError`` and no caller may
    read it as an invalid variant."""


# =============================================================================
# What the comparison receives
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class AxisMember:
    """One Strategy (a row) or one Scenario (a column), as received.
    ``is_base`` marks the implicit Base on its axis; the order given is the
    presentation order."""

    id: str
    name: str
    is_base: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CellIssue:
    """One deterministic reason a variant is invalid, in its validator's own
    words. ``field`` locates it where the validator does."""

    source: CellIssueSource
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CellInput:
    """One completed variant, as the orchestration hands it over: either its
    Project ``results`` with their ``source_fingerprint`` and resolved
    ``hold_period``, or the ``issues`` that made it invalid."""

    strategy_id: str
    scenario_id: str
    results: ProjectResults | None
    source_fingerprint: str | None
    cache_status: str | None
    hold_period: int | None
    issues: tuple[CellIssue, ...] = ()


# =============================================================================
# What the comparison returns
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyRow:
    """One Strategy row group. ``hold_period`` is the hold its valid cells
    share, or ``None`` when none is valid."""

    strategy_id: str
    name: str
    is_base: bool
    hold_period: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioColumn:
    scenario_id: str
    name: str
    is_base: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CellSource:
    """A cell a cross-cell figure read, and its source fingerprint (DC-5)."""

    strategy_id: str
    scenario_id: str
    source_fingerprint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricValue:
    """One cell's value for one metric: the ``AcquisitionResults`` field, or
    ``None`` with its reason. ``irr_status`` is the engine's status for an IRR
    metric."""

    metric: DecisionMetric
    value: float | None
    irr_status: IrrStatus | None
    reason: FigureReason | None
    message: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DeltaVsBase:
    """``metric(S, C) - metric(S, Base Scenario)``. ``is_baseline`` marks the
    Base Scenario cell itself, whose Delta is zero by definition."""

    metric: DecisionMetric
    value: float | None
    is_baseline: bool
    reason: FigureReason | None
    message: str | None
    sources: tuple[CellSource, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class WorstCase:
    """The least favourable value of one metric across one Strategy's
    Scenarios, and the Scenario that produced it."""

    metric: DecisionMetric
    direction: MetricDirection
    value: float | None
    scenario_id: str | None
    scenario_name: str | None
    reason: FigureReason | None
    message: str | None
    unavailable_scenario_ids: tuple[str, ...]
    sources: tuple[CellSource, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioRange:
    """The spread of one metric across one Strategy's Scenarios: the maximum
    less the minimum, and the Scenarios at each end."""

    metric: DecisionMetric
    minimum: float | None
    minimum_scenario_id: str | None
    maximum: float | None
    maximum_scenario_id: str | None
    spread: float | None
    reason: FigureReason | None
    message: str | None
    unavailable_scenario_ids: tuple[str, ...]
    sources: tuple[CellSource, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionCell:
    """One Strategy x Scenario variant. ``metrics`` and ``deltas`` hold one
    entry per applicable metric, in catalog order. ``cache_status`` is
    operational metadata, never investment information."""

    strategy_id: str
    scenario_id: str
    status: CellStatus
    issues: tuple[CellIssue, ...]
    source_fingerprint: str | None
    cache_status: str | None
    hold_period: int | None
    results: ProjectResults | None
    metrics: tuple[MetricValue, ...]
    deltas: tuple[DeltaVsBase, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyFigures:
    """One Strategy's cross-Scenario figures, one per applicable metric. Empty
    when the matrix has no persisted Scenario."""

    strategy_id: str
    worst_cases: tuple[WorstCase, ...]
    ranges: tuple[ScenarioRange, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class OmittedMetric:
    metric: DecisionMetric
    reason: OmissionReason
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionMatrix:
    """The whole comparison package.

    - ``strategies`` and ``scenarios``: the axes, in presentation order, the
      implicit Bases first;
    - ``metrics``: the applicable catalog, in display order;
      ``omitted_metrics`` says which were left out and why;
    - ``hold_periods``: the distinct holds of the valid cells, ascending;
    - ``cross_scenario_figures``: whether Worst Case and Range are part of the
      package (only when a persisted Scenario exists);
    - ``cells``: row-major, in presentation order;
    - ``matrix_fingerprint``: the Decision Comparison fingerprint, or ``None``
      with ``matrix_fingerprint_reason``."""

    perspective: DecisionPerspective
    strategies: tuple[StrategyRow, ...]
    scenarios: tuple[ScenarioColumn, ...]
    metrics: tuple[MetricSpec, ...]
    omitted_metrics: tuple[OmittedMetric, ...]
    hold_periods: tuple[int, ...]
    cross_scenario_figures: bool
    cells: tuple[DecisionCell, ...]
    strategy_figures: tuple[StrategyFigures, ...]
    matrix_fingerprint: str | None
    matrix_fingerprint_reason: str | None


# =============================================================================
# Structure
# =============================================================================


def _canonical_key(member: AxisMember) -> tuple[int, str]:
    """Stable identity order: the Base first, then ids ascending. Never the
    presentation order, never a value."""

    return (0 if member.is_base else 1, member.id)


def _require_axis(members: Sequence[AxisMember], axis: str) -> None:
    ids = [member.id for member in members]
    if len(set(ids)) != len(ids):
        raise DecisionComparisonError(f"The {axis} axis repeats an id.")
    if [member.is_base for member in members].count(True) != 1:
        raise DecisionComparisonError(f"The {axis} axis must hold exactly one implicit Base.")


def _require_cell(cell: CellInput) -> None:
    if cell.results is None:
        if not cell.issues:
            raise DecisionComparisonError(
                f"Cell ({cell.strategy_id!r}, {cell.scenario_id!r}) has neither results nor issues."
            )
        return
    if cell.issues or cell.source_fingerprint is None or cell.hold_period is None:
        raise DecisionComparisonError(
            f"Cell ({cell.strategy_id!r}, {cell.scenario_id!r}) has results but not exactly a "
            "source fingerprint and a hold period with no issues."
        )


def _index_cells(
    cells: Iterable[CellInput],
    strategies: Sequence[AxisMember],
    scenarios: Sequence[AxisMember],
) -> dict[tuple[str, str], CellInput]:
    indexed: dict[tuple[str, str], CellInput] = {}
    for cell in cells:
        key = (cell.strategy_id, cell.scenario_id)
        if key in indexed:
            raise DecisionComparisonError(f"Cell {key!r} is given twice.")
        _require_cell(cell)
        indexed[key] = cell
    expected = {(strategy.id, scenario.id) for strategy in strategies for scenario in scenarios}
    if set(indexed) != expected:
        raise DecisionComparisonError(
            "The cells must be exactly one per Strategy x Scenario pair of the axes."
        )
    return indexed


# =============================================================================
# One cell, one metric
# =============================================================================


def _metric_value(cell: CellInput, spec: MetricSpec) -> MetricValue:
    if cell.results is None:
        return MetricValue(
            metric=spec.metric,
            value=None,
            irr_status=None,
            reason=FigureReason.INVALID_VARIANT,
            message=f"{spec.label} is not available because this variant is invalid.",
        )
    value, irr_status = _reported(cell.results, spec.metric)
    if irr_status is not None and (irr_status is not IrrStatus.DEFINED or value is None):
        return MetricValue(
            metric=spec.metric,
            value=None,
            irr_status=irr_status,
            reason=FigureReason.IRR_NOT_DEFINED,
            message=f"{spec.label} is not reported for this variant ({irr_status.value}).",
        )
    if value is None:
        return MetricValue(
            metric=spec.metric,
            value=None,
            irr_status=irr_status,
            reason=FigureReason.NOT_REPORTED,
            message=f"{spec.label} is not reported for this variant.",
        )
    return MetricValue(
        metric=spec.metric, value=value, irr_status=irr_status, reason=None, message=None
    )


def _source(cell: CellInput) -> CellSource:
    assert cell.source_fingerprint is not None
    return CellSource(
        strategy_id=cell.strategy_id,
        scenario_id=cell.scenario_id,
        source_fingerprint=cell.source_fingerprint,
    )


def _delta(
    cell: CellInput,
    base_cell: CellInput,
    spec: MetricSpec,
    values: Mapping[tuple[str, str], MetricValue],
) -> DeltaVsBase:
    """Delta vs Base Scenario for one cell: always against ``base_cell``, the
    same Strategy's Base Scenario cell. It needs those two cells and nothing
    else."""

    is_baseline = cell.scenario_id == base_cell.scenario_id

    def unavailable(reason: FigureReason, message: str) -> DeltaVsBase:
        return DeltaVsBase(
            metric=spec.metric,
            value=None,
            is_baseline=is_baseline,
            reason=reason,
            message=message,
            sources=(),
        )

    target = values[(cell.strategy_id, cell.scenario_id)]
    reference = values[(base_cell.strategy_id, base_cell.scenario_id)]
    if target.reason is FigureReason.INVALID_VARIANT:
        return unavailable(target.reason, "No Delta vs Base: this variant is invalid.")
    if reference.reason is FigureReason.INVALID_VARIANT:
        return unavailable(
            FigureReason.BASE_SCENARIO_INVALID,
            "No Delta vs Base: this Strategy's Base Scenario variant is invalid.",
        )
    if target.value is None:
        assert target.reason is not None
        return unavailable(target.reason, f"No Delta vs Base: {spec.label} is not reported here.")
    if reference.value is None:
        return unavailable(
            FigureReason.BASE_SCENARIO_NOT_REPORTED,
            f"No Delta vs Base: {spec.label} is not reported under this Strategy's Base Scenario.",
        )
    return DeltaVsBase(
        metric=spec.metric,
        value=target.value - reference.value,
        is_baseline=is_baseline,
        reason=None,
        message=None,
        sources=(_source(base_cell), _source(cell)),
    )


# =============================================================================
# One Strategy, one metric, every Scenario
# =============================================================================


def _row_availability(
    strategy_id: str,
    spec: MetricSpec,
    ordered_scenarios: Sequence[AxisMember],
    values: Mapping[tuple[str, str], MetricValue],
) -> tuple[FigureReason | None, str | None, tuple[str, ...]]:
    """Whether every Scenario cell of the row is valid and reports the metric
    -- the completeness Worst Case and Range require. Nothing is skipped."""

    invalid = tuple(
        scenario.id
        for scenario in ordered_scenarios
        if values[(strategy_id, scenario.id)].reason is FigureReason.INVALID_VARIANT
    )
    if invalid:
        names = ", ".join(scenario.name for scenario in ordered_scenarios if scenario.id in invalid)
        return (
            FigureReason.SCENARIO_INVALID,
            f"Not available: every scenario must be a valid variant, and {names} is not.",
            invalid,
        )
    missing = tuple(
        scenario.id
        for scenario in ordered_scenarios
        if values[(strategy_id, scenario.id)].value is None
    )
    if missing:
        names = ", ".join(scenario.name for scenario in ordered_scenarios if scenario.id in missing)
        return (
            FigureReason.SCENARIO_NOT_REPORTED,
            f"Not available: {spec.label} is not reported under {names}.",
            missing,
        )
    return None, None, ()


def _worst_case(
    strategy_id: str,
    spec: MetricSpec,
    ordered_scenarios: Sequence[AxisMember],
    cells: Mapping[tuple[str, str], CellInput],
    values: Mapping[tuple[str, str], MetricValue],
) -> WorstCase:
    reason, message, unavailable = _row_availability(strategy_id, spec, ordered_scenarios, values)
    if reason is not None:
        return WorstCase(
            metric=spec.metric,
            direction=spec.direction,
            value=None,
            scenario_id=None,
            scenario_name=None,
            reason=reason,
            message=message,
            unavailable_scenario_ids=unavailable,
            sources=(),
        )
    worst_scenario: AxisMember | None = None
    worst_value: float | None = None
    for scenario in ordered_scenarios:
        value = values[(strategy_id, scenario.id)].value
        assert value is not None
        # Strictly worse only, so a tie keeps the first cell in canonical order.
        is_worse = (
            worst_value is None
            or (spec.direction is MetricDirection.HIGHER_IS_BETTER and value < worst_value)
            or (spec.direction is MetricDirection.LOWER_IS_BETTER and value > worst_value)
        )
        if is_worse:
            worst_scenario, worst_value = scenario, value
    assert worst_scenario is not None
    return WorstCase(
        metric=spec.metric,
        direction=spec.direction,
        value=worst_value,
        scenario_id=worst_scenario.id,
        scenario_name=worst_scenario.name,
        reason=None,
        message=None,
        unavailable_scenario_ids=(),
        sources=tuple(_source(cells[(strategy_id, s.id)]) for s in ordered_scenarios),
    )


def _range(
    strategy_id: str,
    spec: MetricSpec,
    ordered_scenarios: Sequence[AxisMember],
    cells: Mapping[tuple[str, str], CellInput],
    values: Mapping[tuple[str, str], MetricValue],
) -> ScenarioRange:
    reason, message, unavailable = _row_availability(strategy_id, spec, ordered_scenarios, values)
    if reason is not None:
        return ScenarioRange(
            metric=spec.metric,
            minimum=None,
            minimum_scenario_id=None,
            maximum=None,
            maximum_scenario_id=None,
            spread=None,
            reason=reason,
            message=message,
            unavailable_scenario_ids=unavailable,
            sources=(),
        )
    low: tuple[float, str] | None = None
    high: tuple[float, str] | None = None
    for scenario in ordered_scenarios:
        value = values[(strategy_id, scenario.id)].value
        assert value is not None
        if low is None or value < low[0]:
            low = (value, scenario.id)
        if high is None or value > high[0]:
            high = (value, scenario.id)
    assert low is not None and high is not None
    return ScenarioRange(
        metric=spec.metric,
        minimum=low[0],
        minimum_scenario_id=low[1],
        maximum=high[0],
        maximum_scenario_id=high[1],
        spread=high[0] - low[0],
        reason=None,
        message=None,
        unavailable_scenario_ids=(),
        sources=tuple(_source(cells[(strategy_id, s.id)]) for s in ordered_scenarios),
    )


# =============================================================================
# Horizons and the matrix fingerprint
# =============================================================================


def _applicable_metrics(
    hold_periods: tuple[int, ...],
    catalog: tuple[MetricSpec, ...] = PROJECT_METRIC_CATALOG,
) -> tuple[tuple[MetricSpec, ...], tuple[OmittedMetric, ...]]:
    """Every catalog metric when the valid variants share one hold period;
    otherwise the horizon-independent metrics alone (ST-5, DC-4)."""

    if len(hold_periods) <= 1:
        return catalog, ()
    holds = " and ".join(str(hold) for hold in hold_periods)
    omitted_labels = " and ".join(spec.label for spec in catalog if spec.horizon_dependent)
    message = (
        f"Strategies use different hold periods ({holds} years). {omitted_labels} are not "
        "compared across different horizons."
    )
    return (
        tuple(spec for spec in catalog if not spec.horizon_dependent),
        tuple(
            OmittedMetric(metric=spec.metric, reason=OmissionReason.DIFFERENT_HOLD_PERIODS, message=message)
            for spec in catalog
            if spec.horizon_dependent
        ),
    )


def decision_matrix_fingerprint(
    perspective: DecisionPerspective, identities: Iterable[tuple[str, str, str]]
) -> str:
    """The Decision Comparison fingerprint: sha256 of canonical JSON over
    ``(strategy_id, scenario_id, source_fingerprint)`` for every cell, sorted.
    Callers pass identities already in canonical order; they are sorted again
    here so no caller's order can reach the digest."""

    payload = {
        "perspective": perspective.value,
        "cells": sorted([strategy_id, scenario_id, fingerprint] for strategy_id, scenario_id, fingerprint in identities),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _matrix_fingerprint(
    cells: Mapping[tuple[str, str], CellInput],
    ordered_strategies: Sequence[AxisMember],
    ordered_scenarios: Sequence[AxisMember],
) -> tuple[str | None, str | None]:
    unavailable = [cell for cell in cells.values() if cell.source_fingerprint is None]
    if unavailable:
        count = len(unavailable)
        noun = "variant is" if count == 1 else "variants are"
        return None, (
            f"No matrix fingerprint: {count} {noun} invalid, and every cell needs a current "
            "source fingerprint."
        )
    identities = []
    for strategy in ordered_strategies:
        for scenario in ordered_scenarios:
            cell = cells[(strategy.id, scenario.id)]
            assert cell.source_fingerprint is not None
            identities.append((strategy.id, scenario.id, cell.source_fingerprint))
    return decision_matrix_fingerprint(DecisionPerspective.PROJECT, identities), None


# =============================================================================
# The package
# =============================================================================


def _row_hold(strategy_id: str, cells: Mapping[tuple[str, str], CellInput]) -> int | None:
    holds = {
        cell.hold_period
        for (row, _), cell in cells.items()
        if row == strategy_id and cell.hold_period is not None
    }
    return holds.pop() if len(holds) == 1 else None


def compare_decision_matrix(
    *,
    strategies: Sequence[AxisMember],
    scenarios: Sequence[AxisMember],
    cells: Iterable[CellInput],
    catalog: tuple[MetricSpec, ...] = PROJECT_METRIC_CATALOG,
) -> DecisionMatrix:
    """The Strategy x Scenario comparison of completed variants.

    ``strategies`` and ``scenarios`` are the axes in presentation order, each
    with exactly one implicit Base; ``cells`` holds exactly one completed
    variant per pair. ``catalog`` is the Project catalog the cells' results
    are read with: a Unit's, or (P7.6) a visible Investment's. Raises
    ``DecisionComparisonError`` for an incoherent matrix -- never for an
    invalid variant, which is a cell of its own."""

    _require_axis(strategies, "Strategy")
    _require_axis(scenarios, "Scenario")
    indexed = _index_cells(cells, strategies, scenarios)
    ordered_strategies = sorted(strategies, key=_canonical_key)
    ordered_scenarios = sorted(scenarios, key=_canonical_key)
    base_scenario = ordered_scenarios[0]

    hold_periods = tuple(
        sorted({cell.hold_period for cell in indexed.values() if cell.hold_period is not None})
    )
    applicable, omitted = _applicable_metrics(hold_periods, catalog)
    values = {
        (key, spec.metric): _metric_value(cell, spec)
        for key, cell in indexed.items()
        for spec in applicable
    }

    def values_of(spec: MetricSpec) -> dict[tuple[str, str], MetricValue]:
        return {key: values[(key, spec.metric)] for key in indexed}

    per_metric = {spec.metric: values_of(spec) for spec in applicable}

    decision_cells: list[DecisionCell] = []
    for strategy in strategies:
        base_cell = indexed[(strategy.id, base_scenario.id)]
        for scenario in scenarios:
            cell = indexed[(strategy.id, scenario.id)]
            decision_cells.append(
                DecisionCell(
                    strategy_id=strategy.id,
                    scenario_id=scenario.id,
                    status=CellStatus.VALID if cell.results is not None else CellStatus.INVALID,
                    issues=cell.issues,
                    source_fingerprint=cell.source_fingerprint,
                    cache_status=cell.cache_status,
                    hold_period=cell.hold_period,
                    results=cell.results,
                    metrics=tuple(per_metric[spec.metric][(strategy.id, scenario.id)] for spec in applicable),
                    deltas=tuple(
                        _delta(cell, base_cell, spec, per_metric[spec.metric]) for spec in applicable
                    ),
                )
            )

    cross_scenario_figures = len(scenarios) > 1
    strategy_figures = tuple(
        StrategyFigures(
            strategy_id=strategy.id,
            worst_cases=tuple(
                _worst_case(strategy.id, spec, ordered_scenarios, indexed, per_metric[spec.metric])
                for spec in applicable
            )
            if cross_scenario_figures
            else (),
            ranges=tuple(
                _range(strategy.id, spec, ordered_scenarios, indexed, per_metric[spec.metric])
                for spec in applicable
            )
            if cross_scenario_figures
            else (),
        )
        for strategy in strategies
    )

    fingerprint, fingerprint_reason = _matrix_fingerprint(indexed, ordered_strategies, ordered_scenarios)
    return DecisionMatrix(
        perspective=DecisionPerspective.PROJECT,
        strategies=tuple(
            StrategyRow(
                strategy_id=strategy.id,
                name=strategy.name,
                is_base=strategy.is_base,
                hold_period=_row_hold(strategy.id, indexed),
            )
            for strategy in strategies
        ),
        scenarios=tuple(
            ScenarioColumn(scenario_id=scenario.id, name=scenario.name, is_base=scenario.is_base)
            for scenario in scenarios
        ),
        metrics=applicable,
        omitted_metrics=omitted,
        hold_periods=hold_periods,
        cross_scenario_figures=cross_scenario_figures,
        cells=tuple(decision_cells),
        strategy_figures=strategy_figures,
        matrix_fingerprint=fingerprint,
        matrix_fingerprint_reason=fingerprint_reason,
    )


__all__ = [
    "INVESTMENT_PROJECT_METRIC_CATALOG",
    "PROJECT_METRIC_CATALOG",
    "ProjectResults",
    "AxisMember",
    "CellInput",
    "CellIssue",
    "CellIssueSource",
    "CellSource",
    "CellStatus",
    "DecisionCell",
    "DecisionComparisonError",
    "DecisionMatrix",
    "DecisionMetric",
    "DecisionPerspective",
    "DeltaVsBase",
    "FigureReason",
    "MetricDirection",
    "MetricSpec",
    "MetricUnit",
    "MetricValue",
    "OmissionReason",
    "OmittedMetric",
    "ScenarioColumn",
    "ScenarioRange",
    "StrategyFigures",
    "StrategyRow",
    "WorstCase",
    "compare_decision_matrix",
    "decision_matrix_fingerprint",
]
