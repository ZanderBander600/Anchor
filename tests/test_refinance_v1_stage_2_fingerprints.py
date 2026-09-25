"""Refinance & Capital Events V1 Stage 2 -- structured fingerprints, staleness
and memo dependencies (fixture F13).

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 14 and 18.2 (F13),
invariants INV-11 and INV-18. Proves:

- FP-2: a structure with no event hashes exactly as before, and the event
  payload joins only when an event exists;
- the payload is canonical -- permuting events, retiring references, cost
  lines or positions changes nothing -- and excludes labels, descriptions,
  position names and valuation labels, while every economic member moves it;
- an exact semantic revert restores the prior fingerprint;
- only an LTV-enabled event consumes a valuation: changing its referenced
  valuation stales the structured result and its memo dependencies, and the
  recomputed result reflects the new value; a DSCR-only event is invariant under
  cap-rate edits, new valuation definitions and evidence-approval changes;
- a published memo keeps its frozen version and report, and freshness names
  ``CAPITAL_STRUCTURE`` only when the refinance actually depends on the change;
- the evidence gate reports ``evidence_not_approved``, never a missing
  timepoint, and never reports the amount the analyst typed.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

import _p7_10_stage_2_fixtures as memo_fx  # type: ignore[import-not-found]
import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from anchor.analysis.strategy import (
    BASE_SCENARIO_ID,
    BASE_STRATEGY_ID,
    InvestmentStrategyOverlay,
    StrategyDomain,
)
from anchor.capital_structure.contracts import CapitalStructure
from anchor.capital_structure.events import AuthoredPositionRef, CapitalStructureWithEvents
from anchor.capital_structure.refinance_contracts import ConstraintKind, RefinanceStatus, RefinanceUnavailableReason
from anchor.deals import memo_dependencies as deps
from anchor.deals import store
from anchor.deals.fingerprint import capital_events_payload, fingerprint_structured_source
from anchor.deals.structured_variants import (
    analyze_structured_valuations,
    analyze_structured_variant,
    structured_variant_fingerprint,
)
from anchor.memo.contracts import MemoDependencyClass, MemoFreshness

BASE, SCENARIO = BASE_STRATEGY_ID, BASE_SCENARIO_ID
PROJECT = "a" * 64


def _fp(structure: CapitalStructure, **kwargs: Any) -> str:
    return fingerprint_structured_source(project_source_fingerprint=PROJECT, capital_structure=structure, **kwargs)


# =============================================================================
# FP-2 and the canonical payload (pure)
# =============================================================================


def test_fp2_a_structure_without_events_hashes_exactly_as_before() -> None:
    plain = fx.closing_mezz_only("u")
    assert capital_events_payload(plain) == []
    # The valuation arguments are never consulted without an event.
    witness = {"x": fx.value_timepoint("u", timepoint_id="x")}
    assert _fp(plain) == _fp(plain, valuation_definitions=witness, evidence_blocked={"x": {"u": "no"}})
    assert _fp(CapitalStructure(positions=())) == PROJECT


def test_the_event_payload_joins_only_when_an_event_exists() -> None:
    evented = fx.evented("u", dscr=2.0)
    same_positions = CapitalStructure(positions=evented.positions)
    assert _fp(evented) != _fp(same_positions)
    assert len(capital_events_payload(evented)) == 1


def test_permuting_every_collection_changes_nothing() -> None:
    structure = fx.full_member_structure("u")
    (event,) = structure.events
    permuted_event = dataclasses.replace(
        event, retiring=tuple(reversed(event.retiring)), costs=tuple(reversed(event.costs))
    )
    permuted = CapitalStructureWithEvents(positions=tuple(reversed(structure.positions)), events=(permuted_event,))
    assert _fp(permuted) == _fp(structure)


def test_permuting_events_changes_nothing() -> None:
    a = fx.evented("a", dscr=2.0)
    b = fx.evented("b", dscr=1.5, event_id="refi-b", replacement_id="refi-loan-b")
    two = CapitalStructureWithEvents(positions=(*a.positions, *b.positions), events=(*a.events, *b.events))
    swapped = CapitalStructureWithEvents(
        positions=(*b.positions, *a.positions), events=(*b.events, *a.events)
    )
    assert _fp(two) == _fp(swapped)


def test_labels_descriptions_names_and_valuation_labels_are_excluded() -> None:
    structure = fx.full_member_structure("u")
    (event,) = structure.events
    relabelled = CapitalStructureWithEvents(
        positions=tuple(dataclasses.replace(position, name=f"{position.name} (renamed)") for position in structure.positions),
        events=(
            dataclasses.replace(
                event,
                label="A different label",
                costs=tuple(dataclasses.replace(line, description="Reworded") for line in event.costs),
            ),
        ),
    )
    definitions = {fx.TIMEPOINT_ID: fx.value_timepoint("u")}
    renamed_view = {fx.TIMEPOINT_ID: fx.value_timepoint("u", label="A new valuation label")}
    assert _fp(relabelled, valuation_definitions=definitions) == _fp(structure, valuation_definitions=definitions)
    assert _fp(structure, valuation_definitions=renamed_view) == _fp(structure, valuation_definitions=definitions)


def _economic_edits() -> dict[str, CapitalStructureWithEvents]:
    base = fx.full_member_structure("u")
    (event,) = base.events

    def edit(**changes: Any) -> CapitalStructureWithEvents:
        return CapitalStructureWithEvents(positions=base.positions, events=(dataclasses.replace(event, **changes),))

    sizing = event.sizing
    return {
        "month": edit(timing=dataclasses.replace(event.timing, model_month=36)),
        "sequence": edit(timing=dataclasses.replace(event.timing, sequence=2)),
        "scope": edit(scope=fx.scope("other")),
        "retiring set": edit(retiring=(fx.legacy("u"),)),
        "retiring kind": edit(retiring=(fx.legacy("u"), AuthoredPositionRef(position_id="u"))),
        "replacement id": edit(replacement_position_id="another-loan"),
        "fixed cap target": edit(sizing=dataclasses.replace(sizing, fixed_cap=dataclasses.replace(sizing.fixed_cap, amount=7_000_000.0))),
        "ltv target": edit(sizing=dataclasses.replace(sizing, max_ltv=dataclasses.replace(sizing.max_ltv, max_ltv=0.6))),
        "dscr target": edit(sizing=dataclasses.replace(sizing, min_dscr=dataclasses.replace(sizing.min_dscr, min_dscr=1.5))),
        "constraint removed": edit(sizing=dataclasses.replace(sizing, fixed_cap=None)),
        "valuation reference": edit(valuation=dataclasses.replace(event.valuation, timepoint_id="another")),
        "cost amount": edit(costs=(dataclasses.replace(event.costs[0], amount=41_000.0), *event.costs[1:])),
        "cost id": edit(costs=(dataclasses.replace(event.costs[0], cost_id="renumbered"), *event.costs[1:])),
        "cost recipient": edit(costs=(*event.costs[:2], dataclasses.replace(event.costs[2], recipient=fx.legacy("u")))),
        "cost removed": edit(costs=event.costs[1:]),
        "event id": edit(event_id="another-event"),
    }


@pytest.mark.parametrize("name", sorted(_economic_edits()))
def test_every_economic_member_moves_the_fingerprint(name: str) -> None:
    assert _fp(_economic_edits()[name]) != _fp(fx.full_member_structure("u")), name


def test_an_exact_semantic_revert_restores_the_fingerprint() -> None:
    original = fx.evented("u", dscr=2.0)
    changed = fx.evented("u", dscr=1.5)
    reverted = fx.evented("u", dscr=2.0)
    assert _fp(changed) != _fp(original)
    assert _fp(reverted) == _fp(original)


def _two_unit_definition(u_cap: float = 0.064, v_cap: float = 0.07) -> dict[str, Any]:
    from anchor.valuation.contracts import DirectCap, UnitValuationInstruction

    point = fx.value_timepoint("u", cap_rate=u_cap)
    point = dataclasses.replace(
        point,
        unit_instructions=(
            UnitValuationInstruction(unit_id="u", method=DirectCap(cap_rate=u_cap)),
            UnitValuationInstruction(unit_id="v", method=DirectCap(cap_rate=v_cap)),
        ),
    )
    return {fx.TIMEPOINT_ID: point}


def test_only_an_ltv_event_reads_the_valuation_arguments_and_only_for_its_scope() -> None:
    """Review correction (Sections 8.1 and 14.1): a Unit event's identity holds
    its own Unit's instruction and evidence state, never another Unit's; an
    Investment event's holds every member's."""

    from anchor.capital_structure.contracts import PositionScope, ScopeKind

    dscr_only = fx.evented("u", dscr=2.0)
    ltv = fx.evented("u", ltv=0.65, dscr=2.0)
    one, two = _two_unit_definition(u_cap=0.064), _two_unit_definition(u_cap=0.08)
    assert _fp(dscr_only, valuation_definitions=one) == _fp(dscr_only, valuation_definitions=two)
    assert _fp(dscr_only, evidence_blocked={fx.TIMEPOINT_ID: {"u": "no"}}) == _fp(dscr_only)
    # The Unit event: its own Unit moves it, and the other Unit never does.
    assert _fp(ltv, valuation_definitions=one) != _fp(ltv, valuation_definitions=two)
    assert _fp(ltv, valuation_definitions=one, evidence_blocked={fx.TIMEPOINT_ID: {"u": "no"}}) != _fp(
        ltv, valuation_definitions=one
    )
    assert _fp(ltv, valuation_definitions=_two_unit_definition(v_cap=0.09)) == _fp(ltv, valuation_definitions=one)
    assert _fp(ltv, valuation_definitions=one, evidence_blocked={fx.TIMEPOINT_ID: {"v": "no"}}) == _fp(
        ltv, valuation_definitions=one
    )
    assert _fp(ltv) != _fp(ltv, valuation_definitions=one)  # "not defined" is a state too
    # The Investment event: any member moves it.
    whole = CapitalStructureWithEvents(
        positions=(dataclasses.replace(ltv.positions[0], scope=PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None)),),
        events=(dataclasses.replace(ltv.events[0], scope=PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None)),),
    )
    assert _fp(whole, valuation_definitions=_two_unit_definition(v_cap=0.09)) != _fp(whole, valuation_definitions=one)
    assert _fp(whole, valuation_definitions=one, evidence_blocked={fx.TIMEPOINT_ID: {"v": "no"}}) != _fp(
        whole, valuation_definitions=one
    )


# =============================================================================
# F13 -- persisted staleness and non-staleness
# =============================================================================


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def _f1(unit_id: str) -> CapitalStructureWithEvents:
    """F1: fixed 7,500,000, LTV 65% on the referenced valuation, DSCR 2.00x."""

    return fx.evented(unit_id, fixed=7_500_000.0, ltv=0.65, dscr=2.0)


@pytest.fixture
def investment(db: Path) -> dict[str, Any]:
    return build_investment(db)


def build_investment(db: Path) -> dict[str, Any]:
    """Base: the LTV-enabled F1 refinance. Strategy "DSCR only": its own F3b
    structure. One direct-cap valuation at month 24 (V = 12,500,000)."""

    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, _f1(deal.id), db_path=db)
    assert investment_id is not None
    timepoint = fx.with_timepoint(db, investment_id, fx.value_timepoint(deal.id))
    dscr_only = store.create_strategy(
        investment_id,
        name="DSCR only",
        root_overlays=(
            InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=fx.evented(deal.id, dscr=2.0)),
        ),
        db_path=db,
    ).strategy.strategy_id
    return {"deal": deal, "investment_id": investment_id, "timepoint": timepoint, "dscr_only": dscr_only}


def _event(analysis: Any) -> Any:
    (event,) = analysis.result.capital_events
    return event


def test_f13_a_the_referenced_valuation_change_stales_and_recomputes(db: Path, investment: dict[str, Any]) -> None:
    investment_id, timepoint = investment["investment_id"], investment["timepoint"]
    before = analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)
    event = _event(before)
    assert event.sizing.binding == (ConstraintKind.FIXED_CAP,)
    assert fx.rf.close(event.sizing.gross_proceeds, 7_500_000) and fx.rf.close(event.bridge.net_event_cash, 1_980_000)

    fx.replace_timepoint(db, investment_id, timepoint, unit_instructions=fx.value_timepoint(investment["deal"].id, cap_rate=0.08).unit_instructions)
    after = analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)
    assert after.structured_source_fingerprint != before.structured_source_fingerprint
    assert structured_variant_fingerprint(investment_id, BASE, SCENARIO, db_path=db).structured_source_fingerprint == (
        after.structured_source_fingerprint
    )
    # The Project identity did not move: a valuation is not a Project input.
    assert after.project_source_fingerprint == before.project_source_fingerprint
    recomputed = _event(after)
    assert recomputed.sizing.binding == (ConstraintKind.MAX_LTV,)
    assert fx.rf.close(recomputed.sizing.gross_proceeds, 6_500_000) and fx.rf.close(recomputed.bridge.net_event_cash, 980_000)

    # The exact semantic revert restores the identity and the result.
    fx.replace_timepoint(db, investment_id, timepoint)
    reverted = analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)
    assert reverted.structured_source_fingerprint == before.structured_source_fingerprint
    assert reverted.result == before.result


def test_f13_b_a_dscr_only_refinance_is_invariant_under_every_valuation_change(
    db: Path, investment: dict[str, Any]
) -> None:
    investment_id, timepoint, dscr_only = investment["investment_id"], investment["timepoint"], investment["dscr_only"]
    deal = investment["deal"]
    before = analyze_structured_variant(investment_id, dscr_only, SCENARIO, db_path=db)
    assert _event(before).value_dependency is None
    assert fx.rf.close(_event(before).sizing.gross_proceeds, 8_000_000)

    fx.replace_timepoint(db, investment_id, timepoint, unit_instructions=fx.value_timepoint(deal.id, cap_rate=0.08).unit_instructions)
    fx.with_timepoint(db, investment_id, fx.value_timepoint(deal.id, timepoint_id="year-3", month=36, label="Year 3"))
    store.put_evidence_reference(investment_id, memo_fx.evidence(investment_id, evidence_id="appraisal-1", approved=False), db_path=db)
    fx.with_timepoint(
        db, investment_id, fx.value_timepoint(deal.id, timepoint_id="analyst", label="Appraisal", method=fx.analyst_value())
    )
    store.put_evidence_reference(investment_id, memo_fx.evidence(investment_id, evidence_id="appraisal-1", approved=True), db_path=db)

    after = analyze_structured_variant(investment_id, dscr_only, SCENARIO, db_path=db)
    assert after.structured_source_fingerprint == before.structured_source_fingerprint
    assert after.result == before.result
    assert analyze_structured_valuations(investment_id, dscr_only, SCENARIO, db_path=db).consumed_timepoint_ids == ()


def test_f13_renaming_labels_changes_no_fingerprint(db: Path, investment: dict[str, Any]) -> None:
    investment_id, timepoint, deal = investment["investment_id"], investment["timepoint"], investment["deal"]
    before = structured_variant_fingerprint(investment_id, BASE, SCENARIO, db_path=db).structured_source_fingerprint
    renamed = _f1(deal.id)
    (event,) = renamed.events
    store.set_deal_capital_structure(
        deal.id, CapitalStructureWithEvents(positions=renamed.positions, events=(dataclasses.replace(event, label="Renamed"),)), db_path=db
    )
    fx.replace_timepoint(db, investment_id, timepoint, label="Renamed valuation")
    assert structured_variant_fingerprint(investment_id, BASE, SCENARIO, db_path=db).structured_source_fingerprint == before
    assert _event(analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)).label == "Renamed"


def test_the_ltv_timepoint_is_consumed_and_the_dscr_structure_consumes_none(db: Path, investment: dict[str, Any]) -> None:
    investment_id = investment["investment_id"]
    assert analyze_structured_valuations(investment_id, BASE, SCENARIO, db_path=db).consumed_timepoint_ids == (fx.TIMEPOINT_ID,)
    assert analyze_structured_valuations(investment_id, investment["dscr_only"], SCENARIO, db_path=db).consumed_timepoint_ids == ()


# =============================================================================
# The evidence gate
# =============================================================================


def test_an_unapproved_analyst_value_is_evidence_not_approved_and_approval_moves_the_identity(db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.evented(deal.id, ltv=0.65, dscr=2.0), db_path=db)
    assert investment_id is not None
    store.put_evidence_reference(investment_id, memo_fx.evidence(investment_id, evidence_id="appraisal-1", approved=False), db_path=db)
    fx.with_timepoint(db, investment_id, fx.value_timepoint(deal.id, method=fx.analyst_value(12_500_000.0)))

    blocked = analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)
    event = _event(blocked)
    assert event.status is RefinanceStatus.UNAVAILABLE
    assert event.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    ltv, dscr = event.sizing.capacities
    assert ltv.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED and ltv.capacity is None
    assert dscr.capacity is not None and fx.rf.close(dscr.capacity, 8_000_000)
    assert event.sizing.gross_proceeds is None and event.bridge is None
    # The typed amount is never reported, and no message claims the timepoint is missing.
    messages = [event.unavailable_message, ltv.unavailable_message, blocked.result.common_equity.unavailable_message]
    messages += [position.unavailable_message for position in blocked.result.unexecuted_positions]
    assert all("12,500,000" not in text and "12500000" not in text and "does not exist" not in text for text in messages)
    assert "approved Evidence Reference" in event.unavailable_message
    assert blocked.result.common_equity.cash_flows is None

    store.put_evidence_reference(investment_id, memo_fx.evidence(investment_id, evidence_id="appraisal-1", approved=True), db_path=db)
    approved = analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)
    assert approved.structured_source_fingerprint != blocked.structured_source_fingerprint
    assert _event(approved).status is RefinanceStatus.EXECUTED


def test_a_timepoint_that_is_genuinely_missing_stays_timepoint_not_found(db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.evented(deal.id, ltv=0.65, dscr=2.0), db_path=db)
    event = _event(analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db))  # type: ignore[arg-type]
    assert event.unavailable_reason is RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND
    assert event.sizing.gross_proceeds is None


# =============================================================================
# Memo publication dependencies and freshness
# =============================================================================


def _publish(db: Path, investment_id: str, *, strategy_id: str = BASE) -> Any:
    store.put_memo_draft(investment_id, memo_fx.memo_draft(investment_id, selected=memo_fx.project_cell(strategy_id=strategy_id)), db_path=db)
    return deps.publish(investment_id, db_path=db)


def _stale(db: Path, investment_id: str, version: Any) -> set[MemoDependencyClass]:
    report = deps.version_freshness(investment_id, store.get_memo_version(investment_id, version.version_id, db_path=db), db_path=db)
    return {item.dependency_class for item in report.stale_dependencies}


def test_the_ltv_valuation_change_stales_capital_structure_and_keeps_the_frozen_version(
    db: Path, investment: dict[str, Any]
) -> None:
    investment_id, timepoint, deal = investment["investment_id"], investment["timepoint"], investment["deal"]
    version = _publish(db, investment_id)
    frozen = store.get_memo_version(investment_id, version.version_id, db_path=db)
    artifact = store.get_memo_version_artifact(investment_id, version.version_id, db_path=db)
    assert _stale(db, investment_id, version) == set()

    fx.replace_timepoint(db, investment_id, timepoint, unit_instructions=fx.value_timepoint(deal.id, cap_rate=0.08).unit_instructions)
    stale = _stale(db, investment_id, version)
    assert {
        MemoDependencyClass.VALUATION_DEFINITIONS,
        MemoDependencyClass.VALUATION_RESULTS,
        MemoDependencyClass.CAPITAL_STRUCTURE,
    } <= stale
    assert MemoDependencyClass.PROJECT_VARIANT not in stale
    # What the committee received is untouched.
    assert store.get_memo_version(investment_id, version.version_id, db_path=db) == frozen
    assert store.get_memo_version_artifact(investment_id, version.version_id, db_path=db) == artifact


def test_a_dscr_only_memo_never_goes_capital_structure_stale_from_a_valuation(
    db: Path, investment: dict[str, Any]
) -> None:
    investment_id, timepoint, deal = investment["investment_id"], investment["timepoint"], investment["deal"]
    version = _publish(db, investment_id, strategy_id=investment["dscr_only"])
    fx.replace_timepoint(db, investment_id, timepoint, unit_instructions=fx.value_timepoint(deal.id, cap_rate=0.08).unit_instructions)
    fx.with_timepoint(db, investment_id, fx.value_timepoint(deal.id, timepoint_id="year-3", month=36, label="Year 3"))
    stale = _stale(db, investment_id, version)
    assert MemoDependencyClass.CAPITAL_STRUCTURE not in stale
    assert MemoDependencyClass.VALUATION_DEFINITIONS in stale  # the ledger records every definition, as before


def test_a_refinance_structure_change_stales_capital_structure_only(db: Path, investment: dict[str, Any]) -> None:
    investment_id, deal = investment["investment_id"], investment["deal"]
    version = _publish(db, investment_id)
    store.set_deal_capital_structure(deal.id, fx.evented(deal.id, fixed=7_000_000.0, ltv=0.65, dscr=2.0), db_path=db)
    assert _stale(db, investment_id, version) == {MemoDependencyClass.CAPITAL_STRUCTURE}


def _refusals(db: Path, investment_id: str) -> list[Any]:
    draft = store.get_memo_draft(investment_id, db_path=db)
    assert draft is not None and draft.selected_decision is not None
    return list(
        deps.publication_refusals_for(
            investment_id, draft, deps.dependency_set(investment_id, draft.selected_decision, draft=draft, db_path=db), db_path=db
        )
    )


def test_publication_requires_the_ltv_valuation_and_never_a_dscr_only_one(db: Path) -> None:
    """R-R: the valuation an LTV-enabled refinance references is a consumed
    publication dependency, exactly as a ``PctOfValue`` consumption is -- a
    defined view that does not resolve blocks the package even though the memo
    displays it nowhere. The same view beside a DSCR-only refinance is
    exploratory and blocks nothing."""

    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.evented(deal.id, ltv=0.65, dscr=2.0), db_path=db)
    assert investment_id is not None
    store.put_evidence_reference(investment_id, memo_fx.evidence(investment_id, evidence_id="appraisal-1", approved=False), db_path=db)
    fx.with_timepoint(db, investment_id, fx.value_timepoint(deal.id, method=fx.analyst_value()))
    store.put_memo_draft(investment_id, memo_fx.memo_draft(investment_id), db_path=db)

    (refusal,) = [item for item in _refusals(db, investment_id) if item.code.value == "valuation_unavailable_for_required_view"]
    assert refusal.scope_id == fx.TIMEPOINT_ID and refusal.field == "capital_structure"
    assert refusal.unavailable_reason == "evidence_not_approved"

    store.set_deal_capital_structure(deal.id, fx.evented(deal.id, dscr=2.0), db_path=db)
    assert _refusals(db, investment_id) == []
    assert deps.publish(investment_id, db_path=db).version_number == 1


def test_an_ltv_reference_to_an_undefined_timepoint_follows_the_pct_of_value_rule(db: Path) -> None:
    """Exactly like ``PctOfValue`` (P7.10 Section 22.6): only a *defined*
    consumed view is a publication dependency. The refinance itself reports
    ``timepoint_not_found`` in its own typed result; nothing is fabricated."""

    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.evented(deal.id, ltv=0.65, dscr=2.0), db_path=db)
    assert investment_id is not None
    store.put_memo_draft(investment_id, memo_fx.memo_draft(investment_id), db_path=db)
    assert analyze_structured_valuations(investment_id, BASE, SCENARIO, db_path=db).consumed_timepoint_ids == ()
    assert [item for item in _refusals(db, investment_id) if item.code.value == "valuation_unavailable_for_required_view"] == []


def test_freshness_is_current_right_after_publication(db: Path, investment: dict[str, Any]) -> None:
    investment_id = investment["investment_id"]
    version = _publish(db, investment_id)
    report = deps.version_freshness(investment_id, version, db_path=db)
    assert report.freshness is MemoFreshness.CURRENT


# =============================================================================
# FP-2 against the accepted tree itself
# =============================================================================

_ACCEPTED = "f2b5cefa7fca3ecde7621927c5818cbc40c068cd"

#: Plain structures in every shape that existed before this gate, each hashed
#: by the accepted tree and by this one. Stated as literals, so the two runs
#: cannot share an object.
_FP2_PROBE = r'''
import json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "src"))
import anchor
assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__
from anchor.capital_structure.contracts import (CapitalPosition, CapitalStructure, DebtTerms, FixedAmount,
    FundingEvent, PctOfPrice, PctOfValue, PositionClass, PositionFee, PositionScope, ScopeKind, ShortfallResolution)
from anchor.deals.fingerprint import fingerprint_structured_source
from anchor.valuation.contracts import (InvestmentValuationResult, UnitValuationResult, ValuationAvailability,
    ValuationKind, ValuationMethodKind, ValuationScopeKind)

def debt(pid, rule, priority=2):
    return CapitalPosition(position_id=pid, name=pid, position_class=PositionClass.MEZZANINE_DEBT, priority=priority,
        scope=PositionScope(kind=ScopeKind.UNIT, unit_id="u"),
        funding=(FundingEvent(event_id=pid + "-f", model_month=0, sequence=1, amount_rule=rule),),
        terms=DebtTerms(interest_rate=0.1, amortization=25, io_period=1, maturity_month=60,
            fees=(PositionFee(fee_id=pid + "-fee", description="x", amount=1.0, model_month=0, sequence=2),),
            current_pay_rate=0.1, pik_rate=0.0),
        shortfall_resolution=ShortfallResolution.COMMON_EQUITY_CONTRIBUTION)

cell = UnitValuationResult(unit_id="u", model_month=0, method_kind=ValuationMethodKind.DIRECT_CAP, analyst_supplied=False,
    status=ValuationAvailability.AVAILABLE, value=1.0e7, forward_noi=6.0e5, cap_rate=0.06, evidence_id=None,
    unavailable_reason=None, unavailable_message=None)
consumed = {"as-is": InvestmentValuationResult(timepoint_id="as-is", investment_id="i", kind=ValuationKind.AS_IS, label="As-Is",
    model_month=0, scope_kind=ValuationScopeKind.INVESTMENT, status=ValuationAvailability.AVAILABLE, value=1.0e7,
    unit_results=(cell,), unavailable_reason=None, unavailable_message=None)}
project = "p" * 64
out = {
    "empty": fingerprint_structured_source(project_source_fingerprint=project, capital_structure=CapitalStructure(positions=())),
    "fixed": fingerprint_structured_source(project_source_fingerprint=project,
        capital_structure=CapitalStructure(positions=(debt("m", FixedAmount(amount=1.5e6)),))),
    "pct_of_price": fingerprint_structured_source(project_source_fingerprint=project,
        capital_structure=CapitalStructure(positions=(debt("m", PctOfPrice(pct=0.2)), debt("n", FixedAmount(amount=2.0), 3)))),
    "pct_of_value": fingerprint_structured_source(project_source_fingerprint=project,
        capital_structure=CapitalStructure(positions=(debt("m", PctOfValue(timepoint_id="as-is", pct=0.5)),)),
        consumed_valuations=consumed),
}
print(json.dumps(out, sort_keys=True))
'''


@pytest.fixture(scope="module")
def accepted_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return extract_accepted_tree(tmp_path_factory.mktemp("fp2_accepted_tree"))


def extract_accepted_tree(scratch: Path) -> Path:
    """The accepted tree's ``src``, by ``git archive`` (objects only)."""

    import subprocess
    import zipfile

    archive = scratch / "accepted.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _ACCEPTED, "src"],
        check=True, capture_output=True, cwd=Path(__file__).resolve().parents[1],
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "tree")
    return scratch / "tree"


def _probe(root: Path) -> dict[str, str]:
    import json
    import subprocess
    import sys

    completed = subprocess.run([sys.executable, "-c", _FP2_PROBE, str(root)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def current_probe() -> dict[str, str]:
    """The same probe, run in this process against this tree -- so a mutant
    installed here is exactly what it measures."""

    import sys

    namespace: dict[str, Any] = {"__name__": "__fp2_probe__"}
    argv = sys.argv
    sys.argv = ["probe", str(Path(__file__).resolve().parents[1])]
    try:
        exec(compile(_FP2_PROBE, "<fp2-probe>", "exec"), namespace)  # noqa: S102 - the stated probe, in-process
    finally:
        sys.argv = argv
    return namespace["out"]


def test_fp2_every_no_event_digest_equals_the_accepted_trees(accepted_tree: Path) -> None:
    accepted = _probe(accepted_tree)
    assert accepted["empty"] == "p" * 64
    assert current_probe() == accepted
