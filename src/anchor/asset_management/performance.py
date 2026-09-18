"""Gate AM1 -- the deterministic monthly performance calculations.

Restates ``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md``
Section 4 (authorized); that document governs on any discrepancy. Pure: no I/O,
no clock, no randomness, no AI, and no knowledge of storage or routes. This
module is the **sole** authority for every AM1 financial result; the API
serializes what it returns and the frontend formats it. Neither recomputes it.

The identities, exactly as authorized:

    total_revenue            = rental_revenue + other_income
    total_operating_expenses = the seven operating-expense lines
    net_operating_income     = total_revenue - total_operating_expenses
    cash_flow_after_capex    = net_operating_income - capital_expenditures
    net_cash_flow            = cash_flow_after_capex - debt_service
    noi_margin               = net_operating_income / total_revenue
    variance                 = actual - budget
    variance_pct             = variance / abs(budget)

Two values are **unavailable** rather than zero or infinite: ``noi_margin``
when total revenue is zero, and ``variance_pct`` when the budget is zero. Both
are ``None``. Zero would be a claim about the asset that nothing supports, and
an infinity would propagate into presentation as a number.

Nothing here divides an annual figure by twelve. A monthly budget is always the
budget the analyst explicitly entered and the report froze; this module never
sees an annual forecast and has no entry point that would accept one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from .contracts import (
    OPERATING_EXPENSE_FIELDS,
    REVENUE_FIELDS,
    Assessment,
    AssetPerformanceResult,
    AttentionItem,
    FinancialLine,
    LineVariance,
    MonthlyAssetReport,
    NoiTrendPoint,
    OperatingFigures,
    PeriodPerformance,
    PeriodTotals,
    UnitOfMeasure,
    VarianceDirection,
)

Line = FinancialLine
Direction = VarianceDirection

#: Which sign of ``actual - budget`` is favorable, declared once per line.
#:
#: Read by ``_assess`` and carried onto every ``LineVariance``, so favorability
#: has exactly one definition in the system and the frontend never re-derives it
#: from a line's name.
#:
#: Three deliberate choices:
#:
#: * every operating-expense line, and their total, are ``LOWER_IS_FAVORABLE``:
#:   spending more than approved is unfavorable, spending less is favorable;
#: * capital expenditures and debt service have ``NO_DIRECTION``. Underspending
#:   CapEx is not a saving -- it is deferred work, and often the opposite of
#:   good news -- and debt service is contractual, so a difference from plan is
#:   a fact to show, never a verdict to render. AM1 never infers that lower
#:   CapEx is favorable;
#: * ``CASH_FLOW_AFTER_CAPEX`` has ``NO_DIRECTION`` because it embeds capital
#:   expenditures, whose variance carries no favorability at all. Giving the
#:   subtotal a direction would launder a neutral line into a verdict. Net cash
#:   flow is explicitly authorized as higher-is-favorable and keeps it.
_LINE_DIRECTION: dict[FinancialLine, VarianceDirection] = {
    Line.OCCUPANCY: Direction.HIGHER_IS_FAVORABLE,
    Line.RENTAL_REVENUE: Direction.HIGHER_IS_FAVORABLE,
    Line.OTHER_INCOME: Direction.HIGHER_IS_FAVORABLE,
    Line.TOTAL_REVENUE: Direction.HIGHER_IS_FAVORABLE,
    Line.PROPERTY_TAXES: Direction.LOWER_IS_FAVORABLE,
    Line.INSURANCE: Direction.LOWER_IS_FAVORABLE,
    Line.UTILITIES: Direction.LOWER_IS_FAVORABLE,
    Line.REPAIRS_AND_MAINTENANCE: Direction.LOWER_IS_FAVORABLE,
    Line.PAYROLL: Direction.LOWER_IS_FAVORABLE,
    Line.MANAGEMENT_FEES: Direction.LOWER_IS_FAVORABLE,
    Line.OTHER_OPERATING_EXPENSES: Direction.LOWER_IS_FAVORABLE,
    Line.TOTAL_OPERATING_EXPENSES: Direction.LOWER_IS_FAVORABLE,
    Line.NET_OPERATING_INCOME: Direction.HIGHER_IS_FAVORABLE,
    Line.CAPITAL_EXPENDITURES: Direction.NO_DIRECTION,
    Line.CASH_FLOW_AFTER_CAPEX: Direction.NO_DIRECTION,
    Line.DEBT_SERVICE: Direction.NO_DIRECTION,
    Line.NET_CASH_FLOW: Direction.HIGHER_IS_FAVORABLE,
}

#: Presentation labels, in one place so the API, the attention items and the
#: frontend all name a line identically. Not economics.
LINE_LABELS: dict[FinancialLine, str] = {
    Line.OCCUPANCY: "Occupancy",
    Line.RENTAL_REVENUE: "Rental Revenue",
    Line.OTHER_INCOME: "Other Income",
    Line.TOTAL_REVENUE: "Total Revenue",
    Line.PROPERTY_TAXES: "Property Taxes",
    Line.INSURANCE: "Insurance",
    Line.UTILITIES: "Utilities",
    Line.REPAIRS_AND_MAINTENANCE: "Repairs and Maintenance",
    Line.PAYROLL: "Payroll",
    Line.MANAGEMENT_FEES: "Management Fees",
    Line.OTHER_OPERATING_EXPENSES: "Other Operating Expenses",
    Line.TOTAL_OPERATING_EXPENSES: "Total Operating Expenses",
    Line.NET_OPERATING_INCOME: "Net Operating Income",
    Line.CAPITAL_EXPENDITURES: "Capital Expenditures",
    Line.CASH_FLOW_AFTER_CAPEX: "Cash Flow After CapEx",
    Line.DEBT_SERVICE: "Debt Service",
    Line.NET_CASH_FLOW: "Net Cash Flow",
}

#: Guards floating-point residue only, in nominal dollars and in fractional
#: occupancy. A variance at or below it is "on plan". It never rounds a reported
#: figure -- only the favorable/unfavorable/on-plan decision reads it, so
#: 0.0000001 of drift from summing floats cannot be reported as a miss.
VARIANCE_TOLERANCE = 1e-9

#: The monetary lines whose totals are summed across months for a year to date,
#: paired with the ``PeriodTotals`` field or ``OperatingFigures`` field each
#: reads. Occupancy is deliberately absent: a sum of occupancy rates is not a
#: fact, and AM1 does not report one (Section 4.6).
_YTD_SUMMED_FIELDS: tuple[str, ...] = (
    "rental_revenue",
    "other_income",
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_and_maintenance",
    "payroll",
    "management_fees",
    "other_operating_expenses",
    "capital_expenditures",
    "debt_service",
)


# =============================================================================
# Totals
# =============================================================================


def total_revenue(figures: OperatingFigures) -> float:
    return float(sum(getattr(figures, field) for field in REVENUE_FIELDS))


def total_operating_expenses(figures: OperatingFigures) -> float:
    return float(sum(getattr(figures, field) for field in OPERATING_EXPENSE_FIELDS))


def net_operating_income(figures: OperatingFigures) -> float:
    return total_revenue(figures) - total_operating_expenses(figures)


def cash_flow_after_capex(figures: OperatingFigures) -> float:
    return net_operating_income(figures) - float(figures.capital_expenditures)


def net_cash_flow(figures: OperatingFigures) -> float:
    return cash_flow_after_capex(figures) - float(figures.debt_service)


def noi_margin(figures: OperatingFigures) -> float | None:
    """NOI as a fraction of total revenue, or ``None`` when there is no revenue
    to take a fraction of. Exact zero is the only unavailable case: a revenue of
    0.0 has no ratio, and every non-zero revenue does."""

    revenue = total_revenue(figures)
    if revenue == 0.0:
        return None
    return net_operating_income(figures) / revenue


def period_totals(figures: OperatingFigures) -> PeriodTotals:
    """Every derived total for one statement, computed once."""

    return PeriodTotals(
        total_revenue=total_revenue(figures),
        total_operating_expenses=total_operating_expenses(figures),
        net_operating_income=net_operating_income(figures),
        cash_flow_after_capex=cash_flow_after_capex(figures),
        net_cash_flow=net_cash_flow(figures),
        noi_margin=noi_margin(figures),
    )


# =============================================================================
# Variance
# =============================================================================


def variance_pct(*, variance: float, budget: float) -> float | None:
    """``variance / abs(budget)``, or ``None`` when the budget is zero.

    ``abs`` is deliberate: the percentage states how far actual landed from
    plan as a share of the plan's magnitude, and its sign must therefore come
    from the variance alone. Dividing by a signed budget would flip the reported
    sign whenever the budget itself was negative, making a favorable result read
    as unfavorable.
    """

    if budget == 0.0:
        return None
    return variance / abs(budget)


def _assess(*, variance: float, direction: VarianceDirection) -> Assessment:
    """How one variance reads, from its sign and its line's direction alone.

    A line with ``NO_DIRECTION`` is ``NEUTRAL`` whatever its variance -- including
    when the variance is zero. It never becomes ``ON_PLAN``: on-plan is a
    judgement that the line landed on a target it has a direction toward, and a
    neutral line has none.
    """

    if direction is Direction.NO_DIRECTION:
        return Assessment.NEUTRAL
    if abs(variance) <= VARIANCE_TOLERANCE:
        return Assessment.ON_PLAN
    favorable_when_positive = direction is Direction.HIGHER_IS_FAVORABLE
    if (variance > 0.0) == favorable_when_positive:
        return Assessment.FAVORABLE
    return Assessment.UNFAVORABLE


def line_variance(
    *, line: FinancialLine, budget: float, actual: float, unit: UnitOfMeasure = UnitOfMeasure.CURRENCY
) -> LineVariance:
    """One line compared. The only place a ``LineVariance`` is built, so every
    line in every period is assessed by exactly the same rule."""

    direction = _LINE_DIRECTION[line]
    variance = float(actual) - float(budget)
    return LineVariance(
        line=line,
        unit=unit,
        direction=direction,
        budget=float(budget),
        actual=float(actual),
        variance=variance,
        variance_pct=variance_pct(variance=variance, budget=float(budget)),
        # Percentage points exist only on a percent line. On a dollar line the
        # field is `None` rather than 0.0, which would read as "no point
        # difference" on a line that has no points at all.
        variance_points=variance * 100.0 if unit is UnitOfMeasure.PERCENT else None,
        assessment=_assess(variance=variance, direction=direction),
    )


# =============================================================================
# Attention items
# =============================================================================


def _describe(item: LineVariance) -> str:
    """One unfavorable line, in words.

    Words, not color: the message states the direction ("below plan", "over
    budget") explicitly, so the item is complete to a reader who cannot
    distinguish red from green.
    """

    label = LINE_LABELS[item.line]
    if item.unit is UnitOfMeasure.PERCENT:
        points = abs(item.variance_points or 0.0)
        return f"{label} is {points:.1f} pts below plan"
    amount = abs(item.variance)
    if item.direction is Direction.LOWER_IS_FAVORABLE:
        return f"{label} is ${amount:,.0f} over budget"
    if item.variance_pct is not None:
        return f"{label} is {abs(item.variance_pct) * 100.0:.1f}% below plan"
    return f"{label} is ${amount:,.0f} below plan"


def attention_items(lines: Iterable[LineVariance]) -> tuple[AttentionItem, ...]:
    """Every unfavorable line, in statement order, worded for a person.

    Purely derived: it filters the variances the engine already computed and
    invents nothing. No model is consulted, no threshold is tuned, and no
    favorable, on-plan or neutral line can appear -- so an asset manager can
    trust that the list is exactly "what the numbers say went wrong".
    """

    return tuple(
        AttentionItem(line=item.line, message=_describe(item), assessment=item.assessment)
        for item in lines
        if item.assessment is Assessment.UNFAVORABLE
    )


# =============================================================================
# Periods
# =============================================================================


def _compare(
    *, budget: OperatingFigures, actual: OperatingFigures, with_occupancy: bool
) -> PeriodPerformance:
    """One period's complete comparison.

    ``with_occupancy=False`` is how a year to date omits the occupancy line
    entirely rather than reporting a summed or averaged rate (Section 4.6).
    """

    budget_totals = period_totals(budget)
    actual_totals = period_totals(actual)

    lines: list[LineVariance] = []
    if with_occupancy:
        lines.append(
            line_variance(
                line=Line.OCCUPANCY,
                budget=budget.occupancy,
                actual=actual.occupancy,
                unit=UnitOfMeasure.PERCENT,
            )
        )

    # Statement order, and every line built from the same two statements: an
    # authored line reads its own field, a derived line reads the totals that
    # were computed once above. No line is computed twice by two routes.
    for line, field in (
        (Line.RENTAL_REVENUE, "rental_revenue"),
        (Line.OTHER_INCOME, "other_income"),
    ):
        lines.append(
            line_variance(line=line, budget=getattr(budget, field), actual=getattr(actual, field))
        )
    lines.append(
        line_variance(
            line=Line.TOTAL_REVENUE,
            budget=budget_totals.total_revenue,
            actual=actual_totals.total_revenue,
        )
    )
    for field in OPERATING_EXPENSE_FIELDS:
        lines.append(
            line_variance(
                line=Line(field), budget=getattr(budget, field), actual=getattr(actual, field)
            )
        )
    lines.append(
        line_variance(
            line=Line.TOTAL_OPERATING_EXPENSES,
            budget=budget_totals.total_operating_expenses,
            actual=actual_totals.total_operating_expenses,
        )
    )
    lines.append(
        line_variance(
            line=Line.NET_OPERATING_INCOME,
            budget=budget_totals.net_operating_income,
            actual=actual_totals.net_operating_income,
        )
    )
    lines.append(
        line_variance(
            line=Line.CAPITAL_EXPENDITURES,
            budget=budget.capital_expenditures,
            actual=actual.capital_expenditures,
        )
    )
    lines.append(
        line_variance(
            line=Line.CASH_FLOW_AFTER_CAPEX,
            budget=budget_totals.cash_flow_after_capex,
            actual=actual_totals.cash_flow_after_capex,
        )
    )
    lines.append(
        line_variance(
            line=Line.DEBT_SERVICE, budget=budget.debt_service, actual=actual.debt_service
        )
    )
    lines.append(
        line_variance(
            line=Line.NET_CASH_FLOW,
            budget=budget_totals.net_cash_flow,
            actual=actual_totals.net_cash_flow,
        )
    )

    frozen = tuple(lines)
    return PeriodPerformance(
        budget=budget_totals,
        actual=actual_totals,
        lines=frozen,
        attention=attention_items(frozen),
    )


def analyze_month(report: MonthlyAssetReport) -> PeriodPerformance:
    """One month's comparison, budget against actual."""

    return _compare(budget=report.budget, actual=report.actual, with_occupancy=True)


def _sum_figures(statements: Sequence[OperatingFigures]) -> OperatingFigures:
    """The element-wise sum of several months' statements.

    ``occupancy`` is carried as ``0.0`` and never read: ``_compare`` is called
    with ``with_occupancy=False`` for a year to date, so no occupancy line is
    produced from it. The field exists because ``OperatingFigures`` is one
    contract for both a month and an aggregate; the zero is a placeholder that
    reaches no result, not a reported rate.
    """

    return OperatingFigures(
        occupancy=0.0,
        **{
            field: float(sum(getattr(statement, field) for statement in statements))
            for field in _YTD_SUMMED_FIELDS
        },
    )


def year_to_date_reports(
    reports: Iterable[MonthlyAssetReport], *, reporting_month: date
) -> tuple[MonthlyAssetReport, ...]:
    """Every saved report from January of ``reporting_month``'s year through
    ``reporting_month`` itself, in month order.

    A calendar-year window, inclusive of the selected month. A month with no
    saved report contributes nothing -- the year to date is the sum of what was
    actually reported, never a forecast of what was not.
    """

    return tuple(
        sorted(
            (
                report
                for report in reports
                if report.reporting_month.year == reporting_month.year
                and report.reporting_month <= reporting_month
            ),
            key=lambda report: report.reporting_month,
        )
    )


def noi_trend(reports: Sequence[MonthlyAssetReport]) -> tuple[NoiTrendPoint, ...]:
    """Budget and actual NOI for each supplied report, in month order."""

    return tuple(
        NoiTrendPoint(
            reporting_month=report.reporting_month,
            budget_net_operating_income=net_operating_income(report.budget),
            actual_net_operating_income=net_operating_income(report.actual),
        )
        for report in reports
    )


def analyze_asset_performance(
    *,
    managed_asset_id: str,
    reporting_month: date,
    reports: Iterable[MonthlyAssetReport],
) -> AssetPerformanceResult:
    """The authoritative AM1 result for one asset at one month.

    ``reports`` is every saved report for the asset; this function selects the
    selected month and the calendar-year window itself, so no caller has to
    decide what "year to date" means and two callers cannot decide differently.

    Raises ``KeyError`` if the selected month has no saved report -- there is no
    performance to report for a month that was never reported, and returning an
    empty comparison would present a fabricated all-zero budget as a plan.
    """

    saved = tuple(reports)
    selected = next(
        (report for report in saved if report.reporting_month == reporting_month), None
    )
    if selected is None:
        raise KeyError(reporting_month)

    window = year_to_date_reports(saved, reporting_month=reporting_month)
    ytd = _compare(
        budget=_sum_figures([report.budget for report in window]),
        actual=_sum_figures([report.actual for report in window]),
        with_occupancy=False,
    )
    return AssetPerformanceResult(
        managed_asset_id=managed_asset_id,
        reporting_month=reporting_month,
        monthly=analyze_month(selected),
        year_to_date=ytd,
        year_to_date_months=len(window),
        noi_trend=noi_trend(window),
        commentary=selected.commentary,
    )
