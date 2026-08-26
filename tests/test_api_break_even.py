"""Tests for the Phase 8 break-even endpoint (``POST /break-even``) in
``mini_anchor.api``.

Mirrors ``test_api_sensitivity.py``'s style: covers the JSON contract (raw
decimals, ``None`` -> ``null``, exactly five results), error handling for
invalid inputs/targets, determinism, and that the endpoint delegates to the
analysis layer rather than computing anything itself.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mini_anchor.analysis import build_standard_break_even_analysis
from mini_anchor.api import app
from mini_anchor.contracts import AcquisitionInputs

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
    "target_levered_irr": 0.10,
    "target_headline_dscr": 1.20,
    "target_equity_multiple": 1.50,
}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_break_even_golden_request_returns_200(client: TestClient) -> None:
    response = client.post("/break-even", json=GENERIC_REQUEST)

    assert response.status_code == 200


def test_break_even_returns_exactly_five_results(client: TestClient) -> None:
    response = client.post("/break-even", json=GENERIC_REQUEST)

    body = response.json()
    assert set(body.keys()) == {
        "max_purchase_price",
        "max_exit_cap_rate",
        "min_noi_growth",
        "max_interest_rate",
        "min_current_noi",
    }


def test_break_even_response_uses_raw_decimals(client: TestClient) -> None:
    response = client.post("/break-even", json=GENERIC_REQUEST)

    body = response.json()
    result = body["max_purchase_price"]
    assert isinstance(result["solved_assumption_value"], float)
    assert isinstance(result["baseline_assumption_value"], float)
    assert result["status"] == "solved"
    assert result["break_even_type"] == "max_purchase_price"
    assert result["assumption"] == "purchase_price"
    assert result["metric"] == "levered_irr"
    assert result["target_metric_value"] == 0.10


def test_break_even_matches_direct_analysis_layer_call(client: TestClient) -> None:
    response = client.post("/break-even", json=GENERIC_REQUEST)

    expected = build_standard_break_even_analysis(
        GOLDEN_INPUTS,
        target_levered_irr=0.10,
        target_headline_dscr=1.20,
        target_equity_multiple=1.50,
    )

    body = response.json()
    assert body["max_purchase_price"]["solved_assumption_value"] == pytest.approx(
        expected.max_purchase_price.solved_assumption_value
    )
    assert body["min_current_noi"]["solved_assumption_value"] == pytest.approx(
        expected.min_current_noi.solved_assumption_value
    )


def test_break_even_custom_irr_hurdle_changes_result(client: TestClient) -> None:
    default_response = client.post("/break-even", json=GENERIC_REQUEST)
    custom_request = dict(GENERIC_REQUEST, target_levered_irr=0.15)
    custom_response = client.post("/break-even", json=custom_request)

    default_price = default_response.json()["max_purchase_price"]["solved_assumption_value"]
    custom_price = custom_response.json()["max_purchase_price"]["solved_assumption_value"]
    assert custom_price < default_price


def test_break_even_custom_dscr_hurdle_changes_result(client: TestClient) -> None:
    default_response = client.post("/break-even", json=GENERIC_REQUEST)
    custom_request = dict(GENERIC_REQUEST, target_headline_dscr=1.35)
    custom_response = client.post("/break-even", json=custom_request)

    default_rate = default_response.json()["max_interest_rate"]["solved_assumption_value"]
    custom_rate = custom_response.json()["max_interest_rate"]["solved_assumption_value"]
    assert custom_rate < default_rate


def test_break_even_no_solution_serializes_as_null(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, target_levered_irr=0.90)

    response = client.post("/break-even", json=request)

    body = response.json()
    assert response.status_code == 200
    assert body["max_purchase_price"]["status"] == "no_solution_in_range"
    assert body["max_purchase_price"]["solved_assumption_value"] is None
    assert body["max_purchase_price"]["solved_metric_value"] is None


def test_break_even_invalid_target_irr_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, target_levered_irr=-1.5)

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_invalid_target_dscr_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, target_headline_dscr=0.0)

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_non_numeric_target_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, target_levered_irr="ten percent")

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_invalid_acquisition_inputs_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, inputs=dict(GOLDEN_INPUTS_PAYLOAD, purchase_price=-5))

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_missing_target_field_returns_422(client: TestClient) -> None:
    request = {key: value for key, value in GENERIC_REQUEST.items() if key != "target_headline_dscr"}

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_missing_inputs_returns_422(client: TestClient) -> None:
    request = {key: value for key, value in GENERIC_REQUEST.items() if key != "inputs"}

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_repeated_identical_request_returns_identical_response(
    client: TestClient,
) -> None:
    first = client.post("/break-even", json=GENERIC_REQUEST)
    second = client.post("/break-even", json=GENERIC_REQUEST)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_break_even_delegates_to_analysis_layer(client: TestClient) -> None:
    with patch(
        "mini_anchor.api.build_standard_break_even_analysis",
        wraps=build_standard_break_even_analysis,
    ) as mock_build:
        response = client.post("/break-even", json=GENERIC_REQUEST)

    assert response.status_code == 200
    mock_build.assert_called_once()


# =============================================================================
# Equity Multiple return hurdle (``return_hurdle_metric``)
# =============================================================================


def test_break_even_missing_target_equity_multiple_returns_422(client: TestClient) -> None:
    request = {key: value for key, value in GENERIC_REQUEST.items() if key != "target_equity_multiple"}

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_defaults_to_levered_irr_return_hurdle(client: TestClient) -> None:
    """Omitting ``return_hurdle_metric`` entirely must retain the pre-existing
    Levered IRR behavior -- this is an additive, backward-compatible field."""

    response = client.post("/break-even", json=GENERIC_REQUEST)

    body = response.json()
    assert body["max_purchase_price"]["metric"] == "levered_irr"
    assert body["max_exit_cap_rate"]["metric"] == "levered_irr"
    assert body["min_noi_growth"]["metric"] == "levered_irr"


def test_break_even_equity_multiple_return_hurdle_changes_metric(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, return_hurdle_metric="equity_multiple")

    response = client.post("/break-even", json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["max_purchase_price"]["metric"] == "equity_multiple"
    assert body["max_exit_cap_rate"]["metric"] == "equity_multiple"
    assert body["min_noi_growth"]["metric"] == "equity_multiple"
    assert body["max_purchase_price"]["target_metric_value"] == 1.50
    assert body["max_purchase_price"]["solved_metric_value"] == pytest.approx(1.50, abs=1e-3)


def test_break_even_equity_multiple_return_hurdle_leaves_dscr_cards_unchanged(
    client: TestClient,
) -> None:
    irr_response = client.post("/break-even", json=GENERIC_REQUEST)
    em_request = dict(GENERIC_REQUEST, return_hurdle_metric="equity_multiple")
    em_response = client.post("/break-even", json=em_request)

    irr_body = irr_response.json()
    em_body = em_response.json()
    assert irr_body["max_interest_rate"] == em_body["max_interest_rate"]
    assert irr_body["min_current_noi"] == em_body["min_current_noi"]


def test_break_even_custom_equity_multiple_hurdle_changes_result(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, return_hurdle_metric="equity_multiple")
    default_response = client.post("/break-even", json=request)

    higher_hurdle_request = dict(request, target_equity_multiple=1.80)
    higher_hurdle_response = client.post("/break-even", json=higher_hurdle_request)

    default_price = default_response.json()["max_purchase_price"]["solved_assumption_value"]
    higher_hurdle_price = higher_hurdle_response.json()["max_purchase_price"]["solved_assumption_value"]
    assert higher_hurdle_price < default_price


def test_break_even_invalid_target_equity_multiple_returns_422(client: TestClient) -> None:
    request = dict(
        GENERIC_REQUEST, target_equity_multiple=0.0, return_hurdle_metric="equity_multiple"
    )

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_invalid_return_hurdle_metric_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, return_hurdle_metric="unlevered_irr")

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_break_even_non_numeric_target_equity_multiple_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, target_equity_multiple="one point five")

    response = client.post("/break-even", json=request)

    assert response.status_code == 422
