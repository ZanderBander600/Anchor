"""Seed Anchor's demo database with an ILLUSTRATIVE value-add multifamily deal.

Usage (from the repo root, with the backend NOT running):
    set ANCHOR_DB_PATH=data\\demo.db          (Windows)   |   export ANCHOR_DB_PATH=data/demo.db
    .venv\\Scripts\\python seed_demo_deal.py

Every number is an illustrative assumption for a product demo. It is not an
underwriting of any real property and uses no confidential data.
"""
import os
from pathlib import Path

from fastapi.testclient import TestClient

from anchor.business_plan.contracts import BusinessPlan
from anchor.contracts import AcquisitionTerms, DetailedOperatingInputs
from anchor.deals import store

db_path = Path(os.environ.get("ANCHOR_DB_PATH", "data/demo.db"))
if db_path.resolve() == Path("data/anchor.db").resolve():
    raise SystemExit("Refusing to seed the main database. Set ANCHOR_DB_PATH to a demo database.")
db_path.parent.mkdir(parents=True, exist_ok=True)
os.environ["ANCHOR_DB_PATH"] = str(db_path)

UNITS = 180
terms = AcquisitionTerms(
    purchase_price=185_000 * UNITS,     # $33.3M = $185K/unit
    hold_period=7,
    exit_cap_rate=0.055,
    ltv=0.60,
    interest_rate=0.055,
    amortization=30,
    acquisition_cost_pct=0.015,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.015,
    annual_capex_reserve=250 * UNITS,   # $250/unit/yr
    io_period=7,                        # interest-only through the hold
)
operating = DetailedOperatingInputs(
    gross_potential_rent=UNITS * 1_450 * 12,   # $1,450 avg in-place rent
    other_income=UNITS * 100 * 12,             # $100/unit/month fees, RUBS, etc.
    vacancy_credit_loss_pct=0.07,
    property_taxes=360_000,
    insurance=145_000,
    utilities=190_000,
    repairs_maintenance=170_000,
    other_operating_expenses=280_000,          # payroll, admin, marketing
    management_fee_pct=0.03,
    revenue_growth=0.025,
    expense_growth=0.0275,
)
context = (
    "Sample deal for demonstration. 1990s garden-style multifamily in a growing Sun Belt suburb. "
    "Business plan: renovate 150 interiors to capture a rent premium; underwrite demand upside as an option, not the base case."
)
deal = store.create_detailed_deal(
    "Sample - 180-unit value-add multifamily", terms, operating,
    deal_context=context, business_plan=BusinessPlan(), db_path=db_path,
)

from anchor.api import app  # imported after ANCHOR_DB_PATH is set

client = TestClient(app)


def call(method, path, body=None):
    response = client.request(method, path, json=body)
    if response.status_code != 200:
        raise SystemExit(f"{method} {path} failed: {response.status_code} {response.text}")
    return response.json()


u = deal.id
upside = call("POST", f"/deals/{u}/scenarios", {
    "name": "Upside", "description": "Faster rent recovery; modest cap compression.",
    "overrides": [
        {"unit_id": u, "target": "revenue_growth", "operation": "add", "value": 0.015},
        {"unit_id": u, "target": "exit_cap_rate", "operation": "set", "value": 0.0525},
    ]})
investment_id = upside["investment_id"]
call("POST", f"/investments/{investment_id}/scenarios", {
    "name": "Downside", "description": "Rents flat, softer occupancy, wider exit cap.",
    "overrides": [
        {"unit_id": u, "target": "revenue_growth", "operation": "add", "value": -0.015},
        {"unit_id": u, "target": "vacancy_credit_loss_pct", "operation": "add", "value": 0.02},
        {"unit_id": u, "target": "exit_cap_rate", "operation": "set", "value": 0.06},
    ]})
call("POST", f"/investments/{investment_id}/strategies", {
    "name": "Value-add renovation",
    "description": "150 interiors at $10K funded at closing; renovation premium underwritten explicitly as +1.5 pts of revenue growth.",
    "overlays": [
        {"unit_id": u, "domain": "business_plan", "content": {
            "capital_items": [{"item_id": "reno", "description": "Interior renovations: 150 units x $10K",
                               "category": "value_add_renovation", "month": 0, "amount": 1_500_000.0}],
            "owner_expense_items": []}},
        {"unit_id": u, "domain": "operating_outcome", "content": {
            "outcomes": [{"target": "revenue_growth", "operation": "set", "value": 0.04}]}},
    ]})
matrix = call("POST", f"/investments/{investment_id}/decision-matrix")
print(f"Seeded deal {u} into {db_path}")
for cell in matrix["matrix"]["cells"]:
    r = cell.get("results") or {}
    irr, em = r.get("levered_irr"), r.get("equity_multiple")
    print(f"  {cell['strategy_id'][:8]:8s} x {cell['scenario_id'][:8]:8s}  {cell['status']:7s}  "
          f"levered IRR {irr*100:5.1f}%  EM {em:.2f}x" if irr is not None else f"  {cell['status']}")
