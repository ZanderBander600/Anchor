"""Sprint D Gate D1.4 -- D1 hardening, adversarial QA and closeout.

This gate adds no lease economics. It proves the D1 engine assembled across
D1.0-D1.3 is correct, deterministic and isolated, by attacking it from
angles the per-gate suites did not:

- a single richer master property case, still hand-auditable end to end;
- an adversarial matrix over analysis-start months, hold lengths and
  escalation anniversaries;
- the invariants that must hold for *every* month of *every* fixture, rather
  than for hand-picked periods;
- proof that state series are not meaningfully summable, and that flow and
  state cannot be confused;
- proof that no month is omitted or double-counted anywhere;
- a deterministic scale sanity check.

Governed by
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``.
"""

from __future__ import annotations

import dataclasses
import pathlib
import time
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
    build_model_months,
    build_property_rent_roll_schedule,
    month_index,
    projection_month_count,
    snapshot_state_at_year_end,
    validate_lease_level_inputs,
)
from anchor.leasing.validation import LeaseIssueCode, LeaseIssueSeverity


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def suite(suite_id: str, area: float) -> Suite:
    return Suite(suite_id=suite_id, suite_area_sf=area)


def lease(
    lease_id: str,
    suite_id: str,
    area: float,
    psf: float,
    commencement: date,
    expiration: date,
    *,
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
    analysis_start: date,
    hold_period: int,
) -> PropertyRentRollSchedule:
    return build_property_rent_roll_schedule(
        LeaseLevelPropertyInputs(
            analysis_start_date=analysis_start, rentable_area_sf=rentable
        ),
        suites,
        leases,
        hold_period=hold_period,
    )


# =============================================================================
# THE D1 MASTER GOLDEN CASE
# =============================================================================
#
# analysis_start = 2027-07-01  (deliberately NOT January)
# hold_period    = 2           ->  36 canonical months
#   Hold Year 1 : m1-12   Jul-2027 .. Jun-2028
#   Hold Year 2 : m13-24  Jul-2028 .. Jun-2029
#   Forward     : m25-36  Jul-2029 .. Jun-2030
#
# rentable_area_sf = 50,000, fully accounted for by four suites:
#   A 20,000  long in-place escalating lease, commenced two years pre-close
#   B 15,000  lease expiring mid-hold, a six-month contractual gap, then re-let
#   C 10,000  future known lease -- and it is RENT-FREE
#   D  5,000  no lease at all, vacant throughout
#
# Every figure below is hand-derived from D0 Section 6.1.
#
#   L1 on A: $30.00/SF, 4% on July anniversaries, commenced 2025-07-01
#            raw first period = month_index(2025-07-01) = -23
#            k(m) = floor((m + 23) / 12)
#            m1-12  k=2  30 * 1.04^2 = 32.448000  ->  32.448 * 20,000/12 = 54,080.000
#            m13-24 k=3  30 * 1.04^3 = 33.745920  ->                       56,243.200
#            m25-36 k=4  30 * 1.04^4 = 35.0957568 ->                       58,492.928
#   L2 on B: $24.00 flat, expires 2028-06-30 = m12   ->  24*15,000/12 = 30,000.000
#   L3 on B: $27.00 flat, commences 2029-01-01 = m19 ->  27*15,000/12 = 33,750.000
#   L4 on C: $0.00, commences 2028-01-01 = m7        ->  0.000, but OCCUPIED
#
# Property rent:
#   m1-12   54,080.000 + 30,000.000            =  84,080.000
#   m13-18  56,243.200                          =  56,243.200
#   m19-24  56,243.200 + 33,750.000             =  89,993.200
#   m25-36  58,492.928 + 33,750.000             =  92,242.928
#
# Occupied area:
#   m1-6    A + B                = 35,000   vacant 15,000   occupancy 0.70
#   m7-12   A + B + C            = 45,000   vacant  5,000   occupancy 0.90
#   m13-18  A + C                = 30,000   vacant 20,000   occupancy 0.60
#   m19-36  A + B + C            = 45,000   vacant  5,000   occupancy 0.90
#
# Annual:
#   Hold Year 1 = 12 * 84,080.000                       = 1,008,960.000
#   Hold Year 2 = 6 * 56,243.200 + 6 * 89,993.200       =   877,418.400
#   Forward     = 12 * 92,242.928                       = 1,106,915.136
# =============================================================================

MASTER_START = date(2027, 7, 1)
MASTER_HOLD = 2
MASTER_RENTABLE = 50_000.0

MASTER_L1 = (54_080.0, 56_243.2, 58_492.928)
MASTER_L2 = 30_000.0
MASTER_L3 = 33_750.0


def master_case() -> PropertyRentRollSchedule:
    return build(
        MASTER_RENTABLE,
        [
            suite("A", 20_000.0),
            suite("B", 15_000.0),
            suite("C", 10_000.0),
            suite("D", 5_000.0),
        ],
        [
            lease(
                "L1", "A", 20_000.0, 30.0,
                date(2025, 7, 1), date(2035, 6, 30),
                escalation_pct=0.04, basis=EscalationBasis.LEASE_ANNIVERSARY,
            ),
            lease("L2", "B", 15_000.0, 24.0, date(2026, 1, 1), date(2028, 6, 30)),
            lease("L3", "B", 15_000.0, 27.0, date(2029, 1, 1), date(2034, 12, 31)),
            lease("L4", "C", 10_000.0, 0.0, date(2028, 1, 1), date(2033, 12, 31)),
        ],
        analysis_start=MASTER_START,
        hold_period=MASTER_HOLD,
    )


def _expected_master_rent() -> dict[int, float]:
    return {
        **{m: 84_080.0 for m in range(1, 13)},
        **{m: 56_243.2 for m in range(13, 19)},
        **{m: 89_993.2 for m in range(19, 25)},
        **{m: 92_242.928 for m in range(25, 37)},
    }


def _expected_master_occupied() -> dict[int, float]:
    return {
        **{m: 35_000.0 for m in range(1, 7)},
        **{m: 45_000.0 for m in range(7, 13)},
        **{m: 30_000.0 for m in range(13, 19)},
        **{m: 45_000.0 for m in range(19, 37)},
    }


def test_master_case_monthly_rent() -> None:
    schedule = master_case()
    expected = _expected_master_rent()

    assert len(schedule.months) == 36
    for month, amount in zip(schedule.months, schedule.contractual_base_rent):
        assert amount == strict(expected[month.period_index]), (
            f"period {month.period_index} ({month.month_start})"
        )


def test_master_case_rent_changes_only_at_the_documented_months() -> None:
    """Four transitions, each traceable to one contractual event."""

    schedule = master_case()
    rent = dict(
        zip((m.period_index for m in schedule.months), schedule.contractual_base_rent)
    )

    # L2 expires at m12; L1 steps at m13 (July anniversary).
    assert rent[12] == strict(84_080.0)
    assert rent[13] == strict(56_243.2)
    # L3 commences at m19.
    assert rent[18] == strict(56_243.2)
    assert rent[19] == strict(89_993.2)
    # L1 steps again at m25 -- the first forward month.
    assert rent[24] == strict(89_993.2)
    assert rent[25] == strict(92_242.928)

    changes = {
        month.period_index
        for previous, month in zip(schedule.months, schedule.months[1:])
        if rent[month.period_index] != rent[previous.period_index]
    }
    assert changes == {13, 19, 25}


def test_master_case_occupancy_and_vacancy() -> None:
    schedule = master_case()
    expected = _expected_master_occupied()

    for position, month in enumerate(schedule.months):
        occupied = expected[month.period_index]
        assert schedule.occupied_area[position] == strict(occupied)
        assert schedule.vacant_area[position] == strict(MASTER_RENTABLE - occupied)
        assert schedule.physical_occupancy[position] == strict(
            occupied / MASTER_RENTABLE
        )


def test_master_case_zero_rent_suite_is_occupied_not_vacant() -> None:
    """Suite C pays nothing from m7 yet occupies 10,000 SF. Occupancy rose
    from 0.70 to 0.90 while rent did not move at all -- the sharpest possible
    proof that occupancy is activity-based, not dollar-based."""

    schedule = master_case()
    rent = dict(
        zip((m.period_index for m in schedule.months), schedule.contractual_base_rent)
    )
    occupied = dict(
        zip((m.period_index for m in schedule.months), schedule.occupied_area)
    )

    assert rent[6] == strict(rent[7])            # rent unchanged
    assert occupied[6] == strict(35_000.0)
    assert occupied[7] == strict(45_000.0)       # occupancy rose by C's 10,000

    c_schedule = next(s for s in schedule.lease_schedules if s.lease_id == "L4")
    assert set(c_schedule.contractual_base_rent) == {0.0}
    assert c_schedule.occupied_area[6] == strict(10_000.0)
    assert c_schedule.first_rent_period == 7


def test_master_case_contractual_gap_is_vacant_without_any_rollover() -> None:
    """Suite B: L2 ends m12, L3 begins m19. Months 13-18 are vacant because
    no contract covers them -- no downtime, no renewal, no successor."""

    schedule = master_case()
    occupied = dict(
        zip((m.period_index for m in schedule.months), schedule.occupied_area)
    )

    assert occupied[12] == strict(45_000.0)
    for period in range(13, 19):
        assert occupied[period] == strict(30_000.0), f"period {period}"
    assert occupied[19] == strict(45_000.0)

    assert len(schedule.lease_schedules) == 4  # exactly the four supplied


def test_master_case_annual_and_forward_totals() -> None:
    schedule = master_case()
    monthly = schedule.contractual_base_rent

    annual = aggregate_flow_to_annual(monthly, hold_period=MASTER_HOLD)
    forward = aggregate_flow_over_forward_exit_window(monthly, hold_period=MASTER_HOLD)

    assert annual == (strict(1_008_960.0), strict(877_418.4))
    assert forward == strict(1_106_915.136)
    assert sum(annual) + forward == strict(sum(monthly))


def test_master_case_annual_state_metrics() -> None:
    schedule = master_case()

    assert snapshot_state_at_year_end(
        schedule.physical_occupancy, hold_period=MASTER_HOLD
    ) == (strict(0.90), strict(0.90))
    assert average_state_over_year(
        schedule.physical_occupancy, hold_period=MASTER_HOLD
    ) == (strict(0.80), strict(0.75))

    assert snapshot_state_at_year_end(
        schedule.occupied_area, hold_period=MASTER_HOLD
    ) == (strict(45_000.0), strict(45_000.0))
    assert average_state_over_year(
        schedule.occupied_area, hold_period=MASTER_HOLD
    ) == (strict(40_000.0), strict(37_500.0))


def test_master_case_hold_years_are_analysis_relative() -> None:
    schedule = master_case()
    by_index = {m.period_index: m for m in schedule.months}

    assert by_index[1].month_start == date(2027, 7, 1)
    assert by_index[6].month_start == date(2027, 12, 1)
    assert by_index[7].month_start == date(2028, 1, 1)
    assert by_index[12].month_start == date(2028, 6, 1)
    assert {by_index[m].hold_year for m in range(1, 13)} == {1}
    assert {by_index[m].hold_year for m in range(13, 25)} == {2}
    assert {by_index[m].hold_year for m in range(25, 37)} == {3}
    assert by_index[25].month_start == date(2029, 7, 1)
    assert by_index[36].month_start == date(2030, 6, 1)


def test_master_case_long_leases_warn_but_do_not_block() -> None:
    """Three of the four leases outlast the 36-month window. Each warns; none
    is an error, and none is truncated in the ``Lease`` itself."""

    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(
            analysis_start_date=MASTER_START, rentable_area_sf=MASTER_RENTABLE
        ),
        [suite("A", 20_000.0), suite("B", 15_000.0), suite("C", 10_000.0), suite("D", 5_000.0)],
        [
            lease(
                "L1", "A", 20_000.0, 30.0, date(2025, 7, 1), date(2035, 6, 30),
                escalation_pct=0.04, basis=EscalationBasis.LEASE_ANNIVERSARY,
            ),
            lease("L2", "B", 15_000.0, 24.0, date(2026, 1, 1), date(2028, 6, 30)),
            lease("L3", "B", 15_000.0, 27.0, date(2029, 1, 1), date(2034, 12, 31)),
            lease("L4", "C", 10_000.0, 0.0, date(2028, 1, 1), date(2033, 12, 31)),
        ],
        hold_period=MASTER_HOLD,
    )

    assert result.is_valid
    assert {issue.code for issue in result.warnings} == {
        LeaseIssueCode.LEASE_EXTENDS_BEYOND_HORIZON
    }
    assert len(result.warnings) == 3
    assert all(i.severity is LeaseIssueSeverity.WARNING for i in result.warnings)


# =============================================================================
# Adversarial matrix -- invariants that must hold everywhere
# =============================================================================


def _adversarial_fixtures() -> list[tuple[str, PropertyRentRollSchedule, float, int]]:
    """One entry per materially distinct property shape (Part 9 A-L)."""

    cases: list[tuple[str, PropertyRentRollSchedule, float, int]] = []

    def add(label: str, rentable: float, suites, leases, start: date, hold: int) -> None:
        cases.append(
            (label, build(rentable, suites, leases, analysis_start=start, hold_period=hold), rentable, hold)
        )

    far = date(2045, 12, 31)
    jan, jul, dec = date(2027, 1, 1), date(2027, 7, 1), date(2027, 12, 1)

    add("A fully occupied", 10_000.0, [suite("S", 10_000.0)],
        [lease("L", "S", 10_000.0, 24.0, jan, far)], jan, 1)

    add("B fully vacant", 10_000.0, [suite("S", 10_000.0)], [], jan, 1)

    add("C partially occupied", 10_000.0,
        [suite("S1", 6_000.0), suite("S2", 4_000.0)],
        [lease("L", "S1", 6_000.0, 24.0, jan, far)], jan, 2)

    add("D different rents", 10_000.0,
        [suite("S1", 6_000.0), suite("S2", 4_000.0)],
        [lease("L1", "S1", 6_000.0, 18.0, jan, far),
         lease("L2", "S2", 4_000.0, 42.0, jan, far)], jan, 1)

    add("E different anniversaries", 10_000.0,
        [suite("S1", 6_000.0), suite("S2", 4_000.0)],
        [lease("L1", "S1", 6_000.0, 24.0, jan, far,
               escalation_pct=0.03, basis=EscalationBasis.LEASE_ANNIVERSARY),
         lease("L2", "S2", 4_000.0, 30.0, date(2027, 5, 1), far,
               escalation_pct=0.07, basis=EscalationBasis.LEASE_ANNIVERSARY)], jan, 3)

    add("F different expirations", 10_000.0,
        [suite("S1", 6_000.0), suite("S2", 4_000.0)],
        [lease("L1", "S1", 6_000.0, 24.0, jan, date(2028, 2, 29)),
         lease("L2", "S2", 4_000.0, 30.0, jan, date(2027, 11, 30))], jan, 2)

    add("G future known lease", 10_000.0, [suite("S", 10_000.0)],
        [lease("L", "S", 10_000.0, 24.0, date(2028, 3, 1), far)], jan, 1)

    add("H back-to-back", 10_000.0, [suite("S", 10_000.0)],
        [lease("L1", "S", 10_000.0, 24.0, jan, date(2027, 6, 30)),
         lease("L2", "S", 10_000.0, 30.0, jul, far)], jan, 1)

    add("I contractual gap", 10_000.0, [suite("S", 10_000.0)],
        [lease("L1", "S", 10_000.0, 24.0, jan, date(2027, 6, 30)),
         lease("L2", "S", 10_000.0, 30.0, date(2027, 10, 1), far)], jan, 1)

    add("J zero-rent occupied", 10_000.0,
        [suite("S1", 6_000.0), suite("S2", 4_000.0)],
        [lease("L1", "S1", 6_000.0, 0.0, jan, far),
         lease("L2", "S2", 4_000.0, 30.0, jan, far)], jan, 1)

    add("K into forward window", 10_000.0, [suite("S", 10_000.0)],
        [lease("L", "S", 10_000.0, 24.0, jan, date(2028, 8, 31))], jan, 1)

    add("L december start, all of the above", MASTER_RENTABLE,
        [suite("A", 20_000.0), suite("B", 15_000.0), suite("C", 10_000.0), suite("D", 5_000.0)],
        [lease("L1", "A", 20_000.0, 30.0, date(2025, 7, 1), date(2035, 6, 30),
               escalation_pct=0.04, basis=EscalationBasis.LEASE_ANNIVERSARY),
         lease("L2", "B", 15_000.0, 24.0, date(2026, 1, 1), date(2029, 6, 30)),
         lease("L3", "C", 10_000.0, 0.0, date(2029, 1, 1), far)], dec, 3)

    cases.append(("master", master_case(), MASTER_RENTABLE, MASTER_HOLD))
    return cases


ADVERSARIAL = _adversarial_fixtures()
IDS = [label for label, _, _, _ in ADVERSARIAL]


@pytest.mark.parametrize(("label", "schedule", "rentable", "hold"), ADVERSARIAL, ids=IDS)
def test_area_reconciles_in_every_month_of_every_fixture(
    label: str, schedule: PropertyRentRollSchedule, rentable: float, hold: int
) -> None:
    """Part 10. Not hand-picked periods -- every month of every shape."""

    assert len(schedule.months) == projection_month_count(hold)

    for position, month in enumerate(schedule.months):
        occupied = schedule.occupied_area[position]
        vacant = schedule.vacant_area[position]
        occupancy = schedule.physical_occupancy[position]

        assert occupied >= 0.0, f"{label} m{month.period_index}"
        assert vacant >= 0.0, f"{label} m{month.period_index}"
        assert occupied + vacant == strict(rentable), f"{label} m{month.period_index}"
        assert 0.0 <= occupancy <= 1.0, f"{label} m{month.period_index}"
        assert occupancy == strict(occupied / rentable)


@pytest.mark.parametrize(("label", "schedule", "rentable", "hold"), ADVERSARIAL, ids=IDS)
def test_monthly_and_annual_reconcile_in_every_fixture(
    label: str, schedule: PropertyRentRollSchedule, rentable: float, hold: int
) -> None:
    """Part 12. No month omitted, none counted twice, no independent annual
    formula."""

    monthly = schedule.contractual_base_rent
    annual = aggregate_flow_to_annual(monthly, hold_period=hold)
    forward = aggregate_flow_over_forward_exit_window(monthly, hold_period=hold)

    assert len(annual) == hold
    for year in range(1, hold + 1):
        assert annual[year - 1] == strict(
            sum(monthly[(year - 1) * 12 : year * 12])
        ), f"{label} year {year}"

    assert forward == strict(sum(monthly[12 * hold :]))
    assert sum(annual) + forward == strict(sum(monthly))


@pytest.mark.parametrize(("label", "schedule", "rentable", "hold"), ADVERSARIAL, ids=IDS)
def test_property_rent_is_auditable_lease_by_lease(
    label: str, schedule: PropertyRentRollSchedule, rentable: float, hold: int
) -> None:
    """Part 9 / auditability: every property month is exactly the sum of its
    lease schedules, and every lease schedule shares the one timeline."""

    for position in range(len(schedule.months)):
        assert schedule.contractual_base_rent[position] == strict(
            sum(s.contractual_base_rent[position] for s in schedule.lease_schedules)
        ), f"{label} position {position}"
        assert schedule.occupied_area[position] == strict(
            sum(s.occupied_area[position] for s in schedule.lease_schedules)
        )

    for lease_schedule in schedule.lease_schedules:
        assert lease_schedule.months is schedule.months


@pytest.mark.parametrize(("label", "schedule", "rentable", "hold"), ADVERSARIAL, ids=IDS)
def test_forward_window_is_exactly_the_final_twelve_months(
    label: str, schedule: PropertyRentRollSchedule, rentable: float, hold: int
) -> None:
    """Part 14. One projection: the forward window is the tail of the same
    canonical timeline, contiguous with Hold Year H, never smoothed."""

    forward = [m for m in schedule.months if m.is_forward_exit_month]

    assert len(forward) == 12
    assert [m.period_index for m in forward] == list(
        range(12 * hold + 1, 12 * hold + 13)
    )
    assert {m.hold_year for m in forward} == {hold + 1}
    assert schedule.months[12 * hold - 1].is_forward_exit_month is False

    # Contiguous in real calendar terms, with no gap at the boundary.
    sale_month = schedule.months[12 * hold - 1].month_start
    first_forward = forward[0].month_start
    expected_year = sale_month.year + (1 if sale_month.month == 12 else 0)
    expected_month = 1 if sale_month.month == 12 else sale_month.month + 1
    assert first_forward == date(expected_year, expected_month, 1)


@pytest.mark.parametrize(("label", "schedule", "rentable", "hold"), ADVERSARIAL, ids=IDS)
def test_canonical_months_have_no_gap_or_repeat(
    label: str, schedule: PropertyRentRollSchedule, rentable: float, hold: int
) -> None:
    """Part 4. Period indices and calendar months both advance exactly one
    step at a time, and hold years never track the calendar year."""

    indices = [m.period_index for m in schedule.months]
    assert indices == list(range(1, len(indices) + 1))

    for earlier, later in zip(schedule.months, schedule.months[1:]):
        expected_year = earlier.month_start.year + (
            1 if earlier.month_start.month == 12 else 0
        )
        expected_month = (
            1 if earlier.month_start.month == 12 else earlier.month_start.month + 1
        )
        assert later.month_start == date(expected_year, expected_month, 1)
        assert later.hold_year == (later.period_index - 1) // 12 + 1


# =============================================================================
# Escalation adversarial QA  (Part 7)
# =============================================================================


@pytest.mark.parametrize(
    ("commencement_month", "label"),
    [(1, "Jan"), (2, "Feb"), (7, "Jul"), (12, "Dec")],
)
@pytest.mark.parametrize("escalation", [0.0, 0.05, -0.02])
def test_escalation_steps_only_on_the_contractual_anniversary(
    commencement_month: int, label: str, escalation: float
) -> None:
    """The step must land on the lease's own anniversary month, whatever the
    analysis start or the calendar year is doing."""

    analysis_start = date(2027, 1, 1)
    commencement = date(2026, commencement_month, 1)
    schedule = build(
        10_000.0,
        [suite("S", 10_000.0)],
        [
            lease(
                "L", "S", 10_000.0, 24.0, commencement, date(2040, 12, 31),
                escalation_pct=escalation,
                basis=EscalationBasis.LEASE_ANNIVERSARY,
            )
        ],
        analysis_start=analysis_start,
        hold_period=2,
    )

    raw_first = month_index(commencement, analysis_start=analysis_start)
    rent = dict(
        zip((m.period_index for m in schedule.months), schedule.contractual_base_rent)
    )

    for period in range(2, len(schedule.months) + 1):
        k_now = (period - raw_first) // 12
        k_prev = (period - 1 - raw_first) // 12
        changed = rent[period] != rent[period - 1]
        if escalation == 0.0:
            assert not changed, f"{label} flat rent moved at m{period}"
        else:
            assert changed == (k_now != k_prev), (
                f"{label} rent change at m{period} did not match the "
                f"contractual anniversary (k {k_prev} -> {k_now})"
            )


@pytest.mark.parametrize("offset_months", [-1, 0, 1])
def test_acquisition_relative_to_an_anniversary_never_resets_the_step(
    offset_months: int,
) -> None:
    """Acquire one month before, exactly on, and one month after the lease's
    anniversary. The contractual step at Month 1 must depend only on the
    lease, never on when the deal closed."""

    commencement = date(2024, 4, 1)
    anniversary_2027 = 4
    month = anniversary_2027 + offset_months
    analysis_start = date(2027, month, 1)

    schedule = build(
        10_000.0,
        [suite("S", 10_000.0)],
        [
            lease(
                "L", "S", 10_000.0, 30.0, commencement, date(2040, 12, 31),
                escalation_pct=0.03, basis=EscalationBasis.LEASE_ANNIVERSARY,
            )
        ],
        analysis_start=analysis_start,
        hold_period=1,
    )

    raw_first = month_index(commencement, analysis_start=analysis_start)
    expected_k = (1 - raw_first) // 12
    expected = 30.0 * 1.03**expected_k * 10_000.0 / 12.0

    assert schedule.contractual_base_rent[0] == strict(expected)
    # Never the un-escalated original rent: the lease is years into its term.
    assert schedule.contractual_base_rent[0] != strict(25_000.0)


def test_calendar_january_does_not_reset_a_non_january_anniversary() -> None:
    """A July-anniversary lease must not step in January."""

    schedule = build(
        10_000.0,
        [suite("S", 10_000.0)],
        [
            lease(
                "L", "S", 10_000.0, 24.0, date(2027, 7, 1), date(2040, 12, 31),
                escalation_pct=0.10, basis=EscalationBasis.LEASE_ANNIVERSARY,
            )
        ],
        analysis_start=date(2027, 7, 1),
        hold_period=2,
    )
    rent = dict(
        zip((m.period_index for m in schedule.months), schedule.contractual_base_rent)
    )

    assert rent[6] == strict(rent[7])     # Dec-2027 -> Jan-2028: no step
    assert rent[12] != rent[13]           # Jun-2028 -> Jul-2028: steps
    assert rent[18] == strict(rent[19])   # Dec-2028 -> Jan-2029: no step


# =============================================================================
# Date-boundary adversarial QA  (Part 5)
# =============================================================================


@pytest.mark.parametrize(
    ("label", "start", "commencement", "expiration", "expected_code"),
    [
        ("mid-month analysis start", date(2027, 1, 2), date(2027, 1, 1), date(2030, 12, 31),
         LeaseIssueCode.ANALYSIS_START_NOT_MONTH_ALIGNED),
        ("mid-month commencement", date(2027, 1, 1), date(2027, 1, 2), date(2030, 12, 31),
         LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED),
        ("expiration before month end", date(2027, 1, 1), date(2027, 1, 1), date(2030, 12, 30),
         LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED),
        ("expiration before commencement", date(2027, 1, 1), date(2028, 1, 1), date(2027, 12, 31),
         LeaseIssueCode.LEASE_EXPIRES_BEFORE_COMMENCEMENT),
    ],
)
def test_d1_rejects_unsupported_economic_dates(
    label: str, start: date, commencement: date, expiration: date,
    expected_code: LeaseIssueCode,
) -> None:
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(analysis_start_date=start, rentable_area_sf=10_000.0),
        [suite("S", 10_000.0)],
        [lease("L", "S", 10_000.0, 24.0, commencement, expiration)],
    )

    assert expected_code in {issue.code for issue in result.issues}, label
    assert not result.is_valid, label


def test_d1_rejects_same_suite_economic_overlap() -> None:
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(
            analysis_start_date=date(2027, 1, 1), rentable_area_sf=10_000.0
        ),
        [suite("S", 10_000.0)],
        [
            lease("L1", "S", 10_000.0, 24.0, date(2027, 1, 1), date(2028, 6, 30)),
            lease("L2", "S", 10_000.0, 30.0, date(2028, 6, 1), date(2030, 12, 31)),
        ],
    )

    assert LeaseIssueCode.OVERLAPPING_LEASES_IN_SUITE in {i.code for i in result.issues}


@pytest.mark.parametrize(
    ("label", "commencement", "expiration"),
    [
        ("leap month end", date(2028, 1, 1), date(2028, 2, 29)),
        ("non-leap month end", date(2027, 1, 1), date(2027, 2, 28)),
        ("30-day month end", date(2027, 1, 1), date(2027, 4, 30)),
        ("31-day month end", date(2027, 1, 1), date(2027, 12, 31)),
        ("commenced long before analysis", date(2015, 3, 1), date(2035, 2, 28)),
    ],
)
def test_d1_accepts_supported_boundaries(
    label: str, commencement: date, expiration: date
) -> None:
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(
            analysis_start_date=date(2027, 1, 1), rentable_area_sf=10_000.0
        ),
        [suite("S", 10_000.0)],
        [lease("L", "S", 10_000.0, 24.0, commencement, expiration)],
    )

    assert result.is_valid, f"{label}: {[i.code for i in result.errors]}"


def test_back_to_back_leases_produce_no_fake_vacancy() -> None:
    schedule = build(
        10_000.0,
        [suite("S", 10_000.0)],
        [
            lease("L1", "S", 10_000.0, 24.0, date(2027, 1, 1), date(2027, 6, 30)),
            lease("L2", "S", 10_000.0, 30.0, date(2027, 7, 1), date(2040, 12, 31)),
        ],
        analysis_start=date(2027, 1, 1),
        hold_period=1,
    )

    assert set(schedule.vacant_area) == {0.0}
    assert set(schedule.physical_occupancy) == {1.0}


# =============================================================================
# Rent-activity QA  (Part 8)
# =============================================================================


def test_rent_activity_boundaries_in_one_pass() -> None:
    schedule = build(
        10_000.0,
        [suite("S", 10_000.0)],
        [lease("L", "S", 10_000.0, 24.0, date(2027, 4, 1), date(2027, 9, 30))],
        analysis_start=date(2027, 1, 1),
        hold_period=1,
    )
    rent = dict(
        zip((m.period_index for m in schedule.months), schedule.contractual_base_rent)
    )
    occupied = dict(
        zip((m.period_index for m in schedule.months), schedule.occupied_area)
    )

    assert rent[3] == 0.0 and occupied[3] == 0.0        # before commencement
    assert rent[4] == strict(20_000.0)                  # commencement month paid
    assert rent[6] == strict(20_000.0)                  # intermediate
    assert rent[9] == strict(20_000.0)                  # expiration month paid
    assert rent[10] == 0.0 and occupied[10] == 0.0      # after expiration


def test_negative_escalation_does_not_change_activity() -> None:
    declining = build(
        10_000.0,
        [suite("S", 10_000.0)],
        [
            lease(
                "L", "S", 10_000.0, 24.0, date(2027, 1, 1), date(2029, 12, 31),
                escalation_pct=-0.10, basis=EscalationBasis.LEASE_ANNIVERSARY,
            )
        ],
        analysis_start=date(2027, 1, 1),
        hold_period=2,
    )

    assert set(declining.occupied_area) == {10_000.0}
    assert declining.contractual_base_rent[12] < declining.contractual_base_rent[0]
    assert all(amount > 0.0 for amount in declining.contractual_base_rent)


# =============================================================================
# Flow vs state  (Part 13)
# =============================================================================


def test_a_state_series_summed_as_a_flow_is_visibly_wrong() -> None:
    """The two aggregators are distinct functions with distinct names. Passing
    a state series to the flow aggregator is not prevented by the type system,
    so this documents exactly how wrong the answer would be -- a twelvefold
    overstatement -- and pins the correct helpers."""

    schedule = master_case()
    occupancy = schedule.physical_occupancy

    misused = aggregate_flow_to_annual(occupancy, hold_period=MASTER_HOLD)
    correct_average = average_state_over_year(occupancy, hold_period=MASTER_HOLD)
    correct_year_end = snapshot_state_at_year_end(occupancy, hold_period=MASTER_HOLD)

    assert misused[0] == strict(9.6)          # meaningless: 12x an occupancy
    assert misused[0] > 1.0                   # obviously not an occupancy
    assert correct_average[0] == strict(0.80)
    assert correct_year_end[0] == strict(0.90)
    assert misused[0] == strict(correct_average[0] * 12)


def test_flow_and_state_helpers_are_separate_named_functions() -> None:
    """FM-7 / FM-8: the aggregators cannot be confused by accident because
    each is named for what it does."""

    from anchor.leasing import aggregation

    for name in (
        "aggregate_flow_to_annual",
        "aggregate_flow_over_forward_exit_window",
        "snapshot_state_at_year_end",
        "average_state_over_year",
    ):
        assert callable(getattr(aggregation, name))


# =============================================================================
# Determinism and immutability  (Parts 15, 16)
# =============================================================================


def test_the_master_build_is_bit_identical_across_repeats() -> None:
    first = master_case()

    for _ in range(25):
        repeat = master_case()
        assert repeat == first
        assert repeat.contractual_base_rent == first.contractual_base_rent
        assert repeat.occupied_area == first.occupied_area


def test_lease_declaration_order_does_not_change_any_total() -> None:
    suites = [suite("A", 20_000.0), suite("B", 15_000.0), suite("C", 10_000.0), suite("D", 5_000.0)]
    leases = [
        lease("L1", "A", 20_000.0, 30.0, date(2025, 7, 1), date(2035, 6, 30),
              escalation_pct=0.04, basis=EscalationBasis.LEASE_ANNIVERSARY),
        lease("L2", "B", 15_000.0, 24.0, date(2026, 1, 1), date(2028, 6, 30)),
        lease("L3", "B", 15_000.0, 27.0, date(2029, 1, 1), date(2034, 12, 31)),
        lease("L4", "C", 10_000.0, 0.0, date(2028, 1, 1), date(2033, 12, 31)),
    ]

    forward_order = build(MASTER_RENTABLE, suites, leases,
                          analysis_start=MASTER_START, hold_period=MASTER_HOLD)
    reversed_order = build(MASTER_RENTABLE, suites, list(reversed(leases)),
                           analysis_start=MASTER_START, hold_period=MASTER_HOLD)

    for position in range(len(forward_order.months)):
        assert forward_order.contractual_base_rent[position] == strict(
            reversed_order.contractual_base_rent[position]
        )
        assert forward_order.occupied_area[position] == strict(
            reversed_order.occupied_area[position]
        )


def test_the_full_build_mutates_none_of_its_inputs() -> None:
    inputs = LeaseLevelPropertyInputs(
        analysis_start_date=MASTER_START, rentable_area_sf=MASTER_RENTABLE
    )
    suites = [suite("A", 30_000.0), suite("B", 20_000.0)]
    leases = [
        lease("L1", "A", 30_000.0, 24.0, date(2026, 1, 1), date(2035, 12, 31)),
        lease("L2", "B", 20_000.0, 30.0, date(2028, 1, 1), date(2035, 12, 31)),
    ]
    months = build_model_months(analysis_start=MASTER_START, hold_period=MASTER_HOLD)

    snapshot = (inputs, list(suites), list(leases), months)
    schedule = build_property_rent_roll_schedule(
        inputs, suites, leases, hold_period=MASTER_HOLD
    )

    assert inputs == snapshot[0]
    assert suites == snapshot[1]
    assert leases == snapshot[2]
    assert months == snapshot[3]

    # Outputs are immutable too.
    with pytest.raises(dataclasses.FrozenInstanceError):
        schedule.occupied_area = ()  # type: ignore[misc]
    for lease_schedule in schedule.lease_schedules:
        with pytest.raises(dataclasses.FrozenInstanceError):
            lease_schedule.contractual_base_rent = ()  # type: ignore[misc]


def test_the_engine_reads_no_clock_and_no_environment() -> None:
    """Determinism means the same inputs give the same outputs on any machine,
    at any time. No leasing module may import a clock, a random source, an
    environment reader, or an I/O facility."""

    import ast
    from pathlib import Path

    leasing_dir = Path(__file__).resolve().parents[1] / "src" / "anchor" / "leasing"
    banned = {"random", "os", "time", "secrets", "uuid", "pathlib", "socket", "requests"}

    for source_file in sorted(leasing_dir.glob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module.split(".")[0]]
            assert not set(names) & banned, f"{source_file} imports {names}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"now", "today", "utcnow"}, (
                    f"{source_file} reads a clock"
                )


# =============================================================================
# Scale sanity  (Part 27)
# =============================================================================


def test_a_hundred_suite_ten_year_property_builds_deterministically() -> None:
    """100 suites, 100 non-overlapping leases, 10-year hold = 132 canonical
    months. A sanity check that the shape is workable, not a benchmark."""

    suites = [suite(f"S{i:03d}", 1_000.0) for i in range(100)]
    leases = [
        lease(
            f"L{i:03d}", f"S{i:03d}", 1_000.0, 20.0 + i % 15,
            date(2020 + i % 7, 1 + i % 12, 1),
            # Beyond model month 132, so every suite stays occupied for the
            # whole horizon and the invariants below are unambiguous.
            date(2045, 12, 31),
            escalation_pct=0.02 + (i % 4) / 100.0,
            basis=EscalationBasis.LEASE_ANNIVERSARY,
        )
        for i in range(100)
    ]

    started = time.perf_counter()
    schedule = build(
        100_000.0, suites, leases, analysis_start=date(2027, 1, 1), hold_period=10
    )
    elapsed = time.perf_counter() - started

    assert len(schedule.months) == 132
    assert len(schedule.lease_schedules) == 100
    assert set(schedule.occupied_area) == {100_000.0}
    assert set(schedule.vacant_area) == {0.0}

    annual = aggregate_flow_to_annual(schedule.contractual_base_rent, hold_period=10)
    forward = aggregate_flow_over_forward_exit_window(
        schedule.contractual_base_rent, hold_period=10
    )
    assert len(annual) == 10
    # Relative, not the usual absolute 1e-9: see
    # test_reconciliation_tolerance_is_magnitude_dependent below. At a
    # ~$40M total the two summation groupings differ by exactly one ULP,
    # which is 7.45e-09 -- larger than 1e-9 and entirely correct.
    assert sum(annual) + forward == pytest.approx(
        sum(schedule.contractual_base_rent), rel=1e-12, abs=0.0
    )

    # Deterministic at scale, and comfortably fast. The bound is loose on
    # purpose: this asserts "no pathological behaviour", not a performance
    # target, so it will not flake on a slow machine.
    assert build(
        100_000.0, suites, leases, analysis_start=date(2027, 1, 1), hold_period=10
    ) == schedule
    assert elapsed < 5.0, f"took {elapsed:.3f}s"


# =============================================================================
# Numeric-tolerance characterisation
# =============================================================================


def test_reconciliation_tolerance_is_magnitude_dependent() -> None:
    """A characterisation test, recording a real property of the reconciliation
    invariant rather than asserting a policy.

    ``sum(annual) + forward`` and ``sum(monthly)`` associate the same addends
    differently, so they may differ by an ULP or two. That is correct IEEE-754
    behaviour, not a defect -- but it means D0's ``abs=1e-9`` reconciliation
    tolerance is only meaningful while totals stay below roughly
    ``1e-9 / 2.22e-16``, about $4.5M. Every D1 golden case is far below that,
    so ``abs=1e-9`` remains the right assertion for them.

    It is recorded here because D4 aggregates NOI and cash flows for a real
    property, where annual totals routinely exceed that magnitude. The
    reconciliation guardrail G-M4 should then assert a relative tolerance, or
    an explicit ULP bound, rather than a fixed absolute one.
    """

    import math

    schedule = master_case()
    monthly = schedule.contractual_base_rent

    # At the master case's magnitude (~$1M/yr) the absolute convention holds.
    regrouped = sum(
        aggregate_flow_to_annual(monthly, hold_period=MASTER_HOLD)
    ) + aggregate_flow_over_forward_exit_window(monthly, hold_period=MASTER_HOLD)
    assert regrouped == strict(sum(monthly))

    # The bound itself: a difference of a few ULP is the most that regrouping
    # can produce, at any magnitude.
    scaled = tuple(value * 40.0 for value in monthly)
    scaled_regrouped = sum(
        aggregate_flow_to_annual(scaled, hold_period=MASTER_HOLD)
    ) + aggregate_flow_over_forward_exit_window(scaled, hold_period=MASTER_HOLD)
    difference = abs(scaled_regrouped - sum(scaled))
    assert difference <= 4 * math.ulp(sum(scaled))
    assert scaled_regrouped == pytest.approx(sum(scaled), rel=1e-12, abs=0.0)


# =============================================================================
# D1 scope boundaries  (Parts 25, 26)
# =============================================================================


def test_d1_exposes_no_downstream_financial_concept() -> None:
    """D1 is contractual rent and occupancy. Nothing else."""

    import anchor.leasing as leasing

    for absent in (
        "noi", "exit_noi", "irr", "equity_multiple", "dscr", "debt_yield",
        "sale_proceeds", "purchase_price", "acquisition_costs", "capex",
        "unlevered_cash_flows", "levered_cash_flows",
    ):
        assert not any(
            name.lower() == absent for name in dir(leasing)
        ), f"{absent} must not exist in D1"


def test_no_contract_declares_a_d2_2_or_downstream_field() -> None:
    """**Narrowed at D2.1**, and only by the two fields that gate delivers.

    ``market_rent_psf`` and ``market_rent_growth`` were removed from the
    banned set when ``MarketLeasingAssumptions`` landed. Everything D2.2 and
    later owns -- renewal, successors, downtime, free rent, TI, LC, recovery
    structure and every downstream operating concept -- remains banned, so
    this guardrail keeps its full force over the rest of Sprint D.
    """

    from anchor.leasing import contracts as contracts_module

    banned = {
        "renewal_probability",
        "successor", "downtime_months", "free_rent_months", "ti_psf",
        "tenant_improvements", "lc_pct", "leasing_commissions",
        "recovery_basis", "expense_stop", "base_year", "origin",
        "noi", "capex", "other_income", "operating_expenses",
        "vacancy_credit_loss_pct", "occupancy", "credit_loss_pct",
    }

    for name in dir(contracts_module):
        obj = getattr(contracts_module, name)
        if not dataclasses.is_dataclass(obj):
            continue
        declared = {f.name for f in dataclasses.fields(obj)}
        leaked = declared & banned
        assert not leaked, f"{name} declares out-of-scope fields: {sorted(leaked)}"


def test_the_d1_rent_formula_is_untouched_by_d2_1() -> None:
    """Failure mode FM-D2-20 stated as a source-level assertion:
    ``Lease.base_rent_psf``'s meaning and ``rent.py``'s formula must be
    untouched by D2.

    The D1.2 formula ``base_rent_psf * (1 + escalation_pct) ** k * area / 12``
    is asserted verbatim in structure, and the market-rent module is proven
    absent from ``rent.py``'s imports."""

    from anchor.leasing import rent as rent_module

    source = pathlib.Path(rent_module.__file__).read_text(encoding="utf-8")

    assert "annual_rent_psf = base_rent_psf * (1 + escalation_pct) ** escalation_index" in source
    assert "annual_rent_psf * leased_area_sf / 12.0" in source
    assert "from .market import" not in source
    assert "market_rent_psf" not in source
    assert "market_rent_growth" not in source
