"""D5.4 -- the v4 -> v5 migration, and the Lease-Level economic fingerprint.

Two things a persistence gate has to get right, and both fail silently if it
does not:

* **Migration.** Built from a *real* v4 database, written with raw ``sqlite3``
  against the v4 DDL, carrying a Quick and a Detailed deal with valid snapshots.
  Constructing a v5 database and calling it v4 would prove nothing; the risk
  being tested is that upgrading disturbs data that already exists.
* **Fingerprint completeness.** Driven by ``dataclasses.fields`` over every
  economic contract rather than a handwritten list, because the failure mode is
  a field nobody remembered -- an edited rent roll reusing a stale analysis, with
  no symptom at all.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from anchor.analysis import (
    EscalationBasis,
    InitialVacancyStrategy,
    LeaseType,
    LeasingCommissionMethod,
    RecoveryBasis,
)
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs, OperatingMode
from anchor.deals import store as deals_store
from anchor.deals.fingerprint import (
    UnfingerprintableValueError,
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)
from test_d5_4_lease_level_persistence import (  # type: ignore[import-not-found]
    LEASES,
    MARKET_LEASING,
    OPERATING_INPUTS,
    OVERRIDE,
    PROPERTY_INPUTS,
    SUITES,
    TERMS,
    store_deal,
)

# =============================================================================
# The exact pre-D5.4 digests.
#
# Captured from the shipped implementation *before* the canonical encoder gained
# date support. Adding a ``default=`` handler must not disturb a byte of an
# existing digest: every saved Quick and Detailed analysis snapshot in every
# existing database is validated against one, so a changed hash would silently
# invalidate them all and force a re-analysis nobody asked for.
# =============================================================================

_QUICK_INPUTS = AcquisitionInputs(
    purchase_price=50_000_000.0, current_noi=2_500_000.0, occupancy=0.95,
    noi_growth=0.03, hold_period=5, exit_cap_rate=0.055, ltv=0.65,
    interest_rate=0.0525, amortization=30, acquisition_cost_pct=0.02,
    financing_fee_pct=0.01, disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0, io_period=2,
)
_DETAILED_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0, hold_period=5, exit_cap_rate=0.065, ltv=0.60,
    interest_rate=0.05, amortization=30, acquisition_cost_pct=0.02,
    financing_fee_pct=0.01, disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0, io_period=2,
)
_DETAILED_OPERATING = DetailedOperatingInputs(
    gross_potential_rent=800_000.0, other_income=20_000.0,
    vacancy_credit_loss_pct=0.05, property_taxes=60_000.0, insurance=20_000.0,
    utilities=25_000.0, repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0, management_fee_pct=0.05,
    revenue_growth=0.03, expense_growth=0.03,
)

_FROZEN_QUICK_DIGEST = "8a9f86952103924be22ba5ca61c68bfc5cf99a0881e48f066ea5508230ecbf62"
_FROZEN_DETAILED_DIGEST = "26ccc4e315b5c742be8757f8f684e3c2105446c39087a43478f8e78aa703f881"


def test_the_quick_fingerprint_digest_is_byte_identical_to_pre_d5_4() -> None:
    assert fingerprint_quick_inputs(_QUICK_INPUTS) == _FROZEN_QUICK_DIGEST


def test_the_detailed_fingerprint_digest_is_byte_identical_to_pre_d5_4() -> None:
    assert (
        fingerprint_detailed_inputs(_DETAILED_TERMS, _DETAILED_OPERATING)
        == _FROZEN_DETAILED_DIGEST
    )


# =============================================================================
# 1. The canonical encoder
# =============================================================================


def test_dates_are_canonicalised_rather_than_crashing() -> None:
    """The latent defect this gate owns.

    ``json.dumps(dataclasses.asdict(...))`` raised ``TypeError`` on any
    ``datetime.date``, so a Lease-Level fingerprint was impossible to compute at
    all before D5.4.
    """

    digest = fingerprint_lease_level_inputs(
        TERMS, PROPERTY_INPUTS, SUITES, LEASES,
        market_leasing=MARKET_LEASING, operating_inputs=OPERATING_INPUTS,
    )
    assert len(digest) == 64


def test_an_unknown_type_raises_rather_than_being_stringified() -> None:
    """``default=str`` would make every future type silently fingerprintable via
    its ``repr`` -- unstable across versions, and capable of giving two different
    values one digest without anyone noticing."""

    from anchor.deals.fingerprint import _fingerprint_json

    class Opaque:
        pass

    with pytest.raises(UnfingerprintableValueError) as excinfo:
        _fingerprint_json({"x": Opaque()})

    assert excinfo.value.offending_type == "Opaque"
    assert "Opaque" not in str(excinfo.value).replace("'Opaque'", "")


# =============================================================================
# 2. Every economic field reaches the fingerprint
# =============================================================================


def _mutated(value: Any) -> Any:
    """Another *valid* value of the same shape, for any field type we persist."""

    if isinstance(value, bool):
        return not value
    if isinstance(value, date):
        return date(value.year + 1, value.month, value.day)
    if isinstance(value, LeaseType):
        return LeaseType.GROSS if value is not LeaseType.GROSS else LeaseType.NNN
    if isinstance(value, EscalationBasis):
        return (
            EscalationBasis.NONE
            if value is not EscalationBasis.NONE
            else EscalationBasis.LEASE_ANNIVERSARY
        )
    if isinstance(value, InitialVacancyStrategy):
        return (
            InitialVacancyStrategy.HOLD_VACANT
            if value is not InitialVacancyStrategy.HOLD_VACANT
            else InitialVacancyStrategy.MARKET_LEASE_UP
        )
    if isinstance(value, RecoveryBasis):
        return None  # the only other valid state of a nullable recovery basis
    if isinstance(value, LeasingCommissionMethod):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value + 1
    if isinstance(value, float):
        return value + 0.5
    if isinstance(value, str):
        return value + "-changed"
    if value is None:
        return 1.0  # a nullable field gaining a value is an economic change
    return None


def _baseline() -> dict[str, Any]:
    return {
        "terms": TERMS,
        "property_inputs": PROPERTY_INPUTS,
        "suites": SUITES,
        "leases": LEASES,
        "market_leasing": MARKET_LEASING,
        "operating_inputs": OPERATING_INPUTS,
    }


def _fingerprint(parts: dict[str, Any]) -> str:
    return fingerprint_lease_level_inputs(
        parts["terms"],
        parts["property_inputs"],
        parts["suites"],
        parts["leases"],
        market_leasing=parts["market_leasing"],
        operating_inputs=parts["operating_inputs"],
    )


def _scalar_contract_cases() -> list[tuple[str, str]]:
    return [
        (part, field.name)
        for part, contract in (
            ("terms", AcquisitionTerms),
            ("property_inputs", type(PROPERTY_INPUTS)),
            ("operating_inputs", type(OPERATING_INPUTS)),
            ("market_leasing", type(MARKET_LEASING)),
        )
        for field in dataclasses.fields(contract)
    ]


@pytest.mark.parametrize(
    ("part", "field_name"), _scalar_contract_cases(), ids=lambda v: str(v)
)
def test_every_scalar_contract_field_changes_the_fingerprint(
    part: str, field_name: str
) -> None:
    """Driven by ``dataclasses.fields``, so a field added tomorrow is covered
    without an edit here. A field omitted from the fingerprint means an edited
    deal silently reuses a stale analysis -- with no symptom."""

    parts = _baseline()
    before = _fingerprint(parts)
    current = getattr(parts[part], field_name)
    parts[part] = dataclasses.replace(parts[part], **{field_name: _mutated(current)})

    assert _fingerprint(parts) != before, (
        f"{part}.{field_name} does not reach the fingerprint"
    )


@pytest.mark.parametrize(
    "field_name",
    [field.name for field in dataclasses.fields(SUITES[1])],
)
def test_every_suite_field_changes_the_fingerprint(field_name: str) -> None:
    parts = _baseline()
    before = _fingerprint(parts)
    suite = SUITES[1]

    if field_name == "market_leasing_override":
        replacement = None
    elif field_name == "initial_vacancy":
        replacement = None
    else:
        replacement = _mutated(getattr(suite, field_name))

    parts["suites"] = (SUITES[0], dataclasses.replace(suite, **{field_name: replacement}), SUITES[2])
    assert _fingerprint(parts) != before, f"Suite.{field_name} is not fingerprinted"


@pytest.mark.parametrize(
    "field_name",
    [field.name for field in dataclasses.fields(LEASES[0])],
)
def test_every_lease_field_changes_the_fingerprint(field_name: str) -> None:
    parts = _baseline()
    before = _fingerprint(parts)
    lease = LEASES[0]
    replacement = _mutated(getattr(lease, field_name))
    if field_name == "suite_id":
        replacement = "301"  # another real suite, so the change stays coherent
    parts["leases"] = (dataclasses.replace(lease, **{field_name: replacement}),)

    assert _fingerprint(parts) != before, f"Lease.{field_name} is not fingerprinted"


@pytest.mark.parametrize(
    "field_name", [field.name for field in dataclasses.fields(OVERRIDE)]
)
def test_every_nested_override_field_changes_the_fingerprint(field_name: str) -> None:
    """The nested contract inside the one JSON column, recursed into."""

    parts = _baseline()
    before = _fingerprint(parts)
    override = dataclasses.replace(
        OVERRIDE, **{field_name: _mutated(getattr(OVERRIDE, field_name))}
    )
    parts["suites"] = (
        SUITES[0],
        dataclasses.replace(SUITES[1], market_leasing_override=override),
        SUITES[2],
    )

    assert _fingerprint(parts) != before, (
        f"market_leasing_override.{field_name} is not fingerprinted"
    )


@pytest.mark.parametrize("field_name", ["strategy", "initial_lease_up_months"])
def test_every_initial_vacancy_field_changes_the_fingerprint(field_name: str) -> None:
    parts = _baseline()
    before = _fingerprint(parts)
    vacancy = SUITES[1].initial_vacancy
    changed = dataclasses.replace(
        vacancy, **{field_name: _mutated(getattr(vacancy, field_name))}
    )
    parts["suites"] = (
        SUITES[0],
        dataclasses.replace(SUITES[1], initial_vacancy=changed),
        SUITES[2],
    )

    assert _fingerprint(parts) != before, (
        f"initial_vacancy.{field_name} is not fingerprinted"
    )


# =============================================================================
# 3. Non-economic changes do not move the fingerprint
# =============================================================================


def test_reordering_suites_does_not_change_the_fingerprint() -> None:
    """The engine addresses suites by id, so row order changes no number.

    A fingerprint that moved here would invalidate a still-valid analysis for a
    purely cosmetic edit.
    """

    parts = _baseline()
    before = _fingerprint(parts)
    parts["suites"] = tuple(reversed(SUITES))

    assert _fingerprint(parts) == before


def test_reordering_leases_does_not_change_the_fingerprint() -> None:
    extra = dataclasses.replace(LEASES[0], lease_id="L-999", suite_id="301", leased_area_sf=25_000.0)
    parts = _baseline()
    parts["leases"] = (LEASES[0], extra)
    before = _fingerprint(parts)
    parts["leases"] = (extra, LEASES[0])

    assert _fingerprint(parts) == before


def test_sorting_is_not_deduplication() -> None:
    """Two suites sharing an id stay two entries.

    They are an invalid rent roll and are refused downstream by
    ``DUPLICATE_SUITE_ID``; collapsing them here would let an invalid deal
    fingerprint as a valid one.
    """

    parts = _baseline()
    single = _fingerprint(parts)
    parts["suites"] = (*SUITES, dataclasses.replace(SUITES[0], suite_area_sf=1.0))

    assert _fingerprint(parts) != single


def test_the_deal_name_id_and_timestamps_are_outside_the_fingerprint(tmp_path: Path) -> None:
    db = tmp_path / "names.db"
    first = store_deal(db, name="One")
    second = store_deal(db, name="Two")

    def digest(deal):
        return fingerprint_lease_level_inputs(
            deal.terms, deal.property_inputs, deal.suites, deal.leases,
            market_leasing=deal.market_leasing, operating_inputs=deal.operating_inputs,
        )

    assert first.id != second.id
    assert digest(first) == digest(second)


def test_the_display_ordinal_is_outside_the_fingerprint(tmp_path: Path) -> None:
    """Stored ordinals differ between these two deals; digests must not."""

    db = tmp_path / "ordinal.db"
    natural = store_deal(db, suites=SUITES)
    reordered = store_deal(db, suites=tuple(reversed(SUITES)))

    connection = sqlite3.connect(db)
    ordinals = {
        deal_id: [
            row[0]
            for row in connection.execute(
                "SELECT ordinal FROM lease_level_suites WHERE deal_id = ? "
                "ORDER BY suite_id",
                (deal_id,),
            )
        ]
        for deal_id in (natural.id, reordered.id)
    }
    connection.close()
    assert ordinals[natural.id] != ordinals[reordered.id], "fixture is not exercising ordinals"

    def digest(deal):
        return fingerprint_lease_level_inputs(
            deal.terms, deal.property_inputs, deal.suites, deal.leases,
            market_leasing=deal.market_leasing, operating_inputs=deal.operating_inputs,
        )

    assert digest(natural) == digest(reordered)


def test_lease_level_cannot_collide_with_another_modes_digest() -> None:
    assert fingerprint_lease_level_inputs(
        TERMS, PROPERTY_INPUTS, SUITES, LEASES,
        market_leasing=MARKET_LEASING, operating_inputs=OPERATING_INPUTS,
    ) not in {_FROZEN_QUICK_DIGEST, _FROZEN_DETAILED_DIGEST}


# =============================================================================
# 4. Migration from a real v4 database
# =============================================================================

_V4_DEALS_DDL = """
CREATE TABLE deals (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, purchase_price REAL NOT NULL,
    current_noi REAL NOT NULL, occupancy REAL NOT NULL, noi_growth REAL NOT NULL,
    hold_period INTEGER NOT NULL, exit_cap_rate REAL NOT NULL, ltv REAL NOT NULL,
    interest_rate REAL NOT NULL, amortization INTEGER NOT NULL,
    acquisition_cost_pct REAL NOT NULL DEFAULT 0.0,
    financing_fee_pct REAL NOT NULL DEFAULT 0.0,
    disposition_cost_pct REAL NOT NULL DEFAULT 0.0,
    annual_capex_reserve REAL NOT NULL DEFAULT 0.0,
    io_period INTEGER NOT NULL DEFAULT 0, deal_context TEXT,
    analysis_snapshot TEXT, analysis_snapshot_schema_version INTEGER,
    analysis_snapshot_fingerprint TEXT, ai_snapshot TEXT,
    ai_snapshot_schema_version INTEGER, ai_snapshot_fingerprint TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
)
"""

_V4_DETAILED_DEALS_DDL = """
CREATE TABLE detailed_deals (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, purchase_price REAL NOT NULL,
    hold_period INTEGER NOT NULL, exit_cap_rate REAL NOT NULL, ltv REAL NOT NULL,
    interest_rate REAL NOT NULL, amortization INTEGER NOT NULL,
    acquisition_cost_pct REAL NOT NULL, financing_fee_pct REAL NOT NULL,
    disposition_cost_pct REAL NOT NULL, annual_capex_reserve REAL NOT NULL,
    io_period INTEGER NOT NULL, deal_context TEXT,
    analysis_snapshot TEXT, analysis_snapshot_schema_version INTEGER,
    analysis_snapshot_fingerprint TEXT, ai_snapshot TEXT,
    ai_snapshot_schema_version INTEGER, ai_snapshot_fingerprint TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
)
"""

_V4_DETAILED_OPERATING_DDL = """
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

_TIMESTAMP = "2026-09-01T12:00:00+00:00"


def _write_v4_database(path: Path) -> dict[str, Any]:
    """A genuine v4 database, written with raw sqlite3 against the v4 DDL.

    Deliberately not built through the store: a database produced by v5 code and
    relabelled would not exercise the upgrade at all.
    """

    import json as _json

    connection = sqlite3.connect(path)
    connection.executescript(
        ";".join((_V4_DEALS_DDL, _V4_DETAILED_DEALS_DDL, _V4_DETAILED_OPERATING_DDL))
    )

    quick_fingerprint = fingerprint_quick_inputs(_QUICK_INPUTS)
    detailed_fingerprint = fingerprint_detailed_inputs(_DETAILED_TERMS, _DETAILED_OPERATING)

    from anchor.engine import analyze_acquisition, analyze_detailed_acquisition_with_projection

    quick_snapshot = _json.dumps(dataclasses.asdict(analyze_acquisition(_QUICK_INPUTS)))
    detailed_snapshot = _json.dumps(
        dataclasses.asdict(
            analyze_detailed_acquisition_with_projection(_DETAILED_TERMS, _DETAILED_OPERATING)
        )
    )

    connection.execute(
        "INSERT INTO deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "quick-1", "Legacy Quick",
            *(getattr(_QUICK_INPUTS, f.name) for f in dataclasses.fields(_QUICK_INPUTS)),
            "legacy context",
            quick_snapshot, 1, quick_fingerprint,
            None, None, None,
            _TIMESTAMP, _TIMESTAMP,
        ),
    )
    connection.execute(
        "INSERT INTO detailed_deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "detailed-1", "Legacy Detailed",
            *(getattr(_DETAILED_TERMS, f.name) for f in dataclasses.fields(_DETAILED_TERMS)),
            None,
            detailed_snapshot, 1, detailed_fingerprint,
            None, None, None,
            _TIMESTAMP, _TIMESTAMP,
        ),
    )
    connection.execute(
        "INSERT INTO detailed_operating_inputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "detailed-1",
            *(getattr(_DETAILED_OPERATING, f.name) for f in dataclasses.fields(_DETAILED_OPERATING)),
        ),
    )
    connection.execute("PRAGMA user_version = 4")
    connection.commit()

    # Prove the fixture really is v4 before anything migrates it.
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert not any(name.startswith("lease_level") for name in tables)
    connection.close()

    return {"quick_fingerprint": quick_fingerprint, "detailed_fingerprint": detailed_fingerprint}


@pytest.fixture
def migrated(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    path = tmp_path / "legacy.db"
    context = _write_v4_database(path)
    deals_store.list_deals(db_path=path)  # any store call triggers the migration
    return path, context


def test_the_migration_reaches_version_five(migrated) -> None:
    path, _ = migrated
    connection = sqlite3.connect(path)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert version == 5


def test_the_migration_adds_all_six_lease_level_tables(migrated) -> None:
    path, _ = migrated
    connection = sqlite3.connect(path)
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    connection.close()

    assert {
        "lease_level_deals",
        "lease_level_property_inputs",
        "lease_level_operating_inputs",
        "lease_level_market_leasing",
        "lease_level_suites",
        "lease_level_leases",
    } <= tables


def test_the_quick_deal_survives_the_migration_unchanged(migrated) -> None:
    path, context = migrated
    deal = deals_store.get_deal("quick-1", db_path=path)

    assert deal.operating_mode is OperatingMode.QUICK
    assert deal.name == "Legacy Quick"
    assert deal.inputs == _QUICK_INPUTS
    assert deal.deal_context == "legacy context"
    assert deal.created_at == datetime.fromisoformat(_TIMESTAMP)
    assert fingerprint_quick_inputs(deal.inputs) == context["quick_fingerprint"]


def test_the_detailed_deal_survives_the_migration_unchanged(migrated) -> None:
    path, context = migrated
    deal = deals_store.get_deal("detailed-1", db_path=path)

    assert deal.operating_mode is OperatingMode.DETAILED
    assert deal.terms == _DETAILED_TERMS
    assert deal.detailed_operating_inputs == _DETAILED_OPERATING
    assert (
        fingerprint_detailed_inputs(deal.terms, deal.detailed_operating_inputs)
        == context["detailed_fingerprint"]
    )


def test_existing_snapshots_remain_valid_after_the_migration(migrated) -> None:
    """The load-bearing one.

    A snapshot is served only when its stored fingerprint still matches one
    recomputed from the deal's current assumptions. If D5.4's encoder change had
    moved a digest, every saved analysis in every existing database would
    silently decode as absent.
    """

    path, _ = migrated

    assert deals_store.get_deal("quick-1", db_path=path).analysis_snapshot is not None
    assert deals_store.get_deal("detailed-1", db_path=path).analysis_snapshot is not None


def test_the_migration_rewrites_no_existing_row(tmp_path: Path) -> None:
    path = tmp_path / "untouched.db"
    _write_v4_database(path)

    connection = sqlite3.connect(path)
    before = {
        table: connection.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("deals", "detailed_deals", "detailed_operating_inputs")
    }
    connection.close()

    deals_store.list_deals(db_path=path)

    connection = sqlite3.connect(path)
    after = {
        table: connection.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("deals", "detailed_deals", "detailed_operating_inputs")
    }
    connection.close()

    assert after == before


def test_the_migration_is_idempotent(migrated) -> None:
    path, _ = migrated
    for _ in range(3):
        deals_store.list_deals(db_path=path)

    connection = sqlite3.connect(path)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    suites = connection.execute("SELECT COUNT(*) FROM lease_level_suites").fetchone()[0]
    connection.close()

    assert version == 5
    assert suites == 0
    assert len(deals_store.list_deals(db_path=path)) == 2


def test_a_lease_level_deal_can_be_created_in_a_migrated_database(migrated) -> None:
    path, _ = migrated
    saved = store_deal(path)

    reloaded = deals_store.get_deal(saved.id, db_path=path)
    assert reloaded.operating_mode is OperatingMode.LEASE_LEVEL
    assert reloaded.suites == SUITES
    assert len(deals_store.list_deals(db_path=path)) == 3


def test_a_migrated_schema_matches_a_fresh_one(tmp_path: Path) -> None:
    """Two routes to v5 must produce the same database.

    A divergence would mean a deal behaves differently depending on when its
    database was created -- the kind of defect that only shows up on someone
    else's machine.
    """

    migrated_path = tmp_path / "migrated.db"
    _write_v4_database(migrated_path)
    deals_store.list_deals(db_path=migrated_path)

    fresh_path = tmp_path / "fresh.db"
    deals_store.list_deals(db_path=fresh_path)

    def schema(path: Path) -> dict[str, list[tuple[Any, ...]]]:
        connection = sqlite3.connect(path)
        tables = sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        )
        result = {
            table: [
                (row[1], row[2].upper(), row[3], row[5])
                for row in connection.execute(f"PRAGMA table_info({table})")
            ]
            for table in tables
        }
        connection.close()
        return result

    migrated_schema = schema(migrated_path)
    fresh_schema = schema(fresh_path)

    assert sorted(migrated_schema) == sorted(fresh_schema)
    for table in fresh_schema:
        assert migrated_schema[table] == fresh_schema[table], table
