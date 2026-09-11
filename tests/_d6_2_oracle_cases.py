"""D6.2 neutral-input oracle runner (not a test module; see
``tests/test_d6_2_neutral_bit_oracle.py``).

Usage: ``python _d6_2_oracle_cases.py <repo_root> <out.json>``

Runs a fixed Quick / Detailed / Lease-Level case set against ``<repo_root>/src``
-- never against whatever ``anchor`` happens to be installed -- and writes every
``AcquisitionResults`` field, plus the Detailed and Lease-Level projections,
encoded bit-exactly with ``float.hex`` (so the last bit and the sign of zero are
visible). When the tree has the D6.2 Business Plan entry points, each case is
also run through them with ``BusinessPlan()`` and stored as ``<case>#bp``.

It must run unchanged against the pre-D6.2 engine, so it imports only names
that existed at 7e67cde, and the D6.2 ones behind ``ImportError``.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2])
sys.path.insert(0, str(root / "src"))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from anchor.analysis import analyze_lease_level_acquisition_with_projection  # noqa: E402
from anchor.contracts import (  # noqa: E402
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
)
from anchor.engine import (  # noqa: E402
    analyze_acquisition,
    analyze_detailed_acquisition_with_projection,
)
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

try:
    from anchor.analysis.business_plan_analysis import (  # noqa: E402
        analyze_detailed_acquisition_with_business_plan,
        analyze_lease_level_acquisition_with_business_plan,
        analyze_quick_acquisition_with_business_plan,
    )
    from anchor.business_plan import BusinessPlan  # noqa: E402

    HAS_BP = True
except ImportError:
    HAS_BP = False


def encode(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, tuple):
        return [encode(item) for item in value]
    if dataclasses.is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return repr(value)


def quick(**overrides: object) -> AcquisitionInputs:
    base: dict[str, object] = dict(
        purchase_price=50_000_000.0,
        current_noi=2_500_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=5,
        exit_cap_rate=0.055,
        ltv=0.65,
        interest_rate=0.0525,
        amortization=30,
        acquisition_cost_pct=0.0,
        financing_fee_pct=0.0,
        disposition_cost_pct=0.0,
        annual_capex_reserve=0.0,
        io_period=0,
    )
    base.update(overrides)
    return AcquisitionInputs(**base)  # type: ignore[arg-type]


def terms(**overrides: object) -> AcquisitionTerms:
    base: dict[str, object] = dict(
        purchase_price=10_000_000.0,
        hold_period=5,
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
    base.update(overrides)
    return AcquisitionTerms(**base)  # type: ignore[arg-type]


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
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.5,
    interest_rate=0.055,
    amortization=30,
    acquisition_cost_pct=0.0,
    financing_fee_pct=0.0,
    disposition_cost_pct=0.0,
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

QUICK_CASES = {
    "Q1_golden": quick(),
    "Q2_costs_capex_io": quick(
        purchase_price=10_000_000.0,
        current_noi=600_000.0,
        exit_cap_rate=0.065,
        ltv=0.60,
        interest_rate=0.05,
        acquisition_cost_pct=0.02,
        financing_fee_pct=0.01,
        disposition_cost_pct=0.025,
        annual_capex_reserve=50_000.0,
        io_period=2,
    ),
    "Q3_hold1_all_cash": quick(
        hold_period=1, ltv=0.0, acquisition_cost_pct=0.015, annual_capex_reserve=75_000.0
    ),
    "Q4_neg_growth_zero_rate_hold10": quick(
        hold_period=10,
        noi_growth=-0.02,
        interest_rate=0.0,
        amortization=25,
        ltv=0.8,
        financing_fee_pct=0.0125,
        disposition_cost_pct=0.02,
        annual_capex_reserve=333_333.33,
        io_period=1,
    ),
}
DETAILED_CASES = {
    "D1_costs_capex_io": (terms(), DETAILED_OPERATING),
    "D2_hold7_all_cash": (terms(hold_period=7, ltv=0.0, io_period=0), DETAILED_OPERATING),
}
LEASE_LEVEL_CASES = {
    "L1_rollover_and_lease_up": LL_TERMS,
    "L2_costs_io": dataclasses.replace(
        LL_TERMS,
        acquisition_cost_pct=0.02,
        financing_fee_pct=0.01,
        disposition_cost_pct=0.02,
        io_period=1,
    ),
    "L3_hold3_all_cash": dataclasses.replace(LL_TERMS, hold_period=3, ltv=0.0),
}

output: dict[str, object] = {"_has_bp": HAS_BP}

for case_id, inputs in QUICK_CASES.items():
    output[case_id] = {"results": encode(analyze_acquisition(inputs))}
    if HAS_BP:
        output[case_id + "#bp"] = {
            "results": encode(
                analyze_quick_acquisition_with_business_plan(inputs, business_plan=BusinessPlan())
            )
        }

for case_id, (case_terms, operating) in DETAILED_CASES.items():
    envelope = analyze_detailed_acquisition_with_projection(case_terms, operating)
    output[case_id] = {
        "results": encode(envelope.results),
        "operating_projection": encode(envelope.operating_projection),
    }
    if HAS_BP:
        bp = analyze_detailed_acquisition_with_business_plan(
            case_terms, operating, business_plan=BusinessPlan()
        )
        output[case_id + "#bp"] = {
            "results": encode(bp.results),
            "operating_projection": encode(bp.operating_projection),
        }

for case_id, case_terms in LEASE_LEVEL_CASES.items():
    envelope = analyze_lease_level_acquisition_with_projection(
        case_terms,
        LL_PROPERTY,
        LL_SUITES,
        LL_LEASES,
        market_leasing=LL_MARKET,
        operating_inputs=LL_OPERATING,
    )
    output[case_id] = {
        "results": encode(envelope.results),
        "annual_projection": encode(envelope.annual_projection),
    }
    if HAS_BP:
        bp = analyze_lease_level_acquisition_with_business_plan(
            case_terms,
            LL_PROPERTY,
            LL_SUITES,
            LL_LEASES,
            market_leasing=LL_MARKET,
            operating_inputs=LL_OPERATING,
            business_plan=BusinessPlan(),
        )
        output[case_id + "#bp"] = {
            "results": encode(bp.results),
            "annual_projection": encode(bp.annual_projection),
        }

out_path.write_text(json.dumps(output, sort_keys=True), encoding="utf-8")
