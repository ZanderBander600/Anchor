"""Sprint D Gate D4.6B -- Lease-Level deterministic sensitivity.

Restates
``docs/plans/2026-09-07-anchor-lease-level-underwriting-d4-6-sensitivity-architecture.md``
(Sections 15-18, 25-29 and the Section 38 human-review closeout amendment)
exactly; that document governs on any discrepancy, and its Section 38 governs
over its own Parts I-IV.

**The third parallel pair.** ``sensitivity.py`` holds the Quick pair and the
Detailed pair. This module holds the Lease-Level pair, and it is a separate
module for one concrete reason (Section 15.1): D4.5B established that only a
named handful of files may import ``anchor.leasing``, and putting these runners
into ``sensitivity.py`` would give ``anchor.analysis.sensitivity`` -- imported
by ``api.py`` on every Quick and Detailed request -- a transitive dependency on
the whole leasing package. ``sensitivity.py`` and ``break_even.py`` are
therefore not edited at all; the Lease-Level mode is distinguished by
**function identity**, exactly as Quick and Detailed already are, and no
``OperatingMode`` member is added (Section 38.10).

**No sensitivity-specific financial model exists here, and none may.** A
scenario is an immutable replacement of exactly one approved assumption on the
one contract that owns it, followed by a complete call to
``analyze_lease_level_acquisition_with_projection``. The entire D1-D4.5A chain
reruns for every cell -- canonical months, suite leasing chains, rollover,
initial vacancy, property expenses, the one recoverable pool, recoveries,
property aggregation, monthly EGI/NOI, the annual projection, the forward exit
NOI, the ``OperatingCapitalSchedule`` and the shared acquisition engine. This
module then reads **one already-computed scalar** off the returned
``AcquisitionResults`` and discards the rest. It calculates no NOI, no
recovery, no rent, no exit value, no IRR, no DSCR and no cash flow, and it
never calls a leasing builder or an engine function directly.

**Values are absolute** (Section 38.7). ``exit_cap_rate=0.065``,
``market_rent_psf=45.0``, ``renewal_probability=0.70`` are the assumption
values themselves, never ``+50 bps``, ``+5%`` or ``-10%``.

**Domain validation is never restated here** (Section 25.4). A scenario is
built by ``dataclasses.replace`` and handed to the normal pipeline, so
``renewal_probability`` keeps its ``0 <= p <= 1`` contract domain with no
clipping, ``p = 0`` and ``p = 1`` reach D2 as the exact branch endpoints they
are, and an out-of-domain candidate fails exactly as it would on a direct
analysis. ``AcquisitionTerms`` additionally routes through the shared
``validate_acquisition_terms``, the same three lines
``_build_detailed_scenario_terms`` already uses, because the Lease-Level entry
point validates the leasing contracts but not the terms.

**``None`` and invalid are different** (Section 38.4.1). ``None`` in a result
cell means the scenario was valid and fully underwritten but the requested
metric is mathematically undefined -- a levered IRR does not exist for the
multiple-sign-change cash flow a rollover year's TI/LC routinely produces. A
scenario that cannot be underwritten at all raises, and one invalid explicit
scenario fails the whole run. A validation failure is never encoded as
``None``, ``0``, ``NaN`` or a sentinel, and ``NON_POSITIVE_FORWARD_EXIT_NOI``
is never caught, floored, capitalised or skipped.

No caching, no memoization, no parallelism, no grid-size limit, and no
per-cell retention of a ``LeaseLevelAcquisitionResults`` (Sections 38.7-38.8).

**Phase 6 Gate D6.4 -- the Business Plan is held fixed.** Both runners take a
keyword-only ``business_plan``, resolved once per run for the base hold period
(none of the eight targets is the hold period). The one resulting
``OwnerCapitalSchedule`` is handed to the bridge for the baseline and every
cell, beside -- never merged into -- the rent roll's own TI and LC. The
default, ``BusinessPlan()``, is the empty plan for callers that supply none.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..business_plan import BusinessPlan, resolve_business_plan
from ..contracts import AcquisitionTerms
from ..engine.contracts import OwnerCapitalSchedule
from ..leasing import (
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    MarketLeasingAssumptions,
    Suite,
)
from ..validation import validate_acquisition_terms
from .contracts import OneWaySensitivityResult, TwoWaySensitivityResult
from .lease_level import analyze_lease_level_acquisition_with_projection
from .sensitivity import (
    SUPPORTED_METRICS,
    UnknownAssumptionError,
    UnknownMetricError,
    _extract_metric,
)

# =============================================================================
# Supported targets -- one authoritative collection, one ownership mapping
# =============================================================================


class _TargetOwner(StrEnum):
    """Which of the three perturbable input contracts owns a target.

    Private by design (Section 17.2): the *public* target stays a plain ``str``
    from a frozen tuple, so ``OneWaySensitivityResult.assumption`` needs no
    contract change and every existing consumer keeps working. The owner is an
    implementation detail of the replacement seam.
    """

    TERMS = "terms"
    MARKET = "market_leasing"
    OPERATING = "operating_inputs"


@dataclass(frozen=True, slots=True, kw_only=True)
class _TargetSpec:
    """Everything the runners need to know about one approved target.

    Three facts, held together so they cannot drift apart:

    ``owner``
        which contract ``dataclasses.replace`` is applied to.
    ``read_baseline``
        reads the target's baseline value off the contract that owns it, by
        **literal attribute name**. No ``getattr`` with a computed name, no
        dotted path, no field-name traversal -- an unapproved field is
        unreachable because no accessor for it exists.
    ``shadowed_by``
        the target-specific suite-override predicate (Section 38.2.2), or
        ``None`` for a target no suite can shadow. Holding the predicate *per
        target* is what encodes the measured asymmetry structurally rather
        than as an ``if target == ...`` scattered through the runners.
    """

    owner: _TargetOwner
    read_baseline: Callable[
        [AcquisitionTerms, MarketLeasingAssumptions, LeaseLevelOperatingInputs],
        float,
    ]
    shadowed_by: Callable[[Suite], bool] | None


#: The one production mapping from an approved target name to the contract that
#: owns it. Every supported target appears here exactly once, and nothing else
#: is reachable -- there is no arbitrary field path, no ``setattr``, no
#: ``eval`` and no suite- or lease-level target anywhere in this module.
#:
#: **The four shared acquisition targets are exactly
#: ``sensitivity.DETAILED_SUPPORTED_ASSUMPTIONS``** -- Lease-Level inherits the
#: Detailed shared-terms set with no additions and no subtractions
#: (Section 38.1). A guardrail asserts that equality against the shipped tuple
#: so the two cannot drift.
#:
#: **The four Lease-Level additive targets** are the approved minimum set: the
#: two highest-value market-leasing questions, and the two property operating
#: assumptions that drive the deepest rebuild chain. Everything else --
#: ``market_rent_growth``, the renewal/new downtime, free-rent, TI, LC, term
#: and spread pairs, ``successor_escalation_pct``, the five individual expense
#: lines, ``other_income``/``other_income_growth``, ``credit_loss_pct``,
#: ``management_fee_pct``, ``annual_capex_reserve``, the acquisition/financing/
#: disposition cost percentages, ``hold_period``, ``amortization``,
#: ``io_period``, every date, every categorical lease structure, the
#: initial-vacancy strategy and every suite-specific assumption -- is
#: explicitly deferred (Section 38.1) and raises here.
_TARGETS: dict[str, _TargetSpec] = {
    # --- shared acquisition terms (= DETAILED_SUPPORTED_ASSUMPTIONS) --------
    "purchase_price": _TargetSpec(
        owner=_TargetOwner.TERMS,
        read_baseline=lambda terms, market, operating: terms.purchase_price,
        shadowed_by=None,
    ),
    "exit_cap_rate": _TargetSpec(
        owner=_TargetOwner.TERMS,
        read_baseline=lambda terms, market, operating: terms.exit_cap_rate,
        shadowed_by=None,
    ),
    "ltv": _TargetSpec(
        owner=_TargetOwner.TERMS,
        read_baseline=lambda terms, market, operating: terms.ltv,
        shadowed_by=None,
    ),
    "interest_rate": _TargetSpec(
        owner=_TargetOwner.TERMS,
        read_baseline=lambda terms, market, operating: terms.interest_rate,
        shadowed_by=None,
    ),
    # --- property-default market leasing -----------------------------------
    # Section 38.2.2, measured at ``leasing/market.py::resolve_market_leasing``:
    # a full ``market_leasing_override`` is all-or-nothing and shadows every
    # field, while ``Suite.market_rent_psf`` is a genuine single-field override
    # and shadows the rent level alone. The two predicates therefore differ,
    # and that asymmetry is load-bearing.
    "market_rent_psf": _TargetSpec(
        owner=_TargetOwner.MARKET,
        read_baseline=lambda terms, market, operating: market.market_rent_psf,
        shadowed_by=lambda suite: (
            suite.market_leasing_override is not None
            or suite.market_rent_psf is not None
        ),
    ),
    "renewal_probability": _TargetSpec(
        owner=_TargetOwner.MARKET,
        read_baseline=lambda terms, market, operating: market.renewal_probability,
        shadowed_by=lambda suite: suite.market_leasing_override is not None,
    ),
    # --- property operating assumptions ------------------------------------
    # ``LeaseLevelOperatingInputs`` shares no field name with ``Suite`` and is
    # unreachable from any suite override, so these two are never shadowed and
    # carry no predicate at all (Section 38.2.2).
    "expense_growth": _TargetSpec(
        owner=_TargetOwner.OPERATING,
        read_baseline=lambda terms, market, operating: operating.expense_growth,
        shadowed_by=None,
    ),
    "recoverable_expense_ratio": _TargetSpec(
        owner=_TargetOwner.OPERATING,
        read_baseline=(
            lambda terms, market, operating: operating.recoverable_expense_ratio
        ),
        shadowed_by=None,
    ),
}

#: The approved D4.6B target set: exactly eight names, in a frozen tuple, in
#: declaration order. Derived from ``_TARGETS`` rather than restated beside it,
#: so a name can never be supported by one and not the other. Dict insertion
#: order is deterministic, so this tuple is too.
LEASE_LEVEL_SUPPORTED_ASSUMPTIONS: tuple[str, ...] = tuple(_TARGETS)

#: The metric surface is the shipped one, reused whole: the same five metrics
#: Quick and Detailed sensitivity expose, extracted by the same shipped
#: selector. No Lease-Level metric name exists, and no metric is recomputed
#: here -- ``_extract_metric`` reads one already-computed field off the
#: ``AcquisitionResults`` the authoritative pipeline produced.
LEASE_LEVEL_SUPPORTED_METRICS: tuple[str, ...] = SUPPORTED_METRICS


# =============================================================================
# Analysis-layer sensitivity validation
# =============================================================================

#: The analysis-layer validation concept named by Section 38.2.3.
#:
#: **This is not a ``LeaseIssueCode``, and it must never become one.** Nothing
#: about the rent roll is invalid: the identical inputs remain perfectly
#: analysable through ``analyze_lease_level_acquisition_with_projection``. What
#: is refused is *this sensitivity question about these inputs* -- perturbing
#: the property default would not reach the intended property economics,
#: because a suite override stands in front of it. The current result contracts
#: have no field in which "this cell moved 2 of your 4 suites" could be stated
#: (Section 38.2.1), so the honest answer is a refusal rather than a table that
#: reads as property-wide and is not.
SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE = (
    "SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE"
)


class UnknownLeaseLevelAssumptionError(UnknownAssumptionError):
    """Raised for a target outside ``LEASE_LEVEL_SUPPORTED_ASSUMPTIONS``.

    A subclass rather than a verbatim reuse of ``UnknownAssumptionError``: the
    base class's message names ``SUPPORTED_ASSUMPTIONS``, the *Quick* set,
    which differs from the Lease-Level set in half its members and would
    misdirect a caller. Callers catching ``UnknownAssumptionError`` -- the
    framework's convention for this failure -- still catch this unchanged, and
    ``sensitivity.py`` is not touched.
    """

    def __init__(self, assumption: object) -> None:
        self.assumption = assumption
        ValueError.__init__(
            self,
            f"Unknown Lease-Level sensitivity assumption: {assumption!r}. "
            "Supported Lease-Level assumptions: "
            f"{', '.join(LEASE_LEVEL_SUPPORTED_ASSUMPTIONS)}.",
        )


class SensitivityTargetShadowedBySuiteOverrideError(ValueError):
    """Raised when a suite override shadows the requested property-default
    market-leasing target (Section 38.2).

    The run is refused **before any scenario is evaluated**, so no misleading
    table is ever assembled. The alternatives were all rejected for D4: the
    override is not overwritten, not removed, not proportionally shocked, and
    the sensitivity is not run partially over the un-overridden suites.
    """

    code = SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE

    def __init__(self, assumption: str, suite_ids: Sequence[str]) -> None:
        self.assumption = assumption
        self.suite_ids = tuple(suite_ids)
        super().__init__(
            f"{self.code}: the property-default sensitivity target "
            f"{assumption!r} is shadowed by a suite-specific override on "
            f"suite(s) {', '.join(self.suite_ids)}. Perturbing the property "
            "default would not reach those suites, so the resulting table "
            "would not describe the property economics it appears to "
            "describe. The rent roll itself is valid and remains analysable; "
            "only this sensitivity question is refused."
        )


def _require_supported_assumption(assumption: str) -> None:
    if assumption not in _TARGETS:
        raise UnknownLeaseLevelAssumptionError(assumption)


def _require_supported_metric(metric: str) -> None:
    if metric not in LEASE_LEVEL_SUPPORTED_METRICS:
        raise UnknownMetricError(metric)


def _require_unshadowed_target(assumption: str, suites: tuple[Suite, ...]) -> None:
    """Refuse the run if **any** suite shadows ``assumption``.

    The predicate is the target's own (Section 38.2.2), so ``expense_growth``
    and ``recoverable_expense_ratio`` -- which no suite override can reach --
    are never refused, on any suite shape, and ``renewal_probability`` is
    refused only by a full ``market_leasing_override``, not by a suite
    carrying only the scalar ``market_rent_psf``.
    """

    shadowed_by = _TARGETS[assumption].shadowed_by
    if shadowed_by is None:
        return
    shadowing = tuple(suite.suite_id for suite in suites if shadowed_by(suite))
    if shadowing:
        raise SensitivityTargetShadowedBySuiteOverrideError(assumption, shadowing)


# =============================================================================
# The one deterministic replacement seam
# =============================================================================


def _scenario_contracts(
    *,
    terms: AcquisitionTerms,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    changes: Mapping[str, float],
) -> tuple[AcquisitionTerms, MarketLeasingAssumptions, LeaseLevelOperatingInputs]:
    """Return the three perturbable contracts with ``changes`` applied to the
    ones that own them.

    Every scenario in this module is built here, from the caller's original
    frozen baseline objects, by ``dataclasses.replace`` -- the repository's
    immutable replacement convention. A contract no change targets is passed
    through **as the caller's own object**, so an unperturbed input reaches the
    analysis bit-identically. Nothing is mutated: every input contract is
    ``frozen=True, slots=True, kw_only=True`` and ``replace`` returns a new
    object.

    ``replace`` also carries every unnamed field forward automatically, which
    is the Gate 9A lesson restated: a hand-maintained field list here would
    silently reset the fields it forgot in every cell.

    ``AcquisitionTerms`` is additionally routed through the shared
    ``validate_acquisition_terms`` -- the same three lines
    ``_build_detailed_scenario_terms`` uses -- because the Lease-Level entry
    point validates the leasing contracts but not the terms. The two leasing
    contracts are deliberately **not** pre-validated: the pipeline validates
    them itself, at ``require_valid_lease_level_inputs`` and
    ``build_property_expense_schedule``, and restating a domain rule here would
    be exactly the duplication this layer exists to avoid.
    """

    grouped: dict[_TargetOwner, dict[str, float]] = {
        _TargetOwner.TERMS: {},
        _TargetOwner.MARKET: {},
        _TargetOwner.OPERATING: {},
    }
    for assumption, value in changes.items():
        grouped[_TARGETS[assumption].owner][assumption] = value

    scenario_terms = terms
    if grouped[_TargetOwner.TERMS]:
        scenario_terms = validate_acquisition_terms(
            dataclasses.asdict(
                dataclasses.replace(terms, **grouped[_TargetOwner.TERMS])
            )
        )

    scenario_market = market_leasing
    if grouped[_TargetOwner.MARKET]:
        scenario_market = dataclasses.replace(
            market_leasing, **grouped[_TargetOwner.MARKET]
        )

    scenario_operating = operating_inputs
    if grouped[_TargetOwner.OPERATING]:
        scenario_operating = dataclasses.replace(
            operating_inputs, **grouped[_TargetOwner.OPERATING]
        )

    return scenario_terms, scenario_market, scenario_operating


def _scenario_metric(
    *,
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: tuple[Suite, ...],
    leases: tuple[Lease, ...],
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    owner_capital: OwnerCapitalSchedule,
    changes: Mapping[str, float],
    metric: str,
) -> float | None:
    """Run **one complete Lease-Level analysis** for ``changes`` and return the
    one requested metric.

    An empty ``changes`` is the baseline call: the caller's own contracts reach
    the entry point untouched.

    ``owner_capital`` is the resolved Business Plan the run holds fixed (D6.4).
    It is required, and the bridge receives it unchanged for every cell.

    The completed ``LeaseLevelAcquisitionResults`` -- with its
    ``MonthlyPropertyProjection``, its ``AnnualOperatingProjection`` and the
    whole suite-chain audit tree -- exists only for the duration of this call
    and is then reduced to a single scalar (Section 38.8). That is a memory
    boundary, **not** a financial shortcut: the full re-underwrite happened.

    Nothing is caught here. A scenario that cannot be underwritten --
    ``renewal_probability`` outside ``[0, 1]``, an out-of-domain exit cap or
    LTV, ``NON_POSITIVE_FORWARD_EXIT_NOI`` -- raises out of this function and
    fails the whole run, and is never converted into ``None``, ``0`` or a
    sentinel.
    """

    scenario_terms, scenario_market, scenario_operating = _scenario_contracts(
        terms=terms,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        changes=changes,
    )
    return _extract_metric(
        analyze_lease_level_acquisition_with_projection(
            scenario_terms,
            property_inputs,
            suites,
            leases,
            market_leasing=scenario_market,
            operating_inputs=scenario_operating,
            owner_capital=owner_capital,
        ).results,
        metric,
    )


# =============================================================================
# One-way sensitivity
# =============================================================================


def run_lease_level_one_way_sensitivity(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    assumption: str,
    values: Sequence[float],
    metric: str,
    business_plan: BusinessPlan = BusinessPlan(),
) -> OneWaySensitivityResult:
    """Vary one approved Lease-Level assumption across ``values``, calling
    ``analyze_lease_level_acquisition_with_projection`` once per scenario, and
    return the requested ``metric`` for each.

    ``values`` are **absolute** assumption values, evaluated in the caller's
    order, which the result preserves positionally: ``metric_values[i]``
    corresponds to ``assumption_values[i]``. Nothing is sorted, deduplicated or
    filtered, and a repeated candidate is evaluated again rather than reused.

    Every scenario starts from the same immutable baseline; no scenario is
    built from its predecessor. Exactly ``1 + len(values)`` analyses run -- one
    baseline call, per the framework's existing baseline semantics, plus one
    per candidate.

    Validation order is deterministic and structural first: an unsupported
    target, then an unsupported metric, then a suite-shadowed target -- all
    before the baseline analysis, so a structurally unanswerable question never
    costs a single re-underwrite, and never returns a misleading table.

    ``business_plan`` is resolved once, after those structural checks and
    before the baseline, for ``terms.hold_period``; the baseline and every
    scenario carry that one schedule (D6.4).
    """

    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)

    _require_supported_assumption(assumption)
    _require_supported_metric(metric)
    _require_unshadowed_target(assumption, suite_tuple)

    owner_capital = resolve_business_plan(business_plan, hold_period=terms.hold_period)

    baseline_assumption_value = _TARGETS[assumption].read_baseline(
        terms, market_leasing, operating_inputs
    )
    baseline_metric_value = _scenario_metric(
        terms=terms,
        property_inputs=property_inputs,
        suites=suite_tuple,
        leases=lease_tuple,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        owner_capital=owner_capital,
        changes={},
        metric=metric,
    )

    assumption_values = tuple(values)
    metric_values: list[float | None] = []
    for value in assumption_values:
        metric_values.append(
            _scenario_metric(
                terms=terms,
                property_inputs=property_inputs,
                suites=suite_tuple,
                leases=lease_tuple,
                market_leasing=market_leasing,
                operating_inputs=operating_inputs,
                owner_capital=owner_capital,
                changes={assumption: value},
                metric=metric,
            )
        )

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


def run_lease_level_two_way_sensitivity(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    row_assumption: str,
    row_values: Sequence[float],
    column_assumption: str,
    column_values: Sequence[float],
    metric: str,
    business_plan: BusinessPlan = BusinessPlan(),
) -> TwoWaySensitivityResult:
    """Vary two approved Lease-Level assumptions independently over a grid,
    calling ``analyze_lease_level_acquisition_with_projection`` once per cell.

    **Every cell is built from the same immutable baseline with both
    replacements applied together**, mirroring the shipped implementation
    exactly. There is no row-then-column incrementalism: no cell is derived
    from the cell before it, no row result becomes another row's baseline, and
    permuting the candidates changes no cell's value. Exactly
    ``1 + (len(row_values) * len(column_values))`` analyses run.

    ``row_assumption == column_assumption`` raises, mirroring the shipped
    framework's rule for both existing modes.

    ``business_plan`` is resolved once, after the structural checks, for
    ``terms.hold_period``; the baseline and every cell carry that one schedule
    (D6.4).
    """

    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)

    _require_supported_assumption(row_assumption)
    _require_supported_assumption(column_assumption)
    _require_supported_metric(metric)
    if row_assumption == column_assumption:
        raise ValueError(
            "row_assumption and column_assumption must differ; got "
            f"{row_assumption!r} for both."
        )
    _require_unshadowed_target(row_assumption, suite_tuple)
    _require_unshadowed_target(column_assumption, suite_tuple)

    owner_capital = resolve_business_plan(business_plan, hold_period=terms.hold_period)

    baseline_row_value = _TARGETS[row_assumption].read_baseline(
        terms, market_leasing, operating_inputs
    )
    baseline_column_value = _TARGETS[column_assumption].read_baseline(
        terms, market_leasing, operating_inputs
    )
    baseline_metric_value = _scenario_metric(
        terms=terms,
        property_inputs=property_inputs,
        suites=suite_tuple,
        leases=lease_tuple,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        owner_capital=owner_capital,
        changes={},
        metric=metric,
    )

    row_values_tuple = tuple(row_values)
    column_values_tuple = tuple(column_values)

    matrix: list[tuple[float | None, ...]] = []
    for row_value in row_values_tuple:
        row_cells: list[float | None] = []
        for column_value in column_values_tuple:
            row_cells.append(
                _scenario_metric(
                    terms=terms,
                    property_inputs=property_inputs,
                    suites=suite_tuple,
                    leases=lease_tuple,
                    market_leasing=market_leasing,
                    operating_inputs=operating_inputs,
                    owner_capital=owner_capital,
                    changes={
                        row_assumption: row_value,
                        column_assumption: column_value,
                    },
                    metric=metric,
                )
            )
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
