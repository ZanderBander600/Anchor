"""Phase 7 Gate P7.2 -- the Scenario variant service.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
7.5, 15.4 and the Section 21 record (Q14, Q15); that document governs on any
discrepancy.

The one place a persisted Scenario meets the deterministic engine::

    the persisted Scenario + the unit's current Deal     (``store``)
            |
    P7.1 resolution                 ``resolve_*_scenario``: the only authority
            |
    resolved-input fingerprint      the existing per-mode fingerprint of the
            |                       *resolved* contracts
    Quick / Detailed:  a current cached result, or else
    every mode:        the existing D6 ``*_with_business_plan`` entry point
            |
    the existing result contracts, unchanged

**One Analysis Variant = one ordinary run (Section 7.5).** In P7.2 the variant
is ``(the hidden Investment, the implicit Base strategy, the Scenario)`` over
the Investment's one unit. Nothing is authored on it and no record of it
exists; only the cache below is keyed by it.

**Fingerprint the resolved inputs, not the recipe (Section 15.4, FP-1, Q15).**
The source fingerprint is the existing unit fingerprint function applied to
the contracts P7.1 resolution produced. It follows that:
- a Scenario with no overrides fingerprints exactly as today's Deal (the
  resolver hands back the Deal's own objects);
- two recipes that resolve to the same inputs share a fingerprint;
- a Scenario's id, name and description, the Investment's id, row order and
  timestamps never reach it -- ``fingerprint_resolved_inputs`` receives only
  the resolved contracts;
- removing an override restores the original fingerprint exactly.
The Business Plan passes through resolution unchanged (P7.1 changes no plan),
so it enters the fingerprint exactly as D6.5 defines: a non-empty plan adds
its key and the empty plan adds nothing.

**The cache is never authority (Q14).** A cached Quick or Detailed result is
served only when its stored source fingerprint equals the fingerprint just
recomputed here from the current Scenario and the current Deal. A stale,
corrupt, incompatible or missing row is a miss, and a miss is a deterministic
recomputation through the D6 entry point.

**Lease-Level is recomputed (Q14, D5 decision A).** A Lease-Level variant never
reads or writes the cache.

**No arithmetic, and no second pathway.** This module computes nothing: it
selects the P7.1 resolver and the D6 entry point for the unit's mode and
passes contracts between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..analysis.business_plan_analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from ..analysis.contracts import LeaseLevelAcquisitionResults
from ..analysis.scenario import (
    ResolvedDetailedInputs,
    ResolvedLeaseLevelInputs,
    ResolvedQuickInputs,
    ScenarioDefinition,
    resolve_detailed_scenario,
    resolve_lease_level_scenario,
    resolve_quick_scenario,
)
from ..contracts import OperatingMode, UnsupportedOperatingModeError
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults
from . import store
from .contracts import Deal
from .fingerprint import (
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)

ResolvedScenarioInputs = ResolvedQuickInputs | ResolvedDetailedInputs | ResolvedLeaseLevelInputs
VariantResults = AcquisitionResults | DetailedAcquisitionResults | LeaseLevelAcquisitionResults


class VariantCacheStatus(StrEnum):
    """How an analysed variant's result was obtained -- reported so the cache
    is visible and never mistaken for a second authority.

    - ``HIT``: a cached Quick or Detailed result whose source fingerprint
      matched the fingerprint just recomputed from the current inputs;
    - ``MISS``: no current cache, so the D6 entry point ran and the result was
      cached under its source fingerprint;
    - ``BYPASSED``: a Lease-Level variant, recomputed and never cached.
    """

    HIT = "hit"
    MISS = "miss"
    BYPASSED = "bypassed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioVariantFingerprint:
    """The resolved-input financial fingerprint of one Scenario's Base-strategy
    variant, beside the identity it belongs to."""

    investment_id: str
    scenario_id: str
    unit_id: str
    operating_mode: OperatingMode
    source_fingerprint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioVariantAnalysis:
    """One analysed variant. ``results`` is the existing result contract of the
    unit's mode, exactly as ``POST /analyze`` returns it for the same resolved
    inputs entered by hand."""

    investment_id: str
    scenario_id: str
    unit_id: str
    operating_mode: OperatingMode
    source_fingerprint: str
    cache_status: VariantCacheStatus
    results: VariantResults


def resolve_scenario_inputs(deal: Deal, scenario: ScenarioDefinition) -> ResolvedScenarioInputs:
    """Resolve ``scenario`` over ``deal``'s current inputs and Business Plan
    with the P7.1 resolver for its mode, the Deal being the one Unit analysed.

    Raises ``ScenarioValidationError`` when the variant is invalid (SC-4,
    SC-5): the existing validator's reason, never a clipped value."""

    match deal.operating_mode:
        case OperatingMode.QUICK:
            assert deal.inputs is not None
            return resolve_quick_scenario(
                deal.inputs,
                unit_id=deal.id,
                scenario=scenario,
                business_plan=deal.business_plan,
            )
        case OperatingMode.DETAILED:
            assert deal.terms is not None
            assert deal.detailed_operating_inputs is not None
            return resolve_detailed_scenario(
                deal.terms,
                deal.detailed_operating_inputs,
                unit_id=deal.id,
                scenario=scenario,
                business_plan=deal.business_plan,
            )
        case OperatingMode.LEASE_LEVEL:
            assert deal.terms is not None
            assert deal.property_inputs is not None
            assert deal.market_leasing is not None
            assert deal.operating_inputs is not None
            assert deal.suites is not None
            assert deal.leases is not None
            return resolve_lease_level_scenario(
                deal.terms,
                deal.property_inputs,
                deal.suites,
                deal.leases,
                market_leasing=deal.market_leasing,
                operating_inputs=deal.operating_inputs,
                unit_id=deal.id,
                scenario=scenario,
                business_plan=deal.business_plan,
            )
        case _:
            raise UnsupportedOperatingModeError(
                deal.operating_mode, operation="resolve_scenario_inputs"
            )


def fingerprint_resolved_inputs(resolved: ResolvedScenarioInputs) -> str:
    """The one authority for a variant's financial source fingerprint: the
    existing fingerprint function of the resolved contracts' own mode, applied
    to exactly those contracts. It receives nothing else, so no display
    metadata can reach it."""

    match resolved:
        case ResolvedQuickInputs():
            return fingerprint_quick_inputs(
                resolved.inputs, business_plan=resolved.business_plan
            )
        case ResolvedDetailedInputs():
            return fingerprint_detailed_inputs(
                resolved.terms,
                resolved.detailed_operating_inputs,
                business_plan=resolved.business_plan,
            )
        case ResolvedLeaseLevelInputs():
            return fingerprint_lease_level_inputs(
                resolved.terms,
                resolved.property_inputs,
                resolved.suites,
                resolved.leases,
                market_leasing=resolved.market_leasing,
                operating_inputs=resolved.operating_inputs,
                business_plan=resolved.business_plan,
            )
        case _:
            raise TypeError(f"Not resolved scenario inputs: {type(resolved).__qualname__}.")


def _analyze_resolved(resolved: ResolvedScenarioInputs) -> VariantResults:
    """The existing D6 entry point for the resolved contracts' own mode."""

    match resolved:
        case ResolvedQuickInputs():
            return analyze_quick_acquisition_with_business_plan(
                resolved.inputs, business_plan=resolved.business_plan
            )
        case ResolvedDetailedInputs():
            return analyze_detailed_acquisition_with_business_plan(
                resolved.terms,
                resolved.detailed_operating_inputs,
                business_plan=resolved.business_plan,
            )
        case ResolvedLeaseLevelInputs():
            return analyze_lease_level_acquisition_with_business_plan(
                resolved.terms,
                resolved.property_inputs,
                resolved.suites,
                resolved.leases,
                market_leasing=resolved.market_leasing,
                operating_inputs=resolved.operating_inputs,
                business_plan=resolved.business_plan,
            )
        case _:
            raise TypeError(f"Not resolved scenario inputs: {type(resolved).__qualname__}.")


@dataclass(frozen=True, slots=True, kw_only=True)
class _VariantSource:
    investment_id: str
    scenario: ScenarioDefinition
    deal: Deal


def _load_variant_source(
    investment_id: str, scenario_id: str, db_path: Path | None
) -> _VariantSource:
    """The persisted Scenario, proven to belong to ``investment_id``, and the
    wrapper's one Deal as currently stored."""

    record = store.get_scenario(investment_id, scenario_id, db_path=db_path)
    investment = store.get_investment(investment_id, db_path=db_path)
    if len(investment.units) != 1:
        raise store.PersistedDealDataError(
            f"Investment {investment_id!r} does not hold exactly one unit."
        )
    deal = store.get_deal(investment.units[0].unit_id, db_path=db_path)
    return _VariantSource(investment_id=investment_id, scenario=record.scenario, deal=deal)


def scenario_variant_fingerprint(
    investment_id: str, scenario_id: str, *, db_path: Path | None = None
) -> ScenarioVariantFingerprint:
    """The current resolved-input fingerprint of the persisted Scenario's
    Base-strategy variant. Read-only."""

    source = _load_variant_source(investment_id, scenario_id, db_path)
    resolved = resolve_scenario_inputs(source.deal, source.scenario)
    return ScenarioVariantFingerprint(
        investment_id=investment_id,
        scenario_id=scenario_id,
        unit_id=source.deal.id,
        operating_mode=source.deal.operating_mode,
        source_fingerprint=fingerprint_resolved_inputs(resolved),
    )


def analyze_scenario_variant(
    investment_id: str, scenario_id: str, *, db_path: Path | None = None
) -> ScenarioVariantAnalysis:
    """Analyse the persisted Scenario's Base-strategy variant.

    Resolves the Scenario over the Deal's current inputs and fingerprints the
    result; serves a Quick or Detailed cached result only when its source
    fingerprint equals that fingerprint; otherwise runs the D6 entry point on
    the resolved contracts and caches the result under the same fingerprint.
    A Lease-Level variant is always recomputed and never cached."""

    source = _load_variant_source(investment_id, scenario_id, db_path)
    deal = source.deal
    resolved = resolve_scenario_inputs(deal, source.scenario)
    source_fingerprint = fingerprint_resolved_inputs(resolved)

    results: VariantResults
    match deal.operating_mode:
        case OperatingMode.QUICK | OperatingMode.DETAILED:
            cached = store.get_variant_snapshot(
                investment_id,
                scenario_id,
                operating_mode=deal.operating_mode,
                expected_fingerprint=source_fingerprint,
                db_path=db_path,
            )
            if cached is not None:
                results, cache_status = cached, VariantCacheStatus.HIT
            else:
                computed = _analyze_resolved(resolved)
                assert not isinstance(computed, LeaseLevelAcquisitionResults)
                store.put_variant_snapshot(
                    investment_id,
                    scenario_id,
                    computed,
                    source_fingerprint=source_fingerprint,
                    db_path=db_path,
                )
                results, cache_status = computed, VariantCacheStatus.MISS
        case OperatingMode.LEASE_LEVEL:
            results = _analyze_resolved(resolved)
            cache_status = VariantCacheStatus.BYPASSED
        case _:
            raise UnsupportedOperatingModeError(
                deal.operating_mode, operation="analyze_scenario_variant"
            )

    return ScenarioVariantAnalysis(
        investment_id=investment_id,
        scenario_id=scenario_id,
        unit_id=deal.id,
        operating_mode=deal.operating_mode,
        source_fingerprint=source_fingerprint,
        cache_status=cache_status,
        results=results,
    )
