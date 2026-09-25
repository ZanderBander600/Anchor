"""Phase 7 Gate P7.9 Stage 2 -- the compatibility oracle against a real
schema-v11 database.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 17.2 and
``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.3
(P-10, P-11). Stage 2 adds eight Partnership tables at schema v12 and a
Partnership layer downstream of the structured variant, so:

- the v11 -> v12 migration adds exactly eight empty tables, alters none and
  rewrites no row, and is idempotent;
- every response the v11 tree recorded -- Quick, Detailed and Lease-Level Deals,
  the P7.5 one-unit matrix, the P7.6 visible Investment, and every P7.8B
  Capital Structure surface (a Deal opted in through its door, Strategies that
  inherit, replace, explicitly empty or leave funding unresolved, structured
  fingerprints and analyses, Position perspectives and matrices) -- is answered
  byte for byte identically;
- replaying writes nothing, and no read materializes a Partnership;
- with no Partnership anywhere, every variant has no Partnership fingerprint and
  no Partnership result (FP-2), while its Project and structured fingerprints
  are exactly the ones the v11 tree reported.

The database is written by ``main`` at ``1df2760`` itself (exported with
``git archive``, which reads objects and never touches the index; no stash and
no second checkout) through ``tests/_p7_9_v11_baseline_builder.py``.
"""

from __future__ import annotations

import json
import math
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from _p7_2_fixtures import AM1_TABLES, ASSET_TYPES_1_TABLES, P7_9_TABLES, P7_10_STAGE_4_TABLES, P7_10_TABLES, REFINANCE_V1_STAGE_2_TABLES, rows, table_names, without_unstated_classification  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.deals import store

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_p7_9_v11_baseline_builder.py"
#: ``main`` when Stage 2 began: P7.9 Stage 1 accepted and documented, schema v11.
_BASELINE_COMMIT = "1df2760"


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("p7_9_v11_baseline")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True, capture_output=True, cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    db, manifest = scratch / "baseline.db", scratch / "baseline.json"
    completed = subprocess.run(
        [sys.executable, str(_BUILDER), str(scratch / "baseline"), str(db), str(manifest)],
        capture_output=True, cwd=_PROJECT_ROOT,
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


def _every_row(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {table: rows(db, table) for table in sorted(table_names(db)) if not table.startswith("sqlite_")}


def _replay(client: TestClient, exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    # Asset Types 1 (schema 14): every Deal body now also states its
    # classification, and a legacy record states it as null ("Not specified").
    # Only those null keys, absent from the recorded response, are set aside;
    # every other byte must still match.
    return [
        (
            (response := client.request(e["method"], e["path"], json=e["body"])).status_code,
            without_unstated_classification(response.json(), e["json"]),
        )
        for e in exchanges
    ]


def _structured_variants(manifest: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """``(fingerprint path, recorded response)`` for every structured variant
    fingerprint the v11 tree recorded."""

    found = []
    for exchange in manifest["exchanges"]:
        path = exchange["path"]
        if "/structured-variants/" in path and path.endswith("/fingerprint"):
            found.append((path, exchange["json"]))
    return found


# =============================================================================
# The baseline
# =============================================================================


def test_the_baseline_is_the_v11_tree_and_covers_every_p7_8b_flow(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    assert manifest["user_version"] == 11 and _version(db) == 11
    assert not set(P7_9_TABLES) & table_names(db)
    paths = [e["path"] for e in manifest["exchanges"]]
    assert paths.count("/analyze") == 5 and paths.count("/deals/fingerprint") == 5
    structured = manifest["structured_investment_id"]
    visible = manifest["visible_investment_id"]
    assert sum(f"/investments/{structured}/structured-variants/" in p and p.endswith("/analysis") for p in paths) == 10
    assert sum(f"/investments/{visible}/structured-variants/" in p and p.endswith("/analysis") for p in paths) == 2
    assert f"/investments/{structured}/position-decision-matrix/mezz-a" in paths
    assert f"/investments/{visible}/position-decision-matrix/portfolio-mezz" in paths
    statuses = {
        e["json"]["result"]["common_equity"]["status"]
        for e in manifest["exchanges"]
        if "/structured-variants/" in e["path"] and e["path"].endswith("/analysis")
    }
    assert statuses == {"complete", "unresolved_funding"}
    strategies = next(e["json"] for e in manifest["exchanges"] if e["path"] == f"/investments/{structured}/strategies")
    root_overlays = [record["strategy"].get("root_overlays") for record in strategies]
    assert root_overlays[0] is None  # inherits: no key at all
    assert root_overlays[1] == [{"domain": "capital_structure", "content": {"positions": []}}]


# =============================================================================
# The v11 -> v12 migration
# =============================================================================


def test_the_migration_adds_exactly_eight_empty_tables_and_rewrites_nothing(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    before_schema, before_rows = _schema(db), _every_row(db)

    store.list_deals(db_path=db)  # any store call migrates
    migrated_schema, migrated_rows = _schema(db), _every_row(db)

    assert _version(db) == 17  # Refinance V1 Stage 2 adds six capital-event tables, additively
    added = {name: migrated_schema[name] for name in set(migrated_schema) - set(before_schema)}
    # A v11 database now also gains AM1's two schema-13 Asset Management tables,
    # which are empty and additive in exactly the way Stage 2's eight are. This
    # test still measures Stage 2's own eight; the AM1 pair is named so the set
    # comparison stays exact rather than being loosened to a subset check.
    # Asset Types 1 (schema 14) adds its two classification tables the same
    # additive way; named here so the comparison stays exact.
    # P7.10 Stage 2 (schema 15) adds its sixteen valuation and Investment Memo
    # tables the same additive way; named here so the comparison stays exact.
    expected_tables = (
        set(P7_9_TABLES) | set(AM1_TABLES) | set(ASSET_TYPES_1_TABLES) | set(P7_10_TABLES) | set(P7_10_STAGE_4_TABLES)
        # Refinance V1 Stage 2 (schema 17): six capital-event tables, named so the comparison stays exact.
        | set(REFINANCE_V1_STAGE_2_TABLES)
    )
    assert {name for name, (kind, _, _) in added.items() if kind == "table"} == expected_tables
    # Every other new object is one of those tables' own key indexes.
    assert {table for _, table, _ in added.values()} == expected_tables
    assert {kind for kind, _, _ in added.values()} == {"table", "index"}
    assert set(before_schema) <= set(migrated_schema)
    # No table, index or column that existed was altered.
    assert {name: migrated_schema[name] for name in before_schema} == before_schema
    assert {table: migrated_rows[table] for table in expected_tables} == dict.fromkeys(expected_tables, [])
    assert {table: migrated_rows[table] for table in before_rows} == before_rows

    for _ in range(3):
        store.list_deals(db_path=db)
        assert (_version(db), _schema(db), _every_row(db)) == (17, migrated_schema, migrated_rows)
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    store._migrate(connection)
    connection.commit()
    connection.close()
    assert (_version(db), _schema(db), _every_row(db)) == (17, migrated_schema, migrated_rows)


def test_every_new_table_is_typed_and_holds_no_json_blob(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    try:
        columns = {
            table: [(row[1], row[2]) for row in connection.execute(f"PRAGMA table_info({table})")]
            for table in P7_9_TABLES
        }
    finally:
        connection.close()
    for table, described in columns.items():
        assert described, table
        for name, declared in described:
            assert declared in {"TEXT", "REAL", "INTEGER"}, (table, name, declared)
            assert not any(word in name for word in ("json", "blob", "payload", "snapshot", "result")), (table, name)


# =============================================================================
# Every recorded response, byte for byte
# =============================================================================


def test_every_recorded_response_is_identical(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    replayed = _replay(client, manifest["exchanges"])

    assert _version(db) == 17  # Refinance V1 Stage 2 adds six capital-event tables, additively
    mismatched = [
        (exchange["method"], exchange["path"])
        for exchange, now in zip(manifest["exchanges"], replayed, strict=True)
        if (exchange["status"], exchange["json"]) != now
    ]
    assert mismatched == []


def test_replaying_writes_nothing_and_no_read_materializes_a_partnership(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    client.get("/deals")
    before = (_version(db), _schema(db), _every_row(db))

    _replay(client, manifest["exchanges"])
    plain = next(e["path"] for e in manifest["exchanges"] if e["path"].endswith("/capital-structure") and e["path"].startswith("/deals/"))
    deal_partnership = client.get(plain.replace("/capital-structure", "/partnership"))
    for investment_id in (
        manifest["hidden_investment_id"],
        manifest["visible_investment_id"],
        manifest["structured_investment_id"],
    ):
        assert client.get(f"/investments/{investment_id}/partnership").json() == {
            "investment_id": investment_id,
            "partnership": None,
        }
        assert client.get(f"/investments/{investment_id}/partner-perspectives").json() == {
            "investment_id": investment_id,
            "partners": [],
        }

    assert deal_partnership.status_code == 200
    assert deal_partnership.json()["partnership"] is None
    assert (_version(db), _schema(db), _every_row(db)) == before
    assert {table: rows(db, table) for table in P7_9_TABLES} == dict.fromkeys(P7_9_TABLES, [])


def test_with_no_partnership_every_variant_has_no_partnership_key(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """FP-2 over real v11 state: every recorded structured variant -- both
    roots, inherited, replaced, emptied and unresolved structures -- has no
    Partnership fingerprint and no Partnership result, and its Project and
    structured fingerprints are exactly the v11 tree's."""

    _, manifest = legacy
    variants = _structured_variants(manifest)
    assert len(variants) == 12
    for path, recorded in variants:
        partnership_path = path.replace("/structured-variants/", "/partnership-variants/")
        fingerprint = client.get(partnership_path).json()
        assert fingerprint["partnership_source_fingerprint"] is None
        assert fingerprint["partnership"] is None
        assert fingerprint["partnership_source"] == "base"
        assert fingerprint["project_source_fingerprint"] == recorded["project_source_fingerprint"]
        assert fingerprint["structured_source_fingerprint"] == recorded["structured_source_fingerprint"]

        analysis = client.post(partnership_path.replace("/fingerprint", "/analysis"))
        assert analysis.status_code == 200
        body = analysis.json()
        assert body["result"] is None and body["partnership"] is None
        assert body["partnership_source_fingerprint"] is None
        assert body["structured_source_fingerprint"] == recorded["structured_source_fingerprint"]


def test_the_comparison_detects_a_single_changed_bit(baseline: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = baseline
    exchanges = [(e["status"], e["json"]) for e in manifest["exchanges"]]
    tampered = json.loads(json.dumps(exchanges))
    analysis = next(
        body
        for _, body in tampered
        if isinstance(body, dict) and isinstance(body.get("result"), dict) and "common_equity" in body["result"]
        and body["result"]["common_equity"]["cash_flows"] is not None
    )
    flows = analysis["result"]["common_equity"]["cash_flows"]
    flows[-1] = math.nextafter(flows[-1], math.inf)
    assert tampered != exchanges
