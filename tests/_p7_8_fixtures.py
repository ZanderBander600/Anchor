"""Shared P7.8 fixtures (not a test module).

Round-number Units whose project economics a reader can check by hand, cash-pay
debt and preferred builders with explicit resolutions, and the independent
hand arithmetic the golden oracles use -- a closed-form level payment and
balance, and a net present value -- written without any
``anchor.engine.debt`` or ``anchor.capital_structure`` function, so an expected
value never comes from the code under test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from _p7_7_fixtures import (  # type: ignore[import-not-found]
    INVESTMENT,
    analyze_visible_investment,
    fee,
    funding,
    unit_scope,
)
from anchor.analysis.business_plan_analysis import analyze_quick_acquisition_with_business_plan
from anchor.business_plan import BusinessPlan
from anchor.capital_structure import (
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureUnit,
    DebtTerms,
    FixedAmount,
    PositionClass,
    PreferredEquityTerms,
    ShortfallResolution,
)
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, acquisition_terms_from_inputs
from anchor.engine.contracts import AcquisitionResults

CEC = ShortfallResolution.COMMON_EQUITY_CONTRIBUTION
UNRESOLVED = ShortfallResolution.UNRESOLVED
UNIT = "u1"


# =============================================================================
# Round-number Units
# =============================================================================


def round_inputs(**overrides: Any) -> AcquisitionInputs:
    """A $10,000,000 acquisition with flat $800,000 NOI, an 8% exit cap (exit
    value $10,000,000), no costs or reserve, and a $6,000,000 acquisition loan
    at 5% interest-only for the whole five-year hold ($300,000 a year). Its
    Equity Cash Flow is ``-4,000,000; 500,000 x 4; 4,500,000``."""

    base: dict[str, Any] = {
        "purchase_price": 10_000_000.0,
        "current_noi": 800_000.0,
        "occupancy": 0.95,
        "noi_growth": 0.0,
        "hold_period": 5,
        "exit_cap_rate": 0.08,
        "ltv": 0.6,
        "interest_rate": 0.05,
        "amortization": 30,
        "acquisition_cost_pct": 0.0,
        "financing_fee_pct": 0.0,
        "disposition_cost_pct": 0.0,
        "annual_capex_reserve": 0.0,
        "io_period": 5,
    }
    base.update(overrides)
    return AcquisitionInputs(**base)


def round_unit(business_plan: BusinessPlan | None = None, **overrides: Any) -> tuple[AcquisitionTerms, AcquisitionResults]:
    """The round-number Unit through today's Quick engine."""

    inputs = round_inputs(**overrides)
    results = analyze_quick_acquisition_with_business_plan(
        inputs, business_plan=BusinessPlan() if business_plan is None else business_plan
    )
    return acquisition_terms_from_inputs(inputs), results


def round_deal(db: Path, *, name: str, **overrides: Any) -> Any:
    """The round-number Unit saved as a Quick Deal on the common P7.6 hold."""

    inputs = round_inputs(**overrides)
    fields = {key: getattr(inputs, key) for key in inputs.__dataclass_fields__}
    return quick_deal(db, name=name, **fields)


def visible(db: Path, *deals: Any, **kwargs: Any) -> tuple[Any, tuple[CapitalStructureUnit, ...]]:
    """A visible Investment over ``deals`` and its Units as the executor
    receives them."""

    investment = create_investment(db, *deals, **kwargs)
    return analyze_visible_investment(investment.id, db)


# =============================================================================
# Positions
# =============================================================================


def cash_pay_debt(
    *, rate: float, amortization: int = 30, io_period: int = 0, maturity_month: int = 60, fees: tuple[Any, ...] = ()
) -> DebtTerms:
    return DebtTerms(
        interest_rate=rate,
        amortization=amortization,
        io_period=io_period,
        maturity_month=maturity_month,
        fees=fees,
        current_pay_rate=rate,
        pik_rate=0.0,
    )


def preferred(
    *,
    preferred_rate: float,
    current_pay_rate: float,
    convention: AccrualConvention | None = None,
    redemption_month: int = 60,
) -> PreferredEquityTerms:
    return PreferredEquityTerms(
        preferred_rate=preferred_rate,
        current_pay_rate=current_pay_rate,
        accrual_permitted=convention is not None,
        accrual_convention=convention,
        redemption_month=redemption_month,
    )


def claim_position(
    position_id: str,
    *,
    position_class: PositionClass,
    priority: int,
    terms: DebtTerms | PreferredEquityTerms,
    resolution: ShortfallResolution,
    amount: float | None = None,
    funding_events: tuple[Any, ...] | None = None,
    scope: Any = None,
) -> CapitalPosition:
    """One authored claim-bearing position, funded at closing by ``amount``
    unless ``funding_events`` says otherwise."""

    if funding_events is None:
        if amount is None:
            raise ValueError(f"{position_id} needs a closing amount or its funding events.")
        funding_events = (funding(f"{position_id}-funding", rule=FixedAmount(amount=amount)),)
    events = funding_events
    return CapitalPosition(
        position_id=position_id,
        name=position_id.title(),
        position_class=position_class,
        priority=priority,
        scope=unit_scope(UNIT) if scope is None else scope,
        funding=events,
        terms=terms,
        shortfall_resolution=resolution,
    )


def common_marker(position_id: str = "common", *, priority: int = 9, scope: Any = None) -> CapitalPosition:
    return CapitalPosition(
        position_id=position_id,
        name="Common equity",
        position_class=PositionClass.COMMON_EQUITY,
        priority=priority,
        scope=unit_scope(UNIT) if scope is None else scope,
        funding=(),
        terms=None,
        shortfall_resolution=None,
    )


def structure(*positions: CapitalPosition) -> CapitalStructure:
    return CapitalStructure(positions=tuple(positions))


#: The Unit golden's mezzanine loan: $1,500,000 at 12%, one interest-only year,
#: then a 25-year amortization, maturing at month 48 (before the month-60 exit),
#: with a $15,000 closing fee and a common-equity contribution for any shortfall.
GOLDEN_MEZZ_AMOUNT = 1_500_000.0
GOLDEN_MEZZ_FEE = 15_000.0


def golden_mezz(resolution: ShortfallResolution = CEC, *, priority: int = 2) -> CapitalPosition:
    return claim_position(
        "mezz",
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=priority,
        terms=cash_pay_debt(
            rate=0.12, amortization=25, io_period=1, maturity_month=48, fees=(fee("mezz-fee", amount=GOLDEN_MEZZ_FEE),)
        ),
        resolution=resolution,
        amount=GOLDEN_MEZZ_AMOUNT,
    )


# =============================================================================
# Independent hand arithmetic
# =============================================================================


def hand_level_payment(principal: float, annual_rate: float, n_payments: int) -> float:
    """The textbook level payment ``P r / (1 - (1 + r)^-n)``, monthly."""

    r = annual_rate / 12
    return principal * r / (1 - (1 + r) ** -n_payments)


def hand_balance(principal: float, annual_rate: float, payment: float, payments_made: int) -> float:
    """The closed-form balance after ``payments_made`` level payments:
    ``P (1 + r)^k - A ((1 + r)^k - 1) / r``."""

    r = annual_rate / 12
    growth = (1 + r) ** payments_made
    return principal * growth - payment * (growth - 1) / r


def npv(rate: float, cash_flows: tuple[float, ...]) -> float:
    return sum(cash_flow / (1 + rate) ** t for t, cash_flow in enumerate(cash_flows))


def close(actual: float | None, expected: float, tol: float = 1e-6) -> bool:
    """Equal within an absolute ``tol``: for hand arithmetic that groups
    floating-point operations differently from the engine."""

    return actual is not None and abs(actual - expected) <= tol


def all_close(actual: tuple[float, ...] | None, expected: tuple[float, ...] | list[float], tol: float = 1e-6) -> bool:
    return actual is not None and len(actual) == len(expected) and all(close(a, e, tol) for a, e in zip(actual, expected))


__all__ = [
    "CEC",
    "GOLDEN_MEZZ_AMOUNT",
    "GOLDEN_MEZZ_FEE",
    "INVESTMENT",
    "UNIT",
    "UNRESOLVED",
    "cash_pay_debt",
    "claim_position",
    "common_marker",
    "fee",
    "funding",
    "golden_mezz",
    "hand_balance",
    "hand_level_payment",
    "npv",
    "preferred",
    "round_deal",
    "round_inputs",
    "round_unit",
    "structure",
    "unit_scope",
    "visible",
]
