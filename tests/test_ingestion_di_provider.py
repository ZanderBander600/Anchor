"""Tests for the Phase 10A Azure Document Intelligence provider adapter
(``mini_anchor.ingestion.di_provider``).

Every test here uses a fake client object -- never the real ``azure`` SDK
or a network call. Mirrors the style of ``test_ai_provider.py``: injectable
client, missing-configuration behavior, a well-formed response converting
cleanly, and provider/timeout failures never leaking a raw exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from mini_anchor.ingestion.contracts import (
    ExtractionConfigurationError,
    ExtractionProviderError,
    StructuredDocument,
)
from mini_anchor.ingestion.di_provider import AzureDocumentIntelligenceProvider


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
