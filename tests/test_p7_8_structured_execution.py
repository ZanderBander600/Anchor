"""Phase 7 Gate P7.8 -- the executor: neutrality, structural subordination, the
visible-Investment goldens, unresolved propagation, the Common Equity returns
and attachment / detachment.

``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md`` Sections 9-13, under
``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 12.3
(CS-4 to CS-7), 12.4 (the parity oracle), 12.6 and 14. Every expected figure is
the completed project result (the upstream authority) or hand arithmetic --
never the executor.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

import pytest

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import cost, detailed_deal, investment_plan, lease_level_deal, quick_deal  # type: ignore[import-not-found]
from _p7_7_fixtures import INVESTMENT, PARITY_CASES, bits, fee, funding, parity_case, unit_scope  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    CEC,
    UNIT,
    UNRESOLVED,
    all_close,
    cash_pay_debt,
    claim_position,
    close,
    common_marker,
    golden_mezz,
    npv,
    preferred,
    round_deal,
    round_unit,
    structure,
    visible,
)
from anchor.capital_structure import (
    AccrualConvention,
    CapitalStructure,
    CapitalStructureExecutionError,
    CapitalStructureStatus,
    CommonEquityUnavailableReason,
    ExecutionIssueCode,
    FundingRequirementStatus,
    PctOfPrice,
    PositionClass,
    PositionResultStatus,
    PositionUnavailableReason,
    PriceBasis,
    PriceBasisKind,
    ScopeKind,
    analyze_investment_capital_structure,
    analyze_unit_capital_structure,
    execute_investment_capital_structure,
    execute_unit_capital_structure,
)
from anchor.engine.contracts import IrrStatus
from anchor.engine.returns import calculate_equity_multiple, calculate_project_return_totals, evaluate_irr

MEZZ = PositionClass.MEZZANINE_DEBT
PREF = PositionClass.PREFERRED_EQUITY
SENIOR = PositionClass.SENIOR_DEBT


def _neutral(kind: str, scope: Any) -> CapitalStructure | None:
    return {"none": None, "empty": structure(), "marker_only": structure(common_marker(scope=scope, priority=9))}[kind]


def _snapshot(consolidated: Any, units: Any) -> tuple[Any, ...]:
    return (dataclasses.asdict(consolidated), [dataclasses.asdict(unit.results) for unit in units])


# =============================================================================
# 1. The neutral oracle: no authored position, bit for bit
# =============================================================================


@pytest.mark.parametrize("kind", ["none", "empty", "marker_only"])
@pytest.mark.parametrize("case", sorted(PARITY_CASES))
def test_neutral_unit_parity_bit_for_bit(case: str, kind: str) -> None:
    """Quick, Detailed and Lease-Level, with leverage, fees, interest-only,
    Business Plans and negative owner years: the Common Equity Cash Flow *is*
    today's levered cash flow, and its returns are today's project returns."""

    terms, results = parity_case(case)
    result = execute_unit_capital_structure(
        unit_id="unit-a", terms=terms, results=results, capital_structure=_neutral(kind, unit_scope("unit-a"))
    )
    common = result.common_equity
    assert common.cash_flows is results.levered_cash_flows
    assert common.cash_flows is not None and bits(common.cash_flows) == bits(results.levered_cash_flows)
    assert (result.positions, result.status) == ((), CapitalStructureStatus.COMPLETE)
    foundation = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results)
    assert result.funding_requirements == foundation.funding_requirements
    assert result.legacy_acquisition_loans == (foundation.legacy_acquisition_loan,)
    assert (common.irr, common.irr_status) == (results.levered_irr, results.levered_irr_status)
    assert (common.equity_multiple, common.total_equity_invested, common.total_cash_returned, common.total_profit) == (
        results.equity_multiple, results.total_equity_invested, results.total_cash_returned, results.total_profit,
    )
    assert common.position_id == ("common" if kind == "marker_only" else None)


@pytest.fixture(scope="module")
def mixed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The P7.7 visible Investment: Quick, Detailed, Lease-Level and all-cash
    Units, Unit and Investment Business Plans, and a transaction cost."""

    db = tmp_path_factory.mktemp("p7_8_mixed") / "mixed.db"
    quick = quick_deal(db, business_plan=fx.business_plan())
    detailed = detailed_deal(db)
    lease = lease_level_deal(db, business_plan=fx.business_plan())
    all_cash = quick_deal(db, ltv=0.0, name="All-cash Quick")
    analysis, units = visible(
        db, lease, all_cash, quick, detailed, business_plan=investment_plan(), costs=(cost("tc-1", 150_000.0),)
    )
    return {"consolidated": analysis.consolidated_results, "units": units}


@pytest.mark.parametrize("kind", ["none", "empty", "marker_only"])
def test_neutral_visible_investment_parity_bit_for_bit(mixed: dict[str, Any], kind: str) -> None:
    consolidated = mixed["consolidated"]
    before = _snapshot(consolidated, mixed["units"])
    result = execute_investment_capital_structure(
        units=mixed["units"], consolidated=consolidated, capital_structure=_neutral(kind, INVESTMENT)
    )
    common = result.common_equity
    assert common.cash_flows is consolidated.levered_cash_flows
    assert (result.analysis_scope, result.unit_ids, result.positions) == (ScopeKind.INVESTMENT, consolidated.unit_ids, ())
    foundation = analyze_investment_capital_structure(units=mixed["units"], consolidated=consolidated)
    assert result.funding_requirements == foundation.funding_requirements
    assert result.legacy_acquisition_loans == foundation.legacy_acquisition_loans
    assert (common.irr, common.irr_status) == (consolidated.levered_irr, consolidated.levered_irr_status)
    assert (common.equity_multiple, common.total_equity_invested, common.total_cash_returned, common.total_profit) == (
        consolidated.equity_multiple, consolidated.total_equity_invested, consolidated.total_cash_returned,
        consolidated.total_profit,
    )
    assert _snapshot(consolidated, mixed["units"]) == before


# =============================================================================
# 2. The Investment-scoped senior debt golden (all-cash Units, CS-5)
# =============================================================================


@pytest.fixture(scope="module")
def all_cash(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Two all-cash Units: $10,000,000 with $800,000 NOI, and $8,000,000 with
    $500,000 NOI at a 6.25% exit cap. Transaction price $18,000,000."""

    db = tmp_path_factory.mktemp("p7_8_all_cash") / "all_cash.db"
    a = round_deal(db, name="Unit A", ltv=0.0)
    b = round_deal(db, name="Unit B", purchase_price=8_000_000.0, current_noi=500_000.0, exit_cap_rate=0.0625, ltv=0.0)
    analysis, units = visible(db, a, b)
    return {"consolidated": analysis.consolidated_results, "units": units}


def _holdco_senior() -> Any:
    return claim_position(
        "holdco-senior",
        position_class=SENIOR,
        priority=1,
        scope=INVESTMENT,
        resolution=CEC,
        terms=cash_pay_debt(rate=0.06, io_period=5, maturity_month=60, fees=(fee("holdco-senior-fee", amount=90_000.0),)),
        funding_events=(funding("holdco-senior-funding", rule=PctOfPrice(pct=0.5)),),
    )


def test_investment_senior_debt_golden(all_cash: dict[str, Any]) -> None:
    """Hand: 50% of the $18,000,000 transaction price is $9,000,000 at 6%
    interest-only ($540,000 a year) with a $90,000 fee. Consolidated NOI is
    $1,300,000 and the all-cash Equity Cash Flow is ``-18,000,000; 1,300,000 x 4;
    19,300,000``."""

    consolidated, units = all_cash["consolidated"], all_cash["units"]
    assert consolidated.loan_amount == 0.0 and consolidated.transaction_price == 18_000_000.0
    assert consolidated.noi_by_year == (1_300_000.0,) * 5
    assert consolidated.levered_cash_flows == (-18_000_000.0, 1_300_000.0, 1_300_000.0, 1_300_000.0, 1_300_000.0, 19_300_000.0)
    before = _snapshot(consolidated, units)

    result = execute_investment_capital_structure(units=units, consolidated=consolidated, capital_structure=structure(_holdco_senior()))
    (senior,) = result.positions
    assert senior.funded_amount == 9_000_000.0
    assert senior.funding[0].price_basis == PriceBasis(kind=PriceBasisKind.INVESTMENT_TRANSACTION_PRICE, amount=18_000_000.0)
    assert all_close(senior.annual_cash_flows, (-8_910_000.0, 540_000.0, 540_000.0, 540_000.0, 540_000.0, 9_540_000.0))
    # The funding lowers the closing equity need, the fee raises it, the debt
    # service lowers each year's residual, and the payoff lowers the exit once.
    flows = result.common_equity.cash_flows
    assert flows is not None and flows[0] == -18_000_000.0 + 9_000_000.0 - 90_000.0
    assert all_close(result.common_equity.cash_flows, (-9_090_000.0, 760_000.0, 760_000.0, 760_000.0, 760_000.0, 9_760_000.0))
    assert result.funding_requirements == () and result.status is CapitalStructureStatus.COMPLETE

    assert senior.valuation_basis.kind is PriceBasisKind.INVESTMENT_TRANSACTION_PRICE
    assert (senior.attachment_basis, senior.attachment_ltv) == (0.0, 0.0)
    assert (senior.detachment_basis, senior.detachment_ltv) == (9_000_000.0, 0.5)
    assert senior.debt_yield_through == 1_300_000.0 / 9_000_000.0
    assert all(
        value is not None and math.isclose(value, 1_300_000.0 / 540_000.0, rel_tol=1e-12)
        for value in senior.coverage_by_year
    )
    assert senior.irr is not None and senior.annual_cash_flows is not None
    assert senior.irr_status is IrrStatus.DEFINED and senior.irr > 0.06
    assert close(npv(senior.irr, senior.annual_cash_flows), 0.0, 1e-3)
    assert close(senior.moic, (90_000.0 + 5 * 540_000.0 + 9_000_000.0) / 9_000_000.0, 1e-9)
    assert _snapshot(consolidated, units) == before


def test_an_investment_percentage_of_price_reads_the_stated_transaction_price(tmp_path: Path) -> None:
    db = tmp_path / "priced.db"
    a = round_deal(db, name="Unit A", ltv=0.0)
    b = round_deal(db, name="Unit B", purchase_price=8_000_000.0, current_noi=500_000.0, exit_cap_rate=0.0625, ltv=0.0)
    analysis, units = visible(db, a, b, transaction_price=18_000_000.005)
    consolidated = analysis.consolidated_results
    assert consolidated.transaction_price == 18_000_000.005 != consolidated.allocated_purchase_price
    result = execute_investment_capital_structure(units=units, consolidated=consolidated, capital_structure=structure(_holdco_senior()))
    (senior,) = result.positions
    assert senior.funded_amount == 0.5 * 18_000_000.005
    assert senior.valuation_basis == PriceBasis(kind=PriceBasisKind.INVESTMENT_TRANSACTION_PRICE, amount=18_000_000.005)


def test_the_investment_root_names_its_own_residual(all_cash: dict[str, Any]) -> None:
    consolidated, units = all_cash["consolidated"], all_cash["units"]
    named = execute_investment_capital_structure(
        units=units, consolidated=consolidated, capital_structure=structure(_holdco_senior(), common_marker(scope=INVESTMENT, priority=5))
    )
    assert (named.common_equity.position_id, named.common_equity.scope) == ("common", INVESTMENT)
    for refused, code in (
        (structure(common_marker(scope=unit_scope(units[0].unit_id), priority=5)), ExecutionIssueCode.UNSUPPORTED_COMMON_EQUITY_SCOPE),
        (structure(common_marker(scope=INVESTMENT, priority=1), dataclasses.replace(_holdco_senior(), priority=2)), ExecutionIssueCode.CLAIM_BELOW_COMMON_EQUITY),
    ):
        with pytest.raises(CapitalStructureExecutionError) as error:
            execute_investment_capital_structure(units=units, consolidated=consolidated, capital_structure=refused)
        assert [issue.code for issue in error.value.issues] == [code]


# =============================================================================
# 3. The structural-subordination golden
# =============================================================================

#: Hand: the holdco preferred's 6% accrual (12% preferred, 6% current pay),
#: compounded annually on $2,000,000 for five years.
_HOLDCO_RATE = 0.12 - 0.06


def _holdco_accrued() -> float:
    accrued = 0.0
    for _ in range(5):
        accrued = accrued + (2_000_000.0 + accrued) * _HOLDCO_RATE
    return accrued


@pytest.fixture(scope="module")
def subordination(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Unit A: $6,000,000 mortgage (5% IO, $300,000 a year) and a $1,500,000
    Unit mezz at 12% IO ($180,000). Unit B ($8,000,000, $500,000 NOI): a
    $4,000,000 mortgage (6% IO, $240,000) and a $1,000,000 Unit preferred at
    10% current pay. The Investment: a $2,000,000 holdco preferred."""

    db = tmp_path_factory.mktemp("p7_8_subordination") / "subordination.db"
    a = round_deal(db, name="Unit A")
    b = round_deal(
        db, name="Unit B", purchase_price=8_000_000.0, current_noi=500_000.0, exit_cap_rate=0.0625, ltv=0.5, interest_rate=0.06
    )
    analysis, units = visible(db, a, b)
    consolidated = analysis.consolidated_results
    positions = (
        claim_position(
            "mezz-a", position_class=MEZZ, priority=2, scope=unit_scope(a.id), resolution=CEC, amount=1_500_000.0,
            terms=cash_pay_debt(rate=0.12, amortization=25, io_period=5, maturity_month=60),
        ),
        claim_position(
            "pref-b", position_class=PREF, priority=2, scope=unit_scope(b.id), resolution=CEC, amount=1_000_000.0,
            terms=preferred(preferred_rate=0.10, current_pay_rate=0.10),
        ),
        claim_position(
            "holdco", position_class=PREF, priority=1, scope=INVESTMENT, resolution=CEC, amount=2_000_000.0,
            terms=preferred(preferred_rate=0.12, current_pay_rate=0.06, convention=AccrualConvention.ANNUAL_COMPOUND),
        ),
    )
    before = _snapshot(consolidated, units)
    result = execute_investment_capital_structure(units=units, consolidated=consolidated, capital_structure=structure(*positions))
    return {
        "a": a.id, "b": b.id, "units": units, "consolidated": consolidated, "positions": positions, "before": before,
        "result": result, "by_id": {position.position_id: position for position in result.positions},
        "unit_results": {unit.unit_id: unit.results for unit in units},
    }


def test_the_subordination_premise(subordination: dict[str, Any]) -> None:
    unit_results, consolidated = subordination["unit_results"], subordination["consolidated"]
    assert unit_results[subordination["a"]].levered_cash_flows == (-4_000_000.0, 500_000.0, 500_000.0, 500_000.0, 500_000.0, 4_500_000.0)
    assert all_close(unit_results[subordination["b"]].levered_cash_flows, (-4_000_000.0, 260_000.0, 260_000.0, 260_000.0, 260_000.0, 4_260_000.0))
    assert consolidated.loan_amount == 10_000_000.0 and consolidated.transaction_price == 18_000_000.0
    assert all_close(consolidated.levered_cash_flows, (-8_000_000.0, 760_000.0, 760_000.0, 760_000.0, 760_000.0, 8_760_000.0))


def test_each_unit_scope_is_paid_from_its_own_units_cash_only(subordination: dict[str, Any]) -> None:
    unit_results, by_id = subordination["unit_results"], subordination["by_id"]
    for position_id, unit_id in (("mezz-a", subordination["a"]), ("pref-b", subordination["b"])):
        levered = unit_results[unit_id].levered_cash_flows
        claims = by_id[position_id].annual_claims
        assert [claim.hold_year for claim in claims] == [1, 2, 3, 4, 5]
        assert bits([claim.settlement.claim.cash_available for claim in claims]) == bits(list(levered[1:])), position_id


def test_the_investment_scope_reads_only_what_clears_every_unit(subordination: dict[str, Any]) -> None:
    """Hand: consolidated ``760,000`` less the Unit mezz ``180,000`` and the
    Unit preferred ``100,000`` in years 1-4; ``8,760,000`` less ``1,680,000``
    and ``1,100,000`` at the exit."""

    holdco = subordination["by_id"]["holdco"]
    available = [claim.settlement.claim.cash_available for claim in holdco.annual_claims]
    assert all_close(tuple(available), (480_000.0, 480_000.0, 480_000.0, 480_000.0, 5_980_000.0))


def test_the_holdco_compound_schedule_and_the_final_common_equity(subordination: dict[str, Any]) -> None:
    holdco, result = subordination["by_id"]["holdco"], subordination["result"]
    accrued = _holdco_accrued()
    assert close(accrued, 2_000_000.0 * ((1 + _HOLDCO_RATE) ** 5 - 1), 1e-6)
    assert close(holdco.balance_at_maturity_or_exit, 2_000_000.0 + accrued, 1e-6)
    assert all_close(holdco.annual_cash_flows, (-2_000_000.0, 120_000.0, 120_000.0, 120_000.0, 120_000.0, 120_000.0 + 2_000_000.0 + accrued))
    exit_residual = 5_980_000.0 - (120_000.0 + 2_000_000.0 + accrued)
    assert all_close(result.common_equity.cash_flows, (-3_500_000.0, 360_000.0, 360_000.0, 360_000.0, 360_000.0, exit_residual))
    assert result.status is CapitalStructureStatus.COMPLETE and result.funding_requirements == ()
    assert [position.status for position in result.positions] == [PositionResultStatus.COMPLETE] * 3


def test_structural_subordination_in_attachment_and_detachment(subordination: dict[str, Any]) -> None:
    """The holdco preferred attaches above both Unit mortgages and both Unit
    positions: $10,000,000 + $1,500,000 + $1,000,000."""

    by_id = subordination["by_id"]
    holdco, mezz_a, pref_b = by_id["holdco"], by_id["mezz-a"], by_id["pref-b"]
    assert (holdco.attachment_basis, holdco.detachment_basis, holdco.last_dollar_basis) == (12_500_000.0, 14_500_000.0, 14_500_000.0)
    assert (holdco.attachment_ltv, holdco.detachment_ltv) == (12_500_000.0 / 18_000_000.0, 14_500_000.0 / 18_000_000.0)
    assert holdco.valuation_basis == PriceBasis(kind=PriceBasisKind.INVESTMENT_TRANSACTION_PRICE, amount=18_000_000.0)
    assert (mezz_a.attachment_basis, mezz_a.detachment_basis, mezz_a.attachment_ltv, mezz_a.detachment_ltv) == (
        6_000_000.0, 7_500_000.0, 0.6, 0.75,
    )
    assert (pref_b.attachment_basis, pref_b.detachment_basis, pref_b.attachment_ltv, pref_b.detachment_ltv) == (
        4_000_000.0, 5_000_000.0, 0.5, 0.625,
    )
    assert pref_b.valuation_basis == PriceBasis(kind=PriceBasisKind.UNIT_PURCHASE_PRICE, amount=8_000_000.0)


def test_coverage_through_includes_every_structurally_senior_position(subordination: dict[str, Any]) -> None:
    """Hand: consolidated NOI $1,300,000 over $540,000 of mortgage service, the
    two Unit positions' $180,000 and $100,000 and the holdco's own $120,000 of
    current pay. A Unit position's coverage reads its own Unit only."""

    by_id = subordination["by_id"]
    for position_id, expected in (
        ("holdco", 1_300_000.0 / 940_000.0), ("mezz-a", 800_000.0 / 480_000.0), ("pref-b", 500_000.0 / 340_000.0),
    ):
        coverage = by_id[position_id].coverage_by_year
        assert len(coverage) == 5 and all(math.isclose(value, expected, rel_tol=1e-12) for value in coverage), position_id


def test_debt_yield_through_is_the_scopes_year_1_noi_never_an_average(subordination: dict[str, Any]) -> None:
    by_id = subordination["by_id"]
    assert by_id["holdco"].debt_yield_through == 1_300_000.0 / 14_500_000.0
    assert by_id["mezz-a"].debt_yield_through == 800_000.0 / 7_500_000.0
    assert by_id["pref-b"].debt_yield_through == 500_000.0 / 5_000_000.0
    average = (by_id["mezz-a"].debt_yield_through + by_id["pref-b"].debt_yield_through) / 2
    assert not math.isclose(by_id["holdco"].debt_yield_through, average, rel_tol=1e-6)


def test_the_upstream_results_are_untouched(subordination: dict[str, Any]) -> None:
    assert _snapshot(subordination["consolidated"], subordination["units"]) == subordination["before"]


def test_no_permutation_of_positions_or_units_moves_a_bit(subordination: dict[str, Any]) -> None:
    permuted = execute_investment_capital_structure(
        units=tuple(reversed(subordination["units"])),
        consolidated=subordination["consolidated"],
        capital_structure=structure(*reversed(subordination["positions"])),
    )
    assert permuted == subordination["result"]
    assert [position.scope.kind for position in permuted.positions] == [ScopeKind.UNIT, ScopeKind.UNIT, ScopeKind.INVESTMENT]


# =============================================================================
# 4. Unresolved funding
# =============================================================================


def test_an_unresolved_senior_blocks_every_junior_and_common_equity() -> None:
    terms, results = round_unit()
    before = dataclasses.asdict(results)
    junior = claim_position(
        "pref", position_class=PREF, priority=3, resolution=CEC, amount=1_000_000.0,
        terms=preferred(preferred_rate=0.10, current_pay_rate=0.10),
    )
    result = execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(junior, golden_mezz(UNRESOLVED))
    )
    mezz, pref = result.positions

    (requirement,) = mezz.funding_requirements
    assert requirement.requirement_id == "mezz/hold_year/4" and requirement.status is FundingRequirementStatus.UNRESOLVED
    assert requirement.cash_available == 500_000.0
    assert requirement.unpaid_claim_amount == requirement.claim_amount - 500_000.0 and requirement.equity_contribution == 0.0
    assert (mezz.status, mezz.unavailable_reason) == (PositionResultStatus.UNRESOLVED_FUNDING, PositionUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT)
    assert mezz.blocking_requirement_ids == ("mezz/hold_year/4",)
    assert (mezz.annual_cash_flows, mezz.irr, mezz.irr_status, mezz.moic, mezz.profit, mezz.total_cash_received) == (None,) * 6

    assert (pref.status, pref.unavailable_reason) == (PositionResultStatus.BLOCKED_BY_SENIOR_UNRESOLVED, PositionUnavailableReason.SENIOR_UNRESOLVED_FUNDING_REQUIREMENT)
    assert pref.blocking_requirement_ids == ("mezz/hold_year/4",)
    assert pref.unavailable_message is not None and "mezz/hold_year/4" in pref.unavailable_message
    assert (pref.annual_claims, pref.funding_requirements, pref.annual_cash_flows, pref.irr) == ((), (), None, None)
    assert (pref.attachment_basis, pref.detachment_basis) == (7_500_000.0, 8_500_000.0)

    common = result.common_equity
    assert (common.cash_flows, common.irr, common.equity_multiple, common.total_profit) == (None, None, None, None)
    assert common.unavailable_reason is CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
    assert result.status is CapitalStructureStatus.UNRESOLVED_FUNDING
    assert result.funding_requirements == (requirement,)
    assert dataclasses.asdict(results) == before


def test_a_valid_senior_keeps_its_returns_when_a_junior_is_unresolved() -> None:
    """The mezz is cured by its own common-equity contribution in year 4. That
    contribution is never cash for the junior preferred, whose year-4 claim is
    therefore unresolved -- and the mezz's complete returns stand."""

    terms, results = round_unit()
    alone = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(golden_mezz()))
    junior = claim_position(
        "pref", position_class=PREF, priority=3, resolution=UNRESOLVED, amount=1_000_000.0,
        terms=preferred(preferred_rate=0.10, current_pay_rate=0.10),
    )
    result = execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(golden_mezz(), junior)
    )
    mezz, pref = result.positions
    assert mezz == alone.positions[0] and mezz.status is PositionResultStatus.COMPLETE and mezz.irr is not None

    (requirement,) = pref.funding_requirements
    assert requirement.requirement_id == "pref/hold_year/4"
    assert requirement.cash_available == 0.0 and requirement.unpaid_claim_amount == 100_000.0
    assert pref.status is PositionResultStatus.UNRESOLVED_FUNDING
    assert result.common_equity.cash_flows is None and result.status is CapitalStructureStatus.UNRESOLVED_FUNDING


@pytest.fixture(scope="module")
def stressed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Unit A carries a mezz whose month-48 balloon it cannot pay and which
    names no cure. Unit B is a $30,000,000 all-cash Unit with a large surplus
    and a valid Unit preferred. The Investment carries a holdco mezz."""

    db = tmp_path_factory.mktemp("p7_8_stressed") / "stressed.db"
    a = round_deal(db, name="Short A")
    b = round_deal(db, name="Surplus B", purchase_price=30_000_000.0, current_noi=2_400_000.0, ltv=0.0)
    analysis, units = visible(db, a, b)
    consolidated = analysis.consolidated_results
    positions = (
        claim_position(
            "mezz-a", position_class=MEZZ, priority=2, scope=unit_scope(a.id), resolution=UNRESOLVED, amount=1_500_000.0,
            terms=cash_pay_debt(rate=0.12, amortization=25, io_period=5, maturity_month=48),
        ),
        claim_position(
            "pref-b", position_class=PREF, priority=1, scope=unit_scope(b.id), resolution=CEC, amount=1_000_000.0,
            terms=preferred(preferred_rate=0.10, current_pay_rate=0.10),
        ),
        claim_position(
            "holdco", position_class=MEZZ, priority=1, scope=INVESTMENT, resolution=CEC, amount=1_000_000.0,
            terms=cash_pay_debt(rate=0.10, io_period=5, maturity_month=60),
        ),
    )
    before = _snapshot(consolidated, units)
    result = execute_investment_capital_structure(units=units, consolidated=consolidated, capital_structure=structure(*positions))
    return {
        "a": a.id, "units": units, "consolidated": consolidated, "before": before, "result": result,
        "by_id": {position.position_id: position for position in result.positions},
    }


def test_one_units_surplus_never_cures_another_units_claim(stressed: dict[str, Any]) -> None:
    consolidated, mezz_a = stressed["consolidated"], stressed["by_id"]["mezz-a"]
    # The premise: netted across the Investment, year 4 would cover the claim.
    assert consolidated.levered_cash_flows[4] > 1_680_000.0 + 100_000.0
    (requirement,) = mezz_a.funding_requirements
    assert requirement.requirement_id == "mezz-a/hold_year/4" and requirement.status is FundingRequirementStatus.UNRESOLVED
    assert requirement.cash_available == 500_000.0  # Unit A's own post-debt cash only
    assert close(requirement.unpaid_claim_amount, 1_680_000.0 - 500_000.0)
    assert mezz_a.status is PositionResultStatus.UNRESOLVED_FUNDING


def test_an_independent_units_valid_position_stays_valid(stressed: dict[str, Any]) -> None:
    pref_b = stressed["by_id"]["pref-b"]
    assert pref_b.status is PositionResultStatus.COMPLETE and pref_b.funding_requirements == ()
    assert close(pref_b.irr, 0.10, 1e-9) and pref_b.moic == 1.5


def test_the_investment_scope_is_blocked_once_any_unit_is_unresolved(stressed: dict[str, Any]) -> None:
    holdco, result = stressed["by_id"]["holdco"], stressed["result"]
    assert holdco.status is PositionResultStatus.BLOCKED_BY_SENIOR_UNRESOLVED
    assert holdco.blocking_requirement_ids == ("mezz-a/hold_year/4",)
    assert (holdco.annual_claims, holdco.funding_requirements, holdco.annual_cash_flows, holdco.irr) == ((), (), None, None)
    assert holdco.attachment_basis == 6_000_000.0 + 1_500_000.0 + 1_000_000.0
    assert result.common_equity.cash_flows is None
    assert "mezz-a/hold_year/4" in result.common_equity.unavailable_message
    assert result.status is CapitalStructureStatus.UNRESOLVED_FUNDING
    assert _snapshot(stressed["consolidated"], stressed["units"]) == stressed["before"]


# =============================================================================
# 5. Common Equity returns after structured positions
# =============================================================================


def test_common_equity_returns_are_read_off_the_final_residual() -> None:
    """Hand: legacy mortgage, a $1,000,000 mezz at 10% interest-only
    ($100,000) and a $500,000 preferred at 6% current pay ($30,000), both
    repaid at the exit. The residual is ``-2,500,000; 370,000 x 4; 2,870,000``."""

    terms, results = round_unit()
    mezz = claim_position(
        "mezz", position_class=MEZZ, priority=2, resolution=CEC, amount=1_000_000.0,
        terms=cash_pay_debt(rate=0.10, io_period=5, maturity_month=60),
    )
    pref = claim_position(
        "pref", position_class=PREF, priority=3, resolution=CEC, amount=500_000.0,
        terms=preferred(preferred_rate=0.06, current_pay_rate=0.06),
    )
    result = execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(pref, common_marker(), mezz)
    )
    common = result.common_equity
    flows = common.cash_flows
    assert flows is not None
    hand = (-2_500_000.0, 370_000.0, 370_000.0, 370_000.0, 370_000.0, 2_870_000.0)
    assert all_close(flows, hand)
    assert (common.irr, common.irr_status) == evaluate_irr(flows)
    hand_irr, hand_status = evaluate_irr(hand)
    assert hand_status is IrrStatus.DEFINED and hand_irr is not None
    assert common.irr_status is IrrStatus.DEFINED and close(common.irr, hand_irr, 1e-9)
    assert common.equity_multiple == calculate_equity_multiple(levered_cash_flows=flows)
    assert close(common.equity_multiple, 4_350_000.0 / 2_500_000.0, 1e-9)
    assert (common.total_cash_returned, common.total_equity_invested, common.total_profit) == calculate_project_return_totals(
        levered_cash_flows=flows
    )
    assert close(common.total_equity_invested, 2_500_000.0) and close(common.total_cash_returned, 4_350_000.0)
    assert close(common.total_profit, 1_850_000.0)
    # Not the project levered returns: those keep their meaning (NS-1).
    assert common.irr != results.levered_irr and common.equity_multiple != results.equity_multiple
    assert common.position_id == "common"


# =============================================================================
# 6. Attachment and detachment
# =============================================================================


def test_attachment_and_detachment_of_a_known_capital_stack() -> None:
    """Senior $60M (the acquisition loan), mezz $15M, preferred $10M, on a
    $100M purchase price. Fees and accrued return never enter the basis."""

    terms, results = round_unit(purchase_price=100_000_000.0, current_noi=8_000_000.0)
    assert results.loan_amount == 60_000_000.0
    mezz = claim_position(
        "mezz", position_class=MEZZ, priority=2, resolution=CEC, amount=15_000_000.0,
        terms=cash_pay_debt(rate=0.11, io_period=5, maturity_month=60, fees=(fee("mezz-fee", amount=150_000.0),)),
    )
    pref = claim_position(
        "pref", position_class=PREF, priority=3, resolution=CEC, amount=10_000_000.0,
        terms=preferred(preferred_rate=0.12, current_pay_rate=0.08, convention=AccrualConvention.SIMPLE),
    )
    mezz_r, pref_r = execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(mezz, pref)
    ).positions
    assert (mezz_r.attachment_basis, mezz_r.detachment_basis, mezz_r.last_dollar_basis) == (60_000_000.0, 75_000_000.0, 75_000_000.0)
    assert (mezz_r.attachment_ltv, mezz_r.detachment_ltv) == (0.6, 0.75)
    assert (pref_r.attachment_basis, pref_r.detachment_basis, pref_r.last_dollar_basis) == (75_000_000.0, 85_000_000.0, 85_000_000.0)
    assert (pref_r.attachment_ltv, pref_r.detachment_ltv) == (0.75, 0.85)
    assert mezz_r.valuation_basis == PriceBasis(kind=PriceBasisKind.UNIT_PURCHASE_PRICE, amount=100_000_000.0)
