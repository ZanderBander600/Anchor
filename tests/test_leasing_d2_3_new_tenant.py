"""Sprint D Gate D2.3 -- the pure new-tenant path, downtime and free rent.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Sections 6, 7, 9.2 and 14, that a non-renewing tenant produces a vacancy, a
market-priced replacement, and a concession consumed by a sequential waterfall.

The financial claims that matter most:

- ``c = e + 1 + floor(D)``, and total rent forgone is exactly ``D``
  month-equivalents (Goldens 2, 3, 4 -- failure modes FM-D2-5, FM-D2-6);
- free rent is consumed **against occupancy, sequentially**, so a fractional
  commencement month consumes only its fraction (Golden 7 -- failure modes
  FM-D2-7, FM-D2-7b, FM-D2-7c);
- free rent never reduces occupancy and never reduces contractual **face**
  rent (Goldens 11, 5 -- failure modes FM-D2-8, FM-D2-10);
- branch physical occupancy stays **integral** while ``O_m`` may be fractional
  (failure mode FM-D2-19);
- a new letting prices at market at its **delayed** commencement (Golden 8);
- zero downtime and zero free rent reproduce the accepted D2.2 renewal branch
  exactly (Golden 14).

Every expected value below is hand-calculable from the D2 Section 6.1 downtime
rule, the Section 7.1 waterfall and the D1 rent formula.
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
    MarketLeasingAssumptions,
    NewTenantBranch,
    RenewalBranch,
    Suite,
    build_market_rent_schedule,
    build_model_months,
    build_new_tenant_branch,
    build_renewal_branch,
    free_rent_waterfall,
    maximum_consumable_free_rent_months,
    new_tenant_starting_rent_psf,
    successor_commencement_period,
    successor_occupancy_factors,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    validate_lease_level_inputs,
)


JAN_START = date(2027, 1, 1)
JUL_START = date(2027, 7, 1)
AREA = 12_000.0

#: The expiring lease pays $30/SF flat and expires 2028-06-30. With a January
#: analysis start that is period 18, so `e = 18` throughout this module.
EXPIRY_PERIOD = 18


def strict(expected: float) -> object:
    """The tolerance convention of ``tests/test_engine_golden_case.py``."""

    return pytest.approx(expected, rel=0.0, abs=1e-9)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    """Market $24 flat, so face rent is a round $24,000/month on 12,000 SF."""

    base: dict[str, object] = {
        "market_rent_psf": 24.0,
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
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)  # type: ignore[arg-type]


def suite(suite_id: str = "S1", **overrides: object) -> Suite:
    base: dict[str, object] = {"suite_id": suite_id, "suite_area_sf": AREA}
    base.update(overrides)
    return Suite(**base)  # type: ignore[arg-type]


def expiring_lease(**overrides: object) -> Lease:
    base: dict[str, object] = {
        "lease_id": "L1",
        "suite_id": "S1",
        "tenant_name": "Acme Corp",
        "leased_area_sf": AREA,
        "rent_commencement_date": date(2026, 1, 1),
        "lease_expiration_date": date(2028, 6, 30),
        "base_rent_psf": 30.0,
        "escalation_pct": 0.0,
        "escalation_basis": EscalationBasis.NONE,
        "lease_type": LeaseType.NNN,
    }
    base.update(overrides)
    return Lease(**base)  # type: ignore[arg-type]


def new_branch(
    *,
    analysis_start: date = JAN_START,
    hold_period: int = 6,
    lease: Lease | None = None,
    the_suite: Suite | None = None,
    defaults: MarketLeasingAssumptions | None = None,
) -> NewTenantBranch:
    return build_new_tenant_branch(
        lease if lease is not None else expiring_lease(),
        suite=the_suite if the_suite is not None else suite(),
        analysis_start=analysis_start,
        months=build_model_months(
            analysis_start=analysis_start, hold_period=hold_period
        ),
        property_defaults=defaults if defaults is not None else assumptions(),
    )


def renewal_branch(
    *,
    analysis_start: date = JAN_START,
    hold_period: int = 6,
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


def at(branch: object, series: str, period: int) -> float:
    return getattr(branch, series)[period - 1]


def face_psf(branch: object, period: int) -> float:
    monthly = branch.successor_schedule.contractual_base_rent[period - 1]  # type: ignore[attr-defined]
    return monthly * 12.0 / branch.successor_lease.leased_area_sf  # type: ignore[attr-defined]


# =============================================================================
# Downtime timing -- c = e + 1 + floor(D)
# =============================================================================


@pytest.mark.parametrize(
    ("downtime", "expected_c"),
    [
        (0.0, 19), (0.25, 19), (0.75, 19), (0.999, 19),
        (1.0, 20), (1.5, 20),
        (2.0, 21), (2.25, 21),
        (3.0, 22),
        (5.5, 24),
        (6.0, 25),
        (12.0, 31),
    ],
)
def test_commencement_is_expiry_plus_one_plus_floor_downtime(
    downtime: float, expected_c: int
) -> None:
    """D2 Section 6.1. Only the whole part of ``D`` moves the commencement
    period; the fraction is carried by the occupancy factor."""

    assert successor_commencement_period(
        expiration_period=EXPIRY_PERIOD, downtime_months=downtime
    ) == expected_c


@pytest.mark.parametrize("bad", [-0.01, -1.0])
def test_negative_downtime_is_refused(bad: float) -> None:
    with pytest.raises(ValueError):
        successor_commencement_period(
            expiration_period=EXPIRY_PERIOD, downtime_months=bad
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_downtime_is_refused(bad: float) -> None:
    with pytest.raises(ValueError):
        successor_commencement_period(
            expiration_period=EXPIRY_PERIOD, downtime_months=bad
        )


def test_fractional_downtime_never_produces_a_non_month_aligned_date() -> None:
    """D2 Section 6.4: D1's contractual dates stay month-aligned. The fraction
    lives entirely in the occupancy factor."""

    for downtime in (0.25, 2.25, 5.5, 0.999):
        branch = new_branch(defaults=assumptions(new_downtime_months=downtime))
        assert branch.successor_lease.rent_commencement_date.day == 1
        expiration = branch.successor_lease.lease_expiration_date
        # Inclusive, and always a real month end.
        assert expiration.day in {28, 29, 30, 31}
        assert (expiration.month % 12) + 1 == (
            expiration + __import__("datetime").timedelta(days=1)
        ).month


# =============================================================================
# GOLDEN 1 -- zero downtime, zero free rent
# =============================================================================


def test_golden_1_zero_downtime_zero_free_rent() -> None:
    """The successor begins the next month, is fully occupied, and cash equals
    face in every period."""

    branch = new_branch()

    assert branch.commencement_period == EXPIRY_PERIOD + 1
    assert branch.starting_rent_psf == strict(24.0)

    for period in range(EXPIRY_PERIOD + 1, EXPIRY_PERIOD + 13):
        assert at(branch, "successor_occupancy_factor", period) == 1.0
        assert at(branch, "free_rent_abatement_months", period) == 0.0
        assert at(branch, "cash_rent_factor", period) == 1.0
        assert at(branch, "cash_base_rent", period) == strict(24_000.0)
        assert at(branch, "free_rent", period) == 0.0
        assert at(branch, "physical_occupancy", period) == 1.0

    assert branch.cash_base_rent == branch.contractual_base_rent


# =============================================================================
# GOLDEN 2 -- integer downtime
# =============================================================================


def test_golden_2_integer_downtime_of_three_months() -> None:
    """Three fully vacant periods, then a full month at factor ``1.00``."""

    branch = new_branch(defaults=assumptions(new_downtime_months=3.0))

    assert branch.commencement_period == EXPIRY_PERIOD + 4

    for period in (EXPIRY_PERIOD + 1, EXPIRY_PERIOD + 2, EXPIRY_PERIOD + 3):
        assert at(branch, "successor_occupancy_factor", period) == 0.0
        assert at(branch, "contractual_base_rent", period) == 0.0
        assert at(branch, "cash_base_rent", period) == 0.0
        assert at(branch, "physical_occupancy", period) == 0.0
        assert at(branch, "occupied_area", period) == 0.0

    boundary = EXPIRY_PERIOD + 4
    assert at(branch, "successor_occupancy_factor", boundary) == 1.0
    assert at(branch, "cash_base_rent", boundary) == strict(24_000.0)
    assert at(branch, "physical_occupancy", boundary) == 1.0


# =============================================================================
# GOLDEN 3 -- fractional downtime 2.25
# =============================================================================


def test_golden_3_fractional_downtime_of_2_25_months() -> None:
    """Two fully vacant periods, then a boundary factor of ``0.75``."""

    branch = new_branch(defaults=assumptions(new_downtime_months=2.25))

    assert branch.commencement_period == EXPIRY_PERIOD + 3

    for period in (EXPIRY_PERIOD + 1, EXPIRY_PERIOD + 2):
        assert at(branch, "successor_occupancy_factor", period) == 0.0
        assert at(branch, "physical_occupancy", period) == 0.0

    boundary = EXPIRY_PERIOD + 3
    assert at(branch, "successor_occupancy_factor", boundary) == strict(0.75)
    assert at(branch, "cash_rent_factor", boundary) == strict(0.75)
    assert at(branch, "cash_base_rent", boundary) == strict(18_000.0)
    # Face rent is a FULL month even though only 0.75 is recognised.
    assert at(branch, "contractual_base_rent", boundary) == strict(24_000.0)
    assert at(branch, "physical_occupancy", boundary) == 1.0

    assert at(branch, "successor_occupancy_factor", EXPIRY_PERIOD + 4) == 1.0


@pytest.mark.parametrize(
    "downtime", [0.0, 0.25, 1.0, 1.5, 2.25, 3.0, 5.5, 6.0, 0.999, 11.75]
)
def test_total_forgone_month_equivalents_equals_downtime(downtime: float) -> None:
    """**The identity that anchors the whole rule** (D2 Section 6.2):
    ``floor(D)`` fully vacant periods contribute ``1.0`` each and the boundary
    contributes ``frac(D)``, so total rent forgone is exactly ``D``.

    Off-by-one forms such as ``e + floor(D)`` or ``e + 1 + ceil(D)`` break it
    (failure mode FM-D2-5)."""

    branch = new_branch(
        hold_period=8, defaults=assumptions(new_downtime_months=downtime)
    )

    forgone = 0.0
    for period in range(EXPIRY_PERIOD + 1, branch.commencement_period + 1):
        forgone += 1.0 - at(branch, "successor_occupancy_factor", period)

    assert forgone == strict(downtime)


# =============================================================================
# GOLDEN 4 -- fractional downtime 5.5
# =============================================================================


def test_golden_4_fractional_downtime_of_5_5_months() -> None:
    """Five fully vacant periods, then a boundary factor of ``0.50``."""

    branch = new_branch(hold_period=8, defaults=assumptions(new_downtime_months=5.5))

    assert branch.commencement_period == EXPIRY_PERIOD + 6

    for offset in range(1, 6):
        assert at(branch, "successor_occupancy_factor", EXPIRY_PERIOD + offset) == 0.0
        assert at(branch, "physical_occupancy", EXPIRY_PERIOD + offset) == 0.0

    boundary = EXPIRY_PERIOD + 6
    assert at(branch, "successor_occupancy_factor", boundary) == strict(0.5)
    assert at(branch, "cash_base_rent", boundary) == strict(12_000.0)
    assert at(branch, "contractual_base_rent", boundary) == strict(24_000.0)


# =============================================================================
# GOLDENS 5 and 6 -- free rent
# =============================================================================


def test_golden_5_integer_free_rent_of_two_months() -> None:
    """``D = 0``, ``F = 2``. The first two occupied months collect nothing; the
    third collects in full. Face rent is untouched throughout."""

    branch = new_branch(defaults=assumptions(new_free_rent_months=2.0))
    c = branch.commencement_period

    for offset in (0, 1):
        assert at(branch, "free_rent_abatement_months", c + offset) == 1.0
        assert at(branch, "cash_rent_factor", c + offset) == 0.0
        assert at(branch, "cash_base_rent", c + offset) == 0.0
        assert at(branch, "free_rent", c + offset) == strict(24_000.0)
        # Face rent is NOT reduced -- D2.4's LC basis reads this series.
        assert at(branch, "contractual_base_rent", c + offset) == strict(24_000.0)
        assert at(branch, "physical_occupancy", c + offset) == 1.0

    assert at(branch, "cash_rent_factor", c + 2) == 1.0
    assert at(branch, "cash_base_rent", c + 2) == strict(24_000.0)


def test_golden_6_fractional_free_rent_of_2_5_months() -> None:
    """``D = 0``, ``F = 2.5``: months 1 and 2 abate fully, month 3 abates a
    half, month 4 pays in full."""

    branch = new_branch(defaults=assumptions(new_free_rent_months=2.5))
    c = branch.commencement_period

    expected = [
        (0, 1.0, 0.0, 0.0),
        (1, 1.0, 0.0, 0.0),
        (2, 0.5, 0.5, 12_000.0),
        (3, 0.0, 1.0, 24_000.0),
    ]
    for offset, abatement, cash_factor, cash in expected:
        assert at(branch, "free_rent_abatement_months", c + offset) == strict(abatement)
        assert at(branch, "cash_rent_factor", c + offset) == strict(cash_factor)
        assert at(branch, "cash_base_rent", c + offset) == strict(cash)

    assert sum(branch.free_rent_abatement_months) == strict(2.5)


# =============================================================================
# GOLDEN 7 -- the mandatory combined case
# =============================================================================


def test_golden_7_mandatory_combined_downtime_and_free_rent() -> None:
    """**The D2 Section 7.2 reference case, asserted period by period.**

    Expiry June 30, ``D = 2.25``, ``F = 2.5``, 12,000 SF at $24/SF face.

    ``floor(2.25) = 2`` so ``c`` is September with ``O = 0.75``. September
    consumes **0.75** of a free month, not ``1.0`` -- one calendar period but
    only three-quarters of a month of occupancy (failure mode FM-D2-7b)."""

    branch = new_branch(
        defaults=assumptions(new_downtime_months=2.25, new_free_rent_months=2.5)
    )

    assert branch.expiration_period == EXPIRY_PERIOD
    assert branch.months[EXPIRY_PERIOD - 1].month_start == date(2028, 6, 1)
    assert branch.commencement_period == 21
    assert branch.months[20].month_start == date(2028, 9, 1)

    # month, O_m, abatement, cash factor, face $, free $, cash $
    expected = [
        (date(2028, 7, 1), 0.00, 0.00, 0.00, 0.0, 0.0, 0.0),
        (date(2028, 8, 1), 0.00, 0.00, 0.00, 0.0, 0.0, 0.0),
        (date(2028, 9, 1), 0.75, 0.75, 0.00, 24_000.0, 18_000.0, 0.0),
        (date(2028, 10, 1), 1.00, 1.00, 0.00, 24_000.0, 24_000.0, 0.0),
        (date(2028, 11, 1), 1.00, 0.75, 0.25, 24_000.0, 18_000.0, 6_000.0),
        (date(2028, 12, 1), 1.00, 0.00, 1.00, 24_000.0, 0.0, 24_000.0),
    ]
    by_month = {month.month_start: month.period_index for month in branch.months}

    for month, occupancy, abatement, cash_factor, face, free, cash in expected:
        period = by_month[month]
        assert at(branch, "successor_occupancy_factor", period) == strict(occupancy), month
        assert at(branch, "free_rent_abatement_months", period) == strict(abatement), month
        assert at(branch, "cash_rent_factor", period) == strict(cash_factor), month
        assert at(branch, "contractual_base_rent", period) == strict(face), month
        assert at(branch, "free_rent", period) == strict(free), month
        assert at(branch, "cash_base_rent", period) == strict(cash), month

    assert sum(branch.free_rent_abatement_months) == strict(2.5)


def test_golden_7_physical_occupancy_across_the_combined_case() -> None:
    """The vacancy is real and the abatement is not. July and August are
    physically vacant; September onward is physically occupied even while no
    cash is collected."""

    branch = new_branch(
        defaults=assumptions(new_downtime_months=2.25, new_free_rent_months=2.5)
    )
    by_month = {month.month_start: month.period_index for month in branch.months}

    assert at(branch, "physical_occupancy", by_month[date(2028, 6, 1)]) == 1.0
    assert at(branch, "physical_occupancy", by_month[date(2028, 7, 1)]) == 0.0
    assert at(branch, "physical_occupancy", by_month[date(2028, 8, 1)]) == 0.0
    for month in (date(2028, 9, 1), date(2028, 10, 1), date(2028, 11, 1)):
        assert at(branch, "physical_occupancy", by_month[month]) == 1.0


# =============================================================================
# The waterfall itself
# =============================================================================


def test_the_waterfall_is_sequential_not_multiplicative() -> None:
    """HD-D2-4. Multiplying independent factors would consume a whole free
    month in the fractional commencement period while abating only a fraction
    of a month's rent, shortchanging the concession."""

    occupancy = (0.0, 0.0, 0.75, 1.0, 1.0, 1.0)
    abatement, cash_factor = free_rent_waterfall(occupancy, free_rent_months=2.5)

    assert abatement == (0.0, 0.0, 0.75, 1.0, 0.75, 0.0)
    assert cash_factor == (0.0, 0.0, 0.0, 0.0, strict(0.25), 1.0)
    assert sum(abatement) == strict(2.5)

    multiplicative = tuple(o * (1.0 if i < 3 else 0.0) for i, o in enumerate(occupancy))
    assert abatement != multiplicative


@pytest.mark.parametrize("free_rent", [0.0, 0.25, 1.0, 2.5, 6.0, 11.75])
def test_the_waterfall_consumes_exactly_the_stated_concession(
    free_rent: float,
) -> None:
    """FM-D2-7c: ``sum(free_abatement_m) == free_rent_months`` exactly."""

    occupancy = (0.0, 0.0, 0.75) + (1.0,) * 20
    abatement, _ = free_rent_waterfall(occupancy, free_rent_months=free_rent)

    assert sum(abatement) == strict(free_rent)


def test_free_rent_is_not_consumed_during_downtime() -> None:
    """It may be consumed only while the successor is economically present.
    A fully vacant period has ``O_m = 0``, so nothing is consumed there --
    the concession is preserved for the months the tenant is actually in."""

    occupancy = (0.0, 0.0, 0.0, 1.0, 1.0)
    abatement, _ = free_rent_waterfall(occupancy, free_rent_months=2.0)

    assert abatement[:3] == (0.0, 0.0, 0.0)
    assert abatement[3:] == (1.0, 1.0)


def test_cash_factor_never_exceeds_occupancy_and_never_goes_negative() -> None:
    occupancy = (0.0, 0.5, 0.75, 1.0, 1.0, 1.0)
    for free_rent in (0.0, 0.1, 1.0, 2.5, 100.0):
        abatement, cash_factor = free_rent_waterfall(
            occupancy, free_rent_months=free_rent
        )
        for index, factor in enumerate(cash_factor):
            assert 0.0 <= factor <= occupancy[index] + 1e-12
            assert abatement[index] + factor == strict(occupancy[index])


@pytest.mark.parametrize("bad", [-0.01, float("nan"), float("inf")])
def test_the_waterfall_refuses_an_out_of_domain_concession(bad: float) -> None:
    with pytest.raises(ValueError):
        free_rent_waterfall((1.0, 1.0), free_rent_months=bad)


# =============================================================================
# GOLDEN 8 -- a market step during downtime
# =============================================================================


def test_golden_8_market_step_during_downtime_prices_at_commencement() -> None:
    """analysis 2027-07-01, market $40 growing 3%. The lease expires in period
    10 and downtime is 4 months, so ``c = 15`` -- in the **second** growth
    band.

    The successor prices at ``MarketRentPSF(15) = 41.20``: the band containing
    its commencement, not the band at expiry, and not day-count interpolated
    (D2 Section 9.2, failure mode FM-18)."""

    # analysis 2027-07-01: period 10 is Apr-2028, period 15 is Sep-2028.
    lease = expiring_lease(
        rent_commencement_date=date(2027, 7, 1),
        lease_expiration_date=date(2028, 4, 30),
    )
    branch = new_branch(
        analysis_start=JUL_START,
        hold_period=6,
        lease=lease,
        defaults=assumptions(
            market_rent_psf=40.0, market_rent_growth=0.03, new_downtime_months=4.0
        ),
    )

    assert branch.expiration_period == 10
    assert branch.commencement_period == 15
    assert branch.months[14].month_start == date(2028, 9, 1)

    assert branch.market_rent_psf_at_commencement == strict(41.2)
    assert branch.starting_rent_psf == strict(41.2)
    # Not the rate at expiry, which was still in the first band.
    assert branch.starting_rent_psf != strict(40.0)


def test_downtime_that_crosses_no_anniversary_keeps_the_expiry_band() -> None:
    """The converse: downtime entirely inside one band prices in that band."""

    lease = expiring_lease(
        rent_commencement_date=date(2027, 7, 1),
        lease_expiration_date=date(2028, 1, 31),
    )
    branch = new_branch(
        analysis_start=JUL_START,
        lease=lease,
        defaults=assumptions(
            market_rent_psf=40.0, market_rent_growth=0.03, new_downtime_months=2.0
        ),
    )

    assert branch.commencement_period == 10  # Apr-2028, still band 0
    assert branch.starting_rent_psf == strict(40.0)


def test_a_new_letting_never_reads_a_renewal_assumption() -> None:
    """A new letting *is* market. Applying a renewal spread or an explicit
    renewal level to a replacement tenant is exactly the cross-branch
    contamination the two-branch method exists to prevent."""

    branch = new_branch(
        defaults=assumptions(renewal_rent_psf=99.0, renewal_rent_spread=-0.5)
    )

    assert branch.starting_rent_psf == strict(24.0)
    assert new_tenant_starting_rent_psf(market_rent_psf_at_commencement=24.0) == 24.0
    assert not hasattr(branch, "renewal_rent_spread")
    assert not hasattr(branch, "renewal_rent_psf")


# =============================================================================
# GOLDEN 9 -- successor escalation versus market growth
# =============================================================================


def test_golden_9_successor_escalates_on_its_own_rate_not_the_market_rate() -> None:
    """Market growth 10%, successor escalation 2%, downtime 4 months.

    The successor prices off market at ``c``, then grows at **2%** on its own
    anniversaries -- not at 10%, and not along the market curve
    (failure mode FM-D2-14)."""

    lease = expiring_lease(
        rent_commencement_date=date(2027, 7, 1),
        lease_expiration_date=date(2028, 4, 30),
    )
    branch = new_branch(
        analysis_start=JUL_START,
        hold_period=8,
        lease=lease,
        defaults=assumptions(
            market_rent_psf=40.0,
            market_rent_growth=0.10,
            successor_escalation_pct=0.02,
            new_downtime_months=4.0,
        ),
    )

    c = branch.commencement_period
    assert c == 15
    assert branch.starting_rent_psf == strict(44.0)  # 40 * 1.10, band 1

    assert face_psf(branch, c) == strict(44.0)
    assert face_psf(branch, c + 11) == strict(44.0)
    assert face_psf(branch, c + 12) == strict(44.0 * 1.02)
    assert face_psf(branch, c + 12) != strict(44.0 * 1.10)
    assert face_psf(branch, c + 12) != strict(40.0 * 1.10**2)
    assert face_psf(branch, c + 24) == strict(44.0 * 1.02**2)


def test_the_market_schedule_keeps_growing_independently_of_the_successor() -> None:
    months = build_model_months(analysis_start=JUL_START, hold_period=8)
    the_suite = suite()
    defaults = assumptions(
        market_rent_psf=40.0,
        market_rent_growth=0.10,
        successor_escalation_pct=0.02,
        new_downtime_months=4.0,
    )
    market = build_market_rent_schedule(
        the_suite, property_defaults=defaults, months=months
    )
    branch = build_new_tenant_branch(
        expiring_lease(
            rent_commencement_date=date(2027, 7, 1),
            lease_expiration_date=date(2028, 4, 30),
        ),
        suite=the_suite,
        analysis_start=JUL_START,
        months=months,
        property_defaults=defaults,
        market_schedule=market,
    )

    assert market.market_rent_psf[26] == strict(40.0 * 1.10**2)  # period 27
    assert face_psf(branch, 27) == strict(44.0 * 1.02)
    assert market.market_rent_psf[26] != strict(face_psf(branch, 27))


# =============================================================================
# GOLDEN 10 -- a zero-rent successor
# =============================================================================


def test_golden_10_zero_market_rent_keeps_the_occupancy_mechanics_valid() -> None:
    """Zero face rent is a real market rent, never an inference of vacancy.
    The occupancy and waterfall series stay well-defined."""

    branch = new_branch(
        defaults=assumptions(
            market_rent_psf=0.0, new_downtime_months=2.25, new_free_rent_months=2.5
        )
    )

    assert branch.starting_rent_psf == 0.0
    c = branch.commencement_period

    assert at(branch, "successor_occupancy_factor", c) == strict(0.75)
    assert at(branch, "free_rent_abatement_months", c) == strict(0.75)
    assert at(branch, "physical_occupancy", c) == 1.0
    assert at(branch, "contractual_base_rent", c) == 0.0
    assert at(branch, "cash_base_rent", c) == 0.0
    assert at(branch, "free_rent", c) == 0.0
    assert sum(branch.free_rent_abatement_months) == strict(2.5)


# =============================================================================
# GOLDEN 11 -- free rent does not alter occupancy
# =============================================================================


def test_golden_11_free_rent_never_makes_occupied_space_vacant() -> None:
    """FM-D2-8, load-bearing for D3 recoveries: a tenant in a free-rent period
    is in possession, so a NNN successor keeps reimbursing operating expenses
    while paying no base rent."""

    without = new_branch(defaults=assumptions(new_free_rent_months=0.0))
    with_free = new_branch(defaults=assumptions(new_free_rent_months=12.0))

    assert with_free.physical_occupancy == without.physical_occupancy
    assert with_free.occupied_area == without.occupied_area
    assert with_free.successor_occupancy_factor == without.successor_occupancy_factor
    # Face rent is identical too; only cash differs.
    assert with_free.contractual_base_rent == without.contractual_base_rent
    assert with_free.cash_base_rent != without.cash_base_rent

    c = with_free.commencement_period
    assert at(with_free, "cash_base_rent", c) == 0.0
    assert at(with_free, "physical_occupancy", c) == 1.0


def test_free_rent_does_not_change_the_commencement_period() -> None:
    """Only downtime moves ``c``. Free rent is consumed after the successor is
    already in place."""

    for free_rent in (0.0, 1.0, 6.0, 24.0):
        branch = new_branch(defaults=assumptions(new_free_rent_months=free_rent))
        assert branch.commencement_period == EXPIRY_PERIOD + 1
        assert branch.successor_expiration_period == EXPIRY_PERIOD + 60


def test_downtime_and_free_rent_are_structurally_distinct() -> None:
    """D2 Section 7.4. One month of downtime and one month of free rent both
    collect zero base rent, but they differ in occupancy and in face rent."""

    downtime = new_branch(defaults=assumptions(new_downtime_months=1.0))
    free = new_branch(defaults=assumptions(new_free_rent_months=1.0))

    first = EXPIRY_PERIOD + 1
    assert at(downtime, "cash_base_rent", first) == 0.0
    assert at(free, "cash_base_rent", first) == 0.0

    # Downtime: nobody is there.
    assert at(downtime, "physical_occupancy", first) == 0.0
    assert at(downtime, "successor_occupancy_factor", first) == 0.0
    assert at(downtime, "contractual_base_rent", first) == 0.0
    assert at(downtime, "free_rent", first) == 0.0

    # Free rent: somebody is there, paying nothing.
    assert at(free, "physical_occupancy", first) == 1.0
    assert at(free, "successor_occupancy_factor", first) == 1.0
    assert at(free, "contractual_base_rent", first) == strict(24_000.0)
    assert at(free, "free_rent", first) == strict(24_000.0)


# =============================================================================
# Face rent versus cash rent
# =============================================================================


def test_face_rent_is_reduced_by_neither_downtime_nor_free_rent() -> None:
    """D2.4's LC basis reads ``contractual_base_rent`` and must not see a
    concession (failure modes FM-D2-10, FM-D2-11b)."""

    plain = new_branch()
    concessions = new_branch(
        defaults=assumptions(new_downtime_months=2.25, new_free_rent_months=6.0)
    )

    c_plain = plain.commencement_period
    c_conc = concessions.commencement_period

    # The same face rent per occupied month, in both branches.
    assert at(plain, "contractual_base_rent", c_plain) == strict(24_000.0)
    assert at(concessions, "contractual_base_rent", c_conc) == strict(24_000.0)
    # Including the fractional boundary month.
    assert at(concessions, "cash_base_rent", c_conc) == 0.0


def test_cash_equals_face_times_cash_factor_for_the_successor() -> None:
    branch = new_branch(
        hold_period=8,
        defaults=assumptions(new_downtime_months=2.25, new_free_rent_months=2.5),
    )

    for position in range(len(branch.months)):
        expiring_face = branch.expiring_schedule.contractual_base_rent[position]
        successor_face = branch.successor_schedule.contractual_base_rent[position]
        assert branch.contractual_base_rent[position] == strict(
            expiring_face + successor_face
        )
        assert branch.cash_base_rent[position] == strict(
            expiring_face + successor_face * branch.cash_rent_factor[position]
        )
        assert branch.free_rent[position] == strict(
            successor_face * branch.free_rent_abatement_months[position]
        )


def test_the_expiring_lease_collects_its_full_face_rent() -> None:
    """Concessions belong to the successor. A signed in-place lease is
    unaffected by any of them (D0 Section 24.4)."""

    branch = new_branch(
        defaults=assumptions(new_downtime_months=3.0, new_free_rent_months=6.0)
    )

    for period in range(1, EXPIRY_PERIOD + 1):
        expiring = branch.expiring_schedule.contractual_base_rent[period - 1]
        assert at(branch, "cash_base_rent", period) == strict(expiring)
        assert at(branch, "free_rent", period) == 0.0


# =============================================================================
# Occupancy naming -- HD-D2-2 / FM-D2-19
# =============================================================================


def test_branch_physical_occupancy_stays_integral_under_every_concession() -> None:
    """HD-D2-2's binding restriction, from the branch side: the fractional
    series is ``successor_occupancy_factor``, and ``physical_occupancy``
    remains a literal scenario state of 0 or 1."""

    for downtime in (0.0, 0.25, 2.25, 5.5, 3.0):
        for free_rent in (0.0, 2.5, 12.0):
            branch = new_branch(
                hold_period=8,
                defaults=assumptions(
                    new_downtime_months=downtime, new_free_rent_months=free_rent
                ),
            )
            assert set(branch.physical_occupancy) <= {0.0, 1.0}, (downtime, free_rent)
            assert set(branch.occupied_area) <= {0.0, AREA}


def test_the_boundary_month_is_physically_occupied_but_fractionally_recognised() -> None:
    """The distinction stated as one assertion: at ``c`` the successor is in
    possession by month-end, so physical occupancy is ``1``, while only
    ``1 - frac(D)`` of the month's rent is recognised."""

    branch = new_branch(defaults=assumptions(new_downtime_months=2.25))
    c = branch.commencement_period

    assert at(branch, "physical_occupancy", c) == 1.0
    assert at(branch, "occupied_area", c) == AREA
    assert at(branch, "successor_occupancy_factor", c) == strict(0.75)


# =============================================================================
# GOLDEN 12 -- free-rent over-grant
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


def test_golden_12_maximum_consumable_free_rent() -> None:
    """``max = T - frac(D)``. Term 12 with 2.25 months downtime absorbs
    ``11.75`` month-equivalents."""

    assert maximum_consumable_free_rent_months(
        term_months=12, downtime_months=2.25
    ) == strict(11.75)
    assert maximum_consumable_free_rent_months(
        term_months=12, downtime_months=3.0
    ) == strict(12.0)
    assert maximum_consumable_free_rent_months(
        term_months=60, downtime_months=0.5
    ) == strict(59.5)


def test_golden_12_free_rent_at_the_maximum_is_valid() -> None:
    result = validate(
        new_term_months=12, new_downtime_months=2.25, new_free_rent_months=11.75
    )
    assert result.is_valid, [issue.message for issue in result.errors]  # type: ignore[attr-defined]


@pytest.mark.parametrize("free_rent", [11.76, 12.0, 24.0])
def test_golden_12_free_rent_above_the_maximum_is_an_error(free_rent: float) -> None:
    """The concession is never silently discarded, capped, carried past
    expiration, or absorbed by extending the term."""

    result = validate(
        new_term_months=12, new_downtime_months=2.25, new_free_rent_months=free_rent
    )

    assert not result.is_valid  # type: ignore[attr-defined]
    assert LeaseIssueCode.FREE_RENT_EXCEEDS_OCCUPIABLE_TERM in codes(result)


def test_the_over_grant_rule_applies_to_the_renewal_branch_too() -> None:
    result = validate(
        renewal_term_months=6, renewal_downtime_months=0.5, renewal_free_rent_months=6.0
    )

    assert not result.is_valid  # type: ignore[attr-defined]
    issue = next(
        item
        for item in result.issues  # type: ignore[attr-defined]
        if item.code is LeaseIssueCode.FREE_RENT_EXCEEDS_OCCUPIABLE_TERM
    )
    assert issue.path == "market_leasing.renewal_free_rent_months"


def test_the_over_grant_bound_is_exactly_the_waterfall_capacity() -> None:
    """The validation bound and the waterfall's actual capacity must agree, or
    a valid input could still lose part of its concession."""

    for term, downtime in ((12, 2.25), (6, 0.5), (24, 0.0), (36, 5.5)):
        maximum = maximum_consumable_free_rent_months(
            term_months=term, downtime_months=downtime
        )
        occupancy = successor_occupancy_factors(
            months=build_model_months(analysis_start=JAN_START, hold_period=20),
            commencement_period=1,
            last_rent_period=term,
            downtime_months=downtime,
        )
        abatement, _ = free_rent_waterfall(occupancy, free_rent_months=maximum)
        assert sum(abatement) == strict(maximum), (term, downtime)
        assert sum(occupancy) == strict(maximum)


# =============================================================================
# GOLDEN 13 -- the horizon ends during free rent
# =============================================================================


def test_golden_13_the_bound_uses_the_full_term_not_the_visible_projection() -> None:
    """A 60-month successor of which only a few months fall inside the window
    may legitimately carry a 12-month concession. The input is valid and the
    visible schedule simply ends mid-abatement."""

    result = validate(
        new_term_months=60, new_downtime_months=0.0, new_free_rent_months=24.0
    )
    assert result.is_valid, [issue.message for issue in result.errors]  # type: ignore[attr-defined]

    # hold 2 -> 36 canonical months; the successor commences at period 19 and
    # would consume its 24 months of free rent through period 42.
    branch = new_branch(
        hold_period=2,
        defaults=assumptions(new_term_months=60, new_free_rent_months=24.0),
    )

    assert len(branch.months) == 36
    assert branch.commencement_period == 19
    assert branch.successor_expiration_period == 78  # far beyond the horizon

    # Every visible successor month is abated, and no cash is collected.
    for period in range(19, 37):
        assert at(branch, "free_rent_abatement_months", period) == 1.0
        assert at(branch, "cash_base_rent", period) == 0.0

    # The visible window shows only 18 of the 24 month-equivalents. The
    # remainder is consumed after the horizon, and that is not an error: the
    # bound is the full contractual term, not the visible projection.
    assert sum(branch.free_rent_abatement_months) == strict(18.0)
    assert branch.free_rent_months == 24.0


def test_golden_13_a_concession_larger_than_the_full_term_is_still_an_error() -> None:
    """The horizon exemption does not weaken the over-grant rule: a concession
    the *contract* cannot absorb is refused however long the projection is."""

    result = validate(
        new_term_months=12, new_downtime_months=0.0, new_free_rent_months=24.0
    )

    assert not result.is_valid  # type: ignore[attr-defined]
    assert LeaseIssueCode.FREE_RENT_EXCEEDS_OCCUPIABLE_TERM in codes(result)


# =============================================================================
# GOLDEN 14 -- the renewal zero/zero regression
# =============================================================================


def test_golden_14_zero_downtime_zero_free_rent_reproduces_d2_2_renewal() -> None:
    """**The D2.2 baseline must survive D2.3 exactly.**

    With ``renewal_downtime_months = 0`` and ``renewal_free_rent_months = 0``
    the renewal branch commences at ``e + 1``, is fully occupied from there,
    and collects its face rent in full."""

    branch = renewal_branch(defaults=assumptions(successor_escalation_pct=0.04))

    assert branch.downtime_months == 0.0
    assert branch.free_rent_months == 0.0
    assert branch.commencement_period == EXPIRY_PERIOD + 1

    for period in range(EXPIRY_PERIOD + 1, EXPIRY_PERIOD + 25):
        assert at(branch, "successor_occupancy_factor", period) == 1.0
        assert at(branch, "cash_rent_factor", period) == 1.0
        assert at(branch, "free_rent_abatement_months", period) == 0.0

    assert branch.cash_base_rent == branch.contractual_base_rent
    assert all(value == 0.0 for value in branch.free_rent)
    assert set(branch.physical_occupancy) <= {0.0, 1.0}
    # Continuous occupancy: no vacant month anywhere across the rollover.
    for period in range(1, EXPIRY_PERIOD + 25):
        assert at(branch, "physical_occupancy", period) == 1.0


def test_golden_14_cash_is_hex_identical_to_face_at_zero_zero() -> None:
    """Bit-level, not merely equal: at zero/zero the concession machinery must
    not perturb a single float."""

    branch = renewal_branch(defaults=assumptions(successor_escalation_pct=0.04))

    for face, cash in zip(branch.contractual_base_rent, branch.cash_base_rent):
        assert face.hex() == cash.hex()


# =============================================================================
# GOLDENS 15 and 16 -- renewal with downtime and free rent
# =============================================================================


def test_golden_15_renewal_downtime_delays_commencement_and_creates_vacancy() -> None:
    branch = renewal_branch(defaults=assumptions(renewal_downtime_months=2.25))

    assert branch.commencement_period == EXPIRY_PERIOD + 3
    assert at(branch, "physical_occupancy", EXPIRY_PERIOD + 1) == 0.0
    assert at(branch, "physical_occupancy", EXPIRY_PERIOD + 2) == 0.0
    assert at(branch, "successor_occupancy_factor", EXPIRY_PERIOD + 3) == strict(0.75)
    assert at(branch, "physical_occupancy", EXPIRY_PERIOD + 3) == 1.0


def test_golden_15_renewal_downtime_can_reprice_across_a_market_step() -> None:
    """A delayed renewal prices in the later band, because ``c`` moved."""

    lease = expiring_lease(
        rent_commencement_date=date(2027, 7, 1),
        lease_expiration_date=date(2028, 4, 30),
    )
    immediate = renewal_branch(
        analysis_start=JUL_START,
        lease=lease,
        defaults=assumptions(market_rent_psf=40.0, market_rent_growth=0.03),
    )
    delayed = renewal_branch(
        analysis_start=JUL_START,
        lease=lease,
        defaults=assumptions(
            market_rent_psf=40.0, market_rent_growth=0.03, renewal_downtime_months=4.0
        ),
    )

    assert immediate.commencement_period == 11
    assert immediate.starting_rent_psf == strict(40.0)
    assert delayed.commencement_period == 15
    assert delayed.starting_rent_psf == strict(41.2)


def test_golden_16_renewal_free_rent_abates_cash_but_not_face() -> None:
    branch = renewal_branch(defaults=assumptions(renewal_free_rent_months=2.5))
    c = branch.commencement_period

    assert at(branch, "physical_occupancy", c) == 1.0
    assert at(branch, "contractual_base_rent", c) == strict(24_000.0)
    assert at(branch, "cash_base_rent", c) == 0.0
    assert at(branch, "free_rent", c) == strict(24_000.0)
    assert at(branch, "cash_base_rent", c + 2) == strict(12_000.0)
    assert at(branch, "cash_base_rent", c + 3) == strict(24_000.0)
    assert sum(branch.free_rent_abatement_months) == strict(2.5)


def test_the_two_branches_share_the_same_mechanics() -> None:
    """Identical downtime and free rent produce identical timing, occupancy and
    concession series on both branches. Only the pricing rule differs, and here
    it is made identical too (renewal at market, spread 0)."""

    defaults = assumptions(
        renewal_term_months=60,
        new_term_months=60,
        renewal_downtime_months=2.25,
        new_downtime_months=2.25,
        renewal_free_rent_months=2.5,
        new_free_rent_months=2.5,
    )
    renewal = renewal_branch(hold_period=8, defaults=defaults)
    new_tenant = new_branch(hold_period=8, defaults=defaults)

    assert renewal.commencement_period == new_tenant.commencement_period
    assert renewal.successor_expiration_period == new_tenant.successor_expiration_period
    assert renewal.successor_occupancy_factor == new_tenant.successor_occupancy_factor
    assert (
        renewal.free_rent_abatement_months == new_tenant.free_rent_abatement_months
    )
    assert renewal.cash_rent_factor == new_tenant.cash_rent_factor
    assert renewal.physical_occupancy == new_tenant.physical_occupancy
    assert renewal.starting_rent_psf == new_tenant.starting_rent_psf
    assert renewal.cash_base_rent == new_tenant.cash_base_rent


def test_the_two_branches_keep_their_own_successor_ids() -> None:
    """A renewal successor and a new-tenant successor for the same expiring
    lease must never be confused in an audit trail."""

    assert renewal_branch().successor_lease_id == "L1::renewal"
    assert new_branch().successor_lease_id == "L1::new"


# =============================================================================
# Adversarial cases
# =============================================================================


@pytest.mark.parametrize(
    ("expiry", "downtime", "expected_commencement"),
    [
        (date(2028, 12, 31), 0.0, date(2029, 1, 1)),  # December -> January
        (date(2027, 12, 31), 1.0, date(2028, 2, 1)),
        (date(2028, 1, 31), 1.0, date(2028, 3, 1)),  # into leap February
        (date(2028, 2, 29), 0.0, date(2028, 3, 1)),  # leap February expiry
        (date(2029, 2, 28), 0.0, date(2029, 3, 1)),  # common February expiry
        (date(2028, 6, 30), 6.0, date(2029, 1, 1)),  # across a year boundary
    ],
)
def test_calendar_chronology_across_downtime(
    expiry: date, downtime: float, expected_commencement: date
) -> None:
    branch = new_branch(
        hold_period=8,
        lease=expiring_lease(lease_expiration_date=expiry),
        defaults=assumptions(new_downtime_months=downtime),
    )

    assert branch.successor_lease.rent_commencement_date == expected_commencement


def test_a_successor_commencing_in_the_forward_window_is_modelled_normally() -> None:
    """Rollover stays fully live in periods ``12H+1 .. 12H+12``
    (D2 Section 11). Downtime depresses forward-window rent, with no smoothing
    to stabilise terminal value."""

    # hold 2 -> hold months 1-24, forward window 25-36. e = 18, D = 8 -> c = 27.
    branch = new_branch(hold_period=2, defaults=assumptions(new_downtime_months=8.0))

    assert branch.commencement_period == 27
    assert branch.months[26].is_forward_exit_month is True
    assert branch.commences_within_projection is True
    for period in range(19, 27):
        assert at(branch, "physical_occupancy", period) == 0.0
    assert at(branch, "cash_base_rent", 27) == strict(24_000.0)


def test_a_successor_commencing_in_the_final_canonical_month() -> None:
    # hold 2 -> 36 months. e = 18, D = 17 -> c = 36.
    branch = new_branch(hold_period=2, defaults=assumptions(new_downtime_months=17.0))

    assert branch.commencement_period == 36
    assert len(branch.months) == 36
    assert branch.commences_within_projection is True
    assert at(branch, "cash_base_rent", 36) == strict(24_000.0)


def test_a_successor_commencing_past_the_horizon_contributes_nothing() -> None:
    """The projection is never extended and no month is fabricated, but the
    successor's contractual metadata is fully retained."""

    # hold 2 -> 36 months. e = 18, D = 18 -> c = 37, one past the horizon.
    branch = new_branch(hold_period=2, defaults=assumptions(new_downtime_months=18.0))

    assert branch.commencement_period == 37
    assert branch.commences_within_projection is False
    assert branch.successor_expiration_period == 96
    assert branch.successor_lease.rent_commencement_date == date(2030, 1, 1)

    for value in branch.successor_schedule.contractual_base_rent:
        assert value == 0.0
    assert all(value == 0.0 for value in branch.successor_occupancy_factor)
    assert all(value == 0.0 for value in branch.free_rent_abatement_months)
    assert branch.cash_base_rent == branch.expiring_schedule.contractual_base_rent


def test_downtime_running_past_the_horizon_leaves_the_suite_vacant() -> None:
    """Every period after expiry is genuinely vacant, and nothing is
    fabricated past the horizon."""

    branch = new_branch(hold_period=2, defaults=assumptions(new_downtime_months=18.0))

    for period in range(EXPIRY_PERIOD + 1, 37):
        assert at(branch, "physical_occupancy", period) == 0.0
        assert at(branch, "contractual_base_rent", period) == 0.0
        assert at(branch, "cash_base_rent", period) == 0.0


@pytest.mark.parametrize("downtime", [0.25, 0.5, 0.75, 0.9, 0.999])
def test_sub_month_downtime_keeps_immediate_commencement(downtime: float) -> None:
    """``floor(D) = 0``, so the successor still commences at ``e + 1`` -- but
    with a reduced boundary factor."""

    branch = new_branch(defaults=assumptions(new_downtime_months=downtime))
    c = branch.commencement_period

    assert c == EXPIRY_PERIOD + 1
    assert at(branch, "successor_occupancy_factor", c) == strict(1.0 - downtime)
    assert at(branch, "physical_occupancy", c) == 1.0
    assert at(branch, "cash_base_rent", c) == strict(24_000.0 * (1.0 - downtime))
    # No fully vacant month at all.
    assert at(branch, "physical_occupancy", EXPIRY_PERIOD) == 1.0


def test_a_one_month_successor_term_is_valid() -> None:
    branch = new_branch(defaults=assumptions(new_term_months=1))
    c = branch.commencement_period

    assert branch.successor_expiration_period == c
    assert at(branch, "successor_occupancy_factor", c) == 1.0
    assert at(branch, "successor_occupancy_factor", c + 1) == 0.0
    assert at(branch, "cash_base_rent", c + 1) == 0.0


def test_repeated_build_is_value_equal() -> None:
    defaults = assumptions(new_downtime_months=2.25, new_free_rent_months=2.5)
    first = new_branch(defaults=defaults)
    second = new_branch(defaults=defaults)

    assert first == second
    for left, right in zip(first.cash_base_rent, second.cash_base_rent):
        assert left.hex() == right.hex()


def test_inputs_are_never_mutated() -> None:
    lease = expiring_lease()
    the_suite = suite()
    defaults = assumptions(new_downtime_months=2.25, new_free_rent_months=2.5)
    before_lease = dataclasses.replace(lease)
    before_defaults = dataclasses.replace(defaults)

    new_branch(lease=lease, the_suite=the_suite, defaults=defaults)

    assert lease == before_lease
    assert defaults == before_defaults
    assert the_suite.market_leasing_override is None


def test_the_branch_is_frozen() -> None:
    branch = new_branch()

    with pytest.raises(dataclasses.FrozenInstanceError):
        branch.starting_rent_psf = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        branch.successor_lease.base_rent_psf = 1.0  # type: ignore[misc]


def test_a_branch_rejects_a_mismatched_series_length() -> None:
    branch = new_branch()

    with pytest.raises(ValueError):
        dataclasses.replace(branch, cash_base_rent=(0.0,))


def test_the_successor_is_never_presented_as_a_known_tenant() -> None:
    branch = new_branch()

    assert branch.successor_lease.tenant_name is None
    assert branch.successor_lease.origin is LeaseOrigin.SUCCESSOR


def test_the_generated_successor_passes_leasing_validation() -> None:
    branch = new_branch(hold_period=10, defaults=assumptions(new_downtime_months=2.25))
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(
            analysis_start_date=JAN_START, rentable_area_sf=AREA
        ),
        [suite("S1")],
        [branch.successor_lease],
        market_leasing=assumptions(),
    )

    assert result.is_valid, [issue.message for issue in result.errors]


# =============================================================================
# Validation -- the D2.3 domains
# =============================================================================


@pytest.mark.parametrize(
    "field", ["renewal_downtime_months", "new_downtime_months"]
)
@pytest.mark.parametrize("bad", [-0.01, -1.0])
def test_negative_downtime_is_an_error(field: str, bad: float) -> None:
    result = validate(**{field: bad})
    assert LeaseIssueCode.DOWNTIME_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize(
    "field", ["renewal_free_rent_months", "new_free_rent_months"]
)
@pytest.mark.parametrize("bad", [-0.01, -2.0])
def test_negative_free_rent_is_an_error(field: str, bad: float) -> None:
    result = validate(**{field: bad})
    assert LeaseIssueCode.FREE_RENT_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize(
    "field",
    [
        "renewal_downtime_months",
        "new_downtime_months",
        "renewal_free_rent_months",
        "new_free_rent_months",
    ],
)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_months_are_errors(field: str, bad: float) -> None:
    result = validate(**{field: bad})
    assert LeaseIssueCode.NON_FINITE_VALUE in codes(result)


@pytest.mark.parametrize("value", [0.0, 0.25, 1.0, 2.25, 5.5, 12.0])
def test_non_negative_downtime_is_valid(value: float) -> None:
    assert validate(new_downtime_months=value).is_valid  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", [0, -1, -12])
def test_a_non_positive_new_term_is_an_error(bad: int) -> None:
    result = validate(new_term_months=bad)
    assert LeaseIssueCode.NEW_TERM_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("bad", [12.0, 12.5, "12", True])
def test_a_non_integer_new_term_is_an_error(bad: object) -> None:
    result = validate(new_term_months=bad)
    assert LeaseIssueCode.NEW_TERM_OUT_OF_DOMAIN in codes(result)


def test_d2_3_issues_are_errors_never_warnings() -> None:
    result = validate(
        new_downtime_months=-1.0, new_free_rent_months=-1.0, new_term_months=0
    )

    for issue in result.issues:  # type: ignore[attr-defined]
        assert issue.severity is LeaseIssueSeverity.ERROR


def test_a_suite_override_is_checked_against_the_d2_3_domains() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite("S1", market_leasing_override=assumptions(new_downtime_months=-1.0))],
        [],
        market_leasing=assumptions(),
    )

    issue = next(
        item
        for item in result.issues
        if item.code is LeaseIssueCode.DOWNTIME_OUT_OF_DOMAIN
    )
    assert issue.path == "suites[0].market_leasing_override.new_downtime_months"


def test_an_incomplete_assumption_record_cannot_be_constructed() -> None:
    """The all-or-nothing override rule stays structural as the record grows:
    every D2.3 field is required and none has a default."""

    complete = {
        "market_rent_psf": 24.0,
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
    }
    for omitted in (
        "renewal_downtime_months",
        "renewal_free_rent_months",
        "new_term_months",
        "new_downtime_months",
        "new_free_rent_months",
    ):
        fields = dict(complete)
        del fields[omitted]
        with pytest.raises(TypeError):
            MarketLeasingAssumptions(**fields)  # type: ignore[arg-type]
