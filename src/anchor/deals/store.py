"""Persistence Phase A / Detailed Operating Model V2.1 Gate 5b -- SQLite
deal store.

The only module in ``anchor.deals`` (and in Anchor overall, outside this
package) that imports ``sqlite3``. No other module -- least of all
``anchor.engine`` or ``anchor.validation`` -- touches storage directly, so
the storage mechanism can be swapped later (e.g. for PostgreSQL) by
replacing this one file, without any caller needing to change.

Numeric representation -- read before changing anything here
==============================================================
``AcquisitionInputs``/``AcquisitionTerms``/``DetailedOperatingInputs``
(``anchor/contracts.py``) declare every fractional field as plain ``float``
and every year field as plain ``int``; the shared validators
(``anchor/validation.py``) produce them via bare ``float(value)`` /
``int(value)`` calls. Anchor's canonical numeric type is Python's native
``float`` (IEEE 754 binary64), not ``decimal.Decimal`` -- confirmed by
inspection, not assumed.

SQLite's ``REAL`` column type stores an 8-byte IEEE 754 double -- bit-for-
bit the same representation CPython uses for ``float``. Writing a Python
``float`` into a ``REAL`` column and reading it back is therefore an exact,
lossless round-trip: no new numeric representation, no additional rounding
step, and no change to the economic meaning of a stored value. This is
verified empirically, not just argued, by
``test_deals_store.test_stored_inputs_round_trip_exactly`` and
``test_deals_store_detailed_v2_1.py``'s Detailed round-trip equivalents
(bit-for-bit ``==``, not ``pytest.approx``).

Year fields map to SQLite ``INTEGER`` (a signed 64-bit integer) -- exact for
the small whole-year values these fields hold.

Two-table Quick/Detailed split (Detailed Operating Model V2.1 Gate 5b)
========================================================================
``deals`` is Quick-only storage, structurally unchanged since Underwriting
V2 Gate 5 -- every column, including its ``NOT NULL`` constraints on
``current_noi``/``occupancy``/``noi_growth``, is exactly as it was. SQLite
cannot relax an existing ``NOT NULL`` constraint without a full table
rebuild (only ``ADD COLUMN``/``RENAME COLUMN``/``DROP COLUMN`` are
supported by plain ``ALTER TABLE``), and a Detailed deal must never store a
fabricated ``current_noi``/``noi_growth``/``occupancy`` value merely to
satisfy those constraints -- so a Detailed deal is never a row in this
table at all.

``detailed_deals`` (the ``AcquisitionTerms`` fields) and
``detailed_operating_inputs`` (the ``DetailedOperatingInputs`` fields, one
row per Detailed deal, ``deal_id`` a 1:1 primary key referencing
``detailed_deals.id``) are new, purely additive tables -- created via
``CREATE TABLE IF NOT EXISTS`` unconditionally on every connection, exactly
like ``deals`` itself, needing no ``ALTER`` of any kind. No existing table,
column, or constraint is touched by this gate.

The public functions below present one domain-level ``Deal`` abstraction
and dispatch across the two storage paths by ``operating_mode`` --
``get_deal``/``list_deals``/``delete_deal``/``duplicate_deal`` look in
whichever table actually holds ``deal_id`` (ids are never shared between
the two tables, since both use freshly generated ``uuid4`` hex strings);
``create_deal``/``update_deal`` remain Quick-only, with their existing
signatures and behavior completely unchanged; ``create_detailed_deal``/
``update_detailed_deal`` are their new Detailed-only counterparts.

Database path
=============
The path is never hardcoded into a call site. ``get_db_path()`` resolves
it fresh on every call (never cached at import time) from the
``ANCHOR_DB_PATH`` environment variable, falling back to the repo-local
default ``data/anchor.db``. Every public function also accepts an explicit
``db_path`` override, which takes precedence over both -- tests use this to
point at an isolated ``tmp_path`` file without touching the environment at
all. The parent directory is created on demand (``mkdir(parents=True,
exist_ok=True)``) before every connection, so a fresh checkout with no
``data/`` directory yet works without any manual setup step.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs, OperatingMode
from .contracts import Deal, DealNotFoundError

_DEFAULT_DB_PATH = Path("data/anchor.db")

# Detailed Operating Model V2.1 Gate 5b: schema version 2 adds the two new
# Detailed tables below. Version 1 (Underwriting V2 Gate 5) added the five
# V2 AcquisitionInputs columns to the pre-existing ``deals`` table via
# ALTER TABLE ADD COLUMN; that migration step is unchanged and still runs
# for a genuine pre-V2 database. Version 2 requires no ALTER at all -- the
# new tables are created unconditionally, via CREATE TABLE IF NOT EXISTS,
# by ``_connect`` itself, exactly like ``deals``. ``_migrate`` only needs to
# record that this connection has now seen a version-2-aware store; the
# actual DDL is idempotent regardless of ``PRAGMA user_version``.
_SCHEMA_VERSION = 2

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS deals (
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

# Detailed Operating Model V2.1 Gate 5b: the eleven AcquisitionTerms fields,
# one row per Detailed deal. Structurally independent of ``deals`` -- no
# foreign key back to it, no shared id namespace requirement beyond both
# using freshly generated uuid4 hex strings.
_CREATE_DETAILED_DEALS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS detailed_deals (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    purchase_price        REAL NOT NULL,
    hold_period           INTEGER NOT NULL,
    exit_cap_rate         REAL NOT NULL,
    ltv                   REAL NOT NULL,
    interest_rate         REAL NOT NULL,
    amortization          INTEGER NOT NULL,
    acquisition_cost_pct  REAL NOT NULL,
    financing_fee_pct     REAL NOT NULL,
    disposition_cost_pct  REAL NOT NULL,
    annual_capex_reserve  REAL NOT NULL,
    io_period             INTEGER NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
)
"""

# Detailed Operating Model V2.1 Gate 5b: the eleven DetailedOperatingInputs
# fields. ``deal_id`` is both the primary key and a foreign key into
# ``detailed_deals.id`` -- a genuine 1:1 relationship (SQLite does not
# enforce FOREIGN KEY constraints unless PRAGMA foreign_keys=ON, which this
# module does not set, matching its existing no-cross-row-integrity-engine
# posture elsewhere; the 1:1 shape is enforced by this module's own
# create/delete logic always writing or removing both rows together).
_CREATE_DETAILED_OPERATING_INPUTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS detailed_operating_inputs (
    deal_id                   TEXT PRIMARY KEY REFERENCES detailed_deals(id),
    gross_potential_rent      REAL NOT NULL,
    other_income              REAL NOT NULL,
    vacancy_credit_loss_pct   REAL NOT NULL,
    property_taxes            REAL NOT NULL,
    insurance                 REAL NOT NULL,
    utilities                 REAL NOT NULL,
    repairs_maintenance       REAL NOT NULL,
    other_operating_expenses  REAL NOT NULL,
    management_fee_pct        REAL NOT NULL,
    revenue_growth            REAL NOT NULL,
    expense_growth            REAL NOT NULL
)
"""

# Underwriting V2 Gate 5's five new columns, in the order they are added to
# a pre-V2 database by ``_migrate``: (column name, SQLite column type,
# neutral-default SQL literal). The literal matches the exact same neutral
# default ``AcquisitionInputs`` itself declares for each field.
_V2_MIGRATION_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("acquisition_cost_pct", "REAL", "0.0"),
    ("financing_fee_pct", "REAL", "0.0"),
    ("disposition_cost_pct", "REAL", "0.0"),
    ("annual_capex_reserve", "REAL", "0.0"),
    ("io_period", "INTEGER", "0"),
)

_INPUT_COLUMNS: tuple[str, ...] = (
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
)

_TERMS_COLUMNS: tuple[str, ...] = (
    "purchase_price",
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
)

_DETAILED_OPERATING_COLUMNS: tuple[str, ...] = (
    "gross_potential_rent",
    "other_income",
    "vacancy_credit_loss_pct",
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "other_operating_expenses",
    "management_fee_pct",
    "revenue_growth",
    "expense_growth",
)


def _migrate(connection: sqlite3.Connection) -> None:
    """Bring an existing database up to ``_SCHEMA_VERSION``, if it isn't
    already.

    Column presence (``PRAGMA table_info``), not just ``user_version``,
    decides which ``deals`` ``ALTER TABLE ADD COLUMN`` statements actually
    run -- a brand-new database's ``CREATE TABLE`` already declares all
    fourteen input columns, so none of the five ``ALTER`` statements below
    ever fire for it; only a genuine pre-V2 database (created before that
    gate) is missing them and gets them added. This block is unconditional
    (not gated on ``current_version < 1``) but safe to run redundantly on a
    version-1-or-later database -- the per-column presence check makes it a
    no-op there. SQLite itself backfills the ``NOT NULL ... DEFAULT`` value
    into every existing row for a column added this way -- no explicit
    ``UPDATE`` is needed.

    The version-2 (Detailed Operating Model V2.1) step is not represented
    here at all: ``detailed_deals``/``detailed_operating_inputs`` are
    created unconditionally by ``_connect``, via ``CREATE TABLE IF NOT
    EXISTS`` -- idempotent by construction, no ``PRAGMA user_version`` gate
    needed. This function's only remaining job for that step is recording
    the version number.

    Safe to call on every connection, in any state: a database already at
    ``_SCHEMA_VERSION`` returns immediately at the top.
    """

    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_version >= _SCHEMA_VERSION:
        return

    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(deals)")
    }
    for column_name, column_type, default_literal in _V2_MIGRATION_COLUMNS:
        if column_name not in existing_columns:
            connection.execute(
                f"ALTER TABLE deals ADD COLUMN {column_name} {column_type} "
                f"NOT NULL DEFAULT {default_literal}"
            )

    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


def get_db_path() -> Path:
    """The Anchor SQLite database path: ``ANCHOR_DB_PATH`` if set, else the
    repo-local default ``data/anchor.db``. Resolved fresh on every call so a
    test can override it via environment variable without any import-order
    dependency."""

    override = os.environ.get("ANCHOR_DB_PATH")
    return Path(override) if override else _DEFAULT_DB_PATH


@contextmanager
def _connect(db_path: Path | None) -> Iterator[sqlite3.Connection]:
    """Open one short-lived connection: commits on clean exit, rolls back
    and re-raises on exception, always closes. No pooling and no shared
    global connection -- at Anchor's single-process, single-user scale, a
    fresh connection per call is simpler than lifecycle-managing a shared
    one, and avoids any cross-thread sqlite3 sharing concern under
    FastAPI's threadpool-dispatched sync routes.

    All three tables are created unconditionally (``CREATE TABLE IF NOT
    EXISTS``) before ``_migrate`` runs, on every connection -- purely
    additive and idempotent, matching ``deals``' own existing pattern
    exactly for the two new Detailed tables.
    """

    resolved_path = db_path if db_path is not None else get_db_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    connection.execute(_CREATE_TABLE_SQL)
    connection.execute(_CREATE_DETAILED_DEALS_TABLE_SQL)
    connection.execute(_CREATE_DETAILED_OPERATING_INPUTS_TABLE_SQL)
    _migrate(connection)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_deal(row: sqlite3.Row) -> Deal:
    inputs = AcquisitionInputs(
        purchase_price=row["purchase_price"],
        current_noi=row["current_noi"],
        occupancy=row["occupancy"],
        noi_growth=row["noi_growth"],
        hold_period=row["hold_period"],
        exit_cap_rate=row["exit_cap_rate"],
        ltv=row["ltv"],
        interest_rate=row["interest_rate"],
        amortization=row["amortization"],
        acquisition_cost_pct=row["acquisition_cost_pct"],
        financing_fee_pct=row["financing_fee_pct"],
        disposition_cost_pct=row["disposition_cost_pct"],
        annual_capex_reserve=row["annual_capex_reserve"],
        io_period=row["io_period"],
    )
    return Deal(
        id=row["id"],
        name=row["name"],
        operating_mode=OperatingMode.QUICK,
        inputs=inputs,
        terms=None,
        detailed_operating_inputs=None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_detailed_deal(
    deal_row: sqlite3.Row, operating_row: sqlite3.Row
) -> Deal:
    terms = AcquisitionTerms(
        purchase_price=deal_row["purchase_price"],
        hold_period=deal_row["hold_period"],
        exit_cap_rate=deal_row["exit_cap_rate"],
        ltv=deal_row["ltv"],
        interest_rate=deal_row["interest_rate"],
        amortization=deal_row["amortization"],
        acquisition_cost_pct=deal_row["acquisition_cost_pct"],
        financing_fee_pct=deal_row["financing_fee_pct"],
        disposition_cost_pct=deal_row["disposition_cost_pct"],
        annual_capex_reserve=deal_row["annual_capex_reserve"],
        io_period=deal_row["io_period"],
    )
    detailed_operating_inputs = DetailedOperatingInputs(
        gross_potential_rent=operating_row["gross_potential_rent"],
        other_income=operating_row["other_income"],
        vacancy_credit_loss_pct=operating_row["vacancy_credit_loss_pct"],
        property_taxes=operating_row["property_taxes"],
        insurance=operating_row["insurance"],
        utilities=operating_row["utilities"],
        repairs_maintenance=operating_row["repairs_maintenance"],
        other_operating_expenses=operating_row["other_operating_expenses"],
        management_fee_pct=operating_row["management_fee_pct"],
        revenue_growth=operating_row["revenue_growth"],
        expense_growth=operating_row["expense_growth"],
    )
    return Deal(
        id=deal_row["id"],
        name=deal_row["name"],
        operating_mode=OperatingMode.DETAILED,
        inputs=None,
        terms=terms,
        detailed_operating_inputs=detailed_operating_inputs,
        created_at=datetime.fromisoformat(deal_row["created_at"]),
        updated_at=datetime.fromisoformat(deal_row["updated_at"]),
    )


def _input_values(inputs: AcquisitionInputs) -> Iterable[object]:
    return (getattr(inputs, column) for column in _INPUT_COLUMNS)


def _terms_values(terms: AcquisitionTerms) -> Iterable[object]:
    return (getattr(terms, column) for column in _TERMS_COLUMNS)


def _detailed_operating_values(
    detailed_operating_inputs: DetailedOperatingInputs,
) -> Iterable[object]:
    return (
        getattr(detailed_operating_inputs, column)
        for column in _DETAILED_OPERATING_COLUMNS
    )


# =============================================================================
# Quick deals -- unchanged signatures and behavior
# =============================================================================


def create_deal(
    name: str,
    inputs: AcquisitionInputs,
    *,
    db_path: Path | None = None,
) -> Deal:
    """Insert a new Quick deal and return it as stored. ``inputs`` must
    already be an ``AcquisitionInputs`` instance -- this function performs
    no validation of its own; the caller (the API layer, matching every
    other endpoint) is responsible for having called
    ``validate_acquisition_inputs`` first. Unchanged by Detailed Operating
    Model V2.1 -- inserts into ``deals`` only."""

    deal_id = uuid.uuid4().hex
    now = _utc_now_iso()

    with _connect(db_path) as connection:
        connection.execute(
            f"""
            INSERT INTO deals (id, name, {", ".join(_INPUT_COLUMNS)}, created_at, updated_at)
            VALUES (?, ?, {", ".join("?" for _ in _INPUT_COLUMNS)}, ?, ?)
            """,
            (deal_id, name, *_input_values(inputs), now, now),
        )

    return get_deal(deal_id, db_path=db_path)


def update_deal(
    deal_id: str,
    name: str,
    inputs: AcquisitionInputs,
    *,
    db_path: Path | None = None,
) -> Deal:
    """Overwrite ``deal_id``'s name and inputs, bump ``updated_at``, and
    return the updated Quick deal. Raises ``DealNotFoundError`` if it
    doesn't exist in ``deals`` -- unchanged by Detailed Operating Model
    V2.1, including for a ``deal_id`` that belongs to a Detailed deal (that
    id is never a row in ``deals``, so this correctly reports it as not
    found rather than silently succeeding against the wrong table)."""

    now = _utc_now_iso()

    with _connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE deals
            SET name = ?, {", ".join(f"{column} = ?" for column in _INPUT_COLUMNS)}, updated_at = ?
            WHERE id = ?
            """,
            (name, *_input_values(inputs), now, deal_id),
        )
        if cursor.rowcount == 0:
            raise DealNotFoundError(deal_id)

    return get_deal(deal_id, db_path=db_path)


# =============================================================================
# Detailed deals -- new
# =============================================================================


def create_detailed_deal(
    name: str,
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    db_path: Path | None = None,
) -> Deal:
    """Insert a new Detailed deal and return it as stored. ``terms`` and
    ``detailed_operating_inputs`` must already be validated instances --
    same no-revalidation contract as ``create_deal``. Writes both the
    ``detailed_deals`` row and its 1:1 ``detailed_operating_inputs`` row in
    the same connection/transaction -- never one without the other. Never
    creates or touches a row in ``deals``."""

    deal_id = uuid.uuid4().hex
    now = _utc_now_iso()

    with _connect(db_path) as connection:
        connection.execute(
            f"""
            INSERT INTO detailed_deals
                (id, name, {", ".join(_TERMS_COLUMNS)}, created_at, updated_at)
            VALUES (?, ?, {", ".join("?" for _ in _TERMS_COLUMNS)}, ?, ?)
            """,
            (deal_id, name, *_terms_values(terms), now, now),
        )
        connection.execute(
            f"""
            INSERT INTO detailed_operating_inputs
                (deal_id, {", ".join(_DETAILED_OPERATING_COLUMNS)})
            VALUES (?, {", ".join("?" for _ in _DETAILED_OPERATING_COLUMNS)})
            """,
            (deal_id, *_detailed_operating_values(detailed_operating_inputs)),
        )

    return get_deal(deal_id, db_path=db_path)


def update_detailed_deal(
    deal_id: str,
    name: str,
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    db_path: Path | None = None,
) -> Deal:
    """Overwrite ``deal_id``'s name, terms, and detailed operating inputs,
    bump ``updated_at``, and return the updated Detailed deal. Raises
    ``DealNotFoundError`` if it doesn't exist in ``detailed_deals``."""

    now = _utc_now_iso()

    with _connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE detailed_deals
            SET name = ?, {", ".join(f"{column} = ?" for column in _TERMS_COLUMNS)}, updated_at = ?
            WHERE id = ?
            """,
            (name, *_terms_values(terms), now, deal_id),
        )
        if cursor.rowcount == 0:
            raise DealNotFoundError(deal_id)

        connection.execute(
            f"""
            UPDATE detailed_operating_inputs
            SET {", ".join(f"{column} = ?" for column in _DETAILED_OPERATING_COLUMNS)}
            WHERE deal_id = ?
            """,
            (*_detailed_operating_values(detailed_operating_inputs), deal_id),
        )

    return get_deal(deal_id, db_path=db_path)


# =============================================================================
# Mode-dispatching operations -- one domain-level Deal abstraction
# =============================================================================


def get_deal(deal_id: str, *, db_path: Path | None = None) -> Deal:
    """Return the deal with ``deal_id``, dispatching by which table
    actually holds it: ``deals`` (Quick) first, then ``detailed_deals`` +
    ``detailed_operating_inputs`` (Detailed). Raises ``DealNotFoundError``
    if ``deal_id`` is in neither."""

    with _connect(db_path) as connection:
        quick_row = connection.execute(
            "SELECT * FROM deals WHERE id = ?", (deal_id,)
        ).fetchone()
        if quick_row is not None:
            return _row_to_deal(quick_row)

        detailed_row = connection.execute(
            "SELECT * FROM detailed_deals WHERE id = ?", (deal_id,)
        ).fetchone()
        if detailed_row is None:
            raise DealNotFoundError(deal_id)

        operating_row = connection.execute(
            "SELECT * FROM detailed_operating_inputs WHERE deal_id = ?", (deal_id,)
        ).fetchone()
        if operating_row is None:
            # The 1:1 invariant (both rows always written/removed together
            # by this module) means this should never happen; surfaced as
            # DealNotFoundError rather than a raw None-access crash if it
            # somehow does (e.g. a hand-edited database).
            raise DealNotFoundError(deal_id)

        return _row_to_detailed_deal(detailed_row, operating_row)


def list_deals(*, db_path: Path | None = None) -> list[Deal]:
    """Return every saved deal, Quick and Detailed together, most recently
    updated first."""

    with _connect(db_path) as connection:
        quick_rows = connection.execute("SELECT * FROM deals").fetchall()
        detailed_rows = connection.execute("SELECT * FROM detailed_deals").fetchall()
        operating_rows_by_deal_id = {
            row["deal_id"]: row
            for row in connection.execute("SELECT * FROM detailed_operating_inputs")
        }

    quick_deals = [_row_to_deal(row) for row in quick_rows]
    detailed_deals = [
        _row_to_detailed_deal(row, operating_rows_by_deal_id[row["id"]])
        for row in detailed_rows
    ]

    # ISO-8601 UTC timestamps (_utc_now_iso) sort lexicographically in
    # chronological order, so string comparison alone is sufficient --
    # matches the ordering "SELECT * FROM deals ORDER BY updated_at DESC"
    # already produced for Quick-only queries before this gate.
    return sorted(
        [*quick_deals, *detailed_deals], key=lambda deal: deal.updated_at, reverse=True
    )


def delete_deal(deal_id: str, *, db_path: Path | None = None) -> None:
    """Permanently delete the deal with ``deal_id``, dispatching by which
    table holds it. Raises ``DealNotFoundError`` if it doesn't exist in
    either. No soft-delete and no history -- the row(s) are simply gone. A
    Detailed deal's ``detailed_operating_inputs`` row is always removed
    together with its ``detailed_deals`` row."""

    with _connect(db_path) as connection:
        cursor = connection.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
        if cursor.rowcount > 0:
            return

        connection.execute(
            "DELETE FROM detailed_operating_inputs WHERE deal_id = ?", (deal_id,)
        )
        cursor = connection.execute(
            "DELETE FROM detailed_deals WHERE id = ?", (deal_id,)
        )
        if cursor.rowcount == 0:
            raise DealNotFoundError(deal_id)


def duplicate_deal(
    deal_id: str,
    *,
    name: str | None = None,
    db_path: Path | None = None,
) -> Deal:
    """Copy an existing deal's assumptions into a brand new deal with a new
    id and fresh timestamps, in the same operating mode as the original.
    Raises ``DealNotFoundError`` if ``deal_id`` doesn't exist. Never copies
    a derived result -- there is none to copy (persistence never stores
    ``AcquisitionResults``). Reuses ``get_deal``/``create_deal``/
    ``create_detailed_deal`` rather than a bespoke SQL copy, so the new deal
    is generated by the exact same id/timestamp logic as any other created
    deal, with no separate path to keep in sync."""

    original = get_deal(deal_id, db_path=db_path)
    new_name = name if name else f"{original.name} (Copy)"

    if original.operating_mode is OperatingMode.QUICK:
        assert original.inputs is not None
        return create_deal(new_name, original.inputs, db_path=db_path)

    assert original.terms is not None
    assert original.detailed_operating_inputs is not None
    return create_detailed_deal(
        new_name, original.terms, original.detailed_operating_inputs, db_path=db_path
    )
