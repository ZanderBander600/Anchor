"""Phase 10A Azure Document Intelligence provider adapter.

The only module in this package (and the only module in Mini-Anchor) that
imports the ``azure`` SDK or talks to the Azure Document Intelligence
service. Isolated here so a different OCR/layout provider could be
introduced later without touching ``mini_anchor.ingestion.orchestrator`` or
``mini_anchor.ingestion.classifier_provider``. This module performs no
semantic field classification of its own: it only calls Azure DI's
``prebuilt-layout`` model (KTD3 -- layout only, never key-value-pairs) and
flattens the response to a ``StructuredDocument`` of anchor-addressable
paragraphs and table cells.
"""

from __future__ import annotations

import os
from typing import Any

from .contracts import (
    DocumentAnchor,
    ExtractionConfigurationError,
    ExtractionProviderError,
    StructuredDocument,
)

_ENDPOINT_ENV_VAR = "AZURE_DOCUMENTINTELLIGENCE_ENDPOINT"
_KEY_ENV_VAR = "AZURE_DOCUMENTINTELLIGENCE_KEY"
_POLLER_TIMEOUT_SECONDS = 90  # KTD11: bounds the shared-threadpool occupancy (KTD2).


def _resolve_credentials() -> tuple[str, str]:
    endpoint = os.environ.get(_ENDPOINT_ENV_VAR)
    key = os.environ.get(_KEY_ENV_VAR)
    if not endpoint or not key:
        raise ExtractionConfigurationError(
            f"{_ENDPOINT_ENV_VAR} and {_KEY_ENV_VAR} must both be configured. "
            "Set them in the process environment before requesting extraction."
        )
    return endpoint, key


def _page_number(bounding_regions: Any) -> int:
    if bounding_regions:
        first_region = bounding_regions[0]
        page_number = getattr(first_region, "page_number", None)
        if isinstance(page_number, int):
            return page_number
    return 1


def _build_structured_document(result: Any) -> StructuredDocument:
    """Flatten an Azure DI ``AnalyzeResult``-shaped ``result`` (real SDK
    object or an injected fake with the same paragraph/table shape) into a
    ``StructuredDocument`` of anchor-addressable text.

    Assigns every anchor id deterministically from the response's own
    ordering -- ``paragraph:<i>`` for the i-th paragraph, ``table:<t>:cell:
    <row>:<col>`` for one cell of the t-th table -- so a classifier
    candidate's citation can be resolved by a direct anchor lookup (R6/
    KTD12), never a second model call.
    """

    anchors: list[DocumentAnchor] = []

    paragraphs = getattr(result, "paragraphs", None) or []
    for index, paragraph in enumerate(paragraphs):
        content = getattr(paragraph, "content", None)
        if not content:
            continue
        anchors.append(
            DocumentAnchor(
                anchor=f"paragraph:{index}",
                page=_page_number(getattr(paragraph, "bounding_regions", None)),
                text=content,
            )
        )

    tables = getattr(result, "tables", None) or []
    for table_index, table in enumerate(tables):
        cells = getattr(table, "cells", None) or []
        for cell in cells:
            content = getattr(cell, "content", None)
            if not content:
                continue
            row_index = getattr(cell, "row_index", None)
            column_index = getattr(cell, "column_index", None)
            bounding_regions = getattr(cell, "bounding_regions", None) or getattr(
                table, "bounding_regions", None
            )
            anchors.append(
                DocumentAnchor(
                    anchor=f"table:{table_index}:cell:{row_index}:{column_index}",
                    page=_page_number(bounding_regions),
                    text=content,
                )
            )

    if not anchors:
        raise ExtractionProviderError(
            "The Azure Document Intelligence response contained no extractable "
            "paragraphs or tables."
        )

    return StructuredDocument(anchors=tuple(anchors))


class AzureDocumentIntelligenceProvider:
    """Thin adapter over Azure DI's ``prebuilt-layout`` model.

    Isolates every Azure-specific detail (client construction, the
    long-running-operation poller, response flattening) behind one
    ``analyze`` method. A test may pass a fake ``client`` (any object
    exposing ``.begin_analyze_document(...)`` whose poller's ``.result()``
    returns an object with ``.paragraphs``/``.tables``) to exercise this
    class without making a real network call.
    """

    def __init__(self, *, client: Any = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        endpoint, key = _resolve_credentials()
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential

        self._client = DocumentIntelligenceClient(
            endpoint=endpoint, credential=AzureKeyCredential(key)
        )
        return self._client

    def analyze(self, pdf_bytes: bytes) -> StructuredDocument:
        """Call ``prebuilt-layout`` once against ``pdf_bytes`` (KTD3 -- no
        ``features``, i.e. no key-value-pairs) and return the flattened
        ``StructuredDocument``.

        Raises ``ExtractionConfigurationError`` if Azure DI credentials are
        not configured (no call attempted), or ``ExtractionProviderError``
        if the call fails, times out, or returns an unusable response. The
        error message is always sanitized -- never the raw SDK exception
        text.
        """

        client = self._get_client()

        try:
            from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

            poller = client.begin_analyze_document(
                "prebuilt-layout",
                body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
            )
            result = poller.result(timeout=_POLLER_TIMEOUT_SECONDS)
        except ExtractionProviderError:
            raise
        except Exception as error:
            raise ExtractionProviderError(
                f"The Azure Document Intelligence request failed ({error.__class__.__name__})."
            ) from error

        return _build_structured_document(result)
