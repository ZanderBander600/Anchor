"""Tests for the presentation-only formatting helpers in ``formatting.py``.

These are pure display-formatting tests. They must never assert against a
rounded value that also happens to feed back into a financial calculation --
formatting is presentation-only per ``docs/financial_conventions.md``
"Numeric Precision and Rounding".
"""

from __future__ import annotations

from anchor.formatting import (
    format_bps,
    format_currency,
    format_multiple,
    format_percent,
    format_years,
)


def test_format_currency_formats_with_dollar_sign_and_commas() -> None:
    assert format_currency(50_000_000.0) == "$50,000,000"


def test_format_currency_rounds_to_whole_dollars() -> None:
    assert format_currency(179_466.20319611699) == "$179,466"


def test_format_currency_handles_negative_values() -> None:
    assert format_currency(-17_500_000.0) == "-$17,500,000"


def test_format_currency_handles_zero() -> None:
    assert format_currency(0.0) == "$0"


def test_format_currency_none_is_na() -> None:
    assert format_currency(None) == "N/A"


def test_format_percent_default_two_decimals() -> None:
    assert format_percent(0.05) == "5.00%"
    assert format_percent(0.07913030056780745) == "7.91%"


def test_format_percent_handles_negative() -> None:
    assert format_percent(-0.0125) == "-1.25%"


def test_format_percent_none_is_na() -> None:
    assert format_percent(None) == "N/A"


def test_format_multiple_two_decimals_with_x_suffix() -> None:
    assert format_multiple(1.44288913123241) == "1.44x"
    assert format_multiple(1.1608499518189) == "1.16x"


def test_format_multiple_none_is_na() -> None:
    assert format_multiple(None) == "N/A"


def test_format_multiple_zero() -> None:
    assert format_multiple(0.0) == "0.00x"


def test_format_bps_converts_decimal_spread_to_whole_basis_points() -> None:
    assert format_bps(0.005) == "50 bps"


def test_format_bps_rounds_to_nearest_bps() -> None:
    assert format_bps(0.0055) == "55 bps"


def test_format_bps_zero() -> None:
    assert format_bps(0.0) == "0 bps"


def test_format_bps_none_is_na() -> None:
    assert format_bps(None) == "N/A"


def test_format_years_appends_years_suffix() -> None:
    assert format_years(5) == "5 years"
    assert format_years(30) == "30 years"


def test_format_years_none_is_na() -> None:
    assert format_years(None) == "N/A"
