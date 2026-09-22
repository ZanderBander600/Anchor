"""Phase 7 Gate P7.10 Stage 4 -- assembling one Investment Committee report.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 9, 12
and 13; that document governs on any discrepancy.

**This module selects; it never calculates.** Every amount, rate, return,
valuation, availability state and fingerprint it places in a report is read from
an accepted contract -- ``AcquisitionResults``, ``ConsolidatedResults``,
``StructuredCapitalResult``, ``StructuredValuationSurface``, the Stage 2
``InvestmentMemoVersion`` -- and converted to display text exactly once, through
``anchor.formatting``. There is no arithmetic here, no aggregate, no ordering by
value and no re-derivation. A figure Anchor does not already publish is reported
unavailable rather than computed.

**Where the numbers come from (Stage 4 §9).** A published version freezes its
memo content, its evidence, its claim-to-evidence links, its selected decision
and the valuation views it selected or consumed -- *with their values and their
typed unavailable reasons*. It does not freeze the returns, the Capital
Structure or the Partnership; it freezes their **fingerprints**. So those are
recomputed from the recorded selected cell, which is exactly what the contract
calls the version's "accepted deterministic dependencies", and the freshness
check then says whether those dependencies still match what was recorded.

**A stale version still exports, and says so.** Section 9 permits reopening and
exporting a stale version and forbids presenting one as current. A stale package
therefore carries ``ReportFreshness.STALE``, the classes that moved, and a
disclosure per class; the renderer watermarks every page. Nothing about the
frozen version is rewritten -- history is described, never edited.

**A draft preview is not a memo.** ``assemble_draft_preview`` reads the one
mutable draft so an analyst can see the report taking shape. It is marked
``DRAFT_PREVIEW`` at the contract level, and ``render_memo_pdf`` is the only
consumer that can turn a package into a file -- the export route refuses a draft
before reaching it, and a test proves both doors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..analysis.strategy import BASE_SCENARIO_ID, BASE_STRATEGY_ID
from ..deals import store
from ..deals.structured_variants import StructuredVariantConflictError, analyze_structured_valuations
from ..formatting import format_currency, format_multiple, format_percent
from ..memo.contracts import (
    DecisionPerspectiveKind,
    InvestmentMemoDraft,
    InvestmentMemoVersion,
    MemoEvidenceReference,
    MemoItem,
    MemoRiskItem,
    MemoSection,
    MemoTermItem,
    SelectedDecision,
)
from .artifact import REPORT_SNAPSHOT_NOT_AVAILABLE_MESSAGE
from .contracts import (
    MemoReportDisclosure,
    MemoReportEvidenceEntry,
    MemoReportMetric,
    MemoReportNarrativeItem,
    MemoReportOrigin,
    MemoReportPackage,
    MemoReportSection,
    MemoReportTable,
    MemoReportValuation,
    ReportFreshness,
    ReportUnavailable,
)


class MemoReportError(RuntimeError):
    """A report that cannot be assembled at all. A programming error, never an
    analyst finding: an unavailable figure is a typed cell, not an exception."""


class PdfExportRefusalCode(StrEnum):
    """Why a PDF export is refused, as a stable wire token.

    Each is a refusal of *authority to export*, never a rendering failure:
    Stage 4 §9 requires a typed explanation rather than a generic error, and
    requires the final PDF to come from an immutable published version.
    """

    #: The caller asked to export the mutable draft. Section 9: no final PDF is
    #: ever generated from a draft. The draft preview is a separate surface.
    DRAFT_NOT_EXPORTABLE = "draft_not_exportable"
    #: The named published version does not exist on this Investment.
    VERSION_NOT_FOUND = "version_not_found"
    #: The version exists but its own recorded content cannot be assembled --
    #: a frozen selected decision naming a perspective the record does not
    #: carry. Reported rather than rendered around.
    VERSION_INCONSISTENT = "version_inconsistent"
    #: The version was published before schema 16, so no report or PDF was
    #: stored with it. A historical condition rather than a fault, and
    #: deliberately not repaired by recomputing today's numbers.
    REPORT_SNAPSHOT_NOT_AVAILABLE = "report_snapshot_not_available"


class PdfExportRefusedError(Exception):
    """A typed refusal to export (Stage 4 §9).

    Carries the code, an analyst-facing message and the version concerned, so
    the API can report a structured refusal and the product can say why rather
    than showing a failed download.
    """

    def __init__(self, code: PdfExportRefusalCode, message: str, *, version_id: str | None = None):
        self.code = code
        self.message = message
        self.version_id = version_id
        super().__init__(message)


# =============================================================================
# Display vocabulary
#
# Professional analyst-facing wording for every stored token. Section 2 of the
# Stage 4 brief forbids exposing enum names, internal ids, fingerprints and
# database vocabulary in normal analyst views, so every token is translated
# here and nothing falls through to its raw value.
# =============================================================================

_RECOMMENDATION_LABELS = {
    "approve": "Approve",
    "approve_with_conditions": "Approve with Conditions",
    "revise_and_resubmit": "Revise and Resubmit",
    "decline": "Decline",
    "insufficient_information": "Insufficient Information",
}

_COMMITTEE_LABELS = {
    "pending": "Pending",
    "approved": "Approved",
    "approved_with_conditions": "Approved with Conditions",
    "deferred": "Deferred",
    "declined": "Declined",
}

_COMPLEXITY_LABELS = {
    "low": "Low",
    "moderate": "Moderate",
    "high": "High",
    "not_assessed": "Not Assessed",
}

_SEVERITY_LABELS = dict(_COMPLEXITY_LABELS)

_PRIORITY_LABELS = {
    "required": "Required",
    "desired": "Desired",
    "negotiable": "Negotiable",
}

_EVIDENCE_KIND_LABELS = {
    "case_document": "Case Document",
    "rent_comp": "Rent Comparable",
    "sales_comp": "Sales Comparable",
    "broker_research": "Broker Research",
    "analyst_assumption": "Analyst Assumption",
    "imported_model": "Imported Model",
    "ai_extracted_approved": "Extracted, Analyst Approved",
    "other": "Other",
}

_VALUATION_KIND_LABELS = {
    "as_is": "As-Is",
    "stabilized": "Stabilized",
    "custom": "Custom",
    "exit": "Exit",
}

_SCOPE_LABELS = {"unit": "Unit", "investment": "Investment"}

_ASSET_TYPE_LABELS = {
    "multifamily": "Multifamily",
    "office": "Office",
    "retail": "Retail",
    "industrial": "Industrial",
    "hospitality": "Hospitality",
    "self_storage": "Self Storage",
    "mixed_use": "Mixed Use",
    "other": "Other",
}

#: Analyst-facing sentences for every typed unavailable reason.
#:
#: The Stage 2 adapter's own ``reason`` is a precise developer-facing sentence
#: that names the Investment, the Unit and the timepoint by their opaque ids --
#: exactly right for a log or a test, and exactly what Section 2 keeps out of an
#: analyst view. The stable thing is the ``reason_code``, so Stage 4 translates
#: that and never repeats the raw message.
#:
#: Nothing is softened in the translation: each sentence says the same thing the
#: code means, including that there is no value. Where the affected scope
#: matters it travels separately, as a label the reader already knows.
_UNAVAILABLE_LABELS = {
    "not_authored": "No valuation is authored at this timepoint.",
    "incomplete_units": (
        "At least one Unit has no value at this timepoint, so the Investment has none. "
        "A partial sum of the Units that do have one is never the Investment value."
    ),
    "non_positive_forward_noi": (
        "Forward NOI is not positive at this timepoint, so direct capitalization has no "
        "meaning here. The NOI is not floored, smoothed or substituted."
    ),
    "evidence_not_approved": (
        "The analyst-supplied value rests on a source that has not been approved, so no "
        "value is reported."
    ),
    "variant_invalid": "The selected Strategy and Scenario did not resolve.",
    "funding_requirement_unresolved": (
        "A value-sized funding could not be sized, so this figure is not reported."
    ),
    "result_unavailable": "Anchor did not report this figure for the selected analysis.",
    "stale_dependency": "This figure rests on state that has changed since publication.",
    "not_implemented_for_scope": "Unavailable – Not Implemented for This Scope.",
    "reserved_exit_month": (
        "This timepoint falls at the exit month, whose value is the system-derived Exit "
        "view rather than an authored valuation."
    ),
    "outside_hold_horizon": (
        "This timepoint falls beyond the selected analysis's hold period. The same "
        "definition may resolve under a longer hold."
    ),
    "unit_not_in_variant": "This valuation names a Unit the selected analysis does not hold.",
    "unit_not_valued": "The selected analysis holds a Unit this valuation does not instruct.",
}


def _unavailable_reason(reason_code: str | None, fallback: str) -> str:
    """One unavailable state as analyst-facing text.

    Falls back to the backend's own sentence only for a code no later gate has
    taught this table, which a guard forbids shipping; it is here so an unknown
    state degrades to something true rather than to silence."""

    if reason_code is None:
        return fallback
    return _UNAVAILABLE_LABELS.get(reason_code, fallback)


#: Analyst-facing names for the thirteen Stage 2 dependency classes. A stale
#: report says "the Business Plan changed", never ``business_plan``.
_DEPENDENCY_LABELS = {
    "investment_membership": "Investment membership",
    "underwriting": "Unit underwriting",
    "business_plan": "Business Plan",
    "strategy": "Strategy definition",
    "scenario": "Scenario definition",
    "project_variant": "Project analysis",
    "capital_structure": "Capital Structure",
    "partnership": "Partnership",
    "valuation_definitions": "Valuation definitions",
    "valuation_results": "Valuation results",
    "decision_perspective": "Decision perspective",
    "evidence": "Evidence",
    "memo_content": "Memo content",
}

_SECTION_TITLES = {
    MemoSection.THESIS: "Investment Thesis",
    MemoSection.STRUCTURAL_PROTECTION: "Structural Protections",
    MemoSection.REPUTATIONAL_CONCERN: "Reputational Concerns",
    MemoSection.DEALBREAKER: "Dealbreakers",
    MemoSection.CONDITION_TO_APPROVAL: "Conditions to Approval",
    MemoSection.BUSINESS_PLAN_MILESTONE: "Business Plan",
}

#: The order narrative sections are printed in. Thesis leads because it is the
#: argument; dealbreakers follow the risks they belong beside.
_SECTION_ORDER = (
    MemoSection.THESIS,
    MemoSection.BUSINESS_PLAN_MILESTONE,
    MemoSection.STRUCTURAL_PROTECTION,
    MemoSection.REPUTATIONAL_CONCERN,
    MemoSection.DEALBREAKER,
    MemoSection.CONDITION_TO_APPROVAL,
)


def _label(table: dict[str, str], token: Any, fallback: str = "") -> str:
    """One stored token as analyst-facing text.

    Falls back to the token's own value only when a later gate adds a member
    this table has not been taught, which a guard forbids shipping; it is here
    so an unknown token degrades to something readable rather than raising
    inside a report.
    """

    key = getattr(token, "value", token)
    if key is None:
        return fallback
    return table.get(str(key), str(key).replace("_", " ").title())


# =============================================================================
# Cells
#
# Every figure enters a report through one of these. Each takes a backend value
# that may be ``None`` and produces either formatted text or a typed
# unavailable -- never ``$0``, never a blank, and never both.
# =============================================================================


def _unavailable(reason_code: str, reason: str, label: str = "Unavailable") -> ReportUnavailable:
    return ReportUnavailable(reason_code=reason_code, reason=reason, label=label)


_NOT_REPORTED = _unavailable(
    "result_unavailable",
    "Anchor did not report this figure for the selected analysis.",
)


def _metric(
    label: str,
    value: str | None,
    *,
    note: str | None = None,
    unavailable: ReportUnavailable | None = None,
) -> MemoReportMetric:
    """One metric cell. ``value is None`` becomes a typed unavailable, so a
    caller cannot accidentally emit an empty figure that reads as zero."""

    if value is None:
        return MemoReportMetric(
            label=label, unavailable=unavailable or _NOT_REPORTED, note=note
        )
    return MemoReportMetric(label=label, value=value, note=note)


def _currency(label: str, value: float | None, *, note: str | None = None) -> MemoReportMetric:
    return _metric(label, None if value is None else format_currency(value), note=note)


def _percent(
    label: str, value: float | None, *, decimals: int = 2, note: str | None = None
) -> MemoReportMetric:
    return _metric(
        label, None if value is None else format_percent(value, decimals), note=note
    )


def _multiple(label: str, value: float | None, *, note: str | None = None) -> MemoReportMetric:
    return _metric(label, None if value is None else format_multiple(value), note=note)


def _cell(value: str | None, unavailable_label: str = "Unavailable") -> str:
    """One table cell. ``None`` prints the unavailable label, never ``$0``."""

    return unavailable_label if value is None else value


def _currency_cell(value: float | None) -> str:
    return _cell(None if value is None else format_currency(value))


def _percent_cell(value: float | None, decimals: int = 2) -> str:
    return _cell(None if value is None else format_percent(value, decimals))


def _multiple_cell(value: float | None) -> str:
    return _cell(None if value is None else format_multiple(value))


# =============================================================================
# The resolved analysis behind a report
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class _Analysis:
    """What the selected cell currently resolves to, or why it does not.

    ``resolved`` is ``False`` when the variant, its Capital Structure or its
    Partnership could not be analysed. The package is still assembled: a report
    whose numbers are unavailable states that, section by section, rather than
    failing to describe the memo at all. That is the same rule
    ``MemoDependencySet`` follows for the dependency ledger.
    """

    resolved: bool
    #: Why it did not resolve, **for this module only**. It is a backend
    #: sentence and it names opaque ids, so it is never rendered: browser QA
    #: found one of these in a report's Disclosures, which is exactly the
    #: implementation vocabulary Section 2 keeps out of an analyst view. The
    #: disclosure below says the same thing in the analyst's terms instead.
    detail: str = ""
    project: Any = None
    consolidated: Any = None
    structured: Any = None
    surface: Any = None
    #: The resolved Partnership variant, where this Investment states a
    #: Partnership. **Added after browser QA at the independent review**: the
    #: Partnership is analysed by its own variant, not by the structured one,
    #: and reading it off ``structured.result`` -- which has no such field --
    #: silently made every Partner-perspective memo report no partner returns
    #: at all, under a disclosure saying the Investment had no Partnership.
    partnership: Any = None
    hold_period: int | None = None
    #: The acquisition price this analysis ran against, read from where the
    #: analyst stored it. ``None`` where it could not be read at all, which is
    #: reported as unavailable rather than substituted.
    purchase_price: float | None = None


def _project_economics(results: Any) -> Any:
    """The Project ``AcquisitionResults`` inside any mode's envelope.

    Selects a field and computes nothing -- the same selection
    ``anchor.deals.structured_variants`` makes for the valuation seam, made here
    rather than imported because that one is private to its module.
    """

    inner = getattr(results, "results", None)
    return results if inner is None else inner


def _analysis_for(
    investment_id: str, selected: SelectedDecision, db_path: Path | None
) -> _Analysis:
    """Run the selected cell, or record why it does not run.

    Every refusal the analysis layers raise is caught and turned into an
    unresolved ``_Analysis``: an invalid Strategy, Scenario, lease or Investment
    variant, an unexecutable Capital Structure. A ``StructuredVariantConflict``
    is deliberately **not** caught -- the saved underwriting moved while the
    report was being assembled, and reporting figures from two different states
    would be worse than asking for the report again.
    """

    from ..deals.structured_variants import analyze_structured_variant

    try:
        structured = analyze_structured_variant(
            investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
        )
        surface = analyze_structured_valuations(
            investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
        )
    except StructuredVariantConflictError:
        raise
    except Exception as error:  # noqa: BLE001 -- every layer's typed refusal
        return _Analysis(resolved=False, detail=str(error) or type(error).__name__)

    from ..deals.partnership_variants import analyze_partnership_variant

    try:
        partnership = analyze_partnership_variant(
            investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
        )
    except StructuredVariantConflictError:
        raise
    except Exception:  # noqa: BLE001 -- an Investment with no Partnership, or one
        # whose Partnership cannot run over this Common Equity Cash Flow. Both
        # are absences the disclosures below state; neither is a report failure.
        partnership = None

    investment = store.get_investment(investment_id, db_path=db_path)
    try:
        if investment.hidden:
            from ..deals.variants import analyze_variant

            variant = analyze_variant(
                investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
            )
            project = _project_economics(variant.results)
            consolidated = None
            source = variant.source_fingerprint
        else:
            from ..deals.investment_variants import analyze_investment_variant

            variant = analyze_investment_variant(
                investment_id, selected.strategy_id, selected.scenario_id, db_path=db_path
            )
            project = None
            consolidated = variant.consolidated_results
            source = variant.source_fingerprint
    except StructuredVariantConflictError:
        raise
    except Exception as error:  # noqa: BLE001
        return _Analysis(
            resolved=False,
            detail=str(error) or type(error).__name__,
            structured=structured,
            surface=surface,
            partnership=partnership,
        )

    if source != structured.project_source_fingerprint:
        raise StructuredVariantConflictError(
            "The saved underwriting changed while the report was being assembled. "
            "Open the report again."
        )

    return _Analysis(
        resolved=True,
        project=project,
        consolidated=consolidated,
        structured=structured,
        surface=surface,
        partnership=partnership,
        hold_period=structured.hold_period,
        purchase_price=_acquisition_price(investment_id, db_path),
    )


def _acquisition_price(investment_id: str, db_path: Path | None) -> float | None:
    """The transaction's acquisition price, read from where the analyst stored
    it.

    A visible Investment states its own ``transaction_price``. A hidden one-unit
    wrapper does not -- it is not a visible Investment -- so its Unit's stored
    purchase price is read from the Deal, exactly as the Deal library and the
    sidebar already read it: ``inputs`` for a Quick Unit and ``terms`` for every
    other mode, never one substituted for the other.

    This is a *stored analyst input*, selected and not derived. It is
    deliberately not ``total_closing_uses``, which is a different figure: uses
    include acquisition costs, financing fees and closing project capital, and
    labelling that sum "Purchase Price" would put a number on the cover of a
    memorandum under a name that is not its own. Where neither source can be
    read the figure is reported unavailable.
    """

    investment = store.get_investment(investment_id, db_path=db_path)
    if not investment.hidden:
        return store.get_visible_investment(
            investment_id, db_path=db_path
        ).transaction_price

    units = sorted(unit.unit_id for unit in investment.units)
    if not units:
        return None
    deal = store.get_deal(units[0], db_path=db_path)
    if deal.inputs is not None:
        return deal.inputs.purchase_price
    if deal.terms is not None:
        return deal.terms.purchase_price
    return None


def analysis_for_selected_cell(
    investment_id: str, selected: SelectedDecision, *, db_path: Path | None = None
) -> _Analysis:
    """The resolved state one report is assembled from.

    Public so the publication path can resolve the cell **once** and hand the
    same instant to both the prerequisite checks and the report. Two separate
    resolutions could disagree, and a document that disagreed with the checks
    that permitted it would be exactly the drift this gate exists to prevent.
    """

    return _analysis_for(investment_id, selected, db_path)


def _economics(analysis: _Analysis) -> Any:
    """The one result contract the headline figures are read from: the
    consolidated economics of a visible Investment, or the single Unit's own."""

    return analysis.consolidated if analysis.consolidated is not None else analysis.project


# =============================================================================
# Identity
# =============================================================================


def _investment_identity(investment_id: str, db_path: Path | None) -> tuple[str, str | None]:
    """The Investment's analyst-facing name and asset classification.

    A hidden one-unit wrapper has no name of its own -- it is not a visible
    Investment -- so its Unit's Deal name is used, which is the name the analyst
    has always seen for it. The classification is the Deal's, because Anchor
    records classification on the Deal; where the Units disagree the Investment
    reports none rather than picking one.

    **Anchor stores no market or location.** The concept's location line and
    market panel have no authoritative source in this product, so they are
    omitted entirely rather than invented (Stage 4 §8: never invent market
    statistics or demographic information).
    """

    investment = store.get_investment(investment_id, db_path=db_path)
    unit_ids = sorted(unit.unit_id for unit in investment.units)
    deals = [store.get_deal(unit_id, db_path=db_path) for unit_id in unit_ids]

    if investment.hidden:
        name = deals[0].name if deals else investment_id
    else:
        name = store.get_visible_investment(investment_id, db_path=db_path).name

    classifications = {
        _classification_text(deal) for deal in deals if deal.asset_type is not None
    }
    asset_type = classifications.pop() if len(classifications) == 1 else None
    return name, asset_type


def _classification_text(deal: Any) -> str:
    kind = _label(_ASSET_TYPE_LABELS, deal.asset_type)
    subtype = getattr(deal, "asset_subtype", None)
    # An en dash, not "--": this string is rendered to a reader, and the
    # double hyphen this file uses in *comments* would appear literally on the
    # page and in the PDF.
    return f"{kind} – {subtype}" if subtype else kind


def _strategy_label(investment_id: str, strategy_id: str, db_path: Path | None) -> str:
    """The Strategy's authored name, or the reserved Base label.

    Never the stored id: Section 2 of the Stage 4 brief forbids internal ids in
    normal analyst views, and a Strategy the analyst deleted is described as
    deleted rather than printed as an opaque key.
    """

    if strategy_id == BASE_STRATEGY_ID:
        return "Base Strategy"
    try:
        return store.get_strategy(investment_id, strategy_id, db_path=db_path).strategy.name
    except Exception:  # noqa: BLE001 -- a deleted Strategy is a stale condition
        return "Strategy no longer defined"


def _scenario_label(investment_id: str, scenario_id: str, db_path: Path | None) -> str:
    if scenario_id == BASE_SCENARIO_ID:
        return "Base Scenario"
    try:
        return store.get_scenario(investment_id, scenario_id, db_path=db_path).scenario.name
    except Exception:  # noqa: BLE001
        return "Scenario no longer defined"


def _perspective_label(selected: SelectedDecision, analysis: _Analysis) -> str:
    """Which stakeholder's returns the recommendation is made from.

    A position or partner is named by the name its own contract carries, so the
    report says "Senior Debt" rather than the opaque id the memo stored.
    """

    if selected.perspective is DecisionPerspectiveKind.PROJECT:
        return "Project"
    if selected.perspective is DecisionPerspectiveKind.POSITION:
        return f"Position – {_position_name(analysis, selected.position_id)}"
    return f"Partner – {_partner_name(analysis, selected.partner_id)}"


def _position_name(analysis: _Analysis, position_id: str | None) -> str:
    if position_id is None:
        return "Unnamed position"
    structured = analysis.structured
    if structured is not None:
        for position in structured.result.positions:
            if position.position_id == position_id:
                return position.name
    return "Position no longer defined"


def _partner_name(analysis: _Analysis, partner_id: str | None) -> str:
    """The selected Partner, by the name its own Partnership carries.

    P-8 makes ``partner_id`` the partner's stable identity while its name is
    presentation, exactly as a position's is -- so the report says "LP", like it
    says "Senior Loan", and not the token the memo stored. **Corrected after
    browser QA at the independent review**, which showed a cover reading
    "Partner – lp": the id was being printed on the reasoning that the contract
    had no name, and it does.

    The id is the fallback rather than an invention, for a Partnership that no
    longer resolves; it is at least a token the analyst chose."""

    if partner_id is None:
        return "Unnamed partner"
    resolved = analysis.partnership
    stated = None if resolved is None else getattr(resolved, "partnership", None)
    for partner in getattr(stated, "partners", ()) or ():
        if getattr(partner, "partner_id", None) == partner_id:
            name = getattr(partner, "name", None)
            return name if name else partner_id
    return partner_id


# =============================================================================
# Key decision metrics
# =============================================================================


def _key_metrics(analysis: _Analysis) -> tuple[MemoReportMetric, ...]:
    """The headline figures of the decision page (Section 13.1).

    Every one is a named field of an accepted result contract, selected and
    formatted. Nothing is derived: the concept's "Price / Unit" is deliberately
    absent because no backend field publishes it, and dividing a price by a Unit
    count here would be the frontend total this gate exists to prevent.

    They are "key decision metrics, not asset-type-specific benchmarks"
    (Section 13.1): the same nine figures whatever the asset type, because
    Anchor has no asset-type-specific underwriting (Section 3.2).
    """

    economics = _economics(analysis)
    if economics is None:
        return ()

    noi_by_year = getattr(economics, "noi_by_year", ())
    dscr = getattr(economics, "headline_aggregate_dscr", None)
    if dscr is None:
        dscr = getattr(economics, "headline_dscr", None)

    return (
        _currency("Purchase Price", analysis.purchase_price),
        _percent("Going-in Cap Rate", getattr(economics, "going_in_cap_rate", None)),
        _currency("Year 1 NOI", noi_by_year[0] if noi_by_year else None),
        _metric(
            "Hold Period",
            None if analysis.hold_period is None else f"{analysis.hold_period} Years",
        ),
        _currency("Exit Value", getattr(economics, "exit_value", None)),
        _currency("Initial Equity", getattr(economics, "initial_equity", None)),
        _percent("Levered IRR", getattr(economics, "levered_irr", None)),
        _multiple("Equity Multiple", getattr(economics, "equity_multiple", None)),
        _multiple("DSCR (Year 1)", dscr),
    )


# =============================================================================
# Valuation views (Sections 5, 13.2)
# =============================================================================


def _timing_label(model_month: int, hold_period: int | None) -> str:
    """When a valuation is struck, in analyst words rather than a model month.

    Month 0 is closing. Every other storable month is a hold-year end, and the
    exit month is the reserved system view. The label states the month it came
    from so nothing is hidden, but leads with the meaning.
    """

    if model_month == 0:
        return "At closing"
    if hold_period is not None and model_month == hold_period * 12:
        return f"At exit (end of Year {hold_period})"
    return f"End of Year {model_month // 12}"


def _valuation_from_view(
    view: Any, *, selected: bool, consumed: bool, hold_period: int | None
) -> MemoReportValuation:
    """One resolved valuation view as the report presents it.

    An unavailable view keeps the backend's own reason code and sentence. Its
    ``value`` stays ``None``, so no renderer can print it as ``$0``, as the
    purchase price, or as another timepoint's value.
    """

    unavailable = getattr(view, "unavailable", None)
    analyst_supplied = any(
        getattr(unit, "analyst_supplied", False) for unit in getattr(view, "unit_views", ())
    )
    return MemoReportValuation(
        label=view.label,
        kind=_label(_VALUATION_KIND_LABELS, view.kind),
        timing=_timing_label(view.model_month, hold_period),
        scope=_label(_SCOPE_LABELS, view.scope_kind),
        value=None if view.value is None else format_currency(view.value),
        unavailable=(
            None
            if view.value is not None or unavailable is None
            else _unavailable(
                (code := str(getattr(unavailable, "reason_code", "result_unavailable"))),
                _unavailable_reason(
                    code,
                    str(getattr(unavailable, "reason", "")) or "No value at this timepoint.",
                ),
            )
        ),
        selected=selected,
        consumed=consumed,
        analyst_supplied=analyst_supplied,
    )


def _valuation_from_frozen(row: Any, hold_period: int | None) -> MemoReportValuation:
    """One valuation exactly as a published version froze it.

    Read from the version, never re-resolved: a version that recorded "no value
    at this timepoint" keeps saying so however the draft has since moved, which
    is what makes republishing the only way to change what a memo asserts.
    """

    return MemoReportValuation(
        label=row.label,
        kind=_label(_VALUATION_KIND_LABELS, row.kind),
        timing=_timing_label(row.model_month, hold_period),
        scope=_label(_SCOPE_LABELS, row.scope_kind),
        value=None if row.value is None else format_currency(row.value),
        unavailable=(
            None
            if row.value is not None
            else _unavailable(
                row.unavailable_reason or "result_unavailable",
                _unavailable_reason(
                    row.unavailable_reason,
                    row.unavailable_message or "No value at this timepoint.",
                ),
            )
        ),
        selected=row.selected,
        consumed=row.consumed,
    )


def _exit_view(analysis: _Analysis) -> MemoReportValuation | None:
    """The reserved system Exit view (R-B).

    It is the existing D6 terminal result read unchanged -- there is no second
    exit calculation and no analyst-editable Exit method -- so it is always
    marked system-controlled and can never be selected or consumed.
    """

    economics = _economics(analysis)
    if economics is None or analysis.hold_period is None:
        return None
    exit_value = getattr(economics, "exit_value", None)
    return MemoReportValuation(
        label="Exit Value",
        kind="Exit",
        timing=_exit_timing(analysis.hold_period),
        scope="Investment" if analysis.consolidated is not None else "Unit",
        value=None if exit_value is None else format_currency(exit_value),
        unavailable=(
            None
            if exit_value is not None
            else _unavailable(
                "result_unavailable",
                "The selected analysis reported no exit value.",
            )
        ),
        system_controlled=True,
    )


def _exit_timing(hold_period: int) -> str:
    """When the reserved Exit view is struck, stated without arithmetic: the
    end of the final hold year, which is what the exit month means."""

    return f"At exit (end of Year {hold_period})"


# =============================================================================
# Capital structure and returns (Sections 13.1, 13.2)
# =============================================================================


def _sources_and_uses(analysis: _Analysis) -> MemoReportTable | None:
    """Sources & Uses at closing, read from the accepted result contract.

    Every line is a published field. ``total_closing_uses`` and
    ``total_closing_sources`` are the engine's own totals, printed as they are
    -- this table never adds its own rows up, which is why the two totals can
    honestly be shown side by side.
    """

    economics = _economics(analysis)
    if economics is None:
        return None

    rows: list[tuple[str, ...]] = []
    for label, attribute in (
        ("Purchase Price", "allocated_purchase_price"),
        ("Acquisition Costs", "acquisition_costs"),
        ("Financing Fees", "financing_fees"),
        ("Financing Fee", "financing_fee"),
        ("Investment Transaction Costs", "investment_transaction_costs"),
        ("Closing Project Capital", "closing_project_capital"),
    ):
        value = getattr(economics, attribute, None)
        if value is not None:
            rows.append((label, format_currency(value)))
    rows.append(("Total Uses", _currency_cell(getattr(economics, "total_closing_uses", None))))
    rows.append(("Loan Amount", _currency_cell(getattr(economics, "loan_amount", None))))
    rows.append(("Initial Equity", _currency_cell(getattr(economics, "initial_equity", None))))
    rows.append(
        ("Total Sources", _currency_cell(getattr(economics, "total_closing_sources", None)))
    )

    total_rows = tuple(
        index for index, row in enumerate(rows) if row[0] in {"Total Uses", "Total Sources"}
    )
    return MemoReportTable(
        caption="Sources & Uses at Closing",
        headers=("Line", "Amount"),
        rows=tuple(rows),
        align_right=(1,),
        emphasize_rows=total_rows,
    )


def _capital_positions(analysis: _Analysis) -> MemoReportTable | None:
    """Each authored capital position, in the executor's own economic order.

    A position whose returns are unavailable keeps its structural facts -- its
    funded amount, its attachment and detachment -- and reports N/A with its
    reason for the returns it does not have. Section 16 is explicit that N/A,
    Unavailable and Stale are different statements, and a blocked position is
    not a position that returned nothing.
    """

    structured = analysis.structured
    if structured is None or not structured.result.positions:
        return None

    rows = tuple(
        (
            position.name,
            _label({}, getattr(position, "position_class", None), "Position"),
            _currency_cell(getattr(position, "funded_amount", None)),
            _percent_cell(position.irr) if position.irr is not None else _position_na(position),
            _multiple_cell(getattr(position, "moic", None)),
            _percent_cell(getattr(position, "detachment_ltv", None)),
        )
        for position in structured.result.positions
    )
    return MemoReportTable(
        caption="Capital Positions",
        headers=("Position", "Class", "Funded", "IRR", "MOIC", "Detachment LTV"),
        rows=rows,
        align_right=(2, 3, 4, 5),
    )


def _position_na(position: Any) -> str:
    """A position's returns cell when it has none.

    Prints ``N/A`` with the executor's own reason rather than a blank: P-9
    reports an unresolved or senior-blocked position as N/A with its reason, and
    a blank cell in a returns column reads as zero.
    """

    reason = getattr(position, "unavailable_reason", None)
    if reason is None:
        return "N/A"
    readable = str(getattr(reason, "value", reason)).replace("_", " ")
    return f"N/A – {readable}"


def _debt_terms_table(analysis: _Analysis) -> MemoReportTable | None:
    """The debt terms of each position that states them."""

    structured = analysis.structured
    if structured is None:
        return None

    rows: list[tuple[str, ...]] = []
    for position in structured.result.positions:
        terms = getattr(position, "terms", None)
        rate = getattr(terms, "interest_rate", None)
        if terms is None or rate is None:
            continue
        amortization = getattr(terms, "amortization", None)
        io_period = getattr(terms, "io_period", None)
        rows.append(
            (
                position.name,
                _percent_cell(rate),
                "N/A" if amortization is None else f"{amortization} years",
                "None" if not io_period else f"{io_period} months",
            )
        )
    if not rows:
        return None
    return MemoReportTable(
        caption="Debt Terms",
        headers=("Position", "Interest Rate", "Amortization", "Interest-Only"),
        rows=tuple(rows),
        align_right=(1, 2, 3),
    )


def _returns_metrics(
    analysis: _Analysis, selected: SelectedDecision
) -> tuple[MemoReportMetric, ...]:
    """The returns of the selected perspective, and only those.

    Project, Position and Partner perspectives stay distinct (Section 12): a
    memo written from a Position's perspective reports that position's IRR and
    MOIC, never the Project's relabelled as the position's.
    """

    if selected.perspective is DecisionPerspectiveKind.POSITION:
        return _position_returns(analysis, selected.position_id)
    if selected.perspective is DecisionPerspectiveKind.PARTNER:
        return _partner_returns(analysis, selected.partner_id)
    return _project_returns(analysis)


def _project_returns(analysis: _Analysis) -> tuple[MemoReportMetric, ...]:
    economics = _economics(analysis)
    if economics is None:
        return ()
    return (
        _percent("Unlevered IRR", getattr(economics, "unlevered_irr", None)),
        _percent("Levered IRR", getattr(economics, "levered_irr", None)),
        _multiple("Equity Multiple", getattr(economics, "equity_multiple", None)),
        _currency("Total Equity Invested", getattr(economics, "total_equity_invested", None)),
        _currency("Total Cash Returned", getattr(economics, "total_cash_returned", None)),
        _currency("Total Profit", getattr(economics, "total_profit", None)),
    )


def _position_returns(
    analysis: _Analysis, position_id: str | None
) -> tuple[MemoReportMetric, ...]:
    structured = analysis.structured
    if structured is None or position_id is None:
        return ()
    for position in structured.result.positions:
        if position.position_id != position_id:
            continue
        note = None if position.irr is not None else _position_na(position)
        return (
            _currency("Funded Amount", getattr(position, "funded_amount", None)),
            _percent("Position IRR", position.irr, note=note),
            _multiple("Position MOIC", getattr(position, "moic", None)),
            _currency("Total Cash Received", getattr(position, "total_cash_received", None)),
            _currency("Profit", getattr(position, "profit", None)),
        )
    return ()


def _partner_returns(analysis: _Analysis, partner_id: str | None) -> tuple[MemoReportMetric, ...]:
    """The selected Partner's returns, from the resolved Partnership variant.

    Reported only where the selected variant actually resolves a Partnership.
    FP-2 makes a Partnership absent rather than empty, so an Investment without
    one produces no partner metrics and the report discloses that instead of
    printing zeros.

    **Corrected after browser QA at the independent review.** This read a
    ``partnership`` attribute off the *structured capital* result, which has no
    such field, and named partner totals that the Partnership contract does not
    carry. Both failures were silent and pointed the same way: every
    Partner-perspective memo reported no partner returns at all, beneath a
    disclosure claiming the Investment resolved no Partnership. It is read from
    ``analyze_partnership_variant`` now -- the same analysis the Partnership
    surfaces use -- by the field names P7.9 actually defines.
    """

    resolved = analysis.partnership
    if resolved is None or partner_id is None:
        return ()
    result = getattr(resolved, "result", None)
    for partner in getattr(result, "partners", ()) or ():
        if getattr(partner, "partner_id", None) != partner_id:
            continue
        irr = getattr(partner, "irr", None)
        return (
            _currency("Capital Contributed", getattr(partner, "total_contributions", None)),
            _percent(
                "Partner IRR",
                irr,
                note=None if irr is not None else "Unavailable for this cash flow.",
            ),
            _multiple("Partner Multiple", getattr(partner, "moic", None)),
            _currency("Total Distributions", getattr(partner, "total_distributions", None)),
            _currency("Profit", getattr(partner, "profit", None)),
        )
    return ()


#: Hold-year labels for the series the report prints. Anchor's hold horizon is
#: bounded well below this; beyond it ``_year_label`` degrades readably.
_YEAR_LABELS = tuple(f"Year {number}" for number in range(1, 41))


def _year_label(index: int) -> str:
    """The hold year one series entry belongs to.

    ``enumerate`` counts from zero and the series are Years 1..H, so the label
    is read from a prepared sequence rather than by adding one to the index --
    the no-arithmetic rule applies to the report's own bookkeeping too, and a
    lookup makes the off-by-one impossible rather than merely correct today.
    """

    if index < len(_YEAR_LABELS):
        return _YEAR_LABELS[index]
    return "Later year"


def _series_cell(series: Any, index: int) -> str:
    """One entry of a parallel series, or ``N/A`` where that series is shorter
    or absent. Never zero: a series that does not reach this year has no value
    for it, which is a different statement from a year with no cash flow."""

    if not series or index >= len(series):
        return "N/A"
    value = series[index]
    return "N/A" if value is None else format_currency(value)


def _operating_projection(analysis: _Analysis) -> MemoReportTable | None:
    """NOI and owner cash flow by hold year, read from the accepted series.

    Both series are published fields indexed by hold year, so the table walks
    them in step and formats each entry. It sums nothing and derives no growth
    rate: a year-over-year change would be an attribution Section 5.6 reserves
    for a ratified backend decomposition.
    """

    economics = _economics(analysis)
    if economics is None:
        return None
    noi = getattr(economics, "noi_by_year", ())
    if not noi:
        return None
    levered = getattr(economics, "levered_owner_cash_flow_by_year", ())
    debt_service = getattr(economics, "annual_debt_service", ())

    rows: list[tuple[str, ...]] = []
    for index, value in enumerate(noi):
        rows.append(
            (
                _year_label(index),
                format_currency(value),
                _series_cell(debt_service, index),
                _series_cell(levered, index),
            )
        )
    return MemoReportTable(
        caption="Operating Projection",
        headers=("Year", "NOI", "Debt Service", "Levered Owner Cash Flow"),
        rows=tuple(rows),
        align_right=(1, 2, 3),
    )


# =============================================================================
# Narrative, evidence and claim-level traceability (Section 8; R-G)
# =============================================================================


def _evidence_titles(
    evidence_ids: tuple[str, ...], library: dict[str, MemoEvidenceReference]
) -> tuple[str, ...]:
    """The titles of the sources one claim cites, in the analyst's own order.

    A cited id the library does not hold is named as a missing source rather
    than dropped: silently printing a claim with one fewer citation than the
    analyst attached would misrepresent what it rests on.
    """

    titles: list[str] = []
    for evidence_id in evidence_ids:
        found = library.get(evidence_id)
        titles.append("Source no longer available" if found is None else found.title)
    return tuple(titles)


def _narrative_item(
    text: str,
    evidence_ids: tuple[str, ...],
    library: dict[str, MemoEvidenceReference],
    *,
    detail: str | None = None,
    labels: tuple[str, ...] = (),
) -> MemoReportNarrativeItem:
    """One authored claim with its sources.

    ``sourced`` is ``True`` only when the claim actually cites something.
    Attaching a source never means Anchor verified it, and nothing in this
    function upgrades an unapproved reference: the register prints approval
    separately, and an uncited claim is labelled an analyst assertion.
    """

    titles = _evidence_titles(evidence_ids, library)
    return MemoReportNarrativeItem(
        text=text,
        detail=detail,
        labels=labels,
        evidence_labels=titles,
        sourced=bool(titles),
    )


def _ordered(items: Any) -> list[Any]:
    """Authored items in their explicit display order.

    ``display_order`` is the stored presentation order and ``item_id`` breaks a
    tie deterministically. This orders by an authored field, never by a value:
    ranking risks by severity or terms by amount would be a judgement the
    analyst did not make.
    """

    return sorted(items, key=lambda entry: (entry.display_order, entry.item_id))


def _narrative_sections(
    items: tuple[MemoItem, ...],
    risks: tuple[MemoRiskItem, ...],
    terms: tuple[MemoTermItem, ...],
    library: dict[str, MemoEvidenceReference],
) -> tuple[MemoReportSection, ...]:
    """The analyst's own sections, in report order.

    A section the analyst left empty is not emitted: Section 7.2 says an empty
    optional section stays absent and the report never manufactures boilerplate
    to fill it.
    """

    sections: list[MemoReportSection] = []

    for section in _SECTION_ORDER:
        authored = [item for item in _ordered(items) if item.section is section]
        if not authored:
            continue
        sections.append(
            MemoReportSection(
                title=_SECTION_TITLES[section],
                narrative=tuple(
                    _narrative_item(item.text, item.evidence_ids, library) for item in authored
                ),
            )
        )

    if risks:
        sections.append(
            MemoReportSection(
                title="Risks & Mitigants",
                subtitle=(
                    "Severity and residual risk are the analyst's own judgements. "
                    "A mitigant does not resolve a risk."
                ),
                narrative=tuple(
                    _narrative_item(
                        risk.text,
                        risk.evidence_ids,
                        library,
                        detail=risk.mitigant,
                        labels=(
                            f"Severity: {_label(_SEVERITY_LABELS, risk.severity)}",
                            f"Residual: {_label(_SEVERITY_LABELS, risk.residual_risk)}",
                        ),
                    )
                    for risk in _ordered(risks)
                ),
            )
        )

    if terms:
        sections.append(
            MemoReportSection(
                title="Terms",
                narrative=tuple(
                    _narrative_item(
                        term.text,
                        term.evidence_ids,
                        library,
                        labels=(_label(_PRIORITY_LABELS, term.priority),),
                    )
                    for term in _ordered(terms)
                ),
            )
        )

    return tuple(sections)


def _claim_citations(
    items: tuple[MemoItem, ...],
    risks: tuple[MemoRiskItem, ...],
    terms: tuple[MemoTermItem, ...],
) -> dict[str, list[str]]:
    """Which claims cite each source, by evidence id.

    The reverse of the per-claim links, so the source register can say what
    rests on each entry. A reader can then follow a citation in both directions,
    which is what makes the claim-to-source relationship unambiguous rather than
    merely present.
    """

    citations: dict[str, list[str]] = {}
    for collection in (_ordered(items), _ordered(risks), _ordered(terms)):
        for item in collection:
            for evidence_id in item.evidence_ids:
                citations.setdefault(evidence_id, []).append(_claim_excerpt(item.text))
    return citations


def _claim_excerpt(text: str) -> str:
    """A claim named short enough to sit in a register cell, cut on a word
    boundary rather than mid-word."""

    if len(text) <= _EXCERPT_LIMIT:
        return text
    head = text[:_EXCERPT_LIMIT].rsplit(" ", 1)[0]
    return f"{head}..."


_EXCERPT_LIMIT = 60


def _evidence_register(
    references: tuple[MemoEvidenceReference, ...],
    citations: dict[str, list[str]],
) -> tuple[MemoReportEvidenceEntry, ...]:
    """The source register, in the analyst's own display order.

    ``approved`` travels as its own field. Section 8 requires source status and
    approval status to stay distinct from the analyst's claim, and a register
    that printed only approved sources would hide exactly the rows a reviewer
    most needs to see.
    """

    return tuple(
        MemoReportEvidenceEntry(
            title=reference.title,
            source_kind=_label(_EVIDENCE_KIND_LABELS, reference.source_kind),
            reference=reference.reference,
            as_of_date=None if reference.as_of_date is None else reference.as_of_date.isoformat(),
            approved=reference.approved,
            cited_by=tuple(citations.get(reference.evidence_id, ())),
        )
        for reference in sorted(
            references, key=lambda entry: (entry.display_order, entry.evidence_id)
        )
    )


# =============================================================================
# Disclosures (Sections 12, 13.2, 16)
# =============================================================================


def _scope_disclosures(analysis: _Analysis, multi_unit: bool) -> tuple[MemoReportDisclosure, ...]:
    """What this report cannot say, said plainly.

    Ratified decision R-I fixes P7.10's decision-support reach: existing
    Decision Matrices and existing sensitivity/break-even results are reused,
    and Lease-Level break-even and Investment-level sensitivity/break-even are
    reported unavailable for the scope. P7.10 adds no solver, so the honest
    answer is this disclosure rather than a hidden section or a substitute
    figure.
    """

    disclosures: list[MemoReportDisclosure] = []

    if multi_unit:
        disclosures.append(
            MemoReportDisclosure(
                title="Sensitivity and break-even at Investment scope",
                detail=(
                    "Unavailable – Not Implemented for This Scope. Anchor provides "
                    "sensitivity and break-even on an individual Unit. No Unit result "
                    "is presented here as an Investment result."
                ),
                scope="Investment",
            )
        )

    # Corrected after browser QA at the independent review. This asked the
    # structured capital result for a ``partnership`` field it does not have, so
    # it was `None` for every Investment and this disclosure appeared on every
    # report -- including the ones that did resolve a Partnership, beside the
    # partner returns it said were absent. The Partnership variant is the thing
    # that knows, so it is what is asked.
    if analysis.structured is not None:
        resolved = analysis.partnership
        stated = None if resolved is None else getattr(resolved, "partnership", None)
        result = None if resolved is None else getattr(resolved, "result", None)
        if stated is None:
            disclosures.append(
                MemoReportDisclosure(
                    title="Partnership",
                    detail=(
                        "The selected analysis resolves no Partnership, so no partner "
                        "returns are reported. This is an absence, not a zero."
                    ),
                )
            )
        elif getattr(result, "partners", None) is None:
            # A Partnership is stated but could not be run over this Common
            # Equity Cash Flow. Its own typed reason says why; no partner figure
            # is estimated in its place.
            disclosures.append(
                MemoReportDisclosure(
                    title="Partnership",
                    detail=_unavailable_reason(
                        getattr(result, "unavailable_reason", None),
                        "The Partnership could not be run over this analysis, so no "
                        "partner returns are reported. This is an absence, not a zero.",
                    ),
                )
            )

    if not analysis.resolved:
        disclosures.append(
            MemoReportDisclosure(
                title="Selected analysis did not resolve",
                detail=(
                    "The selected Strategy, Scenario and perspective did not produce a "
                    "result, so no return, capital structure or partnership figure is "
                    "reported here. Every figure that does not depend on it is "
                    "unchanged, and nothing is estimated in its place."
                ),
            )
        )

    return tuple(disclosures)


def _position_label(analysis: _Analysis, position_id: str | None) -> str | None:
    """One capital position by the name its own contract carries.

    ``None`` when the disclosure names no position at all, so nothing is
    rendered; the honest absence when a position cannot be found, because a
    published document that prints a stored key tells its reader nothing and
    tells an auditor the wrong thing."""

    if position_id is None:
        return None
    structured = analysis.structured
    if structured is not None:
        for position in structured.result.positions:
            if position.position_id == position_id:
                return position.name
    return "Selected position (no longer available)"


def _funding_disclosures(analysis: _Analysis) -> tuple[MemoReportDisclosure, ...]:
    """Every value-sized funding that could not be sized, with its own reason.

    Section 6.2 requires an unresolved ``PctOfValue`` funding to reach the
    surface as a structured unavailable state carrying its specific reason and
    **no amount at all**. Nothing here invents one, and nothing collapses it to
    zero.
    """

    surface = analysis.surface
    if surface is None:
        return ()
    disclosures: list[MemoReportDisclosure] = []
    for state in getattr(surface, "funding_states", ()):
        unavailable = getattr(state, "unavailable", None)
        if unavailable is None:
            continue
        disclosures.append(
            MemoReportDisclosure(
                title="Value-sized funding could not be sized",
                detail=_unavailable_reason(
                    getattr(unavailable, "reason_code", None),
                    str(getattr(unavailable, "reason", "")) or "No value at this timepoint.",
                ),
                # Named, never the stored id: browser QA at the second
                # review found "senior" on a committee document where the
                # position's own name belongs (Correction 2).
                scope=_position_label(analysis, getattr(state, "position_id", None)),
            )
        )
    return tuple(disclosures)


def _published_date(recorded: str) -> str:
    """A stored publication timestamp as the date a committee reads.

    The store records a full ISO instant, which is exactly right for an
    identity and exactly wrong on a memorandum cover: a reader wants
    "21 September 2026", not "2026-09-22T00:49:40.295167+00:00". Formatted once
    here, so the workspace and the PDF cannot disagree about it.

    An unparseable value is returned as recorded rather than dropped -- a
    timestamp nobody can read is still better than a cover that lost its date.
    """

    try:
        return datetime.fromisoformat(recorded).strftime("%d %B %Y")
    except ValueError:
        return recorded


def _generated_at() -> str:
    """The generation timestamp, in UTC to the second.

    Printed on the PDF as Section 13.3 requires. It is the one field that
    legitimately differs between two exports of the same version, and it is
    deliberately not part of any identity.
    """

    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _sections_for(
    analysis: _Analysis,
    selected: SelectedDecision,
    narrative: tuple[MemoReportSection, ...],
    multi_unit: bool,
) -> tuple[MemoReportSection, ...]:
    """The report's sections, in reading order, with the empty ones dropped."""

    sections: list[MemoReportSection] = list(narrative)

    returns = _returns_metrics(analysis, selected)
    if returns:
        sections.append(
            MemoReportSection(
                title="Returns",
                subtitle=f"Reported from the {_perspective_label(selected, analysis)} perspective.",
                metrics=returns,
            )
        )

    capital_tables = tuple(
        table
        for table in (
            _sources_and_uses(analysis),
            _capital_positions(analysis),
            _debt_terms_table(analysis),
        )
        if table is not None
    )
    if capital_tables:
        sections.append(MemoReportSection(title="Capital Structure", tables=capital_tables))

    projection = _operating_projection(analysis)
    if projection is not None:
        sections.append(MemoReportSection(title="Operating Projection", tables=(projection,)))

    disclosures = _scope_disclosures(analysis, multi_unit) + _funding_disclosures(analysis)
    if disclosures:
        sections.append(
            MemoReportSection(
                title="Disclosures",
                subtitle="What this package does not report, and why.",
                disclosures=disclosures,
            )
        )

    return tuple(section for section in sections if not section.is_empty)


def _is_multi_unit(investment_id: str, db_path: Path | None) -> bool:
    investment = store.get_investment(investment_id, db_path=db_path)
    return not investment.hidden and len(investment.units) > 1


def build_version_package(
    investment_id: str,
    version: InvestmentMemoVersion,
    analysis: _Analysis,
    *,
    db_path: Path | None = None,
) -> MemoReportPackage:
    """Assemble one published version's report, once, at publication.

    **This runs exactly once per version** (Stage 4 Correction 1). Its output is
    serialized, rendered to PDF and stored beside the version in the same
    transaction, and every later read returns those stored bytes. Nothing calls
    this to *re-*produce a report for an existing version: a published decision
    document that could be regenerated from today's numbers would not be a
    record of what the committee read.

    ``analysis`` is the resolved state the publication prerequisites were
    checked against, passed in rather than recomputed here, so the document and
    the checks that let it exist describe the same instant.

    ``freshness`` is ``CURRENT`` by construction -- a report is current at the
    moment it is issued. Whether the analysis has moved *since* is a live
    question the Stage 2 freshness route answers, reported in the workspace
    beside this document and never written into it.
    """

    selected = version.selected_decision
    library = {reference.evidence_id: reference for reference in version.evidence}
    citations = _claim_citations(version.items, version.risk_items, version.term_items)
    name, asset_type = _investment_identity(investment_id, db_path)

    valuations = tuple(
        _valuation_from_frozen(row, analysis.hold_period) for row in version.valuations
    )
    exit_view = _exit_view(analysis)
    if exit_view is not None:
        valuations = valuations + (exit_view,)

    return MemoReportPackage(
        origin=MemoReportOrigin.PUBLISHED_VERSION,
        investment_id=investment_id,
        investment_name=name,
        asset_type=asset_type,
        market=None,
        version_number=version.version_number,
        version_id=version.version_id,
        published_at=_published_date(version.created_at),
        prepared_by=version.prepared_by,
        generated_at=_generated_at(),
        decision_ask=version.decision_ask,
        analyst_recommendation=_label(_RECOMMENDATION_LABELS, version.analyst_recommendation),
        # The committee decides *after* publication, so a freshly issued report
        # records no outcome. It is Section 10's reason for keeping the decision
        # off the published fingerprint, and the same reason keeps it out of the
        # frozen document: recording an outcome must not alter what was decided
        # on. The workspace shows the committee's decision beside the report.
        committee_decision=None,
        committee_note=None,
        executive_summary=version.executive_summary,
        strategy_label=_strategy_label(investment_id, selected.strategy_id, db_path),
        scenario_label=_scenario_label(investment_id, selected.scenario_id, db_path),
        perspective_label=_perspective_label(selected, analysis),
        freshness=ReportFreshness.CURRENT,
        verification_code=version.published_fingerprint,
        key_metrics=_key_metrics(analysis),
        valuations=valuations,
        sections=_sections_for(
            analysis,
            selected,
            _narrative_sections(
                version.items, version.risk_items, version.term_items, library
            ),
            _is_multi_unit(investment_id, db_path),
        ),
        evidence=_evidence_register(version.evidence, citations),
        concluding_statement=_concluding_statement(
            name,
            _label(_RECOMMENDATION_LABELS, version.analyst_recommendation),
        ),
    )


def read_version_report(
    investment_id: str, version_id: str, *, db_path: Path | None = None
) -> MemoReportPackage | None:
    """One published version's frozen report, exactly as it was issued.

    Reads the stored artifact and decodes it fail-closed. It recomputes nothing:
    changing the underwriting, the Strategy, the Scenario, the Capital
    Structure, the Partnership or a valuation definition after publication
    changes this not at all, and neither does editing the assembly code that
    produced it.

    ``None`` where the version has no artifact, which is the historical state of
    every version published before schema 16. The caller reports that as the
    typed ``REPORT_SNAPSHOT_NOT_AVAILABLE`` state; nothing reconstructs one from
    current inputs.
    """

    artifact = store.get_memo_version_artifact(investment_id, version_id, db_path=db_path)
    return None if artifact is None else artifact.package()


def assemble_draft_preview(
    investment_id: str, *, db_path: Path | None = None
) -> MemoReportPackage:
    """The mutable draft as a report preview.

    Marked ``DRAFT_PREVIEW`` so no surface can mistake it for a published memo
    and no export route will turn it into a final PDF. Its valuations are
    resolved live rather than read from a frozen row, because a draft has frozen
    nothing yet: what the analyst sees is the current state, which is the point
    of a preview.
    """

    draft = store.get_memo_draft(investment_id, db_path=db_path)
    if draft is None:
        raise MemoReportError(f"Investment {investment_id!r} has no memo draft to preview.")

    selected = draft.selected_decision
    analysis = (
        _Analysis(resolved=False, detail="No decision cell is selected yet.")
        if selected is None
        else _analysis_for(investment_id, selected, db_path)
    )

    references = store.list_evidence_references(investment_id, db_path=db_path)
    library = {reference.evidence_id: reference for reference in references}
    citations = _claim_citations(draft.items, draft.risk_items, draft.term_items)
    name, asset_type = _investment_identity(investment_id, db_path)

    valuations = _draft_valuations(draft, analysis)
    exit_view = _exit_view(analysis)
    if exit_view is not None:
        valuations = valuations + (exit_view,)

    return MemoReportPackage(
        origin=MemoReportOrigin.DRAFT_PREVIEW,
        investment_id=investment_id,
        investment_name=name,
        asset_type=asset_type,
        market=None,
        version_number=None,
        version_id=None,
        published_at=None,
        prepared_by=draft.prepared_by,
        generated_at=_generated_at(),
        decision_ask=draft.decision_ask,
        analyst_recommendation=_label(_RECOMMENDATION_LABELS, draft.analyst_recommendation),
        committee_decision=None,
        committee_note=None,
        executive_summary=draft.executive_summary,
        strategy_label=(
            "Not selected"
            if selected is None
            else _strategy_label(investment_id, selected.strategy_id, db_path)
        ),
        scenario_label=(
            "Not selected"
            if selected is None
            else _scenario_label(investment_id, selected.scenario_id, db_path)
        ),
        perspective_label=(
            "Not selected" if selected is None else _perspective_label(selected, analysis)
        ),
        freshness=ReportFreshness.NOT_APPLICABLE,
        key_metrics=_key_metrics(analysis),
        valuations=valuations,
        sections=_sections_for(
            analysis,
            selected or _NO_SELECTION,
            _narrative_sections(draft.items, draft.risk_items, draft.term_items, library),
            _is_multi_unit(investment_id, db_path),
        ),
        evidence=_evidence_register(references, citations),
        concluding_statement=None,
    )


#: The perspective a draft with no selected cell reports from: none. Used only
#: so the section builder has a shape to read; it names no position or partner
#: and therefore produces Project-shaped empty returns.
_NO_SELECTION = SelectedDecision(
    strategy_id=BASE_STRATEGY_ID,
    scenario_id=BASE_SCENARIO_ID,
    perspective=DecisionPerspectiveKind.PROJECT,
    position_id=None,
    partner_id=None,
)


def _draft_valuations(
    draft: InvestmentMemoDraft, analysis: _Analysis
) -> tuple[MemoReportValuation, ...]:
    """The draft's valuation views: the ones it selected, and the ones a
    ``PctOfValue`` funding consumes.

    A view the analyst authored but neither selected nor consumed is exploratory
    working state (Section 22.6) and is not a dependency of the package, so the
    preview leaves it out of the report exactly as publication would.
    """

    surface = analysis.surface
    if surface is None:
        return ()
    selected_ids = set(draft.selected_valuation_timepoint_ids)
    consumed_ids = set(getattr(surface, "consumed_timepoint_ids", ()))
    included: list[MemoReportValuation] = []
    for view in getattr(surface, "views", ()):
        is_selected = view.timepoint_id in selected_ids
        is_consumed = view.timepoint_id in consumed_ids
        if not (is_selected or is_consumed):
            continue
        included.append(
            _valuation_from_view(
                view,
                selected=is_selected,
                consumed=is_consumed,
                hold_period=analysis.hold_period,
            )
        )
    return tuple(included)


def _concluding_statement(name: str, recommendation: str) -> str:
    """The closing recommendation line.

    It restates the analyst's own recommendation and the Investment it concerns
    and adds nothing: no rationale, no causal claim, no adjective about the
    basis, the leverage or the returns. Every reason a reader might want is the
    analyst's authored thesis, printed above in the analyst's own words.
    """

    return f"The analyst recommendation for {name} is {recommendation}."


# =============================================================================
# Export authority (Stage 4 §9)
# =============================================================================


def export_filename(package: MemoReportPackage) -> str:
    """The download name: the Investment and the memo version.

    Only a published version has a version number, and only a published version
    can be exported, so the name always carries one. Reduced to filename-safe
    characters, which is a presentation decision and touches nothing stored.
    """

    if package.version_number is None:
        raise PdfExportRefusedError(
            PdfExportRefusalCode.DRAFT_NOT_EXPORTABLE,
            "A final PDF is generated only from a published memo version.",
        )
    stem = "".join(
        character if character.isalnum() else "-" for character in package.investment_name
    ).strip("-")
    safe = stem or "investment"
    return f"{safe}-investment-memo-v{package.version_number}.pdf"


def read_version_pdf(
    investment_id: str, version_id: str, *, db_path: Path | None = None
) -> tuple[bytes, str]:
    """The exact PDF one published version was issued as, and its filename.

    **The stored bytes, never a re-render** (Stage 4 Correction 1). Downloading
    the same version twice returns the same bytes, byte for byte, however much
    the surrounding analysis has changed and whatever this presentation code
    does now.

    Refuses with a typed explanation rather than a generic failure: a version
    that does not exist, and a version published before schema 16 that has no
    stored artifact. It cannot be handed a draft at all -- the parameter is a
    ``version_id``, and no draft has one.
    """

    try:
        artifact = store.get_memo_version_artifact(investment_id, version_id, db_path=db_path)
    except LookupError as error:
        raise PdfExportRefusedError(
            PdfExportRefusalCode.VERSION_NOT_FOUND,
            str(error) or f"Memo version {version_id!r} was not found.",
            version_id=version_id,
        ) from None
    if artifact is None:
        raise PdfExportRefusedError(
            PdfExportRefusalCode.REPORT_SNAPSHOT_NOT_AVAILABLE,
            REPORT_SNAPSHOT_NOT_AVAILABLE_MESSAGE,
            version_id=version_id,
        )
    return artifact.pdf_bytes, artifact.pdf_filename
