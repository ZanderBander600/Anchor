"""Shared P7.7 fixtures (not a test module).

Completed Unit analyses of every mode, run through today's D6 entry points
exactly as a Deal runs them; visible-Investment analyses through the P7.6
variant authority; and small builders for authored Capital Structure contracts.
Every economic input is a literal from the P7.1 fixtures.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from anchor.analysis.business_plan_analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.business_plan import BusinessPlan, CapitalItemCategory, CapitalPlanItem
from anchor.capital_structure import (
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureUnit,
    DebtTerms,
    FixedAmount,
    FundingEvent,
    PositionClass,
    PositionFee,
    PositionScope,
    PreferredEquityTerms,
    ScopeKind,
    ShortfallResolution,
)
from anchor.contracts import AcquisitionTerms, acquisition_terms_from_inputs
from anchor.deals.investment_variants import (
    InvestmentVariantAnalysis,
    analyze_investment_variant,
    inspect_investment_variant_inputs,
)
from anchor.engine.contracts import AcquisitionResults

MODES = ("quick", "detailed", "lease_level")
BASE = "base"


def bits(values: Iterable[float]) -> list[bytes]:
    """The IEEE-754 bytes of each value: equality here is bit-for-bit, so
    ``-0.0`` differs from ``0.0`` and nothing is compared within a tolerance."""

    return [struct.pack("<d", value) for value in values]


def heavy_plan(month: int, amount: float) -> BusinessPlan:
    """The P7.1 plan plus one large capital item, enough to turn that hold
    year's Unlevered Owner Cash Flow negative."""

    base = fx.business_plan()
    return BusinessPlan(
        capital_items=(
            *base.capital_items,
            CapitalPlanItem(
                item_id="cap-heavy",
                description="Major repositioning",
                category=CapitalItemCategory.VALUE_ADD_RENOVATION,
                month=month,
                amount=amount,
            ),
        ),
        owner_expense_items=base.owner_expense_items,
    )


def analyze_unit(
    mode: str, *, business_plan: BusinessPlan | None = None, **overrides: Any
) -> tuple[AcquisitionTerms, AcquisitionResults]:
    """One Unit through today's engine, exactly as a Deal of ``mode`` runs:
    its resolved ``AcquisitionTerms`` and its completed ``AcquisitionResults``."""

    plan = BusinessPlan() if business_plan is None else business_plan
    if mode == "quick":
        inputs = fx.quick_inputs(**overrides)
        return acquisition_terms_from_inputs(inputs), analyze_quick_acquisition_with_business_plan(inputs, business_plan=plan)
    if mode == "detailed":
        terms = fx.detailed_terms(**overrides)
        return terms, analyze_detailed_acquisition_with_business_plan(terms, fx.detailed_operating(), business_plan=plan).results
    if mode == "lease_level":
        terms = fx.lease_level_terms(**overrides)
        suites, leases = fx.rent_roll()
        envelope = analyze_lease_level_acquisition_with_business_plan(
            terms,
            fx.lease_level_property(),
            suites,
            leases,
            market_leasing=fx.market(),
            operating_inputs=fx.lease_level_operating(),
            business_plan=plan,
        )
        return terms, envelope.results
    raise ValueError(mode)


#: Realistic acquisitions of every mode: nonzero LTV, a financing fee,
#: amortization, interest-only years (Quick 2, Detailed 1, one Lease-Level 2),
#: Business Plans, and a negative Unlevered Owner Cash Flow year in each mode.
PARITY_CASES: dict[str, tuple[str, Callable[[], BusinessPlan], dict[str, Any]]] = {
    "quick-io": ("quick", BusinessPlan, {}),
    "quick-plan": ("quick", fx.business_plan, {}),
    "quick-negative-owner-year": ("quick", lambda: heavy_plan(14, 3_000_000.0), {}),
    "detailed-io": ("detailed", BusinessPlan, {}),
    "detailed-plan": ("detailed", fx.business_plan, {}),
    "detailed-negative-owner-year": ("detailed", lambda: heavy_plan(26, 4_000_000.0), {}),
    "lease-level": ("lease_level", BusinessPlan, {}),
    "lease-level-plan": ("lease_level", fx.business_plan, {}),
    "lease-level-io-negative-owner-year": ("lease_level", lambda: heavy_plan(30, 6_000_000.0), {"io_period": 2}),
}


def parity_case(name: str) -> tuple[AcquisitionTerms, AcquisitionResults]:
    mode, plan, overrides = PARITY_CASES[name]
    return analyze_unit(mode, business_plan=plan(), **overrides)


def _terms_of(resolved: Any) -> AcquisitionTerms:
    terms = getattr(resolved, "terms", None)
    return acquisition_terms_from_inputs(resolved.inputs) if terms is None else terms


def analyze_visible_investment(
    investment_id: str, db: Path
) -> tuple[InvestmentVariantAnalysis, tuple[CapitalStructureUnit, ...]]:
    """The P7.6 Base x Base analysis of a visible Investment, and each Unit as
    the Capital Structure facade receives it: its resolved terms and its
    completed project results."""

    analysis = analyze_investment_variant(investment_id, BASE, BASE, db_path=db)
    inputs = inspect_investment_variant_inputs(investment_id, BASE, BASE, db_path=db)
    units: list[CapitalStructureUnit] = []
    for unit_inputs, unit_result in zip(inputs.units, analysis.unit_results, strict=True):
        assert unit_inputs.unit_id == unit_result.unit_id
        envelope = unit_result.results
        results = envelope if isinstance(envelope, AcquisitionResults) else envelope.results
        units.append(CapitalStructureUnit(unit_id=unit_inputs.unit_id, terms=_terms_of(unit_inputs.resolved), results=results))
    return analysis, tuple(units)


# =============================================================================
# Authored-position builders
# =============================================================================


def unit_scope(unit_id: Any) -> PositionScope:
    return PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id)


INVESTMENT = PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None)


def funding(event_id: str, *, month: Any = 0, sequence: Any = 1, rule: Any = None) -> FundingEvent:
    return FundingEvent(
        event_id=event_id,
        model_month=month,
        sequence=sequence,
        amount_rule=FixedAmount(amount=1_000_000.0) if rule is None else rule,
    )


def fee(fee_id: str, *, amount: Any = 10_000.0, month: Any = 0, sequence: Any = 2, description: Any = "Origination fee") -> PositionFee:
    return PositionFee(fee_id=fee_id, description=description, amount=amount, model_month=month, sequence=sequence)


def debt_terms(**overrides: Any) -> DebtTerms:
    base: dict[str, Any] = {
        "interest_rate": 0.11,
        "amortization": 30,
        "io_period": 3,
        "maturity_month": 60,
        "fees": (),
        "current_pay_rate": 0.08,
        "pik_rate": 0.03,
    }
    base.update(overrides)
    return DebtTerms(**base)


def preferred_terms(**overrides: Any) -> PreferredEquityTerms:
    base: dict[str, Any] = {
        "preferred_rate": 0.12,
        "current_pay_rate": 0.08,
        "accrual_permitted": True,
        "accrual_convention": AccrualConvention.ANNUAL_COMPOUND,
        "redemption_month": 60,
    }
    base.update(overrides)
    return PreferredEquityTerms(**base)


_BY_CLASS = object()


def position(
    position_id: Any,
    *,
    position_class: Any = PositionClass.MEZZANINE_DEBT,
    priority: Any = 2,
    scope: Any = None,
    funding_events: Any = _BY_CLASS,
    terms: Any = _BY_CLASS,
    shortfall_resolution: Any = _BY_CLASS,
    name: Any = "Position",
) -> CapitalPosition:
    """A well-formed authored position of ``position_class`` unless told
    otherwise: claim-bearing classes get one closing funding and their terms;
    common equity gets neither, and no resolution. A test's explicit arguments
    always win -- including ``None``."""

    common = position_class is PositionClass.COMMON_EQUITY
    if terms is _BY_CLASS:
        terms = (
            None
            if common
            else preferred_terms()
            if position_class is PositionClass.PREFERRED_EQUITY
            else debt_terms()
        )
    if funding_events is _BY_CLASS:
        funding_events = () if common else (funding(f"{position_id}-funding"),)
    if shortfall_resolution is _BY_CLASS:
        shortfall_resolution = None if common else ShortfallResolution.UNRESOLVED
    return CapitalPosition(
        position_id=position_id,
        name=name,
        position_class=position_class,
        priority=priority,
        scope=unit_scope("u1") if scope is None else scope,
        funding=funding_events,
        terms=terms,
        shortfall_resolution=shortfall_resolution,
    )


def structure(*positions: Any) -> CapitalStructure:
    return CapitalStructure(positions=tuple(positions))


def valid_positions() -> tuple[CapitalPosition, ...]:
    """Every class, both scope kinds and every term variant, valid over Units
    ``u1`` (which carries an acquisition loan) and ``u2`` (which does not)."""

    return (
        position(
            "mezz-u1",
            priority=2,
            scope=unit_scope("u1"),
            terms=debt_terms(fees=(fee("mezz-u1-fee"),)),
        ),
        position("senior-u2", position_class=PositionClass.SENIOR_DEBT, priority=1, scope=unit_scope("u2")),
        position(
            "pref-inv",
            position_class=PositionClass.PREFERRED_EQUITY,
            priority=1,
            scope=INVESTMENT,
            shortfall_resolution=ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
        ),
        position("common-inv", position_class=PositionClass.COMMON_EQUITY, priority=2, scope=INVESTMENT),
    )


MEMBERS = frozenset({"u1", "u2"})
LOAN_UNITS = frozenset({"u1"})
