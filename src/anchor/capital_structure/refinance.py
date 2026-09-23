"""Refinance & Capital Events V1 -- planning one refinance for one variant.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 7 to
11 (ratified); that document governs on any discrepancy.

``plan_refinance`` answers, for one well-formed event and one resolved variant,
everything the executor needs before any cash is settled:

- **Horizon.** ``m >= 12H`` is ``event_outside_hold_horizon``.
- **Retirement.** Each retiring position's scheduled payment at ``m`` and its
  payoff immediately after it. An authored position's comes from its own
  accepted P7.8 schedule, run to the event (``schedule_position`` with the
  event year as its horizon, so its modeled payoff *is* month ``m``). The
  acquisition loan's comes from the engine's acquisition-debt balance service
  (R-M), reconciled bit for bit to ``AcquisitionResults``. No amortization
  recurrence exists here.
- **Continuing senior debt** of the same scope (R-D): its balance after its
  month-``m`` payment and its scheduled service in months ``m+1 .. m+12``,
  balloons excluded.
- **Dependencies, kept apart (R-C).** LTV reads only the referenced P7.10 cell
  for the exact scope and month. DSCR reads only the variant's forward NOI,
  through P7.10's own ``forward_noi_at`` over the variant's resolved Unit
  inputs; the Investment's is the canonical Unit sum, reconciled bit for bit to
  the consolidated NOI. Neither falls back to the other, to the purchase price,
  to another month or to another scope.
- **Sizing (R-D).** ``C_FIXED = cap``; ``C_LTV = max_ltv x V - B_sen``;
  ``C_DSCR = (NOI_f / min_dscr - DS_sen) / s_1``, where ``s_1`` is the
  replacement's first twelve months of scheduled service per dollar from the
  P7.8 debt wrapper. ``G`` is the exact minimum over every enabled capacity;
  any unavailable capacity makes the event unavailable, and a non-positive
  minimum makes it not executable. The old loan is never kept silently.
- **Replacement (R-G).** An ordinary debt schedule of ``G``, offset to the
  event month: funded at ``m``, first service at ``m + 1``, modeled payoff
  ``min(maturity, 12H, m + io_months + n_payments)``.
- **Bridge (R-F).** ``N = G - payoffs - replacement lender fees - retiring
  lender fees - third-party costs``.

Nothing here settles a claim or touches a residual; the executor does that.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..contracts import AcquisitionTerms
from ..consolidation.contracts import ConsolidatedResults
from ..engine.acquisition_debt_balance import (
    AcquisitionDebtBalanceReconciliationError,
    AcquisitionLoanBalance,
    acquisition_loan_balance_after_month,
)
from ..engine.contracts import AcquisitionResults, ensure_finite
from ..valuation.contracts import (
    ValuationAvailability,
    ValuationError,
    ValuationMethodKind,
)
from ..valuation.engine import forward_noi_at, unit_inputs
from ..valuation.funding import ValuationAuthority
from .contracts import (
    LEGACY_ACQUISITION_LOAN_PRIORITY,
    MONTHS_PER_HOLD_YEAR,
    CapitalPosition,
    CapitalStructureError,
    CapitalStructureUnit,
    DebtTerms,
    FundingEvent,
    LegacyAcquisitionLoan,
    PositionClass,
    PositionScope,
    ScopeKind,
)
from .debt_position import schedule_debt_position
from .events import (
    AuthoredPositionRef,
    LegacyAcquisitionLoanRef,
    RefinanceCostKind,
    RefinanceEvent,
    RetiringPositionRef,
)
from .execution import schedule_position
from .execution_contracts import (
    CapitalStructureExecutionError,
    ExecutionIssue,
    ExecutionIssueCode,
    PositionCashFlowEvent,
    PositionCashFlowKind,
    PriceBasis,
    ResolvedFundingEvent,
    ScheduledPosition,
)
from .metrics import event_order_key
from .refinance_contracts import (
    ACHIEVED_DSCR_RELATIVE_TOLERANCE,
    BINDING_TIE_RELATIVE_TOLERANCE,
    BridgeDirection,
    ConstraintAvailability,
    ConstraintCapacity,
    ConstraintKind,
    FixedCapOperands,
    MaxLtvOperands,
    MinDscrOperands,
    NoiDependency,
    PayoffAuthority,
    RefinanceBridge,
    RefinanceResult,
    RefinanceStatus,
    RefinanceUnavailableReason,
    ReplacementFunding,
    RetiringPayoff,
    SizingOutcome,
    ValueDependency,
)

_DEBT_CLASSES = frozenset({PositionClass.SENIOR_DEBT, PositionClass.MEZZANINE_DEBT})

#: Within the event month, the scheduled payment precedes the payoff (P7.8's
#: own payment-then-balloon order), and the funding precedes its fees.
PAYOFF_SEQUENCE = 2


# =============================================================================
# The authorities a plan reads
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitRefinanceAuthority:
    """One Unit's resolved terms, completed results and adapted acquisition
    loan (``None`` when it carries none)."""

    unit_id: str
    terms: AcquisitionTerms
    results: AcquisitionResults
    legacy_loan: LegacyAcquisitionLoan | None


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentRefinanceAuthority:
    """The Investment's Units, in canonical order, and their consolidation."""

    units: tuple[CapitalStructureUnit, ...]
    consolidated: ConsolidatedResults


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinancePlan:
    """Everything one event means for one variant, before settlement.

    ``replacement_view`` and ``retiring_views`` are the reporting schedules of
    the replacement and of each authored retiring position, and exist only when
    the event executes. ``affected_position_ids`` are the positions whose cash
    after the event depends on it: every retiring authored position, the
    replacement, and every position ranked at or below the replacement in the
    scope."""

    event: RefinanceEvent
    result: RefinanceResult
    replacement_view: ScheduledPosition | None
    retiring_views: tuple[ScheduledPosition, ...]
    retired_legacy_unit_id: str | None
    continuing_senior_balance: float
    affected_position_ids: frozenset[str]

    @property
    def executed(self) -> bool:
        return self.result.status is RefinanceStatus.EXECUTED

    @property
    def net_event_cash(self) -> float:
        bridge = self.result.bridge
        if bridge is None:
            raise ValueError(f"Event {self.event.event_id!r} did not execute; it has no net event cash.")
        return bridge.net_event_cash


# =============================================================================
# Small helpers
# =============================================================================


def event_month(event: RefinanceEvent) -> int:
    return event.timing.model_month


def event_hold_year(event: RefinanceEvent) -> int:
    return event_month(event) // MONTHS_PER_HOLD_YEAR


def _refuse(code: ExecutionIssueCode, message: str, *, field: str | None = None) -> CapitalStructureExecutionError:
    return CapitalStructureExecutionError((ExecutionIssue(code=code, message=message, field=field),))


def _ref_matches(recipient: RetiringPositionRef | None, ref: RetiringPositionRef) -> bool:
    return recipient == ref


def _retiring_lender_fees(event: RefinanceEvent, ref: RetiringPositionRef) -> tuple[tuple[str, int, float], ...]:
    """``(cost_id, sequence, amount)`` of each fee paid to ``ref``, by id."""

    lines = sorted(
        (line for line in event.costs if line.kind is RefinanceCostKind.RETIRING_LENDER_FEE and _ref_matches(line.recipient, ref)),
        key=lambda line: line.cost_id,
    )
    return tuple((line.cost_id, index, ensure_finite(f"cost[{line.cost_id}]", float(line.amount))) for index, line in enumerate(lines, start=1))


def _total(amounts: list[float], field: str) -> float:
    total = 0.0
    for amount in amounts:
        total = total + amount
    return ensure_finite(field, total)


def legacy_balance(authority: UnitRefinanceAuthority, *, model_month: int) -> AcquisitionLoanBalance:
    """The acquisition loan's balance after month ``model_month``, from the
    engine's balance service. A reconciliation failure is an engine defect and
    is refused with its typed code, never tolerated."""

    try:
        return acquisition_loan_balance_after_month(
            terms=authority.terms, results=authority.results, model_month=model_month
        )
    except AcquisitionDebtBalanceReconciliationError as error:
        raise _refuse(
            ExecutionIssueCode.LEGACY_PAYOFF_RECONCILIATION_FAILURE,
            f"The acquisition loan of Unit {authority.unit_id!r} cannot be retired: {error}",
            field="retiring",
        ) from error


# =============================================================================
# Schedules
# =============================================================================


def replacement_schedule(
    position: CapitalPosition,
    *,
    principal: float,
    model_month: int,
    hold_period: int,
    price_basis: PriceBasis,
) -> ScheduledPosition:
    """The replacement's reporting schedule: funded ``principal`` at
    ``model_month``, its lender fees there, then the unchanged P7.8 debt
    schedule offset to that month. The wrapper is asked for the schedule of a
    loan funded at ``0`` whose maturity and horizon are measured from the event;
    every month it returns is then moved by ``model_month``. No debt formula is
    restated."""

    terms = position.terms
    if not isinstance(terms, DebtTerms):
        raise ValueError(f"Replacement {position.position_id!r} is not debt.")
    funding = position.funding[0]
    if not isinstance(funding, FundingEvent):
        raise ValueError(f"Replacement {position.position_id!r} has no funding event.")
    relative_terms = replace(terms, maturity_month=terms.maturity_month - model_month, fees=())
    relative, contractual = schedule_debt_position(
        position_id=position.position_id,
        principal=principal,
        terms=relative_terms,
        hold_period=hold_period - model_month // MONTHS_PER_HOLD_YEAR,
    )
    schedule = replace(
        relative,
        maturity_month=terms.maturity_month,
        scheduled_full_amortization_month=relative.scheduled_full_amortization_month + model_month,
        modeled_payoff_month=relative.modeled_payoff_month + model_month,
    )
    moved = tuple(
        replace(
            item,
            model_month=item.model_month + model_month,
            event_id=f"{position.position_id}:{item.kind.value}:{item.model_month + model_month}",
        )
        for item in contractual
    )
    funded = PositionCashFlowEvent(
        event_id=funding.event_id,
        position_id=position.position_id,
        model_month=model_month,
        sequence=funding.sequence,
        kind=PositionCashFlowKind.REFINANCE_FUNDING,
        amount=-principal,
    )
    fees = tuple(
        PositionCashFlowEvent(
            event_id=fee.fee_id,
            position_id=position.position_id,
            model_month=fee.model_month,
            sequence=fee.sequence,
            kind=PositionCashFlowKind.FEE,
            amount=ensure_finite(f"fee[{fee.fee_id}]", float(fee.amount)),
        )
        for fee in terms.fees
    )
    return ScheduledPosition(
        position=position,
        price_basis=price_basis,
        funding=(
            ResolvedFundingEvent(
                event_id=funding.event_id,
                model_month=model_month,
                sequence=funding.sequence,
                amount_rule=funding.amount_rule,
                price_basis=None,
                amount=principal,
            ),
        ),
        funded_amount=principal,
        events=tuple(sorted((funded, *fees, *moved), key=event_order_key)),
        debt_schedule=schedule,
        preferred_schedule=None,
        modeled_payoff_month=schedule.modeled_payoff_month,
        balance_at_maturity_or_exit=schedule.balance_at_payoff,
    )


def first_year_service(view: ScheduledPosition, *, model_month: int) -> float:
    """The scheduled service of months ``model_month + 1 .. model_month + 12``,
    balloons excluded (the P7.8 coverage convention)."""

    return _total(
        [
            item.amount
            for item in sorted(view.events, key=event_order_key)
            if item.kind is PositionCashFlowKind.SCHEDULED_DEBT_SERVICE
            and model_month < item.model_month <= model_month + MONTHS_PER_HOLD_YEAR
        ],
        "first_year_service",
    )


def _payment_at(view: ScheduledPosition, *, model_month: int) -> float:
    return _total(
        [
            item.amount
            for item in view.events
            if item.kind is PositionCashFlowKind.SCHEDULED_DEBT_SERVICE and item.model_month == model_month
        ],
        "scheduled_payment_at_event",
    )


def _retiring_view(
    view: ScheduledPosition, *, event: RefinanceEvent, ref: AuthoredPositionRef, model_month: int
) -> ScheduledPosition:
    """An authored retiring position's reporting schedule: its accepted
    schedule to the event, the balloon at ``m`` restated as the event's
    ``REFINANCE_PAYOFF``, and any retiring lender fee received at ``m``."""

    position_id = view.position.position_id
    kept = [item for item in view.events if item.kind is not PositionCashFlowKind.BALLOON]
    payoff = PositionCashFlowEvent(
        event_id=f"{position_id}:{PositionCashFlowKind.REFINANCE_PAYOFF.value}:{model_month}",
        position_id=position_id,
        model_month=model_month,
        sequence=PAYOFF_SEQUENCE,
        kind=PositionCashFlowKind.REFINANCE_PAYOFF,
        amount=view.balance_at_maturity_or_exit,
    )
    fees = [
        PositionCashFlowEvent(
            event_id=cost_id,
            position_id=position_id,
            model_month=model_month,
            sequence=PAYOFF_SEQUENCE + sequence,
            kind=PositionCashFlowKind.FEE,
            amount=amount,
        )
        for cost_id, sequence, amount in _retiring_lender_fees(event, ref)
    ]
    return replace(view, events=tuple(sorted((*kept, payoff, *fees), key=event_order_key)))


# =============================================================================
# Dependencies
# =============================================================================


def _unit_forward_noi(unit: CapitalStructureUnit | UnitRefinanceAuthority, *, model_month: int) -> float:
    return forward_noi_at(unit_inputs(unit_id=unit.unit_id, terms=unit.terms, results=unit.results), model_month=model_month)


def _mismatch(message: str) -> CapitalStructureExecutionError:
    return _refuse(ExecutionIssueCode.FORWARD_NOI_AUTHORITY_MISMATCH, message, field="sizing.min_dscr")


def forward_noi(
    scope: PositionScope,
    *,
    model_month: int,
    unit: UnitRefinanceAuthority | None,
    investment: InvestmentRefinanceAuthority | None,
) -> float | None:
    """The scope's forward NOI at ``model_month`` from the shared NOI-at-month
    authority, or ``None`` only when the scope's authority is absent. The
    Investment's is the canonical Unit sum, reconciled bit for bit to the
    consolidated NOI.

    A present authority that cannot answer -- a month that is not a valuation
    timepoint of its hold, or an NOI series that does not span it -- is a
    programming error. P7.10's ``ValuationError`` propagates: it is never read
    as an unavailable forward NOI. A non-positive NOI is a value, not an
    absence; the caller reports it as ``non_positive_forward_noi``."""

    if scope.kind is ScopeKind.UNIT:
        if unit is None:
            return None
        return _unit_forward_noi(unit, model_month=model_month)
    if investment is None or not investment.units:
        return None
    values = [_unit_forward_noi(member, model_month=model_month) for member in investment.units]
    total = values[0]
    for value in values[1:]:
        total = total + value
    total = ensure_finite("investment_forward_noi", total)
    index = model_month // MONTHS_PER_HOLD_YEAR
    series = investment.consolidated.noi_by_year
    if index >= len(series):
        raise ValuationError(
            f"The consolidated results report {len(series)} NOI years, with no forward NOI at model month "
            f"{model_month}; they do not span the hold."
        )
    consolidated = series[index]
    if total != consolidated:
        raise _mismatch(
            f"The Investment's forward NOI at model month {model_month} sums to {total!r} over its Units, but the "
            f"consolidated NOI is {consolidated!r}. The NOI authority disagrees with itself; nothing is sized."
        )
    return total


def _value_dependency(
    event: RefinanceEvent,
    *,
    valuations: ValuationAuthority | None,
    model_month: int,
    unit: UnitRefinanceAuthority | None,
    investment: InvestmentRefinanceAuthority | None,
) -> tuple[ValueDependency | None, RefinanceUnavailableReason | None, str | None]:
    """The referenced cell for the exact scope and month, or why none is
    usable. No other timepoint, scope or basis is ever consulted."""

    reference = event.valuation
    if reference is None:
        raise ValueError(f"Event {event.event_id!r} enables LTV without a valuation reference.")
    found = None if valuations is None else valuations.find(reference.timepoint_id)
    if found is None:
        return (
            None,
            RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND,
            f"'{event.label}' sizes by LTV, but its valuation timepoint does not exist for this analysis.",
        )
    if found.model_month != model_month:
        return (
            None,
            RefinanceUnavailableReason.MODEL_MONTH_MISMATCH,
            f"'{event.label}' is at model month {model_month}, but the valuation '{found.label}' is at model month "
            f"{found.model_month}. A value from another date is never used.",
        )
    if event.scope.kind is ScopeKind.UNIT:
        cell = next((result for result in found.unit_results if result.unit_id == event.scope.unit_id), None)
        if cell is None:
            return (
                None,
                RefinanceUnavailableReason.SCOPE_NOT_COVERED,
                f"The valuation '{found.label}' has no value for this Unit, so '{event.label}' cannot size by LTV.",
            )
        dependency = ValueDependency(
            timepoint_id=found.timepoint_id,
            scope=event.scope,
            model_month=model_month,
            method=cell.method_kind,
            analyst_supplied=cell.analyst_supplied,
            status=cell.status,
            value=cell.value,
            valuation_unavailable_reason=cell.unavailable_reason,
        )
        if cell.status is ValuationAvailability.AVAILABLE and cell.method_kind is ValuationMethodKind.DIRECT_CAP:
            _reconcile_direct_cap(cell.forward_noi, unit, model_month=model_month, label=found.label)
    else:
        dependency = ValueDependency(
            timepoint_id=found.timepoint_id,
            scope=event.scope,
            model_month=model_month,
            method=None,
            analyst_supplied=None,
            status=found.status,
            value=found.value,
            valuation_unavailable_reason=found.unavailable_reason,
        )
        if investment is not None:
            members = {member.unit_id: member for member in investment.units}
            for cell in found.unit_results:
                if (
                    cell.status is ValuationAvailability.AVAILABLE
                    and cell.method_kind is ValuationMethodKind.DIRECT_CAP
                    and cell.unit_id in members
                ):
                    _reconcile_direct_cap(cell.forward_noi, members[cell.unit_id], model_month=model_month, label=found.label)
    if dependency.status is not ValuationAvailability.AVAILABLE or dependency.value is None:
        reason = dependency.valuation_unavailable_reason
        detail = "" if reason is None else f" ({reason.value})"
        return (
            dependency,
            RefinanceUnavailableReason.VALUATION_UNAVAILABLE,
            f"The valuation '{found.label}' has no value for this scope{detail}, so '{event.label}' cannot size by "
            "LTV. It is never read as zero or replaced by the purchase price.",
        )
    return dependency, None, None


def _reconcile_direct_cap(
    recorded: float | None,
    unit: CapitalStructureUnit | UnitRefinanceAuthority | None,
    *,
    model_month: int,
    label: str,
) -> None:
    """A direct-cap cell's recorded forward NOI must equal the shared NOI
    authority's, bit for bit. The cell is never the NOI source."""

    if unit is None or recorded is None:
        return
    authority = _unit_forward_noi(unit, model_month=model_month)
    if recorded != authority:
        raise _mismatch(
            f"The direct-cap valuation '{label}' records forward NOI {recorded!r} for Unit {unit.unit_id!r}, but the "
            f"variant's NOI authority gives {authority!r}. The NOI authority disagrees with itself; nothing is sized."
        )


# =============================================================================
# The plan
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class _Retirement:
    payoffs: tuple[RetiringPayoff, ...]
    views: tuple[ScheduledPosition, ...]
    legacy_unit_id: str | None
    reason: RefinanceUnavailableReason | None
    message: str | None


def _legacy_provider_cash_flows(
    loan: LegacyAcquisitionLoan, *, hold_year: int, payoff: float, fees: float
) -> tuple[float, ...]:
    """The retired acquisition loan's provider series ``t = 0..H``, read from
    its adapted figures: closing funding and fee, service through the event
    year, and the payoff and any exit fee in the event year."""

    series = [0.0 for _ in range(loan.hold_period + 1)]
    series[0] = ensure_finite("legacy_provider[0]", -loan.loan_amount + loan.financing_fee.amount)
    for year in range(1, hold_year + 1):
        series[year] = loan.annual_debt_service[year - 1]
    series[hold_year] = ensure_finite(f"legacy_provider[{hold_year}]", series[hold_year] + payoff + fees)
    return tuple(series)


def _retire(
    event: RefinanceEvent,
    *,
    positions: dict[str, CapitalPosition],
    price_basis: PriceBasis,
    valuations: ValuationAuthority | None,
    unit: UnitRefinanceAuthority | None,
) -> _Retirement:
    model_month = event_month(event)
    hold_year = event_hold_year(event)
    payoffs: list[RetiringPayoff] = []
    views: list[ScheduledPosition] = []
    legacy_unit: str | None = None
    for ref in sorted(event.retiring, key=lambda ref: (type(ref).__name__, str(getattr(ref, "position_id", getattr(ref, "unit_id", ""))))):
        fees = _total([amount for _, _, amount in _retiring_lender_fees(event, ref)], "retiring_lender_fees")
        if isinstance(ref, LegacyAcquisitionLoanRef):
            loan = None if unit is None else unit.legacy_loan
            if unit is None or loan is None:
                return _Retirement(
                    payoffs=(),
                    views=(),
                    legacy_unit_id=None,
                    reason=RefinanceUnavailableReason.RETIRING_POSITION_ABSENT,
                    message=f"'{event.label}' retires this Unit's acquisition loan, which this variant does not carry.",
                )
            balance = legacy_balance(unit, model_month=model_month)
            if balance.balance_after_month <= 0.0:
                return _Retirement(
                    payoffs=(),
                    views=(),
                    legacy_unit_id=None,
                    reason=RefinanceUnavailableReason.RETIRING_POSITION_NOT_OUTSTANDING,
                    message=f"'{event.label}' retires the acquisition loan, which is repaid before model month {model_month}.",
                )
            legacy_unit = unit.unit_id
            payoffs.append(
                RetiringPayoff(
                    ref=ref,
                    position_id=loan.position_id,
                    scheduled_payment_at_m=balance.scheduled_payment_at_month,
                    payoff=balance.balance_after_month,
                    payoff_authority=PayoffAuthority.ACQUISITION_DEBT_BALANCE_SERVICE,
                    retiring_lender_fees=fees,
                    provider_cash_flows=_legacy_provider_cash_flows(
                        loan, hold_year=hold_year, payoff=balance.balance_after_month, fees=fees
                    ),
                )
            )
            continue
        position = positions[ref.position_id]
        to_event = schedule_position(position, price_basis=price_basis, hold_period=hold_year, valuations=valuations)
        if to_event.modeled_payoff_month != model_month or to_event.balance_at_maturity_or_exit <= 0.0:
            return _Retirement(
                payoffs=(),
                views=(),
                legacy_unit_id=None,
                reason=RefinanceUnavailableReason.RETIRING_POSITION_NOT_OUTSTANDING,
                message=f"'{event.label}' retires '{position.name}', which is repaid before model month {model_month}.",
            )
        views.append(_retiring_view(to_event, event=event, ref=ref, model_month=model_month))
        payoffs.append(
            RetiringPayoff(
                ref=ref,
                position_id=position.position_id,
                scheduled_payment_at_m=_payment_at(to_event, model_month=model_month),
                payoff=to_event.balance_at_maturity_or_exit,
                payoff_authority=PayoffAuthority.AUTHORED_SCHEDULE,
                retiring_lender_fees=fees,
                provider_cash_flows=None,
            )
        )
    return _Retirement(payoffs=tuple(payoffs), views=tuple(views), legacy_unit_id=legacy_unit, reason=None, message=None)


def _continuing_seniors(
    event: RefinanceEvent,
    *,
    replacement: CapitalPosition,
    scope_positions: tuple[CapitalPosition, ...],
    hold_period: int,
    price_basis: PriceBasis,
    valuations: ValuationAuthority | None,
    unit: UnitRefinanceAuthority | None,
) -> tuple[float, float]:
    """``(B_sen, DS_sen)``: the balance after month ``m`` and the scheduled
    service of months ``m+1 .. m+12`` of every debt position of the scope
    senior to the replacement that the event does not retire."""

    model_month = event_month(event)
    hold_year = event_hold_year(event)
    retired = {ref.position_id for ref in event.retiring if isinstance(ref, AuthoredPositionRef)}
    retires_legacy = any(isinstance(ref, LegacyAcquisitionLoanRef) for ref in event.retiring)
    balances: list[float] = []
    service: list[float] = []
    if unit is not None and unit.legacy_loan is not None and not retires_legacy:
        if replacement.priority <= LEGACY_ACQUISITION_LOAN_PRIORITY:
            # Structural validation refuses this (R-N): priority 1 stays the
            # continuing loan's. Never size as though the loan were not there.
            raise CapitalStructureError(
                f"Engine defect: '{event.label}' places its replacement at priority {replacement.priority}, which "
                "this Unit's continuing acquisition loan holds. Nothing is sized."
            )
        balance = legacy_balance(unit, model_month=model_month)
        balances.append(balance.balance_after_month)
        service.append(unit.results.annual_debt_service[hold_year])
    for position in scope_positions:
        if (
            position.position_class not in _DEBT_CLASSES
            or position.priority >= replacement.priority
            or position.position_id in retired
        ):
            continue
        full = schedule_position(position, price_basis=price_basis, hold_period=hold_period, valuations=valuations)
        if full.modeled_payoff_month <= model_month:
            continue
        to_event = schedule_position(position, price_basis=price_basis, hold_period=hold_year, valuations=valuations)
        balances.append(to_event.balance_at_maturity_or_exit)
        service.append(first_year_service(full, model_month=model_month))
    return _total(balances, "continuing_senior_balance"), _total(service, "continuing_senior_service")


def _unavailable_capacity(
    kind: ConstraintKind, operands: FixedCapOperands | MaxLtvOperands | MinDscrOperands, reason: RefinanceUnavailableReason, message: str
) -> ConstraintCapacity:
    return ConstraintCapacity(
        kind=kind,
        status=ConstraintAvailability.UNAVAILABLE,
        capacity=None,
        operands=operands,
        unavailable_reason=reason,
        unavailable_message=message,
    )


def _available_capacity(kind: ConstraintKind, operands: FixedCapOperands | MaxLtvOperands | MinDscrOperands, capacity: float) -> ConstraintCapacity:
    return ConstraintCapacity(
        kind=kind,
        status=ConstraintAvailability.AVAILABLE,
        capacity=ensure_finite(f"capacity[{kind.value}]", capacity),
        operands=operands,
        unavailable_reason=None,
        unavailable_message=None,
    )


def _sizing(capacities: tuple[ConstraintCapacity, ...]) -> SizingOutcome:
    """The exact minimum of every enabled capacity, and every capacity within
    the tie tolerance of it. ``None`` when any capacity is unavailable or the
    minimum is not positive."""

    known = [capacity.capacity for capacity in capacities if capacity.capacity is not None]
    if len(known) != len(capacities):
        return SizingOutcome(capacities=capacities, gross_proceeds=None, binding=(), tie=False)
    proceeds = min(known)
    if proceeds <= 0.0:
        return SizingOutcome(capacities=capacities, gross_proceeds=None, binding=(), tie=False)
    tolerance = BINDING_TIE_RELATIVE_TOLERANCE * max(1.0, abs(proceeds))
    binding = tuple(
        capacity.kind
        for capacity in capacities
        if capacity.capacity is not None and capacity.capacity - proceeds <= tolerance
    )
    return SizingOutcome(capacities=capacities, gross_proceeds=proceeds, binding=binding, tie=len(binding) > 1)


def _result(
    event: RefinanceEvent,
    *,
    status: RefinanceStatus,
    value: ValueDependency | None = None,
    noi: NoiDependency | None = None,
    sizing: SizingOutcome | None = None,
    payoffs: tuple[RetiringPayoff, ...] | None = None,
    funding: ReplacementFunding | None = None,
    bridge: RefinanceBridge | None = None,
    reason: RefinanceUnavailableReason | None = None,
    message: str | None = None,
) -> RefinanceResult:
    return RefinanceResult(
        event_id=event.event_id,
        kind=event.kind,
        label=event.label,
        scope=event.scope,
        model_month=event_month(event),
        hold_year=event_hold_year(event),
        status=status,
        value_dependency=value,
        noi_dependency=noi,
        sizing=sizing,
        payoffs=payoffs,
        funding=funding,
        bridge=bridge,
        unavailable_reason=reason,
        unavailable_message=message,
    )


def _affected(event: RefinanceEvent, replacement: CapitalPosition, scope_positions: tuple[CapitalPosition, ...]) -> frozenset[str]:
    retired = {ref.position_id for ref in event.retiring if isinstance(ref, AuthoredPositionRef)}
    return frozenset(
        {
            replacement.position_id,
            *retired,
            *(position.position_id for position in scope_positions if position.priority >= replacement.priority),
        }
    )


def _bridge(
    *, proceeds: float, payoffs: tuple[RetiringPayoff, ...], replacement_fees: float, event: RefinanceEvent
) -> RefinanceBridge:
    payoff_total = _total([payoff.payoff for payoff in payoffs], "payoffs")
    retiring_fees = _total([payoff.retiring_lender_fees for payoff in payoffs], "retiring_lender_fees")
    third_party = _total(
        [float(line.amount) for line in sorted(event.costs, key=lambda line: line.cost_id) if line.kind is RefinanceCostKind.THIRD_PARTY_COST],
        "third_party_costs",
    )
    net = proceeds - payoff_total
    net = net - replacement_fees
    net = net - retiring_fees
    net = ensure_finite("net_event_cash", net - third_party)
    direction = BridgeDirection.DISTRIBUTION if net > 0.0 else BridgeDirection.CONTRIBUTION if net < 0.0 else BridgeDirection.ZERO
    return RefinanceBridge(
        gross_proceeds=proceeds,
        payoffs=payoff_total,
        replacement_lender_fees=replacement_fees,
        retiring_lender_fees=retiring_fees,
        third_party_costs=third_party,
        net_event_cash=net,
        direction=direction,
    )


def plan_refinance(
    event: RefinanceEvent,
    *,
    scope_positions: tuple[CapitalPosition, ...],
    hold_period: int,
    price_basis: PriceBasis,
    valuations: ValuationAuthority | None,
    unit: UnitRefinanceAuthority | None,
    investment: InvestmentRefinanceAuthority | None,
) -> RefinancePlan:
    """The plan of one structurally valid, execution-admitted event for one
    variant. ``scope_positions`` are the claim-bearing positions of the event
    scope in economic order; ``unit`` is the event Unit's authority (Unit
    scope) and ``investment`` the Investment's (Investment scope)."""

    positions = {position.position_id: position for position in scope_positions}
    replacement = positions[event.replacement_position_id]
    affected = _affected(event, replacement, scope_positions)
    model_month = event_month(event)

    def unavailable(status: RefinanceStatus, reason: RefinanceUnavailableReason, message: str, **extra: object) -> RefinancePlan:
        return RefinancePlan(
            event=event,
            result=_result(event, status=status, reason=reason, message=message, **extra),  # type: ignore[arg-type]
            replacement_view=None,
            retiring_views=(),
            retired_legacy_unit_id=None,
            continuing_senior_balance=0.0,
            affected_position_ids=affected,
        )

    if model_month >= MONTHS_PER_HOLD_YEAR * hold_period:
        return unavailable(
            RefinanceStatus.UNAVAILABLE,
            RefinanceUnavailableReason.EVENT_OUTSIDE_HOLD_HORIZON,
            f"'{event.label}' is at model month {model_month}, at or after this variant's sale at model month "
            f"{MONTHS_PER_HOLD_YEAR * hold_period}. The same event may execute under a longer hold.",
        )

    retirement = _retire(
        event, positions=positions, price_basis=price_basis, valuations=valuations, unit=unit
    )
    senior_balance, senior_service = _continuing_seniors(
        event,
        replacement=replacement,
        scope_positions=scope_positions,
        hold_period=hold_period,
        price_basis=price_basis,
        valuations=valuations,
        unit=unit,
    )

    sizing = event.sizing
    capacities: list[ConstraintCapacity] = []
    value_dependency: ValueDependency | None = None
    noi_dependency: NoiDependency | None = None
    noi: float | None = None
    per_dollar = 0.0
    if sizing.min_dscr is not None:
        per_dollar = first_year_service(
            replacement_schedule(
                replacement,
                principal=1.0,
                model_month=model_month,
                hold_period=hold_period,
                price_basis=price_basis,
            ),
            model_month=model_month,
        )
        noi = forward_noi(event.scope, model_month=model_month, unit=unit, investment=investment)
        noi_dependency = NoiDependency(
            scope=event.scope,
            model_month=model_month,
            forward_year=event_hold_year(event) + 1,
            status=ConstraintAvailability.UNAVAILABLE if noi is None else ConstraintAvailability.AVAILABLE,
            forward_noi=noi,
        )

    if sizing.fixed_cap is not None:
        amount = float(sizing.fixed_cap.amount)
        capacities.append(_available_capacity(ConstraintKind.FIXED_CAP, FixedCapOperands(amount=amount), amount))
    if sizing.max_ltv is not None:
        value_dependency, reason, message = _value_dependency(
            event, valuations=valuations, model_month=model_month, unit=unit, investment=investment
        )
        max_ltv = float(sizing.max_ltv.max_ltv)
        value = None if reason is not None or value_dependency is None else value_dependency.value
        operands = MaxLtvOperands(max_ltv=max_ltv, scope_value=value, continuing_senior_balance=senior_balance)
        if value is None or reason is not None:
            capacities.append(
                _unavailable_capacity(ConstraintKind.MAX_LTV, operands, reason or RefinanceUnavailableReason.VALUATION_UNAVAILABLE, message or "")
            )
        else:
            capacities.append(_available_capacity(ConstraintKind.MAX_LTV, operands, max_ltv * value - senior_balance))
    if sizing.min_dscr is not None:
        min_dscr = float(sizing.min_dscr.min_dscr)
        if noi is None:
            capacities.append(
                _unavailable_capacity(
                    ConstraintKind.MIN_DSCR,
                    MinDscrOperands(
                        min_dscr=min_dscr,
                        forward_noi=None,
                        continuing_senior_service=senior_service,
                        service_capacity=None,
                        first_year_service_per_dollar=per_dollar,
                    ),
                    RefinanceUnavailableReason.FORWARD_NOI_UNAVAILABLE,
                    f"This variant has no forward NOI for model month {model_month}, so '{event.label}' cannot size by DSCR.",
                )
            )
        elif noi <= 0.0:
            capacities.append(
                _unavailable_capacity(
                    ConstraintKind.MIN_DSCR,
                    MinDscrOperands(
                        min_dscr=min_dscr,
                        forward_noi=noi,
                        continuing_senior_service=senior_service,
                        service_capacity=None,
                        first_year_service_per_dollar=per_dollar,
                    ),
                    RefinanceUnavailableReason.NON_POSITIVE_FORWARD_NOI,
                    f"Forward NOI at model month {model_month} is not positive, so '{event.label}' cannot size by "
                    "DSCR. It is never floored.",
                )
            )
        else:
            service_capacity = ensure_finite("service_capacity", noi / min_dscr - senior_service)
            capacities.append(
                _available_capacity(
                    ConstraintKind.MIN_DSCR,
                    MinDscrOperands(
                        min_dscr=min_dscr,
                        forward_noi=noi,
                        continuing_senior_service=senior_service,
                        service_capacity=service_capacity,
                        first_year_service_per_dollar=per_dollar,
                    ),
                    service_capacity / per_dollar,
                )
            )

    outcome = _sizing(tuple(capacities))
    extra = {"value": value_dependency, "noi": noi_dependency, "sizing": outcome}
    if retirement.reason is not None:
        return unavailable(RefinanceStatus.UNAVAILABLE, retirement.reason, retirement.message or "", **extra)
    for capacity in outcome.capacities:
        if capacity.unavailable_reason is not None:
            return unavailable(
                RefinanceStatus.UNAVAILABLE, capacity.unavailable_reason, capacity.unavailable_message or "", **extra
            )
    proceeds = outcome.gross_proceeds
    if proceeds is None:
        return unavailable(
            RefinanceStatus.NOT_EXECUTABLE,
            RefinanceUnavailableReason.NON_POSITIVE_CAPACITY,
            f"The smallest capacity of '{event.label}' is not positive, so no replacement loan can be funded. The old "
            "debt is not kept in place as though the Strategy had no refinance.",
            **extra,
        )

    view = replacement_schedule(
        replacement,
        principal=proceeds,
        model_month=model_month,
        hold_period=hold_period,
        price_basis=price_basis,
    )
    replacement_fees = _total(
        [item.amount for item in view.events if item.kind is PositionCashFlowKind.FEE], "replacement_lender_fees"
    )
    first_year = first_year_service(view, model_month=model_month)
    achieved_dscr = (
        None if noi is None else ensure_finite("achieved_dscr", noi / (senior_service + first_year))
    )
    if (
        achieved_dscr is not None
        and sizing.min_dscr is not None
        and ConstraintKind.MIN_DSCR in outcome.binding
        and achieved_dscr < float(sizing.min_dscr.min_dscr) * (1.0 - ACHIEVED_DSCR_RELATIVE_TOLERANCE)
    ):
        raise CapitalStructureError(
            f"Engine defect: '{event.label}' is DSCR-bound at {sizing.min_dscr.min_dscr!r}, but its executed schedule "
            f"achieves {achieved_dscr!r}. Scheduled service is not proportional to principal."
        )
    scope_value = None if value_dependency is None else value_dependency.value
    achieved_ltv = (
        None
        if scope_value is None or scope_value == 0.0
        else ensure_finite("achieved_ltv", (proceeds + senior_balance) / scope_value)
    )
    bridge = _bridge(proceeds=proceeds, payoffs=retirement.payoffs, replacement_fees=replacement_fees, event=event)
    return RefinancePlan(
        event=event,
        result=_result(
            event,
            status=RefinanceStatus.EXECUTED,
            value=value_dependency,
            noi=noi_dependency,
            sizing=outcome,
            payoffs=retirement.payoffs,
            funding=ReplacementFunding(
                position_id=replacement.position_id,
                funding_month=model_month,
                gross_proceeds=proceeds,
                replacement_lender_fees=replacement_fees,
                first_service_month=model_month + 1,
                first_year_service=first_year,
                achieved_ltv=achieved_ltv,
                achieved_dscr=achieved_dscr,
            ),
            bridge=bridge,
        ),
        replacement_view=view,
        retiring_views=retirement.views,
        retired_legacy_unit_id=retirement.legacy_unit_id,
        continuing_senior_balance=senior_balance,
        affected_position_ids=affected,
    )


def blocked(plan: RefinancePlan, *, message: str) -> RefinancePlan:
    """The same plan, reported ``BLOCKED``: an unresolved Funding Requirement
    upstream of the event stops settlement, so neither the funding nor the
    bridge is reported. Sizing and payoffs stay, as contractual facts."""

    result = replace(
        plan.result,
        status=RefinanceStatus.BLOCKED,
        funding=None,
        bridge=None,
        unavailable_reason=RefinanceUnavailableReason.UPSTREAM_UNRESOLVED_FUNDING,
        unavailable_message=message,
    )
    return replace(plan, result=result)


__all__ = [
    "InvestmentRefinanceAuthority",
    "RefinancePlan",
    "UnitRefinanceAuthority",
    "blocked",
    "event_hold_year",
    "event_month",
    "first_year_service",
    "forward_noi",
    "legacy_balance",
    "plan_refinance",
    "replacement_schedule",
]
