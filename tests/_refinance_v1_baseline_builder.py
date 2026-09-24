"""Refinance & Capital Events V1 Stage 1 baseline builder (not a test module;
see ``tests/test_refinance_v1_compatibility_oracle.py``).

Usage: ``python _refinance_v1_baseline_builder.py <repo_root> <out.json>``

``<repo_root>/src`` is either the accepted product baseline ``0e9f8cc``,
exported by ``git archive`` (which reads objects and never touches the index),
or this working tree. The builder asserts it imported exactly that tree, then
executes one fixed corpus of **no-refinance** Capital Structure and
Partnership analyses through that tree's own executors, and records the full
``repr`` of every result -- every field, every float to the last bit -- and the
field names of every result class an API serializes.

The corpus is stated inline, from literals, so it never depends on a fixture
module that a later gate could change.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2])
sys.path.insert(0, str(root / "src"))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from anchor.analysis.business_plan_analysis import analyze_quick_acquisition_with_business_plan  # noqa: E402
from anchor.business_plan import BusinessPlan  # noqa: E402
from anchor.capital_structure.contracts import (  # noqa: E402
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureUnit,
    DebtTerms,
    FixedAmount,
    FundingEvent,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    PositionFee,
    PositionScope,
    PreferredEquityTerms,
    ScopeKind,
    ShortfallResolution,
)
from anchor.capital_structure import execution_contracts  # noqa: E402
from anchor.capital_structure.execution import (  # noqa: E402
    execute_investment_capital_structure,
    execute_unit_capital_structure,
)
from anchor.consolidation.contracts import ConsolidationUnit  # noqa: E402
from anchor.consolidation.engine import consolidate  # noqa: E402
from anchor.contracts import AcquisitionInputs, acquisition_terms_from_inputs  # noqa: E402
from anchor.partnership.common_equity import execute_partnership  # noqa: E402
from _p7_9_fixtures import f1_terms  # noqa: E402  # accepted P7.9 shapes only

CEC = ShortfallResolution.COMMON_EQUITY_CONTRIBUTION


def quick(**overrides: object) -> tuple[object, object]:
    fields: dict[str, object] = {
        "purchase_price": 10_000_000.0,
        "current_noi": 800_000.0,
        "occupancy": 0.95,
        "noi_growth": 0.02,
        "hold_period": 5,
        "exit_cap_rate": 0.07,
        "ltv": 0.6,
        "interest_rate": 0.055,
        "amortization": 30,
        "acquisition_cost_pct": 0.01,
        "financing_fee_pct": 0.005,
        "disposition_cost_pct": 0.015,
        "annual_capex_reserve": 25_000.0,
        "io_period": 1,
    }
    fields.update(overrides)
    inputs = AcquisitionInputs(**fields)  # type: ignore[arg-type]
    return acquisition_terms_from_inputs(inputs), analyze_quick_acquisition_with_business_plan(inputs, business_plan=BusinessPlan())


def scope(unit_id: str | None) -> PositionScope:
    return PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id) if unit_id else PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None)


def debt(position_id: str, *, amount: object, priority: int, unit_id: str | None, rate: float, resolution: ShortfallResolution = CEC, fees: tuple[PositionFee, ...] = ()) -> CapitalPosition:
    return CapitalPosition(
        position_id=position_id,
        name=position_id,
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=priority,
        scope=scope(unit_id),
        funding=(FundingEvent(event_id=f"{position_id}-f", model_month=0, sequence=1, amount_rule=amount),),  # type: ignore[arg-type]
        terms=DebtTerms(
            interest_rate=rate, amortization=25, io_period=1, maturity_month=48, fees=fees, current_pay_rate=rate, pik_rate=0.0
        ),
        shortfall_resolution=resolution,
    )


def preferred(position_id: str, *, priority: int, unit_id: str | None) -> CapitalPosition:
    return CapitalPosition(
        position_id=position_id,
        name=position_id,
        position_class=PositionClass.PREFERRED_EQUITY,
        priority=priority,
        scope=scope(unit_id),
        funding=(FundingEvent(event_id=f"{position_id}-f", model_month=0, sequence=1, amount_rule=FixedAmount(amount=500_000.0)),),
        terms=PreferredEquityTerms(
            preferred_rate=0.10,
            current_pay_rate=0.06,
            accrual_permitted=True,
            accrual_convention=AccrualConvention.ANNUAL_COMPOUND,
            redemption_month=60,
        ),
        shortfall_resolution=CEC,
    )


def marker(unit_id: str | None) -> CapitalPosition:
    return CapitalPosition(
        position_id="common", name="Common", position_class=PositionClass.COMMON_EQUITY, priority=9,
        scope=scope(unit_id), funding=(), terms=None, shortfall_resolution=None,
    )


records: dict[str, str] = {}

terms, results = quick()
records["unit-none"] = repr(execute_unit_capital_structure(unit_id="u1", terms=terms, results=results))
records["unit-empty"] = repr(
    execute_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=CapitalStructure(positions=()))
)
stack = CapitalStructure(
    positions=(
        debt("mezz", amount=FixedAmount(amount=1_500_000.0), priority=2, unit_id="u1", rate=0.12,
             fees=(PositionFee(fee_id="mezz-fee", description="fee", amount=15_000.0, model_month=0, sequence=2),)),
        preferred("pref", priority=3, unit_id="u1"),
        marker("u1"),
    )
)
records["unit-stack"] = repr(execute_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=stack))
unresolved = CapitalStructure(
    positions=(debt("heavy", amount=PctOfPrice(pct=0.3), priority=2, unit_id="u1", rate=0.25, resolution=ShortfallResolution.UNRESOLVED),)
)
records["unit-unresolved"] = repr(
    execute_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=unresolved)
)

zero_terms, zero_results = quick(interest_rate=0.0, amortization=25, io_period=0, noi_growth=0.0, exit_cap_rate=0.064)
records["zero-rate-mezz"] = repr(
    execute_unit_capital_structure(
        unit_id="u1",
        terms=zero_terms,
        results=zero_results,
        capital_structure=CapitalStructure(positions=(debt("mezz", amount=FixedAmount(amount=1_000_000.0), priority=2, unit_id="u1", rate=0.1),)),
    )
)

structured = execute_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=stack)
records["partnership-stack"] = repr(execute_partnership(f1_terms(), structured))
records["partnership-unresolved"] = repr(
    execute_partnership(
        f1_terms(),
        execute_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=unresolved),
    )
)

units = []
for unit_id, overrides in (("a", {}), ("b", {"current_noi": 600_000.0, "ltv": 0.5})):
    unit_terms, unit_results = quick(**overrides)
    units.append(CapitalStructureUnit(unit_id=unit_id, terms=unit_terms, results=unit_results))
consolidated = consolidate(
    [ConsolidationUnit(unit_id=u.unit_id, purchase_price=u.terms.purchase_price, hold_period=u.terms.hold_period, results=u.results) for u in units],
    transaction_price=20_000_000.0,
)
investment_stack = CapitalStructure(
    positions=(
        debt("a-mezz", amount=FixedAmount(amount=800_000.0), priority=2, unit_id="a", rate=0.11),
        preferred("inv-pref", priority=1, unit_id=None),
        marker(None),
    )
)
records["investment-none"] = repr(execute_investment_capital_structure(units=units, consolidated=consolidated))
records["investment-stack"] = repr(
    execute_investment_capital_structure(units=units, consolidated=consolidated, capital_structure=investment_stack)
)

records["fields"] = repr(
    {
        cls.__name__: [field.name for field in dataclasses.fields(cls)]
        for cls in (
            CapitalStructure,
            execution_contracts.StructuredCapitalResult,
            execution_contracts.CommonEquityReturns,
            execution_contracts.PositionReturns,
            execution_contracts.ScheduledPosition,
            execution_contracts.ResolvedFundingEvent,
        )
    }
)
records["_pct_of_value_rule"] = repr(PctOfValue(timepoint_id="t", pct=0.5))

out.write_text(json.dumps(records, indent=1, sort_keys=True), encoding="utf-8")
