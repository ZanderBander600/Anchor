"""Detailed Operating Model V2.1 Gate 5b -- ``/deals`` mode-awareness over HTTP.

Mirrors ``test_api_deals.py``'s conventions. Covers the ``operating_mode``
discriminator on ``POST``/``PUT /deals`` (mirroring ``/analyze`` exactly),
and that GET/DELETE/duplicate work identically for a Detailed deal id with
no route change needed on their part (they already dispatch by id at the
store layer).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from anchor.api import app

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

GOLDEN_QUICK_PAYLOAD: dict[str, Any] = {
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


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "test-anchor.db"))
    return TestClient(app)


def _create_detailed_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "name": "Detailed Deal",
        "operating_mode": "detailed",
        "terms": GOLDEN_TERMS_PAYLOAD,
        "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
    }
    payload.update(overrides)
    return payload


def test_create_detailed_deal_returns_the_saved_deal(client: TestClient) -> None:
    response = client.post("/deals", json=_create_detailed_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Detailed Deal"
    assert body["operating_mode"] == "detailed"
    assert body["inputs"] is None
    assert body["terms"]["purchase_price"] == pytest.approx(10_000_000.0)
    assert body["detailed_operating_inputs"]["gross_potential_rent"] == pytest.approx(
        800_000.0
    )
    assert body["id"]
    assert body["created_at"]
    assert body["updated_at"]


def test_create_detailed_deal_missing_terms_is_rejected(client: TestClient) -> None:
    payload = _create_detailed_payload()
    del payload["terms"]

    response = client.post("/deals", json=payload)

    assert response.status_code == 422


def test_create_detailed_deal_missing_detailed_operating_inputs_is_rejected(
    client: TestClient,
) -> None:
    payload = _create_detailed_payload()
    del payload["detailed_operating_inputs"]

    response = client.post("/deals", json=payload)

    assert response.status_code == 422


def test_create_detailed_deal_invalid_field_returns_validation_issues(
    client: TestClient,
) -> None:
    payload = _create_detailed_payload(
        terms=GOLDEN_TERMS_PAYLOAD | {"ltv": 1.5}
    )

    response = client.post("/deals", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(issue["field_id"] == "ltv" for issue in detail)


def test_get_detailed_deal_returns_the_saved_deal(client: TestClient) -> None:
    created = client.post("/deals", json=_create_detailed_payload()).json()

    response = client.get(f"/deals/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_list_deals_includes_both_quick_and_detailed(client: TestClient) -> None:
    quick = client.post(
        "/deals", json={"name": "Quick Deal", "inputs": GOLDEN_QUICK_PAYLOAD}
    ).json()
    detailed = client.post("/deals", json=_create_detailed_payload()).json()

    response = client.get("/deals")

    assert response.status_code == 200
    ids = {deal["id"] for deal in response.json()}
    assert ids == {quick["id"], detailed["id"]}


def test_update_detailed_deal_overwrites_terms_and_operating_inputs(
    client: TestClient,
) -> None:
    created = client.post("/deals", json=_create_detailed_payload()).json()

    updated_payload = _create_detailed_payload(
        name="Renamed Detailed Deal",
        terms=GOLDEN_TERMS_PAYLOAD | {"ltv": 0.55},
    )
    response = client.put(f"/deals/{created['id']}", json=updated_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Detailed Deal"
    assert body["terms"]["ltv"] == pytest.approx(0.55)


def test_update_deal_route_does_not_find_a_detailed_only_id(client: TestClient) -> None:
    created = client.post("/deals", json=_create_detailed_payload()).json()

    response = client.put(
        f"/deals/{created['id']}",
        json={"name": "New Name", "inputs": GOLDEN_QUICK_PAYLOAD},
    )

    assert response.status_code == 404


def test_delete_detailed_deal(client: TestClient) -> None:
    created = client.post("/deals", json=_create_detailed_payload()).json()

    delete_response = client.delete(f"/deals/{created['id']}")
    get_response = client.get(f"/deals/{created['id']}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


def test_duplicate_detailed_deal_preserves_operating_mode(client: TestClient) -> None:
    created = client.post("/deals", json=_create_detailed_payload()).json()

    response = client.post(f"/deals/{created['id']}/duplicate", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] != created["id"]
    assert body["operating_mode"] == "detailed"
    assert body["terms"] == created["terms"]
    assert body["detailed_operating_inputs"] == created["detailed_operating_inputs"]
    assert body["name"] == "Detailed Deal (Copy)"


def test_invalid_operating_mode_on_create_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/deals",
        json={"name": "Deal", "operating_mode": "bogus", "inputs": GOLDEN_QUICK_PAYLOAD},
    )

    assert response.status_code == 422
