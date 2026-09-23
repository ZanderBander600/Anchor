"""Refinance & Capital Events V1 Stage 1 -- contracts and structural validation.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 6, 7.4, 10.3,
11.5, 15.1 and 19. Every authoring fault wholly inside a Capital Structure is a
typed refusal (R-Q); nothing is repaired, ignored or partially executed, and a
structure with no event validates exactly as before.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from _p7_8_fixtures import cash_pay_debt  # type: ignore[import-not-found]
from _refinance_v1_fixtures import (  # type: ignore[import-not-found]
    EVENT_ID,
    INVESTMENT_SCOPE,
    LEGACY,
    REPLACEMENT_ID,
    UNIT,
    authored_ref,
    base_structure,
    base_unit,
    closing_debt,
    event,
    evented,
    exit_fee,
    lender_fee,
    plain,
    replacement,
    run_unit,
    third_party,
    unit_scope,
)

from anchor.capital_structure import events as events_module
from anchor.capital_structure import refinance_contracts
from anchor.capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    CapitalStructureIssueCode as Code,
    CapitalStructureValidationError,
    FixedAmount,
    FundingAmountRule,
    FundingEvent,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    RefinanceProceeds,
)
from anchor.capital_structure.events import (
    CapitalEventKind,
    CapitalStructureWithEvents,
    EventTiming,
    RefinanceCostKind,
    RefinanceCostLine,
)
from anchor.capital_structure.execution_contracts import CapitalStructureExecutionError, ExecutionIssueCode
from anchor.capital_structure.validation import validate_capital_structure


def _codes(structure: object, *, loans: tuple[str, ...] = (UNIT,), members: tuple[str, ...] | None = (UNIT,)) -> list[str]:
    return [issue.code.value for issue in validate_capital_structure(structure, member_unit_ids=members, acquisition_loan_unit_ids=loans)]


# =============================================================================
# 1. The contracts
# =============================================================================


@pytest.mark.parametrize("module", [events_module, refinance_contracts])
def test_every_refinance_contract_is_frozen_slotted_and_keyword_only(module: object) -> None:
    classes = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls.__module__ == module.__name__ and dataclasses.is_dataclass(cls)  # type: ignore[attr-defined]
    ]
    assert classes
    for cls in classes:
        params = cls.__dataclass_params__  # type: ignore[attr-defined]
        assert params.frozen, cls
        assert "__slots__" in cls.__dict__, cls
        assert all(field.kw_only for field in dataclasses.fields(cls)), cls


def test_the_enumerations_have_exactly_their_ratified_members() -> None:
    assert [member.value for member in CapitalEventKind] == ["refinance"]
    assert [member.value for member in RefinanceCostKind] == ["retiring_lender_fee", "third_party_cost"]
    assert [member.value for member in refinance_contracts.ConstraintKind] == ["fixed_cap", "max_ltv", "min_dscr"]
    assert [member.value for member in refinance_contracts.RefinanceStatus] == [
        "executed", "unavailable", "not_executable", "blocked",
    ]
    assert [member.value for member in refinance_contracts.BridgeDirection] == ["distribution", "contribution", "zero"]
    assert [member.value for member in refinance_contracts.RefinanceUnavailableReason] == [
        "event_outside_hold_horizon",
        "timepoint_not_found",
        "model_month_mismatch",
        "scope_not_covered",
        "valuation_unavailable",
        "evidence_not_approved",
        "forward_noi_unavailable",
        "non_positive_forward_noi",
        "retiring_position_absent",
        "retiring_position_not_outstanding",
        "non_positive_capacity",
        "upstream_unresolved_funding",
        "upstream_capital_event_not_executed",  # Section 23.4 clarification
    ]


def test_refinance_proceeds_is_the_one_added_funding_rule() -> None:
    assert set(FundingAmountRule.__args__) == {FixedAmount, PctOfPrice, PctOfValue, RefinanceProceeds}
    assert [field.name for field in dataclasses.fields(RefinanceProceeds)] == ["capital_event_id"]


def test_a_plain_capital_structure_keeps_exactly_its_field() -> None:
    """Section 19: a structure without a refinance states no events field at
    all, so it serializes and fingerprints exactly as before."""

    assert [field.name for field in dataclasses.fields(CapitalStructure)] == ["positions"]
    assert [field.name for field in dataclasses.fields(CapitalStructureWithEvents)] == ["positions", "events"]
    assert issubclass(CapitalStructureWithEvents, CapitalStructure)


def test_no_reserve_holdback_or_facility_field_exists_anywhere() -> None:
    """Section 11.5 (R-H): V1 has no reserve, holdback, escrow, release or
    facility field on any refinance contract, so no cash can disappear into
    one, and no percentage fee rule."""

    names = {
        field.name
        for module in (events_module, refinance_contracts)
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if dataclasses.is_dataclass(cls)
        for field in dataclasses.fields(cls)
    }
    for forbidden in ("reserve", "holdback", "escrow", "release", "facility", "pct", "percent"):
        assert not any(forbidden in name for name in names), forbidden
    with pytest.raises(TypeError):
        RefinanceCostLine(  # type: ignore[call-arg]
            cost_id="x", kind=RefinanceCostKind.THIRD_PARTY_COST, amount=1.0, recipient=None, description="", reserve=1.0
        )


# =============================================================================
# 2. A structure without a refinance is judged exactly as before
# =============================================================================


def test_a_plain_structure_gains_no_issue() -> None:
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.1)
    assert _codes(plain(mezz)) == []
    assert _codes(plain()) == []


def test_the_legacy_priority_rule_is_unchanged_without_a_refinance() -> None:
    """R-N is a narrow exception: without an event, priority 1 of a Unit with
    an acquisition loan is still the loan's, and a duplicate is still refused."""

    senior = closing_debt("senior", amount=1_000_000.0, priority=1, rate=0.1, position_class=PositionClass.SENIOR_DEBT)
    assert _codes(plain(senior)) == ["duplicate_priority"]
    twins = (
        closing_debt("a", amount=1_000_000.0, priority=2, rate=0.1),
        closing_debt("b", amount=1_000_000.0, priority=2, rate=0.1),
    )
    assert _codes(plain(*twins)) == ["duplicate_priority"]


def test_an_empty_events_tuple_is_refused_rather_than_read_as_no_refinance() -> None:
    assert _codes(evented(events=())) == ["invalid_capital_event"]


# =============================================================================
# 3. The base event is valid, and succession is the one priority exception
# =============================================================================


def test_the_base_refinance_is_valid() -> None:
    assert _codes(base_structure(dscr=2.0)) == []
    assert _codes(base_structure(fixed=7_500_000.0, ltv=0.65, dscr=2.0)) == []


def test_succession_to_the_acquisition_loan_holds_its_reserved_priority() -> None:
    """The replacement of the acquisition loan takes priority 1 (R-N); the
    same position without the event is refused as before."""

    assert _codes(base_structure(dscr=2.0)) == []
    assert "duplicate_priority" in _codes(plain(replacement()))


def test_succession_admits_exactly_the_retiring_and_replacement_pair() -> None:
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.1)
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT)
    good = evented(mezz, heir, events=(event(dscr=2.0, retiring=(authored_ref("mezz"),)),))
    assert _codes(good) == []
    third = closing_debt("other", amount=500_000.0, priority=2, rate=0.1)
    crowded = evented(mezz, heir, third, events=(event(dscr=2.0, retiring=(authored_ref("mezz"),)),))
    assert "duplicate_priority" in _codes(crowded)


def test_the_replacement_must_succeed_to_the_most_senior_retiring_rank() -> None:
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.1)
    junior_heir = replacement(priority=3)
    assert "replacement_priority_not_successor" in _codes(
        evented(mezz, junior_heir, events=(event(dscr=2.0, retiring=(authored_ref("mezz"),)),))
    )
    assert "replacement_priority_not_successor" in _codes(evented(replacement(priority=2), events=(event(dscr=2.0),)))


# =============================================================================
# 4. Every Section 15.1 refusal
# =============================================================================


def _with_event(**kwargs: object) -> CapitalStructureWithEvents:
    return evented(replacement(), events=(event(**kwargs),))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("structure", "code"),
    [
        pytest.param(lambda: evented(replacement(), events=(event(dscr=2.0, month=0),)), "event_month_not_hold_year_end", id="closing"),
        pytest.param(lambda: evented(replacement(month=18), events=(event(dscr=2.0, month=18),)), "event_month_not_hold_year_end", id="intra-year"),
        pytest.param(lambda: _with_event(dscr=2.0, retiring=()), "no_retiring_position", id="no-retiring"),
        pytest.param(lambda: _with_event(dscr=2.0, retiring=(authored_ref("ghost"),)), "retiring_position_not_found", id="not-found"),
        pytest.param(lambda: _with_event(dscr=2.0, retiring=(LEGACY, LEGACY)), "retiring_position_duplicated", id="duplicated"),
        pytest.param(lambda: _with_event(dscr=2.0, retiring=(authored_ref(REPLACEMENT_ID),)), "retiring_position_not_debt", id="self"),
        pytest.param(lambda: _with_event(dscr=2.0, replacement_id="ghost"), "replacement_position_not_found", id="no-replacement"),
        pytest.param(lambda: _with_event(), "no_sizing_constraint", id="no-constraint"),
        pytest.param(lambda: _with_event(fixed=0.0), "invalid_fixed_cap", id="zero-cap"),
        pytest.param(lambda: _with_event(ltv=1.5), "invalid_max_ltv", id="ltv-above-one"),
        pytest.param(lambda: _with_event(dscr=0.0), "invalid_min_dscr", id="zero-dscr"),
        pytest.param(lambda: _with_event(ltv=0.6, valuation=None), "valuation_reference_required", id="ltv-without-value"),
        pytest.param(lambda: _with_event(dscr=2.0, valuation="year-2-value"), "valuation_reference_unused", id="dscr-with-value"),
        pytest.param(lambda: _with_event(fixed=5e6, valuation="year-2-value"), "valuation_reference_unused", id="fixed-with-value"),
        pytest.param(lambda: _with_event(fixed=5e6, dscr=2.0, valuation="year-2-value"), "valuation_reference_unused", id="fixed-dscr-with-value"),
        pytest.param(lambda: _with_event(dscr=2.0, costs=(exit_fee(1.0, authored_ref("ghost")),)), "invalid_retiring_lender_fee_recipient", id="fee-recipient"),
        pytest.param(lambda: _with_event(dscr=2.0, costs=(third_party(-1.0),)), "invalid_cost_line", id="negative-cost"),
        pytest.param(
            lambda: _with_event(
                dscr=2.0,
                costs=(RefinanceCostLine(cost_id="c", kind=RefinanceCostKind.THIRD_PARTY_COST, amount=1.0, recipient=LEGACY, description=""),),
            ),
            "invalid_cost_line",
            id="third-party-recipient",
        ),
        pytest.param(lambda: _with_event(dscr=2.0, costs=(third_party(1.0, cost_id=EVENT_ID),)), "duplicate_capital_event_id", id="namespace"),
        pytest.param(lambda: evented(replacement(maturity_month=30), events=(event(dscr=2.0),)), "replacement_maturity_too_early", id="bridge"),
        pytest.param(lambda: evented(replacement(fees=(lender_fee(1.0, month=0),)), events=(event(dscr=2.0),)), "replacement_fee_timing", id="fee-timing"),
        pytest.param(lambda: evented(replacement(month=36), events=(event(dscr=2.0),)), "replacement_funding_mismatch", id="funding-month"),
        pytest.param(lambda: evented(replacement(event_id="other"), events=(event(dscr=2.0),)), "replacement_funding_mismatch", id="funding-event"),
        pytest.param(lambda: evented(replacement(rate=0.0, io_period=1), events=(event(dscr=2.0),)), "dscr_zero_first_year_service", id="zero-io"),
        pytest.param(lambda: evented(replacement(scope=unit_scope("u2")), events=(event(dscr=2.0),)), "replacement_scope_mismatch", id="replacement-scope"),
        pytest.param(lambda: _with_event(dscr=2.0, retiring=(LEGACY,), scope=unit_scope("u2")), "foreign_unit_scope", id="foreign-unit"),
        pytest.param(
            lambda: evented(
                replacement(),
                replacement("refi-2", event_id="second"),
                events=(event(dscr=2.0), event(dscr=2.0, event_id="second", replacement_id="refi-2")),
            ),
            "multiple_refinances_in_scope",
            id="two-in-scope",
        ),
        pytest.param(lambda: plain(replacement()), "orphaned_refinance_proceeds", id="orphan"),
    ],
)
def test_each_authoring_fault_is_refused_with_its_code(structure: object, code: str) -> None:
    built = structure()  # type: ignore[operator]
    assert code in _codes(built, members=(UNIT, "u2") if code != "foreign_unit_scope" else (UNIT,)), _codes(built)


def test_a_retiring_position_of_another_scope_or_class_is_refused() -> None:
    other = closing_debt("other", amount=1_000_000.0, priority=2, rate=0.1, scope=unit_scope("u2"))
    codes = _codes(evented(other, replacement(), events=(event(dscr=2.0, retiring=(authored_ref("other"),)),)), members=(UNIT, "u2"))
    assert "retiring_position_scope_mismatch" in codes
    preferred = CapitalPosition(
        position_id="pref",
        name="Preferred",
        position_class=PositionClass.PREFERRED_EQUITY,
        priority=2,
        scope=unit_scope(),
        funding=(FundingEvent(event_id="pref-f", model_month=0, sequence=1, amount_rule=FixedAmount(amount=1.0)),),
        terms=__import__("_p7_8_fixtures").preferred(preferred_rate=0.08, current_pay_rate=0.08),
        shortfall_resolution=replacement().shortfall_resolution,
    )
    assert "retiring_position_not_debt" in _codes(
        evented(preferred, replacement(priority=2), events=(event(dscr=2.0, retiring=(authored_ref("pref"),)),))
    )
    assert "retiring_position_scope_mismatch" in _codes(
        evented(replacement(), events=(event(dscr=2.0, retiring=(LEGACY,), scope=INVESTMENT_SCOPE),)), members=(UNIT,)
    )


def test_a_non_refinance_event_kind_is_refused() -> None:
    bad = dataclasses.replace(event(dscr=2.0), kind="recapitalization")  # type: ignore[arg-type]
    assert "unsupported_capital_event_kind" in _codes(evented(replacement(), events=(bad,)))


def test_the_event_sequence_is_one() -> None:
    bad = dataclasses.replace(event(dscr=2.0), timing=EventTiming(model_month=24, sequence=2))
    assert "unsupported_event_sequence" in _codes(evented(replacement(), events=(bad,)))


def test_issue_order_never_depends_on_list_order() -> None:
    faulty = (
        event(event_id="a-event", replacement_id="a", retiring=(LEGACY,)),
        event(event_id="b-event", replacement_id="b", retiring=(LEGACY,), scope=unit_scope("u2")),
    )
    positions = (replacement("a", event_id="a-event"), replacement("b", event_id="b-event", scope=unit_scope("u2")))
    first = _codes(evented(*positions, events=faulty), members=(UNIT, "u2"))
    second = _codes(evented(*reversed(positions), events=tuple(reversed(faulty))), members=(UNIT, "u2"))
    assert first == second and first


# =============================================================================
# 5. The executor refuses, never ignores
# =============================================================================


def test_an_invalid_evented_structure_is_refused_by_the_executor() -> None:
    with pytest.raises(CapitalStructureValidationError) as raised:
        run_unit(evented(replacement(), events=(event(),)))
    assert [issue.code for issue in raised.value.issues] == [Code.NO_SIZING_CONSTRAINT]


def test_an_investment_event_is_refused_in_a_standalone_unit() -> None:
    structure = evented(
        replacement(scope=INVESTMENT_SCOPE, position_class=PositionClass.MEZZANINE_DEBT, priority=1),
        events=(event(dscr=2.0, retiring=(), scope=INVESTMENT_SCOPE),),
    )
    with pytest.raises((CapitalStructureValidationError, CapitalStructureExecutionError)):
        run_unit(structure)


def test_an_investment_scoped_event_carries_the_typed_execution_code() -> None:
    """With a structurally valid Investment event (it retires Investment debt)
    a standalone Unit analysis refuses it as ``unsupported_event_scope``."""

    inv_debt = closing_debt("inv-mezz", amount=500_000.0, priority=1, rate=0.1, scope=INVESTMENT_SCOPE)
    heir = replacement(scope=INVESTMENT_SCOPE, position_class=PositionClass.MEZZANINE_DEBT, priority=1)
    structure = evented(inv_debt, heir, events=(event(dscr=2.0, retiring=(authored_ref("inv-mezz"),), scope=INVESTMENT_SCOPE),))
    assert _codes(structure) == []
    with pytest.raises(CapitalStructureExecutionError) as raised:
        run_unit(structure)
    codes = {issue.code for issue in raised.value.issues}
    assert ExecutionIssueCode.UNSUPPORTED_EVENT_SCOPE in codes


def test_the_narrowed_refusals_still_refuse_every_other_later_funding_and_fee() -> None:
    """Section 19: only a replacement's RefinanceProceeds funding and its fees
    at the event month are admitted. An ordinary later funding or fee is still
    refused exactly as before."""

    later_funding = CapitalPosition(
        position_id="draw",
        name="Draw",
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=2,
        scope=unit_scope(),
        funding=(FundingEvent(event_id="draw-f", model_month=24, sequence=1, amount_rule=FixedAmount(amount=100.0)),),
        terms=cash_pay_debt(rate=0.1),
        shortfall_resolution=replacement().shortfall_resolution,
    )
    with pytest.raises(CapitalStructureExecutionError) as raised:
        run_unit(plain(later_funding))
    assert {issue.code for issue in raised.value.issues} == {ExecutionIssueCode.UNSUPPORTED_FUNDING_TIMING}
    late_fee = closing_debt("m", amount=100.0, priority=2, rate=0.1)
    late_fee = dataclasses.replace(late_fee, terms=cash_pay_debt(rate=0.1, maturity_month=120, fees=(lender_fee(1.0, fee_id="late", month=24),)))
    with pytest.raises(CapitalStructureExecutionError) as raised:
        run_unit(plain(late_fee))
    assert {issue.code for issue in raised.value.issues} == {ExecutionIssueCode.UNSUPPORTED_FEE_TIMING}


def test_a_replacement_fee_at_the_event_month_is_admitted() -> None:
    terms, results = base_unit()
    result = run_unit(base_structure(dscr=2.0, replacement_fees=(lender_fee(80_000.0),)), terms=terms, results=results)
    (outcome,) = result.capital_events
    assert outcome.status.value == "executed"
