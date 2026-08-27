"""Tests for the Phase 8 deterministic break-even layer
(``anchor.analysis.break_even``).

Covers the core bounded threshold solver, each of the five standard POC
break-even questions, and ``build_standard_break_even_analysis``. Confirms
this layer never duplicates or algebraically rearranges a financial
formula: every candidate must go through ``analyze_acquisition``, and every
solved result is independently re-verified against it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from anchor.analysis import (
    BreakEvenDirection,
    BreakEvenStatus,
    BreakEvenType,
    InvalidBreakEvenBoundsError,
    InvalidBreakEvenTargetError,
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
    build_standard_break_even_analysis,
    solve_break_even_threshold,
    solve_max_exit_cap_rate,
    solve_max_interest_rate,
    solve_max_purchase_price,
    solve_min_current_noi,
    solve_min_noi_growth,
)
from anchor.analysis import break_even as break_even_module
from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition

GOLDEN_INPUTS = AcquisitionInputs(
    purchase_price=50_000_000.0,
    current_noi=2_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.055,
    ltv=0.65,
    interest_rate=0.0525,
    amortization=30,
)


def _evaluate(inputs: AcquisitionInputs, assumption: str, metric: str, value: float):
    """Independent re-evaluation helper for numerical QA: builds its own
    scenario and calls the authoritative ``analyze_acquisition`` directly,
    never trusting the solver's own bookkeeping."""

    field_values = {
        field_id: getattr(inputs, field_id)
        for field_id in (
            "purchase_price",
            "current_noi",
            "occupancy",
            "noi_growth",
            "hold_period",
            "exit_cap_rate",
            "ltv",
            "interest_rate",
            "amortization",
        )
    }
    field_values[assumption] = value
    scenario = AcquisitionInputs(**field_values)
    results = analyze_acquisition(scenario)
    return getattr(results, metric)


# =============================================================================
# Core solver: solve_break_even_threshold
# =============================================================================


def test_core_solver_does_not_mutate_original_inputs() -> None:
    original = GOLDEN_INPUTS

    solve_break_even_threshold(
        GOLDEN_INPUTS,
        assumption="purchase_price",
        metric="levered_irr",
        target=0.10,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=25_000_000.0,
        upper_bound=75_000_000.0,
    )

    assert GOLDEN_INPUTS is original
    assert GOLDEN_INPUTS.purchase_price == 50_000_000.0


def test_core_solver_whole_range_already_meets_target_returns_unfavorable_bound() -> None:
    """When even the least-favorable end of the range still clears the
    hurdle, the solver must not claim a tighter boundary than it searched --
    it returns the extreme (unfavorable) bound itself."""

    value, metric_value, status = solve_break_even_threshold(
        GOLDEN_INPUTS,
        assumption="purchase_price",
        metric="levered_irr",
        target=-0.50,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=25_000_000.0,
        upper_bound=75_000_000.0,
    )

    assert status is BreakEvenStatus.SOLVED
    assert value == 75_000_000.0
    assert metric_value is not None


def test_core_solver_finds_boundary_between_two_candidates_maximum_type() -> None:
    value, metric_value, status = solve_break_even_threshold(
        GOLDEN_INPUTS,
        assumption="purchase_price",
        metric="levered_irr",
        target=0.10,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=25_000_000.0,
        upper_bound=75_000_000.0,
    )

    assert status is BreakEvenStatus.SOLVED
    assert 25_000_000.0 < value < 75_000_000.0
    assert metric_value == pytest.approx(0.10, abs=1e-3)

    # Independent re-verification: the solved value must actually clear the
    # hurdle, and a step to the unfavorable side must not.
    solved_metric = _evaluate(GOLDEN_INPUTS, "purchase_price", "levered_irr", value)
    assert solved_metric >= 0.10 - 1e-3
    beyond_metric = _evaluate(
        GOLDEN_INPUTS, "purchase_price", "levered_irr", value + 10_000.0
    )
    assert beyond_metric < 0.10


def test_core_solver_finds_boundary_between_two_candidates_minimum_type() -> None:
    value, metric_value, status = solve_break_even_threshold(
        GOLDEN_INPUTS,
        assumption="noi_growth",
        metric="levered_irr",
        target=0.10,
        direction=BreakEvenDirection.MINIMUM,
        lower_bound=-0.07,
        upper_bound=0.13,
    )

    assert status is BreakEvenStatus.SOLVED
    assert -0.07 < value < 0.13
    assert metric_value == pytest.approx(0.10, abs=1e-3)

    solved_metric = _evaluate(GOLDEN_INPUTS, "noi_growth", "levered_irr", value)
    assert solved_metric >= 0.10 - 1e-3
    below_metric = _evaluate(GOLDEN_INPUTS, "noi_growth", "levered_irr", value - 0.0005)
    assert below_metric < 0.10


def test_core_solver_none_metric_candidate_fails_hurdle() -> None:
    """With zero leverage, ``headline_dscr`` is ``None`` at every candidate
    -- the search must report no solution, never fabricate a pass."""

    zero_leverage_inputs = AcquisitionInputs(
        purchase_price=GOLDEN_INPUTS.purchase_price,
        current_noi=GOLDEN_INPUTS.current_noi,
        occupancy=GOLDEN_INPUTS.occupancy,
        noi_growth=GOLDEN_INPUTS.noi_growth,
        hold_period=GOLDEN_INPUTS.hold_period,
        exit_cap_rate=GOLDEN_INPUTS.exit_cap_rate,
        ltv=0.0,
        interest_rate=GOLDEN_INPUTS.interest_rate,
        amortization=GOLDEN_INPUTS.amortization,
    )

    value, metric_value, status = solve_break_even_threshold(
        zero_leverage_inputs,
        assumption="interest_rate",
        metric="headline_dscr",
        target=1.20,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=0.0,
        upper_bound=0.20,
    )

    assert status is BreakEvenStatus.NO_SOLUTION_IN_RANGE
    assert value is None
    assert metric_value is None


def test_core_solver_no_solution_in_range() -> None:
    value, metric_value, status = solve_break_even_threshold(
        GOLDEN_INPUTS,
        assumption="purchase_price",
        metric="levered_irr",
        target=0.90,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=25_000_000.0,
        upper_bound=75_000_000.0,
    )

    assert status is BreakEvenStatus.NO_SOLUTION_IN_RANGE
    assert value is None
    assert metric_value is None


def test_core_solver_invalid_lower_bound_raises() -> None:
    with pytest.raises(InvalidBreakEvenBoundsError):
        solve_break_even_threshold(
            GOLDEN_INPUTS,
            assumption="purchase_price",
            metric="levered_irr",
            target=0.10,
            direction=BreakEvenDirection.MAXIMUM,
            lower_bound=-1_000.0,
            upper_bound=75_000_000.0,
        )


def test_core_solver_invalid_upper_bound_raises() -> None:
    with pytest.raises(InvalidBreakEvenBoundsError):
        solve_break_even_threshold(
            GOLDEN_INPUTS,
            assumption="ltv",
            metric="levered_irr",
            target=0.10,
            direction=BreakEvenDirection.MAXIMUM,
            lower_bound=0.5,
            upper_bound=1.5,
        )


def test_core_solver_lower_bound_not_less_than_upper_bound_raises() -> None:
    with pytest.raises(InvalidBreakEvenBoundsError):
        solve_break_even_threshold(
            GOLDEN_INPUTS,
            assumption="purchase_price",
            metric="levered_irr",
            target=0.10,
            direction=BreakEvenDirection.MAXIMUM,
            lower_bound=75_000_000.0,
            upper_bound=25_000_000.0,
        )


def test_core_solver_is_deterministic_across_repeated_calls() -> None:
    first = solve_break_even_threshold(
        GOLDEN_INPUTS,
        assumption="exit_cap_rate",
        metric="levered_irr",
        target=0.10,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=0.025,
        upper_bound=0.105,
    )
    second = solve_break_even_threshold(
        GOLDEN_INPUTS,
        assumption="exit_cap_rate",
        metric="levered_irr",
        target=0.10,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=0.025,
        upper_bound=0.105,
    )

    assert first == second


def test_core_solver_candidates_use_shared_validation() -> None:
    """An out-of-domain lower bound must be rejected by the same
    ``validate_acquisition_inputs`` domain rules used everywhere else, not a
    duplicated check -- surfaced here as ``InvalidBreakEvenBoundsError``."""

    with pytest.raises(InvalidBreakEvenBoundsError, match="greater than 0"):
        solve_break_even_threshold(
            GOLDEN_INPUTS,
            assumption="exit_cap_rate",
            metric="levered_irr",
            target=0.10,
            direction=BreakEvenDirection.MAXIMUM,
            lower_bound=-0.01,
            upper_bound=0.10,
        )


def test_core_solver_analyze_acquisition_is_authoritative() -> None:
    with patch.object(
        break_even_module, "analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        solve_break_even_threshold(
            GOLDEN_INPUTS,
            assumption="purchase_price",
            metric="levered_irr",
            target=0.10,
            direction=BreakEvenDirection.MAXIMUM,
            lower_bound=25_000_000.0,
            upper_bound=75_000_000.0,
        )

    # At minimum, both endpoints must have been evaluated through the
    # authoritative engine entry point.
    assert mock_analyze.call_count >= 2


# =============================================================================
# Maximum Purchase Price
# =============================================================================


def test_max_purchase_price_solves_for_default_target() -> None:
    result = solve_max_purchase_price(GOLDEN_INPUTS, target_levered_irr=0.10)

    assert result.break_even_type is BreakEvenType.MAX_PURCHASE_PRICE
    assert result.assumption == "purchase_price"
    assert result.metric == "levered_irr"
    assert result.status is BreakEvenStatus.SOLVED
    assert result.baseline_assumption_value == 50_000_000.0
    assert result.solved_assumption_value < 50_000_000.0
    assert result.solved_metric_value == pytest.approx(0.10, abs=1e-3)


def test_max_purchase_price_step_beyond_threshold_fails_target() -> None:
    result = solve_max_purchase_price(GOLDEN_INPUTS, target_levered_irr=0.10)

    beyond = _evaluate(
        GOLDEN_INPUTS,
        "purchase_price",
        "levered_irr",
        result.solved_assumption_value + 5_000.0,
    )
    assert beyond < 0.10


def test_max_purchase_price_lower_target_yields_higher_price() -> None:
    low_hurdle = solve_max_purchase_price(GOLDEN_INPUTS, target_levered_irr=0.08)
    high_hurdle = solve_max_purchase_price(GOLDEN_INPUTS, target_levered_irr=0.12)

    assert low_hurdle.status is BreakEvenStatus.SOLVED
    assert high_hurdle.status is BreakEvenStatus.SOLVED
    assert low_hurdle.solved_assumption_value > high_hurdle.solved_assumption_value


def test_max_purchase_price_no_solution_in_tested_range() -> None:
    result = solve_max_purchase_price(GOLDEN_INPUTS, target_levered_irr=0.90)

    assert result.status is BreakEvenStatus.NO_SOLUTION_IN_RANGE
    assert result.solved_assumption_value is None
    assert result.solved_metric_value is None
    assert result.lower_search_bound == 25_000_000.0
    assert result.upper_search_bound == 75_000_000.0


# =============================================================================
# Maximum Exit Cap Rate
# =============================================================================


def test_max_exit_cap_rate_solves_for_default_target() -> None:
    result = solve_max_exit_cap_rate(GOLDEN_INPUTS, target_levered_irr=0.10)

    assert result.break_even_type is BreakEvenType.MAX_EXIT_CAP_RATE
    assert result.assumption == "exit_cap_rate"
    assert result.status is BreakEvenStatus.SOLVED
    assert result.solved_metric_value == pytest.approx(0.10, abs=1e-3)


def test_max_exit_cap_rate_step_beyond_threshold_fails_target() -> None:
    result = solve_max_exit_cap_rate(GOLDEN_INPUTS, target_levered_irr=0.10)

    beyond = _evaluate(
        GOLDEN_INPUTS,
        "exit_cap_rate",
        "levered_irr",
        result.solved_assumption_value + 0.0005,
    )
    assert beyond < 0.10


def test_max_exit_cap_rate_lower_target_yields_higher_cap() -> None:
    low_hurdle = solve_max_exit_cap_rate(GOLDEN_INPUTS, target_levered_irr=0.08)
    high_hurdle = solve_max_exit_cap_rate(GOLDEN_INPUTS, target_levered_irr=0.12)

    assert low_hurdle.solved_assumption_value > high_hurdle.solved_assumption_value


def test_max_exit_cap_rate_no_solution_in_tested_range() -> None:
    result = solve_max_exit_cap_rate(GOLDEN_INPUTS, target_levered_irr=0.90)

    assert result.status is BreakEvenStatus.NO_SOLUTION_IN_RANGE


# =============================================================================
# Minimum NOI Growth
# =============================================================================


def test_min_noi_growth_solves_for_default_target() -> None:
    result = solve_min_noi_growth(GOLDEN_INPUTS, target_levered_irr=0.10)

    assert result.break_even_type is BreakEvenType.MIN_NOI_GROWTH
    assert result.assumption == "noi_growth"
    assert result.status is BreakEvenStatus.SOLVED
    assert result.solved_assumption_value > GOLDEN_INPUTS.noi_growth
    assert result.solved_metric_value == pytest.approx(0.10, abs=1e-3)


def test_min_noi_growth_step_below_threshold_fails_target() -> None:
    result = solve_min_noi_growth(GOLDEN_INPUTS, target_levered_irr=0.10)

    below = _evaluate(
        GOLDEN_INPUTS,
        "noi_growth",
        "levered_irr",
        result.solved_assumption_value - 0.0005,
    )
    assert below < 0.10


def test_min_noi_growth_higher_target_requires_more_growth() -> None:
    low_hurdle = solve_min_noi_growth(GOLDEN_INPUTS, target_levered_irr=0.08)
    high_hurdle = solve_min_noi_growth(GOLDEN_INPUTS, target_levered_irr=0.12)

    assert low_hurdle.solved_assumption_value < high_hurdle.solved_assumption_value


def test_min_noi_growth_no_solution_in_tested_range() -> None:
    result = solve_min_noi_growth(GOLDEN_INPUTS, target_levered_irr=0.90)

    assert result.status is BreakEvenStatus.NO_SOLUTION_IN_RANGE


# =============================================================================
# Maximum Interest Rate (DSCR)
# =============================================================================


def test_max_interest_rate_solves_for_default_target() -> None:
    result = solve_max_interest_rate(GOLDEN_INPUTS, target_headline_dscr=1.20)

    assert result.break_even_type is BreakEvenType.MAX_INTEREST_RATE
    assert result.assumption == "interest_rate"
    assert result.metric == "headline_dscr"
    assert result.status is BreakEvenStatus.SOLVED
    assert result.solved_metric_value == pytest.approx(1.20, abs=1e-3)


def test_max_interest_rate_step_beyond_threshold_fails_target() -> None:
    result = solve_max_interest_rate(GOLDEN_INPUTS, target_headline_dscr=1.20)

    beyond = _evaluate(
        GOLDEN_INPUTS,
        "interest_rate",
        "headline_dscr",
        result.solved_assumption_value + 0.0005,
    )
    assert beyond < 1.20


def test_max_interest_rate_lower_dscr_target_yields_higher_rate() -> None:
    low_hurdle = solve_max_interest_rate(GOLDEN_INPUTS, target_headline_dscr=1.10)
    high_hurdle = solve_max_interest_rate(GOLDEN_INPUTS, target_headline_dscr=1.30)

    assert low_hurdle.solved_assumption_value > high_hurdle.solved_assumption_value


def test_max_interest_rate_no_solution_in_tested_range() -> None:
    result = solve_max_interest_rate(GOLDEN_INPUTS, target_headline_dscr=5.0)

    assert result.status is BreakEvenStatus.NO_SOLUTION_IN_RANGE


# =============================================================================
# Minimum Current NOI (DSCR)
# =============================================================================


def test_min_current_noi_solves_for_default_target() -> None:
    result = solve_min_current_noi(GOLDEN_INPUTS, target_headline_dscr=1.20)

    assert result.break_even_type is BreakEvenType.MIN_CURRENT_NOI
    assert result.assumption == "current_noi"
    assert result.metric == "headline_dscr"
    assert result.status is BreakEvenStatus.SOLVED
    assert result.solved_assumption_value > GOLDEN_INPUTS.current_noi
    assert result.solved_metric_value == pytest.approx(1.20, abs=1e-3)


def test_min_current_noi_step_below_threshold_fails_target() -> None:
    result = solve_min_current_noi(GOLDEN_INPUTS, target_headline_dscr=1.20)

    below = _evaluate(
        GOLDEN_INPUTS,
        "current_noi",
        "headline_dscr",
        result.solved_assumption_value - 150.0,
    )
    assert below < 1.20


def test_min_current_noi_higher_dscr_target_requires_more_noi() -> None:
    low_hurdle = solve_min_current_noi(GOLDEN_INPUTS, target_headline_dscr=1.10)
    high_hurdle = solve_min_current_noi(GOLDEN_INPUTS, target_headline_dscr=1.30)

    assert low_hurdle.solved_assumption_value < high_hurdle.solved_assumption_value


def test_min_current_noi_no_solution_in_tested_range() -> None:
    result = solve_min_current_noi(GOLDEN_INPUTS, target_headline_dscr=50.0)

    assert result.status is BreakEvenStatus.NO_SOLUTION_IN_RANGE


# =============================================================================
# Equity Multiple return hurdle
#
# Numerical QA (per the Phase 8 Equity Multiple extension): for the normal
# POC search ranges, increasing purchase price and increasing exit cap must
# each *weaken* Equity Multiple, and increasing NOI growth must *improve* it
# -- the same monotonicity the existing Levered IRR break-even questions
# already rely on. These tests make that assumption explicit as a
# regression, independently of the solver's own bookkeeping.
# =============================================================================


def test_equity_multiple_weakens_as_purchase_price_increases() -> None:
    lower = _evaluate(GOLDEN_INPUTS, "purchase_price", "equity_multiple", 40_000_000.0)
    higher = _evaluate(GOLDEN_INPUTS, "purchase_price", "equity_multiple", 60_000_000.0)

    assert lower is not None and higher is not None
    assert higher < lower


def test_equity_multiple_weakens_as_exit_cap_rate_increases() -> None:
    lower = _evaluate(GOLDEN_INPUTS, "exit_cap_rate", "equity_multiple", 0.045)
    higher = _evaluate(GOLDEN_INPUTS, "exit_cap_rate", "equity_multiple", 0.075)

    assert lower is not None and higher is not None
    assert higher < lower


def test_equity_multiple_improves_as_noi_growth_increases() -> None:
    lower = _evaluate(GOLDEN_INPUTS, "noi_growth", "equity_multiple", -0.02)
    higher = _evaluate(GOLDEN_INPUTS, "noi_growth", "equity_multiple", 0.08)

    assert lower is not None and higher is not None
    assert higher > lower


def test_max_purchase_price_solves_for_equity_multiple_target() -> None:
    result = solve_max_purchase_price(GOLDEN_INPUTS, target_equity_multiple=1.50)

    assert result.break_even_type is BreakEvenType.MAX_PURCHASE_PRICE
    assert result.assumption == "purchase_price"
    assert result.metric == "equity_multiple"
    assert result.status is BreakEvenStatus.SOLVED
    assert result.solved_assumption_value < 50_000_000.0
    assert result.solved_metric_value == pytest.approx(1.50, abs=1e-3)

    solved_metric = _evaluate(
        GOLDEN_INPUTS, "purchase_price", "equity_multiple", result.solved_assumption_value
    )
    assert solved_metric >= 1.50 - 1e-3
    beyond_metric = _evaluate(
        GOLDEN_INPUTS, "purchase_price", "equity_multiple", result.solved_assumption_value + 10_000.0
    )
    assert beyond_metric < 1.50


def test_max_exit_cap_rate_solves_for_equity_multiple_target() -> None:
    result = solve_max_exit_cap_rate(GOLDEN_INPUTS, target_equity_multiple=1.50)

    assert result.break_even_type is BreakEvenType.MAX_EXIT_CAP_RATE
    assert result.metric == "equity_multiple"
    assert result.status is BreakEvenStatus.SOLVED
    assert result.solved_metric_value == pytest.approx(1.50, abs=1e-2)


def test_min_noi_growth_solves_for_equity_multiple_target() -> None:
    result = solve_min_noi_growth(GOLDEN_INPUTS, target_equity_multiple=1.50)

    assert result.break_even_type is BreakEvenType.MIN_NOI_GROWTH
    assert result.metric == "equity_multiple"
    assert result.status is BreakEvenStatus.SOLVED
    assert result.solved_metric_value == pytest.approx(1.50, abs=1e-2)


def test_max_purchase_price_equity_multiple_no_solution_in_tested_range() -> None:
    result = solve_max_purchase_price(GOLDEN_INPUTS, target_equity_multiple=10.0)

    assert result.status is BreakEvenStatus.NO_SOLUTION_IN_RANGE
    assert result.solved_assumption_value is None
    assert result.solved_metric_value is None


def test_max_purchase_price_higher_equity_multiple_target_yields_lower_price() -> None:
    low_hurdle = solve_max_purchase_price(GOLDEN_INPUTS, target_equity_multiple=1.30)
    high_hurdle = solve_max_purchase_price(GOLDEN_INPUTS, target_equity_multiple=1.70)

    assert low_hurdle.status is BreakEvenStatus.SOLVED
    assert high_hurdle.status is BreakEvenStatus.SOLVED
    assert low_hurdle.solved_assumption_value > high_hurdle.solved_assumption_value


def test_return_hurdle_functions_require_exactly_one_target() -> None:
    with pytest.raises(InvalidBreakEvenTargetError):
        solve_max_purchase_price(GOLDEN_INPUTS)

    with pytest.raises(InvalidBreakEvenTargetError):
        solve_max_purchase_price(
            GOLDEN_INPUTS, target_levered_irr=0.10, target_equity_multiple=1.50
        )


def test_invalid_target_equity_multiple_raises() -> None:
    with pytest.raises(InvalidBreakEvenTargetError):
        solve_max_purchase_price(GOLDEN_INPUTS, target_equity_multiple=0.0)


def test_none_equity_multiple_candidate_fails_hurdle() -> None:
    """When the levered cash-flow series has no negative total (zero equity
    invested), ``equity_multiple`` is ``None`` at every candidate -- the
    search must report no solution, never fabricate a pass. Mirrors the
    existing zero-leverage ``headline_dscr`` regression."""

    zero_purchase_price_inputs = AcquisitionInputs(
        purchase_price=1.0,
        current_noi=GOLDEN_INPUTS.current_noi,
        occupancy=GOLDEN_INPUTS.occupancy,
        noi_growth=GOLDEN_INPUTS.noi_growth,
        hold_period=GOLDEN_INPUTS.hold_period,
        exit_cap_rate=GOLDEN_INPUTS.exit_cap_rate,
        ltv=1.0,
        interest_rate=0.0,
        amortization=GOLDEN_INPUTS.amortization,
    )

    value, metric_value, status = solve_break_even_threshold(
        zero_purchase_price_inputs,
        assumption="noi_growth",
        metric="equity_multiple",
        target=1.50,
        direction=BreakEvenDirection.MINIMUM,
        lower_bound=-0.10,
        upper_bound=0.10,
    )

    assert status is BreakEvenStatus.NO_SOLUTION_IN_RANGE
    assert value is None
    assert metric_value is None


# =============================================================================
# Standard break-even analysis -- Equity Multiple return hurdle
# =============================================================================


def test_standard_analysis_defaults_to_levered_irr_return_hurdle() -> None:
    analysis = build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
    )

    assert analysis.max_purchase_price.metric == "levered_irr"
    assert analysis.max_exit_cap_rate.metric == "levered_irr"
    assert analysis.min_noi_growth.metric == "levered_irr"


def test_standard_analysis_equity_multiple_return_hurdle_selects_metric() -> None:
    analysis = build_standard_break_even_analysis(
        GOLDEN_INPUTS,
        target_levered_irr=0.10,
        target_headline_dscr=1.20,
        target_equity_multiple=1.50,
        return_hurdle_metric=ReturnHurdleMetric.EQUITY_MULTIPLE,
    )

    assert analysis.max_purchase_price.metric == "equity_multiple"
    assert analysis.max_exit_cap_rate.metric == "equity_multiple"
    assert analysis.min_noi_growth.metric == "equity_multiple"
    assert analysis.max_purchase_price.target_metric_value == 1.50


def test_standard_analysis_equity_multiple_return_hurdle_leaves_dscr_questions_unchanged() -> None:
    irr_analysis = build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
    )
    em_analysis = build_standard_break_even_analysis(
        GOLDEN_INPUTS,
        target_levered_irr=0.10,
        target_headline_dscr=1.20,
        target_equity_multiple=1.50,
        return_hurdle_metric=ReturnHurdleMetric.EQUITY_MULTIPLE,
    )

    assert irr_analysis.max_interest_rate == em_analysis.max_interest_rate
    assert irr_analysis.min_current_noi == em_analysis.min_current_noi


def test_standard_analysis_equity_multiple_without_target_raises() -> None:
    with pytest.raises(InvalidBreakEvenTargetError):
        build_standard_break_even_analysis(
            GOLDEN_INPUTS,
            target_levered_irr=0.10,
            target_headline_dscr=1.20,
            return_hurdle_metric=ReturnHurdleMetric.EQUITY_MULTIPLE,
        )


# =============================================================================
# Target validation
# =============================================================================


def test_invalid_target_levered_irr_raises() -> None:
    with pytest.raises(InvalidBreakEvenTargetError):
        solve_max_purchase_price(GOLDEN_INPUTS, target_levered_irr=-1.0)


def test_invalid_target_headline_dscr_raises() -> None:
    with pytest.raises(InvalidBreakEvenTargetError):
        solve_max_interest_rate(GOLDEN_INPUTS, target_headline_dscr=0.0)


# =============================================================================
# Standard break-even analysis
# =============================================================================


def test_standard_analysis_produces_exactly_five_results() -> None:
    analysis = build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
    )

    assert isinstance(analysis, StandardBreakEvenAnalysis)
    fields = (
        analysis.max_purchase_price,
        analysis.max_exit_cap_rate,
        analysis.min_noi_growth,
        analysis.max_interest_rate,
        analysis.min_current_noi,
    )
    assert len(fields) == 5


def test_standard_analysis_break_even_types_are_correct() -> None:
    analysis = build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
    )

    assert analysis.max_purchase_price.break_even_type is BreakEvenType.MAX_PURCHASE_PRICE
    assert analysis.max_exit_cap_rate.break_even_type is BreakEvenType.MAX_EXIT_CAP_RATE
    assert analysis.min_noi_growth.break_even_type is BreakEvenType.MIN_NOI_GROWTH
    assert analysis.max_interest_rate.break_even_type is BreakEvenType.MAX_INTEREST_RATE
    assert analysis.min_current_noi.break_even_type is BreakEvenType.MIN_CURRENT_NOI


def test_standard_analysis_targets_are_correct() -> None:
    analysis = build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.09, target_headline_dscr=1.25
    )

    assert analysis.max_purchase_price.target_metric_value == 0.09
    assert analysis.max_exit_cap_rate.target_metric_value == 0.09
    assert analysis.min_noi_growth.target_metric_value == 0.09
    assert analysis.max_interest_rate.target_metric_value == 1.25
    assert analysis.min_current_noi.target_metric_value == 1.25


def test_standard_analysis_bounds_match_documented_defaults() -> None:
    analysis = build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
    )

    assert analysis.max_purchase_price.lower_search_bound == 25_000_000.0
    assert analysis.max_purchase_price.upper_search_bound == 75_000_000.0

    assert analysis.max_exit_cap_rate.lower_search_bound == pytest.approx(0.025)
    assert analysis.max_exit_cap_rate.upper_search_bound == pytest.approx(0.105)

    assert analysis.min_noi_growth.lower_search_bound == pytest.approx(-0.07)
    assert analysis.min_noi_growth.upper_search_bound == pytest.approx(0.13)

    assert analysis.max_interest_rate.lower_search_bound == 0.0
    assert analysis.max_interest_rate.upper_search_bound == pytest.approx(0.20)

    assert analysis.min_current_noi.lower_search_bound == 1_250_000.0
    assert analysis.min_current_noi.upper_search_bound == 3_750_000.0


def test_standard_analysis_is_deterministic() -> None:
    first = build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
    )
    second = build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
    )

    assert first == second


def test_standard_analysis_does_not_mutate_base_inputs() -> None:
    original = GOLDEN_INPUTS

    build_standard_break_even_analysis(
        GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
    )

    assert GOLDEN_INPUTS is original
    assert GOLDEN_INPUTS.purchase_price == 50_000_000.0
    assert GOLDEN_INPUTS.exit_cap_rate == 0.055
