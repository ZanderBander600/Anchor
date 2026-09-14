"""Shared P7.4 fixtures (not a test module).

Strategy overlays built from literals, their wire forms, and row counts over
every P7 table read from the database directly -- never through the store under
test -- so persistence claims are measured, not asserted by the code that makes
them. Deals come from the P7.2 fixtures, which build them from the P7.1 scenario
fixtures.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from anchor.analysis.scenario import ScenarioOperation, ScenarioTarget
from anchor.analysis.strategy import (
    AcquisitionChoice,
    DispositionChoice,
    FinancingChoice,
    OperatingOutcome,
    OperatingOutcomeSet,
    StrategyDefinition,
    StrategyDomain,
    StrategyOverlay,
)
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)

from _p7_2_fixtures import P7_2_TABLES, P7_4_TABLES, table_names  # type: ignore[import-not-found]

P7_TABLES = (*P7_2_TABLES, *P7_4_TABLES)


def p7_row_counts(db: Path) -> dict[str, int]:
    """Row counts of every P7 table. A database no P7 store has opened reports
    zero for each."""

    present = table_names(db)
    connection = sqlite3.connect(db)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if table in present
            else 0
            for table in P7_TABLES
        }
    finally:
        connection.close()


P7_EMPTY = dict.fromkeys(P7_TABLES, 0)


def counts(**expected: int) -> dict[str, int]:
    """``P7_EMPTY`` with the given tables' counts."""

    return {**P7_EMPTY, **expected}


# =============================================================================
# Overlays, as contracts
# =============================================================================


def acquisition(unit_id: str, *, purchase_price: Any = 9_500_000.0, acquisition_cost_pct: Any = 0.02) -> StrategyOverlay:
    return StrategyOverlay(
        unit_id=unit_id,
        domain=StrategyDomain.ACQUISITION,
        content=AcquisitionChoice(purchase_price=purchase_price, acquisition_cost_pct=acquisition_cost_pct),
    )


def financing(
    unit_id: str,
    *,
    ltv: Any = 0.60,
    interest_rate: Any = 0.0575,
    amortization: Any = 30,
    io_period: Any = 2,
    financing_fee_pct: Any = 0.01,
) -> StrategyOverlay:
    return StrategyOverlay(
        unit_id=unit_id,
        domain=StrategyDomain.FINANCING,
        content=FinancingChoice(
            ltv=ltv,
            interest_rate=interest_rate,
            amortization=amortization,
            io_period=io_period,
            financing_fee_pct=financing_fee_pct,
        ),
    )


def plan_overlay(unit_id: str, plan: BusinessPlan) -> StrategyOverlay:
    return StrategyOverlay(unit_id=unit_id, domain=StrategyDomain.BUSINESS_PLAN, content=plan)


def outcome(target: Any, value: Any, operation: Any = ScenarioOperation.SET) -> OperatingOutcome:
    """An outcome from members or wire tokens; a token that names no member
    stays raw."""

    def member(token_type: Any, token: Any) -> Any:
        try:
            return token_type(token)
        except (ValueError, TypeError):
            return token

    return OperatingOutcome(
        target=member(ScenarioTarget, target), operation=member(ScenarioOperation, operation), value=value
    )


def outcomes(unit_id: str, *entries: OperatingOutcome) -> StrategyOverlay:
    return StrategyOverlay(
        unit_id=unit_id, domain=StrategyDomain.OPERATING_OUTCOME, content=OperatingOutcomeSet(outcomes=entries)
    )


def disposition(unit_id: str, hold_period: Any = 7) -> StrategyOverlay:
    return StrategyOverlay(
        unit_id=unit_id, domain=StrategyDomain.DISPOSITION, content=DispositionChoice(hold_period=hold_period)
    )


def strategy(*overlays: StrategyOverlay, strategy_id: str = "strategy-a", name: str = "Strategy A", description: str | None = None) -> StrategyDefinition:
    return StrategyDefinition(strategy_id=strategy_id, name=name, description=description, overlays=overlays)


def renovation_plan() -> BusinessPlan:
    """A value-add renovation the analyst entered -- a different plan from the
    P7.1 fixture plan, so replacing one with the other is visible."""

    return BusinessPlan(
        capital_items=(
            CapitalPlanItem(
                item_id="reno-units",
                description="Unit renovations",
                category=CapitalItemCategory.VALUE_ADD_RENOVATION,
                month=6,
                amount=5_000_000.0,
            ),
            CapitalPlanItem(
                item_id="reno-amenity",
                description="Amenity package",
                category=CapitalItemCategory.EXTERIOR_COMMON_AREA,
                month=0,
                amount=750_000.0,
            ),
        ),
        owner_expense_items=(
            OwnerExpenseItem(
                item_id="reno-oversight",
                description="Construction oversight",
                category=OwnerExpenseCategory.ASSET_MANAGEMENT,
                annual_amount=60_000.0,
                first_year=1,
                last_year=2,
            ),
        ),
    )


# =============================================================================
# The same overlays on the wire
# =============================================================================


def wire(overlay: StrategyOverlay) -> dict[str, Any]:
    """An overlay as the API accepts and returns it."""

    content: Any = overlay.content
    if isinstance(content, AcquisitionChoice):
        body: Any = {"purchase_price": content.purchase_price, "acquisition_cost_pct": content.acquisition_cost_pct}
    elif isinstance(content, FinancingChoice):
        body = {
            "ltv": content.ltv,
            "interest_rate": content.interest_rate,
            "amortization": content.amortization,
            "io_period": content.io_period,
            "financing_fee_pct": content.financing_fee_pct,
        }
    elif isinstance(content, BusinessPlan):
        body = {
            "capital_items": [
                {
                    "item_id": item.item_id,
                    "description": item.description,
                    "category": item.category.value,
                    "month": item.month,
                    "amount": item.amount,
                }
                for item in content.capital_items
            ],
            "owner_expense_items": [
                {
                    "item_id": item.item_id,
                    "description": item.description,
                    "category": item.category.value,
                    "annual_amount": item.annual_amount,
                    "first_year": item.first_year,
                    "last_year": item.last_year,
                }
                for item in content.owner_expense_items
            ],
        }
    elif isinstance(content, OperatingOutcomeSet):
        body = {
            "outcomes": [
                {
                    "target": getattr(entry.target, "value", entry.target),
                    "operation": getattr(entry.operation, "value", entry.operation),
                    "value": entry.value,
                }
                for entry in content.outcomes
            ]
        }
    else:
        body = {"hold_period": content.hold_period}
    return {"unit_id": overlay.unit_id, "domain": overlay.domain.value, "content": body}
