"""Phase 7 Gate P7.4 -- Strategy resolution and its composition with the P7.1
Scenario engine.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 7.1, 7.4
(ST-2, ST-3, ST-6) and 7.6, and the Section 21.2 ratification: Base -> Strategy
-> Scenario -> validation -> the existing engine, with every relative Scenario
operation acting on the Strategy-resolved value.

Every golden variant is measured against an independent oracle: the ordinary
D6 entry point run on contracts typed by hand with the resolved assumptions.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import pytest

from anchor.analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.analysis import strategy as strategy_module
from anchor.analysis.scenario import (
    ScenarioDefinition,
    ScenarioIssueCode,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    ScenarioValidationError,
)
from anchor.analysis.strategy import (
    StrategyDomain,
    StrategyIssueCode,
    StrategyIssueStage,
    StrategyValidationError,
    analyze_detailed_acquisition_with_strategy,
    analyze_lease_level_acquisition_with_strategy,
    analyze_quick_acquisition_with_strategy,
    resolve_detailed_strategy,
    resolve_detailed_variant,
    resolve_lease_level_strategy,
    resolve_lease_level_variant,
    resolve_quick_strategy,
    resolve_quick_variant,
)
from anchor.business_plan import BusinessPlan

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
import _p7_4_fixtures as f4  # type: ignore[import-not-found]

UNIT = fx.UNIT


def _scenario(*overrides: tuple[str, str, float]) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id="scenario-1",
        name="Downside",
        overrides=tuple(
            ScenarioOverride(unit_id=UNIT, target=ScenarioTarget(t), operation=ScenarioOperation(o), value=v)
            for t, o, v in overrides
        ),
    )


# =============================================================================
# QUICK -- the golden variant
# =============================================================================

QUICK_BASE = fx.quick_inputs(
    purchase_price=10_000_000.0, ltv=0.65, exit_cap_rate=0.065, noi_growth=0.03, hold_period=5
)
QUICK_STRATEGY = f4.strategy(
    f4.acquisition(UNIT, purchase_price=9_500_000.0, acquisition_cost_pct=0.02),
    f4.financing(UNIT, ltv=0.60, interest_rate=0.0575, amortization=30, io_period=2, financing_fee_pct=0.01),
    f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.06), f4.outcome("noi_growth", 0.04)),
    f4.disposition(UNIT, 7),
)
QUICK_SCENARIO = _scenario(("exit_cap_rate", "add", 0.005), ("ltv", "cap_at", 0.55), ("noi_growth", "add", -0.01))


def _quick_variant(scenario: ScenarioDefinition | None = QUICK_SCENARIO, plan: BusinessPlan = BusinessPlan()):
    return resolve_quick_variant(QUICK_BASE, unit_id=UNIT, strategy=QUICK_STRATEGY, scenario=scenario, business_plan=plan)


def test_quick_golden_final_values_are_strategy_first_then_scenario() -> None:
    resolved = _quick_variant().inputs

    assert resolved.purchase_price == 9_500_000.0
    assert resolved.ltv == 0.55
    assert resolved.exit_cap_rate == 0.06 + 0.005
    assert resolved.noi_growth == 0.04 + -0.01
    assert resolved.hold_period == 7
    # Relative operations acted on the strategy's values, never on Base's:
    assert resolved.exit_cap_rate != QUICK_BASE.exit_cap_rate + 0.005
    assert resolved.noi_growth != QUICK_BASE.noi_growth + -0.01
    # Everything no overlay and no override names is Base, exactly.
    untouched = ("current_noi", "occupancy", "disposition_cost_pct", "annual_capex_reserve")
    assert {f: getattr(resolved, f) for f in untouched} == {f: getattr(QUICK_BASE, f) for f in untouched}


def test_quick_strategy_by_base_scenario_is_the_strategy_world() -> None:
    resolved = _quick_variant(scenario=None).inputs
    assert (resolved.purchase_price, resolved.ltv, resolved.exit_cap_rate, resolved.noi_growth, resolved.hold_period) == (
        9_500_000.0, 0.60, 0.06, 0.04, 7,
    )
    assert resolved == resolve_quick_strategy(
        QUICK_BASE, unit_id=UNIT, strategy=QUICK_STRATEGY, business_plan=BusinessPlan()
    ).inputs


def test_quick_golden_analysis_is_the_ordinary_engine_on_hand_typed_inputs() -> None:
    manual = dataclasses.replace(
        QUICK_BASE, purchase_price=9_500_000.0, ltv=0.55, exit_cap_rate=0.06 + 0.005,
        noi_growth=0.04 + -0.01, hold_period=7,
    )
    analysed = analyze_quick_acquisition_with_strategy(
        QUICK_BASE, unit_id=UNIT, strategy=QUICK_STRATEGY, scenario=QUICK_SCENARIO, business_plan=fx.business_plan()
    )
    assert analysed == analyze_quick_acquisition_with_business_plan(manual, business_plan=fx.business_plan())


@pytest.mark.parametrize(("cap", "expected"), [(0.55, 0.55), (0.70, 0.60), (0.60, 0.60)])
def test_a_lender_cap_applies_to_the_strategys_leverage_and_can_never_raise_it(cap: float, expected: float) -> None:
    resolved = _quick_variant(scenario=_scenario(("ltv", "cap_at", cap))).inputs
    assert resolved.ltv == expected


def test_the_p7_1_resolver_receives_the_strategy_resolved_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    real = strategy_module.resolve_quick_scenario

    def spy(inputs: Any, **kwargs: Any) -> Any:
        seen.append((inputs, kwargs["business_plan"]))
        return real(inputs, **kwargs)

    monkeypatch.setattr(strategy_module, "resolve_quick_scenario", spy)
    plan = f4.renovation_plan()
    strategy = f4.strategy(*QUICK_STRATEGY.overlays, f4.plan_overlay(UNIT, plan))
    resolve_quick_variant(QUICK_BASE, unit_id=UNIT, strategy=strategy, scenario=QUICK_SCENARIO, business_plan=fx.business_plan())

    ((inputs, carried_plan),) = seen
    assert (inputs.purchase_price, inputs.ltv, inputs.exit_cap_rate, inputs.hold_period) == (9_500_000.0, 0.60, 0.06, 7)
    assert carried_plan is plan


def test_a_scenario_set_erases_the_strategy_difference_on_that_target() -> None:
    """SC-3: SET states an absolute market fact, so it replaces the strategy's
    value too."""

    assert _quick_variant(scenario=_scenario(("exit_cap_rate", "set", 0.0725))).inputs.exit_cap_rate == 0.0725


def test_purchase_price_and_hold_are_strategy_only() -> None:
    assert "purchase_price" not in {t.value for t in ScenarioTarget}
    assert "hold_period" not in {t.value for t in ScenarioTarget}
    resolved = _quick_variant(scenario=_scenario(("exit_cap_rate", "add", 0.0075))).inputs
    assert (resolved.hold_period, resolved.exit_cap_rate) == (7, 0.06 + 0.0075)


# =============================================================================
# DETAILED -- every domain, then a Scenario
# =============================================================================

DETAILED_STRATEGY = f4.strategy(
    f4.acquisition(UNIT, purchase_price=16_500_000.0, acquisition_cost_pct=0.015),
    f4.financing(UNIT, ltv=0.55, interest_rate=0.0625, amortization=25, io_period=0, financing_fee_pct=0.0075),
    f4.plan_overlay(UNIT, f4.renovation_plan()),
    f4.outcomes(
        UNIT,
        f4.outcome("expense_growth", 0.03),
        f4.outcome("exit_cap_rate", 0.06),
        f4.outcome("vacancy_credit_loss_pct", 0.04),
        f4.outcome("revenue_growth", 0.04),
    ),
    f4.disposition(UNIT, 5),
)
DETAILED_SCENARIO = _scenario(
    ("exit_cap_rate", "add", 0.0075),
    ("interest_rate", "add", 0.005),
    ("ltv", "cap_at", 0.50),
    ("revenue_growth", "add", -0.01),
    ("vacancy_credit_loss_pct", "add", 0.02),
    ("expense_growth", "set", 0.035),
)


def _detailed_variant(scenario: ScenarioDefinition | None = DETAILED_SCENARIO):
    return resolve_detailed_variant(
        fx.detailed_terms(), fx.detailed_operating(), unit_id=UNIT,
        strategy=DETAILED_STRATEGY, scenario=scenario, business_plan=fx.business_plan(),
    )


def test_detailed_golden_every_domain_then_the_scenario() -> None:
    resolved = _detailed_variant()
    terms, operating = resolved.terms, resolved.detailed_operating_inputs

    assert (terms.purchase_price, terms.acquisition_cost_pct) == (16_500_000.0, 0.015)
    assert (terms.amortization, terms.io_period, terms.financing_fee_pct) == (25, 0, 0.0075)
    assert terms.interest_rate == 0.0625 + 0.005
    assert terms.ltv == 0.50
    assert terms.exit_cap_rate == 0.06 + 0.0075
    assert terms.hold_period == 5
    assert operating.revenue_growth == 0.04 + -0.01
    assert operating.vacancy_credit_loss_pct == 0.04 + 0.02
    assert operating.expense_growth == 0.035
    assert resolved.business_plan == f4.renovation_plan()
    # Strategy first: the scenario never saw Base's vacancy or growth.
    assert operating.vacancy_credit_loss_pct != fx.detailed_operating().vacancy_credit_loss_pct + 0.02
    assert operating.revenue_growth != fx.detailed_operating().revenue_growth + -0.01
    base_terms = fx.detailed_terms()
    assert (terms.disposition_cost_pct, terms.annual_capex_reserve) == (
        base_terms.disposition_cost_pct, base_terms.annual_capex_reserve,
    )
    assert operating.gross_potential_rent == fx.detailed_operating().gross_potential_rent


def test_detailed_golden_analysis_is_the_ordinary_engine_on_hand_typed_inputs() -> None:
    terms = fx.detailed_terms(
        purchase_price=16_500_000.0, acquisition_cost_pct=0.015, ltv=0.50, interest_rate=0.0625 + 0.005,
        amortization=25, io_period=0, financing_fee_pct=0.0075, exit_cap_rate=0.06 + 0.0075, hold_period=5,
    )
    operating = fx.detailed_operating(
        revenue_growth=0.04 + -0.01, vacancy_credit_loss_pct=0.04 + 0.02, expense_growth=0.035
    )
    analysed = analyze_detailed_acquisition_with_strategy(
        fx.detailed_terms(), fx.detailed_operating(), unit_id=UNIT,
        strategy=DETAILED_STRATEGY, scenario=DETAILED_SCENARIO, business_plan=fx.business_plan(),
    )
    assert analysed == analyze_detailed_acquisition_with_business_plan(
        terms, operating, business_plan=f4.renovation_plan()
    )


def test_detailed_strategy_by_base_is_the_strategy_world() -> None:
    resolved = _detailed_variant(scenario=None)
    assert resolved == resolve_detailed_strategy(
        fx.detailed_terms(), fx.detailed_operating(), unit_id=UNIT,
        strategy=DETAILED_STRATEGY, business_plan=fx.business_plan(),
    )
    assert (resolved.terms.ltv, resolved.terms.exit_cap_rate, resolved.detailed_operating_inputs.vacancy_credit_loss_pct) == (
        0.55, 0.06, 0.04,
    )


# =============================================================================
# LEASE-LEVEL -- the Strategy world across suite overrides, then the Scenario
# =============================================================================


def _ll_contracts(**rent_roll: Any) -> dict[str, Any]:
    suites, leases = fx.rent_roll(**({"b_market_rent_psf": 40.0} | rent_roll))
    return {
        "terms": fx.lease_level_terms(),
        "property_inputs": fx.lease_level_property(),
        "suites": tuple(suites),
        "leases": tuple(leases),
        "market_leasing": fx.market(market_rent_psf=35.0),
        "operating_inputs": fx.lease_level_operating(),
    }


LL_STRATEGY = f4.strategy(
    f4.outcomes(
        UNIT,
        f4.outcome("market_rent_psf", 45.0),
        f4.outcome("renewal_probability", 0.75),
        f4.outcome("expense_growth", 0.035),
    )
)
LL_SCENARIO = _scenario(
    ("market_rent_psf", "scale", 0.90), ("renewal_probability", "add", -0.10), ("expense_growth", "add", 0.01)
)


def _ll_variant(contracts: dict[str, Any], strategy: Any = LL_STRATEGY, scenario: Any = LL_SCENARIO, plan: BusinessPlan = BusinessPlan()):
    return resolve_lease_level_variant(
        contracts["terms"], contracts["property_inputs"], contracts["suites"], contracts["leases"],
        market_leasing=contracts["market_leasing"], operating_inputs=contracts["operating_inputs"],
        unit_id=UNIT, strategy=strategy, scenario=scenario, business_plan=plan,
    )


def test_lease_level_golden_strategy_establishes_the_world_and_the_scenario_applies_to_it() -> None:
    contracts = _ll_contracts()
    suites_before = copy.deepcopy(contracts["suites"])

    resolved = _ll_variant(contracts)
    suite_b = next(s for s in resolved.suites if s.suite_id == "B")

    assert resolved.market_leasing.market_rent_psf == 45.0 * 0.90 == 40.5
    assert suite_b.market_rent_psf == 45.0 * 0.90
    assert resolved.market_leasing.renewal_probability == 0.75 + -0.10
    assert resolved.operating_inputs.expense_growth == 0.035 + 0.01
    # Applied to Base instead, the scale would have given 31.50 and 36.00.
    assert resolved.market_leasing.market_rent_psf != 35.0 * 0.90
    assert suite_b.market_rent_psf != 40.0 * 0.90
    # Base suites are never mutated.
    assert contracts["suites"] == suites_before
    assert next(s for s in contracts["suites"] if s.suite_id == "B").market_rent_psf == 40.0


def test_lease_level_strategy_set_reaches_every_stated_suite_level() -> None:
    contracts = _ll_contracts(c_override=fx.market(market_rent_psf=38.0), d_market_rent_psf=33.0)
    strategy = f4.strategy(f4.outcomes(UNIT, f4.outcome("market_rent_psf", 45.0)))
    resolved = _ll_variant(contracts, strategy=strategy, scenario=None)

    by_id = {suite.suite_id: suite for suite in resolved.suites}
    assert resolved.market_leasing.market_rent_psf == 45.0
    assert by_id["B"].market_rent_psf == 45.0
    assert by_id["C"].market_leasing_override is not None and by_id["C"].market_leasing_override.market_rent_psf == 45.0
    assert by_id["D"].market_rent_psf == 45.0
    assert by_id["A"].market_rent_psf is None and by_id["A"].market_leasing_override is None
    assert resolved.market_leasing.renewal_probability == contracts["market_leasing"].renewal_probability


def test_lease_level_golden_analysis_is_the_ordinary_engine_on_hand_typed_inputs() -> None:
    contracts = _ll_contracts()
    manual_rent = 45.0 * 0.90
    manual_suites = tuple(
        dataclasses.replace(suite, market_rent_psf=manual_rent) if suite.market_rent_psf is not None else suite
        for suite in contracts["suites"]
    )
    manual_market = dataclasses.replace(contracts["market_leasing"], market_rent_psf=manual_rent, renewal_probability=0.75 + -0.10)
    manual_operating = dataclasses.replace(contracts["operating_inputs"], expense_growth=0.035 + 0.01)

    analysed = analyze_lease_level_acquisition_with_strategy(
        contracts["terms"], contracts["property_inputs"], contracts["suites"], contracts["leases"],
        market_leasing=contracts["market_leasing"], operating_inputs=contracts["operating_inputs"],
        unit_id=UNIT, strategy=LL_STRATEGY, scenario=LL_SCENARIO, business_plan=fx.business_plan(),
    )
    assert analysed == analyze_lease_level_acquisition_with_business_plan(
        contracts["terms"], contracts["property_inputs"], manual_suites, contracts["leases"],
        market_leasing=manual_market, operating_inputs=manual_operating, business_plan=fx.business_plan(),
    )


def test_lease_level_every_domain_resolves_into_the_existing_contracts() -> None:
    contracts = _ll_contracts()
    strategy = f4.strategy(
        f4.acquisition(UNIT, purchase_price=37_000_000.0, acquisition_cost_pct=0.02),
        f4.financing(UNIT, ltv=0.50, interest_rate=0.06, amortization=25, io_period=1, financing_fee_pct=0.01),
        f4.plan_overlay(UNIT, f4.renovation_plan()),
        f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.0625), f4.outcome("recoverable_expense_ratio", 0.85)),
        f4.disposition(UNIT, 7),
    )
    resolved = _ll_variant(contracts, strategy=strategy, scenario=_scenario(("exit_cap_rate", "add", 0.005)))
    assert (resolved.terms.purchase_price, resolved.terms.ltv, resolved.terms.hold_period) == (37_000_000.0, 0.50, 7)
    assert resolved.terms.exit_cap_rate == 0.0625 + 0.005
    assert resolved.operating_inputs.recoverable_expense_ratio == 0.85
    assert resolved.business_plan == f4.renovation_plan()
    assert resolved.suites == contracts["suites"] and resolved.leases == contracts["leases"]


def test_a_shadowed_renewal_outcome_is_refused_rather_than_partly_applied() -> None:
    contracts = _ll_contracts(c_override=fx.market(market_rent_psf=38.0))
    with pytest.raises(StrategyValidationError) as caught:
        _ll_variant(contracts, scenario=None)
    (issue,) = caught.value.issues
    assert (issue.code, issue.target) == (
        StrategyIssueCode.TARGET_SHADOWED_BY_SUITE_OVERRIDE, ScenarioTarget.RENEWAL_PROBABILITY,
    )
    assert "C" in issue.message


# =============================================================================
# ST-6 -- no inferred causality between the plan and the operating outcome
# =============================================================================


def _quick_strategy_world(*overlays: Any):
    return resolve_quick_strategy(
        QUICK_BASE, unit_id=UNIT, strategy=f4.strategy(*overlays), business_plan=fx.business_plan()
    )


def test_a_renovation_alone_moves_no_operating_assumption() -> None:
    renovation = f4.plan_overlay(UNIT, f4.renovation_plan())
    outcome = f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.06), f4.outcome("noi_growth", 0.04))

    a = _quick_strategy_world(renovation)
    b = _quick_strategy_world(renovation, outcome)

    assert a.inputs is QUICK_BASE
    assert a.business_plan == b.business_plan == f4.renovation_plan()
    assert (b.inputs.exit_cap_rate, b.inputs.noi_growth) == (0.06, 0.04)
    assert (a.inputs.exit_cap_rate, a.inputs.noi_growth) == (QUICK_BASE.exit_cap_rate, QUICK_BASE.noi_growth)


def test_removing_either_overlay_leaves_the_other_exactly_as_it_was() -> None:
    renovation = f4.plan_overlay(UNIT, f4.renovation_plan())
    outcome = f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.06), f4.outcome("noi_growth", 0.04))
    both = _quick_strategy_world(renovation, outcome)

    without_plan = _quick_strategy_world(outcome)
    assert without_plan.inputs == both.inputs
    assert without_plan.business_plan == fx.business_plan()

    without_outcome = _quick_strategy_world(renovation)
    assert without_outcome.business_plan == both.business_plan
    assert without_outcome.inputs == QUICK_BASE


def test_the_size_of_the_plan_never_reaches_an_operating_value() -> None:
    small = BusinessPlan()
    large = f4.renovation_plan()
    outcome = f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.06), f4.outcome("noi_growth", 0.04))
    for mode_inputs in (
        _quick_strategy_world(f4.plan_overlay(UNIT, small), outcome),
        _quick_strategy_world(f4.plan_overlay(UNIT, large), outcome),
    ):
        assert (mode_inputs.inputs.exit_cap_rate, mode_inputs.inputs.noi_growth) == (0.06, 0.04)

    contracts = _ll_contracts()
    rent = f4.outcomes(UNIT, f4.outcome("market_rent_psf", 42.0))
    worlds = [
        resolve_lease_level_strategy(
            contracts["terms"], contracts["property_inputs"], contracts["suites"], contracts["leases"],
            market_leasing=contracts["market_leasing"], operating_inputs=contracts["operating_inputs"],
            unit_id=UNIT, strategy=f4.strategy(f4.plan_overlay(UNIT, plan), rent), business_plan=fx.business_plan(),
        )
        for plan in (small, large)
    ]
    assert worlds[0].market_leasing == worlds[1].market_leasing
    assert worlds[0].suites == worlds[1].suites
    no_rent = resolve_lease_level_strategy(
        contracts["terms"], contracts["property_inputs"], contracts["suites"], contracts["leases"],
        market_leasing=contracts["market_leasing"], operating_inputs=contracts["operating_inputs"],
        unit_id=UNIT, strategy=f4.strategy(f4.plan_overlay(UNIT, large)), business_plan=fx.business_plan(),
    )
    assert no_rent.market_leasing is contracts["market_leasing"] and no_rent.suites == contracts["suites"]


# =============================================================================
# BUSINESS_PLAN -- absent vs explicit empty replacement
# =============================================================================


def test_no_plan_overlay_keeps_base_and_an_empty_overlay_replaces_it() -> None:
    base_plan = fx.business_plan()
    kept = resolve_quick_strategy(QUICK_BASE, unit_id=UNIT, strategy=f4.strategy(), business_plan=base_plan)
    emptied = resolve_quick_strategy(
        QUICK_BASE, unit_id=UNIT, strategy=f4.strategy(f4.plan_overlay(UNIT, BusinessPlan())), business_plan=base_plan
    )
    assert kept.business_plan is base_plan
    assert emptied.business_plan == BusinessPlan()
    assert emptied.business_plan != base_plan
    assert analyze_quick_acquisition_with_strategy(
        QUICK_BASE, unit_id=UNIT, strategy=f4.strategy(f4.plan_overlay(UNIT, BusinessPlan())),
        scenario=None, business_plan=base_plan,
    ) == analyze_quick_acquisition_with_business_plan(QUICK_BASE, business_plan=BusinessPlan())


def test_a_scenario_after_a_plan_replacement_keeps_the_replacement() -> None:
    plan = f4.renovation_plan()
    resolved = resolve_quick_variant(
        QUICK_BASE, unit_id=UNIT, strategy=f4.strategy(f4.plan_overlay(UNIT, plan)),
        scenario=_scenario(("exit_cap_rate", "add", 0.005)), business_plan=fx.business_plan(),
    )
    assert resolved.business_plan is plan


# =============================================================================
# Whole-domain, no mutation, no inheritance
# =============================================================================


@pytest.mark.parametrize(
    "overlay",
    [
        f4.acquisition(UNIT, acquisition_cost_pct=None),
        f4.financing(UNIT, amortization=None),
        f4.disposition(UNIT, None),
    ],
    ids=["acquisition", "financing", "disposition"],
)
def test_a_partial_domain_is_refused_before_anything_resolves(overlay: Any) -> None:
    with pytest.raises(StrategyValidationError) as caught:
        resolve_quick_variant(
            QUICK_BASE, unit_id=UNIT, strategy=f4.strategy(overlay), scenario=None, business_plan=BusinessPlan()
        )
    assert [issue.code for issue in caught.value.issues] == [StrategyIssueCode.INCOMPLETE_DOMAIN]


def test_resolution_mutates_nothing_it_was_given() -> None:
    contracts = _ll_contracts(c_override=fx.market(market_rent_psf=38.0))
    strategy = f4.strategy(
        f4.acquisition(UNIT), f4.financing(UNIT), f4.plan_overlay(UNIT, f4.renovation_plan()),
        f4.outcomes(UNIT, f4.outcome("market_rent_psf", 45.0)), f4.disposition(UNIT, 7),
    )
    plan = fx.business_plan()
    snapshot = copy.deepcopy((contracts, strategy, plan))
    _ll_variant(contracts, strategy=strategy, scenario=_scenario(("market_rent_psf", "scale", 0.9)), plan=plan)
    assert (contracts, strategy, plan) == snapshot


def test_overlay_order_never_changes_the_resolution() -> None:
    reversed_strategy = f4.strategy(*reversed(QUICK_STRATEGY.overlays))
    assert resolve_quick_variant(
        QUICK_BASE, unit_id=UNIT, strategy=reversed_strategy, scenario=QUICK_SCENARIO, business_plan=BusinessPlan()
    ) == _quick_variant()


# =============================================================================
# Validation -- the final inputs only, by the existing validators
# =============================================================================


def test_a_strategy_value_that_makes_the_final_inputs_invalid_is_an_invalid_variant() -> None:
    with pytest.raises(StrategyValidationError) as caught:
        resolve_quick_variant(
            QUICK_BASE, unit_id=UNIT, strategy=f4.strategy(f4.acquisition(UNIT, purchase_price=-1.0)),
            scenario=None, business_plan=BusinessPlan(),
        )
    (issue,) = caught.value.issues
    assert (issue.stage, issue.code, issue.domain, issue.field) == (
        StrategyIssueStage.RESOLVED_INPUTS, StrategyIssueCode.RESOLVED_INPUT_INVALID,
        StrategyDomain.ACQUISITION, "purchase_price",
    )
    assert issue.source_code == "out_of_domain_value"


def test_only_final_inputs_are_validated_never_the_strategy_intermediate() -> None:
    """A Strategy vacancy of 120% is not valid underwriting on its own, but a
    Scenario that brings the final value to 70% is a valid variant: validation
    is of what runs, never of an intermediate."""

    strategy = f4.strategy(f4.outcomes(UNIT, f4.outcome("vacancy_credit_loss_pct", 1.2)))
    with pytest.raises(StrategyValidationError):
        resolve_detailed_variant(
            fx.detailed_terms(), fx.detailed_operating(), unit_id=UNIT, strategy=strategy,
            scenario=None, business_plan=BusinessPlan(),
        )
    rescued = resolve_detailed_variant(
        fx.detailed_terms(), fx.detailed_operating(), unit_id=UNIT, strategy=strategy,
        scenario=_scenario(("vacancy_credit_loss_pct", "add", -0.5)), business_plan=BusinessPlan(),
    )
    assert rescued.detailed_operating_inputs.vacancy_credit_loss_pct == 1.2 + -0.5


def test_a_scenario_that_breaks_the_strategy_world_is_refused_by_the_p7_1_validator() -> None:
    contracts = _ll_contracts()
    strategy = f4.strategy(f4.outcomes(UNIT, f4.outcome("renewal_probability", 0.95)))
    with pytest.raises(ScenarioValidationError) as caught:
        _ll_variant(contracts, strategy=strategy, scenario=_scenario(("renewal_probability", "add", 0.10)))
    assert {issue.code for issue in caught.value.issues} == {ScenarioIssueCode.RESOLVED_INPUT_INVALID}


def test_a_hold_change_revalidates_the_rent_roll_against_the_new_hold() -> None:
    contracts = _ll_contracts()
    resolved = _ll_variant(contracts, strategy=f4.strategy(f4.disposition(UNIT, 8)), scenario=None)
    assert resolved.terms.hold_period == 8
    analysed = analyze_lease_level_acquisition_with_strategy(
        contracts["terms"], contracts["property_inputs"], contracts["suites"], contracts["leases"],
        market_leasing=contracts["market_leasing"], operating_inputs=contracts["operating_inputs"],
        unit_id=UNIT, strategy=f4.strategy(f4.disposition(UNIT, 8)), scenario=None, business_plan=BusinessPlan(),
    )
    assert len(analysed.results.levered_cash_flows) == 8 + 1


def test_a_scenario_on_a_foreign_unit_is_still_refused_after_a_strategy() -> None:
    foreign = ScenarioDefinition(
        scenario_id="s", name="n",
        overrides=(ScenarioOverride(unit_id="zzz-other", target=ScenarioTarget.EXIT_CAP_RATE, operation=ScenarioOperation.ADD, value=0.01),),
    )
    with pytest.raises(ScenarioValidationError) as caught:
        _quick_variant(scenario=foreign)
    assert [issue.code for issue in caught.value.issues] == [ScenarioIssueCode.UNIT_NOT_IN_VARIANT]


def test_an_empty_strategy_resolves_to_the_callers_own_objects() -> None:
    plan = fx.business_plan()
    resolved = resolve_quick_variant(QUICK_BASE, unit_id=UNIT, strategy=f4.strategy(), scenario=None, business_plan=plan)
    assert resolved.inputs is QUICK_BASE and resolved.business_plan is plan
