"""Phase 7 Gate P7.8B -- the POSITION Decision Matrix.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 14.1
(DC-2 to DC-7) and Section 15.4, and
``docs/architecture/P7_8_PRODUCT_INTEGRATION.md``.

The claims under test:

- **Every cell is honest** (DC-2, P-9). A cell is an invalid variant, a valid
  variant that does not hold the selected position, or a valid variant that
  holds it -- whose *returns* may still be N/A with a deterministic funding
  reason while its structural metrics stand. None of the three is zero.
- **Every figure comes from the backend** (P-5, Q22). Each metric is one P7.8A
  result field, selected; Delta, Worst Case and Range are the unchanged P7.5
  cross-cell figures, and a row with an absent position has none.
- **Its identity is its own** (Section 15.4). The Position matrix fingerprint
  includes the selected ``position_id`` and every cell's *structured* source
  fingerprint. A Capital Structure edit moves it and leaves the Project matrix
  fingerprint exactly where it was.
- **Different horizons drop horizon-dependent metrics** (ST-5, DC-4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from _p7_7_fixtures import fee, unit_scope  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    GOLDEN_MEZZ_AMOUNT,
    cash_pay_debt,
    claim_position,
    common_marker,
    round_deal,
    structure,
)
from anchor.analysis.scenario import ScenarioOperation, ScenarioOverride, ScenarioTarget
from anchor.analysis.strategy import (
    DispositionChoice,
    InvestmentStrategyOverlay,
    StrategyDomain,
    StrategyOverlay,
)
from anchor.capital_structure.contracts import CapitalStructure, PositionClass, ShortfallResolution
from anchor.capital_structure.execution_contracts import PositionResultStatus
from anchor.decision.comparison import (
    CellStatus,
    DecisionPerspective,
    FigureReason,
    MetricDirection,
    OmissionReason,
    PositionApplicability,
    PositionMetric,
)
from anchor.deals import store
from anchor.deals.contracts import PositionPerspectiveNotFoundError
from anchor.deals.decision_matrix import (
    analyze_decision_matrix,
    analyze_position_decision_matrix,
)
from anchor.deals.structured_variants import analyze_structured_variant

BASE = "base"
CEC = ShortfallResolution.COMMON_EQUITY_CONTRIBUTION


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def mezz(unit_id: str, *, rate: float = 0.12, resolution: ShortfallResolution = CEC, **terms: Any) -> Any:
    stated: dict[str, Any] = {
        "rate": rate,
        "amortization": 25,
        "io_period": 1,
        "maturity_month": 48,
        "fees": (fee("mezz-fee", amount=15_000.0),),
    }
    stated.update(terms)
    return claim_position(
        "mezz-a",
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=2,
        terms=cash_pay_debt(**stated),
        resolution=resolution,
        amount=GOLDEN_MEZZ_AMOUNT,
        scope=unit_scope(unit_id),
    )


def overlay(content: CapitalStructure) -> InvestmentStrategyOverlay:
    return InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=content)


def crash(unit_id: str) -> ScenarioOverride:
    """An exit cap so wide that the sale cannot repay what is senior to the
    mezzanine, which is how a claim goes unresolved."""

    return ScenarioOverride(
        unit_id=unit_id,
        target=ScenarioTarget.EXIT_CAP_RATE,
        operation=ScenarioOperation.SET,
        value=0.25,
    )


def cells(matrix: Any) -> dict[tuple[str, str], Any]:
    return {(cell.strategy_id, cell.scenario_id): cell for cell in matrix.cells}


def metric(cell: Any, name: PositionMetric) -> Any:
    return next(value for value in cell.metrics if value.metric is name)


@pytest.fixture
def matrix_deal(db: Path) -> tuple[Path, str, str]:
    """A Deal whose Base structure holds one mezzanine loan and the Common
    Equity marker, with three Strategies and three Scenarios over it."""

    deal = round_deal(db, name="Matrix deal")
    investment_id, _ = store.set_deal_capital_structure(
        deal.id,
        structure(mezz(deal.id), common_marker("common-a", scope=unit_scope(deal.id))),
        db_path=db,
    )
    assert investment_id is not None
    return db, investment_id, deal.id


# =============================================================================
# The golden 3 x 3
# =============================================================================


@pytest.fixture
def golden(matrix_deal: tuple[Path, str, str]) -> tuple[Path, str, str, str, str]:
    db, investment_id, deal_id = matrix_deal
    stretch = store.create_strategy(
        investment_id,
        name="Stretch mezz",
        root_overlays=(
            overlay(
                structure(
                    mezz(deal_id, rate=0.15),
                    common_marker("common-a", scope=unit_scope(deal_id)),
                )
            ),
        ),
        db_path=db,
    )
    inheriting = store.create_strategy(investment_id, name="Inherit", db_path=db)
    store.create_scenario(
        investment_id,
        name="Downside",
        overrides=(
            ScenarioOverride(
                unit_id=deal_id,
                target=ScenarioTarget.EXIT_CAP_RATE,
                operation=ScenarioOperation.ADD,
                value=0.005,
            ),
        ),
        db_path=db,
    )
    store.create_scenario(
        investment_id,
        name="Upside",
        overrides=(
            ScenarioOverride(
                unit_id=deal_id,
                target=ScenarioTarget.NOI_GROWTH,
                operation=ScenarioOperation.SET,
                value=0.03,
            ),
        ),
        db_path=db,
    )
    return db, investment_id, deal_id, stretch.strategy.strategy_id, inheriting.strategy.strategy_id


def test_the_matrix_is_three_by_three_over_the_claim_bearing_catalog(
    golden: tuple[Path, str, str, str, str],
) -> None:
    db, investment_id, _, stretch_id, inheriting_id = golden

    report = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db)
    matrix = report.matrix

    assert matrix.perspective is DecisionPerspective.POSITION
    assert matrix.position_id == "mezz-a" and matrix.is_common_equity_marker is False
    assert [row.strategy_id for row in matrix.strategies] == [BASE, stretch_id, inheriting_id]
    assert [column.name for column in matrix.scenarios] == ["Base Scenario", "Downside", "Upside"]
    assert len(matrix.cells) == 9
    assert [spec.metric for spec in matrix.metrics] == list(PositionMetric)[:11]
    assert matrix.omitted_metrics == ()


def test_every_cell_value_is_the_executors_own_result_field(
    golden: tuple[Path, str, str, str, str],
) -> None:
    """No figure is recomputed here: each is the P7.8A result the same variant
    produces on its own."""

    db, investment_id, _, stretch_id, _ = golden
    matrix = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix

    for strategy_id in (BASE, stretch_id):
        cell = cells(matrix)[(strategy_id, BASE)]
        analysis = analyze_structured_variant(investment_id, strategy_id, BASE, db_path=db)
        (position,) = analysis.result.positions
        assert cell.status is CellStatus.VALID
        assert cell.applicability is PositionApplicability.PRESENT
        assert metric(cell, PositionMetric.FUNDED_AMOUNT).value == position.funded_amount
        assert metric(cell, PositionMetric.IRR).value == position.irr
        assert metric(cell, PositionMetric.MOIC).value == position.moic
        assert metric(cell, PositionMetric.ATTACHMENT_LTP).value == position.attachment_ltv
        assert metric(cell, PositionMetric.LAST_DOLLAR_BASIS).value == position.last_dollar_basis
        assert cell.source_fingerprint == analysis.structured_source_fingerprint
        assert cell.project_source_fingerprint == analysis.project_source_fingerprint


def test_a_stretch_position_earns_more_and_attaches_no_differently(
    golden: tuple[Path, str, str, str, str],
) -> None:
    """The comparison a Position matrix exists for: the same position id, the
    same attachment, a different coupon."""

    db, investment_id, _, stretch_id, _ = golden
    matrix = cells(analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix)

    base = matrix[(BASE, BASE)]
    stretch = matrix[(stretch_id, BASE)]
    assert metric(stretch, PositionMetric.IRR).value > metric(base, PositionMetric.IRR).value
    assert metric(stretch, PositionMetric.ATTACHMENT_LTP).value == metric(
        base, PositionMetric.ATTACHMENT_LTP
    ).value


def test_delta_worst_case_and_range_are_computed_over_the_rows_scenarios(
    golden: tuple[Path, str, str, str, str],
) -> None:
    db, investment_id, _, _, _ = golden
    matrix = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix
    indexed = cells(matrix)

    base_cell = indexed[(BASE, BASE)]
    (base_delta,) = [delta for delta in base_cell.deltas if delta.metric is PositionMetric.IRR]
    assert base_delta.is_baseline is True and base_delta.value == 0.0

    figures = {entry.strategy_id: entry for entry in matrix.strategy_figures}[BASE]
    irr_worst = next(worst for worst in figures.worst_cases if worst.metric is PositionMetric.IRR)
    irr_range = next(spread for spread in figures.ranges if spread.metric is PositionMetric.IRR)
    row = [
        metric(indexed[(BASE, column.scenario_id)], PositionMetric.IRR).value
        for column in matrix.scenarios
    ]
    assert irr_worst.direction is MetricDirection.HIGHER_IS_BETTER
    assert irr_worst.value == min(row)
    assert irr_range.spread == max(row) - min(row)

    funded_worst = next(
        worst for worst in figures.worst_cases if worst.metric is PositionMetric.FUNDED_AMOUNT
    )
    assert funded_worst.direction is MetricDirection.LOWER_IS_BETTER
    assert funded_worst.value == GOLDEN_MEZZ_AMOUNT


# =============================================================================
# Not applicable to this perspective
# =============================================================================


def test_a_strategy_without_the_position_is_not_applicable_and_not_invalid(
    matrix_deal: tuple[Path, str, str],
) -> None:
    db, investment_id, deal_id = matrix_deal
    dropped = store.create_strategy(
        investment_id,
        name="No mezzanine",
        root_overlays=(overlay(structure(common_marker("common-a", scope=unit_scope(deal_id)))),),
        db_path=db,
    )
    strategy_id = dropped.strategy.strategy_id

    matrix = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix

    cell = cells(matrix)[(strategy_id, BASE)]
    assert cell.status is CellStatus.VALID
    assert cell.applicability is PositionApplicability.NOT_PRESENT
    assert cell.issues == ()
    value = metric(cell, PositionMetric.FUNDED_AMOUNT)
    assert value.value is None
    assert value.reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE
    assert value.message == "Not present in this Strategy's Capital Structure."
    # The Project variant is perfectly valid: only this perspective is empty.
    project = analyze_decision_matrix(investment_id, db_path=db).matrix
    project_cell = next(
        entry
        for entry in project.cells
        if (entry.strategy_id, entry.scenario_id) == (strategy_id, BASE)
    )
    assert project_cell.status is CellStatus.VALID


def test_a_row_missing_the_position_reports_no_worst_case_or_range(
    matrix_deal: tuple[Path, str, str],
) -> None:
    """A Worst Case over the Scenarios that do hold it would compare a position
    with its own absence."""

    db, investment_id, deal_id = matrix_deal
    dropped = store.create_strategy(
        investment_id,
        name="No mezzanine",
        root_overlays=(overlay(structure(common_marker("common-a", scope=unit_scope(deal_id)))),),
        db_path=db,
    )
    store.create_scenario(investment_id, name="Downside", overrides=(crash(deal_id),), db_path=db)

    matrix = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix

    figures = {entry.strategy_id: entry for entry in matrix.strategy_figures}
    worst = figures[dropped.strategy.strategy_id].worst_cases[0]
    assert worst.value is None
    assert worst.reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE


def test_an_unknown_position_has_no_perspective(matrix_deal: tuple[Path, str, str]) -> None:
    db, investment_id, _ = matrix_deal

    with pytest.raises(PositionPerspectiveNotFoundError):
        analyze_position_decision_matrix(investment_id, "nobody", db_path=db)


# =============================================================================
# Unresolved funding: a valid cell whose returns are N/A
# =============================================================================


def test_an_unresolved_scenario_keeps_the_cell_valid_and_the_structure_reported(
    db: Path,
) -> None:
    deal = round_deal(db, name="Matrix deal")
    investment_id, _ = store.set_deal_capital_structure(
        deal.id,
        structure(mezz(deal.id, resolution=ShortfallResolution.UNRESOLVED, maturity_month=60)),
        db_path=db,
    )
    assert investment_id is not None
    store.create_scenario(investment_id, name="Crash", overrides=(crash(deal.id),), db_path=db)

    matrix = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix

    indexed = cells(matrix)
    complete = indexed[(BASE, BASE)]
    starved = next(cell for (strategy, scenario), cell in indexed.items() if scenario != BASE)
    assert complete.position_status is PositionResultStatus.COMPLETE
    assert starved.status is CellStatus.VALID
    assert starved.applicability is PositionApplicability.PRESENT
    assert starved.position_status is PositionResultStatus.UNRESOLVED_FUNDING

    returns = metric(starved, PositionMetric.IRR)
    assert returns.value is None
    assert returns.reason is FigureReason.UNRESOLVED_FUNDING_REQUIREMENT
    assert metric(starved, PositionMetric.MOIC).value is None
    assert metric(starved, PositionMetric.PROFIT).value is None
    # Structural metrics are contractual: they stand whatever the cash did.
    assert metric(starved, PositionMetric.FUNDED_AMOUNT).value == GOLDEN_MEZZ_AMOUNT
    assert metric(starved, PositionMetric.ATTACHMENT_LTP).value == 0.6
    assert metric(starved, PositionMetric.LAST_DOLLAR_BASIS).value == 7_500_000.0


# =============================================================================
# The Common Equity perspective
# =============================================================================


def test_the_common_equity_marker_uses_its_own_catalog_and_the_structured_residual(
    matrix_deal: tuple[Path, str, str],
) -> None:
    """NS-1: these are the Common Equity figures after structured capital, never
    the project's levered returns, which still exist and still differ."""

    db, investment_id, _ = matrix_deal

    matrix = analyze_position_decision_matrix(investment_id, "common-a", db_path=db).matrix

    assert matrix.is_common_equity_marker is True
    assert [spec.metric for spec in matrix.metrics] == [
        PositionMetric.COMMON_EQUITY_IRR,
        PositionMetric.EQUITY_MULTIPLE,
        PositionMetric.TOTAL_EQUITY_INVESTED,
        PositionMetric.TOTAL_CASH_RETURNED,
        PositionMetric.TOTAL_PROFIT,
    ]
    cell = cells(matrix)[(BASE, BASE)]
    analysis = analyze_structured_variant(investment_id, BASE, BASE, db_path=db)
    common_equity = analysis.result.common_equity
    assert metric(cell, PositionMetric.EQUITY_MULTIPLE).value == common_equity.equity_multiple
    assert metric(cell, PositionMetric.TOTAL_PROFIT).value == common_equity.total_profit
    project = analyze_decision_matrix(investment_id, db_path=db).matrix
    project_cell = next(entry for entry in project.cells if entry.strategy_id == BASE)
    assert project_cell.results is not None
    assert common_equity.equity_multiple != project_cell.results.equity_multiple


# =============================================================================
# Horizons
# =============================================================================


def test_different_hold_periods_omit_the_horizon_dependent_metrics(
    matrix_deal: tuple[Path, str, str],
) -> None:
    db, investment_id, deal_id = matrix_deal
    store.create_strategy(
        investment_id,
        name="Long hold",
        overlays=(
            StrategyOverlay(
                unit_id=deal_id,
                domain=StrategyDomain.DISPOSITION,
                content=DispositionChoice(hold_period=7),
            ),
        ),
        db_path=db,
    )

    matrix = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix

    compared = [spec.metric for spec in matrix.metrics]
    omitted = {entry.metric for entry in matrix.omitted_metrics}
    assert omitted == {PositionMetric.MINIMUM_COVERAGE, PositionMetric.BALANCE_AT_MATURITY_OR_EXIT}
    assert all(entry.reason is OmissionReason.DIFFERENT_HOLD_PERIODS for entry in matrix.omitted_metrics)
    assert PositionMetric.IRR in compared and PositionMetric.HEADLINE_COVERAGE in compared
    assert PositionMetric.MINIMUM_COVERAGE not in compared
    assert matrix.hold_periods == (5, 7)


# =============================================================================
# Matrix identity
# =============================================================================


def test_the_position_matrix_fingerprint_is_its_own_and_the_project_matrixs_never_moves(
    matrix_deal: tuple[Path, str, str],
) -> None:
    db, investment_id, deal_id = matrix_deal
    project_before = analyze_decision_matrix(investment_id, db_path=db).matrix.matrix_fingerprint
    position_before = analyze_position_decision_matrix(
        investment_id, "mezz-a", db_path=db
    ).matrix.matrix_fingerprint

    store.set_base_capital_structure(
        investment_id,
        structure(mezz(deal_id, rate=0.14), common_marker("common-a", scope=unit_scope(deal_id))),
        db_path=db,
    )

    assert analyze_decision_matrix(investment_id, db_path=db).matrix.matrix_fingerprint == project_before
    assert (
        analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix.matrix_fingerprint
        != position_before
    )


def test_two_positions_over_the_same_variants_have_different_fingerprints(
    matrix_deal: tuple[Path, str, str],
) -> None:
    db, investment_id, _ = matrix_deal

    mezzanine = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix
    common = analyze_position_decision_matrix(investment_id, "common-a", db_path=db).matrix

    assert mezzanine.matrix_fingerprint is not None
    assert mezzanine.matrix_fingerprint != common.matrix_fingerprint


def test_renaming_a_position_moves_no_fingerprint(matrix_deal: tuple[Path, str, str]) -> None:
    """FP-1 end to end: a display name reaches no digest, so a rename never
    makes a matrix look stale."""

    db, investment_id, deal_id = matrix_deal
    before = analyze_position_decision_matrix(
        investment_id, "mezz-a", db_path=db
    ).matrix.matrix_fingerprint

    renamed = mezz(deal_id)
    store.set_base_capital_structure(
        investment_id,
        CapitalStructure(
            positions=(
                type(renamed)(
                    position_id=renamed.position_id,
                    name="Junior mortgage",
                    position_class=renamed.position_class,
                    priority=renamed.priority,
                    scope=renamed.scope,
                    funding=renamed.funding,
                    terms=renamed.terms,
                    shortfall_resolution=renamed.shortfall_resolution,
                ),
                common_marker("common-a", scope=unit_scope(deal_id)),
            )
        ),
        db_path=db,
    )

    after = analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix
    assert after.matrix_fingerprint == before
    assert after.position_name == "Junior mortgage"
