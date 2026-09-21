"""Phase 7 Gate P7.10 Stage 2 -- whether a draft may become an immutable
version.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 7.3,
9, 14 and 15; that document governs on any discrepancy. Ratified decision R-H is
the version model behind it.

**Fail closed.** Publishing asserts that a complete, internally consistent
decision package existed at one moment. Every prerequisite below is therefore a
refusal with a specific reason, never a warning and never a silently partial
publication. The product disables publication with those reasons; it never
relies on a generic failure for a decision-critical refusal (Section 14).

**Refusals are not errors.** A draft that is not yet publishable is an ordinary,
expected state of an analyst's workspace. These refusals are returned as
structured reasons an analyst can act on -- never as a server error, and never
as a half-written version.

**One transaction (Section 15).** This module decides; the store writes. Either
the complete immutable version and its dependency ledger exist, or neither does.

**Immutable afterwards (R-H).** Nothing here, and no write path anywhere in
Anchor, edits a published version. A later draft edit produces a *new* version;
it never reaches back into an earlier one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from .contracts import (
    DecisionPerspectiveKind,
    InvestmentMemoDraft,
    MemoEvidenceReference,
    SelectedDecision,
)
from .validation import validate_memo_draft


class PublicationRefusalCode(StrEnum):
    """Stable reasons a draft cannot be published right now.

    Each names one missing or inconsistent prerequisite, so the product can say
    exactly what the analyst must do rather than that publication "failed".

    - ``MEMO_INVALID``: the draft is not well formed. Its own issues say why.
    - ``NO_SELECTED_DECISION``: no decision cell is named. A memo recommends one
      cell (Section 7.3); publishing without one would publish a recommendation
      about nothing.
    - ``SELECTED_STRATEGY_MISSING`` / ``SELECTED_SCENARIO_MISSING``: the named
      Strategy or Scenario no longer exists.
    - ``SELECTED_PERSPECTIVE_MISSING``: the named position or partner is not a
      perspective of this Investment.
    - ``SELECTED_CELL_UNRESOLVED``: the selected cell does not currently resolve
      and complete. Section 7.3 requires that it does before a version exists.
    - ``BLANK_DECISION_ASK``: the ask is empty.
    - ``EVIDENCE_NOT_FOUND``: a cited reference does not exist.
    - ``EVIDENCE_NOT_APPROVED``: a cited reference is not approved, so the memo
      would present an unapproved source as a supporting one (Section 8).
    - ``VALUATION_UNAVAILABLE_FOR_REQUIRED_VIEW``: a valuation the package
      *depends on* -- one the memo selected, or one a ``PctOfValue`` funding
      consumed -- has no value. The version is not published with a fabricated
      or omitted figure in its place. An authored but unselected and unconsumed
      definition is not a dependency and never reaches this code.
    """

    MEMO_INVALID = "memo_invalid"
    NO_SELECTED_DECISION = "no_selected_decision"
    SELECTED_STRATEGY_MISSING = "selected_strategy_missing"
    SELECTED_SCENARIO_MISSING = "selected_scenario_missing"
    SELECTED_PERSPECTIVE_MISSING = "selected_perspective_missing"
    SELECTED_CELL_UNRESOLVED = "selected_cell_unresolved"
    BLANK_DECISION_ASK = "blank_decision_ask"
    EVIDENCE_NOT_FOUND = "evidence_not_found"
    EVIDENCE_NOT_APPROVED = "evidence_not_approved"
    VALUATION_UNAVAILABLE_FOR_REQUIRED_VIEW = "valuation_unavailable_for_required_view"


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicationRefusal:
    """One specific reason publication is refused, with the thing it concerns.

    ``unavailable_reason`` carries the upstream structured reason code where the
    refusal has one -- a valuation that could not be resolved states *its own*
    typed reason here rather than being flattened into publication's vocabulary.
    A reader is told "the forward NOI is not positive", not merely "unavailable"
    (Section 16)."""

    code: PublicationRefusalCode
    message: str
    scope_id: str | None = None
    field: str | None = None
    unavailable_reason: str | None = None


class PublicationRefusedError(Exception):
    """A draft that may not be published, with every reason. Nothing is
    written: publication is one transaction, and a refused one performs no part
    of itself."""

    def __init__(self, refusals: tuple[PublicationRefusal, ...]) -> None:
        self.refusals = tuple(refusals)
        super().__init__("; ".join(refusal.message for refusal in self.refusals))


class RequiredValuationReason(StrEnum):
    """Why one valuation is a dependency of the package being published.

    Two different reasons, kept apart because only one of them is visible in
    the report and a reader deserves to know which applies:

    - ``SELECTED``: the memo explicitly included this view. It will be shown.
    - ``CONSUMED``: a ``PctOfValue`` funding of the selected variant sized
      itself from this valuation (Section 6). The memo may never display it,
      and the decision package still rests on it.

    An authored definition with neither reason is not a dependency at all."""

    SELECTED = "selected"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True, kw_only=True)
class RequiredValuation:
    """One valuation the package depends on, and whether it currently resolves.

    ``unavailable_reason`` and ``unavailable_detail`` carry the structured
    reason from the Stage 2 adapter, so a refusal quotes the specific finding --
    "the analyst has not approved the source", "direct capitalisation of a
    non-positive NOI has no meaning" -- rather than a generic "unavailable"."""

    timepoint_id: str
    reason: RequiredValuationReason
    available: bool
    unavailable_reason: str | None = None
    unavailable_detail: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicationContext:
    """What the caller has already established about the current state, as the
    publication rules read it.

    This module performs no I/O and resolves nothing: the store and the variant
    services gather these facts, and this module judges them. That keeps the
    rules testable without a database and keeps a second resolution pathway from
    appearing.

    - ``strategy_exists`` / ``scenario_exists``: whether the selected keys still
      name something. The reserved implicit Base keys always do.
    - ``perspective_exists``: whether the selected position or partner is a
      perspective of this Investment. ``True`` for ``PROJECT``, which needs no
      scope.
    - ``cell_resolves``: whether the selected cell currently resolves and
      completes (Section 7.3). ``cell_detail`` carries the variant's own reason
      when it does not.
    - ``evidence``: every Evidence Reference of the Investment, by id.
    - ``required_valuations``: for each valuation the package actually
      *depends* on, whether it currently has a value. Only the depended-on ones
      appear -- see ``RequiredValuation`` -- so an exploratory definition the
      memo neither selected nor consumed is simply absent and cannot block
      anything.
    """

    strategy_exists: bool
    scenario_exists: bool
    perspective_exists: bool
    cell_resolves: bool
    cell_detail: str = ""
    evidence: Mapping[str, MemoEvidenceReference]
    required_valuations: tuple[RequiredValuation, ...] = ()


def _selection_refusals(
    selected: SelectedDecision, context: PublicationContext
) -> list[PublicationRefusal]:
    """The selected cell exists and resolves (Section 7.3)."""

    refusals: list[PublicationRefusal] = []
    if not context.strategy_exists:
        refusals.append(
            PublicationRefusal(
                code=PublicationRefusalCode.SELECTED_STRATEGY_MISSING,
                message=(
                    f"The memo recommends Strategy {selected.strategy_id!r}, which this Investment no longer "
                    "states. Select a Strategy that exists before publishing."
                ),
                scope_id=selected.strategy_id,
                field="selected_decision.strategy_id",
            )
        )
    if not context.scenario_exists:
        refusals.append(
            PublicationRefusal(
                code=PublicationRefusalCode.SELECTED_SCENARIO_MISSING,
                message=(
                    f"The memo recommends Scenario {selected.scenario_id!r}, which this Investment no longer "
                    "states. Select a Scenario that exists before publishing."
                ),
                scope_id=selected.scenario_id,
                field="selected_decision.scenario_id",
            )
        )
    if not context.perspective_exists:
        scope = (
            selected.position_id
            if selected.perspective is DecisionPerspectiveKind.POSITION
            else selected.partner_id
        )
        refusals.append(
            PublicationRefusal(
                code=PublicationRefusalCode.SELECTED_PERSPECTIVE_MISSING,
                message=(
                    f"The memo recommends the {selected.perspective.value} perspective {scope!r}, which is not a "
                    "perspective of this Investment. No other stakeholder's figures are shown in its place."
                ),
                scope_id=scope,
                field="selected_decision",
            )
        )
    if not context.cell_resolves:
        refusals.append(
            PublicationRefusal(
                code=PublicationRefusalCode.SELECTED_CELL_UNRESOLVED,
                message=(
                    f"Strategy {selected.strategy_id!r} x Scenario {selected.scenario_id!r} does not currently "
                    f"resolve and complete, so there is no result to publish a recommendation about"
                    f"{': ' + context.cell_detail if context.cell_detail else '.'}"
                ),
                field="selected_decision",
            )
        )
    return refusals


def _evidence_refusals(
    evidence_ids: Iterable[str], context: PublicationContext
) -> list[PublicationRefusal]:
    """Every cited Evidence Reference exists and is approved (Section 8).

    ``evidence_ids`` is the *union* of the memo's register and every claim-level
    link, so a source cited only by one risk is held to exactly the same
    standard as one cited by the package as a whole. That is the point of R-G:
    a reviewer must be able to follow a claim to a source they can trust.

    An unapproved reference is never silently downgraded to an unsupported
    assertion at publication time: the analyst either approves it or removes the
    citation, so a published version never carries a source the analyst did not
    stand behind."""

    refusals: list[PublicationRefusal] = []
    for evidence_id in sorted(set(evidence_ids)):
        found = context.evidence.get(evidence_id)
        if found is None:
            refusals.append(
                PublicationRefusal(
                    code=PublicationRefusalCode.EVIDENCE_NOT_FOUND,
                    message=(
                        f"The memo cites Evidence Reference {evidence_id!r}, which this Investment does not hold."
                    ),
                    scope_id=evidence_id,
                    field="evidence_ids",
                )
            )
            continue
        if not found.approved:
            refusals.append(
                PublicationRefusal(
                    code=PublicationRefusalCode.EVIDENCE_NOT_APPROVED,
                    message=(
                        f"The memo cites Evidence Reference {evidence_id!r} ({found.title!r}), which is not "
                        "approved. An unapproved source is never published as a supporting one."
                    ),
                    scope_id=evidence_id,
                    field="evidence_ids",
                )
            )
    return refusals


#: How each reason reads in a refusal, and which field an analyst would fix.
_REQUIRED_VALUATION_WORDING: dict[RequiredValuationReason, tuple[str, str]] = {
    RequiredValuationReason.SELECTED: (
        "the memo selects it for inclusion",
        "selected_valuation_timepoint_ids",
    ),
    RequiredValuationReason.CONSUMED: (
        "a percentage-of-value funding of the selected variant is sized from it",
        "capital_structure",
    ),
}


def _valuation_refusals(context: PublicationContext) -> list[PublicationRefusal]:
    """Every valuation the package **depends on** currently has a value.

    The dependency, not the existence, is what matters. An Investment may hold
    exploratory valuation definitions an analyst is still working out; one of
    those being unavailable says nothing about the decision package and must not
    block it. What must block it is a valuation the memo *selected* for
    inclusion, or one a ``PctOfValue`` funding of the selected variant
    *consumed* -- the second of which the report may never display and the
    package still rests on.

    A blocked publication quotes the valuation's own structured reason. Nothing
    is published as zero, as the acquisition price, as another timepoint's
    value, or silently omitted."""

    refusals: list[PublicationRefusal] = []
    for required in sorted(
        context.required_valuations, key=lambda entry: (entry.timepoint_id, entry.reason.value)
    ):
        if required.available:
            continue
        because, field = _REQUIRED_VALUATION_WORDING[required.reason]
        detail = f" {required.unavailable_detail}" if required.unavailable_detail else ""
        refusals.append(
            PublicationRefusal(
                code=PublicationRefusalCode.VALUATION_UNAVAILABLE_FOR_REQUIRED_VIEW,
                message=(
                    f"Valuation timepoint {required.timepoint_id!r} has no value for the selected variant, and "
                    f"{because}, so the decision package depends on it.{detail} It is never published as zero, as "
                    "the acquisition price, as another valuation, or silently omitted."
                ),
                scope_id=required.timepoint_id,
                field=field,
                unavailable_reason=required.unavailable_reason,
            )
        )
    return refusals


def publication_refusals(
    draft: InvestmentMemoDraft, context: PublicationContext
) -> tuple[PublicationRefusal, ...]:
    """Every reason ``draft`` may not be published right now, or ``()``.

    Ordered: the draft's own well-formedness first, then the selected cell, then
    evidence, then the valuations the package depends on -- so the analyst reads
    the most fundamental problem first."""

    refusals: list[PublicationRefusal] = [
        PublicationRefusal(
            code=PublicationRefusalCode.MEMO_INVALID,
            message=issue.message,
            scope_id=issue.item_id,
            field=issue.field,
        )
        for issue in validate_memo_draft(draft)
    ]
    if not draft.decision_ask.strip():
        refusals.append(
            PublicationRefusal(
                code=PublicationRefusalCode.BLANK_DECISION_ASK,
                message=(
                    "The memo states no decision ask. A published version states what decision is requested."
                ),
                field="decision_ask",
            )
        )
    selected = draft.selected_decision
    if selected is None:
        refusals.append(
            PublicationRefusal(
                code=PublicationRefusalCode.NO_SELECTED_DECISION,
                message=(
                    "The memo names no Strategy, Scenario and perspective. A published version recommends exactly "
                    "one decision cell."
                ),
                field="selected_decision",
            )
        )
    else:
        refusals.extend(_selection_refusals(selected, context))
    refusals.extend(_evidence_refusals(draft.cited_evidence_ids(), context))
    refusals.extend(_valuation_refusals(context))
    return tuple(refusals)


def require_publishable(
    draft: InvestmentMemoDraft, context: PublicationContext
) -> InvestmentMemoDraft:
    """``draft`` unchanged, or raise ``PublicationRefusedError`` with every
    reason. Nothing partial is ever returned."""

    refusals = publication_refusals(draft, context)
    if refusals:
        raise PublicationRefusedError(refusals)
    return draft


def next_version_number(existing: Iterable[int]) -> int:
    """The next version number within an Investment: monotonically increasing,
    and never reusing a number (Section 9).

    Derived from the highest number ever issued rather than from the count, so
    a version number is stable for the life of the Investment."""

    numbers = list(existing)
    return (max(numbers) + 1) if numbers else 1
