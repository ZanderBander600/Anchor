"""D6.3 baseline oracle runner (not a test module; see
``tests/test_d6_3_baseline_oracle.py``).

Usage: ``python _d6_3_oracle_cases.py <repo_root> <out.json>``

Runs against ``<repo_root>/src`` only, and asserts it did. Records, bit-exactly
(``float.hex``):

- ``calculate_irr`` and ``calculate_equity_multiple`` over a fixed corpus of
  every IRR branch plus 3,000 seeded random series (zeros, ``-0.0``, mixed
  signs and magnitudes) -- the same corpus on either side, proved by digest;
- ``evaluate_irr``'s status for the same corpus when the tree has it;
- every ``AcquisitionResults`` field for Quick, Detailed and Lease-Level under
  six Business Plans, including multiple-sign-change and final-year-deficit
  profiles.

It must run unchanged against b828956, so it names only what existed there,
and D6.3's ``evaluate_irr`` behind ``hasattr``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import random
import sys
from datetime import date
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2])
sys.path.insert(0, str(root / "src"))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from anchor.analysis import (  # noqa: E402
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.business_plan import (  # noqa: E402
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from anchor.contracts import (  # noqa: E402
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
)
from anchor.engine import returns  # noqa: E402
from anchor.leasing import (  # noqa: E402
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


def encode(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value if not isinstance(value, str) else str(value)
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, tuple):
        return [encode(item) for item in value]
    if dataclasses.is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    return repr(value)


# --- the IRR / equity multiple corpus ---------------------------------------

FIXED_SERIES = [
    (),
    (0.0,),
    (0.0, 0.0, 0.0),
    (-0.0, 0.0),
    (-0.0, -5.0, 6.0),
    (-100.0, 60.0, 60.0),
    (-100.0, 50.0, 50.0),
    (-100.0, 100.0),
    (-100.0, 150.0),
    (-100.0, 50.0),
    (-100.0, 10_000.0),
    (100.0, -60.0, -60.0),
    (100.0, 50.0, 20.0),
    (0.0, 100.0, -50.0, -60.0),
    (5.0, -3.0, 4.0),
    (-100.0, -50.0, -20.0),
    (-5.0, 0.0),
    (-100.0, 50.0, -20.0, 90.0),
    (-10.0, 0.6, -0.4, 10.6),
    (-10.0, 0.6, 0.6, 10.6),
    (-100.0, 0.0, 0.0, 60.0, 60.0),
    (0.0, -10.0, 30.0),
    (-1.0, 1e-11),
    (-1.0, 1e-13),
    (-1e12, 1.0),
    (-1e308, 1e308, 1e308),
    (-1_000_000.0, 137_000.0, 219_000.0, 301_000.0, 890_000.0),
    (-17500000.0, 346405.56164659606, 421405.56164659606, 498655.56164659606,
     578223.0616465961, 23405870.04998079),
]


def _random_series(rng: random.Random) -> tuple[float, ...]:
    series: list[float] = []
    for _ in range(rng.randint(1, 12)):
        draw = rng.random()
        if draw < 0.12:
            series.append(0.0)
        elif draw < 0.16:
            series.append(-0.0)
        else:
            magnitude = 10.0 ** rng.uniform(-3.0, 9.0)
            series.append(-magnitude if rng.random() < 0.35 else magnitude)
    if series and rng.random() < 0.7 and series[0] > 0.0:
        series[0] = -series[0]
    return tuple(series)


_rng = random.Random(63)
CORPUS = FIXED_SERIES + [_random_series(_rng) for _ in range(3000)]
corpus_digest = hashlib.sha256(json.dumps([encode(s) for s in CORPUS]).encode()).hexdigest()

has_status = hasattr(returns, "evaluate_irr")
corpus = {
    "digest": corpus_digest,
    "irr": [encode(returns.calculate_irr(s)) for s in CORPUS],
    "equity_multiple": [
        encode(returns.calculate_equity_multiple(levered_cash_flows=s)) for s in CORPUS
    ],
    "status": [str(returns.evaluate_irr(s)[1]) for s in CORPUS] if has_status else None,
}

# --- engine results under Business Plans ------------------------------------

QUICK = AcquisitionInputs(
    purchase_price=50_000_000.0, current_noi=2_500_000.0, occupancy=0.95, noi_growth=0.03,
    hold_period=5, exit_cap_rate=0.055, ltv=0.65, interest_rate=0.0525, amortization=30,
    acquisition_cost_pct=0.02, financing_fee_pct=0.01, disposition_cost_pct=0.015,
    annual_capex_reserve=120_000.0, io_period=1,
)
DETAILED_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0, hold_period=5, exit_cap_rate=0.065, ltv=0.60,
    interest_rate=0.05, amortization=30, acquisition_cost_pct=0.02, financing_fee_pct=0.01,
    disposition_cost_pct=0.025, annual_capex_reserve=50_000.0, io_period=2,
)
DETAILED_OPERATING = DetailedOperatingInputs(
    gross_potential_rent=800_000.0, other_income=20_000.0, vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0, insurance=20_000.0, utilities=25_000.0,
    repairs_maintenance=20_000.0, other_operating_expenses=16_000.0, management_fee_pct=0.05,
    revenue_growth=0.03, expense_growth=0.03,
)
LL_TERMS = AcquisitionTerms(
    purchase_price=6_000_000.0, hold_period=5, exit_cap_rate=0.065, ltv=0.5,
    interest_rate=0.055, amortization=30, acquisition_cost_pct=0.02, financing_fee_pct=0.01,
    disposition_cost_pct=0.02, annual_capex_reserve=50_000.0, io_period=0,
)
LL_PROPERTY = LeaseLevelPropertyInputs(analysis_start_date=date(2027, 1, 1), rentable_area_sf=20_000.0)
LL_OPERATING = LeaseLevelOperatingInputs(
    other_income=50_000.0, other_income_growth=0.02, credit_loss_pct=0.01,
    property_taxes=200_000.0, insurance=30_000.0, utilities=60_000.0,
    repairs_maintenance=40_000.0, other_operating_expenses=20_000.0, management_fee_pct=0.03,
    expense_growth=0.03, recoverable_expense_ratio=0.8,
)
LL_MARKET = MarketLeasingAssumptions(
    market_rent_psf=30.0, market_rent_growth=0.03, renewal_rent_psf=None,
    renewal_rent_spread=0.0, renewal_term_months=60, successor_escalation_pct=0.03,
    renewal_downtime_months=2.0, renewal_free_rent_months=1.0, new_term_months=60,
    new_downtime_months=6.0, new_free_rent_months=2.0, renewal_ti_psf=20.0, new_ti_psf=40.0,
    leasing_commission_method=LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
    renewal_lc_pct=0.03, new_lc_pct=0.06, renewal_probability=0.7,
    renewal_lease_type=LeaseType.NNN, renewal_recovery_basis=None,
    renewal_expense_stop_psf=None, new_lease_type=LeaseType.NNN, new_recovery_basis=None,
    new_expense_stop_psf=None,
)
LL_SUITES = (
    Suite(suite_id="100", suite_area_sf=12_000.0),
    Suite(
        suite_id="200",
        suite_area_sf=8_000.0,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP, initial_lease_up_months=6.0
        ),
    ),
)
LL_LEASES = (
    Lease(
        lease_id="L-100", suite_id="100", leased_area_sf=12_000.0,
        rent_commencement_date=date(2024, 1, 1), lease_expiration_date=date(2029, 6, 30),
        base_rent_psf=28.0, escalation_pct=0.03,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY, lease_type=LeaseType.NNN,
        tenant_name="Anchor Tenant",
    ),
)


def cap(month: int, amount: float) -> CapitalPlanItem:
    return CapitalPlanItem(
        item_id=f"c-{month}-{amount}", description="capital",
        category=CapitalItemCategory.VALUE_ADD_RENOVATION, month=month, amount=amount,
    )


def exp(amount: float, first: int, last: int | None = None) -> OwnerExpenseItem:
    return OwnerExpenseItem(
        item_id=f"e-{first}-{last}-{amount}", description="asset management",
        category=OwnerExpenseCategory.ASSET_MANAGEMENT, annual_amount=amount,
        first_year=first, last_year=last,
    )


def bp(*items: object) -> BusinessPlan:
    return BusinessPlan(
        capital_items=tuple(i for i in items if isinstance(i, CapitalPlanItem)),
        owner_expense_items=tuple(i for i in items if isinstance(i, OwnerExpenseItem)),
    )


PLANS = {
    "empty": bp(),
    "closing_only": bp(cap(0, 1_000_000.0)),
    "year_2_deficit": bp(cap(18, 2_500_000.0)),
    "owner_expense": bp(exp(150_000.0, 1)),
    "final_year_deficit": bp(cap(60, 30_000_000.0)),
    "everything": bp(
        cap(0, 500_000.0), cap(13, 1_000_000.0), cap(60, 750_000.0), cap(70, 2_000_000.0),
        exp(40_000.0, 1), exp(25_000.0, 2, 8),
    ),
}


def analyze(mode: str, business_plan: BusinessPlan) -> object:
    if mode == "quick":
        return analyze_quick_acquisition_with_business_plan(QUICK, business_plan=business_plan)
    if mode == "detailed":
        return analyze_detailed_acquisition_with_business_plan(
            DETAILED_TERMS, DETAILED_OPERATING, business_plan=business_plan
        ).results
    return analyze_lease_level_acquisition_with_business_plan(
        LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES,
        market_leasing=LL_MARKET, operating_inputs=LL_OPERATING, business_plan=business_plan,
    ).results


results = {
    f"{mode}/{name}": encode(analyze(mode, business_plan))
    for mode in ("quick", "detailed", "lease_level")
    for name, business_plan in PLANS.items()
}

out_path.write_text(
    json.dumps({"has_status": has_status, "corpus": corpus, "results": results}, sort_keys=True),
    encoding="utf-8",
)
