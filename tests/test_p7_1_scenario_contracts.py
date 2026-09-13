"""Phase 7 Gate P7.1 -- the Scenario contract and stage-1 validation.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 7.2 and
the P7.1 gate (Parts B-E, L, N, Y). Stage 1 judges the scenario itself:
identity, targets, operations, values, and whether each target applies to the
mode. Every refusal is a deterministic ``ScenarioIssue``, and an invalid
scenario never reaches the engine.
"""

from __future__ import annotations

import dataclasses
import itertools
import math

import pytest

from anchor.analysis import scenario as module
from anchor.analysis.scenario import (
    ResolvedDetailedInputs,
    ResolvedLeaseLevelInputs,
    ResolvedQuickInputs,
    ScenarioDefinition,
    ScenarioIssue,
    ScenarioIssueCode,
    ScenarioIssueStage,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    ScenarioTargetSpec,
    ScenarioValidationError,
    resolve_detailed_scenario,
    resolve_lease_level_scenario,
    resolve_quick_scenario,
    validate_scenario,
)
from anchor.business_plan import BusinessPlan
from anchor.contracts import OperatingMode

from _p7_1_scenario_fixtures import (
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


def ov(target: object, operation: object, value: object) -> ScenarioOverride:
    return ScenarioOverride(target=target, operation=operation, value=value)  # type: ignore[arg-type]


def scenario(
    *overrides: ScenarioOverride,
    scenario_id: object = "scn-1",
    name: object = "Any analyst view",
    description: object = None,
) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id=scenario_id,  # type: ignore[arg-type]
        name=name,  # type: ignore[arg-type]
        description=description,  # type: ignore[arg-type]
        overrides=tuple(overrides),
    )


def codes(issues: tuple[ScenarioIssue, ...]) -> list[ScenarioIssueCode]:
    return [issue.code for issue in issues]


# =============================================================================
# The contract shape
# =============================================================================


@pytest.mark.parametrize(
    ("cls", "fields"),
    [
        (ScenarioDefinition, ["scenario_id", "name", "description", "overrides"]),
        (ScenarioOverride, ["target", "operation", "value"]),
        (ScenarioIssue, ["stage", "code", "message", "target", "field", "source_code"]),
        (ScenarioTargetSpec, ["target", "allowed_operations", "owner_fields", "units"]),
        (ResolvedQuickInputs, ["inputs", "business_plan"]),
        (ResolvedDetailedInputs, ["terms", "detailed_operating_inputs", "business_plan"]),
        (
            ResolvedLeaseLevelInputs,
            [
                "terms",
                "property_inputs",
                "suites",
                "leases",
                "market_leasing",
                "operating_inputs",
                "business_plan",
            ],
        ),
    ],
)
def test_every_contract_is_a_frozen_slotted_keyword_only_dataclass(
    cls: type, fields: list[str]
) -> None:
    assert [field.name for field in dataclasses.fields(cls)] == fields
    params = cls.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen
    assert "__slots__" in cls.__dict__
    assert all(field.kw_only for field in dataclasses.fields(cls))


def test_contracts_are_immutable() -> None:
    definition = scenario(ov(T.LTV, Op.CAP_AT, 0.55))
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.name = "changed"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.overrides[0].value = 0.6  # type: ignore[misc]


def test_the_operations_are_exactly_the_four_ratified_operations() -> None:
    assert [op.name for op in ScenarioOperation] == ["SET", "ADD", "SCALE", "CAP_AT"]
    assert [op.value for op in ScenarioOperation] == ["set", "add", "scale", "cap_at"]


def test_only_description_and_overrides_default() -> None:
    required = [
        field.name
        for field in dataclasses.fields(ScenarioDefinition)
        if field.default is dataclasses.MISSING
        and field.default_factory is dataclasses.MISSING
    ]
    assert required == ["scenario_id", "name"]
    assert ScenarioDefinition(scenario_id="s", name="n").overrides == ()


# =============================================================================
# Valid scenarios
# =============================================================================


@pytest.mark.parametrize(
    ("mode", "definition"),
    [
        (Q, scenario()),
        (Q, scenario(ov(T.NOI_GROWTH, Op.ADD, -0.01), ov(T.LTV, Op.CAP_AT, 0.55))),
        (D, scenario(ov(T.VACANCY_CREDIT_LOSS_PCT, Op.SET, 0.08), ov(T.EXIT_CAP_RATE, Op.SCALE, 1.05))),
        (L, scenario(ov(T.MARKET_RENT_PSF, Op.CAP_AT, 40), ov(T.RENEWAL_PROBABILITY, Op.SCALE, 0.8))),
    ],
)
def test_a_valid_scenario_has_no_issues(mode: OperatingMode, definition: ScenarioDefinition) -> None:
    assert validate_scenario(definition, operating_mode=mode) == ()


def test_an_empty_description_is_allowed_context() -> None:
    assert validate_scenario(scenario(description=""), operating_mode=Q) == ()
    assert validate_scenario(scenario(description="Analyst notes"), operating_mode=Q) == ()


# =============================================================================
# Identity and naming
# =============================================================================


@pytest.mark.parametrize("bad", ["", "   ", "\t\n", None, 7, b"id"])
def test_a_blank_or_non_string_scenario_id_is_invalid(bad: object) -> None:
    issues = validate_scenario(scenario(scenario_id=bad), operating_mode=Q)
    assert codes(issues) == [ScenarioIssueCode.INVALID_SCENARIO_ID]
    assert issues[0].stage is ScenarioIssueStage.SCENARIO


@pytest.mark.parametrize("bad", ["", "  ", None, 3.5])
def test_a_blank_or_non_string_name_is_invalid(bad: object) -> None:
    assert codes(validate_scenario(scenario(name=bad), operating_mode=Q)) == [
        ScenarioIssueCode.INVALID_SCENARIO_NAME
    ]


def test_a_non_string_description_is_invalid() -> None:
    assert codes(validate_scenario(scenario(description=5), operating_mode=Q)) == [
        ScenarioIssueCode.INVALID_DESCRIPTION
    ]


def test_names_are_arbitrary_text_with_no_reserved_values() -> None:
    for name in ("Base", "Downside", "Upside", "Recession 2027", "x", "BASE"):
        assert validate_scenario(scenario(name=name), operating_mode=Q) == ()


# =============================================================================
# The override collection and its targets
# =============================================================================


def test_overrides_must_be_a_tuple() -> None:
    definition = ScenarioDefinition(
        scenario_id="s",
        name="n",
        overrides=[ov(T.LTV, Op.CAP_AT, 0.55)],  # type: ignore[arg-type]
    )
    assert codes(validate_scenario(definition, operating_mode=Q)) == [
        ScenarioIssueCode.INVALID_OVERRIDES
    ]


def test_every_override_must_be_a_scenario_override() -> None:
    definition = ScenarioDefinition(
        scenario_id="s",
        name="n",
        overrides=({"target": "ltv", "operation": "cap_at", "value": 0.5},),  # type: ignore[arg-type]
    )
    assert codes(validate_scenario(definition, operating_mode=Q)) == [
        ScenarioIssueCode.INVALID_OVERRIDES
    ]


@pytest.mark.parametrize("target", ["exit_cap_rate", "purchase_price", "terms.ltv", None, 3])
def test_a_target_outside_the_registry_enum_is_refused(target: object) -> None:
    """A plain string is not a target, even when it spells a real one: there is
    no string-path or field-name route into resolution."""

    issues = validate_scenario(scenario(ov(target, Op.SET, 0.07)), operating_mode=Q)
    assert codes(issues) == [ScenarioIssueCode.UNKNOWN_TARGET]
    assert issues[0].target is None


def test_a_duplicate_target_is_refused_once_and_never_composed() -> None:
    """ADD then SCALE on one target would make the scenario's meaning depend on
    row order. It is refused, not composed, and not resolved last-wins."""

    issues = validate_scenario(
        scenario(ov(T.EXIT_CAP_RATE, Op.ADD, 0.005), ov(T.EXIT_CAP_RATE, Op.SCALE, 1.1)),
        operating_mode=Q,
    )
    assert codes(issues) == [ScenarioIssueCode.DUPLICATE_TARGET]
    assert issues[0].target is T.EXIT_CAP_RATE


def test_a_duplicate_is_refused_even_when_both_rows_agree() -> None:
    issues = validate_scenario(
        scenario(ov(T.LTV, Op.CAP_AT, 0.55), ov(T.LTV, Op.CAP_AT, 0.55)), operating_mode=D
    )
    assert codes(issues) == [ScenarioIssueCode.DUPLICATE_TARGET]


@pytest.mark.parametrize(
    "resolve",
    [
        lambda s: resolve_quick_scenario(quick_inputs(), scenario=s, business_plan=BusinessPlan()),
        lambda s: resolve_detailed_scenario(
            detailed_terms(), detailed_operating(), scenario=s, business_plan=BusinessPlan()
        ),
        lambda s: resolve_lease_level_scenario(
            lease_level_terms(),
            lease_level_property(),
            *rent_roll(),
            market_leasing=market(),
            operating_inputs=lease_level_operating(),
            scenario=s,
            business_plan=BusinessPlan(),
        ),
    ],
    ids=["quick", "detailed", "lease_level"],
)
def test_a_duplicate_never_silently_resolves_to_either_row(resolve) -> None:  # type: ignore[no-untyped-def]
    duplicate = scenario(ov(T.INTEREST_RATE, Op.SET, 0.07), ov(T.INTEREST_RATE, Op.SET, 0.08))
    with pytest.raises(ScenarioValidationError) as excinfo:
        resolve(duplicate)
    assert codes(excinfo.value.issues) == [ScenarioIssueCode.DUPLICATE_TARGET]


# =============================================================================
# Operations
# =============================================================================


@pytest.mark.parametrize(
    ("mode", "target", "operation"),
    [
        (Q, T.LTV, Op.SET),
        (Q, T.LTV, Op.ADD),
        (Q, T.LTV, Op.SCALE),
        (Q, T.EXIT_CAP_RATE, Op.CAP_AT),
        (D, T.INTEREST_RATE, Op.CAP_AT),
        (Q, T.NOI_GROWTH, Op.SCALE),
        (D, T.EXPENSE_GROWTH, Op.CAP_AT),
        (L, T.RECOVERABLE_EXPENSE_RATIO, Op.SCALE),
    ],
)
def test_an_operation_outside_the_targets_whitelist_is_refused(
    mode: OperatingMode, target: ScenarioTarget, operation: ScenarioOperation
) -> None:
    issues = validate_scenario(scenario(ov(target, operation, 0.05)), operating_mode=mode)
    assert codes(issues) == [ScenarioIssueCode.OPERATION_NOT_ALLOWED]
    assert issues[0].target is target
    assert operation.value in issues[0].message


def test_a_disallowed_operation_never_falls_back_to_set() -> None:
    with pytest.raises(ScenarioValidationError) as excinfo:
        resolve_quick_scenario(
            quick_inputs(), scenario=scenario(ov(T.LTV, Op.SET, 0.5)), business_plan=BusinessPlan()
        )
    assert codes(excinfo.value.issues) == [ScenarioIssueCode.OPERATION_NOT_ALLOWED]


@pytest.mark.parametrize("operation", ["set", "SET", "min", None, 1])
def test_an_operation_outside_the_enum_is_refused(operation: object) -> None:
    issues = validate_scenario(scenario(ov(T.EXIT_CAP_RATE, operation, 0.07)), operating_mode=Q)
    assert codes(issues) == [ScenarioIssueCode.UNKNOWN_OPERATION]


# =============================================================================
# Mode applicability
# =============================================================================


@pytest.mark.parametrize(
    ("mode", "target", "operation"),
    [
        (D, T.NOI_GROWTH, Op.ADD),
        (L, T.NOI_GROWTH, Op.ADD),
        (Q, T.REVENUE_GROWTH, Op.ADD),
        (L, T.REVENUE_GROWTH, Op.ADD),
        (Q, T.VACANCY_CREDIT_LOSS_PCT, Op.ADD),
        (L, T.VACANCY_CREDIT_LOSS_PCT, Op.ADD),
        (Q, T.EXPENSE_GROWTH, Op.ADD),
        (Q, T.MARKET_RENT_PSF, Op.SCALE),
        (D, T.MARKET_RENT_PSF, Op.SCALE),
        (Q, T.RENEWAL_PROBABILITY, Op.SET),
        (D, T.RECOVERABLE_EXPENSE_RATIO, Op.SET),
    ],
)
def test_a_target_the_mode_does_not_have_is_refused_never_ignored(
    mode: OperatingMode, target: ScenarioTarget, operation: ScenarioOperation
) -> None:
    issues = validate_scenario(scenario(ov(target, operation, 0.02)), operating_mode=mode)
    assert codes(issues) == [ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE]
    assert issues[0].target is target
    assert mode.value in issues[0].message


# =============================================================================
# Values
# =============================================================================


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (math.nan, ScenarioIssueCode.NON_FINITE_VALUE),
        (math.inf, ScenarioIssueCode.NON_FINITE_VALUE),
        (-math.inf, ScenarioIssueCode.NON_FINITE_VALUE),
        (10**400, ScenarioIssueCode.NON_FINITE_VALUE),
        (True, ScenarioIssueCode.NON_NUMERIC_VALUE),
        (False, ScenarioIssueCode.NON_NUMERIC_VALUE),
        ("0.07", ScenarioIssueCode.NON_NUMERIC_VALUE),
        (None, ScenarioIssueCode.NON_NUMERIC_VALUE),
        ([0.07], ScenarioIssueCode.NON_NUMERIC_VALUE),
    ],
)
def test_a_non_finite_or_non_numeric_value_is_refused(value: object, code: ScenarioIssueCode) -> None:
    issues = validate_scenario(scenario(ov(T.EXIT_CAP_RATE, Op.SET, value)), operating_mode=Q)
    assert codes(issues) == [code]
    assert issues[0].target is T.EXIT_CAP_RATE


@pytest.mark.parametrize("value", [0, 1, 40, -3, 0.0, 1e-9])
def test_finite_ints_and_floats_are_numeric(value: float) -> None:
    assert validate_scenario(scenario(ov(T.MARKET_RENT_PSF, Op.ADD, value)), operating_mode=L) == ()


def test_one_override_reports_every_defect_it_has_in_a_fixed_order() -> None:
    issues = validate_scenario(scenario(ov(T.MARKET_RENT_PSF, Op.SET, math.nan)), operating_mode=Q)
    assert codes(issues) == [
        ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE,
        ScenarioIssueCode.NON_FINITE_VALUE,
    ]
    issues = validate_scenario(scenario(ov(T.LTV, Op.ADD, True)), operating_mode=Q)
    assert codes(issues) == [
        ScenarioIssueCode.OPERATION_NOT_ALLOWED,
        ScenarioIssueCode.NON_NUMERIC_VALUE,
    ]


# =============================================================================
# Determinism
# =============================================================================


def test_issue_order_does_not_depend_on_override_row_order() -> None:
    rows = [
        ov(T.RECOVERABLE_EXPENSE_RATIO, Op.SET, math.inf),
        ov(T.LTV, Op.SET, 0.5),
        ov("purchase_price", Op.SET, 1.0),
        ov(T.EXIT_CAP_RATE, Op.ADD, 0.01),
        ov(T.EXIT_CAP_RATE, Op.ADD, 0.02),
        ov(T.NOI_GROWTH, Op.ADD, 0.01),
        ov("hold_period", Op.SET, 7),
    ]
    results = {
        validate_scenario(scenario(*permutation), operating_mode=D)
        for permutation in itertools.permutations(rows)
    }
    assert len(results) == 1
    (issues,) = results
    assert codes(issues) == [
        ScenarioIssueCode.UNKNOWN_TARGET,
        ScenarioIssueCode.UNKNOWN_TARGET,
        ScenarioIssueCode.DUPLICATE_TARGET,
        ScenarioIssueCode.OPERATION_NOT_ALLOWED,
        ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE,
        ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE,
        ScenarioIssueCode.NON_FINITE_VALUE,
    ]
    assert [issue.target for issue in issues] == [
        None,
        None,
        T.EXIT_CAP_RATE,
        T.LTV,
        T.NOI_GROWTH,
        T.RECOVERABLE_EXPENSE_RATIO,
        T.RECOVERABLE_EXPENSE_RATIO,
    ]


def test_header_issues_come_before_override_issues() -> None:
    issues = validate_scenario(
        scenario(ov(T.LTV, Op.SET, 0.5), scenario_id="", name=""), operating_mode=Q
    )
    assert codes(issues) == [
        ScenarioIssueCode.INVALID_SCENARIO_ID,
        ScenarioIssueCode.INVALID_SCENARIO_NAME,
        ScenarioIssueCode.OPERATION_NOT_ALLOWED,
    ]


# =============================================================================
# The error contract
# =============================================================================


def test_the_validation_error_carries_ordered_issues_and_is_a_value_error() -> None:
    first = module._scenario_issue(ScenarioIssueCode.INVALID_SCENARIO_ID, "first")
    second = module._scenario_issue(ScenarioIssueCode.INVALID_SCENARIO_NAME, "second")
    error = ScenarioValidationError([first, second])
    assert isinstance(error, ValueError)
    assert error.issues == (first, second)
    assert str(error) == "first\nsecond"
    assert str(first) == "first"


def test_the_validation_error_requires_issues() -> None:
    with pytest.raises(ValueError, match="at least one issue"):
        ScenarioValidationError([])
    with pytest.raises(TypeError):
        ScenarioValidationError(["not an issue"])  # type: ignore[list-item]


def test_validation_refuses_a_non_scenario_or_a_non_mode_argument() -> None:
    with pytest.raises(TypeError):
        validate_scenario({"scenario_id": "s"}, operating_mode=Q)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validate_scenario(scenario(), operating_mode="quick")  # type: ignore[arg-type]


def test_resolvers_refuse_a_wrong_input_contract() -> None:
    with pytest.raises(TypeError):
        resolve_quick_scenario(
            detailed_terms(), scenario=scenario(), business_plan=BusinessPlan()  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        resolve_quick_scenario(quick_inputs(), scenario=scenario(), business_plan=None)  # type: ignore[arg-type]
