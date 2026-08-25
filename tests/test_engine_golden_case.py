"""Golden-case coverage for the Phase 2A/2B/2C subset of AcquisitionResults
fields.

Values are taken from the "Golden Case" section of
``docs/phase_2_deterministic_engine.md``, restricted to the fields Phase 2A,
Phase 2B, and Phase 2C actually produce (NOI forecast, exit NOI, going-in cap
rate, loan amount, initial equity, monthly debt service, annual debt service,
remaining loan balance, exit value, net sale proceeds, unlevered cash flows,
levered cash flows).
"""

from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine.acquisition import calculate_acquisition_cash_flows
from mini_anchor.engine.debt import calculate_capital_stack, calculate_debt_schedule
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


def test_golden_case_monthly_debt_service() -> None:
    result = calculate_debt_schedule(make_golden_inputs())

    assert result.monthly_debt_service == 179466.20319611699


def test_golden_case_annual_debt_service() -> None:
    result = calculate_debt_schedule(make_golden_inputs())

    assert result.annual_debt_service == (
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
    )


def test_golden_case_remaining_loan_balance() -> None:
    result = calculate_debt_schedule(make_golden_inputs())

    assert result.remaining_loan_balance == 29948583.641211268


def test_golden_case_exit_value() -> None:
    result = calculate_acquisition_cash_flows(make_golden_inputs())

    assert result.exit_value == 52694276.10454546


def test_golden_case_net_sale_proceeds() -> None:
    result = calculate_acquisition_cash_flows(make_golden_inputs())

    assert result.net_sale_proceeds == 22745692.46333419


def test_golden_case_unlevered_cash_flows() -> None:
    result = calculate_acquisition_cash_flows(make_golden_inputs())

    assert result.unlevered_cash_flows == (
        -50000000.0,
        2500000.0,
        2575000.0,
        2652250.0,
        2731817.5,
        55508048.12954546,
    )


def test_golden_case_levered_cash_flows() -> None:
    result = calculate_acquisition_cash_flows(make_golden_inputs())

    assert result.levered_cash_flows == (
        -17500000.0,
        346405.56164659606,
        421405.56164659606,
        498655.56164659606,
        578223.0616465961,
        23405870.04998079,
    )
