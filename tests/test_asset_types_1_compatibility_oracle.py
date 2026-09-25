"""Asset Types 1 -- the compatibility oracle against a real schema-v13 database.

``docs/architecture/ASSET_TYPES_1_CLASSIFICATION.md`` Section 7. Asset Types 1
adds two classification tables at schema v14 and changes no existing table, so:

- the v13 -> v14 migration adds exactly two empty tables, alters none, rewrites
  no row, and is idempotent;
- every response the v13 tree recorded -- Deals in all three operating modes, the
  visible Investment, both Managed Assets, a monthly report, its performance,
  ``/analyze`` and ``/deals/fingerprint`` in two modes, and a recorded refusal --
  is answered identically, except that each Deal and Managed Asset now also
  states its classification, as ``null`` ("Not specified");
- replaying writes nothing, and no read classifies anything;
- the legacy hand-typed ``property_type`` is preserved and exposed verbatim,
  never mapped onto a controlled type.

The database is written by ``main`` at ``2e6ca8e`` itself (exported with ``git
archive``, which reads objects and never touches the index; no stash and no
second checkout) through ``tests/_asset_types_1_v13_baseline_builder.py``.
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
    CLASSIFICATION_KEYS,
    without_unstated_classification,
)
from anchor import api as api_module
from anchor.deals import store

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_asset_types_1_v13_baseline_builder.py"

#: ``main`` when Asset Types 1 began: PR #42 merged, schema v13, no classification.
_BASELINE_COMMIT = "2e6ca8e"


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("asset_types_1_v13_baseline")
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


def _connect(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(db)


def _version(db: Path) -> int:
    connection = _connect(db)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _schema(db: Path) -> dict[str, tuple[str, str, str | None]]:
    """Every schema object -- tables and their automatic key indexes -- as
    ``name -> (type, owning table, sql)``."""

    connection = _connect(db)
    try:
        return {
            name: (kind, table, sql)
            for kind, name, table, sql in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            )
        }
    finally:
        connection.close()


def _every_row(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    connection = _connect(db)
    try:
        tables = sorted(
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not name.startswith("sqlite_")
        )
        return {table: list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid")) for table in tables}
    finally:
        connection.close()


# =============================================================================
# The baseline
# =============================================================================


def test_the_baseline_is_a_real_v13_tree_with_no_classification(
    legacy: tuple[Path, dict[str, Any]],
) -> None:
    db, manifest = legacy
    assert manifest["user_version"] == 13 and _version(db) == 13
    assert not set(ASSET_TYPES_1_TABLES) & set(manifest["tables"])
    paths = [exchange["path"] for exchange in manifest["exchanges"]]
    for key in ("quick_deal_id", "detailed_deal_id", "lease_level_deal_id"):
        assert f"/deals/{manifest[key]}" in paths
    assert f"/managed-assets/{manifest['legacy_asset_id']}" in paths
    # The legacy asset really carries a hand-typed property type.
    legacy_asset = next(
        exchange["json"]
        for exchange in manifest["exchanges"]
        if exchange["path"] == f"/managed-assets/{manifest['legacy_asset_id']}"
    )
    assert legacy_asset["property_type"] == "Multifamily"
    assert not set(CLASSIFICATION_KEYS) & set(legacy_asset)


# =============================================================================
# The v13 -> v14 migration
# =============================================================================


def test_the_migration_adds_exactly_two_empty_tables_and_rewrites_nothing(
    legacy: tuple[Path, dict[str, Any]],
) -> None:
    db, _ = legacy
    before_schema, before_rows = _schema(db), _every_row(db)

    store.list_deals(db_path=db)  # any store call migrates
    migrated_schema, migrated_rows = _schema(db), _every_row(db)

    # P7.10 Stage 2 (schema 15) adds its sixteen valuation and Investment Memo
    # tables in the same additive way; they are named so the table set stays an
    # exact comparison rather than loosening to a subset check.
    # Refinance V1 Stage 2 (schema 17) adds its six capital-event tables the same way.
    expected_tables = (
        set(ASSET_TYPES_1_TABLES) | set(P7_10_TABLES) | set(P7_10_STAGE_4_TABLES) | set(REFINANCE_V1_STAGE_2_TABLES)
    )
    assert _version(db) == 17
    added = {name: migrated_schema[name] for name in set(migrated_schema) - set(before_schema)}
    assert {name for name, (kind, _, _) in added.items() if kind == "table"} == expected_tables
    # Every other new object is one of those tables' own key indexes.
    assert {table for _, table, _ in added.values()} == expected_tables
    assert {kind for kind, _, _ in added.values()} <= {"table", "index"}
    # No table, index or column that existed was altered -- in particular the
    # three Deal tables and ``managed_assets`` keep their DDL byte for byte.
    assert {name: migrated_schema[name] for name in before_schema} == before_schema
    for table in ("deals", "detailed_deals", "lease_level_deals", "managed_assets"):
        assert migrated_schema[table] == before_schema[table]
    # No row was rewritten, and the migration classified nothing.
    assert {table: migrated_rows[table] for table in before_rows} == before_rows
    assert {table: migrated_rows[table] for table in ASSET_TYPES_1_TABLES} == dict.fromkeys(
        ASSET_TYPES_1_TABLES, []
    )


def test_the_migration_is_idempotent(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    store.list_deals(db_path=db)
    settled = (_version(db), _schema(db), _every_row(db))

    for _ in range(3):
        store.list_deals(db_path=db)
        store.list_managed_assets(db_path=db)
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
    connection = _connect(db)
    try:
        for table in ASSET_TYPES_1_TABLES:
            columns = {
                name: (declared, not_null)
                for _, name, declared, not_null, _, _ in connection.execute(f"PRAGMA table_info({table})")
            }
            assert set(columns) - {"deal_id", "managed_asset_id"} == {"asset_type", "asset_subtype"}, table
            assert all(declared == "TEXT" for declared, _ in columns.values()), table
            # A row exists only for a chosen type: "Not specified" is no row,
            # never a row of NULLs.
            assert columns["asset_type"][1] == 1 and columns["asset_subtype"][1] == 0
    finally:
        connection.close()


# =============================================================================
# Every v13 response, answered identically
# =============================================================================

#: The calculation routes that write nothing: pure functions of their body.
_PURE_POSTS = ("/analyze", "/deals/fingerprint")


def _replayable(exchange: dict[str, Any]) -> bool:
    return exchange["method"] == "GET" or exchange["path"] in _PURE_POSTS


def test_every_recorded_read_replays_identically(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    _, manifest = legacy
    replayed = [exchange for exchange in manifest["exchanges"] if _replayable(exchange)]
    assert len(replayed) >= 15
    assert any(exchange["status"] >= 400 for exchange in replayed)

    for exchange in replayed:
        response = client.request(exchange["method"], exchange["path"], json=exchange["body"])
        assert response.status_code == exchange["status"], exchange["path"]
        assert (
            without_unstated_classification(response.json(), exchange["json"]) == exchange["json"]
        ), exchange["path"]


def test_every_legacy_deal_and_asset_reads_not_specified(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """The normalizer above only sets aside null classification keys; this
    states it positively. Every legacy record carries both keys, and both are
    null -- in the library, on each Deal, and on each Managed Asset."""

    _, manifest = legacy
    listed = client.get("/deals").json()
    assert len(listed) == 3
    for deal in listed:
        assert (deal["asset_type"], deal["asset_subtype"]) == (None, None)
    for key in ("quick_deal_id", "detailed_deal_id", "lease_level_deal_id"):
        deal = client.get(f"/deals/{manifest[key]}").json()
        assert (deal["asset_type"], deal["asset_subtype"]) == (None, None)
    for asset in client.get("/managed-assets").json():
        assert (asset["asset_type"], asset["asset_subtype"]) == (None, None)


def test_the_legacy_property_type_is_preserved_and_never_mapped(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """"Multifamily" typed by hand before Asset Types 1 is exactly the text a
    naive rule would map onto ``multifamily``. It is not: the asset stays "Not
    specified", and the analyst's text is exposed verbatim beside it."""

    _, manifest = legacy
    asset = client.get(f"/managed-assets/{manifest['legacy_asset_id']}").json()
    assert asset["property_type"] == "Multifamily"
    assert asset["asset_type"] is None and asset["asset_subtype"] is None
    plain = client.get(f"/managed-assets/{manifest['plain_asset_id']}").json()
    assert plain["property_type"] is None and plain["asset_type"] is None


def test_replaying_every_read_writes_nothing_and_classifies_nothing(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    store.list_deals(db_path=db)  # migrate first, so the comparison is v14 to v14
    before = _every_row(db)

    for exchange in manifest["exchanges"]:
        if _replayable(exchange):
            client.request(exchange["method"], exchange["path"], json=exchange["body"])

    assert _every_row(db) == before
    for table in ASSET_TYPES_1_TABLES:
        assert before[table] == []


# =============================================================================
# A legacy record, classified afterwards by the analyst
# =============================================================================


def test_a_legacy_deal_can_be_classified_and_keeps_its_analysis_and_its_asset(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """The next user-authored edit classifies a legacy Deal. Its saved analysis
    and AI state survive (classification is in no fingerprint), and the Managed
    Asset already created from it keeps its own snapshot: still "Not
    specified", still the legacy "Multifamily" text."""

    db, manifest = legacy
    deal = client.get(f"/deals/{manifest['quick_deal_id']}").json()
    assert deal["analysis_snapshot"] is not None
    before_rows = _every_row(db)

    response = client.put(
        f"/deals/{deal['id']}",
        json={
            "name": deal["name"],
            "operating_mode": "quick",
            "inputs": deal["inputs"],
            "business_plan": deal["business_plan"],
            "deal_context": deal["deal_context"],
            "asset_type": "multifamily",
            "asset_subtype": "Garden apartments",
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert (updated["asset_type"], updated["asset_subtype"]) == ("multifamily", "Garden apartments")
    assert updated["analysis_snapshot"] == deal["analysis_snapshot"]
    assert updated["inputs"] == deal["inputs"]
    assert updated["business_plan"] == deal["business_plan"]

    after_rows = _every_row(db)
    assert after_rows["deal_asset_classifications"] == [
        (deal["id"], "multifamily", "Garden apartments")
    ]
    # Only the classification row and the Deal's own ``updated_at`` moved.
    for table, table_rows in before_rows.items():
        if table in ("deal_asset_classifications", "deals"):
            continue
        assert after_rows[table] == table_rows, table

    asset = client.get(f"/managed-assets/{manifest['legacy_asset_id']}").json()
    assert (asset["asset_type"], asset["asset_subtype"], asset["property_type"]) == (
        None,
        None,
        "Multifamily",
    )
