"""Tests for the Phase 9A AI Analyst grounding prompt
(``mini_anchor.ai.prompts``).

Confirms the system prompt explicitly forbids independent financial
calculation and invented facts, preserves the bounded break-even
NO_SOLUTION_IN_RANGE semantics, notes the occupancy convention, tells the
model to distinguish evidence from interpretation, and (Phase 9A final
hardening) instructs the model to defer to supplied hurdle-relationship
labels rather than judge a hurdle comparison itself; and confirms the user
prompt carries deterministic presentation-formatted evidence (currency,
percentages, "x" multiples, hurdle labels), never raw long-decimal floats.
"""

from __future__ import annotations

import json
import re

from mini_anchor.ai.analyst import build_analysis_context
from mini_anchor.ai.prompts import build_system_prompt, build_user_prompt
from mini_anchor.contracts import AcquisitionInputs

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


def _context():
    return build_analysis_context(
        GOLDEN_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
    )


# =============================================================================
# System prompt (grounding rules)
# =============================================================================


def test_system_prompt_forbids_independent_financial_calculation() -> None:
    prompt = build_system_prompt()

    assert "do not independently calculate" in prompt.lower()
    for metric_term in ("IRR", "Equity Multiple", "DSCR", "debt service", "exit value"):
        assert metric_term in prompt


def test_system_prompt_forbids_invented_facts() -> None:
    prompt = build_system_prompt()

    assert "do not invent missing property facts" in prompt.lower()


def test_system_prompt_preserves_bounded_break_even_semantics() -> None:
    prompt = build_system_prompt()

    assert "no_solution_in_range" in prompt.lower()
    assert "never restate this as" in prompt.lower()
    assert "impossible" in prompt.lower()


def test_system_prompt_notes_occupancy_convention() -> None:
    prompt = build_system_prompt()

    assert "occupancy" in prompt.lower()
    assert "current noi already reflects" in prompt.lower()


def test_system_prompt_tells_model_to_distinguish_facts_from_interpretation() -> None:
    prompt = build_system_prompt()

    assert "distinguish" in prompt.lower()
    assert "interpretation" in prompt.lower()


def test_system_prompt_forbids_unsupplied_market_facts() -> None:
    prompt = build_system_prompt()

    for term in ("market comps", "tenant credit", "lease rollover", "market rents", "capex", "taxes"):
        assert term in prompt.lower()


def test_system_prompt_says_insufficient_evidence_must_be_flagged() -> None:
    prompt = build_system_prompt()

    assert "insufficient" in prompt.lower()


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def test_system_prompt_forbids_derived_spreads_and_differences() -> None:
    prompt = build_system_prompt()

    lowered = _normalize_whitespace(prompt.lower())
    for term in ("spread", "difference", "delta", "basis-point gap"):
        assert term in lowered
    assert "25 bps tighter" in _normalize_whitespace(prompt)
    assert "the exit cap rate is lower than the going-in cap rate" in lowered


def test_system_prompt_requires_hurdle_claims_consistent_with_every_cited_cell() -> None:
    prompt = build_system_prompt()

    lowered = _normalize_whitespace(prompt.lower())
    assert "never say all scenarios clear a hurdle" in lowered
    assert "if any scenario" in lowered


def test_system_prompt_tells_model_to_defer_to_supplied_hurdle_labels() -> None:
    prompt = build_system_prompt()

    lowered = _normalize_whitespace(prompt.lower())
    assert "already labeled in the supplied evidence with its relationship" in lowered
    assert "never independently judge whether a supplied" in lowered
    assert "above, at, or below a hurdle" in lowered


# =============================================================================
# User prompt (presentation-formatted evidence)
# =============================================================================


def test_user_prompt_contains_formatted_evidence_not_raw_decimal_floats() -> None:
    prompt = build_user_prompt(_context())

    json_start = prompt.index("{")
    payload = json.loads(prompt[json_start:])

    # Human-readable presentation, not raw machine decimals.
    assert payload["base_inputs"]["exit_cap_rate"] == "5.5%"
    assert payload["base_inputs"]["purchase_price"] == "$50.0M"
    assert isinstance(payload["base_inputs"]["exit_cap_rate"], str)
    assert isinstance(payload["base_inputs"]["purchase_price"], str)

    # No raw long-decimal float leaks anywhere in the serialized payload.
    serialized = json.dumps(payload)
    assert re.search(r"\d\.\d{5,}", serialized) is None


def test_user_prompt_includes_hurdle_targets_and_return_hurdle_metric() -> None:
    prompt = build_user_prompt(_context())

    json_start = prompt.index("{")
    payload = json.loads(prompt[json_start:])

    assert payload["hurdle_targets"]["target_levered_irr"] == "10%"
    assert payload["hurdle_targets"]["target_equity_multiple"] == "1.50x"
    assert payload["hurdle_targets"]["target_headline_dscr"] == "1.20x"
    assert payload["hurdle_targets"]["return_hurdle_metric"] == "levered_irr"


def test_user_prompt_includes_complete_base_results_and_break_even() -> None:
    prompt = build_user_prompt(_context())

    json_start = prompt.index("{")
    payload = json.loads(prompt[json_start:])

    assert "levered_irr" in payload["base_results"]
    assert "headline_dscr" in payload["base_results"]
    assert set(payload["break_even"].keys()) == {
        "max_purchase_price",
        "max_exit_cap_rate",
        "min_noi_growth",
        "max_interest_rate",
        "min_current_noi",
    }
    assert payload["break_even"]["max_purchase_price"]["status"] in (
        "solved",
        "no_solution_in_range",
    )


def test_user_prompt_includes_sensitivity_matrices() -> None:
    prompt = build_user_prompt(_context())

    json_start = prompt.index("{")
    payload = json.loads(prompt[json_start:])

    assert set(payload["sensitivities"].keys()) == {
        "exit_cap_noi_growth",
        "purchase_price_exit_cap",
        "interest_rate_ltv",
        "interest_rate_ltv_dscr",
    }
