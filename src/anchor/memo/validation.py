"""Phase 7 Gate P7.10 Stage 2 -- whether an authored memo is well formed.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 7, 8
and 15; that document governs on any discrepancy.

**Structural only.** Every rule here is a property of the memo itself. Whether
the selected cell resolves, whether a cited Evidence Reference exists and is
approved, and whether a dependency has moved all depend on state outside the
memo, so none of them is an issue here: ``publication`` answers those, because a
memo that is perfectly well formed today may become unpublishable tomorrow
without a character of it changing.

**Refused whole.** A memo with any issue is never repaired, defaulted or
partially saved. Issues come in field order, then each collection's in
canonical ``item_id`` order; authored list position never participates.

**Nothing is defaulted.** A missing recommendation is an issue, not
``INSUFFICIENT_INFORMATION``; a missing complexity is an issue, not
``NOT_ASSESSED``. Both of those are real analyst statements, and Anchor never
makes one on the analyst's behalf.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .contracts import (
    AnalystRecommendation,
    DecisionPerspectiveKind,
    EvidenceSourceKind,
    ExecutionComplexity,
    InvestmentMemoDraft,
    MemoEvidenceReference,
    MemoItem,
    MemoRiskItem,
    MemoSection,
    MemoTermItem,
    RiskSeverity,
    SelectedDecision,
    TermPriority,
)


class MemoIssueCode(StrEnum):
    """Stable reasons an authored memo or Evidence Reference is not well
    formed."""

    BLANK_MEMO_ID = "blank_memo_id"
    BLANK_INVESTMENT_ID = "blank_investment_id"
    BLANK_DECISION_ASK = "blank_decision_ask"
    UNKNOWN_RECOMMENDATION = "unknown_recommendation"
    UNKNOWN_COMPLEXITY = "unknown_complexity"
    BLANK_ITEM_ID = "blank_item_id"
    DUPLICATE_ITEM_ID = "duplicate_item_id"
    BLANK_ITEM_TEXT = "blank_item_text"
    UNKNOWN_SECTION = "unknown_section"
    UNKNOWN_SEVERITY = "unknown_severity"
    UNKNOWN_TERM_PRIORITY = "unknown_term_priority"
    INVALID_DISPLAY_ORDER = "invalid_display_order"
    BLANK_STRATEGY_ID = "blank_strategy_id"
    BLANK_SCENARIO_ID = "blank_scenario_id"
    UNKNOWN_PERSPECTIVE = "unknown_perspective"
    PERSPECTIVE_SCOPE_MISMATCH = "perspective_scope_mismatch"
    BLANK_EVIDENCE_ID = "blank_evidence_id"
    DUPLICATE_EVIDENCE_ID = "duplicate_evidence_id"
    UNKNOWN_EVIDENCE_SOURCE_KIND = "unknown_evidence_source_kind"
    BLANK_EVIDENCE_TITLE = "blank_evidence_title"
    BLANK_EVIDENCE_REFERENCE = "blank_evidence_reference"
    INVALID_AS_OF_DATE = "invalid_as_of_date"


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoIssue:
    """One deterministic reason an authored memo is not well formed.
    ``item_id`` names the item concerned where one is identifiable, and
    ``field`` locates the finding."""

    code: MemoIssueCode
    message: str
    item_id: str | None = None
    field: str | None = None


class MemoValidationError(Exception):
    """One or more ``MemoIssue``. The memo is refused whole."""

    def __init__(self, issues: tuple[MemoIssue, ...]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


def _blank(text: object) -> bool:
    return not isinstance(text, str) or not text.strip()


def _issue(
    code: MemoIssueCode, message: str, *, item_id: str | None = None, field: str | None = None
) -> MemoIssue:
    return MemoIssue(code=code, message=message, item_id=item_id, field=field)


def _identity_issues(
    items: Iterable[object], *, field: str, issues: list[MemoIssue]
) -> None:
    """``item_id`` is nonblank and unique within its collection (Section 7.4).

    Uniqueness is checked per collection, not across all of them: a thesis item
    and a risk are different kinds of thing and share no id space. A duplicate
    is refused, never collapsed -- two items sharing an id would make a later
    edit ambiguous about which one it meant."""

    identities = [getattr(item, "item_id", "") for item in items]
    for unit_id, count in sorted(Counter(identities).items()):
        if count > 1:
            issues.append(
                _issue(
                    MemoIssueCode.DUPLICATE_ITEM_ID,
                    f"{field} states item {unit_id!r} {count} times; one item id names exactly one item, and no "
                    "item overrides another.",
                    item_id=unit_id,
                    field=field,
                )
            )
    for identity in identities:
        if _blank(identity):
            issues.append(
                _issue(
                    MemoIssueCode.BLANK_ITEM_ID,
                    f"{field} states an item with no id; every item names itself by a stable, opaque item id.",
                    field=field,
                )
            )


def _common_item_issues(item: object, *, field: str, issues: list[MemoIssue]) -> None:
    """The rules every repeating item shares: nonblank prose and a
    non-negative display order."""

    item_id = getattr(item, "item_id", None)
    if _blank(getattr(item, "text", None)):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_ITEM_TEXT,
                f"{field} item {item_id!r} has no text; an empty item is omitted rather than stored blank, and the "
                "report never manufactures boilerplate to fill one.",
                item_id=item_id,
                field=f"{field}.text",
            )
        )
    order = getattr(item, "display_order", None)
    if not isinstance(order, int) or isinstance(order, bool) or order < 0:
        issues.append(
            _issue(
                MemoIssueCode.INVALID_DISPLAY_ORDER,
                f"{field} item {item_id!r} states display order {order!r}; an explicit display order is a "
                "non-negative integer, and it is presentation only.",
                item_id=item_id,
                field=f"{field}.display_order",
            )
        )


def validate_memo_items(items: Iterable[MemoItem]) -> tuple[MemoIssue, ...]:
    """Every structural reason an ordinary item collection is not well
    formed."""

    ordered = list(items)
    issues: list[MemoIssue] = []
    _identity_issues(ordered, field="items", issues=issues)
    for item in sorted(ordered, key=lambda entry: getattr(entry, "item_id", "")):
        _common_item_issues(item, field="items", issues=issues)
        if not isinstance(getattr(item, "section", None), MemoSection):
            issues.append(
                _issue(
                    MemoIssueCode.UNKNOWN_SECTION,
                    f"Item {getattr(item, 'item_id', None)!r} states section {getattr(item, 'section', None)!r}; "
                    f"a memo item belongs to one of: {', '.join(member.value for member in MemoSection)}.",
                    item_id=getattr(item, "item_id", None),
                    field="items.section",
                )
            )
    return tuple(issues)


def validate_memo_risk_items(items: Iterable[MemoRiskItem]) -> tuple[MemoIssue, ...]:
    """Every structural reason a risk collection is not well formed.

    ``severity`` and ``residual_risk`` are required analyst labels with no
    default: ``NOT_ASSESSED`` is a statement the analyst makes, never one Anchor
    makes for them (Section 7.4)."""

    ordered = list(items)
    issues: list[MemoIssue] = []
    _identity_issues(ordered, field="risk_items", issues=issues)
    for item in sorted(ordered, key=lambda entry: getattr(entry, "item_id", "")):
        _common_item_issues(item, field="risk_items", issues=issues)
        for name in ("severity", "residual_risk"):
            if not isinstance(getattr(item, name, None), RiskSeverity):
                issues.append(
                    _issue(
                        MemoIssueCode.UNKNOWN_SEVERITY,
                        f"Risk {getattr(item, 'item_id', None)!r} states {name} "
                        f"{getattr(item, name, None)!r}; it is one of: "
                        f"{', '.join(member.value for member in RiskSeverity)}. It is an analyst label and is never "
                        "derived from a return.",
                        item_id=getattr(item, "item_id", None),
                        field=f"risk_items.{name}",
                    )
                )
    return tuple(issues)


def validate_memo_term_items(items: Iterable[MemoTermItem]) -> tuple[MemoIssue, ...]:
    """Every structural reason a term collection is not well formed."""

    ordered = list(items)
    issues: list[MemoIssue] = []
    _identity_issues(ordered, field="term_items", issues=issues)
    for item in sorted(ordered, key=lambda entry: getattr(entry, "item_id", "")):
        _common_item_issues(item, field="term_items", issues=issues)
        if not isinstance(getattr(item, "priority", None), TermPriority):
            issues.append(
                _issue(
                    MemoIssueCode.UNKNOWN_TERM_PRIORITY,
                    f"Term {getattr(item, 'item_id', None)!r} states priority "
                    f"{getattr(item, 'priority', None)!r}; it is one of: "
                    f"{', '.join(member.value for member in TermPriority)}.",
                    item_id=getattr(item, "item_id", None),
                    field="term_items.priority",
                )
            )
    return tuple(issues)


def validate_selected_decision(selected: SelectedDecision | None) -> tuple[MemoIssue, ...]:
    """Every structural reason a selected decision is not well formed
    (Section 7.3).

    The perspective and its scope must agree exactly: ``POSITION`` states a
    ``position_id`` and no ``partner_id``, ``PARTNER`` the converse, and
    ``PROJECT`` neither. A mismatched pair is refused rather than resolved by
    preferring one -- guessing which stakeholder the analyst meant is precisely
    what a decision memo must not do.

    ``None`` is well formed: a draft may be authored before its cell is chosen.
    Publishing without one is refused by ``publication``, not here."""

    if selected is None:
        return ()
    issues: list[MemoIssue] = []
    if _blank(selected.strategy_id):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_STRATEGY_ID,
                "The selected decision names no Strategy; it names exactly one, including the implicit Base "
                "Strategy by its reserved key.",
                field="selected_decision.strategy_id",
            )
        )
    if _blank(selected.scenario_id):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_SCENARIO_ID,
                "The selected decision names no Scenario; it names exactly one, including the implicit Base "
                "Scenario by its reserved key.",
                field="selected_decision.scenario_id",
            )
        )
    perspective = selected.perspective
    if not isinstance(perspective, DecisionPerspectiveKind):
        issues.append(
            _issue(
                MemoIssueCode.UNKNOWN_PERSPECTIVE,
                f"The selected decision states perspective {perspective!r}; it is one of: "
                f"{', '.join(member.value for member in DecisionPerspectiveKind)}.",
                field="selected_decision.perspective",
            )
        )
        return tuple(issues)

    expected: dict[DecisionPerspectiveKind, tuple[str | None, str | None]] = {
        DecisionPerspectiveKind.PROJECT: (None, None),
        DecisionPerspectiveKind.POSITION: (selected.position_id, None),
        DecisionPerspectiveKind.PARTNER: (None, selected.partner_id),
    }
    wants_position, wants_partner = expected[perspective]
    states_position = selected.position_id is not None
    states_partner = selected.partner_id is not None
    coherent = (
        (not states_position and not states_partner)
        if perspective is DecisionPerspectiveKind.PROJECT
        else (states_position and not states_partner and not _blank(wants_position))
        if perspective is DecisionPerspectiveKind.POSITION
        else (states_partner and not states_position and not _blank(wants_partner))
    )
    if not coherent:
        issues.append(
            _issue(
                MemoIssueCode.PERSPECTIVE_SCOPE_MISMATCH,
                f"The selected decision states perspective {perspective.value!r} with position_id "
                f"{selected.position_id!r} and partner_id {selected.partner_id!r}. A PROJECT perspective states "
                "neither, a POSITION perspective states exactly a position_id, and a PARTNER perspective states "
                "exactly a partner_id; neither is inferred from the other.",
                field="selected_decision",
            )
        )
    return tuple(issues)


def validate_evidence_reference(evidence: MemoEvidenceReference) -> tuple[MemoIssue, ...]:
    """Every structural reason one Evidence Reference is not well formed
    (Section 8).

    ``approved`` is deliberately not validated as a value: both states are
    legitimate, and an unapproved reference is a real, storable record. What it
    may *support* is a separate question the valuation and publication layers
    answer."""

    issues: list[MemoIssue] = []
    if _blank(evidence.evidence_id):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_EVIDENCE_ID,
                "An Evidence Reference names itself by a stable, nonblank, opaque evidence id.",
                field="evidence_id",
            )
        )
    if _blank(evidence.investment_id):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_INVESTMENT_ID,
                f"Evidence Reference {evidence.evidence_id!r} names no Investment; every reference belongs to "
                "exactly one Investment.",
                field="investment_id",
            )
        )
    if not isinstance(evidence.source_kind, EvidenceSourceKind):
        issues.append(
            _issue(
                MemoIssueCode.UNKNOWN_EVIDENCE_SOURCE_KIND,
                f"Evidence Reference {evidence.evidence_id!r} states source kind {evidence.source_kind!r}; it is "
                f"one of: {', '.join(member.value for member in EvidenceSourceKind)}.",
                field="source_kind",
            )
        )
    if _blank(evidence.title):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_EVIDENCE_TITLE,
                f"Evidence Reference {evidence.evidence_id!r} has no title; a reference a reader cannot identify "
                "cannot support a claim.",
                field="title",
            )
        )
    if _blank(evidence.reference):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_EVIDENCE_REFERENCE,
                f"Evidence Reference {evidence.evidence_id!r} states no reference; a document anchor, URL or "
                "analyst note is required. P7.10 stores the reference, never a copy of the source.",
                field="reference",
            )
        )
    if not isinstance(evidence.display_order, int) or isinstance(evidence.display_order, bool) or evidence.display_order < 0:
        issues.append(
            _issue(
                MemoIssueCode.INVALID_DISPLAY_ORDER,
                f"Evidence Reference {evidence.evidence_id!r} states display order {evidence.display_order!r}; an "
                "explicit display order is a non-negative integer, and it is presentation only.",
                field="display_order",
            )
        )
    return tuple(issues)


def parse_as_of_date(raw: object, *, field: str = "as_of_date") -> date | None:
    """An optional ISO-8601 date, or a ``MemoValidationError``.

    Here rather than in the transport layer on purpose. Parsing a date needs
    ``except ValueError``, and broad ``ValueError`` handling in a route is how
    a validator's own refusal gets swallowed and reported as something else.
    The domain raises its own error, and the route catches the error it
    already catches."""

    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    raise MemoValidationError(
        (
            _issue(
                MemoIssueCode.INVALID_AS_OF_DATE,
                f"{field} is {raw!r}; an as-of date is an ISO-8601 date string, or null when the source "
                "states none. It is never inferred from today's date.",
                field=field,
            ),
        )
    )


def require_valid_evidence_reference(evidence: MemoEvidenceReference) -> MemoEvidenceReference:
    """``evidence`` unchanged, or raise ``MemoValidationError``."""

    issues = validate_evidence_reference(evidence)
    if issues:
        raise MemoValidationError(issues)
    return evidence


def validate_memo_draft(draft: InvestmentMemoDraft) -> tuple[MemoIssue, ...]:
    """Every structural reason ``draft`` is not a well-formed memo, or ``()``.

    The decision ask is required: a memo whose ask is blank does not state what
    decision is being requested, which is the one question Section 1 says the
    output must answer."""

    issues: list[MemoIssue] = []
    if _blank(draft.memo_id):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_MEMO_ID,
                "A memo names itself by a stable, nonblank, opaque memo id.",
                field="memo_id",
            )
        )
    if _blank(draft.investment_id):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_INVESTMENT_ID,
                f"Memo {draft.memo_id!r} names no Investment; a memo belongs to exactly one Investment.",
                field="investment_id",
            )
        )
    if _blank(draft.decision_ask):
        issues.append(
            _issue(
                MemoIssueCode.BLANK_DECISION_ASK,
                f"Memo {draft.memo_id!r} states no decision ask; a decision memo states what decision is requested.",
                field="decision_ask",
            )
        )
    if not isinstance(draft.analyst_recommendation, AnalystRecommendation):
        issues.append(
            _issue(
                MemoIssueCode.UNKNOWN_RECOMMENDATION,
                f"Memo {draft.memo_id!r} states analyst recommendation {draft.analyst_recommendation!r}; it is one "
                f"of: {', '.join(member.value for member in AnalystRecommendation)}. It is the analyst's own "
                "statement and is never defaulted, inferred or proposed by AI.",
                field="analyst_recommendation",
            )
        )
    if not isinstance(draft.execution_complexity, ExecutionComplexity):
        issues.append(
            _issue(
                MemoIssueCode.UNKNOWN_COMPLEXITY,
                f"Memo {draft.memo_id!r} states execution complexity {draft.execution_complexity!r}; it is one of: "
                f"{', '.join(member.value for member in ExecutionComplexity)}.",
                field="execution_complexity",
            )
        )
    issues.extend(validate_memo_items(draft.items))
    issues.extend(validate_memo_risk_items(draft.risk_items))
    issues.extend(validate_memo_term_items(draft.term_items))
    issues.extend(validate_selected_decision(draft.selected_decision))

    for evidence_id, count in sorted(Counter(draft.evidence_ids).items()):
        if count > 1:
            issues.append(
                _issue(
                    MemoIssueCode.DUPLICATE_EVIDENCE_ID,
                    f"Memo {draft.memo_id!r} cites Evidence Reference {evidence_id!r} {count} times; one citation "
                    "names one reference.",
                    field="evidence_ids",
                )
            )
    for evidence_id in draft.evidence_ids:
        if _blank(evidence_id):
            issues.append(
                _issue(
                    MemoIssueCode.BLANK_EVIDENCE_ID,
                    f"Memo {draft.memo_id!r} cites an Evidence Reference with no id.",
                    field="evidence_ids",
                )
            )
    return tuple(issues)


def require_valid_memo_draft(draft: InvestmentMemoDraft) -> InvestmentMemoDraft:
    """``draft`` unchanged, or raise ``MemoValidationError``."""

    issues = validate_memo_draft(draft)
    if issues:
        raise MemoValidationError(issues)
    return draft
