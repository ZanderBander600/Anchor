"""Persistence Phase A -- SQLite deal store.

The only module in ``anchor.deals`` (and in Anchor overall, outside this
package) that imports ``sqlite3``. No other module -- least of all
``anchor.engine`` or ``anchor.validation`` -- touches storage directly, so
the storage mechanism can be swapped later (e.g. for PostgreSQL) by
replacing this one file and its seven functions, without any caller
needing to change.

Numeric representation -- read before changing anything here
==============================================================
``AcquisitionInputs`` (``anchor/contracts.py``) declares its seven
fractional fields as plain ``float`` and its two year fields as plain
``int``; ``validate_acquisition_inputs`` (``anchor/validation.py``)
produces them via bare ``float(value)`` / ``int(value)`` calls. Anchor's
canonical numeric type is Python's native ``float`` (IEEE 754 binary64),
not ``decimal.Decimal`` -- confirmed by inspection, not assumed.

SQLite's ``REAL`` column type stores an 8-byte IEEE 754 double -- bit-for-
bit the same representation CPython uses for ``float``. Writing a Python
``float`` into a ``REAL`` column and reading it back is therefore an exact,
lossless round-trip: no new numeric representation, no additional rounding
step, and no change to the economic meaning of a stored value. This is
verified empirically, not just argued, by
``test_deals_store.test_stored_inputs_round_trip_exactly`` (bit-for-bit
``==``, not ``pytest.approx``). ``REAL`` would be the wrong choice if the
canonical type were ``Decimal`` (SQLite has no fixed-point column type,
and coercing ``Decimal`` through ``REAL`` genuinely would be lossy); it is
not, so this is the direct, correct representation rather than a shortcut.

``hold_period``/``amortization`` map to SQLite ``INTEGER`` (a signed
64-bit integer) -- exact for the small whole-year values these fields hold.

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

from ..contracts import AcquisitionInputs
from .contracts import Deal, DealNotFoundError

_DEFAULT_DB_PATH = Path("data/anchor.db")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS deals (
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
)


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
    FastAPI's threadpool-dispatched sync routes."""

    resolved_path = db_path if db_path is not None else get_db_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    connection.execute(_CREATE_TABLE_SQL)
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
    )
    return Deal(
        id=row["id"],
        name=row["name"],
        inputs=inputs,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _input_values(inputs: AcquisitionInputs) -> Iterable[object]:
    return (getattr(inputs, column) for column in _INPUT_COLUMNS)


def create_deal(
    name: str,
    inputs: AcquisitionInputs,
    *,
    db_path: Path | None = None,
) -> Deal:
    """Insert a new deal and return it as stored. ``inputs`` must already be
    an ``AcquisitionInputs`` instance -- this function performs no
    validation of its own; the caller (the API layer, matching every other
    endpoint) is responsible for having called
    ``validate_acquisition_inputs`` first."""

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


def get_deal(deal_id: str, *, db_path: Path | None = None) -> Deal:
    """Return the deal with ``deal_id``, or raise ``DealNotFoundError``."""

    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM deals WHERE id = ?", (deal_id,)
        ).fetchone()

    if row is None:
        raise DealNotFoundError(deal_id)
    return _row_to_deal(row)


def list_deals(*, db_path: Path | None = None) -> list[Deal]:
    """Return every saved deal, most recently updated first."""

    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM deals ORDER BY updated_at DESC"
        ).fetchall()

    return [_row_to_deal(row) for row in rows]


def update_deal(
    deal_id: str,
    name: str,
    inputs: AcquisitionInputs,
    *,
    db_path: Path | None = None,
) -> Deal:
    """Overwrite ``deal_id``'s name and inputs, bump ``updated_at``, and
    return the updated deal. Raises ``DealNotFoundError`` if it doesn't
    exist. ``inputs`` must already be an ``AcquisitionInputs`` instance --
    same validation contract as ``create_deal``."""

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


def delete_deal(deal_id: str, *, db_path: Path | None = None) -> None:
    """Permanently delete the deal with ``deal_id``. Raises
    ``DealNotFoundError`` if it doesn't exist. No soft-delete and no
    history -- the row is simply gone."""

    with _connect(db_path) as connection:
        cursor = connection.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
        if cursor.rowcount == 0:
            raise DealNotFoundError(deal_id)


def duplicate_deal(
    deal_id: str,
    *,
    name: str | None = None,
    db_path: Path | None = None,
) -> Deal:
    """Copy an existing deal's ``AcquisitionInputs`` into a brand new deal
    with a new id and fresh timestamps. Raises ``DealNotFoundError`` if
    ``deal_id`` doesn't exist. Never copies a derived result -- there is
    none to copy (Persistence Phase A never stores ``AcquisitionResults``).
    Reuses ``get_deal``/``create_deal`` rather than a bespoke SQL copy, so
    the new deal is generated by the exact same id/timestamp logic as any
    other created deal, with no separate path to keep in sync."""

    original = get_deal(deal_id, db_path=db_path)
    new_name = name if name else f"{original.name} (Copy)"
    return create_deal(new_name, original.inputs, db_path=db_path)
