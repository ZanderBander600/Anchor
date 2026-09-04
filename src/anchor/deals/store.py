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
``create_deal``/``update_deal`` remain Quick-only; ``create_detailed_deal``/
``update_detailed_deal`` are their Detailed-only counterparts.

Owner Return Metrics V3 Gate A6 -- cached analysis/AI snapshots
==================================================================
``deals``/``detailed_deals`` each additionally carry, as plain nullable
columns (never a separate table -- see ``_ANALYSIS_SNAPSHOT_SCHEMA_VERSION``
below for why that stayed unnecessary): a JSON-serialized
``analysis_snapshot`` (an ``AcquisitionResults``, or for Detailed a
``DetailedAcquisitionResults``) and ``ai_snapshot`` (an ``AIAnalysis``),
each paired with its own ``..._schema_version`` (INTEGER) and
``..._fingerprint`` (TEXT, a sha256 of the exact assumptions -- and, for
the AI fingerprint, ``deal_context`` too -- that produced it). A snapshot
is decoded and returned on ``Deal`` only when its stored schema version
matches what this build understands *and* its stored fingerprint matches a
fingerprint freshly recomputed from the row's own current assumptions/
context; any mismatch, or any JSON/shape decoding failure, makes the
snapshot silently absent (``None``) rather than ever surfacing stale or
malformed cached data -- see ``_decode_analysis_snapshot``/
``_decode_ai_snapshot``.

Owner Return Metrics V3 Gate A7 -- snapshot provenance hardening
==================================================================
Gate A6's ``create_deal``/``update_deal``/``create_detailed_deal``/
``update_detailed_deal`` originally accepted optional ``analysis_snapshot``/
``ai_snapshot`` dicts in the same write as fresh assumptions, trusting them
at face value and pairing them with a fingerprint freshly computed from
*those same, possibly-just-changed* assumptions -- a caller that submitted
new assumptions alongside a snapshot computed under different (stale)
assumptions would have that stale snapshot incorrectly relabeled as valid
for the new ones. The existing frontend never did this, but the invariant
must not depend on frontend behavior.

Gate A7 closes this structurally: none of those four functions accept a
snapshot parameter at all any more -- a generic assumptions write can never
be paired with an unverified derived-results payload in the same call, full
stop. ``update_deal``/``update_detailed_deal`` also no longer touch the six
snapshot columns in any way (neither writing nor explicitly clearing) --
preservation and invalidation both now fall out for free from the
unchanged read-time fingerprint check described above, whether assumptions
changed (stale snapshot's old fingerprint stops matching) or only Deal
Context changed (the AI snapshot's fingerprint stops matching; the analysis
snapshot's, which never depended on Deal Context, still matches).

``update_analysis_snapshot``/``update_ai_snapshot`` remain the only two
functions that ever write a snapshot column, and are now the *sole*
provenance-validated path any snapshot ever persists through -- including
the "first Save of an unsaved, already-analyzed deal" flow (create the deal,
then attach its current valid snapshot(s) through these) and
``duplicate_deal``'s copy. Each now *requires* the caller to supply the
fingerprint the snapshot was actually produced under (``financial_input_
fingerprint``/``ai_context_fingerprint`` -- an opaque token obtained from
``POST /deals/fingerprint``, computed by ``anchor.deals.fingerprint``, the
same canonical algorithm ``_decode_snapshot`` itself uses; the frontend
never computes it) and independently recomputes the fingerprint the deal's
CURRENTLY STORED assumptions/context actually demand; a mismatch raises
``SnapshotValidationError`` and persists nothing -- the caller's token only
ever *unlocks* a write this function's own recomputation already agrees
with, it can never override it. This requires no schema/migration change:
the six columns and their meaning are unchanged from Gate A6, only the
write-time enforcement is new.

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

import dataclasses
import json
import os
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, get_origin, get_type_hints

from ..ai.contracts import AIAnalysis
from ..contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs, OperatingMode
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults, OperatingProjection
from .contracts import Deal, DealNotFoundError
from .fingerprint import fingerprint_ai, fingerprint_detailed_inputs, fingerprint_quick_inputs

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
#
# Owner Return Metrics V3 Gate A4: schema version 3 adds one nullable
# ``deal_context TEXT`` column to both ``deals`` and ``detailed_deals`` (no
# ``NOT NULL``, no ``DEFAULT`` literal needed -- SQLite backfills every
# existing row's new column with ``NULL``, which is exactly the "no context"
# state a legacy deal should have; never a fabricated default string).
# ``detailed_operating_inputs`` needs no equivalent column: Deal Context is
# deal-level metadata, not a per-mode assumption set.
#
# Owner Return Metrics V3 Gate A6: schema version 4 adds six nullable
# columns to both ``deals`` and ``detailed_deals`` -- ``analysis_snapshot``/
# ``analysis_snapshot_schema_version``/``analysis_snapshot_fingerprint`` and
# the same three for ``ai_snapshot``. All six are nullable with no
# ``DEFAULT`` literal, same reasoning as ``deal_context``: a legacy row
# backfills to ``NULL`` on every one, which is exactly "no cached snapshot
# exists yet" -- never a fabricated cached result.
_SCHEMA_VERSION = 4

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
    deal_context          TEXT,
    analysis_snapshot                   TEXT,
    analysis_snapshot_schema_version    INTEGER,
    analysis_snapshot_fingerprint       TEXT,
    ai_snapshot                         TEXT,
    ai_snapshot_schema_version          INTEGER,
    ai_snapshot_fingerprint             TEXT,
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
    deal_context          TEXT,
    analysis_snapshot                   TEXT,
    analysis_snapshot_schema_version    INTEGER,
    analysis_snapshot_fingerprint       TEXT,
    ai_snapshot                         TEXT,
    ai_snapshot_schema_version          INTEGER,
    ai_snapshot_fingerprint             TEXT,
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

# Owner Return Metrics V3 Gate A6: the six nullable snapshot columns added
# to both ``deals`` and ``detailed_deals`` by schema version 4. Unlike
# ``_V2_MIGRATION_COLUMNS``, none of these take a ``NOT NULL DEFAULT`` --
# they are optional cached data, and SQLite's own ``NULL`` backfill for a
# newly added nullable column is exactly the "no snapshot yet" state.
_SNAPSHOT_MIGRATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("analysis_snapshot", "TEXT"),
    ("analysis_snapshot_schema_version", "INTEGER"),
    ("analysis_snapshot_fingerprint", "TEXT"),
    ("ai_snapshot", "TEXT"),
    ("ai_snapshot_schema_version", "INTEGER"),
    ("ai_snapshot_fingerprint", "TEXT"),
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


# =============================================================================
# Owner Return Metrics V3 Gate A6 -- snapshot serialization, versioning, and
# assumption/context fingerprinting.
#
# Bumped whenever the *stored JSON shape* of a snapshot changes in a way
# older code couldn't read (e.g. a field renamed or removed) -- not on
# every Owner Return Metrics/AI contract change per se, only ones that break
# backward JSON-decoding compatibility. A version mismatch makes
# ``_decode_snapshot`` return ``None`` unconditionally, so a future
# incompatible shape can never crash Deal Open; it just makes the cached
# result unavailable until the analyst re-runs Analyze/Generate AI Analysis.
# =============================================================================

_ANALYSIS_SNAPSHOT_SCHEMA_VERSION = 1
_AI_SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotValidationError(ValueError):
    """Raised when a caller-supplied ``analysis_snapshot``/``ai_snapshot``
    dict cannot be reconstructed into its expected result-contract shape.
    Distinct from a decode failure on an already-*stored* snapshot (which
    ``_decode_snapshot`` swallows and treats as absent, never raises) --
    this is raised only against fresh, caller-supplied input on a write, so
    the API layer can reject it (422) rather than silently persisting or
    silently dropping data the caller explicitly asked to save."""


def _coerce_snapshot_value(hint: Any, value: Any) -> Any:
    if value is None:
        return None
    if get_origin(hint) is tuple:
        # A genuine JSON round-trip (the API layer's normal path) always
        # produces a ``list`` here; ``duplicate_deal``'s internal
        # ``dataclasses.asdict`` round-trip (native Python objects, no JSON
        # involved) preserves the original ``tuple`` instead -- both are
        # accepted and normalized to a tuple, since both are legitimate,
        # already-established call shapes in this module.
        if not isinstance(value, (list, tuple)):
            raise SnapshotValidationError(
                f"Expected a list or tuple for a tuple-typed field, got {type(value).__name__}."
            )
        return tuple(value)
    if dataclasses.is_dataclass(hint):
        return _dataclass_from_json(hint, value)
    return value


def _dataclass_from_json(cls: type, data: Any) -> Any:
    """Reconstruct one instance of the frozen dataclass ``cls`` from a
    JSON-decoded ``dict`` -- the inverse of ``dataclasses.asdict``, handling
    the two shapes ``asdict`` produces that ``cls(**data)`` can't consume
    directly: a tuple-typed field becomes a JSON list (converted back to a
    tuple here) and a nested dataclass field becomes a nested ``dict``
    (reconstructed here recursively). Raises ``SnapshotValidationError`` --
    never a bare ``KeyError``/``TypeError`` -- on any missing field, extra
    field, or wrong-shaped value, so every failure mode is caught by the
    same exception type at every call site."""

    if not isinstance(data, dict):
        raise SnapshotValidationError(
            f"Expected an object for {cls.__name__}, got {type(data).__name__}."
        )

    fields = dataclasses.fields(cls)
    field_names = {field.name for field in fields}
    unexpected = sorted(set(data.keys()) - field_names)
    if unexpected:
        raise SnapshotValidationError(f"Unexpected field(s) for {cls.__name__}: {unexpected}.")

    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for field in fields:
        if field.name not in data:
            raise SnapshotValidationError(f"Missing field {field.name!r} for {cls.__name__}.")
        kwargs[field.name] = _coerce_snapshot_value(hints[field.name], data[field.name])

    try:
        return cls(**kwargs)
    except Exception as error:  # pragma: no cover -- defensive; these contracts have no __post_init__
        raise SnapshotValidationError(f"Could not construct {cls.__name__}: {error}") from error


def _quick_analysis_snapshot_from_dict(data: dict) -> AcquisitionResults:
    return _dataclass_from_json(AcquisitionResults, data)


def _detailed_analysis_snapshot_from_dict(data: dict) -> DetailedAcquisitionResults:
    return _dataclass_from_json(DetailedAcquisitionResults, data)


def _ai_snapshot_from_dict(data: dict) -> AIAnalysis:
    return _dataclass_from_json(AIAnalysis, data)


def _encode_snapshot(value: AcquisitionResults | DetailedAcquisitionResults | AIAnalysis) -> str:
    """Canonical JSON encoding for any snapshot dataclass -- ``asdict``
    recurses into nested dataclasses (``DetailedAcquisitionResults.
    operating_projection``/``.results``) automatically; a tuple field
    serializes as a JSON array, decoded back to a tuple by
    ``_dataclass_from_json`` on the way out."""

    return json.dumps(dataclasses.asdict(value))


def _decode_snapshot(
    *,
    raw_json: str | None,
    stored_schema_version: int | None,
    current_schema_version: int,
    stored_fingerprint: str | None,
    expected_fingerprint: str,
    decoder: Any,
) -> Any:
    """Decode one cached JSON snapshot column, or return ``None`` if it is
    absent, schema-version-incompatible, fingerprint-stale (no longer
    matches the row's current assumptions/context), or malformed in any
    way at all. Never raises -- read-path decoding of an already-stored
    value must never block Deal Open, unlike ``_dataclass_from_json``'s
    strict, raising behavior on a fresh write."""

    if raw_json is None:
        return None
    if stored_schema_version != current_schema_version:
        return None
    if stored_fingerprint != expected_fingerprint:
        return None
    try:
        return decoder(json.loads(raw_json))
    except Exception:
        return None


def _validate_provenance(
    *, provided_fingerprint: str, expected_fingerprint: str, label: str
) -> None:
    """Owner Return Metrics V3 Gate A7 -- the single provenance gate every
    snapshot write must pass through. ``expected_fingerprint`` is always
    computed by the caller from the deal's own currently-*stored*
    assumptions/context (never from the caller-supplied payload, and never
    from values this same call might also be changing) -- see
    ``update_analysis_snapshot``/``update_ai_snapshot`` below, the only two
    functions in this module that ever write a snapshot column. Raises
    ``SnapshotValidationError`` (never silently substitutes the expected
    fingerprint for the provided one, and never persists anything) if they
    disagree, which is exactly the "assumptions changed out from under this
    snapshot" case Gate A7 closes."""

    if provided_fingerprint != expected_fingerprint:
        raise SnapshotValidationError(
            f"{label} does not match the deal's current stored assumptions/context -- "
            "refusing to persist a snapshot whose provenance does not match."
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

    The version-3 (Owner Return Metrics V3 Gate A4) step adds one nullable
    ``deal_context TEXT`` column to *both* ``deals`` and ``detailed_deals``.
    Both use the same column-presence check as the version-2 ``deals``
    columns above (a brand-new database's ``CREATE TABLE`` already declares
    it, so the ``ALTER`` is a no-op there; only a database that predates
    this gate is missing it and gets it added). No ``NOT NULL``/``DEFAULT``
    is specified -- SQLite backfills every existing row's new column with
    ``NULL``, exactly the "no context supplied" state a legacy deal should
    have.

    The version-4 (Owner Return Metrics V3 Gate A6) step adds six nullable
    columns -- ``analysis_snapshot``/``analysis_snapshot_schema_version``/
    ``analysis_snapshot_fingerprint`` and the equivalent three for
    ``ai_snapshot`` -- to *both* ``deals`` and ``detailed_deals``. Same
    column-presence check, same "no DEFAULT, backfills to NULL" reasoning
    as ``deal_context`` above.

    Safe to call on every connection, in any state: a database already at
    ``_SCHEMA_VERSION`` returns immediately at the top.
    """

    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_version >= _SCHEMA_VERSION:
        return

    existing_deal_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(deals)")
    }
    for column_name, column_type, default_literal in _V2_MIGRATION_COLUMNS:
        if column_name not in existing_deal_columns:
            connection.execute(
                f"ALTER TABLE deals ADD COLUMN {column_name} {column_type} "
                f"NOT NULL DEFAULT {default_literal}"
            )
    if "deal_context" not in existing_deal_columns:
        connection.execute("ALTER TABLE deals ADD COLUMN deal_context TEXT")
    for column_name, column_type in _SNAPSHOT_MIGRATION_COLUMNS:
        if column_name not in existing_deal_columns:
            connection.execute(f"ALTER TABLE deals ADD COLUMN {column_name} {column_type}")

    existing_detailed_deal_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(detailed_deals)")
    }
    if "deal_context" not in existing_detailed_deal_columns:
        connection.execute("ALTER TABLE detailed_deals ADD COLUMN deal_context TEXT")
    for column_name, column_type in _SNAPSHOT_MIGRATION_COLUMNS:
        if column_name not in existing_detailed_deal_columns:
            connection.execute(
                f"ALTER TABLE detailed_deals ADD COLUMN {column_name} {column_type}"
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


def _inputs_from_row(row: sqlite3.Row) -> AcquisitionInputs:
    return AcquisitionInputs(
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


def _terms_from_row(row: sqlite3.Row) -> AcquisitionTerms:
    return AcquisitionTerms(
        purchase_price=row["purchase_price"],
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


def _detailed_operating_inputs_from_row(row: sqlite3.Row) -> DetailedOperatingInputs:
    return DetailedOperatingInputs(
        gross_potential_rent=row["gross_potential_rent"],
        other_income=row["other_income"],
        vacancy_credit_loss_pct=row["vacancy_credit_loss_pct"],
        property_taxes=row["property_taxes"],
        insurance=row["insurance"],
        utilities=row["utilities"],
        repairs_maintenance=row["repairs_maintenance"],
        other_operating_expenses=row["other_operating_expenses"],
        management_fee_pct=row["management_fee_pct"],
        revenue_growth=row["revenue_growth"],
        expense_growth=row["expense_growth"],
    )


def _row_to_deal(row: sqlite3.Row, *, include_snapshots: bool = True) -> Deal:
    """``include_snapshots=False`` (used by ``list_deals``) skips decoding
    the cached snapshot columns entirely, always returning
    ``analysis_snapshot=None``/``ai_snapshot=None`` regardless of what is
    stored -- the Deal Library list is a lightweight per-deal summary
    (name, mode, timestamps); it must never balloon with every saved
    deal's full cached result/AI JSON. ``get_deal`` (single-deal fetch)
    always decodes them (the default)."""

    inputs = _inputs_from_row(row)
    deal_context = row["deal_context"]
    if not include_snapshots:
        analysis_snapshot = None
        ai_snapshot = None
    else:
        analysis_fingerprint = fingerprint_quick_inputs(inputs)
        analysis_snapshot = _decode_snapshot(
            raw_json=row["analysis_snapshot"],
            stored_schema_version=row["analysis_snapshot_schema_version"],
            current_schema_version=_ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
            stored_fingerprint=row["analysis_snapshot_fingerprint"],
            expected_fingerprint=analysis_fingerprint,
            decoder=_quick_analysis_snapshot_from_dict,
        )
        ai_snapshot = _decode_snapshot(
            raw_json=row["ai_snapshot"],
            stored_schema_version=row["ai_snapshot_schema_version"],
            current_schema_version=_AI_SNAPSHOT_SCHEMA_VERSION,
            stored_fingerprint=row["ai_snapshot_fingerprint"],
            expected_fingerprint=fingerprint_ai(
                analysis_fingerprint=analysis_fingerprint, deal_context=deal_context
            ),
            decoder=_ai_snapshot_from_dict,
        )
    return Deal(
        id=row["id"],
        name=row["name"],
        operating_mode=OperatingMode.QUICK,
        inputs=inputs,
        terms=None,
        detailed_operating_inputs=None,
        deal_context=deal_context,
        analysis_snapshot=analysis_snapshot,
        ai_snapshot=ai_snapshot,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_detailed_deal(
    deal_row: sqlite3.Row, operating_row: sqlite3.Row, *, include_snapshots: bool = True
) -> Deal:
    """``include_snapshots`` mirrors ``_row_to_deal``'s parameter exactly."""

    terms = _terms_from_row(deal_row)
    detailed_operating_inputs = _detailed_operating_inputs_from_row(operating_row)
    deal_context = deal_row["deal_context"]
    if not include_snapshots:
        analysis_snapshot = None
        ai_snapshot = None
    else:
        analysis_fingerprint = fingerprint_detailed_inputs(terms, detailed_operating_inputs)
        analysis_snapshot = _decode_snapshot(
            raw_json=deal_row["analysis_snapshot"],
            stored_schema_version=deal_row["analysis_snapshot_schema_version"],
            current_schema_version=_ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
            stored_fingerprint=deal_row["analysis_snapshot_fingerprint"],
            expected_fingerprint=analysis_fingerprint,
            decoder=_detailed_analysis_snapshot_from_dict,
        )
        ai_snapshot = _decode_snapshot(
            raw_json=deal_row["ai_snapshot"],
            stored_schema_version=deal_row["ai_snapshot_schema_version"],
            current_schema_version=_AI_SNAPSHOT_SCHEMA_VERSION,
            stored_fingerprint=deal_row["ai_snapshot_fingerprint"],
            expected_fingerprint=fingerprint_ai(
                analysis_fingerprint=analysis_fingerprint, deal_context=deal_context
            ),
            decoder=_ai_snapshot_from_dict,
        )
    return Deal(
        id=deal_row["id"],
        name=deal_row["name"],
        operating_mode=OperatingMode.DETAILED,
        inputs=None,
        terms=terms,
        detailed_operating_inputs=detailed_operating_inputs,
        deal_context=deal_context,
        analysis_snapshot=analysis_snapshot,
        ai_snapshot=ai_snapshot,
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
    deal_context: str | None = None,
    db_path: Path | None = None,
) -> Deal:
    """Insert a new Quick deal and return it as stored. ``inputs`` must
    already be an ``AcquisitionInputs`` instance -- this function performs
    no validation of its own; the caller (the API layer, matching every
    other endpoint) is responsible for having called
    ``validate_acquisition_inputs`` first. Unchanged by Detailed Operating
    Model V2.1 -- inserts into ``deals`` only.

    ``deal_context`` (Gate A4) is optional, user-authored free text -- never
    validated as a financial input, since it isn't one. Defaults to
    ``None`` (no context supplied), never a fabricated default string.

    Owner Return Metrics V3 Gate A7: this function never accepts a snapshot.
    A brand-new row always starts with no cached analysis/AI (the six
    snapshot columns default to SQL ``NULL``, exactly "no snapshot yet") --
    a generic assumptions write is never also trusted to carry an arbitrary,
    unverified derived-results payload alongside it (the Gate A6 trust
    boundary this gate closes). To persist a deal's *current, valid*
    analysis/AI immediately after creating it (the "first Save of an
    unsaved, already-analyzed deal" flow), call ``update_analysis_snapshot``/
    ``update_ai_snapshot`` against the id this function returns -- both are
    independently provenance-validated against this row's own just-stored
    ``inputs``, so a mismatched snapshot is rejected exactly as it would be
    on any other deal."""

    deal_id = uuid.uuid4().hex
    now = _utc_now_iso()

    with _connect(db_path) as connection:
        connection.execute(
            f"""
            INSERT INTO deals
                (id, name, {", ".join(_INPUT_COLUMNS)}, deal_context, created_at, updated_at)
            VALUES (?, ?, {", ".join("?" for _ in _INPUT_COLUMNS)}, ?, ?, ?)
            """,
            (deal_id, name, *_input_values(inputs), deal_context, now, now),
        )

    return get_deal(deal_id, db_path=db_path)


def update_deal(
    deal_id: str,
    name: str,
    inputs: AcquisitionInputs,
    *,
    deal_context: str | None = None,
    db_path: Path | None = None,
) -> Deal:
    """Overwrite ``deal_id``'s name, inputs, and Deal Context (Gate A4),
    bump ``updated_at``, and return the updated Quick deal. Raises
    ``DealNotFoundError`` if it doesn't exist in ``deals`` -- unchanged by
    Detailed Operating Model V2.1, including for a ``deal_id`` that belongs
    to a Detailed deal (that id is never a row in ``deals``, so this
    correctly reports it as not found rather than silently succeeding
    against the wrong table).

    Owner Return Metrics V3 Gate A7: this function never touches the six
    snapshot columns at all -- neither writing a caller-supplied value nor
    explicitly clearing one. That is deliberate, and is what closes the
    Gate A6 trust boundary: this call's fresh ``inputs``/``deal_context``
    can never be paired, in the same write, with an unverified snapshot the
    caller merely *claims* corresponds to them. Instead, invalidation and
    preservation both fall out for free from ``get_deal``'s existing
    read-time fingerprint check (unchanged by this gate): if ``inputs``
    changed, whatever snapshot was already stored no longer fingerprint-
    matches the new ``inputs`` and is silently treated as absent on the next
    read; if only ``deal_context`` changed, the analysis snapshot's
    fingerprint (which never depends on Deal Context) still matches and is
    preserved, while the AI snapshot's fingerprint (which does depend on
    Deal Context) no longer matches and is treated as absent -- exactly the
    Gate A4 invalidation rules, with zero explicit clearing logic here."""

    now = _utc_now_iso()

    with _connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE deals
            SET name = ?, {", ".join(f"{column} = ?" for column in _INPUT_COLUMNS)},
                deal_context = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (name, *_input_values(inputs), deal_context, now, deal_id),
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
    deal_context: str | None = None,
    db_path: Path | None = None,
) -> Deal:
    """Insert a new Detailed deal and return it as stored. ``terms`` and
    ``detailed_operating_inputs`` must already be validated instances --
    same no-revalidation contract as ``create_deal``. Writes both the
    ``detailed_deals`` row and its 1:1 ``detailed_operating_inputs`` row in
    the same connection/transaction -- never one without the other. Never
    creates or touches a row in ``deals``.

    ``deal_context`` (Gate A4) mirrors ``create_deal``'s parameter exactly
    -- optional, user-authored, never validated as a financial input.

    Owner Return Metrics V3 Gate A7: mirrors ``create_deal``'s
    no-snapshot-parameter contract exactly -- see its docstring."""

    deal_id = uuid.uuid4().hex
    now = _utc_now_iso()

    with _connect(db_path) as connection:
        connection.execute(
            f"""
            INSERT INTO detailed_deals
                (id, name, {", ".join(_TERMS_COLUMNS)}, deal_context, created_at, updated_at)
            VALUES (?, ?, {", ".join("?" for _ in _TERMS_COLUMNS)}, ?, ?, ?)
            """,
            (deal_id, name, *_terms_values(terms), deal_context, now, now),
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
    deal_context: str | None = None,
    db_path: Path | None = None,
) -> Deal:
    """Overwrite ``deal_id``'s name, terms, detailed operating inputs, and
    Deal Context (Gate A4), bump ``updated_at``, and return the updated
    Detailed deal. Raises ``DealNotFoundError`` if it doesn't exist in
    ``detailed_deals``.

    Owner Return Metrics V3 Gate A7: mirrors ``update_deal``'s
    never-touches-snapshot-columns contract exactly -- see its docstring."""

    now = _utc_now_iso()

    with _connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE detailed_deals
            SET name = ?, {", ".join(f"{column} = ?" for column in _TERMS_COLUMNS)},
                deal_context = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (name, *_terms_values(terms), deal_context, now, deal_id),
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
    updated first.

    Owner Return Metrics V3 Gate A6: every returned ``Deal`` has
    ``analysis_snapshot=None``/``ai_snapshot=None`` regardless of what is
    cached -- the Deal Library list is a lightweight summary (name, mode,
    timestamps) for every saved deal; it must not carry each one's full
    cached result/AI JSON merely to render a list row. Call ``get_deal``
    for one deal's full snapshots (e.g. when opening it)."""

    with _connect(db_path) as connection:
        quick_rows = connection.execute("SELECT * FROM deals").fetchall()
        detailed_rows = connection.execute("SELECT * FROM detailed_deals").fetchall()
        operating_rows_by_deal_id = {
            row["deal_id"]: row
            for row in connection.execute("SELECT * FROM detailed_operating_inputs")
        }

    quick_deals = [_row_to_deal(row, include_snapshots=False) for row in quick_rows]
    detailed_deals = [
        _row_to_detailed_deal(
            row, operating_rows_by_deal_id[row["id"]], include_snapshots=False
        )
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
    Raises ``DealNotFoundError`` if ``deal_id`` doesn't exist. Reuses
    ``get_deal``/``create_deal``/``create_detailed_deal`` rather than a
    bespoke SQL copy, so the new deal is generated by the exact same
    id/timestamp logic as any other created deal, with no separate path to
    keep in sync. Preserves ``deal_context`` (Gate A4) exactly, including
    ``None``, like every other field.

    Owner Return Metrics V3 Gate A6/A7: also copies ``analysis_snapshot``/
    ``ai_snapshot`` when the original has a valid one -- both are
    mathematically/contextually still valid for the copy, since the copy's
    assumptions and Deal Context start out byte-identical to the
    original's. Rather than trusting that verbatim (the Gate A6 combined-
    write path Gate A7 closes everywhere else), the copy is created with no
    snapshot at all and then, if the original had a valid one, attached
    through the same provenance-validated ``update_analysis_snapshot``/
    ``update_ai_snapshot`` path every other snapshot write now goes
    through -- passing the fingerprint recomputed from ``original``'s own
    ``inputs``/``terms``+``detailed_operating_inputs`` (and, for AI,
    ``deal_context``) as the provenance token. Because ``original``'s
    snapshot only ever decoded successfully (non-``None`` on a ``Deal``) by
    already fingerprint-matching those exact values (see ``_decode_snapshot``),
    and the new row's assumptions/context are byte-identical copies of them,
    this recomputed fingerprint is guaranteed to match the new row too -- the
    copy always succeeds, never spuriously rejected. The very first edit to
    the copy's assumptions or Deal Context invalidates its (independent)
    copy exactly like any other change -- see ``update_deal``."""

    original = get_deal(deal_id, db_path=db_path)
    new_name = name if name else f"{original.name} (Copy)"

    if original.operating_mode is OperatingMode.QUICK:
        assert original.inputs is not None
        new_deal = create_deal(
            new_name, original.inputs, deal_context=original.deal_context, db_path=db_path
        )
        analysis_fingerprint = fingerprint_quick_inputs(original.inputs)
    else:
        assert original.terms is not None
        assert original.detailed_operating_inputs is not None
        new_deal = create_detailed_deal(
            new_name,
            original.terms,
            original.detailed_operating_inputs,
            deal_context=original.deal_context,
            db_path=db_path,
        )
        analysis_fingerprint = fingerprint_detailed_inputs(
            original.terms, original.detailed_operating_inputs
        )

    if original.analysis_snapshot is not None:
        new_deal = update_analysis_snapshot(
            new_deal.id,
            dataclasses.asdict(original.analysis_snapshot),
            financial_input_fingerprint=analysis_fingerprint,
            db_path=db_path,
        )

    if original.ai_snapshot is not None:
        new_deal = update_ai_snapshot(
            new_deal.id,
            dataclasses.asdict(original.ai_snapshot),
            ai_context_fingerprint=fingerprint_ai(
                analysis_fingerprint=analysis_fingerprint, deal_context=original.deal_context
            ),
            db_path=db_path,
        )

    return new_deal


# =============================================================================
# Owner Return Metrics V3 Gate A6 / Gate A7 -- provenance-validated snapshot
# writes
#
# The ONLY two functions in this module that ever write to a snapshot
# column. Each updates *only* its one snapshot column, leaving name,
# assumptions, Deal Context, the *other* snapshot, and ``updated_at``
# completely untouched -- unchanged from Gate A6.
#
# Gate A7: each also now REQUIRES the caller to supply the provenance
# fingerprint the snapshot was actually produced under (obtained from
# ``POST /deals/fingerprint`` at the moment the analysis/AI ran -- see
# ``anchor.api``), and independently recomputes the fingerprint the deal's
# CURRENTLY STORED assumptions/context actually demand. The two must match
# exactly, or the write is rejected (``SnapshotValidationError``) and
# nothing is persisted. This is what makes both endpoints safe to call for
# every snapshot write this module ever performs -- the silent background
# cache refresh (an already-saved, not-dirty deal), the deliberate
# provenance-validated first-Save-of-an-unsaved-deal path, and
# ``duplicate_deal``'s copy -- without ever trusting a caller-supplied
# fingerprint at face value: the caller's token only ever *unlocks* a write
# that this function's own fingerprint recomputation already agrees with;
# it can never override it.
# =============================================================================


def update_analysis_snapshot(
    deal_id: str,
    analysis_snapshot: dict[str, Any],
    *,
    financial_input_fingerprint: str,
    db_path: Path | None = None,
) -> Deal:
    """Update only ``deal_id``'s cached deterministic-analysis snapshot.

    ``financial_input_fingerprint`` must equal the canonical fingerprint of
    ``deal_id``'s own currently-stored ``inputs`` (Quick) or ``terms``+
    ``detailed_operating_inputs`` (Detailed) -- i.e. it must originate from
    the same assumptions that are actually stored for this deal right now,
    not from any other assumption set the caller might have on hand.
    Raises ``SnapshotValidationError`` (persisting nothing) if it does not,
    or if ``analysis_snapshot`` is malformed for that deal's operating mode.
    Raises ``DealNotFoundError`` if ``deal_id`` doesn't exist in either
    table."""

    # ``get_deal`` (below) opens its own connection -- it must run only
    # after this ``with`` block has exited and committed, never nested
    # inside it (an uncommitted write is invisible to a second connection
    # against the same on-disk file). Every branch below therefore falls
    # through to one ``return get_deal(...)`` after the block, rather than
    # returning from inside it.
    with _connect(db_path) as connection:
        quick_row = connection.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
        if quick_row is not None:
            expected_fingerprint = fingerprint_quick_inputs(_inputs_from_row(quick_row))
            _validate_provenance(
                provided_fingerprint=financial_input_fingerprint,
                expected_fingerprint=expected_fingerprint,
                label="analysis_snapshot's financial_input_fingerprint",
            )
            encoded = _encode_snapshot(_quick_analysis_snapshot_from_dict(analysis_snapshot))
            connection.execute(
                """
                UPDATE deals
                SET analysis_snapshot = ?, analysis_snapshot_schema_version = ?,
                    analysis_snapshot_fingerprint = ?
                WHERE id = ?
                """,
                (encoded, _ANALYSIS_SNAPSHOT_SCHEMA_VERSION, expected_fingerprint, deal_id),
            )
        else:
            detailed_row = connection.execute(
                "SELECT * FROM detailed_deals WHERE id = ?", (deal_id,)
            ).fetchone()
            if detailed_row is None:
                raise DealNotFoundError(deal_id)
            operating_row = connection.execute(
                "SELECT * FROM detailed_operating_inputs WHERE deal_id = ?", (deal_id,)
            ).fetchone()
            if operating_row is None:
                raise DealNotFoundError(deal_id)

            expected_fingerprint = fingerprint_detailed_inputs(
                _terms_from_row(detailed_row), _detailed_operating_inputs_from_row(operating_row)
            )
            _validate_provenance(
                provided_fingerprint=financial_input_fingerprint,
                expected_fingerprint=expected_fingerprint,
                label="analysis_snapshot's financial_input_fingerprint",
            )
            encoded = _encode_snapshot(_detailed_analysis_snapshot_from_dict(analysis_snapshot))
            connection.execute(
                """
                UPDATE detailed_deals
                SET analysis_snapshot = ?, analysis_snapshot_schema_version = ?,
                    analysis_snapshot_fingerprint = ?
                WHERE id = ?
                """,
                (encoded, _ANALYSIS_SNAPSHOT_SCHEMA_VERSION, expected_fingerprint, deal_id),
            )

    return get_deal(deal_id, db_path=db_path)


def update_ai_snapshot(
    deal_id: str,
    ai_snapshot: dict[str, Any],
    *,
    ai_context_fingerprint: str,
    db_path: Path | None = None,
) -> Deal:
    """Update only ``deal_id``'s cached AI Analyst snapshot.

    ``ai_context_fingerprint`` must equal the canonical AI-context
    fingerprint derived from ``deal_id``'s own currently-stored financial
    assumptions AND currently-stored ``deal_context`` -- i.e. it must
    originate from the same assumptions+context this deal actually has
    right now. Raises ``SnapshotValidationError`` (persisting nothing) if it
    does not, or if ``ai_snapshot`` is malformed. Raises
    ``DealNotFoundError`` if ``deal_id`` doesn't exist in either table."""

    encoded = _encode_snapshot(_ai_snapshot_from_dict(ai_snapshot))

    # See ``update_analysis_snapshot``'s comment above: ``get_deal`` must
    # run only after this ``with`` block commits, never nested inside it.
    with _connect(db_path) as connection:
        quick_row = connection.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
        if quick_row is not None:
            analysis_fingerprint = fingerprint_quick_inputs(_inputs_from_row(quick_row))
            expected_fingerprint = fingerprint_ai(
                analysis_fingerprint=analysis_fingerprint, deal_context=quick_row["deal_context"]
            )
            _validate_provenance(
                provided_fingerprint=ai_context_fingerprint,
                expected_fingerprint=expected_fingerprint,
                label="ai_snapshot's ai_context_fingerprint",
            )
            connection.execute(
                """
                UPDATE deals
                SET ai_snapshot = ?, ai_snapshot_schema_version = ?, ai_snapshot_fingerprint = ?
                WHERE id = ?
                """,
                (encoded, _AI_SNAPSHOT_SCHEMA_VERSION, expected_fingerprint, deal_id),
            )
        else:
            detailed_row = connection.execute(
                "SELECT * FROM detailed_deals WHERE id = ?", (deal_id,)
            ).fetchone()
            if detailed_row is None:
                raise DealNotFoundError(deal_id)
            operating_row = connection.execute(
                "SELECT * FROM detailed_operating_inputs WHERE deal_id = ?", (deal_id,)
            ).fetchone()
            if operating_row is None:
                raise DealNotFoundError(deal_id)

            analysis_fingerprint = fingerprint_detailed_inputs(
                _terms_from_row(detailed_row), _detailed_operating_inputs_from_row(operating_row)
            )
            expected_fingerprint = fingerprint_ai(
                analysis_fingerprint=analysis_fingerprint, deal_context=detailed_row["deal_context"]
            )
            _validate_provenance(
                provided_fingerprint=ai_context_fingerprint,
                expected_fingerprint=expected_fingerprint,
                label="ai_snapshot's ai_context_fingerprint",
            )
            connection.execute(
                """
                UPDATE detailed_deals
                SET ai_snapshot = ?, ai_snapshot_schema_version = ?, ai_snapshot_fingerprint = ?
                WHERE id = ?
                """,
                (encoded, _AI_SNAPSHOT_SCHEMA_VERSION, expected_fingerprint, deal_id),
            )

    return get_deal(deal_id, db_path=db_path)
