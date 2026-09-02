"""Anchor Phase 7 sensitivity-analysis and Phase 8 break-even-analysis
layers.

Sits above the frozen Phase 2 engine (``anchor.engine``) and below the
FastAPI adapter (``anchor.api``):

    financial engine
          ^
    analysis/sensitivity, analysis/break_even
          ^
        FastAPI
          ^
         React

This package never reproduces or algebraically rearranges a financial
formula -- every sensitivity scenario and every break-even candidate is
evaluated by calling ``analyze_acquisition`` and reading a field off its
result.
"""

from __future__ import annotations

from .break_even import (
    BreakEvenDirection,
    InvalidBreakEvenBoundsError,
    InvalidBreakEvenTargetError,
    build_standard_break_even_analysis,
    solve_break_even_threshold,
    solve_detailed_max_exit_cap_rate,
    solve_detailed_max_interest_rate,
    solve_detailed_max_purchase_price,
    solve_detailed_break_even_threshold,
    solve_max_exit_cap_rate,
    solve_max_interest_rate,
    solve_max_purchase_price,
    solve_min_current_noi,
    solve_min_noi_growth,
)
from .contracts import (
    BreakEvenResult,
    BreakEvenStatus,
    BreakEvenType,
    OneWaySensitivityResult,
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
    StandardSensitivityPresets,
    TwoWaySensitivityResult,
)
from .sensitivity import (
    DETAILED_SUPPORTED_ASSUMPTIONS,
    SUPPORTED_ASSUMPTIONS,
    SUPPORTED_METRICS,
    UnknownAssumptionError,
    UnknownMetricError,
    build_exit_cap_noi_growth_preset,
    build_interest_rate_ltv_preset,
    build_purchase_price_exit_cap_preset,
    build_standard_presets,
    run_detailed_one_way_sensitivity,
    run_detailed_two_way_sensitivity,
    run_one_way_sensitivity,
    run_two_way_sensitivity,
)

__all__ = [
    "SUPPORTED_ASSUMPTIONS",
    "SUPPORTED_METRICS",
    "DETAILED_SUPPORTED_ASSUMPTIONS",
    "OneWaySensitivityResult",
    "TwoWaySensitivityResult",
    "StandardSensitivityPresets",
    "UnknownAssumptionError",
    "UnknownMetricError",
    "run_one_way_sensitivity",
    "run_two_way_sensitivity",
    "run_detailed_one_way_sensitivity",
    "run_detailed_two_way_sensitivity",
    "build_exit_cap_noi_growth_preset",
    "build_purchase_price_exit_cap_preset",
    "build_interest_rate_ltv_preset",
    "build_standard_presets",
    "BreakEvenDirection",
    "BreakEvenResult",
    "BreakEvenStatus",
    "BreakEvenType",
    "ReturnHurdleMetric",
    "StandardBreakEvenAnalysis",
    "InvalidBreakEvenBoundsError",
    "InvalidBreakEvenTargetError",
    "solve_break_even_threshold",
    "solve_detailed_break_even_threshold",
    "solve_max_purchase_price",
    "solve_max_exit_cap_rate",
    "solve_min_noi_growth",
    "solve_max_interest_rate",
    "solve_min_current_noi",
    "solve_detailed_max_purchase_price",
    "solve_detailed_max_exit_cap_rate",
    "solve_detailed_max_interest_rate",
    "build_standard_break_even_analysis",
]
