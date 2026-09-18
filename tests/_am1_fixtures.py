"""Gate AM1 -- shared test fixtures.

The authorized demo case (``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md``
Section 9) and the small builders every AM1 test reuses, so one set of figures
proves the engine, the store, the API and the architecture guards rather than
four hand-copied variants that could drift apart.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from anchor.asset_management import MonthlyAssetReport, OperatingFigures

#: The authorized March 2027 approved budget.
MARCH_BUDGET = OperatingFigures(
    occupancy=0.95,
    rental_revenue=100_000.0,
    other_income=5_000.0,
    property_taxes=10_000.0,
    insurance=5_000.0,
    utilities=5_000.0,
    repairs_and_maintenance=6_000.0,
    payroll=6_000.0,
    management_fees=4_000.0,
    other_operating_expenses=2_000.0,
    capital_expenditures=10_000.0,
    debt_service=32_500.0,
)

#: The authorized March 2027 actual results.
MARCH_ACTUAL = OperatingFigures(
    occupancy=0.925,
    rental_revenue=96_000.0,
    other_income=6_500.0,
    property_taxes=10_000.0,
    insurance=5_000.0,
    utilities=6_000.0,
    repairs_and_maintenance=8_000.0,
    payroll=6_000.0,
    management_fees=4_000.0,
    other_operating_expenses=2_000.0,
    capital_expenditures=10_000.0,
    debt_service=32_500.0,
)

MARCH_COMMENTARY = (
    "Two renewals moved into April. Repairs were elevated by an unplanned "
    "HVAC replacement."
)

MARCH = date(2027, 3, 1)


def figures(**overrides: float) -> OperatingFigures:
    """The approved budget with named fields replaced. Keeps a test's intent
    visible: only the fields a case is actually about appear in it."""

    base = {
        field: getattr(MARCH_BUDGET, field)
        for field in (
            "occupancy",
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
    }
    base.update(overrides)
    return OperatingFigures(**base)  # type: ignore[arg-type]


def zero_figures(**overrides: float) -> OperatingFigures:
    """Every field zero except the ones named. The zero-budget cases need a
    statement that is genuinely empty, not one that is merely small."""

    base = {
        field: 0.0
        for field in (
            "occupancy",
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
    }
    base.update(overrides)
    return OperatingFigures(**base)  # type: ignore[arg-type]


def report(
    *,
    reporting_month: date = MARCH,
    budget: OperatingFigures = MARCH_BUDGET,
    actual: OperatingFigures = MARCH_ACTUAL,
    commentary: str | None = MARCH_COMMENTARY,
    managed_asset_id: str = "asset-1",
) -> MonthlyAssetReport:
    """One saved monthly report. Timestamps are fixed rather than read from the
    clock so a result never depends on when the test ran."""

    stamp = datetime(2027, 3, 31, 12, 0, tzinfo=timezone.utc)
    return MonthlyAssetReport(
        managed_asset_id=managed_asset_id,
        reporting_month=reporting_month,
        budget=budget,
        actual=actual,
        commentary=commentary,
        created_at=stamp,
        updated_at=stamp,
    )


def line(performance, token: str):
    """The one ``LineVariance`` for ``token`` in a period's lines."""

    matches = [item for item in performance.lines if item.line.value == token]
    assert len(matches) == 1, f"expected exactly one {token!r} line, got {len(matches)}"
    return matches[0]
