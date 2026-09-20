"""Excel Export 2 -- the Detailed Underwrite formula-audit workbook.

One workbook, eight sheets, in the same order Excel Export 1 publishes::

    Summary, Inputs, Operating Projection, Debt Schedule, Equity Cash Flow,
    Anchor Results, Checks, Audit Metadata

What is Detailed's own is the Operating Projection: an independent Excel
rebuild of the property-level revenue and expense model
(``docs/detailed_operating_model_v2_1_financial_conventions.md``) for Years 1
through H+1 -- gross potential rent and other income compounding at revenue
growth, vacancy and credit loss taken on gross potential rent alone, the five
fixed-dollar expense lines compounding at expense growth, a management fee
scaled from effective gross income, and NOI as the difference. Year H+1 is run
through that *complete* schedule and its NOI is the exit NOI; it is never
approximated by applying a blended growth rate to Year H's NOI, which is the
one thing the Projection Horizon convention forbids and the one thing that
becomes visibly wrong the moment revenue growth and expense growth differ.

Everything below the NOI row -- debt, equity, sale, returns, IRR,
reconciliation and presentation -- is the shared model in ``_workbook.py``,
because in Anchor it genuinely is the same model: Quick and Detailed converge
into one unmodified acquisition engine, and this workbook converges the same
way.

The formulas are an *independent representation* of the ratified contracts;
they are never read back by Anchor and never feed an application result. Every
formula cell is written with a *pessimistic* cached value, so only a real
recalculation can make a check pass.
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
    _xref,
)
from .source import (
    DETAILED_EXPORT_CONTRACT_VERSION,
    DetailedAuditExportError,
    DetailedAuditRefusalCode,
    DetailedAuditSource,
)

__all__ = ["build_detailed_audit_workbook"]

#: The Detailed operating schedule, in statement order: the key both the Excel
#: model and the frozen Anchor block use, the row label, and the
#: ``OperatingProjection`` field the saved analysis holds.
#:
#: One list, used four times -- to write the Excel rows, to write Anchor's
#: frozen rows, to reconcile them year by year, and to prove the sheet is
#: complete -- so a line cannot be modelled, frozen or checked in isolation.
OPERATING_LINES: tuple[tuple[str, str, str], ...] = (
    ("gpr", "Gross potential rent", "gross_potential_rent_by_year"),
    ("other_income", "Other income", "other_income_by_year"),
    ("vacancy", "Vacancy and credit loss", "vacancy_credit_loss_by_year"),
    ("egi", "Effective gross income", "effective_gross_income_by_year"),
    ("property_taxes", "Property taxes", "property_taxes_by_year"),
    ("insurance", "Insurance", "insurance_by_year"),
    ("utilities", "Utilities", "utilities_by_year"),
    ("repairs_maintenance", "Repairs and maintenance", "repairs_maintenance_by_year"),
    ("other_opex", "Other operating expenses", "other_operating_expenses_by_year"),
    ("management_fee", "Management fee", "management_fee_by_year"),
    ("total_opex", "Total operating expenses", "total_operating_expenses_by_year"),
    ("noi", "Net operating income", "noi_by_year"),
)

#: The five fixed-dollar expense lines: Year 1 amounts that compound at
#: expense growth, independently of income. The management fee is deliberately
#: not among them -- it scales from EGI instead (conventions, "Operating
#: Expense Conventions").
FIXED_EXPENSE_LINES: tuple[str, ...] = (
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "other_opex",
)

_LINE_LABELS: dict[str, str] = {key: label for key, label, _field in OPERATING_LINES}


def _line_label(key: str) -> str:
    """One operating line's label, from the single list that defines them.

    Every place a line is named -- the operating statement, the frozen Anchor
    block and the reconciliation -- uses this, so the same line cannot end up
    called two things on two sheets."""

    return _LINE_LABELS[key]


class _DetailedAuditWorkbook(_AuditWorkbookBase):
    """Detailed Underwrite's formula-audit workbook."""

    MODE_LABEL = "Detailed Underwrite"
    WORKBOOK_TITLE = "Detailed Underwrite Audit"
    CONTRACT_VERSION = DETAILED_EXPORT_CONTRACT_VERSION
    SUMMARY_NOTE = (
        "Formula-level audit of a saved Anchor Detailed Underwrite analysis. The Excel model "
        "rebuilds the operating statement and recalculates from the Inputs sheet; Anchor's "
        "results are frozen for comparison."
    )
    CHECKS_NOTE = (
        "Every Detailed operating line is reconciled year by year, not only NOI. Year H+1 is "
        "the exit-only forward year: Anchor stores its NOI, which is reconciled directly, and "
        "its revenue and expense lines are proved by the identities below."
    )
    NOI_CONVENTION = (
        "NOI is built, not assumed: EGI = gross potential rent - vacancy and credit loss + "
        "other income, where vacancy applies to gross potential rent only; NOI = EGI - total "
        "operating expenses. Revenue lines compound at revenue growth and the five fixed "
        "expense lines at expense growth, both from Year 1: Line(y) = Line(1) x (1 + g)^(y - 1). "
        "The management fee is EGI x management fee %, never grown from a Year 1 amount."
    )
    SCOPE_NOTE = (
        "Only Detailed Underwrite Deals are supported. Quick Underwrite has its own audit "
        "workbook; Lease-Level, Investments, Scenarios, Strategies, Capital Structure, "
        "Partnership Waterfalls and Asset Management are not exported."
    )

    def __init__(self, source: DetailedAuditSource) -> None:
        self.detailed = source.detailed_operating_inputs
        self.projection = source.operating_projection
        super().__init__(source, acquisition=source.terms, results=source.results)

    def _refuse(self, message: str) -> Exception:
        return DetailedAuditExportError(
            DetailedAuditRefusalCode.ANALYSIS_INCONSISTENT, message
        )

    # ----------------------------------------------------------------- Inputs

    def _inputs_note(self) -> str:
        return (
            "Original Export is what Anchor analysed. Working Input starts equal to it and is "
            "the only column the model reads; edit it to explore a modified case. Every "
            "operating line is built from these assumptions, not entered as NOI."
        )

    def _input_specs(self) -> list[tuple[str, list[_InputSpec]]]:
        t = self.terms
        d = self.detailed
        positive = {"validate": "decimal", "criteria": ">", "value": 0}
        non_negative = {"validate": "decimal", "criteria": ">=", "value": 0}
        fraction = {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 1}
        above_minus_one = {"validate": "decimal", "criteria": ">", "value": -1}
        return [
            (
                "Acquisition",
                [
                    _InputSpec("purchase_price", "Purchase price", "$", t.purchase_price, NUM_CURRENCY, name="Purchase_Price", validation=positive),
                    _InputSpec("acquisition_cost_pct", "Acquisition costs", "% of purchase price", t.acquisition_cost_pct, NUM_PERCENT, name="Acquisition_Cost_Pct", validation=fraction),
                ],
            ),
            (
                "Revenue (Year 1 amounts)",
                [
                    _InputSpec("gross_potential_rent", "Gross potential rent", "$ per year", d.gross_potential_rent, NUM_CURRENCY, name="Gross_Potential_Rent", validation=non_negative),
                    _InputSpec("other_income", "Other income", "$ per year", d.other_income, NUM_CURRENCY, name="Other_Income", validation=non_negative),
                    _InputSpec("vacancy_credit_loss_pct", "Vacancy and credit loss", "% of gross potential rent", d.vacancy_credit_loss_pct, NUM_PERCENT, name="Vacancy_Credit_Loss_Pct", validation=fraction),
                    _InputSpec("revenue_growth", "Revenue growth", "% per year, from Year 2", d.revenue_growth, NUM_PERCENT, name="Revenue_Growth", validation=above_minus_one),
                ],
            ),
            (
                "Operating expenses (Year 1 amounts)",
                [
                    _InputSpec("property_taxes", "Property taxes", "$ per year", d.property_taxes, NUM_CURRENCY, name="Property_Taxes", validation=non_negative),
                    _InputSpec("insurance", "Insurance", "$ per year", d.insurance, NUM_CURRENCY, name="Insurance", validation=non_negative),
                    _InputSpec("utilities", "Utilities", "$ per year", d.utilities, NUM_CURRENCY, name="Utilities", validation=non_negative),
                    _InputSpec("repairs_maintenance", "Repairs and maintenance", "$ per year", d.repairs_maintenance, NUM_CURRENCY, name="Repairs_Maintenance", validation=non_negative),
                    _InputSpec("other_operating_expenses", "Other operating expenses", "$ per year", d.other_operating_expenses, NUM_CURRENCY, name="Other_Operating_Expenses", validation=non_negative),
                    _InputSpec("management_fee_pct", "Management fee", "% of effective gross income", d.management_fee_pct, NUM_PERCENT, name="Management_Fee_Pct", validation=fraction),
                    _InputSpec("expense_growth", "Expense growth", "% per year, from Year 2", d.expense_growth, NUM_PERCENT, name="Expense_Growth", validation=above_minus_one),
                ],
            ),
            (
                "Reserves (below NOI)",
                [
                    _InputSpec("annual_capex_reserve", "Annual CapEx reserve", "$ per year, below NOI", t.annual_capex_reserve, NUM_CURRENCY, name="CapEx_Reserve", validation=non_negative),
                ],
            ),
            (
                "Financing",
                [
                    _InputSpec("ltv", "Loan-to-value", "% of purchase price", t.ltv, NUM_PERCENT, name="Loan_To_Value", validation=fraction),
                    _InputSpec("interest_rate", "Interest rate", "% per year, fixed", t.interest_rate, NUM_PERCENT, name="Interest_Rate", validation=non_negative),
                    _InputSpec("amortization", "Amortization", "years", float(t.amortization), NUM_INTEGER, name="Amortization_Years", validation={"validate": "integer", "criteria": ">=", "value": 1}),
                    _InputSpec("io_period", "Interest-only period", "years", float(t.io_period), NUM_INTEGER, name="IO_Period_Years", validation={"validate": "integer", "criteria": ">=", "value": 0}),
                    _InputSpec("financing_fee_pct", "Financing fee", "% of loan amount", t.financing_fee_pct, NUM_PERCENT, name="Financing_Fee_Pct", validation=fraction),
                ],
            ),
            (
                "Exit",
                [
                    _InputSpec("hold_period", "Hold period", "years", float(self.hold), NUM_INTEGER, fixed_note="Fixed at export: sets the period columns", name="Hold_Period"),
                    _InputSpec("exit_cap_rate", "Exit cap rate", "% of Year H+1 NOI", t.exit_cap_rate, NUM_PERCENT, name="Exit_Cap_Rate", validation=positive),
                    _InputSpec("disposition_cost_pct", "Disposition costs", "% of gross sale price", t.disposition_cost_pct, NUM_PERCENT, name="Disposition_Cost_Pct", validation=fraction),
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
            "The property-level operating statement, rebuilt from the Detailed assumptions. "
            f"Year {hold + 1} is run through this same complete schedule and its NOI is the "
            "exit NOI; no blended growth rate is applied to Year "
            f"{hold}.",
        )
        row = 3
        self._section(sheet, row, "Assumptions used (from Inputs)", last_col)
        row += 1
        links = (
            ("gpr", "Gross potential rent (Year 1)", "$ per year", "=Gross_Potential_Rent", NUM_CURRENCY),
            ("other_income", "Other income (Year 1)", "$ per year", "=Other_Income", NUM_CURRENCY),
            ("vacancy_pct", "Vacancy and credit loss", "% of gross potential rent", "=Vacancy_Credit_Loss_Pct", NUM_PERCENT),
            ("revenue_growth", "Revenue growth", "% per year", "=Revenue_Growth", NUM_PERCENT),
            ("property_taxes", "Property taxes (Year 1)", "$ per year", "=Property_Taxes", NUM_CURRENCY),
            ("insurance", "Insurance (Year 1)", "$ per year", "=Insurance", NUM_CURRENCY),
            ("utilities", "Utilities (Year 1)", "$ per year", "=Utilities", NUM_CURRENCY),
            ("repairs_maintenance", "Repairs and maintenance (Year 1)", "$ per year", "=Repairs_Maintenance", NUM_CURRENCY),
            ("other_opex", "Other operating expenses (Year 1)", "$ per year", "=Other_Operating_Expenses", NUM_CURRENCY),
            ("management_fee_pct", "Management fee", "% of effective gross income", "=Management_Fee_Pct", NUM_PERCENT),
            ("expense_growth", "Expense growth", "% per year", "=Expense_Growth", NUM_PERCENT),
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

        # Growth factors, written once and read by every line, so the
        # compounding convention is visible in one place per rate.
        self._section(sheet, row, "Growth factors  (1 + growth) ^ (year - 1)", last_col)
        row += 1
        revenue_factor_row, expense_factor_row = row, row + 1
        self._label(sheet, revenue_factor_row, "Revenue growth factor", indent=1)
        self._units(sheet, revenue_factor_row, "factor")
        self._label(sheet, expense_factor_row, "Expense growth factor", indent=1)
        self._units(sheet, expense_factor_row, "factor")
        for offset in range(hold + 1):
            col = first_col + offset
            year_ref = _cell(year_row, col, row_abs=True)
            self._formula(sheet, revenue_factor_row, col, f"=(1+{a['revenue_growth']})^({year_ref}-1)", "calc", NUM_FACTOR)
            self._formula(sheet, expense_factor_row, col, f"=(1+{a['expense_growth']})^({year_ref}-1)", "calc", NUM_FACTOR)
        row = expense_factor_row + 2

        rows: dict[str, int] = {}

        self._section(sheet, row, "Revenue", last_col)
        row += 1
        for key in ("gpr", "other_income", "vacancy"):
            self._label(sheet, row, _line_label(key), indent=1)
            self._units(sheet, row, "$")
            rows[key] = row
            row += 1
        self._label(sheet, row, _line_label("egi"), bold=True)
        self._units(sheet, row, "$")
        rows["egi"] = row
        row += 2

        self._section(sheet, row, "Operating expenses", last_col)
        row += 1
        for key, label, _field in OPERATING_LINES:
            if key not in FIXED_EXPENSE_LINES:
                continue
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, "$")
            rows[key] = row
            row += 1
        self._label(sheet, row, _line_label("management_fee"), indent=1)
        self._units(sheet, row, "$")
        rows["management_fee"] = row
        row += 1
        self._label(sheet, row, _line_label("total_opex"), bold=True)
        self._units(sheet, row, "$")
        rows["total_opex"] = row
        row += 2

        # The section band is named apart from the line it introduces: the two
        # sit in the same column, and a reader (or a test) looking up the NOI
        # row must not find the heading above it instead.
        self._section(sheet, row, "Net operating income (NOI)", last_col)
        row += 1
        self._label(sheet, row, _line_label("noi"), bold=True)
        self._units(sheet, row, "$")
        rows["noi"] = row
        noi_row = row
        row += 1
        self._label(sheet, row, "Change from prior year", indent=1)
        self._units(sheet, row, "%")
        growth_row = row
        row += 1

        # Every column, including the exit-only forward year, is built by the
        # identical formulas. That is the Projection Horizon convention: the
        # forward year is a real year of the model, not an extrapolation.
        for offset in range(hold + 1):
            col = first_col + offset
            revenue_factor = _cell(revenue_factor_row, col)
            expense_factor = _cell(expense_factor_row, col)
            forward = offset == hold
            year = offset + 1

            self._formula(sheet, rows["gpr"], col, f"={a['gpr']}*{revenue_factor}", "calc", NUM_CURRENCY)
            self._formula(sheet, rows["other_income"], col, f"={a['other_income']}*{revenue_factor}", "calc", NUM_CURRENCY)
            self._formula(sheet, rows["vacancy"], col, f"={_cell(rows['gpr'], col)}*{a['vacancy_pct']}", "calc", NUM_CURRENCY)
            self._formula(
                sheet, rows["egi"], col,
                f"={_cell(rows['gpr'], col)}-{_cell(rows['vacancy'], col)}+{_cell(rows['other_income'], col)}",
                "calc", NUM_CURRENCY, bold=True,
            )
            for key in FIXED_EXPENSE_LINES:
                self._formula(sheet, rows[key], col, f"={a[key]}*{expense_factor}", "calc", NUM_CURRENCY)
            self._formula(sheet, rows["management_fee"], col, f"={_cell(rows['egi'], col)}*{a['management_fee_pct']}", "calc", NUM_CURRENCY)
            first_expense_row = rows[FIXED_EXPENSE_LINES[0]]
            self._formula(
                sheet, rows["total_opex"], col,
                f"=SUM({_cell(first_expense_row, col)}:{_cell(rows['management_fee'], col)})",
                "calc", NUM_CURRENCY, bold=True,
            )
            self._formula(
                sheet, rows["noi"], col,
                f"={_cell(rows['egi'], col)}-{_cell(rows['total_opex'], col)}",
                "calc", NUM_CURRENCY, bold=True,
            )

            for key, _label, _field in OPERATING_LINES:
                self.excel[f"line:{key}:{year}"] = _xref(sheet, rows[key], col)
            if forward:
                self.excel["exit_noi"] = _xref(sheet, rows["noi"], col)
            else:
                self.excel[f"noi:{year}"] = _xref(sheet, rows["noi"], col)

            if offset == 0:
                ws.write_string(growth_row, col, "n/a", self.fmt.get(align="right", font_color=NOTE_GRAY))
            else:
                prior, current = _cell(noi_row, col - 1), _cell(noi_row, col)
                self._formula(sheet, growth_row, col, f'=IF({prior}=0,"n/a",{current}/{prior}-1)', "calc", NUM_PERCENT)

        self.noi_row = noi_row
        self.operating_line_rows = rows
        row = growth_row + 1
        ws.write_string(
            row, 0,
            f"Year {hold + 1} is the exit-only forward year: every line above is projected one "
            f"further year by the same formulas, and its NOI values the sale at the end of Year "
            f"{hold}. It is not a hold-year cash flow.",
            self.fmt.note(),
        )
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

    # ----------------------------------------------------------- Anchor Results

    def _anchor_operating_rows(self, row: int, c0: int) -> int:
        """The saved Detailed operating schedule, frozen.

        Years 1..H only: ``OperatingProjection`` holds no line items for the
        forward year -- the saved analysis keeps that year's NOI as
        ``exit_noi`` and nothing else -- so this block stops at Year H rather
        than inventing an Anchor value the analysis never stored."""

        sheet = "Anchor Results"
        ws = self.sheets[sheet]
        last_col = c0 + self.hold
        self._section(sheet, row, f"Detailed operating projection (Years 1 to {self.hold})", last_col)
        row += 1
        self._period_header(sheet, row, c0 + 1, [f"Year {year}" for year in self.years], left="Operating line")
        row += 1
        for key, label, field in OPERATING_LINES:
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, "$")
            for offset, value in enumerate(getattr(self.projection, field)):
                self.anchor[f"line:{key}:{offset + 1}"] = self._frozen(
                    sheet, row, c0 + 1 + offset, value, NUM_CURRENCY
                )
            row += 1
        ws.write_string(
            row, 0,
            f"The saved analysis stores operating lines for Years 1 to {self.hold} only. Year "
            f"{self.hold + 1} is represented by its NOI (Exit NOI, above); the Excel model's "
            "forward-year lines are proved by identity instead.",
            self.fmt.note(),
        )
        return row + 2

    # ----------------------------------------------------------------- Checks

    def _operations_checks(self) -> list[_Check]:
        x = self.excel
        checks: list[_Check] = []
        # Every Detailed operating line, every hold year, against the saved
        # projection -- not only the NOI it adds up to.
        for key, label, _field in OPERATING_LINES:
            checks.extend(
                self._check(
                    f"{label}, Year {year}",
                    f"line:{key}:{year}",
                    x[f"line:{key}:{year}"],
                    "currency",
                    NUM_CURRENCY_CENTS,
                )
                for year in self.years
            )
        checks.append(
            self._check("Exit NOI (Year H+1)", "exit_noi", x["exit_noi"], "currency", NUM_CURRENCY_CENTS)
        )
        checks.extend(
            [
                *self._yearly("CapEx reserve", "capex", "capex", "currency", NUM_CURRENCY_CENTS, negate=True),
                *self._yearly("Business Plan project capital", "project_capital", "project_capital", "currency", NUM_CURRENCY_CENTS, negate=True),
                *self._yearly("Business Plan owner expenses", "owner_expenses", "owner_expenses", "currency", NUM_CURRENCY_CENTS, negate=True),
                *self._yearly("Property cash flow after CapEx", "property_cf", "property_cf", "currency", NUM_CURRENCY_CENTS),
                *self._yearly("Unlevered owner cash flow", "uocf", "uocf", "currency", NUM_CURRENCY_CENTS),
                self._check("Going-in cap rate", "going_in_cap_rate", x["going_in_cap_rate"], "ratio", NUM_PERCENT_FINE, key="going_in_cap_rate"),
            ]
        )
        return checks

    def _identity_checks(self) -> list[_Check]:
        """The operating statement's own identities, every year including the
        exit-only forward year.

        Each row restates a convention as an expression over other cells and
        compares it with the line the model wrote. For Years 1..H this is a
        second, independent proof beside the Anchor reconciliation; for Year
        H+1, where the saved analysis holds no line items, it is what proves
        the forward year was actually projected rather than extrapolated."""

        rows = self.operating_line_rows
        sheet = OPERATING
        checks: list[_Check] = []

        def cell(key: str, offset: int) -> str:
            """A fully qualified reference. These expressions are evaluated on
            the Checks sheet, so an unqualified ``$C$25`` would silently read
            Checks' own row 25 instead of the operating line it names."""

            return _xref(sheet, rows[key], 2 + offset)

        for offset in range(self.hold + 1):
            forward = offset == self.hold
            year = offset + 1
            suffix = f"Year {year}" + (" (exit year)" if forward else "")
            vacancy_pct = "Vacancy_Credit_Loss_Pct"
            management_fee_pct = "Management_Fee_Pct"
            first_expense = cell(FIXED_EXPENSE_LINES[0], offset)
            identities = (
                (
                    "Vacancy and credit loss identity (GPR x vacancy %)",
                    f"{cell('gpr', offset)}*{vacancy_pct}",
                    cell("vacancy", offset),
                ),
                (
                    "Effective gross income identity (GPR - vacancy + other income)",
                    f"{cell('gpr', offset)}-{cell('vacancy', offset)}+{cell('other_income', offset)}",
                    cell("egi", offset),
                ),
                (
                    "Management fee identity (EGI x management fee %)",
                    f"{cell('egi', offset)}*{management_fee_pct}",
                    cell("management_fee", offset),
                ),
                (
                    "Total operating expenses identity (six expense lines)",
                    # The five fixed lines and the management fee are written
                    # as one contiguous block, so the sum is the block.
                    f"SUM({first_expense}:{_abs(rows['management_fee'], 2 + offset)})",
                    cell("total_opex", offset),
                ),
                (
                    "NOI identity (EGI - total operating expenses)",
                    f"{cell('egi', offset)}-{cell('total_opex', offset)}",
                    cell("noi", offset),
                ),
            )
            for label, expression, actual in identities:
                checks.append(
                    _Check(
                        metric=f"{label}, {suffix}",
                        anchor=expression,
                        excel=actual,
                        location=actual.replace("$", "").replace("'", ""),
                        kind="currency",
                        number_format=NUM_CURRENCY_CENTS,
                        guard_anchor=True,
                    )
                )
        return checks

    def _check_groups(self) -> list[tuple[str, list[_Check]]]:
        groups = super()._check_groups()
        # Directly after Operations, where the lines they prove are.
        index = next(i for i, (name, _) in enumerate(groups) if name == "Operations") + 1
        groups.insert(index, ("Operating statement identities", self._identity_checks()))
        return groups

    # ---------------------------------------------------------------- Summary

    def _summary_metrics(self) -> tuple[tuple[str, str, str, str | None, str], ...]:
        x, a = self.excel, self.anchor
        return (
            ("Purchase price", x["input:purchase_price"], x["original:purchase_price"], None, NUM_CURRENCY),
            ("Year 1 effective gross income", x["line:egi:1"], a["line:egi:1"], "metric:Effective gross income, Year 1", NUM_CURRENCY),
            ("Year 1 total operating expenses", x["line:total_opex:1"], a["line:total_opex:1"], "metric:Total operating expenses, Year 1", NUM_CURRENCY),
            ("Year 1 NOI", x["noi:1"], a["line:noi:1"], "metric:Net operating income, Year 1", NUM_CURRENCY),
            (f"Year {self.hold + 1} NOI (exit NOI)", x["exit_noi"], a["exit_noi"], "metric:Exit NOI (Year H+1)", NUM_CURRENCY),
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

    # --------------------------------------------------------- Audit Metadata

    def _extra_conventions(self) -> tuple[tuple[str, str], ...]:
        return (
            (
                "Exit NOI",
                f"Year {self.hold + 1} is projected through the complete operating schedule -- "
                "every revenue line, vacancy, every expense line and the management fee grown "
                "one further year -- and its NOI is the exit NOI. No blended NOI growth rate "
                f"is applied to Year {self.hold}. The saved analysis stores that year's NOI "
                "only, so the forward year's individual lines are reconciled by identity.",
            ),
            (
                "Below NOI",
                "CapEx reserves, debt service, acquisition costs, financing fees and "
                "disposition costs are all below NOI, in the cash-flow assembly. NOI is a "
                "property-level operating metric, and DSCR is computed on it before capital "
                "reserves.",
            ),
            (
                "Occupancy",
                "Detailed Underwrite does not read occupancy. Vacancy and credit loss is the "
                "sole vacancy mechanism, and it applies to gross potential rent only.",
            ),
        )


def build_detailed_audit_workbook(source: DetailedAuditSource) -> bytes:
    """The complete ``.xlsx`` for one saved, currently analysed Detailed Deal.

    Raises ``DetailedAuditExportError`` (``ANALYSIS_INCONSISTENT``) when the
    saved analysis does not reconcile with the saved inputs and Business
    Plan."""

    return _DetailedAuditWorkbook(source).build()
