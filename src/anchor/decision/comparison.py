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

from ..capital_structure.contracts import CapitalStructureStatus, PositionClass, PositionScope
from ..capital_structure.execution_contracts import (
    CommonEquityReturns,
    PositionResultStatus,
    PositionReturns,
    PositionUnavailableReason,
)
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
    """Whose returns the matrix compares (DC-3).

    ``PROJECT`` compares the project's own returns and stays the default and the
    upstream one. ``POSITION`` (P7.8B) compares **one capital position**, named
    by its stable id, across the same Strategy x Scenario variants: a different
    metric catalog over a different result contract, which is the whole point of
    a typed perspective -- a debt investor is not compared on project IRR. The
    partner perspective belongs to P7.9."""

    PROJECT = "project"
    POSITION = "position"


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


class PositionMetric(StrEnum):
    """The ``POSITION(position_id)`` metrics (P7.8B), each one existing P7.8A
    result field of the same meaning.

    The first eleven describe a **claim-bearing** position -- senior debt,
    mezzanine debt or preferred equity -- and split into two kinds that a matrix
    must never merge: the *return* metrics an investor realises (``IRR``,
    ``MOIC``, ``PROFIT``), which exist only when every claim was paid, and the
    *structural* metrics that are contractual underwriting facts (attachment,
    detachment, last-dollar basis, debt yield and coverage through the
    position), which stand whatever the cash settlement.

    The last five describe the **Common Equity** residual named by an authored
    marker. They come from ``StructuredCapitalResult.common_equity`` and never
    from ``AcquisitionResults.levered_*`` (NS-1): after structured capital, the
    two are different numbers with different meanings."""

    FUNDED_AMOUNT = "funded_amount"
    IRR = "irr"
    MOIC = "moic"
    PROFIT = "profit"
    ATTACHMENT_LTP = "attachment_ltp"
    DETACHMENT_LTP = "detachment_ltp"
    LAST_DOLLAR_BASIS = "last_dollar_basis"
    DEBT_YIELD_THROUGH = "debt_yield_through"
    HEADLINE_COVERAGE = "headline_coverage"
    MINIMUM_COVERAGE = "minimum_coverage"
    BALANCE_AT_MATURITY_OR_EXIT = "balance_at_maturity_or_exit"

    COMMON_EQUITY_IRR = "common_equity_irr"
    EQUITY_MULTIPLE = "equity_multiple"
    TOTAL_EQUITY_INVESTED = "total_equity_invested"
    TOTAL_CASH_RETURNED = "total_cash_returned"
    TOTAL_PROFIT = "total_profit"


#: What a matrix cell can report, whichever perspective it belongs to. The two
#: metric namespaces stay separate types: a Project metric is never selected
#: from a position result, and a position metric never from a Project one.
AnyDecisionMetric = DecisionMetric | PositionMetric


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

    metric: AnyDecisionMetric
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


def _reported(
    results: ProjectResults, metric: AnyDecisionMetric
) -> tuple[float | None, IrrStatus | None]:
    """The metric's one Project result field, and the IRR status that explains
    it where there is one. Explicit per metric: no reflection. A visible
    Investment's Minimum DSCR is its ``min_aggregate_dscr``.

    A position metric never reaches this function: the two namespaces are read
    by two selectors, so a Project result can never answer a position's
    question (Section 14)."""

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
        case _:
            raise DecisionComparisonError(f"{metric} is not a Project metric.")


# =============================================================================
# Reasons
# =============================================================================


class FigureReason(StrEnum):
    """Why a figure is not available (DC-2).

    The last three are P7.8B's, and they keep three states apart that a single
    "N/A" would blur: the selected position is **not in** this Strategy's
    Capital Structure at all; it is there but its own funding is unresolved; or
    it is there and blocked because something senior to it is unresolved. None
    of them is an invalid variant, and none of them is zero (P-9)."""

    INVALID_VARIANT = "invalid_variant"
    IRR_NOT_DEFINED = "irr_not_defined"
    NOT_REPORTED = "not_reported"
    BASE_SCENARIO_INVALID = "base_scenario_invalid"
    BASE_SCENARIO_NOT_REPORTED = "base_scenario_not_reported"
    SCENARIO_INVALID = "scenario_invalid"
    SCENARIO_NOT_REPORTED = "scenario_not_reported"
    NOT_APPLICABLE_TO_PERSPECTIVE = "not_applicable_to_perspective"
    UNRESOLVED_FUNDING_REQUIREMENT = "unresolved_funding_requirement"
    SENIOR_UNRESOLVED_FUNDING_REQUIREMENT = "senior_unresolved_funding_requirement"


class OmissionReason(StrEnum):
    """Why a catalog metric is not part of this matrix."""

    DIFFERENT_HOLD_PERIODS = "different_hold_periods"


class CellIssueSource(StrEnum):
    """Which validator found a variant invalid.

    ``CAPITAL_STRUCTURE`` (P7.8B) is the structured layer's own refusal: a
    structure that is not a valid contract for this analysis, or a valid one
    this Project state cannot execute. It is deliberately distinct from the
    Project validators above, because the analyst fixes it somewhere else."""

    STRATEGY = "strategy"
    SCENARIO = "scenario"
    LEASE_LEVEL = "lease_level"
    INVESTMENT = "investment"
    CAPITAL_STRUCTURE = "capital_structure"


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


class PositionApplicability(StrEnum):
    """Whether the selected position took part in one cell (P7.8B).

    - ``PRESENT``: the variant is valid and its resolved Capital Structure holds
      the position. Its metrics are reported, with returns N/A and a reason
      while its funding (or a senior claim's) is unresolved.
    - ``NOT_PRESENT``: the variant is valid and does not hold it.
    - ``NOT_ANALYSED``: the variant is invalid -- a Project refusal, or a
      Capital Structure the Project state cannot execute -- so nothing was
      analysed to be present in."""

    PRESENT = "present"
    NOT_PRESENT = "not_present"
    NOT_ANALYSED = "not_analysed"


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionCellInput:
    """One completed structured variant, as the orchestration hands it over
    (P7.8B).

    ``source_fingerprint`` is the **structured** source fingerprint, which is
    what makes this matrix's identity its own; ``project_source_fingerprint`` is
    carried beside it as provenance. An invalid variant carries its ``issues``
    and neither fingerprint."""

    strategy_id: str
    scenario_id: str
    applicability: PositionApplicability
    position: PositionReturns | None = None
    common_equity: CommonEquityReturns | None = None
    project_source_fingerprint: str | None = None
    source_fingerprint: str | None = None
    hold_period: int | None = None
    issues: tuple[CellIssue, ...] = ()


#: A cell of either perspective. The cross-cell helpers -- Delta, Worst Case and
#: Range -- read only the three fields both shapes share (the two axis ids and
#: the source fingerprint), so one implementation serves both perspectives and
#: their semantics can never drift apart.
AnyCellInput = CellInput | PositionCellInput


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

    metric: AnyDecisionMetric
    value: float | None
    irr_status: IrrStatus | None
    reason: FigureReason | None
    message: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DeltaVsBase:
    """``metric(S, C) - metric(S, Base Scenario)``. ``is_baseline`` marks the
    Base Scenario cell itself, whose Delta is zero by definition."""

    metric: AnyDecisionMetric
    value: float | None
    is_baseline: bool
    reason: FigureReason | None
    message: str | None
    sources: tuple[CellSource, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class WorstCase:
    """The least favourable value of one metric across one Strategy's
    Scenarios, and the Scenario that produced it."""

    metric: AnyDecisionMetric
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

    metric: AnyDecisionMetric
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
    metric: AnyDecisionMetric
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


def _source(cell: AnyCellInput) -> CellSource:
    assert cell.source_fingerprint is not None
    return CellSource(
        strategy_id=cell.strategy_id,
        scenario_id=cell.scenario_id,
        source_fingerprint=cell.source_fingerprint,
    )


def _delta(
    cell: AnyCellInput,
    base_cell: AnyCellInput,
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

    absent = tuple(
        scenario.id
        for scenario in ordered_scenarios
        if values[(strategy_id, scenario.id)].reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE
    )
    if absent:
        # P7.8B: the selected position is not in this Strategy's Capital
        # Structure, so there is no row of values to take a worst case or a
        # range of. Reporting one over the Scenarios that *do* hold it would
        # compare a position with its own absence.
        return (
            FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE,
            "Not available: the selected position is not in this Strategy's Capital Structure.",
            absent,
        )
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
    cells: Mapping[tuple[str, str], AnyCellInput],
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
    cells: Mapping[tuple[str, str], AnyCellInput],
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


def _row_hold(strategy_id: str, cells: Mapping[tuple[str, str], AnyCellInput]) -> int | None:
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


# =============================================================================
# Phase 7 Gate P7.8B -- the POSITION perspective (DC-3)
#
# The same comparison, over one capital position instead of the project. Every
# cross-cell rule above is reused unchanged -- Delta vs the same Strategy's Base
# Scenario, Worst Case and Range across that Strategy's Scenarios, ties to the
# first cell in canonical order, and a figure that needs every Scenario cell --
# so there is one implementation of those semantics, not two.
#
# What differs is only what a cell *is*:
#
# - its results are ``PositionReturns`` (or, for an authored Common Equity
#   marker, ``CommonEquityReturns``), never ``AcquisitionResults``;
# - its source fingerprint is the STRUCTURED one, so a Capital Structure edit
#   moves this matrix and leaves the Project matrix exactly where it was;
# - a cell may be **not applicable to this perspective**: the variant is
#   perfectly valid, and the selected position simply is not in that Strategy's
#   Capital Structure. That is neither an invalid variant nor a zero (P-9,
#   DC-2), and it makes that Strategy's Worst Case and Range unavailable rather
#   than quietly computed over the Scenarios that do hold it.
#
# Nothing here computes a financial figure of its own: every value is one P7.8A
# result field, selected.
# =============================================================================


#: The claim-bearing catalog: senior debt, mezzanine debt and preferred equity.
#: ``FUNDED_AMOUNT`` is "lower is better" for Worst Case only in the sense the
#: gate states -- more funded is more exposure -- and never as advice.
CLAIM_BEARING_POSITION_METRIC_CATALOG: tuple[MetricSpec, ...] = (
    MetricSpec(
        metric=PositionMetric.FUNDED_AMOUNT,
        label="Funded Amount",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.LOWER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.IRR,
        label="IRR",
        unit=MetricUnit.RATE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.MOIC,
        label="MOIC",
        unit=MetricUnit.MULTIPLE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.PROFIT,
        label="Profit",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.ATTACHMENT_LTP,
        label="Attachment LTP",
        unit=MetricUnit.RATE,
        direction=MetricDirection.LOWER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.DETACHMENT_LTP,
        label="Detachment LTP",
        unit=MetricUnit.RATE,
        direction=MetricDirection.LOWER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.LAST_DOLLAR_BASIS,
        label="Last-Dollar Basis",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.LOWER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.DEBT_YIELD_THROUGH,
        label="Debt Yield Through Position",
        unit=MetricUnit.RATE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.HEADLINE_COVERAGE,
        label="Headline Coverage Through",
        unit=MetricUnit.MULTIPLE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.MINIMUM_COVERAGE,
        label="Minimum Coverage Through",
        unit=MetricUnit.MULTIPLE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=True,
    ),
    MetricSpec(
        metric=PositionMetric.BALANCE_AT_MATURITY_OR_EXIT,
        label="Balance at Maturity or Exit",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.LOWER_IS_BETTER,
        horizon_dependent=True,
    ),
)

#: The Common Equity catalog, for an authored marker. ``TOTAL_CASH_RETURNED``
#: is horizon-dependent: more years of distributions is not a better outcome,
#: it is a longer one.
COMMON_EQUITY_POSITION_METRIC_CATALOG: tuple[MetricSpec, ...] = (
    MetricSpec(
        metric=PositionMetric.COMMON_EQUITY_IRR,
        label="Common Equity IRR",
        unit=MetricUnit.RATE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.EQUITY_MULTIPLE,
        label="Equity Multiple",
        unit=MetricUnit.MULTIPLE,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.TOTAL_EQUITY_INVESTED,
        label="Total Equity Invested",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.LOWER_IS_BETTER,
        horizon_dependent=False,
    ),
    MetricSpec(
        metric=PositionMetric.TOTAL_CASH_RETURNED,
        label="Total Cash Returned",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=True,
    ),
    MetricSpec(
        metric=PositionMetric.TOTAL_PROFIT,
        label="Total Profit",
        unit=MetricUnit.CURRENCY,
        direction=MetricDirection.HIGHER_IS_BETTER,
        horizon_dependent=False,
    ),
)

#: The metrics an investor only realises once every claim of the position was
#: paid. While its funding is unresolved they are N/A with a reason -- never
#: zero, and never quietly replaced by a contractual figure.
_REALISED_POSITION_METRICS = frozenset(
    {PositionMetric.IRR, PositionMetric.MOIC, PositionMetric.PROFIT}
)

#: How a P7.8A unavailability becomes a matrix reason. Two distinct states, kept
#: distinct: the position's own funding is unresolved, or something senior to it
#: is, so its cash is unknowable and it was not settled at all.
_POSITION_UNAVAILABLE_REASONS = {
    PositionUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT: (
        FigureReason.UNRESOLVED_FUNDING_REQUIREMENT
    ),
    PositionUnavailableReason.SENIOR_UNRESOLVED_FUNDING_REQUIREMENT: (
        FigureReason.SENIOR_UNRESOLVED_FUNDING_REQUIREMENT
    ),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionDecisionCell:
    """One Strategy x Scenario cell of a Position matrix.

    ``position_status`` and ``unavailable_reason`` are the P7.8A result's own,
    so the UI can say *why* a return is N/A without deriving anything."""

    strategy_id: str
    scenario_id: str
    status: CellStatus
    applicability: PositionApplicability
    issues: tuple[CellIssue, ...]
    project_source_fingerprint: str | None
    source_fingerprint: str | None
    hold_period: int | None
    position_status: PositionResultStatus | None
    unavailable_reason: PositionUnavailableReason | None
    unavailable_message: str | None
    metrics: tuple[MetricValue, ...]
    deltas: tuple[DeltaVsBase, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionDecisionMatrix:
    """The whole Position comparison package: the axes, the catalog that the
    selected position's class decides, the cells and the cross-Scenario figures.

    ``matrix_fingerprint`` includes the selected ``position_id`` and every
    cell's **structured** source fingerprint, so two different positions over
    the same variants never share one."""

    perspective: DecisionPerspective
    position_id: str
    position_name: str
    position_class: PositionClass
    scope: PositionScope
    is_common_equity_marker: bool
    strategies: tuple[StrategyRow, ...]
    scenarios: tuple[ScenarioColumn, ...]
    metrics: tuple[MetricSpec, ...]
    omitted_metrics: tuple[OmittedMetric, ...]
    hold_periods: tuple[int, ...]
    cross_scenario_figures: bool
    cells: tuple[PositionDecisionCell, ...]
    strategy_figures: tuple[StrategyFigures, ...]
    matrix_fingerprint: str | None
    matrix_fingerprint_reason: str | None


def _position_reported(
    position: PositionReturns, metric: AnyDecisionMetric
) -> tuple[float | None, IrrStatus | None]:
    """One claim-bearing metric's P7.8A result field, and the IRR status where
    there is one. Explicit per metric: no reflection."""

    match metric:
        case PositionMetric.FUNDED_AMOUNT:
            return position.funded_amount, None
        case PositionMetric.IRR:
            return position.irr, position.irr_status
        case PositionMetric.MOIC:
            return position.moic, None
        case PositionMetric.PROFIT:
            return position.profit, None
        case PositionMetric.ATTACHMENT_LTP:
            return position.attachment_ltv, None
        case PositionMetric.DETACHMENT_LTP:
            return position.detachment_ltv, None
        case PositionMetric.LAST_DOLLAR_BASIS:
            return position.last_dollar_basis, None
        case PositionMetric.DEBT_YIELD_THROUGH:
            return position.debt_yield_through, None
        case PositionMetric.HEADLINE_COVERAGE:
            return position.headline_coverage, None
        case PositionMetric.MINIMUM_COVERAGE:
            return position.minimum_coverage, None
        case PositionMetric.BALANCE_AT_MATURITY_OR_EXIT:
            return position.balance_at_maturity_or_exit, None
        case _:
            raise DecisionComparisonError(
                f"{metric} is not a claim-bearing position metric."
            )


def _common_equity_reported(
    common_equity: CommonEquityReturns, metric: AnyDecisionMetric
) -> tuple[float | None, IrrStatus | None]:
    """One Common Equity metric's field, read off the structured residual --
    never off ``AcquisitionResults.levered_*`` (NS-1)."""

    match metric:
        case PositionMetric.COMMON_EQUITY_IRR:
            return common_equity.irr, common_equity.irr_status
        case PositionMetric.EQUITY_MULTIPLE:
            return common_equity.equity_multiple, None
        case PositionMetric.TOTAL_EQUITY_INVESTED:
            return common_equity.total_equity_invested, None
        case PositionMetric.TOTAL_CASH_RETURNED:
            return common_equity.total_cash_returned, None
        case PositionMetric.TOTAL_PROFIT:
            return common_equity.total_profit, None
        case _:
            raise DecisionComparisonError(f"{metric} is not a Common Equity metric.")


def _unavailable(spec: MetricSpec, reason: FigureReason, message: str) -> MetricValue:
    return MetricValue(
        metric=spec.metric, value=None, irr_status=None, reason=reason, message=message
    )


def _position_metric_value(cell: PositionCellInput, spec: MetricSpec) -> MetricValue:
    """One cell's value for one position metric, or ``None`` with the reason
    that names the state it is actually in."""

    if cell.applicability is PositionApplicability.NOT_ANALYSED:
        return _unavailable(
            spec,
            FigureReason.INVALID_VARIANT,
            f"{spec.label} is not available because this variant is invalid.",
        )
    if cell.applicability is PositionApplicability.NOT_PRESENT:
        return _unavailable(
            spec,
            FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE,
            "Not present in this Strategy's Capital Structure.",
        )

    if cell.common_equity is not None:
        common_equity = cell.common_equity
        if common_equity.status is not CapitalStructureStatus.COMPLETE:
            return _unavailable(
                spec,
                FigureReason.UNRESOLVED_FUNDING_REQUIREMENT,
                common_equity.unavailable_message
                or f"{spec.label} is not available while a Funding Requirement is unresolved.",
            )
        value, irr_status = _common_equity_reported(common_equity, spec.metric)
    else:
        position = cell.position
        if position is None:
            raise DecisionComparisonError(
                f"Cell ({cell.strategy_id!r}, {cell.scenario_id!r}) is present but carries no "
                "position result."
            )
        if spec.metric in _REALISED_POSITION_METRICS and position.status is not (
            PositionResultStatus.COMPLETE
        ):
            reason = (
                None
                if position.unavailable_reason is None
                else _POSITION_UNAVAILABLE_REASONS.get(position.unavailable_reason)
            )
            return _unavailable(
                spec,
                reason or FigureReason.NOT_REPORTED,
                position.unavailable_message
                or f"{spec.label} is not available for this position.",
            )
        value, irr_status = _position_reported(position, spec.metric)

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


def _require_position_cell(cell: PositionCellInput) -> None:
    """One cell's shape must match the state it claims: an analysed cell carries
    both fingerprints and a hold period and no issue; an unanalysed one carries
    its issues and nothing else; a present cell carries exactly one result."""

    if cell.applicability is PositionApplicability.NOT_ANALYSED:
        if not cell.issues:
            raise DecisionComparisonError(
                f"Cell ({cell.strategy_id!r}, {cell.scenario_id!r}) was not analysed and has no "
                "issues."
            )
        return
    if cell.issues or cell.source_fingerprint is None or cell.hold_period is None:
        raise DecisionComparisonError(
            f"Cell ({cell.strategy_id!r}, {cell.scenario_id!r}) was analysed but does not carry "
            "exactly a structured source fingerprint and a hold period with no issues."
        )
    results = [carried for carried in (cell.position, cell.common_equity) if carried is not None]
    expected = 1 if cell.applicability is PositionApplicability.PRESENT else 0
    if len(results) != expected:
        raise DecisionComparisonError(
            f"Cell ({cell.strategy_id!r}, {cell.scenario_id!r}) is {cell.applicability.value} and "
            f"carries {len(results)} result(s)."
        )


def _index_position_cells(
    cells: Iterable[PositionCellInput],
    strategies: Sequence[AxisMember],
    scenarios: Sequence[AxisMember],
) -> dict[tuple[str, str], PositionCellInput]:
    indexed: dict[tuple[str, str], PositionCellInput] = {}
    for cell in cells:
        key = (cell.strategy_id, cell.scenario_id)
        if key in indexed:
            raise DecisionComparisonError(f"Cell {key!r} is given twice.")
        _require_position_cell(cell)
        indexed[key] = cell
    expected = {(strategy.id, scenario.id) for strategy in strategies for scenario in scenarios}
    if set(indexed) != expected:
        raise DecisionComparisonError(
            "The cells must be exactly one per Strategy x Scenario pair of the axes."
        )
    return indexed


def position_decision_matrix_fingerprint(
    position_id: str, identities: Iterable[tuple[str, str, str]]
) -> str:
    """The Position Decision Comparison fingerprint: sha256 of canonical JSON
    over the perspective, the **selected position id** and every cell's
    structured source fingerprint, sorted.

    The position id is part of the identity on purpose: two positions compared
    over the very same variants are two different comparisons, and a shared
    digest would let one be served as the other."""

    payload = {
        "perspective": DecisionPerspective.POSITION.value,
        "position_id": position_id,
        "cells": sorted(
            [strategy_id, scenario_id, fingerprint]
            for strategy_id, scenario_id, fingerprint in identities
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _position_matrix_fingerprint(
    position_id: str,
    cells: Mapping[tuple[str, str], PositionCellInput],
    ordered_strategies: Sequence[AxisMember],
    ordered_scenarios: Sequence[AxisMember],
) -> tuple[str | None, str | None]:
    unavailable = [cell for cell in cells.values() if cell.source_fingerprint is None]
    if unavailable:
        count = len(unavailable)
        noun = "variant is" if count == 1 else "variants are"
        return None, (
            f"No matrix fingerprint: {count} {noun} invalid, and every cell needs a current "
            "structured source fingerprint."
        )
    identities = []
    for strategy in ordered_strategies:
        for scenario in ordered_scenarios:
            cell = cells[(strategy.id, scenario.id)]
            assert cell.source_fingerprint is not None
            identities.append((strategy.id, scenario.id, cell.source_fingerprint))
    return position_decision_matrix_fingerprint(position_id, identities), None


def compare_position_decision_matrix(
    *,
    position_id: str,
    position_name: str,
    position_class: PositionClass,
    scope: PositionScope,
    is_common_equity_marker: bool,
    strategies: Sequence[AxisMember],
    scenarios: Sequence[AxisMember],
    cells: Iterable[PositionCellInput],
    catalog: tuple[MetricSpec, ...],
) -> PositionDecisionMatrix:
    """The Strategy x Scenario comparison of one capital position.

    ``catalog`` is the position's own: the claim-bearing catalog, or the Common
    Equity one for an authored marker. Raises ``DecisionComparisonError`` for an
    incoherent matrix -- never for an invalid variant or an absent position,
    each of which is a cell of its own."""

    _require_axis(strategies, "Strategy")
    _require_axis(scenarios, "Scenario")
    indexed = _index_position_cells(cells, strategies, scenarios)
    ordered_strategies = sorted(strategies, key=_canonical_key)
    ordered_scenarios = sorted(scenarios, key=_canonical_key)
    base_scenario = ordered_scenarios[0]

    hold_periods = tuple(
        sorted({cell.hold_period for cell in indexed.values() if cell.hold_period is not None})
    )
    applicable, omitted = _applicable_metrics(hold_periods, catalog)
    values = {
        (key, spec.metric): _position_metric_value(cell, spec)
        for key, cell in indexed.items()
        for spec in applicable
    }
    per_metric = {
        spec.metric: {key: values[(key, spec.metric)] for key in indexed} for spec in applicable
    }

    decision_cells: list[PositionDecisionCell] = []
    for strategy in strategies:
        base_cell = indexed[(strategy.id, base_scenario.id)]
        for scenario in scenarios:
            cell = indexed[(strategy.id, scenario.id)]
            position = cell.position
            decision_cells.append(
                PositionDecisionCell(
                    strategy_id=strategy.id,
                    scenario_id=scenario.id,
                    status=CellStatus.INVALID
                    if cell.applicability is PositionApplicability.NOT_ANALYSED
                    else CellStatus.VALID,
                    applicability=cell.applicability,
                    issues=cell.issues,
                    project_source_fingerprint=cell.project_source_fingerprint,
                    source_fingerprint=cell.source_fingerprint,
                    hold_period=cell.hold_period,
                    position_status=None if position is None else position.status,
                    unavailable_reason=None if position is None else position.unavailable_reason,
                    unavailable_message=(
                        cell.common_equity.unavailable_message
                        if cell.common_equity is not None
                        else None
                        if position is None
                        else position.unavailable_message
                    ),
                    metrics=tuple(
                        per_metric[spec.metric][(strategy.id, scenario.id)] for spec in applicable
                    ),
                    deltas=tuple(
                        _delta(cell, base_cell, spec, per_metric[spec.metric])
                        for spec in applicable
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

    fingerprint, fingerprint_reason = _position_matrix_fingerprint(
        position_id, indexed, ordered_strategies, ordered_scenarios
    )
    return PositionDecisionMatrix(
        perspective=DecisionPerspective.POSITION,
        position_id=position_id,
        position_name=position_name,
        position_class=position_class,
        scope=scope,
        is_common_equity_marker=is_common_equity_marker,
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
    "CLAIM_BEARING_POSITION_METRIC_CATALOG",
    "COMMON_EQUITY_POSITION_METRIC_CATALOG",
    "INVESTMENT_PROJECT_METRIC_CATALOG",
    "PROJECT_METRIC_CATALOG",
    "AnyCellInput",
    "AnyDecisionMetric",
    "PositionApplicability",
    "PositionCellInput",
    "PositionDecisionCell",
    "PositionDecisionMatrix",
    "PositionMetric",
    "ProjectResults",
    "compare_position_decision_matrix",
    "position_decision_matrix_fingerprint",
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
