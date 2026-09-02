"""Underwriting V2 Gate 3 -- annual CapEx reserve
(docs/underwriting_v2_financial_conventions.md).

Proves, by direct differential comparison against a common baseline deal,
exactly which AcquisitionResults fields ``annual_capex_reserve`` does and
does not affect -- not just that the engine still runs. Interest-only debt
and min_dscr are explicitly not implemented yet (Gate 4+); every test here
leaves ``io_period`` at its neutral default.
"""

from __future__ import annotations

import math

import pytest

from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition

BASE_KWARGS: dict[str, object] = dict(
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
    return AcquisitionInputs(**(BASE_KWARGS | overrides))  # type: ignore[arg-type]


BASELINE_INPUTS = make_inputs()
BASELINE = analyze_acquisition(BASELINE_INPUTS)

CAPEX_RESERVE = 150_000.0


# =============================================================================
# annual_capex_reserve = 0 preserves existing Gate 2 behavior exactly.
# =============================================================================


def test_annual_capex_reserve_zero_preserves_existing_gate2_behavior() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=0.0))

    assert result == BASELINE
    assert result.capex_by_year == (0.0,) * BASELINE_INPUTS.hold_period


# =============================================================================
# capex_by_year shape and values.
# =============================================================================


def test_capex_by_year_has_exactly_hold_period_entries() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert len(result.capex_by_year) == BASELINE_INPUTS.hold_period


def test_capex_by_year_entries_all_equal_the_reserve() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    for entry in result.capex_by_year:
        assert entry == CAPEX_RESERVE


# =============================================================================
# CapEx reduces every pre-exit operating year's cash flows by exactly the
# reserve amount, in both series.
# =============================================================================


def test_capex_reduces_every_annual_unlevered_operating_cash_flow_by_exactly_the_reserve() -> (
    None
):
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    hold_period = BASELINE_INPUTS.hold_period
    for year in range(1, hold_period):
        assert result.unlevered_cash_flows[year] == (
            BASELINE.unlevered_cash_flows[year] - CAPEX_RESERVE
        )


def test_capex_reduces_every_annual_levered_operating_cash_flow_by_exactly_the_reserve() -> (
    None
):
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    hold_period = BASELINE_INPUTS.hold_period
    for year in range(1, hold_period):
        assert result.levered_cash_flows[year] == (
            BASELINE.levered_cash_flows[year] - CAPEX_RESERVE
        )


# =============================================================================
# The exit year includes the CapEx deduction too. Computed with the engine's
# own exact left-to-right subtraction order (see the Gate 2 test file for
# why this matters under IEEE-754), reusing the result's own already-
# computed exit_value/disposition_costs/net_sale_proceeds rather than
# BASELINE's, so no reordering is introduced.
# =============================================================================


def test_capex_deduction_is_included_in_the_unlevered_exit_year_cash_flow() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    expected_ucf_h = (
        result.noi_by_year[-1] - CAPEX_RESERVE + result.exit_value - result.disposition_costs
    )
    assert result.unlevered_cash_flows[-1] == expected_ucf_h


def test_capex_deduction_is_included_in_the_levered_exit_year_cash_flow() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    expected_lcf_h = (
        result.noi_by_year[-1]
        - result.annual_debt_service[-1]
        - CAPEX_RESERVE
        + result.net_sale_proceeds
    )
    assert result.levered_cash_flows[-1] == expected_lcf_h


# =============================================================================
# Required non-effects: CapEx is purely a below-NOI property cash outflow.
# =============================================================================


def test_capex_does_not_change_noi_or_noi_growth() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.noi_by_year == BASELINE.noi_by_year


def test_capex_does_not_change_exit_noi_or_going_in_cap_rate() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.exit_noi == BASELINE.exit_noi
    assert result.going_in_cap_rate == BASELINE.going_in_cap_rate


def test_capex_does_not_change_gross_exit_value_or_disposition_costs() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.exit_value == BASELINE.exit_value
    assert result.disposition_costs == BASELINE.disposition_costs


def test_capex_does_not_change_net_sale_proceeds() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.net_sale_proceeds == BASELINE.net_sale_proceeds


def test_capex_does_not_change_loan_amount_or_initial_equity() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.loan_amount == BASELINE.loan_amount
    assert result.initial_equity == BASELINE.initial_equity


def test_capex_does_not_change_debt_service_or_remaining_loan_balance() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.monthly_debt_service == BASELINE.monthly_debt_service
    assert result.annual_debt_service == BASELINE.annual_debt_service
    assert result.remaining_loan_balance == BASELINE.remaining_loan_balance


def test_capex_does_not_change_dscr() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.dscr_by_year == BASELINE.dscr_by_year
    assert result.headline_dscr == BASELINE.headline_dscr


# =============================================================================
# Positive CapEx reduces the return metrics that depend on the cash-flow
# series it touches.
# =============================================================================


def test_positive_capex_reduces_unlevered_irr() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.unlevered_irr is not None
    assert BASELINE.unlevered_irr is not None
    assert result.unlevered_irr < BASELINE.unlevered_irr


def test_positive_capex_reduces_levered_irr() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.levered_irr is not None
    assert BASELINE.levered_irr is not None
    assert result.levered_irr < BASELINE.levered_irr


def test_positive_capex_reduces_equity_multiple() -> None:
    result = analyze_acquisition(make_inputs(annual_capex_reserve=CAPEX_RESERVE))

    assert result.equity_multiple is not None
    assert BASELINE.equity_multiple is not None
    assert result.equity_multiple < BASELINE.equity_multiple


# =============================================================================
# CapEx may exceed NOI and produce negative operating cash flow -- it is
# never capped or rejected.
# =============================================================================


def test_capex_may_exceed_noi_and_produce_negative_operating_cash_flow() -> None:
    extreme_reserve = 10_000_000.0
    result = analyze_acquisition(make_inputs(annual_capex_reserve=extreme_reserve))

    hold_period = BASELINE_INPUTS.hold_period
    for year in range(1, hold_period):
        assert result.unlevered_cash_flows[year] < 0.0
        assert result.levered_cash_flows[year] < 0.0
        assert math.isfinite(result.unlevered_cash_flows[year])
        assert math.isfinite(result.levered_cash_flows[year])
    # NOI itself must remain untouched even though the operating cash flow
    # it feeds into has gone deeply negative.
    assert result.noi_by_year == BASELINE.noi_by_year


# =============================================================================
# A one-year hold handles the reserve correctly in the terminal cash flow
# (there are no pre-exit operating years at all -- year 1 is both the first
# and only, exit, year).
# =============================================================================


def test_one_year_hold_handles_the_reserve_correctly_in_the_terminal_cash_flow() -> None:
    one_year_zero_capex = make_inputs(hold_period=1, annual_capex_reserve=0.0)
    one_year_baseline = analyze_acquisition(one_year_zero_capex)

    one_year_with_capex = make_inputs(hold_period=1, annual_capex_reserve=CAPEX_RESERVE)
    result = analyze_acquisition(one_year_with_capex)

    assert len(result.capex_by_year) == 1
    assert result.capex_by_year == (CAPEX_RESERVE,)

    expected_ucf_h = (
        result.noi_by_year[-1] - CAPEX_RESERVE + result.exit_value - result.disposition_costs
    )
    expected_lcf_h = (
        result.noi_by_year[-1]
        - result.annual_debt_service[-1]
        - CAPEX_RESERVE
        + result.net_sale_proceeds
    )
    assert result.unlevered_cash_flows[-1] == expected_ucf_h
    assert result.levered_cash_flows[-1] == expected_lcf_h
    assert result.unlevered_cash_flows[0] == one_year_baseline.unlevered_cash_flows[0]
    assert result.levered_cash_flows[0] == one_year_baseline.levered_cash_flows[0]


# =============================================================================
# Combined case: acquisition costs, financing fee, disposition costs, and
# annual CapEx all nonzero at once. Each component must combine
# independently exactly per the frozen conventions -- CapEx's effect is
# isolated by comparing against a variant with the same three Gate 2 costs
# but zero CapEx, so no baseline reordering risk is introduced.
# =============================================================================


def test_combined_gate2_and_gate3_costs_compose_independently() -> None:
    gate2_costs = dict(
        acquisition_cost_pct=0.02, financing_fee_pct=0.01, disposition_cost_pct=0.025
    )
    without_capex = analyze_acquisition(make_inputs(**gate2_costs, annual_capex_reserve=0.0))
    with_capex = analyze_acquisition(
        make_inputs(**gate2_costs, annual_capex_reserve=CAPEX_RESERVE)
    )

    # Gate 2 economics are identical whether or not CapEx is present.
    assert with_capex.loan_amount == without_capex.loan_amount
    assert with_capex.acquisition_costs == without_capex.acquisition_costs
    assert with_capex.financing_fee == without_capex.financing_fee
    assert with_capex.initial_equity == without_capex.initial_equity
    assert with_capex.exit_value == without_capex.exit_value
    assert with_capex.disposition_costs == without_capex.disposition_costs
    assert with_capex.net_sale_proceeds == without_capex.net_sale_proceeds
    assert with_capex.noi_by_year == without_capex.noi_by_year
    assert with_capex.annual_debt_service == without_capex.annual_debt_service
    assert with_capex.remaining_loan_balance == without_capex.remaining_loan_balance
    assert with_capex.dscr_by_year == without_capex.dscr_by_year

    # T=0: unaffected by CapEx (still only acquisition_costs/initial_equity).
    assert with_capex.unlevered_cash_flows[0] == without_capex.unlevered_cash_flows[0]
    assert with_capex.levered_cash_flows[0] == without_capex.levered_cash_flows[0]

    # Pre-exit operating years: each falls by exactly CAPEX_RESERVE.
    hold_period = BASELINE_INPUTS.hold_period
    for year in range(1, hold_period):
        assert with_capex.unlevered_cash_flows[year] == (
            without_capex.unlevered_cash_flows[year] - CAPEX_RESERVE
        )
        assert with_capex.levered_cash_flows[year] == (
            without_capex.levered_cash_flows[year] - CAPEX_RESERVE
        )

    # Exit year: CapEx stacks with the disposition-cost deduction already
    # present in `without_capex`, computed via the engine's own
    # left-to-right order using with_capex's own fields.
    expected_ucf_h = (
        with_capex.noi_by_year[-1]
        - CAPEX_RESERVE
        + with_capex.exit_value
        - with_capex.disposition_costs
    )
    expected_lcf_h = (
        with_capex.noi_by_year[-1]
        - with_capex.annual_debt_service[-1]
        - CAPEX_RESERVE
        + with_capex.net_sale_proceeds
    )
    assert with_capex.unlevered_cash_flows[-1] == expected_ucf_h
    assert with_capex.levered_cash_flows[-1] == expected_lcf_h

    # Every scalar/series field stays finite under the combined load.
    for value in (
        with_capex.going_in_cap_rate,
        with_capex.loan_amount,
        with_capex.acquisition_costs,
        with_capex.financing_fee,
        with_capex.initial_equity,
        with_capex.monthly_debt_service,
        with_capex.remaining_loan_balance,
        with_capex.exit_noi,
        with_capex.exit_value,
        with_capex.disposition_costs,
        with_capex.net_sale_proceeds,
    ):
        assert math.isfinite(value)
    for series in (
        with_capex.annual_debt_service,
        with_capex.noi_by_year,
        with_capex.capex_by_year,
        with_capex.unlevered_cash_flows,
        with_capex.levered_cash_flows,
    ):
        for value in series:
            assert math.isfinite(value)
