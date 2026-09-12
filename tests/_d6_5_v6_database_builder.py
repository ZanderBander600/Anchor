"""D6.5 schema-v6 database builder (not a test module; see
``tests/test_d6_5_business_plan_migration.py``).

Usage: ``python _d6_5_v6_database_builder.py <repo_root> <db_path> <out.json>``

Writes a genuine schema-v6 database with ``<repo_root>/src``'s own store -- the
pre-D6.5 tree, exported by ``git archive`` -- never a v7 database with its
version lowered. It holds a Quick, a Detailed and a Lease-Level deal, each with
every cached artifact its mode persisted at v6: analysis and AI snapshots for
Quick and Detailed; the AI report and the latest one-way and two-way
sensitivity runs for Lease-Level. A manifest records each deal's id, its inputs
and the financial and AI fingerprints the v6 tree computed for it.

The deals are the D6.2 engine fixtures, restated here so this script imports
nothing but the tree it is pointed at.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import sys
from datetime import date
from enum import Enum
from pathlib import Path

root = Path(sys.argv[1]).resolve()
db_path = Path(sys.argv[2])
out_path = Path(sys.argv[3])
sys.path.insert(0, str(root / "src"))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from anchor.ai.contracts import AIAnalysis, DealStory  # noqa: E402
from anchor.analysis import (  # noqa: E402
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
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
)
from anchor.contracts import (  # noqa: E402
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
)
from anchor.deals import store  # noqa: E402
from anchor.deals.fingerprint import (  # noqa: E402
    fingerprint_ai,
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)
from anchor.engine import (  # noqa: E402
    analyze_acquisition,
    analyze_detailed_acquisition_with_projection,
)

assert store._SCHEMA_VERSION == 6, f"expected the v6 tree, got {store._SCHEMA_VERSION}"

HOLD = 5
QUICK = AcquisitionInputs(
    purchase_price=50_000_000.0, current_noi=2_500_000.0, occupancy=0.95,
    noi_growth=0.03, hold_period=HOLD, exit_cap_rate=0.055, ltv=0.65,
    interest_rate=0.0525, amortization=30, acquisition_cost_pct=0.02,
    financing_fee_pct=0.01, disposition_cost_pct=0.015,
    annual_capex_reserve=120_000.0, io_period=1,
)
DETAILED_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0, hold_period=HOLD, exit_cap_rate=0.065, ltv=0.60,
    interest_rate=0.05, amortization=30, acquisition_cost_pct=0.02,
    financing_fee_pct=0.01, disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0, io_period=2,
)
DETAILED_OPERATING = DetailedOperatingInputs(
    gross_potential_rent=800_000.0, other_income=20_000.0,
    vacancy_credit_loss_pct=0.05, property_taxes=60_000.0, insurance=20_000.0,
    utilities=25_000.0, repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0, management_fee_pct=0.05,
    revenue_growth=0.03, expense_growth=0.03,
)
LL_TERMS = AcquisitionTerms(
    purchase_price=6_000_000.0, hold_period=HOLD, exit_cap_rate=0.065, ltv=0.5,
    interest_rate=0.055, amortization=30, acquisition_cost_pct=0.02,
    financing_fee_pct=0.01, disposition_cost_pct=0.02,
    annual_capex_reserve=50_000.0, io_period=0,
)
LL_PROPERTY = LeaseLevelPropertyInputs(
    analysis_start_date=date(2027, 1, 1), rentable_area_sf=20_000.0
)
LL_OPERATING = LeaseLevelOperatingInputs(
    other_income=50_000.0, other_income_growth=0.02, credit_loss_pct=0.01,
    property_taxes=200_000.0, insurance=30_000.0, utilities=60_000.0,
    repairs_maintenance=40_000.0, other_operating_expenses=20_000.0,
    management_fee_pct=0.03, expense_growth=0.03, recoverable_expense_ratio=0.8,
)
LL_MARKET = MarketLeasingAssumptions(
    market_rent_psf=30.0, market_rent_growth=0.03, renewal_rent_psf=None,
    renewal_rent_spread=0.0, renewal_term_months=60, successor_escalation_pct=0.03,
    renewal_downtime_months=2.0, renewal_free_rent_months=1.0, new_term_months=60,
    new_downtime_months=6.0, new_free_rent_months=2.0, renewal_ti_psf=20.0,
    new_ti_psf=40.0,
    leasing_commission_method=LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
    renewal_lc_pct=0.03, new_lc_pct=0.06, renewal_probability=0.7,
    renewal_lease_type=LeaseType.NNN, renewal_recovery_basis=None,
    renewal_expense_stop_psf=None, new_lease_type=LeaseType.NNN,
    new_recovery_basis=None, new_expense_stop_psf=None,
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
        lease_id="L-100", suite_id="100", leased_area_sf=12_000.0,
        rent_commencement_date=date(2024, 1, 1),
        lease_expiration_date=date(2029, 6, 30), base_rent_psf=28.0,
        escalation_pct=0.03, escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        lease_type=LeaseType.NNN, tenant_name="Anchor Tenant",
    ),
)
AI = AIAnalysis(
    executive_summary="A stabilised asset.",
    investment_view="Proceed, subject to diligence.",
    strengths=("Durable coverage.",),
    risks=("Exit cap sensitivity.",),
    return_drivers=("Exit cap rate.",),
    downside_analysis="Coverage holds.",
    capital_structure_analysis="Modest leverage.",
    break_even_analysis="Not supplied.",
    questions_to_investigate=("Confirm market rent.",),
    confidence_notes=("None.",),
    deal_story=DealStory(
        investment_view="Income-led.",
        key_strengths=("Coverage.",),
        key_risks=("Exit cap.",),
        model_gap=None,
    ),
)


def jsonable(value: object) -> object:
    def encode(item: object) -> object:
        if isinstance(item, date):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        raise TypeError(type(item).__name__)

    payload = (
        [dataclasses.asdict(element) for element in value]
        if isinstance(value, tuple)
        else dataclasses.asdict(value)
    )
    return json.loads(json.dumps(payload, default=encode))


manifest: dict[str, object] = {"deals": {}}

# -- Quick ---------------------------------------------------------------------
quick_context = "Legacy quick context"
quick = store.create_deal("Legacy Quick", QUICK, deal_context=quick_context, db_path=db_path)
quick_fp = fingerprint_quick_inputs(QUICK)
quick_ai_fp = fingerprint_ai(analysis_fingerprint=quick_fp, deal_context=quick_context)
store.update_analysis_snapshot(
    quick.id, dataclasses.asdict(analyze_acquisition(QUICK)),
    financial_input_fingerprint=quick_fp, db_path=db_path,
)
store.update_ai_snapshot(
    quick.id, dataclasses.asdict(AI), ai_context_fingerprint=quick_ai_fp, db_path=db_path
)
manifest["deals"]["quick"] = {  # type: ignore[index]
    "id": quick.id,
    "financial_fingerprint": quick_fp,
    "ai_fingerprint": quick_ai_fp,
    "inputs": {"inputs": jsonable(QUICK)},
}

# -- Detailed ------------------------------------------------------------------
detailed = store.create_detailed_deal(
    "Legacy Detailed", DETAILED_TERMS, DETAILED_OPERATING, db_path=db_path
)
detailed_fp = fingerprint_detailed_inputs(DETAILED_TERMS, DETAILED_OPERATING)
detailed_ai_fp = fingerprint_ai(analysis_fingerprint=detailed_fp, deal_context=None)
store.update_analysis_snapshot(
    detailed.id,
    dataclasses.asdict(
        analyze_detailed_acquisition_with_projection(DETAILED_TERMS, DETAILED_OPERATING)
    ),
    financial_input_fingerprint=detailed_fp,
    db_path=db_path,
)
store.update_ai_snapshot(
    detailed.id, dataclasses.asdict(AI), ai_context_fingerprint=detailed_ai_fp, db_path=db_path
)
manifest["deals"]["detailed"] = {  # type: ignore[index]
    "id": detailed.id,
    "financial_fingerprint": detailed_fp,
    "ai_fingerprint": detailed_ai_fp,
    "inputs": {
        "terms": jsonable(DETAILED_TERMS),
        "detailed_operating_inputs": jsonable(DETAILED_OPERATING),
    },
}

# -- Lease-Level ---------------------------------------------------------------
ll_context = "Legacy lease-level context"
lease_level = store.create_lease_level_deal(
    "Legacy Lease-Level", LL_TERMS, LL_PROPERTY, LL_OPERATING, LL_MARKET,
    LL_SUITES, LL_LEASES, deal_context=ll_context, db_path=db_path,
)
ll_fp = fingerprint_lease_level_inputs(
    LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES,
    market_leasing=LL_MARKET, operating_inputs=LL_OPERATING,
)
ll_ai_fp = fingerprint_ai(analysis_fingerprint=ll_fp, deal_context=ll_context)
store.update_ai_snapshot(
    lease_level.id, dataclasses.asdict(AI), ai_context_fingerprint=ll_ai_fp, db_path=db_path
)
ll_arguments = dict(market_leasing=LL_MARKET, operating_inputs=LL_OPERATING)
one_way = run_lease_level_one_way_sensitivity(
    LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES, **ll_arguments,
    assumption="exit_cap_rate", values=[0.06, 0.065, 0.07], metric="equity_multiple",
)
store.update_one_way_sensitivity_snapshot(
    lease_level.id,
    {
        "configuration": {
            "metric": "equity_multiple",
            "assumption": "exit_cap_rate",
            "values": ("6", "6.5", "7"),
        },
        "result": dataclasses.asdict(one_way),
    },
    financial_input_fingerprint=ll_fp,
    db_path=db_path,
)
two_way = run_lease_level_two_way_sensitivity(
    LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES, **ll_arguments,
    row_assumption="exit_cap_rate", row_values=[0.06, 0.07],
    column_assumption="interest_rate", column_values=[0.05, 0.06],
    metric="equity_multiple",
)
store.update_two_way_sensitivity_snapshot(
    lease_level.id,
    {
        "configuration": {
            "metric": "equity_multiple",
            "row_assumption": "exit_cap_rate",
            "row_values": ("6", "7"),
            "column_assumption": "interest_rate",
            "column_values": ("5", "6"),
        },
        "result": dataclasses.asdict(two_way),
    },
    financial_input_fingerprint=ll_fp,
    db_path=db_path,
)
manifest["deals"]["lease_level"] = {  # type: ignore[index]
    "id": lease_level.id,
    "financial_fingerprint": ll_fp,
    "ai_fingerprint": ll_ai_fp,
    "inputs": {
        "terms": jsonable(LL_TERMS),
        "property_inputs": jsonable(LL_PROPERTY),
        "operating_inputs": jsonable(LL_OPERATING),
        "market_leasing": jsonable(LL_MARKET),
        "suites": jsonable(LL_SUITES),
        "leases": jsonable(LL_LEASES),
    },
}

# Every artifact must decode as current in the tree that wrote it, or the
# migration test would be proving preservation of something already absent.
for name, entry in manifest["deals"].items():  # type: ignore[union-attr]
    deal = store.get_deal(entry["id"], db_path=db_path)
    assert deal.ai_snapshot is not None, name
    if name == "lease_level":
        assert deal.one_way_sensitivity_snapshot is not None
        assert deal.two_way_sensitivity_snapshot is not None
    else:
        assert deal.analysis_snapshot is not None, name

connection = sqlite3.connect(db_path)
manifest["user_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
connection.close()

out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
