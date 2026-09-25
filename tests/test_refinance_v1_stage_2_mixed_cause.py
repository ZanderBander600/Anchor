"""Refinance & Capital Events V1 Stage 2 -- Investment-scope reason precedence
(third review correction).

An Investment value is incomplete when any member cell has no value. Evidence
approval is its reported cause **only** when every unavailable member cell is
withheld for evidence. When another Unit is unavailable for another reason, the
Investment keeps ``valuation_unavailable`` / ``incomplete_units`` and its
message says approving evidence alone will not resolve it. Each member cell
keeps its own precise typed reason, and a Unit-scoped consumer reads its own
cell alone.

The world: one visible two-Unit Investment and one shared timepoint.

- Unit A is valued by direct capitalisation, and its forward NOI is zero, so
  its cell is ``non_positive_forward_noi``.
- Unit B's value is analyst-supplied, and its evidence is unapproved, so its
  cell is ``evidence_not_approved``.

Repairing A's NOI, and approving B's evidence, are the two independent fixes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

import _p7_10_stage_2_fixtures as memo_fx  # type: ignore[import-not-found]
import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment  # type: ignore[import-not-found]
from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain
from anchor.capital_structure.contracts import PctOfValue
from anchor.capital_structure.refinance_contracts import (
    ConstraintKind,
    RefinanceStatus,
    RefinanceUnavailableReason,
)
from anchor.deals import store
from anchor.deals.structured_variants import analyze_structured_valuations, analyze_structured_variant
from anchor.memo.availability import AvailabilityStatus, UnavailableReasonCode
from anchor.valuation.contracts import ValuationUnavailableReason
from test_refinance_v1_stage_2_exact_scope import (  # type: ignore[import-not-found]
    AS_IS,
    EVIDENCE,
    INVESTMENT_SCOPE,
    TIMEPOINT,
    _investment_refinance,
    _pct_of_value,
    _senior,
    _timepoint,
    _unit_refinance,
)

#: Unit A's repaired forward NOI and its direct-cap value (800,000 / 0.064).
A_NOI = 800_000.0
B_AMOUNT = 12_500_000.0


def build_mixed(db: Path) -> dict[str, Any]:
    a = fx.base_deal(db, name="A", ltv=0.0, current_noi=0.0)
    b = fx.base_deal(db, name="B", ltv=0.0)
    investment = create_investment(db, a, b)
    store.put_evidence_reference(
        investment.id, memo_fx.evidence(investment.id, evidence_id=EVIDENCE, approved=False), db_path=db
    )
    fx.with_timepoint(db, investment.id, _timepoint(a.id, b.id, timepoint_id=TIMEPOINT, month=24))
    fx.with_timepoint(db, investment.id, _timepoint(a.id, b.id, timepoint_id=AS_IS, month=0))

    def strategy(name: str, structure: Any) -> str:
        return store.create_strategy(
            investment.id,
            name=name,
            root_overlays=(InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=structure),),
            db_path=db,
        ).strategy.strategy_id

    return {
        "db": db,
        "investment_id": investment.id,
        "a": a.id,
        "b": b.id,
        "portfolio": strategy("Refinance the portfolio", _investment_refinance()),
        "unit_a": strategy("Refinance A", _unit_refinance(a.id, "a")),
        "unit_b": strategy("Refinance B", _unit_refinance(b.id, "b")),
        "pct_inv": strategy(
            "Value-sized portfolio",
            fx.plain(_senior("sen-pi", INVESTMENT_SCOPE, 0.0, PctOfValue(timepoint_id=AS_IS, pct=0.4))),
        ),
        "pct_a": strategy("Value-sized A", _pct_of_value(a.id, "pa")),
        "pct_b": strategy("Value-sized B", _pct_of_value(b.id, "pb")),
    }


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    return build_mixed(tmp_path / "anchor.db")


def _approve(world: dict[str, Any]) -> None:
    store.put_evidence_reference(
        world["investment_id"],
        memo_fx.evidence(world["investment_id"], evidence_id=EVIDENCE, approved=True),
        db_path=world["db"],
    )


def _repair_a(world: dict[str, Any]) -> None:
    deal = store.get_deal(world["a"], db_path=world["db"])
    assert deal.inputs is not None
    store.update_deal(
        world["a"],
        deal.name,
        dataclasses.replace(deal.inputs, current_noi=A_NOI),
        business_plan=deal.business_plan,
        db_path=world["db"],
    )


def _event(world: dict[str, Any], strategy: str) -> Any:
    (event,) = _analysis(world, strategy).result.capital_events
    return event


def _analysis(world: dict[str, Any], strategy: str) -> Any:
    return analyze_structured_variant(world["investment_id"], world[strategy], "base", db_path=world["db"])


def _ltv(event: Any) -> Any:
    return next(capacity for capacity in event.sizing.capacities if capacity.kind is ConstraintKind.MAX_LTV)


def _funding(world: dict[str, Any], strategy: str) -> Any:
    (state,) = analyze_structured_valuations(world["investment_id"], world[strategy], "base", db_path=world["db"]).funding_states
    return state


def _gated_cells(world: dict[str, Any], strategy: str) -> tuple[Any, dict[str, Any]]:
    """The gated Investment result at ``TIMEPOINT`` and its cells by Unit."""

    from anchor.deals.valuation_views import funding_authority

    surface = analyze_structured_valuations(world["investment_id"], world[strategy], "base", db_path=world["db"])
    blocked = {record.timepoint_id: {unit.unit_id: unit.detail for unit in record.units} for record in surface.evidence_blocked}
    authority = funding_authority(investment_id=world["investment_id"], views=surface.views, blocked=blocked)
    valuation = next(item for item in authority.valuations if item.timepoint_id == TIMEPOINT)
    return valuation, {cell.unit_id: cell for cell in valuation.unit_results}


def _forbidden(world: dict[str, Any]) -> tuple[str, ...]:
    return (
        world["a"], world["b"], world["investment_id"], EVIDENCE, TIMEPOINT, AS_IS,
        "event-inv", "refi-inv", "sen-inv", "sen-pi", "sen-pi/funding",
        "12,500,000", "12500000", "5,000,000", "5000000",
    )


def _messages(world: dict[str, Any], strategy: str) -> list[str]:
    result = _analysis(world, strategy).result
    texts = [event.unavailable_message for event in result.capital_events]
    texts += [capacity.unavailable_message for event in result.capital_events if event.sizing for capacity in event.sizing.capacities]
    texts += [position.unavailable_message for position in result.positions]
    texts += [position.unavailable_message for position in result.unexecuted_positions]
    texts.append(result.common_equity.unavailable_message)
    return [text for text in texts if text]


def _is_mixed(event: Any) -> None:
    """The mixed-cause state: every reason kept, and a sentence that never
    implies evidence approval alone would resolve it."""

    assert event.status is RefinanceStatus.UNAVAILABLE
    assert event.unavailable_reason is RefinanceUnavailableReason.VALUATION_UNAVAILABLE
    assert _ltv(event).unavailable_reason is RefinanceUnavailableReason.VALUATION_UNAVAILABLE
    assert event.value_dependency.valuation_unavailable_reason is ValuationUnavailableReason.INCOMPLETE_UNITS
    assert event.value_dependency.value is None and event.sizing.gross_proceeds is None
    for text in (event.unavailable_message, _ltv(event).unavailable_message):
        assert "incomplete for more than one reason" in text and "evidence alone will not" in text, text
        assert "Review each Unit's valuation state" in text, text


# =============================================================================
# The mixed cause: non-positive NOI in A, unapproved evidence in B
# =============================================================================


def test_each_member_cell_keeps_its_own_precise_reason(world: dict[str, Any]) -> None:
    valuation, cells = _gated_cells(world, "portfolio")
    assert cells[world["a"]].unavailable_reason is ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI
    assert cells[world["b"]].unavailable_reason is ValuationUnavailableReason.EVIDENCE_NOT_APPROVED
    assert valuation.unavailable_reason is ValuationUnavailableReason.INCOMPLETE_UNITS and valuation.value is None
    # The Investment sentence matches the gated cells: neither Stage 1's
    # pre-gate prose nor an evidence-only claim, and no identity.
    assert "incomplete for more than one reason" in valuation.unavailable_message
    for token in _forbidden(world):
        assert token not in valuation.unavailable_message, token


def test_an_investment_ltv_event_is_valuation_unavailable_not_evidence_only(world: dict[str, Any]) -> None:
    _is_mixed(_event(world, "portfolio"))


def test_an_investment_pct_of_value_follows_the_same_precedence(world: dict[str, Any]) -> None:
    state = _funding(world, "pct_inv")
    assert state.status is AvailabilityStatus.UNAVAILABLE and state.amount is None
    assert state.unavailable.reason_code is UnavailableReasonCode.FUNDING_REQUIREMENT_UNRESOLVED
    assert state.unavailable.valuation_reason is ValuationUnavailableReason.INCOMPLETE_UNITS
    assert "incomplete for more than one reason" in state.unavailable.reason
    assert "evidence alone will not" in state.unavailable.reason


def test_approving_b_alone_resolves_neither_and_keeps_the_mixed_cause_away(world: dict[str, Any]) -> None:
    """With B approved, A is the sole cause and it is not evidence: nothing
    resolves, and nothing claims evidence as the cause or reports a value."""

    _approve(world)
    event = _event(world, "portfolio")
    assert event.status is RefinanceStatus.UNAVAILABLE
    assert event.unavailable_reason is RefinanceUnavailableReason.VALUATION_UNAVAILABLE
    assert _ltv(event).unavailable_reason is RefinanceUnavailableReason.VALUATION_UNAVAILABLE
    assert event.value_dependency.valuation_unavailable_reason is ValuationUnavailableReason.INCOMPLETE_UNITS
    assert "approved Evidence Reference" not in event.unavailable_message
    state = _funding(world, "pct_inv")
    assert state.status is AvailabilityStatus.UNAVAILABLE and state.amount is None
    assert state.unavailable.reason_code is not UnavailableReasonCode.EVIDENCE_NOT_APPROVED


def test_repairing_a_while_b_is_blocked_makes_evidence_the_sole_cause(world: dict[str, Any]) -> None:
    _repair_a(world)
    event = _event(world, "portfolio")
    assert event.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    assert _ltv(event).unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    assert event.value_dependency.valuation_unavailable_reason is ValuationUnavailableReason.INCOMPLETE_UNITS
    state = _funding(world, "pct_inv")
    assert state.unavailable.reason_code is UnavailableReasonCode.EVIDENCE_NOT_APPROVED
    valuation, _ = _gated_cells(world, "portfolio")
    assert "approved Evidence Reference" in valuation.unavailable_message
    assert "more than one reason" not in valuation.unavailable_message


def test_both_fixes_make_the_investment_value_available(world: dict[str, Any]) -> None:
    _repair_a(world)
    _approve(world)
    event = _event(world, "portfolio")
    assert event.status is RefinanceStatus.EXECUTED
    assert fx.rf.close(event.value_dependency.value, A_NOI / 0.064 + B_AMOUNT)
    state = _funding(world, "pct_inv")
    assert state.status is AvailabilityStatus.AVAILABLE
    assert fx.rf.close(state.amount, 0.4 * (A_NOI / 0.064 + B_AMOUNT))


def test_unit_scoped_consumers_keep_their_exact_cell(world: dict[str, Any]) -> None:
    """A's own reason is A's; B's own reason is B's. Neither is the other's."""

    event_a, event_b = _event(world, "unit_a"), _event(world, "unit_b")
    assert event_a.unavailable_reason is RefinanceUnavailableReason.VALUATION_UNAVAILABLE
    assert event_a.value_dependency.valuation_unavailable_reason is ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI
    assert event_b.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    assert event_b.value_dependency.valuation_unavailable_reason is ValuationUnavailableReason.EVIDENCE_NOT_APPROVED
    assert _funding(world, "pct_a").unavailable.valuation_reason is ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI
    assert _funding(world, "pct_b").unavailable.reason_code is UnavailableReasonCode.EVIDENCE_NOT_APPROVED
    _approve(world)
    assert _event(world, "unit_b").status is RefinanceStatus.EXECUTED
    assert _event(world, "unit_a").value_dependency.valuation_unavailable_reason is ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI


def test_no_mixed_or_evidence_message_names_an_amount_or_an_identity(world: dict[str, Any]) -> None:
    texts = _messages(world, "portfolio") + [_funding(world, "pct_inv").unavailable.reason]
    texts.append(_funding(world, "pct_b").unavailable.reason)
    _repair_a(world)
    texts += _messages(world, "portfolio") + [_funding(world, "pct_inv").unavailable.reason]
    for text in texts:
        for token in _forbidden(world):
            assert token not in text, (token, text)


def test_every_unavailable_member_evidence_blocked_is_evidence_not_approved(tmp_path: Path) -> None:
    """The existing exact-scope world: A available, only B withheld."""

    from test_refinance_v1_stage_2_exact_scope import build  # type: ignore[import-not-found]

    world = build(tmp_path / "anchor.db")
    event = _event(world, "portfolio")
    assert event.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    assert _ltv(event).unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
