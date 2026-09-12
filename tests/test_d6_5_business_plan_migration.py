"""Phase 6 Gate D6.5 -- schema v6 -> v7, from a real v6 database.

The v6 database is written by the pre-D6.5 tree itself (93636ee, exported with
``git archive``, which reads objects and never touches the index) through
``tests/_d6_5_v6_database_builder.py``. Constructing a v7 database and lowering
its version would prove nothing: the risk under test is that upgrading disturbs
data -- deals, snapshots, fingerprints -- that already exists.

The invariants:

- **Additive.** The two Business Plan tables appear; no existing table, column
  or row changes; the version advances 6 -> 7 exactly once and re-opening the
  store changes nothing further.
- **Nothing fabricated.** No plan row is written for a legacy deal; each loads
  as exactly ``BusinessPlan()``.
- **Legacy fingerprints preserved.** Every snapshot the v6 tree stored is still
  current -- which it can only be if the empty plan hashes exactly as v6 did --
  and today's fingerprints equal the ones v6 computed.
- **Invalid snapshots stay safe.** A stored snapshot that is incompatible or
  malformed is absent after migration, and the deal re-analyzes normally.
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
from fastapi.encoders import jsonable_encoder

from anchor.business_plan import BusinessPlan
from anchor.deals import store as deals_store
from anchor.deals.contracts import Deal
from anchor.deals.fingerprint import (
    fingerprint_ai,
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)
from anchor.engine.contracts import IrrStatus

from _d6_5_fixtures import (  # type: ignore[import-not-found]
    MATERIAL,
    MODES,
    PRE_D6_5_DIGESTS,
    analyze,
    analyze_deal,
    plan_rows,
    update,
)
from test_d6_2_owner_cash_flow_engine import (  # type: ignore[import-not-found]
    DETAILED_OPERATING,
    DETAILED_TERMS,
    LL_TERMS,
    QUICK,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_d6_5_v6_database_builder.py"
#: ``main`` after D6.4, immediately before D6.5 -- a schema-v6 tree.
_BASELINE_COMMIT = "93636ee"
_PLAN_TABLES = {"deal_capital_plan_items", "deal_owner_expense_items"}


@pytest.fixture(scope="module")
def v6_database(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    scratch = tmp_path_factory.mktemp("d6_5_v6")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True,
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    db = scratch / "v6.db"
    manifest = scratch / "v6.json"
    completed = subprocess.run(
        [sys.executable, str(_BUILDER), str(scratch / "baseline"), str(db), str(manifest)],
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return db, json.loads(manifest.read_text(encoding="utf-8"))


@pytest.fixture
def legacy(v6_database: tuple[Path, dict[str, Any]], tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """A private copy of the v6 database, so each test migrates its own."""

    source, manifest = v6_database
    copy = tmp_path / "legacy.db"
    shutil.copyfile(source, copy)
    return copy, manifest


def _raw(db: Path) -> dict[str, list[tuple]]:
    connection = sqlite3.connect(db)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in tables
        }
    finally:
        connection.close()


def _schema(db: Path) -> list[tuple]:
    connection = sqlite3.connect(db)
    try:
        return connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        connection.close()


def _version(db: Path) -> int:
    connection = sqlite3.connect(db)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _inputs_of(deal: Deal) -> dict[str, Any]:
    if deal.inputs is not None:
        fields = {"inputs": deal.inputs}
    elif deal.detailed_operating_inputs is not None:
        fields = {"terms": deal.terms, "detailed_operating_inputs": deal.detailed_operating_inputs}
    else:
        fields = {
            "terms": deal.terms,
            "property_inputs": deal.property_inputs,
            "operating_inputs": deal.operating_inputs,
            "market_leasing": deal.market_leasing,
            "suites": deal.suites,
            "leases": deal.leases,
        }
    return json.loads(json.dumps(jsonable_encoder(fields)))


def _financial_fingerprint(deal: Deal) -> str:
    plan = deal.business_plan
    if deal.inputs is not None:
        return fingerprint_quick_inputs(deal.inputs, business_plan=plan)
    assert deal.terms is not None
    if deal.detailed_operating_inputs is not None:
        return fingerprint_detailed_inputs(
            deal.terms, deal.detailed_operating_inputs, business_plan=plan
        )
    assert deal.property_inputs is not None and deal.operating_inputs is not None
    assert deal.market_leasing is not None and deal.suites is not None
    assert deal.leases is not None
    return fingerprint_lease_level_inputs(
        deal.terms,
        deal.property_inputs,
        deal.suites,
        deal.leases,
        market_leasing=deal.market_leasing,
        operating_inputs=deal.operating_inputs,
        business_plan=plan,
    )


# =============================================================================
# The database really is v6
# =============================================================================


def test_the_legacy_database_is_genuinely_v6(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, manifest = legacy

    assert manifest["user_version"] == 6
    assert _version(db) == 6
    assert not _PLAN_TABLES & set(_raw(db))
    assert set(manifest["deals"]) == set(MODES)


# =============================================================================
# The migration is additive, exact and idempotent
# =============================================================================


def test_the_version_advances_to_7_exactly_once_and_only_the_plan_tables_appear(
    legacy: tuple[Path, dict[str, Any]],
) -> None:
    db, _ = legacy
    before = _raw(db)

    deals_store.list_deals(db_path=db)  # any store call migrates
    after_first = _schema(db)
    migrated = _raw(db)

    assert _version(db) == 7
    assert set(migrated) == set(before) | _PLAN_TABLES
    assert migrated["deal_capital_plan_items"] == []
    assert migrated["deal_owner_expense_items"] == []

    for _ in range(3):
        deals_store.list_deals(db_path=db)
        assert _version(db) == 7
        assert _schema(db) == after_first
        assert _raw(db) == migrated


def test_the_migration_rewrites_no_existing_row(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    before = _raw(db)

    deals_store.list_deals(db_path=db)
    after = _raw(db)

    for table, rows in before.items():
        assert after[table] == rows, f"{table} changed during migration"


def test_migrate_is_a_no_op_on_a_v7_database(legacy: tuple[Path, dict[str, Any]]) -> None:
    db, _ = legacy
    deals_store.list_deals(db_path=db)
    schema, rows = _schema(db), _raw(db)

    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    deals_store._migrate(connection)
    connection.commit()
    connection.close()

    assert _version(db) == 7
    assert _schema(db) == schema and _raw(db) == rows


# =============================================================================
# Legacy deals load unchanged, with the empty plan
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_every_legacy_deal_loads_its_inputs_unchanged_and_the_empty_plan(
    legacy: tuple[Path, dict[str, Any]], mode: str
) -> None:
    db, manifest = legacy
    entry = manifest["deals"][mode]

    deal = deals_store.get_deal(entry["id"], db_path=db)
    listed = {listed.id: listed for listed in deals_store.list_deals(db_path=db)}[entry["id"]]

    assert type(deal.business_plan) is BusinessPlan
    assert deal.business_plan == BusinessPlan() == listed.business_plan
    assert _inputs_of(deal) == entry["inputs"]
    assert plan_rows(db, entry["id"]) == (0, 0)


@pytest.mark.parametrize("mode", MODES)
def test_legacy_fingerprints_are_preserved(
    legacy: tuple[Path, dict[str, Any]], mode: str
) -> None:
    """Today's fingerprints of a migrated legacy deal are exactly the ones the
    v6 tree computed for it -- and, because the builder's deals are the D6.2
    fixtures, exactly the digests pinned before any D6.5 source changed."""

    db, manifest = legacy
    entry = manifest["deals"][mode]
    deal = deals_store.get_deal(entry["id"], db_path=db)

    financial = _financial_fingerprint(deal)
    assert financial == entry["financial_fingerprint"] == PRE_D6_5_DIGESTS[mode]
    assert (
        fingerprint_ai(analysis_fingerprint=financial, deal_context=deal.deal_context)
        == entry["ai_fingerprint"]
    )


@pytest.mark.parametrize("mode", MODES)
def test_every_valid_legacy_snapshot_is_still_current(
    legacy: tuple[Path, dict[str, Any]], mode: str
) -> None:
    """The load-bearing one: a stored snapshot is served only while its stored
    fingerprint equals one recomputed from the deal -- plan included. Had the
    empty plan moved a digest, every one of these would silently vanish."""

    db, manifest = legacy
    deal = deals_store.get_deal(manifest["deals"][mode]["id"], db_path=db)

    assert deal.ai_snapshot is not None
    if mode == "lease_level":
        assert deal.one_way_sensitivity_snapshot is not None
        assert deal.two_way_sensitivity_snapshot is not None
    else:
        assert deal.analysis_snapshot is not None
        results = deal.analysis_snapshot if mode == "quick" else deal.analysis_snapshot.results  # type: ignore[union-attr]
        assert type(results.levered_irr_status) is IrrStatus  # type: ignore[union-attr]
        assert results == analyze(mode, BusinessPlan())


def test_an_invalid_legacy_snapshot_is_absent_and_the_deal_still_reanalyzes(
    legacy: tuple[Path, dict[str, Any]],
) -> None:
    db, manifest = legacy
    ids = {mode: manifest["deals"][mode]["id"] for mode in MODES}

    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE deals SET analysis_snapshot_schema_version = 0 WHERE id = ?", (ids["quick"],)
    )
    raw = connection.execute(
        "SELECT analysis_snapshot FROM detailed_deals WHERE id = ?", (ids["detailed"],)
    ).fetchone()[0]
    payload = json.loads(raw)
    del payload["results"]["total_profit"]  # a required D6 field, never fabricated
    connection.execute(
        "UPDATE detailed_deals SET analysis_snapshot = ? WHERE id = ?",
        (json.dumps(payload), ids["detailed"]),
    )
    connection.execute(
        "UPDATE deal_sensitivity_snapshots SET schema_version = 99 "
        "WHERE deal_id = ? AND analysis_kind = 'one_way'",
        (ids["lease_level"],),
    )
    connection.commit()
    connection.close()

    quick = deals_store.get_deal(ids["quick"], db_path=db)
    detailed = deals_store.get_deal(ids["detailed"], db_path=db)
    lease_level = deals_store.get_deal(ids["lease_level"], db_path=db)

    assert quick.analysis_snapshot is None and quick.ai_snapshot is not None
    assert detailed.analysis_snapshot is None and detailed.ai_snapshot is not None
    assert lease_level.one_way_sensitivity_snapshot is None
    assert lease_level.two_way_sensitivity_snapshot is not None

    # The inputs are the D6.2 fixtures, so a fresh analysis is the oracle.
    assert quick.inputs == QUICK
    assert (detailed.terms, detailed.detailed_operating_inputs) == (
        DETAILED_TERMS,
        DETAILED_OPERATING,
    )
    assert lease_level.terms == LL_TERMS
    for mode, deal in (("quick", quick), ("detailed", detailed), ("lease_level", lease_level)):
        assert analyze_deal(deal) == analyze(mode, BusinessPlan())


@pytest.mark.parametrize("mode", MODES)
def test_a_migrated_legacy_deal_takes_a_plan_like_any_other(
    legacy: tuple[Path, dict[str, Any]], mode: str
) -> None:
    db, manifest = legacy
    deal_id = manifest["deals"][mode]["id"]

    planned = update(mode, deal_id, db, business_plan=MATERIAL)

    assert planned.business_plan == MATERIAL
    assert analyze_deal(planned) == analyze(mode, MATERIAL)
    # Same inputs, new plan: every snapshot computed without it is stale.
    assert planned.ai_snapshot is None
    if mode == "lease_level":
        assert planned.one_way_sensitivity_snapshot is None
        assert planned.two_way_sensitivity_snapshot is None
    else:
        assert planned.analysis_snapshot is None
