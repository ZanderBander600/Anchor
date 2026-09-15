"""Phase 7 Gate P7.4 -- the Strategy and variant API.

The backend P7.5 builds the Strategy x Scenario matrix on:
- create the first Strategy from a standalone Deal, which materializes the
  hidden Investment or reuses the one its Scenarios created;
- list, read, update and delete Strategies;
- inspect any variant's resolved inputs;
- read its resolved-input fingerprint;
- analyse it: a current Quick or Detailed cached result when valid, a
  deterministic Lease-Level recomputation always.

Every row count is read from the database directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from anchor import api as api_module
from anchor.business_plan import BusinessPlan

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
import _p7_4_fixtures as f4  # type: ignore[import-not-found]
from _p7_2_fixtures import MODES, create_deal, deal_fingerprint  # type: ignore[import-not-found]

BASE = "base"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "api.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(api_module.app)


def _ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if status != 204 else None


_OUTCOME = {"quick": ("noi_growth", 0.04), "detailed": ("revenue_growth", 0.04), "lease_level": ("market_rent_psf", 42.0)}


def _overlays(mode: str, unit: str) -> list[dict[str, Any]]:
    """Every domain on the wire, in canonical order (as the API returns it)."""

    return [
        f4.wire(f4.acquisition(unit, purchase_price=9_000_000.0)),
        f4.wire(f4.financing(unit)),
        f4.wire(f4.plan_overlay(unit, f4.renovation_plan())),
        f4.wire(f4.outcomes(unit, f4.outcome("exit_cap_rate", 0.06), f4.outcome(*_OUTCOME[mode]))),
        f4.wire(f4.disposition(unit, 7)),
    ]


def _first(client: TestClient, db: Path, mode: str, overlays: Any = None) -> tuple[Any, dict[str, Any]]:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    body = {"name": "Renovate", "overlays": _overlays(mode, deal.id) if overlays is None else overlays}
    return deal, _ok(client.post(f"/deals/{deal.id}/strategies", json=body))


def _path(created: dict[str, Any]) -> str:
    return f"/investments/{created['investment_id']}/strategies/{created['strategy']['strategy_id']}"


def _variant(created: dict[str, Any], scenario_id: str = BASE, suffix: str = "") -> str:
    return f"/investments/{created['investment_id']}/variants/{created['strategy']['strategy_id']}/{scenario_id}{suffix}"


def _state_body(state: dict[str, Any], mode: str) -> dict[str, Any]:
    body: dict[str, Any] = {"operating_mode": mode, "business_plan": state["business_plan"]}
    if mode == "quick":
        body["inputs"] = state["inputs"]
    else:
        body["terms"] = state["terms"]
        if mode == "detailed":
            body["detailed_operating_inputs"] = state["detailed_operating_inputs"]
        else:
            for key in ("property_inputs", "operating_inputs", "market_leasing", "suites", "leases"):
                body[key] = state[key]
    return body


def _analyze_body(resolved: dict[str, Any], mode: str) -> dict[str, Any]:
    """``POST /analyze`` for resolved inputs typed by hand -- the ordinary path."""

    if mode == "quick":
        return {**resolved["inputs"], "business_plan": resolved["business_plan"]}
    if mode == "detailed":
        return {
            "operating_mode": mode, "terms": resolved["terms"],
            "detailed_operating_inputs": resolved["detailed_operating_inputs"], "business_plan": resolved["business_plan"],
        }
    return {"operating_mode": mode, **resolved}


# =============================================================================
# Opt-in, read-only routes and the round trip
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_no_ordinary_or_strategy_read_route_materializes_an_investment(client: TestClient, db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    state = _ok(client.get(f"/deals/{deal.id}"))
    body = _state_body(state, mode)

    _ok(client.get("/deals"))
    _ok(client.post("/deals/fingerprint", json=body))
    _ok(client.post("/analyze", json=body if mode != "quick" else {**state["inputs"], "business_plan": state["business_plan"]}))
    listed = _ok(client.get(f"/deals/{deal.id}/strategies"))
    assert client.get(f"/investments/{'0' * 32}/strategies").status_code == 404

    assert listed == {"deal_id": deal.id, "investment_id": None, "strategies": []}
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


@pytest.mark.parametrize("mode", MODES)
def test_the_first_strategy_materializes_the_hidden_investment_and_round_trips(client: TestClient, db: Path, mode: str) -> None:
    deal, created = _first(client, db, mode)

    assert set(created) == {"investment_id", "strategy", "created_at", "updated_at"}
    assert created["strategy"]["name"] == "Renovate" and created["strategy"]["description"] is None
    assert created["strategy"]["overlays"] == _overlays(mode, deal.id)
    investment = _ok(client.get(f"/investments/{created['investment_id']}"))
    assert (investment["hidden"], investment["units"]) == (True, [{"unit_id": deal.id}])
    assert _ok(client.get(f"/deals/{deal.id}/strategies")) == {
        "deal_id": deal.id, "investment_id": created["investment_id"], "strategies": [created],
    }
    assert _ok(client.get(_path(created))) == created
    assert _ok(client.get(f"/investments/{created['investment_id']}/strategies")) == [created]


def test_a_response_can_be_sent_back_unchanged(client: TestClient, db: Path) -> None:
    _, created = _first(client, db, "lease_level")
    fingerprint = _ok(client.get(_variant(created, suffix="/fingerprint")))
    strategy = created["strategy"]

    updated = _ok(client.put(_path(created), json={k: strategy[k] for k in ("name", "description", "overlays")}))

    assert updated["strategy"] == strategy
    assert _ok(client.get(_variant(created, suffix="/fingerprint"))) == fingerprint


def test_a_deals_scenarios_and_strategies_share_one_investment(client: TestClient, db: Path) -> None:
    deal = create_deal("quick", db)
    scenario = _ok(client.post(f"/deals/{deal.id}/scenarios", json={"name": "Downside"}))
    strategy = _ok(client.post(f"/deals/{deal.id}/strategies", json={"name": "Bid low", "overlays": [f4.wire(f4.acquisition(deal.id))]}))
    another = _ok(client.post(f"/investments/{strategy['investment_id']}/strategies", json={"name": "Hold"}))

    assert scenario["investment_id"] == strategy["investment_id"] == another["investment_id"]
    assert f4.p7_row_counts(db)["investments"] == 1


# =============================================================================
# Update and delete
# =============================================================================


def test_update_keeps_the_id_and_replaces_the_overlays_whole(client: TestClient, db: Path) -> None:
    deal, created = _first(client, db, "quick")
    body = {"name": "Hold only", "description": "Hold", "overlays": [f4.wire(f4.disposition(deal.id, 10))]}

    updated = _ok(client.put(_path(created), json=body))

    assert updated["strategy"] == {"strategy_id": created["strategy"]["strategy_id"], **body}
    assert f4.p7_row_counts(db) == f4.counts(investments=1, investment_units=1, strategies=1, strategy_disposition_overlays=1)


def test_deleting_the_last_strategy_collapses_the_wrapper(client: TestClient, db: Path) -> None:
    deal, created = _first(client, db, "detailed")
    _ok(client.delete(_path(created)), 204)
    assert f4.p7_row_counts(db) == f4.P7_EMPTY
    assert client.get(_path(created)).status_code == 404
    assert _ok(client.get(f"/deals/{deal.id}/strategies"))["investment_id"] is None


def test_the_wrapper_survives_while_either_kind_of_structure_remains(client: TestClient, db: Path) -> None:
    deal, created = _first(client, db, "quick")
    scenario = _ok(client.post(f"/deals/{deal.id}/scenarios", json={"name": "Downside"}))

    _ok(client.delete(f"/investments/{scenario['investment_id']}/scenarios/{scenario['scenario']['scenario_id']}"), 204)
    assert f4.p7_row_counts(db)["investments"] == 1
    again = _ok(client.post(f"/deals/{deal.id}/scenarios", json={"name": "Again"}))
    _ok(client.delete(_path(created)), 204)
    assert f4.p7_row_counts(db)["investments"] == 1
    _ok(client.delete(f"/investments/{again['investment_id']}/scenarios/{again['scenario']['scenario_id']}"), 204)
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_deleting_the_deal_or_the_investment(client: TestClient, db: Path) -> None:
    deal, created = _first(client, db, "quick")
    _ok(client.post(_variant(created, suffix="/analysis")))
    _ok(client.delete(f"/investments/{created['investment_id']}"), 204)
    assert f4.p7_row_counts(db) == f4.P7_EMPTY
    assert client.get(f"/deals/{deal.id}").status_code == 200

    _, created = _first(client, db, "lease_level")
    deal_id = _ok(client.get(f"/investments/{created['investment_id']}"))["units"][0]["unit_id"]
    _ok(client.delete(f"/deals/{deal_id}"), 204)
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


# =============================================================================
# Structural and contract refusals -- nothing is written
# =============================================================================


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"name": "S", "colour": "red"}, "Unknown strategy field"),
        ({"name": "S", "overlays": {}}, "'overlays' must be an array"),
        ({"name": "S", "overlays": ["financing"]}, "overlays[0] must be an object"),
        ({"name": "S", "overlays": [{"unit_id": "u", "domain": "financing"}]}, "must hold exactly 'unit_id', 'domain' and 'content'"),
        ({"name": "S", "overlays": [{"unit_id": "u", "domain": "disposition", "content": {"hold_period": 7, "sale_year": 5}}]}, "unknown field(s): sale_year"),
        ({"name": "S", "overlays": [{"unit_id": "u", "domain": "acquisition", "content": 9e6}]}, "content must be an object"),
        (
            {"name": "S", "overlays": [{"unit_id": "u", "domain": "operating_outcome", "content": {"outcomes": [{"target": "exit_cap_rate", "value": 0.06}]}}]},
            "must hold exactly 'target', 'operation' and 'value'",
        ),
    ],
)
def test_a_structurally_malformed_body_is_a_422_and_writes_nothing(client: TestClient, db: Path, body: dict[str, Any], fragment: str) -> None:
    deal = create_deal("quick", db)
    response = client.post(f"/deals/{deal.id}/strategies", json=body)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_an_invalid_replacement_plan_is_a_d6_shaped_422_rooted_at_the_overlay(client: TestClient, db: Path) -> None:
    deal = create_deal("quick", db)
    content = {"capital_items": [{"item_id": "x", "description": "Roof", "category": "other", "month": 3, "amount": -1.0}]}
    response = client.post(
        f"/deals/{deal.id}/strategies",
        json={"name": "S", "overlays": [{"unit_id": deal.id, "domain": "business_plan", "content": content}]},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"code": "AMOUNT_OUT_OF_DOMAIN", "path": "overlays[0].content.capital_items[0].amount", "message": response.json()["detail"][0]["message"]}
    ]
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


@pytest.mark.parametrize(
    ("overlay", "expected"),
    [
        (lambda u: {**f4.wire(f4.financing(u)), "content": {k: v for k, v in f4.wire(f4.financing(u))["content"].items() if k != "amortization"}},
         {"code": "incomplete_domain", "domain": "financing", "field": "amortization"}),
        (lambda u: {"unit_id": u, "domain": "unit_selection", "content": {"units": [u]}}, {"code": "unsupported_domain", "domain": None}),
        (lambda u: {"unit_id": u, "domain": "capital_structure", "content": {}}, {"code": "unsupported_domain", "domain": None}),
        (lambda u: {"unit_id": u, "domain": "partnership", "content": {}}, {"code": "unsupported_domain", "domain": None}),
        (lambda u: f4.wire(f4.outcomes(u, f4.outcome("exit_cap_rate", 0.005, "add"))),
         {"code": "invalid_operation", "domain": "operating_outcome", "target": "exit_cap_rate"}),
        (lambda u: f4.wire(f4.outcomes(u, f4.outcome("ltv", 0.5))), {"code": "unsupported_target", "target": "ltv"}),
        (lambda u: f4.wire(f4.acquisition("zzz-foreign")), {"code": "unit_not_in_variant", "unit_id": "zzz-foreign"}),
    ],
    ids=["partial-financing", "unit-selection", "capital-structure", "partnership", "relative-operation", "ltv-outcome", "foreign-unit"],
)
def test_a_contract_violation_is_a_structured_422_and_writes_nothing(client: TestClient, db: Path, overlay: Any, expected: dict[str, Any]) -> None:
    deal = create_deal("quick", db)
    response = client.post(f"/deals/{deal.id}/strategies", json={"name": "S", "overlays": [overlay(deal.id)]})
    assert response.status_code == 422
    (issue,) = response.json()["detail"]
    assert issue["stage"] == "strategy"
    assert {key: issue[key] for key in expected} == expected
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


def test_an_unknown_deal_is_a_404(client: TestClient, db: Path) -> None:
    assert client.post(f"/deals/{'0' * 32}/strategies", json={"name": "S"}).status_code == 404
    assert client.get(f"/deals/{'0' * 32}/strategies").status_code == 404
    assert f4.p7_row_counts(db) == f4.P7_EMPTY


# =============================================================================
# Variants -- inspection, fingerprints and analysis
# =============================================================================


def test_strategy_by_scenario_inspection_is_what_runs(client: TestClient, db: Path) -> None:
    deal = create_deal("quick", db)
    created = _ok(client.post(f"/deals/{deal.id}/strategies", json={"name": "S", "overlays": [
        f4.wire(f4.acquisition(deal.id, purchase_price=9_500_000.0)),
        f4.wire(f4.financing(deal.id, ltv=0.60)),
        f4.wire(f4.outcomes(deal.id, f4.outcome("exit_cap_rate", 0.06), f4.outcome("noi_growth", 0.04))),
        f4.wire(f4.disposition(deal.id, 7)),
    ]}))
    scenario = _ok(client.post(f"/deals/{deal.id}/scenarios", json={"name": "Downside", "overrides": [
        {"unit_id": deal.id, "target": "exit_cap_rate", "operation": "add", "value": 0.005},
        {"unit_id": deal.id, "target": "ltv", "operation": "cap_at", "value": 0.55},
        {"unit_id": deal.id, "target": "noi_growth", "operation": "add", "value": -0.01},
    ]}))
    before = f4.p7_row_counts(db)

    inspected = _ok(client.get(_variant(created, scenario["scenario"]["scenario_id"], "/inputs")))

    assert set(inspected) == {"investment_id", "strategy_id", "scenario_id", "unit_id", "operating_mode", "source_fingerprint", "resolved"}
    inputs = inspected["resolved"]["inputs"]
    assert (inputs["purchase_price"], inputs["ltv"], inputs["exit_cap_rate"], inputs["noi_growth"], inputs["hold_period"]) == (
        9_500_000.0, 0.55, 0.06 + 0.005, 0.04 + -0.01, 7,
    )
    assert inspected["resolved"]["business_plan"] == {"capital_items": [], "owner_expense_items": []}
    assert f4.p7_row_counts(db) == before


@pytest.mark.parametrize("mode", MODES)
def test_the_variant_analysis_is_the_ordinary_analysis_of_the_inspected_inputs(client: TestClient, db: Path, mode: str) -> None:
    _, created = _first(client, db, mode)
    inspected = _ok(client.get(_variant(created, suffix="/inputs")))
    fingerprint = _ok(client.get(_variant(created, suffix="/fingerprint")))

    first = _ok(client.post(_variant(created, suffix="/analysis")))
    second = _ok(client.post(_variant(created, suffix="/analysis")))
    ordinary = _ok(client.post("/analyze", json=_analyze_body(inspected["resolved"], mode)))

    assert inspected["source_fingerprint"] == fingerprint["source_fingerprint"] == first["source_fingerprint"]
    expected_statuses = ("bypassed", "bypassed") if mode == "lease_level" else ("miss", "hit")
    assert (first["cache_status"], second["cache_status"]) == expected_statuses
    assert first["results"] == second["results"] == ordinary
    assert (first["strategy_id"], first["scenario_id"]) == (created["strategy"]["strategy_id"], BASE)


def test_lease_level_inspection_carries_the_whole_resolved_rent_roll(client: TestClient, db: Path) -> None:
    deal = create_deal("lease_level", db)
    created = _ok(client.post(f"/deals/{deal.id}/strategies", json={"name": "S", "overlays": [
        f4.wire(f4.outcomes(deal.id, f4.outcome("market_rent_psf", 45.0))),
    ]}))
    resolved = _ok(client.get(_variant(created, suffix="/inputs")))["resolved"]

    assert set(resolved) == {"terms", "property_inputs", "suites", "leases", "market_leasing", "operating_inputs", "business_plan"}
    assert resolved["market_leasing"]["market_rent_psf"] == 45.0
    assert {s["suite_id"]: s["market_rent_psf"] for s in resolved["suites"]}["B"] == 45.0
    assert resolved["property_inputs"]["analysis_start_date"] == fx.ANALYSIS_START.isoformat()


@pytest.mark.parametrize("mode", MODES)
def test_base_by_base_is_the_deals_own_fingerprint_and_analysis(client: TestClient, db: Path, mode: str) -> None:
    deal, created = _first(client, db, mode)
    base = f"/investments/{created['investment_id']}/variants/{BASE}/{BASE}"
    state = _ok(client.get(f"/deals/{deal.id}"))

    assert _ok(client.get(f"{base}/fingerprint"))["source_fingerprint"] == deal_fingerprint(deal)
    analysed = _ok(client.post(f"{base}/analysis"))
    ordinary = _ok(client.post("/analyze", json=_analyze_body(_state_body(state, mode) | ({"inputs": state["inputs"]} if mode == "quick" else {}), mode)))
    assert analysed["cache_status"] == "bypassed"
    assert analysed["results"] == ordinary
    assert f4.p7_row_counts(db)["variant_snapshots"] == 0


def test_base_by_scenario_through_the_variant_route_is_the_p7_2_route(client: TestClient, db: Path) -> None:
    deal, created = _first(client, db, "detailed")
    scenario = _ok(client.post(f"/deals/{deal.id}/scenarios", json={"name": "Downside", "overrides": [
        {"unit_id": deal.id, "target": "vacancy_credit_loss_pct", "operation": "add", "value": 0.02},
    ]}))
    p7_2 = f"/investments/{scenario['investment_id']}/scenarios/{scenario['scenario']['scenario_id']}"
    p7_4 = f"/investments/{scenario['investment_id']}/variants/{BASE}/{scenario['scenario']['scenario_id']}"

    assert _ok(client.get(f"{p7_4}/fingerprint"))["source_fingerprint"] == _ok(client.get(f"{p7_2}/fingerprint"))["source_fingerprint"]
    through_p7_2 = _ok(client.post(f"{p7_2}/analysis"))
    through_p7_4 = _ok(client.post(f"{p7_4}/analysis"))
    assert through_p7_4["results"] == through_p7_2["results"]
    assert (through_p7_2["cache_status"], through_p7_4["cache_status"]) == ("miss", "hit")


def test_an_invalid_variant_is_a_structured_422(client: TestClient, db: Path) -> None:
    deal = create_deal("quick", db)
    created = _ok(client.post(f"/deals/{deal.id}/strategies", json={"name": "S", "overlays": [
        f4.wire(f4.financing(deal.id, ltv=1.5)),
    ]}))
    for method, suffix in (("get", "/inputs"), ("get", "/fingerprint"), ("post", "/analysis")):
        response = client.request(method.upper(), _variant(created, suffix=suffix))
        assert response.status_code == 422, suffix
        (issue,) = response.json()["detail"]
        assert (issue["stage"], issue["code"], issue["domain"], issue["field"]) == (
            "resolved_inputs", "resolved_input_invalid", "financing", "ltv",
        )
    assert f4.p7_row_counts(db)["variant_snapshots"] == 0


def test_a_scenario_that_breaks_the_strategy_world_is_a_scenario_422(client: TestClient, db: Path) -> None:
    deal = create_deal("lease_level", db)
    created = _ok(client.post(f"/deals/{deal.id}/strategies", json={"name": "S", "overlays": [
        f4.wire(f4.outcomes(deal.id, f4.outcome("renewal_probability", 0.95))),
    ]}))
    scenario = _ok(client.post(f"/deals/{deal.id}/scenarios", json={"name": "Up", "overrides": [
        {"unit_id": deal.id, "target": "renewal_probability", "operation": "add", "value": 0.1},
    ]}))
    response = client.post(_variant(created, scenario["scenario"]["scenario_id"], "/analysis"))
    assert response.status_code == 422
    assert {issue["code"] for issue in response.json()["detail"]} == {"resolved_input_invalid"}
    assert {issue["stage"] for issue in response.json()["detail"]} == {"resolved_inputs"}
    assert all("domain" not in issue for issue in response.json()["detail"])


# =============================================================================
# Ownership -- supplied ids are never trusted
# =============================================================================


def test_foreign_ids_are_404s_everywhere(client: TestClient, db: Path) -> None:
    _, mine = _first(client, db, "quick")
    other_deal, theirs = _first(client, db, "quick")
    their_scenario = _ok(client.post(f"/deals/{other_deal.id}/scenarios", json={"name": "Theirs"}))
    before = f4.p7_row_counts(db)
    foreign_strategy = f"/investments/{mine['investment_id']}/strategies/{theirs['strategy']['strategy_id']}"

    assert client.get(foreign_strategy).status_code == 404
    assert client.put(foreign_strategy, json={"name": "Hijack"}).status_code == 404
    assert client.delete(foreign_strategy).status_code == 404
    for suffix in ("/inputs", "/fingerprint"):
        assert client.get(f"/investments/{mine['investment_id']}/variants/{theirs['strategy']['strategy_id']}/{BASE}{suffix}").status_code == 404
        assert client.get(_variant(mine, their_scenario["scenario"]["scenario_id"], suffix)).status_code == 404
    assert client.post(f"/investments/{mine['investment_id']}/variants/{theirs['strategy']['strategy_id']}/{BASE}/analysis").status_code == 404
    assert client.post(_variant(mine, their_scenario["scenario"]["scenario_id"], "/analysis")).status_code == 404
    assert client.get(f"/investments/{'0' * 32}/variants/{BASE}/{BASE}/inputs").status_code == 404
    assert f4.p7_row_counts(db) == before


def test_a_visible_investment_is_a_409(client: TestClient, db: Path) -> None:
    """Re-pinned at P7.6: once promoted to a visible Investment, its Strategies
    are read through the Investment (200), while the Deal-scoped Strategy
    routes and the one-unit P7.4 variant routes stay 409 -- a visible
    Investment's variants consolidate through the P7.6 routes."""

    from anchor.deals import store as p7_6_store
    from anchor.business_plan import BusinessPlan
    from anchor.investment import InvestmentUnitMembership, UnitKind

    deal, created = _first(client, db, "quick")
    p7_6_store.promote_hidden_investment(
        created["investment_id"],
        name="Visible",
        transaction_price=deal.inputs.purchase_price,
        units=(
            InvestmentUnitMembership(
                unit_id=deal.id, ordinal=0, label=None, unit_kind=UnitKind.PROPERTY,
                acquisition_month=0, disposition_month=None,
            ),
        ),
        business_plan=BusinessPlan(),
        db_path=db,
    )
    before = f4.p7_row_counts(db)

    assert client.post(f"/deals/{deal.id}/strategies", json={"name": "S"}).status_code == 409
    assert client.get(f"/deals/{deal.id}/strategies").status_code == 409
    assert client.get(_path(created)).status_code == 200
    for suffix in ("/inputs", "/fingerprint"):
        assert client.get(_variant(created, suffix=suffix)).status_code == 409
    assert client.post(_variant(created, suffix="/analysis")).status_code == 409
    assert f4.p7_row_counts(db) == before


def test_the_empty_plan_replacement_on_the_wire(client: TestClient, db: Path) -> None:
    deal = create_deal("quick", db, business_plan=fx.business_plan())
    created = _ok(client.post(f"/deals/{deal.id}/strategies", json={"name": "No plan", "overlays": [
        {"unit_id": deal.id, "domain": "business_plan", "content": {}},
    ]}))
    assert created["strategy"]["overlays"] == [
        {"unit_id": deal.id, "domain": "business_plan", "content": {"capital_items": [], "owner_expense_items": []}}
    ]
    resolved = _ok(client.get(_variant(created, suffix="/inputs")))
    assert resolved["resolved"]["business_plan"] == {"capital_items": [], "owner_expense_items": []}
    assert resolved["source_fingerprint"] == deal_fingerprint(__import__("dataclasses").replace(deal, business_plan=BusinessPlan()))
