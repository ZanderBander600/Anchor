"""Phase 7 Gate P7.9 Stage 2 -- the ``PARTNER(partner_id)`` Decision Matrix.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 17.2 and
``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 14.1
(DC-2 to DC-7). The claims:

- **The ratified catalog**, each value one Stage 1 ``PartnerResult`` field,
  selected: contributions, distributions, IRR, MOIC, profit, distribution
  difference, Promote Earned and benchmark capital subordination.
- **Honest cells.** Promote Earned is not applicable for a non-participant; a
  Strategy with no Partnership, or without the partner, is not applicable; an
  unavailable Common Equity Cash Flow reports every figure N/A with the
  Partnership's reason; an invalid variant is one invalid cell; a zero-
  contribution partner's MOIC and IRR are N/A, never zero.
- **The unchanged P7.5 cross-cell semantics** -- Delta vs Base Scenario, Worst
  Case and Range -- with the absent-partner rule of P7.8B.
- **Its own identity.** The matrix fingerprint includes the partner id; the
  run is bracketed by a state token that includes every Partnership.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

import _p7_9_fixtures as f  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from _p7_9_stage_2_fixtures import (  # type: ignore[import-not-found]
    capital_overlay,
    no_partnership_overlay,
    partnership_overlay,
    renamed,
    structured_deal,
    unresolved_structure,
    with_partner,
)
from anchor.analysis.strategy import AcquisitionChoice, StrategyDomain, StrategyOverlay
from anchor.analysis.scenario import ScenarioOperation, ScenarioOverride, ScenarioTarget
from anchor.capital_structure import CapitalStructure
from anchor.decision.comparison import (
    PARTNER_METRIC_CATALOG,
    AxisMember,
    CellIssueSource,
    CellStatus,
    DecisionComparisonError,
    DecisionPerspective,
    FigureReason,
    MetricDirection,
    PartnerApplicability,
    PartnerCellInput,
    PartnerMetric,
    compare_partner_decision_matrix,
)
from anchor.deals import decision_matrix as matrix_module
from anchor.deals import partnership_variants as service
from anchor.deals import store
from anchor.deals.contracts import PartnerPerspectiveNotFoundError
from anchor.deals.decision_matrix import (
    DecisionMatrixConflictError,
    analyze_partner_decision_matrix,
)
from anchor.deals.partnership_variants import analyze_partnership_variant
from anchor.deals.structured_variants import StructuredRootKind
from anchor.engine.contracts import IrrStatus
from anchor.partnership import (
    PartnershipExecutionError,
    PartnershipExecutionIssue,
    PartnershipExecutionIssueCode,
    PartnershipStatus,
    PartnerRole,
)

BASE = "base"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def _scenario(db: Path, investment_id: str, unit_id: str) -> str:
    return store.create_scenario(
        investment_id,
        name="Downside",
        overrides=(
            ScenarioOverride(
                unit_id=unit_id,
                target=ScenarioTarget.EXIT_CAP_RATE,
                operation=ScenarioOperation.ADD,
                value=0.005,
            ),
        ),
        db_path=db,
    ).scenario.scenario_id


def _cell(report: Any, strategy_id: str, scenario_id: str) -> Any:
    return next(c for c in report.matrix.cells if (c.strategy_id, c.scenario_id) == (strategy_id, scenario_id))


def _metric(cell: Any, metric: PartnerMetric) -> Any:
    return next(value for value in cell.metrics if value.metric is metric)


def _figures(report: Any, strategy_id: str) -> Any:
    return next(figures for figures in report.matrix.strategy_figures if figures.strategy_id == strategy_id)


@pytest.fixture
def setup(db: Path) -> dict[str, Any]:
    """A hidden Deal with the golden mezzanine loan and the F1 terms, a Downside
    Scenario, and Strategies that inherit, replace, state none, starve the
    mezzanine loan, and carry an invalid bid."""

    deal, investment_id = structured_deal(db, f.f1_terms())
    downside = _scenario(db, investment_id, deal.id)
    inherit = store.create_strategy(investment_id, name="Inherit", db_path=db).strategy.strategy_id
    pari_passu = store.create_strategy(
        investment_id, name="Pari passu", root_overlays=(partnership_overlay(f.pari_passu()),), db_path=db
    ).strategy.strategy_id
    none = store.create_strategy(
        investment_id, name="No partnership", root_overlays=(no_partnership_overlay(),), db_path=db
    ).strategy.strategy_id
    starved = store.create_strategy(
        investment_id, name="Balloon", root_overlays=(capital_overlay(unresolved_structure(deal.id)),), db_path=db
    ).strategy.strategy_id
    invalid = store.create_strategy(
        investment_id,
        name="Bad bid",
        overlays=(
            StrategyOverlay(
                unit_id=deal.id,
                domain=StrategyDomain.ACQUISITION,
                content=AcquisitionChoice(purchase_price=-1.0, acquisition_cost_pct=0.02),
            ),
        ),
        db_path=db,
    ).strategy.strategy_id
    return {
        "deal": deal,
        "investment_id": investment_id,
        "downside": downside,
        "inherit": inherit,
        "pari_passu": pari_passu,
        "none": none,
        "starved": starved,
        "invalid": invalid,
    }


# =============================================================================
# The catalog
# =============================================================================


def test_the_catalog_is_exactly_the_ratified_partner_metrics() -> None:
    assert [spec.metric for spec in PARTNER_METRIC_CATALOG] == [
        PartnerMetric.CONTRIBUTIONS,
        PartnerMetric.DISTRIBUTIONS,
        PartnerMetric.IRR,
        PartnerMetric.MOIC,
        PartnerMetric.PROFIT,
        PartnerMetric.DISTRIBUTION_DIFFERENCE,
        PartnerMetric.PROMOTE_EARNED,
        PartnerMetric.BENCHMARK_CAPITAL_SUBORDINATION,
    ]
    labels = {spec.metric: spec.label for spec in PARTNER_METRIC_CATALOG}
    assert labels[PartnerMetric.PROMOTE_EARNED] == "Promote Earned"
    assert labels[PartnerMetric.IRR] == "Partner IRR"  # never the project's or Common Equity's (NS-1)
    assert "promote" not in labels[PartnerMetric.DISTRIBUTION_DIFFERENCE].lower()
    directions = {spec.metric: spec.direction for spec in PARTNER_METRIC_CATALOG}
    assert directions[PartnerMetric.CONTRIBUTIONS] is MetricDirection.LOWER_IS_BETTER
    assert directions[PartnerMetric.BENCHMARK_CAPITAL_SUBORDINATION] is MetricDirection.LOWER_IS_BETTER


def test_every_value_is_one_partner_result_field(setup: dict[str, Any], db: Path) -> None:
    investment_id = setup["investment_id"]

    report = analyze_partner_decision_matrix(investment_id, "gp", db_path=db)
    analysis = analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)
    assert analysis.result is not None and analysis.result.partners is not None
    gp = next(p for p in analysis.result.partners if p.partner_id == "gp")
    cell = _cell(report, BASE, BASE)

    assert report.matrix.perspective is DecisionPerspective.PARTNER
    assert report.partner.partner_id == "gp" and report.matrix.partner_name == "GP"
    assert (cell.partner_name, cell.partner_role) == ("GP", PartnerRole.GP)
    assert report.root_kind is StructuredRootKind.HIDDEN_UNIT
    assert cell.status is CellStatus.VALID and cell.applicability is PartnerApplicability.PRESENT
    assert cell.is_promote_participant is True
    assert cell.partnership_status is PartnershipStatus.COMPLETE
    assert {value.metric: value.value for value in cell.metrics} == {
        PartnerMetric.CONTRIBUTIONS: gp.total_contributions,
        PartnerMetric.DISTRIBUTIONS: gp.total_distributions,
        PartnerMetric.IRR: gp.irr,
        PartnerMetric.MOIC: gp.moic,
        PartnerMetric.PROFIT: gp.profit,
        PartnerMetric.DISTRIBUTION_DIFFERENCE: gp.distribution_difference,
        PartnerMetric.PROMOTE_EARNED: gp.promote_earned,
        PartnerMetric.BENCHMARK_CAPITAL_SUBORDINATION: gp.benchmark_capital_subordination,
    }
    # The cell carries the engine's own IRR status, whatever it is: under the
    # golden mezzanine loan this GP's series changes sign more than once.
    assert _metric(cell, PartnerMetric.IRR).irr_status is gp.irr_status
    assert gp.promote_earned is not None and gp.promote_earned > 0
    assert cell.source_fingerprint == analysis.partnership_source_fingerprint
    assert cell.structured_source_fingerprint == analysis.structured_source_fingerprint
    assert cell.project_source_fingerprint == analysis.project_source_fingerprint


# =============================================================================
# Honest cell states
# =============================================================================


def test_promote_earned_is_not_applicable_for_a_non_participant(setup: dict[str, Any], db: Path) -> None:
    report = analyze_partner_decision_matrix(setup["investment_id"], "lp", db_path=db)
    cell = _cell(report, BASE, BASE)

    promote = _metric(cell, PartnerMetric.PROMOTE_EARNED)
    assert cell.applicability is PartnerApplicability.PRESENT and cell.is_promote_participant is False
    assert promote.value is None
    assert promote.reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE
    assert promote.message == "Not a promote participant in this Strategy's Partnership."
    assert _metric(cell, PartnerMetric.PROFIT).value is not None
    delta = next(d for d in cell.deltas if d.metric is PartnerMetric.PROMOTE_EARNED)
    assert delta.value is None and delta.reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE
    worst = next(w for w in _figures(report, BASE).worst_cases if w.metric is PartnerMetric.PROMOTE_EARNED)
    assert worst.value is None and worst.reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE
    assert "promote participants" in (worst.message or "")


def test_a_participant_below_its_benchmark_reports_zero_promote(setup: dict[str, Any], db: Path) -> None:
    """Pari passu at the benchmark: the participant is measured, and its
    Promote Earned is a real 0.0 -- not N/A."""

    report = analyze_partner_decision_matrix(setup["investment_id"], "gp", db_path=db)
    promote = _metric(_cell(report, setup["pari_passu"], BASE), PartnerMetric.PROMOTE_EARNED)

    assert promote.value == 0.0 and promote.reason is None


def test_a_strategy_with_no_partnership_is_not_applicable(setup: dict[str, Any], db: Path) -> None:
    report = analyze_partner_decision_matrix(setup["investment_id"], "gp", db_path=db)
    cell = _cell(report, setup["none"], BASE)

    assert cell.status is CellStatus.VALID and cell.applicability is PartnerApplicability.NOT_PRESENT
    assert (cell.partner_name, cell.partner_role) == (None, None)
    assert cell.partnership_status is None and cell.partnership_source_fingerprint is None
    assert cell.source_fingerprint == cell.structured_source_fingerprint
    for value in cell.metrics:
        assert value.value is None and value.reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE
        assert value.message == "This Strategy has no Partnership."
    for figure in (*_figures(report, setup["none"]).worst_cases, *_figures(report, setup["none"]).ranges):
        assert figure.reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE
        expected = (
            "Not available: the selected partner is not in this Strategy's Partnership, or is not one "
            "of its promote participants."
            if figure.metric is PartnerMetric.PROMOTE_EARNED
            else "Not available: the selected partner is not in this Strategy's Partnership."
        )
        assert figure.message == expected


def test_a_partner_absent_from_a_strategys_partnership_is_not_applicable(setup: dict[str, Any], db: Path) -> None:
    investment_id = setup["investment_id"]
    other = store.create_strategy(
        investment_id, name="Class sponsors", root_overlays=(partnership_overlay(f.f12_terms()),), db_path=db
    ).strategy.strategy_id

    report = analyze_partner_decision_matrix(investment_id, "gp", db_path=db)
    cell = _cell(report, other, BASE)
    assert cell.applicability is PartnerApplicability.NOT_PRESENT
    assert cell.partnership_status is PartnershipStatus.COMPLETE
    assert {value.message for value in cell.metrics} == {"Not present in this Strategy's Partnership."}

    sponsor = analyze_partner_decision_matrix(investment_id, "g1", db_path=db)
    assert _cell(sponsor, other, BASE).applicability is PartnerApplicability.PRESENT
    assert _cell(sponsor, BASE, BASE).applicability is PartnerApplicability.NOT_PRESENT
    assert sponsor.partner.present_in_base is False


def test_an_unavailable_common_equity_reports_every_figure_na(setup: dict[str, Any], db: Path) -> None:
    report = analyze_partner_decision_matrix(setup["investment_id"], "gp", db_path=db)
    cell = _cell(report, setup["starved"], BASE)

    assert cell.status is CellStatus.VALID and cell.applicability is PartnerApplicability.PRESENT
    assert cell.partnership_status is PartnershipStatus.UNAVAILABLE
    assert cell.unavailable_reason is not None and cell.unavailable_message
    assert cell.is_promote_participant is None
    assert (cell.partner_name, cell.partner_role) == ("GP", PartnerRole.GP)
    for value in cell.metrics:
        assert value.value is None
        assert value.reason is FigureReason.UNRESOLVED_FUNDING_REQUIREMENT
        assert value.message == cell.unavailable_message
    assert cell.source_fingerprint is not None


def test_an_invalid_variant_is_one_invalid_cell(setup: dict[str, Any], db: Path) -> None:
    report = analyze_partner_decision_matrix(setup["investment_id"], "gp", db_path=db)
    cell = _cell(report, setup["invalid"], BASE)

    assert cell.status is CellStatus.INVALID and cell.applicability is PartnerApplicability.NOT_ANALYSED
    assert cell.issues and {issue.source for issue in cell.issues} == {CellIssueSource.STRATEGY}
    assert all(value.reason is FigureReason.INVALID_VARIANT for value in cell.metrics)
    assert report.matrix.matrix_fingerprint is None and report.matrix.matrix_fingerprint_reason
    assert _cell(report, BASE, BASE).status is CellStatus.VALID


def test_a_partnership_execution_refusal_is_an_invalid_partnership_cell(
    setup: dict[str, Any], db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = service.execute_partnership

    def refuse_pari_passu(partnership: Any, structured: Any) -> Any:
        if partnership == f.pari_passu():
            raise PartnershipExecutionError(
                (
                    PartnershipExecutionIssue(
                        code=PartnershipExecutionIssueCode.NO_CONTRIBUTIONS_FOR_PRO_RATA_SPLIT,
                        message="No contributions to divide by.",
                        tier_id="residual",
                        period=1,
                    ),
                )
            )
        return real(partnership, structured)

    monkeypatch.setattr(service, "execute_partnership", refuse_pari_passu)
    report = analyze_partner_decision_matrix(setup["investment_id"], "gp", db_path=db)
    cell = _cell(report, setup["pari_passu"], BASE)

    assert cell.status is CellStatus.INVALID
    (issue,) = cell.issues
    assert issue.source is CellIssueSource.PARTNERSHIP
    assert issue.code == "no_contributions_for_pro_rata_split"
    assert issue.field == "partnership.tiers[residual]"
    assert _cell(report, BASE, BASE).status is CellStatus.VALID


def test_a_zero_contribution_partner_has_no_moic_or_irr(db: Path) -> None:
    _, investment_id = structured_deal(db, f.f8_terms())

    report = analyze_partner_decision_matrix(investment_id, "sp", db_path=db)
    cell = _cell(report, BASE, BASE)

    moic = _metric(cell, PartnerMetric.MOIC)
    irr = _metric(cell, PartnerMetric.IRR)
    assert moic.value is None and moic.reason is FigureReason.NOT_REPORTED
    assert moic.message == "Partner MOIC is not reported: this partner made no contributions."
    assert irr.value is None and irr.reason is FigureReason.IRR_NOT_DEFINED
    assert irr.irr_status is not IrrStatus.DEFINED
    # The reason is written for the analyst: the typed status travels in
    # `irr_status`, and its internal token never reaches the message.
    assert irr.message is not None
    assert irr.message.startswith("Partner IRR is not reported because ")
    assert irr.irr_status.value not in irr.message
    assert _metric(cell, PartnerMetric.CONTRIBUTIONS).value == 0.0
    promote = _metric(cell, PartnerMetric.PROMOTE_EARNED)
    assert promote.value is not None and promote.value > 0


def test_an_unknown_partner_has_no_perspective(setup: dict[str, Any], db: Path) -> None:
    with pytest.raises(PartnerPerspectiveNotFoundError):
        analyze_partner_decision_matrix(setup["investment_id"], "nobody", db_path=db)
    _, other = structured_deal(db)
    with pytest.raises(PartnerPerspectiveNotFoundError):
        analyze_partner_decision_matrix(other, "gp", db_path=db)


# =============================================================================
# Cross-cell figures and holds
# =============================================================================


def test_delta_worst_case_and_range_are_the_p7_5_semantics(setup: dict[str, Any], db: Path) -> None:
    investment_id, downside = setup["investment_id"], setup["downside"]
    report = analyze_partner_decision_matrix(investment_id, "gp", db_path=db)
    base_cell, down_cell = _cell(report, BASE, BASE), _cell(report, BASE, downside)

    profit_base = _metric(base_cell, PartnerMetric.PROFIT).value
    profit_down = _metric(down_cell, PartnerMetric.PROFIT).value
    delta = next(d for d in down_cell.deltas if d.metric is PartnerMetric.PROFIT)
    assert profit_down < profit_base
    assert delta.value == profit_down - profit_base
    assert [s.scenario_id for s in delta.sources] == [BASE, downside]
    assert next(d for d in base_cell.deltas if d.metric is PartnerMetric.PROFIT).is_baseline

    worst = next(w for w in _figures(report, BASE).worst_cases if w.metric is PartnerMetric.PROFIT)
    spread = next(r for r in _figures(report, BASE).ranges if r.metric is PartnerMetric.PROFIT)
    assert (worst.value, worst.scenario_id) == (profit_down, downside)
    assert spread.spread == profit_base - profit_down
    contributions = next(w for w in _figures(report, BASE).worst_cases if w.metric is PartnerMetric.CONTRIBUTIONS)
    assert contributions.direction is MetricDirection.LOWER_IS_BETTER

    starved = next(w for w in _figures(report, setup["starved"]).worst_cases if w.metric is PartnerMetric.PROFIT)
    assert starved.value is None and starved.reason is FigureReason.SCENARIO_NOT_REPORTED


def test_different_holds_omit_distributions(db: Path) -> None:
    from anchor.analysis.strategy import DispositionChoice

    deal, investment_id = structured_deal(db, f.f1_terms())
    store.create_strategy(
        investment_id,
        name="Shorter hold",
        overlays=(
            StrategyOverlay(unit_id=deal.id, domain=StrategyDomain.DISPOSITION, content=DispositionChoice(hold_period=4)),
        ),
        root_overlays=(capital_overlay(CapitalStructure(positions=())),),
        db_path=db,
    )

    report = analyze_partner_decision_matrix(investment_id, "gp", db_path=db)

    assert len(report.matrix.hold_periods) == 2
    assert [omitted.metric for omitted in report.matrix.omitted_metrics] == [PartnerMetric.DISTRIBUTIONS]
    assert PartnerMetric.DISTRIBUTIONS not in {spec.metric for spec in report.matrix.metrics}


# =============================================================================
# Identity and coherence
# =============================================================================


def test_the_matrix_fingerprint_is_the_partners_own(db: Path) -> None:
    deal, investment_id = structured_deal(db, f.f1_terms())
    _scenario(db, investment_id, deal.id)

    gp = analyze_partner_decision_matrix(investment_id, "gp", db_path=db).matrix.matrix_fingerprint
    lp = analyze_partner_decision_matrix(investment_id, "lp", db_path=db).matrix.matrix_fingerprint
    again = analyze_partner_decision_matrix(investment_id, "gp", db_path=db).matrix.matrix_fingerprint
    position = matrix_module.analyze_position_decision_matrix(investment_id, "mezz", db_path=db).matrix.matrix_fingerprint

    assert gp and lp and gp != lp and gp == again and gp != position

    store.set_base_partnership(investment_id, renamed(f.f1_terms()), db_path=db)
    assert analyze_partner_decision_matrix(investment_id, "gp", db_path=db).matrix.matrix_fingerprint == gp
    store.set_base_partnership(investment_id, dataclasses.replace(f.f1_terms(), promote_participant_ids=()), db_path=db)
    assert analyze_partner_decision_matrix(investment_id, "gp", db_path=db).matrix.matrix_fingerprint != gp


def test_a_partnership_edited_mid_run_is_a_conflict(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())
    real = matrix_module.analyze_partnership_variant
    edited = {"done": False}

    def edit_then_analyse(*args: Any, **kwargs: Any) -> Any:
        if not edited["done"]:
            edited["done"] = True
            store.set_base_partnership(
                investment_id, dataclasses.replace(f.f1_terms(), promote_participant_ids=()), db_path=db
            )
        return real(*args, **kwargs)

    monkeypatch.setattr(matrix_module, "analyze_partnership_variant", edit_then_analyse)
    with pytest.raises(DecisionMatrixConflictError):
        analyze_partner_decision_matrix(investment_id, "gp", db_path=db)


def test_a_rename_mid_run_is_not_a_conflict(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())
    real = matrix_module.analyze_partnership_variant

    def rename_then_analyse(*args: Any, **kwargs: Any) -> Any:
        store.set_base_partnership(investment_id, renamed(f.f1_terms()), db_path=db)
        return real(*args, **kwargs)

    monkeypatch.setattr(matrix_module, "analyze_partnership_variant", rename_then_analyse)
    report = analyze_partner_decision_matrix(investment_id, "gp", db_path=db)
    assert report.partner.name == "GP"


def test_a_visible_investment_has_a_partner_matrix(db: Path) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)
    store.set_base_partnership(investment.id, f.f1_terms(), db_path=db)

    report = analyze_partner_decision_matrix(investment.id, "gp", db_path=db)

    assert report.root_kind is StructuredRootKind.VISIBLE_INVESTMENT
    assert report.unit_ids == tuple(sorted((first.id, second.id)))
    assert _cell(report, BASE, BASE).applicability is PartnerApplicability.PRESENT


# =============================================================================
# The comparison refuses an incoherent matrix
# =============================================================================

_AXES = {
    "strategies": (AxisMember(id=BASE, name="Base", is_base=True),),
    "scenarios": (AxisMember(id=BASE, name="Base", is_base=True),),
}


@pytest.mark.parametrize(
    "cell",
    [
        PartnerCellInput(strategy_id=BASE, scenario_id=BASE, applicability=PartnerApplicability.NOT_ANALYSED),
        PartnerCellInput(strategy_id=BASE, scenario_id=BASE, applicability=PartnerApplicability.NOT_PRESENT, hold_period=5),
        PartnerCellInput(
            strategy_id=BASE, scenario_id=BASE, applicability=PartnerApplicability.PRESENT,
            source_fingerprint="x", hold_period=5,
        ),
        PartnerCellInput(
            strategy_id=BASE, scenario_id=BASE, applicability=PartnerApplicability.NOT_PRESENT,
            source_fingerprint="x", hold_period=5, partner_name="GP", partner_role=PartnerRole.GP,
        ),
    ],
    ids=[
        "unanalysed-without-issues", "analysed-without-fingerprint", "present-without-result",
        "absent-with-presentation-fields",
    ],
)
def test_an_incoherent_cell_is_a_programming_error(cell: PartnerCellInput) -> None:
    with pytest.raises(DecisionComparisonError):
        compare_partner_decision_matrix(partner_id="gp", partner_name="GP", cells=[cell], **_AXES)


# =============================================================================
# One identity, many descriptions (P-8)
# =============================================================================


def test_one_partner_id_may_be_lp_gp_or_co_investor_in_different_strategies(db: Path) -> None:
    """``partner_id`` is the identity; the name and role are presentation each
    resolved Partnership states for itself. The matrix stays one perspective
    keyed by that id, and every applicable cell reports its own metadata."""

    _, investment_id = structured_deal(db, f.f1_terms())  # Base: gp is the GP
    as_lp = store.create_strategy(
        investment_id,
        name="GP as LP",
        root_overlays=(partnership_overlay(with_partner(f.f1_terms(), "gp", role=PartnerRole.LP, name="Sponsor LP")),),
        db_path=db,
    ).strategy.strategy_id
    as_co_investor = store.create_strategy(
        investment_id,
        name="GP as co-investor",
        root_overlays=(
            partnership_overlay(
                with_partner(f.f1_terms(), "gp", role=PartnerRole.CO_INVESTOR, name="Co-investor")
            ),
        ),
        db_path=db,
    ).strategy.strategy_id
    absent = store.create_strategy(
        investment_id, name="Other partners", root_overlays=(partnership_overlay(f.f12_terms()),), db_path=db
    ).strategy.strategy_id

    report = analyze_partner_decision_matrix(investment_id, "gp", db_path=db)

    assert report.partner.partner_id == "gp"
    assert report.matrix.partner_id == "gp" and report.matrix.partner_name == "GP"
    assert not hasattr(report.matrix, "role")
    described = {
        cell.strategy_id: (cell.partner_name, cell.partner_role)
        for cell in report.matrix.cells
        if cell.scenario_id == BASE
    }
    assert described[BASE] == ("GP", PartnerRole.GP)
    assert described[as_lp] == ("Sponsor LP", PartnerRole.LP)
    assert described[as_co_investor] == ("Co-investor", PartnerRole.CO_INVESTOR)
    assert described[absent] == (None, None)  # this Strategy states other partners

    # Every Strategy that holds the id reports its figures; only the Strategy
    # that does not hold it is not applicable.
    applicability = {cell.strategy_id: cell.applicability for cell in report.matrix.cells if cell.scenario_id == BASE}
    assert applicability[absent] is PartnerApplicability.NOT_PRESENT
    for strategy_id in (BASE, as_lp, as_co_investor):
        assert applicability[strategy_id] is PartnerApplicability.PRESENT
        cell = _cell(report, strategy_id, BASE)
        assert _metric(cell, PartnerMetric.PROFIT).value is not None
        assert _metric(cell, PartnerMetric.PROMOTE_EARNED).value is not None

    # A role is presentation: restating it moves no figure and no fingerprint.
    base_cell = _cell(report, BASE, BASE)
    lp_cell = _cell(report, as_lp, BASE)
    assert [value.value for value in lp_cell.metrics] == [value.value for value in base_cell.metrics]
    assert lp_cell.source_fingerprint == base_cell.source_fingerprint


def test_the_perspective_is_addressable_even_when_no_partnership_states_the_base_role(db: Path) -> None:
    """A partner only a Strategy states is still one perspective, named
    deterministically from the first Partnership that states it."""

    _, investment_id = structured_deal(db, f.f1_terms())
    store.create_strategy(
        investment_id,
        name="Sponsors",
        root_overlays=(partnership_overlay(f.f12_terms()),),
        db_path=db,
    )

    report = analyze_partner_decision_matrix(investment_id, "g1", db_path=db)

    assert report.partner.partner_id == "g1" and report.partner.present_in_base is False
    assert report.matrix.partner_name == "G1"
    present = [cell for cell in report.matrix.cells if cell.applicability is PartnerApplicability.PRESENT]
    assert present and {(cell.partner_name, cell.partner_role) for cell in present} == {("G1", PartnerRole.GP)}
