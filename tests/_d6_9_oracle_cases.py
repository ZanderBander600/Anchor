"""D6.9 pre-D6 product oracle runner (not a test module; see
``tests/test_d6_9_phase6_closeout.py``, Part F).

Usage: ``python _d6_9_oracle_cases.py <repo_root> <reference.json> <scratch_dir> <out.json>``

Drives the **HTTP product surface** of the tree at ``<repo_root>/src`` -- never
whatever ``anchor`` happens to be installed -- with the D6.9 reference deals as a
pre-D6 client would send them: no ``business_plan`` key anywhere. It records every
response a legacy client can observe, with every float encoded bit-exactly by
``float.hex``:

- ``/analyze``, one-way and two-way ``/sensitivity``, ``/sensitivity/presets`` and
  ``/break-even`` for each mode that offers them;
- ``/deals/fingerprint``;
- the deal lifecycle: create, reopen, update, the provenance-checked analysis and
  sensitivity snapshot writes, reopen with snapshots, duplicate, delete.

When the tree has the D6 Business Plan, the same requests are sent a second time
with an explicit empty plan (``<key>#bp``), which must equal the absent plan.

It must run unchanged against the pre-D6 tree (908499c), so it imports nothing
from ``anchor`` except the app, and probes the plan behind ``ImportError``.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

root = Path(sys.argv[1]).resolve()
reference = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
scratch = Path(sys.argv[3])
out_path = Path(sys.argv[4])

# Before the app is imported: a private database, and no AI credential -- the
# oracle never calls the AI route, and must never be able to.
os.environ["ANCHOR_DB_PATH"] = str(scratch / "oracle.db")
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(root / "src"))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from fastapi.testclient import TestClient  # noqa: E402

from anchor.api import app  # noqa: E402

try:
    import anchor.business_plan  # noqa: E402,F401

    HAS_BP = True
except ImportError:
    HAS_BP = False

client = TestClient(app)
EMPTY_PLAN = {"capital_items": [], "owner_expense_items": []}

#: One varied assumption per mode -- the Part V targets -- and a two-way grid.
ONE_WAY = {
    "quick": {"assumption": "purchase_price", "values": [45_000_000.0, 50_000_000.0, 55_000_000.0]},
    "detailed": {"assumption": "exit_cap_rate", "values": [0.06, 0.065, 0.07]},
    "lease_level": {"assumption": "market_rent_psf", "values": [27.0, 30.0, 33.0]},
}
TWO_WAY = {
    "quick": {
        "row_assumption": "exit_cap_rate",
        "row_values": [0.05, 0.055, 0.06],
        "column_assumption": "purchase_price",
        "column_values": [45_000_000.0, 55_000_000.0],
    },
    "detailed": {
        "row_assumption": "exit_cap_rate",
        "row_values": [0.06, 0.07],
        "column_assumption": "interest_rate",
        "column_values": [0.045, 0.055],
    },
    "lease_level": {
        "row_assumption": "market_rent_psf",
        "row_values": [27.0, 33.0],
        "column_assumption": "exit_cap_rate",
        "column_values": [0.06, 0.07],
    },
}
BREAK_EVEN_TARGETS = {
    "target_levered_irr": 0.08,
    "target_headline_dscr": 1.25,
    "target_equity_multiple": 1.3,
}


def encode(value: Any) -> Any:
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [encode(item) for item in value]
    return value


def deal_state(mode: str, plan: dict | None) -> dict[str, Any]:
    """The mode's deal-state keys (Quick nests ``inputs``), without a name."""

    body = copy.deepcopy(reference["deals"][mode])
    body.pop("name")
    if plan is not None:
        body["business_plan"] = copy.deepcopy(plan)
    return body


def analyze_body(mode: str, plan: dict | None) -> dict[str, Any]:
    body = deal_state(mode, plan)
    if mode == "quick":
        body.pop("operating_mode")
        inputs = body.pop("inputs")
        return {**inputs, **body}
    return body


def strip_identity(value: Any) -> Any:
    """A deal response without what differs between any two runs."""

    if isinstance(value, dict):
        return {
            key: strip_identity(item)
            for key, item in value.items()
            if key not in ("id", "created_at", "updated_at")
        }
    if isinstance(value, list):
        return [strip_identity(item) for item in value]
    return value


def run(plan: dict | None) -> dict[str, Any]:
    output: dict[str, Any] = {}

    def record(key: str, response: Any, *, deal: bool = False) -> Any:
        body = response.json() if response.content else None
        output[key] = {
            "status": response.status_code,
            "body": encode(strip_identity(body) if deal else body),
        }
        return body

    for mode in ("quick", "detailed", "lease_level"):
        state = deal_state(mode, plan)
        analysis = record(f"{mode}:analyze", client.post("/analyze", json=analyze_body(mode, plan)))
        one_way_config = {**ONE_WAY[mode], "metric": "levered_irr"}
        one_way = record(
            f"{mode}:one-way", client.post("/sensitivity/one-way", json={**state, **one_way_config})
        )
        two_way_config = {**TWO_WAY[mode], "metric": "equity_multiple"}
        two_way = record(
            f"{mode}:two-way", client.post("/sensitivity", json={**state, **two_way_config})
        )
        if mode != "lease_level":
            record(f"{mode}:presets", client.post("/sensitivity/presets", json=state))
            record(
                f"{mode}:break-even",
                client.post("/break-even", json={**state, **BREAK_EVEN_TARGETS}),
            )
        fingerprints = record(
            f"{mode}:fingerprint",
            client.post(
                "/deals/fingerprint", json={**state, "deal_context": "Legacy strategy."}
            ),
        )

        deal_body = {**state, "name": f"Legacy {mode}", "deal_context": "Legacy strategy."}
        created = record(f"{mode}:create", client.post("/deals", json=deal_body), deal=True)
        deal_id = created["id"]
        record(f"{mode}:reopen", client.get(f"/deals/{deal_id}"), deal=True)
        record(
            f"{mode}:update",
            client.put(f"/deals/{deal_id}", json={**deal_body, "name": f"Legacy {mode} (renamed)"}),
            deal=True,
        )
        financial = fingerprints["financial_input_fingerprint"]
        if mode != "lease_level":
            record(
                f"{mode}:analysis-snapshot",
                client.put(
                    f"/deals/{deal_id}/analysis-snapshot",
                    json={"analysis_snapshot": analysis, "financial_input_fingerprint": financial},
                ),
                deal=True,
            )
        if mode != "lease_level":
            # Persisted sensitivity is a Lease-Level surface (D5.8A).
            record(f"{mode}:reopen-with-snapshots", client.get(f"/deals/{deal_id}"), deal=True)
            finish(mode, deal_id, record, output)
            continue
        record(
            f"{mode}:one-way-snapshot",
            client.put(
                f"/deals/{deal_id}/sensitivity-snapshot/one-way",
                json={
                    "sensitivity_snapshot": {
                        "configuration": {
                            "metric": "levered_irr",
                            "assumption": ONE_WAY[mode]["assumption"],
                            "values": [str(v) for v in ONE_WAY[mode]["values"]],
                        },
                        "result": one_way,
                    },
                    "financial_input_fingerprint": financial,
                },
            ),
            deal=True,
        )
        record(
            f"{mode}:two-way-snapshot",
            client.put(
                f"/deals/{deal_id}/sensitivity-snapshot/two-way",
                json={
                    "sensitivity_snapshot": {
                        "configuration": {
                            "metric": "equity_multiple",
                            "row_assumption": TWO_WAY[mode]["row_assumption"],
                            "row_values": [str(v) for v in TWO_WAY[mode]["row_values"]],
                            "column_assumption": TWO_WAY[mode]["column_assumption"],
                            "column_values": [str(v) for v in TWO_WAY[mode]["column_values"]],
                        },
                        "result": two_way,
                    },
                    "financial_input_fingerprint": financial,
                },
            ),
            deal=True,
        )
        record(f"{mode}:reopen-with-snapshots", client.get(f"/deals/{deal_id}"), deal=True)
        finish(mode, deal_id, record, output)
    return output


def finish(mode: str, deal_id: str, record: Any, output: dict[str, Any]) -> None:
    """Duplicate, delete, and reopen both."""

    duplicate = record(
        f"{mode}:duplicate", client.post(f"/deals/{deal_id}/duplicate", json={}), deal=True
    )
    record(f"{mode}:delete", client.delete(f"/deals/{deal_id}"))
    gone = record(f"{mode}:reopen-deleted", client.get(f"/deals/{deal_id}"))
    # The 404 names the (random) deal ID; everything else about it must match.
    output[f"{mode}:reopen-deleted"]["body"] = {"detail": gone["detail"].replace(deal_id, "<deal_id>")}
    record(f"{mode}:reopen-duplicate", client.get(f"/deals/{duplicate['id']}"), deal=True)


result: dict[str, Any] = {"_has_bp": HAS_BP, "legacy": run(None)}
if HAS_BP:
    result["explicit_empty"] = run(EMPTY_PLAN)
out_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
