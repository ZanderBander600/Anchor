"""Refinance & Capital Events V1 Stage 2 -- Strategy resolution and P-8 event
identity (fixture F18).

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 6.1, 13.1 and
18.2 (F18). Proves, against the real store and the real variant service:

- events belong to the ``CAPITAL_STRUCTURE`` domain and are replaced whole: a
  Strategy with its own structure brings its own events or none, one that
  inherits gets the Base's, and an explicit empty structure is empty;
- an inheriting Strategy is bit-identical to the Base -- result and both
  fingerprints -- and removing a Strategy's replacement restores the Base
  exactly;
- an event can never be patched onto an inherited structure;
- the same ``event_id`` with a different scope (or kind) anywhere in the
  Investment is refused, on every lifecycle path that writes a structure, with
  the stable code; identity is ``event_id``, never ``label``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.analysis.strategy import (
    BASE_SCENARIO_ID,
    BASE_STRATEGY_ID,
    InvestmentStrategyOverlay,
    StrategyDomain,
    StrategyValidationError,
)
from anchor.capital_structure.contracts import CapitalStructure
from anchor.capital_structure.events import CapitalStructureWithEvents
from anchor.deals import store
from anchor.deals.capital_event_identity import (
    CapitalEventIdentityConflictError,
    CapitalEventIdentityIssueCode,
    capital_event_identity_issues,
)
from anchor.deals.position_identity import StructureOwner, StructureOwnerKind
from anchor.deals.structured_variants import analyze_structured_variant, structured_variant_fingerprint

BASE, SCENARIO = BASE_STRATEGY_ID, BASE_SCENARIO_ID


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def _overlay(structure: CapitalStructure) -> tuple[InvestmentStrategyOverlay, ...]:
    return (InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=structure),)


def _strategy(db: Path, investment_id: str, name: str, structure: CapitalStructure | None) -> str:
    record = store.create_strategy(
        investment_id, name=name, root_overlays=() if structure is None else _overlay(structure), db_path=db
    )
    return record.strategy.strategy_id


def _hidden(db: Path) -> tuple[Any, str]:
    """A standalone Deal with a hidden wrapper and no Base structure: the base
    case's acquisition loan only (F18's Base)."""

    deal = fx.base_deal(db)
    record = store.create_strategy_for_deal(deal.id, name="Placeholder", db_path=db)
    return deal, record.investment_id


# =============================================================================
# F18 -- whole-domain replacement
# =============================================================================


def test_f18_an_inheriting_strategy_is_bit_identical_to_the_base(db: Path) -> None:
    deal, investment_id = _hidden(db)
    s1 = _strategy(db, investment_id, "S1 refinances", fx.evented(deal.id, dscr=2.0))
    s2 = _strategy(db, investment_id, "S2 inherits", None)

    base = analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)
    inherited = analyze_structured_variant(investment_id, s2, SCENARIO, db_path=db)
    assert type(inherited) is type(base)
    assert inherited.result == base.result
    assert inherited.structured_source_fingerprint == base.structured_source_fingerprint
    assert inherited.capital_structure == base.capital_structure == CapitalStructure(positions=())
    # FP-2: the Base states no structure, so its structured identity is its
    # Project identity, and the inheriting Strategy's is too.
    assert base.structured_source_fingerprint == base.project_source_fingerprint
    assert structured_variant_fingerprint(investment_id, s2, SCENARIO, db_path=db).structured_source_fingerprint == (
        base.structured_source_fingerprint
    )

    refinanced = analyze_structured_variant(investment_id, s1, SCENARIO, db_path=db)
    (event,) = refinanced.result.capital_events
    assert event.event_id == fx.EVENT_ID and event.status.value == "executed"
    assert fx.rf.close(event.sizing.gross_proceeds, 8_000_000)
    assert refinanced.structured_source_fingerprint != base.structured_source_fingerprint
    # The Project half is untouched by the refinance (P-4).
    assert refinanced.project_source_fingerprint == base.project_source_fingerprint


def test_f18_removing_the_replacement_restores_the_base_exactly(db: Path) -> None:
    deal, investment_id = _hidden(db)
    s1 = _strategy(db, investment_id, "S1", fx.evented(deal.id, dscr=2.0))
    base = analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)
    assert analyze_structured_variant(investment_id, s1, SCENARIO, db_path=db).result != base.result

    store.update_strategy(investment_id, s1, name="S1", db_path=db)  # no root overlay: inherit again
    restored = analyze_structured_variant(investment_id, s1, SCENARIO, db_path=db)
    assert restored.result == base.result
    assert restored.structured_source_fingerprint == base.structured_source_fingerprint
    assert restored.capital_structure == base.capital_structure


def test_f18_an_explicit_empty_replacement_drops_the_base_events(db: Path) -> None:
    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.evented(deal.id, dscr=2.0), db_path=db)
    empty = _strategy(db, investment_id, "No structured capital", CapitalStructure(positions=()))
    inherits = _strategy(db, investment_id, "Inherits", None)

    analysis = analyze_structured_variant(investment_id, empty, SCENARIO, db_path=db)
    assert analysis.capital_structure == CapitalStructure(positions=())
    assert not hasattr(analysis.result, "capital_events")
    assert analysis.structured_source_fingerprint == analysis.project_source_fingerprint

    inherited = analyze_structured_variant(investment_id, inherits, SCENARIO, db_path=db)
    assert isinstance(inherited.capital_structure, CapitalStructureWithEvents)
    assert inherited.result == analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db).result


def test_f18_a_strategys_evented_structure_replaces_a_base_with_positions_whole(db: Path) -> None:
    """ST-2: the Strategy's structure is the whole structure. The Base's mezzanine
    does not survive into it, and the Base keeps its own, unevented, result."""

    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.plain(fx.mezz(deal.id)), db_path=db)
    assert investment_id is not None
    own = fx.evented(deal.id, dscr=2.0)
    s1 = _strategy(db, investment_id, "Refinance instead", own)

    analysis = analyze_structured_variant(investment_id, s1, SCENARIO, db_path=db)
    assert analysis.capital_structure == own
    assert {position.position_id for position in analysis.result.positions} == {fx.REPLACEMENT_ID}
    base = analyze_structured_variant(investment_id, BASE, SCENARIO, db_path=db)
    assert type(base.capital_structure) is CapitalStructure
    assert {position.position_id for position in base.result.positions} == {"mezz"}
    assert not hasattr(base.result, "capital_events")


def test_f18_an_event_cannot_be_patched_onto_an_inherited_structure(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Strategy's structure is complete or it is nothing: an event stated
    without the positions it names is refused, never merged with the Base's."""

    deal = fx.base_deal(db)
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.plain(fx.mezz(deal.id)), db_path=db)
    assert investment_id is not None
    event_only = CapitalStructureWithEvents(
        positions=(), events=(fx.unit_event(deal.id, dscr=2.0, retiring=(fx.AuthoredPositionRef(position_id="mezz"),)),)
    )
    with pytest.raises(StrategyValidationError) as refused:
        _strategy(db, investment_id, "Patch", event_only)
    codes = {issue.source_code for issue in refused.value.issues}
    assert {"replacement_position_not_found", "retiring_position_not_found"} <= codes
    assert all(issue.domain is StrategyDomain.CAPITAL_STRUCTURE for issue in refused.value.issues)

    # And through the API door: the overlay content holds exactly what it states.
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    client = TestClient(api_module.app)
    body = {
        "name": "Patch",
        "root_overlays": [
            {
                "domain": "capital_structure",
                "content": {"capital_events": [api_module._wire(event_only.events[0])]},
            }
        ],
    }
    response = client.post(f"/investments/{investment_id}/strategies", json=body)
    assert response.status_code == 422, response.text


# =============================================================================
# P-8 -- one event id, one economic event
# =============================================================================


def _two_unit_investment(db: Path) -> tuple[str, str, str]:
    a = fx.base_deal(db, name="A")
    b = fx.base_deal(db, name="B")
    investment = create_investment(db, a, b)
    return investment.id, a.id, b.id


def _on_b(b: str, **kwargs: Any) -> CapitalStructureWithEvents:
    """Event ``refi-year-2`` -- the Base's id -- but scoped to Unit B, with its
    own replacement id so only the event identity can conflict."""

    return fx.evented(b, replacement_id="refi-loan-b", **kwargs)


def _conflict(error: pytest.ExceptionInfo[CapitalEventIdentityConflictError]) -> set[str]:
    return {issue.code.value for issue in error.value.issues}


def test_p8_a_scope_conflict_is_refused_when_a_strategy_is_created(db: Path) -> None:
    investment_id, a, b = _two_unit_investment(db)
    store.set_base_capital_structure(investment_id, fx.evented(a, dscr=2.0), db_path=db)
    with pytest.raises(CapitalEventIdentityConflictError) as refused:
        _strategy(db, investment_id, "B instead", _on_b(b, dscr=2.0))
    assert _conflict(refused) == {"capital_event_scope_conflict"}
    assert [entry.strategy_id for entry in store.list_investment_capital_structures(investment_id, db_path=db).strategies] == []


def test_p8_a_scope_conflict_is_refused_when_a_strategy_is_updated(db: Path) -> None:
    investment_id, a, b = _two_unit_investment(db)
    store.set_base_capital_structure(investment_id, fx.evented(a, dscr=2.0), db_path=db)
    strategy_id = _strategy(db, investment_id, "Plain", fx.plain(fx.mezz(a)))
    with pytest.raises(CapitalEventIdentityConflictError) as refused:
        store.update_strategy(investment_id, strategy_id, name="Plain", root_overlays=_overlay(_on_b(b, dscr=2.0)), db_path=db)
    assert _conflict(refused) == {"capital_event_scope_conflict"}
    (entry,) = store.list_investment_capital_structures(investment_id, db_path=db).strategies
    assert entry.capital_structure == fx.plain(fx.mezz(a))


def test_p8_a_scope_conflict_is_refused_when_the_base_is_replaced(db: Path) -> None:
    investment_id, a, b = _two_unit_investment(db)
    _strategy(db, investment_id, "B", _on_b(b, dscr=2.0))
    with pytest.raises(CapitalEventIdentityConflictError) as refused:
        store.set_base_capital_structure(investment_id, fx.evented(a, dscr=2.0), db_path=db)
    assert _conflict(refused) == {"capital_event_scope_conflict"}
    assert store.get_base_capital_structure(investment_id, db_path=db) == CapitalStructure(positions=())


def test_p8_a_third_strategy_conflicting_with_another_strategy_is_refused(db: Path) -> None:
    investment_id, a, b = _two_unit_investment(db)
    _strategy(db, investment_id, "A", fx.evented(a, dscr=2.0))
    with pytest.raises(CapitalEventIdentityConflictError) as refused:
        _strategy(db, investment_id, "B", _on_b(b, dscr=2.0))
    assert _conflict(refused) == {"capital_event_scope_conflict"}


def test_p8_the_api_refuses_with_the_stable_code(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    investment_id, a, b = _two_unit_investment(db)
    client = TestClient(api_module.app)
    wire_a = api_module._wire(fx.evented(a, dscr=2.0))
    assert client.put(f"/investments/{investment_id}/capital-structure", json=wire_a).status_code == 200
    response = client.post(
        f"/investments/{investment_id}/strategies",
        json={"name": "B", "root_overlays": [{"domain": "capital_structure", "content": api_module._wire(_on_b(b, dscr=2.0))}]},
    )
    assert response.status_code == 422
    (issue,) = response.json()["detail"]
    assert issue["code"] == "capital_event_scope_conflict" and issue["event_id"] == fx.EVENT_ID and issue["field"] == "scope"
    # Nothing was stored for the refused Strategy.
    assert list(store.list_strategies(investment_id, db_path=db)) == []


def test_p8_timing_constraints_retirements_and_costs_may_differ(db: Path) -> None:
    investment_id, a, _ = _two_unit_investment(db)
    store.set_base_capital_structure(investment_id, fx.evented(a, dscr=2.0), db_path=db)
    different = fx.evented(a, fixed=5_000_000.0, month=36, costs=(fx.rf.third_party(1_000.0),), label="Renamed")
    strategy_id = _strategy(db, investment_id, "Different terms", different)
    (entry,) = store.list_investment_capital_structures(investment_id, db_path=db).strategies
    assert entry.strategy_id == strategy_id and entry.capital_structure == different


def test_p8_identity_is_the_event_id_never_the_label(db: Path) -> None:
    investment_id, a, b = _two_unit_investment(db)
    store.set_base_capital_structure(investment_id, fx.evented(a, dscr=2.0, label="Same label"), db_path=db)
    # A different id with the same label and another scope is another event.
    _strategy(db, investment_id, "B", fx.evented(b, dscr=2.0, event_id="refi-b", replacement_id="refi-loan-b", label="Same label"))
    # The same id renamed is the same event: accepted.
    _strategy(db, investment_id, "Renamed", fx.evented(a, dscr=2.0, label="A new name"))


def test_p8_a_kind_conflict_is_reported_by_the_one_rule() -> None:
    """V1 has one event kind, so a valid stored structure cannot hold another;
    the rule itself still refuses one id naming two kinds, and reports the
    kind before the scope."""

    event = fx.unit_event("a", dscr=2.0)
    other = dataclasses.replace(event, kind=_Kind("recapitalization"), scope=fx.scope("b"))  # type: ignore[arg-type]
    owners = [
        (StructureOwner(kind=StructureOwnerKind.BASE, owner_id="i", label="the Base Capital Structure"),
         CapitalStructureWithEvents(positions=(), events=(event,))),
        (StructureOwner(kind=StructureOwnerKind.STRATEGY, owner_id="s", label="Strategy 'X'"),
         CapitalStructureWithEvents(positions=(), events=(other,))),
    ]
    issues = capital_event_identity_issues(owners)
    assert [issue.code for issue in issues] == [
        CapitalEventIdentityIssueCode.CAPITAL_EVENT_KIND_CONFLICT,
        CapitalEventIdentityIssueCode.CAPITAL_EVENT_SCOPE_CONFLICT,
    ]
    assert all(issue.event_id == fx.EVENT_ID for issue in issues)
    # Order of the owners never changes the answer.
    assert capital_event_identity_issues(list(reversed(owners))) == issues


def test_p8_plain_structures_take_no_part() -> None:
    owners = [
        (StructureOwner(kind=StructureOwnerKind.BASE, owner_id="i", label="Base"), fx.plain(fx.mezz("a"))),
        (StructureOwner(kind=StructureOwnerKind.STRATEGY, owner_id="s", label="S"), fx.plain(fx.mezz("a"))),
    ]
    assert capital_event_identity_issues(owners) == ()


class _Kind(str):
    """A stand-in kind token that is not a V1 member, carrying ``.value`` like
    a ``StrEnum`` does."""

    @property
    def value(self) -> str:
        return str(self)
