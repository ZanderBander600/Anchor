"""Tests for the terminal report builder in ``report.py``.

``build_report`` must only format values already computed by
``analyze_acquisition`` -- it must never reproduce a financial formula. The
golden-case test below pins the exact formatted output for the same
``AcquisitionInputs`` used by ``tests/test_engine_golden_case.py`` and
``tests/test_engine_analyze_acquisition.py``, so any accidental engine or
formatting drift is caught.
"""

from __future__ import annotations

from dataclasses import replace

from anchor.contracts import AcquisitionInputs
from anchor.engine import AcquisitionResults, analyze_acquisition
from anchor.report import build_report


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


def test_build_report_golden_case_key_figures() -> None:
    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    report = build_report(inputs, results)

    assert "Going-In Cap Rate:        5.00%" in report
    assert "Exit NOI:                 $2,898,185" in report
    assert "Exit Value:               $52,694,276" in report
    assert "Loan Amount:              $32,500,000" in report
    assert "Initial Equity:           $17,500,000" in report
    assert "Monthly Debt Service:     $179,466" in report
    assert "Remaining Loan Balance:   $29,948,584" in report
    assert "Levered IRR:              7.91%" in report
    assert "Unlevered IRR:            6.24%" in report
    assert "Equity Multiple:          1.44x" in report
    assert "Headline DSCR:            1.16x" in report
    assert "Net Sale Proceeds:        $22,745,692" in report


def test_build_report_lists_noi_and_ads_by_year() -> None:
    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    report = build_report(inputs, results)

    assert "Year 1:           $2,500,000" in report
    assert "Year 5:           $2,813,772" in report
    assert "Year 1:           $2,153,594" in report


def test_build_report_cash_flow_table_includes_year_zero_acquisition() -> None:
    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    report = build_report(inputs, results)

    assert "-$50,000,000" in report
    assert "-$17,500,000" in report


def test_build_report_reflects_none_values_as_na() -> None:
    """Zero leverage drives DSCR/headline DSCR to ``None``; the report must
    print ``N/A`` rather than crash or invent a number."""

    inputs = AcquisitionInputs(
        purchase_price=50_000_000.0,
        current_noi=2_500_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=5,
        exit_cap_rate=0.055,
        ltv=0.0,
        interest_rate=0.0525,
        amortization=30,
    )
    results = analyze_acquisition(inputs)

    report = build_report(inputs, results)

    assert results.headline_dscr is None
    assert "Headline DSCR:            N/A" in report


def test_build_report_only_formats_precomputed_engine_values() -> None:
    """``build_report`` must read every number straight off ``results`` --
    changing a result field must change the corresponding report line and
    nothing else that a different field would produce, proving the report
    layer performs no independent calculation."""

    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    mutated = AcquisitionResults(
        going_in_cap_rate=results.going_in_cap_rate,
        loan_amount=results.loan_amount,
        acquisition_costs=results.acquisition_costs,
        financing_fee=results.financing_fee,
        initial_equity=results.initial_equity,
        monthly_debt_service=results.monthly_debt_service,
        annual_debt_service=results.annual_debt_service,
        remaining_loan_balance=results.remaining_loan_balance,
        noi_by_year=results.noi_by_year,
        capex_by_year=results.capex_by_year,
        exit_noi=results.exit_noi,
        exit_value=results.exit_value,
        disposition_costs=results.disposition_costs,
        net_sale_proceeds=results.net_sale_proceeds,
        unlevered_cash_flows=results.unlevered_cash_flows,
        levered_cash_flows=results.levered_cash_flows,
        unlevered_irr=results.unlevered_irr,
        levered_irr=0.123456,
        equity_multiple=results.equity_multiple,
        dscr_by_year=results.dscr_by_year,
        headline_dscr=results.headline_dscr,
    )

    report = build_report(inputs, mutated)

    assert "Levered IRR:              12.35%" in report
    assert "Unlevered IRR:            6.24%" in report


def test_build_report_includes_assumptions_section() -> None:
    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    report = build_report(inputs, results)

    assert "ASSUMPTIONS" in report
    assert "Purchase Price:          $50,000,000" in report
    assert "Current NOI:              $2,500,000" in report
    assert "Occupancy:                    95.00%" in report
    assert "NOI Growth:                    3.00%" in report
    assert "Hold Period:                 5 years" in report
    assert "Exit Cap Rate:                 5.50%" in report
    assert "LTV:                          65.00%" in report
    assert "Interest Rate:                 5.25%" in report
    assert "Amortization:               30 years" in report


def test_build_report_still_contains_all_existing_sections() -> None:
    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    report = build_report(inputs, results)

    for section in (
        "PROPERTY",
        "CAPITALIZATION",
        "RETURNS",
        "EXIT",
        "CASH FLOW DETAIL",
        "RISK FLAGS",
    ):
        assert section in report


def test_build_report_golden_case_risk_flags() -> None:
    """The golden case has headline DSCR 1.16x (< 1.20x), levered IRR 7.91%
    (< 10.00%), and a 50 bps exit-cap-over-going-in-cap spread, so all three
    of those flags should trigger; no year has a negative levered cash flow."""

    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    report = build_report(inputs, results)

    assert "Year 1 DSCR below 1.20x" in report
    assert "Levered IRR below 10.00% reference threshold" in report
    assert "Exit cap is 50 bps above going-in cap" in report
    assert "Negative levered cash flow" not in report


def test_build_report_no_risk_flags_triggered() -> None:
    """A DSCR/IRR comfortably above threshold, an exit cap at or below the
    going-in cap, and all-positive levered cash flows should trigger no
    flags."""

    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    clean_results = replace(
        results,
        headline_dscr=1.50,
        dscr_by_year=(1.50,) + results.dscr_by_year[1:],
        levered_irr=0.15,
        going_in_cap_rate=inputs.exit_cap_rate,
        levered_cash_flows=tuple(abs(cf) for cf in results.levered_cash_flows),
    )

    report = build_report(inputs, clean_results)

    assert "No basic risk flags triggered" in report
    assert "Year 1 DSCR below 1.20x" not in report
    assert "Levered IRR below 10.00% reference threshold" not in report
    assert "Exit cap is" not in report
    assert "Negative levered cash flow" not in report


def test_build_report_flags_single_negative_levered_cash_flow_year() -> None:
    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    cash_flows = list(results.levered_cash_flows)
    cash_flows[2] = -1_000.0
    mutated = replace(results, levered_cash_flows=tuple(cash_flows))

    report = build_report(inputs, mutated)

    assert "Negative levered cash flow in Year 2" in report


def test_build_report_flags_multiple_negative_levered_cash_flow_years() -> None:
    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    cash_flows = list(results.levered_cash_flows)
    cash_flows[2] = -1_000.0
    cash_flows[4] = -2_000.0
    mutated = replace(results, levered_cash_flows=tuple(cash_flows))

    report = build_report(inputs, mutated)

    assert "Negative levered cash flow in Years 2, 4" in report


def test_build_report_ignores_year_zero_acquisition_outlay_for_negative_cf_flag() -> None:
    """Year 0's levered cash flow (the initial equity outlay) is always
    negative by construction and must not trip the negative-cash-flow flag."""

    inputs = make_golden_inputs()
    results = analyze_acquisition(inputs)

    report = build_report(inputs, results)

    assert results.levered_cash_flows[0] < 0
    assert "Negative levered cash flow" not in report
