"""Refinance & Capital Events V1 Stage 1 -- dependencies and sizing.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 8 and 9, and
fixtures F1-F4, F3b, F11, F12, F14, F19, F21 and F22; invariants INV-13,
INV-17 and INV-18.

Expected capacities are the contract's own hand arithmetic from the stated
base case (Section 18.1): value $12,500,000 at a 6.4% direct cap, forward NOI
$800,000, and a replacement that is 5% interest-only, so its first-year
service is $0.05 per dollar.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction

import pytest
from _refinance_v1_fixtures import (  # type: ignore[import-not-found]
    FORWARD_NOI,
    LEGACY,
    LEGACY_PAYOFF_AT_24,
    TIMEPOINT_ID,
    UNIT,
    VALUE_AT_24,
    authority,
    authored_ref,
    base_structure,
    base_unit,
    close,
    closing_debt,
    event,
    evented,
    replacement,
    run_unit,
    stated_value,
    unit_authority,
    unit_scope,
)

from anchor.analysis.scenario import (
    ScenarioDefinition,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    resolve_quick_scenario,
)
from anchor.analysis.business_plan_analysis import analyze_quick_acquisition_with_business_plan
from anchor.business_plan import BusinessPlan
from anchor.capital_structure.contracts import CapitalStructureStatus, CommonEquityUnavailableReason, PositionClass
from anchor.capital_structure.execution_contracts import PositionResultStatus
from anchor.capital_structure.refinance_contracts import (
    ConstraintAvailability,
    ConstraintKind,
    RefinanceStatus,
    RefinanceUnavailableReason,
)
from anchor.contracts import acquisition_terms_from_inputs
from _p7_8_fixtures import round_inputs  # type: ignore[import-not-found]

FIXED, LTV, DSCR = ConstraintKind.FIXED_CAP, ConstraintKind.MAX_LTV, ConstraintKind.MIN_DSCR


def _sized(**sizing: float | None) -> object:
    return run_unit(base_structure(**sizing)).capital_events[0]


def _capacities(result: object) -> dict[ConstraintKind, float | None]:
    return {capacity.kind: capacity.capacity for capacity in result.sizing.capacities}  # type: ignore[attr-defined]


# =============================================================================
# F1-F4: the minimum of the enabled capacities, and ties
# =============================================================================


@pytest.mark.parametrize(
    ("sizing", "capacities", "gross", "binding"),
    [
        pytest.param(
            {"fixed": 7_500_000.0, "ltv": 0.65, "dscr": 2.0},
            {FIXED: 7_500_000, LTV: 8_125_000, DSCR: 8_000_000},
            7_500_000,
            (FIXED,),
            id="F1-fixed-cap",
        ),
        pytest.param(
            {"ltv": 0.60, "dscr": 1.60}, {LTV: 7_500_000, DSCR: 10_000_000}, 7_500_000, (LTV,), id="F2-ltv"
        ),
        pytest.param(
            {"ltv": 0.70, "dscr": 2.0}, {LTV: 8_750_000, DSCR: 8_000_000}, 8_000_000, (DSCR,), id="F3-dscr"
        ),
        pytest.param(
            {"fixed": 8_000_000.0, "ltv": 0.64, "dscr": 2.0},
            {FIXED: 8_000_000, LTV: 8_000_000, DSCR: 8_000_000},
            8_000_000,
            (FIXED, LTV, DSCR),
            id="F4-tie",
        ),
    ],
)
def test_gross_proceeds_are_the_least_enabled_capacity(
    sizing: dict[str, float], capacities: dict[ConstraintKind, int], gross: int, binding: tuple[ConstraintKind, ...]
) -> None:
    result = _sized(**sizing)
    assert result.status is RefinanceStatus.EXECUTED
    found = _capacities(result)
    assert set(found) == set(capacities)
    for kind, expected in capacities.items():
        assert close(found[kind], expected), (kind, found[kind])
    assert close(result.sizing.gross_proceeds, gross)
    assert result.sizing.binding == binding
    assert result.sizing.tie is (len(binding) > 1)
    assert close(result.bridge.net_event_cash, Fraction(gross) - LEGACY_PAYOFF_AT_24)


def test_every_capacity_reports_its_operands() -> None:
    result = _sized(fixed=7_500_000.0, ltv=0.65, dscr=2.0)
    by_kind = {capacity.kind: capacity.operands for capacity in result.sizing.capacities}
    assert by_kind[FIXED].amount == 7_500_000.0
    assert by_kind[LTV].max_ltv == 0.65 and close(by_kind[LTV].scope_value, VALUE_AT_24)
    assert by_kind[LTV].continuing_senior_balance == 0.0
    dscr = by_kind[DSCR]
    assert dscr.forward_noi == FORWARD_NOI and dscr.min_dscr == 2.0
    assert close(dscr.service_capacity, 400_000) and close(dscr.first_year_service_per_dollar, Fraction("0.05"))
    assert [capacity.kind for capacity in result.sizing.capacities] == [FIXED, LTV, DSCR]


def test_f3_achieves_the_target_dscr_on_the_executed_schedule() -> None:
    funding = _sized(ltv=0.70, dscr=2.0).funding
    assert close(funding.first_year_service, 400_000)
    assert close(funding.achieved_dscr, 2)
    assert close(funding.achieved_ltv, Fraction(8_000_000, 12_500_000))
    assert funding.first_service_month == 25 and funding.funding_month == 24


def test_a_fixed_cap_only_refinance_needs_neither_value_nor_noi() -> None:
    result = run_unit(base_structure(fixed=6_000_000.0), with_valuation=False).capital_events[0]
    assert result.status is RefinanceStatus.EXECUTED
    assert result.value_dependency is None and result.noi_dependency is None
    assert result.funding.achieved_ltv is None and result.funding.achieved_dscr is None


# =============================================================================
# F3b / INV-18: DSCR needs no valuation, and no valuation moves it
# =============================================================================


def test_f3b_dscr_only_executes_with_no_valuation_anywhere() -> None:
    result = run_unit(base_structure(dscr=2.0), with_valuation=False).capital_events[0]
    assert result.status is RefinanceStatus.EXECUTED
    assert close(result.sizing.gross_proceeds, 8_000_000) and result.sizing.binding == (DSCR,)
    assert close(result.bridge.net_event_cash, 2_480_000)
    assert result.value_dependency is None
    assert result.noi_dependency.forward_noi == FORWARD_NOI and result.noi_dependency.forward_year == 3
    assert result.funding.achieved_ltv is None


@pytest.mark.parametrize(
    "valuations",
    [
        pytest.param(lambda terms, results: None, id="none"),
        pytest.param(lambda terms, results: unit_authority(terms, results), id="direct-cap"),
        pytest.param(lambda terms, results: unit_authority(terms, results, methods={UNIT: stated_value(1.0)}), id="stated"),
        pytest.param(lambda terms, results: unit_authority(terms, results, month=36), id="other-month"),
    ],
)
def test_inv_18_a_dscr_only_result_is_invariant_to_every_valuation(valuations: object) -> None:
    terms, results = base_unit()
    reference = run_unit(base_structure(dscr=2.0), terms=terms, results=results, with_valuation=False)
    other = run_unit(
        base_structure(dscr=2.0), terms=terms, results=results, valuations=valuations(terms, results), with_valuation=False  # type: ignore[operator]
    )
    assert repr(other) == repr(reference)


def test_inv_18_an_ltv_value_change_leaves_the_dscr_capacity_unchanged() -> None:
    terms, results = base_unit()
    low = run_unit(base_structure(ltv=0.65, dscr=2.0), terms=terms, results=results, valuations=unit_authority(terms, results, methods={UNIT: stated_value(9_000_000.0)}))
    high = run_unit(base_structure(ltv=0.65, dscr=2.0), terms=terms, results=results, valuations=unit_authority(terms, results, methods={UNIT: stated_value(20_000_000.0)}))
    assert _capacities(low.capital_events[0])[DSCR] == _capacities(high.capital_events[0])[DSCR]
    assert _capacities(low.capital_events[0])[LTV] != _capacities(high.capital_events[0])[LTV]


# =============================================================================
# F11 / F12: unavailable dependencies are never zero and never fall back
# =============================================================================


def _assert_unavailable_downstream(result: object) -> None:
    common = result.common_equity  # type: ignore[attr-defined]
    assert common.cash_flows is None and common.recurring_cash_flows is None and common.event_cash_flows is None
    assert common.status is CapitalStructureStatus.REFINANCE_UNAVAILABLE
    assert common.unavailable_reason is CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE
    assert common.irr is None and common.total_profit is None
    (unexecuted,) = result.unexecuted_positions  # type: ignore[attr-defined]
    assert unexecuted.position_id == replacement().position_id


def test_f11_a_missing_timepoint_makes_ltv_unavailable_and_dscr_still_reported() -> None:
    terms, results = base_unit()
    result = run_unit(
        base_structure(ltv=0.65, dscr=2.0), terms=terms, results=results, valuations=unit_authority(terms, results, timepoint_id="other")
    )
    outcome = result.capital_events[0]
    assert outcome.status is RefinanceStatus.UNAVAILABLE
    assert outcome.unavailable_reason is RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND
    capacities = {capacity.kind: capacity for capacity in outcome.sizing.capacities}
    assert capacities[LTV].status is ConstraintAvailability.UNAVAILABLE and capacities[LTV].capacity is None
    assert capacities[DSCR].status is ConstraintAvailability.AVAILABLE and close(capacities[DSCR].capacity, 8_000_000)
    assert outcome.sizing.gross_proceeds is None and outcome.bridge is None and outcome.funding is None
    _assert_unavailable_downstream(result)
    assert result.legacy_acquisition_loans  # the Project and the legacy loan stand
    assert "purchase price" in (outcome.unavailable_message or "") or outcome.unavailable_message


def test_f11_no_valuation_authority_at_all_is_timepoint_not_found() -> None:
    outcome = run_unit(base_structure(ltv=0.65), with_valuation=False).capital_events[0]
    assert outcome.unavailable_reason is RefinanceUnavailableReason.TIMEPOINT_NOT_FOUND


def test_f12a_a_non_positive_forward_noi_makes_dscr_unavailable_even_with_a_stated_value() -> None:
    terms, results = base_unit(current_noi=-100_000.0)
    values = unit_authority(terms, results, methods={UNIT: stated_value(12_500_000.0)})
    outcome = run_unit(base_structure(ltv=0.65, dscr=2.0), terms=terms, results=results, valuations=values).capital_events[0]
    capacities = {capacity.kind: capacity for capacity in outcome.sizing.capacities}
    assert capacities[LTV].status is ConstraintAvailability.AVAILABLE and close(capacities[LTV].capacity, 8_125_000)
    assert capacities[DSCR].unavailable_reason is RefinanceUnavailableReason.NON_POSITIVE_FORWARD_NOI
    assert capacities[DSCR].capacity is None and capacities[DSCR].operands.forward_noi == -100_000.0
    assert outcome.status is RefinanceStatus.UNAVAILABLE
    assert outcome.unavailable_reason is RefinanceUnavailableReason.NON_POSITIVE_FORWARD_NOI


def test_f12b_dscr_only_with_non_positive_noi_is_unavailable() -> None:
    terms, results = base_unit(current_noi=0.0)
    outcome = run_unit(base_structure(dscr=2.0), terms=terms, results=results, with_valuation=False).capital_events[0]
    assert outcome.unavailable_reason is RefinanceUnavailableReason.NON_POSITIVE_FORWARD_NOI


def test_an_unavailable_direct_cap_cell_carries_p7_10s_own_reason() -> None:
    terms, results = base_unit(current_noi=-1.0)
    outcome = run_unit(base_structure(ltv=0.65), terms=terms, results=results).capital_events[0]
    assert outcome.unavailable_reason is RefinanceUnavailableReason.VALUATION_UNAVAILABLE
    assert outcome.value_dependency.valuation_unavailable_reason.value == "non_positive_forward_noi"
    assert outcome.value_dependency.value is None


# =============================================================================
# F14: the exact scope and the exact month, never another
# =============================================================================


def test_f14c_a_valuation_without_a_cell_for_this_unit_is_scope_not_covered() -> None:
    terms, results = base_unit()
    values = authority((("other-unit", terms, results),))
    outcome = run_unit(base_structure(ltv=0.65), terms=terms, results=results, valuations=values).capital_events[0]
    assert outcome.unavailable_reason is RefinanceUnavailableReason.SCOPE_NOT_COVERED


def test_f14d_a_valuation_at_another_month_is_never_the_nearest_match() -> None:
    terms, results = base_unit()
    outcome = run_unit(
        base_structure(ltv=0.65), terms=terms, results=results, valuations=unit_authority(terms, results, month=36)
    ).capital_events[0]
    assert outcome.unavailable_reason is RefinanceUnavailableReason.MODEL_MONTH_MISMATCH
    assert outcome.value_dependency is None


def test_a_direct_cap_cell_reconciles_to_the_noi_authority() -> None:
    """R-C: a direct-cap cell's recorded forward NOI equals the variant's NOI
    authority, bit for bit, and is never the NOI source."""

    outcome = _sized(ltv=0.65, dscr=2.0)
    assert outcome.noi_dependency.forward_noi == FORWARD_NOI
    assert outcome.value_dependency.method.value == "direct_cap"


# =============================================================================
# F19: a Scenario moves capacities only through the accepted upstream analysis
# =============================================================================


def _downside() -> tuple[object, object]:
    """Contract F19 scales current NOI by 0.90, but the ratified P7.1 registry
    has no ``current_noi`` target, so the downside is expressed through the
    accepted ``noi_growth`` target instead: SET -5% makes Year 3 NOI -- the
    forward NOI at month 24 -- 800,000 x 0.95^2 = 722,000. The property proven
    is the contract's: both capacities fall through accepted upstream analysis
    and nothing refinance-specific."""

    scenario = ScenarioDefinition(
        scenario_id="downside",
        name="Downside",
        overrides=(ScenarioOverride(unit_id=UNIT, target=ScenarioTarget.NOI_GROWTH, operation=ScenarioOperation.SET, value=-0.05),),
    )
    inputs = round_inputs(interest_rate=0.0, amortization=25, io_period=0, exit_cap_rate=0.064)
    resolved = resolve_quick_scenario(inputs, unit_id=UNIT, scenario=scenario, business_plan=BusinessPlan())
    results = analyze_quick_acquisition_with_business_plan(resolved.inputs, business_plan=resolved.business_plan)
    return acquisition_terms_from_inputs(resolved.inputs), results


def test_f19_the_downside_scenario_lowers_both_capacities_to_a_tie() -> None:
    terms, results = _downside()
    outcome = run_unit(base_structure(ltv=0.64, dscr=2.0), terms=terms, results=results).capital_events[0]  # type: ignore[arg-type]
    found = _capacities(outcome)
    noi = Fraction(800_000) * Fraction("0.95") ** 2
    assert noi == 722_000
    assert close(found[LTV], Fraction("0.64") * noi / Fraction("0.064"), rel=1e-12)
    assert close(found[DSCR], noi / 2 / Fraction("0.05"), rel=1e-12)
    assert close(found[LTV], 7_220_000) and close(found[DSCR], 7_220_000)
    assert close(outcome.sizing.gross_proceeds, 7_220_000) and outcome.sizing.tie
    assert close(outcome.bridge.net_event_cash, 1_700_000)
    assert outcome.payoffs[0].payoff == LEGACY_PAYOFF_AT_24  # NOI never moves the legacy payoff


def test_f19_a_stated_value_does_not_move_so_the_binding_switches_to_dscr() -> None:
    terms, results = _downside()
    values = unit_authority(terms, results, methods={UNIT: stated_value(12_500_000.0)})  # type: ignore[arg-type]
    outcome = run_unit(base_structure(ltv=0.64, dscr=2.0), terms=terms, results=results, valuations=values).capital_events[0]  # type: ignore[arg-type]
    found = _capacities(outcome)
    assert close(found[LTV], 8_000_000) and close(found[DSCR], 7_220_000)
    assert outcome.sizing.binding == (DSCR,)


# =============================================================================
# F21: through the position, behind continuing senior debt
# =============================================================================


def _junior_refinance(ltv: float) -> object:
    mezz = closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.10, io_period=10, maturity_month=120)
    heir = replacement(priority=2, position_class=PositionClass.MEZZANINE_DEBT)
    return evented(mezz, heir, events=(event(ltv=ltv, dscr=1.25, retiring=(authored_ref("mezz"),)),))


def test_f21_sizing_is_net_of_the_continuing_legacy_loan() -> None:
    outcome = run_unit(_junior_refinance(0.60)).capital_events[0]
    by_kind = {capacity.kind: capacity for capacity in outcome.sizing.capacities}
    assert by_kind[LTV].operands.continuing_senior_balance == LEGACY_PAYOFF_AT_24
    assert by_kind[DSCR].operands.continuing_senior_service == 240_000
    assert close(by_kind[LTV].capacity, 7_500_000 - LEGACY_PAYOFF_AT_24)
    assert close(by_kind[DSCR].capacity, (Fraction(800_000) / Fraction("1.25") - 240_000) / Fraction("0.05"))
    assert outcome.sizing.binding == (LTV,) and close(outcome.sizing.gross_proceeds, 1_980_000)
    (payoff,) = outcome.payoffs
    assert payoff.position_id == "mezz" and close(payoff.payoff, 1_000_000)
    assert close(outcome.bridge.net_event_cash, 980_000)
    assert close(outcome.funding.achieved_ltv, Fraction("0.6"))


# =============================================================================
# F22: not executable, and the horizon
# =============================================================================


def test_f22a_a_non_positive_capacity_is_not_executable_and_never_keeps_the_old_loan() -> None:
    result = run_unit(_junior_refinance(0.40))
    outcome = result.capital_events[0]
    assert outcome.status is RefinanceStatus.NOT_EXECUTABLE
    assert outcome.unavailable_reason is RefinanceUnavailableReason.NON_POSITIVE_CAPACITY
    assert close(_capacities(outcome)[LTV], 5_000_000 - LEGACY_PAYOFF_AT_24)
    assert outcome.sizing.gross_proceeds is None and outcome.funding is None and outcome.bridge is None
    _assert_unavailable_downstream(result)
    (mezz,) = [position for position in result.positions if position.position_id == "mezz"]
    assert mezz.status is PositionResultStatus.REFINANCE_UNAVAILABLE and mezz.irr is None


def test_f22b_an_event_at_or_after_the_sale_is_outside_the_horizon() -> None:
    terms, results = base_unit(hold_period=2)
    outcome = run_unit(base_structure(dscr=2.0), terms=terms, results=results, with_valuation=False).capital_events[0]
    assert outcome.status is RefinanceStatus.UNAVAILABLE
    assert outcome.unavailable_reason is RefinanceUnavailableReason.EVENT_OUTSIDE_HOLD_HORIZON
    assert outcome.sizing is None


def test_a_retired_loan_already_repaid_is_not_outstanding() -> None:
    terms, results = base_unit(interest_rate=0.05, amortization=1)
    outcome = run_unit(base_structure(dscr=2.0), terms=terms, results=results, with_valuation=False).capital_events[0]
    assert outcome.unavailable_reason is RefinanceUnavailableReason.RETIRING_POSITION_NOT_OUTSTANDING


def test_a_retired_acquisition_loan_this_variant_lacks_is_absent() -> None:
    terms, results = base_unit(ltv=0.0)
    outcome = run_unit(base_structure(dscr=2.0), terms=terms, results=results, with_valuation=False).capital_events[0]
    assert outcome.unavailable_reason is RefinanceUnavailableReason.RETIRING_POSITION_ABSENT


# =============================================================================
# INV-17: sizing is monotone in every input
# =============================================================================


@pytest.mark.parametrize(
    ("low", "high"),
    [
        ({"fixed": 7_000_000.0, "ltv": 0.64, "dscr": 2.0}, {"fixed": 7_500_000.0, "ltv": 0.64, "dscr": 2.0}),
        ({"ltv": 0.60, "dscr": 1.5}, {"ltv": 0.62, "dscr": 1.5}),
        ({"ltv": 0.70, "dscr": 2.2}, {"ltv": 0.70, "dscr": 2.0}),
    ],
)
def test_inv_17_raising_a_binding_input_raises_the_proceeds(low: dict[str, float], high: dict[str, float]) -> None:
    assert _sized(**high).sizing.gross_proceeds > _sized(**low).sizing.gross_proceeds


def test_inv_17_raising_a_non_binding_input_changes_nothing() -> None:
    assert _sized(fixed=7_000_000.0, ltv=0.64).sizing.gross_proceeds == _sized(fixed=7_000_000.0, ltv=0.70).sizing.gross_proceeds


def test_inv_17_raising_value_or_noi_never_lowers_the_proceeds() -> None:
    terms_low, results_low = base_unit()
    terms_high, results_high = base_unit(current_noi=900_000.0)
    low = run_unit(base_structure(ltv=0.65, dscr=2.0), terms=terms_low, results=results_low).capital_events[0]
    high = run_unit(base_structure(ltv=0.65, dscr=2.0), terms=terms_high, results=results_high).capital_events[0]
    assert high.sizing.gross_proceeds >= low.sizing.gross_proceeds
