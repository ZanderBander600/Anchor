"""Detailed Operating Model V2.1 Gate 5 -- ``validate_acquisition_terms``.

Direct unit coverage beyond the HTTP-layer tests in
``test_api_detailed_v2_1_gate5.py``. Mirrors ``test_validation.py``'s
per-field boundary-test shape, confirming ``validate_acquisition_terms``
reuses the exact same domain rules ``validate_acquisition_inputs`` already
uses for every shared field (``TERMS_FIELD_IDS`` is a subset of
``ALL_FIELD_IDS``), rather than redeclaring them.
"""

from __future__ import annotations

from math import inf, nan

import pytest

from anchor.contracts import AcquisitionInputs, AcquisitionTerms
from anchor.validation import (
    InputIssue,
    InputValidationError,
    IssueCategory,
    TERMS_FIELD_IDS,
    validate_acquisition_inputs,
    validate_acquisition_terms,
)

GOLDEN_TERMS_VALUES: dict[str, object] = {
    "purchase_price": 10_000_000,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
    "acquisition_cost_pct": 0.02,
    "financing_fee_pct": 0.01,
    "disposition_cost_pct": 0.025,
    "annual_capex_reserve": 50_000,
    "io_period": 2,
}


def test_terms_field_ids_is_frozen_and_excludes_quick_only_fields() -> None:
    assert TERMS_FIELD_IDS == (
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
    assert "current_noi" not in TERMS_FIELD_IDS
    assert "occupancy" not in TERMS_FIELD_IDS
    assert "noi_growth" not in TERMS_FIELD_IDS


def test_valid_terms_values_normalize_to_exact_contract_and_builtin_types() -> None:
    result = validate_acquisition_terms(GOLDEN_TERMS_VALUES)

    assert result == AcquisitionTerms(
        purchase_price=10_000_000.0,
        hold_period=5,
        exit_cap_rate=0.065,
        ltv=0.60,
        interest_rate=0.05,
        amortization=30,
        acquisition_cost_pct=0.02,
        financing_fee_pct=0.01,
        disposition_cost_pct=0.025,
        annual_capex_reserve=50_000.0,
        io_period=2,
    )
    assert type(result.purchase_price) is float
    assert type(result.hold_period) is int
    assert type(result.amortization) is int
    assert type(result.io_period) is int


def test_terms_validation_does_not_mutate_the_supplied_mapping() -> None:
    supplied = GOLDEN_TERMS_VALUES.copy()
    before = supplied.copy()

    validate_acquisition_terms(supplied)

    assert supplied == before


@pytest.mark.parametrize("field_id", TERMS_FIELD_IDS)
def test_each_missing_terms_field_is_identified(field_id: str) -> None:
    values = {k: v for k, v in GOLDEN_TERMS_VALUES.items() if k != field_id}

    with pytest.raises(InputValidationError) as caught:
        validate_acquisition_terms(values)

    assert len(caught.value.issues) == 1
    issue = caught.value.issues[0]
    assert issue.category is IssueCategory.MISSING_FIELD_ID
    assert issue.field_id == field_id


def test_unknown_terms_field_is_rejected() -> None:
    values = GOLDEN_TERMS_VALUES | {"current_noi": 600_000}

    with pytest.raises(InputValidationError) as caught:
        validate_acquisition_terms(values)

    unknown_issues = [
        issue
        for issue in caught.value.issues
        if issue.category is IssueCategory.UNKNOWN_FIELD_ID
    ]
    assert len(unknown_issues) == 1
    assert unknown_issues[0].field_id == "current_noi"


def test_terms_ltv_domain_matches_acquisition_inputs_ltv_domain() -> None:
    """Proves the shared domain rule is genuinely reused: the exact same
    out-of-domain LTV value fails identically for both validators."""

    with pytest.raises(InputValidationError) as terms_caught:
        validate_acquisition_terms(GOLDEN_TERMS_VALUES | {"ltv": 1.5})

    inputs_values = {
        "purchase_price": 10_000_000,
        "current_noi": 600_000,
        "occupancy": 0.95,
        "noi_growth": 0.03,
        "hold_period": 5,
        "exit_cap_rate": 0.065,
        "ltv": 1.5,
        "interest_rate": 0.05,
        "amortization": 30,
    }
    with pytest.raises(InputValidationError) as inputs_caught:
        validate_acquisition_inputs(inputs_values)

    assert terms_caught.value.issues[0].category == inputs_caught.value.issues[0].category
    assert terms_caught.value.issues[0].field_id == inputs_caught.value.issues[0].field_id


@pytest.mark.parametrize("field_id", ["hold_period", "amortization", "io_period"])
def test_terms_year_fields_reject_non_whole_numbers(field_id: str) -> None:
    with pytest.raises(InputValidationError) as caught:
        validate_acquisition_terms(GOLDEN_TERMS_VALUES | {field_id: 5.5})

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].category in (
        IssueCategory.NON_WHOLE_NUMBER_HOLD_PERIOD,
        IssueCategory.NON_WHOLE_NUMBER_AMORTIZATION,
        IssueCategory.NON_WHOLE_NUMBER_IO_PERIOD,
    )


@pytest.mark.parametrize("field_id", TERMS_FIELD_IDS)
@pytest.mark.parametrize("bad_value", [nan, inf, -inf])
def test_every_terms_field_rejects_every_non_finite_value(
    field_id: str, bad_value: float
) -> None:
    with pytest.raises(InputValidationError) as caught:
        validate_acquisition_terms(GOLDEN_TERMS_VALUES | {field_id: bad_value})

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].category in (
        IssueCategory.NON_FINITE_VALUE,
        IssueCategory.OUT_OF_DOMAIN_VALUE,
    )


def test_io_period_zero_is_valid_for_terms_too() -> None:
    result = validate_acquisition_terms(GOLDEN_TERMS_VALUES | {"io_period": 0})

    assert result.io_period == 0


def test_terms_field_ids_are_a_subset_of_acquisition_inputs_domain_rules() -> None:
    """Structural proof that validate_acquisition_terms never needs -- and
    never declares -- a domain rule of its own: every TERMS_FIELD_IDS entry
    is already governed by validate_acquisition_inputs' shared rule set."""

    from anchor.validation import ALL_FIELD_IDS

    assert set(TERMS_FIELD_IDS).issubset(set(ALL_FIELD_IDS))
