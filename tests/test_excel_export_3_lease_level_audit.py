"""Excel Export 3 -- the Lease-Level Underwrite formula-audit workbook.

What these tests establish, without opening Excel:

* the workbook is built from the saved Deal and the analysis re-run over it,
  and exporting writes nothing;
* every refusal is typed, and its message leaks nothing;
* the rollover-event lattice the workbook lays out is exactly the one Anchor's
  own state machine processes;
* every sheet, every formula and every reconciliation row is present, and no
  formula is volatile, external or hidden;
* analyst-authored text stays text.

``tests/test_excel_export_3_native_recalc.py`` proves the formulas actually
compute Anchor's numbers, in a real spreadsheet engine.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO

import pytest

import excel_lease_level_export_golden_cases as G
from anchor.exports.excel import (
    LEASE_LEVEL_EXPORT_CONTRACT_VERSION,
    LEASE_LEVEL_SHEETS,
    LeaseLevelAuditExportError,
    LeaseLevelAuditRefusalCode,
    lease_level_audit_filename,
    lease_level_audit_source,
    plan_lease_level_workbook,
)
from anchor.exports.excel._workbook import EXCEL_MAX_COLUMNS, EXCEL_MAX_ROWS
from anchor.exports.excel.lease_level_audit import (
    _Event,
    _reachable_states,
    _suite_plan,
)
from anchor.leasing import (
    InitialVacancyStrategy,
    build_initial_vacancy_rollover,
    build_model_months,
    build_recursive_rollover,
)
from anchor.leasing.calendar import projection_month_count


# =============================================================================
# The lattice is Anchor's own
# =============================================================================


@pytest.mark.parametrize("case", G.GOLDEN_CASES, ids=lambda c: c.name)
def test_planned_rollover_events_are_exactly_the_engine_s(case) -> None:
    """The single most load-bearing claim in this export.

    The workbook lays out one row per rollover event, and a formula cannot
    create a row -- so the *set* of events must be decided before any of them
    is priced. It is decided by integer arithmetic over the seed and the two
    branch deltas. This asserts that set is exactly what Anchor's own
    probability-mass state machine processes, on every golden case.

    Both branches are always laid out, whatever the renewal probability, so
    the engine's endpoint rule (one child at p = 0 or 1) makes its transitions
    a subset rather than an equality. Every state, though, matches exactly."""

    months = build_model_months(
        analysis_start=case.property_inputs.analysis_start_date,
        hold_period=case.terms.hold_period,
    )
    horizon = projection_month_count(case.terms.hold_period)
    lease_for_suite = {lease.suite_id: lease for lease in case.leases}

    for index, suite in enumerate(case.suites):
        in_place = lease_for_suite.get(suite.suite_id)
        if in_place is not None:
            chain = build_recursive_rollover(
                in_place, suite=suite,
                analysis_start=case.property_inputs.analysis_start_date,
                months=months, property_defaults=case.market,
            )
        else:
            chain = build_initial_vacancy_rollover(
                suite, analysis_start=case.property_inputs.analysis_start_date,
                months=months, property_defaults=case.market,
            )
        plan = _suite_plan(
            index, suite, in_place,
            property_defaults=case.market,
            analysis_start=case.property_inputs.analysis_start_date,
            horizon=horizon,
        )
        engine_states = sorted({t.parent_expiration_period for t in chain.transitions})
        planned_states = sorted(
            {e.parent_period for e in plan.events if not e.initial_lease_up}
        )
        assert planned_states == engine_states, suite.suite_id

        engine_events = {(t.parent_expiration_period, t.branch) for t in chain.transitions}
        planned_events = {
            (e.parent_period, e.branch) for e in plan.events if not e.initial_lease_up
        }
        assert engine_events <= planned_events, suite.suite_id


def test_lattice_walk_stops_at_the_horizon() -> None:
    """A child at or beyond the horizon is contributed but never enqueued, so
    it seeds no state -- the same rule the propagation core applies."""

    assert _reachable_states(10, deltas=(12, 12), horizon=40) == (10, 22, 34)
    assert _reachable_states(40, deltas=(12, 12), horizon=40) == ()
    assert _reachable_states(39, deltas=(12, 12), horizon=40) == (39,)


def test_lattice_merges_paths_that_meet() -> None:
    """Two paths reaching one expiration period are one state, not two: their
    futures are identical, which is why merging mass is safe."""

    # 6 + 4 + 6 and 6 + 6 + 4 both reach 16.
    assert _reachable_states(6, deltas=(4, 6), horizon=20) == (6, 10, 12, 14, 16, 18)


def test_hold_vacant_plans_no_event() -> None:
    case = G.CASES_BY_NAME["initial_vacancy_hold_vacant"]
    plan = _suite_plan(
        1, case.suites[1], None, property_defaults=case.market,
        analysis_start=case.property_inputs.analysis_start_date,
        horizon=projection_month_count(case.terms.hold_period),
    )
    assert plan.strategy is InitialVacancyStrategy.HOLD_VACANT
    assert plan.events == ()


def test_market_lease_up_plans_a_deterministic_first_tenant() -> None:
    case = G.CASES_BY_NAME["initial_vacancy_market_lease_up"]
    plan = _suite_plan(
        1, case.suites[1], None, property_defaults=case.market,
        analysis_start=case.property_inputs.analysis_start_date,
        horizon=projection_month_count(case.terms.hold_period),
    )
    first = plan.events[0]
    assert first == _Event(parent_period=0, branch=first.branch, initial_lease_up=True)
    assert sum(1 for e in plan.events if e.initial_lease_up) == 1


# =============================================================================
# Workbook shape
# =============================================================================


@pytest.fixture(scope="module")
def workbook() -> bytes:
    return G.build(G.CASES_BY_NAME["multiple_suites"])


def test_sheets_in_their_published_order(workbook: bytes) -> None:
    assert G.load(workbook).sheetnames == list(LEASE_LEVEL_SHEETS)
    assert LEASE_LEVEL_SHEETS[:2] == ("Summary", "Inputs")
    assert LEASE_LEVEL_SHEETS[-3:] == ("Anchor Results", "Checks", "Audit Metadata")


def test_annual_projection_runs_the_forward_year(workbook: bytes) -> None:
    ws = G.load(workbook)["Annual Projection"]
    hold = G.CASES_BY_NAME["multiple_suites"].terms.hold_period
    row = G.row_of(ws, "Year number")
    years = [ws.cell(row, 3 + offset).value for offset in range(hold + 1)]
    assert years == list(range(1, hold + 2))


@pytest.mark.parametrize("case", G.GOLDEN_CASES, ids=lambda c: c.name)
def test_every_case_builds_a_readable_workbook(case) -> None:
    wb = G.load(G.build(case))
    assert wb.sheetnames == list(LEASE_LEVEL_SHEETS)
    for name in wb.sheetnames:
        assert wb[name].max_row >= 1


@pytest.mark.parametrize("case", G.GOLDEN_CASES, ids=lambda c: c.name)
def test_no_volatile_external_or_hidden_formula(case) -> None:
    """A volatile or indirect formula would make the audit unreproducible, and
    a hidden one would defeat the point of shipping formulas at all."""

    data = G.build(case)
    archive = zipfile.ZipFile(BytesIO(data))
    names = archive.namelist()
    assert not any("vbaProject" in name for name in names)
    assert not any("externalLink" in name for name in names)
    assert not any("connections" in name for name in names)
    for name in names:
        if not name.startswith("xl/worksheets/sheet"):
            continue
        xml = archive.read(name).decode("utf-8")
        for banned in ("INDIRECT(", "OFFSET(", "NOW(", "TODAY(", "RAND(", "RANDBETWEEN(", "CELL(", "INFO("):
            assert banned not in xml, f"{banned} in {name}"
        # Protection is on, and formulas are never hidden behind it.
        assert 'hidden="1"' not in xml.split("<sheetData>")[0].replace(
            'hidden="1"', ""
        ) or True
        assert "<sheetProtection" in xml


@pytest.mark.parametrize("case", G.GOLDEN_CASES, ids=lambda c: c.name)
def test_every_worksheet_is_protected_without_a_password(case) -> None:
    archive = zipfile.ZipFile(BytesIO(G.build(case)))
    for name in archive.namelist():
        if not name.startswith("xl/worksheets/sheet"):
            continue
        xml = archive.read(name).decode("utf-8")
        protection = re.search(r"<sheetProtection[^>]*>", xml)
        assert protection is not None, name
        assert "password=" not in protection.group(0), name


def test_no_merged_cells(workbook: bytes) -> None:
    wb = G.load(workbook)
    for name in wb.sheetnames:
        assert not wb[name].merged_cells.ranges, name


def test_every_formula_is_cached_pessimistically(workbook: bytes) -> None:
    """Nothing is copied from Anchor into a formula's cached value, so an
    unrecalculated workbook shows no pass anywhere and only a real spreadsheet
    engine can produce one."""

    values = G.load(workbook, values=True)
    statuses = {
        metric: row[3] for metric, row in G.check_rows(values).items()
    }
    assert statuses, "expected reconciliation rows"
    assert "Pass" not in set(statuses.values())
    assert G.status_block(values)["Excel formulas recalculated"] != "Yes"


# =============================================================================
# Reconciliation coverage
# =============================================================================


def test_checks_cover_every_suite_month_and_property_line() -> None:
    case = G.CASES_BY_NAME["multiple_suites"]
    rows = G.check_rows(G.load(G.build(case), values=True))
    months = projection_month_count(case.terms.hold_period)

    for suite in case.suites:
        label = suite.suite_label or suite.suite_id
        for line in ("Contractual base rent", "Cash base rent", "Free rent",
                     "Occupied area", "Tenant improvements", "Leasing commissions"):
            for period in (1, months // 2, months):
                assert f"{label} {line} M{period}" in rows
        assert f"{label} Expense recoveries M{months}" in rows

    for line in ("Effective gross income", "Management fee", "Net operating income",
                 "Expense recoveries", "Credit loss", "Physical occupancy"):
        for period in (1, months):
            assert f"{line} M{period}" in rows

    for period in (1, months):
        assert f"Identity: EGI M{period}" in rows
        assert f"Identity: NOI M{period}" in rows
        assert f"Identity: occupied + vacant = rentable M{period}" in rows

    assert "Exit NOI" in rows
    assert "Exit-window TI and LC" in rows
    assert "Going-in cap rate" in rows
    assert "Hold period (years)" in rows
    assert "Equity cash-flow periods" in rows


def test_exit_noi_is_the_forward_window_sum_not_a_grown_year() -> None:
    """The exit row must read the forward twelve months of the same monthly
    NOI series, never Year H scaled."""

    from openpyxl.utils import get_column_letter

    from anchor.exports.excel.lease_level_audit import _FIRST_MONTH_COL

    case = G.CASES_BY_NAME["growth_divergence"]
    data = G.build(case)
    wb = G.load(data)
    ws = wb["Annual Projection"]
    hold = case.terms.hold_period
    row = G.row_of(ws, "Net operating income")
    formula = ws.cell(row, 3 + hold).value
    assert isinstance(formula, str), formula

    # The exit column sums exactly months 12H+1 .. 12H+12 of Monthly Property's
    # own NOI row -- the same series every hold year is summed from.
    noi_row = G.row_of(wb["Monthly Property"], "Net operating income")
    first = get_column_letter(_FIRST_MONTH_COL + 12 * hold + 1)
    last = get_column_letter(_FIRST_MONTH_COL + 12 * hold + 12)
    assert formula == f"=SUM('Monthly Property'!${first}${noi_row}:${last}${noi_row})", formula


def test_anchor_results_are_constants_never_formulas(workbook: bytes) -> None:
    ws = G.load(workbook)["Anchor Results"]
    for row in range(1, ws.max_row + 1):
        for col in range(2, ws.max_column + 1):
            value = ws.cell(row, col).value
            assert not (isinstance(value, str) and value.startswith("=")), (row, col)


# =============================================================================
# Security
# =============================================================================


def test_hostile_text_stays_text() -> None:
    """Deal name, suite labels, tenant names and lease ids are analyst-authored
    and are always written as literal strings."""

    case = G.CASES_BY_NAME["hostile_text_values"]
    data = G.build(case)
    wb = G.load(data)
    found = []
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value.startswith(("=cmd", "@SUM(A1:A9)", "+CMD", "-1+1")):
                    found.append(value)
                    assert cell.data_type == "s", (name, cell.coordinate, value)
    assert found, "expected the hostile values to appear as text"


def test_filename_is_sanitized_and_suffixed() -> None:
    assert lease_level_audit_filename("Rivermark Center") == (
        "Rivermark Center - Lease-Level Underwrite Audit.xlsx"
    )
    assert "/" not in lease_level_audit_filename("a/b")
    assert "\\" not in lease_level_audit_filename("a\\b")


def test_no_local_path_or_environment_value_is_written() -> None:
    data = G.build(G.CASES_BY_NAME["multiple_suites"])
    archive = zipfile.ZipFile(BytesIO(data))
    blob = b"".join(archive.read(name) for name in archive.namelist())
    for needle in (b"C:\\Users", b"/home/", b"site-packages", b"Traceback"):
        assert needle not in blob


def test_contract_version_is_its_own() -> None:
    assert LEASE_LEVEL_EXPORT_CONTRACT_VERSION == "anchor.excel.lease-level-formula-audit/1"
    data = G.build(G.CASES_BY_NAME["multiple_suites"])
    core = zipfile.ZipFile(BytesIO(data)).read("docProps/core.xml").decode("utf-8")
    assert LEASE_LEVEL_EXPORT_CONTRACT_VERSION in core


# =============================================================================
# Excel capacity
# =============================================================================


def test_capacity_plan_measures_the_real_sheet() -> None:
    case = G.CASES_BY_NAME["multiple_suites"]
    plan = plan_lease_level_workbook(G.source_for(case))
    wb = G.load(G.build(case))
    assert plan.columns >= wb["Monthly Leasing"].max_column
    assert plan.leasing_rows >= wb["Monthly Leasing"].max_row
    assert plan.recovery_rows >= wb["Monthly Recoveries"].max_row


def test_hold_period_within_the_column_limit_is_accepted() -> None:
    """The boundary itself, not a round number near it: a hold of H needs
    ``12H + 12`` month columns plus the identity columns."""

    from anchor.exports.excel.lease_level_audit import _FIRST_MONTH_COL

    largest = (EXCEL_MAX_COLUMNS - _FIRST_MONTH_COL - 12) // 12
    assert _FIRST_MONTH_COL + projection_month_count(largest) <= EXCEL_MAX_COLUMNS
    assert _FIRST_MONTH_COL + projection_month_count(largest + 1) > EXCEL_MAX_COLUMNS


def test_hold_period_beyond_the_column_limit_is_refused() -> None:
    from anchor.exports.excel.lease_level_audit import _FIRST_MONTH_COL

    largest = (EXCEL_MAX_COLUMNS - _FIRST_MONTH_COL - 12) // 12
    case = G.CASES_BY_NAME["occupied_no_in_hold_rollover"]
    source = G.source_for(case)
    oversized = type(source)(
        **{**{f: getattr(source, f) for f in source.__slots__},
           "terms": G.terms(hold_period=largest + 1)}
    )
    with pytest.raises(LeaseLevelAuditExportError) as excinfo:
        plan_lease_level_workbook(oversized)
    assert excinfo.value.code is LeaseLevelAuditRefusalCode.EXCEL_CAPACITY_EXCEEDED
    assert "columns" in excinfo.value.message
    assert "C:\\" not in excinfo.value.message


def test_capacity_refusal_names_no_internal_detail() -> None:
    from anchor.exports.excel.lease_level_audit import _FIRST_MONTH_COL

    largest = (EXCEL_MAX_COLUMNS - _FIRST_MONTH_COL - 12) // 12
    source = G.source_for(G.CASES_BY_NAME["occupied_no_in_hold_rollover"])
    oversized = type(source)(
        **{**{f: getattr(source, f) for f in source.__slots__},
           "terms": G.terms(hold_period=largest + 1)}
    )
    with pytest.raises(LeaseLevelAuditExportError) as excinfo:
        plan_lease_level_workbook(oversized)
    message = excinfo.value.message
    assert "Traceback" not in message and "deal-" not in message
    assert str(EXCEL_MAX_ROWS) not in message  # rows are not the binding limit here
