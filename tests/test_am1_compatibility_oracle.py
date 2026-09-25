"""Gate AM1 -- the compatibility oracle against a real schema-v12 database.

``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`` Section 5.5. AM1
adds two Asset Management tables at schema v13 and changes no existing contract,
so:

- the v12 -> v13 migration adds exactly two empty tables, alters none, rewrites
  no row, and is idempotent;
- every response the v12 tree recorded -- Deals in all three operating modes,
  the visible Investment, its Scenario, Strategy, Capital Structure and
  Partnership, the target catalogs, ``/analyze`` and ``/deals/fingerprint``, and
  the recorded refusals -- is answered byte for byte identically;
- replaying writes nothing, and no read materializes a Managed Asset.

The database is written by ``main`` at ``63c2ac0`` itself (exported with ``git
archive``, which reads objects and never touches the index; no stash and no
second checkout) through ``tests/_am1_v12_baseline_builder.py``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from _p7_2_fixtures import (  # type: ignore[import-not-found]
    ASSET_TYPES_1_TABLES,
    P7_10_STAGE_4_TABLES,
    REFINANCE_V1_STAGE_2_TABLES,
    P7_10_TABLES,
    without_unstated_classification,
)
from anchor import api as api_module
from anchor.deals import store

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_am1_v12_baseline_builder.py"

#: ``main`` when AM1 began: P7.9 Stage 3 merged, schema v12, no Asset Management.
_BASELINE_COMMIT = "63c2ac0"

#: The two tables schema v13 adds.
AM1_TABLES = ("managed_assets", "monthly_asset_reports")


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("am1_v12_baseline")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True,
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    db, manifest = scratch / "baseline.db", scratch / "baseline.json"
    completed = subprocess.run(
        [sys.executable, str(_BUILDER), str(scratch / "baseline"), str(db), str(manifest)],
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return db, json.loads(manifest.read_text(encoding="utf-8"))


@pytest.fixture
def legacy(baseline: tuple[Path, dict[str, Any]], tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    source, manifest = baseline
    path = tmp_path / "legacy.db"
    shutil.copyfile(source, path)
    return path, manifest


@pytest.fixture
def client(legacy: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(legacy[0]))
    return TestClient(api_module.app)


def _version(db: Path) -> int:
    connection = sqlite3.connect(db)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _table_names(db: Path) -> set[str]:
    connection = sqlite3.connect(db)
    try:
        return {
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not name.startswith("sqlite_")
        }
    finally:
        connection.close()


def _schema(db: Path) -> dict[str, tuple[str, str, str | None]]:
    """Every schema object -- tables and their automatic key indexes -- as
    ``name -> (type, owning table, sql)``."""

    connection = sqlite3.connect(db)
    try:
        return {
            name: (kind, table, sql)
            for kind, name, table, sql in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            )
        }
    finally:
        connection.close()


def _rows(db: Path, table: str) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(db)
    try:
        return list(connection.execute(f"SELECT * FROM {table}"))
    finally:
        connection.close()


def _every_row(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {table: _rows(db, table) for table in sorted(_table_names(db))}


# =============================================================================
# The baseline
# =============================================================================


def test_the_baseline_is_a_real_v12_tree_with_no_asset_management(
    legacy: tuple[Path, dict[str, Any]],
) -> None:
    db, manifest = legacy
    assert manifest["user_version"] == 12 and _version(db) == 12
    assert not set(AM1_TABLES) & _table_names(db)
    paths = [exchange["path"] for exchange in manifest["exchanges"]]
    assert "/analyze" in paths and "/deals/fingerprint" in paths
    assert any(path.endswith("/partnership") for path in paths)
    assert any(path.endswith("/capital-structure") for path in paths)
    # Three operating modes, each read back.
    for key in ("quick_deal_id", "detailed_deal_id", "lease_level_deal_id"):
        assert f"/deals/{manifest[key]}" in paths


# =============================================================================
# The v12 -> v13 migration
# =============================================================================


def test_the_migration_adds_exactly_two_empty_tables_and_rewrites_nothing(
    legacy: tuple[Path, dict[str, Any]],
) -> None:
    db, _ = legacy
    before_schema, before_rows = _schema(db), _every_row(db)

    store.list_deals(db_path=db)  # any store call migrates
    migrated_schema, migrated_rows = _schema(db), _every_row(db)

    # Asset Types 1 (schema 14) adds its two classification tables and P7.10
    # Stage 2 (schema 15) its sixteen valuation and Investment Memo tables, both
    # in the same additive way; all are named so the table set stays an exact
    # comparison rather than loosening to a subset check.
    # Refinance V1 Stage 2 (schema 17) adds its six capital-event tables the same way.
    assert _version(db) == 17
    expected_tables = (
        set(AM1_TABLES) | set(ASSET_TYPES_1_TABLES) | set(P7_10_TABLES) | set(P7_10_STAGE_4_TABLES)
        | set(REFINANCE_V1_STAGE_2_TABLES)
    )
    added = {name: migrated_schema[name] for name in set(migrated_schema) - set(before_schema)}
    assert {name for name, (kind, _, _) in added.items() if kind == "table"} == expected_tables
    # Every other new object is one of those tables' own key indexes.
    assert {table for _, table, _ in added.values()} == expected_tables
    assert {kind for kind, _, _ in added.values()} <= {"table", "index"}
    # Nothing that existed was removed or altered.
    assert set(before_schema) <= set(migrated_schema)
    assert {name: migrated_schema[name] for name in before_schema} == before_schema
    assert {table: migrated_rows[table] for table in expected_tables} == dict.fromkeys(expected_tables, [])
    assert {table: migrated_rows[table] for table in before_rows} == before_rows


def test_the_migration_is_idempotent(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    store.list_deals(db_path=db)
    settled = (_version(db), _schema(db), _every_row(db))

    for _ in range(3):
        store.list_deals(db_path=db)
        assert (_version(db), _schema(db), _every_row(db)) == settled

    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    store._migrate(connection)
    connection.commit()
    connection.close()
    assert (_version(db), _schema(db), _every_row(db)) == settled


def test_the_two_new_tables_are_typed_and_hold_no_json_blob(
    legacy: tuple[Path, dict[str, Any]],
) -> None:
    db, _ = legacy
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    try:
        for table in AM1_TABLES:
            columns = list(connection.execute(f"PRAGMA table_info({table})"))
            assert columns, table
            for _, name, declared, _, _, _ in columns:
                assert declared in ("TEXT", "REAL", "INTEGER"), (table, name, declared)
                assert "json" not in name.lower() and "blob" not in name.lower()
    finally:
        connection.close()


def test_every_figure_column_is_real(legacy: tuple[Path, dict[str, Any]]) -> None:
    """Twelve budget and twelve actual columns, each its own typed REAL --
    never one JSON financial blob."""

    db, _ = legacy
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    try:
        declared = {
            name: kind
            for _, name, kind, _, _, _ in connection.execute(
                "PRAGMA table_info(monthly_asset_reports)"
            )
        }
    finally:
        connection.close()
    budget = {name for name in declared if name.startswith("budget_")}
    actual = {name for name in declared if name.startswith("actual_")}
    assert len(budget) == 12 and len(actual) == 12
    assert all(declared[name] == "REAL" for name in budget | actual)


# =============================================================================
# Every v12 response, answered identically
# =============================================================================


#: The two calculation routes that write nothing: pure functions of their body,
#: so replaying them is meaningful in exactly the way replaying a POST that
#: creates a row is not. Re-posting ``/investments`` would conflict with the
#: Investment it already created, which would say nothing about compatibility.
_PURE_POSTS = ("/analyze", "/deals/fingerprint")


def _replayable(exchange: dict[str, Any]) -> bool:
    return exchange["method"] == "GET" or exchange["path"] in _PURE_POSTS


def test_every_recorded_read_replays_byte_for_byte(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    _, manifest = legacy
    replayed = [exchange for exchange in manifest["exchanges"] if _replayable(exchange)]
    # Guards the predicate itself: if a future edit to the builder stopped
    # recording reads, this test would otherwise pass by checking nothing.
    assert len(replayed) >= 20
    assert any(exchange["path"] in _PURE_POSTS for exchange in replayed)

    for exchange in replayed:
        response = client.request(exchange["method"], exchange["path"], json=exchange["body"])
        assert response.status_code == exchange["status"], exchange["path"]
        # Asset Types 1: a legacy Deal now also states its classification, as
        # null ("Not specified"); only those keys are set aside.
        assert (
            without_unstated_classification(response.json(), exchange["json"]) == exchange["json"]
        ), exchange["path"]


def test_the_recorded_refusals_are_still_refused_the_same_way(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """The v12 tree's error responses are part of its contract too: a Deal that
    belongs to a visible Investment still reports the same 409, with the same
    body, rather than quietly succeeding."""

    _, manifest = legacy
    refusals = [
        exchange
        for exchange in manifest["exchanges"]
        if _replayable(exchange) and exchange["status"] >= 400
    ]
    assert refusals, "the baseline recorded no refusal to compare"
    for exchange in refusals:
        response = client.request(exchange["method"], exchange["path"], json=exchange["body"])
        assert (
            response.status_code,
            without_unstated_classification(response.json(), exchange["json"]),
        ) == (
            exchange["status"],
            exchange["json"],
        ), exchange["path"]


def test_replaying_every_read_writes_nothing_and_materializes_no_asset(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    store.list_deals(db_path=db)  # migrate first, so the comparison is v13 to v13
    before = _every_row(db)

    for exchange in manifest["exchanges"]:
        if exchange["method"] == "GET":
            client.request(exchange["method"], exchange["path"])

    assert _every_row(db) == before
    assert _rows(db, "managed_assets") == []
    assert _rows(db, "monthly_asset_reports") == []


def test_no_legacy_deal_gains_a_managed_asset_by_being_opened(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    for key in ("quick_deal_id", "detailed_deal_id", "lease_level_deal_id"):
        assert client.get(f"/deals/{manifest[key]}").status_code == 200
    assert store.list_managed_assets(db_path=db) == []


def test_the_new_routes_report_an_empty_portfolio_on_a_legacy_database(
    client: TestClient,
) -> None:
    """A v12 database migrated to v13 has no Managed Asset -- and says so,
    rather than failing."""

    response = client.get("/managed-assets")
    assert response.status_code == 200
    assert response.json() == []
