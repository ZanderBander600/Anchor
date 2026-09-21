"""Phase 7 Gate P7.10 Stage 2 -- the Investment Memo shapes.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 7, 8,
9, 10 and 16 under the ratified P7 authority in
``P7_COMPETITION_DECISION_ARCHITECTURE.md``; those documents govern on any
discrepancy. Ratified decisions R-F, R-G and R-H are the authority behind every
shape here.

**Shapes only.** Like every other ``contracts`` module in the engine, nothing
here calculates, stores or serialises. ``validation`` says whether an authored
memo is well formed, ``availability`` translates an unresolved state into the
structured N/A representation, and ``publication`` says whether a draft may
become an immutable version.

**Narrative is never a second source of financial truth.** No field here holds
an amount, a rate, a return, a delta or a ranking. A memo cites results; it
never restates them. Every figure a memo presents is read from the existing
backend result contracts at read time, so a memo cannot drift from the analysis
it describes.

**Two different acts (R-F).** ``analyst_recommendation`` is the analyst's
proposed action and lives on the draft. ``InvestmentCommitteeDecision`` is the
committee's outcome, is recorded against a *published version*, and is entered
after publication. They are different fields, different records and different
lifecycles. Neither is ever written by AI; Stage 2 implements no AI surface at
all.

**Stable item identity (Section 7.4).** Every repeating item names itself by an
opaque ``item_id``. List position is presentation: ``display_order`` carries the
analyst's authored order explicitly, and no economic identity reads it. Editing
an item's prose or moving it never redefines what it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class MemoError(Exception):
    """A memo operation the domain cannot perform. Raising this is a
    programming error, never an analyst finding: a caller asked for something
    the contract says is unavailable instead of reading the typed refusal."""


# =============================================================================
# The analyst's own statements (Section 7.2; R-F)
# =============================================================================


class AnalystRecommendation(StrEnum):
    """The analyst's proposed action (Section 7.2). It is a *proposal*: it is
    never the committee's decision, and no AI may set it (R-F).

    ``INSUFFICIENT_INFORMATION`` is a real recommendation, not an absence -- it
    states that the package does not yet support a decision, which is exactly
    the honest answer the contract requires instead of a manufactured one."""

    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    REVISE_AND_RESUBMIT = "revise_and_resubmit"
    DECLINE = "decline"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class ExecutionComplexity(StrEnum):
    """An analyst-authored qualitative label (Section 7.2). It is never
    calculated from a return, a Business Plan or a capital structure."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    NOT_ASSESSED = "not_assessed"


class MemoSection(StrEnum):
    """Which authored list an ordinary text item belongs to (Section 7.2).

    Risks and terms are deliberately absent: each carries fields an ordinary
    item does not (severity and residual risk; priority), so each has its own
    shape below rather than a nullable column nothing else uses."""

    THESIS = "thesis"
    STRUCTURAL_PROTECTION = "structural_protection"
    REPUTATIONAL_CONCERN = "reputational_concern"
    DEALBREAKER = "dealbreaker"
    CONDITION_TO_APPROVAL = "condition_to_approval"
    BUSINESS_PLAN_MILESTONE = "business_plan_milestone"


class TermPriority(StrEnum):
    """How hard the analyst will hold a term (Section 7.2)."""

    REQUIRED = "required"
    DESIRED = "desired"
    NEGOTIABLE = "negotiable"


class RiskSeverity(StrEnum):
    """An analyst-authored qualitative label. Section 7.4 is explicit: severity
    and residual risk are *never calculated from returns*, and a mitigant does
    not automatically downgrade either one."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    NOT_ASSESSED = "not_assessed"


class MemoClaimKind(StrEnum):
    """Which authored collection a claim-level evidence link belongs to.

    An ``item_id`` is unique **within** its collection, not across them, so a
    link names the collection as well as the id. Without this discriminator a
    thesis item and a risk that happened to share an id would silently share
    their sources."""

    ITEM = "item"
    RISK = "risk"
    TERM = "term"


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoItem:
    """One authored statement in one section.

    ``item_id`` is the identity; ``display_order`` is presentation only
    (Section 7.4). Rewriting ``text`` edits this item -- it never creates a new
    one -- and reordering the list never changes what any item is.

    ``evidence_ids`` are the Evidence References supporting *this claim*
    (R-G). Zero or more: an unsupported statement is a real, storable analyst
    assertion and is labelled as one, never silently upgraded to a sourced fact
    (Section 8). The ids name records in the Investment's own evidence library;
    a foreign or unknown id is refused rather than stored."""

    item_id: str
    section: MemoSection
    display_order: int
    text: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoRiskItem:
    """One authored risk, with the analyst's own qualitative labels and
    mitigant.

    ``severity`` and ``residual_risk`` are labels the analyst writes. Nothing
    derives either from a return, a sensitivity or a break-even, and stating a
    ``mitigant`` never resolves the risk or lowers its residual label
    (Section 7.4).

    ``evidence_ids`` support the risk and its mitigant together: the contract
    gives a mitigant no id of its own, so a source cited for "pre-leasing is
    underway" attaches to the risk that states it."""

    item_id: str
    display_order: int
    text: str
    severity: RiskSeverity
    residual_risk: RiskSeverity
    mitigant: str | None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoTermItem:
    """One authored term and how hard it is held.

    ``evidence_ids`` are *supported, never required*. A term is a negotiating
    position rather than a claim about the world, so R-G does not oblige a
    source for one; an analyst who wants to cite the letter of intent a term
    came from can, and nothing refuses a term that cites none."""

    item_id: str
    display_order: int
    text: str
    priority: TermPriority
    evidence_ids: tuple[str, ...] = ()


# =============================================================================
# Evidence (Section 8; R-G)
# =============================================================================


class EvidenceSourceKind(StrEnum):
    """What kind of source an Evidence Reference names (Section 8).

    ``AI_EXTRACTED_APPROVED`` records that a human approved something an
    extraction proposed. It is a *provenance* label on an analyst-approved
    reference, not an AI capability: Stage 2 implements no AI surface, and no
    code path in this gate can create or approve a reference on its own."""

    CASE_DOCUMENT = "case_document"
    RENT_COMP = "rent_comp"
    SALES_COMP = "sales_comp"
    BROKER_RESEARCH = "broker_research"
    ANALYST_ASSUMPTION = "analyst_assumption"
    IMPORTED_MODEL = "imported_model"
    AI_EXTRACTED_APPROVED = "ai_extracted_approved"
    OTHER = "other"


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoEvidenceReference:
    """One approved source citation or analyst assertion (Section 8).

    P7.10 stores a *reference*, never a copy of the source document: ``reference``
    is a document anchor, URL or analyst note, and the existing document
    security boundary is reused unchanged.

    ``approved`` is the analyst's own approval state. An unapproved reference is
    never silently upgraded to a fact: a claim resting on one is labelled an
    analyst assertion, and an ``ANALYST_VALUE`` valuation whose evidence is
    unapproved does not resolve (``EVIDENCE_NOT_APPROVED``)."""

    evidence_id: str
    investment_id: str
    source_kind: EvidenceSourceKind
    title: str
    reference: str
    as_of_date: date | None
    approved: bool
    display_order: int


# =============================================================================
# The selected decision (Section 7.3)
# =============================================================================


class DecisionPerspectiveKind(StrEnum):
    """Which stakeholder's returns the recommendation is made from
    (Section 7.3). The three existing P7 perspectives, reused: P7.10 adds no
    fourth and recomputes none of their figures."""

    PROJECT = "project"
    POSITION = "position"
    PARTNER = "partner"


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectedDecision:
    """The one decision cell the memo recommends (Section 7.3).

    Naming a cell *selects*; it never changes a Strategy, a Scenario, a
    position or a Partnership. ``position_id`` is stated exactly when
    ``perspective`` is ``POSITION`` and ``partner_id`` exactly when it is
    ``PARTNER``; ``PROJECT`` states neither.

    The Base Strategy and Base Scenario are named by their existing reserved
    implicit keys, so "the Base cell" is an ordinary selection rather than a
    missing one."""

    strategy_id: str
    scenario_id: str
    perspective: DecisionPerspectiveKind
    position_id: str | None
    partner_id: str | None


# =============================================================================
# The mutable draft (Section 7.2; R-H)
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentMemoDraft:
    """The one mutable analyst workspace belonging to an Investment (R-H).

    Exactly one draft exists per Investment, and it is edited in place. It is
    never a version: publishing copies it into an immutable
    ``InvestmentMemoVersion`` and leaves the draft free to move on.

    ``prepared_by`` is display text, not an authenticated identity
    (Section 7.5). Every narrative field is analyst-authoritative; an empty
    optional section stays empty, and nothing manufactures boilerplate to fill
    it.

    **Authoring a valuation is not selecting one.** An Investment may hold any
    number of authored valuation definitions, including exploratory ones the
    analyst is still working out. ``selected_valuation_timepoint_ids`` is the
    memo's own, explicit statement of which of them this decision package
    *includes* -- and it is the only thing that makes a valuation a memo
    dependency. Selection is never inferred from display order, from a
    definition merely existing, or from which one was authored most recently:
    an analyst who has not chosen has not chosen.

    ``evidence_ids`` is the memo's evidence register -- the sources the package
    presents as a whole. It is distinct from, and does not replace, the
    per-claim links each item carries (R-G): the register says what the package
    rests on, and an item's own ``evidence_ids`` say which source supports
    *that* claim."""

    memo_id: str
    investment_id: str
    prepared_by: str | None
    decision_ask: str
    analyst_recommendation: AnalystRecommendation
    executive_summary: str
    execution_complexity: ExecutionComplexity
    return_on_time_notes: str
    selected_decision: SelectedDecision | None
    items: tuple[MemoItem, ...] = ()
    risk_items: tuple[MemoRiskItem, ...] = ()
    term_items: tuple[MemoTermItem, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    selected_valuation_timepoint_ids: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""

    def cited_evidence_ids(self) -> tuple[str, ...]:
        """Every Evidence Reference this draft cites anywhere -- the register
        and every claim-level link -- in canonical order.

        The union, deduplicated: one reference cited by three claims is one
        record, and publication validates it once."""

        cited: set[str] = set(self.evidence_ids)
        for collection in (self.items, self.risk_items, self.term_items):
            for item in collection:
                cited.update(item.evidence_ids)
        return tuple(sorted(cited))

    def claim_links(self) -> tuple[tuple[str, str, str], ...]:
        """Every claim-to-evidence link as ``(claim_kind, item_id,
        evidence_id)``, canonical by all three.

        One flat, sorted view of the relationships, so persistence, identity and
        the wire all read the same thing and authored order never participates."""

        links: list[tuple[str, str, str]] = []
        for kind, collection in (
            (MemoClaimKind.ITEM, self.items),
            (MemoClaimKind.RISK, self.risk_items),
            (MemoClaimKind.TERM, self.term_items),
        ):
            for item in collection:
                for evidence_id in item.evidence_ids:
                    links.append((kind.value, item.item_id, evidence_id))
        return tuple(sorted(set(links)))

    def section(self, section: MemoSection) -> tuple[MemoItem, ...]:
        """This draft's items in one section, in authored display order."""

        return tuple(
            item
            for item in sorted(self.items, key=lambda entry: (entry.display_order, entry.item_id))
            if item.section is section
        )


# =============================================================================
# The immutable published version (Section 9; R-H)
# =============================================================================


class MemoDependencyClass(StrEnum):
    """One class of authoritative state a published memo version depends on
    (Section 9).

    Each class is separately fingerprinted, so a stale package names *which*
    kind of state moved rather than reporting a single undifferentiated
    "stale". The classes are layered exactly as the ratified P7 identity model
    layers them, and no two of them flatten different domains into one hash.

    - ``INVESTMENT_MEMBERSHIP``: which Units the Investment holds.
    - ``UNDERWRITING``: every member Unit's resolved-input identity -- the
      existing per-Unit Project fingerprints, unchanged.
    - ``BUSINESS_PLAN``: the Investment's and each Unit's authored Business
      Plan. Reported in preference to ``UNDERWRITING`` when both moved, because
      it is the more specific statement of what the analyst changed.
    - ``STRATEGY`` / ``SCENARIO``: the selected Strategy's and Scenario's own
      authored definitions.
    - ``PROJECT_VARIANT``: the selected variant's Project source fingerprint --
      the one identity the existing engine already publishes for it.
    - ``CAPITAL_STRUCTURE``: the structured source fingerprint (P7.8B).
    - ``PARTNERSHIP``: the Partnership source fingerprint (P7.9), absent where
      the variant resolves no Partnership.
    - ``VALUATION_DEFINITIONS``: the authored timepoints' economics. Labels and
      display order are excluded (Section 10), so renaming a view never
      invalidates anything.
    - ``VALUATION_RESULTS``: those definitions resolved against this variant --
      the values and statuses actually cited.
    - ``DECISION_PERSPECTIVE``: the selected perspective's identity.
    - ``EVIDENCE``: the content of the approved references the memo cites.
    - ``MEMO_CONTENT``: the authored memo itself.
    """

    INVESTMENT_MEMBERSHIP = "investment_membership"
    UNDERWRITING = "underwriting"
    BUSINESS_PLAN = "business_plan"
    STRATEGY = "strategy"
    SCENARIO = "scenario"
    PROJECT_VARIANT = "project_variant"
    CAPITAL_STRUCTURE = "capital_structure"
    PARTNERSHIP = "partnership"
    VALUATION_DEFINITIONS = "valuation_definitions"
    VALUATION_RESULTS = "valuation_results"
    DECISION_PERSPECTIVE = "decision_perspective"
    EVIDENCE = "evidence"
    MEMO_CONTENT = "memo_content"


#: The order a stale package reports its reasons in: most specific statement of
#: what the analyst changed first, so "the Business Plan changed" is never
#: buried under the broader identity it also moved.
DEPENDENCY_REPORT_ORDER: tuple[MemoDependencyClass, ...] = (
    MemoDependencyClass.INVESTMENT_MEMBERSHIP,
    MemoDependencyClass.BUSINESS_PLAN,
    MemoDependencyClass.STRATEGY,
    MemoDependencyClass.SCENARIO,
    MemoDependencyClass.UNDERWRITING,
    MemoDependencyClass.PROJECT_VARIANT,
    MemoDependencyClass.CAPITAL_STRUCTURE,
    MemoDependencyClass.PARTNERSHIP,
    MemoDependencyClass.VALUATION_DEFINITIONS,
    MemoDependencyClass.VALUATION_RESULTS,
    MemoDependencyClass.DECISION_PERSPECTIVE,
    MemoDependencyClass.EVIDENCE,
    MemoDependencyClass.MEMO_CONTENT,
)

#: The dependency classes that are *financial*: a change in one of them changes
#: what the analysis says, not merely how the memo reads. Presentation-only
#: edits -- a valuation label, a valuation's display order, a Strategy's name --
#: must never move one of these, and a test proves each direction.
FINANCIAL_DEPENDENCY_CLASSES: frozenset[MemoDependencyClass] = frozenset(
    {
        MemoDependencyClass.INVESTMENT_MEMBERSHIP,
        MemoDependencyClass.UNDERWRITING,
        MemoDependencyClass.BUSINESS_PLAN,
        MemoDependencyClass.STRATEGY,
        MemoDependencyClass.SCENARIO,
        MemoDependencyClass.PROJECT_VARIANT,
        MemoDependencyClass.CAPITAL_STRUCTURE,
        MemoDependencyClass.PARTNERSHIP,
        MemoDependencyClass.VALUATION_DEFINITIONS,
        MemoDependencyClass.VALUATION_RESULTS,
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoDependency:
    """One recorded dependency of a published version: its class, the scope it
    covers, and the fingerprint that state had at publication.

    ``scope_id`` is the Unit, position or partner the entry concerns, or ``""``
    for a whole-Investment entry. It is never ``None``, so two whole-Investment
    entries of one class can never both exist."""

    dependency_class: MemoDependencyClass
    scope_id: str
    fingerprint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoVersionValuation:
    """One valuation view as it stood when the version was published
    (Section 9).

    Frozen with the version: it records what the memo actually cited, including
    an unavailable view and its typed reason. ``value`` is ``None`` for an
    unavailable view and is never zero-filled -- a version that cited "no value
    at this timepoint" keeps saying so forever.

    ``selected`` says the memo *included* this view, and ``consumed`` that a
    ``PctOfValue`` funding of the selected variant sized itself from it. Both
    are recorded because they are different reasons for a valuation to be a
    dependency, and only one of them is visible in the report: a consumed
    valuation the memo never displays is still load-bearing.

    A view that is neither selected nor consumed is frozen for the record --
    the analyst could see it existed -- and is not a dependency of this
    version."""

    timepoint_id: str
    kind: str
    label: str
    model_month: int
    scope_kind: str
    status: str
    value: float | None
    unavailable_reason: str | None
    unavailable_message: str | None
    selected: bool = False
    consumed: bool = False

    @property
    def required(self) -> bool:
        """Whether this view had to resolve for the version to exist."""

        return self.selected or self.consumed


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoClaimEvidence:
    """One frozen claim-to-evidence link of a published version (R-G).

    Snapshotted at publication, exactly as the memo content and the evidence
    content are. A later draft edit, a re-linked claim or a deleted Evidence
    Reference changes the draft and never this record: a reviewer opening
    version N sees the source that supported that claim *then*."""

    claim_kind: MemoClaimKind
    item_id: str
    evidence_id: str
    ordinal: int


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentMemoVersion:
    """One immutable publication of memo content plus the exact results it
    cites (Section 9; R-H).

    **Never edited in place.** No write path in Anchor updates a published
    version: editing resumes in the draft and produces a *new* version when
    published again. ``version_number`` increases monotonically within the
    Investment, and publishing is one transaction -- either the complete version
    and its dependency ledger exist, or neither does.

    ``dependencies`` is the ledger the freshness check compares against.
    ``published_fingerprint`` covers the version's content and that ledger, and
    deliberately excludes the IC decision (Section 10): the committee records
    its outcome *after* publication, and doing so must not alter the identity of
    what it decided on.

    ``claim_evidence`` is the frozen per-claim source map (R-G). It is stored
    beside the items rather than inside them because it is a relationship, and
    a relationship one of whose ends can be deleted has to be snapshotted to
    survive."""

    version_id: str
    investment_id: str
    version_number: int
    prepared_by: str | None
    decision_ask: str
    analyst_recommendation: AnalystRecommendation
    executive_summary: str
    execution_complexity: ExecutionComplexity
    return_on_time_notes: str
    selected_decision: SelectedDecision
    items: tuple[MemoItem, ...]
    risk_items: tuple[MemoRiskItem, ...]
    term_items: tuple[MemoTermItem, ...]
    evidence: tuple[MemoEvidenceReference, ...]
    claim_evidence: tuple[MemoClaimEvidence, ...]
    valuations: tuple[MemoVersionValuation, ...]
    dependencies: tuple[MemoDependency, ...]
    memo_content_fingerprint: str
    published_fingerprint: str
    created_at: str

    def evidence_for(self, claim_kind: MemoClaimKind, item_id: str) -> tuple[str, ...]:
        """The Evidence Reference ids frozen against one claim, in the order
        they were authored."""

        return tuple(
            link.evidence_id
            for link in sorted(self.claim_evidence, key=lambda entry: entry.ordinal)
            if link.claim_kind is claim_kind and link.item_id == item_id
        )

    @property
    def required_valuations(self) -> tuple[MemoVersionValuation, ...]:
        """The views this version depended on: the ones it selected, and the
        ones a ``PctOfValue`` funding consumed."""

        return tuple(view for view in self.valuations if view.required)


# =============================================================================
# The Investment Committee decision (Section 7.5; R-F)
# =============================================================================


class InvestmentCommitteeOutcome(StrEnum):
    """The committee's outcome (Section 7.5).

    Deliberately *not* ``AnalystRecommendation``: the two vocabularies differ
    (``DEFERRED`` is a committee outcome; ``INSUFFICIENT_INFORMATION`` and
    ``REVISE_AND_RESUBMIT`` are analyst recommendations), so no code path and no
    reader can substitute one for the other."""

    PENDING = "pending"
    APPROVED = "approved"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    DEFERRED = "deferred"
    DECLINED = "declined"


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentCommitteeDecision:
    """A separately entered record of the committee outcome (Section 7.5).

    It belongs to a *published version*, never to the draft: a committee decides
    on something immutable. It is entered after publication, so it is excluded
    from the published-version fingerprint (Section 10), and recording it
    changes no memo content and no financial result.

    P7.10 provides no voting workflow and no verified signature.
    ``decision_note`` and ``decided_at`` are analyst-entered display records,
    never security identities. AI cannot write or change this record; Stage 2
    ships no AI surface that could."""

    memo_version_id: str
    decision: InvestmentCommitteeOutcome
    decision_note: str | None
    decided_at: str | None
    created_at: str = ""
    updated_at: str = ""


# =============================================================================
# Freshness (Section 9)
# =============================================================================


class MemoFreshness(StrEnum):
    """Whether a published version still matches the state it was published
    against.

    ``STALE`` always carries the changed dependency classes. Reopening a stale
    version is allowed and its content is unchanged; presenting it as current is
    not (Section 9)."""

    CURRENT = "current"
    STALE = "stale"


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoStaleDependency:
    """One dependency class that no longer matches, with the scope it concerns
    and both fingerprints, so a reader can see exactly what moved.

    ``current_fingerprint`` is ``None`` when the dependency can no longer be
    computed at all -- the selected Strategy was deleted, or the variant no
    longer resolves. That is a real, named condition, never an equality that
    quietly fails."""

    dependency_class: MemoDependencyClass
    scope_id: str
    published_fingerprint: str
    current_fingerprint: str | None
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoFreshnessReport:
    """One published version's freshness against the current state.

    ``stale_dependencies`` is empty exactly when ``freshness`` is ``CURRENT``.
    A historical version is always readable: this report describes it, and never
    withholds or rewrites it."""

    version_id: str
    version_number: int
    freshness: MemoFreshness
    stale_dependencies: tuple[MemoStaleDependency, ...] = field(default_factory=tuple)

    @property
    def stale_classes(self) -> tuple[MemoDependencyClass, ...]:
        """The changed classes, in ``DEPENDENCY_REPORT_ORDER``."""

        changed = {entry.dependency_class for entry in self.stale_dependencies}
        return tuple(item for item in DEPENDENCY_REPORT_ORDER if item in changed)
