"""Phase 9A AI Analyst orchestration.

Builds the deterministic ``AnalysisContext`` for one request by calling the
existing, frozen Phase 2 engine entry point (``analyze_acquisition``) and
the existing Phase 7/8 analysis entry points (``build_standard_presets``,
``build_standard_break_even_analysis``) exactly once each, then hands the
resulting context to the AI provider. This module reproduces no financial
formula, sensitivity scenario, or break-even search of its own -- it only
assembles already-computed results and reads them into ``AnalysisContext``.
"""

from __future__ import annotations

from ..analysis import (
    ReturnHurdleMetric,
    build_standard_break_even_analysis,
    build_standard_presets,
)
from ..contracts import AcquisitionInputs
from ..engine import analyze_acquisition
from .contracts import AIAnalysis, AnalysisContext
from .prompts import build_system_prompt, build_user_prompt
from .provider import OpenAIAnalystProvider


def build_analysis_context(
    inputs: AcquisitionInputs,
    *,
    target_levered_irr: float,
    target_equity_multiple: float,
    target_headline_dscr: float,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
) -> AnalysisContext:
    """Assemble one deterministic ``AnalysisContext`` for ``inputs``.

    Calls ``analyze_acquisition``, ``build_standard_presets``, and
    ``build_standard_break_even_analysis`` -- the same authoritative Phase
    2/7/8 entry points the ``/analyze``, ``/sensitivity/presets``, and
    ``/break-even`` endpoints use -- exactly once each, and reads their
    results directly into the context. No financial formula, sensitivity
    scenario, or break-even search is reproduced here.
    """

    results = analyze_acquisition(inputs)
    sensitivities = build_standard_presets(inputs)
    break_even = build_standard_break_even_analysis(
        inputs,
        target_levered_irr=target_levered_irr,
        target_headline_dscr=target_headline_dscr,
        target_equity_multiple=target_equity_multiple,
        return_hurdle_metric=return_hurdle_metric,
    )

    return AnalysisContext(
        inputs=inputs,
        results=results,
        sensitivities=sensitivities,
        break_even=break_even,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
    )


def generate_ai_analysis(
    inputs: AcquisitionInputs,
    *,
    target_levered_irr: float,
    target_equity_multiple: float,
    target_headline_dscr: float,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
    provider: OpenAIAnalystProvider | None = None,
) -> AIAnalysis:
    """Build the deterministic context for ``inputs`` and return one AI
    Analyst interpretation of it.

    ``provider`` defaults to a real ``OpenAIAnalystProvider`` (which lazily
    reads ``OPENAI_API_KEY``/``ANCHOR_AI_MODEL`` only when a call is
    actually made); tests inject a fake provider to avoid any real network
    call.
    """

    context = build_analysis_context(
        inputs,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
    )

    active_provider = provider if provider is not None else OpenAIAnalystProvider()
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(context)

    return active_provider.generate_analysis(
        system_prompt=system_prompt, user_prompt=user_prompt
    )
