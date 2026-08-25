import math

import pytest

from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine.contracts import NoiForecast, NonFiniteResultError
from mini_anchor.engine.noi import (
    calculate_exit_noi,
    calculate_going_in_cap_rate,
    calculate_noi_by_year,
    forecast_noi,
)


# Stringent absolute tolerance for financial outputs: the no-intermediate-
# rounding convention (docs/financial_conventions.md "Numeric Precision and
# Rounding") forbids presentation-scale rounding, so tests must reject
# whole-dollar or cent-level error while still tolerating ordinary IEEE-754
# last-bit noise (observed here on the order of 1e-9 to 1e-6 for these
# single- and few-operation calculations). Default ``pytest.approx`` relative
# tolerance (1e-6 of the expected value) permits multi-dollar error at
# million-dollar scale and must not be used for these assertions.
def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-6)


def make_inputs(**overrides: object) -> AcquisitionInputs:
    defaults = dict(
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
    defaults.update(overrides)
    return AcquisitionInputs(**defaults)  # type: ignore[arg-type]


# --- calculate_noi_by_year ---------------------------------------------


def test_noi_by_year_hold_period_one_is_single_element_equal_to_current_noi() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=2_500_000.0, noi_growth=0.03, hold_period=1)

    assert noi_by_year == (2_500_000.0,)


def test_noi_by_year_hold_period_greater_than_one_has_length_equal_to_hold_period() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=1_000_000.0, noi_growth=0.05, hold_period=7)

    assert len(noi_by_year) == 7


def test_noi_by_year_current_noi_zero_is_all_zero_regardless_of_growth() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=0.0, noi_growth=0.25, hold_period=5)

    assert noi_by_year == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_noi_by_year_zero_growth_is_flat() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=2_000_000.0, noi_growth=0.0, hold_period=4)

    assert noi_by_year == (2_000_000.0, 2_000_000.0, 2_000_000.0, 2_000_000.0)


def test_noi_by_year_positive_growth_compounds() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=1_000_000.0, noi_growth=0.10, hold_period=3)

    assert noi_by_year == strict((1_000_000.0, 1_100_000.0, 1_210_000.0))


def test_noi_by_year_negative_growth_greater_than_negative_one_decays() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=1_000_000.0, noi_growth=-0.10, hold_period=3)

    assert noi_by_year == strict((1_000_000.0, 900_000.0, 810_000.0))
    assert noi_by_year[0] > noi_by_year[1] > noi_by_year[2] > 0.0


def test_noi_by_year_year_one_never_reflects_growth() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=5_000_000.0, noi_growth=0.5, hold_period=2)

    assert noi_by_year[0] == 5_000_000.0


def test_noi_by_year_golden_case_exact_expected_tuple() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=2_500_000.0, noi_growth=0.03, hold_period=5)

    assert noi_by_year == (
        2_500_000.0,
        2_575_000.0,
        2_652_250.0,
        2_731_817.5,
        2_813_772.0250000004,
    )


# --- calculate_exit_noi ---------------------------------------------------


def test_exit_noi_golden_case_exact_expected_value() -> None:
    exit_noi = calculate_exit_noi(current_noi=2_500_000.0, noi_growth=0.03, hold_period=5)

    assert exit_noi == 2_898_185.18575


def test_exit_noi_zero_growth_equals_current_noi() -> None:
    exit_noi = calculate_exit_noi(current_noi=1_000_000.0, noi_growth=0.0, hold_period=5)

    assert exit_noi == 1_000_000.0


def test_exit_noi_hold_period_one() -> None:
    exit_noi = calculate_exit_noi(current_noi=1_000_000.0, noi_growth=0.1, hold_period=1)

    assert exit_noi == 1_100_000.0


def test_exit_noi_negative_growth_regression() -> None:
    # Explicit regression: current_noi = 100, noi_growth = -0.10, hold_period = 3
    # must produce Exit NOI = 100 * (1 - 0.10)^3 = 72.9 exactly, per
    # docs/financial_conventions.md "Exit value". A future implementation
    # that rounds this result (e.g. to 72.0 or 72.90) must fail here.
    exit_noi = calculate_exit_noi(current_noi=100.0, noi_growth=-0.10, hold_period=3)

    assert exit_noi == 72.9


def test_exit_noi_is_one_growth_period_beyond_final_hold_year_noi() -> None:
    current_noi = 1_000_000.0
    noi_growth = 0.04
    hold_period = 6

    noi_by_year = calculate_noi_by_year(
        current_noi=current_noi, noi_growth=noi_growth, hold_period=hold_period
    )
    exit_noi = calculate_exit_noi(
        current_noi=current_noi, noi_growth=noi_growth, hold_period=hold_period
    )

    assert exit_noi == strict(noi_by_year[-1] * (1 + noi_growth))
    assert exit_noi != noi_by_year[-1]


# --- calculate_going_in_cap_rate -------------------------------------------


def test_going_in_cap_rate_ordinary_case() -> None:
    going_in_cap_rate = calculate_going_in_cap_rate(
        current_noi=2_500_000.0, purchase_price=50_000_000.0
    )

    assert going_in_cap_rate == 0.05


def test_going_in_cap_rate_zero_current_noi_is_zero_not_error() -> None:
    going_in_cap_rate = calculate_going_in_cap_rate(
        current_noi=0.0, purchase_price=50_000_000.0
    )

    assert going_in_cap_rate == 0.0


def test_going_in_cap_rate_golden_case_exact_expected_value() -> None:
    going_in_cap_rate = calculate_going_in_cap_rate(
        current_noi=2_500_000.0, purchase_price=50_000_000.0
    )

    assert going_in_cap_rate == 0.05


def test_going_in_cap_rate_division_overflow_raises_non_finite_result_error() -> None:
    # Phase 0-valid: current_noi is a very large finite positive float and
    # purchase_price is a very small finite positive float (purchase_price
    # > 0 is the only Phase 0 domain constraint). The division current_noi /
    # purchase_price overflows IEEE-754 double precision.
    assert math.isfinite(1.5e308)
    assert math.isfinite(1e-300)

    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_going_in_cap_rate(current_noi=1.5e308, purchase_price=1e-300)

    assert exc_info.value.field_name == "going_in_cap_rate"


def test_going_in_cap_rate_zero_numerator_with_tiny_purchase_price_is_still_zero() -> None:
    going_in_cap_rate = calculate_going_in_cap_rate(current_noi=0.0, purchase_price=1e-300)

    assert going_in_cap_rate == 0.0


# --- occupancy has no effect ------------------------------------------------


def test_occupancy_does_not_affect_noi_by_year() -> None:
    low_occupancy = calculate_noi_by_year(current_noi=2_500_000.0, noi_growth=0.03, hold_period=5)
    # calculate_noi_by_year has no occupancy parameter at all, so this is
    # exercised via forecast_noi against two AcquisitionInputs that differ
    # only in occupancy.
    inputs_low = make_inputs(occupancy=0.10)
    inputs_high = make_inputs(occupancy=1.0)

    assert forecast_noi(inputs_low).noi_by_year == forecast_noi(inputs_high).noi_by_year
    assert forecast_noi(inputs_low).noi_by_year == low_occupancy


def test_same_financial_inputs_different_occupancy_produce_identical_noi_results() -> None:
    inputs_a = make_inputs(occupancy=0.0)
    inputs_b = make_inputs(occupancy=0.5)
    inputs_c = make_inputs(occupancy=1.0)

    result_a = forecast_noi(inputs_a)
    result_b = forecast_noi(inputs_b)
    result_c = forecast_noi(inputs_c)

    assert result_a.noi_by_year == result_b.noi_by_year == result_c.noi_by_year
    assert result_a.exit_noi == result_b.exit_noi == result_c.exit_noi
    assert (
        result_a.going_in_cap_rate
        == result_b.going_in_cap_rate
        == result_c.going_in_cap_rate
    )


# --- non-finite safety -------------------------------------------------------


def test_noi_by_year_overflow_raises_non_finite_result_error() -> None:
    # Phase 0-valid: current_noi >= 0, noi_growth > -1 with no upper bound,
    # hold_period >= 1 integer with no upper bound. This combination compounds
    # to an IEEE-754 double overflow.
    with pytest.raises(NonFiniteResultError):
        calculate_noi_by_year(current_noi=1.0, noi_growth=1e300, hold_period=3)


def test_exit_noi_overflow_raises_non_finite_result_error() -> None:
    with pytest.raises(NonFiniteResultError):
        calculate_exit_noi(current_noi=1.0, noi_growth=1e300, hold_period=3)


def test_forecast_noi_overflow_raises_non_finite_result_error() -> None:
    inputs = make_inputs(current_noi=1.0, noi_growth=1e300, hold_period=3)

    with pytest.raises(NonFiniteResultError):
        forecast_noi(inputs)


def test_noi_by_year_finite_factor_multiplication_overflow_raises_non_finite_result_error() -> None:
    # Regression for the multiplication-overflow path, distinct from the
    # exponentiation-OverflowError path exercised above: current_noi and the
    # growth factor (1 + noi_growth)**(y - 1) are each individually finite,
    # but their product overflows IEEE-754 double precision. Python float
    # multiplication silently returns inf on overflow (unlike float ** int,
    # which raises OverflowError), so this exercises a different code path
    # in ``_growth_factor`` / ``calculate_noi_by_year``.
    current_noi = 1.5e308
    noi_growth = 1.0
    growth_factor = (1 + noi_growth) ** (2 - 1)
    assert math.isfinite(current_noi)
    assert math.isfinite(growth_factor)
    assert not math.isfinite(current_noi * growth_factor)

    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_noi_by_year(current_noi=current_noi, noi_growth=noi_growth, hold_period=2)

    assert exc_info.value.field_name == "noi_by_year[1]"


def test_exit_noi_finite_factor_multiplication_overflow_raises_non_finite_result_error() -> None:
    current_noi = 1.5e308
    noi_growth = 1.0
    growth_factor = (1 + noi_growth) ** 1
    assert math.isfinite(current_noi)
    assert math.isfinite(growth_factor)
    assert not math.isfinite(current_noi * growth_factor)

    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_exit_noi(current_noi=current_noi, noi_growth=noi_growth, hold_period=1)

    assert exc_info.value.field_name == "exit_noi"


def test_noi_by_year_zero_current_noi_does_not_overflow_even_with_extreme_growth() -> None:
    noi_by_year = calculate_noi_by_year(current_noi=0.0, noi_growth=1e300, hold_period=3)

    assert noi_by_year == (0.0, 0.0, 0.0)


def test_exit_noi_zero_current_noi_does_not_overflow_even_with_extreme_growth() -> None:
    exit_noi = calculate_exit_noi(current_noi=0.0, noi_growth=1e300, hold_period=3)

    assert exit_noi == 0.0


def test_valid_zero_is_not_mistaken_for_non_finite_failure() -> None:
    inputs = make_inputs(current_noi=0.0, noi_growth=0.5, hold_period=5)

    result = forecast_noi(inputs)

    assert result.noi_by_year == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert result.exit_noi == 0.0
    assert result.going_in_cap_rate == 0.0


# --- forecast_noi contract shape and determinism ----------------------------


def test_forecast_noi_returns_noi_forecast_with_expected_field_values() -> None:
    inputs = make_inputs()

    result = forecast_noi(inputs)

    assert isinstance(result, NoiForecast)
    assert result.noi_by_year == (
        2_500_000.0,
        2_575_000.0,
        2_652_250.0,
        2_731_817.5,
        2_813_772.0250000004,
    )
    assert result.exit_noi == 2_898_185.18575
    assert result.going_in_cap_rate == 0.05


def test_repeated_calls_with_same_inputs_produce_identical_noi_results() -> None:
    inputs = make_inputs()

    first = forecast_noi(inputs)
    second = forecast_noi(inputs)

    assert first == second


def test_calculate_noi_by_year_repeated_calls_are_bit_identical() -> None:
    first = calculate_noi_by_year(current_noi=2_500_000.0, noi_growth=0.03, hold_period=5)
    second = calculate_noi_by_year(current_noi=2_500_000.0, noi_growth=0.03, hold_period=5)

    assert first == second
