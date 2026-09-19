"""Asset Types 1 baseline builder (not a test module; see
``tests/test_asset_types_1_compatibility_oracle.py``).

Usage: ``python _asset_types_1_v13_baseline_builder.py <repo_root> <db_path> <manifest.json>``

``<repo_root>/src`` is ``main`` at ``2e6ca8e`` -- the schema-v13 tree Asset
Types 1 starts from (PR #42 merged), with every accepted layer through AM1 and
no classification -- exported by ``git archive`` (objects only; no stash and no
second checkout, protocol 11.1/11.2).

Self-contained for the same reason the AM1 builder is: earlier builders assert
which tree they are pointed at, and teaching them a v13 tree would edit another
gate's oracle inputs.

Through the v13 tree's own store and routes it writes a Deal in each of the
three operating modes (Quick and Detailed with a saved analysis), a visible
Investment over two Units, and two Managed Assets -- one carrying the legacy
hand-typed ``property_type`` "Multifamily" and a monthly report, one with none
-- then records every response that tree gives for them. The current tree must
answer every one identically over a copy of the same database, apart from the
two classification keys it adds, which must read ``null`` ("Not specified").
"""

from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
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

assert store._SCHEMA_VERSION == 13, f"expected the v13 tree, got {store._SCHEMA_VERSION}"
assert not (root / "src" / "anchor" / "asset_types.py").exists(), (
    "the baseline tree already has Asset Types 1"
)

# The P7.1/P7.2/AM1 fixtures build every contract this needs and import nothing
# but ``anchor`` itself, so they describe the baseline tree's own shapes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _am1_fixtures as am  # noqa: E402  # type: ignore[import-not-found]
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
# A visible Investment over one Unit (Units must share a hold period and
# reconcile to the transaction price; the subject here is additivity)
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
# Managed Assets -- one with the legacy hand-typed property type and a report
# =============================================================================

legacy_asset = record(
    "POST",
    "/managed-assets",
    {
        "source_deal_id": quick.id,
        "name": None,
        "acquisition_date": "2026-10-01",
        "property_type": "Multifamily",
        "market": "Toronto, ON",
    },
    expect=200,
)
plain_asset = record(
    "POST",
    "/managed-assets",
    {
        "source_deal_id": lease_level.id,
        "name": "Riverbend (owned)",
        "acquisition_date": "2026-11-01",
        "property_type": None,
        "market": None,
    },
    expect=200,
)


def _wire_figures(figures: Any) -> dict[str, float]:
    return dataclasses.asdict(figures)


record(
    "POST",
    f"/managed-assets/{legacy_asset['id']}/reports",
    {
        "reporting_month": am.MARCH.isoformat(),
        "budget": _wire_figures(am.MARCH_BUDGET),
        "actual": _wire_figures(am.MARCH_ACTUAL),
        "commentary": am.MARCH_COMMENTARY,
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
for asset in (legacy_asset, plain_asset):
    record("GET", f"/managed-assets/{asset['id']}")
record("GET", f"/managed-assets/{legacy_asset['id']}/reports")
record("GET", f"/managed-assets/{legacy_asset['id']}/performance/{am.MARCH.isoformat()}")

_quick_body = dataclasses.asdict(QUICK_INPUTS)
_plan_body = dataclasses.asdict(PLAN)
# ``/analyze`` takes Quick's inputs flat; ``/deals/fingerprint`` nests them.
record("POST", "/analyze", {"operating_mode": "quick", **_quick_body, "business_plan": _plan_body})
record(
    "POST",
    "/deals/fingerprint",
    {"operating_mode": "quick", "inputs": _quick_body, "business_plan": _plan_body},
)
_detailed_body = {
    "operating_mode": "detailed",
    "terms": dataclasses.asdict(fx.detailed_terms()),
    "detailed_operating_inputs": dataclasses.asdict(fx.detailed_operating()),
}
record("POST", "/analyze", _detailed_body)
record("POST", "/deals/fingerprint", _detailed_body)

connection = sqlite3.connect(db)
try:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    tables = sorted(
        name
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        if not name.startswith("sqlite_")
    )
finally:
    connection.close()

assert version == 13, version

Path(manifest_arg).write_text(
    json.dumps(
        {
            "user_version": version,
            "tables": tables,
            "quick_deal_id": quick.id,
            "detailed_deal_id": detailed.id,
            "lease_level_deal_id": lease_level.id,
            "visible_investment_id": visible_id,
            "legacy_asset_id": legacy_asset["id"],
            "plain_asset_id": plain_asset["id"],
            "exchanges": exchanges,
        },
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
