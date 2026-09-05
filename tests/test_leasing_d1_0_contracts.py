"""Sprint D Gate D1.0 -- Lease-Level contract shape.

Proves, per
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Section 4:

1. The three D1 contracts construct from their D0-specified fields.
2. They are immutable, hashable-by-value, and compare by value.
3. Tenant is an attribute of ``Lease``, not a separate entity.
4. No rollover, market-leasing, TI/LC/free-rent, recovery, or Detailed-vacancy
   field has leaked into a D1 contract.
5. Nothing in the package computes rent -- D1.0 is vocabulary only.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseLevelPropertyInputs,
    LeaseType,
    Suite,
)
from anchor.leasing import contracts as contracts_module


ANALYSIS_START = date(2026, 1, 1)


def build_lease(**overrides: object) -> Lease:
    fields: dict[str, object] = {
        "lease_id": "L1",
        "suite_id": "S1",
        "leased_area_sf": 10_000.0,
        "rent_commencement_date": date(2026, 1, 1),
        "lease_expiration_date": date(2030, 12, 31),
        "base_rent_psf": 30.0,
        "escalation_pct": 0.03,
        "escalation_basis": EscalationBasis.LEASE_ANNIVERSARY,
        "lease_type": LeaseType.NNN,
    }
    fields.update(overrides)
    return Lease(**fields)  # type: ignore[arg-type]


# =============================================================================
# 1. Construction
# =============================================================================


def test_property_inputs_construct_from_the_two_d0_fields() -> None:
    property_inputs = LeaseLevelPropertyInputs(
        analysis_start_date=ANALYSIS_START, rentable_area_sf=10_000.0
    )

    assert property_inputs.analysis_start_date == ANALYSIS_START
    assert property_inputs.rentable_area_sf == 10_000.0


def test_suite_constructs_with_and_without_the_optional_label() -> None:
    bare = Suite(suite_id="S1", suite_area_sf=6_000.0)
    labelled = Suite(suite_id="S2", suite_area_sf=4_000.0, suite_label="Suite 300")

    assert bare.suite_label is None
    assert labelled.suite_label == "Suite 300"


def test_lease_constructs_with_required_fields_and_documented_defaults() -> None:
    lease = build_lease()

    assert lease.lease_id == "L1"
    assert lease.suite_id == "S1"
    assert lease.leased_area_sf == 10_000.0
    assert lease.rent_commencement_date == date(2026, 1, 1)
    assert lease.lease_expiration_date == date(2030, 12, 31)
    assert lease.base_rent_psf == 30.0
    assert lease.escalation_pct == 0.03
    assert lease.escalation_basis is EscalationBasis.LEASE_ANNIVERSARY
    assert lease.lease_type is LeaseType.NNN
    # Documented D0 defaults: a lease need not name a tenant and need not
    # state a possession date.
    assert lease.tenant_name is None
    assert lease.lease_start_date is None


def test_every_contract_is_keyword_only() -> None:
    """Positional construction must fail -- a rent roll has too many
    same-typed float fields for positional order to ever be safe."""

    with pytest.raises(TypeError):
        Suite("S1", 6_000.0)  # type: ignore[misc]

    with pytest.raises(TypeError):
        LeaseLevelPropertyInputs(ANALYSIS_START, 10_000.0)  # type: ignore[misc]


# =============================================================================
# 2. Immutability, equality, determinism
# =============================================================================


@pytest.mark.parametrize(
    ("instance", "attribute", "value"),
    [
        (
            LeaseLevelPropertyInputs(
                analysis_start_date=ANALYSIS_START, rentable_area_sf=10_000.0
            ),
            "rentable_area_sf",
            1.0,
        ),
        (Suite(suite_id="S1", suite_area_sf=6_000.0), "suite_area_sf", 1.0),
        (build_lease(), "base_rent_psf", 1.0),
    ],
)
def test_contracts_are_immutable(
    instance: object, attribute: str, value: float
) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, attribute, value)


def test_contracts_use_slots_so_no_stray_attribute_can_be_attached() -> None:
    lease = build_lease()

    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        lease.market_rent_psf = 40.0  # type: ignore[attr-defined]


def test_contracts_compare_by_value() -> None:
    assert build_lease() == build_lease()
    assert build_lease() != build_lease(lease_id="L2")
    assert Suite(suite_id="S1", suite_area_sf=6_000.0) == Suite(
        suite_id="S1", suite_area_sf=6_000.0
    )


def test_repr_is_deterministic_across_identical_instances() -> None:
    assert repr(build_lease()) == repr(build_lease())


# =============================================================================
# 3. Tenant is an attribute, not an entity
# =============================================================================


def test_tenant_is_a_lease_attribute_and_no_tenant_entity_exists() -> None:
    """D0 Section 4.1: a tenant matters financially only via credit and
    multi-suite rollup, neither in competition scope. A merged Tenant/Lease
    entity could not represent D2's speculative successor lease."""

    assert "tenant_name" in {f.name for f in dataclasses.fields(Lease)}
    assert not hasattr(contracts_module, "Tenant")

    named = build_lease(tenant_name="Acme Corp")
    speculative = build_lease(lease_id="L2", tenant_name=None)
    assert named.tenant_name == "Acme Corp"
    assert speculative.tenant_name is None


def test_two_leases_for_one_tenant_are_two_rows_with_equal_tenant_name() -> None:
    first = build_lease(lease_id="L1", suite_id="S1", tenant_name="Acme Corp")
    second = build_lease(lease_id="L2", suite_id="S2", tenant_name="Acme Corp")

    assert first.tenant_name == second.tenant_name
    assert first.lease_id != second.lease_id


# =============================================================================
# 4. Out-of-scope fields have not leaked in
# =============================================================================


#: Fields no D1 contract may declare. The set is narrowed **only** by the
#: fields each gate actually delivers, when it lands:
#:
#: - **D2.1** removed ``market_rent_psf`` / ``market_rent_growth`` and the
#:   ``Suite`` overrides D0 Section 4.3 phases to D2.
#: - **D2.2** removed the four renewal-branch fields
#:   (``renewal_rent_psf``, ``renewal_rent_spread``, ``renewal_term_months``,
#:   ``successor_escalation_pct``) and ``origin``, which D0 Section 4.4 marks
#:   derived and phases to D2.
#:
#: Everything D2.3 and later owns stays, so the guardrail keeps its full force
#: against the new-tenant branch, downtime, free rent, TI, LC, probability and
#: every downstream concept.
#:
#: ``Lease`` and ``LeaseLevelPropertyInputs`` are still checked against the
#: market names below, because D0 assigns the market override to ``Suite``
#: alone -- market rent is an assumption about a *space*, never a term of a
#: signed lease (D0 Section 24.4).
_FORBIDDEN_D1_FIELD_NAMES = frozenset(
    {
        # D2.3+ rollover
        "renewal_probability",
        "new_rent_psf",
        "new_term_months",
        "renewal_downtime_months",
        "new_downtime_months",
        "downtime_months",
        # D2 leasing costs
        "free_rent_months",
        "renewal_ti_psf",
        "new_ti_psf",
        "tenant_improvements",
        "renewal_lc_pct",
        "new_lc_pct",
        "leasing_commissions",
        # D3 recoveries
        "recovery_basis",
        "recoverable_expense_ratio",
        # Detailed-mode vacancy -- must never exist on a Lease-Level contract
        "vacancy_credit_loss_pct",
        "occupancy",
        "credit_loss_pct",
    }
)


#: The D2.1 market-rent fields. Permitted on ``Suite`` only (D0 Section 4.3).
_D2_1_MARKET_FIELD_NAMES = frozenset(
    {"market_rent_psf", "market_rent_growth", "market_leasing_override"}
)


@pytest.mark.parametrize(
    "contract", [LeaseLevelPropertyInputs, Suite, Lease], ids=lambda c: c.__name__
)
def test_no_out_of_scope_field_leaked_into_a_d1_contract(contract: type) -> None:
    declared = {f.name for f in dataclasses.fields(contract)}
    leaked = declared & _FORBIDDEN_D1_FIELD_NAMES

    assert not leaked, f"{contract.__name__} declares out-of-D1-scope fields: {leaked}"


def test_market_rent_overrides_live_on_the_suite_and_nowhere_else() -> None:
    """D0 Section 4.3 puts the market-rent override on ``Suite``; D0
    Section 24.4 keeps every market assumption off a signed ``Lease``.

    A ``market_rent_psf`` on ``Lease`` would make market rent look like a
    contractual term, which is exactly the confusion D2 Section 10 exists to
    prevent."""

    suite_fields = {f.name for f in dataclasses.fields(Suite)}
    assert "market_rent_psf" in suite_fields
    assert "market_leasing_override" in suite_fields

    for contract in (Lease, LeaseLevelPropertyInputs):
        declared = {f.name for f in dataclasses.fields(contract)}
        leaked = declared & _D2_1_MARKET_FIELD_NAMES
        assert not leaked, (
            f"{contract.__name__} declares {sorted(leaked)}; market rent is an "
            "assumption about a space, never a term of a lease"
        )


def test_the_d2_1_suite_overrides_default_to_inheriting() -> None:
    """Both override fields default to ``None``, so every D1 call site
    constructs an identical ``Suite`` and no D1 economics moved at D2.1."""

    defaults = {
        f.name: f.default
        for f in dataclasses.fields(Suite)
        if f.name in _D2_1_MARKET_FIELD_NAMES
    }
    assert defaults == {"market_rent_psf": None, "market_leasing_override": None}


def test_no_lease_level_contract_declares_a_detailed_vacancy_field() -> None:
    """D0 Section 15.2 / guardrail G-M14. Applying a blanket vacancy
    percentage on top of explicitly modeled vacancy would double-count, so
    the mechanism is structurally absent rather than merely discouraged."""

    for contract in (LeaseLevelPropertyInputs, Suite, Lease):
        declared = {f.name for f in dataclasses.fields(contract)}
        assert "vacancy_credit_loss_pct" not in declared
        assert "occupancy" not in declared


def test_escalation_basis_declares_exactly_the_two_d1_members() -> None:
    """D0 Section 6.2/6.6: CALENDAR_YEAR and fixed $/SF bumps are documented
    D2+ additive extensions. Neither may be constructible at D1."""

    assert {member.value for member in EscalationBasis} == {
        "none",
        "lease_anniversary",
    }


def test_lease_type_declares_exactly_the_three_recovery_structures() -> None:
    assert {member.value for member in LeaseType} == {
        "nnn",
        "gross",
        "modified_gross",
    }


def test_lease_origin_arrived_at_d2_2_and_defaults_to_in_place() -> None:
    """D0 Section 4.4 marks ``origin`` *derived* and phases it to **D2**. D2.2
    is the gate that can actually construct a successor, so the field and its
    enum land here rather than earlier.

    It defaults to ``IN_PLACE``, which is what keeps the addition non-breaking:
    every D1 call site constructs an identical lease and no D1 economics
    move."""

    import anchor.leasing as leasing

    assert hasattr(leasing, "LeaseOrigin")
    assert {member.value for member in leasing.LeaseOrigin} == {
        "in_place",
        "successor",
    }

    origin_field = next(
        f for f in dataclasses.fields(Lease) if f.name == "origin"
    )
    assert origin_field.default is leasing.LeaseOrigin.IN_PLACE


# =============================================================================
# 5. D1.0 is vocabulary only -- nothing computes
# =============================================================================


def test_contracts_module_defines_no_calculation() -> None:
    """A reviewer must be able to answer 'what is a valid contractual lease'
    without encountering rent-calculation logic (D0 Section 28 quality bar).

    The contracts module declares dataclasses and enums and nothing else --
    no module-level function at all, so there is no place for a formula to
    hide."""

    import inspect

    functions = [
        name
        for name, value in vars(contracts_module).items()
        if inspect.isfunction(value)
        and getattr(value, "__module__", None) == contracts_module.__name__
    ]

    assert functions == [], f"contracts.py must define no functions; found {functions}"


def test_package_exposes_no_d3_or_later_entry_point() -> None:
    """Each surface moved to a positive assertion when its gate landed: month
    identity at D1.1, rent at D1.2, aggregation at D1.3, market rent at D2.1,
    the branches at D2.2/D2.3, leasing costs at D2.4, the expected-value
    composition at D2.5 and the recursion at D2.6. **Sprint D2 is complete**;
    what remains absent is everything D3 and D4 own."""

    import anchor.leasing as leasing

    for absent in (
        "build_lease_level_operating_projection",
        "MonthlyPropertyProjection",
        "AnnualOperatingProjection",
        "expense_recoveries",
        "build_expense_recoveries",
        "RecoveryBasis",
    ):
        assert not hasattr(leasing, absent), (
            f"{absent} belongs to a later gate and must not exist yet"
        )


def test_package_exposes_the_d1_3_aggregation_surface() -> None:
    """The D1.3 deliverable: one canonical monthly property rent roll, plus
    the annual derivations taken from it."""

    import anchor.leasing as leasing

    for present in (
        "PropertyRentRollSchedule",
        "build_property_rent_roll_schedule",
        "aggregate_flow_to_annual",
        "aggregate_flow_over_forward_exit_window",
        "snapshot_state_at_year_end",
        "average_state_over_year",
    ):
        assert hasattr(leasing, present), f"{present} is a D1.3 public export"


def test_rent_helpers_stay_off_the_public_package_surface() -> None:
    """Only the schedule and its builder are public. The step and per-month
    helpers are reachable from ``anchor.leasing.rent`` for tests and future
    internal callers, but are not part of the package's public API."""

    import anchor.leasing as leasing

    for helper in ("monthly_base_rent", "lease_rent_periods", "escalation_period_index"):
        assert not hasattr(leasing, helper), (
            f"{helper} is an internal rent helper, not a public export"
        )


def test_package_exposes_the_d1_2_rent_surface() -> None:
    """The D1.2 deliverable: one validated lease in, its exact canonical
    monthly base rent out."""

    import anchor.leasing as leasing

    for present in ("LeaseMonthlySchedule", "build_lease_monthly_schedule"):
        assert hasattr(leasing, present), f"{present} is a D1.2 public export"


def test_package_exposes_the_d1_1_calendar_surface() -> None:
    """The D1.1 deliverable: one trusted representation of every modeled
    month, reachable from the package's public API."""

    import anchor.leasing as leasing

    for present in (
        "ModelMonth",
        "build_model_months",
        "projection_month_count",
        "month_index",
        "month_start_for_index",
        "is_first_day_of_month",
        "is_last_day_of_month",
        "last_day_of_month",
    ):
        assert hasattr(leasing, present), f"{present} is a D1.1 public export"
