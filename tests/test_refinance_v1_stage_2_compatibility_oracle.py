"""Refinance & Capital Events V1 Stage 2 -- the compatibility oracle against a
real schema-v16 database (F20 persistence and API parity).

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 16.1 and 19,
invariant INV-10. Stage 2 advances the schema exactly once, to add six additive
tables, so:

- the source database is genuinely schema 16, written by accepted ``main`` at
  ``f2b5cef`` itself -- exported with ``git archive``, which reads objects and
  never touches the index (protocol 11.1 / 11.2);
- the v16 -> v17 migration adds exactly the six Stage 2 tables and their key
  indexes, alters no accepted schema object, rewrites no row, and is idempotent;
- every response the v16 tree recorded -- Quick, Detailed and Lease-Level
  analyses, structured variants with and without positions, Partnerships, the
  Project, Position and Partner matrices, fingerprints, valuation views, the
  memo, its frozen report and issued PDF, and Excel Exports 1-3 -- is answered
  identically;
- every stored Capital Structure reads back with no event, no refinance is
  synthesized, and neither the refinance executor nor the acquisition-debt
  balance service is ever called.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
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
from anchor.capital_structure.contracts import CapitalStructure
from anchor.deals import store

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_refinance_v1_v16_baseline_builder.py"
#: Accepted ``main`` when Stage 2 began: the Stage 1 review-history closeout
#: (PR #59), whose product tree is the accepted Stage 1 baseline ``6de7644``.
_BASELINE_COMMIT = "f2b5cefa7fca3ecde7621927c5818cbc40c068cd"

#: The seven tables schema 17 adds.
_NEW_TABLES = {
    "capital_events",
    "capital_event_retirements",
    "capital_event_constraints",
    "capital_event_valuation_refs",
    "capital_event_costs",
    "capital_refinance_proceeds",
    "memo_version_consumed_valuations",
}

_FROZEN_NOW = _datetime.datetime(2026, 9, 24, 12, 0, tzinfo=_datetime.timezone.utc)


class _FrozenDatetime(_datetime.datetime):
    @classmethod
    def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
        return _FROZEN_NOW


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("refinance_v1_v16_baseline")
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
        cwd=_BUILDER.parent,
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
    monkeypatch.setenv("ANCHOR_SOURCE_COMMIT", "0" * 40)
    monkeypatch.setattr(api_module, "datetime", _FrozenDatetime)
    return TestClient(api_module.app)


def _connect(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(db)


def _version(db: Path) -> int:
    connection = _connect(db)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _objects(db: Path) -> dict[tuple[str, str], str | None]:
    connection = _connect(db)
    try:
        return {(kind, name): sql for kind, name, sql in connection.execute("SELECT type, name, sql FROM sqlite_master")}
    finally:
        connection.close()


def _tables(db: Path) -> set[str]:
    return {name for (kind, name) in _objects(db) if kind == "table" and not name.startswith("sqlite_")}


def _every_row(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    connection = _connect(db)
    try:
        return {table: list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid")) for table in sorted(_tables(db))}
    finally:
        connection.close()


def _workbook_content_digest(data: bytes) -> str:
    import io

    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data))
    parts: list[str] = []
    for name in workbook.sheetnames:
        sheet = workbook[name]
        parts.append(f"#sheet:{name}")
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    parts.append(f"{cell.coordinate}|{cell.value!r}|{cell.number_format}")
        for item_name, item in sorted(workbook.defined_names.items()):
            parts.append(f"!name:{item_name}={item.value}")
    return hashlib.sha256(chr(10).join(parts).encode("utf-8")).hexdigest()


def _replay(client: TestClient, exchange: dict[str, Any]) -> dict[str, Any]:
    response = client.request(exchange["method"], exchange["path"], json=exchange["body"])
    answered: dict[str, Any] = {"status": response.status_code}
    if "json" in exchange:
        answered["json"] = response.json()
        # Byte for byte, not only equal once parsed: the serialized body itself.
        answered["raw_sha256"] = hashlib.sha256(response.content).hexdigest()
    elif "content_sha256" in exchange:
        answered["content_sha256"] = _workbook_content_digest(response.content)
    else:
        answered["sha256"] = hashlib.sha256(response.content).hexdigest()
        answered["length"] = len(response.content)
    return answered


# =============================================================================
# The baseline really is a v16 database written by the accepted tree
# =============================================================================


def test_the_baseline_is_a_real_v16_database_without_any_event_table(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    assert manifest["user_version"] == 16 and _version(db) == 16
    assert not (_NEW_TABLES & _tables(db))
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", _BASELINE_COMMIT, "src/anchor/deals"],
        capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT,
    ).stdout.split()
    assert "src/anchor/deals/store.py" in listing and "src/anchor/deals/capital_event_identity.py" not in listing
    # It holds real Capital Structures, Strategies, Partnerships and a memo.
    rows = _every_row(db)
    for table in ("capital_structures", "capital_positions", "partnerships", "investment_memo_versions", "memo_version_report_artifacts"):
        assert rows[table], table
    assert len(manifest["exchanges"]) >= 80


# =============================================================================
# The migration is additive, idempotent, and rewrites nothing
# =============================================================================


def test_the_migration_adds_exactly_the_seven_tables_and_alters_nothing(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    before_objects, before_rows = _objects(db), _every_row(db)

    store.list_deals(db_path=db)  # one ordinary read runs the migration

    after_objects = _objects(db)
    assert _version(db) == 17
    added = set(after_objects) - set(before_objects)
    assert {name for kind, name in added if kind == "table"} == _NEW_TABLES
    # Only the seven tables and SQLite's automatic key indexes for them.
    assert {kind for kind, _ in added} <= {"table", "index"}
    assert all(
        kind == "table" or (name.startswith("sqlite_autoindex_") and any(table in name for table in _NEW_TABLES))
        for kind, name in added
    ), added
    assert set(before_objects) <= set(after_objects)
    for key, sql in before_objects.items():
        assert after_objects[key] == sql, f"{key} was altered"
    after_rows = _every_row(db)
    for table, rows in before_rows.items():
        assert after_rows[table] == rows, f"{table} rows were rewritten"
    for table in _NEW_TABLES:
        assert after_rows[table] == [], table


def test_the_migration_is_idempotent(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    store.list_deals(db_path=db)
    once_rows, once_objects = _every_row(db), _objects(db)
    for _ in range(3):
        store.list_deals(db_path=db)
    assert _version(db) == 17
    assert _every_row(db) == once_rows and _objects(db) == once_objects


# =============================================================================
# Every legacy response is preserved, and nothing is synthesized
# =============================================================================


def test_every_recorded_response_is_answered_identically(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = legacy
    for exchange in manifest["exchanges"]:
        answered = _replay(client, exchange)
        expected = {key: exchange[key] for key in answered}
        assert answered == expected, exchange["path"]


def test_the_corpus_covers_every_surface_f20_names(legacy: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = legacy
    paths = " ".join(exchange["path"] for exchange in manifest["exchanges"])
    for surface in (
        "/analyze",
        "quick-underwrite.xlsx",
        "detailed-underwrite.xlsx",
        "lease-level.xlsx",
        "structured-variants",
        "partnership-variants",
        "/decision-matrix",
        "position-decision-matrix",
        "partner-decision-matrix",
        "/fingerprint",
        "/report",
        "investment-memo.pdf",
        "valuation-views",
    ):
        assert surface in paths, surface
    modes = {
        exchange["json"]["operating_mode"]
        for exchange in manifest["exchanges"]
        if exchange["method"] == "GET" and exchange["path"].startswith("/deals/") and exchange["path"].count("/") == 2
    }
    assert modes == {"quick", "detailed", "lease_level"}


def test_replaying_writes_nothing_and_synthesizes_no_refinance(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    store.list_deals(db_path=db)
    before = _every_row(db)
    for exchange in manifest["exchanges"]:
        _replay(client, exchange)
    assert _every_row(db) == before
    assert all(before[table] == [] for table in _NEW_TABLES)


def test_a_v16_published_version_records_no_scoped_consumption(legacy: tuple[Path, dict[str, Any]]) -> None:
    """A version issued before schema 17 recorded no exact-scope consumption,
    and gains none: nothing is backfilled or reconstructed from today's state."""

    db, manifest = legacy
    store.list_deals(db_path=db)
    assert store.list_memo_version_consumed_valuations(
        manifest["structured_investment_id"], manifest["version_id"], db_path=db
    ) == ()


def test_every_stored_capital_structure_reads_with_no_event(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    for investment_id in (manifest["structured_investment_id"], manifest["visible_investment_id"]):
        structures = store.list_investment_capital_structures(investment_id, db_path=db)
        stated = [structures.base, *(entry.capital_structure for entry in structures.strategies)]
        assert stated and all(type(structure) is CapitalStructure for structure in stated)


def test_no_event_analysis_never_calls_the_refinance_executor_or_the_balance_service(
    client: TestClient, legacy: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-10 and R-M: without an event, the acquisition-debt balance service
    and the refinance executors are never reached on any recorded path."""

    from anchor.capital_structure import refinance, refinance_execution
    from anchor.engine import acquisition_debt_balance

    calls: list[str] = []

    def spy(name: str, original: Any) -> Any:
        def called(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return original(*args, **kwargs)

        return called

    monkeypatch.setattr(
        acquisition_debt_balance,
        "acquisition_loan_balance_after_month",
        spy("balance service", acquisition_debt_balance.acquisition_loan_balance_after_month),
    )
    monkeypatch.setattr(
        refinance, "acquisition_loan_balance_after_month", spy("balance service", refinance.acquisition_loan_balance_after_month)
    )
    for name in ("execute_unit_refinance", "execute_investment_refinance"):
        monkeypatch.setattr(refinance_execution, name, spy(name, getattr(refinance_execution, name)))

    _, manifest = legacy
    for exchange in manifest["exchanges"]:
        _replay(client, exchange)
    assert calls == []
