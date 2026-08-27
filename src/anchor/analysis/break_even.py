"""Phase 8 deterministic break-even analysis, built on top of the frozen
Phase 2 engine.

This module never reproduces a financial formula and never algebraically
rearranges one -- it only asks a threshold question. Every candidate
assumption value is evaluated by constructing one validated
``AcquisitionInputs`` (via the shared ``validate_acquisition_inputs``, never
a duplicated domain check) and calling the existing authoritative
``analyze_acquisition`` exactly once; a break-even result only reads a field
off the returned ``AcquisitionResults`` and compares it to a user-supplied
hurdle. The search itself is a plain bounded bisection over the assumption
value -- no ``scipy``, no numerical optimizer, no symbolic algebra.

Architecture (mirrors ``sensitivity.py``):

    financial engine
          ^
    analysis/break_even
          ^
        FastAPI
          ^
         React
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from math import isfinite

from ..contracts import AcquisitionInputs
from ..engine import AcquisitionResults, analyze_acquisition
from ..validation import FIELD_IDS, InputValidationError, validate_acquisition_inputs
from .contracts import (
    BreakEvenResult,
    BreakEvenStatus,
    BreakEvenType,
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
)

# =============================================================================
# Supported break-even metrics
# =============================================================================

# Restricted to exactly the two metrics the five POC break-even questions
# use (docs: "POC Break-Even Questions"). Unlike ``sensitivity.py``'s
# open assumption/metric matrix, break-even scope is intentionally fixed to
# five named questions -- no generic assumption/metric selector is exposed.
_METRIC_EXTRACTORS: dict[str, Callable[[AcquisitionResults], float | None]] = {
    "levered_irr": lambda results: results.levered_irr,
    "headline_dscr": lambda results: results.headline_dscr,
    "equity_multiple": lambda results: results.equity_multiple,
}


def _extract_metric(results: AcquisitionResults, metric: str) -> float | None:
    return _METRIC_EXTRACTORS[metric](results)


def _build_scenario_inputs(
    base: AcquisitionInputs, changes: Mapping[str, float]
) -> AcquisitionInputs:
    """Return a new validated ``AcquisitionInputs`` with ``changes`` applied
    on top of ``base``. ``base`` is never mutated -- it is frozen, and only
    read here to seed the unchanged fields."""

    values: dict[str, float | int] = {
        field_id: getattr(base, field_id) for field_id in FIELD_IDS
    }
    values.update(changes)
    return validate_acquisition_inputs(values)


def _evaluate_candidate(
    inputs: AcquisitionInputs, *, assumption: str, metric: str, candidate_value: float
) -> float | None:
    """Build one validated candidate scenario, call the authoritative
    ``analyze_acquisition`` exactly once, and read off ``metric``.

    Never converts a legitimately ``None`` metric (e.g. ``headline_dscr``
    under zero leverage) to zero, infinity, or any fabricated value.
    """

    scenario_inputs = _build_scenario_inputs(inputs, {assumption: candidate_value})
    scenario_results = analyze_acquisition(scenario_inputs)
    return _extract_metric(scenario_results, metric)


def _meets_hurdle(metric_value: float | None, target: float) -> bool:
    """A ``None`` metric never satisfies a hurdle -- it is simply a failing
    candidate, deterministically, never a fabricated pass or fail sentinel."""

    return metric_value is not None and metric_value >= target


# =============================================================================
# Errors
# =============================================================================


class InvalidBreakEvenBoundsError(ValueError):
    """Raised when explicit break-even search bounds are invalid: the lower
    bound is not strictly less than the upper bound, or either bound fails
    the shared ``AcquisitionInputs`` domain validation for its assumption."""


class InvalidBreakEvenTargetError(ValueError):
    """Raised when a user-supplied hurdle target (target Levered IRR or
    target headline DSCR) is outside its valid domain."""


# =============================================================================
# Core bounded threshold solver
# =============================================================================


class BreakEvenDirection(StrEnum):
    """Which end of ``[lower_bound, upper_bound]`` is expected to satisfy the
    hurdle for a "maximum" vs. "minimum" break-even question.

    ``MAXIMUM`` (e.g. Maximum Purchase Price, Maximum Exit Cap, Maximum
    Interest Rate): the hurdle is satisfied at ``lower_bound`` and fails by
    ``upper_bound``; the solver returns the highest qualifying value.

    ``MINIMUM`` (e.g. Minimum NOI Growth, Minimum Current NOI): the hurdle
    fails at ``lower_bound`` and is satisfied by ``upper_bound``; the solver
    returns the lowest qualifying value.

    This is a search-orientation label describing where the caller expects
    the qualifying region to sit -- the solver evaluates both endpoints and
    never assumes monotonicity beyond that.
    """

    MAXIMUM = "maximum"
    MINIMUM = "minimum"


# Deterministic stopping tolerances, one per break-even assumption, chosen to
# be far finer than any presentation rounding the POC UI performs while
# staying well clear of floating-point noise:
#   - dollar assumptions (purchase price, current NOI): $1,000 / $100 --
#     immaterial at POC deal sizes (tens of millions / low millions).
#   - rate assumptions (exit cap, NOI growth, interest rate): 0.5 basis
#     points (0.00005), an order of magnitude finer than the 2-decimal
#     percentage points the UI displays.
_ASSUMPTION_TOLERANCES: dict[str, float] = {
    "purchase_price": 1_000.0,
    "exit_cap_rate": 0.00005,
    "noi_growth": 0.00005,
    "interest_rate": 0.00005,
    "current_noi": 100.0,
}

# Generous iteration ceiling for the fixed-tolerance bisection below. Each
# iteration halves the bracket, so this is never reached in practice at POC
# search-range magnitudes (it would take ~50 iterations to bisect a
# $75M range down to $1,000) -- it exists only as a deterministic backstop.
_MAX_ITERATIONS = 100


def solve_break_even_threshold(
    inputs: AcquisitionInputs,
    *,
    assumption: str,
    metric: str,
    target: float,
    direction: BreakEvenDirection,
    lower_bound: float,
    upper_bound: float,
) -> tuple[float | None, float | None, BreakEvenStatus]:
    """Bounded bisection-style threshold search between ``lower_bound`` and
    ``upper_bound``.

    Returns ``(solved_assumption_value, solved_metric_value, status)``.
    Every evaluation constructs a new validated ``AcquisitionInputs`` and
    calls ``analyze_acquisition`` -- ``inputs`` itself is never mutated and
    no financial formula is reproduced here.

    Raises ``InvalidBreakEvenBoundsError`` if ``lower_bound`` is not strictly
    less than ``upper_bound``, or if either bound is outside the shared input
    domain for ``assumption``.
    """

    if not (lower_bound < upper_bound):
        raise InvalidBreakEvenBoundsError(
            f"lower_search_bound must be strictly less than upper_search_bound "
            f"for {assumption!r}; got lower={lower_bound!r}, upper={upper_bound!r}."
        )

    try:
        metric_at_lower = _evaluate_candidate(
            inputs, assumption=assumption, metric=metric, candidate_value=lower_bound
        )
    except InputValidationError as error:
        raise InvalidBreakEvenBoundsError(
            f"lower_search_bound {lower_bound!r} is not a valid {assumption!r} value: {error}"
        ) from error

    try:
        metric_at_upper = _evaluate_candidate(
            inputs, assumption=assumption, metric=metric, candidate_value=upper_bound
        )
    except InputValidationError as error:
        raise InvalidBreakEvenBoundsError(
            f"upper_search_bound {upper_bound!r} is not a valid {assumption!r} value: {error}"
        ) from error

    if direction is BreakEvenDirection.MAXIMUM:
        favorable_value, favorable_metric = lower_bound, metric_at_lower
        unfavorable_value, unfavorable_metric = upper_bound, metric_at_upper
    else:
        favorable_value, favorable_metric = upper_bound, metric_at_upper
        unfavorable_value, unfavorable_metric = lower_bound, metric_at_lower

    # Not even the most favorable end of the documented range satisfies the
    # hurdle -- report NO_SOLUTION_IN_RANGE, never "impossible".
    if not _meets_hurdle(favorable_metric, target):
        return None, None, BreakEvenStatus.NO_SOLUTION_IN_RANGE

    # The entire range satisfies the hurdle -- the extreme (least favorable)
    # value in the documented range is itself the qualifying boundary.
    if _meets_hurdle(unfavorable_metric, target):
        return unfavorable_value, unfavorable_metric, BreakEvenStatus.SOLVED

    tolerance = _ASSUMPTION_TOLERANCES[assumption]
    qualifying_value, qualifying_metric = favorable_value, favorable_metric
    failing_value = unfavorable_value

    for _ in range(_MAX_ITERATIONS):
        if abs(failing_value - qualifying_value) <= tolerance:
            break
        midpoint = (qualifying_value + failing_value) / 2
        midpoint_metric = _evaluate_candidate(
            inputs, assumption=assumption, metric=metric, candidate_value=midpoint
        )
        if _meets_hurdle(midpoint_metric, target):
            qualifying_value, qualifying_metric = midpoint, midpoint_metric
        else:
            failing_value = midpoint

    return qualifying_value, qualifying_metric, BreakEvenStatus.SOLVED


# =============================================================================
# Target hurdle validation
# =============================================================================


def _validate_target_levered_irr(target_levered_irr: float) -> None:
    if not isfinite(target_levered_irr) or target_levered_irr <= -1.0:
        raise InvalidBreakEvenTargetError(
            "target_levered_irr must be finite and greater than -100% (-1.0); "
            f"got {target_levered_irr!r}."
        )


def _validate_target_headline_dscr(target_headline_dscr: float) -> None:
    if not isfinite(target_headline_dscr) or target_headline_dscr <= 0.0:
        raise InvalidBreakEvenTargetError(
            f"target_headline_dscr must be finite and greater than 0; got {target_headline_dscr!r}."
        )


def _validate_target_equity_multiple(target_equity_multiple: float) -> None:
    if not isfinite(target_equity_multiple) or target_equity_multiple <= 0.0:
        raise InvalidBreakEvenTargetError(
            "target_equity_multiple must be finite and greater than 0; "
            f"got {target_equity_multiple!r}."
        )


def _resolve_return_hurdle(
    *, target_levered_irr: float | None, target_equity_multiple: float | None
) -> tuple[str, float]:
    """Resolve the two mutually exclusive return-hurdle target parameters
    accepted by the three return-driven break-even questions (Maximum
    Purchase Price, Maximum Exit Cap Rate, Minimum NOI Growth) into the
    ``(metric, target)`` pair ``solve_break_even_threshold`` needs.

    Exactly one of ``target_levered_irr``/``target_equity_multiple`` must be
    provided -- the caller picks the return hurdle, this never guesses which
    one was intended.
    """

    if (target_levered_irr is None) == (target_equity_multiple is None):
        raise InvalidBreakEvenTargetError(
            "Exactly one of target_levered_irr or target_equity_multiple must "
            f"be provided; got target_levered_irr={target_levered_irr!r}, "
            f"target_equity_multiple={target_equity_multiple!r}."
        )
    if target_levered_irr is not None:
        _validate_target_levered_irr(target_levered_irr)
        return "levered_irr", target_levered_irr
    _validate_target_equity_multiple(target_equity_multiple)
    return "equity_multiple", target_equity_multiple


# =============================================================================
# Default (documented) search bounds
# =============================================================================


def _default_purchase_price_bounds(inputs: AcquisitionInputs) -> tuple[float, float]:
    """50% to 150% of the baseline purchase price."""

    return inputs.purchase_price * 0.5, inputs.purchase_price * 1.5


def _default_exit_cap_rate_bounds(inputs: AcquisitionInputs) -> tuple[float, float]:
    """``max(0.005, baseline - 3pp)`` through ``baseline + 5pp``."""

    return max(0.005, inputs.exit_cap_rate - 0.03), inputs.exit_cap_rate + 0.05


def _default_noi_growth_bounds(inputs: AcquisitionInputs) -> tuple[float, float]:
    """``max(-0.20, baseline - 10pp)`` through ``baseline + 10pp``."""

    return max(-0.20, inputs.noi_growth - 0.10), inputs.noi_growth + 0.10


def _default_interest_rate_bounds(inputs: AcquisitionInputs) -> tuple[float, float]:
    """``0.0`` through ``max(0.20, baseline + 10pp)``."""

    return 0.0, max(0.20, inputs.interest_rate + 0.10)


def _default_current_noi_bounds(inputs: AcquisitionInputs) -> tuple[float, float]:
    """50% to 150% of the baseline Current NOI."""

    return inputs.current_noi * 0.5, inputs.current_noi * 1.5


def _resolve_bounds(
    lower_bound: float | None,
    upper_bound: float | None,
    defaults: tuple[float, float],
) -> tuple[float, float]:
    default_lower, default_upper = defaults
    resolved_lower = default_lower if lower_bound is None else lower_bound
    resolved_upper = default_upper if upper_bound is None else upper_bound
    return resolved_lower, resolved_upper


# =============================================================================
# The five standard POC break-even questions
# =============================================================================


def _build_break_even_result(
    inputs: AcquisitionInputs,
    *,
    break_even_type: BreakEvenType,
    assumption: str,
    metric: str,
    target: float,
    direction: BreakEvenDirection,
    lower_bound: float,
    upper_bound: float,
) -> BreakEvenResult:
    baseline_assumption_value = getattr(inputs, assumption)
    baseline_metric_value = _extract_metric(analyze_acquisition(inputs), metric)

    solved_assumption_value, solved_metric_value, status = solve_break_even_threshold(
        inputs,
        assumption=assumption,
        metric=metric,
        target=target,
        direction=direction,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )

    return BreakEvenResult(
        break_even_type=break_even_type,
        assumption=assumption,
        metric=metric,
        target_metric_value=target,
        baseline_assumption_value=baseline_assumption_value,
        baseline_metric_value=baseline_metric_value,
        solved_assumption_value=solved_assumption_value,
        solved_metric_value=solved_metric_value,
        lower_search_bound=lower_bound,
        upper_search_bound=upper_bound,
        status=status,
    )


def solve_max_purchase_price(
    inputs: AcquisitionInputs,
    *,
    target_levered_irr: float | None = None,
    target_equity_multiple: float | None = None,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> BreakEvenResult:
    """Highest Purchase Price at which the selected return hurdle still
    meets its target, searched over ``[lower_bound, upper_bound]`` (default:
    50%-150% of the baseline purchase price).

    Exactly one of ``target_levered_irr`` or ``target_equity_multiple`` must
    be provided; that choice selects which trusted ``AcquisitionResults``
    metric is used, unchanged from ``analyze_acquisition``."""

    metric, target = _resolve_return_hurdle(
        target_levered_irr=target_levered_irr, target_equity_multiple=target_equity_multiple
    )
    lo, hi = _resolve_bounds(
        lower_bound, upper_bound, _default_purchase_price_bounds(inputs)
    )
    return _build_break_even_result(
        inputs,
        break_even_type=BreakEvenType.MAX_PURCHASE_PRICE,
        assumption="purchase_price",
        metric=metric,
        target=target,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=lo,
        upper_bound=hi,
    )


def solve_max_exit_cap_rate(
    inputs: AcquisitionInputs,
    *,
    target_levered_irr: float | None = None,
    target_equity_multiple: float | None = None,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> BreakEvenResult:
    """Highest Exit Cap Rate at which the selected return hurdle still
    meets its target, searched over ``[lower_bound, upper_bound]`` (default:
    ``max(0.005, baseline - 3pp)`` through ``baseline + 5pp``).

    Exactly one of ``target_levered_irr`` or ``target_equity_multiple`` must
    be provided; that choice selects which trusted ``AcquisitionResults``
    metric is used, unchanged from ``analyze_acquisition``."""

    metric, target = _resolve_return_hurdle(
        target_levered_irr=target_levered_irr, target_equity_multiple=target_equity_multiple
    )
    lo, hi = _resolve_bounds(
        lower_bound, upper_bound, _default_exit_cap_rate_bounds(inputs)
    )
    return _build_break_even_result(
        inputs,
        break_even_type=BreakEvenType.MAX_EXIT_CAP_RATE,
        assumption="exit_cap_rate",
        metric=metric,
        target=target,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=lo,
        upper_bound=hi,
    )


def solve_min_noi_growth(
    inputs: AcquisitionInputs,
    *,
    target_levered_irr: float | None = None,
    target_equity_multiple: float | None = None,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> BreakEvenResult:
    """Lowest NOI Growth at which the selected return hurdle still meets
    its target, searched over ``[lower_bound, upper_bound]`` (default:
    ``max(-0.20, baseline - 10pp)`` through ``baseline + 10pp``).

    Exactly one of ``target_levered_irr`` or ``target_equity_multiple`` must
    be provided; that choice selects which trusted ``AcquisitionResults``
    metric is used, unchanged from ``analyze_acquisition``."""

    metric, target = _resolve_return_hurdle(
        target_levered_irr=target_levered_irr, target_equity_multiple=target_equity_multiple
    )
    lo, hi = _resolve_bounds(
        lower_bound, upper_bound, _default_noi_growth_bounds(inputs)
    )
    return _build_break_even_result(
        inputs,
        break_even_type=BreakEvenType.MIN_NOI_GROWTH,
        assumption="noi_growth",
        metric=metric,
        target=target,
        direction=BreakEvenDirection.MINIMUM,
        lower_bound=lo,
        upper_bound=hi,
    )


def solve_max_interest_rate(
    inputs: AcquisitionInputs,
    *,
    target_headline_dscr: float,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> BreakEvenResult:
    """Highest Interest Rate at which Year 1 (headline) DSCR still meets
    ``target_headline_dscr``, searched over ``[lower_bound, upper_bound]``
    (default: ``0.0`` through ``max(0.20, baseline + 10pp)``)."""

    _validate_target_headline_dscr(target_headline_dscr)
    lo, hi = _resolve_bounds(
        lower_bound, upper_bound, _default_interest_rate_bounds(inputs)
    )
    return _build_break_even_result(
        inputs,
        break_even_type=BreakEvenType.MAX_INTEREST_RATE,
        assumption="interest_rate",
        metric="headline_dscr",
        target=target_headline_dscr,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=lo,
        upper_bound=hi,
    )


def solve_min_current_noi(
    inputs: AcquisitionInputs,
    *,
    target_headline_dscr: float,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> BreakEvenResult:
    """Lowest Current NOI at which Year 1 (headline) DSCR still meets
    ``target_headline_dscr``, searched over ``[lower_bound, upper_bound]``
    (default: 50%-150% of the baseline Current NOI)."""

    _validate_target_headline_dscr(target_headline_dscr)
    lo, hi = _resolve_bounds(
        lower_bound, upper_bound, _default_current_noi_bounds(inputs)
    )
    return _build_break_even_result(
        inputs,
        break_even_type=BreakEvenType.MIN_CURRENT_NOI,
        assumption="current_noi",
        metric="headline_dscr",
        target=target_headline_dscr,
        direction=BreakEvenDirection.MINIMUM,
        lower_bound=lo,
        upper_bound=hi,
    )


def build_standard_break_even_analysis(
    inputs: AcquisitionInputs,
    *,
    target_levered_irr: float,
    target_headline_dscr: float,
    target_equity_multiple: float | None = None,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
) -> StandardBreakEvenAnalysis:
    """Run all five standard POC break-even questions for one base
    ``AcquisitionInputs``, each using its documented default search range.

    The three return-driven questions (Maximum Purchase Price, Maximum Exit
    Cap Rate, Minimum NOI Growth) are solved against whichever return hurdle
    ``return_hurdle_metric`` selects: Levered IRR (``target_levered_irr``,
    the default) or Equity Multiple (``target_equity_multiple``, required
    when selected). The two DSCR-driven questions (Maximum Interest Rate,
    Minimum Current NOI) always use ``target_headline_dscr`` and are
    unaffected by ``return_hurdle_metric``."""

    if return_hurdle_metric is ReturnHurdleMetric.EQUITY_MULTIPLE:
        if target_equity_multiple is None:
            raise InvalidBreakEvenTargetError(
                "target_equity_multiple is required when return_hurdle_metric "
                "is 'equity_multiple'."
            )
        return_hurdle_kwargs: dict[str, float] = {
            "target_equity_multiple": target_equity_multiple
        }
    else:
        return_hurdle_kwargs = {"target_levered_irr": target_levered_irr}

    return StandardBreakEvenAnalysis(
        max_purchase_price=solve_max_purchase_price(inputs, **return_hurdle_kwargs),
        max_exit_cap_rate=solve_max_exit_cap_rate(inputs, **return_hurdle_kwargs),
        min_noi_growth=solve_min_noi_growth(inputs, **return_hurdle_kwargs),
        max_interest_rate=solve_max_interest_rate(
            inputs, target_headline_dscr=target_headline_dscr
        ),
        min_current_noi=solve_min_current_noi(
            inputs, target_headline_dscr=target_headline_dscr
        ),
    )
