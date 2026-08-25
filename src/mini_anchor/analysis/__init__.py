"""Mini-Anchor Phase 7 deterministic sensitivity-analysis layer.

Sits above the frozen Phase 2 engine (``mini_anchor.engine``) and below the
FastAPI adapter (``mini_anchor.api``):

    financial engine
          ^
    analysis/sensitivity
          ^
        FastAPI
          ^
         React

This package never reproduces a financial formula -- every sensitivity
scenario is evaluated by calling ``analyze_acquisition`` and reading a field
off its result. ``analysis.break_even`` (or similar) can be added later
alongside ``sensitivity.py`` without restructuring this package.
"""

from __future__ import annotations

from .contracts import (
    OneWaySensitivityResult,
    StandardSensitivityPresets,
    TwoWaySensitivityResult,
)
from .sensitivity import (
    SUPPORTED_ASSUMPTIONS,
    SUPPORTED_METRICS,
    UnknownAssumptionError,
    UnknownMetricError,
    build_exit_cap_noi_growth_preset,
    build_interest_rate_ltv_preset,
    build_purchase_price_exit_cap_preset,
    build_standard_presets,
    run_one_way_sensitivity,
    run_two_way_sensitivity,
)

__all__ = [
    "SUPPORTED_ASSUMPTIONS",
    "SUPPORTED_METRICS",
    "OneWaySensitivityResult",
    "TwoWaySensitivityResult",
    "StandardSensitivityPresets",
    "UnknownAssumptionError",
    "UnknownMetricError",
    "run_one_way_sensitivity",
    "run_two_way_sensitivity",
    "build_exit_cap_noi_growth_preset",
    "build_purchase_price_exit_cap_preset",
    "build_interest_rate_ltv_preset",
    "build_standard_presets",
]
