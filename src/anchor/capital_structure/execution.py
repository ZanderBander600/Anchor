"""Phase 7 Gate P7.8 -- the structured-position executor.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
3 (P-3, P-4, P-7, P-9, P-14, P-15), 12.3 (CS-4 to CS-8), 12.4, 12.6 and 14, and
the P7.8 decisions of ``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md``;
those documents govern on any discrepancy. P7.8 carries the Q16 engine-scope
approval for executing authored positions downstream of completed project
economics. No Property, NOI, exit, acquisition-debt, consolidation or IRR
formula moves.

**Downstream of the P7.7 foundation.** Each executor first runs the unchanged
P7.7 facade, which adapts every Unit's acquisition loan read-only, reports its
Funding Requirements and names the cash authorities. Authored positions are
then applied to those authorities, never to a reconstruction:

- a Unit-scoped position reads its own Unit's post-acquisition-debt cash,
  ``AcquisitionResults.levered_cash_flows``, in which the acquisition loan is
  already paid exactly once;
- an Investment-scoped position reads ``ConsolidatedResults.levered_cash_flows``
  (every Unit loan, both Business Plans and the transaction costs already in
  it), after the authored Unit positions' own effects are applied to it once.

**Economic order (P-7).** Every Unit scope independently, then the Investment
scope; within a scope, ascending priority. List order never participates, so a
permutation of ``CapitalStructure.positions`` changes nothing.

**Common Equity residual.** Starting from the scope's authority series:

- at closing, each authored funding received is added and each authored fee
  deducted;
- in each hold year, each position's annual claim is settled in priority order
  with ``settle_claim`` against the eligible cash ``max(residual, 0)``, and the
  residual falls by everything paid on the claim: from cash, and from any
  common-equity contribution its own resolution names.

A negative project year therefore stays negative, a resolved shortfall adds a
further negative contribution, and equity contributed to cure one position is
never cash available to the next. The Common Equity Cash Flow is never floored.
One Unit's surplus never pays another Unit's claim.

**Unresolved funding (P7.7 Section 6.5).** A position whose claim is left
unresolved reports N/A returns, and its own settlement stops at that first
unresolved claim: its later contractual events stay in its schedule, but with no
arrears or default convention their settlement is unknowable, so no later
year is settled and no later Funding Requirement is emitted. Every position
junior to it in its scope, and every Investment-scoped position once any Unit
scope is unresolved, is blocked and not settled at all. Senior and independent
positions stay valid. The Common Equity result is unavailable. Nothing is
zero-filled, carried forward, accrued, written off or cured by assumption, and
upstream results are untouched.

**Closing is never over-funded.** Before any claim is settled, every authored
closing funding and fee is applied to the analysis root's pre-structured-capital
closing flow -- the Unit's own, or the Investment's after its Business Plan and
transaction costs. A root flow above ``OVERFUNDED_CLOSING_TOLERANCE`` ($0.01)
is refused: no reserve, closing distribution or recapitalization is inferred,
and nothing is resized. A Unit funded locally beyond its own equity need is not
refused while the Investment root is not.

**Neutral.** With no authored claim-bearing position the Common Equity Cash
Flow *is* the P7.7 authority series, passed through untouched.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from ..consolidation.contracts import ConsolidatedResults
from ..contracts import AcquisitionTerms
from ..engine.contracts import AcquisitionResults, ensure_finite
from .contracts import (
    CapitalPosition,
    CapitalStructure,
    CapitalStructureError,
    CapitalStructureUnit,
    CapitalStructureValidationError,
    ContractualClaim,
    DebtTerms,
    FundingRequirement,
    FundingRequirementStatus,
    HoldYearPeriod,
    PositionClass,
    PositionScope,
    PreferredEquityTerms,
    ScopeKind,
)
from .debt_position import schedule_debt_position
from .execution_contracts import (
    OVERFUNDED_CLOSING_TOLERANCE,
    CapitalStructureExecutionError,
    CommonEquityReturns,
    DebtPositionSchedule,
    ExecutionIssue,
    ExecutionIssueCode,
    PositionAnnualClaim,
    PositionResultStatus,
    PositionReturns,
    PositionUnavailableReason,
    PreferredPositionSchedule,
    PriceBasis,
    ScheduledPosition,
    StructuredCapitalResult,
)
from .execution_validation import validate_structured_execution
from .foundation import (
    analyze_investment_capital_structure,
    analyze_unit_capital_structure,
    annual_period_of_model_month,
    common_equity_outcome,
    settle_claim,
)
from .funding import closing_events, funded_amount, investment_price_basis, resolve_funding, unit_price_basis
from .metrics import (
    annual_current_cash_service,
    annual_position_cash_flows,
    common_equity_metrics,
    coverage_through,
    debt_yield_through,
    event_order_key,
    loan_to_price,
    position_irr,
    position_receipts,
)
from .preferred import schedule_preferred_position
from .validation import economic_order, validate_capital_structure

#: A position's settlement: its annual claims (``None`` when blocked), and the
#: unresolved requirement ids -- its own, or the senior ones that block it.
_Settled = tuple[tuple[PositionAnnualClaim, ...] | None, tuple[str, ...]]

#: A position's layer: attachment basis, detachment basis, and the cumulative
#: current cash service through it in each hold year.
_Layer = tuple[float, float, tuple[float, ...]]


# =============================================================================
# Admission
# =============================================================================


def _executable_positions(
    structure: CapitalStructure | None,
    *,
    member_unit_ids: tuple[str, ...],
    acquisition_loan_unit_ids: tuple[str, ...],
    analysis_scope: ScopeKind,
    hold_period: int,
) -> tuple[CapitalPosition, ...]:
    """The authored positions in economic order. An invalid structure raises
    ``CapitalStructureValidationError`` (P7.7, unchanged); a valid one the
    executor does not execute raises ``CapitalStructureExecutionError``."""

    if structure is None:
        return ()
    issues = validate_capital_structure(
        structure, member_unit_ids=member_unit_ids, acquisition_loan_unit_ids=acquisition_loan_unit_ids
    )
    if issues:
        raise CapitalStructureValidationError(issues)
    execution_issues = validate_structured_execution(structure, analysis_scope=analysis_scope, hold_period=hold_period)
    if execution_issues:
        raise CapitalStructureExecutionError(execution_issues)
    return economic_order(structure.positions)


def _split(positions: tuple[CapitalPosition, ...]) -> tuple[CapitalPosition | None, tuple[CapitalPosition, ...]]:
    """The common-equity marker, if any (at most one is admitted), and the
    claim-bearing positions in economic order."""

    markers = [position for position in positions if position.position_class is PositionClass.COMMON_EQUITY]
    claim_bearing = tuple(position for position in positions if position.position_class is not PositionClass.COMMON_EQUITY)
    return (markers[0] if markers else None), claim_bearing


def _unit_id(position: CapitalPosition) -> str:
    unit_id = position.scope.unit_id
    if position.scope.kind is not ScopeKind.UNIT or unit_id is None:
        raise CapitalStructureError(f"{position.position_id!r} is not Unit-scoped.")
    return unit_id


# =============================================================================
# Scheduling
# =============================================================================


def schedule_position(position: CapitalPosition, *, price_basis: PriceBasis, hold_period: int) -> ScheduledPosition:
    """Resolve and schedule one authored claim-bearing position: its closing
    funding and fees, then its debt or preferred events, in canonical order.
    ``price_basis`` is its scope's stated acquisition price."""

    resolved = resolve_funding(position, price_basis=price_basis)
    principal = funded_amount(resolved)
    terms = position.terms
    debt_schedule: DebtPositionSchedule | None = None
    preferred_schedule: PreferredPositionSchedule | None = None
    if isinstance(terms, DebtTerms):
        debt, contractual = schedule_debt_position(
            position_id=position.position_id, principal=principal, terms=terms, hold_period=hold_period
        )
        debt_schedule, payoff_month, balance = debt, debt.modeled_payoff_month, debt.balance_at_payoff
    elif isinstance(terms, PreferredEquityTerms):
        preferred, contractual = schedule_preferred_position(
            position_id=position.position_id, principal=principal, terms=terms, hold_period=hold_period
        )
        preferred_schedule, payoff_month, balance = preferred, preferred.modeled_payoff_month, preferred.balance_at_redemption
    else:
        raise CapitalStructureError(f"{position.position_id!r} carries no contractual claim to schedule.")

    events = tuple(sorted((*closing_events(position, resolved), *contractual), key=event_order_key))
    duplicated = sorted(identity for identity, count in Counter(event.event_id for event in events).items() if count > 1)
    if duplicated:
        raise CapitalStructureExecutionError(
            ExecutionIssue(
                code=ExecutionIssueCode.DUPLICATE_RESULT_EVENT_ID,
                message=(
                    f"{position.position_id!r} would report two cash events named {identity!r}; an authored funding "
                    "or fee id must not repeat a scheduled event id."
                ),
                position_id=position.position_id,
                field="funding",
            )
            for identity in duplicated
        )
    return ScheduledPosition(
        position=position,
        price_basis=price_basis,
        funding=resolved,
        funded_amount=principal,
        events=events,
        debt_schedule=debt_schedule,
        preferred_schedule=preferred_schedule,
        modeled_payoff_month=payoff_month,
        balance_at_maturity_or_exit=balance,
    )


# =============================================================================
# Settlement
# =============================================================================


def _apply_closing(residual: list[float], scheduled: ScheduledPosition) -> None:
    """Common equity's side of the closing events: the negative of each
    provider event, so a funding received is a source and a fee a use."""

    for event in scheduled.events:
        if event.model_month == 0:
            residual[0] = residual[0] - event.amount


def _require_funded_closing(scheduled: tuple[ScheduledPosition, ...], *, closing_source: float, root: str) -> None:
    """Fail closed on an over-funded closing. Every authored closing funding
    and fee -- of every claim-bearing position, whatever its later settlement
    -- is applied in economic order to the root's pre-structured-capital
    closing flow, exactly as the residual will apply it. Above
    ``OVERFUNDED_CLOSING_TOLERANCE`` there is no ratified destination for the
    excess, so the structure is refused; nothing is resized or rounded."""

    if not scheduled:
        return
    closing = [closing_source]
    for position in scheduled:
        _apply_closing(closing, position)
    if closing[0] > OVERFUNDED_CLOSING_TOLERANCE:
        raise CapitalStructureExecutionError(
            (
                ExecutionIssue(
                    code=ExecutionIssueCode.OVERFUNDED_CLOSING,
                    message=(
                        f"Authored capital exceeds the {root} closing funding requirement by {closing[0]:,.2f}. "
                        "P7.8 does not infer a cash reserve, closing distribution or recapitalization for excess "
                        "proceeds."
                    ),
                    field="funding",
                ),
            )
        )


def _settle_position(
    scheduled: ScheduledPosition, *, residual: list[float], hold_period: int
) -> tuple[PositionAnnualClaim, ...]:
    """Settle one position against ``residual``, the cash its scope has left
    after every senior position, and leave in ``residual`` what remains for the
    next. One annual claim per hold year with a contractual receipt.

    Settlement stops at the position's first unresolved claim, which is kept.
    No arrears, default or capitalization convention exists, so a later year
    cannot be settled honestly: its events stay in the schedule, and no later
    claim or Funding Requirement is produced."""

    position = scheduled.position
    resolution = position.shortfall_resolution
    if resolution is None:
        raise CapitalStructureError(f"{position.position_id!r} states no shortfall resolution.")
    _apply_closing(residual, scheduled)
    claims: list[PositionAnnualClaim] = []
    for year in range(1, hold_period + 1):
        components = tuple(
            event
            for event in scheduled.events
            if event.model_month != 0 and annual_period_of_model_month(event.model_month) == year
        )
        if not components:
            continue
        claim_due = 0.0
        for event in components:
            claim_due = claim_due + event.amount
        available = residual[year]
        settlement = settle_claim(
            ContractualClaim(
                position_id=position.position_id,
                scope=position.scope,
                period=HoldYearPeriod(hold_year=year),
                claim_due=ensure_finite(f"claim[{position.position_id}][{year}]", claim_due),
                cash_available=available if available > 0.0 else 0.0,
                shortfall_resolution=resolution,
            )
        )
        residual[year] = residual[year] - settlement.claim_paid
        claims.append(
            PositionAnnualClaim(
                position_id=position.position_id,
                hold_year=year,
                claim_due=claim_due,
                component_event_ids=tuple(event.event_id for event in components),
                settlement=settlement,
            )
        )
        requirement = settlement.funding_requirement
        if requirement is not None and requirement.status is FundingRequirementStatus.UNRESOLVED:
            break
    return tuple(claims)


def _apply_settled(residual: list[float], scheduled: ScheduledPosition, claims: tuple[PositionAnnualClaim, ...]) -> None:
    """A settled Unit position's effect on the Investment residual: the same
    closing flows and the same paid claims, applied once."""

    _apply_closing(residual, scheduled)
    for claim in claims:
        residual[claim.hold_year] = residual[claim.hold_year] - claim.settlement.claim_paid


def _requirements(claims: tuple[PositionAnnualClaim, ...] | None) -> tuple[FundingRequirement, ...]:
    found: list[FundingRequirement] = []
    for claim in claims or ():
        requirement = claim.settlement.funding_requirement
        if requirement is not None:
            found.append(requirement)
    return tuple(found)


def _settle_scope(
    scheduled: tuple[ScheduledPosition, ...], *, residual: list[float], hold_period: int, blocking: tuple[str, ...]
) -> tuple[dict[str, _Settled], tuple[str, ...]]:
    """Settle one scope's positions in priority order. ``blocking`` names the
    unresolved requirements every position here depends on; once a position is
    unresolved, it blocks every position junior to it. Returns each position's
    settlement and the requirements that block whatever follows the scope."""

    settled: dict[str, _Settled] = {}
    for position in scheduled:
        if blocking:
            settled[position.position.position_id] = (None, blocking)
            continue
        claims = _settle_position(position, residual=residual, hold_period=hold_period)
        unresolved = tuple(
            requirement.requirement_id
            for requirement in _requirements(claims)
            if requirement.status is FundingRequirementStatus.UNRESOLVED
        )
        settled[position.position.position_id] = (claims, unresolved)
        blocking = unresolved
    return settled, blocking


def _finite(series: list[float]) -> tuple[float, ...]:
    return tuple(ensure_finite(f"common_equity_cash_flows[{period}]", value) for period, value in enumerate(series))


# =============================================================================
# Structure: attachment, detachment and cumulative service
# =============================================================================


def _layers(
    scheduled: tuple[ScheduledPosition, ...],
    *,
    senior_capital: float,
    senior_service: tuple[float, ...],
    hold_period: int,
) -> tuple[dict[str, _Layer], float, tuple[float, ...]]:
    """Each position's layer, in priority order above ``senior_capital`` (the
    funded capital structurally senior to the first) and ``senior_service``
    (the current cash service senior to it); and the totals after the last."""

    layers: dict[str, _Layer] = {}
    capital, service = senior_capital, senior_service
    for position in scheduled:
        attachment = capital
        capital = ensure_finite("detachment_basis", attachment + position.funded_amount)
        own = annual_current_cash_service(position.events, hold_period=hold_period)
        service = tuple(
            ensure_finite(f"cumulative_service[{year}]", total + mine)
            for year, (total, mine) in enumerate(zip(service, own, strict=True), start=1)
        )
        layers[position.position.position_id] = (attachment, capital, service)
    return layers, capital, service


# =============================================================================
# Results
# =============================================================================


def _position_returns(
    scheduled: ScheduledPosition,
    *,
    settled: _Settled,
    layer: _Layer,
    noi_by_year: tuple[float, ...],
    hold_period: int,
) -> PositionReturns:
    position = scheduled.position
    claims, requirement_ids = settled
    attachment, detachment, service = layer
    coverage_by_year, headline, minimum = coverage_through(
        noi_by_year=noi_by_year,
        cumulative_service_by_year=service,
        outstanding_years=annual_period_of_model_month(scheduled.modeled_payoff_month),
    )

    annual: tuple[float, ...] | None = None
    irr = irr_status = received = moic = profit = None
    reason: PositionUnavailableReason | None = None
    message: str | None = None
    if claims is None:
        status = PositionResultStatus.BLOCKED_BY_SENIOR_UNRESOLVED
        reason = PositionUnavailableReason.SENIOR_UNRESOLVED_FUNDING_REQUIREMENT
        message = (
            f"The returns of {position.position_id} are not reported: senior Funding Requirement(s) "
            f"{', '.join(requirement_ids)} are unresolved, so the cash available to it is unknown and nothing was "
            "settled for it. Property, Business Plan and project results are unaffected."
        )
    elif requirement_ids:
        status = PositionResultStatus.UNRESOLVED_FUNDING
        reason = PositionUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
        message = (
            f"The returns of {position.position_id} are not reported: its Funding Requirement(s) "
            f"{', '.join(requirement_ids)} are unresolved, so the cash it receives is incomplete. Property, Business "
            "Plan and project results are unaffected."
        )
    else:
        status = PositionResultStatus.COMPLETE
        annual = annual_position_cash_flows(scheduled.events, hold_period=hold_period)
        irr, irr_status = position_irr(annual)
        received, moic, profit = position_receipts(scheduled.events, funded_amount=scheduled.funded_amount)

    return PositionReturns(
        position_id=position.position_id,
        name=position.name,
        position_class=position.position_class,
        scope=position.scope,
        priority=position.priority,
        status=status,
        unavailable_reason=reason,
        unavailable_message=message,
        blocking_requirement_ids=requirement_ids,
        funding=scheduled.funding,
        funded_amount=scheduled.funded_amount,
        debt_schedule=scheduled.debt_schedule,
        preferred_schedule=scheduled.preferred_schedule,
        modeled_payoff_month=scheduled.modeled_payoff_month,
        balance_at_maturity_or_exit=scheduled.balance_at_maturity_or_exit,
        cash_flow_events=scheduled.events,
        annual_claims=() if claims is None else claims,
        funding_requirements=_requirements(claims),
        annual_cash_flows=annual,
        irr=irr,
        irr_status=irr_status,
        total_cash_received=received,
        moic=moic,
        profit=profit,
        valuation_basis=scheduled.price_basis,
        attachment_basis=attachment,
        detachment_basis=detachment,
        last_dollar_basis=detachment,
        attachment_ltv=loan_to_price(attachment, scheduled.price_basis),
        detachment_ltv=loan_to_price(detachment, scheduled.price_basis),
        debt_yield_through=debt_yield_through(year_1_noi=noi_by_year[0], last_dollar_basis=detachment),
        coverage_by_year=coverage_by_year,
        headline_coverage=headline,
        minimum_coverage=minimum,
    )


def _common_equity(
    *,
    marker: CapitalPosition | None,
    root_scope: PositionScope,
    requirements: tuple[FundingRequirement, ...],
    residual: tuple[float, ...],
) -> CommonEquityReturns:
    outcome = common_equity_outcome(funding_requirements=requirements, residual_cash_flows=residual)
    cash_flows = outcome.common_equity_cash_flows
    irr = irr_status = equity_multiple = invested = returned = profit = None
    if cash_flows is not None:
        irr, irr_status, equity_multiple, invested, returned, profit = common_equity_metrics(cash_flows)
    return CommonEquityReturns(
        position_id=None if marker is None else marker.position_id,
        scope=root_scope if marker is None else marker.scope,
        status=outcome.status,
        cash_flows=cash_flows,
        unavailable_reason=outcome.unavailable_reason,
        unavailable_message=outcome.unavailable_message,
        irr=irr,
        irr_status=irr_status,
        equity_multiple=equity_multiple,
        total_equity_invested=invested,
        total_cash_returned=returned,
        total_profit=profit,
    )


# =============================================================================
# The executors
# =============================================================================


def execute_unit_capital_structure(
    *,
    unit_id: str,
    terms: AcquisitionTerms,
    results: AcquisitionResults,
    capital_structure: CapitalStructure | None = None,
) -> StructuredCapitalResult:
    """The structured Capital Structure economics of one standalone Unit.

    ``terms`` and ``results`` are its resolved ``AcquisitionTerms`` and its
    completed ``AcquisitionResults``; nothing upstream is re-run or changed.
    ``capital_structure`` holds its authored positions, all Unit-scoped;
    ``None`` and the empty structure mean none, and the Common Equity Cash Flow
    is then ``results.levered_cash_flows`` itself."""

    foundation = analyze_unit_capital_structure(unit_id=unit_id, terms=terms, results=results)
    loan = foundation.legacy_acquisition_loan
    hold_period = terms.hold_period
    positions = _executable_positions(
        capital_structure,
        member_unit_ids=(unit_id,),
        acquisition_loan_unit_ids=() if loan is None else (unit_id,),
        analysis_scope=ScopeKind.UNIT,
        hold_period=hold_period,
    )
    marker, claim_bearing = _split(positions)
    basis = unit_price_basis(terms)
    scheduled = tuple(schedule_position(position, price_basis=basis, hold_period=hold_period) for position in claim_bearing)

    source = foundation.cash_authority.post_acquisition_debt_cash_flows
    _require_funded_closing(scheduled, closing_source=source[0], root="Unit")
    residual = list(source)
    settled, _ = _settle_scope(scheduled, residual=residual, hold_period=hold_period, blocking=())
    layers, _, _ = _layers(
        scheduled, senior_capital=results.loan_amount, senior_service=results.annual_debt_service, hold_period=hold_period
    )
    positions_returns = tuple(
        _position_returns(
            position,
            settled=settled[position.position.position_id],
            layer=layers[position.position.position_id],
            noi_by_year=results.noi_by_year,
            hold_period=hold_period,
        )
        for position in scheduled
    )
    requirements = (
        *foundation.funding_requirements,
        *(requirement for returns in positions_returns for requirement in returns.funding_requirements),
    )
    common_equity = _common_equity(
        marker=marker,
        root_scope=PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id),
        requirements=requirements,
        residual=_finite(residual) if scheduled else source,
    )
    return StructuredCapitalResult(
        analysis_scope=ScopeKind.UNIT,
        unit_ids=(unit_id,),
        hold_period=hold_period,
        status=common_equity.status,
        legacy_acquisition_loans=() if loan is None else (loan,),
        positions=positions_returns,
        funding_requirements=requirements,
        common_equity=common_equity,
    )


def execute_investment_capital_structure(
    *,
    units: Iterable[CapitalStructureUnit],
    consolidated: ConsolidatedResults,
    capital_structure: CapitalStructure | None = None,
) -> StructuredCapitalResult:
    """The structured Capital Structure economics of a visible Investment.

    ``units`` are its Units' resolved terms and completed results and
    ``consolidated`` their completed consolidation; P7.6 is never
    reconstructed. Every Unit scope clears against its own Unit's cash first;
    the Investment scope then reads the consolidated residual those Unit
    positions leave. ``None`` and the empty structure mean no authored
    position, and the Common Equity Cash Flow is then
    ``consolidated.levered_cash_flows`` itself."""

    given = tuple(units)
    foundation = analyze_investment_capital_structure(units=given, consolidated=consolidated)
    ordered = tuple(sorted(given, key=lambda unit: unit.unit_id))
    hold_period = consolidated.hold_period
    positions = _executable_positions(
        capital_structure,
        member_unit_ids=consolidated.unit_ids,
        acquisition_loan_unit_ids=tuple(
            loan.scope.unit_id for loan in foundation.legacy_acquisition_loans if loan.scope.unit_id is not None
        ),
        analysis_scope=ScopeKind.INVESTMENT,
        hold_period=hold_period,
    )
    marker, claim_bearing = _split(positions)
    by_unit = {unit.unit_id: unit for unit in ordered}
    investment_basis = investment_price_basis(consolidated)
    scheduled = tuple(
        schedule_position(
            position,
            price_basis=unit_price_basis(by_unit[_unit_id(position)].terms)
            if position.scope.kind is ScopeKind.UNIT
            else investment_basis,
            hold_period=hold_period,
        )
        for position in claim_bearing
    )
    unit_scheduled = tuple(position for position in scheduled if position.position.scope.kind is ScopeKind.UNIT)
    investment_scheduled = tuple(
        position for position in scheduled if position.position.scope.kind is ScopeKind.INVESTMENT
    )

    source = foundation.investment_cash_authority.cash_flows_after_unit_positions
    _require_funded_closing(scheduled, closing_source=source[0], root="Investment")
    investment_residual = list(source)
    settled: dict[str, _Settled] = {}
    layers: dict[str, _Layer] = {}
    unit_blocking: list[str] = []
    for unit in ordered:
        in_unit = tuple(position for position in unit_scheduled if _unit_id(position.position) == unit.unit_id)
        if not in_unit:
            continue
        unit_residual = list(unit.results.levered_cash_flows)
        unit_settled, unresolved = _settle_scope(in_unit, residual=unit_residual, hold_period=hold_period, blocking=())
        settled.update(unit_settled)
        unit_blocking.extend(unresolved)
        for position in in_unit:
            claims, _ = unit_settled[position.position.position_id]
            if claims is not None:
                _apply_settled(investment_residual, position, claims)
        unit_layers, _, _ = _layers(
            in_unit,
            senior_capital=unit.results.loan_amount,
            senior_service=unit.results.annual_debt_service,
            hold_period=hold_period,
        )
        layers.update(unit_layers)

    investment_settled, _ = _settle_scope(
        investment_scheduled, residual=investment_residual, hold_period=hold_period, blocking=tuple(unit_blocking)
    )
    settled.update(investment_settled)
    _, senior_capital, senior_service = _layers(
        unit_scheduled,
        senior_capital=consolidated.loan_amount,
        senior_service=consolidated.annual_debt_service,
        hold_period=hold_period,
    )
    investment_layers, _, _ = _layers(
        investment_scheduled, senior_capital=senior_capital, senior_service=senior_service, hold_period=hold_period
    )
    layers.update(investment_layers)

    positions_returns = tuple(
        _position_returns(
            position,
            settled=settled[position.position.position_id],
            layer=layers[position.position.position_id],
            noi_by_year=by_unit[_unit_id(position.position)].results.noi_by_year
            if position.position.scope.kind is ScopeKind.UNIT
            else consolidated.noi_by_year,
            hold_period=hold_period,
        )
        for position in scheduled
    )
    requirements = (
        *foundation.funding_requirements,
        *(requirement for returns in positions_returns for requirement in returns.funding_requirements),
    )
    common_equity = _common_equity(
        marker=marker,
        root_scope=PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None),
        requirements=requirements,
        residual=_finite(investment_residual) if scheduled else source,
    )
    return StructuredCapitalResult(
        analysis_scope=ScopeKind.INVESTMENT,
        unit_ids=consolidated.unit_ids,
        hold_period=hold_period,
        status=common_equity.status,
        legacy_acquisition_loans=foundation.legacy_acquisition_loans,
        positions=positions_returns,
        funding_requirements=requirements,
        common_equity=common_equity,
    )
