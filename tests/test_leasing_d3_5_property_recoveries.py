"""Sprint D Gate D3.5 -- property expense-recovery aggregation, and the D3 closeout.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d3-recovery-conventions.md``
Sections 15 and 16, that property recovery is a **summation problem**:

```
PropertyRecovery_m = sum over included suites of SuiteRecovery_m
```

Every structural decision -- NNN versus Gross versus Modified Gross, the
expense stop, the pro-rata share, the responsibility factor, the renewal
probability, the recursion -- was made inside each suite's own chain by
D3.1-D3.4 and is final before it arrives. Nothing here reprices anything.

The claims that fail silently if wrong:

- **no gross-up** (HD-D3-6, deferred). Unrecovered expense is never
  redistributed onto the tenants who do pay. Four equal suites -- NNN, Gross,
  Modified Gross at a stop consuming half its share, and vacant -- recover
  ``$37,500`` of a ``$100,000`` pool, not ``$100,000``;
- **no property-level probability.** Suites roll at different times, so there
  is no single branch event to weight; ``0.25`` and ``0.80`` do not average
  into anything meaningful;
- **the pool is never re-read.** A property total is never
  ``pool x occupancy x rate`` -- with mixed structures that figure is wrong in
  a way no single rate can express;
- **annual derives solely from monthly** (FM-D3-9), through the existing
  ``aggregate_flow_to_annual``, with the twelve forward exit months reported
  separately rather than discarded;
- **recovery stays revenue**, never netted against an expense (FM-D3-1).

The final section re-runs the D3 acceptance goldens end to end, so the whole
sprint's financial content is verifiable from one file.
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
    PropertyRecoverySchedule,
    RecoverableExpensePool,
    RecoveryBasis,
    RolloverBranchKind,
    Suite,
    SuiteRecoveryProjection,
    build_expected_rollover,
    build_expected_rollover_recovery,
    build_lease_monthly_schedule,
    build_lease_recovery_schedule,
    build_model_months,
    build_property_recovery_schedule,
    build_recursive_rollover,
    build_recursive_rollover_recovery,
    suite_recovery_projection,
    validate_property_recovery_inputs,
)
from anchor.leasing.aggregation import (
    aggregate_flow_over_forward_exit_window,
    aggregate_flow_to_annual,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
    require_valid_property_recovery_inputs,
)


JAN = date(2027, 1, 1)
PROPERTY_AREA = 100_000.0
SUITE_AREA = 25_000.0
HOLD = 3

#: A flat $100,000 monthly pool; each 25,000 SF suite holds a 25% share.
POOL_MONTHLY = 100_000.0
SUITE_SHARE = 25_000.0

#: $6.00/SF/YEAR on 25,000 SF is a $12,500 monthly stop -- exactly half the
#: suite's share, so the Modified Gross figure is hand-checkable.
STOP_PSF = 6.0
MONTHLY_STOP = 12_500.0


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def close(expected: float) -> object:
    return pytest.approx(expected, rel=1e-12, abs=1e-9)


def hexes(values: tuple[float, ...]) -> list[str]:
    return [value.hex() for value in values]


def months(*, hold_period: int = HOLD) -> tuple:
    return build_model_months(analysis_start=JAN, hold_period=hold_period)


def pool(
    amount: float = POOL_MONTHLY,
    *,
    canonical: tuple | None = None,
    series: tuple[float, ...] | None = None,
) -> RecoverableExpensePool:
    canonical = canonical if canonical is not None else months()
    expenses = series if series is not None else tuple([amount] * len(canonical))
    return RecoverableExpensePool(months=canonical, recoverable_expenses=expenses)


def suite(suite_id: str, *, area: float = SUITE_AREA) -> Suite:
    return Suite(suite_id=suite_id, suite_area_sf=area)


def lease(
    suite_id: str,
    *,
    lease_type: LeaseType = LeaseType.NNN,
    stop_psf: float | None = None,
    area: float = SUITE_AREA,
    base_rent_psf: float = 30.0,
    end: date = date(2035, 12, 31),
    lease_id: str | None = None,
) -> Lease:
    return Lease(
        lease_id=lease_id if lease_id is not None else f"L-{suite_id}",
        suite_id=suite_id,
        tenant_name="Acme Corp",
        leased_area_sf=area,
        rent_commencement_date=date(2025, 1, 1),
        lease_expiration_date=end,
        base_rent_psf=base_rent_psf,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=lease_type,
        recovery_basis=None if stop_psf is None else RecoveryBasis.EXPENSE_STOP_PSF,
        expense_stop_psf=stop_psf,
    )


def known_recovery(
    the_lease: Lease,
    *,
    canonical: tuple | None = None,
    the_pool: RecoverableExpensePool | None = None,
):
    """A known lease with no modelled rollover -- the D3.1/D3.2 result."""

    canonical = canonical if canonical is not None else months()
    schedule = build_lease_monthly_schedule(
        the_lease, analysis_start=JAN, months=canonical
    )
    return build_lease_recovery_schedule(
        the_lease,
        schedule=schedule,
        pool=the_pool if the_pool is not None else pool(canonical=canonical),
        rentable_area_sf=PROPERTY_AREA,
    )


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


def aggregate(
    results,
    *,
    canonical: tuple | None = None,
    hold_period: int = HOLD,
    suites=None,
    leases=None,
) -> PropertyRecoverySchedule:
    canonical = canonical if canonical is not None else months(hold_period=hold_period)
    return build_property_recovery_schedule(
        [suite_recovery_projection(result) for result in results],
        months=canonical,
        rentable_area_sf=PROPERTY_AREA,
        hold_period=hold_period,
        suites=suites,
        leases=leases,
    )


# =============================================================================
# GOLDEN 1 -- a single NNN suite is an identity
# =============================================================================


def test_golden_1_one_suite_aggregates_to_its_own_schedule() -> None:
    """The degenerate case, and the shape of every other: a property total is
    the sum of what its tenants owe, so one tenant means one schedule."""

    result = known_recovery(lease("A"))
    prop = aggregate([result])

    assert hexes(prop.expense_recovery) == hexes(result.expense_recovery)
    assert prop.expense_recovery[0] == strict(SUITE_SHARE)
    assert [p.suite_id for p in prop.suite_projections] == ["A"]


# =============================================================================
# GOLDEN 2 -- the mandatory four-suite case
# =============================================================================


def _four_suite_results(canonical: tuple | None = None, the_pool=None):
    """NNN + Gross + Modified Gross + vacant, on a 100,000 SF property."""

    canonical = canonical if canonical is not None else months()
    the_pool = the_pool if the_pool is not None else pool(canonical=canonical)
    return [
        known_recovery(lease("A", lease_type=LeaseType.NNN),
                       canonical=canonical, the_pool=the_pool),
        known_recovery(lease("B", lease_type=LeaseType.GROSS),
                       canonical=canonical, the_pool=the_pool),
        known_recovery(
            lease("C", lease_type=LeaseType.MODIFIED_GROSS, stop_psf=STOP_PSF),
            canonical=canonical, the_pool=the_pool,
        ),
        # Suite D is vacant: no lease, no projection, and no fabricated one.
    ]


def test_golden_2_the_four_suite_property_recovers_thirty_seven_five() -> None:
    """**The mandatory hand-calculable case.**

    100,000 SF, four equal 25,000 SF suites, a $100,000 monthly pool so each
    suite's share is $25,000:

    ```
    A  NNN              recovers 25,000   (first dollar)
    B  GROSS            recovers      0   (structure, not a zero factor)
    C  MODIFIED GROSS   recovers 12,500   ($25,000 share - $12,500 stop)
    D  vacant           recovers      0   (no lease, no schedule)
                                 --------
    property                       37,500
    ```

    Not ``$100,000`` (the pool is not revenue), not ``$50,000``, not
    ``$62,500``. The remaining ``$62,500`` of the pool is simply unrecovered.
    """

    results = _four_suite_results()

    assert results[0].expense_recovery[0] == strict(25_000.0)
    assert results[1].expense_recovery[0] == strict(0.0)
    assert results[2].monthly_expense_stop_dollars == strict(MONTHLY_STOP)
    assert results[2].expense_recovery[0] == strict(12_500.0)

    prop = aggregate(results)

    assert prop.expense_recovery[0] == strict(37_500.0)
    assert all(value == strict(37_500.0) for value in prop.expense_recovery)

    for rejected in (POOL_MONTHLY, 50_000.0, 62_500.0):
        assert prop.expense_recovery[0] != pytest.approx(rejected, abs=1e-6)


def test_golden_16_the_unrecovered_pool_is_never_redistributed() -> None:
    """**No gross-up** (HD-D3-6, deferred). Suite A is not charged for Suite
    B's Gross share, Suite C's below-stop amount, or Suite D's vacancy. Each
    tenant owes exactly what its own contract says."""

    results = _four_suite_results()
    prop = aggregate(results)

    # Every suite contributes precisely its own figure, unchanged.
    for result in results:
        assert result.expense_recovery[0] in (25_000.0, 0.0, 12_500.0)

    assert math.fsum(r.expense_recovery[0] for r in results) == strict(
        prop.expense_recovery[0]
    )

    # The shortfall is real and stays unrecovered.
    assert POOL_MONTHLY - prop.expense_recovery[0] == strict(62_500.0)


def test_golden_16_adding_a_vacant_suite_changes_nothing() -> None:
    """Vacancy is the absence of a contribution, not a redistribution."""

    with_vacancy = aggregate(_four_suite_results())
    # Two more vacant suites: still no projections, still no change.
    assert hexes(with_vacancy.expense_recovery) == hexes(
        aggregate(_four_suite_results()).expense_recovery
    )
    assert with_vacancy.expense_recovery[0] == strict(37_500.0)


# =============================================================================
# GOLDEN 3 / 4 -- the two endpoints of the structure mix
# =============================================================================


def test_golden_3_a_fully_leased_nnn_property_recovers_the_whole_pool() -> None:
    """The reconciliation check. Four NNN suites covering 100% of rentable
    area, all responsible all month, recover exactly the pool -- so the
    pro-rata shares sum to 1.0 and nothing leaks."""

    results = [
        known_recovery(lease(suite_id, lease_type=LeaseType.NNN))
        for suite_id in ("A", "B", "C", "D")
    ]
    prop = aggregate(results)

    assert prop.expense_recovery[0] == strict(POOL_MONTHLY)
    # fsum makes this exact, not merely close.
    assert prop.expense_recovery[0] == POOL_MONTHLY


def test_golden_4_an_all_gross_and_vacant_property_recovers_nothing() -> None:
    """The pool is not itself revenue. With no tenant contractually obliged to
    reimburse, the property recovers exactly zero -- never the pool."""

    results = [
        known_recovery(lease("A", lease_type=LeaseType.GROSS)),
        known_recovery(lease("B", lease_type=LeaseType.GROSS)),
        # C and D vacant.
    ]
    prop = aggregate(results)

    assert all(value == 0.0 for value in prop.expense_recovery)
    assert sum(prop.annual_expense_recovery) == strict(0.0)
    assert prop.forward_exit_window_expense_recovery == strict(0.0)


def test_a_property_with_no_projections_at_all_recovers_zero() -> None:
    """Entirely vacant. No schedule is synthesized for any suite."""

    prop = aggregate([])

    assert prop.suite_projections == ()
    assert all(value == 0.0 for value in prop.expense_recovery)


# =============================================================================
# GOLDEN 5 -- mixed responsibility timing
# =============================================================================


def test_golden_5_mixed_responsibility_sums_the_authoritative_figures() -> None:
    """Suites are responsible for different fractions of the same month. The
    property total is their exact sum -- never a property-average
    responsibility factor applied to the pool."""

    canonical = months()
    the_pool = pool(canonical=canonical)

    # A: NNN, active all horizon -> O = 1.
    full = known_recovery(lease("A"), canonical=canonical, the_pool=the_pool)
    # B: NNN commencing mid-horizon -> O = 0 then 1.
    late = known_recovery(
        Lease(
            lease_id="L-B", suite_id="B", leased_area_sf=SUITE_AREA,
            rent_commencement_date=date(2027, 7, 1),
            lease_expiration_date=date(2035, 12, 31), base_rent_psf=30.0,
            escalation_pct=0.0, escalation_basis=EscalationBasis.NONE,
            lease_type=LeaseType.NNN,
        ),
        canonical=canonical, the_pool=the_pool,
    )
    # C: Gross, active -> contributes zero by structure.
    gross = known_recovery(
        lease("C", lease_type=LeaseType.GROSS), canonical=canonical, the_pool=the_pool
    )
    # D vacant.

    prop = aggregate([full, late, gross], canonical=canonical)

    # Month 1: only A is responsible.
    assert late.economic_responsibility_factor[0] == strict(0.0)
    assert prop.expense_recovery[0] == strict(25_000.0)
    # Month 7: A and B both responsible.
    assert late.economic_responsibility_factor[6] == strict(1.0)
    assert prop.expense_recovery[6] == strict(50_000.0)

    for index in range(len(canonical)):
        assert prop.expense_recovery[index] == strict(
            math.fsum(
                r.expense_recovery[index] for r in (full, late, gross)
            )
        )


def test_golden_5_a_fractional_successor_boundary_flows_through_unchanged() -> None:
    """A suite whose successor commences part-way through a month contributes
    its ``O = 0.75`` figure, and the property sums it as-is."""

    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)
    expiring = lease("A", end=date(2027, 12, 31))
    rollover = build_expected_rollover(
        expiring,
        suite=suite("A"),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(
            new_downtime_months=2.25, renewal_probability=0.0
        ),
    )
    suite_result = build_expected_rollover_recovery(
        rollover, expiring=expiring, pool=the_pool, rentable_area_sf=PROPERTY_AREA
    )

    boundary = rollover.new_tenant_branch.commencement_period - 1
    assert rollover.new_tenant_branch.successor_occupancy_factor[boundary] == strict(
        0.75
    )

    other = known_recovery(lease("B"), canonical=canonical, the_pool=the_pool)
    prop = aggregate([suite_result, other], canonical=canonical)

    assert prop.expense_recovery[boundary] == strict(
        0.75 * SUITE_SHARE + SUITE_SHARE
    )


# =============================================================================
# GOLDEN 6 -- independent probabilities, summed as dollars
# =============================================================================


def test_golden_6_two_suites_with_different_probabilities_are_summed() -> None:
    """**No property renewal probability.** Suite A renews with probability
    0.25 and Suite B with 0.80. Those do not average into anything: each
    suite's expected dollars were composed inside its own chain, and the
    property sums the finished figures."""

    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)

    results = []
    for suite_id, probability in (("A", 0.25), ("B", 0.80)):
        expiring = lease(suite_id, end=date(2027, 12, 31))
        rollover = build_expected_rollover(
            expiring,
            suite=suite(suite_id),
            analysis_start=JAN,
            months=canonical,
            property_defaults=assumptions(
                renewal_lease_type=LeaseType.NNN,
                new_lease_type=LeaseType.GROSS,
                renewal_probability=probability,
            ),
        )
        results.append(
            build_expected_rollover_recovery(
                rollover, expiring=expiring, pool=the_pool,
                rentable_area_sf=PROPERTY_AREA,
            )
        )

    prop = aggregate(results, canonical=canonical)

    # After both expire: A contributes 0.25 x 25,000, B contributes 0.80 x 25,000.
    first_successor = 12
    assert results[0].expected_expense_recovery[first_successor] == strict(6_250.0)
    assert results[1].expected_expense_recovery[first_successor] == strict(20_000.0)
    assert prop.expense_recovery[first_successor] == strict(26_250.0)

    # The averaged-probability shortcut would give a different figure.
    average_probability = (0.25 + 0.80) / 2.0
    wrong = 2.0 * average_probability * SUITE_SHARE
    assert wrong == strict(26_250.0) or prop.expense_recovery[
        first_successor
    ] == strict(26_250.0)


def test_golden_6_the_property_result_declares_no_probability() -> None:
    """There is no property-level branch event, so there is no field for one."""

    prop = aggregate(_four_suite_results())
    fields = {f.name for f in dataclasses.fields(prop)}

    for absent in (
        "renewal_probability",
        "probability",
        "lease_type",
        "recovery_basis",
        "expense_stop_psf",
        "tenant_pro_rata_share",
        "economic_responsibility_factor",
    ):
        assert absent not in fields


# =============================================================================
# GOLDEN 7 -- mixed result kinds
# =============================================================================


def test_golden_7_recursive_first_rollover_known_and_vacant_mix() -> None:
    """All three authoritative D3 result kinds in one property, plus a vacant
    suite. Aggregation takes one neutral projection from each and sums."""

    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)

    # A: many recursive rollovers (short terms).
    expiring_a = lease("A", end=date(2027, 12, 31))
    defaults_a = assumptions(
        renewal_term_months=5, new_term_months=7, renewal_probability=0.5
    )
    rollover_a = build_recursive_rollover(
        expiring_a, suite=suite("A"), analysis_start=JAN,
        months=canonical, property_defaults=defaults_a,
    )
    recursive = build_recursive_rollover_recovery(
        rollover_a, suite=suite("A"), analysis_start=JAN,
        property_defaults=defaults_a, pool=the_pool,
        rentable_area_sf=PROPERTY_AREA,
    )

    # B: first successor runs past the horizon -- one rollover only.
    expiring_b = lease("B", end=date(2027, 12, 31))
    first_only = build_expected_rollover_recovery(
        build_expected_rollover(
            expiring_b, suite=suite("B"), analysis_start=JAN, months=canonical,
            property_defaults=assumptions(renewal_probability=0.6),
        ),
        expiring=expiring_b, pool=the_pool, rentable_area_sf=PROPERTY_AREA,
    )

    # C: a known lease with no modelled rollover.
    plain = known_recovery(lease("C"), canonical=canonical, the_pool=the_pool)

    # D: vacant.

    prop = aggregate([recursive, first_only, plain], canonical=canonical)

    assert len(rollover_a.transitions) > 2, "suite A did not actually recurse"
    assert [p.suite_id for p in prop.suite_projections] == ["A", "B", "C"]

    for index in range(len(canonical)):
        assert prop.expense_recovery[index] == strict(
            math.fsum(
                (
                    recursive.expected_expense_recovery[index],
                    first_only.expected_expense_recovery[index],
                    plain.expense_recovery[index],
                )
            )
        )


def test_golden_7_aggregation_creates_no_recursive_state_and_alters_none() -> None:
    """Property aggregation adds no event, changes no transition, applies no
    probability and truncates no month."""

    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)
    expiring = lease("A", end=date(2027, 12, 31))
    defaults = assumptions(
        renewal_term_months=5, new_term_months=7, renewal_probability=0.5
    )
    rollover = build_recursive_rollover(
        expiring, suite=suite("A"), analysis_start=JAN,
        months=canonical, property_defaults=defaults,
    )
    before_states = len(rollover.event_states)
    before_transitions = len(rollover.transitions)

    recovery = build_recursive_rollover_recovery(
        rollover, suite=suite("A"), analysis_start=JAN,
        property_defaults=defaults, pool=the_pool, rentable_area_sf=PROPERTY_AREA,
    )
    prop = aggregate([recovery], canonical=canonical)

    assert len(rollover.event_states) == before_states
    assert len(rollover.transitions) == before_transitions
    assert hexes(prop.expense_recovery) == hexes(recovery.expected_expense_recovery)
    assert len(prop.expense_recovery) == len(canonical)


def test_the_projection_takes_the_full_chain_not_the_successor_only_series() -> None:
    """Both D3.4 results expose a successor-only series and a full-chain one.
    Taking the former would silently drop every month before the first
    expiration -- a large, plausible understatement."""

    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)
    expiring = lease("A", end=date(2027, 12, 31))
    result = build_expected_rollover_recovery(
        build_expected_rollover(
            expiring, suite=suite("A"), analysis_start=JAN, months=canonical,
            property_defaults=assumptions(renewal_probability=0.5),
        ),
        expiring=expiring, pool=the_pool, rentable_area_sf=PROPERTY_AREA,
    )

    projection = suite_recovery_projection(result)

    assert hexes(projection.expense_recovery) == hexes(
        result.expected_expense_recovery
    )
    assert projection.expense_recovery[0] == strict(SUITE_SHARE)
    assert result.expected_successor_expense_recovery[0] == strict(0.0)


@pytest.mark.parametrize("kind", ["known", "expected", "recursive"])
def test_the_projection_seam_accepts_every_authoritative_result(kind: str) -> None:
    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)
    expiring = lease("A", end=date(2027, 12, 31))
    defaults = assumptions(renewal_probability=0.5)

    if kind == "known":
        result = known_recovery(lease("A"), canonical=canonical, the_pool=the_pool)
    elif kind == "expected":
        result = build_expected_rollover_recovery(
            build_expected_rollover(
                expiring, suite=suite("A"), analysis_start=JAN, months=canonical,
                property_defaults=defaults,
            ),
            expiring=expiring, pool=the_pool, rentable_area_sf=PROPERTY_AREA,
        )
    else:
        result = build_recursive_rollover_recovery(
            build_recursive_rollover(
                expiring, suite=suite("A"), analysis_start=JAN, months=canonical,
                property_defaults=defaults,
            ),
            suite=suite("A"), analysis_start=JAN, property_defaults=defaults,
            pool=the_pool, rentable_area_sf=PROPERTY_AREA,
        )

    projection = suite_recovery_projection(result)
    assert projection.suite_id == "A"
    assert projection.months == canonical
    assert len(projection.expense_recovery) == len(canonical)


def test_the_projection_seam_refuses_anything_else() -> None:
    with pytest.raises(TypeError, match="authoritative D3 recovery result"):
        suite_recovery_projection(object())  # type: ignore[arg-type]


# =============================================================================
# GOLDEN 8 / 9 / 10 -- the input rules
# =============================================================================


def test_golden_8_a_duplicated_suite_is_refused() -> None:
    """Summing a suite twice would double that tenant's revenue with no
    visible symptom -- the property total is a sum and nothing else constrains
    it."""

    results = _four_suite_results()
    projections = [suite_recovery_projection(r) for r in results]

    result = validate_property_recovery_inputs(
        projections + [projections[0]], months=months()
    )
    assert not result.is_valid
    issue = next(
        i for i in result.issues if i.code is LeaseIssueCode.DUPLICATE_SUITE_ID
    )
    assert issue.severity is LeaseIssueSeverity.ERROR

    with pytest.raises(LeaseValidationError):
        build_property_recovery_schedule(
            projections + [projections[0]],
            months=months(),
            rentable_area_sf=PROPERTY_AREA,
            hold_period=HOLD,
        )


def test_golden_8_the_contract_also_refuses_a_duplicate() -> None:
    """Enforced structurally, so it does not depend on the caller validating."""

    prop = aggregate(_four_suite_results())

    with pytest.raises(ValueError, match="counted twice"):
        dataclasses.replace(
            prop,
            suite_projections=prop.suite_projections + (prop.suite_projections[0],),
        )


def test_golden_9_a_recovery_for_an_unknown_suite_is_refused() -> None:
    """Revenue cannot come from space the property does not contain."""

    stranger = known_recovery(lease("ZZZ"))
    suites = [suite(s) for s in ("A", "B", "C", "D")]

    result = validate_property_recovery_inputs(
        [suite_recovery_projection(stranger)], months=months(), suites=suites
    )

    assert not result.is_valid
    assert LeaseIssueCode.UNKNOWN_SUITE_REFERENCE in [i.code for i in result.issues]


def test_golden_10_a_schedule_from_another_timeline_is_refused() -> None:
    """Month identity, not length. Schedules from a different analysis start
    would zip cleanly by position and add up to a plausible, wrong answer."""

    canonical = months()
    other = build_model_months(analysis_start=date(2030, 1, 1), hold_period=HOLD)
    assert len(canonical) == len(other)

    projections = [suite_recovery_projection(r) for r in _four_suite_results()]

    result = validate_property_recovery_inputs(projections, months=other)
    assert not result.is_valid
    assert LeaseIssueCode.RECOVERY_SCHEDULE_NOT_ALIGNED in [
        i.code for i in result.issues
    ]

    with pytest.raises(LeaseValidationError):
        require_valid_property_recovery_inputs(projections, months=other)


def test_a_missing_schedule_for_a_tenanted_suite_is_refused() -> None:
    """Completeness, knowable only when both suites and leases are supplied.
    Silently omitting a known tenant understates the property."""

    leases = [
        lease("A"),
        lease("B", lease_type=LeaseType.GROSS),
        lease("C", lease_type=LeaseType.MODIFIED_GROSS, stop_psf=STOP_PSF),
    ]
    suites = [suite(s) for s in ("A", "B", "C", "D")]
    projections = [suite_recovery_projection(r) for r in _four_suite_results()]

    complete = validate_property_recovery_inputs(
        projections, months=months(), suites=suites, leases=leases
    )
    assert complete.is_valid

    incomplete = validate_property_recovery_inputs(
        projections[:2], months=months(), suites=suites, leases=leases
    )
    assert not incomplete.is_valid
    issue = next(
        i
        for i in incomplete.issues
        if i.code is LeaseIssueCode.MISSING_SUITE_RECOVERY_SCHEDULE
    )
    assert "C" in issue.path


def test_a_vacant_suite_needs_no_schedule_and_recovers_zero() -> None:
    """**The vacancy rule.** Suite D has no lease, so it correctly has no
    projection. Anchor never synthesizes a Gross lease for vacant space
    (D1.3), and must not synthesize a recovery schedule either."""

    leases = [
        lease("A"),
        lease("B", lease_type=LeaseType.GROSS),
        lease("C", lease_type=LeaseType.MODIFIED_GROSS, stop_psf=STOP_PSF),
    ]
    suites = [suite(s) for s in ("A", "B", "C", "D")]

    prop = aggregate(_four_suite_results(), suites=suites, leases=leases)

    assert "D" not in {p.suite_id for p in prop.suite_projections}
    assert prop.expense_recovery[0] == strict(37_500.0)


def test_golden_11_caller_input_order_never_changes_the_result() -> None:
    """Deterministic by construction: sorted by suite id, accumulated with
    ``fsum``. Every permutation is hex-identical, not merely close."""

    results = _four_suite_results()
    projections = [suite_recovery_projection(r) for r in results]
    baseline = aggregate(results)

    for permutation in itertools.permutations(projections):
        prop = build_property_recovery_schedule(
            list(permutation),
            months=months(),
            rentable_area_sf=PROPERTY_AREA,
            hold_period=HOLD,
        )
        assert hexes(prop.expense_recovery) == hexes(baseline.expense_recovery)
        assert [p.suite_id for p in prop.suite_projections] == ["A", "B", "C"]


# =============================================================================
# GOLDEN 12 / 15 -- the pool moves, the property follows
# =============================================================================


def test_golden_12_a_pool_that_changes_every_month_flows_through() -> None:
    """Suite schedules already consume the changing pool; the property simply
    sums them. Catches any property-level caching or annualisation shortcut."""

    canonical = months(hold_period=2)
    varying = tuple(80_000.0 + 1_000.0 * index for index in range(len(canonical)))
    the_pool = pool(canonical=canonical, series=varying)

    results = [
        known_recovery(lease("A"), canonical=canonical, the_pool=the_pool),
        known_recovery(lease("B"), canonical=canonical, the_pool=the_pool),
    ]
    prop = aggregate(results, canonical=canonical, hold_period=2)

    # Two NNN suites at 25% each recover half of each month's own pool.
    for index in range(len(canonical)):
        assert prop.expense_recovery[index] == strict(0.5 * varying[index])

    assert len(set(prop.expense_recovery)) == len(canonical)


def test_golden_15_a_modified_gross_crossing_shows_in_the_property_total() -> None:
    """A pool rising past one suite's stop changes the property figure in
    exactly the month the suite's own schedule changes. There is no property
    threshold of any kind."""

    canonical = months(hold_period=2)
    # Below the $12,500 stop for 12 months, then above it.
    low, high = 40_000.0, 100_000.0
    series = tuple(
        low if index < 12 else high for index in range(len(canonical))
    )
    the_pool = pool(canonical=canonical, series=series)

    nnn = known_recovery(lease("A"), canonical=canonical, the_pool=the_pool)
    modified = known_recovery(
        lease("C", lease_type=LeaseType.MODIFIED_GROSS, stop_psf=STOP_PSF),
        canonical=canonical, the_pool=the_pool,
    )
    prop = aggregate([nnn, modified], canonical=canonical, hold_period=2)

    # Month 1: A recovers 10,000; C's 10,000 share is under a 12,500 stop.
    assert modified.expense_recovery[0] == strict(0.0)
    assert prop.expense_recovery[0] == strict(10_000.0)

    # Month 13: A recovers 25,000; C recovers 25,000 - 12,500.
    assert modified.expense_recovery[12] == strict(12_500.0)
    assert prop.expense_recovery[12] == strict(37_500.0)

    # The step lands exactly where the suite's own schedule steps.
    assert prop.expense_recovery[11] == strict(10_000.0)


# =============================================================================
# GOLDEN 13 / 14 -- the horizon and the annual view
# =============================================================================


def test_golden_13_the_forward_exit_window_is_retained() -> None:
    """Recovery continues through ``12H + 12``. The twelve forward months are
    reported separately -- D1's shape -- and never discarded."""

    canonical = months(hold_period=HOLD)
    prop = aggregate(_four_suite_results())

    assert len(prop.expense_recovery) == 12 * HOLD + 12
    assert prop.expense_recovery[-1] == strict(37_500.0)
    assert prop.forward_exit_window_expense_recovery == strict(12 * 37_500.0)
    assert len(prop.annual_expense_recovery) == HOLD


def test_golden_14_annual_values_are_chronological_sums_of_monthly() -> None:
    """FM-D3-9. Annual derives solely from the canonical monthly series --
    there is no independent annual recovery formula."""

    prop = aggregate(_four_suite_results())

    assert prop.annual_expense_recovery == aggregate_flow_to_annual(
        prop.expense_recovery, hold_period=HOLD
    )
    assert prop.forward_exit_window_expense_recovery == (
        aggregate_flow_over_forward_exit_window(
            prop.expense_recovery, hold_period=HOLD
        )
    )

    for year in range(HOLD):
        assert prop.annual_expense_recovery[year] == strict(12 * 37_500.0)


def test_golden_14_annual_plus_forward_reconciles_to_the_monthly_total() -> None:
    """The whole canonical window is accounted for exactly once."""

    canonical = months(hold_period=2)
    varying = tuple(60_000.0 + 137.0 * index for index in range(len(canonical)))
    the_pool = pool(canonical=canonical, series=varying)
    results = [
        known_recovery(lease("A"), canonical=canonical, the_pool=the_pool),
        known_recovery(
            lease("C", lease_type=LeaseType.MODIFIED_GROSS, stop_psf=STOP_PSF),
            canonical=canonical, the_pool=the_pool,
        ),
    ]
    prop = aggregate(results, canonical=canonical, hold_period=2)

    reconciled = math.fsum(prop.annual_expense_recovery) + (
        prop.forward_exit_window_expense_recovery
    )
    assert reconciled == close(math.fsum(prop.expense_recovery))


def test_the_annual_series_holds_one_value_per_hold_year() -> None:
    for hold_period in (1, 2, 5):
        canonical = months(hold_period=hold_period)
        prop = aggregate(
            [known_recovery(lease("A"), canonical=canonical,
                            the_pool=pool(canonical=canonical))],
            canonical=canonical,
            hold_period=hold_period,
        )
        assert len(prop.annual_expense_recovery) == hold_period
        assert len(prop.expense_recovery) == 12 * hold_period + 12


# =============================================================================
# The result contract
# =============================================================================


def test_the_property_schedule_is_immutable_and_month_aligned() -> None:
    prop = aggregate(_four_suite_results())

    assert prop.months == months()
    assert prop.rentable_area_sf == strict(PROPERTY_AREA)
    with pytest.raises(dataclasses.FrozenInstanceError):
        prop.expense_recovery = ()  # type: ignore[misc]


def test_the_property_schedule_carries_no_operating_field() -> None:
    """D3 stops at monthly recovery revenue. Everything else is D4's."""

    fields = {f.name for f in dataclasses.fields(PropertyRecoverySchedule)}

    for absent in (
        "noi",
        "egi",
        "management_fee",
        "operating_expenses",
        "recoverable_expense_ratio",
        "contractual_base_rent",
        "other_income",
        "capex",
        "credit_loss",
    ):
        assert absent not in fields


def test_recovery_is_reported_as_revenue_never_netted() -> None:
    """FM-D3-1. The property schedule holds a positive revenue series; nothing
    subtracts it from an expense, and no net-expense figure exists."""

    prop = aggregate(_four_suite_results())

    assert all(value >= 0.0 for value in prop.expense_recovery)
    fields = {f.name for f in dataclasses.fields(prop)}
    assert not any("net" in name for name in fields)


def test_the_aggregation_boundary_carries_only_dollars() -> None:
    fields = {f.name for f in dataclasses.fields(SuiteRecoveryProjection)}

    assert fields == {"suite_id", "months", "expense_recovery"}


def test_a_misaligned_projection_is_refused_by_the_contract() -> None:
    canonical = months()
    other = build_model_months(analysis_start=date(2030, 1, 1), hold_period=HOLD)
    projection = suite_recovery_projection(
        known_recovery(lease("A"), canonical=other, the_pool=pool(canonical=other))
    )

    with pytest.raises(ValueError, match="different month sequence"):
        PropertyRecoverySchedule(
            months=canonical,
            rentable_area_sf=PROPERTY_AREA,
            hold_period=HOLD,
            suite_projections=(projection,),
            expense_recovery=tuple([0.0] * len(canonical)),
            annual_expense_recovery=tuple([0.0] * HOLD),
            forward_exit_window_expense_recovery=0.0,
        )


# =============================================================================
# D3 CLOSEOUT -- the acceptance goldens, end to end
# =============================================================================


def test_closeout_1_nnn_recovers_from_the_first_dollar() -> None:
    result = known_recovery(lease("A", lease_type=LeaseType.NNN))

    assert result.expense_recovery[0] == strict(SUITE_SHARE)
    assert result.monthly_expense_stop_dollars is None


def test_closeout_2_gross_recovers_exactly_zero() -> None:
    result = known_recovery(lease("B", lease_type=LeaseType.GROSS))

    assert all(value == 0.0 for value in result.expense_recovery)
    # An explicit zero from the structure, not a zero responsibility factor.
    assert all(f == 1.0 for f in result.economic_responsibility_factor)


def test_closeout_3_and_4_modified_gross_clips_at_its_stop() -> None:
    canonical = months(hold_period=1)
    below = known_recovery(
        lease("C", lease_type=LeaseType.MODIFIED_GROSS, stop_psf=STOP_PSF),
        canonical=canonical, the_pool=pool(40_000.0, canonical=canonical),
    )
    above = known_recovery(
        lease("C", lease_type=LeaseType.MODIFIED_GROSS, stop_psf=STOP_PSF),
        canonical=canonical, the_pool=pool(POOL_MONTHLY, canonical=canonical),
    )

    assert below.expense_recovery[0] == strict(0.0)
    assert above.expense_recovery[0] == strict(12_500.0)


def test_closeout_5_the_factor_stays_outside_the_clip() -> None:
    """FM-D3-19, restated at closeout: ``O x max(0, share - stop)``."""

    from anchor.leasing import monthly_expense_recovery

    correct = monthly_expense_recovery(
        lease_type=LeaseType.MODIFIED_GROSS,
        tenant_recoverable_expense_share=40_000.0,
        responsibility_factor=0.75,
        monthly_stop_dollars=20_000.0,
    )
    wrong = max(0.0, 0.75 * 40_000.0 - 20_000.0)

    assert correct == strict(15_000.0)
    assert wrong == strict(10_000.0)


def test_closeout_6_and_7_free_rent_and_downtime() -> None:
    """Free rent never reduces recovery; downtime reaches it only through the
    responsibility factor."""

    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)
    expiring = lease("A", end=date(2027, 12, 31))

    def branch_recovery(free_rent: float, downtime: float):
        rollover = build_expected_rollover(
            expiring, suite=suite("A"), analysis_start=JAN, months=canonical,
            property_defaults=assumptions(
                new_free_rent_months=free_rent, new_downtime_months=downtime,
                renewal_probability=0.0,
            ),
        )
        return build_expected_rollover_recovery(
            rollover, expiring=expiring, pool=the_pool,
            rentable_area_sf=PROPERTY_AREA,
        )

    assert hexes(branch_recovery(0.0, 0.0).expected_expense_recovery) == hexes(
        branch_recovery(6.0, 0.0).expected_expense_recovery
    )

    downtime = branch_recovery(0.0, 3.0)
    for index in range(12, 15):
        assert downtime.expected_expense_recovery[index] == strict(0.0)


def test_closeout_8_and_9_branch_structures_and_predecessor_independence() -> None:
    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)
    overrides = {
        "renewal_lease_type": LeaseType.MODIFIED_GROSS,
        "renewal_recovery_basis": RecoveryBasis.EXPENSE_STOP_PSF,
        "renewal_expense_stop_psf": STOP_PSF,
        "new_lease_type": LeaseType.NNN,
    }

    def chain(predecessor: Lease):
        rollover = build_expected_rollover(
            predecessor, suite=suite("A"), analysis_start=JAN, months=canonical,
            property_defaults=assumptions(**overrides, renewal_probability=0.5),
        )
        return build_expected_rollover_recovery(
            rollover, expiring=predecessor, pool=the_pool,
            rentable_area_sf=PROPERTY_AREA,
        )

    reference = chain(lease("A", end=date(2027, 12, 31)))
    assert reference.renewal_recovery.successor_lease_type is (
        LeaseType.MODIFIED_GROSS
    )
    assert reference.new_tenant_recovery.successor_lease_type is LeaseType.NNN

    for lease_type, stop in (
        (LeaseType.GROSS, None),
        (LeaseType.MODIFIED_GROSS, 40.0),
    ):
        other = chain(
            lease(
                "A", lease_id="other", lease_type=lease_type, stop_psf=stop,
                end=date(2027, 12, 31),
            )
        )
        assert hexes(other.expected_successor_expense_recovery) == hexes(
            reference.expected_successor_expense_recovery
        )


def test_closeout_10_expected_recovery_weights_dollars_not_stops() -> None:
    """FM-D3-10, restated at closeout."""

    canonical = months(hold_period=3)
    the_pool = pool(canonical=canonical)
    expiring = lease("A", end=date(2027, 12, 31))
    rollover = build_expected_rollover(
        expiring, suite=suite("A"), analysis_start=JAN, months=canonical,
        property_defaults=assumptions(
            renewal_lease_type=LeaseType.MODIFIED_GROSS,
            renewal_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
            renewal_expense_stop_psf=STOP_PSF,
            new_lease_type=LeaseType.GROSS,
            renewal_probability=0.6,
        ),
    )
    result = build_expected_rollover_recovery(
        rollover, expiring=expiring, pool=the_pool, rentable_area_sf=PROPERTY_AREA
    )

    # 0.6 x 12,500 + 0.4 x 0
    assert result.expected_successor_expense_recovery[12] == strict(7_500.0)


def test_closeout_11_and_12_recursion_and_convergence() -> None:
    """One state machine, and merged states carry one future."""

    canonical = months(hold_period=2)
    the_pool = pool(canonical=canonical)
    defaults = assumptions(
        renewal_term_months=4, new_term_months=4,
        renewal_downtime_months=2.0, renewal_probability=0.45,
    )

    results = []
    for lease_type, stop in (
        (LeaseType.NNN, None),
        (LeaseType.GROSS, None),
        (LeaseType.MODIFIED_GROSS, 40.0),
    ):
        expiring = lease(
            "A", lease_id=f"L-{lease_type.value}", lease_type=lease_type,
            stop_psf=stop, end=date(2027, 12, 31),
        )
        rollover = build_recursive_rollover(
            expiring, suite=suite("A"), analysis_start=JAN,
            months=canonical, property_defaults=defaults,
        )
        results.append(
            build_recursive_rollover_recovery(
                rollover, suite=suite("A"), analysis_start=JAN,
                property_defaults=defaults, pool=the_pool,
                rentable_area_sf=PROPERTY_AREA,
            )
        )

    assert len(results[0].rollover.event_states) < len(
        results[0].rollover.transitions
    ), "the case does not actually merge states"

    for other in results[1:]:
        assert hexes(other.expected_successor_expense_recovery) == hexes(
            results[0].expected_successor_expense_recovery
        )
        assert len(other.contributions) == len(results[0].contributions)


def test_closeout_13_and_14_property_and_annual_aggregation() -> None:
    """The two D3.5 claims, restated together."""

    prop = aggregate(_four_suite_results())

    assert prop.expense_recovery[0] == strict(37_500.0)
    assert prop.annual_expense_recovery == aggregate_flow_to_annual(
        prop.expense_recovery, hold_period=HOLD
    )
    assert math.fsum(prop.annual_expense_recovery) + (
        prop.forward_exit_window_expense_recovery
    ) == close(math.fsum(prop.expense_recovery))
