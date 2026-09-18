"""Gate AM1 baseline builder (not a test module; see
``tests/test_am1_compatibility_oracle.py``).

Usage: ``python _am1_v12_baseline_builder.py <repo_root> <db_path> <manifest.json>``

``<repo_root>/src`` is ``main`` at ``63c2ac0`` -- the schema-v12 tree AM1 starts
from, with every accepted layer through P7.9 Stage 3 and no Asset Management --
exported by ``git archive`` (objects only; no stash and no second checkout,
protocol 11.1/11.2).

Deliberately self-contained rather than chained onto the P7.7/P7.9 builders:
those assert which pre-v12 tree they are pointed at, and teaching them a "v12"
gate would mean editing P7.9's own oracle inputs inside an unrelated gate. AM1
changes no P7.9 module, and its oracle should not either.

It writes, through the v12 tree's own store and routes, a database holding a
Deal in each of the three operating modes (one carrying a Business Plan), a
visible Investment with two units, a Scenario, a Strategy, a Capital Structure
and a Partnership -- then records every response that tree gives for them. The
current tree must answer every one identically over a copy of the same database.
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
from anchor.deals import store  # noqa: E402

assert store._SCHEMA_VERSION == 12, f"expected the v12 tree, got {store._SCHEMA_VERSION}"
assert not (root / "src" / "anchor" / "asset_management").exists(), (
    "the baseline tree already has AM1"
)

# The existing P7.1 scenario fixtures build every contract this needs and import
# nothing but ``anchor`` itself, so they describe the baseline tree's own shapes
# rather than a second hand-written copy of them that could drift.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _p7_1_scenario_fixtures as fx  # noqa: E402  # type: ignore[import-not-found]

db = Path(db_arg)
db.parent.mkdir(parents=True, exist_ok=True)

import os  # noqa: E402

os.environ["ANCHOR_DB_PATH"] = str(db)
client = TestClient(api_module.app)

exchanges: list[dict[str, Any]] = []


def record(method: str, path: str, body: Any = None, *, expect: int | None = None) -> Any:
    response = client.request(method, path, json=body)
    if expect is not None and response.status_code != expect:
        raise SystemExit(f"{method} {path} -> {response.status_code}: {response.text}")
    exchanges.append(
        {"method": method, "path": path, "body": body, "status": response.status_code, "json": response.json()}
    )
    return response.json()


# =============================================================================
# Deals, one per operating mode
# =============================================================================

PLAN = fx.business_plan()
QUICK_INPUTS = fx.quick_inputs()

quick = store.create_deal("Harbor Point Apartments", QUICK_INPUTS, business_plan=PLAN, db_path=db)
detailed = store.create_detailed_deal(
    "Westlake Industrial", fx.detailed_terms(), fx.detailed_operating(), db_path=db
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
# An Investment, a Scenario, a Strategy, a Capital Structure, a Partnership
# =============================================================================

visible = record(
    "POST",
    "/investments",
    {
        "name": "Harbor Portfolio",
        # One Unit over the Quick Deal: the Units of an Investment must share a
        # hold period and their allocated prices must reconcile to the
        # transaction price, and the oracle's subject is AM1's additivity, not a
        # multi-unit allocation.
        "transaction_price": QUICK_INPUTS.purchase_price,
        "units": [{"unit_id": quick.id, "label": "Harbor Point", "unit_kind": "property"}],
    },
    expect=200,
)
visible_id = visible["id"]

record(
    "POST",
    f"/deals/{detailed.id}/scenarios",
    {
        "name": "Downside",
        "overrides": [
            {"unit_id": detailed.id, "target": "exit_cap_rate", "operation": "set", "value": 0.07}
        ],
    },
    expect=200,
)

record(
    "POST",
    f"/deals/{detailed.id}/strategies",
    {"name": "Hold", "root_overlays": []},
    expect=200,
)

CAPITAL = {
    "positions": [
        {
            "position_id": "mezz-a",
            "name": "Mezzanine",
            "position_class": "mezzanine_debt",
            "priority": 2,
            "scope": {"kind": "investment", "unit_id": None},
            "funding": [
                {
                    "event_id": "mezz-a-funding",
                    "model_month": 0,
                    "sequence": 1,
                    "amount_rule": {"kind": "fixed_amount", "amount": 1_500_000.0},
                }
            ],
            "terms": {
                "kind": "debt",
                "interest_rate": 0.12,
                "amortization": 25,
                "io_period": 60,
                "maturity_month": 60,
                "fees": [],
                "current_pay_rate": 0.12,
                "pik_rate": 0.0,
            },
            "shortfall_resolution": "common_equity_contribution",
        }
    ]
}
record("PUT", f"/investments/{visible_id}/capital-structure", CAPITAL, expect=200)

PARTNERSHIP = {
    "partners": [
        {"partner_id": "lp", "name": "Limited Partner", "role": "lp", "investor_class": "lp", "commitment_share": 0.9},
        {"partner_id": "gp", "name": "General Partner", "role": "gp", "investor_class": "gp", "commitment_share": 0.1},
    ],
    "contribution_rule": "pro_rata_by_commitment",
    "promote_benchmark": {"shares": [{"partner_id": "gp", "share": 0.1}, {"partner_id": "lp", "share": 0.9}]},
    "promote_participant_ids": ["gp"],
    "tiers": [
        {
            "tier_id": "pref",
            "name": "Preferred Return",
            "sequence": 10,
            "kind": "hurdle",
            "hurdle": {
                "hurdle_subject": {
                    "kind": "partner",
                    "partner_id": "lp",
                    "investor_class": None,
                    "account": None,
                },
                "conditions": [
                    {"condition_id": "pref-8", "kind": "irr", "rate": 0.08, "accrual_convention": "annual_compound", "simple_distribution_order": None}
                ],
                "combinator": "all",
            },
            "catch_up": None,
            "split": {"kind": "explicit", "shares": [{"partner_id": "gp", "share": 0.1}, {"partner_id": "lp", "share": 0.9}]},
        },
        {
            "tier_id": "residual",
            "name": "Residual",
            "sequence": 20,
            "kind": "residual",
            "hurdle": None,
            "catch_up": None,
            "split": {"kind": "explicit", "shares": [{"partner_id": "gp", "share": 0.3}, {"partner_id": "lp", "share": 0.7}]},
        },
    ],
}
record("PUT", f"/investments/{visible_id}/partnership", {"partnership": PARTNERSHIP}, expect=200)

# =============================================================================
# Every response recorded against the final state
# =============================================================================

record("GET", "/health")
record("GET", "/deals")
record("GET", "/investments")
for deal_id in (quick.id, detailed.id, lease_level.id):
    record("GET", f"/deals/{deal_id}")
    record("GET", f"/deals/{deal_id}/scenarios")
    record("GET", f"/deals/{deal_id}/strategies")
    record("GET", f"/deals/{deal_id}/capital-structure")
    record("GET", f"/deals/{deal_id}/partnership")

record("GET", f"/investments/{visible_id}")
record("GET", f"/investments/{visible_id}/details")
record("GET", f"/investments/{visible_id}/scenarios")
record("GET", f"/investments/{visible_id}/strategies")
record("GET", f"/investments/{visible_id}/capital-structure")
record("GET", f"/investments/{visible_id}/partnership")
record("GET", f"/investments/{visible_id}/position-perspectives")
record("GET", "/scenario-targets")
record("GET", "/strategy-targets")

import dataclasses  # noqa: E402

_quick_body = dataclasses.asdict(QUICK_INPUTS)
_plan_body = dataclasses.asdict(PLAN)
record("POST", "/analyze", {"operating_mode": "quick", "inputs": _quick_body, "business_plan": _plan_body})
record("POST", "/deals/fingerprint", {"operating_mode": "quick", "inputs": _quick_body, "business_plan": _plan_body})

connection_version = None
import sqlite3  # noqa: E402

connection = sqlite3.connect(db)
try:
    connection_version = connection.execute("PRAGMA user_version").fetchone()[0]
    tables = sorted(
        name
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        if not name.startswith("sqlite_")
    )
finally:
    connection.close()

assert connection_version == 12, connection_version

Path(manifest_arg).write_text(
    json.dumps(
        {
            "user_version": connection_version,
            "tables": tables,
            "quick_deal_id": quick.id,
            "detailed_deal_id": detailed.id,
            "lease_level_deal_id": lease_level.id,
            "visible_investment_id": visible_id,
            "exchanges": exchanges,
        },
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
