"""Anchor Phase 9A / Detailed Operating Model V2.1 Gate 9 AI Analyst layer.

Sits above the frozen Phase 2 engine, the Phase 7/8 analysis layers, and
the Detailed Operating Model V2.1 engine/analysis layers, and below the
FastAPI adapter (``anchor.api``):

    financial engine (+ Detailed operating projection)
          ^
    analysis/sensitivity, analysis/break_even (+ Detailed counterparts)
          ^
    ai/analyst (context assembly + provider call)
          ^
        FastAPI
          ^
         React

This package never calculates, estimates, or reproduces a financial
metric. Every field in ``AnalysisContext`` is read directly off already
-computed ``AcquisitionResults``/``OperatingProjection``/
``StandardSensitivityPresets``/``StandardDetailedSensitivityPresets``/
``StandardBreakEvenAnalysis``/``StandardDetailedBreakEvenAnalysis`` values;
the OpenAI model is asked only to interpret those trusted values, never to
compute new ones -- for either Quick or Detailed Underwrite.
"""

from __future__ import annotations

from .analyst import (
    build_analysis_context,
    build_detailed_analysis_context,
    generate_ai_analysis,
    generate_detailed_ai_analysis,
)
from .contracts import AIAnalysis, AnalysisContext, DealStory
from .provider import (
    DEFAULT_MODEL,
    AIConfigurationError,
    AIProviderError,
    OpenAIAnalystProvider,
)

__all__ = [
    "AIAnalysis",
    "AnalysisContext",
    "DealStory",
    "AIConfigurationError",
    "AIProviderError",
    "OpenAIAnalystProvider",
    "DEFAULT_MODEL",
    "build_analysis_context",
    "build_detailed_analysis_context",
    "generate_ai_analysis",
    "generate_detailed_ai_analysis",
]
