"""Underwriting V2 Gate 5, Part B -- SQLite persistence migration.

Covers the first real schema migration this project has: adding the five
Underwriting V2 columns to the ``deals`` table via ``PRAGMA
user_version``-gated ``ALTER TABLE ... ADD COLUMN`` (``anchor.deals.store``),
with existing pre-V2 databases migrating safely and existing rows receiving
neutral V2 defaults. ``tests/test_deals_store.py`` remains the permanent
create/get/list/update/delete/duplicate regression for the (now
fourteen-field) contract; this file is additive V2-specific coverage.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from anchor.contracts import AcquisitionInputs
from anchor.deals.store import (
    _SCHEMA_VERSION,
    create_deal,
    duplicate_deal,
    get_deal,
    list_deals,
    update_deal,
)
from anchor.engine import analyze_acquisition

V1_NEUTRAL_INPUTS = AcquisitionInputs(
    purchase_price=50_000_000.0,
    current_noi=2_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.055,
    ltv=0.65,
    interest_rate=0.0525,
    amortization=30,
)

# Matches the frozen Underwriting V2 golden case (Gate 4) -- all five V2
# fields simultaneously nonzero.
V2_INPUTS = AcquisitionInputs(
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

_LEGACY_CREATE_TABLE_SQL = """
CREATE TABLE deals (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    purchase_price REAL NOT NULL,
    current_noi    REAL NOT NULL,
    occupancy      REAL NOT NULL,
    noi_growth     REAL NOT NULL,
    hold_period    INTEGER NOT NULL,
    exit_cap_rate  REAL NOT NULL,
    ltv            REAL NOT NULL,
    interest_rate  REAL NOT NULL,
    amortization   INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
)
"""


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test-anchor.db"


def _write_legacy_database(db_path: Path, *, deal_id: str = "legacy-1") -> None:
    """Build a pre-Gate-5 (nine-input-column, no ``user_version``) database
    file directly via raw ``sqlite3`` -- the exact shape ``store.py``
    produced before this gate, never through the current (already-V2-aware)
    ``store.py`` itself."""

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(_LEGACY_CREATE_TABLE_SQL)
        connection.execute(
            """
            INSERT INTO deals (
                id, name, purchase_price, current_noi, occupancy, noi_growth,
                hold_period, exit_cap_rate, ltv, interest_rate, amortization,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deal_id,
                "Legacy Deal",
                V1_NEUTRAL_INPUTS.purchase_price,
                V1_NEUTRAL_INPUTS.current_noi,
                V1_NEUTRAL_INPUTS.occupancy,
                V1_NEUTRAL_INPUTS.noi_growth,
                V1_NEUTRAL_INPUTS.hold_period,
                V1_NEUTRAL_INPUTS.exit_cap_rate,
                V1_NEUTRAL_INPUTS.ltv,
                V1_NEUTRAL_INPUTS.interest_rate,
                V1_NEUTRAL_INPUTS.amortization,
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    # Confirm the fixture really is pre-V2: no V2 columns, user_version 0.
    connection = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(deals)")}
        assert "acquisition_cost_pct" not in columns
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        connection.close()


# =============================================================================
# Fresh V2 database.
# =============================================================================


def test_fresh_database_schema_contains_all_five_v2_columns(db_path: Path) -> None:
    create_deal("Deal", V1_NEUTRAL_INPUTS, db_path=db_path)

    connection = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(deals)")}
    finally:
        connection.close()

    assert {
        "acquisition_cost_pct",
        "financing_fee_pct",
        "disposition_cost_pct",
        "annual_capex_reserve",
        "io_period",
    } <= columns


def test_fresh_database_is_created_directly_at_the_current_schema_version(
    db_path: Path,
) -> None:
    create_deal("Deal", V1_NEUTRAL_INPUTS, db_path=db_path)

    connection = sqlite3.connect(db_path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    assert version == _SCHEMA_VERSION


def test_v2_inputs_round_trip_exactly(db_path: Path) -> None:
    created = create_deal("V2 Deal", V2_INPUTS, db_path=db_path)
    fetched = get_deal(created.id, db_path=db_path)

    assert fetched.inputs == V2_INPUTS
    assert fetched.inputs.acquisition_cost_pct == 0.02
    assert fetched.inputs.financing_fee_pct == 0.01
    assert fetched.inputs.disposition_cost_pct == 0.025
    assert fetched.inputs.annual_capex_reserve == 50_000.0
    assert fetched.inputs.io_period == 2
    assert isinstance(fetched.inputs.io_period, int)


# =============================================================================
# Migrating an existing pre-V2 database.
# =============================================================================


def test_existing_pre_v2_database_migrates_automatically(db_path: Path) -> None:
    _write_legacy_database(db_path)

    # Any store call opens a connection, which runs the migration.
    deal = get_deal("legacy-1", db_path=db_path)

    assert deal.inputs.acquisition_cost_pct == 0.0

    connection = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(deals)")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    assert {
        "acquisition_cost_pct",
        "financing_fee_pct",
        "disposition_cost_pct",
        "annual_capex_reserve",
        "io_period",
    } <= columns
    assert version == _SCHEMA_VERSION


def test_existing_rows_receive_neutral_v2_defaults(db_path: Path) -> None:
    _write_legacy_database(db_path)

    deal = get_deal("legacy-1", db_path=db_path)

    assert deal.inputs.acquisition_cost_pct == 0.0
    assert deal.inputs.financing_fee_pct == 0.0
    assert deal.inputs.disposition_cost_pct == 0.0
    assert deal.inputs.annual_capex_reserve == 0.0
    assert deal.inputs.io_period == 0


def test_existing_identity_name_timestamps_and_original_nine_inputs_survive_migration(
    db_path: Path,
) -> None:
    _write_legacy_database(db_path)

    deal = get_deal("legacy-1", db_path=db_path)

    assert deal.id == "legacy-1"
    assert deal.name == "Legacy Deal"
    assert deal.created_at.isoformat() == "2020-01-01T00:00:00+00:00"
    assert deal.updated_at.isoformat() == "2020-01-01T00:00:00+00:00"
    assert deal.inputs.purchase_price == V1_NEUTRAL_INPUTS.purchase_price
    assert deal.inputs.current_noi == V1_NEUTRAL_INPUTS.current_noi
    assert deal.inputs.occupancy == V1_NEUTRAL_INPUTS.occupancy
    assert deal.inputs.noi_growth == V1_NEUTRAL_INPUTS.noi_growth
    assert deal.inputs.hold_period == V1_NEUTRAL_INPUTS.hold_period
    assert deal.inputs.exit_cap_rate == V1_NEUTRAL_INPUTS.exit_cap_rate
    assert deal.inputs.ltv == V1_NEUTRAL_INPUTS.ltv
    assert deal.inputs.interest_rate == V1_NEUTRAL_INPUTS.interest_rate
    assert deal.inputs.amortization == V1_NEUTRAL_INPUTS.amortization


def test_migration_is_idempotent(db_path: Path) -> None:
    _write_legacy_database(db_path)

    first = get_deal("legacy-1", db_path=db_path)
    # A second (and third) connection/migration pass over an
    # already-migrated database must not raise (e.g. "duplicate column")
    # and must not change anything.
    second = get_deal("legacy-1", db_path=db_path)
    third = list_deals(db_path=db_path)

    assert first == second
    assert third == [first]

    connection = sqlite3.connect(db_path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    assert version == _SCHEMA_VERSION


def test_reopening_a_migrated_legacy_deal_and_analyzing_it_produces_the_same_v1_neutral_economics(
    db_path: Path,
) -> None:
    _write_legacy_database(db_path)

    deal = get_deal("legacy-1", db_path=db_path)
    reopened_result = analyze_acquisition(deal.inputs)
    direct_result = analyze_acquisition(V1_NEUTRAL_INPUTS)

    assert reopened_result == direct_result
    assert reopened_result.levered_irr == pytest.approx(0.07913030056780745, rel=0.0, abs=1e-9)
    assert reopened_result.acquisition_costs == 0.0
    assert reopened_result.financing_fee == 0.0
    assert reopened_result.disposition_costs == 0.0


# =============================================================================
# Create/update/list/get/duplicate/delete continue working with the
# expanded fourteen-field contract.
# =============================================================================


def test_create_get_list_update_continue_working_with_v2_inputs(db_path: Path) -> None:
    created = create_deal("V2 Deal", V2_INPUTS, db_path=db_path)
    assert created.inputs == V2_INPUTS

    fetched = get_deal(created.id, db_path=db_path)
    assert fetched == created

    listed = list_deals(db_path=db_path)
    assert listed == [created]

    other_v2_inputs = replace(V2_INPUTS, io_period=5)
    updated = update_deal(created.id, "Renamed V2 Deal", other_v2_inputs, db_path=db_path)
    assert updated.inputs.io_period == 5
    assert updated.inputs == other_v2_inputs


def test_duplicate_preserves_all_fourteen_fields_exactly(db_path: Path) -> None:
    original = create_deal("V2 Deal", V2_INPUTS, db_path=db_path)

    copy = duplicate_deal(original.id, db_path=db_path)

    assert copy.inputs == V2_INPUTS
    assert copy.inputs == original.inputs
    assert copy.id != original.id


def test_delete_behavior_is_unaffected_by_the_v2_schema(db_path: Path) -> None:
    from anchor.deals.store import delete_deal
    from anchor.deals import DealNotFoundError

    created = create_deal("V2 Deal", V2_INPUTS, db_path=db_path)

    delete_deal(created.id, db_path=db_path)

    with pytest.raises(DealNotFoundError):
        get_deal(created.id, db_path=db_path)
    assert list_deals(db_path=db_path) == []
