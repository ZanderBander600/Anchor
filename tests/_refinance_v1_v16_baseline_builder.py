"""Refinance & Capital Events V1 Stage 2 baseline builder (not a test module;
see ``tests/test_refinance_v1_stage_2_compatibility_oracle.py``).

Usage: ``python _refinance_v1_v16_baseline_builder.py <repo_root> <db_path> <manifest.json>``

``<repo_root>/src`` is accepted ``main`` at ``f2b5cef`` -- the schema-v16 tree
Stage 2 starts from: every accepted layer through P7.10 Stage 4 and the
Refinance V1 Stage 1 engine, and no persisted capital event of any kind. It is
exported by ``git archive``, which reads objects only; no stash and no second
checkout (protocol 11.1 / 11.2).

Self-contained, for the reason every earlier builder is: it asserts which tree
it is pointed at, and every Deal, Investment, structure, Partnership, valuation
and memo it writes is a literal restated here.

Through the v16 tree's own store and routes it writes the state a real v16
database holds -- Quick, Detailed and Lease-Level Deals; a one-unit Strategy x
Scenario matrix; a structured Deal with inheriting, emptied, replaced and
unresolved Strategies; a mixed visible Investment with an Investment-scoped
position; Partnerships on both; a valuation and Evidence Reference; and a
published memo version with its frozen report and PDF -- and records every
response the tree gives. Binary responses (the Excel Exports 1-3 and the issued
PDF) are recorded by their SHA-256 digest and length.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

root = Path(sys.argv[1]).resolve()
db = Path(sys.argv[2])
manifest_path = Path(sys.argv[3])
sys.path.insert(0, str(root / "src"))
os.environ["ANCHOR_DB_PATH"] = str(db)
#: The workbook provenance a replay can reproduce exactly: a stated commit and a
#: frozen clock (``FROZEN_NOW``, installed on ``anchor.api`` below).
os.environ["ANCHOR_SOURCE_COMMIT"] = "0" * 40

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from anchor.deals import store  # noqa: E402

assert store._SCHEMA_VERSION == 16, f"expected the v16 tree, got {store._SCHEMA_VERSION}"
assert (root / "src" / "anchor" / "capital_structure" / "refinance_execution.py").exists(), (
    "the baseline tree should hold the accepted Stage 1 engine"
)
assert not (root / "src" / "anchor" / "deals" / "capital_event_identity.py").exists(), (
    "the baseline tree already has Stage 2"
)
assert "capital_events" not in (root / "src" / "anchor" / "deals" / "store.py").read_text(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from anchor.analysis import (  # noqa: E402
    EscalationBasis,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    Suite,
)
import anchor.api as api_module  # noqa: E402
from anchor.api import app  # noqa: E402
from anchor.business_plan import BusinessPlan  # noqa: E402
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs  # noqa: E402
from anchor.deals import memo_dependencies as deps  # noqa: E402
from anchor.investment import InvestmentUnitMembership, UnitKind  # noqa: E402
from anchor.memo.contracts import (  # noqa: E402
    AnalystRecommendation,
    DecisionPerspectiveKind,
    EvidenceSourceKind,
    ExecutionComplexity,
    InvestmentMemoDraft,
    MemoEvidenceReference,
    MemoItem,
    MemoSection,
    SelectedDecision,
)
from _p7_9_fixtures import f1_terms  # noqa: E402  # accepted P7.9 shapes only
from anchor.valuation.contracts import (  # noqa: E402
    DirectCap,
    UnitValuationInstruction,
    ValuationKind,
    ValuationTimepoint,
)

QUICK = AcquisitionInputs(
    purchase_price=12_500_000.0, current_noi=800_000.0, occupancy=0.94, noi_growth=0.03,
    hold_period=5, exit_cap_rate=0.0625, ltv=0.65, interest_rate=0.0575, amortization=30,
    acquisition_cost_pct=0.02, financing_fee_pct=0.01, disposition_cost_pct=0.02,
    annual_capex_reserve=40_000.0, io_period=2,
)
DETAILED_TERMS = AcquisitionTerms(
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
    Suite(suite_id="C", suite_area_sf=30_000.0),
)
LL_LEASES = tuple(
    Lease(
        lease_id=f"L-{suite.suite_id}", suite_id=suite.suite_id, leased_area_sf=suite.suite_area_sf,
        rent_commencement_date=date(2024, 1, 1), lease_expiration_date=expires, base_rent_psf=rent,
        escalation_pct=0.02, escalation_basis=EscalationBasis.LEASE_ANNIVERSARY, lease_type=LeaseType.NNN,
    )
    for suite, expires, rent in zip(
        LL_SUITES, (date(2028, 6, 30), date(2029, 12, 31), date(2033, 12, 31)), (32.0, 38.0, 34.0), strict=True
    )
)

import datetime as _datetime  # noqa: E402

FROZEN_NOW = _datetime.datetime(2026, 9, 24, 12, 0, tzinfo=_datetime.timezone.utc)


class _FrozenDatetime(_datetime.datetime):
    @classmethod
    def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
        return FROZEN_NOW


api_module.datetime = _FrozenDatetime  # type: ignore[attr-defined]


def workbook_content_digest(data: bytes) -> str:
    """Every sheet's cell values, formulas and number formats plus the defined
    names -- the accepted Excel Export content digest, which ignores how the
    writer packages the file."""

    import io

    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data))
    parts: list[str] = []
    for name in workbook.sheetnames:
        sheet = workbook[name]
        parts.append(f"#sheet:{name}")
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    parts.append(f"{cell.coordinate}|{cell.value!r}|{cell.number_format}")
        for item_name, item in sorted(workbook.defined_names.items()):
            parts.append(f"!name:{item_name}={item.value}")
    return hashlib.sha256(chr(10).join(parts).encode("utf-8")).hexdigest()


client = TestClient(app)


def ok(method: str, path: str, body: object = None) -> Any:
    response = client.request(method, path, json=body)
    assert response.status_code == 200, (path, response.text)
    return response.json()


def mezz(position_id: str, scope: dict[str, Any], *, amount: float, maturity_month: int, resolution: str) -> dict[str, Any]:
    return {
        "position_id": position_id,
        "name": "Mezzanine",
        "position_class": "mezzanine_debt",
        "priority": 2,
        "scope": scope,
        "funding": [
            {"event_id": f"{position_id}-funding", "model_month": 0, "sequence": 1,
             "amount_rule": {"kind": "fixed_amount", "amount": amount}},
        ],
        "terms": {
            "kind": "debt", "interest_rate": 0.12, "amortization": 25, "io_period": 1,
            "maturity_month": maturity_month,
            "fees": [{"fee_id": f"{position_id}-fee", "description": "Origination fee", "amount": 15_000.0,
                      "model_month": 0, "sequence": 2}],
            "current_pay_rate": 0.12, "pik_rate": 0.0,
        },
        "shortfall_resolution": resolution,
    }


def partnership() -> Any:
    """The accepted P7.9 F1 terms: LP 90% / GP 10%, an 8% IRR hurdle, then 70/30."""

    return f1_terms()


# --- 1. Standalone Deals in every mode ---------------------------------------

standalone = {
    "quick": store.create_deal("Quick", QUICK, db_path=db),
    "detailed": store.create_detailed_deal("Detailed", DETAILED_TERMS, DETAILED_OPERATING, db_path=db),
    "lease_level": store.create_lease_level_deal(
        "Lease-Level", LL_TERMS, LL_PROPERTY, LL_OPERATING, LL_MARKET, LL_SUITES, LL_LEASES,
        business_plan=BusinessPlan(), db_path=db,
    ),
}

# --- 2. A structured Deal: every no-event Capital Structure shape ---------------

structured = store.create_deal("Structured Quick", QUICK, db_path=db)
unit_scope = {"kind": "unit", "unit_id": structured.id}
opted = ok("PUT", f"/deals/{structured.id}/capital-structure", {"positions": [
    mezz("mezz-a", unit_scope, amount=1_500_000.0, maturity_month=60, resolution="common_equity_contribution"),
]})
structured_id = opted["investment_id"]
scenario = ok("POST", f"/investments/{structured_id}/scenarios", {
    "name": "Downside", "overrides": [
        {"unit_id": structured.id, "target": "exit_cap_rate", "operation": "add", "value": 0.005},
    ],
})
strategies = [
    ok("POST", f"/investments/{structured_id}/strategies", body)["strategy"]["strategy_id"]
    for body in (
        {"name": "Inherit", "overlays": [
            {"unit_id": structured.id, "domain": "acquisition",
             "content": {"purchase_price": 12_000_000.0, "acquisition_cost_pct": 0.02}},
        ]},
        {"name": "No structured capital", "root_overlays": [{"domain": "capital_structure", "content": {"positions": []}}]},
        {"name": "Bigger mezzanine", "root_overlays": [{"domain": "capital_structure", "content": {"positions": [
            mezz("mezz-a", unit_scope, amount=2_000_000.0, maturity_month=60, resolution="common_equity_contribution"),
        ]}}]},
        {"name": "Balloon, unresolved", "root_overlays": [{"domain": "capital_structure", "content": {"positions": [
            mezz("mezz-a", unit_scope, amount=1_500_000.0, maturity_month=24, resolution="unresolved"),
        ]}}]},
    )
]
structured_strategies = ["base", *strategies]
structured_scenarios = ["base", scenario["scenario"]["scenario_id"]]
store.set_deal_partnership(structured.id, partnership(), db_path=db)

# The valuation, evidence and a published memo with its frozen report and PDF.
store.create_valuation_timepoint(
    structured_id,
    ValuationTimepoint(
        timepoint_id="year-2", investment_id=structured_id, kind=ValuationKind.STABILIZED, label="Year-2 value",
        model_month=24, unit_instructions=(UnitValuationInstruction(unit_id=structured.id, method=DirectCap(cap_rate=0.06)),),
    ),
    db_path=db,
)
store.put_evidence_reference(
    structured_id,
    MemoEvidenceReference(
        evidence_id="ev-1", investment_id=structured_id, source_kind=EvidenceSourceKind.CASE_DOCUMENT,
        title="Rent roll", reference="data-room/rent-roll.xlsx", as_of_date=None, approved=True, display_order=0,
    ),
    db_path=db,
)
store.put_memo_draft(
    structured_id,
    InvestmentMemoDraft(
        memo_id="", investment_id=structured_id, prepared_by="Baseline analyst",
        decision_ask="Approve the structured acquisition.",
        analyst_recommendation=AnalystRecommendation.APPROVE_WITH_CONDITIONS,
        executive_summary="Published before any refinance could be persisted.",
        execution_complexity=ExecutionComplexity.MODERATE, return_on_time_notes="",
        selected_decision=SelectedDecision(
            strategy_id="base", scenario_id="base", perspective=DecisionPerspectiveKind.POSITION,
            position_id="mezz-a", partner_id=None,
        ),
        items=(MemoItem(item_id="thesis-1", section=MemoSection.THESIS, display_order=0,
                        text="Stable income with a modest mezzanine layer.", evidence_ids=("ev-1",)),),
        risk_items=(), term_items=(), evidence_ids=("ev-1",), selected_valuation_timepoint_ids=("year-2",),
    ),
    db_path=db,
)
version = deps.publish(structured_id, db_path=db)

# --- 3. A mixed visible Investment with an Investment-scoped position ----------

portfolio = (
    store.create_deal("Portfolio Quick", QUICK, db_path=db),
    store.create_detailed_deal("Portfolio Detailed", DETAILED_TERMS, DETAILED_OPERATING, db_path=db),
)
visible = store.create_visible_investment(
    name="Mixed portfolio",
    transaction_price=QUICK.purchase_price + DETAILED_TERMS.purchase_price,
    units=tuple(
        InvestmentUnitMembership(unit_id=deal.id, ordinal=index, label=None, unit_kind=UnitKind.PROPERTY,
                                 acquisition_month=0, disposition_month=None)
        for index, deal in enumerate(portfolio)
    ),
    business_plan=BusinessPlan(),
    db_path=db,
)
ok("PUT", f"/investments/{visible.id}/capital-structure", {"positions": [
    mezz("portfolio-mezz", {"kind": "investment", "unit_id": None}, amount=4_000_000.0, maturity_month=60,
         resolution="common_equity_contribution"),
]})
store.set_base_partnership(visible.id, partnership(), db_path=db)

# Warm the Project variant caches, so every recorded analysis is a stable read.
for strategy_id in structured_strategies:
    for scenario_id in structured_scenarios:
        ok("POST", f"/investments/{structured_id}/structured-variants/{strategy_id}/{scenario_id}/analysis")
ok("POST", f"/investments/{visible.id}/structured-variants/base/base/analysis")

# --- 4. Record everything against the final state ------------------------------

exchanges: list[dict[str, Any]] = []


def record(method: str, path: str, body: object = None) -> None:
    response = client.request(method, path, json=body)
    entry: dict[str, Any] = {"method": method, "path": path, "body": body, "status": response.status_code}
    if response.headers.get("content-type", "").startswith("application/json"):
        entry["json"] = response.json()
        entry["raw_sha256"] = hashlib.sha256(response.content).hexdigest()
    elif path.endswith(".xlsx"):
        entry["content_sha256"] = workbook_content_digest(response.content)
    else:
        entry["sha256"] = hashlib.sha256(response.content).hexdigest()
        entry["length"] = len(response.content)
    assert response.status_code == 200, (path, response.text[:500])
    exchanges.append(entry)


def _bodies(deal_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The Deal's saved state, its fingerprint body and its ``/analyze`` body,
    exactly as the workspace sends them."""

    state = ok("GET", f"/deals/{deal_id}")
    mode = state["operating_mode"]
    body: dict[str, Any] = {"operating_mode": mode, "business_plan": state["business_plan"]}
    if mode == "quick":
        body["inputs"] = state["inputs"]
        analyze_body: dict[str, Any] = {**state["inputs"], "business_plan": state["business_plan"]}
    else:
        body["terms"] = state["terms"]
        if mode == "detailed":
            body["detailed_operating_inputs"] = state["detailed_operating_inputs"]
        else:
            for key in ("property_inputs", "operating_inputs", "market_leasing", "suites", "leases"):
                body[key] = state[key]
        analyze_body = dict(body)
    return state, {**body, "deal_context": state["deal_context"]}, analyze_body


# Save the Quick and Detailed analyses the way the workspace does, so Excel
# Exports 1 and 2 have the current snapshot they export from. Lease-Level
# persists no analysis: Export 3 analyses the saved state it reads.
for deal in (standalone["quick"], standalone["detailed"]):
    _, fingerprint_body, analyze_body = _bodies(deal.id)
    provenance = ok("POST", "/deals/fingerprint", fingerprint_body)
    store.update_analysis_snapshot(
        deal.id,
        ok("POST", "/analyze", analyze_body),
        financial_input_fingerprint=provenance["financial_input_fingerprint"],
        db_path=db,
    )

record("GET", "/deals")
for deal in standalone.values():
    _, fingerprint_body, analyze_body = _bodies(deal.id)
    record("GET", f"/deals/{deal.id}")
    record("POST", "/deals/fingerprint", fingerprint_body)
    record("POST", "/analyze", analyze_body)
    record("GET", f"/deals/{deal.id}/capital-structure")
record("GET", f"/deals/{standalone['quick'].id}/exports/quick-underwrite.xlsx")
record("GET", f"/deals/{standalone['detailed'].id}/exports/detailed-underwrite.xlsx")
record("GET", f"/deals/{standalone['lease_level'].id}/exports/lease-level.xlsx")

record("GET", f"/deals/{structured.id}/capital-structure")
record("GET", f"/deals/{structured.id}/partnership")
record("GET", f"/investments/{structured_id}/capital-structure")
record("GET", f"/investments/{structured_id}/strategies")
for strategy_id in structured_strategies:
    for scenario_id in structured_scenarios:
        variant = f"/investments/{structured_id}/structured-variants/{strategy_id}/{scenario_id}"
        record("GET", f"{variant}/fingerprint")
        record("POST", f"{variant}/analysis")
        partnership_variant = f"/investments/{structured_id}/partnership-variants/{strategy_id}/{scenario_id}"
        record("GET", f"{partnership_variant}/fingerprint")
        record("POST", f"{partnership_variant}/analysis")
record("GET", f"/investments/{structured_id}/position-perspectives")
record("GET", f"/investments/{structured_id}/partner-perspectives")
record("POST", f"/investments/{structured_id}/decision-matrix")
record("POST", f"/investments/{structured_id}/position-decision-matrix/mezz-a")
record("POST", f"/investments/{structured_id}/partner-decision-matrix/lp")
record("GET", f"/investments/{structured_id}/valuation-timepoints")
record("POST", f"/investments/{structured_id}/valuation-views/base/base")
record("GET", f"/investments/{structured_id}/memo")
record("GET", f"/investments/{structured_id}/memo-versions")
record("GET", f"/investments/{structured_id}/memo-versions/{version.version_id}")
record("GET", f"/investments/{structured_id}/memo-versions/{version.version_id}/freshness")
record("GET", f"/investments/{structured_id}/memo-versions/{version.version_id}/report")
record("GET", f"/investments/{structured_id}/memo-versions/{version.version_id}/exports/investment-memo.pdf")
record("GET", f"/investments/{structured_id}/memo/publication-readiness")

record("GET", f"/investments/{visible.id}/capital-structure")
record("GET", f"/investments/{visible.id}/partnership")
for kind in ("structured-variants", "partnership-variants"):
    record("GET", f"/investments/{visible.id}/{kind}/base/base/fingerprint")
    record("POST", f"/investments/{visible.id}/{kind}/base/base/analysis")
record("POST", f"/investments/{visible.id}/position-decision-matrix/portfolio-mezz")
record("POST", f"/investments/{visible.id}/partner-decision-matrix/lp")

connection = sqlite3.connect(db)
try:
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
finally:
    connection.close()
manifest_path.write_text(
    json.dumps(
        {
            "user_version": user_version,
            "structured_investment_id": structured_id,
            "visible_investment_id": visible.id,
            "structured_strategies": structured_strategies,
            "version_id": version.version_id,
            "exchanges": exchanges,
        },
        indent=1,
        sort_keys=True,
    ),
    encoding="utf-8",
)
print(f"v16 baseline written: user_version={user_version}, exchanges={len(exchanges)}")
