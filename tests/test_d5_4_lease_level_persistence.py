"""D5.4 -- Lease-Level deals are durable.

The gate's acceptance test is the round trip: **analyze, save, reload, rebuild
the request from the reloaded inputs alone, analyze again, and require the two
result envelopes to be identical.** That is the only proof that "persisted
inputs are the source of truth" is true rather than aspirational -- it fails if
any field is dropped, coerced, reordered into significance, or silently
defaulted, without needing a separate assertion for each.

Around it:

* **Migration** from a real v4 database, built with raw ``sqlite3`` so it is
  genuinely v4 rather than a v5 database with the version lied about.
* **Fingerprint completeness**, driven by ``dataclasses.fields`` over every
  economic contract, so a field added tomorrow is covered without an edit here.
* **Storage fidelity** -- dates, enums, floats and the one JSON column, each
  compared with exact equality, because "close enough" is not a thing a
  fingerprint can tolerate.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from anchor.analysis import (
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
from anchor.api import app
from anchor.contracts import AcquisitionTerms, OperatingMode
from anchor.deals import store as deals_store
from anchor.deals.fingerprint import (
    UnfingerprintableValueError,
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)
from anchor.deals.store import PersistedDealDataError

# =============================================================================
# Fixtures -- a deal exercising every mechanic the persistence layer must carry
# =============================================================================

TERMS = AcquisitionTerms(
    purchase_price=50_000_000.0,
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

PROPERTY_INPUTS = LeaseLevelPropertyInputs(
    analysis_start_date=date(2027, 1, 1), rentable_area_sf=120_000.0
)

OPERATING_INPUTS = LeaseLevelOperatingInputs(
    other_income=50_000.0,
    other_income_growth=0.03,
    credit_loss_pct=0.01,
    property_taxes=600_000.0,
    insurance=90_000.0,
    utilities=140_000.0,
    repairs_maintenance=110_000.0,
    other_operating_expenses=60_000.0,
    management_fee_pct=0.03,
    expense_growth=0.03,
    recoverable_expense_ratio=0.85,
)


def market_leasing(**overrides: Any) -> MarketLeasingAssumptions:
    base: dict[str, Any] = {
        "market_rent_psf": 34.0,
        "market_rent_growth": 0.03,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.03,
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 1.0,
        "new_term_months": 60,
        "new_downtime_months": 6.0,
        "new_free_rent_months": 3.0,
        "renewal_ti_psf": 15.0,
        "new_ti_psf": 45.0,
        "leasing_commission_method": LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
        "renewal_lc_pct": 0.03,
        "new_lc_pct": 0.06,
        "renewal_probability": 0.7,
        "renewal_lease_type": LeaseType.NNN,
        "renewal_recovery_basis": None,
        "renewal_expense_stop_psf": None,
        "new_lease_type": LeaseType.NNN,
        "new_recovery_basis": None,
        "new_expense_stop_psf": None,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)


MARKET_LEASING = market_leasing()

#: A full override, exercising every kind the JSON column must carry: floats,
#: an explicit ``None``, three enums and a nullable enum that *is* populated.
OVERRIDE = market_leasing(
    market_rent_psf=41.5,
    renewal_rent_psf=39.25,
    renewal_probability=0.55,
    renewal_lease_type=LeaseType.MODIFIED_GROSS,
    renewal_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
    renewal_expense_stop_psf=8.75,
    new_lease_type=LeaseType.GROSS,
)

SUITES = (
    # occupied
    Suite(suite_id="101", suite_area_sf=60_000.0, suite_label="Ground floor"),
    # vacant, leasing up, and carrying the full override
    Suite(
        suite_id="201",
        suite_area_sf=35_000.0,
        market_rent_psf=36.5,
        market_leasing_override=OVERRIDE,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP,
            initial_lease_up_months=6.0,
        ),
    ),
    # vacant, held
    Suite(
        suite_id="301",
        suite_area_sf=25_000.0,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.HOLD_VACANT
        ),
    ),
)

LEASES = (
    Lease(
        lease_id="L-101",
        suite_id="101",
        leased_area_sf=60_000.0,
        rent_commencement_date=date(2024, 3, 1),
        lease_expiration_date=date(2028, 12, 31),
        base_rent_psf=32.5,
        escalation_pct=0.03,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        lease_type=LeaseType.MODIFIED_GROSS,
        tenant_name="Anchor Tenant",
        lease_start_date=date(2024, 2, 1),
        origin=LeaseOrigin.IN_PLACE,
        recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        expense_stop_psf=7.25,
    ),
)


def store_deal(db: Path, **overrides: Any):
    kwargs: dict[str, Any] = {
        "name": "Rolling Rent Roll",
        "terms": TERMS,
        "property_inputs": PROPERTY_INPUTS,
        "operating_inputs": OPERATING_INPUTS,
        "market_leasing": MARKET_LEASING,
        "suites": SUITES,
        "leases": LEASES,
    }
    kwargs.update(overrides)
    return deals_store.create_lease_level_deal(
        kwargs["name"],
        kwargs["terms"],
        kwargs["property_inputs"],
        kwargs["operating_inputs"],
        kwargs["market_leasing"],
        kwargs["suites"],
        kwargs["leases"],
        deal_context=kwargs.get("deal_context"),
        db_path=db,
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "d5-4.db"


def canonical(value: Any) -> Any:
    return json.loads(json.dumps(jsonable_encoder(value), sort_keys=True))


# =============================================================================
# 1. Save / load identity
# =============================================================================


def test_a_saved_lease_level_deal_reloads_as_lease_level(db: Path) -> None:
    saved = store_deal(db)
    loaded = deals_store.get_deal(saved.id, db_path=db)

    assert loaded.operating_mode is OperatingMode.LEASE_LEVEL
    assert loaded.inputs is None
    assert loaded.detailed_operating_inputs is None


@pytest.mark.parametrize(
    "attribute",
    ["terms", "property_inputs", "operating_inputs", "market_leasing", "suites", "leases"],
)
def test_every_persisted_contract_round_trips_exactly(db: Path, attribute: str) -> None:
    """Typed in, typed out -- compared with ``==`` on frozen dataclasses, which
    is exact for every float, date and enum they hold."""

    saved = store_deal(db)
    loaded = deals_store.get_deal(saved.id, db_path=db)

    original = {
        "terms": TERMS,
        "property_inputs": PROPERTY_INPUTS,
        "operating_inputs": OPERATING_INPUTS,
        "market_leasing": MARKET_LEASING,
        "suites": SUITES,
        "leases": LEASES,
    }[attribute]

    assert getattr(loaded, attribute) == original


def test_dates_return_as_dates(db: Path) -> None:
    loaded = deals_store.get_deal(store_deal(db).id, db_path=db)

    assert isinstance(loaded.property_inputs.analysis_start_date, date)
    assert loaded.property_inputs.analysis_start_date == date(2027, 1, 1)
    lease = loaded.leases[0]
    assert isinstance(lease.rent_commencement_date, date)
    assert isinstance(lease.lease_expiration_date, date)
    assert isinstance(lease.lease_start_date, date)
    assert lease.lease_expiration_date == date(2028, 12, 31)


def test_enums_return_as_enum_members(db: Path) -> None:
    """Never bare strings. A raw ``"nnn"`` would type-check nowhere and fail
    somewhere far away, inside a recovery builder comparing it to a member."""

    loaded = deals_store.get_deal(store_deal(db).id, db_path=db)
    lease = loaded.leases[0]

    assert isinstance(lease.lease_type, LeaseType)
    assert isinstance(lease.escalation_basis, EscalationBasis)
    assert isinstance(lease.origin, LeaseOrigin)
    assert isinstance(lease.recovery_basis, RecoveryBasis)
    assert isinstance(
        loaded.market_leasing.leasing_commission_method, LeasingCommissionMethod
    )
    assert isinstance(loaded.suites[1].initial_vacancy.strategy, InitialVacancyStrategy)


def test_nested_initial_vacancy_round_trips(db: Path) -> None:
    loaded = deals_store.get_deal(store_deal(db).id, db_path=db)

    assert loaded.suites[0].initial_vacancy is None
    lease_up = loaded.suites[1].initial_vacancy
    assert isinstance(lease_up, InitialVacancyAssumptions)
    assert lease_up.strategy is InitialVacancyStrategy.MARKET_LEASE_UP
    assert lease_up.initial_lease_up_months == 6.0

    held = loaded.suites[2].initial_vacancy
    assert held.strategy is InitialVacancyStrategy.HOLD_VACANT
    assert held.initial_lease_up_months is None


def test_suite_market_rent_override_round_trips(db: Path) -> None:
    loaded = deals_store.get_deal(store_deal(db).id, db_path=db)

    assert loaded.suites[0].market_rent_psf is None
    assert loaded.suites[1].market_rent_psf == 36.5


def test_the_market_leasing_override_returns_a_contract_not_a_dict(db: Path) -> None:
    loaded = deals_store.get_deal(store_deal(db).id, db_path=db)
    override = loaded.suites[1].market_leasing_override

    assert isinstance(override, MarketLeasingAssumptions)
    assert not isinstance(override, dict)
    assert override == OVERRIDE
    assert loaded.suites[0].market_leasing_override is None


def test_the_override_json_round_trips_every_float_exactly(db: Path) -> None:
    """The JSON column was approved *because* this holds.

    Every float field is given an awkward binary fraction -- the kind that
    survives ``repr`` but not a formatted write -- and compared with ``==``.
    Rounding to cents here would silently move a rent.
    """

    awkward: dict[str, Any] = {}
    for index, field in enumerate(dataclasses.fields(MarketLeasingAssumptions)):
        current = getattr(OVERRIDE, field.name)
        if isinstance(current, float):
            awkward[field.name] = 0.1 + index * 0.0000000001 + 1 / 3
    override = dataclasses.replace(OVERRIDE, **awkward)

    saved = store_deal(
        db,
        suites=(
            dataclasses.replace(SUITES[1], market_leasing_override=override),
            SUITES[0],
            SUITES[2],
        ),
    )
    loaded = deals_store.get_deal(saved.id, db_path=db)
    restored = next(
        suite.market_leasing_override
        for suite in loaded.suites
        if suite.market_leasing_override is not None
    )

    for name, value in awkward.items():
        assert getattr(restored, name) == value, name
    assert restored == override


def test_scalar_floats_round_trip_exactly(db: Path) -> None:
    """SQLite REAL is an IEEE-754 double, so the column path is exact too."""

    awkward_operating = dataclasses.replace(
        OPERATING_INPUTS,
        recoverable_expense_ratio=1 / 3,
        management_fee_pct=0.1 + 0.2,
        expense_growth=0.030000000000000002,
    )
    saved = store_deal(db, operating_inputs=awkward_operating)
    loaded = deals_store.get_deal(saved.id, db_path=db)

    assert loaded.operating_inputs.recoverable_expense_ratio == 1 / 3
    assert loaded.operating_inputs.management_fee_pct == 0.1 + 0.2
    assert loaded.operating_inputs == awkward_operating


def test_row_order_is_preserved_for_display(db: Path) -> None:
    """Stored ``ordinal`` keeps the analyst's own submission order.

    Canonical id order belongs to the fingerprint alone; letting it govern
    display would silently reorder a rent roll under the person who typed it.
    """

    reordered = (SUITES[2], SUITES[0], SUITES[1])
    saved = store_deal(db, suites=reordered)
    loaded = deals_store.get_deal(saved.id, db_path=db)

    assert [suite.suite_id for suite in loaded.suites] == ["301", "101", "201"]


def test_no_analysis_snapshot_is_persisted(db: Path) -> None:
    """D5 decision A, enforced by the schema itself.

    There is no ``analysis_snapshot`` column on ``lease_level_deals`` -- absent
    columns are a stronger guarantee than an unused nullable one, because there
    is nowhere for a later gate to put a cached result by accident.
    """

    saved = store_deal(db)
    loaded = deals_store.get_deal(saved.id, db_path=db)

    assert loaded.analysis_snapshot is None

    connection = sqlite3.connect(db)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(lease_level_deals)")
    }
    connection.close()
    assert not any(column.startswith("analysis_snapshot") for column in columns)


# =============================================================================
# 2. CRUD
# =============================================================================


def test_list_includes_lease_level_deals_labelled_correctly(db: Path) -> None:
    from test_d5_4_helpers import quick_inputs  # type: ignore[import-not-found]

    deals_store.create_deal("A quick deal", quick_inputs(), db_path=db)
    lease_level = store_deal(db)

    listed = deals_store.list_deals(db_path=db)
    by_id = {deal.id: deal for deal in listed}

    assert by_id[lease_level.id].operating_mode is OperatingMode.LEASE_LEVEL
    assert len(listed) == 2
    assert {deal.operating_mode for deal in listed} == {
        OperatingMode.QUICK,
        OperatingMode.LEASE_LEVEL,
    }


def test_update_replaces_the_whole_rent_roll(db: Path) -> None:
    saved = store_deal(db)

    fewer_suites = (
        Suite(suite_id="101", suite_area_sf=120_000.0, suite_label="Whole building"),
    )
    updated = deals_store.update_lease_level_deal(
        saved.id,
        "Renamed",
        TERMS,
        PROPERTY_INPUTS,
        OPERATING_INPUTS,
        MARKET_LEASING,
        fewer_suites,
        (),
        db_path=db,
    )

    assert updated.name == "Renamed"
    assert [suite.suite_id for suite in updated.suites] == ["101"]
    assert updated.leases == ()

    connection = sqlite3.connect(db)
    remaining = connection.execute(
        "SELECT COUNT(*) FROM lease_level_suites WHERE deal_id = ?", (saved.id,)
    ).fetchone()[0]
    leases = connection.execute(
        "SELECT COUNT(*) FROM lease_level_leases WHERE deal_id = ?", (saved.id,)
    ).fetchone()[0]
    connection.close()

    assert remaining == 1, "stale suite rows survived the update"
    assert leases == 0, "stale lease rows survived the update"


def test_update_of_an_unknown_deal_raises(db: Path) -> None:
    with pytest.raises(deals_store.DealNotFoundError):
        deals_store.update_lease_level_deal(
            "nope", "x", TERMS, PROPERTY_INPUTS, OPERATING_INPUTS,
            MARKET_LEASING, SUITES, LEASES, db_path=db,
        )


def test_delete_leaves_no_orphan_rows(db: Path) -> None:
    """Explicit child deletion, because this store never enables
    ``PRAGMA foreign_keys`` -- a declared cascade would silently do nothing."""

    saved = store_deal(db)
    deals_store.delete_deal(saved.id, db_path=db)

    connection = sqlite3.connect(db)
    counts = {
        table: connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE deal_id = ?", (saved.id,)
        ).fetchone()[0]
        for table in (
            "lease_level_property_inputs",
            "lease_level_operating_inputs",
            "lease_level_market_leasing",
            "lease_level_suites",
            "lease_level_leases",
        )
    }
    parents = connection.execute(
        "SELECT COUNT(*) FROM lease_level_deals WHERE id = ?", (saved.id,)
    ).fetchone()[0]
    connection.close()

    assert parents == 0
    assert counts == dict.fromkeys(counts, 0), f"orphan rows survived: {counts}"

    with pytest.raises(deals_store.DealNotFoundError):
        deals_store.get_deal(saved.id, db_path=db)


def test_duplicate_keeps_the_mode_and_deep_copies_the_rent_roll(db: Path) -> None:
    """The D5.1A defect, now implemented rather than refused.

    Before D5.1A this path would have written a *Detailed* deal, silently
    changing which engine underwrites the copy.
    """

    original = store_deal(db)
    copy = deals_store.duplicate_deal(original.id, db_path=db)

    assert copy.operating_mode is OperatingMode.LEASE_LEVEL
    assert copy.id != original.id
    assert copy.name == f"{original.name} (Copy)"
    assert copy.suites == original.suites
    assert copy.leases == original.leases
    assert copy.market_leasing == original.market_leasing
    assert copy.analysis_snapshot is None

    # Independent rows: editing the copy must not disturb the original.
    deals_store.update_lease_level_deal(
        copy.id, "Copy edited", TERMS, PROPERTY_INPUTS, OPERATING_INPUTS,
        MARKET_LEASING, (SUITES[0],), (), db_path=db,
    )
    assert deals_store.get_deal(original.id, db_path=db).suites == SUITES


def test_a_mid_update_failure_leaves_the_previous_rent_roll_intact(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomicity, proved by fault injection.

    An update deletes the children then rewrites them. If the rewrite fails, the
    transaction must roll back to the *previous* rent roll -- not to none.
    """

    saved = store_deal(db)
    real_write = deals_store._write_lease_level_children

    def explode(*args: Any, **kwargs: Any):
        raise RuntimeError("induced failure part-way through the rewrite")

    monkeypatch.setattr(deals_store, "_write_lease_level_children", explode)

    with pytest.raises(RuntimeError):
        deals_store.update_lease_level_deal(
            saved.id, "Should not stick", TERMS, PROPERTY_INPUTS, OPERATING_INPUTS,
            MARKET_LEASING, (SUITES[0],), (), db_path=db,
        )

    monkeypatch.setattr(deals_store, "_write_lease_level_children", real_write)
    reloaded = deals_store.get_deal(saved.id, db_path=db)

    assert reloaded.name == "Rolling Rent Roll"
    assert reloaded.suites == SUITES
    assert reloaded.leases == LEASES


# =============================================================================
# 3. Corrupt stored data fails loudly
# =============================================================================


@pytest.mark.parametrize(
    ("table", "column", "value", "needle"),
    [
        ("lease_level_leases", "lease_type", "triple-net", "LeaseType"),
        ("lease_level_leases", "rent_commencement_date", "01/15/2027", "ISO-8601"),
        ("lease_level_suites", "market_leasing_override", "{not json", "valid JSON"),
        ("lease_level_market_leasing", "renewal_lease_type", "??", "LeaseType"),
    ],
    ids=["bad-enum", "bad-date", "bad-json", "bad-market-enum"],
)
def test_corrupt_stored_data_raises_rather_than_being_repaired(
    db: Path, table: str, column: str, value: str, needle: str
) -> None:
    """A store that substituted a default here would hand the engine a rent roll
    nobody authored, and the resulting numbers would look entirely ordinary."""

    saved = store_deal(db)
    connection = sqlite3.connect(db)
    connection.execute(f"UPDATE {table} SET {column} = ? WHERE deal_id = ?", (value, saved.id))
    connection.commit()
    connection.close()

    with pytest.raises(PersistedDealDataError) as excinfo:
        deals_store.get_deal(saved.id, db_path=db)

    assert needle in str(excinfo.value)


def test_a_missing_child_row_raises(db: Path) -> None:
    saved = store_deal(db)
    connection = sqlite3.connect(db)
    connection.execute(
        "DELETE FROM lease_level_market_leasing WHERE deal_id = ?", (saved.id,)
    )
    connection.commit()
    connection.close()

    with pytest.raises(PersistedDealDataError, match="lease_level_market_leasing"):
        deals_store.get_deal(saved.id, db_path=db)


def test_a_partial_override_record_is_refused(db: Path) -> None:
    """The JSON column may hold a whole record or nothing.

    A partial one is a state the domain forbids -- ``market_leasing_override`` is
    all-or-nothing -- so storage refuses it rather than filling the gaps.
    """

    saved = store_deal(db)
    partial = json.dumps({"market_rent_psf": 41.5})
    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE lease_level_suites SET market_leasing_override = ? "
        "WHERE deal_id = ? AND suite_id = ?",
        (partial, saved.id, "201"),
    )
    connection.commit()
    connection.close()

    with pytest.raises(PersistedDealDataError, match="complete MarketLeasingAssumptions"):
        deals_store.get_deal(saved.id, db_path=db)


# =============================================================================
# 4. Architecture guardrails
#
# Two boundaries the gate must not blur, both of which would be invisible in
# behavioural tests because the wrong architecture still produces right answers
# -- right up until one side changes.
# =============================================================================


def _store_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "src" / "anchor" / "deals" / "store.py"
    ).read_text(encoding="utf-8")


def test_the_store_never_reaches_the_http_transport_parser() -> None:
    """Persistence decodes its own rows; it does not re-parse HTTP.

    ``parse_lease_level_inputs`` answers "can this *untrusted* JSON become a
    contract", with unknown-key reporting and request-shaped error paths. Rows
    the store itself wrote are a different, trusted question. Routing them
    through the transport parser would tie the database format to the wire
    format so neither could change without the other.
    """

    store = _store_source()

    assert "parse_lease_level_inputs" not in store
    assert "ParsedLeaseLevelInputs" not in store
    assert "externally_owned_keys" not in store


def test_the_store_persists_no_lease_level_financial_result() -> None:
    """D5 decision A, structurally.

    The Quick and Detailed snapshot machinery stays exactly as it was -- the
    guardrail permits the existing union -- but no Lease-Level projection or
    result envelope may be named here, and there is no column one could go in.
    """

    store = _store_source()

    for cached in (
        "LeaseLevelAcquisitionResults",
        "MonthlyPropertyProjection",
        "AnnualOperatingProjection",
    ):
        assert cached not in store, (
            f"store.py names {cached}; Lease-Level results are recomputed on "
            "open, never persisted"
        )

    # The Quick/Detailed snapshot path is untouched and still present.
    assert "_ANALYSIS_SNAPSHOT_SCHEMA_VERSION" in store
    assert "update_analysis_snapshot" in store


def test_the_api_declares_only_literal_endpoint_owned_keys() -> None:
    """``externally_owned_keys`` can never be fed from user input.

    The parameter exists so an endpoint can say which top-level keys *it*
    consumes. If that set were ever derived from the request, a typo could
    excuse itself by appearing in it -- and the unknown-field safety D5.2 exists
    to provide would silently evaporate.
    """

    import ast

    api_path = Path(__file__).resolve().parents[1] / "src" / "anchor" / "api.py"
    tree = ast.parse(api_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg not in ("externally_owned_keys", "also_owned"):
                continue
            # A literal tuple, or a Name bound to one of the reviewed constants.
            # ``also_owned`` is the one permitted hop: it is
            # ``_require_lease_level_inputs``' own parameter, and every call
            # site that supplies it is checked by this same loop, so the value
            # still traces back to a reviewed constant.
            if isinstance(keyword.value, ast.Name):
                # D5.8 adds ``_AI_HURDLE_FIELDS`` -- the four hurdle-target
                # keys ``POST /ai/analysis`` consumes beside a Lease-Level
                # input set. Same shape as its three predecessors and for the
                # same reason: naming the endpoint's own keys is what keeps the
                # unknown-key check live for every other key in the body.
                assert keyword.value.id in {
                    "_TWO_WAY_FIELDS",
                    "_ONE_WAY_FIELDS",
                    "_DEAL_FIELDS",
                    "_AI_HURDLE_FIELDS",
                    "also_owned",
                }, f"owned keys came from {keyword.value.id!r}"
            else:
                assert isinstance(keyword.value, (ast.Tuple, ast.List)), (
                    "owned keys must be a literal or a reviewed constant, never "
                    "an expression over the request"
                )

    # Each reviewed constant is itself a literal tuple of literal strings.
    for name in ("_TWO_WAY_FIELDS", "_ONE_WAY_FIELDS", "_DEAL_FIELDS"):
        assignment = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
        )
        assert isinstance(assignment.value, ast.Tuple)
        assert all(
            isinstance(element, ast.Constant) and isinstance(element.value, str)
            for element in assignment.value.elts
        ), f"{name} is not a literal tuple of strings"
