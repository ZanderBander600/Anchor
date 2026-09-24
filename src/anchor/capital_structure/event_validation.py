"""Refinance & Capital Events V1 -- structural validation of capital events.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 6, 7.4,
10.3 and 15.1 (ratified); that document governs on any discrepancy. Pure: no
I/O, no execution, no valuation, no debt function.

These are the **authoring faults wholly inside a Capital Structure**
(decision R-Q). A fact that lives outside the structure -- the hold period, a
valuation, forward NOI, whether a Unit carries an acquisition loan in this
variant, a balance at the event month -- is judged at execution and becomes a
typed unavailable state, never a refusal here.

``validate_capital_events`` returns ``()`` for a structure that states no event
and no ``RefinanceProceeds`` funding, so every structure that existed before
this gate validates exactly as it did. Issues come in a deterministic order that
never depends on how events, retiring references or costs were listed.

``succession_pairs`` states the one narrow exception to P7.7 priority
uniqueness (decision R-N): a retiring position and its replacement may share a
priority, because their outstanding intervals never overlap.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from math import isfinite

from .contracts import (
    LEGACY_ACQUISITION_LOAN_PRIORITY,
    MONTHS_PER_HOLD_YEAR,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureIssue,
    CapitalStructureIssueCode,
    DebtTerms,
    FundingEvent,
    PositionClass,
    PositionFee,
    PositionScope,
    RefinanceProceeds,
    ScopeKind,
)
from .events import (
    AuthoredPositionRef,
    CapitalEventKind,
    CapitalStructureWithEvents,
    EventTiming,
    FixedProceedsCap,
    LegacyAcquisitionLoanRef,
    MaxLtvConstraint,
    MinDscrConstraint,
    RefinanceCostKind,
    RefinanceCostLine,
    RefinanceEvent,
    RefinanceSizing,
    RefinanceValuationRef,
)

_DEBT_CLASSES = frozenset({PositionClass.SENIOR_DEBT, PositionClass.MEZZANINE_DEBT})

#: The shortest replacement V1 accepts: its first twelve months of service
#: must exist. A shorter maturity is bridge financing (Section 7.4).
MINIMUM_REPLACEMENT_TERM_MONTHS = MONTHS_PER_HOLD_YEAR


def _is_text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(float(value))
    except OverflowError:
        return False


def _is_whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _scope_key(scope: object) -> tuple[int, str]:
    if isinstance(scope, PositionScope) and scope.kind is ScopeKind.UNIT and isinstance(scope.unit_id, str):
        return (0, scope.unit_id)
    return (1, "")


def _scope_is_valid(scope: object) -> bool:
    if not isinstance(scope, PositionScope) or not isinstance(scope.kind, ScopeKind):
        return False
    if scope.kind is ScopeKind.UNIT:
        return _is_text(scope.unit_id)
    return scope.unit_id is None


def _event_key(event: object) -> tuple[int, str, str]:
    if isinstance(event, RefinanceEvent):
        rank, unit_id = _scope_key(event.scope)
        return (rank, unit_id, event.event_id if isinstance(event.event_id, str) else repr(event.event_id))
    return (2, "", repr(event))


def _ref_key(ref: object) -> tuple[str, str]:
    if isinstance(ref, AuthoredPositionRef):
        return ("authored", str(ref.position_id))
    if isinstance(ref, LegacyAcquisitionLoanRef):
        return ("legacy", str(ref.unit_id))
    return ("unknown", repr(ref))


def _issue(
    code: CapitalStructureIssueCode, message: str, *, event_id: object = None, field: str | None = None
) -> CapitalStructureIssue:
    identity = event_id if isinstance(event_id, str) else None
    return CapitalStructureIssue(code=code, message=message, position_id=identity, field=field)


def _positions(structure: CapitalStructure) -> dict[str, CapitalPosition]:
    found: dict[str, CapitalPosition] = {}
    for position in structure.positions if isinstance(structure.positions, tuple) else ():
        if isinstance(position, CapitalPosition) and isinstance(position.position_id, str):
            found.setdefault(position.position_id, position)
    return found


def _refinance_proceeds_fundings(structure: CapitalStructure) -> list[tuple[CapitalPosition, FundingEvent]]:
    found: list[tuple[CapitalPosition, FundingEvent]] = []
    for position in _positions(structure).values():
        if not isinstance(position.funding, tuple):
            continue
        for event in position.funding:
            if isinstance(event, FundingEvent) and isinstance(event.amount_rule, RefinanceProceeds):
                found.append((position, event))
    return sorted(found, key=lambda pair: (pair[0].position_id, str(pair[1].event_id)))


def _events(structure: object) -> tuple[object, ...] | None:
    """The events stated, or ``None`` when ``events`` is not a tuple."""

    if not isinstance(structure, CapitalStructureWithEvents):
        return ()
    return structure.events if isinstance(structure.events, tuple) else None


def _well_formed_refinances(structure: CapitalStructure) -> tuple[RefinanceEvent, ...]:
    events = _events(structure) or ()
    return tuple(
        sorted(
            (event for event in events if isinstance(event, RefinanceEvent) and isinstance(event.event_id, str)),
            key=_event_key,
        )
    )


# =============================================================================
# Succession (decision R-N)
# =============================================================================


def succession_pairs(structure: object) -> tuple[frozenset[frozenset[str]], frozenset[str]]:
    """The priority collisions a refinance legitimately creates.

    - The first element holds each ``{retiring, replacement}`` pair of authored
      positions: the replacement succeeds to the retiring position's rank.
    - The second holds each replacement that succeeds to a Unit's acquisition
      loan, and so may hold that Unit's reserved priority 1.

    A pair is admitted only where both positions share the event's scope and
    the replacement's priority equals the retiring rank; anything else stays a
    duplicate, and the event itself is refused for it."""

    if not isinstance(structure, CapitalStructureWithEvents):
        return frozenset(), frozenset()
    positions = _positions(structure)
    pairs: set[frozenset[str]] = set()
    legacy: set[str] = set()
    for event in _well_formed_refinances(structure):
        replacement = positions.get(event.replacement_position_id) if isinstance(event.replacement_position_id, str) else None
        if replacement is None or replacement.scope != event.scope or not isinstance(event.retiring, tuple):
            continue
        for ref in event.retiring:
            if isinstance(ref, AuthoredPositionRef):
                retiring = positions.get(ref.position_id) if isinstance(ref.position_id, str) else None
                if (
                    retiring is not None
                    and retiring.scope == event.scope
                    and retiring.priority == replacement.priority
                    and retiring.position_id != replacement.position_id
                ):
                    pairs.add(frozenset({retiring.position_id, replacement.position_id}))
            elif (
                isinstance(ref, LegacyAcquisitionLoanRef)
                and event.scope.kind is ScopeKind.UNIT
                and ref.unit_id == event.scope.unit_id
                and replacement.priority == LEGACY_ACQUISITION_LOAN_PRIORITY
            ):
                legacy.add(replacement.position_id)
    return frozenset(pairs), frozenset(legacy)


# =============================================================================
# One event
# =============================================================================


def _timing_issues(event: RefinanceEvent) -> list[CapitalStructureIssue]:
    timing = event.timing
    if not isinstance(timing, EventTiming):
        return [
            _issue(
                CapitalStructureIssueCode.INVALID_CAPITAL_EVENT,
                f"Event {event.event_id!r} states no EventTiming.",
                event_id=event.event_id,
                field="timing",
            )
        ]
    issues: list[CapitalStructureIssue] = []
    month = timing.model_month
    if not _is_whole(month) or month <= 0 or month % MONTHS_PER_HOLD_YEAR != 0:
        issues.append(
            _issue(
                CapitalStructureIssueCode.EVENT_MONTH_NOT_HOLD_YEAR_END,
                f"Event {event.event_id!r} is at model month {month!r}. A V1 refinance occurs only at a hold-year "
                "end after closing (model month 12, 24, ...); closing and intra-year events are deferred.",
                event_id=event.event_id,
                field="timing.model_month",
            )
        )
    if timing.sequence != 1 or not _is_whole(timing.sequence):
        issues.append(
            _issue(
                CapitalStructureIssueCode.UNSUPPORTED_EVENT_SEQUENCE,
                f"Event {event.event_id!r} states sequence {timing.sequence!r}; V1 permits one event per scope, so "
                "its sequence is 1.",
                event_id=event.event_id,
                field="timing.sequence",
            )
        )
    return issues


def _event_month(event: RefinanceEvent) -> int | None:
    timing = event.timing
    if isinstance(timing, EventTiming) and _is_whole(timing.model_month):
        return timing.model_month
    return None


def _retiring_issues(event: RefinanceEvent, positions: dict[str, CapitalPosition]) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode
    if not isinstance(event.retiring, tuple) or not event.retiring:
        return [
            _issue(
                code.NO_RETIRING_POSITION,
                f"Event {event.event_id!r} retires nothing; a V1 refinance retires at least one debt position.",
                event_id=event.event_id,
                field="retiring",
            )
        ]
    issues: list[CapitalStructureIssue] = []
    for key, count in sorted(Counter(_ref_key(ref) for ref in event.retiring).items()):
        if count > 1:
            issues.append(
                _issue(
                    code.RETIRING_POSITION_DUPLICATED,
                    f"Event {event.event_id!r} retires {key[1]!r} {count} times.",
                    event_id=event.event_id,
                    field="retiring",
                )
            )
    for ref in sorted(event.retiring, key=_ref_key):
        if isinstance(ref, LegacyAcquisitionLoanRef):
            if not (event.scope.kind is ScopeKind.UNIT and ref.unit_id == event.scope.unit_id):
                issues.append(
                    _issue(
                        code.RETIRING_POSITION_SCOPE_MISMATCH,
                        f"Event {event.event_id!r} retires the acquisition loan of Unit {ref.unit_id!r}, which is "
                        "outside its scope. A refinance retires only debt of its own exact scope.",
                        event_id=event.event_id,
                        field="retiring",
                    )
                )
            continue
        if not isinstance(ref, AuthoredPositionRef) or not _is_text(ref.position_id):
            issues.append(
                _issue(
                    code.INVALID_CAPITAL_EVENT,
                    f"Event {event.event_id!r} names a retiring position {ref!r} that is not a position reference.",
                    event_id=event.event_id,
                    field="retiring",
                )
            )
            continue
        position = positions.get(ref.position_id)
        if position is None:
            issues.append(
                _issue(
                    code.RETIRING_POSITION_NOT_FOUND,
                    f"Event {event.event_id!r} retires {ref.position_id!r}, which this Capital Structure does not "
                    "hold.",
                    event_id=event.event_id,
                    field="retiring",
                )
            )
            continue
        if position.position_class not in _DEBT_CLASSES or position.position_id == event.replacement_position_id:
            issues.append(
                _issue(
                    code.RETIRING_POSITION_NOT_DEBT,
                    f"Event {event.event_id!r} retires {ref.position_id!r}, which is not retiring debt. A V1 "
                    "refinance retires senior or mezzanine debt other than its own replacement; preferred and common "
                    "equity events are deferred.",
                    event_id=event.event_id,
                    field="retiring",
                )
            )
        if position.scope != event.scope:
            issues.append(
                _issue(
                    code.RETIRING_POSITION_SCOPE_MISMATCH,
                    f"Event {event.event_id!r} retires {ref.position_id!r} from another scope. A refinance retires "
                    "only debt of its own exact scope.",
                    event_id=event.event_id,
                    field="retiring",
                )
            )
    return issues


def _retiring_priority(event: RefinanceEvent, positions: dict[str, CapitalPosition]) -> int | None:
    """The most senior retiring priority, or ``None`` when a reference is not
    resolvable (already reported)."""

    ranks: list[int] = []
    for ref in event.retiring if isinstance(event.retiring, tuple) else ():
        if isinstance(ref, LegacyAcquisitionLoanRef):
            ranks.append(LEGACY_ACQUISITION_LOAN_PRIORITY)
        elif isinstance(ref, AuthoredPositionRef) and ref.position_id in positions:
            priority = positions[ref.position_id].priority
            if _is_whole(priority):
                ranks.append(priority)
    return min(ranks) if ranks else None


def _replacement_issues(event: RefinanceEvent, positions: dict[str, CapitalPosition]) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode
    identity = event.replacement_position_id
    replacement = positions.get(identity) if isinstance(identity, str) else None
    if replacement is None:
        return [
            _issue(
                code.REPLACEMENT_POSITION_NOT_FOUND,
                f"Event {event.event_id!r} names replacement {identity!r}, which this Capital Structure does not hold.",
                event_id=event.event_id,
                field="replacement_position_id",
            )
        ]
    terms = replacement.terms
    if replacement.position_class not in _DEBT_CLASSES or not isinstance(terms, DebtTerms):
        return [
            _issue(
                code.REPLACEMENT_POSITION_NOT_DEBT,
                f"Replacement {identity!r} of event {event.event_id!r} is not senior or mezzanine debt; the "
                "replacement is an ordinary debt position.",
                event_id=event.event_id,
                field="replacement_position_id",
            )
        ]
    issues: list[CapitalStructureIssue] = []
    if replacement.scope != event.scope:
        issues.append(
            _issue(
                code.REPLACEMENT_SCOPE_MISMATCH,
                f"Replacement {identity!r} of event {event.event_id!r} is in another scope; it must be funded in the "
                "event's exact scope.",
                event_id=event.event_id,
                field="replacement_position_id",
            )
        )
    month = _event_month(event)
    fundings = replacement.funding if isinstance(replacement.funding, tuple) else ()
    matched = (
        len(fundings) == 1
        and isinstance(fundings[0], FundingEvent)
        and isinstance(fundings[0].amount_rule, RefinanceProceeds)
        and fundings[0].amount_rule.capital_event_id == event.event_id
        and fundings[0].model_month == month
    )
    if not matched:
        issues.append(
            _issue(
                code.REPLACEMENT_FUNDING_MISMATCH,
                f"Replacement {identity!r} of event {event.event_id!r} must be funded by exactly one funding event, at "
                f"the event month {month!r}, whose amount is RefinanceProceeds({event.event_id!r}).",
                event_id=event.event_id,
                field="replacement_position_id",
            )
        )
    senior_rank = _retiring_priority(event, positions)
    if senior_rank is not None and replacement.priority != senior_rank:
        issues.append(
            _issue(
                code.REPLACEMENT_PRIORITY_NOT_SUCCESSOR,
                f"Replacement {identity!r} of event {event.event_id!r} has priority {replacement.priority!r}; it "
                f"succeeds to the most senior retiring rank, priority {senior_rank}.",
                event_id=event.event_id,
                field="replacement_position_id",
            )
        )
    if month is not None and _is_whole(terms.maturity_month) and terms.maturity_month < month + MINIMUM_REPLACEMENT_TERM_MONTHS:
        issues.append(
            _issue(
                code.REPLACEMENT_MATURITY_TOO_EARLY,
                f"Replacement {identity!r} of event {event.event_id!r} matures at model month {terms.maturity_month}, "
                f"inside its first year after month {month}. Bridge financing is deferred.",
                event_id=event.event_id,
                field="replacement_position_id",
            )
        )
    for fee in sorted(
        (fee for fee in terms.fees if isinstance(fee, PositionFee)) if isinstance(terms.fees, tuple) else (),
        key=lambda fee: (str(fee.fee_id), repr(fee.model_month)),
    ):
        if fee.model_month != month:
            issues.append(
                _issue(
                    code.REPLACEMENT_FEE_TIMING,
                    f"Fee {fee.fee_id!r} of replacement {identity!r} is at model month {fee.model_month!r}; a "
                    f"replacement lender fee is paid at the event month {month!r}.",
                    event_id=event.event_id,
                    field="replacement_position_id",
                )
            )
    sizing = event.sizing
    if (
        isinstance(sizing, RefinanceSizing)
        and isinstance(sizing.min_dscr, MinDscrConstraint)
        and terms.interest_rate == 0.0
        and _is_whole(terms.io_period)
        and terms.io_period >= 1
    ):
        issues.append(
            _issue(
                code.DSCR_ZERO_FIRST_YEAR_SERVICE,
                f"Replacement {identity!r} of event {event.event_id!r} is interest-only at 0%: its first-year service "
                "is zero, so DSCR capacity is undefined. It is never read as unlimited.",
                event_id=event.event_id,
                field="sizing.min_dscr",
            )
        )
    return issues


def _sizing_issues(event: RefinanceEvent) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode
    sizing = event.sizing
    if not isinstance(sizing, RefinanceSizing):
        return [
            _issue(code.INVALID_CAPITAL_EVENT, f"Event {event.event_id!r} states no RefinanceSizing.", event_id=event.event_id, field="sizing")
        ]
    issues: list[CapitalStructureIssue] = []
    if sizing.fixed_cap is None and sizing.max_ltv is None and sizing.min_dscr is None:
        issues.append(
            _issue(
                code.NO_SIZING_CONSTRAINT,
                f"Event {event.event_id!r} enables no sizing constraint; a refinance is never implicitly unlimited.",
                event_id=event.event_id,
                field="sizing",
            )
        )
    if sizing.fixed_cap is not None and not (
        isinstance(sizing.fixed_cap, FixedProceedsCap)
        and _is_number(sizing.fixed_cap.amount)
        and float(sizing.fixed_cap.amount) > 0.0
    ):
        issues.append(
            _issue(code.INVALID_FIXED_CAP, f"Event {event.event_id!r}: a fixed cap is finite and > 0.", event_id=event.event_id, field="sizing.fixed_cap")
        )
    if sizing.max_ltv is not None and not (
        isinstance(sizing.max_ltv, MaxLtvConstraint)
        and _is_number(sizing.max_ltv.max_ltv)
        and 0.0 < float(sizing.max_ltv.max_ltv) <= 1.0
    ):
        issues.append(
            _issue(code.INVALID_MAX_LTV, f"Event {event.event_id!r}: a maximum LTV lies in (0, 1].", event_id=event.event_id, field="sizing.max_ltv")
        )
    if sizing.min_dscr is not None and not (
        isinstance(sizing.min_dscr, MinDscrConstraint)
        and _is_number(sizing.min_dscr.min_dscr)
        and float(sizing.min_dscr.min_dscr) > 0.0
    ):
        issues.append(
            _issue(code.INVALID_MIN_DSCR, f"Event {event.event_id!r}: a minimum DSCR is finite and > 0.", event_id=event.event_id, field="sizing.min_dscr")
        )
    if sizing.max_ltv is not None and event.valuation is None:
        issues.append(
            _issue(
                code.VALUATION_REFERENCE_REQUIRED,
                f"Event {event.event_id!r} enables a maximum LTV but references no valuation timepoint.",
                event_id=event.event_id,
                field="valuation",
            )
        )
    if sizing.max_ltv is None and event.valuation is not None:
        issues.append(
            _issue(
                code.VALUATION_REFERENCE_UNUSED,
                f"Event {event.event_id!r} references a valuation but enables no maximum LTV. Only LTV consumes a "
                "valuation; DSCR reads the variant's forward NOI.",
                event_id=event.event_id,
                field="valuation",
            )
        )
    if event.valuation is not None and not (
        isinstance(event.valuation, RefinanceValuationRef) and _is_text(event.valuation.timepoint_id)
    ):
        issues.append(
            _issue(code.INVALID_CAPITAL_EVENT, f"Event {event.event_id!r} names no valuation timepoint id.", event_id=event.event_id, field="valuation")
        )
    return issues


def _cost_issues(event: RefinanceEvent) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode
    if not isinstance(event.costs, tuple):
        return [_issue(code.INVALID_COST_LINE, f"Event {event.event_id!r}: costs must be a tuple.", event_id=event.event_id, field="costs")]
    retiring = {_ref_key(ref) for ref in event.retiring} if isinstance(event.retiring, tuple) else set()
    issues: list[CapitalStructureIssue] = []
    for line in sorted(event.costs, key=lambda line: str(getattr(line, "cost_id", repr(line)))):
        if not (
            isinstance(line, RefinanceCostLine)
            and _is_text(line.cost_id)
            and isinstance(line.kind, RefinanceCostKind)
            and _is_number(line.amount)
            and float(line.amount) >= 0.0
            and isinstance(line.description, str)
        ):
            issues.append(
                _issue(
                    code.INVALID_COST_LINE,
                    f"Event {event.event_id!r}: cost {line!r} must be a fixed-dollar amount >= 0 with an id, a kind "
                    "and a description.",
                    event_id=event.event_id,
                    field="costs",
                )
            )
            continue
        if line.kind is RefinanceCostKind.THIRD_PARTY_COST and line.recipient is not None:
            issues.append(
                _issue(
                    code.INVALID_COST_LINE,
                    f"Third-party cost {line.cost_id!r} of event {event.event_id!r} names a recipient; a third-party "
                    "cost reaches no capital position.",
                    event_id=event.event_id,
                    field="costs",
                )
            )
        if line.kind is RefinanceCostKind.RETIRING_LENDER_FEE and (
            line.recipient is None or _ref_key(line.recipient) not in retiring
        ):
            issues.append(
                _issue(
                    code.INVALID_RETIRING_LENDER_FEE_RECIPIENT,
                    f"Retiring lender fee {line.cost_id!r} of event {event.event_id!r} must name one of the event's "
                    "retiring positions.",
                    event_id=event.event_id,
                    field="costs",
                )
            )
    return issues


def _event_issues(
    event: object, positions: dict[str, CapitalPosition], members: frozenset[str] | None
) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode
    if not isinstance(event, RefinanceEvent):
        return [_issue(code.UNSUPPORTED_CAPITAL_EVENT_KIND, f"Capital event {event!r} is not a V1 refinance.")]
    if event.kind is not CapitalEventKind.REFINANCE:
        return [
            _issue(
                code.UNSUPPORTED_CAPITAL_EVENT_KIND,
                f"Event {event.event_id!r} is a {event.kind!r} event; V1 executes refinances only.",
                event_id=event.event_id,
                field="kind",
            )
        ]
    issues: list[CapitalStructureIssue] = []
    if not _is_text(event.event_id) or not isinstance(event.label, str) or not event.label.strip():
        issues.append(
            _issue(
                code.INVALID_CAPITAL_EVENT,
                f"Capital event {event.event_id!r} needs a nonblank event_id and a nonblank analyst-facing label.",
                event_id=event.event_id,
                field="event_id",
            )
        )
    if not _scope_is_valid(event.scope):
        return [
            *issues,
            _issue(code.INVALID_SCOPE, f"Event {event.event_id!r} states no valid scope.", event_id=event.event_id, field="scope"),
        ]
    if event.scope.kind is ScopeKind.UNIT and members is not None and event.scope.unit_id not in members:
        issues.append(
            _issue(
                code.FOREIGN_UNIT_SCOPE,
                f"Event {event.event_id!r} is scoped to Unit {event.scope.unit_id!r}, which is not in this analysis.",
                event_id=event.event_id,
                field="scope",
            )
        )
    issues.extend(_timing_issues(event))
    issues.extend(_retiring_issues(event, positions))
    issues.extend(_replacement_issues(event, positions))
    issues.extend(_sizing_issues(event))
    issues.extend(_cost_issues(event))
    return issues


# =============================================================================
# The structure
# =============================================================================


def _namespace_issues(structure: CapitalStructure, events: tuple[RefinanceEvent, ...]) -> list[CapitalStructureIssue]:
    """Event ids and cost-line ids join the funding-event and fee namespace
    (P7.7 Section 8). Duplicates among funding events and fees alone are P7.7's
    own finding and are not repeated here."""

    capital: list[str] = []
    for position in _positions(structure).values():
        if isinstance(position.funding, tuple):
            capital.extend(event.event_id for event in position.funding if isinstance(event, FundingEvent))
        if isinstance(position.terms, DebtTerms) and isinstance(position.terms.fees, tuple):
            capital.extend(fee.fee_id for fee in position.terms.fees if isinstance(fee, PositionFee))
    added: list[str] = []
    for event in events:
        added.append(event.event_id)
        if isinstance(event.costs, tuple):
            added.extend(line.cost_id for line in event.costs if isinstance(line, RefinanceCostLine))
    counts = Counter([*capital, *added])
    return [
        _issue(
            CapitalStructureIssueCode.DUPLICATE_CAPITAL_EVENT_ID,
            f"Capital event identity {identity!r} is used {counts[identity]} times; events, event costs, funding "
            "events and fees share one namespace across the Capital Structure.",
        )
        for identity in sorted(set(added))
        if isinstance(identity, str) and counts[identity] > 1
    ]


def _scope_count_issues(events: tuple[RefinanceEvent, ...]) -> list[CapitalStructureIssue]:
    by_scope: dict[tuple[int, str], list[str]] = {}
    for event in events:
        if _scope_is_valid(event.scope):
            by_scope.setdefault(_scope_key(event.scope), []).append(event.event_id)
    return [
        _issue(
            CapitalStructureIssueCode.MULTIPLE_REFINANCES_IN_SCOPE,
            f"Events {', '.join(repr(e) for e in sorted(ids))} refinance the same scope; V1 permits one refinance per "
            "exact scope.",
            field="events",
        )
        for _, ids in sorted(by_scope.items())
        if len(ids) > 1
    ]


def _orphan_issues(structure: CapitalStructure, events: tuple[RefinanceEvent, ...]) -> list[CapitalStructureIssue]:
    replacements = {event.event_id: event.replacement_position_id for event in events}
    return [
        _issue(
            CapitalStructureIssueCode.ORPHANED_REFINANCE_PROCEEDS,
            f"Funding {funding.event_id!r} of {position.position_id!r} is RefinanceProceeds("
            f"{funding.amount_rule.capital_event_id!r}), but no refinance event names {position.position_id!r} as "
            "its replacement.",
            event_id=position.position_id,
            field="funding",
        )
        for position, funding in _refinance_proceeds_fundings(structure)
        if isinstance(funding.amount_rule, RefinanceProceeds)
        and replacements.get(funding.amount_rule.capital_event_id) != position.position_id
    ]


def validate_capital_events(
    structure: object, *, member_unit_ids: Collection[str] | None = None
) -> tuple[CapitalStructureIssue, ...]:
    """Every capital-event authoring fault of ``structure``, in deterministic
    order, or ``()``. A structure that states no event and no
    ``RefinanceProceeds`` funding returns ``()`` without inspection."""

    if not isinstance(structure, CapitalStructure):
        return ()
    events = _events(structure)
    if events is None:
        return (
            _issue(
                CapitalStructureIssueCode.INVALID_CAPITAL_EVENT,
                "events must be a tuple of capital events; a Capital Structure is immutable.",
                field="events",
            ),
        )
    if isinstance(structure, CapitalStructureWithEvents) and not events:
        return (
            _issue(
                CapitalStructureIssueCode.INVALID_CAPITAL_EVENT,
                "A Capital Structure with events states at least one; a structure without a refinance is a plain "
                "CapitalStructure.",
                field="events",
            ),
        )
    if not events and not _refinance_proceeds_fundings(structure):
        return ()
    positions = _positions(structure)
    members = None if member_unit_ids is None else frozenset(member_unit_ids)
    issues: list[CapitalStructureIssue] = []
    for event in sorted(events, key=_event_key):
        issues.extend(_event_issues(event, positions, members))
    refinances = _well_formed_refinances(structure)
    issues.extend(_namespace_issues(structure, refinances))
    issues.extend(_scope_count_issues(refinances))
    issues.extend(_orphan_issues(structure, refinances))
    return tuple(issues)


__all__ = [
    "MINIMUM_REPLACEMENT_TERM_MONTHS",
    "succession_pairs",
    "validate_capital_events",
]
