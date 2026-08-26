"""Phase 9A AI Analyst contracts.

Like ``mini_anchor.engine.contracts`` and ``mini_anchor.analysis.contracts``,
this module performs no calculation of its own -- it only describes the
shape of the deterministic context handed to the model
(``AnalysisContext``) and the structured interpretation handed back
(``AIAnalysis``). Neither dataclass computes, stores, or derives any
financial metric; ``AnalysisContext`` only aggregates already-computed
Phase 2/7/8 result contracts, and every ``AIAnalysis`` field is prose the
model produced by interpreting that context.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..analysis.contracts import (
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
    StandardSensitivityPresets,
)
from ..contracts import AcquisitionInputs
from ..engine.contracts import AcquisitionResults


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisContext:
    """The complete deterministic Mini-Anchor context supplied to the AI
    Analyst for one request.

    Every field is either the original validated ``AcquisitionInputs``, an
    already-computed Phase 2/7/8 result contract, or one of the three
    user-supplied hurdle targets from the request -- nothing here is
    computed by this module. Nesting the existing frozen contracts directly
    (rather than flattening/re-deriving their fields) guarantees the AI
    Analyst always sees the exact same raw decimals the deterministic
    engine and analysis layers produced.
    """

    inputs: AcquisitionInputs
    results: AcquisitionResults
    sensitivities: StandardSensitivityPresets
    break_even: StandardBreakEvenAnalysis
    target_levered_irr: float
    target_equity_multiple: float
    target_headline_dscr: float
    return_hurdle_metric: ReturnHurdleMetric


@dataclass(frozen=True, slots=True, kw_only=True)
class AIAnalysis:
    """The structured investment-analyst interpretation returned by the AI
    provider, suitable for direct frontend rendering.

    Every field is prose (or a tuple of prose statements) produced by
    interpreting a supplied ``AnalysisContext`` -- this contract never
    carries a newly generated numeric financial metric. Field set frozen
    per the Phase 9A AI Analyst spec.
    """

    executive_summary: str
    investment_view: str
    strengths: tuple[str, ...]
    risks: tuple[str, ...]
    return_drivers: tuple[str, ...]
    downside_analysis: str
    capital_structure_analysis: str
    break_even_analysis: str
    questions_to_investigate: tuple[str, ...]
    confidence_notes: tuple[str, ...]
