"""P7.9 Stage 2 baseline builder (not a test module; see
``tests/test_p7_9_stage_2_compatibility_oracle.py``).

Usage: ``python _p7_9_v11_baseline_builder.py <repo_root> <db_path> <manifest.json>``

``<repo_root>/src`` is ``main`` at ``1df2760`` -- the schema-v11 tree with the
P7.8B Capital Structure product surface and the accepted P7.9 Stage 1 engine,
but no Partnership persistence -- exported by ``git archive``.

1. The P7.7 builder (``_p7_7_baseline_builder.py``) runs against it, with its
   optional fourth argument ``v11`` asserting which tree it is, and writes the
   Quick / Detailed / Lease-Level Deals, the P7.5 one-unit matrix and the P7.6
   visible mixed-mode Investment through that tree's own store and routes.
2. Then, through that tree's own routes, this adds every P7.8B surface a v11
   database can hold: a Deal opted into structured capital through its own
   door (materializing its hidden Investment), a Scenario, Strategies that
   inherit, replace and explicitly empty the Capital Structure (one leaving a
   Funding Requirement unresolved), and an Investment-scoped structure on the
   visible Investment.
3. Finally every exchange is recorded against that final state -- the P7.7
   builder's own exchanges again (so a later mutation can never make an earlier
   recording stale), then each structure, Strategy list, structured fingerprint
   and analysis, Position perspective list and Position Decision Matrix.

The current tree must answer every one of them identically over a copy of the
same database. Every literal is restated here, so this script imports nothing
but the tree it is pointed at.
"""

from __future__ import annotations

import json
import runpy
import sqlite3
import sys
from pathlib import Path
from typing import Any

root, db_arg, manifest_arg = sys.argv[1:4]
_P7_7_BUILDER = Path(__file__).resolve().with_name("_p7_7_baseline_builder.py")
sys.argv = [str(_P7_7_BUILDER), root, db_arg, manifest_arg, "v11"]
namespace = runpy.run_path(str(_P7_7_BUILDER), run_name="__p7_7_baseline_builder__")

import anchor  # noqa: E402
from anchor.deals import store  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(Path(root).resolve() / "src"), anchor.__file__
assert store._SCHEMA_VERSION == 11, store._SCHEMA_VERSION

db = Path(db_arg)
client = namespace["client"]
ok = namespace["ok"]
visible = namespace["visible"]
QUICK = namespace["QUICK"]


def mezz(position_id: str, scope: dict[str, Any], *, amount: float, maturity_month: int, io_period: int, resolution: str) -> dict[str, Any]:
    return {
        "position_id": position_id,
        "name": "Mezzanine",
        "position_class": "mezzanine_debt",
        "priority": 2,
        "scope": scope,
        "funding": [
            {
                "event_id": f"{position_id}-funding",
                "model_month": 0,
                "sequence": 1,
                "amount_rule": {"kind": "fixed_amount", "amount": amount},
            }
        ],
        "terms": {
            "kind": "debt",
            "interest_rate": 0.12,
            "amortization": 25,
            "io_period": io_period,
            "maturity_month": maturity_month,
            "fees": [
                {
                    "fee_id": f"{position_id}-fee",
                    "description": "Origination fee",
                    "amount": 15_000.0,
                    "model_month": 0,
                    "sequence": 2,
                }
            ],
            "current_pay_rate": 0.12,
            "pik_rate": 0.0,
        },
        "shortfall_resolution": resolution,
    }


# --- 2. Every P7.8B surface a v11 database can hold ---------------------------

structured_deal = store.create_deal("Structured Quick", QUICK, db_path=db)
unit_scope = {"kind": "unit", "unit_id": structured_deal.id}
opted_in = ok(
    "PUT",
    f"/deals/{structured_deal.id}/capital-structure",
    {"positions": [mezz("mezz-a", unit_scope, amount=1_500_000.0, maturity_month=60, io_period=1, resolution="common_equity_contribution")]},
)
structured_id = opted_in["investment_id"]
assert structured_id is not None
structured_scenario = ok("POST", f"/investments/{structured_id}/scenarios", {
    "name": "Downside", "overrides": [
        {"unit_id": structured_deal.id, "target": "exit_cap_rate", "operation": "add", "value": 0.005},
    ],
})
inheriting = ok("POST", f"/investments/{structured_id}/strategies", {
    "name": "Inherit", "overlays": [
        {"unit_id": structured_deal.id, "domain": "acquisition", "content": {"purchase_price": 12_000_000.0, "acquisition_cost_pct": 0.02}},
    ],
})
emptied = ok("POST", f"/investments/{structured_id}/strategies", {
    "name": "No structured capital",
    "root_overlays": [{"domain": "capital_structure", "content": {"positions": []}}],
})
replaced = ok("POST", f"/investments/{structured_id}/strategies", {
    "name": "Bigger mezzanine",
    "root_overlays": [{"domain": "capital_structure", "content": {"positions": [
        mezz("mezz-a", unit_scope, amount=2_000_000.0, maturity_month=60, io_period=2, resolution="common_equity_contribution"),
    ]}}],
})
unresolved = ok("POST", f"/investments/{structured_id}/strategies", {
    "name": "Balloon, unresolved",
    "root_overlays": [{"domain": "capital_structure", "content": {"positions": [
        mezz("mezz-a", unit_scope, amount=1_500_000.0, maturity_month=24, io_period=2, resolution="unresolved"),
    ]}}],
})
structured_strategies = [
    "base",
    *(record["strategy"]["strategy_id"] for record in (inheriting, emptied, replaced, unresolved)),
]
structured_scenarios = ["base", structured_scenario["scenario"]["scenario_id"]]

investment_scope = {"kind": "investment", "unit_id": None}
ok("PUT", f"/investments/{visible.id}/capital-structure", {"positions": [
    mezz("portfolio-mezz", investment_scope, amount=4_000_000.0, maturity_month=60, io_period=1, resolution="common_equity_contribution"),
]})
visible_scenarios = namespace["visible_scenarios"]
plain_deal = namespace["standalone"]["quick"]

# Warm the Project variant cache under every structured variant, so each
# recorded analysis reports a stable ``hit`` rather than the first-ever ``miss``
# (the P7.7 builder warms its one-unit variants the same way).
for strategy_id in structured_strategies:
    for scenario_id in structured_scenarios:
        ok("POST", f"/investments/{structured_id}/structured-variants/{strategy_id}/{scenario_id}/analysis")

# --- 3. Record everything against the final state ------------------------------

exchanges: list[dict[str, object]] = []


def record(method: str, path: str, body: object = None) -> dict:
    payload = ok(method, path, body)
    exchanges.append({"method": method, "path": path, "body": body, "status": 200, "json": payload})
    return payload


for earlier in namespace["exchanges"]:
    record(earlier["method"], earlier["path"], earlier["body"])

record("GET", f"/deals/{plain_deal.id}/capital-structure")
record("GET", f"/deals/{structured_deal.id}/capital-structure")
record("GET", f"/deals/{structured_deal.id}/strategies")
record("GET", f"/investments/{structured_id}")
record("GET", f"/investments/{structured_id}/capital-structure")
record("GET", f"/investments/{structured_id}/strategies")
for strategy_id in structured_strategies[1:]:
    record("GET", f"/investments/{structured_id}/strategies/{strategy_id}")
for strategy_id in structured_strategies:
    for scenario_id in structured_scenarios:
        variant = f"/investments/{structured_id}/structured-variants/{strategy_id}/{scenario_id}"
        record("GET", f"{variant}/fingerprint")
        record("POST", f"{variant}/analysis")
record("GET", f"/investments/{structured_id}/position-perspectives")
record("POST", f"/investments/{structured_id}/position-decision-matrix/mezz-a")
record("POST", f"/investments/{structured_id}/decision-matrix")

record("GET", f"/investments/{visible.id}/capital-structure")
record("GET", f"/investments/{visible.id}/strategies")
for scenario_id in visible_scenarios:
    variant = f"/investments/{visible.id}/structured-variants/base/{scenario_id}"
    record("GET", f"{variant}/fingerprint")
    record("POST", f"{variant}/analysis")
record("GET", f"/investments/{visible.id}/position-perspectives")
record("POST", f"/investments/{visible.id}/position-decision-matrix/portfolio-mezz")

connection = sqlite3.connect(db)
user_version = connection.execute("PRAGMA user_version").fetchone()[0]
connection.close()
manifest = {
    "exchanges": exchanges,
    "user_version": user_version,
    "hidden_investment_id": namespace["hidden_id"],
    "visible_investment_id": visible.id,
    "structured_investment_id": structured_id,
    "structured_deal_id": structured_deal.id,
    "unresolved_strategy_id": unresolved["strategy"]["strategy_id"],
    "emptied_strategy_id": emptied["strategy"]["strategy_id"],
}
Path(manifest_arg).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
