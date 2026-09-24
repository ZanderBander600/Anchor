"""Phase 7 Gate P7.10 Stage 2 -- the compatibility oracle against a real
schema-v14 database.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 17 (Stage 2)
and 18.2, and ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md``
Section 15.3 (P-10, P-11). Stage 2 advances the schema exactly once and adds a
valuation and memo layer downstream of everything, so:

- the v14 -> v15 migration adds exactly sixteen empty tables, alters none,
  rewrites no row, and is idempotent. **Re-pinned at P7.10 Stage 4:** a v14
  database now migrates in one pass to the current schema version, because
  SQLite's version gate runs every additive step at once. Stage 2's sixteen
  tables are still asserted by name; what is no longer asserted is that the
  journey stops at 15, which was never Stage 2's claim to make about later
  gates;
- every response the v14 tree recorded -- Deals in all three operating modes,
  the visible Investment, the Capital Structure and Partnership surfaces, every
  Scenario, Strategy, variant fingerprint and analysis, the three Decision
  Matrices, the Managed Asset, ``/analyze`` and ``/deals/fingerprint`` -- is
  answered **byte for byte identically**;
- replaying writes nothing, and no read materializes a valuation, an Evidence
  Reference or a memo;
- with no P7.10 record anywhere, every Investment reports no valuation
  definition and no memo, and its Project, structured and Partnership
  fingerprints are exactly the ones the v14 tree reported.

The database is written by ``main`` at ``46650a7`` itself -- the accepted P7.10
Stage 1 baseline -- exported with ``git archive``, which reads objects and never
touches the index; no stash and no second checkout (protocol 11.1 / 11.2).
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

from _p7_2_fixtures import P7_10_TABLES, REFINANCE_V1_STAGE_2_TABLES, rows, table_names  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.deals import store

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_p7_10_v14_baseline_builder.py"
#: ``main`` when Stage 2 began: the P7.10 Stage 1 acceptance closeout (PR #50).
_BASELINE_COMMIT = "46650a7"

#: **Added at P7.10 Stage 4.** Tables later accepted gates add to the same
#: v14 -> current path. A v14 database migrated by today's tree arrives at
#: today's schema, so the set of added tables is Stage 2's sixteen *plus* these;
#: naming them keeps this an exact claim ("these and nothing else") rather than
#: a loosened one, and each is proved additive by its own gate's oracle --
#: Stage 4's is ``tests/test_p7_10_stage_4_compatibility_oracle.py``.
_LATER_GATE_TABLES = frozenset({"memo_version_report_artifacts", *REFINANCE_V1_STAGE_2_TABLES})


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("p7_10_v14_baseline")
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
    return {
        table: rows(db, table)
        for table in sorted(table_names(db))
        if not table.startswith("sqlite_")
    }


def _replay(client: TestClient, exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    return [
        (
            (response := client.request(e["method"], e["path"], json=e["body"])).status_code,
            response.json() if response.content else None,
        )
        for e in exchanges
    ]


# =============================================================================
# The baseline
# =============================================================================


def test_the_baseline_is_the_v14_tree_and_holds_no_p7_10_record(
    legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    assert manifest["user_version"] == 14 and _version(db) == 14
    assert not set(P7_10_TABLES) & table_names(db)
    paths = [e["path"] for e in manifest["exchanges"]]
    structured = manifest["structured_investment_id"]
    # The baseline really exercises the surfaces P7.10 Stage 2 sits downstream of.
    assert sum(p.endswith("/analysis") and "/structured-variants/" in p for p in paths) == 4
    assert sum(p.endswith("/analysis") and "/partnership-variants/" in p for p in paths) == 4
    assert f"/investments/{structured}/position-decision-matrix/senior-loan" in paths
    assert f"/investments/{structured}/partner-decision-matrix/lp" in paths
    assert "/analyze" in paths and "/deals/fingerprint" in paths


# =============================================================================
# The v14 -> v15 migration
# =============================================================================


def test_the_migration_adds_stage_2s_sixteen_empty_tables_and_rewrites_nothing(
    legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, _ = legacy
    before_schema, before_rows = _schema(db), _every_row(db)

    store.list_deals(db_path=db)  # any store call migrates
    migrated_schema, migrated_rows = _schema(db), _every_row(db)

    assert _version(db) == store._SCHEMA_VERSION
    added = {name: migrated_schema[name] for name in set(migrated_schema) - set(before_schema)}
    expected = set(P7_10_TABLES)
    every_added = expected | _LATER_GATE_TABLES
    assert {name for name, (kind, _, _) in added.items() if kind == "table"} == every_added
    # Every other new object is one of those tables' own key indexes.
    assert {table for _, table, _ in added.values()} == every_added
    assert {kind for kind, _, _ in added.values()} == {"table", "index"}
    # No table, index or column that existed was altered.
    assert set(before_schema) <= set(migrated_schema)
    assert {name: migrated_schema[name] for name in before_schema} == before_schema
    # Every new table arrives empty, and every pre-existing row is untouched.
    assert {table: migrated_rows[table] for table in every_added} == dict.fromkeys(every_added, [])
    assert {table: migrated_rows[table] for table in before_rows} == before_rows

    # Idempotent: repeated connections and an explicit re-migration change nothing.
    for _ in range(3):
        store.list_deals(db_path=db)
        assert (_version(db), _schema(db), _every_row(db)) == (
            store._SCHEMA_VERSION,
            migrated_schema,
            migrated_rows,
        )
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    store._migrate(connection)
    connection.commit()
    connection.close()
    assert (_version(db), _schema(db), _every_row(db)) == (
        store._SCHEMA_VERSION,
        migrated_schema,
        migrated_rows,
    )


def test_the_migration_statement_alters_and_drops_nothing(
    legacy: tuple[Path, dict[str, Any]]
) -> None:
    """Measured, not asserted: no schema object's SQL mentions an ALTER or a
    DROP of anything this gate touches, and every P7.10 table is a plain
    CREATE."""

    db, _ = legacy
    store.list_deals(db_path=db)
    schema = _schema(db)
    for table in P7_10_TABLES:
        sql = schema[table][2] or ""
        assert sql.upper().startswith("CREATE TABLE"), table
        assert "ALTER" not in sql.upper() and "DROP" not in sql.upper(), table


def test_every_new_table_is_typed_and_holds_no_json_blob(
    legacy: tuple[Path, dict[str, Any]]
) -> None:
    """Section 15: live records use typed tables; no opaque JSON blob becomes
    the authoritative contract."""

    db, _ = legacy
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    try:
        columns = {
            table: [(row[1], row[2]) for row in connection.execute(f"PRAGMA table_info({table})")]
            for table in P7_10_TABLES
        }
    finally:
        connection.close()
    for table, described in columns.items():
        assert described, table
        for name, declared in described:
            assert declared in {"TEXT", "REAL", "INTEGER"}, (table, name, declared)
            assert not any(
                word in name.lower() for word in ("json", "blob", "payload", "snapshot")
            ), (table, name)


# =============================================================================
# Every recorded response, byte for byte
# =============================================================================


def test_every_recorded_response_is_identical(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """The whole point of the gate's compatibility claim: an existing Deal,
    Investment, Capital Structure, Partnership, variant, matrix and Managed
    Asset with no P7.10 record behaves **exactly** as it did."""

    db, manifest = legacy
    replayed = _replay(client, manifest["exchanges"])

    assert _version(db) == store._SCHEMA_VERSION
    mismatched = [
        (exchange["method"], exchange["path"])
        for exchange, now in zip(manifest["exchanges"], replayed, strict=True)
        if (exchange["status"], exchange["json"]) != now
    ]
    assert mismatched == []


def test_replaying_writes_nothing_and_no_read_materializes_a_p7_10_record(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """Reading a valuation list, an evidence register or a memo creates
    nothing -- not a row, and not a hidden Investment."""

    db, manifest = legacy
    client.get("/deals")  # migrate first, so the comparison is v15 against v15
    before = (_version(db), _schema(db), _every_row(db))

    _replay(client, manifest["exchanges"])
    for investment_id in (manifest["structured_investment_id"], manifest["visible_investment_id"]):
        assert client.get(f"/investments/{investment_id}/valuation-timepoints").json() == {
            "investment_id": investment_id,
            "valuation_timepoints": [],
        }
        assert client.get(f"/investments/{investment_id}/evidence-references").json() == {
            "investment_id": investment_id,
            "evidence_references": [],
        }
        assert client.get(f"/investments/{investment_id}/memo").json() == {
            "investment_id": investment_id,
            "memo": None,
        }
        assert client.get(f"/investments/{investment_id}/memo-versions").json() == {
            "investment_id": investment_id,
            "memo_versions": [],
        }
    # A standalone Deal: reading creates no hidden wrapper. The Quick Deal is
    # deliberately not asked -- it is a Unit of the visible Investment, and a
    # Unit is refused rather than answered, which its own API test proves.
    standalone = manifest["lease_level_deal_id"]
    assert client.get(f"/deals/{standalone}/valuation-timepoints").json() == {
        "deal_id": standalone,
        "investment_id": None,
        "valuation_timepoints": [],
    }
    assert client.get(f"/deals/{standalone}/memo").json() == {
        "deal_id": standalone,
        "investment_id": None,
        "memo": None,
    }

    assert (_version(db), _schema(db), _every_row(db)) == before


def test_a_deal_with_no_p7_10_record_resolves_no_valuation_and_keeps_its_fingerprints(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """With no valuation defined anywhere, the new views route reports no view
    at all -- never a zero-valued one -- and the structured fingerprint is
    exactly the one the v14 tree reported for the same variant (FP-2 for the
    consumed-valuation payload)."""

    _, manifest = legacy
    structured = manifest["structured_investment_id"]
    recorded = {
        exchange["path"]: exchange["json"]
        for exchange in manifest["exchanges"]
        if "/structured-variants/" in exchange["path"] and exchange["path"].endswith("/fingerprint")
    }
    assert recorded, "the baseline recorded no structured fingerprint"

    for path, before in recorded.items():
        now = client.get(path).json()
        assert now == before, path

    views = client.post(f"/investments/{structured}/valuation-views/base/base").json()
    assert views["views"] == []
    assert views["evidence_blocked"] == []
    assert views["consumed_timepoint_ids"] == []
    assert views["structured_source_fingerprint"] == next(iter(recorded.values()))[
        "structured_source_fingerprint"
    ]
