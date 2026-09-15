"""Phase 7 Gate P7.7 -- the read-only legacy acquisition-loan adapter and the
neutral Capital Structure facade.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 12.4 (the
parity oracle and the pre-capital-structure handoff invariant) and
``docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md``. Proves, for Quick,
Detailed, Lease-Level and a visible multi-Unit Investment:

- the Common Equity Cash Flow is today's levered cash flow, bit for bit;
- every adapted figure is the completed result's own field, never recomputed;
- the acquisition loan bridges the pre- and post-debt authorities exactly once
  (the named double-counting oracle);
- a Unit without an acquisition loan has no position at all.
"""

from __future__ import annotations

import ast
import dataclasses
import math
from pathlib import Path
from typing import Any

import pytest

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import (  # type: ignore[import-not-found]
    cost,
    create_investment,
    detailed_deal,
    investment_plan,
    lease_level_deal,
    quick_deal,
)
from _p7_7_fixtures import (  # type: ignore[import-not-found]
    MODES,
    PARITY_CASES,
    analyze_unit,
    analyze_visible_investment,
    bits,
    parity_case,
)
from anchor.capital_structure import (
    LEGACY_ACQUISITION_LOAN_ID_PREFIX,
    CapitalStructure,
    CapitalStructureError,
    CapitalStructureStatus,
    CapitalStructureUnit,
    FixedAmount,
    LegacyAcquisitionLoan,
    PositionClass,
    ScopeKind,
    ShortfallResolution,
    adapt_legacy_acquisition_loan,
    analyze_investment_capital_structure,
    analyze_unit_capital_structure,
    legacy_acquisition_loan_id,
)
from anchor.engine import debt as debt_module

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parity_holds(candidate: tuple[float, ...] | None, authority: tuple[float, ...]) -> bool:
    """The parity oracle: the candidate is the authority, bit for bit."""

    return candidate is not None and bits(candidate) == bits(authority)


# =============================================================================
# The parity cases exercise what they claim
# =============================================================================


def test_the_parity_cases_exercise_leverage_fees_io_plans_and_negative_owner_years() -> None:
    covered = {"io": 0, "plan": 0, "negative": 0}
    for name, (_, plan, _) in PARITY_CASES.items():
        terms, results = parity_case(name)
        assert terms.ltv > 0.0 and results.loan_amount > 0.0, name
        assert results.financing_fee > 0.0, name
        assert terms.amortization >= 1 and results.remaining_loan_balance > 0.0, name
        covered["io"] += terms.io_period > 0
        covered["plan"] += bool(plan().capital_items)
        negative = any(cash_flow < 0.0 for cash_flow in results.unlevered_owner_cash_flow_by_year)
        assert negative is ("negative" in name), name
        covered["negative"] += negative
    assert {mode for mode, _, _ in PARITY_CASES.values()} == set(MODES)
    assert covered == {"io": 7, "plan": 6, "negative": 3}


# =============================================================================
# Unit parity: Quick, Detailed, Lease-Level
# =============================================================================


@pytest.mark.parametrize("case", sorted(PARITY_CASES))
def test_common_equity_is_todays_levered_cash_flow_bit_for_bit(case: str) -> None:
    terms, results = parity_case(case)
    outcome = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results)

    assert outcome.status is CapitalStructureStatus.COMPLETE
    assert _parity_holds(outcome.common_equity_cash_flows, results.levered_cash_flows)
    assert outcome.common_equity_unavailable_reason is None and outcome.common_equity_unavailable_message is None


@pytest.mark.parametrize("case", sorted(PARITY_CASES))
def test_the_adapted_loan_is_read_off_the_result_exactly(case: str) -> None:
    terms, results = parity_case(case)
    loan = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results).legacy_acquisition_loan

    assert isinstance(loan, LegacyAcquisitionLoan)
    assert bits([loan.loan_amount]) == bits([results.loan_amount])
    assert loan.funding.amount_rule == FixedAmount(amount=results.loan_amount)
    assert (loan.funding.model_month, loan.funding.sequence) == (0, 1)
    assert bits([loan.financing_fee.amount]) == bits([results.financing_fee])
    assert (loan.financing_fee.model_month, loan.financing_fee.sequence) == (0, 2)
    assert bits(loan.annual_debt_service) == bits(results.annual_debt_service)
    assert bits([loan.remaining_loan_balance]) == bits([results.remaining_loan_balance])
    assert (loan.position_class, loan.priority, loan.scope.kind, loan.scope.unit_id) == (
        PositionClass.SENIOR_DEBT, 1, ScopeKind.UNIT, "unit-a",
    )
    assert loan.shortfall_resolution is ShortfallResolution.COMMON_EQUITY_CONTRIBUTION
    assert loan.modeled_payoff_month == 12 * terms.hold_period
    assert (loan.interest_rate, loan.amortization, loan.io_period, loan.hold_period) == (
        terms.interest_rate, terms.amortization, terms.io_period, terms.hold_period,
    )


def test_the_facade_passes_the_existing_series_through_and_reconstructs_nothing() -> None:
    terms, results = parity_case("detailed-plan")
    outcome = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results)
    authority = outcome.cash_authority

    assert outcome.common_equity_cash_flows is results.levered_cash_flows
    assert authority.pre_acquisition_debt_cash_flows is results.unlevered_cash_flows
    assert authority.post_acquisition_debt_cash_flows is results.levered_cash_flows
    assert authority.owner_cash_flow_after_acquisition_debt_by_year is results.levered_owner_cash_flow_by_year
    assert bits([authority.net_sale_proceeds_after_acquisition_debt]) == bits([results.net_sale_proceeds])
    loan = outcome.legacy_acquisition_loan
    assert loan is not None and loan.annual_debt_service is results.annual_debt_service


@pytest.mark.parametrize("case", sorted(PARITY_CASES))
def test_the_acquisition_loan_bridges_pre_to_post_debt_exactly_once(case: str) -> None:
    """The handoff invariant as an identity: the pre-debt authority, less the
    adapted loan's figures taken once, is the post-debt authority. Within a
    tolerance only because the two engine series group their floating-point
    operations differently (D6 Section 6)."""

    terms, results = parity_case(case)
    outcome = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results)
    loan = outcome.legacy_acquisition_loan
    assert loan is not None
    pre, post = outcome.cash_authority.pre_acquisition_debt_cash_flows, outcome.cash_authority.post_acquisition_debt_cash_flows
    hold = terms.hold_period
    expected = [pre[0] + loan.loan_amount - loan.financing_fee.amount]
    expected += [pre[t] - loan.annual_debt_service[t - 1] for t in range(1, hold)]
    expected += [pre[hold] - loan.annual_debt_service[hold - 1] - loan.remaining_loan_balance]
    for t, (bridged, actual) in enumerate(zip(expected, post, strict=True)):
        assert math.isclose(bridged, actual, rel_tol=0.0, abs_tol=1e-6), (case, t, bridged, actual)


@pytest.mark.parametrize("case", sorted(PARITY_CASES))
def test_the_pre_debt_authority_is_the_owner_cash_flow_and_the_pre_debt_sale(case: str) -> None:
    """``unlevered_cash_flows[y]`` is the engine's own Unlevered Owner Cash
    Flow, and in the final year that plus Gross Exit Value less Disposition
    Costs -- the cash available to the acquisition loan, bit for bit."""

    terms, results = parity_case(case)
    hold = terms.hold_period
    owner = results.unlevered_owner_cash_flow_by_year
    assert bits(results.unlevered_cash_flows[1:hold]) == bits(owner[: hold - 1])
    sale = owner[hold - 1] + results.exit_value - results.disposition_costs
    assert bits([results.unlevered_cash_flows[hold]]) == bits([sale])


def test_capital_structure_writes_nothing_upstream() -> None:
    terms, results = parity_case("lease-level-plan")
    before = (dataclasses.asdict(terms), dataclasses.asdict(results))
    analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results)
    assert (dataclasses.asdict(terms), dataclasses.asdict(results)) == before


def test_the_empty_structure_is_the_neutral_structure() -> None:
    terms, results = parity_case("quick-plan")
    implicit = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results)
    empty = analyze_unit_capital_structure(
        unit_id="unit-a", terms=terms, results=results, capital_structure=CapitalStructure(positions=())
    )
    assert empty == implicit


# =============================================================================
# Zero debt
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_a_zero_debt_unit_has_no_position_and_keeps_parity(mode: str) -> None:
    terms, results = analyze_unit(mode, business_plan=fx.business_plan(), ltv=0.0)
    assert (results.loan_amount, results.financing_fee, results.remaining_loan_balance) == (0.0, 0.0, 0.0)

    outcome = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results)
    assert outcome.legacy_acquisition_loan is None
    assert outcome.funding_requirements == ()
    assert outcome.status is CapitalStructureStatus.COMPLETE
    assert _parity_holds(outcome.common_equity_cash_flows, results.levered_cash_flows)
    assert adapt_legacy_acquisition_loan(unit_id="unit-a", terms=terms, results=results) is None


def test_a_zero_debt_result_carrying_debt_figures_is_incoherent() -> None:
    terms, results = analyze_unit("quick", ltv=0.0)
    for change in (
        {"financing_fee": 1.0},
        {"remaining_loan_balance": 1.0},
        {"annual_debt_service": (0.0, 1.0, 0.0, 0.0, 0.0)},
    ):
        with pytest.raises(CapitalStructureError, match="no acquisition loan"):
            adapt_legacy_acquisition_loan(unit_id="u", terms=terms, results=dataclasses.replace(results, **change))


# =============================================================================
# The double-counting oracle
# =============================================================================


def test_double_counting_oracle_the_acquisition_loan_is_never_subtracted_twice() -> None:
    """The central P7.7 failure mode, made explicit. Treating today's levered
    cash flow as the cash available to a structure that also carries the
    adapted acquisition loan would subtract the loan's fee, debt service and
    balance a second time. The parity oracle must refuse that series at every
    period, and accept only the existing levered cash flow."""

    terms, results = parity_case("quick-plan")
    hold = terms.hold_period
    assert results.loan_amount > 0.0 and results.financing_fee > 0.0 and results.remaining_loan_balance > 0.0
    assert all(debt_service > 0.0 for debt_service in results.annual_debt_service)

    outcome = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=results)
    loan = outcome.legacy_acquisition_loan
    assert loan is not None
    levered = results.levered_cash_flows
    twice = (
        levered[0] - loan.financing_fee.amount,
        *(levered[t] - loan.annual_debt_service[t - 1] for t in range(1, hold)),
        levered[hold] - loan.annual_debt_service[hold - 1] - loan.remaining_loan_balance,
    )

    assert _parity_holds(outcome.common_equity_cash_flows, levered)
    assert not _parity_holds(twice, levered)
    assert all(a != b for a, b in zip(bits(twice), bits(levered), strict=True))


# =============================================================================
# The result-authority oracle
# =============================================================================


def test_result_authority_oracle_reports_the_result_never_a_recomputation() -> None:
    """A completed result whose loan figures deliberately differ from what the
    terms would recompute to: the adapter reports the result's figures."""

    terms, real = parity_case("detailed-plan")
    hold = terms.hold_period
    synthetic = dataclasses.replace(
        real,
        loan_amount=1_234_567.0,
        financing_fee=4_321.0,
        annual_debt_service=tuple(100_000.0 + year for year in range(hold)),
        remaining_loan_balance=765_432.0,
    )
    naive_loan = terms.purchase_price * terms.ltv
    assert naive_loan != synthetic.loan_amount
    assert naive_loan * terms.financing_fee_pct != synthetic.financing_fee
    assert real.annual_debt_service != synthetic.annual_debt_service

    loan = adapt_legacy_acquisition_loan(unit_id="unit-a", terms=terms, results=synthetic)
    assert loan is not None
    assert (loan.loan_amount, loan.financing_fee.amount, loan.remaining_loan_balance) == (1_234_567.0, 4_321.0, 765_432.0)
    assert loan.funding.amount_rule == FixedAmount(amount=1_234_567.0)
    assert loan.annual_debt_service == synthetic.annual_debt_service

    outcome = analyze_unit_capital_structure(unit_id="unit-a", terms=terms, results=synthetic)
    assert outcome.legacy_acquisition_loan == loan
    assert _parity_holds(outcome.common_equity_cash_flows, synthetic.levered_cash_flows)
    final = outcome.funding_requirements[-1] if outcome.funding_requirements else None
    assert final is None or final.claim_amount != real.annual_debt_service[-1] + real.remaining_loan_balance


def test_result_authority_no_debt_function_is_ever_called(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    public = [
        node.name
        for node in ast.parse((_PROJECT_ROOT / "src/anchor/engine/debt.py").read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]
    assert "calculate_remaining_loan_balance" in public
    unit = parity_case("quick-plan")
    db = tmp_path / "authority.db"
    visible = create_investment(db, quick_deal(db), detailed_deal(db))
    analysis, units = analyze_visible_investment(visible.id, db)

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the legacy adapter must never recompute a debt figure")

    for name in public:
        monkeypatch.setattr(debt_module, name, explode)

    outcome = analyze_unit_capital_structure(unit_id="unit-a", terms=unit[0], results=unit[1])
    assert _parity_holds(outcome.common_equity_cash_flows, unit[1].levered_cash_flows)
    investment = analyze_investment_capital_structure(units=units, consolidated=analysis.consolidated_results)
    assert _parity_holds(investment.common_equity_cash_flows, analysis.consolidated_results.levered_cash_flows)


# =============================================================================
# Identity, payoff and coherence
# =============================================================================


def test_the_legacy_identity_is_reserved_stable_and_never_stored() -> None:
    terms, results = parity_case("quick-io")
    first = adapt_legacy_acquisition_loan(unit_id="abc123", terms=terms, results=results)
    second = adapt_legacy_acquisition_loan(unit_id="abc123", terms=terms, results=results)
    assert first is not None and first == second
    assert first.position_id == legacy_acquisition_loan_id("abc123") == f"{LEGACY_ACQUISITION_LOAN_ID_PREFIX}abc123"
    assert first.funding.event_id.startswith(first.position_id)
    assert first.financing_fee.fee_id.startswith(first.position_id)


def test_the_modeled_payoff_is_labelled_and_no_contract_fact_is_fabricated() -> None:
    fields = {field.name for field in dataclasses.fields(LegacyAcquisitionLoan)}
    assert "modeled_payoff_month" in fields
    assert not fields & {"maturity_month", "current_pay_rate", "pik_rate", "ltv", "financing_fee_pct"}
    assert "not**" in (LegacyAcquisitionLoan.__doc__ or "") and "legal maturity" in (LegacyAcquisitionLoan.__doc__ or "")


def test_incoherent_inputs_are_refused_as_programming_errors() -> None:
    terms, results = parity_case("quick-io")
    for unit_id, bad_terms, bad_results, match in (
        (" ", terms, results, "nonblank unit_id"),
        ("u", dataclasses.replace(terms, hold_period=6), results, "do not span"),
        ("u", terms, dataclasses.replace(results, loan_amount=-1.0), "is not a loan"),
        ("u", terms, dataclasses.replace(results, loan_amount=math.nan), "is not a loan"),
        ("u", results, results, "AcquisitionTerms"),
        ("u", terms, terms, "AcquisitionResults"),
    ):
        with pytest.raises(CapitalStructureError, match=match):
            analyze_unit_capital_structure(unit_id=unit_id, terms=bad_terms, results=bad_results)  # type: ignore[arg-type]
    assert not issubclass(CapitalStructureError, ValueError)


# =============================================================================
# The visible Investment
# =============================================================================


@pytest.fixture(scope="module")
def mixed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """A visible Investment of Quick, Detailed and Lease-Level Units on one hold,
    three with acquisition loans and one all-cash, Unit and Investment Business
    Plans, and an Investment transaction cost."""

    db = tmp_path_factory.mktemp("p7_7_mixed") / "mixed.db"
    quick = quick_deal(db, business_plan=fx.business_plan())
    detailed = detailed_deal(db)
    lease = lease_level_deal(db, business_plan=fx.business_plan())
    all_cash = quick_deal(db, ltv=0.0, name="All-cash Quick")
    visible = create_investment(
        db, lease, all_cash, quick, detailed, business_plan=investment_plan(), costs=(cost("tc-1", 150_000.0),)
    )
    analysis, units = analyze_visible_investment(visible.id, db)
    return {"analysis": analysis, "units": units, "loan_units": sorted([quick.id, detailed.id, lease.id]), "all_cash": all_cash.id}


def test_the_visible_investment_is_realistic(mixed: dict[str, Any]) -> None:
    consolidated = mixed["analysis"].consolidated_results
    assert len(consolidated.unit_ids) == 4
    assert consolidated.investment_transaction_costs == 150_000.0
    assert consolidated.investment_closing_project_capital > 0.0 and any(consolidated.investment_owner_expenses_by_year)
    assert sum(unit.results.loan_amount > 0.0 for unit in mixed["units"]) == 3


def test_visible_investment_parity_bit_for_bit(mixed: dict[str, Any]) -> None:
    consolidated = mixed["analysis"].consolidated_results
    outcome = analyze_investment_capital_structure(units=mixed["units"], consolidated=consolidated)

    assert outcome.status is CapitalStructureStatus.COMPLETE
    assert outcome.common_equity_cash_flows is consolidated.levered_cash_flows
    assert _parity_holds(outcome.common_equity_cash_flows, consolidated.levered_cash_flows)
    assert outcome.unit_ids == consolidated.unit_ids


def test_the_investment_adapts_only_unit_loans_in_canonical_order(mixed: dict[str, Any]) -> None:
    consolidated = mixed["analysis"].consolidated_results
    outcome = analyze_investment_capital_structure(units=mixed["units"], consolidated=consolidated)
    loans = outcome.legacy_acquisition_loans

    assert [loan.scope.unit_id for loan in loans] == mixed["loan_units"]
    assert mixed["all_cash"] not in {loan.scope.unit_id for loan in loans}
    assert all(loan.scope.kind is ScopeKind.UNIT and loan.priority == 1 for loan in loans)
    assert all(loan.position_class is PositionClass.SENIOR_DEBT for loan in loans)
    by_unit = {unit.unit_id: unit for unit in mixed["units"]}
    for loan in loans:
        results = by_unit[loan.scope.unit_id].results
        assert bits([loan.loan_amount, loan.financing_fee.amount, loan.remaining_loan_balance]) == bits(
            [results.loan_amount, results.financing_fee, results.remaining_loan_balance]
        )


def test_each_units_requirements_are_its_own_standalone_requirements(mixed: dict[str, Any]) -> None:
    consolidated = mixed["analysis"].consolidated_results
    outcome = analyze_investment_capital_structure(units=mixed["units"], consolidated=consolidated)
    standalone = tuple(
        requirement
        for unit in mixed["units"]
        for requirement in analyze_unit_capital_structure(unit_id=unit.unit_id, terms=unit.terms, results=unit.results).funding_requirements
    )
    assert outcome.funding_requirements == standalone
    assert [a.unit_id for a in outcome.unit_cash_authorities] == list(consolidated.unit_ids)


def test_the_investment_authority_is_downstream_of_every_unit_loan(mixed: dict[str, Any]) -> None:
    consolidated = mixed["analysis"].consolidated_results
    authority = analyze_investment_capital_structure(units=mixed["units"], consolidated=consolidated).investment_cash_authority
    assert authority.cash_flows_after_unit_positions is consolidated.levered_cash_flows
    assert authority.owner_cash_flow_after_unit_positions_by_year is consolidated.levered_owner_cash_flow_by_year
    assert authority.net_sale_proceeds_after_unit_positions == consolidated.net_sale_proceeds
    assert not any("unlevered" in field.name for field in dataclasses.fields(authority))
    assert not _parity_holds(consolidated.unlevered_cash_flows, authority.cash_flows_after_unit_positions)


def test_unit_order_never_changes_the_investment_result(mixed: dict[str, Any]) -> None:
    consolidated = mixed["analysis"].consolidated_results
    forward = analyze_investment_capital_structure(units=mixed["units"], consolidated=consolidated)
    backward = analyze_investment_capital_structure(units=tuple(reversed(mixed["units"])), consolidated=consolidated)
    assert forward == backward


def test_the_units_must_be_the_ones_consolidated(mixed: dict[str, Any]) -> None:
    consolidated = mixed["analysis"].consolidated_results
    units: tuple[CapitalStructureUnit, ...] = mixed["units"]
    for bad, match in (
        (units[1:], "not the Units consolidated"),
        ((*units, units[0]), "more than once"),
        ((dataclasses.replace(units[0], terms=dataclasses.replace(units[0].terms, hold_period=6)), *units[1:]), "holds for 6"),
        (("not a unit",), "Not a CapitalStructureUnit"),
    ):
        with pytest.raises(CapitalStructureError, match=match):
            analyze_investment_capital_structure(units=bad, consolidated=consolidated)  # type: ignore[arg-type]


def test_a_zero_debt_investment_has_no_position_and_keeps_parity(tmp_path: Path) -> None:
    db = tmp_path / "all_cash.db"
    visible = create_investment(
        db,
        quick_deal(db, ltv=0.0, business_plan=fx.business_plan()),
        detailed_deal(db, ltv=0.0),
        lease_level_deal(db, ltv=0.0),
        business_plan=investment_plan(),
    )
    analysis, units = analyze_visible_investment(visible.id, db)
    consolidated = analysis.consolidated_results
    assert consolidated.loan_amount == 0.0

    outcome = analyze_investment_capital_structure(units=units, consolidated=consolidated)
    assert outcome.legacy_acquisition_loans == ()
    assert outcome.funding_requirements == ()
    assert _parity_holds(outcome.common_equity_cash_flows, consolidated.levered_cash_flows)
