"""Shared P7.6 fixtures (not a test module).

Saved Deals of every mode on one common five-year hold, visible-Investment
builders, an Investment-level Business Plan, and row counts read from the
database directly -- never through the store under test. Deals are built from the
P7.1 scenario fixtures, so every economic input is a literal.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from _p7_2_fixtures import P7_6_TABLES, table_names  # type: ignore[import-not-found]
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from anchor.deals import store
from anchor.deals.contracts import Deal, VisibleInvestment
from anchor.investment import (
    InvestmentTransactionCost,
    InvestmentUnitMembership,
    TransactionCostCategory,
    UnitKind,
)

#: The common Investment horizon every P7.6 Deal is saved with.
HOLD = 5


def member(
    unit_id: str,
    *,
    ordinal: int = 0,
    label: str | None = None,
    kind: Any = UnitKind.PROPERTY,
    acquisition_month: Any = 0,
    disposition_month: Any = None,
) -> InvestmentUnitMembership:
    return InvestmentUnitMembership(
        unit_id=unit_id,
        ordinal=ordinal,
        label=label,
        unit_kind=kind,
        acquisition_month=acquisition_month,
        disposition_month=disposition_month,
    )


def cost(
    cost_id: str,
    amount: Any,
    *,
    description: Any = "Acquisition fee",
    category: Any = TransactionCostCategory.ACQUISITION_FEE,
    model_month: Any = 0,
) -> InvestmentTransactionCost:
    return InvestmentTransactionCost(
        cost_id=cost_id, description=description, category=category, amount=amount, model_month=model_month
    )


def price(deal: Deal) -> float:
    terms = deal.inputs if deal.inputs is not None else deal.terms
    assert terms is not None
    return terms.purchase_price


# =============================================================================
# Deals on the common hold
# =============================================================================


def quick_deal(db: Path, *, business_plan: BusinessPlan = BusinessPlan(), name: str = "Quick unit", **inputs: Any) -> Deal:
    return store.create_deal(name, fx.quick_inputs(**{"hold_period": HOLD, **inputs}), business_plan=business_plan, db_path=db)


def detailed_deal(db: Path, *, business_plan: BusinessPlan = BusinessPlan(), name: str = "Detailed unit", **terms: Any) -> Deal:
    return store.create_detailed_deal(
        name, fx.detailed_terms(**{"hold_period": HOLD, **terms}), fx.detailed_operating(),
        business_plan=business_plan, db_path=db,
    )


def lease_level_deal(
    db: Path,
    *,
    business_plan: BusinessPlan = BusinessPlan(),
    start: date | None = None,
    name: str = "Lease-Level unit",
    **terms: Any,
) -> Deal:
    suites, leases = fx.rent_roll()
    property_inputs = fx.lease_level_property()
    if start is not None:
        property_inputs = dataclasses.replace(property_inputs, analysis_start_date=start)
    return store.create_lease_level_deal(
        name, fx.lease_level_terms(**{"hold_period": HOLD, **terms}), property_inputs,
        fx.lease_level_operating(), fx.market(), tuple(suites), tuple(leases),
        business_plan=business_plan, db_path=db,
    )


def deal_of(mode: str, db: Path, **kwargs: Any) -> Deal:
    return {"quick": quick_deal, "detailed": detailed_deal, "lease_level": lease_level_deal}[mode](db, **kwargs)


def create_investment(
    db: Path,
    *deals: Deal,
    transaction_price: float | None = None,
    business_plan: BusinessPlan = BusinessPlan(),
    costs: tuple[InvestmentTransactionCost, ...] = (),
    name: str = "Portfolio",
) -> VisibleInvestment:
    """A visible Investment over ``deals``, in the given display order, priced at
    exactly the sum of their purchase prices unless told otherwise."""

    return store.create_visible_investment(
        name=name,
        transaction_price=sum(price(deal) for deal in deals) if transaction_price is None else transaction_price,
        units=tuple(member(deal.id, ordinal=index) for index, deal in enumerate(deals)),
        business_plan=business_plan,
        transaction_costs=costs,
        db_path=db,
    )


# =============================================================================
# The Investment-level Business Plan
# =============================================================================


def investment_plan() -> BusinessPlan:
    """Shared owner-level costs: closing capital, in-hold capital in Year 2,
    capital after a five-year hold (disclosure only), and an open-ended owner
    expense."""

    return BusinessPlan(
        capital_items=(
            CapitalPlanItem(
                item_id="inv-closing", description="Portfolio systems", category=CapitalItemCategory.OTHER,
                month=0, amount=200_000.0,
            ),
            CapitalPlanItem(
                item_id="inv-year-2", description="Shared amenity", category=CapitalItemCategory.VALUE_ADD_RENOVATION,
                month=18, amount=300_000.0,
            ),
            CapitalPlanItem(
                item_id="inv-post-hold", description="Deferred works", category=CapitalItemCategory.BUILDING_SYSTEMS,
                month=70, amount=125_000.0,
            ),
        ),
        owner_expense_items=(
            OwnerExpenseItem(
                item_id="inv-asset-management", description="Portfolio asset management",
                category=OwnerExpenseCategory.ASSET_MANAGEMENT, annual_amount=75_000.0, first_year=1, last_year=None,
            ),
        ),
    )


# =============================================================================
# Reading the database directly
# =============================================================================


def p7_6_row_counts(db: Path) -> dict[str, int]:
    present = table_names(db)
    connection = sqlite3.connect(db)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if table in present else 0
            for table in P7_6_TABLES
        }
    finally:
        connection.close()


P7_6_EMPTY = dict.fromkeys(P7_6_TABLES, 0)
