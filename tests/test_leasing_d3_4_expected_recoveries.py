"""Sprint D Gate D3.4 -- expected and recursive expense recoveries.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d3-recovery-conventions.md``
Section 10, that recovery expectation weights **completed recovery dollars**:

```
ExpectedRecovery_m = p x RenewalRecovery_m + (1 - p) x NewTenantRecovery_m
```

after each branch has priced its own structure, and that the same rule extends
across every D2.6 successor generation.

The claims that matter most, and how each fails silently:

- **the nonlinearity is load-bearing.** The Modified Gross clip means
  ``E[max(0, X - S)] != max(0, E[X] - E[S])``. Weighting two branches' stops
  and clipping once is a natural-looking implementation that produces a
  plausible, wrong number -- ``$8,000`` where the truth is ``$12,000``
  (FM-D3-10);
- **there is one recursion, and it is D2.6's.** Recovery attaches to the
  transitions that result already decided: which states exist, which merge,
  how mass splits, when the walk ends. A second state machine could agree
  today and diverge tomorrow with no authority to resolve it;
- **reconstruction is exact.** D3.3 proved a successor's economics are a
  function of ``(suite, resolved assumptions, parent expiration, branch,
  months, market schedule)``, so rebuilding a transition through the same D2
  engine reproduces it identically rather than approximately;
- **the known lease contributes once**, deterministically, never scaled by
  ``p``. What a sitting tenant owes before expiry is history, not a scenario;
- **every successor series is successor-only**, so no generation re-counts its
  predecessor's months.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecoverableExpensePool,
    RecoveryBasis,
    RolloverBranchKind,
    Suite,
    build_expected_rollover,
    build_expected_rollover_recovery,
    build_market_rent_schedule,
    build_model_months,
    build_recursive_rollover,
    build_recursive_rollover_recovery,
    build_successor_contribution,
    build_successor_recovery_schedule,
    successor_state_lease_id_stem,
)


JAN = date(2027, 1, 1)
AREA = 20_000.0
PROPERTY_AREA = 100_000.0
SHARE = 0.20

#: A flat $150,000 pool gives a $30,000 monthly tenant share at a 20% share.
POOL_FLAT = 150_000.0
TENANT_SHARE = 30_000.0

#: $6/SF/YR on 20,000 SF is a $10,000 monthly stop; $24/SF/YR is $40,000.
STOP_LOW_PSF = 6.0
STOP_LOW = 10_000.0
STOP_HIGH_PSF = 24.0
STOP_HIGH = 40_000.0


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def close(expected: float) -> object:
    """The project's accepted magnitude-aware oracle tolerance."""

    return pytest.approx(expected, rel=1e-12, abs=1e-9)


def hexes(values: tuple[float, ...]) -> list[str]:
    return [value.hex() for value in values]


def months(*, hold_period: int = 3) -> tuple:
    return build_model_months(analysis_start=JAN, hold_period=hold_period)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    base: dict[str, object] = {
        "market_rent_psf": 40.0,
        "market_rent_growth": 0.0,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.0,
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 0.0,
        "new_term_months": 60,
        "new_downtime_months": 0.0,
        "new_free_rent_months": 0.0,
        "renewal_ti_psf": 0.0,
        "new_ti_psf": 0.0,
        "leasing_commission_method": (
            LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT
        ),
        "renewal_lc_pct": 0.0,
        "new_lc_pct": 0.0,
        "renewal_probability": 0.5,
        "renewal_lease_type": LeaseType.NNN,
        "renewal_recovery_basis": None,
        "renewal_expense_stop_psf": None,
        "new_lease_type": LeaseType.NNN,
        "new_recovery_basis": None,
        "new_expense_stop_psf": None,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)  # type: ignore[arg-type]


def modified_gross(branch: str, stop_psf: float) -> dict[str, object]:
    return {
        f"{branch}_lease_type": LeaseType.MODIFIED_GROSS,
        f"{branch}_recovery_basis": RecoveryBasis.EXPENSE_STOP_PSF,
        f"{branch}_expense_stop_psf": stop_psf,
    }


def suite() -> Suite:
    return Suite(suite_id="S1", suite_area_sf=AREA)


def lease(
    *,
    lease_type: LeaseType = LeaseType.NNN,
    recovery_basis: RecoveryBasis | None = None,
    expense_stop_psf: float | None = None,
    lease_id: str = "L1",
    base_rent_psf: float = 30.0,
    end: date = date(2027, 12, 31),
) -> Lease:
    """An in-place lease expiring at period 12 unless told otherwise."""

    return Lease(
        lease_id=lease_id,
        suite_id="S1",
        tenant_name="Acme Corp",
        leased_area_sf=AREA,
        rent_commencement_date=date(2025, 1, 1),
        lease_expiration_date=end,
        base_rent_psf=base_rent_psf,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=lease_type,
        recovery_basis=recovery_basis,
        expense_stop_psf=expense_stop_psf,
    )


def pool(
    amount: float = POOL_FLAT,
    *,
    canonical: tuple | None = None,
    series: tuple[float, ...] | None = None,
) -> RecoverableExpensePool:
    canonical = canonical if canonical is not None else months()
    expenses = series if series is not None else tuple([amount] * len(canonical))
    return RecoverableExpensePool(months=canonical, recoverable_expenses=expenses)


def expected_recovery(
    *,
    the_lease: Lease | None = None,
    canonical: tuple | None = None,
    the_pool: RecoverableExpensePool | None = None,
    **overrides: object,
):
    canonical = canonical if canonical is not None else months()
    the_lease = the_lease if the_lease is not None else lease()
    rollover = build_expected_rollover(
        the_lease,
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(**overrides),
    )
    return build_expected_rollover_recovery(
        rollover,
        expiring=the_lease,
        pool=the_pool if the_pool is not None else pool(canonical=canonical),
        rentable_area_sf=PROPERTY_AREA,
    )


def recursive_recovery(
    *,
    the_lease: Lease | None = None,
    canonical: tuple | None = None,
    the_pool: RecoverableExpensePool | None = None,
    **overrides: object,
):
    canonical = canonical if canonical is not None else months()
    the_lease = the_lease if the_lease is not None else lease()
    defaults = assumptions(**overrides)
    rollover = build_recursive_rollover(
        the_lease,
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )
    return build_recursive_rollover_recovery(
        rollover,
        suite=suite(),
        analysis_start=JAN,
        property_defaults=defaults,
        pool=the_pool if the_pool is not None else pool(canonical=canonical),
        rentable_area_sf=PROPERTY_AREA,
    )


#: The first successor month for a lease expiring at period 12 with no
#: downtime: period 13, index 12.
FIRST = 12


# =============================================================================
# GOLDEN 1 / 2 -- the endpoints
# =============================================================================


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {**modified_gross("renewal", STOP_LOW_PSF), **modified_gross("new", STOP_HIGH_PSF)},
        {"renewal_lease_type": LeaseType.GROSS, "new_lease_type": LeaseType.NNN},
        {"renewal_downtime_months": 2.25, "new_downtime_months": 4.0},
    ],
    ids=["nnn", "modified-gross", "mixed-types", "downtime"],
)
def test_golden_1_p_equals_one_is_exactly_the_renewal_recovery(
    overrides: dict[str, object],
) -> None:
    """The composition's key safety property, inherited from D2.5. Under
    ``p = 1`` the weighting is literally ``1.0 * r + 0.0 * n``; if that does
    not reproduce the pure branch, the composition has a bug."""

    result = expected_recovery(**overrides, renewal_probability=1.0)

    assert hexes(result.expected_successor_expense_recovery) == hexes(
        result.renewal_recovery.expense_recovery
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {**modified_gross("renewal", STOP_LOW_PSF), **modified_gross("new", STOP_HIGH_PSF)},
        {"renewal_lease_type": LeaseType.GROSS, "new_lease_type": LeaseType.NNN},
        {"renewal_downtime_months": 2.25, "new_downtime_months": 4.0},
    ],
    ids=["nnn", "modified-gross", "mixed-types", "downtime"],
)
def test_golden_2_p_equals_zero_is_exactly_the_new_tenant_recovery(
    overrides: dict[str, object],
) -> None:
    result = expected_recovery(**overrides, renewal_probability=0.0)

    assert hexes(result.expected_successor_expense_recovery) == hexes(
        result.new_tenant_recovery.expense_recovery
    )


def test_identical_branch_outcomes_are_preserved_exactly() -> None:
    """When both branches recover the same dollar, the composed value is that
    dollar unchanged -- no ULP drift from ``p * x + (1 - p) * x``."""

    result = expected_recovery(renewal_probability=1.0 / 3.0)

    assert hexes(result.renewal_recovery.expense_recovery) == hexes(
        result.new_tenant_recovery.expense_recovery
    )
    assert hexes(result.expected_successor_expense_recovery) == hexes(
        result.renewal_recovery.expense_recovery
    )


# =============================================================================
# GOLDEN 3 -- different lease types compose on dollars
# =============================================================================


def test_golden_3_gross_renewal_and_nnn_new_tenant_blend_on_dollars() -> None:
    """Renewal GROSS recovers ``$0``; a new NNN letting recovers the full
    ``$30,000`` share. At ``p = 0.4`` the expectation is ``0.6 x 30,000``.

    There is no "expected lease type" anywhere in this: ``0.4 x GROSS +
    0.6 x NNN`` is not a structure a tenant signs.
    """

    result = expected_recovery(
        renewal_lease_type=LeaseType.GROSS,
        new_lease_type=LeaseType.NNN,
        renewal_probability=0.4,
    )

    assert result.renewal_recovery.expense_recovery[FIRST] == strict(0.0)
    assert result.new_tenant_recovery.expense_recovery[FIRST] == strict(TENANT_SHARE)
    assert result.expected_successor_expense_recovery[FIRST] == strict(18_000.0)


def test_golden_3_the_composed_result_declares_no_expected_structure() -> None:
    result = expected_recovery()
    fields = {f.name for f in dataclasses.fields(result)}

    for absent in (
        "expected_lease_type",
        "expected_recovery_basis",
        "expected_expense_stop_psf",
        "expected_monthly_expense_stop_dollars",
        "expected_tenant_pro_rata_share",
    ):
        assert absent not in fields

    # The structures remain auditable on the pure branch records.
    assert result.renewal_recovery.successor_lease_type is LeaseType.NNN
    assert result.new_tenant_recovery.successor_lease_type is LeaseType.NNN


# =============================================================================
# GOLDEN 4 -- the nonlinear Modified Gross composition
# =============================================================================


def test_golden_4_expected_recovery_weights_dollars_not_stops() -> None:
    """**The mandatory nonlinear golden.** FM-D3-10.

    Tenant share ``$30,000``. Renewal is Modified Gross on a ``$10,000``
    monthly stop and recovers ``$20,000``; the new letting is Modified Gross
    on a ``$40,000`` stop, is under water, and recovers ``$0``. At ``p = 0.6``:

    ```
    CORRECT  0.6 x 20,000 + 0.4 x 0            = $12,000
    WRONG    max(0, 30,000 - (0.6 x 10,000
                              + 0.4 x 40,000)) = $ 8,000
    ```

    The wrong form averages two contractual thresholds into one that no lease
    contains, then clips once. It is not a rounding difference -- it is a
    third of the figure, and it looks entirely plausible.
    """

    result = expected_recovery(
        **modified_gross("renewal", STOP_LOW_PSF),
        **modified_gross("new", STOP_HIGH_PSF),
        renewal_probability=0.6,
    )

    assert result.renewal_recovery.monthly_expense_stop_dollars == strict(STOP_LOW)
    assert result.new_tenant_recovery.monthly_expense_stop_dollars == strict(STOP_HIGH)

    assert result.renewal_recovery.expense_recovery[FIRST] == strict(20_000.0)
    assert result.new_tenant_recovery.expense_recovery[FIRST] == strict(0.0)
    assert result.expected_successor_expense_recovery[FIRST] == strict(12_000.0)

    weighted_stop = 0.6 * STOP_LOW + 0.4 * STOP_HIGH
    wrong = max(0.0, TENANT_SHARE - weighted_stop)
    assert weighted_stop == strict(22_000.0)
    assert wrong == strict(8_000.0)
    assert result.expected_successor_expense_recovery[FIRST] != pytest.approx(
        wrong, abs=1e-6
    )


def test_golden_4_the_gap_survives_across_the_whole_probability_range() -> None:
    """The two forms coincide only at the degenerate ends, so a single test
    probability could not have distinguished them by luck."""

    for probability in (0.1, 0.25, 0.5, 0.75, 0.9):
        result = expected_recovery(
            **modified_gross("renewal", STOP_LOW_PSF),
            **modified_gross("new", STOP_HIGH_PSF),
            renewal_probability=probability,
        )
        correct = result.expected_successor_expense_recovery[FIRST]
        weighted_stop = probability * STOP_LOW + (1 - probability) * STOP_HIGH
        wrong = max(0.0, TENANT_SHARE - weighted_stop)

        assert correct == strict(probability * 20_000.0)
        assert correct != pytest.approx(wrong, abs=1e-6)


def test_golden_16_a_zero_stop_branch_recovers_like_nnn() -> None:
    """A Modified Gross branch with a zero stop is numerically NNN, and the
    composition treats it as such -- while both records still say what
    structure each branch signed."""

    zero_stop = expected_recovery(
        **modified_gross("renewal", 0.0),
        new_lease_type=LeaseType.NNN,
        renewal_probability=0.7,
    )

    assert zero_stop.renewal_recovery.expense_recovery[FIRST] == strict(TENANT_SHARE)
    assert zero_stop.expected_successor_expense_recovery[FIRST] == strict(TENANT_SHARE)
    assert (
        zero_stop.renewal_recovery.successor_lease_type is LeaseType.MODIFIED_GROSS
    )
    assert zero_stop.new_tenant_recovery.successor_lease_type is LeaseType.NNN


# =============================================================================
# The known in-place lease
# =============================================================================


def test_the_known_lease_recovery_is_never_weighted() -> None:
    """It is deterministic, at probability 1. An NNN sitting tenant recovers
    its full ``$30,000`` every month before expiry, whatever ``p`` is."""

    for probability in (0.0, 0.3, 0.65, 1.0):
        result = expected_recovery(renewal_probability=probability)

        assert result.in_place_expense_recovery[0] == strict(TENANT_SHARE)
        assert result.in_place_expense_recovery[11] == strict(TENANT_SHARE)


def test_the_known_lease_and_its_successors_never_overlap() -> None:
    """Structural non-overlap: the in-place factor is zero after expiry and
    every successor series is zero at or before it."""

    result = expected_recovery(renewal_probability=0.65)

    for known, successor in zip(
        result.in_place_expense_recovery,
        result.expected_successor_expense_recovery,
        strict=True,
    ):
        assert known == 0.0 or successor == 0.0

    assert result.in_place_expense_recovery[12] == strict(0.0)
    assert result.expected_successor_expense_recovery[11] == strict(0.0)


def test_the_full_chain_is_the_sum_of_its_two_disjoint_parts() -> None:
    result = expected_recovery(renewal_probability=0.65)

    for known, successor, total in zip(
        result.in_place_expense_recovery,
        result.expected_successor_expense_recovery,
        result.expected_expense_recovery,
        strict=True,
    ):
        assert total.hex() == (known + successor).hex()


def test_a_gross_in_place_lease_contributes_nothing_but_still_rolls_over() -> None:
    """The known lease's structure is its own; it does not constrain what
    replaces it (HD-D3-1)."""

    result = expected_recovery(
        the_lease=lease(lease_type=LeaseType.GROSS),
        new_lease_type=LeaseType.NNN,
        renewal_probability=0.0,
    )

    assert all(value == 0.0 for value in result.in_place_expense_recovery)
    assert result.expected_expense_recovery[FIRST] == strict(TENANT_SHARE)


def test_a_contract_rejects_overlapping_known_and_successor_recovery() -> None:
    """The anti-double-counting invariant is enforced by the contract, not
    merely produced by the builder."""

    result = expected_recovery(renewal_probability=0.65)
    overlapping = list(result.in_place_expense_recovery)
    overlapping[FIRST] = 1.0  # a month a successor already occupies

    with pytest.raises(ValueError, match="counted twice"):
        dataclasses.replace(
            result, in_place_expense_recovery=tuple(overlapping)
        )


# =============================================================================
# GOLDEN 5 -- one-rollover recursive compatibility
# =============================================================================


def test_golden_5_recursion_matches_the_first_rollover_when_only_one_occurs() -> None:
    """The D3 analogue of the D2.5/D2.6 compatibility proof. With 60-month
    successor terms neither first successor expires inside a 3-year window, so
    the recursion has exactly two transitions and must agree with the
    first-rollover composition month for month."""

    overrides = {
        **modified_gross("renewal", STOP_LOW_PSF),
        "new_lease_type": LeaseType.GROSS,
        "renewal_probability": 0.65,
    }

    first = expected_recovery(**overrides)
    recursive = recursive_recovery(**overrides)

    assert len(recursive.rollover.transitions) == 2
    assert hexes(recursive.expected_expense_recovery) == hexes(
        first.expected_expense_recovery
    )
    assert hexes(recursive.in_place_expense_recovery) == hexes(
        first.in_place_expense_recovery
    )


@pytest.mark.parametrize("probability", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_golden_5_compatibility_holds_across_the_probability_range(
    probability: float,
) -> None:
    overrides = {
        **modified_gross("renewal", STOP_LOW_PSF),
        **modified_gross("new", STOP_HIGH_PSF),
        "renewal_probability": probability,
    }

    first = expected_recovery(**overrides)
    recursive = recursive_recovery(**overrides)

    for expected_value, actual in zip(
        first.expected_expense_recovery,
        recursive.expected_expense_recovery,
        strict=True,
    ):
        assert actual == close(expected_value)


# =============================================================================
# The recursion is D2.6's
# =============================================================================


def test_recovery_attaches_one_contribution_per_authoritative_transition() -> None:
    """D3 adds no event and drops none. The contract asserts the count."""

    result = recursive_recovery(
        renewal_term_months=5, new_term_months=9, renewal_probability=0.65
    )

    assert len(result.contributions) == len(result.rollover.transitions)
    for contribution, transition in zip(
        result.contributions, result.rollover.transitions, strict=True
    ):
        assert contribution.parent_expiration_period == (
            transition.parent_expiration_period
        )
        assert contribution.branch is transition.branch
        assert contribution.probability_mass == strict(transition.probability_mass)


def test_the_probability_mass_comes_from_the_d2_transition() -> None:
    """Not recomputed from ``p``. A later generation's mass is a product of
    branch probabilities along its path, which only the recursion knows."""

    result = recursive_recovery(
        renewal_term_months=4, new_term_months=6, renewal_probability=0.6
    )

    masses = {c.probability_mass for c in result.contributions}
    assert any(
        mass not in (0.6, 0.4) and 0.0 < mass < 0.6 for mass in masses
    ), "no later-generation mass appeared; the case is not exercising recursion"


def test_the_terminal_mass_is_mirrored_not_recomputed() -> None:
    result = recursive_recovery(
        renewal_term_months=4, new_term_months=6, renewal_probability=0.6
    )

    assert result.terminal_probability_mass == (
        result.rollover.terminal_probability_mass
    )


def test_the_contract_refuses_a_contribution_count_that_disagrees() -> None:
    result = recursive_recovery(renewal_probability=0.5)

    with pytest.raises(ValueError, match="authoritative rollover transitions"):
        dataclasses.replace(result, contributions=result.contributions[:1])


# =============================================================================
# Transition reconstruction
# =============================================================================


def test_reconstruction_agrees_with_the_authoritative_transition_audit() -> None:
    """**The mandatory reconstruction proof.** Rebuilding each transition's
    successor through the D2 engine must reproduce the audited economics
    exactly -- so no recovery-specific timing or pricing formula is needed."""

    canonical = months(hold_period=4)
    defaults = assumptions(
        **modified_gross("renewal", STOP_LOW_PSF),
        new_lease_type=LeaseType.NNN,
        renewal_term_months=5,
        new_term_months=9,
        renewal_downtime_months=1.0,
        new_downtime_months=2.25,
        renewal_ti_psf=12.0,
        new_ti_psf=40.0,
        renewal_lc_pct=0.03,
        new_lc_pct=0.06,
        renewal_probability=0.55,
    )
    rollover = build_recursive_rollover(
        lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )
    schedule = build_market_rent_schedule(
        suite(), property_defaults=defaults, months=canonical
    )

    assert len(rollover.transitions) >= 6, "too few transitions to be a matrix"

    for transition in rollover.transitions:
        rebuilt = build_successor_contribution(
            suite=suite(),
            analysis_start=JAN,
            months=canonical,
            market_schedule=schedule,
            parent_expiration_period=transition.parent_expiration_period,
            branch=transition.branch,
            lease_id_stem=successor_state_lease_id_stem(
                rollover.expiring_lease_id, transition.parent_expiration_period
            ),
        )

        assert rebuilt.parent_expiration_period == transition.parent_expiration_period
        assert rebuilt.branch is transition.branch
        assert rebuilt.commencement_period == transition.commencement_period
        assert rebuilt.successor_expiration_period == (
            transition.successor_expiration_period
        )
        assert rebuilt.commences_within_projection == (
            transition.commences_within_projection
        )
        assert rebuilt.term_months == transition.term_months
        assert rebuilt.starting_rent_psf == strict(transition.starting_rent_psf)
        assert rebuilt.tenant_improvement_amount == strict(
            transition.tenant_improvement_amount
        )
        assert rebuilt.leasing_commission_amount == strict(
            transition.leasing_commission_amount
        )

        # And the recovery-bearing mechanics come from D2, not a D3 formula.
        branch_terms = (
            (defaults.renewal_lease_type, defaults.renewal_expense_stop_psf)
            if transition.branch is RolloverBranchKind.RENEWAL
            else (defaults.new_lease_type, defaults.new_expense_stop_psf)
        )
        assert rebuilt.successor_lease.lease_type is branch_terms[0]
        assert rebuilt.successor_lease.expense_stop_psf == branch_terms[1]


def test_the_identifier_stem_reaches_no_financial_output() -> None:
    """Identity is state-derived and inert. Two different stems produce
    identical economics, so no identifier is part of the rollover state."""

    canonical = months()
    schedule = build_market_rent_schedule(
        suite(), property_defaults=assumptions(), months=canonical
    )
    common = dict(
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        market_schedule=schedule,
        parent_expiration_period=12,
        branch=RolloverBranchKind.RENEWAL,
    )
    the_pool = pool(canonical=canonical)

    a = build_successor_contribution(lease_id_stem="one", **common)
    b = build_successor_contribution(lease_id_stem="two", **common)

    recovery_a = build_successor_recovery_schedule(
        branch=RolloverBranchKind.RENEWAL,
        successor_lease=a.successor_lease,
        months=canonical,
        successor_occupancy_factor=a.successor_occupancy_factor,
        commencement_period=a.commencement_period,
        successor_expiration_period=a.successor_expiration_period,
        pool=the_pool,
        rentable_area_sf=PROPERTY_AREA,
    )
    recovery_b = build_successor_recovery_schedule(
        branch=RolloverBranchKind.RENEWAL,
        successor_lease=b.successor_lease,
        months=canonical,
        successor_occupancy_factor=b.successor_occupancy_factor,
        commencement_period=b.commencement_period,
        successor_expiration_period=b.successor_expiration_period,
        pool=the_pool,
        rentable_area_sf=PROPERTY_AREA,
    )

    assert a.successor_lease.lease_id != b.successor_lease.lease_id
    assert hexes(recovery_a.expense_recovery) == hexes(recovery_b.expense_recovery)


def test_the_stem_helper_is_deterministic_and_state_derived() -> None:
    assert successor_state_lease_id_stem("L1", 12) == "L1@e12"
    assert successor_state_lease_id_stem("L1", 12) == successor_state_lease_id_stem(
        "L1", 12
    )


# =============================================================================
# GOLDEN 17 -- the explicit-tree recovery oracle
# =============================================================================


def _explicit_recovery_oracle(
    *,
    the_lease: Lease,
    canonical: tuple,
    defaults: MarketLeasingAssumptions,
    the_pool: RecoverableExpensePool,
) -> tuple[float, ...]:
    """TEST-ONLY. Enumerate every complete scenario path and weight its
    recovery dollars.

    The independent check on the state machine: this builds the exponential
    tree D2.6 deliberately replaces, prices each path's recoveries with the D3
    formulas, and weights by the path's own probability. Production must agree.

    Kept in the test suite, never in production -- an explicit tree is
    precisely the structure the accepted architecture exists to avoid.
    """

    from anchor.leasing.rent import lease_rent_periods

    horizon = canonical[-1].period_index
    count = len(canonical)
    schedule = build_market_rent_schedule(
        suite(), property_defaults=defaults, months=canonical
    )
    probability = defaults.renewal_probability
    totals = [0.0] * count

    _, first_expiration = lease_rent_periods(the_lease, analysis_start=JAN)

    def walk(parent_expiration: int, mass: float) -> None:
        if mass == 0.0 or not 1 <= parent_expiration < horizon:
            return
        for branch, weight in (
            (RolloverBranchKind.RENEWAL, probability),
            (RolloverBranchKind.NEW_TENANT, 1.0 - probability),
        ):
            child_mass = mass * weight
            if child_mass == 0.0:
                continue
            contribution = build_successor_contribution(
                suite=suite(),
                analysis_start=JAN,
                months=canonical,
                market_schedule=schedule,
                parent_expiration_period=parent_expiration,
                branch=branch,
                lease_id_stem=f"oracle@{parent_expiration}",
            )
            recovery = build_successor_recovery_schedule(
                branch=branch,
                successor_lease=contribution.successor_lease,
                months=canonical,
                successor_occupancy_factor=contribution.successor_occupancy_factor,
                commencement_period=contribution.commencement_period,
                successor_expiration_period=(
                    contribution.successor_expiration_period
                ),
                pool=the_pool,
                rentable_area_sf=PROPERTY_AREA,
            )
            for index in range(count):
                totals[index] += child_mass * recovery.expense_recovery[index]
            walk(contribution.successor_expiration_period, child_mass)

    walk(first_expiration, 1.0)
    return tuple(totals)


ORACLE_MATRIX = [
    (0.65, 5, 4, 1.0, 2.25, 0.0, 1.25),
    (0.25, 4, 7, 0.5, 0.0, 1.5, 0.0),
    (1.0, 4, 9, 0.0, 3.0, 0.0, 2.0),
    (0.0, 4, 9, 0.0, 3.0, 0.0, 2.0),
    (0.5, 6, 6, 0.0, 0.0, 0.0, 0.0),
]


@pytest.mark.parametrize(
    ("probability", "renewal_term", "new_term", "renewal_d", "new_d", "renewal_f", "new_f"),
    ORACLE_MATRIX,
    ids=lambda v: str(v),
)
def test_golden_17_production_matches_the_explicit_recovery_tree(
    probability: float,
    renewal_term: int,
    new_term: int,
    renewal_d: float,
    new_d: float,
    renewal_f: float,
    new_f: float,
) -> None:
    """**The independent oracle.** Short terms force many generations inside a
    two-year window, so the enumerated tree and the merged state machine are
    genuinely different computations of the same quantity."""

    canonical = months(hold_period=2)
    defaults = assumptions(
        **modified_gross("renewal", STOP_LOW_PSF),
        new_lease_type=LeaseType.NNN,
        renewal_term_months=renewal_term,
        new_term_months=new_term,
        renewal_downtime_months=renewal_d,
        new_downtime_months=new_d,
        renewal_free_rent_months=renewal_f,
        new_free_rent_months=new_f,
        renewal_probability=probability,
    )
    the_pool = pool(canonical=canonical)

    rollover = build_recursive_rollover(
        lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )
    production = build_recursive_rollover_recovery(
        rollover,
        suite=suite(),
        analysis_start=JAN,
        property_defaults=defaults,
        pool=the_pool,
        rentable_area_sf=PROPERTY_AREA,
    )
    oracle = _explicit_recovery_oracle(
        the_lease=lease(),
        canonical=canonical,
        defaults=defaults,
        the_pool=the_pool,
    )

    assert sum(oracle) > 0.0, "the oracle produced no recovery; case is inert"

    for expected_value, actual in zip(
        oracle, production.expected_successor_expense_recovery, strict=True
    ):
        assert actual == close(expected_value)


# =============================================================================
# GOLDEN 6 / 7 -- generations and convergence
# =============================================================================


def test_golden_6_each_generation_prices_on_its_own_branch_structure() -> None:
    """Renewal is Modified Gross and every new letting is NNN, at every event,
    for every generation -- decided by the **new** branch kind and never by
    what the expiring predecessor happened to be."""

    canonical = months(hold_period=3)
    result = recursive_recovery(
        canonical=canonical,
        the_pool=pool(canonical=canonical),
        **modified_gross("renewal", STOP_LOW_PSF),
        new_lease_type=LeaseType.NNN,
        renewal_term_months=5,
        new_term_months=7,
        renewal_probability=0.5,
    )

    generations = {c.parent_expiration_period for c in result.contributions}
    assert len(generations) >= 3, "fewer than three generations reached"

    for contribution in result.contributions:
        if contribution.branch is RolloverBranchKind.RENEWAL:
            assert contribution.successor_lease_type is LeaseType.MODIFIED_GROSS
            assert contribution.recovery_basis is RecoveryBasis.EXPENSE_STOP_PSF
            assert contribution.expense_stop_psf == strict(STOP_LOW_PSF)
            assert contribution.monthly_expense_stop_dollars == strict(STOP_LOW)
        else:
            assert contribution.successor_lease_type is LeaseType.NNN
            assert contribution.recovery_basis is None
            assert contribution.monthly_expense_stop_dollars is None


PREDECESSOR_STRUCTURES = [
    (LeaseType.NNN, None, None),
    (LeaseType.GROSS, None, None),
    (LeaseType.MODIFIED_GROSS, RecoveryBasis.EXPENSE_STOP_PSF, 5.0),
    (LeaseType.MODIFIED_GROSS, RecoveryBasis.EXPENSE_STOP_PSF, 40.0),
]


@pytest.mark.parametrize(
    ("lease_type", "basis", "stop"), PREDECESSOR_STRUCTURES, ids=lambda v: str(v)
)
def test_golden_7_successor_recovery_is_predecessor_structure_independent(
    lease_type: LeaseType, basis: RecoveryBasis | None, stop: float | None
) -> None:
    """**The most important recursive proof.** Two paths reaching one
    expiration state carry different predecessor structures; D2 merges their
    mass and D3 must attach **one** set of future child recovery economics.

    Since the in-place lease's own structure differs, only the *successor*
    series can be compared -- and it must be identical.
    """

    canonical = months(hold_period=3)
    overrides = {
        **modified_gross("renewal", STOP_LOW_PSF),
        "new_lease_type": LeaseType.NNN,
        "renewal_term_months": 5,
        "new_term_months": 7,
        "renewal_probability": 0.6,
    }
    the_pool = pool(canonical=canonical)

    reference = recursive_recovery(
        the_lease=lease(lease_id="ref"),
        canonical=canonical,
        the_pool=the_pool,
        **overrides,
    )
    other = recursive_recovery(
        the_lease=lease(
            lease_id="other",
            lease_type=lease_type,
            recovery_basis=basis,
            expense_stop_psf=stop,
            base_rent_psf=88.0,
        ),
        canonical=canonical,
        the_pool=the_pool,
        **overrides,
    )

    assert hexes(other.expected_successor_expense_recovery) == hexes(
        reference.expected_successor_expense_recovery
    )
    assert len(other.contributions) == len(reference.contributions)
    assert other.terminal_probability_mass == strict(
        reference.terminal_probability_mass
    )


def test_golden_7_merged_state_economics_match_the_explicit_tree() -> None:
    """The convergence claim checked against the independent enumeration, on a
    case whose paths genuinely merge."""

    canonical = months(hold_period=2)
    defaults = assumptions(
        **modified_gross("renewal", STOP_LOW_PSF),
        new_lease_type=LeaseType.NNN,
        renewal_term_months=4,
        new_term_months=4,
        renewal_downtime_months=2.0,
        new_downtime_months=0.0,
        renewal_probability=0.45,
    )
    the_pool = pool(canonical=canonical)

    rollover = build_recursive_rollover(
        lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )
    # Merging really happens: fewer states than transitions that reach them.
    assert len(rollover.event_states) < len(rollover.transitions)

    production = build_recursive_rollover_recovery(
        rollover,
        suite=suite(),
        analysis_start=JAN,
        property_defaults=defaults,
        pool=the_pool,
        rentable_area_sf=PROPERTY_AREA,
    )
    oracle = _explicit_recovery_oracle(
        the_lease=lease(), canonical=canonical, defaults=defaults, the_pool=the_pool
    )

    for expected_value, actual in zip(
        oracle, production.expected_successor_expense_recovery, strict=True
    ):
        assert actual == close(expected_value)


# =============================================================================
# GOLDEN 8 / 9 -- downtime and free rent across generations
# =============================================================================


def test_golden_8_a_later_generation_boundary_month_uses_the_fractional_factor() -> None:
    """``D = 2.25`` at a later generation still recovers at ``O = 0.75``, and
    for Modified Gross the factor stays outside the clip."""

    canonical = months(hold_period=3)
    defaults = assumptions(
        **modified_gross("new", STOP_LOW_PSF),
        renewal_lease_type=LeaseType.NNN,
        renewal_term_months=6,
        new_term_months=6,
        new_downtime_months=2.25,
        renewal_probability=0.5,
    )
    schedule = build_market_rent_schedule(
        suite(), property_defaults=defaults, months=canonical
    )
    rollover = build_recursive_rollover(
        lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )

    later = [
        t
        for t in rollover.transitions
        if t.branch is RolloverBranchKind.NEW_TENANT
        and t.parent_expiration_period > 12
        and t.commences_within_projection
    ]
    assert later, "no later-generation new-tenant transition inside the window"

    transition = later[0]
    contribution = build_successor_contribution(
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        market_schedule=schedule,
        parent_expiration_period=transition.parent_expiration_period,
        branch=transition.branch,
        lease_id_stem="check",
    )
    boundary = contribution.commencement_period - 1
    recovery = build_successor_recovery_schedule(
        branch=transition.branch,
        successor_lease=contribution.successor_lease,
        months=canonical,
        successor_occupancy_factor=contribution.successor_occupancy_factor,
        commencement_period=contribution.commencement_period,
        successor_expiration_period=contribution.successor_expiration_period,
        pool=pool(canonical=canonical),
        rentable_area_sf=PROPERTY_AREA,
    )

    assert contribution.successor_occupancy_factor[boundary] == strict(0.75)
    assert contribution.physical_occupancy[boundary] == strict(1.0)
    # O x max(0, 30,000 - 10,000), not max(0, 0.75 x 30,000 - 10,000).
    assert recovery.expense_recovery[boundary] == strict(0.75 * 20_000.0)
    assert recovery.expense_recovery[boundary] != pytest.approx(
        max(0.0, 0.75 * TENANT_SHARE - STOP_LOW), abs=1e-6
    )


def test_golden_9_free_rent_does_not_change_recursive_recovery() -> None:
    """**The mandatory free-rent proof, across generations.** Only base-rent
    cash may move; recovery is an expense reimbursement (D2 Section 7.3)."""

    canonical = months(hold_period=3)
    overrides = {
        **modified_gross("renewal", STOP_LOW_PSF),
        "new_lease_type": LeaseType.NNN,
        "renewal_term_months": 5,
        "new_term_months": 7,
        "renewal_probability": 0.55,
    }
    the_pool = pool(canonical=canonical)

    none_free = recursive_recovery(
        canonical=canonical, the_pool=the_pool, **overrides,
        renewal_free_rent_months=0.0, new_free_rent_months=0.0,
    )
    much_free = recursive_recovery(
        canonical=canonical, the_pool=the_pool, **overrides,
        renewal_free_rent_months=3.0, new_free_rent_months=6.0,
    )

    assert hexes(much_free.expected_expense_recovery) == hexes(
        none_free.expected_expense_recovery
    )
    # The control: free rent really did change the rent economics.
    assert hexes(much_free.rollover.expected_cash_base_rent) != hexes(
        none_free.rollover.expected_cash_base_rent
    )


def test_market_and_base_rent_do_not_change_recursive_recovery() -> None:
    """Recovery answers a question about expenses. Downtime is held equal so
    responsibility timing does not move."""

    canonical = months(hold_period=3)
    overrides = {
        "renewal_term_months": 5,
        "new_term_months": 7,
        "renewal_probability": 0.55,
    }
    the_pool = pool(canonical=canonical)

    cheap = recursive_recovery(
        the_lease=lease(base_rent_psf=0.0), canonical=canonical, the_pool=the_pool,
        market_rent_psf=0.0, **overrides,
    )
    dear = recursive_recovery(
        the_lease=lease(base_rent_psf=250.0), canonical=canonical, the_pool=the_pool,
        market_rent_psf=250.0, **overrides,
    )

    assert hexes(cheap.expected_expense_recovery) == hexes(
        dear.expected_expense_recovery
    )
    assert cheap.expected_expense_recovery[FIRST] > 0.0


# =============================================================================
# GOLDEN 10 -- the one-month stress
# =============================================================================


def test_golden_10_one_month_terms_stay_bounded_by_the_d2_transition_set() -> None:
    """``N = 132``, one-month terms, ``p = 0.5``, with the two branches on
    different structures.

    D2 processes on the order of ``N`` states and ``2N`` transitions. D3
    attaches exactly one recovery contribution per transition -- **not**
    ``2^131`` paths. The bound is structural: D3 iterates a list D2 produced.
    """

    canonical = months(hold_period=10)
    assert len(canonical) == 132

    result = recursive_recovery(
        canonical=canonical,
        the_pool=pool(canonical=canonical),
        **modified_gross("renewal", STOP_LOW_PSF),
        new_lease_type=LeaseType.NNN,
        renewal_term_months=1,
        new_term_months=1,
        renewal_probability=0.5,
    )

    states = len(result.rollover.event_states)
    transitions = len(result.rollover.transitions)

    assert states <= 132
    assert transitions <= 2 * 132
    assert states >= 100, "the stress case did not actually recurse"
    assert len(result.contributions) == transitions
    assert result.terminal_probability_mass == strict(
        result.rollover.terminal_probability_mass
    )
    assert all(math.isfinite(v) for v in result.expected_expense_recovery)


# =============================================================================
# GOLDEN 11 / 12 / 13 -- the horizon
# =============================================================================


def test_golden_11_later_generations_recover_in_the_forward_exit_window() -> None:
    """Recursion stays live through ``12H + 12``. A successor recovering after
    the hold period is real revenue and is not truncated at a sale month."""

    canonical = months(hold_period=2)
    result = recursive_recovery(
        canonical=canonical,
        the_pool=pool(canonical=canonical),
        renewal_term_months=4,
        new_term_months=4,
        renewal_probability=0.5,
    )

    forward = result.expected_successor_expense_recovery[24:]
    assert len(forward) == 12
    assert sum(forward) > 0.0, "no recovery in the forward exit window"
    assert result.expected_successor_expense_recovery[-1] > 0.0


def test_golden_12_a_commencement_beyond_the_horizon_contributes_zero() -> None:
    """No fabricated month, and no recovery moved earlier to compensate."""

    canonical = months(hold_period=1)
    defaults = assumptions(
        new_downtime_months=48.0, renewal_term_months=60, renewal_probability=0.5
    )
    rollover = build_recursive_rollover(
        lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )
    result = build_recursive_rollover_recovery(
        rollover,
        suite=suite(),
        analysis_start=JAN,
        property_defaults=defaults,
        pool=pool(canonical=canonical),
        rentable_area_sf=PROPERTY_AREA,
    )

    beyond = [
        c for c in result.contributions if not c.commences_within_projection
    ]
    assert beyond, "no out-of-window commencement in this case"
    for contribution in beyond:
        assert contribution.in_window_expense_recovery == strict(0.0)
        assert contribution.expected_expense_recovery_contribution == strict(0.0)


def test_golden_13_a_term_running_past_the_horizon_recovers_through_it() -> None:
    """A successor commencing inside the window and expiring beyond it
    recovers in every remaining canonical month, and creates no new event."""

    canonical = months(hold_period=2)
    result = recursive_recovery(
        canonical=canonical,
        the_pool=pool(canonical=canonical),
        renewal_term_months=120,
        new_term_months=120,
        renewal_probability=0.5,
    )

    assert len(result.rollover.transitions) == 2
    assert result.expected_successor_expense_recovery[-1] == strict(TENANT_SHARE)
    for contribution in result.contributions:
        assert contribution.successor_expiration_period > canonical[-1].period_index


# =============================================================================
# GOLDEN 14 / 15 / 18 -- the pool
# =============================================================================


def test_golden_14_a_pool_that_changes_every_month_is_consumed_per_month() -> None:
    """Catches any caching of the pool from the rollover event month: recovery
    must consume the pool of the **calendar month** the tenant is responsible
    for."""

    canonical = months(hold_period=2)
    varying = tuple(
        100_000.0 + 1_000.0 * index for index in range(len(canonical))
    )
    result = recursive_recovery(
        canonical=canonical,
        the_pool=pool(canonical=canonical, series=varying),
        renewal_term_months=60,
        new_term_months=60,
        renewal_probability=1.0,
    )

    # p = 1, no downtime: the renewal successor is responsible from period 13
    # and recovers its 20% of that month's own pool.
    for index in range(12, len(canonical)):
        assert result.expected_successor_expense_recovery[index] == strict(
            SHARE * varying[index]
        )

    # Distinct months really do differ, so a cached figure would fail.
    assert len(set(result.expected_successor_expense_recovery[12:])) == 24


def test_golden_15_a_zero_rent_successor_still_recovers() -> None:
    result = recursive_recovery(
        market_rent_psf=0.0, renewal_term_months=60, renewal_probability=1.0
    )

    assert result.rollover.expected_contractual_base_rent[FIRST] == strict(0.0)
    assert result.expected_successor_expense_recovery[FIRST] == strict(TENANT_SHARE)


def test_golden_18_a_pool_from_another_timeline_is_rejected() -> None:
    """Month identity, not length. A pool from a different projection would
    zip cleanly and produce a plausible, wrong answer."""

    canonical = months(hold_period=2)
    other = build_model_months(analysis_start=date(2030, 1, 1), hold_period=2)
    defaults = assumptions()

    rollover = build_recursive_rollover(
        lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )
    assert len(canonical) == len(other)

    with pytest.raises(ValueError, match="canonical timeline"):
        build_recursive_rollover_recovery(
            rollover,
            suite=suite(),
            analysis_start=JAN,
            property_defaults=defaults,
            pool=pool(canonical=other),
            rentable_area_sf=PROPERTY_AREA,
        )

    expected_roll = build_expected_rollover(
        lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )
    with pytest.raises(ValueError, match="canonical timeline"):
        build_expected_rollover_recovery(
            expected_roll,
            expiring=lease(),
            pool=pool(canonical=other),
            rentable_area_sf=PROPERTY_AREA,
        )


def test_a_rollover_for_another_suite_is_rejected() -> None:
    canonical = months()
    rollover = build_recursive_rollover(
        lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(),
    )

    with pytest.raises(ValueError, match="suite"):
        build_recursive_rollover_recovery(
            rollover,
            suite=Suite(suite_id="OTHER", suite_area_sf=AREA),
            analysis_start=JAN,
            property_defaults=assumptions(),
            pool=pool(canonical=canonical),
            rentable_area_sf=PROPERTY_AREA,
        )


def test_a_mismatched_expiring_lease_is_rejected() -> None:
    canonical = months()
    rollover = build_expected_rollover(
        lease(lease_id="L1"),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(),
    )

    with pytest.raises(ValueError, match="not the lease"):
        build_expected_rollover_recovery(
            rollover,
            expiring=lease(lease_id="SOMEONE_ELSE"),
            pool=pool(canonical=canonical),
            rentable_area_sf=PROPERTY_AREA,
        )


# =============================================================================
# The result contracts
# =============================================================================


def test_both_results_are_immutable_and_month_aligned() -> None:
    canonical = months(hold_period=4)
    first = expected_recovery(canonical=canonical, the_pool=pool(canonical=canonical))
    recursive = recursive_recovery(
        canonical=canonical, the_pool=pool(canonical=canonical)
    )

    for result in (first, recursive):
        assert result.months == canonical
        for series in (
            result.in_place_expense_recovery,
            result.expected_successor_expense_recovery,
            result.expected_expense_recovery,
        ):
            assert len(series) == len(canonical)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.expected_expense_recovery = ()  # type: ignore[misc]


def test_the_pure_branch_schedules_stay_auditable_on_the_result() -> None:
    """The composed figure must remain traceable to the structures that made
    it -- which is what makes the nonlinearity checkable by a reader."""

    result = expected_recovery(
        **modified_gross("renewal", STOP_LOW_PSF),
        **modified_gross("new", STOP_HIGH_PSF),
        renewal_probability=0.6,
    )

    assert result.renewal_recovery.branch is RolloverBranchKind.RENEWAL
    assert result.new_tenant_recovery.branch is RolloverBranchKind.NEW_TENANT
    assert result.renewal_recovery.expense_stop_psf == strict(STOP_LOW_PSF)
    assert result.new_tenant_recovery.expense_stop_psf == strict(STOP_HIGH_PSF)

    rebuilt = (
        0.6 * result.renewal_recovery.expense_recovery[FIRST]
        + 0.4 * result.new_tenant_recovery.expense_recovery[FIRST]
    )
    assert result.expected_successor_expense_recovery[FIRST] == close(rebuilt)


def test_the_recursive_result_retains_the_authoritative_rollover() -> None:
    """Rather than copying its state diagnostics: one owner, one answer."""

    result = recursive_recovery(renewal_term_months=5, renewal_probability=0.6)

    assert result.rollover.months == result.months
    assert result.rollover.event_states
    fields = {f.name for f in dataclasses.fields(result)}
    for absent in ("event_states", "transitions"):
        assert absent not in fields, (
            f"{absent} duplicates the retained rollover's diagnostics"
        )


def test_the_contribution_audit_separates_economics_from_the_weight() -> None:
    result = recursive_recovery(
        **modified_gross("renewal", STOP_LOW_PSF),
        new_lease_type=LeaseType.NNN,
        renewal_term_months=5,
        new_term_months=7,
        renewal_probability=0.6,
    )

    for contribution in result.contributions:
        assert contribution.expected_expense_recovery_contribution == close(
            contribution.probability_mass * contribution.in_window_expense_recovery
        )


def test_the_expected_series_is_the_sum_of_the_weighted_contributions() -> None:
    """The accumulation is legible: total expected successor recovery equals
    the sum of every transition's weighted contribution."""

    result = recursive_recovery(
        **modified_gross("renewal", STOP_LOW_PSF),
        new_lease_type=LeaseType.NNN,
        renewal_term_months=5,
        new_term_months=7,
        renewal_probability=0.6,
    )

    assert math.fsum(result.expected_successor_expense_recovery) == close(
        math.fsum(
            c.expected_expense_recovery_contribution for c in result.contributions
        )
    )


def test_no_d2_builder_gained_a_pool_dependency() -> None:
    """The D3.3 boundary held: composition happens beside the rollover, never
    inside it."""

    import inspect

    for builder in (build_expected_rollover, build_recursive_rollover):
        parameters = inspect.signature(builder).parameters
        for forbidden in ("pool", "expense_pool", "recoverable_expenses"):
            assert forbidden not in parameters

    for result_type in (
        build_expected_rollover(
            lease(),
            suite=suite(),
            analysis_start=JAN,
            months=months(),
            property_defaults=assumptions(),
        ),
        build_recursive_rollover(
            lease(),
            suite=suite(),
            analysis_start=JAN,
            months=months(),
            property_defaults=assumptions(),
        ),
    ):
        fields = {f.name for f in dataclasses.fields(result_type)}
        assert not any("recover" in name for name in fields)
