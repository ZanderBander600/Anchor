"""Phase 7 Gate P7.8 -- the human financial review corrections: unresolved-claim
finality and the over-funded closing.

``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md`` Sections 9, 10 and
14 (decisions 2 and 6):

- **Finality.** A position's settlement stops at its first unresolved claim.
  That requirement is preserved exactly; its later contractual events stay
  inspectable, but with no arrears, default or capitalization convention their
  settlement is unknowable, so no later year is settled and no later Funding
  Requirement exists. Juniors and the Investment scope stay blocked; senior
  and independent positions stay valid.
- **Over-funded closing.** After every authored month-0 funding and fee, the
  analysis root's closing Common Equity flow may reach zero within $0.01 and
  never turn materially positive. The check is at the root: a Unit funded
  locally beyond its own equity need is not refused while the Investment still
  has closing uses. Nothing is resized, rebalanced or rounded.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from _p7_6_fixtures import cost, investment_plan  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    CEC,
    INVESTMENT,
    UNIT,
    UNRESOLVED,
    cash_pay_debt,
    claim_position,
    close,
    fee,
    golden_mezz,
    preferred,
    round_deal,
    round_unit,
    structure,
    unit_scope,
    visible,
)
from anchor.business_plan import BusinessPlan, CapitalItemCategory, CapitalPlanItem
from anchor.capital_structure import (
    CapitalPosition,
    CapitalStructureExecutionError,
    CapitalStructureStatus,
    CommonEquityUnavailableReason,
    ExecutionIssueCode,
    FundingRequirementStatus,
    PositionCashFlowKind,
    PositionClass,
    PositionResultStatus,
    PositionUnavailableReason,
    PriceBasis,
    PriceBasisKind,
    execute_investment_capital_structure,
    execute_unit_capital_structure,
    schedule_position,
)
from anchor.capital_structure.execution_contracts import OVERFUNDED_CLOSING_TOLERANCE

MEZZ = PositionClass.MEZZANINE_DEBT
PREF = PositionClass.PREFERRED_EQUITY
Kind = PositionCashFlowKind


def _snapshot(consolidated: Any, units: Any) -> tuple[Any, ...]:
    return (dataclasses.asdict(consolidated), [dataclasses.asdict(unit.results) for unit in units])


# =============================================================================
# 1. Unresolved-claim finality
# =============================================================================

#: A $400,000 roof in month 30 leaves Unit A only $100,000 of post-debt cash in
#: year 3, below the mezz's $180,000 of interest.
_YEAR_3_ROOF = BusinessPlan(
    capital_items=(
        CapitalPlanItem(
            item_id="cap-y3", description="Roof", category=CapitalItemCategory.BUILDING_SYSTEMS, month=30,
            amount=400_000.0,
        ),
    )
)


@pytest.fixture(scope="module")
def finality(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Unit A: the round-number Unit with the roof, an interest-only mezz with
    no cure whose claims fall in every year 1-5, and a junior preferred. Unit
    B: an independent all-cash Unit with a valid preferred. The Investment: a
    holdco mezz."""

    db = tmp_path_factory.mktemp("p7_8_finality") / "finality.db"
    a = round_deal(db, name="Unit A", business_plan=_YEAR_3_ROOF)
    b = round_deal(db, name="Unit B", ltv=0.0)
    analysis, units = visible(db, a, b)
    consolidated = analysis.consolidated_results
    positions = (
        claim_position(
            "mezz-a", position_class=MEZZ, priority=2, scope=unit_scope(a.id), resolution=UNRESOLVED, amount=1_500_000.0,
            terms=cash_pay_debt(rate=0.12, amortization=25, io_period=5, maturity_month=60),
        ),
        claim_position(
            "pref-a", position_class=PREF, priority=3, scope=unit_scope(a.id), resolution=CEC, amount=500_000.0,
            terms=preferred(preferred_rate=0.08, current_pay_rate=0.08),
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
        "a": a.id, "units": units, "consolidated": consolidated, "before": before, "positions": positions,
        "result": result, "by_id": {position.position_id: position for position in result.positions},
        "unit_results": {unit.unit_id: unit.results for unit in units},
    }


def test_the_finality_premise(finality: dict[str, Any]) -> None:
    """Year 3 is the first shortfall; years 4 and 5 would each be covered by
    Unit A's own cash, so settling them would have looked clean."""

    levered = finality["unit_results"][finality["a"]].levered_cash_flows
    assert levered == (-4_000_000.0, 500_000.0, 500_000.0, 100_000.0, 500_000.0, 4_500_000.0)
    assert levered[4] >= 180_000.0 and levered[5] >= 180_000.0 + 1_500_000.0


def test_settlement_stops_at_the_first_unresolved_claim(finality: dict[str, Any]) -> None:
    mezz = finality["by_id"]["mezz-a"]
    assert [claim.hold_year for claim in mezz.annual_claims] == [1, 2, 3]
    assert [claim.settlement.funding_requirement for claim in mezz.annual_claims[:2]] == [None, None]

    requirement = mezz.annual_claims[2].settlement.funding_requirement
    assert requirement is not None
    assert requirement.requirement_id == "mezz-a/hold_year/3"
    assert requirement.status is FundingRequirementStatus.UNRESOLVED
    assert (requirement.claim_amount, requirement.cash_available, requirement.claim_paid_from_cash) == (180_000.0, 100_000.0, 100_000.0)
    assert (requirement.amount, requirement.unpaid_claim_amount, requirement.equity_contribution) == (80_000.0, 80_000.0, 0.0)


def test_only_the_first_unresolved_requirement_is_emitted(finality: dict[str, Any]) -> None:
    mezz, result = finality["by_id"]["mezz-a"], finality["result"]
    (requirement,) = mezz.funding_requirements
    assert requirement.requirement_id == "mezz-a/hold_year/3"
    ids = [requirement.requirement_id for requirement in result.funding_requirements]
    assert ids == ["mezz-a/hold_year/3"]
    assert not {"mezz-a/hold_year/4", "mezz-a/hold_year/5"} & set(ids)


def test_later_contractual_events_stay_inspectable(finality: dict[str, Any]) -> None:
    mezz = finality["by_id"]["mezz-a"]
    payments = [event.model_month for event in mezz.cash_flow_events if event.kind is Kind.SCHEDULED_DEBT_SERVICE]
    assert payments == list(range(1, 61))
    (balloon,) = [event for event in mezz.cash_flow_events if event.kind is Kind.BALLOON]
    assert (balloon.model_month, balloon.amount) == (60, 1_500_000.0)
    scheduled = schedule_position(
        finality["positions"][0],
        price_basis=PriceBasis(kind=PriceBasisKind.UNIT_PURCHASE_PRICE, amount=10_000_000.0),
        hold_period=5,
    )
    assert mezz.cash_flow_events == scheduled.events
    assert mezz.debt_schedule == scheduled.debt_schedule


def test_the_unresolved_positions_returns_are_unavailable(finality: dict[str, Any]) -> None:
    mezz = finality["by_id"]["mezz-a"]
    assert (mezz.status, mezz.unavailable_reason) == (
        PositionResultStatus.UNRESOLVED_FUNDING, PositionUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT,
    )
    assert mezz.blocking_requirement_ids == ("mezz-a/hold_year/3",)
    assert (mezz.annual_cash_flows, mezz.irr, mezz.irr_status, mezz.moic, mezz.profit, mezz.total_cash_received) == (None,) * 6


def test_juniors_and_the_investment_scope_stay_blocked(finality: dict[str, Any]) -> None:
    by_id, result = finality["by_id"], finality["result"]
    for position_id in ("pref-a", "holdco"):
        position = by_id[position_id]
        assert position.status is PositionResultStatus.BLOCKED_BY_SENIOR_UNRESOLVED, position_id
        assert position.blocking_requirement_ids == ("mezz-a/hold_year/3",), position_id
        assert (position.annual_claims, position.funding_requirements, position.irr) == ((), (), None), position_id
    assert result.common_equity.cash_flows is None
    assert result.common_equity.unavailable_reason is CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
    assert result.status is CapitalStructureStatus.UNRESOLVED_FUNDING


def test_an_independent_units_position_stays_valid(finality: dict[str, Any]) -> None:
    pref_b = finality["by_id"]["pref-b"]
    assert pref_b.status is PositionResultStatus.COMPLETE and pref_b.funding_requirements == ()
    assert [claim.hold_year for claim in pref_b.annual_claims] == [1, 2, 3, 4, 5]
    assert close(pref_b.irr, 0.10, 1e-9) and pref_b.moic == 1.5


def test_finality_leaves_every_upstream_figure_untouched(finality: dict[str, Any]) -> None:
    assert _snapshot(finality["consolidated"], finality["units"]) == finality["before"]


# =============================================================================
# 2. The over-funded closing: a standalone Unit
# =============================================================================


@pytest.fixture(scope="module")
def unit() -> tuple[Any, Any]:
    """The round-number Unit: Common Equity T0 is -$4,000,000."""

    return round_unit()


def _mezz(amount: float, *, fee_amount: float = 0.0, position_id: str = "mezz", priority: int = 2) -> CapitalPosition:
    fees = (fee(f"{position_id}-fee", amount=fee_amount),) if fee_amount else ()
    return claim_position(
        position_id, position_class=MEZZ, priority=priority, resolution=CEC, amount=amount,
        terms=cash_pay_debt(rate=0.05, io_period=5, maturity_month=60, fees=fees),
    )


def _run(unit: tuple[Any, Any], *positions: CapitalPosition) -> Any:
    terms, results = unit
    return execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(*positions))


def _refusal(action: Any) -> Any:
    with pytest.raises(CapitalStructureExecutionError) as refused:
        action()
    (issue,) = refused.value.issues
    assert issue.code is ExecutionIssueCode.OVERFUNDED_CLOSING
    assert issue.position_id is None
    return issue


def test_the_tolerance_is_one_cent() -> None:
    assert OVERFUNDED_CLOSING_TOLERANCE == 0.01


def test_a_partly_financed_closing_is_valid(unit: tuple[Any, Any]) -> None:
    result = _run(unit, _mezz(3_000_000.0, fee_amount=10_000.0))
    assert result.common_equity.cash_flows[0] == -4_000_000.0 + 3_000_000.0 - 10_000.0
    assert result.positions[0].funded_amount == 3_000_000.0


def test_a_closing_financed_exactly_to_zero_is_valid_and_nothing_is_resized(unit: tuple[Any, Any]) -> None:
    result = _run(unit, _mezz(4_015_000.0, fee_amount=15_000.0))
    assert result.common_equity.cash_flows[0] == 0.0
    assert result.positions[0].funded_amount == 4_015_000.0
    assert result.status is CapitalStructureStatus.COMPLETE


def test_a_residual_within_the_tolerance_is_valid_and_never_rounded(unit: tuple[Any, Any]) -> None:
    result = _run(unit, _mezz(4_000_000.005))
    t0 = result.common_equity.cash_flows[0]
    assert t0 == -4_000_000.0 - (-4_000_000.005)
    assert 0.0 < t0 <= OVERFUNDED_CLOSING_TOLERANCE


@pytest.mark.parametrize(("amount", "excess"), [(5_015_000.0, "1,000,000.00"), (4_015_000.02, "0.02")])
def test_a_materially_over_funded_unit_closing_is_refused(unit: tuple[Any, Any], amount: float, excess: str) -> None:
    issue = _refusal(lambda: _run(unit, _mezz(amount, fee_amount=15_000.0)))
    assert issue.message == (
        f"Authored capital exceeds the Unit closing funding requirement by {excess}. P7.8 does not infer a cash "
        "reserve, closing distribution or recapitalization for excess proceeds."
    )


def test_every_authored_closing_counts_in_any_order_even_a_blocked_positions(unit: tuple[Any, Any]) -> None:
    """Closing happens before any year is settled: a junior blocked later by an
    unresolved senior still funded at closing. Two positions over-funding
    together are refused whichever is listed first."""

    junior = claim_position(
        "pref", position_class=PREF, priority=3, resolution=CEC, amount=3_000_000.0,
        terms=preferred(preferred_rate=0.10, current_pay_rate=0.10),
    )
    first = _refusal(lambda: _run(unit, golden_mezz(UNRESOLVED), junior))
    second = _refusal(lambda: _run(unit, junior, golden_mezz(UNRESOLVED)))
    assert first == second
    assert "485,000.00" in first.message  # -4,000,000 + 1,500,000 - 15,000 + 3,000,000


# =============================================================================
# 3. The over-funded closing: the visible Investment root
# =============================================================================


@pytest.fixture(scope="module")
def funded(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Unit A (Common Equity T0 -$4,000,000) and Unit B at 90% LTV (T0
    -$1,000,000), with Investment closing uses: a $150,000 transaction cost and
    $200,000 of closing Investment Business Plan capital. The Investment root's
    T0 is -$5,350,000."""

    db = tmp_path_factory.mktemp("p7_8_funded") / "funded.db"
    a = round_deal(db, name="Unit A")
    b = round_deal(db, name="Unit B", ltv=0.9)
    analysis, units = visible(db, a, b, business_plan=investment_plan(), costs=(cost("tc-1", 150_000.0),))
    return {"a": a.id, "units": units, "consolidated": analysis.consolidated_results}


def _unit_mezz(unit_id: str) -> CapitalPosition:
    """$4,200,000 of Unit A mezz less a $50,000 fee: $150,000 more than Unit A's
    own $4,000,000 closing equity need."""

    return claim_position(
        "mezz-a", position_class=MEZZ, priority=2, scope=unit_scope(unit_id), resolution=CEC, amount=4_200_000.0,
        terms=cash_pay_debt(rate=0.05, io_period=5, maturity_month=60, fees=(fee("mezz-a-fee", amount=50_000.0),)),
    )


def _holdco(amount: float) -> CapitalPosition:
    return claim_position(
        "holdco", position_class=PREF, priority=1, scope=INVESTMENT, resolution=CEC, amount=amount,
        terms=preferred(preferred_rate=0.08, current_pay_rate=0.08),
    )


def test_the_investment_root_premise(funded: dict[str, Any]) -> None:
    consolidated, units = funded["consolidated"], funded["units"]
    by_unit = {unit.unit_id: unit.results for unit in units}
    assert by_unit[funded["a"]].levered_cash_flows[0] == -4_000_000.0
    assert consolidated.investment_transaction_costs == 150_000.0
    assert consolidated.investment_closing_project_capital == 200_000.0
    assert close(consolidated.levered_cash_flows[0], -5_350_000.0)


def test_a_locally_over_funded_unit_is_refused_only_as_its_own_root(funded: dict[str, Any]) -> None:
    """Unit A alone, as a standalone root, is over-funded by $150,000. Inside
    the Investment, whose root still has closing uses, the same position with a
    $1,000,000 Investment-scoped preferred leaves the root at -$200,000."""

    unit_a = next(unit for unit in funded["units"] if unit.unit_id == funded["a"])
    standalone = _refusal(
        lambda: execute_unit_capital_structure(
            unit_id=unit_a.unit_id, terms=unit_a.terms, results=unit_a.results,
            capital_structure=structure(_unit_mezz(unit_a.unit_id)),
        )
    )
    assert "the Unit closing funding requirement by 150,000.00" in standalone.message

    consolidated = funded["consolidated"]
    before = _snapshot(consolidated, funded["units"])
    result = execute_investment_capital_structure(
        units=funded["units"], consolidated=consolidated,
        capital_structure=structure(_unit_mezz(funded["a"]), _holdco(1_000_000.0)),
    )
    flows = result.common_equity.cash_flows
    assert flows is not None
    assert close(flows[0], -5_350_000.0 + 4_200_000.0 - 50_000.0 + 1_000_000.0)
    assert flows[0] <= 0.0
    assert [position.funded_amount for position in result.positions] == [4_200_000.0, 1_000_000.0]
    assert _snapshot(consolidated, funded["units"]) == before


def test_a_materially_over_funded_investment_root_is_refused(funded: dict[str, Any]) -> None:
    for positions in (
        (_unit_mezz(funded["a"]), _holdco(2_000_000.0)),
        (_holdco(2_000_000.0), _unit_mezz(funded["a"])),
    ):
        issue = _refusal(
            lambda positions=positions: execute_investment_capital_structure(
                units=funded["units"], consolidated=funded["consolidated"], capital_structure=structure(*positions)
            )
        )
        # -5,350,000 + 4,200,000 - 50,000 + 2,000,000
        assert "the Investment closing funding requirement by 800,000.00" in issue.message
