"""Phase 6 Gate D6.5 -- the Business Plan on the HTTP surface.

- **Request contract.** ``business_plan`` is optional and mode-agnostic: absent,
  ``null``, ``{}`` and empty collections are ``BusinessPlan()``, so every pre-D6
  request is unchanged; a non-empty plan is parsed and validated by the D6.1
  authority and refused with the existing structured-422 shape.
- **/analyze parity.** A material plan submitted to ``/analyze`` produces exactly
  the direct plan-aware D6 analysis in every mode -- the check that catches the
  API falling back to the neutral compatibility default.
- **Secondary seams.** Sensitivity, presets, break-even and the AI Analyst each
  receive the request's plan -- one narrow oracle per exposed route, not the
  D6.4 matrix again.
- **Deal lifecycle.** Save, reopen, list, update, duplicate and delete carry the
  plan; the saved-deal response carries everything an editor needs, in order.
- **Provenance.** ``/deals/fingerprint`` hashes the plan exactly as the store
  does, so a snapshot written under one plan is refused for another.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

import anchor.api as api_module
from anchor.analysis import (
    ReturnHurdleMetric,
    analyze_lease_level_acquisition_with_business_plan,
    build_standard_break_even_analysis,
    build_standard_detailed_break_even_analysis,
    build_standard_detailed_presets,
    build_standard_presets,
    run_detailed_one_way_sensitivity,
    run_detailed_two_way_sensitivity,
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
    run_one_way_sensitivity,
    run_two_way_sensitivity,
)
from anchor.api import app
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
    parse_business_plan,
)

from _d6_5_fixtures import (  # type: ignore[import-not-found]
    MATERIAL,
    MODES,
    PRE_D6_5_DIGESTS,
    analysis_envelope,
    analysis_request,
    analyze,
    deal_request,
    input_fingerprint,
    plan_rows,
    wire,
)
from test_d5_8a_deal_analysis_persistence import (  # type: ignore[import-not-found]
    AI_ANALYSIS,
    ONE_WAY,
    as_dict,
)
from test_d6_2_owner_cash_flow_engine import (  # type: ignore[import-not-found]
    DETAILED_OPERATING,
    DETAILED_TERMS,
    LL_LEASES,
    LL_MARKET,
    LL_OPERATING,
    LL_PROPERTY,
    LL_SUITES,
    LL_TERMS,
    QUICK,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "d6-5-api.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(app)


# =============================================================================
# The request contract
# =============================================================================

_CAPITAL_JSON: dict[str, Any] = {
    "item_id": "c-1",
    "description": "Roof replacement",
    "category": "building_systems",
    "month": 18,
    "amount": 1_000_000.0,
}
_CAPITAL = CapitalPlanItem(
    item_id="c-1",
    description="Roof replacement",
    category=CapitalItemCategory.BUILDING_SYSTEMS,
    month=18,
    amount=1_000_000.0,
)
_EXPENSE_JSON: dict[str, Any] = {
    "item_id": "e-1",
    "description": "Asset management",
    "category": "asset_management",
    "annual_amount": 50_000.0,
    "first_year": 1,
    "last_year": None,
}
_EXPENSE = OwnerExpenseItem(
    item_id="e-1",
    description="Asset management",
    category=OwnerExpenseCategory.ASSET_MANAGEMENT,
    annual_amount=50_000.0,
    first_year=1,
    last_year=None,
)
_ABSENT = object()

_VALID_PLANS: dict[str, tuple[object, BusinessPlan]] = {
    "omitted": (_ABSENT, BusinessPlan()),
    "null": (None, BusinessPlan()),
    "empty-object": ({}, BusinessPlan()),
    "empty-collections": ({"capital_items": [], "owner_expense_items": []}, BusinessPlan()),
    "capital-only": ({"capital_items": [_CAPITAL_JSON]}, BusinessPlan(capital_items=(_CAPITAL,))),
    "owner-expense-only": (
        {"owner_expense_items": [_EXPENSE_JSON]},
        BusinessPlan(owner_expense_items=(_EXPENSE,)),
    ),
    "both": (
        {"capital_items": [_CAPITAL_JSON], "owner_expense_items": [_EXPENSE_JSON]},
        BusinessPlan(capital_items=(_CAPITAL,), owner_expense_items=(_EXPENSE,)),
    ),
    "last-year-null-by-omission": (
        {"owner_expense_items": [{k: v for k, v in _EXPENSE_JSON.items() if k != "last_year"}]},
        BusinessPlan(owner_expense_items=(_EXPENSE,)),
    ),
    "explicit-last-year": (
        {"owner_expense_items": [{**_EXPENSE_JSON, "last_year": 3}]},
        BusinessPlan(owner_expense_items=(dataclasses.replace(_EXPENSE, last_year=3),)),
    ),
    "zero-dollar-items": (
        {
            "capital_items": [{**_CAPITAL_JSON, "amount": 0}],
            "owner_expense_items": [{**_EXPENSE_JSON, "annual_amount": 0.0}],
        },
        BusinessPlan(
            capital_items=(dataclasses.replace(_CAPITAL, amount=0.0),),
            owner_expense_items=(dataclasses.replace(_EXPENSE, annual_amount=0.0),),
        ),
    ),
    "whole-number-amount": (
        {"capital_items": [{**_CAPITAL_JSON, "amount": 1_000_000}]},
        BusinessPlan(capital_items=(_CAPITAL,)),
    ),
    "very-large-post-hold-month": (
        {"capital_items": [{**_CAPITAL_JSON, "month": 1_000_000_000}]},
        BusinessPlan(capital_items=(dataclasses.replace(_CAPITAL, month=1_000_000_000),)),
    ),
}


@pytest.mark.parametrize("case", sorted(_VALID_PLANS))
def test_a_valid_plan_is_accepted_and_analyzed(client: TestClient, case: str) -> None:
    raw, expected = _VALID_PLANS[case]
    body = analysis_request("quick")
    if raw is not _ABSENT:
        body["business_plan"] = raw

    response = client.post("/analyze", json=body)

    assert response.status_code == 200, response.json()
    assert response.json() == jsonable_encoder(analyze("quick", expected))
    if raw is not _ABSENT:
        parsed = parse_business_plan(raw)
        assert parsed == expected
        for item in parsed.capital_items:
            assert type(item.amount) is float and type(item.category) is CapitalItemCategory


def _owner(**changes: Any) -> dict[str, Any]:
    return {"owner_expense_items": [{**_EXPENSE_JSON, **changes}]}


def _capital(**changes: Any) -> dict[str, Any]:
    return {"capital_items": [{**_CAPITAL_JSON, **changes}]}


#: ``raw plan -> (code, request-rooted path)`` the refusal must name.
_INVALID_PLANS: dict[str, tuple[object, str, str]] = {
    "negative-amount": (_capital(amount=-1.0), "AMOUNT_OUT_OF_DOMAIN", "capital_items[0].amount"),
    "negative-annual-amount": (
        _owner(annual_amount=-0.01),
        "AMOUNT_OUT_OF_DOMAIN",
        "owner_expense_items[0].annual_amount",
    ),
    "text-amount": (_capital(amount="100"), "NON_FINITE_VALUE", "capital_items[0].amount"),
    "oversized-whole-number-amount": (
        _capital(amount=10**400),
        "NON_FINITE_VALUE",
        "capital_items[0].amount",
    ),
    "boolean-month": (_capital(month=True), "NON_WHOLE_NUMBER_MONTH", "capital_items[0].month"),
    "fractional-month": (_capital(month=12.0), "NON_WHOLE_NUMBER_MONTH", "capital_items[0].month"),
    "negative-month": (_capital(month=-1), "MONTH_OUT_OF_DOMAIN", "capital_items[0].month"),
    "first-year-zero": (
        _owner(first_year=0),
        "FIRST_YEAR_OUT_OF_DOMAIN",
        "owner_expense_items[0].first_year",
    ),
    "boolean-first-year": (
        _owner(first_year=True),
        "NON_WHOLE_NUMBER_YEAR",
        "owner_expense_items[0].first_year",
    ),
    "last-year-before-first-year": (
        _owner(first_year=3, last_year=2),
        "LAST_YEAR_BEFORE_FIRST_YEAR",
        "owner_expense_items[0].last_year",
    ),
    "unknown-category": (
        _capital(category="contingency"),
        "UNSUPPORTED_CATEGORY",
        "capital_items[0].category",
    ),
    "other-collection-s-category": (
        _capital(category="asset_management"),
        "UNSUPPORTED_CATEGORY",
        "capital_items[0].category",
    ),
    "blank-item-id": (_capital(item_id="   "), "EMPTY_ITEM_ID", "capital_items[0].item_id"),
    "blank-description": (_owner(description=""), "EMPTY_DESCRIPTION", "owner_expense_items[0].description"),
    "duplicate-capital-id": (
        {"capital_items": [_CAPITAL_JSON, {**_CAPITAL_JSON, "month": 0}]},
        "DUPLICATE_ITEM_ID",
        "capital_items[1].item_id",
    ),
    "duplicate-owner-expense-id": (
        {"owner_expense_items": [_EXPENSE_JSON, {**_EXPENSE_JSON, "first_year": 2}]},
        "DUPLICATE_ITEM_ID",
        "owner_expense_items[1].item_id",
    ),
    "cross-type-duplicate-id": (
        {"capital_items": [_CAPITAL_JSON], "owner_expense_items": [{**_EXPENSE_JSON, "item_id": "c-1"}]},
        "DUPLICATE_ITEM_ID",
        "owner_expense_items[0].item_id",
    ),
    "plan-not-an-object": ([], "MALFORMED_FIELD", "business_plan"),
    "collection-not-an-array": ({"capital_items": {}}, "MALFORMED_FIELD", "capital_items"),
    "item-not-an-object": ({"capital_items": [1]}, "MALFORMED_FIELD", "capital_items[0]"),
    "unknown-plan-field": ({"capital_item": []}, "MALFORMED_FIELD", "capital_item"),
    "unknown-item-field": (_capital(notes="x"), "MALFORMED_FIELD", "capital_items[0].notes"),
    "missing-item-field": (
        {"capital_items": [{k: v for k, v in _CAPITAL_JSON.items() if k != "amount"}]},
        "MALFORMED_FIELD",
        "capital_items[0].amount",
    ),
}


def _refusal(response: Any) -> list[tuple[str, str]]:
    assert response.status_code == 422, response.json()
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    for issue in detail:
        assert set(issue) == {"code", "path", "message"}, issue
        assert issue["message"]
    return [(issue["code"], issue["path"]) for issue in detail]


def _rooted(path: str) -> str:
    return path if path == "business_plan" else f"business_plan.{path}"


@pytest.mark.parametrize("case", sorted(_INVALID_PLANS))
def test_an_invalid_plan_is_refused_with_the_structured_issue_shape(
    client: TestClient, case: str
) -> None:
    raw, code, path = _INVALID_PLANS[case]

    issues = _refusal(client.post("/analyze", json={**analysis_request("quick"), "business_plan": raw}))

    assert (code, _rooted(path)) in issues


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_amount_is_refused(client: TestClient, token: str) -> None:
    body = json.dumps(
        {**analysis_request("quick"), "business_plan": _capital(amount="__NON_FINITE__")}
    ).replace('"__NON_FINITE__"', token)

    issues = _refusal(
        client.post("/analyze", content=body, headers={"content-type": "application/json"})
    )

    assert ("NON_FINITE_VALUE", "business_plan.capital_items[0].amount") in issues


# -- every plan-aware surface refuses the same way ---------------------------

_HURDLES = {"target_levered_irr": 0.12, "target_headline_dscr": 1.25, "target_equity_multiple": 1.6}
_TWO_WAY_FIELDS = {
    "quick": {
        "row_assumption": "exit_cap_rate",
        "row_values": [0.05, 0.06],
        "column_assumption": "purchase_price",
        "column_values": [45_000_000.0, 50_000_000.0],
        "metric": "equity_multiple",
    },
    "detailed": {
        "row_assumption": "exit_cap_rate",
        "row_values": [0.06, 0.07],
        "column_assumption": "purchase_price",
        "column_values": [9_000_000.0, 10_000_000.0],
        "metric": "equity_multiple",
    },
    "lease_level": {
        "row_assumption": "exit_cap_rate",
        "row_values": [0.06, 0.07],
        "column_assumption": "interest_rate",
        "column_values": [0.05, 0.06],
        "metric": "equity_multiple",
    },
}
_ONE_WAY_FIELDS = {
    mode: {"assumption": "exit_cap_rate", "values": [0.06, 0.065, 0.07], "metric": "equity_multiple"}
    for mode in MODES
}
_SURFACES = [
    *(("/analyze", mode) for mode in MODES),
    *(("/sensitivity", mode) for mode in MODES),
    *(("/sensitivity/one-way", mode) for mode in MODES),
    ("/sensitivity/presets", "quick"),
    ("/sensitivity/presets", "detailed"),
    ("/break-even", "quick"),
    ("/break-even", "detailed"),
    *(("/ai/analysis", mode) for mode in MODES),
    *(("/deals", mode) for mode in MODES),
    *(("/deals/fingerprint", mode) for mode in MODES),
]


def _surface_body(endpoint: str, mode: str, plan: object) -> dict[str, Any]:
    if endpoint == "/analyze":
        body = analysis_request(mode)
    else:
        extra = {
            "/sensitivity": _TWO_WAY_FIELDS[mode],
            "/sensitivity/one-way": _ONE_WAY_FIELDS[mode],
            "/sensitivity/presets": {},
            "/break-even": _HURDLES,
            "/ai/analysis": _HURDLES,
            "/deals": {"name": "Refused"},
            "/deals/fingerprint": {},
        }[endpoint]
        body = deal_request(mode, **extra)
    body["business_plan"] = plan
    return body


@pytest.mark.parametrize(("endpoint", "mode"), _SURFACES)
def test_every_plan_aware_surface_refuses_an_invalid_plan(
    client: TestClient, db: Path, endpoint: str, mode: str
) -> None:
    raw, code, path = _INVALID_PLANS["cross-type-duplicate-id"]
    no_provider = AssertionError("an invalid plan must be refused before any AI call")
    with (
        patch.object(api_module, "generate_ai_analysis", side_effect=no_provider),
        patch.object(api_module, "generate_detailed_ai_analysis", side_effect=no_provider),
        patch.object(api_module, "generate_lease_level_ai_analysis", side_effect=no_provider),
    ):
        issues = _refusal(client.post(endpoint, json=_surface_body(endpoint, mode, raw)))

    assert (code, _rooted(path)) in issues
    if endpoint == "/deals":
        assert client.get("/deals").json() == []


@pytest.mark.parametrize("mode", MODES)
def test_an_update_with_an_invalid_plan_changes_nothing(client: TestClient, mode: str) -> None:
    created = client.post("/deals", json=deal_request(mode, MATERIAL, name="Kept")).json()
    raw, code, path = _INVALID_PLANS["duplicate-capital-id"]

    issues = _refusal(
        client.put(f"/deals/{created['id']}", json={**deal_request(mode, name="Changed"), "business_plan": raw})
    )

    assert (code, _rooted(path)) in issues
    reopened = client.get(f"/deals/{created['id']}").json()
    assert reopened["name"] == "Kept" and reopened["business_plan"] == wire(MATERIAL)


# =============================================================================
# /analyze -- the API result is the direct D6 analysis
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_analyze_equals_the_direct_plan_aware_analysis(client: TestClient, mode: str) -> None:
    response = client.post("/analyze", json=analysis_request(mode, MATERIAL))

    assert response.status_code == 200, response.json()
    assert response.json() == jsonable_encoder(analysis_envelope(mode, MATERIAL))

    results = response.json() if mode == "quick" else response.json()["results"]
    assert results["closing_project_capital"] == 250_000.0
    assert results["project_capital_by_year"][1] == 1_000_000.0
    assert results["post_hold_project_capital"] == 300_000.0
    assert results["owner_expenses_by_year"] == [50_000.0, 50_000.0, 50_000.0, 75_000.0, 75_000.0]
    # Not the neutral fallback.
    assert response.json() != client.post("/analyze", json=analysis_request(mode)).json()


@pytest.mark.parametrize("mode", MODES)
def test_a_pre_d6_analyze_request_is_unchanged(client: TestClient, mode: str) -> None:
    response = client.post("/analyze", json=analysis_request(mode))

    assert response.status_code == 200
    assert response.json() == jsonable_encoder(analysis_envelope(mode, BusinessPlan()))


# =============================================================================
# Secondary routes receive the same plan
# =============================================================================


def _direct_two_way(mode: str, plan: BusinessPlan) -> Any:
    fields = {**_TWO_WAY_FIELDS[mode], "business_plan": plan}
    if mode == "quick":
        return run_two_way_sensitivity(QUICK, **fields)
    if mode == "detailed":
        return run_detailed_two_way_sensitivity(DETAILED_TERMS, DETAILED_OPERATING, **fields)
    return run_lease_level_two_way_sensitivity(
        LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES,
        market_leasing=LL_MARKET, operating_inputs=LL_OPERATING, **fields,
    )


def _direct_one_way(mode: str, plan: BusinessPlan) -> Any:
    fields = {**_ONE_WAY_FIELDS[mode], "business_plan": plan}
    if mode == "quick":
        return run_one_way_sensitivity(QUICK, **fields)
    if mode == "detailed":
        return run_detailed_one_way_sensitivity(DETAILED_TERMS, DETAILED_OPERATING, **fields)
    return run_lease_level_one_way_sensitivity(
        LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES,
        market_leasing=LL_MARKET, operating_inputs=LL_OPERATING, **fields,
    )


def _direct_presets(mode: str, plan: BusinessPlan) -> Any:
    if mode == "quick":
        return build_standard_presets(QUICK, business_plan=plan)
    return build_standard_detailed_presets(DETAILED_TERMS, DETAILED_OPERATING, business_plan=plan)


def _direct_break_even(mode: str, plan: BusinessPlan) -> Any:
    targets = {**_HURDLES, "return_hurdle_metric": ReturnHurdleMetric.LEVERED_IRR, "business_plan": plan}
    if mode == "quick":
        return build_standard_break_even_analysis(QUICK, **targets)
    return build_standard_detailed_break_even_analysis(DETAILED_TERMS, DETAILED_OPERATING, **targets)


_SECONDARY = [
    *(("/sensitivity", mode, _TWO_WAY_FIELDS[mode], _direct_two_way) for mode in MODES),
    *(("/sensitivity/one-way", mode, _ONE_WAY_FIELDS[mode], _direct_one_way) for mode in MODES),
    *(("/sensitivity/presets", mode, {}, _direct_presets) for mode in ("quick", "detailed")),
    *(("/break-even", mode, _HURDLES, _direct_break_even) for mode in ("quick", "detailed")),
]


@pytest.mark.parametrize(
    ("endpoint", "mode", "fields", "direct"),
    _SECONDARY,
    ids=[f"{endpoint}-{mode}" for endpoint, mode, _, _ in _SECONDARY],
)
def test_a_secondary_route_runs_on_the_requested_plan(
    client: TestClient, endpoint: str, mode: str, fields: dict[str, Any], direct: Any
) -> None:
    with_plan = client.post(endpoint, json=deal_request(mode, MATERIAL, **fields))
    without_plan = client.post(endpoint, json=deal_request(mode, **fields))

    assert with_plan.status_code == 200, with_plan.json()
    assert with_plan.json() == jsonable_encoder(direct(mode, MATERIAL))
    assert without_plan.json() == jsonable_encoder(direct(mode, BusinessPlan()))
    assert with_plan.json() != without_plan.json()


@pytest.mark.parametrize(
    ("mode", "generator"),
    [("quick", "generate_ai_analysis"), ("detailed", "generate_detailed_ai_analysis")],
)
def test_the_ai_analyst_is_handed_the_requested_plan(
    client: TestClient, mode: str, generator: str
) -> None:
    """Mechanical plumbing only (Part R): the plan reaches the D6.4 AI context
    builders, which already thread it. No grounding is added here."""

    for plan, expected in ((MATERIAL, MATERIAL), (None, BusinessPlan())):
        with patch.object(api_module, generator, return_value=AI_ANALYSIS) as spy:
            response = client.post("/ai/analysis", json=deal_request(mode, plan, **_HURDLES))

        assert response.status_code == 200, response.json()
        assert spy.call_count == 1
        assert spy.call_args.kwargs["business_plan"] == expected


def test_the_lease_level_ai_analyst_describes_the_plan_aware_analysis(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def _fake(terms: Any, lease_level_inputs: Any, lease_level_results: Any, **_: Any) -> Any:
        captured["results"] = lease_level_results
        return AI_ANALYSIS

    monkeypatch.setattr(api_module, "generate_lease_level_ai_analysis", _fake)
    response = client.post("/ai/analysis", json=deal_request("lease_level", MATERIAL, **_HURDLES))

    assert response.status_code == 200, response.json()
    assert captured["results"] == analyze_lease_level_acquisition_with_business_plan(
        LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES,
        market_leasing=LL_MARKET, operating_inputs=LL_OPERATING, business_plan=MATERIAL,
    )


# =============================================================================
# The deal lifecycle over HTTP
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_deal_api_carries_the_plan_through_its_whole_lifecycle(
    client: TestClient, db: Path, mode: str
) -> None:
    created = client.post("/deals", json=deal_request(mode, MATERIAL, name="API deal"))
    assert created.status_code == 200, created.json()
    body = created.json()
    deal_id = body["id"]
    assert body["business_plan"] == wire(MATERIAL)

    assert client.get(f"/deals/{deal_id}").json()["business_plan"] == wire(MATERIAL)
    listed = {deal["id"]: deal for deal in client.get("/deals").json()}
    assert listed[deal_id]["business_plan"] == wire(MATERIAL)

    # A reopened plan resubmits unchanged -- the response *is* the request shape.
    resubmitted = client.put(
        f"/deals/{deal_id}",
        json={**deal_request(mode, name="API deal"), "business_plan": body["business_plan"]},
    )
    assert resubmitted.json()["business_plan"] == wire(MATERIAL)

    smaller = BusinessPlan(owner_expense_items=MATERIAL.owner_expense_items[:1])
    replaced = client.put(f"/deals/{deal_id}", json=deal_request(mode, smaller, name="API deal"))
    assert replaced.json()["business_plan"] == wire(smaller)
    assert plan_rows(db, deal_id) == (0, 1)

    copy = client.post(f"/deals/{deal_id}/duplicate", json={}).json()
    assert copy["id"] != deal_id and copy["business_plan"] == wire(smaller)

    # Absent means empty: a save that carries no plan clears it.
    cleared = client.put(f"/deals/{deal_id}", json=deal_request(mode, name="API deal"))
    assert cleared.json()["business_plan"] == {"capital_items": [], "owner_expense_items": []}
    assert plan_rows(db, deal_id) == (0, 0)
    assert client.get(f"/deals/{copy['id']}").json()["business_plan"] == wire(smaller)

    assert client.delete(f"/deals/{copy['id']}").status_code == 204
    assert plan_rows(db, copy["id"]) == (0, 0)


def test_the_saved_plan_response_carries_what_an_editor_needs(client: TestClient) -> None:
    plan = client.post("/deals", json=deal_request("quick", MATERIAL, name="Editor")).json()[
        "business_plan"
    ]

    assert set(plan) == {"capital_items", "owner_expense_items"}
    assert [set(item) for item in plan["capital_items"]] == [
        {"item_id", "description", "category", "month", "amount"}
    ] * 3
    assert [set(item) for item in plan["owner_expense_items"]] == [
        {"item_id", "description", "category", "annual_amount", "first_year", "last_year"}
    ] * 2
    assert [item["item_id"] for item in plan["capital_items"]] == ["cap-C", "cap-A", "cap-B"]
    assert [item["item_id"] for item in plan["owner_expense_items"]] == ["oe-Z", "oe-Y"]
    assert plan["capital_items"][0] == {
        "item_id": "cap-C",
        "description": "Roof and HVAC replacement",
        "category": "building_systems",
        "month": 18,
        "amount": 1_000_000.0,
    }
    assert plan["owner_expense_items"][0]["last_year"] is None
    assert plan["owner_expense_items"][1]["last_year"] == 8


# =============================================================================
# Provenance -- /deals/fingerprint hashes the plan exactly as the store does
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_fingerprint_endpoint_includes_the_plan_and_matches_the_store(
    client: TestClient, mode: str
) -> None:
    token = client.post("/deals/fingerprint", json=deal_request(mode, MATERIAL)).json()[
        "financial_input_fingerprint"
    ]
    plan_free = client.post("/deals/fingerprint", json=deal_request(mode)).json()[
        "financial_input_fingerprint"
    ]

    assert token == input_fingerprint(mode, MATERIAL)
    assert plan_free == PRE_D6_5_DIGESTS[mode]
    assert token != plan_free

    deal_id = client.post("/deals", json=deal_request(mode, MATERIAL, name="Provenance")).json()[
        "id"
    ]
    if mode == "lease_level":
        route = f"/deals/{deal_id}/sensitivity-snapshot/one-way"
        snapshot = {"sensitivity_snapshot": as_dict(ONE_WAY)}
        served = "one_way_sensitivity_snapshot"
    else:
        route = f"/deals/{deal_id}/analysis-snapshot"
        snapshot = {
            "analysis_snapshot": client.post(
                "/analyze", json=analysis_request(mode, MATERIAL)
            ).json()
        }
        served = "analysis_snapshot"

    refused = client.put(route, json={**snapshot, "financial_input_fingerprint": plan_free})
    assert refused.status_code == 422
    accepted = client.put(route, json={**snapshot, "financial_input_fingerprint": token})
    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()[served] is not None
    assert client.get(f"/deals/{deal_id}").json()[served] is not None
