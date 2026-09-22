"""Phase 7 Gate P7.10 Stage 4 -- the compatibility oracle against a real
schema-v15 database.

Ratified at the Stage 4 independent review (Correction 1). Stage 4 advances the
schema exactly once, to add one additive table, so:

- the v15 -> v16 migration adds exactly one empty table, alters none, rewrites
  no row, and is idempotent;
- every response the v15 tree recorded is answered **byte for byte
  identically**;
- a memo version published by the v15 tree keeps every one of its own rows, and
  reports the typed ``REPORT_SNAPSHOT_NOT_AVAILABLE`` state rather than a report
  reconstructed from today's numbers.

The database is written by accepted ``main`` at ``9ca957a`` itself, exported
with ``git archive``, which reads objects and never touches the index; no stash
and no second checkout (protocol 11.1 / 11.2).
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

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_p7_10_v15_baseline_builder.py"
#: Accepted ``main`` when Stage 4 began: the P7.10 Stage 2 acceptance closeout.
_BASELINE_COMMIT = "9ca957a"

#: The one table schema 16 adds.
_NEW_TABLE = "memo_version_report_artifacts"


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("p7_10_v15_baseline")
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


def _tables(db: Path) -> set[str]:
    connection = sqlite3.connect(db)
    try:
        return {
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not name.startswith("sqlite_")
        }
    finally:
        connection.close()


def _schema_sql(db: Path) -> dict[str, str | None]:
    connection = sqlite3.connect(db)
    try:
        return {
            name: sql
            for name, sql in connection.execute(
                "SELECT name, sql FROM sqlite_master ORDER BY name"
            )
        }
    finally:
        connection.close()


def _every_row(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    connection = sqlite3.connect(db)
    try:
        return {
            table: list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid"))
            for table in sorted(_tables(db))
        }
    finally:
        connection.close()


# =============================================================================
# The baseline really is a v15 database with a published version
# =============================================================================


def test_the_baseline_is_a_real_v15_tree_with_a_published_memo(
    legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    assert manifest["user_version"] == 15 and _version(db) == 15
    assert _NEW_TABLE not in _tables(db), "the v15 tree already had the artifact table"

    # The published version and every child row it owns are really there.
    connection = sqlite3.connect(db)
    try:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM investment_memo_versions WHERE version_id = ?",
                (manifest["version_id"],),
            ).fetchone()[0]
            == 1
        )
        for table in ("memo_version_items", "memo_version_evidence", "memo_version_dependencies"):
            assert (
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE version_id = ?",
                    (manifest["version_id"],),
                ).fetchone()[0]
                > 0
            ), table
    finally:
        connection.close()


# =============================================================================
# The migration is additive, idempotent, and rewrites nothing
# =============================================================================


def test_the_migration_adds_exactly_one_empty_table(
    legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, _ = legacy
    before_tables, before_rows, before_schema = _tables(db), _every_row(db), _schema_sql(db)

    store.list_deals(db_path=db)  # one ordinary read runs the migration

    after_tables = _tables(db)
    assert after_tables - before_tables == {_NEW_TABLE}
    assert before_tables - after_tables == set()
    assert _version(db) == 16

    # Every pre-existing table's definition is byte-identical: nothing altered.
    after_schema = _schema_sql(db)
    for name, sql in before_schema.items():
        assert after_schema[name] == sql, f"{name} was altered"

    # Every pre-existing row is byte-identical: nothing rewritten.
    after_rows = _every_row(db)
    for table, rows in before_rows.items():
        assert after_rows[table] == rows, f"{table} rows were rewritten"

    # And the new table is empty: the migration backfills no artifact.
    assert after_rows[_NEW_TABLE] == []


def test_the_migration_is_idempotent(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    store.list_deals(db_path=db)
    once_rows, once_schema = _every_row(db), _schema_sql(db)

    for _ in range(3):
        store.list_deals(db_path=db)

    assert _version(db) == 16
    assert _every_row(db) == once_rows
    assert _schema_sql(db) == once_schema


# =============================================================================
# Every legacy response is preserved
# =============================================================================


def test_every_recorded_response_is_answered_identically(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """Byte for byte, for every surface the v15 tree recorded.

    Deliberately includes the memo, its versions, its freshness and its
    valuation views: Stage 4 changes how a *report* is produced and must change
    none of the Stage 2 answers around it."""

    _, manifest = legacy
    for exchange in manifest["exchanges"]:
        response = client.request(exchange["method"], exchange["path"], json=exchange["body"])
        assert response.status_code == exchange["status"], exchange["path"]
        actual = response.json() if response.content else None
        assert actual == exchange["json"], exchange["path"]


def test_replaying_the_reads_writes_nothing(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    db, manifest = legacy
    store.list_deals(db_path=db)  # migrate first, so only the replay is measured
    before = _every_row(db)

    for exchange in manifest["exchanges"]:
        client.request(exchange["method"], exchange["path"], json=exchange["body"])

    assert _every_row(db) == before, "replaying the recorded reads wrote something"


# =============================================================================
# The pre-v16 published version: readable, and honestly unavailable
# =============================================================================


def test_a_v15_version_reports_the_typed_state_and_recomputes_nothing(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """The migrated version keeps every fact it recorded, and gains no report.

    The alternative -- assembling today's numbers and presenting them as what
    that committee read -- is exactly what the correction forbids."""

    db, manifest = legacy
    investment_id, version_id = manifest["investment_id"], manifest["version_id"]

    # The version itself is unchanged and fully readable.
    stored = client.get(f"/investments/{investment_id}/memo-versions/{version_id}")
    assert stored.status_code == 200
    assert stored.json()["memo_version"]["version_number"] == manifest["version_number"]

    # The report answers successfully, with no report and a typed reason.
    report = client.get(f"/investments/{investment_id}/memo-versions/{version_id}/report")
    assert report.status_code == 200
    body = report.json()
    assert body["report"] is None
    assert body["unavailable"]["code"] == "report_snapshot_not_available"
    assert "publish a new version" in body["unavailable"]["message"].lower()

    # The PDF is refused with the same typed code, never re-rendered.
    pdf = client.get(
        f"/investments/{investment_id}/memo-versions/{version_id}"
        "/exports/investment-memo.pdf"
    )
    assert pdf.status_code == 422
    assert pdf.json()["detail"]["code"] == "report_snapshot_not_available"

    # And asking gained it no artifact: nothing was backfilled by being read.
    connection = sqlite3.connect(db)
    try:
        assert connection.execute(f"SELECT COUNT(*) FROM {_NEW_TABLE}").fetchone()[0] == 0
    finally:
        connection.close()


def test_publishing_again_on_a_migrated_database_issues_a_report(
    client: TestClient, legacy: tuple[Path, dict[str, Any]]
) -> None:
    """The remedy the message names actually works.

    An analyst told to publish a new version gets one, with an issued report and
    a downloadable PDF -- and the older version is still exactly as it was."""

    _, manifest = legacy
    investment_id, old_version = manifest["investment_id"], manifest["version_id"]

    published = client.post(f"/investments/{investment_id}/memo/publish")
    assert published.status_code == 200, published.text
    new_version = published.json()["memo_version"]["version_id"]
    assert new_version != old_version

    report = client.get(f"/investments/{investment_id}/memo-versions/{new_version}/report")
    assert report.status_code == 200
    assert report.json()["report"] is not None
    assert report.json()["unavailable"] is None

    pdf = client.get(
        f"/investments/{investment_id}/memo-versions/{new_version}"
        "/exports/investment-memo.pdf"
    )
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")

    # The older version is untouched: still readable, still without a report.
    old = client.get(f"/investments/{investment_id}/memo-versions/{old_version}/report")
    assert old.json()["report"] is None
    assert old.json()["unavailable"]["code"] == "report_snapshot_not_available"
