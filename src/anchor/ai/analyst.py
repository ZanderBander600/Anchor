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

D5.8 adds the third arm, ``build_lease_level_analysis_context``/
``generate_lease_level_ai_analysis``, into that same shape and that same
provider call. It is the one arm that runs **no** analysis of its own: it
receives the already-computed ``LeaseLevelAcquisitionResults`` the product
flow produced, so the AI Analyst always interprets the exact analysis the
analyst approved rather than a second run of its own. It calls no sensitivity
preset builder and no break-even search either -- Lease-Level has neither, and
inventing one at AI time is precisely what this module exists not to do.

Phase 6 Gate D6.4 threads the deal's Business Plan, mechanically, through the
Quick and Detailed arms: the base analysis runs through the mode's D6 Business
Plan entry point, and the same plan reaches the preset bundle and the
break-even bundle, so every number in the context carries the same plan.
``BusinessPlan()`` is the default for callers that supply none. What the AI is
told about the plan is D6.8's; nothing here changes the prompt.
"""

from __future__ import annotations

from ..analysis import (
    LeaseLevelAcquisitionResults,
    ParsedLeaseLevelInputs,
    ReturnHurdleMetric,
    analyze_detailed_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
    build_standard_break_even_analysis,
    build_standard_detailed_break_even_analysis,
    build_standard_detailed_presets,
    build_standard_presets,
)
from ..business_plan import BusinessPlan
from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
)
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
    deal_context: str | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
) -> AnalysisContext:
    """Assemble one deterministic ``AnalysisContext`` for ``inputs`` (Quick
    Underwrite) -- unchanged behavior since Phase 9A, now explicitly
    ``operating_mode=QUICK`` with ``terms``/``detailed_operating_inputs``/
    ``operating_projection`` all ``None``.

    Calls ``analyze_quick_acquisition_with_business_plan``,
    ``build_standard_presets``, and ``build_standard_break_even_analysis``
    -- the same authoritative analysis entry points the ``/analyze``,
    ``/sensitivity/presets``, and ``/break-even`` endpoints use -- exactly
    once each, each with the same ``business_plan`` (D6.4), and reads their
    results directly into the context. No financial formula, sensitivity
    scenario, or break-even search is reproduced here.
    """

    results = analyze_quick_acquisition_with_business_plan(
        inputs, business_plan=business_plan
    )
    sensitivities = build_standard_presets(inputs, business_plan=business_plan)
    break_even = build_standard_break_even_analysis(
        inputs,
        target_levered_irr=target_levered_irr,
        target_headline_dscr=target_headline_dscr,
        target_equity_multiple=target_equity_multiple,
        return_hurdle_metric=return_hurdle_metric,
        business_plan=business_plan,
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
        deal_context=deal_context,
    )


def build_detailed_analysis_context(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    target_levered_irr: float,
    target_equity_multiple: float,
    target_headline_dscr: float,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
    deal_context: str | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
) -> AnalysisContext:
    """Assemble one deterministic ``AnalysisContext`` for ``terms`` +
    ``detailed_operating_inputs`` (Detailed Underwrite), Detailed Operating
    Model V2.1 Gate 9.

    No ``AcquisitionInputs`` is constructed, read, or required anywhere in
    this call -- ``current_noi``/``noi_growth``/``occupancy`` simply do not
    exist in this path, matching the engine-layer Gate 3/4 resolution.
    Calls ``analyze_detailed_acquisition_with_business_plan`` (which builds
    the Detailed operating projection exactly once and reuses it for both
    the ``operating_projection`` context field and the ``results``
    calculation), ``build_standard_detailed_presets``, and
    ``build_standard_detailed_break_even_analysis`` -- the Detailed
    counterparts of the Quick entry points above -- exactly once each, each
    with the same ``business_plan`` (D6.4). No financial formula,
    sensitivity scenario, or break-even search is reproduced here.
    """

    envelope = analyze_detailed_acquisition_with_business_plan(
        terms, detailed_operating_inputs, business_plan=business_plan
    )
    sensitivities = build_standard_detailed_presets(
        terms, detailed_operating_inputs, business_plan=business_plan
    )
    break_even = build_standard_detailed_break_even_analysis(
        terms,
        detailed_operating_inputs,
        target_levered_irr=target_levered_irr,
        target_headline_dscr=target_headline_dscr,
        target_equity_multiple=target_equity_multiple,
        return_hurdle_metric=return_hurdle_metric,
        business_plan=business_plan,
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
        deal_context=deal_context,
    )


def build_lease_level_analysis_context(
    terms: AcquisitionTerms,
    lease_level_inputs: ParsedLeaseLevelInputs,
    lease_level_results: LeaseLevelAcquisitionResults,
    *,
    target_levered_irr: float,
    target_equity_multiple: float,
    target_headline_dscr: float,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
    deal_context: str | None = None,
) -> AnalysisContext:
    """Assemble one deterministic ``AnalysisContext`` for a Lease-Level deal
    (D5.8).

    **This function runs no analysis.** It differs from its two siblings above
    in exactly that way, and deliberately: ``lease_level_results`` is supplied
    by the caller, already computed by
    ``analyze_lease_level_acquisition_with_projection`` through the product
    flow the analyst drove. Calling the analysis again here would re-underwrite
    the deal at AI time -- a second run that could disagree with the one on the
    analyst's screen, for no benefit. Quick and Detailed call their engine
    entry points because their contexts also need a preset bundle and a
    break-even search, neither of which exists for this mode.

    For the same reason **nothing is triggered on the side**: no sensitivity
    preset call, no break-even search, no alternate scenario. ``sensitivities``
    and ``break_even`` are ``None``, and the presentation layer says what each
    absence means rather than leaving the model to guess.

    ``results`` is passed as ``lease_level_results.results`` -- the identical
    object, not a copy -- which ``AnalysisContext`` asserts.
    """

    return AnalysisContext(
        operating_mode=OperatingMode.LEASE_LEVEL,
        inputs=None,
        terms=terms,
        detailed_operating_inputs=None,
        operating_projection=None,
        lease_level_inputs=lease_level_inputs,
        lease_level_results=lease_level_results,
        results=lease_level_results.results,
        sensitivities=None,
        break_even=None,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
        deal_context=deal_context,
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
    deal_context: str | None = None,
    provider: OpenAIAnalystProvider | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
) -> AIAnalysis:
    """Build the deterministic Quick context for ``inputs`` and return one
    AI Analyst interpretation of it -- unchanged public signature/behavior
    since Phase 9A, plus the optional Gate A4 ``deal_context`` passthrough
    and the D6.4 ``business_plan`` passthrough."""

    context = build_analysis_context(
        inputs,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
        deal_context=deal_context,
        business_plan=business_plan,
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
    deal_context: str | None = None,
    provider: OpenAIAnalystProvider | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
) -> AIAnalysis:
    """Build the deterministic Detailed context for ``terms`` +
    ``detailed_operating_inputs`` and return one AI Analyst interpretation
    of it (Detailed Operating Model V2.1 Gate 9), plus the optional Gate A4
    ``deal_context`` passthrough and the D6.4 ``business_plan``
    passthrough."""

    context = build_detailed_analysis_context(
        terms,
        detailed_operating_inputs,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
        deal_context=deal_context,
        business_plan=business_plan,
    )
    return _generate_from_context(context, provider=provider)


def generate_lease_level_ai_analysis(
    terms: AcquisitionTerms,
    lease_level_inputs: ParsedLeaseLevelInputs,
    lease_level_results: LeaseLevelAcquisitionResults,
    *,
    target_levered_irr: float,
    target_equity_multiple: float,
    target_headline_dscr: float,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
    deal_context: str | None = None,
    provider: OpenAIAnalystProvider | None = None,
) -> AIAnalysis:
    """Build the deterministic Lease-Level context and return one AI Analyst
    interpretation of it (D5.8).

    The third arm of one AI Analyst architecture, not a second AI product: the
    same ``AnalysisContext``, the same ``_generate_from_context`` provider call
    and the same ``AIAnalysis`` back. It takes the already-computed
    ``lease_level_results`` rather than a set of inputs to underwrite, so the
    interpretation is always of the analysis the analyst approved.
    """

    context = build_lease_level_analysis_context(
        terms,
        lease_level_inputs,
        lease_level_results,
        target_levered_irr=target_levered_irr,
        target_equity_multiple=target_equity_multiple,
        target_headline_dscr=target_headline_dscr,
        return_hurdle_metric=return_hurdle_metric,
        deal_context=deal_context,
    )
    return _generate_from_context(context, provider=provider)
