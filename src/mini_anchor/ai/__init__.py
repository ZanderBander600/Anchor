"""Mini-Anchor Phase 9A AI Analyst layer.

Sits above the frozen Phase 2 engine and the Phase 7/8 analysis layers, and
below the FastAPI adapter (``mini_anchor.api``):

    financial engine
          ^
    analysis/sensitivity, analysis/break_even
          ^
    ai/analyst (context assembly + provider call)
          ^
        FastAPI
          ^
         React

This package never calculates, estimates, or reproduces a financial
metric. Every field in ``AnalysisContext`` is read directly off already
-computed ``AcquisitionResults``/``StandardSensitivityPresets``/
``StandardBreakEvenAnalysis`` values; the OpenAI model is asked only to
interpret those trusted values, never to compute new ones.
"""

from __future__ import annotations

from .analyst import build_analysis_context, generate_ai_analysis
from .contracts import AIAnalysis, AnalysisContext
from .provider import (
    DEFAULT_MODEL,
    AIConfigurationError,
    AIProviderError,
    OpenAIAnalystProvider,
)

__all__ = [
    "AIAnalysis",
    "AnalysisContext",
    "AIConfigurationError",
    "AIProviderError",
    "OpenAIAnalystProvider",
    "DEFAULT_MODEL",
    "build_analysis_context",
    "generate_ai_analysis",
]
