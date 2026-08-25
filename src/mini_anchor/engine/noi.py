"""Phase 2A NOI forecast, exit NOI, and going-in cap rate.

Restates ``docs/financial_conventions.md`` "NOI forecast and going-in cap
rate" exactly; that document governs on any discrepancy. Occupancy is
informational only and is never read here.
"""

from __future__ import annotations

from math import inf

from ..contracts import AcquisitionInputs
from .contracts import NoiForecast, ensure_finite


def _growth_factor(noi_growth: float, exponent: int) -> float:
    """Return ``(1 + noi_growth) ** exponent``.

    CPython's ``float ** int`` raises ``OverflowError`` instead of returning
    ``inf`` when the mathematical result exceeds double precision. Since
    ``noi_growth > -1`` is already guaranteed by the input domain, the base
    is always positive, so an overflow can only mean the true result is
    unrepresentably large and positive; it is surfaced as ``inf`` here so the
    Phase 2A non-finite safety rule can catch and reject it explicitly.
    """

    try:
        return (1 + noi_growth) ** exponent
    except OverflowError:
        return inf


def calculate_noi_by_year(
    *, current_noi: float, noi_growth: float, hold_period: int
) -> tuple[float, ...]:
    """Return ``NOI_1 .. NOI_H``, where ``NOI_1 = current_noi`` and growth
    begins in year 2."""

    if current_noi == 0.0:
        return tuple(0.0 for _ in range(hold_period))

    noi_by_year = []
    for year in range(1, hold_period + 1):
        noi_y = current_noi * _growth_factor(noi_growth, year - 1)
        noi_by_year.append(ensure_finite(f"noi_by_year[{year - 1}]", noi_y))
    return tuple(noi_by_year)


def calculate_exit_noi(
    *, current_noi: float, noi_growth: float, hold_period: int
) -> float:
    """Return the forward NOI used only for the exit-value calculation."""

    if current_noi == 0.0:
        return 0.0

    exit_noi = current_noi * _growth_factor(noi_growth, hold_period)
    return ensure_finite("exit_noi", exit_noi)


def calculate_going_in_cap_rate(
    *, current_noi: float, purchase_price: float
) -> float:
    going_in_cap_rate = current_noi / purchase_price
    return ensure_finite("going_in_cap_rate", going_in_cap_rate)


def forecast_noi(inputs: AcquisitionInputs) -> NoiForecast:
    """Compute the Phase 2A NOI forecast for one ``AcquisitionInputs``."""

    noi_by_year = calculate_noi_by_year(
        current_noi=inputs.current_noi,
        noi_growth=inputs.noi_growth,
        hold_period=inputs.hold_period,
    )
    exit_noi = calculate_exit_noi(
        current_noi=inputs.current_noi,
        noi_growth=inputs.noi_growth,
        hold_period=inputs.hold_period,
    )
    going_in_cap_rate = calculate_going_in_cap_rate(
        current_noi=inputs.current_noi,
        purchase_price=inputs.purchase_price,
    )
    return NoiForecast(
        noi_by_year=noi_by_year,
        exit_noi=exit_noi,
        going_in_cap_rate=going_in_cap_rate,
    )
