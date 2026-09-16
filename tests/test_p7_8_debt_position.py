"""Phase 7 Gate P7.8 -- authored debt: the thin ``debt.py`` wrapper, the Unit
debt golden, coverage and debt yield through a position, and the IRR authority.

``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md`` Sections 6, 12 and
13, under ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
12.4 and 12.6. Every expected figure is prepared independently: from the
completed project result (the upstream authority) and from closed-form hand
arithmetic in ``tests/_p7_8_fixtures.py`` -- never from the executor.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

from _p7_7_fixtures import bits  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    CEC,
    GOLDEN_MEZZ_AMOUNT,
    GOLDEN_MEZZ_FEE,
    UNIT,
    all_close,
    cash_pay_debt,
    claim_position,
    close,
    fee,
    golden_mezz,
    hand_balance,
    hand_level_payment,
    npv,
    preferred,
    round_unit,
    structure,
)
from anchor.capital_structure import (
    AccrualConvention,
    CapitalStructureStatus,
    FundingRequirementStatus,
    PositionCashFlowKind,
    PositionClass,
    PositionResultStatus,
    PriceBasis,
    PriceBasisKind,
    adapt_legacy_acquisition_loan,
    execute_unit_capital_structure,
    metrics,
    schedule_position,
)
from anchor.capital_structure.debt_position import modeled_debt_payoff_month, schedule_debt_position
from anchor.contracts import AcquisitionTerms
from anchor.engine import debt as engine_debt
from anchor.engine import returns as engine_returns
from anchor.engine.contracts import IrrStatus

Kind = PositionCashFlowKind


def _scheduled_by_year(events: tuple[Any, ...], hold: int) -> list[float]:
    by_year = [0.0] * hold
    for event in events:
        if event.kind is Kind.SCHEDULED_DEBT_SERVICE:
            year = (event.model_month - 1) // 12
            by_year[year] = by_year[year] + event.amount
    return by_year


# =============================================================================
# 1. The thin wrapper is the debt engine's own schedule
# =============================================================================


@pytest.mark.parametrize(
    ("principal", "rate", "amortization", "io_period", "hold"),
    [
        (1_500_000.0, 0.12, 25, 1, 5),
        (6_000_000.0, 0.0575, 30, 2, 7),
        (2_345_678.9, 0.0, 10, 0, 5),
        (3_000_000.0, 0.09, 3, 0, 5),
        (5_000_000.0, 0.06, 30, 5, 5),
    ],
)
def test_the_schedule_is_the_debt_engines_own_schedule_bit_for_bit(
    principal: float, rate: float, amortization: int, io_period: int, hold: int
) -> None:
    """A position maturing after the exit is paid off at the exit, exactly like
    an acquisition loan of the same principal through the unchanged
    ``calculate_debt_schedule``: the same level payment, the same annual debt
    service and the same balance, bit for bit."""

    terms = cash_pay_debt(rate=rate, amortization=amortization, io_period=io_period, maturity_month=12 * hold + 24)
    schedule, events = schedule_debt_position(position_id="p", principal=principal, terms=terms, hold_period=hold)
    loan = engine_debt.calculate_debt_schedule(
        AcquisitionTerms(
            purchase_price=principal, hold_period=hold, exit_cap_rate=0.07, ltv=1.0, interest_rate=rate,
            amortization=amortization, acquisition_cost_pct=0.0, financing_fee_pct=0.0, disposition_cost_pct=0.0,
            annual_capex_reserve=0.0, io_period=io_period,
        )
    )
    assert schedule.scheduled_full_amortization_month == 12 * io_period + 12 * amortization
    assert schedule.modeled_payoff_month == min(12 * hold, 12 * io_period + 12 * amortization)
    assert bits([schedule.amortizing_payment]) == bits([loan.monthly_debt_service])
    assert bits(_scheduled_by_year(events, hold)) == bits(loan.annual_debt_service)
    assert bits([schedule.balance_at_payoff]) == bits([loan.remaining_loan_balance])
    balloons = [event for event in events if event.kind is Kind.BALLOON]
    if loan.remaining_loan_balance == 0.0:
        assert balloons == []
    else:
        (balloon,) = balloons
        assert (balloon.model_month, balloon.sequence) == (12 * hold, 2)
        assert bits([balloon.amount]) == bits([loan.remaining_loan_balance])


def test_a_maturity_before_the_exit_pays_the_remaining_balance_at_maturity() -> None:
    terms = cash_pay_debt(rate=0.09, amortization=20, io_period=0, maturity_month=42)
    schedule, events = schedule_debt_position(position_id="p", principal=1_000_000.0, terms=terms, hold_period=5)

    assert (schedule.maturity_month, schedule.modeled_payoff_month) == (42, 42)
    assert [event.model_month for event in events if event.kind is Kind.SCHEDULED_DEBT_SERVICE] == list(range(1, 43))
    (balloon,) = [event for event in events if event.kind is Kind.BALLOON]
    assert (balloon.model_month, balloon.sequence) == (42, 2)
    balances = engine_debt.calculate_amortization_schedule(
        loan_amount=1_000_000.0, monthly_rate=0.09 / 12, monthly_debt_service=schedule.amortizing_payment,
        n_payments=240, months_to_run=42,
    )
    assert bits([balloon.amount, schedule.balance_at_payoff]) == bits([balances[-1], balances[-1]])
    hand = hand_balance(1_000_000.0, 0.09, hand_level_payment(1_000_000.0, 0.09, 240), 42)
    assert close(balloon.amount, hand, 1e-6)
    assert modeled_debt_payoff_month(maturity_month=42, hold_period=5, full_amortization_month=240) == 42
    assert modeled_debt_payoff_month(maturity_month=90, hold_period=5, full_amortization_month=240) == 60


def test_a_loan_fully_amortized_before_its_payoff_has_no_balloon() -> None:
    terms = cash_pay_debt(rate=0.08, amortization=2, io_period=0, maturity_month=60)
    schedule, events = schedule_debt_position(position_id="p", principal=500_000.0, terms=terms, hold_period=5)
    assert [event.model_month for event in events] == list(range(1, 25))
    assert schedule.balance_at_payoff == 0.0
    assert (schedule.maturity_month, schedule.scheduled_full_amortization_month, schedule.modeled_payoff_month) == (60, 24, 24)


def test_senior_and_mezzanine_debt_share_one_schedule() -> None:
    """The class orders payment and reporting; it never selects a formula."""

    basis = PriceBasis(kind=PriceBasisKind.UNIT_PURCHASE_PRICE, amount=10_000_000.0)
    amounts = []
    for position_class in (PositionClass.SENIOR_DEBT, PositionClass.MEZZANINE_DEBT):
        position = dataclasses.replace(golden_mezz(), position_class=position_class)
        scheduled = schedule_position(position, price_basis=basis, hold_period=5)
        amounts.append([(event.model_month, event.kind, event.amount) for event in scheduled.events])
    assert amounts[0] == amounts[1]


# =============================================================================
# 2. The Unit debt golden: legacy first mortgage, then an authored mezzanine loan
# =============================================================================

#: Hand arithmetic, from the closed-form annuity: $1,500,000 at 12% (1% a
#: month), twelve interest-only months, then a 300-month level payment; the
#: balloon at month 48 follows 36 amortizing payments.
PMT = hand_level_payment(GOLDEN_MEZZ_AMOUNT, 0.12, 300)
IO_PAYMENT = 15_000.0
BALLOON = hand_balance(GOLDEN_MEZZ_AMOUNT, 0.12, PMT, 36)
YEAR_1 = 12 * IO_PAYMENT
YEAR_2 = YEAR_3 = 12 * PMT
YEAR_4 = 12 * PMT + BALLOON
RECEIVED = GOLDEN_MEZZ_FEE + YEAR_1 + YEAR_2 + YEAR_3 + YEAR_4


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    terms, results = round_unit()
    before = dataclasses.asdict(results)
    result = execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(golden_mezz())
    )
    return {"terms": terms, "results": results, "before": before, "result": result, "mezz": result.positions[0]}


def test_the_golden_premise_is_the_round_number_unit(golden: dict[str, Any]) -> None:
    results = golden["results"]
    assert results.levered_cash_flows == (-4_000_000.0, 500_000.0, 500_000.0, 500_000.0, 500_000.0, 4_500_000.0)
    assert results.annual_debt_service == (300_000.0,) * 5 and results.loan_amount == 6_000_000.0
    assert results.noi_by_year == (800_000.0,) * 5


def test_golden_debt_schedule(golden: dict[str, Any]) -> None:
    mezz = golden["mezz"]
    schedule = mezz.debt_schedule
    assert mezz.funded_amount == GOLDEN_MEZZ_AMOUNT
    assert (schedule.n_payments, schedule.io_months, schedule.io_payment) == (300, 12, IO_PAYMENT)
    assert math.isclose(schedule.amortizing_payment, PMT, rel_tol=1e-12)
    assert (schedule.maturity_month, schedule.modeled_payoff_month, mezz.modeled_payoff_month) == (48, 48, 48)
    assert close(schedule.balance_at_payoff, BALLOON, 1e-5)
    assert mezz.balance_at_maturity_or_exit == schedule.balance_at_payoff

    events = mezz.cash_flow_events
    assert [(e.event_id, e.model_month, e.kind, e.amount) for e in events[:2]] == [
        ("mezz-funding", 0, Kind.FUNDING, -GOLDEN_MEZZ_AMOUNT),
        ("mezz-fee", 0, Kind.FEE, GOLDEN_MEZZ_FEE),
    ]
    payments = [e for e in events if e.kind is Kind.SCHEDULED_DEBT_SERVICE]
    assert [e.amount for e in payments[:12]] == [IO_PAYMENT] * 12
    assert bits([e.amount for e in payments[12:]]) == bits([schedule.amortizing_payment] * 36)
    assert events[-1].kind is Kind.BALLOON and events[-1].model_month == 48
    assert len(events) == 2 + 48 + 1


def test_golden_annual_position_cash_flow(golden: dict[str, Any]) -> None:
    annual = golden["mezz"].annual_cash_flows
    assert annual[0] == -1_485_000.0 and annual[1] == YEAR_1 and annual[5] == 0.0
    assert all_close(annual, (-1_485_000.0, YEAR_1, YEAR_2, YEAR_3, YEAR_4, 0.0), 1e-5)


def test_golden_claims_and_funding_requirement(golden: dict[str, Any]) -> None:
    """Years 1-3 are covered by the Unit's own $500,000 of post-debt cash. The
    year-4 claim -- twelve payments and the balloon -- is not: the shortfall is
    one resolved Funding Requirement, met by a common-equity contribution."""

    mezz, result = golden["mezz"], golden["result"]
    assert [claim.hold_year for claim in mezz.annual_claims] == [1, 2, 3, 4]
    for claim in mezz.annual_claims:
        assert claim.settlement.claim.cash_available == 500_000.0
    for claim in mezz.annual_claims[:3]:
        assert claim.settlement.funding_requirement is None
        assert claim.settlement.claim_paid_from_cash == claim.claim_due
    year_4 = mezz.annual_claims[3]
    assert year_4.component_event_ids == (
        *(f"mezz:scheduled_debt_service:{month}" for month in range(37, 49)),
        "mezz:balloon:48",
    )
    requirement = year_4.settlement.funding_requirement
    assert requirement is not None
    assert requirement.requirement_id == "mezz/hold_year/4"
    assert requirement.status is FundingRequirementStatus.RESOLVED
    assert close(requirement.amount, YEAR_4 - 500_000.0, 1e-5)
    assert requirement.equity_contribution == requirement.amount and requirement.unpaid_claim_amount == 0.0
    assert result.funding_requirements == (requirement,) == mezz.funding_requirements


def test_golden_common_equity_cash_flow(golden: dict[str, Any]) -> None:
    """The residual of the Unit's post-acquisition-debt cash, less the mezz: the
    acquisition loan is never subtracted again."""

    results, common = golden["results"], golden["result"].common_equity
    flows = common.cash_flows
    assert flows[0] == -4_000_000.0 + GOLDEN_MEZZ_AMOUNT - GOLDEN_MEZZ_FEE == -2_515_000.0
    assert flows[1] == 500_000.0 - YEAR_1 == 320_000.0
    assert bits([flows[5]]) == bits([results.levered_cash_flows[5]])
    assert all_close(flows, (-2_515_000.0, 320_000.0, 500_000.0 - YEAR_2, 500_000.0 - YEAR_3, 500_000.0 - YEAR_4, 4_500_000.0), 1e-5)
    assert common.status is CapitalStructureStatus.COMPLETE and common.position_id is None


def test_golden_position_returns(golden: dict[str, Any]) -> None:
    mezz = golden["mezz"]
    assert mezz.status is PositionResultStatus.COMPLETE and mezz.unavailable_reason is None
    assert mezz.irr_status is IrrStatus.DEFINED
    assert 0.12 < mezz.irr < 0.13
    assert close(npv(mezz.irr, mezz.annual_cash_flows), 0.0, 1e-3)
    assert close(mezz.total_cash_received, RECEIVED, 1e-5)
    assert math.isclose(mezz.moic, RECEIVED / GOLDEN_MEZZ_AMOUNT, rel_tol=1e-12)
    assert close(mezz.profit, RECEIVED - GOLDEN_MEZZ_AMOUNT, 1e-5)
    # Gross capital advanced: the closing fee is never netted against it.
    assert not math.isclose(mezz.moic, (RECEIVED - GOLDEN_MEZZ_FEE) / (GOLDEN_MEZZ_AMOUNT - GOLDEN_MEZZ_FEE), rel_tol=1e-9)


def test_golden_structural_metrics(golden: dict[str, Any]) -> None:
    mezz = golden["mezz"]
    assert mezz.valuation_basis == PriceBasis(kind=PriceBasisKind.UNIT_PURCHASE_PRICE, amount=10_000_000.0)
    assert (mezz.attachment_basis, mezz.detachment_basis, mezz.last_dollar_basis) == (6_000_000.0, 7_500_000.0, 7_500_000.0)
    assert (mezz.attachment_ltv, mezz.detachment_ltv) == (0.6, 0.75)
    assert mezz.debt_yield_through == 800_000.0 / 7_500_000.0
    coverage = mezz.coverage_by_year
    assert coverage[0] == 800_000.0 / (300_000.0 + YEAR_1)
    assert all(math.isclose(value, 800_000.0 / (300_000.0 + YEAR_2), rel_tol=1e-12) for value in coverage[1:4])
    assert coverage[4] is None  # repaid at month 48: not outstanding in year 5
    assert mezz.headline_coverage == coverage[0] and mezz.minimum_coverage == min(coverage[1:4])


def test_golden_leaves_every_upstream_figure_untouched(golden: dict[str, Any]) -> None:
    results, result = golden["results"], golden["result"]
    assert dataclasses.asdict(results) == golden["before"]
    (loan,) = result.legacy_acquisition_loans
    assert loan == adapt_legacy_acquisition_loan(unit_id=UNIT, terms=golden["terms"], results=results)
    assert result.common_equity.irr != results.levered_irr


def test_an_interest_only_loan_bought_at_par_yields_its_coupon() -> None:
    terms, results = round_unit()
    par = claim_position(
        "mezz", position_class=PositionClass.MEZZANINE_DEBT, priority=2, resolution=CEC, amount=1_500_000.0,
        terms=cash_pay_debt(rate=0.12, amortization=25, io_period=5, maturity_month=60),
    )
    (mezz,) = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(par)).positions
    assert mezz.annual_cash_flows == (-1_500_000.0, 180_000.0, 180_000.0, 180_000.0, 180_000.0, 1_680_000.0)
    assert close(mezz.irr, 0.12, 1e-9)
    assert mezz.moic == 1.6 and mezz.profit == 900_000.0


# =============================================================================
# 3. The IRR authority
# =============================================================================


def test_every_irr_is_the_existing_procedure(monkeypatch: pytest.MonkeyPatch) -> None:
    terms, results = round_unit()
    seen: list[tuple[float, ...]] = []

    def spy(cash_flows: tuple[float, ...]) -> Any:
        seen.append(cash_flows)
        return engine_returns.evaluate_irr(cash_flows)

    monkeypatch.setattr(metrics, "evaluate_irr", spy)
    result = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(golden_mezz()))
    (mezz,) = result.positions
    assert seen == [mezz.annual_cash_flows, result.common_equity.cash_flows]
    assert mezz.annual_cash_flows is not None
    assert (mezz.irr, mezz.irr_status) == engine_returns.evaluate_irr(mezz.annual_cash_flows)


def test_an_undefined_position_irr_keeps_its_status_and_the_multiple_stays_defined() -> None:
    """A closing fee equal to the funding nets the closing period to zero, so
    the first nonzero flow is a receipt: the IRR convention reports it N/A and
    selects nothing. MOIC reads gross flows and is defined."""

    terms, results = round_unit()
    odd = claim_position(
        "mezz", position_class=PositionClass.MEZZANINE_DEBT, priority=2, resolution=CEC, amount=10_000.0,
        terms=cash_pay_debt(rate=0.12, io_period=5, fees=(fee("mezz-fee", amount=10_000.0),)),
    )
    (mezz,) = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(odd)).positions
    assert mezz.annual_cash_flows is not None and mezz.annual_cash_flows[0] == 0.0
    assert (mezz.irr, mezz.irr_status) == (None, IrrStatus.FIRST_NONZERO_NOT_NEGATIVE)
    assert close(mezz.moic, (10_000.0 + 5 * 1_200.0 + 10_000.0) / 10_000.0, 1e-9)


# =============================================================================
# 4. The modeled payoff is the earliest extinguishment (final review correction)
# =============================================================================


@pytest.mark.parametrize(
    ("amortization", "io_period", "maturity_month", "full_amortization", "payoff", "balloon"),
    [
        (20, 0, 42, 240, 42, True),  # legal maturity before full amortization and the exit
        (30, 0, 84, 360, 60, True),  # the exit before maturity and full amortization
        (2, 0, 60, 24, 24, False),  # full amortization before maturity and the exit
        (2, 1, 60, 36, 36, False),  # interest-only, then amortization: io_months + n_payments
        (5, 0, 60, 60, 60, False),  # all three coincide
    ],
)
def test_the_modeled_payoff_is_the_earliest_of_maturity_exit_and_full_amortization(
    amortization: int, io_period: int, maturity_month: int, full_amortization: int, payoff: int, balloon: bool
) -> None:
    terms = cash_pay_debt(rate=0.08, amortization=amortization, io_period=io_period, maturity_month=maturity_month)
    schedule, events = schedule_debt_position(position_id="p", principal=500_000.0, terms=terms, hold_period=5)

    assert schedule.maturity_month == maturity_month  # the legal maturity, never rewritten
    assert schedule.scheduled_full_amortization_month == full_amortization == schedule.io_months + schedule.n_payments
    assert schedule.modeled_payoff_month == payoff == modeled_debt_payoff_month(
        maturity_month=maturity_month, hold_period=5, full_amortization_month=full_amortization
    )
    assert max(event.model_month for event in events) == payoff
    balloons = [event for event in events if event.kind is Kind.BALLOON]
    if balloon:
        (payoff_balloon,) = balloons
        assert payoff_balloon.model_month == payoff and payoff_balloon.amount > 0.0
        assert schedule.balance_at_payoff == payoff_balloon.amount
    else:
        assert balloons == [] and schedule.balance_at_payoff == 0.0


#: Hand: $500,000 at 8% over 24 level payments, no interest-only months.
EARLY_PMT = hand_level_payment(500_000.0, 0.08, 24)


@pytest.fixture(scope="module")
def early() -> dict[str, Any]:
    """The round-number Unit (its $6,000,000 legacy mortgage pays $300,000 in
    every one of the five years) with a mezzanine loan that amortizes fully in
    two years although its legal maturity is month 60."""

    terms, results = round_unit()
    mezz = claim_position(
        "mezz", position_class=PositionClass.MEZZANINE_DEBT, priority=2, resolution=CEC, amount=500_000.0,
        terms=cash_pay_debt(rate=0.08, amortization=2, io_period=0, maturity_month=60),
    )
    result = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(mezz))
    return {"results": results, "result": result, "mezz": result.positions[0]}


def test_early_amortization_payoff_semantics(early: dict[str, Any]) -> None:
    mezz = early["mezz"]
    schedule = mezz.debt_schedule
    assert schedule.maturity_month == 60
    assert schedule.scheduled_full_amortization_month == 24
    assert (schedule.modeled_payoff_month, mezz.modeled_payoff_month) == (24, 24)
    assert schedule.balance_at_payoff == 0.0 and mezz.balance_at_maturity_or_exit == 0.0
    assert math.isclose(schedule.amortizing_payment, EARLY_PMT, rel_tol=1e-12)
    payments = [event.model_month for event in mezz.cash_flow_events if event.kind is Kind.SCHEDULED_DEBT_SERVICE]
    assert payments == list(range(1, 25))
    assert [event for event in mezz.cash_flow_events if event.kind is Kind.BALLOON] == []


def test_early_amortization_leaves_the_provider_cash_flow_unchanged(early: dict[str, Any]) -> None:
    """The same loan through the unchanged debt engine over the whole hold --
    the pre-correction schedule -- pays in years 1-2 only: the provider series
    is identical, bit for bit."""

    mezz = early["mezz"]
    loan = engine_debt.calculate_debt_schedule(
        AcquisitionTerms(
            purchase_price=500_000.0, hold_period=5, exit_cap_rate=0.07, ltv=1.0, interest_rate=0.08, amortization=2,
            acquisition_cost_pct=0.0, financing_fee_pct=0.0, disposition_cost_pct=0.0, annual_capex_reserve=0.0,
            io_period=0,
        )
    )
    assert loan.remaining_loan_balance == 0.0
    assert mezz.annual_cash_flows[0] == -500_000.0
    assert bits(mezz.annual_cash_flows[1:]) == bits(loan.annual_debt_service)
    assert all_close(mezz.annual_cash_flows, (-500_000.0, 12 * EARLY_PMT, 12 * EARLY_PMT, 0.0, 0.0, 0.0))
    assert mezz.status is PositionResultStatus.COMPLETE and mezz.irr_status is IrrStatus.DEFINED


def test_coverage_through_an_amortized_mezz_is_na_while_the_senior_mortgage_continues(early: dict[str, Any]) -> None:
    results, mezz = early["results"], early["mezz"]
    assert results.annual_debt_service == (300_000.0,) * 5  # the senior mortgage is outstanding all five years
    coverage = mezz.coverage_by_year
    assert coverage[0] is not None and coverage[1] is not None
    assert all(math.isclose(value, 800_000.0 / (300_000.0 + 12 * EARLY_PMT), rel_tol=1e-9) for value in coverage[:2])
    assert coverage[2:] == (None, None, None)
    assert (mezz.headline_coverage, mezz.minimum_coverage) == (coverage[0], min(coverage[0], coverage[1]))
    # Senior-only coverage exists in years 3-5, and is deliberately never
    # reported as coverage through the extinguished mezzanine loan.
    senior_only = engine_returns.calculate_dscr_by_year(
        noi_by_year=results.noi_by_year, annual_debt_service=results.annual_debt_service
    )
    assert senior_only[2:] == (800_000.0 / 300_000.0,) * 3


# =============================================================================
# 5. Coverage and debt yield through a position
# =============================================================================


@pytest.fixture(scope="module")
def stack() -> dict[str, Any]:
    """An all-cash Unit (no acquisition loan) with an authored senior loan, a
    mezzanine loan and a preferred position -- each with a balloon or a
    redemption at the exit, two with closing fees, and one accruing."""

    terms, results = round_unit(ltv=0.0)
    senior = claim_position(
        "senior", position_class=PositionClass.SENIOR_DEBT, priority=1, resolution=CEC, amount=5_000_000.0,
        terms=cash_pay_debt(rate=0.06, io_period=5, maturity_month=60, fees=(fee("senior-fee", amount=50_000.0),)),
    )
    mezz = claim_position(
        "mezz", position_class=PositionClass.MEZZANINE_DEBT, priority=2, resolution=CEC, amount=1_500_000.0,
        terms=cash_pay_debt(rate=0.12, amortization=25, io_period=5, maturity_month=60, fees=(fee("mezz-fee", amount=15_000.0),)),
    )
    pref = claim_position(
        "pref", position_class=PositionClass.PREFERRED_EQUITY, priority=3, resolution=CEC, amount=1_000_000.0,
        terms=preferred(preferred_rate=0.12, current_pay_rate=0.08, convention=AccrualConvention.SIMPLE),
    )
    result = execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(pref, mezz, senior)
    )
    return {"results": results, "positions": {position.position_id: position for position in result.positions}}


def test_coverage_through_each_position_is_noi_over_cumulative_current_cash_service(stack: dict[str, Any]) -> None:
    """Hand: NOI $800,000; the senior pays $300,000 a year, the mezz $180,000
    and the preferred $80,000 current pay (its 4% accrual is not cash)."""

    positions = stack["positions"]
    for position_id, service in (("senior", 300_000.0), ("mezz", 480_000.0), ("pref", 560_000.0)):
        coverage = positions[position_id].coverage_by_year
        assert all(math.isclose(value, 800_000.0 / service, rel_tol=1e-12) for value in coverage), position_id
        assert positions[position_id].headline_coverage == coverage[0]
        assert positions[position_id].minimum_coverage == min(coverage)


def test_coverage_excludes_balloons_redemption_accrual_and_fees(stack: dict[str, Any]) -> None:
    """Year 5 carries the $5,000,000 and $1,500,000 balloons, the preferred
    redemption and its accrued return; year 1 carries the closing fees' year.
    Coverage in both is the recurring figure alone."""

    positions = stack["positions"]
    for position in positions.values():
        assert position.coverage_by_year[4] == position.coverage_by_year[0]
    assert positions["pref"].annual_claims[-1].claim_due > 1_000_000.0  # the redemption is claimed in year 5
    assert not math.isclose(positions["pref"].coverage_by_year[0], 800_000.0 / 600_000.0, rel_tol=1e-9)


def test_debt_yield_and_attachment_through_each_position(stack: dict[str, Any]) -> None:
    positions = stack["positions"]
    for position_id, attachment, detachment in (
        ("senior", 0.0, 5_000_000.0), ("mezz", 5_000_000.0, 6_500_000.0), ("pref", 6_500_000.0, 7_500_000.0),
    ):
        position = positions[position_id]
        assert (position.attachment_basis, position.detachment_basis, position.last_dollar_basis) == (
            attachment, detachment, detachment,
        ), position_id
        assert position.debt_yield_through == 800_000.0 / detachment, position_id
        assert position.detachment_ltv == detachment / 10_000_000.0
