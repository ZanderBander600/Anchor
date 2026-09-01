"""Tests for the Persistence Phase A ``/deals`` endpoints (``api.py``).

Covers create/list/get/update over HTTP, 404/422 error shapes matching the
rest of the API, and the two properties the task explicitly requires:
saved inputs round-trip without changing economic meaning, and reopening a
deal and sending its restored inputs back to the existing ``/analyze``
produces exactly the same ``AcquisitionResults`` as analyzing the original
inputs directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from anchor.api import app
from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition

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

# Long binary-fraction values hostile to a lossy round-trip path.
AWKWARD_PAYLOAD: dict[str, Any] = {
    "purchase_price": 12_345_678.913571113,
    "current_noi": 999_999.0000000001,
    "occupancy": 0.123456789012345,
    "noi_growth": 0.030000000000004,
    "hold_period": 7,
    "exit_cap_rate": 0.05499999999999999,
    "ltv": 0.6666666666666666,
    "interest_rate": 0.052500000000001,
    "amortization": 25,
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "test-anchor.db"))
    return TestClient(app)


def test_create_deal_returns_the_saved_deal(client: TestClient) -> None:
    response = client.post("/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "111 Main St"
    assert body["id"]
    assert body["inputs"] == GOLDEN_PAYLOAD
    assert body["created_at"]
    assert body["updated_at"]


def test_create_deal_rejects_missing_name(client: TestClient) -> None:
    response = client.post("/deals", json={"inputs": GOLDEN_PAYLOAD})

    assert response.status_code == 422


def test_create_deal_rejects_blank_name(client: TestClient) -> None:
    response = client.post("/deals", json={"name": "   ", "inputs": GOLDEN_PAYLOAD})

    assert response.status_code == 422


def test_create_deal_rejects_invalid_inputs_with_the_same_shape_as_analyze(
    client: TestClient,
) -> None:
    bad_payload = dict(GOLDEN_PAYLOAD)
    bad_payload["purchase_price"] = -1

    analyze_response = client.post("/analyze", json=bad_payload)
    create_response = client.post(
        "/deals", json={"name": "Bad Deal", "inputs": bad_payload}
    )

    assert analyze_response.status_code == 422
    assert create_response.status_code == 422
    assert (
        create_response.json()["detail"][0]["message"]
        == analyze_response.json()["detail"][0]["message"]
    )


def test_list_deals_returns_created_deals(client: TestClient) -> None:
    client.post("/deals", json={"name": "Deal A", "inputs": GOLDEN_PAYLOAD})
    client.post("/deals", json={"name": "Deal B", "inputs": GOLDEN_PAYLOAD})

    response = client.get("/deals")

    assert response.status_code == 200
    names = [deal["name"] for deal in response.json()]
    assert names == ["Deal B", "Deal A"]


def test_list_deals_empty_returns_empty_list(client: TestClient) -> None:
    response = client.get("/deals")

    assert response.status_code == 200
    assert response.json() == []


def test_get_deal_returns_the_created_deal(client: TestClient) -> None:
    created = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()

    response = client.get(f"/deals/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_deal_missing_id_returns_404(client: TestClient) -> None:
    response = client.get("/deals/does-not-exist")

    assert response.status_code == 404


def test_update_deal_persists_new_name_and_inputs(client: TestClient) -> None:
    created = client.post(
        "/deals", json={"name": "Original", "inputs": GOLDEN_PAYLOAD}
    ).json()

    response = client.put(
        f"/deals/{created['id']}",
        json={"name": "Renamed", "inputs": AWKWARD_PAYLOAD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["name"] == "Renamed"
    assert body["inputs"] == AWKWARD_PAYLOAD
    assert body["created_at"] == created["created_at"]


def test_update_deal_missing_id_returns_404(client: TestClient) -> None:
    response = client.put(
        "/deals/does-not-exist", json={"name": "X", "inputs": GOLDEN_PAYLOAD}
    )

    assert response.status_code == 404


def test_update_deal_rejects_invalid_inputs(client: TestClient) -> None:
    created = client.post(
        "/deals", json={"name": "Original", "inputs": GOLDEN_PAYLOAD}
    ).json()

    bad_payload = dict(GOLDEN_PAYLOAD)
    bad_payload["ltv"] = 5.0  # out of [0, 1] domain

    response = client.put(
        f"/deals/{created['id']}", json={"name": "Original", "inputs": bad_payload}
    )

    assert response.status_code == 422
    # The deal must be unchanged -- a rejected update must not partially write.
    unchanged = client.get(f"/deals/{created['id']}").json()
    assert unchanged["inputs"] == GOLDEN_PAYLOAD


# =============================================================================
# The two properties the task explicitly requires.
# =============================================================================


def test_saved_inputs_round_trip_without_changing_economic_meaning(
    client: TestClient,
) -> None:
    created = client.post(
        "/deals", json={"name": "Awkward Deal", "inputs": AWKWARD_PAYLOAD}
    ).json()

    fetched = client.get(f"/deals/{created['id']}").json()

    assert fetched["inputs"] == AWKWARD_PAYLOAD


def test_reopened_deal_analyzed_matches_analyzing_the_original_inputs_directly(
    client: TestClient,
) -> None:
    """The golden proof: Save Deal -> Reopen Deal -> resubmit its inputs to
    the existing, unmodified ``/analyze`` must produce identical results to
    analyzing the original inputs directly -- persistence introduces zero
    numeric drift anywhere in the round trip."""

    direct_result = client.post("/analyze", json=GOLDEN_PAYLOAD)
    assert direct_result.status_code == 200

    created = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()
    reopened = client.get(f"/deals/{created['id']}").json()
    reanalyzed_result = client.post("/analyze", json=reopened["inputs"])
    assert reanalyzed_result.status_code == 200

    assert reanalyzed_result.json() == direct_result.json()

    # And both match the engine called directly -- not just each other.
    expected = analyze_acquisition(GOLDEN_INPUTS)
    assert reanalyzed_result.json()["levered_irr"] == pytest.approx(expected.levered_irr)
    assert reanalyzed_result.json()["equity_multiple"] == pytest.approx(
        expected.equity_multiple
    )


# =============================================================================
# Persistence Phase C -- DELETE /deals/{id}, POST /deals/{id}/duplicate
# =============================================================================


def test_delete_deal_returns_204(client: TestClient) -> None:
    created = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()

    response = client.delete(f"/deals/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""


def test_deleted_deal_is_gone(client: TestClient) -> None:
    created = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()

    client.delete(f"/deals/{created['id']}")

    assert client.get(f"/deals/{created['id']}").status_code == 404
    assert client.get("/deals").json() == []


def test_delete_deal_missing_id_returns_404(client: TestClient) -> None:
    response = client.delete("/deals/does-not-exist")

    assert response.status_code == 404


def test_duplicate_deal_returns_a_new_deal_with_a_new_id(client: TestClient) -> None:
    original = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()

    response = client.post(f"/deals/{original['id']}/duplicate", json={})

    assert response.status_code == 200
    copy = response.json()
    assert copy["id"] != original["id"]
    assert copy["inputs"] == GOLDEN_PAYLOAD
    assert copy["name"] == "111 Main St (Copy)"


def test_duplicate_deal_accepts_a_name_override(client: TestClient) -> None:
    original = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()

    response = client.post(
        f"/deals/{original['id']}/duplicate", json={"name": "222 Oak Ave"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "222 Oak Ave"


def test_duplicate_deal_does_not_mutate_the_original(client: TestClient) -> None:
    original = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()

    client.post(f"/deals/{original['id']}/duplicate", json={})

    unchanged = client.get(f"/deals/{original['id']}").json()
    assert unchanged == original


def test_duplicate_deal_missing_id_returns_404(client: TestClient) -> None:
    response = client.post("/deals/does-not-exist/duplicate", json={})

    assert response.status_code == 404


def test_duplicate_deal_appears_in_the_library_alongside_the_original(
    client: TestClient,
) -> None:
    original = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()

    copy = client.post(f"/deals/{original['id']}/duplicate", json={}).json()

    ids = {deal["id"] for deal in client.get("/deals").json()}
    assert ids == {original["id"], copy["id"]}


def test_duplicated_deal_reanalyzed_matches_the_original_deterministic_result(
    client: TestClient,
) -> None:
    """The Phase C counterpart of the Phase A reopen-round-trip proof:
    duplicating a deal and resubmitting the copy's inputs to the existing
    /analyze produces exactly the same result as analyzing the original --
    duplication introduces zero numeric drift and the deterministic engine
    is never bypassed."""

    direct_result = client.post("/analyze", json=GOLDEN_PAYLOAD)
    assert direct_result.status_code == 200

    original = client.post(
        "/deals", json={"name": "111 Main St", "inputs": GOLDEN_PAYLOAD}
    ).json()
    copy = client.post(f"/deals/{original['id']}/duplicate", json={}).json()
    reopened_copy = client.get(f"/deals/{copy['id']}").json()

    reanalyzed_result = client.post("/analyze", json=reopened_copy["inputs"])

    assert reanalyzed_result.status_code == 200
    assert reanalyzed_result.json() == direct_result.json()
