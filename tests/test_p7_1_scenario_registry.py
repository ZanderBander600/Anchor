"""Phase 7 Gate P7.1 -- the ScenarioTarget registry, table-driven (Part AD).

This table is the P7.1 registry decision (Section 21.3). A developer who adds a
target, widens a whitelist or extends a target to another mode must change
this file on purpose. Each target is proven three ways: its modes, the
operations it allows, and the exact contract field its resolver writes. The
last is checked behaviourally, and nothing else in any input contract may
move.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType
from typing import Any, Iterator

import pytest

from anchor.analysis.lease_level_sensitivity import LEASE_LEVEL_SUPPORTED_ASSUMPTIONS
from anchor.analysis.lease_level_sensitivity import _TARGETS as _LEASE_LEVEL_SENSITIVITY_TARGETS
from anchor.analysis.scenario import (
    SCENARIO_TARGET_REGISTRY,
    ScenarioDefinition,
    ScenarioIssueCode,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    resolve_detailed_scenario,
    resolve_lease_level_scenario,
    resolve_quick_scenario,
    validate_scenario,
)
from anchor.analysis.sensitivity import DETAILED_SUPPORTED_ASSUMPTIONS, SUPPORTED_ASSUMPTIONS
from anchor.contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
)
from anchor.leasing import LeaseLevelOperatingInputs, MarketLeasingAssumptions

from _p7_1_scenario_fixtures import (
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
_ALL_OPERATIONS = frozenset(ScenarioOperation)

#: THE P7.1 REGISTRY. (modes, allowed operations) per target.
_EXPECTED: dict[ScenarioTarget, tuple[frozenset[OperatingMode], frozenset[ScenarioOperation]]] = {
    T.EXIT_CAP_RATE: (frozenset({Q, D, L}), frozenset({Op.SET, Op.ADD, Op.SCALE})),
    T.INTEREST_RATE: (frozenset({Q, D, L}), frozenset({Op.SET, Op.ADD, Op.SCALE})),
    T.LTV: (frozenset({Q, D, L}), frozenset({Op.CAP_AT})),
    T.NOI_GROWTH: (frozenset({Q}), frozenset({Op.SET, Op.ADD})),
    T.REVENUE_GROWTH: (frozenset({D}), frozenset({Op.SET, Op.ADD})),
    T.VACANCY_CREDIT_LOSS_PCT: (frozenset({D}), frozenset({Op.SET, Op.ADD})),
    T.EXPENSE_GROWTH: (frozenset({D, L}), frozenset({Op.SET, Op.ADD})),
    T.MARKET_RENT_PSF: (frozenset({L}), _ALL_OPERATIONS),
    T.RENEWAL_PROBABILITY: (frozenset({L}), _ALL_OPERATIONS),
    T.RECOVERABLE_EXPENSE_RATIO: (frozenset({L}), frozenset({Op.SET, Op.ADD})),
}

#: The one field each (target, mode) resolver writes, as leaf paths into the
#: resolved bundle, and the owning contract class name the registry must cite.
#: The Lease-Level default rent roll gives suite B (index 1) a scalar market
#: rent, so a unit-wide market-rent target writes it too.
_OWNER: dict[tuple[ScenarioTarget, OperatingMode], tuple[set[str], str]] = {
    (T.EXIT_CAP_RATE, Q): ({"inputs.exit_cap_rate"}, "AcquisitionInputs"),
    (T.EXIT_CAP_RATE, D): ({"terms.exit_cap_rate"}, "AcquisitionTerms"),
    (T.EXIT_CAP_RATE, L): ({"terms.exit_cap_rate"}, "AcquisitionTerms"),
    (T.INTEREST_RATE, Q): ({"inputs.interest_rate"}, "AcquisitionInputs"),
    (T.INTEREST_RATE, D): ({"terms.interest_rate"}, "AcquisitionTerms"),
    (T.INTEREST_RATE, L): ({"terms.interest_rate"}, "AcquisitionTerms"),
    (T.LTV, Q): ({"inputs.ltv"}, "AcquisitionInputs"),
    (T.LTV, D): ({"terms.ltv"}, "AcquisitionTerms"),
    (T.LTV, L): ({"terms.ltv"}, "AcquisitionTerms"),
    (T.NOI_GROWTH, Q): ({"inputs.noi_growth"}, "AcquisitionInputs"),
    (T.REVENUE_GROWTH, D): ({"detailed_operating_inputs.revenue_growth"}, "DetailedOperatingInputs"),
    (T.VACANCY_CREDIT_LOSS_PCT, D): (
        {"detailed_operating_inputs.vacancy_credit_loss_pct"},
        "DetailedOperatingInputs",
    ),
    (T.EXPENSE_GROWTH, D): ({"detailed_operating_inputs.expense_growth"}, "DetailedOperatingInputs"),
    (T.EXPENSE_GROWTH, L): ({"operating_inputs.expense_growth"}, "LeaseLevelOperatingInputs"),
    (T.MARKET_RENT_PSF, L): (
        {"market_leasing.market_rent_psf", "suites[1].market_rent_psf"},
        "MarketLeasingAssumptions",
    ),
    (T.RENEWAL_PROBABILITY, L): ({"market_leasing.renewal_probability"}, "MarketLeasingAssumptions"),
    (T.RECOVERABLE_EXPENSE_RATIO, L): (
        {"operating_inputs.recoverable_expense_ratio"},
        "LeaseLevelOperatingInputs",
    ),
}

#: One distinctive, valid, allowed operation per target, for the authority
#: proof. LTV allows only CAP_AT, so it caps below every fixture's base LTV.
_PROBE: dict[ScenarioTarget, tuple[ScenarioOperation, float]] = {
    T.EXIT_CAP_RATE: (Op.SET, 0.0711),
    T.INTEREST_RATE: (Op.SET, 0.0633),
    T.LTV: (Op.CAP_AT, 0.41),
    T.NOI_GROWTH: (Op.SET, 0.0123),
    T.REVENUE_GROWTH: (Op.SET, 0.0234),
    T.VACANCY_CREDIT_LOSS_PCT: (Op.SET, 0.0777),
    T.EXPENSE_GROWTH: (Op.SET, 0.0345),
    T.MARKET_RENT_PSF: (Op.SET, 44.4),
    T.RENEWAL_PROBABILITY: (Op.SET, 0.444),
    T.RECOVERABLE_EXPENSE_RATIO: (Op.SET, 0.777),
}

_CONTRACT_CLASSES = {
    "AcquisitionInputs": AcquisitionInputs,
    "AcquisitionTerms": AcquisitionTerms,
    "DetailedOperatingInputs": DetailedOperatingInputs,
    "LeaseLevelOperatingInputs": LeaseLevelOperatingInputs,
    "MarketLeasingAssumptions": MarketLeasingAssumptions,
}


def _one(target: ScenarioTarget, operation: ScenarioOperation, value: float) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id="probe",
        name="probe",
        overrides=(ScenarioOverride(target=target, operation=operation, value=value),),
    )


def _bases() -> dict[OperatingMode, Any]:
    suites, leases = rent_roll()
    plan = business_plan()
    return {
        Q: lambda s: resolve_quick_scenario(quick_inputs(), scenario=s, business_plan=plan),
        D: lambda s: resolve_detailed_scenario(
            detailed_terms(), detailed_operating(), scenario=s, business_plan=plan
        ),
        L: lambda s: resolve_lease_level_scenario(
            lease_level_terms(),
            lease_level_property(),
            suites,
            leases,
            market_leasing=market(),
            operating_inputs=lease_level_operating(),
            scenario=s,
            business_plan=plan,
        ),
    }


def _leaves(value: object, prefix: str = "") -> Iterator[tuple[str, object]]:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            path = f"{prefix}.{field.name}" if prefix else field.name
            yield from _leaves(getattr(value, field.name), path)
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


# =============================================================================
# The table itself
# =============================================================================


def test_the_registry_is_exactly_this_table() -> None:
    assert set(ScenarioTarget) == set(_EXPECTED)
    assert list(SCENARIO_TARGET_REGISTRY) == list(ScenarioTarget)
    for target, (modes, operations) in _EXPECTED.items():
        spec = SCENARIO_TARGET_REGISTRY[target]
        assert spec.target is target
        assert spec.modes == modes, target
        assert spec.allowed_operations == operations, target
        assert spec.units.strip(), target


def test_the_registry_and_each_owner_table_are_read_only() -> None:
    assert isinstance(SCENARIO_TARGET_REGISTRY, MappingProxyType)
    with pytest.raises(TypeError):
        SCENARIO_TARGET_REGISTRY[T.LTV] = SCENARIO_TARGET_REGISTRY[T.EXIT_CAP_RATE]  # type: ignore[index]
    for spec in SCENARIO_TARGET_REGISTRY.values():
        assert isinstance(spec.owner_fields, MappingProxyType)
        assert isinstance(spec.allowed_operations, frozenset)


def test_no_target_allows_every_operation_by_default() -> None:
    """Whitelists are chosen per target (Q5). Only the two targets the gate
    ratified with all four operations carry all four."""

    everything = {target for target, spec in SCENARIO_TARGET_REGISTRY.items()
                  if spec.allowed_operations == _ALL_OPERATIONS}
    assert everything == {T.MARKET_RENT_PSF, T.RENEWAL_PROBABILITY}


def test_cap_at_is_an_upper_cap_offered_only_where_availability_or_a_ceiling_is_meaningful() -> None:
    assert {t for t, s in SCENARIO_TARGET_REGISTRY.items() if Op.CAP_AT in s.allowed_operations} == {
        T.LTV,
        T.MARKET_RENT_PSF,
        T.RENEWAL_PROBABILITY,
    }
    assert SCENARIO_TARGET_REGISTRY[T.LTV].allowed_operations == {Op.CAP_AT}


# =============================================================================
# Per target: modes, allowed operations, rejected operations, authority
# =============================================================================

_APPLICABLE = [(t, m) for t, (modes, _) in _EXPECTED.items() for m in sorted(modes)]
_NOT_APPLICABLE = [
    (t, m) for t, (modes, _) in _EXPECTED.items() for m in OperatingMode if m not in modes
]
_REJECTED = [
    (t, m, op)
    for t, (modes, ops) in _EXPECTED.items()
    for m in sorted(modes)
    for op in ScenarioOperation
    if op not in ops
]
_ALLOWED = [
    (t, m, op) for t, (modes, ops) in _EXPECTED.items() for m in sorted(modes) for op in sorted(ops)
]


@pytest.mark.parametrize(("target", "mode", "operation"), _ALLOWED)
def test_every_allowed_operation_is_valid_in_every_applicable_mode(
    target: ScenarioTarget, mode: OperatingMode, operation: ScenarioOperation
) -> None:
    assert validate_scenario(_one(target, operation, 0.5), operating_mode=mode) == ()


@pytest.mark.parametrize(("target", "mode", "operation"), _REJECTED)
def test_every_other_operation_is_rejected(
    target: ScenarioTarget, mode: OperatingMode, operation: ScenarioOperation
) -> None:
    issues = validate_scenario(_one(target, operation, 0.5), operating_mode=mode)
    assert [issue.code for issue in issues] == [ScenarioIssueCode.OPERATION_NOT_ALLOWED]


@pytest.mark.parametrize(("target", "mode"), _NOT_APPLICABLE)
def test_every_target_is_refused_outside_its_modes(
    target: ScenarioTarget, mode: OperatingMode
) -> None:
    operation, value = _PROBE[target]
    issues = validate_scenario(_one(target, operation, value), operating_mode=mode)
    assert [issue.code for issue in issues] == [ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE]


@pytest.mark.parametrize(("target", "mode"), _APPLICABLE)
def test_every_target_resolves_exactly_its_owner_field_and_nothing_else(
    target: ScenarioTarget, mode: OperatingMode
) -> None:
    """The deterministic resolver authority, proven behaviourally. Probing one
    target moves exactly its documented field(s). Every other leaf of every
    input contract, the Business Plan included, stays bit-identical."""

    operation, value = _PROBE[target]
    resolve = _bases()[mode]
    base = dict(_leaves(resolve(ScenarioDefinition(scenario_id="b", name="b"))))
    resolved = dict(_leaves(resolve(_one(target, operation, value))))

    assert base.keys() == resolved.keys()
    changed = {path for path in base if repr(base[path]) != repr(resolved[path])}
    paths, owner = _OWNER[(target, mode)]
    assert changed == paths
    for path in paths:
        assert resolved[path] == value
        assert type(resolved[path]) is float

    spec = SCENARIO_TARGET_REGISTRY[target]
    field = target.value
    assert spec.owner_fields[mode].startswith(f"{owner}.{field}")
    assert field in {f.name for f in dataclasses.fields(_CONTRACT_CLASSES[owner])}


def test_the_owner_table_covers_every_applicable_pair_and_no_other() -> None:
    assert set(_OWNER) == set(_APPLICABLE)
    assert set(_PROBE) == set(ScenarioTarget)


# =============================================================================
# Coherence with sensitivity, and the excluded targets
# =============================================================================


def test_a_target_sharing_a_sensitivity_name_means_the_same_field_of_the_same_contract() -> None:
    """Section 7.3: where a scenario target and a sensitivity target share a
    name, they are the same field of the same contract. Their *reach* may
    differ on purpose. Lease-Level market-rent sensitivity refuses a shadowed
    default; the scenario reaches every suite's resolved rent (Q10)."""

    owner_by_sensitivity_role = {
        "terms": "AcquisitionTerms",
        "market_leasing": "MarketLeasingAssumptions",
        "operating_inputs": "LeaseLevelOperatingInputs",
    }
    shared = 0
    for target in ScenarioTarget:
        spec = SCENARIO_TARGET_REGISTRY[target]
        if target.value in SUPPORTED_ASSUMPTIONS and Q in spec.modes:
            assert spec.owner_fields[Q] == f"AcquisitionInputs.{target.value}"
            shared += 1
        if target.value in DETAILED_SUPPORTED_ASSUMPTIONS and D in spec.modes:
            assert spec.owner_fields[D] == f"AcquisitionTerms.{target.value}"
            shared += 1
        if target.value in LEASE_LEVEL_SUPPORTED_ASSUMPTIONS and L in spec.modes:
            role = _LEASE_LEVEL_SENSITIVITY_TARGETS[target.value].owner.value
            assert spec.owner_fields[L].startswith(
                f"{owner_by_sensitivity_role[role]}.{target.value}"
            )
            shared += 1
    assert shared == 4 + 3 + 7


#: Strategy decisions and structure. None may be a P7.1 scenario target.
_EXCLUDED = (
    "purchase_price",
    "hold_period",
    "amortization",
    "io_period",
    "acquisition_cost_pct",
    "financing_fee_pct",
    "disposition_cost_pct",
    "annual_capex_reserve",
    "current_noi",
    "occupancy",
    "project_capital_cost_scale",
    "project_capital_delay_months",
    "business_plan",
    "capital_items",
    "owner_expense_items",
    "market_rent_growth",
    "renewal_rent_psf",
    "analysis_start_date",
)


@pytest.mark.parametrize("name", _EXCLUDED)
def test_decisions_and_structure_are_not_scenario_targets(name: str) -> None:
    assert name not in {target.value for target in ScenarioTarget}
    assert name.upper() not in ScenarioTarget.__members__
    for mode in OperatingMode:
        issues = validate_scenario(_one(name, Op.SET, 1.0), operating_mode=mode)  # type: ignore[arg-type]
        assert [issue.code for issue in issues] == [ScenarioIssueCode.UNKNOWN_TARGET]


def test_purchase_price_is_a_sensitivity_input_but_never_a_scenario_target() -> None:
    """Sensitivity may perturb the bid; a Scenario may not, because the bid is
    the analyst's decision (Section 7.1, Strategy)."""

    assert "purchase_price" in SUPPORTED_ASSUMPTIONS
    assert "purchase_price" in DETAILED_SUPPORTED_ASSUMPTIONS
    assert "purchase_price" in LEASE_LEVEL_SUPPORTED_ASSUMPTIONS
    assert all("PRICE" not in member for member in ScenarioTarget.__members__)
    assert all("purchase" not in spec.owner_fields.get(m, "") for spec in SCENARIO_TARGET_REGISTRY.values() for m in OperatingMode)
