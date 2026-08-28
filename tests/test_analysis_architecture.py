"""Architecture guardrails for the Phase 7 sensitivity-analysis layer.

Confirms ``anchor.analysis`` sits strictly above the frozen engine --
it must delegate every scenario to ``analyze_acquisition`` rather than
duplicating a financial formula, and must not depend on ``openpyxl`` (the
Excel-ingestion dependency belongs to Phase 1 only).
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

from anchor.analysis import break_even as break_even_module
from anchor.analysis import sensitivity as sensitivity_module
from anchor.analysis import (
    BreakEvenDirection,
    run_one_way_sensitivity,
    run_two_way_sensitivity,
    solve_break_even_threshold,
)
from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition

GOLDEN_INPUTS = AcquisitionInputs(
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

_ANALYSIS_DIR = Path(sensitivity_module.__file__).parent


def test_analysis_package_has_no_openpyxl_import() -> None:
    for source_file in _ANALYSIS_DIR.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            assert not any(
                name is not None and name.startswith("openpyxl") for name in names
            ), f"{source_file} must not import openpyxl"


def test_one_way_sensitivity_calls_analyze_acquisition_for_every_scenario() -> None:
    values = (0.045, 0.05, 0.055, 0.06, 0.065)

    with patch(
        "anchor.analysis.sensitivity.analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        run_one_way_sensitivity(
            GOLDEN_INPUTS,
            assumption="exit_cap_rate",
            values=values,
            metric="levered_irr",
        )

    # One baseline call, plus one call per scenario value.
    assert mock_analyze.call_count == 1 + len(values)


def test_two_way_sensitivity_calls_analyze_acquisition_for_every_cell() -> None:
    row_values = (0.01, 0.02, 0.03)
    column_values = (0.05, 0.055, 0.06, 0.065)

    with patch(
        "anchor.analysis.sensitivity.analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        run_two_way_sensitivity(
            GOLDEN_INPUTS,
            row_assumption="noi_growth",
            row_values=row_values,
            column_assumption="exit_cap_rate",
            column_values=column_values,
            metric="levered_irr",
        )

    # One baseline call, plus one call per matrix cell.
    assert mock_analyze.call_count == 1 + (len(row_values) * len(column_values))


def test_break_even_package_has_no_openpyxl_import() -> None:
    for source_file in Path(break_even_module.__file__).parent.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            assert not any(
                name is not None and name.startswith("openpyxl") for name in names
            ), f"{source_file} must not import openpyxl"


def test_break_even_package_has_no_scipy_or_numpy_import() -> None:
    for source_file in Path(break_even_module.__file__).parent.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                assert not (
                    name is not None
                    and (name.startswith("scipy") or name.startswith("numpy"))
                ), f"{source_file} must not import scipy or numpy"


def test_break_even_solver_calls_analyze_acquisition_for_every_candidate() -> None:
    with patch(
        "anchor.analysis.break_even.analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        solve_break_even_threshold(
            GOLDEN_INPUTS,
            assumption="purchase_price",
            metric="levered_irr",
            target=0.10,
            direction=BreakEvenDirection.MAXIMUM,
            lower_bound=25_000_000.0,
            upper_bound=75_000_000.0,
        )

    # Both bound evaluations, plus every bisection midpoint, went through
    # the authoritative engine entry point -- at least the two bounds.
    assert mock_analyze.call_count >= 2
