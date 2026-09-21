"""Phase 7 Gate P7.10 Stage 2 -- the typed API surface.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 6.2, 14, 15 and
16. Every Stage 2 route is exercised for success, typed refusal, unavailable,
stale and not-found as each applies.

The rule the whole suite is really about: **an expected unavailable state is a
200 carrying a typed reason, never a server error and never a number.** A real
defect still fails as an error, which is what makes the distinction worth
anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]
from anchor import api as api_module

BASE, BASE_SCENARIO = "base", "base"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "anchor.db"))
    return TestClient(api_module.app)


QUICK_BODY = {
    "purchase_price": 10_000_000.0,
    "current_noi": 600_000.0,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.06,
    "ltv": 0.0,
    "interest_rate": 0.055,
    "amortization": 30,
}


def _deal(client: TestClient) -> str:
    return client.post("/deals", json={"name": "API deal", "inputs": QUICK_BODY}).json()["id"]


def _as_is(unit_id: str, *, timepoint_id: str = "as-is", cap_rate: float = 0.055) -> dict[str, Any]:
    return {
        "timepoint_id": timepoint_id,
        "kind": "as_is",
        "label": "As-Is",
        "model_month": 0,
        "unit_instructions": [
            {"unit_id": unit_id, "method": {"kind": "direct_cap", "cap_rate": cap_rate}}
        ],
    }


def _memo_body(**changes: Any) -> dict[str, Any]:
    body = {
        "prepared_by": "A. Analyst",
        "decision_ask": "Approve the acquisition at $10.0m.",
        "analyst_recommendation": "approve_with_conditions",
        "executive_summary": "Core-plus asset.",
        "execution_complexity": "moderate",
        "return_on_time_notes": "",
        "selected_decision": {
            "strategy_id": BASE,
            "scenario_id": BASE_SCENARIO,
            "perspective": "project",
            "position_id": None,
            "partner_id": None,
        },
        "items": [
            {"item_id": "t1", "section": "thesis", "display_order": 0, "text": "Below replacement cost."}
        ],
        "risk_items": [
            {
                "item_id": "r1",
                "display_order": 0,
                "text": "Year-3 rollover.",
                "severity": "moderate",
                "residual_risk": "low",
                "mitigant": None,
            }
        ],
        "term_items": [
            {"item_id": "x1", "display_order": 0, "text": "60-day DD.", "priority": "required"}
        ],
        "evidence_ids": [],
    }
    body.update(changes)
    return body


def _opted_in(client: TestClient) -> tuple[str, str]:
    deal_id = _deal(client)
    investment_id = client.post(
        f"/deals/{deal_id}/valuation-timepoints", json=_as_is(deal_id)
    ).json()["investment_id"]
    return deal_id, investment_id


def _published(client: TestClient) -> tuple[str, str, dict[str, Any]]:
    deal_id, investment_id = _opted_in(client)
    client.put(f"/investments/{investment_id}/memo", json=_memo_body())
    version = client.post(f"/investments/{investment_id}/memo/publish").json()["memo_version"]
    return deal_id, investment_id, version


# =============================================================================
# Valuation definitions
# =============================================================================


def test_the_deal_door_materializes_on_the_first_save_only(client: TestClient) -> None:
    deal_id = _deal(client)

    read = client.get(f"/deals/{deal_id}/valuation-timepoints")
    assert read.status_code == 200
    assert read.json() == {"deal_id": deal_id, "investment_id": None, "valuation_timepoints": []}

    created = client.post(f"/deals/{deal_id}/valuation-timepoints", json=_as_is(deal_id))
    assert created.status_code == 200
    assert created.json()["investment_id"] is not None


def test_the_full_definition_lifecycle(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)

    assert len(client.get(f"/investments/{investment_id}/valuation-timepoints").json()[
        "valuation_timepoints"
    ]) == 1

    one = client.get(f"/investments/{investment_id}/valuation-timepoints/as-is")
    assert one.status_code == 200
    assert one.json()["valuation_timepoint"]["model_month"] == 0

    updated = client.put(
        f"/investments/{investment_id}/valuation-timepoints/as-is",
        json=_as_is(deal_id, cap_rate=0.05),
    )
    assert updated.status_code == 200
    assert updated.json()["valuation_timepoint"]["unit_instructions"][0]["method"]["cap_rate"] == 0.05

    assert client.delete(f"/investments/{investment_id}/valuation-timepoints/as-is").status_code == 204


def test_an_unknown_timepoint_is_404_and_never_discloses_another_investment(
    client: TestClient,
) -> None:
    _, first = _opted_in(client)
    second_deal = client.post("/deals", json={"name": "Other", "inputs": QUICK_BODY}).json()["id"]
    second = client.post(
        f"/deals/{second_deal}/valuation-timepoints", json=_as_is(second_deal, timepoint_id="other")
    ).json()["investment_id"]

    missing = client.get(f"/investments/{first}/valuation-timepoints/other")
    assert missing.status_code == 404
    assert second not in missing.text


@pytest.mark.parametrize(
    "body, expect",
    [
        ({"model_month": 7}, "multiple of 12"),
        ({"model_month": 24}, "always model month 0"),
    ],
)
def test_an_invalid_definition_is_a_structured_422(
    client: TestClient, body: dict[str, Any], expect: str
) -> None:
    deal_id, investment_id = _opted_in(client)
    payload = {**_as_is(deal_id, timepoint_id="bad"), **body}
    response = client.post(f"/investments/{investment_id}/valuation-timepoints", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail[0]["code"]
    assert expect in detail[0]["message"]


def test_an_unknown_method_kind_is_refused_structurally(client: TestClient) -> None:
    """Nothing is inferred: a method with no ``kind`` never reads as a direct
    capitalisation."""

    deal_id, investment_id = _opted_in(client)
    payload = _as_is(deal_id, timepoint_id="odd")
    payload["unit_instructions"][0]["method"] = {"kind": "dcf", "rate": 0.08}
    response = client.post(f"/investments/{investment_id}/valuation-timepoints", json=payload)
    assert response.status_code == 422
    assert "direct_cap" in response.text and "analyst_value" in response.text


def test_an_unknown_body_key_is_refused(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    payload = {**_as_is(deal_id, timepoint_id="extra"), "oops": 1}
    assert client.post(f"/investments/{investment_id}/valuation-timepoints", json=payload).status_code == 422


def test_a_path_and_body_id_disagreement_is_refused(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    response = client.put(
        f"/investments/{investment_id}/valuation-timepoints/as-is",
        json=_as_is(deal_id, timepoint_id="something-else"),
    )
    assert response.status_code == 422
    assert "they must agree" in response.text


def test_reordering_is_its_own_route(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    client.post(
        f"/investments/{investment_id}/valuation-timepoints",
        json={**_as_is(deal_id, timepoint_id="later"), "kind": "stabilized", "model_month": 24},
    )
    response = client.post(
        f"/investments/{investment_id}/valuation-timepoint-order",
        json={"timepoint_ids": ["later", "as-is"]},
    )
    assert response.status_code == 200
    assert [t["timepoint_id"] for t in response.json()["valuation_timepoints"]] == ["later", "as-is"]

    partial = client.post(
        f"/investments/{investment_id}/valuation-timepoint-order", json={"timepoint_ids": ["as-is"]}
    )
    assert partial.status_code == 409


# =============================================================================
# Evidence
# =============================================================================


def test_the_evidence_lifecycle_and_its_in_use_refusal(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    body = {
        "evidence_id": "ev-1",
        "source_kind": "sales_comp",
        "title": "Q3 comps",
        "reference": "doc://comps/q3",
        "as_of_date": "2026-06-30",
        "approved": True,
        "display_order": 0,
    }
    assert client.put(f"/investments/{investment_id}/evidence-references/ev-1", json=body).status_code == 200
    listed = client.get(f"/investments/{investment_id}/evidence-references").json()
    assert [e["evidence_id"] for e in listed["evidence_references"]] == ["ev-1"]

    client.post(
        f"/investments/{investment_id}/valuation-timepoints",
        json={
            "timepoint_id": "analyst",
            "kind": "custom",
            "label": "Analyst-Supplied",
            "model_month": 12,
            "unit_instructions": [
                {
                    "unit_id": deal_id,
                    "method": {"kind": "analyst_value", "amount": 12_500_000.0, "evidence_id": "ev-1"},
                }
            ],
        },
    )
    blocked = client.delete(f"/investments/{investment_id}/evidence-references/ev-1")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["valuation_timepoint_ids"] == ["analyst"]

    assert client.delete(f"/investments/{investment_id}/valuation-timepoints/analyst").status_code == 204
    assert client.delete(f"/investments/{investment_id}/evidence-references/ev-1").status_code == 204
    assert client.delete(f"/investments/{investment_id}/evidence-references/ev-1").status_code == 404


def test_an_unparseable_as_of_date_is_a_structured_422(client: TestClient) -> None:
    """Refused by the domain, not swallowed by broad exception handling in the
    route."""

    deal_id, investment_id = _opted_in(client)
    response = client.put(
        f"/investments/{investment_id}/evidence-references/ev-x",
        json={
            "evidence_id": "ev-x",
            "source_kind": "other",
            "title": "t",
            "reference": "r",
            "as_of_date": "not-a-date",
            "approved": False,
            "display_order": 0,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["code"] == "invalid_as_of_date"


def test_a_missing_approval_is_never_read_as_approved(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    response = client.put(
        f"/investments/{investment_id}/evidence-references/ev-y",
        json={
            "evidence_id": "ev-y",
            "source_kind": "other",
            "title": "t",
            "reference": "r",
            "as_of_date": None,
            "approved": None,
            "display_order": 0,
        },
    )
    assert response.status_code == 422
    assert "never read as approved" in response.text


# =============================================================================
# Resolved views: the unavailable contract (Section 6.2)
# =============================================================================


def test_an_available_view_reports_its_operands(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    body = client.post(f"/investments/{investment_id}/valuation-views/{BASE}/{BASE_SCENARIO}")
    assert body.status_code == 200
    (view,) = body.json()["views"]
    assert view["status"] == "available"
    assert view["value"] == pytest.approx(600_000.0 / 0.055)
    assert view["unit_views"][0]["forward_noi"] == pytest.approx(600_000.0)
    assert view["unit_views"][0]["analyst_supplied"] is False


def test_an_unavailable_view_is_200_with_a_typed_reason_and_no_value(client: TestClient) -> None:
    """The Section 6.2 obligation, on the wire. The unapproved amount appears
    nowhere in the response."""

    deal_id, investment_id = _opted_in(client)
    client.put(
        f"/investments/{investment_id}/evidence-references/ev-1",
        json={
            "evidence_id": "ev-1",
            "source_kind": "broker_research",
            "title": "BOV",
            "reference": "doc://bov",
            "as_of_date": None,
            "approved": False,
            "display_order": 0,
        },
    )
    client.post(
        f"/investments/{investment_id}/valuation-timepoints",
        json={
            "timepoint_id": "analyst",
            "kind": "custom",
            "label": "Analyst-Supplied",
            "model_month": 12,
            "unit_instructions": [
                {
                    "unit_id": deal_id,
                    "method": {"kind": "analyst_value", "amount": 12_500_000.0, "evidence_id": "ev-1"},
                }
            ],
        },
    )
    response = client.post(f"/investments/{investment_id}/valuation-views/{BASE}/{BASE_SCENARIO}")
    assert response.status_code == 200

    view = next(v for v in response.json()["views"] if v["timepoint_id"] == "analyst")
    assert view["status"] == "unavailable"
    assert view["value"] is None
    assert view["unavailable"]["reason_code"] == "evidence_not_approved"
    assert view["unavailable"]["reason"]
    assert "12500000" not in response.text and "12,500,000" not in response.text


def test_an_unresolvable_value_sized_funding_is_200_with_no_amount(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    client.put(
        f"/deals/{deal_id}/capital-structure",
        json={
            "positions": [
                {
                    "position_id": "senior",
                    "name": "Senior",
                    "position_class": "senior_debt",
                    "priority": 1,
                    "scope": {"kind": "unit", "unit_id": deal_id},
                    "funding": [
                        {
                            "event_id": "close",
                            "model_month": 0,
                            "sequence": 1,
                            "amount_rule": {"kind": "pct_of_value", "timepoint_id": "missing", "pct": 0.6},
                        }
                    ],
                    "terms": {
                        "kind": "debt",
                        "interest_rate": 0.06,
                        "amortization": 30,
                        "io_period": 0,
                        "maturity_month": 60,
                        "fees": [],
                        "current_pay_rate": 0.06,
                        "pik_rate": 0.0,
                    },
                    "shortfall_resolution": "common_equity_contribution",
                },
                {
                    "position_id": "common",
                    "name": "Common Equity",
                    "position_class": "common_equity",
                    "priority": 99,
                    "scope": {"kind": "unit", "unit_id": deal_id},
                    "funding": [],
                    "terms": None,
                    "shortfall_resolution": None,
                },
            ]
        },
    )
    response = client.post(f"/investments/{investment_id}/valuation-views/{BASE}/{BASE_SCENARIO}")
    assert response.status_code == 200
    (state,) = response.json()["funding_states"]
    assert state["status"] == "unavailable"
    assert state["amount"] is None
    assert state["unavailable"]["reason_code"] == "funding_requirement_unresolved"
    assert "10000000" not in response.text, "never the purchase price"


def test_an_invalid_variant_is_a_typed_refusal_not_a_server_error(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    response = client.post(f"/investments/{investment_id}/valuation-views/no-such-strategy/{BASE_SCENARIO}")
    assert response.status_code == 404
    assert response.status_code != 500


# =============================================================================
# The memo draft
# =============================================================================


def test_the_memo_draft_lifecycle_through_both_doors(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)

    assert client.get(f"/investments/{investment_id}/memo").json()["memo"] is None
    saved = client.put(f"/investments/{investment_id}/memo", json=_memo_body())
    assert saved.status_code == 200
    assert saved.json()["memo"]["decision_ask"] == "Approve the acquisition at $10.0m."

    through_deal = client.get(f"/deals/{deal_id}/memo").json()
    assert through_deal["investment_id"] == investment_id
    assert through_deal["memo"]["memo_id"] == saved.json()["memo"]["memo_id"]

    assert client.delete(f"/investments/{investment_id}/memo").status_code == 204
    assert client.delete(f"/investments/{investment_id}/memo").status_code == 404


def test_a_deal_memo_materializes_the_wrapper_on_first_save(client: TestClient) -> None:
    deal_id = _deal(client)
    assert client.get(f"/deals/{deal_id}/memo").json()["investment_id"] is None
    saved = client.put(f"/deals/{deal_id}/memo", json=_memo_body())
    assert saved.status_code == 200
    assert saved.json()["investment_id"] is not None


def test_a_memo_naming_an_unknown_reference_is_404(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    response = client.put(
        f"/investments/{investment_id}/memo", json=_memo_body(evidence_ids=["nope"])
    )
    assert response.status_code == 404


def test_a_perspective_scope_mismatch_is_refused(client: TestClient) -> None:
    """A PROJECT perspective states neither a position nor a partner; guessing
    which stakeholder the analyst meant is what a decision memo must not do."""

    deal_id, investment_id = _opted_in(client)
    response = client.put(
        f"/investments/{investment_id}/memo",
        json=_memo_body(
            selected_decision={
                "strategy_id": BASE,
                "scenario_id": BASE_SCENARIO,
                "perspective": "project",
                "position_id": "senior",
                "partner_id": None,
            }
        ),
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["code"] == "perspective_scope_mismatch"


def test_a_missing_recommendation_is_refused_not_defaulted(client: TestClient) -> None:
    deal_id, investment_id = _opted_in(client)
    response = client.put(
        f"/investments/{investment_id}/memo", json=_memo_body(analyst_recommendation=None)
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["code"] == "unknown_recommendation"


# =============================================================================
# Publication, versions and freshness
# =============================================================================


def test_publication_readiness_names_every_refusal(client: TestClient) -> None:
    """A well-formed draft can still be unpublishable: the selected Strategy
    must exist and the cell must resolve. The product disables publication with
    these reasons rather than letting an analyst discover them by failing."""

    deal_id, investment_id = _opted_in(client)
    saved = client.put(
        f"/investments/{investment_id}/memo",
        json=_memo_body(
            selected_decision={
                "strategy_id": "no-such-strategy",
                "scenario_id": BASE_SCENARIO,
                "perspective": "project",
                "position_id": None,
                "partner_id": None,
            }
        ),
    )
    assert saved.status_code == 200, "a draft may name a cell that has since gone"

    ready = client.get(f"/investments/{investment_id}/memo/publication-readiness")
    assert ready.status_code == 200
    assert ready.json()["publishable"] is False
    codes = {r["code"] for r in ready.json()["refusals"]}
    assert "selected_strategy_missing" in codes
    assert all(r["message"] for r in ready.json()["refusals"])

    refused = client.post(f"/investments/{investment_id}/memo/publish")
    assert refused.status_code == 422
    assert "selected_strategy_missing" in {r["code"] for r in refused.json()["detail"]}
    assert client.get(f"/investments/{investment_id}/memo-versions").json()["memo_versions"] == []


def test_publication_readiness_is_404_without_a_draft(client: TestClient) -> None:
    _, investment_id = _opted_in(client)
    assert client.get(f"/investments/{investment_id}/memo/publication-readiness").status_code == 404
    assert client.post(f"/investments/{investment_id}/memo/publish").status_code == 404


def test_publishing_and_listing_versions(client: TestClient) -> None:
    deal_id, investment_id, version = _published(client)
    assert version["version_number"] == 1
    assert version["dependencies"]
    assert version["valuations"][0]["status"] == "available"

    listed = client.get(f"/investments/{investment_id}/memo-versions").json()["memo_versions"]
    assert [v["version_number"] for v in listed] == [1]

    one = client.get(f"/investments/{investment_id}/memo-versions/{version['version_id']}")
    assert one.status_code == 200
    assert one.json()["memo_version"] == version

    assert client.get(f"/investments/{investment_id}/memo-versions/nope").status_code == 404


def test_freshness_is_200_and_names_the_changed_class(client: TestClient) -> None:
    deal_id, investment_id, version = _published(client)
    path = f"/investments/{investment_id}/memo-versions/{version['version_id']}/freshness"

    current = client.get(path).json()
    assert current["freshness"] == "current"
    assert current["stale_classes"] == []

    client.put(
        f"/investments/{investment_id}/valuation-timepoints/as-is",
        json=_as_is(deal_id, cap_rate=0.05),
    )
    stale = client.get(path)
    assert stale.status_code == 200, "a stale version is a successful answer"
    assert stale.json()["freshness"] == "stale"
    assert set(stale.json()["stale_classes"]) == {"valuation_definitions", "valuation_results"}
    assert all(entry["reason"] for entry in stale.json()["stale_dependencies"])

    # The version itself is unchanged and still readable.
    assert client.get(
        f"/investments/{investment_id}/memo-versions/{version['version_id']}"
    ).json()["memo_version"] == version


def test_republishing_creates_a_new_version_and_leaves_the_first(client: TestClient) -> None:
    deal_id, investment_id, v1 = _published(client)
    client.put(
        f"/investments/{investment_id}/memo",
        json=_memo_body(decision_ask="Decline.", analyst_recommendation="decline"),
    )
    v2 = client.post(f"/investments/{investment_id}/memo/publish").json()["memo_version"]

    assert v2["version_number"] == 2
    assert v2["analyst_recommendation"] == "decline"
    assert client.get(
        f"/investments/{investment_id}/memo-versions/{v1['version_id']}"
    ).json()["memo_version"] == v1


# =============================================================================
# The Investment Committee decision (R-F)
# =============================================================================


def test_the_ic_decision_is_its_own_route_and_moves_no_version(client: TestClient) -> None:
    deal_id, investment_id, version = _published(client)
    path = f"/investments/{investment_id}/memo-versions/{version['version_id']}/decision"

    assert client.get(path).json()["decision"] is None

    recorded = client.put(
        path,
        json={
            "decision": "approved_with_conditions",
            "decision_note": "Subject to DD.",
            "decided_at": "2026-09-20",
        },
    )
    assert recorded.status_code == 200
    assert recorded.json()["decision"]["decision"] == "approved_with_conditions"

    after = client.get(
        f"/investments/{investment_id}/memo-versions/{version['version_id']}"
    ).json()["memo_version"]
    assert after == version
    assert after["analyst_recommendation"] == "approve_with_conditions"


def test_an_unknown_committee_outcome_is_refused(client: TestClient) -> None:
    deal_id, investment_id, version = _published(client)
    response = client.put(
        f"/investments/{investment_id}/memo-versions/{version['version_id']}/decision",
        json={"decision": "rubber_stamped", "decision_note": None, "decided_at": None},
    )
    assert response.status_code == 422


def test_a_decision_on_an_unknown_version_is_404(client: TestClient) -> None:
    _, investment_id = _opted_in(client)
    assert client.put(
        f"/investments/{investment_id}/memo-versions/nope/decision",
        json={"decision": "approved", "decision_note": None, "decided_at": None},
    ).status_code == 404


# =============================================================================
# Coverage
# =============================================================================


def test_every_p7_10_route_is_covered_by_this_suite() -> None:
    """The prompt's requirement 8, measured: every Stage 2 route appears in this
    module's own assertions, so a route added later without a test is visible."""

    import re

    source = Path(__file__).read_bytes().decode("utf-8")
    routes = {
        (method, route.path)  # type: ignore[attr-defined]
        for route in api_module.app.routes
        for method in getattr(route, "methods", ()) or ()
        if any(
            word in str(getattr(route, "path", ""))
            for word in ("valuation-timepoint", "valuation-views", "evidence-references", "/memo")
        )
    }
    assert len(routes) == 24
    for _, path in routes:
        # The route's distinctive tail must appear somewhere in this file.
        tail = re.sub(r"\{[^}]+\}", "", path).rstrip("/").rsplit("/", 1)[-1]
        assert tail in source, path
