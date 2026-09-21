"""Shared P7.10 Stage 2 fixtures (not a test module).

One saved Deal opted into a valuation and a memo, plus the contract builders the
Stage 2 suites author with. Everything here goes through the real store and the
real contracts, so a claim about persistence is measured rather than asserted by
the code that makes it.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from anchor.analysis.strategy import BASE_SCENARIO_ID, BASE_STRATEGY_ID
from anchor.capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    DebtTerms,
    FundingEvent,
    PctOfValue,
    PositionClass,
    PositionScope,
    ScopeKind,
    ShortfallResolution,
)
from anchor.contracts import AcquisitionInputs
from anchor.deals import store
from anchor.memo.contracts import (
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
from anchor.valuation.contracts import (
    AnalystValue,
    DirectCap,
    UnitValuationInstruction,
    ValuationKind,
    ValuationTimepoint,
)

BASE = BASE_STRATEGY_ID
BASE_SCENARIO = BASE_SCENARIO_ID

#: A Quick Deal with a five-year hold, a clean Year-1 NOI and no acquisition
#: debt, so a direct-cap valuation is exactly ``noi_by_year[0] / cap_rate`` and
#: a reader can verify every figure by hand.
QUICK_INPUTS = AcquisitionInputs(
    purchase_price=10_000_000.0,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.06,
    ltv=0.0,
    interest_rate=0.055,
    amortization=30,
)

AS_IS_CAP_RATE = 0.055


def create_deal(db: Path, *, name: str = "P7.10 deal") -> Any:
    return store.create_deal(name, QUICK_INPUTS, db_path=db)


def as_is_timepoint(
    unit_id: str, *, timepoint_id: str = "as-is", cap_rate: float = AS_IS_CAP_RATE, label: str = "As-Is"
) -> ValuationTimepoint:
    """The closing-time direct-cap definition (Section 5.2: As-Is is month 0)."""

    return ValuationTimepoint(
        timepoint_id=timepoint_id,
        investment_id="",
        kind=ValuationKind.AS_IS,
        label=label,
        model_month=0,
        unit_instructions=(
            UnitValuationInstruction(unit_id=unit_id, method=DirectCap(cap_rate=cap_rate)),
        ),
    )


def stabilized_timepoint(
    unit_id: str,
    *,
    timepoint_id: str = "stabilized",
    model_month: int = 24,
    cap_rate: float = 0.05,
    label: str = "Stabilized",
) -> ValuationTimepoint:
    """An analyst-declared stabilized value at a hold-year end (R-C)."""

    return ValuationTimepoint(
        timepoint_id=timepoint_id,
        investment_id="",
        kind=ValuationKind.STABILIZED,
        label=label,
        model_month=model_month,
        unit_instructions=(
            UnitValuationInstruction(unit_id=unit_id, method=DirectCap(cap_rate=cap_rate)),
        ),
    )


def analyst_value_timepoint(
    unit_id: str,
    *,
    timepoint_id: str = "analyst",
    evidence_id: str = "ev-1",
    amount: float = 12_500_000.0,
    model_month: int = 0,
    kind: ValuationKind = ValuationKind.AS_IS,
    label: str = "Analyst-Supplied",
) -> ValuationTimepoint:
    """An explicitly labelled analyst-supplied value (Section 5.4; R-D)."""

    return ValuationTimepoint(
        timepoint_id=timepoint_id,
        investment_id="",
        kind=kind,
        label=label,
        model_month=model_month,
        unit_instructions=(
            UnitValuationInstruction(
                unit_id=unit_id, method=AnalystValue(amount=amount, evidence_id=evidence_id)
            ),
        ),
    )


def evidence(
    investment_id: str,
    *,
    evidence_id: str = "ev-1",
    approved: bool = True,
    title: str = "Q3 sales comparables",
    reference: str = "doc://comps/q3",
    source_kind: EvidenceSourceKind = EvidenceSourceKind.SALES_COMP,
    as_of_date: date | None = None,
    display_order: int = 0,
) -> MemoEvidenceReference:
    return MemoEvidenceReference(
        evidence_id=evidence_id,
        investment_id=investment_id,
        source_kind=source_kind,
        title=title,
        reference=reference,
        as_of_date=as_of_date,
        approved=approved,
        display_order=display_order,
    )


def memo_draft(
    investment_id: str,
    *,
    selected: SelectedDecision | None = None,
    evidence_ids: tuple[str, ...] = (),
    selected_valuation_timepoint_ids: tuple[str, ...] = (),
    thesis_evidence_ids: tuple[str, ...] = (),
    risk_evidence_ids: tuple[str, ...] = (),
    term_evidence_ids: tuple[str, ...] = (),
    decision_ask: str = "Approve the acquisition at $10.0m.",
    recommendation: AnalystRecommendation = AnalystRecommendation.APPROVE_WITH_CONDITIONS,
) -> InvestmentMemoDraft:
    return InvestmentMemoDraft(
        memo_id="",
        investment_id=investment_id,
        prepared_by="A. Analyst",
        decision_ask=decision_ask,
        analyst_recommendation=recommendation,
        executive_summary="Core-plus asset, below replacement cost.",
        execution_complexity=ExecutionComplexity.MODERATE,
        return_on_time_notes="Modest asset-management load.",
        selected_decision=selected if selected is not None else project_cell(),
        items=(
            MemoItem(
                item_id="thesis-1",
                section=MemoSection.THESIS,
                display_order=0,
                text="Acquired below replacement cost.",
                evidence_ids=thesis_evidence_ids,
            ),
            MemoItem(
                item_id="condition-1",
                section=MemoSection.CONDITION_TO_APPROVAL,
                display_order=1,
                text="Satisfactory environmental report.",
            ),
        ),
        risk_items=(
            MemoRiskItem(
                item_id="risk-1",
                display_order=0,
                text="Concentrated Year-3 rollover.",
                severity=RiskSeverity.MODERATE,
                residual_risk=RiskSeverity.LOW,
                mitigant="Pre-leasing discussions underway.",
                evidence_ids=risk_evidence_ids,
            ),
        ),
        term_items=(
            MemoTermItem(
                item_id="term-1",
                display_order=0,
                text="60-day due diligence period.",
                priority=TermPriority.REQUIRED,
                evidence_ids=term_evidence_ids,
            ),
        ),
        evidence_ids=evidence_ids,
        selected_valuation_timepoint_ids=selected_valuation_timepoint_ids,
    )


def project_cell(
    *, strategy_id: str = BASE, scenario_id: str = BASE_SCENARIO
) -> SelectedDecision:
    return SelectedDecision(
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        perspective=DecisionPerspectiveKind.PROJECT,
        position_id=None,
        partner_id=None,
    )


def position_cell(position_id: str) -> SelectedDecision:
    return SelectedDecision(
        strategy_id=BASE,
        scenario_id=BASE_SCENARIO,
        perspective=DecisionPerspectiveKind.POSITION,
        position_id=position_id,
        partner_id=None,
    )


def pct_of_value_structure(
    unit_id: str, *, timepoint_id: str = "as-is", pct: float = 0.6
) -> CapitalStructure:
    """A senior loan funded as a percentage of a valuation at closing, plus the
    Common Equity marker its residual needs (Section 6; R-E)."""

    return CapitalStructure(
        positions=(
            CapitalPosition(
                position_id="senior",
                name="Senior Loan",
                position_class=PositionClass.SENIOR_DEBT,
                priority=1,
                scope=PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id),
                funding=(
                    FundingEvent(
                        event_id="senior-close",
                        model_month=0,
                        sequence=1,
                        amount_rule=PctOfValue(timepoint_id=timepoint_id, pct=pct),
                    ),
                ),
                terms=DebtTerms(
                    interest_rate=0.06,
                    amortization=30,
                    io_period=0,
                    maturity_month=60,
                    fees=(),
                    current_pay_rate=0.06,
                    pik_rate=0.0,
                ),
                shortfall_resolution=ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
            ),
            CapitalPosition(
                position_id="common",
                name="Common Equity",
                position_class=PositionClass.COMMON_EQUITY,
                priority=99,
                scope=PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id),
                funding=(),
                terms=None,
                shortfall_resolution=None,
            ),
        )
    )


# =============================================================================
# Reading the database directly
# =============================================================================


def rows(db: Path, table: str) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(db)
    try:
        return list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid"))
    finally:
        connection.close()


def row_count(db: Path, table: str) -> int:
    return len(rows(db, table))


def opted_in_deal(db: Path) -> tuple[Any, str]:
    """A saved Deal with one As-Is valuation, and the hidden one-unit Investment
    the first save materialized (Q4)."""

    deal = create_deal(db)
    investment_id, _ = store.create_deal_valuation_timepoint(
        deal.id, as_is_timepoint(deal.id), db_path=db
    )
    return deal, investment_id


def with_approved_evidence(db: Path, investment_id: str, **kwargs: Any) -> MemoEvidenceReference:
    return store.put_evidence_reference(investment_id, evidence(investment_id, **kwargs), db_path=db)


def replace_timepoint(
    db: Path, investment_id: str, timepoint: ValuationTimepoint, **changes: Any
) -> ValuationTimepoint:
    return store.update_valuation_timepoint(
        investment_id,
        dataclasses.replace(timepoint, investment_id=investment_id, **changes),
        db_path=db,
    )
