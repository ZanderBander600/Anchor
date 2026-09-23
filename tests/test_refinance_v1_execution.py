"""Refinance & Capital Events V1 Stage 1 -- execution, the bridge and
conservation.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 7, 10, 11, 12.4
and 17, and fixtures F5-F10, F15 and F15b; invariants INV-1 to INV-9, INV-11,
INV-15 and INV-16.

Every expected figure is the contract's hand arithmetic on the stated base
case, or an accounting identity over the engine's own outputs; none is read
back from the code under test.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction
from typing import Any

import pytest
from _refinance_v1_fixtures import (  # type: ignore[import-not-found]
    EVENT_ID,
    INVESTMENT_SCOPE,
    LEGACY,
    LEGACY_ANNUAL,
    LEGACY_BALANCE_AT_60,
    LEGACY_PAYOFF_AT_24,
    REPLACEMENT_ID,
    UNIT,
    authored_ref,
    base_structure,
    base_unit,
    close,
    closing_debt,
    event,
    evented,
    exit_fee,
    lender_fee,
    oracle_npv,
    plain,
    replacement,
    run_investment,
    run_unit,
    third_party,
    unit_scope,
)

from anchor.capital_structure.contracts import (
    CapitalStructureStatus,
    CapitalStructureUnit,
    CommonEquityUnavailableReason,
    FundingRequirementStatus,
    PositionClass,
    ShortfallResolution,
)
from anchor.capital_structure.execution_contracts import (
    CapitalStructureExecutionError,
    ExecutionIssueCode,
    PositionCashFlowKind,
    PositionResultStatus,
)
from anchor.capital_structure.refinance_contracts import (
    BridgeDirection,
    RefinanceStatus,
    RefinanceUnavailableReason,
    RefinancedCapitalResult,
)
from anchor.consolidation.contracts import ConsolidationUnit
from anchor.consolidation.engine import consolidate

F5_COSTS = {"replacement_fees": (lender_fee(80_000.0),), "costs": (third_party(40_000.0),)}


def _f5(**sizing: Any) -> Any:
    return run_unit(base_structure(**{"ltv": 0.70, "dscr": 2.0, **F5_COSTS, **sizing}))


def _position(result: Any, position_id: str) -> Any:
    (found,) = [position for position in result.positions if position.position_id == position_id]
    return found


def _delta(result: Any) -> list[Fraction]:
    _, results = base_unit()
    return [Fraction(a) - Fraction(b) for a, b in zip(result.common_equity.cash_flows, results.levered_cash_flows, strict=True)]


# =============================================================================
# F5-F7: the bridge, its sign and the Common Equity decomposition
# =============================================================================


def test_f5_positive_net_proceeds_are_a_common_equity_distribution() -> None:
    result = _f5()
    assert isinstance(result, RefinancedCapitalResult)
    (outcome,) = result.capital_events
    bridge = outcome.bridge
    assert close(bridge.gross_proceeds, 8_000_000) and bridge.payoffs == LEGACY_PAYOFF_AT_24
    assert bridge.replacement_lender_fees == 80_000 and bridge.retiring_lender_fees == 0 and bridge.third_party_costs == 40_000
    assert close(bridge.net_event_cash, 2_360_000) and bridge.direction is BridgeDirection.DISTRIBUTION
    expected = [0, 0, 2_360_000, -160_000, -160_000, -3_360_000]
    for got, want in zip(_delta(result), expected, strict=True):
        assert close(got, want)
    assert close(sum(_delta(result)), -1_320_000)


def test_f5_the_common_equity_decomposition_is_recurring_plus_event() -> None:
    common = _f5().common_equity
    assert common.event_cash_flows[:2] == (0.0, 0.0) and common.event_cash_flows[3:] == (0.0, 0.0, 0.0)
    assert close(common.event_cash_flows[2], 2_360_000)
    for final, recurring, event_cash in zip(common.cash_flows, common.recurring_cash_flows, common.event_cash_flows, strict=True):
        assert close(final, Fraction(recurring) + Fraction(event_cash))
    _, results = base_unit()
    assert common.recurring_cash_flows[2] == results.levered_cash_flows[2]  # the event is not recurring cash


def test_f6_negative_net_cash_is_an_explicit_contribution_not_a_funding_requirement() -> None:
    result = _f5(fixed=5_000_000.0)
    (outcome,) = result.capital_events
    assert close(outcome.bridge.net_event_cash, -640_000) and outcome.bridge.direction is BridgeDirection.CONTRIBUTION
    assert result.funding_requirements == ()
    assert close(_delta(result)[2], -640_000)
    assert result.status is CapitalStructureStatus.COMPLETE


def test_f7_an_exact_zero_is_computed_never_unavailable() -> None:
    result = _f5(fixed=5_640_000.0)
    (outcome,) = result.capital_events
    assert outcome.status is RefinanceStatus.EXECUTED
    assert outcome.bridge.net_event_cash == 0.0 and outcome.bridge.direction is BridgeDirection.ZERO
    assert result.common_equity.event_cash_flows[2] == 0.0 and _delta(result)[2] == 0


def test_proceeds_never_cure_an_earlier_operating_shortfall() -> None:
    """A year-2 claim of a junior position is settled against year-2 operating
    cash before the event cash exists, exactly as without a refinance."""

    junior = closing_debt(
        "junior",
        amount=3_000_000.0,
        priority=2,
        rate=0.20,
        amortization=3,
        maturity_month=36,
        resolution=ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
    )
    with_event = run_unit(evented(replacement(), junior, events=(event(fixed=9_000_000.0),)))
    without = run_unit(plain(junior))
    year_2 = lambda result: [c for c in _position(result, "junior").annual_claims if c.hold_year == 2][0]  # noqa: E731
    assert year_2(with_event).settlement.equity_contribution == year_2(without).settlement.equity_contribution > 0


# =============================================================================
# F8-F9: legacy retirement, the splice, replacement service and sale payoff
# =============================================================================


def test_f8_the_acquisition_loan_retires_at_the_event() -> None:
    terms, results = base_unit()
    before = repr((terms, results))
    result = run_unit(base_structure(ltv=0.70, dscr=2.0), terms=terms, results=results)
    assert repr((terms, results)) == before  # INV-15
    (payoff,) = result.capital_events[0].payoffs
    assert payoff.provider_cash_flows == (-6_000_000.0, 240_000.0, 5_760_000.0, 0.0, 0.0, 0.0)
    assert close(oracle_npv(payoff.provider_cash_flows, Fraction(0)), 0)  # the 0% loan's IRR is 0
    assert payoff.scheduled_payment_at_m == 20_000
    assert all(
        requirement.period.hold_year <= 2 for requirement in result.funding_requirements
    )  # no legacy claim after the event
    assert result.legacy_acquisition_loans  # still historically identifiable


def test_f8_inv_16_the_splice_composes_accepted_series_and_adds_nothing_back() -> None:
    _, results = base_unit()
    common = run_unit(base_structure(dscr=2.0)).common_equity
    assert common.recurring_cash_flows[:3] == results.levered_cash_flows[:3]
    for year in (3, 4):
        assert close(common.recurring_cash_flows[year], Fraction(results.unlevered_cash_flows[year]) - 400_000)
    assert close(common.recurring_cash_flows[5], Fraction(results.unlevered_cash_flows[5]) - 8_400_000)


def test_a_splice_identity_failure_is_refused() -> None:
    terms, results = base_unit()
    broken = dataclasses.replace(results, unlevered_cash_flows=(*results.unlevered_cash_flows[:4], results.unlevered_cash_flows[4] + 1.0, results.unlevered_cash_flows[5]))
    with pytest.raises(CapitalStructureExecutionError) as raised:
        run_unit(base_structure(dscr=2.0), terms=terms, results=broken, with_valuation=False)
    assert [issue.code for issue in raised.value.issues] == [ExecutionIssueCode.LEGACY_AUTHORITY_SPLICE_MISMATCH]


def test_f9_the_replacement_serves_from_month_25_and_is_repaid_at_the_sale() -> None:
    result = run_unit(base_structure(ltv=0.70, dscr=2.0))
    refi = _position(result, REPLACEMENT_ID)
    assert refi.status is PositionResultStatus.COMPLETE
    expected = [0, 0, -8_000_000, 400_000, 400_000, 8_400_000]
    for got, want in zip(refi.annual_cash_flows, expected, strict=True):
        assert close(got, want)
    assert close(refi.irr, Fraction("0.05"), rel=1e-6) and close(refi.moic, Fraction("1.15"))
    assert refi.modeled_payoff_month == 60 and close(refi.balance_at_maturity_or_exit, 8_000_000)
    service_months = sorted(e.model_month for e in refi.cash_flow_events if e.kind is PositionCashFlowKind.SCHEDULED_DEBT_SERVICE)
    assert service_months[0] == 25 and service_months[-1] == 60 and len(service_months) == 36  # INV-4, INV-9
    (funding,) = [e for e in refi.cash_flow_events if e.kind is PositionCashFlowKind.REFINANCE_FUNDING]
    assert funding.model_month == 24 and close(funding.amount, -8_000_000)
    (balloon,) = [e for e in refi.cash_flow_events if e.kind is PositionCashFlowKind.BALLOON]
    assert balloon.model_month == 60  # INV-7
    assert refi.coverage_by_year[:2] == (None, None) and all(close(c, 2) for c in refi.coverage_by_year[2:])
    assert refi.attachment_basis == 0.0 and close(refi.detachment_basis, 8_000_000)


def test_inv_3_an_authored_retiring_position_ends_at_its_payoff() -> None:
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.10, io_period=10, maturity_month=120)
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT)
    result = run_unit(evented(mezz, heir, events=(event(fixed=1_500_000.0, retiring=(authored_ref("mezz"),)),)))
    retired = _position(result, "mezz")
    assert max(e.model_month for e in retired.cash_flow_events) == 24  # INV-3, INV-9
    (payoff,) = [e for e in retired.cash_flow_events if e.kind is PositionCashFlowKind.REFINANCE_PAYOFF]
    assert close(payoff.amount, 1_000_000) and not [e for e in retired.cash_flow_events if e.kind is PositionCashFlowKind.BALLOON]
    assert retired.modeled_payoff_month == 24 and retired.debt_schedule.maturity_month == 120
    assert all(claim.hold_year <= 2 for claim in retired.annual_claims)
    assert all(e.event_id not in (c for claim in retired.annual_claims for c in claim.component_event_ids) for e in [payoff])
    assert retired.coverage_by_year[2:] == (None, None, None)


# =============================================================================
# F10 / INV-2 / INV-5: fees reach exactly their providers, and cash conserves
# =============================================================================


def test_f10_every_fee_reaches_exactly_its_recipient() -> None:
    result = run_unit(
        base_structure(
            ltv=0.70, dscr=2.0, replacement_fees=(lender_fee(80_000.0),), costs=(third_party(40_000.0), exit_fee(30_000.0, LEGACY))
        )
    )
    (outcome,) = result.capital_events
    assert close(outcome.bridge.net_event_cash, 2_330_000)
    refi = _position(result, REPLACEMENT_ID)
    assert close(refi.annual_cash_flows[2], -7_920_000)
    (payoff,) = outcome.payoffs
    assert payoff.retiring_lender_fees == 30_000 and close(payoff.provider_cash_flows[2], 5_790_000)
    # INV-2: at the event, every provider flow and the equity cash sum to zero.
    event_flows = (
        Fraction(-outcome.bridge.gross_proceeds)
        + outcome.bridge.replacement_lender_fees
        + payoff.payoff
        + payoff.retiring_lender_fees
        + outcome.bridge.third_party_costs
        + Fraction(outcome.bridge.net_event_cash)
    )
    assert close(event_flows, 0)
    # INV-5: every year, pre-debt cash = equity + every provider + third parties.
    _, results = base_unit()
    for t in range(6):
        providers = Fraction(payoff.provider_cash_flows[t]) + Fraction(refi.annual_cash_flows[t])
        third = 40_000 if t == 2 else 0
        assert close(results.unlevered_cash_flows[t], Fraction(result.common_equity.cash_flows[t]) + providers + third), t


def test_third_party_costs_reach_no_capital_position() -> None:
    result = run_unit(base_structure(dscr=2.0, costs=(third_party(40_000.0),)))
    assert [p.position_id for p in result.positions] == [REPLACEMENT_ID]
    assert all(e.amount != 40_000.0 for e in _position(result, REPLACEMENT_ID).cash_flow_events)


# =============================================================================
# BLOCKED: an upstream unresolved requirement stops the event
# =============================================================================


def test_an_unresolved_requirement_before_the_event_blocks_it() -> None:
    junior = closing_debt(
        "junior", amount=3_000_000.0, priority=2, rate=0.20, amortization=3, maturity_month=36,
        resolution=ShortfallResolution.UNRESOLVED,
    )
    result = run_unit(evented(replacement(), junior, events=(event(fixed=7_000_000.0),)))
    (outcome,) = result.capital_events
    assert outcome.status is RefinanceStatus.BLOCKED
    assert outcome.unavailable_reason is RefinanceUnavailableReason.UPSTREAM_UNRESOLVED_FUNDING
    assert outcome.bridge is None and outcome.funding is None and outcome.sizing is not None
    assert result.common_equity.cash_flows is None
    assert result.common_equity.unavailable_reason is CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
    assert _position(result, REPLACEMENT_ID).status is PositionResultStatus.REFINANCE_UNAVAILABLE
    assert any(r.status is FundingRequirementStatus.UNRESOLVED for r in result.funding_requirements)


# =============================================================================
# INV-11: deterministic, order-free reruns
# =============================================================================


def test_inv_11_permutations_change_nothing() -> None:
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.10, io_period=10)
    first = run_unit(evented(replacement(fees=(lender_fee(1.0),)), mezz, events=(event(dscr=2.0, costs=(third_party(1.0, "a"), third_party(2.0, "b"))),)))
    second = run_unit(evented(mezz, replacement(fees=(lender_fee(1.0),)), events=(event(dscr=2.0, costs=(third_party(2.0, "b"), third_party(1.0, "a"))),)))
    assert repr(first) == repr(second)
    assert repr(run_unit(base_structure(dscr=2.0))) == repr(run_unit(base_structure(dscr=2.0)))


# =============================================================================
# F15 / F15b: multi-unit isolation and the Investment NOI reconciliation
# =============================================================================


def _investment(b_overrides: dict[str, Any] | None = None, *, a_overrides: dict[str, Any] | None = None) -> tuple[tuple[CapitalStructureUnit, ...], Any]:
    units = []
    for unit_id, overrides in (("a", a_overrides or {}), ("b", b_overrides or {"current_noi": 600_000.0, "ltv": 0.5})):
        terms, results = base_unit(**overrides)
        units.append(CapitalStructureUnit(unit_id=unit_id, terms=terms, results=results))
    consolidated = consolidate(
        [ConsolidationUnit(unit_id=u.unit_id, purchase_price=u.terms.purchase_price, hold_period=u.terms.hold_period, results=u.results) for u in units],
        transaction_price=sum(u.terms.purchase_price for u in units),
    )
    return tuple(units), consolidated


def _a_event() -> tuple[Any, ...]:
    heir = replacement(scope=unit_scope("a"))
    b_mezz = closing_debt("b-mezz", amount=500_000.0, priority=2, rate=0.08, io_period=10, scope=unit_scope("b"))
    return heir, b_mezz


def test_f15_a_unit_refinance_touches_only_its_own_unit() -> None:
    units, consolidated = _investment()
    heir, b_mezz = _a_event()
    refinanced = run_investment(
        evented(heir, b_mezz, events=(event(dscr=2.0, retiring=(dataclasses.replace(LEGACY, unit_id="a"),), scope=unit_scope("a")),)),
        units=units,
        consolidated=consolidated,
    )
    neutral = run_investment(plain(b_mezz), units=units, consolidated=consolidated)
    assert repr(_position(refinanced, "b-mezz")) == repr(_position(neutral, "b-mezz"))
    (outcome,) = refinanced.capital_events
    assert close(outcome.bridge.net_event_cash, 2_480_000)
    delta = [Fraction(a) - Fraction(b) for a, b in zip(refinanced.common_equity.cash_flows, neutral.common_equity.cash_flows, strict=True)]
    for got, want in zip(delta, [0, 0, 2_480_000, -160_000, -160_000, -3_360_000], strict=True):
        assert close(got, want)


def test_f15_another_units_noi_never_moves_this_units_event() -> None:
    heir, b_mezz = _a_event()
    structure = evented(heir, b_mezz, events=(event(dscr=2.0, retiring=(dataclasses.replace(LEGACY, unit_id="a"),), scope=unit_scope("a")),))
    first = run_investment(structure, units=_investment()[0], consolidated=_investment()[1])
    units, consolidated = _investment({"current_noi": 900_000.0, "ltv": 0.3})
    second = run_investment(structure, units=units, consolidated=consolidated)
    assert repr(first.capital_events) == repr(second.capital_events)  # INV-1


def test_f15_an_investment_event_is_refused_while_unit_debt_remains() -> None:
    units, consolidated = _investment()
    inv_mezz = closing_debt("inv-mezz", amount=500_000.0, priority=1, rate=0.1, io_period=10, scope=INVESTMENT_SCOPE)
    heir = replacement(scope=INVESTMENT_SCOPE, position_class=PositionClass.MEZZANINE_DEBT)
    structure = evented(inv_mezz, heir, events=(event(dscr=2.0, retiring=(authored_ref("inv-mezz"),), scope=INVESTMENT_SCOPE),))
    with pytest.raises(CapitalStructureExecutionError) as raised:
        run_investment(structure, units=units, consolidated=consolidated)
    assert [issue.code for issue in raised.value.issues] == [ExecutionIssueCode.INVESTMENT_REFINANCE_WITH_UNIT_DEBT]


def _f15b() -> tuple[Any, Any, Any]:
    units, consolidated = _investment({"current_noi": 600_000.0, "ltv": 0.0}, a_overrides={"ltv": 0.0})
    portfolio = closing_debt(
        "portfolio", amount=8_000_000.0, priority=1, rate=0.05, io_period=10, maturity_month=120,
        position_class=PositionClass.SENIOR_DEBT, scope=INVESTMENT_SCOPE,
    )
    heir = replacement(scope=INVESTMENT_SCOPE)
    structure = evented(portfolio, heir, events=(event(dscr=2.0, retiring=(authored_ref("portfolio"),), scope=INVESTMENT_SCOPE),))
    return units, consolidated, structure


def test_f15b_the_investment_forward_noi_is_the_reconciled_unit_sum() -> None:
    units, consolidated, structure = _f15b()
    result = run_investment(structure, units=units, consolidated=consolidated)
    (outcome,) = result.capital_events
    assert outcome.noi_dependency.forward_noi == 1_400_000 == consolidated.noi_by_year[2]
    assert close(outcome.sizing.gross_proceeds, 14_000_000)
    assert close(outcome.bridge.net_event_cash, 6_000_000)


def test_f15b_a_broken_reconciliation_is_refused() -> None:
    units, consolidated, structure = _f15b()
    tampered = dataclasses.replace(consolidated, noi_by_year=(*consolidated.noi_by_year[:2], consolidated.noi_by_year[2] + 1.0, *consolidated.noi_by_year[3:]))
    with pytest.raises(CapitalStructureExecutionError) as raised:
        run_investment(structure, units=units, consolidated=tampered)
    assert [issue.code for issue in raised.value.issues] == [ExecutionIssueCode.FORWARD_NOI_AUTHORITY_MISMATCH]


def test_an_unavailable_unit_event_makes_the_investment_residual_unavailable() -> None:
    units, consolidated = _investment()
    heir, b_mezz = _a_event()
    structure = evented(heir, b_mezz, events=(event(ltv=0.6, retiring=(dataclasses.replace(LEGACY, unit_id="a"),), scope=unit_scope("a")),))
    result = run_investment(structure, units=units, consolidated=consolidated, valuations=None)
    assert result.capital_events[0].unavailable_reason is RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND
    assert result.common_equity.cash_flows is None
    assert result.common_equity.unavailable_reason is CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE
    assert _position(result, "b-mezz").status is PositionResultStatus.COMPLETE  # another Unit's senior stays valid
    assert [u.position_id for u in result.unexecuted_positions] == [REPLACEMENT_ID]


def test_inv_5_an_authored_retirement_conserves_every_year() -> None:
    """INV-5 with a continuing acquisition loan and a retired authored
    mezzanine loan: in every year, pre-debt cash equals Common Equity plus every
    provider's annual flow plus third-party costs. A payoff settled twice -- by
    the event and again by the retiring position's annual claim -- breaks it."""

    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.10, io_period=10, maturity_month=120)
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT, fees=(lender_fee(10_000.0),))
    result = run_unit(
        evented(mezz, heir, events=(event(fixed=1_500_000.0, retiring=(authored_ref("mezz"),), costs=(third_party(5_000.0),)),))
    )
    _, results = base_unit()
    legacy = [-results.loan_amount + results.financing_fee, *results.annual_debt_service]
    legacy[5] = legacy[5] + results.remaining_loan_balance
    retired, refi = _position(result, "mezz"), _position(result, REPLACEMENT_ID)
    for t in range(6):
        providers = Fraction(legacy[t]) + Fraction(retired.annual_cash_flows[t]) + Fraction(refi.annual_cash_flows[t])
        third = 5_000 if t == 2 else 0
        assert close(results.unlevered_cash_flows[t], Fraction(result.common_equity.cash_flows[t]) + providers + third), t
