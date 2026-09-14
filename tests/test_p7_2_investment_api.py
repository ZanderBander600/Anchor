"""Phase 7 Gate P7.2 -- the Investment and Scenario API.

The backend P7.3 builds on: create the first Scenario from a standalone Deal
(materializing the hidden Investment), list, read, update and delete Scenarios,
inspect the Investment, obtain a Scenario's resolved-input fingerprint, and
analyse it -- a current Quick or Detailed cached result when valid, a
deterministic Lease-Level recomputation always.

Every row count is read from the database directly.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from anchor import api as api_module
from anchor.business_plan import BusinessPlan
from anchor.deals import store

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from _p7_2_fixtures import (  # type: ignore[import-not-found]
    EMPTY,
    MODES,
    create_deal,
    deal_fingerprint,
    execute,
    row_counts,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "api.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(api_module.app)


def _ok(response: Any) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


#: One economically material override per mode, on the wire.
_WIRE_ECONOMIC = {
    "quick": {"target": "exit_cap_rate", "operation": "add", "value": 0.005},
    "detailed": {"target": "vacancy_credit_loss_pct", "operation": "add", "value": 0.02},
    "lease_level": {"target": "market_rent_psf", "operation": "scale", "value": 0.9},
}


def _body(mode: str, deal_id: str, **extra: Any) -> dict[str, Any]:
    return {"name": "Downside", "overrides": [{"unit_id": deal_id, **_WIRE_ECONOMIC[mode]}], **extra}


def _first_scenario(client: TestClient, db: Path, mode: str) -> tuple[Any, dict[str, Any]]:
    deal = create_deal(mode, db)
    return deal, _ok(client.post(f"/deals/{deal.id}/scenarios", json=_body(mode, deal.id)))


def _path(created: dict[str, Any], suffix: str = "") -> str:
    return f"/investments/{created['investment_id']}/scenarios/{created['scenario']['scenario_id']}{suffix}"


# =============================================================================
# Opt-in and read-only routes
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_no_ordinary_or_read_route_materializes_an_investment(client: TestClient, db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    state = _ok(client.get(f"/deals/{deal.id}"))
    body: dict[str, Any] = {"operating_mode": mode, "business_plan": state["business_plan"]}
    if mode == "quick":
        body["inputs"] = state["inputs"]
        analyze_body = {**state["inputs"], "business_plan": state["business_plan"]}
    else:
        body["terms"] = state["terms"]
        if mode == "detailed":
            body["detailed_operating_inputs"] = state["detailed_operating_inputs"]
        else:
            for key in ("property_inputs", "operating_inputs", "market_leasing", "suites", "leases"):
                body[key] = state[key]
        analyze_body = body

    _ok(client.get("/deals"))
    _ok(client.post("/deals/fingerprint", json=body))
    _ok(client.post("/analyze", json=analyze_body))
    listed = _ok(client.get(f"/deals/{deal.id}/scenarios"))

    assert listed == {"deal_id": deal.id, "investment_id": None, "scenarios": []}
    assert row_counts(db) == EMPTY


@pytest.mark.parametrize("mode", MODES)
def test_the_first_scenario_materializes_the_hidden_investment(client: TestClient, db: Path, mode: str) -> None:
    deal, created = _first_scenario(client, db, mode)

    assert set(created) == {"investment_id", "scenario", "created_at", "updated_at"}
    assert created["scenario"]["name"] == "Downside"
    assert created["scenario"]["description"] is None
    assert created["scenario"]["overrides"] == [{"unit_id": deal.id, **_WIRE_ECONOMIC[mode]}]
    investment = _ok(client.get(f"/investments/{created['investment_id']}"))
    assert (investment["id"], investment["hidden"], investment["units"]) == (
        created["investment_id"], True, [{"unit_id": deal.id}],
    )
    assert row_counts(db)["investments"] == 1
    assert _ok(client.get(f"/deals/{deal.id}/scenarios")) == {
        "deal_id": deal.id, "investment_id": created["investment_id"], "scenarios": [created],
    }


def test_the_scenario_crud_round_trip(client: TestClient, db: Path) -> None:
    deal, created = _first_scenario(client, db, "quick")
    investment_id = created["investment_id"]
    second = _ok(client.post(f"/investments/{investment_id}/scenarios", json={"name": "Upside"}))
    assert second["investment_id"] == investment_id

    assert _ok(client.get(f"/investments/{investment_id}/scenarios")) == [created, second]
    assert _ok(client.get(_path(created))) == created

    updated = _ok(client.put(_path(created), json={
        "name": "Renamed", "description": "Edited",
        "overrides": [{"unit_id": deal.id, "target": "interest_rate", "operation": "add", "value": 0.01}],
    }))
    assert updated["scenario"]["scenario_id"] == created["scenario"]["scenario_id"]
    assert (updated["scenario"]["name"], updated["scenario"]["description"]) == ("Renamed", "Edited")
    assert updated["created_at"] == created["created_at"]

    assert client.delete(_path(created)).status_code == 204
    assert _ok(client.get(f"/investments/{investment_id}/scenarios")) == [second]
    assert client.get(_path(created)).status_code == 404


def test_deleting_the_last_scenario_collapses_the_wrapper(client: TestClient, db: Path) -> None:
    deal, created = _first_scenario(client, db, "detailed")

    assert client.delete(_path(created)).status_code == 204

    assert row_counts(db) == EMPTY
    assert _ok(client.get(f"/deals/{deal.id}/scenarios"))["investment_id"] is None
    assert client.get(f"/investments/{created['investment_id']}").status_code == 404


def test_deleting_the_investment_releases_the_deal(client: TestClient, db: Path) -> None:
    deal, created = _first_scenario(client, db, "lease_level")
    before = _ok(client.get(f"/deals/{deal.id}"))

    assert client.delete(f"/investments/{created['investment_id']}").status_code == 204

    assert row_counts(db) == EMPTY
    assert _ok(client.get(f"/deals/{deal.id}")) == before


def test_deleting_the_wrappers_deal_removes_the_wrapper(client: TestClient, db: Path) -> None:
    deal, _ = _first_scenario(client, db, "quick")

    assert client.delete(f"/deals/{deal.id}").status_code == 204

    assert row_counts(db) == EMPTY
    assert client.get(f"/deals/{deal.id}").status_code == 404


# =============================================================================
# Fingerprint and analysis
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_fingerprint_route_fingerprints_the_resolved_inputs(client: TestClient, db: Path, mode: str) -> None:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    neutral = _ok(client.post(f"/deals/{deal.id}/scenarios", json={"name": "Neutral"}))
    downside = _ok(client.post(f"/deals/{deal.id}/scenarios", json=_body(mode, deal.id)))

    neutral_fp = _ok(client.get(_path(neutral, "/fingerprint")))
    downside_fp = _ok(client.get(_path(downside, "/fingerprint")))

    assert neutral_fp == {
        "investment_id": neutral["investment_id"],
        "scenario_id": neutral["scenario"]["scenario_id"],
        "unit_id": deal.id,
        "operating_mode": mode,
        "source_fingerprint": deal_fingerprint(deal),
    }
    assert downside_fp["source_fingerprint"] != neutral_fp["source_fingerprint"]


def _hand_resolved_analyze_body(mode: str) -> dict[str, Any]:
    """The ``POST /analyze`` body for the fixture Deal with the economic
    override typed in by hand."""

    if mode == "quick":
        inputs = dataclasses.replace(fx.quick_inputs(), exit_cap_rate=fx.quick_inputs().exit_cap_rate + 0.005)
        return dataclasses.asdict(inputs)
    if mode == "detailed":
        operating = fx.detailed_operating()
        return {
            "operating_mode": "detailed",
            "terms": dataclasses.asdict(fx.detailed_terms()),
            "detailed_operating_inputs": dataclasses.asdict(
                dataclasses.replace(operating, vacancy_credit_loss_pct=operating.vacancy_credit_loss_pct + 0.02)
            ),
        }
    return {}


@pytest.mark.parametrize("mode", ["quick", "detailed"])
def test_the_analysis_route_reports_a_miss_then_a_current_hit(client: TestClient, db: Path, mode: str) -> None:
    _, created = _first_scenario(client, db, mode)

    first = _ok(client.post(_path(created, "/analysis")))
    second = _ok(client.post(_path(created, "/analysis")))
    by_hand = _ok(client.post("/analyze", json=_hand_resolved_analyze_body(mode)))

    assert (first["cache_status"], second["cache_status"]) == ("miss", "hit")
    assert first["results"] == second["results"] == by_hand
    assert first["source_fingerprint"] == _ok(client.get(_path(created, "/fingerprint")))["source_fingerprint"]
    assert row_counts(db)["variant_snapshots"] == 1


def test_the_analysis_route_recomputes_lease_level_and_says_so(client: TestClient, db: Path) -> None:
    _, created = _first_scenario(client, db, "lease_level")

    first = _ok(client.post(_path(created, "/analysis")))
    second = _ok(client.post(_path(created, "/analysis")))

    assert (first["cache_status"], second["cache_status"]) == ("bypassed", "bypassed")
    assert first["results"] == second["results"]
    assert set(first["results"]) == {"monthly_projection", "annual_projection", "results"}
    assert row_counts(db)["variant_snapshots"] == 0


def test_an_invalid_variant_is_a_structured_422_from_both_routes(client: TestClient, db: Path) -> None:
    deal = create_deal("lease_level", db)
    created = _ok(client.post(f"/deals/{deal.id}/scenarios", json={
        "name": "Too high", "overrides": [{"unit_id": deal.id, "target": "renewal_probability", "operation": "add", "value": 0.5}],
    }))

    for response in (client.get(_path(created, "/fingerprint")), client.post(_path(created, "/analysis"))):
        assert response.status_code == 422
        (issue,) = response.json()["detail"]
        assert (issue["stage"], issue["code"], issue["target"], issue["unit_id"]) == (
            "resolved_inputs", "resolved_input_invalid", "renewal_probability", deal.id,
        )


# =============================================================================
# Deterministic errors
# =============================================================================


def test_contract_errors_are_the_p7_1_issues_in_the_p7_1_order(client: TestClient, db: Path) -> None:
    """P7.1 orders issues by identity, then unknown targets, then address --
    units in sorted order, targets in registry order. The foreign unit id is
    chosen to sort after any minted (hexadecimal) deal id, so the expected
    order is fixed whatever id the deal was given."""

    deal = create_deal("quick", db)
    foreign = "zzz-another-deal"
    overrides = [
        {"unit_id": deal.id, "target": "ltv", "operation": "set", "value": 0.5},
        {"unit_id": deal.id, "target": "interest_rate", "operation": "divide", "value": 0.01},
        {"unit_id": foreign, "target": "exit_cap_rate", "operation": "add", "value": 0.01},
        {"unit_id": deal.id, "target": "not_a_target", "operation": "add", "value": 0.01},
        {"unit_id": deal.id, "target": "exit_cap_rate", "operation": "add", "value": True},
    ]
    responses = [
        client.post(f"/deals/{deal.id}/scenarios", json={"name": " ", "overrides": order})
        for order in (overrides, list(reversed(overrides)), overrides)
    ]

    assert {response.status_code for response in responses} == {422}
    details = [response.json()["detail"] for response in responses]
    assert details[0] == details[1] == details[2]
    assert [(issue["code"], issue["target"], issue["unit_id"]) for issue in details[0]] == [
        ("invalid_scenario_name", None, None),
        ("unknown_target", None, deal.id),
        ("non_numeric_value", "exit_cap_rate", deal.id),
        ("unknown_operation", "interest_rate", deal.id),
        ("operation_not_allowed", "ltv", deal.id),
        ("unit_not_in_variant", "exit_cap_rate", foreign),
    ]
    assert row_counts(db) == EMPTY


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"name": "S", "scenario_id": "mine"}, "Unknown scenario field(s): scenario_id"),
        ({"name": "S", "investment_id": "theirs"}, "Unknown scenario field(s): investment_id"),
        ({"name": "S", "overrides": {"target": "ltv"}}, "'overrides' must be an array"),
        ({"name": "S", "overrides": ["ltv"]}, "overrides[0] must be an object"),
        ({"name": "S", "overrides": [{"target": "ltv", "operation": "cap_at", "value": 0.5}]}, "missing: ['unit_id']"),
        ({"name": "S", "overrides": [{"unit_id": "u", "target": "ltv", "operation": "cap_at", "value": 0.5, "rank": 1}]}, "unknown: ['rank']"),
    ],
)
def test_structural_errors_are_refused_before_anything_is_judged(
    client: TestClient, db: Path, body: dict[str, Any], fragment: str
) -> None:
    deal = create_deal("quick", db)
    response = client.post(f"/deals/{deal.id}/scenarios", json=body)

    assert response.status_code == 422
    assert fragment in response.json()["detail"]
    assert row_counts(db) == EMPTY


def test_unknown_ids_are_404(client: TestClient, db: Path) -> None:
    store.list_deals(db_path=db)
    missing = "f" * 32
    for response in (
        client.post(f"/deals/{missing}/scenarios", json={"name": "S"}),
        client.get(f"/deals/{missing}/scenarios"),
        client.get(f"/investments/{missing}"),
        client.delete(f"/investments/{missing}"),
        client.get(f"/investments/{missing}/scenarios"),
        client.post(f"/investments/{missing}/scenarios", json={"name": "S"}),
    ):
        assert response.status_code == 404, response.text
    assert row_counts(db) == EMPTY


def test_a_foreign_scenario_id_is_never_reachable_through_another_investment(client: TestClient, db: Path) -> None:
    _, mine = _first_scenario(client, db, "quick")
    _, theirs = _first_scenario(client, db, "quick")
    foreign = f"/investments/{mine['investment_id']}/scenarios/{theirs['scenario']['scenario_id']}"

    for response in (
        client.get(foreign),
        client.put(foreign, json={"name": "Hijack"}),
        client.delete(foreign),
        client.get(f"{foreign}/fingerprint"),
        client.post(f"{foreign}/analysis"),
    ):
        assert response.status_code == 404, response.text
    assert _ok(client.get(_path(theirs))) == theirs


def test_an_override_on_a_unit_outside_the_investment_is_refused(client: TestClient, db: Path) -> None:
    _, mine = _first_scenario(client, db, "quick")
    other = create_deal("quick", db)

    response = client.put(_path(mine), json={
        "name": "S", "overrides": [{"unit_id": other.id, "target": "exit_cap_rate", "operation": "add", "value": 0.01}],
    })

    assert response.status_code == 422
    assert [issue["code"] for issue in response.json()["detail"]] == ["unit_not_in_variant"]
    assert _ok(client.get(_path(mine))) == mine


def test_a_visible_investment_is_a_409_and_its_deal_survives(client: TestClient, db: Path) -> None:
    deal = create_deal("quick", db)
    execute(db, "INSERT INTO investments VALUES (?, 0, 'now', 'now')", ("v" * 32,))
    execute(db, "INSERT INTO investment_units VALUES (?, ?)", ("v" * 32, deal.id))

    assert client.post(f"/deals/{deal.id}/scenarios", json={"name": "S"}).status_code == 409
    assert client.delete(f"/deals/{deal.id}").status_code == 409
    assert client.delete(f"/investments/{'v' * 32}").status_code == 409
    assert _ok(client.get(f"/deals/{deal.id}"))["id"] == deal.id


def test_success_payloads_are_deterministic(client: TestClient, db: Path) -> None:
    _, created = _first_scenario(client, db, "detailed")
    assert _ok(client.get(_path(created))) == _ok(client.get(_path(created)))
    assert _ok(client.get(_path(created, "/fingerprint"))) == _ok(client.get(_path(created, "/fingerprint")))
    assert jsonable_encoder(BusinessPlan()) == {"capital_items": [], "owner_expense_items": []}
