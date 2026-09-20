"""Shared infrastructure for Anchor's formula-audit workbooks.

Excel Export 1 (Quick) and Excel Export 2 (Detailed) publish the *same*
workbook contract: eight sheets in one order, one presentation language, one
reconciliation vocabulary, one set of tolerances, and -- below the NOI line --
one model. That is not a coincidence to be papered over with a mode flag: it
is Anchor's own architecture. Quick and Detailed differ only in how they
*produce* an NOI schedule, and both hand the identical schedule to the single,
unmodified acquisition engine
(``docs/detailed_operating_model_v2_1_architecture.md`` "Quick/Detailed
Convergence"). ``OperatingProjectionLike`` is the seam there --
``noi_by_year``, ``exit_noi``, ``going_in_cap_rate`` -- and it is the seam
here.

So this module owns everything from the NOI row downward (debt, equity, sale,
returns, IRR, reconciliation, presentation) and each export owns what is
genuinely its own: its inputs, its operating build, and the words that
describe them. A subclass fills the Operating Projection sheet and publishes
the same small contract the engine's protocol publishes; every sheet after it
is written by the code below, identically for both modes.

Nothing here reads a database, resolves a Business Plan, or computes an
authoritative Anchor result. Every formula is written with a *pessimistic*
cached value, so an unrecalculated workbook can never show a pass.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timezone
from io import BytesIO
from typing import Any, Protocol

import xlsxwriter
from xlsxwriter.format import Format
from xlsxwriter.utility import xl_rowcol_to_cell
from xlsxwriter.worksheet import Worksheet

from ...engine.contracts import IrrStatus
from ...engine.debt import (
    calculate_amortization_schedule,
    calculate_io_months,
    calculate_io_payment,
    calculate_monthly_rate,
    calculate_scheduled_payment_count,
)

SUMMARY = "Summary"
INPUTS = "Inputs"
OPERATING = "Operating Projection"
DEBT = "Debt Schedule"
EQUITY = "Equity Cash Flow"
ANCHOR = "Anchor Results"
CHECKS = "Checks"
AUDIT = "Audit Metadata"

SHEET_ORDER: tuple[str, ...] = (
    SUMMARY,
    INPUTS,
    OPERATING,
    DEBT,
    EQUITY,
    ANCHOR,
    CHECKS,
    AUDIT,
)

#: Excel's hard worksheet limits. A workbook that would need more rows or
#: columns than these cannot be written at all, so an export that would exceed
#: them is refused with a typed, user-facing reason rather than producing a
#: file that is silently truncated (Excel Export 3).
EXCEL_MAX_ROWS = 1_048_576
EXCEL_MAX_COLUMNS = 16_384

#: The one text every unavailable figure is written as, on both sides of a
#: check: a missing number is never shown as zero.
UNAVAILABLE = "Unavailable"
#: The cached value of every status formula until a spreadsheet engine
#: recalculates it.
NOT_RECALCULATED = "Not recalculated"
PASS = "Pass"
PASS_BOTH_UNAVAILABLE = "Pass (both unavailable)"
FAIL = "FAIL"
EXCEL_ERROR = "Excel error"
NOT_LIKE_FOR_LIKE = "Not like-for-like"

#: IRR availability, in the vocabulary both sides of the check use. The first
#: five are what the workbook's sign-rule formulas can produce; the last two are
#: Anchor-only numerical outcomes Excel cannot reproduce (documented).
IRR_STATUS_TEXT: dict[IrrStatus, str] = {
    IrrStatus.DEFINED: "Available",
    IrrStatus.NO_NONZERO_CASH_FLOW: "No nonzero cash flow",
    IrrStatus.FIRST_NONZERO_NOT_NEGATIVE: "First nonzero cash flow not negative",
    IrrStatus.NO_POSITIVE_CASH_FLOW: "No positive cash flow",
    IrrStatus.MULTIPLE_SIGN_CHANGES: "More than one sign change",
    IrrStatus.ROOT_OUTSIDE_SEARCH_DOMAIN: "Outside Anchor's IRR search domain",
    IrrStatus.NUMERICAL_FAILURE: "Anchor numerical failure",
}

# --- Tolerances --------------------------------------------------------------
#
# Anchor and Excel both compute in IEEE-754 double precision from the same
# unrounded inputs; they differ only in operation order (a SUM across a row
# versus Anchor's left-to-right subtraction, ``(1+r)^-N`` versus
# ``expm1(-N*log1p(r))``, twelve monthly steps per year). Those differences are
# a few units in the last place per operation. The tolerances below sit several
# orders of magnitude above that and far below any displayed digit.

#: Currency: the larger of one millionth of a currency unit and one part in
#: 10^10 of the Anchor value.
CURRENCY_ABSOLUTE_TOLERANCE = 1e-6
CURRENCY_RELATIVE_TOLERANCE = 1e-10
#: Ratios, rates and multiples (DSCR, cap rate, yields, cash-on-cash, equity
#: multiple): absolute.
RATIO_TOLERANCE = 1e-10
#: IRR: Excel's documented ``IRR`` convergence criterion (0.00001 percent).
#: Anchor bisects to a tighter bound, so Excel's stopping rule is the binding
#: precision.
IRR_TOLERANCE = 1e-7

# --- Presentation ------------------------------------------------------------

FONT = "Arial"
NAVY = "#1F3864"
HEADER_FILL = "#DCE3EE"
#: The vertical rule between one column header and the next.
#:
#: The rule alone is not what keeps a header its own -- that was the original
#: behaviour and it was too quiet, because a right-aligned header and the
#: left-aligned one beside it met at their shared cell boundary and read as a
#: single run of words. Separation is now real space (``_headers``: value
#: headers centred, descriptive headers indented), and the rule marks the
#: boundary inside it.
HEADER_RULE = "#8FA0BC"
SUBSECTION_FILL = "#EEF1F6"
INPUT_BLUE = "#0000FF"
INPUT_FILL = "#FFF7DC"
LINK_GREEN = "#00703C"
FROZEN_GRAY = "#595959"
FROZEN_FILL = "#F2F2F2"
NOTE_GRAY = "#595959"

NUM_CURRENCY = '#,##0_);(#,##0);"-"_)'
NUM_CURRENCY_CENTS = '#,##0.00_);(#,##0.00);"-"_)'
NUM_PERCENT = '0.00%_);(0.00%);"-"_)'
NUM_PERCENT_FINE = '0.0000%_);(0.0000%);"-"_)'
NUM_MULTIPLE = '0.00"x"_);(0.00"x");"-"_)'
NUM_MULTIPLE_FINE = '0.0000"x"_);(0.0000"x");"-"_)'
NUM_INTEGER = '0_);(0);"-"_)'
#: Sign flags and counts in the IRR audit: -1 reads as -1, not (1).
NUM_FLAG = "0;-0;0"
NUM_FACTOR = "0.000000_)"
NUM_SCIENTIFIC = "0.00E+00"
NUM_DATETIME = "yyyy-mm-dd hh:mm:ss"

LABEL_WIDTH = 58
UNITS_WIDTH = 21
PERIOD_WIDTH = 14
#: Excel's own width for a column whose width this workbook never sets.
DEFAULT_COLUMN_WIDTH = 8.43
#: A column width counts characters of the body font; a bold header character
#: is wider, and the cell keeps a character of padding. A header longer than
#: its column's allowance wraps rather than being clipped by its neighbour.
HEADER_CHARS_PER_WIDTH = 0.92
#: An ordinary-weight label holds slightly more characters than its column's
#: nominal width, because the width unit is a digit and prose is narrower than
#: that. Deliberately cautious: over-wrapping only costs a taller row.
LABEL_CHARS_PER_WIDTH = 1.05
#: Row height, in points, for one line of wrapped text.
HEADER_LINE_HEIGHT = 13.5
#: Indent levels applied to a header that has another header to its left.
HEADER_INDENT = 1
#: One indent level is three spaces of the normal font (ECMA-376 alignment).
INDENT_CHARS = 3

_PROTECTION = {
    "select_locked_cells": True,
    "select_unlocked_cells": True,
    "format_columns": True,
    "format_rows": True,
}


def _xref(sheet: str, row: int, col: int, *, absolute: bool = True) -> str:
    """A cross-sheet reference such as ``'Debt Schedule'!$C$12``."""

    return f"'{sheet}'!{xl_rowcol_to_cell(row, col, absolute, absolute)}"


def _cell(row: int, col: int, *, row_abs: bool = False, col_abs: bool = False) -> str:
    return xl_rowcol_to_cell(row, col, row_abs, col_abs)


def _abs(row: int, col: int) -> str:
    return xl_rowcol_to_cell(row, col, True, True)


def _range(sheet: str | None, row1: int, col1: int, row2: int, col2: int) -> str:
    body = f"{_abs(row1, col1)}:{_abs(row2, col2)}"
    return f"'{sheet}'!{body}" if sheet is not None else body


def _write_formula(ws: Worksheet, row: int, col: int, formula: str, cell_format: Format, cached: str) -> None:
    """Every formula in the workbook is written here, with a *string* cached
    value (blank or a "Not recalculated" status). XlsxWriter documents and
    accepts a string ``value``; its type stub declares ``int``."""

    ws.write_formula(row, col, formula, cell_format, cached)  # pyright: ignore[reportArgumentType]


def _humanize(token: str) -> str:
    return token.replace("_", " ").capitalize()


def _wrapped_lines(text: str, chars_per_line: int) -> int:
    """How many lines ``text`` needs when Excel wraps it at word boundaries.

    Greedy, like Excel: a word that does not fit starts a new line, and a word
    longer than the line is broken. Counting words rather than characters
    matters -- ``"... are not detected)"`` needs a third line that dividing the
    length would miss, and a row set one line short clips the text it wraps."""

    limit = max(1, chars_per_line)
    lines, current = 1, 0
    for word in text.split():
        length = len(word)
        while length > limit:  # a single word longer than the line
            if current:
                lines += 1
            lines += 1
            length -= limit
            current = 0
        if current == 0:
            current = length
        elif current + 1 + length <= limit:
            current += 1 + length
        else:
            lines += 1
            current = length
    return lines


@dataclass(frozen=True, slots=True)
class _Check:
    """One reconciliation row: an Anchor constant against an Excel result."""

    metric: str
    anchor: str
    excel: str
    location: str
    #: ``currency`` / ``ratio`` / ``irr`` compare within a tolerance;
    #: ``exact`` compares identity (numbers with ``=``, text with ``EXACT``).
    kind: str
    number_format: str
    key: str | None = None
    #: Whether the Anchor side is an *expression* that could itself error,
    #: rather than a frozen constant. A reconciliation against a saved Anchor
    #: value never needs this -- that cell is a number Anchor wrote. An
    #: identity row does: both of its sides are live formulas, and an error on
    #: either must read as an error rather than propagate out of the status
    #: cell and corrupt the pass/fail counts.
    guard_anchor: bool = False


@dataclass(frozen=True, slots=True)
class _InputSpec:
    key: str
    label: str
    units: str
    value: float
    number_format: str
    #: ``None`` keeps the Working Input equal to the Original Export and
    #: locked, with this note as its status.
    fixed_note: str | None = None
    name: str | None = None
    validation: dict[str, Any] | None = None


class AcquisitionTermsLike(Protocol):
    """The eleven acquisition/debt/exit assumptions both modes share.

    Structural rather than concrete because Quick supplies them on
    ``AcquisitionInputs`` and Detailed on ``AcquisitionTerms`` -- the same
    eleven names, by the architecture document's own construction
    (``docs/detailed_operating_model_v2_1_architecture.md`` Section 2.2).

    Read-only properties rather than attributes: both contracts are frozen
    dataclasses, and a protocol that declared settable attributes would not
    be satisfied by either of them -- correctly, since nothing here ever
    assigns to one."""

    @property
    def purchase_price(self) -> float: ...
    @property
    def hold_period(self) -> int: ...
    @property
    def exit_cap_rate(self) -> float: ...
    @property
    def ltv(self) -> float: ...
    @property
    def interest_rate(self) -> float: ...
    @property
    def amortization(self) -> int: ...
    @property
    def acquisition_cost_pct(self) -> float: ...
    @property
    def financing_fee_pct(self) -> float: ...
    @property
    def disposition_cost_pct(self) -> float: ...
    @property
    def annual_capex_reserve(self) -> float: ...
    @property
    def io_period(self) -> int: ...


class _Formats:
    """Cached XlsxWriter formats keyed by their properties."""

    def __init__(self, workbook: xlsxwriter.Workbook) -> None:
        self._workbook = workbook
        self._cache: dict[tuple[tuple[str, Any], ...], Format] = {}

    def get(self, **properties: Any) -> Format:
        merged = {"font_name": FONT, "font_size": 10, "valign": "vcenter", **properties}
        key = tuple(sorted(merged.items()))
        cached = self._cache.get(key)
        if cached is None:
            cached = self._workbook.add_format(merged)
            self._cache[key] = cached
        return cached

    # Roles ------------------------------------------------------------------

    def title(self) -> Format:
        return self.get(bold=True, font_size=14, font_color=NAVY)

    def note(self) -> Format:
        return self.get(italic=True, font_color=NOTE_GRAY)

    def section(self) -> Format:
        return self.get(bold=True, font_color="#FFFFFF", bg_color=NAVY)

    def subsection(self) -> Format:
        return self.get(bold=True, bg_color=SUBSECTION_FILL)

    def header(self, *, align: str = "right", indent: int = 0, wrap: bool = False) -> Format:
        """One column header: the band's fill, its rule underneath, and a
        vertical rule on its right edge separating it from the next header."""

        properties: dict[str, Any] = {
            "bold": True,
            "bg_color": HEADER_FILL,
            "bottom": 1,
            "right": 1,
            "right_color": HEADER_RULE,
            "align": align,
            # Bottom, not centred: a wrapped header's last line then sits on
            # the same baseline as the single-line headers beside it.
            "valign": "bottom",
        }
        if indent:
            properties["indent"] = indent
        if wrap:
            properties["text_wrap"] = True
        return self.get(**properties)

    def label(self, *, bold: bool = False, indent: int = 0, wrap: bool = False) -> Format:
        properties: dict[str, Any] = {"bold": bold} if bold else {}
        if indent:
            properties["indent"] = indent
        if wrap:
            properties["text_wrap"] = True
            properties["valign"] = "top"
        return self.get(**properties)

    def units(self) -> Format:
        return self.get(font_color=NOTE_GRAY)

    def text(self, *, bold: bool = False, wrap: bool = False) -> Format:
        properties: dict[str, Any] = {}
        if bold:
            properties["bold"] = True
        if wrap:
            properties["text_wrap"] = True
            properties["valign"] = "top"
        return self.get(**properties)

    def value(self, role: str, number_format: str, *, bold: bool = False) -> Format:
        properties: dict[str, Any] = {"num_format": number_format, "align": "right"}
        if bold:
            properties["bold"] = True
            properties["top"] = 1
        if role == "input":
            properties.update(font_color=INPUT_BLUE, bg_color=INPUT_FILL, locked=False)
        elif role == "link":
            properties["font_color"] = LINK_GREEN
        elif role == "frozen":
            properties.update(font_color=FROZEN_GRAY, bg_color=FROZEN_FILL)
        return self.get(**properties)

    def status(self, role: str = "calc") -> Format:
        properties: dict[str, Any] = {"align": "left"}
        if role == "link":
            properties["font_color"] = LINK_GREEN
        return self.get(**properties)


class _AuditWorkbookBase:
    """Builds one formula-audit workbook. Sheets are added in their final order
    first, then filled in dependency order so every cross-sheet reference is
    known when it is written.

    A subclass supplies four things and nothing else: the words that name the
    mode, the input rows, the Operating Projection sheet, and the checks for
    the lines that sheet adds. Everything below NOI is written here."""

    # --- Subclass contract ---------------------------------------------------

    #: ``"Quick Underwrite"`` / ``"Detailed Underwrite"``.
    MODE_LABEL: str = ""
    #: The workbook's own title, e.g. ``"Quick Underwrite Audit"``.
    WORKBOOK_TITLE: str = ""
    #: ``anchor.excel.<name>/<version>``.
    CONTRACT_VERSION: str = ""
    #: The one-line note under the Summary title.
    SUMMARY_NOTE: str = ""
    #: The closing note on Checks, explaining what this mode reconciles.
    CHECKS_NOTE: str = ""
    #: The NOI convention, for Audit Metadata.
    NOI_CONVENTION: str = ""
    #: The export's scope limitation, for Audit Metadata.
    SCOPE_NOTE: str = ""

    # --- Provenance copy ------------------------------------------------------
    #
    # Where the workbook tells an analyst *where Anchor's numbers came from*.
    # The defaults below describe Quick and Detailed, which freeze a **stored**
    # analysis snapshot whose fingerprint was verified against the saved inputs.
    #
    # A mode that has no persisted analysis must override all four. Excel
    # Export 3 does: ``lease_level_deals`` carries no ``analysis_snapshot``
    # column, so its workbook is built from an analysis Anchor **reran at
    # export** over the saved inputs. Saying "saved analysis" there would claim
    # a stored artifact that does not exist, and an audit workbook that
    # misdescribes its own provenance is wrong in the one way it cannot afford
    # to be. They are four strings rather than four conditionals so that the
    # claim each sheet makes is stated once, beside the others.

    #: The note under the Anchor Results title.
    ANCHOR_RESULTS_NOTE: str = (
        "Values produced by Anchor's deterministic engine and saved with this Deal's current "
        "analysis. They are constants, not Excel formulas, and never change with Working Inputs."
    )
    #: Summary's "Status at export" value.
    STATUS_AT_EXPORT: str = "Saved Deal; saved analysis current for the saved inputs"
    #: Audit Metadata's "Source" value.
    AUDIT_SOURCE_NOTE: str = (
        "The saved Anchor Deal and its current saved analysis. The analysis fingerprint was "
        "verified against the saved inputs and Business Plan at export."
    )
    #: The closing note on Debt Schedule, explaining where annual ending
    #: balances come from when the analysis records only the balance at sale.
    DEBT_BALANCE_NOTE: str = (
        "The saved analysis records the loan balance only at the sale. Annual ending balances "
        "come from Anchor's debt engine at export, from the saved inputs and saved payment; the "
        "final year equals the saved balance exactly."
    )

    #: The sheets this workbook holds, in their final order. Quick and Detailed
    #: keep the published eight; a mode whose model does not fit them (Excel
    #: Export 3's Lease-Level rent roll) names its own, and every sheet the
    #: shared code writes keeps its name and its place in both.
    SHEETS: tuple[str, ...] = SHEET_ORDER

    #: Whether this mode's rent roll produces variable below-NOI capital (TI
    #: and LC). ``False`` for Quick and Detailed, which have no rent roll: their
    #: saved analysis must carry an all-zero operating-capital schedule, and a
    #: non-zero one means the snapshot is not what it claims.
    HAS_OPERATING_CAPITAL: bool = False

    #: The sheet carrying the annual NOI row and the below-NOI block. Debt and
    #: Equity read their NOI, CapEx and Business Plan lines from it by name, so
    #: a mode that builds its annual view on a differently named sheet says so
    #: here rather than duplicating those builders.
    OPERATING_SHEET: str = OPERATING

    #: Published by ``_build_operating``: the Operating Projection row holding
    #: NOI for Years 1..H and, one column further right, the exit year. This
    #: and ``operating_rows`` are the whole of what the model below NOI knows
    #: about how NOI was produced.
    noi_row: int
    operating_rows: dict[str, int]

    def __init__(
        self,
        source: Any,
        *,
        acquisition: AcquisitionTermsLike,
        results: Any,
    ) -> None:
        self.source = source
        self.terms = acquisition
        self.results = results
        self.hold = acquisition.hold_period
        self.years = tuple(range(1, self.hold + 1))
        self.ending_balance_by_year = self._anchor_ending_balances()
        self._require_consistent_analysis()

        self.output = BytesIO()
        self.book = xlsxwriter.Workbook(
            self.output,
            {
                "in_memory": True,
                # Analyst-authored text is always written with write_string;
                # these options make a stray write() equally unable to turn
                # "=..." into a formula or a string into a number or a link.
                "strings_to_formulas": False,
                "strings_to_numbers": False,
                "strings_to_urls": False,
            },
        )
        self.fmt = _Formats(self.book)
        self.sheets: dict[str, Worksheet] = {
            name: self.book.add_worksheet(name) for name in self.SHEETS
        }
        #: Column widths as they are set, so a header knows its own room.
        self.column_width: dict[str, dict[int, float]] = {name: {} for name in self.SHEETS}
        #: Excel-model cells by key, for Checks and Summary.
        self.excel: dict[str, str] = {}
        #: Anchor constants by the same keys.
        self.anchor: dict[str, str] = {}
        #: Checks status cells by key, for Summary.
        self.status: dict[str, str] = {}
        #: Checks status cells by metric label.
        self.status_by_metric: dict[str, str] = {}
        self.checks: list[tuple[str, list[_Check]]] = []

    # ------------------------------------------------------------------ guards

    def _refuse(self, message: str) -> Exception:
        """The export's own typed ``ANALYSIS_INCONSISTENT`` refusal."""

        raise NotImplementedError

    def _anchor_ending_balances(self) -> tuple[float, ...]:
        """Anchor's loan balance at the end of each hold year.

        The saved analysis records only the balance at the sale. The annual
        balances come from Anchor's own debt engine functions, fed the saved
        inputs and the saved monthly payment -- the same recurrence that
        produced the saved exit balance -- and the last one must equal it."""

        terms = self.terms
        loan_amount = self.results.loan_amount
        monthly_rate = calculate_monthly_rate(interest_rate=terms.interest_rate)
        n_payments = calculate_scheduled_payment_count(amortization=terms.amortization)
        io_months = calculate_io_months(io_period=terms.io_period)
        io_payment = calculate_io_payment(loan_amount=loan_amount, monthly_rate=monthly_rate)
        months_to_run = min(self.hold * 12, io_months + n_payments)
        balances = calculate_amortization_schedule(
            loan_amount=loan_amount,
            monthly_rate=monthly_rate,
            monthly_debt_service=self.results.monthly_debt_service,
            n_payments=n_payments,
            months_to_run=months_to_run,
            io_months=io_months,
            io_payment=io_payment,
        )
        return tuple(
            balances[12 * year - 1] if 12 * year <= months_to_run else 0.0
            for year in self.years
        )

    def _consistency_problems(self) -> list[bool]:
        """The reconciliation every saved analysis must satisfy before it can
        be laid beside independent formulas. Subclasses add their own."""

        results = self.results
        # A mode with no rent roll has no variable below-NOI capital, and a
        # non-zero TI or LC in its saved analysis would mean the snapshot is not
        # what it claims. A mode that *does* have one (Excel Export 3) asserts
        # the schedule's length instead, and reconciles its values on Checks.
        no_operating_capital = not self.HAS_OPERATING_CAPITAL
        return [
            len(results.noi_by_year) != self.hold,
            len(results.levered_cash_flows) != self.hold + 1,
            len(results.unlevered_cash_flows) != self.hold + 1,
            any(value != 0.0 for value in results.tenant_improvements_by_year)
            if no_operating_capital
            else len(results.tenant_improvements_by_year) != self.hold,
            any(value != 0.0 for value in results.leasing_commissions_by_year)
            if no_operating_capital
            else len(results.leasing_commissions_by_year) != self.hold,
            len(results.project_capital_by_year) != self.hold,
            len(results.owner_expenses_by_year) != self.hold,
            self.ending_balance_by_year[-1] != results.remaining_loan_balance,
        ]

    def _require_consistent_analysis(self) -> None:
        if any(self._consistency_problems()):
            raise self._refuse(
                "The saved analysis could not be reconciled with the saved inputs "
                "and Business Plan. Analyze and save the Deal again, then export."
            )

    # ------------------------------------------------------------- primitives

    def _formula(
        self,
        sheet: str,
        row: int,
        col: int,
        formula: str,
        role: str,
        number_format: str,
        *,
        bold: bool = False,
        cached: str = "",
    ) -> str:
        """Write a formula with a pessimistic cached value and return its
        absolute cross-sheet reference."""

        _write_formula(
            self.sheets[sheet], row, col, formula, self.fmt.value(role, number_format, bold=bold), cached
        )
        return _xref(sheet, row, col)

    def _status_formula(self, sheet: str, row: int, col: int, formula: str, role: str = "calc") -> str:
        _write_formula(
            self.sheets[sheet], row, col, formula, self.fmt.status(role), NOT_RECALCULATED
        )
        return _xref(sheet, row, col)

    def _label(self, sheet: str, row: int, text: str, *, bold: bool = False, indent: int = 0) -> None:
        self.sheets[sheet].write_string(row, 0, text, self.fmt.label(bold=bold, indent=indent))

    def _units(self, sheet: str, row: int, text: str) -> None:
        self.sheets[sheet].write_string(row, 1, text, self.fmt.units())

    def _section(self, sheet: str, row: int, text: str, last_col: int) -> None:
        ws = self.sheets[sheet]
        ws.write_string(row, 0, text, self.fmt.section())
        for col in range(1, last_col + 1):
            ws.write_blank(row, col, None, self.fmt.section())

    def _subsection(self, sheet: str, row: int, text: str, last_col: int) -> None:
        ws = self.sheets[sheet]
        ws.write_string(row, 0, text, self.fmt.subsection())
        for col in range(1, last_col + 1):
            ws.write_blank(row, col, None, self.fmt.subsection())

    def _title(self, sheet: str, title: str, note: str) -> None:
        ws = self.sheets[sheet]
        ws.write_string(0, 0, title, self.fmt.title())
        ws.write_string(1, 0, note, self.fmt.note())
        ws.set_row(0, 22)

    def _set_column(self, sheet: str, first: int, last: int, width: float) -> None:
        """Set a column width and remember it: ``_headers`` wraps a header
        that is too long for the column it sits in, so every width must be
        known before that sheet's headers are written."""

        self.sheets[sheet].set_column(first, last, width)
        widths = self.column_width[sheet]
        for col in range(first, last + 1):
            widths[col] = width

    def _header_lines(self, sheet: str, col: int, text: str, indent: int = 0) -> int:
        width = self.column_width[sheet].get(col, DEFAULT_COLUMN_WIDTH)
        room = width - 1 - INDENT_CHARS * indent
        return _wrapped_lines(text, int(room * HEADER_CHARS_PER_WIDTH))

    def _headers(self, sheet: str, row: int, cells: Sequence[tuple[int, str, str]]) -> None:
        """Write one band of column headers, as ``(column, text, alignment)``,
        where the alignment given is that of the column's own data.

        Two headers must never read as one label. A rule alone is too quiet for
        that, so the separation is real space:

        * a header over a **value** column is *centred*, so its text stops well
          before the boundary it shares with the header on its right (and it
          costs no width, which matters in the narrow value columns);
        * a **descriptive** header that has a header to its left is *indented*,
          so its text never starts on that boundary;
        * the leading label column keeps its text on the margin, where no
          header meets it.

        The thin vertical rule stays, marking the boundary inside that space. A
        header longer than its column wraps instead of being clipped by the
        header beside it, and the row grows to hold the tallest one. An empty
        text writes the band across a column that has no header of its own."""

        ws = self.sheets[sheet]
        first_col = min(col for col, _, _ in cells)
        placed: list[tuple[int, str, str, int]] = [
            (col, text, "center", 0)
            if align == "right"
            else (col, text, "left", 0 if col == first_col else HEADER_INDENT)
            for col, text, align in cells
        ]
        lines = {col: self._header_lines(sheet, col, text, indent) for col, text, _, indent in placed}
        for col, text, align, indent in placed:
            cell_format = self.fmt.header(align=align, indent=indent, wrap=lines[col] > 1)
            if text:
                ws.write_string(row, col, text, cell_format)
            else:
                ws.write_blank(row, col, None, cell_format)
        tallest = max(lines.values(), default=1)
        if tallest > 1:
            ws.set_row(row, HEADER_LINE_HEIGHT * tallest)

    def _period_header(
        self,
        sheet: str,
        row: int,
        first_col: int,
        labels: Sequence[str],
        left: str = "Period",
        second: str = "",
    ) -> None:
        self._headers(
            sheet,
            row,
            [
                (0, left, "left"),
                (1, second, "right"),
                *((first_col + offset, text, "right") for offset, text in enumerate(labels)),
            ],
        )

    def _frozen(self, sheet: str, row: int, col: int, value: float | str | None, number_format: str) -> str:
        """Write one Anchor constant: a number, or ``Unavailable``."""

        ws = self.sheets[sheet]
        cell_format = self.fmt.value("frozen", number_format)
        if value is None:
            ws.write_string(row, col, UNAVAILABLE, cell_format)
        elif isinstance(value, str):
            ws.write_string(row, col, value, cell_format)
        else:
            ws.write_number(row, col, float(value), cell_format)
        return _xref(sheet, row, col)

    def _base_layout(self, sheet: str, period_columns: int) -> None:
        """The sheet's page and column layout. Called before the sheet is
        filled, so every header can be measured against its column."""

        ws = self.sheets[sheet]
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, LABEL_WIDTH)
        self._set_column(sheet, 1, 1, UNITS_WIDTH)
        if period_columns:
            self._set_column(sheet, 2, 1 + period_columns, PERIOD_WIDTH)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)

    # ------------------------------------------------------------------ build

    def build(self) -> bytes:
        self._build_inputs()
        self._build_operating()
        self._build_debt()
        self._build_equity()
        self._build_anchor_results()
        self._build_checks()
        self._build_summary()
        self._build_audit()
        self._finish_workbook()
        self.book.close()
        return self.output.getvalue()

    def _finish_workbook(self) -> None:
        generated = self.source.generated_at.astimezone(timezone.utc).replace(tzinfo=None)
        self.book.set_properties(
            {
                "title": f"{self.source.deal_name} - {self.WORKBOOK_TITLE}",
                "subject": f"{self.MODE_LABEL} formula audit",
                "author": "Anchor",
                "comments": self.CONTRACT_VERSION,
                "created": generated,
            }
        )
        self.book.set_calc_mode("auto")
        self.sheets[SUMMARY].activate()

    # ----------------------------------------------------------------- Inputs

    def _input_specs(self) -> list[tuple[str, list[_InputSpec]]]:
        """The Inputs sheet's rows, by section. Mode-specific."""

        raise NotImplementedError

    def _inputs_note(self) -> str:
        return (
            "Original Export is what Anchor analysed. Working Input starts equal to it and is "
            "the only column the model reads; edit it to explore a modified case."
        )

    def _build_inputs(self) -> None:
        sheet = INPUTS
        ws = self.sheets[sheet]
        self._inputs_layout()
        self._title(sheet, "Inputs", self._inputs_note())
        ws.write_string(
            2,
            0,
            "Blue: editable working input.  Black: calculation.  Green: value from another "
            "sheet.  Gray: frozen Anchor value.",
            self.fmt.note(),
        )
        ws.write_string(3, 0, "Model state", self.fmt.label(bold=True))
        _write_formula(ws, 3, 1, "=Model_State", self.fmt.status("link"), NOT_RECALCULATED)
        header_row = 5
        self._headers(
            sheet,
            header_row,
            [
                (0, "Assumption", "left"),
                (1, "Original Export", "right"),
                (2, "Working Input", "right"),
                (3, "Units", "left"),
                (4, "Status", "left"),
            ],
        )

        row = header_row + 1
        self.inputs_first_row = row
        #: The block's shape, replayed on Anchor Results as the frozen record.
        self.input_layout: list[_InputSpec | str] = []
        for section, specs in self._input_specs():
            self._subsection(sheet, row, section, 4)
            self.input_layout.append(section)
            row += 1
            for spec in specs:
                self._write_input(row, spec)
                self.input_layout.append(spec)
                row += 1
        self.inputs_last_row = row - 1

        # Business Plan by year: Original and Working side by side, per year.
        row += 1
        first_col = 2
        last_col = first_col + self.hold - 1
        self._period_header(
            sheet, row, first_col, [f"Year {year}" for year in self.years],
            left="Business Plan by year", second="Units",
        )
        row += 1
        self.bp_rows: dict[str, tuple[int, int]] = {}
        series = (
            ("project_capital", "Project capital", self.results.project_capital_by_year),
            ("owner_expenses", "Owner expenses", self.results.owner_expenses_by_year),
        )
        for key, label, values in series:
            original_row, working_row = row, row + 1
            self._label(sheet, original_row, f"{label} - Original Export")
            self._label(sheet, working_row, f"{label} - Working Input")
            self._units(sheet, original_row, "$")
            self._units(sheet, working_row, "$")
            for offset, value in enumerate(values):
                col = first_col + offset
                ws.write_number(original_row, col, value, self.fmt.value("frozen", NUM_CURRENCY))
                ws.write_number(working_row, col, value, self.fmt.value("input", NUM_CURRENCY))
            ws.data_validation(
                working_row, first_col, working_row, last_col,
                {"validate": "decimal", "criteria": ">=", "value": 0,
                 "error_title": "Business Plan amount",
                 "error_message": "Enter an amount of 0 or more, as Anchor requires."},
            )
            self.bp_rows[key] = (original_row, working_row)
            row += 2
        self._label(sheet, row, "Status")
        pc_o, pc_w = self.bp_rows["project_capital"]
        oe_o, oe_w = self.bp_rows["owner_expenses"]
        for offset in range(self.hold):
            col = first_col + offset
            _write_formula(ws,
                row, col,
                f'=IF(AND({_cell(pc_w, col)}={_cell(pc_o, col)},{_cell(oe_w, col)}={_cell(oe_o, col)}),"","Modified")',
                self.fmt.get(align="right"), "",
            )
        self.bp_first_col, self.bp_last_col = first_col, last_col
        row += 2

        self._build_business_plan_items(row)
        ws.freeze_panes(header_row + 1, 1)

    def _inputs_layout(self) -> None:
        """Inputs has its own column widths (two value columns, then Units and
        Status), set before anything is written so the headers can wrap."""

        sheet = INPUTS
        ws = self.sheets[sheet]
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, LABEL_WIDTH)
        self._set_column(sheet, 1, 2, UNITS_WIDTH)
        self._set_column(sheet, 3, 3, 30)
        self._set_column(sheet, 4, 4, 36)
        if self.hold > 3:
            self._set_column(sheet, 5, 1 + self.hold, PERIOD_WIDTH)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)

    def _write_input(self, row: int, spec: _InputSpec) -> None:
        sheet = INPUTS
        ws = self.sheets[sheet]
        self._label(sheet, row, spec.label, indent=1)
        ws.write_number(row, 1, spec.value, self.fmt.value("frozen", spec.number_format))
        original = _cell(row, 1)
        working = _cell(row, 2)
        if spec.fixed_note is None:
            ws.write_number(row, 2, spec.value, self.fmt.value("input", spec.number_format))
            _write_formula(ws, row, 4, f'=IF({working}={original},"","Modified")', self.fmt.status(), "")
            if spec.validation is not None:
                ws.data_validation(
                    row, 2, row, 2,
                    {**spec.validation,
                     "error_title": spec.label,
                     "error_message": "This value is outside the domain Anchor accepts for this input."},
                )
        else:
            _write_formula(ws, row, 2, f"={original}", self.fmt.value("calc", spec.number_format), "")
            ws.write_string(row, 4, spec.fixed_note, self.fmt.units())
        ws.write_string(row, 3, spec.units, self.fmt.units())
        if spec.name is not None:
            self.book.define_name(spec.name, f"={_xref(INPUTS, row, 2)}")
        self.excel[f"input:{spec.key}"] = _xref(INPUTS, row, 2)
        self.excel[f"original:{spec.key}"] = _xref(INPUTS, row, 1)

    def _build_business_plan_items(self, row: int) -> None:
        sheet = INPUTS
        ws = self.sheets[sheet]
        plan = self.source.business_plan
        self._subsection(sheet, row, "Business Plan items (as saved, for reference)", 4)
        row += 1
        self.bp_items: dict[str, Any] = {}
        if not plan.capital_items and not plan.owner_expense_items:
            ws.write_string(row, 0, "No Business Plan items are saved for this Deal.", self.fmt.note())
            return

        frozen_text = self.fmt.get(font_color=FROZEN_GRAY, bg_color=FROZEN_FILL)
        if plan.capital_items:
            self._headers(
                sheet,
                row,
                [
                    (0, "Capital item", "left"),
                    (1, "Model month", "right"),
                    (2, "Amount", "right"),
                    (3, "Category", "left"),
                    (4, "", "left"),
                ],
            )
            row += 1
            first = row
            for item in plan.capital_items:
                ws.write_string(row, 0, item.description, frozen_text)
                ws.write_number(row, 1, item.month, self.fmt.value("frozen", NUM_INTEGER))
                ws.write_number(row, 2, item.amount, self.fmt.value("frozen", NUM_CURRENCY))
                ws.write_string(row, 3, _humanize(item.category.value), frozen_text)
                row += 1
            self.bp_items["capital"] = (first, row - 1)
            ws.write_string(row, 0, "Month 0 is closing; months 1 to 12H fall in hold year ((month - 1) / 12) + 1; later months are post-hold.", self.fmt.note())
            row += 2
        if plan.owner_expense_items:
            self._headers(
                sheet,
                row,
                [
                    (0, "Owner-expense item", "left"),
                    (1, "First year", "right"),
                    (2, "Annual amount", "right"),
                    (3, "Last year (blank = through hold)", "left"),
                    (4, "Category", "left"),
                ],
            )
            row += 1
            first = row
            for item in plan.owner_expense_items:
                ws.write_string(row, 0, item.description, frozen_text)
                ws.write_number(row, 1, item.first_year, self.fmt.value("frozen", NUM_INTEGER))
                ws.write_number(row, 2, item.annual_amount, self.fmt.value("frozen", NUM_CURRENCY))
                if item.last_year is None:
                    ws.write_blank(row, 3, None, self.fmt.value("frozen", NUM_INTEGER))
                else:
                    ws.write_number(row, 3, item.last_year, self.fmt.value("frozen", NUM_INTEGER))
                ws.write_string(row, 4, _humanize(item.category.value), frozen_text)
                row += 1
            self.bp_items["expenses"] = (first, row - 1)
            row += 1

        # Excel's own resolution of the items, reconciled against Anchor's.
        self._period_header(
            sheet, row, self.bp_first_col, [f"Year {year}" for year in self.years],
            left="Items resolved by Excel", second="Year 0",
        )
        row += 1
        self._label(sheet, row, "Project capital from items")
        self._label(sheet, row + 1, "Owner expenses from items")
        if "capital" in self.bp_items:
            c1, c2 = self.bp_items["capital"]
            months = _range(None, c1, 1, c2, 1)
            amounts = _range(None, c1, 2, c2, 2)
            self.excel["items:closing"] = self._formula(sheet, row, 1, f'=SUMIFS({amounts},{months},0)', "calc", NUM_CURRENCY)
        else:
            self.excel["items:closing"] = self._formula(sheet, row, 1, "=0", "calc", NUM_CURRENCY)
        for offset, year in enumerate(self.years):
            col = self.bp_first_col + offset
            if "capital" in self.bp_items:
                c1, c2 = self.bp_items["capital"]
                months = _range(None, c1, 1, c2, 1)
                amounts = _range(None, c1, 2, c2, 2)
                formula = f'=SUMIFS({amounts},{months},">="&(12*({year}-1)+1),{months},"<="&(12*{year}))'
            else:
                formula = "=0"
            self.excel[f"items:project_capital:{year}"] = self._formula(sheet, row, col, formula, "calc", NUM_CURRENCY)
            if "expenses" in self.bp_items:
                e1, e2 = self.bp_items["expenses"]
                first_years = _range(None, e1, 1, e2, 1)
                annual = _range(None, e1, 2, e2, 2)
                last_years = _range(None, e1, 3, e2, 3)
                formula = (
                    f'=SUMPRODUCT({annual},--({first_years}<={year}),'
                    f'--((({last_years}="")+({last_years}>={year}))>0))'
                )
            else:
                formula = "=0"
            self.excel[f"items:owner_expenses:{year}"] = self._formula(sheet, row + 1, col, formula, "calc", NUM_CURRENCY)

    # ------------------------------------------------------ Operating Projection

    def _build_operating(self) -> None:
        """Fill the Operating Projection sheet.

        Must publish, for the sheets below it: ``self.noi_row``,
        ``self.operating_rows`` (``capex``/``project_capital``/
        ``owner_expenses``/``uocf``), and in ``self.excel`` the keys
        ``noi:<year>``, ``exit_noi``, ``going_in_cap_rate``, ``capex:<year>``,
        ``project_capital:<year>``, ``owner_expenses:<year>``,
        ``property_cf:<year>`` and ``uocf:<year>``. That is this workbook's
        ``OperatingProjectionLike``: the only thing the model below NOI knows
        about how NOI was produced."""

        raise NotImplementedError

    def _operating_capital_line(self) -> tuple[str, dict[int, str]] | None:
        """The below-NOI variable capital line, or ``None`` when the mode has
        none.

        Quick and Detailed have no rent roll, so they have no variable
        below-NOI capital and return ``None``: no row is written and their
        below-NOI block is unchanged. Excel Export 3 returns its label and one
        **positive** reference per hold year -- the shared code negates it
        exactly once, beside CapEx, matching
        ``anchor.engine.acquisition.calculate_operating_capital_by_year``."""

        return None

    def _build_below_noi(self, sheet: str, row: int, first_col: int, last_col: int, noi_row: int, capex_ref: str) -> int:
        """The below-NOI block: CapEx, Business Plan and unlevered owner cash
        flow, hold years only. Identical in both modes -- CapEx, debt service,
        acquisition costs, financing fees and disposition costs all sit below
        NOI, in the cash-flow assembly, and never in the operating build
        (``docs/detailed_operating_model_v2_1_financial_conventions.md``
        "NOI Convention")."""

        self._section(sheet, row, "Below-NOI cash flow (hold years; outflows negative)", last_col)
        row += 1
        # A mode whose rent roll produces variable below-NOI capital (Excel
        # Export 3's TI and LC) gets one extra line here. Quick and Detailed
        # have none, so `_operating_capital_line` returns None for them, no row
        # is written, and every row below keeps its original index and label.
        capital_line = self._operating_capital_line()
        r_noi, r_capex = row, row + 1
        r_opcap = r_capex + 1 if capital_line is not None else None
        r_pcf = (r_opcap if r_opcap is not None else r_capex) + 1
        r_pc, r_oe, r_uocf = r_pcf + 1, r_pcf + 2, r_pcf + 3
        self._label(sheet, r_noi, "Net operating income", indent=1)
        self._label(sheet, r_capex, "CapEx reserve", indent=1)
        if capital_line is not None and r_opcap is not None:
            self._label(sheet, r_opcap, capital_line[0], indent=1)
        self._label(
            sheet,
            r_pcf,
            "Property cash flow after CapEx" if capital_line is None else "Property cash flow after capital",
            bold=True,
        )
        self._label(sheet, r_pc, "Business Plan project capital", indent=1)
        self._label(sheet, r_oe, "Business Plan owner expenses", indent=1)
        self._label(sheet, r_uocf, "Unlevered owner cash flow", bold=True)
        for r in (r_noi, r_capex, r_opcap, r_pcf, r_pc, r_oe, r_uocf):
            if r is not None:
                self._units(sheet, r, "$")
        pc_working = self.bp_rows["project_capital"][1]
        oe_working = self.bp_rows["owner_expenses"][1]
        for offset, year in enumerate(self.years):
            col = first_col + offset
            input_col = self.bp_first_col + offset
            self._formula(sheet, r_noi, col, f"={_cell(noi_row, col)}", "calc", NUM_CURRENCY)
            self.excel[f"capex:{year}"] = self._formula(sheet, r_capex, col, f"=-{capex_ref}", "calc", NUM_CURRENCY)
            property_cf = f"={_cell(r_noi, col)}+{_cell(r_capex, col)}"
            if capital_line is not None and r_opcap is not None:
                self.excel[f"operating_capital:{year}"] = self._formula(
                    sheet, r_opcap, col, f"=-({capital_line[1][year]})", "link", NUM_CURRENCY
                )
                property_cf += f"+{_cell(r_opcap, col)}"
            self.excel[f"property_cf:{year}"] = self._formula(sheet, r_pcf, col, property_cf, "calc", NUM_CURRENCY, bold=True)
            self.excel[f"project_capital:{year}"] = self._formula(sheet, r_pc, col, f"=-{_xref(INPUTS, pc_working, input_col)}", "link", NUM_CURRENCY)
            self.excel[f"owner_expenses:{year}"] = self._formula(sheet, r_oe, col, f"=-{_xref(INPUTS, oe_working, input_col)}", "link", NUM_CURRENCY)
            self.excel[f"uocf:{year}"] = self._formula(
                sheet, r_uocf, col, f"={_cell(r_pcf, col)}+{_cell(r_pc, col)}+{_cell(r_oe, col)}", "calc", NUM_CURRENCY, bold=True
            )
        self.operating_rows = {"capex": r_capex, "project_capital": r_pc, "owner_expenses": r_oe, "uocf": r_uocf}
        if r_opcap is not None:
            self.operating_rows["operating_capital"] = r_opcap
        return r_uocf + 2

    # ----------------------------------------------------------- Debt Schedule

    def _build_debt(self) -> None:
        sheet = DEBT
        ws = self.sheets[sheet]
        hold = self.hold
        first_col = 2
        last_col = max(first_col + hold - 1, 7)
        self._base_layout(sheet, max(hold, 6))
        self._title(
            sheet,
            "Debt Schedule",
            "Monthly fixed-rate schedule: interest = beginning balance x monthly rate; principal = "
            "payment - interest; the balance is set to zero at contractual maturity.",
        )
        row = 3
        self._section(sheet, row, "Loan terms", last_col)
        row += 1
        terms: dict[str, int] = {}

        def line(key: str, label: str, units: str, formula: str, role: str, number_format: str, *, bold: bool = False, name: str | None = None) -> None:
            nonlocal row
            self._label(sheet, row, label, indent=0 if bold else 1, bold=bold)
            self._units(sheet, row, units)
            self._formula(sheet, row, 2, formula, role, number_format, bold=bold)
            terms[key] = row
            if name is not None:
                self.book.define_name(name, f"={_xref(DEBT, row, 2)}")
            row += 1

        line("price", "Purchase price", "$", "=Purchase_Price", "link", NUM_CURRENCY)
        line("ltv", "Loan-to-value", "%", "=Loan_To_Value", "link", NUM_PERCENT)
        line("rate", "Interest rate", "% per year", "=Interest_Rate", "link", NUM_PERCENT)
        line("amort", "Amortization", "years", "=Amortization_Years", "link", NUM_INTEGER)
        line("io", "Interest-only period", "years", "=IO_Period_Years", "link", NUM_INTEGER)
        line("fee_pct", "Financing fee", "% of loan", "=Financing_Fee_Pct", "link", NUM_PERCENT)
        line("hold", "Hold period", "years", "=Hold_Period", "link", NUM_INTEGER)
        T = {key: _abs(r, 2) for key, r in terms.items()}
        line("loan", "Loan amount", "$", f"={T['price']}*{T['ltv']}", "calc", NUM_CURRENCY, bold=True, name="Loan_Amount")
        T["loan"] = _abs(terms["loan"], 2)
        line("fee", "Financing fee", "$", f"={T['loan']}*{T['fee_pct']}", "calc", NUM_CURRENCY)
        T["fee"] = _abs(terms["fee"], 2)
        line("r", "Monthly rate  (annual rate / 12)", "% per month", f"={T['rate']}/12", "calc", NUM_PERCENT_FINE, name="Monthly_Rate")
        T["r"] = _abs(terms["r"], 2)
        line("n", "Amortizing payments  (amortization x 12)", "months", f"={T['amort']}*12", "calc", NUM_INTEGER)
        T["n"] = _abs(terms["n"], 2)
        line("io_months", "Interest-only months  (IO period x 12)", "months", f"={T['io']}*12", "calc", NUM_INTEGER)
        T["io_months"] = _abs(terms["io_months"], 2)
        line("io_payment", "Interest-only monthly payment  (loan x monthly rate)", "$ per month", f"={T['loan']}*{T['r']}", "calc", NUM_CURRENCY_CENTS)
        T["io_payment"] = _abs(terms["io_payment"], 2)
        line(
            "pmt",
            "Amortizing payment  L x r / (1 - (1 + r)^-N)",
            "$ per month",
            f"=IF({T['loan']}=0,0,IF({T['r']}=0,{T['loan']}/{T['n']},{T['loan']}*({T['r']}/(1-(1+{T['r']})^(-{T['n']})))))",
            "calc",
            NUM_CURRENCY_CENTS,
        )
        T["pmt"] = _abs(terms["pmt"], 2)
        line("maturity", "Contractual maturity  (IO months + N)", "month", f"={T['io_months']}+{T['n']}", "calc", NUM_INTEGER)
        T["maturity"] = _abs(terms["maturity"], 2)
        line("sale_month", "Sale month  (hold period x 12)", "month", f"={T['hold']}*12", "calc", NUM_INTEGER)
        self.excel["loan_amount"] = _xref(DEBT, terms["loan"], 2)
        self.excel["financing_fee"] = _xref(DEBT, terms["fee"], 2)
        self.excel["monthly_debt_service"] = _xref(DEBT, terms["pmt"], 2)
        ws.write_string(row, 0, "With a zero interest rate the payment is loan / N, matching Anchor; Excel's PMT would give the same figures.", self.fmt.note())
        row += 2

        # Monthly schedule placement is fixed first so the annual block can
        # reference it.
        annual_top = row
        annual_rows = 12
        monthly_section = annual_top + annual_rows + 2
        monthly_header = monthly_section + 1
        first_month_row = monthly_header + 1
        months = 12 * hold

        def month_row(month: int) -> int:
            return first_month_row + month - 1

        # Annual summary.
        self._section(sheet, row, "Annual summary", last_col)
        row += 1
        self._period_header(sheet, row, first_col, [f"Year {year}" for year in self.years])
        row += 1
        r_beg, r_ds, r_int, r_prin, r_end, r_noi, r_dscr = range(row, row + 7)
        for r, label, units, bold in (
            (r_beg, "Beginning loan balance", "$", False),
            (r_ds, "Scheduled debt service", "$", True),
            (r_int, "Interest", "$", False),
            (r_prin, "Principal amortization", "$", False),
            (r_end, "Ending loan balance", "$", True),
            (r_noi, "Net operating income", "$", False),
            (r_dscr, "Debt service coverage (NOI / debt service)", "x", True),
        ):
            self._label(sheet, r, label, bold=bold, indent=0 if bold else 1)
            self._units(sheet, r, units)
        for offset, year in enumerate(self.years):
            col = first_col + offset
            first, last = month_row(12 * year - 11), month_row(12 * year)
            if offset == 0:
                self._formula(sheet, r_beg, col, f"={T['loan']}", "calc", NUM_CURRENCY)
            else:
                self._formula(sheet, r_beg, col, f"={_cell(r_end, col - 1)}", "calc", NUM_CURRENCY)
            self.excel[f"debt_service:{year}"] = self._formula(sheet, r_ds, col, f"=SUM({_cell(first, 4)}:{_cell(last, 4)})", "calc", NUM_CURRENCY, bold=True)
            self._formula(sheet, r_int, col, f"=SUM({_cell(first, 5)}:{_cell(last, 5)})", "calc", NUM_CURRENCY)
            self._formula(sheet, r_prin, col, f"=SUM({_cell(first, 6)}:{_cell(last, 6)})", "calc", NUM_CURRENCY)
            self.excel[f"ending_balance:{year}"] = self._formula(sheet, r_end, col, f"={_cell(last, 7)}", "calc", NUM_CURRENCY, bold=True)
            self._formula(sheet, r_noi, col, f"={_xref(self.OPERATING_SHEET, self.noi_row, 2 + offset)}", "link", NUM_CURRENCY)
            self.excel[f"dscr:{year}"] = self._formula(
                sheet, r_dscr, col,
                f'=IF({_cell(r_ds, col)}>0,{_cell(r_noi, col)}/{_cell(r_ds, col)},"{UNAVAILABLE}")',
                "calc", NUM_MULTIPLE, bold=True,
            )
        last_year_col = first_col + hold - 1
        dscr_range = f"{_abs(r_dscr, first_col)}:{_abs(r_dscr, last_year_col)}"
        row = r_dscr + 1
        self._label(sheet, row, "Headline DSCR (Year 1)", indent=1)
        self._units(sheet, row, "x")
        self.excel["headline_dscr"] = self._formula(sheet, row, 2, f"={_abs(r_dscr, first_col)}", "calc", NUM_MULTIPLE)
        row += 1
        self._label(sheet, row, "Minimum DSCR (years with debt service)", indent=1)
        self._units(sheet, row, "x")
        self.excel["min_dscr"] = self._formula(sheet, row, 2, f'=IF(COUNT({dscr_range})=0,"{UNAVAILABLE}",MIN({dscr_range}))', "calc", NUM_MULTIPLE)
        row += 1
        self._label(sheet, row, "Year 1 debt yield  (Year 1 NOI / loan amount)", indent=1)
        self._units(sheet, row, "%")
        self.excel["year_1_debt_yield"] = self._formula(sheet, row, 2, f'=IF({T["loan"]}=0,"{UNAVAILABLE}",{_abs(r_noi, first_col)}/{T["loan"]})', "calc", NUM_PERCENT)
        row += 1
        self._label(sheet, row, f"Loan payoff at sale (end of Year {hold})", bold=True)
        self._units(sheet, row, "$")
        payoff = self._formula(sheet, row, 2, f"={_abs(r_end, last_year_col)}", "calc", NUM_CURRENCY, bold=True)
        self.excel["remaining_loan_balance"] = payoff
        self.debt_payoff_ref = payoff
        self.debt_ds_row = r_ds
        assert row < monthly_section

        # Monthly schedule.
        self._section(sheet, monthly_section, "Monthly schedule", last_col)
        headers = ("Month", "Hold year", "Phase", "Beginning balance", "Payment", "Interest", "Principal", "Ending balance")
        self._headers(
            sheet,
            monthly_header,
            [(col, text, "left" if col in (0, 2) else "right") for col, text in enumerate(headers)],
        )
        phase_format = self.fmt.get(font_color=NOTE_GRAY)
        month_format = self.fmt.get(align="left", num_format="0")
        year_format = self.fmt.value("calc", NUM_INTEGER)
        for month in range(1, months + 1):
            r = month_row(month)
            m = _cell(r, 0)
            ws.write_number(r, 0, month, month_format)
            ws.write_number(r, 1, (month - 1) // 12 + 1, year_format)
            _write_formula(ws,
                r, 2,
                f'=IF({m}<={T["io_months"]},"Interest-only",IF({m}<={T["maturity"]},"Amortizing","Repaid"))',
                phase_format, "",
            )
            beginning = f"={T['loan']}" if month == 1 else f"={_cell(r - 1, 7)}"
            self._formula(sheet, r, 3, beginning, "calc", NUM_CURRENCY_CENTS)
            self._formula(
                sheet, r, 4,
                f"=IF({m}<={T['io_months']},{T['io_payment']},IF({m}-{T['io_months']}<={T['n']},{T['pmt']},0))",
                "calc", NUM_CURRENCY_CENTS,
            )
            self._formula(sheet, r, 5, f"={_cell(r, 3)}*{T['r']}", "calc", NUM_CURRENCY_CENTS)
            self._formula(sheet, r, 6, f"={_cell(r, 4)}-{_cell(r, 5)}", "calc", NUM_CURRENCY_CENTS)
            self._formula(sheet, r, 7, f"=IF({m}={T['maturity']},0,{_cell(r, 3)}-{_cell(r, 6)})", "calc", NUM_CURRENCY_CENTS)
        ws.freeze_panes(0, 2)

    # -------------------------------------------------------- Equity Cash Flow

    def _build_equity(self) -> None:
        sheet = EQUITY
        ws = self.sheets[sheet]
        hold = self.hold
        c0 = 2  # Year 0
        cH = c0 + hold
        last_col = cH
        self._base_layout(sheet, hold + 1)
        self._title(
            sheet,
            "Equity Cash Flow",
            f"Annual periods: Year 0 is acquisition; the sale occurs at the end of Year {hold} and "
            "is included in that year. Inflows are positive, outflows negative.",
        )
        row = 3
        self._section(sheet, row, "Assumptions used", last_col)
        row += 1
        a: dict[str, str] = {}
        links = (
            ("price", "Purchase price", "$", "=Purchase_Price", NUM_CURRENCY),
            ("acq_pct", "Acquisition costs", "% of purchase price", "=Acquisition_Cost_Pct", NUM_PERCENT),
            ("disp_pct", "Disposition costs", "% of gross sale price", "=Disposition_Cost_Pct", NUM_PERCENT),
            ("exit_cap", "Exit cap rate", "%", "=Exit_Cap_Rate", NUM_PERCENT),
            ("closing_pc", "Closing project capital", "$", "=Closing_Project_Capital", NUM_CURRENCY),
            ("loan", "Loan amount", "$", f"={self.excel['loan_amount']}", NUM_CURRENCY),
            ("fee", "Financing fee", "$", f"={self.excel['financing_fee']}", NUM_CURRENCY),
            ("exit_noi", f"Year {hold + 1} NOI (exit NOI)", "$", f"={self.excel['exit_noi']}", NUM_CURRENCY),
            ("hold", "Hold period", "years", "=Hold_Period", NUM_INTEGER),
        )
        for key, label, units, formula, number_format in links:
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            self._formula(sheet, row, 2, formula, "link", number_format)
            a[key] = _abs(row, 2)
            row += 1
        row += 1

        self._period_header(sheet, row, c0, [f"Year {year}" for year in range(0, hold + 1)])
        row += 1

        # Acquisition, Year 0.
        self._section(sheet, row, "Acquisition (Year 0)", last_col)
        row += 1
        r_price, r_acq, r_fee, r_cpc, r_loan, r_equity, r_uses, r_sources = range(row, row + 8)
        acquisition = (
            (r_price, "Purchase price", f"=-{a['price']}", "calc", False),
            (r_acq, "Acquisition costs", f"=-{a['price']}*{a['acq_pct']}", "calc", False),
            (r_fee, "Financing fee", f"=-{a['fee']}", "calc", False),
            (r_cpc, "Closing project capital", f"=-{a['closing_pc']}", "calc", False),
            (r_loan, "Loan proceeds", f"={a['loan']}", "calc", False),
            (r_equity, "Acquisition equity", f"=SUM({_cell(r_price, c0)}:{_cell(r_loan, c0)})", "calc", True),
            (r_uses, "Total closing uses", f"=-SUM({_cell(r_price, c0)}:{_cell(r_cpc, c0)})", "calc", False),
            (r_sources, "Total closing sources  (loan + equity)", f"={_cell(r_loan, c0)}-{_cell(r_equity, c0)}", "calc", False),
        )
        for r, label, formula, role, bold in acquisition:
            self._label(sheet, r, label, bold=bold, indent=0 if bold else 1)
            self._units(sheet, r, "$")
            self._formula(sheet, r, c0, formula, role, NUM_CURRENCY, bold=bold)
        self.excel["acquisition_costs_neg"] = _xref(sheet, r_acq, c0)
        self.excel["acquisition_equity"] = _xref(sheet, r_equity, c0)
        self.excel["total_closing_uses"] = _xref(sheet, r_uses, c0)
        self.excel["total_closing_sources"] = _xref(sheet, r_sources, c0)
        self.excel["closing_pc_neg"] = _xref(sheet, r_cpc, c0)
        row = r_sources + 2

        # Operations, Years 1..H.
        self._section(sheet, row, f"Operations (Years 1 to {hold})", last_col)
        row += 1
        # The same optional line the below-NOI block carries. It is inserted
        # inside the summed range rather than added afterwards, so the levered
        # cash flow stays one contiguous SUM in both shapes.
        capital_line = self._operating_capital_line()
        if capital_line is None:
            r_opcap = None
            r_noi, r_capex, r_pc, r_oe, r_ds, r_locf = range(row, row + 6)
            operations = (
                (r_noi, "Net operating income", False),
                (r_capex, "CapEx reserve", False),
                (r_pc, "Business Plan project capital", False),
                (r_oe, "Business Plan owner expenses", False),
                (r_ds, "Debt service", False),
                (r_locf, "Levered owner cash flow", True),
            )
        else:
            r_noi, r_capex, r_opcap, r_pc, r_oe, r_ds, r_locf = range(row, row + 7)
            operations = (
                (r_noi, "Net operating income", False),
                (r_capex, "CapEx reserve", False),
                (r_opcap, capital_line[0], False),
                (r_pc, "Business Plan project capital", False),
                (r_oe, "Business Plan owner expenses", False),
                (r_ds, "Debt service", False),
                (r_locf, "Levered owner cash flow", True),
            )
        for r, label, bold in operations:
            self._label(sheet, r, label, bold=bold, indent=0 if bold else 1)
            self._units(sheet, r, "$")
        op = self.operating_rows
        for offset, year in enumerate(self.years):
            col = c0 + 1 + offset
            op_col = 2 + offset
            self._formula(sheet, r_noi, col, f"={_xref(self.OPERATING_SHEET, self.noi_row, op_col)}", "link", NUM_CURRENCY)
            self._formula(sheet, r_capex, col, f"={_xref(self.OPERATING_SHEET, op['capex'], op_col)}", "link", NUM_CURRENCY)
            if r_opcap is not None:
                self._formula(sheet, r_opcap, col, f"={_xref(self.OPERATING_SHEET, op['operating_capital'], op_col)}", "link", NUM_CURRENCY)
            self._formula(sheet, r_pc, col, f"={_xref(self.OPERATING_SHEET, op['project_capital'], op_col)}", "link", NUM_CURRENCY)
            self._formula(sheet, r_oe, col, f"={_xref(self.OPERATING_SHEET, op['owner_expenses'], op_col)}", "link", NUM_CURRENCY)
            self._formula(sheet, r_ds, col, f"=-{_xref(DEBT, self.debt_ds_row, op_col)}", "link", NUM_CURRENCY)
            self.excel[f"locf:{year}"] = self._formula(
                sheet, r_locf, col, f"=SUM({_cell(r_noi, col)}:{_cell(r_ds, col)})", "calc", NUM_CURRENCY, bold=True
            )
        row = r_locf + 2

        # Sale, end of Year H.
        self._section(sheet, row, f"Sale (end of Year {hold})", last_col)
        row += 1
        r_gross, r_sell, r_payoff, r_nsp = range(row, row + 4)
        sale = (
            (r_gross, "Gross sale price  (exit NOI / exit cap rate)", f"={a['exit_noi']}/{a['exit_cap']}", "calc", False),
            (r_sell, "Selling costs", f"=-{_cell(r_gross, cH)}*{a['disp_pct']}", "calc", False),
            (r_payoff, "Debt payoff", f"=-{self.debt_payoff_ref}", "link", False),
            (r_nsp, "Net sale proceeds", f"=SUM({_cell(r_gross, cH)}:{_cell(r_payoff, cH)})", "calc", True),
        )
        for r, label, formula, role, bold in sale:
            self._label(sheet, r, label, bold=bold, indent=0 if bold else 1)
            self._units(sheet, r, "$")
            self._formula(sheet, r, cH, formula, role, NUM_CURRENCY, bold=bold)
        self.excel["exit_value"] = _xref(sheet, r_gross, cH)
        self.excel["disposition_costs_neg"] = _xref(sheet, r_sell, cH)
        self.excel["net_sale_proceeds"] = _xref(sheet, r_nsp, cH)
        row = r_nsp + 2

        # Equity cash flow.
        self._section(sheet, row, "Equity cash flow", last_col)
        row += 1
        r_ecf, r_cum = row, row + 1
        self._label(sheet, r_ecf, "Total equity cash flow", bold=True)
        self._label(sheet, r_cum, "Cumulative equity cash flow", indent=1)
        self._units(sheet, r_ecf, "$")
        self._units(sheet, r_cum, "$")
        for t in range(0, hold + 1):
            col = c0 + t
            if t == 0:
                formula = f"={_cell(r_equity, col)}"
            elif t < hold:
                formula = f"={_cell(r_locf, col)}"
            else:
                formula = f"={_cell(r_locf, col)}+{_cell(r_nsp, col)}"
            self.excel[f"ecf:{t}"] = self._formula(sheet, r_ecf, col, formula, "calc", NUM_CURRENCY, bold=True)
            cumulative = f"={_cell(r_ecf, col)}" if t == 0 else f"={_cell(r_cum, col - 1)}+{_cell(r_ecf, col)}"
            self._formula(sheet, r_cum, col, cumulative, "calc", NUM_CURRENCY)
        ecf_range = f"{_abs(r_ecf, c0)}:{_abs(r_ecf, cH)}"
        self.excel["ecf_range_count"] = f"COUNT({_range(EQUITY, r_ecf, c0, r_ecf, cH)})"
        row = r_cum + 2

        # Returns.
        self._section(sheet, row, "Returns", last_col)
        row += 1
        r_inv, r_ret, r_profit, r_em = range(row, row + 4)
        returns = (
            (r_inv, "Total equity invested  (sum of negative periods)", "$", f'=-SUMIF({ecf_range},"<0")', NUM_CURRENCY),
            (r_ret, "Total cash returned  (sum of positive periods)", "$", f'=SUMIF({ecf_range},">0")', NUM_CURRENCY),
            (r_profit, "Total profit", "$", f"={_cell(r_ret, 2)}-{_cell(r_inv, 2)}", NUM_CURRENCY),
            (r_em, "Equity multiple  (returned / invested)", "x", f'=IF({_cell(r_inv, 2)}=0,"{UNAVAILABLE}",{_cell(r_ret, 2)}/{_cell(r_inv, 2)})', NUM_MULTIPLE),
        )
        for r, label, units, formula, number_format in returns:
            self._label(sheet, r, label, bold=r in (r_profit, r_em))
            self._units(sheet, r, units)
            self._formula(sheet, r, 2, formula, "calc", number_format, bold=r in (r_profit, r_em))
        self.excel["total_equity_invested"] = _xref(sheet, r_inv, 2)
        self.excel["total_cash_returned"] = _xref(sheet, r_ret, 2)
        self.excel["total_profit"] = _xref(sheet, r_profit, 2)
        self.excel["equity_multiple"] = _xref(sheet, r_em, 2)
        row = r_em + 1
        row = self._irr_block(sheet, row, r_ecf, c0, cH, "levered", "Levered IRR", hold=a["hold"])
        row += 1

        # Owner return metrics by year.
        self._section(sheet, row, "Owner return metrics by year", last_col)
        row += 1
        r_coc, r_cum_dist = row, row + 1
        self._label(sheet, r_coc, "Levered cash-on-cash  (owner cash flow / equity)", indent=1)
        self._label(sheet, r_cum_dist, "Cumulative operating distributions", indent=1)
        self._units(sheet, r_coc, "%")
        self._units(sheet, r_cum_dist, "$")
        equity0 = _abs(r_equity, c0)
        for offset, year in enumerate(self.years):
            col = c0 + 1 + offset
            self.excel[f"coc:{year}"] = self._formula(
                sheet, r_coc, col, f'=IF({equity0}=0,"{UNAVAILABLE}",{_cell(r_locf, col)}/-{equity0})', "calc", NUM_PERCENT
            )
            cumulative = f"={_cell(r_locf, col)}" if offset == 0 else f"={_cell(r_cum_dist, col - 1)}+{_cell(r_locf, col)}"
            self.excel[f"cum_dist:{year}"] = self._formula(sheet, r_cum_dist, col, cumulative, "calc", NUM_CURRENCY)
        row = r_cum_dist + 2

        # Unlevered project cash flow.
        self._section(sheet, row, "Unlevered project cash flow (no debt)", last_col)
        row += 1
        r_uocf, r_ucf, r_yield = row, row + 1, row + 2
        self._label(sheet, r_uocf, "Unlevered owner cash flow", indent=1)
        self._label(sheet, r_ucf, "Unlevered project cash flow", bold=True)
        self._label(sheet, r_yield, "Unlevered cash yield  (owner cash flow / cost basis)", indent=1)
        self._units(sheet, r_uocf, "$")
        self._units(sheet, r_ucf, "$")
        self._units(sheet, r_yield, "%")
        self.excel["ucf:0"] = self._formula(
            sheet, r_ucf, c0, f"={_cell(r_price, c0)}+{_cell(r_acq, c0)}+{_cell(r_cpc, c0)}", "calc", NUM_CURRENCY, bold=True
        )
        basis = _abs(r_ucf, c0)
        for offset, year in enumerate(self.years):
            col = c0 + 1 + offset
            self._formula(sheet, r_uocf, col, f"={_xref(self.OPERATING_SHEET, op['uocf'], 2 + offset)}", "link", NUM_CURRENCY)
            if year < hold:
                formula = f"={_cell(r_uocf, col)}"
            else:
                formula = f"={_cell(r_uocf, col)}+{_cell(r_gross, col)}+{_cell(r_sell, col)}"
            self.excel[f"ucf:{year}"] = self._formula(sheet, r_ucf, col, formula, "calc", NUM_CURRENCY, bold=True)
            self.excel[f"unlevered_yield:{year}"] = self._formula(
                sheet, r_yield, col, f'=IF({basis}=0,"{UNAVAILABLE}",{_cell(r_uocf, col)}/-{basis})', "calc", NUM_PERCENT
            )
        row = r_yield + 1
        row = self._irr_block(sheet, row, r_ucf, c0, cH, "unlevered", "Unlevered IRR", hold=a["hold"])
        ws.freeze_panes(0, 2)

    def _irr_block(
        self,
        sheet: str,
        row: int,
        cf_row: int,
        c0: int,
        cH: int,
        key: str,
        title: str,
        *,
        hold: str,
    ) -> int:
        """The IRR, guarded by Anchor's sign rules, with every helper visible.

        Rules (``docs/financial_conventions.md`` "IRR validity"): zero periods
        are ignored for signs only; the nonzero sequence must start negative,
        contain a positive, and change sign exactly once. Otherwise the IRR is
        ``Unavailable`` and Excel's ``IRR`` is never evaluated."""

        ws = self.sheets[sheet]
        self._subsection(sheet, row, f"{title}: sign-rule audit", cH)
        row += 1
        r_sign, r_last, r_change, r_first = range(row, row + 4)
        for r, label in (
            (r_sign, "Sign of cash flow"),
            (r_last, "Sign of latest nonzero cash flow"),
            (r_change, "Sign change here"),
            (r_first, "First nonzero cash flow here"),
        ):
            self._label(sheet, r, label, indent=1)
            self._units(sheet, r, "flag")
        for col in range(c0, cH + 1):
            sign = _cell(r_sign, col)
            self._formula(sheet, r_sign, col, f"=SIGN({_cell(cf_row, col)})", "calc", NUM_FLAG)
            if col == c0:
                self._formula(sheet, r_last, col, f"={sign}", "calc", NUM_FLAG)
                self._formula(sheet, r_change, col, "=0", "calc", NUM_FLAG)
                self._formula(sheet, r_first, col, f"=IF({sign}<>0,1,0)", "calc", NUM_FLAG)
            else:
                prior = _cell(r_last, col - 1)
                self._formula(sheet, r_last, col, f"=IF({sign}<>0,{sign},{prior})", "calc", NUM_FLAG)
                self._formula(sheet, r_change, col, f"=IF(AND({sign}<>0,{prior}<>0,{sign}<>{prior}),1,0)", "calc", NUM_FLAG)
                self._formula(sheet, r_first, col, f"=IF(AND({sign}<>0,{prior}=0),1,0)", "calc", NUM_FLAG)
        signs = f"{_abs(r_sign, c0)}:{_abs(r_sign, cH)}"
        row = r_first + 1
        r_nonzero, r_first_sign, r_positive, r_changes, r_status, r_multiple, r_guess, r_irr = range(row, row + 8)
        scalars = (
            (r_nonzero, "Nonzero periods", "count", f'=COUNTIF({signs},"<>0")', NUM_INTEGER),
            (r_first_sign, "Sign of first nonzero cash flow", "flag", f"=SUMPRODUCT({_abs(r_first, c0)}:{_abs(r_first, cH)},{signs})", NUM_FLAG),
            (r_positive, "Positive periods", "count", f'=COUNTIF({signs},">0")', NUM_INTEGER),
            (r_changes, "Sign changes", "count", f"=SUM({_abs(r_change, c0)}:{_abs(r_change, cH)})", NUM_INTEGER),
        )
        for r, label, units, formula, number_format in scalars:
            self._label(sheet, r, label, indent=1)
            self._units(sheet, r, units)
            self._formula(sheet, r, 2, formula, "calc", number_format)
        self._label(sheet, r_status, f"{title} availability", indent=1)
        self._units(sheet, r_status, "status")
        n, first, positive, changes = (_abs(r, 2) for r in (r_nonzero, r_first_sign, r_positive, r_changes))
        status = self._status_formula(
            sheet, r_status, 2,
            f'=IF({n}=0,"{IRR_STATUS_TEXT[IrrStatus.NO_NONZERO_CASH_FLOW]}",'
            f'IF({first}>=0,"{IRR_STATUS_TEXT[IrrStatus.FIRST_NONZERO_NOT_NEGATIVE]}",'
            f'IF({positive}=0,"{IRR_STATUS_TEXT[IrrStatus.NO_POSITIVE_CASH_FLOW]}",'
            f'IF({changes}<>1,"{IRR_STATUS_TEXT[IrrStatus.MULTIPLE_SIGN_CHANGES]}",'
            f'"{IRR_STATUS_TEXT[IrrStatus.DEFINED]}"))))',
        )
        cf_range = f"{_abs(cf_row, c0)}:{_abs(cf_row, cH)}"
        self._label(sheet, r_multiple, "Cash multiple of this series  (inflows / outflows)", indent=1)
        self._units(sheet, r_multiple, "x")
        self._formula(
            sheet, r_multiple, 2,
            f'=IF(SUMIF({cf_range},"<0")=0,"{UNAVAILABLE}",SUMIF({cf_range},">0")/-SUMIF({cf_range},"<0"))',
            "calc", NUM_MULTIPLE,
        )
        # Excel's IRR iterates from a starting estimate. Seeding it with the rate
        # that would turn this series' own multiple into its value over the hold
        # keeps it on the right branch near -100% and at very high returns.
        self._label(sheet, r_guess, "Starting estimate for Excel IRR  (multiple ^ (1 / H) - 1)", indent=1)
        self._units(sheet, r_guess, "%")
        multiple = _abs(r_multiple, 2)
        self._formula(
            sheet, r_guess, 2,
            f"=IF(AND(ISNUMBER({multiple}),N({multiple})>0),{multiple}^(1/{hold})-1,0.1)",
            "calc", NUM_PERCENT,
        )
        self._label(sheet, r_irr, title, bold=True)
        self._units(sheet, r_irr, "% per year")
        irr = f"IRR({cf_range},{_abs(r_guess, 2)})"
        status_ref = _abs(r_status, 2)
        ref = self._formula(
            sheet, r_irr, 2,
            f'=IF({status_ref}<>"{IRR_STATUS_TEXT[IrrStatus.DEFINED]}","{UNAVAILABLE}",'
            f'IF(ISERROR({irr}),IF(ERROR.TYPE({irr})=6,"Did not converge",{irr}),{irr}))',
            "calc", NUM_PERCENT, bold=True,
        )
        ws.write_string(
            r_irr + 1, 0,
            "Excel's IRR solves the same annual equation by iteration; a series that passes the "
            "sign rules but does not converge shows 'Did not converge', never a number.",
            self.fmt.note(),
        )
        self.excel[f"{key}_irr"] = ref
        self.excel[f"{key}_irr_status"] = status
        return r_irr + 2

    # ----------------------------------------------------------- Anchor Results

    def _anchor_operating_rows(self, row: int, c0: int) -> int:
        """Mode-specific frozen operating lines, written above the shared
        annual results. Quick has none; Detailed has its whole schedule."""

        return row

    def _build_anchor_results(self) -> None:
        sheet = ANCHOR
        ws = self.sheets[sheet]
        results = self.results
        hold = self.hold
        c0 = 2
        last_col = c0 + hold
        self._base_layout(sheet, hold + 1)
        self._title(
            sheet,
            "Anchor Results (frozen at export)",
            self.ANCHOR_RESULTS_NOTE,
        )
        row = 3
        self._section(sheet, row, "Headline and summary results", last_col)
        row += 1
        self._headers(sheet, row, [(0, "Result", "left"), (1, "Units", "left"), (2, "Anchor", "right")])
        row += 1
        scalars: tuple[tuple[str, str, str, float | str | None, str], ...] = (
            ("hold_period", "Hold period", "years", float(len(results.noi_by_year)), NUM_INTEGER),
            ("ecf_periods", "Equity cash-flow periods", "count", float(len(results.levered_cash_flows)), NUM_INTEGER),
            ("going_in_cap_rate", "Going-in cap rate", "%", results.going_in_cap_rate, NUM_PERCENT),
            ("loan_amount", "Loan amount", "$", results.loan_amount, NUM_CURRENCY),
            ("acquisition_costs", "Acquisition costs", "$", results.acquisition_costs, NUM_CURRENCY),
            ("financing_fee", "Financing fee", "$", results.financing_fee, NUM_CURRENCY),
            ("closing_project_capital", "Closing project capital", "$", results.closing_project_capital, NUM_CURRENCY),
            ("initial_equity", "Initial equity requirement", "$", results.initial_equity, NUM_CURRENCY),
            ("total_closing_uses", "Total closing uses", "$", results.total_closing_uses, NUM_CURRENCY),
            ("total_closing_sources", "Total closing sources", "$", results.total_closing_sources, NUM_CURRENCY),
            ("monthly_debt_service", "Amortizing monthly payment (post-IO)", "$ per month", results.monthly_debt_service, NUM_CURRENCY_CENTS),
            ("remaining_loan_balance", "Loan balance at sale (debt payoff)", "$", results.remaining_loan_balance, NUM_CURRENCY),
            ("exit_noi", "Exit NOI (Year H+1)", "$", results.exit_noi, NUM_CURRENCY),
            ("exit_value", "Exit value (gross sale price)", "$", results.exit_value, NUM_CURRENCY),
            ("disposition_costs", "Disposition costs", "$", results.disposition_costs, NUM_CURRENCY),
            ("net_sale_proceeds", "Net sale proceeds", "$", results.net_sale_proceeds, NUM_CURRENCY),
            ("headline_dscr", "Headline DSCR (Year 1)", "x", results.headline_dscr, NUM_MULTIPLE),
            ("min_dscr", "Minimum DSCR", "x", results.min_dscr, NUM_MULTIPLE),
            ("year_1_debt_yield", "Year 1 debt yield", "%", results.year_1_debt_yield, NUM_PERCENT),
            ("total_equity_invested", "Total equity invested", "$", results.total_equity_invested, NUM_CURRENCY),
            ("total_cash_returned", "Total cash returned", "$", results.total_cash_returned, NUM_CURRENCY),
            ("total_profit", "Total profit", "$", results.total_profit, NUM_CURRENCY),
            ("equity_multiple", "Equity multiple", "x", results.equity_multiple, NUM_MULTIPLE),
            ("levered_irr", "Levered IRR", "% per year", results.levered_irr, NUM_PERCENT),
            ("levered_irr_status", "Levered IRR availability", "status", IRR_STATUS_TEXT[results.levered_irr_status], "@"),
            ("unlevered_irr", "Unlevered IRR", "% per year", results.unlevered_irr, NUM_PERCENT),
            ("unlevered_irr_status", "Unlevered IRR availability", "status", IRR_STATUS_TEXT[results.unlevered_irr_status], "@"),
            ("post_hold_project_capital", "Post-hold project capital (disclosure)", "$", results.post_hold_project_capital, NUM_CURRENCY),
        )
        for key, label, units, value, number_format in scalars:
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            self.anchor[key] = self._frozen(sheet, row, 2, value, number_format)
            row += 1
        row += 1

        row = self._anchor_operating_rows(row, c0)

        self._section(sheet, row, "Annual results", last_col)
        row += 1
        self._period_header(sheet, row, c0, [f"Year {year}" for year in range(0, hold + 1)], left="Result")
        row += 1
        annual: tuple[tuple[str, str, str, Sequence[float | None], str], ...] = (
            ("noi", "Net operating income", "$", results.noi_by_year, NUM_CURRENCY),
            ("capex", "CapEx reserve (outflow)", "$", results.capex_by_year, NUM_CURRENCY),
            ("project_capital", "Business Plan project capital (outflow)", "$", results.project_capital_by_year, NUM_CURRENCY),
            ("owner_expenses", "Business Plan owner expenses (outflow)", "$", results.owner_expenses_by_year, NUM_CURRENCY),
            ("property_cf", "Property cash flow after CapEx", "$", results.property_cash_flow_by_year, NUM_CURRENCY),
            ("uocf", "Unlevered owner cash flow", "$", results.unlevered_owner_cash_flow_by_year, NUM_CURRENCY),
            ("debt_service", "Scheduled debt service", "$", results.annual_debt_service, NUM_CURRENCY),
            ("ending_balance", "Ending loan balance (see note)", "$", self.ending_balance_by_year, NUM_CURRENCY),
            ("dscr", "Debt service coverage", "x", results.dscr_by_year, NUM_MULTIPLE),
            ("locf", "Levered owner cash flow", "$", results.levered_owner_cash_flow_by_year, NUM_CURRENCY),
            ("coc", "Levered cash-on-cash", "%", results.levered_cash_on_cash_by_year, NUM_PERCENT),
            ("cum_dist", "Cumulative operating distributions", "$", results.cumulative_operating_distributions_by_year, NUM_CURRENCY),
            ("unlevered_yield", "Unlevered cash yield", "%", results.unlevered_cash_yield_by_year, NUM_PERCENT),
        )
        for key, label, units, values, number_format in annual:
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            for offset, value in enumerate(values):
                self.anchor[f"{key}:{offset + 1}"] = self._frozen(sheet, row, c0 + 1 + offset, value, number_format)
            row += 1
        for key, label, values in (
            ("ecf", "Equity cash flow", results.levered_cash_flows),
            ("ucf", "Unlevered project cash flow", results.unlevered_cash_flows),
        ):
            self._label(sheet, row, label, bold=True)
            self._units(sheet, row, "$")
            for t, value in enumerate(values):
                self.anchor[f"{key}:{t}"] = self._frozen(sheet, row, c0 + t, value, NUM_CURRENCY)
            row += 1
        ws.write_string(row, 0, self.DEBT_BALANCE_NOTE, self.fmt.note())
        row += 2

        # The frozen record of the exported inputs, laid out exactly like the
        # Inputs block so Checks can compare the two ranges cell for cell.
        self._section(sheet, row, "Exported inputs (frozen record)", last_col)
        row += 1
        self.record_first_row = row
        for entry in self.input_layout:
            if isinstance(entry, str):
                self._label(sheet, row, entry, bold=True)
            else:
                self._label(sheet, row, entry.label, indent=1)
                self._units(sheet, row, entry.units)
                self._frozen(sheet, row, 2, entry.value, entry.number_format)
            row += 1
        self.record_last_row = row - 1
        self.record_bp_rows: dict[str, int] = {}
        for key, label, values in (
            ("project_capital", "Business Plan project capital (resolved)", self.results.project_capital_by_year),
            ("owner_expenses", "Business Plan owner expenses (resolved)", self.results.owner_expenses_by_year),
        ):
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, "$")
            for offset, value in enumerate(values):
                self._frozen(sheet, row, c0 + 1 + offset, value, NUM_CURRENCY)
            self.record_bp_rows[key] = row
            row += 1
        ws.freeze_panes(0, 2)

    # ----------------------------------------------------------------- Checks

    def _operations_checks(self) -> list[_Check]:
        """The Operations group. Mode-specific: Quick reconciles NOI directly;
        Detailed reconciles every revenue and expense line that produces it."""

        raise NotImplementedError

    def _check_groups(self) -> list[tuple[str, list[_Check]]]:
        x, a = self.excel, self.anchor

        def loc(ref: str) -> str:
            return ref.replace("$", "")

        def neg(ref: str) -> str:
            return f"-{ref}"

        def check(metric: str, anchor_key: str, excel_ref: str, kind: str, number_format: str, *, negate: bool = False, key: str | None = None) -> _Check:
            return _Check(
                metric=metric,
                anchor=a[anchor_key],
                excel=neg(excel_ref) if negate else excel_ref,
                location=loc(excel_ref),
                kind=kind,
                number_format=number_format,
                key=key,
            )

        groups: list[tuple[str, list[_Check]]] = [
            (
                "Periods and identity",
                [
                    check("Hold period (years)", "hold_period", x["input:hold_period"], "exact", NUM_INTEGER),
                    _Check("Equity cash-flow periods", a["ecf_periods"], x["ecf_range_count"], f"'{EQUITY}' total equity cash flow row", "exact", NUM_INTEGER),
                ],
            ),
            ("Operations", self._operations_checks()),
            (
                "Acquisition and debt",
                [
                    check("Loan amount", "loan_amount", x["loan_amount"], "currency", NUM_CURRENCY_CENTS, key="loan_amount"),
                    check("Acquisition costs", "acquisition_costs", x["acquisition_costs_neg"], "currency", NUM_CURRENCY_CENTS, negate=True),
                    check("Financing fee", "financing_fee", x["financing_fee"], "currency", NUM_CURRENCY_CENTS),
                    check("Closing project capital", "closing_project_capital", x["closing_pc_neg"], "currency", NUM_CURRENCY_CENTS, negate=True),
                    check("Initial equity requirement", "initial_equity", x["acquisition_equity"], "currency", NUM_CURRENCY_CENTS, negate=True, key="initial_equity"),
                    check("Total closing uses", "total_closing_uses", x["total_closing_uses"], "currency", NUM_CURRENCY_CENTS),
                    check("Total closing sources", "total_closing_sources", x["total_closing_sources"], "currency", NUM_CURRENCY_CENTS),
                    check("Amortizing monthly payment", "monthly_debt_service", x["monthly_debt_service"], "currency", NUM_CURRENCY_CENTS),
                    *self._yearly("Scheduled debt service", "debt_service", "debt_service", "currency", NUM_CURRENCY_CENTS),
                    *self._yearly("Ending loan balance", "ending_balance", "ending_balance", "currency", NUM_CURRENCY_CENTS),
                    *self._yearly("Debt service coverage", "dscr", "dscr", "ratio", NUM_MULTIPLE_FINE),
                    check("Headline DSCR (Year 1)", "headline_dscr", x["headline_dscr"], "ratio", NUM_MULTIPLE_FINE, key="headline_dscr"),
                    check("Minimum DSCR", "min_dscr", x["min_dscr"], "ratio", NUM_MULTIPLE_FINE),
                    check("Year 1 debt yield", "year_1_debt_yield", x["year_1_debt_yield"], "ratio", NUM_PERCENT_FINE),
                ],
            ),
            (
                "Sale",
                [
                    check("Exit value (gross sale price)", "exit_value", x["exit_value"], "currency", NUM_CURRENCY_CENTS, key="exit_value"),
                    check("Disposition costs", "disposition_costs", x["disposition_costs_neg"], "currency", NUM_CURRENCY_CENTS, negate=True),
                    check("Debt payoff at sale", "remaining_loan_balance", x["remaining_loan_balance"], "currency", NUM_CURRENCY_CENTS),
                    check("Net sale proceeds", "net_sale_proceeds", x["net_sale_proceeds"], "currency", NUM_CURRENCY_CENTS, key="net_sale_proceeds"),
                ],
            ),
            (
                "Equity cash flow",
                [
                    *self._yearly("Levered owner cash flow", "locf", "locf", "currency", NUM_CURRENCY_CENTS),
                    *[
                        check(f"Equity cash flow, Year {t}", f"ecf:{t}", x[f"ecf:{t}"], "currency", NUM_CURRENCY_CENTS)
                        for t in range(0, self.hold + 1)
                    ],
                    *[
                        check(f"Unlevered project cash flow, Year {t}", f"ucf:{t}", x[f"ucf:{t}"], "currency", NUM_CURRENCY_CENTS)
                        for t in range(0, self.hold + 1)
                    ],
                ],
            ),
            (
                "Returns",
                [
                    check("Total equity invested", "total_equity_invested", x["total_equity_invested"], "currency", NUM_CURRENCY_CENTS, key="total_equity_invested"),
                    check("Total cash returned", "total_cash_returned", x["total_cash_returned"], "currency", NUM_CURRENCY_CENTS, key="total_cash_returned"),
                    check("Total profit", "total_profit", x["total_profit"], "currency", NUM_CURRENCY_CENTS, key="total_profit"),
                    check("Equity multiple", "equity_multiple", x["equity_multiple"], "ratio", NUM_MULTIPLE_FINE, key="equity_multiple"),
                    check("Levered IRR availability", "levered_irr_status", x["levered_irr_status"], "exact", "@"),
                    check("Levered IRR", "levered_irr", x["levered_irr"], "irr", NUM_PERCENT_FINE, key="levered_irr"),
                    check("Unlevered IRR availability", "unlevered_irr_status", x["unlevered_irr_status"], "exact", "@"),
                    check("Unlevered IRR", "unlevered_irr", x["unlevered_irr"], "irr", NUM_PERCENT_FINE, key="unlevered_irr"),
                    *self._yearly("Levered cash-on-cash", "coc", "coc", "ratio", NUM_PERCENT_FINE),
                    *self._yearly("Cumulative operating distributions", "cum_dist", "cum_dist", "currency", NUM_CURRENCY_CENTS),
                    *self._yearly("Unlevered cash yield", "unlevered_yield", "unlevered_yield", "ratio", NUM_PERCENT_FINE),
                ],
            ),
            (
                "Business Plan",
                [
                    check("Post-hold project capital (disclosure)", "post_hold_project_capital", x["original:post_hold_project_capital"], "currency", NUM_CURRENCY_CENTS),
                ],
            ),
        ]
        if "items:closing" in x:
            groups[-1][1].extend(
                [
                    check("Closing capital resolved from items", "closing_project_capital", x["items:closing"], "currency", NUM_CURRENCY_CENTS),
                    *self._yearly("Project capital resolved from items", "project_capital", "items:project_capital", "currency", NUM_CURRENCY_CENTS),
                    *self._yearly("Owner expenses resolved from items", "owner_expenses", "items:owner_expenses", "currency", NUM_CURRENCY_CENTS),
                ]
            )
        return groups

    def _check(self, metric: str, anchor_key: str, excel_ref: str, kind: str, number_format: str, *, negate: bool = False, key: str | None = None) -> _Check:
        return _Check(
            metric=metric,
            anchor=self.anchor[anchor_key],
            excel=f"-{excel_ref}" if negate else excel_ref,
            location=excel_ref.replace("$", ""),
            kind=kind,
            number_format=number_format,
            key=key,
        )

    def _yearly(self, label: str, anchor_prefix: str, excel_prefix: str, kind: str, number_format: str, *, negate: bool = False) -> list[_Check]:
        return [
            self._check(f"{label}, Year {year}", f"{anchor_prefix}:{year}", self.excel[f"{excel_prefix}:{year}"], kind, number_format, negate=negate)
            for year in self.years
        ]

    def _build_checks(self) -> None:
        sheet = CHECKS
        ws = self.sheets[sheet]
        self._checks_layout()
        self._title(
            sheet,
            "Checks",
            "Each row compares a frozen Anchor result with the Excel model. A missing, "
            "uncalculated or erroring Excel value never passes.",
        )
        last_col = 7
        row = 3
        self._section(sheet, row, "Workbook status", last_col)
        row += 1
        status_rows = {name: row + offset for offset, name in enumerate(
            ("recalculated", "differing", "modified", "original", "available", "total", "passed", "open", "first", "first_location", "explanation")
        )}

        def status_line(name: str, label: str) -> None:
            self._label(sheet, status_rows[name], label)

        status_line("recalculated", "Excel formulas recalculated")
        status_line("differing", "Working inputs that differ from the export")
        status_line("modified", "Workbook modified since export")
        status_line("original", "Original inputs unchanged")
        status_line("available", "Anchor reconciliation available")
        status_line("total", "Reconciliation checks")
        status_line("passed", "Passed")
        status_line("open", "Not passed")
        status_line("first", "First check not passed")
        status_line("first_location", "Its location")
        status_line("explanation", "What the comparison means")

        # Recalculation canary: a formula whose only cached value says it has
        # not been calculated.
        recalculated = self._status_formula(sheet, status_rows["recalculated"], 1, '="Yes"')
        self.book.define_name("Formulas_Recalculated", f"={recalculated}")

        first_input, last_input = self.inputs_first_row, self.inputs_last_row
        originals = _range(INPUTS, first_input, 1, last_input, 1)
        workings = _range(INPUTS, first_input, 2, last_input, 2)
        bp_terms = []
        record_terms = []
        for key in ("project_capital", "owner_expenses"):
            original_row, working_row = self.bp_rows[key]
            bp_o = _range(INPUTS, original_row, self.bp_first_col, original_row, self.bp_last_col)
            bp_w = _range(INPUTS, working_row, self.bp_first_col, working_row, self.bp_last_col)
            bp_terms.append(f"SUMPRODUCT(--({bp_w}<>{bp_o}))")
            record_row = self.record_bp_rows[key]
            record = _range(ANCHOR, record_row, 3, record_row, 3 + self.hold - 1)
            record_terms.append(f"SUMPRODUCT(--({bp_o}<>{record}))")
        differing = self._formula(
            sheet, status_rows["differing"], 1,
            f"=SUMPRODUCT(--({workings}<>{originals}))+" + "+".join(bp_terms),
            "link", NUM_INTEGER,
        )
        modified = self._status_formula(sheet, status_rows["modified"], 1, f'=IF({differing}>0,"Yes","No")')
        self.book.define_name("Workbook_Modified", f"={modified}")
        record_range = _range(ANCHOR, self.record_first_row, 2, self.record_last_row, 2)
        original_ok = self._status_formula(
            sheet, status_rows["original"], 1,
            f'=IF(SUMPRODUCT(--({originals}<>{record_range}))+' + "+".join(record_terms) + '=0,"Yes","No")',
            "link",
        )
        available = self._status_formula(
            sheet, status_rows["available"], 1,
            f'=IF({recalculated}<>"Yes","No: formulas not recalculated",'
            f'IF({modified}="Yes","No: Working Inputs modified",'
            f'IF({original_ok}<>"Yes","No: Original Export values altered","Yes")))',
        )
        self.book.define_name(
            "Model_State",
            f"={_xref(CHECKS, status_rows['explanation'], 1)}",
        )

        # Reconciliation table.
        row = status_rows["explanation"] + 2
        self._section(sheet, row, "Reconciliation", last_col)
        row += 1
        headers = ("Metric", "Anchor Result", "Excel Result", "Difference", "Tolerance", "Status", "Excel location", "Open")
        self._headers(
            sheet,
            row,
            [(col, text, "left" if col in (0, 5, 6) else "right") for col, text in enumerate(headers)],
        )
        header_row = row
        row += 1
        first_check_row = row
        groups = self._check_groups()
        for group, checks in groups:
            self._subsection(sheet, row, group, last_col)
            row += 1
            for check_row in checks:
                self._write_check(row, check_row, modified)
                row += 1
        last_check_row = row - 1
        ws.write_string(row + 1, 0, self.CHECKS_NOTE, self.fmt.note())

        statuses = _range(None, first_check_row, 5, last_check_row, 5)
        flags = _range(None, first_check_row, 7, last_check_row, 7)
        metrics = _range(None, first_check_row, 0, last_check_row, 0)
        total = self._formula(sheet, status_rows["total"], 1, f"=COUNTIF({flags},\">=0\")", "calc", NUM_INTEGER)
        self._formula(sheet, status_rows["passed"], 1, f"={total}-SUM({flags})", "calc", NUM_INTEGER)
        open_count = self._formula(sheet, status_rows["open"], 1, f"=SUM({flags})", "calc", NUM_INTEGER)
        self._status_formula(
            sheet, status_rows["first"], 1,
            f'=IF({open_count}=0,"None",INDEX({metrics},MATCH(1,{flags},0)))',
        )
        self._status_formula(
            sheet, status_rows["first_location"], 1,
            f'=IF({open_count}=0,"None","Checks!F"&ROW(INDEX({statuses},MATCH(1,{flags},0))))',
        )
        self._status_formula(
            sheet, status_rows["explanation"], 1,
            f'=IF({modified}="Yes","MODIFIED MODEL: Working Inputs differ from the exported inputs, so Excel '
            f'results describe a modified case and are not a like-for-like reconciliation with Anchor. '
            f'The frozen Anchor Results are unchanged.","Working Inputs equal the exported inputs: every row '
            f'below is a like-for-like reconciliation with Anchor.")',
        )
        self.check_summary = {
            "recalculated": recalculated,
            "modified": modified,
            "original": original_ok,
            "available": available,
            "total": total,
            "passed": _xref(CHECKS, status_rows["passed"], 1),
            "open": open_count,
            "first": _xref(CHECKS, status_rows["first"], 1),
            "first_location": _xref(CHECKS, status_rows["first_location"], 1),
            "explanation": _xref(CHECKS, status_rows["explanation"], 1),
        }

        fail_format = self.fmt.get(bold=True, font_color="#C00000")
        amber_format = self.fmt.get(font_color="#9C5700")
        pass_format = self.fmt.get(font_color="#006100")
        for text, cell_format, criteria in (
            (FAIL, fail_format, "begins with"),
            (EXCEL_ERROR, fail_format, "begins with"),
            (NOT_LIKE_FOR_LIKE, amber_format, "begins with"),
            (NOT_RECALCULATED, amber_format, "begins with"),
            (PASS, pass_format, "begins with"),
        ):
            ws.conditional_format(
                first_check_row, 5, last_check_row, 5,
                {"type": "text", "criteria": criteria, "value": text, "format": cell_format},
            )

        ws.freeze_panes(header_row + 1, 1)

    def _checks_layout(self) -> None:
        """Checks has its own column widths (two value columns, a difference
        and a tolerance, the status, the location and the open flag), set
        before anything is written so the headers can wrap."""

        sheet = CHECKS
        ws = self.sheets[sheet]
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, LABEL_WIDTH)
        self._set_column(sheet, 1, 2, 18)
        self._set_column(sheet, 3, 4, 12)
        self._set_column(sheet, 5, 5, 24)
        self._set_column(sheet, 6, 6, 34)
        self._set_column(sheet, 7, 7, 7)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)

    def _write_check(self, row: int, check: _Check, modified: str) -> None:
        sheet = CHECKS
        ws = self.sheets[sheet]
        ws.write_string(row, 0, check.metric, self.fmt.label(indent=1))
        b, c, d, e, f = (_cell(row, col) for col in range(1, 6))
        _write_formula(ws, row, 1, f"={check.anchor}", self.fmt.value("link", check.number_format), "")
        source = check.excel
        if check.excel.startswith("COUNT("):
            excel_formula = f"={source}"
        else:
            bare = source.lstrip("-")
            excel_formula = f'=IF(ISBLANK({bare}),"Missing",{source})'
        _write_formula(ws, row, 2, excel_formula, self.fmt.value("link", check.number_format), "")
        _write_formula(ws,
            row, 3, f'=IF(AND(ISNUMBER({b}),ISNUMBER({c})),{c}-{b},"n/a")',
            self.fmt.value("calc", NUM_SCIENTIFIC), "",
        )
        tolerance_format = self.fmt.value("calc", NUM_SCIENTIFIC)
        if check.kind == "exact":
            ws.write_string(row, 4, "Exact", self.fmt.get(align="right"))
            if check.number_format == "@":
                comparison = f'IF(EXACT({b},{c}),"{PASS}","{FAIL}")'
            else:
                comparison = f'IF(AND(ISNUMBER({b}),ISNUMBER({c})),IF({b}={c},"{PASS}","{FAIL}"),"{FAIL}")'
        else:
            if check.kind == "currency":
                _write_formula(ws,
                    row, 4,
                    f"=MAX({CURRENCY_ABSOLUTE_TOLERANCE},{CURRENCY_RELATIVE_TOLERANCE}*ABS(N({b})))",
                    tolerance_format, "",
                )
            else:
                ws.write_number(row, 4, RATIO_TOLERANCE if check.kind == "ratio" else IRR_TOLERANCE, tolerance_format)
            comparison = (
                f'IF(AND(ISNUMBER({b}),ISNUMBER({c})),IF(ABS({c}-{b})<={e},"{PASS}","{FAIL}"),'
                f'IF(AND({b}="{UNAVAILABLE}",{c}="{UNAVAILABLE}"),"{PASS_BOTH_UNAVAILABLE}","{FAIL}"))'
            )
        # A reconciliation row's Anchor side is a frozen number and cannot
        # error, so it is not tested; an identity row's is a live expression
        # and is.
        errored = f"OR(ISERROR({b}),ISERROR({c}))" if check.guard_anchor else f"ISERROR({c})"
        _write_formula(ws,
            row, 5,
            f'=IF({errored},"{EXCEL_ERROR}",IF({modified}="Yes","{NOT_LIKE_FOR_LIKE}",{comparison}))',
            self.fmt.status(), NOT_RECALCULATED,
        )
        self.status_by_metric[check.metric] = _xref(CHECKS, row, 5)
        ws.write_string(row, 6, check.location, self.fmt.units())
        _write_formula(ws, row, 7, f'=IF(LEFT({f},4)="{PASS}",0,1)', self.fmt.value("calc", "0"), "")
        if check.key is not None:
            self.status[check.key] = _xref(CHECKS, row, 5)
            self.excel[f"check_excel:{check.key}"] = _xref(CHECKS, row, 2)

    # ---------------------------------------------------------------- Summary

    def _summary_metrics(self) -> tuple[tuple[str, str, str, str | None, str], ...]:
        """The Summary key-metric rows. Mode-specific at the top (what the
        analyst reads first), identical from the loan amount down.

        Each row is ``(label, excel ref, anchor ref, check, number format)``.
        ``check`` names the Checks cell to echo: a ``_Check.key`` normally, or
        ``"metric:<metric label>"`` for a row whose check is a reconciliation
        row's own status. ``None`` shows whether the input is unchanged --
        used only where the row is an input, not a reconciled result."""

        raise NotImplementedError

    def _build_summary(self) -> None:
        sheet = SUMMARY
        ws = self.sheets[sheet]
        source = self.source
        self._summary_layout()
        ws.write_string(0, 0, self.WORKBOOK_TITLE, self.fmt.title())
        ws.set_row(0, 22)
        ws.write_string(1, 0, source.deal_name, self.fmt.get(bold=True, font_size=12))
        ws.write_string(2, 0, self.SUMMARY_NOTE, self.fmt.note())
        row = 4
        self._section(sheet, row, "Deal", 3)
        row += 1
        not_specified = "Not specified"
        facts = (
            ("Deal", source.deal_name),
            ("Asset Type", source.asset_type_label or not_specified),
            ("Asset subtype", source.asset_subtype or not_specified),
            ("Operating mode", self.MODE_LABEL),
            ("Status at export", self.STATUS_AT_EXPORT),
        )
        for label, value in facts:
            self._label(sheet, row, label)
            ws.write_string(row, 1, value, self.fmt.text())
            row += 1
        self._label(sheet, row, "Generated (UTC)")
        ws.write_datetime(
            row, 1,
            source.generated_at.astimezone(timezone.utc).replace(tzinfo=None),
            self.fmt.get(num_format=NUM_DATETIME, align="left"),
        )
        row += 1
        self._label(sheet, row, "Model state")
        _write_formula(ws, row, 1, f"={self.check_summary['modified']}", self.fmt.status("link"), NOT_RECALCULATED)
        ws.write_string(row, 2, "(Yes = Working Inputs modified since export)", self.fmt.units())
        row += 2

        self._section(sheet, row, "Key metrics", 3)
        row += 1
        self._headers(
            sheet,
            row,
            [
                (col, text, "left" if col in (0, 3) else "right")
                for col, text in enumerate(("Metric", "Excel model", "Anchor (exported)", "Check"))
            ],
        )
        row += 1
        for label, excel_ref, anchor_ref, status_key, number_format in self._summary_metrics():
            self._label(sheet, row, label, indent=1)
            self._formula(sheet, row, 1, f"={excel_ref}", "link", number_format)
            self._formula(sheet, row, 2, f"={anchor_ref}", "link", number_format)
            if status_key is not None and status_key.startswith("metric:"):
                _write_formula(ws, row, 3, "=" + self.status_by_metric[status_key[len("metric:"):]], self.fmt.status("link"), NOT_RECALCULATED)
            elif status_key is not None:
                _write_formula(ws, row, 3, f"={self.status[status_key]}", self.fmt.status("link"), NOT_RECALCULATED)
            else:
                input_status = f'IF({self.excel["input:purchase_price"]}={self.excel["original:purchase_price"]},"Input unchanged","Input modified")'
                _write_formula(ws, row, 3, f"={input_status}", self.fmt.status("link"), NOT_RECALCULATED)
            row += 1
        row += 1

        self._section(sheet, row, "Reconciliation", 3)
        row += 1
        summary = self.check_summary
        for label, ref in (
            ("Excel formulas recalculated", summary["recalculated"]),
            ("Workbook modified since export", summary["modified"]),
            ("Original inputs unchanged", summary["original"]),
            ("Anchor reconciliation available", summary["available"]),
            ("Reconciliation checks", summary["total"]),
            ("Passed", summary["passed"]),
            ("Not passed", summary["open"]),
            ("First check not passed", summary["first"]),
            ("Its location", summary["first_location"]),
        ):
            self._label(sheet, row, label, indent=1)
            is_count = label in ("Reconciliation checks", "Passed", "Not passed")
            if is_count:
                self._formula(sheet, row, 1, f"={ref}", "link", NUM_INTEGER)
            else:
                _write_formula(ws, row, 1, f"={ref}", self.fmt.status("link"), NOT_RECALCULATED)
            row += 1
        ws.write_string(
            row, 0,
            "If these cells read 'Not recalculated', the file was opened without calculation. "
            "Open it in Excel (or press Ctrl+Alt+F9) to recalculate every formula.",
            self.fmt.note(),
        )
        row += 2

        self._section(sheet, row, "Formatting legend", 3)
        row += 1
        legend = (
            ("Editable working input", "input", 1000),
            ("Calculation on the same sheet", "calc", 1000),
            ("Value brought from another sheet", "link", 1000),
            ("Frozen Anchor result", "frozen", 1000),
        )
        for label, role, sample in legend:
            self._label(sheet, row, label, indent=1)
            # The input sample is shown in input colours but stays locked:
            # the Summary has nothing to edit.
            sample_format = (
                self.fmt.get(num_format=NUM_CURRENCY, align="right", font_color=INPUT_BLUE, bg_color=INPUT_FILL)
                if role == "input"
                else self.fmt.value(role, NUM_CURRENCY)
            )
            ws.write_number(row, 1, sample, sample_format)
            row += 1
        self._label(sheet, row, "Negative amounts, zero and unavailable", indent=1)
        ws.write_number(row, 1, -1000, self.fmt.value("calc", NUM_CURRENCY))
        ws.write_number(row, 2, 0, self.fmt.value("calc", NUM_CURRENCY))
        ws.write_string(row, 3, UNAVAILABLE, self.fmt.get(align="left"))

    def _summary_layout(self) -> None:
        """Summary is a four-column sheet (metric, Excel, Anchor, check), laid
        out before anything is written so the headers can wrap."""

        sheet = SUMMARY
        ws = self.sheets[sheet]
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, 40)
        self._set_column(sheet, 1, 2, 20)
        self._set_column(sheet, 3, 3, 44)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)

    # --------------------------------------------------------- Audit Metadata

    def _audit_row(self, row: int, label: str, value: str, *, wrap_value: bool) -> None:
        """One label / value row on Audit Metadata.

        A label too long for its column wraps instead of being cut off by the
        value beside it -- the provenance qualification on the source commit is
        part of what the label says -- and the row grows to show every line.
        The height covers the value as well, so wrapping a label can never hide
        the value it names. A label that already fits is left exactly as it
        was, height included."""

        sheet = AUDIT
        ws = self.sheets[sheet]
        widths = self.column_width[sheet]
        label_width = widths.get(0, DEFAULT_COLUMN_WIDTH)
        value_format = self.fmt.text(wrap=wrap_value)
        if len(label) <= label_width * LABEL_CHARS_PER_WIDTH:
            self._label(sheet, row, label)
            ws.write_string(row, 1, value, value_format)
            return
        ws.write_string(row, 0, label, self.fmt.label(wrap=True))
        ws.write_string(row, 1, value, value_format)
        value_lines = (
            _wrapped_lines(value, int(widths.get(1, DEFAULT_COLUMN_WIDTH) - 1)) if wrap_value else 1
        )
        lines = max(_wrapped_lines(label, int(label_width - 1)), value_lines)
        ws.set_row(row, HEADER_LINE_HEIGHT * lines)

    def _extra_conventions(self) -> tuple[tuple[str, str], ...]:
        """Mode-specific convention rows, written after the NOI convention."""

        return ()

    def _build_audit(self) -> None:
        sheet = AUDIT
        ws = self.sheets[sheet]
        source = self.source
        plan = source.business_plan
        generated = source.generated_at.astimezone(timezone.utc)
        self._audit_layout()
        self._title(sheet, "Audit Metadata", "What this workbook was built from, and under which conventions.")
        row = 3
        self._section(sheet, row, "Provenance", 1)
        row += 1
        entries: list[tuple[str, str]] = [
            ("Deal name", source.deal_name),
            ("Deal ID", source.deal_id),
            ("Operating mode", self.MODE_LABEL),
            ("Asset Type", source.asset_type_label or "Not specified"),
            ("Asset subtype", source.asset_subtype or "Not specified"),
        ]
        for label, value in entries:
            self._audit_row(row, label, value, wrap_value=False)
            row += 1
        self._label(sheet, row, "Generated (UTC)")
        ws.write_datetime(row, 1, generated.replace(tzinfo=None), self.fmt.get(num_format=NUM_DATETIME, align="left"))
        row += 1
        more: list[tuple[str, str]] = [
            ("Generated (ISO 8601, with time zone)", generated.isoformat()),
            ("Anchor version", source.anchor_version),
            ("Source commit (checkout HEAD; uncommitted changes are not detected)", source.source_commit or "Not available"),
            ("Analysis fingerprint", source.analysis_fingerprint),
            ("Workbook contract", self.CONTRACT_VERSION),
            ("Source", self.AUDIT_SOURCE_NOTE),
            ("Business Plan", f"{len(plan.capital_items)} capital item(s) and {len(plan.owner_expense_items)} owner-expense item(s), resolved by Anchor into the annual totals on Inputs."),
        ]
        for label, value in more:
            self._audit_row(row, label, value, wrap_value=True)
            row += 1
        row += 1
        self._section(sheet, row, "Conventions", 1)
        row += 1
        conventions = (
            ("Currency", "Amounts are in the Deal's own currency units as entered; Anchor records no currency code."),
            ("Periods", f"Annual. Year 0 is acquisition; Years 1 to {self.hold} are hold years; the sale is at the end of Year {self.hold} and included in it. Year {self.hold + 1} NOI is used only for the exit value."),
            ("NOI", self.NOI_CONVENTION),
            *self._extra_conventions(),
            ("Exit", f"Gross sale price = Year {self.hold + 1} NOI / exit cap rate. Selling costs = gross sale price x disposition cost %. Net sale proceeds = gross sale price - selling costs - loan payoff."),
            ("Debt", "Fixed rate, monthly. Monthly rate = annual rate / 12. Interest-only months (IO years x 12) come first, then N = amortization x 12 amortizing payments. The balance is set to zero at contractual maturity; annual figures sum twelve months."),
            ("Fees", "Acquisition costs = purchase price x acquisition cost %. Financing fee = loan amount x financing fee %. Both are funded by equity and never change the loan."),
            ("Signs", "Equity cash flow: inflows positive, outflows negative. Total equity invested = sum of negative periods; total cash returned = sum of positive periods."),
            ("IRR", "Annual periodic IRR over equal intervals, so Excel's IRR (not XIRR) is the matching function. Anchor solves by bracket-and-bisection; Excel iterates. Both are guarded by the same sign rules; an unavailable IRR is never shown as a number."),
            ("Rounding", "No value is rounded; number formats affect display only."),
            ("Stored precision", "Numbers are stored to 16 significant digits (beyond Excel's 15-digit display), so a frozen Anchor value can differ from Anchor's own double in the last binary place: about 1 part in 10^16, far inside every tolerance."),
            ("Calculation mode", "Automatic, with a full recalculation requested when the file opens."),
            ("Tolerances", f"Currency: the larger of {CURRENCY_ABSOLUTE_TOLERANCE:g} and {CURRENCY_RELATIVE_TOLERANCE:g} x |Anchor value|. Ratios and multiples: {RATIO_TOLERANCE:g}. IRR: {IRR_TOLERANCE:g} (Excel's documented IRR precision). Counts, hold period and availability: exact."),
            ("Scope", self.SCOPE_NOTE),
        )
        for label, value in conventions:
            self._audit_row(row, label, value, wrap_value=True)
            row += 1

    def _audit_layout(self) -> None:
        """Audit Metadata is a label / value sheet, laid out before anything is
        written so a label can be measured against its column."""

        sheet = AUDIT
        ws = self.sheets[sheet]
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, 36)
        self._set_column(sheet, 1, 1, 110)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)
