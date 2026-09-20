"""Excel Export 2 test support: golden Detailed Underwrite cases and helpers.

Each case is analysed by Anchor's own engine entry point -- exactly what a
saved analysis snapshot holds -- and its expected IRR statuses are asserted,
so a case cannot silently stop exercising the boundary it is named for.

The matrix is deliberately built around the things the Detailed operating
model can get wrong that Quick cannot: divergent revenue and expense growth
(which is what makes an approximated exit NOI visibly incorrect), a zeroed
line, negative growth, a management fee that is the entire expense load, and
a vacancy of nothing and of everything.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

import openpyxl

from anchor.analysis.business_plan_analysis import (
    analyze_detailed_acquisition_with_business_plan,
)
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from anchor.contracts import AcquisitionTerms, DetailedOperatingInputs
from anchor.deals.fingerprint import fingerprint_detailed_inputs
from anchor.engine.contracts import DetailedAcquisitionResults, IrrStatus
from anchor.exports.excel import DetailedAuditSource, build_detailed_audit_workbook

GENERATED_AT = datetime(2026, 9, 19, 15, 30, 0, tzinfo=timezone.utc)

#: The frozen Detailed Operating Model V2.1 golden case
#: (``docs/detailed_operating_model_v2_1_golden_case.md``), which produces
#: exactly the Underwriting V2 golden case's NOI series.
GOLDEN_OPERATING = dict(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)

GOLDEN_TERMS = dict(
    purchase_price=10_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)


def operating(**overrides: float) -> DetailedOperatingInputs:
    return DetailedOperatingInputs(**{**GOLDEN_OPERATING, **overrides})  # type: ignore[arg-type]


def terms(**overrides: float | int) -> AcquisitionTerms:
    return AcquisitionTerms(**{**GOLDEN_TERMS, **overrides})  # type: ignore[arg-type]


def _capital(item_id: str, month: int, amount: float) -> CapitalPlanItem:
    return CapitalPlanItem(
        item_id=item_id,
        description=f"Capital {item_id}",
        category=CapitalItemCategory.VALUE_ADD_RENOVATION,
        month=month,
        amount=amount,
    )


def _expense(item_id: str, amount: float, first: int, last: int | None) -> OwnerExpenseItem:
    return OwnerExpenseItem(
        item_id=item_id,
        description=f"Expense {item_id}",
        category=OwnerExpenseCategory.ASSET_MANAGEMENT,
        annual_amount=amount,
        first_year=first,
        last_year=last,
    )


@dataclass(frozen=True)
class DetailedGoldenCase:
    name: str
    terms: AcquisitionTerms
    operating: DetailedOperatingInputs
    business_plan: BusinessPlan = field(default_factory=BusinessPlan)
    levered_status: IrrStatus = IrrStatus.DEFINED
    unlevered_status: IrrStatus = IrrStatus.DEFINED
    #: Check rows Excel is *documented* not to reproduce (Anchor-only numerical
    #: outcomes). Every other row must pass.
    expected_failures: frozenset[str] = frozenset()


DETAILED_GOLDEN_CASES: tuple[DetailedGoldenCase, ...] = (
    # The frozen V2.1 golden case, unchanged.
    DetailedGoldenCase("golden_v2_1", terms(), operating()),
    # Revenue and expense growth diverging is the case the Projection Horizon
    # convention exists for: a blended rate applied to Year H would not
    # reproduce Year H+1, so exit NOI is wrong unless the forward year is
    # genuinely projected.
    DetailedGoldenCase(
        "revenue_outgrows_expenses",
        terms(hold_period=7),
        operating(revenue_growth=0.04, expense_growth=0.015),
    ),
    DetailedGoldenCase(
        "expenses_outgrow_revenue",
        terms(hold_period=6, exit_cap_rate=0.07),
        operating(revenue_growth=0.01, expense_growth=0.05),
    ),
    DetailedGoldenCase(
        "expenses_outgrow_revenue_long_hold",
        terms(hold_period=10),
        operating(revenue_growth=0.005, expense_growth=0.06),
    ),
    DetailedGoldenCase(
        "zero_growth_both",
        terms(hold_period=3),
        operating(revenue_growth=0.0, expense_growth=0.0),
    ),
    DetailedGoldenCase(
        "negative_revenue_growth",
        terms(exit_cap_rate=0.075),
        operating(revenue_growth=-0.03, expense_growth=0.02),
    ),
    DetailedGoldenCase(
        "negative_expense_growth",
        terms(),
        operating(revenue_growth=0.02, expense_growth=-0.04),
    ),
    DetailedGoldenCase(
        "high_growth_both",
        terms(hold_period=8, interest_rate=0.0625),
        operating(revenue_growth=0.09, expense_growth=0.07),
    ),
    # Zero-value lines: every expense line and other income at zero, so a
    # formula that silently treats a blank as something else is exposed.
    DetailedGoldenCase(
        "zero_other_income_and_lines",
        terms(),
        operating(
            other_income=0.0,
            insurance=0.0,
            utilities=0.0,
            other_operating_expenses=0.0,
        ),
    ),
    DetailedGoldenCase(
        "no_vacancy",
        terms(),
        operating(vacancy_credit_loss_pct=0.0),
    ),
    # Every dollar of rent lost: only other income survives, so the property
    # cannot cover debt service in any year and the levered IRR is unavailable
    # by the sign rules rather than by a numerical failure.
    DetailedGoldenCase(
        "total_vacancy",
        terms(hold_period=3, exit_cap_rate=0.09),
        operating(vacancy_credit_loss_pct=1.0, other_income=250_000.0),
        levered_status=IrrStatus.NO_POSITIVE_CASH_FLOW,
    ),
    DetailedGoldenCase(
        "no_management_fee",
        terms(),
        operating(management_fee_pct=0.0),
    ),
    DetailedGoldenCase(
        "management_fee_only_expense",
        terms(),
        operating(
            property_taxes=0.0,
            insurance=0.0,
            utilities=0.0,
            repairs_maintenance=0.0,
            other_operating_expenses=0.0,
            management_fee_pct=0.35,
        ),
    ),
    # Financing boundaries, over an unchanged operating build.
    DetailedGoldenCase("interest_only_beyond_hold", terms(io_period=10), operating()),
    DetailedGoldenCase("amortizing_no_io", terms(io_period=0), operating()),
    DetailedGoldenCase("all_cash", terms(ltv=0.0, io_period=0), operating()),
    DetailedGoldenCase("zero_interest_rate", terms(interest_rate=0.0, io_period=0), operating()),
    DetailedGoldenCase(
        "full_leverage_no_equity",
        terms(ltv=1.0, acquisition_cost_pct=0.0, financing_fee_pct=0.0, annual_capex_reserve=0.0),
        operating(gross_potential_rent=1_400_000.0),
        levered_status=IrrStatus.FIRST_NONZERO_NOT_NEGATIVE,
    ),
    # A Business Plan whose items land at closing, inside the hold and after it.
    DetailedGoldenCase(
        "business_plan_items",
        terms(hold_period=6),
        operating(revenue_growth=0.035, expense_growth=0.02),
        BusinessPlan(
            capital_items=(
                _capital("c0", 0, 250_000.0),
                _capital("c6", 6, 900_000.0),
                _capital("c14", 14, 125_000.0),
                _capital("c200", 200, 400_000.0),
            ),
            owner_expense_items=(
                _expense("e1", 40_000.0, 1, 2),
                _expense("e2", 15_000.0, 3, None),
            ),
        ),
    ),
    # An operating build that cannot service its debt: the levered series has
    # no positive period, so its IRR is unavailable by the sign rules.
    DetailedGoldenCase(
        "no_positive_levered_cash_flow",
        terms(ltv=0.95, interest_rate=0.11, io_period=0, exit_cap_rate=0.14),
        operating(gross_potential_rent=430_000.0, other_income=0.0),
        levered_status=IrrStatus.NO_POSITIVE_CASH_FLOW,
    ),
)

CASES_BY_NAME = {case.name: case for case in DETAILED_GOLDEN_CASES}


def analyze(case: DetailedGoldenCase) -> DetailedAcquisitionResults:
    analysis = analyze_detailed_acquisition_with_business_plan(
        case.terms, case.operating, business_plan=case.business_plan
    )
    assert analysis.results.levered_irr_status is case.levered_status, (
        case.name,
        analysis.results.levered_irr_status,
    )
    assert analysis.results.unlevered_irr_status is case.unlevered_status, (
        case.name,
        analysis.results.unlevered_irr_status,
    )
    return analysis


def source_for(case: DetailedGoldenCase, *, deal_name: str | None = None) -> DetailedAuditSource:
    analysis = analyze(case)
    return DetailedAuditSource(
        deal_id=f"golden-detailed-{case.name}",
        deal_name=deal_name if deal_name is not None else f"Golden {case.name}",
        asset_type_label="Multifamily",
        asset_subtype="Garden",
        terms=case.terms,
        detailed_operating_inputs=case.operating,
        business_plan=case.business_plan,
        operating_projection=analysis.operating_projection,
        results=analysis.results,
        analysis_fingerprint=fingerprint_detailed_inputs(
            case.terms, case.operating, business_plan=case.business_plan
        ),
        generated_at=GENERATED_AT,
        anchor_version="test",
        source_commit=None,
    )


def build(case: DetailedGoldenCase, **kwargs: str) -> bytes:
    return build_detailed_audit_workbook(source_for(case, **kwargs))


# --- Reading workbooks -------------------------------------------------------


def load(data: bytes, *, values: bool = False) -> openpyxl.Workbook:
    return openpyxl.load_workbook(io.BytesIO(data), data_only=values)


def row_of(ws, label: str, *, column: int = 1, start: int = 1) -> int:  # noqa: ANN001
    """The first row at or after ``start`` whose ``column`` holds ``label``."""

    for row in range(start, ws.max_row + 1):
        if ws.cell(row, column).value == label:
            return row
    raise KeyError(f"{ws.title}: {label!r} not found")


def number_at(ws, row: int, column: int) -> float:  # noqa: ANN001
    """A cell's value as a float, asserting it really is a number.

    openpyxl types a cell's value as a wide union, so reading one into
    arithmetic needs a narrowing step; doing it here keeps that out of every
    assertion and turns "this cell should hold a number" into a real check."""

    value = ws.cell(row, column).value
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        ws.title,
        row,
        column,
        value,
    )
    return float(value)


def labels_in(ws, *, column: int = 1, start: int = 1, end: int | None = None) -> list[str]:  # noqa: ANN001
    """Every string label in ``column`` between ``start`` and ``end``."""

    last = ws.max_row if end is None else end
    return [
        value
        for row in range(start, last + 1)
        if isinstance(value := ws.cell(row, column).value, str)
    ]


def check_rows(values_wb: openpyxl.Workbook) -> dict[str, tuple[object, object, object, str]]:
    """Metric -> (Anchor, Excel, tolerance, status) for every reconciliation row."""

    ws = values_wb["Checks"]
    header = row_of(ws, "Metric")
    rows: dict[str, tuple[object, object, object, str]] = {}
    for row in range(header + 1, ws.max_row + 1):
        status = ws.cell(row, 6).value
        metric = ws.cell(row, 1).value
        if status is None or metric is None:
            continue
        rows[str(metric)] = (ws.cell(row, 2).value, ws.cell(row, 3).value, ws.cell(row, 5).value, str(status))
    return rows


def status_block(values_wb: openpyxl.Workbook) -> dict[str, object]:
    ws = values_wb["Checks"]
    block: dict[str, object] = {}
    for row in range(1, row_of(ws, "Reconciliation") + 1):
        label = ws.cell(row, 1).value
        if isinstance(label, str):
            block[label] = ws.cell(row, 2).value
    return block
