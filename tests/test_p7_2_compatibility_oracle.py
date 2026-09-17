"""Phase 7 Gate P7.2 -- the v7 -> v8 compatibility oracle against the real
``58f862d`` tree.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.3 (P-10,
P-11): every existing saved Deal reopens, analyzes and fingerprints exactly as
before, keeps its snapshots, and stays outside every P7 table until the analyst
opts in.

The v7 database is written by the pre-P7.2 tree itself (``58f862d``, exported
with ``git archive``, which reads objects and never touches the index) through
``tests/_p7_2_v7_database_builder.py``. That same tree's HTTP app records every
legacy-visible exchange -- the Deal Library, each Deal (with its analysis, AI
and sensitivity snapshots, Business Plan, Detailed inputs and rent roll), each
Deal's fingerprints and each Deal's ``/analyze`` economics. The P7.2 tree must
return exactly the same responses over the migrated database.

What is not required: byte-identical SQLite files. The migration adds five
tables, so the schema differs by exactly those; every legacy row is compared
instead.
"""

from __future__ import annotations

import copy
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
    P7_2_TABLES,
    P7_4_TABLES,
    P7_6_TABLES,
    P7_8_TABLES,
    P7_9_TABLES,
    legacy_rows,
    row_counts,
    rows,
    table_names,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_p7_2_v7_database_builder.py"
#: ``main`` when P7.2 began: the P7.1 merge, a schema-v7 tree.
_BASELINE_COMMIT = "58f862ddd8e96173d6732dc371ebda01c1a8c395"
_EMPTY = dict.fromkeys(P7_2_TABLES, 0)


@pytest.fixture(scope="module")
def v7_database(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("p7_2_v7")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True, capture_output=True, cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    db = scratch / "v7.db"
    manifest = scratch / "v7.json"
    completed = subprocess.run(
        [sys.executable, str(_BUILDER), str(scratch / "baseline"), str(db), str(manifest)],
        capture_output=True, cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return db, json.loads(manifest.read_text(encoding="utf-8"))


@pytest.fixture
def legacy(v7_database: tuple[Path, dict[str, Any]], tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """A private copy of the v7 database, so each test migrates its own."""

    source, manifest = v7_database
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


def _replay(client: TestClient, exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    return [
        ((response := client.request(e["method"], e["path"], json=e["body"])).status_code, response.json())
        for e in exchanges
    ]


def _recorded(exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    return [(e["status"], e["json"]) for e in exchanges]


# =============================================================================
# The database really is v7, and the baseline really is pre-P7.2
# =============================================================================


def test_the_legacy_database_is_genuinely_v7(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy

    assert manifest["user_version"] == 7
    assert _version(db) == 7
    assert not set(P7_2_TABLES) & table_names(db)
    assert set(manifest["deals"]) == {"quick", "detailed", "lease_level"}
    assert len(manifest["exchanges"]) == 1 + 3 * 3


# =============================================================================
# The migration is additive, exact and idempotent
# =============================================================================


def test_the_migration_adds_exactly_five_empty_tables_and_rewrites_no_row(legacy: tuple[Path, dict[str, Any]]) -> None:
    """P7.2's five tables -- and, since later gates migrate the same v7 database
    on to schema 11, P7.4's eight Strategy tables, P7.6's five Investment
    sidecars and P7.8B's six Capital Structure tables beside them, every one
    empty. Each of those gates carries its own oracle for its own step
    (``tests/test_p7_4_compatibility_oracle.py`` and its P7.6 / P7.8
    counterparts)."""

    db, _ = legacy
    before_tables, before_rows = table_names(db), legacy_rows(db)

    store.list_deals(db_path=db)  # any store call migrates
    migrated_schema, migrated_rows = _schema(db), legacy_rows(db)

    assert _version(db) == 12  # P7.4, P7.6, P7.8B and P7.9 Stage 2 migrate the same v7 database on to schema 12
    assert table_names(db) == (
        before_tables
        | set(P7_2_TABLES)
        | set(P7_4_TABLES)
        | set(P7_6_TABLES)
        | set(P7_8_TABLES)
        | set(P7_9_TABLES)
    )
    assert {table: rows(db, table) for table in P7_9_TABLES} == dict.fromkeys(P7_9_TABLES, [])
    assert {table: rows(db, table) for table in P7_8_TABLES} == dict.fromkeys(P7_8_TABLES, [])
    assert {table: rows(db, table) for table in P7_6_TABLES} == dict.fromkeys(P7_6_TABLES, [])
    assert row_counts(db) == _EMPTY
    assert {table: rows(db, table) for table in P7_4_TABLES} == dict.fromkeys(P7_4_TABLES, [])
    assert migrated_rows == before_rows
    for _ in range(3):
        store.list_deals(db_path=db)
        assert (_version(db), _schema(db), legacy_rows(db)) == (12, migrated_schema, migrated_rows)

    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    store._migrate(connection)
    connection.commit()
    connection.close()
    assert (_version(db), _schema(db), legacy_rows(db)) == (12, migrated_schema, migrated_rows)


# =============================================================================
# Every legacy-visible response is identical
# =============================================================================


def test_every_legacy_response_is_identical_after_migration(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """Reopen, the Deal Library, snapshots, Business Plan, Detailed inputs, the
    rent roll, fingerprints and ``/analyze`` economics: every exchange the v7
    tree answered is answered identically by the v8 tree, floats included
    (JSON carries each float's shortest round-tripping representation)."""

    db, manifest = legacy
    replayed = _replay(client, manifest["exchanges"])

    assert _version(db) == 12  # P7.4, P7.6, P7.8B and P7.9 Stage 2 migrate the same v7 database on to schema 12
    mismatched = [
        (exchange["method"], exchange["path"])
        for exchange, now in zip(manifest["exchanges"], replayed, strict=True)
        if (exchange["status"], exchange["json"]) != now
    ]
    assert mismatched == []


def test_the_replayed_deals_carry_their_snapshots_rather_than_losing_them(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """Identity alone could be two empty answers. These are not: every
    snapshot the v7 tree stored is served, current, by the v8 tree."""

    _, manifest = legacy
    for mode, entry in manifest["deals"].items():
        deal = client.get(f"/deals/{entry['id']}").json()
        assert deal["ai_snapshot"] is not None, mode
        if mode == "lease_level":
            assert deal["one_way_sensitivity_snapshot"] is not None
        else:
            assert deal["analysis_snapshot"] is not None
        if mode != "detailed":
            assert deal["business_plan"]["capital_items"], mode


def test_the_legacy_workflow_materializes_nothing(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    client.get("/deals")
    rows_after_migration = legacy_rows(db)

    _replay(client, manifest["exchanges"])
    for entry in manifest["deals"].values():
        client.get(f"/deals/{entry['id']}/scenarios")

    assert row_counts(db) == _EMPTY
    assert legacy_rows(db) == rows_after_migration


# =============================================================================
# Opting a legacy Deal in, and back out
# =============================================================================


def test_a_neutral_scenario_on_a_legacy_deal_reproduces_its_fingerprint_and_economics(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    _, manifest = legacy
    for mode, entry in manifest["deals"].items():
        created = client.post(f"/deals/{entry['id']}/scenarios", json={"name": "Neutral"}).json()
        path = f"/investments/{created['investment_id']}/scenarios/{created['scenario']['scenario_id']}"

        fingerprint = client.get(f"{path}/fingerprint").json()
        analysis = client.post(f"{path}/analysis").json()

        assert fingerprint["source_fingerprint"] == entry["financial_fingerprint"], mode
        assert analysis["results"] == entry["analyze"], mode


def test_opting_in_and_back_out_leaves_every_legacy_row_and_response_as_it_was(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    client.get("/deals")
    before = legacy_rows(db)

    for mode, entry in manifest["deals"].items():
        unit = entry["id"]
        target = {"quick": "exit_cap_rate", "detailed": "revenue_growth", "lease_level": "expense_growth"}[mode]
        created = client.post(f"/deals/{unit}/scenarios", json={
            "name": "Downside", "overrides": [{"unit_id": unit, "target": target, "operation": "add", "value": 0.005}],
        }).json()
        path = f"/investments/{created['investment_id']}/scenarios/{created['scenario']['scenario_id']}"
        assert client.post(f"{path}/analysis").status_code == 200
        assert client.delete(path).status_code == 204

    assert row_counts(db) == _EMPTY
    assert legacy_rows(db) == before
    replayed = _replay(client, manifest["exchanges"])
    assert replayed == _recorded(manifest["exchanges"])


def test_deleting_an_opted_in_legacy_deal_leaves_nothing_behind(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    unit = manifest["deals"]["quick"]["id"]
    client.post(f"/deals/{unit}/scenarios", json={"name": "S"})

    assert client.delete(f"/deals/{unit}").status_code == 204

    assert row_counts(db) == _EMPTY
    assert client.get(f"/deals/{unit}").status_code == 404
    for mode in ("detailed", "lease_level"):
        assert client.get(f"/deals/{manifest['deals'][mode]['id']}").status_code == 200


# =============================================================================
# The comparison can see a single bit
# =============================================================================


def test_the_comparison_detects_a_single_changed_bit(legacy: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = legacy
    recorded = _recorded(manifest["exchanges"])
    tampered = copy.deepcopy(recorded)
    analysis = next(body for status, body in tampered if isinstance(body, dict) and "results" in body and "monthly_projection" in body)
    flows = analysis["results"]["levered_cash_flows"]
    flows[2] = float.fromhex((flows[2] + abs(flows[2]) * 2.0**-52).hex())

    assert tampered != recorded
