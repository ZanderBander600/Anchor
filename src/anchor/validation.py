from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from .contracts import AcquisitionInputs


FIELD_IDS = (
    "purchase_price",
    "current_noi",
    "occupancy",
    "noi_growth",
    "hold_period",
    "exit_cap_rate",
    "ltv",
    "interest_rate",
    "amortization",
)

# Underwriting V2 Gate 1 (docs/underwriting_v2_financial_conventions.md):
# optional, not required -- absent from a payload/workbook, each defaults to
# its neutral value via the AcquisitionInputs dataclass default rather than
# raising a missing-field issue. Deliberately kept out of FIELD_IDS itself,
# since FIELD_IDS also drives the Excel reader's and sensitivity/break-even's
# required-field-id sets, neither of which this gate extends.
V2_FIELD_IDS = (
    "acquisition_cost_pct",
    "financing_fee_pct",
    "disposition_cost_pct",
    "annual_capex_reserve",
    "io_period",
)

ALL_FIELD_IDS = FIELD_IDS + V2_FIELD_IDS

_YEAR_FIELD_IDS = frozenset(("hold_period", "amortization", "io_period"))
_YEAR_FIELD_MINIMUM = {"hold_period": 1, "amortization": 1, "io_period": 0}
_MAX_SAFE_REPR_LENGTH = 200


class IssueCategory(StrEnum):
    WORKBOOK_OPEN = "workbook_open"
    MISSING_SHEET = "missing_sheet"
    MALFORMED_TABLE = "malformed_table"
    MISSING_FIELD_ID = "missing_field_id"
    DUPLICATE_FIELD_ID = "duplicate_field_id"
    UNKNOWN_FIELD_ID = "unknown_field_id"
    BLANK_VALUE = "blank_value"
    FORMULA_VALUE = "formula_value"
    NON_NUMERIC_VALUE = "non_numeric_value"
    NON_FINITE_VALUE = "non_finite_value"
    OUT_OF_DOMAIN_VALUE = "out_of_domain_value"
    NON_WHOLE_NUMBER_HOLD_PERIOD = "non_whole_number_hold_period"
    NON_WHOLE_NUMBER_AMORTIZATION = "non_whole_number_amortization"
    NON_WHOLE_NUMBER_IO_PERIOD = "non_whole_number_io_period"


@dataclass(frozen=True, slots=True, kw_only=True)
class InputIssue:
    category: IssueCategory
    message: str
    field_id: str | None = None
    row: int | None = None
    cell: str | None = None
    rows: tuple[int, ...] = ()
    value: object | None = None

    def __str__(self) -> str:
        return self.message


class InputValidationError(ValueError):
    """One ordered collection of deterministic Phase 1 input issues."""

    def __init__(self, issues: Iterable[InputIssue]) -> None:
        ordered_issues = tuple(issues)
        if not ordered_issues:
            raise ValueError("InputValidationError requires at least one issue.")
        if not all(isinstance(issue, InputIssue) for issue in ordered_issues):
            raise TypeError("issues must contain only InputIssue instances.")

        self.issues = ordered_issues
        super().__init__("\n".join(issue.message for issue in ordered_issues))


_DOMAIN_DESCRIPTIONS = {
    "purchase_price": "greater than 0",
    "current_noi": "greater than or equal to 0",
    "occupancy": "between 0 and 1, inclusive",
    "noi_growth": "greater than -1",
    "hold_period": "a whole number of years greater than or equal to 1",
    "exit_cap_rate": "greater than 0",
    "ltv": "between 0 and 1, inclusive",
    "interest_rate": "greater than or equal to 0",
    "amortization": "a whole number of years greater than or equal to 1",
    "acquisition_cost_pct": "between 0 and 1, inclusive",
    "financing_fee_pct": "between 0 and 1, inclusive",
    "disposition_cost_pct": "between 0 and 1, inclusive",
    "annual_capex_reserve": "greater than or equal to 0",
    "io_period": "a whole number of years greater than or equal to 0",
}

_NON_WHOLE_NUMBER_CATEGORY = {
    "hold_period": IssueCategory.NON_WHOLE_NUMBER_HOLD_PERIOD,
    "amortization": IssueCategory.NON_WHOLE_NUMBER_AMORTIZATION,
    "io_period": IssueCategory.NON_WHOLE_NUMBER_IO_PERIOD,
}


def _safe_repr(value: object) -> str | None:
    """Return a bounded representation, or ``None`` when display is unsafe."""

    try:
        representation = repr(value)
    except Exception:
        return None
    if len(representation) > _MAX_SAFE_REPR_LENGTH:
        return None
    return representation


def _unknown_id_sort_key(field_id: object) -> tuple[str, str, int, object]:
    """Order normal strings and integers without formatting arbitrary values."""

    value_type = type(field_id)
    type_key = (value_type.__module__, value_type.__qualname__)
    if type(field_id) in (str, int, float, bool):
        return (*type_key, 0, field_id)

    representation = _safe_repr(field_id)
    return (*type_key, 1, representation or "")


def _issue(
    category: IssueCategory,
    field_id: str,
    value: object,
    requirement: str,
) -> InputIssue:
    representation = _safe_repr(value)
    value_context = (
        f"value {representation}" if representation is not None else "value"
    )
    return InputIssue(
        category=category,
        field_id=field_id,
        value=value if representation is not None else None,
        message=f"{field_id}: {value_context} {requirement}.",
    )


def _normalize_field_value(
    field_id: str,
    value: object,
) -> tuple[float | int | None, InputIssue | None]:
    """Normalize and validate one known canonical field in isolation."""

    if field_id not in ALL_FIELD_IDS:
        representation = _safe_repr(field_id)
        detail = f": {representation}" if representation is not None else ""
        raise ValueError(f"Unknown canonical Field ID{detail}")

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, _issue(
            IssueCategory.NON_NUMERIC_VALUE,
            field_id,
            value,
            "must be a numeric value; Booleans and text are not accepted",
        )

    if field_id in _YEAR_FIELD_IDS:
        if isinstance(value, float):
            if not isfinite(value):
                return None, _issue(
                    IssueCategory.NON_FINITE_VALUE,
                    field_id,
                    value,
                    "must be finite",
                )
            if not value.is_integer():
                return None, _issue(
                    _NON_WHOLE_NUMBER_CATEGORY[field_id],
                    field_id,
                    value,
                    "must be a whole number of years",
                )

        normalized_year = int(value)
        if normalized_year < _YEAR_FIELD_MINIMUM[field_id]:
            return None, _issue(
                IssueCategory.OUT_OF_DOMAIN_VALUE,
                field_id,
                value,
                f"must be {_DOMAIN_DESCRIPTIONS[field_id]}",
            )
        return normalized_year, None

    try:
        normalized_value = float(value)
    except (OverflowError, TypeError, ValueError):
        return None, _issue(
            IssueCategory.NON_FINITE_VALUE,
            field_id,
            value,
            "cannot be normalized to a finite built-in float",
        )

    if not isfinite(normalized_value):
        return None, _issue(
            IssueCategory.NON_FINITE_VALUE,
            field_id,
            normalized_value,
            "must be finite",
        )

    in_domain = {
        "purchase_price": normalized_value > 0,
        "current_noi": normalized_value >= 0,
        "occupancy": 0 <= normalized_value <= 1,
        "noi_growth": normalized_value > -1,
        "exit_cap_rate": normalized_value > 0,
        "ltv": 0 <= normalized_value <= 1,
        "interest_rate": normalized_value >= 0,
        "acquisition_cost_pct": 0 <= normalized_value <= 1,
        "financing_fee_pct": 0 <= normalized_value <= 1,
        "disposition_cost_pct": 0 <= normalized_value <= 1,
        "annual_capex_reserve": normalized_value >= 0,
    }[field_id]

    if not in_domain:
        return None, _issue(
            IssueCategory.OUT_OF_DOMAIN_VALUE,
            field_id,
            value,
            f"must be {_DOMAIN_DESCRIPTIONS[field_id]}",
        )

    return normalized_value, None


def validate_acquisition_inputs(values: Mapping[str, object]) -> AcquisitionInputs:
    """Normalize and validate an acquisition input mapping: the nine
    required POC V1 Field IDs, plus the five optional Underwriting V2
    Field IDs (``V2_FIELD_IDS``).

    The nine V1 Field IDs remain exactly as required as before -- a missing
    one is still a ``MISSING_FIELD_ID`` issue. A V2 Field ID is validated
    when supplied, but its absence is not an issue: the returned
    ``AcquisitionInputs`` simply takes that field's neutral dataclass
    default, so an existing nine-field payload continues to validate
    unchanged.

    Issues are collected deterministically: unknown IDs first, then missing IDs,
    then value/type/domain issues in canonical field order.
    """

    issues: list[InputIssue] = []
    normalized: dict[str, float | int] = {}

    unknown_ids = sorted(
        (field_id for field_id in values if field_id not in ALL_FIELD_IDS),
        key=_unknown_id_sort_key,
    )
    for field_id in unknown_ids:
        representation = _safe_repr(field_id)
        if isinstance(field_id, str):
            supplied_id = field_id
        elif representation is not None:
            supplied_id = representation
        else:
            supplied_id = f"<{type(field_id).__qualname__}>"
        display = representation or "that cannot be displayed safely"
        issues.append(
            InputIssue(
                category=IssueCategory.UNKNOWN_FIELD_ID,
                field_id=supplied_id,
                value=field_id if representation is not None else None,
                message=f"Unknown Field ID {display}.",
            )
        )

    missing_ids = [field_id for field_id in FIELD_IDS if field_id not in values]
    for field_id in missing_ids:
        issues.append(
            InputIssue(
                category=IssueCategory.MISSING_FIELD_ID,
                field_id=field_id,
                message=f"Missing required Field ID {field_id!r}.",
            )
        )

    for field_id in ALL_FIELD_IDS:
        if field_id not in values:
            continue
        normalized_value, issue = _normalize_field_value(field_id, values[field_id])
        if issue is not None:
            issues.append(issue)
        else:
            assert normalized_value is not None
            normalized[field_id] = normalized_value

    if issues:
        raise InputValidationError(issues)

    return AcquisitionInputs(**normalized)
