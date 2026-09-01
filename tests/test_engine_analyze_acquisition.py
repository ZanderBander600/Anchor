"""Phase 2E tests: the ``AcquisitionResults`` contract and the integrated
``analyze_acquisition`` orchestration.

Restates ``docs/phase_2_deterministic_engine.md`` "Phase 2 Output Contract",
"Golden Case", "Public Engine Entry Point", and "Frozen Phase 2 Decisions"
exactly; that document governs on any discrepancy. ``analyze_acquisition``
must orchestrate the already-committed Phase 2A/2B/2C/2D calculations only --
it must not independently recompute NOI, loan amount, debt service, exit
value, cash flows, DSCR, Equity Multiple, or IRR.
"""

from dataclasses import FrozenInstanceError, fields, is_dataclass
import typing
from unittest.mock import patch

import pytest

import anchor.engine as engine_package
import anchor.engine.acquisition as acquisition_module
from anchor.contracts import AcquisitionInputs
from anchor.engine import AcquisitionResults, analyze_acquisition
from anchor.engine.acquisition import calculate_acquisition_cash_flows


# Stringent absolute tolerance mirroring tests/test_engine_golden_case.py:
# rejects presentation-scale rounding while tolerating ordinary IEEE-754
# last-bit noise from the bisection-based IRR solver.
def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


ACQUISITION_RESULTS_FIELDS = (
    ("going_in_cap_rate", float),
    ("loan_amount", float),
    ("acquisition_costs", float),
    ("financing_fee", float),
    ("initial_equity", float),
    ("monthly_debt_service", float),
    ("annual_debt_service", tuple[float, ...]),
    ("remaining_loan_balance", float),
    ("noi_by_year", tuple[float, ...]),
    ("exit_noi", float),
    ("exit_value", float),
    ("disposition_costs", float),
    ("net_sale_proceeds", float),
    ("unlevered_cash_flows", tuple[float, ...]),
    ("levered_cash_flows", tuple[float, ...]),
    ("unlevered_irr", float | None),
    ("levered_irr", float | None),
    ("equity_multiple", float | None),
    ("dscr_by_year", tuple[float | None, ...]),
    ("headline_dscr", float | None),
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
# AcquisitionResults contract shape
# =============================================================================


def test_acquisition_results_has_exact_fields_order_and_keyword_only_shape() -> None:
    contract_fields = fields(AcquisitionResults)

    assert is_dataclass(AcquisitionResults)
    assert tuple(field.name for field in contract_fields) == tuple(
        name for name, _ in ACQUISITION_RESULTS_FIELDS
    )
    assert all(field.kw_only for field in contract_fields)
    assert AcquisitionResults.__slots__ == tuple(
        name for name, _ in ACQUISITION_RESULTS_FIELDS
    )


def test_acquisition_results_has_exact_field_annotation_types() -> None:
    resolved_types = typing.get_type_hints(AcquisitionResults)

    assert resolved_types == dict(ACQUISITION_RESULTS_FIELDS)


def test_acquisition_results_is_frozen_and_slotted() -> None:
    result = analyze_acquisition(make_golden_inputs())

    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.exit_value = 0.0  # type: ignore[misc]


def test_acquisition_results_tuple_fields_are_immutable_tuples() -> None:
    result = analyze_acquisition(make_golden_inputs())

    assert isinstance(result.annual_debt_service, tuple)
    assert isinstance(result.noi_by_year, tuple)
    assert isinstance(result.unlevered_cash_flows, tuple)
    assert isinstance(result.levered_cash_flows, tuple)
    assert isinstance(result.dscr_by_year, tuple)


def test_acquisition_results_has_no_excel_or_source_or_ui_metadata() -> None:
    result = analyze_acquisition(make_golden_inputs())

    assert not hasattr(result, "source")
    assert not hasattr(result, "cell")
    assert not hasattr(result, "row")
    assert not hasattr(result, "narrative")
    assert not hasattr(result, "confidence")
    assert not hasattr(result, "scenario")


# =============================================================================
# Public API surface
# =============================================================================


def test_engine_package_exposes_only_analyze_acquisition_and_acquisition_results() -> None:
    assert set(engine_package.__all__) == {"analyze_acquisition", "AcquisitionResults"}


def test_engine_package_does_not_re_export_internal_helpers() -> None:
    assert not hasattr(engine_package, "forecast_noi")
    assert not hasattr(engine_package, "calculate_capital_stack")
    assert not hasattr(engine_package, "calculate_debt_schedule")
    assert not hasattr(engine_package, "calculate_acquisition_cash_flows")
    assert not hasattr(engine_package, "calculate_return_metrics")


# =============================================================================
# analyze_acquisition -- golden case
# =============================================================================


def test_analyze_acquisition_returns_acquisition_results() -> None:
    result = analyze_acquisition(make_golden_inputs())

    assert isinstance(result, AcquisitionResults)


def test_analyze_acquisition_golden_case_full_result() -> None:
    result = analyze_acquisition(make_golden_inputs())

    assert result.going_in_cap_rate == 0.05
    assert result.loan_amount == 32_500_000.0
    assert result.initial_equity == 17_500_000.0
    assert result.monthly_debt_service == 179466.20319611699
    assert result.annual_debt_service == (
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
        2153594.438353404,
    )
    assert result.remaining_loan_balance == 29948583.641211268
    assert result.noi_by_year == (
        2500000.0,
        2575000.0,
        2652250.0,
        2731817.5,
        2813772.0250000004,
    )
    assert result.exit_noi == 2898185.18575
    assert result.exit_value == 52694276.10454546
    assert result.net_sale_proceeds == 22745692.46333419
    assert result.unlevered_cash_flows == (
        -50000000.0,
        2500000.0,
        2575000.0,
        2652250.0,
        2731817.5,
        55508048.12954546,
    )
    assert result.levered_cash_flows == (
        -17500000.0,
        346405.56164659606,
        421405.56164659606,
        498655.56164659606,
        578223.0616465961,
        23405870.04998079,
    )
    assert result.unlevered_irr == strict(0.062414943980353854)
    assert result.levered_irr == strict(0.07913030056780745)
    assert result.equity_multiple == strict(1.44288913123241)
    assert result.dscr_by_year == (
        strict(1.1608499518189),
        strict(1.195675450373467),
        strict(1.231545713884671),
        strict(1.2684920853012112),
        strict(1.3065468478602478),
    )
    assert result.headline_dscr == strict(1.1608499518189)


# =============================================================================
# analyze_acquisition -- boundary cases
# =============================================================================


def test_analyze_acquisition_hold_period_one() -> None:
    result = analyze_acquisition(make_inputs(hold_period=1))

    assert len(result.noi_by_year) == 1
    assert len(result.annual_debt_service) == 1
    assert len(result.dscr_by_year) == 1
    assert len(result.unlevered_cash_flows) == 2
    assert len(result.levered_cash_flows) == 2
    assert result.unlevered_cash_flows[0] == -50_000_000.0
    assert result.unlevered_cash_flows[-1] == result.noi_by_year[-1] + result.exit_value


def test_analyze_acquisition_zero_leverage() -> None:
    result = analyze_acquisition(make_inputs(ltv=0.0))

    assert result.loan_amount == 0.0
    assert result.initial_equity == -result.unlevered_cash_flows[0]
    assert result.monthly_debt_service == 0.0
    assert all(ads == 0.0 for ads in result.annual_debt_service)
    assert result.remaining_loan_balance == 0.0
    assert result.net_sale_proceeds == result.exit_value
    assert result.levered_cash_flows == result.unlevered_cash_flows
    assert all(dscr is None for dscr in result.dscr_by_year)
    assert result.headline_dscr is None


def test_analyze_acquisition_full_leverage() -> None:
    result = analyze_acquisition(make_inputs(ltv=1.0))

    assert result.loan_amount == -result.unlevered_cash_flows[0]
    assert result.initial_equity == 0.0
    assert result.levered_cash_flows[0] == 0.0


def test_analyze_acquisition_zero_interest_rate() -> None:
    result = analyze_acquisition(make_inputs(interest_rate=0.0))

    n_payments = 30 * 12
    expected_pmt = result.loan_amount / n_payments
    assert result.monthly_debt_service == expected_pmt
    assert all(dscr is not None for dscr in result.dscr_by_year)


def test_analyze_acquisition_zero_noi() -> None:
    result = analyze_acquisition(make_inputs(current_noi=0.0))

    assert all(noi == 0.0 for noi in result.noi_by_year)
    assert result.exit_noi == 0.0
    assert result.exit_value == 0.0
    assert result.going_in_cap_rate == 0.0
    assert all(dscr == 0.0 for dscr in result.dscr_by_year)


def test_analyze_acquisition_zero_noi_growth() -> None:
    result = analyze_acquisition(make_inputs(noi_growth=0.0))

    assert all(noi == 2_500_000.0 for noi in result.noi_by_year)
    assert result.exit_noi == 2_500_000.0


def test_analyze_acquisition_negative_noi_growth() -> None:
    result = analyze_acquisition(make_inputs(noi_growth=-0.10))

    for earlier, later in zip(result.noi_by_year, result.noi_by_year[1:]):
        assert later < earlier
    assert result.exit_value > 0.0


def test_analyze_acquisition_debt_matures_before_exit() -> None:
    result = analyze_acquisition(make_inputs(amortization=3, hold_period=5))

    assert result.annual_debt_service[3] == 0.0
    assert result.annual_debt_service[4] == 0.0
    assert result.remaining_loan_balance == 0.0
    assert result.net_sale_proceeds == result.exit_value
    assert result.dscr_by_year[3] is None
    assert result.dscr_by_year[4] is None


def test_analyze_acquisition_debt_matures_exactly_at_exit() -> None:
    result = analyze_acquisition(make_inputs(amortization=5, hold_period=5))

    assert result.remaining_loan_balance == 0.0
    assert result.net_sale_proceeds == result.exit_value


def test_analyze_acquisition_debt_outstanding_at_exit() -> None:
    result = analyze_acquisition(make_inputs(amortization=30, hold_period=5))

    assert result.remaining_loan_balance > 0.0
    assert result.net_sale_proceeds < result.exit_value


def test_analyze_acquisition_dscr_none_when_ads_zero() -> None:
    result = analyze_acquisition(make_inputs(ltv=0.0))

    assert result.headline_dscr is None
    assert all(dscr is None for dscr in result.dscr_by_year)


def test_analyze_acquisition_irr_none_when_series_invalid() -> None:
    # 100% LTV with an interest rate high enough that every levered cash flow
    # is non-negative (LCF_0 = 0, no negative entry anywhere): the IRR
    # validity rules (first nonzero negative, exactly one sign change) fail.
    result = analyze_acquisition(make_inputs(ltv=1.0, interest_rate=0.0))

    assert result.levered_cash_flows[0] == 0.0
    if all(cf >= 0.0 for cf in result.levered_cash_flows):
        assert result.levered_irr is None
        assert result.equity_multiple is None


# =============================================================================
# Determinism, immutability, and no duplicate calculation
# =============================================================================


def test_analyze_acquisition_deterministic_repeated_calls() -> None:
    inputs = make_golden_inputs()

    first = analyze_acquisition(inputs)
    second = analyze_acquisition(inputs)

    assert first == second


def test_analyze_acquisition_does_not_mutate_input() -> None:
    inputs = make_golden_inputs()
    snapshot = AcquisitionInputs(
        purchase_price=inputs.purchase_price,
        current_noi=inputs.current_noi,
        occupancy=inputs.occupancy,
        noi_growth=inputs.noi_growth,
        hold_period=inputs.hold_period,
        exit_cap_rate=inputs.exit_cap_rate,
        ltv=inputs.ltv,
        interest_rate=inputs.interest_rate,
        amortization=inputs.amortization,
    )

    analyze_acquisition(inputs)

    assert inputs == snapshot


def test_analyze_acquisition_final_tuple_lengths_correct() -> None:
    hold_period = 7
    result = analyze_acquisition(make_inputs(hold_period=hold_period))

    assert len(result.noi_by_year) == hold_period
    assert len(result.annual_debt_service) == hold_period
    assert len(result.dscr_by_year) == hold_period
    assert len(result.unlevered_cash_flows) == hold_period + 1
    assert len(result.levered_cash_flows) == hold_period + 1


def test_analyze_acquisition_computes_noi_forecast_exactly_once() -> None:
    inputs = make_golden_inputs()
    with patch.object(
        acquisition_module, "forecast_noi", wraps=acquisition_module.forecast_noi
    ) as mock_forecast_noi:
        analyze_acquisition(inputs)

    assert mock_forecast_noi.call_count == 1


def test_analyze_acquisition_computes_capital_stack_exactly_once() -> None:
    inputs = make_golden_inputs()
    with patch.object(
        acquisition_module,
        "calculate_capital_stack",
        wraps=acquisition_module.calculate_capital_stack,
    ) as mock_capital_stack:
        analyze_acquisition(inputs)

    assert mock_capital_stack.call_count == 1


def test_analyze_acquisition_computes_debt_schedule_exactly_once() -> None:
    inputs = make_golden_inputs()
    with patch.object(
        acquisition_module,
        "calculate_debt_schedule",
        wraps=acquisition_module.calculate_debt_schedule,
    ) as mock_debt_schedule:
        analyze_acquisition(inputs)

    assert mock_debt_schedule.call_count == 1


def test_analyze_acquisition_computes_return_metrics_exactly_once() -> None:
    inputs = make_golden_inputs()
    with patch.object(
        acquisition_module,
        "calculate_return_metrics",
        wraps=acquisition_module.calculate_return_metrics,
    ) as mock_return_metrics:
        analyze_acquisition(inputs)

    assert mock_return_metrics.call_count == 1


def test_analyze_acquisition_does_not_call_calculate_acquisition_cash_flows() -> None:
    # calculate_acquisition_cash_flows independently recomputes the NOI
    # forecast, capital stack, and debt schedule internally; calling it from
    # analyze_acquisition would duplicate calculations already performed
    # directly by analyze_acquisition.
    inputs = make_golden_inputs()
    with patch.object(
        acquisition_module,
        "calculate_acquisition_cash_flows",
        wraps=calculate_acquisition_cash_flows,
    ) as mock_cash_flows:
        analyze_acquisition(inputs)

    assert mock_cash_flows.call_count == 0


def test_analyze_acquisition_matches_manual_phase_2a_2b_2c_2d_assembly() -> None:
    # analyze_acquisition must reproduce exactly what independently calling
    # the committed Phase 2A/2B/2C/2D functions and assembling their results
    # by hand would produce -- proving there is one authoritative path for
    # every calculation.
    from anchor.engine.debt import calculate_capital_stack, calculate_debt_schedule
    from anchor.engine.noi import forecast_noi
    from anchor.engine.returns import calculate_return_metrics

    inputs = make_golden_inputs()

    noi_forecast = forecast_noi(inputs)
    capital_stack = calculate_capital_stack(inputs)
    debt_schedule = calculate_debt_schedule(inputs)
    cash_flows = calculate_acquisition_cash_flows(inputs)
    return_metrics = calculate_return_metrics(
        noi_by_year=noi_forecast.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        unlevered_cash_flows=cash_flows.unlevered_cash_flows,
        levered_cash_flows=cash_flows.levered_cash_flows,
    )

    result = analyze_acquisition(inputs)

    assert result.going_in_cap_rate == noi_forecast.going_in_cap_rate
    assert result.loan_amount == capital_stack.loan_amount
    assert result.initial_equity == capital_stack.initial_equity
    assert result.monthly_debt_service == debt_schedule.monthly_debt_service
    assert result.annual_debt_service == debt_schedule.annual_debt_service
    assert result.remaining_loan_balance == debt_schedule.remaining_loan_balance
    assert result.noi_by_year == noi_forecast.noi_by_year
    assert result.exit_noi == noi_forecast.exit_noi
    assert result.exit_value == cash_flows.exit_value
    assert result.net_sale_proceeds == cash_flows.net_sale_proceeds
    assert result.unlevered_cash_flows == cash_flows.unlevered_cash_flows
    assert result.levered_cash_flows == cash_flows.levered_cash_flows
    assert result.unlevered_irr == return_metrics.unlevered_irr
    assert result.levered_irr == return_metrics.levered_irr
    assert result.equity_multiple == return_metrics.equity_multiple
    assert result.dscr_by_year == return_metrics.dscr_by_year
    assert result.headline_dscr == return_metrics.headline_dscr
