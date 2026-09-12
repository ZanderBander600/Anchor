"""D6.8 empty-plan oracle runner (not a test module; see
``tests/test_d6_8_empty_plan_oracle.py``).

Usage: ``python _d6_8_oracle_cases.py <repo_root> <out.json>``

Runs against ``<repo_root>/src`` only, and asserts it did. For deals with no
Business Plan in all three modes it records the system prompt, the user prompt,
and every deterministic figure the AI context carries -- results, sensitivity
presets and break-even -- bit-exactly (``float.hex``).

It must run unchanged against 7f52b9e, where the Lease-Level builder takes no
``business_plan``; the plan is passed only where the signature accepts it.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import sys
from datetime import date
from enum import Enum
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2])
sys.path.insert(0, str(root / "src"))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from anchor.ai.analyst import (  # noqa: E402
    build_analysis_context,
    build_detailed_analysis_context,
    build_lease_level_analysis_context,
)
from anchor.ai.prompts import build_system_prompt, build_user_prompt  # noqa: E402
from anchor.analysis import (  # noqa: E402
    ParsedLeaseLevelInputs,
    ReturnHurdleMetric,
    analyze_lease_level_acquisition_with_business_plan,
)
from anchor.business_plan import BusinessPlan  # noqa: E402
from anchor.contracts import (  # noqa: E402
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
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


def encode(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, date):
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return {field.name: encode(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    raise TypeError(type(value).__name__)


HURDLES = dict(target_levered_irr=0.10, target_equity_multiple=1.50, target_headline_dscr=1.20)

GOLDEN = AcquisitionInputs(
    purchase_price=50_000_000.0, current_noi=2_500_000.0, occupancy=0.95, noi_growth=0.03,
    hold_period=5, exit_cap_rate=0.055, ltv=0.65, interest_rate=0.0525, amortization=30,
)
QUICK_V2 = AcquisitionInputs(
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
LL_INPUTS = ParsedLeaseLevelInputs(
    property_inputs=LeaseLevelPropertyInputs(
        analysis_start_date=date(2027, 1, 1), rentable_area_sf=20_000.0
    ),
    operating_inputs=LeaseLevelOperatingInputs(
        other_income=50_000.0, other_income_growth=0.02, credit_loss_pct=0.01,
        property_taxes=200_000.0, insurance=30_000.0, utilities=60_000.0,
        repairs_maintenance=40_000.0, other_operating_expenses=20_000.0, management_fee_pct=0.03,
        expense_growth=0.03, recoverable_expense_ratio=0.8,
    ),
    market_leasing=MarketLeasingAssumptions(
        market_rent_psf=30.0, market_rent_growth=0.03, renewal_rent_psf=None,
        renewal_rent_spread=0.0, renewal_term_months=60, successor_escalation_pct=0.03,
        renewal_downtime_months=2.0, renewal_free_rent_months=1.0, new_term_months=60,
        new_downtime_months=6.0, new_free_rent_months=2.0, renewal_ti_psf=20.0, new_ti_psf=40.0,
        leasing_commission_method=LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
        renewal_lc_pct=0.03, new_lc_pct=0.06, renewal_probability=0.7,
        renewal_lease_type=LeaseType.NNN, renewal_recovery_basis=None,
        renewal_expense_stop_psf=None, new_lease_type=LeaseType.NNN, new_recovery_basis=None,
        new_expense_stop_psf=None,
    ),
    suites=(
        Suite(suite_id="100", suite_area_sf=12_000.0),
        Suite(
            suite_id="200",
            suite_area_sf=8_000.0,
            initial_vacancy=InitialVacancyAssumptions(
                strategy=InitialVacancyStrategy.MARKET_LEASE_UP, initial_lease_up_months=6.0
            ),
        ),
    ),
    leases=(
        Lease(
            lease_id="L-100", suite_id="100", leased_area_sf=12_000.0,
            rent_commencement_date=date(2024, 1, 1), lease_expiration_date=date(2029, 6, 30),
            base_rent_psf=28.0, escalation_pct=0.03,
            escalation_basis=EscalationBasis.LEASE_ANNIVERSARY, lease_type=LeaseType.NNN,
            tenant_name="Anchor Tenant",
        ),
    ),
)


def lease_level_context(**extra: object):
    results = analyze_lease_level_acquisition_with_business_plan(
        LL_TERMS,
        LL_INPUTS.property_inputs,
        LL_INPUTS.suites,
        LL_INPUTS.leases,
        market_leasing=LL_INPUTS.market_leasing,
        operating_inputs=LL_INPUTS.operating_inputs,
        business_plan=BusinessPlan(),
    )
    plan = (
        {"business_plan": BusinessPlan()}
        if "business_plan" in inspect.signature(build_lease_level_analysis_context).parameters
        else {}
    )
    return build_lease_level_analysis_context(LL_TERMS, LL_INPUTS, results, **plan, **HURDLES, **extra)


CASES = {
    "quick-golden": lambda: build_analysis_context(GOLDEN, **HURDLES),
    "quick-v2-with-context": lambda: build_analysis_context(
        QUICK_V2,
        deal_context="Buy, stabilise and sell in year five.",
        return_hurdle_metric=ReturnHurdleMetric.EQUITY_MULTIPLE,
        **HURDLES,
    ),
    "detailed": lambda: build_detailed_analysis_context(DETAILED_TERMS, DETAILED_OPERATING, **HURDLES),
    "lease-level": lease_level_context,
    "lease-level-with-context": lambda: lease_level_context(deal_context="Lease up suite 200."),
}

recorded = {}
for name, build in CASES.items():
    context = build()
    recorded[name] = {
        "system_prompt": build_system_prompt(),
        "user_prompt": build_user_prompt(context),
        "results": encode(context.results),
        "sensitivities": encode(context.sensitivities),
        "break_even": encode(context.break_even),
    }

out_path.write_text(json.dumps(recorded, sort_keys=True), encoding="utf-8")
