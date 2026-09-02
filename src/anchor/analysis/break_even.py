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

import dataclasses
from collections.abc import Callable, Mapping
from enum import StrEnum
from math import isfinite

from ..contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from ..engine import (
    AcquisitionResults,
    analyze_acquisition,
    analyze_detailed_acquisition_with_projection,
)
from ..validation import (
    InputValidationError,
    validate_acquisition_inputs,
    validate_acquisition_terms,
)
from .contracts import (
    BreakEvenResult,
    BreakEvenStatus,
    BreakEvenType,
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
    StandardDetailedBreakEvenAnalysis,
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
    on top of ``base``. ``base`` is never mutated -- it is frozen.

    Uses ``dataclasses.replace`` (via ``dataclasses.asdict`` into the shared
    validator) rather than seeding a values dict from a hand-maintained
    field-id list: every field of ``base`` not named in ``changes`` --
    including all five Underwriting V2 fields, and any field added in the
    future -- carries over automatically. A field-list reconstruction here
    previously reset every candidate's V2 fields (acquisition_cost_pct,
    financing_fee_pct, disposition_cost_pct, annual_capex_reserve, io_period)
    to their neutral defaults, silently discarding a V2 base deal's actual
    assumptions in every break-even candidate (Gate 9A root cause). Still
    routed through ``validate_acquisition_inputs`` -- domain validation is
    never reimplemented here, and an out-of-domain candidate (including a
    search bound) still raises ``InputValidationError`` exactly as before.
    """

    candidate = dataclasses.replace(base, **changes)
    return validate_acquisition_inputs(dataclasses.asdict(candidate))


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


def _resolve_undefined_favorable_endpoint(
    inputs: AcquisitionInputs,
    *,
    assumption: str,
    metric: str,
    undefined_value: float,
    other_value: float,
    other_metric: float | None,
    tolerance: float,
    max_iterations: int,
) -> tuple[float, float] | tuple[None, None]:
    """Gate 9G: the documented favorable endpoint (``undefined_value``)
    evaluated to an undefined (``None``) ``metric`` -- e.g. ``headline_dscr``
    is ``None`` at ``interest_rate == 0.0`` with a positive ``io_period``,
    because Year-1 annual debt service is then exactly zero. That is a
    correct, frozen engine convention (never fabricated as zero or
    infinity) -- but an undefined *endpoint* is not evidence that ``metric``
    is undefined everywhere in the search interval, so it must not by
    itself force ``NO_SOLUTION_IN_RANGE``.

    Bisects between ``undefined_value`` and ``other_value`` for the point
    closest to ``undefined_value`` at which ``metric`` first becomes
    defined -- the same deterministic, tolerance-bounded bisection style as
    the main threshold search, generalized over any assumption/metric this
    solver evaluates (never a hardcoded probe offset). The caller then
    treats the returned point as the effective favorable boundary and
    proceeds with the existing, unchanged solver logic from there, so a
    genuine threshold discovered beyond it is still located exactly as
    before.

    Returns ``(None, None)`` if ``metric`` is undefined at ``other_value``
    too -- the whole interval is undefined, so there is genuinely nothing
    to search (a real ``NO_SOLUTION_IN_RANGE``, not a boundary artifact).
    """

    if other_metric is None:
        return None, None

    still_undefined_value = undefined_value
    defined_value, defined_metric = other_value, other_metric

    for _ in range(max_iterations):
        if abs(defined_value - still_undefined_value) <= tolerance:
            break
        midpoint = (still_undefined_value + defined_value) / 2
        midpoint_metric = _evaluate_candidate(
            inputs, assumption=assumption, metric=metric, candidate_value=midpoint
        )
        if midpoint_metric is None:
            still_undefined_value = midpoint
        else:
            defined_value, defined_metric = midpoint, midpoint_metric

    return defined_value, defined_metric


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

    tolerance = _ASSUMPTION_TOLERANCES[assumption]

    # Gate 9G: the documented favorable endpoint itself may be an undefined
    # (None) metric (e.g. headline_dscr at interest_rate == 0.0 with a
    # positive io_period -- zero Year-1 debt service is a correct, frozen
    # engine convention, not a fabricated value). That does not mean no
    # solution exists in the interval -- resolve to the nearest point with a
    # defined metric before deciding, so a real qualifying value found just
    # inside the boundary is never masked as NO_SOLUTION_IN_RANGE.
    if favorable_metric is None:
        favorable_value, favorable_metric = _resolve_undefined_favorable_endpoint(
            inputs,
            assumption=assumption,
            metric=metric,
            undefined_value=favorable_value,
            other_value=unfavorable_value,
            other_metric=unfavorable_metric,
            tolerance=tolerance,
            max_iterations=_MAX_ITERATIONS,
        )

    # Not even the most favorable end of the documented range satisfies the
    # hurdle -- report NO_SOLUTION_IN_RANGE, never "impossible". This also
    # covers the case above where the metric is undefined throughout the
    # entire interval (``_resolve_undefined_favorable_endpoint`` returns
    # ``None``, which never satisfies a hurdle either).
    if not _meets_hurdle(favorable_metric, target):
        return None, None, BreakEvenStatus.NO_SOLUTION_IN_RANGE

    # The entire range satisfies the hurdle -- the extreme (least favorable)
    # value in the documented range is itself the qualifying boundary.
    if _meets_hurdle(unfavorable_metric, target):
        return unfavorable_value, unfavorable_metric, BreakEvenStatus.SOLVED

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


# =============================================================================
# Detailed Operating Model V2.1 Gate 8 -- Detailed break-even
#
# Only the three questions that are structurally meaningful for a Detailed
# deal: Maximum Purchase Price, Maximum Exit Cap Rate (both AcquisitionTerms
# fields), and Maximum Interest Rate (also an AcquisitionTerms field).
# Minimum NOI Growth and Minimum Current NOI have no Detailed counterpart --
# neither noi_growth nor current_noi exists on AcquisitionTerms/
# DetailedOperatingInputs (Gate 3/4's resolution) -- so no Detailed version
# of either is added. Every candidate preserves detailed_operating_inputs
# completely unchanged, mirroring sensitivity.py's Detailed extension and
# the same Gate 9A-generalizing pattern: dataclasses.replace on the complete
# AcquisitionTerms contract, never a partial reconstruction.
# =============================================================================


def _build_detailed_scenario_terms(
    base: AcquisitionTerms, changes: Mapping[str, float]
) -> AcquisitionTerms:
    """Detailed counterpart to ``_build_scenario_inputs``. ``base`` is never
    mutated -- it is frozen. Still routed through
    ``validate_acquisition_terms`` -- domain validation is never
    reimplemented here."""

    candidate = dataclasses.replace(base, **changes)
    return validate_acquisition_terms(dataclasses.asdict(candidate))


def _evaluate_detailed_candidate(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    assumption: str,
    metric: str,
    candidate_value: float,
) -> float | None:
    """Build one validated candidate ``AcquisitionTerms`` scenario, call
    ``analyze_detailed_acquisition_with_projection`` exactly once, and read
    off ``metric``. ``detailed_operating_inputs`` is passed through
    unchanged -- never varied, never dropped. Never converts a legitimately
    ``None`` metric to zero, infinity, or any fabricated value."""

    scenario_terms = _build_detailed_scenario_terms(terms, {assumption: candidate_value})
    scenario_results = analyze_detailed_acquisition_with_projection(
        scenario_terms, detailed_operating_inputs
    ).results
    return _extract_metric(scenario_results, metric)


def _resolve_undefined_favorable_endpoint_detailed(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    assumption: str,
    metric: str,
    undefined_value: float,
    other_value: float,
    other_metric: float | None,
    tolerance: float,
    max_iterations: int,
) -> tuple[float, float] | tuple[None, None]:
    """Detailed counterpart to ``_resolve_undefined_favorable_endpoint``
    (Gate 9G) -- identical bisection-to-first-defined-point logic, evaluated
    via ``_evaluate_detailed_candidate`` instead."""

    if other_metric is None:
        return None, None

    still_undefined_value = undefined_value
    defined_value, defined_metric = other_value, other_metric

    for _ in range(max_iterations):
        if abs(defined_value - still_undefined_value) <= tolerance:
            break
        midpoint = (still_undefined_value + defined_value) / 2
        midpoint_metric = _evaluate_detailed_candidate(
            terms,
            detailed_operating_inputs,
            assumption=assumption,
            metric=metric,
            candidate_value=midpoint,
        )
        if midpoint_metric is None:
            still_undefined_value = midpoint
        else:
            defined_value, defined_metric = midpoint, midpoint_metric

    return defined_value, defined_metric


def solve_detailed_break_even_threshold(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    assumption: str,
    metric: str,
    target: float,
    direction: BreakEvenDirection,
    lower_bound: float,
    upper_bound: float,
) -> tuple[float | None, float | None, BreakEvenStatus]:
    """Detailed counterpart to ``solve_break_even_threshold`` -- the
    identical bounded bisection-style threshold search, evaluated via
    ``_evaluate_detailed_candidate``/``_resolve_undefined_favorable_endpoint_detailed``
    instead. ``detailed_operating_inputs`` is passed through unchanged to
    every evaluation.

    Raises ``InvalidBreakEvenBoundsError`` if ``lower_bound`` is not
    strictly less than ``upper_bound``, or if either bound is outside the
    shared ``AcquisitionTerms`` domain for ``assumption``.
    """

    if not (lower_bound < upper_bound):
        raise InvalidBreakEvenBoundsError(
            f"lower_search_bound must be strictly less than upper_search_bound "
            f"for {assumption!r}; got lower={lower_bound!r}, upper={upper_bound!r}."
        )

    try:
        metric_at_lower = _evaluate_detailed_candidate(
            terms,
            detailed_operating_inputs,
            assumption=assumption,
            metric=metric,
            candidate_value=lower_bound,
        )
    except InputValidationError as error:
        raise InvalidBreakEvenBoundsError(
            f"lower_search_bound {lower_bound!r} is not a valid {assumption!r} value: {error}"
        ) from error

    try:
        metric_at_upper = _evaluate_detailed_candidate(
            terms,
            detailed_operating_inputs,
            assumption=assumption,
            metric=metric,
            candidate_value=upper_bound,
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

    tolerance = _ASSUMPTION_TOLERANCES[assumption]

    if favorable_metric is None:
        favorable_value, favorable_metric = _resolve_undefined_favorable_endpoint_detailed(
            terms,
            detailed_operating_inputs,
            assumption=assumption,
            metric=metric,
            undefined_value=favorable_value,
            other_value=unfavorable_value,
            other_metric=unfavorable_metric,
            tolerance=tolerance,
            max_iterations=_MAX_ITERATIONS,
        )

    if not _meets_hurdle(favorable_metric, target):
        return None, None, BreakEvenStatus.NO_SOLUTION_IN_RANGE

    if _meets_hurdle(unfavorable_metric, target):
        return unfavorable_value, unfavorable_metric, BreakEvenStatus.SOLVED

    qualifying_value, qualifying_metric = favorable_value, favorable_metric
    failing_value = unfavorable_value

    for _ in range(_MAX_ITERATIONS):
        if abs(failing_value - qualifying_value) <= tolerance:
            break
        midpoint = (qualifying_value + failing_value) / 2
        midpoint_metric = _evaluate_detailed_candidate(
            terms,
            detailed_operating_inputs,
            assumption=assumption,
            metric=metric,
            candidate_value=midpoint,
        )
        if _meets_hurdle(midpoint_metric, target):
            qualifying_value, qualifying_metric = midpoint, midpoint_metric
        else:
            failing_value = midpoint

    return qualifying_value, qualifying_metric, BreakEvenStatus.SOLVED


def _build_detailed_break_even_result(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    break_even_type: BreakEvenType,
    assumption: str,
    metric: str,
    target: float,
    direction: BreakEvenDirection,
    lower_bound: float,
    upper_bound: float,
) -> BreakEvenResult:
    baseline_assumption_value = getattr(terms, assumption)
    baseline_metric_value = _extract_metric(
        analyze_detailed_acquisition_with_projection(
            terms, detailed_operating_inputs
        ).results,
        metric,
    )

    solved_assumption_value, solved_metric_value, status = solve_detailed_break_even_threshold(
        terms,
        detailed_operating_inputs,
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


def solve_detailed_max_purchase_price(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    target_levered_irr: float | None = None,
    target_equity_multiple: float | None = None,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> BreakEvenResult:
    """Detailed counterpart to ``solve_max_purchase_price`` -- default
    search bounds (50%-150% of the baseline purchase price) computed the
    same way, over ``terms.purchase_price``."""

    metric, target = _resolve_return_hurdle(
        target_levered_irr=target_levered_irr, target_equity_multiple=target_equity_multiple
    )
    default_lower, default_upper = terms.purchase_price * 0.5, terms.purchase_price * 1.5
    lo, hi = _resolve_bounds(lower_bound, upper_bound, (default_lower, default_upper))
    return _build_detailed_break_even_result(
        terms,
        detailed_operating_inputs,
        break_even_type=BreakEvenType.MAX_PURCHASE_PRICE,
        assumption="purchase_price",
        metric=metric,
        target=target,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=lo,
        upper_bound=hi,
    )


def solve_detailed_max_exit_cap_rate(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    target_levered_irr: float | None = None,
    target_equity_multiple: float | None = None,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> BreakEvenResult:
    """Detailed counterpart to ``solve_max_exit_cap_rate`` -- default
    search bounds (``max(0.005, baseline - 3pp)`` through ``baseline +
    5pp``) computed the same way, over ``terms.exit_cap_rate``."""

    metric, target = _resolve_return_hurdle(
        target_levered_irr=target_levered_irr, target_equity_multiple=target_equity_multiple
    )
    default_lower = max(0.005, terms.exit_cap_rate - 0.03)
    default_upper = terms.exit_cap_rate + 0.05
    lo, hi = _resolve_bounds(lower_bound, upper_bound, (default_lower, default_upper))
    return _build_detailed_break_even_result(
        terms,
        detailed_operating_inputs,
        break_even_type=BreakEvenType.MAX_EXIT_CAP_RATE,
        assumption="exit_cap_rate",
        metric=metric,
        target=target,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=lo,
        upper_bound=hi,
    )


def solve_detailed_max_interest_rate(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    target_headline_dscr: float,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> BreakEvenResult:
    """Detailed counterpart to ``solve_max_interest_rate`` -- default
    search bounds (``0.0`` through ``max(0.20, baseline + 10pp)``) computed
    the same way, over ``terms.interest_rate``."""

    _validate_target_headline_dscr(target_headline_dscr)
    default_lower, default_upper = 0.0, max(0.20, terms.interest_rate + 0.10)
    lo, hi = _resolve_bounds(lower_bound, upper_bound, (default_lower, default_upper))
    return _build_detailed_break_even_result(
        terms,
        detailed_operating_inputs,
        break_even_type=BreakEvenType.MAX_INTEREST_RATE,
        assumption="interest_rate",
        metric="headline_dscr",
        target=target_headline_dscr,
        direction=BreakEvenDirection.MAXIMUM,
        lower_bound=lo,
        upper_bound=hi,
    )


# =============================================================================
# Detailed Operating Model V2.1 Gate 9 (AI Analyst) -- standard Detailed
# break-even bundle, mirroring build_standard_break_even_analysis so the AI
# context can receive "the already-authoritative Detailed ... break-even
# outputs where the existing Quick AI path receives those analyses".
# Composes only the already-built, already-tested solve_detailed_max_*
# functions -- no new break-even target.
# =============================================================================


def build_standard_detailed_break_even_analysis(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    target_levered_irr: float,
    target_headline_dscr: float,
    target_equity_multiple: float | None = None,
    return_hurdle_metric: ReturnHurdleMetric = ReturnHurdleMetric.LEVERED_IRR,
) -> StandardDetailedBreakEvenAnalysis:
    """Run the three standard Detailed break-even questions for one base
    ``AcquisitionTerms``/``DetailedOperatingInputs`` pair, each using its
    documented default search range -- the Detailed counterpart of
    ``build_standard_break_even_analysis``. ``min_noi_growth``/
    ``min_current_noi`` have no Detailed equivalent (see
    ``StandardDetailedBreakEvenAnalysis``), so this bundle has three members
    instead of five."""

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

    return StandardDetailedBreakEvenAnalysis(
        max_purchase_price=solve_detailed_max_purchase_price(
            terms, detailed_operating_inputs, **return_hurdle_kwargs
        ),
        max_exit_cap_rate=solve_detailed_max_exit_cap_rate(
            terms, detailed_operating_inputs, **return_hurdle_kwargs
        ),
        max_interest_rate=solve_detailed_max_interest_rate(
            terms, detailed_operating_inputs, target_headline_dscr=target_headline_dscr
        ),
    )
