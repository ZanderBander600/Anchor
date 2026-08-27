"""Minimal terminal entry point: Excel workbook -> formatted results.

This module is a thin presentation/orchestration layer. It calls
``read_acquisition_inputs`` and ``analyze_acquisition`` -- the two existing,
frozen Phase 1/Phase 2 functions -- and never reproduces or reimplements any
financial formula itself.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .engine import analyze_acquisition
from .excel_reader import read_acquisition_inputs
from .report import build_report
from .validation import InputValidationError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m anchor",
        description=(
            "Analyze a Anchor Excel acquisition workbook and print a "
            "formatted investment summary."
        ),
    )
    parser.add_argument(
        "workbook",
        help="Path to the .xlsx acquisition workbook (must contain an 'Inputs' sheet).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        inputs = read_acquisition_inputs(args.workbook)
    except InputValidationError as error:
        print(f"Could not read workbook: {args.workbook}", file=sys.stderr)
        for issue in error.issues:
            print(f"  - {issue.message}", file=sys.stderr)
        return 1

    results = analyze_acquisition(inputs)
    print(build_report(inputs, results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
