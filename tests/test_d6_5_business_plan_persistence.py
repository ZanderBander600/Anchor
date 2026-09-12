"""Phase 6 Gate D6.5 -- the Business Plan is durable deal state.

What fails silently if wrong, and is therefore asserted here, in every mode:

- **Save/reopen is exact and financially identical.** A reopened deal carries
  the same plan -- items, order, categories, timing, amounts, ``last_year=None``
  -- and re-underwriting it from nothing but its stored state reproduces the
  original result (Closing, future and post-hold capital and owner expenses).
- **Replacement is whole.** An update replaces every plan row; an empty plan
  leaves no ghost rows.
- **Duplicate copies, delete removes.** A copy owns identical rows with the
  same result; deleting a deal leaves no plan row behind, proven by reading the
  tables directly.
- **Transactional.** A failure part-way through a save leaves the previous
  inputs and plan exactly as they were -- never half a plan.
- **Refused, not repaired.** Invalid plans are refused before a write, and
  corrupt stored rows are refused on read by the same validation authority.
- **D6.3 typing holds.** A plan-bearing snapshot still restores real
  ``IrrStatus`` members.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import warnings
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from anchor.business_plan import (
    BusinessPlan,
    BusinessPlanValidationError,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
    validate_business_plan,
)
from anchor.deals import store as deals_store
from anchor.deals.contracts import Deal, DealNotFoundError
from anchor.deals.store import PersistedDealDataError
from anchor.engine.contracts import IrrStatus

from _d6_5_fixtures import (  # type: ignore[import-not-found]
    MATERIAL,
    MODES,
    analysis_snapshot_payload,
    analyze,
    analyze_deal,
    create,
    input_fingerprint,
    plan_rows,
    reversed_plan,
    update,
)
from test_d6_2_owner_cash_flow_engine import QUICK  # type: ignore[import-not-found]

_PARENT_TABLES = ("deals", "detailed_deals", "lease_level_deals")
_PLAN_TABLES = ("deal_capital_plan_items", "deal_owner_expense_items")

#: One item, kept, and nothing else.
SMALLER = BusinessPlan(capital_items=(MATERIAL.capital_items[1],))

#: A valid model month (the contract sets no maximum) that SQLite's signed
#: 64-bit INTEGER cannot hold -- a real, reachable mid-write failure.
UNSTORABLE_MONTH = 2**63


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "d6-5.db"


def _total_plan_rows(db: Path) -> int:
    connection = sqlite3.connect(db)
    try:
        return sum(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in _PLAN_TABLES
        )
    finally:
        connection.close()


def _orphan_plan_rows(db: Path) -> int:
    connection = sqlite3.connect(db)
    try:
        parents = " UNION ".join(f"SELECT id FROM {table}" for table in _PARENT_TABLES)
        return sum(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE deal_id NOT IN ({parents})"
            ).fetchone()[0]
            for table in _PLAN_TABLES
        )
    finally:
        connection.close()


# =============================================================================
# Save / reopen
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_a_saved_plan_reopens_exactly(db: Path, mode: str) -> None:
    created = create(mode, db, business_plan=MATERIAL)
    reopened = deals_store.get_deal(created.id, db_path=db)

    assert created.business_plan == MATERIAL
    assert reopened.business_plan == MATERIAL
    # Declared order, not ID order.
    assert [item.item_id for item in reopened.business_plan.capital_items] == [
        "cap-C",
        "cap-A",
        "cap-B",
    ]
    assert [item.item_id for item in reopened.business_plan.owner_expense_items] == [
        "oe-Z",
        "oe-Y",
    ]
    # ``None`` stays ``None`` -- never the hold period.
    assert reopened.business_plan.owner_expense_items[0].last_year is None
    assert reopened.business_plan.owner_expense_items[1].last_year == 8
    for item in reopened.business_plan.capital_items:
        assert type(item.category) is CapitalItemCategory
        assert type(item.month) is int and type(item.amount) is float
    for item in reopened.business_plan.owner_expense_items:
        assert type(item.category) is OwnerExpenseCategory
        assert type(item.annual_amount) is float and type(item.first_year) is int


@pytest.mark.parametrize("mode", MODES)
def test_save_and_reopen_preserve_the_financial_result(db: Path, mode: str) -> None:
    """The oracle: the result re-underwritten from the reopened deal alone is
    the result the plan produced before it was ever saved."""

    before = analyze(mode, MATERIAL)
    deal = create(mode, db, business_plan=MATERIAL)

    assert analyze_deal(deals_store.get_deal(deal.id, db_path=db)) == before
    # Material in every channel the plan carries, and not the plan-free result.
    assert before.closing_project_capital == 250_000.0
    assert before.project_capital_by_year[1] == 1_000_000.0
    assert before.post_hold_project_capital == 300_000.0
    assert tuple(before.owner_expenses_by_year) == (50_000.0, 50_000.0, 50_000.0, 75_000.0, 75_000.0)
    assert before != analyze(mode, BusinessPlan())


@pytest.mark.parametrize("mode", MODES)
def test_a_deal_saved_without_a_plan_carries_the_empty_plan(db: Path, mode: str) -> None:
    deal = create(mode, db, business_plan=BusinessPlan())

    assert deals_store.get_deal(deal.id, db_path=db).business_plan == BusinessPlan()
    assert plan_rows(db, deal.id) == (0, 0)


def test_a_plan_free_caller_still_gets_the_empty_plan(db: Path) -> None:
    """The store's compatibility default: a caller that names no plan saves a
    deal with none."""

    deal = deals_store.create_deal("Plan-free", QUICK, db_path=db)

    assert deal.business_plan == BusinessPlan()
    assert plan_rows(db, deal.id) == (0, 0)


def test_the_library_lists_every_deal_with_its_own_plan(db: Path) -> None:
    planned = [create(mode, db, business_plan=MATERIAL) for mode in MODES]
    empty = create("detailed", db, business_plan=BusinessPlan())
    smaller = create("lease_level", db, business_plan=SMALLER)

    listed = {deal.id: deal for deal in deals_store.list_deals(db_path=db)}

    for deal in planned:
        assert listed[deal.id].business_plan == MATERIAL
    assert listed[empty.id].business_plan == BusinessPlan()
    assert listed[smaller.id].business_plan == SMALLER


# =============================================================================
# Update
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_an_update_replaces_the_plan_whole(db: Path, mode: str) -> None:
    deal = create(mode, db, business_plan=MATERIAL)
    assert plan_rows(db, deal.id) == (3, 2)

    assert update(mode, deal.id, db, business_plan=SMALLER).business_plan == SMALLER
    assert plan_rows(db, deal.id) == (1, 0)

    reordered = reversed_plan(MATERIAL)
    reopened = update(mode, deal.id, db, business_plan=reordered).business_plan
    assert reopened == reordered
    assert [item.item_id for item in reopened.capital_items] == ["cap-B", "cap-A", "cap-C"]

    assert update(mode, deal.id, db, business_plan=BusinessPlan()).business_plan == BusinessPlan()
    assert plan_rows(db, deal.id) == (0, 0)
    assert _orphan_plan_rows(db) == 0


# =============================================================================
# Duplicate / delete
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_a_duplicate_owns_an_identical_copy_of_the_plan(db: Path, mode: str) -> None:
    source = create(mode, db, business_plan=MATERIAL)
    copy = deals_store.duplicate_deal(source.id, db_path=db)

    assert copy.id != source.id
    assert copy.operating_mode is source.operating_mode
    assert copy.business_plan == MATERIAL
    assert analyze_deal(copy) == analyze_deal(source) == analyze(mode, MATERIAL)
    assert plan_rows(db, copy.id) == plan_rows(db, source.id) == (3, 2)

    # The rows are the copy's own: changing or deleting the source leaves them.
    update(mode, source.id, db, business_plan=BusinessPlan())
    assert deals_store.get_deal(copy.id, db_path=db).business_plan == MATERIAL
    deals_store.delete_deal(source.id, db_path=db)
    assert deals_store.get_deal(copy.id, db_path=db).business_plan == MATERIAL
    assert plan_rows(db, copy.id) == (3, 2)


@pytest.mark.parametrize("mode", MODES)
def test_delete_leaves_no_plan_row_behind(db: Path, mode: str) -> None:
    doomed = create(mode, db, business_plan=MATERIAL)
    survivor = create(mode, db, business_plan=MATERIAL)

    deals_store.delete_deal(doomed.id, db_path=db)

    assert plan_rows(db, doomed.id) == (0, 0)
    assert plan_rows(db, survivor.id) == (3, 2)
    assert _orphan_plan_rows(db) == 0
    with pytest.raises(DealNotFoundError):
        deals_store.get_deal(doomed.id, db_path=db)


def test_deleting_an_unknown_id_deletes_no_plan_row(db: Path) -> None:
    survivor = create("quick", db, business_plan=MATERIAL)

    with pytest.raises(DealNotFoundError):
        deals_store.delete_deal("no-such-deal", db_path=db)

    assert plan_rows(db, survivor.id) == (3, 2)


# =============================================================================
# Transactional safety
# =============================================================================


def _unstorable() -> BusinessPlan:
    """Two capital items; the second cannot be written, so the first one is
    written and then must be rolled back."""

    plan = BusinessPlan(
        capital_items=(
            MATERIAL.capital_items[1],
            dataclasses.replace(MATERIAL.capital_items[0], month=UNSTORABLE_MONTH),
        ),
        owner_expense_items=MATERIAL.owner_expense_items,
    )
    assert validate_business_plan(plan).is_valid  # the contract accepts it
    return plan


@pytest.mark.parametrize("mode", MODES)
def test_a_failed_update_leaves_the_previous_inputs_and_plan(db: Path, mode: str) -> None:
    deal = create(mode, db, business_plan=MATERIAL)

    with pytest.raises(OverflowError):
        update(
            mode,
            deal.id,
            db,
            business_plan=_unstorable(),
            name="Renamed",
            purchase_price=1_234_567.0,
        )

    reopened = deals_store.get_deal(deal.id, db_path=db)
    assert reopened.name == deal.name
    assert reopened.updated_at == deal.updated_at
    assert (reopened.inputs, reopened.terms) == (deal.inputs, deal.terms)
    assert reopened.business_plan == MATERIAL
    assert plan_rows(db, deal.id) == (3, 2)


@pytest.mark.parametrize("mode", MODES)
def test_a_failed_create_writes_nothing(db: Path, mode: str) -> None:
    with pytest.raises(OverflowError):
        create(mode, db, business_plan=_unstorable())

    assert deals_store.list_deals(db_path=db) == []
    assert _total_plan_rows(db) == 0


def test_the_store_refuses_an_invalid_plan_before_writing_anything(db: Path) -> None:
    """The one shared item-ID namespace is the validation authority's rule, not
    SQL's: the two tables cannot see each other's keys, so the store asks the
    authority before every write."""

    cross_type = BusinessPlan(
        capital_items=(dataclasses.replace(MATERIAL.capital_items[0], item_id="shared"),),
        owner_expense_items=(
            dataclasses.replace(MATERIAL.owner_expense_items[0], item_id="shared"),
        ),
    )

    with pytest.raises(BusinessPlanValidationError):
        create("quick", db, business_plan=cross_type)
    assert deals_store.list_deals(db_path=db) == []
    assert _total_plan_rows(db) == 0

    deal = create("detailed", db, business_plan=MATERIAL)
    with pytest.raises(BusinessPlanValidationError):
        update("detailed", deal.id, db, business_plan=cross_type)
    assert deals_store.get_deal(deal.id, db_path=db).business_plan == MATERIAL


# =============================================================================
# Corrupt stored rows are refused, never repaired
# =============================================================================


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param(
            "UPDATE deal_capital_plan_items SET category = 'contingency' "
            "WHERE deal_id = ? AND item_id = 'cap-A'",
            id="unknown-category-token",
        ),
        pytest.param(
            "UPDATE deal_owner_expense_items SET item_id = 'cap-A' "
            "WHERE deal_id = ? AND item_id = 'oe-Z'",
            id="cross-type-duplicate-id",
        ),
        pytest.param(
            "UPDATE deal_capital_plan_items SET description = '   ' "
            "WHERE deal_id = ? AND item_id = 'cap-A'",
            id="blank-description",
        ),
        pytest.param(
            "UPDATE deal_capital_plan_items SET month = 1.5 "
            "WHERE deal_id = ? AND item_id = 'cap-A'",
            id="fractional-month",
        ),
        pytest.param(
            "UPDATE deal_capital_plan_items SET amount = -5.0 "
            "WHERE deal_id = ? AND item_id = 'cap-A'",
            id="negative-amount",
        ),
        pytest.param(
            "UPDATE deal_owner_expense_items SET last_year = 2 "
            "WHERE deal_id = ? AND item_id = 'oe-Y'",
            id="last-year-before-first-year",
        ),
    ],
)
def test_corrupt_plan_rows_are_refused_not_repaired(db: Path, statement: str) -> None:
    deal = create("detailed", db, business_plan=MATERIAL)
    connection = sqlite3.connect(db)
    connection.execute(statement, (deal.id,))
    connection.commit()
    connection.close()

    with pytest.raises(PersistedDealDataError):
        deals_store.get_deal(deal.id, db_path=db)
    with pytest.raises(PersistedDealDataError):
        deals_store.list_deals(db_path=db)


# =============================================================================
# D6.3: IrrStatus still rehydrates through a plan-bearing snapshot
# =============================================================================


@pytest.mark.parametrize("mode", ("quick", "detailed"))
def test_irr_status_rehydrates_through_a_plan_bearing_round_trip(db: Path, mode: str) -> None:
    deal = create(mode, db, business_plan=MATERIAL)
    deals_store.update_analysis_snapshot(
        deal.id,
        analysis_snapshot_payload(mode, MATERIAL),
        financial_input_fingerprint=input_fingerprint(mode, MATERIAL),
        db_path=db,
    )

    reopened = deals_store.get_deal(deal.id, db_path=db)
    snapshot = reopened.analysis_snapshot
    assert snapshot is not None
    results = snapshot if mode == "quick" else snapshot.results  # type: ignore[union-attr]
    expected = analyze(mode, MATERIAL)

    assert results == expected
    assert type(results.levered_irr_status) is IrrStatus  # type: ignore[union-attr]
    assert type(results.unlevered_irr_status) is IrrStatus  # type: ignore[union-attr]
    assert results.levered_irr_status is expected.levered_irr_status  # type: ignore[union-attr]
    # The plan makes the levered stream non-conventional, so this is not the
    # default status restored by accident.
    assert expected.levered_irr_status is not IrrStatus.DEFINED
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        TypeAdapter(Deal).dump_json(reopened)


# =============================================================================
# Schema and contract shape
# =============================================================================


def test_the_plan_tables_are_mode_blind_and_carry_every_contract_field(db: Path) -> None:
    create("quick", db, business_plan=BusinessPlan())
    connection = sqlite3.connect(db)
    try:
        columns = {
            table: [
                (row[1], row[3]) for row in connection.execute(f"PRAGMA table_info({table})")
            ]
            for table in _PLAN_TABLES
        }
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        parent_columns = {
            row[1]
            for table in (*_PARENT_TABLES, "detailed_operating_inputs")
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
    finally:
        connection.close()

    # (name, NOT NULL): every contract field, plus the deal and the ordinal.
    assert columns["deal_capital_plan_items"] == [
        ("deal_id", 1), ("item_id", 1), ("ordinal", 1), ("description", 1),
        ("category", 1), ("month", 1), ("amount", 1),
    ]
    assert columns["deal_owner_expense_items"] == [
        ("deal_id", 1), ("item_id", 1), ("ordinal", 1), ("description", 1),
        ("category", 1), ("annual_amount", 1), ("first_year", 1), ("last_year", 0),
    ]
    for table, contract in zip(_PLAN_TABLES, (CapitalPlanItem, OwnerExpenseItem)):
        stored = {name for name, _ in columns[table]} - {"deal_id", "ordinal"}
        assert stored == {field.name for field in dataclasses.fields(contract)}

    # One representation for every mode: no per-mode plan table, and no plan
    # field folded into any mode's own columns.
    assert {table for table in tables if "capital" in table or "expense" in table} == set(
        _PLAN_TABLES
    )
    assert not parent_columns & {"business_plan", "capital_items", "owner_expense_items"}


def test_a_deal_never_carries_an_absent_plan(db: Path) -> None:
    deal = create("quick", db, business_plan=MATERIAL)

    with pytest.raises(ValueError, match="business_plan"):
        dataclasses.replace(deal, business_plan=None)
