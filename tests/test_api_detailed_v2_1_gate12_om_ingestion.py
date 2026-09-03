"""Tests for the Detailed Operating Model V2.1 Gate 12 endpoint
(``POST /ingestion/om/detailed``) in ``anchor.api``.

Mirrors ``test_api_ingestion.py``'s style. No test in this module makes a
real Azure DI or OpenAI call: ``anchor.api.extract_detailed_om`` is always
patched, either directly (for the endpoint's own upload-validation and
error-mapping contract) or left unpatched only where the assertion is
specifically that it is *never called* (e.g. a rejected upload).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from anchor.api import app
from anchor.ingestion.contracts import (
    DETAILED_OPERATING_FIELD_IDS,
    DETAILED_TERMS_FIELD_IDS,
    DetailedExtractionResult,
    EvidenceStatus,
    ExtractionCandidate,
    ExtractionConfigurationError,
    ExtractionProviderError,
    FieldCandidates,
    Provenance,
)

_ALL_FIELD_IDS = (*DETAILED_TERMS_FIELD_IDS, *DETAILED_OPERATING_FIELD_IDS)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


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


def _fixture_detailed_extraction_result() -> DetailedExtractionResult:
    stated = FieldCandidates(
        field_id="purchase_price",
        candidates=(
            ExtractionCandidate(
                value="10000000",
                status=EvidenceStatus.STATED,
                provenance=Provenance(page=1, anchor="paragraph:0", snippet="$10,000,000"),
            ),
        ),
    )
    conflicting = FieldCandidates(
        field_id="gross_potential_rent",
        candidates=(
            ExtractionCandidate(
                value="800000",
                status=EvidenceStatus.CONFLICTING,
                provenance=Provenance(page=1, anchor="paragraph:1", snippet="GPR: $800,000"),
            ),
            ExtractionCandidate(
                value="820000",
                status=EvidenceStatus.CONFLICTING,
                provenance=Provenance(page=2, anchor="paragraph:2", snippet="GPR: $820,000"),
            ),
        ),
    )
    fields = {field_id: _missing(field_id) for field_id in _ALL_FIELD_IDS}
    fields["purchase_price"] = stated
    fields["gross_potential_rent"] = conflicting
    return DetailedExtractionResult(**fields)


VALID_PDF_BYTES = _build_minimal_pdf()
VALID_DETAILED_EXTRACTION_RESULT = _fixture_detailed_extraction_result()


def _upload_files(content: bytes, content_type: str = "application/pdf") -> dict[str, Any]:
    return {"file": ("om.pdf", content, content_type)}


# =============================================================================
# Happy path
# =============================================================================


def test_valid_upload_returns_200_with_detailed_candidates_json(client: TestClient) -> None:
    with patch(
        "anchor.api.extract_detailed_om", return_value=VALID_DETAILED_EXTRACTION_RESULT
    ) as mock_extract:
        response = client.post(
            "/ingestion/om/detailed", files=_upload_files(VALID_PDF_BYTES)
        )

    assert response.status_code == 200
    mock_extract.assert_called_once()
    body = response.json()
    assert body["purchase_price"]["candidates"][0]["status"] == "stated"
    assert body["insurance"]["candidates"] == []
    assert len(body["gross_potential_rent"]["candidates"]) == 2
    assert all(c["status"] == "conflicting" for c in body["gross_potential_rent"]["candidates"])
    # No calculated/derived fields ever leak into the response.
    assert "deal_context" not in body
    assert "current_noi" not in body
    assert "operating_projection" not in body
    assert "results" not in body


def test_extract_detailed_om_is_called_with_the_uploaded_pdf_bytes(client: TestClient) -> None:
    with patch(
        "anchor.api.extract_detailed_om", return_value=VALID_DETAILED_EXTRACTION_RESULT
    ) as mock_extract:
        client.post("/ingestion/om/detailed", files=_upload_files(VALID_PDF_BYTES))

    mock_extract.assert_called_once_with(VALID_PDF_BYTES)


# =============================================================================
# Upload validation -- content-type / signature (KTD9, shared with Quick)
# =============================================================================


def test_non_pdf_content_type_is_rejected_without_a_provider_call(client: TestClient) -> None:
    with patch("anchor.api.extract_detailed_om") as mock_extract:
        response = client.post(
            "/ingestion/om/detailed",
            files={"file": ("om.txt", b"just some text", "text/plain")},
        )

    assert 400 <= response.status_code < 500
    mock_extract.assert_not_called()


def test_spoofed_content_type_on_non_pdf_bytes_is_rejected_without_a_provider_call(
    client: TestClient,
) -> None:
    with patch("anchor.api.extract_detailed_om") as mock_extract:
        response = client.post(
            "/ingestion/om/detailed",
            files={"file": ("om.pdf", b"this is not a pdf at all", "application/pdf")},
        )

    assert 400 <= response.status_code < 500
    mock_extract.assert_not_called()


def test_body_exceeding_the_size_ceiling_is_rejected_without_a_provider_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("anchor.api._MAX_UPLOAD_BYTES", 10)

    with patch("anchor.api.extract_detailed_om") as mock_extract:
        response = client.post(
            "/ingestion/om/detailed", files=_upload_files(VALID_PDF_BYTES)
        )

    assert 400 <= response.status_code < 500
    mock_extract.assert_not_called()


# =============================================================================
# Provider failures -- consistent status-code mapping with Quick
# =============================================================================


def test_configuration_error_returns_503(client: TestClient) -> None:
    with patch(
        "anchor.api.extract_detailed_om",
        side_effect=ExtractionConfigurationError(
            "AZURE_DOCUMENTINTELLIGENCE_KEY is not configured."
        ),
    ):
        response = client.post(
            "/ingestion/om/detailed", files=_upload_files(VALID_PDF_BYTES)
        )

    assert response.status_code == 503


def test_provider_failure_returns_502_without_raw_stack_trace(client: TestClient) -> None:
    with patch(
        "anchor.api.extract_detailed_om",
        side_effect=ExtractionProviderError(
            "The Azure Document Intelligence request failed (TimeoutError)."
        ),
    ):
        response = client.post(
            "/ingestion/om/detailed", files=_upload_files(VALID_PDF_BYTES)
        )

    assert response.status_code == 502
    assert "Traceback" not in response.text


# =============================================================================
# Quick endpoint backward compatibility -- unaffected by this gate
# =============================================================================


def test_quick_om_endpoint_still_reachable_and_unaffected(client: TestClient) -> None:
    from anchor.ingestion.contracts import DealContext, ExtractionResult

    def _missing_quick(field_id: str) -> FieldCandidates:
        return FieldCandidates(field_id=field_id)

    quick_fields = {
        field_id: _missing_quick(field_id)
        for field_id in (
            "purchase_price",
            "current_noi",
            "occupancy",
            "noi_growth",
            "hold_period",
            "exit_cap_rate",
            "ltv",
            "interest_rate",
            "amortization",
        )
    }
    deal_context = DealContext(
        property_name=_missing_quick("property_name"),
        address=_missing_quick("address"),
        property_type=_missing_quick("property_type"),
        unit_count_or_building_area=_missing_quick("unit_count_or_building_area"),
        year_built=_missing_quick("year_built"),
    )
    quick_result = ExtractionResult(**quick_fields, deal_context=deal_context)

    with patch("anchor.api.extract_om", return_value=quick_result) as mock_extract:
        response = client.post("/ingestion/om", files=_upload_files(VALID_PDF_BYTES))

    assert response.status_code == 200
    mock_extract.assert_called_once()
    assert "deal_context" in response.json()
