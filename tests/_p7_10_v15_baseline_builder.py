"""P7.10 Stage 4 baseline builder (not a test module; see
``tests/test_p7_10_stage_4_compatibility_oracle.py``).

Usage: ``python _p7_10_v15_baseline_builder.py <repo_root> <db_path> <manifest.json>``

``<repo_root>/src`` is ``main`` at ``9ca957a`` -- the accepted schema-v15 tree
Stage 4 starts from: every accepted layer through P7.10 Stage 2, and no report
artifact of any kind. It is exported by ``git archive``, which reads objects
only; no stash and no second checkout (protocol 11.1 / 11.2).

Self-contained, for the reason every earlier builder is: each asserts which tree
it is pointed at, and teaching one a different tree would edit another gate's
oracle inputs.

Through the v15 tree's own store and routes it writes the state a real database
holds before this gate -- including, and this is the point, **a published memo
version**. That version was issued before Anchor stored a report with each
publication, so after the v15 -> v16 migration it must report the typed
``REPORT_SNAPSHOT_NOT_AVAILABLE`` state rather than a report reconstructed from
today's numbers. Every response the v15 tree gives is recorded so the current
tree can be held to answering them identically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

root = Path(sys.argv[1]).resolve()
db_arg, manifest_arg = sys.argv[2], sys.argv[3]
sys.path.insert(0, str(root / "src"))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from fastapi.testclient import TestClient  # noqa: E402

from anchor import api as api_module  # noqa: E402
from anchor.contracts import AcquisitionInputs  # noqa: E402
from anchor.deals import memo_dependencies as deps  # noqa: E402
from anchor.deals import store  # noqa: E402
from anchor.memo.contracts import (  # noqa: E402
    AnalystRecommendation,
    DecisionPerspectiveKind,
    EvidenceSourceKind,
    ExecutionComplexity,
    InvestmentMemoDraft,
    MemoEvidenceReference,
    MemoItem,
    MemoRiskItem,
    MemoSection,
    MemoTermItem,
    RiskSeverity,
    SelectedDecision,
    TermPriority,
)
from anchor.valuation.contracts import (  # noqa: E402
    DirectCap,
    UnitValuationInstruction,
    ValuationKind,
    ValuationTimepoint,
)

assert store._SCHEMA_VERSION == 15, f"expected the v15 tree, got {store._SCHEMA_VERSION}"
assert (root / "src" / "anchor" / "memo").exists(), "the baseline tree should have accepted Stage 2"
assert not (root / "src" / "anchor" / "reporting").exists(), (
    "the baseline tree already has the Stage 4 reporting package"
)

db = Path(db_arg)
db.parent.mkdir(parents=True, exist_ok=True)
os_environ_key = "ANCHOR_DB_PATH"
import os  # noqa: E402

os.environ[os_environ_key] = str(db)

INPUTS = AcquisitionInputs(
    purchase_price=12_000_000.0,
    current_noi=720_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.06,
    ltv=0.55,
    interest_rate=0.055,
    amortization=30,
)

deal = store.create_deal("V15 baseline deal", INPUTS, db_path=db)

investment_id, _ = store.create_deal_valuation_timepoint(
    deal.id,
    ValuationTimepoint(
        timepoint_id="as-is",
        investment_id="",
        kind=ValuationKind.AS_IS,
        label="As-Is at closing",
        model_month=0,
        unit_instructions=(
            UnitValuationInstruction(unit_id=deal.id, method=DirectCap(cap_rate=0.055)),
        ),
    ),
    db_path=db,
)

store.put_evidence_reference(
    investment_id,
    MemoEvidenceReference(
        evidence_id="ev-1",
        investment_id=investment_id,
        source_kind=EvidenceSourceKind.CASE_DOCUMENT,
        title="Baseline rent roll",
        reference="data-room/baseline.xlsx",
        as_of_date=None,
        approved=True,
        display_order=0,
    ),
    db_path=db,
)

store.put_memo_draft(
    investment_id,
    InvestmentMemoDraft(
        memo_id="",
        investment_id=investment_id,
        prepared_by="Baseline analyst",
        decision_ask="Approve the baseline acquisition at $12.0m.",
        analyst_recommendation=AnalystRecommendation.APPROVE_WITH_CONDITIONS,
        executive_summary="A memo published before Anchor stored an issued report.",
        execution_complexity=ExecutionComplexity.MODERATE,
        return_on_time_notes="",
        selected_decision=SelectedDecision(
            strategy_id="base",
            scenario_id="base",
            perspective=DecisionPerspectiveKind.PROJECT,
            position_id=None,
            partner_id=None,
        ),
        items=(
            MemoItem(
                item_id="thesis-1",
                section=MemoSection.THESIS,
                display_order=0,
                text="Acquired below replacement cost.",
                evidence_ids=("ev-1",),
            ),
        ),
        risk_items=(
            MemoRiskItem(
                item_id="risk-1",
                display_order=0,
                text="Concentrated rollover.",
                severity=RiskSeverity.MODERATE,
                residual_risk=RiskSeverity.LOW,
                mitigant="Pre-leasing underway.",
                evidence_ids=(),
            ),
        ),
        term_items=(
            MemoTermItem(
                item_id="term-1",
                display_order=0,
                text="Sixty-day diligence.",
                priority=TermPriority.REQUIRED,
                evidence_ids=(),
            ),
        ),
        evidence_ids=("ev-1",),
        selected_valuation_timepoint_ids=("as-is",),
    ),
    db_path=db,
)

# The published version this oracle exists for: issued by the v15 tree, with no
# report artifact, because that tree stored none.
version = deps.publish(investment_id, db_path=db)

client = TestClient(api_module.app)

EXCHANGES: list[dict[str, Any]] = [
    {"method": "GET", "path": "/deals", "body": None},
    {"method": "GET", "path": f"/deals/{deal.id}", "body": None},
    {"method": "GET", "path": f"/investments/{investment_id}/valuation-timepoints", "body": None},
    {"method": "GET", "path": f"/investments/{investment_id}/evidence-references", "body": None},
    {"method": "GET", "path": f"/investments/{investment_id}/memo", "body": None},
    {"method": "GET", "path": f"/investments/{investment_id}/memo-versions", "body": None},
    {
        "method": "GET",
        "path": f"/investments/{investment_id}/memo-versions/{version.version_id}",
        "body": None,
    },
    {
        "method": "GET",
        "path": f"/investments/{investment_id}/memo-versions/{version.version_id}/freshness",
        "body": None,
    },
    {
        "method": "GET",
        "path": f"/investments/{investment_id}/memo-versions/{version.version_id}/decision",
        "body": None,
    },
    {
        "method": "GET",
        "path": f"/investments/{investment_id}/memo/publication-readiness",
        "body": None,
    },
    {
        "method": "POST",
        "path": f"/investments/{investment_id}/valuation-views/base/base",
        "body": None,
    },
]

recorded = []
for exchange in EXCHANGES:
    response = client.request(exchange["method"], exchange["path"], json=exchange["body"])
    recorded.append(
        {
            **exchange,
            "status": response.status_code,
            "json": response.json() if response.content else None,
        }
    )

import sqlite3  # noqa: E402

connection = sqlite3.connect(db)
try:
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
finally:
    connection.close()

Path(manifest_arg).write_text(
    json.dumps(
        {
            "user_version": user_version,
            "deal_id": deal.id,
            "investment_id": investment_id,
            "version_id": version.version_id,
            "version_number": version.version_number,
            "exchanges": recorded,
        },
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
print(f"v15 baseline written: user_version={user_version}, version={version.version_id}")
