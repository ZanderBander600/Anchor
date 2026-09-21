"""Phase 7 Gate P7.8 -- execution compatibility of a valid Capital Structure.

Restates the P7.8 decisions of
``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md`` under
``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 12 and
21.3; those documents govern on any discrepancy.

**Separate from structural validation.** ``validation.validate_capital_structure``
(P7.7) says whether a contract is well formed, and is unchanged. This module
runs only on a structure that passed it, and says whether the first executor
executes it. A contract it refuses is valid: it is never called malformed,
never moved to a supported convention, and never partially executed.

The first executor runs:

- funding and fees at model month 0 (closing) only;
- ``FixedAmount`` and ``PctOfPrice`` funding; and, from P7.10 Stage 1,
  ``PctOfValue`` funding when the caller supplies a ``ValuationAuthority``
  that sizes it. Without an authority the rule is refused exactly as before,
  so an analysis with no P7.10 structure is unchanged. With one, a funding
  whose valuation did not resolve is refused by its own typed reason rather
  than sized at zero;
- cash-pay debt: ``pik_rate == 0`` and ``current_pay_rate == interest_rate``;
- preferred equity with ``0 <= current_pay_rate <= preferred_rate``, any
  accrual permitted by its terms, and a redemption at a hold-year end or at or
  after the exit;
- in a standalone Unit, Unit-scoped positions only;
- at most one common-equity marker, scoped to the analysis root (that Unit, or
  the Investment), with no claim below it.

Issues come in economic order, each position's in field order, then the
cross-position issues. List order never participates.
"""

from __future__ import annotations

from ..valuation.contracts import UnresolvedFundingRequirement
from ..valuation.funding import ValuationAuthority
from .contracts import (
    CapitalPosition,
    CapitalStructure,
    DebtTerms,
    FundingEvent,
    PctOfValue,
    PositionClass,
    PositionFee,
    PreferredEquityTerms,
    ScopeKind,
)
from .execution_contracts import ExecutionIssue, ExecutionIssueCode
from .funding import resolve_valuation_funding
from .preferred import modeled_redemption_month
from .validation import economic_order


def _issue(code: ExecutionIssueCode, message: str, position: CapitalPosition, field: str) -> ExecutionIssue:
    return ExecutionIssue(code=code, message=message, position_id=position.position_id, field=field)


def _order(item: FundingEvent | PositionFee) -> tuple[int, int, str]:
    identity = item.event_id if isinstance(item, FundingEvent) else item.fee_id
    return (item.model_month, item.sequence, identity)


def _root_scope_kind(analysis_scope: ScopeKind) -> ScopeKind:
    return ScopeKind.UNIT if analysis_scope is ScopeKind.UNIT else ScopeKind.INVESTMENT


def _common_equity_issues(position: CapitalPosition, analysis_scope: ScopeKind) -> list[ExecutionIssue]:
    if position.scope.kind is _root_scope_kind(analysis_scope):
        return []
    root = "that Unit" if analysis_scope is ScopeKind.UNIT else "the Investment"
    return [
        _issue(
            ExecutionIssueCode.UNSUPPORTED_COMMON_EQUITY_SCOPE,
            f"Common equity {position.position_id!r} names a {position.scope.kind.value} residual, but the final "
            f"residual of this analysis is {root}'s. Common equity is never split among scopes.",
            position,
            "scope",
        )
    ]


def _funding_issues(position: CapitalPosition, valuations: ValuationAuthority | None) -> list[ExecutionIssue]:
    issues: list[ExecutionIssue] = []
    for event in sorted(position.funding, key=_order):
        where = f"funding[{event.event_id}]"
        if event.model_month != 0:
            issues.append(
                _issue(
                    ExecutionIssueCode.UNSUPPORTED_FUNDING_TIMING,
                    f"Funding event {event.event_id!r} of {position.position_id!r} is at model month "
                    f"{event.model_month}; this executor funds positions at closing (model month 0) only. "
                    "Scheduled draws are a later extension, and nothing is moved to closing.",
                    position,
                    f"{where}.model_month",
                )
            )
        if isinstance(event.amount_rule, PctOfValue):
            if valuations is None:
                issues.append(
                    _issue(
                        ExecutionIssueCode.UNSUPPORTED_AMOUNT_RULE,
                        f"Funding event {event.event_id!r} of {position.position_id!r} is a percentage of the value at "
                        f"valuation timepoint {event.amount_rule.timepoint_id!r}; valuation timepoints are not executed "
                        "yet.",
                        position,
                        f"{where}.amount_rule",
                    )
                )
                continue
            resolution = resolve_valuation_funding(position, event, event.amount_rule, authority=valuations)
            if isinstance(resolution, UnresolvedFundingRequirement):
                issues.append(
                    _issue(
                        ExecutionIssueCode.UNRESOLVED_VALUATION_FUNDING,
                        resolution.message,
                        position,
                        f"{where}.amount_rule",
                    )
                )
    return issues


def _debt_issues(position: CapitalPosition, terms: DebtTerms) -> list[ExecutionIssue]:
    issues = [
        _issue(
            ExecutionIssueCode.UNSUPPORTED_FEE_TIMING,
            f"Fee {fee.fee_id!r} of {position.position_id!r} is at model month {fee.model_month}; this executor "
            "executes closing fees (model month 0) only.",
            position,
            f"terms.fees[{fee.fee_id}].model_month",
        )
        for fee in sorted(terms.fees, key=_order)
        if fee.model_month != 0
    ]
    if terms.pik_rate != 0.0:
        issues.append(
            _issue(
                ExecutionIssueCode.UNSUPPORTED_DEBT_PIK,
                f"{position.position_id!r} states a PIK rate of {terms.pik_rate!r}; this executor executes cash-pay "
                "debt only. PIK is never ignored and never reinterpreted.",
                position,
                "terms.pik_rate",
            )
        )
    if terms.current_pay_rate != terms.interest_rate:
        issues.append(
            _issue(
                ExecutionIssueCode.UNSUPPORTED_DEBT_CURRENT_PAY,
                f"{position.position_id!r} states a current-pay rate of {terms.current_pay_rate!r} against an "
                f"interest rate of {terms.interest_rate!r}; cash-pay debt pays its whole coupon, so the two must be "
                "equal.",
                position,
                "terms.current_pay_rate",
            )
        )
    return issues


def _preferred_issues(position: CapitalPosition, terms: PreferredEquityTerms, hold_period: int) -> list[ExecutionIssue]:
    issues: list[ExecutionIssue] = []
    if terms.current_pay_rate > terms.preferred_rate:
        issues.append(
            _issue(
                ExecutionIssueCode.UNSUPPORTED_PREFERRED_CURRENT_PAY,
                f"{position.position_id!r} pays current pay at {terms.current_pay_rate!r}, above its preferred rate "
                f"of {terms.preferred_rate!r}.",
                position,
                "terms.current_pay_rate",
            )
        )
    elif terms.preferred_rate > terms.current_pay_rate and not terms.accrual_permitted:
        issues.append(
            _issue(
                ExecutionIssueCode.UNPERMITTED_PREFERRED_ACCRUAL,
                f"{position.position_id!r} pays current pay at {terms.current_pay_rate!r} below its preferred rate of "
                f"{terms.preferred_rate!r}, but its terms do not permit accrual. The difference is never waived and "
                "accrual is never inferred.",
                position,
                "terms.accrual_permitted",
            )
        )
    if modeled_redemption_month(redemption_month=terms.redemption_month, hold_period=hold_period) is None:
        issues.append(
            _issue(
                ExecutionIssueCode.UNSUPPORTED_REDEMPTION_TIMING,
                f"{position.position_id!r} redeems at model month {terms.redemption_month}, within a hold year and "
                "before the exit. Preferred accrual is annual, so an early redemption is executed at a hold-year end "
                "only; no partial year is prorated.",
                position,
                "terms.redemption_month",
            )
        )
    return issues


def _claim_issues(
    position: CapitalPosition, analysis_scope: ScopeKind, hold_period: int, valuations: ValuationAuthority | None
) -> list[ExecutionIssue]:
    issues: list[ExecutionIssue] = []
    if analysis_scope is ScopeKind.UNIT and position.scope.kind is ScopeKind.INVESTMENT:
        issues.append(
            _issue(
                ExecutionIssueCode.UNSUPPORTED_SCOPE,
                f"{position.position_id!r} is Investment-scoped, but a standalone Unit analysis has no Investment "
                "scope.",
                position,
                "scope",
            )
        )
    issues.extend(_funding_issues(position, valuations))
    terms = position.terms
    if isinstance(terms, DebtTerms):
        issues.extend(_debt_issues(position, terms))
    elif isinstance(terms, PreferredEquityTerms):
        issues.extend(_preferred_issues(position, terms, hold_period))
    return issues


def validate_structured_execution(
    structure: CapitalStructure,
    *,
    analysis_scope: ScopeKind,
    hold_period: int,
    valuations: ValuationAuthority | None = None,
) -> tuple[ExecutionIssue, ...]:
    """Every reason the executor does not execute ``structure``, or ``()``.

    ``structure`` must already be structurally valid. ``analysis_scope`` is
    ``UNIT`` for a standalone Unit and ``INVESTMENT`` for a visible Investment;
    ``hold_period`` is the analysis' hold, which decides the exit month.

    ``valuations`` is the P7.10 authority a ``PctOfValue`` funding is sized
    from. ``None`` is the default and every pre-P7.10 caller: the rule is then
    refused with its original reason and message."""

    ordered = economic_order(structure.positions)
    issues: list[ExecutionIssue] = []
    for position in ordered:
        if position.position_class is PositionClass.COMMON_EQUITY:
            issues.extend(_common_equity_issues(position, analysis_scope))
        else:
            issues.extend(_claim_issues(position, analysis_scope, hold_period, valuations))

    markers = [position for position in ordered if position.position_class is PositionClass.COMMON_EQUITY]
    if len(markers) > 1:
        issues.append(
            ExecutionIssue(
                code=ExecutionIssueCode.MULTIPLE_COMMON_EQUITY_MARKERS,
                message=(
                    f"Common equity positions {', '.join(sorted(repr(m.position_id) for m in markers))} would split "
                    "the one residual; at most one may name it, and investor allocation is the Partnership's."
                ),
                field="positions",
            )
        )
    for marker in markers:
        if marker.scope.kind is not _root_scope_kind(analysis_scope):
            continue
        issues.extend(
            _issue(
                ExecutionIssueCode.CLAIM_BELOW_COMMON_EQUITY,
                f"{position.position_id!r} (priority {position.priority}) ranks below common equity "
                f"{marker.position_id!r} (priority {marker.priority}); common equity is the residual and is "
                "economically last.",
                position,
                "priority",
            )
            for position in ordered
            if position.position_class is not PositionClass.COMMON_EQUITY
            and position.scope == marker.scope
            and position.priority > marker.priority
        )
    return tuple(issues)
