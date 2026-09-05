"""Sprint D Gate D1.2 -- the contractual base-rent monthly timeline.

Proves, per
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 6.1, 6.2 and Gate D1.2, that one validated lease produces its exact
canonical monthly base rent.

The financial claims that matter most:

- rent follows the lease's TRUE contractual chronology; acquisition never
  resets the escalation clock (Golden 2B, 7, 8 -- failure mode FM-5);
- the commencement month and the expiration month are both paid
  (Goldens 3, 4 -- failure mode FM-10);
- expiration stops rent dead: nothing carries forward, renews, or reaches for
  a market rent.

Every expected value below is hand-calculable from the Section 6.1 formula
alone.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.engine.contracts import NonFiniteResultError
from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseMonthlySchedule,
    LeaseType,
    build_lease_monthly_schedule,
    build_model_months,
)
from anchor.leasing.rent import (
    escalation_period_index,
    lease_rent_periods,
    monthly_base_rent,
)


AREA = 12_000.0


def strict(expected: float) -> object:
    """The tolerance convention of ``tests/test_engine_golden_case.py``:
    tight enough to reject presentation-scale rounding, loose enough for
    ordinary IEEE-754 last-bit noise."""

    return pytest.approx(expected, rel=0.0, abs=1e-9)


def lease(**overrides: object) -> Lease:
    fields: dict[str, object] = {
        "lease_id": "L1",
        "suite_id": "S1",
        "leased_area_sf": AREA,
        "rent_commencement_date": date(2027, 1, 1),
        "lease_expiration_date": date(2032, 12, 31),
        "base_rent_psf": 24.0,
        "escalation_pct": 0.0,
        "escalation_basis": EscalationBasis.NONE,
        "lease_type": LeaseType.NNN,
    }
    fields.update(overrides)
    return Lease(**fields)  # type: ignore[arg-type]


def schedule_for(
    the_lease: Lease,
    *,
    analysis_start: date = date(2027, 1, 1),
    hold_period: int = 1,
) -> LeaseMonthlySchedule:
    return build_lease_monthly_schedule(
        the_lease,
        analysis_start=analysis_start,
        months=build_model_months(
            analysis_start=analysis_start, hold_period=hold_period
        ),
    )


def rent_at(schedule: LeaseMonthlySchedule, period: int) -> float:
    """Look a month's rent up by canonical period index, never by raw
    position -- the tie the schedule's ``months`` field exists to make."""

    for month, amount in zip(schedule.months, schedule.contractual_base_rent):
        if month.period_index == period:
            return amount
    raise AssertionError(f"period {period} is not in this schedule")


# =============================================================================
# Contract shape
# =============================================================================


def test_schedule_is_immutable_and_value_equal() -> None:
    first = schedule_for(lease())
    second = schedule_for(lease())

    assert first == second
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.lease_id = "L2"  # type: ignore[misc]


def test_schedule_declares_only_the_delivered_fields() -> None:
    """D2/D3's free rent, recoveries, TI, LC and ``occupancy_factor`` are not
    declared: a gate declares only what it can actually produce.

    ``occupied_area`` joined at D1.3, when property aggregation gave it a
    consumer.
    """

    declared = {f.name for f in dataclasses.fields(LeaseMonthlySchedule)}

    assert declared == {
        "lease_id",
        "suite_id",
        "months",
        "contractual_base_rent",
        "occupied_area",
        "first_rent_period",
        "last_rent_period",
    }
    assert not declared & {
        "free_rent",
        "expense_recoveries",
        "tenant_improvements",
        "leasing_commissions",
        "occupancy_factor",
    }


def test_rent_is_aligned_one_to_one_with_the_canonical_months() -> None:
    schedule = schedule_for(lease())

    assert len(schedule.contractual_base_rent) == len(schedule.months)
    assert [m.period_index for m in schedule.months] == list(range(1, 25))


def test_a_length_mismatch_is_rejected_at_construction() -> None:
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=1)

    with pytest.raises(ValueError, match="contractual_base_rent"):
        LeaseMonthlySchedule(
            lease_id="L1",
            suite_id="S1",
            months=months,
            contractual_base_rent=(1.0,),
            occupied_area=(0.0,) * len(months),
            first_rent_period=1,
            last_rent_period=1,
        )

    with pytest.raises(ValueError, match="occupied_area"):
        LeaseMonthlySchedule(
            lease_id="L1",
            suite_id="S1",
            months=months,
            contractual_base_rent=(0.0,) * len(months),
            occupied_area=(1.0,),
            first_rent_period=1,
            last_rent_period=1,
        )


def test_the_builder_mutates_nothing() -> None:
    original = lease(rent_commencement_date=date(2024, 1, 1))
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=1)

    build_lease_monthly_schedule(
        original, analysis_start=date(2027, 1, 1), months=months
    )

    assert original == lease(rent_commencement_date=date(2024, 1, 1))
    assert months == build_model_months(
        analysis_start=date(2027, 1, 1), hold_period=1
    )


def test_repeated_builds_are_value_equal() -> None:
    first = schedule_for(lease(escalation_pct=0.05, escalation_basis=EscalationBasis.LEASE_ANNIVERSARY))

    for _ in range(50):
        assert (
            schedule_for(
                lease(
                    escalation_pct=0.05,
                    escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
                )
            )
            == first
        )


# =============================================================================
# GOLDEN 1 -- flat in-place lease
# =============================================================================


def test_golden_1_flat_in_place_lease() -> None:
    """analysis 2027-01-01, H=1; 12,000 SF; commenced 2026-01-01; expires
    2028-12-31; $24.00/SF/yr flat.

        24.00 * 12,000 / 12 = 24,000.00 every active month
    """

    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2026, 1, 1),
            lease_expiration_date=date(2028, 12, 31),
            base_rent_psf=24.0,
            escalation_basis=EscalationBasis.NONE,
            escalation_pct=0.0,
        )
    )

    assert len(schedule.contractual_base_rent) == 24
    for amount in schedule.contractual_base_rent:
        assert amount == strict(24_000.0)

    assert schedule.first_rent_period == 1
    assert schedule.last_rent_period == 24


def test_golden_1_value_is_exactly_representable() -> None:
    """24 * 12000 / 12 is exact in binary floating point, so this is an
    equality, not an approximation."""

    schedule = schedule_for(
        lease(rent_commencement_date=date(2026, 1, 1), base_rent_psf=24.0)
    )

    assert schedule.contractual_base_rent[0] == 24_000.0


# =============================================================================
# GOLDEN 2 -- annual escalation
# =============================================================================


def test_golden_2_annual_escalation() -> None:
    """12,000 SF; commences 2027-01-01 (= analysis start); $24.00; 5%.

        months  1-12   k=0   24.00    -> 24,000.00
        months 13-24   k=1   25.20    -> 25,200.00
    """

    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2027, 1, 1),
            base_rent_psf=24.0,
            escalation_pct=0.05,
            escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        )
    )

    for period in range(1, 13):
        assert rent_at(schedule, period) == strict(24_000.0), f"period {period}"
    for period in range(13, 25):
        assert rent_at(schedule, period) == strict(25_200.0), f"period {period}"


def test_golden_2_escalates_on_the_anniversary_month_not_before() -> None:
    schedule = schedule_for(
        lease(
            base_rent_psf=24.0,
            escalation_pct=0.05,
            escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        )
    )

    assert rent_at(schedule, 12) == strict(24_000.0)   # Dec-2027, still step 0
    assert rent_at(schedule, 13) == strict(25_200.0)   # Jan-2028, step 1


# =============================================================================
# GOLDEN 2B -- acquisition does not reset escalation  (FM-5, critical)
# =============================================================================


def test_golden_2b_acquisition_does_not_reset_the_escalation_clock() -> None:
    """Lease commenced 2025-04-01 at $30.00/SF/yr with 3% anniversary steps.
    Anchor acquires 2027-01-01, nearly two contract years in.

        raw first_rent_period = month_index(2025-04-01) = -20
        k(Jan-2027) = floor((1 - (-20)) / 12) = floor(21/12) = 1
        k(Apr-2027) = floor((4 - (-20)) / 12) = floor(24/12) = 2

        Jan-Mar 2027   30.00 * 1.03   = 30.900   -> 30,900.00
        Apr-2027 on    30.00 * 1.03^2 = 31.827   -> 31,827.00

    The lease must NOT restart at $30.00 just because the deal closed.
    """

    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2025, 4, 1),
            base_rent_psf=30.0,
            escalation_pct=0.03,
            escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        )
    )

    for period in (1, 2, 3):
        assert rent_at(schedule, period) == strict(30_900.0), f"period {period}"

    for period in range(4, 16):
        assert rent_at(schedule, period) == strict(31_827.0), f"period {period}"

    # Never the un-escalated original rent.
    assert 30_000.0 not in schedule.contractual_base_rent

    # Next contractual anniversary: Apr-2028, model month 16.
    assert rent_at(schedule, 16) == strict(32_781.81)


def test_golden_2b_escalation_index_is_measured_from_raw_commencement() -> None:
    the_lease = lease(
        rent_commencement_date=date(2025, 4, 1),
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        escalation_pct=0.03,
    )
    raw_first, _ = lease_rent_periods(the_lease, analysis_start=date(2027, 1, 1))

    assert raw_first == -20
    assert escalation_period_index(
        period=1, raw_first_rent_period=raw_first, basis=EscalationBasis.LEASE_ANNIVERSARY
    ) == 1
    assert escalation_period_index(
        period=4, raw_first_rent_period=raw_first, basis=EscalationBasis.LEASE_ANNIVERSARY
    ) == 2


# =============================================================================
# GOLDEN 3 -- mid-horizon expiration
# =============================================================================


def test_golden_3_expiration_month_is_paid_and_rent_then_stops() -> None:
    """Expires 2027-06-30 = model month 6 (inclusive)."""

    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2026, 1, 1),
            lease_expiration_date=date(2027, 6, 30),
            base_rent_psf=24.0,
        )
    )

    for period in range(1, 7):
        assert rent_at(schedule, period) == strict(24_000.0), f"period {period}"
    for period in range(7, 25):
        assert rent_at(schedule, period) == 0.0, f"period {period}"

    assert schedule.last_rent_period == 6


def test_golden_3_rent_is_never_carried_past_expiration() -> None:
    """Expiration stops rent: no carry-forward, no renewal, no month-to-month,
    no market rent, no successor."""

    schedule = schedule_for(
        lease(
            lease_expiration_date=date(2027, 6, 30),
            escalation_pct=0.05,
            escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        )
    )

    assert set(schedule.contractual_base_rent[6:]) == {0.0}


# =============================================================================
# GOLDEN 4 -- future commencement
# =============================================================================


def test_golden_4_commencement_month_is_paid_and_earlier_months_are_zero() -> None:
    """Commences 2027-04-01 = model month 4."""

    schedule = schedule_for(
        lease(rent_commencement_date=date(2027, 4, 1), base_rent_psf=24.0)
    )

    for period in (1, 2, 3):
        assert rent_at(schedule, period) == 0.0, f"period {period}"
    for period in range(4, 25):
        assert rent_at(schedule, period) == strict(24_000.0), f"period {period}"

    assert schedule.first_rent_period == 4


def test_golden_4_pre_commencement_zero_is_not_vacancy_or_free_rent() -> None:
    """The zero means only that contractual rent has not commenced. D1 has no
    vacancy, downtime or free-rent concept to confuse it with -- none of those
    fields exists on the schedule."""

    schedule = schedule_for(lease(rent_commencement_date=date(2027, 4, 1)))
    declared = {f.name for f in dataclasses.fields(LeaseMonthlySchedule)}

    assert schedule.contractual_base_rent[0] == 0.0
    assert not declared & {"free_rent", "occupancy_factor", "downtime"}


# =============================================================================
# GOLDEN 5 -- negative escalation
# =============================================================================


def test_golden_5_negative_escalation_reduces_rent_on_each_anniversary() -> None:
    """-2% is mathematically valid (D1.0 permits ``escalation_pct > -1``).

        k=0   24.00                 -> 24,000.00
        k=1   24.00 * 0.98 = 23.52  -> 23,520.00
        k=2   24.00 * 0.98^2        -> 23,049.60
    """

    schedule = schedule_for(
        lease(
            base_rent_psf=24.0,
            escalation_pct=-0.02,
            escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        ),
        hold_period=2,
    )

    assert rent_at(schedule, 1) == strict(24_000.0)
    assert rent_at(schedule, 13) == strict(23_520.0)
    assert rent_at(schedule, 25) == strict(23_049.6)


# =============================================================================
# GOLDEN 6 -- zero rent
# =============================================================================


def test_golden_6_a_zero_rent_lease_is_active_with_exactly_zero_rent() -> None:
    """A zero-rent lease still occupies its suite contractually. Zero rent is
    never reinterpreted as vacancy -- occupancy is separate state that D1.3
    derives."""

    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2027, 4, 1),
            lease_expiration_date=date(2027, 9, 30),
            base_rent_psf=0.0,
        )
    )

    assert set(schedule.contractual_base_rent) == {0.0}
    # Active periods are reported from contractual activity, not from a
    # non-zero figure.
    assert schedule.first_rent_period == 4
    assert schedule.last_rent_period == 9


# =============================================================================
# GOLDEN 7 -- commencement many years before analysis
# =============================================================================


def test_golden_7_escalation_count_is_contractual_not_model_relative() -> None:
    """Commenced 2020-07-01, acquired 2027-01-01, $30.00, 3%.

        raw first_rent_period = month_index(2020-07-01) = -77
        k(Jan-2027) = floor((1 + 77) / 12) = floor(78/12) = 6

    Six completed contract years (Jul-2021 .. Jul-2026), so Jan-2027 sits in
    the Jul-2026..Jun-2027 band. A model-month-relative count would have said
    zero.
    """

    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2020, 7, 1),
            base_rent_psf=30.0,
            escalation_pct=0.03,
            escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        )
    )

    expected_step_6 = 30.0 * 1.03**6 * AREA / 12.0
    expected_step_7 = 30.0 * 1.03**7 * AREA / 12.0

    assert rent_at(schedule, 1) == strict(expected_step_6)
    assert rent_at(schedule, 6) == strict(expected_step_6)    # Jun-2027
    assert rent_at(schedule, 7) == strict(expected_step_7)    # Jul-2027, step 7
    assert rent_at(schedule, 1) == strict(35_821.56889587)


# =============================================================================
# GOLDEN 8 -- the calendar year is irrelevant
# =============================================================================


def test_golden_8_escalation_falls_on_the_lease_anniversary_not_jan_or_the_analysis_month() -> None:
    """analysis 2027-07-01; lease commences 2027-09-01 (model month 3).

    The step must land in Sep-2028 (model month 15) -- not Jan-2028 (month 7,
    a calendar-year boundary) and not Jul-2028 (month 13, the analysis
    anniversary).
    """

    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2027, 9, 1),
            base_rent_psf=24.0,
            escalation_pct=0.05,
            escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        ),
        analysis_start=date(2027, 7, 1),
        hold_period=2,
    )

    assert rent_at(schedule, 3) == strict(24_000.0)    # Sep-2027, step 0
    assert rent_at(schedule, 7) == strict(24_000.0)    # Jan-2028, still step 0
    assert rent_at(schedule, 13) == strict(24_000.0)   # Jul-2028, still step 0
    assert rent_at(schedule, 14) == strict(24_000.0)   # Aug-2028, still step 0
    assert rent_at(schedule, 15) == strict(25_200.0)   # Sep-2028, step 1


# =============================================================================
# GOLDEN 9 -- a lease expired before the analysis start
# =============================================================================


def test_golden_9_a_lease_expired_before_the_analysis_start_is_rejected() -> None:
    """D0's accepted treatment is validation rejection, not a zero schedule:
    ``LEASE_EXPIRED_BEFORE_ANALYSIS_START`` is an ERROR, because such a lease
    is not a lease of this deal (D0 Section 6.4). Nothing is invented here."""

    from anchor.leasing import (
        LeaseIssueCode,
        LeaseLevelPropertyInputs,
        Suite,
        validate_lease_level_inputs,
    )

    expired = lease(
        rent_commencement_date=date(2020, 1, 1),
        lease_expiration_date=date(2026, 12, 31),
    )
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(
            analysis_start_date=date(2027, 1, 1), rentable_area_sf=AREA
        ),
        [Suite(suite_id="S1", suite_area_sf=AREA)],
        [expired],
    )

    assert LeaseIssueCode.LEASE_EXPIRED_BEFORE_ANALYSIS_START in {
        issue.code for issue in result.issues
    }
    assert not result.is_valid


# =============================================================================
# GOLDEN 10 -- a lease running past the projection window
# =============================================================================


def test_golden_10_a_long_lease_stops_exactly_at_the_canonical_horizon() -> None:
    """The schedule spans exactly the months supplied -- never one more -- and
    the Lease itself is neither truncated nor mutated."""

    long_lease = lease(
        rent_commencement_date=date(2027, 1, 1),
        lease_expiration_date=date(2045, 12, 31),
        base_rent_psf=24.0,
    )
    schedule = schedule_for(long_lease, hold_period=1)

    assert len(schedule.contractual_base_rent) == 24
    assert schedule.months[-1].period_index == 24
    assert schedule.last_rent_period == 24
    assert set(schedule.contractual_base_rent) == {24_000.0}
    assert long_lease.lease_expiration_date == date(2045, 12, 31)


def test_a_lease_commencing_after_the_horizon_yields_an_all_zero_series() -> None:
    """D0 Gate D1.2: an out-of-window lease yields an all-zero series and
    ``first_rent_period is None``. It is valid, not an error -- the D1.1
    horizon warning explains why it contributes nothing."""

    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2040, 1, 1),
            lease_expiration_date=date(2045, 12, 31),
        )
    )

    assert set(schedule.contractual_base_rent) == {0.0}
    assert schedule.first_rent_period is None
    assert schedule.last_rent_period is None


# =============================================================================
# Boundary exactness
# =============================================================================


@pytest.mark.parametrize(
    ("commencement", "expiration", "expected_active"),
    [
        (date(2027, 1, 1), date(2027, 1, 31), [1]),
        (date(2027, 1, 1), date(2027, 2, 28), [1, 2]),
        (date(2027, 12, 1), date(2028, 1, 31), [12, 13]),
        (date(2028, 2, 1), date(2028, 2, 29), [14]),
    ],
)
def test_active_month_boundaries_are_inclusive_at_both_ends(
    commencement: date, expiration: date, expected_active: list[int]
) -> None:
    """Both the commencement month and the (inclusive) expiration month are
    paid. December-to-January and leap-February boundaries behave identically
    to any other."""

    schedule = schedule_for(
        lease(rent_commencement_date=commencement, lease_expiration_date=expiration)
    )

    active = [
        month.period_index
        for month, amount in zip(schedule.months, schedule.contractual_base_rent)
        if amount != 0.0
    ]
    assert active == expected_active


def test_the_month_before_commencement_and_after_expiration_are_zero() -> None:
    schedule = schedule_for(
        lease(
            rent_commencement_date=date(2027, 4, 1),
            lease_expiration_date=date(2027, 9, 30),
        )
    )

    assert rent_at(schedule, 3) == 0.0    # Mar-2027
    assert rent_at(schedule, 4) != 0.0    # Apr-2027, first paid
    assert rent_at(schedule, 9) != 0.0    # Sep-2027, last paid
    assert rent_at(schedule, 10) == 0.0   # Oct-2027


# =============================================================================
# Contractual rate helpers
# =============================================================================


@pytest.mark.parametrize(
    ("escalation_pct", "escalation_index", "expected_psf"),
    [
        (0.0, 0, 24.0),
        (0.0, 5, 24.0),
        (0.05, 0, 24.0),
        (0.05, 1, 25.2),
        (0.03, 2, 31.827 * 24.0 / 30.0),
        (-0.02, 1, 23.52),
    ],
)
def test_monthly_base_rent_applies_the_rate_then_area_then_twelve(
    escalation_pct: float, escalation_index: int, expected_psf: float
) -> None:
    amount = monthly_base_rent(
        base_rent_psf=24.0,
        leased_area_sf=AREA,
        escalation_pct=escalation_pct,
        escalation_index=escalation_index,
    )

    assert amount == strict(expected_psf * AREA / 12.0)


def test_division_by_twelve_happens_once_and_last() -> None:
    """Converting to a monthly PSF first would change the floating-point
    operation order and could differ in the last bits."""

    amount = monthly_base_rent(
        base_rent_psf=100.0 / 3.0,
        leased_area_sf=7_777.0,
        escalation_pct=0.037,
        escalation_index=3,
    )
    expected = (100.0 / 3.0) * (1 + 0.037) ** 3 * 7_777.0 / 12.0

    assert amount == expected


@pytest.mark.parametrize("period", [1, 6, 12, 13, 24, 100])
def test_escalation_basis_none_is_always_step_zero(period: int) -> None:
    assert (
        escalation_period_index(
            period=period, raw_first_rent_period=-20, basis=EscalationBasis.NONE
        )
        == 0
    )


def test_none_basis_and_zero_escalation_produce_identical_series() -> None:
    """D0 Gate D1.2 acceptance bullet."""

    with_none = schedule_for(
        lease(escalation_basis=EscalationBasis.NONE, escalation_pct=0.0)
    )
    with_anniversary = schedule_for(
        lease(escalation_basis=EscalationBasis.LEASE_ANNIVERSARY, escalation_pct=0.0)
    )

    assert with_none.contractual_base_rent == with_anniversary.contractual_base_rent


def test_a_non_finite_result_fails_loudly() -> None:
    """An escalation that overflows must raise, never propagate a silent
    ``inf`` into a schedule."""

    with pytest.raises(NonFiniteResultError):
        monthly_base_rent(
            base_rent_psf=1e308,
            leased_area_sf=1e308,
            escalation_pct=0.0,
            escalation_index=0,
        )


def test_lease_rent_periods_are_raw_and_never_clamped() -> None:
    the_lease = lease(
        rent_commencement_date=date(2020, 7, 1),
        lease_expiration_date=date(2045, 12, 31),
    )

    first, last = lease_rent_periods(the_lease, analysis_start=date(2027, 1, 1))

    assert first == -77
    assert last == 228


def test_the_informational_possession_date_never_affects_rent() -> None:
    without = schedule_for(lease(rent_commencement_date=date(2027, 4, 1)))
    with_possession = schedule_for(
        lease(
            rent_commencement_date=date(2027, 4, 1),
            lease_start_date=date(2026, 11, 17),
        )
    )

    assert without.contractual_base_rent == with_possession.contractual_base_rent


# =============================================================================
# Multiple leases are computed independently -- no aggregation exists yet
# =============================================================================


def test_two_leases_are_scheduled_independently_by_the_rent_module() -> None:
    """The rent module's own scope is one lease. Summing them is D1.3's
    property aggregator, which lives in its own module and consumes these
    finished schedules -- ``rent.py`` still offers no way to combine them."""

    from anchor.leasing import rent as rent_module

    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=1)
    first = build_lease_monthly_schedule(
        lease(lease_id="L1", suite_id="S1", leased_area_sf=6_000.0),
        analysis_start=date(2027, 1, 1),
        months=months,
    )
    second = build_lease_monthly_schedule(
        lease(lease_id="L2", suite_id="S2", leased_area_sf=4_000.0),
        analysis_start=date(2027, 1, 1),
        months=months,
    )

    assert first.contractual_base_rent[0] == strict(12_000.0)
    assert second.contractual_base_rent[0] == strict(8_000.0)

    for absent in (
        "build_property_rent_roll_schedule",
        "aggregate_flow_to_annual",
        "PropertyRentRollSchedule",
    ):
        assert not hasattr(rent_module, absent), (
            f"{absent} belongs to anchor.leasing.aggregation, not rent.py"
        )
