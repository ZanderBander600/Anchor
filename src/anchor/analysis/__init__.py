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
evaluated by calling ``analyze_acquisition``/``analyze_detailed_acquisition_
with_projection`` and reading a field off its result.
"""

from __future__ import annotations

from .break_even import (
    BreakEvenDirection,
    InvalidBreakEvenBoundsError,
    InvalidBreakEvenTargetError,
    build_standard_break_even_analysis,
    build_standard_detailed_break_even_analysis,
    solve_break_even_threshold,
    solve_detailed_break_even_threshold,
    solve_detailed_max_exit_cap_rate,
    solve_detailed_max_interest_rate,
    solve_detailed_max_purchase_price,
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
    LeaseLevelAcquisitionResults,
    OneWaySensitivityResult,
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
    StandardDetailedBreakEvenAnalysis,
    StandardDetailedSensitivityPresets,
    StandardSensitivityPresets,
    TwoWaySensitivityResult,
)
from .lease_level import analyze_lease_level_acquisition_with_projection
from .lease_level_sensitivity import (
    LEASE_LEVEL_SUPPORTED_ASSUMPTIONS,
    LEASE_LEVEL_SUPPORTED_METRICS,
    SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE,
    SensitivityTargetShadowedBySuiteOverrideError,
    UnknownLeaseLevelAssumptionError,
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
)
# D5.3 -- the analysis package's facade over the D5.2 structural parser.
#
# ``api.py`` must not import ``anchor.leasing`` (HD-D4-8: the dependency
# direction is leasing -> analysis -> engine, and the leasing architecture
# guardrails enforce it). The parser's implementation owner stays
# ``leasing/parsing.py``; this is a re-export, not a copy and not a second
# parser, so the delivery layer reaches it through the same boundary it already
# reaches ``analyze_lease_level_acquisition_with_projection`` through.
#
# Imported here rather than added to ``lease_level.py`` deliberately: that
# module is the D4.5B financial bridge and is held byte-identical by the D4.6B
# guardrails. A transport concern does not belong in it.
# ``LeaseValidationError`` travels with them: it is what both
# ``parse_lease_level_inputs`` and
# ``analyze_lease_level_acquisition_with_projection`` raise, so a caller that
# can reach the entry point but not its failure mode could not use it at all.
from ..leasing.validation import LeaseValidationError
from ..leasing.parsing import ParsedLeaseLevelInputs, parse_lease_level_inputs
from .sensitivity import (
    DETAILED_SUPPORTED_ASSUMPTIONS,
    SUPPORTED_ASSUMPTIONS,
    SUPPORTED_METRICS,
    UnknownAssumptionError,
    UnknownMetricError,
    build_detailed_interest_rate_ltv_preset,
    build_detailed_purchase_price_exit_cap_preset,
    build_exit_cap_noi_growth_preset,
    build_interest_rate_ltv_preset,
    build_purchase_price_exit_cap_preset,
    build_standard_detailed_presets,
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
    "StandardDetailedSensitivityPresets",
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
    "build_detailed_purchase_price_exit_cap_preset",
    "build_detailed_interest_rate_ltv_preset",
    "build_standard_detailed_presets",
    "BreakEvenDirection",
    "BreakEvenResult",
    "BreakEvenStatus",
    "BreakEvenType",
    "ReturnHurdleMetric",
    "StandardBreakEvenAnalysis",
    "StandardDetailedBreakEvenAnalysis",
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
    "build_standard_detailed_break_even_analysis",
    # Lease-Level structural request parsing (D5.2), re-exported at D5.3 so
    # the API can reach it without importing anchor.leasing directly.
    "LeaseValidationError",
    "ParsedLeaseLevelInputs",
    "parse_lease_level_inputs",
    # Lease-Level acquisition orchestration (D4.5B)
    "LeaseLevelAcquisitionResults",
    "analyze_lease_level_acquisition_with_projection",
    # Lease-Level sensitivity (D4.6B) -- the third parallel runner pair. No
    # OperatingMode member accompanies it: the mode is distinguished by
    # function identity, and D5 owns public mode publication.
    "LEASE_LEVEL_SUPPORTED_ASSUMPTIONS",
    "LEASE_LEVEL_SUPPORTED_METRICS",
    "SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE",
    "SensitivityTargetShadowedBySuiteOverrideError",
    "UnknownLeaseLevelAssumptionError",
    "run_lease_level_one_way_sensitivity",
    "run_lease_level_two_way_sensitivity",
]
