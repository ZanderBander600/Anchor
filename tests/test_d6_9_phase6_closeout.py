"""Phase 6 Gate D6.9 -- cross-mode closeout: one Business Plan through the whole
product.

``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` governs. D6.1-D6.8 each proved
their own layer exhaustively; this module proves the *assembled* system, compactly,
mostly through the HTTP surface a real client uses:

- **Parts B-D, R, S, U, V -- the chain.** One Business Plan, per mode: analyze,
  save, reopen, sensitivity, break-even, AI, snapshot writes, Plan A -> Plan B ->
  exact revert, row reorder, description and category edits, reopen again.
- **Part E** -- the same plan is the same plan in every mode: wire, rows,
  schedule, fingerprint semantics, AI grounding.
- **Part F** -- a legacy client sees exactly what it saw before D6 (908499c),
  end to end over HTTP (runner: ``tests/_d6_9_oracle_cases.py``).
- **Part G** -- a deal with no Business Plan works everywhere.
- **Parts H-P, W** -- the financial oracles and the invariance matrix.
- **Part Q** -- the persistence lifecycle over HTTP.
- **Parts X, Y** -- the Phase 6 guard inventory, one authority per contract and a
  frontend mirror that matches it, and the D6.9 production ledger.

The deals and the plan live in ``tests/fixtures/d6_9_phase6_reference_deals.json``,
which also seeds the human-acceptance database.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import json
import re
import sqlite3
import subprocess
import sys
import zipfile
from collections import defaultdict
from math import isclose
from pathlib import Path
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

import anchor.api as api_module
from anchor.ai import AIAnalysis
from anchor.ai.presentation import _IRR_STATUS_EXPLANATIONS, format_metric_value
from anchor.analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.api import app
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
    parse_business_plan,
)
from anchor.deals import store as deals_store
from anchor.deals.contracts import Deal
from anchor.engine.contracts import AcquisitionResults, IrrStatus, OwnerCapitalSchedule

from _d6_5_fixtures import plan_rows  # type: ignore[import-not-found]
from test_d6_8_ai_business_plan_grounding import (  # type: ignore[import-not-found]
    D6_FIELD_HOMES,
    SECTION,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_REFERENCE_PATH = Path(__file__).resolve().parent / "fixtures" / "d6_9_phase6_reference_deals.json"
REFERENCE: dict[str, Any] = json.loads(_REFERENCE_PATH.read_text(encoding="utf-8"))

MODES = ("quick", "detailed", "lease_level")
HOLD = 5
PLAN_WIRE: dict[str, Any] = REFERENCE["business_plan"]
PLAN = parse_business_plan(PLAN_WIRE)
EMPTY_WIRE: dict[str, Any] = {"capital_items": [], "owner_expense_items": []}
HURDLES = {"target_levered_irr": 0.10, "target_equity_multiple": 1.50, "target_headline_dscr": 1.25}

_CAPITAL = {item["item_id"]: item for item in PLAN_WIRE["capital_items"]}


def _plan(capital: list[dict] = (), expenses: list[dict] = ()) -> dict[str, Any]:  # type: ignore[assignment]
    return {
        "capital_items": copy.deepcopy(list(capital)),
        "owner_expense_items": copy.deepcopy(list(expenses)),
    }


#: Single-channel perturbations of the canonical plan (Parts H-P, W).
PLANS: dict[str, dict[str, Any]] = {
    "empty": EMPTY_WIRE,
    "closing": _plan([_CAPITAL["cap-closing"]]),
    "future": _plan([_CAPITAL["cap-renovation"]]),
    "covered": _plan([{**_CAPITAL["cap-renovation"], "amount": 250_000.0}]),
    "owner_expense": _plan(expenses=PLAN_WIRE["owner_expense_items"]),
    "post_hold": _plan([_CAPITAL["cap-roof"]]),
    "canonical": PLAN_WIRE,
    "no_positive": _plan(
        expenses=[
            {
                "item_id": "oe-no-return",
                "description": "Owner costs that consume every return",
                "category": "other",
                "annual_amount": 25_000_000.0,
                "first_year": 1,
                "last_year": None,
            }
        ]
    ),
}

#: Everything a lender, an appraiser or the sale computes, plus the property layer
#: above owner cash flow -- none of it may move for Project Capital or Owner
#: Expenses (conventions Section 12).
LENDER_EXIT_AND_PROPERTY_FIELDS = (
    "going_in_cap_rate",
    "loan_amount",
    "acquisition_costs",
    "financing_fee",
    "monthly_debt_service",
    "annual_debt_service",
    "remaining_loan_balance",
    "noi_by_year",
    "capex_by_year",
    "tenant_improvements_by_year",
    "leasing_commissions_by_year",
    "exit_noi",
    "exit_value",
    "disposition_costs",
    "net_sale_proceeds",
    "dscr_by_year",
    "headline_dscr",
    "min_dscr",
    "year_1_debt_yield",
    "property_cash_flow_by_year",
)

#: The fifteen result fields D6 appended; a legacy client never saw them.
D6_RESULT_FIELDS = frozenset(
    {
        "closing_project_capital",
        "project_capital_by_year",
        "post_hold_project_capital",
        "owner_expenses_by_year",
        "property_cash_flow_by_year",
        "unlevered_owner_cash_flow_by_year",
        "levered_owner_cash_flow_by_year",
        "total_closing_uses",
        "total_closing_sources",
        "net_additional_equity_requirement_by_year",
        "total_equity_invested",
        "total_cash_returned",
        "total_profit",
        "unlevered_irr_status",
        "levered_irr_status",
    }
)

#: Per mode, the Part V one-way target and a two-way grid.
ONE_WAY = {
    "quick": ("purchase_price", [45_000_000.0, 50_000_000.0, 55_000_000.0]),
    "detailed": ("exit_cap_rate", [0.06, 0.065, 0.07]),
    "lease_level": ("market_rent_psf", [27.0, 30.0, 33.0]),
}
TWO_WAY = {
    "quick": ("exit_cap_rate", [0.05, 0.06], "purchase_price", [45_000_000.0, 55_000_000.0]),
    "detailed": ("exit_cap_rate", [0.06, 0.07], "interest_rate", [0.045, 0.055]),
    "lease_level": ("market_rent_psf", [27.0, 33.0], "exit_cap_rate", [0.06, 0.07]),
}


# =============================================================================
# Requests, typed deals and bits
# =============================================================================


def deal_state(mode: str, plan_wire: dict | None) -> dict[str, Any]:
    """The mode's deal-state body (Quick nests ``inputs``), without a name."""

    body = copy.deepcopy(REFERENCE["deals"][mode])
    body.pop("name")
    if plan_wire is not None:
        body["business_plan"] = copy.deepcopy(plan_wire)
    return body


def deal_body(mode: str, plan_wire: dict | None, **extra: Any) -> dict[str, Any]:
    return {**deal_state(mode, plan_wire), "name": REFERENCE["deals"][mode]["name"], **extra}


def analyze_body(mode: str, plan_wire: dict | None) -> dict[str, Any]:
    body = deal_state(mode, plan_wire)
    if mode == "quick":
        body.pop("operating_mode")
        return {**body.pop("inputs"), **body}
    return body


def results_of(mode: str, response_json: dict[str, Any]) -> dict[str, Any]:
    return response_json if mode == "quick" else response_json["results"]


def purchase_price(mode: str) -> float:
    deal = REFERENCE["deals"][mode]
    return (deal["inputs"] if mode == "quick" else deal["terms"])["purchase_price"]


def direct(deal: Deal, plan: BusinessPlan, assumption: str | None = None, value: float | None = None) -> AcquisitionResults:
    """The independent plan-aware analysis of a stored deal, optionally with one
    assumption replaced -- never through the API or a secondary-analysis runner."""

    change = {} if assumption is None else {assumption: value}
    if deal.inputs is not None:
        return analyze_quick_acquisition_with_business_plan(
            dataclasses.replace(deal.inputs, **change), business_plan=plan
        )
    assert deal.terms is not None
    market_change = change if assumption == "market_rent_psf" else {}
    terms = deal.terms if market_change else dataclasses.replace(deal.terms, **change)
    if deal.detailed_operating_inputs is not None:
        return analyze_detailed_acquisition_with_business_plan(
            terms, deal.detailed_operating_inputs, business_plan=plan
        ).results
    assert deal.market_leasing is not None and deal.property_inputs is not None
    assert deal.operating_inputs is not None and deal.suites is not None and deal.leases is not None
    return analyze_lease_level_acquisition_with_business_plan(
        terms,
        deal.property_inputs,
        deal.suites,
        deal.leases,
        market_leasing=dataclasses.replace(deal.market_leasing, **market_change),
        operating_inputs=deal.operating_inputs,
        business_plan=plan,
    ).results


def bits(value: Any) -> Any:
    """``value`` with every float as ``float.hex`` -- equality is then bitwise,
    sign of zero included."""

    if isinstance(value, float):
        return value.hex()
    if isinstance(value, dict):
        return {key: bits(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [bits(item) for item in value]
    return value


def wire(results: AcquisitionResults) -> dict[str, Any]:
    return json.loads(json.dumps(jsonable_encoder(results)))


def with_item(plan_wire: dict, collection: str, item_id: str, **changes: Any) -> dict[str, Any]:
    edited = copy.deepcopy(plan_wire)
    for item in edited[collection]:
        if item["item_id"] == item_id:
            item.update(changes)
    return edited


def reversed_plan(plan_wire: dict) -> dict[str, Any]:
    return {key: list(reversed(copy.deepcopy(items))) for key, items in plan_wire.items()}


def plan_row_content(db: Path, deal_id: str) -> tuple[list[tuple], list[tuple]]:
    """The stored plan rows, read directly from SQLite, without the deal ID."""

    connection = sqlite3.connect(db)
    try:
        capital = connection.execute(
            "SELECT item_id, ordinal, description, category, month, amount "
            "FROM deal_capital_plan_items WHERE deal_id = ? ORDER BY ordinal",
            (deal_id,),
        ).fetchall()
        expenses = connection.execute(
            "SELECT item_id, ordinal, description, category, annual_amount, first_year, last_year "
            "FROM deal_owner_expense_items WHERE deal_id = ? ORDER BY ordinal",
            (deal_id,),
        ).fetchall()
    finally:
        connection.close()
    return capital, expenses


# =============================================================================
# The AI Analyst, recorded -- no network, no paid call
# =============================================================================

AI_REPORT = AIAnalysis(
    executive_summary="Summary.",
    investment_view="View.",
    strengths=("Strength.",),
    risks=("Risk.",),
    return_drivers=("Driver.",),
    downside_analysis="Downside.",
    capital_structure_analysis="Capital.",
    break_even_analysis="Break-even.",
    questions_to_investigate=("Question.",),
    confidence_notes=("Note.",),
)


class _Recorder:
    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []

    def generate_analysis(self, *, system_prompt: str, user_prompt: str) -> AIAnalysis:
        self.prompts.append((system_prompt, user_prompt))
        return AI_REPORT


_GENERATORS = (
    "generate_ai_analysis",
    "generate_detailed_ai_analysis",
    "generate_lease_level_ai_analysis",
)


@pytest.fixture
def ai_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every AI Analyst call the API makes: the plan it was handed and exactly
    what the model would have read."""

    calls: list[dict[str, Any]] = []
    for name in _GENERATORS:
        real = getattr(api_module, name)

        def _recording(*args: Any, _real: Any = real, **kwargs: Any) -> AIAnalysis:
            recorder = _Recorder()
            report = _real(*args, provider=recorder, **kwargs)
            system_prompt, user_prompt = recorder.prompts[0]
            calls.append(
                {
                    "business_plan": kwargs["business_plan"],
                    "system_prompt": system_prompt,
                    "shown": json.loads(user_prompt[user_prompt.index("{"):]),
                }
            )
            return report

        monkeypatch.setattr(api_module, name, _recording)
    return calls


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "d6-9.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(app)


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


# =============================================================================
# The reference deals themselves (Part A)
# =============================================================================


def test_a_the_reference_plan_is_the_canonical_phase_6_plan() -> None:
    assert PLAN == BusinessPlan(
        capital_items=(
            CapitalPlanItem(
                item_id="cap-closing",
                description="Closing Building Systems",
                category=CapitalItemCategory.BUILDING_SYSTEMS,
                month=0,
                amount=250_000.0,
            ),
            CapitalPlanItem(
                item_id="cap-renovation",
                description="Unit Renovation Program",
                category=CapitalItemCategory.VALUE_ADD_RENOVATION,
                month=18,
                amount=1_000_000.0,
            ),
            CapitalPlanItem(
                item_id="cap-roof",
                description="Future Roof Replacement",
                category=CapitalItemCategory.DEFERRED_MAINTENANCE,
                month=61,
                amount=500_000.0,
            ),
        ),
        owner_expense_items=(
            OwnerExpenseItem(
                item_id="oe-asset-management",
                description="Asset Management",
                category=OwnerExpenseCategory.ASSET_MANAGEMENT,
                annual_amount=50_000.0,
                first_year=1,
                last_year=None,
            ),
            OwnerExpenseItem(
                item_id="oe-legal",
                description="Legal / Partnership",
                category=OwnerExpenseCategory.LEGAL_PARTNERSHIP,
                annual_amount=15_000.0,
                first_year=2,
                last_year=3,
            ),
        ),
    )
    for mode in MODES:
        deal = REFERENCE["deals"][mode]
        assert deal["operating_mode"] == mode
        assert "business_plan" not in deal, "the plan is shared, never per mode"
        assert (deal["inputs"] if mode == "quick" else deal["terms"])["hold_period"] == HOLD


# =============================================================================
# Parts B, C, D, R, S, U, V -- one Business Plan through the whole product
# =============================================================================


def _schedule(results: dict[str, Any]) -> dict[str, Any]:
    return {
        field: results[field]
        for field in (
            "closing_project_capital",
            "project_capital_by_year",
            "post_hold_project_capital",
            "owner_expenses_by_year",
        )
    }


_CANONICAL_SCHEDULE = {
    "closing_project_capital": 250_000.0,
    "project_capital_by_year": [0.0, 1_000_000.0, 0.0, 0.0, 0.0],
    "post_hold_project_capital": 500_000.0,
    "owner_expenses_by_year": [50_000.0, 65_000.0, 65_000.0, 50_000.0, 50_000.0],
}


def _snapshots(deal_json: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deal_json[key]
        for key in (
            "analysis_snapshot",
            "ai_snapshot",
            "one_way_sensitivity_snapshot",
            "two_way_sensitivity_snapshot",
        )
    }


@pytest.mark.parametrize("mode", MODES)
def test_bcd_one_business_plan_travels_the_whole_product(
    client: TestClient, db: Path, ai_calls: list[dict[str, Any]], mode: str
) -> None:
    state = deal_state(mode, PLAN_WIRE)

    # -- Analyze: the deterministic result reflects the plan ------------------
    analysis = ok(client.post("/analyze", json=analyze_body(mode, PLAN_WIRE)))
    results = results_of(mode, analysis)
    assert _schedule(results) == _CANONICAL_SCHEDULE

    # -- Save and reopen: IDs, order, values and a null last_year survive -----
    deal_id = ok(client.post("/deals", json=deal_body(mode, PLAN_WIRE)))["id"]
    reopened = ok(client.get(f"/deals/{deal_id}"))
    assert reopened["business_plan"] == PLAN_WIRE
    assert reopened["business_plan"]["owner_expense_items"][0]["last_year"] is None
    deal = deals_store.get_deal(deal_id)
    assert deal.business_plan == PLAN
    assert plan_rows(db, deal_id) == (3, 2)
    # The API's analysis is the independent plan-aware analysis of the saved deal.
    assert bits(results) == bits(wire(direct(deal, PLAN)))

    fingerprints = ok(client.post("/deals/fingerprint", json=state))
    financial = fingerprints["financial_input_fingerprint"]
    if mode != "lease_level":
        ok(
            client.put(
                f"/deals/{deal_id}/analysis-snapshot",
                json={"analysis_snapshot": analysis, "financial_input_fingerprint": financial},
            )
        )

    # -- Sensitivity (Part V): every cell is the candidate plus the same plan --
    assumption, values = ONE_WAY[mode]
    one_way = ok(
        client.post(
            "/sensitivity/one-way",
            json={**state, "assumption": assumption, "values": values, "metric": "equity_multiple"},
        )
    )
    moved_by_plan = False
    for value, metric in zip(one_way["assumption_values"], one_way["metric_values"], strict=True):
        assert metric == direct(deal, PLAN, assumption, value).equity_multiple
        moved_by_plan |= metric != direct(deal, BusinessPlan(), assumption, value).equity_multiple
    assert moved_by_plan, "the sensitivity ran without the plan"

    row, row_values, column, column_values = TWO_WAY[mode]
    two_way = ok(
        client.post(
            "/sensitivity",
            json={
                **state,
                "row_assumption": row,
                "row_values": row_values,
                "column_assumption": column,
                "column_values": column_values,
                "metric": "levered_irr",
            },
        )
    )
    for row_value, cells in zip(two_way["row_values"], two_way["matrix"], strict=True):
        for column_value, cell in zip(two_way["column_values"], cells, strict=True):
            if row == "market_rent_psf":
                candidate = dataclasses.replace(
                    deal, market_leasing=dataclasses.replace(deal.market_leasing, market_rent_psf=row_value)
                )
                expected = direct(candidate, PLAN, column, column_value)
            else:
                candidate_terms = {row: row_value}
                if deal.inputs is not None:
                    candidate = dataclasses.replace(
                        deal, inputs=dataclasses.replace(deal.inputs, **candidate_terms)
                    )
                else:
                    candidate = dataclasses.replace(
                        deal, terms=dataclasses.replace(deal.terms, **candidate_terms)
                    )
                expected = direct(candidate, PLAN, column, column_value)
            assert cell == expected.levered_irr

    one_way_snapshot = {
        "configuration": {
            "metric": "equity_multiple",
            "assumption": assumption,
            "values": [str(v) for v in values],
        },
        "result": one_way,
    }
    two_way_snapshot = {
        "configuration": {
            "metric": "levered_irr",
            "row_assumption": row,
            "row_values": [str(v) for v in row_values],
            "column_assumption": column,
            "column_values": [str(v) for v in column_values],
        },
        "result": two_way,
    }
    # Persisted sensitivity is a Lease-Level surface (D5.8A); Quick and Detailed
    # persist the analysis snapshot instead.
    if mode == "lease_level":
        for kind, snapshot in (("one-way", one_way_snapshot), ("two-way", two_way_snapshot)):
            ok(
                client.put(
                    f"/deals/{deal_id}/sensitivity-snapshot/{kind}",
                    json={"sensitivity_snapshot": snapshot, "financial_input_fingerprint": financial},
                )
            )

    # -- Break-even (Quick and Detailed): the solved candidate carries the plan --
    if mode != "lease_level":
        break_even = ok(
            client.post(
                "/break-even",
                json={
                    **state,
                    **HURDLES,
                    "target_equity_multiple": 1.10,
                    "return_hurdle_metric": "equity_multiple",
                },
            )
        )
        solved = 0
        for question in break_even.values():
            assert question["baseline_metric_value"] == results[question["metric"]]
            if question["solved_assumption_value"] is not None:
                solved += 1
                candidate = direct(deal, PLAN, question["assumption"], question["solved_assumption_value"])
                assert question["solved_metric_value"] == getattr(candidate, question["metric"])
        assert solved, "no break-even question solved, so the check proved nothing"

    # -- AI (Parts U, S): the same plan, grounded in the deterministic result --
    report = ok(client.post("/ai/analysis", json={**state, **HURDLES}))
    call = ai_calls[-1]
    assert call["business_plan"] == PLAN
    shown = call["shown"]
    grounding = shown[SECTION]
    assert [item["description"] for item in grounding["capital_plan_items"]] == [
        item["description"] for item in PLAN_WIRE["capital_items"]
    ]
    assert [item["description"] for item in grounding["owner_expense_items"]] == [
        item["description"] for item in PLAN_WIRE["owner_expense_items"]
    ]
    for field, (subsection, key) in D6_FIELD_HOMES.items():
        value = results[field]
        expected = (
            [format_metric_value(field, v) for v in value]
            if isinstance(value, list)
            else format_metric_value(field, value)
        )
        assert grounding[subsection][key] == expected, field
    for series in ("levered_irr", "unlevered_irr"):
        status = IrrStatus(results[f"{series}_status"])
        assert shown["irr_status"][series]["status"] == status.value
        assert shown["irr_status"][series]["explanation"] == _IRR_STATUS_EXPLANATIONS[status]
    ok(
        client.put(
            f"/deals/{deal_id}/ai-snapshot",
            json={"ai_snapshot": report, "ai_context_fingerprint": fingerprints["ai_context_fingerprint"]},
        )
    )

    # -- Reopen: every derived result is current and exactly what was produced --
    current = _snapshots(ok(client.get(f"/deals/{deal_id}")))
    lease_level = mode == "lease_level"
    expected_current = {
        "analysis_snapshot": None if lease_level else analysis,
        "ai_snapshot": report,
        "one_way_sensitivity_snapshot": one_way_snapshot if lease_level else None,
        "two_way_sensitivity_snapshot": two_way_snapshot if lease_level else None,
    }
    assert current == expected_current
    stale = {key: None for key in expected_current}

    # -- Part R: Plan A -> B -> exact revert, reorder, narrative edits ---------
    def save(plan_wire: dict) -> dict[str, Any]:
        return ok(client.put(f"/deals/{deal_id}", json=deal_body(mode, plan_wire)))

    def fingerprint(plan_wire: dict) -> str:
        return ok(client.post("/deals/fingerprint", json=deal_state(mode, plan_wire)))[
            "financial_input_fingerprint"
        ]

    plan_b = with_item(PLAN_WIRE, "capital_items", "cap-renovation", amount=1_200_000.0)
    save(plan_b)
    assert _snapshots(ok(client.get(f"/deals/{deal_id}"))) == stale
    assert fingerprint(plan_b) != financial
    moved = results_of(mode, ok(client.post("/analyze", json=analyze_body(mode, plan_b))))
    assert moved["project_capital_by_year"][1] == 1_200_000.0

    save(PLAN_WIRE)
    assert _snapshots(ok(client.get(f"/deals/{deal_id}"))) == expected_current

    reordered = reversed_plan(PLAN_WIRE)
    assert fingerprint(reordered) == financial
    save(reordered)
    reopened = ok(client.get(f"/deals/{deal_id}"))
    assert reopened["business_plan"] == reordered, "the analyst's row order is kept"
    assert _snapshots(reopened) == expected_current

    for edit in (
        with_item(PLAN_WIRE, "capital_items", "cap-renovation", description="Unit Renovation (revised)"),
        with_item(PLAN_WIRE, "capital_items", "cap-renovation", category="other"),
        with_item(PLAN_WIRE, "owner_expense_items", "oe-legal", description="Legal"),
        with_item(PLAN_WIRE, "owner_expense_items", "oe-legal", category="other"),
    ):
        assert fingerprint(edit) != financial
        save(edit)
        assert _snapshots(ok(client.get(f"/deals/{deal_id}"))) == stale

    # -- Restore, reopen again: no plan loss, everything current ---------------
    save(PLAN_WIRE)
    final = ok(client.get(f"/deals/{deal_id}"))
    assert final["business_plan"] == PLAN_WIRE
    assert _snapshots(final) == expected_current
    assert plan_rows(db, deal_id) == (3, 2), "no duplicated capital rows"


@pytest.mark.parametrize("mode", ("detailed", "lease_level"))
def test_cd_the_plan_never_reaches_the_operating_statement(client: TestClient, mode: str) -> None:
    """Part C / D: Owner Expenses are not operating expenses and Project Capital
    is not TI/LC -- the mode's own operating projection is byte-identical with
    and without the plan."""

    projection = "operating_projection" if mode == "detailed" else "annual_projection"
    empty = ok(client.post("/analyze", json=analyze_body(mode, EMPTY_WIRE)))
    material = ok(client.post("/analyze", json=analyze_body(mode, PLAN_WIRE)))
    assert bits(material[projection]) == bits(empty[projection])


# =============================================================================
# Part E -- the same Business Plan in every mode
# =============================================================================


def test_e_one_business_plan_is_the_same_plan_in_every_mode(
    client: TestClient, db: Path, ai_calls: list[dict[str, Any]]
) -> None:
    ids = {mode: ok(client.post("/deals", json=deal_body(mode, PLAN_WIRE)))["id"] for mode in MODES}

    # The same wire contract back, and the same stored rows.
    for mode in MODES:
        assert ok(client.get(f"/deals/{ids[mode]}"))["business_plan"] == PLAN_WIRE
        assert deals_store.get_deal(ids[mode]).business_plan == PLAN
    rows = {mode: plan_row_content(db, ids[mode]) for mode in MODES}
    assert rows["quick"] == rows["detailed"] == rows["lease_level"]
    assert [row[0] for row in rows["quick"][0]] == ["cap-closing", "cap-renovation", "cap-roof"]
    assert rows["quick"][1][0][-1] is None, "a null last_year is stored as NULL"

    # The same resolved schedule; operations differ, the plan does not.
    analyses = {mode: results_of(mode, ok(client.post("/analyze", json=analyze_body(mode, PLAN_WIRE)))) for mode in MODES}
    for mode in MODES:
        assert _schedule(analyses[mode]) == _CANONICAL_SCHEDULE
    assert len({tuple(analyses[mode]["noi_by_year"]) for mode in MODES}) == 3

    # The same fingerprint semantics.
    for mode in MODES:
        def fp(plan_wire: dict | None, mode: str = mode) -> str:
            return ok(client.post("/deals/fingerprint", json=deal_state(mode, plan_wire)))[
                "financial_input_fingerprint"
            ]

        base = fp(PLAN_WIRE)
        assert fp(reversed_plan(PLAN_WIRE)) == base
        assert fp(with_item(PLAN_WIRE, "capital_items", "cap-roof", description="Roof")) != base
        assert fp(with_item(PLAN_WIRE, "capital_items", "cap-roof", category="other")) != base
        assert fp(EMPTY_WIRE) == fp(None) != base

    # The same AI grounding: only the figures the modes' operations move differ.
    groundings = {}
    for mode in MODES:
        ok(client.post("/ai/analysis", json={**deal_state(mode, PLAN_WIRE), **HURDLES}))
        assert ai_calls[-1]["business_plan"] == PLAN
        groundings[mode] = {
            key: value
            for key, value in ai_calls[-1]["shown"][SECTION].items()
            if key
            not in ("owner_cash_flow", "sources_and_uses_at_closing", "equity_requirements", "project_returns")
        }
    assert groundings["quick"] == groundings["detailed"] == groundings["lease_level"]


# =============================================================================
# Part F -- a legacy client sees exactly what it saw before D6 (908499c)
# =============================================================================

_PRE_D6 = "908499c"
_RUNNER = Path(__file__).resolve().parent / "_d6_9_oracle_cases.py"
#: Keys D6 appended to a response a legacy client already received.
_ADDITIVE_KEYS = D6_RESULT_FIELDS | {"business_plan"}


def _run_oracle(root: Path, scratch: Path, out: Path) -> dict[str, Any]:
    scratch.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, str(_RUNNER), str(root), str(_REFERENCE_PATH), str(scratch), str(out)],
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def product_oracle(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, dict]:
    scratch = tmp_path_factory.mktemp("d6_9_oracle")
    archive = scratch / "pre_d6.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _PRE_D6, "src"],
        check=True,
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "pre_d6")
    baseline = _run_oracle(scratch / "pre_d6", scratch / "pre_d6_db", scratch / "pre_d6.json")
    current = _run_oracle(_PROJECT_ROOT, scratch / "current_db", scratch / "current.json")
    return baseline, current


def _differences(before: Any, after: Any, path: str = "") -> tuple[list[tuple], int]:
    """Every way ``after`` differs from ``before``, except a D6-appended key; and
    how many leaves were compared."""

    if isinstance(before, dict):
        if not isinstance(after, dict):
            return [(path, "not an object")], 0
        found: list[tuple] = []
        compared = 0
        for key in sorted(set(before) | set(after)):
            if key not in after:
                found.append((f"{path}.{key}", "missing"))
            elif key not in before:
                if key not in _ADDITIVE_KEYS:
                    found.append((f"{path}.{key}", "unexpected new key"))
            else:
                sub_found, sub_compared = _differences(before[key], after[key], f"{path}.{key}")
                found.extend(sub_found)
                compared += sub_compared
        return found, compared
    if isinstance(before, list):
        if not isinstance(after, list) or len(after) != len(before):
            return [(path, "length")], 0
        found, compared = [], 0
        for index, (b, a) in enumerate(zip(before, after)):
            sub_found, sub_compared = _differences(b, a, f"{path}[{index}]")
            found.extend(sub_found)
            compared += sub_compared
        return found, compared
    return ([] if before == after else [(path, before, after)]), 1


def test_f_the_two_sides_are_the_pre_d6_and_the_phase_6_trees(product_oracle: tuple[dict, dict]) -> None:
    baseline, current = product_oracle
    assert baseline["_has_bp"] is False, "the baseline side is not the pre-D6 tree"
    assert current["_has_bp"] is True
    assert set(baseline) == {"_has_bp", "legacy"}
    # Every request was a real, accepted request on the pre-D6 tree -- a 422 on
    # both sides would compare equal and prove nothing.
    for key, response in baseline["legacy"].items():
        expected = {"delete": 204, "reopen-deleted": 404}.get(key.split(":")[1], 200)
        assert response["status"] == expected, (key, response)
    assert len(baseline["legacy"]) == 44


@pytest.mark.parametrize("variant", ("legacy", "explicit_empty"))
def test_f_every_legacy_response_is_bit_identical_to_908499c(
    product_oracle: tuple[dict, dict], variant: str
) -> None:
    """Analysis, sensitivity, presets, break-even, fingerprints and the whole deal
    lifecycle, in every mode: every pre-D6 field of every response, to the bit. An
    absent plan and an explicit empty plan are both the pre-D6 deal."""

    baseline, current = product_oracle
    found, compared = _differences(baseline["legacy"], current[variant])
    assert not found, found[:20]
    assert compared > 3000, compared


def test_f_the_only_additions_are_the_d6_fields_and_they_are_neutral(
    product_oracle: tuple[dict, dict],
) -> None:
    _, current = product_oracle
    zero = (0.0).hex()
    for mode in MODES:
        analysis = current["legacy"][f"{mode}:analyze"]["body"]
        results = results_of(mode, analysis)
        assert D6_RESULT_FIELDS <= set(results)
        assert results["closing_project_capital"] == zero
        assert results["post_hold_project_capital"] == zero
        assert results["project_capital_by_year"] == [zero] * HOLD
        assert results["owner_expenses_by_year"] == [zero] * HOLD
        assert results["unlevered_owner_cash_flow_by_year"] == results["property_cash_flow_by_year"]
        for key in (f"{mode}:create", f"{mode}:reopen", f"{mode}:reopen-duplicate"):
            assert current["legacy"][key]["body"]["business_plan"] == EMPTY_WIRE


def test_f_the_comparison_detects_a_single_changed_bit(product_oracle: tuple[dict, dict]) -> None:
    """Self-test: the oracle cannot pass vacuously -- one ulp in one reopened
    deal's stored sensitivity cell is found, and nothing else is."""

    baseline, current = product_oracle
    tampered = json.loads(json.dumps(current["legacy"]))
    cells = tampered["lease_level:reopen-with-snapshots"]["body"]["two_way_sensitivity_snapshot"]["result"]["matrix"]
    value = float.fromhex(cells[1][0])
    cells[1][0] = (value + abs(value) * 2.0**-52).hex()
    found, _ = _differences(baseline["legacy"], tampered)
    assert [entry[0] for entry in found] == [
        ".lease_level:reopen-with-snapshots.body.two_way_sensitivity_snapshot.result.matrix[1][0]"
    ]
    tampered_key = json.loads(json.dumps(current["legacy"]))
    tampered_key["quick:analyze"]["body"]["capital_plan_total"] = 0.0
    assert _differences(baseline["legacy"], tampered_key)[0] == [
        (".quick:analyze.body.capital_plan_total", "unexpected new key")
    ]


# =============================================================================
# Part G -- a deal with no Business Plan works everywhere
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_g_a_deal_with_no_business_plan_works_everywhere(
    client: TestClient, db: Path, ai_calls: list[dict[str, Any]], mode: str
) -> None:
    legacy = deal_state(mode, None)
    results = results_of(mode, ok(client.post("/analyze", json=analyze_body(mode, None))))
    assert _schedule(results) == {
        "closing_project_capital": 0.0,
        "project_capital_by_year": [0.0] * HOLD,
        "post_hold_project_capital": 0.0,
        "owner_expenses_by_year": [0.0] * HOLD,
    }
    assert isclose(
        results["total_equity_invested"],
        results["initial_equity"] + sum(results["net_additional_equity_requirement_by_year"]),
        rel_tol=1e-12,
    )

    deal_id = ok(client.post("/deals", json=deal_body(mode, None)))["id"]
    assert ok(client.get(f"/deals/{deal_id}"))["business_plan"] == EMPTY_WIRE
    assert deals_store.get_deal(deal_id).business_plan == BusinessPlan()
    assert plan_rows(db, deal_id) == (0, 0)

    fingerprint = ok(client.post("/deals/fingerprint", json=legacy))
    assert fingerprint == ok(client.post("/deals/fingerprint", json=deal_state(mode, EMPTY_WIRE)))

    assumption, values = ONE_WAY[mode]
    ok(client.post("/sensitivity/one-way", json={**legacy, "assumption": assumption, "values": values, "metric": "levered_irr"}))
    if mode != "lease_level":
        ok(client.post("/break-even", json={**legacy, **HURDLES}))

    ok(client.post("/ai/analysis", json={**legacy, **HURDLES}))
    call = ai_calls[-1]
    assert call["business_plan"] == BusinessPlan()
    assert SECTION not in call["shown"], "no Business Plan section for a deal with no plan"
    # Both IRRs are reported for these deals, so there is no N/A reason to give
    # either (Part M covers an unreported IRR).
    assert results["levered_irr_status"] == results["unlevered_irr_status"] == IrrStatus.DEFINED.value
    assert "irr_status" not in call["shown"]


# =============================================================================
# Parts H-P, W -- the financial oracles and the invariance matrix
# =============================================================================


@pytest.fixture(scope="module")
def analyzed(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """``/analyze`` for (mode, plan name), each computed once."""

    cache: dict[tuple[str, str], dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ANCHOR_DB_PATH", str(tmp_path_factory.mktemp("d6_9_matrix") / "matrix.db"))
        matrix_client = TestClient(app)

        def get(mode: str, plan_name: str) -> dict[str, Any]:
            if (mode, plan_name) not in cache:
                cache[mode, plan_name] = ok(
                    matrix_client.post("/analyze", json=analyze_body(mode, PLANS[plan_name]))
                )
            return cache[mode, plan_name]

        yield get


def _pair(analyzed: Any, mode: str, plan_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return results_of(mode, analyzed(mode, "empty")), results_of(mode, analyzed(mode, plan_name))


def _close(a: float, b: float) -> bool:
    return isclose(a, b, rel_tol=0.0, abs_tol=1e-6)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "plan_name", ("closing", "future", "covered", "owner_expense", "post_hold", "canonical")
)
def test_w_lender_exit_and_property_figures_never_move(analyzed: Any, mode: str, plan_name: str) -> None:
    """Part W, the invariance half: NOI, DSCR (headline and minimum), debt yield,
    the loan, debt service, the remaining balance, exit NOI, gross exit value,
    disposition costs and net sale proceeds -- and the operating statement -- are
    bit-identical to the no-plan deal under every single-channel perturbation."""

    base, moved = _pair(analyzed, mode, plan_name)
    for field in LENDER_EXIT_AND_PROPERTY_FIELDS:
        assert bits(moved[field]) == bits(base[field]), field
    projection = {"detailed": "operating_projection", "lease_level": "annual_projection"}.get(mode)
    if projection:
        assert bits(analyzed(mode, plan_name)[projection]) == bits(analyzed(mode, "empty")[projection])


@pytest.mark.parametrize("mode", MODES)
def test_w_the_material_plan_moves_owner_and_equity_economics(analyzed: Any, mode: str) -> None:
    """Part W, the moving half: owner cash flow, equity cash flow, the equity
    multiple, cash-on-cash, cash yield, TEI/TCR/Profit and the levered IRR (its
    value or its status) all move, and in the economic direction."""

    base, moved = _pair(analyzed, mode, "canonical")
    for field in (
        "unlevered_owner_cash_flow_by_year",
        "levered_owner_cash_flow_by_year",
        "unlevered_cash_flows",
        "levered_cash_flows",
        "equity_multiple",
        "levered_cash_on_cash_by_year",
        "unlevered_cash_yield_by_year",
        "total_equity_invested",
        "total_cash_returned",
        "total_profit",
    ):
        assert bits(moved[field]) != bits(base[field]), field
    assert (moved["levered_irr"], moved["levered_irr_status"]) != (base["levered_irr"], base["levered_irr_status"])
    assert moved["equity_multiple"] < base["equity_multiple"]
    assert moved["total_profit"] < base["total_profit"]


@pytest.mark.parametrize("mode", MODES)
def test_h_closing_project_capital_is_equity_funded_at_t0(analyzed: Any, mode: str) -> None:
    base, moved = _pair(analyzed, mode, "closing")
    assert moved["closing_project_capital"] == 250_000.0
    assert moved["loan_amount"] == base["loan_amount"]
    assert _close(moved["initial_equity"] - base["initial_equity"], 250_000.0)
    assert _close(base["unlevered_cash_flows"][0] - moved["unlevered_cash_flows"][0], 250_000.0)
    assert _close(moved["total_closing_uses"] - base["total_closing_uses"], 250_000.0)
    assert _close(moved["total_closing_sources"], moved["total_closing_uses"])
    assert moved["levered_cash_flows"][0] == -moved["initial_equity"]
    # Nothing during the hold moves: it is a closing use only.
    for field in ("unlevered_owner_cash_flow_by_year", "levered_owner_cash_flow_by_year", "project_capital_by_year"):
        assert bits(moved[field]) == bits(base[field]), field


@pytest.mark.parametrize("mode", MODES)
def test_i_future_project_capital_enters_its_hold_year_only(analyzed: Any, mode: str) -> None:
    base, moved = _pair(analyzed, mode, "future")
    assert moved["project_capital_by_year"] == [0.0, 1_000_000.0, 0.0, 0.0, 0.0]
    # Never a closing use, never pre-funded.
    for field in ("closing_project_capital", "initial_equity", "total_closing_uses", "total_closing_sources"):
        assert bits(moved[field]) == bits(base[field]), field
    for year in range(HOLD):
        reduction = 1_000_000.0 if year == 1 else 0.0
        for series in ("unlevered_owner_cash_flow_by_year", "levered_owner_cash_flow_by_year"):
            assert _close(base[series][year] - moved[series][year], reduction), (series, year)
    assert moved["levered_cash_flows"][2] != base["levered_cash_flows"][2]
    assert moved["equity_multiple"] != base["equity_multiple"]
    # Additional equity appears only where the annual net equity cash flow is negative.
    for year in range(1, HOLD + 1):
        assert moved["net_additional_equity_requirement_by_year"][year - 1] == max(
            -moved["levered_cash_flows"][year], 0.0
        )


@pytest.mark.parametrize("mode", MODES)
def test_j_owner_expenses_reduce_owner_cash_flow_and_returns_only(analyzed: Any, mode: str) -> None:
    base, moved = _pair(analyzed, mode, "owner_expense")
    assert moved["owner_expenses_by_year"] == [50_000.0, 65_000.0, 65_000.0, 50_000.0, 50_000.0]
    for year, expense in enumerate(moved["owner_expenses_by_year"]):
        for series in ("unlevered_owner_cash_flow_by_year", "levered_owner_cash_flow_by_year"):
            assert _close(base[series][year] - moved[series][year], expense), (series, year)
        assert moved["levered_cash_on_cash_by_year"][year] < base["levered_cash_on_cash_by_year"][year]
    assert moved["equity_multiple"] < base["equity_multiple"]
    assert moved["total_profit"] < base["total_profit"]


@pytest.mark.parametrize("mode", MODES)
def test_k_post_hold_capital_moves_only_its_disclosure(analyzed: Any, mode: str) -> None:
    """Hold cash flows, IRR, EM, TEI/TCR/Profit, exit, NSP and closing Sources &
    Uses are all bit-identical; only the disclosure moves."""

    base, moved = _pair(analyzed, mode, "post_hold")
    changed = {field for field in moved if bits(moved[field]) != bits(base[field])}
    assert changed == {"post_hold_project_capital"}
    assert moved["post_hold_project_capital"] == 500_000.0


@pytest.mark.parametrize("mode", ("quick", "detailed"))
def test_l_multiple_sign_changes_leave_irr_unreported_and_every_other_return(
    analyzed: Any, client: TestClient, mode: str
) -> None:
    results = results_of(mode, analyzed(mode, "canonical"))
    flows = [cf for cf in results["levered_cash_flows"] if cf != 0.0]
    assert sum(1 for a, b in zip(flows, flows[1:]) if (a < 0) != (b < 0)) > 1
    assert results["levered_irr"] is None
    assert results["levered_irr_status"] == IrrStatus.MULTIPLE_SIGN_CHANGES.value
    assert results["equity_multiple"] is not None
    assert _close(results["total_profit"], results["total_cash_returned"] - results["total_equity_invested"])

    # Break-even keeps its undefined-IRR policy: an IRR hurdle is measured against
    # an unreported base IRR, and an unreported IRR never qualifies a candidate.
    break_even = ok(client.post("/break-even", json={**deal_state(mode, PLAN_WIRE), **HURDLES}))
    irr_questions = [q for q in break_even.values() if q["metric"] == "levered_irr"]
    assert irr_questions
    for question in irr_questions:
        assert question["baseline_metric_value"] is None
        if question["solved_assumption_value"] is not None:
            assert question["solved_metric_value"] is not None


def test_m_no_positive_cash_flow_agrees_across_result_snapshot_and_ai(
    analyzed: Any, client: TestClient, ai_calls: list[dict[str, Any]]
) -> None:
    """Part M: a non-multiple-sign undefined IRR, through the result, a snapshot
    round trip (rehydrated to the enum) and the AI grounding."""

    analysis = analyzed("quick", "no_positive")
    assert analysis["levered_irr"] is None
    assert analysis["levered_irr_status"] == IrrStatus.NO_POSITIVE_CASH_FLOW.value
    assert analysis["equity_multiple"] == 0.0
    assert analysis["total_cash_returned"] == 0.0
    assert analysis["total_profit"] == -analysis["total_equity_invested"] < 0.0

    plan = PLANS["no_positive"]
    deal_id = ok(client.post("/deals", json=deal_body("quick", plan)))["id"]
    fingerprints = ok(client.post("/deals/fingerprint", json=deal_state("quick", plan)))
    ok(
        client.put(
            f"/deals/{deal_id}/analysis-snapshot",
            json={
                "analysis_snapshot": analysis,
                "financial_input_fingerprint": fingerprints["financial_input_fingerprint"],
            },
        )
    )
    assert ok(client.get(f"/deals/{deal_id}"))["analysis_snapshot"] == analysis
    snapshot = deals_store.get_deal(deal_id).analysis_snapshot
    assert isinstance(snapshot, AcquisitionResults)
    assert snapshot.levered_irr_status is IrrStatus.NO_POSITIVE_CASH_FLOW

    ok(client.post("/ai/analysis", json={**deal_state("quick", plan), **HURDLES}))
    shown = ai_calls[-1]["shown"]["irr_status"]["levered_irr"]
    assert shown["status"] == IrrStatus.NO_POSITIVE_CASH_FLOW.value
    assert shown["explanation"] == _IRR_STATUS_EXPLANATIONS[IrrStatus.NO_POSITIVE_CASH_FLOW]


@pytest.mark.parametrize("mode", ("quick", "detailed"))
def test_n_additional_equity_is_the_annual_net_deficit_not_gross_capital(analyzed: Any, mode: str) -> None:
    future = results_of(mode, analyzed(mode, "future"))
    deficit = future["net_additional_equity_requirement_by_year"]
    assert deficit[1] == -future["levered_cash_flows"][2] > 0.0
    assert deficit[1] < future["project_capital_by_year"][1] == 1_000_000.0, "net, never gross"
    assert deficit[0] == deficit[2] == deficit[3] == deficit[4] == 0.0

    covered = results_of(mode, analyzed(mode, "covered"))
    assert covered["project_capital_by_year"][1] == 250_000.0
    assert covered["net_additional_equity_requirement_by_year"] == [0.0] * HOLD
    assert covered["total_equity_invested"] == covered["initial_equity"]

    for plan_name in ("future", "canonical"):
        results = results_of(mode, analyzed(mode, plan_name))
        assert isclose(
            results["total_equity_invested"],
            results["initial_equity"] + sum(results["net_additional_equity_requirement_by_year"]),
            rel_tol=1e-12,
        )


def test_n_lease_level_additional_equity_nets_every_channel_in_its_year(analyzed: Any) -> None:
    results = results_of("lease_level", analyzed("lease_level", "canonical"))
    year_2 = 1
    gross = sum(
        results[field][year_2]
        for field in (
            "capex_by_year",
            "tenant_improvements_by_year",
            "leasing_commissions_by_year",
            "project_capital_by_year",
            "owner_expenses_by_year",
        )
    )
    requirement = results["net_additional_equity_requirement_by_year"][year_2]
    assert requirement == -results["levered_cash_flows"][year_2 + 1] > 0.0
    assert requirement < gross + results["annual_debt_service"][year_2], "NOI nets against it"


@pytest.mark.parametrize("mode", MODES)
def test_o_sources_and_uses_are_the_engines_closing_figures(analyzed: Any, mode: str) -> None:
    results = results_of(mode, analyzed(mode, "canonical"))
    assert _close(
        results["total_closing_uses"],
        purchase_price(mode)
        + results["acquisition_costs"]
        + results["financing_fee"]
        + results["closing_project_capital"],
    )
    assert _close(results["total_closing_sources"], results["loan_amount"] + results["initial_equity"])
    assert _close(results["total_closing_uses"], results["total_closing_sources"])
    # Future and post-hold capital are never closing uses: the canonical plan's
    # closing figures are exactly the closing-only plan's.
    closing_only = results_of(mode, analyzed(mode, "closing"))
    for field in ("total_closing_uses", "total_closing_sources", "initial_equity", "loan_amount"):
        assert bits(results[field]) == bits(closing_only[field]), field


@pytest.mark.parametrize("mode", MODES)
def test_p_each_capital_channel_is_its_own_series(analyzed: Any, mode: str) -> None:
    base, results = _pair(analyzed, mode, "canonical")
    reserve = (
        REFERENCE["deals"][mode]["inputs"] if mode == "quick" else REFERENCE["deals"][mode]["terms"]
    )["annual_capex_reserve"]
    assert results["capex_by_year"] == [reserve] * HOLD, "the reserve stays the reserve alone"
    for field in ("tenant_improvements_by_year", "leasing_commissions_by_year"):
        assert bits(results[field]) == bits(base[field]), "TI / LC are never Project Capital"
    assert sum(results["project_capital_by_year"]) == 1_000_000.0, "post-hold stays outside the hold rows"
    for year in range(HOLD):
        assert _close(
            results["property_cash_flow_by_year"][year],
            results["noi_by_year"][year]
            - results["capex_by_year"][year]
            - results["tenant_improvements_by_year"][year]
            - results["leasing_commissions_by_year"][year],
        )
        assert _close(
            results["unlevered_owner_cash_flow_by_year"][year],
            results["property_cash_flow_by_year"][year]
            - results["project_capital_by_year"][year]
            - results["owner_expenses_by_year"][year],
        )
        assert _close(
            results["levered_owner_cash_flow_by_year"][year],
            results["unlevered_owner_cash_flow_by_year"][year] - results["annual_debt_service"][year],
        )
    if mode == "lease_level":
        # Year 2 carries all four owner channels at once, each visible separately.
        for field in (
            "tenant_improvements_by_year",
            "leasing_commissions_by_year",
            "project_capital_by_year",
            "owner_expenses_by_year",
        ):
            assert results[field][1] > 0.0, field


# =============================================================================
# Part Q -- the persistence lifecycle over HTTP
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_q_create_reopen_update_duplicate_delete(client: TestClient, db: Path, mode: str) -> None:
    deal_id = ok(client.post("/deals", json=deal_body(mode, PLAN_WIRE)))["id"]
    assert ok(client.get(f"/deals/{deal_id}"))["business_plan"] == PLAN_WIRE

    plan_b = reversed_plan(PLAN_WIRE)
    plan_b["capital_items"].append(
        {
            "item_id": "cap-lobby",
            "description": "Lobby refresh",
            "category": "exterior_common_area",
            "month": 30,
            "amount": 75_000.0,
        }
    )
    ok(client.put(f"/deals/{deal_id}", json=deal_body(mode, plan_b)))
    assert ok(client.get(f"/deals/{deal_id}"))["business_plan"] == plan_b
    assert plan_rows(db, deal_id) == (4, 2)

    # An unrelated update that carries the plan keeps it, IDs and all.
    ok(client.put(f"/deals/{deal_id}", json=deal_body(mode, plan_b, name="Renamed", deal_context="New thesis.")))
    assert ok(client.get(f"/deals/{deal_id}"))["business_plan"] == plan_b

    duplicate_id = ok(client.post(f"/deals/{deal_id}/duplicate", json={}))["id"]
    assert duplicate_id != deal_id
    assert ok(client.get(f"/deals/{duplicate_id}"))["business_plan"] == plan_b
    original, duplicate = deals_store.get_deal(deal_id), deals_store.get_deal(duplicate_id)
    assert bits(wire(direct(duplicate, duplicate.business_plan))) == bits(
        wire(direct(original, original.business_plan))
    ), "the duplicate is financially identical"

    assert client.delete(f"/deals/{deal_id}").status_code == 204
    assert plan_rows(db, deal_id) == (0, 0), "no orphan plan rows"
    assert plan_rows(db, duplicate_id) == (4, 2), "the duplicate owns its own rows"

    ok(client.put(f"/deals/{duplicate_id}", json=deal_body(mode, EMPTY_WIRE)))
    assert plan_rows(db, duplicate_id) == (0, 0), "an empty-plan save clears the rows intentionally"
    assert ok(client.get(f"/deals/{duplicate_id}"))["business_plan"] == EMPTY_WIRE


# =============================================================================
# Part S -- the AI report version
# =============================================================================


def test_s_ai_reports_are_version_2_and_the_version_never_reaches_a_fingerprint(
    client: TestClient, db: Path, ai_calls: list[dict[str, Any]]
) -> None:
    assert deals_store._AI_SNAPSHOT_SCHEMA_VERSION == 2

    state = deal_state("quick", PLAN_WIRE)
    deal_id = ok(client.post("/deals", json=deal_body("quick", PLAN_WIRE)))["id"]
    fingerprints = ok(client.post("/deals/fingerprint", json=state))
    analysis = ok(client.post("/analyze", json=analyze_body("quick", PLAN_WIRE)))
    ok(
        client.put(
            f"/deals/{deal_id}/analysis-snapshot",
            json={"analysis_snapshot": analysis, "financial_input_fingerprint": fingerprints["financial_input_fingerprint"]},
        )
    )
    report = ok(client.post("/ai/analysis", json={**state, **HURDLES}))
    ok(
        client.put(
            f"/deals/{deal_id}/ai-snapshot",
            json={"ai_snapshot": report, "ai_context_fingerprint": fingerprints["ai_context_fingerprint"]},
        )
    )
    connection = sqlite3.connect(db)
    try:
        assert connection.execute(
            "SELECT ai_snapshot_schema_version FROM deals WHERE id = ?", (deal_id,)
        ).fetchone() == (2,)
        # A pre-D6.8 report: same fingerprint, older version.
        connection.execute("UPDATE deals SET ai_snapshot_schema_version = 1 WHERE id = ?", (deal_id,))
        connection.commit()
    finally:
        connection.close()
    reopened = ok(client.get(f"/deals/{deal_id}"))
    assert reopened["ai_snapshot"] is None, "a pre-D6.8 report is never shown as current"
    assert reopened["analysis_snapshot"] == analysis, "the deterministic snapshot is unaffected"

    # No prompt or AI-version input can reach a financial fingerprint.
    source = (_PROJECT_ROOT / "src" / "anchor" / "deals" / "fingerprint.py").read_text(encoding="utf-8")
    imported = {
        node.module or "" for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import) for alias in node.names
    }
    assert not any("ai" in module.split(".") for module in imported), imported


# =============================================================================
# Parts X, Y -- the final Phase 6 architecture
# =============================================================================

#: Part X: the guard that holds each Phase 6 architecture property. Each must
#: still exist -- removing one is a deliberate act, never an accident.
_PHASE_6_GUARDS: dict[str, tuple[tuple[str, str], ...]] = {
    "the engine and leasing never import the Business Plan": (
        ("tests/test_business_plan_architecture.py", "test_importing_the_engine_and_leasing_does_not_pull_in_the_business_plan"),
        ("tests/test_d6_2_owner_cash_flow_architecture.py", "test_the_engine_names_no_business_plan_concept"),
        ("tests/test_business_plan_architecture.py", "test_the_engine_and_the_bridge_take_owner_capital_never_a_business_plan"),
    ),
    "the analysis layer resolves the plan": (
        ("tests/test_d6_2_owner_cash_flow_architecture.py", "test_a_business_plan_is_resolved_in_exactly_one_module"),
        ("tests/test_d6_2_owner_cash_flow_architecture.py", "test_each_business_plan_entry_point_resolves_once_and_delegates_once"),
    ),
    "secondary analysis cannot omit the plan": (
        ("tests/test_d6_4_business_plan_threading_architecture.py", "test_the_plan_cannot_be_omitted_from_any_secondary_analysis"),
        ("tests/test_d6_4_business_plan_threading_architecture.py", "test_the_guard_rejects_a_real_omission"),
    ),
    "the API cannot omit the plan": (
        ("tests/test_d6_5_business_plan_persistence_architecture.py", "test_the_api_passes_the_request_plan_to_every_plan_aware_call"),
        ("tests/test_d6_5_business_plan_persistence_architecture.py", "test_the_api_guard_rejects_a_real_omission"),
    ),
    "frontend deal-state requests cannot omit the plan": (
        ("web/src/businessPlanRequests.test.ts", "finds exactly the deal-state functions the behavioural table covers, all carrying the plan"),
        ("web/src/businessPlanRequests.test.ts", "kills the mutant where a new deal-state function is added without the plan"),
    ),
    "Business Plan persistence is mode-blind": (
        ("tests/test_d6_5_business_plan_persistence.py", "test_the_plan_tables_are_mode_blind_and_carry_every_contract_field"),
        ("tests/test_d6_5_business_plan_persistence_architecture.py", "test_the_store_threads_the_stored_plan_everywhere"),
    ),
    "fingerprint canonicalization ignores row order": (
        ("tests/test_d6_5_business_plan_fingerprint.py", "test_f9_to_f11_reordering_rows_leaves_the_digest"),
        ("tests/test_d6_5_business_plan_persistence_architecture.py", "test_the_real_fingerprint_includes_the_plan_canonically"),
    ),
    "the AI receives the plan": (
        ("tests/test_d6_8_ai_grounding_architecture.py", "test_every_analysis_context_carries_the_callers_own_plan"),
        ("tests/test_d6_8_ai_grounding_architecture.py", "test_the_context_guard_rejects_a_real_omission"),
    ),
    "the AI never calculates a D6 metric": (
        ("tests/test_d6_8_ai_grounding_architecture.py", "test_the_grounding_computes_nothing_and_reads_every_d6_figure_off_results"),
        ("tests/test_d6_8_ai_grounding_architecture.py", "test_the_computation_guard_rejects_a_real_mutant"),
    ),
    "the frontend never calculates a D6 metric": (
        ("web/src/capitalEconomics.test.tsx", "has exactly one arithmetic expression: the display-only year label"),
        ("web/src/capitalEconomics.test.tsx", "reads exactly the intended result fields, and only by name"),
        ("web/src/businessPlan.test.ts", "has exactly one arithmetic expression: the display-only month-to-year label"),
        ("tests/test_business_plan_architecture.py", "test_the_frontend_edits_the_business_plan_but_never_resolves_it"),
    ),
    "the financial engine boundaries hold": (
        ("tests/test_d6_2_owner_cash_flow_architecture.py", "test_lender_metrics_read_noi_only"),
        ("tests/test_d6_2_owner_cash_flow_architecture.py", "test_each_owner_channel_is_subtracted_once_per_series"),
        ("tests/test_d6_2_owner_cash_flow_architecture.py", "test_post_hold_capital_is_disclosed_and_never_an_operand"),
        ("tests/test_d6_4_business_plan_threading_architecture.py", "test_no_plan_aware_module_reads_a_plan_item"),
    ),
}


def _guard_exists(path: str, name: str) -> bool:
    source = (_PROJECT_ROOT / path).read_text(encoding="utf-8")
    if path.endswith(".py"):
        return any(
            isinstance(node, ast.FunctionDef) and node.name == name
            for node in ast.parse(source).body
        )
    return re.search(r"\bit\(\s*(['\"])" + re.escape(name) + r"\1", source) is not None


@pytest.mark.parametrize("prop", sorted(_PHASE_6_GUARDS))
def test_x_every_phase_6_architecture_property_keeps_its_guard(prop: str) -> None:
    for path, name in _PHASE_6_GUARDS[prop]:
        assert _guard_exists(path, name), f"{prop}: {path}::{name} is gone"


def test_x_the_guard_inventory_detects_a_missing_guard() -> None:
    assert not _guard_exists("tests/test_d6_2_owner_cash_flow_architecture.py", "test_lender_metrics_read_noi_only_removed")
    assert not _guard_exists("web/src/capitalEconomics.test.tsx", "has exactly two arithmetic expressions")


_D6_7_MERGE = "9ba3383"

#: The one production file D6.9 changes: the authorized final-acceptance patch
#: that keeps the narrow Lease-Level Capital Schedule inside its own scroll
#: container (CSS only; no financial, request or state change).
_D6_9_PRODUCTION_FILES = ["web/src/index.css"]


def test_x_d6_9_changes_only_authorized_production_files() -> None:
    """D6.9 is a closeout: it adds tests, fixtures and documentation, plus the
    one authorized CSS containment patch above.

    Pinned to ``HEAD`` on purpose while D6.9 is the latest gate. The first Phase 7
    gate must pin it to ``9ba3383..<D6.9 merge>`` (the D6 ledger precedent)."""

    changed = subprocess.run(
        ["git", "diff", "--name-only", _D6_7_MERGE, "HEAD", "--", "src", "web"],
        capture_output=True,
        text=True,
        check=True,
        cwd=_PROJECT_ROOT,
    ).stdout.split()
    production = [path for path in changed if not re.search(r"\.test\.tsx?$", path)]
    assert production == _D6_9_PRODUCTION_FILES


#: Part Y: every Phase 6 contract has exactly one production authority.
_AUTHORITIES = {
    "BusinessPlan": "src/anchor/business_plan/contracts.py",
    "CapitalPlanItem": "src/anchor/business_plan/contracts.py",
    "OwnerExpenseItem": "src/anchor/business_plan/contracts.py",
    "CapitalItemCategory": "src/anchor/business_plan/contracts.py",
    "OwnerExpenseCategory": "src/anchor/business_plan/contracts.py",
    "OwnerCapitalSchedule": "src/anchor/engine/contracts.py",
    "IrrStatus": "src/anchor/engine/contracts.py",
    "resolve_business_plan": "src/anchor/business_plan/resolver.py",
}


def test_y_each_phase_6_contract_has_exactly_one_authority() -> None:
    defined: dict[str, list[str]] = defaultdict(list)
    for path in sorted((_PROJECT_ROOT / "src" / "anchor").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in _AUTHORITIES:
                defined[node.name].append(path.relative_to(_PROJECT_ROOT).as_posix())
    assert {name: paths for name, paths in defined.items()} == {
        name: [path] for name, path in _AUTHORITIES.items()
    }


def _ts_source(name: str) -> str:
    return (_PROJECT_ROOT / "web" / "src" / name).read_text(encoding="utf-8")


def _ts_union(source: str, type_name: str) -> list[str]:
    match = re.search(rf"export type {type_name} =([^;]+);", source)
    assert match, type_name
    return re.findall(r"'([a-z_]+)'", match.group(1))


def _ts_fields(source: str, interface: str) -> list[str]:
    match = re.search(rf"export interface {interface} \{{(.*?)\}}", source, re.DOTALL)
    assert match, interface
    return re.findall(r"^\s*(\w+)\s*:", match.group(1), re.MULTILINE)


def test_y_the_frontend_mirror_is_the_python_authority() -> None:
    """The frontend holds a typed mirror, not a second model: its unions and
    fields are exactly the Python contract's, and it declares each once."""

    plan_ts = _ts_source("businessPlan.ts")
    assert _ts_union(plan_ts, "CapitalItemCategory") == [c.value for c in CapitalItemCategory]
    assert _ts_union(plan_ts, "OwnerExpenseCategory") == [c.value for c in OwnerExpenseCategory]
    assert _ts_fields(plan_ts, "CapitalPlanItemInput") == [f.name for f in dataclasses.fields(CapitalPlanItem)]
    assert _ts_fields(plan_ts, "OwnerExpenseItemInput") == [f.name for f in dataclasses.fields(OwnerExpenseItem)]
    assert _ts_fields(plan_ts, "BusinessPlanInput") == [f.name for f in dataclasses.fields(BusinessPlan)]

    types_ts = _ts_source("types.ts")
    statuses = re.search(r"export const IRR_STATUSES = \[(.*?)\] as const;", types_ts, re.DOTALL)
    assert statuses
    assert re.findall(r"'([a-z_]+)'", statuses.group(1)) == [s.value for s in IrrStatus]

    declarations = {
        r"export type CapitalItemCategory\b": 1,
        r"export type OwnerExpenseCategory\b": 1,
        r"export interface BusinessPlanInput\b": 1,
        r"export const IRR_STATUSES\b": 1,
        r"OwnerCapitalSchedule": 0,
    }
    production = [
        path
        for path in (_PROJECT_ROOT / "web" / "src").rglob("*.ts*")
        if ".test." not in path.name and "Fixture" not in path.name
    ]
    for pattern, expected in declarations.items():
        found = [p.name for p in production if re.search(pattern, p.read_text(encoding="utf-8"))]
        assert len(found) == expected, (pattern, found)
    # OwnerCapitalSchedule is referenced here so the import is intentional: the
    # engine's resolved schedule never crosses to the client.
    assert OwnerCapitalSchedule.__module__ == "anchor.engine.contracts"
