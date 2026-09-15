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
the AI fingerprint, ``deal_context`` too -- that produced it). Sprint B
Gate B4 adds no column and no schema version: the concise ``DealStory``
lives *inside* ``AIAnalysis`` (``anchor.ai.contracts``), so it persists,
restores, invalidates, duplicates, and validates its provenance through
the existing ``ai_snapshot`` column and the existing
``ai_context_fingerprint``, with no parallel persistence system. A
pre-B4 ``ai_snapshot`` JSON simply has no ``deal_story`` key and decodes
to ``deal_story=None`` (see ``_dataclass_from_json``'s
default-tolerance), so no stored snapshot is orphaned. A snapshot
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
from enum import Enum
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from ..ai.contracts import AIAnalysis
from ..business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
    require_valid_business_plan,
    validate_business_plan,
)
from ..analysis import (
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecoveryBasis,
    Suite,
)
from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
    UnsupportedOperatingModeError,
)
from ..analysis.scenario import (
    ScenarioDefinition,
    ScenarioIssue,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    ScenarioValidationError,
    validate_investment_scenario,
    validate_scenario,
)
from ..analysis.strategy import (
    BASE_SCENARIO_ID,
    AcquisitionChoice,
    DispositionChoice,
    FinancingChoice,
    OperatingOutcome,
    OperatingOutcomeSet,
    StrategyDefinition,
    StrategyDomain,
    StrategyIssue,
    StrategyOverlay,
    StrategyValidationError,
    validate_investment_strategy,
    validate_strategy,
)
from ..engine.contracts import (
    AcquisitionResults,
    DetailedAcquisitionResults,
    IrrStatus,
    OperatingProjection,
)
from ..investment import (
    InvestmentIssue,
    InvestmentIssueCode,
    InvestmentTransactionCost,
    InvestmentUnitMembership,
    InvestmentValidationError,
    TransactionCostCategory,
    UnitEconomicFacts,
    UnitKind,
    validate_investment_inputs,
    validate_unit_memberships,
    validate_variant_economics,
)
from .contracts import (
    Deal,
    DealNotFoundError,
    Investment,
    InvestmentNotFoundError,
    InvestmentScenario,
    InvestmentStrategy,
    InvestmentStructureError,
    InvestmentUnit,
    InvestmentUnitNotFoundError,
    OneWaySensitivitySnapshot,
    ScenarioNotFoundError,
    StrategyNotFoundError,
    TwoWaySensitivitySnapshot,
    VisibleInvestment,
)
from .fingerprint import (
    fingerprint_ai,
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)

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
# Sprint D5.8A: schema version 6 adds one purely additive table,
# ``deal_sensitivity_snapshots``, created unconditionally by ``_connect`` via
# CREATE TABLE IF NOT EXISTS exactly as the Detailed pair was at version 2 and
# the Lease-Level family at version 5. No ALTER, no existing row read or
# rewritten, and the new table simply starts empty for every deal that already
# exists.
# Phase 6 Gate D6.5: schema version 7 adds the two mode-blind Business Plan
# child tables, ``deal_capital_plan_items`` and ``deal_owner_expense_items``,
# created unconditionally by ``_connect`` exactly as version 6's table was. No
# ALTER and no existing row read or rewritten; a legacy deal simply has no plan
# rows, which is exactly the empty ``BusinessPlan()`` -- nothing is fabricated.
# Phase 7 Gate P7.2: schema version 8 adds five purely additive P7 tables --
# ``investments``, ``investment_units``, ``scenarios``, ``scenario_overrides``
# and ``variant_snapshots`` -- created unconditionally by ``_connect`` exactly
# as version 7's were. No ALTER and no existing row read or rewritten; every
# legacy deal simply belongs to no Investment until the analyst opts in (Q4).
# Phase 7 Gate P7.4: schema version 9 adds eight purely additive Strategy
# tables -- ``strategies``, one typed table per overlay domain, and the Business
# Plan overlay's two item tables -- created unconditionally by ``_connect``
# exactly as version 8's were. No ALTER and no existing row read or rewritten:
# no Deal, Scenario, override or cached variant changes, and a Deal gains a
# Strategy only when the analyst opts in.
# Phase 7 Gate P7.6: schema version 10 adds five purely additive sidecar tables
# for the visible Investment -- its details, its Units' membership details, its
# Business Plan items and its transaction costs -- created unconditionally by
# ``_connect`` exactly as version 9's were. No ALTER of ``investments`` or
# ``investment_units`` or any other table, and no existing row read or
# rewritten: every hidden wrapper simply has no sidecar row, which is exactly
# its neutral state, and none is created by reading it.
_SCHEMA_VERSION = 10


class PersistedDealDataError(RuntimeError):
    """Stored data could not be decoded into an authoritative contract.

    Distinct from a validation error, which describes something a *caller*
    submitted and can fix. This describes the database disagreeing with the code
    -- an enum token no longer in the enum, an override JSON that will not parse,
    a parent row whose children are missing.

    Raised rather than repaired. A store that quietly substituted a default for
    an unreadable ``lease_type`` would hand the engine a rent roll nobody
    authored, and the resulting numbers would look entirely ordinary.
    """


class PersistedScenarioDataError(PersistedDealDataError):
    """A stored Scenario no longer passes the P7.1 contract validation.

    ``issues`` is the P7.1 validator's own ordered list -- identity first, then
    unit, then target registry order -- so which problem is reported first
    never depends on the order SQLite returns rows in."""

    def __init__(self, scenario_id: str, issues: Iterable[ScenarioIssue]) -> None:
        self.scenario_id = scenario_id
        self.issues = tuple(issues)
        super().__init__(
            f"Stored scenario {scenario_id!r} does not validate: "
            + "; ".join(issue.message for issue in self.issues)
        )


class PersistedStrategyDataError(PersistedDealDataError):
    """A stored Strategy no longer passes the P7.4 contract validation.

    ``issues`` is the P7.4 validator's own ordered list -- identity first, then
    domain declaration order and unit -- so which problem is reported first
    never depends on the order SQLite returns rows in."""

    def __init__(self, strategy_id: str, issues: Iterable[StrategyIssue]) -> None:
        self.strategy_id = strategy_id
        self.issues = tuple(issues)
        super().__init__(
            f"Stored strategy {strategy_id!r} does not validate: "
            + "; ".join(issue.message for issue in self.issues)
        )


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

# =============================================================================
# Sprint D5.4 -- Lease-Level persistence, schema version 5.
#
# Six tables, following the Detailed precedent exactly: a new table family per
# mode rather than a discriminator column, because ``operating_mode`` is not
# stored anywhere -- it is inferred from which table a row lives in. That keeps
# ``deals`` and ``detailed_deals`` byte-untouched by this gate.
#
# Fixed-arity contracts stay flat and typed, so SQLite stores a float as a REAL
# and returns it bit-identical. Only the two genuinely variable-arity
# collections become relational rows.
#
# The single JSON column is ``lease_level_suites.market_leasing_override``, and
# it is JSON because the domain says the record is atomic: a suite supplies a
# whole ``MarketLeasingAssumptions`` or none of one (D0 24.2). Twenty-three
# nullable columns would make a *partial* override representable in storage,
# which the domain forbids -- the shape would permit a state no analyst can
# author and no validator would catch.
#
# No ON DELETE CASCADE is declared: this module never enables
# ``PRAGMA foreign_keys``, matching its existing posture, so a declared cascade
# would be decorative. Child rows are deleted explicitly, in the same
# transaction as the parent, exactly as ``detailed_operating_inputs`` already is.
# =============================================================================

_CREATE_LEASE_LEVEL_DEALS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lease_level_deals (
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
    ai_snapshot                         TEXT,
    ai_snapshot_schema_version          INTEGER,
    ai_snapshot_fingerprint             TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
)
"""

# Deliberately no ``analysis_snapshot`` columns. D5 decision A: Lease-Level
# results are recomputed from approved inputs on open, so there is no cached
# financial artifact to store, to go stale, or to be served as current. Absent
# columns are a stronger guarantee than an unused nullable one -- there is
# nowhere for a future gate to put one by accident.

_CREATE_LEASE_LEVEL_PROPERTY_INPUTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lease_level_property_inputs (
    deal_id              TEXT PRIMARY KEY REFERENCES lease_level_deals(id),
    analysis_start_date  TEXT NOT NULL,
    rentable_area_sf     REAL NOT NULL
)
"""

_CREATE_LEASE_LEVEL_OPERATING_INPUTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lease_level_operating_inputs (
    deal_id                    TEXT PRIMARY KEY REFERENCES lease_level_deals(id),
    other_income               REAL NOT NULL,
    other_income_growth        REAL NOT NULL,
    credit_loss_pct            REAL NOT NULL,
    property_taxes             REAL NOT NULL,
    insurance                  REAL NOT NULL,
    utilities                  REAL NOT NULL,
    repairs_maintenance        REAL NOT NULL,
    other_operating_expenses   REAL NOT NULL,
    management_fee_pct         REAL NOT NULL,
    expense_growth             REAL NOT NULL,
    recoverable_expense_ratio  REAL NOT NULL
)
"""

_CREATE_LEASE_LEVEL_MARKET_LEASING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lease_level_market_leasing (
    deal_id                    TEXT PRIMARY KEY REFERENCES lease_level_deals(id),
    market_rent_psf            REAL NOT NULL,
    market_rent_growth         REAL NOT NULL,
    renewal_rent_psf           REAL,
    renewal_rent_spread        REAL NOT NULL,
    renewal_term_months        INTEGER NOT NULL,
    successor_escalation_pct   REAL NOT NULL,
    renewal_downtime_months    REAL NOT NULL,
    renewal_free_rent_months   REAL NOT NULL,
    new_term_months            INTEGER NOT NULL,
    new_downtime_months        REAL NOT NULL,
    new_free_rent_months       REAL NOT NULL,
    renewal_ti_psf             REAL NOT NULL,
    new_ti_psf                 REAL NOT NULL,
    leasing_commission_method  TEXT NOT NULL,
    renewal_lc_pct             REAL NOT NULL,
    new_lc_pct                 REAL NOT NULL,
    renewal_probability        REAL NOT NULL,
    renewal_lease_type         TEXT NOT NULL,
    renewal_recovery_basis     TEXT,
    renewal_expense_stop_psf   REAL,
    new_lease_type             TEXT NOT NULL,
    new_recovery_basis         TEXT,
    new_expense_stop_psf       REAL
)
"""

# ``ordinal`` is display metadata: it preserves the order the analyst entered
# the rent roll in, and is excluded from the economic fingerprint, so reordering
# rows never invalidates a snapshot. The composite primary key is the domain's
# own identity rule -- one suite id per deal -- and nothing more. No CHECK
# constraint restates a financial domain: ``renewal_probability`` bounds belong
# to the D2 validator, in one place.
_CREATE_LEASE_LEVEL_SUITES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lease_level_suites (
    deal_id                  TEXT NOT NULL REFERENCES lease_level_deals(id),
    suite_id                 TEXT NOT NULL,
    ordinal                  INTEGER NOT NULL,
    suite_area_sf            REAL NOT NULL,
    suite_label              TEXT,
    market_rent_psf          REAL,
    market_leasing_override  TEXT,
    initial_vacancy_strategy            TEXT,
    initial_vacancy_lease_up_months     REAL,
    PRIMARY KEY (deal_id, suite_id)
)
"""

_CREATE_LEASE_LEVEL_LEASES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lease_level_leases (
    deal_id                 TEXT NOT NULL REFERENCES lease_level_deals(id),
    lease_id                TEXT NOT NULL,
    ordinal                 INTEGER NOT NULL,
    suite_id                TEXT NOT NULL,
    leased_area_sf          REAL NOT NULL,
    rent_commencement_date  TEXT NOT NULL,
    lease_expiration_date   TEXT NOT NULL,
    base_rent_psf           REAL NOT NULL,
    escalation_pct          REAL NOT NULL,
    escalation_basis        TEXT NOT NULL,
    lease_type              TEXT NOT NULL,
    tenant_name             TEXT,
    lease_start_date        TEXT,
    origin                  TEXT NOT NULL,
    recovery_basis          TEXT,
    expense_stop_psf        REAL,
    PRIMARY KEY (deal_id, lease_id)
)
"""

# =============================================================================
# Sprint D5.8A -- persisted derived analytical state, schema version 6.
#
# One table, not one per analysis type and not a column family on each mode's
# parent row.
#
# **Why its own table rather than more columns.** ``analysis_snapshot`` and
# ``ai_snapshot`` are single-valued per deal, so a column pair each was the
# smallest thing that worked (Gate A6). Sensitivity is not: a deal holds a
# latest one-way *and* a latest two-way, independently, and running one must
# never disturb the other. Two rows discriminated by ``analysis_kind`` make that
# independence structural -- there is no single row a write could clobber -- and
# it costs one table instead of six columns on each of three parent tables.
#
# **Operating-mode identity comes for free.** A deal id lives in exactly one of
# ``deals``/``detailed_deals``/``lease_level_deals`` (all three mint fresh
# ``uuid4`` hex strings), so the mode is already determined by which table holds
# the id -- the same rule this module has used since the Detailed split. A
# second, stored copy of the mode here would be a value that could disagree with
# it, so there is none. D5.8A writes only Lease-Level rows; the table is
# mode-blind so a later gate can adopt it without a migration.
#
# **The payload is one atomic versioned JSON document.** ``snapshot`` holds the
# whole ``{configuration, result}`` pair, so a configuration can never be
# persisted beside another run's result -- they are written and read as one
# value or not at all. This is a DERIVED snapshot, exactly like ``ai_snapshot``;
# it authorises nothing about how Suites, Leases or assumptions are stored,
# which stay relational and untouched.
#
# ``source_fingerprint`` is the canonical financial-input fingerprint of the
# assumptions the run was actually performed against (never the AI-context one:
# a sensitivity run reads no ``deal_context``). ``schema_version`` lets a future
# contract change invalidate old rows rather than crash on them.
#
# No ON DELETE CASCADE, for the reason stated above ``lease_level_suites``: this
# module never enables ``PRAGMA foreign_keys``, so a declared cascade would be
# decorative and would leave orphan rows behind a schema that looked safe.
# ``delete_deal`` removes these rows explicitly, in the same transaction as the
# parent.
# =============================================================================

_ONE_WAY_KIND = "one_way"
_TWO_WAY_KIND = "two_way"

_CREATE_DEAL_SENSITIVITY_SNAPSHOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS deal_sensitivity_snapshots (
    deal_id            TEXT NOT NULL,
    analysis_kind      TEXT NOT NULL,
    snapshot           TEXT NOT NULL,
    schema_version     INTEGER NOT NULL,
    source_fingerprint TEXT NOT NULL,
    generated_at       TEXT NOT NULL,
    PRIMARY KEY (deal_id, analysis_kind)
)
"""


# =============================================================================
# Phase 6 Gate D6.5 -- the Business Plan, schema version 7.
#
# Two MODE-BLIND relational child tables, one per item type, keyed by the deal
# id alone. The Business Plan is the same contract in all three modes (D6
# conventions Section 13), so it is stored once, the same way, whichever parent
# table holds the deal -- never as Quick, Detailed and Lease-Level copies, and
# never folded into a mode's own columns. Like ``deal_sensitivity_snapshots``,
# no mode is stored here: the mode is which parent table holds the id.
#
# Relational rather than one JSON document, following the rent roll: a plan is
# variable-arity *input* state, and each field gets a typed column so SQLite
# stores a float as a REAL and returns it bit-identical.
#
# ``ordinal`` is presentation state -- the analyst's row order, restored on
# load -- and nothing else: no calculation reads it and the fingerprint sorts
# by ``item_id`` instead (``anchor.deals.fingerprint``). ``last_year`` is
# nullable because ``None`` ("through the current hold") is a value the resolver
# owns; it is stored as ``NULL`` and never replaced by the hold period.
#
# The composite primary key is the per-collection identity rule and nothing
# more. The one shared item-ID namespace across *both* tables (decision D17) is
# the validation authority's rule and is not restated in SQL: every write is
# validated before it reaches a table, and every read is validated again, so a
# stored cross-type duplicate is refused on load rather than silently loaded.
# No CHECK constraint restates a financial domain, for the same reason.
#
# No FOREIGN KEY / ON DELETE CASCADE, for the reason stated above
# ``lease_level_suites``: this module never enables ``PRAGMA foreign_keys``, so a
# declared cascade would be decorative. ``delete_deal`` removes these rows
# explicitly, for every mode, in the same transaction as the parent.
# =============================================================================

_CREATE_DEAL_CAPITAL_PLAN_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS deal_capital_plan_items (
    deal_id      TEXT NOT NULL,
    item_id      TEXT NOT NULL,
    ordinal      INTEGER NOT NULL,
    description  TEXT NOT NULL,
    category     TEXT NOT NULL,
    month        INTEGER NOT NULL,
    amount       REAL NOT NULL,
    PRIMARY KEY (deal_id, item_id)
)
"""

_CREATE_DEAL_OWNER_EXPENSE_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS deal_owner_expense_items (
    deal_id        TEXT NOT NULL,
    item_id        TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL,
    annual_amount  REAL NOT NULL,
    first_year     INTEGER NOT NULL,
    last_year      INTEGER,
    PRIMARY KEY (deal_id, item_id)
)
"""

_BUSINESS_PLAN_TABLES = ("deal_capital_plan_items", "deal_owner_expense_items")


# =============================================================================
# Phase 7 Gate P7.2 -- the Investment shell, persisted Scenarios and the variant
# cache, schema version 8.
#
# Five purely additive tables, created by ``_connect`` via CREATE TABLE IF NOT
# EXISTS exactly as every table since version 2. No ALTER, and no existing row is
# read or rewritten: a v7 database gains five empty tables, and every legacy deal
# stays outside them until the analyst opts in (Q4).
#
# ``investments`` -- one row per Investment. ``is_hidden`` is 1 for the one-unit
# wrapper materialized by a Deal's first Scenario, the only kind P7.2 writes.
# There is no name, price or memo yet: those belong to the gates that need them.
#
# ``investment_units`` -- membership. ``deal_id`` is UNIQUE: a Deal belongs to at
# most one Investment (Q3), enforced by SQLite as well as by the lifecycle below,
# so no code path can quietly add a second one.
#
# ``scenarios`` / ``scenario_overrides`` -- the P7.1 contract, relational. The
# override primary key ``(scenario_id, unit_id, target)`` is SC-1's uniqueness
# rule in the schema. Targets and operations are stored as their wire tokens and
# decoded strictly; ``value`` is a REAL, so a float round-trips bit-identically.
# There is no ordinal, because override order has no meaning (SC-1, P-7).
#
# ``variant_snapshots`` -- a mode-blind cache of Quick and Detailed variant
# results, following ``deal_sensitivity_snapshots``. It is keyed by the variant
# identity ``(root_id, strategy_id, scenario_id)`` (Section 7.5), where
# ``strategy_id`` is ``_BASE_STRATEGY_ID`` until the Strategy gate adds real
# strategies. A row is served only while its ``source_fingerprint`` equals a
# freshly computed resolved-input fingerprint and its ``schema_version`` is
# current, so it is an optimization and never financial authority (Q14).
# Lease-Level variants are recomputed and never written here (Q14, D5 decision
# A). Base x Base is never written here either: it is the deal's own analysis.
#
# No FOREIGN KEY / ON DELETE CASCADE, for the reason stated above
# ``lease_level_suites``. Every lifecycle function below deletes child rows
# explicitly, in one transaction with their parent.
# =============================================================================

_CREATE_INVESTMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS investments (
    id          TEXT PRIMARY KEY,
    is_hidden   INTEGER NOT NULL CHECK (is_hidden IN (0, 1)),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""

_CREATE_INVESTMENT_UNITS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS investment_units (
    investment_id  TEXT NOT NULL,
    deal_id        TEXT NOT NULL UNIQUE,
    PRIMARY KEY (investment_id, deal_id)
)
"""

_CREATE_SCENARIOS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scenarios (
    id             TEXT PRIMARY KEY,
    investment_id  TEXT NOT NULL,
    name           TEXT NOT NULL,
    description    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
)
"""

_CREATE_SCENARIO_OVERRIDES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scenario_overrides (
    scenario_id  TEXT NOT NULL,
    unit_id      TEXT NOT NULL,
    target       TEXT NOT NULL,
    operation    TEXT NOT NULL,
    value        REAL NOT NULL,
    PRIMARY KEY (scenario_id, unit_id, target)
)
"""

_CREATE_VARIANT_SNAPSHOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS variant_snapshots (
    root_id            TEXT NOT NULL,
    strategy_id        TEXT NOT NULL,
    scenario_id        TEXT NOT NULL,
    snapshot           TEXT NOT NULL,
    schema_version     INTEGER NOT NULL,
    source_fingerprint TEXT NOT NULL,
    generated_at       TEXT NOT NULL,
    PRIMARY KEY (root_id, strategy_id, scenario_id)
)
"""

_P7_2_TABLES = (
    "investments",
    "investment_units",
    "scenarios",
    "scenario_overrides",
    "variant_snapshots",
)

#: The Strategy dimension of every P7.2 variant identity: the implicit Base
#: strategy. It is a reserved cache key, never an authored Strategy row, and it
#: cannot collide with a real id -- every id this store mints is
#: ``uuid4().hex``, 32 lowercase hexadecimal characters, and this is neither
#: that long nor hexadecimal.
_BASE_STRATEGY_ID = "base"


# =============================================================================
# Phase 7 Gate P7.4 -- persisted Strategies, schema version 9.
#
# Eight purely additive tables, created by ``_connect`` via CREATE TABLE IF NOT
# EXISTS exactly as every table since version 2. No ALTER, and no existing row
# is read or rewritten.
#
# ``strategies`` -- one row per persisted Strategy, owned by an Investment like
# a Scenario. The Base Strategy is implicit and is never a row.
#
# One typed table per overlay domain, never an opaque patch column. Every table
# is keyed ``(strategy_id, unit_id)`` -- the P7.4 rule of at most one overlay
# per ``(domain, unit_id)``, in the schema -- and carries exactly its domain's
# fields as typed columns: REAL for rates and dollars, so a float round-trips
# bit-identically, and INTEGER for whole numbers of years.
#
# ``strategy_business_plan_overlays`` is the explicit overlay marker. Its item
# rows live in the two item tables beside it, in the D6 tables' own shape. The
# marker is what separates "no BUSINESS_PLAN overlay" (no marker: the Deal's own
# plan) from "BUSINESS_PLAN overlay = the empty plan" (a marker with no items):
# absence of item rows never decides it. An item row without its marker is
# corrupt and fails closed.
#
# ``strategy_operating_outcomes`` holds one row per ``(unit_id, target)``, the
# SC-1-style uniqueness of an outcome, with its operation stored and decoded
# strictly. An OPERATING_OUTCOME overlay states at least one outcome, so its
# rows are its presence.
#
# Strategy x Scenario results reuse ``variant_snapshots`` under the variant
# identity ``(root_id, strategy_id, scenario_id)``; no second cache exists.
# =============================================================================

_CREATE_STRATEGIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategies (
    id             TEXT PRIMARY KEY,
    investment_id  TEXT NOT NULL,
    name           TEXT NOT NULL,
    description    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
)
"""

_CREATE_STRATEGY_ACQUISITION_OVERLAYS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_acquisition_overlays (
    strategy_id           TEXT NOT NULL,
    unit_id               TEXT NOT NULL,
    purchase_price        REAL NOT NULL,
    acquisition_cost_pct  REAL NOT NULL,
    PRIMARY KEY (strategy_id, unit_id)
)
"""

_CREATE_STRATEGY_FINANCING_OVERLAYS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_financing_overlays (
    strategy_id        TEXT NOT NULL,
    unit_id            TEXT NOT NULL,
    ltv                REAL NOT NULL,
    interest_rate      REAL NOT NULL,
    amortization       INTEGER NOT NULL,
    io_period          INTEGER NOT NULL,
    financing_fee_pct  REAL NOT NULL,
    PRIMARY KEY (strategy_id, unit_id)
)
"""

_CREATE_STRATEGY_BUSINESS_PLAN_OVERLAYS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_business_plan_overlays (
    strategy_id  TEXT NOT NULL,
    unit_id      TEXT NOT NULL,
    PRIMARY KEY (strategy_id, unit_id)
)
"""

_CREATE_STRATEGY_CAPITAL_PLAN_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_capital_plan_items (
    strategy_id  TEXT NOT NULL,
    unit_id      TEXT NOT NULL,
    item_id      TEXT NOT NULL,
    ordinal      INTEGER NOT NULL,
    description  TEXT NOT NULL,
    category     TEXT NOT NULL,
    month        INTEGER NOT NULL,
    amount       REAL NOT NULL,
    PRIMARY KEY (strategy_id, unit_id, item_id)
)
"""

_CREATE_STRATEGY_OWNER_EXPENSE_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_owner_expense_items (
    strategy_id    TEXT NOT NULL,
    unit_id        TEXT NOT NULL,
    item_id        TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL,
    annual_amount  REAL NOT NULL,
    first_year     INTEGER NOT NULL,
    last_year      INTEGER,
    PRIMARY KEY (strategy_id, unit_id, item_id)
)
"""

_CREATE_STRATEGY_OPERATING_OUTCOMES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_operating_outcomes (
    strategy_id  TEXT NOT NULL,
    unit_id      TEXT NOT NULL,
    target       TEXT NOT NULL,
    operation    TEXT NOT NULL,
    value        REAL NOT NULL,
    PRIMARY KEY (strategy_id, unit_id, target)
)
"""

_CREATE_STRATEGY_DISPOSITION_OVERLAYS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_disposition_overlays (
    strategy_id  TEXT NOT NULL,
    unit_id      TEXT NOT NULL,
    hold_period  INTEGER NOT NULL,
    PRIMARY KEY (strategy_id, unit_id)
)
"""

#: Every table a Strategy's overlays occupy. Deleting a Strategy deletes its
#: rows from each of them, explicitly, in one transaction with the Strategy.
_STRATEGY_OVERLAY_TABLES = (
    "strategy_acquisition_overlays",
    "strategy_financing_overlays",
    "strategy_business_plan_overlays",
    "strategy_capital_plan_items",
    "strategy_owner_expense_items",
    "strategy_operating_outcomes",
    "strategy_disposition_overlays",
)

_P7_4_TABLES = ("strategies", *_STRATEGY_OVERLAY_TABLES)


# =============================================================================
# Phase 7 Gate P7.6 -- the visible Investment, schema version 10.
#
# Five purely additive sidecar tables keyed to the existing ``investments`` id
# (and, for Units, the existing ``investment_units`` membership), created by
# ``_connect`` via CREATE TABLE IF NOT EXISTS exactly as every table since
# version 2. ``investments`` and ``investment_units`` are not altered: a visible
# Investment is the same ``investments`` row with ``is_hidden = 0`` and these
# sidecars beside it.
#
# ``investment_details`` -- the name and transaction price. Its presence is the
# visible state's; a hidden wrapper never has one.
#
# ``investment_unit_details`` -- one row per member Unit: presentation
# (``ordinal``, ``label``, ``unit_kind``) and economic timing
# (``acquisition_month``, ``disposition_month``, NULL for "through the common
# horizon"). Its Unit set must equal the ``investment_units`` membership; a
# mismatch is corrupt and fails closed.
#
# ``investment_capital_plan_items`` / ``investment_owner_expense_items`` -- the
# Investment-level Business Plan, in the D6 tables' own shape and decoded by the
# one D6 row codec, in its own item-ID namespace.
#
# ``investment_transaction_costs`` -- the closing costs, with the analyst's
# row order kept as a display ordinal.
#
# No FOREIGN KEY / ON DELETE CASCADE, for the reason stated above
# ``lease_level_suites``. Every lifecycle function deletes these rows
# explicitly, in one transaction with their parent.
# =============================================================================

_CREATE_INVESTMENT_DETAILS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS investment_details (
    investment_id      TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    transaction_price  REAL NOT NULL
)
"""

_CREATE_INVESTMENT_UNIT_DETAILS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS investment_unit_details (
    investment_id      TEXT NOT NULL,
    unit_id            TEXT NOT NULL UNIQUE,
    ordinal            INTEGER NOT NULL,
    label              TEXT,
    unit_kind          TEXT NOT NULL,
    acquisition_month  INTEGER NOT NULL,
    disposition_month  INTEGER,
    PRIMARY KEY (investment_id, unit_id)
)
"""

_CREATE_INVESTMENT_CAPITAL_PLAN_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS investment_capital_plan_items (
    investment_id  TEXT NOT NULL,
    item_id        TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL,
    month          INTEGER NOT NULL,
    amount         REAL NOT NULL,
    PRIMARY KEY (investment_id, item_id)
)
"""

_CREATE_INVESTMENT_OWNER_EXPENSE_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS investment_owner_expense_items (
    investment_id  TEXT NOT NULL,
    item_id        TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL,
    annual_amount  REAL NOT NULL,
    first_year     INTEGER NOT NULL,
    last_year      INTEGER,
    PRIMARY KEY (investment_id, item_id)
)
"""

_CREATE_INVESTMENT_TRANSACTION_COSTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS investment_transaction_costs (
    investment_id  TEXT NOT NULL,
    cost_id        TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL,
    amount         REAL NOT NULL,
    model_month    INTEGER NOT NULL,
    PRIMARY KEY (investment_id, cost_id)
)
"""

#: Every sidecar a visible Investment owns. Deleting the Investment deletes its
#: rows from each of them, explicitly, in one transaction with the Investment.
_P7_6_TABLES = (
    "investment_details",
    "investment_unit_details",
    "investment_capital_plan_items",
    "investment_owner_expense_items",
    "investment_transaction_costs",
)


_LEASE_LEVEL_CHILD_TABLES = (
    "lease_level_property_inputs",
    "lease_level_operating_inputs",
    "lease_level_market_leasing",
    "lease_level_suites",
    "lease_level_leases",
)


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
# Phase 6 Gate D6.8: 2. For ``ai_snapshot`` this version is also the AI
# report's compatibility with the grounding it was generated under -- and D6.8
# changed that grounding (the Business Plan & Capital Economics section and its
# rules) without changing any deal input, so a pre-D6.8 report still matches its
# deal's fingerprint exactly. Only ``ai_snapshot`` carries this version, so the
# bump makes every such report decode as absent (the analyst regenerates) while
# the deal fingerprints, the analysis snapshot and both sensitivity snapshots
# stay exactly as current as they were. Within one version nothing else
# changes: the fingerprint check still decides currency, so an exact revert
# restores a report. No migration -- the version is a value in the existing
# column, written on every AI snapshot write.
_AI_SNAPSHOT_SCHEMA_VERSION = 2
# D5.8A: the serialized ``{configuration, result}`` contract for one persisted
# sensitivity run. Bumping this makes every stored row of the old shape decode
# as absent rather than as a wrongly-shaped result -- the same graceful
# invalidation ``_decode_snapshot`` already gives the other two.
_SENSITIVITY_SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotValidationError(ValueError):
    """Raised when a caller-supplied ``analysis_snapshot``/``ai_snapshot``
    dict cannot be reconstructed into its expected result-contract shape.
    Distinct from a decode failure on an already-*stored* snapshot (which
    ``_decode_snapshot`` swallows and treats as absent, never raises) --
    this is raised only against fresh, caller-supplied input on a write, so
    the API layer can reject it (422) rather than silently persisting or
    silently dropping data the caller explicitly asked to save."""


def _unwrap_optional(hint: Any) -> Any:
    """Return ``T`` for a ``T | None`` hint, and ``hint`` unchanged for
    anything else (including a genuine multi-member union such as
    ``AcquisitionResults | DetailedAcquisitionResults | None``, which has no
    single member to unwrap to). Needed only so an *optional nested
    dataclass* field -- ``AIAnalysis.deal_story: DealStory | None``, Sprint
    B Gate B4 -- is reconstructed as its dataclass rather than left as the
    raw decoded ``dict`` it arrives as."""

    if get_origin(hint) not in (Union, UnionType):
        return hint
    non_none = [arg for arg in get_args(hint) if arg is not type(None)]
    return non_none[0] if len(non_none) == 1 else hint


def _coerce_snapshot_value(hint: Any, value: Any) -> Any:
    if value is None:
        return None
    hint = _unwrap_optional(hint)
    if hint is IrrStatus:
        # D6.3 closeout: a stored IRR status token back into its member, so a
        # decoded snapshot carries the enum the result contract declares rather
        # than a bare ``str`` (JSON is unchanged: the member serialises to the
        # same token). Strict, like ``_decode_enum``: an unknown token is invalid
        # data, never a default -- on the read path the snapshot is then absent
        # and recomputed, on a write it is refused.
        try:
            return IrrStatus(value)
        except (ValueError, TypeError) as error:
            raise SnapshotValidationError(
                f"{value!r} is not a valid IrrStatus value."
            ) from error
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
        # D5.8A: coerce the *elements* too, by the element type the hint
        # declares. Until this gate every tuple field held a scalar
        # (``tuple[float, ...]``, ``tuple[str, ...]``) for which element
        # coercion is the identity, so no existing snapshot decodes any
        # differently. ``TwoWaySensitivityResult.matrix`` is the first
        # ``tuple[tuple[...], ...]``, and without this its rows would decode as
        # the JSON ``list``s they arrived as -- a matrix that compares unequal
        # to the one that was stored, and a round-trip that silently is not
        # one.
        element_hints = get_args(hint)
        if len(element_hints) == 2 and element_hints[1] is Ellipsis:
            element_hint = element_hints[0]
            return tuple(_coerce_snapshot_value(element_hint, item) for item in value)
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
            # A field the contract itself declares a default for is
            # *optional in the stored JSON* -- this is the one backward-
            # compatible mechanism by which a snapshot written before that
            # field existed still decodes (Sprint B Gate B4:
            # ``AIAnalysis.deal_story``, absent from every pre-B4
            # ``ai_snapshot``, decodes to ``None``, so a legacy snapshot
            # restores its full report and simply shows no Deal Story).
            # Every field without a default remains strictly required.
            if field.default is not dataclasses.MISSING:
                kwargs[field.name] = field.default
                continue
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


def _one_way_sensitivity_snapshot_from_dict(data: dict) -> OneWaySensitivitySnapshot:
    return _dataclass_from_json(OneWaySensitivitySnapshot, data)


def _two_way_sensitivity_snapshot_from_dict(data: dict) -> TwoWaySensitivitySnapshot:
    return _dataclass_from_json(TwoWaySensitivitySnapshot, data)


def _encode_snapshot(
    value: AcquisitionResults
    | DetailedAcquisitionResults
    | AIAnalysis
    | OneWaySensitivitySnapshot
    | TwoWaySensitivitySnapshot,
) -> str:
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


def _read_sensitivity_snapshots(
    connection: sqlite3.Connection, deal_id: str, *, expected_fingerprint: str
) -> tuple[OneWaySensitivitySnapshot | None, TwoWaySensitivitySnapshot | None]:
    """D5.8A -- the latest one-way and two-way runs stored for ``deal_id``,
    each returned only if it still matches ``expected_fingerprint`` (the
    fingerprint of the deal's own currently-stored assumptions) and still
    decodes under the current contract.

    Read through the same ``_decode_snapshot`` gate every other snapshot passes:
    absent, schema-incompatible, fingerprint-stale or malformed all resolve to
    ``None``, and none of them raises -- an unreadable derived artifact must
    never block opening a deal, and a stale one must never be handed back as
    current.

    The two are looked up independently and neither can affect the other: a
    one-way row that has gone stale, gone missing or gone unreadable leaves the
    two-way matrix exactly where it was.
    """

    decoders = {
        _ONE_WAY_KIND: _one_way_sensitivity_snapshot_from_dict,
        _TWO_WAY_KIND: _two_way_sensitivity_snapshot_from_dict,
    }
    decoded: dict[str, Any] = {_ONE_WAY_KIND: None, _TWO_WAY_KIND: None}
    rows = connection.execute(
        "SELECT * FROM deal_sensitivity_snapshots WHERE deal_id = ?", (deal_id,)
    ).fetchall()
    for row in rows:
        kind = row["analysis_kind"]
        decoder = decoders.get(kind)
        if decoder is None:
            # A kind this build does not know about is ignored, never guessed
            # at -- the same posture as an incompatible schema version.
            continue
        decoded[kind] = _decode_snapshot(
            raw_json=row["snapshot"],
            stored_schema_version=row["schema_version"],
            current_schema_version=_SENSITIVITY_SNAPSHOT_SCHEMA_VERSION,
            stored_fingerprint=row["source_fingerprint"],
            expected_fingerprint=expected_fingerprint,
            decoder=decoder,
        )
    return decoded[_ONE_WAY_KIND], decoded[_TWO_WAY_KIND]


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

    # D5.4 -- schema version 5 adds the six ``lease_level_*`` tables. There is
    # no ALTER here, and deliberately nothing to write: the tables are created
    # unconditionally by ``_connect`` via CREATE TABLE IF NOT EXISTS, exactly as
    # the Detailed pair was at version 2, so a v4 database gains the new family
    # without a single existing row being read or rewritten. The safest
    # migration available is one that touches no existing data.
    # D5.8A -- schema version 6 adds ``deal_sensitivity_snapshots``. Nothing to
    # do here for the same reason version 5 had nothing to do: the table is
    # created unconditionally by ``_connect`` via CREATE TABLE IF NOT EXISTS, so
    # a v5 (or v1) database gains it without a single existing row being read or
    # rewritten, and every pre-existing deal simply has no rows in it yet.
    # D6.5 -- schema version 7 adds the two Business Plan tables, again with
    # nothing to do here: ``_connect`` creates them via CREATE TABLE IF NOT
    # EXISTS, and a legacy deal with no plan rows loads as ``BusinessPlan()``
    # without any row being written for it.
    # P7.2 -- schema version 8 adds the five P7 tables with nothing to do here
    # either: ``_connect`` creates them via CREATE TABLE IF NOT EXISTS, and no
    # Investment, membership or Scenario row is written for any existing deal.
    # P7.4 -- schema version 9 adds the eight Strategy tables the same way: no
    # row is written for any existing Deal, Scenario or cached variant.
    # P7.6 -- schema version 10 adds the five visible-Investment sidecars the
    # same way: no row is written for any existing Deal, hidden Investment,
    # Scenario, Strategy or cached variant, and ``investments`` is not altered.
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
    connection.execute(_CREATE_LEASE_LEVEL_DEALS_TABLE_SQL)
    connection.execute(_CREATE_LEASE_LEVEL_PROPERTY_INPUTS_TABLE_SQL)
    connection.execute(_CREATE_LEASE_LEVEL_OPERATING_INPUTS_TABLE_SQL)
    connection.execute(_CREATE_LEASE_LEVEL_MARKET_LEASING_TABLE_SQL)
    connection.execute(_CREATE_LEASE_LEVEL_SUITES_TABLE_SQL)
    connection.execute(_CREATE_LEASE_LEVEL_LEASES_TABLE_SQL)
    connection.execute(_CREATE_DEAL_SENSITIVITY_SNAPSHOTS_TABLE_SQL)
    connection.execute(_CREATE_DEAL_CAPITAL_PLAN_ITEMS_TABLE_SQL)
    connection.execute(_CREATE_DEAL_OWNER_EXPENSE_ITEMS_TABLE_SQL)
    connection.execute(_CREATE_INVESTMENTS_TABLE_SQL)
    connection.execute(_CREATE_INVESTMENT_UNITS_TABLE_SQL)
    connection.execute(_CREATE_SCENARIOS_TABLE_SQL)
    connection.execute(_CREATE_SCENARIO_OVERRIDES_TABLE_SQL)
    connection.execute(_CREATE_VARIANT_SNAPSHOTS_TABLE_SQL)
    connection.execute(_CREATE_STRATEGIES_TABLE_SQL)
    connection.execute(_CREATE_STRATEGY_ACQUISITION_OVERLAYS_TABLE_SQL)
    connection.execute(_CREATE_STRATEGY_FINANCING_OVERLAYS_TABLE_SQL)
    connection.execute(_CREATE_STRATEGY_BUSINESS_PLAN_OVERLAYS_TABLE_SQL)
    connection.execute(_CREATE_STRATEGY_CAPITAL_PLAN_ITEMS_TABLE_SQL)
    connection.execute(_CREATE_STRATEGY_OWNER_EXPENSE_ITEMS_TABLE_SQL)
    connection.execute(_CREATE_STRATEGY_OPERATING_OUTCOMES_TABLE_SQL)
    connection.execute(_CREATE_STRATEGY_DISPOSITION_OVERLAYS_TABLE_SQL)
    connection.execute(_CREATE_INVESTMENT_DETAILS_TABLE_SQL)
    connection.execute(_CREATE_INVESTMENT_UNIT_DETAILS_TABLE_SQL)
    connection.execute(_CREATE_INVESTMENT_CAPITAL_PLAN_ITEMS_TABLE_SQL)
    connection.execute(_CREATE_INVESTMENT_OWNER_EXPENSE_ITEMS_TABLE_SQL)
    connection.execute(_CREATE_INVESTMENT_TRANSACTION_COSTS_TABLE_SQL)
    _migrate(connection)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



# =============================================================================
# Sprint D5.4 -- Lease-Level storage codec.
#
# A *trusted* boundary, deliberately separate from ``leasing/parsing.py``. That
# module answers "can this untrusted JSON become a contract"; this one answers
# "restore the contract this store wrote". Routing rows through the HTTP parser
# would make persistence inherit transport semantics -- unknown-key reporting,
# request-shaped error paths -- for data the store itself produced, and would
# couple the database format to the wire format so neither could change alone.
#
# Everything here is contract-driven: column tuples come from
# ``dataclasses.fields``, so a field added to ``Suite`` or ``Lease`` is a schema
# change this module notices rather than silently drops.
# =============================================================================


def _column_names(contract: type) -> tuple[str, ...]:
    return tuple(field.name for field in dataclasses.fields(contract))


_LEASE_LEVEL_OPERATING_COLUMNS = _column_names(LeaseLevelOperatingInputs)
_LEASE_LEVEL_MARKET_COLUMNS = _column_names(MarketLeasingAssumptions)

#: ``MarketLeasingAssumptions`` fields by name, with the enum type each enum
#: field must be restored to. Derived from the contract so a new enum field
#: cannot be silently decoded as a bare string.
_MARKET_ENUM_FIELDS: dict[str, type] = {
    "leasing_commission_method": LeasingCommissionMethod,
    "renewal_lease_type": LeaseType,
    "renewal_recovery_basis": RecoveryBasis,
    "new_lease_type": LeaseType,
    "new_recovery_basis": RecoveryBasis,
}

_LEASE_ENUM_FIELDS: dict[str, type] = {
    "escalation_basis": EscalationBasis,
    "lease_type": LeaseType,
    "origin": LeaseOrigin,
    "recovery_basis": RecoveryBasis,
}

_LEASE_DATE_FIELDS = (
    "rent_commencement_date",
    "lease_expiration_date",
    "lease_start_date",
)


def _encode_enum(value: object) -> str | None:
    """An enum as its wire token. ``None`` stays ``None``."""

    if value is None:
        return None
    assert isinstance(value, Enum)
    return value.value


def _decode_enum(value: object, enum_type: type, *, path: str) -> object:
    """A stored token back into its authoritative member.

    A token the enum no longer recognises is a data-integrity failure, not a
    reason to pick a default: silently substituting ``NNN`` for an unreadable
    ``lease_type`` would hand the engine a lease nobody wrote, and the resulting
    recoveries would look perfectly ordinary.
    """

    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError:
        raise PersistedDealDataError(
            f"{path} holds {value!r}, which is not a valid "
            f"{enum_type.__name__} value."
        ) from None


def _encode_date(value: object) -> str | None:
    """ISO-8601 TEXT -- the same spelling the wire and the fingerprint use, so
    one value has one representation everywhere. No timezone is introduced: a
    lease date is a calendar date, not an instant."""

    if value is None:
        return None
    assert isinstance(value, date)
    return value.isoformat()


def _decode_date(value: object, *, path: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise PersistedDealDataError(
            f"{path} holds {value!r}, which is not an ISO-8601 date."
        ) from None


def _encode_market_leasing_override(
    override: MarketLeasingAssumptions | None,
) -> str | None:
    """The one approved nested-JSON column.

    ``MarketLeasingAssumptions`` is atomic by design -- a suite supplies the
    whole record or none of it -- so the two states this column can hold are
    exactly the two the domain permits. Canonical (sorted-key, tight) JSON, with
    dates and enums going through the same encoders the columns use, so the
    stored bytes are a function of the value and nothing else.

    Floats are written by ``json`` in ``repr`` form, which round-trips a Python
    float exactly; a test pins that over the whole contract rather than trusting
    it.
    """

    if override is None:
        return None

    payload = {
        name: (
            _encode_enum(value)
            if isinstance(value, Enum)
            else _encode_date(value)
            if isinstance(value, date)
            else value
        )
        for name, value in dataclasses.asdict(override).items()
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _decode_market_leasing_override(
    raw: object, *, path: str
) -> MarketLeasingAssumptions | None:
    """Rebuild the authoritative contract -- never hand back a raw dict.

    A dict would type-check nowhere and blow up somewhere far from here, inside
    a rollover builder reading ``.renewal_probability`` off a mapping.
    """

    if raw is None:
        return None
    try:
        payload = json.loads(str(raw))
    except ValueError:
        raise PersistedDealDataError(
            f"{path} does not hold valid JSON."
        ) from None
    if not isinstance(payload, dict):
        raise PersistedDealDataError(f"{path} does not hold a JSON object.")

    expected = set(_LEASE_LEVEL_MARKET_COLUMNS)
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        unexpected = sorted(set(payload) - expected)
        raise PersistedDealDataError(
            f"{path} is not a complete MarketLeasingAssumptions record "
            f"(missing={missing}, unexpected={unexpected})."
        )

    for name, enum_type in _MARKET_ENUM_FIELDS.items():
        payload[name] = _decode_enum(payload[name], enum_type, path=f"{path}.{name}")
    return MarketLeasingAssumptions(**payload)


def _suite_row_values(deal_id: str, ordinal: int, suite: Suite) -> tuple[object, ...]:
    initial_vacancy = suite.initial_vacancy
    return (
        deal_id,
        suite.suite_id,
        ordinal,
        suite.suite_area_sf,
        suite.suite_label,
        suite.market_rent_psf,
        _encode_market_leasing_override(suite.market_leasing_override),
        _encode_enum(initial_vacancy.strategy) if initial_vacancy is not None else None,
        initial_vacancy.initial_lease_up_months if initial_vacancy is not None else None,
    )


def _suite_from_row(row: sqlite3.Row) -> Suite:
    suite_id = row["suite_id"]
    strategy = row["initial_vacancy_strategy"]
    initial_vacancy = (
        InitialVacancyAssumptions(
            strategy=_decode_enum(
                strategy,
                InitialVacancyStrategy,
                path=f"suite {suite_id!r} initial_vacancy_strategy",
            ),
            initial_lease_up_months=row["initial_vacancy_lease_up_months"],
        )
        if strategy is not None
        else None
    )
    return Suite(
        suite_id=suite_id,
        suite_area_sf=row["suite_area_sf"],
        suite_label=row["suite_label"],
        market_rent_psf=row["market_rent_psf"],
        market_leasing_override=_decode_market_leasing_override(
            row["market_leasing_override"],
            path=f"suite {suite_id!r} market_leasing_override",
        ),
        initial_vacancy=initial_vacancy,
    )


def _lease_row_values(deal_id: str, ordinal: int, lease: Lease) -> tuple[object, ...]:
    return (
        deal_id,
        lease.lease_id,
        ordinal,
        lease.suite_id,
        lease.leased_area_sf,
        _encode_date(lease.rent_commencement_date),
        _encode_date(lease.lease_expiration_date),
        lease.base_rent_psf,
        lease.escalation_pct,
        _encode_enum(lease.escalation_basis),
        _encode_enum(lease.lease_type),
        lease.tenant_name,
        _encode_date(lease.lease_start_date),
        _encode_enum(lease.origin),
        _encode_enum(lease.recovery_basis),
        lease.expense_stop_psf,
    )


def _lease_from_row(row: sqlite3.Row) -> Lease:
    lease_id = row["lease_id"]
    decoded: dict[str, object] = {
        "lease_id": lease_id,
        "suite_id": row["suite_id"],
        "leased_area_sf": row["leased_area_sf"],
        "base_rent_psf": row["base_rent_psf"],
        "escalation_pct": row["escalation_pct"],
        "tenant_name": row["tenant_name"],
        "expense_stop_psf": row["expense_stop_psf"],
    }
    for name in _LEASE_DATE_FIELDS:
        decoded[name] = _decode_date(row[name], path=f"lease {lease_id!r} {name}")
    for name, enum_type in _LEASE_ENUM_FIELDS.items():
        decoded[name] = _decode_enum(row[name], enum_type, path=f"lease {lease_id!r} {name}")
    return Lease(**decoded)


def _lease_level_property_inputs_from_row(row: sqlite3.Row) -> LeaseLevelPropertyInputs:
    return LeaseLevelPropertyInputs(
        analysis_start_date=_decode_date(
            row["analysis_start_date"], path="property_inputs.analysis_start_date"
        ),
        rentable_area_sf=row["rentable_area_sf"],
    )


def _lease_level_operating_inputs_from_row(row: sqlite3.Row) -> LeaseLevelOperatingInputs:
    return LeaseLevelOperatingInputs(
        **{name: row[name] for name in _LEASE_LEVEL_OPERATING_COLUMNS}
    )


def _market_leasing_from_row(row: sqlite3.Row) -> MarketLeasingAssumptions:
    values: dict[str, object] = {
        name: row[name] for name in _LEASE_LEVEL_MARKET_COLUMNS
    }
    for name, enum_type in _MARKET_ENUM_FIELDS.items():
        values[name] = _decode_enum(values[name], enum_type, path=f"market_leasing.{name}")
    return MarketLeasingAssumptions(**values)


def _write_lease_level_children(
    connection: sqlite3.Connection,
    deal_id: str,
    property_inputs: LeaseLevelPropertyInputs,
    operating_inputs: LeaseLevelOperatingInputs,
    market_leasing: MarketLeasingAssumptions,
    suites: tuple[Suite, ...],
    leases: tuple[Lease, ...],
) -> None:
    """Write every child row for one Lease-Level deal.

    Called inside the caller's transaction, after any existing children have
    been removed, so an update is a whole-rent-roll replacement rather than a
    row-by-row diff. Replacement is the simpler correct thing here: a rent roll
    is submitted whole, ids are the only identity, and a diff would have to
    invent an answer for a suite that changed id.
    """

    connection.execute(
        "INSERT INTO lease_level_property_inputs "
        "(deal_id, analysis_start_date, rentable_area_sf) VALUES (?, ?, ?)",
        (
            deal_id,
            _encode_date(property_inputs.analysis_start_date),
            property_inputs.rentable_area_sf,
        ),
    )
    connection.execute(
        f"""
        INSERT INTO lease_level_operating_inputs
            (deal_id, {", ".join(_LEASE_LEVEL_OPERATING_COLUMNS)})
        VALUES (?, {", ".join("?" for _ in _LEASE_LEVEL_OPERATING_COLUMNS)})
        """,
        (
            deal_id,
            *(getattr(operating_inputs, name) for name in _LEASE_LEVEL_OPERATING_COLUMNS),
        ),
    )
    market_values = [
        _encode_enum(getattr(market_leasing, name))
        if name in _MARKET_ENUM_FIELDS
        else getattr(market_leasing, name)
        for name in _LEASE_LEVEL_MARKET_COLUMNS
    ]
    connection.execute(
        f"""
        INSERT INTO lease_level_market_leasing
            (deal_id, {", ".join(_LEASE_LEVEL_MARKET_COLUMNS)})
        VALUES (?, {", ".join("?" for _ in _LEASE_LEVEL_MARKET_COLUMNS)})
        """,
        (deal_id, *market_values),
    )
    connection.executemany(
        """
        INSERT INTO lease_level_suites
            (deal_id, suite_id, ordinal, suite_area_sf, suite_label,
             market_rent_psf, market_leasing_override,
             initial_vacancy_strategy, initial_vacancy_lease_up_months)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [_suite_row_values(deal_id, ordinal, suite) for ordinal, suite in enumerate(suites)],
    )
    connection.executemany(
        """
        INSERT INTO lease_level_leases
            (deal_id, lease_id, ordinal, suite_id, leased_area_sf,
             rent_commencement_date, lease_expiration_date, base_rent_psf,
             escalation_pct, escalation_basis, lease_type, tenant_name,
             lease_start_date, origin, recovery_basis, expense_stop_psf)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [_lease_row_values(deal_id, ordinal, lease) for ordinal, lease in enumerate(leases)],
    )


def _delete_lease_level_children(connection: sqlite3.Connection, deal_id: str) -> None:
    """Remove every child row for one deal.

    Explicit rather than by ``ON DELETE CASCADE``: this module never enables
    ``PRAGMA foreign_keys``, so a declared cascade would silently do nothing and
    leave orphans behind a reassuring-looking schema.
    """

    for table in _LEASE_LEVEL_CHILD_TABLES:
        connection.execute(f"DELETE FROM {table} WHERE deal_id = ?", (deal_id,))


# =============================================================================
# Phase 6 Gate D6.5 -- Business Plan storage codec.
#
# A trusted boundary in the rent roll's sense: it restores the contract this
# store wrote, and does not route rows through the wire parser. It is not a
# second validation authority either -- both directions hand the whole plan to
# ``anchor.business_plan.validation`` and refuse what it refuses.
# =============================================================================


def _write_business_plan(
    connection: sqlite3.Connection, deal_id: str, business_plan: BusinessPlan
) -> None:
    """Write every Business Plan row for one deal, in the analyst's order.

    Called inside the caller's transaction, after any existing plan rows have
    been removed: a plan is submitted whole and replaced whole, exactly like the
    rent roll, so an update can never leave a mixture of old and new items.
    """

    connection.executemany(
        """
        INSERT INTO deal_capital_plan_items
            (deal_id, item_id, ordinal, description, category, month, amount)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                deal_id,
                item.item_id,
                ordinal,
                item.description,
                _encode_enum(item.category),
                item.month,
                item.amount,
            )
            for ordinal, item in enumerate(business_plan.capital_items)
        ],
    )
    connection.executemany(
        """
        INSERT INTO deal_owner_expense_items
            (deal_id, item_id, ordinal, description, category, annual_amount,
             first_year, last_year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                deal_id,
                item.item_id,
                ordinal,
                item.description,
                _encode_enum(item.category),
                item.annual_amount,
                item.first_year,
                item.last_year,
            )
            for ordinal, item in enumerate(business_plan.owner_expense_items)
        ],
    )


def _delete_business_plan(connection: sqlite3.Connection, deal_id: str) -> None:
    """Remove every Business Plan row for one deal, whichever mode it is."""

    for table in _BUSINESS_PLAN_TABLES:
        connection.execute(f"DELETE FROM {table} WHERE deal_id = ?", (deal_id,))


def _business_plan_from_rows(
    deal_id: str,
    capital_rows: Iterable[sqlite3.Row],
    owner_expense_rows: Iterable[sqlite3.Row],
) -> BusinessPlan:
    """Rebuild one deal's ``BusinessPlan`` from its rows, already in ordinal
    order, and refuse it if the validation authority does.

    No rows is the empty plan -- the state every legacy deal is in -- reached
    without constructing anything special for it. A row the enum no longer
    recognises, a value of the wrong type or a cross-type duplicate ID is a
    ``PersistedDealDataError``: silently dropping or repairing an item would
    hand the engine a plan nobody wrote, and its numbers would look ordinary.
    """

    capital_items = tuple(
        CapitalPlanItem(
            item_id=row["item_id"],
            description=row["description"],
            category=_decode_enum(  # type: ignore[arg-type]
                row["category"],
                CapitalItemCategory,
                path=f"capital plan item {row['item_id']!r} category",
            ),
            month=row["month"],
            amount=row["amount"],
        )
        for row in capital_rows
    )
    owner_expense_items = tuple(
        OwnerExpenseItem(
            item_id=row["item_id"],
            description=row["description"],
            category=_decode_enum(  # type: ignore[arg-type]
                row["category"],
                OwnerExpenseCategory,
                path=f"owner expense item {row['item_id']!r} category",
            ),
            annual_amount=row["annual_amount"],
            first_year=row["first_year"],
            last_year=row["last_year"],
        )
        for row in owner_expense_rows
    )
    business_plan = BusinessPlan(
        capital_items=capital_items, owner_expense_items=owner_expense_items
    )
    result = validate_business_plan(business_plan)
    if not result.is_valid:
        raise PersistedDealDataError(
            f"Deal {deal_id!r} holds a Business Plan that does not validate: "
            + "; ".join(f"{issue.path}: {issue.message}" for issue in result.issues)
        )
    return business_plan


def _read_business_plan(connection: sqlite3.Connection, deal_id: str) -> BusinessPlan:
    """The Business Plan currently stored for ``deal_id`` -- two bounded
    queries, ordered by the display ordinal the analyst's submission set."""

    capital_rows = connection.execute(
        "SELECT * FROM deal_capital_plan_items WHERE deal_id = ? ORDER BY ordinal",
        (deal_id,),
    ).fetchall()
    owner_expense_rows = connection.execute(
        "SELECT * FROM deal_owner_expense_items WHERE deal_id = ? ORDER BY ordinal",
        (deal_id,),
    ).fetchall()
    return _business_plan_from_rows(deal_id, capital_rows, owner_expense_rows)


def _read_all_business_plans(
    connection: sqlite3.Connection, deal_ids: Iterable[str]
) -> dict[str, BusinessPlan]:
    """Every listed deal's Business Plan in two queries for the whole library,
    rather than two per deal."""

    capital_rows: dict[str, list[sqlite3.Row]] = {}
    for row in connection.execute(
        "SELECT * FROM deal_capital_plan_items ORDER BY deal_id, ordinal"
    ):
        capital_rows.setdefault(row["deal_id"], []).append(row)
    owner_expense_rows: dict[str, list[sqlite3.Row]] = {}
    for row in connection.execute(
        "SELECT * FROM deal_owner_expense_items ORDER BY deal_id, ordinal"
    ):
        owner_expense_rows.setdefault(row["deal_id"], []).append(row)
    return {
        deal_id: _business_plan_from_rows(
            deal_id, capital_rows.get(deal_id, ()), owner_expense_rows.get(deal_id, ())
        )
        for deal_id in deal_ids
    }


def _lease_level_input_fingerprint(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> str:
    """D5.8A -- the canonical financial-input fingerprint of the Lease-Level
    deal ``row`` **as it is currently stored**, rebuilt from its own rows.

    Used by the three write paths that must independently verify a caller's
    provenance token rather than trust it (``update_ai_snapshot`` and the two
    sensitivity writers below). It calls the same
    ``fingerprint_lease_level_inputs`` the read path calls, over the same six
    contracts, so there is exactly one definition of what a Lease-Level deal
    fingerprints to and no possibility of the read and write sides drifting.

    Raises ``PersistedDealDataError`` through ``_row_to_lease_level_deal`` if a
    child row is missing -- a deal that cannot be reassembled has no fingerprint,
    and inventing one would let a snapshot be certified against assumptions
    nobody could read back.
    """

    deal = _row_to_lease_level_deal(
        connection,
        row,
        business_plan=_read_business_plan(connection, row["id"]),
        include_snapshots=False,
    )
    assert deal.terms is not None
    assert deal.property_inputs is not None
    assert deal.operating_inputs is not None
    assert deal.market_leasing is not None
    assert deal.suites is not None
    assert deal.leases is not None
    return fingerprint_lease_level_inputs(
        deal.terms,
        deal.property_inputs,
        deal.suites,
        deal.leases,
        market_leasing=deal.market_leasing,
        operating_inputs=deal.operating_inputs,
        business_plan=deal.business_plan,
    )


def _row_to_lease_level_deal(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    business_plan: BusinessPlan,
    include_snapshots: bool = True,
) -> Deal:
    """Reassemble one Lease-Level deal from its parent row and children.

    ``business_plan`` is the deal's stored plan, read by the caller (D6.5).
    Required: a reassembled deal with its plan silently replaced by an empty
    one would fingerprint as a different deal and serve stale snapshots."""

    deal_id = row["id"]

    def one(table: str) -> sqlite3.Row:
        child = connection.execute(
            f"SELECT * FROM {table} WHERE deal_id = ?", (deal_id,)
        ).fetchone()
        if child is None:
            raise PersistedDealDataError(
                f"Lease-Level deal {deal_id!r} has no {table} row."
            )
        return child

    # Ordered by the display ordinal the analyst's own submission order set --
    # not by id. Canonical id order belongs to the fingerprint alone, and
    # letting it govern display would reorder a rent roll under the analyst.
    suite_rows = connection.execute(
        "SELECT * FROM lease_level_suites WHERE deal_id = ? ORDER BY ordinal",
        (deal_id,),
    ).fetchall()
    lease_rows = connection.execute(
        "SELECT * FROM lease_level_leases WHERE deal_id = ? ORDER BY ordinal",
        (deal_id,),
    ).fetchall()

    deal_context = row["deal_context"]
    terms = _terms_from_row(row)
    property_inputs = _lease_level_property_inputs_from_row(one("lease_level_property_inputs"))
    operating_inputs = _lease_level_operating_inputs_from_row(
        one("lease_level_operating_inputs")
    )
    market_leasing = _market_leasing_from_row(one("lease_level_market_leasing"))
    suites = tuple(_suite_from_row(suite_row) for suite_row in suite_rows)
    leases = tuple(_lease_from_row(lease_row) for lease_row in lease_rows)

    ai_snapshot = None
    one_way_sensitivity_snapshot = None
    two_way_sensitivity_snapshot = None
    if include_snapshots:
        analysis_fingerprint = fingerprint_lease_level_inputs(
            terms,
            property_inputs,
            suites,
            leases,
            market_leasing=market_leasing,
            operating_inputs=operating_inputs,
            business_plan=business_plan,
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
        # D5.8A. Guarded by the *financial-input* fingerprint, not the AI one: a
        # sensitivity run reads no Deal Context, so editing the stated strategy
        # invalidates the AI report and leaves the matrix exactly as valid as it
        # was. The two staleness rules differ because the two analyses genuinely
        # depend on different things.
        (
            one_way_sensitivity_snapshot,
            two_way_sensitivity_snapshot,
        ) = _read_sensitivity_snapshots(
            connection, deal_id, expected_fingerprint=analysis_fingerprint
        )

    return Deal(
        id=deal_id,
        name=row["name"],
        operating_mode=OperatingMode.LEASE_LEVEL,
        inputs=None,
        terms=terms,
        detailed_operating_inputs=None,
        property_inputs=property_inputs,
        operating_inputs=operating_inputs,
        market_leasing=market_leasing,
        suites=suites,
        leases=leases,
        business_plan=business_plan,
        deal_context=deal_context,
        # D5 decision A: never restored from persistence, and there is no column
        # it could be restored from. D5.8A does not reverse this -- the AI report
        # and the sensitivity runs below are restored from their own snapshots,
        # each validated against the same input fingerprint, without any cached
        # base result being needed to prove either is current.
        analysis_snapshot=None,
        ai_snapshot=ai_snapshot,
        one_way_sensitivity_snapshot=one_way_sensitivity_snapshot,
        two_way_sensitivity_snapshot=two_way_sensitivity_snapshot,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )

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


def _row_to_deal(
    row: sqlite3.Row, *, business_plan: BusinessPlan, include_snapshots: bool = True
) -> Deal:
    """``include_snapshots=False`` (used by ``list_deals``) skips decoding
    the cached snapshot columns entirely, always returning
    ``analysis_snapshot=None``/``ai_snapshot=None`` regardless of what is
    stored -- the Deal Library list is a lightweight per-deal summary
    (name, mode, timestamps); it must never balloon with every saved
    deal's full cached result/AI JSON. ``get_deal`` (single-deal fetch)
    always decodes them (the default).

    ``business_plan`` (D6.5) is the deal's stored plan, read by the caller;
    required for the reason ``_row_to_lease_level_deal`` gives."""

    inputs = _inputs_from_row(row)
    deal_context = row["deal_context"]
    if not include_snapshots:
        analysis_snapshot = None
        ai_snapshot = None
    else:
        analysis_fingerprint = fingerprint_quick_inputs(
            inputs, business_plan=business_plan
        )
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
        business_plan=business_plan,
        deal_context=deal_context,
        analysis_snapshot=analysis_snapshot,
        ai_snapshot=ai_snapshot,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_detailed_deal(
    deal_row: sqlite3.Row,
    operating_row: sqlite3.Row,
    *,
    business_plan: BusinessPlan,
    include_snapshots: bool = True,
) -> Deal:
    """``include_snapshots`` and ``business_plan`` mirror ``_row_to_deal``'s
    parameters exactly."""

    terms = _terms_from_row(deal_row)
    detailed_operating_inputs = _detailed_operating_inputs_from_row(operating_row)
    deal_context = deal_row["deal_context"]
    if not include_snapshots:
        analysis_snapshot = None
        ai_snapshot = None
    else:
        analysis_fingerprint = fingerprint_detailed_inputs(
            terms, detailed_operating_inputs, business_plan=business_plan
        )
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
        business_plan=business_plan,
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
    business_plan: BusinessPlan = BusinessPlan(),
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
    on any other deal.

    Phase 6 Gate D6.5: ``business_plan`` is written in the same transaction
    as the parent row, so a deal can never exist with half a plan. It is
    handed to the validation authority first, and an invalid plan is refused
    (``BusinessPlanValidationError``) before anything is written. The empty
    default is a compatibility boundary for plan-free callers; the API always
    passes the request's plan."""

    require_valid_business_plan(business_plan)
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
        _write_business_plan(connection, deal_id, business_plan)

    return get_deal(deal_id, db_path=db_path)


def update_deal(
    deal_id: str,
    name: str,
    inputs: AcquisitionInputs,
    *,
    deal_context: str | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
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
    Gate A4 invalidation rules, with zero explicit clearing logic here.

    Phase 6 Gate D6.5: the stored Business Plan is replaced whole by
    ``business_plan`` -- every prior row removed, the new ones written -- in the
    same transaction as the inputs, so an empty plan leaves no ghost rows and a
    failure part-way leaves the previous inputs *and* plan intact. A plan
    change moves the fingerprint, so the same read-time check invalidates
    every snapshot computed under the old plan."""

    require_valid_business_plan(business_plan)
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

        _delete_business_plan(connection, deal_id)
        _write_business_plan(connection, deal_id, business_plan)

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
    business_plan: BusinessPlan = BusinessPlan(),
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
    no-snapshot-parameter contract exactly -- see its docstring.

    Phase 6 Gate D6.5: ``business_plan`` mirrors ``create_deal``'s parameter
    exactly -- validated first, written in the same transaction."""

    require_valid_business_plan(business_plan)
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
        _write_business_plan(connection, deal_id, business_plan)

    return get_deal(deal_id, db_path=db_path)


def update_detailed_deal(
    deal_id: str,
    name: str,
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    deal_context: str | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
    db_path: Path | None = None,
) -> Deal:
    """Overwrite ``deal_id``'s name, terms, detailed operating inputs, and
    Deal Context (Gate A4), bump ``updated_at``, and return the updated
    Detailed deal. Raises ``DealNotFoundError`` if it doesn't exist in
    ``detailed_deals``.

    Owner Return Metrics V3 Gate A7: mirrors ``update_deal``'s
    never-touches-snapshot-columns contract exactly -- see its docstring.

    Phase 6 Gate D6.5: mirrors ``update_deal``'s whole-plan replacement, in
    the same transaction."""

    require_valid_business_plan(business_plan)
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
        _delete_business_plan(connection, deal_id)
        _write_business_plan(connection, deal_id, business_plan)

    return get_deal(deal_id, db_path=db_path)


# =============================================================================
# Mode-dispatching operations -- one domain-level Deal abstraction
# =============================================================================



def create_lease_level_deal(
    name: str,
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    operating_inputs: LeaseLevelOperatingInputs,
    market_leasing: MarketLeasingAssumptions,
    suites: tuple[Suite, ...],
    leases: tuple[Lease, ...],
    *,
    deal_context: str | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
    db_path: Path | None = None,
) -> Deal:
    """Persist one Lease-Level deal: parent row plus every child row.

    Phase 6 Gate D6.5: the Business Plan is written in the same transaction
    and into the same two mode-blind tables every mode uses -- the rent roll's
    tables never carry it.

    Takes **typed contracts**, never a mapping. The API layer has already turned
    the request body into these through the D5.2 parser; handing this function
    raw JSON would give the store a second, divergent notion of the wire format
    and make the database schema hostage to the HTTP one.

    Parent and children are written in one transaction, so a failure part-way
    cannot leave a deal with half a rent roll.

    Persists inputs only. There is no analysis-snapshot column to write, by
    design (D5 decision A) -- opening the deal re-runs the engine.
    """

    require_valid_business_plan(business_plan)
    deal_id = uuid.uuid4().hex
    now = _utc_now_iso()

    with _connect(db_path) as connection:
        connection.execute(
            f"""
            INSERT INTO lease_level_deals
                (id, name, {", ".join(_TERMS_COLUMNS)}, deal_context,
                 created_at, updated_at)
            VALUES (?, ?, {", ".join("?" for _ in _TERMS_COLUMNS)}, ?, ?, ?)
            """,
            (deal_id, name, *_terms_values(terms), deal_context, now, now),
        )
        _write_lease_level_children(
            connection,
            deal_id,
            property_inputs,
            operating_inputs,
            market_leasing,
            suites,
            leases,
        )
        _write_business_plan(connection, deal_id, business_plan)

    return get_deal(deal_id, db_path=db_path)


def update_lease_level_deal(
    deal_id: str,
    name: str,
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    operating_inputs: LeaseLevelOperatingInputs,
    market_leasing: MarketLeasingAssumptions,
    suites: tuple[Suite, ...],
    leases: tuple[Lease, ...],
    *,
    deal_context: str | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
    db_path: Path | None = None,
) -> Deal:
    """Replace one Lease-Level deal's approved input state.

    Phase 6 Gate D6.5: the Business Plan is replaced whole in the same
    transaction as the rent roll, exactly as ``update_deal`` replaces it.

    The rent roll is replaced wholesale -- children deleted, then rewritten --
    rather than diffed row by row. A rent roll is submitted whole, ``suite_id``
    is its only identity, and a diff would need an answer for a suite whose id
    changed that no submission actually expresses. Wholesale replacement has
    exactly one meaning.

    All of it in one transaction: a mid-update failure leaves the previous rent
    roll intact rather than a half-replaced one.
    """

    require_valid_business_plan(business_plan)
    with _connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE lease_level_deals
            SET name = ?,
                {", ".join(f"{column} = ?" for column in _TERMS_COLUMNS)},
                deal_context = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (name, *_terms_values(terms), deal_context, _utc_now_iso(), deal_id),
        )
        if cursor.rowcount == 0:
            raise DealNotFoundError(deal_id)

        _delete_lease_level_children(connection, deal_id)
        _write_lease_level_children(
            connection,
            deal_id,
            property_inputs,
            operating_inputs,
            market_leasing,
            suites,
            leases,
        )
        _delete_business_plan(connection, deal_id)
        _write_business_plan(connection, deal_id, business_plan)

    return get_deal(deal_id, db_path=db_path)

def get_deal(deal_id: str, *, db_path: Path | None = None) -> Deal:
    """Return the deal with ``deal_id``, dispatching by which table
    actually holds it: ``deals`` (Quick) first, then ``detailed_deals`` +
    ``detailed_operating_inputs`` (Detailed). Raises ``DealNotFoundError``
    if ``deal_id`` is in neither.

    Phase 6 Gate D6.5: every mode's deal carries its stored Business Plan,
    read from the same two tables inside the same connection."""

    with _connect(db_path) as connection:
        return _read_deal(connection, deal_id)


def _read_deal(connection: sqlite3.Connection, deal_id: str) -> Deal:
    """``get_deal``'s read, inside the caller's connection -- so a P7.6
    Investment write can judge its Units' stored inputs in the same
    transaction that writes the Investment. Unchanged from ``get_deal``."""

    quick_row = connection.execute(
        "SELECT * FROM deals WHERE id = ?", (deal_id,)
    ).fetchone()
    if quick_row is not None:
        return _row_to_deal(
            quick_row, business_plan=_read_business_plan(connection, deal_id)
        )

    detailed_row = connection.execute(
        "SELECT * FROM detailed_deals WHERE id = ?", (deal_id,)
    ).fetchone()
    if detailed_row is None:
        # D5.4: the third table family. Probed last, so Quick and Detailed
        # lookups are unchanged, and returned as LEASE_LEVEL by construction
        # -- the mode is which table the row lives in, never a guess.
        lease_level_row = connection.execute(
            "SELECT * FROM lease_level_deals WHERE id = ?", (deal_id,)
        ).fetchone()
        if lease_level_row is None:
            raise DealNotFoundError(deal_id)
        return _row_to_lease_level_deal(
            connection,
            lease_level_row,
            business_plan=_read_business_plan(connection, deal_id),
        )

    operating_row = connection.execute(
        "SELECT * FROM detailed_operating_inputs WHERE deal_id = ?", (deal_id,)
    ).fetchone()
    if operating_row is None:
        # The 1:1 invariant (both rows always written/removed together
        # by this module) means this should never happen; surfaced as
        # DealNotFoundError rather than a raw None-access crash if it
        # somehow does (e.g. a hand-edited database).
        raise DealNotFoundError(deal_id)

    return _row_to_detailed_deal(
        detailed_row,
        operating_row,
        business_plan=_read_business_plan(connection, deal_id),
    )


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
        lease_level_rows = connection.execute(
            "SELECT * FROM lease_level_deals"
        ).fetchall()
        # D6.5: every listed deal's Business Plan, in two queries for the whole
        # library. A plan is input state, like the rent roll, so a listed deal
        # carries its real plan rather than a placeholder.
        business_plans = _read_all_business_plans(
            connection,
            [row["id"] for row in (*quick_rows, *detailed_rows, *lease_level_rows)],
        )
        # Built inside the connection block: a Lease-Level deal is assembled
        # from five child tables, so its reader needs the live connection --
        # unlike the flat Quick/Detailed rows, which are complete on their own.
        lease_level_deals = [
            _row_to_lease_level_deal(
                connection,
                row,
                business_plan=business_plans[row["id"]],
                include_snapshots=False,
            )
            for row in lease_level_rows
        ]
        operating_rows_by_deal_id = {
            row["deal_id"]: row
            for row in connection.execute("SELECT * FROM detailed_operating_inputs")
        }

    quick_deals = [
        _row_to_deal(
            row, business_plan=business_plans[row["id"]], include_snapshots=False
        )
        for row in quick_rows
    ]
    detailed_deals = [
        _row_to_detailed_deal(
            row,
            operating_rows_by_deal_id[row["id"]],
            business_plan=business_plans[row["id"]],
            include_snapshots=False,
        )
        for row in detailed_rows
    ]

    # ISO-8601 UTC timestamps (_utc_now_iso) sort lexicographically in
    # chronological order, so string comparison alone is sufficient --
    # matches the ordering "SELECT * FROM deals ORDER BY updated_at DESC"
    # already produced for Quick-only queries before this gate.
    return sorted(
        [*quick_deals, *detailed_deals, *lease_level_deals],
        key=lambda deal: deal.updated_at,
        reverse=True,
    )


def delete_deal(deal_id: str, *, db_path: Path | None = None) -> None:
    """Permanently delete the deal with ``deal_id``, dispatching by which
    table holds it. Raises ``DealNotFoundError`` if it doesn't exist in
    either. No soft-delete and no history -- the row(s) are simply gone. A
    Detailed deal's ``detailed_operating_inputs`` row is always removed
    together with its ``detailed_deals`` row."""

    with _connect(db_path) as connection:
        # P7.2: a Deal inside the hidden Scenario wrapper takes the wrapper with
        # it -- cached variants, overrides, Scenarios, membership and the hidden
        # Investment -- in this same transaction, so nothing is orphaned. A Deal
        # in a visible Investment is refused instead (Section 15.2), and a
        # standalone Deal has nothing to remove. A failure below rolls this back.
        _remove_hidden_wrapper_of_deal(connection, deal_id)
        # D5.8A: derived analytical state is removed first, for every mode,
        # before any parent row is looked at -- so a deal that turns out to live
        # in the Quick table leaves no sensitivity row behind either. Explicit
        # rather than by cascade for the reason stated below: this module never
        # enables ``PRAGMA foreign_keys``, so a declared ON DELETE CASCADE would
        # do nothing at all. Deleting unconditionally is also what makes it
        # impossible to add a fourth mode later and forget this line.
        connection.execute(
            "DELETE FROM deal_sensitivity_snapshots WHERE deal_id = ?", (deal_id,)
        )
        # D6.5: the Business Plan tables are mode-blind, so their rows go the
        # same way and for the same reason -- unconditionally, first, for every
        # mode. A deal id that turns out to exist nowhere raises below, and the
        # raise rolls this delete back with everything else.
        _delete_business_plan(connection, deal_id)

        cursor = connection.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
        if cursor.rowcount > 0:
            return

        connection.execute(
            "DELETE FROM detailed_operating_inputs WHERE deal_id = ?", (deal_id,)
        )
        cursor = connection.execute(
            "DELETE FROM detailed_deals WHERE id = ?", (deal_id,)
        )
        if cursor.rowcount > 0:
            return

        # D5.4: children first, then the parent, in one transaction. Explicit
        # rather than by cascade, because this module never enables
        # ``PRAGMA foreign_keys`` -- a declared ON DELETE CASCADE would do
        # nothing and leave orphan suites behind a schema that looked safe.
        _delete_lease_level_children(connection, deal_id)
        cursor = connection.execute(
            "DELETE FROM lease_level_deals WHERE id = ?", (deal_id,)
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
    copy exactly like any other change -- see ``update_deal``.

    Phase 6 Gate D6.5: the Business Plan is underwriting, not an analytical
    output, so it is always copied -- every item, in order, with the same item
    IDs (unique only within one plan) -- in the same transaction that creates
    the copy. The copy's rows are its own: editing or deleting either deal's
    plan never touches the other's. Both fingerprints include the plan, so a
    copied snapshot stays valid exactly when the copied plan is unchanged."""

    original = get_deal(deal_id, db_path=db_path)
    new_name = name if name else f"{original.name} (Copy)"

    # D5.1A: total dispatch. This branch was ``if QUICK: ... else: <Detailed
    # copy>``, so a deal of any third mode would have been duplicated *as a
    # Detailed deal* -- silently rewriting the copy's operating mode and, with
    # it, which engine later underwrites it. That is a data-corruption path, not
    # merely a wrong error message, which is why it is closed here rather than
    # in the gate that adds the mode's own persistence.
    match original.operating_mode:
        case OperatingMode.QUICK:
            assert original.inputs is not None
            new_deal = create_deal(
                new_name,
                original.inputs,
                deal_context=original.deal_context,
                business_plan=original.business_plan,
                db_path=db_path,
            )
            analysis_fingerprint = fingerprint_quick_inputs(
                original.inputs, business_plan=original.business_plan
            )
        case OperatingMode.DETAILED:
            assert original.terms is not None
            assert original.detailed_operating_inputs is not None
            new_deal = create_detailed_deal(
                new_name,
                original.terms,
                original.detailed_operating_inputs,
                deal_context=original.deal_context,
                business_plan=original.business_plan,
                db_path=db_path,
            )
            analysis_fingerprint = fingerprint_detailed_inputs(
                original.terms,
                original.detailed_operating_inputs,
                business_plan=original.business_plan,
            )
        case OperatingMode.LEASE_LEVEL:
            # D5.4 implements what D5.1A made safe. The copy keeps its own mode
            # -- the whole point of the arm D5.1A added, since the implicit
            # ``else`` it replaced would have written a *Detailed* deal here and
            # silently changed which engine underwrites the copy.
            assert original.terms is not None
            assert original.property_inputs is not None
            assert original.operating_inputs is not None
            assert original.market_leasing is not None
            assert original.suites is not None
            assert original.leases is not None
            new_deal = create_lease_level_deal(
                new_name,
                original.terms,
                original.property_inputs,
                original.operating_inputs,
                original.market_leasing,
                original.suites,
                original.leases,
                deal_context=original.deal_context,
                business_plan=original.business_plan,
                db_path=db_path,
            )
            analysis_fingerprint = fingerprint_lease_level_inputs(
                original.terms,
                original.property_inputs,
                original.suites,
                original.leases,
                market_leasing=original.market_leasing,
                operating_inputs=original.operating_inputs,
                business_plan=original.business_plan,
            )
        case _:
            raise UnsupportedOperatingModeError(
                original.operating_mode, operation="duplicate_deal"
            )

    if original.analysis_snapshot is not None:
        new_deal = update_analysis_snapshot(
            new_deal.id,
            dataclasses.asdict(original.analysis_snapshot),
            financial_input_fingerprint=analysis_fingerprint,
            db_path=db_path,
        )

    # D5.8A -- the copy starts with no derived analytical state of its own,
    # except where a shipped mode already promised otherwise.
    #
    # An AI report and a sensitivity matrix are analytical *outputs* associated
    # with the deal instance that produced them; "Duplicate" copies the
    # underwriting, and a copy that silently arrived carrying somebody else's
    # analysis would read as work the analyst had done on it. So:
    #
    #   * ``deal_sensitivity_snapshots`` rows are never copied, for any mode.
    #     There is no code below that copies them, which is the strongest form
    #     of that rule -- ``create_*_deal`` writes no row into that table and
    #     nothing here adds one.
    #
    #   * A Lease-Level AI report is never copied. Lease-Level AI persistence is
    #     new in this gate, so there is no shipped behavior to preserve and the
    #     rule applies from the start.
    #
    #   * Quick's and Detailed's ``analysis_snapshot``/``ai_snapshot`` copying is
    #     UNCHANGED. It is a deliberate, documented and separately tested Gate A6
    #     decision (the cached result is mathematically still valid for a copy
    #     whose assumptions and Deal Context begin byte-identical), and D5.8A is
    #     explicitly forbidden from regressing either of those two modes.
    if (
        original.ai_snapshot is not None
        and original.operating_mode is not OperatingMode.LEASE_LEVEL
    ):
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
            expected_fingerprint = fingerprint_quick_inputs(
                _inputs_from_row(quick_row),
                business_plan=_read_business_plan(connection, deal_id),
            )
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
                _terms_from_row(detailed_row),
                _detailed_operating_inputs_from_row(operating_row),
                business_plan=_read_business_plan(connection, deal_id),
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
            analysis_fingerprint = fingerprint_quick_inputs(
                _inputs_from_row(quick_row),
                business_plan=_read_business_plan(connection, deal_id),
            )
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
            if detailed_row is not None:
                operating_row = connection.execute(
                    "SELECT * FROM detailed_operating_inputs WHERE deal_id = ?", (deal_id,)
                ).fetchone()
                if operating_row is None:
                    raise DealNotFoundError(deal_id)

                analysis_fingerprint = fingerprint_detailed_inputs(
                    _terms_from_row(detailed_row),
                    _detailed_operating_inputs_from_row(operating_row),
                    business_plan=_read_business_plan(connection, deal_id),
                )
                expected_fingerprint = fingerprint_ai(
                    analysis_fingerprint=analysis_fingerprint,
                    deal_context=detailed_row["deal_context"],
                )
                _validate_provenance(
                    provided_fingerprint=ai_context_fingerprint,
                    expected_fingerprint=expected_fingerprint,
                    label="ai_snapshot's ai_context_fingerprint",
                )
                connection.execute(
                    """
                    UPDATE detailed_deals
                    SET ai_snapshot = ?, ai_snapshot_schema_version = ?,
                        ai_snapshot_fingerprint = ?
                    WHERE id = ?
                    """,
                    (encoded, _AI_SNAPSHOT_SCHEMA_VERSION, expected_fingerprint, deal_id),
                )
            else:
                # D5.8A -- the third arm.
                #
                # ``lease_level_deals`` has carried the three ``ai_snapshot``
                # columns, and ``_row_to_lease_level_deal`` has decoded them,
                # since D5.4 -- but nothing could ever write one, because this
                # function stopped looking after ``detailed_deals`` and raised
                # ``DealNotFoundError`` for a Lease-Level id. That is the exact
                # reason a Lease-Level AI report vanished on navigation: it was
                # never persisted at all. No schema change is needed to fix it;
                # the storage was already there and only the write path was
                # missing.
                lease_level_row = connection.execute(
                    "SELECT * FROM lease_level_deals WHERE id = ?", (deal_id,)
                ).fetchone()
                if lease_level_row is None:
                    raise DealNotFoundError(deal_id)

                analysis_fingerprint = _lease_level_input_fingerprint(
                    connection, lease_level_row
                )
                expected_fingerprint = fingerprint_ai(
                    analysis_fingerprint=analysis_fingerprint,
                    deal_context=lease_level_row["deal_context"],
                )
                _validate_provenance(
                    provided_fingerprint=ai_context_fingerprint,
                    expected_fingerprint=expected_fingerprint,
                    label="ai_snapshot's ai_context_fingerprint",
                )
                connection.execute(
                    """
                    UPDATE lease_level_deals
                    SET ai_snapshot = ?, ai_snapshot_schema_version = ?,
                        ai_snapshot_fingerprint = ?
                    WHERE id = ?
                    """,
                    (encoded, _AI_SNAPSHOT_SCHEMA_VERSION, expected_fingerprint, deal_id),
                )

    return get_deal(deal_id, db_path=db_path)


# =============================================================================
# Sprint D5.8A -- provenance-validated sensitivity-snapshot writes
#
# The only two functions in this module that ever write to
# ``deal_sensitivity_snapshots``, and they follow Gate A7's contract exactly:
# the caller supplies the fingerprint the run was actually performed under
# (obtained from ``POST /deals/fingerprint``), this layer independently
# recomputes the fingerprint the deal's CURRENTLY STORED assumptions demand, and
# a mismatch is refused with nothing persisted. The caller's token only ever
# unlocks a write this module's own recomputation already agrees with.
#
# Two things follow structurally from the ``(deal_id, analysis_kind)`` primary
# key and the ``INSERT .. ON CONFLICT .. DO UPDATE`` below:
#
#   * one-way and two-way never touch each other -- different rows, different
#     statements, no shared column;
#   * a re-run replaces the latest snapshot for its own kind atomically, in a
#     single statement, so no intermediate state exists where the new
#     configuration is stored beside the old result.
#
# Only a SUCCESSFUL run ever reaches here. A validation failure, a shadowed
# target, a ``NON_POSITIVE_FORWARD_EXIT_NOI`` refusal or a transport error
# produces no result to pass in, so the previous successful snapshot is left
# untouched by construction rather than by a rule someone has to remember.
# =============================================================================


def _update_sensitivity_snapshot(
    deal_id: str,
    kind: str,
    snapshot: OneWaySensitivitySnapshot | TwoWaySensitivitySnapshot,
    *,
    financial_input_fingerprint: str,
    db_path: Path | None,
) -> Deal:
    """The shared body of the two public writers below."""

    encoded = _encode_snapshot(snapshot)

    # ``get_deal`` opens its own connection and must run only after this block
    # has committed -- same rule as ``update_ai_snapshot`` above.
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM lease_level_deals WHERE id = ?", (deal_id,)
        ).fetchone()
        if row is None:
            # Total dispatch, D5.1A's rule: a deal that exists in another mode's
            # table is refused *by name* rather than falling through to a
            # not-found error that would read as a missing deal. D5.8A ships this
            # surface for Lease-Level only; Quick and Detailed recompute their
            # standardized preset bundle on every Analyze and have no
            # analyst-configured sensitivity to keep.
            mode = _operating_mode_of(connection, deal_id)
            if mode is None:
                raise DealNotFoundError(deal_id)
            raise UnsupportedOperatingModeError(
                mode, operation="update_sensitivity_snapshot"
            )

        expected_fingerprint = _lease_level_input_fingerprint(connection, row)
        _validate_provenance(
            provided_fingerprint=financial_input_fingerprint,
            expected_fingerprint=expected_fingerprint,
            label=f"{kind} sensitivity snapshot's financial_input_fingerprint",
        )
        connection.execute(
            """
            INSERT INTO deal_sensitivity_snapshots
                (deal_id, analysis_kind, snapshot, schema_version,
                 source_fingerprint, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (deal_id, analysis_kind) DO UPDATE SET
                snapshot = excluded.snapshot,
                schema_version = excluded.schema_version,
                source_fingerprint = excluded.source_fingerprint,
                generated_at = excluded.generated_at
            """,
            (
                deal_id,
                kind,
                encoded,
                _SENSITIVITY_SNAPSHOT_SCHEMA_VERSION,
                expected_fingerprint,
                _utc_now_iso(),
            ),
        )

    return get_deal(deal_id, db_path=db_path)


def _operating_mode_of(
    connection: sqlite3.Connection, deal_id: str
) -> OperatingMode | None:
    """Which mode's table holds ``deal_id``, or ``None`` if no table does.

    The mode is not stored anywhere -- it is which table the row lives in -- so
    this is the one honest way to answer the question, and it stays in one
    place rather than being re-derived at each call site.
    """

    for table, mode in (
        ("deals", OperatingMode.QUICK),
        ("detailed_deals", OperatingMode.DETAILED),
        ("lease_level_deals", OperatingMode.LEASE_LEVEL),
    ):
        found = connection.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (deal_id,)
        ).fetchone()
        if found is not None:
            return mode
    return None


def update_one_way_sensitivity_snapshot(
    deal_id: str,
    snapshot: dict[str, Any],
    *,
    financial_input_fingerprint: str,
    db_path: Path | None = None,
) -> Deal:
    """Replace ``deal_id``'s latest successful one-way sensitivity snapshot.

    ``snapshot`` is the ``{configuration, result}`` pair as one document.
    ``financial_input_fingerprint`` must equal the canonical fingerprint of
    ``deal_id``'s own currently-stored Lease-Level assumptions. Raises
    ``SnapshotValidationError`` (persisting nothing) if it does not, or if
    ``snapshot`` is malformed; ``DealNotFoundError`` if ``deal_id`` exists in no
    table; ``UnsupportedOperatingModeError`` if it is a Quick or Detailed deal.

    Leaves the two-way snapshot, the AI snapshot, the assumptions, the name,
    Deal Context and ``updated_at`` completely untouched.
    """

    return _update_sensitivity_snapshot(
        deal_id,
        _ONE_WAY_KIND,
        _one_way_sensitivity_snapshot_from_dict(snapshot),
        financial_input_fingerprint=financial_input_fingerprint,
        db_path=db_path,
    )


def update_two_way_sensitivity_snapshot(
    deal_id: str,
    snapshot: dict[str, Any],
    *,
    financial_input_fingerprint: str,
    db_path: Path | None = None,
) -> Deal:
    """Replace ``deal_id``'s latest successful two-way sensitivity snapshot.

    Mirrors ``update_one_way_sensitivity_snapshot`` exactly, over the other
    ``analysis_kind``, and leaves the one-way snapshot untouched.
    """

    return _update_sensitivity_snapshot(
        deal_id,
        _TWO_WAY_KIND,
        _two_way_sensitivity_snapshot_from_dict(snapshot),
        financial_input_fingerprint=financial_input_fingerprint,
        db_path=db_path,
    )


# =============================================================================
# Phase 7 Gate P7.2 -- the Investment shell and persisted Scenarios
#
# Every function below manages only the **hidden one-unit Investment**, the
# wrapper a standalone Deal gains with its first Scenario (Q4, Section 15.1):
#
#   * **Opt-in only.** ``_materialize_hidden_investment`` is the one place an
#     Investment row is ever written, and ``create_scenario_for_deal`` is its
#     one caller -- inside the same transaction as that first Scenario, after
#     the Scenario has passed validation. Creating, saving, opening, listing,
#     analysing or fingerprinting a Deal never reaches it, and neither does any
#     read below. A failure anywhere rolls the whole write back: no empty
#     Investment, no membership and no partial Scenario survives.
#   * **One authority for the contract.** Every Scenario is validated by the
#     P7.1 stage-1 validator for the wrapper's one unit, on the way in and
#     again on the way out, so a stored Scenario that no longer validates fails
#     closed (``PersistedScenarioDataError``) rather than being repaired.
#   * **Fail closed outside the wrapper.** A visible Investment is a later
#     gate's structure. Every function here refuses it
#     (``InvestmentStructureError``) rather than editing, collapsing, orphaning
#     or deleting it, and a hidden wrapper that does not hold exactly one saved
#     Deal is refused as corrupt (``PersistedDealDataError``).
#   * **Ownership is proven, never assumed.** A Scenario is found only through
#     the Investment that owns it; a foreign id is simply not found.
#
# Nothing here computes anything. Resolution, fingerprints and analysis live in
# ``anchor.deals.variants``, over the P7.1 resolvers and the D6 entry points.
# =============================================================================

#: The serialized-result contract of one cached Quick or Detailed variant: the
#: same ``AcquisitionResults`` / ``DetailedAcquisitionResults`` shape the deal
#: analysis snapshot stores. Bump it with any change that stops a stored result
#: from decoding, exactly as ``_ANALYSIS_SNAPSHOT_SCHEMA_VERSION`` is bumped: a
#: row of another version then reads as absent and is recomputed.
_VARIANT_SNAPSHOT_SCHEMA_VERSION = 1


def _decode_hidden_flag(row: sqlite3.Row) -> bool:
    value = row["is_hidden"]
    if value == 1:
        return True
    if value == 0:
        return False
    raise PersistedDealDataError(
        f"Investment {row['id']!r} holds is_hidden={value!r}; it must be 0 or 1."
    )


def _investment_row(connection: sqlite3.Connection, investment_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM investments WHERE id = ?", (investment_id,)
    ).fetchone()
    if row is None:
        raise InvestmentNotFoundError(investment_id)
    return row


def _unit_rows(connection: sqlite3.Connection, investment_id: str) -> list[sqlite3.Row]:
    """The Investment's membership rows, in ``deal_id`` order: membership is a
    set, and its order means nothing (Section 15.5)."""

    return connection.execute(
        "SELECT deal_id FROM investment_units WHERE investment_id = ? ORDER BY deal_id",
        (investment_id,),
    ).fetchall()


def _investment_of_deal(connection: sqlite3.Connection, deal_id: str) -> str | None:
    """The one Investment ``deal_id`` belongs to, or ``None``.

    A Deal belongs to at most one Investment (Q3). The ``UNIQUE`` column makes
    a second membership unwritable; a database that holds one anyway (a table
    built without the constraint) is corrupt and is refused, never resolved by
    picking one."""

    rows = connection.execute(
        "SELECT investment_id FROM investment_units WHERE deal_id = ? ORDER BY investment_id",
        (deal_id,),
    ).fetchall()
    if len(rows) > 1:
        raise PersistedDealDataError(
            f"Deal {deal_id!r} belongs to {len(rows)} investments; a deal belongs "
            "to at most one."
        )
    return rows[0]["investment_id"] if rows else None


def _require_hidden_wrapper(
    connection: sqlite3.Connection, investment_id: str
) -> tuple[str, OperatingMode]:
    """The one unit of the hidden wrapper ``investment_id``, and that Deal's
    operating mode -- or a refusal.

    - an unknown id: ``InvestmentNotFoundError``;
    - a visible Investment: ``InvestmentStructureError`` (a later gate's
      structure, which P7.2 never changes);
    - a hidden wrapper without exactly one member, or whose member is no saved
      Deal: ``PersistedDealDataError``.
    """

    row = _investment_row(connection, investment_id)
    if not _decode_hidden_flag(row):
        raise InvestmentStructureError(
            f"Investment {investment_id!r} is a visible Investment. P7.2 manages only "
            "the hidden one-unit Scenario wrapper and does not change a visible one."
        )
    units = _unit_rows(connection, investment_id)
    if len(units) != 1:
        raise PersistedDealDataError(
            f"Hidden investment {investment_id!r} has {len(units)} units; the Scenario "
            "wrapper has exactly one."
        )
    unit_id = units[0]["deal_id"]
    operating_mode = _operating_mode_of(connection, unit_id)
    if operating_mode is None:
        raise PersistedDealDataError(
            f"Hidden investment {investment_id!r} names unit {unit_id!r}, which is not "
            "a saved deal."
        )
    return unit_id, operating_mode


def _require_owned_scenario(
    connection: sqlite3.Connection, investment_id: str, scenario_id: str
) -> None:
    found = connection.execute(
        "SELECT 1 FROM scenarios WHERE id = ? AND investment_id = ?",
        (scenario_id, investment_id),
    ).fetchone()
    if found is None:
        raise ScenarioNotFoundError(investment_id, scenario_id)


class _StructureOwner:
    """The Investment that owns Strategies and Scenarios, as their validators
    see it: the hidden wrapper's one Unit, or -- from P7.6 -- a visible
    Investment's member Units, each with its Deal's operating mode, in
    ``unit_id`` order.

    A plain slotted class rather than a dataclass: this module defines no
    dataclass of its own, and several tests load it as a fresh module outside
    ``sys.modules``, where dataclass annotation resolution cannot run."""

    __slots__ = ("investment_id", "hidden", "unit_modes")

    def __init__(
        self, *, investment_id: str, hidden: bool, unit_modes: Mapping[str, OperatingMode]
    ) -> None:
        self.investment_id = investment_id
        self.hidden = hidden
        self.unit_modes = unit_modes


def _require_structure_owner(
    connection: sqlite3.Connection, investment_id: str
) -> _StructureOwner:
    """The owner of ``investment_id``'s Strategies and Scenarios, or a
    refusal. A hidden wrapper is judged exactly as P7.2 judged it; a visible
    Investment must hold coherent sidecars and only saved Deals."""

    row = _investment_row(connection, investment_id)
    if _decode_hidden_flag(row):
        unit_id, operating_mode = _require_hidden_wrapper(connection, investment_id)
        return _StructureOwner(
            investment_id=investment_id, hidden=True, unit_modes={unit_id: operating_mode}
        )
    return _StructureOwner(
        investment_id=investment_id,
        hidden=False,
        unit_modes=_require_visible_units(connection, investment_id),
    )


def _scenario_contract_issues(
    scenario: ScenarioDefinition, owner: _StructureOwner
) -> tuple[ScenarioIssue, ...]:
    """The hidden wrapper's Scenarios keep the exact P7.1 one-Unit contract; a
    visible Investment's are judged against its member set (P7.6)."""

    if owner.hidden:
        ((unit_id, operating_mode),) = owner.unit_modes.items()
        return validate_scenario(scenario, operating_mode=operating_mode, unit_id=unit_id)
    return validate_investment_scenario(scenario, unit_modes=owner.unit_modes)


def _require_valid_scenario(scenario: ScenarioDefinition, *, owner: _StructureOwner) -> None:
    """The P7.1 stage-1 contract, for the owner's Units: identity, naming,
    unit addressing (SC-5), ``(unit_id, target)`` uniqueness (SC-1), targets,
    each target's operation whitelist (Q5) and finite values. This store adds
    no rule of its own."""

    issues = _scenario_contract_issues(scenario, owner)
    if issues:
        raise ScenarioValidationError(issues)


def _stored_token(value: object, token_type: type[ScenarioTarget] | type[ScenarioOperation]) -> Any:
    """A stored token as its member -- or, when no member has it, the raw value,
    so that the P7.1 validator reports it in its own deterministic order rather
    than this codec reporting it first."""

    if isinstance(value, str):
        try:
            return token_type(value)
        except ValueError:
            return value
    return value


_TARGET_RANK = {target: rank for rank, target in enumerate(ScenarioTarget)}


def _override_order(override: ScenarioOverride) -> tuple[str, int, str]:
    """Canonical override order: unit, then the P7.1 target registry's
    declaration order. An unrecognised target sorts after every real one."""

    target = override.target
    rank = _TARGET_RANK[target] if isinstance(target, ScenarioTarget) else len(_TARGET_RANK)
    return str(override.unit_id), rank, str(target)


def _scenario_from_rows(
    scenario_row: sqlite3.Row,
    override_rows: Iterable[sqlite3.Row],
    *,
    owner: _StructureOwner,
) -> ScenarioDefinition:
    """Rebuild one stored Scenario as the exact P7.1 contract and refuse it if
    the P7.1 validator does. Nothing is repaired, defaulted or dropped."""

    overrides = tuple(
        sorted(
            (
                ScenarioOverride(
                    unit_id=row["unit_id"],
                    target=_stored_token(row["target"], ScenarioTarget),
                    operation=_stored_token(row["operation"], ScenarioOperation),
                    value=row["value"],
                )
                for row in override_rows
            ),
            key=_override_order,
        )
    )
    scenario = ScenarioDefinition(
        scenario_id=scenario_row["id"],
        name=scenario_row["name"],
        description=scenario_row["description"],
        overrides=overrides,
    )
    issues = _scenario_contract_issues(scenario, owner)
    if issues:
        raise PersistedScenarioDataError(scenario_row["id"], issues)
    return scenario


def _read_scenarios(
    connection: sqlite3.Connection,
    investment_id: str,
    *,
    owner: _StructureOwner,
    scenario_id: str | None = None,
) -> list[InvestmentScenario]:
    """The wrapper's Scenarios -- or the one ``scenario_id`` it owns -- in
    creation order. That order is presentation only; the insertion ``rowid``
    breaks a timestamp tie, so it never depends on a random id."""

    if scenario_id is None:
        rows = connection.execute(
            "SELECT * FROM scenarios WHERE investment_id = ? ORDER BY created_at, rowid",
            (investment_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM scenarios WHERE investment_id = ? AND id = ?",
            (investment_id, scenario_id),
        ).fetchall()
    scenarios: list[InvestmentScenario] = []
    for row in rows:
        override_rows = connection.execute(
            "SELECT * FROM scenario_overrides WHERE scenario_id = ? ORDER BY unit_id, target",
            (row["id"],),
        ).fetchall()
        scenarios.append(
            InvestmentScenario(
                investment_id=investment_id,
                scenario=_scenario_from_rows(row, override_rows, owner=owner),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        )
    return scenarios


def _write_scenario_overrides(
    connection: sqlite3.Connection, scenario_id: str, overrides: Iterable[ScenarioOverride]
) -> None:
    """Every override of one Scenario. Called inside the caller's transaction,
    after validation, and after any previous overrides were removed: an
    override set is replaced whole, never diffed."""

    connection.executemany(
        """
        INSERT INTO scenario_overrides (scenario_id, unit_id, target, operation, value)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                scenario_id,
                override.unit_id,
                _encode_enum(override.target),
                _encode_enum(override.operation),
                float(override.value),
            )
            for override in overrides
        ],
    )


def _touch_investment(connection: sqlite3.Connection, investment_id: str, *, now: str) -> None:
    connection.execute(
        "UPDATE investments SET updated_at = ? WHERE id = ?", (now, investment_id)
    )


def _insert_scenario(
    connection: sqlite3.Connection,
    investment_id: str,
    scenario: ScenarioDefinition,
    *,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO scenarios (id, investment_id, name, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (scenario.scenario_id, investment_id, scenario.name, scenario.description, now, now),
    )
    _write_scenario_overrides(connection, scenario.scenario_id, scenario.overrides)
    _touch_investment(connection, investment_id, now=now)


def _materialize_hidden_investment(
    connection: sqlite3.Connection, deal_id: str, *, now: str
) -> str:
    """Create the hidden one-unit Investment for the standalone ``deal_id``.

    The only code that writes an Investment or a membership. Its two callers,
    ``create_scenario_for_deal`` and (from P7.4) ``create_strategy_for_deal``,
    reach it only for a Deal with no Investment, only after the first Scenario
    or Strategy has validated, and only inside the transaction that then writes
    it."""

    investment_id = uuid.uuid4().hex
    connection.execute(
        "INSERT INTO investments (id, is_hidden, created_at, updated_at) VALUES (?, 1, ?, ?)",
        (investment_id, now, now),
    )
    connection.execute(
        "INSERT INTO investment_units (investment_id, deal_id) VALUES (?, ?)",
        (investment_id, deal_id),
    )
    return investment_id


def _delete_scenario_rows(
    connection: sqlite3.Connection, investment_id: str, scenario_id: str
) -> None:
    """One Scenario and everything it owns: its cached variants and overrides."""

    connection.execute(
        "DELETE FROM variant_snapshots WHERE root_id = ? AND scenario_id = ?",
        (investment_id, scenario_id),
    )
    connection.execute("DELETE FROM scenario_overrides WHERE scenario_id = ?", (scenario_id,))
    connection.execute(
        "DELETE FROM scenarios WHERE id = ? AND investment_id = ?", (scenario_id, investment_id)
    )


def _delete_investment_rows(connection: sqlite3.Connection, investment_id: str) -> None:
    """Every row the Investment owns -- cached variants, Strategy overlays and
    Strategies (P7.4), overrides, Scenarios, membership and the Investment
    itself -- and never a Deal row. Deleting an Investment releases its Deal
    (Q3)."""

    connection.execute("DELETE FROM variant_snapshots WHERE root_id = ?", (investment_id,))
    # P7.6: a visible Investment's sidecars. A hidden wrapper has none, so this
    # deletes nothing for it.
    for table in _P7_6_TABLES:
        connection.execute(f"DELETE FROM {table} WHERE investment_id = ?", (investment_id,))
    for table in _STRATEGY_OVERLAY_TABLES:
        connection.execute(
            f"DELETE FROM {table} WHERE strategy_id IN "
            "(SELECT id FROM strategies WHERE investment_id = ?)",
            (investment_id,),
        )
    connection.execute("DELETE FROM strategies WHERE investment_id = ?", (investment_id,))
    connection.execute(
        "DELETE FROM scenario_overrides WHERE scenario_id IN "
        "(SELECT id FROM scenarios WHERE investment_id = ?)",
        (investment_id,),
    )
    connection.execute("DELETE FROM scenarios WHERE investment_id = ?", (investment_id,))
    connection.execute("DELETE FROM investment_units WHERE investment_id = ?", (investment_id,))
    connection.execute("DELETE FROM investments WHERE id = ?", (investment_id,))


def _wrapper_holds_no_structure(connection: sqlite3.Connection, investment_id: str) -> bool:
    """Whether the hidden wrapper has no P7 structure left: no Scenario and,
    from P7.4, no Strategy. A wrapper that still holds either never collapses,
    whichever of the two was deleted last."""

    remaining_scenario = connection.execute(
        "SELECT 1 FROM scenarios WHERE investment_id = ? LIMIT 1", (investment_id,)
    ).fetchone()
    remaining_strategy = connection.execute(
        "SELECT 1 FROM strategies WHERE investment_id = ? LIMIT 1", (investment_id,)
    ).fetchone()
    return remaining_scenario is None and remaining_strategy is None


def _remove_hidden_wrapper_of_deal(connection: sqlite3.Connection, deal_id: str) -> None:
    """Called by ``delete_deal``, inside its transaction: remove the hidden
    wrapper ``deal_id`` belongs to, if any, before the Deal itself goes.

    Only the hidden one-unit wrapper is removed this way (Section 21.3). A Deal
    in a visible Investment is refused, because Section 15.2 requires removing
    it from the Investment first."""

    investment_id = _investment_of_deal(connection, deal_id)
    if investment_id is None:
        return
    if not _decode_hidden_flag(_investment_row(connection, investment_id)):
        # P7.6: fail closed, and never mutate the visible Investment.
        raise InvestmentStructureError(
            f"Deal {deal_id!r} is a Unit of a visible Investment. Remove the Unit from the "
            "Investment before deleting the Deal; deleting a Deal never changes an "
            "Investment."
        )
    _require_hidden_wrapper(connection, investment_id)
    _delete_investment_rows(connection, investment_id)


def create_scenario_for_deal(
    deal_id: str,
    *,
    name: str,
    description: str | None = None,
    overrides: Iterable[ScenarioOverride] = (),
    db_path: Path | None = None,
) -> InvestmentScenario:
    """Persist a new Scenario for the Deal ``deal_id``, materializing its hidden
    one-unit Investment first if it has none (Q4).

    One transaction: the Deal must exist; any Investment it already belongs to
    must be its hidden wrapper, which is reused (never one Investment per
    Scenario); the Scenario must pass the P7.1 contract for this unit; then the
    Investment and membership (first Scenario only), the Scenario and its
    overrides are written. Any failure leaves no row behind.

    Raises ``DealNotFoundError``, ``InvestmentStructureError``,
    ``ScenarioValidationError`` or ``PersistedDealDataError``."""

    scenario = ScenarioDefinition(
        scenario_id=uuid.uuid4().hex,
        name=name,
        description=description,
        overrides=tuple(overrides),
    )
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        operating_mode = _operating_mode_of(connection, deal_id)
        if operating_mode is None:
            raise DealNotFoundError(deal_id)
        investment_id = _investment_of_deal(connection, deal_id)
        if investment_id is not None:
            _require_hidden_wrapper(connection, investment_id)
        _require_valid_scenario(
            scenario,
            owner=_StructureOwner(
                investment_id=investment_id or "", hidden=True, unit_modes={deal_id: operating_mode}
            ),
        )
        if investment_id is None:
            investment_id = _materialize_hidden_investment(connection, deal_id, now=now)
        _insert_scenario(connection, investment_id, scenario, now=now)

    return get_scenario(investment_id, scenario.scenario_id, db_path=db_path)


def create_scenario(
    investment_id: str,
    *,
    name: str,
    description: str | None = None,
    overrides: Iterable[ScenarioOverride] = (),
    db_path: Path | None = None,
) -> InvestmentScenario:
    """Persist another Scenario in the existing Investment ``investment_id``:
    the hidden wrapper, validated for its one unit, or (P7.6) a visible
    Investment, validated for its member Units."""

    scenario = ScenarioDefinition(
        scenario_id=uuid.uuid4().hex,
        name=name,
        description=description,
        overrides=tuple(overrides),
    )
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        _require_valid_scenario(scenario, owner=owner)
        _insert_scenario(connection, investment_id, scenario, now=now)

    return get_scenario(investment_id, scenario.scenario_id, db_path=db_path)


def update_scenario(
    investment_id: str,
    scenario_id: str,
    *,
    name: str,
    description: str | None = None,
    overrides: Iterable[ScenarioOverride] = (),
    db_path: Path | None = None,
) -> InvestmentScenario:
    """Replace one Scenario's name, description and whole override set,
    keeping its id.

    Validated before anything is written; the old overrides are removed and
    the new ones written in the same transaction, so a failure leaves the
    previous Scenario exactly as it was. Cached variants are left alone: each
    is served only while its source fingerprint still matches the resolved
    inputs, so a recipe that resolves to the same inputs keeps its cache and
    any other change makes the old row stale."""

    scenario = ScenarioDefinition(
        scenario_id=scenario_id,
        name=name,
        description=description,
        overrides=tuple(overrides),
    )
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        _require_owned_scenario(connection, investment_id, scenario_id)
        _require_valid_scenario(scenario, owner=owner)
        connection.execute(
            "UPDATE scenarios SET name = ?, description = ?, updated_at = ? "
            "WHERE id = ? AND investment_id = ?",
            (scenario.name, scenario.description, now, scenario_id, investment_id),
        )
        connection.execute("DELETE FROM scenario_overrides WHERE scenario_id = ?", (scenario_id,))
        _write_scenario_overrides(connection, scenario_id, scenario.overrides)
        _touch_investment(connection, investment_id, now=now)

    return get_scenario(investment_id, scenario_id, db_path=db_path)


def delete_scenario(
    investment_id: str, scenario_id: str, *, db_path: Path | None = None
) -> None:
    """Delete one Scenario with its overrides and cached variants.

    When that leaves the hidden wrapper holding no structure, the wrapper is
    removed too, in the same transaction, and the Deal is a plain standalone
    Deal again (P-11: empty advanced structure leaves no state behind). A
    visible Investment never collapses: its ownership of its Units is meaningful
    on its own (P7.6)."""

    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        _require_owned_scenario(connection, investment_id, scenario_id)
        _delete_scenario_rows(connection, investment_id, scenario_id)
        if owner.hidden and _wrapper_holds_no_structure(connection, investment_id):
            _delete_investment_rows(connection, investment_id)
        else:
            _touch_investment(connection, investment_id, now=_utc_now_iso())


def delete_investment(investment_id: str, *, db_path: Path | None = None) -> None:
    """Delete the Investment ``investment_id`` and everything it owns -- for a
    visible Investment (P7.6) also its details, Unit details, Business Plan and
    transaction costs -- and release its Deals, each exactly as it was (Q3).
    Never deletes a Deal row. One transaction."""

    with _connect(db_path) as connection:
        if _decode_hidden_flag(_investment_row(connection, investment_id)):
            _require_hidden_wrapper(connection, investment_id)
        _delete_investment_rows(connection, investment_id)


def get_investment(investment_id: str, *, db_path: Path | None = None) -> Investment:
    """Read one Investment and its membership. A hidden wrapper that does not
    hold exactly one saved Deal is refused as corrupt."""

    with _connect(db_path) as connection:
        row = _investment_row(connection, investment_id)
        hidden = _decode_hidden_flag(row)
        if hidden:
            _require_hidden_wrapper(connection, investment_id)
        return Investment(
            id=investment_id,
            hidden=hidden,
            units=tuple(
                InvestmentUnit(unit_id=unit["deal_id"])
                for unit in _unit_rows(connection, investment_id)
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


def list_scenarios(
    investment_id: str, *, db_path: Path | None = None
) -> list[InvestmentScenario]:
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        return _read_scenarios(connection, investment_id, owner=owner)


def get_scenario(
    investment_id: str, scenario_id: str, *, db_path: Path | None = None
) -> InvestmentScenario:
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        found = _read_scenarios(
            connection, investment_id, owner=owner, scenario_id=scenario_id
        )
    if not found:
        raise ScenarioNotFoundError(investment_id, scenario_id)
    return found[0]


def list_deal_scenarios(
    deal_id: str, *, db_path: Path | None = None
) -> tuple[str | None, list[InvestmentScenario]]:
    """The Investment ``deal_id`` belongs to and its Scenarios -- or
    ``(None, [])`` for a standalone Deal. Read-only: it never materializes an
    Investment."""

    with _connect(db_path) as connection:
        if _operating_mode_of(connection, deal_id) is None:
            raise DealNotFoundError(deal_id)
        investment_id = _investment_of_deal(connection, deal_id)
        if investment_id is None:
            return None, []
        unit_id, operating_mode = _require_hidden_wrapper(connection, investment_id)
        return investment_id, _read_scenarios(
            connection,
            investment_id,
            owner=_StructureOwner(
                investment_id=investment_id, hidden=True, unit_modes={unit_id: operating_mode}
            ),
        )


# -----------------------------------------------------------------------------
# The variant cache -- fingerprint-guarded, Quick and Detailed only
# -----------------------------------------------------------------------------


def get_variant_snapshot(
    investment_id: str,
    scenario_id: str,
    *,
    operating_mode: OperatingMode,
    expected_fingerprint: str,
    db_path: Path | None = None,
) -> AcquisitionResults | DetailedAcquisitionResults | None:
    """The cached result of the Base-strategy variant of ``scenario_id``, only
    if it is current.

    ``expected_fingerprint`` is the resolved-input fingerprint the caller has
    just recomputed from the Scenario and the unit's current inputs. Exactly as
    for every other snapshot (``_decode_snapshot``), a missing row, another
    schema version, a different fingerprint and an undecodable or malformed
    payload all read as ``None``: a cache miss, recomputed by the caller, never
    repaired and never an error.

    Lease-Level variants have no cache (Q14, D5 decision A), so asking for one
    is a caller error and is refused."""

    match operating_mode:
        case OperatingMode.QUICK:
            decoder: Any = _quick_analysis_snapshot_from_dict
        case OperatingMode.DETAILED:
            decoder = _detailed_analysis_snapshot_from_dict
        case OperatingMode.LEASE_LEVEL:
            raise UnsupportedOperatingModeError(operating_mode, operation="get_variant_snapshot")
        case _:
            raise UnsupportedOperatingModeError(operating_mode, operation="get_variant_snapshot")

    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM variant_snapshots "
            "WHERE root_id = ? AND strategy_id = ? AND scenario_id = ?",
            (investment_id, _BASE_STRATEGY_ID, scenario_id),
        ).fetchone()
    if row is None:
        return None
    return _decode_snapshot(
        raw_json=row["snapshot"],
        stored_schema_version=row["schema_version"],
        current_schema_version=_VARIANT_SNAPSHOT_SCHEMA_VERSION,
        stored_fingerprint=row["source_fingerprint"],
        expected_fingerprint=expected_fingerprint,
        decoder=decoder,
    )


def put_variant_snapshot(
    investment_id: str,
    scenario_id: str,
    results: AcquisitionResults | DetailedAcquisitionResults,
    *,
    source_fingerprint: str,
    db_path: Path | None = None,
) -> None:
    """Cache the result of the Base-strategy variant of ``scenario_id``.

    Written only by ``anchor.deals.variants``, which passes the result of the
    D6 entry point and the fingerprint of the very resolved inputs it ran --
    the pair is truthful by construction, and the read side re-proves it
    against the current inputs before serving anything. The Scenario must
    belong to the wrapper, and the result must be its unit's own mode's
    contract. A Lease-Level variant is refused (Q14, D5 decision A)."""

    if not isinstance(source_fingerprint, str) or not source_fingerprint:
        raise SnapshotValidationError("A variant snapshot needs a non-empty source fingerprint.")
    with _connect(db_path) as connection:
        _, operating_mode = _require_hidden_wrapper(connection, investment_id)
        _require_owned_scenario(connection, investment_id, scenario_id)
        match operating_mode:
            case OperatingMode.QUICK:
                expected_type: type = AcquisitionResults
            case OperatingMode.DETAILED:
                expected_type = DetailedAcquisitionResults
            case OperatingMode.LEASE_LEVEL:
                raise UnsupportedOperatingModeError(operating_mode, operation="put_variant_snapshot")
            case _:
                raise UnsupportedOperatingModeError(operating_mode, operation="put_variant_snapshot")
        if type(results) is not expected_type:
            raise SnapshotValidationError(
                f"A {operating_mode.value} variant caches {expected_type.__name__}, "
                f"not {type(results).__name__}."
            )
        connection.execute(
            """
            INSERT INTO variant_snapshots
                (root_id, strategy_id, scenario_id, snapshot, schema_version,
                 source_fingerprint, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (root_id, strategy_id, scenario_id) DO UPDATE SET
                snapshot = excluded.snapshot,
                schema_version = excluded.schema_version,
                source_fingerprint = excluded.source_fingerprint,
                generated_at = excluded.generated_at
            """,
            (
                investment_id,
                _BASE_STRATEGY_ID,
                scenario_id,
                _encode_snapshot(results),
                _VARIANT_SNAPSHOT_SCHEMA_VERSION,
                source_fingerprint,
                _utc_now_iso(),
            ),
        )


# =============================================================================
# Phase 7 Gate P7.4 -- persisted Strategies
#
# Every function below manages the Strategies of the **hidden one-unit
# Investment**, on the lifecycle rules the P7.2 Scenarios follow:
#
#   * **Opt-in only.** A standalone Deal's first Strategy materializes the hidden
#     wrapper through ``_materialize_hidden_investment``, inside the transaction
#     that writes that Strategy and after it has validated; a Deal whose
#     Scenarios already created the wrapper reuses it. No read below writes.
#   * **One authority for the contract.** Every Strategy is validated by the
#     P7.4 stage-1 validator for the wrapper's one unit, on the way in and again
#     on the way out, so a stored Strategy that no longer validates fails closed
#     (``PersistedStrategyDataError``) rather than being repaired.
#   * **Typed and whole.** Each overlay lives in its own domain's typed table,
#     and an update replaces the whole overlay set.
#   * **The wrapper collapses only when it holds nothing.** Deleting the last
#     Strategy removes the wrapper only when no Scenario remains, and deleting
#     the last Scenario removes it only when no Strategy remains
#     (``_wrapper_holds_no_structure``).
#   * **Fail closed outside the wrapper**, and **ownership is proven**, never
#     assumed, exactly as for Scenarios.
#
# Nothing here computes anything. Resolution, fingerprints and analysis live in
# ``anchor.analysis.strategy`` and ``anchor.deals.variants``.
# =============================================================================

_STRATEGY_DOMAIN_RANK = {domain: rank for rank, domain in enumerate(StrategyDomain)}


def _require_owned_strategy(
    connection: sqlite3.Connection, investment_id: str, strategy_id: str
) -> None:
    found = connection.execute(
        "SELECT 1 FROM strategies WHERE id = ? AND investment_id = ?",
        (strategy_id, investment_id),
    ).fetchone()
    if found is None:
        raise StrategyNotFoundError(investment_id, strategy_id)


def _strategy_contract_issues(
    strategy: StrategyDefinition, owner: _StructureOwner
) -> tuple[StrategyIssue, ...]:
    """The hidden wrapper's Strategies keep the exact P7.4 one-Unit contract; a
    visible Investment's are judged against its member set (P7.6)."""

    if owner.hidden:
        ((unit_id, operating_mode),) = owner.unit_modes.items()
        return validate_strategy(strategy, operating_mode=operating_mode, unit_id=unit_id)
    return validate_investment_strategy(strategy, unit_modes=owner.unit_modes)


def _require_valid_strategy(strategy: StrategyDefinition, *, owner: _StructureOwner) -> None:
    """The P7.4 stage-1 contract, for the owner's Units: identity, naming,
    unit addressing, one overlay per ``(domain, unit_id)``, whole-domain
    completeness, finite numbers, the D6 plan rules and the operating-outcome
    whitelist. This store adds no rule of its own."""

    issues = _strategy_contract_issues(strategy, owner)
    if issues:
        raise StrategyValidationError(issues)


def _write_strategy_business_plan(
    connection: sqlite3.Connection, strategy_id: str, unit_id: str, business_plan: BusinessPlan
) -> None:
    """One BUSINESS_PLAN overlay: its explicit marker, then every item in the
    analyst's order, in the D6 item tables' own shape. The marker is written
    even for the empty plan -- that is what an explicit empty replacement is."""

    connection.execute(
        "INSERT INTO strategy_business_plan_overlays (strategy_id, unit_id) VALUES (?, ?)",
        (strategy_id, unit_id),
    )
    connection.executemany(
        """
        INSERT INTO strategy_capital_plan_items
            (strategy_id, unit_id, item_id, ordinal, description, category, month, amount)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                strategy_id,
                unit_id,
                item.item_id,
                ordinal,
                item.description,
                _encode_enum(item.category),
                item.month,
                item.amount,
            )
            for ordinal, item in enumerate(business_plan.capital_items)
        ],
    )
    connection.executemany(
        """
        INSERT INTO strategy_owner_expense_items
            (strategy_id, unit_id, item_id, ordinal, description, category, annual_amount,
             first_year, last_year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                strategy_id,
                unit_id,
                item.item_id,
                ordinal,
                item.description,
                _encode_enum(item.category),
                item.annual_amount,
                item.first_year,
                item.last_year,
            )
            for ordinal, item in enumerate(business_plan.owner_expense_items)
        ],
    )


def _write_strategy_overlays(
    connection: sqlite3.Connection, strategy_id: str, overlays: Iterable[StrategyOverlay]
) -> None:
    """Every overlay of one Strategy, each into its own domain's table. Called
    inside the caller's transaction, after validation, and after any previous
    overlays were removed: an overlay set is replaced whole, never diffed.
    Rates and dollars are written as REAL and whole years as INTEGER, exactly
    as the resolver will read them."""

    for overlay in overlays:
        content = overlay.content
        match content:
            case AcquisitionChoice():
                connection.execute(
                    "INSERT INTO strategy_acquisition_overlays "
                    "(strategy_id, unit_id, purchase_price, acquisition_cost_pct) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        strategy_id,
                        overlay.unit_id,
                        float(content.purchase_price),
                        float(content.acquisition_cost_pct),
                    ),
                )
            case FinancingChoice():
                connection.execute(
                    "INSERT INTO strategy_financing_overlays "
                    "(strategy_id, unit_id, ltv, interest_rate, amortization, io_period, "
                    "financing_fee_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        strategy_id,
                        overlay.unit_id,
                        float(content.ltv),
                        float(content.interest_rate),
                        int(content.amortization),
                        int(content.io_period),
                        float(content.financing_fee_pct),
                    ),
                )
            case BusinessPlan():
                _write_strategy_business_plan(connection, strategy_id, overlay.unit_id, content)
            case OperatingOutcomeSet():
                connection.executemany(
                    "INSERT INTO strategy_operating_outcomes "
                    "(strategy_id, unit_id, target, operation, value) VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            strategy_id,
                            overlay.unit_id,
                            _encode_enum(outcome.target),
                            _encode_enum(outcome.operation),
                            float(outcome.value),
                        )
                        for outcome in content.outcomes
                    ],
                )
            case DispositionChoice():
                connection.execute(
                    "INSERT INTO strategy_disposition_overlays (strategy_id, unit_id, hold_period) "
                    "VALUES (?, ?, ?)",
                    (strategy_id, overlay.unit_id, int(content.hold_period)),
                )
            case _:
                raise TypeError(f"No table holds strategy content {type(content).__qualname__}.")


def _delete_strategy_overlay_rows(connection: sqlite3.Connection, strategy_id: str) -> None:
    """Every overlay row of one Strategy, from every domain's table."""

    for table in _STRATEGY_OVERLAY_TABLES:
        connection.execute(f"DELETE FROM {table} WHERE strategy_id = ?", (strategy_id,))


def _strategy_rows(
    connection: sqlite3.Connection, table: str, strategy_id: str, *, order: str = "unit_id"
) -> list[sqlite3.Row]:
    return connection.execute(
        f"SELECT * FROM {table} WHERE strategy_id = ? ORDER BY {order}", (strategy_id,)
    ).fetchall()


def _rows_by_unit(rows: Iterable[sqlite3.Row]) -> dict[str, list[sqlite3.Row]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["unit_id"], []).append(row)
    return grouped


def _stored_outcome_order(outcome: OperatingOutcome) -> tuple[int, str]:
    """Registry declaration order; an unrecognised target sorts after every
    real one, for the P7.4 validator to refuse by name."""

    target = outcome.target
    rank = _TARGET_RANK[target] if isinstance(target, ScenarioTarget) else len(_TARGET_RANK)
    return rank, str(target)


def _strategy_business_plan_from_rows(
    strategy_id: str, capital_rows: Iterable[sqlite3.Row], owner_expense_rows: Iterable[sqlite3.Row]
) -> BusinessPlan:
    """A BUSINESS_PLAN overlay's plan, through the one D6 row codec and its
    validation authority."""

    try:
        return _business_plan_from_rows(strategy_id, capital_rows, owner_expense_rows)
    except PersistedDealDataError as error:
        raise PersistedDealDataError(
            f"Strategy {strategy_id!r} holds a Business Plan overlay that cannot be "
            f"restored: {error}"
        ) from error


def _strategy_from_rows(
    connection: sqlite3.Connection,
    strategy_row: sqlite3.Row,
    *,
    owner: _StructureOwner,
) -> StrategyDefinition:
    """Rebuild one stored Strategy as the exact P7.4 contract, its overlays in
    canonical order (domain, then unit), and refuse it if the P7.4 validator
    does. Nothing is repaired, defaulted or dropped: a Business Plan item row
    with no overlay marker is corrupt, never an implied overlay."""

    strategy_id = strategy_row["id"]
    overlays: list[StrategyOverlay] = []
    for row in _strategy_rows(connection, "strategy_acquisition_overlays", strategy_id):
        overlays.append(
            StrategyOverlay(
                unit_id=row["unit_id"],
                domain=StrategyDomain.ACQUISITION,
                content=AcquisitionChoice(
                    purchase_price=row["purchase_price"],
                    acquisition_cost_pct=row["acquisition_cost_pct"],
                ),
            )
        )
    for row in _strategy_rows(connection, "strategy_financing_overlays", strategy_id):
        overlays.append(
            StrategyOverlay(
                unit_id=row["unit_id"],
                domain=StrategyDomain.FINANCING,
                content=FinancingChoice(
                    ltv=row["ltv"],
                    interest_rate=row["interest_rate"],
                    amortization=row["amortization"],
                    io_period=row["io_period"],
                    financing_fee_pct=row["financing_fee_pct"],
                ),
            )
        )

    plan_units = [
        row["unit_id"]
        for row in _strategy_rows(connection, "strategy_business_plan_overlays", strategy_id)
    ]
    capital_rows = _rows_by_unit(
        _strategy_rows(
            connection, "strategy_capital_plan_items", strategy_id, order="unit_id, ordinal"
        )
    )
    owner_expense_rows = _rows_by_unit(
        _strategy_rows(
            connection, "strategy_owner_expense_items", strategy_id, order="unit_id, ordinal"
        )
    )
    orphaned = sorted(set(capital_rows).union(owner_expense_rows).difference(plan_units))
    if orphaned:
        raise PersistedDealDataError(
            f"Strategy {strategy_id!r} holds Business Plan items for unit(s) "
            f"{', '.join(orphaned)} with no Business Plan overlay; an item row never "
            "implies an overlay."
        )
    for plan_unit in plan_units:
        overlays.append(
            StrategyOverlay(
                unit_id=plan_unit,
                domain=StrategyDomain.BUSINESS_PLAN,
                content=_strategy_business_plan_from_rows(
                    strategy_id,
                    capital_rows.get(plan_unit, ()),
                    owner_expense_rows.get(plan_unit, ()),
                ),
            )
        )

    outcome_rows = _rows_by_unit(
        _strategy_rows(
            connection, "strategy_operating_outcomes", strategy_id, order="unit_id, target"
        )
    )
    for outcome_unit, rows_of_unit in outcome_rows.items():
        outcomes = tuple(
            sorted(
                (
                    OperatingOutcome(
                        target=_stored_token(row["target"], ScenarioTarget),
                        operation=_stored_token(row["operation"], ScenarioOperation),
                        value=row["value"],
                    )
                    for row in rows_of_unit
                ),
                key=_stored_outcome_order,
            )
        )
        overlays.append(
            StrategyOverlay(
                unit_id=outcome_unit,
                domain=StrategyDomain.OPERATING_OUTCOME,
                content=OperatingOutcomeSet(outcomes=outcomes),
            )
        )
    for row in _strategy_rows(connection, "strategy_disposition_overlays", strategy_id):
        overlays.append(
            StrategyOverlay(
                unit_id=row["unit_id"],
                domain=StrategyDomain.DISPOSITION,
                content=DispositionChoice(hold_period=row["hold_period"]),
            )
        )

    strategy = StrategyDefinition(
        strategy_id=strategy_id,
        name=strategy_row["name"],
        description=strategy_row["description"],
        overlays=tuple(
            sorted(
                overlays,
                key=lambda overlay: (_STRATEGY_DOMAIN_RANK[overlay.domain], overlay.unit_id),
            )
        ),
    )
    issues = _strategy_contract_issues(strategy, owner)
    if issues:
        raise PersistedStrategyDataError(strategy_id, issues)
    return strategy


def _read_strategies(
    connection: sqlite3.Connection,
    investment_id: str,
    *,
    owner: _StructureOwner,
    strategy_id: str | None = None,
) -> list[InvestmentStrategy]:
    """The wrapper's Strategies -- or the one ``strategy_id`` it owns -- in
    creation order. That order is presentation only; the insertion ``rowid``
    breaks a timestamp tie, so it never depends on a random id."""

    if strategy_id is None:
        rows = connection.execute(
            "SELECT * FROM strategies WHERE investment_id = ? ORDER BY created_at, rowid",
            (investment_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM strategies WHERE investment_id = ? AND id = ?",
            (investment_id, strategy_id),
        ).fetchall()
    return [
        InvestmentStrategy(
            investment_id=investment_id,
            strategy=_strategy_from_rows(connection, row, owner=owner),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        for row in rows
    ]


def _insert_strategy(
    connection: sqlite3.Connection,
    investment_id: str,
    strategy: StrategyDefinition,
    *,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO strategies (id, investment_id, name, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (strategy.strategy_id, investment_id, strategy.name, strategy.description, now, now),
    )
    _write_strategy_overlays(connection, strategy.strategy_id, strategy.overlays)
    _touch_investment(connection, investment_id, now=now)


def _delete_strategy_rows(
    connection: sqlite3.Connection, investment_id: str, strategy_id: str
) -> None:
    """One Strategy and everything it owns: its cached variants, under every
    Scenario key, and its overlays."""

    connection.execute(
        "DELETE FROM variant_snapshots WHERE root_id = ? AND strategy_id = ?",
        (investment_id, strategy_id),
    )
    _delete_strategy_overlay_rows(connection, strategy_id)
    connection.execute(
        "DELETE FROM strategies WHERE id = ? AND investment_id = ?", (strategy_id, investment_id)
    )


def create_strategy_for_deal(
    deal_id: str,
    *,
    name: str,
    description: str | None = None,
    overlays: Iterable[StrategyOverlay] = (),
    db_path: Path | None = None,
) -> InvestmentStrategy:
    """Persist a new Strategy for the Deal ``deal_id``, materializing its hidden
    one-unit Investment first if it has none (Q4).

    One transaction: the Deal must exist; any Investment it already belongs to
    must be its hidden wrapper, which is reused -- whether its Scenarios or an
    earlier Strategy created it; the Strategy must pass the P7.4 contract for
    this unit; then the Investment and membership (first opt-in only), the
    Strategy and its overlays are written. Any failure leaves no row behind.

    Raises ``DealNotFoundError``, ``InvestmentStructureError``,
    ``StrategyValidationError`` or ``PersistedDealDataError``."""

    strategy = StrategyDefinition(
        strategy_id=uuid.uuid4().hex,
        name=name,
        description=description,
        overlays=tuple(overlays),
    )
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        operating_mode = _operating_mode_of(connection, deal_id)
        if operating_mode is None:
            raise DealNotFoundError(deal_id)
        investment_id = _investment_of_deal(connection, deal_id)
        if investment_id is not None:
            _require_hidden_wrapper(connection, investment_id)
        _require_valid_strategy(
            strategy,
            owner=_StructureOwner(
                investment_id=investment_id or "", hidden=True, unit_modes={deal_id: operating_mode}
            ),
        )
        if investment_id is None:
            investment_id = _materialize_hidden_investment(connection, deal_id, now=now)
        _insert_strategy(connection, investment_id, strategy, now=now)

    return get_strategy(investment_id, strategy.strategy_id, db_path=db_path)


def create_strategy(
    investment_id: str,
    *,
    name: str,
    description: str | None = None,
    overlays: Iterable[StrategyOverlay] = (),
    db_path: Path | None = None,
) -> InvestmentStrategy:
    """Persist another Strategy in the existing Investment ``investment_id``:
    the hidden wrapper, validated for its one unit, or (P7.6) a visible
    Investment, validated for its member Units."""

    strategy = StrategyDefinition(
        strategy_id=uuid.uuid4().hex,
        name=name,
        description=description,
        overlays=tuple(overlays),
    )
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        _require_valid_strategy(strategy, owner=owner)
        _insert_strategy(connection, investment_id, strategy, now=now)

    return get_strategy(investment_id, strategy.strategy_id, db_path=db_path)


def update_strategy(
    investment_id: str,
    strategy_id: str,
    *,
    name: str,
    description: str | None = None,
    overlays: Iterable[StrategyOverlay] = (),
    db_path: Path | None = None,
) -> InvestmentStrategy:
    """Replace one Strategy's name, description and whole overlay set, keeping
    its id.

    Validated before anything is written; the old overlays are removed and the
    new ones written in the same transaction, so a failure leaves the previous
    Strategy exactly as it was. Cached variants are left alone: each is served
    only while its source fingerprint still matches the resolved inputs, so a
    rename, or a recipe that resolves to the same inputs, keeps its cache and
    any other change makes the old row stale."""

    strategy = StrategyDefinition(
        strategy_id=strategy_id,
        name=name,
        description=description,
        overlays=tuple(overlays),
    )
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        _require_owned_strategy(connection, investment_id, strategy_id)
        _require_valid_strategy(strategy, owner=owner)
        connection.execute(
            "UPDATE strategies SET name = ?, description = ?, updated_at = ? "
            "WHERE id = ? AND investment_id = ?",
            (strategy.name, strategy.description, now, strategy_id, investment_id),
        )
        _delete_strategy_overlay_rows(connection, strategy_id)
        _write_strategy_overlays(connection, strategy_id, strategy.overlays)
        _touch_investment(connection, investment_id, now=now)

    return get_strategy(investment_id, strategy_id, db_path=db_path)


def delete_strategy(
    investment_id: str, strategy_id: str, *, db_path: Path | None = None
) -> None:
    """Delete one Strategy with its overlays and cached variants.

    When that leaves the hidden wrapper holding no structure -- no Strategy and
    no Scenario -- the wrapper is removed too, in the same transaction, and the
    Deal is a plain standalone Deal again (P-11). A wrapper that still holds a
    Scenario is kept, and a visible Investment never collapses (P7.6)."""

    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        _require_owned_strategy(connection, investment_id, strategy_id)
        _delete_strategy_rows(connection, investment_id, strategy_id)
        if owner.hidden and _wrapper_holds_no_structure(connection, investment_id):
            _delete_investment_rows(connection, investment_id)
        else:
            _touch_investment(connection, investment_id, now=_utc_now_iso())


def list_strategies(
    investment_id: str, *, db_path: Path | None = None
) -> list[InvestmentStrategy]:
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        return _read_strategies(connection, investment_id, owner=owner)


def get_strategy(
    investment_id: str, strategy_id: str, *, db_path: Path | None = None
) -> InvestmentStrategy:
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        found = _read_strategies(
            connection, investment_id, owner=owner, strategy_id=strategy_id
        )
    if not found:
        raise StrategyNotFoundError(investment_id, strategy_id)
    return found[0]


def list_deal_strategies(
    deal_id: str, *, db_path: Path | None = None
) -> tuple[str | None, list[InvestmentStrategy]]:
    """The Investment ``deal_id`` belongs to and its Strategies -- or
    ``(None, [])`` for a standalone Deal. Read-only: it never materializes an
    Investment."""

    with _connect(db_path) as connection:
        if _operating_mode_of(connection, deal_id) is None:
            raise DealNotFoundError(deal_id)
        investment_id = _investment_of_deal(connection, deal_id)
        if investment_id is None:
            return None, []
        unit_id, operating_mode = _require_hidden_wrapper(connection, investment_id)
        return investment_id, _read_strategies(
            connection,
            investment_id,
            owner=_StructureOwner(
                investment_id=investment_id, hidden=True, unit_modes={unit_id: operating_mode}
            ),
        )


# -----------------------------------------------------------------------------
# The variant cache for Strategy variants -- the same table, the same rules
# -----------------------------------------------------------------------------


def _require_variant_scenario(
    connection: sqlite3.Connection, investment_id: str, scenario_id: str
) -> None:
    """A variant's Scenario key: the reserved implicit Base, or a Scenario this
    Investment owns."""

    if scenario_id != BASE_SCENARIO_ID:
        _require_owned_scenario(connection, investment_id, scenario_id)


def get_strategy_variant_snapshot(
    investment_id: str,
    strategy_id: str,
    scenario_id: str,
    *,
    operating_mode: OperatingMode,
    expected_fingerprint: str,
    db_path: Path | None = None,
) -> AcquisitionResults | DetailedAcquisitionResults | None:
    """The cached result of the variant ``(strategy_id, scenario_id)``, only if
    it is current -- exactly the ``get_variant_snapshot`` rules under the full
    variant identity. A missing row, another schema version, a different
    fingerprint and an undecodable payload all read as ``None``, a miss.
    Lease-Level variants have no cache, so asking for one is refused."""

    match operating_mode:
        case OperatingMode.QUICK:
            decoder: Any = _quick_analysis_snapshot_from_dict
        case OperatingMode.DETAILED:
            decoder = _detailed_analysis_snapshot_from_dict
        case OperatingMode.LEASE_LEVEL:
            raise UnsupportedOperatingModeError(
                operating_mode, operation="get_strategy_variant_snapshot"
            )
        case _:
            raise UnsupportedOperatingModeError(
                operating_mode, operation="get_strategy_variant_snapshot"
            )

    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM variant_snapshots "
            "WHERE root_id = ? AND strategy_id = ? AND scenario_id = ?",
            (investment_id, strategy_id, scenario_id),
        ).fetchone()
    if row is None:
        return None
    return _decode_snapshot(
        raw_json=row["snapshot"],
        stored_schema_version=row["schema_version"],
        current_schema_version=_VARIANT_SNAPSHOT_SCHEMA_VERSION,
        stored_fingerprint=row["source_fingerprint"],
        expected_fingerprint=expected_fingerprint,
        decoder=decoder,
    )


def put_strategy_variant_snapshot(
    investment_id: str,
    strategy_id: str,
    scenario_id: str,
    results: AcquisitionResults | DetailedAcquisitionResults,
    *,
    source_fingerprint: str,
    db_path: Path | None = None,
) -> None:
    """Cache the result of the variant ``(strategy_id, scenario_id)``.

    Written only by ``anchor.deals.variants``, with the result of the D6 entry
    point and the fingerprint of the very resolved inputs it ran. The Strategy
    must be one this wrapper owns -- never the Base key, so Base x Base can
    never be written here -- and the Scenario key must be the Base key or a
    Scenario this wrapper owns. A Lease-Level variant is refused."""

    if not isinstance(source_fingerprint, str) or not source_fingerprint:
        raise SnapshotValidationError("A variant snapshot needs a non-empty source fingerprint.")
    with _connect(db_path) as connection:
        _, operating_mode = _require_hidden_wrapper(connection, investment_id)
        _require_owned_strategy(connection, investment_id, strategy_id)
        _require_variant_scenario(connection, investment_id, scenario_id)
        match operating_mode:
            case OperatingMode.QUICK:
                expected_type: type = AcquisitionResults
            case OperatingMode.DETAILED:
                expected_type = DetailedAcquisitionResults
            case OperatingMode.LEASE_LEVEL:
                raise UnsupportedOperatingModeError(
                    operating_mode, operation="put_strategy_variant_snapshot"
                )
            case _:
                raise UnsupportedOperatingModeError(
                    operating_mode, operation="put_strategy_variant_snapshot"
                )
        if type(results) is not expected_type:
            raise SnapshotValidationError(
                f"A {operating_mode.value} variant caches {expected_type.__name__}, "
                f"not {type(results).__name__}."
            )
        connection.execute(
            """
            INSERT INTO variant_snapshots
                (root_id, strategy_id, scenario_id, snapshot, schema_version,
                 source_fingerprint, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (root_id, strategy_id, scenario_id) DO UPDATE SET
                snapshot = excluded.snapshot,
                schema_version = excluded.schema_version,
                source_fingerprint = excluded.source_fingerprint,
                generated_at = excluded.generated_at
            """,
            (
                investment_id,
                strategy_id,
                scenario_id,
                _encode_snapshot(results),
                _VARIANT_SNAPSHOT_SCHEMA_VERSION,
                source_fingerprint,
                _utc_now_iso(),
            ),
        )


# =============================================================================
# Phase 7 Gate P7.6 -- the visible Investment
#
# Every function below manages a **visible** Investment: one negotiated
# transaction over one or more Units, each an existing Deal, unchanged.
#
#   * **One transaction per request.** Creating, promoting, updating, adding or
#     removing a Unit and deleting each validate everything first -- the
#     Investment's own inputs, each Deal's existence and standalone state, and
#     the Base variant's common timeline and price allocation -- and then write,
#     inside one ``_connect`` transaction. Any failure rolls the whole request
#     back: no parent without memberships, no membership without its details, no
#     partial plan.
#   * **Exclusive membership (Q3).** A Deal is a Unit of at most one Investment;
#     the ``UNIQUE`` columns enforce it as well as this code.
#   * **Promotion reuses the hidden wrapper.** Its Strategies, Scenarios and
#     their ids stay exactly as they are; no second parent is created and
#     nothing is copied.
#   * **Nothing is auto-changed.** No transaction price, Unit price, hold or
#     analysis start date is altered to make a request reconcile, and no Unit is
#     dropped from a Strategy or Scenario.
#   * **The result cache is never authority (Q14).** A membership change or a
#     promotion deletes the Investment's variant cache rows; a visible
#     Investment's variants are recomputed and never cached.
#
# Nothing here computes anything. Resolution and consolidation live in
# ``anchor.deals.investment_variants`` and ``anchor.consolidation``.
# =============================================================================


def _visible_details_row(connection: sqlite3.Connection, investment_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM investment_details WHERE investment_id = ?", (investment_id,)
    ).fetchone()


def _require_visible_units(
    connection: sqlite3.Connection, investment_id: str
) -> dict[str, OperatingMode]:
    """The member Units of the visible Investment ``investment_id``, each with
    its Deal's operating mode, in ``unit_id`` order -- or
    ``PersistedDealDataError`` when its sidecars are incoherent: no details
    record, no Unit, a membership and Unit details that disagree, or a member
    that is no saved Deal. Nothing is repaired."""

    if _visible_details_row(connection, investment_id) is None:
        raise PersistedDealDataError(
            f"Visible investment {investment_id!r} has no details record; a visible "
            "Investment always has a name and a transaction price."
        )
    member_ids = [row["deal_id"] for row in _unit_rows(connection, investment_id)]
    if not member_ids:
        raise PersistedDealDataError(f"Visible investment {investment_id!r} has no units.")
    detail_ids = {
        row["unit_id"]
        for row in connection.execute(
            "SELECT unit_id FROM investment_unit_details WHERE investment_id = ?",
            (investment_id,),
        )
    }
    if detail_ids != set(member_ids):
        raise PersistedDealDataError(
            f"Visible investment {investment_id!r} holds unit details that do not match its "
            "membership."
        )
    unit_modes: dict[str, OperatingMode] = {}
    for unit_id in member_ids:
        operating_mode = _operating_mode_of(connection, unit_id)
        if operating_mode is None:
            raise PersistedDealDataError(
                f"Visible investment {investment_id!r} names unit {unit_id!r}, which is not a "
                "saved deal."
            )
        unit_modes[unit_id] = operating_mode
    return unit_modes


def _membership_from_row(row: sqlite3.Row) -> InvestmentUnitMembership:
    return InvestmentUnitMembership(
        unit_id=row["unit_id"],
        ordinal=row["ordinal"],
        label=row["label"],
        unit_kind=_decode_enum(  # type: ignore[arg-type]
            row["unit_kind"], UnitKind, path=f"unit {row['unit_id']!r} unit_kind"
        ),
        acquisition_month=row["acquisition_month"],
        disposition_month=row["disposition_month"],
    )


def _transaction_cost_from_row(row: sqlite3.Row) -> InvestmentTransactionCost:
    return InvestmentTransactionCost(
        cost_id=row["cost_id"],
        description=row["description"],
        category=_decode_enum(  # type: ignore[arg-type]
            row["category"],
            TransactionCostCategory,
            path=f"transaction cost {row['cost_id']!r} category",
        ),
        amount=row["amount"],
        model_month=row["model_month"],
    )


def _read_investment_business_plan(connection: sqlite3.Connection, investment_id: str) -> BusinessPlan:
    """The Investment-level plan, through the one D6 row codec and its
    validation authority."""

    capital_rows = connection.execute(
        "SELECT * FROM investment_capital_plan_items WHERE investment_id = ? ORDER BY ordinal",
        (investment_id,),
    ).fetchall()
    owner_expense_rows = connection.execute(
        "SELECT * FROM investment_owner_expense_items WHERE investment_id = ? ORDER BY ordinal",
        (investment_id,),
    ).fetchall()
    try:
        return _business_plan_from_rows(investment_id, capital_rows, owner_expense_rows)
    except PersistedDealDataError as error:
        raise PersistedDealDataError(
            f"Investment {investment_id!r} holds a Business Plan that cannot be restored: {error}"
        ) from error


def _read_visible_investment(connection: sqlite3.Connection, investment_id: str) -> VisibleInvestment:
    """The visible Investment as stored, re-validated on the way out: a record
    that no longer validates fails closed rather than being repaired. A hidden
    wrapper is refused -- it has no visible state, and none is created by
    reading it."""

    row = _investment_row(connection, investment_id)
    if _decode_hidden_flag(row):
        raise InvestmentStructureError(
            f"Investment {investment_id!r} is a hidden one-unit wrapper, not a visible "
            "Investment; it has no visible details. Promote it to make it visible."
        )
    _require_visible_units(connection, investment_id)
    details = _visible_details_row(connection, investment_id)
    assert details is not None
    units = tuple(
        _membership_from_row(unit_row)
        for unit_row in connection.execute(
            "SELECT * FROM investment_unit_details WHERE investment_id = ? ORDER BY ordinal, unit_id",
            (investment_id,),
        ).fetchall()
    )
    business_plan = _read_investment_business_plan(connection, investment_id)
    costs = tuple(
        _transaction_cost_from_row(cost_row)
        for cost_row in connection.execute(
            "SELECT * FROM investment_transaction_costs WHERE investment_id = ? ORDER BY ordinal",
            (investment_id,),
        ).fetchall()
    )
    issues = validate_investment_inputs(
        name=details["name"],
        transaction_price=details["transaction_price"],
        memberships=units,
        business_plan=business_plan,
        transaction_costs=costs,
    )
    if issues:
        raise PersistedDealDataError(
            f"Visible investment {investment_id!r} does not validate: "
            + "; ".join(issue.message for issue in issues)
        )
    return VisibleInvestment(
        id=investment_id,
        name=details["name"],
        transaction_price=details["transaction_price"],
        units=units,
        business_plan=business_plan,
        transaction_costs=costs,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _write_visible_details(
    connection: sqlite3.Connection, investment_id: str, *, name: str, transaction_price: float
) -> None:
    connection.execute(
        """
        INSERT INTO investment_details (investment_id, name, transaction_price) VALUES (?, ?, ?)
        ON CONFLICT (investment_id) DO UPDATE SET
            name = excluded.name, transaction_price = excluded.transaction_price
        """,
        (investment_id, name, float(transaction_price)),
    )


def _write_membership(
    connection: sqlite3.Connection, investment_id: str, membership: InvestmentUnitMembership
) -> None:
    """One Unit's membership and its Unit details, together."""

    connection.execute(
        "INSERT INTO investment_units (investment_id, deal_id) VALUES (?, ?)",
        (investment_id, membership.unit_id),
    )
    connection.execute(
        """
        INSERT INTO investment_unit_details
            (investment_id, unit_id, ordinal, label, unit_kind, acquisition_month,
             disposition_month)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            investment_id,
            membership.unit_id,
            membership.ordinal,
            membership.label,
            _encode_enum(membership.unit_kind),
            membership.acquisition_month,
            membership.disposition_month,
        ),
    )


def _replace_investment_business_plan(
    connection: sqlite3.Connection, investment_id: str, business_plan: BusinessPlan
) -> None:
    """The Investment-level plan, replaced whole, in the D6 item tables' own
    shape and the analyst's order."""

    for table in ("investment_capital_plan_items", "investment_owner_expense_items"):
        connection.execute(f"DELETE FROM {table} WHERE investment_id = ?", (investment_id,))
    connection.executemany(
        """
        INSERT INTO investment_capital_plan_items
            (investment_id, item_id, ordinal, description, category, month, amount)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                investment_id,
                item.item_id,
                ordinal,
                item.description,
                _encode_enum(item.category),
                item.month,
                item.amount,
            )
            for ordinal, item in enumerate(business_plan.capital_items)
        ],
    )
    connection.executemany(
        """
        INSERT INTO investment_owner_expense_items
            (investment_id, item_id, ordinal, description, category, annual_amount,
             first_year, last_year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                investment_id,
                item.item_id,
                ordinal,
                item.description,
                _encode_enum(item.category),
                item.annual_amount,
                item.first_year,
                item.last_year,
            )
            for ordinal, item in enumerate(business_plan.owner_expense_items)
        ],
    )


def _replace_transaction_costs(
    connection: sqlite3.Connection,
    investment_id: str,
    costs: Iterable[InvestmentTransactionCost],
) -> None:
    """The transaction costs, replaced whole, in the analyst's order."""

    connection.execute(
        "DELETE FROM investment_transaction_costs WHERE investment_id = ?", (investment_id,)
    )
    connection.executemany(
        """
        INSERT INTO investment_transaction_costs
            (investment_id, cost_id, ordinal, description, category, amount, model_month)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                investment_id,
                cost.cost_id,
                ordinal,
                cost.description,
                _encode_enum(cost.category),
                float(cost.amount),
                cost.model_month,
            )
            for ordinal, cost in enumerate(costs)
        ],
    )


def _require_standalone_deal(connection: sqlite3.Connection, deal_id: str) -> None:
    """``deal_id`` names a saved Deal that belongs to no Investment. A Deal that
    already has one is refused without disclosing that Investment's
    structure."""

    if _operating_mode_of(connection, deal_id) is None:
        raise DealNotFoundError(deal_id)
    investment_id = _investment_of_deal(connection, deal_id)
    if investment_id is None:
        return
    if _decode_hidden_flag(_investment_row(connection, investment_id)):
        raise InvestmentStructureError(
            f"Deal {deal_id!r} already has its own Strategies or Scenarios in a hidden "
            "Investment. Promote that Investment to make it visible; a Deal is never a Unit "
            "of two Investments."
        )
    raise InvestmentStructureError(
        f"Deal {deal_id!r} is already a Unit of another Investment. A Deal belongs to at "
        "most one Investment."
    )


def _unit_economic_facts(deal: Deal) -> UnitEconomicFacts:
    """The Base facts of one Unit the Investment-level rules read, off the
    Deal's own stored contracts."""

    match deal.operating_mode:
        case OperatingMode.QUICK:
            assert deal.inputs is not None
            return UnitEconomicFacts(
                unit_id=deal.id,
                operating_mode=deal.operating_mode,
                purchase_price=deal.inputs.purchase_price,
                hold_period=deal.inputs.hold_period,
                analysis_start_date=None,
            )
        case OperatingMode.DETAILED:
            assert deal.terms is not None
            return UnitEconomicFacts(
                unit_id=deal.id,
                operating_mode=deal.operating_mode,
                purchase_price=deal.terms.purchase_price,
                hold_period=deal.terms.hold_period,
                analysis_start_date=None,
            )
        case OperatingMode.LEASE_LEVEL:
            assert deal.terms is not None
            assert deal.property_inputs is not None
            return UnitEconomicFacts(
                unit_id=deal.id,
                operating_mode=deal.operating_mode,
                purchase_price=deal.terms.purchase_price,
                hold_period=deal.terms.hold_period,
                analysis_start_date=deal.property_inputs.analysis_start_date,
            )
        case _:
            raise UnsupportedOperatingModeError(deal.operating_mode, operation="_unit_economic_facts")


def _require_valid_investment_inputs(
    *,
    name: object,
    transaction_price: object,
    memberships: tuple[InvestmentUnitMembership, ...],
    business_plan: BusinessPlan,
    transaction_costs: tuple[InvestmentTransactionCost, ...],
) -> None:
    issues = validate_investment_inputs(
        name=name,
        transaction_price=transaction_price,
        memberships=memberships,
        business_plan=business_plan,
        transaction_costs=transaction_costs,
    )
    if issues:
        raise InvestmentValidationError(issues)


def _require_reconciled_base(
    connection: sqlite3.Connection,
    memberships: tuple[InvestmentUnitMembership, ...],
    transaction_price: float,
) -> None:
    """The Base variant's common timeline and price allocation, over the Units'
    stored Deals, read in this transaction. Nothing is adjusted to pass."""

    facts = [
        _unit_economic_facts(_read_deal(connection, membership.unit_id))
        for membership in sorted(memberships, key=lambda membership: membership.unit_id)
    ]
    issues = validate_variant_economics(facts, transaction_price=transaction_price)
    if issues:
        raise InvestmentValidationError(issues)


def _structure_references(
    connection: sqlite3.Connection, investment_id: str, unit_id: str
) -> list[str]:
    """Every persisted Scenario override and Strategy overlay of this
    Investment that addresses ``unit_id``, named deterministically."""

    scenarios = connection.execute(
        """
        SELECT DISTINCT s.id, s.name FROM scenarios s
        JOIN scenario_overrides o ON o.scenario_id = s.id
        WHERE s.investment_id = ? AND o.unit_id = ?
        ORDER BY s.id
        """,
        (investment_id, unit_id),
    ).fetchall()
    strategies: dict[str, str] = {}
    for table in _STRATEGY_OVERLAY_TABLES:
        for row in connection.execute(
            f"""
            SELECT DISTINCT st.id, st.name FROM strategies st
            JOIN {table} t ON t.strategy_id = st.id
            WHERE st.investment_id = ? AND t.unit_id = ?
            """,
            (investment_id, unit_id),
        ):
            strategies[row["id"]] = row["name"]
    return [
        *(f"Scenario {row['name']!r} ({row['id']})" for row in scenarios),
        *(f"Strategy {strategies[key]!r} ({key})" for key in sorted(strategies)),
    ]


def get_visible_investment(investment_id: str, *, db_path: Path | None = None) -> VisibleInvestment:
    """Read one visible Investment. Read-only: a hidden wrapper is refused and
    gains nothing."""

    with _connect(db_path) as connection:
        return _read_visible_investment(connection, investment_id)


def list_visible_investments(*, db_path: Path | None = None) -> list[VisibleInvestment]:
    """Every visible Investment, most recently updated first. Hidden wrappers are
    never listed: they stay the P7.2-P7.5 per-Deal state."""

    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id FROM investments WHERE is_hidden = 0 ORDER BY updated_at DESC, rowid DESC"
        ).fetchall()
        return [_read_visible_investment(connection, row["id"]) for row in rows]


def create_visible_investment(
    *,
    name: str,
    transaction_price: float,
    units: Iterable[InvestmentUnitMembership],
    business_plan: BusinessPlan,
    transaction_costs: Iterable[InvestmentTransactionCost] = (),
    db_path: Path | None = None,
) -> VisibleInvestment:
    """Create a visible Investment over one or more standalone Deals.

    One transaction: the Investment's inputs validate; every Deal exists and
    belongs to no Investment; the Base variant's timeline and allocation hold;
    then the parent, the memberships and Unit details, the details, the plan
    and the costs are written. Any failure leaves no row behind.

    Raises ``InvestmentValidationError``, ``DealNotFoundError`` or
    ``InvestmentStructureError``."""

    memberships = tuple(units)
    costs = tuple(transaction_costs)
    investment_id = uuid.uuid4().hex
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        _require_valid_investment_inputs(
            name=name,
            transaction_price=transaction_price,
            memberships=memberships,
            business_plan=business_plan,
            transaction_costs=costs,
        )
        for membership in sorted(memberships, key=lambda membership: membership.unit_id):
            _require_standalone_deal(connection, membership.unit_id)
        _require_reconciled_base(connection, memberships, transaction_price)
        connection.execute(
            "INSERT INTO investments (id, is_hidden, created_at, updated_at) VALUES (?, 0, ?, ?)",
            (investment_id, now, now),
        )
        for membership in memberships:
            _write_membership(connection, investment_id, membership)
        _write_visible_details(connection, investment_id, name=name, transaction_price=transaction_price)
        _replace_investment_business_plan(connection, investment_id, business_plan)
        _replace_transaction_costs(connection, investment_id, costs)

    return get_visible_investment(investment_id, db_path=db_path)


def promote_hidden_investment(
    investment_id: str,
    *,
    name: str,
    transaction_price: float,
    units: Iterable[InvestmentUnitMembership],
    business_plan: BusinessPlan,
    transaction_costs: Iterable[InvestmentTransactionCost] = (),
    db_path: Path | None = None,
) -> VisibleInvestment:
    """Make the hidden wrapper ``investment_id`` a visible Investment -- the
    same Investment, never a second parent.

    ``units`` lists every Unit of the result: the wrapper's own Unit (which it
    must retain) and any standalone Deals added with it. One transaction: its
    Strategies, Scenarios and their ids are kept exactly; the memberships of the
    added Units, every Unit's details, the details, the plan and the costs are
    written; ``is_hidden`` is set to 0; and its variant cache rows are deleted,
    because its variants now consolidate. Any failure leaves the wrapper exactly
    as it was."""

    memberships = tuple(units)
    costs = tuple(transaction_costs)
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        existing_unit, _ = _require_hidden_wrapper(connection, investment_id)
        _require_valid_investment_inputs(
            name=name,
            transaction_price=transaction_price,
            memberships=memberships,
            business_plan=business_plan,
            transaction_costs=costs,
        )
        if existing_unit not in {membership.unit_id for membership in memberships}:
            raise InvestmentValidationError(
                [
                    InvestmentIssue(
                        code=InvestmentIssueCode.UNIT_NOT_RETAINED,
                        message=(
                            f"The Investment's own Unit {existing_unit!r} must be listed: its "
                            "Strategies and Scenarios address it, and promoting never drops a "
                            "Unit."
                        ),
                        unit_id=existing_unit,
                        field="units",
                    )
                ]
            )
        added = [m for m in memberships if m.unit_id != existing_unit]
        for membership in sorted(added, key=lambda membership: membership.unit_id):
            _require_standalone_deal(connection, membership.unit_id)
        _require_reconciled_base(connection, memberships, transaction_price)
        connection.execute(
            "UPDATE investments SET is_hidden = 0, updated_at = ? WHERE id = ?",
            (now, investment_id),
        )
        for membership in memberships:
            if membership.unit_id == existing_unit:
                connection.execute(
                    """
                    INSERT INTO investment_unit_details
                        (investment_id, unit_id, ordinal, label, unit_kind, acquisition_month,
                         disposition_month)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        investment_id,
                        membership.unit_id,
                        membership.ordinal,
                        membership.label,
                        _encode_enum(membership.unit_kind),
                        membership.acquisition_month,
                        membership.disposition_month,
                    ),
                )
            else:
                _write_membership(connection, investment_id, membership)
        _write_visible_details(connection, investment_id, name=name, transaction_price=transaction_price)
        _replace_investment_business_plan(connection, investment_id, business_plan)
        _replace_transaction_costs(connection, investment_id, costs)
        connection.execute("DELETE FROM variant_snapshots WHERE root_id = ?", (investment_id,))

    return get_visible_investment(investment_id, db_path=db_path)


def update_visible_investment(
    investment_id: str,
    *,
    name: str,
    transaction_price: float,
    business_plan: BusinessPlan,
    transaction_costs: Iterable[InvestmentTransactionCost],
    db_path: Path | None = None,
) -> VisibleInvestment:
    """Replace the visible Investment's name, transaction price, Business Plan
    and transaction costs as one request. Validated first -- the Base variant
    must reconcile to the new price -- and written in one transaction; a failure
    leaves the Investment exactly as it was. Its Units and Deals are
    untouched."""

    costs = tuple(transaction_costs)
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        current = _read_visible_investment(connection, investment_id)
        _require_valid_investment_inputs(
            name=name,
            transaction_price=transaction_price,
            memberships=current.units,
            business_plan=business_plan,
            transaction_costs=costs,
        )
        _require_reconciled_base(connection, current.units, transaction_price)
        _write_visible_details(connection, investment_id, name=name, transaction_price=transaction_price)
        _replace_investment_business_plan(connection, investment_id, business_plan)
        _replace_transaction_costs(connection, investment_id, costs)
        _touch_investment(connection, investment_id, now=now)

    return get_visible_investment(investment_id, db_path=db_path)


def add_investment_unit(
    investment_id: str,
    unit: InvestmentUnitMembership,
    *,
    transaction_price: float | None = None,
    db_path: Path | None = None,
) -> VisibleInvestment:
    """Add the standalone Deal ``unit.unit_id`` to the visible Investment, last
    in presentation order.

    ``transaction_price`` optionally restates the Investment's price in the same
    request -- the analyst's figure, never a derived one. The resulting Base
    variant must reconcile and share one timeline; no price, hold or date is
    changed to make it. One transaction; the Investment's variant cache rows are
    deleted."""

    now = _utc_now_iso()
    with _connect(db_path) as connection:
        current = _read_visible_investment(connection, investment_id)
        price = current.transaction_price if transaction_price is None else transaction_price
        membership = dataclasses.replace(
            unit, ordinal=max(existing.ordinal for existing in current.units) + 1
        )
        memberships = (*current.units, membership)
        _require_valid_investment_inputs(
            name=current.name,
            transaction_price=price,
            memberships=memberships,
            business_plan=current.business_plan,
            transaction_costs=current.transaction_costs,
        )
        _require_standalone_deal(connection, membership.unit_id)
        _require_reconciled_base(connection, memberships, price)
        _write_membership(connection, investment_id, membership)
        if transaction_price is not None:
            _write_visible_details(
                connection, investment_id, name=current.name, transaction_price=transaction_price
            )
        connection.execute("DELETE FROM variant_snapshots WHERE root_id = ?", (investment_id,))
        _touch_investment(connection, investment_id, now=now)

    return get_visible_investment(investment_id, db_path=db_path)


def update_investment_unit(
    investment_id: str,
    unit_id: str,
    *,
    label: str | None,
    unit_kind: UnitKind,
    ordinal: int,
    db_path: Path | None = None,
) -> VisibleInvestment:
    """Change one Unit's display metadata -- label, kind and presentation order.
    None of them is economic, so no variant, fingerprint or cache is touched."""

    now = _utc_now_iso()
    with _connect(db_path) as connection:
        current = _read_visible_investment(connection, investment_id)
        if unit_id not in {membership.unit_id for membership in current.units}:
            raise InvestmentUnitNotFoundError(investment_id, unit_id)
        memberships = tuple(
            dataclasses.replace(membership, label=label, unit_kind=unit_kind, ordinal=ordinal)
            if membership.unit_id == unit_id
            else membership
            for membership in current.units
        )
        issues = validate_unit_memberships(memberships)
        if issues:
            raise InvestmentValidationError(issues)
        connection.execute(
            "UPDATE investment_unit_details SET ordinal = ?, label = ?, unit_kind = ? "
            "WHERE investment_id = ? AND unit_id = ?",
            (ordinal, label, _encode_enum(unit_kind), investment_id, unit_id),
        )
        _touch_investment(connection, investment_id, now=now)

    return get_visible_investment(investment_id, db_path=db_path)


def remove_investment_unit(
    investment_id: str, unit_id: str, *, db_path: Path | None = None
) -> VisibleInvestment:
    """Remove the Unit ``unit_id`` from the visible Investment, releasing its
    Deal -- which is neither deleted nor changed -- to standalone.

    Refused while a persisted Scenario override or Strategy overlay addresses
    the Unit (those are never silently edited), and for the Investment's last
    Unit (delete the Investment to release every Unit). The Investment stays
    visible, even with one Unit. One transaction; its variant cache rows are
    deleted."""

    now = _utc_now_iso()
    with _connect(db_path) as connection:
        current = _read_visible_investment(connection, investment_id)
        if unit_id not in {membership.unit_id for membership in current.units}:
            raise InvestmentUnitNotFoundError(investment_id, unit_id)
        if len(current.units) == 1:
            raise InvestmentStructureError(
                f"Unit {unit_id!r} is the Investment's last Unit. Delete the Investment to "
                "release it; a visible Investment always holds at least one Unit."
            )
        references = _structure_references(connection, investment_id, unit_id)
        if references:
            raise InvestmentStructureError(
                f"Unit {unit_id!r} is still addressed by {', '.join(references)}. Remove those "
                "overrides and overlays first; Strategies and Scenarios are never edited "
                "silently."
            )
        connection.execute(
            "DELETE FROM investment_units WHERE investment_id = ? AND deal_id = ?",
            (investment_id, unit_id),
        )
        connection.execute(
            "DELETE FROM investment_unit_details WHERE investment_id = ? AND unit_id = ?",
            (investment_id, unit_id),
        )
        connection.execute("DELETE FROM variant_snapshots WHERE root_id = ?", (investment_id,))
        _touch_investment(connection, investment_id, now=now)

    return get_visible_investment(investment_id, db_path=db_path)
