"""Phase 7 Gate P7.1 review correction -- unit-addressed scenario overrides.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 7.2
ratified the override contract with ``unit_id``: "the Unit (Deal) it applies
to; always explicit, even with one unit". Two rules go with it:
- SC-1: uniqueness is per ``(unit_id, target)``;
- SC-5: an override whose unit is not in the variant makes the variant
  invalid, and is never silently ignored.

P7.1 analyses one Unit per call. Every override must address that Unit, and
any other unit is refused rather than ignored, filtered out or reinterpreted.
"""

from __future__ import annotations

import inspect
import itertools

import pytest

from anchor.analysis import business_plan_analysis
from anchor.analysis import scenario as module
from anchor.analysis.scenario import (
    ScenarioDefinition,
    ScenarioIssue,
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
    validate_scenario,
)
from anchor.contracts import OperatingMode

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
Q, D, L = OperatingMode.QUICK, OperatingMode.DETAILED, OperatingMode.LEASE_LEVEL
OTHER = "deal-other"


def addr(unit_id: object, target: object, operation: ScenarioOperation, value: float) -> ScenarioOverride:
    return ScenarioOverride(unit_id=unit_id, target=target, operation=operation, value=value)  # type: ignore[arg-type]


def scenario(*overrides: ScenarioOverride) -> ScenarioDefinition:
    return ScenarioDefinition(scenario_id="scn-units", name="Unit view", overrides=tuple(overrides))


def codes(issues: tuple[ScenarioIssue, ...]) -> list[ScenarioIssueCode]:
    return [issue.code for issue in issues]


def resolve(mode: OperatingMode, definition: ScenarioDefinition, unit_id: str = UNIT):  # type: ignore[no-untyped-def]
    if mode is Q:
        return resolve_quick_scenario(
            quick_inputs(), unit_id=unit_id, scenario=definition, business_plan=business_plan()
        )
    if mode is D:
        return resolve_detailed_scenario(
            detailed_terms(), detailed_operating(), unit_id=unit_id, scenario=definition,
            business_plan=business_plan(),
        )
    suites, leases = rent_roll()
    return resolve_lease_level_scenario(
        lease_level_terms(), lease_level_property(), suites, leases,
        market_leasing=market(), operating_inputs=lease_level_operating(),
        unit_id=unit_id, scenario=definition, business_plan=business_plan(),
    )


def analyze(mode: OperatingMode, definition: ScenarioDefinition):  # type: ignore[no-untyped-def]
    if mode is Q:
        return analyze_quick_acquisition_with_scenario(
            quick_inputs(), unit_id=UNIT, scenario=definition, business_plan=business_plan()
        )
    if mode is D:
        return analyze_detailed_acquisition_with_scenario(
            detailed_terms(), detailed_operating(), unit_id=UNIT, scenario=definition,
            business_plan=business_plan(),
        )
    suites, leases = rent_roll()
    return analyze_lease_level_acquisition_with_scenario(
        lease_level_terms(), lease_level_property(), suites, leases,
        market_leasing=market(), operating_inputs=lease_level_operating(),
        unit_id=UNIT, scenario=definition, business_plan=business_plan(),
    )


#: A target every mode has, so each proof runs in all three modes.
SHARED = T.EXIT_CAP_RATE


@pytest.fixture
def engine_must_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a scenario with a foreign-unit override reached the engine")

    for name in (
        "analyze_quick_acquisition_with_business_plan",
        "analyze_detailed_acquisition_with_business_plan",
        "analyze_lease_level_acquisition_with_business_plan",
    ):
        monkeypatch.setattr(module, name, refuse)


# =============================================================================
# 1-2. The contract: unit_id is explicit, required and nonblank
# =============================================================================


def test_every_override_must_name_its_unit_explicitly() -> None:
    with pytest.raises(TypeError):
        ScenarioOverride(target=SHARED, operation=Op.ADD, value=0.005)  # type: ignore[call-arg]
    override = addr(UNIT, SHARED, Op.ADD, 0.005)
    assert override.unit_id == UNIT


@pytest.mark.parametrize("blank", ["", "   ", "\t\n", None, 7, b"deal-a1"])
def test_a_blank_or_non_string_unit_id_is_invalid(blank: object) -> None:
    issues = validate_scenario(
        scenario(addr(blank, SHARED, Op.ADD, 0.005)), operating_mode=Q, unit_id=UNIT
    )
    assert codes(issues) == [ScenarioIssueCode.INVALID_UNIT_ID]
    (issue,) = issues
    assert (issue.stage, issue.target, issue.unit_id) == (ScenarioIssueStage.SCENARIO, SHARED, None)


def test_the_analysed_units_own_identity_must_be_a_nonblank_string() -> None:
    with pytest.raises(ValueError):
        validate_scenario(scenario(), operating_mode=Q, unit_id="  ")
    with pytest.raises(TypeError):
        validate_scenario(scenario(), operating_mode=Q, unit_id=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        resolve(Q, scenario(), unit_id="")
    with pytest.raises(TypeError):
        resolve_quick_scenario(quick_inputs(), scenario=scenario(), business_plan=business_plan())  # type: ignore[call-arg]


def test_every_scenario_entry_point_requires_a_keyword_unit_and_ordinary_ones_take_none() -> None:
    for function in (
        validate_scenario, resolve_quick_scenario, resolve_detailed_scenario,
        resolve_lease_level_scenario, analyze_quick_acquisition_with_scenario,
        analyze_detailed_acquisition_with_scenario, analyze_lease_level_acquisition_with_scenario,
    ):
        parameter = inspect.signature(function).parameters["unit_id"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, function.__name__
        assert parameter.default is inspect.Parameter.empty, function.__name__
    for ordinary in (
        business_plan_analysis.analyze_quick_acquisition_with_business_plan,
        business_plan_analysis.analyze_detailed_acquisition_with_business_plan,
        business_plan_analysis.analyze_lease_level_acquisition_with_business_plan,
    ):
        assert "unit_id" not in inspect.signature(ordinary).parameters


# =============================================================================
# 3-5. Addressability: the analysed unit resolves; any other unit is refused
# =============================================================================


@pytest.mark.parametrize("mode", [Q, D, L])
def test_an_override_on_the_analysed_unit_resolves_normally(mode: OperatingMode) -> None:
    resolved = resolve(mode, scenario(addr(UNIT, SHARED, Op.ADD, 0.005)))
    terms = resolved.inputs if mode is Q else resolved.terms
    base = {Q: 0.0625, D: 0.065, L: 0.065}[mode]
    assert terms.exit_cap_rate == base + 0.005


@pytest.mark.parametrize("mode", [Q, D, L])
def test_an_override_addressing_another_unit_is_invalid_and_names_that_unit(mode: OperatingMode) -> None:
    with pytest.raises(ScenarioValidationError) as excinfo:
        resolve(mode, scenario(addr(OTHER, SHARED, Op.ADD, 0.005)))
    (issue,) = excinfo.value.issues
    assert issue.code is ScenarioIssueCode.UNIT_NOT_IN_VARIANT
    assert issue.stage is ScenarioIssueStage.SCENARIO
    assert (issue.unit_id, issue.target) == (OTHER, SHARED)
    assert repr(OTHER) in issue.message and repr(UNIT) in issue.message


@pytest.mark.usefixtures("engine_must_not_run")
@pytest.mark.parametrize("mode", [Q, D, L])
def test_a_foreign_override_is_never_silently_ignored_beside_valid_ones(mode: OperatingMode) -> None:
    """The analysed unit's own override is valid. The scenario still fails as
    a whole: the foreign row is neither dropped nor applied, and no result is
    produced."""

    definition = scenario(addr(UNIT, SHARED, Op.ADD, 0.005), addr(OTHER, T.INTEREST_RATE, Op.ADD, 0.01))
    with pytest.raises(ScenarioValidationError) as resolved:
        resolve(mode, definition)
    with pytest.raises(ScenarioValidationError) as analysed:
        analyze(mode, definition)
    for excinfo in (resolved, analysed):
        assert [(i.code, i.unit_id, i.target) for i in excinfo.value.issues] == [
            (ScenarioIssueCode.UNIT_NOT_IN_VARIANT, OTHER, T.INTEREST_RATE)
        ]


@pytest.mark.parametrize("near_miss", [f"{UNIT} ", f" {UNIT}", UNIT.upper(), f"{UNIT}-copy"])
def test_a_near_miss_unit_id_is_another_unit_never_reinterpreted(near_miss: str) -> None:
    assert near_miss != UNIT
    issues = validate_scenario(
        scenario(addr(near_miss, SHARED, Op.ADD, 0.005)), operating_mode=Q, unit_id=UNIT
    )
    assert [(i.code, i.unit_id) for i in issues] == [(ScenarioIssueCode.UNIT_NOT_IN_VARIANT, near_miss)]


# =============================================================================
# 6-7. Duplicate identity is (unit_id, target)
# =============================================================================


def test_the_same_target_twice_on_the_same_unit_is_a_duplicate() -> None:
    issues = validate_scenario(
        scenario(addr(UNIT, SHARED, Op.ADD, 0.005), addr(UNIT, SHARED, Op.SCALE, 1.1)),
        operating_mode=D, unit_id=UNIT,
    )
    assert [(i.code, i.unit_id, i.target) for i in issues] == [
        (ScenarioIssueCode.DUPLICATE_TARGET, UNIT, SHARED)
    ]


def test_a_duplicate_on_a_foreign_unit_is_reported_once_as_a_duplicate() -> None:
    issues = validate_scenario(
        scenario(addr(OTHER, SHARED, Op.ADD, 0.005), addr(OTHER, SHARED, Op.ADD, 0.005)),
        operating_mode=Q, unit_id=UNIT,
    )
    assert [(i.code, i.unit_id) for i in issues] == [(ScenarioIssueCode.DUPLICATE_TARGET, OTHER)]


def test_the_same_target_on_two_units_is_two_addresses_not_a_duplicate() -> None:
    """P7.6 will resolve this exact scenario across both units without any
    change to the contract. In P7.1 only the foreign address is refused."""

    issues = validate_scenario(
        scenario(addr(UNIT, SHARED, Op.ADD, 0.005), addr(OTHER, SHARED, Op.ADD, 0.005)),
        operating_mode=L, unit_id=UNIT,
    )
    assert ScenarioIssueCode.DUPLICATE_TARGET not in codes(issues)
    assert [(i.code, i.unit_id, i.target) for i in issues] == [
        (ScenarioIssueCode.UNIT_NOT_IN_VARIANT, OTHER, SHARED)
    ]


# =============================================================================
# 8. Order independence across units and rows
# =============================================================================


def test_issue_order_is_deterministic_whatever_the_authored_row_order() -> None:
    """Addresses are reported by unit, in sorted order ("deal-a1" < "deal-aa"
    < "deal-zz"), then by target in registry order. Malformed unit ids come
    first."""

    rows = [
        addr("deal-zz", T.LTV, Op.CAP_AT, 0.5),
        addr("deal-aa", SHARED, Op.ADD, 0.01),
        addr(UNIT, T.LTV, Op.SET, 0.5),
        addr(UNIT, T.NOI_GROWTH, Op.ADD, 0.01),
        addr(UNIT, T.NOI_GROWTH, Op.ADD, 0.02),
        addr("", SHARED, Op.ADD, 0.01),
    ]
    results = {
        validate_scenario(scenario(*p), operating_mode=Q, unit_id=UNIT)
        for p in itertools.permutations(rows)
    }
    assert len(results) == 1
    (issues,) = results
    assert [(i.code, i.unit_id, i.target) for i in issues] == [
        (ScenarioIssueCode.INVALID_UNIT_ID, None, SHARED),
        (ScenarioIssueCode.OPERATION_NOT_ALLOWED, UNIT, T.LTV),
        (ScenarioIssueCode.DUPLICATE_TARGET, UNIT, T.NOI_GROWTH),
        (ScenarioIssueCode.UNIT_NOT_IN_VARIANT, "deal-aa", SHARED),
        (ScenarioIssueCode.UNIT_NOT_IN_VARIANT, "deal-zz", T.LTV),
    ]


def test_resolution_with_explicit_units_ignores_row_order() -> None:
    rows = (
        addr(UNIT, T.INTEREST_RATE, Op.ADD, 0.01),
        addr(UNIT, SHARED, Op.SCALE, 1.08),
        addr(UNIT, T.LTV, Op.CAP_AT, 0.6),
    )
    outcomes = [repr(resolve(Q, scenario(*p))) for p in itertools.permutations(rows)]
    assert len(set(outcomes)) == 1


# =============================================================================
# Every issue names its unit where one exists
# =============================================================================


def test_stage_two_and_shadowing_issues_name_the_analysed_unit() -> None:
    with pytest.raises(ScenarioValidationError) as stage_two:
        resolve(L, scenario(addr(UNIT, T.RENEWAL_PROBABILITY, Op.ADD, 0.5)))
    assert [(i.stage, i.unit_id) for i in stage_two.value.issues] == [
        (ScenarioIssueStage.RESOLVED_INPUTS, UNIT)
    ]

    suites, leases = rent_roll(c_override=market(market_rent_psf=50.0))
    with pytest.raises(ScenarioValidationError) as shadowed:
        resolve_lease_level_scenario(
            lease_level_terms(), lease_level_property(), suites, leases,
            market_leasing=market(), operating_inputs=lease_level_operating(), unit_id=UNIT,
            scenario=scenario(addr(UNIT, T.RENEWAL_PROBABILITY, Op.ADD, -0.1)),
            business_plan=business_plan(),
        )
    assert [(i.code, i.unit_id) for i in shadowed.value.issues] == [
        (ScenarioIssueCode.TARGET_SHADOWED_BY_SUITE_OVERRIDE, UNIT)
    ]


def test_purchase_price_stays_unreachable_on_any_unit() -> None:
    for unit in (UNIT, OTHER):
        issues = validate_scenario(
            scenario(addr(unit, "purchase_price", Op.SET, 1.0)), operating_mode=Q, unit_id=UNIT
        )
        assert [(i.code, i.unit_id) for i in issues] == [(ScenarioIssueCode.UNKNOWN_TARGET, unit)]
