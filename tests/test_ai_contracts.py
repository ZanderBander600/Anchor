"""Contract tests for the Phase 9A AI Analyst layer (``anchor.ai.contracts``).

Mirrors the style of ``test_engine_contracts.py`` / ``test_analysis_presets.py``:
frozen/slotted/kw-only shape, exact fields, and immutable tuple collections.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from typing import get_type_hints

import pytest

from anchor.ai.contracts import AIAnalysis, AnalysisContext, DealStory
from anchor.analysis import (
    ReturnHurdleMetric,
    build_standard_break_even_analysis,
    build_standard_presets,
)
from anchor.contracts import AcquisitionInputs, OperatingMode
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
    ("deal_story", "DealStory | None"),
)

DEAL_STORY_FIELDS = (
    ("investment_view", str),
    ("key_strengths", tuple[str, ...]),
    ("key_risks", tuple[str, ...]),
    ("model_gap", "str | None"),
)


def _make_deal_story(**overrides: object) -> DealStory:
    values: dict[str, object] = {
        "investment_view": "Owner view.",
        "key_strengths": ("Story strength.",),
        "key_risks": ("Story risk.",),
        "model_gap": None,
    }
    values.update(overrides)
    return DealStory(**values)  # type: ignore[arg-type]


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
        "deal_story": _make_deal_story(),
    }
    values.update(overrides)
    return AIAnalysis(**values)  # type: ignore[arg-type]


def _make_context(**overrides: object) -> AnalysisContext:
    values: dict[str, object] = {
        "operating_mode": OperatingMode.QUICK,
        "inputs": GOLDEN_INPUTS,
        "terms": None,
        "detailed_operating_inputs": None,
        "operating_projection": None,
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
        "deal_context": None,
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


def test_ai_analysis_deal_story_defaults_to_none() -> None:
    """Sprint B Gate B4: the one defaulted field on the contract. The
    default exists so a pre-B4 ``ai_snapshot`` (whose stored JSON has no
    ``deal_story`` key) still decodes into a complete full report -- see
    ``anchor.deals.store._dataclass_from_json``. A live provider response
    always supplies one."""

    values = {name: getattr(_make_ai_analysis(), name) for name, _ in AI_ANALYSIS_FIELDS}
    del values["deal_story"]

    analysis = AIAnalysis(**values)  # type: ignore[arg-type]

    assert analysis.deal_story is None


# =============================================================================
# DealStory (Sprint B Gate B4)
# =============================================================================


def test_deal_story_has_exact_fields_order_and_keyword_only_shape() -> None:
    contract_fields = fields(DealStory)

    assert is_dataclass(DealStory)
    assert tuple(field.name for field in contract_fields) == tuple(
        name for name, _ in DEAL_STORY_FIELDS
    )
    assert all(field.kw_only for field in contract_fields)
    assert DealStory.__slots__ == tuple(name for name, _ in DEAL_STORY_FIELDS)


def test_deal_story_is_frozen_and_slotted() -> None:
    story = _make_deal_story()

    assert not hasattr(story, "__dict__")
    with pytest.raises(FrozenInstanceError):
        story.investment_view = "changed"  # type: ignore[misc]


def test_deal_story_tuple_fields_are_immutable_tuples() -> None:
    story = _make_deal_story()

    assert isinstance(story.key_strengths, tuple)
    assert isinstance(story.key_risks, tuple)


def test_deal_story_model_gap_is_nullable() -> None:
    assert _make_deal_story(model_gap=None).model_gap is None
    assert _make_deal_story(model_gap="Refinance is not modeled.").model_gap == (
        "Refinance is not modeled."
    )


def test_deal_story_accepts_up_to_two_strengths_and_risks() -> None:
    story = _make_deal_story(key_strengths=("One.", "Two."), key_risks=("One.", "Two."))

    assert story.key_strengths == ("One.", "Two.")
    assert story.key_risks == ("One.", "Two.")


def test_deal_story_accepts_empty_strengths_and_risks() -> None:
    """Fewer than the cap is always valid -- the contract sets a maximum,
    never a quota that would pressure the model into filler."""

    story = _make_deal_story(key_strengths=(), key_risks=())

    assert story.key_strengths == ()
    assert story.key_risks == ()


def test_deal_story_rejects_more_than_two_strengths() -> None:
    with pytest.raises(ValueError, match="key_strengths"):
        _make_deal_story(key_strengths=("One.", "Two.", "Three."))


def test_deal_story_rejects_more_than_two_risks() -> None:
    with pytest.raises(ValueError, match="key_risks"):
        _make_deal_story(key_risks=("One.", "Two.", "Three."))


def test_deal_story_max_story_items_is_two_and_not_a_dataclass_field() -> None:
    assert DealStory.MAX_STORY_ITEMS == 2
    assert "MAX_STORY_ITEMS" not in {field.name for field in fields(DealStory)}


def test_deal_story_carries_no_numeric_field() -> None:
    """The Deal Story is interpretation only -- like ``AIAnalysis``, it
    never carries a newly generated financial number."""

    hints = get_type_hints(DealStory)
    for name, _ in DEAL_STORY_FIELDS:
        assert hints[name] in (str, str | None, tuple[str, ...])


# =============================================================================
# AnalysisContext
# =============================================================================


def test_analysis_context_has_exact_fields_and_keyword_only_shape() -> None:
    contract_fields = fields(AnalysisContext)

    assert is_dataclass(AnalysisContext)
    assert tuple(field.name for field in contract_fields) == (
        "operating_mode",
        "inputs",
        "terms",
        "detailed_operating_inputs",
        "operating_projection",
        "results",
        "sensitivities",
        "break_even",
        "target_levered_irr",
        "target_equity_multiple",
        "target_headline_dscr",
        "return_hurdle_metric",
        "deal_context",
    )
    assert all(field.kw_only for field in contract_fields)


def test_analysis_context_quick_mode_rejects_detailed_fields_populated() -> None:
    with pytest.raises(ValueError, match="QUICK"):
        _make_context(terms=object())


def test_analysis_context_quick_mode_requires_inputs() -> None:
    with pytest.raises(ValueError, match="QUICK"):
        _make_context(inputs=None)


def test_analysis_context_detailed_mode_requires_all_three_detailed_fields() -> None:
    with pytest.raises(ValueError, match="DETAILED"):
        _make_context(
            operating_mode=OperatingMode.DETAILED,
            inputs=None,
            terms=object(),
            detailed_operating_inputs=None,
            operating_projection=None,
        )


def test_analysis_context_detailed_mode_rejects_inputs_populated() -> None:
    with pytest.raises(ValueError, match="DETAILED"):
        _make_context(
            operating_mode=OperatingMode.DETAILED,
            inputs=GOLDEN_INPUTS,
            terms=object(),
            detailed_operating_inputs=object(),
            operating_projection=object(),
        )


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
