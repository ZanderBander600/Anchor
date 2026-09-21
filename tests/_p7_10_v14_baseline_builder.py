"""P7.10 Stage 2 baseline builder (not a test module; see
``tests/test_p7_10_stage_2_compatibility_oracle.py``).

Usage: ``python _p7_10_v14_baseline_builder.py <repo_root> <db_path> <manifest.json>``

``<repo_root>/src`` is ``main`` at ``46650a7`` -- the schema-v14 tree P7.10
Stage 2 starts from: every accepted layer through Asset Types 1, plus the
accepted P7.10 **Stage 1** valuation engine, and no valuation or memo
persistence of any kind. It is exported by ``git archive``, which reads objects
only; no stash and no second checkout (protocol 11.1 / 11.2).

Self-contained, for the reason the AM1 and Asset Types 1 builders are: earlier
builders assert which tree they are pointed at, and teaching one a v14 tree
would edit another gate's oracle inputs.

Through the v14 tree's own store and routes it writes the state a real database
holds before this gate -- Deals in all three operating modes, a visible
Investment, a Deal opted into structured capital through its own door, a
Scenario and Strategies, a Partnership, and a Managed Asset -- then records
every response that tree gives for them. The current tree must answer every one
identically over a copy of the same database, and must add exactly the sixteen
empty P7.10 tables and nothing else.

Every literal is restated here or taken from the shared fixtures, so this script
imports nothing but the tree it is pointed at.
"""

from __future__ import annotations

import dataclasses
import json
import os
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
from anchor.deals import store  # noqa: E402

assert store._SCHEMA_VERSION == 14, f"expected the v14 tree, got {store._SCHEMA_VERSION}"
assert not (root / "src" / "anchor" / "memo").exists(), "the baseline tree already has the P7.10 memo domain"
assert (root / "src" / "anchor" / "valuation").exists(), "the baseline tree should have accepted Stage 1"

# The shared fixtures build every contract this needs and import nothing but
# ``anchor`` itself, so they describe the baseline tree's own shapes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _p7_1_scenario_fixtures as fx  # noqa: E402  # type: ignore[import-not-found]
import _p7_2_fixtures as f2  # noqa: E402  # type: ignore[import-not-found]

db = Path(db_arg)
db.parent.mkdir(parents=True, exist_ok=True)
os.environ["ANCHOR_DB_PATH"] = str(db)
client = TestClient(api_module.app)

exchanges: list[dict[str, Any]] = []


def record(method: str, path: str, body: Any = None, *, expect: int | None = None) -> Any:
    response = client.request(method, path, json=body)
    if expect is not None and response.status_code != expect:
        raise SystemExit(f"{method} {path} -> {response.status_code}: {response.text}")
    payload = response.json() if response.content else None
    exchanges.append(
        {"method": method, "path": path, "body": body, "status": response.status_code, "json": payload}
    )
    return payload


def _analyzed(deal: Any) -> Any:
    store.update_analysis_snapshot(
        deal.id,
        dataclasses.asdict(f2.analyze_deal(deal)),
        financial_input_fingerprint=f2.deal_fingerprint(deal),
        db_path=db,
    )
    return store.get_deal(deal.id, db_path=db)


# =============================================================================
# Deals, one per operating mode
# =============================================================================

PLAN = fx.business_plan()
QUICK_INPUTS = fx.quick_inputs()

quick = _analyzed(
    store.create_deal(
        "Harbor Point Apartments",
        QUICK_INPUTS,
        deal_context="Value-add garden community.",
        business_plan=PLAN,
        db_path=db,
    )
)
detailed = _analyzed(
    store.create_detailed_deal("Westlake Industrial", fx.detailed_terms(), fx.detailed_operating(), db_path=db)
)
_suites, _leases = fx.rent_roll()
lease_level = store.create_lease_level_deal(
    "Riverbend Retail",
    fx.lease_level_terms(),
    fx.lease_level_property(),
    fx.lease_level_operating(),
    fx.market(),
    tuple(_suites),
    tuple(_leases),
    db_path=db,
)

# =============================================================================
# A visible Investment over one Unit
# =============================================================================

visible = record(
    "POST",
    "/investments",
    {
        "name": "Harbor Portfolio",
        "transaction_price": QUICK_INPUTS.purchase_price,
        "units": [{"unit_id": quick.id, "label": "Harbor Point", "unit_kind": "property"}],
    },
    expect=200,
)
visible_id = visible["id"]

# =============================================================================
# A Deal opted into structured capital through its own door, which materializes
# its hidden one-unit Investment -- the same seam P7.10 Stage 2 uses
# =============================================================================

COMMON_EQUITY = {
    "position_id": "sponsor-equity",
    "name": "Sponsor Equity",
    "position_class": "common_equity",
    "priority": 99,
    "scope": {"kind": "unit", "unit_id": detailed.id},
    "funding": [],
    "terms": None,
    "shortfall_resolution": None,
}
SENIOR = {
    "position_id": "senior-loan",
    "name": "Senior Loan",
    "position_class": "senior_debt",
    "priority": 1,
    "scope": {"kind": "unit", "unit_id": detailed.id},
    "funding": [
        {
            "event_id": "senior-close",
            "model_month": 0,
            "sequence": 1,
            "amount_rule": {"kind": "pct_of_price", "pct": 0.55},
        }
    ],
    "terms": {
        "kind": "debt",
        "interest_rate": 0.062,
        "amortization": 30,
        "io_period": 12,
        "maturity_month": 60,
        "fees": [],
        "current_pay_rate": 0.062,
        "pik_rate": 0.0,
    },
    "shortfall_resolution": "common_equity_contribution",
}

record(
    "PUT",
    f"/deals/{detailed.id}/capital-structure",
    {"positions": [SENIOR, COMMON_EQUITY]},
    expect=200,
)
structured_id = client.get(f"/deals/{detailed.id}/capital-structure").json()["investment_id"]

# A Scenario and a Strategy on that hidden Investment.
scenario = record(
    "POST",
    f"/investments/{structured_id}/scenarios",
    {
        "name": "Softer exit",
        "description": "Exit cap +50bps.",
        "overrides": [
            {"unit_id": detailed.id, "target": "exit_cap_rate", "operation": "add", "value": 0.005}
        ],
    },
    expect=200,
)
strategy = record(
    "POST",
    f"/investments/{structured_id}/strategies",
    {
        "name": "Hold longer",
        "description": "Seven-year hold.",
        "overlays": [],
        "root_overlays": [],
    },
    expect=200,
)

# A Partnership on the same hidden Investment.
record(
    "PUT",
    f"/deals/{detailed.id}/partnership",
    {
        "partnership": {
            "partners": [
                {
                    "partner_id": "lp",
                    "name": "Institutional LP",
                    "role": "lp",
                    "investor_class": "lp",
                    "commitment_share": 0.9,
                },
                {
                    "partner_id": "gp",
                    "name": "Sponsor GP",
                    "role": "gp",
                    "investor_class": "gp",
                    "commitment_share": 0.1,
                },
            ],
            "contribution_rule": "pro_rata_by_commitment",
            "promote_benchmark": {"shares": [{"partner_id": "lp", "share": 1.0}]},
            "promote_participant_ids": ["gp"],
            "tiers": [
                {
                    "tier_id": "return-of-capital",
                    "name": "Return of capital",
                    "sequence": 1,
                    "kind": "hurdle",
                    "split": {"kind": "pro_rata_by_contribution"},
                    "hurdle": None,
                    "catch_up": None,
                },
                {
                    "tier_id": "residual",
                    "name": "Residual split",
                    "sequence": 2,
                    "kind": "residual",
                    "split": {
                        "kind": "explicit",
                        "shares": [
                            {"partner_id": "lp", "share": 0.8},
                            {"partner_id": "gp", "share": 0.2},
                        ],
                    },
                    "hurdle": None,
                    "catch_up": None,
                },
            ],
        }
    },
    expect=200,
)

# =============================================================================
# A Managed Asset, so the AM1 surface is represented too
# =============================================================================

managed = record(
    "POST",
    "/managed-assets",
    {
        "source_deal_id": lease_level.id,
        "name": "Riverbend (owned)",
        "acquisition_date": "2026-11-01",
        "property_type": None,
        "market": None,
        "asset_type": None,
        "asset_subtype": None,
    },
    expect=200,
)

# =============================================================================
# Every response recorded against the final state
# =============================================================================

record("GET", "/deals")
for deal_id in (quick.id, detailed.id, lease_level.id):
    record("GET", f"/deals/{deal_id}")
record("GET", "/deals/no-such-deal")
record("GET", "/investments")
record("GET", f"/investments/{visible_id}/details")
record("GET", "/managed-assets")
record("GET", f"/managed-assets/{managed['id']}")

record("GET", f"/deals/{detailed.id}/capital-structure")
record("GET", f"/investments/{structured_id}/capital-structure")
record("GET", f"/deals/{detailed.id}/partnership")
record("GET", f"/investments/{structured_id}/partnership")
record("GET", f"/investments/{structured_id}/scenarios")
record("GET", f"/investments/{structured_id}/strategies")
record("GET", f"/investments/{structured_id}/position-perspectives")
record("GET", f"/investments/{structured_id}/partner-perspectives")

for strategy_id in ("base", strategy["strategy"]["strategy_id"]):
    for scenario_id in ("base", scenario["scenario"]["scenario_id"]):
        record("GET", f"/investments/{structured_id}/variants/{strategy_id}/{scenario_id}/fingerprint")
        record("POST", f"/investments/{structured_id}/variants/{strategy_id}/{scenario_id}/analysis")
        record(
            "GET",
            f"/investments/{structured_id}/structured-variants/{strategy_id}/{scenario_id}/fingerprint",
        )
        record(
            "POST",
            f"/investments/{structured_id}/structured-variants/{strategy_id}/{scenario_id}/analysis",
        )
        record(
            "GET",
            f"/investments/{structured_id}/partnership-variants/{strategy_id}/{scenario_id}/fingerprint",
        )
        record(
            "POST",
            f"/investments/{structured_id}/partnership-variants/{strategy_id}/{scenario_id}/analysis",
        )

record("POST", f"/investments/{structured_id}/decision-matrix", {"perspective": "project"})
record("POST", f"/investments/{structured_id}/position-decision-matrix/senior-loan")
record("POST", f"/investments/{structured_id}/partner-decision-matrix/lp")

_quick_body = dataclasses.asdict(QUICK_INPUTS)
_plan_body = dataclasses.asdict(PLAN)
record("POST", "/analyze", {**_quick_body, "business_plan": _plan_body})
record("POST", "/deals/fingerprint", {"operating_mode": "quick", "inputs": _quick_body, "business_plan": _plan_body})

connection = __import__("sqlite3").connect(db)
try:
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
finally:
    connection.close()

Path(manifest_arg).write_text(
    json.dumps(
        {
            "user_version": user_version,
            "quick_deal_id": quick.id,
            "detailed_deal_id": detailed.id,
            "lease_level_deal_id": lease_level.id,
            "visible_investment_id": visible_id,
            "structured_investment_id": structured_id,
            "managed_asset_id": managed["id"],
            "scenario_id": scenario["scenario"]["scenario_id"],
            "strategy_id": strategy["strategy"]["strategy_id"],
            "exchanges": exchanges,
        },
        indent=2,
    ),
    encoding="utf-8",
)
print(f"baseline written: {db} (schema {user_version}, {len(exchanges)} exchanges)")
