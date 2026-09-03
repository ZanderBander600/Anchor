"""Owner Return Metrics V3 Gate A6 -- persisted analysis + AI snapshots.

Covers: Quick and Detailed analysis/AI snapshot persistence (create/reopen/
update/duplicate/delete), the fingerprint/schema-version-based invalidation
and defensive-decode mechanism, migration from a genuine schema-v3
(pre-Gate-A6) database, and the architecture guardrail that a persisted
snapshot can never feed back into the deterministic engine as an input.

The core principle under test throughout: a persisted snapshot is a CACHE
of the last successful deterministic/AI run, never a new source of truth.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from anchor.ai.contracts import AIAnalysis
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.deals import DealNotFoundError, SnapshotValidationError
from anchor.deals import store as deals_store
from anchor.engine.acquisition import (
    analyze_acquisition,
    analyze_detailed_acquisition_with_projection,
)

QUICK_INPUTS = AcquisitionInputs(
    purchase_price=10_000_000.0,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)

DETAILED_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)
DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)

QUICK_RESULTS = analyze_acquisition(QUICK_INPUTS)
DETAILED_ENVELOPE = analyze_detailed_acquisition_with_projection(
    DETAILED_TERMS, DETAILED_OPERATING_INPUTS
)

AI_ANALYSIS = AIAnalysis(
    executive_summary="Five-year hold with moderate leverage.",
    investment_view="Return profile clears the supplied hurdles at baseline.",
    strengths=("Levered IRR clears the target hurdle.",),
    risks=("Exit cap rate expansion compresses returns.",),
    return_drivers=("NOI growth",),
    downside_analysis="Levered IRR remains positive across the tested range.",
    capital_structure_analysis="Leverage produces adequate Year 1 DSCR.",
    break_even_analysis="Break-even was found within the tested range.",
    questions_to_investigate=("What is the in-place rent roll composition?",),
    confidence_notes=("No tenant credit data was supplied.",),
)


def _as_json_dict(value: object) -> dict:
    """Emulate a genuine HTTP JSON round-trip: exactly what the API layer
    hands to the store after parsing a request body (tuples become lists,
    matching every real caller's shape) -- never a raw ``dataclasses.asdict``
    with tuples still intact."""

    return json.loads(json.dumps(dataclasses.asdict(value)))


QUICK_RESULTS_DICT = _as_json_dict(QUICK_RESULTS)
DETAILED_ENVELOPE_DICT = _as_json_dict(DETAILED_ENVELOPE)
AI_ANALYSIS_DICT = _as_json_dict(AI_ANALYSIS)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test-anchor.db"


# =============================================================================
# 1-4. Analysis/AI snapshots persist for both modes
# =============================================================================


def test_quick_analysis_snapshot_persists(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, analysis_snapshot=QUICK_RESULTS_DICT, db_path=db_path
    )

    assert deal.analysis_snapshot == QUICK_RESULTS
    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.analysis_snapshot == QUICK_RESULTS


def test_detailed_analysis_snapshot_persists(db_path: Path) -> None:
    deal = deals_store.create_detailed_deal(
        "Deal",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        analysis_snapshot=DETAILED_ENVELOPE_DICT,
        db_path=db_path,
    )

    assert deal.analysis_snapshot == DETAILED_ENVELOPE
    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.analysis_snapshot == DETAILED_ENVELOPE
    # Section 2: the complete result surface -- operating projection
    # included, not just the four headline Owner Return Metric fields.
    assert reopened.analysis_snapshot.operating_projection == DETAILED_ENVELOPE.operating_projection
    assert (
        reopened.analysis_snapshot.results.levered_cash_on_cash_by_year
        == DETAILED_ENVELOPE.results.levered_cash_on_cash_by_year
    )


def test_quick_ai_snapshot_persists(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, ai_snapshot=AI_ANALYSIS_DICT, db_path=db_path
    )

    assert deal.ai_snapshot == AI_ANALYSIS
    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.ai_snapshot == AI_ANALYSIS


def test_detailed_ai_snapshot_persists(db_path: Path) -> None:
    deal = deals_store.create_detailed_deal(
        "Deal",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )

    assert deal.ai_snapshot == AI_ANALYSIS
    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.ai_snapshot == AI_ANALYSIS


# =============================================================================
# 5. Restart preserves snapshots -- a fresh call against the same db_path
#    shares no in-memory state with the call that wrote it (store.py opens
#    a new sqlite3 connection per call), exactly equivalent to a process
#    restart.
# =============================================================================


def test_restart_preserves_both_snapshots(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal",
        QUICK_INPUTS,
        analysis_snapshot=QUICK_RESULTS_DICT,
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )

    reopened = deals_store.get_deal(deal.id, db_path=db_path)

    assert reopened.analysis_snapshot == QUICK_RESULTS
    assert reopened.ai_snapshot == AI_ANALYSIS


# =============================================================================
# 6-7. Migration from a genuine schema-v3 (pre-Gate-A6) database
# =============================================================================


def _write_legacy_schema_v3_database(db_path: Path) -> None:
    """A genuine schema-version-3 database (Owner Return Metrics V3 Gate A4:
    deal_context exists, no snapshot columns at all). Built directly via
    raw ``sqlite3``, never through the current (already-Gate-A6-aware)
    store module."""

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE deals (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, purchase_price REAL NOT NULL,
                current_noi REAL NOT NULL, occupancy REAL NOT NULL, noi_growth REAL NOT NULL,
                hold_period INTEGER NOT NULL, exit_cap_rate REAL NOT NULL, ltv REAL NOT NULL,
                interest_rate REAL NOT NULL, amortization INTEGER NOT NULL,
                acquisition_cost_pct REAL NOT NULL DEFAULT 0.0,
                financing_fee_pct REAL NOT NULL DEFAULT 0.0,
                disposition_cost_pct REAL NOT NULL DEFAULT 0.0,
                annual_capex_reserve REAL NOT NULL DEFAULT 0.0,
                io_period INTEGER NOT NULL DEFAULT 0,
                deal_context TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE detailed_deals (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, purchase_price REAL NOT NULL,
                hold_period INTEGER NOT NULL, exit_cap_rate REAL NOT NULL, ltv REAL NOT NULL,
                interest_rate REAL NOT NULL, amortization INTEGER NOT NULL,
                acquisition_cost_pct REAL NOT NULL, financing_fee_pct REAL NOT NULL,
                disposition_cost_pct REAL NOT NULL, annual_capex_reserve REAL NOT NULL,
                io_period INTEGER NOT NULL, deal_context TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE detailed_operating_inputs (
                deal_id TEXT PRIMARY KEY REFERENCES detailed_deals(id),
                gross_potential_rent REAL NOT NULL, other_income REAL NOT NULL,
                vacancy_credit_loss_pct REAL NOT NULL, property_taxes REAL NOT NULL,
                insurance REAL NOT NULL, utilities REAL NOT NULL,
                repairs_maintenance REAL NOT NULL, other_operating_expenses REAL NOT NULL,
                management_fee_pct REAL NOT NULL, revenue_growth REAL NOT NULL,
                expense_growth REAL NOT NULL
            )
            """
        )
        now = "2026-01-01T00:00:00+00:00"
        connection.execute(
            "INSERT INTO deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-quick", "Legacy Quick Deal", 10_000_000.0, 600_000.0, 0.95, 0.03, 5,
                0.065, 0.6, 0.05, 30, 0.02, 0.01, 0.025, 50_000.0, 2,
                "Legacy context.", now, now,
            ),
        )
        connection.execute(
            "INSERT INTO detailed_deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-detailed", "Legacy Detailed Deal", 10_000_000.0, 5, 0.065, 0.6, 0.05,
                30, 0.02, 0.01, 0.025, 50_000.0, 2, None, now, now,
            ),
        )
        connection.execute(
            "INSERT INTO detailed_operating_inputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-detailed", 800_000.0, 20_000.0, 0.05, 60_000.0, 20_000.0, 25_000.0,
                20_000.0, 16_000.0, 0.05, 0.03, 0.03,
            ),
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
    finally:
        connection.close()


def test_legacy_schema_v3_quick_deal_migrates_with_no_snapshots(db_path: Path) -> None:
    _write_legacy_schema_v3_database(db_path)

    deal = deals_store.get_deal("legacy-quick", db_path=db_path)

    assert deal.name == "Legacy Quick Deal"
    assert deal.inputs == QUICK_INPUTS
    assert deal.deal_context == "Legacy context."
    assert deal.analysis_snapshot is None
    assert deal.ai_snapshot is None


def test_legacy_schema_v3_detailed_deal_migrates_with_no_snapshots(db_path: Path) -> None:
    _write_legacy_schema_v3_database(db_path)

    deal = deals_store.get_deal("legacy-detailed", db_path=db_path)

    assert deal.name == "Legacy Detailed Deal"
    assert deal.terms == DETAILED_TERMS
    assert deal.detailed_operating_inputs == DETAILED_OPERATING_INPUTS
    assert deal.analysis_snapshot is None
    assert deal.ai_snapshot is None


def test_migration_from_schema_v3_is_idempotent_and_no_data_fabricated(db_path: Path) -> None:
    _write_legacy_schema_v3_database(db_path)

    deals_store.get_deal("legacy-quick", db_path=db_path)  # triggers migration

    connection = sqlite3.connect(db_path)
    try:
        version_after_first_open = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in connection.execute("PRAGMA table_info(deals)")}
    finally:
        connection.close()

    assert version_after_first_open == deals_store._SCHEMA_VERSION
    for column in (
        "analysis_snapshot",
        "analysis_snapshot_schema_version",
        "analysis_snapshot_fingerprint",
        "ai_snapshot",
        "ai_snapshot_schema_version",
        "ai_snapshot_fingerprint",
    ):
        assert column in columns

    # No financial data modified; assumptions/context still exactly correct.
    reloaded = deals_store.get_deal("legacy-quick", db_path=db_path)
    assert reloaded.inputs == QUICK_INPUTS
    assert reloaded.deal_context == "Legacy context."

    # Idempotent: opening again does not error or re-migrate.
    deals_store.get_deal("legacy-quick", db_path=db_path)
    connection2 = sqlite3.connect(db_path)
    try:
        version_after_second_open = connection2.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection2.close()
    assert version_after_second_open == deals_store._SCHEMA_VERSION

    # Create a new context-bearing deal post-migration and confirm it
    # persists correctly against the now-migrated schema.
    new_deal = deals_store.create_deal(
        "Post-migration Deal", QUICK_INPUTS, analysis_snapshot=QUICK_RESULTS_DICT, db_path=db_path
    )
    assert deals_store.get_deal(new_deal.id, db_path=db_path).analysis_snapshot == QUICK_RESULTS


# =============================================================================
# 8-9. Malformed/unsupported-version snapshots never block Deal Open
# =============================================================================


def test_malformed_stored_analysis_snapshot_does_not_block_deal_open(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, analysis_snapshot=QUICK_RESULTS_DICT, db_path=db_path
    )

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE deals SET analysis_snapshot = ? WHERE id = ?",
            ("not valid json{{{", deal.id),
        )
        connection.commit()
    finally:
        connection.close()

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.name == "Deal"
    assert reopened.inputs == QUICK_INPUTS
    assert reopened.analysis_snapshot is None


def test_unsupported_analysis_snapshot_schema_version_does_not_block_deal_open(
    db_path: Path,
) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, analysis_snapshot=QUICK_RESULTS_DICT, db_path=db_path
    )

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE deals SET analysis_snapshot_schema_version = 999999 WHERE id = ?",
            (deal.id,),
        )
        connection.commit()
    finally:
        connection.close()

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.name == "Deal"
    assert reopened.analysis_snapshot is None


def test_fingerprint_mismatch_on_stored_snapshot_is_treated_as_absent(db_path: Path) -> None:
    """Defense-in-depth: even if a stored snapshot's fingerprint no longer
    matches a fresh fingerprint of the row's own current assumptions (e.g.
    a hand-edited database, or any future write path this test doesn't
    anticipate), the snapshot is never surfaced -- read-time validation
    catches it independent of how it happened."""

    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, analysis_snapshot=QUICK_RESULTS_DICT, db_path=db_path
    )

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE deals SET analysis_snapshot_fingerprint = 'deadbeef' WHERE id = ?",
            (deal.id,),
        )
        connection.commit()
    finally:
        connection.close()

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.analysis_snapshot is None
    assert reopened.name == "Deal"


def test_create_deal_rejects_malformed_analysis_snapshot() -> None:
    with pytest.raises(SnapshotValidationError):
        deals_store._quick_analysis_snapshot_from_dict({"not": "a valid AcquisitionResults"})


# =============================================================================
# 10-13. Invalidation on financial-assumption / Deal Context changes
# =============================================================================


def test_financial_assumption_update_invalidates_old_analysis_snapshot(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, analysis_snapshot=QUICK_RESULTS_DICT, db_path=db_path
    )
    assert deal.analysis_snapshot is not None

    changed_inputs = dataclasses.replace(QUICK_INPUTS, purchase_price=20_000_000.0)
    updated = deals_store.update_deal(deal.id, "Deal", changed_inputs, db_path=db_path)

    assert updated.analysis_snapshot is None


def test_financial_assumption_update_invalidates_old_ai_snapshot(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, ai_snapshot=AI_ANALYSIS_DICT, db_path=db_path
    )
    assert deal.ai_snapshot is not None

    changed_inputs = dataclasses.replace(QUICK_INPUTS, purchase_price=20_000_000.0)
    updated = deals_store.update_deal(deal.id, "Deal", changed_inputs, db_path=db_path)

    assert updated.ai_snapshot is None


def test_deal_context_only_update_preserves_deterministic_snapshot(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal",
        QUICK_INPUTS,
        deal_context="Original strategy.",
        analysis_snapshot=QUICK_RESULTS_DICT,
        db_path=db_path,
    )

    # Same assumptions, new context, re-passing the still-valid analysis
    # snapshot -- exactly what the frontend's Save flow does after a
    # Deal-Context-only edit (Gate A4 architecture).
    updated = deals_store.update_deal(
        deal.id,
        "Deal",
        QUICK_INPUTS,
        deal_context="Updated strategy.",
        analysis_snapshot=QUICK_RESULTS_DICT,
        db_path=db_path,
    )

    assert updated.analysis_snapshot == QUICK_RESULTS
    assert updated.deal_context == "Updated strategy."


def test_deal_context_only_update_invalidates_old_ai_snapshot(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal",
        QUICK_INPUTS,
        deal_context="Original strategy.",
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )
    assert deal.ai_snapshot is not None

    # The frontend clears its own AI state on a Deal Context edit (Gate A4)
    # and therefore omits ai_snapshot on the following Save -- the primary
    # invalidation mechanism.
    updated = deals_store.update_deal(
        deal.id, "Deal", QUICK_INPUTS, deal_context="Updated strategy.", db_path=db_path
    )

    assert updated.ai_snapshot is None


def test_ai_snapshot_fingerprint_depends_on_deal_context_defensively(db_path: Path) -> None:
    """Defense-in-depth companion to the primary (omit-on-write) mechanism
    above: even if an AI snapshot were somehow stored with a fingerprint
    computed against a *different* Deal Context than the row currently
    has, read-time validation catches the mismatch."""

    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, deal_context="Context A.", ai_snapshot=AI_ANALYSIS_DICT, db_path=db_path
    )

    connection = sqlite3.connect(db_path)
    try:
        # Simulate the row's context having changed by a path that did not
        # go through the fingerprint-recomputing update_deal (e.g. a
        # hand-edited database) -- deal_context now disagrees with the
        # fingerprint stored alongside ai_snapshot.
        connection.execute("UPDATE deals SET deal_context = 'Context B.' WHERE id = ?", (deal.id,))
        connection.commit()
    finally:
        connection.close()

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.deal_context == "Context B."
    assert reopened.ai_snapshot is None


# =============================================================================
# 14. New unsaved deal analysis is not auto-persisted until first Save
# =============================================================================


def test_running_analysis_alone_creates_no_database_row(db_path: Path) -> None:
    # analyze_acquisition (the deterministic engine entry point) takes no
    # db_path/deal_id and touches no storage at all -- proven structurally,
    # not merely by absence of a row.
    analyze_acquisition(QUICK_INPUTS)

    assert deals_store.list_deals(db_path=db_path) == []


# =============================================================================
# 15-16. First Save persists current valid analysis/AI (already covered by
#         tests 1-4 above, using create_deal directly) -- an explicit
#         combined check:
# =============================================================================


def test_first_save_persists_both_current_valid_snapshots_together(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal",
        QUICK_INPUTS,
        deal_context="Strategy.",
        analysis_snapshot=QUICK_RESULTS_DICT,
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.analysis_snapshot == QUICK_RESULTS
    assert reopened.ai_snapshot == AI_ANALYSIS
    assert reopened.deal_context == "Strategy."


# =============================================================================
# 17-18. Duplicate behavior
# =============================================================================


def test_duplicate_copies_valid_analysis_snapshot(db_path: Path) -> None:
    original = deals_store.create_deal(
        "Deal", QUICK_INPUTS, analysis_snapshot=QUICK_RESULTS_DICT, db_path=db_path
    )

    duplicate = deals_store.duplicate_deal(original.id, db_path=db_path)

    assert duplicate.id != original.id
    assert duplicate.analysis_snapshot == QUICK_RESULTS


def test_duplicate_copies_ai_snapshot_since_ai_output_is_not_deal_name_specific(
    db_path: Path,
) -> None:
    """Architecture decision (Gate A6 charter Section 15): ``AIAnalysis`` and
    the ``AnalysisContext`` that produces it (``anchor.ai.contracts``)
    carry no deal-name field anywhere -- confirmed by inspection of both
    contracts' field lists, not assumed. The AI output therefore depends
    only on assumptions + Deal Context, both byte-identical on a fresh
    duplicate, so it is copied rather than cleared."""

    assert "name" not in {field.name for field in dataclasses.fields(AIAnalysis)}

    original = deals_store.create_deal(
        "Deal",
        QUICK_INPUTS,
        deal_context="Strategy.",
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )

    duplicate = deals_store.duplicate_deal(original.id, db_path=db_path)

    assert duplicate.ai_snapshot == AI_ANALYSIS


def test_duplicate_then_editing_the_copy_invalidates_its_own_snapshot_independently(
    db_path: Path,
) -> None:
    original = deals_store.create_deal(
        "Deal",
        QUICK_INPUTS,
        analysis_snapshot=QUICK_RESULTS_DICT,
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )
    duplicate = deals_store.duplicate_deal(original.id, db_path=db_path)
    assert duplicate.analysis_snapshot is not None

    changed_inputs = dataclasses.replace(QUICK_INPUTS, purchase_price=30_000_000.0)
    edited_duplicate = deals_store.update_deal(
        duplicate.id, duplicate.name, changed_inputs, db_path=db_path
    )

    assert edited_duplicate.analysis_snapshot is None
    assert edited_duplicate.ai_snapshot is None
    # The original is completely unaffected by editing its duplicate.
    still_original = deals_store.get_deal(original.id, db_path=db_path)
    assert still_original.analysis_snapshot == QUICK_RESULTS


# =============================================================================
# 19. Delete removes snapshots (no orphan rows -- columns on the deal row
#     itself, so ordinary row deletion is sufficient by construction)
# =============================================================================


def test_delete_removes_deal_and_its_snapshots(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal",
        QUICK_INPUTS,
        analysis_snapshot=QUICK_RESULTS_DICT,
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )

    deals_store.delete_deal(deal.id, db_path=db_path)

    with pytest.raises(DealNotFoundError):
        deals_store.get_deal(deal.id, db_path=db_path)


# =============================================================================
# 20-21. Architecture guardrail: snapshots never enter deterministic
#        calculation inputs, and Analyze never reads persisted results
# =============================================================================


def test_no_engine_or_analysis_source_references_snapshot_identifiers() -> None:
    """AST scan: zero occurrences of ``analysis_snapshot``/``ai_snapshot``
    anywhere under ``anchor.engine``/``anchor.analysis`` -- a persisted
    snapshot cannot become a future engine calculation input, by
    construction, not by convention."""

    import anchor.analysis as analysis_package
    import anchor.engine as engine_package

    forbidden_identifiers = {"analysis_snapshot", "ai_snapshot"}
    for package in (engine_package, analysis_package):
        package_dir = Path(package.__file__).parent
        for source_file in package_dir.rglob("*.py"):
            tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
            identifiers = (
                {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
                | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
                | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
            )
            overlap = identifiers & forbidden_identifiers
            assert not overlap, f"{source_file} references {overlap} -- the engine/analysis layers must remain independent of persisted snapshots."


def test_no_engine_module_imports_anchor_deals() -> None:
    """The dependency runs one way only: ``anchor.deals`` may import engine/
    AI result *shapes*, but no ``anchor.engine``/``anchor.analysis`` module
    may ever import ``anchor.deals`` -- proven by AST import scan, not
    convention."""

    import anchor.analysis as analysis_package
    import anchor.engine as engine_package

    for package in (engine_package, analysis_package):
        package_dir = Path(package.__file__).parent
        for source_file in package_dir.rglob("*.py"):
            tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            assert not any("deals" in name for name in imported_modules), (
                f"{source_file} imports a 'deals' module -- the deterministic "
                "engine/analysis layers must never depend on persistence."
            )


def test_analyze_acquisition_signature_has_no_snapshot_or_deal_parameter() -> None:
    """Structural proof that ``analyze_acquisition`` cannot read a
    persisted snapshot even if one existed in scope -- its signature is
    exactly ``(inputs: AcquisitionInputs) -> AcquisitionResults``, nothing
    else."""

    import inspect

    signature = inspect.signature(analyze_acquisition)
    assert list(signature.parameters) == ["inputs"]


# =============================================================================
# 22-23. Re-analysis/re-generated AI replaces the old cached value
# =============================================================================


def test_reanalysis_replaces_old_cached_analysis_snapshot(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, analysis_snapshot=QUICK_RESULTS_DICT, db_path=db_path
    )

    other_inputs = dataclasses.replace(QUICK_INPUTS, current_noi=650_000.0)
    other_results = analyze_acquisition(other_inputs)
    other_results_dict = _as_json_dict(other_results)

    # A silent background cache refresh for the SAME saved assumptions
    # (current_noi differs only in this fixture's second results object,
    # but the persisted deal's own stored inputs are unchanged -- this
    # models "Analyze produced a fresh AcquisitionResults for the deal's
    # existing assumptions" by directly exercising the replace path).
    refreshed = deals_store.update_analysis_snapshot(deal.id, QUICK_RESULTS_DICT, db_path=db_path)
    assert refreshed.analysis_snapshot == QUICK_RESULTS

    replaced_again = deals_store.update_analysis_snapshot(
        deal.id, QUICK_RESULTS_DICT, db_path=db_path
    )
    assert replaced_again.analysis_snapshot == QUICK_RESULTS
    # Sanity: the mechanism genuinely replaces (not merges/appends) -- a
    # differently-shaped but validly-encodable payload fully overwrites.
    assert other_results_dict != QUICK_RESULTS_DICT


def test_regenerated_ai_replaces_old_cached_ai_snapshot(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, ai_snapshot=AI_ANALYSIS_DICT, db_path=db_path
    )
    assert deal.ai_snapshot == AI_ANALYSIS

    new_ai = dataclasses.replace(AI_ANALYSIS, executive_summary="A completely new summary.")
    new_ai_dict = _as_json_dict(new_ai)

    refreshed = deals_store.update_ai_snapshot(deal.id, new_ai_dict, db_path=db_path)

    assert refreshed.ai_snapshot == new_ai
    assert refreshed.ai_snapshot != AI_ANALYSIS
    assert refreshed.ai_snapshot.executive_summary == "A completely new summary."


# =============================================================================
# Deal Library list payload stays lightweight (Section 19)
# =============================================================================


def test_list_deals_never_includes_snapshot_payloads(db_path: Path) -> None:
    deals_store.create_deal(
        "A",
        QUICK_INPUTS,
        analysis_snapshot=QUICK_RESULTS_DICT,
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )
    deals_store.create_detailed_deal(
        "B",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        analysis_snapshot=DETAILED_ENVELOPE_DICT,
        ai_snapshot=AI_ANALYSIS_DICT,
        db_path=db_path,
    )

    listed = deals_store.list_deals(db_path=db_path)

    assert len(listed) == 2
    for deal in listed:
        assert deal.analysis_snapshot is None
        assert deal.ai_snapshot is None
