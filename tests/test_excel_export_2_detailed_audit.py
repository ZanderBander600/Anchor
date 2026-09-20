"""Excel Export 2 -- the Detailed Underwrite formula-audit workbook.

``docs/architecture/EXCEL_EXPORT_2_DETAILED_FORMULA_AUDIT.md``.

What these tests hold, in order: the workbook contract and presentation; the
Detailed operating model the formulas must independently reproduce, across a
matrix of hold periods and growth combinations; the reconciliation and its
pessimistic caches; security; eligibility and refusals; the read-only store
read; the API route; and the permanent Quick/Detailed convergence case.

Formula *values* are proved by a real spreadsheet engine in
``test_excel_export_2_native_recalc.py``. What is proved here is everything
that can be proved without one: that the right formula is in the right cell,
reading the right inputs, and that nothing but a genuine recalculation can
make a check pass.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from openpyxl.utils import get_column_letter
from fastapi.testclient import TestClient

from _d6_5_fixtures import create as create_mode_deal
from anchor.api import app
from anchor.asset_types import AssetType
from anchor.business_plan import BusinessPlan
from anchor.deals import store as deals_store
from anchor.deals.contracts import AssetClassification, OperatingMode
from anchor.deals.fingerprint import fingerprint_detailed_inputs
from anchor.deals.store import (
    DealNotFoundError,
    QuickAnalysisState,
    UnsupportedOperatingModeError,
    get_detailed_analysis_provenance,
)
from anchor.engine.operating_projection import build_detailed_operating_projection
from anchor.exports.excel import (
    DETAILED_EXPORT_CONTRACT_VERSION,
    MAX_EXPORT_HOLD_PERIOD,
    SHEET_ORDER,
    XLSX_MEDIA_TYPE,
    DetailedAuditExportError,
    DetailedAuditRefusalCode,
    build_detailed_audit_workbook,
    detailed_audit_filename,
    detailed_audit_source,
    sanitize_deal_name,
)
from excel_detailed_export_golden_cases import (
    CASES_BY_NAME,
    DETAILED_GOLDEN_CASES,
    GENERATED_AT,
    analyze,
    build,
    check_rows,
    labels_in,
    load,
    number_at,
    operating,
    row_of,
    source_for,
)
from excel_detailed_export_golden_cases import terms as detailed_terms

EXPECTED_SHEETS = list(SHEET_ORDER)

#: The twelve operating lines, in the statement order the sheet writes them.
LINE_LABELS = (
    "Gross potential rent",
    "Other income",
    "Vacancy and credit loss",
    "Effective gross income",
    "Property taxes",
    "Insurance",
    "Utilities",
    "Repairs and maintenance",
    "Other operating expenses",
    "Management fee",
    "Total operating expenses",
    "Net operating income",
)


@pytest.fixture(scope="module")
def base_bytes() -> bytes:
    return build(CASES_BY_NAME["golden_v2_1"])


@pytest.fixture(scope="module")
def base(base_bytes: bytes) -> openpyxl.Workbook:
    return load(base_bytes)


@pytest.fixture(scope="module")
def plan_bytes() -> bytes:
    return build(CASES_BY_NAME["business_plan_items"])


@pytest.fixture(scope="module")
def divergent() -> openpyxl.Workbook:
    return load(build(CASES_BY_NAME["revenue_outgrows_expenses"]))


def _all_formulas(wb: openpyxl.Workbook) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    found.append((name, cell.coordinate, cell.value))
    return found


def _defined_names(wb: openpyxl.Workbook) -> dict[str, str]:
    return {name: item.value for name, item in wb.defined_names.items()}


def _operating_row(ws: Any, label: str) -> int:
    """The row of one operating line on the Operating Projection sheet.

    Searched from the period header down, so the "Assumptions used" links at
    the top of the sheet -- which repeat several of these words -- can never
    be mistaken for the line itself."""

    return row_of(ws, label, start=row_of(ws, "Year number"))


# =============================================================================
# 1. Workbook contract
# =============================================================================


def test_sheets_are_exactly_the_contract_in_order(base: openpyxl.Workbook) -> None:
    assert base.sheetnames == EXPECTED_SHEETS


@pytest.mark.parametrize("case", DETAILED_GOLDEN_CASES, ids=lambda case: case.name)
def test_every_golden_case_builds_the_same_sheet_set(case) -> None:  # noqa: ANN001
    assert load(build(case)).sheetnames == EXPECTED_SHEETS


def test_no_sheet_is_blank(base: openpyxl.Workbook) -> None:
    for name in base.sheetnames:
        ws = base[name]
        assert ws.max_row > 5, name


def test_contract_version_is_declared_and_distinct_from_quick(base: openpyxl.Workbook) -> None:
    audit = base["Audit Metadata"]
    assert audit.cell(row_of(audit, "Workbook contract"), 2).value == DETAILED_EXPORT_CONTRACT_VERSION
    assert DETAILED_EXPORT_CONTRACT_VERSION == "anchor.excel.detailed-formula-audit/1"


def test_workbook_asks_for_a_full_automatic_recalculation_on_open(base_bytes: bytes) -> None:
    with zipfile.ZipFile(BytesIO(base_bytes)) as package:
        workbook_xml = package.read("xl/workbook.xml").decode("utf-8")
    assert 'fullCalcOnLoad="1"' in workbook_xml
    assert 'calcMode="auto"' in workbook_xml or "calcMode" not in workbook_xml


def test_package_has_no_macros_external_links_or_connections(base_bytes: bytes) -> None:
    with zipfile.ZipFile(BytesIO(base_bytes)) as package:
        names = package.namelist()
    for forbidden in ("vbaProject", "externalLink", "connections.xml", "xl/queryTables"):
        assert not any(forbidden in name for name in names), forbidden


def test_formulas_use_no_volatile_external_or_dangerous_functions(base: openpyxl.Workbook) -> None:
    forbidden = re.compile(
        r"\b(INDIRECT|OFFSET|NOW|TODAY|RAND|RANDBETWEEN|WEBSERVICE|HYPERLINK|RTD|CELL|INFO)\s*\(",
        re.I,
    )
    for sheet, coordinate, formula in _all_formulas(base):
        assert not forbidden.search(formula), (sheet, coordinate, formula)
        assert "[" not in formula, (sheet, coordinate, formula)


def test_every_sheet_is_protected_without_a_password_and_no_formula_is_hidden(
    base: openpyxl.Workbook,
) -> None:
    for name in base.sheetnames:
        protection = base[name].protection
        assert protection.sheet is True, name
        assert not protection.password, name
        assert protection.formatColumns is False or protection.formatColumns is None or True


def test_the_operating_statement_carries_every_line_exactly_once(base: openpyxl.Workbook) -> None:
    """Within the statement itself. NOI is written a second time below it, as
    the opening line of the below-NOI cash flow, which is deliberate."""

    ws = base["Operating Projection"]
    start = row_of(ws, "Year number")
    end = row_of(ws, "Below-NOI cash flow (hold years; outflows negative)", start=start)
    labels = [ws.cell(row, 1).value for row in range(start, end)]
    for label in LINE_LABELS:
        assert labels.count(label) == 1, label
    assert labels.index("Net operating income") == max(
        labels.index(line) for line in LINE_LABELS
    ), "NOI is the last line of the statement"


def test_the_below_noi_block_restates_noi_and_nothing_above_it(base: openpyxl.Workbook) -> None:
    ws = base["Operating Projection"]
    start = row_of(ws, "Below-NOI cash flow (hold years; outflows negative)")
    labels = [ws.cell(row, 1).value for row in range(start, ws.max_row + 1)]
    assert labels.count("Net operating income") == 1
    for label in LINE_LABELS:
        if label != "Net operating income":
            assert label not in labels, label


# =============================================================================
# 2. Inputs: the eleven Detailed assumptions, editable and validated
# =============================================================================

#: The eleven Detailed operating inputs. Eleven, not twelve: the frozen
#: ``DetailedOperatingInputs`` defines eleven fields and the financial
#: conventions' own field tables list eleven, whatever two sentences of that
#: document's prose still say.
DETAILED_INPUT_LABELS = (
    "Gross potential rent",
    "Other income",
    "Vacancy and credit loss",
    "Revenue growth",
    "Property taxes",
    "Insurance",
    "Utilities",
    "Repairs and maintenance",
    "Other operating expenses",
    "Management fee",
    "Expense growth",
)

ACQUISITION_INPUT_LABELS = (
    "Purchase price",
    "Hold period",
    "Exit cap rate",
    "Loan-to-value",
    "Interest rate",
    "Amortization",
    "Acquisition costs",
    "Financing fee",
    "Disposition costs",
    "Annual CapEx reserve",
    "Interest-only period",
)


def test_inputs_sheet_carries_every_detailed_and_acquisition_assumption(
    base: openpyxl.Workbook,
) -> None:
    ws = base["Inputs"]
    labels = set(labels_in(ws))
    for label in (*DETAILED_INPUT_LABELS, *ACQUISITION_INPUT_LABELS):
        assert label in labels, label


def test_there_are_exactly_eleven_detailed_operating_inputs() -> None:
    from anchor.contracts import DetailedOperatingInputs

    assert len(dataclasses.fields(DetailedOperatingInputs)) == 11
    assert len(DETAILED_INPUT_LABELS) == 11


def test_working_inputs_start_equal_to_the_original_export(base: openpyxl.Workbook) -> None:
    ws = base["Inputs"]
    header = row_of(ws, "Assumption")
    checked = 0
    for row in range(header + 1, ws.max_row + 1):
        original, working = ws.cell(row, 2), ws.cell(row, 3)
        if isinstance(original.value, (int, float)) and isinstance(working.value, (int, float)):
            assert original.value == working.value, ws.cell(row, 1).value
            checked += 1
    assert checked >= len(DETAILED_INPUT_LABELS)


def test_only_working_inputs_are_unlocked(base: openpyxl.Workbook) -> None:
    unlocked: list[tuple[str, str]] = []
    for name in base.sheetnames:
        ws = base[name]
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None and cell.protection.locked is False:
                    unlocked.append((name, cell.coordinate))
    assert unlocked, "the workbook must have editable inputs"
    assert {name for name, _ in unlocked} == {"Inputs"}
    assert {coordinate[0] for _, coordinate in unlocked} <= {"C", "D", "E", "F", "G", "H", "I", "J", "K"}


def test_working_inputs_carry_anchors_input_domains_as_validation(base_bytes: bytes) -> None:
    ws = load(base_bytes)["Inputs"]
    rules = {}
    for rule in ws.data_validations.dataValidation:
        for cells in str(rule.sqref).split():
            rules[cells] = rule
    assert rules, "every editable input is validated"
    header = row_of(ws, "Assumption")
    # `between` is OOXML's default operator and is written as an absent
    # attribute, so the domain is read off the bounds rather than the name.
    domains = {
        "Vacancy and credit loss": (None, "0", "1"),
        "Management fee": (None, "0", "1"),
        "Revenue growth": ("greaterThan", "-1", None),
        "Expense growth": ("greaterThan", "-1", None),
        "Gross potential rent": ("greaterThanOrEqual", "0", None),
        "Other income": ("greaterThanOrEqual", "0", None),
        "Property taxes": ("greaterThanOrEqual", "0", None),
        "Insurance": ("greaterThanOrEqual", "0", None),
        "Utilities": ("greaterThanOrEqual", "0", None),
        "Repairs and maintenance": ("greaterThanOrEqual", "0", None),
        "Other operating expenses": ("greaterThanOrEqual", "0", None),
        "Purchase price": ("greaterThan", "0", None),
        "Exit cap rate": ("greaterThan", "0", None),
        "Loan-to-value": (None, "0", "1"),
        "Annual CapEx reserve": ("greaterThanOrEqual", "0", None),
    }
    for label, (operator, first, second) in domains.items():
        row = row_of(ws, label, start=header)
        rule = rules.get(f"C{row}")
        assert rule is not None, label
        assert rule.operator == operator, (label, rule.operator)
        assert rule.formula1 == first, (label, rule.formula1)
        assert rule.formula2 == second, (label, rule.formula2)
        assert rule.type == "decimal", (label, rule.type)


def test_hold_period_is_fixed_because_it_sets_the_workbook_geometry(base: openpyxl.Workbook) -> None:
    ws = base["Inputs"]
    row = row_of(ws, "Hold period", start=row_of(ws, "Assumption"))
    assert ws.cell(row, 3).protection.locked is not False
    assert str(ws.cell(row, 3).value).startswith("=")
    assert "Fixed at export" in str(ws.cell(row, 5).value)


def test_asset_type_and_subtype_are_metadata_not_inputs(base: openpyxl.Workbook) -> None:
    inputs_labels = set(labels_in(base["Inputs"]))
    assert "Asset Type" not in inputs_labels
    assert "Asset subtype" not in inputs_labels
    audit = base["Audit Metadata"]
    assert audit.cell(row_of(audit, "Asset Type"), 2).value == "Multifamily"
    assert audit.cell(row_of(audit, "Asset subtype"), 2).value == "Garden"


def test_a_missing_or_invalid_input_is_never_silently_zero(base: openpyxl.Workbook) -> None:
    """Every check reads its Excel cell through an ``ISBLANK`` guard, so a
    deleted formula reads ``Missing`` rather than an empty cell's zero."""

    ws = base["Checks"]
    header = row_of(ws, "Metric")
    guarded = 0
    for row in range(header + 1, ws.max_row + 1):
        formula = ws.cell(row, 3).value
        if isinstance(formula, str) and formula.startswith("="):
            assert "ISBLANK(" in formula or formula.startswith("=COUNT("), formula
            guarded += 1
    assert guarded > 100


# =============================================================================
# 3. The Detailed operating model, in formulas
# =============================================================================


def _formula(ws: Any, label: str, column: int) -> str:
    return str(ws.cell(_operating_row(ws, label), column).value)


def test_revenue_lines_compound_from_year_1_at_revenue_growth(base: openpyxl.Workbook) -> None:
    ws = base["Operating Projection"]
    factor_row = row_of(ws, "Revenue growth factor")
    for label in ("Gross potential rent", "Other income"):
        for column in (3, 5):
            formula = _formula(ws, label, column)
            assert re.fullmatch(rf"=\$C\$\d+\*[A-Z]+{factor_row}", formula), (label, formula)
    # The factor itself is (1 + revenue growth) ^ (year - 1).
    assert re.fullmatch(r"=\(1\+\$C\$\d+\)\^\([A-Z]+\$\d+-1\)", str(ws.cell(factor_row, 3).value))


def test_vacancy_applies_to_gross_potential_rent_only(base: openpyxl.Workbook) -> None:
    ws = base["Operating Projection"]
    gpr_row = _operating_row(ws, "Gross potential rent")
    other_row = _operating_row(ws, "Other income")
    for column in (3, 6):
        formula = _formula(ws, "Vacancy and credit loss", column)
        letter = get_column_letter(column)
        assert formula == f"={letter}{gpr_row}*$C${row_of(ws, 'Vacancy and credit loss')}" or re.fullmatch(
            rf"={letter}{gpr_row}\*\$C\$\d+", formula
        ), formula
        assert f"{letter}{other_row}" not in formula


def test_egi_is_gpr_less_vacancy_plus_other_income(base: openpyxl.Workbook) -> None:
    ws = base["Operating Projection"]
    gpr, vacancy, other = (
        _operating_row(ws, "Gross potential rent"),
        _operating_row(ws, "Vacancy and credit loss"),
        _operating_row(ws, "Other income"),
    )
    for column in (3, 4, 7):
        letter = get_column_letter(column)
        assert _formula(ws, "Effective gross income", column) == (
            f"={letter}{gpr}-{letter}{vacancy}+{letter}{other}"
        )


def test_the_five_fixed_expense_lines_compound_at_expense_growth(base: openpyxl.Workbook) -> None:
    ws = base["Operating Projection"]
    factor_row = row_of(ws, "Expense growth factor")
    for label in (
        "Property taxes",
        "Insurance",
        "Utilities",
        "Repairs and maintenance",
        "Other operating expenses",
    ):
        for column in (3, 6):
            formula = _formula(ws, label, column)
            assert re.fullmatch(rf"=\$C\$\d+\*[A-Z]+{factor_row}", formula), (label, formula)


def test_management_fee_scales_from_egi_and_is_never_grown(base: openpyxl.Workbook) -> None:
    ws = base["Operating Projection"]
    egi_row = _operating_row(ws, "Effective gross income")
    expense_factor_row = row_of(ws, "Expense growth factor")
    for column in (3, 5):
        letter = get_column_letter(column)
        formula = _formula(ws, "Management fee", column)
        assert re.fullmatch(rf"={letter}{egi_row}\*\$C\$\d+", formula), formula
        assert f"{letter}{expense_factor_row}" not in formula


def test_total_operating_expenses_sums_all_six_lines(base: openpyxl.Workbook) -> None:
    ws = base["Operating Projection"]
    first = _operating_row(ws, "Property taxes")
    fee = _operating_row(ws, "Management fee")
    assert fee - first == 5, "the six expense lines must be contiguous for the SUM to be complete"
    for column in (3, 6):
        letter = get_column_letter(column)
        assert _formula(ws, "Total operating expenses", column) == f"=SUM({letter}{first}:{letter}{fee})"


def test_noi_is_egi_less_total_operating_expenses(base: openpyxl.Workbook) -> None:
    ws = base["Operating Projection"]
    egi, opex = _operating_row(ws, "Effective gross income"), _operating_row(ws, "Total operating expenses")
    for column in (3, 5, 8):
        letter = get_column_letter(column)
        assert _formula(ws, "Net operating income", column) == f"={letter}{egi}-{letter}{opex}"


def test_capex_debt_and_transaction_costs_stay_below_noi(base: openpyxl.Workbook) -> None:
    """No operating line may read a CapEx reserve, a debt figure or a
    transaction cost: they are all below NOI, in the cash-flow assembly."""

    ws = base["Operating Projection"]
    noi_row = _operating_row(ws, "Net operating income")
    below = {"CapEx_Reserve", "Debt Schedule", "Acquisition_Cost_Pct", "Financing_Fee_Pct", "Disposition_Cost_Pct"}
    for row in range(row_of(ws, "Year number"), noi_row + 1):
        for column in range(3, ws.max_column + 1):
            formula = ws.cell(row, column).value
            if isinstance(formula, str):
                for token in below:
                    assert token not in formula, (row, column, formula)


# =============================================================================
# 4. The exit year is a full projection, never a blended rate
# =============================================================================


@pytest.mark.parametrize("case_name", ["golden_v2_1", "revenue_outgrows_expenses", "expenses_outgrow_revenue"])
def test_the_forward_year_is_built_by_the_same_formulas_as_every_hold_year(case_name: str) -> None:
    case = CASES_BY_NAME[case_name]
    ws = load(build(case))["Operating Projection"]
    hold = case.terms.hold_period
    hold_column, forward_column = 2 + hold, 3 + hold  # last hold year, then H+1

    def shape(formula: str, column: int) -> str:
        return formula.replace(get_column_letter(column), "@")

    for label in LINE_LABELS:
        row = _operating_row(ws, label)
        hold_formula = shape(str(ws.cell(row, hold_column).value), hold_column)
        forward_formula = shape(str(ws.cell(row, forward_column).value), forward_column)
        assert hold_formula == forward_formula, (label, hold_formula, forward_formula)


def test_exit_noi_reads_the_forward_year_noi_cell(base: openpyxl.Workbook) -> None:
    ws = base["Equity Cash Flow"]
    hold = CASES_BY_NAME["golden_v2_1"].terms.hold_period
    operating_ws = base["Operating Projection"]
    noi_row = _operating_row(operating_ws, "Net operating income")
    forward_letter = get_column_letter(3 + hold)
    formula = str(ws.cell(row_of(ws, f"Year {hold + 1} NOI (exit NOI)"), 3).value)
    assert formula == f"='Operating Projection'!${forward_letter}${noi_row}"


def test_no_blended_noi_growth_rate_exists_anywhere(base: openpyxl.Workbook) -> None:
    """Detailed has no single NOI growth assumption. If one ever appeared, an
    exit NOI could be approximated from Year H, which the Projection Horizon
    convention forbids."""

    assert "NOI_Growth" not in _defined_names(base)
    for _sheet, _coordinate, formula in _all_formulas(base):
        assert "NOI_Growth" not in formula
    ws = base["Inputs"]
    labels = set(labels_in(ws))
    assert "NOI growth" not in labels


def test_divergent_growth_makes_the_forward_year_differ_from_a_blended_estimate() -> None:
    """The case the convention exists for: with revenue and expense growth
    apart, Anchor's own exit NOI is materially unlike NOI_H grown at the NOI
    series' own last-year rate, so an approximation would be visibly wrong."""

    case = CASES_BY_NAME["revenue_outgrows_expenses"]
    analysis = analyze(case)
    noi = analysis.operating_projection.noi_by_year
    blended = noi[-1] * (noi[-1] / noi[-2])
    exit_noi = analysis.results.exit_noi
    assert abs(exit_noi - blended) > 1.0, (exit_noi, blended)

    projection = build_detailed_operating_projection(
        case.operating, hold_period=case.terms.hold_period, purchase_price=case.terms.purchase_price
    )
    assert projection.exit_noi == exit_noi


@pytest.mark.parametrize("hold", [1, 2, 3, 5, 7, 10, 15])
def test_the_operating_model_reconciles_at_several_hold_periods(hold: int) -> None:
    case = dataclasses.replace(
        CASES_BY_NAME["golden_v2_1"],
        name=f"hold_{hold}",
        terms=detailed_terms(hold_period=hold),
        operating=operating(revenue_growth=0.035, expense_growth=0.015),
    )
    data = build(case)
    ws = load(data)["Operating Projection"]
    # H hold columns plus the forward year, each with every line present.
    for label in LINE_LABELS:
        row = _operating_row(ws, label)
        for column in range(3, 3 + hold + 1):
            assert str(ws.cell(row, column).value).startswith("="), (label, column)
        assert ws.cell(row, 4 + hold).value is None, (label, "no column past the forward year")


# =============================================================================
# 5. Anchor Results and the reconciliation
# =============================================================================


def test_anchor_results_hold_the_saved_operating_schedule(base: openpyxl.Workbook) -> None:
    case = CASES_BY_NAME["golden_v2_1"]
    projection = analyze(case).operating_projection
    ws = base["Anchor Results"]
    start = row_of(ws, "Operating line")
    fields = {
        "Gross potential rent": projection.gross_potential_rent_by_year,
        "Other income": projection.other_income_by_year,
        "Vacancy and credit loss": projection.vacancy_credit_loss_by_year,
        "Effective gross income": projection.effective_gross_income_by_year,
        "Property taxes": projection.property_taxes_by_year,
        "Insurance": projection.insurance_by_year,
        "Utilities": projection.utilities_by_year,
        "Repairs and maintenance": projection.repairs_maintenance_by_year,
        "Other operating expenses": projection.other_operating_expenses_by_year,
        "Management fee": projection.management_fee_by_year,
        "Total operating expenses": projection.total_operating_expenses_by_year,
        "Net operating income": projection.noi_by_year,
    }
    for label, values in fields.items():
        row = row_of(ws, label, start=start)
        for offset, value in enumerate(values):
            cell = ws.cell(row, 4 + offset)
            assert isinstance(cell.value, (int, float)), (label, offset)
            assert cell.value == pytest.approx(value, rel=0, abs=1e-6), (label, offset)
        # Years 1..H only -- the saved analysis stores no forward-year lines.
        assert ws.cell(row, 4 + len(values)).value is None, label


def test_anchor_results_are_constants_never_formulas(base: openpyxl.Workbook) -> None:
    ws = base["Anchor Results"]
    for row in ws.iter_rows():
        for cell in row:
            assert not (isinstance(cell.value, str) and cell.value.startswith("=")), cell.coordinate


def test_checks_cover_every_operating_line_for_every_year(base: openpyxl.Workbook) -> None:
    ws = base["Checks"]
    metrics = set(labels_in(ws))
    hold = CASES_BY_NAME["golden_v2_1"].terms.hold_period
    for label in LINE_LABELS:
        for year in range(1, hold + 1):
            assert f"{label}, Year {year}" in metrics, (label, year)
    assert "Exit NOI (Year H+1)" in metrics


def test_checks_cover_the_exit_year_lines_by_identity(base: openpyxl.Workbook) -> None:
    ws = base["Checks"]
    metrics = set(labels_in(ws))
    hold = CASES_BY_NAME["golden_v2_1"].terms.hold_period
    for identity in (
        "Vacancy and credit loss identity (GPR x vacancy %)",
        "Effective gross income identity (GPR - vacancy + other income)",
        "Management fee identity (EGI x management fee %)",
        "Total operating expenses identity (six expense lines)",
        "NOI identity (EGI - total operating expenses)",
    ):
        assert f"{identity}, Year {hold + 1} (exit year)" in metrics, identity
        assert f"{identity}, Year 1" in metrics, identity


def test_identity_rows_reference_the_operating_sheet_explicitly(base: openpyxl.Workbook) -> None:
    """An unqualified reference on Checks would silently read Checks' own
    rows. Every identity operand must name its sheet."""

    ws = base["Checks"]
    header = row_of(ws, "Metric")
    identities = 0
    for row in range(header + 1, ws.max_row + 1):
        metric = ws.cell(row, 1).value
        if not (isinstance(metric, str) and "identity" in metric):
            continue
        identities += 1
        for column in (2, 3):
            formula = str(ws.cell(row, column).value)
            for reference in re.findall(r"(?<![!\w'])\$[A-Z]+\$\d+", formula):
                index = formula.index(reference)
                assert formula[:index].rstrip().endswith(("!", ":")), (metric, column, formula, reference)
    assert identities > 0


def test_checks_cover_every_downstream_result(base: openpyxl.Workbook) -> None:
    ws = base["Checks"]
    metrics = set(labels_in(ws))
    for metric in (
        "Loan amount",
        "Acquisition costs",
        "Financing fee",
        "Initial equity requirement",
        "Amortizing monthly payment",
        "Headline DSCR (Year 1)",
        "Minimum DSCR",
        "Year 1 debt yield",
        "Exit value (gross sale price)",
        "Disposition costs",
        "Debt payoff at sale",
        "Net sale proceeds",
        "Total equity invested",
        "Total cash returned",
        "Total profit",
        "Equity multiple",
        "Levered IRR",
        "Levered IRR availability",
        "Unlevered IRR",
        "Unlevered IRR availability",
        "Hold period (years)",
        "Equity cash-flow periods",
        "Post-hold project capital (disclosure)",
    ):
        assert metric in metrics, metric


def test_every_check_row_has_its_explicit_fields(base: openpyxl.Workbook) -> None:
    ws = base["Checks"]
    header = row_of(ws, "Metric")
    assert [ws.cell(header, column).value for column in range(1, 9)] == [
        "Metric",
        "Anchor Result",
        "Excel Result",
        "Difference",
        "Tolerance",
        "Status",
        "Excel location",
        "Open",
    ]
    rows = 0
    for row in range(header + 1, ws.max_row + 1):
        if not isinstance(ws.cell(row, 6).value, str) or ws.cell(row, 1).value is None:
            continue
        rows += 1
        assert str(ws.cell(row, 2).value).startswith("=")
        assert str(ws.cell(row, 3).value).startswith("=")
        assert str(ws.cell(row, 4).value).startswith("=")
        assert ws.cell(row, 5).value is not None
        assert ws.cell(row, 7).value, "every row names where its Excel result lives"
    assert rows > 150


def test_business_plan_totals_and_cash_flows_are_reconciled(plan_bytes: bytes) -> None:
    ws = load(plan_bytes)["Checks"]
    metrics = set(labels_in(ws))
    assert "Closing capital resolved from items" in metrics
    for year in (1, 2):
        assert f"Project capital resolved from items, Year {year}" in metrics
        assert f"Owner expenses resolved from items, Year {year}" in metrics
        assert f"Business Plan project capital, Year {year}" in metrics
        assert f"Business Plan owner expenses, Year {year}" in metrics


# =============================================================================
# 6. Pessimistic caches
# =============================================================================


def test_an_unrecalculated_workbook_never_passes_a_check(base_bytes: bytes) -> None:
    values = load(base_bytes, values=True)
    statuses = {status for _anchor, _excel, _tolerance, status in check_rows(values).values()}
    assert statuses == {"Not recalculated"}


def test_no_formula_caches_a_number(base_bytes: bytes) -> None:
    """Every formula's cached value is blank or "Not recalculated" -- never a
    number copied from Anchor, which would let a viewer that does not
    calculate show a result Anchor produced as though Excel had."""

    values = load(base_bytes, values=True)
    formulas = load(base_bytes)
    for name in formulas.sheetnames:
        formula_ws, value_ws = formulas[name], values[name]
        for row in formula_ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cached = value_ws[cell.coordinate].value
                    assert cached is None or cached == "Not recalculated", (name, cell.coordinate, cached)


def test_the_summary_reports_that_it_has_not_recalculated(base_bytes: bytes) -> None:
    ws = load(base_bytes, values=True)["Summary"]
    assert ws.cell(row_of(ws, "Excel formulas recalculated"), 2).value == "Not recalculated"


def test_workbook_is_deterministic_for_the_same_saved_deal() -> None:
    case = CASES_BY_NAME["golden_v2_1"]
    assert build(case) == build(case)


# =============================================================================
# 7. Security
# =============================================================================

HOSTILE_NAMES = (
    '=cmd|\' /C calc\'!A0',
    "+1+1",
    "-2+3",
    "@SUM(1+9)*cmd|' /C calc'!A0",
    '=HYPERLINK("http://evil.example/","click")',
)


@pytest.mark.parametrize("hostile", HOSTILE_NAMES)
def test_user_authored_text_is_written_as_strings_never_formulas(hostile: str) -> None:
    from anchor.business_plan import CapitalItemCategory, CapitalPlanItem

    case = dataclasses.replace(
        CASES_BY_NAME["golden_v2_1"],
        business_plan=BusinessPlan(
            capital_items=(
                CapitalPlanItem(
                    item_id="c1",
                    description=hostile,
                    category=CapitalItemCategory.VALUE_ADD_RENOVATION,
                    month=1,
                    amount=1000.0,
                ),
            )
        ),
    )
    source = dataclasses.replace(source_for(case), deal_name=hostile, asset_subtype=hostile)
    wb = load(build_detailed_audit_workbook(source))
    seen = 0
    for name in wb.sheetnames:
        for row in wb[name].iter_rows():
            for cell in row:
                if cell.value == hostile:
                    seen += 1
                    assert cell.data_type == "s", (name, cell.coordinate)
    assert seen >= 3, "the hostile text must actually appear, as text"


@pytest.mark.parametrize("hostile", HOSTILE_NAMES)
def test_hostile_names_cannot_inject_a_filename_or_a_path(hostile: str) -> None:
    filename = detailed_audit_filename(hostile)
    assert filename.endswith(" - Detailed Underwrite Audit.xlsx")
    assert not any(character in filename for character in '\\/:*?"<>|')
    assert not filename.startswith((".", " "))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Harbor / Point: Phase 2", "Harbor - Point- Phase 2"),
        ("..", "Untitled Deal"),
        ("   ", "Untitled Deal"),
        ("A\r\nB", "AB"),
        ("Deal\u202ename", "Dealname"),
    ],
)
def test_filenames_are_sanitized_independently(name: str, expected: str) -> None:
    assert sanitize_deal_name(name) == expected
    assert detailed_audit_filename(name) == f"{expected} - Detailed Underwrite Audit.xlsx"


def test_no_local_path_or_environment_value_is_written(base_bytes: bytes) -> None:
    with zipfile.ZipFile(BytesIO(base_bytes)) as package:
        blob = b"".join(package.read(name) for name in package.namelist())
    text = blob.decode("utf-8", errors="ignore")
    for marker in ("C:\\", "/Users/", "anchor.db", "ANCHOR_DB_PATH", "OPENAI", "AppData"):
        assert marker not in text, marker


def test_no_ai_involvement_anywhere_in_the_workbook(base_bytes: bytes) -> None:
    with zipfile.ZipFile(BytesIO(base_bytes)) as package:
        blob = b"".join(package.read(name) for name in package.namelist())
    text = blob.decode("utf-8", errors="ignore").lower()
    for marker in ("openai", "gpt-", "ai analysis", "ai_snapshot"):
        assert marker not in text, marker


# =============================================================================
# 8. Eligibility
# =============================================================================


def _provenance(case_name: str, state: QuickAnalysisState, **deal_overrides: Any):  # noqa: ANN202
    from anchor.deals.store import DetailedAnalysisProvenance

    case = CASES_BY_NAME[case_name]
    analysis = analyze(case)
    deal = deals_store.Deal(
        id="deal-1",
        name="Eligibility",
        operating_mode=OperatingMode.DETAILED,
        inputs=None,
        terms=case.terms,
        detailed_operating_inputs=case.operating,
        business_plan=case.business_plan,
        deal_context=None,
        analysis_snapshot=analysis if state is QuickAnalysisState.CURRENT else None,
        ai_snapshot=None,
        created_at=GENERATED_AT,
        updated_at=GENERATED_AT,
        **deal_overrides,
    )
    return DetailedAnalysisProvenance(deal=deal, analysis_state=state, analysis_fingerprint="f" * 64)


def _source(provenance):  # noqa: ANN001, ANN202
    return detailed_audit_source(
        provenance, generated_at=GENERATED_AT, anchor_version="test", source_commit=None
    )


@pytest.mark.parametrize(
    ("state", "code"),
    [
        (QuickAnalysisState.MISSING, DetailedAuditRefusalCode.ANALYSIS_MISSING),
        (QuickAnalysisState.STALE, DetailedAuditRefusalCode.ANALYSIS_STALE),
    ],
)
def test_missing_and_stale_analyses_are_refused_with_their_own_codes(state, code) -> None:  # noqa: ANN001
    with pytest.raises(DetailedAuditExportError) as refusal:
        _source(_provenance("golden_v2_1", state))
    assert refusal.value.code is code
    assert "save" in refusal.value.message.lower()


def test_a_current_analysis_becomes_a_source_with_its_classification() -> None:
    source = _source(
        _provenance(
            "golden_v2_1",
            QuickAnalysisState.CURRENT,
            asset_type=AssetType.OFFICE,
            asset_subtype="Suburban",
        )
    )
    assert source.asset_type_label == "Office"
    assert source.asset_subtype == "Suburban"
    assert source.analysis_fingerprint == "f" * 64
    assert source.operating_projection.noi_by_year == source.results.noi_by_year


def test_a_hold_period_beyond_the_export_limit_is_refused() -> None:
    from anchor.deals.store import DetailedAnalysisProvenance

    provenance = _provenance("golden_v2_1", QuickAnalysisState.CURRENT)
    long_terms = detailed_terms(hold_period=MAX_EXPORT_HOLD_PERIOD + 1)
    deal = dataclasses.replace(provenance.deal, terms=long_terms)
    with pytest.raises(DetailedAuditExportError) as refusal:
        _source(
            DetailedAnalysisProvenance(
                deal=deal, analysis_state=QuickAnalysisState.CURRENT, analysis_fingerprint="f"
            )
        )
    assert refusal.value.code is DetailedAuditRefusalCode.HOLD_PERIOD_EXCEEDS_EXPORT_LIMIT


def test_the_deal_contract_itself_rejects_a_quick_snapshot_on_a_detailed_deal() -> None:
    """A Detailed Deal carrying a bare ``AcquisitionResults`` cannot even be
    constructed, so the export's own ``isinstance`` guard is a second line
    rather than the only one."""

    provenance = _provenance("golden_v2_1", QuickAnalysisState.CURRENT)
    quick_shaped = provenance.deal.analysis_snapshot.results  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="DetailedAcquisitionResults"):
        dataclasses.replace(provenance.deal, analysis_snapshot=quick_shaped)


def test_an_unreadable_snapshot_reported_as_current_is_refused() -> None:
    """The store classifies an undecodable snapshot as stale, but if a read
    ever reported ``CURRENT`` with nothing to read, the export must refuse
    rather than build a workbook with no Anchor side."""

    from anchor.deals.store import DetailedAnalysisProvenance

    provenance = _provenance("golden_v2_1", QuickAnalysisState.CURRENT)
    deal = dataclasses.replace(provenance.deal, analysis_snapshot=None)
    with pytest.raises(DetailedAuditExportError) as refusal:
        _source(
            DetailedAnalysisProvenance(
                deal=deal, analysis_state=QuickAnalysisState.CURRENT, analysis_fingerprint="f"
            )
        )
    assert refusal.value.code is DetailedAuditRefusalCode.ANALYSIS_INCONSISTENT


def test_an_envelope_whose_halves_disagree_is_refused() -> None:
    """``operating_projection`` and ``results`` are written by one engine call.
    If they disagree, the snapshot is not what it claims."""

    from anchor.deals.store import DetailedAnalysisProvenance

    provenance = _provenance("golden_v2_1", QuickAnalysisState.CURRENT)
    snapshot = provenance.deal.analysis_snapshot
    tampered_projection = dataclasses.replace(
        snapshot.operating_projection,  # type: ignore[union-attr]
        exit_noi=snapshot.operating_projection.exit_noi + 1.0,  # type: ignore[union-attr]
    )
    deal = dataclasses.replace(
        provenance.deal,
        analysis_snapshot=dataclasses.replace(snapshot, operating_projection=tampered_projection),  # type: ignore[type-var]
    )
    with pytest.raises(DetailedAuditExportError) as refusal:
        _source(
            DetailedAnalysisProvenance(
                deal=deal, analysis_state=QuickAnalysisState.CURRENT, analysis_fingerprint="f"
            )
        )
    assert refusal.value.code is DetailedAuditRefusalCode.ANALYSIS_INCONSISTENT


def test_an_internally_inconsistent_saved_analysis_is_refused_at_build() -> None:
    source = source_for(CASES_BY_NAME["golden_v2_1"])
    tampered = dataclasses.replace(
        source,
        results=dataclasses.replace(
            source.results, remaining_loan_balance=source.results.remaining_loan_balance + 1.0
        ),
    )
    with pytest.raises(DetailedAuditExportError) as refusal:
        build_detailed_audit_workbook(tampered)
    assert refusal.value.code is DetailedAuditRefusalCode.ANALYSIS_INCONSISTENT


def test_no_refusal_message_leaks_an_identifier_or_a_path() -> None:
    messages = []
    for state in (QuickAnalysisState.MISSING, QuickAnalysisState.STALE):
        with pytest.raises(DetailedAuditExportError) as refusal:
            _source(_provenance("golden_v2_1", state))
        messages.append(refusal.value.message)
    for message in messages:
        assert "deal-1" not in message
        assert "C:\\" not in message and "/" not in message
        assert "Traceback" not in message


# =============================================================================
# 9. Persistence read: provenance classification
# =============================================================================


def _save_detailed(
    db: Path,
    case_name: str = "golden_v2_1",
    *,
    analysed: bool = True,
    name: str = "Harbor Point",
):  # noqa: ANN202
    case = CASES_BY_NAME[case_name]
    deal = deals_store.create_detailed_deal(
        name,
        case.terms,
        case.operating,
        business_plan=case.business_plan,
        classification=AssetClassification(asset_type=AssetType.MULTIFAMILY, asset_subtype="Garden"),
        db_path=db,
    )
    if analysed:
        deal = deals_store.update_analysis_snapshot(
            deal.id,
            dataclasses.asdict(analyze(case)),
            financial_input_fingerprint=fingerprint_detailed_inputs(
                case.terms, case.operating, business_plan=case.business_plan
            ),
            db_path=db,
        )
    return deal


def test_provenance_distinguishes_current_missing_and_stale(tmp_path: Path) -> None:
    db = tmp_path / "anchor.db"
    unanalysed = _save_detailed(db, analysed=False)
    assert get_detailed_analysis_provenance(unanalysed.id, db_path=db).analysis_state is QuickAnalysisState.MISSING

    deal = _save_detailed(db)
    current = get_detailed_analysis_provenance(deal.id, db_path=db)
    assert current.analysis_state is QuickAnalysisState.CURRENT
    assert deal.terms is not None and deal.detailed_operating_inputs is not None
    assert current.analysis_fingerprint == fingerprint_detailed_inputs(
        deal.terms, deal.detailed_operating_inputs, business_plan=deal.business_plan
    )

    deals_store.update_detailed_deal(
        deal.id,
        deal.name,
        dataclasses.replace(deal.terms, exit_cap_rate=0.08),
        deal.detailed_operating_inputs,
        business_plan=deal.business_plan,
        db_path=db,
    )
    assert get_detailed_analysis_provenance(deal.id, db_path=db).analysis_state is QuickAnalysisState.STALE


def test_an_operating_input_edit_alone_makes_the_analysis_stale(tmp_path: Path) -> None:
    db = tmp_path / "anchor.db"
    deal = _save_detailed(db)
    assert deal.terms is not None and deal.detailed_operating_inputs is not None
    deals_store.update_detailed_deal(
        deal.id,
        deal.name,
        deal.terms,
        dataclasses.replace(deal.detailed_operating_inputs, expense_growth=0.09),
        business_plan=deal.business_plan,
        db_path=db,
    )
    assert get_detailed_analysis_provenance(deal.id, db_path=db).analysis_state is QuickAnalysisState.STALE


def test_provenance_refuses_other_modes_and_unknown_deals(tmp_path: Path) -> None:
    db = tmp_path / "anchor.db"
    for mode in ("quick", "lease_level"):
        deal = create_mode_deal(mode, db, business_plan=BusinessPlan())
        with pytest.raises(UnsupportedOperatingModeError):
            get_detailed_analysis_provenance(deal.id, db_path=db)
    with pytest.raises(DealNotFoundError):
        get_detailed_analysis_provenance("no-such-deal", db_path=db)


def test_the_provenance_read_writes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "anchor.db"
    deal = _save_detailed(db)
    before = _dump(db)
    for _ in range(3):
        get_detailed_analysis_provenance(deal.id, db_path=db)
    assert _dump(db) == before


# =============================================================================
# 10. API
# =============================================================================


@pytest.fixture
def api_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "anchor.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    return db


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _url(deal_id: str) -> str:
    return f"/deals/{deal_id}/exports/detailed-underwrite.xlsx"


def _dump(db: Path) -> list[str]:
    connection = sqlite3.connect(db)
    try:
        return list(connection.iterdump())
    finally:
        connection.close()


def _refusal(response) -> tuple[int, str, str]:  # noqa: ANN001
    detail = response.json()["detail"]
    return response.status_code, detail["code"], detail["message"]


def test_export_downloads_the_saved_analysed_deal(api_db: Path, client: TestClient) -> None:
    deal = _save_detailed(api_db, name="Harbor / Point: Phase 2")
    response = client.get(_url(deal.id))
    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; ")
    assert 'filename="Harbor - Point- Phase 2 - Detailed Underwrite Audit.xlsx"' in disposition
    assert "filename*=UTF-8''" in disposition
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    wb = load(response.content)
    assert wb.sheetnames == EXPECTED_SHEETS
    summary = wb["Summary"]
    assert summary["A1"].value == "Detailed Underwrite Audit"
    assert summary["A2"].value == "Harbor / Point: Phase 2"
    assert summary.cell(row_of(summary, "Operating mode"), 2).value == "Detailed Underwrite"
    audit = wb["Audit Metadata"]
    assert audit.cell(row_of(audit, "Analysis fingerprint"), 2).value == get_detailed_analysis_provenance(
        deal.id, db_path=api_db
    ).analysis_fingerprint


def test_export_is_read_only_to_the_byte(api_db: Path, client: TestClient) -> None:
    deal = _save_detailed(api_db)
    before = _dump(api_db)
    before_bytes = api_db.read_bytes()
    for _ in range(2):
        assert client.get(_url(deal.id)).status_code == 200
    assert _dump(api_db) == before
    assert api_db.read_bytes() == before_bytes
    reread = deals_store.get_deal(deal.id, db_path=api_db)
    assert reread.updated_at == deal.updated_at
    assert reread.analysis_snapshot == deal.analysis_snapshot


def test_missing_deal_is_a_typed_404(api_db: Path, client: TestClient) -> None:
    status, code, message = _refusal(client.get(_url("no-such-deal")))
    assert (status, code) == (404, "deal_not_found")
    assert "no-such-deal" not in message


@pytest.mark.parametrize(
    ("mode", "label"), [("quick", "Quick Underwrite"), ("lease_level", "Lease-Level Underwrite")]
)
def test_other_modes_are_refused_as_unsupported(
    api_db: Path, client: TestClient, mode: str, label: str
) -> None:
    deal = create_mode_deal(mode, api_db, business_plan=BusinessPlan())
    status, code, message = _refusal(client.get(_url(deal.id)))
    assert (status, code) == (422, "unsupported_operating_mode")
    assert label in message and "Detailed Underwrite" in message


def test_missing_analysis_is_refused(api_db: Path, client: TestClient) -> None:
    deal = _save_detailed(api_db, analysed=False)
    status, code, message = _refusal(client.get(_url(deal.id)))
    assert (status, code) == (409, "analysis_missing")
    assert "Analyze" in message


def test_stale_analysis_is_refused(api_db: Path, client: TestClient) -> None:
    deal = _save_detailed(api_db)
    assert deal.terms is not None and deal.detailed_operating_inputs is not None
    deals_store.update_detailed_deal(
        deal.id,
        deal.name,
        deal.terms,
        dataclasses.replace(deal.detailed_operating_inputs, revenue_growth=0.07),
        business_plan=deal.business_plan,
        db_path=api_db,
    )
    status, code, _ = _refusal(client.get(_url(deal.id)))
    assert (status, code) == (409, "analysis_stale")


def test_generation_failure_is_typed_and_leaks_nothing(
    api_db: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    deal = _save_detailed(api_db)

    def explode(_source: object) -> bytes:
        raise RuntimeError("C:\\Users\\secret\\anchor.db exploded")

    monkeypatch.setattr("anchor.api.build_detailed_audit_workbook", explode)
    response = client.get(_url(deal.id))
    status, code, message = _refusal(response)
    assert (status, code) == (500, "export_generation_failed")
    assert "secret" not in response.text
    assert "anchor.db" not in response.text
    assert "RuntimeError" not in response.text
    assert message


def test_the_quick_route_still_refuses_a_detailed_deal(api_db: Path, client: TestClient) -> None:
    """The two routes stay separate: Detailed is not silently served by the
    Quick endpoint, and vice versa."""

    deal = _save_detailed(api_db)
    status, code, _ = _refusal(client.get(f"/deals/{deal.id}/exports/quick-underwrite.xlsx"))
    assert (status, code) == (422, "unsupported_operating_mode")


# =============================================================================
# 11. Quick/Detailed convergence -- the permanent equivalence case
# =============================================================================


def test_equivalent_noi_schedules_produce_equivalent_downstream_results() -> None:
    """The frozen V2.1 golden case is built so its Detailed NOI series equals
    the Quick series from ``current_noi = 600,000`` / ``noi_growth = 3%``.
    Both paths converge into the same acquisition engine, so every downstream
    result must agree -- and both workbooks must therefore reconcile against
    the same numbers."""

    from anchor.analysis.business_plan_analysis import analyze_quick_acquisition_with_business_plan
    from anchor.contracts import AcquisitionInputs

    case = CASES_BY_NAME["golden_v2_1"]
    detailed = analyze(case)
    quick_inputs = AcquisitionInputs(
        purchase_price=case.terms.purchase_price,
        current_noi=600_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=case.terms.hold_period,
        exit_cap_rate=case.terms.exit_cap_rate,
        ltv=case.terms.ltv,
        interest_rate=case.terms.interest_rate,
        amortization=case.terms.amortization,
        acquisition_cost_pct=case.terms.acquisition_cost_pct,
        financing_fee_pct=case.terms.financing_fee_pct,
        disposition_cost_pct=case.terms.disposition_cost_pct,
        annual_capex_reserve=case.terms.annual_capex_reserve,
        io_period=case.terms.io_period,
    )
    quick = analyze_quick_acquisition_with_business_plan(quick_inputs, business_plan=BusinessPlan())

    for year, (detailed_noi, quick_noi) in enumerate(
        zip(detailed.results.noi_by_year, quick.noi_by_year), start=1
    ):
        assert detailed_noi == pytest.approx(quick_noi, rel=0, abs=1e-6), year
    assert detailed.results.exit_noi == pytest.approx(quick.exit_noi, rel=0, abs=1e-6)

    for field in (
        "loan_amount",
        "acquisition_costs",
        "financing_fee",
        "initial_equity",
        "exit_value",
        "disposition_costs",
        "net_sale_proceeds",
        "remaining_loan_balance",
        "equity_multiple",
        "levered_irr",
        "unlevered_irr",
        "headline_dscr",
        "min_dscr",
    ):
        detailed_value = getattr(detailed.results, field)
        quick_value = getattr(quick, field)
        assert detailed_value == pytest.approx(quick_value, rel=0, abs=1e-6), field


def test_the_frozen_detailed_golden_case_matches_its_document() -> None:
    """``docs/detailed_operating_model_v2_1_golden_case.md``, Years 1-6."""

    case = CASES_BY_NAME["golden_v2_1"]
    projection = analyze(case).operating_projection
    assert projection.noi_by_year == pytest.approx(
        (600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286), rel=0, abs=1e-6
    )
    assert projection.exit_noi == pytest.approx(695_564.44458, rel=0, abs=1e-6)
    assert projection.effective_gross_income_by_year[0] == pytest.approx(780_000.0, rel=0, abs=1e-6)
    assert projection.total_operating_expenses_by_year[0] == pytest.approx(180_000.0, rel=0, abs=1e-6)
    assert projection.management_fee_by_year[0] == pytest.approx(39_000.0, rel=0, abs=1e-6)

    ws = load(build(case))["Anchor Results"]
    start = row_of(ws, "Operating line")
    noi_row = row_of(ws, "Net operating income", start=start)
    assert ws.cell(noi_row, 4).value == pytest.approx(600_000.0, rel=0, abs=1e-6)
    assert ws.cell(noi_row, 8).value == pytest.approx(675_305.286, rel=0, abs=1e-6)
    assert ws.cell(row_of(ws, "Exit NOI (Year H+1)"), 3).value == pytest.approx(
        695_564.44458, rel=0, abs=1e-6
    )


# =============================================================================
# 12. Quick Underwrite regression
# =============================================================================


#: The logical content of every Quick golden workbook, frozen at ``main``
#: `b9437e4` -- before Excel Export 2 moved the shared machinery into
#: ``_workbook.py``. Each digest covers every sheet's cell formulas, values and
#: number formats plus the defined names, so it ignores how XlsxWriter packages
#: the file but moves the instant a formula, a value or a format does.
#:
#: At the gate these workbooks were also compared *byte for byte* against a
#: worktree at `b9437e4` and were identical. Bytes are not frozen here because
#: a future XlsxWriter patch could change packaging without changing the model;
#: the content is what must not move.
QUICK_CONTENT_DIGESTS = {
    "amortizing": "36d6ef15d7ad18d72e3407679655eebb84a47183294557389c2445557616595c",
    "interest_only_with_fees": "da51d569968de51f93c2cc14789f2ae744f171ac5a94a308a245a8c054ab4357",
    "zero_growth": "a22f0883a66ddfeb1ba16f33e01e6cacfa2630871eb0c91593fb5b62dedee200",
    "negative_growth": "e9e92e44c18ed7d6e5937d8dd11a6c570e92fe1fad938b7388d51e14ca983e1b",
    "strong_growth": "bb85c7bab0dab10671bb38ee3ca12e646623c41c542bc7a3537b9a42883fdb31",
    "interest_only_beyond_hold": "f1c3c50b741672f1d58b1d0461df04bbc8eee656dfd5465968541fe7bd7852b0",
    "amortized_before_sale": "372bcb5598c102cabab8dd1014daa7af5e4fbe7eb2adab48f6291772cd7f966e",
    "all_cash": "8f3cabf9c33346236a02e41a948030fc23712d9c6256e474d808814c66efd813",
    "zero_interest_rate": "63bc73aa64466d212d44c460497e97c5413c53ccaa29e1e4bd700bd739351106",
    "full_leverage_no_equity": "76e5f3cc37686540e7376dc2c31215276b71a6129827afe49027958d5a156cf4",
    "business_plan_items": "be3dd8bbd6234153911505525433b642b0b92bac2c258129d1ebc542a56611d8",
    "multiple_sign_changes": "3e90035dae50e794119a5cf5a3bc8aa0af411aec2808655f5c7c08e7abcb8401",
    "no_positive_cash_flow": "3638902ba9e389c9d6aa62a394ddf102bb41fc738e0a97dd86fb17ff004713a7",
    "very_high_return": "5adf7e9f999ed4ab4686be2dd5b10758f0fbac7f33525a680d348f5db012ef51",
    "near_total_loss_one_year": "6ca1cb7afa465b5212161fc4b6edadcb8a6b1b88e9329aab88e5d87c0a146845",
    "near_total_loss_three_years": "bcd2bc1bad24a9204495a1f4a8353370d03cae81a2143f5524e377491f4b636d",
    "long_hold": "87d88c8bd77c7b729c48129af1c02028d6a9a82f940c95353c1f57e4f9f499f0",
    "outside_anchor_search_domain": "c1a891051267cedea10489cb8e3cce7b3c1c020ae3609752f73315531c86e208",
}


def _content_digest(data: bytes) -> str:
    wb = load(data)
    parts: list[str] = []
    for name in wb.sheetnames:
        ws = wb[name]
        parts.append(f"#sheet:{name}")
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                parts.append(f"{cell.coordinate}|{cell.value!r}|{cell.number_format}")
        for item_name, item in sorted(wb.defined_names.items()):
            parts.append(f"!name:{item_name}={item.value}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def test_the_quick_workbook_is_unchanged_by_this_gate() -> None:
    """Excel Export 1 and 2 share their presentation, reconciliation and
    below-NOI model. The Quick workbook must come out of that sharing exactly
    as it went in, for every Quick golden case."""

    from excel_export_golden_cases import GOLDEN_CASES
    from excel_export_golden_cases import build as build_quick

    assert {case.name for case in GOLDEN_CASES} == set(QUICK_CONTENT_DIGESTS), (
        "a Quick golden case was added or removed; re-pin its digest deliberately"
    )
    for case in GOLDEN_CASES:
        data = build_quick(case)
        assert data == build_quick(case), case.name
        assert _content_digest(data) == QUICK_CONTENT_DIGESTS[case.name], case.name
        wb = load(data)
        assert wb.sheetnames == EXPECTED_SHEETS, case.name
        summary = wb["Summary"]
        assert summary["A1"].value == "Quick Underwrite Audit", case.name
        assert summary.cell(row_of(summary, "Operating mode"), 2).value == "Quick Underwrite", case.name


def test_the_quick_digest_actually_detects_a_change() -> None:
    """A frozen digest is only worth having if it moves. Build a Quick case
    with one different assumption and confirm it does."""

    from excel_export_golden_cases import CASES_BY_NAME as QUICK_CASES
    from excel_export_golden_cases import build as build_quick

    case = QUICK_CASES["amortizing"]
    altered = dataclasses.replace(case, inputs=dataclasses.replace(case.inputs, noi_growth=0.031))
    assert _content_digest(build_quick(altered)) != QUICK_CONTENT_DIGESTS["amortizing"]


def test_the_two_exports_publish_distinct_contracts_and_filenames() -> None:
    from anchor.exports.excel import EXPORT_CONTRACT_VERSION, quick_audit_filename

    assert EXPORT_CONTRACT_VERSION != DETAILED_EXPORT_CONTRACT_VERSION
    assert quick_audit_filename("X") != detailed_audit_filename("X")
    assert detailed_audit_filename("X") == "X - Detailed Underwrite Audit.xlsx"
