"""Phase 7 Gate P7.7 -- the neutral compatibility oracle against the real
``fbaa07b`` tree.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.3 (P-10,
P-11). P7.7 adds a downstream package that no existing route, service or store
reaches, so every existing response must be byte-identical and no fingerprint,
schema or row may move.

The database is written by the P7.6 tree itself (``fbaa07b``, exported with
``git archive``, which reads objects and never touches the index; no stash and
no second checkout) through ``tests/_p7_7_baseline_builder.py``. That same tree's
HTTP app records the representative exchanges: Quick, Detailed and Lease-Level
Deals with and without Business Plans, a P7.5 one-unit Strategy x Scenario
matrix, and a P7.6 visible mixed-mode Investment with its consolidated analyses
and Investment Decision Matrix. The P7.7 tree must answer every one identically,
over a copy of the same database, and reading must write nothing.
"""

from __future__ import annotations

import json
import math
import re
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

from _p7_2_fixtures import rows, table_names  # type: ignore[import-not-found]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_p7_7_baseline_builder.py"
#: ``main`` when P7.7 began: the P7.6 merge, a schema-v10 tree.
_BASELINE_COMMIT = "fbaa07bfe546b05d104e4e6335f8501ca9293558"


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("p7_7_baseline")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True, capture_output=True, cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    db = scratch / "baseline.db"
    manifest = scratch / "baseline.json"
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


def _schema(db: Path) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(db)
    try:
        return connection.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    finally:
        connection.close()


def _every_row(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {table: rows(db, table) for table in sorted(table_names(db)) if not table.startswith("sqlite_")}


def _replay(client: TestClient, exchanges: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    return [
        ((response := client.request(e["method"], e["path"], json=e["body"])).status_code, response.json())
        for e in exchanges
    ]


def test_the_baseline_is_the_p7_6_tree_and_covers_every_representative_flow(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    assert manifest["user_version"] == 10 and _version(db) == 10
    paths = [e["path"] for e in manifest["exchanges"]]
    assert paths.count("/analyze") == 5 and paths.count("/deals/fingerprint") == 5
    modes = {e["body"]["operating_mode"] for e in manifest["exchanges"] if e["path"] == "/deals/fingerprint"}
    assert modes == {"quick", "detailed", "lease_level"}
    hidden, visible = manifest["hidden_investment_id"], manifest["visible_investment_id"]
    assert sum(p.startswith(f"/investments/{hidden}/variants/") and p.endswith("/analysis") for p in paths) == 4
    assert f"/investments/{hidden}/decision-matrix" in paths
    assert sum(p.startswith(f"/investments/{visible}/investment-variants/") and p.endswith("/analysis") for p in paths) == 2
    assert f"/investments/{visible}/investment-decision-matrix" in paths
    consolidated = [e["json"] for e in manifest["exchanges"] if "/investment-variants/" in e["path"] and e["path"].endswith("/analysis")]
    assert all(len(body["unit_results"]) == 3 for body in consolidated)
    one_unit = [e["json"] for e in manifest["exchanges"] if "/variants/" in e["path"] and e["path"].endswith("/analysis")]
    # Base x Base is the Deal's own analysis and bypasses the cache; every
    # Strategy or Scenario variant was warmed, so replaying reads it.
    assert {body["cache_status"] for body in one_unit} == {"hit", "bypassed"}
    assert all(
        body["cache_status"] == "hit" for body in one_unit if (body["strategy_id"], body["scenario_id"]) != ("base", "base")
    )


def test_every_recorded_response_is_identical(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    """Every Deal, fingerprint and ``/analyze`` economics, the one-unit
    variants and Decision Matrix, and the visible Investment's consolidated
    analyses and Investment Decision Matrix: the P7.7 tree answers every
    exchange the P7.6 tree answered, identically, floats included."""

    _, manifest = legacy
    replayed = _replay(client, manifest["exchanges"])
    mismatched = [
        (exchange["method"], exchange["path"])
        for exchange, now in zip(manifest["exchanges"], replayed, strict=True)
        if (exchange["status"], exchange["json"]) != now
    ]
    assert mismatched == []


def test_no_schema_change_and_no_read_triggered_materialization(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy
    client.get("/deals")
    before = (_version(db), _schema(db), _every_row(db))

    _replay(client, manifest["exchanges"])

    assert (_version(db), _schema(db), _every_row(db)) == before
    assert not {
        table for table in table_names(db) if re.search(r"capital_(position|structure|event)|funding_requirement", table)
    }


def test_the_comparison_detects_a_single_changed_bit(legacy: tuple[Path, dict[str, Any]]) -> None:
    _, manifest = legacy
    recorded = [(e["status"], e["json"]) for e in manifest["exchanges"]]
    tampered = json.loads(json.dumps(recorded))
    analysis = next(
        body for _, body in tampered
        if isinstance(body, dict) and "consolidated_results" in body
    )
    flows = analysis["consolidated_results"]["levered_cash_flows"]
    flows[-1] = math.nextafter(flows[-1], math.inf)
    assert tampered != recorded
