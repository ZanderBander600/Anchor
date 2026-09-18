"""Gate AM1 -- structural validation of a Managed Asset and its monthly report.

Restates ``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md``
Section 3 (authorized); that document governs on any discrepancy. Pure: no I/O,
no clock, no randomness, and no knowledge of storage or routes. It performs no
financial arithmetic -- range checks only.

Nothing here repairs, coerces, reorders or defaults a value. A figure that is
not a finite non-negative number is refused, never clamped to zero: a clamp
would put a number the analyst never entered into a frozen budget.

Issue order is deterministic and never depends on dict iteration or caller
order: for a report, the reporting month, then the budget's fields in
``MONETARY_FIELDS`` statement order (occupancy first), then the actual's, then
commentary.
"""

from __future__ import annotations

from datetime import date
from math import isfinite

from .contracts import (
    MONETARY_FIELDS,
    AssetReportIssue,
    AssetReportIssueCode,
    AssetReportValidationError,
    OperatingFigures,
)

Code = AssetReportIssueCode

#: The longest commentary accepted. Commentary is a management note, not a
#: document store; a ceiling keeps one report from becoming an unbounded blob in
#: a TEXT column. Generous enough that no realistic note reaches it.
MAX_COMMENTARY_LENGTH = 4000

#: The longest free-text identity field (asset name, property type, market).
MAX_NAME_LENGTH = 200


def _is_number(value: object) -> bool:
    """A finite ``int`` or ``float``. ``bool`` is not a number here -- ``True``
    is not one dollar, and letting it through would make a checkbox a
    figure."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(float(value))
    except OverflowError:
        return False


def _is_text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def parse_iso_date(raw: object) -> date | None:
    """``raw`` as a calendar date, or ``None`` if it is not one.

    Returns rather than raises, deliberately. ``date.fromisoformat`` signals a
    malformed string with ``ValueError``, and every validation error in this
    repository subclasses ``ValueError`` -- so a ``try/except ValueError`` at the
    transport boundary is one refactor away from silently converting a typed
    domain refusal into a generic "bad date" message. Keeping the catch here,
    around a single call that can raise nothing else, means the boundary never
    needs one at all.
    """

    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def normalize_reporting_month(value: date) -> date:
    """The first day of ``value``'s month.

    The single normalization in AM1, applied at every boundary that accepts a
    month so ``2027-03-01`` and ``2027-03-31`` are one reporting month with one
    report, never two rows that would each freeze a different budget.
    """

    return value.replace(day=1)


def validate_figures(figures: object, *, scope: str) -> tuple[AssetReportIssue, ...]:
    """Every structural issue in one statement, in statement order.

    ``scope`` is carried onto each issue (``"budget"`` / ``"actual"``) so a
    refusal names which of the two failed -- the budget and the actual have
    identical field names, and an unscoped message could not tell them apart.
    """

    if not isinstance(figures, OperatingFigures):
        return (
            AssetReportIssue(
                code=Code.INVALID_FIGURES,
                message=f"The {scope} figures are missing or not an operating statement.",
                scope=scope,
                field=None,
            ),
        )

    issues: list[AssetReportIssue] = []

    occupancy = figures.occupancy
    if not _is_number(occupancy) or not 0.0 <= float(occupancy) <= 1.0:
        issues.append(
            AssetReportIssue(
                code=Code.INVALID_OCCUPANCY,
                message=(
                    f"The {scope} occupancy must be a percentage between 0% and 100%."
                ),
                scope=scope,
                field="occupancy",
            )
        )

    for field in MONETARY_FIELDS:
        amount = getattr(figures, field)
        if not _is_number(amount):
            issues.append(
                AssetReportIssue(
                    code=Code.INVALID_AMOUNT,
                    message=f"The {scope} {field.replace('_', ' ')} must be an amount.",
                    scope=scope,
                    field=field,
                )
            )
        elif float(amount) < 0.0:
            issues.append(
                AssetReportIssue(
                    code=Code.NEGATIVE_AMOUNT,
                    message=(
                        f"The {scope} {field.replace('_', ' ')} cannot be negative."
                    ),
                    scope=scope,
                    field=field,
                )
            )

    return tuple(issues)


def validate_commentary(commentary: object) -> tuple[AssetReportIssue, ...]:
    """Commentary is optional. ``None`` is "none written"; a string that is only
    whitespace is refused rather than stored, because a report that claims to
    carry a note and carries nothing is worse than one that carries none."""

    if commentary is None:
        return ()
    if not isinstance(commentary, str):
        return (
            AssetReportIssue(
                code=Code.INVALID_COMMENTARY,
                message="Management commentary must be text.",
                scope=None,
                field="commentary",
            ),
        )
    if commentary.strip() == "":
        return (
            AssetReportIssue(
                code=Code.INVALID_COMMENTARY,
                message="Management commentary cannot be blank. Leave it out instead.",
                scope=None,
                field="commentary",
            ),
        )
    if len(commentary) > MAX_COMMENTARY_LENGTH:
        return (
            AssetReportIssue(
                code=Code.INVALID_COMMENTARY,
                message=(
                    f"Management commentary is limited to {MAX_COMMENTARY_LENGTH} characters."
                ),
                scope=None,
                field="commentary",
            ),
        )
    return ()


def validate_monthly_report(
    *,
    reporting_month: object,
    budget: object,
    actual: object,
    commentary: object,
) -> tuple[AssetReportIssue, ...]:
    """Every structural issue in one monthly report, in deterministic order."""

    issues: list[AssetReportIssue] = []
    if not isinstance(reporting_month, date):
        issues.append(
            AssetReportIssue(
                code=Code.INVALID_REPORTING_MONTH,
                message="The reporting month must be a calendar month.",
                scope=None,
                field="reporting_month",
            )
        )
    issues.extend(validate_figures(budget, scope="budget"))
    issues.extend(validate_figures(actual, scope="actual"))
    issues.extend(validate_commentary(commentary))
    return tuple(issues)


def require_valid_monthly_report(
    *,
    reporting_month: object,
    budget: object,
    actual: object,
    commentary: object,
) -> None:
    """Raise ``AssetReportValidationError`` if the report is structurally
    invalid; return ``None`` otherwise. The one call site every write path uses,
    so no path can accept a report another path would refuse."""

    issues = validate_monthly_report(
        reporting_month=reporting_month,
        budget=budget,
        actual=actual,
        commentary=commentary,
    )
    if issues:
        raise AssetReportValidationError(issues)


def validate_managed_asset(
    *,
    name: object,
    acquisition_date: object,
    property_type: object,
    market: object,
) -> tuple[AssetReportIssue, ...]:
    """Every structural issue in a Managed Asset's authored identity.

    The fingerprint and the source Deal id are deliberately not validated here:
    neither is authored by the analyst. Both are captured by the store from the
    Deal itself, so there is no untrusted value to check.
    """

    issues: list[AssetReportIssue] = []
    if not _is_text(name):
        issues.append(
            AssetReportIssue(
                code=Code.INVALID_ASSET_NAME,
                message="The managed asset needs a name.",
                scope=None,
                field="name",
            )
        )
    elif len(name) > MAX_NAME_LENGTH:  # type: ignore[arg-type]
        issues.append(
            AssetReportIssue(
                code=Code.INVALID_ASSET_NAME,
                message=f"The managed asset name is limited to {MAX_NAME_LENGTH} characters.",
                scope=None,
                field="name",
            )
        )
    if not isinstance(acquisition_date, date):
        issues.append(
            AssetReportIssue(
                code=Code.INVALID_ACQUISITION_DATE,
                message="The acquisition date must be a calendar date.",
                scope=None,
                field="acquisition_date",
            )
        )
    for value, field, code in (
        (property_type, "property_type", Code.INVALID_PROPERTY_TYPE),
        (market, "market", Code.INVALID_MARKET),
    ):
        # Optional: absent is stated by `None`. A blank string is refused rather
        # than folded into `None`, so "not stated" has exactly one spelling and
        # the store never has to guess which the analyst meant.
        if value is None:
            continue
        if not _is_text(value) or len(value) > MAX_NAME_LENGTH:  # type: ignore[arg-type]
            issues.append(
                AssetReportIssue(
                    code=code,
                    message=(
                        f"The {field.replace('_', ' ')} must be text of at most "
                        f"{MAX_NAME_LENGTH} characters, or left out."
                    ),
                    scope=None,
                    field=field,
                )
            )
    return tuple(issues)


def require_valid_managed_asset(
    *,
    name: object,
    acquisition_date: object,
    property_type: object,
    market: object,
) -> None:
    """Raise ``AssetReportValidationError`` if the asset's identity is
    structurally invalid; return ``None`` otherwise."""

    issues = validate_managed_asset(
        name=name,
        acquisition_date=acquisition_date,
        property_type=property_type,
        market=market,
    )
    if issues:
        raise AssetReportValidationError(issues)
