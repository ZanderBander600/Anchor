"""Refinance & Capital Events V1 Stage 1 -- analyst-facing message boundaries.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 15.3, 15.4 and
23.4. No opaque position, event, replacement or Funding Requirement identity
appears in any analyst-facing message a ``RefinancedCapitalResult`` carries,
and the typed identity fields are untouched.

Every structure here is an existing Stage 1 fixture with each authored identity
re-seeded under a recognizable ``ZZID-`` prefix; names and labels are unchanged.
Each result is then walked recursively: every ``unavailable_message`` and
``explanation`` at any depth is checked against the prefix and against every
identity the result itself carries. Unit ids are not checked: the engine's
Units carry no analyst name, so a Unit is named by its id throughout P7.7.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from _refinance_v1_fixtures import (  # type: ignore[import-not-found]
    authored_ref,
    base_structure,
    closing_debt,
    event,
    evented,
    replacement,
    run_investment,
    run_unit,
)
from test_refinance_v1_execution_state_boundaries import (  # type: ignore[import-not-found]
    _mixed_structure,
    _two_units,
    _upstream_structure,
)

from anchor.capital_structure import refinance_execution
from anchor.capital_structure.contracts import (
    CapitalStructureStatus,
    CommonEquityUnavailableReason,
    PositionClass,
    RefinanceProceeds,
    ShortfallResolution,
)
from anchor.capital_structure.events import AuthoredPositionRef
from anchor.capital_structure.execution_contracts import PositionResultStatus
from anchor.capital_structure.refinance_contracts import RefinanceStatus

SEED = "ZZID-"
_MESSAGE_FIELDS = frozenset({"unavailable_message", "explanation"})
_UNNAMED_IDENTITIES = frozenset({"unit_id", "unit_ids"})


# =============================================================================
# Seeding and walking
# =============================================================================


def _seed(identity: str) -> str:
    return f"{SEED}{identity}"


def _seeded_position(position: Any) -> Any:
    funding = tuple(
        dataclasses.replace(
            item,
            event_id=_seed(item.event_id),
            amount_rule=dataclasses.replace(item.amount_rule, capital_event_id=_seed(item.amount_rule.capital_event_id))
            if isinstance(item.amount_rule, RefinanceProceeds)
            else item.amount_rule,
        )
        for item in position.funding
    )
    terms = position.terms
    if getattr(terms, "fees", None):
        terms = dataclasses.replace(terms, fees=tuple(dataclasses.replace(fee, fee_id=_seed(fee.fee_id)) for fee in terms.fees))
    return dataclasses.replace(position, position_id=_seed(position.position_id), funding=funding, terms=terms)


def _seeded_ref(ref: Any) -> Any:
    return AuthoredPositionRef(position_id=_seed(ref.position_id)) if isinstance(ref, AuthoredPositionRef) else ref


def _seeded(structure: Any) -> Any:
    """``structure`` with every authored position, event, funding, fee and
    cost identity under the seed. Names and labels are unchanged."""

    events = tuple(
        dataclasses.replace(
            item,
            event_id=_seed(item.event_id),
            replacement_position_id=_seed(item.replacement_position_id),
            retiring=tuple(_seeded_ref(ref) for ref in item.retiring),
            costs=tuple(
                dataclasses.replace(
                    line,
                    cost_id=_seed(line.cost_id),
                    recipient=None if line.recipient is None else _seeded_ref(line.recipient),
                )
                for line in item.costs
            ),
        )
        for item in structure.events
    )
    return evented(*(_seeded_position(position) for position in structure.positions), events=events)


def _walk(value: Any, path: str = "result") -> Iterator[tuple[str, str, Any]]:
    """Every ``(path, field, value)`` of every dataclass in ``value``."""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            item = getattr(value, field.name)
            yield path, field.name, item
            yield from _walk(item, f"{path}.{field.name}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def _messages(result: Any) -> list[tuple[str, str]]:
    return [
        (f"{path}.{name}", value)
        for path, name, value in _walk(result)
        if name in _MESSAGE_FIELDS and isinstance(value, str)
    ]


def _identities(result: Any) -> set[str]:
    found: set[str] = set()
    for _, name, value in _walk(result):
        if name in _UNNAMED_IDENTITIES or not (name.endswith("_id") or name.endswith("_ids")):
            continue
        if isinstance(value, str):
            found.add(value)
        elif isinstance(value, tuple):
            found.update(item for item in value if isinstance(item, str))
    return found


def _assert_no_identity_in_any_message(result: Any) -> list[tuple[str, str]]:
    messages = _messages(result)
    identities = _identities(result)
    assert any(identity.startswith(SEED) for identity in identities), "the seed never reached the result"
    for where, text in messages:
        assert SEED not in text, (where, text)
        for identity in identities:
            assert identity not in text, (where, identity, text)
    return messages


def _blank(value: Any) -> Any:
    """``value`` with every message emptied, for comparing everything else."""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        changes = {
            field.name: ("" if field.name in _MESSAGE_FIELDS and isinstance(getattr(value, field.name), str) else _blank(getattr(value, field.name)))
            for field in dataclasses.fields(value)
        }
        return dataclasses.replace(value, **changes)
    if isinstance(value, tuple):
        return tuple(_blank(item) for item in value)
    return value


# =============================================================================
# The eight representative results
# =============================================================================


def _named(position: Any, name: str) -> Any:
    return dataclasses.replace(position, name=name)


def unavailable_unit_event() -> Any:
    """1 and 8: an unavailable event and its unexecuted replacement."""

    return run_unit(_seeded(base_structure(ltv=0.65)), with_valuation=False)


def not_executable_unit_event() -> Any:
    """2: a non-positive capacity (F22a's junior refinance)."""

    mezz = _named(closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.10, io_period=10, maturity_month=120), "Mezzanine loan")
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT)
    return run_unit(_seeded(evented(mezz, heir, events=(event(ltv=0.40, dscr=1.25, retiring=(authored_ref("mezz"),)),))))


def blocked_unit_event() -> Any:
    """3, 4 and 6 in one Unit: a blocked event, an unresolved position, a
    position blocked by it, and Common Equity with unresolved funding only."""

    junior = _named(
        closing_debt(
            "junior", amount=3_000_000.0, priority=2, rate=0.20, amortization=3, maturity_month=36,
            resolution=ShortfallResolution.UNRESOLVED,
        ),
        "Junior loan",
    )
    subordinate = _named(closing_debt("subordinate", amount=100_000.0, priority=3, rate=0.10, io_period=10), "Subordinate note")
    return run_unit(_seeded(evented(replacement(), junior, subordinate, events=(event(fixed=7_000_000.0),))))


def blocked_only_investment() -> Any:
    """5 and 6 across scopes: Unit 'b' blocked, Unit 'a' executed, and the
    Investment scope blocked by the Unit's unresolved requirement."""

    mixed = _mixed_structure()
    executing = next(item for item in _upstream_structure(unit_executes=True).events if item.scope.unit_id == "a")
    structure = evented(
        *mixed.positions, events=tuple(executing if item.scope.unit_id == "a" else item for item in mixed.events)
    )
    units, consolidated = _two_units()
    return run_investment(_seeded(structure), units=units, consolidated=consolidated)


def mixed_investment() -> Any:
    """7: one Unit event unavailable, another blocked."""

    units, consolidated = _two_units()
    return run_investment(_seeded(_mixed_structure()), units=units, consolidated=consolidated)


_CASES: dict[str, Callable[[], Any]] = {
    "unavailable": unavailable_unit_event,
    "not_executable": not_executable_unit_event,
    "blocked_unit": blocked_unit_event,
    "blocked_only_investment": blocked_only_investment,
    "mixed_investment": mixed_investment,
}


def _statuses(result: Any) -> set[object]:
    return {
        *(outcome.status for outcome in result.capital_events),
        *(position.status for position in result.positions),
        result.common_equity.unavailable_reason,
    }


def test_the_cases_cover_every_required_state() -> None:
    seen: set[object] = set()
    for build in _CASES.values():
        seen |= _statuses(build())
    assert {
        RefinanceStatus.UNAVAILABLE,
        RefinanceStatus.NOT_EXECUTABLE,
        RefinanceStatus.BLOCKED,
        PositionResultStatus.UNRESOLVED_FUNDING,
        PositionResultStatus.BLOCKED_BY_SENIOR_UNRESOLVED,
        PositionResultStatus.REFINANCE_UNAVAILABLE,
        CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT,
        CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE,
    } <= seen
    assert unavailable_unit_event().unexecuted_positions
    assert blocked_unit_event().funding_requirements


@pytest.mark.parametrize("case", sorted(_CASES))
def test_no_identity_appears_in_any_analyst_facing_message(case: str) -> None:
    messages = _assert_no_identity_in_any_message(_CASES[case]())
    assert messages, case


def no_identity_in_any_message() -> None:
    """The mutation fixture: every case at once."""

    for build in _CASES.values():
        _assert_no_identity_in_any_message(build())


def test_messages_name_positions_events_and_periods() -> None:
    result = blocked_unit_event()
    (outcome,) = result.capital_events
    assert outcome.unavailable_message.startswith(f"'{outcome.label}' is blocked: ")
    assert "Junior loan in Hold Year 1" in outcome.unavailable_message
    by_name = {position.name: position for position in result.positions}
    assert "Junior loan in Hold Year 1" in by_name["Subordinate note"].unavailable_message
    assert "in Hold Year 1" in by_name["Junior loan"].unavailable_message
    assert "Junior loan in Hold Year 1" in result.common_equity.unavailable_message
    unresolved = [requirement for requirement in result.funding_requirements if requirement.status.value == "unresolved"]
    assert unresolved and all(requirement.explanation.startswith("Junior loan (Unit u1) was owed ") for requirement in unresolved)


@pytest.mark.parametrize("case", sorted(_CASES))
def test_presentation_changes_messages_only(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Identities, amounts, statuses and order are exactly what the result
    carries without the Section 15.3 presentation; only messages differ."""

    presented = _CASES[case]()
    monkeypatch.setattr(refinance_execution, "_presented_requirement", lambda requirement, names: requirement)
    monkeypatch.setattr(refinance_execution, "_presented_position", lambda position, names, requirements: position)
    monkeypatch.setattr(refinance_execution, "_presented_common_equity", lambda common_equity, names, requirements: common_equity)
    raw = _CASES[case]()
    assert repr(_blank(presented)) == repr(_blank(raw))
    assert _identities(presented) == _identities(raw)
    assert [r.requirement_id for r in presented.funding_requirements] == [r.requirement_id for r in raw.funding_requirements]
    for mine, theirs in zip(presented.positions, raw.positions, strict=True):
        assert mine.blocking_requirement_ids == theirs.blocking_requirement_ids


def test_requirements_stay_one_object_wherever_they_appear() -> None:
    result = blocked_unit_event()
    top = {requirement.requirement_id: requirement for requirement in result.funding_requirements}
    for position in result.positions:
        for requirement in position.funding_requirements:
            assert requirement == top[requirement.requirement_id]
        for claim in position.annual_claims:
            requirement = claim.settlement.funding_requirement
            if requirement is not None:
                assert requirement == top[requirement.requirement_id]


# =============================================================================
# Common Equity precedence (Section 15.4)
# =============================================================================


def test_a_non_executed_event_outranks_unresolved_funding_for_common_equity() -> None:
    equity = mixed_investment().common_equity
    assert equity.status is CapitalStructureStatus.REFINANCE_UNAVAILABLE
    assert equity.unavailable_reason is CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE
    assert equity.cash_flows is None and equity.irr is None and equity.equity_multiple is None


def test_blocked_only_keeps_the_unresolved_funding_reason() -> None:
    for result in (blocked_unit_event(), blocked_only_investment()):
        equity = result.common_equity
        assert equity.status is CapitalStructureStatus.UNRESOLVED_FUNDING
        assert equity.unavailable_reason is CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
        assert equity.cash_flows is None
        assert all(outcome.status is not RefinanceStatus.UNAVAILABLE for outcome in result.capital_events)
