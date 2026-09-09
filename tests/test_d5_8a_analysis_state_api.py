"""D5.8A -- the HTTP surface the browser actually persists through.

Two narrow endpoints, and the existing ``PUT /deals/{id}/ai-snapshot`` reaching a
third mode for the first time. Every claim here is about the seam: that the
frontend can save a completed analysis, that it gets it back on the next
``GET /deals/{id}``, that a caller cannot certify a snapshot against assumptions
the deal does not hold, and that a refusal is refused with the right status
rather than accepted quietly.

The repository-level guarantees these ride on -- durability, exact round trip,
independence, staleness -- are proved in
``tests/test_d5_8a_deal_analysis_persistence.py``; this file does not restate
them, it checks that the wire preserves them.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from anchor.api import app
from anchor.deals import store as deals_store

from tests.test_d5_8a_deal_analysis_persistence import (
    AI_ANALYSIS,
    ONE_WAY,
    ONE_WAY_VALUES,
    TWO_WAY,
    as_dict,
    store_all,
)
from tests.test_d5_4_lease_level_persistence import (
    LEASES,
    MARKET_LEASING,
    OPERATING_INPUTS,
    PROPERTY_INPUTS,
    SUITES,
    TERMS,
    store_deal,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private database, wired in through the same environment variable the
    application resolves on every call -- so the endpoints under test read and
    write exactly where this file can inspect."""

    path = tmp_path / "d5-8a-api.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def wire(value: Any) -> Any:
    """The JSON a client would actually send: enums as their wire tokens, dates
    as ISO-8601, tuples as arrays."""

    return json.loads(json.dumps(jsonable_encoder(value)))


def fingerprint_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "operating_mode": "lease_level",
        "terms": wire(TERMS),
        "property_inputs": wire(PROPERTY_INPUTS),
        "operating_inputs": wire(OPERATING_INPUTS),
        "market_leasing": wire(MARKET_LEASING),
        "suites": wire(SUITES),
        "leases": wire(LEASES),
    }
    body.update(overrides)
    return body


def fingerprints(client: TestClient, **overrides: Any) -> dict[str, str]:
    response = client.post("/deals/fingerprint", json=fingerprint_body(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


# =============================================================================
# The write endpoints
# =============================================================================


def test_a_lease_level_ai_report_can_finally_be_saved_over_http(
    db: Path, client: TestClient
) -> None:
    """The defect, at the seam where it was visible.

    ``PUT /deals/{id}/ai-snapshot`` has existed since Gate A6, and returned 404
    for every Lease-Level deal because the store stopped looking after the
    Detailed table. No new endpoint was needed -- only the third arm behind it.
    """

    deal = store_deal(db)
    tokens = fingerprints(client)

    response = client.put(
        f"/deals/{deal.id}/ai-snapshot",
        json={
            "ai_snapshot": as_dict(AI_ANALYSIS),
            "ai_context_fingerprint": tokens["ai_context_fingerprint"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["ai_snapshot"]["executive_summary"] == AI_ANALYSIS.executive_summary


@pytest.mark.parametrize(
    ("kind", "snapshot"),
    [("one-way", ONE_WAY), ("two-way", TWO_WAY)],
)
def test_a_completed_sensitivity_run_is_saved_and_returned_on_the_next_get(
    db: Path, client: TestClient, kind: str, snapshot: Any
) -> None:
    """The whole product claim, over HTTP: run it, save it, fetch the deal
    again, and it is there -- configuration and result together."""

    deal = store_deal(db)
    tokens = fingerprints(client)

    saved = client.put(
        f"/deals/{deal.id}/sensitivity-snapshot/{kind}",
        json={
            "sensitivity_snapshot": as_dict(snapshot),
            "financial_input_fingerprint": tokens["financial_input_fingerprint"],
        },
    )
    assert saved.status_code == 200, saved.text

    reopened = client.get(f"/deals/{deal.id}")
    assert reopened.status_code == 200
    field = "one_way_sensitivity_snapshot" if kind == "one-way" else "two_way_sensitivity_snapshot"
    payload = reopened.json()[field]
    assert payload is not None
    assert payload == wire(snapshot)


def test_the_candidate_values_survive_the_wire_in_order(db: Path, client: TestClient) -> None:
    """The visible candidate values are the analyst's own strings, and the wire
    neither reorders, reformats nor renumbers them."""

    deal = store_deal(db)
    tokens = fingerprints(client)
    client.put(
        f"/deals/{deal.id}/sensitivity-snapshot/one-way",
        json={
            "sensitivity_snapshot": as_dict(ONE_WAY),
            "financial_input_fingerprint": tokens["financial_input_fingerprint"],
        },
    )

    payload = client.get(f"/deals/{deal.id}").json()["one_way_sensitivity_snapshot"]
    assert payload["configuration"]["values"] == list(ONE_WAY_VALUES)
    # And the undefined metric is still ``null`` on the wire, never 0.
    assert payload["result"]["metric_values"][2] is None


def test_the_matrix_keeps_its_orientation_on_the_wire(db: Path, client: TestClient) -> None:
    """3 rows x 2 columns in, 3 rows x 2 columns out, row-major."""

    deal = store_deal(db)
    tokens = fingerprints(client)
    client.put(
        f"/deals/{deal.id}/sensitivity-snapshot/two-way",
        json={
            "sensitivity_snapshot": as_dict(TWO_WAY),
            "financial_input_fingerprint": tokens["financial_input_fingerprint"],
        },
    )

    payload = client.get(f"/deals/{deal.id}").json()["two_way_sensitivity_snapshot"]
    matrix = payload["result"]["matrix"]
    assert len(matrix) == 3 and all(len(row) == 2 for row in matrix)
    assert matrix == [[1.61, 1.83], [1.72, 1.95], [None, 1.89]]
    assert payload["configuration"]["row_assumption"] == "exit_cap_rate"
    assert payload["configuration"]["column_assumption"] == "purchase_price"


# =============================================================================
# Refusals
# =============================================================================


def test_a_snapshot_whose_provenance_does_not_match_is_rejected_422(
    db: Path, client: TestClient
) -> None:
    """The Gate A7 contract, extended. The caller's token only unlocks a write
    the backend's own recomputation already agrees with."""

    deal = store_deal(db)
    edited = dataclasses.replace(TERMS, purchase_price=51_000_000.0)
    other_tokens = fingerprints(client, terms=wire(edited))

    response = client.put(
        f"/deals/{deal.id}/sensitivity-snapshot/one-way",
        json={
            "sensitivity_snapshot": as_dict(ONE_WAY),
            "financial_input_fingerprint": other_tokens["financial_input_fingerprint"],
        },
    )

    assert response.status_code == 422
    assert client.get(f"/deals/{deal.id}").json()["one_way_sensitivity_snapshot"] is None


def test_a_malformed_snapshot_is_rejected_422(db: Path, client: TestClient) -> None:
    deal = store_deal(db)
    tokens = fingerprints(client)

    response = client.put(
        f"/deals/{deal.id}/sensitivity-snapshot/two-way",
        json={
            "sensitivity_snapshot": {"configuration": {"metric": "levered_irr"}},
            "financial_input_fingerprint": tokens["financial_input_fingerprint"],
        },
    )
    assert response.status_code == 422


def test_a_missing_field_is_reported_rather_than_defaulted(
    db: Path, client: TestClient
) -> None:
    deal = store_deal(db)

    missing_snapshot = client.put(
        f"/deals/{deal.id}/sensitivity-snapshot/one-way",
        json={"financial_input_fingerprint": "x"},
    )
    assert missing_snapshot.status_code == 422
    assert "sensitivity_snapshot" in missing_snapshot.json()["detail"]

    missing_token = client.put(
        f"/deals/{deal.id}/sensitivity-snapshot/one-way",
        json={"sensitivity_snapshot": as_dict(ONE_WAY)},
    )
    assert missing_token.status_code == 422
    assert "financial_input_fingerprint" in missing_token.json()["detail"]


def test_an_unknown_deal_is_404(db: Path, client: TestClient) -> None:
    response = client.put(
        "/deals/no-such-deal/sensitivity-snapshot/one-way",
        json={
            "sensitivity_snapshot": as_dict(ONE_WAY),
            "financial_input_fingerprint": "x",
        },
    )
    assert response.status_code == 404


def test_a_quick_deal_is_refused_as_an_unsupported_mode_not_as_missing(
    db: Path, client: TestClient
) -> None:
    """D5.1A's distinction, preserved at the new endpoint: a real deal in a mode
    this surface does not serve is a 422 naming the mode, never a 404 implying
    the deal does not exist."""

    created = client.post(
        "/deals",
        json={
            "name": "Quick",
            "inputs": {
                "purchase_price": 50_000_000,
                "current_noi": 2_500_000,
                "occupancy": 0.95,
                "noi_growth": 0.03,
                "hold_period": 5,
                "exit_cap_rate": 0.055,
                "ltv": 0.65,
                "interest_rate": 0.0525,
                "amortization": 30,
            },
        },
    )
    assert created.status_code == 200, created.text
    deal_id = created.json()["id"]

    response = client.put(
        f"/deals/{deal_id}/sensitivity-snapshot/one-way",
        json={
            "sensitivity_snapshot": as_dict(ONE_WAY),
            "financial_input_fingerprint": "x",
        },
    )
    assert response.status_code == 422
    assert "quick" in response.json()["detail"]


# =============================================================================
# Isolation and lifecycle, over HTTP
# =============================================================================


def test_two_deals_stay_isolated_across_the_wire(db: Path, client: TestClient) -> None:
    """The reported defect, driven exactly as the analyst hits it: open A, open
    B, open A again. Every read is a fresh request; nothing is held between
    them."""

    deal_a = store_all(db, name="Deal A")
    deal_b = store_deal(db, name="Deal B")

    a_first = client.get(f"/deals/{deal_a.id}").json()
    b = client.get(f"/deals/{deal_b.id}").json()
    a_again = client.get(f"/deals/{deal_a.id}").json()

    assert a_first["ai_snapshot"] is not None
    assert a_first["one_way_sensitivity_snapshot"] is not None
    assert a_first["two_way_sensitivity_snapshot"] is not None

    assert b["ai_snapshot"] is None
    assert b["one_way_sensitivity_snapshot"] is None
    assert b["two_way_sensitivity_snapshot"] is None

    assert a_again == a_first


def test_an_underwriting_edit_over_http_stops_presenting_the_analysis(
    db: Path, client: TestClient
) -> None:
    deal = store_all(db)

    updated = client.put(
        f"/deals/{deal.id}",
        json={
            "operating_mode": "lease_level",
            "name": deal.name,
            "terms": wire(dataclasses.replace(TERMS, purchase_price=51_000_000.0)),
            "property_inputs": wire(PROPERTY_INPUTS),
            "operating_inputs": wire(OPERATING_INPUTS),
            "market_leasing": wire(MARKET_LEASING),
            "suites": wire(SUITES),
            "leases": wire(LEASES),
        },
    )
    assert updated.status_code == 200, updated.text

    reopened = client.get(f"/deals/{deal.id}").json()
    assert reopened["ai_snapshot"] is None
    assert reopened["one_way_sensitivity_snapshot"] is None
    assert reopened["two_way_sensitivity_snapshot"] is None


def test_duplicating_over_http_inherits_no_analysis(db: Path, client: TestClient) -> None:
    deal = store_all(db)

    copy = client.post(f"/deals/{deal.id}/duplicate", json={}).json()

    assert copy["id"] != deal.id
    assert copy["ai_snapshot"] is None
    assert copy["one_way_sensitivity_snapshot"] is None
    assert copy["two_way_sensitivity_snapshot"] is None


def test_deleting_over_http_removes_the_derived_analysis(
    db: Path, client: TestClient
) -> None:
    deal = store_all(db)

    assert client.delete(f"/deals/{deal.id}").status_code == 204
    assert client.get(f"/deals/{deal.id}").status_code == 404

    import sqlite3

    connection = sqlite3.connect(db)
    orphans = connection.execute(
        "SELECT COUNT(*) FROM deal_sensitivity_snapshots WHERE deal_id = ?", (deal.id,)
    ).fetchone()[0]
    connection.close()
    assert orphans == 0


def test_the_deal_library_listing_stays_a_lightweight_summary(
    db: Path, client: TestClient
) -> None:
    """``list_deals`` must not start shipping every saved deal's full analysis.

    The Library shows names, modes and timestamps; carrying three JSON payloads
    per row would make opening it proportional to how much analysis the user has
    ever done.
    """

    store_all(db, name="Analyzed")

    listed = client.get("/deals").json()
    assert len(listed) == 1
    assert listed[0]["ai_snapshot"] is None
    assert listed[0]["one_way_sensitivity_snapshot"] is None
    assert listed[0]["two_way_sensitivity_snapshot"] is None
    # The single-deal fetch is where the analysis lives.
    assert client.get(f"/deals/{listed[0]['id']}").json()["ai_snapshot"] is not None


def test_no_analysis_snapshot_appears_for_a_lease_level_deal(
    db: Path, client: TestClient
) -> None:
    """D5 decision A is not reversed by this gate.

    The AI report and the two sensitivity runs are restored against the input
    fingerprint directly. No cached base Lease-Level financial result is stored,
    returned, or needed to prove any of them current.
    """

    deal = store_all(db)
    payload = client.get(f"/deals/{deal.id}").json()

    assert payload["analysis_snapshot"] is None
    assert payload["ai_snapshot"] is not None
    assert payload["one_way_sensitivity_snapshot"] is not None


def test_the_stored_state_is_visible_to_a_second_service_instance(
    db: Path, client: TestClient
) -> None:
    """Persistence, not memory: a second ``TestClient`` over the same app makes
    its own connections and shares no request state with the first."""

    deal = store_all(db)
    client.get(f"/deals/{deal.id}")

    second = TestClient(app)
    payload = second.get(f"/deals/{deal.id}").json()

    assert payload["ai_snapshot"] is not None
    assert payload["one_way_sensitivity_snapshot"] == wire(ONE_WAY)
    assert payload["two_way_sensitivity_snapshot"] == wire(TWO_WAY)


def test_the_store_is_where_the_endpoints_actually_wrote(db: Path, client: TestClient) -> None:
    """The endpoints are not a facade over request-scoped state: what they wrote
    is readable through the repository directly, with no HTTP involved."""

    deal = store_deal(db)
    tokens = fingerprints(client)
    client.put(
        f"/deals/{deal.id}/sensitivity-snapshot/one-way",
        json={
            "sensitivity_snapshot": as_dict(ONE_WAY),
            "financial_input_fingerprint": tokens["financial_input_fingerprint"],
        },
    )

    assert deals_store.get_deal(deal.id, db_path=db).one_way_sensitivity_snapshot == ONE_WAY
