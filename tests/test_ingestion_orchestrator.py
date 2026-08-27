"""Tests for the Phase 10A OM ingestion orchestrator
(``mini_anchor.ingestion.orchestrator``).

Mirrors ``test_ai_analyst``-style orchestration tests: fake providers only
(never a real Azure/OpenAI call), asserting each provider is called exactly
once, in order, with only the previous provider's return value (never the
raw PDF bytes), and that either provider's typed error propagates
unchanged.
"""

from __future__ import annotations

import pickle

import pytest

from mini_anchor.ingestion.contracts import (
    DealContext,
    DocumentAnchor,
    EvidenceStatus,
    ExtractionCandidate,
    ExtractionConfigurationError,
    ExtractionProviderError,
    ExtractionResult,
    FieldCandidates,
    Provenance,
    StructuredDocument,
)
from mini_anchor.ingestion.orchestrator import extract_om

DOCUMENT = StructuredDocument(
    anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $1,000,000"),)
)


def _missing_field(field_id: str) -> FieldCandidates:
    return FieldCandidates(field_id=field_id)


def _stated_purchase_price() -> ExtractionResult:
    candidate = ExtractionCandidate(
        value="1000000",
        status=EvidenceStatus.STATED,
        provenance=Provenance(page=1, anchor="paragraph:0", snippet="Purchase Price: $1,000,000"),
    )
    fields = {
        "purchase_price": FieldCandidates(field_id="purchase_price", candidates=(candidate,)),
        "current_noi": _missing_field("current_noi"),
        "occupancy": _missing_field("occupancy"),
        "noi_growth": _missing_field("noi_growth"),
        "hold_period": _missing_field("hold_period"),
        "exit_cap_rate": _missing_field("exit_cap_rate"),
        "ltv": _missing_field("ltv"),
        "interest_rate": _missing_field("interest_rate"),
        "amortization": _missing_field("amortization"),
    }
    deal_context = DealContext(
        property_name=_missing_field("property_name"),
        address=_missing_field("address"),
        property_type=_missing_field("property_type"),
        unit_count_or_building_area=_missing_field("unit_count_or_building_area"),
        year_built=_missing_field("year_built"),
    )
    return ExtractionResult(**fields, deal_context=deal_context)


class _FakeDiProvider:
    def __init__(self, *, document: StructuredDocument = DOCUMENT) -> None:
        self.calls: list[bytes] = []
        self._document = document

    def analyze(self, pdf_bytes: bytes) -> StructuredDocument:
        self.calls.append(pdf_bytes)
        return self._document


class _FailingDiProvider:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def analyze(self, pdf_bytes: bytes) -> StructuredDocument:
        raise self._error


class _FakeClassifierProvider:
    def __init__(self, *, result: ExtractionResult | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._result = result if result is not None else _stated_purchase_price()

    def classify(self, *, system_prompt: str, user_prompt: str, document: StructuredDocument) -> ExtractionResult:
        self.calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "document": document}
        )
        return self._result


class _FailingClassifierProvider:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def classify(self, *, system_prompt: str, user_prompt: str, document: StructuredDocument) -> ExtractionResult:
        raise self._error


# =============================================================================
# Happy path -- each provider called exactly once, in order
# =============================================================================


def test_extract_om_calls_di_then_classifier_exactly_once_each() -> None:
    di_provider = _FakeDiProvider()
    classifier_provider = _FakeClassifierProvider()

    result = extract_om(
        b"%PDF-1.4 fake bytes",
        di_provider=di_provider,
        classifier_provider=classifier_provider,
    )

    assert len(di_provider.calls) == 1
    assert len(classifier_provider.calls) == 1
    assert isinstance(result, ExtractionResult)


def test_extract_om_passes_di_bytes_to_di_provider() -> None:
    di_provider = _FakeDiProvider()
    classifier_provider = _FakeClassifierProvider()

    extract_om(b"the pdf bytes", di_provider=di_provider, classifier_provider=classifier_provider)

    assert di_provider.calls == [b"the pdf bytes"]


def test_extract_om_passes_only_the_di_providers_return_value_to_the_classifier() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="unique marker text"),)
    )
    di_provider = _FakeDiProvider(document=document)
    classifier_provider = _FakeClassifierProvider()

    extract_om(b"%PDF-1.4 fake bytes", di_provider=di_provider, classifier_provider=classifier_provider)

    assert classifier_provider.calls[0]["document"] is document


def test_extract_om_returns_the_classifiers_composed_result() -> None:
    di_provider = _FakeDiProvider()
    expected = _stated_purchase_price()
    classifier_provider = _FakeClassifierProvider(result=expected)

    result = extract_om(
        b"%PDF-1.4 fake bytes", di_provider=di_provider, classifier_provider=classifier_provider
    )

    assert result is expected


# =============================================================================
# R13 -- the raw PDF bytes are never retained on/reachable from the result
# =============================================================================


def test_pdf_bytes_are_not_reachable_from_the_returned_extraction_result() -> None:
    pdf_bytes = b"%PDF-1.4 a very specific unique marker payload 12345"
    di_provider = _FakeDiProvider()
    classifier_provider = _FakeClassifierProvider()

    result = extract_om(pdf_bytes, di_provider=di_provider, classifier_provider=classifier_provider)

    serialized = pickle.dumps(result)
    assert pdf_bytes not in serialized


# =============================================================================
# Error propagation (R16) -- neither provider's typed error is swallowed
# =============================================================================


def test_di_configuration_error_propagates_unchanged() -> None:
    di_provider = _FailingDiProvider(ExtractionConfigurationError("Azure DI not configured."))
    classifier_provider = _FakeClassifierProvider()

    with pytest.raises(ExtractionConfigurationError):
        extract_om(b"%PDF-1.4", di_provider=di_provider, classifier_provider=classifier_provider)


def test_di_provider_error_propagates_unchanged() -> None:
    di_provider = _FailingDiProvider(ExtractionProviderError("Azure DI call failed."))
    classifier_provider = _FakeClassifierProvider()

    with pytest.raises(ExtractionProviderError):
        extract_om(b"%PDF-1.4", di_provider=di_provider, classifier_provider=classifier_provider)


def test_classifier_configuration_error_propagates_unchanged() -> None:
    di_provider = _FakeDiProvider()
    classifier_provider = _FailingClassifierProvider(
        ExtractionConfigurationError("OpenAI not configured.")
    )

    with pytest.raises(ExtractionConfigurationError):
        extract_om(b"%PDF-1.4", di_provider=di_provider, classifier_provider=classifier_provider)


def test_classifier_provider_error_propagates_unchanged() -> None:
    di_provider = _FakeDiProvider()
    classifier_provider = _FailingClassifierProvider(ExtractionProviderError("Classifier call failed."))

    with pytest.raises(ExtractionProviderError):
        extract_om(b"%PDF-1.4", di_provider=di_provider, classifier_provider=classifier_provider)


def test_di_failure_prevents_the_classifier_from_being_called() -> None:
    di_provider = _FailingDiProvider(ExtractionProviderError("Azure DI call failed."))
    classifier_provider = _FakeClassifierProvider()

    with pytest.raises(ExtractionProviderError):
        extract_om(b"%PDF-1.4", di_provider=di_provider, classifier_provider=classifier_provider)

    assert classifier_provider.calls == []
