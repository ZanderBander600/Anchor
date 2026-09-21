"""Shared P7.10 Stage 1 fixtures (not a test module).

Round-number valuation definitions and hand-checkable variant inputs. The
expected values the golden cases assert are written here and in the tests from
the *stated* economics -- a flat or compounding NOI the reader can multiply out
-- never by calling ``anchor.valuation``. No helper in this file imports the
resolution it is used to check.
"""

from __future__ import annotations

from typing import Any

from anchor.valuation.contracts import (
    AnalystValue,
    DirectCap,
    UnitValuationInstruction,
    ValuationKind,
    ValuationMethod,
    ValuationTimepoint,
    ValuationUnitInputs,
    ValuationVariantInputs,
)

INVESTMENT_ID = "inv-1"

#: The round-number Unit these fixtures value: a five-year hold whose NOI is
#: $800,000 in Year 1 and compounds at 10%. Years 1..5 are therefore
#: 800,000; 880,000; 968,000; 1,064,800; 1,171,280, and Year 6 -- the exit NOI,
#: never a member of ``noi_by_year`` -- is 1,288,408. At an 8% exit cap the
#: exit value is 16,105,100.
BASE_NOI = 800_000.0
GROWTH = 0.10
HOLD = 5
EXIT_CAP = 0.08


def hand_noi_by_year(*, base: float = BASE_NOI, growth: float = GROWTH, hold: int = HOLD) -> tuple[float, ...]:
    """Years 1..H, compounded by hand. Independent of the engine."""

    return tuple(base * (1.0 + growth) ** year for year in range(hold))


def hand_exit_noi(*, base: float = BASE_NOI, growth: float = GROWTH, hold: int = HOLD) -> float:
    """Year H+1, compounded by hand."""

    return base * (1.0 + growth) ** hold


def unit(
    unit_id: str = "u1",
    *,
    hold: int = HOLD,
    noi_by_year: tuple[float, ...] | None = None,
    exit_noi: float | None = None,
    exit_cap: float = EXIT_CAP,
    exit_value: float | None = None,
    disposition_costs: float = 0.0,
    net_sale_proceeds: float | None = None,
) -> ValuationUnitInputs:
    """One Unit's valuation inputs, stated directly. Nothing is derived from
    the valuation layer."""

    years = hand_noi_by_year(hold=hold) if noi_by_year is None else noi_by_year
    terminal = hand_exit_noi(hold=hold) if exit_noi is None else exit_noi
    value = terminal / exit_cap if exit_value is None else exit_value
    return ValuationUnitInputs(
        unit_id=unit_id,
        hold_period=hold,
        noi_by_year=years,
        exit_noi=terminal,
        exit_cap_rate=exit_cap,
        exit_value=value,
        disposition_costs=disposition_costs,
        net_sale_proceeds=value - disposition_costs if net_sale_proceeds is None else net_sale_proceeds,
    )


def variant(*units: ValuationUnitInputs, investment_id: str = INVESTMENT_ID) -> ValuationVariantInputs:
    """The variant inputs, built without the package's own canonicaliser so a
    test can assert that ordering is imposed by the resolution, not by us."""

    holds = {member.hold_period for member in units}
    (hold,) = holds
    return ValuationVariantInputs(investment_id=investment_id, hold_period=hold, units=units)


def cap(rate: float = 0.06) -> DirectCap:
    return DirectCap(cap_rate=rate)


def stated(amount: float = 12_500_000.0, evidence_id: str = "ev-1") -> AnalystValue:
    return AnalystValue(amount=amount, evidence_id=evidence_id)


def instruction(unit_id: str = "u1", method: ValuationMethod | None = None) -> UnitValuationInstruction:
    return UnitValuationInstruction(unit_id=unit_id, method=cap() if method is None else method)


def timepoint(
    timepoint_id: str = "as-is",
    *,
    investment_id: str = INVESTMENT_ID,
    kind: ValuationKind = ValuationKind.AS_IS,
    label: str = "As-Is",
    model_month: int = 0,
    instructions: tuple[UnitValuationInstruction, ...] | None = None,
    **overrides: Any,
) -> ValuationTimepoint:
    return ValuationTimepoint(
        timepoint_id=overrides.get("timepoint_id", timepoint_id),
        investment_id=investment_id,
        kind=kind,
        label=label,
        model_month=model_month,
        unit_instructions=(instruction(),) if instructions is None else instructions,
    )


def stabilized(
    *, model_month: int = 24, instructions: tuple[UnitValuationInstruction, ...] | None = None
) -> ValuationTimepoint:
    return timepoint(
        "stabilized",
        kind=ValuationKind.STABILIZED,
        label="Stabilized",
        model_month=model_month,
        instructions=instructions,
    )


__all__ = [
    "BASE_NOI",
    "EXIT_CAP",
    "GROWTH",
    "HOLD",
    "INVESTMENT_ID",
    "cap",
    "hand_exit_noi",
    "hand_noi_by_year",
    "instruction",
    "stabilized",
    "stated",
    "timepoint",
    "unit",
    "variant",
]
