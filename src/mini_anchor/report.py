"""Terminal presentation of one ``AcquisitionResults`` (Phase 4 results layer).

This module formats already-computed engine output for display. It performs
no financial calculation of its own -- every number shown here is read
directly from ``AcquisitionInputs`` or ``AcquisitionResults`` and only passed
through the presentation-only helpers in ``formatting.py``.
"""

from __future__ import annotations

from .contracts import AcquisitionInputs
from .engine import AcquisitionResults
from .formatting import (
    format_bps,
    format_currency,
    format_multiple,
    format_percent,
    format_years,
)

_RULE = "=" * 72
_SECTION_RULE = "-" * 72

# Width of the "Label:" column in the ASSUMPTIONS section, chosen so the
# longest label ("Purchase Price:") sets the column and every row totals
# _ASSUMPTION_LABEL_WIDTH + _ASSUMPTION_VALUE_WIDTH characters.
_ASSUMPTION_LABEL_WIDTH = 15
_ASSUMPTION_VALUE_WIDTH = 21

_HEADLINE_DSCR_THRESHOLD = 1.20
_LEVERED_IRR_THRESHOLD = 0.10


def _header(title: str) -> str:
    return f"{_SECTION_RULE}\n{title}\n{_SECTION_RULE}"


def build_report(inputs: AcquisitionInputs, results: AcquisitionResults) -> str:
    """Build the professionally formatted investment summary as one string."""

    lines: list[str] = []

    lines.append(_RULE)
    lines.append("MINI-ANCHOR ACQUISITION ANALYSIS")
    lines.append(_RULE)
    lines.append("")

    lines.append(_header("ASSUMPTIONS"))
    lines.append(_assumptions_section(inputs))
    lines.append("")

    lines.append(_header("PROPERTY"))
    lines.append(f"Going-In Cap Rate:        {format_percent(results.going_in_cap_rate)}")
    lines.append("NOI by Year:")
    for year, noi in enumerate(results.noi_by_year, start=1):
        label = f"  Year {year}:"
        lines.append(f"{label:<20}{format_currency(noi)}")
    lines.append(f"Exit NOI:                 {format_currency(results.exit_noi)}")
    lines.append(f"Exit Value:               {format_currency(results.exit_value)}")
    lines.append("")

    lines.append(_header("CAPITALIZATION"))
    lines.append(f"Loan Amount:              {format_currency(results.loan_amount)}")
    lines.append(f"Initial Equity:           {format_currency(results.initial_equity)}")
    lines.append(f"Monthly Debt Service:     {format_currency(results.monthly_debt_service)}")
    lines.append("Annual Debt Service by Year:")
    for year, ads in enumerate(results.annual_debt_service, start=1):
        label = f"  Year {year}:"
        lines.append(f"{label:<20}{format_currency(ads)}")
    lines.append(f"Remaining Loan Balance:   {format_currency(results.remaining_loan_balance)}")
    lines.append("")

    lines.append(_header("RETURNS"))
    lines.append(f"Levered IRR:              {format_percent(results.levered_irr)}")
    lines.append(f"Unlevered IRR:            {format_percent(results.unlevered_irr)}")
    lines.append(f"Equity Multiple:          {format_multiple(results.equity_multiple)}")
    lines.append(f"Headline DSCR:            {format_multiple(results.headline_dscr)}")
    lines.append("")

    lines.append(_header("EXIT"))
    lines.append(f"Net Sale Proceeds:        {format_currency(results.net_sale_proceeds)}")
    lines.append("")

    lines.append(_header("CASH FLOW DETAIL"))
    lines.append(_cash_flow_table(inputs, results))
    lines.append("")

    lines.append(_header("RISK FLAGS"))
    lines.append(
        "(Presentation-only heuristics -- not engine calculations, not investment recommendations.)"
    )
    lines.append(_risk_flags_section(inputs, results))
    lines.append("")

    return "\n".join(lines)


def _assumption_line(label: str, value: str) -> str:
    return f"{label + ':':<{_ASSUMPTION_LABEL_WIDTH}}{value:>{_ASSUMPTION_VALUE_WIDTH}}"


def _assumptions_section(inputs: AcquisitionInputs) -> str:
    rows = [
        _assumption_line("Purchase Price", format_currency(inputs.purchase_price)),
        _assumption_line("Current NOI", format_currency(inputs.current_noi)),
        _assumption_line("Occupancy", format_percent(inputs.occupancy)),
        _assumption_line("NOI Growth", format_percent(inputs.noi_growth)),
        _assumption_line("Hold Period", format_years(inputs.hold_period)),
        _assumption_line("Exit Cap Rate", format_percent(inputs.exit_cap_rate)),
        _assumption_line("LTV", format_percent(inputs.ltv)),
        _assumption_line("Interest Rate", format_percent(inputs.interest_rate)),
        _assumption_line("Amortization", format_years(inputs.amortization)),
    ]
    return "\n".join(rows)


def _compute_risk_flags(inputs: AcquisitionInputs, results: AcquisitionResults) -> list[str]:
    """Simple presentation-layer heuristics -- not engine calculations and not
    investment recommendations. These flags are derived only from values
    already present on ``AcquisitionInputs``/``AcquisitionResults``."""

    flags: list[str] = []

    if results.headline_dscr is not None and results.headline_dscr < _HEADLINE_DSCR_THRESHOLD:
        flags.append("Year 1 DSCR below 1.20x")

    if results.levered_irr is not None and results.levered_irr < _LEVERED_IRR_THRESHOLD:
        flags.append("Levered IRR below 10.00% reference threshold")

    if inputs.exit_cap_rate > results.going_in_cap_rate:
        spread = inputs.exit_cap_rate - results.going_in_cap_rate
        flags.append(f"Exit cap is {format_bps(spread)} above going-in cap")

    negative_years = [
        year
        for year in range(1, inputs.hold_period + 1)
        if results.levered_cash_flows[year] < 0
    ]
    if negative_years:
        year_word = "Year" if len(negative_years) == 1 else "Years"
        years_text = ", ".join(str(year) for year in negative_years)
        flags.append(f"Negative levered cash flow in {year_word} {years_text}")

    return flags


def _risk_flags_section(inputs: AcquisitionInputs, results: AcquisitionResults) -> str:
    flags = _compute_risk_flags(inputs, results)
    if not flags:
        return "No basic risk flags triggered"
    return "\n".join(f"- {flag}" for flag in flags)


def _cash_flow_table(inputs: AcquisitionInputs, results: AcquisitionResults) -> str:
    hold_period = inputs.hold_period

    header = f"{'Year':<8}{'NOI':>16}{'DSCR':>10}{'Unlevered CF':>18}{'Levered CF':>18}"
    rows = [header, "-" * len(header)]

    rows.append(
        f"{'0':<8}{'—':>16}{'—':>10}"
        f"{format_currency(results.unlevered_cash_flows[0]):>18}"
        f"{format_currency(results.levered_cash_flows[0]):>18}"
    )

    for year in range(1, hold_period + 1):
        noi = results.noi_by_year[year - 1]
        dscr = results.dscr_by_year[year - 1]
        ucf = results.unlevered_cash_flows[year]
        lcf = results.levered_cash_flows[year]
        rows.append(
            f"{year:<8}{format_currency(noi):>16}{format_multiple(dscr):>10}"
            f"{format_currency(ucf):>18}{format_currency(lcf):>18}"
        )

    return "\n".join(rows)
