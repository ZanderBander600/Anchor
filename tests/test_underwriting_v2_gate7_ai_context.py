"""Underwriting V2 Gate 7 -- AI Analyst context integration.

Confirms the five V2 assumptions and the five new V2 deterministic dollar
results (Gate 2/3/4) reach the AI Analyst's presentation payload/prompt --
not just the raw ``AnalysisContext`` dataclass, which has carried them
since the Gate 4 contract expansion -- and that the payload never
recomputes anything: every formatted value is read directly from the
authoritative engine result via the existing, already-tested
``format_metric_value``/``format_currency`` presentation helpers, never a
hand-derived number. The AI layer remains interpretation-only throughout;
no financial formula is introduced anywhere in ``anchor.ai``.
"""

from __future__ import annotations

import json

import pytest

from anchor.ai.analyst import build_analysis_context
from anchor.ai.prompts import build_system_prompt, build_user_prompt
from anchor.ai.presentation import build_presentation_payload, format_currency, format_metric_value
from anchor.contracts import AcquisitionInputs

V1_NEUTRAL_INPUTS = AcquisitionInputs(
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

# The frozen Underwriting V2 golden case (docs/underwriting_v2_golden_case.md).
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

_HURDLES: dict[str, float] = dict(
    target_levered_irr=0.10,
    target_equity_multiple=1.50,
    target_headline_dscr=1.20,
)


def _context(inputs: AcquisitionInputs):
    return build_analysis_context(inputs, **_HURDLES)


def _payload(inputs: AcquisitionInputs) -> dict:
    return build_presentation_payload(_context(inputs))


# =============================================================================
# All five V2 assumptions reach AI context (the presentation payload the
# model actually receives, not just the raw AnalysisContext dataclass).
# =============================================================================


def test_all_five_v2_assumptions_reach_the_presentation_payload() -> None:
    context = _context(V2_GOLDEN_INPUTS)
    base_inputs = build_presentation_payload(context)["base_inputs"]

    assert base_inputs["acquisition_cost_pct"] == format_metric_value(
        "acquisition_cost_pct", context.inputs.acquisition_cost_pct
    )
    assert base_inputs["financing_fee_pct"] == format_metric_value(
        "financing_fee_pct", context.inputs.financing_fee_pct
    )
    assert base_inputs["disposition_cost_pct"] == format_metric_value(
        "disposition_cost_pct", context.inputs.disposition_cost_pct
    )
    assert base_inputs["annual_capex_reserve"] == format_metric_value(
        "annual_capex_reserve", context.inputs.annual_capex_reserve
    )
    assert base_inputs["io_period"] == format_metric_value("io_period", context.inputs.io_period)

    # Percentage fields render as percentages, not raw fractions.
    assert base_inputs["acquisition_cost_pct"].endswith("%")
    assert base_inputs["financing_fee_pct"].endswith("%")
    assert base_inputs["disposition_cost_pct"].endswith("%")
    # io_period renders with the same year-field convention as hold_period.
    assert base_inputs["io_period"].endswith("years")


def test_v1_neutral_assumptions_still_reach_the_payload_at_their_neutral_value() -> None:
    base_inputs = _payload(V1_NEUTRAL_INPUTS)["base_inputs"]

    assert base_inputs["acquisition_cost_pct"] == "0%"
    assert base_inputs["financing_fee_pct"] == "0%"
    assert base_inputs["disposition_cost_pct"] == "0%"
    assert base_inputs["annual_capex_reserve"] == "$0"
    assert base_inputs["io_period"] == "0 years"


# =============================================================================
# The five new V2 deterministic dollar results reach the payload.
# =============================================================================


def test_v2_dollar_results_reach_the_presentation_payload() -> None:
    context = _context(V2_GOLDEN_INPUTS)
    base_results = build_presentation_payload(context)["base_results"]

    assert base_results["acquisition_costs"] == format_currency(context.results.acquisition_costs)
    assert base_results["financing_fee"] == format_currency(context.results.financing_fee)
    assert base_results["disposition_costs"] == format_currency(context.results.disposition_costs)
    # Positive V2 golden-case values, not the V1-neutral zero default.
    assert context.results.acquisition_costs > 0
    assert context.results.financing_fee > 0
    assert context.results.disposition_costs > 0


def test_capex_by_year_reaches_the_payload_without_being_recomputed() -> None:
    context = _context(V2_GOLDEN_INPUTS)
    base_results = build_presentation_payload(context)["base_results"]

    expected = tuple(
        format_currency(value) for value in context.results.capex_by_year
    )
    assert base_results["capex_by_year"] == expected
    # The engine's own authoritative series, not a recomputed one -- each
    # entry equals the flat reserve for this deal.
    assert context.results.capex_by_year == (50_000.0,) * 5


# =============================================================================
# headline_dscr (Year 1) and min_dscr (minimum during the hold) are
# independently represented -- the most important V2 analytical addition.
# =============================================================================


def test_headline_dscr_and_min_dscr_are_independently_represented() -> None:
    context = _context(V2_GOLDEN_INPUTS)
    base_results = build_presentation_payload(context)["base_results"]

    assert base_results["headline_dscr"] == format_metric_value(
        "headline_dscr", context.results.headline_dscr
    )
    assert base_results["min_dscr"] == format_metric_value("min_dscr", context.results.min_dscr)
    # For this IO deal the two must genuinely differ -- proving the payload
    # doesn't collapse them into one figure.
    assert base_results["headline_dscr"] != base_results["min_dscr"]
    assert context.results.headline_dscr > context.results.min_dscr


def test_min_dscr_is_represented_safely_as_na_for_a_no_debt_case() -> None:
    zero_leverage_inputs = AcquisitionInputs(
        purchase_price=50_000_000.0,
        current_noi=2_500_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=5,
        exit_cap_rate=0.055,
        ltv=0.0,
        interest_rate=0.0525,
        amortization=30,
    )
    context = _context(zero_leverage_inputs)
    base_results = build_presentation_payload(context)["base_results"]

    assert context.results.min_dscr is None
    assert context.results.headline_dscr is None
    assert base_results["min_dscr"] == "N/A"
    assert base_results["headline_dscr"] == "N/A"


# =============================================================================
# The V2 golden case reaches context with the correct authoritative values.
# Every expected value below is read from the actual engine run, not
# hand-derived -- this only reconciles the presentation string against the
# already-verified (Gate 4) raw engine number, with a tolerance appropriate
# to the display precision.
# =============================================================================


def test_v2_golden_case_reaches_the_ai_context_with_correct_authoritative_values() -> None:
    context = _context(V2_GOLDEN_INPUTS)
    results = context.results

    # Reconcile the raw engine output against the frozen golden case
    # (docs/underwriting_v2_golden_case.md) -- proves the context is built
    # from a genuine engine run, not a stub.
    assert results.acquisition_costs == pytest.approx(200_000.0, abs=1.0)
    assert results.financing_fee == pytest.approx(60_000.0, abs=1.0)
    assert results.disposition_costs == pytest.approx(267_524.79, abs=1e-2)
    assert results.headline_dscr == pytest.approx(2.0, abs=1e-9)
    assert results.min_dscr == pytest.approx(1.64688, abs=1e-5)
    assert results.levered_irr == pytest.approx(0.073802, abs=1e-6)
    assert results.unlevered_irr == pytest.approx(0.061388, abs=1e-6)
    assert results.equity_multiple == pytest.approx(1.38235, abs=1e-5)

    payload = build_presentation_payload(context)
    base_inputs = payload["base_inputs"]
    base_results = payload["base_results"]

    assert base_inputs["purchase_price"] == "$10.0M"
    assert base_inputs["acquisition_cost_pct"] == "2%"
    assert base_inputs["financing_fee_pct"] == "1%"
    assert base_inputs["disposition_cost_pct"] == "2.5%"
    assert base_inputs["annual_capex_reserve"] == "$50.0K"
    assert base_inputs["io_period"] == "2 years"

    assert base_results["acquisition_costs"] == "$200.0K"
    assert base_results["financing_fee"] == "$60.0K"
    assert base_results["disposition_costs"] == "$267.5K"
    assert base_results["headline_dscr"] == "2.00x"
    assert base_results["min_dscr"] == "1.65x"
    assert base_results["levered_irr"] == "7.38%"
    assert base_results["unlevered_irr"] == "6.14%"
    assert base_results["equity_multiple"] == "1.38x"

    # And the same evidence actually reaches the serialized user prompt.
    user_prompt = build_user_prompt(context)
    serialized_payload = json.loads(user_prompt[user_prompt.index("{") :])
    assert serialized_payload["base_results"]["min_dscr"] == "1.65x"
    assert serialized_payload["base_inputs"]["io_period"] == "2 years"


# =============================================================================
# System-prompt grounding: V2 semantic definitions and the
# headline_dscr/min_dscr distinction, without asking the model to
# calculate anything itself.
# =============================================================================


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def test_system_prompt_explains_v2_transaction_cost_and_capex_semantics() -> None:
    prompt = _normalize_whitespace(build_system_prompt().lower())

    assert "percentage of purchase price" in prompt
    assert "percentage of loan amount" in prompt
    assert "percentage of gross exit value" in prompt
    assert "below-noi" in prompt
    assert "interest-only debt before scheduled principal amortization" in prompt


def test_system_prompt_explains_headline_dscr_vs_min_dscr_distinction() -> None:
    prompt = _normalize_whitespace(build_system_prompt().lower())

    assert "headline_dscr is year 1 dscr" in prompt
    assert "min_dscr is the" in prompt and "lowest dscr" in prompt
    assert "never changes reported noi" in prompt


def test_system_prompt_still_forbids_independent_calculation_of_v2_amounts() -> None:
    prompt = _normalize_whitespace(build_system_prompt().lower())

    assert "never recompute any of them from the percentage/reserve inputs" in prompt
