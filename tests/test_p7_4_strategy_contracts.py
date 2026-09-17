"""Phase 7 Gate P7.4 -- the Strategy contract and its stage-1 validation.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 7.4 (ST-1,
ST-2), the P7.4 gate's five domains and its domain ownership map. Every rule
below is structural: what a Strategy must be to be stored. Whether its variants
produce valid underwriting is the resolver's question
(``tests/test_p7_4_strategy_resolution.py``).
"""

from __future__ import annotations

import dataclasses
import itertools
import math

import pytest

from anchor.analysis.scenario import SCENARIO_TARGET_REGISTRY, ScenarioOperation, ScenarioTarget
from anchor.analysis.strategy import (
    BASE_STRATEGY_ID,
    STRATEGY_DOMAIN_FIELDS,
    STRATEGY_OUTCOME_TARGETS,
    AcquisitionChoice,
    DispositionChoice,
    FinancingChoice,
    OperatingOutcome,
    OperatingOutcomeSet,
    StrategyDefinition,
    StrategyDomain,
    StrategyIssueCode,
    StrategyIssueStage,
    StrategyOverlay,
    StrategyValidationError,
    validate_strategy,
)
from anchor.business_plan import BusinessPlan, CapitalItemCategory, CapitalPlanItem
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, OperatingMode

import _p7_4_fixtures as f4  # type: ignore[import-not-found]

UNIT = "deal-a1"
FOREIGN = "zzz-foreign-unit"


def _issues(strategy: StrategyDefinition, mode: OperatingMode = OperatingMode.QUICK, unit: str = UNIT):
    return validate_strategy(strategy, operating_mode=mode, unit_id=unit)


def _codes(strategy: StrategyDefinition, mode: OperatingMode = OperatingMode.QUICK) -> list[StrategyIssueCode]:
    return [issue.code for issue in _issues(strategy, mode)]


def _full(mode: OperatingMode, unit: str = UNIT) -> StrategyDefinition:
    """Every domain, valid, for ``mode``."""

    outcomes = tuple(f4.outcome(target, 0.05) for target in STRATEGY_OUTCOME_TARGETS[mode])
    return f4.strategy(
        f4.acquisition(unit),
        f4.financing(unit),
        f4.plan_overlay(unit, f4.renovation_plan()),
        f4.outcomes(unit, *outcomes),
        f4.disposition(unit),
    )


# =============================================================================
# The contract shape
# =============================================================================


def test_every_contract_is_frozen_keyword_only_and_slotted() -> None:
    for contract in (
        StrategyDefinition, StrategyOverlay, AcquisitionChoice, FinancingChoice,
        OperatingOutcome, OperatingOutcomeSet, DispositionChoice,
    ):
        parameters = contract.__dataclass_params__  # type: ignore[attr-defined]
        assert parameters.frozen, contract
        assert "__slots__" in vars(contract), contract
        assert all(field.kw_only for field in dataclasses.fields(contract)), contract
    overlay = f4.acquisition(UNIT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        overlay.unit_id = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        StrategyDefinition("id", "name")  # type: ignore[misc]


def test_the_definition_carries_identity_naming_and_overlays_and_no_unit() -> None:
    """P7.8B appends ``root_overlays``, the Investment-root overlay collection,
    and nothing else: the Strategy is still addressed by its own id, its Unit
    overlays are still ``overlays``, and it still carries no ``unit_id`` of its
    own."""

    assert [field.name for field in dataclasses.fields(StrategyDefinition)] == [
        "strategy_id", "name", "description", "overlays", "root_overlays",
    ]
    assert [field.name for field in dataclasses.fields(StrategyOverlay)] == ["unit_id", "domain", "content"]
    unit_field = dataclasses.fields(StrategyOverlay)[0]
    assert unit_field.default is dataclasses.MISSING and unit_field.default_factory is dataclasses.MISSING


def test_exactly_the_five_unit_domains_and_the_two_investment_root_domains_exist() -> None:
    """The five P7.4 Unit domains, in declaration order, then -- from P7.8B --
    ``CAPITAL_STRUCTURE``, the first Investment-root domain, and -- from P7.9
    Stage 2 -- ``PARTNERSHIP``, the second. Only the Unit domains own engine
    input fields: a root domain replaces a downstream contract, not a field
    of one."""

    assert [(domain.name, domain.value) for domain in StrategyDomain] == [
        ("ACQUISITION", "acquisition"),
        ("FINANCING", "financing"),
        ("BUSINESS_PLAN", "business_plan"),
        ("OPERATING_OUTCOME", "operating_outcome"),
        ("DISPOSITION", "disposition"),
        ("CAPITAL_STRUCTURE", "capital_structure"),
        ("PARTNERSHIP", "partnership"),
    ]
    assert tuple(STRATEGY_DOMAIN_FIELDS) == tuple(
        domain
        for domain in StrategyDomain
        if domain not in (StrategyDomain.CAPITAL_STRUCTURE, StrategyDomain.PARTNERSHIP)
    )
    for later in ("unit_selection",):
        assert later not in {domain.value for domain in StrategyDomain}


def test_the_base_strategy_key_is_reserved() -> None:
    assert BASE_STRATEGY_ID == "base"


# =============================================================================
# One home per field
# =============================================================================


def test_no_field_is_writable_by_two_domains() -> None:
    for first, second in itertools.combinations(STRATEGY_DOMAIN_FIELDS, 2):
        assert not set(STRATEGY_DOMAIN_FIELDS[first]) & set(STRATEGY_DOMAIN_FIELDS[second]), (first, second)
    everything = [field for domain in STRATEGY_DOMAIN_FIELDS for field in STRATEGY_DOMAIN_FIELDS[domain]]
    assert len(everything) == len(set(everything))


def test_the_ratified_ownership_map() -> None:
    assert dict(STRATEGY_DOMAIN_FIELDS) == {
        StrategyDomain.ACQUISITION: ("purchase_price", "acquisition_cost_pct"),
        StrategyDomain.FINANCING: ("ltv", "interest_rate", "amortization", "io_period", "financing_fee_pct"),
        StrategyDomain.BUSINESS_PLAN: ("business_plan",),
        StrategyDomain.OPERATING_OUTCOME: (
            "exit_cap_rate", "noi_growth", "revenue_growth", "vacancy_credit_loss_pct",
            "expense_growth", "market_rent_psf", "renewal_probability", "recoverable_expense_ratio",
        ),
        StrategyDomain.DISPOSITION: ("hold_period",),
    }


def test_each_whole_domain_contract_holds_exactly_its_domain_fields() -> None:
    for domain, contract in (
        (StrategyDomain.ACQUISITION, AcquisitionChoice),
        (StrategyDomain.FINANCING, FinancingChoice),
        (StrategyDomain.DISPOSITION, DispositionChoice),
    ):
        assert tuple(field.name for field in dataclasses.fields(contract)) == STRATEGY_DOMAIN_FIELDS[domain]
        for field in STRATEGY_DOMAIN_FIELDS[domain]:
            assert field in AcquisitionTerms.__dataclass_fields__, field
            assert field in AcquisitionInputs.__dataclass_fields__, field


def test_the_acquisition_disposition_and_financing_domains_exclude_neighbouring_fields() -> None:
    for excluded in ("annual_capex_reserve", "disposition_cost_pct", "financing_fee_pct", "hold_period"):
        assert excluded not in STRATEGY_DOMAIN_FIELDS[StrategyDomain.ACQUISITION]
    assert STRATEGY_DOMAIN_FIELDS[StrategyDomain.DISPOSITION] == ("hold_period",)
    assert "exit_cap_rate" not in STRATEGY_DOMAIN_FIELDS[StrategyDomain.DISPOSITION]


def test_the_operating_outcome_whitelist_per_mode() -> None:
    assert {mode: [t.value for t in targets] for mode, targets in STRATEGY_OUTCOME_TARGETS.items()} == {
        OperatingMode.QUICK: ["exit_cap_rate", "noi_growth"],
        OperatingMode.DETAILED: ["exit_cap_rate", "revenue_growth", "vacancy_credit_loss_pct", "expense_growth"],
        OperatingMode.LEASE_LEVEL: [
            "exit_cap_rate", "expense_growth", "market_rent_psf", "renewal_probability", "recoverable_expense_ratio",
        ],
    }
    covered = {target.value for targets in STRATEGY_OUTCOME_TARGETS.values() for target in targets}
    assert covered == set(STRATEGY_DOMAIN_FIELDS[StrategyDomain.OPERATING_OUTCOME])
    assert not covered & {"interest_rate", "ltv"}


def test_every_strategy_outcome_is_a_registry_target_for_its_mode_with_set() -> None:
    """The Strategy whitelist is a subset of the P7.1 registry, never a second
    registry: each target already has a SET resolver in that mode."""

    for mode, targets in STRATEGY_OUTCOME_TARGETS.items():
        assert list(targets) == sorted(targets, key=list(ScenarioTarget).index), mode
        for target in targets:
            spec = SCENARIO_TARGET_REGISTRY[target]
            assert mode in spec.modes, (mode, target)
            assert ScenarioOperation.SET in spec.allowed_operations, target


# =============================================================================
# A valid strategy
# =============================================================================


@pytest.mark.parametrize("mode", list(OperatingMode))
def test_a_strategy_using_every_domain_is_valid(mode: OperatingMode) -> None:
    assert _issues(_full(mode), mode) == ()


def test_a_strategy_with_no_overlay_is_valid() -> None:
    assert _issues(f4.strategy()) == ()


def test_integral_floats_are_whole_numbers_and_ints_are_real_numbers() -> None:
    strategy = f4.strategy(
        f4.acquisition(UNIT, purchase_price=9_500_000, acquisition_cost_pct=0),
        f4.financing(UNIT, amortization=30.0, io_period=0.0),
        f4.disposition(UNIT, 7.0),
    )
    assert _issues(strategy) == ()


def test_the_empty_business_plan_is_a_valid_replacement() -> None:
    assert _issues(f4.strategy(f4.plan_overlay(UNIT, BusinessPlan()))) == ()


# =============================================================================
# Identity and naming
# =============================================================================


@pytest.mark.parametrize("strategy_id", ["", "   ", None, 7])
def test_a_blank_or_non_text_id_is_refused(strategy_id: object) -> None:
    assert _codes(f4.strategy(strategy_id=strategy_id)) == [StrategyIssueCode.INVALID_STRATEGY_ID]  # type: ignore[arg-type]


@pytest.mark.parametrize("strategy_id", ["base", "Base", " BASE "])
def test_the_reserved_base_key_is_never_a_strategy_id(strategy_id: str) -> None:
    assert _codes(f4.strategy(strategy_id=strategy_id)) == [StrategyIssueCode.RESERVED_STRATEGY_ID]


@pytest.mark.parametrize("name", ["", "  ", None])
def test_a_blank_name_is_refused(name: object) -> None:
    assert _codes(f4.strategy(name=name)) == [StrategyIssueCode.INVALID_NAME]  # type: ignore[arg-type]


def test_a_description_is_optional_text() -> None:
    assert _issues(f4.strategy(description="Bid lower, renovate, hold longer.")) == ()
    assert _codes(f4.strategy(description=3)) == [StrategyIssueCode.INVALID_DESCRIPTION]  # type: ignore[arg-type]


def test_names_carry_no_meaning() -> None:
    for name in ("Base", "Downside", "Renovate", "Upside"):
        assert _issues(f4.strategy(f4.acquisition(UNIT), name=name)) == ()


# =============================================================================
# Overlays, domains and unit addressing
# =============================================================================


def test_a_malformed_overlay_collection_is_refused() -> None:
    listed = StrategyDefinition(strategy_id="s", name="n", overlays=[f4.acquisition(UNIT)])  # type: ignore[arg-type]
    assert [i.code for i in _issues(listed)] == [StrategyIssueCode.INVALID_OVERLAYS]
    mixed = StrategyDefinition(strategy_id="s", name="n", overlays=(f4.acquisition(UNIT), "financing"))  # type: ignore[arg-type]
    assert [i.code for i in _issues(mixed)] == [StrategyIssueCode.INVALID_OVERLAYS]


@pytest.mark.parametrize("token", ["unit_selection", "capital_structure", "partnership", "refinance", 3])
def test_every_later_gate_or_unknown_domain_is_refused(token: object) -> None:
    overlay = StrategyOverlay(unit_id=UNIT, domain=token, content=None)  # type: ignore[arg-type]
    (issue,) = _issues(f4.strategy(overlay))
    assert issue.code is StrategyIssueCode.UNSUPPORTED_DOMAIN
    assert issue.stage is StrategyIssueStage.STRATEGY
    assert "acquisition, financing, business_plan, operating_outcome, disposition" in issue.message


@pytest.mark.parametrize("unit", ["", "  ", None, 42])
def test_every_overlay_names_its_unit(unit: object) -> None:
    (issue,) = _issues(f4.strategy(f4.acquisition(unit)))  # type: ignore[arg-type]
    assert issue.code is StrategyIssueCode.INVALID_UNIT_ID
    assert "no investment-scoped overlay" in issue.message


def test_a_foreign_unit_is_refused_never_ignored_or_reassigned() -> None:
    (issue,) = _issues(f4.strategy(f4.acquisition(FOREIGN)))
    assert issue.code is StrategyIssueCode.UNIT_NOT_IN_VARIANT
    assert (issue.unit_id, issue.domain) == (FOREIGN, StrategyDomain.ACQUISITION)


def test_at_most_one_overlay_per_domain_and_unit() -> None:
    doubled = f4.strategy(f4.acquisition(UNIT), f4.acquisition(UNIT, purchase_price=9.0e6))
    (issue,) = _issues(doubled)
    assert issue.code is StrategyIssueCode.DUPLICATE_DOMAIN
    assert _issues(f4.strategy(f4.acquisition(UNIT), f4.acquisition(FOREIGN))) and [
        i.code for i in _issues(f4.strategy(f4.acquisition(UNIT), f4.acquisition(FOREIGN)))
    ] == [StrategyIssueCode.UNIT_NOT_IN_VARIANT]


def test_content_must_be_the_domains_own_contract() -> None:
    swapped = StrategyOverlay(
        unit_id=UNIT, domain=StrategyDomain.ACQUISITION,
        content=FinancingChoice(ltv=0.6, interest_rate=0.05, amortization=30, io_period=0, financing_fee_pct=0.0),
    )
    (issue,) = _issues(f4.strategy(swapped))
    assert issue.code is StrategyIssueCode.INVALID_CONTENT
    no_plan = StrategyOverlay(unit_id=UNIT, domain=StrategyDomain.BUSINESS_PLAN, content=None)  # type: ignore[arg-type]
    assert [i.code for i in _issues(f4.strategy(no_plan))] == [StrategyIssueCode.INVALID_CONTENT]


# =============================================================================
# Whole-domain overlays (ST-2) -- the whole-domain oracle
# =============================================================================


def test_acquisition_missing_its_cost_percentage_is_incomplete() -> None:
    (issue,) = _issues(f4.strategy(f4.acquisition(UNIT, acquisition_cost_pct=None)))
    assert (issue.code, issue.field, issue.domain) == (
        StrategyIssueCode.INCOMPLETE_DOMAIN, "acquisition_cost_pct", StrategyDomain.ACQUISITION,
    )
    assert "never inherited from Base" in issue.message


def test_financing_missing_amortization_is_incomplete() -> None:
    (issue,) = _issues(f4.strategy(f4.financing(UNIT, amortization=None)))
    assert (issue.code, issue.field, issue.domain) == (
        StrategyIssueCode.INCOMPLETE_DOMAIN, "amortization", StrategyDomain.FINANCING,
    )


def test_disposition_without_a_hold_period_is_incomplete() -> None:
    (issue,) = _issues(f4.strategy(f4.disposition(UNIT, None)))
    assert (issue.code, issue.field) == (StrategyIssueCode.INCOMPLETE_DOMAIN, "hold_period")


def test_every_missing_field_is_reported_in_declared_order() -> None:
    empty = FinancingChoice(ltv=None, interest_rate=None, amortization=None, io_period=None, financing_fee_pct=None)  # type: ignore[arg-type]
    overlay = StrategyOverlay(unit_id=UNIT, domain=StrategyDomain.FINANCING, content=empty)
    assert [(i.code, i.field) for i in _issues(f4.strategy(overlay))] == [
        (StrategyIssueCode.INCOMPLETE_DOMAIN, field) for field in STRATEGY_DOMAIN_FIELDS[StrategyDomain.FINANCING]
    ]


@pytest.mark.parametrize(
    "value",
    [True, "0.6", math.nan, math.inf, -math.inf, 10**400, [0.6]],
    ids=["bool", "text", "nan", "inf", "-inf", "overflow", "list"],
)
def test_a_whole_domain_value_must_be_a_finite_number(value: object) -> None:
    (issue,) = _issues(f4.strategy(f4.financing(UNIT, ltv=value)))
    assert (issue.code, issue.field) == (StrategyIssueCode.INVALID_NUMBER, "ltv")


@pytest.mark.parametrize("field", ["amortization", "io_period"])
def test_whole_years_are_whole_numbers(field: str) -> None:
    (issue,) = _issues(f4.strategy(f4.financing(UNIT, **{field: 2.5})))
    assert (issue.code, issue.field) == (StrategyIssueCode.INVALID_NUMBER, field)
    (issue,) = _issues(f4.strategy(f4.disposition(UNIT, 6.5)))
    assert (issue.code, issue.field) == (StrategyIssueCode.INVALID_NUMBER, "hold_period")


def test_structure_is_not_financial_validity() -> None:
    """A negative price or a 150% LTV is stored-valid: whether the variant
    underwrites is decided on the final inputs, by the existing validators."""

    assert _issues(f4.strategy(f4.acquisition(UNIT, purchase_price=-1.0), f4.financing(UNIT, ltv=1.5))) == ()


# =============================================================================
# The Business Plan overlay -- the D6 authority, unchanged
# =============================================================================


def test_an_invalid_replacement_plan_is_reported_by_the_d6_validator() -> None:
    item = CapitalPlanItem(item_id="x", description="Roof", category=CapitalItemCategory.OTHER, month=-1, amount=-5.0)
    plan = BusinessPlan(capital_items=(item, item))
    issues = _issues(f4.strategy(f4.plan_overlay(UNIT, plan)))
    assert issues
    assert {issue.code for issue in issues} == {StrategyIssueCode.INVALID_BUSINESS_PLAN}
    assert {issue.source_code for issue in issues} >= {"MONTH_OUT_OF_DOMAIN", "AMOUNT_OUT_OF_DOMAIN", "DUPLICATE_ITEM_ID"}
    assert all(issue.field.startswith("business_plan.capital_items[") for issue in issues)  # type: ignore[union-attr]


# =============================================================================
# The operating-outcome overlay -- SET over the Strategy whitelist
# =============================================================================


@pytest.mark.parametrize("mode", list(OperatingMode))
def test_every_approved_target_validates_with_set(mode: OperatingMode) -> None:
    for target in STRATEGY_OUTCOME_TARGETS[mode]:
        assert _issues(f4.strategy(f4.outcomes(UNIT, f4.outcome(target, 0.05))), mode) == (), target


def test_an_empty_outcome_overlay_is_incomplete() -> None:
    (issue,) = _issues(f4.strategy(f4.outcomes(UNIT)))
    assert issue.code is StrategyIssueCode.INCOMPLETE_DOMAIN


@pytest.mark.parametrize("operation", ["add", "scale", "cap_at"])
def test_a_strategy_outcome_uses_set_only(operation: str) -> None:
    (issue,) = _issues(f4.strategy(f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.06, operation))))
    assert (issue.code, issue.target) == (StrategyIssueCode.INVALID_OPERATION, ScenarioTarget.EXIT_CAP_RATE)
    assert "relative operations are Scenario operations" in issue.message


def test_an_unknown_operation_is_refused() -> None:
    (issue,) = _issues(f4.strategy(f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.06, "multiply"))))
    assert issue.code is StrategyIssueCode.INVALID_OPERATION


@pytest.mark.parametrize("target", ["interest_rate", "ltv"])
def test_financing_fields_are_never_operating_outcomes(target: str) -> None:
    (issue,) = _issues(f4.strategy(f4.outcomes(UNIT, f4.outcome(target, 0.05))))
    assert issue.code is StrategyIssueCode.UNSUPPORTED_TARGET
    assert "financing decision" in issue.message


@pytest.mark.parametrize(
    ("mode", "target"),
    [
        (OperatingMode.QUICK, "market_rent_psf"),
        (OperatingMode.QUICK, "revenue_growth"),
        (OperatingMode.DETAILED, "noi_growth"),
        (OperatingMode.DETAILED, "renewal_probability"),
        (OperatingMode.LEASE_LEVEL, "noi_growth"),
        (OperatingMode.LEASE_LEVEL, "vacancy_credit_loss_pct"),
    ],
)
def test_a_target_unavailable_to_the_mode_is_refused(mode: OperatingMode, target: str) -> None:
    (issue,) = _issues(f4.strategy(f4.outcomes(UNIT, f4.outcome(target, 0.05))), mode)
    assert issue.code is StrategyIssueCode.UNSUPPORTED_TARGET
    assert f"not a {mode.value} strategy operating outcome" in issue.message


@pytest.mark.parametrize("token", ["purchase_price", "hold_period", "business_plan", 5])
def test_a_token_outside_the_registry_is_refused(token: object) -> None:
    (issue,) = _issues(f4.strategy(f4.outcomes(UNIT, f4.outcome(token, 0.05))))
    assert issue.code is StrategyIssueCode.UNSUPPORTED_TARGET


def test_each_target_is_set_at_most_once() -> None:
    doubled = f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.06), f4.outcome("exit_cap_rate", 0.07))
    (issue,) = _issues(f4.strategy(doubled))
    assert (issue.code, issue.target) == (StrategyIssueCode.DUPLICATE_TARGET, ScenarioTarget.EXIT_CAP_RATE)


@pytest.mark.parametrize("value", [None, True, "0.06", math.nan, math.inf])
def test_an_outcome_value_is_a_finite_number(value: object) -> None:
    (issue,) = _issues(f4.strategy(f4.outcomes(UNIT, f4.outcome("exit_cap_rate", value))))
    assert issue.code is StrategyIssueCode.INVALID_NUMBER


def test_outcomes_must_be_a_tuple_of_outcomes() -> None:
    listed = StrategyOverlay(
        unit_id=UNIT, domain=StrategyDomain.OPERATING_OUTCOME,
        content=OperatingOutcomeSet(outcomes=[f4.outcome("exit_cap_rate", 0.06)]),  # type: ignore[arg-type]
    )
    assert [i.code for i in _issues(f4.strategy(listed))] == [StrategyIssueCode.INVALID_CONTENT]
    mixed = f4.outcomes(UNIT, f4.outcome("exit_cap_rate", 0.06), "noi_growth")  # type: ignore[arg-type]
    assert [i.code for i in _issues(f4.strategy(mixed))] == [StrategyIssueCode.INVALID_CONTENT]


# =============================================================================
# Deterministic issue order
# =============================================================================


def _many_problems() -> tuple[StrategyOverlay, ...]:
    return (
        f4.disposition(UNIT, None),
        f4.outcomes(
            UNIT,
            f4.outcome("renewal_probability", 0.5),
            f4.outcome("noi_growth", math.nan),
            f4.outcome("exit_cap_rate", 0.06, "add"),
        ),
        f4.financing(UNIT, amortization=None, ltv="x"),
        f4.acquisition(FOREIGN),
        f4.acquisition(UNIT, acquisition_cost_pct=None),
        StrategyOverlay(unit_id=UNIT, domain="partnership", content=None),  # type: ignore[arg-type]
        f4.plan_overlay(UNIT, BusinessPlan()),
        f4.plan_overlay(UNIT, BusinessPlan()),
    )


def test_issue_order_never_depends_on_overlay_or_outcome_order() -> None:
    overlays = _many_problems()
    expected = _issues(f4.strategy(*overlays, strategy_id="base"))
    for permutation in itertools.islice(itertools.permutations(overlays), 0, 40320, 997):
        assert _issues(f4.strategy(*permutation, strategy_id="base")) == expected


def test_issues_follow_identity_then_domain_declaration_order_then_unit_then_target() -> None:
    issues = _issues(f4.strategy(*_many_problems(), strategy_id="base"))
    assert [(issue.code, issue.domain, issue.unit_id, issue.target, issue.field) for issue in issues] == [
        (StrategyIssueCode.RESERVED_STRATEGY_ID, None, None, None, None),
        (StrategyIssueCode.UNSUPPORTED_DOMAIN, None, UNIT, None, None),
        (StrategyIssueCode.INCOMPLETE_DOMAIN, StrategyDomain.ACQUISITION, UNIT, None, "acquisition_cost_pct"),
        (StrategyIssueCode.UNIT_NOT_IN_VARIANT, StrategyDomain.ACQUISITION, FOREIGN, None, None),
        (StrategyIssueCode.INVALID_NUMBER, StrategyDomain.FINANCING, UNIT, None, "ltv"),
        (StrategyIssueCode.INCOMPLETE_DOMAIN, StrategyDomain.FINANCING, UNIT, None, "amortization"),
        (StrategyIssueCode.DUPLICATE_DOMAIN, StrategyDomain.BUSINESS_PLAN, UNIT, None, None),
        (StrategyIssueCode.INVALID_OPERATION, StrategyDomain.OPERATING_OUTCOME, UNIT, ScenarioTarget.EXIT_CAP_RATE, None),
        (StrategyIssueCode.INVALID_NUMBER, StrategyDomain.OPERATING_OUTCOME, UNIT, ScenarioTarget.NOI_GROWTH, None),
        (StrategyIssueCode.UNSUPPORTED_TARGET, StrategyDomain.OPERATING_OUTCOME, UNIT, ScenarioTarget.RENEWAL_PROBABILITY, None),
        (StrategyIssueCode.INCOMPLETE_DOMAIN, StrategyDomain.DISPOSITION, UNIT, None, "hold_period"),
    ]


# =============================================================================
# Caller errors and the error type
# =============================================================================


def test_caller_facts_are_programming_errors_not_issues() -> None:
    with pytest.raises(TypeError):
        validate_strategy("s", operating_mode=OperatingMode.QUICK, unit_id=UNIT)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validate_strategy(f4.strategy(), operating_mode="quick", unit_id=UNIT)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validate_strategy(f4.strategy(), operating_mode=OperatingMode.QUICK, unit_id=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        validate_strategy(f4.strategy(), operating_mode=OperatingMode.QUICK, unit_id="  ")


def test_the_error_carries_at_least_one_ordered_issue_and_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        StrategyValidationError(())
    with pytest.raises(TypeError):
        StrategyValidationError(("not an issue",))  # type: ignore[arg-type]
    issues = _issues(f4.strategy(strategy_id=""))
    error = StrategyValidationError(issues)
    assert isinstance(error, ValueError)
    assert error.issues == issues and str(error) == issues[0].message
