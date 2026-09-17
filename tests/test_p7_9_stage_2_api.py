"""Phase 7 Gate P7.9 Stage 2 -- the Partnership routes.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 17.2. The routes:

- ``GET``/``PUT /deals/{id}/partnership`` and
  ``GET``/``PUT /investments/{id}/partnership``;
- ``GET /investments/{id}/partnership-variants/{strategy}/{scenario}/fingerprint``
  and ``POST .../analysis``;
- ``GET /investments/{id}/partner-perspectives``;
- ``POST /investments/{id}/partner-decision-matrix/{partner_id}``.

The claims: kinds are explicit and a response body is a valid request body
(every typed union round-trips over the wire); nothing is defaulted -- a
missing ``promote_participant_ids`` is refused and ``[]`` is the confirmed
empty set; an unknown discriminator is a structural 422 and every other unknown
token the Stage 1 validator's 422; one authority per refusal; a Strategy states
its Partnership as a root overlay, with ``null`` as the explicit "no
Partnership", and a Strategy that states none answers without the key.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _p7_9_fixtures as f  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from _p7_8_fixtures import round_deal  # type: ignore[import-not-found]
from _p7_9_stage_2_fixtures import (  # type: ignore[import-not-found]
    all_fixture_partnerships,
    capital_overlay,
    gp_as_lp,
    structured_deal,
    unresolved_structure,
)
from anchor import api as api_module
from anchor.deals import decision_matrix as matrix_module
from anchor.deals import partnership_variants as service
from anchor.deals import store
from anchor.partnership import (
    PartnershipExecutionError,
    PartnershipExecutionIssue,
    PartnershipExecutionIssueCode,
)

BASE = "base"
_WIRE_CASES = all_fixture_partnerships()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


@pytest.fixture
def client(db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    return TestClient(api_module.app)


def wire(partnership: Any) -> Any:
    return api_module._wire(partnership)


def put_base(client: TestClient, investment_id: str, body: Any) -> Any:
    return client.put(f"/investments/{investment_id}/partnership", json={"partnership": body})


def detail(response: Any) -> Any:
    return response.json()["detail"]


# =============================================================================
# The doors
# =============================================================================


def test_reading_a_standalone_deals_partnership_creates_nothing(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")

    response = client.get(f"/deals/{deal.id}/partnership")

    assert response.status_code == 200
    assert response.json() == {"deal_id": deal.id, "investment_id": None, "partnership": None}
    assert client.put(f"/deals/{deal.id}/partnership", json={"partnership": None}).json() == {
        "deal_id": deal.id,
        "investment_id": None,
        "partnership": None,
    }
    assert store.list_deal_scenarios(deal.id, db_path=db)[0] is None


def test_the_first_save_opts_the_deal_in_and_clearing_releases_it(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")

    saved = client.put(f"/deals/{deal.id}/partnership", json={"partnership": wire(f.f1_terms())})
    assert saved.status_code == 200
    investment_id = saved.json()["investment_id"]
    assert investment_id and saved.json()["partnership"] == wire(f.f1_terms())
    assert client.get(f"/deals/{deal.id}/partnership").json()["investment_id"] == investment_id
    assert client.get(f"/investments/{investment_id}/partnership").json() == {
        "investment_id": investment_id,
        "partnership": wire(f.f1_terms()),
    }

    cleared = client.put(f"/deals/{deal.id}/partnership", json={"partnership": None})
    assert cleared.json() == {"deal_id": deal.id, "investment_id": None, "partnership": None}
    assert client.get(f"/investments/{investment_id}").status_code == 404


def test_a_visible_units_door_is_a_conflict_and_unknown_ids_are_not_found(client: TestClient, db: Path) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)

    assert client.get(f"/deals/{first.id}/partnership").status_code == 409
    assert client.put(f"/deals/{first.id}/partnership", json={"partnership": wire(f.f1_terms())}).status_code == 409
    assert client.get("/deals/zzz-missing/partnership").status_code == 404
    assert client.put("/deals/zzz-missing/partnership", json={"partnership": None}).status_code == 404
    assert client.get("/investments/zzz-missing/partnership").status_code == 404
    assert put_base(client, "zzz-missing", None).status_code == 404
    assert put_base(client, investment.id, wire(f.f1_terms())).status_code == 200


@pytest.mark.parametrize(("name", "terms"), _WIRE_CASES, ids=[name for name, _ in _WIRE_CASES])
def test_every_typed_union_round_trips_over_the_wire(client: TestClient, db: Path, name: str, terms: Any) -> None:
    _, investment_id = structured_deal(db)

    saved = put_base(client, investment_id, wire(terms))
    assert saved.status_code == 200, saved.text
    body = client.get(f"/investments/{investment_id}/partnership").json()["partnership"]
    again = put_base(client, investment_id, body)

    assert again.status_code == 200
    assert body == wire(terms)
    assert store.get_base_partnership(investment_id, db_path=db) == terms


def test_kinds_are_explicit_on_the_wire() -> None:
    body = wire(f.f10_terms(pro_rata=True))
    assert body["tiers"][0]["split"] == {"kind": "pro_rata_by_contribution"}
    assert body["tiers"][0]["hurdle"]["conditions"][0]["kind"] == "irr"
    assert body["tiers"][0]["hurdle"]["hurdle_subject"]["kind"] == "partner"
    explicit = wire(f.f1_terms())
    assert explicit["tiers"][0]["split"]["kind"] == "explicit"
    assert explicit["tiers"][1]["catch_up"]["recipient"]["kind"] == "partner"
    assert wire(f.f5_terms())["tiers"][0]["hurdle"]["conditions"][0] == {
        "kind": "moic", "condition_id": "roc-1", "multiple": 1.0,
    }


# =============================================================================
# Nothing defaulted, nothing inferred
# =============================================================================


def test_the_confirmed_empty_participant_set_is_accepted(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db)
    body = wire(f.f1_terms(participants=()))
    assert body["promote_participant_ids"] == []

    assert put_base(client, investment_id, body).status_code == 200
    assert client.get(f"/investments/{investment_id}/partnership").json()["partnership"]["promote_participant_ids"] == []


def _without(path: list[Any], key: str) -> Any:
    body = copy.deepcopy(wire(f.f1_terms()))
    node = body
    for step in path:
        node = node[step]
    del node[key]
    return body


def _with(path: list[Any], key: str, value: Any) -> Any:
    body = copy.deepcopy(wire(f.f1_terms()))
    node = body
    for step in path:
        node = node[step]
    node[key] = value
    return body


@pytest.mark.parametrize(
    "body",
    [
        _without([], "promote_participant_ids"),
        _without([], "promote_benchmark"),
        _without(["partners", 0], "investor_class"),
        _without(["tiers", 0], "catch_up"),
        _without(["tiers", 0, "hurdle"], "combinator"),
        _without(["tiers", 0, "hurdle", "hurdle_subject"], "account"),
        _without(["tiers", 0, "hurdle", "conditions", 0], "simple_distribution_order"),
        _without(["tiers", 1, "catch_up", "recipient"], "investor_class"),
        _with([], "fees", []),
        _with(["partners", 0], "is_sponsor", True),
        _with(["tiers", 0, "split"], "kind", "equal"),
        _with(["tiers", 0, "hurdle", "conditions", 0], "kind", "npv"),
        _with([], "promote_participant_ids", "gp"),
        _with([], "partners", {"lp": 0.9}),
        _with(["tiers", 0, "hurdle"], "conditions", None),
        "not an object",
    ],
    ids=[
        "missing-participants", "missing-benchmark", "missing-investor-class", "missing-catch-up",
        "missing-combinator", "missing-account", "missing-simple-order", "missing-recipient-class",
        "unknown-top-level-key", "unknown-partner-key", "unknown-split-kind", "unknown-condition-kind",
        "participants-not-an-array", "partners-not-an-array", "conditions-not-an-array", "not-an-object",
    ],
)
def test_a_structurally_malformed_body_is_a_structural_422_and_writes_nothing(
    client: TestClient, db: Path, body: Any
) -> None:
    _, investment_id = structured_deal(db, f.f7_terms())

    response = put_base(client, investment_id, body)

    assert response.status_code == 422
    assert isinstance(detail(response), str)
    assert store.get_base_partnership(investment_id, db_path=db) == f.f7_terms()


def test_a_body_without_the_partnership_key_is_refused(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db)
    assert client.put(f"/investments/{investment_id}/partnership", json={}).status_code == 422
    assert client.put(
        f"/investments/{investment_id}/partnership", json={"partnership": None, "tiers": []}
    ).status_code == 422


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (_with(["partners", 0], "role", "sponsor"), "invalid_role"),
        (_with([], "contribution_rule", "gp_funds_overruns"), "invalid_contribution_rule"),
        (_with(["tiers", 0], "kind", "lookback"), "invalid_tier"),
        (_with(["tiers", 0], "split", None), "missing_split"),
        (_with(["tiers", 0], "hurdle", None), "missing_hurdle_subject"),
        (_with(["tiers", 0, "hurdle"], "hurdle_subject", None), "missing_hurdle_subject"),
        (_with(["tiers", 0, "hurdle", "hurdle_subject"], "kind", "fund"), "invalid_hurdle_subject"),
        (_with(["tiers", 0, "hurdle"], "combinator", "either"), "invalid_combinator"),
        (_with(["tiers", 0, "hurdle", "conditions", 0], "accrual_convention", None), "missing_accrual_convention"),
        (_with(["tiers", 0, "hurdle", "conditions", 0], "accrual_convention", "continuous"), "invalid_condition"),
        (_with(["tiers", 0, "hurdle", "conditions", 0], "accrual_convention", "simple"), "missing_simple_distribution_order"),
        (_with(["tiers", 0, "hurdle", "conditions", 0], "simple_distribution_order", "capital_first"), "unexpected_simple_distribution_order"),
        (_with(["tiers", 1, "catch_up", "recipient"], "kind", "economic_account"), "unsupported_catch_up_recipient"),
        (_with(["tiers", 1], "split", {"kind": "pro_rata_by_contribution"}), "catch_up_requires_explicit_split"),
        (_with([], "promote_participant_ids", ["gp", "gp"]), "duplicate_promote_participant"),
        (_with([], "promote_participant_ids", ["ghost"]), "unknown_promote_participant"),
        (_with(["partners", 0], "commitment_share", True), "invalid_share"),
        (_with([], "tiers", []), "no_tiers"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_contract_violation_is_the_validators_422_and_writes_nothing(
    client: TestClient, db: Path, body: Any, code: str
) -> None:
    _, investment_id = structured_deal(db, f.f7_terms())

    response = put_base(client, investment_id, body)

    assert response.status_code == 422
    issues = detail(response)
    assert code in {issue["code"] for issue in issues}
    assert set(issues[0]) == {"code", "message", "partner_id", "tier_id", "field"}
    assert store.get_base_partnership(investment_id, db_path=db) == f.f7_terms()


def test_a_partner_identity_conflict_is_its_own_422(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())
    strategy = client.post(
        f"/investments/{investment_id}/strategies",
        json={"name": "Recast", "root_overlays": [{"domain": "partnership", "content": wire(gp_as_lp(f.f1_terms()))}]},
    )

    assert strategy.status_code == 422
    assert detail(strategy) == [
        {
            "code": "partner_role_conflict",
            "message": detail(strategy)[0]["message"],
            "partner_id": "gp",
            "field": "role",
        }
    ]
    assert client.get(f"/investments/{investment_id}/strategies").json() == []


# =============================================================================
# Strategies state their Partnership as a root overlay
# =============================================================================


def test_a_strategy_states_replace_or_explicit_none_and_otherwise_has_no_key(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())

    own = client.post(
        f"/investments/{investment_id}/strategies",
        json={"name": "Own", "root_overlays": [{"domain": "partnership", "content": wire(f.f7_terms())}]},
    )
    none = client.post(
        f"/investments/{investment_id}/strategies",
        json={"name": "None", "root_overlays": [{"domain": "partnership", "content": None}]},
    )
    inherit = client.post(f"/investments/{investment_id}/strategies", json={"name": "Inherit"})

    assert own.json()["strategy"]["root_overlays"] == [{"domain": "partnership", "content": wire(f.f7_terms())}]
    assert none.json()["strategy"]["root_overlays"] == [{"domain": "partnership", "content": None}]
    assert "root_overlays" not in inherit.json()["strategy"]

    strategy_id = own.json()["strategy"]["strategy_id"]
    updated = client.put(f"/investments/{investment_id}/strategies/{strategy_id}", json={"name": "Own"})
    assert updated.status_code == 200 and "root_overlays" not in updated.json()["strategy"]


def test_a_strategys_invalid_partnership_is_a_strategy_422(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db)
    body = _with([], "promote_participant_ids", ["ghost"])

    response = client.post(
        f"/investments/{investment_id}/strategies",
        json={"name": "Bad", "root_overlays": [{"domain": "partnership", "content": body}]},
    )

    assert response.status_code == 422
    (issue,) = detail(response)
    assert issue["code"] == "invalid_partnership"
    assert issue["domain"] == "partnership"
    assert issue["source_code"] == "unknown_promote_participant"


def test_a_strategys_malformed_partnership_is_a_structural_422(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db)

    response = client.post(
        f"/investments/{investment_id}/strategies",
        json={"name": "Bad", "root_overlays": [{"domain": "partnership", "content": _without([], "promote_participant_ids")}]},
    )

    assert response.status_code == 422 and isinstance(detail(response), str)


# =============================================================================
# Fingerprints and analyses
# =============================================================================


def test_the_fingerprint_route_has_no_partnership_key_without_a_partnership(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db)

    body = client.get(f"/investments/{investment_id}/partnership-variants/base/base/fingerprint").json()
    structured = client.get(f"/investments/{investment_id}/structured-variants/base/base/fingerprint").json()

    assert body["partnership"] is None and body["partnership_source_fingerprint"] is None
    assert body["partnership_source"] == "base" and body["root_kind"] == "hidden_unit"
    assert body["structured_source_fingerprint"] == structured["structured_source_fingerprint"]
    assert body["project_source_fingerprint"] == structured["project_source_fingerprint"]


def test_the_analysis_route_reports_the_stage_1_result(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())

    analysis = client.post(f"/investments/{investment_id}/partnership-variants/base/base/analysis")
    fingerprint = client.get(f"/investments/{investment_id}/partnership-variants/base/base/fingerprint").json()

    assert analysis.status_code == 200
    body = analysis.json()
    assert body["partnership"] == wire(f.f1_terms())
    assert body["partnership_source_fingerprint"] == fingerprint["partnership_source_fingerprint"]
    result = body["result"]
    assert result["status"] == "complete" and result["cadence"] == "annual"
    assert [partner["partner_id"] for partner in result["partners"]] == ["gp", "lp"]
    lp = result["partners"][1]
    assert lp["promote_earned"] is None and lp["promote_unavailable_reason"] == "not_a_promote_participant"
    assert result["tiers"][0]["split_rule"] == "explicit"
    assert result["tiers"][0]["hurdle_subject"]["kind"] == "partner"
    assert "name" not in result["partners"][0] and "name" not in result["tiers"][0]


def test_an_unavailable_common_equity_is_a_successful_analysis(client: TestClient, db: Path) -> None:
    deal, investment_id = structured_deal(db, f.f1_terms())
    starved = store.create_strategy(
        investment_id, name="Balloon", root_overlays=(capital_overlay(unresolved_structure(deal.id)),), db_path=db
    ).strategy.strategy_id

    response = client.post(f"/investments/{investment_id}/partnership-variants/{starved}/base/analysis")

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "common_equity_unavailable"
    assert result["upstream_reason"] == "unresolved_funding_requirement"
    assert result["upstream_requirement_ids"]
    assert result["partners"] is None and result["common_equity_cash_flows"] is None


def test_the_analysis_route_keeps_each_refusal_in_its_layer(
    client: TestClient, db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deal, investment_id = structured_deal(db, f.f1_terms())
    bad_bid = client.post(
        f"/investments/{investment_id}/strategies",
        json={"name": "Bad", "overlays": [{"unit_id": deal.id, "domain": "acquisition", "content": {"purchase_price": -1.0, "acquisition_cost_pct": 0.02}}]},
    ).json()["strategy"]["strategy_id"]

    project = client.post(f"/investments/{investment_id}/partnership-variants/{bad_bid}/base/analysis")
    assert project.status_code == 422 and detail(project)[0]["stage"] == "resolved_inputs"

    def refuse(partnership: Any, structured: Any) -> Any:
        raise PartnershipExecutionError(
            (
                PartnershipExecutionIssue(
                    code=PartnershipExecutionIssueCode.NO_CONTRIBUTIONS_FOR_PRO_RATA_SPLIT,
                    message="No contributions to divide by.",
                    tier_id="residual",
                    period=1,
                ),
            )
        )

    monkeypatch.setattr(service, "execute_partnership", refuse)
    engine = client.post(f"/investments/{investment_id}/partnership-variants/base/base/analysis")
    assert engine.status_code == 422
    assert detail(engine) == [
        {
            "code": "no_contributions_for_pro_rata_split",
            "message": "No contributions to divide by.",
            "tier_id": "residual",
            "period": 1,
        }
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/investments/zzz-missing/partnership-variants/base/base/{route}",
        "/investments/{investment_id}/partnership-variants/zzz-missing/base/{route}",
        "/investments/{investment_id}/partnership-variants/base/zzz-missing/{route}",
    ],
)
@pytest.mark.parametrize(("method", "route"), [("GET", "fingerprint"), ("POST", "analysis")])
def test_an_unknown_variant_is_not_found(client: TestClient, db: Path, path: str, method: str, route: str) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())

    response = client.request(method, path.format(investment_id=investment_id, route=route))

    assert response.status_code == 404


# =============================================================================
# Perspectives and the Partner matrix
# =============================================================================


def test_the_partner_perspectives_route(client: TestClient, db: Path) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())

    body = client.get(f"/investments/{investment_id}/partner-perspectives").json()

    assert body == {
        "investment_id": investment_id,
        "partners": [
            {"partner_id": "gp", "name": "GP", "role": "gp", "present_in_base": True, "strategy_ids": []},
            {"partner_id": "lp", "name": "LP", "role": "lp", "present_in_base": True, "strategy_ids": []},
        ],
    }
    assert client.get("/investments/zzz-missing/partner-perspectives").status_code == 404


def test_the_partner_matrix_route(client: TestClient, db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())

    response = client.post(f"/investments/{investment_id}/partner-decision-matrix/lp")
    assert response.status_code == 200
    body = response.json()
    assert body["partner"]["partner_id"] == "lp" and body["root_kind"] == "hidden_unit"
    matrix = body["matrix"]
    assert matrix["perspective"] == "partner" and matrix["partner_id"] == "lp"
    assert [metric["metric"] for metric in matrix["metrics"]] == [
        "total_contributions", "total_distributions", "partner_irr", "partner_moic", "partner_profit",
        "distribution_difference", "promote_earned", "benchmark_capital_subordination",
    ]
    promote = next(value for value in matrix["cells"][0]["metrics"] if value["metric"] == "promote_earned")
    assert promote == {
        "metric": "promote_earned",
        "value": None,
        "irr_status": None,
        "reason": "not_applicable_to_perspective",
        "message": "Not a promote participant in this Strategy's Partnership.",
    }

    assert client.post(f"/investments/{investment_id}/partner-decision-matrix/nobody").status_code == 404
    assert client.post("/investments/zzz-missing/partner-decision-matrix/lp").status_code == 404

    def conflict(*args: Any, **kwargs: Any) -> Any:
        raise matrix_module.DecisionMatrixConflictError("moved")

    monkeypatch.setattr(api_module, "analyze_partner_decision_matrix", conflict)
    assert client.post(f"/investments/{investment_id}/partner-decision-matrix/lp").status_code == 409
