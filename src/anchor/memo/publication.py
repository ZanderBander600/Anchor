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
    ValuationConsumerKind,
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
    - ``REFINANCE_REPORTING_NOT_AVAILABLE``: the selected Capital Structure
      configures a capital event, and the refinance-aware report -- the
      Common Equity / Partner primary returns, the sizing and bridge sections
      and the refinance headlines (Refinance V1 R-P, Sections 12.5 and 16.3) --
      is Stage 3 work. Until it exists, a report of the acquisition financing
      alone would misstate the recommended case, so none is issued or
      previewed. **Temporary:** Stage 3 removes this gate only once that
      presentation is implemented and tested.
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
    REFINANCE_REPORTING_NOT_AVAILABLE = "refinance_reporting_not_available"


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


class ReportPreviewRefusedError(PublicationRefusedError):
    """A draft whose report cannot be previewed yet, with the same typed
    refusals publication states. A subclass so every surface reports it
    through the one established refusal shape."""


#: The analyst-facing statement of the temporary Stage 3 report gate. No
#: identity of any event, position or Unit is named: the analyst knows which
#: Capital Structure they selected.
REFINANCE_REPORTING_NOT_AVAILABLE_MESSAGE = (
    "The selected Capital Structure includes a refinance, and Anchor cannot yet issue a report for it: the "
    "refinance-aware returns, the refinance sizing and bridge sections and the report headlines are not available "
    "yet. A report of the acquisition financing alone would misstate the recommended case, so none is issued or "
    "previewed. Select a Strategy whose Capital Structure has no refinance to publish now."
)


def refinance_reporting_refusal() -> PublicationRefusal:
    """The one refusal the temporary Stage 3 report gate states, shared by the
    readiness route, the publish route and the draft preview so the three can
    never word or code it differently."""

    return PublicationRefusal(
        code=PublicationRefusalCode.REFINANCE_REPORTING_NOT_AVAILABLE,
        message=REFINANCE_REPORTING_NOT_AVAILABLE_MESSAGE,
        field="capital_structure",
    )


class RequiredValuationReason(StrEnum):
    """Why one valuation is a dependency of the package being published.

    Two different reasons, kept apart because only one of them is visible in
    the report and a reader deserves to know which applies:

    - ``SELECTED``: the memo explicitly included this view. It will be shown.
    - ``CONSUMED``: the selected Capital Structure sized itself from this
      valuation at one exact scope -- a ``PctOfValue`` funding (Section 6), an
      LTV refinance (Refinance V1 Section 8.1), or both; ``consumers`` on the
      requirement says which. The memo may never display it, and the decision
      package still rests on it.

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
    #: What consumes a ``CONSUMED`` requirement, canonical and never empty for
    #: one; empty for ``SELECTED``. The refusal's wording is chosen from it.
    consumers: tuple[ValuationConsumerKind, ...] = ()
    #: The valuation's analyst-facing label, named by a refusal that must not
    #: print an opaque identity. ``""`` where none is known.
    label: str = ""


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
    #: Whether the selected Capital Structure configures a capital event, so
    #: the temporary Stage 3 report gate applies.
    capital_events_selected: bool = False


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


#: How a consumed requirement reads, by what consumes it. ``PctOfValue`` alone
#: keeps the accepted P7.10 wording word for word; a refinance, alone or beside
#: a funding, is named for what it is and by the valuation's label.
_REFINANCE_CONSUMED_WORDING = "the selected refinance sizes its LTV capacity from it"
_BOTH_CONSUMED_WORDING = (
    "the selected Capital Structure sizes both a percentage-of-value funding and a refinance's LTV capacity from it"
)


def _required_valuation_message(required: RequiredValuation) -> tuple[str, str]:
    """One refusal's message and field, chosen from the typed reason and
    consumers -- never from any text."""

    because, field = _REQUIRED_VALUATION_WORDING[required.reason]
    detail = f" {required.unavailable_detail}" if required.unavailable_detail else ""
    consumers = set(required.consumers)
    if required.reason is RequiredValuationReason.CONSUMED and ValuationConsumerKind.REFINANCE_LTV in consumers:
        because = (
            _BOTH_CONSUMED_WORDING if ValuationConsumerKind.PCT_OF_VALUE in consumers else _REFINANCE_CONSUMED_WORDING
        )
        named = f"The valuation '{required.label}'" if required.label else "A valuation"
        return (
            f"{named} has no value for the selected variant, and {because}, so the decision package depends on "
            f"it.{detail} It is never published as zero, as the acquisition price, as another valuation, or "
            "silently omitted.",
            field,
        )
    return (
        f"Valuation timepoint {required.timepoint_id!r} has no value for the selected variant, and "
        f"{because}, so the decision package depends on it.{detail} It is never published as zero, as "
        "the acquisition price, as another valuation, or silently omitted.",
        field,
    )


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
        message, field = _required_valuation_message(required)
        refusals.append(
            PublicationRefusal(
                code=PublicationRefusalCode.VALUATION_UNAVAILABLE_FOR_REQUIRED_VIEW,
                message=message,
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
    the most fundamental problem first -- and last the temporary Stage 3 report
    gate, which is stated *beside* every specific finding rather than instead
    of them."""

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
    if context.capital_events_selected:
        refusals.append(refinance_reporting_refusal())
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
