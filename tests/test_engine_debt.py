import pytest

from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine.contracts import CapitalStack
from mini_anchor.engine.debt import (
    calculate_capital_stack,
    calculate_initial_equity,
    calculate_loan_amount,
)


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


# --- calculate_loan_amount --------------------------------------------------


def test_loan_amount_ltv_zero_is_zero() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=0.0)

    assert loan_amount == 0.0


def test_loan_amount_ltv_one_equals_purchase_price() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=1.0)

    assert loan_amount == 50_000_000.0


def test_loan_amount_ordinary_ltv_golden_case_exact_value() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=0.65)

    assert loan_amount == 32_500_000.0


def test_loan_amount_non_round_friendly_case_rejects_dollar_or_cent_rounding() -> None:
    # Regression: purchase_price and ltv chosen so loan_amount lands on a
    # sub-cent fractional dollar value. A future implementation that rounds
    # loan_amount to the nearest cent (7576543.15) or nearest dollar
    # (7576543.0) before returning it must fail this exact-equality check.
    loan_amount = calculate_loan_amount(purchase_price=12_345_678.91, ltv=0.6137)

    assert loan_amount == 7576543.147067


# --- calculate_initial_equity -----------------------------------------------


def test_initial_equity_ltv_zero_equals_purchase_price() -> None:
    initial_equity = calculate_initial_equity(purchase_price=50_000_000.0, loan_amount=0.0)

    assert initial_equity == 50_000_000.0


def test_initial_equity_ltv_one_is_zero() -> None:
    initial_equity = calculate_initial_equity(
        purchase_price=50_000_000.0, loan_amount=50_000_000.0
    )

    assert initial_equity == 0.0


def test_initial_equity_ordinary_ltv_golden_case_exact_value() -> None:
    loan_amount = calculate_loan_amount(purchase_price=50_000_000.0, ltv=0.65)
    initial_equity = calculate_initial_equity(
        purchase_price=50_000_000.0, loan_amount=loan_amount
    )

    assert initial_equity == 17_500_000.0


def test_initial_equity_non_round_friendly_case_rejects_dollar_or_cent_rounding() -> None:
    # Regression: mirrors the non-round loan_amount case above so a future
    # implementation that rounds initial_equity to the nearest cent
    # (4769135.76) or nearest dollar (4769136.0) fails this check.
    loan_amount = calculate_loan_amount(purchase_price=12_345_678.91, ltv=0.6137)
    initial_equity = calculate_initial_equity(
        purchase_price=12_345_678.91, loan_amount=loan_amount
    )

    assert initial_equity == 4769135.762933


# --- capital stack composition ----------------------------------------------


@pytest.mark.parametrize("ltv", [0.0, 1.0, 0.65])
def test_loan_amount_plus_initial_equity_equals_purchase_price(ltv: float) -> None:
    purchase_price = 50_000_000.0
    loan_amount = calculate_loan_amount(purchase_price=purchase_price, ltv=ltv)
    initial_equity = calculate_initial_equity(
        purchase_price=purchase_price, loan_amount=loan_amount
    )

    assert loan_amount + initial_equity == purchase_price


def test_calculate_capital_stack_returns_capital_stack_with_expected_field_values() -> None:
    inputs = make_inputs()

    result = calculate_capital_stack(inputs)

    assert isinstance(result, CapitalStack)
    assert result.loan_amount == 32_500_000.0
    assert result.initial_equity == 17_500_000.0


def test_calculate_capital_stack_ltv_zero() -> None:
    inputs = make_inputs(ltv=0.0)

    result = calculate_capital_stack(inputs)

    assert result.loan_amount == 0.0
    assert result.initial_equity == inputs.purchase_price


def test_calculate_capital_stack_ltv_one() -> None:
    inputs = make_inputs(ltv=1.0)

    result = calculate_capital_stack(inputs)

    assert result.loan_amount == inputs.purchase_price
    assert result.initial_equity == 0.0


def test_repeated_calls_with_same_inputs_produce_identical_capital_stack_results() -> None:
    inputs = make_inputs()

    first = calculate_capital_stack(inputs)
    second = calculate_capital_stack(inputs)

    assert first == second
