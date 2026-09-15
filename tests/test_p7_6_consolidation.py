"""Phase 7 Gate P7.6 -- consolidation, the Tier 1 core.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 9 (CON-1
to CON-3, 9.2 to 9.4, 9.6), 10 (BP-2 to BP-4) and 11 (PP-2, PP-3, TC-1, TC-2).

Every expected consolidated figure here is computed independently of
``consolidate``: from literals worked by hand, or from each Unit's completed
``AcquisitionResults`` with plain ``math.fsum`` arithmetic and an IRR found by
an independent bisection on NPV. Unit results come from the existing engine,
which is the authority for a Unit.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from anchor.analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
    resolve_business_plan,
)
from anchor.consolidation import (
    AreaMetricReason,
    ConsolidatedResults,
    ConsolidationError,
    ConsolidationUnit,
    consolidate,
)
from anchor.engine.contracts import AcquisitionResults, IrrStatus, OwnerCapitalSchedule
from anchor.investment import TransactionCostCategory

from _p7_6_fixtures import HOLD, cost, investment_plan  # type: ignore[import-not-found]


# =============================================================================
# Unit results, straight from the existing engine
# =============================================================================


def _quick(**inputs: Any) -> tuple[AcquisitionResults, float]:
    values = fx.quick_inputs(**{"hold_period": HOLD, **inputs})
    return analyze_quick_acquisition_with_business_plan(values, business_plan=inputs.pop("_plan", BusinessPlan())), values.purchase_price


def _unit(unit_id: str, results: Any, purchase_price: float, *, area: bool = False) -> ConsolidationUnit:
    project = getattr(results, "results", results)
    occupied = results.annual_projection.occupied_area_at_year_end if area else None
    vacant = results.annual_projection.vacant_area_at_year_end if area else None
    return ConsolidationUnit(
        unit_id=unit_id, purchase_price=purchase_price, hold_period=len(project.noi_by_year), results=project,
        occupied_area_at_year_end=occupied, vacant_area_at_year_end=vacant,
    )


def _envelope(mode: str, *, business_plan: BusinessPlan = BusinessPlan(), **terms: Any) -> tuple[Any, float]:
    if mode == "quick":
        inputs = fx.quick_inputs(**{"hold_period": HOLD, **terms})
        return analyze_quick_acquisition_with_business_plan(inputs, business_plan=business_plan), inputs.purchase_price
    if mode == "detailed":
        acquisition = fx.detailed_terms(**{"hold_period": HOLD, **terms})
        return (
            analyze_detailed_acquisition_with_business_plan(acquisition, fx.detailed_operating(), business_plan=business_plan),
            acquisition.purchase_price,
        )
    acquisition = fx.lease_level_terms(**{"hold_period": HOLD, **terms})
    suites, leases = fx.rent_roll()
    return (
        analyze_lease_level_acquisition_with_business_plan(
            acquisition, fx.lease_level_property(), suites, leases,
            market_leasing=fx.market(), operating_inputs=fx.lease_level_operating(), business_plan=business_plan,
        ),
        acquisition.purchase_price,
    )


# =============================================================================
# The one-unit parity oracle -- the primary neutral oracle (Section 9.6)
# =============================================================================

#: Every consolidated figure with a direct Unit analogue, and that analogue.
_ANALOGUES = {
    "loan_amount": "loan_amount",
    "acquisition_costs": "acquisition_costs",
    "financing_fees": "financing_fee",
    "initial_equity": "initial_equity",
    "closing_project_capital": "closing_project_capital",
    "total_closing_uses": "total_closing_uses",
    "total_closing_sources": "total_closing_sources",
    "noi_by_year": "noi_by_year",
    "capex_by_year": "capex_by_year",
    "tenant_improvements_by_year": "tenant_improvements_by_year",
    "leasing_commissions_by_year": "leasing_commissions_by_year",
    "property_cash_flow_by_year": "property_cash_flow_by_year",
    "project_capital_by_year": "project_capital_by_year",
    "owner_expenses_by_year": "owner_expenses_by_year",
    "unlevered_owner_cash_flow_by_year": "unlevered_owner_cash_flow_by_year",
    "annual_debt_service": "annual_debt_service",
    "levered_owner_cash_flow_by_year": "levered_owner_cash_flow_by_year",
    "remaining_loan_balance": "remaining_loan_balance",
    "exit_noi": "exit_noi",
    "exit_value": "exit_value",
    "disposition_costs": "disposition_costs",
    "net_sale_proceeds": "net_sale_proceeds",
    "post_hold_project_capital": "post_hold_project_capital",
    "unlevered_cash_flows": "unlevered_cash_flows",
    "levered_cash_flows": "levered_cash_flows",
    "unlevered_irr": "unlevered_irr",
    "unlevered_irr_status": "unlevered_irr_status",
    "levered_irr": "levered_irr",
    "levered_irr_status": "levered_irr_status",
    "total_equity_invested": "total_equity_invested",
    "total_cash_returned": "total_cash_returned",
    "total_profit": "total_profit",
    "equity_multiple": "equity_multiple",
    "net_additional_equity_requirement_by_year": "net_additional_equity_requirement_by_year",
    "aggregate_dscr_by_year": "dscr_by_year",
    "headline_aggregate_dscr": "headline_dscr",
    "min_aggregate_dscr": "min_dscr",
    "going_in_cap_rate": "going_in_cap_rate",
    "year_1_debt_yield": "year_1_debt_yield",
    "levered_cash_on_cash_by_year": "levered_cash_on_cash_by_year",
    "unlevered_cash_yield_by_year": "unlevered_cash_yield_by_year",
    "cumulative_operating_distributions_by_year": "cumulative_operating_distributions_by_year",
}


def _bits(value: Any) -> Any:
    """``value`` with every float as its exact hex, so ``-0.0`` and ``0.0``
    and the last bit all count."""

    if isinstance(value, float):
        return value.hex()
    if isinstance(value, tuple):
        return tuple(_bits(item) for item in value)
    return value


@pytest.mark.parametrize("mode", ["quick", "detailed", "lease_level"])
@pytest.mark.parametrize("with_plan", [False, True])
def test_a_one_unit_investment_reproduces_its_unit_bit_for_bit(mode: str, with_plan: bool) -> None:
    envelope, price = _envelope(mode, business_plan=fx.business_plan() if with_plan else BusinessPlan())
    unit = envelope.results if mode != "quick" else envelope

    consolidated = consolidate([_unit("u", envelope, price)], transaction_price=price)

    assert {name: _bits(getattr(consolidated, name)) for name in _ANALOGUES} == {
        name: _bits(getattr(unit, analogue)) for name, analogue in _ANALOGUES.items()
    }
    assert consolidated.unlevered_project_basis == -unit.unlevered_cash_flows[0]
    assert (consolidated.transaction_price, consolidated.allocated_purchase_price, consolidated.allocation_variance) == (price, price, 0.0)
    assert (consolidated.investment_transaction_costs, consolidated.investment_closing_project_capital) == (0.0, 0.0)


def test_the_parity_oracle_sees_a_single_bit() -> None:
    envelope, price = _envelope("quick")
    moved = dataclasses.replace(envelope, noi_by_year=(math.nextafter(envelope.noi_by_year[0], math.inf), *envelope.noi_by_year[1:]))
    consolidated = consolidate([_unit("u", moved, price)], transaction_price=price)
    assert _bits(consolidated.noi_by_year) != _bits(envelope.noi_by_year)


# =============================================================================
# A golden worked by hand -- two Quick Units, flat NOI, interest-only debt
# =============================================================================


def _hand_units() -> list[ConsolidationUnit]:
    """Unit A: $10.0M, NOI $800k flat, 8.0% exit, 50% LTV interest-only at
    6.0%. Unit B: $6.0M, NOI $540k flat, 9.0% exit, all cash. No transaction
    costs, reserves or Business Plans at the Unit level."""

    neutral = {
        "noi_growth": 0.0, "acquisition_cost_pct": 0.0, "financing_fee_pct": 0.0,
        "disposition_cost_pct": 0.0, "annual_capex_reserve": 0.0, "amortization": 30,
    }
    a, price_a = _quick(purchase_price=10_000_000.0, current_noi=800_000.0, exit_cap_rate=0.08, ltv=0.5, interest_rate=0.06, io_period=5, **neutral)
    b, price_b = _quick(purchase_price=6_000_000.0, current_noi=540_000.0, exit_cap_rate=0.09, ltv=0.0, interest_rate=0.06, io_period=0, **neutral)
    return [_unit("unit-a", a, price_a), _unit("unit-b", b, price_b)]


def _hand_plan() -> OwnerCapitalSchedule:
    plan = BusinessPlan(
        capital_items=(
            CapitalPlanItem(item_id="c", description="Systems", category=CapitalItemCategory.OTHER, month=0, amount=50_000.0),
        ),
        owner_expense_items=(
            OwnerExpenseItem(
                item_id="o", description="Asset management", category=OwnerExpenseCategory.ASSET_MANAGEMENT,
                annual_amount=20_000.0, first_year=1, last_year=None,
            ),
        ),
    )
    return resolve_business_plan(plan, hold_period=HOLD)


def test_the_hand_worked_golden() -> None:
    c = consolidate(
        _hand_units(), transaction_price=16_000_000.0, investment_owner_capital=_hand_plan(),
        transaction_costs=(cost("fee", 100_000.0),),
    )
    approx = lambda value: pytest.approx(value, rel=1e-12, abs=1e-6)  # noqa: E731

    # Closing: $16.0M of Units, $5.0M of debt, $50k shared capital, $100k costs.
    assert (c.allocated_purchase_price, c.transaction_price, c.allocation_variance) == (16_000_000.0, 16_000_000.0, 0.0)
    assert c.loan_amount == approx(5_000_000.0)
    assert c.investment_transaction_costs == 100_000.0 and c.investment_closing_project_capital == 50_000.0
    assert c.initial_equity == approx(11_150_000.0)
    assert c.total_closing_uses == approx(16_150_000.0) and c.total_closing_sources == approx(16_150_000.0)
    assert c.unlevered_project_basis == approx(16_150_000.0)

    # Annual: NOI $1.34M, debt service $300k, shared owner expense $20k.
    assert c.noi_by_year == approx((1_340_000.0,) * 5)
    assert c.annual_debt_service == approx((300_000.0,) * 5)
    assert c.property_cash_flow_by_year == approx((1_340_000.0,) * 5)
    assert c.owner_expenses_by_year == approx((20_000.0,) * 5)
    assert c.unlevered_owner_cash_flow_by_year == approx((1_320_000.0,) * 5)
    assert c.levered_owner_cash_flow_by_year == approx((1_020_000.0,) * 5)

    # Exit: $10.0M + $6.0M gross; $5.0M balance repaid.
    assert (c.exit_noi, c.exit_value, c.remaining_loan_balance) == (approx(1_340_000.0), approx(16_000_000.0), approx(5_000_000.0))
    assert c.net_sale_proceeds == approx(11_000_000.0)

    # Project cash flows.
    assert c.unlevered_cash_flows == approx((-16_150_000.0, 1_320_000.0, 1_320_000.0, 1_320_000.0, 1_320_000.0, 17_320_000.0))
    assert c.levered_cash_flows == approx((-11_150_000.0, 1_020_000.0, 1_020_000.0, 1_020_000.0, 1_020_000.0, 12_020_000.0))

    # Returns derived from those series.
    assert (c.total_equity_invested, c.total_cash_returned, c.total_profit) == (approx(11_150_000.0), approx(16_100_000.0), approx(4_950_000.0))
    assert c.equity_multiple == approx(16_100_000.0 / 11_150_000.0)
    assert c.net_additional_equity_requirement_by_year == (0.0,) * 5
    assert c.levered_irr_status is c.unlevered_irr_status is IrrStatus.DEFINED
    assert c.levered_irr == pytest.approx(_irr([-11_150_000.0, 1_020_000.0, 1_020_000.0, 1_020_000.0, 1_020_000.0, 12_020_000.0]), abs=1e-9)
    unit_irrs = [unit.results.levered_irr for unit in _hand_units()]
    assert all(irr is not None for irr in unit_irrs)
    assert c.levered_irr != pytest.approx(math.fsum(unit_irrs) / 2, abs=1e-6)  # never an average
    assert c.unlevered_irr == pytest.approx(_irr([-16_150_000.0, 1_320_000.0, 1_320_000.0, 1_320_000.0, 1_320_000.0, 17_320_000.0]), abs=1e-9)

    # Ratios.
    assert c.aggregate_dscr_by_year == approx((1_340_000.0 / 300_000.0,) * 5)
    assert c.headline_aggregate_dscr == c.min_aggregate_dscr == approx(1_340_000.0 / 300_000.0)
    assert c.going_in_cap_rate == approx(0.08375) and c.implied_exit_cap_rate == approx(0.08375)
    assert c.year_1_debt_yield == approx(0.268)
    assert c.levered_cash_on_cash_by_year == approx((1_020_000.0 / 11_150_000.0,) * 5)
    assert c.unlevered_cash_yield_by_year == approx((1_320_000.0 / 16_150_000.0,) * 5)
    assert c.cumulative_operating_distributions_by_year == approx(tuple(1_020_000.0 * y for y in range(1, 6)))


# =============================================================================
# The mixed three-Unit golden -- Quick + Detailed + Lease-Level
# =============================================================================


def _irr(flows: list[float]) -> float:
    """An independent IRR: bisection on NPV, never the engine's solver."""

    def npv(rate: float) -> float:
        return math.fsum(flow / (1.0 + rate) ** t for t, flow in enumerate(flows))

    low, high = -0.95, 5.0
    assert npv(low) > 0 > npv(high)
    for _ in range(300):
        mid = (low + high) / 2
        if npv(mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _mixed_units() -> list[tuple[str, Any, float]]:
    """Three Units on one five-year hold with different prices, LTVs, rates and
    exit caps, each with its own Business Plan. The Detailed Unit's Year-2 plan
    capital makes its own Year-2 Equity Cash Flow negative."""

    detailed_plan = BusinessPlan(
        capital_items=(
            CapitalPlanItem(item_id="d-reno", description="Renovation", category=CapitalItemCategory.VALUE_ADD_RENOVATION, month=15, amount=1_600_000.0),
        ),
    )
    quick, quick_price = _envelope("quick", business_plan=fx.business_plan(), ltv=0.65, interest_rate=0.0575, exit_cap_rate=0.0625)
    detailed, detailed_price = _envelope("detailed", business_plan=detailed_plan, ltv=0.55, interest_rate=0.0625, exit_cap_rate=0.07)
    lease_level, lease_price = _envelope("lease_level", ltv=0.60, interest_rate=0.055, exit_cap_rate=0.065)
    return [("u-detailed", detailed, detailed_price), ("u-lease", lease_level, lease_price), ("u-quick", quick, quick_price)]


def _mixed_costs() -> tuple[Any, ...]:
    return (cost("tc-legal", 85_000.0), cost("tc-dd", 40_000.0), cost("tc-fee", 250_000.0))


def _fsum_series(series: list[tuple[float, ...]]) -> list[float]:
    return [math.fsum(values) for values in zip(*series, strict=True)]


def test_the_mixed_three_unit_golden() -> None:
    raw = _mixed_units()
    units = [_unit(unit_id, envelope, price, area=unit_id == "u-lease") for unit_id, envelope, price in raw]
    results = [unit.results for unit in units]
    plan = resolve_business_plan(investment_plan(), hold_period=HOLD)
    costs = _mixed_costs()
    total_price = math.fsum(unit.purchase_price for unit in units)
    close = lambda value: pytest.approx(value, rel=1e-11, abs=1e-5)  # noqa: E731

    c = consolidate(units, transaction_price=total_price, investment_owner_capital=plan, transaction_costs=costs)

    # Premises of the fixture: a Unit with a negative year the others offset.
    detailed = results[0]
    assert detailed.levered_cash_flows[2] < 0
    assert math.fsum(r.levered_cash_flows[2] for r in results) - plan.project_capital_by_year[1] - plan.owner_expenses_by_year[1] > 0

    tc = math.fsum(item.amount for item in costs)
    loan = math.fsum(r.loan_amount for r in results)
    initial_equity = math.fsum([*(r.initial_equity for r in results), plan.closing_project_capital, tc])
    uses = math.fsum([*(r.total_closing_uses for r in results), plan.closing_project_capital, tc])
    assert (c.transaction_price, c.allocated_purchase_price) == (total_price, close(total_price))
    assert c.investment_transaction_costs == tc == 375_000.0
    assert c.acquisition_costs == close(math.fsum(r.acquisition_costs for r in results))
    assert c.financing_fees == close(math.fsum(r.financing_fee for r in results))
    assert c.closing_project_capital == close(math.fsum([*(r.closing_project_capital for r in results), plan.closing_project_capital]))
    assert c.loan_amount == close(loan) and c.initial_equity == close(initial_equity)
    assert c.total_closing_uses == close(uses) and c.total_closing_sources == close(loan + initial_equity)
    assert c.initial_equity == close(c.total_closing_uses - c.loan_amount)

    noi = _fsum_series([r.noi_by_year for r in results])
    debt_service = _fsum_series([r.annual_debt_service for r in results])
    inv_pc, inv_oe = plan.project_capital_by_year, plan.owner_expenses_by_year
    uocf = [u - pc - oe for u, pc, oe in zip(_fsum_series([r.unlevered_owner_cash_flow_by_year for r in results]), inv_pc, inv_oe, strict=True)]
    locf = [lv - pc - oe for lv, pc, oe in zip(_fsum_series([r.levered_owner_cash_flow_by_year for r in results]), inv_pc, inv_oe, strict=True)]
    assert c.noi_by_year == close(tuple(noi))
    assert c.capex_by_year == close(tuple(_fsum_series([r.capex_by_year for r in results])))
    assert c.tenant_improvements_by_year == close(tuple(_fsum_series([r.tenant_improvements_by_year for r in results])))
    assert c.leasing_commissions_by_year == close(tuple(_fsum_series([r.leasing_commissions_by_year for r in results])))
    assert c.property_cash_flow_by_year == close(tuple(_fsum_series([r.property_cash_flow_by_year for r in results])))
    assert c.project_capital_by_year == close(tuple(p + q for p, q in zip(_fsum_series([r.project_capital_by_year for r in results]), inv_pc, strict=True)))
    assert c.owner_expenses_by_year == close(tuple(p + q for p, q in zip(_fsum_series([r.owner_expenses_by_year for r in results]), inv_oe, strict=True)))
    assert c.annual_debt_service == close(tuple(debt_service))
    assert c.unlevered_owner_cash_flow_by_year == close(tuple(uocf))
    assert c.levered_owner_cash_flow_by_year == close(tuple(locf))

    ucf = _fsum_series([r.unlevered_cash_flows for r in results])
    lcf = _fsum_series([r.levered_cash_flows for r in results])
    ucf = [ucf[0] - plan.closing_project_capital - tc, *(v - pc - oe for v, pc, oe in zip(ucf[1:], inv_pc, inv_oe, strict=True))]
    lcf = [lcf[0] - plan.closing_project_capital - tc, *(v - pc - oe for v, pc, oe in zip(lcf[1:], inv_pc, inv_oe, strict=True))]
    assert c.unlevered_cash_flows == close(tuple(ucf)) and c.levered_cash_flows == close(tuple(lcf))

    exit_noi = math.fsum(r.exit_noi for r in results)
    exit_value = math.fsum(r.exit_value for r in results)
    assert c.exit_noi == close(exit_noi) and c.exit_value == close(exit_value)
    assert c.remaining_loan_balance == close(math.fsum(r.remaining_loan_balance for r in results))
    assert c.disposition_costs == close(math.fsum(r.disposition_costs for r in results))
    assert c.net_sale_proceeds == close(math.fsum(r.net_sale_proceeds for r in results))
    assert c.post_hold_project_capital == close(math.fsum([*(r.post_hold_project_capital for r in results), plan.post_hold_project_capital]))
    assert c.investment_post_hold_project_capital == 125_000.0

    # Returns from the consolidated series, never from the Units'.
    tei = -math.fsum(v for v in lcf if v < 0)
    tcr = math.fsum(v for v in lcf if v > 0)
    assert c.total_equity_invested == close(tei) and c.total_cash_returned == close(tcr)
    assert c.total_profit == close(tcr - tei) and c.total_profit == close(math.fsum(lcf))
    assert c.equity_multiple == close(tcr / tei)
    assert c.net_additional_equity_requirement_by_year == close(tuple(max(-v, 0.0) for v in lcf[1:]))
    assert c.total_equity_invested == close(c.initial_equity + math.fsum(c.net_additional_equity_requirement_by_year))
    assert tei != pytest.approx(math.fsum(r.total_equity_invested for r in results))  # TEI is not additive
    assert c.levered_irr_status is IrrStatus.DEFINED and c.unlevered_irr_status is IrrStatus.DEFINED
    assert c.levered_irr == pytest.approx(_irr(lcf), abs=1e-8)
    assert c.unlevered_irr == pytest.approx(_irr(ucf), abs=1e-8)
    # The Detailed Unit alone has multiple sign changes and no IRR, yet the
    # consolidated series has one: a Unit's IRR status is never the Investment's.
    assert results[0].levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES

    dscr = [n / d for n, d in zip(noi, debt_service, strict=True)]
    assert c.aggregate_dscr_by_year == close(tuple(dscr))
    assert c.headline_aggregate_dscr == close(dscr[0]) and c.min_aggregate_dscr == close(min(dscr))
    assert c.going_in_cap_rate == close(noi[0] / total_price)
    assert c.year_1_debt_yield == close(noi[0] / loan)
    assert c.implied_exit_cap_rate == close(exit_noi / exit_value)
    assert c.levered_cash_on_cash_by_year == close(tuple(v / initial_equity for v in locf))
    assert c.unlevered_cash_yield_by_year == close(tuple(v / -ucf[0] for v in uocf))
    assert c.physical_occupancy_at_year_end is None and c.physical_occupancy_reason is AreaMetricReason.UNIT_WITHOUT_AREA_MEASURE


# =============================================================================
# CON-3 -- canonical order, never display order
# =============================================================================


def _synthetic(unit_id: str, noi: float) -> ConsolidationUnit:
    base, price = _quick()
    return ConsolidationUnit(
        unit_id=unit_id, purchase_price=price, hold_period=HOLD,
        results=dataclasses.replace(base, noi_by_year=(noi, *base.noi_by_year[1:])),
    )


def test_units_are_summed_in_unit_id_order_whatever_order_they_arrive_in() -> None:
    units = [_synthetic("unit-c", 0.3), _synthetic("unit-a", 0.1), _synthetic("unit-b", 0.2)]
    price = math.fsum(unit.purchase_price for unit in units)

    orders = [consolidate(ordering, transaction_price=price) for ordering in (units, units[::-1], sorted(units, key=lambda u: u.unit_id))]

    assert {_bits(result.noi_by_year[0]) for result in orders} == {(0.1 + 0.2 + 0.3).hex()}
    assert (0.3 + 0.2 + 0.1) != (0.1 + 0.2 + 0.3)  # the order is observable
    assert all(result.unit_ids == ("unit-a", "unit-b", "unit-c") for result in orders)
    assert len({_bits(dataclasses.astuple(result)) for result in orders}) == 1


# =============================================================================
# The Investment Business Plan oracle (BP-2, BP-3, BP-4)
# =============================================================================


def test_the_investment_plan_enters_consolidation_once_and_nowhere_else() -> None:
    units = [_unit(unit_id, envelope, price) for unit_id, envelope, price in _mixed_units()]
    before_units = [dataclasses.astuple(unit.results) for unit in units]
    price = math.fsum(unit.purchase_price for unit in units)
    plan = resolve_business_plan(investment_plan(), hold_period=HOLD)

    without = consolidate(units, transaction_price=price)
    with_plan = consolidate(units, transaction_price=price, investment_owner_capital=plan)

    assert [dataclasses.astuple(unit.results) for unit in units] == before_units
    for unchanged in ("noi_by_year", "property_cash_flow_by_year", "annual_debt_service", "aggregate_dscr_by_year",
                      "exit_value", "exit_noi", "net_sale_proceeds", "loan_amount", "remaining_loan_balance", "year_1_debt_yield"):
        assert getattr(with_plan, unchanged) == getattr(without, unchanged), unchanged
    assert with_plan.initial_equity == pytest.approx(without.initial_equity + 200_000.0)
    assert with_plan.total_closing_uses == pytest.approx(without.total_closing_uses + 200_000.0)
    assert with_plan.closing_project_capital == pytest.approx(without.closing_project_capital + 200_000.0)
    assert with_plan.levered_cash_flows[0] == pytest.approx(without.levered_cash_flows[0] - 200_000.0)
    assert with_plan.unlevered_cash_flows[0] == pytest.approx(without.unlevered_cash_flows[0] - 200_000.0)
    charges = [75_000.0, 375_000.0, 75_000.0, 75_000.0, 75_000.0]  # Year 2 carries the month-18 capital
    for year, charge in enumerate(charges):
        assert with_plan.unlevered_owner_cash_flow_by_year[year] == pytest.approx(without.unlevered_owner_cash_flow_by_year[year] - charge)
        assert with_plan.levered_owner_cash_flow_by_year[year] == pytest.approx(without.levered_owner_cash_flow_by_year[year] - charge)
        assert with_plan.levered_cash_flows[year + 1] == pytest.approx(without.levered_cash_flows[year + 1] - charge)
        assert with_plan.unlevered_cash_flows[year + 1] == pytest.approx(without.unlevered_cash_flows[year + 1] - charge)
    assert with_plan.post_hold_project_capital == pytest.approx(without.post_hold_project_capital + 125_000.0)
    assert with_plan.investment_project_capital_by_year == (0.0, 300_000.0, 0.0, 0.0, 0.0)
    assert with_plan.investment_owner_expenses_by_year == (75_000.0,) * 5


def test_a_plan_resolved_for_another_hold_is_refused() -> None:
    units = [_unit("u", *_quick())]
    with pytest.raises(ConsolidationError):
        consolidate(units, transaction_price=units[0].purchase_price, investment_owner_capital=resolve_business_plan(investment_plan(), hold_period=7))


# =============================================================================
# The transaction-cost oracle (TC-1, TC-2)
# =============================================================================


def test_a_100k_transaction_cost_moves_exactly_closing_and_t0() -> None:
    units = [_unit(unit_id, envelope, price) for unit_id, envelope, price in _mixed_units()]
    price = math.fsum(unit.purchase_price for unit in units)

    without = consolidate(units, transaction_price=price)
    with_cost = consolidate(units, transaction_price=price, transaction_costs=(cost("tc", 100_000.0),))

    assert with_cost.total_closing_uses - without.total_closing_uses == pytest.approx(100_000.0, abs=1e-6)
    assert with_cost.initial_equity - without.initial_equity == pytest.approx(100_000.0, abs=1e-6)
    assert without.unlevered_cash_flows[0] - with_cost.unlevered_cash_flows[0] == pytest.approx(100_000.0, abs=1e-6)
    assert without.levered_cash_flows[0] - with_cost.levered_cash_flows[0] == pytest.approx(100_000.0, abs=1e-6)
    assert with_cost.unlevered_cash_flows[1:] == without.unlevered_cash_flows[1:]
    assert with_cost.levered_cash_flows[1:] == without.levered_cash_flows[1:]
    for unchanged in ("loan_amount", "annual_debt_service", "noi_by_year", "exit_value", "allocated_purchase_price",
                      "acquisition_costs", "financing_fees", "closing_project_capital", "property_cash_flow_by_year"):
        assert getattr(with_cost, unchanged) == getattr(without, unchanged), unchanged


def test_cost_descriptions_and_categories_never_move_a_figure() -> None:
    units = [_unit("u", *_quick())]
    price = units[0].purchase_price
    one = consolidate(units, transaction_price=price, transaction_costs=(cost("a", 60_000.0), cost("b", 40_000.0)))
    other = consolidate(units, transaction_price=price, transaction_costs=(
        cost("b", 40_000.0, description="Other text", category=TransactionCostCategory.LEGAL),
        cost("a", 60_000.0, description="Renamed", category=TransactionCostCategory.DUE_DILIGENCE),
    ))
    assert dataclasses.astuple(one) == dataclasses.astuple(other)


def test_an_unsupported_cost_month_is_refused() -> None:
    units = [_unit("u", *_quick())]
    with pytest.raises(ConsolidationError):
        consolidate(units, transaction_price=units[0].purchase_price, transaction_costs=(cost("tc", 1.0, model_month=12),))


# =============================================================================
# PP-2 and PP-3 -- the transaction price is validation, never a cash flow
# =============================================================================


def test_the_transaction_price_never_reaches_a_cash_flow() -> None:
    (unit,) = [_unit("u", *_quick())]
    exact = consolidate([unit], transaction_price=unit.purchase_price)
    cent_over = consolidate([unit], transaction_price=unit.purchase_price + 0.01)

    assert _bits(cent_over.levered_cash_flows) == _bits(exact.levered_cash_flows)
    assert _bits(cent_over.unlevered_cash_flows) == _bits(exact.unlevered_cash_flows)
    assert cent_over.initial_equity == exact.initial_equity and cent_over.total_closing_uses == exact.total_closing_uses
    assert cent_over.allocated_purchase_price == unit.purchase_price
    assert cent_over.allocation_variance == pytest.approx(-0.01)


def test_an_unreconciled_allocation_is_refused_never_rescaled() -> None:
    (unit,) = [_unit("u", *_quick())]
    with pytest.raises(ConsolidationError, match="reconcile"):
        consolidate([unit], transaction_price=unit.purchase_price + 0.02)


def test_allocation_invariance_under_linear_unit_terms() -> None:
    """Hold the total price, move $3.0M of allocation from one Unit to the
    other: loan, costs, debt service, balance, exits and every consolidated cash
    flow are unchanged, because every Unit term here is linear in its price."""

    shared = {"ltv": 0.6, "interest_rate": 0.06, "amortization": 25, "io_period": 1, "acquisition_cost_pct": 0.015, "financing_fee_pct": 0.01}

    def pair(price_a: float, price_b: float) -> ConsolidatedResults:
        a, _ = _quick(purchase_price=price_a, current_noi=820_000.0, exit_cap_rate=0.07, **shared)
        b, _ = _quick(purchase_price=price_b, current_noi=560_000.0, exit_cap_rate=0.075, **shared)
        return consolidate([_unit("a", a, price_a), _unit("b", b, price_b)], transaction_price=price_a + price_b)

    first, second = pair(10_000_000.0, 6_000_000.0), pair(7_000_000.0, 9_000_000.0)

    for name in ("allocated_purchase_price", "loan_amount", "acquisition_costs", "financing_fees", "initial_equity",
                 "total_closing_uses", "remaining_loan_balance", "exit_value", "net_sale_proceeds", "total_equity_invested",
                 "total_profit", "levered_irr", "unlevered_irr", "equity_multiple", "going_in_cap_rate"):
        assert getattr(second, name) == pytest.approx(getattr(first, name), rel=1e-12), name
    for name in ("noi_by_year", "annual_debt_service", "levered_cash_flows", "unlevered_cash_flows", "aggregate_dscr_by_year"):
        assert getattr(second, name) == pytest.approx(getattr(first, name), rel=1e-12), name


# =============================================================================
# Q11 -- no partial weighted average
# =============================================================================


def test_occupancy_is_area_weighted_only_when_every_unit_has_an_area() -> None:
    lease_a, price_a = _envelope("lease_level")
    lease_b, price_b = _envelope("lease_level", purchase_price=30_000_000.0)
    units = [_unit("a", lease_a, price_a, area=True), _unit("b", lease_b, price_b, area=True)]
    both = consolidate(units, transaction_price=price_a + price_b)

    annual_a, annual_b = lease_a.annual_projection, lease_b.annual_projection
    expected = tuple(
        (oa + ob) / (oa + va + ob + vb)
        for oa, va, ob, vb in zip(annual_a.occupied_area_at_year_end, annual_a.vacant_area_at_year_end,
                                  annual_b.occupied_area_at_year_end, annual_b.vacant_area_at_year_end, strict=True)
    )
    assert both.physical_occupancy_at_year_end == pytest.approx(expected, rel=1e-12)
    assert both.physical_occupancy_reason is None


def test_a_quick_unit_makes_consolidated_occupancy_na_never_a_partial_average() -> None:
    lease, lease_price = _envelope("lease_level")
    quick, quick_price = _quick()
    mixed = consolidate([_unit("lease", lease, lease_price, area=True), _unit("quick", quick, quick_price)],
                        transaction_price=lease_price + quick_price)
    assert mixed.physical_occupancy_at_year_end is None
    assert mixed.physical_occupancy_reason is AreaMetricReason.UNIT_WITHOUT_AREA_MEASURE
    assert mixed.physical_occupancy_message is not None and "quick" in mixed.physical_occupancy_message


# =============================================================================
# Incoherent input is a programming error, never a finding
# =============================================================================


def test_incoherent_units_are_refused() -> None:
    quick, price = _quick()
    seven, seven_price = _quick(hold_period=7)
    with pytest.raises(ConsolidationError):
        consolidate([], transaction_price=1.0)
    with pytest.raises(ConsolidationError):
        consolidate([_unit("a", quick, price), _unit("a", quick, price)], transaction_price=2 * price)
    with pytest.raises(ConsolidationError, match="hold period"):
        consolidate([_unit("a", quick, price), _unit("b", seven, seven_price)], transaction_price=price + seven_price)
    assert not issubclass(ConsolidationError, ValueError)
