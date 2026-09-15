"""Phase 7 Gate P7.8 -- preferred equity: current pay, contractual accrual,
redemption, and a current-pay shortfall that is never accrued.

``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md`` Section 7, under
``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 12.3
(FR-4: accrual only by contract, under the convention it names; Q21). Every
expected figure is hand arithmetic over the ratified formulas, prepared here
without the executor:

- current pay ``= current_pay_rate x P``, a year-end cash claim;
- ``SIMPLE`` accrual ``= P x (preferred_rate - current_pay_rate)``;
- ``ANNUAL_COMPOUND`` accrual ``= (P + beginning_accrued) x (preferred_rate - current_pay_rate)``;
- redemption ``= P + accrued``, at a hold-year end or the exit.
"""

from __future__ import annotations

from typing import Any

import pytest

from _p7_7_fixtures import bits  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    CEC,
    UNIT,
    UNRESOLVED,
    all_close,
    claim_position,
    close,
    npv,
    preferred,
    round_unit,
    structure,
)
from anchor.business_plan import BusinessPlan, CapitalItemCategory, CapitalPlanItem
from anchor.capital_structure import (
    AccrualConvention,
    CapitalPosition,
    CapitalStructureExecutionError,
    CapitalStructureStatus,
    ExecutionIssueCode,
    FundingRequirementStatus,
    PositionCashFlowKind,
    PositionClass,
    PositionResultStatus,
    ShortfallResolution,
    execute_unit_capital_structure,
    validate_capital_structure,
)
from anchor.capital_structure.preferred import modeled_redemption_month
from anchor.engine.contracts import IrrStatus

Kind = PositionCashFlowKind
SIMPLE = AccrualConvention.SIMPLE
COMPOUND = AccrualConvention.ANNUAL_COMPOUND
PRINCIPAL = 1_000_000.0
#: The ratified split: preferred rate 12%, current pay 8%.
ACCRUAL_RATE = 0.12 - 0.08


def _pref(
    convention: AccrualConvention | None,
    *,
    redemption_month: int = 48,
    preferred_rate: float = 0.12,
    current_pay_rate: float = 0.08,
    resolution: ShortfallResolution = CEC,
) -> CapitalPosition:
    return claim_position(
        "pref",
        position_class=PositionClass.PREFERRED_EQUITY,
        priority=2,
        resolution=resolution,
        amount=PRINCIPAL,
        terms=preferred(
            preferred_rate=preferred_rate,
            current_pay_rate=current_pay_rate,
            convention=convention,
            redemption_month=redemption_month,
        ),
    )


def _run(position: CapitalPosition, *, business_plan: BusinessPlan | None = None) -> tuple[Any, Any]:
    terms, results = round_unit(business_plan)
    return results, execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(position)
    )


def _hand_accrual(convention: AccrualConvention, years: int) -> list[tuple[float, float, float]]:
    """``(beginning, accrual, ending)`` of each year, by the ratified formula."""

    rows: list[tuple[float, float, float]] = []
    accrued = 0.0
    for _ in range(years):
        base = PRINCIPAL if convention is SIMPLE else PRINCIPAL + accrued
        accrual = base * ACCRUAL_RATE
        rows.append((accrued, accrual, accrued + accrual))
        accrued = accrued + accrual
    return rows


# =============================================================================
# 1. SIMPLE: redeemed at the end of year 4, before the exit
# =============================================================================


@pytest.fixture(scope="module")
def simple() -> dict[str, Any]:
    results, result = _run(_pref(SIMPLE))
    return {"results": results, "result": result, "pref": result.positions[0]}


def test_simple_accrual_golden_schedule(simple: dict[str, Any]) -> None:
    schedule = simple["pref"].preferred_schedule
    assert bits([schedule.accrual_rate]) == bits([ACCRUAL_RATE])
    assert (schedule.accrual_convention, schedule.redemption_month, schedule.modeled_payoff_month) == (SIMPLE, 48, 48)
    hand = _hand_accrual(SIMPLE, 4)
    for year, (row, (beginning, accrual, ending)) in enumerate(zip(schedule.years, hand, strict=True), start=1):
        assert (row.hold_year, row.unreturned_principal, row.current_pay) == (year, PRINCIPAL, 80_000.0)
        assert close(row.beginning_accrued, beginning, 1e-9) and close(row.accrual, accrual, 1e-9)
        assert close(row.ending_accrued, ending, 1e-9)
        assert close(row.accrual, 40_000.0, 1e-6)  # never compounds
    assert close(schedule.balance_at_redemption, 1_160_000.0, 1e-6)
    assert simple["pref"].balance_at_maturity_or_exit == schedule.balance_at_redemption


def test_simple_accrual_golden_events_and_cash_flows(simple: dict[str, Any]) -> None:
    pref = simple["pref"]
    receipts = [(e.model_month, e.sequence, e.kind) for e in pref.cash_flow_events if e.model_month > 0]
    assert receipts == [
        (12, 1, Kind.PREFERRED_CURRENT_PAY), (24, 1, Kind.PREFERRED_CURRENT_PAY), (36, 1, Kind.PREFERRED_CURRENT_PAY),
        (48, 1, Kind.PREFERRED_CURRENT_PAY), (48, 2, Kind.PREFERRED_REDEMPTION),
    ]
    assert all_close(pref.annual_cash_flows, (-PRINCIPAL, 80_000.0, 80_000.0, 80_000.0, 1_240_000.0, 0.0))
    assert pref.annual_cash_flows[5] == 0.0  # nothing after the redemption


def test_simple_accrual_golden_settlement_and_common_equity(simple: dict[str, Any]) -> None:
    """Years 1-3 are paid from the $500,000 of post-debt cash; year 4's current
    pay plus redemption is not, and the shortfall is one resolved
    requirement."""

    pref, common, results = simple["pref"], simple["result"].common_equity, simple["results"]
    assert [claim.hold_year for claim in pref.annual_claims] == [1, 2, 3, 4]
    assert all(claim.settlement.claim.cash_available == 500_000.0 for claim in pref.annual_claims)
    (requirement,) = pref.funding_requirements
    assert requirement.requirement_id == "pref/hold_year/4" and requirement.status is FundingRequirementStatus.RESOLVED
    assert close(requirement.amount, 1_240_000.0 - 500_000.0)
    flows = common.cash_flows
    assert flows[0] == -3_000_000.0 and flows[1:4] == (420_000.0,) * 3
    assert close(flows[4], 500_000.0 - 1_240_000.0) and bits([flows[5]]) == bits([results.levered_cash_flows[5]])


def test_simple_accrual_golden_returns_and_structure(simple: dict[str, Any]) -> None:
    pref = simple["pref"]
    assert pref.status is PositionResultStatus.COMPLETE and pref.irr_status is IrrStatus.DEFINED
    assert close(npv(pref.irr, pref.annual_cash_flows), 0.0, 1e-3)
    assert close(pref.moic, 1.48, 1e-9) and close(pref.profit, 480_000.0)
    assert pref.coverage_by_year[:4] == (800_000.0 / 380_000.0,) * 4 and pref.coverage_by_year[4] is None
    # The accrued return never enters the closing basis.
    assert (pref.attachment_basis, pref.detachment_basis) == (6_000_000.0, 7_000_000.0)


# =============================================================================
# 2. ANNUAL_COMPOUND: the same position
# =============================================================================


def test_annual_compound_accrual_golden() -> None:
    _, result = _run(_pref(COMPOUND))
    (pref,) = result.positions
    schedule = pref.preferred_schedule
    hand = _hand_accrual(COMPOUND, 4)
    for row, (beginning, accrual, ending) in zip(schedule.years, hand, strict=True):
        assert close(row.beginning_accrued, beginning, 1e-9) and close(row.accrual, accrual, 1e-9)
        assert close(row.ending_accrued, ending, 1e-9)
    closed_form = PRINCIPAL * ((1 + ACCRUAL_RATE) ** 4 - 1)
    assert close(schedule.years[-1].ending_accrued, closed_form, 1e-6)
    assert close(schedule.balance_at_redemption, 1_169_858.56, 1e-6)
    assert close(pref.annual_claims[-1].claim_due, 80_000.0 + 1_169_858.56, 1e-6)
    assert close(pref.moic, (4 * 80_000.0 + 1_169_858.56) / PRINCIPAL, 1e-9)
    # Compounding differs from simple accrual; each convention is its own.
    assert schedule.years[1].accrual > schedule.years[0].accrual


# =============================================================================
# 3. No accrual
# =============================================================================


def test_preferred_without_accrual_pays_current_and_returns_principal() -> None:
    results, result = _run(_pref(None, preferred_rate=0.10, current_pay_rate=0.10, redemption_month=60))
    (pref,) = result.positions
    schedule = pref.preferred_schedule
    assert (schedule.accrual_rate, schedule.accrual_convention) == (0.0, None)
    assert all(row.accrual == 0.0 and row.ending_accrued == 0.0 for row in schedule.years)
    assert schedule.balance_at_redemption == PRINCIPAL
    assert pref.annual_cash_flows == (-PRINCIPAL, 100_000.0, 100_000.0, 100_000.0, 100_000.0, 1_100_000.0)
    assert close(pref.irr, 0.10, 1e-9)
    assert (pref.moic, pref.profit) == (1.5, 500_000.0)
    assert result.common_equity.cash_flows[5] == results.levered_cash_flows[5] - 1_100_000.0


def test_a_rate_difference_without_permitted_accrual_is_refused_never_waived() -> None:
    unpermitted = _pref(None, preferred_rate=0.12, current_pay_rate=0.08)
    assert validate_capital_structure(structure(unpermitted), member_unit_ids={UNIT}, acquisition_loan_unit_ids={UNIT}) == ()
    with pytest.raises(CapitalStructureExecutionError) as refused:
        _run(unpermitted)
    assert [issue.code for issue in refused.value.issues] == [ExecutionIssueCode.UNPERMITTED_PREFERRED_ACCRUAL]


# =============================================================================
# 4. A current-pay shortfall is a Funding Requirement, never an accrual
# =============================================================================

#: A $2,000,000 capital item in month 18 turns year 2's post-debt cash negative.
_ROOF = BusinessPlan(
    capital_items=(
        CapitalPlanItem(
            item_id="cap-roof", description="Roof", category=CapitalItemCategory.BUILDING_SYSTEMS, month=18,
            amount=2_000_000.0,
        ),
    )
)


@pytest.mark.parametrize("resolution", [CEC, UNRESOLVED])
def test_a_current_pay_shortfall_is_a_funding_requirement_never_an_accrual(resolution: ShortfallResolution) -> None:
    _, clean = _run(_pref(SIMPLE, redemption_month=60))
    results, stressed = _run(_pref(SIMPLE, redemption_month=60, resolution=resolution), business_plan=_ROOF)
    assert results.levered_cash_flows[2] == 500_000.0 - 2_000_000.0

    (pref,), (clean_pref,) = stressed.positions, clean.positions
    # The accrual is contractual: the shortfall changes neither it nor the balance.
    assert pref.preferred_schedule == clean_pref.preferred_schedule
    assert pref.balance_at_maturity_or_exit == clean_pref.balance_at_maturity_or_exit
    assert bits([pref.annual_claims[-1].claim_due]) == bits([clean_pref.annual_claims[-1].claim_due])

    year_2 = pref.annual_claims[1]
    requirement = year_2.settlement.funding_requirement
    assert year_2.settlement.claim.cash_available == 0.0
    assert requirement is not None and requirement.amount == 80_000.0
    if resolution is CEC:
        assert requirement.status is FundingRequirementStatus.RESOLVED and requirement.equity_contribution == 80_000.0
        assert pref.status is PositionResultStatus.COMPLETE
        assert bits(pref.annual_cash_flows) == bits(clean_pref.annual_cash_flows)
        assert stressed.common_equity.cash_flows[2] == results.levered_cash_flows[2] - 80_000.0
    else:
        assert requirement.status is FundingRequirementStatus.UNRESOLVED and requirement.unpaid_claim_amount == 80_000.0
        assert pref.status is PositionResultStatus.UNRESOLVED_FUNDING
        assert (pref.irr, pref.moic, pref.annual_cash_flows) == (None, None, None)
        assert pref.blocking_requirement_ids == ("pref/hold_year/2",)
        # Each later year is settled on its own; the unpaid amount is not carried.
        assert [claim.settlement.funding_requirement for claim in pref.annual_claims[2:]] == [None, None, None]
        assert stressed.common_equity.cash_flows is None
        assert stressed.status is CapitalStructureStatus.UNRESOLVED_FUNDING


# =============================================================================
# 5. Redemption timing
# =============================================================================


@pytest.mark.parametrize(("stated", "modeled"), [(12, 12), (24, 24), (48, 48), (60, 60), (61, 60), (96, 60)])
def test_a_redemption_is_at_a_hold_year_end_or_at_the_exit(stated: int, modeled: int) -> None:
    assert modeled_redemption_month(redemption_month=stated, hold_period=5) == modeled
    _, result = _run(_pref(SIMPLE, redemption_month=stated))
    (pref,) = result.positions
    redeemed = modeled // 12
    assert pref.modeled_payoff_month == modeled
    assert max(event.model_month for event in pref.cash_flow_events) == modeled
    assert [claim.hold_year for claim in pref.annual_claims] == list(range(1, redeemed + 1))
    assert len(pref.preferred_schedule.years) == redeemed
    assert pref.annual_cash_flows[redeemed + 1 :] == (0.0,) * (5 - redeemed)


@pytest.mark.parametrize("stated", [1, 11, 13, 30, 59])
def test_a_partial_year_redemption_before_the_exit_is_refused(stated: int) -> None:
    assert modeled_redemption_month(redemption_month=stated, hold_period=5) is None
    with pytest.raises(CapitalStructureExecutionError) as refused:
        _run(_pref(SIMPLE, redemption_month=stated))
    assert [issue.code for issue in refused.value.issues] == [ExecutionIssueCode.UNSUPPORTED_REDEMPTION_TIMING]
