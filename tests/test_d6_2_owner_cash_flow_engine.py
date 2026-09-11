"""Phase 6 Gate D6.2 -- the owner cash-flow engine bridge.

Governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 4-14,
19 and 20; that document governs on any discrepancy.

What fails silently if wrong, and is therefore asserted here:

- **An empty plan is the old engine.** ``BusinessPlan()`` reproduces every mode
  bit for bit (and ``tests/test_d6_2_neutral_bit_oracle.py`` proves it against
  the 7e67cde engine itself).
- **Capital is below NOI.** Project capital and owner expenses never move NOI,
  DSCR, debt yield, the loan, debt service, the loan balance, exit NOI, exit
  value, disposition costs or net sale proceeds (Section 12).
- **Each dollar is subtracted once, in its own timing bucket.** Closing capital
  only at ``T0``, hold-year items only in their year, post-hold capital nowhere
  but its disclosure field (Sections 4 and 19).
- **The three modes share one implementation.** The same plan moves each
  mode's owner economics by the same amounts relative to its own base
  (Section 13).
- **Existing metrics move through their inputs only.** IRR, equity multiple,
  cash-on-cash, cash yield and cumulative distributions keep their formulas and
  read the owner cash-flow series (Section 8).

The reference cases R1-R10 are the gate specification's.
"""

from __future__ import annotations

import dataclasses
import functools
import inspect
import json
from datetime import date

import pytest

from anchor.analysis import (
    LeaseValidationError,
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_projection,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.analysis import business_plan_analysis
from anchor.business_plan import (
    BusinessPlan,
    BusinessPlanValidationError,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
    resolve_business_plan,
)
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.engine.acquisition import (
    analyze_acquisition,
    analyze_acquisition_from_operating_projection,
    analyze_detailed_acquisition_with_projection,
    calculate_owner_capital_schedule,
    calculate_unlevered_cash_flows,
)
from anchor.engine.contracts import AcquisitionResults, OwnerCapitalSchedule
from anchor.engine.returns import (
    calculate_equity_multiple,
    calculate_irr,
    calculate_owner_return_metrics,
    calculate_recurring_levered_cash_flows,
    calculate_recurring_unlevered_cash_flows,
)
from anchor.leasing import (
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    Suite,
)

# =============================================================================
# Fixtures -- one deal per operating mode, all five-year holds
# =============================================================================

HOLD = 5

QUICK = AcquisitionInputs(
    purchase_price=50_000_000.0,
    current_noi=2_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=HOLD,
    exit_cap_rate=0.055,
    ltv=0.65,
    interest_rate=0.0525,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.015,
    annual_capex_reserve=120_000.0,
    io_period=1,
)

DETAILED_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
    hold_period=HOLD,
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
DETAILED_OPERATING = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)

LL_TERMS = AcquisitionTerms(
    purchase_price=6_000_000.0,
    hold_period=HOLD,
    exit_cap_rate=0.065,
    ltv=0.5,
    interest_rate=0.055,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.02,
    annual_capex_reserve=50_000.0,
    io_period=0,
)
LL_PROPERTY = LeaseLevelPropertyInputs(
    analysis_start_date=date(2027, 1, 1), rentable_area_sf=20_000.0
)
LL_OPERATING = LeaseLevelOperatingInputs(
    other_income=50_000.0,
    other_income_growth=0.02,
    credit_loss_pct=0.01,
    property_taxes=200_000.0,
    insurance=30_000.0,
    utilities=60_000.0,
    repairs_maintenance=40_000.0,
    other_operating_expenses=20_000.0,
    management_fee_pct=0.03,
    expense_growth=0.03,
    recoverable_expense_ratio=0.8,
)
LL_MARKET = MarketLeasingAssumptions(
    market_rent_psf=30.0,
    market_rent_growth=0.03,
    renewal_rent_psf=None,
    renewal_rent_spread=0.0,
    renewal_term_months=60,
    successor_escalation_pct=0.03,
    renewal_downtime_months=2.0,
    renewal_free_rent_months=1.0,
    new_term_months=60,
    new_downtime_months=6.0,
    new_free_rent_months=2.0,
    renewal_ti_psf=20.0,
    new_ti_psf=40.0,
    leasing_commission_method=LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
    renewal_lc_pct=0.03,
    new_lc_pct=0.06,
    renewal_probability=0.7,
    renewal_lease_type=LeaseType.NNN,
    renewal_recovery_basis=None,
    renewal_expense_stop_psf=None,
    new_lease_type=LeaseType.NNN,
    new_recovery_basis=None,
    new_expense_stop_psf=None,
)
# One lease that rolls mid-hold and one suite that leases up, so TI and LC are
# real, non-zero and in more than one year.
LL_SUITES = (
    Suite(suite_id="100", suite_area_sf=12_000.0),
    Suite(
        suite_id="200",
        suite_area_sf=8_000.0,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP,
            initial_lease_up_months=6.0,
        ),
    ),
)
LL_LEASES = (
    Lease(
        lease_id="L-100",
        suite_id="100",
        leased_area_sf=12_000.0,
        rent_commencement_date=date(2024, 1, 1),
        lease_expiration_date=date(2029, 6, 30),
        base_rent_psf=28.0,
        escalation_pct=0.03,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        lease_type=LeaseType.NNN,
        tenant_name="Anchor Tenant",
    ),
)

MODES = ("quick", "detailed", "lease_level")
PURCHASE_PRICE = {
    "quick": QUICK.purchase_price,
    "detailed": DETAILED_TERMS.purchase_price,
    "lease_level": LL_TERMS.purchase_price,
}
RESERVE = {
    "quick": QUICK.annual_capex_reserve,
    "detailed": DETAILED_TERMS.annual_capex_reserve,
    "lease_level": LL_TERMS.annual_capex_reserve,
}

#: The nine result fields D6.2 adds.
D6_2_FIELDS = (
    "closing_project_capital",
    "project_capital_by_year",
    "post_hold_project_capital",
    "owner_expenses_by_year",
    "property_cash_flow_by_year",
    "unlevered_owner_cash_flow_by_year",
    "levered_owner_cash_flow_by_year",
    "total_closing_uses",
    "total_closing_sources",
)

#: Everything a lender, an appraiser or the sale computes -- none of it may move
#: when only project capital or owner expenses move (Section 12). Property Cash
#: Flow is here too: it is above the owner layer.
LENDER_EXIT_AND_PROPERTY_FIELDS = (
    "noi_by_year",
    "exit_noi",
    "going_in_cap_rate",
    "loan_amount",
    "acquisition_costs",
    "financing_fee",
    "monthly_debt_service",
    "annual_debt_service",
    "remaining_loan_balance",
    "dscr_by_year",
    "headline_dscr",
    "min_dscr",
    "year_1_debt_yield",
    "exit_value",
    "disposition_costs",
    "net_sale_proceeds",
    "capex_by_year",
    "tenant_improvements_by_year",
    "leasing_commissions_by_year",
    "property_cash_flow_by_year",
)


# =============================================================================
# Helpers
# =============================================================================


def capital(month: int, amount: float, *, item_id: str | None = None) -> CapitalPlanItem:
    return CapitalPlanItem(
        item_id=item_id or f"capital-{month}-{amount}",
        description="Business plan capital",
        category=CapitalItemCategory.VALUE_ADD_RENOVATION,
        month=month,
        amount=amount,
    )


def expense(
    annual_amount: float,
    first_year: int,
    last_year: int | None = None,
    *,
    item_id: str | None = None,
) -> OwnerExpenseItem:
    return OwnerExpenseItem(
        item_id=item_id or f"expense-{first_year}-{last_year}-{annual_amount}",
        description="Asset management",
        category=OwnerExpenseCategory.ASSET_MANAGEMENT,
        annual_amount=annual_amount,
        first_year=first_year,
        last_year=last_year,
    )


def plan(*items: CapitalPlanItem | OwnerExpenseItem) -> BusinessPlan:
    return BusinessPlan(
        capital_items=tuple(i for i in items if isinstance(i, CapitalPlanItem)),
        owner_expense_items=tuple(i for i in items if isinstance(i, OwnerExpenseItem)),
    )


@functools.cache
def run(mode: str, business_plan: BusinessPlan | None = None) -> AcquisitionResults:
    """``business_plan=None`` runs the mode's own, plan-free entry point;
    anything else runs the D6.2 Business Plan entry point."""

    if business_plan is None:
        if mode == "quick":
            return analyze_acquisition(QUICK)
        if mode == "detailed":
            return analyze_detailed_acquisition_with_projection(
                DETAILED_TERMS, DETAILED_OPERATING
            ).results
        return analyze_lease_level_acquisition_with_projection(
            LL_TERMS,
            LL_PROPERTY,
            LL_SUITES,
            LL_LEASES,
            market_leasing=LL_MARKET,
            operating_inputs=LL_OPERATING,
        ).results

    if mode == "quick":
        return analyze_quick_acquisition_with_business_plan(
            QUICK, business_plan=business_plan
        )
    if mode == "detailed":
        return analyze_detailed_acquisition_with_business_plan(
            DETAILED_TERMS, DETAILED_OPERATING, business_plan=business_plan
        ).results
    return analyze_lease_level_acquisition_with_business_plan(
        LL_TERMS,
        LL_PROPERTY,
        LL_SUITES,
        LL_LEASES,
        market_leasing=LL_MARKET,
        operating_inputs=LL_OPERATING,
        business_plan=business_plan,
    ).results


def bits(value: object) -> object:
    """Bit-exact encoding: ``float.hex`` sees the last bit and the sign of
    zero, which ``==`` does not."""

    if isinstance(value, float):
        return value.hex()
    if isinstance(value, tuple):
        return tuple(bits(item) for item in value)
    return value


def field_bits(results: AcquisitionResults, *, exclude: frozenset[str] = frozenset()) -> dict:
    return {
        field.name: bits(getattr(results, field.name))
        for field in dataclasses.fields(results)
        if field.name not in exclude
    }


def assert_lender_exit_and_property_unchanged(
    results: AcquisitionResults, base: AcquisitionResults
) -> None:
    for name in LENDER_EXIT_AND_PROPERTY_FIELDS:
        assert bits(getattr(results, name)) == bits(getattr(base, name)), name


#: A plan with something in every timing bucket, used across several tests.
COMMON_PLAN = plan(capital(0, 250_000.0), capital(18, 300_000.0), expense(20_000.0, 1))


# =============================================================================
# R1 -- the empty plan is the old engine
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_r1_the_empty_plan_reproduces_the_mode_entry_point_bit_for_bit(mode: str) -> None:
    assert field_bits(run(mode, BusinessPlan())) == field_bits(run(mode))


@pytest.mark.parametrize("mode", MODES)
def test_r1_the_empty_plan_reports_neutral_owner_fields(mode: str) -> None:
    results = run(mode, BusinessPlan())

    assert results.closing_project_capital == 0.0
    assert results.post_hold_project_capital == 0.0
    assert results.project_capital_by_year == (0.0,) * HOLD
    assert results.owner_expenses_by_year == (0.0,) * HOLD
    # With nothing below Property Cash Flow, the owner series *are* it.
    assert bits(results.unlevered_owner_cash_flow_by_year) == bits(
        results.property_cash_flow_by_year
    )
    assert results.total_closing_uses == pytest.approx(
        results.total_closing_sources, rel=1e-12
    )


def test_r1_an_explicit_zero_schedule_is_the_absent_schedule() -> None:
    zero = OwnerCapitalSchedule(
        closing_project_capital=0.0,
        project_capital_by_year=(0.0,) * HOLD,
        owner_expenses_by_year=(0.0,) * HOLD,
        post_hold_project_capital=0.0,
    )

    assert field_bits(analyze_acquisition(QUICK, owner_capital=zero)) == field_bits(
        analyze_acquisition(QUICK)
    )


@pytest.mark.parametrize("mode", MODES)
def test_r1_legacy_fields_reuse_the_owner_chain_and_keep_their_d5_bits(mode: str) -> None:
    """The D6.2 mechanism (Section 25) by which legacy fields reuse the
    authoritative series: under an empty plan every one of them equals, to the
    bit, what the unchanged D5 helpers compute -- so the rewiring moved no
    number, and the owner chain *is* the D5 recurring series."""

    results = run(mode)
    operating_capital = tuple(
        ti + lc
        for ti, lc in zip(
            results.tenant_improvements_by_year, results.leasing_commissions_by_year
        )
    )

    legacy_owner_metrics = calculate_owner_return_metrics(
        noi_by_year=results.noi_by_year,
        capex_by_year=results.capex_by_year,
        annual_debt_service=results.annual_debt_service,
        purchase_price=PURCHASE_PRICE[mode],
        acquisition_costs=results.acquisition_costs,
        initial_equity=results.initial_equity,
        loan_amount=results.loan_amount,
        operating_capital_by_year=operating_capital,
    )
    for name in (
        "levered_cash_on_cash_by_year",
        "unlevered_cash_yield_by_year",
        "cumulative_operating_distributions_by_year",
        "year_1_debt_yield",
    ):
        assert bits(getattr(results, name)) == bits(getattr(legacy_owner_metrics, name)), name

    assert bits(results.unlevered_owner_cash_flow_by_year) == bits(
        calculate_recurring_unlevered_cash_flows(
            noi_by_year=results.noi_by_year,
            capex_by_year=results.capex_by_year,
            operating_capital_by_year=operating_capital,
        )
    )
    assert bits(results.levered_owner_cash_flow_by_year) == bits(
        calculate_recurring_levered_cash_flows(
            noi_by_year=results.noi_by_year,
            capex_by_year=results.capex_by_year,
            annual_debt_service=results.annual_debt_service,
            operating_capital_by_year=operating_capital,
        )
    )
    assert bits(results.unlevered_cash_flows) == bits(
        calculate_unlevered_cash_flows(
            purchase_price=PURCHASE_PRICE[mode],
            noi_by_year=results.noi_by_year,
            exit_value=results.exit_value,
            acquisition_costs=results.acquisition_costs,
            disposition_costs=results.disposition_costs,
            capex_by_year=results.capex_by_year,
            operating_capital_by_year=operating_capital,
        )
    )


# =============================================================================
# R2 -- $1M of future project capital in Year 2
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_r2_future_project_capital_reaches_owner_cash_flow_in_its_year_only(mode: str) -> None:
    amount = 1_000_000.0
    base, results = run(mode), run(mode, plan(capital(18, amount)))

    assert results.project_capital_by_year == (0.0, amount, 0.0, 0.0, 0.0)
    assert_lender_exit_and_property_unchanged(results, base)

    # Year 2 (index 1): owner cash flow falls by exactly the capital.
    assert (
        results.unlevered_owner_cash_flow_by_year[1]
        == base.unlevered_owner_cash_flow_by_year[1] - amount
    )
    assert (
        results.levered_owner_cash_flow_by_year[1]
        == results.unlevered_owner_cash_flow_by_year[1] - results.annual_debt_service[1]
    )
    assert results.levered_owner_cash_flow_by_year[1] == pytest.approx(
        base.levered_owner_cash_flow_by_year[1] - amount, abs=1e-6
    )
    assert results.unlevered_cash_flows[2] == base.unlevered_cash_flows[2] - amount
    assert results.levered_cash_flows[2] == base.levered_cash_flows[2] - amount

    # Every other year, and closing, is untouched to the bit.
    for year in (0, 2, 3, 4):
        assert bits(results.unlevered_owner_cash_flow_by_year[year]) == bits(
            base.unlevered_owner_cash_flow_by_year[year]
        )
        assert bits(results.levered_owner_cash_flow_by_year[year]) == bits(
            base.levered_owner_cash_flow_by_year[year]
        )
    for period in (0, 1, 3, 4, 5):
        assert bits(results.unlevered_cash_flows[period]) == bits(base.unlevered_cash_flows[period])
        assert bits(results.levered_cash_flows[period]) == bits(base.levered_cash_flows[period])
    assert bits(results.initial_equity) == bits(base.initial_equity)
    assert bits(results.total_closing_uses) == bits(base.total_closing_uses)
    assert results.closing_project_capital == 0.0


# =============================================================================
# R3 -- $1M of closing project capital
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_r3_closing_project_capital_is_equity_funded_at_t0(mode: str) -> None:
    amount = 1_000_000.0
    base, results = run(mode), run(mode, plan(capital(0, amount)))

    assert results.closing_project_capital == amount
    assert results.project_capital_by_year == (0.0,) * HOLD

    # Equity, not debt.
    assert results.initial_equity == base.initial_equity + amount
    assert bits(results.loan_amount) == bits(base.loan_amount)
    assert results.levered_cash_flows[0] == -results.initial_equity

    # The unlevered basis.
    assert results.unlevered_cash_flows[0] == base.unlevered_cash_flows[0] - amount
    assert results.unlevered_cash_flows[0] == -(
        (PURCHASE_PRICE[mode] + results.acquisition_costs) + amount
    )

    # Sources & Uses.
    assert results.total_closing_uses == base.total_closing_uses + amount
    assert results.total_closing_sources == results.loan_amount + results.initial_equity
    assert results.total_closing_sources == pytest.approx(
        results.total_closing_uses, rel=1e-12
    )

    # Nothing in the hold moves.
    assert_lender_exit_and_property_unchanged(results, base)
    for name in ("unlevered_owner_cash_flow_by_year", "levered_owner_cash_flow_by_year"):
        assert bits(getattr(results, name)) == bits(getattr(base, name)), name
    assert bits(results.unlevered_cash_flows[1:]) == bits(base.unlevered_cash_flows[1:])
    assert bits(results.levered_cash_flows[1:]) == bits(base.levered_cash_flows[1:])

    # The two annual yields re-base on the larger closing figures.
    basis = (PURCHASE_PRICE[mode] + results.acquisition_costs) + amount
    assert results.unlevered_cash_yield_by_year == tuple(
        flow / basis for flow in results.unlevered_owner_cash_flow_by_year
    )
    assert results.levered_cash_on_cash_by_year == tuple(
        flow / results.initial_equity for flow in results.levered_owner_cash_flow_by_year
    )


# =============================================================================
# R4 -- the recurring reserve and project capital stay separate
# =============================================================================


@pytest.mark.parametrize("mode", ["quick", "detailed"])
def test_r4_reserve_and_project_capital_appear_separately(mode: str) -> None:
    amount = 250_000.0
    base, results = run(mode), run(mode, plan(capital(30, amount)))

    assert results.capex_by_year == (RESERVE[mode],) * HOLD
    assert bits(results.capex_by_year) == bits(base.capex_by_year)
    assert results.project_capital_by_year == (0.0, 0.0, amount, 0.0, 0.0)

    for year in range(HOLD):
        assert results.property_cash_flow_by_year[year] == (
            results.noi_by_year[year]
            - results.capex_by_year[year]
            - (results.tenant_improvements_by_year[year] + results.leasing_commissions_by_year[year])
        )
    assert results.unlevered_owner_cash_flow_by_year[2] == (
        results.property_cash_flow_by_year[2] - amount
    )


# =============================================================================
# R5 -- Lease-Level TI/LC and project capital in the same year
# =============================================================================


def test_r5_lease_level_ti_lc_and_project_capital_are_each_subtracted_once() -> None:
    base = run("lease_level")
    year = next(
        index
        for index, (ti, lc) in enumerate(
            zip(base.tenant_improvements_by_year, base.leasing_commissions_by_year)
        )
        if ti > 0.0 and lc > 0.0
    )
    assert year + 1 < HOLD, "the fixture's leasing year must be a mid-hold year"
    project, owner = 150_000.0, 40_000.0
    results = run(
        "lease_level",
        plan(capital(12 * year + 7, project), expense(owner, year + 1, year + 1)),
    )

    # The leasing-capital authority and the reserve are untouched.
    assert bits(results.tenant_improvements_by_year) == bits(base.tenant_improvements_by_year)
    assert bits(results.leasing_commissions_by_year) == bits(base.leasing_commissions_by_year)
    assert bits(results.capex_by_year) == bits(base.capex_by_year)
    assert bits(results.property_cash_flow_by_year) == bits(base.property_cash_flow_by_year)

    # Property Cash Flow = NOI - Reserve - TI - LC ...
    assert results.property_cash_flow_by_year[year] == (
        results.noi_by_year[year]
        - results.capex_by_year[year]
        - (results.tenant_improvements_by_year[year] + results.leasing_commissions_by_year[year])
    )
    # ... and project capital and owner expenses come off it once each.
    assert results.unlevered_owner_cash_flow_by_year[year] == (
        results.property_cash_flow_by_year[year] - project - owner
    )
    assert results.unlevered_owner_cash_flow_by_year[year] == (
        base.unlevered_owner_cash_flow_by_year[year] - project - owner
    )
    assert results.levered_cash_flows[year + 1] == (
        base.levered_cash_flows[year + 1] - project - owner
    )
    assert sum(base.unlevered_cash_flows) - sum(results.unlevered_cash_flows) == pytest.approx(
        project + owner, abs=1e-6
    )
    assert_lender_exit_and_property_unchanged(results, base)


# =============================================================================
# R6 -- owner expenses alone
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_r6_owner_expenses_reduce_owner_cash_flow_and_returns_only(mode: str) -> None:
    amount = 25_000.0
    base, results = run(mode), run(mode, plan(expense(amount, 1)))

    assert results.owner_expenses_by_year == (amount,) * HOLD
    assert results.project_capital_by_year == (0.0,) * HOLD
    assert_lender_exit_and_property_unchanged(results, base)

    for year in range(HOLD):
        assert results.unlevered_owner_cash_flow_by_year[year] == (
            base.unlevered_owner_cash_flow_by_year[year] - amount
        )
    for period in range(1, HOLD):
        assert results.levered_cash_flows[period] == base.levered_cash_flows[period] - amount

    # Returns move, through their unchanged formulas.
    assert results.unlevered_irr is not None and base.unlevered_irr is not None
    assert results.unlevered_irr < base.unlevered_irr
    if results.levered_irr is not None and base.levered_irr is not None:
        assert results.levered_irr < base.levered_irr
    assert results.equity_multiple is not None and base.equity_multiple is not None
    assert results.equity_multiple < base.equity_multiple
    for year in range(HOLD):
        assert results.levered_cash_on_cash_by_year[year] < base.levered_cash_on_cash_by_year[year]
        assert results.unlevered_cash_yield_by_year[year] < base.unlevered_cash_yield_by_year[year]
    assert results.cumulative_operating_distributions_by_year[-1] == pytest.approx(
        base.cumulative_operating_distributions_by_year[-1] - HOLD * amount, abs=1e-6
    )


# =============================================================================
# R7 -- final-year capital and the sale
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_r7_final_year_capital_is_deducted_once_and_the_sale_added_separately(
    mode: str,
) -> None:
    amount = 400_000.0
    base, results = run(mode), run(mode, plan(capital(12 * HOLD, amount)))

    assert results.project_capital_by_year == (0.0, 0.0, 0.0, 0.0, amount)
    assert results.post_hold_project_capital == 0.0
    assert_lender_exit_and_property_unchanged(results, base)

    last = HOLD - 1
    assert results.unlevered_owner_cash_flow_by_year[last] == (
        base.unlevered_owner_cash_flow_by_year[last] - amount
    )
    assert results.unlevered_cash_flows[HOLD] == (
        results.unlevered_owner_cash_flow_by_year[last]
        + results.exit_value
        - results.disposition_costs
    )
    assert results.unlevered_cash_flows[HOLD] == pytest.approx(
        base.unlevered_cash_flows[HOLD] - amount, abs=1e-6
    )
    assert results.levered_cash_flows[HOLD] == pytest.approx(
        base.levered_cash_flows[HOLD] - amount, abs=1e-6
    )
    assert sum(base.unlevered_cash_flows) - sum(results.unlevered_cash_flows) == pytest.approx(
        amount, abs=1e-6
    )
    assert sum(base.levered_cash_flows) - sum(results.levered_cash_flows) == pytest.approx(
        amount, abs=1e-6
    )


# =============================================================================
# R8 -- post-hold capital is disclosure only
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_r8_post_hold_capital_moves_only_its_disclosure_field(mode: str) -> None:
    base = run(mode)
    # Month 61 is the first month after a five-year hold; month 240 is far past it.
    results = run(mode, plan(capital(12 * HOLD + 1, 2_000_000.0), capital(240, 500_000.0)))

    assert results.post_hold_project_capital == 2_500_000.0
    assert field_bits(results, exclude=frozenset({"post_hold_project_capital"})) == field_bits(
        base, exclude=frozenset({"post_hold_project_capital"})
    )


# =============================================================================
# R9 -- owner expenses partly or wholly outside the hold
# =============================================================================


@pytest.mark.parametrize("mode", ["quick", "lease_level"])
def test_r9_only_active_hold_years_of_an_owner_expense_have_effect(mode: str) -> None:
    partial = expense(50_000.0, 4, 8)
    outside = expense(1_000_000.0, 7, 9)

    partial_only = run(mode, plan(partial))
    with_outside = run(mode, plan(partial, outside))

    assert partial_only.owner_expenses_by_year == (0.0, 0.0, 0.0, 50_000.0, 50_000.0)
    assert field_bits(with_outside) == field_bits(partial_only)
    assert run(mode, plan(expense(10_000.0, 3))).owner_expenses_by_year == (
        0.0,
        0.0,
        10_000.0,
        10_000.0,
        10_000.0,
    )
    # There is no post-hold owner-expense dollar result (Section 5).
    assert not [
        field.name
        for field in dataclasses.fields(AcquisitionResults)
        if "expense" in field.name and "post_hold" in field.name
    ]


# =============================================================================
# R10 -- T0, hold and post-hold together, without leakage
# =============================================================================

HOLD_SERIES = (
    "project_capital_by_year",
    "owner_expenses_by_year",
    "property_cash_flow_by_year",
    "unlevered_owner_cash_flow_by_year",
    "levered_owner_cash_flow_by_year",
)
T0_FIELDS = (
    "closing_project_capital",
    "initial_equity",
    "total_closing_uses",
    "total_closing_sources",
)


@pytest.mark.parametrize("mode", ["quick", "lease_level"])
def test_r10_the_three_timing_buckets_do_not_leak_into_each_other(mode: str) -> None:
    closing = capital(0, 500_000.0)
    hold = capital(20, 1_000_000.0)
    post = capital(12 * HOLD + 3, 2_000_000.0)
    owner = expense(25_000.0, 1)

    everything = run(mode, plan(closing, hold, post, owner))
    no_post = run(mode, plan(closing, hold, owner))
    hold_only = run(mode, plan(hold, owner))
    closing_only = run(mode, plan(closing))

    # Post-hold: its disclosure and nothing else.
    assert everything.post_hold_project_capital == 2_000_000.0
    assert field_bits(everything, exclude=frozenset({"post_hold_project_capital"})) == field_bits(
        no_post, exclude=frozenset({"post_hold_project_capital"})
    )

    # Hold years do not see closing capital ...
    for name in HOLD_SERIES:
        assert bits(getattr(no_post, name)) == bits(getattr(hold_only, name)), name
    assert bits(no_post.unlevered_cash_flows[1:]) == bits(hold_only.unlevered_cash_flows[1:])
    assert bits(no_post.levered_cash_flows[1:]) == bits(hold_only.levered_cash_flows[1:])

    # ... and closing does not see hold-year items.
    for name in T0_FIELDS:
        assert bits(getattr(no_post, name)) == bits(getattr(closing_only, name)), name
    assert bits(no_post.unlevered_cash_flows[0]) == bits(closing_only.unlevered_cash_flows[0])
    assert bits(no_post.levered_cash_flows[0]) == bits(closing_only.levered_cash_flows[0])

    assert_lender_exit_and_property_unchanged(everything, run(mode))


# =============================================================================
# Part L -- lender and exit invariance under perturbation
# =============================================================================

PERTURBATIONS = {
    "project_capital_only": plan(capital(1, 800_000.0), capital(13, 1_200_000.0), capital(60, 900_000.0)),
    "owner_expenses_only": plan(expense(150_000.0, 1), expense(60_000.0, 2, 4)),
    "everything": plan(
        capital(0, 2_000_000.0),
        capital(13, 1_000_000.0),
        capital(60, 1_000_000.0),
        capital(75, 3_000_000.0),
        expense(100_000.0, 1),
    ),
}


@pytest.mark.parametrize("perturbation", sorted(PERTURBATIONS))
@pytest.mark.parametrize("mode", MODES)
def test_lender_exit_and_property_figures_never_move(mode: str, perturbation: str) -> None:
    base, results = run(mode), run(mode, PERTURBATIONS[perturbation])

    assert_lender_exit_and_property_unchanged(results, base)
    # The perturbation is real: owner economics did move.
    assert bits(results.unlevered_owner_cash_flow_by_year) != bits(
        base.unlevered_owner_cash_flow_by_year
    )
    assert bits(results.levered_cash_flows) != bits(base.levered_cash_flows)


# =============================================================================
# Part M -- three modes, one Business Plan treatment
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_same_plan_moves_every_mode_by_the_same_amounts(mode: str) -> None:
    base, results = run(mode), run(mode, COMMON_PLAN)
    closing, year_2, owner = 250_000.0, 300_000.0, 20_000.0
    expected_owner_delta = (-owner, -(year_2 + owner), -owner, -owner, -owner)

    assert results.closing_project_capital == closing
    assert results.project_capital_by_year == (0.0, year_2, 0.0, 0.0, 0.0)
    assert results.owner_expenses_by_year == (owner,) * HOLD

    assert results.initial_equity - base.initial_equity == pytest.approx(closing, abs=1e-6)
    assert results.total_closing_uses - base.total_closing_uses == pytest.approx(closing, abs=1e-6)
    assert results.unlevered_cash_flows[0] - base.unlevered_cash_flows[0] == pytest.approx(
        -closing, abs=1e-6
    )
    assert results.levered_cash_flows[0] - base.levered_cash_flows[0] == pytest.approx(
        -closing, abs=1e-6
    )
    for series in ("unlevered_owner_cash_flow_by_year", "levered_owner_cash_flow_by_year"):
        delta = tuple(
            new - old for new, old in zip(getattr(results, series), getattr(base, series))
        )
        assert delta == pytest.approx(expected_owner_delta, abs=1e-6), series
    for series in ("unlevered_cash_flows", "levered_cash_flows"):
        delta = tuple(
            new - old for new, old in zip(getattr(results, series)[1:], getattr(base, series)[1:])
        )
        assert delta == pytest.approx(expected_owner_delta, abs=1e-6), series
    assert_lender_exit_and_property_unchanged(results, base)


def test_the_modes_differ_in_noi_and_agree_on_the_resolved_schedule() -> None:
    results = {mode: run(mode, COMMON_PLAN) for mode in MODES}

    assert len({bits(result.noi_by_year) for result in results.values()}) == len(MODES)
    for name in (
        "closing_project_capital",
        "project_capital_by_year",
        "owner_expenses_by_year",
        "post_hold_project_capital",
    ):
        assert len({bits(getattr(result, name)) for result in results.values()}) == 1, name


# =============================================================================
# Sources & Uses 2.0
# =============================================================================


@pytest.mark.parametrize("plan_name", ["empty", "common", "everything"])
@pytest.mark.parametrize("mode", MODES)
def test_sources_equal_uses_and_future_capital_is_not_a_closing_use(
    mode: str, plan_name: str
) -> None:
    business_plan = {
        "empty": BusinessPlan(),
        "common": COMMON_PLAN,
        "everything": PERTURBATIONS["everything"],
    }[plan_name]
    results = run(mode, business_plan)

    assert results.total_closing_sources == pytest.approx(results.total_closing_uses, rel=1e-12)
    assert results.total_closing_uses == (
        PURCHASE_PRICE[mode]
        + results.acquisition_costs
        + results.financing_fee
        + results.closing_project_capital
    )

    # Only the month-0 items are closing uses.
    closing_only = run(
        mode, plan(*(item for item in business_plan.capital_items if item.month == 0))
    )
    assert bits(results.total_closing_uses) == bits(closing_only.total_closing_uses)
    assert bits(results.total_closing_sources) == bits(closing_only.total_closing_sources)


# =============================================================================
# Part I / J -- existing metrics consume the extended series, formulas unchanged
# =============================================================================


@pytest.mark.parametrize("plan_name", ["common", "everything"])
@pytest.mark.parametrize("mode", MODES)
def test_existing_metrics_read_the_owner_cash_flow_series(mode: str, plan_name: str) -> None:
    business_plan = COMMON_PLAN if plan_name == "common" else PERTURBATIONS["everything"]
    results = run(mode, business_plan)

    # IRR and equity multiple: the frozen formulas over the extended series.
    assert results.levered_irr == calculate_irr(results.levered_cash_flows)
    assert results.unlevered_irr == calculate_irr(results.unlevered_cash_flows)
    assert results.equity_multiple == calculate_equity_multiple(
        levered_cash_flows=results.levered_cash_flows
    )

    # Cash-on-cash: Levered Owner Cash Flow over the Initial Equity Requirement.
    assert results.levered_cash_on_cash_by_year == tuple(
        flow / results.initial_equity for flow in results.levered_owner_cash_flow_by_year
    )
    # Cash yield: Unlevered Owner Cash Flow over PP + acquisition costs + closing capital.
    basis = (PURCHASE_PRICE[mode] + results.acquisition_costs) + results.closing_project_capital
    assert results.unlevered_cash_yield_by_year == tuple(
        flow / basis for flow in results.unlevered_owner_cash_flow_by_year
    )
    # Cumulative operating distributions (legacy name): running Levered Owner Cash Flow.
    running, expected = 0.0, []
    for flow in results.levered_owner_cash_flow_by_year:
        running += flow
        expected.append(running)
    assert results.cumulative_operating_distributions_by_year == tuple(expected)
    # Debt yield is NOI over the loan -- never an owner series.
    assert results.year_1_debt_yield == results.noi_by_year[0] / results.loan_amount

    # The chain itself.
    for year in range(HOLD):
        assert results.levered_owner_cash_flow_by_year[year] == (
            results.unlevered_owner_cash_flow_by_year[year] - results.annual_debt_service[year]
        )
        assert results.unlevered_owner_cash_flow_by_year[year] == (
            results.property_cash_flow_by_year[year]
            - results.project_capital_by_year[year]
            - results.owner_expenses_by_year[year]
        )

    # The Unlevered Project Cash Flow is built from Unlevered Owner Cash Flow.
    assert results.unlevered_cash_flows[0] == -basis
    assert results.unlevered_cash_flows[1:HOLD] == results.unlevered_owner_cash_flow_by_year[:-1]
    assert results.unlevered_cash_flows[HOLD] == (
        results.unlevered_owner_cash_flow_by_year[-1]
        + results.exit_value
        - results.disposition_costs
    )

    # The Equity Cash Flow keeps its D5 grouping, so it agrees with the owner
    # chain within tolerance -- never bitwise (Section 6, "Arithmetic rules").
    assert results.levered_cash_flows[0] == -results.initial_equity
    for period in range(1, HOLD):
        assert results.levered_cash_flows[period] == pytest.approx(
            results.levered_owner_cash_flow_by_year[period - 1], rel=1e-12, abs=1e-6
        )
    assert results.levered_cash_flows[HOLD] == pytest.approx(
        results.levered_owner_cash_flow_by_year[-1] + results.net_sale_proceeds,
        rel=1e-12,
        abs=1e-6,
    )


# =============================================================================
# Resolution -- once, for the analysis's own hold
# =============================================================================


def test_each_entry_point_resolves_the_plan_once_for_its_own_hold(monkeypatch) -> None:
    calls: list[int] = []
    real = business_plan_analysis.resolve_business_plan

    def spy(business_plan: BusinessPlan, *, hold_period: int) -> OwnerCapitalSchedule:
        calls.append(hold_period)
        return real(business_plan, hold_period=hold_period)

    monkeypatch.setattr(business_plan_analysis, "resolve_business_plan", spy)

    analyze_quick_acquisition_with_business_plan(
        dataclasses.replace(QUICK, hold_period=7), business_plan=COMMON_PLAN
    )
    assert calls == [7]
    analyze_detailed_acquisition_with_business_plan(
        dataclasses.replace(DETAILED_TERMS, hold_period=6),
        DETAILED_OPERATING,
        business_plan=COMMON_PLAN,
    )
    assert calls == [7, 6]
    analyze_lease_level_acquisition_with_business_plan(
        dataclasses.replace(LL_TERMS, hold_period=3),
        LL_PROPERTY,
        LL_SUITES,
        LL_LEASES,
        market_leasing=LL_MARKET,
        operating_inputs=LL_OPERATING,
        business_plan=COMMON_PLAN,
    )
    assert calls == [7, 6, 3]


def test_a_hold_period_change_re_resolves_the_plan() -> None:
    business_plan = plan(expense(10_000.0, 2), capital(66, 100_000.0))

    five = analyze_quick_acquisition_with_business_plan(QUICK, business_plan=business_plan)
    seven = analyze_quick_acquisition_with_business_plan(
        dataclasses.replace(QUICK, hold_period=7), business_plan=business_plan
    )

    assert five.owner_expenses_by_year == (0.0,) + (10_000.0,) * 4
    assert seven.owner_expenses_by_year == (0.0,) + (10_000.0,) * 6
    # Month 66 is after a five-year hold but inside a seven-year one.
    assert five.post_hold_project_capital == 100_000.0
    assert seven.project_capital_by_year[5] == 100_000.0
    assert seven.post_hold_project_capital == 0.0


# =============================================================================
# Negative paths and the neutral default
# =============================================================================


def test_a_schedule_resolved_for_another_hold_is_refused() -> None:
    six_year = resolve_business_plan(plan(capital(18, 1.0)), hold_period=6)

    with pytest.raises(ValueError, match="5-year hold requires 5 annual figures"):
        analyze_acquisition(QUICK, owner_capital=six_year)


def test_an_invalid_plan_is_refused_before_any_analysis() -> None:
    duplicate_ids = BusinessPlan(
        capital_items=(capital(1, 1.0, item_id="same"),),
        owner_expense_items=(expense(1.0, 1, item_id="same"),),
    )

    for mode in MODES:
        with pytest.raises(BusinessPlanValidationError):
            run.__wrapped__(mode, duplicate_ids)


def test_a_lease_level_plan_error_surfaces_before_a_rent_roll_error() -> None:
    bad_rent_roll = LL_LEASES + LL_LEASES  # the same lease twice

    with pytest.raises(LeaseValidationError):
        analyze_lease_level_acquisition_with_business_plan(
            LL_TERMS,
            LL_PROPERTY,
            LL_SUITES,
            bad_rent_roll,
            market_leasing=LL_MARKET,
            operating_inputs=LL_OPERATING,
            business_plan=BusinessPlan(),
        )
    with pytest.raises(BusinessPlanValidationError):
        analyze_lease_level_acquisition_with_business_plan(
            LL_TERMS,
            LL_PROPERTY,
            LL_SUITES,
            bad_rent_roll,
            market_leasing=LL_MARKET,
            operating_inputs=LL_OPERATING,
            business_plan=plan(capital(1, -5.0)),
        )


def test_the_neutral_default_is_immutable_and_rebuilt_for_each_hold() -> None:
    three = calculate_owner_capital_schedule(owner_capital=None, hold_period=3)
    seven = calculate_owner_capital_schedule(owner_capital=None, hold_period=7)

    assert three.project_capital_by_year == (0.0,) * 3
    assert seven.owner_expenses_by_year == (0.0,) * 7
    with pytest.raises(dataclasses.FrozenInstanceError):
        three.closing_project_capital = 1.0  # type: ignore[misc]

    for function in (
        analyze_acquisition,
        analyze_acquisition_from_operating_projection,
        analyze_detailed_acquisition_with_projection,
        analyze_lease_level_acquisition_with_projection,
    ):
        parameter = inspect.signature(function).parameters["owner_capital"]
        assert parameter.default is None, function.__name__
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, function.__name__


# =============================================================================
# Part O -- snapshots: an old result decodes as absent, never fabricated
# =============================================================================


def _json_dict(value: object) -> dict:
    return json.loads(json.dumps(dataclasses.asdict(value)))


def test_a_pre_d6_2_analysis_snapshot_decodes_as_absent_never_with_zeros() -> None:
    from anchor.deals.store import (
        _ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
        SnapshotValidationError,
        _dataclass_from_json,
        _decode_snapshot,
        _detailed_analysis_snapshot_from_dict,
        _quick_analysis_snapshot_from_dict,
    )

    def decode(raw: dict, decoder) -> object:
        return _decode_snapshot(
            raw_json=json.dumps(raw),
            stored_schema_version=_ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
            current_schema_version=_ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
            stored_fingerprint="unchanged-assumptions",
            expected_fingerprint="unchanged-assumptions",
            decoder=decoder,
        )

    quick = _json_dict(run("quick"))
    legacy_quick = {name: value for name, value in quick.items() if name not in D6_2_FIELDS}
    assert decode(legacy_quick, _quick_analysis_snapshot_from_dict) is None
    with pytest.raises(SnapshotValidationError, match="Missing field"):
        _dataclass_from_json(AcquisitionResults, legacy_quick)
    assert decode(quick, _quick_analysis_snapshot_from_dict) == run("quick")

    envelope = analyze_detailed_acquisition_with_projection(DETAILED_TERMS, DETAILED_OPERATING)
    detailed = _json_dict(envelope)
    legacy_detailed = {
        **detailed,
        "results": {
            name: value for name, value in detailed["results"].items() if name not in D6_2_FIELDS
        },
    }
    assert decode(legacy_detailed, _detailed_analysis_snapshot_from_dict) is None
    assert decode(detailed, _detailed_analysis_snapshot_from_dict) == envelope


def test_no_d6_2_result_field_has_a_default_so_none_can_be_fabricated() -> None:
    from anchor.deals.store import _ANALYSIS_SNAPSHOT_SCHEMA_VERSION

    for field in dataclasses.fields(AcquisitionResults):
        if field.name in D6_2_FIELDS:
            assert field.default is dataclasses.MISSING, field.name
            assert field.default_factory is dataclasses.MISSING, field.name

    # D6.2 deliberately does not bump the snapshot schema: the strict decoder
    # above already treats the old shape as absent. D6.5 owns schema changes.
    assert _ANALYSIS_SNAPSHOT_SCHEMA_VERSION == 1


# =============================================================================
# Part P -- the new fields do not reach the AI Analyst before D6.8
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_owner_cash_flow_fields_do_not_reach_the_ai_analyst(mode: str) -> None:
    from anchor.ai.presentation import INTENTIONALLY_EXCLUDED_RESULT_FIELDS, _format_results

    formatted = _format_results(run(mode, COMMON_PLAN))

    assert not set(formatted) & set(D6_2_FIELDS)
    assert (
        {field.name for field in dataclasses.fields(AcquisitionResults)} - set(formatted)
        == INTENTIONALLY_EXCLUDED_RESULT_FIELDS
        == frozenset(D6_2_FIELDS)
    )
