"""Phase 9A / Detailed Operating Model V2.1 Gate 9 AI Analyst orchestration.

Builds the deterministic ``AnalysisContext`` for one request by calling the
existing, frozen engine entry point (``analyze_acquisition`` for Quick,
``analyze_detailed_acquisition_with_projection`` for Detailed) and the
existing analysis-layer entry points (``build_standard_presets``/
``build_standard_detailed_presets``, ``build_standard_break_even_analysis``/
``build_standard_detailed_break_even_analysis``) exactly once each, then
hands the resulting context to the AI provider. This module reproduces no
financial formula, sensitivity scenario, or break-even search of its own --
it only assembles already-computed results and reads them into
``AnalysisContext``.

One AI Analyst architecture, not two parallel systems: both
``build_analysis_context``/``generate_ai_analysis`` (Quick) and
``build_detailed_analysis_context``/``generate_detailed_ai_analysis``
(Detailed) produce the same ``AnalysisContext`` shape and funnel through the
same ``_generate_from_context`` provider call -- mirroring exactly how the
engine's ``analyze_acquisition``/``analyze_detailed_acquisition`` converge
on one downstream calculation path.
"""

from __future__ import annotations

from ..analysis import (
    ReturnHurdleMetric,
    build_standard_break_even_analysis,
    build_standard_detailed_break_even_analysis,
    build_standard_detailed_presets,
    build_standard_presets,
)
from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
)
from ..engine import analyze_acquisition, analyze_detailed_acquisition_with_projection
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
    """Assemble one deterministic ``AnalysisContext`` for ``inputs`` (Quick
    Underwrite) -- unchanged behavior since Phase 9A, now explicitly
    ``operating_mode=QUICK`` with ``terms``/``detailed_operating_inputs``/
    ``operating_projection`` all ``None``.

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
        operating_mode=OperatingMode.QUICK,
        inputs=inputs,
        terms=None,
        detailed_operating_inputs=None,
        operating_projection=None,
        results=results,
        sensitivities=sensitivities,
        break_even=break_even,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
    )


def build_detailed_analysis_context(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    target_levered_irr: float,
    target_equity_multiple: float,
    target_headline_dscr: float,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
) -> AnalysisContext:
    """Assemble one deterministic ``AnalysisContext`` for ``terms`` +
    ``detailed_operating_inputs`` (Detailed Underwrite), Detailed Operating
    Model V2.1 Gate 9.

    No ``AcquisitionInputs`` is constructed, read, or required anywhere in
    this call -- ``current_noi``/``noi_growth``/``occupancy`` simply do not
    exist in this path, matching the engine-layer Gate 3/4 resolution.
    Calls ``analyze_detailed_acquisition_with_projection`` (which builds
    the Detailed operating projection exactly once and reuses it for both
    the ``operating_projection`` context field and the ``results``
    calculation), ``build_standard_detailed_presets``, and
    ``build_standard_detailed_break_even_analysis`` -- the Detailed
    counterparts of the Quick entry points above -- exactly once each. No
    financial formula, sensitivity scenario, or break-even search is
    reproduced here.
    """

    envelope = analyze_detailed_acquisition_with_projection(terms, detailed_operating_inputs)
    sensitivities = build_standard_detailed_presets(terms, detailed_operating_inputs)
    break_even = build_standard_detailed_break_even_analysis(
        terms,
        detailed_operating_inputs,
        target_levered_irr=target_levered_irr,
        target_headline_dscr=target_headline_dscr,
        target_equity_multiple=target_equity_multiple,
        return_hurdle_metric=return_hurdle_metric,
    )

    return AnalysisContext(
        operating_mode=OperatingMode.DETAILED,
        inputs=None,
        terms=terms,
        detailed_operating_inputs=detailed_operating_inputs,
        operating_projection=envelope.operating_projection,
        results=envelope.results,
        sensitivities=sensitivities,
        break_even=break_even,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
    )


def _generate_from_context(
    context: AnalysisContext, *, provider: OpenAIAnalystProvider | None = None
) -> AIAnalysis:
    """Shared provider call for both modes: build the two prompts from
    ``context`` and return the parsed ``AIAnalysis``. ``provider`` defaults
    to a real ``OpenAIAnalystProvider`` (which lazily reads
    ``OPENAI_API_KEY``/``ANCHOR_AI_MODEL`` only when a call is actually
    made); tests inject a fake provider to avoid any real network call."""

    active_provider = provider if provider is not None else OpenAIAnalystProvider()
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(context)

    return active_provider.generate_analysis(
        system_prompt=system_prompt, user_prompt=user_prompt
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
    """Build the deterministic Quick context for ``inputs`` and return one
    AI Analyst interpretation of it -- unchanged public signature/behavior
    since Phase 9A."""

    context = build_analysis_context(
        inputs,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
    )
    return _generate_from_context(context, provider=provider)


def generate_detailed_ai_analysis(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    target_levered_irr: float,
    target_equity_multiple: float,
    target_headline_dscr: float,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
    provider: OpenAIAnalystProvider | None = None,
) -> AIAnalysis:
    """Build the deterministic Detailed context for ``terms`` +
    ``detailed_operating_inputs`` and return one AI Analyst interpretation
    of it (Detailed Operating Model V2.1 Gate 9)."""

    context = build_detailed_analysis_context(
        terms,
        detailed_operating_inputs,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
    )
    return _generate_from_context(context, provider=provider)
