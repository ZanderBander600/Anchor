"""Refinance & Capital Events V1 Stage 2 -- the API contracts.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 11.5, 12.5, 15
and 16.2. Proves, through the real routes:

- the Capital Structure payloads carry ``capital_events`` additively: an evented
  body round-trips exactly, every union carries its ``kind``, and an absent or
  empty member is the empty set with no ``capital_events`` key on the wire;
- a reserve-like or otherwise unknown member is refused as an unknown field,
  and every authoring fault is the established typed 422, never a 500;
- the accepted closing-only doors are narrowed exactly: only a
  ``refinance_proceeds`` funding and a replacement's fees may be later;
- a refinance-bearing analysis carries the typed event results, separate value
  and NOI dependencies, capacities and binding constraints, the bridge, the
  Common Equity decomposition and the primary-return facts; an unavailable
  amount is ``null``, never ``0``;
- Partner returns are named the primary investor namespace wherever a
  Partnership exists, and an unavailable refinance is itself the primary answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from _p7_9_fixtures import f1_terms  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.deals import store


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "anchor.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(api_module.app)


def _put(client: TestClient, deal_id: str, body: Any) -> Any:
    return client.put(f"/deals/{deal_id}/capital-structure", json=body)


def _analysis(client: TestClient, investment_id: str, strategy_id: str = "base") -> dict[str, Any]:
    response = client.post(f"/investments/{investment_id}/structured-variants/{strategy_id}/base/analysis")
    assert response.status_code == 200, response.text
    return response.json()


# =============================================================================
# Authoring
# =============================================================================


def test_an_evented_body_round_trips_exactly_with_every_kind_stated(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    body = api_module._wire(fx.full_member_structure(deal.id))
    assert set(body) == {"positions", "capital_events"}
    response = _put(client, deal.id, body)
    assert response.status_code == 200, response.text
    assert response.json()["capital_structure"] == body
    assert client.get(f"/deals/{deal.id}/capital-structure").json()["capital_structure"] == body

    (event,) = body["capital_events"]
    assert event["kind"] == "refinance"
    assert [ref["kind"] for ref in event["retiring"]] == ["legacy_acquisition_loan", "authored_position"]
    assert event["retiring"][0] == {"kind": "legacy_acquisition_loan", "unit_id": deal.id}
    assert event["sizing"] == {"fixed_cap": {"amount": 7_500_000.0}, "max_ltv": {"max_ltv": 0.65}, "min_dscr": {"min_dscr": 2.0}}
    assert event["valuation"] == {"timepoint_id": fx.TIMEPOINT_ID}
    (replacement, _) = body["positions"]
    assert replacement["funding"][0]["amount_rule"] == {"kind": "refinance_proceeds", "capital_event_id": fx.EVENT_ID}


def test_a_body_without_events_is_answered_exactly_as_before(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    body = api_module._wire(fx.closing_mezz_only(deal.id))
    assert set(body) == {"positions"}
    saved = _put(client, deal.id, body).json()["capital_structure"]
    assert saved == body and "capital_events" not in saved

    explicit_empty = _put(client, deal.id, {**body, "capital_events": []}).json()["capital_structure"]
    assert explicit_empty == body
    assert type(store.read_deal_capital_structure(deal.id, db_path=db)[1]).__name__ == "CapitalStructure"


@pytest.mark.parametrize(
    "where",
    ["event", "sizing", "cost", "retiring", "timing", "valuation", "proceeds"],
)
def test_a_reserve_like_member_is_an_unknown_field(client: TestClient, db: Path, where: str) -> None:
    deal = fx.base_deal(db)
    body = api_module._wire(fx.full_member_structure(deal.id))
    event = body["capital_events"][0]
    target = {
        "event": event,
        "sizing": event["sizing"],
        "cost": event["costs"][0],
        "retiring": event["retiring"][0],
        "timing": event["timing"],
        "valuation": event["valuation"],
        "proceeds": body["positions"][0]["funding"][0]["amount_rule"],
    }[where]
    target["reserve_holdback"] = 250_000.0
    response = _put(client, deal.id, body)
    assert response.status_code == 422
    assert "reserve_holdback" in response.text
    assert store.read_deal_capital_structure(deal.id, db_path=db)[1].positions == ()


def test_an_unknown_reference_kind_is_refused(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    body = api_module._wire(fx.evented(deal.id, dscr=2.0))
    body["capital_events"][0]["retiring"][0] = {"kind": "legacy-acquisition-loan:" + deal.id, "unit_id": deal.id}
    assert _put(client, deal.id, body).status_code == 422


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda event: event.update(valuation={"timepoint_id": fx.TIMEPOINT_ID}), "valuation_reference_unused"),
        (lambda event: event["sizing"].update(min_dscr=None), "no_sizing_constraint"),
        (lambda event: event.update(kind="recapitalization"), "unsupported_capital_event_kind"),
        (lambda event: event["timing"].update(model_month=18), "event_month_not_hold_year_end"),
        (lambda event: event.update(replacement_position_id="nobody"), "replacement_position_not_found"),
    ],
)
def test_authoring_faults_are_the_typed_422(client: TestClient, db: Path, change: Any, code: str) -> None:
    deal = fx.base_deal(db)
    body = api_module._wire(fx.evented(deal.id, dscr=2.0))
    change(body["capital_events"][0])
    response = _put(client, deal.id, body)
    assert response.status_code == 422, response.text
    assert code in {issue["code"] for issue in response.json()["detail"]}


def test_the_closing_only_doors_are_narrowed_exactly(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    # A later FixedAmount funding is still refused at the door.
    later = api_module._wire(fx.closing_mezz_only(deal.id))
    later["positions"][0]["funding"][0]["model_month"] = 24
    response = _put(client, deal.id, later)
    assert response.status_code == 422 and response.json()["detail"][0]["code"] == "unsupported_funding_timing"

    # A later fee on an ordinary position is still refused at the door.
    fee = api_module._wire(fx.closing_mezz_only(deal.id))
    fee["positions"][0]["terms"]["fees"] = [
        {"fee_id": "f", "description": "Later", "amount": 1.0, "model_month": 24, "sequence": 2}
    ]
    response = _put(client, deal.id, fee)
    assert response.status_code == 422 and response.json()["detail"][0]["code"] == "unsupported_fee_timing"

    # A replacement's fee at its event month is accepted...
    assert _put(client, deal.id, api_module._wire(fx.evented(deal.id, dscr=2.0, replacement_fees=(fx.rf.lender_fee(80_000.0),)))).status_code == 200
    # ...and at any other month is the validator's typed refusal.
    off = api_module._wire(fx.evented(deal.id, dscr=2.0, replacement_fees=(fx.rf.lender_fee(80_000.0, month=36),)))
    response = _put(client, deal.id, off)
    assert response.status_code == 422
    assert "replacement_fee_timing" in {issue["code"] for issue in response.json()["detail"]}


# =============================================================================
# Results
# =============================================================================


def test_an_executed_refinance_reports_every_typed_result_and_the_primary_view(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id = _put(client, deal.id, api_module._wire(fx.evented(deal.id, dscr=2.0))).json()["investment_id"]
    body = _analysis(client, investment_id)

    (event,) = body["result"]["capital_events"]
    assert event["status"] == "executed" and event["unavailable_reason"] is None
    assert event["value_dependency"] is None
    assert event["noi_dependency"]["forward_noi"] == 800_000.0 and event["noi_dependency"]["forward_year"] == 3
    (capacity,) = event["sizing"]["capacities"]
    assert capacity["kind"] == "min_dscr" and fx.rf.close(capacity["capacity"], 8_000_000)
    assert event["sizing"]["binding"] == ["min_dscr"]
    (payoff,) = event["payoffs"]
    assert payoff["payoff_authority"] == "acquisition_debt_balance_service" and fx.rf.close(payoff["payoff"], 5_520_000)
    assert event["bridge"]["direction"] == "distribution" and fx.rf.close(event["bridge"]["net_event_cash"], 2_480_000)
    assert event["funding"]["first_service_month"] == 25

    equity = body["result"]["common_equity"]
    events = equity["event_cash_flows"]
    assert fx.rf.close(events[2], 2_480_000) and [value for index, value in enumerate(events) if index != 2] == [0.0] * 5
    assert all(
        fx.rf.close(total, recurring + event_cash)
        for total, recurring, event_cash in zip(equity["cash_flows"], equity["recurring_cash_flows"], events, strict=True)
    )

    primary = body["primary_return"]
    assert primary == {
        "primary_equity_namespace": "common_equity_after_capital_structure",
        "primary_investor_namespace": None,
        "reference_namespace": "acquisition_financing_reference",
        "reference_excludes_capital_events": True,
        "status": "available",
        "unavailable_reason": None,
        "unavailable_message": None,
        "capital_event_ids": [fx.EVENT_ID],
        "executed_event_ids": [fx.EVENT_ID],
    }
    assert body["capital_structure"]["capital_events"][0]["event_id"] == fx.EVENT_ID


def test_an_unavailable_refinance_reports_null_never_zero_and_is_the_primary_answer(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id = _put(client, deal.id, api_module._wire(fx.evented(deal.id, ltv=0.65, dscr=2.0))).json()["investment_id"]
    body = _analysis(client, investment_id)

    (event,) = body["result"]["capital_events"]
    assert event["status"] == "unavailable" and event["unavailable_reason"] == "timepoint_not_found"
    assert event["sizing"]["gross_proceeds"] is None and event["sizing"]["binding"] == []
    assert event["funding"] is None and event["bridge"] is None and event["payoffs"] is None
    ltv, dscr = event["sizing"]["capacities"]
    assert ltv["capacity"] is None and ltv["status"] == "unavailable"
    assert fx.rf.close(dscr["capacity"], 8_000_000)  # the other dependency is still reported

    equity = body["result"]["common_equity"]
    for field in ("cash_flows", "recurring_cash_flows", "event_cash_flows", "irr", "equity_multiple", "total_profit"):
        assert equity[field] is None, field
    assert equity["unavailable_reason"] == "refinance_unavailable"
    (unexecuted,) = body["result"]["unexecuted_positions"]
    assert unexecuted["position_id"] == fx.REPLACEMENT_ID

    primary = body["primary_return"]
    assert primary["status"] == "unavailable"
    assert primary["unavailable_reason"] == "refinance_unavailable"
    assert primary["primary_equity_namespace"] == "common_equity_after_capital_structure"
    assert primary["executed_event_ids"] == []


def test_partner_returns_are_the_primary_investor_namespace_where_a_partnership_exists(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id = _put(client, deal.id, api_module._wire(fx.evented(deal.id, dscr=2.0))).json()["investment_id"]
    store.set_deal_partnership(deal.id, f1_terms(), db_path=db)

    structured = _analysis(client, investment_id)
    assert structured["primary_return"]["primary_investor_namespace"] == "partner"
    response = client.post(f"/investments/{investment_id}/partnership-variants/base/base/analysis")
    assert response.status_code == 200, response.text
    partnership = response.json()
    assert partnership["primary_return"] == structured["primary_return"]
    assert partnership["result"]["status"] == "complete"


def test_a_no_event_analysis_carries_no_additive_member(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id = _put(client, deal.id, api_module._wire(fx.closing_mezz_only(deal.id))).json()["investment_id"]
    body = _analysis(client, investment_id)
    assert "primary_return" not in body
    assert "capital_events" not in body["result"] and "unexecuted_positions" not in body["result"]
    assert "recurring_cash_flows" not in body["result"]["common_equity"]
    assert "capital_events" not in body["capital_structure"]


def test_the_fingerprint_route_carries_the_evented_structure(client: TestClient, db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id = _put(client, deal.id, api_module._wire(fx.evented(deal.id, dscr=2.0))).json()["investment_id"]
    fingerprint = client.get(f"/investments/{investment_id}/structured-variants/base/base/fingerprint").json()
    assert fingerprint["capital_structure"]["capital_events"][0]["event_id"] == fx.EVENT_ID
    assert fingerprint["structured_source_fingerprint"] == _analysis(client, investment_id)["structured_source_fingerprint"]
