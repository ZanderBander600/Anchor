"""Phase 10A OM ingestion orchestration.

Assembles one ``ExtractionResult`` per uploaded OM by calling the Azure DI
provider once, then the GPT classifier provider once with only Azure DI's
own structured return (never the raw PDF bytes -- KD1). This module
reproduces no extraction, classification, or verification logic of its
own; it only sequences the two provider calls this package already
defines and returns their composed result. ``pdf_bytes`` is never stored on
any returned object or module-level state (R13) -- it exists only as a
local call argument for the duration of this function.
"""

from __future__ import annotations

from .classifier_provider import GPTClassifierProvider
from .contracts import DetailedExtractionResult, ExtractionResult
from .di_provider import AzureDocumentIntelligenceProvider
from .prompts import (
    build_detailed_system_prompt,
    build_detailed_user_prompt,
    build_system_prompt,
    build_user_prompt,
)


def extract_om(
    pdf_bytes: bytes,
    *,
    di_provider: AzureDocumentIntelligenceProvider | None = None,
    classifier_provider: GPTClassifierProvider | None = None,
) -> ExtractionResult:
    """Extract and classify one uploaded OM PDF into an ``ExtractionResult``.

    Calls ``di_provider.analyze`` exactly once with ``pdf_bytes``, then
    ``classifier_provider.classify`` exactly once with the resulting
    ``StructuredDocument`` -- never with ``pdf_bytes`` itself (KD1/R3/R4).

    ``di_provider``/``classifier_provider`` default to real providers
    (which lazily read their respective credentials only when a call is
    actually made); tests inject fakes to avoid any real network call.
    Either provider's ``ExtractionConfigurationError``/
    ``ExtractionProviderError`` propagates unchanged -- this function never
    swallows or re-wraps it (R16).
    """

    active_di_provider = di_provider if di_provider is not None else AzureDocumentIntelligenceProvider()
    active_classifier_provider = (
        classifier_provider if classifier_provider is not None else GPTClassifierProvider()
    )

    document = active_di_provider.analyze(pdf_bytes)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(document)

    return active_classifier_provider.classify(
        system_prompt=system_prompt, user_prompt=user_prompt, document=document
    )


def extract_detailed_om(
    pdf_bytes: bytes,
    *,
    di_provider: AzureDocumentIntelligenceProvider | None = None,
    classifier_provider: GPTClassifierProvider | None = None,
) -> DetailedExtractionResult:
    """Detailed Operating Model V2.1 Gate 12: the Detailed counterpart to
    ``extract_om`` -- identical sequencing (Azure DI exactly once, then the
    GPT classifier exactly once with only the resulting ``StructuredDocument``,
    never ``pdf_bytes`` itself) and the same default/injectable provider
    pattern, over the Detailed prompts/schema and returning
    ``DetailedExtractionResult`` instead. Reuses
    ``AzureDocumentIntelligenceProvider`` completely unchanged -- Azure DI's
    layout extraction has no notion of Quick or Detailed fields at all.
    """

    active_di_provider = di_provider if di_provider is not None else AzureDocumentIntelligenceProvider()
    active_classifier_provider = (
        classifier_provider if classifier_provider is not None else GPTClassifierProvider()
    )

    document = active_di_provider.analyze(pdf_bytes)

    system_prompt = build_detailed_system_prompt()
    user_prompt = build_detailed_user_prompt(document)

    return active_classifier_provider.classify_detailed(
        system_prompt=system_prompt, user_prompt=user_prompt, document=document
    )
