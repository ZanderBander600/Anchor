"""Shared P7.1 scenario fixtures (not a test module).

Raw, ordinary Quick / Detailed / Lease-Level inputs built from literals only,
plus a small non-empty Business Plan. Every P7.1 test starts from these, and
every "manual entry" oracle rebuilds the same contracts by hand with the
resolved assumption typed in directly, so a scenario result is always measured
against an independent ordinary analysis rather than against itself.

Imports only names that existed at ``f234e4c``, so the P7.1 neutral oracle
runner can build the same cases against that baseline tree.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
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

ANALYSIS_START = date(2027, 1, 1)
RENTABLE_AREA = 100_000.0


# =============================================================================
# Quick
# =============================================================================


def quick_inputs(**overrides: Any) -> AcquisitionInputs:
    base: dict[str, Any] = {
        "purchase_price": 12_500_000.0,
        "current_noi": 800_000.0,
        "occupancy": 0.94,
        "noi_growth": 0.03,
        "hold_period": 5,
        "exit_cap_rate": 0.0625,
        "ltv": 0.65,
        "interest_rate": 0.0575,
        "amortization": 30,
        "acquisition_cost_pct": 0.02,
        "financing_fee_pct": 0.01,
        "disposition_cost_pct": 0.02,
        "annual_capex_reserve": 40_000.0,
        "io_period": 2,
    }
    base.update(overrides)
    return AcquisitionInputs(**base)


# =============================================================================
# Detailed
# =============================================================================


def detailed_terms(**overrides: Any) -> AcquisitionTerms:
    base: dict[str, Any] = {
        "purchase_price": 18_000_000.0,
        "hold_period": 7,
        "exit_cap_rate": 0.065,
        "ltv": 0.62,
        "interest_rate": 0.06,
        "amortization": 30,
        "acquisition_cost_pct": 0.015,
        "financing_fee_pct": 0.01,
        "disposition_cost_pct": 0.02,
        "annual_capex_reserve": 60_000.0,
        "io_period": 1,
    }
    base.update(overrides)
    return AcquisitionTerms(**base)


def detailed_operating(**overrides: Any) -> DetailedOperatingInputs:
    base: dict[str, Any] = {
        "gross_potential_rent": 2_100_000.0,
        "other_income": 90_000.0,
        "vacancy_credit_loss_pct": 0.06,
        "property_taxes": 210_000.0,
        "insurance": 55_000.0,
        "utilities": 80_000.0,
        "repairs_maintenance": 70_000.0,
        "other_operating_expenses": 40_000.0,
        "management_fee_pct": 0.03,
        "revenue_growth": 0.03,
        "expense_growth": 0.025,
    }
    base.update(overrides)
    return DetailedOperatingInputs(**base)


# =============================================================================
# Lease-Level
# =============================================================================


def lease_level_terms(**overrides: Any) -> AcquisitionTerms:
    base: dict[str, Any] = {
        "purchase_price": 40_000_000.0,
        "hold_period": 5,
        "exit_cap_rate": 0.065,
        "ltv": 0.60,
        "interest_rate": 0.055,
        "amortization": 30,
        "acquisition_cost_pct": 0.02,
        "financing_fee_pct": 0.01,
        "disposition_cost_pct": 0.015,
        "annual_capex_reserve": 50_000.0,
        "io_period": 0,
    }
    base.update(overrides)
    return AcquisitionTerms(**base)


def lease_level_property() -> LeaseLevelPropertyInputs:
    return LeaseLevelPropertyInputs(
        analysis_start_date=ANALYSIS_START, rentable_area_sf=RENTABLE_AREA
    )


def market(**overrides: Any) -> MarketLeasingAssumptions:
    """Differentiated renewal and new-tenant branches (downtime, free rent, TI
    and LC differ), so renewal probability and market rent both reach the
    economics rather than being inert."""

    base: dict[str, Any] = {
        "market_rent_psf": 36.0,
        "market_rent_growth": 0.03,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.02,
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 0.0,
        "new_term_months": 60,
        "new_downtime_months": 6.0,
        "new_free_rent_months": 3.0,
        "renewal_ti_psf": 5.0,
        "new_ti_psf": 40.0,
        "leasing_commission_method": LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
        "renewal_lc_pct": 0.02,
        "new_lc_pct": 0.06,
        "renewal_probability": 0.65,
        "renewal_lease_type": LeaseType.NNN,
        "renewal_recovery_basis": None,
        "renewal_expense_stop_psf": None,
        "new_lease_type": LeaseType.NNN,
        "new_recovery_basis": None,
        "new_expense_stop_psf": None,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)


def lease_level_operating(**overrides: Any) -> LeaseLevelOperatingInputs:
    base: dict[str, Any] = {
        "other_income": 150_000.0,
        "other_income_growth": 0.03,
        "credit_loss_pct": 0.0,
        "property_taxes": 600_000.0,
        "insurance": 120_000.0,
        "utilities": 240_000.0,
        "repairs_maintenance": 180_000.0,
        "other_operating_expenses": 60_000.0,
        "management_fee_pct": 0.03,
        "expense_growth": 0.03,
        "recoverable_expense_ratio": 0.9,
    }
    base.update(overrides)
    return LeaseLevelOperatingInputs(**base)


def in_place_lease(
    suite: Suite, *, expires: date, base_rent_psf: float, start: date = date(2024, 1, 1)
) -> Lease:
    return Lease(
        lease_id=f"L-{suite.suite_id}",
        suite_id=suite.suite_id,
        leased_area_sf=suite.suite_area_sf,
        rent_commencement_date=start,
        lease_expiration_date=expires,
        base_rent_psf=base_rent_psf,
        escalation_pct=0.02,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        lease_type=LeaseType.NNN,
    )


def rent_roll(
    *,
    b_market_rent_psf: float | None = 42.0,
    c_override: MarketLeasingAssumptions | None = None,
    d_market_rent_psf: float | None = None,
    d_override: MarketLeasingAssumptions | None = None,
) -> tuple[list[Suite], list[Lease]]:
    """Four suites summing to the rentable area. By default:

    - A takes the property default and rolls over inside the hold;
    - B carries a scalar ``market_rent_psf`` override and rolls over too;
    - C takes the property default and runs past the hold;
    - D is vacant at the start and leases up at market after nine months.

    ``c_override`` / ``d_override`` add full ``market_leasing_override``
    records; ``d_market_rent_psf`` adds a scalar rent on D as well."""

    a = Suite(suite_id="A", suite_area_sf=40_000.0)
    b = Suite(suite_id="B", suite_area_sf=30_000.0, market_rent_psf=b_market_rent_psf)
    c = Suite(suite_id="C", suite_area_sf=20_000.0, market_leasing_override=c_override)
    d = Suite(
        suite_id="D",
        suite_area_sf=10_000.0,
        market_rent_psf=d_market_rent_psf,
        market_leasing_override=d_override,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP, initial_lease_up_months=9.0
        ),
    )
    leases = [
        in_place_lease(a, expires=date(2028, 6, 30), base_rent_psf=32.0),
        in_place_lease(b, expires=date(2029, 12, 31), base_rent_psf=38.0),
        in_place_lease(c, expires=date(2033, 12, 31), base_rent_psf=34.0),
    ]
    return [a, b, c, d], leases


# =============================================================================
# Business Plan
# =============================================================================


def business_plan() -> BusinessPlan:
    """A small non-empty plan: closing and in-hold project capital plus an
    open-ended owner expense."""

    return BusinessPlan(
        capital_items=(
            CapitalPlanItem(
                item_id="cap-roof",
                description="Roof replacement",
                category=CapitalItemCategory.BUILDING_SYSTEMS,
                month=0,
                amount=250_000.0,
            ),
            CapitalPlanItem(
                item_id="cap-lobby",
                description="Lobby refresh",
                category=CapitalItemCategory.VALUE_ADD_RENOVATION,
                month=14,
                amount=400_000.0,
            ),
        ),
        owner_expense_items=(
            OwnerExpenseItem(
                item_id="ox-asset-management",
                description="Asset management",
                category=OwnerExpenseCategory.ASSET_MANAGEMENT,
                annual_amount=50_000.0,
                first_year=1,
                last_year=None,
            ),
        ),
    )
