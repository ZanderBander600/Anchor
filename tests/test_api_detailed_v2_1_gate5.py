"""Detailed Operating Model V2.1 Gate 5 -- ``POST /analyze`` mode-awareness.

Covers ``docs/detailed_operating_model_v2_1_architecture.md`` Section 5:
an existing ``"quick"``/absent ``operating_mode`` payload is unaffected;
``operating_mode`` itself is popped before validation so it is never seen
as an unknown Field ID; a ``"detailed"`` request validates ``terms`` and
``detailed_operating_inputs`` with the shared validators and delegates to
``analyze_detailed_acquisition``; response shape is identical either way.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from anchor.api import app
from anchor.contracts import AcquisitionInputs
from anchor.engine import AcquisitionResults, analyze_acquisition

GOLDEN_QUICK_PAYLOAD: dict[str, Any] = {
    "purchase_price": 10_000_000,
    "current_noi": 600_000,
    "occupancy": 0.95,
    "noi_growth": 0.03,
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

GOLDEN_QUICK_INPUTS = AcquisitionInputs(
    purchase_price=10_000_000.0,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
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

GOLDEN_TERMS_PAYLOAD: dict[str, Any] = {
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

GOLDEN_DETAILED_OPERATING_PAYLOAD: dict[str, Any] = {
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

_RESULT_FIELDS = tuple(AcquisitionResults.__dataclass_fields__)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# =============================================================================
# Quick mode is unaffected
# =============================================================================


def test_analyze_with_no_operating_mode_key_is_unaffected(client: TestClient) -> None:
    response = client.post("/analyze", json=GOLDEN_QUICK_PAYLOAD)

    assert response.status_code == 200
    expected = analyze_acquisition(GOLDEN_QUICK_INPUTS)
    body = response.json()
    assert body["loan_amount"] == pytest.approx(expected.loan_amount)
    assert body["levered_irr"] == pytest.approx(expected.levered_irr)


def test_analyze_with_explicit_quick_operating_mode_matches_absent_operating_mode(
    client: TestClient,
) -> None:
    with_key = client.post(
        "/analyze", json=GOLDEN_QUICK_PAYLOAD | {"operating_mode": "quick"}
    )
    without_key = client.post("/analyze", json=GOLDEN_QUICK_PAYLOAD)

    assert with_key.status_code == 200
    assert with_key.json() == without_key.json()


def test_operating_mode_key_is_popped_before_validation_never_an_unknown_field(
    client: TestClient,
) -> None:
    """If operating_mode were not popped before
    validate_acquisition_inputs, this would 422 with an UNKNOWN_FIELD_ID
    issue for 'operating_mode' itself."""

    response = client.post(
        "/analyze", json=GOLDEN_QUICK_PAYLOAD | {"operating_mode": "quick"}
    )

    assert response.status_code == 200


def test_invalid_operating_mode_value_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/analyze", json=GOLDEN_QUICK_PAYLOAD | {"operating_mode": "bogus"}
    )

    assert response.status_code == 422
    assert "operating_mode" in response.json()["detail"]


# =============================================================================
# Detailed mode
# =============================================================================


def test_analyze_detailed_golden_case_reconciles_to_the_v2_golden_case(
    client: TestClient,
) -> None:
    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": GOLDEN_TERMS_PAYLOAD,
            "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["loan_amount"] == pytest.approx(6_000_000.0)
    assert body["initial_equity"] == pytest.approx(4_260_000.0)
    assert body["noi_by_year"] == pytest.approx(
        [600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286]
    )
    assert body["headline_dscr"] == pytest.approx(2.0, abs=1e-5)
    assert body["levered_irr"] == pytest.approx(0.073802, abs=1e-6)


def test_analyze_detailed_response_shape_matches_quick_response_shape(
    client: TestClient,
) -> None:
    detailed_response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": GOLDEN_TERMS_PAYLOAD,
            "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
        },
    )
    quick_response = client.post("/analyze", json=GOLDEN_QUICK_PAYLOAD)

    assert set(detailed_response.json().keys()) == set(_RESULT_FIELDS)
    assert set(detailed_response.json().keys()) == set(quick_response.json().keys())


def test_analyze_detailed_missing_terms_object_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
        },
    )

    assert response.status_code == 422
    assert "terms" in response.json()["detail"]


def test_analyze_detailed_missing_detailed_operating_inputs_object_is_rejected(
    client: TestClient,
) -> None:
    response = client.post(
        "/analyze",
        json={"operating_mode": "detailed", "terms": GOLDEN_TERMS_PAYLOAD},
    )

    assert response.status_code == 422
    assert "detailed_operating_inputs" in response.json()["detail"]


def test_analyze_detailed_invalid_terms_field_returns_validation_issues(
    client: TestClient,
) -> None:
    bad_terms = GOLDEN_TERMS_PAYLOAD | {"ltv": 1.5}
    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": bad_terms,
            "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(issue["field_id"] == "ltv" for issue in detail)


def test_analyze_detailed_invalid_detailed_operating_field_returns_validation_issues(
    client: TestClient,
) -> None:
    bad_detailed_inputs = GOLDEN_DETAILED_OPERATING_PAYLOAD | {
        "vacancy_credit_loss_pct": 1.5
    }
    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": GOLDEN_TERMS_PAYLOAD,
            "detailed_operating_inputs": bad_detailed_inputs,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(issue["field_id"] == "vacancy_credit_loss_pct" for issue in detail)


def test_analyze_detailed_terms_as_non_object_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": "not-an-object",
            "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
        },
    )

    assert response.status_code == 422
