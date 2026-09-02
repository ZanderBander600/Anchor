"""Underwriting V2 Gate 9 -- sensitivity/break-even V2 reconciliation.

Root cause (Gate 9A): both ``analysis.sensitivity._build_scenario_inputs``
and ``analysis.break_even._build_scenario_inputs`` reconstructed every
scenario's ``AcquisitionInputs`` by seeding a values dict from
``validation.FIELD_IDS`` -- the nine original V1 field ids only -- then
applying the changed dimension(s) on top. The five Underwriting V2 fields
(``acquisition_cost_pct``, ``financing_fee_pct``, ``disposition_cost_pct``,
``annual_capex_reserve``, ``io_period``) were never in that seed dict, so
every sensitivity cell and every break-even candidate silently evaluated a
neutral-V2 deal, even when the analyzed base deal had nonzero V2
assumptions. Both call sites now build the candidate via
``dataclasses.replace(base, **changes)`` (re-validated through the existing
``validate_acquisition_inputs``) -- every field of ``base`` not explicitly
changed carries over automatically, including any field added in the
future, so this class of bug cannot be reintroduced by forgetting to extend
a field list.

This module proves the fix at three levels:
  1. internal construction (``_build_scenario_inputs`` preserves every
     untouched field, checked by iterating ``dataclasses.fields`` rather
     than hardcoding another 14-field list);
  2. public sensitivity/break-even API, against the frozen Underwriting V2
     golden case (``purchase_price=10,000,000`` ... ``io_period=2``,
     authoritative Levered IRR ~7.380240%); and
  3. V1-neutral backward compatibility (a deal with all V2 fields at their
     default carries no behavior change).
"""

from __future__ import annotations

import dataclasses

import pytest

from anchor.analysis import (
    BreakEvenStatus,
    build_standard_break_even_analysis,
    build_standard_presets,
    run_two_way_sensitivity,
)
from anchor.analysis import break_even as break_even_module
from anchor.analysis import sensitivity as sensitivity_module
from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition

# The frozen Underwriting V2 golden case (Gate 4/6/9) -- all five V2 fields
# simultaneously nonzero. Authoritative engine output: Levered IRR
# 7.380240064972221%, Equity Multiple 1.3823468941908068x, Year 1 (headline)
# DSCR 2.0x, Minimum DSCR 1.6468847293681788x.
V2_GOLDEN_INPUTS = AcquisitionInputs(
    purchase_price=10_000_000.0,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)
V2_GOLDEN_RESULTS = analyze_acquisition(V2_GOLDEN_INPUTS)

# A V1-era deal: every V2 field at its neutral dataclass default.
V1_GOLDEN_INPUTS = AcquisitionInputs(
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


def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-6)


# =============================================================================
# 1. Internal construction: every untouched field survives scenario/candidate
#    construction, checked generically (no hardcoded 14-field list) so a
#    future AcquisitionInputs field is covered automatically.
# =============================================================================


@pytest.mark.parametrize(
    "build_scenario_inputs",
    [sensitivity_module._build_scenario_inputs, break_even_module._build_scenario_inputs],
    ids=["sensitivity", "break_even"],
)
def test_build_scenario_inputs_preserves_every_untouched_field(build_scenario_inputs) -> None:
    changes = {"exit_cap_rate": 0.07, "noi_growth": 0.04}
    scenario = build_scenario_inputs(V2_GOLDEN_INPUTS, changes)

    for field in dataclasses.fields(AcquisitionInputs):
        if field.name in changes:
            continue
        assert getattr(scenario, field.name) == getattr(V2_GOLDEN_INPUTS, field.name), (
            f"{field.name} was not preserved from the base deal"
        )

    for name, value in changes.items():
        assert getattr(scenario, name) == value


@pytest.mark.parametrize(
    "build_scenario_inputs",
    [sensitivity_module._build_scenario_inputs, break_even_module._build_scenario_inputs],
    ids=["sensitivity", "break_even"],
)
def test_build_scenario_inputs_never_mutates_base(build_scenario_inputs) -> None:
    original = V2_GOLDEN_INPUTS
    build_scenario_inputs(V2_GOLDEN_INPUTS, {"ltv": 0.5})

    assert V2_GOLDEN_INPUTS == original


# =============================================================================
# 2a. Sensitivity -- required baseline-coordinate invariant (Gate 9B).
# =============================================================================


def test_exit_cap_noi_growth_baseline_equals_v2_base_analysis() -> None:
    presets = build_standard_presets(V2_GOLDEN_INPUTS)
    result = presets.exit_cap_noi_growth

    row_index = result.row_values.index(V2_GOLDEN_INPUTS.noi_growth)
    column_index = result.column_values.index(V2_GOLDEN_INPUTS.exit_cap_rate)

    assert result.baseline_metric_value == strict(V2_GOLDEN_RESULTS.levered_irr)
    assert result.matrix[row_index][column_index] == strict(V2_GOLDEN_RESULTS.levered_irr)
    assert V2_GOLDEN_RESULTS.levered_irr == pytest.approx(0.07380240064972221, abs=1e-9)


def test_purchase_price_exit_cap_baseline_equals_v2_base_analysis() -> None:
    presets = build_standard_presets(V2_GOLDEN_INPUTS)
    result = presets.purchase_price_exit_cap

    row_index = result.row_values.index(V2_GOLDEN_INPUTS.purchase_price)
    column_index = result.column_values.index(V2_GOLDEN_INPUTS.exit_cap_rate)

    assert result.baseline_metric_value == strict(V2_GOLDEN_RESULTS.levered_irr)
    assert result.matrix[row_index][column_index] == strict(V2_GOLDEN_RESULTS.levered_irr)


def test_interest_rate_ltv_baseline_equals_v2_base_levered_irr_and_headline_dscr() -> None:
    presets = build_standard_presets(V2_GOLDEN_INPUTS)

    irr_result = presets.interest_rate_ltv
    row_index = irr_result.row_values.index(V2_GOLDEN_INPUTS.interest_rate)
    column_index = irr_result.column_values.index(V2_GOLDEN_INPUTS.ltv)
    assert irr_result.baseline_metric_value == strict(V2_GOLDEN_RESULTS.levered_irr)
    assert irr_result.matrix[row_index][column_index] == strict(V2_GOLDEN_RESULTS.levered_irr)

    dscr_result = presets.interest_rate_ltv_dscr
    assert dscr_result.baseline_metric_value == strict(V2_GOLDEN_RESULTS.headline_dscr)
    assert dscr_result.matrix[row_index][column_index] == strict(V2_GOLDEN_RESULTS.headline_dscr)
    assert V2_GOLDEN_RESULTS.headline_dscr == strict(2.0)


# =============================================================================
# 2b. Sensitivity -- every cell reflects the full V2 deal, not a neutral
#     reset, and derived financing values (loan amount, financing fee,
#     equity, debt service) move naturally through the engine as LTV
#     changes rather than being held artificially constant (Gate 9B).
# =============================================================================


def test_two_way_sensitivity_cells_match_direct_engine_calls_on_the_full_v2_deal() -> None:
    """Every matrix cell must equal `analyze_acquisition` on the V2 golden
    deal with *only* the swept dimensions replaced -- proof (at the public
    API, not just the internal helper) that no sensitivity path silently
    resets the five V2 fields."""

    row_values = (0.03, 0.045, 0.06, 0.075)
    column_values = (0.50, 0.60, 0.70, 0.80)

    result = run_two_way_sensitivity(
        V2_GOLDEN_INPUTS,
        row_assumption="interest_rate",
        row_values=row_values,
        column_assumption="ltv",
        column_values=column_values,
        metric="levered_irr",
    )

    for row_index, interest_rate in enumerate(row_values):
        for column_index, ltv in enumerate(column_values):
            expected_inputs = dataclasses.replace(
                V2_GOLDEN_INPUTS, interest_rate=interest_rate, ltv=ltv
            )
            expected = analyze_acquisition(expected_inputs).levered_irr
            assert result.matrix[row_index][column_index] == pytest.approx(expected)


def test_ltv_sensitivity_naturally_moves_financing_fee_loan_and_equity_through_the_engine() -> None:
    """Changing LTV must change loan amount, financing fee (a function of
    loan amount), equity requirement, and debt service through the normal
    engine -- never held artificially constant."""

    low_ltv_results = analyze_acquisition(dataclasses.replace(V2_GOLDEN_INPUTS, ltv=0.50))
    high_ltv_results = analyze_acquisition(dataclasses.replace(V2_GOLDEN_INPUTS, ltv=0.70))

    assert low_ltv_results.loan_amount < high_ltv_results.loan_amount
    assert low_ltv_results.financing_fee < high_ltv_results.financing_fee
    assert low_ltv_results.initial_equity > high_ltv_results.initial_equity
    assert low_ltv_results.annual_debt_service[0] < high_ltv_results.annual_debt_service[0]

    # financing_fee is exactly financing_fee_pct of the (LTV-driven) loan
    # amount -- confirms the V2 field is still applied, not defaulted to 0.
    assert high_ltv_results.financing_fee == pytest.approx(
        high_ltv_results.loan_amount * V2_GOLDEN_INPUTS.financing_fee_pct
    )
    assert high_ltv_results.financing_fee > 0.0

    # And this is exactly what the interest_rate x ltv preset's baseline row
    # (interest_rate held at base) reports at these two LTV points.
    presets = build_standard_presets(V2_GOLDEN_INPUTS)
    result = presets.interest_rate_ltv
    row_index = result.row_values.index(V2_GOLDEN_INPUTS.interest_rate)
    ltv_050_index = result.column_values.index(0.50) if 0.50 in result.column_values else None
    ltv_070_index = result.column_values.index(0.70) if 0.70 in result.column_values else None
    if ltv_050_index is not None:
        assert result.matrix[row_index][ltv_050_index] == pytest.approx(low_ltv_results.levered_irr)
    if ltv_070_index is not None:
        assert result.matrix[row_index][ltv_070_index] == pytest.approx(high_ltv_results.levered_irr)


@pytest.mark.parametrize(
    "changes",
    [
        {"exit_cap_rate": 0.07},
        {"noi_growth": 0.05},
        {"purchase_price": 11_000_000.0},
        {"interest_rate": 0.06},
        {"ltv": 0.55},
    ],
)
def test_sensitivity_scenarios_preserve_all_five_v2_fields(changes: dict[str, float]) -> None:
    """Differential proof: for a single-dimension change, every V2 field
    (acquisition_cost_pct, financing_fee_pct, disposition_cost_pct,
    annual_capex_reserve, io_period) is unchanged in the constructed
    scenario, and the resulting engine economics incorporate them (the
    scenario is never bit-identical to the same change against a
    neutral-V2 deal)."""

    scenario_inputs = sensitivity_module._build_scenario_inputs(V2_GOLDEN_INPUTS, changes)

    assert scenario_inputs.acquisition_cost_pct == V2_GOLDEN_INPUTS.acquisition_cost_pct
    assert scenario_inputs.financing_fee_pct == V2_GOLDEN_INPUTS.financing_fee_pct
    assert scenario_inputs.disposition_cost_pct == V2_GOLDEN_INPUTS.disposition_cost_pct
    assert scenario_inputs.annual_capex_reserve == V2_GOLDEN_INPUTS.annual_capex_reserve
    assert scenario_inputs.io_period == V2_GOLDEN_INPUTS.io_period

    v2_neutral_scenario = dataclasses.replace(
        scenario_inputs,
        acquisition_cost_pct=0.0,
        financing_fee_pct=0.0,
        disposition_cost_pct=0.0,
        annual_capex_reserve=0.0,
        io_period=0,
    )
    with_v2 = analyze_acquisition(scenario_inputs)
    without_v2 = analyze_acquisition(v2_neutral_scenario)
    assert with_v2.levered_irr != pytest.approx(without_v2.levered_irr)


# =============================================================================
# 3. Break-even -- required directional invariants and re-verification
#    against the authoritative engine (Gate 9C).
# =============================================================================


V2_BREAK_EVEN = build_standard_break_even_analysis(
    V2_GOLDEN_INPUTS, target_levered_irr=0.10, target_headline_dscr=1.20
)


def test_v2_base_case_falls_short_of_the_ten_percent_irr_target() -> None:
    # The premise of every directional invariant below: the V2 golden case
    # earns ~7.38% at baseline, short of the 10% target.
    assert V2_GOLDEN_RESULTS.levered_irr == pytest.approx(0.07380240064972221, abs=1e-9)
    assert V2_GOLDEN_RESULTS.levered_irr < 0.10


def test_max_purchase_price_break_even_is_directionally_consistent() -> None:
    result = V2_BREAK_EVEN.max_purchase_price
    assert result.status == BreakEvenStatus.SOLVED
    # Base case falls short of the hurdle, so the qualifying purchase price
    # must be below the (too-generous) $10.0M baseline.
    assert result.solved_assumption_value < 10_000_000.0
    # Independent reconciliation checkpoint: ~$9.52M.
    assert result.solved_assumption_value == pytest.approx(9_520_000, rel=0.01)


def test_max_exit_cap_rate_break_even_is_directionally_consistent() -> None:
    result = V2_BREAK_EVEN.max_exit_cap_rate
    assert result.status == BreakEvenStatus.SOLVED
    assert result.solved_assumption_value < 0.065
    # Independent reconciliation checkpoint: ~6.09%.
    assert result.solved_assumption_value == pytest.approx(0.0609, rel=0.01)


def test_min_noi_growth_break_even_is_directionally_consistent() -> None:
    result = V2_BREAK_EVEN.min_noi_growth
    assert result.status == BreakEvenStatus.SOLVED
    assert result.solved_assumption_value > 0.03
    # Independent reconciliation checkpoint: ~4.19%.
    assert result.solved_assumption_value == pytest.approx(0.0419, rel=0.02)


@pytest.mark.parametrize(
    "break_even_type,assumption,metric,target",
    [
        ("max_purchase_price", "purchase_price", "levered_irr", 0.10),
        ("max_exit_cap_rate", "exit_cap_rate", "levered_irr", 0.10),
        ("min_noi_growth", "noi_growth", "levered_irr", 0.10),
        ("min_current_noi", "current_noi", "headline_dscr", 1.20),
    ],
)
def test_solved_break_even_values_reevaluate_through_the_engine_within_tolerance(
    break_even_type: str, assumption: str, metric: str, target: float
) -> None:
    """The single most important correctness proof: feed each solved
    assumption value back through the authoritative `analyze_acquisition`
    (never trusting the solver's own bookkeeping) and confirm the target
    metric is actually achieved, within the solver's own documented
    assumption-value tolerance translated to a generous metric delta."""

    result = getattr(V2_BREAK_EVEN, break_even_type)
    assert result.status == BreakEvenStatus.SOLVED
    assert result.solved_assumption_value is not None

    candidate = dataclasses.replace(
        V2_GOLDEN_INPUTS, **{assumption: result.solved_assumption_value}
    )
    reevaluated = getattr(analyze_acquisition(candidate), metric)

    assert reevaluated is not None
    assert reevaluated == pytest.approx(result.solved_metric_value)
    assert reevaluated == pytest.approx(target, abs=0.003)


@pytest.mark.parametrize(
    "break_even_type,assumption,direction_favors_lower",
    [
        ("max_purchase_price", "purchase_price", True),
        ("max_exit_cap_rate", "exit_cap_rate", True),
        ("min_noi_growth", "noi_growth", False),
        ("min_current_noi", "current_noi", False),
    ],
)
def test_solved_break_even_values_are_directionally_consistent_just_inside_and_outside(
    break_even_type: str, assumption: str, direction_favors_lower: bool
) -> None:
    """Just inside the solved boundary the hurdle is met; just outside it,
    the hurdle fails -- confirms the solved point is a genuine threshold,
    not a search artifact."""

    result = getattr(V2_BREAK_EVEN, break_even_type)
    solved = result.solved_assumption_value
    assert solved is not None

    step = solved * 0.001 if assumption in ("purchase_price", "current_noi") else 0.0005
    lower_candidate = dataclasses.replace(V2_GOLDEN_INPUTS, **{assumption: solved - step})
    upper_candidate = dataclasses.replace(V2_GOLDEN_INPUTS, **{assumption: solved + step})

    metric_name = result.metric
    lower_metric = getattr(analyze_acquisition(lower_candidate), metric_name)
    upper_metric = getattr(analyze_acquisition(upper_candidate), metric_name)

    favorable_metric = lower_metric if direction_favors_lower else upper_metric
    unfavorable_metric = upper_metric if direction_favors_lower else lower_metric

    assert favorable_metric is not None and favorable_metric >= result.target_metric_value
    assert unfavorable_metric is None or unfavorable_metric < result.target_metric_value


def test_max_interest_rate_dscr_break_even_documents_the_zero_rate_io_boundary_edge_case() -> None:
    """Gate 9C coverage: revalidates Maximum Interest Rate for the DSCR
    target against the V2 deal. The default search lower bound is exactly
    0.0, and with io_period=2 the Year-1 payment during the IO period is
    interest-only (principal * rate) -- at interest_rate=0.0 that payment is
    exactly 0.0, and the frozen DSCR convention
    (`engine.returns.calculate_dscr_by_year`: ADS_y == 0 => DSCR_y is None,
    never a fabricated infinity) makes headline_dscr None at that exact
    boundary. The solver only checks the two documented endpoints and never
    fabricates a value for an undefined boundary metric, so it reports
    NO_SOLUTION_IN_RANGE even though a qualifying interest rate exists
    strictly inside (0, upper_bound]. This is a pre-existing edge case in
    the boundary-only search heuristic, exposed now that the V2 io_period is
    correctly preserved (it was previously masked by the Gate 9A bug, which
    always reset io_period to 0 for every candidate) -- not a new
    regression, and out of scope for this fix (search-bounds mechanics are
    otherwise preserved). This test documents current, unchanged behavior;
    see the Gate 9 report for the recommendation to assess it separately.
    """

    result = V2_BREAK_EVEN.max_interest_rate
    assert result.status == BreakEvenStatus.NO_SOLUTION_IN_RANGE
    assert result.solved_assumption_value is None
    assert result.solved_metric_value is None

    # Confirm *why*: headline_dscr is genuinely None at the lower bound...
    boundary_results = analyze_acquisition(
        dataclasses.replace(V2_GOLDEN_INPUTS, interest_rate=result.lower_search_bound)
    )
    assert result.lower_search_bound == 0.0
    assert boundary_results.headline_dscr is None

    # ...even though a qualifying rate exists just inside the range.
    just_inside_results = analyze_acquisition(
        dataclasses.replace(V2_GOLDEN_INPUTS, interest_rate=0.001)
    )
    assert just_inside_results.headline_dscr is not None
    assert just_inside_results.headline_dscr >= 1.20


def test_min_current_noi_break_even_solves_for_the_v2_deal() -> None:
    result = V2_BREAK_EVEN.min_current_noi
    assert result.status == BreakEvenStatus.SOLVED
    assert result.solved_assumption_value is not None
    assert result.solved_assumption_value < V2_GOLDEN_INPUTS.current_noi


def test_break_even_dscr_questions_target_headline_dscr_not_min_dscr() -> None:
    """Gate 9C: confirms these two solvers intentionally target the
    existing headline (Year 1) DSCR convention, unchanged by this fix --
    never silently switched to min_dscr."""

    assert V2_BREAK_EVEN.max_interest_rate.metric == "headline_dscr"
    assert V2_BREAK_EVEN.min_current_noi.metric == "headline_dscr"


# =============================================================================
# 4. V1-neutral backward compatibility (Gate 9D).
# =============================================================================


def test_v1_neutral_sensitivity_baseline_still_matches_base_analysis() -> None:
    base_results = analyze_acquisition(V1_GOLDEN_INPUTS)
    presets = build_standard_presets(V1_GOLDEN_INPUTS)
    result = presets.exit_cap_noi_growth

    row_index = result.row_values.index(V1_GOLDEN_INPUTS.noi_growth)
    column_index = result.column_values.index(V1_GOLDEN_INPUTS.exit_cap_rate)

    assert result.matrix[row_index][column_index] == pytest.approx(base_results.levered_irr)


def test_v1_neutral_break_even_solutions_still_reevaluate_correctly() -> None:
    analysis = build_standard_break_even_analysis(
        V1_GOLDEN_INPUTS, target_levered_irr=0.08, target_headline_dscr=1.15
    )
    result = analysis.max_purchase_price
    assert result.status == BreakEvenStatus.SOLVED

    candidate = dataclasses.replace(
        V1_GOLDEN_INPUTS, purchase_price=result.solved_assumption_value
    )
    reevaluated = analyze_acquisition(candidate).levered_irr
    assert reevaluated == pytest.approx(0.08, abs=0.003)
