"""Sprint D Gate D1.3 -- property rent-roll aggregation and annual derivation.

Proves, per
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 5.6, 5.7, 18.1, 18.4 and Gate D1.3:

- many leases across many suites combine into one canonical monthly property
  series, deterministically and without double counting;
- occupied and vacant rentable area are derived from contractual **activity**,
  never from rent dollars -- a zero-rent lease still occupies its suite;
- ``occupied + vacant == rentable_area_sf`` in every canonical month;
- annual figures derive **only** from monthly ones, and reconcile exactly.

No NOI, no expenses, no rollover, no acquisition integration.
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
    PropertyRentRollSchedule,
    Suite,
    aggregate_flow_over_forward_exit_window,
    aggregate_flow_to_annual,
    average_state_over_year,
    build_property_rent_roll_schedule,
    snapshot_state_at_year_end,
)
from anchor.leasing.validation import LeaseValidationError


ANALYSIS_START = date(2027, 1, 1)
FAR_FUTURE = date(2040, 12, 31)


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def suite(suite_id: str, area: float) -> Suite:
    return Suite(suite_id=suite_id, suite_area_sf=area)


def lease(
    lease_id: str,
    suite_id: str,
    area: float,
    psf: float,
    *,
    commencement: date = ANALYSIS_START,
    expiration: date = FAR_FUTURE,
    escalation_pct: float = 0.0,
    basis: EscalationBasis = EscalationBasis.NONE,
) -> Lease:
    return Lease(
        lease_id=lease_id,
        suite_id=suite_id,
        leased_area_sf=area,
        rent_commencement_date=commencement,
        lease_expiration_date=expiration,
        base_rent_psf=psf,
        escalation_pct=escalation_pct,
        escalation_basis=basis,
        lease_type=LeaseType.NNN,
    )


def build(
    rentable: float,
    suites: list[Suite],
    leases: list[Lease],
    *,
    analysis_start: date = ANALYSIS_START,
    hold_period: int = 1,
) -> PropertyRentRollSchedule:
    return build_property_rent_roll_schedule(
        LeaseLevelPropertyInputs(
            analysis_start_date=analysis_start, rentable_area_sf=rentable
        ),
        suites,
        leases,
        hold_period=hold_period,
    )


def at(schedule: PropertyRentRollSchedule, period: int) -> tuple[float, float, float]:
    """``(rent, occupied, vacant)`` for a canonical period index."""

    for position, month in enumerate(schedule.months):
        if month.period_index == period:
            return (
                schedule.contractual_base_rent[position],
                schedule.occupied_area[position],
                schedule.vacant_area[position],
            )
    raise AssertionError(f"period {period} is not in this schedule")


def assert_area_invariant(schedule: PropertyRentRollSchedule, rentable: float) -> None:
    """D0 Section 18.4, asserted in **every** canonical month."""

    for position, month in enumerate(schedule.months):
        occupied = schedule.occupied_area[position]
        vacant = schedule.vacant_area[position]
        assert occupied >= 0.0, f"period {month.period_index}"
        assert vacant >= 0.0, f"period {month.period_index}"
        assert occupied + vacant == strict(rentable), f"period {month.period_index}"
        assert 0.0 <= schedule.physical_occupancy[position] <= 1.0


# =============================================================================
# Contract shape
# =============================================================================


def test_property_schedule_declares_only_the_d0_fields() -> None:
    declared = [f.name for f in dataclasses.fields(PropertyRentRollSchedule)]

    assert declared == [
        "months",
        "lease_schedules",
        "contractual_base_rent",
        "occupied_area",
        "vacant_area",
        "physical_occupancy",
    ]


def test_no_out_of_scope_field_leaked_into_the_property_schedule() -> None:
    declared = {f.name for f in dataclasses.fields(PropertyRentRollSchedule)}

    assert not declared & {
        "noi",
        "expense_recoveries",
        "other_income",
        "operating_expenses",
        "market_rent_psf",
        "free_rent",
        "tenant_improvements",
        "leasing_commissions",
        "capex",
        "annual_debt_service",
    }


def test_lease_level_detail_is_retained_for_auditability() -> None:
    """Property rent in any month must be traceable back to the leases that
    produced it -- monthly schedules are first-class outputs, not scratch work
    discarded after aggregation."""

    schedule = build(
        12_000.0,
        [suite("A", 6_000.0), suite("B", 6_000.0)],
        [lease("L1", "A", 6_000.0, 24.0), lease("L2", "B", 6_000.0, 30.0)],
    )

    assert len(schedule.lease_schedules) == 2
    for position in range(len(schedule.months)):
        assert schedule.contractual_base_rent[position] == strict(
            sum(s.contractual_base_rent[position] for s in schedule.lease_schedules)
        )


def test_every_lease_schedule_shares_the_one_canonical_timeline() -> None:
    schedule = build(
        12_000.0,
        [suite("A", 6_000.0), suite("B", 6_000.0)],
        [lease("L1", "A", 6_000.0, 24.0), lease("L2", "B", 6_000.0, 30.0)],
    )

    for lease_schedule in schedule.lease_schedules:
        assert lease_schedule.months is schedule.months


def test_a_mismatched_timeline_fails_loudly_rather_than_being_zipped() -> None:
    from anchor.leasing import build_lease_monthly_schedule, build_model_months

    months = build_model_months(analysis_start=ANALYSIS_START, hold_period=1)
    other_months = build_model_months(analysis_start=ANALYSIS_START, hold_period=2)
    foreign = build_lease_monthly_schedule(
        lease("L1", "A", 6_000.0, 24.0),
        analysis_start=ANALYSIS_START,
        months=other_months,
    )

    with pytest.raises(ValueError, match="different month sequence"):
        PropertyRentRollSchedule(
            months=months,
            lease_schedules=(foreign,),
            contractual_base_rent=(0.0,) * len(months),
            occupied_area=(0.0,) * len(months),
            vacant_area=(0.0,) * len(months),
            physical_occupancy=(0.0,) * len(months),
        )


# =============================================================================
# PROPERTY GOLDEN 1 -- one occupied suite
# =============================================================================


def test_property_golden_1_single_fully_occupied_suite() -> None:
    """12,000 SF rentable, one suite, flat $24.00/SF/yr.

        monthly rent  = 24.00 * 12,000 / 12 = 24,000.00
        annual Year 1 = 12 * 24,000.00      = 288,000.00
    """

    schedule = build(12_000.0, [suite("A", 12_000.0)], [lease("L1", "A", 12_000.0, 24.0)])

    for period in range(1, 25):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(24_000.0)
        assert occupied == strict(12_000.0)
        assert vacant == strict(0.0)

    annual = aggregate_flow_to_annual(schedule.contractual_base_rent, hold_period=1)
    assert annual == (strict(288_000.0),)
    assert_area_invariant(schedule, 12_000.0)


# =============================================================================
# PROPERTY GOLDEN 2 -- an explicit vacant suite
# =============================================================================


def test_property_golden_2_explicit_vacant_suite() -> None:
    """100,000 SF rentable: A 40,000 @ $30, B 35,000 @ $24, C 25,000 with no
    lease at all.

        A monthly = 30.00 * 40,000 / 12 = 100,000.00
        B monthly = 24.00 * 35,000 / 12 =  70,000.00
        property                        = 170,000.00
        occupied 75,000 ; vacant 25,000
    """

    schedule = build(
        100_000.0,
        [suite("A", 40_000.0), suite("B", 35_000.0), suite("C", 25_000.0)],
        [lease("L1", "A", 40_000.0, 30.0), lease("L2", "B", 35_000.0, 24.0)],
    )

    for period in range(1, 25):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(170_000.0)
        assert occupied == strict(75_000.0)
        assert vacant == strict(25_000.0)

    assert schedule.physical_occupancy[0] == strict(0.75)
    assert_area_invariant(schedule, 100_000.0)


def test_property_golden_2_vacancy_needs_no_vacancy_percentage() -> None:
    """Suite C's 25,000 SF is vacant because it carries no lease -- not
    because a percentage was applied. No such field exists anywhere."""

    from anchor.leasing import contracts as contracts_module

    for contract in (
        contracts_module.LeaseLevelPropertyInputs,
        contracts_module.Suite,
        contracts_module.Lease,
        PropertyRentRollSchedule,
    ):
        declared = {f.name for f in dataclasses.fields(contract)}
        assert not declared & {"vacancy_credit_loss_pct", "occupancy", "vacancy_pct"}


# =============================================================================
# PROPERTY GOLDEN 3 -- different expirations
# =============================================================================


def test_property_golden_3_one_lease_expires_mid_year() -> None:
    """B expires 2027-06-30 (period 6); A and vacant C continue.

        periods 1-6   170,000.00   occupied 75,000   vacant 25,000
        periods 7-24  100,000.00   occupied 40,000   vacant 60,000
        annual Year 1 = 6*170,000 + 6*100,000 = 1,620,000.00
        forward window = 12*100,000            = 1,200,000.00
    """

    schedule = build(
        100_000.0,
        [suite("A", 40_000.0), suite("B", 35_000.0), suite("C", 25_000.0)],
        [
            lease("L1", "A", 40_000.0, 30.0),
            lease("L2", "B", 35_000.0, 24.0, expiration=date(2027, 6, 30)),
        ],
    )

    for period in range(1, 7):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(170_000.0)
        assert occupied == strict(75_000.0)
        assert vacant == strict(25_000.0)

    for period in range(7, 25):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(100_000.0)
        assert occupied == strict(40_000.0)
        assert vacant == strict(60_000.0)

    assert aggregate_flow_to_annual(
        schedule.contractual_base_rent, hold_period=1
    ) == (strict(1_620_000.0),)
    assert aggregate_flow_over_forward_exit_window(
        schedule.contractual_base_rent, hold_period=1
    ) == strict(1_200_000.0)
    assert_area_invariant(schedule, 100_000.0)


# =============================================================================
# PROPERTY GOLDEN 4 -- a future known lease
# =============================================================================


def test_property_golden_4_future_commencement_leaves_the_suite_vacant_first() -> None:
    """Lease commences 2027-04-01 (period 4)."""

    schedule = build(
        12_000.0,
        [suite("A", 12_000.0)],
        [lease("L1", "A", 12_000.0, 24.0, commencement=date(2027, 4, 1))],
    )

    for period in (1, 2, 3):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(0.0)
        assert occupied == strict(0.0)
        assert vacant == strict(12_000.0)

    for period in range(4, 25):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(24_000.0)
        assert occupied == strict(12_000.0)
        assert vacant == strict(0.0)

    # Year 1 = 9 paying months.
    assert aggregate_flow_to_annual(
        schedule.contractual_base_rent, hold_period=1
    ) == (strict(216_000.0),)
    assert_area_invariant(schedule, 12_000.0)


# =============================================================================
# PROPERTY GOLDEN 5 -- back-to-back leases
# =============================================================================


def test_property_golden_5_back_to_back_leases_are_continuously_occupied() -> None:
    """Lease A through 2027-06-30, Lease B from 2027-07-01, same suite.

    There is no vacant month and no downtime -- D1 infers neither. Adjacent
    contractual terms are simply continuous occupancy.
    """

    schedule = build(
        12_000.0,
        [suite("A", 12_000.0)],
        [
            lease("L1", "A", 12_000.0, 24.0, expiration=date(2027, 6, 30)),
            lease("L2", "A", 12_000.0, 30.0, commencement=date(2027, 7, 1)),
        ],
    )

    assert at(schedule, 6)[0] == strict(24_000.0)   # June, Lease A
    assert at(schedule, 7)[0] == strict(30_000.0)   # July, Lease B

    for period in range(1, 25):
        _, occupied, vacant = at(schedule, period)
        assert occupied == strict(12_000.0), f"period {period}"
        assert vacant == strict(0.0), f"period {period}"

    assert set(schedule.vacant_area) == {0.0}
    assert_area_invariant(schedule, 12_000.0)


# =============================================================================
# PROPERTY GOLDEN 6 -- a contractual gap
# =============================================================================


def test_property_golden_6_gap_between_two_known_leases_is_vacant() -> None:
    """Lease A through 2027-06-30, Lease B from 2027-09-01: July and August
    are contractually vacant. No rollover assumption is involved."""

    schedule = build(
        12_000.0,
        [suite("A", 12_000.0)],
        [
            lease("L1", "A", 12_000.0, 24.0, expiration=date(2027, 6, 30)),
            lease("L2", "A", 12_000.0, 30.0, commencement=date(2027, 9, 1)),
        ],
    )

    for period in range(1, 7):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(24_000.0)
        assert occupied == strict(12_000.0)
        assert vacant == strict(0.0)

    for period in (7, 8):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(0.0)
        assert occupied == strict(0.0)
        assert vacant == strict(12_000.0)

    for period in range(9, 25):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(30_000.0)
        assert occupied == strict(12_000.0)
        assert vacant == strict(0.0)

    # Year 1 = 6 * 24,000 + 0 + 0 + 4 * 30,000
    assert aggregate_flow_to_annual(
        schedule.contractual_base_rent, hold_period=1
    ) == (strict(264_000.0),)
    assert_area_invariant(schedule, 12_000.0)


# =============================================================================
# PROPERTY GOLDEN 7 -- a zero-rent occupied lease
# =============================================================================


def test_property_golden_7_zero_rent_lease_still_occupies_its_suite() -> None:
    """Occupancy is derived from contractual activity, never from dollars.
    ``contractual_base_rent > 0`` must never be the occupancy test."""

    schedule = build(
        20_000.0,
        [suite("A", 12_000.0), suite("B", 8_000.0)],
        [
            lease("L1", "A", 12_000.0, 0.0),   # active, rent-free
            lease("L2", "B", 8_000.0, 24.0),
        ],
    )

    for period in range(1, 25):
        rent, occupied, vacant = at(schedule, period)
        assert rent == strict(16_000.0)         # only Suite B pays
        assert occupied == strict(20_000.0)     # BOTH suites occupied
        assert vacant == strict(0.0)

    assert schedule.lease_schedules[0].contractual_base_rent[0] == 0.0
    assert schedule.lease_schedules[0].occupied_area[0] == strict(12_000.0)
    assert_area_invariant(schedule, 20_000.0)


# =============================================================================
# PROPERTY GOLDEN 8 -- escalating multi-tenant, different anniversaries
# =============================================================================


def test_property_golden_8_property_rent_steps_when_its_leases_step() -> None:
    """A: 6,000 SF @ $24, 5%, commences 2027-01-01 (anniversary January).
    B: 6,000 SF @ $30, 10%, commences 2027-04-01 (anniversary April).

        A  k=0  24.00 * 6,000 / 12 = 12,000.00
           k=1  25.20 * 6,000 / 12 = 12,600.00
        B  k=0  30.00 * 6,000 / 12 = 15,000.00
           k=1  33.00 * 6,000 / 12 = 16,500.00

        periods  1-3   A only                    12,000.00
        periods  4-12  A + B                     27,000.00
        periods 13-15  A steps January           27,600.00
        periods 16-24  B steps April             29,100.00

        annual Year 1 = 3*12,000 + 9*27,000 =   279,000.00
        forward       = 3*27,600 + 9*29,100 =   344,700.00
    """

    schedule = build(
        12_000.0,
        [suite("A", 6_000.0), suite("B", 6_000.0)],
        [
            lease(
                "L1", "A", 6_000.0, 24.0,
                escalation_pct=0.05, basis=EscalationBasis.LEASE_ANNIVERSARY,
            ),
            lease(
                "L2", "B", 6_000.0, 30.0,
                commencement=date(2027, 4, 1),
                escalation_pct=0.10, basis=EscalationBasis.LEASE_ANNIVERSARY,
            ),
        ],
    )

    expected = {
        **{p: 12_000.0 for p in range(1, 4)},
        **{p: 27_000.0 for p in range(4, 13)},
        **{p: 27_600.0 for p in range(13, 16)},
        **{p: 29_100.0 for p in range(16, 25)},
    }
    for period, amount in expected.items():
        assert at(schedule, period)[0] == strict(amount), f"period {period}"

    assert aggregate_flow_to_annual(
        schedule.contractual_base_rent, hold_period=1
    ) == (strict(279_000.0),)
    assert aggregate_flow_over_forward_exit_window(
        schedule.contractual_base_rent, hold_period=1
    ) == strict(344_700.0)


# =============================================================================
# PROPERTY GOLDEN 9 -- a non-January hold year
# =============================================================================


def test_property_golden_9_hold_year_one_is_not_calendar_2027() -> None:
    """analysis 2027-07-01; lease commenced 2027-01-01 at $24.00 with 5%
    January anniversaries, 12,000 SF.

        raw first period = month_index(2027-01-01) = -5
        k(m) = floor((m + 5) / 12)
        periods  1-6   (Jul-Dec 2027)  k=0  24,000.00
        periods  7-18  (Jan-Dec 2028)  k=1  25,200.00
        periods 19-24  (Jan-Jun 2029)  k=2  26,460.00

        Hold Year 1 (Jul-2027..Jun-2028) = 6*24,000 + 6*25,200 = 295,200.00
        forward     (Jul-2028..Jun-2029) = 6*25,200 + 6*26,460 = 309,960.00

    Calendar-year grouping would have produced neither figure.
    """

    schedule = build(
        12_000.0,
        [suite("A", 12_000.0)],
        [
            lease(
                "L1", "A", 12_000.0, 24.0,
                commencement=date(2027, 1, 1),
                escalation_pct=0.05,
                basis=EscalationBasis.LEASE_ANNIVERSARY,
            )
        ],
        analysis_start=date(2027, 7, 1),
    )

    assert at(schedule, 1)[0] == strict(24_000.0)    # Jul-2027
    assert at(schedule, 6)[0] == strict(24_000.0)    # Dec-2027
    assert at(schedule, 7)[0] == strict(25_200.0)    # Jan-2028
    assert at(schedule, 18)[0] == strict(25_200.0)   # Dec-2028
    assert at(schedule, 19)[0] == strict(26_460.0)   # Jan-2029

    assert aggregate_flow_to_annual(
        schedule.contractual_base_rent, hold_period=1
    ) == (strict(295_200.0),)
    assert aggregate_flow_over_forward_exit_window(
        schedule.contractual_base_rent, hold_period=1
    ) == strict(309_960.0)

    # Hold Year 1 spans two calendar years.
    assert schedule.months[0].month_start == date(2027, 7, 1)
    assert schedule.months[11].month_start == date(2028, 6, 1)
    assert {m.hold_year for m in schedule.months[:12]} == {1}


# =============================================================================
# PROPERTY GOLDEN 10 -- the forward exit year
# =============================================================================


@pytest.mark.parametrize("hold_period", [1, 2])
def test_property_golden_10_the_forward_window_is_kept_and_reported(
    hold_period: int,
) -> None:
    """The final twelve canonical months are never discarded. They are
    reported as their own scalar rather than folded into a Year H+1 entry, so
    the ``_by_year`` series keeps its uniform length H."""

    schedule = build(
        12_000.0,
        [suite("A", 12_000.0)],
        [lease("L1", "A", 12_000.0, 24.0)],
        hold_period=hold_period,
    )

    annual = aggregate_flow_to_annual(
        schedule.contractual_base_rent, hold_period=hold_period
    )
    forward = aggregate_flow_over_forward_exit_window(
        schedule.contractual_base_rent, hold_period=hold_period
    )

    assert len(annual) == hold_period
    assert all(value == strict(288_000.0) for value in annual)
    assert forward == strict(288_000.0)

    forward_months = [m for m in schedule.months if m.is_forward_exit_month]
    assert len(forward_months) == 12
    assert {m.hold_year for m in forward_months} == {hold_period + 1}

    # The scalar is exactly the sum over those twelve months.
    positions = [
        position
        for position, month in enumerate(schedule.months)
        if month.is_forward_exit_month
    ]
    assert forward == strict(
        sum(schedule.contractual_base_rent[p] for p in positions)
    )


# =============================================================================
# Monthly / annual reconciliation  (G-M4)
# =============================================================================


def _reconciliation_fixtures() -> list[tuple[str, PropertyRentRollSchedule, int]]:
    flat = build(12_000.0, [suite("A", 12_000.0)], [lease("L1", "A", 12_000.0, 24.0)])
    escalating = build(
        12_000.0,
        [suite("A", 12_000.0)],
        [
            lease(
                "L1", "A", 12_000.0, 24.0,
                escalation_pct=0.05, basis=EscalationBasis.LEASE_ANNIVERSARY,
            )
        ],
        hold_period=3,
    )
    expiring = build(
        100_000.0,
        [suite("A", 40_000.0), suite("B", 35_000.0), suite("C", 25_000.0)],
        [
            lease("L1", "A", 40_000.0, 30.0),
            lease("L2", "B", 35_000.0, 24.0, expiration=date(2028, 6, 30)),
        ],
        hold_period=2,
    )
    commencing = build(
        12_000.0,
        [suite("A", 12_000.0)],
        [lease("L1", "A", 12_000.0, 24.0, commencement=date(2028, 4, 1))],
        hold_period=2,
    )
    return [
        ("flat", flat, 1),
        ("escalating", escalating, 3),
        ("multi-suite expiring", expiring, 2),
        ("future commencement", commencing, 2),
    ]


@pytest.mark.parametrize(
    ("label", "schedule", "hold_period"),
    _reconciliation_fixtures(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_annual_equals_the_sum_of_its_twelve_months(
    label: str, schedule: PropertyRentRollSchedule, hold_period: int
) -> None:
    monthly = schedule.contractual_base_rent
    annual = aggregate_flow_to_annual(monthly, hold_period=hold_period)

    assert len(annual) == hold_period
    for year in range(1, hold_period + 1):
        expected = sum(monthly[(year - 1) * 12 : year * 12])
        assert annual[year - 1] == strict(expected), f"{label} year {year}"

    forward = aggregate_flow_over_forward_exit_window(monthly, hold_period=hold_period)
    assert forward == strict(sum(monthly[12 * hold_period :]))

    # Every month is accounted for exactly once.
    assert sum(annual) + forward == strict(sum(monthly))


def test_year_slices_partition_the_hold_with_no_gap_or_overlap() -> None:
    """Failure modes FM-2 (a month omitted) and FM-3 (a month counted twice)."""

    hold_period = 3
    monthly = tuple(float(i) for i in range(1, 12 * hold_period + 13))

    annual = aggregate_flow_to_annual(monthly, hold_period=hold_period)
    forward = aggregate_flow_over_forward_exit_window(monthly, hold_period=hold_period)

    assert annual == (
        strict(sum(range(1, 13))),
        strict(sum(range(13, 25))),
        strict(sum(range(25, 37))),
    )
    assert forward == strict(sum(range(37, 49)))
    assert sum(annual) + forward == strict(sum(monthly))


@pytest.mark.parametrize("hold_period", [1, 2, 5])
def test_a_monthly_series_of_the_wrong_length_is_rejected(hold_period: int) -> None:
    with pytest.raises(ValueError):
        aggregate_flow_to_annual((1.0, 2.0), hold_period=hold_period)


# =============================================================================
# Flow vs state aggregation  (D0 Section 5.7; FM-7, FM-8)
# =============================================================================


def test_state_metrics_have_snapshot_and_average_forms_never_a_sum() -> None:
    schedule = build(
        12_000.0,
        [suite("A", 12_000.0)],
        [lease("L1", "A", 12_000.0, 24.0, commencement=date(2027, 7, 1))],
    )

    # Occupied for periods 7..24 only.
    year_end = snapshot_state_at_year_end(schedule.occupied_area, hold_period=1)
    average = average_state_over_year(schedule.occupied_area, hold_period=1)

    assert year_end == (strict(12_000.0),)          # December 2027: occupied
    assert average == (strict(6_000.0),)            # 6 of 12 months occupied
    # A sum would be a meaningless 72,000 SF.
    assert average[0] != sum(schedule.occupied_area[:12])


def test_occupancy_snapshot_and_average_differ_when_occupancy_changes() -> None:
    schedule = build(
        100_000.0,
        [suite("A", 40_000.0), suite("B", 35_000.0), suite("C", 25_000.0)],
        [
            lease("L1", "A", 40_000.0, 30.0),
            lease("L2", "B", 35_000.0, 24.0, expiration=date(2027, 6, 30)),
        ],
    )

    assert snapshot_state_at_year_end(
        schedule.physical_occupancy, hold_period=1
    ) == (strict(0.40),)
    assert average_state_over_year(
        schedule.physical_occupancy, hold_period=1
    ) == (strict((6 * 0.75 + 6 * 0.40) / 12),)


def test_average_state_divides_once_after_an_ascending_sum() -> None:
    monthly = tuple(float(i) for i in range(1, 25))

    assert average_state_over_year(monthly, hold_period=1) == (
        strict(sum(range(1, 13)) / 12),
    )


# =============================================================================
# Property invariants across representative fixtures
# =============================================================================


@pytest.mark.parametrize(
    ("label", "schedule", "hold_period"),
    _reconciliation_fixtures(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_area_invariant_holds_in_every_month_of_every_fixture(
    label: str, schedule: PropertyRentRollSchedule, hold_period: int
) -> None:
    rentable = schedule.occupied_area[0] + schedule.vacant_area[0]

    for position, month in enumerate(schedule.months):
        occupied = schedule.occupied_area[position]
        vacant = schedule.vacant_area[position]
        assert occupied >= 0.0
        assert vacant >= 0.0
        assert occupied + vacant == strict(rentable), f"{label} period {month.period_index}"
        assert 0.0 <= schedule.physical_occupancy[position] <= 1.0


def test_occupancy_is_never_clamped_to_hide_bad_arithmetic() -> None:
    """The invariant holds because the areas genuinely reconcile, not because
    a ``min``/``max`` was applied. A fully occupied property reports exactly
    1.0 and a fully vacant one exactly 0.0."""

    full = build(12_000.0, [suite("A", 12_000.0)], [lease("L1", "A", 12_000.0, 24.0)])
    empty = build(12_000.0, [suite("A", 12_000.0)], [])

    assert set(full.physical_occupancy) == {1.0}
    assert set(empty.physical_occupancy) == {0.0}
    assert set(empty.occupied_area) == {0.0}
    assert set(empty.vacant_area) == {12_000.0}


# =============================================================================
# Determinism and immutability
# =============================================================================


def test_repeated_property_builds_are_value_equal() -> None:
    def make() -> PropertyRentRollSchedule:
        return build(
            12_000.0,
            [suite("A", 6_000.0), suite("B", 6_000.0)],
            [
                lease("L1", "A", 6_000.0, 24.0, escalation_pct=0.05, basis=EscalationBasis.LEASE_ANNIVERSARY),
                lease("L2", "B", 6_000.0, 30.0),
            ],
        )

    first = make()
    for _ in range(50):
        assert make() == first


def test_lease_order_does_not_change_property_totals() -> None:
    suites = [suite("A", 6_000.0), suite("B", 6_000.0)]
    leases = [
        lease("L1", "A", 6_000.0, 24.0),
        lease("L2", "B", 6_000.0, 30.0),
    ]

    forward = build(12_000.0, suites, leases)
    reversed_order = build(12_000.0, suites, list(reversed(leases)))

    for position in range(len(forward.months)):
        assert forward.contractual_base_rent[position] == strict(
            reversed_order.contractual_base_rent[position]
        )
        assert forward.occupied_area[position] == strict(
            reversed_order.occupied_area[position]
        )


def test_the_builder_mutates_nothing() -> None:
    inputs = LeaseLevelPropertyInputs(
        analysis_start_date=ANALYSIS_START, rentable_area_sf=12_000.0
    )
    suites = [suite("A", 12_000.0)]
    leases = [lease("L1", "A", 12_000.0, 24.0)]

    build_property_rent_roll_schedule(inputs, suites, leases, hold_period=1)

    assert inputs == LeaseLevelPropertyInputs(
        analysis_start_date=ANALYSIS_START, rentable_area_sf=12_000.0
    )
    assert suites == [suite("A", 12_000.0)]
    assert leases == [lease("L1", "A", 12_000.0, 24.0)]


def test_property_schedule_is_immutable() -> None:
    schedule = build(12_000.0, [suite("A", 12_000.0)], [lease("L1", "A", 12_000.0, 24.0)])

    with pytest.raises(dataclasses.FrozenInstanceError):
        schedule.contractual_base_rent = ()  # type: ignore[misc]


# =============================================================================
# Validation boundary
# =============================================================================


def test_the_property_builder_refuses_a_rent_roll_whose_areas_do_not_reconcile() -> None:
    with pytest.raises(LeaseValidationError):
        build(100_000.0, [suite("A", 40_000.0)], [lease("L1", "A", 40_000.0, 30.0)])


def test_the_property_builder_refuses_overlapping_same_suite_leases() -> None:
    """Aggregation adds no second overlap algorithm; it relies on the one
    validation authority and fails fast."""

    with pytest.raises(LeaseValidationError):
        build(
            12_000.0,
            [suite("A", 12_000.0)],
            [
                lease("L1", "A", 12_000.0, 24.0, expiration=date(2028, 6, 30)),
                lease("L2", "A", 12_000.0, 30.0, commencement=date(2028, 1, 1)),
            ],
        )


def test_the_property_builder_refuses_a_non_month_aligned_date() -> None:
    with pytest.raises(LeaseValidationError):
        build(
            12_000.0,
            [suite("A", 12_000.0)],
            [lease("L1", "A", 12_000.0, 24.0, commencement=date(2027, 4, 15))],
        )


def test_a_property_with_no_leases_at_all_aggregates_to_zero() -> None:
    schedule = build(12_000.0, [suite("A", 12_000.0)], [])

    assert set(schedule.contractual_base_rent) == {0.0}
    assert aggregate_flow_to_annual(
        schedule.contractual_base_rent, hold_period=1
    ) == (strict(0.0),)
    assert_area_invariant(schedule, 12_000.0)
