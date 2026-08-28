"""Tests for the ``python -m anchor`` CLI entry point (``cli.py``).

Covers the full ``Excel file -> read_acquisition_inputs -> analyze_acquisition
-> formatted terminal results`` workflow, error handling for invalid/missing
workbook paths, and that the CLI layer performs no independent financial
calculation of its own.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from anchor.cli import main
from anchor.contracts import AcquisitionInputs
from anchor.engine import AcquisitionResults, analyze_acquisition

EXAMPLE_WORKBOOK = Path(__file__).resolve().parents[1] / "examples" / "anchor_input.xlsx"


def test_cli_valid_workbook_prints_formatted_results(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(EXAMPLE_WORKBOOK)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ANCHOR ACQUISITION ANALYSIS" in captured.out
    assert "ASSUMPTIONS" in captured.out
    assert "Purchase Price:          $50,000,000" in captured.out
    assert "Going-In Cap Rate:        5.00%" in captured.out
    assert "Levered IRR:              7.91%" in captured.out
    assert "Equity Multiple:          1.44x" in captured.out
    assert "RISK FLAGS" in captured.out
    assert "Year 1 DSCR below 1.20x" in captured.out
    assert captured.err == ""


def test_cli_missing_workbook_reports_readable_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    missing = tmp_path / "does_not_exist.xlsx"

    exit_code = main([str(missing)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Could not read workbook" in captured.err
    assert str(missing) in captured.err
    assert captured.out == ""


def test_cli_invalid_extension_reports_readable_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    not_a_workbook = tmp_path / "notes.txt"
    not_a_workbook.write_text("not a workbook")

    exit_code = main([str(not_a_workbook)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Could not read workbook" in captured.err
    assert captured.out == ""


def test_cli_missing_argument_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])

    assert excinfo.value.code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_cli_does_not_independently_calculate_financial_outputs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI must call the frozen engine's ``analyze_acquisition`` exactly
    once with the inputs read from the workbook, and print exactly what
    ``build_report`` produces from that result -- never compute a financial
    value itself."""

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
    expected_results = analyze_acquisition(inputs)
    sentinel_report = "SENTINEL REPORT TEXT"

    with (
        patch("anchor.cli.read_acquisition_inputs", return_value=inputs) as mock_read,
        patch(
            "anchor.cli.analyze_acquisition", wraps=analyze_acquisition
        ) as mock_analyze,
        patch("anchor.cli.build_report", return_value=sentinel_report) as mock_build,
    ):
        exit_code = main([str(EXAMPLE_WORKBOOK)])

    assert exit_code == 0
    mock_read.assert_called_once_with(str(EXAMPLE_WORKBOOK))
    mock_analyze.assert_called_once_with(inputs)
    mock_build.assert_called_once()
    called_inputs, called_results = mock_build.call_args.args
    assert called_inputs == inputs
    assert called_results == expected_results

    captured = capsys.readouterr()
    assert captured.out == sentinel_report + "\n"


def test_cli_result_type_is_frozen_acquisition_results() -> None:
    """Guard against the CLI layer swapping in its own ad hoc result type."""

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
    assert isinstance(analyze_acquisition(inputs), AcquisitionResults)
