"""Golden-case coverage for the Phase 2A subset of AcquisitionResults fields.

Values are taken from the "Golden Case" section of
``docs/phase_2_deterministic_engine.md``, restricted to the fields Phase 2A
actually produces (NOI forecast, exit NOI, going-in cap rate, loan amount,
initial equity).
"""

from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine.debt import calculate_capital_stack
from mini_anchor.engine.noi import forecast_noi


def make_golden_inputs() -> AcquisitionInputs:
    return AcquisitionInputs(
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


def test_golden_case_going_in_cap_rate() -> None:
    result = forecast_noi(make_golden_inputs())

    assert result.going_in_cap_rate == 0.05


def test_golden_case_noi_by_year() -> None:
    result = forecast_noi(make_golden_inputs())

    assert result.noi_by_year == (
        2_500_000.0,
        2_575_000.0,
        2_652_250.0,
        2_731_817.5,
        2_813_772.0250000004,
    )


def test_golden_case_exit_noi() -> None:
    result = forecast_noi(make_golden_inputs())

    assert result.exit_noi == 2_898_185.18575


def test_golden_case_loan_amount() -> None:
    result = calculate_capital_stack(make_golden_inputs())

    assert result.loan_amount == 32_500_000.0


def test_golden_case_initial_equity() -> None:
    result = calculate_capital_stack(make_golden_inputs())

    assert result.initial_equity == 17_500_000.0
