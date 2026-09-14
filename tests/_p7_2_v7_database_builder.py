"""P7.2 schema-v7 database builder (not a test module; see
``tests/test_p7_2_compatibility_oracle.py``).

Usage: ``python _p7_2_v7_database_builder.py <repo_root> <db_path> <out.json>``

Writes a genuine schema-v7 database with ``<repo_root>/src``'s own store -- the
pre-P7.2 tree ``58f862d``, exported by ``git archive`` -- never a v8 database
with its version lowered. It holds one Deal per operating mode, each with every
artifact its mode persists at v7: a Business Plan (Quick and Lease-Level), Deal
Context, analysis snapshots (Quick and Detailed), AI snapshots and a Lease-Level
sensitivity snapshot.

It then records, through that same tree's own HTTP app, every legacy-visible
exchange for those Deals -- the Deal Library, each Deal, each Deal's
fingerprints and each Deal's ``/analyze`` -- so the P7.2 tree can be required to
return exactly the same responses over the migrated database.

The Deals are literals restated here, so this script imports nothing but the
tree it is pointed at.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

root = Path(sys.argv[1]).resolve()
db_path = Path(sys.argv[2])
out_path = Path(sys.argv[3])
sys.path.insert(0, str(root / "src"))
os.environ["ANCHOR_DB_PATH"] = str(db_path)

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from fastapi.testclient import TestClient  # noqa: E402

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
    analyze_detailed_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
    run_lease_level_one_way_sensitivity,
)
from anchor.business_plan import (  # noqa: E402
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs  # noqa: E402
from anchor.deals import store  # noqa: E402
from anchor.deals.fingerprint import (  # noqa: E402
    fingerprint_ai,
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)

assert store._SCHEMA_VERSION == 7, f"expected the v7 tree, got {store._SCHEMA_VERSION}"

PLAN = BusinessPlan(
    capital_items=(
        CapitalPlanItem(
            item_id="cap-2", description="Roof", category=CapitalItemCategory.BUILDING_SYSTEMS,
            month=15, amount=400_000.0,
        ),
        CapitalPlanItem(
            item_id="cap-1", description="Lobby", category=CapitalItemCategory.VALUE_ADD_RENOVATION,
            month=0, amount=250_000.0,
        ),
    ),
    owner_expense_items=(
        OwnerExpenseItem(
            item_id="ox-1", description="Asset management", category=OwnerExpenseCategory.ASSET_MANAGEMENT,
            annual_amount=50_000.0, first_year=1, last_year=None,
        ),
    ),
)
QUICK = AcquisitionInputs(
    purchase_price=12_500_000.0, current_noi=800_000.0, occupancy=0.94, noi_growth=0.03,
    hold_period=5, exit_cap_rate=0.0625, ltv=0.65, interest_rate=0.0575, amortization=30,
    acquisition_cost_pct=0.02, financing_fee_pct=0.01, disposition_cost_pct=0.02,
    annual_capex_reserve=40_000.0, io_period=2,
)
DETAILED_TERMS = AcquisitionTerms(
    purchase_price=18_000_000.0, hold_period=7, exit_cap_rate=0.065, ltv=0.62,
    interest_rate=0.06, amortization=30, acquisition_cost_pct=0.015, financing_fee_pct=0.01,
    disposition_cost_pct=0.02, annual_capex_reserve=60_000.0, io_period=1,
)
DETAILED_OPERATING = DetailedOperatingInputs(
    gross_potential_rent=2_100_000.0, other_income=90_000.0, vacancy_credit_loss_pct=0.06,
    property_taxes=210_000.0, insurance=55_000.0, utilities=80_000.0,
    repairs_maintenance=70_000.0, other_operating_expenses=40_000.0,
    management_fee_pct=0.03, revenue_growth=0.03, expense_growth=0.025,
)
LL_TERMS = AcquisitionTerms(
    purchase_price=40_000_000.0, hold_period=5, exit_cap_rate=0.065, ltv=0.60,
    interest_rate=0.055, amortization=30, acquisition_cost_pct=0.02, financing_fee_pct=0.01,
    disposition_cost_pct=0.015, annual_capex_reserve=50_000.0, io_period=0,
)
LL_PROPERTY = LeaseLevelPropertyInputs(analysis_start_date=date(2027, 1, 1), rentable_area_sf=100_000.0)
LL_OPERATING = LeaseLevelOperatingInputs(
    other_income=150_000.0, other_income_growth=0.03, credit_loss_pct=0.0,
    property_taxes=600_000.0, insurance=120_000.0, utilities=240_000.0,
    repairs_maintenance=180_000.0, other_operating_expenses=60_000.0,
    management_fee_pct=0.03, expense_growth=0.03, recoverable_expense_ratio=0.9,
)
LL_MARKET = MarketLeasingAssumptions(
    market_rent_psf=36.0, market_rent_growth=0.03, renewal_rent_psf=None, renewal_rent_spread=0.0,
    renewal_term_months=60, successor_escalation_pct=0.02, renewal_downtime_months=0.0,
    renewal_free_rent_months=0.0, new_term_months=60, new_downtime_months=6.0,
    new_free_rent_months=3.0, renewal_ti_psf=5.0, new_ti_psf=40.0,
    leasing_commission_method=LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
    renewal_lc_pct=0.02, new_lc_pct=0.06, renewal_probability=0.65,
    renewal_lease_type=LeaseType.NNN, renewal_recovery_basis=None, renewal_expense_stop_psf=None,
    new_lease_type=LeaseType.NNN, new_recovery_basis=None, new_expense_stop_psf=None,
)
LL_SUITES = (
    Suite(suite_id="A", suite_area_sf=40_000.0),
    Suite(suite_id="B", suite_area_sf=30_000.0, market_rent_psf=42.0),
    Suite(suite_id="C", suite_area_sf=20_000.0),
    Suite(
        suite_id="D", suite_area_sf=10_000.0,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP, initial_lease_up_months=9.0
        ),
    ),
)


def _lease(suite: Suite, expires: date, rent: float) -> Lease:
    return Lease(
        lease_id=f"L-{suite.suite_id}", suite_id=suite.suite_id, leased_area_sf=suite.suite_area_sf,
        rent_commencement_date=date(2024, 1, 1), lease_expiration_date=expires, base_rent_psf=rent,
        escalation_pct=0.02, escalation_basis=EscalationBasis.LEASE_ANNIVERSARY, lease_type=LeaseType.NNN,
    )


LL_LEASES = (
    _lease(LL_SUITES[0], date(2028, 6, 30), 32.0),
    _lease(LL_SUITES[1], date(2029, 12, 31), 38.0),
    _lease(LL_SUITES[2], date(2033, 12, 31), 34.0),
)
AI = AIAnalysis(
    executive_summary="A stabilised asset.", investment_view="Proceed, subject to diligence.",
    strengths=("Durable coverage.",), risks=("Exit cap sensitivity.",),
    return_drivers=("Exit cap rate.",), downside_analysis="Coverage holds.",
    capital_structure_analysis="Modest leverage.", break_even_analysis="Not supplied.",
    questions_to_investigate=("Confirm market rent.",), confidence_notes=("None.",),
    deal_story=DealStory(
        investment_view="Income-led.", key_strengths=("Coverage.",), key_risks=("Exit cap.",), model_gap=None,
    ),
)

manifest: dict[str, object] = {"deals": {}}

# -- Quick: material plan, Deal Context, analysis and AI snapshots ------------
quick = store.create_deal("Legacy Quick", QUICK, deal_context="Legacy thesis", business_plan=PLAN, db_path=db_path)
quick_fp = fingerprint_quick_inputs(QUICK, business_plan=PLAN)
store.update_analysis_snapshot(
    quick.id, dataclasses.asdict(analyze_quick_acquisition_with_business_plan(QUICK, business_plan=PLAN)),
    financial_input_fingerprint=quick_fp, db_path=db_path,
)
store.update_ai_snapshot(
    quick.id, dataclasses.asdict(AI),
    ai_context_fingerprint=fingerprint_ai(analysis_fingerprint=quick_fp, deal_context="Legacy thesis"),
    db_path=db_path,
)
manifest["deals"]["quick"] = {"id": quick.id, "financial_fingerprint": quick_fp}  # type: ignore[index]

# -- Detailed: empty plan, analysis and AI snapshots --------------------------
detailed = store.create_detailed_deal("Legacy Detailed", DETAILED_TERMS, DETAILED_OPERATING, db_path=db_path)
detailed_fp = fingerprint_detailed_inputs(DETAILED_TERMS, DETAILED_OPERATING, business_plan=BusinessPlan())
store.update_analysis_snapshot(
    detailed.id,
    dataclasses.asdict(
        analyze_detailed_acquisition_with_business_plan(DETAILED_TERMS, DETAILED_OPERATING, business_plan=BusinessPlan())
    ),
    financial_input_fingerprint=detailed_fp, db_path=db_path,
)
store.update_ai_snapshot(
    detailed.id, dataclasses.asdict(AI),
    ai_context_fingerprint=fingerprint_ai(analysis_fingerprint=detailed_fp, deal_context=None),
    db_path=db_path,
)
manifest["deals"]["detailed"] = {"id": detailed.id, "financial_fingerprint": detailed_fp}  # type: ignore[index]

# -- Lease-Level: material plan, AI and one-way sensitivity snapshots ---------
lease_level = store.create_lease_level_deal(
    "Legacy Lease-Level", LL_TERMS, LL_PROPERTY, LL_OPERATING, LL_MARKET, LL_SUITES, LL_LEASES,
    deal_context="Legacy rent roll", business_plan=PLAN, db_path=db_path,
)
ll_fp = fingerprint_lease_level_inputs(
    LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES,
    market_leasing=LL_MARKET, operating_inputs=LL_OPERATING, business_plan=PLAN,
)
store.update_ai_snapshot(
    lease_level.id, dataclasses.asdict(AI),
    ai_context_fingerprint=fingerprint_ai(analysis_fingerprint=ll_fp, deal_context="Legacy rent roll"),
    db_path=db_path,
)
one_way = run_lease_level_one_way_sensitivity(
    LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES, market_leasing=LL_MARKET, operating_inputs=LL_OPERATING,
    assumption="exit_cap_rate", values=[0.06, 0.07], metric="equity_multiple", business_plan=PLAN,
)
store.update_one_way_sensitivity_snapshot(
    lease_level.id,
    {
        "configuration": {"metric": "equity_multiple", "assumption": "exit_cap_rate", "values": ("6", "7")},
        "result": dataclasses.asdict(one_way),
    },
    financial_input_fingerprint=ll_fp, db_path=db_path,
)
manifest["deals"]["lease_level"] = {"id": lease_level.id, "financial_fingerprint": ll_fp}  # type: ignore[index]

# Every artifact must be current in the tree that wrote it, or the oracle would
# be proving the preservation of something already absent.
for name, entry in manifest["deals"].items():  # type: ignore[union-attr]
    deal = store.get_deal(entry["id"], db_path=db_path)
    assert deal.ai_snapshot is not None, name
    if name == "lease_level":
        assert deal.one_way_sensitivity_snapshot is not None
    else:
        assert deal.analysis_snapshot is not None, name

# -- The legacy-visible exchanges, through this tree's own app -----------------
from anchor.api import app  # noqa: E402

client = TestClient(app)
exchanges: list[dict[str, object]] = []


def record(method: str, path: str, body: object = None) -> dict:
    response = client.request(method, path, json=body)
    assert response.status_code == 200, (path, response.text)
    exchanges.append({"method": method, "path": path, "body": body, "status": 200, "json": response.json()})
    return response.json()


record("GET", "/deals")
for name, entry in manifest["deals"].items():  # type: ignore[union-attr]
    state = record("GET", f"/deals/{entry['id']}")
    mode = state["operating_mode"]
    body: dict[str, object] = {"operating_mode": mode, "business_plan": state["business_plan"]}
    if mode == "quick":
        body["inputs"] = state["inputs"]
        analyze_body: dict[str, object] = {**state["inputs"], "business_plan": state["business_plan"]}
    else:
        body["terms"] = state["terms"]
        if mode == "detailed":
            body["detailed_operating_inputs"] = state["detailed_operating_inputs"]
        else:
            for key in ("property_inputs", "operating_inputs", "market_leasing", "suites", "leases"):
                body[key] = state[key]
        analyze_body = dict(body)
    fingerprints = record("POST", "/deals/fingerprint", {**body, "deal_context": state["deal_context"]})
    assert fingerprints["financial_input_fingerprint"] == entry["financial_fingerprint"], name
    entry["analyze"] = record("POST", "/analyze", analyze_body)

manifest["exchanges"] = exchanges
connection = sqlite3.connect(db_path)
manifest["user_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
connection.close()

out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
