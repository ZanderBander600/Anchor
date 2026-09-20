"""Excel Export 1 -- the Quick Underwrite formula-audit workbook.

One workbook, eight sheets, in this order::

    Summary, Inputs, Operating Projection, Debt Schedule, Equity Cash Flow,
    Anchor Results, Checks, Audit Metadata

The model sheets rebuild Anchor's Quick Underwrite calculation with visible
Excel formulas driven only by the ``Working Input`` column of ``Inputs``.
``Anchor Results`` holds the values Anchor saved, as constants. ``Checks``
compares the two row by row. The formulas are an *independent
representation* of the ratified Quick contract
(``docs/financial_conventions.md``, ``docs/underwriting_v2_financial_conventions.md``
and ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md``); they are never
read back by Anchor and never feed an application result.

Every formula cell is written with a *pessimistic* cached value -- blank, or
"Not recalculated" for a status -- never a number copied from Anchor. A viewer
that does not calculate therefore shows an honestly unfinished workbook, and
only a real recalculation can make a check pass. ``fullCalcOnLoad`` asks Excel
to recalculate everything when the file is opened.

Quick Underwrite's own part of this is small, and it is all that lives here:
the nine acquisition assumptions, and an NOI schedule projected directly from
Current NOI and NOI growth. Everything from the NOI row downward -- debt,
equity, sale, returns, IRR, reconciliation and presentation -- is shared with
the Detailed export in ``_workbook.py``, because in Anchor it is genuinely the
same model (``docs/detailed_operating_model_v2_1_architecture.md``
"Quick/Detailed Convergence").
"""

from __future__ import annotations

from ._workbook import (
    NOTE_GRAY,
    NUM_CURRENCY,
    NUM_CURRENCY_CENTS,
    NUM_FACTOR,
    NUM_INTEGER,
    NUM_MULTIPLE,
    NUM_PERCENT,
    NUM_PERCENT_FINE,
    OPERATING,
    _abs,
    _AuditWorkbookBase,
    _Check,
    _cell,
    _InputSpec,
)
from .source import (
    EXPORT_CONTRACT_VERSION,
    QuickAuditExportError,
    QuickAuditRefusalCode,
    QuickAuditSource,
)

__all__ = ["build_quick_audit_workbook"]


class _QuickAuditWorkbook(_AuditWorkbookBase):
    """Quick Underwrite's formula-audit workbook."""

    MODE_LABEL = "Quick Underwrite"
    WORKBOOK_TITLE = "Quick Underwrite Audit"
    CONTRACT_VERSION = EXPORT_CONTRACT_VERSION
    SUMMARY_NOTE = (
        "Formula-level audit of a saved Anchor Quick Underwrite analysis. The Excel model "
        "recalculates from the Inputs sheet; Anchor's results are frozen for comparison."
    )
    CHECKS_NOTE = (
        "Quick Underwrite has no revenue, vacancy or operating-expense lines: NOI is its input "
        "and is reconciled directly, year by year."
    )
    NOI_CONVENTION = (
        "Year 1 NOI equals Current NOI; growth applies from Year 2: "
        "NOI(y) = Current NOI x (1 + growth)^(y - 1)."
    )
    SCOPE_NOTE = (
        "Only Quick Underwrite Deals are supported. Detailed Underwrite, Lease-Level, "
        "Investments, Capital Structure, Partnership Waterfalls and Asset Management are "
        "not exported."
    )

    def __init__(self, source: QuickAuditSource) -> None:
        self.inputs = source.inputs
        super().__init__(source, acquisition=source.inputs, results=source.results)

    def _refuse(self, message: str) -> Exception:
        return QuickAuditExportError(QuickAuditRefusalCode.ANALYSIS_INCONSISTENT, message)

    # ----------------------------------------------------------------- Inputs

    def _input_specs(self) -> list[tuple[str, list[_InputSpec]]]:
        i = self.inputs
        positive = {"validate": "decimal", "criteria": ">", "value": 0}
        non_negative = {"validate": "decimal", "criteria": ">=", "value": 0}
        fraction = {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 1}
        above_minus_one = {"validate": "decimal", "criteria": ">", "value": -1}
        return [
            (
                "Acquisition",
                [
                    _InputSpec("purchase_price", "Purchase price", "$", i.purchase_price, NUM_CURRENCY, name="Purchase_Price", validation=positive),
                    _InputSpec("acquisition_cost_pct", "Acquisition costs", "% of purchase price", i.acquisition_cost_pct, NUM_PERCENT, name="Acquisition_Cost_Pct", validation=fraction),
                ],
            ),
            (
                "Operations",
                [
                    _InputSpec("current_noi", "Current NOI (Year 1 NOI)", "$ per year", i.current_noi, NUM_CURRENCY, name="Current_NOI", validation=non_negative),
                    _InputSpec("noi_growth", "NOI growth", "% per year, from Year 2", i.noi_growth, NUM_PERCENT, name="NOI_Growth", validation=above_minus_one),
                    _InputSpec("occupancy", "Occupancy", "% (informational)", i.occupancy, NUM_PERCENT, fixed_note="Informational: not used by the Quick engine"),
                    _InputSpec("annual_capex_reserve", "Annual CapEx reserve", "$ per year, below NOI", i.annual_capex_reserve, NUM_CURRENCY, name="CapEx_Reserve", validation=non_negative),
                ],
            ),
            (
                "Financing",
                [
                    _InputSpec("ltv", "Loan-to-value", "% of purchase price", i.ltv, NUM_PERCENT, name="Loan_To_Value", validation=fraction),
                    _InputSpec("interest_rate", "Interest rate", "% per year, fixed", i.interest_rate, NUM_PERCENT, name="Interest_Rate", validation=non_negative),
                    _InputSpec("amortization", "Amortization", "years", float(i.amortization), NUM_INTEGER, name="Amortization_Years", validation={"validate": "integer", "criteria": ">=", "value": 1}),
                    _InputSpec("io_period", "Interest-only period", "years", float(i.io_period), NUM_INTEGER, name="IO_Period_Years", validation={"validate": "integer", "criteria": ">=", "value": 0}),
                    _InputSpec("financing_fee_pct", "Financing fee", "% of loan amount", i.financing_fee_pct, NUM_PERCENT, name="Financing_Fee_Pct", validation=fraction),
                ],
            ),
            (
                "Exit",
                [
                    _InputSpec("hold_period", "Hold period", "years", float(self.hold), NUM_INTEGER, fixed_note="Fixed at export: sets the period columns", name="Hold_Period"),
                    _InputSpec("exit_cap_rate", "Exit cap rate", "% of Year H+1 NOI", i.exit_cap_rate, NUM_PERCENT, name="Exit_Cap_Rate", validation=positive),
                    _InputSpec("disposition_cost_pct", "Disposition costs", "% of gross sale price", i.disposition_cost_pct, NUM_PERCENT, name="Disposition_Cost_Pct", validation=fraction),
                ],
            ),
            (
                "Business Plan (annual totals Anchor resolved, from the saved analysis)",
                [
                    _InputSpec("closing_project_capital", "Closing project capital", "$ at Year 0", self.results.closing_project_capital, NUM_CURRENCY, name="Closing_Project_Capital", validation=non_negative),
                    _InputSpec("post_hold_project_capital", "Post-hold project capital", "$ (disclosure only)", self.results.post_hold_project_capital, NUM_CURRENCY, fixed_note="Disclosure only: never enters the hold"),
                ],
            ),
        ]

    # ------------------------------------------------------ Operating Projection

    def _build_operating(self) -> None:
        sheet = OPERATING
        ws = self.sheets[sheet]
        hold = self.hold
        first_col = 2
        forward_col = first_col + hold
        last_col = forward_col
        self._base_layout(sheet, hold + 1)
        self._title(
            sheet,
            "Operating Projection",
            "Quick Underwrite projects NOI directly from Current NOI and NOI growth; revenue, "
            "vacancy and operating-expense lines are not Quick inputs and are not modelled.",
        )
        row = 3
        self._section(sheet, row, "Assumptions used (from Inputs)", last_col)
        row += 1
        links = (
            ("current_noi", "Current NOI (Year 1 NOI)", "$ per year", "=Current_NOI", NUM_CURRENCY),
            ("noi_growth", "NOI growth", "% per year", "=NOI_Growth", NUM_PERCENT),
            ("capex", "Annual CapEx reserve", "$ per year", "=CapEx_Reserve", NUM_CURRENCY),
            ("purchase_price", "Purchase price", "$", "=Purchase_Price", NUM_CURRENCY),
        )
        a: dict[str, str] = {}
        for key, label, units, formula, number_format in links:
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            self._formula(sheet, row, 2, formula, "link", number_format)
            a[key] = _abs(row, 2)
            row += 1
        row += 1

        labels = [f"Year {year}" for year in self.years] + [f"Year {hold + 1}"]
        self._period_header(sheet, row, first_col, labels)
        row += 1
        year_row = row
        self._label(sheet, row, "Year number")
        for offset, year in enumerate([*self.years, hold + 1]):
            ws.write_number(row, first_col + offset, year, self.fmt.value("calc", NUM_INTEGER))
        row += 1
        self._label(sheet, row, "Period type")
        for offset in range(hold):
            ws.write_string(row, first_col + offset, "Hold year", self.fmt.get(align="right", font_color=NOTE_GRAY))
        ws.write_string(row, forward_col, "Exit NOI only", self.fmt.get(align="right", font_color=NOTE_GRAY))
        row += 2

        self._section(sheet, row, "Net operating income", last_col)
        row += 1
        factor_row, noi_row, growth_row = row, row + 1, row + 2
        self._label(sheet, factor_row, "NOI growth factor  (1 + growth) ^ (year - 1)", indent=1)
        self._units(sheet, factor_row, "factor")
        self._label(sheet, noi_row, "Net operating income", bold=True)
        self._units(sheet, noi_row, "$")
        self._label(sheet, growth_row, "Change from prior year", indent=1)
        self._units(sheet, growth_row, "%")
        for offset in range(hold + 1):
            col = first_col + offset
            year_ref = _cell(year_row, col, row_abs=True)
            self._formula(sheet, factor_row, col, f"=(1+{a['noi_growth']})^({year_ref}-1)", "calc", NUM_FACTOR)
            ref = self._formula(sheet, noi_row, col, f"={a['current_noi']}*{_cell(factor_row, col)}", "calc", NUM_CURRENCY, bold=True)
            if offset < hold:
                self.excel[f"noi:{offset + 1}"] = ref
            else:
                self.excel["exit_noi"] = ref
            if offset == 0:
                ws.write_string(growth_row, col, "n/a", self.fmt.get(align="right", font_color=NOTE_GRAY))
            else:
                prior, current = _cell(noi_row, col - 1), _cell(noi_row, col)
                self._formula(sheet, growth_row, col, f'=IF({prior}=0,"n/a",{current}/{prior}-1)', "calc", NUM_PERCENT)
        self.noi_row = noi_row
        row = growth_row + 1
        ws.write_string(row, 0, f"Year {hold + 1} NOI is used only to value the sale at the end of Year {hold}; it is not a hold-year cash flow.", self.fmt.note())
        row += 2

        row = self._build_below_noi(sheet, row, first_col, last_col, noi_row, a["capex"])

        self._section(sheet, row, "Valuation metric", last_col)
        row += 1
        self._label(sheet, row, "Going-in cap rate  (Year 1 NOI / purchase price)", indent=1)
        self._units(sheet, row, "%")
        self.excel["going_in_cap_rate"] = self._formula(
            sheet, row, 2, f"={_cell(noi_row, first_col)}/{a['purchase_price']}", "calc", NUM_PERCENT
        )
        ws.freeze_panes(0, 2)

    # ----------------------------------------------------------------- Checks

    def _operations_checks(self) -> list[_Check]:
        x = self.excel
        return [
            *self._yearly("Net operating income", "noi", "noi", "currency", NUM_CURRENCY_CENTS),
            self._check("Exit NOI (Year H+1)", "exit_noi", x["exit_noi"], "currency", NUM_CURRENCY_CENTS),
            *self._yearly("CapEx reserve", "capex", "capex", "currency", NUM_CURRENCY_CENTS, negate=True),
            *self._yearly("Business Plan project capital", "project_capital", "project_capital", "currency", NUM_CURRENCY_CENTS, negate=True),
            *self._yearly("Business Plan owner expenses", "owner_expenses", "owner_expenses", "currency", NUM_CURRENCY_CENTS, negate=True),
            *self._yearly("Property cash flow after CapEx", "property_cf", "property_cf", "currency", NUM_CURRENCY_CENTS),
            *self._yearly("Unlevered owner cash flow", "uocf", "uocf", "currency", NUM_CURRENCY_CENTS),
            self._check("Going-in cap rate", "going_in_cap_rate", x["going_in_cap_rate"], "ratio", NUM_PERCENT_FINE, key="going_in_cap_rate"),
        ]

    # ---------------------------------------------------------------- Summary

    def _summary_metrics(self) -> tuple[tuple[str, str, str, str | None, str], ...]:
        x, a = self.excel, self.anchor
        return (
            ("Purchase price", x["input:purchase_price"], x["original:purchase_price"], None, NUM_CURRENCY),
            ("Year 1 NOI", x["noi:1"], a["noi:1"], "metric:Net operating income, Year 1", NUM_CURRENCY),
            ("Going-in cap rate", x["going_in_cap_rate"], a["going_in_cap_rate"], "going_in_cap_rate", NUM_PERCENT),
            ("Loan amount", x["loan_amount"], a["loan_amount"], "loan_amount", NUM_CURRENCY),
            ("Required equity (initial equity)", x["check_excel:initial_equity"], a["initial_equity"], "initial_equity", NUM_CURRENCY),
            ("Headline DSCR (Year 1)", x["headline_dscr"], a["headline_dscr"], "headline_dscr", NUM_MULTIPLE),
            ("Gross sale price", x["exit_value"], a["exit_value"], "exit_value", NUM_CURRENCY),
            ("Net sale proceeds", x["net_sale_proceeds"], a["net_sale_proceeds"], "net_sale_proceeds", NUM_CURRENCY),
            ("Total equity invested", x["total_equity_invested"], a["total_equity_invested"], "total_equity_invested", NUM_CURRENCY),
            ("Total cash returned", x["total_cash_returned"], a["total_cash_returned"], "total_cash_returned", NUM_CURRENCY),
            ("Total profit", x["total_profit"], a["total_profit"], "total_profit", NUM_CURRENCY),
            ("Equity multiple", x["equity_multiple"], a["equity_multiple"], "equity_multiple", NUM_MULTIPLE),
            ("Levered IRR", x["levered_irr"], a["levered_irr"], "levered_irr", NUM_PERCENT),
            ("Unlevered IRR", x["unlevered_irr"], a["unlevered_irr"], "unlevered_irr", NUM_PERCENT),
        )


def build_quick_audit_workbook(source: QuickAuditSource) -> bytes:
    """The complete ``.xlsx`` for one saved, currently analysed Quick Deal.

    Raises ``QuickAuditExportError`` (``ANALYSIS_INCONSISTENT``) when the saved
    analysis does not reconcile with the saved inputs and Business Plan."""

    return _QuickAuditWorkbook(source).build()
