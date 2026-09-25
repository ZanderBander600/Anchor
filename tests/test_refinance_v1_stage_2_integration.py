"""Refinance & Capital Events V1 Stage 2 -- structured execution integration.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 12, 13 and 16. A
persisted refinance reaches the one accepted Stage 1 authority through the
existing structured-variant path, for every operating mode and both roots:

- Quick, Detailed and Lease-Level Deals execute a DSCR-sized refinance of their
  acquisition loan through the engine's balance service, and the bridge
  conserves (INV-2) -- read from the engine, never recomputed here;
- a visible Investment executes a Unit event in its own scope, and the other
  Unit's positions are exactly what they are without it (INV-1);
- the Partnership consumes only the resulting Common Equity series;
- the Project result is identical with and without the event (P-4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, detailed_deal, lease_level_deal  # type: ignore[import-not-found]
from _p7_9_fixtures import f1_terms  # type: ignore[import-not-found]
from anchor.capital_structure.refinance_contracts import PayoffAuthority, RefinanceStatus
from anchor.deals import store
from anchor.deals.partnership_variants import analyze_partnership_variant
from anchor.deals.structured_variants import analyze_structured_variant


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def _conserves(event: Any) -> None:
    bridge = event.bridge
    total = bridge.payoffs + bridge.replacement_lender_fees + bridge.retiring_lender_fees + bridge.third_party_costs
    assert fx.rf.close(bridge.gross_proceeds, total + bridge.net_event_cash)


@pytest.mark.parametrize("mode", ["quick", "detailed", "lease_level"])
def test_every_mode_executes_through_the_one_stage_1_authority(db: Path, mode: str) -> None:
    deal = {
        "quick": lambda: fx.base_deal(db),
        "detailed": lambda: detailed_deal(db),
        "lease_level": lambda: lease_level_deal(db),
    }[mode]()
    before_id, _ = store.set_deal_capital_structure(deal.id, fx.closing_mezz_only(deal.id), db_path=db)
    plain = analyze_structured_variant(before_id, "base", "base", db_path=db)  # type: ignore[arg-type]

    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.evented(deal.id, dscr=1.25), db_path=db)
    analysis = analyze_structured_variant(investment_id, "base", "base", db_path=db)  # type: ignore[arg-type]
    (event,) = analysis.result.capital_events
    assert event.status is RefinanceStatus.EXECUTED, (mode, event.unavailable_reason, event.unavailable_message)
    (payoff,) = event.payoffs
    assert payoff.payoff_authority is PayoffAuthority.ACQUISITION_DEBT_BALANCE_SERVICE
    _conserves(event)
    # The refinance is downstream of the Project: its result and identity are untouched.
    assert analysis.project_source_fingerprint == plain.project_source_fingerprint


def test_a_visible_investment_executes_a_unit_event_in_its_own_scope(db: Path) -> None:
    a = fx.base_deal(db, name="A")
    b = fx.base_deal(db, name="B", current_noi=600_000.0)
    investment = create_investment(db, a, b)
    other = fx.fixed_closing("b-mezz", b.id, 500_000.0)

    store.set_base_capital_structure(investment.id, fx.plain(other), db_path=db)
    without = analyze_structured_variant(investment.id, "base", "base", db_path=db)

    structure = fx.evented(a.id, other, dscr=2.0)
    store.set_base_capital_structure(investment.id, structure, db_path=db)
    analysis = analyze_structured_variant(investment.id, "base", "base", db_path=db)
    (event,) = analysis.result.capital_events
    assert event.status is RefinanceStatus.EXECUTED and event.scope == fx.scope(a.id)
    assert fx.rf.close(event.sizing.gross_proceeds, 8_000_000)
    _conserves(event)
    (b_without,) = [position for position in without.result.positions if position.position_id == "b-mezz"]
    (b_with,) = [position for position in analysis.result.positions if position.position_id == "b-mezz"]
    assert b_with == b_without
    assert analysis.project_source_fingerprint == without.project_source_fingerprint


def test_the_partnership_consumes_only_the_common_equity_series(db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.evented(deal.id, dscr=2.0), db_path=db)
    assert investment_id is not None
    store.set_deal_partnership(deal.id, f1_terms(), db_path=db)
    structured = analyze_structured_variant(investment_id, "base", "base", db_path=db)
    partnership = analyze_partnership_variant(investment_id, "base", "base", db_path=db)
    assert partnership.result is not None
    cash = structured.result.common_equity.cash_flows
    assert cash is not None and partnership.result.periods is not None
    assert [record.common_equity_cash_flow for record in partnership.result.periods] == list(cash)
    for record in partnership.result.periods:
        assert fx.rf.close(record.total_distributions - record.total_contributions, cash[record.period]), record.period
