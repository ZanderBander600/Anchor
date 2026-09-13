"""Phase 7 Gate P7.1 -- Lease-Level unit-wide market rent (Part I, Part X).

Ratified for P7.1 (Q10 extended by the gate): ``MARKET_RENT_PSF`` is a unit-wide
target over **resolved** suite market rents. SET, ADD, SCALE and CAP_AT all act
on every suite, whether its rent comes from the property default, a scalar
``Suite.market_rent_psf`` override, or a full ``market_leasing_override``.
The stored configuration never changes; resolution returns a new one.

The oracle rent roll covers every precedence path of
``leasing.market.resolve_market_leasing``:

====  ==============================================  ================
Suite  configuration                                   resolved rent
====  ==============================================  ================
A      property default (36)                           36
B      scalar override 42                              42
C      full override 50                                50
D      full override 55 **and** scalar 60              60 (scalar wins)
====  ==============================================  ================
"""

from __future__ import annotations

import copy
import dataclasses

import pytest

from anchor.analysis.business_plan_analysis import analyze_lease_level_acquisition_with_business_plan
from anchor.analysis.scenario import (
    ScenarioDefinition,
    ScenarioIssueCode,
    ScenarioIssueStage,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    ScenarioValidationError,
    analyze_lease_level_acquisition_with_scenario,
    resolve_lease_level_scenario,
)
from anchor.leasing import MarketLeasingAssumptions, Suite
from anchor.leasing.market import resolve_market_leasing

from _p7_1_scenario_fixtures import (
    UNIT,
    business_plan,
    lease_level_operating,
    lease_level_property,
    lease_level_terms,
    market,
    rent_roll,
)

Op = ScenarioOperation
MARKET_RENT = ScenarioTarget.MARKET_RENT_PSF

DEFAULT_RENT = 36.0
B_SCALAR = 42.0
C_OVERRIDE = 50.0
D_OVERRIDE = 55.0
D_SCALAR = 60.0


def oracle_roll():  # type: ignore[no-untyped-def]
    return rent_roll(
        b_market_rent_psf=B_SCALAR,
        c_override=market(market_rent_psf=C_OVERRIDE, renewal_probability=0.5, new_ti_psf=30.0),
        d_market_rent_psf=D_SCALAR,
        d_override=market(market_rent_psf=D_OVERRIDE, market_rent_growth=0.02),
    )


def default_market() -> MarketLeasingAssumptions:
    return market(market_rent_psf=DEFAULT_RENT, renewal_rent_psf=38.0)


def market_rent_scenario(operation: ScenarioOperation, value: float) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id="mkt",
        name="Market",
        overrides=(ScenarioOverride(unit_id=UNIT, target=MARKET_RENT, operation=operation, value=value),),
    )


def resolve(operation: ScenarioOperation, value: float, suites=None, leases=None):  # type: ignore[no-untyped-def]
    if suites is None:
        suites, leases = oracle_roll()
    return resolve_lease_level_scenario(
        lease_level_terms(),
        lease_level_property(),
        suites,
        leases,
        market_leasing=default_market(),
        operating_inputs=lease_level_operating(),
        unit_id=UNIT, scenario=market_rent_scenario(operation, value),
        business_plan=business_plan(),
    )


def resolved_rents(suites, defaults: MarketLeasingAssumptions) -> dict[str, float]:  # type: ignore[no-untyped-def]
    """Each suite's rent **after precedence**, by the one precedence authority."""

    return {
        suite.suite_id: resolve_market_leasing(suite, property_defaults=defaults).assumptions.market_rent_psf
        for suite in suites
    }


def test_the_oracle_roll_exercises_every_precedence_path() -> None:
    suites, _ = oracle_roll()
    assert resolved_rents(suites, default_market()) == {
        "A": DEFAULT_RENT, "B": B_SCALAR, "C": C_OVERRIDE, "D": D_SCALAR,
    }
    sources = [resolve_market_leasing(s, property_defaults=default_market()) for s in suites]
    assert [(r.source.value, r.market_rent_psf_from_suite) for r in sources] == [
        ("property_default", False), ("property_default", True),
        ("suite_override", False), ("suite_override", True),
    ]


@pytest.mark.parametrize(
    ("operation", "value", "expected"),
    [
        (Op.SET, 40.0, {"A": 40.0, "B": 40.0, "C": 40.0, "D": 40.0}),
        (Op.ADD, -3.0, {"A": DEFAULT_RENT - 3.0, "B": B_SCALAR - 3.0, "C": C_OVERRIDE - 3.0, "D": D_SCALAR - 3.0}),
        (Op.SCALE, 0.9, {"A": DEFAULT_RENT * 0.9, "B": B_SCALAR * 0.9, "C": C_OVERRIDE * 0.9, "D": D_SCALAR * 0.9}),
        (Op.CAP_AT, 45.0, {"A": DEFAULT_RENT, "B": B_SCALAR, "C": 45.0, "D": 45.0}),
    ],
    ids=["set", "add", "scale", "cap_at"],
)
def test_every_operation_acts_on_every_suites_resolved_rent_including_explicit_overrides(
    operation: ScenarioOperation, value: float, expected: dict[str, float]
) -> None:
    resolved = resolve(operation, value)
    assert resolved_rents(resolved.suites, resolved.market_leasing) == expected


def test_scale_reaches_default_derived_and_explicitly_overridden_suites_alike() -> None:
    """The M2 invariant, stated field by field: the default, the scalar
    override, the full override's rent and the stacked scalar all move."""

    resolved = resolve(Op.SCALE, 0.9)
    a, b, c, d = resolved.suites
    assert resolved.market_leasing.market_rent_psf == DEFAULT_RENT * 0.9
    assert a.market_rent_psf is None and a.market_leasing_override is None
    assert b.market_rent_psf == B_SCALAR * 0.9
    assert c.market_rent_psf is None
    assert c.market_leasing_override is not None
    assert c.market_leasing_override.market_rent_psf == C_OVERRIDE * 0.9
    assert d.market_rent_psf == D_SCALAR * 0.9
    assert d.market_leasing_override is not None
    assert d.market_leasing_override.market_rent_psf == D_OVERRIDE * 0.9


def test_set_replaces_every_stated_market_rent_level_with_the_absolute_value() -> None:
    resolved = resolve(Op.SET, 40.0)
    a, b, c, d = resolved.suites
    assert resolved.market_leasing.market_rent_psf == 40.0
    assert b.market_rent_psf == 40.0
    assert c.market_leasing_override.market_rent_psf == 40.0  # type: ignore[union-attr]
    assert d.market_rent_psf == 40.0
    assert d.market_leasing_override.market_rent_psf == 40.0  # type: ignore[union-attr]


def test_cap_at_never_raises_a_suites_rent() -> None:
    resolved = resolve(Op.CAP_AT, 100.0)
    suites, _ = oracle_roll()
    assert resolved_rents(resolved.suites, resolved.market_leasing) == resolved_rents(
        suites, default_market()
    )


@pytest.mark.parametrize("operation", list(ScenarioOperation))
def test_precedence_provenance_and_every_other_market_field_stay_where_the_analyst_put_them(
    operation: ScenarioOperation,
) -> None:
    value = {Op.SET: 40.0, Op.ADD: 2.5, Op.SCALE: 1.1, Op.CAP_AT: 45.0}[operation]
    base_suites, _ = oracle_roll()
    resolved = resolve(operation, value)

    for before, after in zip(base_suites, resolved.suites, strict=True):
        was = resolve_market_leasing(before, property_defaults=default_market())
        now = resolve_market_leasing(after, property_defaults=resolved.market_leasing)
        assert (now.source, now.market_rent_psf_from_suite) == (was.source, was.market_rent_psf_from_suite)
        assert dataclasses.replace(now.assumptions, market_rent_psf=0.0) == dataclasses.replace(
            was.assumptions, market_rent_psf=0.0
        )
        assert (after.suite_id, after.suite_area_sf, after.suite_label, after.initial_vacancy) == (
            before.suite_id, before.suite_area_sf, before.suite_label, before.initial_vacancy,
        )
    assert dataclasses.replace(resolved.market_leasing, market_rent_psf=0.0) == dataclasses.replace(
        default_market(), market_rent_psf=0.0
    )
    assert resolved.market_leasing.renewal_rent_psf == 38.0  # a negotiated level, not market


def test_the_stored_configuration_is_never_mutated() -> None:
    suites, leases = oracle_roll()
    before = copy.deepcopy((suites, leases))
    defaults = default_market()
    defaults_before = copy.deepcopy(defaults)
    resolve_lease_level_scenario(
        lease_level_terms(), lease_level_property(), suites, leases,
        market_leasing=defaults, operating_inputs=lease_level_operating(),
        unit_id=UNIT, scenario=market_rent_scenario(Op.SCALE, 0.8), business_plan=business_plan(),
    )
    assert (suites, leases) == before
    assert defaults == defaults_before
    assert resolved_rents(suites, defaults) == {
        "A": DEFAULT_RENT, "B": B_SCALAR, "C": C_OVERRIDE, "D": D_SCALAR,
    }


def test_a_scaled_market_equals_the_same_market_entered_suite_by_suite() -> None:
    """Part U for the market-rent semantics: the full Lease-Level analysis of
    the scenario is bit-identical to an ordinary analysis of a rent roll typed
    in with every rent level already scaled."""

    suites, leases = oracle_roll()
    scenario_results = analyze_lease_level_acquisition_with_scenario(
        lease_level_terms(), lease_level_property(), suites, leases,
        market_leasing=default_market(), operating_inputs=lease_level_operating(),
        unit_id=UNIT, scenario=market_rent_scenario(Op.SCALE, 0.9), business_plan=business_plan(),
    )
    manual_suites, manual_leases = rent_roll(
        b_market_rent_psf=B_SCALAR * 0.9,
        c_override=market(market_rent_psf=C_OVERRIDE * 0.9, renewal_probability=0.5, new_ti_psf=30.0),
        d_market_rent_psf=D_SCALAR * 0.9,
        d_override=market(market_rent_psf=D_OVERRIDE * 0.9, market_rent_growth=0.02),
    )
    manual_results = analyze_lease_level_acquisition_with_business_plan(
        lease_level_terms(), lease_level_property(), manual_suites, manual_leases,
        market_leasing=market(market_rent_psf=DEFAULT_RENT * 0.9, renewal_rent_psf=38.0),
        operating_inputs=lease_level_operating(), business_plan=business_plan(),
    )
    assert scenario_results == manual_results
    assert repr(scenario_results) == repr(manual_results)
    base = analyze_lease_level_acquisition_with_business_plan(
        lease_level_terms(), lease_level_property(), suites, leases,
        market_leasing=default_market(), operating_inputs=lease_level_operating(),
        business_plan=business_plan(),
    )
    assert scenario_results.results.noi_by_year != base.results.noi_by_year


def test_a_negative_resolved_rent_is_invalid_and_never_clipped_to_zero() -> None:
    """ADD -45: the default (36) and B's scalar (42) go negative; C (50), D's
    override (55) and D's scalar (60) stay positive. Every negative stated
    level is reported, on the leasing validator's own path."""

    with pytest.raises(ScenarioValidationError) as excinfo:
        resolve(Op.ADD, -45.0)
    issues = excinfo.value.issues
    assert all(i.stage is ScenarioIssueStage.RESOLVED_INPUTS for i in issues)
    assert all(i.code is ScenarioIssueCode.RESOLVED_INPUT_INVALID for i in issues)
    assert all(i.target is MARKET_RENT for i in issues)
    assert [i.field for i in issues] == ["market_leasing.market_rent_psf", "suites[1].market_rent_psf"]


def test_a_rent_only_the_default_supplies_is_still_validated() -> None:
    """ADD -40 leaves every explicit level positive, but suite A inherits the
    default, which goes to -4. The scenario is invalid."""

    with pytest.raises(ScenarioValidationError) as excinfo:
        resolve(Op.ADD, -40.0)
    assert [i.field for i in excinfo.value.issues] == ["market_leasing.market_rent_psf"]


def test_zero_market_rent_is_a_real_market_and_stays_valid() -> None:
    resolved = resolve(Op.SET, 0.0)
    assert set(resolved_rents(resolved.suites, resolved.market_leasing).values()) == {0.0}


# =============================================================================
# Renewal probability is property-default: a full override shadows it
# =============================================================================


def renewal_scenario() -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id="r",
        name="Renewals",
        overrides=(
            ScenarioOverride(unit_id=UNIT, target=ScenarioTarget.RENEWAL_PROBABILITY, operation=Op.ADD, value=-0.1),
        ),
    )


def test_a_full_suite_override_shadows_renewal_probability_and_the_scenario_is_refused() -> None:
    """Q10 ratified a unit-wide reach for market rent only. Renewal probability
    is a property-default target, so partial application would silently skip
    suites C and D. It is refused, failing closed."""

    suites, leases = oracle_roll()
    with pytest.raises(ScenarioValidationError) as excinfo:
        resolve_lease_level_scenario(
            lease_level_terms(), lease_level_property(), suites, leases,
            market_leasing=default_market(), operating_inputs=lease_level_operating(),
            unit_id=UNIT, scenario=renewal_scenario(), business_plan=business_plan(),
        )
    (issue,) = excinfo.value.issues
    assert issue.code is ScenarioIssueCode.TARGET_SHADOWED_BY_SUITE_OVERRIDE
    assert issue.stage is ScenarioIssueStage.SCENARIO
    assert issue.target is ScenarioTarget.RENEWAL_PROBABILITY
    assert "C, D" in issue.message


def test_a_scalar_rent_override_does_not_shadow_renewal_probability() -> None:
    suites, leases = rent_roll(b_market_rent_psf=B_SCALAR)
    resolved = resolve_lease_level_scenario(
        lease_level_terms(), lease_level_property(), suites, leases,
        market_leasing=default_market(), operating_inputs=lease_level_operating(),
        unit_id=UNIT, scenario=renewal_scenario(), business_plan=business_plan(),
    )
    assert resolved.market_leasing.renewal_probability == 0.65 + -0.1
    assert isinstance(resolved.suites[1], Suite)
