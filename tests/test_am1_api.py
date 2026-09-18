"""Gate AM1 -- the Managed Asset and Monthly Performance routes.

``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`` Section 6. The
nine routes, their refusals, and the one claim that matters most on the wire:
every number in a performance response comes from the deterministic engine.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _am1_fixtures as am  # type: ignore[import-not-found]
import _p7_2_fixtures as fx  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.deals import store


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "am1_api.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(api_module.app)


def _wire_figures(figures) -> dict[str, float]:
    return dataclasses.asdict(figures)


def _deal(db: Path, mode: str = "quick", name: str = "Harbor Point Apartments"):
    deal = fx.create_deal(mode, db, name=name)
    if mode != "lease_level":
        store.update_analysis_snapshot(
            deal.id,
            dataclasses.asdict(fx.analyze_deal(deal)),
            financial_input_fingerprint=fx.deal_fingerprint(deal),
            db_path=db,
        )
    return store.get_deal(deal.id, db_path=db)


def _create_asset(client: TestClient, db: Path, **overrides: Any) -> dict[str, Any]:
    deal = _deal(db)
    body = {
        "source_deal_id": deal.id,
        "name": None,
        "acquisition_date": "2026-10-01",
        "property_type": "Multifamily",
        "market": "Toronto, ON",
    }
    body.update(overrides)
    response = client.post("/managed-assets", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _create_report(client: TestClient, asset_id: str, **overrides: Any) -> Any:
    body = {
        "reporting_month": "2027-03-01",
        "budget": _wire_figures(am.MARCH_BUDGET),
        "actual": _wire_figures(am.MARCH_ACTUAL),
        "commentary": am.MARCH_COMMENTARY,
    }
    body.update(overrides)
    return client.post(f"/managed-assets/{asset_id}/reports", json=body)


# =============================================================================
# Creating and reading a Managed Asset
# =============================================================================


def test_a_managed_asset_is_created_from_a_deal(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    assert asset["name"] == "Harbor Point Apartments"
    assert asset["property_type"] == "Multifamily"
    assert asset["acquisition_date"] == "2026-10-01"
    assert asset["acquisition_fingerprint"]
    assert asset["id"] != asset["source_deal_id"]


def test_an_empty_portfolio_lists_empty(client: TestClient) -> None:
    assert client.get("/managed-assets").json() == []


def test_a_created_asset_is_listed_and_readable(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    assert [item["id"] for item in client.get("/managed-assets").json()] == [asset["id"]]
    assert client.get(f"/managed-assets/{asset['id']}").json() == asset


def test_a_second_asset_for_the_same_deal_is_a_typed_conflict(
    client: TestClient, db: Path
) -> None:
    asset = _create_asset(client, db)
    response = client.post(
        "/managed-assets",
        json={
            "source_deal_id": asset["source_deal_id"],
            "name": None,
            "acquisition_date": "2026-10-01",
            "property_type": None,
            "market": None,
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "managed_asset_exists"
    assert detail["managed_asset_id"] == asset["id"]


def test_an_unknown_deal_is_404(client: TestClient) -> None:
    response = client.post(
        "/managed-assets",
        json={
            "source_deal_id": "nope",
            "name": None,
            "acquisition_date": "2026-10-01",
            "property_type": None,
            "market": None,
        },
    )
    assert response.status_code == 404


def test_a_deal_with_no_current_analysis_is_409(client: TestClient, db: Path) -> None:
    deal = fx.create_deal("quick", db, name="Unanalyzed")
    response = client.post(
        "/managed-assets",
        json={
            "source_deal_id": deal.id,
            "name": None,
            "acquisition_date": "2026-10-01",
            "property_type": None,
            "market": None,
        },
    )
    assert response.status_code == 409


def test_an_unknown_asset_is_404(client: TestClient) -> None:
    assert client.get("/managed-assets/nope").status_code == 404
    assert client.get("/managed-assets/nope/reports").status_code == 404


def test_a_body_missing_a_field_is_refused(client: TestClient, db: Path) -> None:
    """Every field is stated explicitly, including the ones that are null, so
    nothing a request does not say can be filled in from anywhere else."""

    deal = _deal(db)
    response = client.post(
        "/managed-assets", json={"source_deal_id": deal.id, "acquisition_date": "2026-10-01"}
    )
    assert response.status_code == 422


def test_an_invalid_identity_is_a_structured_422(client: TestClient, db: Path) -> None:
    deal = _deal(db)
    response = client.post(
        "/managed-assets",
        json={
            "source_deal_id": deal.id,
            "name": "   ",
            "acquisition_date": "2026-10-01",
            "property_type": None,
            "market": None,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["code"] == "invalid_asset_name"


# =============================================================================
# Monthly reports
# =============================================================================


def test_a_monthly_report_is_created_and_read_back(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    created = _create_report(client, asset["id"])
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["budget"]["rental_revenue"] == 100_000.0
    assert body["actual"]["repairs_and_maintenance"] == 8_000.0
    assert body["commentary"] == am.MARCH_COMMENTARY
    assert body["reporting_month"] == "2027-03-01"

    read = client.get(f"/managed-assets/{asset['id']}/reports/2027-03-01")
    assert read.json() == body


def test_any_day_of_the_month_addresses_the_same_report(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"], reporting_month="2027-03-31")
    for spelling in ("2027-03-01", "2027-03-17", "2027-03-31"):
        response = client.get(f"/managed-assets/{asset['id']}/reports/{spelling}")
        assert response.status_code == 200
        assert response.json()["reporting_month"] == "2027-03-01"


def test_a_second_report_for_one_month_is_a_conflict(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    again = _create_report(client, asset["id"], budget=_wire_figures(am.figures(payroll=1.0)))
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "monthly_report_exists"


def test_a_negative_figure_is_a_structured_422(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    response = _create_report(
        client, asset["id"], budget=_wire_figures(am.figures(payroll=-1.0))
    )
    assert response.status_code == 422
    issue = response.json()["detail"][0]
    assert issue["code"] == "negative_amount"
    assert issue["scope"] == "budget"
    assert issue["field"] == "payroll"


def test_occupancy_above_one_hundred_percent_is_refused(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    response = _create_report(
        client, asset["id"], actual=_wire_figures(am.figures(occupancy=1.5))
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["code"] == "invalid_occupancy"


def test_an_unreported_month_is_404(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    assert client.get(f"/managed-assets/{asset['id']}/reports/2027-07-01").status_code == 404


def test_a_malformed_month_is_refused(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    assert client.get(f"/managed-assets/{asset['id']}/reports/March").status_code == 422


# =============================================================================
# Actuals update and the frozen budget
# =============================================================================


def test_actuals_and_commentary_are_updatable(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    response = client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.figures(utilities=7_500.0)),
            "commentary": "Revised after the utility true-up.",
            "budget": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["actual"]["utilities"] == 7_500.0
    assert response.json()["commentary"] == "Revised after the utility true-up."
    assert response.json()["budget"]["utilities"] == 5_000.0


def test_a_budget_change_is_a_409_naming_every_changed_field(
    client: TestClient, db: Path
) -> None:
    """Not a 422: the submitted budget is well-formed, and a 422 would tell the
    product "fix these numbers", which is exactly the wrong instruction."""

    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    response = client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.MARCH_ACTUAL),
            "commentary": None,
            "budget": _wire_figures(am.figures(payroll=9_000.0, insurance=5_500.0)),
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "budget_immutable"
    assert detail["changed_fields"] == ["insurance", "payroll"]
    assert detail["reporting_month"] == "2027-03-01"


def test_echoing_the_identical_budget_is_accepted(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    response = client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.figures(payroll=6_100.0)),
            "commentary": None,
            "budget": _wire_figures(am.MARCH_BUDGET),
        },
    )
    assert response.status_code == 200
    assert response.json()["actual"]["payroll"] == 6_100.0


@pytest.mark.parametrize(
    "bad",
    [None, "6000", True],
    ids=["null", "string", "bool"],
)
def test_a_malformed_echoed_budget_is_a_422_and_never_a_500(
    client: TestClient, db: Path, bad
) -> None:
    """A bad request, not an internal failure. Before the supplied budget was
    validated, the comparison called ``float(None)`` and the route raised an
    uncaught TypeError."""

    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    response = client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.MARCH_ACTUAL),
            "commentary": None,
            "budget": {**_wire_figures(am.MARCH_BUDGET), "payroll": bad},
        },
    )
    assert response.status_code == 422, response.text
    issue = response.json()["detail"][0]
    assert issue["scope"] == "budget"
    assert issue["field"] == "payroll"


def test_a_malformed_echoed_budget_is_not_reported_as_the_frozen_conflict(
    client: TestClient, db: Path
) -> None:
    """422 says "fix this number"; 409 says "this is not yours to change". A
    malformed echo is the former."""

    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    response = client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.MARCH_ACTUAL),
            "commentary": None,
            "budget": {**_wire_figures(am.MARCH_BUDGET), "payroll": None},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["code"] != "budget_immutable"


def test_a_malformed_echoed_budget_leaves_the_report_untouched(
    client: TestClient, db: Path
) -> None:
    asset = _create_asset(client, db)
    before = _create_report(client, asset["id"]).json()
    client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.figures(utilities=99_000.0)),
            "commentary": "Should not be stored.",
            "budget": {**_wire_figures(am.MARCH_BUDGET), "payroll": None},
        },
    )
    assert client.get(f"/managed-assets/{asset['id']}/reports/2027-03-01").json() == before


def test_a_valid_changed_budget_is_still_the_typed_409(client: TestClient, db: Path) -> None:
    """Validating the echo must not turn an authority refusal into a shape
    one."""

    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    response = client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.MARCH_ACTUAL),
            "commentary": None,
            "budget": _wire_figures(am.figures(payroll=9_000.0)),
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "budget_immutable"
    assert response.json()["detail"]["changed_fields"] == ["payroll"]


def test_a_refused_budget_change_persists_nothing(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    before = _create_report(client, asset["id"]).json()
    client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.figures(utilities=99_000.0)),
            "commentary": None,
            "budget": _wire_figures(am.figures(payroll=9_000.0)),
        },
    )
    after = client.get(f"/managed-assets/{asset['id']}/reports/2027-03-01").json()
    assert after["budget"] == before["budget"]
    assert after["actual"] == before["actual"]


# =============================================================================
# Performance
# =============================================================================


def test_the_performance_route_reproduces_the_authorized_demo_result(
    client: TestClient, db: Path
) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    response = client.get(f"/managed-assets/{asset['id']}/performance/2027-03-01")
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    monthly = result["monthly"]

    assert monthly["budget"]["total_revenue"] == 105_000.0
    assert monthly["actual"]["total_revenue"] == 102_500.0
    assert monthly["budget"]["total_operating_expenses"] == 38_000.0
    assert monthly["actual"]["total_operating_expenses"] == 41_000.0
    assert monthly["budget"]["net_operating_income"] == 67_000.0
    assert monthly["actual"]["net_operating_income"] == 61_500.0
    assert monthly["budget"]["net_cash_flow"] == 24_500.0
    assert monthly["actual"]["net_cash_flow"] == 19_000.0

    lines = {line["line"]: line for line in monthly["lines"]}
    assert lines["net_operating_income"]["variance"] == -5_500.0
    assert lines["net_operating_income"]["variance_pct"] == pytest.approx(-0.0820895, abs=1e-6)
    assert lines["net_operating_income"]["assessment"] == "unfavorable"
    assert lines["occupancy"]["variance_points"] == pytest.approx(-2.5, abs=1e-9)
    assert lines["capital_expenditures"]["assessment"] == "neutral"
    assert lines["debt_service"]["assessment"] == "neutral"

    assert result["commentary"] == am.MARCH_COMMENTARY
    assert response.json()["reported_months"] == ["2027-03-01"]


def test_the_response_carries_the_assets_provenance(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    body = client.get(f"/managed-assets/{asset['id']}/performance/2027-03-01").json()
    assert body["managed_asset"]["acquisition_fingerprint"] == asset["acquisition_fingerprint"]
    assert body["managed_asset"]["source_deal_id"] == asset["source_deal_id"]


def test_attention_items_are_words_not_only_colour(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    body = client.get(f"/managed-assets/{asset['id']}/performance/2027-03-01").json()
    messages = [item["message"] for item in body["result"]["monthly"]["attention"]]
    assert "Occupancy is 2.5 pts below plan" in messages
    assert "Repairs and Maintenance is $2,000 over budget" in messages
    assert all(item["assessment"] == "unfavorable" for item in body["result"]["monthly"]["attention"])


def test_year_to_date_sums_reported_months_and_omits_occupancy(
    client: TestClient, db: Path
) -> None:
    asset = _create_asset(client, db)
    for month in ("2027-01-01", "2027-02-01", "2027-03-01"):
        _create_report(client, asset["id"], reporting_month=month)
    body = client.get(f"/managed-assets/{asset['id']}/performance/2027-03-01").json()
    result = body["result"]
    assert result["year_to_date_months"] == 3
    assert result["year_to_date"]["budget"]["total_revenue"] == 3 * 105_000.0
    assert all(line["line"] != "occupancy" for line in result["year_to_date"]["lines"])
    assert [point["reporting_month"] for point in result["noi_trend"]] == [
        "2027-01-01",
        "2027-02-01",
        "2027-03-01",
    ]


def test_zero_revenue_reports_an_unavailable_margin_on_the_wire(
    client: TestClient, db: Path
) -> None:
    """`null`, never 0 and never an infinity that would reach presentation as a
    number."""

    asset = _create_asset(client, db)
    _create_report(
        client,
        asset["id"],
        budget=_wire_figures(am.zero_figures()),
        actual=_wire_figures(am.zero_figures()),
    )
    body = client.get(f"/managed-assets/{asset['id']}/performance/2027-03-01").json()
    assert body["result"]["monthly"]["budget"]["noi_margin"] is None
    lines = {line["line"]: line for line in body["result"]["monthly"]["lines"]}
    assert lines["rental_revenue"]["variance_pct"] is None


def test_performance_for_an_unreported_month_is_404(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    assert client.get(f"/managed-assets/{asset['id']}/performance/2027-07-01").status_code == 404


def test_performance_for_an_unknown_asset_is_404(client: TestClient) -> None:
    assert client.get("/managed-assets/nope/performance/2027-03-01").status_code == 404


# =============================================================================
# AM1 changes no acquisition surface
# =============================================================================


def test_monthly_reporting_cannot_mutate_the_source_deal(client: TestClient, db: Path) -> None:
    asset = _create_asset(client, db)
    before = client.get(f"/deals/{asset['source_deal_id']}").json()
    _create_report(client, asset["id"])
    client.put(
        f"/managed-assets/{asset['id']}/reports/2027-03-01",
        json={
            "actual": _wire_figures(am.figures(utilities=9_000.0)),
            "commentary": "Updated.",
            "budget": None,
        },
    )
    assert client.get(f"/deals/{asset['source_deal_id']}").json() == before


def test_deleting_an_asset_removes_its_reports_but_not_its_source_deal(
    client: TestClient, db: Path
) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    source_before = client.get(f"/deals/{asset['source_deal_id']}").json()

    response = client.delete(f"/managed-assets/{asset['id']}")

    assert response.status_code == 204
    assert client.get(f"/managed-assets/{asset['id']}").status_code == 404
    assert client.get(f"/managed-assets/{asset['id']}/reports").status_code == 404
    assert client.get(f"/deals/{asset['source_deal_id']}").json() == source_before
    assert client.get("/managed-assets").json() == []


def test_deleting_an_unknown_asset_is_404(client: TestClient) -> None:
    assert client.delete("/managed-assets/nope").status_code == 404


def test_there_is_no_independent_delete_route_for_a_report(
    client: TestClient, db: Path
) -> None:
    asset = _create_asset(client, db)
    _create_report(client, asset["id"])
    assert client.delete(f"/managed-assets/{asset['id']}/reports/2027-03-01").status_code == 405
