"""Refinance & Capital Events V1 Stage 2 -- persistence and the codec.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 16.1. Proves, against
the real store:

- every Stage 1 member round-trips exactly (save -> read equality, read -> save
  stability), in authored order independent of physical row order;
- ``RefinanceProceeds`` is persisted without altering ``capital_funding_events``:
  the discriminator token plus a typed sidecar link, checked in both directions;
- legacy references are typed ``(kind, unit_id)`` rows, never the reserved string;
- a structure with no event writes no event row and reads back as the plain
  contract; an explicit empty event set is the empty set;
- every corruption fails closed -- unknown tokens, orphans, malformed scopes,
  unsupported (reserve-like) members, unused or missing valuation references,
  malformed ``RefinanceProceeds`` links, anything the validator refuses -- and
  no event is ever partially decoded or dropped;
- writes are atomic with the owning structure, and child rows are deleted
  explicitly on every lifecycle path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from anchor.capital_structure.contracts import CapitalStructure, CapitalStructureValidationError
from anchor.capital_structure.events import CapitalStructureWithEvents
from anchor.deals import store
from anchor.deals.store import PersistedCapitalStructureDataError


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def save_full(db: Path) -> tuple[Any, str, CapitalStructureWithEvents]:
    """A saved Deal whose Base structure states every Stage 1 member."""

    deal = fx.base_deal(db)
    structure = fx.full_member_structure(deal.id)
    investment_id, written = store.set_deal_capital_structure(deal.id, structure, db_path=db)
    assert written == structure and investment_id is not None
    return deal, investment_id, structure


@pytest.fixture
def saved(db: Path) -> tuple[Any, str, CapitalStructureWithEvents]:
    return save_full(db)


def _read(db: Path, deal_id: str) -> CapitalStructure:
    return store.read_deal_capital_structure(deal_id, db_path=db)[1]


# =============================================================================
# Round trips
# =============================================================================


def test_every_stage_1_member_round_trips_exactly(db: Path, saved: tuple[Any, str, Any]) -> None:
    deal, _, structure = saved
    back = _read(db, deal.id)
    assert type(back) is CapitalStructureWithEvents
    assert back == structure
    (event,) = back.events
    assert event.sizing.fixed_cap is not None and event.sizing.max_ltv is not None and event.sizing.min_dscr is not None
    assert event.valuation is not None and len(event.retiring) == 2 and len(event.costs) == 3


def test_read_then_save_is_stable(db: Path, saved: tuple[Any, str, Any]) -> None:
    deal, _, _ = saved
    first = _read(db, deal.id)
    before = {table: [row[1:] for row in fx.rows(db, table)] for table in fx.STAGE_2_TABLES}
    store.set_deal_capital_structure(deal.id, first, db_path=db)
    assert _read(db, deal.id) == first
    # Only the structure id changes (a structure is replaced whole); every
    # stored value, token and ordinal is identical.
    after = {table: [row[1:] for row in fx.rows(db, table)] for table in fx.STAGE_2_TABLES}
    assert after == before


def test_reading_follows_authored_order_not_physical_row_order(db: Path, saved: tuple[Any, str, Any]) -> None:
    deal, _, structure = saved
    for table in ("capital_event_retirements", "capital_event_costs", "capital_event_constraints"):
        connection = sqlite3.connect(db)
        try:
            with connection:
                stored = list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid"))
                connection.execute(f"DELETE FROM {table}")
                placeholders = ", ".join("?" for _ in stored[0])
                connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", list(reversed(stored)))
        finally:
            connection.close()
    assert _read(db, deal.id) == structure


def test_legacy_references_are_typed_rows_never_the_reserved_string(db: Path, saved: tuple[Any, str, Any]) -> None:
    deal, _, _ = saved
    retirements = fx.rows(db, "capital_event_retirements")
    assert {(row[3], row[4], row[5]) for row in retirements} == {
        ("legacy_acquisition_loan", None, deal.id),
        ("authored_position", "mezz", None),
    }
    connection = sqlite3.connect(db)
    try:
        for table in fx.STAGE_2_TABLES:
            for row in connection.execute(f"SELECT * FROM {table}"):
                assert not any(isinstance(value, str) and "legacy-acquisition-loan:" in value for value in row), table
    finally:
        connection.close()


def test_refinance_proceeds_uses_the_token_and_a_sidecar_never_an_existing_column(
    db: Path, saved: tuple[Any, str, Any]
) -> None:
    (funding,) = [row for row in fx.rows(db, "capital_funding_events") if row[5] == "refinance_proceeds"]
    # structure_id, position_id, event_id, model_month, sequence, amount_rule, amount, pct, timepoint_id
    assert funding[1:] == (fx.REPLACEMENT_ID, f"{fx.REPLACEMENT_ID}-funding", 24, 1, "refinance_proceeds", None, None, None)
    (link,) = fx.rows(db, "capital_refinance_proceeds")
    assert link[1:] == (f"{fx.REPLACEMENT_ID}-funding", fx.EVENT_ID)


def test_disabled_constraints_have_no_row(db: Path) -> None:
    deal = fx.base_deal(db)
    store.set_deal_capital_structure(deal.id, fx.evented(deal.id, dscr=2.0), db_path=db)
    assert [(row[2], row[3]) for row in fx.rows(db, "capital_event_constraints")] == [("min_dscr", 2.0)]
    assert fx.rows(db, "capital_event_valuation_refs") == []


# =============================================================================
# No events, and the explicit empty set
# =============================================================================


def test_a_structure_without_events_writes_no_event_row_and_reads_back_plain(db: Path) -> None:
    deal = fx.base_deal(db)
    plain = fx.closing_mezz_only(deal.id)
    store.set_deal_capital_structure(deal.id, plain, db_path=db)
    back = _read(db, deal.id)
    assert type(back) is CapitalStructure and back == plain
    assert all(rows == [] for rows in fx.event_rows(db).values())


def test_replacing_an_evented_structure_with_a_plain_one_leaves_no_event_row(
    db: Path, saved: tuple[Any, str, Any]
) -> None:
    deal, _, _ = saved
    store.set_deal_capital_structure(deal.id, fx.closing_mezz_only(deal.id), db_path=db)
    assert type(_read(db, deal.id)) is CapitalStructure
    assert all(rows == [] for rows in fx.event_rows(db).values())


def test_a_strategy_keeps_its_own_whole_event_set(db: Path, saved: tuple[Any, str, Any]) -> None:
    from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain

    deal, investment_id, base = saved
    own = fx.evented(deal.id, dscr=1.5)
    strategy = store.create_strategy(
        investment_id,
        name="Lower DSCR",
        root_overlays=(InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=own),),
        db_path=db,
    )
    listed = store.list_investment_capital_structures(investment_id, db_path=db)
    assert listed.base == base
    (entry,) = listed.strategies
    assert entry.strategy_id == strategy.strategy.strategy_id and entry.capital_structure == own
    # Two structures, two independent event sets.
    assert len({row[0] for row in fx.rows(db, "capital_events")}) == 2


# =============================================================================
# Fail closed
# =============================================================================


def _structure_id(db: Path) -> str:
    return fx.rows(db, "capital_events")[0][0]


_CORRUPTIONS: dict[str, tuple[str, ...]] = {
    "unknown event kind": ("UPDATE capital_events SET kind = 'recapitalization'",),
    "unknown scope kind": ("UPDATE capital_events SET scope_kind = 'portfolio'",),
    "unit scope without a unit": ("UPDATE capital_events SET scope_unit_id = NULL",),
    "unknown constraint (debt yield)": ("UPDATE capital_event_constraints SET constraint_kind = 'min_debt_yield' WHERE constraint_kind = 'fixed_cap'",),
    "a reserve-like constraint": ("UPDATE capital_event_constraints SET constraint_kind = 'reserve_holdback' WHERE constraint_kind = 'fixed_cap'",),
    "a reserve-like cost": ("UPDATE capital_event_costs SET kind = 'reserve_deposit' WHERE cost_id = 'legal-title'",),
    "unknown reference kind": ("UPDATE capital_event_retirements SET ref_kind = 'reserved_string' WHERE ref_kind = 'legacy_acquisition_loan'",),
    "reference stating both ids": ("UPDATE capital_event_retirements SET unit_id = 'x' WHERE ref_kind = 'authored_position'",),
    "legacy reference with no unit": ("UPDATE capital_event_retirements SET unit_id = NULL WHERE ref_kind = 'legacy_acquisition_loan'",),
    "recipient id with no recipient kind": ("UPDATE capital_event_costs SET recipient_position_id = 'mezz' WHERE cost_id = 'legal-title'",),
    "third-party cost with a recipient": (
        "UPDATE capital_event_costs SET recipient_kind = 'authored_position', recipient_position_id = 'mezz' "
        "WHERE cost_id = 'legal-title'",
    ),
    "orphaned retirement": ("UPDATE capital_event_retirements SET event_id = 'ghost' WHERE ordinal = 0",),
    # The orphan is the only fault here: the real event is untouched, so only
    # the orphan check itself can refuse the structure.
    "an extra orphaned child row": (
        "INSERT INTO capital_event_constraints SELECT structure_id, 'ghost', 'min_dscr', 2.0 FROM capital_events",
    ),
    "an extra orphaned proceeds link": (
        "INSERT INTO capital_refinance_proceeds SELECT structure_id, 'mezz-funding', 'ghost' FROM capital_events",
    ),
    "orphaned constraint": ("UPDATE capital_event_constraints SET event_id = 'ghost' WHERE constraint_kind = 'min_dscr'",),
    "orphaned valuation reference": ("UPDATE capital_event_valuation_refs SET event_id = 'ghost'",),
    "orphaned cost": ("UPDATE capital_event_costs SET event_id = 'ghost' WHERE cost_id = 'legal-title'",),
    "event row deleted, children kept": ("DELETE FROM capital_events",),
    "missing LTV valuation reference": ("DELETE FROM capital_event_valuation_refs",),
    "valuation reference without LTV": ("DELETE FROM capital_event_constraints WHERE constraint_kind = 'max_ltv'",),
    "no constraint at all": ("DELETE FROM capital_event_constraints",),
    "no retiring position": ("DELETE FROM capital_event_retirements",),
    "missing replacement position": ("UPDATE capital_events SET replacement_position_id = 'nobody'",),
    "duplicate capital-event identity": ("UPDATE capital_event_costs SET cost_id = 'mezz-funding' WHERE cost_id = 'legal-title'",),
    "proceeds funding with no link": ("DELETE FROM capital_refinance_proceeds",),
    "link naming no proceeds funding": ("UPDATE capital_refinance_proceeds SET funding_event_id = 'mezz-funding'",),
    "link naming another event": ("UPDATE capital_refinance_proceeds SET capital_event_id = 'ghost'",),
    "proceeds funding stating an amount": ("UPDATE capital_funding_events SET amount = 1.0 WHERE amount_rule = 'refinance_proceeds'",),
    "proceeds funding stating a timepoint": (
        "UPDATE capital_funding_events SET timepoint_id = 'year-2-value' WHERE amount_rule = 'refinance_proceeds'",
    ),
    "wrong event month": ("UPDATE capital_events SET model_month = 30",),
    "unsupported sequence": ("UPDATE capital_events SET sequence = 2",),
    "a negative cost": ("UPDATE capital_event_costs SET amount = -1.0 WHERE cost_id = 'legal-title'",),
    "an LTV above one": ("UPDATE capital_event_constraints SET target = 1.5 WHERE constraint_kind = 'max_ltv'",),
}


@pytest.mark.parametrize("name", sorted(_CORRUPTIONS))
def test_every_corruption_fails_closed(db: Path, saved: tuple[Any, str, Any], name: str) -> None:
    deal, investment_id, _ = saved
    for sql in _CORRUPTIONS[name]:
        fx.execute(db, sql)
    with pytest.raises(PersistedCapitalStructureDataError):
        _read(db, deal.id)
    # Every door reads the same way: nothing reads the structure as empty or
    # as the structure minus the bad event.
    with pytest.raises(PersistedCapitalStructureDataError):
        store.list_investment_capital_structures(investment_id, db_path=db)
    with pytest.raises(PersistedCapitalStructureDataError):
        store.get_base_capital_structure(investment_id, db_path=db)


def test_an_orphaned_event_row_under_no_structure_is_never_attached(db: Path, saved: tuple[Any, str, Any]) -> None:
    """A row keyed to a structure id nothing owns is never read into any
    structure -- and it cannot make a real structure read differently."""

    deal, _, structure = saved
    fx.execute(
        db,
        "INSERT INTO capital_events VALUES ('nobody', 'stray', 0, 'refinance', 'Stray', 'unit', ?, 24, 1, 'x')",
        (deal.id,),
    )
    assert _read(db, deal.id) == structure


def test_the_corruption_list_covers_the_ratified_fail_closed_classes() -> None:
    names = " ".join(_CORRUPTIONS)
    for word in ("unknown", "orphaned", "scope", "reserve-like", "without LTV", "missing LTV", "link", "duplicate"):
        assert word in names, word


# =============================================================================
# Atomic writes and explicit child deletion
# =============================================================================


def test_a_failed_write_leaves_the_previous_structure_exactly(
    db: Path, saved: tuple[Any, str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    deal, _, structure = saved
    before = fx.event_rows(db)

    def failing(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the disk went away half way through the events")

    monkeypatch.setattr(store, "_write_capital_events", failing)
    with pytest.raises(RuntimeError):
        store.set_deal_capital_structure(deal.id, fx.evented(deal.id, dscr=1.5), db_path=db)
    monkeypatch.undo()
    assert _read(db, deal.id) == structure
    assert fx.event_rows(db) == before


def test_an_invalid_structure_is_refused_before_anything_is_written(db: Path, saved: tuple[Any, str, Any]) -> None:
    deal, _, structure = saved
    bad = fx.evented(deal.id, dscr=2.0, valuation=fx.TIMEPOINT_ID)  # valuation_reference_unused
    with pytest.raises(CapitalStructureValidationError) as refused:
        store.set_deal_capital_structure(deal.id, bad, db_path=db)
    assert "valuation_reference_unused" in {issue.code.value for issue in refused.value.issues}
    assert _read(db, deal.id) == structure


def test_clearing_the_base_structure_deletes_every_event_row(db: Path, saved: tuple[Any, str, Any]) -> None:
    deal, _, _ = saved
    store.set_deal_capital_structure(deal.id, CapitalStructure(positions=()), db_path=db)
    assert all(rows == [] for rows in fx.event_rows(db).values())


def test_deleting_a_strategy_deletes_its_event_rows_and_keeps_the_base(db: Path, saved: tuple[Any, str, Any]) -> None:
    from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain

    deal, investment_id, base = saved
    strategy = store.create_strategy(
        investment_id,
        name="Own",
        root_overlays=(
            InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=fx.evented(deal.id, dscr=1.5)),
        ),
        db_path=db,
    )
    store.delete_strategy(investment_id, strategy.strategy.strategy_id, db_path=db)
    base_structure_id = _structure_id(db)
    assert {row[0] for table in fx.STAGE_2_TABLES for row in fx.rows(db, table)} == {base_structure_id}
    assert _read(db, deal.id) == base


def test_updating_a_strategy_to_inherit_removes_its_event_rows(db: Path, saved: tuple[Any, str, Any]) -> None:
    from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain

    deal, investment_id, _ = saved
    strategy = store.create_strategy(
        investment_id,
        name="Own",
        root_overlays=(
            InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=fx.evented(deal.id, dscr=1.5)),
        ),
        db_path=db,
    )
    before = len(fx.rows(db, "capital_events"))
    store.update_strategy(investment_id, strategy.strategy.strategy_id, name="Own", db_path=db)
    assert len(fx.rows(db, "capital_events")) == before - 1


def test_deleting_the_deal_leaves_no_event_row(db: Path, saved: tuple[Any, str, Any]) -> None:
    deal, _, _ = saved
    store.delete_deal(deal.id, db_path=db)
    assert all(rows == [] for rows in fx.event_rows(db).values())
