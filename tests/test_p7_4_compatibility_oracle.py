"""Phase 7 Gate P7.4 -- the neutral compatibility oracle: v8 -> v9 against the
real ``aa96155`` tree.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.3 (P-10,
P-11): with no Strategy present, every existing Deal -- and every existing
Scenario -- behaves exactly as before P7.4.

The v8 database is written by the pre-P7.4 tree itself (``aa96155``, exported
with ``git archive``, which reads objects and never touches the index; no stash
and no second checkout) through ``tests/_p7_4_v8_database_builder.py``. That
same tree's HTTP app records every exchange a P7.3 client can make:
- the Deal Library, each Deal with its snapshots, Business Plan and rent roll;
- each Deal's fingerprints and ``/analyze`` economics;
- its Scenarios and hidden Investment;
- each Scenario's fingerprint and analysis, served from the variant cache;
- the Scenario target catalog.

The P7.4 tree must return exactly the same responses over the migrated database.
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

from _p7_2_fixtures import P7_4_TABLES, P7_6_TABLES, rows, table_names  # type: ignore[import-not-found]
import _p7_4_fixtures as f4  # type: ignore[import-not-found]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_p7_4_v8_database_builder.py"
#: ``main`` when P7.4 began: the P7.3 merge, a schema-v8 tree.
_BASELINE_COMMIT = "aa96155c4c097a1b7dad3f4c791178cb26b619a5"


@pytest.fixture(scope="module")
def v8_database(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("p7_4_v8")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True, capture_output=True, cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    db = scratch / "v8.db"
    manifest = scratch / "v8.json"
    completed = subprocess.run(
        [sys.executable, str(_BUILDER), str(scratch / "baseline"), str(db), str(manifest)],
        capture_output=True, cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return db, json.loads(manifest.read_text(encoding="utf-8"))


@pytest.fixture
def legacy(v8_database: tuple[Path, dict[str, Any]], tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """A private copy of the v8 database, so each test migrates its own."""

    source, manifest = v8_database
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
    """Every row of every table that is not a P7.4 table -- legacy and P7.2
    alike -- in rowid order."""

    return {
        table: rows(db, table)
        for table in sorted(table_names(db) - set(P7_4_TABLES) - set(P7_6_TABLES))
        if not table.startswith("sqlite_")
    }


def _replay(client: TestClient, exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    return [
        ((response := client.request(e["method"], e["path"], json=e["body"])).status_code, response.json())
        for e in exchanges
    ]


def _recorded(exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    return [(e["status"], e["json"]) for e in exchanges]


# =============================================================================
# The database really is v8, with real P7.2 structure in it
# =============================================================================


def test_the_legacy_database_is_genuinely_v8_with_scenarios_and_cached_variants(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy

    assert manifest["user_version"] == 8
    assert _version(db) == 8
    assert not set(P7_4_TABLES) & table_names(db)
    assert set(manifest["deals"]) == {"quick", "detailed", "lease_level"}
    assert len(rows(db, "investments")) == 3 and len(rows(db, "scenarios")) == 6
    assert len(rows(db, "variant_snapshots")) == 4  # Quick and Detailed only
    assert len(manifest["exchanges"]) == 2 + 4 * 4 + 3 * (2 + 2 * 3)


# =============================================================================
# The migration is additive, exact and idempotent
# =============================================================================


def test_the_migration_adds_exactly_eight_empty_tables_and_rewrites_no_row(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    before_tables, before_rows = table_names(db), _every_row(db)

    store.list_deals(db_path=db)  # any store call migrates
    migrated_schema, migrated_rows = _schema(db), _every_row(db)

    assert _version(db) == 10  # P7.6 migrates the same v8 database on to schema 10
    assert table_names(db) == before_tables | set(P7_4_TABLES) | set(P7_6_TABLES)
    assert {table: rows(db, table) for table in P7_6_TABLES} == dict.fromkeys(P7_6_TABLES, [])
    assert {table: rows(db, table) for table in P7_4_TABLES} == dict.fromkeys(P7_4_TABLES, [])
    assert migrated_rows == before_rows
    for _ in range(3):
        store.list_deals(db_path=db)
        assert (_version(db), _schema(db), _every_row(db)) == (10, migrated_schema, migrated_rows)

    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    store._migrate(connection)
    connection.commit()
    connection.close()
    assert (_version(db), _schema(db), _every_row(db)) == (10, migrated_schema, migrated_rows)


# =============================================================================
# Every legacy, P7.2 and P7.3 response is identical
# =============================================================================


def test_every_recorded_response_is_identical_after_migration(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    """Ordinary Quick / Detailed / Lease-Level analysis, fingerprints, Business
    Plans, snapshots, Scenario persistence, Scenario fingerprints and analyses
    (Quick and Detailed served from the cache written by the v8 tree), and the
    P7.3 Scenario target catalog: every exchange the v8 tree answered, the v9
    tree answers identically, floats included."""

    db, manifest = legacy
    replayed = _replay(client, manifest["exchanges"])

    assert _version(db) == 10
    mismatched = [
        (exchange["method"], exchange["path"])
        for exchange, now in zip(manifest["exchanges"], replayed, strict=True)
        if (exchange["status"], exchange["json"]) != now
    ]
    assert mismatched == []


def test_the_replay_really_covers_snapshots_cache_hits_and_the_catalog(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = legacy
    analyses = [e["json"] for e in manifest["exchanges"] if e["path"].endswith("/analysis")]
    assert sorted(a["cache_status"] for a in analyses) == ["bypassed", "bypassed", "hit", "hit", "hit", "hit"]
    assert any(e["path"] == "/scenario-targets" for e in manifest["exchanges"])
    for mode, entry in manifest["deals"].items():
        deal = client.get(f"/deals/{entry['id']}").json()
        assert deal["ai_snapshot"] is not None, mode
        if mode != "detailed":
            assert deal["business_plan"]["capital_items"], mode


def test_strategy_reads_and_the_legacy_workflow_materialize_nothing(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    client.get("/deals")
    before = _every_row(db)

    _replay(client, manifest["exchanges"])
    for entry in [*manifest["deals"].values(), manifest["standalone"]]:
        assert client.get(f"/deals/{entry['id']}/strategies").status_code == 200
    for entry in manifest["deals"].values():
        assert client.get(f"/investments/{entry['investment_id']}/strategies").json() == []
        for scenario_id in entry["scenario_ids"]:
            assert client.get(f"/investments/{entry['investment_id']}/variants/base/{scenario_id}/inputs").status_code == 200
    assert client.get(f"/deals/{manifest['standalone']['id']}/strategies").json() == {
        "deal_id": manifest["standalone"]["id"], "investment_id": None, "strategies": [],
    }

    assert {table: rows(db, table) for table in P7_4_TABLES} == dict.fromkeys(P7_4_TABLES, [])
    assert _every_row(db) == before


# =============================================================================
# Opting a legacy Deal into Strategies, and back out
# =============================================================================


def test_a_strategy_restating_base_on_a_legacy_deal_reproduces_its_fingerprint_and_economics(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    _, manifest = legacy
    for mode, entry in [*manifest["deals"].items(), ("quick", manifest["standalone"])]:
        state = client.get(f"/deals/{entry['id']}").json()
        hold = (state["inputs"] or state["terms"])["hold_period"]
        created = client.post(f"/deals/{entry['id']}/strategies", json={
            "name": "Hold as underwritten", "overlays": [f4.wire(f4.disposition(entry["id"], hold))],
        }).json()
        variant = f"/investments/{created['investment_id']}/variants/{created['strategy']['strategy_id']}/base"

        assert client.get(f"{variant}/fingerprint").json()["source_fingerprint"] == entry["financial_fingerprint"], mode
        assert client.post(f"{variant}/analysis").json()["results"] == entry["analyze"], mode


def test_opting_a_standalone_deal_in_and_back_out_leaves_every_row_and_response(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    client.get("/deals")
    before = _every_row(db)
    deal_id = manifest["standalone"]["id"]

    created = client.post(f"/deals/{deal_id}/strategies", json={
        "name": "Bid low", "overlays": [f4.wire(f4.acquisition(deal_id, purchase_price=11_000_000.0))],
    }).json()
    path = f"/investments/{created['investment_id']}/strategies/{created['strategy']['strategy_id']}"
    assert client.post(f"/investments/{created['investment_id']}/variants/{created['strategy']['strategy_id']}/base/analysis").status_code == 200
    assert client.delete(path).status_code == 204

    assert {table: rows(db, table) for table in P7_4_TABLES} == dict.fromkeys(P7_4_TABLES, [])
    assert _every_row(db) == before
    assert _replay(client, manifest["exchanges"]) == _recorded(manifest["exchanges"])


def test_a_strategy_beside_legacy_scenarios_changes_no_scenario_response(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """The one row a Strategy's arrival and departure touches is the shared
    Investment's ``updated_at``. Every Scenario, override, cached variant and
    Deal row -- and every response but the Investment's own -- is unchanged."""

    db, manifest = legacy
    client.get("/deals")
    before = {table: rows for table, rows in _every_row(db).items() if table != "investments"}

    for mode, entry in manifest["deals"].items():
        created = client.post(f"/deals/{entry['id']}/strategies", json={
            "name": "Renovate", "overlays": [f4.wire(f4.plan_overlay(entry["id"], f4.renovation_plan()))],
        }).json()
        assert created["investment_id"] == entry["investment_id"], mode
        path = f"/investments/{created['investment_id']}/strategies/{created['strategy']['strategy_id']}"
        assert client.delete(path).status_code == 204
        assert client.get(f"/investments/{entry['investment_id']}").status_code == 200, mode

    after = {table: rows for table, rows in _every_row(db).items() if table != "investments"}
    assert after == before
    investment_paths = {f"/investments/{entry['investment_id']}" for entry in manifest["deals"].values()}
    kept = [e for e in manifest["exchanges"] if e["path"] not in investment_paths]
    assert _replay(client, kept) == _recorded(kept)


def test_deleting_an_opted_in_legacy_deal_leaves_nothing_behind(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    entry = manifest["deals"]["quick"]
    client.post(f"/deals/{entry['id']}/strategies", json={"name": "S"})

    assert client.delete(f"/deals/{entry['id']}").status_code == 204

    assert {table: rows(db, table) for table in P7_4_TABLES} == dict.fromkeys(P7_4_TABLES, [])
    assert not [row for row in rows(db, "investments") if row[0] == entry["investment_id"]]
    assert not [row for row in rows(db, "scenarios") if row[1] == entry["investment_id"]]
    for mode in ("detailed", "lease_level"):
        assert client.get(f"/deals/{manifest['deals'][mode]['id']}").status_code == 200


def test_the_comparison_detects_a_single_changed_bit(legacy: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = legacy
    recorded = _recorded(manifest["exchanges"])
    tampered = json.loads(json.dumps(recorded))
    analysis = next(
        body for _, body in tampered
        if isinstance(body, dict) and "results" in body and isinstance(body["results"], dict)
        and "levered_cash_flows" in body["results"]
    )
    flows = analysis["results"]["levered_cash_flows"]
    flows[2] = float.fromhex((flows[2] + abs(flows[2]) * 2.0**-52).hex())
    assert tampered != recorded
