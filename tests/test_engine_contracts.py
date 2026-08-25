from dataclasses import FrozenInstanceError, fields, is_dataclass
import math
import os
from pathlib import Path
import subprocess
import sys
import typing

import pytest

from mini_anchor.engine.contracts import (
    AcquisitionCashFlows,
    CapitalStack,
    DebtSchedule,
    NoiForecast,
    NonFiniteResultError,
    ReturnMetrics,
    ensure_finite,
)


NOI_FORECAST_FIELDS = (
    ("noi_by_year", tuple[float, ...]),
    ("exit_noi", float),
    ("going_in_cap_rate", float),
)

CAPITAL_STACK_FIELDS = (
    ("loan_amount", float),
    ("initial_equity", float),
)

DEBT_SCHEDULE_FIELDS = (
    ("monthly_debt_service", float),
    ("annual_debt_service", tuple[float, ...]),
    ("remaining_loan_balance", float),
)

ACQUISITION_CASH_FLOWS_FIELDS = (
    ("exit_value", float),
    ("net_sale_proceeds", float),
    ("unlevered_cash_flows", tuple[float, ...]),
    ("levered_cash_flows", tuple[float, ...]),
)

RETURN_METRICS_FIELDS = (
    ("dscr_by_year", tuple[float | None, ...]),
    ("headline_dscr", float | None),
    ("equity_multiple", float | None),
    ("unlevered_irr", float | None),
    ("levered_irr", float | None),
)


def test_noi_forecast_has_exact_fields_order_and_keyword_only_shape() -> None:
    contract_fields = fields(NoiForecast)

    assert is_dataclass(NoiForecast)
    assert tuple(field.name for field in contract_fields) == tuple(
        name for name, _ in NOI_FORECAST_FIELDS
    )
    assert all(field.kw_only for field in contract_fields)
    assert NoiForecast.__slots__ == tuple(name for name, _ in NOI_FORECAST_FIELDS)


def test_noi_forecast_has_exact_field_annotation_types() -> None:
    resolved_types = typing.get_type_hints(NoiForecast)

    assert resolved_types == dict(NOI_FORECAST_FIELDS)


def test_noi_forecast_is_frozen_and_slotted() -> None:
    noi_forecast = NoiForecast(
        noi_by_year=(2_500_000.0,), exit_noi=2_575_000.0, going_in_cap_rate=0.05
    )

    assert not hasattr(noi_forecast, "__dict__")
    with pytest.raises(FrozenInstanceError):
        noi_forecast.exit_noi = 0.0  # type: ignore[misc]


def test_noi_forecast_noi_by_year_is_immutable_tuple() -> None:
    noi_forecast = NoiForecast(
        noi_by_year=(2_500_000.0, 2_575_000.0), exit_noi=2_652_250.0, going_in_cap_rate=0.05
    )

    assert isinstance(noi_forecast.noi_by_year, tuple)


def test_noi_forecast_has_no_excel_or_source_metadata() -> None:
    noi_forecast = NoiForecast(
        noi_by_year=(2_500_000.0,), exit_noi=2_575_000.0, going_in_cap_rate=0.05
    )

    assert not hasattr(noi_forecast, "source")
    assert not hasattr(noi_forecast, "cell")
    assert not hasattr(noi_forecast, "row")


def test_capital_stack_has_exact_fields_order_and_keyword_only_shape() -> None:
    contract_fields = fields(CapitalStack)

    assert is_dataclass(CapitalStack)
    assert tuple(field.name for field in contract_fields) == tuple(
        name for name, _ in CAPITAL_STACK_FIELDS
    )
    assert all(field.kw_only for field in contract_fields)
    assert CapitalStack.__slots__ == tuple(name for name, _ in CAPITAL_STACK_FIELDS)


def test_capital_stack_has_exact_field_annotation_types() -> None:
    resolved_types = typing.get_type_hints(CapitalStack)

    assert resolved_types == dict(CAPITAL_STACK_FIELDS)


def test_capital_stack_is_frozen_and_slotted() -> None:
    capital_stack = CapitalStack(loan_amount=32_500_000.0, initial_equity=17_500_000.0)

    assert not hasattr(capital_stack, "__dict__")
    with pytest.raises(FrozenInstanceError):
        capital_stack.loan_amount = 0.0  # type: ignore[misc]


def test_capital_stack_has_no_excel_or_source_metadata() -> None:
    capital_stack = CapitalStack(loan_amount=32_500_000.0, initial_equity=17_500_000.0)

    assert not hasattr(capital_stack, "source")
    assert not hasattr(capital_stack, "cell")
    assert not hasattr(capital_stack, "row")


def test_debt_schedule_has_exact_fields_order_and_keyword_only_shape() -> None:
    contract_fields = fields(DebtSchedule)

    assert is_dataclass(DebtSchedule)
    assert tuple(field.name for field in contract_fields) == tuple(
        name for name, _ in DEBT_SCHEDULE_FIELDS
    )
    assert all(field.kw_only for field in contract_fields)
    assert DebtSchedule.__slots__ == tuple(name for name, _ in DEBT_SCHEDULE_FIELDS)


def test_debt_schedule_has_exact_field_annotation_types() -> None:
    resolved_types = typing.get_type_hints(DebtSchedule)

    assert resolved_types == dict(DEBT_SCHEDULE_FIELDS)


def test_debt_schedule_is_frozen_and_slotted() -> None:
    debt_schedule = DebtSchedule(
        monthly_debt_service=179_466.20319611699,
        annual_debt_service=(2_153_594.438353404,),
        remaining_loan_balance=29_948_583.641211268,
    )

    assert not hasattr(debt_schedule, "__dict__")
    with pytest.raises(FrozenInstanceError):
        debt_schedule.remaining_loan_balance = 0.0  # type: ignore[misc]


def test_debt_schedule_annual_debt_service_is_immutable_tuple() -> None:
    debt_schedule = DebtSchedule(
        monthly_debt_service=179_466.20319611699,
        annual_debt_service=(2_153_594.438353404, 2_153_594.438353404),
        remaining_loan_balance=29_948_583.641211268,
    )

    assert isinstance(debt_schedule.annual_debt_service, tuple)


def test_debt_schedule_has_no_excel_or_source_metadata() -> None:
    debt_schedule = DebtSchedule(
        monthly_debt_service=179_466.20319611699,
        annual_debt_service=(2_153_594.438353404,),
        remaining_loan_balance=29_948_583.641211268,
    )

    assert not hasattr(debt_schedule, "source")
    assert not hasattr(debt_schedule, "cell")
    assert not hasattr(debt_schedule, "row")


def test_acquisition_cash_flows_has_exact_fields_order_and_keyword_only_shape() -> None:
    contract_fields = fields(AcquisitionCashFlows)

    assert is_dataclass(AcquisitionCashFlows)
    assert tuple(field.name for field in contract_fields) == tuple(
        name for name, _ in ACQUISITION_CASH_FLOWS_FIELDS
    )
    assert all(field.kw_only for field in contract_fields)
    assert AcquisitionCashFlows.__slots__ == tuple(
        name for name, _ in ACQUISITION_CASH_FLOWS_FIELDS
    )


def test_acquisition_cash_flows_has_exact_field_annotation_types() -> None:
    resolved_types = typing.get_type_hints(AcquisitionCashFlows)

    assert resolved_types == dict(ACQUISITION_CASH_FLOWS_FIELDS)


def test_acquisition_cash_flows_is_frozen_and_slotted() -> None:
    cash_flows = AcquisitionCashFlows(
        exit_value=52_694_276.10454546,
        net_sale_proceeds=22_745_692.46333419,
        unlevered_cash_flows=(-50_000_000.0, 55_508_048.12954546),
        levered_cash_flows=(-17_500_000.0, 23_405_870.04998079),
    )

    assert not hasattr(cash_flows, "__dict__")
    with pytest.raises(FrozenInstanceError):
        cash_flows.exit_value = 0.0  # type: ignore[misc]


def test_acquisition_cash_flows_tuples_are_immutable() -> None:
    cash_flows = AcquisitionCashFlows(
        exit_value=52_694_276.10454546,
        net_sale_proceeds=22_745_692.46333419,
        unlevered_cash_flows=(-50_000_000.0, 55_508_048.12954546),
        levered_cash_flows=(-17_500_000.0, 23_405_870.04998079),
    )

    assert isinstance(cash_flows.unlevered_cash_flows, tuple)
    assert isinstance(cash_flows.levered_cash_flows, tuple)


def test_acquisition_cash_flows_has_no_excel_or_source_metadata() -> None:
    cash_flows = AcquisitionCashFlows(
        exit_value=52_694_276.10454546,
        net_sale_proceeds=22_745_692.46333419,
        unlevered_cash_flows=(-50_000_000.0, 55_508_048.12954546),
        levered_cash_flows=(-17_500_000.0, 23_405_870.04998079),
    )

    assert not hasattr(cash_flows, "source")
    assert not hasattr(cash_flows, "cell")
    assert not hasattr(cash_flows, "row")


def test_return_metrics_has_exact_fields_order_and_keyword_only_shape() -> None:
    contract_fields = fields(ReturnMetrics)

    assert is_dataclass(ReturnMetrics)
    assert tuple(field.name for field in contract_fields) == tuple(
        name for name, _ in RETURN_METRICS_FIELDS
    )
    assert all(field.kw_only for field in contract_fields)
    assert ReturnMetrics.__slots__ == tuple(name for name, _ in RETURN_METRICS_FIELDS)


def test_return_metrics_has_exact_field_annotation_types() -> None:
    resolved_types = typing.get_type_hints(ReturnMetrics)

    assert resolved_types == dict(RETURN_METRICS_FIELDS)


def test_return_metrics_is_frozen_and_slotted() -> None:
    return_metrics = ReturnMetrics(
        dscr_by_year=(1.1608499518189,),
        headline_dscr=1.1608499518189,
        equity_multiple=1.44288913123241,
        unlevered_irr=0.062414943980353854,
        levered_irr=0.07913030056780745,
    )

    assert not hasattr(return_metrics, "__dict__")
    with pytest.raises(FrozenInstanceError):
        return_metrics.headline_dscr = 0.0  # type: ignore[misc]


def test_return_metrics_dscr_by_year_is_immutable_tuple() -> None:
    return_metrics = ReturnMetrics(
        dscr_by_year=(1.1608499518189, None),
        headline_dscr=1.1608499518189,
        equity_multiple=1.44288913123241,
        unlevered_irr=0.062414943980353854,
        levered_irr=0.07913030056780745,
    )

    assert isinstance(return_metrics.dscr_by_year, tuple)


def test_return_metrics_has_no_excel_or_source_metadata() -> None:
    return_metrics = ReturnMetrics(
        dscr_by_year=(1.1608499518189,),
        headline_dscr=1.1608499518189,
        equity_multiple=1.44288913123241,
        unlevered_irr=0.062414943980353854,
        levered_irr=0.07913030056780745,
    )

    assert not hasattr(return_metrics, "source")
    assert not hasattr(return_metrics, "cell")
    assert not hasattr(return_metrics, "row")


def test_non_finite_result_error_is_value_error_subclass() -> None:
    assert issubclass(NonFiniteResultError, ValueError)


def test_non_finite_result_error_carries_field_name_and_value() -> None:
    error = NonFiniteResultError("exit_noi", math.inf)

    assert error.field_name == "exit_noi"
    assert error.value == math.inf


def test_ensure_finite_returns_value_unchanged_when_finite() -> None:
    assert ensure_finite("going_in_cap_rate", 0.05) == 0.05


def test_ensure_finite_returns_zero_unchanged() -> None:
    assert ensure_finite("going_in_cap_rate", 0.0) == 0.0


def test_ensure_finite_raises_on_positive_infinity() -> None:
    with pytest.raises(NonFiniteResultError):
        ensure_finite("exit_noi", math.inf)


def test_ensure_finite_raises_on_negative_infinity() -> None:
    with pytest.raises(NonFiniteResultError):
        ensure_finite("exit_noi", -math.inf)


def test_ensure_finite_raises_on_nan() -> None:
    with pytest.raises(NonFiniteResultError):
        ensure_finite("exit_noi", math.nan)


def test_engine_package_contains_only_expected_phase_2a_2b_2c_2d_modules() -> None:
    engine_dir = Path(__file__).resolve().parents[1] / "src" / "mini_anchor" / "engine"
    module_names = {path.name for path in engine_dir.glob("*.py")}

    assert module_names == {
        "__init__.py",
        "contracts.py",
        "noi.py",
        "debt.py",
        "acquisition.py",
        "returns.py",
    }


def test_engine_contracts_noi_debt_acquisition_returns_do_not_import_openpyxl() -> None:
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
                "import sys; import mini_anchor.engine; "
                "import mini_anchor.engine.contracts; "
                "import mini_anchor.engine.noi; "
                "import mini_anchor.engine.debt; "
                "import mini_anchor.engine.acquisition; "
                "import mini_anchor.engine.returns; "
                "assert 'openpyxl' not in sys.modules"
            ),
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
