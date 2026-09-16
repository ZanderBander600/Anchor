"""Phase 7 Gate P7.6 -- the neutral compatibility oracle: v9 -> v10 against the
real ``6cade62`` tree.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.3 (P-10,
P-11): with no visible Investment present, every existing Deal, hidden
Investment, Scenario, Strategy, variant and one-unit Decision Matrix behaves
exactly as before P7.6.

The v9 database is written by the pre-P7.6 tree itself (``6cade62``, exported
with ``git archive``, which reads objects and never touches the index; no stash
and no second checkout) through ``tests/_p7_6_v9_database_builder.py``. That
same tree's HTTP app records every exchange a P7.5 client can make, with the
Quick and Detailed variant caches already warm. The P7.6 tree must return
exactly the same responses over the migrated database, floats and cache
statuses included, and reading must create no visible Investment.
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

from anchor import api as api_module
from anchor.deals import store

from _p7_2_fixtures import (  # type: ignore[import-not-found]
    P7_6_TABLES,
    P7_8_TABLES,
    rows,
    table_names,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_p7_6_v9_database_builder.py"
#: ``main`` when P7.6 began: the P7.5 merge, a schema-v9 tree.
_BASELINE_COMMIT = "6cade6279ff9f071d672f68889585065a829fb2c"


@pytest.fixture(scope="module")
def v9_database(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("p7_6_v9")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True, capture_output=True, cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    db = scratch / "v9.db"
    manifest = scratch / "v9.json"
    completed = subprocess.run(
        [sys.executable, str(_BUILDER), str(scratch / "baseline"), str(db), str(manifest)],
        capture_output=True, cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return db, json.loads(manifest.read_text(encoding="utf-8"))


@pytest.fixture
def legacy(v9_database: tuple[Path, dict[str, Any]], tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    source, manifest = v9_database
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


def _schema(db: Path) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(db)
    try:
        return connection.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    finally:
        connection.close()


def _every_row(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table that is not a P7.6 sidecar or a later gate's
    appended table, in rowid order.

    P7.8B's six Capital Structure tables are excluded for the same reason the
    sidecars are: they are appended empty, and an empty table a v9 database
    never had must not read as a row that moved. That they are empty is
    asserted directly."""

    return {
        table: rows(db, table)
        for table in sorted(table_names(db) - set(P7_6_TABLES) - set(P7_8_TABLES))
        if not table.startswith("sqlite_")
    }


def _replay(client: TestClient, exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    return [
        ((response := client.request(e["method"], e["path"], json=e["body"])).status_code, response.json())
        for e in exchanges
    ]


def _recorded(exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    return [(e["status"], e["json"]) for e in exchanges]


def test_the_legacy_database_is_genuinely_v9_with_every_kind_of_p7_structure(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    assert manifest["user_version"] == 9 and _version(db) == 9
    assert not set(P7_6_TABLES) & table_names(db)
    assert len(rows(db, "investments")) == 4 and all(row[1] == 1 for row in rows(db, "investments"))
    assert len(rows(db, "scenarios")) == 6 and len(rows(db, "strategies")) == 3
    assert rows(db, "variant_snapshots")
    paths = [e["path"] for e in manifest["exchanges"]]
    assert sum(path.endswith("/decision-matrix") for path in paths) == 4
    assert {"/scenario-targets", "/strategy-targets"} <= set(paths)


def test_the_migration_adds_exactly_five_empty_sidecars_and_rewrites_no_row(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    before_tables, before_rows = table_names(db), _every_row(db)

    store.list_deals(db_path=db)
    migrated_schema, migrated_rows = _schema(db), _every_row(db)

    assert _version(db) == 11  # P7.8B migrates the same v9 database on to schema 11
    assert table_names(db) == before_tables | set(P7_6_TABLES) | set(P7_8_TABLES)
    assert {table: rows(db, table) for table in P7_8_TABLES} == dict.fromkeys(P7_8_TABLES, [])
    assert {table: rows(db, table) for table in P7_6_TABLES} == dict.fromkeys(P7_6_TABLES, [])
    assert migrated_rows == before_rows
    for _ in range(3):
        store.list_deals(db_path=db)
        assert (_version(db), _schema(db), _every_row(db)) == (11, migrated_schema, migrated_rows)
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    store._migrate(connection)
    connection.commit()
    connection.close()
    assert (_version(db), _schema(db), _every_row(db)) == (11, migrated_schema, migrated_rows)


def test_every_recorded_response_is_identical_after_migration(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    """Deals, fingerprints, ``/analyze``, Scenarios, Strategies, every variant's
    inputs, fingerprint and analysis (Quick and Detailed served from the cache
    the v9 tree wrote), every one-unit Decision Matrix and both target catalogs:
    every exchange the v9 tree answered, the current tree answers identically.

    Re-pinned at P7.8B: the same v9 database now migrates on to schema 11, and
    every one of these responses is still byte-identical. What P7.6 proved is
    unchanged -- only the version the migration lands on has moved."""

    db, manifest = legacy
    replayed = _replay(client, manifest["exchanges"])

    assert _version(db) == 11
    mismatched = [
        (exchange["method"], exchange["path"])
        for exchange, now in zip(manifest["exchanges"], replayed, strict=True)
        if (exchange["status"], exchange["json"]) != now
    ]
    assert mismatched == []


def test_the_replay_covers_cache_hits_strategy_variants_and_matrices(legacy: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = legacy
    analyses = [e["json"] for e in manifest["exchanges"] if "/variants/" in e["path"] and e["path"].endswith("/analysis")]
    assert {a["cache_status"] for a in analyses} == {"hit", "bypassed"}
    assert any(a["strategy_id"] != "base" and a["cache_status"] == "hit" for a in analyses)
    matrices = [e["json"] for e in manifest["exchanges"] if e["path"].endswith("/decision-matrix")]
    assert all(m["matrix"]["matrix_fingerprint"] for m in matrices)


def test_reading_everything_creates_no_visible_investment(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    client.get("/deals")
    before = _every_row(db)

    _replay(client, manifest["exchanges"])
    assert client.get("/investments").json() == []
    for entry in [*manifest["deals"].values(), manifest["strategy_only"]]:
        assert client.get(f"/investments/{entry['investment_id']}/details").status_code == 409

    assert {table: rows(db, table) for table in P7_6_TABLES} == dict.fromkeys(P7_6_TABLES, [])
    assert _every_row(db) == before


def test_the_comparison_detects_a_single_changed_bit(legacy: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = legacy
    recorded = _recorded(manifest["exchanges"])
    tampered = json.loads(json.dumps(recorded))
    matrix = next(body for _, body in tampered if isinstance(body, dict) and "matrix" in body)
    cell = next(c for c in matrix["matrix"]["cells"] if c["results"])
    import math

    cell["results"]["total_profit"] = math.nextafter(cell["results"]["total_profit"], math.inf)
    assert tampered != recorded
