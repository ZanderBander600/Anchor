"""Tests for the Phase 10A Azure Document Intelligence provider adapter
(``anchor.ingestion.di_provider``).

Every test here uses a fake client object -- never the real ``azure`` SDK
or a network call. Mirrors the style of ``test_ai_provider.py``: injectable
client, missing-configuration behavior, a well-formed response converting
cleanly, and provider/timeout failures never leaking a raw exception.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import pypdf
import pytest

from anchor.ingestion.contracts import (
    ExtractionConfigurationError,
    ExtractionProviderError,
    StructuredDocument,
)
from anchor.ingestion.di_provider import AzureDocumentIntelligenceProvider


# =============================================================================
# Fake Azure DI SDK shapes -- mirror the real DocumentParagraph /
# DocumentTable / DocumentTableCell / BoundingRegion attribute names.
# =============================================================================


@dataclass
class _FakeBoundingRegion:
    page_number: int


@dataclass
class _FakeParagraph:
    content: str
    bounding_regions: list[_FakeBoundingRegion] = field(default_factory=list)


@dataclass
class _FakeCell:
    content: str
    row_index: int
    column_index: int
    bounding_regions: list[_FakeBoundingRegion] = field(default_factory=list)


@dataclass
class _FakeTable:
    cells: list[_FakeCell] = field(default_factory=list)
    bounding_regions: list[_FakeBoundingRegion] = field(default_factory=list)


@dataclass
class _FakeAnalyzeResult:
    paragraphs: list[_FakeParagraph] = field(default_factory=list)
    tables: list[_FakeTable] = field(default_factory=list)


@dataclass
class _FakePoller:
    outcome: Any  # _FakeAnalyzeResult or an Exception instance

    def result(self, timeout: int | None = None) -> Any:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@dataclass
class _FakeClient:
    outcome: Any
    calls: list[dict[str, Any]] = field(default_factory=list)

    def begin_analyze_document(self, model_id: str, *, body: Any) -> _FakePoller:
        self.calls.append({"model_id": model_id, "body": body})
        return _FakePoller(outcome=self.outcome)


WELL_FORMED_RESULT = _FakeAnalyzeResult(
    paragraphs=[
        _FakeParagraph(
            content="Purchase Price: $1,000,000", bounding_regions=[_FakeBoundingRegion(page_number=1)]
        )
    ],
    tables=[
        _FakeTable(
            cells=[
                _FakeCell(
                    content="24",
                    row_index=1,
                    column_index=2,
                    bounding_regions=[_FakeBoundingRegion(page_number=2)],
                )
            ],
            bounding_regions=[_FakeBoundingRegion(page_number=2)],
        )
    ],
)


# =============================================================================
# Missing configuration
# =============================================================================


def test_missing_credentials_raises_configuration_error_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_DOCUMENTINTELLIGENCE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DOCUMENTINTELLIGENCE_KEY", raising=False)
    provider = AzureDocumentIntelligenceProvider()  # no fake client -- must not reach the network

    with pytest.raises(ExtractionConfigurationError):
        provider.analyze(b"%PDF-1.4 ...")


# =============================================================================
# Happy path
# =============================================================================


def test_well_formed_response_converts_to_structured_document() -> None:
    client = _FakeClient(outcome=WELL_FORMED_RESULT)
    provider = AzureDocumentIntelligenceProvider(client=client)

    document = provider.analyze(b"%PDF-1.4 ...")

    assert isinstance(document, StructuredDocument)
    anchors_by_id = {anchor.anchor: anchor for anchor in document.anchors}
    assert anchors_by_id["paragraph:0"].text == "Purchase Price: $1,000,000"
    assert anchors_by_id["paragraph:0"].page == 1
    assert anchors_by_id["table:0:cell:1:2"].text == "24"
    assert anchors_by_id["table:0:cell:1:2"].page == 2


def test_analyze_calls_prebuilt_layout_with_no_features() -> None:
    client = _FakeClient(outcome=WELL_FORMED_RESULT)
    provider = AzureDocumentIntelligenceProvider(client=client)

    provider.analyze(b"%PDF-1.4 ...")

    call = client.calls[0]
    assert call["model_id"] == "prebuilt-layout"
    assert "features" not in call


def test_calling_analyze_twice_calls_the_client_twice() -> None:
    client = _FakeClient(outcome=WELL_FORMED_RESULT)
    provider = AzureDocumentIntelligenceProvider(client=client)

    provider.analyze(b"%PDF-1.4 ...")
    provider.analyze(b"%PDF-1.4 ...")

    assert len(client.calls) == 2


# =============================================================================
# Malformed / empty response
# =============================================================================


def test_empty_result_raises_provider_error() -> None:
    client = _FakeClient(outcome=_FakeAnalyzeResult(paragraphs=[], tables=[]))
    provider = AzureDocumentIntelligenceProvider(client=client)

    with pytest.raises(ExtractionProviderError):
        provider.analyze(b"%PDF-1.4 ...")


# =============================================================================
# Underlying client exception / timeout
# =============================================================================


def test_underlying_client_exception_raises_provider_error_not_raw_exception() -> None:
    client = _FakeClient(outcome=RuntimeError("secret internal detail"))
    provider = AzureDocumentIntelligenceProvider(client=client)

    with pytest.raises(ExtractionProviderError) as exc_info:
        provider.analyze(b"%PDF-1.4 ...")

    assert "secret internal detail" not in str(exc_info.value)


def test_poller_timeout_raises_provider_error_not_an_unhandled_hang() -> None:
    client = _FakeClient(outcome=TimeoutError("poller exceeded 90s"))
    provider = AzureDocumentIntelligenceProvider(client=client)

    with pytest.raises(ExtractionProviderError) as exc_info:
        provider.analyze(b"%PDF-1.4 ...")

    assert "poller exceeded 90s" not in str(exc_info.value)


# =============================================================================
# Provider-side page-completeness guard: Azure DI (notably the free F0
# tier) can silently process only a prefix of the uploaded PDF, returning a
# normal, warning-free response for the pages it did process. Never let
# that read as "the rest of the document had no evidence" (fields silently
# reported missing) -- fail extraction explicitly instead. ``pdf_bytes``
# here are real, pypdf-openable PDFs (via ``pypdf.PdfWriter``) so the
# source-page-count comparison actually engages; every other test in this
# file intentionally uses non-parseable placeholder bytes so that
# comparison is skipped (see ``_source_page_count``'s None fallback).
# =============================================================================


def _pdf_bytes(page_count: int) -> bytes:
    writer = pypdf.PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _paragraph_on_page(page_number: int) -> _FakeParagraph:
    return _FakeParagraph(
        content=f"Content on page {page_number}",
        bounding_regions=[_FakeBoundingRegion(page_number=page_number)],
    )


def test_all_source_pages_processed_by_azure_passes() -> None:
    client = _FakeClient(
        outcome=_FakeAnalyzeResult(paragraphs=[_paragraph_on_page(p) for p in range(1, 9)])
    )
    provider = AzureDocumentIntelligenceProvider(client=client)

    document = provider.analyze(_pdf_bytes(8))

    assert isinstance(document, StructuredDocument)
    assert {anchor.page for anchor in document.anchors} == set(range(1, 9))


def test_azure_silently_truncating_an_8_page_pdf_to_2_pages_fails_explicitly() -> None:
    """The exact live-bug shape: an 8-page source PDF, Azure DI (F0 tier)
    only returns evidence for pages 1-2. This must fail extraction outright
    -- never be reported as pages 3-8's fields simply being ``missing``."""

    client = _FakeClient(
        outcome=_FakeAnalyzeResult(paragraphs=[_paragraph_on_page(1), _paragraph_on_page(2)])
    )
    provider = AzureDocumentIntelligenceProvider(client=client)

    with pytest.raises(ExtractionProviderError) as exc_info:
        provider.analyze(_pdf_bytes(8))

    message = str(exc_info.value)
    assert "2" in message and "8" in message


def test_single_page_pdf_fully_processed_by_azure_passes() -> None:
    client = _FakeClient(outcome=_FakeAnalyzeResult(paragraphs=[_paragraph_on_page(1)]))
    provider = AzureDocumentIntelligenceProvider(client=client)

    document = provider.analyze(_pdf_bytes(1))

    assert isinstance(document, StructuredDocument)
    assert {anchor.page for anchor in document.anchors} == {1}


def test_non_pdf_bytes_skip_the_completeness_check_rather_than_failing() -> None:
    """``pdf_bytes`` this module cannot open locally (as every other test
    in this file uses) must not turn into a spurious completeness failure
    -- by the time a real upload reaches this provider, KTD9 has already
    confirmed the file opens as a PDF; this check is defense-in-depth on
    top of that, not the PDF's validity gate."""

    client = _FakeClient(outcome=WELL_FORMED_RESULT)
    provider = AzureDocumentIntelligenceProvider(client=client)

    document = provider.analyze(b"%PDF-1.4 ...")

    assert isinstance(document, StructuredDocument)
