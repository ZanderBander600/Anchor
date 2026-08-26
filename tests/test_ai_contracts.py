"""Contract tests for the Phase 9A AI Analyst layer (``mini_anchor.ai.contracts``).

Mirrors the style of ``test_engine_contracts.py`` / ``test_analysis_presets.py``:
frozen/slotted/kw-only shape, exact fields, and immutable tuple collections.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest

from mini_anchor.ai.contracts import AIAnalysis, AnalysisContext
from mini_anchor.analysis import (
    ReturnHurdleMetric,
    build_standard_break_even_analysis,
    build_standard_presets,
)
from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine import analyze_acquisition

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

AI_ANALYSIS_FIELDS = (
    ("executive_summary", str),
    ("investment_view", str),
    ("strengths", tuple[str, ...]),
    ("risks", tuple[str, ...]),
    ("return_drivers", tuple[str, ...]),
    ("downside_analysis", str),
    ("capital_structure_analysis", str),
    ("break_even_analysis", str),
    ("questions_to_investigate", tuple[str, ...]),
    ("confidence_notes", tuple[str, ...]),
)


def _make_ai_analysis(**overrides: object) -> AIAnalysis:
    values: dict[str, object] = {
        "executive_summary": "Summary.",
        "investment_view": "View.",
        "strengths": ("Strength one.",),
        "risks": ("Risk one.",),
        "return_drivers": ("Driver one.",),
        "downside_analysis": "Downside.",
        "capital_structure_analysis": "Capital structure.",
        "break_even_analysis": "Break-even.",
        "questions_to_investigate": ("Question one.",),
        "confidence_notes": ("Note one.",),
    }
    values.update(overrides)
    return AIAnalysis(**values)  # type: ignore[arg-type]


def _make_context(**overrides: object) -> AnalysisContext:
    values: dict[str, object] = {
        "inputs": GOLDEN_INPUTS,
        "results": analyze_acquisition(GOLDEN_INPUTS),
        "sensitivities": build_standard_presets(GOLDEN_INPUTS),
        "break_even": build_standard_break_even_analysis(
            GOLDEN_INPUTS,
            target_levered_irr=0.10,
            target_headline_dscr=1.20,
            target_equity_multiple=1.50,
        ),
        "target_levered_irr": 0.10,
        "target_equity_multiple": 1.50,
        "target_headline_dscr": 1.20,
        "return_hurdle_metric": ReturnHurdleMetric.LEVERED_IRR,
    }
    values.update(overrides)
    return AnalysisContext(**values)  # type: ignore[arg-type]


# =============================================================================
# AIAnalysis
# =============================================================================


def test_ai_analysis_has_exact_fields_order_and_keyword_only_shape() -> None:
    contract_fields = fields(AIAnalysis)

    assert is_dataclass(AIAnalysis)
    assert tuple(field.name for field in contract_fields) == tuple(
        name for name, _ in AI_ANALYSIS_FIELDS
    )
    assert all(field.kw_only for field in contract_fields)
    assert AIAnalysis.__slots__ == tuple(name for name, _ in AI_ANALYSIS_FIELDS)


def test_ai_analysis_is_frozen_and_slotted() -> None:
    analysis = _make_ai_analysis()

    assert not hasattr(analysis, "__dict__")
    with pytest.raises(FrozenInstanceError):
        analysis.executive_summary = "changed"  # type: ignore[misc]


def test_ai_analysis_tuple_fields_are_immutable_tuples() -> None:
    analysis = _make_ai_analysis()

    for field_name in ("strengths", "risks", "return_drivers", "questions_to_investigate", "confidence_notes"):
        assert isinstance(getattr(analysis, field_name), tuple)


def test_ai_analysis_construction_requires_keywords() -> None:
    with pytest.raises(TypeError):
        AIAnalysis(  # type: ignore[misc,call-arg]
            "summary", "view", (), (), (), "downside", "capital", "break-even", (), ()
        )


# =============================================================================
# AnalysisContext
# =============================================================================


def test_analysis_context_has_exact_fields_and_keyword_only_shape() -> None:
    contract_fields = fields(AnalysisContext)

    assert is_dataclass(AnalysisContext)
    assert tuple(field.name for field in contract_fields) == (
        "inputs",
        "results",
        "sensitivities",
        "break_even",
        "target_levered_irr",
        "target_equity_multiple",
        "target_headline_dscr",
        "return_hurdle_metric",
    )
    assert all(field.kw_only for field in contract_fields)


def test_analysis_context_is_frozen_and_slotted() -> None:
    context = _make_context()

    assert not hasattr(context, "__dict__")
    with pytest.raises(FrozenInstanceError):
        context.target_levered_irr = 0.5  # type: ignore[misc]


def test_analysis_context_carries_the_exact_inputs_instance_unchanged() -> None:
    context = _make_context()

    assert context.inputs == GOLDEN_INPUTS
    assert context.inputs.purchase_price == 50_000_000.0


def test_analysis_context_carries_complete_results() -> None:
    context = _make_context()
    expected = analyze_acquisition(GOLDEN_INPUTS)

    assert context.results == expected


def test_analysis_context_carries_complete_sensitivities_and_break_even() -> None:
    context = _make_context()

    assert context.sensitivities == build_standard_presets(GOLDEN_INPUTS)
    assert context.break_even == build_standard_break_even_analysis(
        GOLDEN_INPUTS,
        target_levered_irr=0.10,
        target_headline_dscr=1.20,
        target_equity_multiple=1.50,
    )
