"""Phase 7 Gate P7.1 -- resolution: operations, identity, and invalid scenarios.

The claims that would fail silently if wrong:

- a scenario result is **bit-identical** to an ordinary analysis of the same
  assumptions entered by hand (Parts U, V), in every mode;
- CAP_AT is ``min``, never ``max`` (Part W);
- override order, names and descriptions never move a number (Parts M, Q);
- nothing is mutated, and the Business Plan rides through untouched (K, S);
- no overrides means the caller's own objects and today's results (P, AE);
- an invalid scenario raises with the existing validator's reason, is never
  clipped, and never reaches the engine (N, O, Y).
"""

from __future__ import annotations

import copy
import itertools
import math

import pytest

from anchor.analysis import scenario as module
from anchor.analysis.business_plan_analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.analysis.lease_level import analyze_lease_level_acquisition_with_projection
from anchor.analysis.scenario import (
    ScenarioDefinition,
    ScenarioIssueCode,
    ScenarioIssueStage,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    ScenarioValidationError,
    analyze_detailed_acquisition_with_scenario,
    analyze_lease_level_acquisition_with_scenario,
    analyze_quick_acquisition_with_scenario,
    resolve_detailed_scenario,
    resolve_lease_level_scenario,
    resolve_quick_scenario,
)
from anchor.business_plan import BusinessPlan
from anchor.engine import analyze_acquisition, analyze_detailed_acquisition_with_projection
from anchor.leasing import LeaseIssueCode, Suite

from _p7_1_scenario_fixtures import (
    UNIT,
    business_plan,
    detailed_operating,
    detailed_terms,
    lease_level_operating,
    lease_level_property,
    lease_level_terms,
    market,
    quick_inputs,
    rent_roll,
)

T = ScenarioTarget
Op = ScenarioOperation


def ov(target: ScenarioTarget, operation: ScenarioOperation, value: float) -> ScenarioOverride:
    return ScenarioOverride(unit_id=UNIT, target=target, operation=operation, value=value)


def scenario(*overrides: ScenarioOverride, scenario_id: str = "scn", name: str = "View",
             description: str | None = None) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id=scenario_id, name=name, description=description, overrides=tuple(overrides)
    )


def identical(left: object, right: object) -> bool:
    """Bit identity: ``==`` plus ``repr``, which shows the last float bit and
    the sign of zero."""

    return left == right and repr(left) == repr(right)


# --- one runner per mode, so every test states only its scenario -----------


def run_quick(definition: ScenarioDefinition, plan: BusinessPlan | None = None):  # type: ignore[no-untyped-def]
    return analyze_quick_acquisition_with_scenario(
        quick_inputs(), unit_id=UNIT, scenario=definition, business_plan=plan or business_plan()
    )


def run_detailed(definition: ScenarioDefinition, plan: BusinessPlan | None = None):  # type: ignore[no-untyped-def]
    return analyze_detailed_acquisition_with_scenario(
        detailed_terms(), detailed_operating(), unit_id=UNIT, scenario=definition,
        business_plan=plan or business_plan(),
    )


def resolve_lease_level(definition: ScenarioDefinition, suites=None, leases=None, mkt=None):  # type: ignore[no-untyped-def]
    default_suites, default_leases = rent_roll()
    return resolve_lease_level_scenario(
        lease_level_terms(),
        lease_level_property(),
        suites if suites is not None else default_suites,
        leases if leases is not None else default_leases,
        market_leasing=mkt or market(),
        operating_inputs=lease_level_operating(),
        unit_id=UNIT, scenario=definition,
        business_plan=business_plan(),
    )


def run_lease_level(definition: ScenarioDefinition):  # type: ignore[no-untyped-def]
    suites, leases = rent_roll()
    return analyze_lease_level_acquisition_with_scenario(
        lease_level_terms(),
        lease_level_property(),
        suites,
        leases,
        market_leasing=market(),
        operating_inputs=lease_level_operating(),
        unit_id=UNIT, scenario=definition,
        business_plan=business_plan(),
    )


# =============================================================================
# Operation semantics (Parts C, D)
# =============================================================================


def test_the_four_operations_have_exactly_the_ratified_semantics() -> None:
    apply = module._apply_operation
    assert apply(Op.SET, 0.0625, 0.07) == 0.07
    assert apply(Op.ADD, 0.0625, 0.005) == 0.0625 + 0.005
    assert apply(Op.SCALE, 0.0625, 1.1) == 0.0625 * 1.1
    assert apply(Op.CAP_AT, 0.65, 0.55) == 0.55
    assert apply(Op.CAP_AT, 0.50, 0.55) == 0.50
    assert apply(Op.CAP_AT, 0.55, 0.55) == 0.55
    assert apply(Op.ADD, 0.03, -0.015) == 0.03 - 0.015
    for operation in ScenarioOperation:
        assert type(apply(operation, 1, 2)) is float


def test_set_add_and_scale_resolve_through_the_public_resolver() -> None:
    base = quick_inputs()
    for operation, value, expected in (
        (Op.SET, 0.07, 0.07),
        (Op.ADD, 0.005, base.exit_cap_rate + 0.005),
        (Op.SCALE, 1.10, base.exit_cap_rate * 1.10),
    ):
        resolved = resolve_quick_scenario(
            base, unit_id=UNIT, scenario=scenario(ov(T.EXIT_CAP_RATE, operation, value)),
            business_plan=BusinessPlan(),
        )
        assert resolved.inputs.exit_cap_rate == expected
    resolved = resolve_quick_scenario(
        base, unit_id=UNIT, scenario=scenario(ov(T.INTEREST_RATE, Op.ADD, 0.005)), business_plan=BusinessPlan()
    )
    assert resolved.inputs.interest_rate == 0.0575 + 0.005  # +50 bps, in internal units


def test_an_integer_value_resolves_to_the_same_float_assumption() -> None:
    as_int = resolve_lease_level(scenario(ov(T.MARKET_RENT_PSF, Op.SET, 40)))
    as_float = resolve_lease_level(scenario(ov(T.MARKET_RENT_PSF, Op.SET, 40.0)))
    assert identical(as_int, as_float)
    assert type(as_int.market_leasing.market_rent_psf) is float


# =============================================================================
# The CAP_AT oracle (Part W)
# =============================================================================


@pytest.mark.parametrize(("base_ltv", "expected"), [(0.65, 0.55), (0.50, 0.50), (0.55, 0.55)])
def test_ltv_cap_at_never_raises_the_current_value_in_any_mode(base_ltv: float, expected: float) -> None:
    capped = scenario(ov(T.LTV, Op.CAP_AT, 0.55))
    quick = resolve_quick_scenario(
        quick_inputs(ltv=base_ltv), unit_id=UNIT, scenario=capped, business_plan=BusinessPlan()
    )
    detailed = resolve_detailed_scenario(
        detailed_terms(ltv=base_ltv), detailed_operating(), unit_id=UNIT, scenario=capped,
        business_plan=BusinessPlan(),
    )
    suites, leases = rent_roll()
    lease_level = resolve_lease_level_scenario(
        lease_level_terms(ltv=base_ltv), lease_level_property(), suites, leases,
        market_leasing=market(), operating_inputs=lease_level_operating(),
        unit_id=UNIT, scenario=capped, business_plan=BusinessPlan(),
    )
    assert quick.inputs.ltv == expected
    assert detailed.terms.ltv == expected
    assert lease_level.terms.ltv == expected


@pytest.mark.parametrize(("base_p", "expected"), [(0.65, 0.5), (0.40, 0.40)])
def test_renewal_probability_cap_at_is_an_upper_cap_too(base_p: float, expected: float) -> None:
    resolved = resolve_lease_level(
        scenario(ov(T.RENEWAL_PROBABILITY, Op.CAP_AT, 0.5)),
        mkt=market(renewal_probability=base_p),
    )
    assert resolved.market_leasing.renewal_probability == expected


# =============================================================================
# Multi-variable scenarios == the same assumptions entered by hand (U, V)
# =============================================================================


def test_quick_downside_equals_manual_entry_bit_for_bit() -> None:
    downside = scenario(
        ov(T.NOI_GROWTH, Op.ADD, -0.015),
        ov(T.EXIT_CAP_RATE, Op.ADD, 0.0075),
        ov(T.INTEREST_RATE, Op.ADD, 0.01),
        ov(T.LTV, Op.CAP_AT, 0.55),
        name="Downside",
    )
    manual = quick_inputs(
        noi_growth=0.03 + -0.015, exit_cap_rate=0.0625 + 0.0075,
        interest_rate=0.0575 + 0.01, ltv=0.55,
    )

    resolved = resolve_quick_scenario(quick_inputs(), unit_id=UNIT, scenario=downside, business_plan=business_plan())
    scenario_results = run_quick(downside)
    manual_results = analyze_quick_acquisition_with_business_plan(manual, business_plan=business_plan())

    assert identical(resolved.inputs, manual)
    assert identical(scenario_results, manual_results)
    base_results = analyze_quick_acquisition_with_business_plan(
        quick_inputs(), business_plan=business_plan()
    )
    assert scenario_results.total_profit < base_results.total_profit
    assert scenario_results.exit_value < base_results.exit_value


def test_quick_upside_equals_manual_entry_bit_for_bit() -> None:
    upside = scenario(
        ov(T.NOI_GROWTH, Op.SET, 0.04),
        ov(T.EXIT_CAP_RATE, Op.SCALE, 0.95),
        ov(T.INTEREST_RATE, Op.ADD, -0.005),
        name="Upside",
    )
    manual = quick_inputs(noi_growth=0.04, exit_cap_rate=0.0625 * 0.95, interest_rate=0.0575 + -0.005)
    assert identical(
        run_quick(upside),
        analyze_quick_acquisition_with_business_plan(manual, business_plan=business_plan()),
    )


def test_detailed_downside_equals_manual_entry_bit_for_bit() -> None:
    downside = scenario(
        ov(T.REVENUE_GROWTH, Op.ADD, -0.01),
        ov(T.VACANCY_CREDIT_LOSS_PCT, Op.ADD, 0.04),
        ov(T.EXPENSE_GROWTH, Op.ADD, 0.01),
        ov(T.EXIT_CAP_RATE, Op.ADD, 0.005),
        ov(T.INTEREST_RATE, Op.SCALE, 1.1),
        ov(T.LTV, Op.CAP_AT, 0.55),
        name="Downside",
    )
    manual_terms = detailed_terms(exit_cap_rate=0.065 + 0.005, interest_rate=0.06 * 1.1, ltv=0.55)
    manual_operating = detailed_operating(
        revenue_growth=0.03 + -0.01, vacancy_credit_loss_pct=0.06 + 0.04, expense_growth=0.025 + 0.01
    )

    resolved = resolve_detailed_scenario(
        detailed_terms(), detailed_operating(), unit_id=UNIT, scenario=downside, business_plan=business_plan()
    )
    assert identical(resolved.terms, manual_terms)
    assert identical(resolved.detailed_operating_inputs, manual_operating)

    scenario_results = run_detailed(downside)
    manual_results = analyze_detailed_acquisition_with_business_plan(
        manual_terms, manual_operating, business_plan=business_plan()
    )
    assert identical(scenario_results, manual_results)  # projection and results
    base = analyze_detailed_acquisition_with_business_plan(
        detailed_terms(), detailed_operating(), business_plan=business_plan()
    )
    assert scenario_results.results.noi_by_year != base.results.noi_by_year


def test_lease_level_downside_equals_manual_entry_bit_for_bit() -> None:
    downside = scenario(
        ov(T.MARKET_RENT_PSF, Op.SCALE, 0.9),
        ov(T.RENEWAL_PROBABILITY, Op.ADD, -0.25),
        ov(T.EXPENSE_GROWTH, Op.ADD, 0.01),
        ov(T.RECOVERABLE_EXPENSE_RATIO, Op.ADD, -0.1),
        ov(T.EXIT_CAP_RATE, Op.ADD, 0.005),
        ov(T.INTEREST_RATE, Op.ADD, 0.01),
        ov(T.LTV, Op.CAP_AT, 0.55),
        name="Downside",
    )
    manual_suites, manual_leases = rent_roll(b_market_rent_psf=42.0 * 0.9)
    manual = dict(
        market_leasing=market(market_rent_psf=36.0 * 0.9, renewal_probability=0.65 + -0.25),
        operating_inputs=lease_level_operating(expense_growth=0.03 + 0.01, recoverable_expense_ratio=0.9 + -0.1),
    )
    manual_terms = lease_level_terms(exit_cap_rate=0.065 + 0.005, interest_rate=0.055 + 0.01, ltv=0.55)

    resolved = resolve_lease_level(downside)
    assert identical(resolved.terms, manual_terms)
    assert identical(resolved.suites, tuple(manual_suites))
    assert identical(resolved.market_leasing, manual["market_leasing"])
    assert identical(resolved.operating_inputs, manual["operating_inputs"])

    scenario_results = run_lease_level(downside)
    manual_results = analyze_lease_level_acquisition_with_business_plan(
        manual_terms, lease_level_property(), manual_suites, manual_leases,
        business_plan=business_plan(), **manual,
    )
    assert identical(scenario_results, manual_results)  # monthly, annual and results
    base = run_lease_level(scenario())
    assert scenario_results.results.noi_by_year != base.results.noi_by_year
    assert scenario_results.results.levered_irr != base.results.levered_irr


def test_lease_level_upside_equals_manual_entry_bit_for_bit() -> None:
    upside = scenario(
        ov(T.MARKET_RENT_PSF, Op.ADD, 3.0),
        ov(T.RENEWAL_PROBABILITY, Op.CAP_AT, 0.9),  # 0.65 < 0.9: unchanged
        ov(T.EXIT_CAP_RATE, Op.SCALE, 0.97),
        name="Upside",
    )
    manual_suites, manual_leases = rent_roll(b_market_rent_psf=42.0 + 3.0)
    manual_results = analyze_lease_level_acquisition_with_business_plan(
        lease_level_terms(exit_cap_rate=0.065 * 0.97), lease_level_property(),
        manual_suites, manual_leases,
        market_leasing=market(market_rent_psf=36.0 + 3.0),
        operating_inputs=lease_level_operating(), business_plan=business_plan(),
    )
    assert identical(run_lease_level(upside), manual_results)


# =============================================================================
# Order, names, repeatability, immutability (K, M, Q)
# =============================================================================


def test_quick_override_order_never_changes_resolved_inputs_or_results() -> None:
    rows = (
        ov(T.INTEREST_RATE, Op.ADD, 0.01),
        ov(T.EXIT_CAP_RATE, Op.SCALE, 1.08),
        ov(T.NOI_GROWTH, Op.SET, 0.01),
        ov(T.LTV, Op.CAP_AT, 0.6),
    )
    outcomes = [
        (
            resolve_quick_scenario(quick_inputs(), unit_id=UNIT, scenario=scenario(*p), business_plan=business_plan()),
            run_quick(scenario(*p)),
        )
        for p in itertools.permutations(rows)
    ]
    assert len(outcomes) == 24
    for resolved, results in outcomes[1:]:
        assert identical(resolved, outcomes[0][0])
        assert identical(results, outcomes[0][1])


def test_lease_level_override_order_never_changes_resolved_inputs_or_results() -> None:
    rows = (
        ov(T.INTEREST_RATE, Op.ADD, 0.0075),
        ov(T.EXIT_CAP_RATE, Op.ADD, 0.0025),
        ov(T.MARKET_RENT_PSF, Op.SCALE, 0.92),
    )
    outcomes = [
        (resolve_lease_level(scenario(*p)), run_lease_level(scenario(*p)))
        for p in itertools.permutations(rows)
    ]
    for resolved, results in outcomes[1:]:
        assert identical(resolved, outcomes[0][0])
        assert identical(results, outcomes[0][1])


def test_ids_names_and_descriptions_never_reach_a_number() -> None:
    rows = (ov(T.EXIT_CAP_RATE, Op.ADD, 0.005), ov(T.INTEREST_RATE, Op.ADD, 0.01))
    first = scenario(*rows, scenario_id="a1", name="Downside", description="Rates up")
    second = scenario(*rows, scenario_id="zz-9", name="Recession 2027", description=None)
    third = scenario(*rows, scenario_id="base", name="Base", description="anything")
    for runner in (run_quick, run_detailed, run_lease_level):
        results = [runner(s) for s in (first, second, third)]
        assert identical(results[0], results[1])
        assert identical(results[0], results[2])
    assert identical(resolve_lease_level(first), resolve_lease_level(second))


def test_resolving_twice_gives_equivalent_results_and_mutates_nothing() -> None:
    suites, leases = rent_roll(c_override=market(market_rent_psf=50.0, renewal_probability=0.5))
    suites_before, leases_before = copy.deepcopy(suites), copy.deepcopy(leases)
    terms, mkt, ops, plan = lease_level_terms(), market(), lease_level_operating(), business_plan()
    snapshot = copy.deepcopy((terms, mkt, ops, plan))
    definition = scenario(
        ov(T.MARKET_RENT_PSF, Op.SCALE, 0.9), ov(T.EXPENSE_GROWTH, Op.ADD, 0.01),
        ov(T.LTV, Op.CAP_AT, 0.5),
    )

    def resolve():  # type: ignore[no-untyped-def]
        return resolve_lease_level_scenario(
            terms, lease_level_property(), suites, leases, market_leasing=mkt,
            operating_inputs=ops, unit_id=UNIT, scenario=definition, business_plan=plan,
        )

    assert identical(resolve(), resolve())
    assert suites == suites_before and leases == leases_before  # the caller's lists
    assert (terms, mkt, ops, plan) == snapshot


# =============================================================================
# Neutral compatibility (P, AE) and the Business Plan freeze (S)
# =============================================================================


def test_a_zero_override_scenario_hands_back_the_callers_own_objects() -> None:
    empty = scenario()
    inputs, plan = quick_inputs(), business_plan()
    quick = resolve_quick_scenario(inputs, unit_id=UNIT, scenario=empty, business_plan=plan)
    assert quick.inputs is inputs and quick.business_plan is plan

    terms, operating = detailed_terms(), detailed_operating()
    detailed = resolve_detailed_scenario(terms, operating, unit_id=UNIT, scenario=empty, business_plan=plan)
    assert detailed.terms is terms and detailed.detailed_operating_inputs is operating

    suites, leases = rent_roll()
    ll_terms, mkt, ops = lease_level_terms(), market(), lease_level_operating()
    lease_level = resolve_lease_level_scenario(
        ll_terms, lease_level_property(), suites, leases, market_leasing=mkt,
        operating_inputs=ops, unit_id=UNIT, scenario=empty, business_plan=plan,
    )
    assert lease_level.terms is ll_terms and lease_level.market_leasing is mkt
    assert lease_level.operating_inputs is ops and lease_level.business_plan is plan
    assert all(a is b for a, b in zip(lease_level.suites, suites, strict=True))
    assert all(a is b for a, b in zip(lease_level.leases, leases, strict=True))


def test_a_zero_override_scenario_reproduces_every_ordinary_analysis_bit_for_bit() -> None:
    empty = scenario()
    plan = business_plan()
    assert identical(
        run_quick(empty, BusinessPlan()), analyze_acquisition(quick_inputs())
    )
    assert identical(
        run_quick(empty, plan),
        analyze_quick_acquisition_with_business_plan(quick_inputs(), business_plan=plan),
    )
    assert identical(
        run_detailed(empty, BusinessPlan()),
        analyze_detailed_acquisition_with_projection(detailed_terms(), detailed_operating()),
    )
    suites, leases = rent_roll()
    assert identical(
        run_lease_level(empty),
        analyze_lease_level_acquisition_with_business_plan(
            lease_level_terms(), lease_level_property(), suites, leases,
            market_leasing=market(), operating_inputs=lease_level_operating(), business_plan=plan,
        ),
    )
    assert identical(
        analyze_lease_level_acquisition_with_scenario(
            lease_level_terms(), lease_level_property(), suites, leases,
            market_leasing=market(), operating_inputs=lease_level_operating(),
            unit_id=UNIT, scenario=empty, business_plan=BusinessPlan(),
        ),
        analyze_lease_level_acquisition_with_projection(
            lease_level_terms(), lease_level_property(), suites, leases,
            market_leasing=market(), operating_inputs=lease_level_operating(),
        ),
    )


@pytest.mark.parametrize("target", list(ScenarioTarget))
def test_no_target_touches_the_business_plan(target: ScenarioTarget) -> None:
    operation, value = {
        T.LTV: (Op.CAP_AT, 0.5),
        T.MARKET_RENT_PSF: (Op.SCALE, 0.9),
        T.RENEWAL_PROBABILITY: (Op.SET, 0.5),
    }.get(target, (Op.ADD, 0.001))
    definition = scenario(ov(target, operation, value))
    plan = business_plan()
    snapshot = copy.deepcopy(plan)
    spec = module.SCENARIO_TARGET_REGISTRY[target]
    resolved = []
    if module.OperatingMode.QUICK in spec.modes:
        resolved.append(resolve_quick_scenario(quick_inputs(), unit_id=UNIT, scenario=definition, business_plan=plan))
    if module.OperatingMode.DETAILED in spec.modes:
        resolved.append(resolve_detailed_scenario(
            detailed_terms(), detailed_operating(), unit_id=UNIT, scenario=definition, business_plan=plan))
    if module.OperatingMode.LEASE_LEVEL in spec.modes:
        suites, leases = rent_roll()
        resolved.append(resolve_lease_level_scenario(
            lease_level_terms(), lease_level_property(), suites, leases,
            market_leasing=market(), operating_inputs=lease_level_operating(),
            unit_id=UNIT, scenario=definition, business_plan=plan))
    assert resolved
    for bundle in resolved:
        assert bundle.business_plan is plan
    assert plan == snapshot


# =============================================================================
# Invalid resolution (N, O, Y) -- no clipping, no result, the existing reason
# =============================================================================


@pytest.fixture
def engine_must_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("an invalid scenario reached the engine")

    for name in (
        "analyze_quick_acquisition_with_business_plan",
        "analyze_detailed_acquisition_with_business_plan",
        "analyze_lease_level_acquisition_with_business_plan",
    ):
        monkeypatch.setattr(module, name, refuse)


def _only_issue(excinfo: pytest.ExceptionInfo[ScenarioValidationError]):  # type: ignore[no-untyped-def]
    (issue,) = excinfo.value.issues
    return issue


@pytest.mark.usefixtures("engine_must_not_run")
@pytest.mark.parametrize(
    ("operation", "value"),
    [(Op.ADD, 0.5), (Op.SCALE, 2.0), (Op.SET, 1.0000001), (Op.ADD, -0.7), (Op.SET, -0.01)],
)
def test_a_renewal_probability_outside_zero_to_one_is_invalid_never_clipped(
    operation: ScenarioOperation, value: float
) -> None:
    resolved_p = module._apply_operation(operation, market().renewal_probability, value)
    assert not 0.0 <= resolved_p <= 1.0
    with pytest.raises(ScenarioValidationError) as excinfo:
        run_lease_level(scenario(ov(T.RENEWAL_PROBABILITY, operation, value)))
    issue = _only_issue(excinfo)
    assert issue.stage is ScenarioIssueStage.RESOLVED_INPUTS
    assert issue.code is ScenarioIssueCode.RESOLVED_INPUT_INVALID
    assert issue.source_code == LeaseIssueCode.RENEWAL_PROBABILITY_OUT_OF_DOMAIN.value
    assert issue.field == "market_leasing.renewal_probability"
    assert issue.target is T.RENEWAL_PROBABILITY
    assert repr(resolved_p) in issue.message  # the unclipped resolved value


def test_renewal_probability_endpoints_are_valid() -> None:
    for value in (0.0, 1.0):
        resolved = resolve_lease_level(scenario(ov(T.RENEWAL_PROBABILITY, Op.SET, value)))
        assert resolved.market_leasing.renewal_probability == value


@pytest.mark.usefixtures("engine_must_not_run")
@pytest.mark.parametrize(
    ("runner", "field"),
    [(run_quick, "interest_rate"), (run_detailed, "interest_rate"), (run_lease_level, "interest_rate")],
    ids=["quick", "detailed", "lease_level"],
)
def test_an_interest_rate_resolving_below_zero_is_invalid(runner, field: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ScenarioValidationError) as excinfo:
        runner(scenario(ov(T.INTEREST_RATE, Op.ADD, -0.07)))
    issue = _only_issue(excinfo)
    assert issue.stage is ScenarioIssueStage.RESOLVED_INPUTS
    assert issue.source_code == "out_of_domain_value"
    assert issue.field == field
    assert issue.target is T.INTEREST_RATE


@pytest.mark.usefixtures("engine_must_not_run")
@pytest.mark.parametrize(
    ("runner", "definition", "code"),
    [
        (run_quick, scenario(ov(T.EXIT_CAP_RATE, Op.SCALE, 0.0)), ScenarioIssueCode.RESOLVED_INPUT_INVALID),
        (run_quick, scenario(ov(T.NOI_GROWTH, Op.SET, -1.0)), ScenarioIssueCode.RESOLVED_INPUT_INVALID),
        (run_quick, scenario(ov(T.LTV, Op.CAP_AT, -0.1)), ScenarioIssueCode.RESOLVED_INPUT_INVALID),
        (run_detailed, scenario(ov(T.VACANCY_CREDIT_LOSS_PCT, Op.ADD, 0.95)), ScenarioIssueCode.RESOLVED_INPUT_INVALID),
        (run_detailed, scenario(ov(T.REVENUE_GROWTH, Op.SET, -1.5)), ScenarioIssueCode.RESOLVED_INPUT_INVALID),
        (run_lease_level, scenario(ov(T.RECOVERABLE_EXPENSE_RATIO, Op.ADD, 0.2)), ScenarioIssueCode.RESOLVED_INPUT_INVALID),
        (run_lease_level, scenario(ov(T.EXPENSE_GROWTH, Op.SET, -1.0)), ScenarioIssueCode.RESOLVED_INPUT_INVALID),
        (run_quick, scenario(ov(T.MARKET_RENT_PSF, Op.SCALE, 0.9)), ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE),
        (run_detailed, scenario(ov(T.NOI_GROWTH, Op.ADD, 0.01)), ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE),
        (run_lease_level, scenario(ov(T.LTV, Op.SET, 0.5)), ScenarioIssueCode.OPERATION_NOT_ALLOWED),
        (run_quick, scenario(ov(T.EXIT_CAP_RATE, Op.CAP_AT, 0.07)), ScenarioIssueCode.OPERATION_NOT_ALLOWED),
        (run_detailed, scenario(ov(T.EXIT_CAP_RATE, Op.ADD, 0.01), ov(T.EXIT_CAP_RATE, Op.ADD, 0.01)), ScenarioIssueCode.DUPLICATE_TARGET),
        (run_quick, scenario(ov(T.EXIT_CAP_RATE, Op.ADD, math.nan)), ScenarioIssueCode.NON_FINITE_VALUE),
        (run_lease_level, scenario(ov(T.MARKET_RENT_PSF, Op.SCALE, math.inf)), ScenarioIssueCode.NON_FINITE_VALUE),
        (run_detailed, scenario(ov(T.INTEREST_RATE, Op.SET, True)), ScenarioIssueCode.NON_NUMERIC_VALUE),
    ],
)
def test_every_invalid_scenario_raises_before_the_engine_and_returns_nothing(  # type: ignore[no-untyped-def]
    runner, definition: ScenarioDefinition, code: ScenarioIssueCode
) -> None:
    with pytest.raises(ScenarioValidationError) as excinfo:
        runner(definition)
    assert [issue.code for issue in excinfo.value.issues] == [code]


def test_stage_two_reports_every_changed_contract_terms_first() -> None:
    with pytest.raises(ScenarioValidationError) as excinfo:
        run_detailed(scenario(
            ov(T.VACANCY_CREDIT_LOSS_PCT, Op.SET, 1.5), ov(T.EXIT_CAP_RATE, Op.SET, -0.01),
        ))
    assert [(i.field, i.target) for i in excinfo.value.issues] == [
        ("exit_cap_rate", T.EXIT_CAP_RATE),
        ("vacancy_credit_loss_pct", T.VACANCY_CREDIT_LOSS_PCT),
    ]
    assert all(i.stage is ScenarioIssueStage.RESOLVED_INPUTS for i in excinfo.value.issues)


def test_a_pre_existing_base_defect_is_reported_without_blaming_a_target() -> None:
    with pytest.raises(ScenarioValidationError) as excinfo:
        resolve_quick_scenario(
            quick_inputs(purchase_price=-1.0),
            unit_id=UNIT, scenario=scenario(ov(T.EXIT_CAP_RATE, Op.ADD, 0.005)),
            business_plan=BusinessPlan(),
        )
    issue = _only_issue(excinfo)
    assert (issue.field, issue.target) == ("purchase_price", None)


def test_a_warning_never_invalidates_a_scenario() -> None:
    """``renewal_probability`` in (0, 1) raises the leasing validator's
    weighted-rollover WARNING; it is not an error."""

    resolved = resolve_lease_level(scenario(ov(T.RENEWAL_PROBABILITY, Op.SET, 0.4)))
    assert resolved.market_leasing.renewal_probability == 0.4


def test_the_invalid_reason_is_the_existing_validators_wording() -> None:
    from anchor.validation import InputValidationError, validate_acquisition_inputs
    import dataclasses

    with pytest.raises(InputValidationError) as direct:
        validate_acquisition_inputs(dataclasses.asdict(quick_inputs(interest_rate=0.0575 + -0.07)))
    with pytest.raises(ScenarioValidationError) as via_scenario:
        resolve_quick_scenario(
            quick_inputs(), unit_id=UNIT, scenario=scenario(ov(T.INTEREST_RATE, Op.ADD, -0.07)),
            business_plan=BusinessPlan(),
        )
    assert [i.message for i in via_scenario.value.issues] == [i.message for i in direct.value.issues]
    assert [i.source_code for i in via_scenario.value.issues] == [
        i.category.value for i in direct.value.issues
    ]


def test_suites_without_any_override_pass_through_as_the_callers_objects() -> None:
    suites, leases = rent_roll()
    resolved = resolve_lease_level(scenario(ov(T.MARKET_RENT_PSF, Op.SCALE, 0.9)), suites, leases)
    assert resolved.suites[0] is suites[0]  # A: default-derived, no field of its own moves
    assert resolved.suites[1] is not suites[1]  # B: its scalar override moves
    assert isinstance(resolved.suites[1], Suite)
