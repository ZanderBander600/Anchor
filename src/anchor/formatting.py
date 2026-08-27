"""Presentation-only formatting helpers for terminal display.

These functions never alter, round, or otherwise touch a raw
``AcquisitionResults`` value before it is used in a calculation -- they are
called only when a value is about to be printed. Rounding here is
display-only, per ``docs/financial_conventions.md`` "Numeric Precision and
Rounding": "Rounding is presentation-only ... UI or CLI display formatting
must not alter the underlying stored or calculated value."

This module performs no financial calculation of its own.
"""

from __future__ import annotations


def format_currency(value: float | None) -> str:
    """Format a dollar amount as ``$1,234,567`` (or ``-$1,234,567``)."""

    if value is None:
        return "N/A"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def format_percent(value: float | None, decimals: int = 2) -> str:
    """Format a decimal fraction as a percentage, e.g. ``0.0791`` -> ``7.91%``."""

    if value is None:
        return "N/A"
    return f"{value * 100:.{decimals}f}%"


def format_multiple(value: float | None) -> str:
    """Format a multiple as ``1.44x`` (used for Equity Multiple and DSCR)."""

    if value is None:
        return "N/A"
    return f"{value:.2f}x"


def format_bps(value: float | None) -> str:
    """Format a decimal fraction spread as basis points, e.g. ``0.005`` -> ``50 bps``."""

    if value is None:
        return "N/A"
    return f"{round(value * 10_000):.0f} bps"


def format_years(value: int | None) -> str:
    """Format an integer year count as ``5 years``."""

    if value is None:
        return "N/A"
    return f"{value} years"
