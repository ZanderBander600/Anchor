"""Phase 7 Gate P7.2 -- the Investment shell and Scenario persistence, at the
store.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 8.2 and
15.1-15.2, and the Section 21 record (Q3, Q4). Every row count is read from the
database directly (``_p7_2_fixtures``), never through the store under test.

- **Opt-in only.** Nothing but a Deal's first valid Scenario materializes an
  Investment; every ordinary Deal operation and every read leaves the five P7.2
  tables empty.
- **Membership.** A Deal belongs to at most one Investment; a malformed or
  visible structure fails closed.
- **The P7.1 contract, faithfully.** A Scenario round-trips exactly, is
  validated by the P7.1 validator on the way in and on the way out, and its
  override order never matters.
- **Lifecycle.** Deleting the wrapper's Deal takes the wrapper with it; deleting
  the Investment releases the Deal; deleting the last Scenario collapses the
  wrapper.
- **Transactions.** Every multi-row operation rolls back whole.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from anchor.analysis.scenario import (
    ScenarioDefinition,
    ScenarioIssueCode,
    ScenarioTarget,
    ScenarioValidationError,
)
from anchor.contracts import OperatingMode
from anchor.deals import store
from anchor.deals.contracts import (
    DealNotFoundError,
    Investment,
    InvestmentNotFoundError,
    InvestmentStructureError,
    InvestmentUnit,
    ScenarioNotFoundError,
)

from _p7_2_fixtures import (  # type: ignore[import-not-found]
    EMPTY,
    MODES,
    analyze_deal,
    create_deal,
    deal_fingerprint,
    economic_override,
    execute,
    legacy_rows,
    override,
    row_counts,
    rows,
    second_override,
    update_deal,
)
import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_2.db"


def _codes(error: ScenarioValidationError) -> list[str]:
    return [issue.code.value for issue in error.issues]


# =============================================================================
# Schema v8
# =============================================================================


def test_a_fresh_store_is_schema_8_with_the_five_tables_empty(db: Path) -> None:
    store.list_deals(db_path=db)

    connection = sqlite3.connect(db)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()
    assert version == 9  # P7.4 added schema version 9's eight Strategy tables
    assert row_counts(db) == EMPTY


def test_the_membership_column_is_unique_at_the_persistence_layer(db: Path) -> None:
    """Q3 in the schema itself: a second membership for one Deal is
    unwritable, whatever code tries."""

    deal = create_deal("quick", db)
    execute(db, "INSERT INTO investment_units (investment_id, deal_id) VALUES (?, ?)", ("a" * 32, deal.id))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        execute(db, "INSERT INTO investment_units (investment_id, deal_id) VALUES (?, ?)", ("b" * 32, deal.id))


def test_the_override_key_is_unit_and_target_at_the_persistence_layer(db: Path) -> None:
    """SC-1 in the schema: at most one override per (scenario, unit, target)."""

    store.list_deals(db_path=db)
    execute(db, "INSERT INTO scenario_overrides VALUES ('s', 'u', 'ltv', 'cap_at', 0.5)")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        execute(db, "INSERT INTO scenario_overrides VALUES ('s', 'u', 'ltv', 'cap_at', 0.4)")


# =============================================================================
# Opt-in only (Q4)
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_ordinary_deal_workflow_never_materializes_an_investment(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    assert row_counts(db) == EMPTY

    saved = update_deal(deal, db, hold_period=6)
    store.get_deal(deal.id, db_path=db)
    store.list_deals(db_path=db)
    analyze_deal(saved)
    deal_fingerprint(saved)
    copy = store.duplicate_deal(deal.id, db_path=db)
    assert store.list_deal_scenarios(deal.id, db_path=db) == (None, [])
    assert store.list_deal_scenarios(copy.id, db_path=db) == (None, [])
    store.delete_deal(copy.id, db_path=db)

    assert row_counts(db) == EMPTY


@pytest.mark.parametrize("mode", MODES)
def test_the_first_valid_scenario_materializes_exactly_one_hidden_investment(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)

    record = store.create_scenario_for_deal(
        deal.id, name="Downside", overrides=(economic_override(mode, deal.id),), db_path=db
    )

    assert row_counts(db) == {
        "investments": 1,
        "investment_units": 1,
        "scenarios": 1,
        "scenario_overrides": 1,
        "variant_snapshots": 0,
    }
    ((investment_id, is_hidden, *_),) = rows(db, "investments")
    assert (investment_id, is_hidden) == (record.investment_id, 1)
    assert rows(db, "investment_units") == [(record.investment_id, deal.id)]
    investment = store.get_investment(record.investment_id, db_path=db)
    assert investment.hidden is True
    assert investment.units == (InvestmentUnit(unit_id=deal.id),)


@pytest.mark.parametrize("mode", MODES)
def test_additional_scenarios_reuse_the_same_investment(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    first = store.create_scenario_for_deal(deal.id, name="One", db_path=db)
    second = store.create_scenario_for_deal(
        deal.id, name="Two", overrides=(economic_override(mode, deal.id),), db_path=db
    )
    third = store.create_scenario(
        first.investment_id, name="Three", overrides=(second_override(mode, deal.id),), db_path=db
    )

    assert first.investment_id == second.investment_id == third.investment_id
    assert row_counts(db)["investments"] == 1
    assert row_counts(db)["investment_units"] == 1
    assert [r.scenario.name for r in store.list_scenarios(first.investment_id, db_path=db)] == [
        "One", "Two", "Three",
    ]


_INVALID_FIRST_SCENARIOS = {
    "unknown-target": ("name", ("target", "nope"), ScenarioIssueCode.UNKNOWN_TARGET),
    "unknown-operation": ("name", ("operation", "divide"), ScenarioIssueCode.UNKNOWN_OPERATION),
    "operation-not-whitelisted": ("name", ("ltv-set", None), ScenarioIssueCode.OPERATION_NOT_ALLOWED),
    "non-finite": ("name", ("value", float("inf")), ScenarioIssueCode.NON_FINITE_VALUE),
    "non-numeric": ("name", ("value", "0.01"), ScenarioIssueCode.NON_NUMERIC_VALUE),
    "boolean": ("name", ("value", True), ScenarioIssueCode.NON_NUMERIC_VALUE),
    "foreign-unit": ("name", ("unit_id", "someone-else"), ScenarioIssueCode.UNIT_NOT_IN_VARIANT),
    "blank-unit": ("name", ("unit_id", " "), ScenarioIssueCode.INVALID_UNIT_ID),
    "blank-name": ("  ", None, ScenarioIssueCode.INVALID_SCENARIO_NAME),
    "duplicate": ("name", ("duplicate", None), ScenarioIssueCode.DUPLICATE_TARGET),
}


@pytest.mark.parametrize("case", sorted(_INVALID_FIRST_SCENARIOS))
def test_an_invalid_first_scenario_leaves_no_row_behind(db: Path, case: str) -> None:
    deal = create_deal("quick", db)
    name, change, expected = _INVALID_FIRST_SCENARIOS[case]
    good = override(deal.id, "exit_cap_rate", "add", 0.005)
    overrides = [good]
    if change is not None:
        key, value = change
        if key == "duplicate":
            overrides = [good, override(deal.id, "exit_cap_rate", "set", 0.07)]
        elif key == "ltv-set":
            overrides = [override(deal.id, "ltv", "set", 0.5)]
        elif key == "target":
            overrides = [override(deal.id, value, "add", 0.005)]
        elif key == "operation":
            overrides = [override(deal.id, "exit_cap_rate", value, 0.005)]
        elif key == "value":
            overrides = [override(deal.id, "exit_cap_rate", "add", value)]
        elif key == "unit_id":
            overrides = [override(value, "exit_cap_rate", "add", 0.005)]

    with pytest.raises(ScenarioValidationError) as raised:
        store.create_scenario_for_deal(deal.id, name=name, overrides=overrides, db_path=db)

    assert expected.value in _codes(raised.value)
    assert row_counts(db) == EMPTY


def test_a_target_outside_the_deal_mode_is_refused(db: Path) -> None:
    deal = create_deal("detailed", db)
    with pytest.raises(ScenarioValidationError) as raised:
        store.create_scenario_for_deal(
            deal.id, name="Growth", overrides=(override(deal.id, "noi_growth", "add", 0.01),), db_path=db
        )
    assert _codes(raised.value) == [ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE.value]
    assert row_counts(db) == EMPTY


def test_a_scenario_for_a_missing_deal_writes_nothing(db: Path) -> None:
    store.list_deals(db_path=db)
    with pytest.raises(DealNotFoundError):
        store.create_scenario_for_deal("f" * 32, name="Orphan", db_path=db)
    assert row_counts(db) == EMPTY


# =============================================================================
# Scenario persistence -- the exact P7.1 contract
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_a_scenario_round_trips_the_exact_p7_1_contract(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    overrides = (second_override(mode, deal.id), economic_override(mode, deal.id))

    created = store.create_scenario_for_deal(
        deal.id, name="Recession 2027", description="Rates up, rents down.", overrides=overrides, db_path=db
    )
    reread = store.get_scenario(created.investment_id, created.scenario.scenario_id, db_path=db)

    canonical = tuple(
        sorted(overrides, key=lambda o: (o.unit_id, list(ScenarioTarget).index(o.target)))
    )
    assert reread == created
    assert reread.scenario == ScenarioDefinition(
        scenario_id=created.scenario.scenario_id,
        name="Recession 2027",
        description="Rates up, rents down.",
        overrides=canonical,
    )
    assert all(type(o.value) is float for o in reread.scenario.overrides)
    assert store.list_scenarios(created.investment_id, db_path=db) == [created]
    assert store.list_deal_scenarios(deal.id, db_path=db) == (created.investment_id, [created])


def test_a_minted_scenario_id_is_opaque_nonblank_and_never_the_reserved_base_key(db: Path) -> None:
    deal = create_deal("quick", db)
    ids = {store.create_scenario_for_deal(deal.id, name=f"S{n}", db_path=db).scenario.scenario_id for n in range(5)}
    assert len(ids) == 5
    for scenario_id in ids:
        assert len(scenario_id) == 32 and set(scenario_id) <= set("0123456789abcdef")
        assert scenario_id != store._BASE_STRATEGY_ID


def test_override_order_is_never_economic_meaning(db: Path) -> None:
    deal = create_deal("lease_level", db)
    forward = (
        override(deal.id, "interest_rate", "add", 0.01),
        override(deal.id, "market_rent_psf", "scale", 0.9),
        override(deal.id, "expense_growth", "set", 0.035),
    )
    first = store.create_scenario_for_deal(deal.id, name="A", overrides=forward, db_path=db)
    second = store.create_scenario_for_deal(deal.id, name="A", overrides=tuple(reversed(forward)), db_path=db)

    assert first.scenario.overrides == second.scenario.overrides
    assert [o.target for o in first.scenario.overrides] == [
        ScenarioTarget.INTEREST_RATE, ScenarioTarget.EXPENSE_GROWTH, ScenarioTarget.MARKET_RENT_PSF,
    ]


def test_an_update_keeps_the_identity_and_replaces_the_whole_override_set(db: Path) -> None:
    deal = create_deal("quick", db)
    created = store.create_scenario_for_deal(
        deal.id, name="Before", overrides=(economic_override("quick", deal.id),), db_path=db
    )
    scenario_id = created.scenario.scenario_id

    updated = store.update_scenario(
        created.investment_id, scenario_id, name="After", description="Edited",
        overrides=(second_override("quick", deal.id),), db_path=db,
    )

    assert updated.scenario.scenario_id == scenario_id
    assert updated.investment_id == created.investment_id
    assert updated.created_at == created.created_at
    assert updated.updated_at >= created.updated_at
    assert (updated.scenario.name, updated.scenario.description) == ("After", "Edited")
    assert updated.scenario.overrides == (second_override("quick", deal.id),)
    assert rows(db, "scenario_overrides") == [(scenario_id, deal.id, "interest_rate", "add", 0.01)]


def test_an_invalid_update_changes_nothing(db: Path) -> None:
    deal = create_deal("quick", db)
    created = store.create_scenario_for_deal(
        deal.id, name="Keep", overrides=(economic_override("quick", deal.id),), db_path=db
    )
    before = {table: rows(db, table) for table in ("scenarios", "scenario_overrides")}

    with pytest.raises(ScenarioValidationError) as raised:
        store.update_scenario(
            created.investment_id, created.scenario.scenario_id, name="Keep",
            overrides=(override("another-deal", "exit_cap_rate", "add", 0.01),), db_path=db,
        )

    assert _codes(raised.value) == [ScenarioIssueCode.UNIT_NOT_IN_VARIANT.value]
    assert {table: rows(db, table) for table in ("scenarios", "scenario_overrides")} == before


# =============================================================================
# Stored state that no longer validates fails closed, in a deterministic order
# =============================================================================


def _stored_scenario(db: Path) -> tuple[str, str, str]:
    deal = create_deal("quick", db)
    record = store.create_scenario_for_deal(
        deal.id, name="Stored", overrides=(economic_override("quick", deal.id),), db_path=db
    )
    return deal.id, record.investment_id, record.scenario.scenario_id


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("target", "not_a_target", ScenarioIssueCode.UNKNOWN_TARGET),
        ("operation", "divide", ScenarioIssueCode.UNKNOWN_OPERATION),
        ("operation", "cap_at", ScenarioIssueCode.OPERATION_NOT_ALLOWED),
        ("value", float("inf"), ScenarioIssueCode.NON_FINITE_VALUE),
        ("target", "noi_growth", None),  # valid for Quick: stays readable
        ("unit_id", "someone-else", ScenarioIssueCode.UNIT_NOT_IN_VARIANT),
    ],
)
def test_a_stored_scenario_that_no_longer_validates_fails_closed(
    db: Path, column: str, value: object, code: ScenarioIssueCode | None
) -> None:
    _, investment_id, scenario_id = _stored_scenario(db)
    execute(db, f"UPDATE scenario_overrides SET {column} = ?", (value,))

    if code is None:
        assert store.get_scenario(investment_id, scenario_id, db_path=db).scenario.overrides[0].target is ScenarioTarget.NOI_GROWTH
        return
    for read in (
        lambda: store.get_scenario(investment_id, scenario_id, db_path=db),
        lambda: store.list_scenarios(investment_id, db_path=db),
    ):
        with pytest.raises(store.PersistedScenarioDataError) as raised:
            read()
        assert [issue.code for issue in raised.value.issues] == [code]


def test_several_malformed_stored_overrides_report_in_one_order_whatever_the_row_order(
    tmp_path: Path,
) -> None:
    """The issue order comes from the P7.1 validator (unit, then registry
    order), never from the order SQLite returns rows in."""

    malformed = [
        ("interest_rate", "divide", 0.01),
        ("exit_cap_rate", "add", float("inf")),
        ("ltv", "set", 0.5),
        ("not_a_target", "add", 0.01),
    ]
    reports = []
    for label, order in (("forward", malformed), ("reversed", list(reversed(malformed)))):
        db = tmp_path / f"{label}.db"
        deal_id, investment_id, scenario_id = _stored_scenario(db)
        execute(db, "DELETE FROM scenario_overrides")
        for target, operation, value in order:
            execute(
                db, "INSERT INTO scenario_overrides VALUES (?, ?, ?, ?, ?)",
                (scenario_id, deal_id, target, operation, value),
            )
        with pytest.raises(store.PersistedScenarioDataError) as raised:
            store.get_scenario(investment_id, scenario_id, db_path=db)
        reports.append([(i.code.value, i.target.value if i.target else None) for i in raised.value.issues])

    assert reports[0] == reports[1] == [
        ("unknown_target", None),
        ("non_finite_value", "exit_cap_rate"),
        ("unknown_operation", "interest_rate"),
        ("operation_not_allowed", "ltv"),
    ]


# =============================================================================
# Membership and structure fail closed
# =============================================================================


def _visible_investment(db: Path, deal_id: str) -> str:
    investment_id = "v" * 32
    execute(db, "INSERT INTO investments VALUES (?, 0, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')", (investment_id,))
    execute(db, "INSERT INTO investment_units VALUES (?, ?)", (investment_id, deal_id))
    return investment_id


def test_a_visible_investment_is_refused_by_every_p7_2_mutation_and_never_orphaned(db: Path) -> None:
    deal = create_deal("quick", db)
    investment_id = _visible_investment(db, deal.id)
    before = legacy_rows(db), row_counts(db)

    visible = store.get_investment(investment_id, db_path=db)
    assert isinstance(visible, Investment)
    assert (visible.hidden, visible.units) == (False, (InvestmentUnit(unit_id=deal.id),))
    for refused in (
        lambda: store.create_scenario_for_deal(deal.id, name="S", db_path=db),
        lambda: store.create_scenario(investment_id, name="S", db_path=db),
        lambda: store.list_scenarios(investment_id, db_path=db),
        lambda: store.list_deal_scenarios(deal.id, db_path=db),
        lambda: store.delete_investment(investment_id, db_path=db),
        lambda: store.delete_deal(deal.id, db_path=db),
    ):
        with pytest.raises(InvestmentStructureError):
            refused()
    assert (legacy_rows(db), row_counts(db)) == before
    assert store.get_deal(deal.id, db_path=db).id == deal.id


@pytest.mark.parametrize("units", [0, 2])
def test_a_hidden_wrapper_without_exactly_one_unit_fails_closed(db: Path, units: int) -> None:
    deal = create_deal("quick", db)
    other = create_deal("quick", db)
    record = store.create_scenario_for_deal(deal.id, name="S", db_path=db)
    if units == 0:
        execute(db, "DELETE FROM investment_units")
    else:
        execute(db, "INSERT INTO investment_units VALUES (?, ?)", (record.investment_id, other.id))

    for read in (
        lambda: store.get_investment(record.investment_id, db_path=db),
        lambda: store.list_scenarios(record.investment_id, db_path=db),
        lambda: store.delete_investment(record.investment_id, db_path=db),
    ):
        with pytest.raises(store.PersistedDealDataError):
            read()


def test_a_membership_naming_no_saved_deal_fails_closed(db: Path) -> None:
    deal = create_deal("quick", db)
    record = store.create_scenario_for_deal(deal.id, name="S", db_path=db)
    execute(db, "UPDATE investment_units SET deal_id = ?", ("0" * 32,))

    with pytest.raises(store.PersistedDealDataError, match="not a saved deal"):
        store.get_scenario(record.investment_id, record.scenario.scenario_id, db_path=db)


def test_a_deal_in_two_investments_fails_closed_rather_than_picking_one(tmp_path: Path) -> None:
    """A table built without the UNIQUE constraint (the constraint cannot be
    added to an existing table) holding two memberships for one Deal is
    corrupt: every path that asks which Investment the Deal belongs to refuses
    it, and the Deal itself survives."""

    db = tmp_path / "corrupt.db"
    execute(db, "CREATE TABLE investment_units (investment_id TEXT NOT NULL, deal_id TEXT NOT NULL)")
    deal = create_deal("quick", db)
    for investment_id in ("a" * 32, "b" * 32):
        execute(db, "INSERT INTO investments VALUES (?, 1, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')", (investment_id,))
        execute(db, "INSERT INTO investment_units VALUES (?, ?)", (investment_id, deal.id))

    for refused in (
        lambda: store.list_deal_scenarios(deal.id, db_path=db),
        lambda: store.create_scenario_for_deal(deal.id, name="S", db_path=db),
        lambda: store.delete_deal(deal.id, db_path=db),
    ):
        with pytest.raises(store.PersistedDealDataError, match="at most one"):
            refused()
    assert store.get_deal(deal.id, db_path=db).id == deal.id


def test_an_unknown_investment_is_not_found(db: Path) -> None:
    store.list_deals(db_path=db)
    for read in (
        lambda: store.get_investment("x", db_path=db),
        lambda: store.list_scenarios("x", db_path=db),
        lambda: store.delete_investment("x", db_path=db),
        lambda: store.create_scenario("x", name="S", db_path=db),
    ):
        with pytest.raises(InvestmentNotFoundError):
            read()


def test_a_scenario_is_found_only_through_the_investment_that_owns_it(db: Path) -> None:
    deal_a, deal_b = create_deal("quick", db), create_deal("quick", db)
    a = store.create_scenario_for_deal(deal_a.id, name="A", db_path=db)
    b = store.create_scenario_for_deal(deal_b.id, name="B", overrides=(economic_override("quick", deal_b.id),), db_path=db)
    before = rows(db, "scenarios"), rows(db, "scenario_overrides")

    foreign = b.scenario.scenario_id
    for refused in (
        lambda: store.get_scenario(a.investment_id, foreign, db_path=db),
        lambda: store.update_scenario(a.investment_id, foreign, name="Hijack", db_path=db),
        lambda: store.delete_scenario(a.investment_id, foreign, db_path=db),
    ):
        with pytest.raises(ScenarioNotFoundError):
            refused()
    assert (rows(db, "scenarios"), rows(db, "scenario_overrides")) == before


# =============================================================================
# Lifecycle
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_deleting_the_wrappers_deal_removes_the_whole_wrapper(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    bystander = create_deal(mode, db)
    kept = store.create_scenario_for_deal(bystander.id, name="Kept", overrides=(economic_override(mode, bystander.id),), db_path=db)
    store.create_scenario_for_deal(deal.id, name="S1", overrides=(economic_override(mode, deal.id),), db_path=db)
    store.create_scenario_for_deal(deal.id, name="S2", db_path=db)
    execute(db, "INSERT INTO variant_snapshots VALUES (?, 'base', ?, '{}', 1, 'fp', 'now')",
            (store.list_deal_scenarios(deal.id, db_path=db)[0], "any"))

    store.delete_deal(deal.id, db_path=db)

    with pytest.raises(DealNotFoundError):
        store.get_deal(deal.id, db_path=db)
    assert row_counts(db) == {
        "investments": 1, "investment_units": 1, "scenarios": 1, "scenario_overrides": 1, "variant_snapshots": 0,
    }
    assert store.list_scenarios(kept.investment_id, db_path=db) == [kept]


@pytest.mark.parametrize("mode", MODES)
def test_deleting_the_investment_releases_the_deal_unchanged(db: Path, mode: str) -> None:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    before = legacy_rows(db)
    record = store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override(mode, deal.id),), db_path=db)

    store.delete_investment(record.investment_id, db_path=db)

    assert row_counts(db) == EMPTY
    assert legacy_rows(db) == before
    assert store.get_deal(deal.id, db_path=db) == deal
    again = store.create_scenario_for_deal(deal.id, name="Again", db_path=db)
    assert again.investment_id != record.investment_id


def test_deleting_one_of_several_scenarios_keeps_the_wrapper(db: Path) -> None:
    deal = create_deal("quick", db)
    keep = store.create_scenario_for_deal(deal.id, name="Keep", overrides=(economic_override("quick", deal.id),), db_path=db)
    drop = store.create_scenario_for_deal(deal.id, name="Drop", overrides=(second_override("quick", deal.id),), db_path=db)
    execute(db, "INSERT INTO variant_snapshots VALUES (?, 'base', ?, '{}', 1, 'fp', 'now')", (drop.investment_id, drop.scenario.scenario_id))

    store.delete_scenario(drop.investment_id, drop.scenario.scenario_id, db_path=db)

    assert store.list_scenarios(keep.investment_id, db_path=db) == [
        store.get_scenario(keep.investment_id, keep.scenario.scenario_id, db_path=db)
    ]
    assert row_counts(db) == {
        "investments": 1, "investment_units": 1, "scenarios": 1, "scenario_overrides": 1, "variant_snapshots": 0,
    }


@pytest.mark.parametrize("mode", MODES)
def test_deleting_the_last_scenario_returns_the_deal_to_a_pure_standalone_deal(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    before = legacy_rows(db)
    record = store.create_scenario_for_deal(deal.id, name="Only", overrides=(economic_override(mode, deal.id),), db_path=db)

    store.delete_scenario(record.investment_id, record.scenario.scenario_id, db_path=db)

    assert row_counts(db) == EMPTY
    assert legacy_rows(db) == before
    assert store.list_deal_scenarios(deal.id, db_path=db) == (None, [])
    with pytest.raises(InvestmentNotFoundError):
        store.get_investment(record.investment_id, db_path=db)


@pytest.mark.parametrize("mode", MODES)
def test_duplicating_a_deal_in_a_wrapper_copies_no_scenario_ownership(db: Path, mode: str) -> None:
    """P7.2 leaves Duplicate exactly as it was: the copy is a standalone Deal
    with no Investment, and the source's Scenarios are untouched."""

    deal = create_deal(mode, db)
    record = store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override(mode, deal.id),), db_path=db)
    counts = row_counts(db)

    copy = store.duplicate_deal(deal.id, db_path=db)

    assert row_counts(db) == counts
    assert store.list_deal_scenarios(copy.id, db_path=db) == (None, [])
    assert store.list_deal_scenarios(deal.id, db_path=db) == (record.investment_id, [record])


# =============================================================================
# Transactions -- every multi-row operation rolls back whole
# =============================================================================


def _boom(*args: object, **kwargs: object) -> None:
    raise RuntimeError("injected failure")


def test_first_scenario_creation_rolls_back_whole(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The overrides are written last, after the Investment, membership and
    Scenario rows; failing there must leave none of them."""

    deal = create_deal("quick", db)
    monkeypatch.setattr(store, "_write_scenario_overrides", _boom)

    with pytest.raises(RuntimeError, match="injected"):
        store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override("quick", deal.id),), db_path=db)

    assert row_counts(db) == EMPTY


def test_a_scenario_update_rolls_back_whole(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal = create_deal("quick", db)
    record = store.create_scenario_for_deal(deal.id, name="Before", overrides=(economic_override("quick", deal.id),), db_path=db)
    before = {table: rows(db, table) for table in ("investments", "scenarios", "scenario_overrides")}
    monkeypatch.setattr(store, "_write_scenario_overrides", _boom)

    with pytest.raises(RuntimeError, match="injected"):
        store.update_scenario(
            record.investment_id, record.scenario.scenario_id, name="After",
            overrides=(second_override("quick", deal.id),), db_path=db,
        )

    assert {table: rows(db, table) for table in before} == before
    monkeypatch.undo()
    assert store.get_scenario(record.investment_id, record.scenario.scenario_id, db_path=db) == record


@pytest.mark.parametrize("last", [True, False])
def test_a_scenario_deletion_rolls_back_whole(db: Path, monkeypatch: pytest.MonkeyPatch, last: bool) -> None:
    deal = create_deal("quick", db)
    record = store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override("quick", deal.id),), db_path=db)
    if not last:
        store.create_scenario_for_deal(deal.id, name="Other", db_path=db)
    before = {table: rows(db, table) for table in ("investments", "investment_units", "scenarios", "scenario_overrides")}
    monkeypatch.setattr(store, "_delete_investment_rows" if last else "_touch_investment", _boom)

    with pytest.raises(RuntimeError, match="injected"):
        store.delete_scenario(record.investment_id, record.scenario.scenario_id, db_path=db)

    assert {table: rows(db, table) for table in before} == before


def test_a_wrapper_deal_deletion_rolls_back_whole(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The wrapper is removed first; a failure afterwards, while the Deal's own
    rows are being deleted, must restore the wrapper and the Deal alike."""

    deal = create_deal("quick", db, business_plan=fx.business_plan())
    store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override("quick", deal.id),), db_path=db)
    before = legacy_rows(db), {table: rows(db, table) for table in ("investments", "investment_units", "scenarios", "scenario_overrides")}
    monkeypatch.setattr(store, "_delete_business_plan", _boom)

    with pytest.raises(RuntimeError, match="injected"):
        store.delete_deal(deal.id, db_path=db)

    assert (legacy_rows(db), {table: rows(db, table) for table in before[1]}) == before


def test_an_investment_deletion_rolls_back_whole(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal = create_deal("quick", db)
    record = store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override("quick", deal.id),), db_path=db)
    execute(db, "INSERT INTO variant_snapshots VALUES (?, 'base', ?, '{}', 1, 'fp', 'now')", (record.investment_id, record.scenario.scenario_id))
    before = {table: rows(db, table) for table in ("investments", "investment_units", "scenarios", "scenario_overrides", "variant_snapshots")}

    def partial(connection: sqlite3.Connection, investment_id: str) -> None:
        connection.execute("DELETE FROM variant_snapshots WHERE root_id = ?", (investment_id,))
        connection.execute("DELETE FROM scenarios WHERE investment_id = ?", (investment_id,))
        raise RuntimeError("injected failure")

    monkeypatch.setattr(store, "_delete_investment_rows", partial)
    with pytest.raises(RuntimeError, match="injected"):
        store.delete_investment(record.investment_id, db_path=db)

    assert {table: rows(db, table) for table in before} == before


# =============================================================================
# Ordinary Deal state is untouched by Scenario work
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_scenario_work_never_changes_the_deal(db: Path, mode: str) -> None:
    deal = create_deal(mode, db, business_plan=fx.business_plan())
    before = legacy_rows(db)

    record = store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override(mode, deal.id),), db_path=db)
    store.update_scenario(record.investment_id, record.scenario.scenario_id, name="T", overrides=(second_override(mode, deal.id),), db_path=db)
    store.create_scenario(record.investment_id, name="U", db_path=db)

    assert legacy_rows(db) == before
    assert store.get_deal(deal.id, db_path=db) == deal
    assert deal_fingerprint(store.get_deal(deal.id, db_path=db)) == deal_fingerprint(deal)
    assert store.get_deal(deal.id, db_path=db).operating_mode is OperatingMode(mode)
