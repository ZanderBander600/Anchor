"""Gate AM1 -- the deterministic monthly performance calculations.

``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`` Section 4. The
financial identities, the two unavailable values, the favorability directions
and the year-to-date aggregation, proved directly against
``anchor.asset_management.performance``.
"""

from __future__ import annotations

from datetime import date

import pytest

from anchor.asset_management import (
    Assessment,
    FinancialLine,
    UnitOfMeasure,
    VarianceDirection,
    analyze_asset_performance,
    analyze_month,
    cash_flow_after_capex,
    net_cash_flow,
    net_operating_income,
    noi_margin,
    period_totals,
    total_operating_expenses,
    total_revenue,
    variance_pct,
    year_to_date_reports,
)

from _am1_fixtures import (  # type: ignore[import-not-found]
    MARCH,
    MARCH_ACTUAL,
    MARCH_BUDGET,
    MARCH_COMMENTARY,
    figures,
    line,
    report,
    zero_figures,
)


# =============================================================================
# The authorized demo case, figure for figure
# =============================================================================


def test_demo_case_reproduces_every_authorized_figure() -> None:
    """Section 9's expected results, which are the gate's acceptance numbers."""

    monthly = analyze_month(report())

    assert monthly.budget.total_revenue == 105_000.0
    assert monthly.actual.total_revenue == 102_500.0
    assert monthly.budget.total_operating_expenses == 38_000.0
    assert monthly.actual.total_operating_expenses == 41_000.0
    assert monthly.budget.net_operating_income == 67_000.0
    assert monthly.actual.net_operating_income == 61_500.0
    assert monthly.budget.net_cash_flow == 24_500.0
    assert monthly.actual.net_cash_flow == 19_000.0

    noi = line(monthly, "net_operating_income")
    assert noi.variance == -5_500.0
    assert noi.variance_pct == pytest.approx(-0.0820895, abs=1e-6)
    assert noi.assessment is Assessment.UNFAVORABLE

    occupancy = line(monthly, "occupancy")
    assert occupancy.variance_points == pytest.approx(-2.5, abs=1e-9)
    assert occupancy.unit is UnitOfMeasure.PERCENT
    assert occupancy.assessment is Assessment.UNFAVORABLE


# =============================================================================
# Financial identities
# =============================================================================


def test_totals_satisfy_every_authorized_identity() -> None:
    """The five totals are exactly their definitions, on both statements."""

    for statement in (MARCH_BUDGET, MARCH_ACTUAL):
        assert total_revenue(statement) == (
            statement.rental_revenue + statement.other_income
        )
        assert total_operating_expenses(statement) == (
            statement.property_taxes
            + statement.insurance
            + statement.utilities
            + statement.repairs_and_maintenance
            + statement.payroll
            + statement.management_fees
            + statement.other_operating_expenses
        )
        assert net_operating_income(statement) == (
            total_revenue(statement) - total_operating_expenses(statement)
        )
        assert cash_flow_after_capex(statement) == (
            net_operating_income(statement) - statement.capital_expenditures
        )
        assert net_cash_flow(statement) == (
            cash_flow_after_capex(statement) - statement.debt_service
        )


def test_operating_expenses_exclude_capex_and_debt_service() -> None:
    """Neither is an operating expense. If either were summed into the total,
    NOI would silently change -- the single most consequential way this contract
    could be got wrong."""

    base = total_operating_expenses(MARCH_BUDGET)
    assert total_operating_expenses(figures(capital_expenditures=999_999.0)) == base
    assert total_operating_expenses(figures(debt_service=999_999.0)) == base
    assert net_operating_income(figures(capital_expenditures=999_999.0)) == (
        net_operating_income(MARCH_BUDGET)
    )


def test_noi_margin_is_noi_over_total_revenue() -> None:
    assert noi_margin(MARCH_BUDGET) == pytest.approx(67_000.0 / 105_000.0)


# =============================================================================
# Unavailable, never zero and never infinite
# =============================================================================


def test_noi_margin_is_unavailable_when_revenue_is_zero() -> None:
    """Unavailable is `None`. Zero would assert the asset earned nothing on
    revenue it did earn, and an infinity would reach presentation as a
    number."""

    empty = zero_figures(property_taxes=1_000.0)
    assert total_revenue(empty) == 0.0
    assert noi_margin(empty) is None
    assert period_totals(empty).noi_margin is None


def test_variance_pct_is_unavailable_when_budget_is_zero() -> None:
    assert variance_pct(variance=500.0, budget=0.0) is None
    assert variance_pct(variance=0.0, budget=0.0) is None


def test_zero_budget_line_reports_variance_but_not_a_percentage() -> None:
    """The difference is well defined even when the ratio is not, so the
    variance is present and only the percentage is withheld."""

    monthly = analyze_month(
        report(budget=zero_figures(), actual=zero_figures(other_income=4_000.0))
    )
    other_income = line(monthly, "other_income")
    assert other_income.budget == 0.0
    assert other_income.variance == 4_000.0
    assert other_income.variance_pct is None
    assert other_income.assessment is Assessment.FAVORABLE


def test_variance_pct_uses_the_budget_magnitude() -> None:
    """Dividing by a signed budget would flip the reported sign when the budget
    itself was negative, making a favorable result read as unfavorable."""

    assert variance_pct(variance=-50.0, budget=-200.0) == -0.25


# =============================================================================
# Favorability direction
# =============================================================================


def test_revenue_occupancy_noi_and_net_cash_flow_are_higher_is_favorable() -> None:
    monthly = analyze_month(
        report(
            budget=figures(),
            actual=figures(occupancy=0.98, rental_revenue=110_000.0),
        )
    )
    for token in ("occupancy", "rental_revenue", "total_revenue", "net_operating_income", "net_cash_flow"):
        item = line(monthly, token)
        assert item.direction is VarianceDirection.HIGHER_IS_FAVORABLE, token
        assert item.assessment is Assessment.FAVORABLE, token


def test_every_operating_expense_line_is_lower_is_favorable() -> None:
    """Overspending is unfavorable and underspending is favorable, on each of
    the seven lines and on their total."""

    for token in (
        "property_taxes",
        "insurance",
        "utilities",
        "repairs_and_maintenance",
        "payroll",
        "management_fees",
        "other_operating_expenses",
    ):
        over = analyze_month(
            report(budget=figures(), actual=figures(**{token: getattr(MARCH_BUDGET, token) + 1_000.0}))
        )
        assert line(over, token).direction is VarianceDirection.LOWER_IS_FAVORABLE, token
        assert line(over, token).assessment is Assessment.UNFAVORABLE, token
        assert line(over, "total_operating_expenses").assessment is Assessment.UNFAVORABLE

        under = analyze_month(
            report(budget=figures(), actual=figures(**{token: getattr(MARCH_BUDGET, token) - 1_000.0}))
        )
        assert line(under, token).assessment is Assessment.FAVORABLE, token
        assert line(under, "total_operating_expenses").assessment is Assessment.FAVORABLE


def test_capex_and_debt_service_are_always_neutral() -> None:
    """Under, over or exactly on plan. Underspending CapEx is deferred work,
    not a saving, and AM1 never infers that lower CapEx is favorable."""

    for token in ("capital_expenditures", "debt_service"):
        for delta in (-5_000.0, 0.0, 5_000.0):
            monthly = analyze_month(
                report(
                    budget=figures(),
                    actual=figures(**{token: getattr(MARCH_BUDGET, token) + delta}),
                )
            )
            item = line(monthly, token)
            assert item.direction is VarianceDirection.NO_DIRECTION, (token, delta)
            assert item.assessment is Assessment.NEUTRAL, (token, delta)


def test_cash_flow_after_capex_is_neutral_because_it_embeds_capex() -> None:
    """Giving the subtotal a direction would launder a neutral line into a
    verdict. Net cash flow is explicitly authorized as directional and keeps
    it."""

    monthly = analyze_month(report())
    assert line(monthly, "cash_flow_after_capex").assessment is Assessment.NEUTRAL
    assert line(monthly, "net_cash_flow").direction is VarianceDirection.HIGHER_IS_FAVORABLE


def test_a_directional_line_exactly_on_plan_reads_on_plan() -> None:
    monthly = analyze_month(report(budget=figures(), actual=figures()))
    assert line(monthly, "rental_revenue").assessment is Assessment.ON_PLAN
    assert line(monthly, "net_operating_income").assessment is Assessment.ON_PLAN
    # A neutral line never becomes on-plan: on-plan is a judgement about a
    # target, and a neutral line has no direction toward one.
    assert line(monthly, "capital_expenditures").assessment is Assessment.NEUTRAL


# =============================================================================
# Attention items
# =============================================================================


def test_attention_items_are_exactly_the_unfavorable_lines() -> None:
    monthly = analyze_month(report())
    unfavorable = {
        item.line for item in monthly.lines if item.assessment is Assessment.UNFAVORABLE
    }
    assert {item.line for item in monthly.attention} == unfavorable
    assert all(item.assessment is Assessment.UNFAVORABLE for item in monthly.attention)


def test_attention_items_state_the_direction_in_words() -> None:
    """Words, not color: each message is complete to a reader who cannot
    distinguish red from green."""

    messages = [item.message for item in analyze_month(report()).attention]
    assert "Occupancy is 2.5 pts below plan" in messages
    assert "Repairs and Maintenance is $2,000 over budget" in messages
    assert "Net Operating Income is 8.2% below plan" in messages


def test_a_month_entirely_on_plan_raises_no_attention_item() -> None:
    monthly = analyze_month(report(budget=figures(), actual=figures()))
    assert monthly.attention == ()


def test_neutral_lines_never_become_attention_items() -> None:
    monthly = analyze_month(
        report(budget=figures(), actual=figures(capital_expenditures=90_000.0))
    )
    assert all(item.line is not FinancialLine.CAPITAL_EXPENDITURES for item in monthly.attention)


# =============================================================================
# Year to date
# =============================================================================


def _january_through_march() -> tuple:
    return (
        report(reporting_month=date(2027, 1, 1), budget=figures(), actual=figures(rental_revenue=90_000.0)),
        report(reporting_month=date(2027, 2, 1), budget=figures(), actual=figures(rental_revenue=95_000.0)),
        report(reporting_month=MARCH),
    )


def test_year_to_date_sums_january_through_the_selected_month() -> None:
    result = analyze_asset_performance(
        managed_asset_id="asset-1", reporting_month=MARCH, reports=_january_through_march()
    )
    assert result.year_to_date_months == 3
    assert result.year_to_date.budget.total_revenue == 3 * 105_000.0
    assert result.year_to_date.actual.total_revenue == (
        (90_000.0 + 5_000.0) + (95_000.0 + 5_000.0) + 102_500.0
    )


def test_year_to_date_excludes_later_months_and_other_years() -> None:
    reports = (
        *_january_through_march(),
        report(reporting_month=date(2027, 4, 1)),
        report(reporting_month=date(2026, 12, 1)),
    )
    result = analyze_asset_performance(
        managed_asset_id="asset-1", reporting_month=MARCH, reports=reports
    )
    assert result.year_to_date_months == 3
    assert [point.reporting_month for point in result.noi_trend] == [
        date(2027, 1, 1),
        date(2027, 2, 1),
        date(2027, 3, 1),
    ]


def test_year_to_date_reports_no_occupancy_line() -> None:
    """A sum of occupancy rates is not a fact, so rather than reporting a
    meaningless number the year-to-date line set omits occupancy entirely."""

    result = analyze_asset_performance(
        managed_asset_id="asset-1", reporting_month=MARCH, reports=_january_through_march()
    )
    assert all(item.line is not FinancialLine.OCCUPANCY for item in result.year_to_date.lines)
    assert any(item.line is FinancialLine.OCCUPANCY for item in result.monthly.lines)


def test_year_to_date_counts_only_months_that_were_actually_reported() -> None:
    """A month with no saved report contributes nothing; it is never a zero
    month that would read as an asset earning nothing."""

    reports = (
        report(reporting_month=date(2027, 1, 1)),
        report(reporting_month=MARCH),
    )
    result = analyze_asset_performance(
        managed_asset_id="asset-1", reporting_month=MARCH, reports=reports
    )
    assert result.year_to_date_months == 2
    assert result.year_to_date.budget.total_revenue == 2 * 105_000.0


def test_noi_trend_carries_budget_and_actual_noi_per_reported_month() -> None:
    result = analyze_asset_performance(
        managed_asset_id="asset-1", reporting_month=MARCH, reports=_january_through_march()
    )
    assert result.noi_trend[-1].budget_net_operating_income == 67_000.0
    assert result.noi_trend[-1].actual_net_operating_income == 61_500.0


def test_year_to_date_window_is_month_ordered_regardless_of_input_order() -> None:
    shuffled = tuple(reversed(_january_through_march()))
    window = year_to_date_reports(shuffled, reporting_month=MARCH)
    assert [item.reporting_month for item in window] == [
        date(2027, 1, 1),
        date(2027, 2, 1),
        date(2027, 3, 1),
    ]


# =============================================================================
# Negative paths
# =============================================================================


def test_a_month_with_no_saved_report_refuses_rather_than_fabricating_a_plan() -> None:
    """Returning an empty comparison would present an all-zero budget as an
    approved plan."""

    with pytest.raises(KeyError):
        analyze_asset_performance(
            managed_asset_id="asset-1", reporting_month=date(2027, 7, 1), reports=(report(),)
        )


def test_the_result_carries_the_selected_month_commentary() -> None:
    result = analyze_asset_performance(
        managed_asset_id="asset-1", reporting_month=MARCH, reports=_january_through_march()
    )
    assert result.commentary == MARCH_COMMENTARY
    assert result.reporting_month == MARCH
    assert result.managed_asset_id == "asset-1"
