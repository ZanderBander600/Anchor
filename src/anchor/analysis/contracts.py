"""Phase 7 sensitivity-analysis and Phase 8 break-even-analysis result
contracts.

These are narrow, immutable output contracts for the deterministic
sensitivity layer in ``sensitivity.py`` and the deterministic break-even
layer in ``break_even.py``. Like ``anchor.engine.contracts``, this
module performs no calculation of its own -- it only describes the shape of
already-computed results.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


# =============================================================================
# Phase 8 -- break-even analysis
# =============================================================================


class BreakEvenType(StrEnum):
    """One of the five supported POC break-even questions."""

    MAX_PURCHASE_PRICE = "max_purchase_price"
    MAX_EXIT_CAP_RATE = "max_exit_cap_rate"
    MIN_NOI_GROWTH = "min_noi_growth"
    MAX_INTEREST_RATE = "max_interest_rate"
    MIN_CURRENT_NOI = "min_current_noi"


class ReturnHurdleMetric(StrEnum):
    """Which return metric drives the three return-hurdle break-even
    questions (Maximum Purchase Price, Maximum Exit Cap Rate, Minimum NOI
    Growth). The two DSCR-driven questions (Maximum Interest Rate, Minimum
    Current NOI) always use ``target_headline_dscr`` and are unaffected by
    this selector."""

    LEVERED_IRR = "levered_irr"
    EQUITY_MULTIPLE = "equity_multiple"


class BreakEvenStatus(StrEnum):
    """Outcome of one bounded break-even search.

    ``NO_SOLUTION_IN_RANGE`` means only that no qualifying assumption value
    was found inside ``lower_search_bound``/``upper_search_bound`` -- it is
    not a claim that no solution exists outside that documented interval.
    Consumers (including any future AI Analyst) must not restate this as
    "impossible" or "no solution exists".
    """

    SOLVED = "solved"
    NO_SOLUTION_IN_RANGE = "no_solution_in_range"


@dataclass(frozen=True, slots=True, kw_only=True)
class BreakEvenResult:
    """One deterministic break-even search: the assumption value at which a
    trusted ``AcquisitionResults`` metric first crosses a user-defined
    hurdle, found by bisecting ``analyze_acquisition`` evaluations between
    ``lower_search_bound`` and ``upper_search_bound``.

    ``solved_assumption_value``/``solved_metric_value`` are ``None`` when
    ``status`` is ``NO_SOLUTION_IN_RANGE``. ``baseline_metric_value`` can
    legitimately be ``None`` (e.g. ``headline_dscr`` with zero leverage) --
    this is a real base-case result, not a search failure.
    """

    break_even_type: BreakEvenType
    assumption: str
    metric: str
    target_metric_value: float
    baseline_assumption_value: float
    baseline_metric_value: float | None
    solved_assumption_value: float | None
    solved_metric_value: float | None
    lower_search_bound: float
    upper_search_bound: float
    status: BreakEvenStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class StandardBreakEvenAnalysis:
    """The five standard POC break-even results for one base
    ``AcquisitionInputs`` and its two hurdle targets."""

    max_purchase_price: BreakEvenResult
    max_exit_cap_rate: BreakEvenResult
    min_noi_growth: BreakEvenResult
    max_interest_rate: BreakEvenResult
    min_current_noi: BreakEvenResult
