"""Phase 7 Gate P7.8 -- the execution contracts, execution validation, funding
resolution and event aggregation.

``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md`` Sections 3-5, 8 and
12, under ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
12 and 15.5:

- a structurally valid contract the first executor does not run is refused with
  a deterministic execution issue -- never called malformed, never moved to a
  supported convention, never partially executed;
- funding resolves event by event, at closing only, against the stated
  acquisition price of the position's scope;
- the annual position cash flow is the canonical aggregation of its exact
  model-month events, and no list order moves a bit.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable
from typing import Any

import pytest

from _p7_7_fixtures import bits  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    CEC,
    INVESTMENT,
    UNIT,
    cash_pay_debt,
    claim_position,
    common_marker,
    fee,
    funding,
    golden_mezz,
    preferred,
    round_unit,
    structure,
)
from anchor.capital_structure import (
    AccrualConvention,
    CapitalPosition,
    CapitalStructureExecutionError,
    CapitalStructureValidationError,
    DebtTerms,
    ExecutionIssueCode,
    FixedAmount,
    PctOfPrice,
    PctOfValue,
    PositionCashFlowKind,
    PositionClass,
    PositionResultStatus,
    PositionUnavailableReason,
    PriceBasisKind,
    execute_unit_capital_structure,
    execution_contracts,
    validate_capital_structure,
)

Kind = PositionCashFlowKind
MEZZ = PositionClass.MEZZANINE_DEBT
PREF = PositionClass.PREFERRED_EQUITY


@pytest.fixture(scope="module")
def unit() -> tuple[Any, Any]:
    return round_unit()


def _execute(unit: tuple[Any, Any], *positions: CapitalPosition) -> Any:
    terms, results = unit
    return execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(*positions))


def _mezz(**kwargs: Any) -> CapitalPosition:
    base: dict[str, Any] = {
        "position_class": MEZZ,
        "priority": 2,
        "terms": cash_pay_debt(rate=0.10, io_period=5),
        "resolution": CEC,
        "amount": 1_000_000.0,
    }
    base.update(kwargs)
    return claim_position("mezz", **base)


def _pref(**terms: Any) -> CapitalPosition:
    return claim_position(
        "pref", position_class=PREF, priority=3, terms=preferred(**terms), resolution=CEC, amount=1_000_000.0
    )


# =============================================================================
# 1. The contracts
# =============================================================================


def test_the_execution_enumerations_have_exactly_their_members() -> None:
    assert [member.value for member in ExecutionIssueCode] == [
        "unsupported_amount_rule",
        "unsupported_funding_timing",
        "unsupported_fee_timing",
        "unsupported_debt_pik",
        "unsupported_debt_current_pay",
        "unsupported_preferred_current_pay",
        "unpermitted_preferred_accrual",
        "unsupported_redemption_timing",
        "unsupported_scope",
        "unsupported_common_equity_scope",
        "multiple_common_equity_markers",
        "claim_below_common_equity",
        "duplicate_result_event_id",
        "overfunded_closing",
        # P7.10 Stage 1 appends exactly one member: the reason a ``PctOfValue``
        # funding the supplied valuation authority cannot size is refused.
        # Every pre-existing member keeps its place and its meaning.
        "unresolved_valuation_funding",
    ]
    assert [member.value for member in Kind] == [
        "funding", "fee", "scheduled_debt_service", "balloon", "preferred_current_pay", "preferred_redemption",
    ]
    assert [member.value for member in PositionResultStatus] == [
        "complete", "unresolved_funding", "blocked_by_senior_unresolved",
    ]
    assert [member.value for member in PositionUnavailableReason] == [
        "unresolved_funding_requirement", "senior_unresolved_funding_requirement",
    ]
    assert [member.value for member in PriceBasisKind] == ["unit_purchase_price", "investment_transaction_price"]


def test_every_execution_contract_is_frozen_slotted_and_keyword_only() -> None:
    contracts = [
        cls
        for _, cls in inspect.getmembers(execution_contracts, inspect.isclass)
        if dataclasses.is_dataclass(cls) and cls.__module__ == execution_contracts.__name__
    ]
    assert sorted(contract.__name__ for contract in contracts) == [
        "CommonEquityReturns", "DebtPositionSchedule", "ExecutionIssue", "PositionAnnualClaim", "PositionCashFlowEvent",
        "PositionReturns", "PreferredAccrualYear", "PreferredPositionSchedule", "PriceBasis", "ResolvedFundingEvent",
        "ScheduledPosition", "StructuredCapitalResult",
    ]
    for contract in contracts:
        assert contract.__dataclass_params__.frozen, contract  # type: ignore[attr-defined]
        assert "__slots__" in vars(contract), contract
        assert all(field.kw_only for field in dataclasses.fields(contract)), contract


def test_an_execution_refusal_is_its_own_error_never_a_structural_one() -> None:
    assert issubclass(CapitalStructureExecutionError, ValueError)
    assert not issubclass(CapitalStructureExecutionError, CapitalStructureValidationError)
    with pytest.raises(ValueError, match="at least one issue"):
        CapitalStructureExecutionError(())
    with pytest.raises(TypeError):
        CapitalStructureExecutionError(("not an issue",))  # type: ignore[arg-type]


def test_the_result_carries_no_project_field() -> None:
    """Position returns are their own namespace (Section 14): no field of the
    project result contracts is appended to or duplicated in them."""

    names = {field.name for field in dataclasses.fields(execution_contracts.StructuredCapitalResult)}
    assert not names & {"levered_irr", "unlevered_irr", "levered_cash_flows", "noi_by_year", "dscr_by_year"}
    common = {field.name for field in dataclasses.fields(execution_contracts.CommonEquityReturns)}
    assert "levered_irr" not in common and "irr" in common


# =============================================================================
# 2. Execution validation: valid, but not executed by this executor
# =============================================================================

_REFUSALS: dict[str, tuple[Callable[[], tuple[CapitalPosition, ...]], ExecutionIssueCode, str | None]] = {
    "later_funding_month": (
        lambda: (_mezz(funding_events=(funding("draw", month=12, rule=FixedAmount(amount=1_000_000.0)),)),),
        ExecutionIssueCode.UNSUPPORTED_FUNDING_TIMING,
        "mezz",
    ),
    "pct_of_value": (
        lambda: (_mezz(funding_events=(funding("valued", rule=PctOfValue(timepoint_id="stabilized", pct=0.1)),)),),
        ExecutionIssueCode.UNSUPPORTED_AMOUNT_RULE,
        "mezz",
    ),
    "later_fee": (
        lambda: (_mezz(terms=cash_pay_debt(rate=0.10, io_period=5, fees=(fee("exit-fee", month=60),))),),
        ExecutionIssueCode.UNSUPPORTED_FEE_TIMING,
        "mezz",
    ),
    "positive_debt_pik": (
        lambda: (
            _mezz(
                terms=DebtTerms(
                    interest_rate=0.12, amortization=30, io_period=5, maturity_month=60, fees=(),
                    current_pay_rate=0.12, pik_rate=0.02,
                )
            ),
        ),
        ExecutionIssueCode.UNSUPPORTED_DEBT_PIK,
        "mezz",
    ),
    "split_debt_current_pay": (
        lambda: (
            _mezz(
                terms=DebtTerms(
                    interest_rate=0.12, amortization=30, io_period=5, maturity_month=60, fees=(),
                    current_pay_rate=0.09, pik_rate=0.0,
                )
            ),
        ),
        ExecutionIssueCode.UNSUPPORTED_DEBT_CURRENT_PAY,
        "mezz",
    ),
    "preferred_current_pay_above_its_rate": (
        lambda: (_pref(preferred_rate=0.08, current_pay_rate=0.10),),
        ExecutionIssueCode.UNSUPPORTED_PREFERRED_CURRENT_PAY,
        "pref",
    ),
    "unpermitted_preferred_accrual": (
        lambda: (_pref(preferred_rate=0.12, current_pay_rate=0.08),),
        ExecutionIssueCode.UNPERMITTED_PREFERRED_ACCRUAL,
        "pref",
    ),
    "partial_year_redemption": (
        lambda: (_pref(preferred_rate=0.10, current_pay_rate=0.10, redemption_month=30),),
        ExecutionIssueCode.UNSUPPORTED_REDEMPTION_TIMING,
        "pref",
    ),
    "investment_scope_in_a_standalone_unit": (
        lambda: (_mezz(priority=1, scope=INVESTMENT),),
        ExecutionIssueCode.UNSUPPORTED_SCOPE,
        "mezz",
    ),
    "investment_marker_in_a_standalone_unit": (
        lambda: (common_marker(scope=INVESTMENT, priority=1),),
        ExecutionIssueCode.UNSUPPORTED_COMMON_EQUITY_SCOPE,
        "common",
    ),
    "claim_below_common_equity": (
        lambda: (common_marker(priority=2), _mezz(priority=3)),
        ExecutionIssueCode.CLAIM_BELOW_COMMON_EQUITY,
        "mezz",
    ),
    "two_common_equity_markers": (
        lambda: (common_marker("common-a", priority=8), common_marker("common-b", priority=9)),
        ExecutionIssueCode.MULTIPLE_COMMON_EQUITY_MARKERS,
        None,
    ),
}


@pytest.mark.parametrize("case", sorted(_REFUSALS))
def test_a_valid_contract_the_executor_does_not_run_is_refused_with_exactly_its_issue(
    case: str, unit: tuple[Any, Any]
) -> None:
    build, code, position_id = _REFUSALS[case]
    candidate = structure(*build())
    assert validate_capital_structure(candidate, member_unit_ids={UNIT}, acquisition_loan_unit_ids={UNIT}) == ()

    terms, results = unit
    with pytest.raises(CapitalStructureExecutionError) as refused:
        execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=candidate)
    assert [(issue.code, issue.position_id) for issue in refused.value.issues] == [(code, position_id)]
    assert str(refused.value) == refused.value.issues[0].message


def test_an_authored_event_id_repeating_a_scheduled_event_id_is_refused(unit: tuple[Any, Any]) -> None:
    clash = _mezz(
        terms=cash_pay_debt(rate=0.10, amortization=25, io_period=1, maturity_month=48),
        funding_events=(funding("mezz:balloon:48", rule=FixedAmount(amount=1_000_000.0)),),
    )
    assert validate_capital_structure(structure(clash), member_unit_ids={UNIT}, acquisition_loan_unit_ids={UNIT}) == ()
    with pytest.raises(CapitalStructureExecutionError) as refused:
        _execute(unit, clash)
    assert [issue.code for issue in refused.value.issues] == [ExecutionIssueCode.DUPLICATE_RESULT_EVENT_ID]


def test_a_malformed_contract_is_refused_as_malformed_first(unit: tuple[Any, Any]) -> None:
    """Structural validation (P7.7, unchanged) runs first: a structure that is
    both malformed and unsupported is reported malformed."""

    malformed = _mezz(
        priority=1,
        terms=DebtTerms(
            interest_rate=0.12, amortization=30, io_period=5, maturity_month=60, fees=(), current_pay_rate=0.12,
            pik_rate=0.02,
        ),
    )
    with pytest.raises(CapitalStructureValidationError):
        _execute(unit, malformed)


def test_execution_issues_never_depend_on_list_order(unit: tuple[Any, Any]) -> None:
    pik = _mezz(
        terms=DebtTerms(
            interest_rate=0.12, amortization=30, io_period=5, maturity_month=60, fees=(), current_pay_rate=0.12,
            pik_rate=0.02,
        )
    )
    unpermitted = _pref(preferred_rate=0.12, current_pay_rate=0.08)
    issues = []
    for positions in ((pik, unpermitted), (unpermitted, pik)):
        with pytest.raises(CapitalStructureExecutionError) as refused:
            _execute(unit, *positions)
        issues.append(refused.value.issues)
    assert issues[0] == issues[1]
    assert [issue.position_id for issue in issues[0]] == ["mezz", "pref"]


def test_a_permitted_accrual_and_equal_rates_are_both_executable(unit: tuple[Any, Any]) -> None:
    executed = _execute(
        unit,
        claim_position(
            "pref-a", position_class=PREF, priority=2, resolution=CEC, amount=500_000.0,
            terms=preferred(preferred_rate=0.12, current_pay_rate=0.08, convention=AccrualConvention.SIMPLE),
        ),
        claim_position(
            "pref-b", position_class=PREF, priority=3, resolution=CEC, amount=500_000.0,
            terms=preferred(preferred_rate=0.10, current_pay_rate=0.10),
        ),
    )
    assert [position.status for position in executed.positions] == [PositionResultStatus.COMPLETE] * 2


# =============================================================================
# 3. Funding resolution
# =============================================================================


def test_pct_of_price_resolves_against_the_units_resolved_purchase_price(unit: tuple[Any, Any]) -> None:
    terms, _ = unit
    (position,) = _execute(unit, _mezz(funding_events=(funding("f", rule=PctOfPrice(pct=0.15)),))).positions
    (resolved,) = position.funding
    assert resolved.amount == 0.15 * terms.purchase_price == 1_500_000.0
    assert resolved.price_basis is not None
    assert (resolved.price_basis.kind, resolved.price_basis.amount) == (PriceBasisKind.UNIT_PURCHASE_PRICE, 10_000_000.0)
    assert position.valuation_basis == resolved.price_basis
    assert position.funded_amount == 1_500_000.0


def test_each_closing_funding_event_is_resolved_on_its_own_and_summed_canonically(unit: tuple[Any, Any]) -> None:
    _, results = unit
    events = (
        funding("f-3", sequence=5, rule=FixedAmount(amount=250_000.0)),
        funding("f-1", sequence=1, rule=FixedAmount(amount=1_000_000.0)),
        funding("f-2", sequence=3, rule=PctOfPrice(pct=0.05)),
    )
    fees = (fee("fee-b", amount=5_000.0, sequence=4), fee("fee-a", amount=10_000.0, sequence=2))
    executed = _execute(unit, _mezz(funding_events=events, terms=cash_pay_debt(rate=0.10, io_period=5, fees=fees)))
    (position,) = executed.positions

    assert [(event.event_id, event.amount, event.price_basis is None) for event in position.funding] == [
        ("f-1", 1_000_000.0, True), ("f-2", 500_000.0, False), ("f-3", 250_000.0, True),
    ]
    assert position.funded_amount == 1_750_000.0
    closing = [(event.event_id, event.kind, event.amount) for event in position.cash_flow_events if event.model_month == 0]
    assert closing == [
        ("f-1", Kind.FUNDING, -1_000_000.0),
        ("fee-a", Kind.FEE, 10_000.0),
        ("f-2", Kind.FUNDING, -500_000.0),
        ("fee-b", Kind.FEE, 5_000.0),
        ("f-3", Kind.FUNDING, -250_000.0),
    ]
    assert position.annual_cash_flows is not None and position.annual_cash_flows[0] == -1_735_000.0
    # Common equity: the funding is a closing source and the fees a use.
    assert executed.common_equity.cash_flows[0] == results.levered_cash_flows[0] + 1_750_000.0 - 15_000.0
    # The fees never reduce the capital advanced.
    assert position.detachment_basis == 6_000_000.0 + 1_750_000.0


# =============================================================================
# 4. Events and their annual aggregation
# =============================================================================


def _aggregation_positions() -> tuple[CapitalPosition, ...]:
    return (
        _mezz(
            funding_events=(
                funding("mezz-f2", sequence=3, rule=PctOfPrice(pct=0.05)),
                funding("mezz-f1", sequence=1, rule=FixedAmount(amount=1_000_000.0)),
            ),
            terms=cash_pay_debt(
                rate=0.11, amortization=20, io_period=1, maturity_month=42,
                fees=(fee("mezz-fee-2", amount=7_500.0, sequence=4), fee("mezz-fee-1", amount=12_500.0, sequence=2)),
            ),
        ),
        _pref(preferred_rate=0.12, current_pay_rate=0.07, convention=AccrualConvention.ANNUAL_COMPOUND),
        common_marker(),
    )


def test_every_event_is_typed_and_timed_explicitly(unit: tuple[Any, Any]) -> None:
    mezz, pref = _execute(unit, *_aggregation_positions()).positions
    kinds = [event.kind for event in mezz.cash_flow_events]
    assert kinds.count(Kind.FUNDING) == 2 and kinds.count(Kind.FEE) == 2
    assert kinds.count(Kind.SCHEDULED_DEBT_SERVICE) == 42 and kinds.count(Kind.BALLOON) == 1
    payments = [event for event in mezz.cash_flow_events if event.kind is Kind.SCHEDULED_DEBT_SERVICE]
    assert [(event.model_month, event.sequence) for event in payments] == [(month, 1) for month in range(1, 43)]
    (balloon,) = [event for event in mezz.cash_flow_events if event.kind is Kind.BALLOON]
    assert (balloon.model_month, balloon.sequence, balloon.event_id) == (42, 2, "mezz:balloon:42")
    assert all(event.amount > 0.0 for event in mezz.cash_flow_events if event.kind is not Kind.FUNDING)
    assert all(event.amount < 0.0 for event in mezz.cash_flow_events if event.kind is Kind.FUNDING)

    current = [event for event in pref.cash_flow_events if event.kind is Kind.PREFERRED_CURRENT_PAY]
    assert [(event.model_month, event.sequence) for event in current] == [(12, 1), (24, 1), (36, 1), (48, 1), (60, 1)]
    (redemption,) = [event for event in pref.cash_flow_events if event.kind is Kind.PREFERRED_REDEMPTION]
    assert (redemption.model_month, redemption.sequence) == (60, 2)


def test_the_annual_cash_flow_is_the_canonical_aggregation_of_the_exact_events(unit: tuple[Any, Any]) -> None:
    for position in _execute(unit, *_aggregation_positions()).positions:
        expected = [0.0] * 6
        for event in sorted(position.cash_flow_events, key=lambda e: (e.model_month, e.sequence, e.event_id)):
            period = 0 if event.model_month == 0 else (event.model_month - 1) // 12 + 1
            expected[period] = expected[period] + event.amount
        assert position.annual_cash_flows is not None
        assert bits(position.annual_cash_flows) == bits(expected), position.position_id
        by_year = [claim.hold_year for claim in position.annual_claims]
        assert by_year == [year for year in range(1, 6) if expected[year] != 0.0]
        for claim in position.annual_claims:
            assert bits([claim.claim_due]) == bits([expected[claim.hold_year]])
            components = [e for e in position.cash_flow_events if e.event_id in set(claim.component_event_ids)]
            assert {(e.model_month - 1) // 12 + 1 for e in components} == {claim.hold_year}


def test_the_same_economic_events_in_another_order_are_bit_identical(unit: tuple[Any, Any]) -> None:
    """Order semantics (Section 15.5, P-7): reversing the positions, and every
    funding and fee tuple within them, moves nothing."""

    forward = _aggregation_positions()
    mezz, pref, marker = forward
    assert isinstance(mezz.terms, DebtTerms)
    reversed_mezz = dataclasses.replace(
        mezz,
        funding=tuple(reversed(mezz.funding)),
        terms=dataclasses.replace(mezz.terms, fees=tuple(reversed(mezz.terms.fees))),
    )
    assert _execute(unit, *forward) == _execute(unit, marker, pref, reversed_mezz)


def test_positions_are_settled_by_priority_never_by_list_position(unit: tuple[Any, Any]) -> None:
    """The mezzanine loan (priority 2) is settled before the preferred
    (priority 3) whichever is listed first: the year-4 balloon leaves the
    preferred no cash, so its whole year-4 claim is a Funding Requirement."""

    pref = claim_position(
        "pref", position_class=PREF, priority=3, resolution=CEC, amount=1_000_000.0,
        terms=preferred(preferred_rate=0.10, current_pay_rate=0.10),
    )
    for positions in ((golden_mezz(), pref), (pref, golden_mezz())):
        executed = _execute(unit, *positions)
        assert [position.position_id for position in executed.positions] == ["mezz", "pref"]
        year_4 = next(claim for claim in executed.positions[1].annual_claims if claim.hold_year == 4)
        assert year_4.settlement.claim.cash_available == 0.0
        assert year_4.settlement.equity_contribution == 100_000.0
