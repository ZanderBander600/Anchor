"""Second AM1 QA pass -- updating a monthly report's commentary, and nothing else.

The focused "Update Commentary" editor first saved through the actual-results
route, resending the actual figures the browser had loaded. That wrote every
``actual_*`` column: had another tab or user saved newer actuals after this
browser loaded the report, a commentary save would have silently put the stale
figures back. The commentary-only operation closes that by construction -- its
one SQL statement names only ``commentary`` and ``updated_at`` -- and these tests
prove it at the store, on the wire, under a concurrent actuals save, and in the
source itself.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _am1_fixtures as am  # type: ignore[import-not-found]
import _p7_2_fixtures as fx  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.asset_management.contracts import (
    AssetReportValidationError,
    ManagedAssetNotFoundError,
    MonthlyReportNotFoundError,
)
from anchor.deals import store

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_STORE = _PROJECT_ROOT / "src/anchor/deals/store.py"
_API = _PROJECT_ROOT / "src/anchor/api.py"

#: Figures another session saves after this browser loaded the report.
NEWER_ACTUAL = am.figures(rental_revenue=97_250.0, other_income=7_125.0, utilities=5_400.0)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "am1_commentary.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(api_module.app)


def _asset(db: Path) -> str:
    deal = fx.create_deal("quick", db, name="Harbor Point Apartments")
    store.update_analysis_snapshot(
        deal.id,
        dataclasses.asdict(fx.analyze_deal(deal)),
        financial_input_fingerprint=fx.deal_fingerprint(deal),
        db_path=db,
    )
    asset = store.create_managed_asset(
        source_deal_id=deal.id,
        name=None,
        acquisition_date=am.MARCH,
        property_type="Multifamily",
        market="Toronto, ON",
        db_path=db,
    )
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        commentary=am.MARCH_COMMENTARY,
        db_path=db,
    )
    return asset.id


def _row(db: Path, asset_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT * FROM monthly_asset_reports WHERE managed_asset_id = ? AND reporting_month = ?",
            (asset_id, am.MARCH.isoformat()),
        ).fetchone()
        return dict(row)
    finally:
        connection.close()


def _figure_columns(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key.startswith(("actual_", "budget_"))}


# =============================================================================
# 1. The store changes only commentary and updated_at
# =============================================================================


def test_the_store_changes_only_commentary_and_updated_at(db: Path) -> None:
    asset_id = _asset(db)
    before = _row(db, asset_id)

    report = store.update_monthly_report_commentary(
        managed_asset_id=asset_id,
        reporting_month=am.MARCH,
        commentary="Leasing recovered in the second half of the month.",
        db_path=db,
    )

    after = _row(db, asset_id)
    changed = {key for key in before if before[key] != after[key]}
    assert changed <= {"commentary", "updated_at"}
    assert "commentary" in changed
    assert after["commentary"] == "Leasing recovered in the second half of the month."
    # Every actual and budget column is value- and type-identical.
    assert _figure_columns(after) == _figure_columns(before)
    for key, value in _figure_columns(before).items():
        assert type(after[key]) is type(value), key
    assert report.commentary == after["commentary"]
    assert report.actual == am.MARCH_ACTUAL
    assert report.budget == am.MARCH_BUDGET


def test_none_clears_the_commentary_and_touches_no_figure(db: Path) -> None:
    asset_id = _asset(db)
    before = _row(db, asset_id)
    store.update_monthly_report_commentary(
        managed_asset_id=asset_id, reporting_month=am.MARCH, commentary=None, db_path=db
    )
    after = _row(db, asset_id)
    assert after["commentary"] is None
    assert _figure_columns(after) == _figure_columns(before)


def test_any_day_of_the_month_addresses_the_same_report(db: Path) -> None:
    asset_id = _asset(db)
    store.update_monthly_report_commentary(
        managed_asset_id=asset_id,
        reporting_month=am.MARCH.replace(day=17),
        commentary="Normalized to March.",
        db_path=db,
    )
    assert _row(db, asset_id)["commentary"] == "Normalized to March."


@pytest.mark.parametrize("commentary", ["   ", "", "x" * 20_000])
def test_invalid_commentary_is_refused_and_writes_nothing(db: Path, commentary: str) -> None:
    asset_id = _asset(db)
    before = _row(db, asset_id)
    with pytest.raises(AssetReportValidationError) as raised:
        store.update_monthly_report_commentary(
            managed_asset_id=asset_id, reporting_month=am.MARCH, commentary=commentary, db_path=db
        )
    assert [issue.field for issue in raised.value.issues] == ["commentary"]
    assert _row(db, asset_id) == before


def test_a_missing_asset_or_report_is_the_typed_not_found(db: Path) -> None:
    asset_id = _asset(db)
    with pytest.raises(ManagedAssetNotFoundError):
        store.update_monthly_report_commentary(
            managed_asset_id="no-such-asset", reporting_month=am.MARCH, commentary="x", db_path=db
        )
    with pytest.raises(MonthlyReportNotFoundError):
        store.update_monthly_report_commentary(
            managed_asset_id=asset_id,
            reporting_month=am.MARCH.replace(month=4),
            commentary="x",
            db_path=db,
        )


# =============================================================================
# 2. A concurrent actual-results save survives a later commentary save
# =============================================================================


def test_a_concurrent_actuals_save_survives_a_later_commentary_save(db: Path) -> None:
    asset_id = _asset(db)
    # This browser loads the report...
    loaded = store.get_monthly_report(asset_id, am.MARCH, db_path=db)
    assert loaded.actual == am.MARCH_ACTUAL

    # ...another session then saves newer actual results...
    store.update_monthly_report_actuals(
        managed_asset_id=asset_id,
        reporting_month=am.MARCH,
        actual=NEWER_ACTUAL,
        commentary=loaded.commentary,
        db_path=db,
    )
    newer = _row(db, asset_id)

    # ...and this browser saves only its commentary.
    store.update_monthly_report_commentary(
        managed_asset_id=asset_id,
        reporting_month=am.MARCH,
        commentary="Written against the report as first loaded.",
        db_path=db,
    )

    final = store.get_monthly_report(asset_id, am.MARCH, db_path=db)
    assert final.actual == NEWER_ACTUAL
    assert final.actual != loaded.actual
    assert _figure_columns(_row(db, asset_id)) == _figure_columns(newer)
    assert final.commentary == "Written against the report as first loaded."


def test_the_previous_commentary_save_would_have_reverted_them(db: Path) -> None:
    """The defect this operation removes, reproduced: saving commentary through
    the actual-results write with the figures the browser loaded puts the stale
    figures back over a concurrent save. The test above passes because the
    commentary write is different, not because the race is imaginary."""

    asset_id = _asset(db)
    loaded = store.get_monthly_report(asset_id, am.MARCH, db_path=db)
    store.update_monthly_report_actuals(
        managed_asset_id=asset_id,
        reporting_month=am.MARCH,
        actual=NEWER_ACTUAL,
        commentary=loaded.commentary,
        db_path=db,
    )
    store.update_monthly_report_actuals(
        managed_asset_id=asset_id,
        reporting_month=am.MARCH,
        actual=loaded.actual,
        commentary="Written against the report as first loaded.",
        db_path=db,
    )
    assert store.get_monthly_report(asset_id, am.MARCH, db_path=db).actual == am.MARCH_ACTUAL


def test_the_same_race_over_the_wire(client: TestClient, db: Path) -> None:
    asset_id = _asset(db)
    loaded = client.get(f"/managed-assets/{asset_id}/reports/2027-03-01").json()

    newer = client.put(
        f"/managed-assets/{asset_id}/reports/2027-03-01",
        json={
            "actual": dataclasses.asdict(NEWER_ACTUAL),
            "commentary": loaded["commentary"],
            "budget": None,
        },
    )
    assert newer.status_code == 200, newer.text

    saved = client.put(
        f"/managed-assets/{asset_id}/reports/2027-03-01/commentary",
        json={"commentary": "Written against the report as first loaded."},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["actual"] == dataclasses.asdict(NEWER_ACTUAL)
    assert saved.json()["actual"] != loaded["actual"]
    assert saved.json()["commentary"] == "Written against the report as first loaded."


# =============================================================================
# 3. The route: exact body, typed refusals, the established wire format
# =============================================================================


def test_the_route_returns_the_updated_report_in_the_wire_format(
    client: TestClient, db: Path
) -> None:
    asset_id = _asset(db)
    read = client.get(f"/managed-assets/{asset_id}/reports/2027-03-01").json()
    response = client.put(
        f"/managed-assets/{asset_id}/reports/2027-03-01/commentary",
        json={"commentary": "Two renewals closed."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The same shape the report read returns, with only the note and its
    # timestamp different.
    assert set(body) == set(read)
    assert body["commentary"] == "Two renewals closed."
    assert {key: body[key] for key in body if key not in ("commentary", "updated_at")} == {
        key: read[key] for key in read if key not in ("commentary", "updated_at")
    }


def test_null_is_none_written(client: TestClient, db: Path) -> None:
    asset_id = _asset(db)
    response = client.put(
        f"/managed-assets/{asset_id}/reports/2027-03-01/commentary", json={"commentary": None}
    )
    assert response.status_code == 200
    assert response.json()["commentary"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"commentary": "x", "actual": {}},
        {"commentary": "x", "budget": None},
        {"commentary": "x", "actual": None, "budget": None},
        {},
    ],
)
def test_the_body_states_exactly_commentary(client: TestClient, db: Path, body: dict) -> None:
    asset_id = _asset(db)
    before = _row(db, asset_id)
    response = client.put(f"/managed-assets/{asset_id}/reports/2027-03-01/commentary", json=body)
    assert response.status_code == 422
    assert _row(db, asset_id) == before


def test_non_text_commentary_is_refused(client: TestClient, db: Path) -> None:
    asset_id = _asset(db)
    response = client.put(
        f"/managed-assets/{asset_id}/reports/2027-03-01/commentary", json={"commentary": 42}
    )
    assert response.status_code == 422


def test_blank_commentary_is_the_established_structured_422(client: TestClient, db: Path) -> None:
    asset_id = _asset(db)
    before = _row(db, asset_id)
    response = client.put(
        f"/managed-assets/{asset_id}/reports/2027-03-01/commentary", json={"commentary": "   "}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    # The same structured issue list the create and actuals routes return.
    assert isinstance(detail, list) and len(detail) == 1
    assert set(detail[0]) == {"code", "message", "scope", "field"}
    assert detail[0]["field"] == "commentary"
    assert detail[0]["scope"] is None
    assert detail[0]["code"] == "invalid_commentary"
    # The actual-results route answers the same blank note identically.
    actuals = client.put(
        f"/managed-assets/{asset_id}/reports/2027-03-01",
        json={"actual": dataclasses.asdict(am.MARCH_ACTUAL), "commentary": "   ", "budget": None},
    )
    assert actuals.status_code == 422
    assert actuals.json()["detail"] == detail
    assert _row(db, asset_id) == before


def test_a_missing_asset_report_or_bad_month_is_refused(client: TestClient, db: Path) -> None:
    asset_id = _asset(db)
    body = {"commentary": "x"}
    assert (
        client.put("/managed-assets/nope/reports/2027-03-01/commentary", json=body).status_code
        == 404
    )
    assert (
        client.put(f"/managed-assets/{asset_id}/reports/2027-04-01/commentary", json=body).status_code
        == 404
    )
    assert (
        client.put(f"/managed-assets/{asset_id}/reports/not-a-month/commentary", json=body).status_code
        == 422
    )


# =============================================================================
# 4. The source: two distinct operations
# =============================================================================


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_bytes().decode("utf-8"))
    return next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _joined_sql(node: ast.AST) -> list[str]:
    """Each SQL statement as written, adjacent string literals joined."""

    statements: list[str] = []
    for call in ast.walk(node):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "execute"
            and call.args
        ):
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                statements.append(first.value)
            else:
                statements.append(ast.unparse(first))
    return statements


def test_the_commentary_write_assigns_only_commentary_and_updated_at() -> None:
    update = _function(_STORE, "update_monthly_report_commentary")
    statements = _joined_sql(update)
    writes = [sql for sql in statements if re.search(r"\b(UPDATE|INSERT|DELETE)\b", sql, re.I)]
    assert writes == [
        "UPDATE monthly_asset_reports SET commentary = ?, updated_at = ? "
        "WHERE managed_asset_id = ? AND reporting_month = ?"
    ]
    # Literal SQL: no assignment list built at run time that could grow.
    assert not any(isinstance(node, ast.JoinedStr) for node in ast.walk(update))
    set_clause = writes[0].split(" SET ", 1)[1].split(" WHERE ", 1)[0]
    assigned = {part.split("=")[0].strip() for part in set_clause.split(",")}
    assert assigned == {"commentary", "updated_at"}
    # No statement it executes -- read or write -- names a figure column. (The
    # docstring explains what is avoided; the claim is about the SQL.)
    assert len(statements) == 3
    for sql in statements:
        assert "actual_" not in sql and "budget_" not in sql, sql
    source = ast.unparse(update)
    assert "_figure_values" not in source
    assert "require_valid_monthly_report" not in source
    assert "validate_commentary" in source


def test_the_actuals_write_is_unchanged_and_still_the_only_one_moving_actuals() -> None:
    actuals = ast.unparse(_function(_STORE, "update_monthly_report_actuals"))
    assert "_figure_values(actual, 'actual')" in actuals
    store_source = _STORE.read_bytes().decode("utf-8")
    assert store_source.count('_figure_values(actual, "actual")') == 2  # create + actuals update


def test_the_two_routes_call_two_different_operations() -> None:
    commentary_route = ast.unparse(_function(_API, "update_monthly_asset_report_commentary"))
    actuals_route = ast.unparse(_function(_API, "update_monthly_asset_report_actuals"))
    assert "update_monthly_report_commentary" in commentary_route
    assert "update_monthly_report_actuals" not in commentary_route
    assert "_am1_figures" not in commentary_route
    assert "_COMMENTARY_FIELDS" in commentary_route
    assert "update_monthly_report_actuals" in actuals_route
    assert "update_monthly_report_commentary" not in actuals_route
    api_source = _API.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert '_COMMENTARY_FIELDS = ("commentary",)' in api_source
    assert '_ACTUALS_FIELDS = ("actual", "commentary", "budget")' in api_source
