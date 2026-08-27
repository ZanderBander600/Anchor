"""Tests for the Phase 10A OM ingestion endpoint (``POST /ingestion/om``)
in ``mini_anchor.api``.

Mirrors ``test_api_ai_analysis.py``'s style. No test in this module makes
a real Azure DI or OpenAI call: ``mini_anchor.api.extract_om`` is always
patched, either directly (for the endpoint's own upload-validation and
error-mapping contract) or left unpatched only where the assertion is
specifically that it is *never called* (e.g. a rejected upload).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mini_anchor.api import _IngestionUploadSizeGuard, app
from mini_anchor.ingestion.contracts import (
    DealContext,
    EvidenceStatus,
    ExtractionCandidate,
    ExtractionConfigurationError,
    ExtractionProviderError,
    ExtractionResult,
    FieldCandidates,
    Provenance,
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# =============================================================================
# Fixtures: a minimal, valid, hand-built PDF (no external PDF-generation
# dependency needed) and a fixture ExtractionResult with one stated, one
# missing, and one conflicting field (AE1/AE2/AE3).
# =============================================================================


def _build_minimal_pdf(page_count: int = 1) -> bytes:
    kids = " ".join(f"{3 + i} 0 R" for i in range(page_count))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode(),
    ]
    objects.extend(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>" for _ in range(page_count)
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    object_count = len(objects) + 1
    out += f"xref\n0 {object_count}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += b"trailer\n"
    out += f"<< /Size {object_count} /Root 1 0 R >>\n".encode()
    out += b"startxref\n"
    out += f"{xref_offset}\n".encode()
    out += b"%%EOF"
    return bytes(out)


def _missing(field_id: str) -> FieldCandidates:
    return FieldCandidates(field_id=field_id)


def _fixture_extraction_result() -> ExtractionResult:
    stated = FieldCandidates(
        field_id="purchase_price",
        candidates=(
            ExtractionCandidate(
                value="1000000",
                status=EvidenceStatus.STATED,
                provenance=Provenance(page=1, anchor="paragraph:0", snippet="$1,000,000"),
            ),
        ),
    )
    conflicting = FieldCandidates(
        field_id="current_noi",
        candidates=(
            ExtractionCandidate(
                value="75000",
                status=EvidenceStatus.CONFLICTING,
                provenance=Provenance(page=1, anchor="paragraph:1", snippet="NOI: $75,000"),
            ),
            ExtractionCandidate(
                value="80000",
                status=EvidenceStatus.CONFLICTING,
                provenance=Provenance(page=2, anchor="paragraph:2", snippet="NOI: $80,000"),
            ),
        ),
    )
    fields = {
        "purchase_price": stated,
        "current_noi": conflicting,
        "occupancy": _missing("occupancy"),
        "noi_growth": _missing("noi_growth"),
        "hold_period": _missing("hold_period"),
        "exit_cap_rate": _missing("exit_cap_rate"),
        "ltv": _missing("ltv"),
        "interest_rate": _missing("interest_rate"),
        "amortization": _missing("amortization"),
    }
    deal_context = DealContext(
        property_name=_missing("property_name"),
        address=_missing("address"),
        property_type=_missing("property_type"),
        unit_count_or_building_area=_missing("unit_count_or_building_area"),
        year_built=_missing("year_built"),
    )
    return ExtractionResult(**fields, deal_context=deal_context)


VALID_PDF_BYTES = _build_minimal_pdf()
VALID_EXTRACTION_RESULT = _fixture_extraction_result()


def _upload_files(content: bytes, content_type: str = "application/pdf") -> dict[str, Any]:
    return {"file": ("om.pdf", content, content_type)}


# =============================================================================
# Happy path (AE1/AE2/AE3)
# =============================================================================


def test_valid_upload_returns_200_with_candidates_json(client: TestClient) -> None:
    with patch("mini_anchor.api.extract_om", return_value=VALID_EXTRACTION_RESULT) as mock_extract:
        response = client.post(
            "/ingestion/om", files=_upload_files(VALID_PDF_BYTES)
        )

    assert response.status_code == 200
    mock_extract.assert_called_once()
    body = response.json()
    assert body["purchase_price"]["candidates"][0]["status"] == "stated"
    assert body["occupancy"]["candidates"] == []
    assert len(body["current_noi"]["candidates"]) == 2
    assert all(c["status"] == "conflicting" for c in body["current_noi"]["candidates"])


def test_extract_om_is_called_with_the_uploaded_pdf_bytes(client: TestClient) -> None:
    with patch("mini_anchor.api.extract_om", return_value=VALID_EXTRACTION_RESULT) as mock_extract:
        client.post("/ingestion/om", files=_upload_files(VALID_PDF_BYTES))

    mock_extract.assert_called_once_with(VALID_PDF_BYTES)


# =============================================================================
# Upload validation -- content-type / signature (KTD9)
# =============================================================================


def test_non_pdf_content_type_is_rejected_without_a_provider_call(client: TestClient) -> None:
    with patch("mini_anchor.api.extract_om") as mock_extract:
        response = client.post(
            "/ingestion/om",
            files={"file": ("om.txt", b"just some text", "text/plain")},
        )

    assert 400 <= response.status_code < 500
    mock_extract.assert_not_called()


def test_spoofed_content_type_on_non_pdf_bytes_is_rejected_without_a_provider_call(
    client: TestClient,
) -> None:
    with patch("mini_anchor.api.extract_om") as mock_extract:
        response = client.post(
            "/ingestion/om",
            files={"file": ("om.pdf", b"this is not a pdf at all", "application/pdf")},
        )

    assert 400 <= response.status_code < 500
    mock_extract.assert_not_called()


# =============================================================================
# Upload validation -- size ceiling (KTD9)
# =============================================================================


def test_body_exceeding_the_size_ceiling_is_rejected_without_a_provider_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mini_anchor.api._MAX_UPLOAD_BYTES", 10)

    with patch("mini_anchor.api.extract_om") as mock_extract:
        response = client.post("/ingestion/om", files=_upload_files(VALID_PDF_BYTES))

    assert 400 <= response.status_code < 500
    mock_extract.assert_not_called()


def test_upload_size_guard_rejects_an_oversized_declared_content_length() -> None:
    """Unit-tests the ASGI middleware directly (KTD9(b)): httpx/TestClient
    recomputes Content-Length from the actual body, so a spoofed larger
    declared size can't be driven through the HTTP client -- this exercises
    the guard's own logic against a raw ASGI scope instead."""

    downstream_calls: list[dict[str, Any]] = []

    async def downstream_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        downstream_calls.append(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    guard = _IngestionUploadSizeGuard(downstream_app, path="/ingestion/om", max_bytes=10)

    sent_messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/ingestion/om",
        "headers": [(b"content-length", b"999999")],
    }

    asyncio.run(guard(scope, receive, send))

    assert downstream_calls == []
    start_message = next(m for m in sent_messages if m["type"] == "http.response.start")
    assert start_message["status"] == 413


def test_upload_size_guard_passes_through_a_request_within_the_ceiling() -> None:
    downstream_calls: list[dict[str, Any]] = []

    async def downstream_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        downstream_calls.append(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    guard = _IngestionUploadSizeGuard(downstream_app, path="/ingestion/om", max_bytes=1000)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        pass

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/ingestion/om",
        "headers": [(b"content-length", b"100")],
    }

    asyncio.run(guard(scope, receive, send))

    assert len(downstream_calls) == 1


# =============================================================================
# Upload validation -- page count ceiling (KTD9)
# =============================================================================


def test_pdf_over_the_page_ceiling_is_rejected_without_a_provider_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mini_anchor.api._MAX_UPLOAD_PAGES", 1)
    two_page_pdf = _build_minimal_pdf(page_count=2)

    with patch("mini_anchor.api.extract_om") as mock_extract:
        response = client.post("/ingestion/om", files=_upload_files(two_page_pdf))

    assert 400 <= response.status_code < 500
    mock_extract.assert_not_called()


def test_unopenable_pdf_bytes_are_rejected_as_400_not_500(client: TestClient) -> None:
    garbage = b"%PDF-1.4\nthis is not a real pdf body structure at all\n%%EOF"

    with patch("mini_anchor.api.extract_om") as mock_extract:
        response = client.post("/ingestion/om", files=_upload_files(garbage))

    assert response.status_code == 400
    mock_extract.assert_not_called()


def test_page_count_ambiguity_is_not_rejected_and_proceeds_to_extraction(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _AmbiguousPageCountReader:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        @property
        def pages(self) -> Any:
            raise ValueError("cannot determine page count for this document")

    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", _AmbiguousPageCountReader)

    with patch("mini_anchor.api.extract_om", return_value=VALID_EXTRACTION_RESULT) as mock_extract:
        response = client.post("/ingestion/om", files=_upload_files(VALID_PDF_BYTES))

    assert response.status_code == 200
    mock_extract.assert_called_once()


def test_local_pdf_parse_timeout_is_rejected_without_a_provider_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    class _SlowReader:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            time.sleep(2)

    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", _SlowReader)
    monkeypatch.setattr("mini_anchor.api._PDF_PARSE_TIMEOUT_SECONDS", 0.05)

    with patch("mini_anchor.api.extract_om") as mock_extract:
        response = client.post("/ingestion/om", files=_upload_files(VALID_PDF_BYTES))

    assert 400 <= response.status_code < 500
    mock_extract.assert_not_called()


# =============================================================================
# Provider configuration / failure (AE6)
# =============================================================================


def test_configuration_error_returns_503(client: TestClient) -> None:
    with patch(
        "mini_anchor.api.extract_om",
        side_effect=ExtractionConfigurationError("AZURE_DOCUMENTINTELLIGENCE_KEY is not configured."),
    ):
        response = client.post("/ingestion/om", files=_upload_files(VALID_PDF_BYTES))

    assert response.status_code == 503
    assert "AZURE_DOCUMENTINTELLIGENCE_KEY" in response.json()["detail"]


def test_provider_failure_returns_502_without_raw_stack_trace(client: TestClient) -> None:
    with patch(
        "mini_anchor.api.extract_om",
        side_effect=ExtractionProviderError("The Azure Document Intelligence request failed (TimeoutError)."),
    ):
        response = client.post("/ingestion/om", files=_upload_files(VALID_PDF_BYTES))

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "Traceback" not in detail
    assert "api_key" not in detail.lower()


# =============================================================================
# Deterministic endpoints unaffected
# =============================================================================


def test_analyze_endpoint_still_works(client: TestClient) -> None:
    payload = {
        "purchase_price": 50_000_000,
        "current_noi": 2_500_000,
        "occupancy": 0.95,
        "noi_growth": 0.03,
        "hold_period": 5,
        "exit_cap_rate": 0.055,
        "ltv": 0.65,
        "interest_rate": 0.0525,
        "amortization": 30,
    }

    response = client.post("/analyze", json=payload)

    assert response.status_code == 200
