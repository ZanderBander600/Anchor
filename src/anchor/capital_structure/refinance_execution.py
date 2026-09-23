"""Refinance & Capital Events V1 -- executing a Capital Structure that states
refinance events.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 7, 10,
11, 12, 15.4 and 17 (ratified); that document governs on any discrepancy.

The P7.8 executors hand a ``CapitalStructureWithEvents`` here; a plain
``CapitalStructure`` never arrives, so every analysis without a refinance runs
the P7.8 path exactly as before. **There is one settlement implementation**:
this module calls P7.8's own admission, scheduling, claim settlement, returns
and Common Equity functions and restates none of them. What it adds is only
what a refinance changes:

- **The legacy splice (INV-16).** When a Unit's acquisition loan retires in
  year ``y``, the Unit's cash authority is ``levered_cash_flows[t]`` for
  ``t <= y`` and ``unlevered_cash_flows[t]`` after: accepted series composed,
  nothing added back, the loan subtracted exactly once. The accepted identity
  behind it is checked first, for every year, and a failure is refused.
- **Settlement views.** A retiring position's payoff, its retiring lender fees
  and the replacement's funding and fees are settled by the event, never by an
  annual claim. The claims settle on schedules without them; results report the
  full schedules.
- **Event cash after settlement.** ``N`` joins the root residual in year ``y``
  only after every year-``y`` claim of every scope has settled, so proceeds
  never cure an operating shortfall, and negative ``N`` is an explicit Common
  Equity contribution, never a Funding Requirement.
- **Unavailability (Section 15.4).** A non-executed event leaves upstream and
  senior results valid, reports every affected position N/A with the event's
  reason, reports its replacement as unexecuted, and makes Common Equity
  unavailable. Nothing is zero-filled and nothing falls back to "no refinance".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from ..consolidation.contracts import ConsolidatedResults
from ..contracts import AcquisitionTerms
from ..engine.contracts import AcquisitionResults, ensure_finite
from ..valuation.funding import ValuationAuthority
from .contracts import (
    MONTHS_PER_HOLD_YEAR,
    CapitalPosition,
    CapitalStructureStatus,
    CapitalStructureUnit,
    CommonEquityUnavailableReason,
    FundingRequirement,
    FundingRequirementStatus,
    HoldYearPeriod,
    PositionClass,
    PositionScope,
    ScopeKind,
)
from .events import CapitalStructureWithEvents, RefinanceEvent
from .execution import (
    _Settled,
    _apply_settled,
    _common_equity,
    _executable_positions,
    _finite,
    _position_returns,
    _require_funded_closing,
    _settle_scope,
    _split,
    _unit_id,
    schedule_position,
)
from .execution_contracts import (
    CapitalStructureExecutionError,
    CommonEquityReturns,
    ExecutionIssue,
    ExecutionIssueCode,
    PositionCashFlowKind,
    PositionResultStatus,
    PositionReturns,
    PositionUnavailableReason,
    PriceBasis,
    ScheduledPosition,
    StructuredCapitalResult,
)
from .foundation import analyze_investment_capital_structure, analyze_unit_capital_structure
from .funding import investment_price_basis, unit_price_basis
from .metrics import annual_current_cash_service
from .refinance import (
    InvestmentRefinanceAuthority,
    RefinancePlan,
    UnitRefinanceAuthority,
    blocked,
    event_hold_year,
    event_month,
    legacy_balance,
    plan_refinance,
)
from .refinance_contracts import (
    RefinanceStatus,
    RefinancedCapitalResult,
    RefinancedCommonEquityReturns,
    UnexecutedPosition,
)

#: The event-settled cash of the retiring positions and the replacement.
_EVENT_SETTLED_KINDS = frozenset({PositionCashFlowKind.REFINANCE_PAYOFF, PositionCashFlowKind.REFINANCE_FUNDING})

#: The statuses of an event that never executed: Common Equity after it is
#: unavailable with ``refinance_unavailable``. ``BLOCKED`` is not among them --
#: its root cause is an unresolved Funding Requirement, which keeps P7.7's
#: reason.
_NOT_EXECUTED = frozenset({RefinanceStatus.UNAVAILABLE, RefinanceStatus.NOT_EXECUTABLE})

#: A splice identity residue this small is floating-point representation only.
_SPLICE_TOLERANCE_ABSOLUTE = 1e-6
_SPLICE_TOLERANCE_RELATIVE = 1e-12

_Layer = tuple[float, float, tuple[float, ...]]


# =============================================================================
# Events
# =============================================================================


def _events(structure: CapitalStructureWithEvents) -> tuple[RefinanceEvent, ...]:
    """The events in economic order: every Unit scope by ``unit_id``, then the
    Investment scope. The structural validator has admitted each."""

    def key(event: RefinanceEvent) -> tuple[int, str]:
        return (0, event.scope.unit_id or "") if event.scope.kind is ScopeKind.UNIT else (1, "")

    return tuple(sorted((event for event in structure.events if isinstance(event, RefinanceEvent)), key=key))


def _refuse(code: ExecutionIssueCode, message: str) -> CapitalStructureExecutionError:
    return CapitalStructureExecutionError((ExecutionIssue(code=code, message=message, field="events"),))


# =============================================================================
# The legacy splice (INV-16)
# =============================================================================


def spliced_unit_authority(results: AcquisitionResults, *, hold_year: int) -> tuple[float, ...]:
    """A Unit's cash authority once its acquisition loan retires in
    ``hold_year``: ``levered_cash_flows`` through that year, then
    ``unlevered_cash_flows``. Refused unless the accepted identity
    ``levered[t] = unlevered[t] - ADS[t] - remaining balance x [t = H]`` holds
    in every year, so the splice can drop or double nothing but the loan."""

    levered = results.levered_cash_flows
    unlevered = results.unlevered_cash_flows
    hold_period = len(results.annual_debt_service)
    for year in range(1, hold_period + 1):
        expected = unlevered[year] - results.annual_debt_service[year - 1]
        if year == hold_period:
            expected = expected - results.remaining_loan_balance
        tolerance = _SPLICE_TOLERANCE_ABSOLUTE + _SPLICE_TOLERANCE_RELATIVE * abs(levered[year])
        if abs(levered[year] - expected) > tolerance:
            raise _refuse(
                ExecutionIssueCode.LEGACY_AUTHORITY_SPLICE_MISMATCH,
                f"Year {year}'s levered cash flow {levered[year]!r} is not its unlevered cash flow less the acquisition "
                f"loan's claims ({expected!r}). Retiring the loan would drop or double a non-debt item, so it is "
                "refused.",
            )
    return (*levered[: hold_year + 1], *unlevered[hold_year + 1 :])


def _legacy_requirements(
    requirements: tuple[FundingRequirement, ...], *, unit_id: str, retired_in: int | None
) -> tuple[FundingRequirement, ...]:
    """A retired acquisition loan has no claim after its event year, so its
    later P7.7 requirements -- including the sale-year balance -- are dropped."""

    if retired_in is None:
        return requirements
    return tuple(
        requirement
        for requirement in requirements
        if requirement.scope.unit_id != unit_id
        or not isinstance(requirement.period, HoldYearPeriod)
        or requirement.period.hold_year <= retired_in
    )


# =============================================================================
# One scope
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class _ScopeRun:
    """One scope after settlement: each position's reporting view and
    settlement, what remains of the scope's cash, the plan as it finally
    stands, and the positions reported N/A because of the event."""

    views: tuple[ScheduledPosition, ...]
    settlement_views: dict[str, ScheduledPosition]
    settled: dict[str, _Settled]
    residual: list[float]
    plan: RefinancePlan | None
    unavailable_ids: frozenset[str]


def _settlement_view(view: ScheduledPosition, *, model_month: int) -> ScheduledPosition:
    """``view`` without the cash the event settles: payoffs, the replacement's
    funding, and the fees paid at the event month."""

    return replace(
        view,
        events=tuple(
            item
            for item in view.events
            if item.kind not in _EVENT_SETTLED_KINDS
            and not (item.kind is PositionCashFlowKind.FEE and item.model_month == model_month)
        ),
    )


def _is_blocked(plan: RefinancePlan, settled: dict[str, _Settled], positions: dict[str, CapitalPosition]) -> str | None:
    """Why an executed plan is blocked, or ``None``: an unresolved Funding
    Requirement in the scope at or before the event year, or an unresolved
    continuing senior position."""

    hold_year = event_hold_year(plan.event)
    replacement = positions[plan.event.replacement_position_id]
    found: list[str] = []
    for position_id, (claims, _) in sorted(settled.items()):
        senior = positions[position_id].priority < replacement.priority
        for claim in claims or ():
            requirement = claim.settlement.funding_requirement
            if (
                requirement is not None
                and requirement.status is FundingRequirementStatus.UNRESOLVED
                and (claim.hold_year <= hold_year or senior)
            ):
                found.append(requirement.requirement_id)
    if not found:
        return None
    return (
        f"'{plan.event.label}' is blocked: Funding Requirement(s) {', '.join(found)} are unresolved at or before its "
        "event, so the cash of the refinanced scope is unknowable."
    )


def _run_scope(
    positions: tuple[CapitalPosition, ...],
    *,
    plan: RefinancePlan | None,
    authority: tuple[float, ...],
    hold_period: int,
    price_basis: PriceBasis,
    valuations: ValuationAuthority | None,
    blocking: tuple[str, ...] = (),
) -> tuple[_ScopeRun, tuple[str, ...]]:
    """Schedule and settle one scope's claim-bearing positions against
    ``authority``, in economic order, and return what blocks the scopes after
    it."""

    by_id = {position.position_id: position for position in positions}
    special: dict[str, ScheduledPosition] = {}
    unavailable: frozenset[str] = frozenset()
    replacement_id = None if plan is None else plan.event.replacement_position_id
    if plan is not None and plan.executed:
        special = {view.position.position_id: view for view in plan.retiring_views}
        if plan.replacement_view is not None:
            special[plan.replacement_view.position.position_id] = plan.replacement_view
    elif plan is not None:
        unavailable = plan.affected_position_ids
    views = tuple(
        special.get(position.position_id)
        or schedule_position(position, price_basis=price_basis, hold_period=hold_period, valuations=valuations)
        for position in positions
        if position.position_id != replacement_id or position.position_id in special
    )
    model_month = 0 if plan is None else event_month(plan.event)
    settlement_views = {
        view.position.position_id: _settlement_view(view, model_month=model_month)
        if view.position.position_id in special
        else view
        for view in views
    }
    residual = list(authority)
    settled, onward = _settle_scope(
        tuple(settlement_views[view.position.position_id] for view in views if view.position.position_id not in unavailable),
        residual=residual,
        hold_period=hold_period,
        blocking=blocking,
    )
    if plan is not None and plan.executed:
        reason = _is_blocked(plan, settled, by_id)
        if reason is not None:
            plan = blocked(plan, message=reason)
            unavailable = frozenset(plan.affected_position_ids)
    return (
        _ScopeRun(
            views=views,
            settlement_views=settlement_views,
            settled=settled,
            residual=residual,
            plan=plan,
            unavailable_ids=unavailable,
        ),
        onward,
    )


# =============================================================================
# Structure
# =============================================================================


def _event_layers(
    views: Iterable[ScheduledPosition],
    *,
    plan: RefinancePlan | None,
    senior_capital: float,
    senior_service: tuple[float, ...],
    hold_period: int,
) -> tuple[dict[str, _Layer], float, tuple[float, ...]]:
    """Each position's attachment, detachment and cumulative service through
    it, in priority order, as P7.8 states them -- except the replacement,
    whose layer is an event fact: attachment at the continuing senior balance
    after month ``m``, detachment ``B_sen + G``, and no coverage before its
    first service year. Its principal is not a closing fact, so it never joins
    a later position's closing attachment; its service joins every junior's."""

    layers: dict[str, _Layer] = {}
    capital, service = senior_capital, senior_service
    replacement_id = None if plan is None or not plan.executed else plan.event.replacement_position_id
    for view in views:
        own = annual_current_cash_service(view.events, hold_period=hold_period)
        through = tuple(
            ensure_finite(f"cumulative_service[{year}]", total + mine)
            for year, (total, mine) in enumerate(zip(service, own, strict=True), start=1)
        )
        if plan is not None and view.position.position_id == replacement_id:
            hold_year = event_hold_year(plan.event)
            attachment = plan.continuing_senior_balance
            detachment = ensure_finite("detachment_basis", attachment + view.funded_amount)
            layers[view.position.position_id] = (
                attachment,
                detachment,
                tuple(0.0 if year <= hold_year else value for year, value in enumerate(through, start=1)),
            )
            service = through
            continue
        attachment = capital
        capital = ensure_finite("detachment_basis", attachment + view.funded_amount)
        service = through
        layers[view.position.position_id] = (attachment, capital, through)
    return layers, capital, service


def _retired_service(service: tuple[float, ...], *, hold_year: int) -> tuple[float, ...]:
    """A retired acquisition loan's annual service: as accepted through its
    event year, and none after."""

    return tuple(value if year <= hold_year else 0.0 for year, value in enumerate(service, start=1))


# =============================================================================
# Results
# =============================================================================


def _unavailable_message(plan: RefinancePlan) -> str:
    detail = plan.result.unavailable_message or ""
    return (
        f"Not reported: its cash after model month {event_month(plan.event)} depends on '{plan.event.label}', which "
        f"did not execute for this variant. {detail}".strip()
    )


def _returns(
    run: _ScopeRun,
    *,
    layers: dict[str, _Layer],
    noi_by_year: tuple[float, ...],
    hold_period: int,
    also_unavailable: frozenset[str] = frozenset(),
    message: str | None = None,
) -> tuple[PositionReturns, ...]:
    """Each position's returns. A position whose cash depends on an event that
    did not execute is N/A with the event's reason -- unless its own settlement
    already reports an unresolved or blocked claim, which is the truer root
    cause and is kept, with its Funding Requirements, exactly as P7.8 states
    it. Nothing settled is ever discarded."""

    found: list[PositionReturns] = []
    for view in run.views:
        position_id = view.position.position_id
        layer = layers[position_id]
        settled = run.settled.get(position_id, (None, ()))
        base = _position_returns(view, settled=settled, layer=layer, noi_by_year=noi_by_year, hold_period=hold_period)
        affected = position_id in run.unavailable_ids or position_id in also_unavailable
        if affected and (position_id not in run.settled or base.status is PositionResultStatus.COMPLETE):
            text = message if run.plan is None else _unavailable_message(run.plan)
            base = replace(
                base,
                status=PositionResultStatus.REFINANCE_UNAVAILABLE,
                unavailable_reason=PositionUnavailableReason.REFINANCE_UNAVAILABLE,
                unavailable_message=text or "",
                blocking_requirement_ids=(),
                annual_cash_flows=None,
                irr=None,
                irr_status=None,
                total_cash_received=None,
                moic=None,
                profit=None,
            )
        found.append(base)
    return tuple(found)


def _unexecuted(run: _ScopeRun, positions: dict[str, CapitalPosition]) -> tuple[UnexecutedPosition, ...]:
    plan = run.plan
    if plan is None or plan.executed:
        return ()
    replacement = positions[plan.event.replacement_position_id]
    return (
        UnexecutedPosition(
            position_id=replacement.position_id,
            name=replacement.name,
            position_class=replacement.position_class,
            scope=replacement.scope,
            priority=replacement.priority,
            event_id=plan.event.event_id,
            unavailable_reason=PositionUnavailableReason.REFINANCE_UNAVAILABLE,
            unavailable_message=_unavailable_message(plan),
        ),
    )


def _requirements_of(returns: tuple[PositionReturns, ...]) -> tuple[FundingRequirement, ...]:
    return tuple(requirement for position in returns for requirement in position.funding_requirements)


def _common_equity_result(
    *,
    marker: CapitalPosition | None,
    root_scope: PositionScope,
    requirements: tuple[FundingRequirement, ...],
    recurring: tuple[float, ...],
    event_cash: dict[int, float],
    not_executed: tuple[RefinancePlan, ...],
) -> RefinancedCommonEquityReturns:
    """Common Equity after the events. With every event executed, it is P7.8's
    own result on the final series, decomposed into recurring and event cash.
    An unresolved Funding Requirement keeps P7.7's reason; otherwise a
    non-executed event makes it unavailable with ``refinance_unavailable``."""

    unresolved = any(requirement.status is FundingRequirementStatus.UNRESOLVED for requirement in requirements)
    if not_executed and not unresolved:
        names = ", ".join(f"'{plan.event.label}'" for plan in not_executed)
        details = " ".join(plan.result.unavailable_message or "" for plan in not_executed)
        return RefinancedCommonEquityReturns(
            position_id=None if marker is None else marker.position_id,
            scope=root_scope if marker is None else marker.scope,
            status=CapitalStructureStatus.REFINANCE_UNAVAILABLE,
            cash_flows=None,
            unavailable_reason=CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE,
            unavailable_message=(
                f"Common Equity is not reported: refinance {names} did not execute for this variant, so the cash "
                f"after it is unknowable. Property, Business Plan and project results are unaffected. {details}".strip()
            ),
            irr=None,
            irr_status=None,
            equity_multiple=None,
            total_equity_invested=None,
            total_cash_returned=None,
            total_profit=None,
            recurring_cash_flows=None,
            event_cash_flows=None,
        )
    events = [0.0 for _ in recurring]
    final = list(recurring)
    for year, amount in sorted(event_cash.items()):
        events[year] = ensure_finite(f"event_cash_flows[{year}]", events[year] + amount)
        final[year] = final[year] + amount
    base: CommonEquityReturns = _common_equity(
        marker=marker, root_scope=root_scope, requirements=requirements, residual=_finite(final)
    )
    available = base.cash_flows is not None
    return RefinancedCommonEquityReturns(
        position_id=base.position_id,
        scope=base.scope,
        status=base.status,
        cash_flows=base.cash_flows,
        unavailable_reason=base.unavailable_reason,
        unavailable_message=base.unavailable_message,
        irr=base.irr,
        irr_status=base.irr_status,
        equity_multiple=base.equity_multiple,
        total_equity_invested=base.total_equity_invested,
        total_cash_returned=base.total_cash_returned,
        total_profit=base.total_profit,
        recurring_cash_flows=recurring if available else None,
        event_cash_flows=tuple(events) if available else None,
    )


def _result(
    *,
    base: StructuredCapitalResult,
    common_equity: RefinancedCommonEquityReturns,
    plans: tuple[RefinancePlan, ...],
    unexecuted: tuple[UnexecutedPosition, ...],
) -> RefinancedCapitalResult:
    return RefinancedCapitalResult(
        analysis_scope=base.analysis_scope,
        unit_ids=base.unit_ids,
        hold_period=base.hold_period,
        status=common_equity.status,
        legacy_acquisition_loans=base.legacy_acquisition_loans,
        positions=base.positions,
        funding_requirements=base.funding_requirements,
        common_equity=common_equity,
        capital_events=tuple(plan.result for plan in plans),
        unexecuted_positions=unexecuted,
    )


# =============================================================================
# The executors
# =============================================================================


def execute_unit_refinance(
    *,
    unit_id: str,
    terms: AcquisitionTerms,
    results: AcquisitionResults,
    capital_structure: CapitalStructureWithEvents,
    valuations: ValuationAuthority | None = None,
) -> RefinancedCapitalResult:
    """A standalone Unit whose Capital Structure states a refinance."""

    foundation = analyze_unit_capital_structure(unit_id=unit_id, terms=terms, results=results)
    loan = foundation.legacy_acquisition_loan
    hold_period = terms.hold_period
    admitted = _executable_positions(
        capital_structure,
        member_unit_ids=(unit_id,),
        acquisition_loan_unit_ids=() if loan is None else (unit_id,),
        analysis_scope=ScopeKind.UNIT,
        hold_period=hold_period,
        valuations=valuations,
    )
    marker, claim_bearing = _split(admitted)
    (event,) = _events(capital_structure)
    basis = unit_price_basis(terms)
    plan = plan_refinance(
        event,
        scope_positions=claim_bearing,
        hold_period=hold_period,
        price_basis=basis,
        valuations=valuations,
        unit=UnitRefinanceAuthority(unit_id=unit_id, terms=terms, results=results, legacy_loan=loan),
        investment=None,
    )
    retired_in = event_hold_year(event) if plan.executed and plan.retired_legacy_unit_id == unit_id else None
    source = foundation.cash_authority.post_acquisition_debt_cash_flows
    if retired_in is not None:
        source = spliced_unit_authority(results, hold_year=retired_in)
    run, _ = _run_scope(
        claim_bearing, plan=plan, authority=source, hold_period=hold_period, price_basis=basis, valuations=valuations
    )
    _require_funded_closing(tuple(run.settlement_views.values()), closing_source=source[0], root="Unit")
    # A blocked plan was settled on the spliced authority: the retirement it
    # scheduled stands, and only what depends on the event is reported N/A.
    plan = run.plan if run.plan is not None else plan

    senior_service = results.annual_debt_service
    if retired_in is not None:
        senior_service = _retired_service(senior_service, hold_year=retired_in)
    layers, _, _ = _event_layers(
        run.views, plan=plan, senior_capital=results.loan_amount, senior_service=senior_service, hold_period=hold_period
    )
    returns = _returns(run, layers=layers, noi_by_year=results.noi_by_year, hold_period=hold_period)
    requirements = (
        *_legacy_requirements(foundation.funding_requirements, unit_id=unit_id, retired_in=retired_in),
        *_requirements_of(returns),
    )
    common_equity = _common_equity_result(
        marker=marker,
        root_scope=PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id),
        requirements=requirements,
        recurring=_finite(run.residual),
        event_cash={event_hold_year(event): plan.net_event_cash} if plan.executed else {},
        not_executed=(plan,) if plan.result.status in _NOT_EXECUTED else (),
    )
    base = StructuredCapitalResult(
        analysis_scope=ScopeKind.UNIT,
        unit_ids=(unit_id,),
        hold_period=hold_period,
        status=common_equity.status,
        legacy_acquisition_loans=() if loan is None else (loan,),
        positions=returns,
        funding_requirements=requirements,
        common_equity=common_equity,
    )
    return _result(
        base=base,
        common_equity=common_equity,
        plans=(plan,),
        unexecuted=_unexecuted(run, {position.position_id: position for position in claim_bearing}),
    )


def _require_no_unit_debt_after(
    event: RefinanceEvent,
    *,
    units: tuple[CapitalStructureUnit, ...],
    unit_runs: list[tuple[CapitalStructureUnit, _ScopeRun]],
    loans: dict[str | None, object],
    retired: dict[str, int],
    hold_period: int,
) -> None:
    """Refuse an Investment-scope refinance while any Unit-scoped debt is
    outstanding after its month (Section 12.4): an acquisition loan still owed
    then (from the engine's balance service), or an authored Unit debt position
    whose final schedule -- the replacement's included -- runs past it. V1
    never counts another scope's debt in a constraint."""

    model_month = event_month(event)
    if model_month >= MONTHS_PER_HOLD_YEAR * hold_period:
        return
    runs = {unit.unit_id: run for unit, run in unit_runs}
    carrying: list[str] = []
    for unit in units:
        run = runs.get(unit.unit_id)
        retired_at = retired.get(unit.unit_id)
        loan_owed = False
        if unit.unit_id in loans and (retired_at is None or MONTHS_PER_HOLD_YEAR * retired_at > model_month):
            authority = UnitRefinanceAuthority(unit_id=unit.unit_id, terms=unit.terms, results=unit.results, legacy_loan=None)
            loan_owed = legacy_balance(authority, model_month=model_month).balance_after_month > 0.0
        authored_owed = run is not None and any(
            view.modeled_payoff_month > model_month
            for view in run.views
            if view.position.position_class in (PositionClass.SENIOR_DEBT, PositionClass.MEZZANINE_DEBT)
        )
        if loan_owed or authored_owed:
            carrying.append(unit.unit_id)
    if carrying:
        raise _refuse(
            ExecutionIssueCode.INVESTMENT_REFINANCE_WITH_UNIT_DEBT,
            f"'{event.label}' refinances the Investment scope while Unit-scoped debt of {', '.join(carrying)} is "
            f"outstanding after model month {model_month}. V1 defers that case and never counts another scope's debt "
            "in a constraint.",
        )


def execute_investment_refinance(
    *,
    units: Iterable[CapitalStructureUnit],
    consolidated: ConsolidatedResults,
    capital_structure: CapitalStructureWithEvents,
    valuations: ValuationAuthority | None = None,
) -> RefinancedCapitalResult:
    """A visible Investment whose Capital Structure states refinances: at most
    one per Unit scope, and at most one for the Investment scope."""

    given = tuple(units)
    foundation = analyze_investment_capital_structure(units=given, consolidated=consolidated)
    ordered = tuple(sorted(given, key=lambda unit: unit.unit_id))
    hold_period = consolidated.hold_period
    loans = {loan.scope.unit_id: loan for loan in foundation.legacy_acquisition_loans}
    admitted = _executable_positions(
        capital_structure,
        member_unit_ids=consolidated.unit_ids,
        acquisition_loan_unit_ids=tuple(unit_id for unit_id in loans if unit_id is not None),
        analysis_scope=ScopeKind.INVESTMENT,
        hold_period=hold_period,
        valuations=valuations,
    )
    marker, claim_bearing = _split(admitted)
    by_position = {position.position_id: position for position in claim_bearing}
    events = _events(capital_structure)
    unit_events = {event.scope.unit_id: event for event in events if event.scope.kind is ScopeKind.UNIT}
    investment_event = next((event for event in events if event.scope.kind is ScopeKind.INVESTMENT), None)
    unit_positions = {
        unit.unit_id: tuple(
            position for position in claim_bearing if position.scope.kind is ScopeKind.UNIT and _unit_id(position) == unit.unit_id
        )
        for unit in ordered
    }
    investment_positions = tuple(position for position in claim_bearing if position.scope.kind is ScopeKind.INVESTMENT)

    investment_residual = list(foundation.investment_cash_authority.cash_flows_after_unit_positions)
    closing_views: list[ScheduledPosition] = []
    plans: list[RefinancePlan] = []
    returns: list[PositionReturns] = []
    unexecuted: list[UnexecutedPosition] = []
    unit_blocking: list[str] = []
    event_cash: dict[int, float] = {}
    retired: dict[str, int] = {}
    unit_runs: list[tuple[CapitalStructureUnit, _ScopeRun]] = []
    unit_event_unavailable = False

    for unit in ordered:
        in_unit = unit_positions[unit.unit_id]
        event = unit_events.get(unit.unit_id)
        if not in_unit and event is None:
            continue
        basis = unit_price_basis(unit.terms)
        plan = None
        if event is not None:
            plan = plan_refinance(
                event,
                scope_positions=in_unit,
                hold_period=hold_period,
                price_basis=basis,
                valuations=valuations,
                unit=UnitRefinanceAuthority(
                    unit_id=unit.unit_id, terms=unit.terms, results=unit.results, legacy_loan=loans.get(unit.unit_id)
                ),
                investment=None,
            )
        retired_in = None
        source = unit.results.levered_cash_flows
        if plan is not None and plan.executed and plan.retired_legacy_unit_id == unit.unit_id:
            retired_in = event_hold_year(plan.event)
            source = spliced_unit_authority(unit.results, hold_year=retired_in)
        run, unresolved = _run_scope(
            in_unit, plan=plan, authority=source, hold_period=hold_period, price_basis=basis, valuations=valuations
        )
        unit_blocking.extend(unresolved)
        closing_views.extend(run.settlement_views.values())
        final_plan = run.plan
        if final_plan is not None:
            plans.append(final_plan)
            if final_plan.executed:
                event_cash[event_hold_year(final_plan.event)] = ensure_finite(
                    "event_cash", event_cash.get(event_hold_year(final_plan.event), 0.0) + final_plan.net_event_cash
                )
            elif final_plan.result.status in _NOT_EXECUTED:
                unit_event_unavailable = True
        if retired_in is not None:
            retired[unit.unit_id] = retired_in
            for year in range(retired_in + 1, hold_period + 1):
                investment_residual[year] = investment_residual[year] + (source[year] - unit.results.levered_cash_flows[year])
        for view in run.views:
            position_id = view.position.position_id
            if position_id in run.unavailable_ids or position_id not in run.settled:
                continue
            claims, _ = run.settled[position_id]
            if claims is not None:
                _apply_settled(investment_residual, run.settlement_views[position_id], claims)
        senior_service = unit.results.annual_debt_service
        if retired_in is not None:
            senior_service = _retired_service(senior_service, hold_year=retired_in)
        unit_layers, _, _ = _event_layers(
            run.views,
            plan=final_plan,
            senior_capital=unit.results.loan_amount,
            senior_service=senior_service,
            hold_period=hold_period,
        )
        returns.extend(_returns(run, layers=unit_layers, noi_by_year=unit.results.noi_by_year, hold_period=hold_period))
        unexecuted.extend(_unexecuted(run, by_position))
        unit_runs.append((unit, run))

    if investment_event is not None:
        _require_no_unit_debt_after(
            investment_event, units=ordered, unit_runs=unit_runs, loans=loans, retired=retired, hold_period=hold_period
        )
    investment_basis = investment_price_basis(consolidated)
    investment_plan = None
    if investment_event is not None:
        investment_plan = plan_refinance(
            investment_event,
            scope_positions=investment_positions,
            hold_period=hold_period,
            price_basis=investment_basis,
            valuations=valuations,
            unit=None,
            investment=InvestmentRefinanceAuthority(units=ordered, consolidated=consolidated),
        )
    if unit_event_unavailable:
        # A Unit event that did not execute leaves the cash reaching the
        # Investment scope unknowable after it: every Investment-scoped
        # position is N/A, and nothing is settled for it.
        investment_run = _ScopeRun(
            views=tuple(
                schedule_position(position, price_basis=investment_basis, hold_period=hold_period, valuations=valuations)
                for position in investment_positions
                if investment_plan is None or position.position_id != investment_event.replacement_position_id  # type: ignore[union-attr]
            ),
            settlement_views={},
            settled={},
            residual=investment_residual,
            plan=None,
            unavailable_ids=frozenset(position.position_id for position in investment_positions),
        )
        blocked_investment_message = (
            "Not reported: a refinance of one of the Investment's Units did not execute for this variant, so the cash "
            "reaching the Investment scope is unknowable."
        )
    else:
        investment_run, _ = _run_scope(
            investment_positions,
            plan=investment_plan,
            authority=tuple(investment_residual),
            hold_period=hold_period,
            price_basis=investment_basis,
            valuations=valuations,
            blocking=tuple(unit_blocking),
        )
        blocked_investment_message = None
    closing_views.extend(investment_run.settlement_views.values())
    _require_funded_closing(
        tuple(closing_views),
        closing_source=foundation.investment_cash_authority.cash_flows_after_unit_positions[0],
        root="Investment",
    )
    if investment_run.plan is not None:
        plans.append(investment_run.plan)
        if investment_run.plan.executed:
            year = event_hold_year(investment_run.plan.event)
            event_cash[year] = ensure_finite("event_cash", event_cash.get(year, 0.0) + investment_run.plan.net_event_cash)

    consolidated_service = consolidated.annual_debt_service
    for unit in ordered:
        if unit.unit_id in retired:
            consolidated_service = tuple(
                ensure_finite(f"senior_service[{year}]", total - unit.results.annual_debt_service[year - 1])
                if year > retired[unit.unit_id]
                else total
                for year, total in enumerate(consolidated_service, start=1)
            )
    capital, service = consolidated.loan_amount, consolidated_service
    for unit, run in unit_runs:
        _, capital, service = _event_layers(
            run.views, plan=run.plan, senior_capital=capital, senior_service=service, hold_period=hold_period
        )
    investment_layers, _, _ = _event_layers(
        investment_run.views, plan=investment_run.plan, senior_capital=capital, senior_service=service, hold_period=hold_period
    )
    returns.extend(
        _returns(
            investment_run,
            layers=investment_layers,
            noi_by_year=consolidated.noi_by_year,
            hold_period=hold_period,
            message=blocked_investment_message,
        )
    )
    unexecuted.extend(_unexecuted(investment_run, by_position))
    if investment_plan is not None and unit_event_unavailable:
        unexecuted.extend(
            UnexecutedPosition(
                position_id=position.position_id,
                name=position.name,
                position_class=position.position_class,
                scope=position.scope,
                priority=position.priority,
                event_id=investment_plan.event.event_id,
                unavailable_reason=PositionUnavailableReason.REFINANCE_UNAVAILABLE,
                unavailable_message=blocked_investment_message or "",
            )
            for position in investment_positions
            if position.position_id == investment_plan.event.replacement_position_id
        )
        plans.append(investment_plan)

    not_executed = tuple(plan for plan in plans if plan.result.status in _NOT_EXECUTED)
    requirements: list[FundingRequirement] = []
    for requirement in foundation.funding_requirements:
        unit_id = requirement.scope.unit_id
        if unit_id is not None and unit_id in retired:
            requirements.extend(_legacy_requirements((requirement,), unit_id=unit_id, retired_in=retired[unit_id]))
        else:
            requirements.append(requirement)
    requirements.extend(_requirements_of(tuple(returns)))
    common_equity = _common_equity_result(
        marker=marker,
        root_scope=PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None),
        requirements=tuple(requirements),
        recurring=_finite(investment_run.residual),
        event_cash=event_cash if not not_executed else {},
        not_executed=not_executed,
    )
    base = StructuredCapitalResult(
        analysis_scope=ScopeKind.INVESTMENT,
        unit_ids=consolidated.unit_ids,
        hold_period=hold_period,
        status=common_equity.status,
        legacy_acquisition_loans=foundation.legacy_acquisition_loans,
        positions=tuple(returns),
        funding_requirements=tuple(requirements),
        common_equity=common_equity,
    )
    return _result(base=base, common_equity=common_equity, plans=tuple(plans), unexecuted=tuple(unexecuted))


__all__ = [
    "execute_investment_refinance",
    "execute_unit_refinance",
    "spliced_unit_authority",
]
