"""Phase 7 sensitivity-analysis result contracts.

These are narrow, immutable output contracts for the deterministic
sensitivity layer in ``sensitivity.py``. Like ``mini_anchor.engine.contracts``,
this module performs no calculation of its own -- it only describes the shape
of already-computed sensitivity results.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class OneWaySensitivityResult:
    """One assumption varied across ``assumption_values``, holding all other
    ``AcquisitionInputs`` fixed at their base value.

    ``metric_values[i]`` corresponds exactly to ``assumption_values[i]``.
    """

    assumption: str
    metric: str
    baseline_assumption_value: float
    baseline_metric_value: float | None
    assumption_values: tuple[float, ...]
    metric_values: tuple[float | None, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TwoWaySensitivityResult:
    """Two assumptions varied independently over a grid, holding all other
    ``AcquisitionInputs`` fields fixed at their base value.

    ``matrix[row][column]`` corresponds exactly to ``row_values[row]`` and
    ``column_values[column]``. ``baseline_row_value``/``baseline_column_value``
    identify which grid value (if any) equals the original base input, so
    consumers can locate the baseline cell without re-deriving it from
    position alone -- a domain-filtered preset grid is not guaranteed to have
    the baseline at its center.
    """

    row_assumption: str
    column_assumption: str
    metric: str
    baseline_row_value: float
    baseline_column_value: float
    baseline_metric_value: float | None
    row_values: tuple[float, ...]
    column_values: tuple[float, ...]
    matrix: tuple[tuple[float | None, ...], ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class StandardSensitivityPresets:
    """The three standard POC sensitivity matrices, plus the optional DSCR
    variant of the Interest Rate x LTV matrix."""

    exit_cap_noi_growth: TwoWaySensitivityResult
    purchase_price_exit_cap: TwoWaySensitivityResult
    interest_rate_ltv: TwoWaySensitivityResult
    interest_rate_ltv_dscr: TwoWaySensitivityResult
