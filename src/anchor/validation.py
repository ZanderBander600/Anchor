from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from .contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs


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

# Detailed Operating Model V2.1 Gate 1
# (docs/detailed_operating_model_v2_1_financial_conventions.md): the eleven
# Detailed operating Field IDs. Unlike V2_FIELD_IDS, every one of these is
# required -- there is no economically meaningful neutral default for e.g.
# gross_potential_rent -- so DETAILED_FIELD_IDS is validated by its own
# validate_detailed_operating_inputs (below), never folded into
# ALL_FIELD_IDS/validate_acquisition_inputs: a Detailed deal supplies all
# eleven or none, never some subset defaulted like the V2 fields are.
DETAILED_FIELD_IDS = (
    "gross_potential_rent",
    "other_income",
    "vacancy_credit_loss_pct",
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "other_operating_expenses",
    "management_fee_pct",
    "revenue_growth",
    "expense_growth",
)

# Detailed Operating Model V2.1 Gate 5: the eleven AcquisitionTerms Field
# IDs -- exactly the FIELD_IDS/V2_FIELD_IDS names that are neither
# current_noi, occupancy, nor noi_growth. Every one of these already has a
# domain rule in _normalize_field_value (below); validate_acquisition_terms
# reuses that same function field-by-field rather than redeclaring any
# domain rule, so a Quick and a Detailed deal validate purchase_price (or
# any other shared field) identically, by construction.
TERMS_FIELD_IDS = (
    "purchase_price",
    "hold_period",
    "exit_cap_rate",
    "ltv",
    "interest_rate",
    "amortization",
    "acquisition_cost_pct",
    "financing_fee_pct",
    "disposition_cost_pct",
    "annual_capex_reserve",
    "io_period",
)

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
    # Detailed Operating Model V2.1 Gate 10 -- explicit workbook schema/
    # version metadata (``anchor.workbook_schema``). SCHEMA_MISMATCH is a
    # Quick workbook uploaded through the Detailed path or vice versa;
    # UNSUPPORTED_SCHEMA is an ``anchor_schema`` value neither reader
    # recognizes; UNSUPPORTED_SCHEMA_VERSION is a recognized Detailed schema
    # at a ``schema_version`` this Anchor version does not parse. All three
    # are terminal, single-issue errors raised before any field-level
    # parsing, exactly like WORKBOOK_OPEN/MISSING_SHEET/MALFORMED_TABLE.
    SCHEMA_MISMATCH = "schema_mismatch"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"


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

_DETAILED_DOMAIN_DESCRIPTIONS = {
    "gross_potential_rent": "greater than or equal to 0",
    "other_income": "greater than or equal to 0",
    "vacancy_credit_loss_pct": "between 0 and 1, inclusive",
    "property_taxes": "greater than or equal to 0",
    "insurance": "greater than or equal to 0",
    "utilities": "greater than or equal to 0",
    "repairs_maintenance": "greater than or equal to 0",
    "other_operating_expenses": "greater than or equal to 0",
    "management_fee_pct": "between 0 and 1, inclusive",
    # Growth Rate Validation (financial-conventions doc): identical shape to
    # noi_growth's existing domain -- strictly greater than -1, no upper
    # bound. g <= -1 makes (1 + g) non-positive, which either collapses
    # every subsequent year to exactly 0 (g == -1) or flips sign every year
    # (g < -1) -- neither is economically meaningful for a compounding
    # dollar amount.
    "revenue_growth": "greater than -1",
    "expense_growth": "greater than -1",
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


# =============================================================================
# Detailed Operating Model V2.1 Gate 5 -- AcquisitionTerms validation
# =============================================================================


def validate_acquisition_terms(values: Mapping[str, object]) -> AcquisitionTerms:
    """Normalize and validate an ``AcquisitionTerms`` mapping: all eleven
    ``TERMS_FIELD_IDS`` are required (``AcquisitionTerms`` has no field
    defaults -- Detailed Operating Model V2.1 Gate 1). Needed once the
    Detailed API path can submit ``terms`` directly (the Quick path never
    calls this -- it reaches ``AcquisitionTerms`` only via
    ``acquisition_terms_from_inputs``, which performs no validation of its
    own because its argument is already validated).

    Reuses ``_normalize_field_value`` -- the exact same per-field domain
    function ``validate_acquisition_inputs`` uses -- for every one of the
    eleven fields, so a shared field (e.g. ``purchase_price``) validates
    identically for a Quick and a Detailed deal. Never redeclares a domain
    rule. Issue ordering mirrors ``validate_acquisition_inputs``: unknown
    IDs first, then missing IDs, then value/type/domain issues in canonical
    field order.
    """

    issues: list[InputIssue] = []
    normalized: dict[str, float | int] = {}

    unknown_ids = sorted(
        (field_id for field_id in values if field_id not in TERMS_FIELD_IDS),
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

    missing_ids = [field_id for field_id in TERMS_FIELD_IDS if field_id not in values]
    for field_id in missing_ids:
        issues.append(
            InputIssue(
                category=IssueCategory.MISSING_FIELD_ID,
                field_id=field_id,
                message=f"Missing required Field ID {field_id!r}.",
            )
        )

    for field_id in TERMS_FIELD_IDS:
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

    return AcquisitionTerms(**normalized)


# =============================================================================
# Detailed Operating Model V2.1 Gate 1 -- DetailedOperatingInputs validation
# =============================================================================


def _normalize_detailed_field_value(
    field_id: str,
    value: object,
) -> tuple[float | None, InputIssue | None]:
    """Normalize and validate one known Detailed Field ID in isolation.

    Mirrors ``_normalize_field_value``'s shape, but every Detailed field is
    a plain float with no whole-number/year handling (``DETAILED_FIELD_IDS``
    contains no ``hold_period``/``amortization``/``io_period``-style field).
    """

    if field_id not in DETAILED_FIELD_IDS:
        representation = _safe_repr(field_id)
        detail = f": {representation}" if representation is not None else ""
        raise ValueError(f"Unknown Detailed Field ID{detail}")

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, _issue(
            IssueCategory.NON_NUMERIC_VALUE,
            field_id,
            value,
            "must be a numeric value; Booleans and text are not accepted",
        )

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
        "gross_potential_rent": normalized_value >= 0,
        "other_income": normalized_value >= 0,
        "vacancy_credit_loss_pct": 0 <= normalized_value <= 1,
        "property_taxes": normalized_value >= 0,
        "insurance": normalized_value >= 0,
        "utilities": normalized_value >= 0,
        "repairs_maintenance": normalized_value >= 0,
        "other_operating_expenses": normalized_value >= 0,
        "management_fee_pct": 0 <= normalized_value <= 1,
        "revenue_growth": normalized_value > -1,
        "expense_growth": normalized_value > -1,
    }[field_id]

    if not in_domain:
        return None, _issue(
            IssueCategory.OUT_OF_DOMAIN_VALUE,
            field_id,
            value,
            f"must be {_DETAILED_DOMAIN_DESCRIPTIONS[field_id]}",
        )

    return normalized_value, None


def validate_detailed_operating_inputs(
    values: Mapping[str, object]
) -> DetailedOperatingInputs:
    """Normalize and validate a Detailed operating input mapping: all eleven
    ``DETAILED_FIELD_IDS`` are required -- unlike the five optional
    Underwriting V2 fields, none has a neutral default, so a missing field
    here is always a ``MISSING_FIELD_ID`` issue, never a silently-defaulted
    value.

    Issues are collected deterministically in the same order
    ``validate_acquisition_inputs`` uses: unknown IDs first, then missing
    IDs, then value/type/domain issues in canonical field order. This
    function never reuses or reimplements ``validate_acquisition_inputs``'
    domain rules -- the eleven Detailed fields are a disjoint field set with
    their own domain rules (financial-conventions doc), not an extension of
    ``AcquisitionInputs``'.
    """

    issues: list[InputIssue] = []
    normalized: dict[str, float] = {}

    unknown_ids = sorted(
        (field_id for field_id in values if field_id not in DETAILED_FIELD_IDS),
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

    missing_ids = [
        field_id for field_id in DETAILED_FIELD_IDS if field_id not in values
    ]
    for field_id in missing_ids:
        issues.append(
            InputIssue(
                category=IssueCategory.MISSING_FIELD_ID,
                field_id=field_id,
                message=f"Missing required Field ID {field_id!r}.",
            )
        )

    for field_id in DETAILED_FIELD_IDS:
        if field_id not in values:
            continue
        normalized_value, issue = _normalize_detailed_field_value(
            field_id, values[field_id]
        )
        if issue is not None:
            issues.append(issue)
        else:
            assert normalized_value is not None
            normalized[field_id] = normalized_value

    if issues:
        raise InputValidationError(issues)

    return DetailedOperatingInputs(**normalized)
