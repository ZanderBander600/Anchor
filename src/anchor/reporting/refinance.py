"""Refinance & Capital Events V1 Stage 3 -- the refinance-aware report.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 11,
12.5, 13.3 and 16.3 (ratified); that document governs on any discrepancy.

When the selected decision cell's resolved Capital Structure configures a
refinance, the report changes in three places, and only then:

1. **Headlines (R-P rules 1 to 4).** The key-metric return and multiple are
   Common Equity after Capital Structure -- or, for a Partner-perspective memo,
   that Partner's -- never the acquisition-loan levered figures. When the
   refinance did not execute, that unavailable state *is* the headline, with
   its reason; nothing stands in for it (rule 6).
2. **Returns and projection (rule 5).** Wherever the acquisition-loan levered
   figures still appear they are named "Acquisition financing — excludes later
   capital events", beside the figure.
3. **A Refinance section.** Timing and scope, the replacement loan, each
   sizing capacity with the operands behind it and the binding constraint, the
   valuation dependency only where LTV applies, the forward-NOI dependency only
   where DSCR applies, the payoff and fee bridge, the cash returned to Common
   Equity (or the contribution it requires), and the Common Equity cash flow
   with the refinance cash apart from the recurring cash.

**It computes nothing.** Every figure is one field of the accepted engine
result, converted to text once through ``anchor.formatting``. A contribution's
magnitude is the formatted figure with its sign removed as *text*; nothing is
negated, summed or compared (Section 12.5 rule 7). A report without a
refinance never reaches this module, so it is byte-identical to before.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analysis.strategy import BASE_SCENARIO_ID
from ..capital_structure.contracts import ScopeKind
from ..capital_structure.refinance_contracts import (
    BridgeDirection,
    ConstraintKind,
    FixedCapOperands,
    MaxLtvOperands,
    MinDscrOperands,
    RefinanceResult,
    RefinanceStatus,
)
from ..deals.refinance_presentation import (
    ACQUISITION_REFERENCE_LABEL,
    DSCR_BASIS,
    SCENARIO_RATE_LIMITATION,
    common_equity_unavailable_sentence,
    event_reason_sentence,
    not_executed,
    reason_sentence,
    scope_name,
    unit_names_of,
)
from ..formatting import format_currency, format_multiple, format_percent
from ..memo.contracts import DecisionPerspectiveKind, SelectedDecision
from .contracts import (
    MemoReportDisclosure,
    MemoReportMetric,
    MemoReportSection,
    MemoReportTable,
    ReportUnavailable,
)

#: The stable code every refinance-dependent unavailable cell carries. It is
#: the engine's own ``CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE``
#: token, so a reader of the frozen artifact can tell it from any other state.
REFINANCE_UNAVAILABLE_CODE = "refinance_unavailable"

#: Period labels for a series indexed ``t = 0..H``, read by position so the
#: report's bookkeeping carries no arithmetic.
_PERIOD_LABELS = tuple(f"Year {number}" for number in range(0, 41))

_CONSTRAINT_LABELS = {
    ConstraintKind.FIXED_CAP: "Fixed maximum proceeds",
    ConstraintKind.MAX_LTV: "Maximum LTV",
    ConstraintKind.MIN_DSCR: "Minimum DSCR",
}

_STATUS_LABELS = {
    RefinanceStatus.EXECUTED: "Executed",
    RefinanceStatus.UNAVAILABLE: "Unavailable",
    RefinanceStatus.NOT_EXECUTABLE: "Not executable",
    RefinanceStatus.BLOCKED: "Blocked",
}

_DIRECTION_HEADINGS = {
    BridgeDirection.DISTRIBUTION: "Cash Returned to Common Equity",
    BridgeDirection.CONTRIBUTION: "Common Equity Contribution Required",
    BridgeDirection.ZERO: "Cash Returned to Common Equity",
}

_DIRECTION_LABELS = {
    BridgeDirection.DISTRIBUTION: "Distribution",
    BridgeDirection.CONTRIBUTION: "Contribution",
    BridgeDirection.ZERO: "Zero",
}


#: Why the engine reports no IRR for a series, in the words the workspace
#: already uses (``web/src/capitalEconomics.ts`` ``IRR_NOT_REPORTED_REASONS``).
#: Keyed on the engine's own ``IrrStatus``, never on the value being absent.
_IRR_NOT_REPORTED = {
    "no_nonzero_cash_flow": "every modeled cash flow is zero",
    "first_nonzero_not_negative": "the modeled cash flows do not begin with an investment",
    "no_positive_cash_flow": "the modeled cash flows contain no positive cash flow",
    "multiple_sign_changes": "the modeled cash-flow pattern changes sign more than once",
    "root_outside_search_domain": "the return falls outside Anchor's supported search domain",
    "numerical_failure": "the deterministic IRR calculation encountered a numerical issue",
}


def _irr_not_reported(label: str, status: Any) -> str | None:
    """"<label> is not reported because ...", or ``None`` for a defined IRR
    or no status at all."""

    token = getattr(status, "value", status)
    reason = None if token is None else _IRR_NOT_REPORTED.get(str(token))
    return None if reason is None else f"{label} is not reported because {reason}."


def _irr_code(status: Any) -> str:
    """The engine's own ``IrrStatus`` token, carried through unchanged as the
    unavailable cell's ``reason_code`` (``ReportUnavailable``)."""

    return str(getattr(status, "value", status))


def _period_label(index: int) -> str:
    return _PERIOD_LABELS[index] if index < len(_PERIOD_LABELS) else "Later year"


def _money(value: float | None) -> str:
    return "Unavailable" if value is None else format_currency(value)


def _magnitude(value: float) -> str:
    """The engine's figure as text without its sign, for a line whose heading
    already says which way the cash moves. Text only; nothing is negated."""

    return format_currency(value).removeprefix("-")


def _available(label: str, value: str, *, note: str | None = None) -> MemoReportMetric:
    return MemoReportMetric(label=label, value=value, note=note)


def _unavailable(
    label: str, reason: str, *, note: str | None = None, code: str = REFINANCE_UNAVAILABLE_CODE
) -> MemoReportMetric:
    return MemoReportMetric(
        label=label,
        unavailable=ReportUnavailable(reason_code=code, reason=reason),
        note=note,
    )


# =============================================================================
# Is this report refinance-bearing, and what are things called
# =============================================================================


def refinance_bearing(structured: Any) -> bool:
    """Whether the selected cell's resolved Capital Structure configures a
    refinance: the server's own typed primary-return statement is present
    exactly then (Stage 2, Section 24.6)."""

    return getattr(structured, "primary_return", None) is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceNames:
    """Analyst-facing names the refinance section needs, never identities."""

    units: Mapping[str, str]
    positions: Mapping[str, str]
    valuations: Mapping[str, str]
    multi_unit: bool


def names_for(analysis: Any, *, db_path: Path | None) -> RefinanceNames:
    structured = analysis.structured
    result = structured.result
    unit_ids = tuple(result.unit_ids)
    units = unit_names_of(unit_ids, db_path=db_path)
    positions = {position.position_id: position.name for position in result.positions}
    positions.update({position.position_id: position.name for position in getattr(result, "unexecuted_positions", ())})
    valuations = {view.timepoint_id: view.label for view in getattr(analysis.surface, "views", ())}
    return RefinanceNames(units=units, positions=positions, valuations=valuations, multi_unit=len(unit_ids) > 1)


def _events(structured: Any) -> tuple[RefinanceResult, ...]:
    return tuple(getattr(structured.result, "capital_events", ()))


def _retiring_name(ref: Any, names: RefinanceNames) -> str:
    unit_id = getattr(ref, "unit_id", None)
    if unit_id is not None:
        return f"Acquisition loan – {names.units.get(unit_id, 'Unit')}" if names.multi_unit else "Acquisition loan"
    return names.positions.get(getattr(ref, "position_id", ""), "A loan no longer in this structure")


# =============================================================================
# 1. Headlines
# =============================================================================


def _partner(analysis: Any, partner_id: str | None) -> tuple[str, Any] | None:
    """The selected partner's name and result, where the variant resolves a
    Partnership that holds it."""

    resolved = analysis.partnership
    if resolved is None or partner_id is None:
        return None
    stated = getattr(resolved, "partnership", None)
    name = next(
        (partner.name for partner in getattr(stated, "partners", ()) or () if partner.partner_id == partner_id),
        None,
    )
    result = getattr(resolved, "result", None)
    figures = next(
        (partner for partner in getattr(result, "partners", ()) or () if partner.partner_id == partner_id), None
    )
    return None if name is None else (name, figures)


def headline_returns(
    analysis: Any, selected: SelectedDecision, names: RefinanceNames
) -> tuple[MemoReportMetric, ...]:
    """The refinance-adjusted headline return and multiple, then the cash each
    refinance returned to (or required from) Common Equity."""

    structured = analysis.structured
    events = _events(structured)
    missed = not_executed(structured.result)
    reason = None if not missed else common_equity_unavailable_sentence(missed)
    note_missing = "Refinance did not execute – see Refinance."
    metrics: list[MemoReportMetric] = []

    partner = _partner(analysis, selected.partner_id) if selected.perspective is DecisionPerspectiveKind.PARTNER else None
    if partner is not None:
        name, figures = partner
        irr = None if figures is None else getattr(figures, "irr", None)
        moic = None if figures is None else getattr(figures, "moic", None)
        why = reason or "The Partnership did not report this partner's return for the selected analysis."
        metrics.append(
            _available(f"Partner IRR – {name}", format_percent(irr), note="Refinance-adjusted")
            if irr is not None
            else _unavailable(f"Partner IRR – {name}", why, note=note_missing if reason else None)
        )
        metrics.append(
            _available(f"Partner Multiple – {name}", format_multiple(moic), note="Refinance-adjusted")
            if moic is not None
            else _unavailable(f"Partner Multiple – {name}", why, note=note_missing if reason else None)
        )
    else:
        common = structured.result.common_equity
        why = reason or "Common Equity did not report this figure for the selected analysis."
        irr_note = _irr_not_reported("Common Equity IRR", common.irr_status)
        metrics.append(
            _available("Common Equity IRR", format_percent(common.irr), note="After Capital Structure")
            if common.irr is not None
            else _unavailable(
                "Common Equity IRR",
                irr_note or why,
                note=note_missing if reason else ("Not defined for this cash flow" if irr_note else None),
                code=_irr_code(common.irr_status) if irr_note else REFINANCE_UNAVAILABLE_CODE,
            )
        )
        metrics.append(
            _available("Common Equity Multiple", format_multiple(common.equity_multiple), note="After Capital Structure")
            if common.equity_multiple is not None
            else _unavailable("Common Equity Multiple", why, note=note_missing if reason else None)
        )

    for event in events:
        suffix = "" if len(events) == 1 else f" – {event.label}"
        bridge = event.bridge
        if bridge is None:
            metrics.append(
                _unavailable(
                    f"Cash Returned to Common Equity{suffix}",
                    event_reason_sentence(event, unit_names=names.units, valuation_labels=names.valuations)
                    or "The refinance did not execute.",
                    note="Refinance did not execute – see Refinance.",
                )
            )
        else:
            metrics.append(
                _available(
                    f"{_DIRECTION_HEADINGS[bridge.direction]}{suffix}",
                    _magnitude(bridge.net_event_cash),
                    note=f"End of Year {event.hold_year}",
                )
            )
    return tuple(metrics)


# =============================================================================
# 2. Returns beside the acquisition-financing reference
# =============================================================================


def project_returns(analysis: Any, economics: Any) -> tuple[MemoReportMetric, ...]:
    """A Project-perspective memo's returns when a refinance is configured:
    Common Equity after Capital Structure first, the property-level unlevered
    IRR, and the acquisition-loan levered figures only under their reference
    label."""

    structured = analysis.structured
    common = structured.result.common_equity
    missed = not_executed(structured.result)
    reason = None if not missed else common_equity_unavailable_sentence(missed)
    why = reason or "Common Equity did not report this figure for the selected analysis."

    def common_metric(label: str, value: float | None, formatter: Any) -> MemoReportMetric:
        return _available(label, formatter(value)) if value is not None else _unavailable(label, why)

    irr_note = _irr_not_reported("Common Equity IRR", common.irr_status)
    metrics = [
        common_metric("Common Equity IRR (after Capital Structure)", common.irr, format_percent)
        if common.irr is not None or irr_note is None
        else _unavailable(
            "Common Equity IRR (after Capital Structure)",
            irr_note,
            note="Not defined for this cash flow",
            code=_irr_code(common.irr_status),
        ),
        common_metric("Common Equity Multiple", common.equity_multiple, format_multiple),
        common_metric("Total Equity Invested", common.total_equity_invested, format_currency),
        common_metric("Total Cash Returned", common.total_cash_returned, format_currency),
        common_metric("Total Profit", common.total_profit, format_currency),
    ]
    if economics is not None:
        unlevered = getattr(economics, "unlevered_irr", None)
        if unlevered is not None:
            metrics.append(_available("Unlevered IRR", format_percent(unlevered), note="Property level"))
        levered = getattr(economics, "levered_irr", None)
        multiple = getattr(economics, "equity_multiple", None)
        if levered is not None:
            metrics.append(_available("Levered IRR", format_percent(levered), note=ACQUISITION_REFERENCE_LABEL))
        if multiple is not None:
            metrics.append(_available("Equity Multiple", format_multiple(multiple), note=ACQUISITION_REFERENCE_LABEL))
    return tuple(metrics)


# =============================================================================
# 3. The Refinance section
# =============================================================================


def _operands(kind: ConstraintKind, operands: Any, event: RefinanceResult, names: RefinanceNames) -> str:
    if kind is ConstraintKind.FIXED_CAP and isinstance(operands, FixedCapOperands):
        return f"Authored cap {format_currency(operands.amount)}"
    if kind is ConstraintKind.MAX_LTV and isinstance(operands, MaxLtvOperands):
        timepoint = None if event.value_dependency is None else event.value_dependency.timepoint_id
        label = names.valuations.get(timepoint or "", "the referenced valuation")
        return (
            f"{format_percent(operands.max_ltv)} of {label} ({_money(operands.scope_value)}), less continuing "
            f"senior debt {format_currency(operands.continuing_senior_balance)}"
        )
    if kind is ConstraintKind.MIN_DSCR and isinstance(operands, MinDscrOperands):
        forward = "" if event.noi_dependency is None else f"Year {event.noi_dependency.forward_year} "
        return (
            f"{forward}forward NOI {_money(operands.forward_noi)} at {format_multiple(operands.min_dscr)}, less "
            f"continuing senior service {format_currency(operands.continuing_senior_service)}; first-year service "
            f"{format_percent(operands.first_year_service_per_dollar, 4)} per dollar"
        )
    return "Unavailable"


def _sizing_table(event: RefinanceResult, names: RefinanceNames) -> MemoReportTable | None:
    sizing = event.sizing
    if sizing is None:
        return None
    binding = set(sizing.binding)
    rows = []
    for capacity in sizing.capacities:
        if capacity.capacity is None:
            result = "Unavailable"
        elif capacity.kind in binding:
            result = "Binding (tie)" if sizing.tie else "Binding"
        elif sizing.gross_proceeds is None:
            # Another enabled constraint is unavailable, so no minimum was
            # taken: this capacity was not compared, and is not "not binding".
            result = "Not compared"
        else:
            result = "Not binding"
        rows.append(
            (
                _CONSTRAINT_LABELS[capacity.kind],
                _operands(capacity.kind, capacity.operands, event, names),
                _money(capacity.capacity),
                result,
            )
        )
    notes = [
        reason_sentence(capacity.unavailable_reason, event, unit_names=names.units, valuation_labels=names.valuations)
        for capacity in sizing.capacities
        if capacity.unavailable_reason is not None
    ]
    if any(capacity.kind is ConstraintKind.MIN_DSCR for capacity in sizing.capacities):
        notes.append(DSCR_BASIS)
    return MemoReportTable(
        caption=f"Sizing – {event.label}",
        headers=("Constraint", "Operands", "Capacity", "Result"),
        rows=tuple(rows),
        align_right=(2,),
        emphasize_rows=tuple(index for index, capacity in enumerate(sizing.capacities) if capacity.kind in binding),
        note=" ".join(notes) or None,
    )


def _bridge_table(event: RefinanceResult, names: RefinanceNames) -> MemoReportTable:
    bridge = event.bridge
    replacement = None if event.funding is None else names.positions.get(event.funding.position_id)
    rows: list[tuple[str, str]] = [
        (
            "Gross replacement-loan proceeds" if replacement is None else f"Gross proceeds – {replacement}",
            "Unavailable" if bridge is None else format_currency(bridge.gross_proceeds),
        )
    ]
    for payoff in event.payoffs or ():
        rows.append(
            (
                f"Less payoff – {_retiring_name(payoff.ref, names)}",
                "Unavailable" if bridge is None else format_currency(payoff.payoff),
            )
        )
    if event.payoffs is None:
        rows.append(("Less payoff of the loans repaid", "Unavailable"))
    rows.extend(
        [
            ("Less replacement-lender fees", "Unavailable" if bridge is None else format_currency(bridge.replacement_lender_fees)),
            ("Less retiring-lender fees", "Unavailable" if bridge is None else format_currency(bridge.retiring_lender_fees)),
            ("Less third-party costs", "Unavailable" if bridge is None else format_currency(bridge.third_party_costs)),
        ]
    )
    # The net line's position, read before it is appended: a count, not a sum.
    total = len(rows)
    rows.append(("Net refinance cash to Common Equity", "Unavailable" if bridge is None else format_currency(bridge.net_event_cash)))
    rows.append(("Direction", "Unavailable" if bridge is None else _DIRECTION_LABELS[bridge.direction]))
    return MemoReportTable(
        caption=f"Refinance Bridge – {event.label}",
        headers=("Line", "Amount"),
        rows=tuple(rows),
        align_right=(1,),
        emphasize_rows=(total,),
        note=(
            "Each line is the engine's own figure at the refinance date. The retiring loans' scheduled payments "
            "for that month are ordinary debt service of the year and are not in the bridge."
        ),
    )


def _event_metrics(event: RefinanceResult, names: RefinanceNames) -> tuple[MemoReportMetric, ...]:
    funding = event.funding
    replacement = None if funding is None else names.positions.get(funding.position_id)
    metrics = [
        _available("Refinance", event.label),
        _available("Date", f"End of Year {event.hold_year}"),
        _available(
            "Scope",
            "Whole Investment" if event.scope.kind is ScopeKind.INVESTMENT else scope_name(event.scope, names.units),
        ),
        _available("Status", _STATUS_LABELS[event.status]),
    ]
    if funding is None:
        why = event_reason_sentence(event, unit_names=names.units, valuation_labels=names.valuations) or "The refinance did not execute."
        metrics.extend(
            [
                _unavailable("Replacement Loan", why),
                _unavailable("Gross Proceeds", why),
                _unavailable("Cash Returned to Common Equity", why),
            ]
        )
        return tuple(metrics)
    sizing = event.sizing
    metrics.extend(
        [
            _available("Replacement Loan", replacement or "Replacement loan"),
            _available("Gross Proceeds", format_currency(funding.gross_proceeds)),
            _available(
                "Binding Constraint",
                "Unavailable"
                if sizing is None or not sizing.binding
                else ", ".join(_CONSTRAINT_LABELS[kind] for kind in sizing.binding),
                note="Tie" if sizing is not None and sizing.tie else None,
            ),
            _available(
                "Achieved LTV", "Not applicable" if funding.achieved_ltv is None else format_percent(funding.achieved_ltv)
            ),
            _available(
                "Achieved DSCR",
                "Not applicable" if funding.achieved_dscr is None else format_multiple(funding.achieved_dscr),
            ),
            _available("First Payment", f"Model Month {funding.first_service_month}"),
            _available("First-Year Debt Service", format_currency(funding.first_year_service)),
        ]
    )
    if event.bridge is not None:
        metrics.append(
            _available(
                _DIRECTION_HEADINGS[event.bridge.direction],
                _magnitude(event.bridge.net_event_cash),
                note=_DIRECTION_LABELS[event.bridge.direction],
            )
        )
    return tuple(metrics)


def _dependency_disclosures(event: RefinanceResult, names: RefinanceNames) -> list[MemoReportDisclosure]:
    """The valuation dependency only where LTV applies, and the forward-NOI
    dependency only where DSCR applies (R-C)."""

    found: list[MemoReportDisclosure] = []
    scope = scope_name(event.scope, names.units)
    value = event.value_dependency
    if value is not None:
        label = names.valuations.get(value.timepoint_id, "the referenced valuation")
        supplied = " (Analyst-Supplied Value)" if value.analyst_supplied else ""
        found.append(
            MemoReportDisclosure(
                title=f"Valuation dependency – {event.label}",
                detail=(
                    f"The maximum LTV is measured against “{label}”{supplied} for {scope} at the end of Year "
                    f"{event.hold_year}: {_money(value.value)}."
                    if value.value is not None
                    else f"The maximum LTV is measured against “{label}” for {scope}, which has no value in this "
                    "analysis. It is never read as zero or replaced by the purchase price."
                ),
            )
        )
    noi = event.noi_dependency
    if noi is not None:
        found.append(
            MemoReportDisclosure(
                title=f"Forward NOI dependency – {event.label}",
                detail=(
                    f"The minimum DSCR is sized on Year {noi.forward_year} forward NOI of {scope}: "
                    f"{_money(noi.forward_noi)}. {DSCR_BASIS}"
                ),
            )
        )
    reason = event_reason_sentence(event, unit_names=names.units, valuation_labels=names.valuations)
    if reason is not None:
        found.append(
            MemoReportDisclosure(title=f"{_STATUS_LABELS[event.status]} – {event.label}", detail=reason)
        )
    return found


def _common_equity_table(structured: Any) -> MemoReportTable | None:
    common = structured.result.common_equity
    total = common.cash_flows
    recurring = getattr(common, "recurring_cash_flows", None)
    event_cash = getattr(common, "event_cash_flows", None)
    if total is None or recurring is None or event_cash is None:
        return None
    rows = tuple(
        (_period_label(index), format_currency(recurring[index]), format_currency(event_cash[index]), format_currency(value))
        for index, value in enumerate(total)
    )
    return MemoReportTable(
        caption="Common Equity Cash Flow",
        headers=("Year", "Recurring Common Equity Cash", "Refinance Event Cash", "Total Common Equity Cash"),
        rows=rows,
        align_right=(1, 2, 3),
        note=(
            "Refinance cash is shown apart from recurring Common Equity cash in its year. Common Equity returns are "
            "measured on the total."
        ),
    )


def refinance_section(
    analysis: Any, selected: SelectedDecision, names: RefinanceNames, economics: Any
) -> MemoReportSection:
    """The Refinance section of a refinance-bearing report."""

    structured = analysis.structured
    events = _events(structured)
    metrics: list[MemoReportMetric] = []
    tables: list[MemoReportTable] = []
    disclosures: list[MemoReportDisclosure] = []
    for event in events:
        metrics.extend(_event_metrics(event, names))
        sizing = _sizing_table(event, names)
        if sizing is not None:
            tables.append(sizing)
        tables.append(_bridge_table(event, names))
        disclosures.extend(_dependency_disclosures(event, names))

    common = _common_equity_table(structured)
    if common is not None:
        tables.append(common)
    missed = not_executed(structured.result)
    if missed:
        disclosures.append(
            MemoReportDisclosure(title="Common Equity", detail=common_equity_unavailable_sentence(missed))
        )

    reference = []
    if economics is not None:
        levered = getattr(economics, "levered_irr", None)
        multiple = getattr(economics, "equity_multiple", None)
        if levered is not None:
            reference.append(f"levered IRR {format_percent(levered)}")
        if multiple is not None:
            reference.append(f"equity multiple {format_multiple(multiple)}")
    disclosures.append(
        MemoReportDisclosure(
            title=ACQUISITION_REFERENCE_LABEL,
            detail=(
                "The acquisition-loan levered figures hold the acquisition loan to the sale and exclude every later "
                "capital event. They are a reference only, never this memo's refinance-adjusted return"
                + (f": {', '.join(reference)}." if reference else ".")
            ),
        )
    )
    if selected.scenario_id != BASE_SCENARIO_ID:
        disclosures.append(MemoReportDisclosure(title="Scenario rate changes", detail=SCENARIO_RATE_LIMITATION))

    primary = "Partner returns" if selected.perspective is DecisionPerspectiveKind.PARTNER else "Common Equity after Capital Structure"
    return MemoReportSection(
        title="Refinance",
        subtitle=(
            f"{primary} is the primary return of this memo. Every figure is Anchor's own engine result for the "
            "selected analysis."
        ),
        metrics=tuple(metrics),
        tables=tuple(tables),
        disclosures=tuple(disclosures),
    )


def refinance_unavailable_sentences(analysis: Any, *, db_path: Path | None) -> tuple[str, ...]:
    """Why each configured refinance of the selected cell did not execute, in
    the analyst's words -- the reasons publication states when it refuses a
    report whose primary return is unavailable."""

    structured = analysis.structured
    if structured is None or not refinance_bearing(structured):
        return ()
    names = names_for(analysis, db_path=db_path)
    return tuple(
        f"“{event.label}” did not execute: "
        + (
            event_reason_sentence(event, unit_names=names.units, valuation_labels=names.valuations)
            or "it has no result for this analysis."
        )
        for event in not_executed(structured.result)
    )


__all__ = [
    "REFINANCE_UNAVAILABLE_CODE",
    "RefinanceNames",
    "headline_returns",
    "names_for",
    "project_returns",
    "refinance_bearing",
    "refinance_section",
    "refinance_unavailable_sentences",
]
