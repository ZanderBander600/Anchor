"""Tests for the Detailed Operating Model V2.1 Gate 10 endpoint
(``POST /ingestion/excel/detailed``) in ``anchor.api``.

Mirrors ``test_api_excel_ingestion.py``'s style: most tests exercise the
real ``read_detailed_excel_intake_from_bytes`` path end to end (the same
deterministic parsing/validation ``tests/test_detailed_v2_1_gate10_excel_ingestion.py``
already covers directly), and only the delegation test stubs it out to
prove the route doesn't reimplement any parsing itself.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from anchor.api import app
from anchor.contracts import AcquisitionTerms, DetailedOperatingInputs
from anchor.validation import DETAILED_FIELD_IDS, TERMS_FIELD_IDS

HEADERS = ("Field ID", "Input", "Value", "Unit")
META_HEADERS = ("Key", "Value")

TERMS_VALUES: dict[str, int | float] = {
    "purchase_price": 10_000_000,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
    "acquisition_cost_pct": 0.02,
    "financing_fee_pct": 0.01,
    "disposition_cost_pct": 0.025,
    "annual_capex_reserve": 50_000,
    "io_period": 2,
}
DETAILED_VALUES: dict[str, int | float] = {
    "gross_potential_rent": 800_000,
    "other_income": 20_000,
    "vacancy_credit_loss_pct": 0.05,
    "property_taxes": 60_000,
    "insurance": 20_000,
    "utilities": 25_000,
    "repairs_maintenance": 20_000,
    "other_operating_expenses": 16_000,
    "management_fee_pct": 0.05,
    "revenue_growth": 0.03,
    "expense_growth": 0.03,
}
FIELD_ORDER = TERMS_FIELD_IDS + DETAILED_FIELD_IDS
ALL_VALUES: dict[str, int | float] = {**TERMS_VALUES, **DETAILED_VALUES}
LABELS = {field_id: field_id.replace("_", " ").title() for field_id in FIELD_ORDER}

EXPECTED_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)
EXPECTED_DETAILED_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)

EXAMPLE_WORKBOOK = (
    Path(__file__).resolve().parents[1] / "examples" / "anchor_detailed_input_v2_1.xlsx"
)
QUICK_WORKBOOK = Path(__file__).resolve().parents[1] / "examples" / "anchor_input_v2.xlsx"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _build_workbook_bytes(
    *,
    anchor_schema: object = "detailed_acquisition",
    schema_version: object = "2.1",
    values: dict[str, object] | None = None,
) -> bytes:
    supplied = ALL_VALUES if values is None else values
    workbook = Workbook()
    meta = workbook.active
    meta.title = "Meta"
    meta.append(META_HEADERS)
    if anchor_schema is not None:
        meta.append(("anchor_schema", anchor_schema))
    if schema_version is not None:
        meta.append(("schema_version", schema_version))

    inputs = workbook.create_sheet("Inputs")
    inputs.append(HEADERS)
    for field_id in FIELD_ORDER:
        inputs.append((field_id, LABELS[field_id], supplied[field_id], ""))

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


VALID_WORKBOOK_BYTES = _build_workbook_bytes()


def _upload_files(content: bytes, filename: str = "anchor_detailed_input_v2_1.xlsx") -> dict[str, Any]:
    return {
        "file": (
            filename,
            content,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }


# =============================================================================
# Happy path
# =============================================================================


def test_valid_upload_returns_200_with_terms_and_detailed_operating_inputs(
    client: TestClient,
) -> None:
    response = client.post(
        "/ingestion/excel/detailed", files=_upload_files(VALID_WORKBOOK_BYTES)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["anchor_schema"] == "detailed_acquisition"
    assert body["schema_version"] == "2.1"
    assert body["terms"] == {
        "purchase_price": 10_000_000.0,
        "hold_period": 5,
        "exit_cap_rate": 0.065,
        "ltv": 0.60,
        "interest_rate": 0.05,
        "amortization": 30,
        "acquisition_cost_pct": 0.02,
        "financing_fee_pct": 0.01,
        "disposition_cost_pct": 0.025,
        "annual_capex_reserve": 50_000.0,
        "io_period": 2,
    }
    assert body["detailed_operating_inputs"] == {
        "gross_potential_rent": 800_000.0,
        "other_income": 20_000.0,
        "vacancy_credit_loss_pct": 0.05,
        "property_taxes": 60_000.0,
        "insurance": 20_000.0,
        "utilities": 25_000.0,
        "repairs_maintenance": 20_000.0,
        "other_operating_expenses": 16_000.0,
        "management_fee_pct": 0.05,
        "revenue_growth": 0.03,
        "expense_growth": 0.03,
    }
    # Never an OperatingProjection/AcquisitionResults leak into the response.
    assert "operating_projection" not in body
    assert "results" not in body


def test_valid_upload_of_the_tracked_example_workbook_matches_golden_values(
    client: TestClient,
) -> None:
    response = client.post(
        "/ingestion/excel/detailed",
        files=_upload_files(EXAMPLE_WORKBOOK.read_bytes()),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["terms"] == {
        "purchase_price": EXPECTED_TERMS.purchase_price,
        "hold_period": EXPECTED_TERMS.hold_period,
        "exit_cap_rate": EXPECTED_TERMS.exit_cap_rate,
        "ltv": EXPECTED_TERMS.ltv,
        "interest_rate": EXPECTED_TERMS.interest_rate,
        "amortization": EXPECTED_TERMS.amortization,
        "acquisition_cost_pct": EXPECTED_TERMS.acquisition_cost_pct,
        "financing_fee_pct": EXPECTED_TERMS.financing_fee_pct,
        "disposition_cost_pct": EXPECTED_TERMS.disposition_cost_pct,
        "annual_capex_reserve": EXPECTED_TERMS.annual_capex_reserve,
        "io_period": EXPECTED_TERMS.io_period,
    }
    assert body["detailed_operating_inputs"] == {
        "gross_potential_rent": EXPECTED_DETAILED_INPUTS.gross_potential_rent,
        "other_income": EXPECTED_DETAILED_INPUTS.other_income,
        "vacancy_credit_loss_pct": EXPECTED_DETAILED_INPUTS.vacancy_credit_loss_pct,
        "property_taxes": EXPECTED_DETAILED_INPUTS.property_taxes,
        "insurance": EXPECTED_DETAILED_INPUTS.insurance,
        "utilities": EXPECTED_DETAILED_INPUTS.utilities,
        "repairs_maintenance": EXPECTED_DETAILED_INPUTS.repairs_maintenance,
        "other_operating_expenses": EXPECTED_DETAILED_INPUTS.other_operating_expenses,
        "management_fee_pct": EXPECTED_DETAILED_INPUTS.management_fee_pct,
        "revenue_growth": EXPECTED_DETAILED_INPUTS.revenue_growth,
        "expense_growth": EXPECTED_DETAILED_INPUTS.expense_growth,
    }


def test_endpoint_delegates_to_the_shared_bytes_reader_rather_than_reimplementing_parsing(
    client: TestClient,
) -> None:
    from anchor.detailed_excel_reader import DetailedExcelIntakeReport

    stub_report = DetailedExcelIntakeReport(
        terms=EXPECTED_TERMS,
        detailed_operating_inputs=EXPECTED_DETAILED_INPUTS,
        anchor_schema="detailed_acquisition",
        schema_version="2.1",
    )
    with patch(
        "anchor.api.read_detailed_excel_intake_from_bytes",
        wraps=lambda data: stub_report,
    ) as mock_read:
        response = client.post(
            "/ingestion/excel/detailed", files=_upload_files(VALID_WORKBOOK_BYTES)
        )

    assert response.status_code == 200
    mock_read.assert_called_once_with(VALID_WORKBOOK_BYTES)


# =============================================================================
# Upload validation -- filename / signature / size (shared with Quick, KTD9)
# =============================================================================


def test_non_xlsx_filename_is_rejected_without_parsing(client: TestClient) -> None:
    with patch("anchor.api.read_detailed_excel_intake_from_bytes") as mock_read:
        response = client.post(
            "/ingestion/excel/detailed",
            files={"file": ("anchor_detailed_input.csv", b"just some text", "text/csv")},
        )

    assert 400 <= response.status_code < 500
    mock_read.assert_not_called()


def test_xlsx_filename_with_non_xlsx_bytes_is_rejected_without_parsing(client: TestClient) -> None:
    with patch("anchor.api.read_detailed_excel_intake_from_bytes") as mock_read:
        response = client.post(
            "/ingestion/excel/detailed",
            files=_upload_files(b"this is not a real xlsx file at all"),
        )

    assert 400 <= response.status_code < 500
    mock_read.assert_not_called()


def test_body_exceeding_the_size_ceiling_is_rejected_without_parsing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("anchor.api._MAX_EXCEL_UPLOAD_BYTES", 10)

    with patch("anchor.api.read_detailed_excel_intake_from_bytes") as mock_read:
        response = client.post(
            "/ingestion/excel/detailed", files=_upload_files(VALID_WORKBOOK_BYTES)
        )

    assert 400 <= response.status_code < 500
    mock_read.assert_not_called()


# =============================================================================
# Wrong-workbook protection
# =============================================================================


def test_quick_workbook_through_detailed_endpoint_returns_422_with_clear_message(
    client: TestClient,
) -> None:
    response = client.post(
        "/ingestion/excel/detailed",
        files=_upload_files(QUICK_WORKBOOK.read_bytes(), filename="anchor_input_v2.xlsx"),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert len(detail) == 1
    assert detail[0]["category"] == "schema_mismatch"
    assert "Quick Underwrite" in detail[0]["message"]


def test_unsupported_schema_version_returns_422(client: TestClient) -> None:
    response = client.post(
        "/ingestion/excel/detailed",
        files=_upload_files(_build_workbook_bytes(schema_version="9.9")),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["category"] == "unsupported_schema_version"


# =============================================================================
# Malformed workbook -> 422 with the same issue shape /analyze uses; never
# reaches the deterministic engine.
# =============================================================================


def test_malformed_workbook_returns_422_and_never_reaches_the_engine(
    client: TestClient,
) -> None:
    values = dict(ALL_VALUES)
    values["gross_potential_rent"] = None  # blank required value

    with patch("anchor.api.analyze_detailed_acquisition_with_projection") as mock_analyze:
        response = client.post(
            "/ingestion/excel/detailed",
            files=_upload_files(_build_workbook_bytes(values=values)),
        )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    assert any(issue["field_id"] == "gross_potential_rent" for issue in body["detail"])
    mock_analyze.assert_not_called()
