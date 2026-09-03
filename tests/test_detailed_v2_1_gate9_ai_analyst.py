"""Detailed Operating Model V2.1 Gate 9 -- Detailed AI Analyst integration.

Covers the 18 required scenarios from this gate's instructions. No test in
this module makes a real OpenAI API call -- the provider is always a fake
injected via ``provider=`` or ``patch("anchor.ai.analyst.OpenAIAnalystProvider")``.
Golden-case values are generated from the authoritative deterministic
engine (``analyze_detailed_acquisition_with_projection``), never
hardcoded into production code.
"""

from __future__ import annotations

import json
from dataclasses import fields

import pytest

from anchor.ai.analyst import (
    build_analysis_context,
    build_detailed_analysis_context,
    generate_ai_analysis,
    generate_detailed_ai_analysis,
)
from anchor.ai.contracts import AIAnalysis
from anchor.ai.presentation import (
    INTENTIONALLY_EXCLUDED_DETAILED_OPERATING_FIELDS,
    INTENTIONALLY_EXCLUDED_OPERATING_PROJECTION_FIELDS,
    INTENTIONALLY_EXCLUDED_TERMS_FIELDS,
    _format_detailed_operating_inputs,
    _format_operating_projection,
    _format_terms,
    build_presentation_payload,
)
from anchor.ai.prompts import build_user_prompt
from anchor.contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
)
from anchor.engine import analyze_detailed_acquisition_with_projection
from anchor.engine.contracts import OperatingProjection

GOLDEN_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
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

GOLDEN_DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)

GOLDEN_QUICK_INPUTS = AcquisitionInputs(
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
    target_levered_irr=0.10, target_equity_multiple=1.50, target_headline_dscr=1.20
)


class _RecordingProvider:
    """A fake provider that records every call and never touches the network."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def generate_analysis(self, *, system_prompt: str, user_prompt: str) -> AIAnalysis:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return AIAnalysis(
            executive_summary="Summary.",
            investment_view="View.",
            strengths=("Strength.",),
            risks=("Risk.",),
            return_drivers=("Driver.",),
            downside_analysis="Downside.",
            capital_structure_analysis="Capital.",
            break_even_analysis="Break-even.",
            questions_to_investigate=("Question.",),
            confidence_notes=("Note.",),
        )


# =============================================================================
# 1. Quick AI context remains backward compatible
# =============================================================================


def test_quick_ai_context_remains_backward_compatible() -> None:
    context = build_analysis_context(GOLDEN_QUICK_INPUTS, **_HURDLES)

    assert context.operating_mode is OperatingMode.QUICK
    assert context.inputs == GOLDEN_QUICK_INPUTS
    assert context.terms is None
    assert context.detailed_operating_inputs is None
    assert context.operating_projection is None

    payload = build_presentation_payload(context)
    assert "base_inputs" in payload
    assert payload["base_inputs"]["current_noi"] == "$600.0K"
    assert "base_terms" not in payload
    assert "operating_projection" not in payload


def test_quick_ai_analysis_still_generates_via_fake_provider() -> None:
    provider = _RecordingProvider()
    analysis = generate_ai_analysis(GOLDEN_QUICK_INPUTS, provider=provider, **_HURDLES)

    assert isinstance(analysis, AIAnalysis)
    assert len(provider.calls) == 1
    assert '"operating_mode": "quick"' in provider.calls[0]["user_prompt"]


# =============================================================================
# 2. Detailed AI context identifies operating_mode correctly
# =============================================================================


def test_detailed_ai_context_identifies_operating_mode() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )

    assert context.operating_mode is OperatingMode.DETAILED

    payload = build_presentation_payload(context)
    assert payload["operating_mode"] == "detailed"


# =============================================================================
# 3. DetailedOperatingInputs reach the AI presentation payload
# =============================================================================


def test_detailed_operating_inputs_reach_the_presentation_payload() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    payload = build_presentation_payload(context)

    section = payload["base_detailed_operating_inputs"]
    assert section["gross_potential_rent"] == "$800.0K"
    assert section["other_income"] == "$20.0K"
    assert section["vacancy_credit_loss_pct"] == "5%"
    assert section["property_taxes"] == "$60.0K"
    assert section["insurance"] == "$20.0K"
    assert section["utilities"] == "$25.0K"
    assert section["repairs_maintenance"] == "$20.0K"
    assert section["other_operating_expenses"] == "$16.0K"
    assert section["management_fee_pct"] == "5%"
    assert section["revenue_growth"] == "3%"
    assert section["expense_growth"] == "3%"


# =============================================================================
# 4. OperatingProjection schedules reach the AI context
# =============================================================================


def test_operating_projection_schedules_reach_the_ai_context() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )

    assert isinstance(context.operating_projection, OperatingProjection)
    for field in fields(OperatingProjection):
        getattr(context.operating_projection, field.name)  # nothing dropped

    payload = build_presentation_payload(context)
    schedule = payload["operating_projection"]
    for key in (
        "gross_potential_rent_by_year",
        "other_income_by_year",
        "vacancy_credit_loss_by_year",
        "effective_gross_income_by_year",
        "property_taxes_by_year",
        "insurance_by_year",
        "utilities_by_year",
        "repairs_maintenance_by_year",
        "other_operating_expenses_by_year",
        "management_fee_by_year",
        "total_operating_expenses_by_year",
        "noi_by_year",
        "exit_noi",
    ):
        assert key in schedule


# =============================================================================
# 5. Existing acquisition/debt/returns results reach Detailed AI context
# =============================================================================


def test_existing_acquisition_debt_returns_results_reach_detailed_context() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    expected = analyze_detailed_acquisition_with_projection(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    ).results

    assert context.results == expected

    payload = build_presentation_payload(context)
    results_section = payload["base_results"]
    for key in (
        "loan_amount",
        "acquisition_costs",
        "financing_fee",
        "initial_equity",
        "capex_by_year",
        "annual_debt_service",
        "remaining_loan_balance",
        "disposition_costs",
        "exit_value",
        "net_sale_proceeds",
        "headline_dscr",
        "min_dscr",
        "dscr_by_year",
        "unlevered_irr",
        "levered_irr",
        "equity_multiple",
    ):
        assert key in results_section


# =============================================================================
# 6/7. Detailed sensitivity/break-even results are included where appropriate
# =============================================================================


def test_detailed_sensitivity_results_are_included() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    payload = build_presentation_payload(context)

    assert set(payload["sensitivities"].keys()) == {
        "purchase_price_exit_cap",
        "interest_rate_ltv",
        "interest_rate_ltv_dscr",
    }
    # No Detailed counterpart exists for the noi_growth-based dimension.
    assert "exit_cap_noi_growth" not in payload["sensitivities"]


def test_detailed_break_even_results_are_included() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    payload = build_presentation_payload(context)

    assert set(payload["break_even"].keys()) == {
        "max_purchase_price",
        "max_exit_cap_rate",
        "max_interest_rate",
    }
    # No Detailed counterpart exists for current_noi/noi_growth.
    assert "min_noi_growth" not in payload["break_even"]
    assert "min_current_noi" not in payload["break_even"]


# =============================================================================
# 8/9. No fake current_noi/noi_growth appears as a Detailed analyst assumption
# =============================================================================


def test_no_fake_current_noi_in_detailed_payload() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    payload = build_presentation_payload(context)
    serialized = json.dumps(payload)

    assert "current_noi" not in serialized
    assert context.inputs is None


def test_no_fake_noi_growth_in_detailed_payload() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    payload = build_presentation_payload(context)
    serialized = json.dumps(payload)

    assert '"noi_growth"' not in serialized


# =============================================================================
# 10. revenue_growth and expense_growth remain independently represented
# =============================================================================


def test_revenue_growth_and_expense_growth_are_independently_represented() -> None:
    diverging_inputs = DetailedOperatingInputs(
        gross_potential_rent=800_000.0,
        other_income=20_000.0,
        vacancy_credit_loss_pct=0.05,
        property_taxes=60_000.0,
        insurance=20_000.0,
        utilities=25_000.0,
        repairs_maintenance=20_000.0,
        other_operating_expenses=16_000.0,
        management_fee_pct=0.05,
        revenue_growth=0.04,
        expense_growth=0.01,
    )
    context = build_detailed_analysis_context(GOLDEN_TERMS, diverging_inputs, **_HURDLES)
    payload = build_presentation_payload(context)

    section = payload["base_detailed_operating_inputs"]
    assert section["revenue_growth"] == "4%"
    assert section["expense_growth"] == "1%"
    assert section["revenue_growth"] != section["expense_growth"]


# =============================================================================
# 11. vacancy_credit_loss_pct is represented as an underwriting assumption
# =============================================================================


def test_vacancy_credit_loss_pct_is_a_labeled_underwriting_assumption() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    payload = build_presentation_payload(context)

    assert payload["base_detailed_operating_inputs"]["vacancy_credit_loss_pct"] == "5%"
    # It lives under the assumptions section, not results/market-evidence.
    assert "vacancy_credit_loss_pct" not in payload["base_results"]


def test_system_prompt_instructs_vacancy_is_an_assumption_not_market_evidence() -> None:
    from anchor.ai.prompts import build_system_prompt

    prompt = build_system_prompt().lower()

    assert "underwriting assumes 5% vacancy" in prompt
    assert "not the market vacancy rate" in prompt or "never" in prompt


# =============================================================================
# 12. capex remains represented below NOI
# =============================================================================


def test_capex_remains_represented_below_noi_never_folded_into_operating_projection() -> (
    None
):
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    payload = build_presentation_payload(context)

    # CapEx lives only in base_results, never as an operating_projection field.
    assert "capex_by_year" in payload["base_results"]
    assert "capex_by_year" not in payload["operating_projection"]
    assert "capex" not in {key.lower() for key in payload["operating_projection"]}


# =============================================================================
# 13. headline_dscr and min_dscr remain independently represented
# =============================================================================


def test_headline_dscr_and_min_dscr_independently_represented_in_detailed_mode() -> None:
    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    payload = build_presentation_payload(context)

    results_section = payload["base_results"]
    assert results_section["headline_dscr"] == "2.00x"
    assert results_section["min_dscr"] == "1.65x"
    assert results_section["headline_dscr"] != results_section["min_dscr"]


# =============================================================================
# 14. No underwriting formulas are introduced into AI-specific code
# =============================================================================


def test_ai_presentation_module_imports_no_math() -> None:
    import ast
    from pathlib import Path

    source_file = Path(__file__).resolve().parents[1] / "src" / "anchor" / "ai" / "presentation.py"
    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert "math" not in imported


# =============================================================================
# 15. Reflection-based AI field coverage guardrails, extended for the three
#     new Detailed contracts
# =============================================================================


def test_every_acquisition_terms_field_is_presented_or_deliberately_excluded() -> None:
    formatted = _format_terms(GOLDEN_TERMS)

    dataclass_fields = {field.name for field in fields(AcquisitionTerms)}
    accounted_for = set(formatted) | INTENTIONALLY_EXCLUDED_TERMS_FIELDS
    missing = dataclass_fields - accounted_for

    assert not missing, (
        f"AcquisitionTerms field(s) {missing} are neither formatted by "
        "_format_terms nor listed in INTENTIONALLY_EXCLUDED_TERMS_FIELDS."
    )


def test_every_detailed_operating_inputs_field_is_presented_or_deliberately_excluded() -> (
    None
):
    formatted = _format_detailed_operating_inputs(GOLDEN_DETAILED_OPERATING_INPUTS)

    dataclass_fields = {field.name for field in fields(DetailedOperatingInputs)}
    accounted_for = set(formatted) | INTENTIONALLY_EXCLUDED_DETAILED_OPERATING_FIELDS
    missing = dataclass_fields - accounted_for

    assert not missing, (
        f"DetailedOperatingInputs field(s) {missing} are neither formatted "
        "by _format_detailed_operating_inputs nor listed in "
        "INTENTIONALLY_EXCLUDED_DETAILED_OPERATING_FIELDS."
    )


def test_every_operating_projection_field_is_presented_or_deliberately_excluded() -> None:
    envelope = analyze_detailed_acquisition_with_projection(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )
    formatted = _format_operating_projection(envelope.operating_projection)

    dataclass_fields = {field.name for field in fields(OperatingProjection)}
    accounted_for = set(formatted) | INTENTIONALLY_EXCLUDED_OPERATING_PROJECTION_FIELDS
    missing = dataclass_fields - accounted_for

    assert not missing, (
        f"OperatingProjection field(s) {missing} are neither formatted by "
        "_format_operating_projection nor listed in "
        "INTENTIONALLY_EXCLUDED_OPERATING_PROJECTION_FIELDS."
    )


def test_detailed_intentional_exclusion_allowlists_are_currently_empty() -> None:
    assert INTENTIONALLY_EXCLUDED_TERMS_FIELDS == frozenset()
    assert INTENTIONALLY_EXCLUDED_DETAILED_OPERATING_FIELDS == frozenset()
    assert INTENTIONALLY_EXCLUDED_OPERATING_PROJECTION_FIELDS == frozenset()


# =============================================================================
# 16. Detailed golden-case values reach the prompt exactly from engine results
# =============================================================================


def test_detailed_golden_case_values_reach_the_prompt_exactly() -> None:
    """docs/detailed_operating_model_v2_1_golden_case.md's Year 1-5 NOI,
    exit NOI, and headline return metrics, generated here from the live
    engine (never hardcoded into production code), must appear verbatim in
    the serialized user prompt."""

    context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )
    prompt = build_user_prompt(context)

    envelope = analyze_detailed_acquisition_with_projection(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )
    assert envelope.results.noi_by_year[0] == pytest.approx(600_000.0, abs=1e-6)
    assert envelope.operating_projection.exit_noi == pytest.approx(695_564.44458, abs=1e-3)
    assert envelope.results.headline_dscr == pytest.approx(2.0, abs=1e-5)
    assert envelope.results.min_dscr == pytest.approx(1.64688, abs=1e-5)
    assert envelope.results.levered_irr == pytest.approx(0.073802, abs=1e-6)

    assert "$600.0K" in prompt  # Year 1 NOI
    assert "$618.0K" in prompt  # Year 2 NOI
    assert "$695.6K" in prompt  # exit NOI (rounded to $K per format_currency)
    assert "2.00x" in prompt  # headline DSCR
    assert "1.65x" in prompt  # min DSCR (1.64688 rounds to 1.65x)
    assert "7.38%" in prompt  # levered IRR


def test_detailed_ai_analysis_generates_via_fake_provider_with_golden_case() -> None:
    provider = _RecordingProvider()
    analysis = generate_detailed_ai_analysis(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, provider=provider, **_HURDLES
    )

    assert isinstance(analysis, AIAnalysis)
    assert len(provider.calls) == 1
    assert '"operating_mode": "detailed"' in provider.calls[0]["user_prompt"]
    assert "$600.0K" in provider.calls[0]["user_prompt"]


# =============================================================================
# 17. min_dscr=None and other optional result cases remain safely handled
# =============================================================================


def test_zero_leverage_detailed_deal_handles_none_dscr_safely() -> None:
    zero_leverage_terms = AcquisitionTerms(
        purchase_price=10_000_000.0,
        hold_period=5,
        exit_cap_rate=0.065,
        ltv=0.0,
        interest_rate=0.05,
        amortization=30,
        acquisition_cost_pct=0.02,
        financing_fee_pct=0.01,
        disposition_cost_pct=0.025,
        annual_capex_reserve=50_000.0,
        io_period=0,
    )
    context = build_detailed_analysis_context(
        zero_leverage_terms, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )

    assert context.results.headline_dscr is None
    assert context.results.min_dscr is None

    payload = build_presentation_payload(context)
    assert payload["base_results"]["headline_dscr"] == "N/A"
    assert payload["base_results"]["min_dscr"] == "N/A"
    assert "N/A" in payload["hurdle_evaluation"]["headline_dscr_vs_target"]

    # Never raises, and never fabricates a numeric value.
    prompt = build_user_prompt(context)
    assert "N/A" in prompt


# =============================================================================
# 18. Existing Quick AI tests remain green -- explicit smoke check here too
# =============================================================================


def test_quick_and_detailed_contexts_coexist_without_cross_contamination() -> None:
    """Building a Detailed context immediately after a Quick context (or
    vice versa) must not leak state between them -- each AnalysisContext is
    independently constructed from its own inputs."""

    quick_context = build_analysis_context(GOLDEN_QUICK_INPUTS, **_HURDLES)
    detailed_context = build_detailed_analysis_context(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, **_HURDLES
    )

    assert quick_context.operating_mode is OperatingMode.QUICK
    assert detailed_context.operating_mode is OperatingMode.DETAILED
    # Economically identical golden decks -- equivalent to floating-point
    # noise only (Gate 4's cross-model equivalence test covers this in
    # full; this is just a lightweight non-contamination smoke check).
    assert detailed_context.results.headline_dscr == pytest.approx(
        quick_context.results.headline_dscr, rel=0.0, abs=1e-6
    )
    assert detailed_context.results.levered_irr == pytest.approx(
        quick_context.results.levered_irr, rel=0.0, abs=1e-6
    )
    assert quick_context.inputs is not None
    assert detailed_context.inputs is None
