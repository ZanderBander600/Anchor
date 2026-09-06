"""Sprint D Gate D3.2 -- Modified Gross recoveries and the explicit expense stop.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d3-recovery-conventions.md``
Sections 5.0, 5.3, 6.2, 6.3 and 7.1.1, that a `MODIFIED_GROSS` lease reimburses
only the part of its share of the recoverable pool that **exceeds an explicit
contractual expense stop**:

```
monthly_stop_dollars = expense_stop_psf × leased_area_sf / 12
recovery_m           = O_m × max(0, share × P_m − monthly_stop_dollars)
```

The claims that matter most, and the ways each one fails silently:

- **the comparison is dimensionally valid** -- the stop is stated in
  ``$/SF/YEAR`` and converted to the tenant's own monthly dollars *before* the
  subtraction. Subtracting a rate from pool dollars still yields a positive,
  plausible-looking number (FM-D3-18);
- **the responsibility factor sits outside the clip** -- ``O × max(0, share −
  stop)``, never ``max(0, O × share − stop)``. The wrong ordering compares a
  partial month's share against a whole month's stop and under-recovers in
  every fractional month (FM-D3-19). On the reference case the two forms give
  ``$15,000`` and ``$10,000``;
- **the stop is never inferred** -- not from Hold Year 1, the analysis year, the
  acquisition year or the current expense schedule. An unstated stop is refused
  (FM-D3-6);
- **the stop is nominally fixed** -- it never escalates and never resets, which
  is precisely what makes the structure economically interesting: the pool
  grows past a stationary threshold and recoveries emerge (HD-D3-4);
- **below or at the stop, recovery is exactly zero** -- there is no negative
  reimbursement, no landlord credit, no carryforward and no annual true-up;
- **NNN and Gross are untouched** -- proved by float-level identity against the
  D3.1 schedules, not by re-deriving them.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseRecoverySchedule,
    LeaseType,
    RecoverableExpensePool,
    RecoveryBasis,
    build_lease_monthly_schedule,
    build_lease_recovery_schedule,
    build_model_months,
    monthly_expense_recovery,
    monthly_expense_stop_dollars,
    validate_recovery_inputs,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
    require_valid_recovery_inputs,
)


JAN = date(2027, 1, 1)
PROPERTY_AREA = 100_000.0
SUITE_AREA = 20_000.0

#: $12.00/SF/YEAR on 20,000 SF is $20,000 a month -- every golden below is
#: dimensioned against this one figure so a units error is visible by arithmetic
#: rather than by inspection.
STOP_PSF = 12.0
MONTHLY_STOP = 20_000.0

#: A 20% pro-rata share, so a $100,000 pool is exactly the stop.
POOL_AT_STOP = 100_000.0
POOL_BELOW_STOP = 75_000.0
POOL_ABOVE_STOP = 150_000.0


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def months(*, analysis_start: date = JAN, hold_period: int = 2) -> tuple:
    return build_model_months(analysis_start=analysis_start, hold_period=hold_period)


def lease(
    *,
    area: float = SUITE_AREA,
    lease_type: LeaseType = LeaseType.MODIFIED_GROSS,
    stop_psf: float | None = STOP_PSF,
    base_rent_psf: float = 30.0,
    lease_id: str = "L1",
    suite_id: str = "S1",
    start: date = JAN,
    end: date = date(2031, 12, 31),
) -> Lease:
    """A Modified Gross lease with an explicit stop, by default.

    ``stop_psf=None`` produces a lease with **no** contractual basis, which is
    the D3.1 refusal case and stays a refusal at D3.2.
    """

    return Lease(
        lease_id=lease_id,
        suite_id=suite_id,
        tenant_name="Acme Corp",
        leased_area_sf=area,
        rent_commencement_date=start,
        lease_expiration_date=end,
        base_rent_psf=base_rent_psf,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=lease_type,
        recovery_basis=None if stop_psf is None else RecoveryBasis.EXPENSE_STOP_PSF,
        expense_stop_psf=stop_psf,
    )


def pool(
    amount: float = POOL_ABOVE_STOP,
    *,
    canonical: tuple | None = None,
    series: tuple[float, ...] | None = None,
) -> RecoverableExpensePool:
    canonical = canonical if canonical is not None else months()
    expenses = (
        series if series is not None else tuple([amount] * len(canonical))
    )
    return RecoverableExpensePool(months=canonical, recoverable_expenses=expenses)


def recovery(
    the_lease: Lease | None = None,
    *,
    the_pool: RecoverableExpensePool | None = None,
    analysis_start: date = JAN,
    canonical: tuple | None = None,
    rentable_area_sf: float = PROPERTY_AREA,
) -> LeaseRecoverySchedule:
    canonical = (
        canonical if canonical is not None else months(analysis_start=analysis_start)
    )
    the_lease = the_lease if the_lease is not None else lease()
    schedule = build_lease_monthly_schedule(
        the_lease, analysis_start=analysis_start, months=canonical
    )
    return build_lease_recovery_schedule(
        the_lease,
        schedule=schedule,
        pool=the_pool if the_pool is not None else pool(canonical=canonical),
        rentable_area_sf=rentable_area_sf,
    )


def hexes(values: tuple[float, ...]) -> list[str]:
    return [value.hex() for value in values]


# =============================================================================
# The stop conversion -- $/SF/YEAR to monthly tenant dollars
# =============================================================================


@pytest.mark.parametrize(
    ("stop_psf", "area", "expected"),
    [
        (12.0, 20_000.0, 20_000.0),
        (12.0, 10_000.0, 10_000.0),
        (6.0, 20_000.0, 10_000.0),
        (0.0, 20_000.0, 0.0),
        (18.0, 33_333.0, 18.0 * 33_333.0 / 12.0),
        (1.0, 12.0, 1.0),
    ],
)
def test_the_stop_converts_from_psf_per_year_to_monthly_tenant_dollars(
    stop_psf: float, area: float, expected: float
) -> None:
    """``expense_stop_psf × leased_area_sf / 12``. One division by 12, applied
    last -- the same shape D1 uses for ``base_rent_psf``."""

    assert monthly_expense_stop_dollars(
        expense_stop_psf=stop_psf, leased_area_sf=area
    ) == strict(expected)


def test_the_stop_scales_with_the_tenants_own_area_not_the_building() -> None:
    """An expense stop is a tenant-level contract term. Scaling it by rentable
    area would apply the whole property's threshold to a single lease and
    suppress recovery on every suite smaller than the building."""

    tenant_level = monthly_expense_stop_dollars(
        expense_stop_psf=STOP_PSF, leased_area_sf=SUITE_AREA
    )
    building_level = monthly_expense_stop_dollars(
        expense_stop_psf=STOP_PSF, leased_area_sf=PROPERTY_AREA
    )

    assert tenant_level == strict(20_000.0)
    assert building_level == strict(100_000.0)
    assert tenant_level < building_level


# =============================================================================
# GOLDEN 1 -- below the stop
# =============================================================================


def test_golden_1_a_share_below_the_stop_recovers_exactly_zero() -> None:
    """$75,000 pool × 20% = $15,000 against a $20,000 stop. Not a small
    positive number, not a negative one: exactly zero."""

    result = recovery(the_pool=pool(POOL_BELOW_STOP))

    assert result.tenant_recoverable_expense_share[0] == strict(15_000.0)
    assert result.monthly_expense_stop_dollars == strict(MONTHLY_STOP)
    assert result.expense_recovery[0] == strict(0.0)
    assert all(value == 0.0 for value in result.expense_recovery)


def test_golden_1_below_the_stop_is_zero_not_a_landlord_credit() -> None:
    """The shortfall is $5,000 a month. A model that carried it as a negative
    recovery would net it against revenue, and one that accumulated it would be
    modelling a carryforward -- neither is a structure Anchor supports."""

    result = recovery(the_pool=pool(POOL_BELOW_STOP))

    assert all(value >= 0.0 for value in result.expense_recovery)
    assert sum(result.expense_recovery) == strict(0.0)


# =============================================================================
# GOLDEN 2 -- exactly at the stop
# =============================================================================


def test_golden_2_a_share_exactly_at_the_stop_recovers_zero() -> None:
    """The boundary is closed on the zero side: at the stop the tenant owes
    nothing. No tolerance is applied to manufacture a positive figure."""

    result = recovery(the_pool=pool(POOL_AT_STOP))

    assert result.tenant_recoverable_expense_share[0] == strict(MONTHLY_STOP)
    assert result.expense_recovery[0] == strict(0.0)


def test_golden_2_one_dollar_above_the_stop_recovers_one_dollar() -> None:
    """The boundary is not a dead zone. Crossing it by $1 of *pool* recovers
    the tenant's 20% of that dollar."""

    just_above = recovery(the_pool=pool(POOL_AT_STOP + 5.0))

    assert just_above.expense_recovery[0] == strict(1.0)


# =============================================================================
# GOLDEN 3 -- above the stop
# =============================================================================


def test_golden_3_a_share_above_the_stop_recovers_the_excess_only() -> None:
    """$150,000 pool × 20% = $30,000 against a $20,000 stop, so $10,000 -- the
    excess, never the full share."""

    result = recovery(the_pool=pool(POOL_ABOVE_STOP))

    assert result.tenant_recoverable_expense_share[0] == strict(30_000.0)
    assert result.expense_recovery[0] == strict(10_000.0)
    assert all(value == strict(10_000.0) for value in result.expense_recovery)


def test_golden_3_modified_gross_recovers_strictly_less_than_nnn() -> None:
    """The whole economic point of the structure. A rent roll that priced
    Modified Gross as NNN would overstate recovery revenue by the stop on every
    such lease, every month."""

    the_pool = pool(POOL_ABOVE_STOP)
    modified_gross = recovery(lease(), the_pool=the_pool)
    triple_net = recovery(lease(lease_type=LeaseType.NNN, stop_psf=None), the_pool=the_pool)

    assert modified_gross.expense_recovery[0] == strict(10_000.0)
    assert triple_net.expense_recovery[0] == strict(30_000.0)
    assert sum(modified_gross.expense_recovery) < sum(triple_net.expense_recovery)

    # And the difference is exactly the stop, month by month.
    for mg_value, nnn_value in zip(
        modified_gross.expense_recovery, triple_net.expense_recovery, strict=True
    ):
        assert nnn_value - mg_value == strict(MONTHLY_STOP)


# =============================================================================
# GOLDEN 4 -- the dimensional proof
# =============================================================================


def test_golden_4_the_clip_compares_monthly_tenant_dollars_on_both_sides() -> None:
    """Failure mode FM-D3-18, and the reason the conversion exists.

    With a 20,000 SF suite in a 100,000 SF building, a $150,000 monthly pool and
    a $12.00/SF/YEAR stop, the only dimensionally valid comparison is
    ``$30,000`` of tenant share against ``$20,000`` of tenant stop.
    """

    result = recovery(the_pool=pool(POOL_ABOVE_STOP))

    assert result.tenant_pro_rata_share == strict(0.20)
    assert result.tenant_recoverable_expense_share[0] == strict(30_000.0)
    assert result.monthly_expense_stop_dollars == strict(20_000.0)
    assert result.expense_recovery[0] == strict(10_000.0)


def test_golden_4_the_unit_incompatible_forms_are_numerically_excluded() -> None:
    """Each rejected form is *positive and plausible* -- which is exactly why
    the guard has to be arithmetic rather than a reviewer's attention."""

    result = recovery(the_pool=pool(POOL_ABOVE_STOP))
    correct = result.expense_recovery[0]

    # Rejected A: subtract the $/SF rate from the pool, then take the share.
    rate_from_pool = 0.20 * max(0.0, POOL_ABOVE_STOP - STOP_PSF)
    # Rejected B: subtract the $/SF rate from the tenant's share of the pool.
    rate_from_share = max(0.0, 30_000.0 - STOP_PSF)
    # Rejected C: forget the /12, using an annual stop against a monthly share.
    annual_stop = max(0.0, 30_000.0 - STOP_PSF * SUITE_AREA)

    assert correct == strict(10_000.0)
    assert rate_from_pool == strict(29_997.6)
    assert rate_from_share == strict(29_988.0)
    assert annual_stop == strict(0.0)

    for rejected in (rate_from_pool, rate_from_share, annual_stop):
        assert correct != pytest.approx(rejected, rel=0.0, abs=1e-6)


def test_golden_4_the_stop_dollars_track_area_at_a_fixed_rate() -> None:
    """Two suites on the same $/SF stop reach different dollar thresholds, in
    proportion to area. A stop held directly in dollars would not."""

    small = recovery(
        lease(area=10_000.0),
        the_pool=pool(POOL_ABOVE_STOP),
        rentable_area_sf=PROPERTY_AREA,
    )
    large = recovery(
        lease(area=40_000.0),
        the_pool=pool(POOL_ABOVE_STOP),
        rentable_area_sf=PROPERTY_AREA,
    )

    assert small.monthly_expense_stop_dollars == strict(10_000.0)
    assert large.monthly_expense_stop_dollars == strict(40_000.0)

    # 10% of $150,000 is $15,000, above a $10,000 stop -> $5,000.
    assert small.expense_recovery[0] == strict(5_000.0)
    # 40% of $150,000 is $60,000, above a $40,000 stop -> $20,000.
    assert large.expense_recovery[0] == strict(20_000.0)


# =============================================================================
# GOLDEN 5 -- a zero stop
# =============================================================================


def test_golden_5_a_zero_stop_recovers_the_full_tenant_share() -> None:
    """Economically valid, and the degenerate endpoint of the formula: with no
    threshold to clear, a Modified Gross lease recovers from the first dollar."""

    result = recovery(lease(stop_psf=0.0), the_pool=pool(POOL_ABOVE_STOP))

    assert result.monthly_expense_stop_dollars == strict(0.0)
    assert result.expense_recovery[0] == strict(30_000.0)


def test_golden_5_a_zero_stop_is_float_identical_to_nnn() -> None:
    """Identity at the endpoint, at float level -- the D2.5 endpoint idiom.
    Approximate agreement would hide a reordering of the arithmetic."""

    the_pool = pool(POOL_ABOVE_STOP)
    zero_stop = recovery(lease(stop_psf=0.0), the_pool=the_pool)
    triple_net = recovery(lease(lease_type=LeaseType.NNN, stop_psf=None), the_pool=the_pool)

    assert hexes(zero_stop.expense_recovery) == hexes(triple_net.expense_recovery)
    assert hexes(zero_stop.full_month_expense_recovery) == hexes(
        triple_net.full_month_expense_recovery
    )


def test_golden_5_a_zero_stop_lease_is_still_modified_gross() -> None:
    """`lease_type` describes the contract, not the arithmetic that happens to
    coincide. Collapsing the two would lose the audit trail on a term that can
    be renegotiated at rollover."""

    result = recovery(lease(stop_psf=0.0), the_pool=pool(POOL_ABOVE_STOP))

    assert result.lease_type is LeaseType.MODIFIED_GROSS
    assert result.recovery_basis is RecoveryBasis.EXPENSE_STOP_PSF
    assert result.expense_stop_psf == strict(0.0)


# =============================================================================
# GOLDEN 6 -- fractional responsibility, the placement proof
# =============================================================================


def test_golden_6_the_factor_scales_the_obligation_not_the_expense_share() -> None:
    """**The mandatory worked case** (D3 Section 7.1.1, FM-D3-19).

    A $40,000 monthly share against a $20,000 monthly stop at ``O_m = 0.75``:

    ```
    CORRECT  0.75 × max(0, 40,000 − 20,000) = 0.75 × 20,000 = $15,000
    WRONG    max(0, 0.75 × 40,000 − 20,000) =      max(0, 10,000) = $10,000
    ```

    The wrong form charges a partial month's share against a *whole* month's
    stop. It is not a rounding difference -- it is 33% of the figure.
    """

    correct = monthly_expense_recovery(
        lease_type=LeaseType.MODIFIED_GROSS,
        tenant_recoverable_expense_share=40_000.0,
        responsibility_factor=0.75,
        monthly_stop_dollars=20_000.0,
    )
    wrong = max(0.0, 0.75 * 40_000.0 - 20_000.0)

    assert correct == strict(15_000.0)
    assert wrong == strict(10_000.0)
    assert correct != pytest.approx(wrong, rel=0.0, abs=1e-6)


@pytest.mark.parametrize(
    ("factor", "expected"),
    [
        (1.0, 20_000.0),
        (0.75, 15_000.0),
        (0.5, 10_000.0),
        (0.25, 5_000.0),
        (0.0, 0.0),
    ],
)
def test_golden_6_recovery_is_linear_in_the_factor_above_the_stop(
    factor: float, expected: float
) -> None:
    """Above the stop the clip is inactive, so the obligation is a straight
    proportion of the month. The wrong ordering is *not* linear here -- it goes
    to zero at ``O = 0.5`` -- which is what this pins."""

    assert monthly_expense_recovery(
        lease_type=LeaseType.MODIFIED_GROSS,
        tenant_recoverable_expense_share=40_000.0,
        responsibility_factor=factor,
        monthly_stop_dollars=20_000.0,
    ) == strict(expected)


def test_golden_6_a_fractional_factor_never_manufactures_a_recovery() -> None:
    """Below the stop the clip fires first, so no factor -- fractional or
    otherwise -- can produce a positive figure."""

    for factor in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert monthly_expense_recovery(
            lease_type=LeaseType.MODIFIED_GROSS,
            tenant_recoverable_expense_share=15_000.0,
            responsibility_factor=factor,
            monthly_stop_dollars=20_000.0,
        ) == strict(0.0)


def test_golden_6_the_full_month_series_shows_the_ordering() -> None:
    """``full_month_expense_recovery`` is the clip's output *before* the factor,
    so a reader can see which quantity the factor scaled without reconstructing
    it."""

    result = recovery(the_pool=pool(POOL_ABOVE_STOP))

    for full_month, factor, recognised in zip(
        result.full_month_expense_recovery,
        result.economic_responsibility_factor,
        result.expense_recovery,
        strict=True,
    ):
        assert recognised == strict(factor * full_month)


# =============================================================================
# GOLDEN 7 -- a pool that crosses the stop
# =============================================================================


def test_golden_7_each_month_is_clipped_on_its_own() -> None:
    """The clip is per month, with no annual reconciliation. A pool that dips
    below the stop in one month and rises above it in the next recovers zero
    and then the excess -- it does not average, net or true up."""

    canonical = months()
    crossing = (POOL_BELOW_STOP, POOL_AT_STOP, POOL_ABOVE_STOP) + tuple(
        [POOL_ABOVE_STOP] * (len(canonical) - 3)
    )
    result = recovery(the_pool=pool(canonical=canonical, series=crossing))

    assert result.tenant_recoverable_expense_share[:3] == (
        strict(15_000.0),
        strict(20_000.0),
        strict(30_000.0),
    )
    assert result.expense_recovery[:3] == (
        strict(0.0),
        strict(0.0),
        strict(10_000.0),
    )


def test_golden_7_a_shortfall_month_is_not_carried_into_a_surplus_month() -> None:
    """A carryforward would let the $5,000 shortfall of month 1 reduce the
    $10,000 recovery of month 3. Anchor does not model one, so month 3 is
    unaffected by what preceded it."""

    canonical = months()
    crossing = (POOL_BELOW_STOP,) + tuple([POOL_ABOVE_STOP] * (len(canonical) - 1))
    with_shortfall = recovery(the_pool=pool(canonical=canonical, series=crossing))
    without_shortfall = recovery(
        the_pool=pool(canonical=canonical, series=tuple([POOL_ABOVE_STOP] * len(canonical)))
    )

    assert hexes(with_shortfall.expense_recovery[1:]) == hexes(
        without_shortfall.expense_recovery[1:]
    )


# =============================================================================
# GOLDEN 8 -- the stop is nominally fixed
# =============================================================================


def test_golden_8_the_stop_is_one_scalar_for_the_life_of_the_lease() -> None:
    """HD-D3-4. It is a scalar rather than a series precisely so that it cannot
    vary by month; a per-month stop is the shape a resetting stop would need."""

    result = recovery(the_pool=pool(POOL_ABOVE_STOP))

    assert isinstance(result.monthly_expense_stop_dollars, float)
    assert result.monthly_expense_stop_dollars == strict(MONTHLY_STOP)


def test_golden_8_a_growing_pool_meets_a_stationary_stop() -> None:
    """The structure's whole economic content. Over 36 months of 5%-a-year
    expense growth the stop does not move, so recovery emerges and then widens
    -- monotonically, because nothing resets it."""

    canonical = months(hold_period=2)
    growing = tuple(
        POOL_AT_STOP * (1.05 ** (index // 12)) for index in range(len(canonical))
    )
    result = recovery(the_pool=pool(canonical=canonical, series=growing))

    # Year 1 sits exactly at the stop; every later year clears it.
    assert result.expense_recovery[0] == strict(0.0)
    assert result.expense_recovery[11] == strict(0.0)
    assert result.expense_recovery[12] > 0.0
    assert result.expense_recovery[24] > result.expense_recovery[12]

    # Never decreasing, because the threshold is stationary.
    for earlier, later in zip(
        result.expense_recovery, result.expense_recovery[1:], strict=False
    ):
        assert later >= earlier - 1e-9


def test_golden_8_the_stop_does_not_reset_on_a_lease_anniversary() -> None:
    """A resetting stop would zero recovery every twelfth month. Under a
    growing pool the series has no such sawtooth."""

    canonical = months(hold_period=2)
    growing = tuple(
        POOL_ABOVE_STOP * (1.05 ** (index // 12)) for index in range(len(canonical))
    )
    result = recovery(the_pool=pool(canonical=canonical, series=growing))

    for anniversary in (12, 24):
        assert result.expense_recovery[anniversary] > result.expense_recovery[
            anniversary - 1
        ]


def test_golden_8_the_stop_is_independent_of_rent_escalation() -> None:
    """The stop is an expense term. A lease escalating at 3% a year reaches the
    same threshold as one that does not escalate at all."""

    escalating = dataclasses.replace(
        lease(), escalation_pct=0.03, escalation_basis=EscalationBasis.LEASE_ANNIVERSARY
    )
    flat = lease()
    the_pool = pool(POOL_ABOVE_STOP)

    assert hexes(recovery(escalating, the_pool=the_pool).expense_recovery) == hexes(
        recovery(flat, the_pool=the_pool).expense_recovery
    )


# =============================================================================
# GOLDEN 9 -- independence from rent
# =============================================================================


@pytest.mark.parametrize("base_rent_psf", [0.0, 15.0, 30.0, 100.0])
def test_golden_9_recovery_is_independent_of_contractual_rent(
    base_rent_psf: float,
) -> None:
    """FM-D3-2 and FM-D3-3, carried forward from D3.1 into the clipped formula.
    Recovery answers a question about *expenses*; a lease paying $0/SF recovers
    exactly what one paying $100/SF recovers."""

    result = recovery(
        lease(base_rent_psf=base_rent_psf), the_pool=pool(POOL_ABOVE_STOP)
    )

    assert result.expense_recovery[0] == strict(10_000.0)


def test_golden_9_a_zero_rent_modified_gross_lease_still_recovers() -> None:
    """The responsibility factor comes from D1 contractual activity, never from
    rent dollars -- which is what makes D2's free rent safe to connect at D3.4."""

    zero_rent = recovery(lease(base_rent_psf=0.0), the_pool=pool(POOL_ABOVE_STOP))
    market_rent = recovery(lease(base_rent_psf=100.0), the_pool=pool(POOL_ABOVE_STOP))

    assert hexes(zero_rent.expense_recovery) == hexes(market_rent.expense_recovery)
    assert all(factor == 1.0 for factor in zero_rent.economic_responsibility_factor)


# =============================================================================
# GOLDEN 10 -- NNN is unchanged
# =============================================================================


def test_golden_10_nnn_recovers_the_full_share_from_the_first_dollar() -> None:
    """The D3.1 formula, restated so a regression in the shared primitive is
    visible in this file too."""

    result = recovery(
        lease(lease_type=LeaseType.NNN, stop_psf=None), the_pool=pool(POOL_ABOVE_STOP)
    )

    assert result.expense_recovery[0] == strict(30_000.0)
    assert result.monthly_expense_stop_dollars is None
    assert result.recovery_basis is None
    assert result.expense_stop_psf is None


def test_golden_10_an_nnn_lease_refuses_a_stop_rather_than_ignoring_it() -> None:
    """*A stop implies Modified Gross* (D3 Section 5.2). Quietly accepting one
    on an NNN lease would make ``lease_type`` unreliable as an economic
    discriminator, and would silently under-recover if the field were ever
    populated by an abstraction error."""

    with pytest.raises(ValueError, match="MODIFIED_GROSS"):
        monthly_expense_recovery(
            lease_type=LeaseType.NNN,
            tenant_recoverable_expense_share=30_000.0,
            responsibility_factor=1.0,
            monthly_stop_dollars=MONTHLY_STOP,
        )


# =============================================================================
# GOLDEN 11 -- Gross is unchanged
# =============================================================================


def test_golden_11_gross_recovers_nothing_and_carries_no_threshold() -> None:
    """An explicit zero from the lease structure, not a clip that happened to
    fire."""

    result = recovery(
        lease(lease_type=LeaseType.GROSS, stop_psf=None), the_pool=pool(POOL_ABOVE_STOP)
    )

    assert all(value == 0.0 for value in result.expense_recovery)
    assert all(value == 0.0 for value in result.full_month_expense_recovery)
    assert result.monthly_expense_stop_dollars is None


def test_golden_11_gross_is_not_modified_gross_with_an_infinite_stop() -> None:
    """The two produce the same number here and for different reasons. Gross
    recovers nothing because of what its lease says; a huge stop is a Modified
    Gross lease that happens to be under water this month."""

    gross = recovery(
        lease(lease_type=LeaseType.GROSS, stop_psf=None), the_pool=pool(POOL_ABOVE_STOP)
    )
    huge_stop = recovery(lease(stop_psf=1_000.0), the_pool=pool(POOL_ABOVE_STOP))

    assert hexes(gross.expense_recovery) == hexes(huge_stop.expense_recovery)
    assert gross.lease_type is LeaseType.GROSS
    assert huge_stop.lease_type is LeaseType.MODIFIED_GROSS
    assert gross.recovery_basis is None
    assert huge_stop.recovery_basis is RecoveryBasis.EXPENSE_STOP_PSF


def test_golden_11_a_gross_lease_refuses_a_stop_rather_than_ignoring_it() -> None:
    with pytest.raises(ValueError, match="MODIFIED_GROSS"):
        monthly_expense_recovery(
            lease_type=LeaseType.GROSS,
            tenant_recoverable_expense_share=30_000.0,
            responsibility_factor=1.0,
            monthly_stop_dollars=MONTHLY_STOP,
        )


# =============================================================================
# GOLDEN 12 -- a missing basis is refused, never inferred
# =============================================================================


def test_golden_12_a_modified_gross_lease_without_a_basis_is_refused() -> None:
    """FM-D3-6, and the D3.1 refusal preserved. Anchor never infers a stop --
    not from Hold Year 1, the analysis year, the acquisition year or the current
    expense schedule. Each would silently rewrite a contract term on every
    Modified Gross lease in a rent roll."""

    with pytest.raises(ValueError, match="MODIFIED_GROSS"):
        monthly_expense_recovery(
            lease_type=LeaseType.MODIFIED_GROSS,
            tenant_recoverable_expense_share=30_000.0,
            responsibility_factor=1.0,
        )

    with pytest.raises(ValueError):
        recovery(lease(stop_psf=None), the_pool=pool(POOL_ABOVE_STOP))


def test_golden_12_the_refusal_message_names_what_is_missing() -> None:
    """An operator has to be able to act on it: the fix is to abstract the
    lease's stop, not to change a setting."""

    with pytest.raises(ValueError, match="explicit"):
        monthly_expense_recovery(
            lease_type=LeaseType.MODIFIED_GROSS,
            tenant_recoverable_expense_share=30_000.0,
            responsibility_factor=1.0,
        )


def test_golden_12_validation_reports_the_missing_basis_as_an_error() -> None:
    result = validate_recovery_inputs([lease(stop_psf=None)], pool(POOL_ABOVE_STOP))

    assert not result.is_valid
    issue = next(
        issue
        for issue in result.issues
        if issue.code is LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS
    )
    assert issue.severity is LeaseIssueSeverity.ERROR

    with pytest.raises(LeaseValidationError):
        require_valid_recovery_inputs([lease(stop_psf=None)], pool(POOL_ABOVE_STOP))


def test_golden_12_a_basis_without_a_stop_is_refused() -> None:
    """Half-stated is not stated. A basis naming ``EXPENSE_STOP_PSF`` with no
    rate behind it is the shape a partially-abstracted rent roll produces."""

    half_stated = dataclasses.replace(lease(), expense_stop_psf=None)
    result = validate_recovery_inputs([half_stated], pool(POOL_ABOVE_STOP))

    assert not result.is_valid
    assert LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS in [
        issue.code for issue in result.issues
    ]


# =============================================================================
# GOLDEN 13 -- the stop's domain
# =============================================================================


def test_golden_13_a_negative_stop_is_an_error() -> None:
    """A negative stop is a recovery *floor* -- a structure in which the tenant
    reimburses more than its share. Anchor does not model one, so it is refused
    rather than clipped to zero."""

    result = validate_recovery_inputs([lease(stop_psf=-1.0)], pool(POOL_ABOVE_STOP))

    assert not result.is_valid
    issue = next(
        issue
        for issue in result.issues
        if issue.code is LeaseIssueCode.EXPENSE_STOP_OUT_OF_DOMAIN
    )
    assert issue.severity is LeaseIssueSeverity.ERROR


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), float("-inf")])
def test_golden_13_the_arithmetic_refuses_a_stop_outside_the_domain(
    bad: float,
) -> None:
    with pytest.raises(ValueError):
        monthly_expense_stop_dollars(expense_stop_psf=bad, leased_area_sf=SUITE_AREA)


def test_golden_13_a_zero_stop_is_inside_the_domain() -> None:
    """The domain is ``>= 0``, not ``> 0`` -- a zero stop is an ordinary
    negotiated outcome, not a data error."""

    result = validate_recovery_inputs([lease(stop_psf=0.0)], pool(POOL_ABOVE_STOP))

    assert result.is_valid


def test_golden_13_a_stop_on_a_non_modified_gross_lease_is_an_error() -> None:
    """Reported at validation as well as refused by the arithmetic, so a rent
    roll is rejected before any figure is produced from it."""

    for lease_type in (LeaseType.NNN, LeaseType.GROSS):
        result = validate_recovery_inputs(
            [lease(lease_type=lease_type, stop_psf=STOP_PSF)], pool(POOL_ABOVE_STOP)
        )

        assert not result.is_valid
        assert LeaseIssueCode.RECOVERY_BASIS_ON_NON_MODIFIED_GROSS in [
            issue.code for issue in result.issues
        ]


# =============================================================================
# GOLDEN 14 -- partial-year and boundary responsibility
# =============================================================================


def test_golden_14_a_lease_expiring_mid_horizon_recovers_only_while_active() -> None:
    """The factor is D1 contractual activity. After expiry the lease owes
    nothing, and the stop does not keep it owing."""

    expiring = lease(start=JAN, end=date(2027, 6, 30))
    result = recovery(expiring, the_pool=pool(POOL_ABOVE_STOP))

    assert result.expense_recovery[5] == strict(10_000.0)
    assert result.expense_recovery[6] == strict(0.0)
    assert result.economic_responsibility_factor[6] == strict(0.0)


def test_golden_14_a_lease_commencing_mid_horizon_recovers_only_once_active() -> None:
    late = lease(start=date(2027, 4, 1))
    result = recovery(late, the_pool=pool(POOL_ABOVE_STOP))

    assert result.expense_recovery[2] == strict(0.0)
    assert result.expense_recovery[3] == strict(10_000.0)


def test_golden_14_the_stop_is_stated_before_the_factor_is_known() -> None:
    """The scalar stop is a property of the contract, so it is identical on two
    leases with different activity windows. Only the recognised figure differs."""

    full_term = recovery(lease(), the_pool=pool(POOL_ABOVE_STOP))
    part_term = recovery(
        lease(end=date(2027, 6, 30)), the_pool=pool(POOL_ABOVE_STOP)
    )

    assert full_term.monthly_expense_stop_dollars == strict(
        part_term.monthly_expense_stop_dollars
    )
    assert hexes(full_term.full_month_expense_recovery) == hexes(
        part_term.full_month_expense_recovery
    )
    assert hexes(full_term.expense_recovery) != hexes(part_term.expense_recovery)


# =============================================================================
# GOLDEN 15 -- the forward exit window
# =============================================================================


def test_golden_15_the_schedule_spans_the_full_canonical_timeline() -> None:
    """``12H + 12``. Recovery is defined over the forward exit window too, so a
    D4 exit-value calculation never has to extrapolate one."""

    canonical = months(hold_period=5)
    result = recovery(
        the_pool=pool(canonical=canonical), canonical=canonical
    )

    assert len(canonical) == 5 * 12 + 12
    assert result.months == canonical
    assert len(result.expense_recovery) == len(canonical)
    assert len(result.full_month_expense_recovery) == len(canonical)


def test_golden_15_the_clip_applies_in_the_forward_window_too() -> None:
    """The forward window is not a special case with a suspended stop. The
    lease runs past month 72 so the factor stays 1.0 and the only thing being
    measured is the clip."""

    canonical = months(hold_period=5)
    long_lease = lease(end=date(2035, 12, 31))
    result = recovery(
        long_lease,
        the_pool=pool(canonical=canonical, series=tuple([POOL_ABOVE_STOP] * len(canonical))),
        canonical=canonical,
    )

    assert result.economic_responsibility_factor[-1] == strict(1.0)
    assert result.expense_recovery[-1] == strict(10_000.0)
    assert result.monthly_expense_stop_dollars == strict(MONTHLY_STOP)


def test_golden_15_the_stop_has_not_drifted_by_the_end_of_the_window() -> None:
    """Seventy-two months in, the threshold is the one the lease stated -- so a
    pool sitting exactly at the stop recovers nothing in month 72 just as it did
    in month 1. A stop that had drifted in either direction would show here."""

    canonical = months(hold_period=5)
    long_lease = lease(end=date(2035, 12, 31))
    at_stop = recovery(
        long_lease,
        the_pool=pool(canonical=canonical, series=tuple([POOL_AT_STOP] * len(canonical))),
        canonical=canonical,
    )

    assert all(factor == 1.0 for factor in at_stop.economic_responsibility_factor)
    assert all(value == strict(0.0) for value in at_stop.expense_recovery)

    # And one dollar of pool above the stop still recovers in the final month,
    # which is what separates "unchanged" from "switched off".
    just_above = recovery(
        long_lease,
        the_pool=pool(
            canonical=canonical, series=tuple([POOL_AT_STOP + 5.0] * len(canonical))
        ),
        canonical=canonical,
    )
    assert just_above.expense_recovery[-1] == strict(1.0)


# =============================================================================
# The audit surface
# =============================================================================


def test_the_schedule_exposes_the_threshold_that_actually_applied() -> None:
    """Four fields, each answering a distinct question, so a Modified Gross
    figure is auditable without reconstructing a hidden assumption."""

    result = recovery(the_pool=pool(POOL_ABOVE_STOP))

    assert result.recovery_basis is RecoveryBasis.EXPENSE_STOP_PSF
    assert result.expense_stop_psf == strict(STOP_PSF)
    assert result.monthly_expense_stop_dollars == strict(MONTHLY_STOP)
    assert result.full_month_expense_recovery[0] == strict(10_000.0)


def test_the_schedule_series_are_all_aligned_to_the_canonical_months() -> None:
    canonical = months(hold_period=3)
    result = recovery(the_pool=pool(canonical=canonical), canonical=canonical)

    for series in (
        result.economic_responsibility_factor,
        result.tenant_recoverable_expense_share,
        result.full_month_expense_recovery,
        result.expense_recovery,
    ):
        assert len(series) == len(canonical)


def test_the_recognised_figure_is_reproducible_from_the_disclosed_inputs() -> None:
    """Every number a reader needs is on the schedule: share, stop, factor. The
    recognised figure follows from them and nothing else."""

    result = recovery(the_pool=pool(POOL_ABOVE_STOP))

    for share, factor, recognised in zip(
        result.tenant_recoverable_expense_share,
        result.economic_responsibility_factor,
        result.expense_recovery,
        strict=True,
    ):
        rebuilt = factor * max(0.0, share - result.monthly_expense_stop_dollars)
        assert recognised.hex() == rebuilt.hex()


def test_the_schedule_requires_every_d3_2_field_to_be_stated() -> None:
    """None of the four D3.2 fields carries a default, so no call site can
    build a schedule that silently omits the threshold that applied.

    This is a *structural* guard rather than a behavioural one: today's builder
    always passes all four, so a default would be unobservable in any figure.
    It becomes load-bearing at D3.3 and D3.4, where successor and expected
    schedules are constructed from new call sites -- a defaulted
    ``monthly_expense_stop_dollars`` would let one of them report ``None``
    ("no threshold applied") for a lease whose recovery had in fact been
    clipped.
    """

    required = {
        f.name
        for f in dataclasses.fields(LeaseRecoverySchedule)
        if f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING
    }

    for field in (
        "recovery_basis",
        "expense_stop_psf",
        "monthly_expense_stop_dollars",
        "full_month_expense_recovery",
    ):
        assert field in required, (
            f"{field} has a default; every D3.2 field must be stated "
            "explicitly by whoever builds a recovery schedule"
        )


def test_the_schedule_is_immutable() -> None:
    result = recovery(the_pool=pool(POOL_ABOVE_STOP))

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.monthly_expense_stop_dollars = 0.0  # type: ignore[misc]


# =============================================================================
# Adversarial
# =============================================================================


def test_a_stop_larger_than_the_whole_pool_recovers_zero_not_a_negative() -> None:
    result = recovery(lease(stop_psf=10_000.0), the_pool=pool(POOL_ABOVE_STOP))

    assert all(value == 0.0 for value in result.expense_recovery)


def test_a_vacant_suites_share_of_the_pool_stays_unrecovered() -> None:
    """The disclosed no-gross-up consequence, unchanged by the stop: the
    remaining 80% of the pool is not redistributed to this tenant."""

    result = recovery(the_pool=pool(POOL_ABOVE_STOP), rentable_area_sf=PROPERTY_AREA)

    assert result.tenant_pro_rata_share == strict(0.20)
    assert result.tenant_recoverable_expense_share[0] == strict(30_000.0)


def test_a_zero_pool_recovers_zero_under_a_positive_stop() -> None:
    result = recovery(the_pool=pool(0.0))

    assert all(value == 0.0 for value in result.expense_recovery)


def test_a_zero_pool_recovers_zero_under_a_zero_stop() -> None:
    """Both terms of the clip are zero. The result is zero rather than a
    NaN-producing degenerate case."""

    result = recovery(lease(stop_psf=0.0), the_pool=pool(0.0))

    assert all(value == 0.0 for value in result.expense_recovery)


def test_an_unsupported_lease_type_is_refused_by_the_arithmetic() -> None:
    with pytest.raises(ValueError, match="unsupported lease type"):
        monthly_expense_recovery(
            lease_type="triple_net_plus",  # type: ignore[arg-type]
            tenant_recoverable_expense_share=30_000.0,
            responsibility_factor=1.0,
            monthly_stop_dollars=MONTHLY_STOP,
        )


def test_a_non_finite_stop_never_reaches_the_clip() -> None:
    with pytest.raises(ValueError):
        monthly_expense_recovery(
            lease_type=LeaseType.MODIFIED_GROSS,
            tenant_recoverable_expense_share=30_000.0,
            responsibility_factor=1.0,
            monthly_stop_dollars=float("nan"),
        )


def test_a_factor_outside_zero_to_one_is_refused() -> None:
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError):
            monthly_expense_recovery(
                lease_type=LeaseType.MODIFIED_GROSS,
                tenant_recoverable_expense_share=30_000.0,
                responsibility_factor=bad,
                monthly_stop_dollars=MONTHLY_STOP,
            )


def test_a_zero_area_lease_cannot_produce_a_stop() -> None:
    """A zero-area suite has no threshold to state; dividing by it or returning
    zero would both be wrong, so the conversion refuses."""

    with pytest.raises(ValueError):
        monthly_expense_stop_dollars(expense_stop_psf=STOP_PSF, leased_area_sf=0.0)


def test_the_recovery_basis_enum_has_exactly_one_member() -> None:
    """An extension seam, not an invitation. A base-year member is reserved for
    the day a rent roll forces it *and* the history it needs can be sourced."""

    assert [member.value for member in RecoveryBasis] == ["expense_stop_psf"]
    assert RecoveryBasis.EXPENSE_STOP_PSF.value == "expense_stop_psf"


def test_an_unsupported_recovery_basis_is_reported_not_silently_priced() -> None:
    """The seam refuses forward. If a second member is ever added without the
    arithmetic to price it, this is what stops it becoming a wrong number."""

    assert hasattr(LeaseIssueCode, "UNSUPPORTED_RECOVERY_BASIS")


def test_modified_gross_remains_valid_input_to_d1_and_d2_validation() -> None:
    """D3.2 prices the structure; it does not restrict what D1 and D2 accept.
    A Modified Gross lease with no stop is still a legitimate D1 rent roll."""

    from anchor.leasing import LeaseLevelPropertyInputs, Suite
    from anchor.leasing.validation import validate_lease_level_inputs

    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(analysis_start_date=JAN, rentable_area_sf=SUITE_AREA),
        [Suite(suite_id="S1", suite_area_sf=SUITE_AREA)],
        [lease(area=SUITE_AREA, stop_psf=None)],
    )

    assert result.is_valid
