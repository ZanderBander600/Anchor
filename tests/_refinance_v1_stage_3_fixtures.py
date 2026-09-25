"""Shared Refinance & Capital Events V1 Stage 3 fixtures (not a test module).

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 12.5, 16.3, 18.2
(F23) and 25. Saved Deals and Investments carrying the Section 18.1 base case
with a persisted refinance, memo drafts selecting a decision cell, and readers
for the frozen report, the PDF and the refinance audit workbook. Everything goes
through the real store, engine, assembler, renderer and routes.

Expected figures are the contract's own hand arithmetic (Section 18), never a
value read back from the code under test.
"""

from __future__ import annotations

import dataclasses
import io
import zipfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import _p7_10_stage_2_fixtures as memo_fx  # type: ignore[import-not-found]
import _refinance_v1_fixtures as rf  # type: ignore[import-not-found]
import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.analysis.business_plan_analysis import analyze_quick_acquisition_with_business_plan
from anchor.deals.fingerprint import fingerprint_quick_inputs
from anchor.deals import memo_dependencies as deps
from anchor.deals import store
from anchor.memo.contracts import DecisionPerspectiveKind, SelectedDecision
from anchor.reporting.assembly import assemble_draft_preview

#: The acquisition-financing reference label (R-P rule 3), spelled once.
REFERENCE = "Acquisition financing — excludes later capital events"

def f5_structure(unit_id: str, **overrides: Any) -> Any:
    """F5 (Section 18.2): N = 8,000,000 - 5,520,000 - 80,000 - 40,000 =
    2,360,000, a distribution."""

    kwargs: dict[str, Any] = {"dscr": 2.0, "costs": (rf.third_party(40_000.0),)}
    kwargs.update(overrides)
    return fx.evented(unit_id, replacement_fees=(rf.lender_fee(80_000.0),), **kwargs)


def f6_structure(unit_id: str) -> Any:
    """F6: a binding fixed cap of 5,000,000 gives N = -640,000."""

    return fx.evented(
        unit_id, replacement_fees=(rf.lender_fee(80_000.0),), fixed=5_000_000.0, costs=(rf.third_party(40_000.0),)
    )


def f7_structure(unit_id: str) -> Any:
    """F7: a binding fixed cap of 5,640,000 gives an exact N = 0."""

    return fx.evented(
        unit_id, replacement_fees=(rf.lender_fee(80_000.0),), fixed=5_640_000.0, costs=(rf.third_party(40_000.0),)
    )


def f4_structure(unit_id: str) -> Any:
    """F4: fixed 8,000,000, LTV 64% of 12,500,000 and DSCR 2.00x all bind."""

    return fx.evented(unit_id, fixed=8_000_000.0, ltv=0.64, dscr=2.0)


def refinance_deal(db: Path, structure_of: Any = f5_structure, *, name: str = "Refinance unit", **deal: Any) -> tuple[Any, str]:
    """A saved Section 18.1 Deal carrying ``structure_of(deal.id)`` as its Base
    Capital Structure; returns the Deal and its hidden Investment."""

    saved = fx.base_deal(db, name=name, **deal)
    investment_id, _ = store.set_deal_capital_structure(saved.id, structure_of(saved.id), db_path=db)
    assert investment_id is not None
    return saved, investment_id


def analysed(db: Path, deal: Any) -> Any:
    """Save the Quick Deal's current analysis, so Excel Export 1 is eligible."""

    results = analyze_quick_acquisition_with_business_plan(deal.inputs, business_plan=deal.business_plan)
    return store.update_analysis_snapshot(
        deal.id,
        dataclasses.asdict(results),
        financial_input_fingerprint=fingerprint_quick_inputs(deal.inputs, business_plan=deal.business_plan),
        db_path=db,
    )


def with_value_timepoint(db: Path, investment_id: str, unit_id: str, **kwargs: Any) -> Any:
    """The Section 18.1 CUSTOM timepoint at month 24 (V = 12,500,000)."""

    return fx.with_timepoint(db, investment_id, fx.value_timepoint(unit_id, **kwargs))


def project_cell(strategy_id: str = "base", scenario_id: str = "base") -> SelectedDecision:
    return memo_fx.project_cell(strategy_id=strategy_id, scenario_id=scenario_id)


def partner_cell(partner_id: str = "lp", strategy_id: str = "base") -> SelectedDecision:
    return SelectedDecision(
        strategy_id=strategy_id,
        scenario_id="base",
        perspective=DecisionPerspectiveKind.PARTNER,
        position_id=None,
        partner_id=partner_id,
    )


def draft(db: Path, investment_id: str, selected: SelectedDecision | None = None) -> None:
    store.put_memo_draft(
        investment_id, memo_fx.memo_draft(investment_id, selected=selected or project_cell()), db_path=db
    )


def preview(db: Path, investment_id: str, selected: SelectedDecision | None = None) -> Any:
    draft(db, investment_id, selected)
    return assemble_draft_preview(investment_id, db_path=db)


def refusal_codes(db: Path, investment_id: str) -> list[str]:
    stored = store.get_memo_draft(investment_id, db_path=db)
    assert stored is not None and stored.selected_decision is not None
    return [
        refusal.code.value
        for refusal in deps.publication_refusals_for(
            investment_id,
            stored,
            deps.dependency_set(investment_id, stored.selected_decision, draft=stored, db_path=db),
            db_path=db,
        )
    ]


def publish(db: Path, investment_id: str, selected: SelectedDecision | None = None) -> Any:
    draft(db, investment_id, selected)
    return deps.publish(investment_id, db_path=db)


def _one(found: list[Any], what: str) -> Any:
    """Exactly one match, or an assertion (never a ValueError), so a mutation
    proof counts a missing item as a kill."""

    assert len(found) == 1, (what, len(found))
    return found[0]


def metric(package: Any, label: str) -> Any:
    return _one([item for item in package.key_metrics if item.label == label], label)


def section(package: Any, title: str) -> Any:
    return _one([item for item in package.sections if item.title == title], title)


def table(section_: Any, caption_prefix: str) -> Any:
    return _one([item for item in section_.tables if item.caption.startswith(caption_prefix)], caption_prefix)


def rows(table_: Any) -> dict[str, tuple[str, ...]]:
    return {row[0]: row for row in table_.rows}


def client(db: Path, monkeypatch: Any) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    return TestClient(api_module.app)


def analysis(client_: TestClient, investment_id: str, strategy_id: str = "base", scenario_id: str = "base") -> dict[str, Any]:
    response = client_.post(f"/investments/{investment_id}/structured-variants/{strategy_id}/{scenario_id}/analysis")
    assert response.status_code == 200, response.text
    return response.json()


def audit(client_: TestClient, investment_id: str, fingerprint: str | None, **params: str) -> Any:
    query = {**params}
    if fingerprint is not None:
        query["fingerprint"] = fingerprint
    return client_.get(f"/investments/{investment_id}/exports/refinance-capital-structure-audit.xlsx", params=query)


def workbook_parts(content: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return archive.namelist()


def wire_strings(value: Any) -> list[str]:
    """Every string anywhere in a JSON-like structure."""

    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in wire_strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in wire_strings(item)]
    return []
