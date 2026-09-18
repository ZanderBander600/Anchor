"""Gate AM1 -- structural validation and the typed frozen-budget conflict.

``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`` Section 3. The
negative paths: what a monthly report refuses, what it never repairs, and why a
budget conflict is not a validation failure.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from anchor.asset_management import (
    MAX_COMMENTARY_LENGTH,
    MONETARY_FIELDS,
    AssetReportIssueCode,
    AssetReportValidationError,
    BudgetImmutableError,
    normalize_reporting_month,
    require_valid_managed_asset,
    require_valid_monthly_report,
    validate_figures,
    validate_managed_asset,
    validate_monthly_report,
)

from _am1_fixtures import (  # type: ignore[import-not-found]
    MARCH,
    MARCH_ACTUAL,
    MARCH_BUDGET,
    MARCH_COMMENTARY,
    figures,
)


def _codes(issues) -> list[str]:
    return [issue.code.value for issue in issues]


# =============================================================================
# The valid case
# =============================================================================


def test_the_authorized_demo_report_is_valid() -> None:
    assert (
        validate_monthly_report(
            reporting_month=MARCH,
            budget=MARCH_BUDGET,
            actual=MARCH_ACTUAL,
            commentary=MARCH_COMMENTARY,
        )
        == ()
    )


def test_commentary_is_optional() -> None:
    assert (
        validate_monthly_report(
            reporting_month=MARCH, budget=MARCH_BUDGET, actual=MARCH_ACTUAL, commentary=None
        )
        == ()
    )


# =============================================================================
# Monetary fields: finite and non-negative
# =============================================================================


@pytest.mark.parametrize("field", MONETARY_FIELDS)
def test_every_monetary_field_refuses_a_negative_amount(field: str) -> None:
    issues = validate_figures(figures(**{field: -1.0}), scope="budget")
    assert _codes(issues) == [AssetReportIssueCode.NEGATIVE_AMOUNT.value]
    assert issues[0].field == field
    assert issues[0].scope == "budget"


@pytest.mark.parametrize("field", MONETARY_FIELDS)
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_every_monetary_field_refuses_a_non_finite_amount(field: str, bad: float) -> None:
    issues = validate_figures(figures(**{field: bad}), scope="actual")
    assert _codes(issues) == [AssetReportIssueCode.INVALID_AMOUNT.value]
    assert issues[0].field == field


def test_a_boolean_is_not_an_amount() -> None:
    """`True` is not one dollar. Letting it through would make a checkbox a
    figure."""

    issues = validate_figures(figures(payroll=True), scope="budget")  # type: ignore[arg-type]
    assert _codes(issues) == [AssetReportIssueCode.INVALID_AMOUNT.value]


def test_zero_is_a_valid_amount() -> None:
    assert validate_figures(figures(capital_expenditures=0.0), scope="budget") == ()


def test_nothing_is_repaired_or_clamped() -> None:
    """A clamp would put a number the analyst never entered into a frozen
    budget, so an invalid figure is refused instead."""

    bad = figures(payroll=-5.0)
    validate_figures(bad, scope="budget")
    assert bad.payroll == -5.0


# =============================================================================
# Occupancy
# =============================================================================


@pytest.mark.parametrize("bad", [-0.01, 1.01, 95.0, math.nan, math.inf])
def test_occupancy_outside_zero_to_one_hundred_percent_is_refused(bad: float) -> None:
    """Occupancy is a fraction on the repository's existing convention, so 95.0
    is out of range -- 95% is 0.95."""

    issues = validate_figures(figures(occupancy=bad), scope="budget")
    assert _codes(issues) == [AssetReportIssueCode.INVALID_OCCUPANCY.value]
    assert issues[0].field == "occupancy"


@pytest.mark.parametrize("ok", [0.0, 0.5, 0.925, 1.0])
def test_occupancy_at_and_between_the_bounds_is_accepted(ok: float) -> None:
    assert validate_figures(figures(occupancy=ok), scope="budget") == ()


# =============================================================================
# Reporting month and commentary
# =============================================================================


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (date(2027, 3, 1), date(2027, 3, 1)),
        (date(2027, 3, 31), date(2027, 3, 1)),
        (date(2027, 3, 17), date(2027, 3, 1)),
        (date(2027, 12, 31), date(2027, 12, 1)),
    ],
)
def test_the_reporting_month_normalizes_to_the_first_of_the_month(
    given: date, expected: date
) -> None:
    """Two spellings of one month can never become two rows that would each
    freeze a different budget."""

    assert normalize_reporting_month(given) == expected


def test_a_reporting_month_that_is_not_a_date_is_refused() -> None:
    issues = validate_monthly_report(
        reporting_month="2027-03", budget=MARCH_BUDGET, actual=MARCH_ACTUAL, commentary=None
    )
    assert _codes(issues) == [AssetReportIssueCode.INVALID_REPORTING_MONTH.value]


def test_blank_commentary_is_refused_rather_than_stored() -> None:
    """A report that claims to carry a note and carries nothing is worse than
    one that carries none."""

    issues = validate_monthly_report(
        reporting_month=MARCH, budget=MARCH_BUDGET, actual=MARCH_ACTUAL, commentary="   "
    )
    assert _codes(issues) == [AssetReportIssueCode.INVALID_COMMENTARY.value]


def test_commentary_beyond_the_ceiling_is_refused() -> None:
    issues = validate_monthly_report(
        reporting_month=MARCH,
        budget=MARCH_BUDGET,
        actual=MARCH_ACTUAL,
        commentary="x" * (MAX_COMMENTARY_LENGTH + 1),
    )
    assert _codes(issues) == [AssetReportIssueCode.INVALID_COMMENTARY.value]


# =============================================================================
# Reporting every issue, in a deterministic order
# =============================================================================


def test_every_issue_is_reported_in_one_round_trip() -> None:
    """Never only the first: one submission reports every field the analyst
    must fix."""

    issues = validate_monthly_report(
        reporting_month=MARCH,
        budget=figures(payroll=-1.0, insurance=-1.0),
        actual=figures(occupancy=2.0),
        commentary="",
    )
    assert _codes(issues) == [
        AssetReportIssueCode.NEGATIVE_AMOUNT.value,
        AssetReportIssueCode.NEGATIVE_AMOUNT.value,
        AssetReportIssueCode.INVALID_OCCUPANCY.value,
        AssetReportIssueCode.INVALID_COMMENTARY.value,
    ]
    assert [issue.scope for issue in issues] == ["budget", "budget", "actual", None]


def test_issue_order_follows_the_statement_not_the_caller() -> None:
    """Insurance precedes payroll in statement order, whichever was set
    first."""

    issues = validate_figures(figures(payroll=-1.0, insurance=-1.0), scope="budget")
    assert [issue.field for issue in issues] == ["insurance", "payroll"]


def test_the_budget_and_the_actual_are_told_apart() -> None:
    """They have identical field names; an unscoped message could not say which
    statement failed."""

    issues = validate_monthly_report(
        reporting_month=MARCH,
        budget=MARCH_BUDGET,
        actual=figures(utilities=-1.0),
        commentary=None,
    )
    assert [issue.scope for issue in issues] == ["actual"]


def test_require_valid_monthly_report_raises_with_every_issue() -> None:
    with pytest.raises(AssetReportValidationError) as raised:
        require_valid_monthly_report(
            reporting_month=MARCH,
            budget=figures(payroll=-1.0),
            actual=figures(occupancy=5.0),
            commentary=None,
        )
    assert len(raised.value.issues) == 2


# =============================================================================
# Managed Asset identity
# =============================================================================


def test_a_managed_asset_needs_a_name_and_an_acquisition_date() -> None:
    issues = validate_managed_asset(
        name="  ", acquisition_date="2026-10-01", property_type=None, market=None
    )
    assert _codes(issues) == [
        AssetReportIssueCode.INVALID_ASSET_NAME.value,
        AssetReportIssueCode.INVALID_ACQUISITION_DATE.value,
    ]


def test_property_type_and_market_are_optional_but_never_blank() -> None:
    """"Not stated" has exactly one spelling, so the store never has to guess
    which the analyst meant."""

    assert (
        validate_managed_asset(
            name="Harbor Point Apartments",
            acquisition_date=date(2026, 10, 1),
            property_type=None,
            market=None,
        )
        == ()
    )
    issues = validate_managed_asset(
        name="Harbor Point Apartments",
        acquisition_date=date(2026, 10, 1),
        property_type="   ",
        market="",
    )
    assert _codes(issues) == [
        AssetReportIssueCode.INVALID_PROPERTY_TYPE.value,
        AssetReportIssueCode.INVALID_MARKET.value,
    ]


def test_require_valid_managed_asset_accepts_the_demo_asset() -> None:
    require_valid_managed_asset(
        name="Harbor Point Apartments",
        acquisition_date=date(2026, 10, 1),
        property_type="Multifamily",
        market="Toronto, ON",
    )


# =============================================================================
# The frozen-budget conflict is not a validation failure
# =============================================================================


def test_budget_immutable_error_is_not_a_validation_error() -> None:
    """The submitted budget may be perfectly well-formed. The refusal is about
    authority, not shape, and the product must be able to tell the two apart."""

    error = BudgetImmutableError(
        managed_asset_id="asset-1", reporting_month=MARCH, changed_fields=("payroll",)
    )
    assert not isinstance(error, AssetReportValidationError)
    assert not isinstance(error, ValueError)


def test_budget_immutable_error_names_every_changed_field() -> None:
    error = BudgetImmutableError(
        managed_asset_id="asset-1",
        reporting_month=MARCH,
        changed_fields=("insurance", "payroll"),
    )
    assert error.changed_fields == ("insurance", "payroll")
    assert "insurance" in str(error)
    assert "payroll" in str(error)
    assert error.reporting_month == MARCH
