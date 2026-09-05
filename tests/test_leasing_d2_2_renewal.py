"""Sprint D Gate D2.2 -- the pure renewal rollover path.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Sections 4.2, 9.1, 10 and 14, and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 8.1, 8.4-8.6 and 24.3, that an expiring lease produces exactly one
renewal successor with the correct timing, pricing and escalation.

The financial claims that matter most:

- the successor commences the month **after** the inclusive expiry, with no
  vacant month and no overlapping month (Goldens 1, 2);
- it prices at the market rent of its **commencement** period, from the
  canonical D2.1 schedule -- not at the market rent at expiry (Golden 2);
- once commenced it escalates on **its own** anniversaries at
  ``successor_escalation_pct``, *not* at ``market_rent_growth``
  (Goldens 5, 7 -- failure mode FM-D2-14);
- the existing D1 lease is reused untouched, bit for bit (Golden 10 --
  failure mode FM-D2-20).

Every expected value below is hand-calculable from the D1 rent formula and the
D2.1 market formula alone.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseLevelPropertyInputs,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RenewalBranch,
    Suite,
    build_lease_monthly_schedule,
    build_market_rent_schedule,
    build_model_months,
    build_renewal_branch,
    build_renewal_successor_lease,
    renewal_commencement_period,
    renewal_starting_rent_psf,
    successor_expiration_period,
)
from anchor.leasing.market import resolve_market_leasing
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    validate_lease_level_inputs,
)


JAN_START = date(2027, 1, 1)
JUL_START = date(2027, 7, 1)
AREA = 12_000.0


def strict(expected: float) -> object:
    """The tolerance convention of ``tests/test_engine_golden_case.py``: tight
    enough to reject presentation-scale rounding, loose enough for ordinary
    IEEE-754 last-bit noise."""

    return pytest.approx(expected, rel=0.0, abs=1e-9)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    base: dict[str, object] = {
        "market_rent_psf": 40.0,
        "market_rent_growth": 0.03,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.04,
        # D2.3 concession fields -- inert for every assertion in this module.
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 0.0,
        "new_term_months": 60,
        "new_downtime_months": 0.0,
        "new_free_rent_months": 0.0,
        # D2.4 leasing costs -- inert for every assertion in this module.
        "renewal_ti_psf": 0.0,
        "new_ti_psf": 0.0,
        "leasing_commission_method": (
            LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT
        ),
        "renewal_lc_pct": 0.0,
        "new_lc_pct": 0.0,
        # D2.5 probability -- inert for every assertion in this module.
        "renewal_probability": 1.0,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)  # type: ignore[arg-type]


def suite(suite_id: str = "S1", **overrides: object) -> Suite:
    base: dict[str, object] = {"suite_id": suite_id, "suite_area_sf": AREA}
    base.update(overrides)
    return Suite(**base)  # type: ignore[arg-type]


def expiring_lease(**overrides: object) -> Lease:
    """An in-place lease expiring 2028-06-30, flat at $30/SF."""

    base: dict[str, object] = {
        "lease_id": "L1",
        "suite_id": "S1",
        "tenant_name": "Acme Corp",
        "leased_area_sf": AREA,
        "rent_commencement_date": date(2025, 7, 1),
        "lease_expiration_date": date(2028, 6, 30),
        "base_rent_psf": 30.0,
        "escalation_pct": 0.0,
        "escalation_basis": EscalationBasis.NONE,
        "lease_type": LeaseType.NNN,
    }
    base.update(overrides)
    return Lease(**base)  # type: ignore[arg-type]


def branch_for(
    *,
    analysis_start: date = JUL_START,
    hold_period: int = 8,
    lease: Lease | None = None,
    the_suite: Suite | None = None,
    defaults: MarketLeasingAssumptions | None = None,
) -> RenewalBranch:
    return build_renewal_branch(
        lease if lease is not None else expiring_lease(),
        suite=the_suite if the_suite is not None else suite(),
        analysis_start=analysis_start,
        months=build_model_months(
            analysis_start=analysis_start, hold_period=hold_period
        ),
        property_defaults=defaults if defaults is not None else assumptions(),
    )


def successor_psf(branch: RenewalBranch, period: int) -> float:
    """Recover the successor's annual $/SF rate from its monthly dollars."""

    monthly = branch.successor_schedule.contractual_base_rent[period - 1]
    return monthly * 12.0 / branch.successor_lease.leased_area_sf


# =============================================================================
# Successor timing -- c = e + 1
# =============================================================================


@pytest.mark.parametrize(
    ("expiration_period", "expected_c"),
    [(1, 2), (12, 13), (24, 25), (60, 61), (0, 1), (-5, -4)],
)
def test_renewal_commences_the_month_after_expiry(
    expiration_period: int, expected_c: int
) -> None:
    """A pure renewal has no downtime: ``c = e + 1``, always."""

    assert renewal_commencement_period(expiration_period) == expected_c


@pytest.mark.parametrize("bad", [1.0, "1", True, None])
def test_commencement_rejects_a_non_integer_period(bad: object) -> None:
    with pytest.raises(TypeError):
        renewal_commencement_period(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("expiry", "expected_commencement"),
    [
        (date(2028, 6, 30), date(2028, 7, 1)),
        (date(2027, 12, 31), date(2028, 1, 1)),  # December -> January
        (date(2028, 2, 29), date(2028, 3, 1)),  # leap February -> March
        (date(2029, 2, 28), date(2029, 3, 1)),  # common February -> March
        (date(2028, 1, 31), date(2028, 2, 1)),
    ],
)
def test_commencement_date_follows_the_inclusive_expiry(
    expiry: date, expected_commencement: date
) -> None:
    """Calendar chronology across month-length and leap-year boundaries. The
    expiring lease's inclusive expiration month is fully paid, and the
    successor starts on the first day of the next calendar month."""

    branch = branch_for(
        analysis_start=JAN_START,
        hold_period=10,
        lease=expiring_lease(lease_expiration_date=expiry),
    )

    assert branch.successor_lease.rent_commencement_date == expected_commencement
    assert branch.commencement_period == branch.expiration_period + 1


# =============================================================================
# GOLDEN 1 -- immediate flat renewal
# =============================================================================


def test_golden_1_immediate_flat_renewal() -> None:
    """12,000 SF, market $24, 0% growth, 0% spread, 0% escalation, 12-month
    term. The renewal pays ``24 * 12,000 / 12 = 24,000`` every month of its
    term, and there is no vacant month."""

    branch = branch_for(
        analysis_start=JAN_START,
        hold_period=6,
        defaults=assumptions(
            market_rent_psf=24.0,
            market_rent_growth=0.0,
            renewal_rent_spread=0.0,
            renewal_term_months=12,
            successor_escalation_pct=0.0,
        ),
        lease=expiring_lease(
            rent_commencement_date=JAN_START,
            lease_expiration_date=date(2028, 12, 31),
        ),
    )

    assert branch.starting_rent_psf == strict(24.0)
    assert branch.commencement_period == 25
    assert branch.successor_expiration_period == 36

    for period in range(25, 37):
        assert branch.successor_schedule.contractual_base_rent[period - 1] == strict(
            24_000.0
        )
    assert branch.successor_schedule.contractual_base_rent[36] == 0.0

    # No vacant month anywhere across the rollover.
    for period in range(1, 37):
        assert branch.physical_occupancy[period - 1] == 1.0


# =============================================================================
# GOLDEN 2 -- renewal on a market step
# =============================================================================


def test_golden_2_renewal_prices_at_the_commencement_market_rent() -> None:
    """analysis 2027-07-01, market $40 growing 3%, expiry 2028-06-30.

    The successor commences 2028-07-01 = period 13, the first month of the
    second growth band, so it prices at ``41.20`` -- **not** at the ``40.00``
    that applied in the expiry month."""

    branch = branch_for()

    assert branch.expiration_period == 12
    assert branch.months[11].month_start == date(2028, 6, 1)
    assert branch.commencement_period == 13
    assert branch.months[12].month_start == date(2028, 7, 1)

    assert branch.market_rent_psf_at_commencement == strict(41.2)
    assert branch.starting_rent_psf == strict(41.2)
    assert successor_psf(branch, 13) == strict(41.2)


def test_golden_2_the_market_rate_comes_from_the_canonical_schedule() -> None:
    """The branch must read D2.1's schedule, not recompute growth. Proven by
    equality with the schedule the caller builds independently."""

    months = build_model_months(analysis_start=JUL_START, hold_period=8)
    the_suite = suite()
    market = build_market_rent_schedule(
        the_suite, property_defaults=assumptions(), months=months
    )
    branch = build_renewal_branch(
        expiring_lease(),
        suite=the_suite,
        analysis_start=JUL_START,
        months=months,
        property_defaults=assumptions(),
    )

    assert branch.market_rent_psf_at_commencement == (
        market.market_rent_psf[branch.commencement_period - 1]
    )


def test_a_supplied_market_schedule_is_reused_and_must_match() -> None:
    """The caller may pass a schedule it already built; a schedule for a
    different suite or a different timeline is refused rather than silently
    repriced."""

    months = build_model_months(analysis_start=JUL_START, hold_period=8)
    the_suite = suite("S1")
    own = build_market_rent_schedule(
        the_suite, property_defaults=assumptions(), months=months
    )

    reused = build_renewal_branch(
        expiring_lease(),
        suite=the_suite,
        analysis_start=JUL_START,
        months=months,
        property_defaults=assumptions(),
        market_schedule=own,
    )
    rebuilt = branch_for()
    assert reused.contractual_base_rent == rebuilt.contractual_base_rent

    foreign = build_market_rent_schedule(
        suite("OTHER"), property_defaults=assumptions(), months=months
    )
    with pytest.raises(ValueError, match="belongs to suite"):
        build_renewal_branch(
            expiring_lease(),
            suite=the_suite,
            analysis_start=JUL_START,
            months=months,
            property_defaults=assumptions(),
            market_schedule=foreign,
        )

    other_timeline = build_market_rent_schedule(
        the_suite,
        property_defaults=assumptions(),
        months=build_model_months(analysis_start=JUL_START, hold_period=3),
    )
    with pytest.raises(ValueError, match="different month sequence"):
        build_renewal_branch(
            expiring_lease(),
            suite=the_suite,
            analysis_start=JUL_START,
            months=months,
            property_defaults=assumptions(),
            market_schedule=other_timeline,
        )


# =============================================================================
# GOLDENS 3 and 4 -- the renewal spread
# =============================================================================


@pytest.mark.parametrize(
    ("spread", "expected"),
    [
        (0.0, 40.0),
        (-0.05, 38.0),
        (0.05, 42.0),
        (-0.25, 30.0),
        (0.5, 60.0),
    ],
)
def test_goldens_3_and_4_spread_is_applied_to_market_at_commencement(
    spread: float, expected: float
) -> None:
    """``starting = MarketRentPSF(c) * (1 + renewal_rent_spread)``
    (D0 Section 24.3). Market $40 at commencement: 0% renews at market, -5%
    five percent below, +5% five percent above."""

    assert renewal_starting_rent_psf(
        assumptions=assumptions(renewal_rent_spread=spread),
        market_rent_psf_at_commencement=40.0,
        commencement_period=13,
    ) == strict(expected)


def test_a_below_market_renewal_flows_into_the_monthly_series() -> None:
    """The spread is not merely recorded -- it is what the successor pays."""

    branch = branch_for(defaults=assumptions(renewal_rent_spread=-0.05))

    assert branch.market_rent_psf_at_commencement == strict(41.2)
    assert branch.starting_rent_psf == strict(41.2 * 0.95)
    assert branch.successor_schedule.contractual_base_rent[12] == strict(
        41.2 * 0.95 * AREA / 12.0
    )


def test_an_explicit_renewal_level_wins_over_the_spread() -> None:
    """D0 Section 24.3's precedence: an explicit ``renewal_rent_psf`` wins,
    grown from ``analysis_start_date`` to ``c`` by the **market** growth
    convention. At $50 as of the analysis start, 3% growth and ``c = 13``, the
    successor starts at ``50 * 1.03 = 51.50`` -- and the spread is ignored."""

    branch = branch_for(
        defaults=assumptions(renewal_rent_psf=50.0, renewal_rent_spread=-0.5)
    )

    assert branch.starting_rent_psf == strict(51.5)
    assert branch.renewal_rent_psf == 50.0
    assert branch.renewal_rent_spread == -0.5  # preserved verbatim, unused


def test_an_explicit_renewal_level_uses_the_same_growth_bands_as_market() -> None:
    """The explicit level is measured on the same anchor as ``market_rent_psf``
    and grows in the same annual steps, so a suite rolling in Year 3 prices one
    band higher than one rolling in Year 2."""

    early = branch_for(defaults=assumptions(renewal_rent_psf=50.0))
    late = branch_for(
        defaults=assumptions(renewal_rent_psf=50.0),
        lease=expiring_lease(lease_expiration_date=date(2029, 6, 30)),
    )

    assert early.commencement_period == 13
    assert early.starting_rent_psf == strict(50.0 * 1.03)
    assert late.commencement_period == 25
    assert late.starting_rent_psf == strict(50.0 * 1.03**2)


def test_a_zero_explicit_renewal_level_is_not_treated_as_absent() -> None:
    """``0.0`` is a real explicit level; only ``None`` means "not supplied"."""

    branch = branch_for(
        defaults=assumptions(renewal_rent_psf=0.0, renewal_rent_spread=0.25)
    )

    assert branch.starting_rent_psf == 0.0
    for value in branch.successor_schedule.contractual_base_rent:
        assert value == 0.0


def test_zero_market_rent_renews_at_exactly_zero() -> None:
    branch = branch_for(defaults=assumptions(market_rent_psf=0.0))

    assert branch.market_rent_psf_at_commencement == 0.0
    assert branch.starting_rent_psf == 0.0
    for period in range(13, 25):
        assert branch.successor_schedule.contractual_base_rent[period - 1] == 0.0
        assert branch.physical_occupancy[period - 1] == 1.0


# =============================================================================
# GOLDEN 5 -- market growth versus successor contractual escalation
# =============================================================================


def test_golden_5_successor_escalates_on_its_own_rate_not_the_market_rate() -> None:
    """**The load-bearing distinction** (D2 Section 10, failure mode FM-D2-14).

    Market growth 10%, successor escalation 2%. Once the renewal commences it
    grows at **2%**, not 10%. The market schedule keeps growing at 10% in the
    background for the next rollover and has no further effect on this lease.
    """

    defaults = assumptions(market_rent_growth=0.10, successor_escalation_pct=0.02)
    branch = branch_for(defaults=defaults)

    # Commencement at period 13 prices off market: 40 * 1.10 = 44.00.
    assert branch.commencement_period == 13
    assert branch.market_rent_psf_at_commencement == strict(44.0)
    assert branch.starting_rent_psf == strict(44.0)

    # The successor's own year 1 (periods 13-24) holds at 44.00 ...
    assert successor_psf(branch, 13) == strict(44.0)
    assert successor_psf(branch, 24) == strict(44.0)

    # ... and its year 2 steps by 2%, NOT by 10%, and NOT to 40 * 1.10**2.
    assert successor_psf(branch, 25) == strict(44.0 * 1.02)
    assert successor_psf(branch, 25) != strict(44.0 * 1.10)
    assert successor_psf(branch, 25) != strict(40.0 * 1.10**2)
    assert successor_psf(branch, 37) == strict(44.0 * 1.02**2)


def test_golden_5_the_market_schedule_keeps_growing_independently() -> None:
    """Market rent continues on its own clock for the *next* rollover, while
    the successor is on its contractual one. The two series diverge, and that
    divergence is correct."""

    months = build_model_months(analysis_start=JUL_START, hold_period=8)
    the_suite = suite()
    defaults = assumptions(market_rent_growth=0.10, successor_escalation_pct=0.02)

    market = build_market_rent_schedule(
        the_suite, property_defaults=defaults, months=months
    )
    branch = build_renewal_branch(
        expiring_lease(),
        suite=the_suite,
        analysis_start=JUL_START,
        months=months,
        property_defaults=defaults,
        market_schedule=market,
    )

    assert market.market_rent_psf[24] == strict(40.0 * 1.10**2)  # 48.40
    assert successor_psf(branch, 25) == strict(44.88)
    assert market.market_rent_psf[24] != strict(successor_psf(branch, 25))


def test_a_market_growth_of_zero_still_lets_the_successor_escalate() -> None:
    """The converse of Golden 5: the two rates are independent in both
    directions."""

    branch = branch_for(
        defaults=assumptions(market_rent_growth=0.0, successor_escalation_pct=0.05)
    )

    assert branch.starting_rent_psf == strict(40.0)
    assert successor_psf(branch, 13) == strict(40.0)
    assert successor_psf(branch, 25) == strict(42.0)


def test_negative_successor_escalation_is_permitted() -> None:
    """Domain ``> -1``, the same bound every other Anchor compounding rate
    carries."""

    branch = branch_for(defaults=assumptions(successor_escalation_pct=-0.10))

    assert successor_psf(branch, 13) == strict(41.2)
    assert successor_psf(branch, 25) == strict(41.2 * 0.9)


# =============================================================================
# GOLDENS 6 and 9 -- the term
# =============================================================================


def test_golden_6_sixty_month_term_expires_2033_06_30() -> None:
    """Commencement 2028-07-01, term 60 -> inclusive expiration 2033-06-30.
    Exact calendar-month arithmetic, no day count, no conversion to years."""

    branch = branch_for()

    assert branch.term_months == 60
    assert branch.successor_lease.rent_commencement_date == date(2028, 7, 1)
    assert branch.successor_lease.lease_expiration_date == date(2033, 6, 30)
    assert branch.successor_expiration_period == 13 + 60 - 1


@pytest.mark.parametrize(
    ("term", "expected_last"),
    [(1, 13), (12, 24), (13, 25), (60, 72), (120, 132), (240, 252)],
)
def test_the_term_counts_canonical_months_inclusively(
    term: int, expected_last: int
) -> None:
    assert successor_expiration_period(commencement_period=13, term_months=term) == (
        expected_last
    )


def test_a_twelve_month_term_pays_in_its_expiration_month() -> None:
    """Commencement 2028-07-01, term 12 -> expiration 2029-06-30 inclusive.
    The expiration month is paid; the following month is outside the term."""

    branch = branch_for(defaults=assumptions(renewal_term_months=12))

    assert branch.successor_lease.lease_expiration_date == date(2029, 6, 30)
    assert branch.successor_schedule.contractual_base_rent[23] > 0.0  # period 24
    assert branch.successor_schedule.contractual_base_rent[24] == 0.0  # period 25
    assert branch.physical_occupancy[23] == 1.0
    assert branch.physical_occupancy[24] == 0.0  # D2.6 decides what follows


@pytest.mark.parametrize("bad", [0, -1, -60])
def test_a_non_positive_term_is_refused(bad: int) -> None:
    with pytest.raises(ValueError):
        successor_expiration_period(commencement_period=13, term_months=bad)


@pytest.mark.parametrize("bad", [12.0, "12", True])
def test_a_non_integer_term_is_refused(bad: object) -> None:
    with pytest.raises(TypeError):
        successor_expiration_period(commencement_period=13, term_months=bad)  # type: ignore[arg-type]


def test_golden_9_a_term_beyond_the_horizon_keeps_its_full_metadata() -> None:
    """D0 Section 8.6: the horizon truncates the monthly *series*, never the
    assumption. The successor's true contractual expiration is preserved even
    though no month past the horizon is computed -- D2.4's LC basis needs the
    full term (failure mode FM-D2-11)."""

    branch = branch_for(
        hold_period=2,  # 36 canonical months
        defaults=assumptions(renewal_term_months=120),
    )

    assert len(branch.months) == 36
    assert branch.commencement_period == 13
    assert branch.successor_expiration_period == 132  # far beyond the horizon
    assert branch.successor_lease.lease_expiration_date == date(2038, 6, 30)
    assert branch.term_months == 120

    # The series simply stops at the horizon; nothing is fabricated past it.
    assert len(branch.contractual_base_rent) == 36
    assert branch.successor_schedule.contractual_base_rent[35] > 0.0


# =============================================================================
# GOLDEN 7 -- non-January renewal anniversaries
# =============================================================================


def test_golden_7_a_september_renewal_escalates_every_september() -> None:
    """Renewal commencing 2027-09-01 steps next on 2028-09-01, not on any
    January. The successor's clock is its own commencement, exactly as D1's
    ``LEASE_ANNIVERSARY`` means (D0 Section 6.2)."""

    branch = branch_for(
        analysis_start=JAN_START,
        hold_period=8,
        lease=expiring_lease(
            rent_commencement_date=date(2026, 1, 1),
            lease_expiration_date=date(2027, 8, 31),
        ),
        defaults=assumptions(successor_escalation_pct=0.04),
    )

    assert branch.successor_lease.rent_commencement_date == date(2027, 9, 1)
    by_month = {
        month.month_start: successor_psf(branch, month.period_index)
        for month in branch.months
    }
    start = branch.starting_rent_psf

    assert by_month[date(2027, 9, 1)] == strict(start)
    assert by_month[date(2027, 12, 1)] == strict(start)
    assert by_month[date(2028, 1, 1)] == strict(start)  # NOT a step
    assert by_month[date(2028, 8, 1)] == strict(start)
    assert by_month[date(2028, 9, 1)] == strict(start * 1.04)  # the step
    assert by_month[date(2029, 9, 1)] == strict(start * 1.04**2)


def test_golden_7_every_successor_step_lands_on_its_own_anniversary() -> None:
    """Generalised: the successor's rate changes only in its commencement
    month, never in any other month of the year."""

    branch = branch_for(
        analysis_start=JAN_START,
        hold_period=9,
        lease=expiring_lease(
            rent_commencement_date=date(2026, 1, 1),
            lease_expiration_date=date(2027, 8, 31),
        ),
    )

    previous = None
    for month in branch.months:
        if month.period_index < branch.commencement_period:
            continue
        if month.period_index > branch.successor_expiration_period:
            break
        value = successor_psf(branch, month.period_index)
        if previous is not None and value != previous:
            assert month.month_start.month == 9, (
                f"successor stepped in {month.month_start}, which is not an "
                "anniversary of its 2027-09-01 commencement"
            )
        previous = value


@pytest.mark.parametrize("commencement_period", [13, 25, 37])
def test_renewal_commencing_on_a_band_boundary_prices_one_band_higher(
    commencement_period: int,
) -> None:
    """Adversarial: commencement at exactly periods 13, 25 and 37 -- the market
    growth band boundaries -- must take the *new* band's rate."""

    expiry_period = commencement_period - 1
    # analysis 2027-07-01; period p starts (p - 1) months later.
    expiry_month_start = date(
        2027 + (6 + expiry_period - 1) // 12,
        (6 + expiry_period - 1) % 12 + 1,
        1,
    )
    branch = branch_for(
        lease=expiring_lease(
            rent_commencement_date=date(2025, 7, 1),
            lease_expiration_date=date(
                expiry_month_start.year,
                expiry_month_start.month,
                [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][
                    expiry_month_start.month - 1
                ],
            ),
        )
    )

    band = (commencement_period - 1) // 12
    assert branch.commencement_period == commencement_period
    assert branch.starting_rent_psf == strict(40.0 * 1.03**band)


# =============================================================================
# GOLDEN 8 -- the forward exit window
# =============================================================================


def test_golden_8_renewal_inside_the_forward_window_is_modelled_normally() -> None:
    """Rollover stays fully live in periods ``12H+1 .. 12H+12``
    (D2 Section 11). No special case, no smoothing to stabilise exit value."""

    # hold 3 -> hold months 1-36, forward window 37-48.
    branch = branch_for(
        hold_period=3,
        lease=expiring_lease(lease_expiration_date=date(2030, 9, 30)),
    )

    assert branch.expiration_period == 39
    assert branch.commencement_period == 40
    assert branch.months[39].is_forward_exit_month is True

    assert branch.starting_rent_psf == strict(40.0 * 1.03**3)
    assert branch.successor_schedule.contractual_base_rent[39] == strict(
        40.0 * 1.03**3 * AREA / 12.0
    )
    for period in range(40, 49):
        assert branch.physical_occupancy[period - 1] == 1.0


def test_a_renewal_commencing_in_the_final_canonical_month_is_modelled() -> None:
    """Adversarial: expiry at ``12H+11`` puts commencement at exactly the last
    canonical month."""

    branch = branch_for(
        hold_period=3,
        lease=expiring_lease(lease_expiration_date=date(2031, 5, 31)),
    )

    assert branch.commencement_period == 48
    assert len(branch.months) == 48
    assert branch.commences_within_projection is True
    assert branch.successor_schedule.contractual_base_rent[47] > 0.0


def test_a_renewal_commencing_past_the_horizon_contributes_nothing() -> None:
    """Adversarial: expiry in the last canonical month puts commencement one
    month beyond the horizon.

    The projection is never extended and no month is fabricated, but the
    successor's contractual metadata is fully retained -- the assumption is
    real even where the window does not reach it."""

    branch = branch_for(
        hold_period=3,
        lease=expiring_lease(lease_expiration_date=date(2031, 6, 30)),
    )

    assert branch.expiration_period == 48
    assert branch.commencement_period == 49
    assert len(branch.months) == 48
    assert branch.commences_within_projection is False

    assert branch.successor_lease.rent_commencement_date == date(2031, 7, 1)
    assert branch.successor_expiration_period == 108
    assert branch.starting_rent_psf == strict(40.0 * 1.03**4)

    for value in branch.successor_schedule.contractual_base_rent:
        assert value == 0.0
    assert branch.contractual_base_rent == (
        branch.expiring_schedule.contractual_base_rent
    )


# =============================================================================
# No gap, no overlap -- the critical invariant
# =============================================================================


def test_exactly_one_occupant_in_every_month_across_the_rollover() -> None:
    """The expiry month belongs to the expiring lease alone and period ``c`` to
    the successor alone. No vacancy, no double rent, no overlapping area."""

    branch = branch_for()
    e, c = branch.expiration_period, branch.commencement_period

    for position, month in enumerate(branch.months):
        expiring_active = branch.expiring_schedule.occupied_area[position] > 0.0
        successor_active = branch.successor_schedule.occupied_area[position] > 0.0
        assert not (expiring_active and successor_active), (
            f"period {month.period_index} is occupied by both leases"
        )

    assert branch.expiring_schedule.occupied_area[e - 1] == AREA
    assert branch.successor_schedule.occupied_area[e - 1] == 0.0
    assert branch.expiring_schedule.occupied_area[c - 1] == 0.0
    assert branch.successor_schedule.occupied_area[c - 1] == AREA


def test_branch_occupancy_is_continuous_and_integral_across_the_rollover() -> None:
    """Branch physical occupancy is a genuine scenario state (D2 HD-D2-2): the
    suite is occupied or it is not, never 0.65 of it. A pure renewal has no
    downtime, so occupancy is continuous."""

    branch = branch_for()

    for period in range(1, branch.successor_expiration_period + 1):
        if period > len(branch.months):
            break
        assert branch.physical_occupancy[period - 1] == 1.0
        assert branch.occupied_area[period - 1] == AREA

    assert set(branch.physical_occupancy) <= {0.0, 1.0}


def test_the_branch_series_is_the_exact_sum_of_the_two_schedules() -> None:
    branch = branch_for()

    for position in range(len(branch.months)):
        assert branch.contractual_base_rent[position] == (
            branch.expiring_schedule.contractual_base_rent[position]
            + branch.successor_schedule.contractual_base_rent[position]
        )


def test_a_lease_expiring_before_the_analysis_start_is_refused_not_clamped() -> None:
    """Adversarial: an expiry before Month 1 makes ``c`` non-positive, where
    market rent is undefined.

    Validation already rejects such an input
    (``LEASE_EXPIRED_BEFORE_ANALYSIS_START``), so this is a defensive boundary;
    it **refuses** rather than clamping ``c`` to Month 1, because a silent
    normalisation would price the successor off the wrong growth band and
    report a plausible number for an unrepresentable scenario."""

    stale = expiring_lease(
        rent_commencement_date=date(2024, 1, 1),
        lease_expiration_date=date(2026, 6, 30),
    )

    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(analysis_start_date=JAN_START, rentable_area_sf=AREA),
        [suite("S1")],
        [stale],
    )
    assert LeaseIssueCode.LEASE_EXPIRED_BEFORE_ANALYSIS_START in codes(result)

    with pytest.raises(ValueError, match="before the analysis start"):
        branch_for(analysis_start=JAN_START, lease=stale)


def test_the_raw_unclamped_expiry_drives_commencement() -> None:
    """A lease running past the horizon must roll at its **real** expiration,
    not at the window edge. Clamping would be the FM-5 trap on the rollover
    side: a 5-year hold would roll every long lease in its final month."""

    long_lease = expiring_lease(
        rent_commencement_date=date(2027, 7, 1),
        lease_expiration_date=date(2040, 6, 30),
    )
    branch = branch_for(hold_period=3, lease=long_lease)  # 48 canonical months

    assert branch.expiration_period == 156  # far past the 48-month horizon
    assert branch.commencement_period == 157
    assert branch.commences_within_projection is False
    assert branch.successor_lease.rent_commencement_date == date(2040, 7, 1)


# =============================================================================
# GOLDEN 10 -- the existing D1 lease is untouched
# =============================================================================


def test_golden_10_the_expiring_schedule_is_hex_identical_to_its_d1_schedule() -> None:
    """D2.2 reuses the in-place lease's D1 schedule and never recomputes it.
    Proven bit for bit against ``build_lease_monthly_schedule`` called
    directly, which is what D1 does (failure mode FM-D2-20)."""

    months = build_model_months(analysis_start=JUL_START, hold_period=8)
    lease = expiring_lease()

    d1_schedule = build_lease_monthly_schedule(
        lease, analysis_start=JUL_START, months=months
    )
    branch = branch_for()

    assert branch.expiring_schedule == d1_schedule
    for left, right in zip(
        branch.expiring_schedule.contractual_base_rent,
        d1_schedule.contractual_base_rent,
    ):
        assert left.hex() == right.hex()


def test_no_market_assumption_touches_the_expiring_lease() -> None:
    """D0 Section 24.4: contractual terms always win. Changing every market and
    renewal assumption must leave the expiring lease's dollars bit-identical."""

    baseline = branch_for()
    altered = branch_for(
        defaults=assumptions(
            market_rent_psf=999.0,
            market_rent_growth=0.5,
            renewal_rent_psf=123.0,
            renewal_rent_spread=0.75,
            renewal_term_months=7,
            successor_escalation_pct=0.9,
        )
    )

    assert (
        baseline.expiring_schedule.contractual_base_rent
        == altered.expiring_schedule.contractual_base_rent
    )
    assert baseline.starting_rent_psf != altered.starting_rent_psf


def test_the_expiring_lease_object_is_never_mutated() -> None:
    lease = expiring_lease()
    before = dataclasses.replace(lease)
    the_suite = suite()

    branch_for(lease=lease, the_suite=the_suite)

    assert lease == before
    assert lease.origin is LeaseOrigin.IN_PLACE
    assert lease.tenant_name == "Acme Corp"


# =============================================================================
# The successor is an assumption, not a known tenant
# =============================================================================


def test_the_successor_is_never_presented_as_a_known_tenant() -> None:
    """D0 Section 8.4, failure mode FM-D2-18."""

    branch = branch_for()

    assert branch.successor_lease.tenant_name is None
    assert branch.successor_lease.origin is LeaseOrigin.SUCCESSOR
    assert branch.successor_lease.lease_id == "L1::renewal"
    assert branch.successor_lease_id == branch.successor_lease.lease_id


def test_the_successor_inherits_structure_but_not_identity() -> None:
    branch = branch_for(lease=expiring_lease(lease_type=LeaseType.MODIFIED_GROSS))

    assert branch.successor_lease.lease_type is LeaseType.MODIFIED_GROSS
    assert branch.successor_lease.suite_id == "S1"
    assert branch.successor_lease.leased_area_sf == AREA
    assert branch.successor_lease.escalation_basis is EscalationBasis.LEASE_ANNIVERSARY
    assert branch.successor_lease.lease_start_date is None


def test_a_successor_lease_naming_a_tenant_is_a_validation_error() -> None:
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(analysis_start_date=JAN_START, rentable_area_sf=AREA),
        [suite("S1")],
        [
            expiring_lease(
                tenant_name="Acme Corp", origin=LeaseOrigin.SUCCESSOR
            )
        ],
    )

    assert not result.is_valid
    assert LeaseIssueCode.SUCCESSOR_LEASE_NAMES_A_TENANT in [
        issue.code for issue in result.issues
    ]


def test_a_successor_lease_without_a_tenant_name_is_valid() -> None:
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(analysis_start_date=JAN_START, rentable_area_sf=AREA),
        [suite("S1")],
        [expiring_lease(tenant_name=None, origin=LeaseOrigin.SUCCESSOR)],
    )

    assert result.is_valid


def test_the_generated_successor_passes_leasing_validation() -> None:
    """The engine may not construct a lease its own validator would reject."""

    branch = branch_for(hold_period=10)
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(
            analysis_start_date=JUL_START, rentable_area_sf=AREA
        ),
        [suite("S1")],
        [branch.successor_lease],
        market_leasing=assumptions(),
    )

    assert result.is_valid, [issue.message for issue in result.errors]


# =============================================================================
# Determinism and immutability
# =============================================================================


def test_repeated_build_is_value_equal() -> None:
    first = branch_for()
    second = branch_for()

    assert first == second
    for left, right in zip(first.contractual_base_rent, second.contractual_base_rent):
        assert left.hex() == right.hex()


def test_the_branch_is_frozen() -> None:
    branch = branch_for()

    with pytest.raises(dataclasses.FrozenInstanceError):
        branch.starting_rent_psf = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        branch.successor_lease.base_rent_psf = 1.0  # type: ignore[misc]


def test_component_assumptions_are_preserved_verbatim() -> None:
    """D0 Section 8.4: the result never overwrites the assumptions that
    produced it."""

    defaults = assumptions(
        renewal_rent_psf=None,
        renewal_rent_spread=-0.05,
        renewal_term_months=84,
        successor_escalation_pct=0.025,
    )
    branch = branch_for(defaults=defaults)

    assert branch.renewal_rent_psf is None
    assert branch.renewal_rent_spread == -0.05
    assert branch.term_months == 84
    assert branch.successor_escalation_pct == 0.025
    assert branch.resolved.assumptions == defaults
    assert branch.market_rent_psf_at_commencement == strict(41.2)
    assert branch.starting_rent_psf == strict(41.2 * 0.95)


def test_a_suite_override_drives_the_renewal() -> None:
    """Precedence resolves once per suite (D0 Section 24.5) and the renewal
    prices from the resolved record, not from the property default."""

    override = assumptions(
        market_rent_psf=60.0,
        market_rent_growth=0.05,
        renewal_rent_spread=-0.10,
        renewal_term_months=36,
        successor_escalation_pct=0.03,
    )
    branch = branch_for(the_suite=suite("S1", market_leasing_override=override))

    assert branch.market_rent_psf_at_commencement == strict(63.0)
    assert branch.starting_rent_psf == strict(63.0 * 0.9)
    assert branch.term_months == 36
    assert branch.resolved.source.value == "suite_override"


def test_the_rent_level_override_carries_every_other_field_through() -> None:
    """D0 Section 24.1 overrides the rent **level alone**.

    Regression guard: a resolver that rebuilds the record field by field
    silently drops every assumption a later gate adds, so a suite with a
    rent-level override would quietly lose its renewal term. Asserted over the
    whole record rather than over a hand-listed subset, so it keeps biting as
    D2.3-D2.5 add fields."""

    defaults = assumptions(
        renewal_rent_psf=33.0,
        renewal_rent_spread=-0.07,
        renewal_term_months=84,
        successor_escalation_pct=0.035,
    )
    resolved = resolve_market_leasing(
        suite("S1", market_rent_psf=52.0), property_defaults=defaults
    )

    assert resolved.assumptions.market_rent_psf == 52.0
    assert resolved.assumptions == dataclasses.replace(defaults, market_rent_psf=52.0)
    assert dataclasses.asdict(resolved.assumptions) == {
        **dataclasses.asdict(defaults),
        "market_rent_psf": 52.0,
    }


def test_a_rent_level_override_drives_the_renewal_but_not_its_term() -> None:
    """The same rule seen through the branch: the suite's rent level prices the
    successor, while its term and escalation still come from the property
    default."""

    defaults = assumptions(renewal_term_months=24, successor_escalation_pct=0.06)
    branch = branch_for(
        the_suite=suite("S1", market_rent_psf=100.0), defaults=defaults
    )

    assert branch.market_rent_psf_at_commencement == strict(103.0)  # 100 * 1.03
    assert branch.starting_rent_psf == strict(103.0)
    assert branch.term_months == 24
    # c = 13, term 24 -> periods 13..36; the escalation step falls at c + 12.
    assert branch.successor_expiration_period == 36
    assert successor_psf(branch, 24) == strict(103.0)
    assert successor_psf(branch, 25) == strict(103.0 * 1.06)
    assert successor_psf(branch, 36) == strict(103.0 * 1.06)
    assert branch.successor_schedule.contractual_base_rent[36] == 0.0


def test_a_branch_rejects_a_mismatched_series_length() -> None:
    branch = branch_for()

    with pytest.raises(ValueError):
        dataclasses.replace(branch, contractual_base_rent=(0.0,))


# =============================================================================
# Validation -- the D2.2 domains
# =============================================================================


def property_inputs() -> LeaseLevelPropertyInputs:
    return LeaseLevelPropertyInputs(
        analysis_start_date=JAN_START, rentable_area_sf=AREA
    )


def codes(result: object) -> list[LeaseIssueCode]:
    return [issue.code for issue in result.issues]  # type: ignore[attr-defined]


def validate(**overrides: object) -> object:
    return validate_lease_level_inputs(
        property_inputs(),
        [suite("S1")],
        [],
        market_leasing=assumptions(**overrides),
    )


@pytest.mark.parametrize("bad", [-0.01, -40.0])
def test_a_negative_explicit_renewal_rent_is_an_error(bad: float) -> None:
    result = validate(renewal_rent_psf=bad)
    assert LeaseIssueCode.RENEWAL_RENT_OUT_OF_DOMAIN in codes(result)


def test_a_none_explicit_renewal_rent_is_valid() -> None:
    assert validate(renewal_rent_psf=None).is_valid  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", [-1.0, -1.5])
def test_a_renewal_spread_at_or_below_minus_one_is_an_error(bad: float) -> None:
    result = validate(renewal_rent_spread=bad)
    assert LeaseIssueCode.RENEWAL_RENT_SPREAD_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("spread", [-0.99, -0.05, 0.0, 0.05, 1.0])
def test_a_renewal_spread_above_minus_one_is_valid(spread: float) -> None:
    assert validate(renewal_rent_spread=spread).is_valid  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", [0, -1, -12])
def test_a_non_positive_renewal_term_is_an_error(bad: int) -> None:
    result = validate(renewal_term_months=bad)
    assert LeaseIssueCode.RENEWAL_TERM_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("bad", [12.0, 12.5, "12", True])
def test_a_non_integer_renewal_term_is_an_error(bad: object) -> None:
    result = validate(renewal_term_months=bad)
    assert LeaseIssueCode.RENEWAL_TERM_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("term", [1, 12, 60, 240])
def test_a_positive_integer_renewal_term_is_valid(term: int) -> None:
    assert validate(renewal_term_months=term).is_valid  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", [-1.0, -2.0])
def test_a_successor_escalation_at_or_below_minus_one_is_an_error(bad: float) -> None:
    result = validate(successor_escalation_pct=bad)
    assert LeaseIssueCode.SUCCESSOR_ESCALATION_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("rate", [-0.99, -0.1, 0.0, 0.03, 1.0])
def test_a_successor_escalation_above_minus_one_is_valid(rate: float) -> None:
    assert validate(successor_escalation_pct=rate).is_valid  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_renewal_assumptions_are_errors(bad: float) -> None:
    for field in ("renewal_rent_psf", "renewal_rent_spread", "successor_escalation_pct"):
        result = validate(**{field: bad})
        assert LeaseIssueCode.NON_FINITE_VALUE in codes(result), field


def test_renewal_issues_are_errors_never_warnings() -> None:
    result = validate(
        renewal_rent_psf=-1.0,
        renewal_rent_spread=-2.0,
        renewal_term_months=0,
        successor_escalation_pct=-3.0,
    )

    for issue in result.issues:
        assert issue.severity is LeaseIssueSeverity.ERROR


def test_a_suite_override_is_checked_against_the_renewal_domains() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [
            suite(
                "S1",
                market_leasing_override=assumptions(renewal_term_months=0),
            )
        ],
        [],
        market_leasing=assumptions(),
    )

    issue = next(
        item
        for item in result.issues
        if item.code is LeaseIssueCode.RENEWAL_TERM_OUT_OF_DOMAIN
    )
    assert issue.path == "suites[0].market_leasing_override.renewal_term_months"


def test_an_incomplete_assumption_record_cannot_be_constructed() -> None:
    """The all-or-nothing override rule (D0 Section 24.2) stays structural as
    the record grows: every D2.2 field is required and none has a default."""

    complete = {
        "market_rent_psf": 40.0,
        "market_rent_growth": 0.03,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.03,
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
        "renewal_probability": 1.0,
    }
    for omitted in (
        "renewal_rent_psf",
        "renewal_rent_spread",
        "renewal_term_months",
        "successor_escalation_pct",
    ):
        fields = dict(complete)
        del fields[omitted]
        with pytest.raises(TypeError):
            MarketLeasingAssumptions(**fields)  # type: ignore[arg-type]


# =============================================================================
# D1 / D2.1 isolation
# =============================================================================


def test_a_lease_defaults_to_in_place_origin() -> None:
    """Additive and non-breaking: every D1 call site constructs an identical
    lease."""

    assert expiring_lease().origin is LeaseOrigin.IN_PLACE


def test_the_successor_builder_needs_no_downtime_or_free_rent_concept() -> None:
    """A pure renewal has no vacancy by construction, so D2.2 never reaches for
    a concept D2.3 owns. Proven by signature."""

    import inspect

    parameters = set(inspect.signature(build_renewal_successor_lease).parameters)
    for absent in (
        "downtime_months",
        "free_rent_months",
        "renewal_probability",
        "occupancy_factor",
    ):
        assert absent not in parameters
