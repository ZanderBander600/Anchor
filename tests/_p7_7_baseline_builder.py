"""P7.7 baseline builder (not a test module; see
``tests/test_p7_7_compatibility_oracle.py``).

Usage: ``python _p7_7_baseline_builder.py <repo_root> <db_path> <out.json>``

Runs entirely inside ``<repo_root>/src`` -- the P7.6 merge ``fbaa07b``, exported
by ``git archive``, a schema-v10 tree with no Capital Structure package. It writes
a database through that tree's own store and records, through that tree's own
HTTP app, every representative existing exchange:

- Quick, Detailed and Lease-Level Deals, and Quick and Lease-Level Deals with a
  Business Plan: each Deal, its fingerprint and its ``/analyze`` economics;
- a P7.5 one-unit Strategy x Scenario Decision Matrix on a hidden Investment,
  with every variant's inputs, fingerprint and analysis (the Quick cache warmed
  first, so replaying reads it and writes nothing);
- a P7.6 visible mixed-mode Investment (Quick, Detailed and Lease-Level Units,
  Unit and Investment Business Plans, a transaction cost and a Scenario): its
  details, every consolidated variant's inputs, fingerprint and analysis, and
  its Investment Decision Matrix.

The P7.7 tree must return exactly the same responses over a copy of the same
database. The Deals are literals restated here, so this script imports nothing
but the tree it is pointed at.
"""

from __future__ import annotations

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
assert not (root / "src" / "anchor" / "capital_structure").exists(), "the baseline tree already has P7.7"

from fastapi.testclient import TestClient  # noqa: E402

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
from anchor.investment import (  # noqa: E402
    InvestmentTransactionCost,
    InvestmentUnitMembership,
    TransactionCostCategory,
    UnitKind,
)

assert store._SCHEMA_VERSION == 10, f"expected the v10 tree, got {store._SCHEMA_VERSION}"

PLAN = BusinessPlan(
    capital_items=(
        CapitalPlanItem(item_id="cap-2", description="Roof", category=CapitalItemCategory.BUILDING_SYSTEMS, month=15, amount=400_000.0),
        CapitalPlanItem(item_id="cap-1", description="Lobby", category=CapitalItemCategory.VALUE_ADD_RENOVATION, month=0, amount=250_000.0),
    ),
    owner_expense_items=(
        OwnerExpenseItem(
            item_id="ox-1", description="Asset management", category=OwnerExpenseCategory.ASSET_MANAGEMENT,
            annual_amount=50_000.0, first_year=1, last_year=None,
        ),
    ),
)
INVESTMENT_PLAN = BusinessPlan(
    capital_items=(
        CapitalPlanItem(item_id="inv-closing", description="Portfolio systems", category=CapitalItemCategory.OTHER, month=0, amount=200_000.0),
        CapitalPlanItem(item_id="inv-year-2", description="Shared amenity", category=CapitalItemCategory.VALUE_ADD_RENOVATION, month=18, amount=300_000.0),
    ),
    owner_expense_items=(
        OwnerExpenseItem(
            item_id="inv-am", description="Portfolio asset management", category=OwnerExpenseCategory.ASSET_MANAGEMENT,
            annual_amount=75_000.0, first_year=1, last_year=None,
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
DETAILED_TERMS_5 = AcquisitionTerms(
    purchase_price=18_000_000.0, hold_period=5, exit_cap_rate=0.065, ltv=0.62,
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
        initial_vacancy=InitialVacancyAssumptions(strategy=InitialVacancyStrategy.MARKET_LEASE_UP, initial_lease_up_months=9.0),
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


def _lease_level(name: str, plan: BusinessPlan) -> object:
    return store.create_lease_level_deal(
        name, LL_TERMS, LL_PROPERTY, LL_OPERATING, LL_MARKET, LL_SUITES, LL_LEASES, business_plan=plan, db_path=db_path
    )


standalone = {
    "quick": store.create_deal("Quick", QUICK, db_path=db_path),
    "quick_plan": store.create_deal("Quick with plan", QUICK, business_plan=PLAN, db_path=db_path),
    "detailed": store.create_detailed_deal("Detailed", DETAILED_TERMS, DETAILED_OPERATING, db_path=db_path),
    "lease_level": _lease_level("Lease-Level", BusinessPlan()),
    "lease_level_plan": _lease_level("Lease-Level with plan", PLAN),
}
portfolio = {
    "quick": store.create_deal("Portfolio Quick", QUICK, business_plan=PLAN, db_path=db_path),
    "detailed": store.create_detailed_deal("Portfolio Detailed", DETAILED_TERMS_5, DETAILED_OPERATING, db_path=db_path),
    "lease_level": _lease_level("Portfolio Lease-Level", PLAN),
}
visible = store.create_visible_investment(
    name="Mixed portfolio",
    transaction_price=QUICK.purchase_price + DETAILED_TERMS_5.purchase_price + LL_TERMS.purchase_price,
    units=tuple(
        InvestmentUnitMembership(
            unit_id=deal.id, ordinal=index, label=None, unit_kind=UnitKind.PROPERTY, acquisition_month=0, disposition_month=None
        )
        for index, deal in enumerate(portfolio.values())
    ),
    business_plan=INVESTMENT_PLAN,
    transaction_costs=(
        InvestmentTransactionCost(
            cost_id="tc-1", description="Acquisition fee", category=TransactionCostCategory.ACQUISITION_FEE,
            amount=150_000.0, model_month=0,
        ),
    ),
    db_path=db_path,
)

from anchor.api import app  # noqa: E402

client = TestClient(app)


def ok(method: str, path: str, body: object = None) -> dict:
    response = client.request(method, path, json=body)
    assert response.status_code == 200, (path, response.text)
    return response.json()


decision_deal = standalone["quick_plan"]
scenario = ok("POST", f"/deals/{decision_deal.id}/scenarios", {
    "name": "Downside", "description": "Wider exit", "overrides": [
        {"unit_id": decision_deal.id, "target": "exit_cap_rate", "operation": "add", "value": 0.005},
    ],
})
hidden_id = scenario["investment_id"]
strategy = ok("POST", f"/investments/{hidden_id}/strategies", {
    "name": "Bid low", "overlays": [
        {"unit_id": decision_deal.id, "domain": "acquisition", "content": {"purchase_price": 12_000_000.0, "acquisition_cost_pct": 0.02}},
    ],
})
hidden_strategies = ["base", strategy["strategy"]["strategy_id"]]
hidden_scenarios = ["base", scenario["scenario"]["scenario_id"]]
visible_scenario = ok("POST", f"/investments/{visible.id}/scenarios", {
    "name": "Downside", "overrides": [
        {"unit_id": portfolio["quick"].id, "target": "exit_cap_rate", "operation": "add", "value": 0.005},
    ],
})
visible_scenarios = ["base", visible_scenario["scenario"]["scenario_id"]]

# Warm the one-unit variant cache, so every recorded analysis is a stable read.
for strategy_id in hidden_strategies:
    for scenario_id in hidden_scenarios:
        ok("POST", f"/investments/{hidden_id}/variants/{strategy_id}/{scenario_id}/analysis")
ok("POST", f"/investments/{hidden_id}/decision-matrix")

exchanges: list[dict[str, object]] = []


def record(method: str, path: str, body: object = None) -> dict:
    payload = ok(method, path, body)
    exchanges.append({"method": method, "path": path, "body": body, "status": 200, "json": payload})
    return payload


record("GET", "/deals")
for deal in standalone.values():
    state = record("GET", f"/deals/{deal.id}")
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
    record("POST", "/deals/fingerprint", {**body, "deal_context": state["deal_context"]})
    record("POST", "/analyze", analyze_body)

record("GET", f"/investments/{hidden_id}")
for strategy_id in hidden_strategies:
    for scenario_id in hidden_scenarios:
        variant = f"/investments/{hidden_id}/variants/{strategy_id}/{scenario_id}"
        record("GET", f"{variant}/inputs")
        record("GET", f"{variant}/fingerprint")
        record("POST", f"{variant}/analysis")
record("POST", f"/investments/{hidden_id}/decision-matrix")

record("GET", "/investments")
record("GET", f"/investments/{visible.id}/details")
for scenario_id in visible_scenarios:
    variant = f"/investments/{visible.id}/investment-variants/base/{scenario_id}"
    record("GET", f"{variant}/inputs")
    record("GET", f"{variant}/fingerprint")
    record("POST", f"{variant}/analysis")
record("POST", f"/investments/{visible.id}/investment-decision-matrix")

connection = sqlite3.connect(db_path)
user_version = connection.execute("PRAGMA user_version").fetchone()[0]
connection.close()
manifest = {
    "exchanges": exchanges,
    "user_version": user_version,
    "hidden_investment_id": hidden_id,
    "visible_investment_id": visible.id,
}
out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
