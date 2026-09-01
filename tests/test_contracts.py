from dataclasses import FrozenInstanceError, fields, is_dataclass
import os
from pathlib import Path
import subprocess
import sys

import pytest

from anchor.contracts import AcquisitionInputs


EXPECTED_FIELDS = (
    ("purchase_price", float),
    ("current_noi", float),
    ("occupancy", float),
    ("noi_growth", float),
    ("hold_period", int),
    ("exit_cap_rate", float),
    ("ltv", float),
    ("interest_rate", float),
    ("amortization", int),
    ("acquisition_cost_pct", float),
    ("financing_fee_pct", float),
    ("disposition_cost_pct", float),
    ("annual_capex_reserve", float),
    ("io_period", int),
)


def make_inputs() -> AcquisitionInputs:
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


def test_contract_has_exact_fields_order_annotations_and_keyword_only_shape() -> None:
    contract_fields = fields(AcquisitionInputs)

    assert is_dataclass(AcquisitionInputs)
    assert tuple((field.name, field.type) for field in contract_fields) == EXPECTED_FIELDS
    assert len(contract_fields) == 14
    assert all(field.kw_only for field in contract_fields)
    assert AcquisitionInputs.__slots__ == tuple(name for name, _ in EXPECTED_FIELDS)


def test_contract_is_frozen_and_slotted() -> None:
    inputs = make_inputs()

    assert not hasattr(inputs, "__dict__")
    with pytest.raises(FrozenInstanceError):
        inputs.purchase_price = 1.0  # type: ignore[misc]


def test_contract_rejects_positional_construction() -> None:
    with pytest.raises(TypeError):
        AcquisitionInputs(  # type: ignore[misc]
            50_000_000.0,
            2_500_000.0,
            0.95,
            0.03,
            5,
            0.055,
            0.65,
            0.0525,
            30,
        )


def test_contract_contains_only_supplied_inputs() -> None:
    inputs = make_inputs()

    assert tuple(field.name for field in fields(inputs)) == tuple(
        name for name, _ in EXPECTED_FIELDS
    )
    assert not hasattr(inputs, "source")
    assert not hasattr(inputs, "going_in_cap_rate")
    assert not hasattr(inputs, "irr")


def test_old_nine_field_construction_still_works_via_v2_defaults() -> None:
    """Underwriting V2 Gate 1 backward compatibility: existing internal
    construction using only the original nine keyword arguments must
    continue working, with the five new fields taking their neutral
    dataclass default."""

    inputs = AcquisitionInputs(
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

    assert inputs.acquisition_cost_pct == 0.0
    assert inputs.financing_fee_pct == 0.0
    assert inputs.disposition_cost_pct == 0.0
    assert inputs.annual_capex_reserve == 0.0
    assert inputs.io_period == 0
    assert type(inputs.io_period) is int


def test_v2_fields_can_be_supplied_explicitly() -> None:
    inputs = AcquisitionInputs(
        purchase_price=50_000_000.0,
        current_noi=2_500_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=5,
        exit_cap_rate=0.055,
        ltv=0.65,
        interest_rate=0.0525,
        amortization=30,
        acquisition_cost_pct=0.02,
        financing_fee_pct=0.01,
        disposition_cost_pct=0.025,
        annual_capex_reserve=50_000.0,
        io_period=2,
    )

    assert inputs.acquisition_cost_pct == 0.02
    assert inputs.financing_fee_pct == 0.01
    assert inputs.disposition_cost_pct == 0.025
    assert inputs.annual_capex_reserve == 50_000.0
    assert inputs.io_period == 2


def test_contract_and_validation_imports_do_not_import_openpyxl() -> None:
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
                "import sys; import anchor; import anchor.contracts; "
                "import anchor.validation; "
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
