from dataclasses import replace
from math import inf, nan, nextafter

import pytest

from anchor.contracts import AcquisitionInputs
from anchor.validation import (
    FIELD_IDS,
    InputIssue,
    InputValidationError,
    IssueCategory,
    _normalize_field_value,
    validate_acquisition_inputs,
)


VALID_VALUES: dict[str, object] = {
    "purchase_price": 50_000_000,
    "current_noi": 2_500_000,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.055,
    "ltv": 0.65,
    "interest_rate": 0.0525,
    "amortization": 30,
}


def validate_with(field_id: str, value: object) -> AcquisitionInputs:
    values = VALID_VALUES | {field_id: value}
    return validate_acquisition_inputs(values)


def only_issue(field_id: str, value: object) -> InputIssue:
    with pytest.raises(InputValidationError) as caught:
        validate_with(field_id, value)
    assert len(caught.value.issues) == 1
    return caught.value.issues[0]


def test_canonical_field_order_is_frozen() -> None:
    assert FIELD_IDS == (
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


def test_valid_values_normalize_to_exact_contract_and_builtin_types() -> None:
    result = validate_acquisition_inputs(VALID_VALUES)

    assert result == AcquisitionInputs(
        purchase_price=50_000_000.0,
        current_noi=2_500_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=5,
        exit_cap_rate=0.055,
        ltv=0.65,
        interest_rate=0.0525,
        amortization=30,
    )
    assert tuple(type(getattr(result, field_id)) for field_id in FIELD_IDS) == (
        float,
        float,
        float,
        float,
        int,
        float,
        float,
        float,
        int,
    )


def test_validation_does_not_mutate_the_supplied_mapping() -> None:
    supplied = VALID_VALUES.copy()
    before = supplied.copy()

    validate_acquisition_inputs(supplied)

    assert supplied == before


def test_integral_floats_normalize_to_builtin_int_years() -> None:
    result = validate_acquisition_inputs(
        VALID_VALUES | {"hold_period": 5.0, "amortization": 30.0}
    )

    assert result.hold_period == 5
    assert type(result.hold_period) is int
    assert result.amortization == 30
    assert type(result.amortization) is int


def test_percentage_decimal_semantics_are_preserved_without_rescaling() -> None:
    result = validate_acquisition_inputs(
        VALID_VALUES
        | {
            "occupancy": 0.95,
            "noi_growth": 0.03,
            "exit_cap_rate": 0.055,
            "ltv": 0.65,
            "interest_rate": 0.0525,
        }
    )

    assert (
        result.occupancy,
        result.noi_growth,
        result.exit_cap_rate,
        result.ltv,
        result.interest_rate,
    ) == (0.95, 0.03, 0.055, 0.65, 0.0525)


def test_occupancy_is_never_applied_to_current_noi() -> None:
    result = validate_acquisition_inputs(
        VALID_VALUES | {"occupancy": 0.5, "current_noi": 2_500_000}
    )

    assert result.occupancy == 0.5
    assert result.current_noi == 2_500_000.0


@pytest.mark.parametrize(
    ("field_id", "accepted_values"),
    [
        ("purchase_price", (1e-300, 1.0, 1e308)),
        ("current_noi", (0, 1.0, 1e308)),
        ("occupancy", (0, 0.5, 1)),
        ("noi_growth", (nextafter(-1.0, inf), 0, 1e308)),
        ("hold_period", (1, 1.0, 10**100)),
        ("exit_cap_rate", (1e-300, 0.055, 1e308)),
        ("ltv", (0, 0.65, 1)),
        ("interest_rate", (0, 0.0525, 1e308)),
        ("amortization", (1, 1.0, 10**100)),
    ],
)
def test_phase_zero_domains_accept_every_boundary_and_unbounded_large_value(
    field_id: str,
    accepted_values: tuple[object, ...],
) -> None:
    for accepted_value in accepted_values:
        result = validate_with(field_id, accepted_value)
        expected_type = int if field_id in {"hold_period", "amortization"} else float
        assert type(getattr(result, field_id)) is expected_type


@pytest.mark.parametrize(
    ("field_id", "rejected_value"),
    [
        ("purchase_price", 0),
        ("purchase_price", -1),
        ("current_noi", -1e-300),
        ("occupancy", -1e-300),
        ("occupancy", nextafter(1.0, inf)),
        ("noi_growth", -1),
        ("noi_growth", nextafter(-1.0, -inf)),
        ("hold_period", 0),
        ("hold_period", -1),
        ("exit_cap_rate", 0),
        ("exit_cap_rate", -1e-300),
        ("ltv", -1e-300),
        ("ltv", nextafter(1.0, inf)),
        ("interest_rate", -1e-300),
        ("amortization", 0),
        ("amortization", -1),
    ],
)
def test_phase_zero_domain_violations_are_field_specific(
    field_id: str,
    rejected_value: object,
) -> None:
    issue = only_issue(field_id, rejected_value)

    assert issue.category is IssueCategory.OUT_OF_DOMAIN_VALUE
    assert issue.field_id == field_id
    assert field_id in issue.message
    assert issue.value is not None


def test_domain_issue_preserves_the_supplied_numeric_representation() -> None:
    year_issue = only_issue("hold_period", 0.0)
    occupancy_issue = only_issue("occupancy", 95)

    assert type(year_issue.value) is float
    assert type(occupancy_issue.value) is int


@pytest.mark.parametrize(
    ("field_id", "value", "category"),
    [
        ("hold_period", 5.5, IssueCategory.NON_WHOLE_NUMBER_HOLD_PERIOD),
        ("hold_period", -0.5, IssueCategory.NON_WHOLE_NUMBER_HOLD_PERIOD),
        ("amortization", 30.5, IssueCategory.NON_WHOLE_NUMBER_AMORTIZATION),
        ("amortization", -0.5, IssueCategory.NON_WHOLE_NUMBER_AMORTIZATION),
    ],
)
def test_fractional_years_receive_specific_errors(
    field_id: str,
    value: float,
    category: IssueCategory,
) -> None:
    issue = only_issue(field_id, value)

    assert issue.category is category
    assert issue.field_id == field_id
    assert issue.value == value


@pytest.mark.parametrize("field_id", FIELD_IDS)
@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_every_field_rejects_every_non_finite_value(
    field_id: str,
    value: float,
) -> None:
    issue = only_issue(field_id, value)

    assert issue.category is IssueCategory.NON_FINITE_VALUE
    assert issue.field_id == field_id


def test_huge_int_that_cannot_normalize_to_float_is_a_safe_non_finite_issue() -> None:
    huge_value = 10**5000

    issue = only_issue("purchase_price", huge_value)

    assert issue.category is IssueCategory.NON_FINITE_VALUE
    assert issue.value is None
    assert "purchase_price" in issue.message
    assert len(issue.message) < 300
    assert "InputIssue" in repr(issue)


def test_huge_negative_year_is_a_safe_out_of_domain_issue() -> None:
    huge_negative_year = -(10**5000)

    issue = only_issue("hold_period", huge_negative_year)

    assert issue.category is IssueCategory.OUT_OF_DOMAIN_VALUE
    assert issue.value is None
    assert "hold_period" in issue.message
    assert len(issue.message) < 300
    assert "InputIssue" in repr(issue)


@pytest.mark.parametrize("field_id", FIELD_IDS)
@pytest.mark.parametrize("value", [True, False])
def test_booleans_are_never_accepted_as_numeric(
    field_id: str,
    value: bool,
) -> None:
    issue = only_issue(field_id, value)

    assert issue.category is IssueCategory.NON_NUMERIC_VALUE
    assert issue.field_id == field_id


@pytest.mark.parametrize("field_id", FIELD_IDS)
@pytest.mark.parametrize("value", ["5", None])
def test_non_numeric_python_values_are_not_coerced(
    field_id: str,
    value: object,
) -> None:
    issue = only_issue(field_id, value)

    assert issue.category is IssueCategory.NON_NUMERIC_VALUE
    assert issue.field_id == field_id


@pytest.mark.parametrize("field_id", FIELD_IDS)
def test_each_missing_field_is_identified(field_id: str) -> None:
    values = VALID_VALUES.copy()
    del values[field_id]

    with pytest.raises(InputValidationError) as caught:
        validate_acquisition_inputs(values)

    assert [(issue.category, issue.field_id) for issue in caught.value.issues] == [
        (IssueCategory.MISSING_FIELD_ID, field_id)
    ]


def test_unknown_fields_are_rejected_in_stable_order() -> None:
    values = {"zzz": 1, **VALID_VALUES, "aaa": 2}

    with pytest.raises(InputValidationError) as caught:
        validate_acquisition_inputs(values)

    assert [(issue.category, issue.field_id) for issue in caught.value.issues] == [
        (IssueCategory.UNKNOWN_FIELD_ID, "aaa"),
        (IssueCategory.UNKNOWN_FIELD_ID, "zzz"),
    ]


def test_huge_integer_unknown_key_cannot_leak_a_repr_exception() -> None:
    huge_unknown_id = 10**5000
    values = VALID_VALUES | {huge_unknown_id: 1}  # type: ignore[dict-item]

    with pytest.raises(InputValidationError) as caught:
        validate_acquisition_inputs(values)

    assert len(caught.value.issues) == 1
    issue = caught.value.issues[0]
    assert issue.category is IssueCategory.UNKNOWN_FIELD_ID
    assert issue.value is None
    assert len(issue.message) < 300
    assert "InputIssue" in repr(issue)


def test_multiple_errors_follow_frozen_group_and_canonical_field_order() -> None:
    values = {
        "unknown": 1,
        "current_noi": -1,
        "occupancy": 95,
        "noi_growth": nan,
        "hold_period": 5.5,
        "exit_cap_rate": 0,
        "ltv": -0.1,
        "interest_rate": -0.01,
        "amortization": 30.5,
    }

    with pytest.raises(InputValidationError) as caught:
        validate_acquisition_inputs(values)

    assert [(issue.category, issue.field_id) for issue in caught.value.issues] == [
        (IssueCategory.UNKNOWN_FIELD_ID, "unknown"),
        (IssueCategory.MISSING_FIELD_ID, "purchase_price"),
        (IssueCategory.OUT_OF_DOMAIN_VALUE, "current_noi"),
        (IssueCategory.OUT_OF_DOMAIN_VALUE, "occupancy"),
        (IssueCategory.NON_FINITE_VALUE, "noi_growth"),
        (IssueCategory.NON_WHOLE_NUMBER_HOLD_PERIOD, "hold_period"),
        (IssueCategory.OUT_OF_DOMAIN_VALUE, "exit_cap_rate"),
        (IssueCategory.OUT_OF_DOMAIN_VALUE, "ltv"),
        (IssueCategory.OUT_OF_DOMAIN_VALUE, "interest_rate"),
        (IssueCategory.NON_WHOLE_NUMBER_AMORTIZATION, "amortization"),
    ]


def test_no_additional_cross_field_relationships_are_imposed() -> None:
    result = validate_acquisition_inputs(
        VALID_VALUES
        | {
            "purchase_price": 1,
            "current_noi": 1e308,
            "noi_growth": 1e308,
            "hold_period": 100,
            "exit_cap_rate": 1e308,
            "ltv": 1,
            "interest_rate": 1e308,
            "amortization": 1,
        }
    )

    assert result.current_noi == 1e308
    assert result.noi_growth == 1e308
    assert result.exit_cap_rate == 1e308
    assert result.interest_rate == 1e308
    assert result.hold_period > result.amortization


def test_one_field_helper_does_not_require_the_other_eight_fields() -> None:
    normalized, issue = _normalize_field_value("hold_period", 5.0)

    assert normalized == 5
    assert type(normalized) is int
    assert issue is None


def test_issue_context_is_typed_immutable_and_replaceable_by_reader() -> None:
    issue = InputIssue(
        category=IssueCategory.OUT_OF_DOMAIN_VALUE,
        field_id="occupancy",
        value=95.0,
        message="occupancy is outside its domain",
    )
    contextual = replace(issue, row=4, cell="C4")

    assert contextual.row == 4
    assert contextual.cell == "C4"
    assert issue.row is None
    assert issue.cell is None


def test_validation_error_preserves_issue_tuple_and_user_readable_order() -> None:
    first = InputIssue(
        category=IssueCategory.MISSING_FIELD_ID,
        field_id="purchase_price",
        message="first issue",
    )
    second = InputIssue(
        category=IssueCategory.MISSING_FIELD_ID,
        field_id="current_noi",
        message="second issue",
    )

    error = InputValidationError(issue for issue in (first, second))

    assert error.issues == (first, second)
    assert type(error.issues) is tuple
    assert str(error) == "first issue\nsecond issue"


def test_issue_categories_cover_every_frozen_phase_one_condition() -> None:
    assert tuple(IssueCategory.__members__) == (
        "WORKBOOK_OPEN",
        "MISSING_SHEET",
        "MALFORMED_TABLE",
        "MISSING_FIELD_ID",
        "DUPLICATE_FIELD_ID",
        "UNKNOWN_FIELD_ID",
        "BLANK_VALUE",
        "FORMULA_VALUE",
        "NON_NUMERIC_VALUE",
        "NON_FINITE_VALUE",
        "OUT_OF_DOMAIN_VALUE",
        "NON_WHOLE_NUMBER_HOLD_PERIOD",
        "NON_WHOLE_NUMBER_AMORTIZATION",
    )
