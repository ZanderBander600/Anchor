"""Refinance & Capital Events V1 Stage 2 -- exact-scope valuation dependencies
(review correction).

P7.10 Section 6 and R-E; Refinance V1 Sections 8.1, 14.1 and 14.3; F15 and
INV-1. A value dependency is resolved for its consumer's **exact scope**, so
evidence approval is cell-scoped:

- a Unit-scoped LTV event depends only on its own Unit's cell and evidence;
- an Investment-scoped LTV event depends on the complete Investment value;
- a Unit-scoped ``PctOfValue`` funding follows the same rule;
- a DSCR-only or fixed event depends on no valuation at all.

One visible two-Unit Investment shares one timepoint: Unit A has an available
direct-cap value, Unit B an analyst-supplied value whose evidence is
unapproved. Neither Unit carries an acquisition loan, so each refinance
retires an authored senior loan and an Investment-scope refinance is
admissible.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

import _p7_10_stage_2_fixtures as memo_fx  # type: ignore[import-not-found]
import _refinance_v1_fixtures as rf  # type: ignore[import-not-found]
import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment  # type: ignore[import-not-found]
from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain
from anchor.capital_structure import refinance as cs_refinance
from anchor.capital_structure import refinance_execution as cs_refinance_execution
from anchor.capital_structure.contracts import (
    CapitalPosition,
    PctOfValue,
    PositionClass,
    PositionScope,
    ScopeKind,
)
from anchor.capital_structure.events import AuthoredPositionRef, CapitalStructureWithEvents
from anchor.capital_structure.refinance_contracts import RefinanceStatus, RefinanceUnavailableReason
from anchor.deals import memo_dependencies as deps
from anchor.deals import store
from anchor.deals.structured_variants import (
    analyze_structured_valuations,
    analyze_structured_variant,
    structured_variant_fingerprint,
)
from anchor.memo.availability import AvailabilityStatus
from anchor.memo.publication import PublicationRefusedError
from anchor.valuation.contracts import (
    DirectCap,
    UnitValuationInstruction,
    ValuationKind,
    ValuationTimepoint,
)

INVESTMENT_SCOPE = PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None)
TIMEPOINT = fx.TIMEPOINT_ID
AS_IS = "as-is"
EVIDENCE = "appraisal-b"
B_AMOUNT = 12_500_000.0


def _senior(position_id: str, scope: PositionScope, amount: float, rule: Any = None) -> CapitalPosition:
    position = rf.closing_debt(
        position_id, amount=amount, priority=1, rate=0.05, position_class=PositionClass.SENIOR_DEBT, scope=scope
    )
    if rule is None:
        return position
    (funding,) = position.funding
    return dataclasses.replace(position, funding=(dataclasses.replace(funding, amount_rule=rule),))


def _unit_refinance(unit_id: str, tag: str, **sizing: Any) -> CapitalStructureWithEvents:
    sizing = sizing or {"ltv": 0.65}
    return CapitalStructureWithEvents(
        positions=(
            _senior(f"sen-{tag}", fx.scope(unit_id), 4_000_000.0),
            fx.unit_replacement(unit_id, position_id=f"refi-{tag}", event_id=f"event-{tag}"),
        ),
        events=(
            fx.unit_event(
                unit_id,
                event_id=f"event-{tag}",
                replacement_id=f"refi-{tag}",
                retiring=(AuthoredPositionRef(position_id=f"sen-{tag}"),),
                label=f"Refinance {tag.upper()}",
                **sizing,
            ),
        ),
    )


def _investment_refinance() -> CapitalStructureWithEvents:
    return CapitalStructureWithEvents(
        positions=(
            _senior("sen-inv", INVESTMENT_SCOPE, 8_000_000.0),
            rf.replacement("refi-inv", event_id="event-inv", scope=INVESTMENT_SCOPE),
        ),
        events=(
            rf.event(
                ltv=0.65,
                event_id="event-inv",
                replacement_id="refi-inv",
                scope=INVESTMENT_SCOPE,
                retiring=(AuthoredPositionRef(position_id="sen-inv"),),
                label="Portfolio refinance",
            ),
        ),
    )


def _pct_of_value(unit_id: str, tag: str) -> Any:
    return fx.plain(_senior(f"sen-{tag}", fx.scope(unit_id), 0.0, PctOfValue(timepoint_id=AS_IS, pct=0.4)))


def _timepoint(a: str, b: str, *, timepoint_id: str, month: int, b_amount: float = B_AMOUNT, a_cap: float = 0.064) -> ValuationTimepoint:
    return ValuationTimepoint(
        timepoint_id=timepoint_id,
        investment_id="",
        kind=ValuationKind.CUSTOM if month else ValuationKind.AS_IS,
        label="Year-2 value" if month else "As-Is",
        model_month=month,
        unit_instructions=(
            UnitValuationInstruction(unit_id=a, method=DirectCap(cap_rate=a_cap)),
            UnitValuationInstruction(unit_id=b, method=fx.analyst_value(b_amount, evidence_id=EVIDENCE)),
        ),
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def build(db: Path) -> dict[str, Any]:
    """The two-Unit Investment, its shared timepoints, B's unapproved evidence
    and one Strategy per consumer."""

    a = fx.base_deal(db, name="A", ltv=0.0)
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
        "unit_a": strategy("Refinance A", _unit_refinance(a.id, "a")),
        "unit_b": strategy("Refinance B", _unit_refinance(b.id, "b")),
        "portfolio": strategy("Refinance the portfolio", _investment_refinance()),
        "dscr_a": strategy("DSCR A", _unit_refinance(a.id, "d", dscr=2.0)),
        "pct_a": strategy("Value-sized A", _pct_of_value(a.id, "pa")),
        "pct_b": strategy("Value-sized B", _pct_of_value(b.id, "pb")),
    }


@pytest.fixture
def world(db: Path) -> dict[str, Any]:
    return build(db)


def _analysis(world: dict[str, Any], strategy: str) -> Any:
    return analyze_structured_variant(world["investment_id"], strategy, "base", db_path=world["db"])


def _event(world: dict[str, Any], strategy: str) -> Any:
    (event,) = _analysis(world, strategy).result.capital_events
    return event


def _fingerprint(world: dict[str, Any], strategy: str) -> str:
    return structured_variant_fingerprint(world["investment_id"], strategy, "base", db_path=world["db"]).structured_source_fingerprint


def _approve(world: dict[str, Any], approved: bool = True) -> None:
    store.put_evidence_reference(
        world["investment_id"],
        memo_fx.evidence(world["investment_id"], evidence_id=EVIDENCE, approved=approved),
        db_path=world["db"],
    )


def _change_b(world: dict[str, Any], amount: float) -> None:
    for timepoint_id, month in ((TIMEPOINT, 24), (AS_IS, 0)):
        fx.replace_timepoint(
            world["db"], world["investment_id"], _timepoint(world["a"], world["b"], timepoint_id=timepoint_id, month=month, b_amount=amount)
        )


def _valuation_refusals(world: dict[str, Any], strategy: str) -> list[Any]:
    investment_id, db = world["investment_id"], world["db"]
    store.put_memo_draft(investment_id, memo_fx.memo_draft(investment_id, selected=memo_fx.project_cell(strategy_id=strategy)), db_path=db)
    draft = store.get_memo_draft(investment_id, db_path=db)
    assert draft is not None and draft.selected_decision is not None
    refusals = deps.publication_refusals_for(
        investment_id, draft, deps.dependency_set(investment_id, draft.selected_decision, draft=draft, db_path=db), db_path=db
    )
    return [item for item in refusals if item.code.value == "valuation_unavailable_for_required_view"]


def _analyst_messages(analysis: Any) -> list[str]:
    result = analysis.result
    texts = [event.unavailable_message for event in result.capital_events]
    texts += [capacity.unavailable_message for event in result.capital_events if event.sizing for capacity in event.sizing.capacities]
    texts += [position.unavailable_message for position in result.positions]
    texts += [position.unavailable_message for position in result.unexecuted_positions]
    texts.append(result.common_equity.unavailable_message)
    return [text for text in texts if text]


# =============================================================================
# 1-3. Unit A: executes, is independent of Unit B, and publishes
# =============================================================================


def test_1_a_unit_a_ltv_refinance_executes_beside_a_blocked_unit_b(world: dict[str, Any]) -> None:
    event = _event(world, world["unit_a"])
    assert event.status is RefinanceStatus.EXECUTED
    assert event.value_dependency is not None and fx.rf.close(event.value_dependency.value, 12_500_000)
    assert fx.rf.close(event.sizing.gross_proceeds, 0.65 * 12_500_000)


def test_2_unit_a_is_invariant_under_every_unit_b_change(world: dict[str, Any]) -> None:
    before = _analysis(world, world["unit_a"])
    fingerprint = _fingerprint(world, world["unit_a"])
    for change in (lambda: _change_b(world, 9_000_000.0), lambda: _approve(world), lambda: _approve(world, False)):
        change()
        assert _analysis(world, world["unit_a"]).result == before.result
        assert _fingerprint(world, world["unit_a"]) == fingerprint
    # Changing Unit A's own dependency does move it, and an exact revert restores it.
    fx.replace_timepoint(world["db"], world["investment_id"], _timepoint(world["a"], world["b"], timepoint_id=TIMEPOINT, month=24, b_amount=9_000_000.0, a_cap=0.08))
    assert _fingerprint(world, world["unit_a"]) != fingerprint
    fx.replace_timepoint(world["db"], world["investment_id"], _timepoint(world["a"], world["b"], timepoint_id=TIMEPOINT, month=24, b_amount=B_AMOUNT))
    assert _fingerprint(world, world["unit_a"]) == fingerprint


def _refusal_codes(world: dict[str, Any], strategy: str) -> list[str]:
    investment_id, db = world["investment_id"], world["db"]
    store.put_memo_draft(investment_id, memo_fx.memo_draft(investment_id, selected=memo_fx.project_cell(strategy_id=strategy)), db_path=db)
    draft = store.get_memo_draft(investment_id, db_path=db)
    assert draft is not None and draft.selected_decision is not None
    refusals = deps.publication_refusals_for(
        investment_id, draft, deps.dependency_set(investment_id, draft.selected_decision, draft=draft, db_path=db), db_path=db
    )
    return [item.code.value for item in refusals]


def test_3_publication_is_not_blocked_by_an_unrelated_units_evidence(world: dict[str, Any]) -> None:
    """No valuation refusal for Unit A -- B's evidence is not its dependency.
    Refinance V1 Stage 3 removed the temporary report gate that stood here, so
    the claim is now proved end to end: the package publishes."""

    assert _valuation_refusals(world, world["unit_a"]) == []
    assert _refusal_codes(world, world["unit_a"]) == []
    deps.publish(world["investment_id"], db_path=world["db"])
    assert len(store.list_memo_versions(world["investment_id"], db_path=world["db"])) == 1


# =============================================================================
# 4-5. Unit B and the Investment: evidence_not_approved, and publication blocked
# =============================================================================


def test_4_a_unit_b_ltv_refinance_is_evidence_not_approved_and_blocks_publication(world: dict[str, Any]) -> None:
    analysis = _analysis(world, world["unit_b"])
    (event,) = analysis.result.capital_events
    assert event.status is RefinanceStatus.UNAVAILABLE
    assert event.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    ltv = event.sizing.capacities[0]
    assert ltv.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED and ltv.capacity is None
    assert event.value_dependency is not None and event.value_dependency.value is None
    for text in _analyst_messages(analysis):
        assert "12,500,000" not in text and "12500000" not in text, text
        assert world["a"] not in text and world["b"] not in text and world["investment_id"] not in text, text
    assert "approved Evidence Reference" in analysis.result.common_equity.unavailable_message
    (refusal,) = _valuation_refusals(world, world["unit_b"])
    assert refusal.scope_id == TIMEPOINT and refusal.unavailable_reason == "evidence_not_approved"


def test_5_an_investment_ltv_refinance_is_unavailable_and_blocks_publication(world: dict[str, Any]) -> None:
    event = _event(world, world["portfolio"])
    assert event.status is RefinanceStatus.UNAVAILABLE
    assert event.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    assert event.sizing.gross_proceeds is None
    (refusal,) = _valuation_refusals(world, world["portfolio"])
    assert refusal.scope_id == TIMEPOINT


# =============================================================================
# 6. Approving B's evidence moves exactly the identities that depend on it
# =============================================================================


def test_6_approving_unit_b_resolves_b_and_the_investment_and_moves_only_their_identities(world: dict[str, Any]) -> None:
    before = {key: _fingerprint(world, world[key]) for key in ("unit_a", "unit_b", "portfolio", "dscr_a")}
    _approve(world)
    after = {key: _fingerprint(world, world[key]) for key in ("unit_a", "unit_b", "portfolio", "dscr_a")}
    assert after["unit_a"] == before["unit_a"] and after["dscr_a"] == before["dscr_a"]
    assert after["unit_b"] != before["unit_b"] and after["portfolio"] != before["portfolio"]
    assert _event(world, world["unit_b"]).status is RefinanceStatus.EXECUTED
    assert _event(world, world["portfolio"]).status is RefinanceStatus.EXECUTED
    assert _valuation_refusals(world, world["unit_b"]) == []
    assert _valuation_refusals(world, world["portfolio"]) == []


def test_an_investment_event_moves_with_any_member_unit(world: dict[str, Any]) -> None:
    _approve(world)
    before = _fingerprint(world, world["portfolio"])
    fx.replace_timepoint(world["db"], world["investment_id"], _timepoint(world["a"], world["b"], timepoint_id=TIMEPOINT, month=24, a_cap=0.07))
    assert _fingerprint(world, world["portfolio"]) != before


def test_a_dscr_only_refinance_is_invariant_under_every_valuation_change(world: dict[str, Any]) -> None:
    before, fingerprint = _analysis(world, world["dscr_a"]).result, _fingerprint(world, world["dscr_a"])
    _change_b(world, 9_000_000.0)
    _approve(world)
    fx.replace_timepoint(world["db"], world["investment_id"], _timepoint(world["a"], world["b"], timepoint_id=TIMEPOINT, month=24, a_cap=0.08))
    assert _analysis(world, world["dscr_a"]).result == before
    assert _fingerprint(world, world["dscr_a"]) == fingerprint


# =============================================================================
# 7. Unit-scoped PctOfValue follows the same exact-scope rule
# =============================================================================


def _funding_state(world: dict[str, Any], strategy: str) -> Any:
    (state,) = analyze_structured_valuations(world["investment_id"], strategy, "base", db_path=world["db"]).funding_states
    return state


def test_7_a_unit_pct_of_value_is_sized_from_its_own_units_cell_alone(world: dict[str, Any]) -> None:
    state_a = _funding_state(world, world["pct_a"])
    assert state_a.status is AvailabilityStatus.AVAILABLE and fx.rf.close(state_a.amount, 0.4 * 800_000 / 0.064)
    state_b = _funding_state(world, world["pct_b"])
    assert state_b.status is AvailabilityStatus.UNAVAILABLE and state_b.amount is None
    assert state_b.unavailable.reason_code.value == "evidence_not_approved"
    assert _valuation_refusals(world, world["pct_a"]) == []
    assert _valuation_refusals(world, world["pct_b"]) != []
    _approve(world)
    assert _funding_state(world, world["pct_b"]).status is AvailabilityStatus.AVAILABLE
    assert _valuation_refusals(world, world["pct_b"]) == []


# =============================================================================
# Typed propagation: Stage 1's prose is never the authority
# =============================================================================


def test_changing_stage_1_prose_changes_neither_classification_nor_downstream_messages(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _analysis(world, world["unit_b"])
    original_dependency = cs_refinance._value_dependency

    def reworded(*args: Any, **kwargs: Any) -> Any:
        dependency, reason, message = original_dependency(*args, **kwargs)
        return dependency, reason, None if message is None else f"REWORDED ({message[::-1]})"

    monkeypatch.setattr(cs_refinance, "_value_dependency", reworded)
    monkeypatch.setattr(cs_refinance_execution, "_unavailable_message", lambda plan: "REWORDED POSITION PROSE")
    reworded_analysis = _analysis(world, world["unit_b"])
    (event,) = reworded_analysis.result.capital_events
    assert event.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    assert reworded_analysis.result == expected.result
    assert not [text for text in _analyst_messages(reworded_analysis) if "REWORDED" in text]


def test_unaffected_events_and_positions_are_returned_untouched(world: dict[str, Any]) -> None:
    """Unit A's executed refinance and every position of it are exactly the
    engine's: nothing is rebuilt that the evidence gate did not concern."""

    from anchor.deals.refinance_integration import with_evidence_not_approved

    analysis = _analysis(world, world["unit_a"])
    structure = store.get_strategy(world["investment_id"], world["unit_a"], db_path=world["db"]).strategy.root_overlays[0].content
    again = with_evidence_not_approved(
        analysis.result, capital_structure=structure, authority=gated_authority(world, world["unit_a"]), valuation_labels={}
    )
    assert again is analysis.result


def gated_authority(world: dict[str, Any], strategy: str) -> Any:
    """The same gated authority the engine reads for ``strategy``."""

    from anchor.deals.valuation_views import funding_authority

    surface = analyze_structured_valuations(world["investment_id"], strategy, "base", db_path=world["db"])
    blocked = {record.timepoint_id: {unit.unit_id: unit.detail for unit in record.units} for record in surface.evidence_blocked}
    return funding_authority(investment_id=world["investment_id"], views=surface.views, blocked=blocked)
