"""Tests for Phase 9A ``AnalysisContext`` construction
(``anchor.ai.analyst.build_analysis_context``).

Confirms the context includes every ``AcquisitionInputs`` field, the
complete ``AcquisitionResults``, the standard sensitivities, and the
standard break-even analysis; that raw decimals are preserved with no
presentation formatting; that the base inputs are never mutated; and that
construction delegates to the existing Phase 2/7/8 entry points rather than
reproducing any calculation.
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import patch

from anchor.ai.analyst import build_analysis_context
from anchor.analysis import ReturnHurdleMetric
from anchor.contracts import AcquisitionInputs
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


def _build(**overrides: object):
    values: dict[str, object] = {
        "target_levered_irr": 0.10,
        "target_equity_multiple": 1.50,
        "target_headline_dscr": 1.20,
    }
    values.update(overrides)
    return build_analysis_context(GOLDEN_INPUTS, **values)  # type: ignore[arg-type]


def test_context_carries_every_acquisition_input_field() -> None:
    context = _build()

    for field in fields(AcquisitionInputs):
        assert getattr(context.inputs, field.name) == getattr(GOLDEN_INPUTS, field.name)


def test_context_base_inputs_are_unchanged_and_not_mutated() -> None:
    original_purchase_price = GOLDEN_INPUTS.purchase_price

    _build()

    assert GOLDEN_INPUTS.purchase_price == original_purchase_price
    assert GOLDEN_INPUTS.occupancy == 0.95


def test_context_carries_every_acquisition_results_field() -> None:
    context = _build()

    result_field_names = {field.name for field in fields(AcquisitionResults)}
    for field_name in result_field_names:
        # Every declared AcquisitionResults field is readable on the
        # context's nested results -- nothing was dropped.
        getattr(context.results, field_name)

    assert result_field_names == {
        "going_in_cap_rate",
        "loan_amount",
        "acquisition_costs",
        "financing_fee",
        "initial_equity",
        "monthly_debt_service",
        "annual_debt_service",
        "remaining_loan_balance",
        "noi_by_year",
        "capex_by_year",
        "exit_noi",
        "exit_value",
        "disposition_costs",
        "net_sale_proceeds",
        "unlevered_cash_flows",
        "levered_cash_flows",
        "unlevered_irr",
        "levered_irr",
        "equity_multiple",
        "dscr_by_year",
        "headline_dscr",
        "min_dscr",
    }


def test_context_carries_standard_sensitivities() -> None:
    context = _build()

    assert context.sensitivities.exit_cap_noi_growth is not None
    assert context.sensitivities.purchase_price_exit_cap is not None
    assert context.sensitivities.interest_rate_ltv is not None
    assert context.sensitivities.interest_rate_ltv_dscr is not None


def test_context_carries_standard_break_even_analysis() -> None:
    context = _build()

    assert context.break_even.max_purchase_price is not None
    assert context.break_even.max_exit_cap_rate is not None
    assert context.break_even.min_noi_growth is not None
    assert context.break_even.max_interest_rate is not None
    assert context.break_even.min_current_noi is not None


def test_context_preserves_raw_decimal_values_not_presentation_strings() -> None:
    context = _build()

    assert isinstance(context.results.levered_irr, float)
    assert context.results.levered_irr == analyze_acquisition_result_levered_irr()
    assert isinstance(context.inputs.exit_cap_rate, float)
    assert context.inputs.exit_cap_rate == 0.055


def analyze_acquisition_result_levered_irr() -> float | None:
    from anchor.engine import analyze_acquisition

    return analyze_acquisition(GOLDEN_INPUTS).levered_irr


def test_context_carries_hurdle_targets_and_return_hurdle_metric_unchanged() -> None:
    context = _build(
        target_levered_irr=0.12, target_equity_multiple=1.75, target_headline_dscr=1.30
    )

    assert context.target_levered_irr == 0.12
    assert context.target_equity_multiple == 1.75
    assert context.target_headline_dscr == 1.30
    assert context.return_hurdle_metric is ReturnHurdleMetric.LEVERED_IRR


def test_context_respects_explicit_equity_multiple_return_hurdle() -> None:
    context = _build(return_hurdle_metric=ReturnHurdleMetric.EQUITY_MULTIPLE)

    assert context.return_hurdle_metric is ReturnHurdleMetric.EQUITY_MULTIPLE
    assert context.break_even.max_purchase_price.metric == "equity_multiple"


def test_build_analysis_context_delegates_to_engine_and_analysis_layers() -> None:
    from anchor.engine import analyze_acquisition

    with patch(
        "anchor.ai.analyst.analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        _build()

    assert mock_analyze.call_count >= 1


def test_build_analysis_context_calls_standard_presets_and_break_even_once_each() -> None:
    from anchor.analysis import build_standard_break_even_analysis, build_standard_presets

    with (
        patch(
            "anchor.ai.analyst.build_standard_presets", wraps=build_standard_presets
        ) as mock_presets,
        patch(
            "anchor.ai.analyst.build_standard_break_even_analysis",
            wraps=build_standard_break_even_analysis,
        ) as mock_break_even,
    ):
        _build()

    mock_presets.assert_called_once()
    mock_break_even.assert_called_once()
