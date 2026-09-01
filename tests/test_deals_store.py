"""Tests for the Persistence Phase A SQLite store (``anchor.deals.store``).

Covers create/get/list/update, missing-id errors, list ordering, and --
the load-bearing property from the numeric-representation decision in
``store.py`` -- that a saved deal's ``AcquisitionInputs`` round-trip through
SQLite bit-for-bit, not merely "close enough".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anchor.contracts import AcquisitionInputs
from anchor.deals import Deal, DealNotFoundError
from anchor.deals.store import (
    create_deal,
    delete_deal,
    duplicate_deal,
    get_deal,
    list_deals,
    update_deal,
)

GOLDEN_INPUTS = AcquisitionInputs(
    purchase_price=50_000_000.0,
    current_noi=2_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.055,
    ltv=0.65,
    interest_rate=0.0525,
    amortization=30,
)

# Deliberately awkward binary fractions -- values that do not round-trip
# cleanly through most lossy numeric paths (e.g. via a string with limited
# precision, or a fixed-decimal coercion) but must round-trip exactly
# through IEEE 754 double storage.
AWKWARD_INPUTS = AcquisitionInputs(
    purchase_price=12_345_678.913571113,
    current_noi=999_999.0000000001,
    occupancy=0.123456789012345,
    noi_growth=0.030000000000004,
    hold_period=7,
    exit_cap_rate=0.05499999999999999,
    ltv=0.6666666666666666,
    interest_rate=0.052500000000001,
    amortization=25,
)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test-anchor.db"


def test_create_deal_returns_stored_deal_with_id_and_timestamps(db_path: Path) -> None:
    deal = create_deal("111 Main St", GOLDEN_INPUTS, db_path=db_path)

    assert deal.id
    assert deal.name == "111 Main St"
    assert deal.inputs == GOLDEN_INPUTS
    assert deal.created_at == deal.updated_at


def test_get_deal_returns_the_same_deal(db_path: Path) -> None:
    created = create_deal("111 Main St", GOLDEN_INPUTS, db_path=db_path)

    fetched = get_deal(created.id, db_path=db_path)

    assert fetched == created


def test_get_deal_raises_deal_not_found_error_for_unknown_id(db_path: Path) -> None:
    with pytest.raises(DealNotFoundError):
        get_deal("does-not-exist", db_path=db_path)


def test_list_deals_returns_all_deals_most_recently_updated_first(db_path: Path) -> None:
    first = create_deal("First Deal", GOLDEN_INPUTS, db_path=db_path)
    second = create_deal("Second Deal", GOLDEN_INPUTS, db_path=db_path)

    # Force a distinct, later updated_at without depending on wall-clock
    # timing between the two create_deal calls above.
    update_deal(first.id, "First Deal (edited)", GOLDEN_INPUTS, db_path=db_path)

    deals = list_deals(db_path=db_path)

    assert [deal.id for deal in deals] == [first.id, second.id]


def test_update_deal_overwrites_name_and_inputs_and_preserves_created_at(
    db_path: Path,
) -> None:
    created = create_deal("Original Name", GOLDEN_INPUTS, db_path=db_path)

    updated = update_deal(created.id, "Renamed Deal", AWKWARD_INPUTS, db_path=db_path)

    assert updated.id == created.id
    assert updated.name == "Renamed Deal"
    assert updated.inputs == AWKWARD_INPUTS
    assert updated.created_at == created.created_at
    assert updated.updated_at >= created.updated_at


def test_update_deal_raises_deal_not_found_error_for_unknown_id(db_path: Path) -> None:
    with pytest.raises(DealNotFoundError):
        update_deal("does-not-exist", "Name", GOLDEN_INPUTS, db_path=db_path)


def test_create_deal_generates_distinct_ids(db_path: Path) -> None:
    first = create_deal("Deal A", GOLDEN_INPUTS, db_path=db_path)
    second = create_deal("Deal B", GOLDEN_INPUTS, db_path=db_path)

    assert first.id != second.id


# =============================================================================
# Numeric-representation guarantee: float -> SQLite REAL -> float is exact.
# =============================================================================


def test_stored_inputs_round_trip_exactly(db_path: Path) -> None:
    """Every field, compared with ``==`` (never ``pytest.approx``) -- the
    numeric-representation note in ``store.py`` claims a lossless round-trip
    through SQLite REAL/INTEGER, not merely a close one, and this is the
    test that actually proves it for values chosen to be hostile to lossy
    paths (long binary-fraction tails, values just off a clean decimal)."""

    created = create_deal("Awkward Deal", AWKWARD_INPUTS, db_path=db_path)
    fetched = get_deal(created.id, db_path=db_path)

    assert fetched.inputs.purchase_price == AWKWARD_INPUTS.purchase_price
    assert fetched.inputs.current_noi == AWKWARD_INPUTS.current_noi
    assert fetched.inputs.occupancy == AWKWARD_INPUTS.occupancy
    assert fetched.inputs.noi_growth == AWKWARD_INPUTS.noi_growth
    assert fetched.inputs.hold_period == AWKWARD_INPUTS.hold_period
    assert fetched.inputs.exit_cap_rate == AWKWARD_INPUTS.exit_cap_rate
    assert fetched.inputs.ltv == AWKWARD_INPUTS.ltv
    assert fetched.inputs.interest_rate == AWKWARD_INPUTS.interest_rate
    assert fetched.inputs.amortization == AWKWARD_INPUTS.amortization
    assert fetched.inputs == AWKWARD_INPUTS


def test_stored_year_fields_remain_python_int(db_path: Path) -> None:
    created = create_deal("Deal", GOLDEN_INPUTS, db_path=db_path)
    fetched = get_deal(created.id, db_path=db_path)

    assert isinstance(fetched.inputs.hold_period, int)
    assert isinstance(fetched.inputs.amortization, int)


def test_db_path_creates_missing_parent_directory(tmp_path: Path) -> None:
    nested_path = tmp_path / "nested" / "does" / "not" / "exist" / "anchor.db"

    create_deal("Deal", GOLDEN_INPUTS, db_path=nested_path)

    assert nested_path.exists()


# =============================================================================
# Persistence Phase C -- delete_deal / duplicate_deal
# =============================================================================


def test_delete_deal_removes_an_existing_deal(db_path: Path) -> None:
    created = create_deal("Deal", GOLDEN_INPUTS, db_path=db_path)

    delete_deal(created.id, db_path=db_path)

    with pytest.raises(DealNotFoundError):
        get_deal(created.id, db_path=db_path)


def test_delete_deal_raises_deal_not_found_error_for_unknown_id(db_path: Path) -> None:
    with pytest.raises(DealNotFoundError):
        delete_deal("does-not-exist", db_path=db_path)


def test_delete_deal_does_not_affect_other_deals(db_path: Path) -> None:
    kept = create_deal("Kept Deal", GOLDEN_INPUTS, db_path=db_path)
    removed = create_deal("Removed Deal", GOLDEN_INPUTS, db_path=db_path)

    delete_deal(removed.id, db_path=db_path)

    remaining = list_deals(db_path=db_path)
    assert [deal.id for deal in remaining] == [kept.id]


def test_duplicate_deal_creates_a_new_id(db_path: Path) -> None:
    original = create_deal("111 Main St", GOLDEN_INPUTS, db_path=db_path)

    copy = duplicate_deal(original.id, db_path=db_path)

    assert copy.id != original.id


def test_duplicate_deal_preserves_all_nine_inputs_exactly(db_path: Path) -> None:
    original = create_deal("Awkward Deal", AWKWARD_INPUTS, db_path=db_path)

    copy = duplicate_deal(original.id, db_path=db_path)

    assert copy.inputs == AWKWARD_INPUTS
    assert copy.inputs == original.inputs


def test_duplicate_deal_default_name_is_original_name_plus_copy_suffix(db_path: Path) -> None:
    original = create_deal("111 Main St", GOLDEN_INPUTS, db_path=db_path)

    copy = duplicate_deal(original.id, db_path=db_path)

    assert copy.name == "111 Main St (Copy)"


def test_duplicate_deal_accepts_an_explicit_name_override(db_path: Path) -> None:
    original = create_deal("111 Main St", GOLDEN_INPUTS, db_path=db_path)

    copy = duplicate_deal(original.id, name="222 Oak Ave", db_path=db_path)

    assert copy.name == "222 Oak Ave"


def test_duplicate_deal_gets_fresh_timestamps(db_path: Path) -> None:
    original = create_deal("111 Main St", GOLDEN_INPUTS, db_path=db_path)

    copy = duplicate_deal(original.id, db_path=db_path)

    assert copy.created_at == copy.updated_at
    # Not asserting copy.created_at > original.created_at -- both calls can
    # legitimately land in the same microsecond-resolution instant; the
    # meaningful guarantee is that the copy has its own timestamp pair, not
    # that it is strictly later than the original's.
    assert isinstance(copy.created_at, type(original.created_at))


def test_duplicate_deal_does_not_mutate_the_original(db_path: Path) -> None:
    original = create_deal("111 Main St", GOLDEN_INPUTS, db_path=db_path)

    duplicate_deal(original.id, name="A Copy", db_path=db_path)

    unchanged = get_deal(original.id, db_path=db_path)
    assert unchanged == original


def test_duplicate_deal_raises_deal_not_found_error_for_unknown_id(db_path: Path) -> None:
    with pytest.raises(DealNotFoundError):
        duplicate_deal("does-not-exist", db_path=db_path)


def test_duplicate_deal_appears_alongside_the_original_in_list_deals(db_path: Path) -> None:
    original = create_deal("111 Main St", GOLDEN_INPUTS, db_path=db_path)

    copy = duplicate_deal(original.id, db_path=db_path)

    ids = {deal.id for deal in list_deals(db_path=db_path)}
    assert ids == {original.id, copy.id}
