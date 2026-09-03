"""Detailed Operating Model V2.1 Gate 1 -- contracts + validation.

Covers, per ``docs/detailed_operating_model_v2_1_architecture.md`` Section 2
and Section 11's Gate 1 scope:

- ``AcquisitionTerms`` (``anchor.contracts``) -- the new, concrete,
  mode-agnostic acquisition/debt/exit contract, and
  ``acquisition_terms_from_inputs``, the sole Quick-side adapter into it.
- ``DetailedOperatingInputs`` (``anchor.contracts``) -- the eleven Detailed
  operating assumptions, and ``validate_detailed_operating_inputs``
  (``anchor.validation``).
- ``OperatingProjection`` / ``OperatingProjectionLike``
  (``anchor.engine.contracts``) -- the canonical Detailed operating-schedule
  contract and the narrow structural shape the downstream engine consumes.

No calculation logic and no engine wiring is introduced at this gate
(``build_detailed_operating_projection`` is Gate 2;
``analyze_detailed_acquisition``/the ``debt.py`` signature narrowing is
Gate 3) -- this module tests contracts and validation only, and confirms the
existing Quick/V2 surface (``AcquisitionInputs``, ``validate_acquisition_inputs``,
``analyze_acquisition``) is completely unaffected by their addition.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from math import inf, nan

import pytest

from anchor.contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    acquisition_terms_from_inputs,
)
from anchor.engine import analyze_acquisition
from anchor.engine.contracts import NoiForecast, OperatingProjection, OperatingProjectionLike
from anchor.validation import (
    DETAILED_FIELD_IDS,
    InputIssue,
    InputValidationError,
    IssueCategory,
    validate_acquisition_inputs,
    validate_detailed_operating_inputs,
)


# =============================================================================
# AcquisitionTerms
# =============================================================================

ACQUISITION_TERMS_EXPECTED_FIELDS = (
    ("purchase_price", float),
    ("hold_period", int),
    ("exit_cap_rate", float),
    ("ltv", float),
    ("interest_rate", float),
    ("amortization", int),
    ("acquisition_cost_pct", float),
    ("financing_fee_pct", float),
    ("disposition_cost_pct", float),
    ("annual_capex_reserve", float),
    ("io_period", int),
)


def make_terms() -> AcquisitionTerms:
    return AcquisitionTerms(
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


def test_acquisition_terms_has_exact_fields_order_annotations_and_keyword_only_shape() -> None:
    contract_fields = fields(AcquisitionTerms)

    assert is_dataclass(AcquisitionTerms)
    assert (
        tuple((field.name, field.type) for field in contract_fields)
        == ACQUISITION_TERMS_EXPECTED_FIELDS
    )
    assert len(contract_fields) == 11
    assert all(field.kw_only for field in contract_fields)
    assert AcquisitionTerms.__slots__ == tuple(
        name for name, _ in ACQUISITION_TERMS_EXPECTED_FIELDS
    )


def test_acquisition_terms_excludes_current_noi_occupancy_and_noi_growth() -> None:
    """The exact three-field exclusion Section 4 of the architecture
    document resolves: AcquisitionTerms has no way to carry how NOI was
    produced, or the Quick-only informational occupancy field."""

    field_names = {field.name for field in fields(AcquisitionTerms)}

    assert "current_noi" not in field_names
    assert "occupancy" not in field_names
    assert "noi_growth" not in field_names


def test_acquisition_terms_is_frozen_and_slotted() -> None:
    terms = make_terms()

    assert not hasattr(terms, "__dict__")
    with pytest.raises(FrozenInstanceError):
        terms.purchase_price = 1.0  # type: ignore[misc]


def test_acquisition_terms_rejects_positional_construction() -> None:
    with pytest.raises(TypeError):
        AcquisitionTerms(  # type: ignore[misc]
            10_000_000.0, 5, 0.065, 0.60, 0.05, 30, 0.02, 0.01, 0.025, 50_000.0, 2
        )


def test_acquisition_terms_from_inputs_copies_every_shared_field_verbatim() -> None:
    inputs = AcquisitionInputs(
        purchase_price=10_000_000.0,
        current_noi=600_000.0,
        occupancy=0.95,
        noi_growth=0.03,
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

    terms = acquisition_terms_from_inputs(inputs)

    assert terms == AcquisitionTerms(
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


def test_acquisition_terms_from_inputs_reflects_v1_neutral_v2_defaults() -> None:
    """A nine-field-constructed AcquisitionInputs (V2 fields at their
    neutral default) adapts to an AcquisitionTerms with those same
    neutral values -- the adapter performs no defaulting of its own,
    it only copies whatever AcquisitionInputs already resolved."""

    inputs = AcquisitionInputs(
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

    terms = acquisition_terms_from_inputs(inputs)

    assert terms.acquisition_cost_pct == 0.0
    assert terms.financing_fee_pct == 0.0
    assert terms.disposition_cost_pct == 0.0
    assert terms.annual_capex_reserve == 0.0
    assert terms.io_period == 0
    assert type(terms.io_period) is int


def test_acquisition_terms_from_inputs_never_mutates_its_argument() -> None:
    inputs = AcquisitionInputs(
        purchase_price=10_000_000.0,
        current_noi=600_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=5,
        exit_cap_rate=0.065,
        ltv=0.60,
        interest_rate=0.05,
        amortization=30,
    )
    before = inputs

    acquisition_terms_from_inputs(inputs)

    assert inputs == before


# =============================================================================
# DetailedOperatingInputs
# =============================================================================

DETAILED_INPUTS_EXPECTED_FIELDS = (
    ("gross_potential_rent", float),
    ("other_income", float),
    ("vacancy_credit_loss_pct", float),
    ("property_taxes", float),
    ("insurance", float),
    ("utilities", float),
    ("repairs_maintenance", float),
    ("other_operating_expenses", float),
    ("management_fee_pct", float),
    ("revenue_growth", float),
    ("expense_growth", float),
)

GOLDEN_DETAILED_VALUES: dict[str, float] = {
    "gross_potential_rent": 800_000.0,
    "other_income": 20_000.0,
    "vacancy_credit_loss_pct": 0.05,
    "property_taxes": 60_000.0,
    "insurance": 20_000.0,
    "utilities": 25_000.0,
    "repairs_maintenance": 20_000.0,
    "other_operating_expenses": 16_000.0,
    "management_fee_pct": 0.05,
    "revenue_growth": 0.03,
    "expense_growth": 0.03,
}


def make_detailed_inputs() -> DetailedOperatingInputs:
    return DetailedOperatingInputs(**GOLDEN_DETAILED_VALUES)


def test_detailed_operating_inputs_has_exact_fields_order_annotations_and_keyword_only_shape() -> (
    None
):
    contract_fields = fields(DetailedOperatingInputs)

    assert is_dataclass(DetailedOperatingInputs)
    assert (
        tuple((field.name, field.type) for field in contract_fields)
        == DETAILED_INPUTS_EXPECTED_FIELDS
    )
    assert len(contract_fields) == 11
    assert all(field.kw_only for field in contract_fields)
    assert DetailedOperatingInputs.__slots__ == tuple(
        name for name, _ in DETAILED_INPUTS_EXPECTED_FIELDS
    )


def test_detailed_operating_inputs_is_frozen_and_slotted() -> None:
    detailed_inputs = make_detailed_inputs()

    assert not hasattr(detailed_inputs, "__dict__")
    with pytest.raises(FrozenInstanceError):
        detailed_inputs.gross_potential_rent = 1.0  # type: ignore[misc]


def test_detailed_operating_inputs_rejects_positional_construction() -> None:
    with pytest.raises(TypeError):
        DetailedOperatingInputs(  # type: ignore[misc]
            800_000.0, 20_000.0, 0.05, 60_000.0, 20_000.0, 25_000.0, 20_000.0,
            16_000.0, 0.05, 0.03, 0.03,
        )


def test_detailed_operating_inputs_has_no_field_defaults() -> None:
    """Every field is required -- unlike AcquisitionInputs' V2 fields,
    none has an economically meaningful neutral default."""

    import dataclasses

    for field in fields(DetailedOperatingInputs):
        assert field.default is dataclasses.MISSING
        assert field.default_factory is dataclasses.MISSING


# =============================================================================
# DETAILED_FIELD_IDS / validate_detailed_operating_inputs
# =============================================================================


def test_detailed_field_ids_is_frozen_and_matches_the_contract_field_order() -> None:
    assert DETAILED_FIELD_IDS == tuple(
        name for name, _ in DETAILED_INPUTS_EXPECTED_FIELDS
    )


def test_valid_detailed_values_normalize_to_exact_contract_and_builtin_types() -> None:
    result = validate_detailed_operating_inputs(GOLDEN_DETAILED_VALUES)

    assert result == DetailedOperatingInputs(**GOLDEN_DETAILED_VALUES)
    assert all(
        type(getattr(result, field_id)) is float for field_id in DETAILED_FIELD_IDS
    )


def test_detailed_validation_does_not_mutate_the_supplied_mapping() -> None:
    supplied = GOLDEN_DETAILED_VALUES.copy()
    before = supplied.copy()

    validate_detailed_operating_inputs(supplied)

    assert supplied == before


@pytest.mark.parametrize("field_id", DETAILED_FIELD_IDS)
def test_each_missing_detailed_field_is_identified(field_id: str) -> None:
    values = {k: v for k, v in GOLDEN_DETAILED_VALUES.items() if k != field_id}

    with pytest.raises(InputValidationError) as caught:
        validate_detailed_operating_inputs(values)

    assert len(caught.value.issues) == 1
    issue = caught.value.issues[0]
    assert issue.category is IssueCategory.MISSING_FIELD_ID
    assert issue.field_id == field_id


def test_unknown_detailed_field_is_rejected() -> None:
    values = GOLDEN_DETAILED_VALUES | {"current_noi": 600_000.0}

    with pytest.raises(InputValidationError) as caught:
        validate_detailed_operating_inputs(values)

    unknown_issues = [
        issue
        for issue in caught.value.issues
        if issue.category is IssueCategory.UNKNOWN_FIELD_ID
    ]
    assert len(unknown_issues) == 1
    assert unknown_issues[0].field_id == "current_noi"


@pytest.mark.parametrize(
    "field_id",
    [
        "gross_potential_rent",
        "other_income",
        "property_taxes",
        "insurance",
        "utilities",
        "repairs_maintenance",
        "other_operating_expenses",
    ],
)
def test_detailed_currency_fields_reject_negative_values(field_id: str) -> None:
    values = GOLDEN_DETAILED_VALUES | {field_id: -0.01}

    with pytest.raises(InputValidationError) as caught:
        validate_detailed_operating_inputs(values)

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].category is IssueCategory.OUT_OF_DOMAIN_VALUE
    assert caught.value.issues[0].field_id == field_id


@pytest.mark.parametrize("field_id", ["gross_potential_rent", "other_income"])
def test_detailed_currency_fields_accept_zero(field_id: str) -> None:
    values = GOLDEN_DETAILED_VALUES | {field_id: 0.0}

    result = validate_detailed_operating_inputs(values)

    assert getattr(result, field_id) == 0.0


@pytest.mark.parametrize("field_id", ["vacancy_credit_loss_pct", "management_fee_pct"])
def test_detailed_percentage_fields_accept_boundary_zero_and_one(field_id: str) -> None:
    at_zero = validate_detailed_operating_inputs(GOLDEN_DETAILED_VALUES | {field_id: 0.0})
    at_one = validate_detailed_operating_inputs(GOLDEN_DETAILED_VALUES | {field_id: 1.0})

    assert getattr(at_zero, field_id) == 0.0
    assert getattr(at_one, field_id) == 1.0


@pytest.mark.parametrize("field_id", ["vacancy_credit_loss_pct", "management_fee_pct"])
@pytest.mark.parametrize("value", [-0.0001, 1.0001])
def test_detailed_percentage_fields_reject_values_outside_zero_to_one(
    field_id: str, value: float
) -> None:
    with pytest.raises(InputValidationError) as caught:
        validate_detailed_operating_inputs(GOLDEN_DETAILED_VALUES | {field_id: value})

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].category is IssueCategory.OUT_OF_DOMAIN_VALUE
    assert caught.value.issues[0].field_id == field_id


@pytest.mark.parametrize("field_id", ["revenue_growth", "expense_growth"])
@pytest.mark.parametrize("value", [-1.0, -1.5])
def test_detailed_growth_fields_reject_at_and_below_negative_one(
    field_id: str, value: float
) -> None:
    """g <= -1 makes (1 + g) non-positive -- collapse-to-zero at exactly
    -1, sign-flipping compounding below it. Both rejected, matching
    noi_growth's existing strictly-greater-than-(-1) domain."""

    with pytest.raises(InputValidationError) as caught:
        validate_detailed_operating_inputs(GOLDEN_DETAILED_VALUES | {field_id: value})

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].category is IssueCategory.OUT_OF_DOMAIN_VALUE
    assert caught.value.issues[0].field_id == field_id


@pytest.mark.parametrize("field_id", ["revenue_growth", "expense_growth"])
def test_detailed_growth_fields_accept_large_negative_and_positive_values(
    field_id: str,
) -> None:
    """No upper bound, and any downside scenario short of -100% remains
    expressible -- mirrors noi_growth's existing unbounded-above domain."""

    downside = validate_detailed_operating_inputs(
        GOLDEN_DETAILED_VALUES | {field_id: -0.30}
    )
    upside = validate_detailed_operating_inputs(
        GOLDEN_DETAILED_VALUES | {field_id: 5.0}
    )

    assert getattr(downside, field_id) == -0.30
    assert getattr(upside, field_id) == 5.0


@pytest.mark.parametrize("field_id", DETAILED_FIELD_IDS)
@pytest.mark.parametrize("bad_value", [nan, inf, -inf])
def test_every_detailed_field_rejects_every_non_finite_value(
    field_id: str, bad_value: float
) -> None:
    with pytest.raises(InputValidationError) as caught:
        validate_detailed_operating_inputs(GOLDEN_DETAILED_VALUES | {field_id: bad_value})

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].category is IssueCategory.NON_FINITE_VALUE


@pytest.mark.parametrize("field_id", DETAILED_FIELD_IDS)
def test_detailed_fields_reject_booleans(field_id: str) -> None:
    with pytest.raises(InputValidationError) as caught:
        validate_detailed_operating_inputs(GOLDEN_DETAILED_VALUES | {field_id: True})

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].category is IssueCategory.NON_NUMERIC_VALUE


def test_detailed_fields_reject_non_numeric_strings() -> None:
    with pytest.raises(InputValidationError) as caught:
        validate_detailed_operating_inputs(
            GOLDEN_DETAILED_VALUES | {"gross_potential_rent": "800000"}
        )

    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].category is IssueCategory.NON_NUMERIC_VALUE


# =============================================================================
# OperatingProjection / OperatingProjectionLike (anchor.engine.contracts)
# =============================================================================

OPERATING_PROJECTION_EXPECTED_FIELD_NAMES = (
    "gross_potential_rent_by_year",
    "other_income_by_year",
    "vacancy_credit_loss_by_year",
    "effective_gross_income_by_year",
    "property_taxes_by_year",
    "insurance_by_year",
    "utilities_by_year",
    "repairs_maintenance_by_year",
    "other_operating_expenses_by_year",
    "management_fee_by_year",
    "total_operating_expenses_by_year",
    "noi_by_year",
    "exit_noi",
    "going_in_cap_rate",
)


def make_operating_projection() -> OperatingProjection:
    year_series = (600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286)
    return OperatingProjection(
        gross_potential_rent_by_year=year_series,
        other_income_by_year=year_series,
        vacancy_credit_loss_by_year=year_series,
        effective_gross_income_by_year=year_series,
        property_taxes_by_year=year_series,
        insurance_by_year=year_series,
        utilities_by_year=year_series,
        repairs_maintenance_by_year=year_series,
        other_operating_expenses_by_year=year_series,
        management_fee_by_year=year_series,
        total_operating_expenses_by_year=year_series,
        noi_by_year=year_series,
        exit_noi=695_564.44458,
        going_in_cap_rate=0.06,
    )


def test_operating_projection_has_exact_field_order_and_keyword_only_shape() -> None:
    contract_fields = fields(OperatingProjection)

    assert is_dataclass(OperatingProjection)
    assert tuple(field.name for field in contract_fields) == (
        OPERATING_PROJECTION_EXPECTED_FIELD_NAMES
    )
    assert len(contract_fields) == 14
    assert all(field.kw_only for field in contract_fields)
    assert OperatingProjection.__slots__ == OPERATING_PROJECTION_EXPECTED_FIELD_NAMES


def test_operating_projection_is_frozen_and_slotted() -> None:
    projection = make_operating_projection()

    assert not hasattr(projection, "__dict__")
    with pytest.raises(FrozenInstanceError):
        projection.exit_noi = 1.0  # type: ignore[misc]


def test_operating_projection_satisfies_operating_projection_like_by_field_presence() -> None:
    """Structural check (Protocol, not runtime-checkable): every field
    OperatingProjectionLike declares is present, by the correct name and
    type, on OperatingProjection."""

    projection = make_operating_projection()

    for field_name in ("noi_by_year", "exit_noi", "going_in_cap_rate"):
        assert hasattr(projection, field_name)

    assert isinstance(projection.noi_by_year, tuple)
    assert isinstance(projection.exit_noi, float)
    assert isinstance(projection.going_in_cap_rate, float)


def test_noi_forecast_also_satisfies_operating_projection_like_by_field_presence() -> None:
    """The existing, unmodified NoiForecast (Quick's projection contract)
    satisfies the same narrow shape -- confirming the downstream engine can
    be written against OperatingProjectionLike without caring which mode
    produced its projection."""

    forecast = NoiForecast(
        noi_by_year=(600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286),
        exit_noi=695_564.44458,
        going_in_cap_rate=0.06,
    )

    for field_name in ("noi_by_year", "exit_noi", "going_in_cap_rate"):
        assert hasattr(forecast, field_name)


def test_operating_projection_like_declares_exactly_the_three_narrow_fields() -> None:
    """OperatingProjectionLike must never grow to include a Detailed-only
    line-item schedule -- that would violate "do not make downstream
    calculations depend on detailed operating line items.\""""

    protocol_annotations = OperatingProjectionLike.__annotations__

    assert set(protocol_annotations) == {"noi_by_year", "exit_noi", "going_in_cap_rate"}


# =============================================================================
# Quick/V2 surface is completely unaffected by this gate
# =============================================================================


GOLDEN_V2_PAYLOAD = {
    "purchase_price": 10_000_000,
    "current_noi": 600_000,
    "occupancy": 0.95,
    "noi_growth": 0.03,
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


def test_old_fourteen_field_validation_and_construction_still_works() -> None:
    result = validate_acquisition_inputs(GOLDEN_V2_PAYLOAD)

    assert isinstance(result, AcquisitionInputs)
    assert result.current_noi == 600_000.0
    assert result.noi_growth == 0.03


def test_v2_golden_case_results_are_unchanged_by_gate_1() -> None:
    """No engine code changed at Gate 1 -- this pins the existing,
    already-frozen V2 golden case (docs/underwriting_v2_golden_case.md) as
    an explicit Gate 1 regression checkpoint, not just an implicit one."""

    inputs = validate_acquisition_inputs(GOLDEN_V2_PAYLOAD)
    results = analyze_acquisition(inputs)

    assert results.loan_amount == pytest.approx(6_000_000.0, rel=0.0, abs=1e-6)
    assert results.initial_equity == pytest.approx(4_260_000.0, rel=0.0, abs=1e-6)
    assert results.noi_by_year == pytest.approx(
        (600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286), rel=0.0, abs=1e-6
    )
    assert results.exit_noi == pytest.approx(695_564.44458, rel=0.0, abs=1e-5)
    assert results.headline_dscr == pytest.approx(2.0, rel=0.0, abs=1e-5)
    assert results.min_dscr == pytest.approx(1.64688, rel=0.0, abs=1e-5)
    assert results.unlevered_irr == pytest.approx(0.061388, rel=0.0, abs=1e-6)
    assert results.levered_irr == pytest.approx(0.073802, rel=0.0, abs=1e-6)
    assert results.equity_multiple == pytest.approx(1.38235, rel=0.0, abs=1e-5)
