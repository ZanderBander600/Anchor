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
    InvestmentStrategyOverlay,
    NoPartnership,
    OperatingOutcome,
    OperatingOutcomeSet,
    StrategyDefinition,
    StrategyDomain,
    StrategyIssue,
    StrategyOverlay,
    StrategyValidationError,
    strategy_capital_structure,
    strategy_partnership,
    validate_investment_strategy,
    validate_strategy,
)
from ..capital_structure.contracts import (
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureValidationError,
    DebtTerms,
    FixedAmount,
    FundingAmountRule,
    FundingEvent,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    PositionFee,
    PositionScope,
    PositionTerms,
    PreferredEquityTerms,
    ScopeKind,
    ShortfallResolution,
)
from ..capital_structure.validation import validate_capital_structure
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
from ..partnership.contracts import (
    BenchmarkShare,
    CatchUpRecipient,
    CatchUpRecipientKind,
    CatchUpTerms,
    ContributionRule,
    EconomicAccount,
    ExplicitSplit,
    HurdleCombinator,
    HurdleCondition,
    HurdleSubject,
    HurdleSubjectKind,
    HurdleTerms,
    IrrHurdle,
    MoicHurdle,
    Partner,
    PartnerRole,
    Partnership,
    PartnershipValidationError,
    ProRataByContribution,
    PromoteBenchmark,
    SimpleDistributionOrder,
    SplitRule,
    SplitShare,
    TierKind,
    TierSplit,
    WaterfallTier,
)
from ..partnership.validation import validate_partnership

# Gate AM1. Contracts and range-checking only -- no calculation module is
# imported here, exactly as this store imports no engine calculation module.
# ``anchor.asset_management.performance`` (the sole authority for every AM1
# financial result) is deliberately absent: nothing computed is persisted, so
# the store has no reason to reach it.
from ..asset_management.contracts import (
    MONETARY_FIELDS as AM1_MONETARY_FIELDS,
    BudgetImmutableError,
    ManagedAsset,
    ManagedAssetExistsError,
    ManagedAssetNotFoundError,
    MonthlyAssetReport,
    MonthlyReportExistsError,
    MonthlyReportNotFoundError,
    OperatingFigures,
)
from ..asset_management.validation import (
    normalize_reporting_month,
    require_valid_managed_asset,
    require_valid_monthly_report,
)
from .capital_structure_codec import FundingAmountRuleKind, amount_rule_kind
from .contracts import (
    Deal,
    DealNotFoundError,
    Investment,
    InvestmentCapitalStructures,
    InvestmentNotFoundError,
    InvestmentPartnerships,
    InvestmentScenario,
    InvestmentStrategy,
    InvestmentStructureError,
    InvestmentUnit,
    InvestmentUnitNotFoundError,
    OneWaySensitivitySnapshot,
    ScenarioNotFoundError,
    StrategyCapitalStructure,
    StrategyNotFoundError,
    StrategyPartnership,
    TwoWaySensitivitySnapshot,
    VisibleInvestment,
)
from .partnership_codec import HurdleConditionKind, condition_kind, split_rule_kind
from .position_identity import (
    StructureOwner,
    StructureOwnerKind,
    require_coherent_position_identity,
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
# Phase 7 Gate P7.8B: schema version 11 adds six purely additive Capital
# Structure tables -- the structure owner and its positions, funding events,
# fees, debt terms and preferred terms -- created unconditionally by
# ``_connect`` exactly as version 10's were. No ALTER of any table and no
# existing row read or rewritten: every Deal, Investment, Strategy, Scenario and
# cached variant is untouched, and a Deal or Strategy gains a Capital Structure
# only when the analyst opts in. An Investment with no structure row has the
# neutral empty structure, which is exactly today's behaviour (P-11).
# Phase 7 Gate P7.9 Stage 2: schema version 12 adds eight purely additive
# Partnership tables -- the Partnership owner marker and its partners, benchmark
# shares, promote participants, waterfall tiers, tier splits, hurdle conditions
# and catch-up terms -- created unconditionally by ``_connect`` exactly as
# version 11's were. No ALTER and no existing row read or rewritten: an
# Investment gains a Partnership only when the analyst opts in, and one with no
# Partnership row has none -- no Partnership result, fingerprint or key (FP-2).
#
# Gate AM1 -- schema version 13 adds the two Asset Management tables,
# ``managed_assets`` and ``monthly_asset_reports`` -- created unconditionally by
# ``_connect`` exactly as version 12's were. No ALTER and no existing row read
# or rewritten: a Deal gains a Managed Asset only when the analyst explicitly
# creates one, and a v12 database simply gains two empty tables.
_SCHEMA_VERSION = 13


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


class PersistedCapitalStructureDataError(PersistedDealDataError):
    """A stored Capital Structure that cannot recreate its authoritative P7.7
    contract: a class, scope, resolution or amount-rule token the contract no
    longer recognises, a position whose terms rows do not match its class, an
    event or fee with no position, or a structure the P7.7 validator refuses.

    Raised rather than repaired, and never softened into an empty structure. A
    Capital Structure that read as empty because one row would not decode would
    silently delete a lender from the stack, and every figure downstream of it --
    the residual, the Common Equity return, the coverage of every senior
    position -- would look perfectly ordinary."""


class PersistedPartnershipDataError(PersistedDealDataError):
    """A stored Partnership that cannot recreate its authoritative P7.9
    contract (Stage 2): a role, rule, kind, subject, recipient, convention or
    order token the contract no longer recognises; a row whose columns do not
    match the token it states; a missing or miscounted promote-participant set;
    a child row with no parent; or a Partnership the Stage 1 validator refuses.

    Raised rather than repaired, and never softened into "no Partnership". A
    Partnership that read as absent because one row would not decode would
    silently hand every partner's cash to nobody, and an unreadable participant
    set read as empty would silently erase a sponsor's Promote Earned."""


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


# =============================================================================
# Phase 7 Gate P7.8B -- the persisted Capital Structure, schema version 11.
#
# Six purely additive tables, created by ``_connect`` via CREATE TABLE IF NOT
# EXISTS exactly as every table since version 2. No ALTER, and no existing row
# is read or rewritten.
#
# **One owner type: the Investment** (Section 15.1). ``capital_structures`` holds
# one row per stored structure, and ``owner_kind`` says which of the two owners
# states it:
#
#   * ``base``   -- the Investment's own Base Capital Structure, which the
#                   implicit Base Strategy owns. ``owner_id`` is the Investment
#                   id. The Base Strategy is never a stored Strategy row.
#   * ``strategy`` -- one Strategy's whole replacement. ``owner_id`` is that
#                   Strategy's id.
#
# ``UNIQUE (owner_kind, owner_id)`` is that rule in the schema: one structure per
# owner, so a second can never be written beside the first.
#
# **The marker is the meaning** (P7.8B's mandatory distinction):
#
#   * no ``base`` row          -- the Investment has no Base structure, which is
#                                the neutral empty one. Reading it creates
#                                nothing.
#   * no ``strategy`` row      -- that Strategy INHERITS the Base structure.
#   * a ``strategy`` row with no position rows -- that Strategy explicitly
#                                replaces the Base structure with an EMPTY one:
#                                "this Strategy deliberately uses no structured
#                                capital". It is not inheritance, and the two are
#                                never collapsed.
#
# **Relational and typed, never a JSON blob.** Every field of the P7.7 financial
# contracts is its own column, so the stored financial data is inspectable and a
# malformed value is visible rather than hidden inside a document: REAL for rates
# and dollars (an IEEE 754 double, so a float round-trips bit-identically),
# INTEGER for whole months, years and sequences, and TEXT for the wire tokens the
# enums already use.
#
# **Position ids are owner-scoped, never database-global.** The same
# ``position_id`` is *meant* to appear in the Base structure and in one or more
# Strategy structures -- that is what makes ``POSITION(position_id)`` a coherent
# comparison -- so every key here is ``(structure_id, ...)``. The same holds for
# a funding event id and a fee id, which are unique within one structure (P7.7's
# one capital-event namespace) and repeat freely across copied structures.
#
# No FOREIGN KEY / ON DELETE CASCADE, for the reason stated above
# ``lease_level_suites``. Every lifecycle function deletes these rows explicitly,
# in one transaction with their parent.
# =============================================================================

_CREATE_CAPITAL_STRUCTURES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS capital_structures (
    structure_id   TEXT PRIMARY KEY,
    investment_id  TEXT NOT NULL,
    owner_kind     TEXT NOT NULL CHECK (owner_kind IN ('base', 'strategy')),
    owner_id       TEXT NOT NULL,
    UNIQUE (owner_kind, owner_id)
)
"""

_CREATE_CAPITAL_POSITIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS capital_positions (
    structure_id          TEXT NOT NULL,
    position_id           TEXT NOT NULL,
    ordinal               INTEGER NOT NULL,
    name                  TEXT NOT NULL,
    position_class        TEXT NOT NULL,
    priority              INTEGER NOT NULL,
    scope_kind            TEXT NOT NULL,
    scope_unit_id         TEXT,
    shortfall_resolution  TEXT,
    PRIMARY KEY (structure_id, position_id)
)
"""

_CREATE_CAPITAL_FUNDING_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS capital_funding_events (
    structure_id   TEXT NOT NULL,
    position_id    TEXT NOT NULL,
    event_id       TEXT NOT NULL,
    model_month    INTEGER NOT NULL,
    sequence       INTEGER NOT NULL,
    amount_rule    TEXT NOT NULL,
    amount         REAL,
    pct            REAL,
    timepoint_id   TEXT,
    PRIMARY KEY (structure_id, event_id)
)
"""

_CREATE_CAPITAL_POSITION_FEES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS capital_position_fees (
    structure_id  TEXT NOT NULL,
    position_id   TEXT NOT NULL,
    fee_id        TEXT NOT NULL,
    description   TEXT NOT NULL,
    amount        REAL NOT NULL,
    model_month   INTEGER NOT NULL,
    sequence      INTEGER NOT NULL,
    PRIMARY KEY (structure_id, fee_id)
)
"""

_CREATE_CAPITAL_DEBT_TERMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS capital_debt_terms (
    structure_id      TEXT NOT NULL,
    position_id       TEXT NOT NULL,
    interest_rate     REAL NOT NULL,
    amortization      INTEGER NOT NULL,
    io_period         INTEGER NOT NULL,
    maturity_month    INTEGER NOT NULL,
    current_pay_rate  REAL NOT NULL,
    pik_rate          REAL NOT NULL,
    PRIMARY KEY (structure_id, position_id)
)
"""

_CREATE_CAPITAL_PREFERRED_TERMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS capital_preferred_terms (
    structure_id       TEXT NOT NULL,
    position_id        TEXT NOT NULL,
    preferred_rate     REAL NOT NULL,
    current_pay_rate   REAL NOT NULL,
    accrual_permitted  INTEGER NOT NULL CHECK (accrual_permitted IN (0, 1)),
    accrual_convention TEXT,
    redemption_month   INTEGER NOT NULL,
    PRIMARY KEY (structure_id, position_id)
)
"""

#: Every child table one Capital Structure owns, in delete order (children
#: before the structure row itself).
_CAPITAL_STRUCTURE_CHILD_TABLES = (
    "capital_funding_events",
    "capital_position_fees",
    "capital_debt_terms",
    "capital_preferred_terms",
    "capital_positions",
)

_P7_8_TABLES = ("capital_structures", *_CAPITAL_STRUCTURE_CHILD_TABLES)

#: The two owners of a stored Capital Structure, as ``owner_kind`` spells them.
_BASE_OWNER_KIND = "base"
_STRATEGY_OWNER_KIND = "strategy"


# =============================================================================
# Phase 7 Gate P7.9 Stage 2 -- the persisted Partnership, schema version 12.
#
# Eight purely additive tables, created by ``_connect`` via CREATE TABLE IF NOT
# EXISTS exactly as every table since version 2. No ALTER, and no existing row
# is read or rewritten.
#
# **One owner type: the Investment** (Section 15.1), with the same two owners as
# a Capital Structure: ``base`` (``owner_id`` is the Investment id; the implicit
# Base Strategy owns it) and ``strategy`` (``owner_id`` is the Strategy id).
# ``UNIQUE (owner_kind, owner_id)`` keeps one Partnership per owner.
#
# **The marker is the meaning** (the same three states as a Capital Structure):
#
#   * no ``base`` row      -- the Investment has no Base Partnership. Reading it
#                            creates nothing, and nothing is fingerprinted.
#   * no ``strategy`` row  -- that Strategy INHERITS the Base Partnership.
#   * a ``strategy`` row with ``has_partnership = 0`` -- that Strategy explicitly
#                            has NO Partnership. A Partnership always has a
#                            partner, so there is no "empty Partnership" to
#                            store instead; the flag is the statement.
#
# A ``base`` row with ``has_partnership = 0`` is never written (clearing the
# Base Partnership removes its row), so a database holding one is corrupt.
#
# **Promote participants: stated, never defaulted.** ``promote_participant_count``
# records how many participant rows the Partnership states. ``0`` is the
# explicitly confirmed empty set; ``NULL`` on a stated Partnership is a missing
# set, which is corrupt and never read as empty; a count that disagrees with the
# rows is corrupt too.
#
# **Relational and typed, never a JSON blob.** Every contract field is its own
# column: REAL for shares, rates, multiples and targets (a float round-trips
# bit-identically), INTEGER for sequences and ordinals, TEXT for the Stage 1 wire
# tokens and the codec's condition token. A union is stored under its explicit
# discriminator (``split_rule``, ``condition_kind``, ``subject_kind``,
# ``recipient_kind``), and the columns a row states must be exactly those its
# token requires. A token the contract no longer knows fails closed.
#
# **Ids are owner-scoped.** The same ``partner_id`` and ``tier_id`` are *meant* to
# appear in the Base Partnership and in a Strategy's own -- that is what makes
# ``PARTNER(partner_id)`` a coherent comparison -- so every key is
# ``(partnership_id, ...)``. ``ordinal`` keeps the analyst's authored order for
# presentation; no fingerprint or allocation reads it.
#
# No FOREIGN KEY / ON DELETE CASCADE, for the reason stated above
# ``lease_level_suites``. Every lifecycle function deletes these rows explicitly,
# in one transaction with their parent.
# =============================================================================

_CREATE_PARTNERSHIPS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS partnerships (
    partnership_id             TEXT PRIMARY KEY,
    investment_id              TEXT NOT NULL,
    owner_kind                 TEXT NOT NULL CHECK (owner_kind IN ('base', 'strategy')),
    owner_id                   TEXT NOT NULL,
    has_partnership            INTEGER NOT NULL CHECK (has_partnership IN (0, 1)),
    contribution_rule          TEXT,
    promote_participant_count  INTEGER,
    UNIQUE (owner_kind, owner_id)
)
"""

_CREATE_PARTNERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS partners (
    partnership_id    TEXT NOT NULL,
    partner_id        TEXT NOT NULL,
    ordinal           INTEGER NOT NULL,
    name              TEXT NOT NULL,
    role              TEXT NOT NULL,
    investor_class    TEXT,
    commitment_share  REAL NOT NULL,
    PRIMARY KEY (partnership_id, partner_id)
)
"""

_CREATE_PARTNERSHIP_BENCHMARK_SHARES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS partnership_benchmark_shares (
    partnership_id  TEXT NOT NULL,
    partner_id      TEXT NOT NULL,
    ordinal         INTEGER NOT NULL,
    share           REAL NOT NULL,
    PRIMARY KEY (partnership_id, partner_id)
)
"""

_CREATE_PARTNERSHIP_PROMOTE_PARTICIPANTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS partnership_promote_participants (
    partnership_id  TEXT NOT NULL,
    partner_id      TEXT NOT NULL,
    ordinal         INTEGER NOT NULL,
    PRIMARY KEY (partnership_id, partner_id)
)
"""

_CREATE_WATERFALL_TIERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS waterfall_tiers (
    partnership_id          TEXT NOT NULL,
    tier_id                 TEXT NOT NULL,
    ordinal                 INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    sequence                INTEGER NOT NULL,
    kind                    TEXT NOT NULL,
    split_rule              TEXT NOT NULL,
    subject_kind            TEXT,
    subject_partner_id      TEXT,
    subject_investor_class  TEXT,
    subject_account         TEXT,
    combinator              TEXT,
    PRIMARY KEY (partnership_id, tier_id)
)
"""

_CREATE_WATERFALL_TIER_SPLITS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS waterfall_tier_splits (
    partnership_id  TEXT NOT NULL,
    tier_id         TEXT NOT NULL,
    partner_id      TEXT NOT NULL,
    ordinal         INTEGER NOT NULL,
    share           REAL NOT NULL,
    PRIMARY KEY (partnership_id, tier_id, partner_id)
)
"""

_CREATE_WATERFALL_HURDLE_CONDITIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS waterfall_hurdle_conditions (
    partnership_id             TEXT NOT NULL,
    tier_id                    TEXT NOT NULL,
    condition_id               TEXT NOT NULL,
    ordinal                    INTEGER NOT NULL,
    condition_kind             TEXT NOT NULL,
    rate                       REAL,
    accrual_convention         TEXT,
    simple_distribution_order  TEXT,
    multiple                   REAL,
    PRIMARY KEY (partnership_id, tier_id, condition_id)
)
"""

_CREATE_WATERFALL_CATCH_UP_TERMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS waterfall_catch_up_terms (
    partnership_id            TEXT NOT NULL,
    tier_id                   TEXT NOT NULL,
    recipient_kind            TEXT NOT NULL,
    recipient_partner_id      TEXT,
    recipient_investor_class  TEXT,
    target_profit_share       REAL NOT NULL,
    PRIMARY KEY (partnership_id, tier_id)
)
"""

#: Every child table one Partnership owns, in delete order (children before the
#: owner row itself).
_PARTNERSHIP_CHILD_TABLES = (
    "partners",
    "partnership_benchmark_shares",
    "partnership_promote_participants",
    "waterfall_tier_splits",
    "waterfall_hurdle_conditions",
    "waterfall_catch_up_terms",
    "waterfall_tiers",
)

_P7_9_TABLES = ("partnerships", *_PARTNERSHIP_CHILD_TABLES)


# =============================================================================
# Gate AM1 -- the persisted Managed Asset and Monthly Asset Report, schema
# version 13.
#
# Two purely additive tables, created by ``_connect`` via CREATE TABLE IF NOT
# EXISTS exactly as every table since version 2. No ALTER, and no existing row
# is read or rewritten -- in particular no ``deals`` row is touched when a
# Managed Asset is created from it.
#
# **A Managed Asset is not a Deal.** It has its own id space, its own name and
# its own lifecycle. ``source_deal_id`` is provenance, not ownership: the Deal
# it came from remains an acquisition analysis that can still be edited,
# re-analyzed and saved, and none of that reaches this table. The FOREIGN KEY
# (declared, and unlike the pre-P7 tables actually enforceable here because
# neither table predates ``PRAGMA foreign_keys``) records that provenance;
# ``UNIQUE (source_deal_id)`` is the one-asset-per-Deal rule, enforced by the
# database rather than by a check a future write path could forget.
#
# **The fingerprint is a frozen copy, captured once.** ``acquisition_fingerprint``
# is the Deal's authoritative analysis fingerprint at the moment the asset was
# created. It is written by ``create_managed_asset`` and by nothing else -- no
# UPDATE statement in this module sets it -- so a later Deal edit changes that
# Deal's current fingerprint and leaves this column exactly as it was. The
# divergence between the two is the product's provenance signal, never a
# trigger to rewrite anything.
#
# **The approved budget is frozen in typed columns.** Both statements are stored
# as twelve REAL columns each, prefixed ``budget_``/``actual_`` -- never a JSON
# financial blob, so a figure is queryable, typed, and cannot acquire a field
# that no contract declares. The budget columns are written once, by the INSERT
# in ``create_monthly_report``; ``update_monthly_report_actuals`` names only
# ``actual_*``, ``commentary`` and ``updated_at`` in its SET clause, so a budget
# change is not merely refused at the contract boundary -- there is no SQL in
# this module capable of performing one.
#
# **One report per asset per month.** ``reporting_month`` is stored as an
# ISO-8601 date string already normalized to the first of the month by the
# caller, and ``PRIMARY KEY (managed_asset_id, reporting_month)`` makes a second
# report for one month impossible. Two spellings of March cannot become two rows
# that each freeze a different budget.
#
# Nothing computed is persisted: no total, variance, percentage, assessment,
# attention item or trend point has a column. Every one of them is derived on
# read by ``anchor.asset_management.performance``, which is the sole authority.
# =============================================================================

#: The twelve REAL columns one statement occupies, in ``OperatingFigures``
#: field order. Derived from the contract itself rather than restated, so a
#: field added to ``OperatingFigures`` is a schema change this module notices at
#: import rather than silently drops on write.
_AM1_FIGURE_FIELDS: tuple[str, ...] = ("occupancy", *AM1_MONETARY_FIELDS)


def _am1_figure_columns(prefix: str) -> str:
    """The DDL fragment for one statement's twelve columns."""

    return ",\n    ".join(f"{prefix}_{field} REAL NOT NULL" for field in _AM1_FIGURE_FIELDS)


_CREATE_MANAGED_ASSETS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS managed_assets (
    id                      TEXT PRIMARY KEY,
    source_deal_id          TEXT NOT NULL,
    name                    TEXT NOT NULL,
    acquisition_date        TEXT NOT NULL,
    property_type           TEXT,
    market                  TEXT,
    acquisition_fingerprint TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    UNIQUE (source_deal_id)
)
"""

_CREATE_MONTHLY_ASSET_REPORTS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS monthly_asset_reports (
    managed_asset_id TEXT NOT NULL,
    reporting_month  TEXT NOT NULL,
    {_am1_figure_columns("budget")},
    {_am1_figure_columns("actual")},
    commentary       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (managed_asset_id, reporting_month),
    FOREIGN KEY (managed_asset_id) REFERENCES managed_assets (id)
)
"""

_AM1_TABLES = ("managed_assets", "monthly_asset_reports")


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
    # P7.8B -- schema version 11 adds the six Capital Structure tables the same
    # way: no row is written for anything that already exists, no table is
    # altered, and no Investment gains a structure by being opened. A v10
    # database simply gains six empty tables.
    # P7.9 Stage 2 -- schema version 12 adds the eight Partnership tables the
    # same way: no row is written for anything that already exists, no table is
    # altered, and no Investment gains a Partnership by being opened. A v11
    # database simply gains eight empty tables.
    # Gate AM1 -- schema version 13 adds ``managed_assets`` and
    # ``monthly_asset_reports`` the same way: no row is written for anything
    # that already exists, no table is altered, and no Deal gains a Managed
    # Asset by being opened or edited. A v12 database simply gains two empty
    # tables, and every pre-existing Deal keeps loading and responding exactly
    # as it did.
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
    connection.execute(_CREATE_CAPITAL_STRUCTURES_TABLE_SQL)
    connection.execute(_CREATE_CAPITAL_POSITIONS_TABLE_SQL)
    connection.execute(_CREATE_CAPITAL_FUNDING_EVENTS_TABLE_SQL)
    connection.execute(_CREATE_CAPITAL_POSITION_FEES_TABLE_SQL)
    connection.execute(_CREATE_CAPITAL_DEBT_TERMS_TABLE_SQL)
    connection.execute(_CREATE_CAPITAL_PREFERRED_TERMS_TABLE_SQL)
    connection.execute(_CREATE_PARTNERSHIPS_TABLE_SQL)
    connection.execute(_CREATE_PARTNERS_TABLE_SQL)
    connection.execute(_CREATE_PARTNERSHIP_BENCHMARK_SHARES_TABLE_SQL)
    connection.execute(_CREATE_PARTNERSHIP_PROMOTE_PARTICIPANTS_TABLE_SQL)
    connection.execute(_CREATE_WATERFALL_TIERS_TABLE_SQL)
    connection.execute(_CREATE_WATERFALL_TIER_SPLITS_TABLE_SQL)
    connection.execute(_CREATE_WATERFALL_HURDLE_CONDITIONS_TABLE_SQL)
    connection.execute(_CREATE_WATERFALL_CATCH_UP_TERMS_TABLE_SQL)
    connection.execute(_CREATE_MANAGED_ASSETS_TABLE_SQL)
    connection.execute(_CREATE_MONTHLY_ASSET_REPORTS_TABLE_SQL)
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
    # P7.8B: every Capital Structure the Investment owns -- its Base structure
    # and each Strategy's own. An Investment with none loses nothing here.
    _delete_investment_capital_structures(connection, investment_id)
    # P7.9 Stage 2: every Partnership statement the Investment owns -- its Base
    # Partnership and each Strategy's own.
    _delete_investment_partnerships(connection, investment_id)
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
    """Whether the hidden wrapper has no P7 structure left: no Scenario, from
    P7.4 no Strategy, from P7.8B no Capital Structure, and from P7.9 Stage 2 no
    Partnership. A wrapper that still holds any of them never collapses,
    whichever was removed last."""

    remaining_scenario = connection.execute(
        "SELECT 1 FROM scenarios WHERE investment_id = ? LIMIT 1", (investment_id,)
    ).fetchone()
    remaining_strategy = connection.execute(
        "SELECT 1 FROM strategies WHERE investment_id = ? LIMIT 1", (investment_id,)
    ).fetchone()
    remaining_structure = connection.execute(
        "SELECT 1 FROM capital_structures WHERE investment_id = ? LIMIT 1", (investment_id,)
    ).fetchone()
    remaining_partnership = connection.execute(
        "SELECT 1 FROM partnerships WHERE investment_id = ? LIMIT 1", (investment_id,)
    ).fetchone()
    return (
        remaining_scenario is None
        and remaining_strategy is None
        and remaining_structure is None
        and remaining_partnership is None
    )


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
    """Every overlay row of one Strategy: each Unit domain's table, and (P7.8B)
    the Investment-root Capital Structure it states, with every row under it.
    Removing the structure is what makes an update a whole replacement and makes
    a deleted Strategy leave no position behind."""

    for table in _STRATEGY_OVERLAY_TABLES:
        connection.execute(f"DELETE FROM {table} WHERE strategy_id = ?", (strategy_id,))
    _delete_capital_structure(connection, _STRATEGY_OWNER_KIND, strategy_id)
    # P7.9 Stage 2: the Strategy's own Partnership statement, the same way.
    _delete_partnership(connection, _STRATEGY_OWNER_KIND, strategy_id)


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

    own_structure = _stored_capital_structure(
        connection,
        _STRATEGY_OWNER_KIND,
        strategy_id,
        where=f"Strategy {strategy_id!r}'s Capital Structure",
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
        # P7.8B: no structure row means this Strategy INHERITS the Base Capital
        # Structure; a row with no position means it explicitly replaces it with
        # an empty one. The two are never collapsed on the way out either.
        root_overlays=()
        if own_structure is None
        else (
            InvestmentStrategyOverlay(
                domain=StrategyDomain.CAPITAL_STRUCTURE, content=own_structure
            ),
        ),
    )
    # P7.9 Stage 2: the Strategy's own Partnership statement, after the Capital
    # Structure. None stored means it inherits the Base Partnership.
    strategy = _with_strategy_partnership(connection, strategy)
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
    _write_strategy_root_overlays(connection, investment_id, strategy)
    _write_strategy_partnership(connection, investment_id, strategy)
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
    root_overlays: Iterable[InvestmentStrategyOverlay] = (),
    db_path: Path | None = None,
) -> InvestmentStrategy:
    """Persist a new Strategy for the Deal ``deal_id``, materializing its hidden
    one-unit Investment first if it has none (Q4).

    ``root_overlays`` carries the Strategy's Investment-root replacements
    (P7.8B): its own Capital Structure, when it states one. Stating none is
    inheriting the Base structure.

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
        root_overlays=tuple(root_overlays),
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
        _require_coherent_strategy_identity(connection, investment_id, strategy)
        _insert_strategy(connection, investment_id, strategy, now=now)

    return get_strategy(investment_id, strategy.strategy_id, db_path=db_path)


def create_strategy(
    investment_id: str,
    *,
    name: str,
    description: str | None = None,
    overlays: Iterable[StrategyOverlay] = (),
    root_overlays: Iterable[InvestmentStrategyOverlay] = (),
    db_path: Path | None = None,
) -> InvestmentStrategy:
    """Persist another Strategy in the existing Investment ``investment_id``:
    the hidden wrapper, validated for its one unit, or (P7.6) a visible
    Investment, validated for its member Units. ``root_overlays`` carries its
    Investment-root replacements (P7.8B)."""

    strategy = StrategyDefinition(
        strategy_id=uuid.uuid4().hex,
        name=name,
        description=description,
        overlays=tuple(overlays),
        root_overlays=tuple(root_overlays),
    )
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        _require_valid_strategy(strategy, owner=owner)
        _require_coherent_strategy_identity(connection, investment_id, strategy)
        _insert_strategy(connection, investment_id, strategy, now=now)

    return get_strategy(investment_id, strategy.strategy_id, db_path=db_path)


def update_strategy(
    investment_id: str,
    strategy_id: str,
    *,
    name: str,
    description: str | None = None,
    overlays: Iterable[StrategyOverlay] = (),
    root_overlays: Iterable[InvestmentStrategyOverlay] = (),
    db_path: Path | None = None,
) -> InvestmentStrategy:
    """Replace one Strategy's name, description, whole overlay set and whole
    Investment-root overlay set, keeping its id.

    Validated before anything is written; the old overlays and the old Capital
    Structure are removed and the new ones written in the same transaction, so a
    failure leaves the previous Strategy exactly as it was. Passing no
    ``root_overlays`` is the analyst choosing to inherit the Base Capital
    Structure again, and it removes the Strategy's own structure; passing an
    empty structure keeps the explicit "no structured capital" replacement. The
    two are never confused.

    Cached Project variants are left alone: each is served only while its source
    fingerprint still matches the resolved inputs, and a Capital Structure is
    not one of those inputs (P-4), so junior financing never invalidates an
    upstream Project result."""

    strategy = StrategyDefinition(
        strategy_id=strategy_id,
        name=name,
        description=description,
        overlays=tuple(overlays),
        root_overlays=tuple(root_overlays),
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
        _require_coherent_strategy_identity(connection, investment_id, strategy)
        _delete_strategy_overlay_rows(connection, strategy_id)
        _write_strategy_overlays(connection, strategy_id, strategy.overlays)
        _write_strategy_root_overlays(connection, investment_id, strategy)
        _write_strategy_partnership(connection, investment_id, strategy)
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
        # P7.8B: a Unit that a Capital Structure position is scoped to is
        # referenced just as firmly as one a Scenario override addresses. The
        # position is never reassigned to Investment scope and never deleted:
        # the analyst changes the structure first.
        *_capital_structure_references(connection, investment_id, unit_id),
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
        _require_promotable_capital_structures(connection, investment_id)
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


def _capital_structure_owner_row(
    connection: sqlite3.Connection, owner_kind: str, owner_id: str
) -> sqlite3.Row | None:
    """The structure row one owner states, or ``None`` -- the marker itself.

    ``None`` for a ``base`` owner means the Investment states no Base structure,
    which is the neutral empty one. ``None`` for a ``strategy`` owner means that
    Strategy inherits the Base structure, which is a different answer from a row
    with no positions (an explicit empty replacement)."""

    return connection.execute(
        "SELECT * FROM capital_structures WHERE owner_kind = ? AND owner_id = ?",
        (owner_kind, owner_id),
    ).fetchone()


def _capital_enum(value: object, enum_type: type, *, path: str) -> Any:
    """A stored Capital Structure token as its authoritative member.

    The decode is the one shared codec; only the error type is this layer's own,
    so a malformed capital stack is distinguishable from any other corrupt row --
    and, like every decode here, a token the enum no longer recognises is a
    failure rather than a reason to pick a default."""

    try:
        return _decode_enum(value, enum_type, path=path)
    except PersistedDealDataError as error:
        raise PersistedCapitalStructureDataError(str(error)) from None


def _amount_rule_from_row(row: sqlite3.Row, *, where: str) -> FundingAmountRule:
    """One stored funding amount rule, strictly. A token the contract no longer
    knows, or a rule whose columns do not match the token it states, is corrupt:
    nothing is defaulted to a fixed amount."""

    kind, amount, pct, timepoint_id = (
        row["amount_rule"],
        row["amount"],
        row["pct"],
        row["timepoint_id"],
    )
    stated = {"amount": amount, "pct": pct, "timepoint_id": timepoint_id}

    def _exactly(*required: str) -> None:
        wrong = sorted(
            name for name, value in stated.items() if (value is None) is (name in required)
        )
        if wrong:
            raise PersistedCapitalStructureDataError(
                f"{where} states {kind!r} funding, whose columns are exactly "
                f"{', '.join(required)}; {', '.join(wrong)} disagree(s)."
            )

    match kind:
        case FundingAmountRuleKind.FIXED_AMOUNT:
            _exactly("amount")
            return FixedAmount(amount=amount)
        case FundingAmountRuleKind.PCT_OF_PRICE:
            _exactly("pct")
            return PctOfPrice(pct=pct)
        case FundingAmountRuleKind.PCT_OF_VALUE:
            _exactly("pct", "timepoint_id")
            return PctOfValue(timepoint_id=timepoint_id, pct=pct)
        case _:
            raise PersistedCapitalStructureDataError(
                f"{where} holds amount rule {kind!r}, which is not one of: "
                f"{', '.join(member.value for member in FundingAmountRuleKind)}."
            )


def _capital_position_from_rows(
    row: sqlite3.Row,
    funding_rows: Iterable[sqlite3.Row],
    fee_rows: Iterable[sqlite3.Row],
    debt_row: sqlite3.Row | None,
    preferred_row: sqlite3.Row | None,
    *,
    where: str,
) -> CapitalPosition:
    """One stored position as the exact P7.7 contract.

    The class decides which terms rows must be there, and exactly which: a debt
    position has debt terms and may have fees, a preferred position has
    preferred terms and no fee (P7.7 puts fees on ``DebtTerms`` alone), and the
    common-equity marker has neither. A position whose rows disagree with its
    class is corrupt rather than coerced into a class its rows would fit."""

    position_id = row["position_id"]
    located = f"{where} position {position_id!r}"
    position_class = _capital_enum(
        row["position_class"], PositionClass, path=f"{located} position_class"
    )
    scope_kind = _capital_enum(row["scope_kind"], ScopeKind, path=f"{located} scope_kind")
    resolution = _capital_enum(
        row["shortfall_resolution"], ShortfallResolution, path=f"{located} shortfall_resolution"
    )
    funding = tuple(
        FundingEvent(
            event_id=event["event_id"],
            model_month=event["model_month"],
            sequence=event["sequence"],
            amount_rule=_amount_rule_from_row(
                event, where=f"{located} funding event {event['event_id']!r}"
            ),
        )
        for event in funding_rows
    )
    fees = tuple(
        PositionFee(
            fee_id=fee["fee_id"],
            description=fee["description"],
            amount=fee["amount"],
            model_month=fee["model_month"],
            sequence=fee["sequence"],
        )
        for fee in fee_rows
    )

    def _require(carried: sqlite3.Row | None, *, kind: str, expected: bool) -> None:
        if (carried is not None) is not expected:
            state = "carries no" if expected else "also carries"
            raise PersistedCapitalStructureDataError(
                f"{located} is {position_class} and {state} {kind} terms."
            )

    terms: PositionTerms | None
    match position_class:
        case PositionClass.SENIOR_DEBT | PositionClass.MEZZANINE_DEBT:
            _require(debt_row, kind="debt", expected=True)
            _require(preferred_row, kind="preferred equity", expected=False)
            assert debt_row is not None
            terms = DebtTerms(
                interest_rate=debt_row["interest_rate"],
                amortization=debt_row["amortization"],
                io_period=debt_row["io_period"],
                maturity_month=debt_row["maturity_month"],
                fees=fees,
                current_pay_rate=debt_row["current_pay_rate"],
                pik_rate=debt_row["pik_rate"],
            )
        case PositionClass.PREFERRED_EQUITY:
            _require(preferred_row, kind="preferred equity", expected=True)
            _require(debt_row, kind="debt", expected=False)
            assert preferred_row is not None
            permitted = preferred_row["accrual_permitted"]
            if permitted not in (0, 1):
                raise PersistedCapitalStructureDataError(
                    f"{located} holds accrual_permitted={permitted!r}; it must be 0 or 1."
                )
            terms = PreferredEquityTerms(
                preferred_rate=preferred_row["preferred_rate"],
                current_pay_rate=preferred_row["current_pay_rate"],
                accrual_permitted=bool(permitted),
                accrual_convention=_capital_enum(  # type: ignore[arg-type]
                    preferred_row["accrual_convention"],
                    AccrualConvention,
                    path=f"{located} accrual_convention",
                ),
                redemption_month=preferred_row["redemption_month"],
            )
        case _:
            _require(debt_row, kind="debt", expected=False)
            _require(preferred_row, kind="preferred equity", expected=False)
            terms = None
    if fees and not isinstance(terms, DebtTerms):
        raise PersistedCapitalStructureDataError(
            f"{located} is {position_class} and holds fee row(s); a fee belongs to a debt "
            "position's terms."
        )
    return CapitalPosition(
        position_id=position_id,
        name=row["name"],
        position_class=position_class,  # type: ignore[arg-type]
        priority=row["priority"],
        scope=PositionScope(kind=scope_kind, unit_id=row["scope_unit_id"]),  # type: ignore[arg-type]
        funding=funding,
        terms=terms,
        shortfall_resolution=resolution,  # type: ignore[arg-type]
    )


def _read_capital_structure(
    connection: sqlite3.Connection, structure_id: str, *, where: str
) -> CapitalStructure:
    """Every row of one stored structure, rebuilt as the P7.7 contract and
    refused if the P7.7 validator refuses it.

    Positions come back in the analyst's own authored order (``ordinal``), which
    is presentation: the economic order is scope then priority, and every
    consumer sorts by it. Membership is deliberately not judged here -- a Unit
    cannot be removed while a structure references it -- so only the contract
    itself can make a stored structure unreadable."""

    position_rows = connection.execute(
        "SELECT * FROM capital_positions WHERE structure_id = ? ORDER BY ordinal, position_id",
        (structure_id,),
    ).fetchall()
    known = {row["position_id"] for row in position_rows}
    funding_rows: dict[str, list[sqlite3.Row]] = {}
    for event in connection.execute(
        "SELECT * FROM capital_funding_events WHERE structure_id = ? "
        "ORDER BY model_month, sequence, event_id",
        (structure_id,),
    ):
        funding_rows.setdefault(event["position_id"], []).append(event)
    fee_rows: dict[str, list[sqlite3.Row]] = {}
    for fee in connection.execute(
        "SELECT * FROM capital_position_fees WHERE structure_id = ? "
        "ORDER BY model_month, sequence, fee_id",
        (structure_id,),
    ):
        fee_rows.setdefault(fee["position_id"], []).append(fee)
    debt_rows = {
        row["position_id"]: row
        for row in connection.execute(
            "SELECT * FROM capital_debt_terms WHERE structure_id = ?", (structure_id,)
        )
    }
    preferred_rows = {
        row["position_id"]: row
        for row in connection.execute(
            "SELECT * FROM capital_preferred_terms WHERE structure_id = ?", (structure_id,)
        )
    }
    orphaned = sorted(
        (set(funding_rows) | set(fee_rows) | set(debt_rows) | set(preferred_rows)) - known
    )
    if orphaned:
        raise PersistedCapitalStructureDataError(
            f"{where} holds funding, fee or terms rows for position(s) "
            f"{', '.join(orphaned)}, which it does not hold; a child row never implies a "
            "position."
        )

    structure = CapitalStructure(
        positions=tuple(
            _capital_position_from_rows(
                row,
                funding_rows.get(row["position_id"], ()),
                fee_rows.get(row["position_id"], ()),
                debt_rows.get(row["position_id"]),
                preferred_rows.get(row["position_id"]),
                where=where,
            )
            for row in position_rows
        )
    )
    issues = validate_capital_structure(structure, acquisition_loan_unit_ids=())
    if issues:
        raise PersistedCapitalStructureDataError(
            f"{where} does not validate: " + "; ".join(issue.message for issue in issues)
        )
    return structure


def _stored_capital_structure(
    connection: sqlite3.Connection, owner_kind: str, owner_id: str, *, where: str
) -> CapitalStructure | None:
    """The structure one owner states, or ``None`` when it states none. A ``base``
    marker with no position is corrupt: clearing a Base structure removes its
    marker, so an empty one was never written."""

    row = _capital_structure_owner_row(connection, owner_kind, owner_id)
    if row is None:
        return None
    structure = _read_capital_structure(connection, row["structure_id"], where=where)
    if owner_kind == _BASE_OWNER_KIND and not structure.positions:
        raise PersistedCapitalStructureDataError(
            f"{where} holds a Base Capital Structure marker with no position. Clearing the "
            "Base structure removes its marker, so an empty one is never stored; an empty "
            "structure is a Strategy's explicit replacement, never a Base."
        )
    return structure


def _write_capital_structure(
    connection: sqlite3.Connection,
    *,
    investment_id: str,
    owner_kind: str,
    owner_id: str,
    capital_structure: CapitalStructure,
) -> None:
    """One whole structure: its marker, then every position with its funding,
    its fees and its typed terms, in the analyst's authored order.

    Called inside the caller's transaction, after validation, and after any
    previous structure of this owner was removed: a Capital Structure is
    replaced whole, never diffed, so no half-written position stack can exist."""

    structure_id = uuid.uuid4().hex
    connection.execute(
        "INSERT INTO capital_structures (structure_id, investment_id, owner_kind, owner_id) "
        "VALUES (?, ?, ?, ?)",
        (structure_id, investment_id, owner_kind, owner_id),
    )
    for ordinal, position in enumerate(capital_structure.positions):
        connection.execute(
            """
            INSERT INTO capital_positions
                (structure_id, position_id, ordinal, name, position_class, priority, scope_kind,
                 scope_unit_id, shortfall_resolution)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                structure_id,
                position.position_id,
                ordinal,
                position.name,
                _encode_enum(position.position_class),
                int(position.priority),
                _encode_enum(position.scope.kind),
                position.scope.unit_id,
                _encode_enum(position.shortfall_resolution),
            ),
        )
        for event in position.funding:
            rule = event.amount_rule
            connection.execute(
                """
                INSERT INTO capital_funding_events
                    (structure_id, position_id, event_id, model_month, sequence, amount_rule,
                     amount, pct, timepoint_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    structure_id,
                    position.position_id,
                    event.event_id,
                    int(event.model_month),
                    int(event.sequence),
                    amount_rule_kind(rule).value,
                    float(rule.amount) if isinstance(rule, FixedAmount) else None,
                    float(rule.pct) if isinstance(rule, (PctOfPrice, PctOfValue)) else None,
                    rule.timepoint_id if isinstance(rule, PctOfValue) else None,
                ),
            )
        terms = position.terms
        if isinstance(terms, DebtTerms):
            connection.execute(
                """
                INSERT INTO capital_debt_terms
                    (structure_id, position_id, interest_rate, amortization, io_period,
                     maturity_month, current_pay_rate, pik_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    structure_id,
                    position.position_id,
                    float(terms.interest_rate),
                    int(terms.amortization),
                    int(terms.io_period),
                    int(terms.maturity_month),
                    float(terms.current_pay_rate),
                    float(terms.pik_rate),
                ),
            )
            connection.executemany(
                """
                INSERT INTO capital_position_fees
                    (structure_id, position_id, fee_id, description, amount, model_month, sequence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        structure_id,
                        position.position_id,
                        fee.fee_id,
                        fee.description,
                        float(fee.amount),
                        int(fee.model_month),
                        int(fee.sequence),
                    )
                    for fee in terms.fees
                ],
            )
        elif isinstance(terms, PreferredEquityTerms):
            connection.execute(
                """
                INSERT INTO capital_preferred_terms
                    (structure_id, position_id, preferred_rate, current_pay_rate,
                     accrual_permitted, accrual_convention, redemption_month)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    structure_id,
                    position.position_id,
                    float(terms.preferred_rate),
                    float(terms.current_pay_rate),
                    1 if terms.accrual_permitted else 0,
                    _encode_enum(terms.accrual_convention),
                    int(terms.redemption_month),
                ),
            )


def _delete_capital_structure(
    connection: sqlite3.Connection, owner_kind: str, owner_id: str
) -> None:
    """One owner's structure and every row it owns. Deleting nothing is
    ordinary: most owners state no structure."""

    row = _capital_structure_owner_row(connection, owner_kind, owner_id)
    if row is None:
        return
    structure_id = row["structure_id"]
    for table in _CAPITAL_STRUCTURE_CHILD_TABLES:
        connection.execute(f"DELETE FROM {table} WHERE structure_id = ?", (structure_id,))
    connection.execute("DELETE FROM capital_structures WHERE structure_id = ?", (structure_id,))


def _delete_investment_capital_structures(
    connection: sqlite3.Connection, investment_id: str
) -> None:
    """Every Capital Structure the Investment owns -- its Base structure and
    each Strategy's own -- with every row under them."""

    for table in _CAPITAL_STRUCTURE_CHILD_TABLES:
        connection.execute(
            f"DELETE FROM {table} WHERE structure_id IN "
            "(SELECT structure_id FROM capital_structures WHERE investment_id = ?)",
            (investment_id,),
        )
    connection.execute("DELETE FROM capital_structures WHERE investment_id = ?", (investment_id,))


def _strategy_capital_structures(
    connection: sqlite3.Connection, investment_id: str
) -> list[tuple[str, str, CapitalStructure]]:
    """``(strategy_id, name, structure)`` for every Strategy of the Investment
    that states its own Capital Structure, in creation order. A Strategy that
    inherits the Base structure is simply absent."""

    stated: list[tuple[str, str, CapitalStructure]] = []
    for row in connection.execute(
        "SELECT id, name FROM strategies WHERE investment_id = ? ORDER BY created_at, rowid",
        (investment_id,),
    ).fetchall():
        structure = _stored_capital_structure(
            connection,
            _STRATEGY_OWNER_KIND,
            row["id"],
            where=f"Strategy {row['id']!r}'s Capital Structure",
        )
        if structure is not None:
            stated.append((row["id"], row["name"], structure))
    return stated


def _structure_owner(kind: StructureOwnerKind, owner_id: str, label: str) -> StructureOwner:
    return StructureOwner(kind=kind, owner_id=owner_id, label=label)


def _require_coherent_identity(
    connection: sqlite3.Connection,
    investment_id: str,
    *,
    owner_kind: str,
    owner_id: str,
    capital_structure: CapitalStructure,
) -> None:
    """P-8 across the Investment: the structure about to be written, beside
    every other structure the Investment already holds.

    The owner being written replaces its own stored structure rather than being
    compared with it, so re-saving one structure never conflicts with the copy
    it is replacing."""

    others: list[tuple[StructureOwner, CapitalStructure]] = []
    if owner_kind != _BASE_OWNER_KIND:
        base = _stored_capital_structure(
            connection,
            _BASE_OWNER_KIND,
            investment_id,
            where="The Base Capital Structure",
        )
        if base is not None:
            others.append(
                (
                    _structure_owner(
                        StructureOwnerKind.BASE, investment_id, "the Base Capital Structure"
                    ),
                    base,
                )
            )
    for strategy_id, name, structure in _strategy_capital_structures(connection, investment_id):
        if owner_kind == _STRATEGY_OWNER_KIND and strategy_id == owner_id:
            continue
        others.append(
            (
                _structure_owner(StructureOwnerKind.STRATEGY, strategy_id, f"Strategy {name!r}"),
                structure,
            )
        )
    label = (
        "the Base Capital Structure"
        if owner_kind == _BASE_OWNER_KIND
        else "this Strategy's Capital Structure"
    )
    kind = (
        StructureOwnerKind.BASE if owner_kind == _BASE_OWNER_KIND else StructureOwnerKind.STRATEGY
    )
    require_coherent_position_identity(
        [*others, (_structure_owner(kind, owner_id, label), capital_structure)]
    )


def _require_valid_capital_structure(
    capital_structure: object, *, member_unit_ids: Iterable[str]
) -> CapitalStructure:
    """The P7.7 structural authority on a structure about to be stored, judged
    against the owner's Units. This store adds no rule of its own.

    Whether the structure *executes* for a given variant -- a priority the
    acquisition loan holds, CS-5, a funding month P7.8 does not schedule -- is a
    variant question the executor asks of the resolved Project state, so it is
    deliberately not asked here: a Base edit must never make a stored structure
    unwritable or unreadable."""

    issues = validate_capital_structure(
        capital_structure, member_unit_ids=sorted(member_unit_ids), acquisition_loan_unit_ids=()
    )
    if issues:
        raise CapitalStructureValidationError(issues)
    assert isinstance(capital_structure, CapitalStructure)
    return capital_structure


def _replace_capital_structure(
    connection: sqlite3.Connection,
    *,
    investment_id: str,
    owner_kind: str,
    owner_id: str,
    capital_structure: CapitalStructure,
) -> None:
    """Whole-structure atomic replacement: the owner's previous structure and
    every row under it go, then the new one is written, inside the caller's one
    transaction."""

    _delete_capital_structure(connection, owner_kind, owner_id)
    if capital_structure.positions or owner_kind == _STRATEGY_OWNER_KIND:
        _write_capital_structure(
            connection,
            investment_id=investment_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            capital_structure=capital_structure,
        )


def _every_capital_structure(
    connection: sqlite3.Connection, investment_id: str
) -> list[tuple[str, CapitalStructure]]:
    """Every structure the Investment holds, each with the label a message names
    it by: its Base structure, then each Strategy's own in creation order."""

    stated: list[tuple[str, CapitalStructure]] = []
    base = _stored_capital_structure(
        connection, _BASE_OWNER_KIND, investment_id, where="The Base Capital Structure"
    )
    if base is not None:
        stated.append(("the Base Capital Structure", base))
    for _, name, structure in _strategy_capital_structures(connection, investment_id):
        stated.append((f"Strategy {name!r}'s Capital Structure", structure))
    return stated


def _write_strategy_root_overlays(
    connection: sqlite3.Connection, investment_id: str, strategy: StrategyDefinition
) -> None:
    """The Strategy's Investment-root overlays: in P7.8B, its own Capital
    Structure when it states one.

    The marker is written **even for the empty structure**, because that is
    precisely what it distinguishes: a Strategy with no row inherits the Base
    structure, and a Strategy with a row holding no position deliberately uses
    no structured capital."""

    own = strategy_capital_structure(strategy)
    if own is None:
        return
    _write_capital_structure(
        connection,
        investment_id=investment_id,
        owner_kind=_STRATEGY_OWNER_KIND,
        owner_id=strategy.strategy_id,
        capital_structure=own,
    )


def _require_coherent_strategy_identity(
    connection: sqlite3.Connection, investment_id: str, strategy: StrategyDefinition
) -> None:
    """P-8 for a Strategy about to be written: its own Capital Structure against
    every other structure this Investment holds. A Strategy that inherits the
    Base structure states none and cannot conflict with it."""

    own = strategy_capital_structure(strategy)
    if own is None:
        return
    _require_coherent_identity(
        connection,
        investment_id,
        owner_kind=_STRATEGY_OWNER_KIND,
        owner_id=strategy.strategy_id,
        capital_structure=own,
    )


def _require_promotable_capital_structures(
    connection: sqlite3.Connection, investment_id: str
) -> None:
    """Refuse promotion while a stored structure names its residual at Unit
    scope.

    A hidden one-unit executor's analysis root is the Unit, so an authored
    Common Equity marker there is Unit-scoped. A visible Investment's root is
    the Investment, and the P7.8 executor requires the marker at the analysis
    root. Rewriting the marker's scope during promotion would silently change a
    stored financial contract, so the analyst changes it (under a new position
    id, because scope is part of a position's identity) or removes it first."""

    for label, structure in _every_capital_structure(connection, investment_id):
        for position in structure.positions:
            if (
                position.position_class is PositionClass.COMMON_EQUITY
                and position.scope.kind is ScopeKind.UNIT
            ):
                raise InvestmentStructureError(
                    f"{label} names the Common Equity residual with position "
                    f"{position.name!r} ({position.position_id}), scoped to Unit "
                    f"{position.scope.unit_id!r}. A visible Investment's residual is the "
                    "Investment's own, so that structure would no longer execute after "
                    "promotion. Give the marker Investment scope under a new position id, or "
                    "remove it, first; promotion never rewrites a stored structure."
                )


def _capital_structure_references(
    connection: sqlite3.Connection, investment_id: str, unit_id: str
) -> list[str]:
    """Every stored Capital Structure position of this Investment whose scope
    names ``unit_id``, named by its own display name and its structure's -- never
    by an opaque id, because the analyst has to know which position to change."""

    names = {
        row["id"]: row["name"]
        for row in connection.execute(
            "SELECT id, name FROM strategies WHERE investment_id = ?", (investment_id,)
        )
    }
    references: list[str] = []
    for row in connection.execute(
        """
        SELECT cs.owner_kind, cs.owner_id, cp.name, cp.position_id
        FROM capital_structures cs
        JOIN capital_positions cp ON cp.structure_id = cs.structure_id
        WHERE cs.investment_id = ? AND cp.scope_unit_id = ?
        ORDER BY cs.owner_kind, cs.owner_id, cp.position_id
        """,
        (investment_id, unit_id),
    ):
        owner = (
            "the Base Capital Structure"
            if row["owner_kind"] == _BASE_OWNER_KIND
            else f"Strategy {names.get(row['owner_id'], row['owner_id'])!r}'s Capital Structure"
        )
        references.append(f"Capital Structure position {row['name']!r} in {owner}")
    return references


def _require_deal_wrapper(connection: sqlite3.Connection, deal_id: str) -> str | None:
    """The hidden wrapper ``deal_id`` belongs to, or ``None`` for a standalone
    Deal. A Unit of a visible Investment is refused: that Investment's Capital
    Structure is the Investment's own, and a Unit never holds a second one."""

    investment_id = _investment_of_deal(connection, deal_id)
    if investment_id is None:
        return None
    if not _decode_hidden_flag(_investment_row(connection, investment_id)):
        raise InvestmentStructureError(
            f"Deal {deal_id!r} is a Unit of a visible Investment, which owns the Capital "
            "Structure for every one of its Units. Edit the Investment's Capital Structure; a "
            "Unit never holds a second one."
        )
    _require_hidden_wrapper(connection, investment_id)
    return investment_id


def get_base_capital_structure(
    investment_id: str, *, db_path: Path | None = None
) -> CapitalStructure:
    """The Investment's Base Capital Structure -- the neutral empty structure
    when it states none. Read-only: reading one creates nothing."""

    with _connect(db_path) as connection:
        _require_structure_owner(connection, investment_id)
        stored = _stored_capital_structure(
            connection, _BASE_OWNER_KIND, investment_id, where="The Base Capital Structure"
        )
    return CapitalStructure(positions=()) if stored is None else stored


def set_base_capital_structure(
    investment_id: str,
    capital_structure: CapitalStructure,
    *,
    db_path: Path | None = None,
) -> CapitalStructure:
    """Replace the Investment's Base Capital Structure whole.

    One transaction: the structure validates against this Investment's Units,
    its position identities agree with every other structure the Investment
    holds, and then the previous structure and the new one are swapped. An empty
    structure clears it, leaving no marker and no row. A hidden wrapper that is
    left holding no structure at all -- no Scenario, no Strategy and no Capital
    Structure -- is removed with it, and its Deal is a plain standalone Deal
    again (P-11)."""

    now = _utc_now_iso()
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        structure = _require_valid_capital_structure(
            capital_structure, member_unit_ids=owner.unit_modes
        )
        _require_coherent_identity(
            connection,
            investment_id,
            owner_kind=_BASE_OWNER_KIND,
            owner_id=investment_id,
            capital_structure=structure,
        )
        _replace_capital_structure(
            connection,
            investment_id=investment_id,
            owner_kind=_BASE_OWNER_KIND,
            owner_id=investment_id,
            capital_structure=structure,
        )
        if owner.hidden and _wrapper_holds_no_structure(connection, investment_id):
            _delete_investment_rows(connection, investment_id)
        else:
            _touch_investment(connection, investment_id, now=now)
    return structure


def read_deal_capital_structure(
    deal_id: str, *, db_path: Path | None = None
) -> tuple[str | None, CapitalStructure]:
    """The Deal's Base Capital Structure and the hidden Investment that owns it
    -- or ``(None, the empty structure)`` for a standalone Deal.

    Read-only, and it materializes nothing: asking a Deal what structured
    capital it has never gives it an Investment."""

    with _connect(db_path) as connection:
        if _operating_mode_of(connection, deal_id) is None:
            raise DealNotFoundError(deal_id)
        investment_id = _require_deal_wrapper(connection, deal_id)
        if investment_id is None:
            return None, CapitalStructure(positions=())
        stored = _stored_capital_structure(
            connection, _BASE_OWNER_KIND, investment_id, where="The Base Capital Structure"
        )
    return investment_id, CapitalStructure(positions=()) if stored is None else stored


def set_deal_capital_structure(
    deal_id: str,
    capital_structure: CapitalStructure,
    *,
    db_path: Path | None = None,
) -> tuple[str | None, CapitalStructure]:
    """Replace the Deal's Base Capital Structure, materializing its hidden
    one-unit Investment on the first non-empty save (Q4).

    One transaction. An empty structure for a Deal that has no Investment
    creates nothing at all -- there is nothing to store and no wrapper to
    materialize -- and an empty structure that empties an existing wrapper
    removes the wrapper when no Scenario and no Strategy is left. The UI keeps
    saying "Deal" throughout: a hidden wrapper is storage, never chrome."""

    now = _utc_now_iso()
    with _connect(db_path) as connection:
        operating_mode = _operating_mode_of(connection, deal_id)
        if operating_mode is None:
            raise DealNotFoundError(deal_id)
        investment_id = _require_deal_wrapper(connection, deal_id)
        structure = _require_valid_capital_structure(
            capital_structure, member_unit_ids=(deal_id,)
        )
        if investment_id is None:
            if not structure.positions:
                return None, structure
            investment_id = _materialize_hidden_investment(connection, deal_id, now=now)
        _require_coherent_identity(
            connection,
            investment_id,
            owner_kind=_BASE_OWNER_KIND,
            owner_id=investment_id,
            capital_structure=structure,
        )
        _replace_capital_structure(
            connection,
            investment_id=investment_id,
            owner_kind=_BASE_OWNER_KIND,
            owner_id=investment_id,
            capital_structure=structure,
        )
        if _wrapper_holds_no_structure(connection, investment_id):
            _delete_investment_rows(connection, investment_id)
            return None, structure
        _touch_investment(connection, investment_id, now=now)
    return investment_id, structure


def list_investment_capital_structures(
    investment_id: str, *, db_path: Path | None = None
) -> InvestmentCapitalStructures:
    """Every Capital Structure the Investment holds: its Base structure and each
    Strategy's own replacement, with the Strategies that state none simply
    absent. Read-only.

    This is what the Position perspectives, the structured fingerprints and the
    Position Decision Matrix read: one coherent view of everything authored,
    never one structure at a time."""

    with _connect(db_path) as connection:
        _require_structure_owner(connection, investment_id)
        base = _stored_capital_structure(
            connection, _BASE_OWNER_KIND, investment_id, where="The Base Capital Structure"
        )
        strategies = tuple(
            StrategyCapitalStructure(strategy_id=strategy_id, name=name, capital_structure=structure)
            for strategy_id, name, structure in _strategy_capital_structures(
                connection, investment_id
            )
        )
    return InvestmentCapitalStructures(
        investment_id=investment_id,
        base=CapitalStructure(positions=()) if base is None else base,
        strategies=strategies,
    )


def remove_investment_unit(
    investment_id: str,
    unit_id: str,
    *,
    transaction_price: float | None = None,
    db_path: Path | None = None,
) -> VisibleInvestment:
    """Remove the Unit ``unit_id`` from the visible Investment, releasing its
    Deal -- which is neither deleted nor changed -- to standalone.

    The Investment that remains must be a valid Base when the transaction
    commits: its remaining Units share one timeline and reconcile to the
    resulting transaction price. That price is ``transaction_price`` when the
    request restates it, and the current price otherwise. Nothing is derived --
    removing a Unit never subtracts its price -- so a removal that leaves the
    old price unreconciled is refused (``ALLOCATION_MISMATCH``) until the
    caller restates the price in the same request. Restating it first, or
    removing first and repairing later, would each commit an invalid state.

    Also refused while a persisted Scenario override or Strategy overlay
    addresses the Unit (those are never silently edited), and for the
    Investment's last Unit (delete the Investment to release every Unit). The
    Investment stays visible, even with one Unit.

    One transaction: every check runs before any write; then the membership and
    its Unit details are deleted, a restated price is written, and the
    Investment's variant cache rows are deleted. Any failure rolls all of it
    back."""

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
        remaining = tuple(membership for membership in current.units if membership.unit_id != unit_id)
        price = current.transaction_price if transaction_price is None else transaction_price
        _require_valid_investment_inputs(
            name=current.name,
            transaction_price=price,
            memberships=remaining,
            business_plan=current.business_plan,
            transaction_costs=current.transaction_costs,
        )
        _require_reconciled_base(connection, remaining, price)
        connection.execute(
            "DELETE FROM investment_units WHERE investment_id = ? AND deal_id = ?",
            (investment_id, unit_id),
        )
        connection.execute(
            "DELETE FROM investment_unit_details WHERE investment_id = ? AND unit_id = ?",
            (investment_id, unit_id),
        )
        if transaction_price is not None:
            _write_visible_details(
                connection, investment_id, name=current.name, transaction_price=transaction_price
            )
        connection.execute("DELETE FROM variant_snapshots WHERE root_id = ?", (investment_id,))
        _touch_investment(connection, investment_id, now=now)

    return get_visible_investment(investment_id, db_path=db_path)


# =============================================================================
# Phase 7 Gate P7.9 Stage 2 -- Partnership persistence
#
# Read, written and deleted only here. Every read rebuilds the exact Stage 1
# ``Partnership`` contract and runs the Stage 1 validator on it; nothing is
# repaired, defaulted or dropped. Nothing here computes anything: the
# Partnership economics are ``anchor.partnership``'s, reached only through
# ``anchor.deals.partnership_variants``.
# =============================================================================


def _partnership_owner_row(
    connection: sqlite3.Connection, owner_kind: str, owner_id: str
) -> sqlite3.Row | None:
    """The Partnership row one owner states, or ``None`` -- the marker itself.

    ``None`` for a ``base`` owner means the Investment has no Base Partnership.
    ``None`` for a ``strategy`` owner means that Strategy inherits the Base
    Partnership, which is a different answer from a row with
    ``has_partnership = 0`` (an explicit "no Partnership")."""

    return connection.execute(
        "SELECT * FROM partnerships WHERE owner_kind = ? AND owner_id = ?",
        (owner_kind, owner_id),
    ).fetchone()


def _partnership_token(value: object, enum_type: type, *, path: str) -> Any:
    """A stored Partnership token as its authoritative member, strictly: a
    missing token or one the enum no longer recognises is corrupt."""

    if value is None:
        raise PersistedPartnershipDataError(
            f"{path} is missing; the Partnership contract states it explicitly."
        )
    try:
        return _decode_enum(value, enum_type, path=path)
    except PersistedDealDataError as error:
        raise PersistedPartnershipDataError(str(error)) from None


def _require_columns(
    row: sqlite3.Row, *, stated: tuple[str, ...], absent: tuple[str, ...], where: str
) -> None:
    """``row`` states exactly the ``stated`` columns of this variant and leaves
    every ``absent`` one ``NULL``. Anything else disagrees with its own token."""

    wrong = sorted(
        [name for name in stated if row[name] is None]
        + [name for name in absent if row[name] is not None]
    )
    if wrong:
        raise PersistedPartnershipDataError(
            f"{where} states columns that disagree with its kind: {', '.join(wrong)}."
        )


def _rows_by(rows: Iterable[sqlite3.Row], key: str) -> dict[str, list[sqlite3.Row]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(row)
    return grouped


def _split_from_rows(
    tier_row: sqlite3.Row, split_rows: list[sqlite3.Row], *, where: str
) -> TierSplit:
    rule = _partnership_token(tier_row["split_rule"], SplitRule, path=f"{where} split_rule")
    if rule is SplitRule.EXPLICIT:
        return ExplicitSplit(
            shares=tuple(
                SplitShare(partner_id=row["partner_id"], share=row["share"]) for row in split_rows
            )
        )
    if split_rows:
        raise PersistedPartnershipDataError(
            f"{where} splits pro rata by contribution and also holds split share rows."
        )
    return ProRataByContribution()


def _condition_from_row(row: sqlite3.Row, *, where: str) -> HurdleCondition:
    located = f"{where} condition {row['condition_id']!r}"
    kind = _partnership_token(row["condition_kind"], HurdleConditionKind, path=f"{located} kind")
    if kind is HurdleConditionKind.IRR:
        _require_columns(
            row, stated=("rate", "accrual_convention"), absent=("multiple",), where=located
        )
        order = row["simple_distribution_order"]
        return IrrHurdle(
            condition_id=row["condition_id"],
            rate=row["rate"],
            accrual_convention=_partnership_token(
                row["accrual_convention"], AccrualConvention, path=f"{located} accrual_convention"
            ),
            simple_distribution_order=None
            if order is None
            else _partnership_token(
                order, SimpleDistributionOrder, path=f"{located} simple_distribution_order"
            ),
        )
    _require_columns(
        row,
        stated=("multiple",),
        absent=("rate", "accrual_convention", "simple_distribution_order"),
        where=located,
    )
    return MoicHurdle(condition_id=row["condition_id"], multiple=row["multiple"])


_SUBJECT_COLUMNS = ("subject_partner_id", "subject_investor_class", "subject_account")

_SUBJECT_COLUMN = {
    HurdleSubjectKind.PARTNER: "subject_partner_id",
    HurdleSubjectKind.INVESTOR_CLASS: "subject_investor_class",
    HurdleSubjectKind.ECONOMIC_ACCOUNT: "subject_account",
}


def _hurdle_from_rows(
    tier_row: sqlite3.Row, condition_rows: list[sqlite3.Row], *, where: str
) -> HurdleTerms:
    kind = _partnership_token(
        tier_row["subject_kind"], HurdleSubjectKind, path=f"{where} subject_kind"
    )
    column = _SUBJECT_COLUMN[kind]
    _require_columns(
        tier_row,
        stated=(column,),
        absent=tuple(name for name in _SUBJECT_COLUMNS if name != column),
        where=f"{where} hurdle subject",
    )
    return HurdleTerms(
        hurdle_subject=HurdleSubject(
            kind=kind,
            partner_id=tier_row["subject_partner_id"],
            investor_class=tier_row["subject_investor_class"],
            account=None
            if tier_row["subject_account"] is None
            else _partnership_token(
                tier_row["subject_account"], EconomicAccount, path=f"{where} subject_account"
            ),
        ),
        conditions=tuple(_condition_from_row(row, where=where) for row in condition_rows),
        combinator=_partnership_token(
            tier_row["combinator"], HurdleCombinator, path=f"{where} combinator"
        ),
    )


def _catch_up_from_row(row: sqlite3.Row, *, where: str) -> CatchUpTerms:
    located = f"{where} catch-up recipient"
    kind = _partnership_token(row["recipient_kind"], CatchUpRecipientKind, path=f"{located} kind")
    stated = (
        "recipient_partner_id"
        if kind is CatchUpRecipientKind.PARTNER
        else "recipient_investor_class"
    )
    _require_columns(
        row,
        stated=(stated,),
        absent=tuple(
            name
            for name in ("recipient_partner_id", "recipient_investor_class")
            if name != stated
        ),
        where=located,
    )
    return CatchUpTerms(
        recipient=CatchUpRecipient(
            kind=kind,
            partner_id=row["recipient_partner_id"],
            investor_class=row["recipient_investor_class"],
        ),
        target_profit_share=row["target_profit_share"],
    )


def _tier_from_rows(
    tier_row: sqlite3.Row,
    split_rows: list[sqlite3.Row],
    condition_rows: list[sqlite3.Row],
    catch_up_rows: list[sqlite3.Row],
    *,
    where: str,
) -> WaterfallTier:
    """One stored tier as the exact contract. The kind decides which terms rows
    must exist, and exactly which: hurdle columns and conditions for a
    ``HURDLE``, one catch-up row for a ``CATCH_UP``, neither for the
    ``RESIDUAL``."""

    located = f"{where} tier {tier_row['tier_id']!r}"
    kind = _partnership_token(tier_row["kind"], TierKind, path=f"{located} kind")
    hurdle: HurdleTerms | None = None
    catch_up: CatchUpTerms | None = None
    if kind is TierKind.HURDLE:
        _require_columns(tier_row, stated=("subject_kind", "combinator"), absent=(), where=located)
        hurdle = _hurdle_from_rows(tier_row, condition_rows, where=located)
    else:
        _require_columns(
            tier_row,
            stated=(),
            absent=("subject_kind", *_SUBJECT_COLUMNS, "combinator"),
            where=located,
        )
        if condition_rows:
            raise PersistedPartnershipDataError(
                f"{located} is {kind.value} and holds hurdle condition rows."
            )
    if kind is TierKind.CATCH_UP:
        if len(catch_up_rows) != 1:
            raise PersistedPartnershipDataError(
                f"{located} is a catch-up tier and holds {len(catch_up_rows)} catch-up rows; it "
                "holds exactly one."
            )
        catch_up = _catch_up_from_row(catch_up_rows[0], where=located)
    elif catch_up_rows:
        raise PersistedPartnershipDataError(f"{located} is {kind.value} and holds catch-up rows.")
    return WaterfallTier(
        tier_id=tier_row["tier_id"],
        name=tier_row["name"],
        sequence=tier_row["sequence"],
        kind=kind,
        split=_split_from_rows(tier_row, split_rows, where=located),
        hurdle=hurdle,
        catch_up=catch_up,
    )


#: The row order each child table is read in: the analyst's authored order
#: (``ordinal``), with the stable id making it total.
_PARTNERSHIP_CHILD_ORDER = {
    "partners": "ordinal, partner_id",
    "partnership_benchmark_shares": "ordinal, partner_id",
    "partnership_promote_participants": "ordinal, partner_id",
    "waterfall_tier_splits": "tier_id, ordinal, partner_id",
    "waterfall_hurdle_conditions": "tier_id, ordinal, condition_id",
    "waterfall_catch_up_terms": "tier_id",
    "waterfall_tiers": "ordinal, tier_id",
}


def _partnership_children(
    connection: sqlite3.Connection, partnership_id: str
) -> dict[str, list[sqlite3.Row]]:
    return {
        table: connection.execute(
            f"SELECT * FROM {table} WHERE partnership_id = ? "
            f"ORDER BY {_PARTNERSHIP_CHILD_ORDER[table]}",
            (partnership_id,),
        ).fetchall()
        for table in _PARTNERSHIP_CHILD_TABLES
    }


def _read_explicit_none(
    row: sqlite3.Row, children: Mapping[str, list[sqlite3.Row]], *, where: str
) -> None:
    """Check an explicit "no Partnership" marker: a Strategy's, stating no
    terms and owning no row."""

    if row["owner_kind"] != _STRATEGY_OWNER_KIND:
        raise PersistedPartnershipDataError(
            f"{where} holds a Base 'no Partnership' marker. Clearing the Base Partnership "
            "removes its marker, so one is never stored; 'no Partnership' is a Strategy's "
            "explicit replacement, never a Base."
        )
    stated = [
        name for name in ("contribution_rule", "promote_participant_count") if row[name] is not None
    ]
    populated = [table for table, rows in children.items() if rows]
    if stated or populated:
        raise PersistedPartnershipDataError(
            f"{where} is a 'no Partnership' marker and also holds "
            f"{', '.join([*stated, *populated])}."
        )


def _read_participant_ids(
    row: sqlite3.Row, participant_rows: list[sqlite3.Row], *, where: str
) -> tuple[str, ...]:
    """The stated promote participants. ``NULL`` is a missing set, never the
    confirmed empty one, and a count that disagrees with the rows is corrupt."""

    count = row["promote_participant_count"]
    if count is None:
        raise PersistedPartnershipDataError(
            f"{where} holds no promote-participant count, so its participant set is missing. "
            "A missing set is never read as the explicitly empty one."
        )
    if isinstance(count, bool) or not isinstance(count, int) or count != len(participant_rows):
        raise PersistedPartnershipDataError(
            f"{where} states {count!r} promote participant(s) and holds "
            f"{len(participant_rows)} participant row(s)."
        )
    return tuple(participant["partner_id"] for participant in participant_rows)


def _read_partnership(
    connection: sqlite3.Connection, row: sqlite3.Row, *, where: str
) -> Partnership | None:
    """The Partnership one marker row states -- or ``None`` for an explicit
    "no Partnership" marker -- rebuilt strictly and refused if the Stage 1
    validator refuses it.

    Lists come back in the analyst's authored order (``ordinal``), which is
    presentation: every consumer orders by the canonical keys."""

    children = _partnership_children(connection, row["partnership_id"])
    flag = row["has_partnership"]
    if isinstance(flag, bool) or flag not in (0, 1):
        raise PersistedPartnershipDataError(
            f"{where} holds has_partnership={flag!r}; it must be 0 or 1."
        )
    if flag == 0:
        _read_explicit_none(row, children, where=where)
        return None

    participant_ids = _read_participant_ids(
        row, children["partnership_promote_participants"], where=where
    )
    tier_rows = children["waterfall_tiers"]
    tier_ids = {tier["tier_id"] for tier in tier_rows}
    splits = _rows_by(children["waterfall_tier_splits"], "tier_id")
    conditions = _rows_by(children["waterfall_hurdle_conditions"], "tier_id")
    catch_ups = _rows_by(children["waterfall_catch_up_terms"], "tier_id")
    orphaned = sorted((set(splits) | set(conditions) | set(catch_ups)) - tier_ids)
    if orphaned:
        raise PersistedPartnershipDataError(
            f"{where} holds split, condition or catch-up rows for tier(s) "
            f"{', '.join(orphaned)}, which it does not hold; a child row never implies a tier."
        )

    partnership = Partnership(
        partners=tuple(
            Partner(
                partner_id=partner["partner_id"],
                name=partner["name"],
                role=_partnership_token(
                    partner["role"],
                    PartnerRole,
                    path=f"{where} partner {partner['partner_id']!r} role",
                ),
                investor_class=partner["investor_class"],
                commitment_share=partner["commitment_share"],
            )
            for partner in children["partners"]
        ),
        contribution_rule=_partnership_token(
            row["contribution_rule"], ContributionRule, path=f"{where} contribution_rule"
        ),
        promote_benchmark=PromoteBenchmark(
            shares=tuple(
                BenchmarkShare(partner_id=share["partner_id"], share=share["share"])
                for share in children["partnership_benchmark_shares"]
            )
        ),
        promote_participant_ids=participant_ids,
        tiers=tuple(
            _tier_from_rows(
                tier,
                splits.get(tier["tier_id"], []),
                conditions.get(tier["tier_id"], []),
                catch_ups.get(tier["tier_id"], []),
                where=where,
            )
            for tier in tier_rows
        ),
    )
    issues = validate_partnership(partnership)
    if issues:
        raise PersistedPartnershipDataError(
            f"{where} does not validate: " + "; ".join(issue.message for issue in issues)
        )
    return partnership


def _stored_partnership(
    connection: sqlite3.Connection, owner_kind: str, owner_id: str, *, where: str
) -> Partnership | NoPartnership | None:
    """What one owner states: its Partnership, ``NoPartnership()`` for an
    explicit "no Partnership" (a Strategy only), or ``None`` when it states
    nothing at all."""

    row = _partnership_owner_row(connection, owner_kind, owner_id)
    if row is None:
        return None
    partnership = _read_partnership(connection, row, where=where)
    return NoPartnership() if partnership is None else partnership


def _stored_base_partnership(
    connection: sqlite3.Connection, investment_id: str
) -> Partnership | None:
    """The Investment's Base Partnership, or ``None``. A Base marker can never
    read as ``NoPartnership``: ``_read_partnership`` refuses one."""

    stated = _stored_partnership(
        connection, _BASE_OWNER_KIND, investment_id, where="The Base Partnership"
    )
    return stated if isinstance(stated, Partnership) else None


def _write_partnership_terms(
    connection: sqlite3.Connection, partnership_id: str, partnership: Partnership
) -> None:
    """Every row under one stated Partnership, in the analyst's authored
    order."""

    connection.executemany(
        "INSERT INTO partners (partnership_id, partner_id, ordinal, name, role, investor_class, "
        "commitment_share) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                partnership_id,
                partner.partner_id,
                ordinal,
                partner.name,
                _encode_enum(partner.role),
                partner.investor_class,
                float(partner.commitment_share),
            )
            for ordinal, partner in enumerate(partnership.partners)
        ],
    )
    connection.executemany(
        "INSERT INTO partnership_benchmark_shares (partnership_id, partner_id, ordinal, share) "
        "VALUES (?, ?, ?, ?)",
        [
            (partnership_id, share.partner_id, ordinal, float(share.share))
            for ordinal, share in enumerate(partnership.promote_benchmark.shares)
        ],
    )
    connection.executemany(
        "INSERT INTO partnership_promote_participants (partnership_id, partner_id, ordinal) "
        "VALUES (?, ?, ?)",
        [
            (partnership_id, partner_id, ordinal)
            for ordinal, partner_id in enumerate(partnership.promote_participant_ids)
        ],
    )
    for ordinal, tier in enumerate(partnership.tiers):
        _write_tier(connection, partnership_id, ordinal, tier)


def _write_tier(
    connection: sqlite3.Connection, partnership_id: str, ordinal: int, tier: WaterfallTier
) -> None:
    """One tier: its row (split rule, hurdle subject and combinator), then its
    split shares, hurdle conditions and catch-up terms."""

    subject = None if tier.hurdle is None else tier.hurdle.hurdle_subject
    connection.execute(
        "INSERT INTO waterfall_tiers (partnership_id, tier_id, ordinal, name, sequence, kind, "
        "split_rule, subject_kind, subject_partner_id, subject_investor_class, "
        "subject_account, combinator) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            partnership_id,
            tier.tier_id,
            ordinal,
            tier.name,
            int(tier.sequence),
            _encode_enum(tier.kind),
            split_rule_kind(tier.split).value,
            None if subject is None else _encode_enum(subject.kind),
            None if subject is None else subject.partner_id,
            None if subject is None else subject.investor_class,
            None if subject is None else _encode_enum(subject.account),
            None if tier.hurdle is None else _encode_enum(tier.hurdle.combinator),
        ),
    )
    if isinstance(tier.split, ExplicitSplit):
        connection.executemany(
            "INSERT INTO waterfall_tier_splits (partnership_id, tier_id, partner_id, ordinal, "
            "share) VALUES (?, ?, ?, ?, ?)",
            [
                (partnership_id, tier.tier_id, share.partner_id, index, float(share.share))
                for index, share in enumerate(tier.split.shares)
            ],
        )
    if tier.hurdle is not None:
        connection.executemany(
            "INSERT INTO waterfall_hurdle_conditions (partnership_id, tier_id, condition_id, "
            "ordinal, condition_kind, rate, accrual_convention, simple_distribution_order, "
            "multiple) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                _condition_row(partnership_id, tier.tier_id, index, condition)
                for index, condition in enumerate(tier.hurdle.conditions)
            ],
        )
    if tier.catch_up is not None:
        recipient = tier.catch_up.recipient
        connection.execute(
            "INSERT INTO waterfall_catch_up_terms (partnership_id, tier_id, recipient_kind, "
            "recipient_partner_id, recipient_investor_class, target_profit_share) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                partnership_id,
                tier.tier_id,
                _encode_enum(recipient.kind),
                recipient.partner_id,
                recipient.investor_class,
                float(tier.catch_up.target_profit_share),
            ),
        )


def _condition_row(
    partnership_id: str, tier_id: str, ordinal: int, condition: HurdleCondition
) -> tuple[object, ...]:
    """One condition's row under its codec token: exactly the columns its
    variant has, and ``NULL`` for the others."""

    kind = condition_kind(condition).value
    if isinstance(condition, IrrHurdle):
        return (
            partnership_id,
            tier_id,
            condition.condition_id,
            ordinal,
            kind,
            float(condition.rate),
            _encode_enum(condition.accrual_convention),
            _encode_enum(condition.simple_distribution_order),
            None,
        )
    return (
        partnership_id,
        tier_id,
        condition.condition_id,
        ordinal,
        kind,
        None,
        None,
        None,
        float(condition.multiple),
    )


def _write_partnership(
    connection: sqlite3.Connection,
    *,
    investment_id: str,
    owner_kind: str,
    owner_id: str,
    partnership: Partnership | None,
) -> None:
    """One owner's whole Partnership statement: its marker and, for a stated
    Partnership, every row under it. ``None`` writes the explicit
    "no Partnership" marker alone.

    Called inside the caller's transaction, after validation, and after any
    previous statement of this owner was removed: a Partnership is replaced
    whole, never diffed. The participant count is written beside the rows, so
    the confirmed empty set is stated rather than implied."""

    partnership_id = uuid.uuid4().hex
    connection.execute(
        "INSERT INTO partnerships (partnership_id, investment_id, owner_kind, owner_id, "
        "has_partnership, contribution_rule, promote_participant_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            partnership_id,
            investment_id,
            owner_kind,
            owner_id,
            0 if partnership is None else 1,
            None if partnership is None else _encode_enum(partnership.contribution_rule),
            None if partnership is None else len(partnership.promote_participant_ids),
        ),
    )
    if partnership is not None:
        _write_partnership_terms(connection, partnership_id, partnership)


def _delete_partnership(connection: sqlite3.Connection, owner_kind: str, owner_id: str) -> None:
    """One owner's Partnership statement and every row it owns. Deleting
    nothing is ordinary: most owners state no Partnership."""

    row = _partnership_owner_row(connection, owner_kind, owner_id)
    if row is None:
        return
    partnership_id = row["partnership_id"]
    for table in _PARTNERSHIP_CHILD_TABLES:
        connection.execute(f"DELETE FROM {table} WHERE partnership_id = ?", (partnership_id,))
    connection.execute("DELETE FROM partnerships WHERE partnership_id = ?", (partnership_id,))


def _delete_investment_partnerships(connection: sqlite3.Connection, investment_id: str) -> None:
    """Every Partnership statement the Investment owns -- its Base Partnership
    and each Strategy's own -- with every row under them."""

    for table in _PARTNERSHIP_CHILD_TABLES:
        connection.execute(
            f"DELETE FROM {table} WHERE partnership_id IN "
            "(SELECT partnership_id FROM partnerships WHERE investment_id = ?)",
            (investment_id,),
        )
    connection.execute("DELETE FROM partnerships WHERE investment_id = ?", (investment_id,))


def _strategy_partnerships(
    connection: sqlite3.Connection, investment_id: str
) -> list[tuple[str, str, Partnership | None]]:
    """``(strategy_id, name, partnership)`` for every Strategy of the Investment
    that states its own Partnership, in creation order -- ``partnership`` is
    ``None`` for an explicit "no Partnership". A Strategy that inherits the Base
    Partnership is simply absent."""

    stated: list[tuple[str, str, Partnership | None]] = []
    for row in connection.execute(
        "SELECT id, name FROM strategies WHERE investment_id = ? ORDER BY created_at, rowid",
        (investment_id,),
    ).fetchall():
        own = _stored_partnership(
            connection,
            _STRATEGY_OWNER_KIND,
            row["id"],
            where=f"Strategy {row['id']!r}'s Partnership",
        )
        if own is not None:
            stated.append((row["id"], row["name"], own if isinstance(own, Partnership) else None))
    return stated


def _require_valid_partnership(partnership: object) -> Partnership:
    """The Stage 1 structural authority on a Partnership about to be stored.
    This store adds no rule of its own; whether it executes over a variant's
    Common Equity Cash Flow is the variant's question."""

    issues = validate_partnership(partnership)
    if issues:
        raise PartnershipValidationError(issues)
    assert isinstance(partnership, Partnership)
    return partnership


def _write_strategy_partnership(
    connection: sqlite3.Connection, investment_id: str, strategy: StrategyDefinition
) -> None:
    """The Strategy's own Partnership statement, when it states one. The marker
    is written even for ``NoPartnership``, because that is precisely what it
    distinguishes from inheritance."""

    own = strategy_partnership(strategy)
    if own is None:
        return
    _write_partnership(
        connection,
        investment_id=investment_id,
        owner_kind=_STRATEGY_OWNER_KIND,
        owner_id=strategy.strategy_id,
        partnership=own if isinstance(own, Partnership) else None,
    )


def _with_strategy_partnership(
    connection: sqlite3.Connection, strategy: StrategyDefinition
) -> StrategyDefinition:
    """``strategy`` with its stored Partnership statement appended to its root
    overlays, after the Capital Structure (declaration order). A Strategy that
    states none is returned unchanged: it inherits."""

    own = _stored_partnership(
        connection,
        _STRATEGY_OWNER_KIND,
        strategy.strategy_id,
        where=f"Strategy {strategy.strategy_id!r}'s Partnership",
    )
    if own is None:
        return strategy
    return dataclasses.replace(
        strategy,
        root_overlays=(
            *strategy.root_overlays,
            InvestmentStrategyOverlay(domain=StrategyDomain.PARTNERSHIP, content=own),
        ),
    )


def _require_partnership_deal_wrapper(connection: sqlite3.Connection, deal_id: str) -> str | None:
    """The hidden wrapper ``deal_id`` belongs to, or ``None`` for a standalone
    Deal. A Unit of a visible Investment is refused: the Partnership allocates
    the Investment's Common Equity, never one Unit's."""

    investment_id = _investment_of_deal(connection, deal_id)
    if investment_id is None:
        return None
    if not _decode_hidden_flag(_investment_row(connection, investment_id)):
        raise InvestmentStructureError(
            f"Deal {deal_id!r} is a Unit of a visible Investment, whose Partnership allocates the "
            "Investment's Common Equity. Edit the Investment's Partnership; a Unit never holds "
            "one of its own."
        )
    _require_hidden_wrapper(connection, investment_id)
    return investment_id


def _replace_base_partnership(
    connection: sqlite3.Connection, investment_id: str, partnership: Partnership | None
) -> None:
    """Whole atomic replacement of the Base Partnership: the previous statement
    and every row under it go, then the new one is written. ``None`` leaves no
    marker at all."""

    _delete_partnership(connection, _BASE_OWNER_KIND, investment_id)
    if partnership is not None:
        _write_partnership(
            connection,
            investment_id=investment_id,
            owner_kind=_BASE_OWNER_KIND,
            owner_id=investment_id,
            partnership=partnership,
        )


def get_base_partnership(investment_id: str, *, db_path: Path | None = None) -> Partnership | None:
    """The Investment's Base Partnership, or ``None`` when it states none.
    Read-only: reading one creates nothing."""

    with _connect(db_path) as connection:
        _require_structure_owner(connection, investment_id)
        return _stored_base_partnership(connection, investment_id)


def set_base_partnership(
    investment_id: str, partnership: Partnership | None, *, db_path: Path | None = None
) -> Partnership | None:
    """Replace the Investment's Base Partnership whole; ``None`` clears it.

    One transaction: the Partnership validates, and the previous and new
    statements are swapped. A ``partner_id`` is the partner's stable identity
    (P-8); its name and role are presentation and may differ from the Base
    Partnership's or another Strategy's. A hidden wrapper left holding no
    structure at all is removed with it, and its Deal is a plain standalone
    Deal again (P-11)."""

    now = _utc_now_iso()
    with _connect(db_path) as connection:
        owner = _require_structure_owner(connection, investment_id)
        stated = None if partnership is None else _require_valid_partnership(partnership)
        _replace_base_partnership(connection, investment_id, stated)
        if owner.hidden and _wrapper_holds_no_structure(connection, investment_id):
            _delete_investment_rows(connection, investment_id)
        else:
            _touch_investment(connection, investment_id, now=now)
    return stated


def read_deal_partnership(
    deal_id: str, *, db_path: Path | None = None
) -> tuple[str | None, Partnership | None]:
    """The Deal's Base Partnership and the hidden Investment that owns it -- or
    ``(None, None)`` for a standalone Deal. Read-only; it materializes
    nothing."""

    with _connect(db_path) as connection:
        if _operating_mode_of(connection, deal_id) is None:
            raise DealNotFoundError(deal_id)
        investment_id = _require_partnership_deal_wrapper(connection, deal_id)
        if investment_id is None:
            return None, None
        return investment_id, _stored_base_partnership(connection, investment_id)


def set_deal_partnership(
    deal_id: str, partnership: Partnership | None, *, db_path: Path | None = None
) -> tuple[str | None, Partnership | None]:
    """Replace the Deal's Base Partnership, materializing its hidden one-unit
    Investment on the first save of a Partnership (Q4).

    One transaction. Clearing a Deal that has no Investment creates nothing, and
    clearing one that leaves the wrapper holding no structure removes the
    wrapper. The UI keeps saying "Deal" throughout."""

    now = _utc_now_iso()
    with _connect(db_path) as connection:
        if _operating_mode_of(connection, deal_id) is None:
            raise DealNotFoundError(deal_id)
        investment_id = _require_partnership_deal_wrapper(connection, deal_id)
        stated = None if partnership is None else _require_valid_partnership(partnership)
        if investment_id is None:
            if stated is None:
                return None, None
            investment_id = _materialize_hidden_investment(connection, deal_id, now=now)
        _replace_base_partnership(connection, investment_id, stated)
        if _wrapper_holds_no_structure(connection, investment_id):
            _delete_investment_rows(connection, investment_id)
            return None, stated
        _touch_investment(connection, investment_id, now=now)
    return investment_id, stated


def list_investment_partnerships(
    investment_id: str, *, db_path: Path | None = None
) -> InvestmentPartnerships:
    """Every Partnership statement the Investment holds: its Base Partnership
    and each Strategy's own, with inheriting Strategies simply absent.
    Read-only. The Partner perspectives, the Partnership fingerprints and the
    Partner Decision Matrix read this one coherent view."""

    with _connect(db_path) as connection:
        _require_structure_owner(connection, investment_id)
        base = _stored_base_partnership(connection, investment_id)
        strategies = tuple(
            StrategyPartnership(strategy_id=strategy_id, name=name, partnership=stated)
            for strategy_id, name, stated in _strategy_partnerships(connection, investment_id)
        )
    return InvestmentPartnerships(investment_id=investment_id, base=base, strategies=strategies)


# =============================================================================
# Gate AM1 -- the Managed Asset and Monthly Asset Report lifecycle.
#
# ``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`` Sections 2, 3
# and 5. The bounded deletion extension removes a Managed Asset and its owned
# reports in one transaction. It never deletes or mutates the source Deal, and
# there remains no independent report-deletion path.
#
# Nothing in this section performs a financial calculation or imports a module
# that does. Reads return stored figures; every total, variance and assessment
# is derived by ``anchor.asset_management.performance`` above the store.
# =============================================================================


def _deal_analysis_fingerprint(connection: sqlite3.Connection, deal_id: str) -> str:
    """The canonical analysis fingerprint of ``deal_id`` **as it is currently
    stored**, in whichever mode actually holds it.

    Calls exactly the same three ``fingerprint_*`` functions the read and
    snapshot-write paths call, over the same contracts, so a Managed Asset's
    frozen acquisition basis is certified against the identical definition of
    "these assumptions" that the rest of Anchor already uses -- never a second,
    AM1-private notion of what a Deal fingerprints to.

    Raises ``DealNotFoundError`` if the deal is in none of the three tables.
    """

    quick_row = connection.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
    if quick_row is not None:
        return fingerprint_quick_inputs(
            _inputs_from_row(quick_row),
            business_plan=_read_business_plan(connection, deal_id),
        )

    detailed_row = connection.execute(
        "SELECT * FROM detailed_deals WHERE id = ?", (deal_id,)
    ).fetchone()
    if detailed_row is not None:
        operating_row = connection.execute(
            "SELECT * FROM detailed_operating_inputs WHERE deal_id = ?", (deal_id,)
        ).fetchone()
        if operating_row is None:
            raise DealNotFoundError(deal_id)
        return fingerprint_detailed_inputs(
            _terms_from_row(detailed_row),
            _detailed_operating_inputs_from_row(operating_row),
            business_plan=_read_business_plan(connection, deal_id),
        )

    lease_level_row = connection.execute(
        "SELECT * FROM lease_level_deals WHERE id = ?", (deal_id,)
    ).fetchone()
    if lease_level_row is None:
        raise DealNotFoundError(deal_id)
    return _lease_level_input_fingerprint(connection, lease_level_row)


def _figures_from_row(row: sqlite3.Row, prefix: str) -> OperatingFigures:
    """One statement, rebuilt from its twelve prefixed columns.

    Field-driven from ``_AM1_FIGURE_FIELDS``, exactly as the DDL and the write
    path are, so the three can never disagree about which columns exist.
    """

    return OperatingFigures(
        **{field: row[f"{prefix}_{field}"] for field in _AM1_FIGURE_FIELDS}  # type: ignore[arg-type]
    )


def _figure_values(figures: OperatingFigures, prefix: str) -> dict[str, float]:
    """One statement's twelve bind parameters, keyed by prefixed column name."""

    return {f"{prefix}_{field}": float(getattr(figures, field)) for field in _AM1_FIGURE_FIELDS}


def _row_to_managed_asset(row: sqlite3.Row) -> ManagedAsset:
    return ManagedAsset(
        id=row["id"],
        source_deal_id=row["source_deal_id"],
        name=row["name"],
        acquisition_date=date.fromisoformat(row["acquisition_date"]),
        property_type=row["property_type"],
        market=row["market"],
        acquisition_fingerprint=row["acquisition_fingerprint"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_monthly_report(row: sqlite3.Row) -> MonthlyAssetReport:
    return MonthlyAssetReport(
        managed_asset_id=row["managed_asset_id"],
        reporting_month=date.fromisoformat(row["reporting_month"]),
        budget=_figures_from_row(row, "budget"),
        actual=_figures_from_row(row, "actual"),
        commentary=row["commentary"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _require_managed_asset(connection: sqlite3.Connection, managed_asset_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM managed_assets WHERE id = ?", (managed_asset_id,)
    ).fetchone()
    if row is None:
        raise ManagedAssetNotFoundError(managed_asset_id)
    return row


def create_managed_asset(
    *,
    source_deal_id: str,
    name: str | None = None,
    acquisition_date: date,
    property_type: str | None = None,
    market: str | None = None,
    db_path: Path | None = None,
) -> ManagedAsset:
    """Create the Managed Asset for a saved Deal, once.

    ``name`` defaults to the Deal's own name -- a copy taken at creation, not a
    live reference. Renaming the Deal afterwards does not rename the asset, and
    renaming the asset does not rename the Deal.

    The Deal must have a **current** saved analysis, in every mode that can
    store one. ``_read_deal`` returns ``analysis_snapshot=None`` whenever the
    stored snapshot does not match the deal's currently-stored assumptions, so
    requiring it means an asset can only be created from an acquisition whose
    approved basis was actually computed from the assumptions on file. Refusing
    this is the point: an "approved basis" nobody has analyzed is not a basis.

    **Lease-Level is deliberately exempt from the snapshot check**, and this is
    a storage fact rather than a financial one: ``lease_level_deals`` has no
    ``analysis_snapshot`` column (D5.4 gave that family ``ai_snapshot`` only), so
    a Lease-Level deal *structurally cannot* carry a cached deterministic
    analysis. Applying the check to it would bar an entire operating mode from
    Asset Management as a side effect of an unrelated persistence gap, not
    because anything about its basis is less trustworthy. What AM1 actually
    freezes is the fingerprint, and ``_deal_analysis_fingerprint`` produces one
    from a Lease-Level deal's own stored rows exactly as it does for the other
    two modes. A saved Lease-Level deal therefore qualifies on the strength of
    the same evidence the other modes' snapshots stand on: assumptions that are
    on file and reassemble into the contracts the engine consumes.

    Raises ``DealNotFoundError`` if the Deal does not exist,
    ``InvestmentStructureError`` if it has no current analysis,
    ``ManagedAssetExistsError`` if it already has an asset, and
    ``AssetReportValidationError`` if the authored identity is invalid.
    """

    managed_asset_id = uuid.uuid4().hex
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        deal = _read_deal(connection, source_deal_id)
        if (
            deal.operating_mode is not OperatingMode.LEASE_LEVEL
            and deal.analysis_snapshot is None
        ):
            raise InvestmentStructureError(
                f"Deal {source_deal_id} has no current saved analysis. Analyze and "
                "save it before creating a Managed Asset, so the approved "
                "acquisition basis is the one actually on file."
            )
        existing = connection.execute(
            "SELECT id FROM managed_assets WHERE source_deal_id = ?", (source_deal_id,)
        ).fetchone()
        if existing is not None:
            raise ManagedAssetExistsError(
                source_deal_id=source_deal_id, managed_asset_id=existing["id"]
            )

        resolved_name = name if name is not None else deal.name
        require_valid_managed_asset(
            name=resolved_name,
            acquisition_date=acquisition_date,
            property_type=property_type,
            market=market,
        )
        # Captured once, here, and written by no other statement in this module.
        # A later Deal edit changes the Deal's current fingerprint and leaves
        # this frozen copy exactly as it is.
        fingerprint = _deal_analysis_fingerprint(connection, source_deal_id)
        connection.execute(
            """
            INSERT INTO managed_assets (
                id, source_deal_id, name, acquisition_date, property_type,
                market, acquisition_fingerprint, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                managed_asset_id,
                source_deal_id,
                resolved_name,
                acquisition_date.isoformat(),
                property_type,
                market,
                fingerprint,
                now,
                now,
            ),
        )
        row = _require_managed_asset(connection, managed_asset_id)
        return _row_to_managed_asset(row)


def list_managed_assets(*, db_path: Path | None = None) -> list[ManagedAsset]:
    """Every Managed Asset, most recently updated first -- the same ordering the
    Deal and Investment libraries already use."""

    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM managed_assets ORDER BY updated_at DESC, id ASC"
        ).fetchall()
    return [_row_to_managed_asset(row) for row in rows]


def get_managed_asset(managed_asset_id: str, *, db_path: Path | None = None) -> ManagedAsset:
    """One Managed Asset. Raises ``ManagedAssetNotFoundError``."""

    with _connect(db_path) as connection:
        return _row_to_managed_asset(_require_managed_asset(connection, managed_asset_id))


def delete_managed_asset(managed_asset_id: str, *, db_path: Path | None = None) -> None:
    """Permanently delete one Managed Asset and every report it owns.

    The source Deal and all acquisition underwriting remain untouched. Reports
    are deleted explicitly before their parent because this store does not
    enable SQLite foreign-key enforcement on every connection and therefore
    does not rely on ``ON DELETE CASCADE`` for correctness.

    Raises ``ManagedAssetNotFoundError`` without writing anything when the
    asset does not exist.
    """

    with _connect(db_path) as connection:
        _require_managed_asset(connection, managed_asset_id)
        connection.execute(
            "DELETE FROM monthly_asset_reports WHERE managed_asset_id = ?",
            (managed_asset_id,),
        )
        connection.execute("DELETE FROM managed_assets WHERE id = ?", (managed_asset_id,))


def list_monthly_reports(
    managed_asset_id: str, *, db_path: Path | None = None
) -> list[MonthlyAssetReport]:
    """Every saved report for one asset, in month order. Raises
    ``ManagedAssetNotFoundError`` if the asset does not exist -- an empty list
    means "no reports yet", and must never also mean "no such asset"."""

    with _connect(db_path) as connection:
        _require_managed_asset(connection, managed_asset_id)
        rows = connection.execute(
            "SELECT * FROM monthly_asset_reports WHERE managed_asset_id = ? "
            "ORDER BY reporting_month ASC",
            (managed_asset_id,),
        ).fetchall()
    return [_row_to_monthly_report(row) for row in rows]


def get_monthly_report(
    managed_asset_id: str, reporting_month: date, *, db_path: Path | None = None
) -> MonthlyAssetReport:
    """One report. The month is normalized before lookup, so any day in March
    finds March's report. Raises ``MonthlyReportNotFoundError``."""

    month = normalize_reporting_month(reporting_month)
    with _connect(db_path) as connection:
        _require_managed_asset(connection, managed_asset_id)
        row = connection.execute(
            "SELECT * FROM monthly_asset_reports WHERE managed_asset_id = ? "
            "AND reporting_month = ?",
            (managed_asset_id, month.isoformat()),
        ).fetchone()
    if row is None:
        raise MonthlyReportNotFoundError((managed_asset_id, month))
    return _row_to_monthly_report(row)


def create_monthly_report(
    *,
    managed_asset_id: str,
    reporting_month: date,
    budget: OperatingFigures,
    actual: OperatingFigures,
    commentary: str | None = None,
    db_path: Path | None = None,
) -> MonthlyAssetReport:
    """Create one month's report, freezing its approved budget.

    The only statement in this module that writes a ``budget_*`` column. After
    it commits, the budget is immutable: ``update_monthly_report_actuals`` names
    only ``actual_*``, ``commentary`` and ``updated_at``, so there is no SQL
    here capable of revising one.

    Raises ``ManagedAssetNotFoundError``, ``AssetReportValidationError`` and
    ``MonthlyReportExistsError``. A second create for a month that already has a
    report is refused rather than merged -- merging would be an undeclared
    budget revision.
    """

    month = normalize_reporting_month(reporting_month)
    require_valid_monthly_report(
        reporting_month=month, budget=budget, actual=actual, commentary=commentary
    )
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        _require_managed_asset(connection, managed_asset_id)
        existing = connection.execute(
            "SELECT 1 FROM monthly_asset_reports WHERE managed_asset_id = ? "
            "AND reporting_month = ?",
            (managed_asset_id, month.isoformat()),
        ).fetchone()
        if existing is not None:
            raise MonthlyReportExistsError(
                managed_asset_id=managed_asset_id, reporting_month=month
            )

        values: dict[str, object] = {
            "managed_asset_id": managed_asset_id,
            "reporting_month": month.isoformat(),
            **_figure_values(budget, "budget"),
            **_figure_values(actual, "actual"),
            "commentary": commentary,
            "created_at": now,
            "updated_at": now,
        }
        columns = ", ".join(values)
        placeholders = ", ".join(f":{name}" for name in values)
        connection.execute(
            f"INSERT INTO monthly_asset_reports ({columns}) VALUES ({placeholders})", values
        )
        row = connection.execute(
            "SELECT * FROM monthly_asset_reports WHERE managed_asset_id = ? "
            "AND reporting_month = ?",
            (managed_asset_id, month.isoformat()),
        ).fetchone()
    return _row_to_monthly_report(row)


def update_monthly_report_actuals(
    *,
    managed_asset_id: str,
    reporting_month: date,
    actual: OperatingFigures,
    commentary: str | None = None,
    budget: OperatingFigures | None = None,
    db_path: Path | None = None,
) -> MonthlyAssetReport:
    """Update one report's actual results and commentary. The approved budget is
    not updatable.

    ``budget`` is accepted only so a caller that round-trips a whole report can
    be told precisely what it got wrong. When supplied, it is compared field by
    field against the frozen budget and any difference raises
    ``BudgetImmutableError`` naming every changed field -- a typed conflict,
    deliberately distinct from ``AssetReportValidationError``, because the
    submitted budget may be perfectly well-formed and the refusal is about
    authority rather than shape. A budget is never silently replaced or revised.

    Passing ``None`` asserts nothing about the budget and is the ordinary path.
    """

    month = normalize_reporting_month(reporting_month)
    now = _utc_now_iso()
    with _connect(db_path) as connection:
        _require_managed_asset(connection, managed_asset_id)
        row = connection.execute(
            "SELECT * FROM monthly_asset_reports WHERE managed_asset_id = ? "
            "AND reporting_month = ?",
            (managed_asset_id, month.isoformat()),
        ).fetchone()
        if row is None:
            raise MonthlyReportNotFoundError((managed_asset_id, month))

        frozen = _figures_from_row(row, "budget")
        # When the caller echoes a budget back, *that* is the budget validated
        # here -- not the frozen one. A malformed echoed field is the caller's
        # error to fix, so it must be refused as a structured 422 before the
        # comparison below tries to read it as a number: ``float(None)`` is a
        # TypeError, which would surface as a 500 for what is plainly a bad
        # request. The frozen budget is valid by construction (``create_monthly_report``
        # validated it, and no statement in this module can change it), so it is
        # validated only when there is no supplied budget to check instead.
        require_valid_monthly_report(
            reporting_month=month,
            budget=frozen if budget is None else budget,
            actual=actual,
            commentary=commentary,
        )
        if budget is not None:
            changed = tuple(
                field
                for field in _AM1_FIGURE_FIELDS
                if float(getattr(budget, field)) != float(getattr(frozen, field))
            )
            if changed:
                raise BudgetImmutableError(
                    managed_asset_id=managed_asset_id,
                    reporting_month=month,
                    changed_fields=changed,
                )

        values: dict[str, object] = {
            **_figure_values(actual, "actual"),
            "commentary": commentary,
            "updated_at": now,
            "key_asset": managed_asset_id,
            "key_month": month.isoformat(),
        }
        assignments = ", ".join(
            f"{name} = :{name}"
            for name in values
            if name not in ("key_asset", "key_month")
        )
        connection.execute(
            f"UPDATE monthly_asset_reports SET {assignments} "
            "WHERE managed_asset_id = :key_asset AND reporting_month = :key_month",
            values,
        )
        updated = connection.execute(
            "SELECT * FROM monthly_asset_reports WHERE managed_asset_id = ? "
            "AND reporting_month = ?",
            (managed_asset_id, month.isoformat()),
        ).fetchone()
    return _row_to_monthly_report(updated)
