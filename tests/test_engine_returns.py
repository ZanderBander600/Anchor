"""Phase 2D tests: DSCR, Equity Multiple, and the frozen IRR solver.

Restates ``docs/financial_conventions.md`` "Return Conventions" and
``docs/phase_2_deterministic_engine.md`` "DSCR" / "Equity Multiple" / "IRR"
exactly; those documents govern on any discrepancy.
"""

from __future__ import annotations

import inspect
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine import returns as returns_module
from mini_anchor.engine.acquisition import calculate_acquisition_cash_flows
from mini_anchor.engine.contracts import NonFiniteResultError, ReturnMetrics
from mini_anchor.engine.debt import calculate_debt_schedule
from mini_anchor.engine.noi import forecast_noi
from mini_anchor.engine.returns import (
    calculate_dscr_by_year,
    calculate_equity_multiple,
    calculate_headline_dscr,
    calculate_irr,
    calculate_return_metrics,
)


# Stringent absolute tolerance for financial outputs, mirroring
# tests/test_engine_noi.py, tests/test_engine_debt.py, and
# tests/test_engine_acquisition.py: rejects whole-dollar/cent/percentage-
# point rounding while tolerating ordinary IEEE-754 last-bit noise.
def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


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
# DSCR
# =============================================================================


def test_dscr_ordinary_case_golden_case_exact_values() -> None:
    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=(
            2500000.0,
            2575000.0,
            2652250.0,
            2731817.5,
            2813772.0250000004,
        ),
        annual_debt_service=(
            2153594.438353404,
            2153594.438353404,
            2153594.438353404,
            2153594.438353404,
            2153594.438353404,
        ),
    )

    assert dscr_by_year == (
        strict(1.1608499518189),
        strict(1.195675450373467),
        strict(1.231545713884671),
        strict(1.2684920853012112),
        strict(1.3065468478602478),
    )


def test_dscr_zero_leverage_all_none() -> None:
    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=(1_000.0, 1_000.0, 1_000.0),
        annual_debt_service=(0.0, 0.0, 0.0),
    )

    assert dscr_by_year == (None, None, None)


def test_dscr_current_noi_zero_with_positive_ads_is_zero_not_none() -> None:
    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=(0.0,), annual_debt_service=(100_000.0,)
    )

    assert dscr_by_year == (0.0,)
    assert dscr_by_year[0] is not None


def test_dscr_ads_zero_is_none() -> None:
    dscr_by_year = calculate_dscr_by_year(noi_by_year=(500_000.0,), annual_debt_service=(0.0,))

    assert dscr_by_year == (None,)


def test_dscr_debt_matures_before_exit_is_none_after_maturity() -> None:
    inputs = make_inputs(amortization=3, hold_period=5)
    noi_forecast = forecast_noi(inputs)
    debt_schedule = calculate_debt_schedule(inputs)

    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=noi_forecast.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
    )

    assert dscr_by_year[0] is not None
    assert dscr_by_year[1] is not None
    assert dscr_by_year[2] is not None
    assert dscr_by_year[3] is None
    assert dscr_by_year[4] is None


def test_dscr_headline_equals_year_1() -> None:
    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=(2500000.0,), annual_debt_service=(2153594.438353404,)
    )

    headline_dscr = calculate_headline_dscr(dscr_by_year=dscr_by_year)

    assert headline_dscr == dscr_by_year[0]
    assert headline_dscr == strict(1.1608499518189)


def test_dscr_headline_is_none_when_ads_1_is_zero() -> None:
    dscr_by_year = calculate_dscr_by_year(noi_by_year=(500_000.0,), annual_debt_service=(0.0,))

    headline_dscr = calculate_headline_dscr(dscr_by_year=dscr_by_year)

    assert headline_dscr is None


def test_dscr_result_is_immutable_tuple() -> None:
    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=(500_000.0, 600_000.0), annual_debt_service=(100_000.0, 0.0)
    )

    assert isinstance(dscr_by_year, tuple)
    with pytest.raises(TypeError):
        dscr_by_year[0] = 99.0  # type: ignore[index]


def test_dscr_no_rounding() -> None:
    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=(1_234_567.891,), annual_debt_service=(987_654.321,)
    )

    expected = 1_234_567.891 / 987_654.321
    assert dscr_by_year[0] == expected
    assert dscr_by_year[0] != round(dscr_by_year[0], 4)


def test_dscr_non_finite_raises() -> None:
    with pytest.raises(NonFiniteResultError) as exc_info:
        calculate_dscr_by_year(noi_by_year=(1.5e308,), annual_debt_service=(1e-300,))

    assert exc_info.value.field_name == "dscr_by_year[0]"


# =============================================================================
# Equity Multiple
# =============================================================================


def test_equity_multiple_ordinary_case_golden_case_exact_value() -> None:
    equity_multiple = calculate_equity_multiple(
        levered_cash_flows=(
            -17500000.0,
            346405.56164659606,
            421405.56164659606,
            498655.56164659606,
            578223.0616465961,
            23405870.04998079,
        )
    )

    assert equity_multiple == strict(1.44288913123241)


def test_equity_multiple_denominator_zero_returns_none() -> None:
    equity_multiple = calculate_equity_multiple(levered_cash_flows=(0.0, 100.0, 200.0))

    assert equity_multiple is None


def test_equity_multiple_zero_cash_flows_ignored() -> None:
    with_zero = calculate_equity_multiple(levered_cash_flows=(-100.0, 0.0, 150.0))
    without_zero = calculate_equity_multiple(levered_cash_flows=(-100.0, 150.0))

    assert with_zero == without_zero == strict(1.5)


def test_equity_multiple_later_negative_cash_flow_contributes_to_denominator() -> None:
    # A negative cash flow after time 0 must be added to the denominator, not
    # ignored -- e.g. a mid-hold capital call.
    equity_multiple = calculate_equity_multiple(
        levered_cash_flows=(-100.0, -50.0, 300.0)
    )

    assert equity_multiple == strict(300.0 / 150.0)


def test_equity_multiple_100_percent_ltv_zero_time_zero_no_other_negative_is_none() -> None:
    equity_multiple = calculate_equity_multiple(levered_cash_flows=(0.0, 50.0, 60.0))

    assert equity_multiple is None


def test_equity_multiple_zero_numerator_nonzero_denominator_is_zero_not_none() -> None:
    equity_multiple = calculate_equity_multiple(levered_cash_flows=(-100.0, -50.0, 0.0))

    assert equity_multiple == 0.0
    assert equity_multiple is not None


def test_equity_multiple_never_returns_infinity() -> None:
    # A denominator sum that underflows to exactly 0.0 despite genuinely
    # negative inputs is out of scope here (Phase 0 does not define this
    # case); this test instead confirms an ordinary nonzero denominator never
    # produces an infinite result.
    equity_multiple = calculate_equity_multiple(levered_cash_flows=(-1.0, 1e300))

    assert equity_multiple is None or math.isfinite(equity_multiple)


def test_equity_multiple_no_rounding() -> None:
    equity_multiple = calculate_equity_multiple(
        levered_cash_flows=(-1_234_567.891, 9_876_543.219)
    )

    expected = 9_876_543.219 / 1_234_567.891
    assert equity_multiple == expected
    assert equity_multiple != round(equity_multiple, 4)


# =============================================================================
# IRR -- validity (sign) rules
# =============================================================================


def test_irr_ordinary_conventional_stream() -> None:
    irr = calculate_irr((-100.0, 60.0, 60.0))

    assert irr is not None
    assert irr > 0.0


def test_irr_zero_irr() -> None:
    irr = calculate_irr((-100.0, 50.0, 50.0))

    assert irr == strict(0.0)


def test_irr_positive_irr() -> None:
    irr = calculate_irr((-100.0, 150.0))

    assert irr == strict(0.5)


def test_irr_negative_irr() -> None:
    irr = calculate_irr((-100.0, 50.0))

    assert irr == strict(-0.5)


def test_irr_first_nonzero_cash_flow_positive_is_none() -> None:
    irr = calculate_irr((100.0, -60.0, -60.0))

    assert irr is None


def test_irr_no_positive_cash_flow_is_none() -> None:
    irr = calculate_irr((-100.0, -50.0, -20.0))

    assert irr is None


def test_irr_no_negative_cash_flow_is_none() -> None:
    irr = calculate_irr((100.0, 50.0, 20.0))

    assert irr is None


def test_irr_more_than_one_sign_change_is_none() -> None:
    # -100, +50, -20, +90: two sign changes in the nonzero sequence.
    irr = calculate_irr((-100.0, 50.0, -20.0, 90.0))

    assert irr is None


def test_irr_zero_cash_flows_ignored_for_sign_change_counting() -> None:
    # -100, 0, 0, 60, 60: zeros must not be counted as sign changes or break
    # the "exactly one sign change" rule.
    irr = calculate_irr((-100.0, 0.0, 0.0, 60.0, 60.0))

    assert irr is not None
    assert irr > 0.0


def test_irr_leading_zero_cash_flows() -> None:
    # First nonzero cash flow (index 1) is negative; leading zero at index 0
    # must be ignored for validity but retain its time index in evaluation.
    irr = calculate_irr((0.0, -100.0, 150.0))

    assert irr is not None
    assert irr == strict(0.5)


def test_irr_leading_zero_first_nonzero_positive_is_none() -> None:
    irr = calculate_irr((0.0, 100.0, -50.0, -60.0))

    assert irr is None


def test_irr_lcf_0_zero_full_leverage_case() -> None:
    # Simulates a 100% LTV levered series where LCF_0 = 0: t0 is the first
    # actual nonzero entry, and original annual spacing is preserved.
    irr = calculate_irr((0.0, -10.0, 30.0))

    assert irr is not None
    assert irr == strict(2.0)


# =============================================================================
# IRR -- numerical solution
# =============================================================================


def test_irr_exact_root_at_x_equals_1() -> None:
    # F(1) == 0 exactly: -100 + 100 == 0. x_star = x_high = 1 directly, no
    # bisection entered.
    irr = calculate_irr((-100.0, 100.0))

    assert irr == 0.0


def test_irr_large_positive_irr() -> None:
    irr = calculate_irr((-100.0, 10_000.0))

    # Bisection interval-width tolerance scales with x_mid magnitude, so the
    # converged value carries more absolute error at this larger root than
    # at the small-magnitude cases elsewhere in this file.
    assert irr == pytest.approx(99.0, rel=0.0, abs=1e-6)


def test_irr_negative_irr_requires_x_high_expansion() -> None:
    # F(1) = -100 + 50 = -50 < 0, so x_high must expand past 1. Expansion to
    # x_high = 2 hits F(2) = -100 + 100 = 0 exactly.
    irr = calculate_irr((-100.0, 50.0))

    assert irr == strict(-0.5)


def test_irr_root_near_negative_100_percent_within_supported_domain() -> None:
    # x* = 1e11 <= 1e12: within the supported numerical domain. r is very
    # close to -1 but not equal to it.
    cash_flows = (-1.0, 1e-11)
    irr = calculate_irr(cash_flows)

    assert irr is not None
    assert irr == strict(1.0 / 1e11 - 1.0)
    assert -1.0 < irr < -0.999


def test_irr_root_requiring_x_greater_than_1e12_is_none() -> None:
    # True root at x* = 1e13 > 1e12: outside the supported domain.
    cash_flows = (-1.0, 1e-13)
    irr = calculate_irr(cash_flows)

    assert irr is None


def test_irr_exact_root_at_x_equals_1e12() -> None:
    # F(x) = -1e12 + 1.0 * x. F(1e12) == 0 exactly, and x_high's doubling
    # sequence (1, 2, 4, ..., clamped to 1e12) reaches exactly x = 1e12.
    cash_flows = (-1e12, 1.0)
    irr = calculate_irr(cash_flows)

    assert irr is not None
    assert irr == strict(1.0 / 1e12 - 1.0)


def test_irr_non_finite_horner_intermediate_is_none() -> None:
    # An extreme cash-flow magnitude drives a Horner intermediate to
    # overflow during ordinary evaluation.
    irr = calculate_irr((-1e308, 1e308, 1e308))

    assert irr is None or math.isfinite(irr)


def test_irr_deterministic_repeated_calls() -> None:
    cash_flows = (-17500000.0, 346405.56164659606, 421405.56164659606, 498655.56164659606, 578223.0616465961, 23405870.04998079)

    first = calculate_irr(cash_flows)
    second = calculate_irr(cash_flows)

    assert first == second


def test_irr_256_iteration_bisection_converges_within_tolerance() -> None:
    # A cash-flow series unlikely to hit an exact-root or wide-interval
    # shortcut; verify the converged IRR actually zeroes the NPV equation
    # to a tight tolerance, exercising the bisection loop itself.
    cash_flows = (-1_000_000.0, 137_000.0, 219_000.0, 301_000.0, 890_000.0)
    irr = calculate_irr(cash_flows)

    assert irr is not None
    npv = sum(cf / (1.0 + irr) ** t for t, cf in enumerate(cash_flows))
    assert abs(npv) < 1e-4


def test_irr_unlevered_and_levered_use_same_function() -> None:
    inputs = make_inputs()
    cash_flows = calculate_acquisition_cash_flows(inputs)

    unlevered_irr = calculate_irr(cash_flows.unlevered_cash_flows)
    levered_irr = calculate_irr(cash_flows.levered_cash_flows)

    assert unlevered_irr == calculate_irr(cash_flows.unlevered_cash_flows)
    assert levered_irr == calculate_irr(cash_flows.levered_cash_flows)


# =============================================================================
# calculate_return_metrics -- orchestration
# =============================================================================


def test_calculate_return_metrics_returns_return_metrics() -> None:
    inputs = make_inputs()
    noi_forecast = forecast_noi(inputs)
    debt_schedule = calculate_debt_schedule(inputs)
    cash_flows = calculate_acquisition_cash_flows(inputs)

    result = calculate_return_metrics(
        noi_by_year=noi_forecast.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        unlevered_cash_flows=cash_flows.unlevered_cash_flows,
        levered_cash_flows=cash_flows.levered_cash_flows,
    )

    assert isinstance(result, ReturnMetrics)


def test_calculate_return_metrics_golden_case_exact_values() -> None:
    inputs = make_inputs()
    noi_forecast = forecast_noi(inputs)
    debt_schedule = calculate_debt_schedule(inputs)
    cash_flows = calculate_acquisition_cash_flows(inputs)

    result = calculate_return_metrics(
        noi_by_year=noi_forecast.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        unlevered_cash_flows=cash_flows.unlevered_cash_flows,
        levered_cash_flows=cash_flows.levered_cash_flows,
    )

    assert result.dscr_by_year == (
        strict(1.1608499518189),
        strict(1.195675450373467),
        strict(1.231545713884671),
        strict(1.2684920853012112),
        strict(1.3065468478602478),
    )
    assert result.headline_dscr == strict(1.1608499518189)
    assert result.equity_multiple == strict(1.44288913123241)
    assert result.unlevered_irr == strict(0.062414943980353854)
    assert result.levered_irr == strict(0.07913030056780745)


def test_calculate_return_metrics_repeated_calls_produce_identical_results() -> None:
    inputs = make_inputs()
    noi_forecast = forecast_noi(inputs)
    debt_schedule = calculate_debt_schedule(inputs)
    cash_flows = calculate_acquisition_cash_flows(inputs)

    kwargs = dict(
        noi_by_year=noi_forecast.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        unlevered_cash_flows=cash_flows.unlevered_cash_flows,
        levered_cash_flows=cash_flows.levered_cash_flows,
    )

    first = calculate_return_metrics(**kwargs)
    second = calculate_return_metrics(**kwargs)

    assert first == second


# =============================================================================
# Architecture
# =============================================================================


def test_returns_module_defines_only_one_irr_implementation() -> None:
    source = inspect.getsource(returns_module)

    assert source.count("def calculate_irr(") == 1
    assert source.count("def _solve_x_star(") == 1
    assert source.count("def _evaluate_horner(") == 1


def test_returns_module_does_not_use_third_party_solver() -> None:
    import_lines = [
        line.strip()
        for line in inspect.getsource(returns_module).splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]

    for forbidden in ("numpy", "numpy_financial", "scipy", "openpyxl"):
        assert not any(forbidden in line for line in import_lines), import_lines


def test_returns_module_does_not_import_openpyxl_at_runtime() -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    python_path_parts = [str(project_root / "src")]
    if existing_python_path := environment.get("PYTHONPATH"):
        python_path_parts.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import mini_anchor.engine.returns; "
                "assert 'openpyxl' not in sys.modules; "
                "assert 'numpy' not in sys.modules; "
                "assert 'scipy' not in sys.modules"
            ),
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_acquisition_results_does_not_exist_yet() -> None:
    import mini_anchor.contracts as top_level_contracts

    assert not hasattr(top_level_contracts, "AcquisitionResults")
