"""Shared Refinance & Capital Events V1 Stage 1 fixtures (not a test module).

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 18. The base case
of Section 18.1, builders for refinance events and their replacement positions,
a P7.10 valuation authority, and the independent exact-rational oracles the
fixtures assert against.

No helper here calls ``anchor.capital_structure.refinance``,
``anchor.engine.acquisition_debt_balance`` or ``anchor.engine.debt``: every
expected figure is either stated from the contract's hand arithmetic or
computed by ``fractions.Fraction`` from the stated terms, so an expected value
never comes from the code under test.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from _p7_8_fixtures import CEC, cash_pay_debt, round_unit  # type: ignore[import-not-found]

from anchor.capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    CapitalStructureUnit,
    FixedAmount,
    FundingEvent,
    PositionClass,
    PositionFee,
    PositionScope,
    RefinanceProceeds,
    ScopeKind,
    ShortfallResolution,
)
from anchor.capital_structure.events import (
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
    RetiringPositionRef,
)
from anchor.capital_structure.execution import execute_investment_capital_structure, execute_unit_capital_structure
from anchor.contracts import AcquisitionTerms
from anchor.engine.contracts import AcquisitionResults
from anchor.valuation.contracts import (
    AnalystValue,
    DirectCap,
    UnitValuationInstruction,
    ValuationKind,
    ValuationMethod,
    ValuationTimepoint,
)
from anchor.valuation.engine import resolve_investment_valuation, unit_inputs, variant_inputs
from anchor.valuation.funding import ValuationAuthority, valuation_authority

UNIT = "u1"
INVESTMENT_ID = "inv-refi"
EVENT_ID = "refi-year-2"
EVENT_LABEL = "Year-2 refinance"
REPLACEMENT_ID = "refi-loan"
TIMEPOINT_ID = "year-2-value"
EVENT_MONTH = 24
EVENT_YEAR = 2
HOLD = 5

#: Section 18.1, stated. The legacy loan: $6,000,000 at 0% over 25 years.
LEGACY_PRINCIPAL = 6_000_000
LEGACY_MONTHLY = 20_000
LEGACY_ANNUAL = 240_000
LEGACY_PAYOFF_AT_24 = 5_520_000
LEGACY_BALANCE_AT_60 = 4_800_000
FORWARD_NOI = 800_000
VALUE_AT_24 = 12_500_000


def unit_scope(unit_id: str = UNIT) -> PositionScope:
    return PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id)


INVESTMENT_SCOPE = PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None)


# =============================================================================
# Units
# =============================================================================


def base_unit(**overrides: Any) -> tuple[AcquisitionTerms, AcquisitionResults]:
    """Section 18.1: flat $800,000 NOI over a five-year hold, a $6,000,000
    acquisition loan at 0% over 25 years with no IO and no fees, and a 6.4% exit
    cap. Every override is a Quick input."""

    base: dict[str, Any] = {"interest_rate": 0.0, "amortization": 25, "io_period": 0, "exit_cap_rate": 0.064}
    base.update(overrides)
    return round_unit(**base)


def capital_unit(unit_id: str = UNIT, **overrides: Any) -> CapitalStructureUnit:
    terms, results = base_unit(**overrides)
    return CapitalStructureUnit(unit_id=unit_id, terms=terms, results=results)


# =============================================================================
# Positions and events
# =============================================================================


def replacement(
    position_id: str = REPLACEMENT_ID,
    *,
    event_id: str = EVENT_ID,
    month: int = EVENT_MONTH,
    priority: int = 1,
    rate: float = 0.05,
    io_period: int = 5,
    amortization: int = 30,
    maturity_month: int = 144,
    fees: tuple[PositionFee, ...] = (),
    scope: PositionScope | None = None,
    position_class: PositionClass = PositionClass.SENIOR_DEBT,
    resolution: ShortfallResolution = CEC,
) -> CapitalPosition:
    """The replacement: an ordinary debt position funded by
    ``RefinanceProceeds``. The base is 5% interest-only through the sale."""

    return CapitalPosition(
        position_id=position_id,
        name="Replacement loan",
        position_class=position_class,
        priority=priority,
        scope=unit_scope() if scope is None else scope,
        funding=(
            FundingEvent(
                event_id=f"{position_id}-funding",
                model_month=month,
                sequence=1,
                amount_rule=RefinanceProceeds(capital_event_id=event_id),
            ),
        ),
        terms=cash_pay_debt(
            rate=rate, amortization=amortization, io_period=io_period, maturity_month=maturity_month, fees=fees
        ),
        shortfall_resolution=resolution,
    )


def lender_fee(amount: float, *, fee_id: str = "refi-origination", month: int = EVENT_MONTH) -> PositionFee:
    """A replacement lender fee. It shares the event month with the funding,
    so P7.7's distinct-sequence rule makes it sequence 2."""

    return PositionFee(fee_id=fee_id, description="Origination", amount=amount, model_month=month, sequence=2)


def closing_debt(
    position_id: str,
    *,
    amount: float,
    priority: int,
    rate: float,
    position_class: PositionClass = PositionClass.MEZZANINE_DEBT,
    amortization: int = 30,
    io_period: int = 0,
    maturity_month: int = 120,
    scope: PositionScope | None = None,
    resolution: ShortfallResolution = CEC,
) -> CapitalPosition:
    return CapitalPosition(
        position_id=position_id,
        name=position_id.replace("-", " ").title(),
        position_class=position_class,
        priority=priority,
        scope=unit_scope() if scope is None else scope,
        funding=(FundingEvent(event_id=f"{position_id}-funding", model_month=0, sequence=1, amount_rule=FixedAmount(amount=amount)),),
        terms=cash_pay_debt(rate=rate, amortization=amortization, io_period=io_period, maturity_month=maturity_month),
        shortfall_resolution=resolution,
    )


def third_party(amount: float, cost_id: str = "legal-title") -> RefinanceCostLine:
    return RefinanceCostLine(
        cost_id=cost_id, kind=RefinanceCostKind.THIRD_PARTY_COST, amount=amount, recipient=None, description="Legal and title"
    )


def exit_fee(amount: float, recipient: RetiringPositionRef, cost_id: str = "exit-fee") -> RefinanceCostLine:
    return RefinanceCostLine(
        cost_id=cost_id, kind=RefinanceCostKind.RETIRING_LENDER_FEE, amount=amount, recipient=recipient, description="Exit fee"
    )


def event(
    *,
    fixed: float | None = None,
    ltv: float | None = None,
    dscr: float | None = None,
    valuation: str | None | object = ...,
    retiring: tuple[RetiringPositionRef, ...] = (LegacyAcquisitionLoanRef(unit_id=UNIT),),
    costs: tuple[RefinanceCostLine, ...] = (),
    event_id: str = EVENT_ID,
    replacement_id: str = REPLACEMENT_ID,
    month: int = EVENT_MONTH,
    scope: PositionScope | None = None,
    label: str = EVENT_LABEL,
) -> RefinanceEvent:
    """A refinance. ``valuation`` defaults to the base timepoint exactly when
    LTV is enabled, as the contract requires; pass it explicitly to break that."""

    reference: RefinanceValuationRef | None
    if valuation is ...:
        reference = RefinanceValuationRef(timepoint_id=TIMEPOINT_ID) if ltv is not None else None
    elif valuation is None:
        reference = None
    else:
        reference = RefinanceValuationRef(timepoint_id=str(valuation))
    return RefinanceEvent(
        event_id=event_id,
        kind=CapitalEventKind.REFINANCE,
        scope=unit_scope() if scope is None else scope,
        timing=EventTiming(model_month=month, sequence=1),
        label=label,
        retiring=retiring,
        replacement_position_id=replacement_id,
        sizing=RefinanceSizing(
            fixed_cap=None if fixed is None else FixedProceedsCap(amount=fixed),
            max_ltv=None if ltv is None else MaxLtvConstraint(max_ltv=ltv),
            min_dscr=None if dscr is None else MinDscrConstraint(min_dscr=dscr),
        ),
        valuation=reference,
        costs=costs,
    )


def evented(*positions: CapitalPosition, events: tuple[RefinanceEvent, ...]) -> CapitalStructureWithEvents:
    return CapitalStructureWithEvents(positions=tuple(positions), events=events)


def plain(*positions: CapitalPosition) -> CapitalStructure:
    return CapitalStructure(positions=tuple(positions))


def authored_ref(position_id: str) -> AuthoredPositionRef:
    return AuthoredPositionRef(position_id=position_id)


LEGACY = LegacyAcquisitionLoanRef(unit_id=UNIT)


# =============================================================================
# Valuations
# =============================================================================


def authority(
    units: tuple[tuple[str, AcquisitionTerms, AcquisitionResults], ...],
    *,
    month: int = EVENT_MONTH,
    methods: dict[str, ValuationMethod] | None = None,
    timepoint_id: str = TIMEPOINT_ID,
    label: str = "Year-2 value",
) -> ValuationAuthority:
    """A P7.10 authority holding one CUSTOM timepoint, resolved through P7.10's
    own engine for the given variant. The default method is the base case's
    6.4% direct cap."""

    chosen = methods or {}
    point = ValuationTimepoint(
        timepoint_id=timepoint_id,
        investment_id=INVESTMENT_ID,
        kind=ValuationKind.CUSTOM,
        label=label,
        model_month=month,
        unit_instructions=tuple(
            UnitValuationInstruction(unit_id=unit_id, method=chosen.get(unit_id, DirectCap(cap_rate=0.064)))
            for unit_id, _, _ in units
        ),
    )
    variant = variant_inputs(
        investment_id=INVESTMENT_ID,
        units=tuple(unit_inputs(unit_id=unit_id, terms=terms, results=results) for unit_id, terms, results in units),
    )
    return valuation_authority(investment_id=INVESTMENT_ID, valuations=(resolve_investment_valuation(point, variant=variant),))


def unit_authority(terms: AcquisitionTerms, results: AcquisitionResults, **kwargs: Any) -> ValuationAuthority:
    return authority(((UNIT, terms, results),), **kwargs)


def stated_value(amount: float) -> AnalystValue:
    return AnalystValue(amount=amount, evidence_id="appraisal-1")


# =============================================================================
# Running
# =============================================================================


def run_unit(
    structure: CapitalStructure | None,
    *,
    terms: AcquisitionTerms | None = None,
    results: AcquisitionResults | None = None,
    valuations: ValuationAuthority | None = None,
    with_valuation: bool = True,
) -> Any:
    if terms is None or results is None:
        terms, results = base_unit()
    if valuations is None and with_valuation:
        valuations = unit_authority(terms, results)
    return execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure, valuations=valuations
    )


def run_investment(
    structure: CapitalStructure | None, *, units: tuple[CapitalStructureUnit, ...], consolidated: Any, valuations: Any = None
) -> Any:
    return execute_investment_capital_structure(
        units=units, consolidated=consolidated, capital_structure=structure, valuations=valuations
    )


def base_structure(**event_kwargs: Any) -> CapitalStructureWithEvents:
    """The base replacement retiring the legacy loan, with the given sizing."""

    fees = event_kwargs.pop("replacement_fees", ())
    return evented(replacement(fees=fees), events=(event(**event_kwargs),))


# =============================================================================
# Exact-rational oracles (independent of the engine)
# =============================================================================


def close(actual: float, expected: Fraction | int | float, *, rel: float = 1e-12, absolute: float = 1e-6) -> bool:
    """The P7.9 Section 14 tolerance: ``1e-6 + 1e-12 x |x|``."""

    target = Fraction(expected)
    return abs(Fraction(actual) - target) <= Fraction(absolute) + Fraction(rel) * abs(target)


def oracle_level_payment(principal: Fraction, *, annual_rate: Fraction, n_payments: int) -> Fraction:
    """The level monthly payment, exactly: ``P i / (1 - (1 + i)^-n)``, or
    ``P / n`` at a zero rate."""

    if annual_rate == 0:
        return principal / n_payments
    i = annual_rate / 12
    return principal * i / (1 - (1 + i) ** -n_payments)


def oracle_balance_after(
    principal: Fraction, *, annual_rate: Fraction, amortization_years: int, io_years: int, month: int
) -> Fraction:
    """The balance after month ``month``'s payment, exactly, by the stated
    recurrence: interest-only months leave the balance unchanged; each
    amortizing month repays ``payment - balance x i``."""

    i = annual_rate / 12
    n = 12 * amortization_years
    io_months = 12 * io_years
    payment = oracle_level_payment(principal, annual_rate=annual_rate, n_payments=n)
    balance = principal
    for t in range(1, month + 1):
        if t <= io_months:
            continue
        if t - io_months > n:
            return Fraction(0)
        balance = balance - (payment - balance * i)
    return balance


def oracle_npv(cash_flows: tuple[float, ...] | list[Fraction], rate: Fraction) -> Fraction:
    return sum((Fraction(amount) / (1 + rate) ** t for t, amount in enumerate(cash_flows)), Fraction(0))
