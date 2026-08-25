"""Tests for the Phase 7 sensitivity endpoints (``POST /sensitivity`` and
``POST /sensitivity/presets``) in ``mini_anchor.api``.

Mirrors ``test_api.py``'s style: covers the JSON contract (raw decimals,
``None`` -> ``null``, exact matrix dimensions), error handling for invalid
assumptions/metrics/domains, determinism, and that the endpoint delegates to
the analysis layer rather than computing anything itself.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mini_anchor.analysis import run_two_way_sensitivity
from mini_anchor.api import app
from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine import analyze_acquisition

GOLDEN_INPUTS_PAYLOAD: dict[str, Any] = {
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

GENERIC_REQUEST: dict[str, Any] = {
    "inputs": GOLDEN_INPUTS_PAYLOAD,
    "row_assumption": "noi_growth",
    "row_values": [0.01, 0.02, 0.03, 0.04, 0.05],
    "column_assumption": "exit_cap_rate",
    "column_values": [0.045, 0.05, 0.055, 0.06, 0.065],
    "metric": "levered_irr",
}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# =============================================================================
# POST /sensitivity
# =============================================================================


def test_sensitivity_valid_request_returns_200(client: TestClient) -> None:
    response = client.post("/sensitivity", json=GENERIC_REQUEST)

    assert response.status_code == 200


def test_sensitivity_response_uses_raw_decimals_and_correct_dimensions(
    client: TestClient,
) -> None:
    response = client.post("/sensitivity", json=GENERIC_REQUEST)

    body = response.json()
    assert body["row_assumption"] == "noi_growth"
    assert body["column_assumption"] == "exit_cap_rate"
    assert body["metric"] == "levered_irr"
    assert len(body["matrix"]) == 5
    assert all(len(row) == 5 for row in body["matrix"])
    assert isinstance(body["baseline_metric_value"], float)


def test_sensitivity_matches_direct_analysis_layer_call(client: TestClient) -> None:
    response = client.post("/sensitivity", json=GENERIC_REQUEST)

    expected = run_two_way_sensitivity(
        GOLDEN_INPUTS,
        row_assumption="noi_growth",
        row_values=(0.01, 0.02, 0.03, 0.04, 0.05),
        column_assumption="exit_cap_rate",
        column_values=(0.045, 0.05, 0.055, 0.06, 0.065),
        metric="levered_irr",
    )

    body = response.json()
    for row_index, row in enumerate(body["matrix"]):
        for column_index, cell in enumerate(row):
            assert cell == pytest.approx(expected.matrix[row_index][column_index])


def test_sensitivity_null_metric_serializes_as_json_null(client: TestClient) -> None:
    zero_leverage_request = dict(
        GENERIC_REQUEST,
        inputs=dict(GOLDEN_INPUTS_PAYLOAD, ltv=0.0),
        metric="headline_dscr",
    )

    response = client.post("/sensitivity", json=zero_leverage_request)

    body = response.json()
    assert response.status_code == 200
    assert body["baseline_metric_value"] is None
    assert all(cell is None for row in body["matrix"] for cell in row)


def test_sensitivity_invalid_metric_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, metric="cash_on_cash")

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_sensitivity_invalid_assumption_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, row_assumption="occupancy")

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_sensitivity_invalid_input_domain_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, inputs=dict(GOLDEN_INPUTS_PAYLOAD, purchase_price=-5))

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_sensitivity_invalid_scenario_value_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, column_values=[-0.01, 0.05, 0.055, 0.06, 0.065])

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_sensitivity_missing_field_returns_422(client: TestClient) -> None:
    request = {key: value for key, value in GENERIC_REQUEST.items() if key != "metric"}

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_sensitivity_repeated_identical_request_returns_identical_response(
    client: TestClient,
) -> None:
    first = client.post("/sensitivity", json=GENERIC_REQUEST)
    second = client.post("/sensitivity", json=GENERIC_REQUEST)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_sensitivity_delegates_to_analysis_layer(client: TestClient) -> None:
    with patch(
        "mini_anchor.api.run_two_way_sensitivity", wraps=run_two_way_sensitivity
    ) as mock_run:
        response = client.post("/sensitivity", json=GENERIC_REQUEST)

    assert response.status_code == 200
    mock_run.assert_called_once()


def test_sensitivity_base_engine_remains_authoritative(client: TestClient) -> None:
    """Every cell must ultimately be produced by the frozen
    ``analyze_acquisition`` -- the API/analysis layers must not compute a
    financial value independently."""

    with patch(
        "mini_anchor.analysis.sensitivity.analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        response = client.post("/sensitivity", json=GENERIC_REQUEST)

    assert response.status_code == 200
    # 1 baseline call + 25 grid cells.
    assert mock_analyze.call_count == 26


# =============================================================================
# POST /sensitivity/presets
# =============================================================================


def test_sensitivity_presets_returns_all_four_matrices(client: TestClient) -> None:
    response = client.post("/sensitivity/presets", json={"inputs": GOLDEN_INPUTS_PAYLOAD})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "exit_cap_noi_growth",
        "purchase_price_exit_cap",
        "interest_rate_ltv",
        "interest_rate_ltv_dscr",
    }
    for key in body:
        assert len(body[key]["matrix"]) == 5
        assert all(len(row) == 5 for row in body[key]["matrix"])


def test_sensitivity_presets_invalid_input_domain_returns_422(client: TestClient) -> None:
    response = client.post(
        "/sensitivity/presets",
        json={"inputs": dict(GOLDEN_INPUTS_PAYLOAD, exit_cap_rate=0.0)},
    )

    assert response.status_code == 422
