"""Sprint D Gate D3.3 -- successor recovery terms and pure-branch recoveries.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d3-recovery-conventions.md``
Sections 9.2, 9.3 and 10.2 (HD-D3-1 and HD-D3-2, both LOCKED), that when a
lease expires:

- **the successor's structure comes from its own branch's assumptions**, never
  from the lease it replaces. An existing `GROSS` lease whose renewal is
  `MODIFIED_GROSS` and whose new-tenant replacement is `NNN` is representable,
  and the predecessor's own type changes nothing (FM-D3-15);
- **each pure branch produces its own recovery schedule**, on its own
  structure, from the same injected pool;
- **the D2.6 merge key survives**, and is re-proved here rather than cited.
  Because every input to a successor's recoveries is a function of
  ``(branch kind, resolved assumptions, commencement period)``, two scenario
  paths reaching one expiration period still face identical futures -- so the
  recursion may continue merging on the expiration period alone.

The claims that fail silently if wrong:

- **the responsibility driver is ``successor_occupancy_factor``**, not
  ``physical_occupancy``. In the boundary month a fractional ``D`` creates,
  occupancy is the integral ``1`` while the successor owes only part of the
  month, so occupancy over-recovers exactly there (FM-D3-4, FM-D3-19);
- **free rent does not touch recovery.** Two branches identical but for free
  rent produce identical recovery schedules; only base-rent cash differs
  (D2 Section 7.3, FM-D3-3);
- **recovery is independent of rent**, so a market step that changes the
  successor's starting rent changes no recovery figure (FM-D3-2);
- **a suite rent override preserves the whole resolved record**, including
  every D3 successor field -- the D2.2 record-preserving fix, re-proved for
  fields that did not exist when it was written.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecoverableExpensePool,
    RecoveryBasis,
    RolloverBranchKind,
    Suite,
    build_lease_monthly_schedule,
    build_lease_recovery_schedule,
    build_market_rent_schedule,
    build_model_months,
    build_new_tenant_branch,
    build_recursive_rollover,
    build_renewal_branch,
    build_successor_contribution,
    build_successor_recovery_schedule,
    resolve_market_leasing,
    validate_successor_recovery_assumptions,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
    require_valid_successor_recovery_assumptions,
)


JAN = date(2027, 1, 1)
AREA = 20_000.0
PROPERTY_AREA = 100_000.0
SHARE = AREA / PROPERTY_AREA  # 0.20

#: $12.00/SF/YEAR on 20,000 SF is a $20,000 monthly stop -- the D3.2 frame,
#: reused so a units error is visible by arithmetic rather than inspection.
STOP_PSF = 12.0
MONTHLY_STOP = 20_000.0

POOL_AT_STOP = 100_000.0  # x 0.20 share = 20,000, exactly the stop
POOL_ABOVE_STOP = 150_000.0  # x 0.20 share = 30,000 -> 10,000 above


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def hexes(values: tuple[float, ...]) -> list[str]:
    return [value.hex() for value in values]


def months(*, hold_period: int = 3) -> tuple:
    return build_model_months(analysis_start=JAN, hold_period=hold_period)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    """Both branches NNN by default, so a test that cares about structure
    states it and a test that does not is unaffected by it."""

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


def modified_gross(branch: str, stop_psf: float = STOP_PSF) -> dict[str, object]:
    """Assumption overrides making one branch Modified Gross on an explicit
    stop, leaving the other branch alone."""

    return {
        f"{branch}_lease_type": LeaseType.MODIFIED_GROSS,
        f"{branch}_recovery_basis": RecoveryBasis.EXPENSE_STOP_PSF,
        f"{branch}_expense_stop_psf": stop_psf,
    }


def suite(suite_id: str = "S1") -> Suite:
    return Suite(suite_id=suite_id, suite_area_sf=AREA)


def expiring_lease(
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
    amount: float = POOL_ABOVE_STOP,
    *,
    canonical: tuple | None = None,
    series: tuple[float, ...] | None = None,
) -> RecoverableExpensePool:
    canonical = canonical if canonical is not None else months()
    expenses = series if series is not None else tuple([amount] * len(canonical))
    return RecoverableExpensePool(months=canonical, recoverable_expenses=expenses)


def renewal_branch(*, lease: Lease | None = None, **overrides: object):
    canonical = months()
    return build_renewal_branch(
        lease if lease is not None else expiring_lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(**overrides),
    )


def new_tenant_branch(*, lease: Lease | None = None, **overrides: object):
    canonical = months()
    return build_new_tenant_branch(
        lease if lease is not None else expiring_lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(**overrides),
    )


def recovery_for(branch_result, *, branch: RolloverBranchKind, the_pool=None):
    """The D3.3 builder, driven from a finished D2 branch."""

    return build_successor_recovery_schedule(
        branch=branch,
        successor_lease=branch_result.successor_lease,
        months=branch_result.months,
        successor_occupancy_factor=branch_result.successor_occupancy_factor,
        commencement_period=branch_result.commencement_period,
        successor_expiration_period=branch_result.successor_expiration_period,
        pool=the_pool if the_pool is not None else pool(canonical=branch_result.months),
        rentable_area_sf=PROPERTY_AREA,
    )


def renewal_recovery(*, lease: Lease | None = None, the_pool=None, **overrides: object):
    return recovery_for(
        renewal_branch(lease=lease, **overrides),
        branch=RolloverBranchKind.RENEWAL,
        the_pool=the_pool,
    )


def new_tenant_recovery(
    *, lease: Lease | None = None, the_pool=None, **overrides: object
):
    return recovery_for(
        new_tenant_branch(lease=lease, **overrides),
        branch=RolloverBranchKind.NEW_TENANT,
        the_pool=the_pool,
    )


# =============================================================================
# GOLDEN 1 -- Gross predecessor, NNN new tenant
# =============================================================================


def test_golden_1_a_gross_predecessor_is_replaced_by_a_first_dollar_nnn() -> None:
    """The case inheritance got wrong. A legacy Gross tenant leaves and the
    space is re-let NNN at prevailing terms; the replacement recovers from the
    first dollar even though its predecessor recovered nothing."""

    result = new_tenant_recovery(
        lease=expiring_lease(lease_type=LeaseType.GROSS),
        new_lease_type=LeaseType.NNN,
    )

    assert result.successor_lease_type is LeaseType.NNN
    assert result.recovery_basis is None
    assert result.monthly_expense_stop_dollars is None
    assert result.tenant_pro_rata_share == strict(SHARE)

    # Successor commences at period 13 (e = 12, D = 0), and recovers in full.
    assert result.expense_recovery[11] == strict(0.0)
    assert result.expense_recovery[12] == strict(SHARE * POOL_ABOVE_STOP)
    assert result.expense_recovery[12] == strict(30_000.0)


def test_golden_1_the_predecessor_recovers_nothing_over_the_same_pool() -> None:
    """Both figures are true at once, and they are computed by the same
    formula from the same pool: the difference is the *structure*, which
    changed at the rollover because the assumptions said so."""

    lease = expiring_lease(lease_type=LeaseType.GROSS)
    canonical = months()
    in_place = build_lease_recovery_schedule(
        lease,
        schedule=build_lease_monthly_schedule(
            lease, analysis_start=JAN, months=canonical
        ),
        pool=pool(canonical=canonical),
        rentable_area_sf=PROPERTY_AREA,
    )

    assert all(value == 0.0 for value in in_place.expense_recovery)

    successor = new_tenant_recovery(lease=lease, new_lease_type=LeaseType.NNN)
    assert successor.expense_recovery[12] == strict(30_000.0)


# =============================================================================
# GOLDEN 2 -- Gross predecessor, Modified Gross renewal
# =============================================================================


def test_golden_2_a_gross_predecessor_renews_modified_gross_on_its_own_stop() -> None:
    """The D3.2 formula, reached through a rollover successor rather than an
    in-place lease -- and it is the *same* formula, not a branch copy."""

    result = renewal_recovery(**modified_gross("renewal"))

    assert result.successor_lease_type is LeaseType.MODIFIED_GROSS
    assert result.recovery_basis is RecoveryBasis.EXPENSE_STOP_PSF
    assert result.expense_stop_psf == strict(STOP_PSF)
    assert result.monthly_expense_stop_dollars == strict(MONTHLY_STOP)

    # share 30,000 against a 20,000 stop -> 10,000
    assert result.tenant_recoverable_expense_share[12] == strict(30_000.0)
    assert result.expense_recovery[12] == strict(10_000.0)


def test_golden_2_the_successor_stop_matches_an_identical_in_place_lease() -> None:
    """A rollover successor and a known lease with the same terms must agree
    exactly. They share one implementation, so this pins that they still do."""

    successor = renewal_recovery(**modified_gross("renewal"))

    canonical = months()
    equivalent = Lease(
        lease_id="equivalent",
        suite_id="S1",
        leased_area_sf=AREA,
        rent_commencement_date=date(2028, 1, 1),
        lease_expiration_date=date(2032, 12, 31),
        base_rent_psf=40.0,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        lease_type=LeaseType.MODIFIED_GROSS,
        recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        expense_stop_psf=STOP_PSF,
    )
    in_place = build_lease_recovery_schedule(
        equivalent,
        schedule=build_lease_monthly_schedule(
            equivalent, analysis_start=JAN, months=canonical
        ),
        pool=pool(canonical=canonical),
        rentable_area_sf=PROPERTY_AREA,
    )

    assert successor.monthly_expense_stop_dollars == strict(
        in_place.monthly_expense_stop_dollars
    )
    assert hexes(successor.expense_recovery) == hexes(in_place.expense_recovery)


# =============================================================================
# GOLDEN 3 -- NNN predecessor, Gross successor
# =============================================================================


def test_golden_3_an_nnn_predecessor_does_not_leak_into_a_gross_successor() -> None:
    """The reverse leak, and the one a plausible implementation makes: the
    predecessor recovers its full share, so a successor that inherited would
    keep recovering. It must recover exactly zero."""

    result = new_tenant_recovery(
        lease=expiring_lease(lease_type=LeaseType.NNN),
        new_lease_type=LeaseType.GROSS,
    )

    assert result.successor_lease_type is LeaseType.GROSS
    assert all(value == 0.0 for value in result.expense_recovery)
    assert all(value == 0.0 for value in result.full_month_expense_recovery)
    assert result.monthly_expense_stop_dollars is None


def test_golden_3_the_tenant_share_is_still_reported_for_a_gross_successor() -> None:
    """`GROSS` owes none of the pool, but the audit series still says what its
    arithmetic share *was* -- so a zero is legible as a structure decision
    rather than a missing input."""

    result = new_tenant_recovery(new_lease_type=LeaseType.GROSS)

    assert result.tenant_recoverable_expense_share[12] == strict(30_000.0)
    assert result.expense_recovery[12] == strict(0.0)
    assert result.economic_responsibility_factor[12] == strict(1.0)


# =============================================================================
# GOLDEN 4 -- the two branches take different structures
# =============================================================================


def test_golden_4_one_parent_produces_two_differently_structured_successors() -> None:
    """HD-D3-1 and HD-D3-2 together: one expiring lease, two branches, two
    structures, two recovery answers -- and no probability anywhere."""

    overrides = {
        **modified_gross("renewal"),
        "new_lease_type": LeaseType.NNN,
    }
    parent = expiring_lease(lease_type=LeaseType.GROSS)

    renewal = renewal_recovery(lease=parent, **overrides)
    new_tenant = new_tenant_recovery(lease=parent, **overrides)

    assert renewal.branch is RolloverBranchKind.RENEWAL
    assert new_tenant.branch is RolloverBranchKind.NEW_TENANT

    assert renewal.successor_lease_type is LeaseType.MODIFIED_GROSS
    assert new_tenant.successor_lease_type is LeaseType.NNN

    assert renewal.expense_recovery[12] == strict(10_000.0)
    assert new_tenant.expense_recovery[12] == strict(30_000.0)


def test_golden_4_neither_branch_result_carries_a_probability() -> None:
    """D3.3 is the pure-branch gate. Weighting is D3.4's, and a probability
    field here would be the seam through which it leaked early."""

    fields = {f.name for f in dataclasses.fields(renewal_recovery())}

    for absent in (
        "renewal_probability",
        "probability",
        "probability_mass",
        "expected_expense_recovery",
    ):
        assert absent not in fields


# =============================================================================
# GOLDEN 5 -- different stops on the two branches
# =============================================================================


def test_golden_5_each_branch_clips_at_its_own_stop() -> None:
    """Renewal at $10/SF/YR and a new letting at $20/SF/YR, over one pool.

    Monthly stops are $16,667 (10 x 20,000 / 12) and $33,333. Against a
    $30,000 tenant share the renewal recovers the difference and the new
    tenant, whose stop exceeds its share, recovers nothing.
    """

    overrides = {
        **modified_gross("renewal", stop_psf=10.0),
        **modified_gross("new", stop_psf=20.0),
    }
    parent = expiring_lease()

    renewal = renewal_recovery(lease=parent, **overrides)
    new_tenant = new_tenant_recovery(lease=parent, **overrides)

    assert renewal.monthly_expense_stop_dollars == strict(10.0 * AREA / 12.0)
    assert new_tenant.monthly_expense_stop_dollars == strict(20.0 * AREA / 12.0)

    assert renewal.expense_recovery[12] == strict(30_000.0 - 10.0 * AREA / 12.0)
    assert new_tenant.expense_recovery[12] == strict(0.0)


def test_golden_5_a_higher_stop_never_recovers_more() -> None:
    """Monotonicity in the stop, which the clip guarantees and a reversed
    subtraction would invert."""

    parent = expiring_lease()
    recoveries = [
        renewal_recovery(
            lease=parent, **modified_gross("renewal", stop_psf=stop)
        ).expense_recovery[12]
        for stop in (0.0, 6.0, 12.0, 18.0, 24.0)
    ]

    for higher, lower in zip(recoveries, recoveries[1:], strict=False):
        assert higher >= lower
    assert recoveries[0] > recoveries[-1]


# =============================================================================
# GOLDEN 6 -- fractional commencement drives recovery through O
# =============================================================================


def test_golden_6_the_boundary_month_recovers_at_the_fractional_factor() -> None:
    """**The mandatory placement case.** With ``D = 2.25`` the successor
    commences part-way through its first month and is responsible for
    ``1 - 0.25 = 0.75`` of it.

    ``physical_occupancy`` is the integral ``1`` in that same month. Using it
    would recover the full ``$30,000`` where only ``$22,500`` is owed
    (FM-D3-4).
    """

    branch = new_tenant_branch(new_downtime_months=2.25)
    result = recovery_for(branch, branch=RolloverBranchKind.NEW_TENANT)

    # e = 12, D = 2.25 -> c = 12 + 1 + 2 = 15, i.e. index 14.
    assert branch.commencement_period == 15
    boundary = branch.commencement_period - 1

    assert branch.successor_occupancy_factor[boundary] == strict(0.75)
    assert branch.physical_occupancy[boundary] == strict(1.0)

    assert result.economic_responsibility_factor[boundary] == strict(0.75)
    assert result.expense_recovery[boundary] == strict(0.75 * 30_000.0)
    assert result.expense_recovery[boundary] != strict(30_000.0)


def test_golden_6_the_factor_series_is_the_branchs_own_occupancy_factor() -> None:
    """Carried through unchanged rather than recomputed, so the two can never
    disagree about a boundary month."""

    branch = new_tenant_branch(new_downtime_months=2.25)
    result = recovery_for(branch, branch=RolloverBranchKind.NEW_TENANT)

    assert hexes(result.economic_responsibility_factor) == hexes(
        branch.successor_occupancy_factor
    )
    assert hexes(result.economic_responsibility_factor) != hexes(
        branch.physical_occupancy
    )


def test_golden_6_a_modified_gross_boundary_scales_the_clipped_obligation() -> None:
    """FM-D3-19 through a successor. The factor scales the *obligation*, so the
    boundary month recovers ``0.75 x 10,000``, not ``max(0, 0.75 x 30,000 -
    20,000)`` which would be ``$2,500``."""

    branch = new_tenant_branch(
        new_downtime_months=2.25, **modified_gross("new")
    )
    result = recovery_for(branch, branch=RolloverBranchKind.NEW_TENANT)
    boundary = branch.commencement_period - 1

    assert result.expense_recovery[boundary] == strict(0.75 * 10_000.0)
    assert result.expense_recovery[boundary] == strict(7_500.0)

    wrong = max(0.0, 0.75 * 30_000.0 - MONTHLY_STOP)
    assert wrong == strict(2_500.0)
    assert result.expense_recovery[boundary] != pytest.approx(wrong, abs=1e-6)


def test_golden_6_full_downtime_months_recover_nothing() -> None:
    """Downtime reaches recovery only through the factor. The landlord bears
    the expense while the space is empty (FM-D3-13)."""

    branch = new_tenant_branch(new_downtime_months=3.0)
    result = recovery_for(branch, branch=RolloverBranchKind.NEW_TENANT)

    for index in range(12, 15):  # the three vacant months after e = 12
        assert branch.successor_occupancy_factor[index] == strict(0.0)
        assert result.expense_recovery[index] == strict(0.0)


# =============================================================================
# GOLDEN 7 -- free-rent independence
# =============================================================================


def test_golden_7_free_rent_does_not_reduce_recovery() -> None:
    """**The mandatory branch test.** Same successor, same pool, same
    structure, same downtime -- one branch with no free rent and one with six
    months. The recovery schedules must be identical at float level.

    A rent concession is a concession against *base rent*. Inferring a recovery
    abatement from it would silently change every lease with free rent
    (D2 Section 7.3, HD-D3-7, FM-D3-3).
    """

    none_free = new_tenant_recovery(new_free_rent_months=0.0)
    six_free = new_tenant_recovery(new_free_rent_months=6.0)

    assert hexes(none_free.expense_recovery) == hexes(six_free.expense_recovery)
    assert hexes(none_free.economic_responsibility_factor) == hexes(
        six_free.economic_responsibility_factor
    )
    assert hexes(none_free.full_month_expense_recovery) == hexes(
        six_free.full_month_expense_recovery
    )


def test_golden_7_base_rent_cash_does_differ_between_those_branches() -> None:
    """The control: free rent is doing something, just not to recoveries. If
    both branches were identical in cash too, the test above would prove
    nothing."""

    none_free = new_tenant_branch(new_free_rent_months=0.0)
    six_free = new_tenant_branch(new_free_rent_months=6.0)

    assert hexes(none_free.cash_base_rent) != hexes(six_free.cash_base_rent)
    assert sum(six_free.cash_base_rent) < sum(none_free.cash_base_rent)
    # ...and face rent is untouched, as D2 already fixed.
    assert hexes(none_free.contractual_base_rent) == hexes(
        six_free.contractual_base_rent
    )


def test_golden_7_free_rent_independence_holds_for_modified_gross_too() -> None:
    """The clip is where a cash factor would most plausibly be applied by
    mistake, so the claim is re-proved on the structure that has one."""

    overrides = modified_gross("new")
    none_free = new_tenant_recovery(new_free_rent_months=0.0, **overrides)
    six_free = new_tenant_recovery(new_free_rent_months=6.0, **overrides)

    assert hexes(none_free.expense_recovery) == hexes(six_free.expense_recovery)
    assert none_free.expense_recovery[12] == strict(10_000.0)


# =============================================================================
# GOLDEN 8 -- a market step changes rent, not recovery
# =============================================================================


def test_golden_8_a_market_step_across_downtime_leaves_recovery_unchanged() -> None:
    """Downtime carries commencement over a market-rent anniversary, so the
    successor prices at the *stepped* level. Recovery is determined by pool,
    share, structure and ``O`` -- none of which moved."""

    flat = new_tenant_branch(market_rent_growth=0.0, new_downtime_months=1.0)
    growing = new_tenant_branch(market_rent_growth=0.10, new_downtime_months=1.0)

    # The market step really did change the successor's rent.
    assert growing.starting_rent_psf > flat.starting_rent_psf
    assert hexes(growing.contractual_base_rent) != hexes(flat.contractual_base_rent)

    flat_recovery = recovery_for(flat, branch=RolloverBranchKind.NEW_TENANT)
    growing_recovery = recovery_for(growing, branch=RolloverBranchKind.NEW_TENANT)

    assert hexes(growing_recovery.expense_recovery) == hexes(
        flat_recovery.expense_recovery
    )


def test_golden_8_a_zero_rent_successor_recovers_like_any_other() -> None:
    """Recovery answers a question about expenses. A ``$0/SF`` market and a
    ``$100/SF`` market produce identical recovery schedules (FM-D3-2)."""

    cheap = new_tenant_recovery(market_rent_psf=0.0)
    dear = new_tenant_recovery(market_rent_psf=100.0)

    assert hexes(cheap.expense_recovery) == hexes(dear.expense_recovery)
    assert cheap.expense_recovery[12] == strict(30_000.0)


def test_golden_8_escalation_does_not_reach_recovery() -> None:
    """A successor escalating at 5% a year recovers exactly what a flat one
    recovers."""

    flat = new_tenant_recovery(successor_escalation_pct=0.0)
    escalating = new_tenant_recovery(successor_escalation_pct=0.05)

    assert hexes(flat.expense_recovery) == hexes(escalating.expense_recovery)


# =============================================================================
# GOLDEN 9 -- a suite rent override preserves every D3 field
# =============================================================================


def test_golden_9_a_suite_rent_override_preserves_the_d3_successor_fields() -> None:
    """The D2.2 record-preserving fix, re-proved for fields that did not exist
    when it was written.

    ``Suite.market_rent_psf`` overrides the market rent **level** and nothing
    else. The bug this guards against -- rebuilding the resolved record field
    by field -- would silently drop the successor's lease type and stop, and
    the resulting recovery schedule would look entirely plausible.
    """

    defaults = assumptions(
        **modified_gross("renewal", stop_psf=7.5),
        new_lease_type=LeaseType.GROSS,
    )
    overridden = Suite(suite_id="S1", suite_area_sf=AREA, market_rent_psf=99.0)

    resolved = resolve_market_leasing(overridden, property_defaults=defaults)

    assert resolved.market_rent_psf_from_suite is True
    assert resolved.assumptions.market_rent_psf == strict(99.0)

    # Every D3.3 field survives untouched.
    assert resolved.assumptions.renewal_lease_type is LeaseType.MODIFIED_GROSS
    assert (
        resolved.assumptions.renewal_recovery_basis
        is RecoveryBasis.EXPENSE_STOP_PSF
    )
    assert resolved.assumptions.renewal_expense_stop_psf == strict(7.5)
    assert resolved.assumptions.new_lease_type is LeaseType.GROSS
    assert resolved.assumptions.new_recovery_basis is None
    assert resolved.assumptions.new_expense_stop_psf is None


def test_golden_9_the_override_changes_exactly_one_field_of_the_record() -> None:
    """Asserted over the whole record rather than field by field, so a field
    added by a later gate is covered by this test on the day it lands."""

    defaults = assumptions(**modified_gross("renewal"))
    plain = resolve_market_leasing(suite(), property_defaults=defaults)
    overridden = resolve_market_leasing(
        Suite(suite_id="S1", suite_area_sf=AREA, market_rent_psf=99.0),
        property_defaults=defaults,
    )

    assert plain.assumptions == defaults
    assert overridden.assumptions == dataclasses.replace(
        defaults, market_rent_psf=99.0
    )


def test_golden_9_an_overridden_suite_still_prices_recoveries_correctly() -> None:
    """End to end: the override reaches a real successor, and the structure it
    preserved is the one that gets used."""

    canonical = months()
    branch = build_renewal_branch(
        expiring_lease(),
        suite=Suite(suite_id="S1", suite_area_sf=AREA, market_rent_psf=99.0),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(**modified_gross("renewal")),
    )
    result = recovery_for(branch, branch=RolloverBranchKind.RENEWAL)

    assert branch.starting_rent_psf == strict(99.0)
    assert result.successor_lease_type is LeaseType.MODIFIED_GROSS
    assert result.expense_recovery[12] == strict(10_000.0)


# =============================================================================
# GOLDEN 10 -- predecessor structure independence
# =============================================================================


PREDECESSOR_STRUCTURES = [
    (LeaseType.NNN, None, None),
    (LeaseType.GROSS, None, None),
    (LeaseType.MODIFIED_GROSS, RecoveryBasis.EXPENSE_STOP_PSF, 5.0),
    (LeaseType.MODIFIED_GROSS, RecoveryBasis.EXPENSE_STOP_PSF, 40.0),
]


@pytest.mark.parametrize(
    ("lease_type", "basis", "stop"), PREDECESSOR_STRUCTURES, ids=lambda v: str(v)
)
def test_golden_10_future_economics_are_identical_whatever_the_predecessor_was(
    lease_type: LeaseType, basis: RecoveryBasis | None, stop: float | None
) -> None:
    """**The path-independence proof** (D3 Section 10.2).

    Four predecessors with the same suite, area and expiration but different
    structures. Under one set of future assumptions every successor figure --
    dates, rent, term, TI, LC and recovery dollars -- is identical.
    """

    overrides = {
        **modified_gross("renewal"),
        "new_lease_type": LeaseType.GROSS,
    }
    reference = renewal_recovery(lease=expiring_lease(lease_id="ref"), **overrides)

    parent = expiring_lease(
        lease_id="other",
        lease_type=lease_type,
        recovery_basis=basis,
        expense_stop_psf=stop,
        base_rent_psf=77.0,  # a different rent, too
    )
    result = renewal_recovery(lease=parent, **overrides)

    assert result.successor_lease_type is reference.successor_lease_type
    assert result.recovery_basis is reference.recovery_basis
    assert result.expense_stop_psf == strict(reference.expense_stop_psf)
    assert result.monthly_expense_stop_dollars == strict(
        reference.monthly_expense_stop_dollars
    )
    assert hexes(result.expense_recovery) == hexes(reference.expense_recovery)
    assert hexes(result.economic_responsibility_factor) == hexes(
        reference.economic_responsibility_factor
    )


@pytest.mark.parametrize(
    ("lease_type", "basis", "stop"), PREDECESSOR_STRUCTURES, ids=lambda v: str(v)
)
def test_golden_10_the_whole_d2_branch_is_predecessor_structure_independent(
    lease_type: LeaseType, basis: RecoveryBasis | None, stop: float | None
) -> None:
    """The same claim across every accepted D2 series, so a structure leak into
    rent, timing, TI or LC would fail here rather than only in recoveries."""

    overrides = {**modified_gross("renewal"), "renewal_downtime_months": 2.25}
    reference = renewal_branch(lease=expiring_lease(lease_id="ref"), **overrides)
    other = renewal_branch(
        lease=expiring_lease(
            lease_id="other",
            lease_type=lease_type,
            recovery_basis=basis,
            expense_stop_psf=stop,
        ),
        **overrides,
    )

    assert other.commencement_period == reference.commencement_period
    assert other.successor_expiration_period == reference.successor_expiration_period
    assert other.term_months == reference.term_months
    assert other.starting_rent_psf == strict(reference.starting_rent_psf)
    assert other.successor_lease.rent_commencement_date == (
        reference.successor_lease.rent_commencement_date
    )
    assert other.successor_lease.lease_expiration_date == (
        reference.successor_lease.lease_expiration_date
    )

    for series in (
        "successor_occupancy_factor",
        "cash_rent_factor",
        "free_rent_abatement_months",
        "tenant_improvements",
        "leasing_commissions",
    ):
        assert hexes(getattr(other, series)) == hexes(getattr(reference, series))


def test_golden_10_the_successor_lease_carries_the_branch_structure() -> None:
    """One contractual representation: the recovery schedule and the successor
    ``Lease`` agree, because the schedule reads the lease."""

    branch = renewal_branch(**modified_gross("renewal", stop_psf=9.0))
    result = recovery_for(branch, branch=RolloverBranchKind.RENEWAL)

    assert branch.successor_lease.lease_type is LeaseType.MODIFIED_GROSS
    assert branch.successor_lease.recovery_basis is RecoveryBasis.EXPENSE_STOP_PSF
    assert branch.successor_lease.expense_stop_psf == strict(9.0)
    assert branch.successor_lease.origin is LeaseOrigin.SUCCESSOR

    assert result.successor_lease_type is branch.successor_lease.lease_type
    assert result.recovery_basis is branch.successor_lease.recovery_basis
    assert result.expense_stop_psf == strict(branch.successor_lease.expense_stop_psf)


# =============================================================================
# GOLDEN 11 -- converged state, one future
# =============================================================================


def test_golden_11_two_paths_converging_on_one_period_have_one_future() -> None:
    """**The re-proved merge key.** Two predecessors differing in lease id,
    structure, recovery terms and rent, but sharing a suite, an area and an
    expiration period. Processing the state once must equal processing each
    path separately, for every branch.

    This is what licenses ``build_recursive_rollover`` to keep merging on the
    expiration period alone: the state carries no structural dimension because
    no future economics read one.
    """

    canonical = months()
    schedule = build_market_rent_schedule(
        suite(),
        property_defaults=assumptions(
            **modified_gross("renewal"), new_lease_type=LeaseType.GROSS
        ),
        months=canonical,
    )
    the_pool = pool(canonical=canonical)

    for branch_kind in RolloverBranchKind:
        # The engine takes no predecessor at all, so "two paths" can differ
        # only in the state -- and the state here is one period.
        contribution = build_successor_contribution(
            suite=suite(),
            analysis_start=JAN,
            months=canonical,
            market_schedule=schedule,
            parent_expiration_period=12,
            branch=branch_kind,
            lease_id_stem="converged@e12",
        )
        again = build_successor_contribution(
            suite=suite(),
            analysis_start=JAN,
            months=canonical,
            market_schedule=schedule,
            parent_expiration_period=12,
            branch=branch_kind,
            lease_id_stem="converged@e12",
        )

        assert contribution.successor_lease == again.successor_lease

        first = build_successor_recovery_schedule(
            branch=branch_kind,
            successor_lease=contribution.successor_lease,
            months=canonical,
            successor_occupancy_factor=contribution.successor_occupancy_factor,
            commencement_period=contribution.commencement_period,
            successor_expiration_period=contribution.successor_expiration_period,
            pool=the_pool,
            rentable_area_sf=PROPERTY_AREA,
        )
        second = build_successor_recovery_schedule(
            branch=branch_kind,
            successor_lease=again.successor_lease,
            months=canonical,
            successor_occupancy_factor=again.successor_occupancy_factor,
            commencement_period=again.commencement_period,
            successor_expiration_period=again.successor_expiration_period,
            pool=the_pool,
            rentable_area_sf=PROPERTY_AREA,
        )

        assert first == second


def test_golden_11_the_successor_engine_takes_no_predecessor_at_all() -> None:
    """Why the convergence above is structural rather than lucky: there is no
    parameter through which a predecessor could reach the calculation."""

    import inspect

    parameters = set(inspect.signature(build_successor_contribution).parameters)

    assert parameters == {
        "suite",
        "analysis_start",
        "months",
        "market_schedule",
        "parent_expiration_period",
        "branch",
        "lease_id_stem",
        # D3.6 added exactly one: this event's own delay, defaulting to None so
        # every D2 call site is unchanged. It is a timing input, not a
        # predecessor -- two callers passing the same value at the same
        # (parent_expiration_period, branch) get identical economics, so the
        # merge key is unaffected.
        "event_downtime_months",
    }


def test_golden_11_recursion_state_counts_are_unchanged_by_structure() -> None:
    """The merge is still happening, and D3.3 did not multiply the state count.
    Four different predecessor structures produce the same states, the same
    transitions, and the same economics."""

    canonical = months(hold_period=4)
    overrides = {
        **modified_gross("renewal"),
        "new_lease_type": LeaseType.GROSS,
        "renewal_term_months": 5,
        "new_term_months": 9,
        "renewal_downtime_months": 1.0,
        "new_downtime_months": 2.25,
    }

    results = [
        build_recursive_rollover(
            expiring_lease(
                lease_id=f"L{index}",
                lease_type=lease_type,
                recovery_basis=basis,
                expense_stop_psf=stop,
            ),
            suite=suite(),
            analysis_start=JAN,
            months=canonical,
            property_defaults=assumptions(**overrides),
        )
        for index, (lease_type, basis, stop) in enumerate(PREDECESSOR_STRUCTURES)
    ]

    reference = results[0]
    for result in results[1:]:
        assert len(result.event_states) == len(reference.event_states)
        assert len(result.transitions) == len(reference.transitions)
        assert hexes(result.expected_contractual_base_rent) == hexes(
            reference.expected_contractual_base_rent
        )
        assert hexes(result.expected_cash_base_rent) == hexes(
            reference.expected_cash_base_rent
        )
        assert hexes(result.expected_occupancy) == hexes(reference.expected_occupancy)


# =============================================================================
# GOLDEN 12 -- D2 economics preserved
# =============================================================================


def test_golden_12_the_pool_is_never_required_by_a_d2_builder() -> None:
    """**The injection boundary.** Every D2 builder still runs with no pool in
    existence; recovery is added beside a finished branch, never inside it."""

    import inspect

    for builder in (
        build_renewal_branch,
        build_new_tenant_branch,
        build_recursive_rollover,
        build_successor_contribution,
    ):
        parameters = inspect.signature(builder).parameters
        for forbidden in ("pool", "expense_pool", "recoverable_expenses"):
            assert forbidden not in parameters, (
                f"{builder.__name__} requires {forbidden!r}"
            )

    # And they genuinely run: no pool is constructed anywhere in this test.
    assert renewal_branch().successor_lease is not None


def test_golden_12_no_recovery_field_appears_on_a_d2_result() -> None:
    """D2 results are rent and occupancy. A recovery series on one of them
    would be recovery revenue folded into a rent structure (FM-D3-1)."""

    for result in (renewal_branch(), new_tenant_branch()):
        fields = {f.name for f in dataclasses.fields(result)}
        assert not any("recovery" in name for name in fields)
        assert not any("recoverable" in name for name in fields)


def test_golden_12_recovery_does_not_alter_the_branch_it_was_built_from() -> None:
    """Building a recovery schedule is a read. The branch is unchanged
    afterwards, so ordering the two calls differently cannot change a figure."""

    branch = renewal_branch(**modified_gross("renewal"))
    before = dataclasses.asdict(branch)

    recovery_for(branch, branch=RolloverBranchKind.RENEWAL)

    assert dataclasses.asdict(branch) == before


# =============================================================================
# Validation
# =============================================================================


def test_a_modified_gross_branch_without_a_basis_is_an_error() -> None:
    """FM-D3-6 at the branch level: never inferred, and now explicitly never
    inherited from the lease being replaced."""

    result = validate_successor_recovery_assumptions(
        assumptions(renewal_lease_type=LeaseType.MODIFIED_GROSS)
    )

    assert not result.is_valid
    issue = next(
        issue
        for issue in result.issues
        if issue.code is LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS
    )
    assert issue.severity is LeaseIssueSeverity.ERROR
    assert "renewal" in issue.path

    with pytest.raises(LeaseValidationError):
        require_valid_successor_recovery_assumptions(
            assumptions(renewal_lease_type=LeaseType.MODIFIED_GROSS)
        )


def test_each_branch_is_validated_independently() -> None:
    """A valid renewal does not excuse an invalid new-tenant branch, and the
    issue names which one failed."""

    result = validate_successor_recovery_assumptions(
        assumptions(
            **modified_gross("renewal"),
            new_lease_type=LeaseType.MODIFIED_GROSS,
        )
    )

    assert not result.is_valid
    codes = [issue.code for issue in result.issues]
    assert codes == [LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS]
    assert "new" in result.issues[0].path


@pytest.mark.parametrize("branch", ["renewal", "new"])
@pytest.mark.parametrize("lease_type", [LeaseType.NNN, LeaseType.GROSS])
def test_a_stop_on_a_non_modified_gross_branch_is_an_error(
    branch: str, lease_type: LeaseType
) -> None:
    """A stop implies Modified Gross. Consuming one silently would make the
    branch's ``lease_type`` unreliable as an economic discriminator."""

    result = validate_successor_recovery_assumptions(
        assumptions(
            **{
                f"{branch}_lease_type": lease_type,
                f"{branch}_recovery_basis": RecoveryBasis.EXPENSE_STOP_PSF,
                f"{branch}_expense_stop_psf": STOP_PSF,
            }
        )
    )

    assert not result.is_valid
    assert LeaseIssueCode.RECOVERY_BASIS_ON_NON_MODIFIED_GROSS in [
        issue.code for issue in result.issues
    ]


def test_a_negative_branch_stop_is_an_error() -> None:
    result = validate_successor_recovery_assumptions(
        assumptions(**modified_gross("new", stop_psf=-1.0))
    )

    assert not result.is_valid
    assert LeaseIssueCode.EXPENSE_STOP_OUT_OF_DOMAIN in [
        issue.code for issue in result.issues
    ]


def test_a_zero_branch_stop_is_valid() -> None:
    """Domain is ``>= 0``. A zero stop makes a Modified Gross successor recover
    its full share -- a negotiated outcome, not a data error."""

    result = validate_successor_recovery_assumptions(
        assumptions(**modified_gross("renewal", stop_psf=0.0))
    )

    assert result.is_valid

    recovery = renewal_recovery(**modified_gross("renewal", stop_psf=0.0))
    assert recovery.expense_recovery[12] == strict(30_000.0)


def test_valid_branch_assumptions_produce_no_issues() -> None:
    result = validate_successor_recovery_assumptions(
        assumptions(**modified_gross("renewal"), new_lease_type=LeaseType.GROSS)
    )

    assert result.is_valid
    assert result.issues == ()


def test_branch_recovery_validation_does_not_invalidate_a_d2_rollover() -> None:
    """Scoped, like D3.1's. Assumptions that cannot yet price a recovery are
    still legitimate D2 rollover input -- the refusal belongs to the
    calculation that needs the information, and to nothing else."""

    incomplete = assumptions(renewal_lease_type=LeaseType.MODIFIED_GROSS)

    assert not validate_successor_recovery_assumptions(incomplete).is_valid

    # The D2 branch still builds, and its rent economics are unaffected.
    branch = build_renewal_branch(
        expiring_lease(),
        suite=suite(),
        analysis_start=JAN,
        months=months(),
        property_defaults=incomplete,
    )
    assert branch.starting_rent_psf == strict(40.0)


def test_the_recovery_builder_refuses_an_unpriceable_successor() -> None:
    """Belt and braces: if validation is skipped, the builder refuses rather
    than defaulting the stop to zero."""

    branch = build_renewal_branch(
        expiring_lease(),
        suite=suite(),
        analysis_start=JAN,
        months=months(),
        property_defaults=assumptions(renewal_lease_type=LeaseType.MODIFIED_GROSS),
    )

    with pytest.raises(ValueError, match="MODIFIED_GROSS"):
        recovery_for(branch, branch=RolloverBranchKind.RENEWAL)


# =============================================================================
# The result contract
# =============================================================================


def test_the_schedule_is_aligned_to_the_canonical_months() -> None:
    canonical = months(hold_period=5)
    branch = build_renewal_branch(
        expiring_lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(),
    )
    result = recovery_for(
        branch,
        branch=RolloverBranchKind.RENEWAL,
        the_pool=pool(canonical=canonical),
    )

    assert len(canonical) == 5 * 12 + 12
    assert result.months == canonical
    for series in (
        result.economic_responsibility_factor,
        result.tenant_recoverable_expense_share,
        result.full_month_expense_recovery,
        result.expense_recovery,
    ):
        assert len(series) == len(canonical)


def test_a_pool_from_a_different_timeline_is_refused() -> None:
    """Month identity, not length. A pool from another projection would zip
    cleanly and produce a plausible, wrong answer."""

    branch = renewal_branch()
    other = build_model_months(analysis_start=date(2028, 1, 1), hold_period=3)

    with pytest.raises(ValueError, match="canonical"):
        recovery_for(branch, branch=RolloverBranchKind.RENEWAL,
                     the_pool=pool(canonical=other))


def test_the_schedule_records_which_branch_chose_the_structure() -> None:
    """Provenance: a reader can see *which* assumption produced this structure,
    which is what the merge-key proof depends on."""

    renewal = renewal_recovery(**modified_gross("renewal"))
    new_tenant = new_tenant_recovery(new_lease_type=LeaseType.GROSS)

    assert renewal.branch is RolloverBranchKind.RENEWAL
    assert renewal.suite_id == "S1"
    assert renewal.successor_lease_id.endswith("renewal")

    assert new_tenant.branch is RolloverBranchKind.NEW_TENANT
    assert new_tenant.successor_lease_id.endswith("new")


def test_the_schedule_is_immutable() -> None:
    result = renewal_recovery()

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.expense_recovery = ()  # type: ignore[misc]


def test_the_recognised_figure_is_reproducible_from_the_disclosed_inputs() -> None:
    """Every number a reader needs is on the schedule: share, stop, factor."""

    result = renewal_recovery(**modified_gross("renewal"))
    stop = result.monthly_expense_stop_dollars

    for share, factor, recognised in zip(
        result.tenant_recoverable_expense_share,
        result.economic_responsibility_factor,
        result.expense_recovery,
        strict=True,
    ):
        rebuilt = factor * max(0.0, share - stop)
        assert recognised.hex() == rebuilt.hex()


def test_recovery_is_zero_before_the_successor_commences() -> None:
    """FM-D3-12. The successor is not responsible for expenses it has not yet
    contracted for, and the series is successor-only."""

    branch = new_tenant_branch(new_downtime_months=3.0)
    result = recovery_for(branch, branch=RolloverBranchKind.NEW_TENANT)

    for index in range(branch.commencement_period - 1):
        assert result.expense_recovery[index] == strict(0.0)
        assert result.economic_responsibility_factor[index] == strict(0.0)


def test_recovery_stops_when_the_successor_expires() -> None:
    """FM-D3-13. A short successor term inside the window leaves later months
    at zero rather than recovering forever."""

    canonical = months(hold_period=5)
    branch = build_new_tenant_branch(
        expiring_lease(),
        suite=suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(new_term_months=12),
    )
    result = recovery_for(
        branch,
        branch=RolloverBranchKind.NEW_TENANT,
        the_pool=pool(canonical=canonical),
    )

    last = branch.successor_expiration_period
    assert result.expense_recovery[last - 1] == strict(30_000.0)
    assert result.expense_recovery[last] == strict(0.0)
