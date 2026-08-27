"""Phase 2C tests: exit value, net sale proceeds, unlevered/levered cash flows.

Restates ``docs/financial_conventions.md`` "Exit value" / "Cash-Flow Timing"
and ``docs/phase_2_deterministic_engine.md`` "Phase 2C -- Exit Value" /
"Unlevered Cash Flows" / "Levered Cash Flows" exactly; those documents govern
on any discrepancy.
"""

import math

import pytest

from anchor.contracts import AcquisitionInputs
from anchor.engine.contracts import AcquisitionCashFlows, NonFiniteResultError
from anchor.engine.acquisition import (
    calculate_acquisition_cash_flows,
    calculate_exit_value,
    calculate_levered_cash_flows,
    calculate_net_sale_proceeds,
    calculate_unlevered_cash_flows,
)
from anchor.engine.debt import calculate_capital_stack, calculate_debt_schedule
from anchor.engine.noi import calculate_exit_noi, forecast_noi


# Stringent absolute tolerance for financial outputs, mirroring
# tests/test_engine_noi.py and tests/test_engine_debt.py: rejects
# whole-dollar/cent rounding while tolerating ordinary IEEE-754 last-bit
# noise.
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


# =============================================================================
# Exit value
# =============================================================================


def test_exit_value_ordinary_case_golden_case_exact_value() -> None:
    exit_value = calculate_exit_value(exit_noi=2_898_185.18575, exit_cap_rate=0.055)

    assert exit_value == 52694276.10454546


def test_exit_value_hold_period_one() -> None:
    exit_noi = calculate_exit_noi(current_noi=1_000_000.0, noi_growth=0.1, hold_period=1)
    exit_value = calculate_exit_value(exit_noi=exit_noi, exit_cap_rate=0.05)

    assert exit_noi == 1_100_000.0
    assert exit_value == 22_000_000.0


def test_exit_value_zero_growth() -> None:
    exit_noi = calculate_exit_noi(current_noi=2_000_000.0, noi_growth=0.0, hold_period=4)
    exit_value = calculate_exit_value(exit_noi=exit_noi, exit_cap_rate=0.05)

    assert exit_noi == 2_000_000.0
    assert exit_value == 40_000_000.0


def test_exit_value_positive_growth() -> None:
    exit_value = calculate_exit_value(exit_noi=2_898_185.18575, exit_cap_rate=0.055)

    assert exit_value == strict(52_694_276.10454546)


def test_exit_value_negative_growth() -> None:
    exit_noi = calculate_exit_noi(current_noi=100.0, noi_growth=-0.10, hold_period=3)
    exit_value = calculate_exit_value(exit_noi=exit_noi, exit_cap_rate=0.06)

    assert exit_noi == 72.9
    assert exit_value == strict(1215.0)


def test_exit_value_uses_forward_exit_noi_not_noi_h() -> None:
    inputs = make_inputs(noi_growth=0.03, hold_period=5)
    noi_forecast = forecast_noi(inputs)

    exit_value_using_exit_noi = calculate_exit_value(
        exit_noi=noi_forecast.exit_noi, exit_cap_rate=inputs.exit_cap_rate
    )
    exit_value_if_it_wrongly_used_noi_h = calculate_exit_value(
        exit_noi=noi_forecast.noi_by_year[-1], exit_cap_rate=inputs.exit_cap_rate
    )

    assert noi_forecast.exit_noi != noi_forecast.noi_by_year[-1]
    assert exit_value_using_exit_noi != exit_value_if_it_wrongly_used_noi_h
    assert exit_value_using_exit_noi == 52694276.10454546


def test_exit_value_does_not_use_noi_h() -> None:
    inputs = make_inputs()
    noi_forecast = forecast_noi(inputs)
    exit_value = calculate_exit_value(
        exit_noi=noi_forecast.exit_noi, exit_cap_rate=inputs.exit_cap_rate
    )

    assert exit_value != noi_forecast.noi_by_year[-1] / inputs.exit_cap_rate


def test_exit_value_no_sale_costs_is_gross_division_only() -> None:
    # Sale costs are 0 (Phase 0 exclusion): exit_value is exactly exit_noi /
    # exit_cap_rate with no deduction of any kind.
    exit_value = calculate_exit_value(exit_noi=10_000_000.0, exit_cap_rate=0.05)

    assert exit_value == 200_000_000.0


def test_exit_value_non_finite_raises() -> None:
    # Phase 0-valid: exit_noi is a very large finite positive float and
    # exit_cap_rate is a very small finite positive float (exit_cap_rate > 0
    # is the only Phase 0 domain constraint). The division overflows.
    assert math.isfinite(1.5e308)
    assert math.isfinite(1e-300)

    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_exit_value(exit_noi=1.5e308, exit_cap_rate=1e-300)

    assert exc_info.value.field_name == "exit_value"


# =============================================================================
# Net sale proceeds
# =============================================================================


def test_net_sale_proceeds_ordinary_debt_golden_case_exact_value() -> None:
    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=52694276.10454546, remaining_loan_balance=29948583.641211268
    )

    assert net_sale_proceeds == 22745692.46333419


def test_net_sale_proceeds_zero_leverage_equals_exit_value() -> None:
    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=52694276.10454546, remaining_loan_balance=0.0
    )

    assert net_sale_proceeds == 52694276.10454546


def test_net_sale_proceeds_fully_amortized_before_exit_equals_exit_value() -> None:
    inputs = make_inputs(amortization=3, hold_period=5)
    debt_schedule = calculate_debt_schedule(inputs)
    assert debt_schedule.remaining_loan_balance == 0.0

    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=100_000_000.0, remaining_loan_balance=debt_schedule.remaining_loan_balance
    )

    assert net_sale_proceeds == 100_000_000.0


def test_net_sale_proceeds_maturity_exactly_at_exit_equals_exit_value() -> None:
    inputs = make_inputs(amortization=5, hold_period=5)
    debt_schedule = calculate_debt_schedule(inputs)
    assert debt_schedule.remaining_loan_balance == 0.0

    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=100_000_000.0, remaining_loan_balance=debt_schedule.remaining_loan_balance
    )

    assert net_sale_proceeds == 100_000_000.0


def test_net_sale_proceeds_loan_outstanding_at_exit_is_less_than_exit_value() -> None:
    inputs = make_inputs(amortization=30, hold_period=5)
    debt_schedule = calculate_debt_schedule(inputs)
    assert debt_schedule.remaining_loan_balance > 0.0

    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=100_000_000.0, remaining_loan_balance=debt_schedule.remaining_loan_balance
    )

    assert net_sale_proceeds < 100_000_000.0


def test_net_sale_proceeds_equals_exit_value_minus_remaining_balance() -> None:
    exit_value = 12_345_678.91
    remaining_loan_balance = 3_456_789.12

    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=exit_value, remaining_loan_balance=remaining_loan_balance
    )

    assert net_sale_proceeds == exit_value - remaining_loan_balance


def test_net_sale_proceeds_non_finite_raises() -> None:
    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_net_sale_proceeds(exit_value=1.7e308, remaining_loan_balance=-1.7e308)

    assert exc_info.value.field_name == "net_sale_proceeds"


# =============================================================================
# Unlevered cash flows
# =============================================================================


def test_unlevered_cash_flows_time_zero_is_negative_purchase_price() -> None:
    cash_flows = calculate_unlevered_cash_flows(
        purchase_price=500.0, noi_by_year=(100.0, 200.0, 300.0), exit_value=1000.0
    )

    assert cash_flows[0] == -500.0


def test_unlevered_cash_flows_length_is_hold_period_plus_one() -> None:
    cash_flows = calculate_unlevered_cash_flows(
        purchase_price=500.0, noi_by_year=(100.0, 200.0, 300.0), exit_value=1000.0
    )

    assert len(cash_flows) == 4  # H = 3


def test_unlevered_cash_flows_intermediate_years_contain_noi_only() -> None:
    cash_flows = calculate_unlevered_cash_flows(
        purchase_price=500.0, noi_by_year=(100.0, 200.0, 300.0), exit_value=1000.0
    )

    assert cash_flows[1] == 100.0
    assert cash_flows[2] == 200.0


def test_unlevered_cash_flows_final_year_is_noi_h_plus_exit_value() -> None:
    cash_flows = calculate_unlevered_cash_flows(
        purchase_price=500.0, noi_by_year=(100.0, 200.0, 300.0), exit_value=1000.0
    )

    assert cash_flows[3] == 1300.0  # NOI_3 (300.0) + exit_value (1000.0)


def test_unlevered_cash_flows_exact_tuple() -> None:
    cash_flows = calculate_unlevered_cash_flows(
        purchase_price=500.0, noi_by_year=(100.0, 200.0, 300.0), exit_value=1000.0
    )

    assert cash_flows == (-500.0, 100.0, 200.0, 1300.0)


def test_unlevered_cash_flows_hold_period_one() -> None:
    cash_flows = calculate_unlevered_cash_flows(
        purchase_price=10_000.0, noi_by_year=(500.0,), exit_value=2000.0
    )

    assert cash_flows == (-10_000.0, 2500.0)
    assert len(cash_flows) == 2


def test_unlevered_cash_flows_exit_noi_not_double_counted() -> None:
    # exit_value already folds in exit_noi (NOI_(H+1)); it must not be added
    # again as a separate operating cash flow anywhere in the series.
    inputs = make_inputs(noi_growth=0.03, hold_period=5)
    noi_forecast = forecast_noi(inputs)
    exit_value = calculate_exit_value(
        exit_noi=noi_forecast.exit_noi, exit_cap_rate=inputs.exit_cap_rate
    )

    cash_flows = calculate_unlevered_cash_flows(
        purchase_price=inputs.purchase_price,
        noi_by_year=noi_forecast.noi_by_year,
        exit_value=exit_value,
    )

    expected_final = noi_forecast.noi_by_year[-1] + exit_value
    assert cash_flows[-1] == expected_final
    # A wrong implementation that also added exit_noi would produce a
    # different (larger) final entry.
    assert cash_flows[-1] != expected_final + noi_forecast.exit_noi


def test_unlevered_cash_flows_no_debt_appears() -> None:
    # Unlevered cash flows must be identical regardless of leverage, since
    # purchase_price, NOI, and exit_value are all leverage-independent.
    zero_leverage = calculate_acquisition_cash_flows(make_inputs(ltv=0.0))
    full_leverage = calculate_acquisition_cash_flows(make_inputs(ltv=1.0))
    ordinary_leverage = calculate_acquisition_cash_flows(make_inputs(ltv=0.65))

    assert zero_leverage.unlevered_cash_flows == full_leverage.unlevered_cash_flows
    assert zero_leverage.unlevered_cash_flows == ordinary_leverage.unlevered_cash_flows


def test_unlevered_cash_flows_no_rounding() -> None:
    cash_flows = calculate_unlevered_cash_flows(
        purchase_price=12_345_678.91,
        noi_by_year=(1_234_567.891,),
        exit_value=9_876_543.219,
    )

    expected_final = 1_234_567.891 + 9_876_543.219
    assert cash_flows[1] == expected_final
    assert cash_flows[1] != round(cash_flows[1], 2)


def test_unlevered_cash_flows_non_finite_raises() -> None:
    with pytest.raises(NonFiniteResultError):
        calculate_unlevered_cash_flows(
            purchase_price=500.0, noi_by_year=(1.5e308,), exit_value=1.5e308
        )


# =============================================================================
# Levered cash flows
# =============================================================================


def test_levered_cash_flows_time_zero_is_negative_initial_equity() -> None:
    cash_flows = calculate_levered_cash_flows(
        initial_equity=250.0,
        noi_by_year=(100.0, 200.0, 300.0),
        annual_debt_service=(10.0, 20.0, 30.0),
        net_sale_proceeds=995.0,
    )

    assert cash_flows[0] == -250.0


def test_levered_cash_flows_length_is_hold_period_plus_one() -> None:
    cash_flows = calculate_levered_cash_flows(
        initial_equity=250.0,
        noi_by_year=(100.0, 200.0, 300.0),
        annual_debt_service=(10.0, 20.0, 30.0),
        net_sale_proceeds=995.0,
    )

    assert len(cash_flows) == 4  # H = 3


def test_levered_cash_flows_intermediate_years_are_noi_minus_ads() -> None:
    cash_flows = calculate_levered_cash_flows(
        initial_equity=250.0,
        noi_by_year=(100.0, 200.0, 300.0),
        annual_debt_service=(10.0, 20.0, 30.0),
        net_sale_proceeds=995.0,
    )

    assert cash_flows[1] == 90.0  # 100 - 10
    assert cash_flows[2] == 180.0  # 200 - 20


def test_levered_cash_flows_final_year_is_noi_minus_ads_plus_net_sale_proceeds() -> None:
    cash_flows = calculate_levered_cash_flows(
        initial_equity=250.0,
        noi_by_year=(100.0, 200.0, 300.0),
        annual_debt_service=(10.0, 20.0, 30.0),
        net_sale_proceeds=995.0,
    )

    assert cash_flows[3] == 1265.0  # 300 - 30 + 995


def test_levered_cash_flows_exact_tuple() -> None:
    cash_flows = calculate_levered_cash_flows(
        initial_equity=250.0,
        noi_by_year=(100.0, 200.0, 300.0),
        annual_debt_service=(10.0, 20.0, 30.0),
        net_sale_proceeds=995.0,
    )

    assert cash_flows == (-250.0, 90.0, 180.0, 1265.0)


def test_levered_cash_flows_hold_period_one() -> None:
    cash_flows = calculate_levered_cash_flows(
        initial_equity=6_000.0,
        noi_by_year=(500.0,),
        annual_debt_service=(50.0,),
        net_sale_proceeds=1900.0,
    )

    assert cash_flows == (-6_000.0, 2350.0)  # -6000, then 500 - 50 + 1900
    assert len(cash_flows) == 2


def test_levered_cash_flows_zero_leverage_equals_unlevered_cash_flows() -> None:
    result = calculate_acquisition_cash_flows(make_inputs(ltv=0.0))

    assert result.levered_cash_flows == result.unlevered_cash_flows


def test_levered_cash_flows_100_percent_leverage_time_zero_is_zero() -> None:
    result = calculate_acquisition_cash_flows(make_inputs(ltv=1.0))

    assert result.levered_cash_flows[0] == 0.0


def test_levered_cash_flows_a_less_than_h() -> None:
    inputs = make_inputs(amortization=3, hold_period=5)
    result = calculate_acquisition_cash_flows(inputs)
    debt_schedule = calculate_debt_schedule(inputs)
    noi_forecast = forecast_noi(inputs)

    assert debt_schedule.annual_debt_service[3] == 0.0
    assert debt_schedule.annual_debt_service[4] == 0.0
    # Years after amortization: LCF_y == NOI_y (no debt service deducted).
    assert result.levered_cash_flows[4] == noi_forecast.noi_by_year[3]
    assert result.net_sale_proceeds == result.exit_value  # fully amortized: B_exit = 0


def test_levered_cash_flows_a_equals_h() -> None:
    inputs = make_inputs(amortization=5, hold_period=5)
    result = calculate_acquisition_cash_flows(inputs)

    assert result.net_sale_proceeds == result.exit_value  # maturity exactly at exit


def test_levered_cash_flows_a_greater_than_h() -> None:
    inputs = make_inputs(amortization=30, hold_period=5)
    result = calculate_acquisition_cash_flows(inputs)

    assert result.net_sale_proceeds < result.exit_value  # loan outstanding at exit


def test_levered_cash_flows_loan_payoff_occurs_exactly_once() -> None:
    # net_sale_proceeds (which folds in the loan payoff) must appear only in
    # the final entry; every intermediate entry is exactly NOI_y - ADS_y.
    noi_by_year = (100.0, 200.0, 300.0, 400.0)
    annual_debt_service = (10.0, 20.0, 30.0, 40.0)
    net_sale_proceeds = 5000.0

    cash_flows = calculate_levered_cash_flows(
        initial_equity=1_000.0,
        noi_by_year=noi_by_year,
        annual_debt_service=annual_debt_service,
        net_sale_proceeds=net_sale_proceeds,
    )

    for year in range(1, len(noi_by_year)):
        expected = noi_by_year[year - 1] - annual_debt_service[year - 1]
        assert cash_flows[year] == expected
    assert cash_flows[-1] == noi_by_year[-1] - annual_debt_service[-1] + net_sale_proceeds


def test_levered_cash_flows_no_sale_proceeds_before_final_year() -> None:
    inputs = make_inputs(noi_growth=0.03, hold_period=5)
    result = calculate_acquisition_cash_flows(inputs)
    debt_schedule = calculate_debt_schedule(inputs)
    noi_forecast = forecast_noi(inputs)

    for year in range(1, 5):
        expected = noi_forecast.noi_by_year[year - 1] - debt_schedule.annual_debt_service[year - 1]
        assert result.levered_cash_flows[year] == expected


def test_levered_cash_flows_no_exit_noi_double_counting() -> None:
    inputs = make_inputs(noi_growth=0.03, hold_period=5)
    result = calculate_acquisition_cash_flows(inputs)
    noi_forecast = forecast_noi(inputs)
    debt_schedule = calculate_debt_schedule(inputs)

    expected_final = (
        noi_forecast.noi_by_year[-1] - debt_schedule.annual_debt_service[-1] + result.net_sale_proceeds
    )
    assert result.levered_cash_flows[-1] == expected_final
    assert result.levered_cash_flows[-1] != expected_final + noi_forecast.exit_noi


def test_levered_cash_flows_no_rounding() -> None:
    cash_flows = calculate_levered_cash_flows(
        initial_equity=1_234.567,
        noi_by_year=(1_234_567.891,),
        annual_debt_service=(98_765.4321,),
        net_sale_proceeds=9_876_543.219,
    )

    expected_final = 1_234_567.891 - 98_765.4321 + 9_876_543.219
    assert cash_flows[1] == expected_final
    assert cash_flows[1] != round(cash_flows[1], 2)


def test_levered_cash_flows_non_finite_raises() -> None:
    with pytest.raises(NonFiniteResultError):
        calculate_levered_cash_flows(
            initial_equity=250.0,
            noi_by_year=(1.5e308,),
            annual_debt_service=(0.0,),
            net_sale_proceeds=1.5e308,
        )


# =============================================================================
# calculate_acquisition_cash_flows -- orchestration and boundary cases
# =============================================================================


def test_calculate_acquisition_cash_flows_returns_acquisition_cash_flows() -> None:
    result = calculate_acquisition_cash_flows(make_inputs())

    assert isinstance(result, AcquisitionCashFlows)


def test_calculate_acquisition_cash_flows_hold_period_one() -> None:
    inputs = make_inputs(hold_period=1)
    result = calculate_acquisition_cash_flows(inputs)

    assert len(result.unlevered_cash_flows) == 2
    assert len(result.levered_cash_flows) == 2


def test_calculate_acquisition_cash_flows_current_noi_zero() -> None:
    inputs = make_inputs(current_noi=0.0)
    result = calculate_acquisition_cash_flows(inputs)

    assert result.exit_value == 0.0
    assert result.unlevered_cash_flows[1] == 0.0
    assert result.unlevered_cash_flows[-1] == 0.0  # NOI_H (0) + exit_value (0)


def test_calculate_acquisition_cash_flows_noi_growth_zero() -> None:
    inputs = make_inputs(noi_growth=0.0)
    noi_forecast = forecast_noi(inputs)
    result = calculate_acquisition_cash_flows(inputs)

    assert noi_forecast.exit_noi == inputs.current_noi
    assert result.unlevered_cash_flows[1] == inputs.current_noi


def test_calculate_acquisition_cash_flows_negative_noi_growth() -> None:
    inputs = make_inputs(noi_growth=-0.10)
    result = calculate_acquisition_cash_flows(inputs)

    assert math.isfinite(result.exit_value)
    assert result.exit_value > 0.0


def test_calculate_acquisition_cash_flows_zero_leverage() -> None:
    inputs = make_inputs(ltv=0.0)
    result = calculate_acquisition_cash_flows(inputs)
    capital_stack = calculate_capital_stack(inputs)

    assert result.levered_cash_flows[0] == -capital_stack.initial_equity
    assert capital_stack.initial_equity == inputs.purchase_price
    assert result.net_sale_proceeds == result.exit_value


def test_calculate_acquisition_cash_flows_full_leverage() -> None:
    inputs = make_inputs(ltv=1.0)
    result = calculate_acquisition_cash_flows(inputs)
    capital_stack = calculate_capital_stack(inputs)

    assert capital_stack.initial_equity == 0.0
    assert result.levered_cash_flows[0] == 0.0


def test_calculate_acquisition_cash_flows_debt_matures_before_exit() -> None:
    inputs = make_inputs(amortization=3, hold_period=5)
    result = calculate_acquisition_cash_flows(inputs)

    assert result.net_sale_proceeds == result.exit_value


def test_calculate_acquisition_cash_flows_debt_matures_exactly_at_exit() -> None:
    inputs = make_inputs(amortization=5, hold_period=5)
    result = calculate_acquisition_cash_flows(inputs)

    assert result.net_sale_proceeds == result.exit_value


def test_calculate_acquisition_cash_flows_debt_outstanding_at_exit() -> None:
    inputs = make_inputs(amortization=30, hold_period=5)
    result = calculate_acquisition_cash_flows(inputs)

    assert result.net_sale_proceeds < result.exit_value


def test_calculate_acquisition_cash_flows_remaining_loan_balance_zero() -> None:
    inputs = make_inputs(ltv=0.0)
    debt_schedule = calculate_debt_schedule(inputs)
    result = calculate_acquisition_cash_flows(inputs)

    assert debt_schedule.remaining_loan_balance == 0.0
    assert result.net_sale_proceeds == result.exit_value


def test_calculate_acquisition_cash_flows_initial_equity_zero_at_100_ltv() -> None:
    inputs = make_inputs(ltv=1.0)
    capital_stack = calculate_capital_stack(inputs)

    assert capital_stack.initial_equity == 0.0


def test_calculate_acquisition_cash_flows_very_small_exit_cap_rate_raises() -> None:
    inputs = make_inputs(exit_cap_rate=1e-320)

    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_acquisition_cash_flows(inputs)

    assert exc_info.value.field_name == "exit_value"


def test_calculate_acquisition_cash_flows_large_but_finite_outputs() -> None:
    inputs = make_inputs(purchase_price=1e12, current_noi=5e10, hold_period=10)
    result = calculate_acquisition_cash_flows(inputs)

    assert math.isfinite(result.exit_value)
    assert math.isfinite(result.net_sale_proceeds)
    assert all(math.isfinite(cf) for cf in result.unlevered_cash_flows)
    assert all(math.isfinite(cf) for cf in result.levered_cash_flows)


def test_calculate_acquisition_cash_flows_repeated_calls_produce_identical_results() -> None:
    inputs = make_inputs()

    first = calculate_acquisition_cash_flows(inputs)
    second = calculate_acquisition_cash_flows(inputs)

    assert first == second
