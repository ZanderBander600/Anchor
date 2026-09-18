"""Gate AM1 -- focused mutation proofs.

Protocol section 9: surgical, not ceremonial. Each case answers one question --
"if this invariant were removed or weakened, would a test fail?" -- for the
invariants AM1 exists to protect. Five mutants, all applied in memory to a copy
of the contract; nothing on disk is modified.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.asset_management import (
    Assessment,
    FinancialLine,
    UnitOfMeasure,
    VarianceDirection,
    analyze_asset_performance,
    analyze_month,
    noi_margin,
    variance_pct,
)
from anchor.asset_management import performance as perf

from _am1_fixtures import (  # type: ignore[import-not-found]
    MARCH,
    figures,
    line,
    report,
    zero_figures,
)


# =============================================================================
# 1. Expense favorability direction
# =============================================================================


def test_flipping_an_expense_direction_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """If Payroll became higher-is-favorable, overspending on it would read as
    good news. The assessment must change, and a test must see it."""

    healthy = analyze_month(
        report(budget=figures(), actual=figures(payroll=9_000.0))
    )
    assert line(healthy, "payroll").assessment is Assessment.UNFAVORABLE

    mutated = dict(perf._LINE_DIRECTION)
    mutated[FinancialLine.PAYROLL] = VarianceDirection.HIGHER_IS_FAVORABLE
    monkeypatch.setattr(perf, "_LINE_DIRECTION", mutated)

    poisoned = analyze_month(report(budget=figures(), actual=figures(payroll=9_000.0)))
    assert line(poisoned, "payroll").assessment is Assessment.FAVORABLE
    assert line(poisoned, "payroll").assessment is not line(healthy, "payroll").assessment


# =============================================================================
# 2. CapEx neutrality
# =============================================================================


def test_giving_capex_a_direction_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Underspending CapEx is deferred work, not a saving. If CapEx gained a
    direction, spending less than approved would be reported as favorable --
    exactly the inference AM1 forbids."""

    healthy = analyze_month(
        report(budget=figures(), actual=figures(capital_expenditures=1_000.0))
    )
    assert line(healthy, "capital_expenditures").assessment is Assessment.NEUTRAL
    assert all(item.line is not FinancialLine.CAPITAL_EXPENDITURES for item in healthy.attention)

    mutated = dict(perf._LINE_DIRECTION)
    mutated[FinancialLine.CAPITAL_EXPENDITURES] = VarianceDirection.LOWER_IS_FAVORABLE
    monkeypatch.setattr(perf, "_LINE_DIRECTION", mutated)

    poisoned = analyze_month(
        report(budget=figures(), actual=figures(capital_expenditures=1_000.0))
    )
    assert line(poisoned, "capital_expenditures").assessment is Assessment.FAVORABLE


# =============================================================================
# 3. Unavailable, never zero
# =============================================================================


def test_returning_zero_instead_of_unavailable_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero-budget line that reported `variance_pct = 0.0` would claim the
    actual landed exactly on a plan that does not exist."""

    assert variance_pct(variance=500.0, budget=0.0) is None

    monkeypatch.setattr(
        perf,
        "variance_pct",
        lambda *, variance, budget: 0.0 if budget == 0.0 else variance / abs(budget),
    )
    poisoned = analyze_month(
        report(budget=zero_figures(), actual=zero_figures(other_income=4_000.0))
    )
    assert line(poisoned, "other_income").variance_pct == 0.0


def test_a_zero_revenue_margin_of_zero_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero margin would assert the asset earned nothing on revenue it did
    earn. Unavailable is the truth."""

    empty = zero_figures(property_taxes=1_000.0)
    assert noi_margin(empty) is None

    monkeypatch.setattr(perf, "noi_margin", lambda figures: 0.0)
    assert perf.period_totals(empty).noi_margin == 0.0


# =============================================================================
# 4. Operating expenses exclude CapEx and debt service
# =============================================================================


def test_folding_capex_into_operating_expenses_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single most consequential way this contract could be got wrong: NOI
    would silently change, and every downstream figure with it."""

    healthy = analyze_month(report())
    assert healthy.budget.net_operating_income == 67_000.0

    monkeypatch.setattr(
        perf,
        "OPERATING_EXPENSE_FIELDS",
        (*perf.OPERATING_EXPENSE_FIELDS, "capital_expenditures"),
    )
    poisoned = analyze_month(report())
    assert poisoned.budget.net_operating_income == 57_000.0
    assert poisoned.budget.net_operating_income != healthy.budget.net_operating_income


# =============================================================================
# 5. Year to date never sums occupancy
# =============================================================================


def test_summing_occupancy_year_to_date_is_caught() -> None:
    """Three months at 95% is not 285% occupancy. The year-to-date line set
    omits occupancy entirely, and adding it back produces a figure no test
    would accept."""

    reports = tuple(
        report(reporting_month=date(2027, month, 1)) for month in (1, 2, 3)
    )
    result = analyze_asset_performance(
        managed_asset_id="asset-1", reporting_month=MARCH, reports=reports
    )
    assert all(item.line is not FinancialLine.OCCUPANCY for item in result.year_to_date.lines)

    # The mutant: compare the summed statements *with* occupancy, which is what
    # `with_occupancy=True` would do for a year to date.
    summed_budget = perf._sum_figures([item.budget for item in reports])
    poisoned = perf._compare(
        budget=dataclasses.replace(summed_budget, occupancy=3 * 0.95),
        actual=dataclasses.replace(
            perf._sum_figures([item.actual for item in reports]), occupancy=3 * 0.925
        ),
        with_occupancy=True,
    )
    occupancy = [item for item in poisoned.lines if item.line is FinancialLine.OCCUPANCY]
    assert len(occupancy) == 1
    # 285% -- self-evidently not an occupancy rate, which is why AM1 does not
    # report one.
    assert occupancy[0].budget == pytest.approx(2.85)
    assert occupancy[0].unit is UnitOfMeasure.PERCENT


# =============================================================================
# 6. The frozen budget
# =============================================================================


def test_removing_the_budget_comparison_would_let_a_budget_change_through(
    tmp_path,
) -> None:
    """The store's conflict check is what stands between an echoed budget and a
    silent revision. With it removed, the differing budget would simply be
    ignored -- so the check must be the thing that raises."""

    from anchor.asset_management import BudgetImmutableError
    from anchor.deals import store

    import _am1_fixtures as am  # type: ignore[import-not-found]
    import _p7_2_fixtures as fx  # type: ignore[import-not-found]

    db = tmp_path / "mutation.db"
    deal = fx.create_deal("quick", db, name="Mutation")
    store.update_analysis_snapshot(
        deal.id,
        dataclasses.asdict(fx.analyze_deal(deal)),
        financial_input_fingerprint=fx.deal_fingerprint(deal),
        db_path=db,
    )
    asset = store.create_managed_asset(
        source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db
    )
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )

    with pytest.raises(BudgetImmutableError):
        store.update_monthly_report_actuals(
            managed_asset_id=asset.id,
            reporting_month=MARCH,
            actual=am.MARCH_ACTUAL,
            budget=am.figures(payroll=99_000.0),
            db_path=db,
        )

    # And the budget on disk is untouched either way: even if the check were
    # removed, no SQL in the update path names a budget column.
    assert store.get_monthly_report(asset.id, MARCH, db_path=db).budget == am.MARCH_BUDGET
