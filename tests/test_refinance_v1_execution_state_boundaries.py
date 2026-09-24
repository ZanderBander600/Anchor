"""Refinance & Capital Events V1 Stage 1 -- execution-state boundaries.

The three independent-review corrections of Stage 1
(``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 23.4):

1. The R-N succession pair never excuses a Unit's reserved priority 1 while its
   acquisition loan continues, and sizing never omits a continuing loan.
2. ``forward_noi`` returns ``None`` only for an absent scope authority. A
   malformed NOI authority is an engine defect, never
   ``forward_noi_unavailable``; a non-positive NOI stays F12's typed state.
3. An Investment-scope event after a Unit event that did not execute is never
   reported ``EXECUTED``: it is ``UNAVAILABLE`` with
   ``upstream_capital_event_not_executed``, and nothing of its settlement exists.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from _refinance_v1_fixtures import (  # type: ignore[import-not-found]
    EVENT_MONTH,
    INVESTMENT_SCOPE,
    LEGACY,
    REPLACEMENT_ID,
    UNIT,
    authored_ref,
    base_structure,
    base_unit,
    close,
    closing_debt,
    event,
    evented,
    replacement,
    run_investment,
    run_unit,
)

from anchor.capital_structure.contracts import (
    CapitalStructureError,
    CapitalStructureStatus,
    CapitalStructureUnit,
    CommonEquityUnavailableReason,
    PositionClass,
    PositionScope,
    ScopeKind,
    ShortfallResolution,
)
from anchor.capital_structure.execution_contracts import PositionUnavailableReason
from anchor.capital_structure.foundation import analyze_unit_capital_structure
from anchor.capital_structure.funding import unit_price_basis
from anchor.capital_structure.refinance import (
    InvestmentRefinanceAuthority,
    UnitRefinanceAuthority,
    forward_noi,
    plan_refinance,
)
from anchor.capital_structure.refinance_contracts import RefinanceStatus, RefinanceUnavailableReason
from anchor.capital_structure.validation import validate_capital_structure
from anchor.consolidation import ConsolidationUnit, consolidate
from anchor.valuation.contracts import ValuationError


def _codes(structure: object) -> list[str]:
    return [
        issue.code.value
        for issue in validate_capital_structure(structure, member_unit_ids=(UNIT,), acquisition_loan_unit_ids=(UNIT,))
    ]


def _unit_authority(**overrides: Any) -> UnitRefinanceAuthority:
    terms, results = base_unit(**overrides)
    loan = analyze_unit_capital_structure(unit_id=UNIT, terms=terms, results=results).legacy_acquisition_loan
    return UnitRefinanceAuthority(unit_id=UNIT, terms=terms, results=results, legacy_loan=loan)


def _plan(structure: Any, *, unit: UnitRefinanceAuthority | None) -> Any:
    terms, _ = base_unit()
    (refinance,) = structure.events
    return plan_refinance(
        refinance,
        scope_positions=structure.positions,
        hold_period=terms.hold_period,
        price_basis=unit_price_basis(terms),
        valuations=None,
        unit=unit,
        investment=None,
    )


# =============================================================================
# 1. The acquisition loan's reserved priority (R-N)
# =============================================================================


def _priority_1_pair() -> Any:
    """An authored priority-1 senior and its priority-1 replacement, while the
    Unit's acquisition loan continues: the defect the review found accepted."""

    senior = closing_debt(
        "senior", amount=1_000_000.0, priority=1, rate=0.1, position_class=PositionClass.SENIOR_DEBT
    )
    return evented(senior, replacement(priority=1), events=(event(dscr=2.0, retiring=(authored_ref("senior"),)),))


def test_a_priority_1_succession_pair_is_refused_while_the_acquisition_loan_continues() -> None:
    assert _codes(_priority_1_pair()) == ["duplicate_priority"]
    (issue,) = validate_capital_structure(_priority_1_pair(), member_unit_ids=(UNIT,), acquisition_loan_unit_ids=(UNIT,))
    assert "held by its acquisition loan" in issue.message


def test_the_pair_never_excuses_a_retiring_position_that_overlapped_the_acquisition_loan() -> None:
    """Retiring the loan in the same event does not excuse an authored
    priority-1 position that was outstanding beside it before the event."""

    senior = closing_debt(
        "senior", amount=1_000_000.0, priority=1, rate=0.1, position_class=PositionClass.SENIOR_DEBT
    )
    both = evented(senior, replacement(priority=1), events=(event(dscr=2.0, retiring=(LEGACY, authored_ref("senior"))),))
    assert "duplicate_priority" in _codes(both)


def test_the_replacement_that_succeeds_the_retired_acquisition_loan_holds_priority_1() -> None:
    assert _codes(base_structure(dscr=2.0)) == []


def test_a_junior_succession_pair_with_no_other_occupant_is_valid() -> None:
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.1)
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT)
    assert _codes(evented(mezz, heir, events=(event(dscr=2.0, retiring=(authored_ref("mezz"),)),))) == []


def test_ordinary_duplicate_priorities_are_still_refused() -> None:
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.1)
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT)
    other = closing_debt("other", amount=500_000.0, priority=2, rate=0.1)
    crowded = evented(mezz, heir, other, events=(event(dscr=2.0, retiring=(authored_ref("mezz"),)),))
    assert _codes(crowded) == ["duplicate_priority"]


def test_sizing_never_omits_a_continuing_acquisition_loan() -> None:
    """Below validation, a replacement claiming priority 1 beside a continuing
    acquisition loan is an engine defect -- never a sizing without the loan."""

    with pytest.raises(CapitalStructureError, match="continuing acquisition loan"):
        _plan(_priority_1_pair(), unit=_unit_authority())


# =============================================================================
# 2. The forward-NOI authority boundary
# =============================================================================


def test_a_non_positive_forward_noi_is_a_value_and_keeps_its_typed_state() -> None:
    authority = _unit_authority(current_noi=0.0)
    assert forward_noi(PositionScope(kind=ScopeKind.UNIT, unit_id=UNIT), model_month=EVENT_MONTH, unit=authority, investment=None) == 0.0
    terms, results = base_unit(current_noi=0.0)
    outcome = run_unit(base_structure(dscr=2.0), terms=terms, results=results, with_valuation=False).capital_events[0]
    assert outcome.status is RefinanceStatus.UNAVAILABLE
    assert outcome.unavailable_reason is RefinanceUnavailableReason.NON_POSITIVE_FORWARD_NOI


def test_only_an_absent_scope_authority_is_an_unavailable_forward_noi() -> None:
    unit_scope = PositionScope(kind=ScopeKind.UNIT, unit_id=UNIT)
    assert forward_noi(unit_scope, model_month=EVENT_MONTH, unit=None, investment=None) is None
    assert forward_noi(INVESTMENT_SCOPE, model_month=EVENT_MONTH, unit=None, investment=None) is None
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.1)
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT)
    plan = _plan(evented(mezz, heir, events=(event(dscr=2.0, retiring=(authored_ref("mezz"),)),)), unit=None)
    assert plan.result.status is RefinanceStatus.UNAVAILABLE
    assert plan.result.unavailable_reason is RefinanceUnavailableReason.FORWARD_NOI_UNAVAILABLE
    assert plan.result.noi_dependency.forward_noi is None


def _truncated_unit() -> UnitRefinanceAuthority:
    authority = _unit_authority()
    short = dataclasses.replace(authority.results, noi_by_year=authority.results.noi_by_year[: EVENT_MONTH // 12])
    return dataclasses.replace(authority, results=short)


def test_a_truncated_noi_series_is_an_engine_defect_never_unavailability() -> None:
    unit_scope = PositionScope(kind=ScopeKind.UNIT, unit_id=UNIT)
    with pytest.raises(ValuationError):
        forward_noi(unit_scope, model_month=EVENT_MONTH, unit=_truncated_unit(), investment=None)
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.1)
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT)
    with pytest.raises(ValuationError):
        _plan(evented(mezz, heir, events=(event(dscr=2.0, retiring=(authored_ref("mezz"),)),)), unit=_truncated_unit())


def test_an_invalid_internal_month_is_an_engine_defect_never_unavailability() -> None:
    unit_scope = PositionScope(kind=ScopeKind.UNIT, unit_id=UNIT)
    authority = _unit_authority()
    for month in (18, -12, 60):  # inside a year, before closing, the reserved exit month
        with pytest.raises(ValuationError):
            forward_noi(unit_scope, model_month=month, unit=authority, investment=None)


def test_a_malformed_investment_noi_authority_is_an_engine_defect() -> None:
    units, consolidated = _two_units()
    authority = InvestmentRefinanceAuthority(units=units, consolidated=consolidated)
    with pytest.raises(ValuationError):
        forward_noi(INVESTMENT_SCOPE, model_month=18, unit=None, investment=authority)
    short = dataclasses.replace(
        units[0], results=dataclasses.replace(units[0].results, noi_by_year=units[0].results.noi_by_year[:2])
    )
    with pytest.raises(ValuationError):
        forward_noi(
            INVESTMENT_SCOPE,
            model_month=EVENT_MONTH,
            unit=None,
            investment=InvestmentRefinanceAuthority(units=(short, units[1]), consolidated=consolidated),
        )
    truncated = dataclasses.replace(consolidated, noi_by_year=consolidated.noi_by_year[:2])
    with pytest.raises(ValuationError):
        forward_noi(
            INVESTMENT_SCOPE,
            model_month=EVENT_MONTH,
            unit=None,
            investment=InvestmentRefinanceAuthority(units=units, consolidated=truncated),
        )


def malformed_noi_authorities_are_never_unavailability() -> None:
    """The mutation fixture for correction 2."""

    test_a_truncated_noi_series_is_an_engine_defect_never_unavailability()
    test_an_invalid_internal_month_is_an_engine_defect_never_unavailability()
    test_a_malformed_investment_noi_authority_is_an_engine_defect()


# =============================================================================
# 3. An Investment event after a Unit event that did not execute
# =============================================================================

INVESTMENT_EVENT_ID = "refi-investment"
INVESTMENT_EVENT_LABEL = "Year-4 portfolio refinance"
INVESTMENT_REPLACEMENT_ID = "portfolio-refi"
INVESTMENT_MONTH = 48


def _two_units() -> tuple[tuple[CapitalStructureUnit, ...], Any]:
    """Two Units with no acquisition loan, so Investment-scoped senior debt is
    admitted (CS-5): $800,000 and $600,000 flat NOI."""

    units = []
    for unit_id, noi in (("a", 800_000.0), ("b", 600_000.0)):
        terms, results = base_unit(current_noi=noi, ltv=0.0)
        units.append(CapitalStructureUnit(unit_id=unit_id, terms=terms, results=results))
    consolidated = consolidate(
        [
            ConsolidationUnit(unit_id=u.unit_id, purchase_price=u.terms.purchase_price, hold_period=u.terms.hold_period, results=u.results)
            for u in units
        ],
        transaction_price=sum(u.terms.purchase_price for u in units),
    )
    return tuple(units), consolidated


def _upstream_structure(*, unit_executes: bool) -> Any:
    """Unit 'a' refinances its $1,000,000 senior loan at month 24; that loan
    matures at month 36, so no Unit debt is outstanding after the Investment
    event at month 48 whether or not the Unit event executes, and Section 12.4
    admits the Investment event either way. The Unit replacement also matures
    by month 48. The Investment event retires an $8,000,000 portfolio loan,
    sized at DSCR 2.0 on $1,400,000 forward NOI: $14,000,000 at 5% IO.

    The Unit event sizes by LTV with no valuation authority, so it is
    ``timepoint_not_found``; with ``unit_executes`` it sizes by a fixed cap."""

    a_scope = PositionScope(kind=ScopeKind.UNIT, unit_id="a")
    a_senior = closing_debt(
        "a-senior", amount=1_000_000.0, priority=1, rate=0.05, maturity_month=36,
        position_class=PositionClass.SENIOR_DEBT, scope=a_scope,
    )
    a_heir = replacement(scope=a_scope, maturity_month=48)
    sizing: dict[str, Any] = {"fixed": 900_000.0} if unit_executes else {"ltv": 0.6}
    unit_event = event(
        **sizing,
        retiring=(authored_ref("a-senior"),),
        scope=a_scope,
    )
    portfolio = closing_debt(
        "portfolio-senior", amount=8_000_000.0, priority=1, rate=0.05, io_period=10, maturity_month=120,
        position_class=PositionClass.SENIOR_DEBT, scope=INVESTMENT_SCOPE,
    )
    investment_heir = replacement(
        INVESTMENT_REPLACEMENT_ID, event_id=INVESTMENT_EVENT_ID, month=INVESTMENT_MONTH, scope=INVESTMENT_SCOPE
    )
    investment_event = event(
        dscr=2.0,
        retiring=(authored_ref("portfolio-senior"),),
        scope=INVESTMENT_SCOPE,
        event_id=INVESTMENT_EVENT_ID,
        replacement_id=INVESTMENT_REPLACEMENT_ID,
        month=INVESTMENT_MONTH,
        label=INVESTMENT_EVENT_LABEL,
    )
    return evented(a_senior, a_heir, portfolio, investment_heir, events=(unit_event, investment_event))


def test_an_investment_event_after_an_unexecuted_unit_event_is_upstream_unavailable() -> None:
    units, consolidated = _two_units()
    result = run_investment(_upstream_structure(unit_executes=False), units=units, consolidated=consolidated)

    unit_outcome, investment_outcome = result.capital_events
    assert unit_outcome.status is RefinanceStatus.UNAVAILABLE
    assert unit_outcome.unavailable_reason is RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND

    assert investment_outcome.event_id == INVESTMENT_EVENT_ID
    assert investment_outcome.status is RefinanceStatus.UNAVAILABLE
    assert investment_outcome.unavailable_reason is RefinanceUnavailableReason.UPSTREAM_CAPITAL_EVENT_NOT_EXECUTED
    message = investment_outcome.unavailable_message
    assert f"'{INVESTMENT_EVENT_LABEL}'" in message and f"'{unit_outcome.label}'" in message
    for opaque in (INVESTMENT_EVENT_ID, INVESTMENT_REPLACEMENT_ID, REPLACEMENT_ID, "a-senior", "portfolio-senior"):
        assert opaque not in message, opaque
    # Nothing of a settlement exists.
    assert investment_outcome.sizing.gross_proceeds is None
    assert investment_outcome.sizing.binding == () and investment_outcome.sizing.tie is False
    assert investment_outcome.funding is None and investment_outcome.bridge is None
    assert investment_outcome.payoffs is None
    # Its capacities stay, as contractual facts: it would otherwise have sized.
    (dscr,) = investment_outcome.sizing.capacities
    assert close(dscr.capacity, 14_000_000)

    investment_replacements = [u for u in result.unexecuted_positions if u.position_id == INVESTMENT_REPLACEMENT_ID]
    assert len(investment_replacements) == 1
    (unexecuted,) = investment_replacements
    assert unexecuted.event_id == INVESTMENT_EVENT_ID
    assert unexecuted.unavailable_reason is PositionUnavailableReason.REFINANCE_UNAVAILABLE
    assert [u.position_id for u in result.unexecuted_positions] == [REPLACEMENT_ID, INVESTMENT_REPLACEMENT_ID]
    assert all(position.position_id != INVESTMENT_REPLACEMENT_ID for position in result.positions)

    assert result.common_equity.status is CapitalStructureStatus.REFINANCE_UNAVAILABLE
    assert result.common_equity.unavailable_reason is CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE
    assert result.common_equity.cash_flows is None
    assert result.common_equity.event_cash_flows is None and result.common_equity.recurring_cash_flows is None
    assert not any(outcome.status is RefinanceStatus.EXECUTED and outcome.bridge is None for outcome in result.capital_events)


def test_an_investment_event_executes_when_every_upstream_unit_event_executes() -> None:
    units, consolidated = _two_units()
    result = run_investment(_upstream_structure(unit_executes=True), units=units, consolidated=consolidated)

    unit_outcome, investment_outcome = result.capital_events
    assert unit_outcome.status is RefinanceStatus.EXECUTED
    assert investment_outcome.status is RefinanceStatus.EXECUTED
    assert investment_outcome.unavailable_reason is None
    assert close(investment_outcome.sizing.gross_proceeds, 14_000_000)
    assert close(investment_outcome.bridge.net_event_cash, 6_000_000)
    assert investment_outcome.funding.position_id == INVESTMENT_REPLACEMENT_ID
    assert result.unexecuted_positions == ()
    assert result.common_equity.cash_flows is not None
    assert close(result.common_equity.event_cash_flows[4], 6_000_000)
    assert close(result.common_equity.event_cash_flows[2], unit_outcome.bridge.net_event_cash)


def _mixed_structure() -> Any:
    """The upstream structure with a second Unit event that is ``BLOCKED``:
    Unit 'b' refinances its own $1,000,000 senior loan at month 24, while a
    $3,000,000 junior at 20% over three years leaves an unresolved Funding
    Requirement in year 1. Every Unit debt of 'b' is repaid by month 48 too,
    so Section 12.4 still admits the Investment event."""

    b_scope = PositionScope(kind=ScopeKind.UNIT, unit_id="b")
    b_senior = closing_debt(
        "b-senior", amount=1_000_000.0, priority=1, rate=0.05, maturity_month=36,
        position_class=PositionClass.SENIOR_DEBT, scope=b_scope,
    )
    b_junior = closing_debt(
        "b-junior", amount=3_000_000.0, priority=2, rate=0.20, amortization=3, maturity_month=36,
        scope=b_scope, resolution=ShortfallResolution.UNRESOLVED,
    )
    b_heir = replacement("b-refi", event_id="refi-b", scope=b_scope, maturity_month=48)
    b_event = event(
        fixed=900_000.0, retiring=(authored_ref("b-senior"),), scope=b_scope,
        event_id="refi-b", replacement_id="b-refi", label="Unit B refinance",
    )
    upstream = _upstream_structure(unit_executes=False)
    return evented(*upstream.positions, b_senior, b_junior, b_heir, events=(*upstream.events, b_event))


def test_an_unexecuted_unit_event_outranks_a_blocked_one_downstream() -> None:
    """Section 23.4: with one Unit event unavailable and another blocked by
    unresolved funding, the would-be-executed Investment event is
    ``UNAVAILABLE`` with ``upstream_capital_event_not_executed`` -- resolving
    the funding alone would not let it execute, so ``BLOCKED`` would mislead."""

    units, consolidated = _two_units()
    result = run_investment(_mixed_structure(), units=units, consolidated=consolidated)

    a_outcome, b_outcome, investment_outcome = result.capital_events
    assert a_outcome.status is RefinanceStatus.UNAVAILABLE
    assert a_outcome.unavailable_reason is RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND
    assert b_outcome.status is RefinanceStatus.BLOCKED
    assert b_outcome.unavailable_reason is RefinanceUnavailableReason.UPSTREAM_UNRESOLVED_FUNDING

    assert investment_outcome.event_id == INVESTMENT_EVENT_ID
    assert investment_outcome.status is RefinanceStatus.UNAVAILABLE
    assert investment_outcome.unavailable_reason is RefinanceUnavailableReason.UPSTREAM_CAPITAL_EVENT_NOT_EXECUTED
    message = investment_outcome.unavailable_message
    assert f"'{INVESTMENT_EVENT_LABEL}'" in message and f"'{a_outcome.label}'" in message
    for opaque in (
        INVESTMENT_EVENT_ID, INVESTMENT_REPLACEMENT_ID, REPLACEMENT_ID, "refi-b", "b-refi",
        "a-senior", "b-senior", "b-junior", "portfolio-senior", "hold_year",
    ):
        assert opaque not in message, opaque

    assert investment_outcome.sizing.gross_proceeds is None and investment_outcome.sizing.binding == ()
    assert investment_outcome.payoffs is None
    assert investment_outcome.funding is None and investment_outcome.bridge is None
    assert [u.position_id for u in result.unexecuted_positions].count(INVESTMENT_REPLACEMENT_ID) == 1
    assert all(position.position_id != INVESTMENT_REPLACEMENT_ID for position in result.positions)

    # Common Equity follows the dominant non-executed refinance, not the
    # simultaneous unresolved funding (Section 15.4): resolving that funding
    # alone would not make it reportable.
    equity = result.common_equity
    assert equity.status is CapitalStructureStatus.REFINANCE_UNAVAILABLE
    assert equity.unavailable_reason is CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE
    assert equity.cash_flows is None
    assert equity.event_cash_flows is None and equity.recurring_cash_flows is None
    assert equity.irr is None and equity.equity_multiple is None and equity.total_profit is None
    for opaque in ("refi-b", "b-refi", "b-junior", "hold_year", INVESTMENT_EVENT_ID, INVESTMENT_REPLACEMENT_ID):
        assert opaque not in equity.unavailable_message, opaque


def _blocked_only_structure() -> Any:
    """The mixed structure with Unit 'a''s event executing: Unit 'b' is the
    only non-executing Unit event, and it is ``BLOCKED``."""

    mixed = _mixed_structure()
    executing = next(item for item in _upstream_structure(unit_executes=True).events if item.scope.unit_id == "a")
    return evented(*mixed.positions, events=tuple(executing if item.scope.unit_id == "a" else item for item in mixed.events))


def test_a_blocked_only_upstream_blocks_the_investment_event_and_keeps_unresolved_funding() -> None:
    """Section 23.4: with no Unit event ``UNAVAILABLE`` or ``NOT_EXECUTABLE``
    and one ``BLOCKED`` by unresolved funding, the downstream event is
    ``BLOCKED`` -- never ``EXECUTED`` with nothing settled -- and Common Equity
    keeps P7.7's unresolved-funding reason."""

    units, consolidated = _two_units()
    result = run_investment(_blocked_only_structure(), units=units, consolidated=consolidated)

    a_outcome, b_outcome, investment_outcome = result.capital_events
    assert a_outcome.status is RefinanceStatus.EXECUTED
    assert b_outcome.status is RefinanceStatus.BLOCKED
    assert investment_outcome.status is RefinanceStatus.BLOCKED
    assert investment_outcome.unavailable_reason is RefinanceUnavailableReason.UPSTREAM_UNRESOLVED_FUNDING
    assert investment_outcome.funding is None and investment_outcome.bridge is None
    message = investment_outcome.unavailable_message
    assert f"'{INVESTMENT_EVENT_LABEL}' is blocked" in message and "B Junior in Hold Year 1" in message
    for opaque in ("b-junior", "hold_year", INVESTMENT_EVENT_ID, INVESTMENT_REPLACEMENT_ID, "portfolio-senior"):
        assert opaque not in message, opaque

    equity = result.common_equity
    assert equity.status is CapitalStructureStatus.UNRESOLVED_FUNDING
    assert equity.unavailable_reason is CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
    assert equity.cash_flows is None and equity.event_cash_flows is None
