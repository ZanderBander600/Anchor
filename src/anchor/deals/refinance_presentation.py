"""Refinance & Capital Events V1 Stage 3 -- the analyst-facing facts every
refinance surface reads.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 12.5,
15.3 and 16.3 (ratified); that document governs on any discrepancy.

Two narrow jobs, and no calculation:

1. **Which Strategies are refinance-bearing.** A Strategy's resolved Capital
   Structure -- the Base structure it inherits, or its own whole replacement
   (ST-2) -- either configures a capital event or does not. That typed fact is
   what lets a Project surface (the Project Decision Matrix, a Deal's
   underwriting results, Excel Exports 1-3) label its acquisition-loan levered
   figures as the acquisition-financing reference (R-P rules 3 to 5), without
   the presentation layer resolving a Strategy itself.
2. **Why a refinance did not execute, in the analyst's words.** The engine's
   own ``unavailable_message`` is built from typed objects, but at its layer a
   Unit has no analyst name and is named by its id (Section 23.4 item 6). So
   every analyst surface translates the stable reason code here instead, naming
   the refinance by its label, the scope by its Deal or Investment name and the
   valuation by its label (Section 15.3). ``web/src/refinanceCatalog.ts`` holds
   the workspace's copy of the same table, and a guard keeps the two key sets
   equal.

Nothing here sizes, sums, compares or re-derives a figure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..analysis.strategy import BASE_SCENARIO_ID, BASE_STRATEGY_ID
from ..capital_structure.contracts import CommonEquityUnavailableReason, PositionScope, ScopeKind
from ..decision.comparison import DecisionMetric
from ..capital_structure.refinance_contracts import (
    RefinanceResult,
    RefinanceStatus,
    RefinanceUnavailableReason,
    RefinancedCapitalResult,
)
from . import store
from .contracts import DealNotFoundError
from .refinance_integration import has_capital_events
from .structured_variants import resolve_variant_capital_structure

# =============================================================================
# 1. Which Strategies are refinance-bearing
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyCapitalEvents:
    """Whether one Strategy's resolved Capital Structure configures a capital
    event. ``strategy_id`` is the reserved Base key for the Base Strategy."""

    strategy_id: str
    capital_events_configured: bool


#: The Project Decision Matrix metrics that hold the acquisition loan to the
#: sale, and so are the acquisition-financing reference beside a refinance-
#: bearing Strategy (R-P rule 5). The property-level metrics -- unlevered IRR
#: and exit value -- no capital event changes. Stated here, by the server, so
#: no presentation layer keeps a metric catalog of its own.
ACQUISITION_FINANCING_METRICS: tuple[DecisionMetric, ...] = (
    DecisionMetric.LEVERED_IRR,
    DecisionMetric.EQUITY_MULTIPLE,
    DecisionMetric.TOTAL_PROFIT,
    DecisionMetric.TOTAL_EQUITY_INVESTED,
    DecisionMetric.MIN_DSCR,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalEventPresence:
    """The refinance-bearing fact for the Base Strategy and every persisted
    Strategy of one Investment, in the Decision Matrix's own axis order, and
    the Project metrics a refinance-bearing Strategy's figures qualify."""

    investment_id: str
    strategies: tuple[StrategyCapitalEvents, ...]
    acquisition_financing_metrics: tuple[DecisionMetric, ...]


def capital_event_presence(investment_id: str, *, db_path: Path | None = None) -> CapitalEventPresence:
    """Resolve each Strategy's Capital Structure through the accepted
    whole-domain authority and state whether it configures a capital event.
    Reads only; resolves no Project variant and executes nothing."""

    strategy_ids = (
        BASE_STRATEGY_ID,
        *(record.strategy.strategy_id for record in store.list_strategies(investment_id, db_path=db_path)),
    )
    return CapitalEventPresence(
        investment_id=investment_id,
        strategies=tuple(
            StrategyCapitalEvents(
                strategy_id=strategy_id,
                capital_events_configured=has_capital_events(
                    resolve_variant_capital_structure(investment_id, strategy_id, db_path=db_path).capital_structure
                ),
            )
            for strategy_id in strategy_ids
        ),
        acquisition_financing_metrics=ACQUISITION_FINANCING_METRICS,
    )


def base_capital_events_configured(investment_id: str | None, *, db_path: Path | None = None) -> bool:
    """Whether the Base Capital Structure of ``investment_id`` configures a
    capital event. ``None`` -- a Deal with no Investment yet -- has none."""

    if investment_id is None:
        return False
    return has_capital_events(
        resolve_variant_capital_structure(investment_id, BASE_STRATEGY_ID, db_path=db_path).capital_structure
    )


class AcquisitionReferenceUnavailableError(RuntimeError):
    """Whether a Deal's acquisition figures are the acquisition-financing
    reference could not be decided: its owning Base Capital Structure could not
    be read or analysed. Never to be read as "no refinance"."""


def _visible_owner(deal_id: str, *, db_path: Path | None) -> str | None:
    """The visible Investment ``deal_id`` is a Unit of, or ``None``."""

    for investment in store.list_visible_investments(db_path=db_path):
        if any(unit.unit_id == deal_id for unit in investment.units):
            return investment.id
    return None


def acquisition_reference_applies(deal_id: str, *, db_path: Path | None = None) -> bool:
    """Whether Excel Exports 1-3 must name this Deal's acquisition-loan levered
    figures as the acquisition-financing reference (Section 25.1 item 10).

    The Deal's *Base* Capital Structure is read from its true owner: its own
    (hidden) wrapper for a standalone Deal, and the owning visible Investment
    for a Unit -- never through the Deal route that rightly refuses a visible
    Investment's Unit. Strategy replacements are not consulted: an export is of
    the saved Base underwriting. The reference applies when an **executed**
    refinance of the Base Strategy under the Base Scenario applies to this
    Deal: one scoped to it, or one of the whole Investment. A refinance of
    another Unit does not. Nothing is computed; statuses and scopes are read.

    Raises ``AcquisitionReferenceUnavailableError`` when the owner's structure
    or its analysis cannot be read, so the export is refused rather than
    produced without a label it may need. ``DealNotFoundError`` and any
    unexpected error propagate unchanged."""

    from ..capital_structure.contracts import CapitalStructureValidationError, UnsupportedCapitalPositionError
    from ..capital_structure.execution_contracts import CapitalStructureExecutionError
    from .contracts import InvestmentNotFoundError, InvestmentStructureError
    from .investment_variants import InvestmentVariantValidationError
    from .structured_variants import StructuredVariantConflictError, analyze_structured_variant

    try:
        owner = _visible_owner(deal_id, db_path=db_path)
        if owner is None:
            investment_id, structure = store.read_deal_capital_structure(deal_id, db_path=db_path)
        else:
            investment_id, structure = owner, store.get_base_capital_structure(owner, db_path=db_path)
        if investment_id is None or not has_capital_events(structure):
            return False
        result = analyze_structured_variant(
            investment_id, BASE_STRATEGY_ID, BASE_SCENARIO_ID, db_path=db_path
        ).result
    except DealNotFoundError:
        raise
    except (
        store.PersistedDealDataError,
        InvestmentStructureError,
        InvestmentNotFoundError,
        CapitalStructureValidationError,
        UnsupportedCapitalPositionError,
        CapitalStructureExecutionError,
        StructuredVariantConflictError,
        InvestmentVariantValidationError,
    ) as error:
        raise AcquisitionReferenceUnavailableError(str(error)) from error
    if not isinstance(result, RefinancedCapitalResult):
        raise AcquisitionReferenceUnavailableError("The Base analysis carries no refinance result.")
    return any(
        event.status is RefinanceStatus.EXECUTED
        and (event.scope.kind is ScopeKind.INVESTMENT or event.scope.unit_id == deal_id)
        for event in result.capital_events
    )


# =============================================================================
# 2. Why a refinance did not execute, in the analyst's words
# =============================================================================


#: The acquisition-financing reference label (R-P rule 3), one spelling for
#: every backend surface.
ACQUISITION_REFERENCE_LABEL = "Acquisition financing — excludes later capital events"

#: Section 13.3's disclosure: a Scenario's interest-rate change moves the
#: acquisition loan, never a replacement loan.
SCENARIO_RATE_LIMITATION = (
    "A Scenario's interest-rate change applies to the acquisition loan only. A replacement loan's rate is a "
    "Capital Structure term, so alternative refinance terms are modelled as separate Strategies."
)

#: The V1 DSCR basis Section 9.3 obliges Stage 3 to state beside every DSCR
#: capacity.
DSCR_BASIS = (
    "V1 basis: the replacement loan's actual scheduled debt service in its first twelve months, interest-only "
    "months included."
)


def _valuation_phrase(label: str | None) -> str:
    return "The referenced valuation" if label is None else f"The valuation “{label}”"


#: One sentence per typed reason (Section 15.2). The keys are exactly
#: ``RefinanceUnavailableReason``; ``web/src/refinanceCatalog.ts`` carries the
#: same keys.
REFINANCE_REASON_SENTENCES: Mapping[RefinanceUnavailableReason, str] = {
    RefinanceUnavailableReason.EVENT_OUTSIDE_HOLD_HORIZON: (
        "“{label}” is at the end of Year {hold_year}, which is not before the sale in this analysis, so it "
        "cannot execute here. It may execute under a longer hold."
    ),
    RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND: (
        "The valuation that “{label}” measures its maximum LTV against no longer exists. No other value is used "
        "in its place."
    ),
    RefinanceUnavailableReason.MODEL_MONTH_MISMATCH: (
        "{valuation} is dated at a different time than “{label}”. A valuation is never moved to match a refinance."
    ),
    RefinanceUnavailableReason.SCOPE_NOT_COVERED: (
        "{valuation} has no value for {scope}. No other scope's value is used."
    ),
    RefinanceUnavailableReason.VALUATION_UNAVAILABLE: (
        "{valuation} has no value for {scope} in this analysis. It is never read as zero or replaced by the "
        "purchase price."
    ),
    RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED: (
        "{valuation} is analyst-supplied and its Evidence Reference is not approved. The typed amount is not used "
        "until the evidence is approved."
    ),
    RefinanceUnavailableReason.FORWARD_NOI_UNAVAILABLE: (
        "There is no forward NOI for {scope}{forward} in this analysis, so the minimum DSCR cannot be sized. No "
        "valuation stands in for it."
    ),
    RefinanceUnavailableReason.NON_POSITIVE_FORWARD_NOI: (
        "Forward NOI for {scope}{forward} is zero or negative, so the minimum DSCR supports no loan. It is never "
        "floored."
    ),
    RefinanceUnavailableReason.RETIRING_POSITION_ABSENT: (
        "A loan it repays does not exist in this analysis — for example, the acquisition loan when this variant "
        "finances with none."
    ),
    RefinanceUnavailableReason.RETIRING_POSITION_NOT_OUTSTANDING: (
        "A loan it repays is already fully repaid before the refinance date in this analysis."
    ),
    RefinanceUnavailableReason.NON_POSITIVE_CAPACITY: (
        "The least of its sizing capacities is zero or negative, so no replacement loan can be funded. The old "
        "loans are not silently kept in place."
    ),
    RefinanceUnavailableReason.UPSTREAM_UNRESOLVED_FUNDING: (
        "A Funding Requirement in its scope, at or before the refinance, is unresolved, so the refinance cannot "
        "settle."
    ),
    RefinanceUnavailableReason.UPSTREAM_CAPITAL_EVENT_NOT_EXECUTED: (
        "A Unit refinance in this Investment did not execute, so this Investment refinance cannot settle either."
    ),
}


def scope_name(scope: PositionScope, unit_names: Mapping[str, str]) -> str:
    """A refinance's scope as the analyst knows it."""

    if scope.kind is ScopeKind.INVESTMENT:
        return "the whole Investment"
    return unit_names.get(scope.unit_id or "", "this Unit")


def reason_sentence(
    reason: RefinanceUnavailableReason,
    result: RefinanceResult,
    *,
    unit_names: Mapping[str, str],
    valuation_labels: Mapping[str, str],
) -> str:
    """One typed reason as the analyst reads it. No identity, amount or
    upstream prose is quoted."""

    timepoint = None if result.value_dependency is None else result.value_dependency.timepoint_id
    forward = None if result.noi_dependency is None else result.noi_dependency.forward_year
    return REFINANCE_REASON_SENTENCES[reason].format(
        label=result.label,
        scope=scope_name(result.scope, unit_names),
        hold_year=result.hold_year,
        forward="" if forward is None else f" in Year {forward}",
        valuation=_valuation_phrase(None if timepoint is None else valuation_labels.get(timepoint)),
    )


def event_reason_sentence(
    result: RefinanceResult, *, unit_names: Mapping[str, str], valuation_labels: Mapping[str, str]
) -> str | None:
    """Why this refinance did not execute, or ``None`` when it did."""

    if result.unavailable_reason is None:
        return None
    return reason_sentence(result.unavailable_reason, result, unit_names=unit_names, valuation_labels=valuation_labels)


def not_executed(result: object) -> tuple[RefinanceResult, ...]:
    """The configured refinances of a structured result that did not execute,
    in the result's economic order. Empty for a result with no capital event."""

    if not isinstance(result, RefinancedCapitalResult):
        return ()
    return tuple(event for event in result.capital_events if event.status is not RefinanceStatus.EXECUTED)


def common_equity_unavailable_sentence(events: tuple[RefinanceResult, ...]) -> str:
    """Why Common Equity -- the primary refinance-adjusted return -- has no
    figures, naming each refinance that did not execute by its label."""

    names = ", ".join(f"“{event.label}”" for event in events)
    return (
        f"Common Equity is not reported: {names} did not execute for this analysis, so the cash after it is "
        "unknowable. Property and project results are unaffected, and the acquisition-financing figures are not a "
        "substitute."
    )


def blanked_by_refinance(partnership_result: object) -> bool:
    """Whether a Partnership result is unavailable because its upstream Common
    Equity was blanked by a refinance that did not execute (R-O) -- read from
    the typed upstream reason, never from a message."""

    return getattr(partnership_result, "upstream_reason", None) is CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE


def unit_names_of(unit_ids: tuple[str, ...], *, db_path: Path | None = None) -> dict[str, str]:
    """Each Unit by its Deal's name -- the name the analyst has always seen.

    A Unit whose Deal no longer exists is named honestly, never by its id.
    Only that: persisted-data corruption, a database failure or a programming
    error propagates to the caller's typed refusal boundary rather than being
    worded as a removed Unit (Stage 3 correction round)."""

    names: dict[str, str] = {}
    for unit_id in unit_ids:
        try:
            names[unit_id] = store.get_deal(unit_id, db_path=db_path).name
        except DealNotFoundError:
            names[unit_id] = "the selected Unit (no longer available)"
    return names


__all__ = [
    "ACQUISITION_REFERENCE_LABEL",
    "AcquisitionReferenceUnavailableError",
    "acquisition_reference_applies",
    "CapitalEventPresence",
    "DSCR_BASIS",
    "REFINANCE_REASON_SENTENCES",
    "SCENARIO_RATE_LIMITATION",
    "StrategyCapitalEvents",
    "base_capital_events_configured",
    "blanked_by_refinance",
    "capital_event_presence",
    "common_equity_unavailable_sentence",
    "event_reason_sentence",
    "not_executed",
    "reason_sentence",
    "scope_name",
    "unit_names_of",
]
