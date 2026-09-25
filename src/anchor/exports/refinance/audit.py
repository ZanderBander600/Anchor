"""Refinance & Capital Events V1 Stage 3 -- the Refinance & Capital Structure
Audit workbook.

Implements ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 25.1,
the ratified Stage 3 export sub-contract, in the accepted export conventions
(``docs/architecture/EXCEL_EXPORT_1_QUICK_FORMULA_AUDIT.md`` Sections 4 to 7):
pessimistic formula caches, protected formula cells, blue editable inputs, a
formula-driven Checks sheet, ``Missing`` rather than zero for a deleted
formula, no macros, no external links and no volatile functions.

It reproduces, in live Excel formulas, and reconciles against Anchor:

- each retiring loan's monthly amortization through the event month, its
  scheduled payment in that month and its payoff after it;
- each enabled sizing capacity (fixed cap, maximum LTV, minimum DSCR), the
  minimum, every binding constraint and the tie;
- the bridge: gross proceeds, payoffs, replacement-lender fees, retiring-lender
  fees, third-party costs, the net event cash and its direction;
- the replacement loan's schedule through the sale;
- Common Equity: the pre-debt cash less every provider and third-party cost,
  the refinance event cash apart from the recurring cash, and the returns;
- each Partner's cash and returns where a Partnership exists.

**The headline is Common Equity** (or the Partners'). The acquisition-loan
levered figures appear once, frozen and labelled "Acquisition financing —
excludes later capital events". The workbook is an audit artifact: no
production module reads it, and no formula in it feeds an application result.
"""

from __future__ import annotations

from datetime import timezone
from io import BytesIO

from ..excel._workbook import (
    ACQUISITION_REFERENCE_LABEL,
    ANCHOR,
    AUDIT,
    CHECKS,
    CURRENCY_ABSOLUTE_TOLERANCE,
    CURRENCY_RELATIVE_TOLERANCE,
    EXCEL_ERROR,
    FAIL,
    INPUT_BLUE,
    INPUT_FILL,
    IRR_STATUS_TEXT,
    IRR_TOLERANCE,
    LABEL_WIDTH,
    NOT_LIKE_FOR_LIKE,
    NOT_RECALCULATED,
    NUM_CURRENCY,
    NUM_CURRENCY_CENTS,
    NUM_DATETIME,
    NUM_FLAG,
    NUM_INTEGER,
    NUM_MULTIPLE,
    NUM_MULTIPLE_FINE,
    NUM_PERCENT,
    NUM_PERCENT_FINE,
    PASS,
    PERIOD_WIDTH,
    RATIO_TOLERANCE,
    SUMMARY,
    UNAVAILABLE,
    UNITS_WIDTH,
    _AuditWorkbookBase,
    _Check,
    _Formats,
    _PROTECTION,
    _abs,
    _cell,
    _range,
    _write_formula,
    _xref,
    Worksheet,
    open_audit_workbook,
)
from .source import RefinanceAuditSource

CONTRACT_VERSION = "anchor.excel.refinance-capital-structure-audit/1"
WORKBOOK_TITLE = "Refinance & Capital Structure Audit"

INPUTS = "Inputs"
RETIRING = "Retiring Debt"
SIZING = "Sizing"
BRIDGE = "Bridge"
REPLACEMENT = "Replacement Loan"
EQUITY = "Common Equity"
PARTNERS = "Partners"

_CONSTRAINT_LABELS = {
    "fixed_cap": "Fixed maximum proceeds",
    "max_ltv": "Maximum LTV",
    "min_dscr": "Minimum DSCR",
}
_DIRECTION_TEXT = {"distribution": "Distribution", "contribution": "Contribution", "zero": "Zero"}

#: The Section 9.6 tie tolerance, relative to the gross proceeds.
BINDING_TOLERANCE = 1e-9


def _year_labels(first: int, last: int) -> list[str]:
    return [f"Year {year}" for year in range(first, last + 1)]


class _RefinanceAuditWorkbook(_AuditWorkbookBase):
    """One refinance audit. Sheets are added in their final order, then filled
    in dependency order so every cross-sheet reference is known when it is
    written."""

    WORKBOOK_TITLE = WORKBOOK_TITLE
    CONTRACT_VERSION = CONTRACT_VERSION

    def __init__(self, source: RefinanceAuditSource) -> None:  # noqa: D107 -- no acquisition model to reconcile
        self.source = source
        self.hold = source.hold_period
        self.years = tuple(range(1, self.hold + 1))
        self.output = BytesIO()
        self.book = open_audit_workbook(self.output)
        self.fmt = _Formats(self.book)
        sheets = [SUMMARY, INPUTS, RETIRING, SIZING, BRIDGE, REPLACEMENT, EQUITY]
        if source.partners is not None:
            sheets.append(PARTNERS)
        sheets.extend([ANCHOR, CHECKS, AUDIT])
        self.SHEETS = tuple(sheets)
        self.sheets: dict[str, Worksheet] = {name: self.book.add_worksheet(name) for name in self.SHEETS}
        self.column_width = {name: {} for name in self.SHEETS}
        self.excel: dict[str, str] = {}
        self.anchor: dict[str, str] = {}
        self.status: dict[str, str] = {}
        self.status_by_metric: dict[str, str] = {}
        self.checks: list[tuple[str, list[_Check]]] = []
        #: Every Original Export value, in input order, with its Anchor Results
        #: record cell, for the tamper check.
        self._records: list[tuple[str, float | str]] = []

    # ------------------------------------------------------------------ build

    def build(self) -> bytes:
        self._build_inputs()
        self._build_retiring()
        self._build_sizing()
        self._build_replacement()
        self._build_bridge()
        self._build_equity()
        if self.source.partners is not None:
            self._build_partners()
        self._build_anchor_results()
        self._build_checks()
        self._build_summary()
        self._build_audit()
        self._finish()
        self.book.close()
        return self.output.getvalue()

    def _finish(self) -> None:
        generated = self.source.generated_at.astimezone(timezone.utc).replace(tzinfo=None)
        self.book.set_properties(
            {
                "title": f"{self.source.investment_name} - {WORKBOOK_TITLE}",
                "subject": "Refinance & Capital Structure formula audit",
                "author": "Anchor",
                "comments": CONTRACT_VERSION,
                "created": generated,
            }
        )
        self.book.set_calc_mode("auto")
        self.sheets[SUMMARY].activate()

    # ------------------------------------------------------------- layouts

    def _layout(self, sheet: str, period_columns: int, *, label_width: float = LABEL_WIDTH) -> None:
        ws = self.sheets[sheet]
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, label_width)
        self._set_column(sheet, 1, 1, UNITS_WIDTH)
        if period_columns:
            self._set_column(sheet, 2, 1 + period_columns, PERIOD_WIDTH)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)

    def _period_row_header(self, sheet: str, row: int, first_year: int = 0) -> None:
        self._headers(
            sheet,
            row,
            [(0, "Period", "left"), (1, "", "right"), *((2 + offset, text, "right") for offset, text in enumerate(_year_labels(first_year, self.hold)))],
        )

    # ------------------------------------------------------------------ Inputs

    def _build_inputs(self) -> None:
        sheet = INPUTS
        ws = self.sheets[sheet]
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, LABEL_WIDTH)
        self._set_column(sheet, 1, 1, UNITS_WIDTH)
        self._set_column(sheet, 2, 3, 20)
        self._set_column(sheet, 4, 4, 22)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)
        self._title(
            sheet,
            "Inputs",
            "Original Export is what Anchor analysed. Working Input starts equal to it and is the only column the "
            "model reads; edit it to explore a modified case.",
        )
        row = 3
        self._headers(
            sheet,
            row,
            [(0, "Input", "left"), (1, "Units", "left"), (2, "Original Export", "right"), (3, "Working Input", "right"), (4, "Status", "left")],
        )
        row += 1
        self.inputs_first_row = row
        self.inputs: dict[str, str] = {}

        def write(key: str, label: str, units: str, value: float, number_format: str, *, editable: bool = True) -> None:
            nonlocal row
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            original = self._frozen(sheet, row, 2, value, number_format)
            if editable:
                ws.write_number(row, 3, float(value), self.fmt.value("input", number_format))
            else:
                self._formula(sheet, row, 3, f"={_cell(row, 2)}", "calc", number_format)
            status = (
                f'IF({_cell(row, 3)}={_cell(row, 2)},"Unchanged","Modified")' if editable else '"Fixed at export"'
            )
            self._status_formula(sheet, row, 4, f"={status}")
            self.inputs[key] = _xref(sheet, row, 3)
            self.excel[f"original:{key}"] = original
            self._records.append((key, value))
            row += 1

        write("hold", "Hold period", "years", self.hold, NUM_INTEGER, editable=False)
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            row += 1
            self._section(sheet, row, f"Refinance {index} — {event.label} ({event.scope_name})", 4)
            row += 1
            write(f"{e}:month", "Refinance date (model month; end of hold year)", "month", event.model_month, NUM_INTEGER, editable=False)
            write(f"{e}:year", "Refinance hold year", "year", event.hold_year, NUM_INTEGER, editable=False)
            for loan_index, loan in enumerate(event.retiring, start=1):
                r = f"{e}:r{loan_index}"
                self._subsection(sheet, row, f"Loan repaid: {loan.name}", 4)
                row += 1
                write(f"{r}:principal", "Principal at closing", "$", loan.principal, NUM_CURRENCY)
                write(f"{r}:rate", "Interest rate", "% per year", loan.interest_rate, NUM_PERCENT_FINE)
                write(f"{r}:amort", "Amortization", "years", loan.amortization, NUM_INTEGER)
                write(f"{r}:io", "Interest-only period", "years", loan.io_period, NUM_INTEGER)
                for fee_index, fee in enumerate(loan.closing_fees, start=1):
                    write(f"{r}:closing_fee:{fee_index}", f"Closing fee — {fee.description}", "$", fee.amount, NUM_CURRENCY)
            self._subsection(sheet, row, f"Replacement loan: {event.replacement.name} ({event.replacement.class_label})", 4)
            row += 1
            rep = event.replacement
            write(f"{e}:rep:rate", "Interest rate", "% per year", rep.interest_rate, NUM_PERCENT_FINE)
            write(f"{e}:rep:amort", "Amortization", "years", rep.amortization, NUM_INTEGER)
            write(f"{e}:rep:io", "Interest-only period", "years", rep.io_period, NUM_INTEGER)
            write(f"{e}:rep:maturity", "Legal maturity", "model month", rep.maturity_month, NUM_INTEGER)
            for fee_index, fee in enumerate(rep.lender_fees, start=1):
                write(f"{e}:rep:fee:{fee_index}", f"Replacement-lender fee — {fee.description}", "$", fee.amount, NUM_CURRENCY)
            self._subsection(sheet, row, "Sizing constraints and their dependencies", 4)
            row += 1
            if event.fixed_cap is not None:
                write(f"{e}:fixed", "Fixed maximum proceeds", "$", event.fixed_cap, NUM_CURRENCY)
            if event.max_ltv is not None:
                write(f"{e}:ltv", "Maximum LTV", "%", event.max_ltv, NUM_PERCENT)
                label = "Contemporaneous value" + (f" — {event.value_label}" if event.value_label else "")
                if event.value_analyst_supplied:
                    label += " (Analyst-Supplied Value)"
                write(f"{e}:value", label, "$", event.value or 0.0, NUM_CURRENCY)
                write(f"{e}:ltv_senior", "Continuing senior debt balance at the refinance", "$", event.continuing_senior_balance or 0.0, NUM_CURRENCY)
            if event.min_dscr is not None:
                write(f"{e}:dscr", "Minimum DSCR", "x", event.min_dscr, NUM_MULTIPLE_FINE)
                write(f"{e}:noi", f"Forward NOI (Year {event.forward_year})", "$", event.forward_noi or 0.0, NUM_CURRENCY)
                write(f"{e}:dscr_senior", "Continuing senior debt service, first year after", "$", event.continuing_senior_service or 0.0, NUM_CURRENCY)
            self._subsection(sheet, row, "Refinance costs", 4)
            row += 1
            for fee_index, (description, recipient, amount) in enumerate(event.retiring_fee_lines, start=1):
                write(f"{e}:xfee:{fee_index}", f"Retiring-lender fee — {description} (to {recipient})", "$", amount, NUM_CURRENCY)
            for cost_index, cost in enumerate(event.third_party_costs, start=1):
                write(f"{e}:tp:{cost_index}", f"Third-party cost — {cost.description}", "$", cost.amount, NUM_CURRENCY)
            if not event.retiring_fee_lines and not event.third_party_costs:
                ws.write_string(row, 0, "No retiring-lender fee or third-party cost.", self.fmt.note())
                row += 1
        self.inputs_last_row = row - 1
        ws.freeze_panes(4, 1)

    def _input(self, key: str) -> str:
        return self.inputs[key]

    def _sum_inputs(self, keys: list[str]) -> str:
        return "0" if not keys else "SUM(" + ",".join(self.inputs[key] for key in keys) + ")"

    # ------------------------------------------------------------ Retiring Debt

    def _build_retiring(self) -> None:
        sheet = RETIRING
        ws = self.sheets[sheet]
        self._layout(sheet, max(self.hold + 1, 7))
        self._title(
            sheet,
            "Retiring Debt",
            "Each loan a refinance repays, amortized month by month through the refinance month: interest = beginning "
            "balance x monthly rate; principal = payment - interest. The payoff is the balance immediately after the "
            "refinance month's scheduled payment.",
        )
        row = 3
        month_format = self.fmt.get(align="left", num_format="0")
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            m = event.model_month
            for loan_index, loan in enumerate(event.retiring, start=1):
                r = f"{e}:r{loan_index}"
                self._section(sheet, row, f"{event.label} — {loan.name}", 8)
                row += 1
                terms: dict[str, str] = {}

                def line(key: str, label: str, units: str, formula: str, role: str, number_format: str, *, bold: bool = False) -> None:
                    nonlocal row
                    self._label(sheet, row, label, indent=0 if bold else 1, bold=bold)
                    self._units(sheet, row, units)
                    terms[key] = self._formula(sheet, row, 2, formula, role, number_format, bold=bold).replace(f"'{sheet}'!", "")
                    row += 1

                line("P", "Principal", "$", f"={self._input(f'{r}:principal')}", "link", NUM_CURRENCY)
                line("rate", "Interest rate", "% per year", f"={self._input(f'{r}:rate')}", "link", NUM_PERCENT_FINE)
                line("amort", "Amortization", "years", f"={self._input(f'{r}:amort')}", "link", NUM_INTEGER)
                line("io", "Interest-only period", "years", f"={self._input(f'{r}:io')}", "link", NUM_INTEGER)
                line("r", "Monthly rate  (annual rate / 12)", "% per month", f"={terms['rate']}/12", "calc", NUM_PERCENT_FINE)
                line("n", "Amortizing payments  (amortization x 12)", "months", f"={terms['amort']}*12", "calc", NUM_INTEGER)
                line("io_m", "Interest-only months  (IO period x 12)", "months", f"={terms['io']}*12", "calc", NUM_INTEGER)
                line("io_pmt", "Interest-only payment  (principal x monthly rate)", "$ per month", f"={terms['P']}*{terms['r']}", "calc", NUM_CURRENCY_CENTS)
                line(
                    "pmt",
                    "Amortizing payment  P x r / (1 - (1 + r)^-N)",
                    "$ per month",
                    f"=IF({terms['P']}=0,0,IF({terms['r']}=0,{terms['P']}/{terms['n']},{terms['P']}*({terms['r']}/(1-(1+{terms['r']})^(-{terms['n']})))))",
                    "calc",
                    NUM_CURRENCY_CENTS,
                )
                line("full", "Full amortization month  (IO months + N)", "month", f"={terms['io_m']}+{terms['n']}", "calc", NUM_INTEGER)
                line("m", "Refinance month", "month", f"={self._input(f'{e}:month')}", "link", NUM_INTEGER)
                row += 1

                # Monthly schedule, months 1..m.
                self._headers(
                    sheet,
                    row,
                    [(col, text, "left" if col == 0 else "right") for col, text in enumerate(("Month", "Hold year", "Beginning balance", "Payment", "Interest", "Principal", "Ending balance"))],
                )
                row += 1
                first = row
                for month in range(1, m + 1):
                    mm = _cell(row, 0)
                    ws.write_number(row, 0, month, month_format)
                    ws.write_number(row, 1, (month - 1) // 12 + 1, self.fmt.value("calc", NUM_INTEGER))
                    beginning = f"={terms['P']}" if month == 1 else f"={_cell(row - 1, 6)}"
                    self._formula(sheet, row, 2, beginning, "calc", NUM_CURRENCY_CENTS)
                    self._formula(
                        sheet, row, 3,
                        f"=IF({mm}<={terms['io_m']},{terms['io_pmt']},IF({mm}-{terms['io_m']}<={terms['n']},{terms['pmt']},0))",
                        "calc", NUM_CURRENCY_CENTS,
                    )
                    self._formula(sheet, row, 4, f"={_cell(row, 2)}*{terms['r']}", "calc", NUM_CURRENCY_CENTS)
                    self._formula(sheet, row, 5, f"={_cell(row, 3)}-{_cell(row, 4)}", "calc", NUM_CURRENCY_CENTS)
                    self._formula(sheet, row, 6, f"=IF({mm}={terms['full']},0,{_cell(row, 2)}-{_cell(row, 5)})", "calc", NUM_CURRENCY_CENTS)
                    row += 1
                last = row - 1
                row += 1
                self._label(sheet, row, "Scheduled payment in the refinance month (operating debt service of its year)", indent=1)
                self._units(sheet, row, "$")
                self.excel[f"{r}:payment_at_m"] = self._formula(sheet, row, 2, f"={_cell(last, 3)}", "calc", NUM_CURRENCY_CENTS)
                row += 1
                self._label(sheet, row, "Payoff  (balance immediately after that payment)", bold=True)
                self._units(sheet, row, "$")
                self.excel[f"{r}:payoff"] = self._formula(sheet, row, 2, f"={_cell(last, 6)}", "calc", NUM_CURRENCY_CENTS, bold=True)
                row += 1
                fee_keys = [
                    f"{e}:xfee:{fee_index}"
                    for fee_index, (_, recipient, _) in enumerate(event.retiring_fee_lines, start=1)
                    if recipient == loan.name
                ]
                self._label(sheet, row, "Retiring-lender fees paid to this lender at the refinance", indent=1)
                self._units(sheet, row, "$")
                self.excel[f"{r}:xfees"] = self._formula(sheet, row, 2, f"={self._sum_inputs(fee_keys)}", "link", NUM_CURRENCY_CENTS)
                row += 2

                # The provider's annual cash, Year 0..H.
                self._period_row_header(sheet, row)
                row += 1
                self._label(sheet, row, "Provider cash flow  (funding -, service, payoff and fees +)", bold=True)
                self._units(sheet, row, "$")
                closing_fees = self._sum_inputs([f"{r}:closing_fee:{i}" for i in range(1, len(loan.closing_fees) + 1)])
                years = _range(None, first, 1, last, 1)
                payments = _range(None, first, 3, last, 3)
                for t in range(0, self.hold + 1):
                    col = 2 + t
                    if t == 0:
                        formula = f"=-{terms['P']}+{closing_fees}"
                    elif t < event.hold_year:
                        formula = f"=SUMIF({years},{t},{payments})"
                    elif t == event.hold_year:
                        formula = f"=SUMIF({years},{t},{payments})+{self.excel[f'{r}:payoff']}+{self.excel[f'{r}:xfees']}"
                    else:
                        formula = "=0"
                    self.excel[f"{r}:provider:{t}"] = self._formula(sheet, row, col, formula, "calc", NUM_CURRENCY, bold=True)
                row += 3
        ws.freeze_panes(0, 1)

    # ------------------------------------------------------------------ Sizing

    def _build_sizing(self) -> None:
        sheet = SIZING
        ws = self.sheets[sheet]
        self._layout(sheet, 4)
        self._title(
            sheet,
            "Sizing",
            "Each enabled constraint's capacity, the least of them, and every constraint within the tie tolerance "
            "of it. A cap limits proceeds; it never instructs more than another constraint allows.",
        )
        row = 3
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            self._section(sheet, row, f"{event.label} ({event.scope_name}), end of Year {event.hold_year}", 4)
            row += 1
            capacities: list[tuple[str, str]] = []

            def line(key: str, label: str, units: str, formula: str, role: str, number_format: str, *, bold: bool = False, status: bool = False) -> str:
                nonlocal row
                self._label(sheet, row, label, indent=0 if bold else 1, bold=bold)
                self._units(sheet, row, units)
                if status:
                    ref = self._status_formula(sheet, row, 2, formula)
                else:
                    ref = self._formula(sheet, row, 2, formula, role, number_format, bold=bold)
                self.excel[key] = ref
                row += 1
                return ref

            if event.fixed_cap is not None:
                self._subsection(sheet, row, "Fixed maximum proceeds", 4)
                row += 1
                capacities.append(("fixed_cap", line(f"{e}:cap:fixed_cap", "Capacity  (the authored cap)", "$", f"={self._input(f'{e}:fixed')}", "link", NUM_CURRENCY, bold=True)))
            if event.max_ltv is not None:
                self._subsection(sheet, row, "Maximum LTV, through the replacement's rank", 4)
                row += 1
                ltv = line(f"{e}:ltv", "Maximum LTV", "%", f"={self._input(f'{e}:ltv')}", "link", NUM_PERCENT)
                value = line(f"{e}:value", "Contemporaneous value" + (f" — {event.value_label}" if event.value_label else ""), "$", f"={self._input(f'{e}:value')}", "link", NUM_CURRENCY)
                senior = line(f"{e}:ltv_senior", "Continuing senior debt balance", "$", f"={self._input(f'{e}:ltv_senior')}", "link", NUM_CURRENCY)
                capacities.append(("max_ltv", line(f"{e}:cap:max_ltv", "Capacity  (maximum LTV x value - continuing senior balance)", "$", f"={ltv}*{value}-{senior}", "calc", NUM_CURRENCY, bold=True)))
            if event.min_dscr is not None:
                self._subsection(sheet, row, f"Minimum DSCR, through the replacement's rank (Year {event.forward_year} forward NOI)", 4)
                row += 1
                dscr = line(f"{e}:dscr", "Minimum DSCR", "x", f"={self._input(f'{e}:dscr')}", "link", NUM_MULTIPLE_FINE)
                noi = line(f"{e}:noi", f"Forward NOI (Year {event.forward_year})", "$", f"={self._input(f'{e}:noi')}", "link", NUM_CURRENCY)
                senior = line(f"{e}:dscr_senior", "Continuing senior debt service", "$", f"={self._input(f'{e}:dscr_senior')}", "link", NUM_CURRENCY)
                service = line(f"{e}:service_capacity", "Service capacity  (forward NOI / minimum DSCR - continuing senior service)", "$", f"={noi}/{dscr}-{senior}", "calc", NUM_CURRENCY)
                rate = line(f"{e}:s_rate", "Replacement interest rate", "% per year", f"={self._input(f'{e}:rep:rate')}", "link", NUM_PERCENT_FINE)
                io = line(f"{e}:s_io", "Replacement interest-only period", "years", f"={self._input(f'{e}:rep:io')}", "link", NUM_INTEGER)
                amort = line(f"{e}:s_amort", "Replacement amortization", "years", f"={self._input(f'{e}:rep:amort')}", "link", NUM_INTEGER)
                r = line(f"{e}:s_r", "Monthly rate", "% per month", f"={rate}/12", "calc", NUM_PERCENT_FINE)
                n = line(f"{e}:s_n", "Amortizing payments", "months", f"={amort}*12", "calc", NUM_INTEGER)
                per_dollar = line(
                    f"{e}:per_dollar",
                    "First-year service per $1 of loan  (twelve interest-only, or twelve amortizing, payments)",
                    "$ per $1",
                    f"=IF({io}>=1,12*{r},IF({r}=0,12/{n},12*({r}/(1-(1+{r})^(-{n})))))",
                    "calc",
                    NUM_PERCENT_FINE,
                )
                capacities.append(("min_dscr", line(f"{e}:cap:min_dscr", "Capacity  (service capacity / first-year service per $1)", "$", f'=IF({per_dollar}=0,"{UNAVAILABLE}",{service}/{per_dollar})', "calc", NUM_CURRENCY, bold=True)))
                ws.write_string(row, 0, "V1 basis: the replacement's actual first-year scheduled service, interest-only months included.", self.fmt.note())
                row += 1
            self._subsection(sheet, row, "The minimum and what binds", 4)
            row += 1
            gross = line(f"{e}:gross", "Gross proceeds  (least enabled capacity)", "$", "=MIN(" + ",".join(ref for _, ref in capacities) + ")", "calc", NUM_CURRENCY, bold=True)
            tolerance = line(f"{e}:tolerance", "Tie tolerance  (1e-9 x max(1, |gross proceeds|))", "$", f"={BINDING_TOLERANCE}*MAX(1,ABS({gross}))", "calc", NUM_CURRENCY_CENTS)
            flags: list[tuple[str, str]] = []
            for kind, capacity in capacities:
                flags.append((kind, line(f"{e}:binds:{kind}", f"{_CONSTRAINT_LABELS[kind]} binds", "flag", f"=IF({capacity}-{gross}<={tolerance},1,0)", "calc", NUM_FLAG)))
            count = line(f"{e}:binding_count", "Constraints binding", "count", "=" + "+".join(ref for _, ref in flags), "calc", NUM_INTEGER)
            text = "&".join(f'IF({ref}=1,", {_CONSTRAINT_LABELS[kind]}","")' for kind, ref in flags)
            line(f"{e}:binding_text", "Binding constraint(s)", "text", f"=MID({text},3,200)", "calc", "@", status=True)
            line(f"{e}:tie", "Tie", "text", f'=IF({count}>1,"Yes","No")', "calc", "@", status=True)
            row += 1
        ws.freeze_panes(0, 1)

    # ------------------------------------------------------- Replacement Loan

    def _build_replacement(self) -> None:
        sheet = REPLACEMENT
        ws = self.sheets[sheet]
        self._layout(sheet, max(self.hold + 1, 8))
        self._title(
            sheet,
            "Replacement Loan",
            "The replacement funds the gross proceeds at the refinance month. Its first payment is the next month; "
            "its balance is repaid at the earlier of its legal maturity and the sale.",
        )
        row = 3
        month_format = self.fmt.get(align="left", num_format="0")
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            m = event.model_month
            sale = 12 * self.hold
            self._section(sheet, row, f"{event.label} — {event.replacement.name}", 8)
            row += 1
            terms: dict[str, str] = {}

            def line(key: str, label: str, units: str, formula: str, role: str, number_format: str, *, bold: bool = False) -> None:
                nonlocal row
                self._label(sheet, row, label, indent=0 if bold else 1, bold=bold)
                self._units(sheet, row, units)
                terms[key] = self._formula(sheet, row, 2, formula, role, number_format, bold=bold).replace(f"'{sheet}'!", "")
                row += 1

            line("G", "Principal  (gross proceeds)", "$", f"={self.excel[f'{e}:gross']}", "link", NUM_CURRENCY)
            line("rate", "Interest rate", "% per year", f"={self._input(f'{e}:rep:rate')}", "link", NUM_PERCENT_FINE)
            line("amort", "Amortization", "years", f"={self._input(f'{e}:rep:amort')}", "link", NUM_INTEGER)
            line("io", "Interest-only period", "years", f"={self._input(f'{e}:rep:io')}", "link", NUM_INTEGER)
            line("maturity", "Legal maturity", "model month", f"={self._input(f'{e}:rep:maturity')}", "link", NUM_INTEGER)
            line("m", "Funding month  (the refinance month)", "month", f"={self._input(f'{e}:month')}", "link", NUM_INTEGER)
            line("r", "Monthly rate", "% per month", f"={terms['rate']}/12", "calc", NUM_PERCENT_FINE)
            line("n", "Amortizing payments", "months", f"={terms['amort']}*12", "calc", NUM_INTEGER)
            line("io_m", "Interest-only months", "months", f"={terms['io']}*12", "calc", NUM_INTEGER)
            line("io_pmt", "Interest-only payment", "$ per month", f"={terms['G']}*{terms['r']}", "calc", NUM_CURRENCY_CENTS)
            line(
                "pmt",
                "Amortizing payment  G x r / (1 - (1 + r)^-N)",
                "$ per month",
                f"=IF({terms['G']}=0,0,IF({terms['r']}=0,{terms['G']}/{terms['n']},{terms['G']}*({terms['r']}/(1-(1+{terms['r']})^(-{terms['n']})))))",
                "calc",
                NUM_CURRENCY_CENTS,
            )
            line("payoff_month", "Modeled payoff month  (earlier of legal maturity and the sale)", "month", f"=MIN({terms['maturity']},{self.hold}*12)", "calc", NUM_INTEGER)
            line("fees", "Replacement-lender fees, paid at the refinance", "$", f"={self._sum_inputs([f'{e}:rep:fee:{i}' for i in range(1, len(event.replacement.lender_fees) + 1)])}", "link", NUM_CURRENCY)
            self.excel[f"{e}:rep_fees"] = _xref(sheet, row - 1, 2)
            row += 1
            self._headers(
                sheet,
                row,
                [(col, text, "left" if col == 0 else "right") for col, text in enumerate(("Month", "Hold year", "Beginning balance", "Payment", "Interest", "Principal", "Repaid at payoff", "Ending balance"))],
            )
            row += 1
            first = row
            for month in range(m + 1, sale + 1):
                mm = _cell(row, 0)
                ws.write_number(row, 0, month, month_format)
                ws.write_number(row, 1, (month - 1) // 12 + 1, self.fmt.value("calc", NUM_INTEGER))
                beginning = f"={terms['G']}" if month == m + 1 else f"={_cell(row - 1, 7)}"
                self._formula(sheet, row, 2, beginning, "calc", NUM_CURRENCY_CENTS)
                k = f"({mm}-{terms['m']})"
                self._formula(
                    sheet, row, 3,
                    f"=IF({mm}>{terms['payoff_month']},0,IF({k}<={terms['io_m']},{terms['io_pmt']},IF({k}-{terms['io_m']}<={terms['n']},{terms['pmt']},0)))",
                    "calc", NUM_CURRENCY_CENTS,
                )
                self._formula(sheet, row, 4, f"={_cell(row, 2)}*{terms['r']}", "calc", NUM_CURRENCY_CENTS)
                self._formula(sheet, row, 5, f"=IF({mm}>{terms['payoff_month']},0,{_cell(row, 3)}-{_cell(row, 4)})", "calc", NUM_CURRENCY_CENTS)
                self._formula(sheet, row, 6, f"=IF({mm}={terms['payoff_month']},{_cell(row, 2)}-{_cell(row, 5)},0)", "calc", NUM_CURRENCY_CENTS)
                self._formula(
                    sheet, row, 7,
                    f"=IF(OR({mm}>={terms['payoff_month']},{k}={terms['io_m']}+{terms['n']}),0,{_cell(row, 2)}-{_cell(row, 5)})",
                    "calc", NUM_CURRENCY_CENTS,
                )
                row += 1
            last = row - 1
            row += 1
            self._label(sheet, row, "First-year scheduled service  (the twelve months after funding)", bold=True)
            self._units(sheet, row, "$")
            self.excel[f"{e}:first_year_service"] = self._formula(
                sheet, row, 2, f"=SUM({_cell(first, 3)}:{_cell(min(first + 11, last), 3)})", "calc", NUM_CURRENCY_CENTS, bold=True
            )
            row += 2
            self._period_row_header(sheet, row)
            row += 1
            self._label(sheet, row, "Provider cash flow  (funding -, fees, service and payoff +)", bold=True)
            self._units(sheet, row, "$")
            years = _range(None, first, 1, last, 1)
            payments = _range(None, first, 3, last, 3)
            payoffs = _range(None, first, 6, last, 6)
            for t in range(0, self.hold + 1):
                col = 2 + t
                if t < event.hold_year:
                    formula = "=0"
                elif t == event.hold_year:
                    formula = f"=-{terms['G']}+{terms['fees']}"
                else:
                    formula = f"=SUMIF({years},{t},{payments})+SUMIF({years},{t},{payoffs})"
                self.excel[f"{e}:rep_provider:{t}"] = self._formula(sheet, row, col, formula, "calc", NUM_CURRENCY, bold=True)
            row += 3
        ws.freeze_panes(0, 1)

    # ------------------------------------------------------------------ Bridge

    def _build_bridge(self) -> None:
        sheet = BRIDGE
        self._layout(sheet, 1)
        self._title(
            sheet,
            "Bridge",
            "Net refinance cash = gross proceeds - payoffs - replacement-lender fees - retiring-lender fees - "
            "third-party costs. Positive is a Common Equity distribution; negative an explicit contribution.",
        )
        row = 3
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            self._section(sheet, row, f"{event.label} ({event.scope_name}), end of Year {event.hold_year}", 2)
            row += 1

            def line(key: str, label: str, formula: str, role: str, *, bold: bool = False, number_format: str = NUM_CURRENCY_CENTS) -> str:
                nonlocal row
                self._label(sheet, row, label, indent=0 if bold else 1, bold=bold)
                self._units(sheet, row, "$" if number_format != "@" else "text")
                ref = (
                    self._status_formula(sheet, row, 2, formula)
                    if number_format == "@"
                    else self._formula(sheet, row, 2, formula, role, number_format, bold=bold)
                )
                self.excel[key] = ref
                row += 1
                return ref

            gross = line(f"{e}:bridge_gross", f"Gross proceeds — {event.replacement.name}", f"={self.excel[f'{e}:gross']}", "link")
            payoff_refs = [
                line(f"{e}:bridge_payoff:{loan_index}", f"Less payoff — {loan.name}", f"={self.excel[f'{e}:r{loan_index}:payoff']}", "link")
                for loan_index, loan in enumerate(event.retiring, start=1)
            ]
            payoffs = line(f"{e}:payoffs", "Total payoffs", "=" + "+".join(payoff_refs), "calc")
            fr = line(f"{e}:fr", "Less replacement-lender fees", f"={self.excel[f'{e}:rep_fees']}", "link")
            fx = line(f"{e}:fx", "Less retiring-lender fees", f"={self._sum_inputs([f'{e}:xfee:{i}' for i in range(1, len(event.retiring_fee_lines) + 1)])}", "link")
            tp = line(f"{e}:tp", "Less third-party costs", f"={self._sum_inputs([f'{e}:tp:{i}' for i in range(1, len(event.third_party_costs) + 1)])}", "link")
            net = line(f"{e}:net", "Net refinance cash to Common Equity", f"={gross}-{payoffs}-{fr}-{fx}-{tp}", "calc", bold=True)
            line(f"{e}:direction", "Direction", f'=IF({net}>0,"Distribution",IF({net}<0,"Contribution","Zero"))', "calc", number_format="@")
            # Achieved leverage and coverage, reported rather than used for
            # sizing, each only where its dependency exists.
            if event.max_ltv is not None:
                line(
                    f"{e}:achieved_ltv",
                    "Achieved LTV  ((gross proceeds + continuing senior balance) / value)",
                    f"=({gross}+{self.excel[f'{e}:ltv_senior']})/{self.excel[f'{e}:value']}",
                    "calc",
                    number_format=NUM_PERCENT_FINE,
                )
            else:
                self._label(sheet, row, "Achieved LTV  (no LTV constraint, so no value dependency)", indent=1)
                self.excel[f"{e}:achieved_ltv"] = self._formula(sheet, row, 2, f'="{UNAVAILABLE}"', "calc", "@")
                row += 1
            if event.min_dscr is not None:
                line(
                    f"{e}:achieved_dscr",
                    "Achieved DSCR  (forward NOI / (continuing senior service + first-year service))",
                    f"={self.excel[f'{e}:noi']}/({self.excel[f'{e}:dscr_senior']}+{self.excel[f'{e}:first_year_service']})",
                    "calc",
                    number_format=NUM_MULTIPLE_FINE,
                )
            else:
                self._label(sheet, row, "Achieved DSCR  (no DSCR constraint, so no forward-NOI dependency)", indent=1)
                self.excel[f"{e}:achieved_dscr"] = self._formula(sheet, row, 2, f'="{UNAVAILABLE}"', "calc", "@")
                row += 1
            row += 1

    # ------------------------------------------------------------ Common Equity

    def _build_equity(self) -> None:
        sheet = EQUITY
        ws = self.sheets[sheet]
        hold = self.hold
        c0, cH = 2, 2 + hold
        self._layout(sheet, hold + 1)
        self._title(
            sheet,
            "Common Equity",
            "Common Equity after Capital Structure = pre-debt cash - every capital provider's cash - third-party "
            "costs. The refinance cash is shown apart from the recurring cash in its year.",
        )
        row = 3
        self._period_row_header(sheet, row)
        row += 1
        self._section(sheet, row, "Pre-debt cash (frozen Anchor dependency)", cH)
        row += 1
        self._label(sheet, row, "Cash before every capital provider  (the accepted unlevered authority)", indent=1)
        self._units(sheet, row, "$")
        pre = row
        for t in range(0, hold + 1):
            self.excel[f"pre:{t}"] = self._frozen(sheet, row, c0 + t, self.source.pre_debt_cash_flows[t], NUM_CURRENCY)
        row += 2

        provider_rows: list[int] = []
        self._section(sheet, row, "Capital providers (provider sign: funding -, receipts +)", cH)
        row += 1
        for loan_index, loan in enumerate(self.source.continuing_loans, start=1):
            self._subsection(sheet, row, f"{loan.name} (not repaid by a refinance)", cH)
            row += 1
            self._label(sheet, row, "Loan amount at closing", indent=1)
            self._units(sheet, row, "$")
            amount = self._frozen(sheet, row, c0, loan.loan_amount, NUM_CURRENCY).replace(f"'{sheet}'!", "")
            row += 1
            self._label(sheet, row, "Financing fee at closing", indent=1)
            self._units(sheet, row, "$")
            fee = self._frozen(sheet, row, c0, loan.financing_fee, NUM_CURRENCY).replace(f"'{sheet}'!", "")
            row += 1
            self._label(sheet, row, "Annual debt service", indent=1)
            self._units(sheet, row, "$")
            service_row = row
            for t in range(1, hold + 1):
                self._frozen(sheet, row, c0 + t, loan.annual_debt_service[t - 1], NUM_CURRENCY)
            row += 1
            self._label(sheet, row, "Balance repaid at the sale", indent=1)
            self._units(sheet, row, "$")
            balance = self._frozen(sheet, row, cH, loan.remaining_loan_balance, NUM_CURRENCY).replace(f"'{sheet}'!", "")
            row += 1
            self._label(sheet, row, f"Provider cash flow — {loan.name}", bold=True)
            self._units(sheet, row, "$")
            for t in range(0, hold + 1):
                col = c0 + t
                if t == 0:
                    formula = f"=-{amount}+{fee}"
                elif t < hold:
                    formula = f"={_cell(service_row, col)}"
                else:
                    formula = f"={_cell(service_row, col)}+{balance}"
                self._formula(sheet, row, col, formula, "calc", NUM_CURRENCY, bold=True)
            provider_rows.append(row)
            row += 1
        for provider in self.source.other_providers:
            self._label(sheet, row, f"Provider cash flow — {provider.name} (frozen)", indent=1)
            self._units(sheet, row, "$")
            for t in range(0, hold + 1):
                self._frozen(sheet, row, c0 + t, provider.cash_flows[t], NUM_CURRENCY)
            provider_rows.append(row)
            row += 1
        third_rows: list[int] = []
        event_rows: list[int] = []
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            for loan_index, loan in enumerate(event.retiring, start=1):
                self._label(sheet, row, f"Provider cash flow — {loan.name} (repaid by {event.label})", indent=1)
                self._units(sheet, row, "$")
                for t in range(0, hold + 1):
                    self._formula(sheet, row, c0 + t, f"={self.excel[f'{e}:r{loan_index}:provider:{t}']}", "link", NUM_CURRENCY)
                provider_rows.append(row)
                row += 1
            self._label(sheet, row, f"Provider cash flow — {event.replacement.name} (funded by {event.label})", indent=1)
            self._units(sheet, row, "$")
            for t in range(0, hold + 1):
                self._formula(sheet, row, c0 + t, f"={self.excel[f'{e}:rep_provider:{t}']}", "link", NUM_CURRENCY)
            provider_rows.append(row)
            row += 1
        self._label(sheet, row, "Total capital providers", bold=True)
        self._units(sheet, row, "$")
        total_providers = row
        for t in range(0, hold + 1):
            col = c0 + t
            terms = "+".join(_cell(provider_row, col) for provider_row in provider_rows) or "0"
            self._formula(sheet, row, col, f"={terms}", "calc", NUM_CURRENCY, bold=True)
        row += 2

        self._section(sheet, row, "Third-party refinance costs (paid to no capital provider)", cH)
        row += 1
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            self._label(sheet, row, f"Third-party costs — {event.label}", indent=1)
            self._units(sheet, row, "$")
            for t in range(0, hold + 1):
                formula = f"={self.excel[f'{e}:tp']}" if t == event.hold_year else "=0"
                self._formula(sheet, row, c0 + t, formula, "link" if t == event.hold_year else "calc", NUM_CURRENCY)
            third_rows.append(row)
            row += 1
        row += 1

        self._section(sheet, row, "Common Equity after Capital Structure", cH)
        row += 1
        self._label(sheet, row, "Total Common Equity cash flow", bold=True)
        self._units(sheet, row, "$")
        total = row
        for t in range(0, hold + 1):
            col = c0 + t
            thirds = "".join(f"-{_cell(third_row, col)}" for third_row in third_rows)
            self.excel[f"ce:{t}"] = self._formula(sheet, row, col, f"={_cell(pre, col)}-{_cell(total_providers, col)}{thirds}", "calc", NUM_CURRENCY, bold=True)
        row += 1
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            self._label(sheet, row, f"Refinance event cash — {event.label}", indent=1)
            self._units(sheet, row, "$")
            for t in range(0, hold + 1):
                formula = f"={self.excel[f'{e}:net']}" if t == event.hold_year else "=0"
                self._formula(sheet, row, c0 + t, formula, "link" if t == event.hold_year else "calc", NUM_CURRENCY)
            event_rows.append(row)
            row += 1
        self._label(sheet, row, "Refinance event cash", bold=True)
        self._units(sheet, row, "$")
        event_total = row
        for t in range(0, hold + 1):
            col = c0 + t
            self.excel[f"event:{t}"] = self._formula(sheet, row, col, "=" + "+".join(_cell(event_row, col) for event_row in event_rows), "calc", NUM_CURRENCY, bold=True)
        row += 1
        self._label(sheet, row, "Recurring Common Equity cash flow  (total - refinance event cash)", bold=True)
        self._units(sheet, row, "$")
        for t in range(0, hold + 1):
            col = c0 + t
            self.excel[f"recurring:{t}"] = self._formula(sheet, row, col, f"={_cell(total, col)}-{_cell(event_total, col)}", "calc", NUM_CURRENCY, bold=True)
        row += 2

        self._section(sheet, row, "Returns — primary: Common Equity after Capital Structure", cH)
        row += 1
        cf = f"{_abs(total, c0)}:{_abs(total, cH)}"
        returns = (
            ("invested", "Total equity invested  (sum of negative periods)", "$", f'=-SUMIF({cf},"<0")', NUM_CURRENCY),
            ("returned", "Total cash returned  (sum of positive periods)", "$", f'=SUMIF({cf},">0")', NUM_CURRENCY),
        )
        refs: dict[str, str] = {}
        for key, label, units, formula, number_format in returns:
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            refs[key] = self._formula(sheet, row, 2, formula, "calc", number_format).replace(f"'{sheet}'!", "")
            self.excel[f"ce_{key}"] = _xref(sheet, row, 2)
            row += 1
        self._label(sheet, row, "Total profit", bold=True)
        self._units(sheet, row, "$")
        self.excel["ce_profit"] = self._formula(sheet, row, 2, f"={refs['returned']}-{refs['invested']}", "calc", NUM_CURRENCY, bold=True)
        row += 1
        self._label(sheet, row, "Equity multiple  (returned / invested)", bold=True)
        self._units(sheet, row, "x")
        self.excel["ce_multiple"] = self._formula(sheet, row, 2, f'=IF({refs["invested"]}=0,"{UNAVAILABLE}",{refs["returned"]}/{refs["invested"]})', "calc", NUM_MULTIPLE, bold=True)
        row += 1
        hold_ref = self._input("hold")
        row = self._irr_block(sheet, row, total, c0, cH, "ce", "Common Equity IRR", hold=hold_ref)
        row += 1

        self._section(sheet, row, ACQUISITION_REFERENCE_LABEL, cH)
        row += 1
        ws.write_string(
            row, 0,
            "The acquisition loan held to the sale, excluding every later capital event. A reference only, never the "
            "refinance-adjusted return. Frozen from Anchor.",
            self.fmt.note(),
        )
        row += 1
        self._label(sheet, row, "Levered IRR — acquisition financing reference", indent=1)
        self._units(sheet, row, "% per year")
        self.excel["reference_irr"] = self._frozen(sheet, row, 2, self.source.reference_levered_irr, NUM_PERCENT)
        row += 1
        self._label(sheet, row, "Equity multiple — acquisition financing reference", indent=1)
        self._units(sheet, row, "x")
        self.excel["reference_multiple"] = self._frozen(sheet, row, 2, self.source.reference_equity_multiple, NUM_MULTIPLE)
        row += 1
        self._label(sheet, row, "Common Equity IRR less the acquisition-financing reference", indent=1)
        self._units(sheet, row, "% points")
        self.excel["irr_change"] = self._formula(
            sheet, row, 2,
            f'=IF(AND(ISNUMBER({self.excel["ce_irr"]}),ISNUMBER({self.excel["reference_irr"]})),{self.excel["ce_irr"]}-{self.excel["reference_irr"]},"{UNAVAILABLE}")',
            "calc", NUM_PERCENT,
        )
        row += 1
        self._label(sheet, row, "Common Equity multiple less the acquisition-financing reference", indent=1)
        self._units(sheet, row, "x")
        self.excel["multiple_change"] = self._formula(
            sheet, row, 2,
            f'=IF(AND(ISNUMBER({self.excel["ce_multiple"]}),ISNUMBER({self.excel["reference_multiple"]})),{self.excel["ce_multiple"]}-{self.excel["reference_multiple"]},"{UNAVAILABLE}")',
            "calc", NUM_MULTIPLE,
        )
        ws.freeze_panes(4, 2)

    # ---------------------------------------------------------------- Partners

    def _build_partners(self) -> None:
        sheet = PARTNERS
        ws = self.sheets[sheet]
        hold = self.hold
        c0, cH = 2, 2 + hold
        self._layout(sheet, hold + 1)
        self._title(
            sheet,
            "Partners",
            "Each partner's contributions and distributions are the accepted P7.9 waterfall's, frozen. Their net cash "
            "must sum to Common Equity in every year, and each partner's return is recomputed here.",
        )
        row = 3
        self._period_row_header(sheet, row)
        row += 1
        net_rows: list[int] = []
        hold_ref = self._input("hold")
        for index, partner in enumerate(self.source.partners or (), start=1):
            p = f"p{index}"
            self._section(sheet, row, partner.name, cH)
            row += 1
            self._label(sheet, row, "Contributions (frozen)", indent=1)
            self._units(sheet, row, "$")
            contributions = row
            for t in range(0, hold + 1):
                self._frozen(sheet, row, c0 + t, partner.contributions[t], NUM_CURRENCY)
            row += 1
            self._label(sheet, row, "Distributions (frozen)", indent=1)
            self._units(sheet, row, "$")
            distributions = row
            for t in range(0, hold + 1):
                self._frozen(sheet, row, c0 + t, partner.distributions[t], NUM_CURRENCY)
            row += 1
            self._label(sheet, row, "Net cash flow  (distributions - contributions)", bold=True)
            self._units(sheet, row, "$")
            net = row
            for t in range(0, hold + 1):
                col = c0 + t
                self.excel[f"{p}:net:{t}"] = self._formula(sheet, row, col, f"={_cell(distributions, col)}-{_cell(contributions, col)}", "calc", NUM_CURRENCY, bold=True)
            net_rows.append(net)
            row += 1
            self._label(sheet, row, "Multiple  (total distributions / total contributions)", bold=True)
            self._units(sheet, row, "x")
            contributed = f"SUM({_abs(contributions, c0)}:{_abs(contributions, cH)})"
            distributed = f"SUM({_abs(distributions, c0)}:{_abs(distributions, cH)})"
            self.excel[f"{p}:moic"] = self._formula(sheet, row, 2, f'=IF({contributed}=0,"{UNAVAILABLE}",{distributed}/{contributed})', "calc", NUM_MULTIPLE, bold=True)
            row += 1
            row = self._irr_block(sheet, row, net, c0, cH, p, f"{partner.name} IRR", hold=hold_ref)
            row += 1
        self._section(sheet, row, "Conservation: every partner's net cash equals Common Equity", cH)
        row += 1
        self._label(sheet, row, "Sum of partner net cash flows", bold=True)
        self._units(sheet, row, "$")
        for t in range(0, hold + 1):
            col = c0 + t
            self.excel[f"partners_sum:{t}"] = self._formula(sheet, row, col, "=" + "+".join(_cell(net_row, col) for net_row in net_rows), "calc", NUM_CURRENCY, bold=True)
        row += 1
        self._label(sheet, row, "Common Equity cash flow", indent=1)
        self._units(sheet, row, "$")
        for t in range(0, hold + 1):
            self._formula(sheet, row, c0 + t, f"={self.excel[f'ce:{t}']}", "link", NUM_CURRENCY)
        ws.freeze_panes(4, 2)

    # ---------------------------------------------------------- Anchor Results

    def _build_anchor_results(self) -> None:
        sheet = ANCHOR
        ws = self.sheets[sheet]
        hold = self.hold
        self._layout(sheet, max(hold + 1, 3))
        self._title(
            sheet,
            "Anchor Results",
            "Values produced by Anchor's deterministic engine for this analysis. They are constants, not Excel "
            "formulas, and never change with Working Inputs.",
        )
        row = 3
        a = self.anchor
        src = self.source

        def value(key: str, label: str, number: float | str | None, number_format: str) -> None:
            nonlocal row
            self._label(sheet, row, label, indent=1)
            a[key] = self._frozen(sheet, row, 2, number, number_format)
            row += 1

        def series(key: str, label: str, numbers: tuple[float, ...], number_format: str = NUM_CURRENCY) -> None:
            nonlocal row
            self._label(sheet, row, label, indent=1)
            for t, number in enumerate(numbers):
                a[f"{key}:{t}"] = self._frozen(sheet, row, 2 + t, number, number_format)
            row += 1

        self._period_row_header(sheet, row)
        row += 1
        for index, event in enumerate(src.events, start=1):
            e = f"e{index}"
            self._section(sheet, row, event.label, 2 + hold)
            row += 1
            for loan_index, loan in enumerate(event.retiring, start=1):
                r = f"{e}:r{loan_index}"
                value(f"{r}:payment_at_m", f"{loan.name} — scheduled payment in the refinance month", loan.scheduled_payment_at_m, NUM_CURRENCY_CENTS)
                value(f"{r}:payoff", f"{loan.name} — payoff", loan.payoff, NUM_CURRENCY_CENTS)
                value(f"{r}:xfees", f"{loan.name} — retiring-lender fees", loan.retiring_lender_fees, NUM_CURRENCY_CENTS)
                series(f"{r}:provider", f"{loan.name} — provider cash flow", loan.provider_cash_flows)
            for kind in ("fixed_cap", "max_ltv", "min_dscr"):
                if kind in event.capacities:
                    value(f"{e}:cap:{kind}", f"{_CONSTRAINT_LABELS[kind]} capacity", event.capacities[kind], NUM_CURRENCY_CENTS)
            if event.service_per_dollar is not None:
                value(f"{e}:per_dollar", "First-year service per $1 of loan", event.service_per_dollar, NUM_PERCENT_FINE)
            value(f"{e}:gross", "Gross proceeds", event.gross_proceeds, NUM_CURRENCY_CENTS)
            for kind in ("fixed_cap", "max_ltv", "min_dscr"):
                if kind in event.capacities:
                    value(f"{e}:binds:{kind}", f"{_CONSTRAINT_LABELS[kind]} binds", 1 if kind in event.binding else 0, NUM_FLAG)
            value(f"{e}:binding_text", "Binding constraint(s)", ", ".join(_CONSTRAINT_LABELS[kind] for kind in event.binding), "@")
            value(f"{e}:tie", "Tie", "Yes" if event.tie else "No", "@")
            value(f"{e}:payoffs", "Total payoffs", event.payoffs_total, NUM_CURRENCY_CENTS)
            value(f"{e}:fr", "Replacement-lender fees", event.replacement_lender_fees, NUM_CURRENCY_CENTS)
            value(f"{e}:fx", "Retiring-lender fees", event.retiring_lender_fees, NUM_CURRENCY_CENTS)
            value(f"{e}:tp", "Third-party costs", event.third_party_costs_total, NUM_CURRENCY_CENTS)
            value(f"{e}:net", "Net refinance cash to Common Equity", event.net_event_cash, NUM_CURRENCY_CENTS)
            value(f"{e}:direction", "Direction", _DIRECTION_TEXT[event.direction], "@")
            value(f"{e}:first_year_service", "Replacement first-year service", event.replacement.first_year_service, NUM_CURRENCY_CENTS)
            value(f"{e}:achieved_ltv", "Achieved LTV", event.achieved_ltv, NUM_PERCENT_FINE)
            value(f"{e}:achieved_dscr", "Achieved DSCR", event.achieved_dscr, NUM_MULTIPLE_FINE)
            series(f"{e}:rep_provider", f"{event.replacement.name} — provider cash flow", event.replacement.provider_cash_flows)
            row += 1
        self._section(sheet, row, "Common Equity after Capital Structure", 2 + hold)
        row += 1
        series("ce", "Total Common Equity cash flow", src.common_cash_flows)
        series("recurring", "Recurring Common Equity cash flow", src.recurring_cash_flows)
        series("event", "Refinance event cash", src.event_cash_flows)
        value("ce_invested", "Total equity invested", src.total_equity_invested, NUM_CURRENCY_CENTS)
        value("ce_returned", "Total cash returned", src.total_cash_returned, NUM_CURRENCY_CENTS)
        value("ce_profit", "Total profit", src.total_profit, NUM_CURRENCY_CENTS)
        value("ce_multiple", "Equity multiple", src.equity_multiple, NUM_MULTIPLE_FINE)
        value("ce_irr_status", "Common Equity IRR availability", IRR_STATUS_TEXT[src.common_irr_status], "@")
        value("ce_irr", "Common Equity IRR", src.common_irr, NUM_PERCENT_FINE)
        if src.partners is not None:
            row += 1
            self._section(sheet, row, "Partners", 2 + hold)
            row += 1
            for index, partner in enumerate(src.partners, start=1):
                p = f"p{index}"
                series(f"{p}:net", f"{partner.name} — net cash flow", partner.net_cash_flows)
                value(f"{p}:moic", f"{partner.name} — multiple", partner.moic, NUM_MULTIPLE_FINE)
                value(f"{p}_irr_status", f"{partner.name} — IRR availability", IRR_STATUS_TEXT[partner.irr_status], "@")
                value(f"{p}_irr", f"{partner.name} — IRR", partner.irr, NUM_PERCENT_FINE)
        row += 1
        self._section(sheet, row, "Record of the exported inputs", 2 + hold)
        row += 1
        self.record_first_row = row
        for key, number in self._records:
            self._label(sheet, row, key, indent=1)
            self._frozen(sheet, row, 2, number, NUM_CURRENCY_CENTS)
            row += 1
        self.record_last_row = row - 1
        ws.freeze_panes(4, 2)

    # ------------------------------------------------------------------ Checks

    def _check_groups(self) -> list[tuple[str, list[_Check]]]:
        x, a = self.excel, self.anchor

        def check(metric: str, key: str, kind: str, number_format: str, *, anchor_key: str | None = None) -> _Check:
            return _Check(
                metric=metric,
                anchor=a[anchor_key or key],
                excel=x[key],
                location=x[key].replace("$", ""),
                kind=kind,
                number_format=number_format,
                key=key,
            )

        groups: list[tuple[str, list[_Check]]] = []
        for index, event in enumerate(self.source.events, start=1):
            e = f"e{index}"
            debt: list[_Check] = []
            for loan_index, loan in enumerate(event.retiring, start=1):
                r = f"{e}:r{loan_index}"
                debt.append(check(f"{loan.name}: scheduled payment in the refinance month", f"{r}:payment_at_m", "currency", NUM_CURRENCY_CENTS))
                debt.append(check(f"{loan.name}: payoff", f"{r}:payoff", "currency", NUM_CURRENCY_CENTS))
                debt.append(check(f"{loan.name}: retiring-lender fees", f"{r}:xfees", "currency", NUM_CURRENCY_CENTS))
                debt.extend(
                    check(f"{loan.name}: provider cash flow, Year {t}", f"{r}:provider:{t}", "currency", NUM_CURRENCY_CENTS)
                    for t in range(0, self.hold + 1)
                )
            groups.append((f"{event.label}: retiring debt", debt))
            sizing = [
                check(f"{_CONSTRAINT_LABELS[kind]} capacity", f"{e}:cap:{kind}", "currency", NUM_CURRENCY_CENTS)
                for kind in ("fixed_cap", "max_ltv", "min_dscr")
                if kind in event.capacities
            ]
            if event.service_per_dollar is not None:
                sizing.append(check("First-year service per $1 of loan", f"{e}:per_dollar", "ratio", NUM_PERCENT_FINE))
            sizing.append(check("Gross proceeds", f"{e}:gross", "currency", NUM_CURRENCY_CENTS))
            sizing.extend(
                check(f"{_CONSTRAINT_LABELS[kind]} binds", f"{e}:binds:{kind}", "exact", NUM_FLAG)
                for kind in ("fixed_cap", "max_ltv", "min_dscr")
                if kind in event.capacities
            )
            sizing.append(check("Binding constraint(s)", f"{e}:binding_text", "exact", "@"))
            sizing.append(check("Tie", f"{e}:tie", "exact", "@"))
            groups.append((f"{event.label}: sizing", sizing))
            bridge = [
                check("Total payoffs", f"{e}:payoffs", "currency", NUM_CURRENCY_CENTS),
                check("Replacement-lender fees", f"{e}:fr", "currency", NUM_CURRENCY_CENTS),
                check("Retiring-lender fees", f"{e}:fx", "currency", NUM_CURRENCY_CENTS),
                check("Third-party costs", f"{e}:tp", "currency", NUM_CURRENCY_CENTS),
                check("Net refinance cash to Common Equity", f"{e}:net", "currency", NUM_CURRENCY_CENTS),
                check("Direction", f"{e}:direction", "exact", "@"),
                check("Achieved LTV", f"{e}:achieved_ltv", "ratio", NUM_PERCENT_FINE),
                check("Achieved DSCR", f"{e}:achieved_dscr", "ratio", NUM_MULTIPLE_FINE),
            ]
            groups.append((f"{event.label}: bridge", bridge))
            replacement = [
                check("Replacement first-year service", f"{e}:first_year_service", "currency", NUM_CURRENCY_CENTS),
                *(
                    check(f"{event.replacement.name}: provider cash flow, Year {t}", f"{e}:rep_provider:{t}", "currency", NUM_CURRENCY_CENTS)
                    for t in range(0, self.hold + 1)
                ),
            ]
            groups.append((f"{event.label}: replacement loan", replacement))
        equity = [
            *(check(f"Total Common Equity cash flow, Year {t}", f"ce:{t}", "currency", NUM_CURRENCY_CENTS) for t in range(0, self.hold + 1)),
            *(check(f"Refinance event cash, Year {t}", f"event:{t}", "currency", NUM_CURRENCY_CENTS) for t in range(0, self.hold + 1)),
            *(check(f"Recurring Common Equity cash flow, Year {t}", f"recurring:{t}", "currency", NUM_CURRENCY_CENTS) for t in range(0, self.hold + 1)),
            check("Total equity invested", "ce_invested", "currency", NUM_CURRENCY_CENTS),
            check("Total cash returned", "ce_returned", "currency", NUM_CURRENCY_CENTS),
            check("Total profit", "ce_profit", "currency", NUM_CURRENCY_CENTS),
            check("Equity multiple", "ce_multiple", "ratio", NUM_MULTIPLE_FINE),
            check("Common Equity IRR availability", "ce_irr_status", "exact", "@"),
            check("Common Equity IRR", "ce_irr", "irr", NUM_PERCENT_FINE),
        ]
        groups.append(("Common Equity after Capital Structure", equity))
        if self.source.partners is not None:
            partners: list[_Check] = []
            for index, partner in enumerate(self.source.partners, start=1):
                p = f"p{index}"
                partners.extend(
                    check(f"{partner.name}: net cash flow, Year {t}", f"{p}:net:{t}", "currency", NUM_CURRENCY_CENTS)
                    for t in range(0, self.hold + 1)
                )
                partners.append(check(f"{partner.name}: multiple", f"{p}:moic", "ratio", NUM_MULTIPLE_FINE))
                partners.append(check(f"{partner.name}: IRR availability", f"{p}_irr_status", "exact", "@"))
                partners.append(check(f"{partner.name}: IRR", f"{p}_irr", "irr", NUM_PERCENT_FINE))
            partners.extend(
                _Check(
                    metric=f"Partners' net cash equals Common Equity, Year {t}",
                    anchor=x[f"ce:{t}"],
                    excel=x[f"partners_sum:{t}"],
                    location=x[f"partners_sum:{t}"].replace("$", ""),
                    kind="currency",
                    number_format=NUM_CURRENCY_CENTS,
                    guard_anchor=True,
                )
                for t in range(0, self.hold + 1)
            )
            groups.append(("Partners", partners))
        return groups

    def _build_checks(self) -> None:
        sheet = CHECKS
        ws = self.sheets[sheet]
        self._checks_layout()
        self._title(
            sheet,
            "Checks",
            "Each row compares a frozen Anchor result with the Excel model. A missing, uncalculated or erroring Excel "
            "value never passes.",
        )
        last_col = 7
        row = 3
        self._section(sheet, row, "Workbook status", last_col)
        row += 1
        names = ("recalculated", "differing", "modified", "original", "available", "total", "passed", "open", "first", "first_location", "explanation")
        status_rows = {name: row + offset for offset, name in enumerate(names)}
        for name, label in (
            ("recalculated", "Excel formulas recalculated"),
            ("differing", "Working inputs that differ from the export"),
            ("modified", "Workbook modified since export"),
            ("original", "Original inputs unchanged"),
            ("available", "Anchor reconciliation available"),
            ("total", "Reconciliation checks"),
            ("passed", "Passed"),
            ("open", "Not passed"),
            ("first", "First check not passed"),
            ("first_location", "Its location"),
            ("explanation", "What the comparison means"),
        ):
            self._label(sheet, status_rows[name], label)
        recalculated = self._status_formula(sheet, status_rows["recalculated"], 1, '="Yes"')
        originals = _range(INPUTS, self.inputs_first_row, 2, self.inputs_last_row, 2)
        workings = _range(INPUTS, self.inputs_first_row, 3, self.inputs_last_row, 3)
        differing = self._formula(sheet, status_rows["differing"], 1, f"=SUMPRODUCT(--({workings}<>{originals}))", "link", NUM_INTEGER)
        modified = self._status_formula(sheet, status_rows["modified"], 1, f'=IF({differing}>0,"Yes","No")')
        record = _range(ANCHOR, self.record_first_row, 2, self.record_last_row, 2)
        original_values = self._original_values_range()
        original_ok = self._status_formula(
            sheet, status_rows["original"], 1, f'=IF(SUMPRODUCT(--({original_values}<>{record}))=0,"Yes","No")', "link"
        )
        available = self._status_formula(
            sheet, status_rows["available"], 1,
            f'=IF({recalculated}<>"Yes","No: formulas not recalculated",IF({modified}="Yes","No: Working Inputs modified",'
            f'IF({original_ok}<>"Yes","No: Original Export values altered","Yes")))',
        )
        row = status_rows["explanation"] + 2
        self._section(sheet, row, "Reconciliation", last_col)
        row += 1
        headers = ("Metric", "Anchor Result", "Excel Result", "Difference", "Tolerance", "Status", "Excel location", "Open")
        self._headers(sheet, row, [(col, text, "left" if col in (0, 5, 6) else "right") for col, text in enumerate(headers)])
        header_row = row
        row += 1
        first_check_row = row
        for group, checks in self._check_groups():
            self._subsection(sheet, row, group, last_col)
            row += 1
            for check_row in checks:
                self._write_check(row, check_row, modified)
                row += 1
        last_check_row = row - 1
        ws.write_string(
            row + 1, 0,
            "Refinance inputs and accepted dependencies are frozen; every refinance calculation above is reproduced by "
            "a live Excel formula. The acquisition-financing reference is frozen and not reconciled here.",
            self.fmt.note(),
        )
        statuses = _range(None, first_check_row, 5, last_check_row, 5)
        flags = _range(None, first_check_row, 7, last_check_row, 7)
        metrics = _range(None, first_check_row, 0, last_check_row, 0)
        total = self._formula(sheet, status_rows["total"], 1, f'=COUNTIF({flags},">=0")', "calc", NUM_INTEGER)
        self._formula(sheet, status_rows["passed"], 1, f"={total}-SUM({flags})", "calc", NUM_INTEGER)
        open_count = self._formula(sheet, status_rows["open"], 1, f"=SUM({flags})", "calc", NUM_INTEGER)
        self._status_formula(sheet, status_rows["first"], 1, f'=IF({open_count}=0,"None",INDEX({metrics},MATCH(1,{flags},0)))')
        self._status_formula(sheet, status_rows["first_location"], 1, f'=IF({open_count}=0,"None","Checks!F"&ROW(INDEX({statuses},MATCH(1,{flags},0))))')
        self._status_formula(
            sheet, status_rows["explanation"], 1,
            f'=IF({modified}="Yes","MODIFIED MODEL: Working Inputs differ from the exported inputs, so Excel results '
            f'describe a modified case and are not a like-for-like reconciliation with Anchor. The frozen Anchor '
            f'Results are unchanged.","Working Inputs equal the exported inputs: every row below is a like-for-like '
            f'reconciliation with Anchor.")',
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
        }
        fail_format = self.fmt.get(bold=True, font_color="#C00000")
        amber_format = self.fmt.get(font_color="#9C5700")
        pass_format = self.fmt.get(font_color="#006100")
        for text, cell_format in (
            (FAIL, fail_format),
            (EXCEL_ERROR, fail_format),
            (NOT_LIKE_FOR_LIKE, amber_format),
            (NOT_RECALCULATED, amber_format),
            (PASS, pass_format),
        ):
            ws.conditional_format(first_check_row, 5, last_check_row, 5, {"type": "text", "criteria": "begins with", "value": text, "format": cell_format})
        ws.freeze_panes(header_row + 1, 1)

    def _original_values_range(self) -> str:
        """The Original Export values, one per input, in input order -- the same
        order the Anchor Results record keeps them in. Inputs sit on rows
        separated by section bars, so the range is rebuilt from the recorded
        cells through a helper column on Anchor Results."""

        sheet = ANCHOR
        for offset, (key, _) in enumerate(self._records):
            self._formula(sheet, self.record_first_row + offset, 3, f"={self.excel[f'original:{key}']}", "link", NUM_CURRENCY_CENTS)
        return _range(ANCHOR, self.record_first_row, 3, self.record_last_row, 3)

    # ----------------------------------------------------------------- Summary

    def _build_summary(self) -> None:
        sheet = SUMMARY
        ws = self.sheets[sheet]
        src = self.source
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, 52)
        self._set_column(sheet, 1, 2, 20)
        self._set_column(sheet, 3, 3, 40)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)
        ws.write_string(0, 0, WORKBOOK_TITLE, self.fmt.title())
        ws.set_row(0, 22)
        ws.write_string(1, 0, src.investment_name, self.fmt.get(bold=True, font_size=12))
        ws.write_string(
            2, 0,
            "An independent formula audit of Anchor's refinance: what sized the new loan, what it repaid, what it "
            "cost, and what it returned to Common Equity.",
            self.fmt.note(),
        )
        row = 4
        self._section(sheet, row, "Analysis", 3)
        row += 1
        for label, value in (
            ("Investment", src.investment_name),
            ("Strategy", src.strategy_label),
            ("Scenario", src.scenario_label),
            ("Hold period", f"{src.hold_period} years"),
            ("Status at export", "Saved analysis, current for the saved Capital Structure"),
        ):
            self._label(sheet, row, label)
            ws.write_string(row, 1, value, self.fmt.text())
            row += 1
        self._label(sheet, row, "Model state")
        _write_formula(ws, row, 1, f"={self.check_summary['modified']}", self.fmt.status("link"), NOT_RECALCULATED)
        ws.write_string(row, 2, "(Yes = Working Inputs modified since export)", self.fmt.units())
        row += 2

        def headed(title: str) -> None:
            nonlocal row
            self._section(sheet, row, title, 3)
            row += 1
            self._headers(sheet, row, [(col, text, "left" if col in (0, 3) else "right") for col, text in enumerate(("Metric", "Excel model", "Anchor (exported)", "Check"))])
            row += 1

        def metric(label: str, key: str, number_format: str) -> None:
            nonlocal row
            self._label(sheet, row, label, indent=1)
            if number_format == "@":
                _write_formula(ws, row, 1, f"={self.excel[key]}", self.fmt.status("link"), NOT_RECALCULATED)
                _write_formula(ws, row, 2, f"={self.anchor[key]}", self.fmt.status("link"), "")
            else:
                self._formula(sheet, row, 1, f"={self.excel[key]}", "link", number_format)
                self._formula(sheet, row, 2, f"={self.anchor[key]}", "link", number_format)
            _write_formula(ws, row, 3, f"={self.status[key]}", self.fmt.status("link"), NOT_RECALCULATED)
            row += 1

        headed("Primary return — Common Equity after Capital Structure")
        metric("Common Equity IRR", "ce_irr", NUM_PERCENT)
        metric("Equity multiple", "ce_multiple", NUM_MULTIPLE)
        metric("Total equity invested", "ce_invested", NUM_CURRENCY)
        metric("Total cash returned", "ce_returned", NUM_CURRENCY)
        metric("Total profit", "ce_profit", NUM_CURRENCY)
        row += 1
        for index, event in enumerate(src.events, start=1):
            e = f"e{index}"
            headed(f"{event.label} — {event.scope_name}, end of Year {event.hold_year}")
            direction = _DIRECTION_TEXT[event.direction]
            metric(
                "How much cash was returned to Common Equity? (net refinance cash)"
                if direction != "Contribution"
                else "How much must Common Equity contribute? (net refinance cash, negative)",
                f"{e}:net",
                NUM_CURRENCY,
            )
            metric("Direction", f"{e}:direction", "@")
            metric("What sized the new loan? (gross proceeds)", f"{e}:gross", NUM_CURRENCY)
            metric("Which constraint bound?", f"{e}:binding_text", "@")
            metric("Tie", f"{e}:tie", "@")
            metric("What debt was repaid? (total payoffs)", f"{e}:payoffs", NUM_CURRENCY)
            metric("What did it cost? Replacement-lender fees", f"{e}:fr", NUM_CURRENCY)
            metric("What did it cost? Retiring-lender fees", f"{e}:fx", NUM_CURRENCY)
            metric("What did it cost? Third-party costs", f"{e}:tp", NUM_CURRENCY)
            row += 1
        if src.partners is not None:
            headed("Primary investor return — Partners")
            for index, partner in enumerate(src.partners, start=1):
                metric(f"{partner.name} IRR", f"p{index}_irr", NUM_PERCENT)
                metric(f"{partner.name} multiple", f"p{index}:moic", NUM_MULTIPLE)
            row += 1

        self._section(sheet, row, "How the refinance changed the equity return", 3)
        row += 1
        ws.write_string(row, 0, f"Against the {ACQUISITION_REFERENCE_LABEL.lower()}: a frozen reference, never a headline.", self.fmt.note())
        row += 1
        for label, key, number_format in (
            ("Common Equity IRR", "ce_irr", NUM_PERCENT),
            (f"Levered IRR — {ACQUISITION_REFERENCE_LABEL}", "reference_irr", NUM_PERCENT),
            ("Change in IRR", "irr_change", NUM_PERCENT),
            ("Common Equity multiple", "ce_multiple", NUM_MULTIPLE),
            (f"Equity multiple — {ACQUISITION_REFERENCE_LABEL}", "reference_multiple", NUM_MULTIPLE),
            ("Change in multiple", "multiple_change", NUM_MULTIPLE),
        ):
            ws.write_string(row, 0, label, self.fmt.label(indent=1, wrap=True))
            if len(label) > 48:
                ws.set_row(row, 27)
            self._formula(sheet, row, 1, f"={self.excel[key]}", "link", number_format)
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
            if label in ("Reconciliation checks", "Passed", "Not passed"):
                self._formula(sheet, row, 1, f"={ref}", "link", NUM_INTEGER)
            else:
                _write_formula(ws, row, 1, f"={ref}", self.fmt.status("link"), NOT_RECALCULATED)
            row += 1
        ws.write_string(
            row, 0,
            "If these cells read 'Not recalculated', the file was opened without calculation. Open it in Excel (or "
            "press Ctrl+Alt+F9) to recalculate every formula.",
            self.fmt.note(),
        )
        row += 2
        self._section(sheet, row, "Formatting legend", 3)
        row += 1
        for label, role in (
            ("Editable working input", "input"),
            ("Calculation on the same sheet", "calc"),
            ("Value brought from another sheet", "link"),
            ("Frozen Anchor result or dependency", "frozen"),
        ):
            self._label(sheet, row, label, indent=1)
            sample_format = (
                self.fmt.get(num_format=NUM_CURRENCY, align="right", font_color=INPUT_BLUE, bg_color=INPUT_FILL)
                if role == "input"
                else self.fmt.value(role, NUM_CURRENCY)
            )
            ws.write_number(row, 1, 1000, sample_format)
            row += 1
        self._label(sheet, row, "Negative amounts, zero and unavailable", indent=1)
        ws.write_number(row, 1, -1000, self.fmt.value("calc", NUM_CURRENCY))
        ws.write_number(row, 2, 0, self.fmt.value("calc", NUM_CURRENCY))
        ws.write_string(row, 3, UNAVAILABLE, self.fmt.get(align="left"))

    # ---------------------------------------------------------- Audit Metadata

    def _build_audit(self) -> None:
        sheet = AUDIT
        ws = self.sheets[sheet]
        src = self.source
        generated = src.generated_at.astimezone(timezone.utc)
        self._audit_layout()
        self._title(sheet, "Audit Metadata", "What this workbook was built from, and under which conventions.")
        row = 3
        self._section(sheet, row, "Provenance", 1)
        row += 1
        for label, value in (("Investment", src.investment_name), ("Strategy", src.strategy_label), ("Scenario", src.scenario_label)):
            self._audit_row(row, label, value, wrap_value=False)
            row += 1
        self._label(sheet, row, "Generated (UTC)")
        ws.write_datetime(row, 1, generated.replace(tzinfo=None), self.fmt.get(num_format=NUM_DATETIME, align="left"))
        row += 1
        for label, value in (
            ("Generated (ISO 8601, with time zone)", generated.isoformat()),
            ("Anchor version", src.anchor_version),
            ("Source commit (checkout HEAD; uncommitted changes are not detected)", src.source_commit or "Not available"),
            ("Structured analysis fingerprint", src.structured_source_fingerprint),
            ("Workbook contract", CONTRACT_VERSION),
            (
                "Source",
                "The saved Investment's structured analysis, recomputed at export and verified against the "
                "fingerprint of the analysis the analyst ran. Every refinance executed.",
            ),
        ):
            self._audit_row(row, label, value, wrap_value=True)
            row += 1
        row += 1
        self._section(sheet, row, "Conventions", 1)
        row += 1
        for label, value in (
            ("Timing", "A refinance occurs at the end of a hold year (model month 12y). The retiring loans make their scheduled payment for that month, are then repaid, and the replacement funds; its first payment is the next month."),
            ("Sizing", "Gross proceeds are the least enabled capacity. Fixed cap: the amount. Maximum LTV: max LTV x the contemporaneous value, less continuing senior debt. Minimum DSCR: (forward NOI / min DSCR, less continuing senior service) / first-year service per dollar, on the replacement's actual first-year service, interest-only months included. Every constraint within 1e-9 x max(1, gross) of the minimum binds."),
            ("Bridge", "Net refinance cash = gross proceeds - payoffs - replacement-lender fees - retiring-lender fees - third-party costs, all at the refinance. Positive is a distribution to Common Equity; negative an explicit contribution, never a Funding Requirement."),
            ("Common Equity", "Pre-debt cash less every capital provider's annual cash (provider sign) less third-party costs. The refinance cash is its own line; recurring = total - refinance cash."),
            ("Dependencies", "Frozen, not recomputed: the contemporaneous value an LTV constraint consumed, the forward NOI a DSCR constraint consumed, the continuing senior debt, the pre-debt cash authority, the provider cash of positions no refinance touches, and each partner's waterfall allocation."),
            ("Acquisition financing", f"{ACQUISITION_REFERENCE_LABEL}. The Project levered figures hold the acquisition loan to the sale; they are a frozen reference only."),
            ("IRR", "Annual periodic IRR over equal intervals (Excel IRR, not XIRR), evaluated only when the series starts negative, contains a positive, and changes sign exactly once."),
            ("Rounding", "No value is rounded; number formats affect display only."),
            ("Calculation mode", "Automatic, with a full recalculation requested when the file opens."),
            ("Tolerances", f"Currency: the larger of {CURRENCY_ABSOLUTE_TOLERANCE:g} and {CURRENCY_RELATIVE_TOLERANCE:g} x |Anchor value|. Ratios: {RATIO_TOLERANCE:g}. IRR: {IRR_TOLERANCE:g}. Flags, text and availability: exact."),
            ("Authority", "An audit artifact. No Anchor result is read from this workbook, and editing it changes nothing in Anchor."),
        ):
            self._audit_row(row, label, value, wrap_value=True)
            row += 1


def build_refinance_audit_workbook(source: RefinanceAuditSource) -> bytes:
    """The complete ``.xlsx`` for one refinance-bearing saved Analysis Variant."""

    return _RefinanceAuditWorkbook(source).build()


__all__ = ["CONTRACT_VERSION", "WORKBOOK_TITLE", "build_refinance_audit_workbook"]
