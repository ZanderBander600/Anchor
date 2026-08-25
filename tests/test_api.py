"""Tests for the minimal FastAPI adapter (``api.py``).

Covers ``GET /health``, the ``JSON -> validate_acquisition_inputs ->
analyze_acquisition -> JSON`` workflow of ``POST /analyze``, JSON
representation rules (raw decimals, tuples as arrays, ``None`` as ``null``),
and that the API layer performs no independent financial calculation or
validation of its own.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mini_anchor.api import app
from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine import AcquisitionResults, analyze_acquisition

GOLDEN_PAYLOAD: dict[str, Any] = {
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

GOLDEN_INPUTS = AcquisitionInputs(
    purchase_price=50_000_000.0,
    current_noi=2_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.055,
    ltv=0.65,
    interest_rate=0.0525,
    amortization=30,
)

_RESULT_FIELDS = tuple(AcquisitionResults.__dataclass_fields__)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_golden_case_returns_all_result_fields(client: TestClient) -> None:
    response = client.post("/analyze", json=GOLDEN_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == set(_RESULT_FIELDS)

    expected = analyze_acquisition(GOLDEN_INPUTS)
    assert body["going_in_cap_rate"] == pytest.approx(expected.going_in_cap_rate)
    assert body["levered_irr"] == pytest.approx(expected.levered_irr)
    assert body["equity_multiple"] == pytest.approx(expected.equity_multiple)
    assert body["headline_dscr"] == pytest.approx(expected.headline_dscr)


def test_analyze_percentage_values_remain_raw_decimals(client: TestClient) -> None:
    response = client.post("/analyze", json=GOLDEN_PAYLOAD)

    body = response.json()
    assert body["going_in_cap_rate"] == pytest.approx(0.05)
    assert isinstance(body["levered_irr"], float)
    assert 0.0 < body["levered_irr"] < 1.0
    for key in ("going_in_cap_rate", "levered_irr", "unlevered_irr"):
        assert "%" not in str(body[key])


def test_analyze_tuple_values_serialize_as_arrays(client: TestClient) -> None:
    response = client.post("/analyze", json=GOLDEN_PAYLOAD)

    body = response.json()
    assert isinstance(body["annual_debt_service"], list)
    assert isinstance(body["noi_by_year"], list)
    assert isinstance(body["unlevered_cash_flows"], list)
    assert isinstance(body["levered_cash_flows"], list)
    assert isinstance(body["dscr_by_year"], list)
    assert len(body["annual_debt_service"]) == 5
    assert len(body["unlevered_cash_flows"]) == 6


def test_analyze_zero_leverage_returns_null_dscr_and_zero_debt(client: TestClient) -> None:
    payload = dict(GOLDEN_PAYLOAD, ltv=0.0)

    response = client.post("/analyze", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["loan_amount"] == 0.0
    assert body["monthly_debt_service"] == 0.0
    assert body["annual_debt_service"] == [0.0, 0.0, 0.0, 0.0, 0.0]
    assert body["dscr_by_year"] == [None, None, None, None, None]
    assert body["headline_dscr"] is None
    assert body["initial_equity"] == pytest.approx(50_000_000.0)


def test_analyze_invalid_purchase_price_returns_422(client: TestClient) -> None:
    payload = dict(GOLDEN_PAYLOAD, purchase_price=-5)

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(issue["field_id"] == "purchase_price" for issue in detail)


def test_analyze_invalid_exit_cap_rate_returns_422(client: TestClient) -> None:
    payload = dict(GOLDEN_PAYLOAD, exit_cap_rate=0.0)

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(issue["field_id"] == "exit_cap_rate" for issue in detail)


def test_analyze_invalid_hold_period_returns_422(client: TestClient) -> None:
    payload = dict(GOLDEN_PAYLOAD, hold_period=0)

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(issue["field_id"] == "hold_period" for issue in detail)


def test_analyze_missing_required_field_returns_422(client: TestClient) -> None:
    payload = {key: value for key, value in GOLDEN_PAYLOAD.items() if key != "ltv"}

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(
        issue["field_id"] == "ltv" and issue["category"] == "missing_field_id"
        for issue in detail
    )


def test_analyze_malformed_json_returns_422(client: TestClient) -> None:
    response = client.post(
        "/analyze",
        content="{not valid json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_analyze_repeated_identical_request_returns_identical_response(
    client: TestClient,
) -> None:
    first = client.post("/analyze", json=GOLDEN_PAYLOAD)
    second = client.post("/analyze", json=GOLDEN_PAYLOAD)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_analyze_calls_analyze_acquisition_exactly_once(client: TestClient) -> None:
    """The API must call the frozen engine's ``analyze_acquisition`` exactly
    once with the inputs validated from the request body, and return exactly
    what it produces -- never compute a financial value itself."""

    with patch(
        "mini_anchor.api.analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        response = client.post("/analyze", json=GOLDEN_PAYLOAD)

    assert response.status_code == 200
    mock_analyze.assert_called_once_with(GOLDEN_INPUTS)


def test_analyze_engine_failure_returns_500(client: TestClient) -> None:
    """An unexpected exception from the engine must surface as an HTTP 500,
    not a fabricated 200 response or a swallowed error."""

    no_raise_client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "mini_anchor.api.analyze_acquisition", side_effect=RuntimeError("engine boom")
    ):
        response = no_raise_client.post("/analyze", json=GOLDEN_PAYLOAD)

    assert response.status_code == 500


# =============================================================================
# CORS
# =============================================================================


def test_cors_allows_localhost_5173(client: TestClient) -> None:
    origin = "http://localhost:5173"

    response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


def test_cors_allows_127_0_0_1_5173(client: TestClient) -> None:
    origin = "http://127.0.0.1:5173"

    response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


def test_cors_does_not_allow_unrelated_origin(client: TestClient) -> None:
    origin = "http://evil.example.com"

    response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") is None
