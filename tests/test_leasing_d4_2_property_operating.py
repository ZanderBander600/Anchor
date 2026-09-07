"""Sprint D Gate D4.2 -- suite operating projections and property aggregation.

Governed by
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 2.8, 2.10, 2.11, 16.1 and 29.

D4.2 answers "what are the completed monthly leasing economics of the
property", and nothing else. The claims that fail silently if wrong:

- **cash base rent is carried, never rebuilt.** In a fractional-downtime month
  ``contractual - free_rent`` exceeds cash rent by the portion of the month
  nobody occupied, so rebuilding it recognises vacancy as revenue (HD-D4-5);
- **occupancy is an area quotient, computed once at the property level.**
  Averaging suite percentages is wrong the moment two suites differ in size;
- **economic responsibility and physical occupancy are different quantities.**
  A tenant taking possession three-quarters of the way through a month pays
  three-quarters of the rent and occupies the whole suite;
- **every suite appears exactly once**, including a deliberately empty one, so
  a modelled zero never looks like an omission (D3.6);
- **the full chain projects**, not the first rollover and not the successors
  alone;
- **the forward window survives**, TI and LC included, because whose cash flow
  those are is D4.4/D4.5's question and not this gate's.
"""

from __future__ import annotations

import dataclasses
import itertools
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseIssueCode,
    LeaseType,
    LeasingCommissionMethod,
    LeaseValidationError,
    MarketLeasingAssumptions,
    ModelMonth,
    PropertyOperatingSchedule,
    Suite,
    SuiteOperatingProjection,
    build_expected_rollover,
    build_initial_vacancy_rollover,
    build_model_months,
    build_property_operating_schedule,
    build_recursive_rollover,
    suite_operating_projection,
    validate_property_operating_inputs,
)


# =============================================================================
# Fixtures
# =============================================================================


JAN = date(2027, 1, 1)
HOLD = 3
PROPERTY_AREA = 100_000.0


def months(*, hold_period: int = HOLD, analysis_start: date = JAN) -> tuple[ModelMonth, ...]:
    return build_model_months(analysis_start=analysis_start, hold_period=hold_period)


MONTHS = months()


def hexes(values: tuple[float, ...]) -> list[str]:
    return [value.hex() for value in values]


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    base: dict[str, object] = {
        "market_rent_psf": 120.0,
        "market_rent_growth": 0.0,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 12,
        "successor_escalation_pct": 0.0,
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 0.0,
        "new_term_months": 12,
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


def occupied_suite(suite_id: str = "A", *, area: float = 40_000.0) -> Suite:
    return Suite(suite_id=suite_id, suite_area_sf=area)


def lease_for(
    suite: Suite,
    *,
    end: date = date(2035, 12, 31),
    base_rent_psf: float = 12.0,
) -> Lease:
    return Lease(
        lease_id=f"L-{suite.suite_id}",
        suite_id=suite.suite_id,
        leased_area_sf=suite.suite_area_sf,
        rent_commencement_date=date(2025, 1, 1),
        lease_expiration_date=end,
        base_rent_psf=base_rent_psf,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=LeaseType.NNN,
    )


def lease_up_suite(
    suite_id: str = "B", *, area: float = 30_000.0, lease_up: float = 0.0
) -> Suite:
    return Suite(
        suite_id=suite_id,
        suite_area_sf=area,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP,
            initial_lease_up_months=lease_up,
        ),
    )


def hold_vacant_suite(suite_id: str = "C", *, area: float = 20_000.0) -> Suite:
    return Suite(
        suite_id=suite_id,
        suite_area_sf=area,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.HOLD_VACANT, initial_lease_up_months=None
        ),
    )


def occupied_chain(
    suite: Suite,
    lease: Lease,
    *,
    timeline: tuple[ModelMonth, ...] = MONTHS,
    **assumption_overrides: object,
):
    return build_recursive_rollover(
        lease,
        suite=suite,
        analysis_start=timeline[0].month_start,
        months=timeline,
        property_defaults=assumptions(**assumption_overrides),
    )


def vacant_chain(
    suite: Suite,
    *,
    timeline: tuple[ModelMonth, ...] = MONTHS,
    **assumption_overrides: object,
):
    return build_initial_vacancy_rollover(
        suite,
        analysis_start=timeline[0].month_start,
        months=timeline,
        property_defaults=assumptions(**assumption_overrides),
    )


def synthetic(
    suite_id: str,
    area: float,
    *,
    timeline: tuple[ModelMonth, ...] = MONTHS,
    contractual: float = 0.0,
    cash: float = 0.0,
    free_rent: float = 0.0,
    ti: float = 0.0,
    lc: float = 0.0,
    occupied: float | None = None,
    event_month: int | None = None,
) -> SuiteOperatingProjection:
    """A hand-specified projection, for the pure-arithmetic goldens.

    ``event_month`` (1-based) places TI and LC in exactly one month, the way a
    real chain does; otherwise they are level.
    """

    count = len(timeline)
    occupied_sf = area if occupied is None else occupied

    def flow(value: float) -> tuple[float, ...]:
        return tuple(value for _ in range(count))

    def event(value: float) -> tuple[float, ...]:
        if event_month is None:
            return flow(value)
        return tuple(
            value if index == event_month - 1 else 0.0 for index in range(count)
        )

    return SuiteOperatingProjection(
        suite_id=suite_id,
        suite_area_sf=area,
        months=timeline,
        contractual_base_rent=flow(contractual),
        cash_base_rent=flow(cash),
        free_rent=flow(free_rent),
        tenant_improvements=event(ti),
        leasing_commissions=event(lc),
        occupied_area_sf=flow(occupied_sf),
    )


def schedule_for(
    projections, suites, *, timeline: tuple[ModelMonth, ...] = MONTHS, leases=None
) -> PropertyOperatingSchedule:
    return build_property_operating_schedule(
        projections,
        suites,
        months=timeline,
        rentable_area_sf=PROPERTY_AREA,
        leases=leases,
    )


# =============================================================================
# G1 -- occupied suite, full-chain projection identity
# =============================================================================


def test_g1_an_occupied_suite_projects_its_full_chain_bit_for_bit() -> None:
    suite = occupied_suite(area=40_000.0)
    lease = lease_for(suite, end=date(2028, 12, 31))
    chain = occupied_chain(suite, lease)

    projection = suite_operating_projection(suite, chain)

    assert hexes(projection.contractual_base_rent) == hexes(
        chain.expected_contractual_base_rent
    )
    assert hexes(projection.cash_base_rent) == hexes(chain.expected_cash_base_rent)
    assert hexes(projection.free_rent) == hexes(chain.expected_free_rent)
    assert hexes(projection.tenant_improvements) == hexes(
        chain.expected_tenant_improvements
    )
    assert hexes(projection.leasing_commissions) == hexes(
        chain.expected_leasing_commissions
    )
    assert hexes(projection.occupied_area_sf) == hexes(
        chain.expected_occupied_area_sf
    )


def test_g1_the_projection_carries_the_in_place_lease_not_only_successors() -> None:
    """The chain is seeded with the known lease's own economics. A
    successor-only projection would be zero before the first expiry."""

    suite = occupied_suite(area=40_000.0)
    lease = lease_for(suite, end=date(2028, 12, 31))

    projection = suite_operating_projection(suite, occupied_chain(suite, lease))

    # 40,000 SF at $12.00/SF/year is $40,000 a month, live from month 1.
    assert projection.contractual_base_rent[0] == pytest.approx(40_000.0, abs=1e-9)
    assert projection.cash_base_rent[0] == pytest.approx(40_000.0, abs=1e-9)


def test_g1_the_projection_carries_the_suite_identity_and_area() -> None:
    suite = occupied_suite(area=40_000.0)
    projection = suite_operating_projection(
        suite, occupied_chain(suite, lease_for(suite))
    )

    assert projection.suite_id == "A"
    assert projection.suite_area_sf == 40_000.0
    assert projection.months is MONTHS


# =============================================================================
# G2 -- market lease-up, full-chain projection identity
# =============================================================================


def test_g2_a_market_lease_up_suite_projects_its_full_chain_bit_for_bit() -> None:
    suite = lease_up_suite(area=30_000.0, lease_up=6.0)
    chain = vacant_chain(suite)

    projection = suite_operating_projection(suite, chain)

    assert hexes(projection.contractual_base_rent) == hexes(
        chain.expected_contractual_base_rent
    )
    assert hexes(projection.cash_base_rent) == hexes(chain.expected_cash_base_rent)
    assert hexes(projection.occupied_area_sf) == hexes(
        chain.expected_occupied_area_sf
    )


def test_g2_the_lease_up_months_are_zero_and_the_tenant_then_appears() -> None:
    suite = lease_up_suite(area=30_000.0, lease_up=6.0)

    projection = suite_operating_projection(suite, vacant_chain(suite))

    assert projection.cash_base_rent[:6] == tuple(0.0 for _ in range(6))
    assert projection.occupied_area_sf[:6] == tuple(0.0 for _ in range(6))
    assert projection.cash_base_rent[6] > 0.0
    assert projection.occupied_area_sf[6] == pytest.approx(30_000.0, abs=1e-9)


# =============================================================================
# G3 -- HOLD_VACANT stays explicit
# =============================================================================


def test_g3_a_hold_vacant_suite_projects_an_explicit_all_zero_chain() -> None:
    suite = hold_vacant_suite(area=20_000.0)

    projection = suite_operating_projection(suite, vacant_chain(suite))

    for series in (
        projection.contractual_base_rent,
        projection.cash_base_rent,
        projection.free_rent,
        projection.tenant_improvements,
        projection.leasing_commissions,
        projection.occupied_area_sf,
    ):
        assert series == tuple(0.0 for _ in MONTHS)


def test_g3_a_hold_vacant_suite_keeps_its_identity_and_area() -> None:
    """Deliberate vacancy is visible, never a missing row."""

    suite = hold_vacant_suite(area=20_000.0)

    projection = suite_operating_projection(suite, vacant_chain(suite))

    assert projection.suite_id == "C"
    assert projection.suite_area_sf == 20_000.0
    assert len(projection.months) == len(MONTHS)


def test_g3_a_hold_vacant_suite_appears_in_the_property_schedule() -> None:
    empty = hold_vacant_suite("C", area=100_000.0)

    schedule = schedule_for(
        [suite_operating_projection(empty, vacant_chain(empty))], [empty]
    )

    assert [p.suite_id for p in schedule.suite_projections] == ["C"]


# =============================================================================
# G4 -- the mandatory fractional-downtime cash-rent proof (HD-D4-5)
# =============================================================================


def _fractional_commencement_property():
    """10,000 SF at $120/SF/year is $100,000 a month. A 0.25-month lease-up
    puts commencement in month 1 with economic responsibility ``1 - 0.25``."""

    suite = lease_up_suite("X", area=10_000.0, lease_up=0.25)
    chain = vacant_chain(suite)
    return suite, chain, suite_operating_projection(suite, chain)


def test_g4_fractional_responsibility_produces_three_quarter_cash_rent() -> None:
    _, _, projection = _fractional_commencement_property()

    assert projection.contractual_base_rent[0] == pytest.approx(100_000.0, abs=1e-9)
    assert projection.free_rent[0] == 0.0
    assert projection.cash_base_rent[0] == pytest.approx(75_000.0, abs=1e-9)


def test_g4_the_explanatory_gap_is_the_downtime_quarter() -> None:
    """"Absent rent" is a reconciliation concept only -- derived here, in a
    test, and declared on no production contract (HD-D4-5 as narrowed)."""

    _, _, projection = _fractional_commencement_property()

    gap = (
        projection.contractual_base_rent[0]
        - projection.free_rent[0]
        - projection.cash_base_rent[0]
    )
    assert gap == pytest.approx(25_000.0, abs=1e-9)


def test_g4_property_cash_rent_is_seventy_five_thousand_not_one_hundred() -> None:
    """The whole point of HD-D4-5. Rebuilding cash rent as
    ``contractual - free_rent`` would report ``100,000`` of collected revenue
    in a month whose tenant paid ``75,000``."""

    suite, _, projection = _fractional_commencement_property()

    schedule = build_property_operating_schedule(
        [projection], [suite], months=MONTHS, rentable_area_sf=10_000.0
    )

    assert schedule.cash_base_rent[0] == pytest.approx(75_000.0, abs=1e-9)
    assert schedule.cash_base_rent[0] != pytest.approx(100_000.0, abs=1e-3)
    assert schedule.contractual_base_rent[0] == pytest.approx(100_000.0, abs=1e-9)


def test_g4_the_gap_is_zero_when_downtime_is_integral() -> None:
    """The identity ``contractual - free == cash`` holds wherever no fractional
    absence exists -- which is why it is not asserted as a universal property
    invariant."""

    suite = lease_up_suite("X", area=10_000.0, lease_up=2.0)

    projection = suite_operating_projection(suite, vacant_chain(suite))

    for index in range(len(MONTHS)):
        gap = (
            projection.contractual_base_rent[index]
            - projection.free_rent[index]
            - projection.cash_base_rent[index]
        )
        assert gap == pytest.approx(0.0, abs=1e-9)


# =============================================================================
# G5 -- fractional commencement keeps physical occupancy integral
# =============================================================================


def test_g5_a_fractional_commencement_month_is_fully_occupied() -> None:
    """Economic responsibility ``0.75``; physical occupancy ``1.0``. The tenant
    is in possession by month end (D2 HD-D2-2)."""

    suite, chain, projection = _fractional_commencement_property()

    assert chain.expected_successor_occupancy_factor[0] == pytest.approx(
        0.75, abs=1e-12
    )
    assert projection.occupied_area_sf[0] == pytest.approx(10_000.0, abs=1e-9)


def test_g5_property_occupancy_in_that_month_is_one_not_three_quarters() -> None:
    suite, _, projection = _fractional_commencement_property()

    schedule = build_property_operating_schedule(
        [projection], [suite], months=MONTHS, rentable_area_sf=10_000.0
    )

    assert schedule.physical_occupancy[0] == pytest.approx(1.0, abs=1e-12)
    assert schedule.vacant_area_sf[0] == pytest.approx(0.0, abs=1e-9)


# =============================================================================
# G6 -- mixed-size occupancy
# =============================================================================


def test_g6_mixed_size_occupancy_is_ninety_percent_not_fifty() -> None:
    """The load-bearing case. Averaging suite percentages would give ``0.50``;
    the area quotient gives ``0.90``."""

    big = occupied_suite("A", area=90_000.0)
    small = hold_vacant_suite("B", area=10_000.0)
    lease = lease_for(big)

    schedule = schedule_for(
        [
            suite_operating_projection(big, occupied_chain(big, lease)),
            suite_operating_projection(small, vacant_chain(small)),
        ],
        [big, small],
        leases=[lease],
    )

    assert schedule.occupied_area_sf[0] == pytest.approx(90_000.0, abs=1e-9)
    assert schedule.vacant_area_sf[0] == pytest.approx(10_000.0, abs=1e-9)
    assert schedule.physical_occupancy[0] == pytest.approx(0.90, abs=1e-12)
    assert schedule.physical_occupancy[0] != pytest.approx(0.50, abs=1e-3)


def test_g6_occupied_and_vacant_area_reconcile_in_every_month() -> None:
    big = occupied_suite("A", area=90_000.0)
    small = hold_vacant_suite("B", area=10_000.0)
    lease = lease_for(big)

    schedule = schedule_for(
        [
            suite_operating_projection(big, occupied_chain(big, lease)),
            suite_operating_projection(small, vacant_chain(small)),
        ],
        [big, small],
        leases=[lease],
    )

    for index in range(len(MONTHS)):
        assert schedule.occupied_area_sf[index] + schedule.vacant_area_sf[
            index
        ] == pytest.approx(PROPERTY_AREA, abs=1e-9)


# =============================================================================
# G7 / G8 -- property rent aggregation
# =============================================================================


def test_g7_property_cash_rent_is_the_sum_of_suite_cash_rent() -> None:
    suites = [
        occupied_suite("A", area=50_000.0),
        occupied_suite("B", area=30_000.0),
        hold_vacant_suite("C", area=20_000.0),
    ]
    projections = [
        synthetic("A", 50_000.0, cash=100_000.0, contractual=100_000.0),
        synthetic("B", 30_000.0, cash=50_000.0, contractual=50_000.0),
        synthetic("C", 20_000.0, occupied=0.0),
    ]

    schedule = schedule_for(projections, suites)

    assert schedule.cash_base_rent[0] == pytest.approx(150_000.0, abs=1e-9)


def test_g8_contractual_free_and_cash_are_three_independent_series() -> None:
    """Suite A abates a quarter of its rent; suite B does not. The property
    reports all three lines from the suites' own finished values."""

    suites = [occupied_suite("A", area=60_000.0), occupied_suite("B", area=40_000.0)]
    projections = [
        synthetic(
            "A", 60_000.0, contractual=100_000.0, free_rent=25_000.0, cash=75_000.0
        ),
        synthetic("B", 40_000.0, contractual=50_000.0, free_rent=0.0, cash=50_000.0),
    ]

    schedule = schedule_for(projections, suites)

    assert schedule.contractual_base_rent[0] == pytest.approx(150_000.0, abs=1e-9)
    assert schedule.free_rent[0] == pytest.approx(25_000.0, abs=1e-9)
    assert schedule.cash_base_rent[0] == pytest.approx(125_000.0, abs=1e-9)


def test_g8_free_rent_is_never_subtracted_from_cash_rent_again() -> None:
    """Free rent already reduced cash rent inside the chain. Property cash rent
    equals the sum of suite cash rent, untouched."""

    suites = [occupied_suite("A", area=100_000.0)]
    projections = [
        synthetic(
            "A", 100_000.0, contractual=100_000.0, free_rent=25_000.0, cash=75_000.0
        )
    ]

    schedule = schedule_for(projections, suites)

    assert schedule.cash_base_rent[0] == pytest.approx(75_000.0, abs=1e-9)
    assert schedule.cash_base_rent[0] != pytest.approx(50_000.0, abs=1e-3)


def test_g8_a_free_rent_tenant_is_still_physically_occupying() -> None:
    suites = [occupied_suite("A", area=100_000.0)]
    projections = [
        synthetic(
            "A", 100_000.0, contractual=100_000.0, free_rent=100_000.0, cash=0.0
        )
    ]

    schedule = schedule_for(projections, suites)

    assert schedule.cash_base_rent[0] == 0.0
    assert schedule.physical_occupancy[0] == pytest.approx(1.0, abs=1e-12)


# =============================================================================
# G9 / G10 -- leasing costs
# =============================================================================


def test_g9_property_ti_is_the_sum_of_suite_ti_in_that_month() -> None:
    suites = [occupied_suite("A", area=60_000.0), occupied_suite("B", area=40_000.0)]
    projections = [
        synthetic("A", 60_000.0, ti=100_000.0, lc=50_000.0, event_month=7),
        synthetic("B", 40_000.0, ti=20_000.0, lc=10_000.0, event_month=7),
    ]

    schedule = schedule_for(projections, suites)

    assert schedule.tenant_improvements[6] == pytest.approx(120_000.0, abs=1e-9)
    assert schedule.tenant_improvements[5] == 0.0


def test_g10_property_lc_is_the_sum_of_suite_lc_in_that_month() -> None:
    suites = [occupied_suite("A", area=60_000.0), occupied_suite("B", area=40_000.0)]
    projections = [
        synthetic("A", 60_000.0, ti=100_000.0, lc=50_000.0, event_month=7),
        synthetic("B", 40_000.0, ti=20_000.0, lc=10_000.0, event_month=7),
    ]

    schedule = schedule_for(projections, suites)

    assert schedule.leasing_commissions[6] == pytest.approx(60_000.0, abs=1e-9)
    assert schedule.leasing_commissions[5] == 0.0


def test_g9_g10_leasing_costs_never_touch_rent_or_occupancy() -> None:
    """TI and LC are below NOI and are carried, not netted. Doubling them
    leaves every rent and area figure bit-identical."""

    suites = [occupied_suite("A", area=100_000.0)]
    base = schedule_for(
        [synthetic("A", 100_000.0, contractual=90.0, cash=90.0, ti=1.0, lc=2.0)],
        suites,
    )
    doubled = schedule_for(
        [synthetic("A", 100_000.0, contractual=90.0, cash=90.0, ti=2.0, lc=4.0)],
        suites,
    )

    assert hexes(base.cash_base_rent) == hexes(doubled.cash_base_rent)
    assert hexes(base.contractual_base_rent) == hexes(doubled.contractual_base_rent)
    assert hexes(base.occupied_area_sf) == hexes(doubled.occupied_area_sf)
    assert hexes(base.physical_occupancy) == hexes(doubled.physical_occupancy)
    assert base.tenant_improvements != doubled.tenant_improvements


# =============================================================================
# G11 -- a mixed-structure property
# =============================================================================


def _mixed_property():
    """40k occupied, 30k lease-up, 20k hold-vacant, 10k occupied with a
    different rollover date and a different renewal probability."""

    a = occupied_suite("A", area=40_000.0)
    b = lease_up_suite("B", area=30_000.0, lease_up=4.0)
    c = hold_vacant_suite("C", area=20_000.0)
    d = occupied_suite("D", area=10_000.0)

    lease_a = lease_for(a, end=date(2028, 6, 30))
    lease_d = lease_for(d, end=date(2029, 3, 31), base_rent_psf=18.0)

    projections = [
        suite_operating_projection(a, occupied_chain(a, lease_a, renewal_probability=0.8)),
        suite_operating_projection(b, vacant_chain(b)),
        suite_operating_projection(c, vacant_chain(c)),
        suite_operating_projection(d, occupied_chain(d, lease_d, renewal_probability=0.2)),
    ]
    return [a, b, c, d], [lease_a, lease_d], projections


def test_g11_a_mixed_property_aggregates_all_four_suite_kinds() -> None:
    suites, leases, projections = _mixed_property()

    schedule = schedule_for(projections, suites, leases=leases)

    assert len(schedule.suite_projections) == 4
    assert [p.suite_id for p in schedule.suite_projections] == ["A", "B", "C", "D"]
    assert len(schedule.months) == 12 * HOLD + 12


def test_g11_every_property_month_equals_the_suite_sum() -> None:
    suites, leases, projections = _mixed_property()

    schedule = schedule_for(projections, suites, leases=leases)

    for index in range(len(MONTHS)):
        for name in (
            "contractual_base_rent",
            "cash_base_rent",
            "free_rent",
            "tenant_improvements",
            "leasing_commissions",
            "occupied_area_sf",
        ):
            expected = sum(
                getattr(projection, name)[index] for projection in projections
            )
            assert getattr(schedule, name)[index] == pytest.approx(
                expected, abs=1e-9
            ), f"{name} at month {index + 1}"


def test_g11_the_hold_vacant_suite_contributes_exactly_zero_but_must_be_present() -> None:
    """Its zeros change no total -- and it is still required, because a
    modelled zero and an omission must stay distinguishable (D3.6)."""

    suites, leases, projections = _mixed_property()

    schedule = schedule_for(projections, suites, leases=leases)
    without_c = schedule_for(
        [p for p in projections if p.suite_id != "C"],
        [s for s in suites if s.suite_id != "C"],
        leases=leases,
    )

    assert hexes(schedule.cash_base_rent) == hexes(without_c.cash_base_rent)
    assert hexes(schedule.occupied_area_sf) == hexes(without_c.occupied_area_sf)

    # Dropping the projection while the suite remains is refused outright.
    with pytest.raises(LeaseValidationError):
        schedule_for(
            [p for p in projections if p.suite_id != "C"], suites, leases=leases
        )


def test_g11_property_occupancy_never_exceeds_one_or_falls_below_zero() -> None:
    suites, leases, projections = _mixed_property()

    schedule = schedule_for(projections, suites, leases=leases)

    for value in schedule.physical_occupancy:
        assert 0.0 <= value <= 1.0 + 1e-12


# =============================================================================
# G12 -- different renewal probabilities
# =============================================================================


def test_g12_two_suites_with_different_renewal_probabilities_simply_sum() -> None:
    a = occupied_suite("A", area=60_000.0)
    d = occupied_suite("D", area=40_000.0)
    lease_a = lease_for(a, end=date(2028, 6, 30))
    lease_d = lease_for(d, end=date(2028, 6, 30))

    chain_a = occupied_chain(a, lease_a, renewal_probability=0.9)
    chain_d = occupied_chain(d, lease_d, renewal_probability=0.1)

    schedule = schedule_for(
        [
            suite_operating_projection(a, chain_a),
            suite_operating_projection(d, chain_d),
        ],
        [a, d],
        leases=[lease_a, lease_d],
    )

    for index in range(len(MONTHS)):
        assert schedule.cash_base_rent[index] == pytest.approx(
            chain_a.expected_cash_base_rent[index]
            + chain_d.expected_cash_base_rent[index],
            abs=1e-9,
        )


def test_g12_no_property_level_renewal_probability_is_published() -> None:
    """There is no such thing as a property renewal probability."""

    suites, leases, projections = _mixed_property()

    schedule = schedule_for(projections, suites, leases=leases)

    fields = {field.name for field in dataclasses.fields(PropertyOperatingSchedule)}
    assert "renewal_probability" not in fields
    assert not hasattr(schedule, "renewal_probability")

    projection_fields = {
        field.name for field in dataclasses.fields(SuiteOperatingProjection)
    }
    assert "renewal_probability" not in projection_fields


# =============================================================================
# G13-G17 -- refusals
# =============================================================================


def test_g13_a_duplicate_suite_projection_is_refused() -> None:
    suite = occupied_suite("A", area=100_000.0)
    projection = synthetic("A", 100_000.0, cash=1.0)

    with pytest.raises(LeaseValidationError) as raised:
        schedule_for([projection, projection], [suite])

    assert LeaseIssueCode.DUPLICATE_SUITE_ID in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g14_an_unknown_suite_projection_is_refused() -> None:
    suite = occupied_suite("A", area=100_000.0)

    with pytest.raises(LeaseValidationError) as raised:
        schedule_for(
            [synthetic("A", 100_000.0), synthetic("Z", 5_000.0)], [suite]
        )

    assert LeaseIssueCode.UNKNOWN_SUITE_REFERENCE in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g15_a_missing_occupied_suite_projection_is_refused() -> None:
    a = occupied_suite("A", area=60_000.0)
    b = occupied_suite("B", area=40_000.0)
    leases = [lease_for(a), lease_for(b)]

    with pytest.raises(LeaseValidationError) as raised:
        schedule_for([synthetic("A", 60_000.0)], [a, b], leases=leases)

    assert LeaseIssueCode.MISSING_SUITE_OPERATING_PROJECTION in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g15_a_missing_market_lease_up_projection_is_refused() -> None:
    a = occupied_suite("A", area=70_000.0)
    b = lease_up_suite("B", area=30_000.0)

    with pytest.raises(LeaseValidationError) as raised:
        schedule_for([synthetic("A", 70_000.0)], [a, b], leases=[lease_for(a)])

    assert LeaseIssueCode.MISSING_SUITE_OPERATING_PROJECTION in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g15_a_missing_hold_vacant_projection_is_refused() -> None:
    """A deliberate zero must be present. D4.2 has no "vacant suites may be
    omitted" case (D3.6)."""

    a = occupied_suite("A", area=80_000.0)
    c = hold_vacant_suite("C", area=20_000.0)

    with pytest.raises(LeaseValidationError) as raised:
        schedule_for([synthetic("A", 80_000.0)], [a, c], leases=[lease_for(a)])

    codes = [issue.code for issue in raised.value.result.errors]
    assert LeaseIssueCode.MISSING_SUITE_OPERATING_PROJECTION in codes


def test_g15_an_un_underwritten_vacant_suite_reports_the_d3_6_error() -> None:
    """Vacant, no lease, no treatment: the D3.6 rule is preserved, not
    weakened."""

    a = occupied_suite("A", area=80_000.0)
    bare = Suite(suite_id="V", suite_area_sf=20_000.0)

    with pytest.raises(LeaseValidationError) as raised:
        schedule_for([synthetic("A", 80_000.0)], [a, bare], leases=[lease_for(a)])

    assert LeaseIssueCode.MISSING_INITIAL_VACANCY_TREATMENT in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g16_a_suite_area_mismatch_is_refused() -> None:
    suite = occupied_suite("A", area=100_000.0)

    with pytest.raises(LeaseValidationError) as raised:
        schedule_for([synthetic("A", 99_000.0)], [suite])

    assert LeaseIssueCode.SUITE_AREA_MISMATCH in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g16_an_area_within_the_scaled_tolerance_is_accepted() -> None:
    """Anchor's existing scaled comparison, not ``==``: floating-point noise
    must not fail a rent roll that reconciles on paper."""

    suite = occupied_suite("A", area=100_000.0)

    schedule = schedule_for([synthetic("A", 100_000.0 + 1e-7)], [suite])

    assert schedule.rentable_area_sf == PROPERTY_AREA


def test_g17_a_month_sequence_mismatch_is_refused() -> None:
    suite = occupied_suite("A", area=100_000.0)
    other = months(hold_period=HOLD, analysis_start=date(2028, 1, 1))

    with pytest.raises(LeaseValidationError) as raised:
        schedule_for([synthetic("A", 100_000.0, timeline=other)], [suite])

    assert LeaseIssueCode.OPERATING_SCHEDULE_NOT_ALIGNED in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g17_a_same_length_different_identity_tuple_is_refused() -> None:
    """Month identity, not length. A same-length tuple from a different
    analysis start zips cleanly and produces a plausible, wrong answer."""

    suite = occupied_suite("A", area=100_000.0)
    other = months(analysis_start=date(2030, 6, 1))

    assert len(other) == len(MONTHS)

    with pytest.raises(LeaseValidationError):
        schedule_for([synthetic("A", 100_000.0, timeline=other)], [suite])


def test_g17_a_different_hold_period_is_refused() -> None:
    suite = occupied_suite("A", area=100_000.0)
    longer = months(hold_period=HOLD + 1)

    with pytest.raises(LeaseValidationError):
        schedule_for([synthetic("A", 100_000.0, timeline=longer)], [suite])


def test_only_full_chain_results_may_be_projected() -> None:
    """A first-rollover-only result carries the same field names and would
    project silently, dropping every later generation."""

    suite = occupied_suite("A", area=40_000.0)
    lease = lease_for(suite, end=date(2028, 6, 30))
    first_rollover = build_expected_rollover(
        lease,
        suite=suite,
        analysis_start=JAN,
        months=MONTHS,
        property_defaults=assumptions(),
    )

    with pytest.raises(TypeError, match="authoritative full-chain"):
        suite_operating_projection(suite, first_rollover)


def test_a_projection_cannot_pair_one_suite_with_another_s_economics() -> None:
    a = occupied_suite("A", area=40_000.0)
    b = occupied_suite("B", area=60_000.0)

    with pytest.raises(ValueError, match="paired with a leasing result"):
        suite_operating_projection(b, occupied_chain(a, lease_for(a)))


# =============================================================================
# G18 -- order independence
# =============================================================================


def test_g18_property_aggregation_is_independent_of_projection_order() -> None:
    suites, leases, projections = _mixed_property()

    baseline = schedule_for(projections, suites, leases=leases)

    for permutation in itertools.permutations(projections):
        candidate = schedule_for(list(permutation), suites, leases=leases)
        assert candidate == baseline


def test_g18_property_aggregation_is_independent_of_suite_order() -> None:
    suites, leases, projections = _mixed_property()

    baseline = schedule_for(projections, suites, leases=leases)

    for permutation in itertools.permutations(suites):
        candidate = schedule_for(projections, list(permutation), leases=leases)
        assert candidate == baseline


def test_g18_order_independence_is_bit_exact_not_merely_close() -> None:
    suites, leases, projections = _mixed_property()

    baseline = schedule_for(projections, suites, leases=leases)
    reversed_ = schedule_for(list(reversed(projections)), suites, leases=leases)

    for name in (
        "contractual_base_rent",
        "cash_base_rent",
        "free_rent",
        "tenant_improvements",
        "leasing_commissions",
        "occupied_area_sf",
        "vacant_area_sf",
        "physical_occupancy",
    ):
        assert hexes(getattr(baseline, name)) == hexes(getattr(reversed_, name))


# =============================================================================
# G19 -- one-suite identity
# =============================================================================


def test_g19_a_one_suite_property_preserves_the_suite_series_bit_for_bit() -> None:
    """Catches an accidental property-level transformation."""

    suite = occupied_suite("A", area=100_000.0)
    lease = lease_for(suite, end=date(2028, 6, 30))
    projection = suite_operating_projection(suite, occupied_chain(suite, lease))

    schedule = schedule_for([projection], [suite], leases=[lease])

    for name in (
        "contractual_base_rent",
        "cash_base_rent",
        "free_rent",
        "tenant_improvements",
        "leasing_commissions",
    ):
        assert hexes(getattr(schedule, name)) == hexes(getattr(projection, name))
    assert hexes(schedule.occupied_area_sf) == hexes(projection.occupied_area_sf)


# =============================================================================
# G20 / G21 -- the two extremes
# =============================================================================


def test_g20_a_fully_hold_vacant_property_is_all_zero_and_fully_vacant() -> None:
    a = hold_vacant_suite("A", area=60_000.0)
    b = hold_vacant_suite("B", area=40_000.0)

    schedule = schedule_for(
        [
            suite_operating_projection(a, vacant_chain(a)),
            suite_operating_projection(b, vacant_chain(b)),
        ],
        [a, b],
    )

    zeros = tuple(0.0 for _ in MONTHS)
    assert schedule.contractual_base_rent == zeros
    assert schedule.cash_base_rent == zeros
    assert schedule.free_rent == zeros
    assert schedule.tenant_improvements == zeros
    assert schedule.leasing_commissions == zeros
    assert schedule.occupied_area_sf == zeros
    assert schedule.vacant_area_sf == tuple(PROPERTY_AREA for _ in MONTHS)
    assert schedule.physical_occupancy == zeros


def test_g20_a_fully_vacant_property_still_lists_every_suite() -> None:
    a = hold_vacant_suite("A", area=60_000.0)
    b = hold_vacant_suite("B", area=40_000.0)

    schedule = schedule_for(
        [
            suite_operating_projection(a, vacant_chain(a)),
            suite_operating_projection(b, vacant_chain(b)),
        ],
        [a, b],
    )

    assert [p.suite_id for p in schedule.suite_projections] == ["A", "B"]


def test_g21_a_fully_occupied_property_reports_full_occupancy() -> None:
    a = occupied_suite("A", area=60_000.0)
    b = occupied_suite("B", area=40_000.0)
    leases = [lease_for(a), lease_for(b)]

    schedule = schedule_for(
        [
            suite_operating_projection(a, occupied_chain(a, leases[0])),
            suite_operating_projection(b, occupied_chain(b, leases[1])),
        ],
        [a, b],
        leases=leases,
    )

    assert schedule.occupied_area_sf[0] == pytest.approx(PROPERTY_AREA, abs=1e-9)
    assert schedule.vacant_area_sf[0] == pytest.approx(0.0, abs=1e-9)
    assert schedule.physical_occupancy[0] == pytest.approx(1.0, abs=1e-12)


# =============================================================================
# G22 / G23 -- the forward exit window survives
# =============================================================================


def test_g22_the_schedule_spans_the_full_canonical_window() -> None:
    suites, leases, projections = _mixed_property()

    schedule = schedule_for(projections, suites, leases=leases)

    assert len(schedule.months) == 12 * HOLD + 12
    forward = schedule.months[12 * HOLD :]
    assert len(forward) == 12
    assert all(month.is_forward_exit_month for month in forward)


def test_g22_rent_continues_through_the_forward_window() -> None:
    """Nothing stops at month 12H. Which forward figures are a seller cash flow
    is D4.4/D4.5's question."""

    suite = occupied_suite("A", area=100_000.0)
    lease = lease_for(suite)

    schedule = schedule_for(
        [suite_operating_projection(suite, occupied_chain(suite, lease))],
        [suite],
        leases=[lease],
    )

    for index in range(12 * HOLD, len(MONTHS)):
        assert schedule.cash_base_rent[index] > 0.0
        assert schedule.occupied_area_sf[index] > 0.0


def test_g23_forward_window_ti_and_lc_are_retained() -> None:
    """A successor commencing after the sale date still records its TI and LC
    here. Discarding them now would destroy the audit trail D4.4 needs to
    exclude them from seller cash flow."""

    suite = occupied_suite("A", area=100_000.0)
    # Expires inside the forward window, so its successor's TI/LC land there.
    lease = lease_for(suite, end=date(2030, 4, 30))

    projection = suite_operating_projection(
        suite,
        occupied_chain(suite, lease, new_ti_psf=50.0, new_lc_pct=0.06),
    )
    schedule = schedule_for([projection], [suite], leases=[lease])

    forward_ti = sum(schedule.tenant_improvements[12 * HOLD :])
    forward_lc = sum(schedule.leasing_commissions[12 * HOLD :])

    assert forward_ti > 0.0, "forward-window TI was discarded"
    assert forward_lc > 0.0, "forward-window LC was discarded"


def test_g23_no_series_is_truncated_at_the_sale_date() -> None:
    suites, leases, projections = _mixed_property()

    schedule = schedule_for(projections, suites, leases=leases)

    for name in (
        "contractual_base_rent",
        "cash_base_rent",
        "free_rent",
        "tenant_improvements",
        "leasing_commissions",
        "occupied_area_sf",
        "vacant_area_sf",
        "physical_occupancy",
    ):
        assert len(getattr(schedule, name)) == 12 * HOLD + 12


# =============================================================================
# G24 -- initial vacancy: first tenant plus recursive tail, counted once
# =============================================================================


def test_g24_a_lease_up_chain_contains_vacancy_first_tenant_and_tail() -> None:
    """Three phases, each present exactly once, from one chain."""

    suite = lease_up_suite("B", area=30_000.0, lease_up=3.0)
    chain = vacant_chain(suite, new_term_months=12)

    projection = suite_operating_projection(suite, chain)

    # Phase 1: vacancy.
    assert projection.occupied_area_sf[:3] == tuple(0.0 for _ in range(3))
    # Phase 2: the deterministic first tenant, from month 4.
    assert projection.occupied_area_sf[3] == pytest.approx(30_000.0, abs=1e-9)
    assert projection.cash_base_rent[3] > 0.0
    # Phase 3: a later generation still paying after the first term ends.
    assert projection.cash_base_rent[20] > 0.0


def test_g24_the_projection_is_the_chain_and_nothing_is_added_twice() -> None:
    suite = lease_up_suite("B", area=30_000.0, lease_up=3.0)
    chain = vacant_chain(suite, new_term_months=12)

    projection = suite_operating_projection(suite, chain)

    assert hexes(projection.cash_base_rent) == hexes(chain.expected_cash_base_rent)
    assert hexes(projection.occupied_area_sf) == hexes(
        chain.expected_occupied_area_sf
    )
    assert projection.occupied_area_sf[3] <= suite.suite_area_sf + 1e-9


def test_g24_occupied_area_never_exceeds_the_suite_area() -> None:
    """Double-counting the first tenant against the tail would show here."""

    suite = lease_up_suite("B", area=30_000.0, lease_up=3.0)

    projection = suite_operating_projection(suite, vacant_chain(suite))

    for value in projection.occupied_area_sf:
        assert -1e-9 <= value <= suite.suite_area_sf + 1e-9


# =============================================================================
# Contract shape and scope
# =============================================================================


def test_the_suite_projection_publishes_no_occupancy_ratio() -> None:
    """Structural defence against averaging suite percentages: there is no
    suite-level ratio to average (D4 Section 16.1)."""

    fields = {field.name for field in dataclasses.fields(SuiteOperatingProjection)}

    assert "physical_occupancy" not in fields
    assert "vacant_area_sf" not in fields
    assert "occupied_area_sf" in fields


def test_neither_contract_declares_a_downstream_concept() -> None:
    for contract in (SuiteOperatingProjection, PropertyOperatingSchedule):
        fields = {field.name for field in dataclasses.fields(contract)}
        for forbidden in (
            "absent_rent",
            "expense_recovery",
            "recoverable_expenses",
            "property_taxes",
            "fixed_operating_expenses",
            "other_income",
            "credit_loss",
            "management_fee",
            "effective_gross_income",
            "noi",
            "capex",
            "exit_noi",
        ):
            assert forbidden not in fields, f"{contract.__name__} declares {forbidden}"


def test_no_annual_series_is_produced() -> None:
    """Monthly is canonical; the annual adapter is D4.4's."""

    fields = {field.name for field in dataclasses.fields(PropertyOperatingSchedule)}

    assert not any(name.endswith("_by_year") for name in fields)
    assert not any("annual" in name for name in fields)
    assert "hold_period" not in fields


def test_the_builder_takes_no_hold_period_and_so_cannot_annualize() -> None:
    import inspect

    parameters = set(
        inspect.signature(build_property_operating_schedule).parameters
    )

    assert "hold_period" not in parameters
    for forbidden in ("pool", "expenses", "operating_inputs", "recovery"):
        assert forbidden not in parameters


def test_both_contracts_are_immutable() -> None:
    suite = occupied_suite("A", area=100_000.0)
    projection = synthetic("A", 100_000.0)
    schedule = schedule_for([projection], [suite])

    with pytest.raises(dataclasses.FrozenInstanceError):
        projection.cash_base_rent = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        schedule.cash_base_rent = ()  # type: ignore[misc]


def test_a_mismatched_series_length_is_refused_by_the_contract() -> None:
    with pytest.raises(ValueError, match="one cash_base_rent figure"):
        SuiteOperatingProjection(
            suite_id="A",
            suite_area_sf=1.0,
            months=MONTHS,
            contractual_base_rent=tuple(0.0 for _ in MONTHS),
            cash_base_rent=(0.0,),
            free_rent=tuple(0.0 for _ in MONTHS),
            tenant_improvements=tuple(0.0 for _ in MONTHS),
            leasing_commissions=tuple(0.0 for _ in MONTHS),
            occupied_area_sf=tuple(0.0 for _ in MONTHS),
        )


def test_repeated_builds_are_equal_and_bit_identical() -> None:
    suites, leases, projections = _mixed_property()

    first = schedule_for(projections, suites, leases=leases)
    second = schedule_for(projections, suites, leases=leases)

    assert first == second
    assert hexes(first.cash_base_rent) == hexes(second.cash_base_rent)


# =============================================================================
# Validation ordering
# =============================================================================


def test_validation_issue_ordering_is_deterministic() -> None:
    a = occupied_suite("A", area=50_000.0)
    b = occupied_suite("B", area=30_000.0)
    c = hold_vacant_suite("C", area=20_000.0)
    other = months(analysis_start=date(2029, 1, 1))

    result = validate_property_operating_inputs(
        [
            synthetic("A", 49_000.0, timeline=other),
            synthetic("A", 50_000.0),
            synthetic("Z", 1.0),
        ],
        [a, b, c],
        months=MONTHS,
        leases=[lease_for(a), lease_for(b)],
    )

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.OPERATING_SCHEDULE_NOT_ALIGNED,
        LeaseIssueCode.SUITE_AREA_MISMATCH,
        LeaseIssueCode.DUPLICATE_SUITE_ID,
        LeaseIssueCode.UNKNOWN_SUITE_REFERENCE,
        LeaseIssueCode.MISSING_SUITE_OPERATING_PROJECTION,
        LeaseIssueCode.MISSING_SUITE_OPERATING_PROJECTION,
    ]


def test_validation_ordering_is_stable_across_runs() -> None:
    a = occupied_suite("A", area=60_000.0)
    b = occupied_suite("B", area=40_000.0)
    args = ([synthetic("A", 1.0)], [a, b])

    first = validate_property_operating_inputs(
        *args, months=MONTHS, leases=[lease_for(a), lease_for(b)]
    )
    second = validate_property_operating_inputs(
        *args, months=MONTHS, leases=[lease_for(a), lease_for(b)]
    )

    assert [issue.path for issue in first.issues] == [
        issue.path for issue in second.issues
    ]


def test_a_valid_property_produces_no_issues() -> None:
    suites, leases, projections = _mixed_property()

    result = validate_property_operating_inputs(
        projections, suites, months=MONTHS, leases=leases
    )

    assert result.is_valid
    assert not result.issues
