"""Phase 6 Gate D6.5 -- the Business Plan in the deal fingerprint, and the stale
state it drives.

The fingerprint is the single authority that decides whether a stored analysis,
AI report or sensitivity run is still current. D6.5 adds the plan to it:

- **F1.** The empty plan adds nothing: every legacy digest is preserved byte for
  byte (decision D11), pinned against the pre-D6.5 tree.
- **F2-F8.** Every field of every item moves the digest -- including edits that
  change no cash flow (a description, a category, a month in the same hold year,
  an owner-expense year past the hold), because the AI Analyst, audit and
  reporting read them.
- **F9-F11.** Row order is presentation: reordering either collection, or both,
  leaves the digest -- and every snapshot -- exactly as they were.
- **F12.** An exact semantic revert restores the original digest.

Then, through the store, for every applicable snapshot of every mode: a plan
edit makes it stale without deleting it, an exact revert makes it current again,
and a reorder never disturbs it.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from anchor.deals import fingerprint as fingerprint_module
from anchor.deals import store as deals_store
from anchor.deals.contracts import Deal
from anchor.deals.fingerprint import UnfingerprintableValueError, fingerprint_ai
from anchor.deals.store import SnapshotValidationError

from _d6_5_fixtures import (  # type: ignore[import-not-found]
    MATERIAL,
    MODES,
    PRE_D6_5_DIGESTS,
    analysis_snapshot_payload,
    analyze,
    create,
    edit_item,
    fingerprint_with,
    input_fingerprint,
    reversed_plan,
    update,
)
from test_d5_4_lease_level_persistence import (  # type: ignore[import-not-found]
    LEASES,
    MARKET_LEASING,
    OPERATING_INPUTS,
    PROPERTY_INPUTS,
    SUITES,
    TERMS,
)
from test_d5_8a_deal_analysis_persistence import (  # type: ignore[import-not-found]
    AI_ANALYSIS,
    ONE_WAY,
    TWO_WAY,
    as_dict,
)
from test_d6_2_owner_cash_flow_engine import HOLD, QUICK  # type: ignore[import-not-found]

#: The pre-D5.4 / pre-D6.5 digests already pinned by
#: ``test_d5_4_migration_and_fingerprint.py``, plus the D5.4 rent roll's digest
#: captured from the pre-D6.5 tree.
_D5_4_LEASE_LEVEL_DIGEST = "424175f2fbdf24ccd90cd05f0c9dfdc74339e6d74f24a6b098238d43d8fa6b7e"


def fp(mode: str, business_plan: BusinessPlan) -> str:
    return input_fingerprint(mode, business_plan)


# =============================================================================
# F1 -- the empty plan preserves every legacy digest
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_f1_the_empty_plan_keeps_the_pre_d6_5_digest(mode: str) -> None:
    assert fp(mode, BusinessPlan()) == PRE_D6_5_DIGESTS[mode]
    # ... and so does the compatibility default a plan-free caller relies on.
    assert fingerprint_with(fingerprint_module, mode, None) == PRE_D6_5_DIGESTS[mode]


def test_f1_the_d5_4_rent_roll_keeps_its_digest() -> None:
    assert (
        fingerprint_module.fingerprint_lease_level_inputs(
            TERMS,
            PROPERTY_INPUTS,
            SUITES,
            LEASES,
            market_leasing=MARKET_LEASING,
            operating_inputs=OPERATING_INPUTS,
            business_plan=BusinessPlan(),
        )
        == _D5_4_LEASE_LEVEL_DIGEST
    )


@pytest.mark.parametrize("mode", MODES)
def test_any_non_empty_plan_moves_the_digest(mode: str) -> None:
    zero_dollar = BusinessPlan(
        capital_items=(dataclasses.replace(MATERIAL.capital_items[0], amount=0.0),)
    )
    capital_only = BusinessPlan(capital_items=MATERIAL.capital_items)
    owner_only = BusinessPlan(owner_expense_items=MATERIAL.owner_expense_items)

    digests = {
        fp(mode, plan)
        for plan in (BusinessPlan(), zero_dollar, capital_only, owner_only, MATERIAL)
    }
    assert len(digests) == 5


def test_no_two_modes_share_a_digest() -> None:
    assert len({fp(mode, plan) for mode in MODES for plan in (BusinessPlan(), MATERIAL)}) == 6


def test_an_absent_plan_is_refused_not_hashed() -> None:
    """``None`` is not the empty plan: hashing it as one would let a caller
    that lost a deal's plan certify snapshots for it."""

    with pytest.raises(UnfingerprintableValueError):
        fingerprint_module.fingerprint_quick_inputs(QUICK, business_plan=None)  # type: ignore[arg-type]


# =============================================================================
# F2-F8 -- every field moves the digest
# =============================================================================

_ADDED_CAPITAL = CapitalPlanItem(
    item_id="cap-D",
    description="Parking resurfacing",
    category=CapitalItemCategory.DEFERRED_MAINTENANCE,
    month=30,
    amount=80_000.0,
)
_ADDED_EXPENSE = OwnerExpenseItem(
    item_id="oe-X",
    description="Fund administration",
    category=OwnerExpenseCategory.OTHER,
    annual_amount=10_000.0,
    first_year=2,
    last_year=3,
)

#: ``(collection, index, changes)``. Each is an edit an analyst could make.
_EDITS: dict[str, tuple[str, int, dict[str, object]]] = {
    "f3-capital-amount": ("capital_items", 0, {"amount": 1_000_001.0}),
    "f4-capital-month": ("capital_items", 0, {"month": 30}),
    "f4-capital-month-same-hold-year": ("capital_items", 0, {"month": 19}),
    "f5-capital-description": ("capital_items", 0, {"description": "Roof replacement"}),
    "f6-capital-category": ("capital_items", 0, {"category": CapitalItemCategory.OTHER}),
    "capital-item-id": ("capital_items", 0, {"item_id": "cap-E"}),
    "f7-owner-expense-annual-amount": ("owner_expense_items", 0, {"annual_amount": 55_000.0}),
    "f7-owner-expense-description": ("owner_expense_items", 0, {"description": "AM fee"}),
    "f7-owner-expense-category": (
        "owner_expense_items",
        0,
        {"category": OwnerExpenseCategory.OTHER},
    ),
    "owner-expense-item-id": ("owner_expense_items", 0, {"item_id": "oe-W"}),
    "f8-first-year": ("owner_expense_items", 1, {"first_year": 5}),
    "f8-last-year": ("owner_expense_items", 1, {"last_year": 6}),
    "f8-last-year-past-the-hold": ("owner_expense_items", 1, {"last_year": 9}),
    "f8-open-ended-to-the-current-hold": ("owner_expense_items", 0, {"last_year": HOLD}),
}

#: Edits that change no cash flow at this hold -- the digest must move anyway.
_FINANCIALLY_SILENT = (
    "f4-capital-month-same-hold-year",
    "f5-capital-description",
    "f6-capital-category",
    "capital-item-id",
    "f7-owner-expense-description",
    "f7-owner-expense-category",
    "owner-expense-item-id",
    "f8-last-year-past-the-hold",
    "f8-open-ended-to-the-current-hold",
)


def _edited(name: str) -> BusinessPlan:
    collection, index, changes = _EDITS[name]
    return edit_item(MATERIAL, collection, index, **changes)


@pytest.mark.parametrize("mode", MODES)
def test_f2_adding_a_capital_item_moves_the_digest(mode: str) -> None:
    added = dataclasses.replace(
        MATERIAL, capital_items=(*MATERIAL.capital_items, _ADDED_CAPITAL)
    )
    assert fp(mode, added) != fp(mode, MATERIAL)


@pytest.mark.parametrize("mode", MODES)
def test_f7_adding_an_owner_expense_moves_the_digest(mode: str) -> None:
    added = dataclasses.replace(
        MATERIAL, owner_expense_items=(*MATERIAL.owner_expense_items, _ADDED_EXPENSE)
    )
    assert fp(mode, added) != fp(mode, MATERIAL)


@pytest.mark.parametrize("edit", sorted(_EDITS))
@pytest.mark.parametrize("mode", MODES)
def test_every_business_plan_field_moves_the_digest(mode: str, edit: str) -> None:
    assert fp(mode, _edited(edit)) != fp(mode, MATERIAL)


def test_every_item_field_is_covered_by_an_edit() -> None:
    edited = {
        (collection, field)
        for collection, _, changes in _EDITS.values()
        for field in changes
    }
    expected = {
        ("capital_items", field.name) for field in dataclasses.fields(CapitalPlanItem)
    } | {("owner_expense_items", field.name) for field in dataclasses.fields(OwnerExpenseItem)}
    assert edited == expected


@pytest.mark.parametrize("edit", _FINANCIALLY_SILENT)
@pytest.mark.parametrize("mode", MODES)
def test_a_narrative_edit_moves_the_digest_but_not_the_numbers(mode: str, edit: str) -> None:
    """Part X: identical cash flows, different plan -- so stale, on purpose."""

    assert analyze(mode, _edited(edit)) == analyze(mode, MATERIAL)
    assert fp(mode, _edited(edit)) != fp(mode, MATERIAL)


# =============================================================================
# F9-F12 -- order is presentation; an exact revert restores the digest
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_f9_to_f11_reordering_rows_leaves_the_digest(mode: str) -> None:
    capital_reordered = dataclasses.replace(
        MATERIAL, capital_items=tuple(reversed(MATERIAL.capital_items))
    )
    owner_reordered = dataclasses.replace(
        MATERIAL, owner_expense_items=tuple(reversed(MATERIAL.owner_expense_items))
    )

    assert fp(mode, capital_reordered) == fp(mode, MATERIAL)  # F9
    assert fp(mode, owner_reordered) == fp(mode, MATERIAL)  # F10
    assert fp(mode, reversed_plan(MATERIAL)) == fp(mode, MATERIAL)  # F11
    assert analyze(mode, reversed_plan(MATERIAL)) == analyze(mode, MATERIAL)


@pytest.mark.parametrize("mode", MODES)
def test_f12_an_exact_semantic_revert_restores_the_digest(mode: str) -> None:
    original = fp(mode, MATERIAL)
    edited = edit_item(MATERIAL, "capital_items", 0, amount=2.0)
    reverted = edit_item(edited, "capital_items", 0, amount=1_000_000.0)

    assert fp(mode, edited) != original
    assert reverted == MATERIAL and reverted is not MATERIAL
    assert fp(mode, reverted) == original


# =============================================================================
# Stale state, through the store
# =============================================================================


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "d6-5-stale.db"


def _attach_snapshots(mode: str, deal_id: str, db: Path, business_plan: BusinessPlan) -> None:
    """Every snapshot this mode persists, produced under ``business_plan``."""

    financial = fp(mode, business_plan)
    if mode != "lease_level":
        deals_store.update_analysis_snapshot(
            deal_id,
            analysis_snapshot_payload(mode, business_plan),
            financial_input_fingerprint=financial,
            db_path=db,
        )
    deals_store.update_ai_snapshot(
        deal_id,
        as_dict(AI_ANALYSIS),
        ai_context_fingerprint=fingerprint_ai(analysis_fingerprint=financial, deal_context=None),
        db_path=db,
    )
    if mode == "lease_level":
        deals_store.update_one_way_sensitivity_snapshot(
            deal_id, as_dict(ONE_WAY), financial_input_fingerprint=financial, db_path=db
        )
        deals_store.update_two_way_sensitivity_snapshot(
            deal_id, as_dict(TWO_WAY), financial_input_fingerprint=financial, db_path=db
        )


def _current(mode: str, deal: Deal) -> dict[str, bool]:
    """Which snapshots the store serves as current."""

    served = {"ai": deal.ai_snapshot is not None}
    if mode == "lease_level":
        served["one_way"] = deal.one_way_sensitivity_snapshot is not None
        served["two_way"] = deal.two_way_sensitivity_snapshot is not None
    else:
        served["analysis"] = deal.analysis_snapshot is not None
    return served


def _stored(mode: str, deal_id: str, db: Path) -> int:
    """How many snapshots are physically stored, current or not."""

    connection = sqlite3.connect(db)
    try:
        if mode == "lease_level":
            ai = connection.execute(
                "SELECT ai_snapshot IS NOT NULL FROM lease_level_deals WHERE id = ?", (deal_id,)
            ).fetchone()[0]
            runs = connection.execute(
                "SELECT COUNT(*) FROM deal_sensitivity_snapshots WHERE deal_id = ?", (deal_id,)
            ).fetchone()[0]
            return ai + runs
        table = "deals" if mode == "quick" else "detailed_deals"
        row = connection.execute(
            f"SELECT analysis_snapshot IS NOT NULL, ai_snapshot IS NOT NULL FROM {table} "
            "WHERE id = ?",
            (deal_id,),
        ).fetchone()
        return row[0] + row[1]
    finally:
        connection.close()


_ALL_STORED = {"quick": 2, "detailed": 2, "lease_level": 3}


def _planned_deal(mode: str, db: Path) -> Deal:
    deal = create(mode, db, business_plan=MATERIAL)
    _attach_snapshots(mode, deal.id, db, MATERIAL)
    fresh = deals_store.get_deal(deal.id, db_path=db)
    assert all(_current(mode, fresh).values()), _current(mode, fresh)
    return fresh


@pytest.mark.parametrize("mode", MODES)
def test_a_plan_edit_makes_every_snapshot_stale_and_an_exact_revert_restores_them(
    db: Path, mode: str
) -> None:
    deal = _planned_deal(mode, db)

    edited = update(
        mode, deal.id, db, business_plan=edit_item(MATERIAL, "capital_items", 0, amount=1.5e6)
    )
    assert not any(_current(mode, edited).values()), _current(mode, edited)
    # Stale is not deleted: D5 keeps the reference output, it just is not current.
    assert _stored(mode, deal.id, db) == _ALL_STORED[mode]

    rebuilt = BusinessPlan(
        capital_items=tuple(dataclasses.replace(item) for item in MATERIAL.capital_items),
        owner_expense_items=tuple(
            dataclasses.replace(item) for item in MATERIAL.owner_expense_items
        ),
    )
    reverted = update(mode, deal.id, db, business_plan=rebuilt)
    assert all(_current(mode, reverted).values()), _current(mode, reverted)


@pytest.mark.parametrize("mode", MODES)
def test_a_row_reorder_keeps_every_snapshot_current(db: Path, mode: str) -> None:
    deal = _planned_deal(mode, db)

    reordered = update(mode, deal.id, db, business_plan=reversed_plan(MATERIAL))

    assert reordered.business_plan == reversed_plan(MATERIAL)
    assert all(_current(mode, reordered).values()), _current(mode, reordered)


@pytest.mark.parametrize(
    "edit", ("f5-capital-description", "f6-capital-category", "f7-owner-expense-category")
)
@pytest.mark.parametrize("mode", MODES)
def test_a_description_or_category_edit_makes_snapshots_stale(
    db: Path, mode: str, edit: str
) -> None:
    deal = _planned_deal(mode, db)

    edited = update(mode, deal.id, db, business_plan=_edited(edit))

    assert not any(_current(mode, edited).values()), _current(mode, edited)


@pytest.mark.parametrize("mode", MODES)
def test_adding_and_removing_a_plan_moves_a_legacy_deal_s_snapshots(db: Path, mode: str) -> None:
    deal = create(mode, db, business_plan=BusinessPlan())
    _attach_snapshots(mode, deal.id, db, BusinessPlan())

    planned = update(mode, deal.id, db, business_plan=MATERIAL)
    assert not any(_current(mode, planned).values())

    cleared = update(mode, deal.id, db, business_plan=BusinessPlan())
    assert all(_current(mode, cleared).values())


@pytest.mark.parametrize("mode", MODES)
def test_a_snapshot_computed_under_another_plan_cannot_be_certified(
    db: Path, mode: str
) -> None:
    """Part Y: a pre-edit analysis can never be written as current for the
    edited deal -- the store recomputes the fingerprint, plan included."""

    deal = create(mode, db, business_plan=MATERIAL)
    plan_free = fp(mode, BusinessPlan())

    with pytest.raises(SnapshotValidationError):
        deals_store.update_ai_snapshot(
            deal.id,
            as_dict(AI_ANALYSIS),
            ai_context_fingerprint=fingerprint_ai(analysis_fingerprint=plan_free, deal_context=None),
            db_path=db,
        )
    if mode == "lease_level":
        with pytest.raises(SnapshotValidationError):
            deals_store.update_one_way_sensitivity_snapshot(
                deal.id, as_dict(ONE_WAY), financial_input_fingerprint=plan_free, db_path=db
            )
        with pytest.raises(SnapshotValidationError):
            deals_store.update_two_way_sensitivity_snapshot(
                deal.id, as_dict(TWO_WAY), financial_input_fingerprint=plan_free, db_path=db
            )
    else:
        with pytest.raises(SnapshotValidationError):
            deals_store.update_analysis_snapshot(
                deal.id,
                analysis_snapshot_payload(mode, BusinessPlan()),
                financial_input_fingerprint=plan_free,
                db_path=db,
            )
    assert _stored(mode, deal.id, db) == 0
