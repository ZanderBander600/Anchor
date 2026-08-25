"""Golden-case coverage for the Phase 2A/2B/2C/2D subset of AcquisitionResults
fields.

Values are taken from the "Golden Case" section of
``docs/phase_2_deterministic_engine.md``, restricted to the fields Phase 2A,
Phase 2B, Phase 2C, and Phase 2D actually produce (NOI forecast, exit NOI,
going-in cap rate, loan amount, initial equity, monthly debt service, annual
debt service, remaining loan balance, exit value, net sale proceeds,
unlevered cash flows, levered cash flows, DSCR by year, headline DSCR,
equity multiple, unlevered IRR, levered IRR).
"""

import pytest

from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine.acquisition import calculate_acquisition_cash_flows
from mini_anchor.engine.debt import calculate_capital_stack, calculate_debt_schedule
from mini_anchor.engine.noi import forecast_noi
from mini_anchor.engine.returns import calculate_return_metrics


# Stringent absolute tolerance mirroring tests/test_engine_returns.py: rejects
# presentation-scale rounding while tolerating ordinary IEEE-754 last-bit
# noise from the bisection-based IRR solver.
def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def make_golden_return_metrics():
    inputs = make_golden_inputs()
    noi_forecast = forecast_noi(inputs)
    debt_schedule = calculate_debt_schedule(inputs)
    cash_flows = calculate_acquisition_cash_flows(inputs)

    return calculate_return_metrics(
        noi_by_year=noi_forecast.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        unlevered_cash_flows=cash_flows.unlevered_cash_flows,
        levered_cash_flows=cash_flows.levered_cash_flows,
    )


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


def test_golden_case_dscr_by_year() -> None:
    result = make_golden_return_metrics()

    assert result.dscr_by_year == (
        strict(1.1608499518189),
        strict(1.195675450373467),
        strict(1.231545713884671),
        strict(1.2684920853012112),
        strict(1.3065468478602478),
    )


def test_golden_case_headline_dscr() -> None:
    result = make_golden_return_metrics()

    assert result.headline_dscr == strict(1.1608499518189)
    assert result.headline_dscr == result.dscr_by_year[0]


def test_golden_case_equity_multiple() -> None:
    result = make_golden_return_metrics()

    assert result.equity_multiple == strict(1.44288913123241)


def test_golden_case_unlevered_irr() -> None:
    result = make_golden_return_metrics()

    assert result.unlevered_irr == strict(0.062414943980353854)


def test_golden_case_levered_irr() -> None:
    result = make_golden_return_metrics()

    assert result.levered_irr == strict(0.07913030056780745)
