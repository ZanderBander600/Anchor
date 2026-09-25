"""Shared Refinance & Capital Events V1 Stage 2 fixtures (not a test module).

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 13, 14, 16 and 18.
Saved Deals and Investments carrying the Section 18.1 base case, builders for
persisted refinance structures, valuation definitions and memo drafts, and raw
database readers. Everything goes through the real store, the real contracts
and the real engine, so a claim about persistence, identity or staleness is
measured rather than asserted by the code that makes it.

Expected figures are the contract's own hand arithmetic (Section 18), never a
value read back from the code under test.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path
from typing import Any

import _refinance_v1_fixtures as rf  # type: ignore[import-not-found]
from _p7_8_fixtures import round_deal  # type: ignore[import-not-found]

from anchor.capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    FixedAmount,
    FundingEvent,
    PositionClass,
    PositionScope,
    ScopeKind,
)
from anchor.capital_structure.events import (
    AuthoredPositionRef,
    CapitalStructureWithEvents,
    LegacyAcquisitionLoanRef,
    RefinanceEvent,
)
from anchor.deals import store
from anchor.valuation.contracts import (
    AnalystValue,
    DirectCap,
    UnitValuationInstruction,
    ValuationKind,
    ValuationTimepoint,
)

EVENT_ID = rf.EVENT_ID
REPLACEMENT_ID = rf.REPLACEMENT_ID
TIMEPOINT_ID = rf.TIMEPOINT_ID
EVENT_MONTH = rf.EVENT_MONTH

#: Section 18.1 as a saved Quick Deal: $800,000 flat NOI, a $6,000,000
#: acquisition loan at 0% over 25 years, and a 6.4% exit cap.
BASE_CASE = {"interest_rate": 0.0, "amortization": 25, "io_period": 0, "exit_cap_rate": 0.064}

#: Every capital-event table schema 17 adds (the seventh, the memo version's
#: consumed-valuation record, is not a Capital Structure child).
STAGE_2_TABLES = (
    "capital_events",
    "capital_event_retirements",
    "capital_event_constraints",
    "capital_event_valuation_refs",
    "capital_event_costs",
    "capital_refinance_proceeds",
)


def base_deal(db: Path, *, name: str = "Refinance unit", **overrides: Any) -> Any:
    return round_deal(db, name=name, **{**BASE_CASE, **overrides})


def scope(unit_id: str) -> PositionScope:
    return PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id)


def legacy(unit_id: str) -> LegacyAcquisitionLoanRef:
    return LegacyAcquisitionLoanRef(unit_id=unit_id)


def unit_event(unit_id: str, **kwargs: Any) -> RefinanceEvent:
    """The base refinance of ``unit_id``: at model month 24, retiring that Unit's
    acquisition loan unless told otherwise."""

    kwargs.setdefault("retiring", (legacy(unit_id),))
    kwargs.setdefault("scope", scope(unit_id))
    return rf.event(**kwargs)


def unit_replacement(unit_id: str, **kwargs: Any) -> CapitalPosition:
    kwargs.setdefault("scope", scope(unit_id))
    return rf.replacement(**kwargs)


def evented(unit_id: str, *extra: CapitalPosition, replacement_fees: tuple = (), **event_kwargs: Any) -> CapitalStructureWithEvents:
    """The base replacement plus any ``extra`` positions, with one event."""

    replacement_id = event_kwargs.get("replacement_id", REPLACEMENT_ID)
    event_id = event_kwargs.get("event_id", EVENT_ID)
    month = event_kwargs.get("month", EVENT_MONTH)
    return CapitalStructureWithEvents(
        positions=(
            unit_replacement(
                unit_id, position_id=replacement_id, event_id=event_id, month=month, fees=replacement_fees
            ),
            *extra,
        ),
        events=(unit_event(unit_id, **event_kwargs),),
    )


def mezz(unit_id: str, *, position_id: str = "mezz", amount: float = 500_000.0, priority: int = 2) -> CapitalPosition:
    return rf.closing_debt(position_id, amount=amount, priority=priority, rate=0.10, scope=scope(unit_id))


def full_member_structure(unit_id: str) -> CapitalStructureWithEvents:
    """One event stating every Stage 1 member: two retiring references of both
    kinds, all three constraints, the LTV valuation reference, all three cost
    shapes and a replacement lender fee at the event month."""

    return evented(
        unit_id,
        mezz(unit_id),
        replacement_fees=(rf.lender_fee(80_000.0),),
        fixed=7_500_000.0,
        ltv=0.65,
        dscr=2.0,
        retiring=(legacy(unit_id), AuthoredPositionRef(position_id="mezz")),
        costs=(
            rf.third_party(40_000.0),
            rf.exit_fee(30_000.0, legacy(unit_id)),
            rf.exit_fee(10_000.0, AuthoredPositionRef(position_id="mezz"), cost_id="mezz-exit"),
        ),
    )


def value_timepoint(
    unit_id: str,
    *,
    timepoint_id: str = TIMEPOINT_ID,
    cap_rate: float = 0.064,
    month: int = EVENT_MONTH,
    label: str = "Year-2 value",
    method: Any = None,
) -> ValuationTimepoint:
    """The Section 18.1 CUSTOM timepoint: 6.4% direct cap at month 24, so
    ``V = 800,000 / 0.064 = 12,500,000``."""

    return ValuationTimepoint(
        timepoint_id=timepoint_id,
        investment_id="",
        kind=ValuationKind.CUSTOM,
        label=label,
        model_month=month,
        unit_instructions=(
            UnitValuationInstruction(unit_id=unit_id, method=method or DirectCap(cap_rate=cap_rate)),
        ),
    )


def analyst_value(amount: float = 12_500_000.0, evidence_id: str = "appraisal-1") -> AnalystValue:
    return AnalystValue(amount=amount, evidence_id=evidence_id)


def with_timepoint(db: Path, investment_id: str, timepoint: ValuationTimepoint) -> ValuationTimepoint:
    return store.create_valuation_timepoint(
        investment_id, dataclasses.replace(timepoint, investment_id=investment_id), db_path=db
    )


def replace_timepoint(db: Path, investment_id: str, timepoint: ValuationTimepoint, **changes: Any) -> ValuationTimepoint:
    return store.update_valuation_timepoint(
        investment_id, dataclasses.replace(timepoint, investment_id=investment_id, **changes), db_path=db
    )


def plain(*positions: CapitalPosition) -> CapitalStructure:
    return CapitalStructure(positions=tuple(positions))


def closing_mezz_only(unit_id: str) -> CapitalStructure:
    return plain(mezz(unit_id))


def fixed_closing(position_id: str, unit_id: str, amount: float) -> CapitalPosition:
    return CapitalPosition(
        position_id=position_id,
        name=position_id,
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=2,
        scope=scope(unit_id),
        funding=(FundingEvent(event_id=f"{position_id}-f", model_month=0, sequence=1, amount_rule=FixedAmount(amount=amount)),),
        terms=rf.cash_pay_debt(rate=0.1, amortization=30, io_period=0, maturity_month=120),
        shortfall_resolution=rf.CEC,
    )


# =============================================================================
# Reading and writing the database directly
# =============================================================================


def connect(db: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    return connection


def rows(db: Path, table: str) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(db)
    try:
        return list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid"))
    finally:
        connection.close()


def execute(db: Path, sql: str, parameters: tuple[Any, ...] = ()) -> None:
    connection = sqlite3.connect(db)
    try:
        with connection:
            connection.execute(sql, parameters)
    finally:
        connection.close()


def event_rows(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {table: rows(db, table) for table in STAGE_2_TABLES}
