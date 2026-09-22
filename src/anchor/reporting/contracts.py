"""Phase 7 Gate P7.10 Stage 4 -- the assembled report's shapes.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Section 13;
that document governs on any discrepancy.

**Shapes only, and presentation shapes at that.** Like every other ``contracts``
module in Anchor nothing here calculates. What is unusual, and deliberate, is
that every numeric field below is a **string that has already been formatted**.
A report cell carries ``"$25,000,000"``, not ``25000000.0``.

That is the point. A renderer holding raw floats is a renderer one edit away
from summing two of them; a renderer holding finished text cannot compute
anything even by accident, and the Section 11 guard that forbids arithmetic in
the PDF layer then has something real to protect. The single conversion from a
backend float to display text happens in ``assembly``, through
``anchor.formatting``, which is the presentation-only helper the CLI report has
used since Phase 4.

**Unavailable is a value, not an absence.** ``ReportUnavailable`` carries the
backend's own ``reason_code`` and analyst-facing ``reason``. Section 2 forbids
rendering a missing, stale or unavailable figure as zero or omitting it where
the omission could mislead, so a cell that has no number holds one of these and
the renderer prints its label -- never ``$0``, never the purchase price, never
a blank that reads as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoReportOrigin(StrEnum):
    """Which memo state a report was assembled from.

    The distinction is load-bearing rather than cosmetic (Section 9 of the
    Stage 4 contract): a ``DRAFT_PREVIEW`` is assembled from the one mutable
    draft and may never become a final PDF, while ``PUBLISHED_VERSION`` is
    assembled from an immutable version and is the only thing that may. The
    renderer reads this field to decide whether to mark every page a draft, and
    the export route reads it to decide whether to refuse.
    """

    DRAFT_PREVIEW = "draft_preview"
    PUBLISHED_VERSION = "published_version"


class ReportFreshness(StrEnum):
    """What this report was, at the moment it was assembled.

    **Not a live status.** A published report is frozen at publication, so it
    records ``CURRENT`` forever: it *was* current when it was issued, and an
    issued document does not change its mind later. Whether today's analysis
    still matches what that version recorded is a different question, answered
    by the Stage 2 freshness route against the dependency ledger and displayed
    *around* the frozen report rather than inside it.

    There is deliberately no ``STALE`` member. Painting a stale marking onto an
    issued document would be a change to the document, which Correction 1
    forbids; ``anchor.memo.contracts.MemoFreshness`` owns staleness and is the
    only place it is decided.

    A draft preview reports ``NOT_APPLICABLE``: a draft is published against
    nothing and so cannot have drifted from it.
    """

    CURRENT = "current"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportUnavailable:
    """Why a report cell has no value.

    ``reason_code`` is the backend's own stable token -- a
    ``ValuationUnavailableReason``, an ``UnavailableReasonCode``, a
    ``PositionUnavailableReason`` -- carried through unchanged, and ``reason``
    is the analyst-facing sentence that came with it. Neither is composed here.

    ``label`` is what the renderer prints in place of a number. It defaults to
    ``"Unavailable"`` and is never ``"0"``, ``"$0"``, ``"-"`` or ``""``.
    """

    reason_code: str
    reason: str
    label: str = "Unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportMetric:
    """One labelled figure in a metric card or a summary row.

    ``value`` is the formatted text when the figure exists, and ``unavailable``
    carries the typed reason when it does not. Exactly one of the two is set;
    ``assembly`` builds them through helpers that cannot produce both or
    neither.

    ``note`` is an optional qualifier the analyst must read with the number --
    "Analyst-Supplied Value", "Investment scope", "System-derived". It is never
    a second number.
    """

    label: str
    value: str | None = None
    unavailable: ReportUnavailable | None = None
    note: str | None = None

    @property
    def is_available(self) -> bool:
        return self.value is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportTable:
    """One financial table: a caption, column headers, and formatted rows.

    ``rows`` are already strings, in the order they are printed. ``align_right``
    names the column indices that carry figures, so the renderer right-aligns
    them without inspecting their contents -- a renderer that sniffed for a
    leading ``$`` would be reading the data to make a layout decision, and would
    align an ``Unavailable`` cell differently from a dollar one in the same
    column.

    ``emphasize_rows`` names total or base-case rows by index. ``note`` carries
    a disclosure that belongs with this table specifically, such as a scope that
    has no implemented result.
    """

    caption: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    align_right: tuple[int, ...] = ()
    emphasize_rows: tuple[int, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportNarrativeItem:
    """One analyst-authored claim as the report presents it.

    ``text`` is the analyst's own words, unedited. ``detail`` carries a risk's
    mitigant or a milestone's qualifier where the contract gives one.

    ``evidence_labels`` are the human-readable titles of the Evidence References
    this claim cites, in authored order. ``sourced`` is ``False`` when the claim
    cites none, and the renderer then prints the Section 8 label **Analyst
    Assertion -- Source Not Attached** rather than leaving the claim looking
    sourced. Anchor has verified nothing by virtue of an analyst attaching a
    reference, and no field here says otherwise.
    """

    text: str
    detail: str | None = None
    labels: tuple[str, ...] = ()
    evidence_labels: tuple[str, ...] = ()
    sourced: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportEvidenceEntry:
    """One row of the source register.

    ``cited_by`` names the claims that rest on this source, in report order, so
    a reader can follow a citation in both directions. ``approved`` is the
    analyst's own approval state, printed as its own column: Section 8 requires
    source status, approval status and the analyst's claim to stay visibly
    distinct, and collapsing an unapproved source into an approved-looking row
    is exactly the silent upgrade it forbids.
    """

    title: str
    source_kind: str
    reference: str
    as_of_date: str | None
    approved: bool
    cited_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportValuation:
    """One valuation view as the report presents it.

    ``selected`` says the memo included this view and ``consumed`` that a
    ``PctOfValue`` funding of the selected Capital Structure sized itself from
    it. Both are printed, because a consumed view the report never displays as
    a headline is still load-bearing, and a reader deciding whether a number
    mattered needs to see which.

    ``system_controlled`` marks the reserved Exit view (R-B). ``analyst_supplied``
    marks a view resolved from an analyst's stated amount rather than an Anchor
    direct capitalization -- Section 5.4 requires it to read **Analyst-Supplied
    Value** everywhere it appears.
    """

    label: str
    kind: str
    timing: str
    scope: str
    value: str | None = None
    unavailable: ReportUnavailable | None = None
    selected: bool = False
    consumed: bool = False
    system_controlled: bool = False
    analyst_supplied: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportDisclosure:
    """One thing the reader is told rather than left to infer.

    Section 13.2 is explicit that an appendix whose data does not exist is
    omitted and a *material* unavailable condition is stated instead, where a
    reader could otherwise infer zero or completeness. These are those
    statements: a scope with no implemented solver, a stale dependency class, a
    selected valuation that did not resolve, a Partnership the variant does not
    hold.
    """

    title: str
    detail: str
    scope: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportSection:
    """One titled block of the report.

    A section holds any mix of narrative items, metrics and tables, and the
    renderer prints whichever are present. A section with nothing in it is
    dropped by ``assembly`` rather than printed empty: Section 13.2 forbids
    generating the empty appendix, and the concept's "do not populate them with
    demo copy" is the same rule from the other side.
    """

    title: str
    subtitle: str | None = None
    narrative: tuple[MemoReportNarrativeItem, ...] = ()
    metrics: tuple[MemoReportMetric, ...] = ()
    tables: tuple[MemoReportTable, ...] = ()
    body: str | None = None
    disclosures: tuple[MemoReportDisclosure, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.narrative or self.metrics or self.tables or self.body or self.disclosures
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportPackage:
    """One complete Investment Committee memorandum, ready to render.

    This is the whole contract between what Anchor knows and what the PDF
    prints. The renderer receives one of these and nothing else -- no store, no
    engine, no analysis function, no raw result contract -- so "the PDF renderer
    performs formatting only" (Section 13.3) is enforced by what it is handed
    rather than by a convention it is asked to respect.

    ``origin`` decides whether this may become a final PDF, and whether every
    page is marked a draft.

    **A published package is frozen.** It is assembled once, at publication,
    stored as an immutable artifact beside the version, and returned unchanged
    on every later read. Nothing in it tracks the current analysis, because a
    document that changed after it was issued would not be the document the
    committee read.

    ``analyst_recommendation`` and ``committee_decision`` are separate fields
    that are separately printed (R-F). The committee's outcome is ``None`` until
    a human records one, and ``None`` is rendered as "Not yet recorded" -- never
    as Pending, which is a decision somebody made, and never inferred from the
    analyst's recommendation.
    """

    origin: MemoReportOrigin
    investment_id: str
    investment_name: str
    asset_type: str | None
    market: str | None
    version_number: int | None
    version_id: str | None
    published_at: str | None
    prepared_by: str | None
    generated_at: str

    decision_ask: str
    analyst_recommendation: str
    committee_decision: str | None
    committee_note: str | None
    executive_summary: str

    strategy_label: str
    scenario_label: str
    perspective_label: str

    freshness: ReportFreshness = ReportFreshness.NOT_APPLICABLE

    #: The published version's own fingerprint, which Section 13.3 requires the
    #: PDF to carry. It appears in exactly one place -- the closing version
    #: appendix, labelled as a verification code -- and never in the workspace,
    #: a metric, a table cell or a heading. That boundary is the Section 2 rule
    #: about implementation vocabulary in normal analyst views, kept while still
    #: giving a committee reader the audit identity the contract promises them.
    #: ``None`` for a draft preview, which has published nothing to verify.
    verification_code: str | None = None

    key_metrics: tuple[MemoReportMetric, ...] = ()
    valuations: tuple[MemoReportValuation, ...] = ()
    sections: tuple[MemoReportSection, ...] = ()
    evidence: tuple[MemoReportEvidenceEntry, ...] = ()
    disclosures: tuple[MemoReportDisclosure, ...] = ()
    concluding_statement: str | None = None

    #: Printed at the foot of every page. Stage 4 stores no generated PDF as a
    #: source record (Section 13.3), so this is a marking, not a claim of
    #: custody.
    confidentiality: str = "Confidential – For Investment Committee Use Only"

    @property
    def is_draft(self) -> bool:
        return self.origin is MemoReportOrigin.DRAFT_PREVIEW

    @property
    def title(self) -> str:
        return "Investment Committee Memorandum"

    @property
    def status_line(self) -> str:
        """The one line that says what this document is.

        Two states, because a report is one of two things: a preview of a draft
        nobody has published, or an issued version. A published line never
        changes afterwards: what changed is the analysis around it, and that is
        reported beside the document rather than stamped onto it.
        """

        if self.is_draft:
            return "DRAFT – NOT PUBLISHED"
        return "PUBLISHED"

    def rendered_sections(self) -> tuple[MemoReportSection, ...]:
        """The sections that have content. An empty one is never printed."""

        return tuple(section for section in self.sections if not section.is_empty)


#: The report's own labels for the two decision acts, kept here so the workspace
#: and the PDF cannot drift into calling them different things.
ANALYST_RECOMMENDATION_LABEL = "Analyst Recommendation"
COMMITTEE_DECISION_LABEL = "Investment Committee Decision"

#: What a committee outcome nobody has recorded reads as. Deliberately not
#: "Pending": Stage 2's route returns ``null`` for "nothing recorded" and
#: ``pending`` for "the committee recorded that it is pending", and those are
#: different facts (Section 7.5).
COMMITTEE_DECISION_UNRECORDED = "Not yet recorded"

#: Section 8's label for a claim that cites no source.
UNSOURCED_CLAIM_LABEL = "Analyst Assertion – Source Not Attached"

__all__ = [
    "ANALYST_RECOMMENDATION_LABEL",
    "COMMITTEE_DECISION_LABEL",
    "COMMITTEE_DECISION_UNRECORDED",
    "MemoReportDisclosure",
    "MemoReportEvidenceEntry",
    "MemoReportMetric",
    "MemoReportNarrativeItem",
    "MemoReportOrigin",
    "MemoReportPackage",
    "MemoReportSection",
    "MemoReportTable",
    "MemoReportValuation",
    "ReportFreshness",
    "ReportUnavailable",
    "UNSOURCED_CLAIM_LABEL",
]
