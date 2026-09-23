"""Phase 7 Gate P7.7 -- structural validation of an authored Capital Structure.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
3 (P-7, P-8, P-14), 12.2, 12.3 (CS-3 to CS-5, CS-7) and 15.5; that document
governs on any discrepancy. Pure: no I/O, no clock, no randomness, no
arithmetic, and no knowledge of storage, routes, results or the engine.

``validate_capital_structure`` returns ``()`` for a valid structure and never
repairs, coerces, reorders or defaults anything. Issues come in a deterministic
order that never depends on how the positions were listed: each position's own
issues, in economic order, and then the cross-position issues, each sorted.

**Economic order is explicit (P-7).** Scope first -- every Unit scope, then the
Investment scope, which is downstream of all of them (CS-4) -- and then
``priority``, lower being more senior. List position never participates.
``priority`` is unique within one scope; the same priority in two scopes is
legitimate. Where a Unit carries an acquisition loan, priority 1 of that Unit's
scope is the loan's.

**CS-5.** Investment-scoped senior debt is refused while any Unit carries an
acquisition loan, so one dollar is never financed twice. Cross-collateralization
is never inferred. The caller states which Units carry a loan; it is never
assumed that none does.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable
from math import isfinite

from .contracts import (
    LEGACY_ACQUISITION_LOAN_ID_PREFIX,
    LEGACY_ACQUISITION_LOAN_PRIORITY,
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureIssue,
    CapitalStructureIssueCode,
    DebtTerms,
    FixedAmount,
    FundingEvent,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    PositionFee,
    PositionScope,
    PreferredEquityTerms,
    RefinanceProceeds,
    ScopeKind,
    ShortfallResolution,
)
from .event_validation import succession_pairs, validate_capital_events

_MAX_SAFE_REPR_LENGTH = 200

#: Class / terms pairing, exactly (Section 12.2).
_TERMS_OF_CLASS: dict[PositionClass, type[DebtTerms] | type[PreferredEquityTerms] | None] = {
    PositionClass.SENIOR_DEBT: DebtTerms,
    PositionClass.MEZZANINE_DEBT: DebtTerms,
    PositionClass.PREFERRED_EQUITY: PreferredEquityTerms,
    PositionClass.COMMON_EQUITY: None,
}


def _safe_repr(value: object) -> str:
    try:
        representation = repr(value)
    except Exception:
        return f"<{type(value).__qualname__}>"
    if len(representation) > _MAX_SAFE_REPR_LENGTH:
        return f"<{type(value).__qualname__}>"
    return representation


def _full_repr(value: object) -> str:
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__qualname__}>"


def _is_nonblank_text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_finite_number(value: object) -> bool:
    """A finite ``int`` or ``float``; ``bool`` is not a number here."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(float(value))
    except OverflowError:
        return False


def _is_whole_number(value: object) -> bool:
    """An ``int`` that is not a ``bool``."""

    return isinstance(value, int) and not isinstance(value, bool)


def _is_rate(value: object) -> bool:
    """A finite number ``>= 0``: the domain of ``AcquisitionTerms.interest_rate``."""

    return _is_finite_number(value) and float(value) >= 0.0  # type: ignore[arg-type]


def _is_fraction(value: object) -> bool:
    """A finite number in ``(0, 1]``: the ``ltv`` domain, less zero, because a
    zero funding is no position at all."""

    return _is_finite_number(value) and 0.0 < float(value) <= 1.0  # type: ignore[arg-type]


def _issue(
    code: CapitalStructureIssueCode,
    message: str,
    *,
    position_id: str | None = None,
    field: str | None = None,
) -> CapitalStructureIssue:
    return CapitalStructureIssue(code=code, message=message, position_id=position_id, field=field)


# =============================================================================
# Scope and economic order
# =============================================================================


def _scope_is_valid(scope: object) -> bool:
    if not isinstance(scope, PositionScope) or not isinstance(scope.kind, ScopeKind):
        return False
    if scope.kind is ScopeKind.UNIT:
        return _is_nonblank_text(scope.unit_id)
    return scope.unit_id is None


def scope_order_key(scope: PositionScope) -> tuple[int, str]:
    """The economic order of scopes (CS-4). Every Unit scope comes first, by
    ``unit_id``: the Units are paid in parallel, each from its own cash, so the
    order among them is canonical only. The Investment scope follows, because
    it reads only what has cleared all of them."""

    if scope.kind is ScopeKind.UNIT:
        return (0, scope.unit_id or "")
    return (1, "")


def economic_order(positions: Iterable[CapitalPosition]) -> tuple[CapitalPosition, ...]:
    """Valid positions in economic order: scope (``scope_order_key``), then
    ``priority``, lower being more senior. ``position_id`` breaks no economic
    tie, because priority is unique within a scope; it only makes the order
    total. List position never participates (P-7)."""

    return tuple(
        sorted(
            positions,
            key=lambda position: (*scope_order_key(position.scope), position.priority, position.position_id),
        )
    )


def _order_key(position: object) -> tuple[int, str, int, str, str]:
    """A total, list-order-free key over possibly malformed positions: the
    economic order where the fields allow it, then the full representation."""

    if not isinstance(position, CapitalPosition):
        return (3, "", 0, "", _full_repr(position))
    rank, unit_id = scope_order_key(position.scope) if _scope_is_valid(position.scope) else (2, "")
    priority = position.priority if _is_whole_number(position.priority) else 0
    position_id = position.position_id if isinstance(position.position_id, str) else ""
    return (rank, unit_id, priority, position_id, _full_repr(position))


def _event_key(item: object) -> tuple[int, int, str, str]:
    model_month = getattr(item, "model_month", None)
    sequence = getattr(item, "sequence", None)
    identity = getattr(item, "event_id", getattr(item, "fee_id", None))
    return (
        model_month if _is_whole_number(model_month) else 0,  # type: ignore[return-value]
        sequence if _is_whole_number(sequence) else 0,  # type: ignore[return-value]
        identity if isinstance(identity, str) else "",
        _full_repr(item),
    )


# =============================================================================
# One position
# =============================================================================


def _identity_issues(
    value: object, *, code: CapitalStructureIssueCode, what: str, position_id: str | None, field: str
) -> list[CapitalStructureIssue]:
    if not _is_nonblank_text(value):
        return [_issue(code, f"{what} {_safe_repr(value)} must be a nonblank string.", position_id=position_id, field=field)]
    assert isinstance(value, str)
    if value.startswith(LEGACY_ACQUISITION_LOAN_ID_PREFIX):
        return [
            _issue(
                CapitalStructureIssueCode.RESERVED_IDENTITY,
                f"{what} {value!r} uses the reserved prefix {LEGACY_ACQUISITION_LOAN_ID_PREFIX!r}, which "
                "identifies only an adapted acquisition loan.",
                position_id=position_id,
                field=field,
            )
        ]
    return []


def _scope_issues(scope: object, position_id: str | None, members: frozenset[str] | None) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode.INVALID_SCOPE
    if not isinstance(scope, PositionScope) or not isinstance(scope.kind, ScopeKind):
        return [
            _issue(
                code,
                f"scope {_safe_repr(scope)} must be a PositionScope of kind "
                f"{' or '.join(kind.value for kind in ScopeKind)}.",
                position_id=position_id,
                field="scope",
            )
        ]
    if scope.kind is ScopeKind.UNIT:
        if not _is_nonblank_text(scope.unit_id):
            return [
                _issue(
                    code,
                    f"a unit scope names exactly one nonblank unit_id; got {_safe_repr(scope.unit_id)}.",
                    position_id=position_id,
                    field="scope.unit_id",
                )
            ]
        if members is not None and scope.unit_id not in members:
            return [
                _issue(
                    CapitalStructureIssueCode.FOREIGN_UNIT_SCOPE,
                    f"scope names Unit {scope.unit_id!r}, which is not a Unit of this analysis "
                    f"({', '.join(sorted(members))}).",
                    position_id=position_id,
                    field="scope.unit_id",
                )
            ]
        return []
    if scope.unit_id is not None:
        return [
            _issue(
                code,
                f"an investment scope carries no unit_id; got {_safe_repr(scope.unit_id)}.",
                position_id=position_id,
                field="scope.unit_id",
            )
        ]
    return []


def _amount_rule_issues(rule: object, position_id: str | None, where: str) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode.INVALID_AMOUNT_RULE
    field = f"{where}.amount_rule"
    fraction = "must be a finite number greater than 0 and at most 1"
    match rule:
        case FixedAmount():
            if _is_finite_number(rule.amount) and float(rule.amount) > 0.0:
                return []
            return [
                _issue(
                    code,
                    f"a fixed funding amount {_safe_repr(rule.amount)} must be a finite number of dollars "
                    "greater than 0; a zero-dollar position does not exist.",
                    position_id=position_id,
                    field=f"{field}.amount",
                )
            ]
        case PctOfPrice():
            if _is_fraction(rule.pct):
                return []
            return [_issue(code, f"pct_of_price {_safe_repr(rule.pct)} {fraction}.", position_id=position_id, field=f"{field}.pct")]
        case PctOfValue():
            issues: list[CapitalStructureIssue] = []
            if not _is_nonblank_text(rule.timepoint_id):
                issues.append(
                    _issue(
                        code,
                        f"pct_of_value names a valuation timepoint by a nonblank timepoint_id; got "
                        f"{_safe_repr(rule.timepoint_id)}.",
                        position_id=position_id,
                        field=f"{field}.timepoint_id",
                    )
                )
            if not _is_fraction(rule.pct):
                issues.append(
                    _issue(code, f"pct_of_value {_safe_repr(rule.pct)} {fraction}.", position_id=position_id, field=f"{field}.pct")
                )
            return issues
        case RefinanceProceeds():
            # Refinance & Capital Events V1: whether the named event exists and
            # names this position as its replacement is judged with the events.
            if _is_nonblank_text(rule.capital_event_id):
                return []
            return [
                _issue(
                    code,
                    f"refinance_proceeds names its refinance event by a nonblank capital_event_id; got "
                    f"{_safe_repr(rule.capital_event_id)}.",
                    position_id=position_id,
                    field=f"{field}.capital_event_id",
                )
            ]
        case _:
            return [
                _issue(
                    code,
                    f"amount_rule {_safe_repr(rule)} must be a FixedAmount, PctOfPrice or PctOfValue.",
                    position_id=position_id,
                    field=field,
                )
            ]


def _timing_issues(item: FundingEvent | PositionFee, code: CapitalStructureIssueCode, position_id: str | None, where: str) -> list[CapitalStructureIssue]:
    issues: list[CapitalStructureIssue] = []
    if not _is_whole_number(item.model_month) or item.model_month < 0:
        issues.append(
            _issue(
                code,
                f"model_month {_safe_repr(item.model_month)} must be a whole model month >= 0 (0 = closing).",
                position_id=position_id,
                field=f"{where}.model_month",
            )
        )
    if not _is_whole_number(item.sequence) or item.sequence < 1:
        issues.append(
            _issue(
                code,
                f"sequence {_safe_repr(item.sequence)} must be a whole number >= 1; it orders events that "
                "share a model month.",
                position_id=position_id,
                field=f"{where}.sequence",
            )
        )
    return issues


def _funding_event_issues(event: object, position_id: str | None) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode.INVALID_FUNDING_EVENT
    if not isinstance(event, FundingEvent):
        return [_issue(code, f"funding event {_safe_repr(event)} must be a FundingEvent.", position_id=position_id, field="funding")]
    where = f"funding[{event.event_id}]" if isinstance(event.event_id, str) else "funding"
    return [
        *_identity_issues(event.event_id, code=code, what="event_id", position_id=position_id, field=f"{where}.event_id"),
        *_timing_issues(event, code, position_id, where),
        *_amount_rule_issues(event.amount_rule, position_id, where),
    ]


def _fee_issues(fee: object, position_id: str | None) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode.INVALID_FEE
    if not isinstance(fee, PositionFee):
        return [_issue(code, f"fee {_safe_repr(fee)} must be a PositionFee.", position_id=position_id, field="terms.fees")]
    where = f"terms.fees[{fee.fee_id}]" if isinstance(fee.fee_id, str) else "terms.fees"
    issues = _identity_issues(fee.fee_id, code=code, what="fee_id", position_id=position_id, field=f"{where}.fee_id")
    if not _is_nonblank_text(fee.description):
        issues.append(
            _issue(code, f"description {_safe_repr(fee.description)} must be a nonblank string.", position_id=position_id, field=f"{where}.description")
        )
    if not _is_finite_number(fee.amount) or float(fee.amount) < 0.0:
        issues.append(
            _issue(
                code,
                f"fee amount {_safe_repr(fee.amount)} must be a finite number of dollars >= 0.",
                position_id=position_id,
                field=f"{where}.amount",
            )
        )
    issues.extend(_timing_issues(fee, code, position_id, where))
    return issues


def _funding_issues(position: CapitalPosition, position_class: PositionClass | None, position_id: str | None) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode.INVALID_FUNDING
    funding = position.funding
    if not isinstance(funding, tuple):
        return [_issue(code, "funding must be a tuple of FundingEvent.", position_id=position_id, field="funding")]
    issues: list[CapitalStructureIssue] = []
    if position_class is PositionClass.COMMON_EQUITY:
        if funding:
            issues.append(
                _issue(
                    code,
                    "common equity is the residual: its funding is never an authored amount, so it carries no "
                    "funding events.",
                    position_id=position_id,
                    field="funding",
                )
            )
    elif position_class is not None and not funding:
        issues.append(
            _issue(
                code,
                f"a {position_class.value} position is funded by at least one timed funding event.",
                position_id=position_id,
                field="funding",
            )
        )
    for event in sorted(funding, key=_event_key):
        issues.extend(_funding_event_issues(event, position_id))
    return issues


def _debt_terms_issues(terms: DebtTerms, position_id: str | None) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode.INVALID_DEBT_TERMS
    issues: list[CapitalStructureIssue] = []
    for name in ("interest_rate", "current_pay_rate", "pik_rate"):
        value = getattr(terms, name)
        if not _is_rate(value):
            issues.append(
                _issue(code, f"{name} {_safe_repr(value)} must be a finite rate >= 0.", position_id=position_id, field=f"terms.{name}")
            )
    for name, minimum, unit in (
        ("amortization", 1, "years"),
        ("io_period", 0, "years"),
        ("maturity_month", 1, "model month"),
    ):
        value = getattr(terms, name)
        if not _is_whole_number(value) or value < minimum:
            issues.append(
                _issue(
                    code,
                    f"{name} {_safe_repr(value)} must be a whole number of {unit} >= {minimum}.",
                    position_id=position_id,
                    field=f"terms.{name}",
                )
            )
    if not isinstance(terms.fees, tuple):
        issues.append(_issue(code, "fees must be a tuple of PositionFee.", position_id=position_id, field="terms.fees"))
    else:
        for fee in sorted(terms.fees, key=_event_key):
            issues.extend(_fee_issues(fee, position_id))
    return issues


def _preferred_terms_issues(terms: PreferredEquityTerms, position_id: str | None) -> list[CapitalStructureIssue]:
    code = CapitalStructureIssueCode.INVALID_PREFERRED_EQUITY_TERMS
    issues: list[CapitalStructureIssue] = []
    for name in ("preferred_rate", "current_pay_rate"):
        value = getattr(terms, name)
        if not _is_rate(value):
            issues.append(
                _issue(code, f"{name} {_safe_repr(value)} must be a finite rate >= 0.", position_id=position_id, field=f"terms.{name}")
            )
    permitted, convention = terms.accrual_permitted, terms.accrual_convention
    conventions = " or ".join(member.value for member in AccrualConvention)
    if not isinstance(permitted, bool):
        issues.append(
            _issue(
                code,
                f"accrual_permitted {_safe_repr(permitted)} must be stated explicitly as True or False.",
                position_id=position_id,
                field="terms.accrual_permitted",
            )
        )
    elif permitted and not isinstance(convention, AccrualConvention):
        issues.append(
            _issue(
                code,
                f"accrual is permitted, so its convention must be named ({conventions}); got "
                f"{_safe_repr(convention)}. No convention is ever assumed.",
                position_id=position_id,
                field="terms.accrual_convention",
            )
        )
    elif not permitted and convention is not None:
        issues.append(
            _issue(
                code,
                f"accrual is not permitted, so no accrual convention applies; got {_safe_repr(convention)}. "
                "Accrual is never inferred.",
                position_id=position_id,
                field="terms.accrual_convention",
            )
        )
    if not _is_whole_number(terms.redemption_month) or terms.redemption_month < 1:
        issues.append(
            _issue(
                code,
                f"redemption_month {_safe_repr(terms.redemption_month)} must be a whole model month >= 1.",
                position_id=position_id,
                field="terms.redemption_month",
            )
        )
    return issues


def _terms_issues(position: CapitalPosition, position_class: PositionClass | None, position_id: str | None) -> list[CapitalStructureIssue]:
    if position_class is None:
        return []
    terms, expected = position.terms, _TERMS_OF_CLASS[position_class]
    code = CapitalStructureIssueCode.CLASS_TERMS_MISMATCH
    if expected is None:
        if terms is None:
            return []
        return [
            _issue(
                code,
                f"a {position_class.value} position carries no terms at this layer (its economics are the "
                f"Partnership's); got {type(terms).__qualname__}.",
                position_id=position_id,
                field="terms",
            )
        ]
    if not isinstance(terms, expected):
        return [
            _issue(
                code,
                f"a {position_class.value} position carries {expected.__qualname__}; got {type(terms).__qualname__}.",
                position_id=position_id,
                field="terms",
            )
        ]
    if isinstance(terms, DebtTerms):
        return _debt_terms_issues(terms, position_id)
    return _preferred_terms_issues(terms, position_id)


def _resolution_issues(position: CapitalPosition, position_class: PositionClass | None, position_id: str | None) -> list[CapitalStructureIssue]:
    resolution = position.shortfall_resolution
    resolutions = " or ".join(member.value for member in ShortfallResolution)
    if position_class is None:
        return []
    if position_class is PositionClass.COMMON_EQUITY:
        if resolution is None:
            return []
        return [
            _issue(
                CapitalStructureIssueCode.INVALID_SHORTFALL_RESOLUTION,
                "common equity is the residual and carries no contractual claim, so it has no shortfall to "
                f"resolve; got {_safe_repr(resolution)}.",
                position_id=position_id,
                field="shortfall_resolution",
            )
        ]
    if resolution is None:
        return [
            _issue(
                CapitalStructureIssueCode.MISSING_SHORTFALL_RESOLUTION,
                f"a {position_class.value} position must state its shortfall resolution explicitly "
                f"({resolutions}); there is no default.",
                position_id=position_id,
                field="shortfall_resolution",
            )
        ]
    if not isinstance(resolution, ShortfallResolution):
        return [
            _issue(
                CapitalStructureIssueCode.INVALID_SHORTFALL_RESOLUTION,
                f"shortfall_resolution {_safe_repr(resolution)} is not one of: {resolutions}.",
                position_id=position_id,
                field="shortfall_resolution",
            )
        ]
    return []


def _event_order_issues(position: CapitalPosition, position_id: str | None) -> list[CapitalStructureIssue]:
    """A position's funding events and fees share one explicit order: a model
    month and a sequence may be used once (Section 15.5)."""

    items: list[FundingEvent | PositionFee] = []
    if isinstance(position.funding, tuple):
        items.extend(event for event in position.funding if isinstance(event, FundingEvent))
    if isinstance(position.terms, DebtTerms) and isinstance(position.terms.fees, tuple):
        items.extend(fee for fee in position.terms.fees if isinstance(fee, PositionFee))
    counts = Counter(
        (item.model_month, item.sequence)
        for item in items
        if _is_whole_number(item.model_month) and _is_whole_number(item.sequence)
    )
    return [
        _issue(
            CapitalStructureIssueCode.DUPLICATE_EVENT_ORDER,
            f"model month {month} sequence {sequence} is used by {count} of this position's funding events "
            "and fees; events that share a model month need distinct sequences.",
            position_id=position_id,
            field="funding",
        )
        for (month, sequence), count in sorted(counts.items())
        if count > 1
    ]


def _position_issues(position: object, members: frozenset[str] | None) -> list[CapitalStructureIssue]:
    if not isinstance(position, CapitalPosition):
        return [
            _issue(CapitalStructureIssueCode.INVALID_POSITION, f"position {_safe_repr(position)} must be a CapitalPosition.")
        ]
    position_id = position.position_id if _is_nonblank_text(position.position_id) else None
    issues = _identity_issues(
        position.position_id,
        code=CapitalStructureIssueCode.INVALID_POSITION_ID,
        what="position_id",
        position_id=position_id,
        field="position_id",
    )
    if not _is_nonblank_text(position.name):
        issues.append(
            _issue(
                CapitalStructureIssueCode.INVALID_NAME,
                f"name {_safe_repr(position.name)} must be a nonblank string.",
                position_id=position_id,
                field="name",
            )
        )
    position_class = position.position_class if isinstance(position.position_class, PositionClass) else None
    if position_class is None:
        issues.append(
            _issue(
                CapitalStructureIssueCode.UNKNOWN_POSITION_CLASS,
                f"position_class {_safe_repr(position.position_class)} is not one of: "
                f"{', '.join(member.value for member in PositionClass)}.",
                position_id=position_id,
                field="position_class",
            )
        )
    if not _is_whole_number(position.priority) or position.priority < 1:
        issues.append(
            _issue(
                CapitalStructureIssueCode.INVALID_PRIORITY,
                f"priority {_safe_repr(position.priority)} must be a whole number >= 1; lower is more senior.",
                position_id=position_id,
                field="priority",
            )
        )
    issues.extend(_scope_issues(position.scope, position_id, members))
    issues.extend(_funding_issues(position, position_class, position_id))
    issues.extend(_terms_issues(position, position_class, position_id))
    issues.extend(_resolution_issues(position, position_class, position_id))
    issues.extend(_event_order_issues(position, position_id))
    return issues


# =============================================================================
# Across positions
# =============================================================================


def _duplicate_position_ids(positions: list[CapitalPosition]) -> list[CapitalStructureIssue]:
    counts = Counter(position.position_id for position in positions if _is_nonblank_text(position.position_id))
    return [
        _issue(
            CapitalStructureIssueCode.DUPLICATE_POSITION_ID,
            f"position_id {position_id!r} is given {count} times; every position has one stable identity.",
            position_id=position_id,
            field="position_id",
        )
        for position_id, count in sorted(counts.items())
        if count > 1
    ]


def _duplicate_priorities(
    positions: list[CapitalPosition],
    loan_units: frozenset[str],
    succession: tuple[frozenset[frozenset[str]], frozenset[str]] = (frozenset(), frozenset()),
) -> list[CapitalStructureIssue]:
    """Priority is unique within a scope, and priority 1 of a Unit carrying an
    acquisition loan is the loan's. ``succession`` names the one exception
    (Refinance & Capital Events V1, decision R-N): a retiring position and its
    replacement, whose outstanding intervals never overlap, and a replacement
    that succeeds to the acquisition loan's rank. Without a refinance it is
    empty and nothing is excused."""

    pairs, legacy_successors = succession
    ranked: dict[tuple[tuple[int, str], int], list[str]] = {}
    for position in positions:
        if _scope_is_valid(position.scope) and _is_whole_number(position.priority) and position.priority >= 1:
            ranked.setdefault((scope_order_key(position.scope), position.priority), []).append(
                position.position_id if isinstance(position.position_id, str) else _safe_repr(position.position_id)
            )
    issues: list[CapitalStructureIssue] = []
    for ((rank, unit_id), priority), position_ids in sorted(ranked.items()):
        scope = f"Unit {unit_id!r}" if rank == 0 else "the Investment"
        if len(position_ids) == 2 and frozenset(position_ids) in pairs:
            continue
        if len(position_ids) == 1 and position_ids[0] in legacy_successors:
            continue
        if len(position_ids) > 1:
            issues.append(
                _issue(
                    CapitalStructureIssueCode.DUPLICATE_PRIORITY,
                    f"priority {priority} is used by {', '.join(repr(p) for p in sorted(position_ids))} in the scope "
                    f"of {scope}; priority is unique within a scope.",
                    field="priority",
                )
            )
        if rank == 0 and unit_id in loan_units and priority == LEGACY_ACQUISITION_LOAN_PRIORITY:
            issues.append(
                _issue(
                    CapitalStructureIssueCode.DUPLICATE_PRIORITY,
                    f"priority {priority} of {scope} is held by its acquisition loan "
                    f"({LEGACY_ACQUISITION_LOAN_ID_PREFIX}{unit_id}); "
                    f"{', '.join(repr(p) for p in sorted(position_ids))} must rank below it.",
                    field="priority",
                )
            )
    return issues


def _duplicate_event_ids(positions: list[CapitalPosition]) -> list[CapitalStructureIssue]:
    identities: list[str] = []
    for position in positions:
        if isinstance(position.funding, tuple):
            identities.extend(
                event.event_id for event in position.funding if isinstance(event, FundingEvent) and _is_nonblank_text(event.event_id)
            )
        if isinstance(position.terms, DebtTerms) and isinstance(position.terms.fees, tuple):
            identities.extend(
                fee.fee_id for fee in position.terms.fees if isinstance(fee, PositionFee) and _is_nonblank_text(fee.fee_id)
            )
    return [
        _issue(
            CapitalStructureIssueCode.DUPLICATE_EVENT_ID,
            f"capital event identity {identity!r} is used {count} times; funding events and fees share one "
            "namespace across the Capital Structure.",
        )
        for identity, count in sorted(Counter(identities).items())
        if count > 1
    ]


def _double_financing(positions: list[CapitalPosition], loan_units: frozenset[str]) -> list[CapitalStructureIssue]:
    if not loan_units:
        return []
    return [
        _issue(
            CapitalStructureIssueCode.INVESTMENT_SENIOR_DEBT_WITH_ACQUISITION_LOAN,
            f"Investment-scoped senior debt {position.position_id!r} would finance the same acquisition as the "
            f"acquisition loan(s) of Unit(s) {', '.join(sorted(loan_units))}. Investment-scoped senior debt is "
            "allowed only when no Unit carries an acquisition loan; cross-collateralization is never inferred.",
            position_id=position.position_id if isinstance(position.position_id, str) else None,
            field="scope",
        )
        for position in positions
        if _scope_is_valid(position.scope)
        and position.scope.kind is ScopeKind.INVESTMENT
        and position.position_class is PositionClass.SENIOR_DEBT
    ]


def validate_capital_structure(
    structure: object,
    *,
    member_unit_ids: Collection[str] | None = None,
    acquisition_loan_unit_ids: Collection[str],
) -> tuple[CapitalStructureIssue, ...]:
    """Every structural issue with ``structure``, in deterministic order, or
    ``()``.

    - ``member_unit_ids``: the Units of the analysis. When supplied, a Unit
      scope naming any other Unit is refused. ``None`` leaves membership
      unjudged.
    - ``acquisition_loan_unit_ids``: the Units that carry an acquisition loan.
      Required: priority 1 of each such Unit's scope is its loan, and CS-5
      refuses Investment-scoped senior debt while any exists.

    Validation never executes, sizes or values a position."""

    if not isinstance(structure, CapitalStructure):
        return (
            _issue(
                CapitalStructureIssueCode.INVALID_STRUCTURE,
                f"capital structure {_safe_repr(structure)} must be a CapitalStructure.",
            ),
        )
    if not isinstance(structure.positions, tuple):
        return (
            _issue(
                CapitalStructureIssueCode.INVALID_STRUCTURE,
                "positions must be a tuple of CapitalPosition; a Capital Structure is immutable.",
                field="positions",
            ),
        )
    members = None if member_unit_ids is None else frozenset(member_unit_ids)
    loan_units = frozenset(acquisition_loan_unit_ids)
    ordered = sorted(structure.positions, key=_order_key)
    positions = [position for position in ordered if isinstance(position, CapitalPosition)]
    issues: list[CapitalStructureIssue] = []
    for position in ordered:
        issues.extend(_position_issues(position, members))
    issues.extend(_duplicate_position_ids(positions))
    issues.extend(_duplicate_priorities(positions, loan_units, succession_pairs(structure)))
    issues.extend(_duplicate_event_ids(positions))
    issues.extend(_double_financing(positions, loan_units))
    # Refinance & Capital Events V1: a structure that states no event and no
    # RefinanceProceeds funding adds nothing here.
    issues.extend(validate_capital_events(structure, member_unit_ids=member_unit_ids))
    return tuple(issues)
