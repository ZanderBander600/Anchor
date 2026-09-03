"""Detailed Operating Model V2.1 Gate 5b -- two-table Quick/Detailed
persistence split.

Covers the design confirmed for this gate: ``deals`` (Quick) is completely
untouched -- schema, constraints, and existing rows -- by the addition of
``detailed_deals``/``detailed_operating_inputs`` (Detailed), both created
purely additively (``CREATE TABLE IF NOT EXISTS``, no ``ALTER`` of any
existing column). One domain-level ``Deal`` abstraction dispatches by
``operating_mode`` across the two storage paths.

Mirrors ``tests/test_deals_store_v2_migration.py``'s existing conventions
(a hand-built ``sqlite3`` fixture database, ``_SCHEMA_VERSION`` imported
directly from the store module) for consistency with the established
migration-test style.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs, OperatingMode
from anchor.deals import DealNotFoundError
from anchor.deals.store import (
    _SCHEMA_VERSION,
    create_deal,
    create_detailed_deal,
    delete_deal,
    duplicate_deal,
    get_deal,
    list_deals,
    update_deal,
    update_detailed_deal,
)
from anchor.engine import analyze_acquisition, analyze_detailed_acquisition

QUICK_INPUTS = AcquisitionInputs(
    purchase_price=50_000_000.0,
    current_noi=2_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.055,
    ltv=0.65,
    interest_rate=0.0525,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)

GOLDEN_TERMS = AcquisitionTerms(
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

GOLDEN_DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
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

# Deliberately awkward binary fractions, mirroring test_deals_store.py's
# AWKWARD_INPUTS convention -- values hostile to any lossy numeric path,
# which must still round-trip exactly through IEEE 754 double storage.
AWKWARD_TERMS = AcquisitionTerms(
    purchase_price=12_345_678.913571113,
    hold_period=7,
    exit_cap_rate=0.05499999999999999,
    ltv=0.6666666666666666,
    interest_rate=0.052500000000001,
    amortization=25,
    acquisition_cost_pct=0.019999999999999,
    financing_fee_pct=0.010000000000002,
    disposition_cost_pct=0.024999999999998,
    annual_capex_reserve=49_999.99999999991,
    io_period=3,
)

AWKWARD_DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=799_999.9999999998,
    other_income=19_999.999999999996,
    vacancy_credit_loss_pct=0.050000000000002,
    property_taxes=59_999.99999999989,
    insurance=19_999.999999999985,
    utilities=24_999.999999999996,
    repairs_maintenance=19_999.999999999992,
    other_operating_expenses=15_999.999999999998,
    management_fee_pct=0.049999999999997,
    revenue_growth=0.030000000000004,
    expense_growth=0.029999999999996,
)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test-anchor.db"


def _raw_column_names(db_path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    finally:
        connection.close()


def _raw_table_names(db_path: Path) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        connection.close()


def _raw_user_version(db_path: Path) -> int:
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


# =============================================================================
# The ``deals`` table is structurally untouched by this gate (Gate 5b),
# plus Owner Return Metrics V3 Gate A4's one later, deliberate addition
# =============================================================================

_QUICK_ONLY_COLUMNS = frozenset(
    (
        "id",
        "name",
        "purchase_price",
        "current_noi",
        "occupancy",
        "noi_growth",
        "hold_period",
        "exit_cap_rate",
        "ltv",
        "interest_rate",
        "amortization",
        "acquisition_cost_pct",
        "financing_fee_pct",
        "disposition_cost_pct",
        "annual_capex_reserve",
        "io_period",
        # Owner Return Metrics V3 Gate A4: one nullable deal-metadata column,
        # added after this test module was written for Gate 5b.
        "deal_context",
        # Owner Return Metrics V3 Gate A6: six nullable cached-snapshot
        # columns, added later still -- the only other legitimate additions
        # to this otherwise-frozen list since Gate 5b.
        "analysis_snapshot",
        "analysis_snapshot_schema_version",
        "analysis_snapshot_fingerprint",
        "ai_snapshot",
        "ai_snapshot_schema_version",
        "ai_snapshot_fingerprint",
        "created_at",
        "updated_at",
    )
)


def test_fresh_database_deals_table_schema_is_exactly_the_pre_gate_5b_shape(
    db_path: Path,
) -> None:
    """No column added to, removed from, or altered on ``deals`` by Gate 5b
    itself -- confirms the 'structurally untouched by Gate 5b' requirement
    directly against the live schema, not just by absence of a diff. The one
    column present beyond the original fourteen Quick assumptions
    (``deal_context``) was added later, deliberately, by Owner Return
    Metrics V3 Gate A4 -- see that column's comment in ``_QUICK_ONLY_COLUMNS``
    above."""

    create_deal("Deal", QUICK_INPUTS, db_path=db_path)

    assert _raw_column_names(db_path, "deals") == _QUICK_ONLY_COLUMNS


def test_fresh_database_contains_both_new_detailed_tables(db_path: Path) -> None:
    create_deal("Deal", QUICK_INPUTS, db_path=db_path)

    assert {"deals", "detailed_deals", "detailed_operating_inputs"} <= _raw_table_names(
        db_path
    )


def _write_legacy_v1_database(db_path: Path, *, deal_id: str = "quick-1") -> None:
    """Build a genuine pre-Gate-5b (schema version 1: fourteen Quick
    columns, no Detailed tables) database directly via raw ``sqlite3`` --
    never through the current (already-Gate-5b-aware) store module."""

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE deals (
                id                    TEXT PRIMARY KEY,
                name                  TEXT NOT NULL,
                purchase_price        REAL NOT NULL,
                current_noi           REAL NOT NULL,
                occupancy             REAL NOT NULL,
                noi_growth            REAL NOT NULL,
                hold_period           INTEGER NOT NULL,
                exit_cap_rate         REAL NOT NULL,
                ltv                   REAL NOT NULL,
                interest_rate         REAL NOT NULL,
                amortization          INTEGER NOT NULL,
                acquisition_cost_pct  REAL NOT NULL DEFAULT 0.0,
                financing_fee_pct     REAL NOT NULL DEFAULT 0.0,
                disposition_cost_pct  REAL NOT NULL DEFAULT 0.0,
                annual_capex_reserve  REAL NOT NULL DEFAULT 0.0,
                io_period             INTEGER NOT NULL DEFAULT 0,
                created_at            TEXT NOT NULL,
                updated_at            TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO deals (
                id, name, purchase_price, current_noi, occupancy, noi_growth,
                hold_period, exit_cap_rate, ltv, interest_rate, amortization,
                acquisition_cost_pct, financing_fee_pct, disposition_cost_pct,
                annual_capex_reserve, io_period, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deal_id,
                "Existing Quick Deal",
                QUICK_INPUTS.purchase_price,
                QUICK_INPUTS.current_noi,
                QUICK_INPUTS.occupancy,
                QUICK_INPUTS.noi_growth,
                QUICK_INPUTS.hold_period,
                QUICK_INPUTS.exit_cap_rate,
                QUICK_INPUTS.ltv,
                QUICK_INPUTS.interest_rate,
                QUICK_INPUTS.amortization,
                QUICK_INPUTS.acquisition_cost_pct,
                QUICK_INPUTS.financing_fee_pct,
                QUICK_INPUTS.disposition_cost_pct,
                QUICK_INPUTS.annual_capex_reserve,
                QUICK_INPUTS.io_period,
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:00:00+00:00",
            ),
        )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    finally:
        connection.close()

    # Confirm the fixture really is version 1 with no Detailed tables yet.
    assert _raw_user_version(db_path) == 1
    assert "detailed_deals" not in _raw_table_names(db_path)


# =============================================================================
# 1. Existing Quick database migrates without modifying Quick rows
# =============================================================================


def test_existing_quick_database_migrates_without_modifying_quick_rows(
    db_path: Path,
) -> None:
    _write_legacy_v1_database(db_path)

    # Any store call opens a connection, which runs the migration.
    deal = get_deal("quick-1", db_path=db_path)

    assert deal.id == "quick-1"
    assert deal.name == "Existing Quick Deal"
    assert deal.operating_mode is OperatingMode.QUICK
    assert deal.inputs == QUICK_INPUTS
    assert deal.created_at.isoformat() == "2020-01-01T00:00:00+00:00"
    assert deal.updated_at.isoformat() == "2020-01-01T00:00:00+00:00"

    # Schema matches the current authoritative shape exactly -- the
    # original fourteen Quick columns unchanged, plus Gate A4's later
    # deal_context addition backfilled to NULL by the migration.
    assert _raw_column_names(db_path, "deals") == _QUICK_ONLY_COLUMNS
    assert _raw_user_version(db_path) == _SCHEMA_VERSION


def test_migrating_a_quick_database_adds_the_two_detailed_tables_but_no_rows(
    db_path: Path,
) -> None:
    _write_legacy_v1_database(db_path)

    get_deal("quick-1", db_path=db_path)

    assert {"detailed_deals", "detailed_operating_inputs"} <= _raw_table_names(db_path)
    connection = sqlite3.connect(db_path)
    try:
        detailed_deal_count = connection.execute(
            "SELECT COUNT(*) FROM detailed_deals"
        ).fetchone()[0]
        detailed_operating_count = connection.execute(
            "SELECT COUNT(*) FROM detailed_operating_inputs"
        ).fetchone()[0]
    finally:
        connection.close()
    assert detailed_deal_count == 0
    assert detailed_operating_count == 0


# =============================================================================
# 2. Existing Quick deal economics remain unchanged
# =============================================================================


def test_existing_quick_deal_economics_are_unchanged_after_migration(
    db_path: Path,
) -> None:
    _write_legacy_v1_database(db_path)

    deal = get_deal("quick-1", db_path=db_path)
    reopened_result = analyze_acquisition(deal.inputs)
    direct_result = analyze_acquisition(QUICK_INPUTS)

    assert reopened_result == direct_result


# =============================================================================
# 3. A Detailed deal persists without any row in the Quick deals table
# =============================================================================


def test_detailed_deal_creates_no_row_in_the_quick_deals_table(db_path: Path) -> None:
    created = create_detailed_deal(
        "Detailed Deal",
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        db_path=db_path,
    )

    connection = sqlite3.connect(db_path)
    try:
        quick_row = connection.execute(
            "SELECT * FROM deals WHERE id = ?", (created.id,)
        ).fetchone()
    finally:
        connection.close()

    assert quick_row is None


def test_detailed_deal_has_no_fabricated_quick_only_fields() -> None:
    deal = create_detailed_deal(
        "Detailed Deal", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert deal.operating_mode is OperatingMode.DETAILED
    assert deal.inputs is None


# =============================================================================
# 4/5. AcquisitionTerms and DetailedOperatingInputs round-trip exactly
# =============================================================================


def test_detailed_terms_round_trip_exactly(db_path: Path) -> None:
    created = create_detailed_deal(
        "Awkward Detailed Deal",
        AWKWARD_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        db_path=db_path,
    )
    fetched = get_deal(created.id, db_path=db_path)

    assert fetched.terms == AWKWARD_TERMS
    assert fetched.terms.purchase_price == AWKWARD_TERMS.purchase_price
    assert fetched.terms.hold_period == AWKWARD_TERMS.hold_period
    assert fetched.terms.exit_cap_rate == AWKWARD_TERMS.exit_cap_rate
    assert fetched.terms.ltv == AWKWARD_TERMS.ltv
    assert fetched.terms.interest_rate == AWKWARD_TERMS.interest_rate
    assert fetched.terms.amortization == AWKWARD_TERMS.amortization
    assert fetched.terms.acquisition_cost_pct == AWKWARD_TERMS.acquisition_cost_pct
    assert fetched.terms.financing_fee_pct == AWKWARD_TERMS.financing_fee_pct
    assert fetched.terms.disposition_cost_pct == AWKWARD_TERMS.disposition_cost_pct
    assert fetched.terms.annual_capex_reserve == AWKWARD_TERMS.annual_capex_reserve
    assert fetched.terms.io_period == AWKWARD_TERMS.io_period
    assert isinstance(fetched.terms.hold_period, int)
    assert isinstance(fetched.terms.io_period, int)


def test_detailed_operating_inputs_round_trip_exactly(db_path: Path) -> None:
    created = create_detailed_deal(
        "Awkward Detailed Deal",
        GOLDEN_TERMS,
        AWKWARD_DETAILED_OPERATING_INPUTS,
        db_path=db_path,
    )
    fetched = get_deal(created.id, db_path=db_path)

    assert fetched.detailed_operating_inputs == AWKWARD_DETAILED_OPERATING_INPUTS
    assert (
        fetched.detailed_operating_inputs.gross_potential_rent
        == AWKWARD_DETAILED_OPERATING_INPUTS.gross_potential_rent
    )
    assert (
        fetched.detailed_operating_inputs.other_income
        == AWKWARD_DETAILED_OPERATING_INPUTS.other_income
    )
    assert (
        fetched.detailed_operating_inputs.vacancy_credit_loss_pct
        == AWKWARD_DETAILED_OPERATING_INPUTS.vacancy_credit_loss_pct
    )
    assert (
        fetched.detailed_operating_inputs.management_fee_pct
        == AWKWARD_DETAILED_OPERATING_INPUTS.management_fee_pct
    )
    assert (
        fetched.detailed_operating_inputs.revenue_growth
        == AWKWARD_DETAILED_OPERATING_INPUTS.revenue_growth
    )
    assert (
        fetched.detailed_operating_inputs.expense_growth
        == AWKWARD_DETAILED_OPERATING_INPUTS.expense_growth
    )


def test_detailed_bridge_case_reopened_from_storage_reconciles_to_the_v2_golden_case(
    db_path: Path,
) -> None:
    """An end-to-end proof that storage round-tripping doesn't perturb the
    economics: creating, fetching, and analyzing the Detailed golden case
    through the store reproduces the same result as calling
    analyze_detailed_acquisition directly."""

    created = create_detailed_deal(
        "Golden Detailed Deal",
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        db_path=db_path,
    )
    fetched = get_deal(created.id, db_path=db_path)

    reopened_result = analyze_detailed_acquisition(
        fetched.terms, fetched.detailed_operating_inputs
    )
    direct_result = analyze_detailed_acquisition(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert reopened_result == direct_result
    assert reopened_result.loan_amount == pytest.approx(6_000_000.0)
    assert reopened_result.headline_dscr == pytest.approx(2.0, abs=1e-5)


# =============================================================================
# 6. list/get/create/update/duplicate/delete work across both modes
# =============================================================================


def test_list_deals_returns_both_modes_most_recently_updated_first(
    db_path: Path,
) -> None:
    quick_deal = create_deal("Quick Deal", QUICK_INPUTS, db_path=db_path)
    detailed_deal = create_detailed_deal(
        "Detailed Deal",
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        db_path=db_path,
    )
    # Force detailed_deal to be the most recently updated, deterministically.
    detailed_deal = update_detailed_deal(
        detailed_deal.id,
        "Detailed Deal (edited)",
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        db_path=db_path,
    )

    deals = list_deals(db_path=db_path)

    assert [deal.id for deal in deals] == [detailed_deal.id, quick_deal.id]
    assert {deal.operating_mode for deal in deals} == {
        OperatingMode.QUICK,
        OperatingMode.DETAILED,
    }


def test_get_deal_dispatches_to_the_correct_mode(db_path: Path) -> None:
    quick_deal = create_deal("Quick Deal", QUICK_INPUTS, db_path=db_path)
    detailed_deal = create_detailed_deal(
        "Detailed Deal",
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        db_path=db_path,
    )

    fetched_quick = get_deal(quick_deal.id, db_path=db_path)
    fetched_detailed = get_deal(detailed_deal.id, db_path=db_path)

    assert fetched_quick.operating_mode is OperatingMode.QUICK
    assert fetched_quick.inputs == QUICK_INPUTS
    assert fetched_detailed.operating_mode is OperatingMode.DETAILED
    assert fetched_detailed.terms == GOLDEN_TERMS
    assert fetched_detailed.detailed_operating_inputs == GOLDEN_DETAILED_OPERATING_INPUTS


def test_get_deal_raises_not_found_for_an_id_in_neither_table(db_path: Path) -> None:
    create_deal("Quick Deal", QUICK_INPUTS, db_path=db_path)

    with pytest.raises(DealNotFoundError):
        get_deal("does-not-exist", db_path=db_path)


def test_update_detailed_deal_overwrites_terms_and_operating_inputs(
    db_path: Path,
) -> None:
    created = create_detailed_deal(
        "Original Name", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    updated = update_detailed_deal(
        created.id,
        "Renamed Detailed Deal",
        AWKWARD_TERMS,
        AWKWARD_DETAILED_OPERATING_INPUTS,
        db_path=db_path,
    )

    assert updated.id == created.id
    assert updated.name == "Renamed Detailed Deal"
    assert updated.terms == AWKWARD_TERMS
    assert updated.detailed_operating_inputs == AWKWARD_DETAILED_OPERATING_INPUTS
    assert updated.created_at == created.created_at
    assert updated.updated_at >= created.updated_at


def test_update_detailed_deal_raises_not_found_for_unknown_id(db_path: Path) -> None:
    with pytest.raises(DealNotFoundError):
        update_detailed_deal(
            "does-not-exist",
            "Name",
            GOLDEN_TERMS,
            GOLDEN_DETAILED_OPERATING_INPUTS,
            db_path=db_path,
        )


def test_update_deal_does_not_find_a_detailed_only_id(db_path: Path) -> None:
    """A Quick-only updater called against a Detailed deal's id correctly
    reports it as not found -- that id is genuinely absent from ``deals``,
    never silently treated as a match."""

    detailed_deal = create_detailed_deal(
        "Detailed Deal", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    with pytest.raises(DealNotFoundError):
        update_deal(detailed_deal.id, "New Name", QUICK_INPUTS, db_path=db_path)


def test_duplicate_deal_preserves_operating_mode_for_quick(db_path: Path) -> None:
    original = create_deal("111 Main St", QUICK_INPUTS, db_path=db_path)

    copy = duplicate_deal(original.id, db_path=db_path)

    assert copy.id != original.id
    assert copy.operating_mode is OperatingMode.QUICK
    assert copy.inputs == QUICK_INPUTS
    assert copy.name == "111 Main St (Copy)"


def test_duplicate_deal_preserves_operating_mode_for_detailed(db_path: Path) -> None:
    original = create_detailed_deal(
        "222 Oak Ave", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    copy = duplicate_deal(original.id, db_path=db_path)

    assert copy.id != original.id
    assert copy.operating_mode is OperatingMode.DETAILED
    assert copy.terms == GOLDEN_TERMS
    assert copy.detailed_operating_inputs == GOLDEN_DETAILED_OPERATING_INPUTS
    assert copy.name == "222 Oak Ave (Copy)"

    # The duplicate must also create no row in the Quick deals table.
    connection = sqlite3.connect(db_path)
    try:
        quick_row = connection.execute(
            "SELECT * FROM deals WHERE id = ?", (copy.id,)
        ).fetchone()
    finally:
        connection.close()
    assert quick_row is None


def test_duplicate_deal_does_not_mutate_the_original_detailed_deal(
    db_path: Path,
) -> None:
    original = create_detailed_deal(
        "Detailed Deal", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    duplicate_deal(original.id, name="A Copy", db_path=db_path)

    unchanged = get_deal(original.id, db_path=db_path)
    assert unchanged == original


def test_delete_deal_removes_a_quick_deal(db_path: Path) -> None:
    created = create_deal("Deal", QUICK_INPUTS, db_path=db_path)

    delete_deal(created.id, db_path=db_path)

    with pytest.raises(DealNotFoundError):
        get_deal(created.id, db_path=db_path)


def test_delete_deal_removes_a_detailed_deal_and_its_operating_inputs_row(
    db_path: Path,
) -> None:
    created = create_detailed_deal(
        "Detailed Deal", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    delete_deal(created.id, db_path=db_path)

    with pytest.raises(DealNotFoundError):
        get_deal(created.id, db_path=db_path)

    connection = sqlite3.connect(db_path)
    try:
        detailed_deal_row = connection.execute(
            "SELECT * FROM detailed_deals WHERE id = ?", (created.id,)
        ).fetchone()
        operating_row = connection.execute(
            "SELECT * FROM detailed_operating_inputs WHERE deal_id = ?", (created.id,)
        ).fetchone()
    finally:
        connection.close()
    assert detailed_deal_row is None
    assert operating_row is None


def test_delete_deal_raises_not_found_for_unknown_id(db_path: Path) -> None:
    with pytest.raises(DealNotFoundError):
        delete_deal("does-not-exist", db_path=db_path)


def test_delete_deal_does_not_affect_other_deals_of_either_mode(db_path: Path) -> None:
    kept_quick = create_deal("Kept Quick", QUICK_INPUTS, db_path=db_path)
    kept_detailed = create_detailed_deal(
        "Kept Detailed", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, db_path=db_path
    )
    removed = create_deal("Removed", QUICK_INPUTS, db_path=db_path)

    delete_deal(removed.id, db_path=db_path)

    remaining_ids = {deal.id for deal in list_deals(db_path=db_path)}
    assert remaining_ids == {kept_quick.id, kept_detailed.id}


# =============================================================================
# 7. Restart persistence works
# =============================================================================


def test_data_persists_across_a_simulated_application_restart(db_path: Path) -> None:
    """Each store call already opens and closes its own connection (no
    shared/global connection -- store.py's own documented design), so a
    'restart' is simply a fresh call sequence against the same db_path file
    with no in-process state carried over. Written here explicitly as its
    own scenario, per the Gate 5b test requirements, rather than left only
    implicit in every other test's fixture reuse."""

    quick = create_deal("Quick Deal", QUICK_INPUTS, db_path=db_path)
    detailed = create_detailed_deal(
        "Detailed Deal", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    # Simulate the process restarting: nothing but the file on disk carries
    # forward. A brand-new call sequence, with no shared Python objects from
    # above, must still read back identical data.
    after_restart_quick = get_deal(quick.id, db_path=db_path)
    after_restart_detailed = get_deal(detailed.id, db_path=db_path)
    after_restart_list = list_deals(db_path=db_path)

    assert after_restart_quick == quick
    assert after_restart_detailed == detailed
    assert {deal.id for deal in after_restart_list} == {quick.id, detailed.id}


# =============================================================================
# 8. Migration is idempotent
# =============================================================================


def test_migration_from_v1_to_v2_is_idempotent(db_path: Path) -> None:
    _write_legacy_v1_database(db_path)

    first = get_deal("quick-1", db_path=db_path)
    # A second (and third) connection/migration pass over an
    # already-migrated database must not raise (e.g. "table already exists")
    # and must not change anything.
    second = get_deal("quick-1", db_path=db_path)
    third = list_deals(db_path=db_path)

    assert first == second
    assert third == [first]
    assert _raw_user_version(db_path) == _SCHEMA_VERSION


def test_migration_on_an_already_v2_database_is_a_no_op(db_path: Path) -> None:
    create_deal("Deal", QUICK_INPUTS, db_path=db_path)
    version_after_first_call = _raw_user_version(db_path)

    # Repeated store calls each independently trigger _connect -> _migrate.
    create_detailed_deal(
        "Detailed Deal", GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS, db_path=db_path
    )
    list_deals(db_path=db_path)
    version_after_further_calls = _raw_user_version(db_path)

    assert version_after_first_call == _SCHEMA_VERSION
    assert version_after_further_calls == _SCHEMA_VERSION


def test_repeated_connections_do_not_duplicate_or_corrupt_detailed_tables(
    db_path: Path,
) -> None:
    for i in range(3):
        create_detailed_deal(
            f"Detailed Deal {i}",
            GOLDEN_TERMS,
            GOLDEN_DETAILED_OPERATING_INPUTS,
            db_path=db_path,
        )

    deals = [deal for deal in list_deals(db_path=db_path) if deal.operating_mode is OperatingMode.DETAILED]
    assert len(deals) == 3
    assert all(deal.terms == GOLDEN_TERMS for deal in deals)
