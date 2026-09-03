"""Tests for the Phase 9A deterministic presentation layer
(``anchor.ai.presentation``).

Covers the Phase 9A final live-evaluation regressions:

1. Human-readable financial formatting (currency $/K/M, percentages, "x"
   multiples) instead of raw machine decimals.
2. Deterministic hurdle-relationship labeling (e.g. "1.22x -- above 1.20x
   target") so the model is never left to judge a hurdle comparison from a
   raw number itself -- including the exact DSCR value from the reported
   regression (1.2205000701906463 mislabeled as below a 1.20x hurdle).
3. No raw long-decimal float leaking into the full model-facing payload for
   standard golden/strong-deal cases.

None of these tests touch the financial engine, the deterministic analysis
modules, or ``AnalysisContext`` itself -- only the presentation strings this
module derives from already-computed, trusted values.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields

import pytest

from anchor.ai.analyst import build_analysis_context
from anchor.ai.presentation import (
    INTENTIONALLY_EXCLUDED_INPUT_FIELDS,
    INTENTIONALLY_EXCLUDED_RESULT_FIELDS,
    UnknownPresentationFieldError,
    _format_inputs,
    _format_results,
    build_presentation_payload,
    format_currency,
    format_hurdle_relationship,
    format_metric_value,
    format_multiple,
    format_percent,
)
from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition
from anchor.engine.contracts import AcquisitionResults

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

# A second, distinct "strong deal" scenario -- lower leverage, higher NOI
# growth -- to confirm no-raw-float coverage isn't an artifact of one
# specific input combination.
STRONG_DEAL_INPUTS = AcquisitionInputs(
    purchase_price=30_000_000.0,
    current_noi=2_100_000.0,
    occupancy=0.97,
    noi_growth=0.045,
    hold_period=7,
    exit_cap_rate=0.0475,
    ltv=0.55,
    interest_rate=0.0475,
    amortization=30,
)

_LONG_DECIMAL_PATTERN = re.compile(r"\d\.\d{5,}")


def _payload_for(inputs: AcquisitionInputs) -> dict:
    context = build_analysis_context(
        inputs,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
    )
    return build_presentation_payload(context)


# =============================================================================
# Primitive formatters
# =============================================================================


@pytest.mark.parametrize(
    "value, expected",
    [
        (45_000_000.0, "$45.0M"),
        (-45_000_000.0, "-$45.0M"),
        (500_000.0, "$500.0K"),
        (999.0, "$999"),
        (0.0, "$0"),
    ],
)
def test_format_currency(value: float, expected: str) -> None:
    assert format_currency(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.16444164771657266, "16.44%"),
        (0.6, "60%"),
        (0.0475, "4.75%"),
        (0.03, "3%"),
    ],
)
def test_format_percent(value: float, expected: str) -> None:
    assert format_percent(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (1.4791697077264836, "1.48x"),
        (1.2205000701906463, "1.22x"),
        (1.5, "1.50x"),
    ],
)
def test_format_multiple(value: float, expected: str) -> None:
    assert format_multiple(value) == expected


def test_format_metric_value_returns_na_for_none() -> None:
    assert format_metric_value("headline_dscr", None) == "N/A"


def test_format_metric_value_raises_for_unknown_field() -> None:
    with pytest.raises(UnknownPresentationFieldError):
        format_metric_value("not_a_real_field", 1.0)


def test_format_metric_value_formats_years_as_whole_numbers() -> None:
    assert format_metric_value("hold_period", 5) == "5 years"
    assert format_metric_value("amortization", 30) == "30 years"


# =============================================================================
# Hurdle relationship labeling (Issue 2 regression)
# =============================================================================


def test_hurdle_relationship_labels_dscr_above_target_from_reported_regression() -> None:
    # Exact value from the Phase 9A live-evaluation regression: the model
    # previously claimed this DSCR was *below* a 1.20x hurdle.
    label = format_hurdle_relationship("headline_dscr", 1.2205000701906463, 1.20)

    assert label == "1.22x — above 1.20x target"


def test_hurdle_relationship_labels_dscr_below_target() -> None:
    label = format_hurdle_relationship("headline_dscr", 1.13, 1.20)

    assert label == "1.13x — below 1.20x target"


def test_hurdle_relationship_labels_exact_match_as_at() -> None:
    label = format_hurdle_relationship("headline_dscr", 1.20, 1.20)

    assert label == "1.20x — at 1.20x target"


def test_hurdle_relationship_handles_none_metric_without_fabricating_a_comparison() -> None:
    label = format_hurdle_relationship("headline_dscr", None, 1.20)

    assert "N/A" in label
    assert "above" not in label
    assert "below" not in label


def test_hurdle_relationship_labels_levered_irr_with_percent_formatting() -> None:
    label = format_hurdle_relationship("levered_irr", 0.145, 0.10)

    assert label == "14.5% — above 10% target"


def test_hurdle_relationship_labels_equity_multiple_with_x_formatting() -> None:
    label = format_hurdle_relationship("equity_multiple", 1.35, 1.50)

    assert label == "1.35x — below 1.50x target"


# =============================================================================
# Precision disambiguation near a hurdle threshold (this issue's regression)
# =============================================================================
#
# Default rounding can make a metric that is genuinely above or below its
# hurdle *display* as exactly equal to it (e.g. "1.20x -- below 1.20x
# target"), which reads as self-contradictory even though the underlying
# comparison is correct. When that happens, displayed precision for the
# metric (never the target, and never the comparison itself) is stepped up
# just enough to make the relation visually consistent.


def test_hurdle_relationship_disambiguates_dscr_just_below_target() -> None:
    # Exact value from this issue: raw DSCR 1.1977023312417228 rounds to
    # "1.20x" at the normal 2-decimal precision, colliding with the 1.20x
    # target even though the deterministic comparison says "below".
    label = format_hurdle_relationship("headline_dscr", 1.1977023312417228, 1.20)

    assert label == "1.198x — below 1.20x target"


def test_hurdle_relationship_disambiguates_dscr_just_above_target() -> None:
    # Analogous case on the other side of the hurdle: still reads as an
    # exact match at 3 decimals ("1.200x" vs "1.200x"), so precision must
    # climb again before the two diverge.
    label = format_hurdle_relationship("headline_dscr", 1.2004, 1.20)

    assert label == "1.2004x — above 1.20x target"


def test_hurdle_relationship_disambiguates_equity_multiple_just_below_target() -> None:
    label = format_hurdle_relationship("equity_multiple", 1.4996, 1.50)

    assert label == "1.4996x — below 1.50x target"


def test_hurdle_relationship_disambiguates_levered_irr_just_below_target() -> None:
    label = format_hurdle_relationship("levered_irr", 0.099999, 0.10)

    assert label == "9.9999% — below 10% target"


def test_hurdle_relationship_disambiguates_levered_irr_just_above_target() -> None:
    label = format_hurdle_relationship("levered_irr", 0.1000499, 0.10)

    assert label == "10.005% — above 10% target"


def test_hurdle_relationship_keeps_concise_formatting_when_unambiguous() -> None:
    # No collision at default precision -- must not gain spurious extra
    # decimals just because the value is near its hurdle.
    assert (
        format_hurdle_relationship("headline_dscr", 1.2205000701906463, 1.20)
        == "1.22x — above 1.20x target"
    )
    assert format_hurdle_relationship("headline_dscr", 1.13, 1.20) == "1.13x — below 1.20x target"
    assert (
        format_hurdle_relationship("levered_irr", 0.145, 0.10) == "14.5% — above 10% target"
    )


def test_hurdle_relationship_exact_match_still_reports_at_without_extra_precision() -> None:
    # An exact match is not a rounding artifact -- it must stay "at" and
    # must not be run through the disambiguation step at all.
    label = format_hurdle_relationship("headline_dscr", 1.20, 1.20)

    assert label == "1.20x — at 1.20x target"


# =============================================================================
# Full payload: human-readable formatting + no raw long-decimal floats
# =============================================================================


@pytest.mark.parametrize("inputs", [GOLDEN_INPUTS, STRONG_DEAL_INPUTS], ids=["golden", "strong_deal"])
def test_payload_uses_human_readable_formatting(inputs: AcquisitionInputs) -> None:
    payload = _payload_for(inputs)

    assert payload["base_inputs"]["purchase_price"].startswith("$")
    assert payload["base_inputs"]["purchase_price"].endswith("M")
    assert payload["base_inputs"]["exit_cap_rate"].endswith("%")
    assert payload["base_inputs"]["ltv"].endswith("%")
    assert payload["base_inputs"]["hold_period"].endswith("years")

    for field in ("levered_irr", "unlevered_irr"):
        value = payload["base_results"][field]
        assert value == "N/A" or value.endswith("%")
    for field in ("equity_multiple", "headline_dscr"):
        value = payload["base_results"][field]
        assert value == "N/A" or value.endswith("x")


@pytest.mark.parametrize("inputs", [GOLDEN_INPUTS, STRONG_DEAL_INPUTS], ids=["golden", "strong_deal"])
def test_payload_has_no_raw_long_decimal_floats(inputs: AcquisitionInputs) -> None:
    payload = _payload_for(inputs)
    serialized = json.dumps(payload)

    assert _LONG_DECIMAL_PATTERN.search(serialized) is None


@pytest.mark.parametrize("inputs", [GOLDEN_INPUTS, STRONG_DEAL_INPUTS], ids=["golden", "strong_deal"])
def test_payload_hurdle_evaluation_section_has_above_at_below_relationship_words(
    inputs: AcquisitionInputs,
) -> None:
    payload = _payload_for(inputs)
    hurdle_evaluation = payload["hurdle_evaluation"]

    for key in ("levered_irr_vs_target", "equity_multiple_vs_target", "headline_dscr_vs_target"):
        value = hurdle_evaluation[key]
        assert ("above" in value) or ("below" in value) or ("at" in value) or ("N/A" in value)


@pytest.mark.parametrize("inputs", [GOLDEN_INPUTS, STRONG_DEAL_INPUTS], ids=["golden", "strong_deal"])
def test_payload_break_even_results_include_hurdle_relationship_and_search_bounds(
    inputs: AcquisitionInputs,
) -> None:
    payload = _payload_for(inputs)

    for key in (
        "max_purchase_price",
        "max_exit_cap_rate",
        "min_noi_growth",
        "max_interest_rate",
        "min_current_noi",
    ):
        entry = payload["break_even"][key]
        assert "baseline_metric_value_vs_target" in entry
        relation = entry["baseline_metric_value_vs_target"]
        assert ("above" in relation) or ("below" in relation) or ("at" in relation) or (
            "N/A" in relation
        )
        assert "to" in entry["search_bounds"]


@pytest.mark.parametrize("inputs", [GOLDEN_INPUTS, STRONG_DEAL_INPUTS], ids=["golden", "strong_deal"])
def test_payload_dscr_sensitivity_matrix_cells_carry_hurdle_labels(
    inputs: AcquisitionInputs,
) -> None:
    payload = _payload_for(inputs)
    dscr_grid = payload["sensitivities"]["interest_rate_ltv_dscr"]

    for row in dscr_grid["matrix"]:
        for cell in row:
            assert ("above" in cell) or ("below" in cell) or ("at" in cell) or ("N/A" in cell)


# =============================================================================
# No-independent-calculation rules remain intact (Phase 9A core rule)
# =============================================================================


def test_presentation_layer_never_averages_or_derives_new_numeric_values() -> None:
    """The presentation layer only formats and labels already-supplied
    values -- it must never combine two supplied numbers into a new one
    (e.g. an average, spread, or projected value) beyond a plain hurdle
    comparison."""

    payload = _payload_for(GOLDEN_INPUTS)
    context = build_analysis_context(
        GOLDEN_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
    )

    # Every formatted base_results value round-trips to the exact same
    # trusted number it was formatted from -- nothing was derived.
    assert payload["base_results"]["headline_dscr"] == format_metric_value(
        "headline_dscr", context.results.headline_dscr
    )
    assert payload["base_inputs"]["purchase_price"] == format_metric_value(
        "purchase_price", context.inputs.purchase_price
    )


# =============================================================================
# Gate 8 architecture guardrail -- deliberate omission, not accidental drift.
#
# A future field added to AcquisitionInputs or AcquisitionResults must
# either be presented to the AI Analyst or be named explicitly in
# presentation.py's INTENTIONALLY_EXCLUDED_*_FIELDS allowlist. This test
# fails the moment a new dataclass field exists that neither
# _format_inputs/_format_results nor the allowlist accounts for -- so
# omission from AI context can only ever be a deliberate decision, never a
# forgotten one. It never forces every field to be shown (the allowlist
# provides the deliberate-exclusion escape hatch) and never touches the
# presentation classification/formatting logic itself.
# =============================================================================


def test_every_acquisition_input_field_is_presented_or_deliberately_excluded() -> None:
    formatted = _format_inputs(GOLDEN_INPUTS)

    dataclass_fields = {field.name for field in fields(AcquisitionInputs)}
    accounted_for = set(formatted) | INTENTIONALLY_EXCLUDED_INPUT_FIELDS
    missing = dataclass_fields - accounted_for

    assert not missing, (
        f"AcquisitionInputs field(s) {missing} are neither formatted by "
        "_format_inputs nor listed in INTENTIONALLY_EXCLUDED_INPUT_FIELDS "
        "-- the AI Analyst presentation layer must deliberately decide "
        "whether to show a new field, not silently omit it."
    )


def test_every_acquisition_results_field_is_presented_or_deliberately_excluded() -> None:
    results = analyze_acquisition(GOLDEN_INPUTS)
    formatted = _format_results(results)

    dataclass_fields = {field.name for field in fields(AcquisitionResults)}
    accounted_for = set(formatted) | INTENTIONALLY_EXCLUDED_RESULT_FIELDS
    missing = dataclass_fields - accounted_for

    assert not missing, (
        f"AcquisitionResults field(s) {missing} are neither formatted by "
        "_format_results nor listed in INTENTIONALLY_EXCLUDED_RESULT_FIELDS "
        "-- the AI Analyst presentation layer must deliberately decide "
        "whether to show a new field, not silently omit it."
    )


def test_intentional_exclusion_allowlists_are_currently_empty_or_documented() -> None:
    """Documents the current state: every ``AcquisitionInputs`` field is
    presented today (allowlist empty). ``AcquisitionResults`` has four
    deliberate Owner Return Metrics V3 Gate A2 exclusions (values fully
    computed and authoritative on the result; deliberate AI presentation is
    deferred to a later gate) -- if either allowlist's membership ever
    legitimately changes further, update the allowlist in presentation.py
    (with a comment explaining why) rather than this test."""

    assert INTENTIONALLY_EXCLUDED_INPUT_FIELDS == frozenset()
    assert INTENTIONALLY_EXCLUDED_RESULT_FIELDS == frozenset(
        {
            "levered_cash_on_cash_by_year",
            "unlevered_cash_yield_by_year",
            "cumulative_operating_distributions_by_year",
            "year_1_debt_yield",
        }
    )
