"""Phase 7 deterministic sensitivity analysis, built on top of the frozen
Phase 2 engine.

This module never reproduces a financial formula. Every scenario is
evaluated by constructing one validated ``AcquisitionInputs`` and calling the
existing authoritative ``analyze_acquisition`` exactly once; a sensitivity
result only reads a field off the returned ``AcquisitionResults``. Input
validation is never reimplemented here either -- every scenario is built
through ``validate_acquisition_inputs``, the same shared rules the base
engine and API already use, so an out-of-domain scenario value fails exactly
as it would on the base analysis, never silently clamped.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence

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
    OneWaySensitivityResult,
    StandardDetailedSensitivityPresets,
    StandardSensitivityPresets,
    TwoWaySensitivityResult,
)

# =============================================================================
# Supported assumptions and metrics
# =============================================================================

# Continuous assumptions only (Phase 7 POC scope). Occupancy is intentionally
# excluded -- it is informational only under the frozen POC convention
# (``engine/noi.py`` never reads it). Hold period and amortization are
# discrete structural assumptions, deferred to a later phase.
SUPPORTED_ASSUMPTIONS: tuple[str, ...] = (
    "purchase_price",
    "current_noi",
    "noi_growth",
    "exit_cap_rate",
    "ltv",
    "interest_rate",
)

# Detailed Operating Model V2.1 Gate 8: exactly the SUPPORTED_ASSUMPTIONS
# subset that exists on AcquisitionTerms -- current_noi and noi_growth have
# no Detailed counterpart (Gate 3/4's resolution: a Detailed deal has no
# AcquisitionInputs, so neither field exists to vary). Detailed-only
# dimensions (revenue_growth, vacancy_credit_loss_pct, expense_growth) are
# explicitly deferred -- not added here "merely to claim completeness."
DETAILED_SUPPORTED_ASSUMPTIONS: tuple[str, ...] = (
    "purchase_price",
    "exit_cap_rate",
    "ltv",
    "interest_rate",
)

_METRIC_EXTRACTORS: dict[str, Callable[[AcquisitionResults], float | None]] = {
    "levered_irr": lambda results: results.levered_irr,
    "unlevered_irr": lambda results: results.unlevered_irr,
    "equity_multiple": lambda results: results.equity_multiple,
    "headline_dscr": lambda results: results.headline_dscr,
    "exit_value": lambda results: results.exit_value,
}

SUPPORTED_METRICS: tuple[str, ...] = tuple(_METRIC_EXTRACTORS)


class UnknownAssumptionError(ValueError):
    """Raised for a sensitivity assumption identifier outside
    ``SUPPORTED_ASSUMPTIONS``."""

    def __init__(self, assumption: object) -> None:
        self.assumption = assumption
        super().__init__(
            f"Unknown sensitivity assumption: {assumption!r}. "
            f"Supported assumptions: {', '.join(SUPPORTED_ASSUMPTIONS)}."
        )


class UnknownMetricError(ValueError):
    """Raised for a sensitivity metric identifier outside
    ``SUPPORTED_METRICS``."""

    def __init__(self, metric: object) -> None:
        self.metric = metric
        super().__init__(
            f"Unknown sensitivity metric: {metric!r}. "
            f"Supported metrics: {', '.join(SUPPORTED_METRICS)}."
        )


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
    previously reset every scenario's V2 fields (acquisition_cost_pct,
    financing_fee_pct, disposition_cost_pct, annual_capex_reserve, io_period)
    to their neutral defaults, silently discarding a V2 base deal's actual
    assumptions in every sensitivity cell (Gate 9A root cause). Still routed
    through ``validate_acquisition_inputs`` -- domain validation is never
    reimplemented here, and out-of-domain scenario values still raise
    ``InputValidationError`` exactly as before.
    """

    candidate = dataclasses.replace(base, **changes)
    return validate_acquisition_inputs(dataclasses.asdict(candidate))


# =============================================================================
# One-way sensitivity
# =============================================================================


def run_one_way_sensitivity(
    inputs: AcquisitionInputs,
    *,
    assumption: str,
    values: Sequence[float],
    metric: str,
) -> OneWaySensitivityResult:
    """Vary one assumption across ``values``, calling ``analyze_acquisition``
    once per scenario, and return the requested ``metric`` for each."""

    if assumption not in SUPPORTED_ASSUMPTIONS:
        raise UnknownAssumptionError(assumption)
    if metric not in SUPPORTED_METRICS:
        raise UnknownMetricError(metric)

    baseline_assumption_value = getattr(inputs, assumption)
    baseline_metric_value = _extract_metric(analyze_acquisition(inputs), metric)

    assumption_values = tuple(values)
    metric_values: list[float | None] = []
    for value in assumption_values:
        scenario_inputs = _build_scenario_inputs(inputs, {assumption: value})
        scenario_results = analyze_acquisition(scenario_inputs)
        metric_values.append(_extract_metric(scenario_results, metric))

    return OneWaySensitivityResult(
        assumption=assumption,
        metric=metric,
        baseline_assumption_value=baseline_assumption_value,
        baseline_metric_value=baseline_metric_value,
        assumption_values=assumption_values,
        metric_values=tuple(metric_values),
    )


# =============================================================================
# Two-way sensitivity
# =============================================================================


def run_two_way_sensitivity(
    inputs: AcquisitionInputs,
    *,
    row_assumption: str,
    row_values: Sequence[float],
    column_assumption: str,
    column_values: Sequence[float],
    metric: str,
) -> TwoWaySensitivityResult:
    """Vary two assumptions independently over a grid, calling
    ``analyze_acquisition`` once per cell, and return the requested
    ``metric`` for each cell."""

    if row_assumption not in SUPPORTED_ASSUMPTIONS:
        raise UnknownAssumptionError(row_assumption)
    if column_assumption not in SUPPORTED_ASSUMPTIONS:
        raise UnknownAssumptionError(column_assumption)
    if metric not in SUPPORTED_METRICS:
        raise UnknownMetricError(metric)
    if row_assumption == column_assumption:
        raise ValueError(
            "row_assumption and column_assumption must differ; got "
            f"{row_assumption!r} for both."
        )

    baseline_row_value = getattr(inputs, row_assumption)
    baseline_column_value = getattr(inputs, column_assumption)
    baseline_metric_value = _extract_metric(analyze_acquisition(inputs), metric)

    row_values_tuple = tuple(row_values)
    column_values_tuple = tuple(column_values)

    matrix: list[tuple[float | None, ...]] = []
    for row_value in row_values_tuple:
        row_cells: list[float | None] = []
        for column_value in column_values_tuple:
            scenario_inputs = _build_scenario_inputs(
                inputs, {row_assumption: row_value, column_assumption: column_value}
            )
            scenario_results = analyze_acquisition(scenario_inputs)
            row_cells.append(_extract_metric(scenario_results, metric))
        matrix.append(tuple(row_cells))

    return TwoWaySensitivityResult(
        row_assumption=row_assumption,
        column_assumption=column_assumption,
        metric=metric,
        baseline_row_value=baseline_row_value,
        baseline_column_value=baseline_column_value,
        baseline_metric_value=baseline_metric_value,
        row_values=row_values_tuple,
        column_values=column_values_tuple,
        matrix=tuple(matrix),
    )


# =============================================================================
# Standard POC presets
# =============================================================================

# Basis-point offsets (1 bp = 0.0001 = 0.01 percentage points).
_EXIT_CAP_BPS_OFFSETS: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01)
_INTEREST_RATE_BPS_OFFSETS: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01)

# Percentage-point offsets (1 pp = 0.01).
_NOI_GROWTH_PP_OFFSETS: tuple[float, ...] = (-0.02, -0.01, 0.0, 0.01, 0.02)
_LTV_PP_OFFSETS: tuple[float, ...] = (-0.10, -0.05, 0.0, 0.05, 0.10)

# Multipliers of the baseline purchase price.
_PURCHASE_PRICE_MULTIPLIERS: tuple[float, ...] = (0.90, 0.95, 1.00, 1.05, 1.10)


def _valid_scenario_values(
    inputs: AcquisitionInputs, assumption: str, candidates: Iterable[float]
) -> tuple[float, ...]:
    """Return only the ``candidates`` that satisfy the frozen input domain
    for ``assumption``, in the given order.

    Presets never clamp an out-of-domain candidate into range and never
    raise for it either -- it is simply omitted. This can make a preset
    matrix narrower than 5x5 near a domain boundary (for example, a Interest
    Rate x LTV preset near a baseline interest rate under 100 bps). Domain
    validity is checked field-by-field via the same shared
    ``validate_acquisition_inputs`` used everywhere else, never a duplicated
    check, and because each field's domain is independent of every other
    field's value, checking one changed field at a time here is equivalent to
    checking it as part of a full combined scenario.
    """

    valid_values = []
    for candidate in candidates:
        try:
            _build_scenario_inputs(inputs, {assumption: candidate})
        except InputValidationError:
            continue
        valid_values.append(candidate)
    return tuple(valid_values)


def build_exit_cap_noi_growth_preset(
    inputs: AcquisitionInputs,
) -> TwoWaySensitivityResult:
    """NOI Growth (rows) x Exit Cap Rate (columns), Levered IRR."""

    noi_growth_values = _valid_scenario_values(
        inputs,
        "noi_growth",
        (inputs.noi_growth + offset for offset in _NOI_GROWTH_PP_OFFSETS),
    )
    exit_cap_values = _valid_scenario_values(
        inputs,
        "exit_cap_rate",
        (inputs.exit_cap_rate + offset for offset in _EXIT_CAP_BPS_OFFSETS),
    )
    return run_two_way_sensitivity(
        inputs,
        row_assumption="noi_growth",
        row_values=noi_growth_values,
        column_assumption="exit_cap_rate",
        column_values=exit_cap_values,
        metric="levered_irr",
    )


def build_purchase_price_exit_cap_preset(
    inputs: AcquisitionInputs,
) -> TwoWaySensitivityResult:
    """Purchase Price (rows) x Exit Cap Rate (columns), Levered IRR."""

    purchase_price_values = _valid_scenario_values(
        inputs,
        "purchase_price",
        (
            inputs.purchase_price * multiplier
            for multiplier in _PURCHASE_PRICE_MULTIPLIERS
        ),
    )
    exit_cap_values = _valid_scenario_values(
        inputs,
        "exit_cap_rate",
        (inputs.exit_cap_rate + offset for offset in _EXIT_CAP_BPS_OFFSETS),
    )
    return run_two_way_sensitivity(
        inputs,
        row_assumption="purchase_price",
        row_values=purchase_price_values,
        column_assumption="exit_cap_rate",
        column_values=exit_cap_values,
        metric="levered_irr",
    )


def build_interest_rate_ltv_preset(
    inputs: AcquisitionInputs, *, metric: str = "levered_irr"
) -> TwoWaySensitivityResult:
    """Interest Rate (rows) x LTV (columns), for ``metric`` (default Levered
    IRR; ``headline_dscr`` is also supported, reusing this same grid)."""

    interest_rate_values = _valid_scenario_values(
        inputs,
        "interest_rate",
        (inputs.interest_rate + offset for offset in _INTEREST_RATE_BPS_OFFSETS),
    )
    ltv_values = _valid_scenario_values(
        inputs, "ltv", (inputs.ltv + offset for offset in _LTV_PP_OFFSETS)
    )
    return run_two_way_sensitivity(
        inputs,
        row_assumption="interest_rate",
        row_values=interest_rate_values,
        column_assumption="ltv",
        column_values=ltv_values,
        metric=metric,
    )


def build_standard_presets(inputs: AcquisitionInputs) -> StandardSensitivityPresets:
    """Return all three standard POC sensitivity matrices, plus the optional
    DSCR variant of the Interest Rate x LTV matrix."""

    return StandardSensitivityPresets(
        exit_cap_noi_growth=build_exit_cap_noi_growth_preset(inputs),
        purchase_price_exit_cap=build_purchase_price_exit_cap_preset(inputs),
        interest_rate_ltv=build_interest_rate_ltv_preset(inputs, metric="levered_irr"),
        interest_rate_ltv_dscr=build_interest_rate_ltv_preset(
            inputs, metric="headline_dscr"
        ),
    )


# =============================================================================
# Detailed Operating Model V2.1 Gate 8 -- Detailed sensitivity
#
# For a Detailed base deal, every scenario preserves detailed_operating_inputs
# completely unchanged -- only the varied AcquisitionTerms field(s) differ
# between the baseline and each scenario cell. This is the direct Detailed
# counterpart of the Gate 9A fix: dataclasses.replace on the complete
# AcquisitionTerms contract, never a hand-maintained field-list
# reconstruction that could silently drop a field.
# =============================================================================


def _build_detailed_scenario_terms(
    base: AcquisitionTerms, changes: Mapping[str, float]
) -> AcquisitionTerms:
    """Detailed counterpart to ``_build_scenario_inputs``: immutable
    replacement of the complete ``AcquisitionTerms`` contract. ``base`` is
    never mutated -- it is frozen. Still routed through
    ``validate_acquisition_terms`` -- domain validation is never
    reimplemented here."""

    candidate = dataclasses.replace(base, **changes)
    return validate_acquisition_terms(dataclasses.asdict(candidate))


def _analyze_detailed_scenario(
    terms: AcquisitionTerms, detailed_operating_inputs: DetailedOperatingInputs
) -> AcquisitionResults:
    return analyze_detailed_acquisition_with_projection(
        terms, detailed_operating_inputs
    ).results


def run_detailed_one_way_sensitivity(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    assumption: str,
    values: Sequence[float],
    metric: str,
) -> OneWaySensitivityResult:
    """Detailed counterpart to ``run_one_way_sensitivity``: vary one
    ``AcquisitionTerms`` assumption across ``values``, calling
    ``analyze_detailed_acquisition_with_projection`` once per scenario --
    ``detailed_operating_inputs`` is passed through unchanged to every
    scenario, never varied and never dropped."""

    if assumption not in DETAILED_SUPPORTED_ASSUMPTIONS:
        raise UnknownAssumptionError(assumption)
    if metric not in SUPPORTED_METRICS:
        raise UnknownMetricError(metric)

    baseline_assumption_value = getattr(terms, assumption)
    baseline_metric_value = _extract_metric(
        _analyze_detailed_scenario(terms, detailed_operating_inputs), metric
    )

    assumption_values = tuple(values)
    metric_values: list[float | None] = []
    for value in assumption_values:
        scenario_terms = _build_detailed_scenario_terms(terms, {assumption: value})
        scenario_results = _analyze_detailed_scenario(
            scenario_terms, detailed_operating_inputs
        )
        metric_values.append(_extract_metric(scenario_results, metric))

    return OneWaySensitivityResult(
        assumption=assumption,
        metric=metric,
        baseline_assumption_value=baseline_assumption_value,
        baseline_metric_value=baseline_metric_value,
        assumption_values=assumption_values,
        metric_values=tuple(metric_values),
    )


def run_detailed_two_way_sensitivity(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    row_assumption: str,
    row_values: Sequence[float],
    column_assumption: str,
    column_values: Sequence[float],
    metric: str,
) -> TwoWaySensitivityResult:
    """Detailed counterpart to ``run_two_way_sensitivity``: vary two
    ``AcquisitionTerms`` assumptions independently over a grid, calling
    ``analyze_detailed_acquisition_with_projection`` once per cell --
    ``detailed_operating_inputs`` is passed through unchanged to every
    cell."""

    if row_assumption not in DETAILED_SUPPORTED_ASSUMPTIONS:
        raise UnknownAssumptionError(row_assumption)
    if column_assumption not in DETAILED_SUPPORTED_ASSUMPTIONS:
        raise UnknownAssumptionError(column_assumption)
    if metric not in SUPPORTED_METRICS:
        raise UnknownMetricError(metric)
    if row_assumption == column_assumption:
        raise ValueError(
            "row_assumption and column_assumption must differ; got "
            f"{row_assumption!r} for both."
        )

    baseline_row_value = getattr(terms, row_assumption)
    baseline_column_value = getattr(terms, column_assumption)
    baseline_metric_value = _extract_metric(
        _analyze_detailed_scenario(terms, detailed_operating_inputs), metric
    )

    row_values_tuple = tuple(row_values)
    column_values_tuple = tuple(column_values)

    matrix: list[tuple[float | None, ...]] = []
    for row_value in row_values_tuple:
        row_cells: list[float | None] = []
        for column_value in column_values_tuple:
            scenario_terms = _build_detailed_scenario_terms(
                terms, {row_assumption: row_value, column_assumption: column_value}
            )
            scenario_results = _analyze_detailed_scenario(
                scenario_terms, detailed_operating_inputs
            )
            row_cells.append(_extract_metric(scenario_results, metric))
        matrix.append(tuple(row_cells))

    return TwoWaySensitivityResult(
        row_assumption=row_assumption,
        column_assumption=column_assumption,
        metric=metric,
        baseline_row_value=baseline_row_value,
        baseline_column_value=baseline_column_value,
        baseline_metric_value=baseline_metric_value,
        row_values=row_values_tuple,
        column_values=column_values_tuple,
        matrix=tuple(matrix),
    )


# =============================================================================
# Detailed Operating Model V2.1 Gate 9 (AI Analyst) -- standard Detailed
# preset bundle, mirroring build_standard_presets so the AI context can
# receive "the already-authoritative Detailed sensitivity ... outputs where
# the existing Quick AI path receives those analyses" without the AI layer
# (or this module) inventing a new dimension. Composes only the already-
# built, already-tested run_detailed_two_way_sensitivity -- no new scenario
# logic.
# =============================================================================


def _valid_detailed_scenario_values(
    terms: AcquisitionTerms, assumption: str, candidates: Iterable[float]
) -> tuple[float, ...]:
    """Detailed counterpart to ``_valid_scenario_values``: only the
    ``candidates`` that satisfy the shared ``AcquisitionTerms`` domain for
    ``assumption``, in the given order. Never clamps or raises for an
    out-of-domain candidate -- it is simply omitted."""

    valid_values = []
    for candidate in candidates:
        try:
            _build_detailed_scenario_terms(terms, {assumption: candidate})
        except InputValidationError:
            continue
        valid_values.append(candidate)
    return tuple(valid_values)


def build_detailed_purchase_price_exit_cap_preset(
    terms: AcquisitionTerms, detailed_operating_inputs: DetailedOperatingInputs
) -> TwoWaySensitivityResult:
    """Purchase Price (rows) x Exit Cap Rate (columns), Levered IRR --
    Detailed counterpart of ``build_purchase_price_exit_cap_preset``."""

    purchase_price_values = _valid_detailed_scenario_values(
        terms,
        "purchase_price",
        (terms.purchase_price * multiplier for multiplier in _PURCHASE_PRICE_MULTIPLIERS),
    )
    exit_cap_values = _valid_detailed_scenario_values(
        terms, "exit_cap_rate", (terms.exit_cap_rate + offset for offset in _EXIT_CAP_BPS_OFFSETS)
    )
    return run_detailed_two_way_sensitivity(
        terms,
        detailed_operating_inputs,
        row_assumption="purchase_price",
        row_values=purchase_price_values,
        column_assumption="exit_cap_rate",
        column_values=exit_cap_values,
        metric="levered_irr",
    )


def build_detailed_interest_rate_ltv_preset(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    metric: str = "levered_irr",
) -> TwoWaySensitivityResult:
    """Interest Rate (rows) x LTV (columns), for ``metric`` -- Detailed
    counterpart of ``build_interest_rate_ltv_preset``."""

    interest_rate_values = _valid_detailed_scenario_values(
        terms,
        "interest_rate",
        (terms.interest_rate + offset for offset in _INTEREST_RATE_BPS_OFFSETS),
    )
    ltv_values = _valid_detailed_scenario_values(
        terms, "ltv", (terms.ltv + offset for offset in _LTV_PP_OFFSETS)
    )
    return run_detailed_two_way_sensitivity(
        terms,
        detailed_operating_inputs,
        row_assumption="interest_rate",
        row_values=interest_rate_values,
        column_assumption="ltv",
        column_values=ltv_values,
        metric=metric,
    )


def build_standard_detailed_presets(
    terms: AcquisitionTerms, detailed_operating_inputs: DetailedOperatingInputs
) -> StandardDetailedSensitivityPresets:
    """Return the standard Detailed sensitivity bundle: Purchase Price x
    Exit Cap Rate, Interest Rate x LTV, and its DSCR variant -- exactly the
    ``StandardSensitivityPresets`` members that exist for
    ``DETAILED_SUPPORTED_ASSUMPTIONS`` (no ``exit_cap_noi_growth`` member;
    see ``StandardDetailedSensitivityPresets``)."""

    return StandardDetailedSensitivityPresets(
        purchase_price_exit_cap=build_detailed_purchase_price_exit_cap_preset(
            terms, detailed_operating_inputs
        ),
        interest_rate_ltv=build_detailed_interest_rate_ltv_preset(
            terms, detailed_operating_inputs, metric="levered_irr"
        ),
        interest_rate_ltv_dscr=build_detailed_interest_rate_ltv_preset(
            terms, detailed_operating_inputs, metric="headline_dscr"
        ),
    )
