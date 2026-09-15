"""Phase 7 Gate P7.7 -- claim settlement, Funding Requirements and the
unresolved-funding rule.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3 (P-9,
P-14), 12.3 (CS-7, CS-8) and 21.3, and the P7.7 decisions recorded in
``docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md``: exactly two
resolutions, no default, and an unresolved requirement makes the downstream
Common Equity Cash Flow unavailable rather than fabricated.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

import pytest

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from _p7_7_fixtures import INVESTMENT, analyze_unit, analyze_visible_investment, bits, heavy_plan, unit_scope  # type: ignore[import-not-found]
from anchor.capital_structure import (
    CapitalStructureError,
    CapitalStructureStatus,
    CommonEquityUnavailableReason,
    ContractualClaim,
    FundingRequirementStatus,
    HoldYearPeriod,
    ModelMonthPeriod,
    ShortfallResolution,
    TimingBasis,
    analyze_investment_capital_structure,
    analyze_unit_capital_structure,
    common_equity_outcome,
    settle_claim,
)

CEC = ShortfallResolution.COMMON_EQUITY_CONTRIBUTION
UNRESOLVED = ShortfallResolution.UNRESOLVED


def _claim(due: float, available: float, resolution: Any = CEC, *, period: Any = None) -> ContractualClaim:
    return ContractualClaim(
        position_id="mezz-1",
        scope=unit_scope("u1"),
        period=HoldYearPeriod(hold_year=2) if period is None else period,
        claim_due=due,
        cash_available=available,
        shortfall_resolution=resolution,
    )


# =============================================================================
# 1-3. The pure settlement
# =============================================================================


@pytest.mark.parametrize("resolution", list(ShortfallResolution))
@pytest.mark.parametrize(("due", "available"), [(100.0, 150.0), (150.0, 150.0), (0.0, 0.0), (0.0, 10.0)])
def test_a_covered_claim_has_no_funding_requirement(resolution: ShortfallResolution, due: float, available: float) -> None:
    settlement = settle_claim(_claim(due, available, resolution))
    assert settlement.funding_requirement is None
    assert (settlement.claim_paid, settlement.claim_paid_from_cash) == (due, due)
    assert (settlement.equity_contribution, settlement.unpaid_claim_amount) == (0.0, 0.0)


def test_a_shortfall_with_a_common_equity_contribution_is_resolved_and_paid_in_full() -> None:
    settlement = settle_claim(_claim(150.0, 100.0, CEC))
    requirement = settlement.funding_requirement
    assert requirement is not None
    assert requirement.status is FundingRequirementStatus.RESOLVED
    assert requirement.resolution is CEC
    assert (requirement.claim_amount, requirement.cash_available, requirement.claim_paid_from_cash) == (150.0, 100.0, 100.0)
    assert (requirement.amount, requirement.equity_contribution, requirement.unpaid_claim_amount) == (50.0, 50.0, 0.0)
    assert (settlement.claim_paid, settlement.equity_contribution, settlement.unpaid_claim_amount) == (150.0, 50.0, 0.0)
    assert requirement.requirement_id == "mezz-1/hold_year/2"
    assert (requirement.position_id, requirement.scope, requirement.period) == ("mezz-1", unit_scope("u1"), HoldYearPeriod(hold_year=2))
    assert requirement.explanation == (
        "mezz-1 (Unit u1) was owed 150.00 in hold year 2, but only 100.00 of eligible cash was available to it. "
        "The 50.00 shortfall is met by an additional common-equity contribution, as this position's terms state, "
        "so the claim is paid in full."
    )


def test_an_unresolved_shortfall_pays_only_the_cash_and_invents_no_equity() -> None:
    settlement = settle_claim(_claim(150.0, 100.0, UNRESOLVED))
    requirement = settlement.funding_requirement
    assert requirement is not None
    assert requirement.status is FundingRequirementStatus.UNRESOLVED
    assert (requirement.amount, requirement.equity_contribution, requirement.unpaid_claim_amount) == (50.0, 0.0, 50.0)
    assert (settlement.claim_paid, settlement.claim_paid_from_cash, settlement.equity_contribution) == (100.0, 100.0, 0.0)
    assert "unresolved" in requirement.explanation and "stays unpaid" in requirement.explanation


def test_a_model_month_claim_is_reported_at_its_exact_month() -> None:
    requirement = settle_claim(_claim(80.0, 0.0, UNRESOLVED, period=ModelMonthPeriod(model_month=19))).funding_requirement
    assert requirement is not None
    assert requirement.period.basis is TimingBasis.MODEL_MONTH
    assert requirement.requirement_id == "mezz-1/model_month/19"
    assert "model month 19" in requirement.explanation
    investment = settle_claim(dataclasses.replace(_claim(80.0, 0.0, UNRESOLVED), scope=INVESTMENT)).funding_requirement
    assert investment is not None and "(the Investment)" in investment.explanation


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"shortfall_resolution": None}, "no shortfall resolution"),
        ({"shortfall_resolution": "common_equity_contribution"}, "no shortfall resolution"),
        ({"cash_available": -1.0}, "negative"),
        ({"claim_due": -1.0}, "negative"),
        ({"claim_due": math.nan}, "finite"),
        ({"cash_available": math.inf}, "finite"),
        ({"claim_due": True}, "finite"),
        ({"period": HoldYearPeriod(hold_year=0)}, "valid period"),
        ({"period": ModelMonthPeriod(model_month=True)}, "valid period"),
        ({"period": 2}, "valid period"),
        ({"position_id": " "}, "names its position"),
    ],
)
def test_settlement_refuses_what_it_cannot_settle_and_assumes_no_cure(change: dict[str, Any], match: str) -> None:
    with pytest.raises(CapitalStructureError, match=match):
        settle_claim(dataclasses.replace(_claim(150.0, 100.0), **change))


# =============================================================================
# 4-5. The legacy acquisition loan's Funding Requirements
# =============================================================================


def test_a_legacy_debt_service_shortfall_is_a_resolved_unit_requirement() -> None:
    """Year 2 of the Quick plan: pre-debt cash is positive but below debt
    service. The shortfall is exactly the D6 Net Additional Equity Requirement
    of that year, and the Common Equity Cash Flow is unchanged."""

    terms, results = analyze_unit("quick", business_plan=fx.business_plan())
    outcome = analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results)
    (requirement,) = outcome.funding_requirements

    assert requirement.period == HoldYearPeriod(hold_year=2)
    assert requirement.scope == unit_scope("u1")
    assert requirement.position_id == "legacy-acquisition-loan:u1"
    assert requirement.resolution is CEC and requirement.status is FundingRequirementStatus.RESOLVED
    assert bits([requirement.claim_amount]) == bits([results.annual_debt_service[1]])
    assert bits([requirement.cash_available]) == bits([results.unlevered_cash_flows[2]])
    assert 0.0 < requirement.cash_available < requirement.claim_amount
    assert bits([requirement.amount]) == bits([results.annual_debt_service[1] - results.unlevered_cash_flows[2]])
    assert requirement.equity_contribution == requirement.amount and requirement.unpaid_claim_amount == 0.0
    assert math.isclose(requirement.amount, results.net_additional_equity_requirement_by_year[1], abs_tol=1e-6)
    assert outcome.status is CapitalStructureStatus.COMPLETE
    assert outcome.common_equity_cash_flows is results.levered_cash_flows


def test_a_funding_requirement_is_never_the_whole_net_additional_equity_requirement() -> None:
    """A capital-driven negative pre-debt year: no eligible cash, so the loan's
    requirement is exactly its debt service. The negative Property / Business
    Plan cash stays common equity's -- inside the NAER, not the debt claim."""

    terms, results = analyze_unit("quick", business_plan=heavy_plan(14, 3_000_000.0))
    assert results.unlevered_cash_flows[2] < 0.0
    outcome = analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results)
    year_2 = next(r for r in outcome.funding_requirements if r.period == HoldYearPeriod(hold_year=2))

    assert year_2.cash_available == 0.0 and bits([year_2.cash_available]) == bits([0.0])
    assert bits([year_2.amount]) == bits([results.annual_debt_service[1]])
    naer = results.net_additional_equity_requirement_by_year[1]
    assert year_2.amount < naer
    assert math.isclose(naer - year_2.amount, -results.unlevered_cash_flows[2], abs_tol=1e-6)


def test_the_exit_year_claim_is_debt_service_plus_the_balance_against_pre_debt_sale_cash() -> None:
    terms, results = analyze_unit("quick", exit_cap_rate=0.30)
    hold = terms.hold_period
    outcome = analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results)
    final = next(r for r in outcome.funding_requirements if r.period == HoldYearPeriod(hold_year=hold))

    claim = results.annual_debt_service[hold - 1] + results.remaining_loan_balance
    assert bits([final.claim_amount]) == bits([claim])
    assert bits([final.cash_available]) == bits([results.unlevered_cash_flows[hold]])
    assert 0.0 < final.cash_available < final.claim_amount
    assert bits([final.amount]) == bits([claim - results.unlevered_cash_flows[hold]])
    assert results.levered_cash_flows[hold] < 0.0
    assert math.isclose(final.amount, results.net_additional_equity_requirement_by_year[hold - 1], abs_tol=1e-6)
    assert outcome.common_equity_cash_flows is results.levered_cash_flows


def test_requirements_are_reported_in_hold_year_order_with_honest_annual_timing() -> None:
    terms, results = analyze_unit("lease_level", business_plan=heavy_plan(30, 6_000_000.0), io_period=2)
    requirements = analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results).funding_requirements
    assert requirements
    assert all(r.period.basis is TimingBasis.HOLD_YEAR for r in requirements)
    years = [r.period.hold_year for r in requirements if isinstance(r.period, HoldYearPeriod)]
    assert years == sorted(years)


# =============================================================================
# 6. Multi-Unit scope isolation
# =============================================================================


def test_a_unit_shortfall_is_never_netted_against_another_units_surplus(tmp_path: Path) -> None:
    db = tmp_path / "isolation.db"
    short = quick_deal(db, business_plan=heavy_plan(14, 1_000_000.0), name="Short Unit")
    surplus = quick_deal(db, ltv=0.0, current_noi=2_400_000.0, purchase_price=30_000_000.0, name="Surplus Unit")
    visible = create_investment(db, short, surplus)
    analysis, units = analyze_visible_investment(visible.id, db)
    consolidated = analysis.consolidated_results
    short_results = next(unit.results for unit in units if unit.unit_id == short.id)

    # The premise: the short Unit has no pre-debt cash in Year 2, and the
    # Investment's netted pre-debt cash would cover every Year-2 claim.
    assert short_results.unlevered_cash_flows[2] < 0.0
    assert consolidated.unlevered_cash_flows[2] > consolidated.annual_debt_service[1]

    outcome = analyze_investment_capital_structure(units=units, consolidated=consolidated)
    year_2 = [r for r in outcome.funding_requirements if r.period == HoldYearPeriod(hold_year=2)]
    assert [r.scope.unit_id for r in year_2] == [short.id]
    (requirement,) = year_2
    assert requirement.cash_available == 0.0
    assert bits([requirement.amount]) == bits([short_results.annual_debt_service[1]])
    assert outcome.status is CapitalStructureStatus.COMPLETE
    assert outcome.common_equity_cash_flows is consolidated.levered_cash_flows


# =============================================================================
# The unresolved-funding rule
# =============================================================================


def test_unresolved_downstream_oracle_common_equity_is_unavailable_not_fabricated() -> None:
    terms, results = analyze_unit("quick", business_plan=fx.business_plan())
    before = dataclasses.asdict(results)
    legacy = analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results).funding_requirements
    unresolved = settle_claim(_claim(500_000.0, 200_000.0, UNRESOLVED, period=ModelMonthPeriod(model_month=18))).funding_requirement
    assert unresolved is not None and unresolved.status is FundingRequirementStatus.UNRESOLVED

    outcome = common_equity_outcome(funding_requirements=(*legacy, unresolved), residual_cash_flows=results.levered_cash_flows)

    assert outcome.status is CapitalStructureStatus.UNRESOLVED_FUNDING
    assert outcome.common_equity_cash_flows is None
    assert outcome.unavailable_reason is CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
    assert outcome.unresolved_requirement_ids == ("mezz-1/model_month/18",)
    assert outcome.unavailable_message is not None and "mezz-1/model_month/18" in outcome.unavailable_message
    assert "unaffected" in outcome.unavailable_message
    assert dataclasses.asdict(results) == before


def test_resolved_requirements_leave_the_residual_complete_and_untouched() -> None:
    terms, results = analyze_unit("quick", business_plan=fx.business_plan())
    legacy = analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results).funding_requirements
    assert legacy and all(r.status is FundingRequirementStatus.RESOLVED for r in legacy)
    outcome = common_equity_outcome(funding_requirements=legacy, residual_cash_flows=results.levered_cash_flows)
    assert outcome.status is CapitalStructureStatus.COMPLETE
    assert outcome.common_equity_cash_flows is results.levered_cash_flows
    assert (outcome.unavailable_reason, outcome.unavailable_message, outcome.unresolved_requirement_ids) == (None, None, ())


def test_every_unresolved_requirement_is_named_in_order() -> None:
    first = settle_claim(_claim(10.0, 0.0, UNRESOLVED, period=ModelMonthPeriod(model_month=3))).funding_requirement
    second = settle_claim(_claim(10.0, 0.0, UNRESOLVED, period=ModelMonthPeriod(model_month=40))).funding_requirement
    outcome = common_equity_outcome(funding_requirements=(first, second), residual_cash_flows=(-1.0, 2.0))  # type: ignore[arg-type]
    assert outcome.unresolved_requirement_ids == ("mezz-1/model_month/3", "mezz-1/model_month/40")
    assert outcome.common_equity_cash_flows is None
