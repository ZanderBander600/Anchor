"""Phase 7 Gate P7.8 -- the neutral compatibility oracle against the real
``a9f9b09`` tree.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.3
(P-10, P-11). P7.8 Session A adds a downstream executor that no existing route,
service or store reaches, so every existing response must be byte-identical, no
schema or row may move, and with no authored position the Capital Structure
must stay exactly the P7.7 foundation.

The database is written by the P7.7 merge itself (``a9f9b09``, exported with
``git archive``, which reads objects and never touches the index; no stash and
no second checkout) through ``tests/_p7_8_baseline_builder.py``, which replays
the P7.7 builder there: Quick, Detailed and Lease-Level Deals with and without
Business Plans, a P7.5 one-unit Strategy x Scenario matrix, and a P7.6 visible
mixed-mode Investment with its consolidated analyses and Investment Decision
Matrix. The same tree's P7.7 facades record the neutral foundation of that
Investment and of its Quick, Detailed and Lease-Level Units. The current tree
must answer every exchange identically, over a copy of the same database,
reproduce every foundation record, and execute a neutral structure onto exactly
the same Common Equity Cash Flow.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from _p7_2_fixtures import P7_8_TABLES, REFINANCE_V1_STAGE_2_TABLES, rows, table_names, without_unstated_classification  # type: ignore[import-not-found]
from _p7_7_fixtures import analyze_visible_investment  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.capital_structure import (
    CapitalStructure,
    analyze_investment_capital_structure,
    analyze_unit_capital_structure,
    execute_investment_capital_structure,
    execute_unit_capital_structure,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_p7_8_baseline_builder.py"
#: ``main`` when P7.8 began: the P7.7 merge, a schema-v10 tree.
_BASELINE_COMMIT = "a9f9b09fd71940cfdc079c109e9261187a041261"


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("p7_8_baseline")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True, capture_output=True, cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    db, manifest, foundation = scratch / "baseline.db", scratch / "baseline.json", scratch / "foundation.json"
    completed = subprocess.run(
        [sys.executable, str(_BUILDER), str(scratch / "baseline"), str(db), str(manifest), str(foundation)],
        capture_output=True, cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return db, json.loads(manifest.read_text(encoding="utf-8")), json.loads(foundation.read_text(encoding="utf-8"))


@pytest.fixture
def legacy(baseline: tuple[Path, dict[str, Any], dict[str, Any]], tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    source, manifest, _ = baseline
    path = tmp_path / "legacy.db"
    shutil.copyfile(source, path)
    return path, manifest


@pytest.fixture
def client(legacy: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(legacy[0]))
    return TestClient(api_module.app)


@pytest.fixture
def current_foundation(baseline: tuple[Path, dict[str, Any], dict[str, Any]], tmp_path: Path) -> dict[str, Any]:
    """The same visible Investment analysed by the current tree, on its own
    private copy of the baseline database."""

    source, _, recorded = baseline
    private = tmp_path / "foundation.db"
    shutil.copyfile(source, private)
    analysis, units = analyze_visible_investment(recorded["investment_id"], private)
    return {"consolidated": analysis.consolidated_results, "units": units}


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


def _json(value: Any) -> Any:
    return json.loads(json.dumps(dataclasses.asdict(value), sort_keys=True))


def _json_list(values: Any) -> Any:
    return json.loads(json.dumps([dataclasses.asdict(value) for value in values], sort_keys=True))


def _bits(values: list[float] | tuple[float, ...] | None) -> list[bytes]:
    assert values is not None
    return [struct.pack("<d", value) for value in values]


def test_the_baseline_is_the_p7_7_merge_and_covers_every_representative_flow(legacy: tuple[Path, dict[str, Any]]) -> None:
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
    one_unit = [e["json"] for e in manifest["exchanges"] if "/variants/" in e["path"] and e["path"].endswith("/analysis")]
    assert {body["cache_status"] for body in one_unit} == {"hit", "bypassed"}


def test_every_recorded_response_is_identical(client: TestClient, legacy: tuple[Path, dict[str, Any]]) -> None:
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
    # P7.8B adds the six Capital Structure tables at schema v11. Opening a
    # legacy database creates them and writes nothing into them: a Deal that
    # never opted into structured capital has no position, and no read makes it
    # one (P-11).
    capital_tables = sorted(table for table in table_names(db) if table.startswith("capital_"))
    # Refinance V1 Stage 2 appends six capital-event tables the same way, empty.
    assert capital_tables == sorted((*P7_8_TABLES, *(table for table in REFINANCE_V1_STAGE_2_TABLES if table.startswith("capital_"))))
    assert {table: rows(db, table) for table in capital_tables} == dict.fromkeys(capital_tables, [])
    assert not {table for table in table_names(db) if "funding_requirement" in table}


def test_the_p7_7_neutral_facades_reproduce_the_merged_tree(
    baseline: tuple[Path, dict[str, Any], dict[str, Any]], current_foundation: dict[str, Any]
) -> None:
    """The P7.7 Unit facade for the Quick, Detailed and Lease-Level Units and the
    P7.7 Investment facade answer exactly as the ``a9f9b09`` tree did."""

    _, _, recorded = baseline
    units, consolidated = current_foundation["units"], current_foundation["consolidated"]
    assert sorted(recorded["units"]) == sorted(unit.unit_id for unit in units) and len(units) == 3
    for unit in units:
        assert _json(analyze_unit_capital_structure(unit_id=unit.unit_id, terms=unit.terms, results=unit.results)) == recorded["units"][unit.unit_id]
    assert _json(analyze_investment_capital_structure(units=units, consolidated=consolidated)) == recorded["investment"]


@pytest.mark.parametrize("structure", [None, CapitalStructure(positions=())])
def test_the_p7_8_executor_is_neutral_against_the_merged_tree(
    baseline: tuple[Path, dict[str, Any], dict[str, Any]], current_foundation: dict[str, Any], structure: CapitalStructure | None
) -> None:
    _, _, recorded = baseline
    units, consolidated = current_foundation["units"], current_foundation["consolidated"]
    for unit in units:
        result = execute_unit_capital_structure(unit_id=unit.unit_id, terms=unit.terms, results=unit.results, capital_structure=structure)
        foundation = recorded["units"][unit.unit_id]
        assert _bits(result.common_equity.cash_flows) == _bits(foundation["common_equity_cash_flows"])
        assert _json_list(result.funding_requirements) == foundation["funding_requirements"]
        assert _json_list(result.legacy_acquisition_loans) == (
            [] if foundation["legacy_acquisition_loan"] is None else [foundation["legacy_acquisition_loan"]]
        )
        assert result.positions == ()
    investment = execute_investment_capital_structure(units=units, consolidated=consolidated, capital_structure=structure)
    assert _bits(investment.common_equity.cash_flows) == _bits(recorded["investment"]["common_equity_cash_flows"])
    assert _json_list(investment.funding_requirements) == recorded["investment"]["funding_requirements"]
    assert _json_list(investment.legacy_acquisition_loans) == recorded["investment"]["legacy_acquisition_loans"]
    assert investment.positions == ()


def test_the_comparison_detects_a_single_changed_bit(baseline: tuple[Path, dict[str, Any], dict[str, Any]]) -> None:
    _, manifest, recorded = baseline
    exchanges = [(e["status"], e["json"]) for e in manifest["exchanges"]]
    tampered = json.loads(json.dumps(exchanges))
    analysis = next(body for _, body in tampered if isinstance(body, dict) and "consolidated_results" in body)
    flows = analysis["consolidated_results"]["levered_cash_flows"]
    flows[-1] = math.nextafter(flows[-1], math.inf)
    assert tampered != exchanges
    foundation = json.loads(json.dumps(recorded["investment"]))
    foundation["common_equity_cash_flows"][-1] = math.nextafter(foundation["common_equity_cash_flows"][-1], math.inf)
    assert _bits(foundation["common_equity_cash_flows"]) != _bits(recorded["investment"]["common_equity_cash_flows"])
