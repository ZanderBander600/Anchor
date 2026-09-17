"""Phase 7 Gate P7.6 -- the visible Investment's persistence and lifecycle.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 6, 8.2,
15.1 to 15.3 and the Section 21 record (Q3, Q4, Q6, Q9). Every row is read from
the database directly, never through the store under test.

- Schema 10 adds five sidecars; a hidden wrapper has none, and no read creates
  one.
- Create, promote, add, update, remove and delete are each one transaction:
  validated first, rolled back whole on any failure.
- Membership is exclusive; a released Deal is never deleted or changed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
import _p7_4_fixtures as f4  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.analysis.scenario import ScenarioIssueCode, ScenarioValidationError
from anchor.business_plan import BusinessPlan
from anchor.deals import store
from anchor.deals.contracts import (
    DealNotFoundError,
    InvestmentNotFoundError,
    InvestmentStructureError,
    InvestmentUnit,
    InvestmentUnitNotFoundError,
)
from anchor.deals.variants import analyze_variant
from anchor.investment import InvestmentIssueCode, InvestmentValidationError, TransactionCostCategory, UnitKind

from _p7_2_fixtures import P7_6_TABLES, override, rows, table_names  # type: ignore[import-not-found]
from _p7_6_fixtures import (  # type: ignore[import-not-found]
    P7_6_EMPTY,
    cost,
    create_investment,
    detailed_deal,
    investment_plan,
    lease_level_deal,
    member,
    p7_6_row_counts,
    price,
    quick_deal,
)

Code = InvestmentIssueCode


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_6.db"


def _every_row(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {table: rows(db, table) for table in sorted(table_names(db)) if not table.startswith("sqlite_")}


def _deals(db: Path) -> tuple[Any, Any, Any]:
    return quick_deal(db, business_plan=fx.business_plan()), detailed_deal(db), lease_level_deal(db)


def _codes(error: pytest.ExceptionInfo[Any]) -> list[Any]:
    return [issue.code for issue in error.value.issues]


# =============================================================================
# Schema 10 -- five additive sidecars
# =============================================================================


def test_a_fresh_store_is_schema_10_with_five_empty_sidecars(db: Path) -> None:
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    columns = {
        table: [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        for table in P7_6_TABLES
    }
    connection.close()

    assert version == 12  # P7.8B added schema 11's Capital Structure tables, P7.9 Stage 2 schema 12's Partnership tables
    assert p7_6_row_counts(db) == P7_6_EMPTY
    assert columns == {
        "investment_details": ["investment_id", "name", "transaction_price"],
        "investment_unit_details": [
            "investment_id", "unit_id", "ordinal", "label", "unit_kind", "acquisition_month", "disposition_month",
        ],
        "investment_capital_plan_items": ["investment_id", "item_id", "ordinal", "description", "category", "month", "amount"],
        "investment_owner_expense_items": [
            "investment_id", "item_id", "ordinal", "description", "category", "annual_amount", "first_year", "last_year",
        ],
        "investment_transaction_costs": ["investment_id", "cost_id", "ordinal", "description", "category", "amount", "model_month"],
    }


def test_the_investments_table_itself_is_not_altered(db: Path) -> None:
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    investments = [row[1] for row in connection.execute("PRAGMA table_info(investments)")]
    units = [row[1] for row in connection.execute("PRAGMA table_info(investment_units)")]
    connection.close()
    assert investments == ["id", "is_hidden", "created_at", "updated_at"]
    assert units == ["investment_id", "deal_id"]


def test_a_hidden_wrapper_has_no_sidecar_and_no_read_creates_one(db: Path) -> None:
    deal = quick_deal(db)
    record = store.create_scenario_for_deal(deal.id, name="Downside", db_path=db)
    before = _every_row(db)

    store.get_investment(record.investment_id, db_path=db)
    store.list_scenarios(record.investment_id, db_path=db)
    store.list_strategies(record.investment_id, db_path=db)
    assert store.list_visible_investments(db_path=db) == []
    with pytest.raises(InvestmentStructureError, match="hidden one-unit wrapper"):
        store.get_visible_investment(record.investment_id, db_path=db)

    assert p7_6_row_counts(db) == P7_6_EMPTY
    assert _every_row(db) == before


# =============================================================================
# Create
# =============================================================================


def test_create_writes_the_whole_visible_investment_in_one_transaction(db: Path) -> None:
    quick, detailed, lease = _deals(db)
    deals_before = [store.get_deal(deal.id, db_path=db) for deal in (quick, detailed, lease)]

    visible = create_investment(
        db, lease, quick, detailed, business_plan=investment_plan(),
        costs=(cost("tc-fee", 250_000.0), cost("tc-legal", 85_000.0, category=TransactionCostCategory.LEGAL)),
        name="Mixed portfolio",
    )

    assert (visible.name, visible.transaction_price) == ("Mixed portfolio", price(quick) + price(detailed) + price(lease))
    assert [unit.unit_id for unit in visible.units] == [lease.id, quick.id, detailed.id]  # presentation order
    assert [unit.ordinal for unit in visible.units] == [0, 1, 2]
    assert visible.business_plan == investment_plan()
    assert [c.cost_id for c in visible.transaction_costs] == ["tc-fee", "tc-legal"]
    assert p7_6_row_counts(db) == {
        "investment_details": 1, "investment_unit_details": 3, "investment_capital_plan_items": 3,
        "investment_owner_expense_items": 1, "investment_transaction_costs": 2,
    }
    ((investment_id, is_hidden, *_),) = rows(db, "investments")
    assert (investment_id, is_hidden) == (visible.id, 0)
    assert store.get_investment(visible.id, db_path=db).units == tuple(
        InvestmentUnit(unit_id=unit_id) for unit_id in sorted([quick.id, detailed.id, lease.id])
    )
    assert [store.get_deal(deal.id, db_path=db) for deal in (quick, detailed, lease)] == deals_before
    assert store.get_visible_investment(visible.id, db_path=db) == visible
    assert store.list_visible_investments(db_path=db) == [visible]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda deals: {"name": " "}, [Code.INVALID_NAME]),
        (lambda deals: {"transaction_price": sum(price(d) for d in deals) + 0.02}, [Code.ALLOCATION_MISMATCH]),
        (lambda deals: {"units": (member(deals[0].id, acquisition_month=6), member(deals[1].id))}, [Code.UNSUPPORTED_ACQUISITION_MONTH]),
        (lambda deals: {"units": (member(deals[0].id, disposition_month=36), member(deals[1].id))}, [Code.UNSUPPORTED_DISPOSITION_MONTH]),
        (lambda deals: {"units": (member(deals[0].id), member(deals[0].id))}, [Code.DUPLICATE_UNIT]),
        (lambda deals: {"transaction_costs": (cost("c", 1.0, model_month=1),)}, [Code.UNSUPPORTED_COST_MONTH]),
    ],
)
def test_create_refuses_invalid_input_and_writes_nothing(db: Path, change: Any, expected: list[Any]) -> None:
    deals = (quick_deal(db), detailed_deal(db))
    before = _every_row(db)
    request: dict[str, Any] = {
        "name": "P", "transaction_price": price(deals[0]) + price(deals[1]),
        "units": (member(deals[0].id), member(deals[1].id, ordinal=1)),
        "business_plan": BusinessPlan(), "transaction_costs": (),
    }
    request.update(change(deals))

    with pytest.raises(InvestmentValidationError) as error:
        store.create_visible_investment(**request, db_path=db)

    assert _codes(error) == expected
    assert _every_row(db) == before


def test_create_refuses_a_common_timeline_mismatch(db: Path) -> None:
    quick, seven = quick_deal(db), detailed_deal(db, hold_period=7)
    with pytest.raises(InvestmentValidationError) as error:
        create_investment(db, quick, seven)
    assert _codes(error) == [Code.HOLD_PERIOD_MISMATCH]

    from datetime import date

    lease_a, lease_b = lease_level_deal(db), lease_level_deal(db, start=date(2027, 7, 1))
    with pytest.raises(InvestmentValidationError) as error:
        create_investment(db, lease_a, lease_b)
    assert _codes(error) == [Code.ANALYSIS_START_DATE_MISMATCH]
    assert p7_6_row_counts(db) == P7_6_EMPTY and rows(db, "investments") == []


def test_create_refuses_a_deal_that_already_belongs_to_an_investment(db: Path) -> None:
    free, wrapped, member_deal = quick_deal(db), quick_deal(db), quick_deal(db)
    store.create_scenario_for_deal(wrapped.id, name="Downside", db_path=db)
    create_investment(db, member_deal)
    before = _every_row(db)

    with pytest.raises(InvestmentStructureError, match="Promote that Investment"):
        create_investment(db, free, wrapped)
    with pytest.raises(InvestmentStructureError, match="another Investment") as error:
        create_investment(db, free, member_deal)
    with pytest.raises(DealNotFoundError):
        store.create_visible_investment(
            name="P", transaction_price=1.0, units=(member("0" * 32),), business_plan=BusinessPlan(), db_path=db
        )

    assert _every_row(db) == before
    assert not any(row[0] in str(error.value) for row in rows(db, "investments"))  # no other Investment disclosed


def test_an_injected_failure_rolls_the_whole_create_back(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    quick, detailed = quick_deal(db), detailed_deal(db)
    before = _every_row(db)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(store, "_replace_transaction_costs", fail)
    with pytest.raises(RuntimeError, match="injected"):
        create_investment(db, quick, detailed, costs=(cost("c", 1.0),))

    assert _every_row(db) == before


def test_membership_is_exclusive_in_the_schema_too(db: Path) -> None:
    deal = quick_deal(db)
    create_investment(db, deal)
    connection = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute("INSERT INTO investment_units VALUES ('other', ?)", (deal.id,))
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO investment_unit_details VALUES ('other', ?, 0, NULL, 'property', 0, NULL)", (deal.id,)
            )
    finally:
        connection.close()


# =============================================================================
# Promote a hidden wrapper -- the same Investment, never a second parent
# =============================================================================


def test_promotion_reuses_the_wrapper_and_keeps_every_strategy_and_scenario(db: Path) -> None:
    deal, added = quick_deal(db), detailed_deal(db)
    scenario = store.create_scenario_for_deal(deal.id, name="Downside", overrides=(override(deal.id, "exit_cap_rate", "add", 0.005),), db_path=db)
    strategy = store.create_strategy(scenario.investment_id, name="Bid", overlays=(f4.acquisition(deal.id, purchase_price=12_000_000.0),), db_path=db)
    analyze_variant(scenario.investment_id, "base", scenario.scenario.scenario_id, db_path=db)
    assert len(rows(db, "variant_snapshots")) == 1

    visible = store.promote_hidden_investment(
        scenario.investment_id, name="Portfolio", transaction_price=price(deal) + price(added),
        units=(member(deal.id, label="Tower"), member(added.id, ordinal=1)),
        business_plan=investment_plan(), transaction_costs=(cost("tc", 50_000.0),), db_path=db,
    )

    assert visible.id == scenario.investment_id
    assert len(rows(db, "investments")) == 1 and rows(db, "investments")[0][1] == 0
    assert store.get_scenario(visible.id, scenario.scenario.scenario_id, db_path=db).scenario == scenario.scenario
    assert store.get_strategy(visible.id, strategy.strategy.strategy_id, db_path=db).strategy == strategy.strategy
    assert rows(db, "variant_snapshots") == []
    assert [unit.label for unit in visible.units] == ["Tower", None]


def test_promotion_must_retain_the_wrappers_unit_and_is_one_transaction(db: Path) -> None:
    deal, other = quick_deal(db), quick_deal(db)
    record = store.create_scenario_for_deal(deal.id, name="S", db_path=db)
    before = _every_row(db)

    with pytest.raises(InvestmentValidationError) as error:
        store.promote_hidden_investment(
            record.investment_id, name="P", transaction_price=price(other), units=(member(other.id),),
            business_plan=BusinessPlan(), db_path=db,
        )
    assert _codes(error) == [Code.UNIT_NOT_RETAINED]
    with pytest.raises(InvestmentValidationError):
        store.promote_hidden_investment(
            record.investment_id, name="P", transaction_price=price(deal) + 1.0, units=(member(deal.id),),
            business_plan=BusinessPlan(), db_path=db,
        )
    assert _every_row(db) == before

    visible = store.promote_hidden_investment(
        record.investment_id, name="P", transaction_price=price(deal), units=(member(deal.id),),
        business_plan=BusinessPlan(), db_path=db,
    )
    with pytest.raises(InvestmentStructureError):
        store.promote_hidden_investment(
            visible.id, name="P", transaction_price=price(deal), units=(member(deal.id),),
            business_plan=BusinessPlan(), db_path=db,
        )
    with pytest.raises(InvestmentNotFoundError):
        store.promote_hidden_investment(
            "0" * 32, name="P", transaction_price=1.0, units=(member(deal.id),), business_plan=BusinessPlan(), db_path=db,
        )


# =============================================================================
# Add, update and remove a Unit
# =============================================================================


def test_adding_a_unit_needs_a_reconciling_price_and_changes_nothing_else(db: Path) -> None:
    first, second = quick_deal(db), detailed_deal(db)
    visible = create_investment(db, first)
    before = _every_row(db)
    second_before = store.get_deal(second.id, db_path=db)

    with pytest.raises(InvestmentValidationError) as error:
        store.add_investment_unit(visible.id, member(second.id), db_path=db)
    assert _codes(error) == [Code.ALLOCATION_MISMATCH]
    assert _every_row(db) == before

    added = store.add_investment_unit(
        visible.id, member(second.id, label="Annex", kind=UnitKind.COMPONENT),
        transaction_price=price(first) + price(second), db_path=db,
    )
    assert [(u.unit_id, u.ordinal, u.label, u.unit_kind) for u in added.units] == [
        (first.id, 0, None, UnitKind.PROPERTY), (second.id, 1, "Annex", UnitKind.COMPONENT),
    ]
    assert added.transaction_price == price(first) + price(second)
    assert store.get_deal(second.id, db_path=db) == second_before


def test_adding_refuses_every_structural_problem_and_rolls_back(db: Path) -> None:
    first, seven, elsewhere = quick_deal(db), quick_deal(db, hold_period=7), quick_deal(db)
    visible = create_investment(db, first)
    create_investment(db, elsewhere)
    before = _every_row(db)

    with pytest.raises(InvestmentValidationError) as error:
        store.add_investment_unit(visible.id, member(seven.id), transaction_price=price(first) + price(seven), db_path=db)
    assert _codes(error) == [Code.HOLD_PERIOD_MISMATCH]
    with pytest.raises(InvestmentStructureError):
        store.add_investment_unit(visible.id, member(elsewhere.id), transaction_price=price(first) + price(elsewhere), db_path=db)
    with pytest.raises(InvestmentValidationError) as error:
        store.add_investment_unit(visible.id, member(first.id), transaction_price=2 * price(first), db_path=db)
    assert _codes(error) == [Code.DUPLICATE_UNIT]
    with pytest.raises(DealNotFoundError):
        store.add_investment_unit(visible.id, member("0" * 32), db_path=db)

    assert _every_row(db) == before


def test_updating_a_units_display_metadata(db: Path) -> None:
    first, second = quick_deal(db), quick_deal(db)
    visible = create_investment(db, first, second)

    updated = store.update_investment_unit(visible.id, first.id, label="Retail podium", unit_kind=UnitKind.COMPONENT, ordinal=5, db_path=db)
    assert [(u.unit_id, u.label, u.unit_kind, u.ordinal) for u in updated.units] == [
        (second.id, None, UnitKind.PROPERTY, 1), (first.id, "Retail podium", UnitKind.COMPONENT, 5),
    ]
    with pytest.raises(InvestmentUnitNotFoundError):
        store.update_investment_unit(visible.id, "0" * 32, label=None, unit_kind=UnitKind.PHASE, ordinal=0, db_path=db)
    with pytest.raises(InvestmentValidationError):
        store.update_investment_unit(visible.id, first.id, label=" ", unit_kind=UnitKind.PHASE, ordinal=0, db_path=db)


def _twelve_and_eighteen(db: Path) -> tuple[Any, Any, Any]:
    """Unit A $12.0M (Quick) and Unit B $18.0M (Detailed), priced at $30.0M,
    with a stale cache row seeded under the Investment's root."""

    a, b = quick_deal(db, purchase_price=12_000_000.0), detailed_deal(db, purchase_price=18_000_000.0)
    visible = create_investment(db, a, b)
    assert visible.transaction_price == 30_000_000.0
    connection = sqlite3.connect(db)
    connection.execute(
        "INSERT INTO variant_snapshots VALUES (?, 'base', 'base', '{}', 1, 'seeded', '2026-01-01T00:00:00+00:00')",
        (visible.id,),
    )
    connection.commit()
    connection.close()
    return a, b, visible


def test_removing_a_unit_without_a_reconciling_price_is_refused_and_changes_nothing(db: Path) -> None:
    """PP-2 holds when the removal commits: the old $30.0M no longer reconciles
    with A's $12.0M, and nothing derives a new price from B's."""

    a, b, visible = _twelve_and_eighteen(db)
    before = _every_row(db)

    with pytest.raises(InvestmentValidationError) as error:
        store.remove_investment_unit(visible.id, b.id, db_path=db)
    assert _codes(error) == [Code.ALLOCATION_MISMATCH]
    with pytest.raises(InvestmentValidationError) as error:
        store.remove_investment_unit(visible.id, b.id, transaction_price=12_500_000.0, db_path=db)
    assert _codes(error) == [Code.ALLOCATION_MISMATCH]
    with pytest.raises(InvestmentValidationError) as error:
        store.remove_investment_unit(visible.id, b.id, transaction_price=0.0, db_path=db)
    assert Code.INVALID_TRANSACTION_PRICE in _codes(error)

    assert _every_row(db) == before
    current = store.get_visible_investment(visible.id, db_path=db)
    assert [unit.unit_id for unit in current.units] == [a.id, b.id]
    assert current.transaction_price == 30_000_000.0
    assert [row[0] for row in rows(db, "investment_units") if row[1] == b.id] == [visible.id]
    assert len(rows(db, "variant_snapshots")) == 1


def test_removing_a_unit_with_the_restated_price_is_one_atomic_valid_change(db: Path) -> None:
    from anchor.deals.investment_variants import analyze_investment_variant, investment_variant_fingerprint

    a, b, visible = _twelve_and_eighteen(db)
    b_before = store.get_deal(b.id, db_path=db)

    remaining = store.remove_investment_unit(visible.id, b.id, transaction_price=12_000_000.0, db_path=db)

    assert [unit.unit_id for unit in remaining.units] == [a.id]
    assert remaining.transaction_price == 12_000_000.0
    assert rows(db, "investments")[0][1] == 0  # still visible, even with one Unit
    assert store.get_deal(b.id, db_path=db) == b_before
    assert store.list_deal_scenarios(b.id, db_path=db) == (None, [])
    assert [row[1] for row in rows(db, "investment_units")] == [a.id]
    assert p7_6_row_counts(db)["investment_unit_details"] == 1
    assert rows(db, "variant_snapshots") == []
    assert investment_variant_fingerprint(visible.id, "base", "base", db_path=db).source_fingerprint
    analysis = analyze_investment_variant(visible.id, "base", "base", db_path=db)
    assert abs(analysis.consolidated_results.allocation_variance) <= 0.01
    assert analysis.consolidated_results.allocated_purchase_price == 12_000_000.0


def test_an_injected_failure_rolls_the_whole_removal_back(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, b, visible = _twelve_and_eighteen(db)
    before = _every_row(db)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(store, "_write_visible_details", fail)
    with pytest.raises(RuntimeError, match="injected"):
        store.remove_investment_unit(visible.id, b.id, transaction_price=12_000_000.0, db_path=db)

    assert _every_row(db) == before


def test_the_last_unit_and_an_unknown_unit_are_refused(db: Path) -> None:
    a, b, visible = _twelve_and_eighteen(db)
    store.remove_investment_unit(visible.id, b.id, transaction_price=12_000_000.0, db_path=db)
    before = _every_row(db)

    with pytest.raises(InvestmentStructureError, match="last Unit"):
        store.remove_investment_unit(visible.id, a.id, transaction_price=12_000_000.0, db_path=db)
    with pytest.raises(InvestmentUnitNotFoundError):
        store.remove_investment_unit(visible.id, b.id, db_path=db)
    assert _every_row(db) == before


def test_a_unit_a_strategy_or_scenario_addresses_cannot_be_removed(db: Path) -> None:
    first, second = quick_deal(db), quick_deal(db)
    visible = create_investment(db, first, second)
    scenario = store.create_scenario(visible.id, name="Wide exit", overrides=(override(second.id, "exit_cap_rate", "add", 0.005),), db_path=db)
    strategy = store.create_strategy(visible.id, name="Hold", overlays=(f4.disposition(second.id, 5),), db_path=db)
    before = _every_row(db)

    with pytest.raises(InvestmentStructureError, match="Wide exit") as error:
        store.remove_investment_unit(visible.id, second.id, db_path=db)
    assert "Hold" in str(error.value)
    assert _every_row(db) == before

    store.update_scenario(visible.id, scenario.scenario.scenario_id, name="Wide exit", overrides=(override(first.id, "exit_cap_rate", "add", 0.005),), db_path=db)
    with pytest.raises(InvestmentStructureError, match="Hold"):
        store.remove_investment_unit(visible.id, second.id, db_path=db)
    store.delete_strategy(visible.id, strategy.strategy.strategy_id, db_path=db)
    released = store.remove_investment_unit(visible.id, second.id, transaction_price=price(first), db_path=db)
    assert [unit.unit_id for unit in released.units] == [first.id]


# =============================================================================
# Update the Investment's own inputs
# =============================================================================


def test_updating_the_details_plan_and_costs_is_one_validated_request(db: Path) -> None:
    first, second = quick_deal(db), detailed_deal(db)
    visible = create_investment(db, first, second)
    before = _every_row(db)

    with pytest.raises(InvestmentValidationError):
        store.update_visible_investment(
            visible.id, name="Renamed", transaction_price=visible.transaction_price + 5.0,
            business_plan=investment_plan(), transaction_costs=(cost("c", 1.0),), db_path=db,
        )
    assert _every_row(db) == before

    updated = store.update_visible_investment(
        visible.id, name="Renamed", transaction_price=visible.transaction_price + 0.01,
        business_plan=investment_plan(), transaction_costs=(cost("c", 1.0),), db_path=db,
    )
    assert (updated.name, updated.transaction_price, updated.business_plan) == (
        "Renamed", visible.transaction_price + 0.01, investment_plan(),
    )
    assert updated.units == visible.units and updated.created_at == visible.created_at


def test_a_corrupt_visible_investment_fails_closed(db: Path) -> None:
    deal = quick_deal(db)
    visible = create_investment(db, deal)
    connection = sqlite3.connect(db)
    connection.execute("DELETE FROM investment_details")
    connection.commit()
    connection.close()

    for read in (
        lambda: store.get_visible_investment(visible.id, db_path=db),
        lambda: store.list_scenarios(visible.id, db_path=db),
        lambda: store.create_scenario(visible.id, name="S", db_path=db),
    ):
        with pytest.raises(store.PersistedDealDataError):
            read()


# =============================================================================
# Delete -- the Investment releases its Deals; a Deal never leaves silently
# =============================================================================


def test_deleting_a_visible_investment_releases_every_deal_and_deletes_only_its_rows(db: Path) -> None:
    quick, detailed, lease = _deals(db)
    bystander = quick_deal(db)
    bystander_scenario = store.create_scenario_for_deal(bystander.id, name="Untouched", db_path=db)
    visible = create_investment(db, quick, detailed, lease, business_plan=investment_plan(), costs=(cost("c", 1.0),))
    store.create_scenario(visible.id, name="S", overrides=(override(quick.id, "exit_cap_rate", "add", 0.005),), db_path=db)
    store.create_strategy(visible.id, name="T", overlays=(f4.disposition(lease.id, 5),), db_path=db)
    deals_before = [store.get_deal(d.id, db_path=db) for d in (quick, detailed, lease)]

    store.delete_investment(visible.id, db_path=db)

    assert p7_6_row_counts(db) == P7_6_EMPTY
    assert [row[0] for row in rows(db, "investments")] == [bystander_scenario.investment_id]
    assert [store.get_deal(d.id, db_path=db) for d in (quick, detailed, lease)] == deals_before
    assert rows(db, "strategies") == [] and [row[1] for row in rows(db, "scenarios")] == [bystander_scenario.investment_id]


def test_deleting_a_deal_of_a_visible_investment_fails_closed(db: Path) -> None:
    deal, other = quick_deal(db), quick_deal(db)
    create_investment(db, deal, other)
    before = _every_row(db)

    with pytest.raises(InvestmentStructureError, match="Remove the Unit from the Investment"):
        store.delete_deal(deal.id, db_path=db)
    assert _every_row(db) == before


# =============================================================================
# Strategies and Scenarios of a visible Investment
# =============================================================================


def test_a_visible_investments_strategies_and_scenarios_address_its_units_and_never_collapse(db: Path) -> None:
    quick, detailed, lease = _deals(db)
    visible = create_investment(db, quick, detailed, lease)

    scenario = store.create_scenario(visible.id, name="Market", overrides=(
        override(quick.id, "exit_cap_rate", "add", 0.005),
        override(lease.id, "market_rent_psf", "scale", 0.9),
        override(detailed.id, "expense_growth", "add", 0.01),
    ), db_path=db)
    strategy = store.create_strategy(visible.id, name="Plan", overlays=(
        f4.plan_overlay(detailed.id, f4.renovation_plan()), f4.outcomes(quick.id, f4.outcome("exit_cap_rate", 0.06)),
    ), db_path=db)
    assert store.list_scenarios(visible.id, db_path=db) == [scenario]
    assert store.list_strategies(visible.id, db_path=db) == [strategy]

    store.delete_scenario(visible.id, scenario.scenario.scenario_id, db_path=db)
    store.delete_strategy(visible.id, strategy.strategy.strategy_id, db_path=db)
    assert store.get_visible_investment(visible.id, db_path=db).units == visible.units
    assert rows(db, "investments")[0][1] == 0


def test_a_foreign_unit_override_or_overlay_is_refused_never_ignored(db: Path) -> None:
    quick, detailed = quick_deal(db), detailed_deal(db)
    visible = create_investment(db, quick, detailed)
    with pytest.raises(ScenarioValidationError) as error:
        store.create_scenario(visible.id, name="S", overrides=(override("zzz-foreign", "exit_cap_rate", "add", 0.005),), db_path=db)
    assert [issue.code for issue in error.value.issues] == [ScenarioIssueCode.UNIT_NOT_IN_VARIANT]
    with pytest.raises(ScenarioValidationError):  # a Detailed target on the Quick Unit
        store.create_scenario(visible.id, name="S", overrides=(override(quick.id, "vacancy_credit_loss_pct", "add", 0.01),), db_path=db)
    from anchor.analysis.strategy import StrategyValidationError

    with pytest.raises(StrategyValidationError):
        store.create_strategy(visible.id, name="T", overlays=(f4.disposition("zzz-foreign", 5),), db_path=db)
    assert rows(db, "scenarios") == [] and rows(db, "strategies") == []


# =============================================================================
# The HTTP surface P7.6B builds on
# =============================================================================


@pytest.fixture
def client(db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    return TestClient(api_module.app)


def _body(*deals: Any, **extra: Any) -> dict[str, Any]:
    return {
        "name": "Portfolio",
        "transaction_price": sum(price(deal) for deal in deals),
        "units": [{"unit_id": deal.id, "unit_kind": "property"} for deal in deals],
        **extra,
    }


def test_the_visible_investment_routes_round_trip(client: TestClient, db: Path) -> None:
    quick, detailed, lease = _deals(db)
    created = client.post("/investments", json=_body(
        quick, detailed,
        business_plan={"capital_items": [{"item_id": "c", "description": "Systems", "category": "other", "month": 0, "amount": 1000.0}]},
        transaction_costs=[{"cost_id": "tc", "description": "Fee", "category": "acquisition_fee", "amount": 5000.0}],
    ))
    assert created.status_code == 200, created.text
    body = created.json()
    investment = body["id"]
    assert body["units"][0] == {
        "unit_id": quick.id, "ordinal": 0, "label": None, "unit_kind": "property", "acquisition_month": 0, "disposition_month": None,
    }
    assert body["transaction_costs"] == [{"cost_id": "tc", "description": "Fee", "category": "acquisition_fee", "amount": 5000.0, "model_month": 0}]
    assert client.get("/investments").json() == [body]
    assert client.get(f"/investments/{investment}/details").json() == body
    assert client.get(f"/investments/{investment}").json()["hidden"] is False

    added = client.post(f"/investments/{investment}/units", json={
        "unit_id": lease.id, "unit_kind": "component", "label": "Office", "transaction_price": body["transaction_price"] + price(lease),
    })
    assert added.status_code == 200, added.text
    assert [u["unit_id"] for u in added.json()["units"]] == [quick.id, detailed.id, lease.id]
    moved = client.put(f"/investments/{investment}/units/{lease.id}", json={"label": None, "unit_kind": "phase", "ordinal": 0})
    assert moved.status_code == 200, moved.text
    # Ordinal 0 now ties the first Unit's; ties break by unit_id, so assert the
    # metadata, never a position.
    (lease_entry,) = [u for u in moved.json()["units"] if u["unit_id"] == lease.id]
    assert (lease_entry["ordinal"], lease_entry["unit_kind"], lease_entry["label"]) == (0, "phase", None)
    removed = client.delete(
        f"/investments/{investment}/units/{lease.id}", params={"transaction_price": body["transaction_price"]}
    )
    assert removed.status_code == 200, removed.text
    assert len(removed.json()["units"]) == 2 and removed.json()["transaction_price"] == body["transaction_price"]

    details = client.put(f"/investments/{investment}/details", json={
        "name": "Renamed", "transaction_price": body["transaction_price"], "business_plan": None, "transaction_costs": [],
    })
    assert details.status_code == 200, details.text
    assert (details.json()["name"], details.json()["transaction_costs"]) == ("Renamed", [])
    assert client.delete(f"/investments/{investment}").status_code == 204
    assert client.get(f"/investments/{investment}/details").status_code == 404


def test_the_routes_report_refusals_with_their_status_and_reasons(client: TestClient, db: Path) -> None:
    quick, seven = quick_deal(db), quick_deal(db, hold_period=7)
    wrapped = quick_deal(db)
    record = store.create_scenario_for_deal(
        wrapped.id, name="S", overrides=(override(wrapped.id, "exit_cap_rate", "add", 0.005),), db_path=db
    )

    invalid = client.post("/investments", json=_body(quick, seven))
    assert invalid.status_code == 422
    assert [issue["code"] for issue in invalid.json()["detail"]] == ["hold_period_mismatch"]
    assert client.post("/investments", json={**_body(quick), "unknown": 1}).status_code == 422
    assert client.post("/investments", json={"name": "P", "transaction_price": 1.0}).status_code == 422
    plan = client.post("/investments", json=_body(quick, business_plan={"capital_items": [{"item_id": "x"}]}))
    assert plan.status_code == 422 and plan.json()["detail"][0]["path"].startswith("business_plan")
    assert client.post("/investments", json=_body(quick, wrapped)).status_code == 409
    missing = _body(quick)
    missing["units"].append({"unit_id": "0" * 32, "unit_kind": "property"})
    assert client.post("/investments", json=missing).status_code == 404
    assert client.get(f"/investments/{record.investment_id}/details").status_code == 409
    assert client.get(f"/investments/{'0' * 32}/details").status_code == 404

    promoted = client.post(f"/investments/{record.investment_id}/promote", json=_body(wrapped, quick))
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["id"] == record.investment_id
    assert client.delete(f"/deals/{wrapped.id}").status_code == 409
    assert client.delete(f"/investments/{record.investment_id}/units/{wrapped.id}").status_code == 409  # its Scenario addresses it
    assert client.delete(f"/investments/{record.investment_id}/units/{'0' * 32}").status_code == 404
    assert p7_6_row_counts(db)["investment_unit_details"] == 2


def test_the_removal_route_restates_the_price_atomically(client: TestClient, db: Path) -> None:
    a, b, visible = _twelve_and_eighteen(db)
    before = _every_row(db)

    refused = client.delete(f"/investments/{visible.id}/units/{b.id}")
    assert refused.status_code == 422
    assert [issue["code"] for issue in refused.json()["detail"]] == ["allocation_mismatch"]
    assert _every_row(db) == before

    removed = client.delete(f"/investments/{visible.id}/units/{b.id}", params={"transaction_price": 12_000_000})
    assert removed.status_code == 200, removed.text
    assert ([u["unit_id"] for u in removed.json()["units"]], removed.json()["transaction_price"]) == ([a.id], 12_000_000.0)
    analysis = client.post(f"/investments/{visible.id}/investment-variants/base/base/analysis")
    assert analysis.status_code == 200, analysis.text
    assert client.delete(f"/investments/{visible.id}/units/{a.id}", params={"transaction_price": 12_000_000}).status_code == 409
    assert client.delete(f"/investments/{visible.id}/units/{b.id}").status_code == 404


def test_no_ordinary_read_route_materializes_a_visible_investment(client: TestClient, db: Path) -> None:
    deal = quick_deal(db)
    for path in ("/deals", f"/deals/{deal.id}", f"/deals/{deal.id}/scenarios", f"/deals/{deal.id}/strategies", "/investments"):
        assert client.get(path).status_code == 200, path
    assert p7_6_row_counts(db) == P7_6_EMPTY and rows(db, "investments") == []
