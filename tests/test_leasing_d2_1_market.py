"""Sprint D Gate D2.1 -- the canonical monthly market-rent schedule.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Section 9 and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 7.1-7.4 and 24.1-24.5, that market rent is an assumption **rate**
schedule anchored to ``analysis_start_date``.

The financial claims that matter most:

- growth is an **annual step on analysis-start anniversaries**, never monthly
  compounding and never a lease anniversary (Goldens 2, 3, 4 -- failure modes
  FM-D2-12, FM-D2-13);
- a **non-January analysis start** steps in its own month, not in January
  (Golden 3);
- the schedule **keeps growing through the forward exit window** (Golden 8);
- market rent and contractual rent **never contaminate each other**
  (Golden 10 -- failure mode FM-D2-14, and FM-D2-20's untouched D1 formula).

Every expected value below is hand-calculable from the Section 9.1 formula
alone, and the 3% figures are exactly the ones tabulated in D2 Section 9.1.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.engine.contracts import NonFiniteResultError
from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseLevelPropertyInputs,
    LeaseType,
    MarketAssumptionSource,
    MarketLeasingAssumptions,
    MarketRentSchedule,
    Suite,
    build_lease_monthly_schedule,
    build_market_rent_schedule,
    build_model_months,
    build_property_market_rent_schedules,
    market_growth_index,
    market_rent_psf_at_period,
    market_rent_psf_for_period,
    resolve_market_leasing,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    validate_lease_level_inputs,
)


JAN_START = date(2027, 1, 1)
JUL_START = date(2027, 7, 1)
AREA = 10_000.0


def strict(expected: float) -> object:
    """The tolerance convention of ``tests/test_engine_golden_case.py`` and
    ``tests/test_leasing_d1_2_rent.py``: tight enough to reject
    presentation-scale rounding, loose enough for ordinary IEEE-754 last-bit
    noise."""

    return pytest.approx(expected, rel=0.0, abs=1e-9)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    """A property-default record.

    The renewal fields arrived at D2.2 and the concession fields at D2.3; all
    are required on the record (the all-or-nothing override rule is
    structural). **D2.1 reads none of them**, so every market-rent expectation
    in this module is unaffected by their presence -- which the isolation test
    at the end asserts directly."""

    base: dict[str, object] = {
        "market_rent_psf": 40.0,
        "market_rent_growth": 0.03,
        # D2.2 renewal fields -- inert for every assertion in this module.
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.0,
        # D2.3 concession fields -- inert for every assertion in this module.
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


def schedule_for(
    *,
    analysis_start: date = JAN_START,
    hold_period: int = 5,
    the_suite: Suite | None = None,
    defaults: MarketLeasingAssumptions | None = None,
) -> MarketRentSchedule:
    return build_market_rent_schedule(
        the_suite if the_suite is not None else suite(),
        property_defaults=defaults if defaults is not None else assumptions(),
        months=build_model_months(
            analysis_start=analysis_start, hold_period=hold_period
        ),
    )


def rent_at(schedule: MarketRentSchedule, period: int) -> float:
    return schedule.market_rent_psf[period - 1]


# =============================================================================
# The growth index -- floor((m - 1) / 12)
# =============================================================================


@pytest.mark.parametrize(
    ("period", "expected_k"),
    [
        (1, 0), (2, 0), (11, 0), (12, 0),
        (13, 1), (24, 1),
        (25, 2), (36, 2),
        (37, 3), (48, 3),
        (121, 10),
    ],
)
def test_growth_index_is_completed_analysis_years(period: int, expected_k: int) -> None:
    """D2 Section 9.1: periods 1-12 use ``k = 0``, 13-24 use ``k = 1``, and so
    on. This is the off-by-one that failure mode FM-D2-12 lives in."""

    assert market_growth_index(period) == expected_k


def test_growth_index_is_constant_within_every_twelve_period_band() -> None:
    """The defining property of *step* growth: the index changes only on a
    band boundary, never inside one."""

    for band in range(0, 10):
        indices = {
            market_growth_index(band * 12 + offset) for offset in range(1, 13)
        }
        assert indices == {band}


@pytest.mark.parametrize("period", [0, -1, -12])
def test_growth_index_rejects_periods_before_the_analysis_start(period: int) -> None:
    """"The market rent before the analysis start" is not a concept this model
    has. Extrapolating backwards through a negative exponent would invent one,
    so the boundary refuses instead."""

    with pytest.raises(ValueError):
        market_growth_index(period)


@pytest.mark.parametrize("period", [1.0, "1", True, None])
def test_growth_index_rejects_a_non_integer_period(period: object) -> None:
    with pytest.raises(TypeError):
        market_growth_index(period)  # type: ignore[arg-type]


# =============================================================================
# GOLDEN 1 -- flat market rent
# =============================================================================


def test_golden_1_zero_growth_is_flat_in_every_month() -> None:
    """analysis 2027-01-01, $40.00, 0% -> $40.00 in every canonical month,
    exactly, including the forward exit window."""

    schedule = schedule_for(defaults=assumptions(market_rent_growth=0.0))

    assert len(schedule.market_rent_psf) == 72
    for value in schedule.market_rent_psf:
        assert value == 40.0


# =============================================================================
# GOLDEN 2 -- 3% annual step
# =============================================================================


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (1, 40.0), (12, 40.0),
        (13, 41.2), (24, 41.2),
        (25, 42.436), (36, 42.436),
        (37, 43.70908), (48, 43.70908),
    ],
)
def test_golden_2_three_percent_annual_step(period: int, expected: float) -> None:
    """The D2 Section 9.1 table, asserted period by period.

    ``40.000000 / 41.200000 / 42.436000 / 43.709080`` -- **not** the monthly
    compounding ``40 * 1.03 ** ((m - 1) / 12)``, which would put Month 2 at
    ``40.0987...`` rather than at exactly ``40.00``."""

    assert rent_at(schedule_for(), period) == strict(expected)


def test_golden_2_is_flat_within_each_band_not_monthly_compounded() -> None:
    """FM-D2-12 stated directly: every month inside a 12-period band carries
    the identical rate, so no month-over-month drift exists to compound."""

    schedule = schedule_for()
    for band_start in (1, 13, 25, 37, 49, 61):
        band = {
            rent_at(schedule, band_start + offset) for offset in range(12)
        }
        assert len(band) == 1, f"band starting at {band_start} is not flat"

    monthly_compounded_month_2 = 40.0 * 1.03 ** (1 / 12)
    assert rent_at(schedule, 2) != strict(monthly_compounded_month_2)
    assert rent_at(schedule, 2) == 40.0


# =============================================================================
# GOLDEN 3 -- non-January analysis start
# =============================================================================


def test_golden_3_non_january_start_steps_on_its_own_anniversary() -> None:
    """analysis 2027-07-01, $40.00, 3%.

    Jul-2027 through Jun-2028 is ``40.00``; Jul-2028 through Jun-2029 is
    ``41.20``. Market rent is analysis-anniversary-relative exactly as hold
    years are."""

    schedule = schedule_for(analysis_start=JUL_START)
    by_month = {
        month.month_start: value
        for month, value in zip(schedule.months, schedule.market_rent_psf)
    }

    assert by_month[date(2027, 7, 1)] == strict(40.0)
    assert by_month[date(2028, 6, 1)] == strict(40.0)
    assert by_month[date(2028, 7, 1)] == strict(41.2)
    assert by_month[date(2029, 6, 1)] == strict(41.2)
    assert by_month[date(2029, 7, 1)] == strict(42.436)


def test_golden_3_no_january_step_occurs() -> None:
    """The trap stated as its own assertion: January 2028 must carry the same
    rate as December 2027, because the calendar year is not the market
    clock (FM-D2-13)."""

    schedule = schedule_for(analysis_start=JUL_START)
    by_month = {
        month.month_start: value
        for month, value in zip(schedule.months, schedule.market_rent_psf)
    }

    assert by_month[date(2027, 12, 1)] == strict(40.0)
    assert by_month[date(2028, 1, 1)] == strict(40.0)
    assert by_month[date(2029, 1, 1)] == strict(41.2)


def test_golden_3_every_step_lands_in_the_analysis_start_month() -> None:
    """Generalised over the whole schedule: the rate changes only between a
    June and a July, never at any other month boundary."""

    schedule = schedule_for(analysis_start=JUL_START, hold_period=6)
    previous_value = schedule.market_rent_psf[0]

    for month, value in zip(schedule.months[1:], schedule.market_rent_psf[1:]):
        if value != previous_value:
            assert month.month_start.month == 7, (
                f"market rent stepped in {month.month_start}, which is not an "
                "anniversary of the 2027-07-01 analysis start"
            )
        previous_value = value


# =============================================================================
# GOLDEN 4 -- the month 12 / 13 boundary
# =============================================================================


def test_golden_4_month_12_to_13_boundary_at_100_percent_growth() -> None:
    """A deliberately unmissable rate. Month 12 is ``40.00``; Month 13 is
    ``80.00``. Any off-by-one in ``floor((m - 1) / 12)`` doubles or halves an
    entire year."""

    schedule = schedule_for(defaults=assumptions(market_rent_growth=1.0))

    assert rent_at(schedule, 11) == strict(40.0)
    assert rent_at(schedule, 12) == strict(40.0)
    assert rent_at(schedule, 13) == strict(80.0)
    assert rent_at(schedule, 24) == strict(80.0)
    assert rent_at(schedule, 25) == strict(160.0)


# =============================================================================
# GOLDEN 5 -- negative market growth
# =============================================================================


def test_golden_5_negative_growth_declines_by_analysis_year() -> None:
    """``> -1`` is the domain D0 Section 4.5 assigns, the same lower bound
    every other Anchor compounding rate carries. $40 at -5%: 40.00, 38.00,
    36.10 by successive analysis years."""

    schedule = schedule_for(defaults=assumptions(market_rent_growth=-0.05))

    assert rent_at(schedule, 1) == strict(40.0)
    assert rent_at(schedule, 12) == strict(40.0)
    assert rent_at(schedule, 13) == strict(38.0)
    assert rent_at(schedule, 25) == strict(36.1)
    assert rent_at(schedule, 37) == strict(34.295)


# =============================================================================
# GOLDEN 6 -- the property default
# =============================================================================


def test_golden_6_suites_without_overrides_share_the_property_schedule() -> None:
    """Many suites, no overrides: every market-rent series is identical, and
    each records ``PROPERTY_DEFAULT`` as its source."""

    months = build_model_months(analysis_start=JAN_START, hold_period=5)
    defaults = assumptions()
    schedules = build_property_market_rent_schedules(
        LeaseLevelPropertyInputs(
            analysis_start_date=JAN_START, rentable_area_sf=3 * AREA
        ),
        [suite("A"), suite("B"), suite("C")],
        property_defaults=defaults,
        months=months,
    )

    assert [item.suite_id for item in schedules] == ["A", "B", "C"]
    first = schedules[0].market_rent_psf
    for item in schedules:
        assert item.market_rent_psf == first
        assert item.resolved.source is MarketAssumptionSource.PROPERTY_DEFAULT
        assert item.resolved.market_rent_psf_from_suite is False
        assert item.resolved.assumptions == defaults


def test_a_timeline_from_a_different_anchor_is_rejected() -> None:
    """Market rent is anchored to ``analysis_start_date`` and to nothing else.
    A timeline built from a different anchor would shift every growth band
    while each individual value still looked plausible -- FM-D2-13 in its most
    silent form -- so the mismatch fails loudly rather than being rebuilt."""

    mismatched = build_model_months(analysis_start=JUL_START, hold_period=5)

    with pytest.raises(ValueError, match="same analysis start"):
        build_property_market_rent_schedules(
            LeaseLevelPropertyInputs(
                analysis_start_date=JAN_START, rentable_area_sf=AREA
            ),
            [suite("A")],
            property_defaults=assumptions(),
            months=mismatched,
        )


def test_an_empty_timeline_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_property_market_rent_schedules(
            LeaseLevelPropertyInputs(
                analysis_start_date=JAN_START, rentable_area_sf=AREA
            ),
            [suite("A")],
            property_defaults=assumptions(),
            months=(),
        )


# =============================================================================
# GOLDEN 7 -- the suite override
# =============================================================================


def test_golden_7_suite_override_precedence_is_exact() -> None:
    """Property default $40 / 3%. Suite A inherits. Suite B overrides the rent
    level alone (D0 Section 24.1). Suite C overrides the whole record
    (Section 24.2, all-or-nothing). Suite D does both, and the rent-level
    exception wins over the override's own rent."""

    defaults = assumptions()
    override = assumptions(market_rent_psf=60.0, market_rent_growth=0.05)

    a = resolve_market_leasing(suite("A"), property_defaults=defaults)
    assert a.assumptions == defaults
    assert a.source is MarketAssumptionSource.PROPERTY_DEFAULT
    assert a.market_rent_psf_from_suite is False

    b = resolve_market_leasing(
        suite("B", market_rent_psf=52.0), property_defaults=defaults
    )
    assert b.assumptions.market_rent_psf == 52.0
    assert b.assumptions.market_rent_growth == 0.03  # falls through, per 24.1
    assert b.source is MarketAssumptionSource.PROPERTY_DEFAULT
    assert b.market_rent_psf_from_suite is True

    c = resolve_market_leasing(
        suite("C", market_leasing_override=override), property_defaults=defaults
    )
    assert c.assumptions == override  # used in full; nothing falls through
    assert c.source is MarketAssumptionSource.SUITE_OVERRIDE
    assert c.market_rent_psf_from_suite is False

    d = resolve_market_leasing(
        suite("D", market_rent_psf=52.0, market_leasing_override=override),
        property_defaults=defaults,
    )
    assert d.assumptions.market_rent_psf == 52.0
    assert d.assumptions.market_rent_growth == 0.05
    assert d.source is MarketAssumptionSource.SUITE_OVERRIDE
    assert d.market_rent_psf_from_suite is True


def test_golden_7_override_drives_the_whole_monthly_series() -> None:
    """Precedence is not merely recorded -- it is what the months are built
    from. The override's own growth rate governs its bands."""

    defaults = assumptions()
    override = assumptions(market_rent_psf=60.0, market_rent_growth=0.05)

    inherited = schedule_for(the_suite=suite("A"), defaults=defaults)
    rent_only = schedule_for(
        the_suite=suite("B", market_rent_psf=52.0), defaults=defaults
    )
    full = schedule_for(
        the_suite=suite("C", market_leasing_override=override), defaults=defaults
    )

    assert rent_at(inherited, 1) == strict(40.0)
    assert rent_at(inherited, 13) == strict(41.2)

    assert rent_at(rent_only, 1) == strict(52.0)
    assert rent_at(rent_only, 13) == strict(52.0 * 1.03)

    assert rent_at(full, 1) == strict(60.0)
    assert rent_at(full, 13) == strict(63.0)
    assert rent_at(full, 25) == strict(66.15)


def test_golden_7_an_override_never_mutates_the_property_assumption() -> None:
    """The resolver reads; it does not write. The property default and the
    suite records are unchanged by any number of resolutions, and a third
    suite still inherits the original."""

    defaults = assumptions()
    before = dataclasses.replace(defaults)
    override = assumptions(market_rent_psf=60.0, market_rent_growth=0.05)
    overridden = suite("B", market_leasing_override=override)

    resolve_market_leasing(overridden, property_defaults=defaults)
    resolve_market_leasing(
        suite("C", market_rent_psf=1.0), property_defaults=defaults
    )

    assert defaults == before
    assert overridden.market_leasing_override == override

    later = resolve_market_leasing(suite("Z"), property_defaults=defaults)
    assert later.assumptions == before


# =============================================================================
# GOLDEN 8 -- the forward exit window
# =============================================================================


def test_golden_8_growth_steps_inside_the_forward_exit_window() -> None:
    """analysis 2027-07-01, hold 3. The forward window is periods 37-48, and
    period 37 (Jul-2030) is itself a growth anniversary.

    Market rent must step there normally: rollover stays fully live in the
    window (D2 Section 11), so a successor commencing there prices from a
    market rent that kept growing."""

    schedule = schedule_for(analysis_start=JUL_START, hold_period=3)
    forward = [
        (month, value)
        for month, value in zip(schedule.months, schedule.market_rent_psf)
        if month.is_forward_exit_month
    ]

    assert len(forward) == 12
    assert forward[0][0].period_index == 37
    assert forward[0][0].month_start == date(2030, 7, 1)

    assert rent_at(schedule, 36) == strict(42.436)
    assert rent_at(schedule, 37) == strict(43.70908)
    for _, value in forward:
        assert value == strict(43.70908)


def test_golden_8_market_rent_is_never_frozen_at_the_sale_month() -> None:
    """A longer forward window case: with hold 4 and a January start, the step
    falls at period 49, the first forward month. The last hold month and the
    first forward month must differ."""

    schedule = schedule_for(hold_period=4)

    assert len(schedule.market_rent_psf) == 60
    assert schedule.months[47].is_forward_exit_month is False
    assert schedule.months[48].is_forward_exit_month is True
    assert rent_at(schedule, 48) == strict(40.0 * 1.03**3)
    assert rent_at(schedule, 49) == strict(40.0 * 1.03**4)
    assert rent_at(schedule, 49) != rent_at(schedule, 48)


def test_market_rent_covers_the_entire_canonical_timeline() -> None:
    """Hold years 1..H **plus** twelve forward months, one value each, aligned
    1:1 with the canonical ``ModelMonth`` sequence."""

    for hold_period in (1, 3, 5, 10):
        schedule = schedule_for(hold_period=hold_period)
        assert len(schedule.market_rent_psf) == 12 * hold_period + 12
        assert len(schedule.months) == len(schedule.market_rent_psf)
        assert sum(
            1 for month in schedule.months if month.is_forward_exit_month
        ) == 12


# =============================================================================
# GOLDEN 9 -- repeated build
# =============================================================================


def test_golden_9_repeated_build_is_value_equal() -> None:
    """Pure and deterministic: the same inputs always produce a value-equal
    schedule, bit for bit."""

    first = schedule_for()
    second = schedule_for()

    assert first == second
    assert first.market_rent_psf == second.market_rent_psf
    for left, right in zip(first.market_rent_psf, second.market_rent_psf):
        assert left.hex() == right.hex()


def test_golden_9_the_lookup_agrees_with_the_schedule_everywhere() -> None:
    """There is one market-rent formula, not two. The rollover lookup path and
    the schedule must agree in every period, exactly."""

    schedule = schedule_for(analysis_start=JUL_START, hold_period=4)

    for month, value in zip(schedule.months, schedule.market_rent_psf):
        assert market_rent_psf_at_period(schedule, month.period_index) == value
        assert market_rent_psf_for_period(
            market_rent_psf=schedule.resolved.assumptions.market_rent_psf,
            market_rent_growth=schedule.resolved.assumptions.market_rent_growth,
            period=month.period_index,
        ) == value


@pytest.mark.parametrize("period", [0, -1, 61, 1000])
def test_lookup_outside_the_schedule_raises_rather_than_clamping(period: int) -> None:
    """A successor commencing past the horizon is a real modelling question
    for D2.6, not something to answer with the last month's rent."""

    schedule = schedule_for(hold_period=4)  # periods 1..60
    with pytest.raises(ValueError):
        market_rent_psf_at_period(schedule, period)


# =============================================================================
# GOLDEN 10 -- market rent versus contractual rent
# =============================================================================


def test_golden_10_market_and_contract_do_not_contaminate_each_other() -> None:
    """An in-place lease at $30/SF flat, in a market assumed at $45/SF growing
    4%.

    The D1 contractual schedule stays at $30 throughout -- market growth does
    not touch a signed lease. The D2.1 market schedule starts at $45 and grows
    on its own clock -- the lease does not touch the market. This is
    FM-D2-14 and FM-D2-20 in one case."""

    months = build_model_months(analysis_start=JAN_START, hold_period=5)
    the_suite = suite("S1")
    in_place = Lease(
        lease_id="L1",
        suite_id="S1",
        leased_area_sf=AREA,
        rent_commencement_date=JAN_START,
        lease_expiration_date=date(2032, 12, 31),  # spans all 72 canonical months
        base_rent_psf=30.0,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=LeaseType.NNN,
    )

    contractual = build_lease_monthly_schedule(
        in_place, analysis_start=JAN_START, months=months
    )
    market = build_market_rent_schedule(
        the_suite,
        property_defaults=assumptions(market_rent_psf=45.0, market_rent_growth=0.04),
        months=months,
    )

    expected_monthly_dollars = 30.0 * AREA / 12.0
    for value in contractual.contractual_base_rent:
        assert value == strict(expected_monthly_dollars)

    assert rent_at(market, 1) == strict(45.0)
    assert rent_at(market, 13) == strict(46.8)
    assert rent_at(market, 25) == strict(48.672)

    # The two series never meet: no market value appears in the contractual
    # dollars, and no contractual rate appears in the market rates.
    assert 30.0 not in market.market_rent_psf
    assert 45.0 not in contractual.contractual_base_rent


def test_golden_10_market_escalation_does_not_step_on_the_lease_anniversary() -> None:
    """A lease commencing in April 2027 under a January analysis start. Market
    rent still steps in January, not in April -- the lease anniversary is a
    contract fact and moves nothing about the market (FM-D2-13)."""

    months = build_model_months(analysis_start=JAN_START, hold_period=3)
    market = build_market_rent_schedule(
        suite("S1"), property_defaults=assumptions(), months=months
    )
    by_month = {
        month.month_start: value
        for month, value in zip(market.months, market.market_rent_psf)
    }

    assert by_month[date(2028, 3, 1)] == strict(41.2)
    assert by_month[date(2028, 4, 1)] == strict(41.2)  # the lease anniversary
    assert by_month[date(2027, 12, 1)] == strict(40.0)
    assert by_month[date(2028, 1, 1)] == strict(41.2)  # the market anniversary


def test_market_rent_is_a_rate_never_a_cash_flow() -> None:
    """D2.1 produces ``$/SF/year`` and stops. Nothing multiplies by suite area
    or divides by 12; that conversion needs a commencement period, a term,
    downtime and free rent, none of which exist at this gate."""

    schedule = schedule_for(the_suite=suite("S1"))

    assert rent_at(schedule, 1) == strict(40.0)
    assert rent_at(schedule, 1) != strict(40.0 * AREA / 12.0)
    assert max(schedule.market_rent_psf) < 1_000.0  # a rate, not dollars


# =============================================================================
# Zero market rent
# =============================================================================


def test_zero_market_rent_is_permitted_and_computes_exact_zero() -> None:
    """D0 Section 4.5 sets the domain at ``>= 0``. Zero is a real market rent:
    it is not vacancy, not missing data, and not free rent, and it stays
    exactly ``0.0`` under any growth rate."""

    for growth in (0.0, 0.03, -0.05, 1.0):
        schedule = schedule_for(
            defaults=assumptions(market_rent_psf=0.0, market_rent_growth=growth)
        )
        for value in schedule.market_rent_psf:
            assert value == 0.0


def test_zero_market_rent_raises_no_validation_issue() -> None:
    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(analysis_start_date=JAN_START, rentable_area_sf=AREA),
        [suite("S1")],
        [],
        market_leasing=assumptions(market_rent_psf=0.0),
    )

    assert result.is_valid
    assert not result.warnings


# =============================================================================
# Non-finite results
# =============================================================================


def test_overflowing_growth_fails_loudly_rather_than_returning_inf() -> None:
    """The package's one non-finite convention, shared with every other Anchor
    calculator via ``ensure_finite``."""

    with pytest.raises(NonFiniteResultError):
        market_rent_psf_for_period(
            market_rent_psf=1e308, market_rent_growth=1e300, period=13
        )


# =============================================================================
# Validation -- leasing-scoped only
# =============================================================================


def property_inputs(area: float = AREA) -> LeaseLevelPropertyInputs:
    return LeaseLevelPropertyInputs(
        analysis_start_date=JAN_START, rentable_area_sf=area
    )


def codes(result: object) -> list[LeaseIssueCode]:
    return [issue.code for issue in result.issues]  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad_rent", [-0.01, -40.0])
def test_negative_market_rent_is_an_error(bad_rent: float) -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite("S1")], [], market_leasing=assumptions(market_rent_psf=bad_rent)
    )

    assert not result.is_valid
    assert LeaseIssueCode.MARKET_RENT_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("bad_growth", [-1.0, -1.5, -2.0])
def test_market_growth_at_or_below_minus_one_is_an_error(bad_growth: float) -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite("S1")],
        [],
        market_leasing=assumptions(market_rent_growth=bad_growth),
    )

    assert not result.is_valid
    assert LeaseIssueCode.MARKET_RENT_GROWTH_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("growth", [-0.99, -0.5, 0.0, 0.03, 2.0])
def test_growth_above_minus_one_is_accepted(growth: float) -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite("S1")],
        [],
        market_leasing=assumptions(market_rent_growth=growth),
    )

    assert result.is_valid


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_market_assumptions_are_errors(bad: float) -> None:
    rent_result = validate_lease_level_inputs(
        property_inputs(), [suite("S1")], [], market_leasing=assumptions(market_rent_psf=bad)
    )
    growth_result = validate_lease_level_inputs(
        property_inputs(),
        [suite("S1")],
        [],
        market_leasing=assumptions(market_rent_growth=bad),
    )

    assert LeaseIssueCode.NON_FINITE_VALUE in codes(rent_result)
    assert LeaseIssueCode.NON_FINITE_VALUE in codes(growth_result)


def test_suite_rent_level_override_is_domain_checked() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite("S1", market_rent_psf=-5.0)],
        [],
        market_leasing=assumptions(),
    )

    assert not result.is_valid
    issue = next(
        item
        for item in result.issues
        if item.code is LeaseIssueCode.MARKET_RENT_OUT_OF_DOMAIN
    )
    assert issue.path == "suites[0].market_rent_psf"


def test_suite_full_override_is_domain_checked() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [
            suite(
                "S1",
                market_leasing_override=assumptions(
                    market_rent_psf=50.0, market_rent_growth=-1.0
                ),
            )
        ],
        [],
        market_leasing=assumptions(),
    )

    assert not result.is_valid
    issue = next(
        item
        for item in result.issues
        if item.code is LeaseIssueCode.MARKET_RENT_GROWTH_OUT_OF_DOMAIN
    )
    assert issue.path == "suites[0].market_leasing_override.market_rent_growth"


def test_a_suite_override_without_a_property_default_is_an_error() -> None:
    """D0 Section 4.5: the property default is always present. A suite carrying
    only a rent level has no growth rate without it, and Anchor does not invent
    one."""

    result = validate_lease_level_inputs(
        property_inputs(), [suite("S1", market_rent_psf=52.0)], []
    )

    assert not result.is_valid
    assert LeaseIssueCode.MARKET_LEASING_DEFAULT_REQUIRED in codes(result)


def test_an_incomplete_override_cannot_be_constructed_at_all() -> None:
    """D0 Section 24.2's all-or-nothing rule is enforced structurally: both
    fields are required and neither has a default, so there is no
    partially-populated override for validation to catch."""

    with pytest.raises(TypeError):
        MarketLeasingAssumptions(market_rent_psf=40.0)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        MarketLeasingAssumptions(market_rent_growth=0.03)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        # Still structural as the record grew at D2.2 and again at D2.3.
        MarketLeasingAssumptions(  # type: ignore[call-arg]
            market_rent_psf=40.0, market_rent_growth=0.03
        )


def test_market_validation_is_ordered_property_default_then_suites() -> None:
    """D0 Section 19.1 issue ordering, extended to the market rules."""

    result = validate_lease_level_inputs(
        property_inputs(2 * AREA),
        [suite("A", market_rent_psf=-1.0), suite("B", market_rent_psf=-2.0)],
        [],
        market_leasing=assumptions(market_rent_psf=-3.0),
    )

    market_paths = [
        issue.path
        for issue in result.issues
        if issue.code is LeaseIssueCode.MARKET_RENT_OUT_OF_DOMAIN
    ]
    assert market_paths == [
        "market_leasing.market_rent_psf",
        "suites[0].market_rent_psf",
        "suites[1].market_rent_psf",
    ]


def test_market_issues_are_errors_never_warnings() -> None:
    """A mathematically invalid input is never downgraded (D0 Section 19.1)."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite("S1")],
        [],
        market_leasing=assumptions(market_rent_psf=-1.0, market_rent_growth=-2.0),
    )

    for issue in result.issues:
        assert issue.severity is LeaseIssueSeverity.ERROR


# =============================================================================
# D1 isolation -- D2.1 changes no D1 behaviour
# =============================================================================


def test_omitting_market_assumptions_leaves_d1_validation_unchanged() -> None:
    """The D1 call signature still works and still evaluates every D1 rule; no
    market rule fires and no market issue appears."""

    result = validate_lease_level_inputs(property_inputs(), [suite("S1")], [])

    assert result.is_valid
    market_codes = {
        LeaseIssueCode.MARKET_RENT_OUT_OF_DOMAIN,
        LeaseIssueCode.MARKET_RENT_GROWTH_OUT_OF_DOMAIN,
        LeaseIssueCode.MARKET_LEASING_DEFAULT_REQUIRED,
    }
    assert not market_codes & set(codes(result))


def test_a_suite_defaults_to_no_market_override() -> None:
    """Both D2.1 fields default to ``None``, so every D1 call site constructs
    an identical ``Suite`` and no D1 economics move."""

    plain = Suite(suite_id="S1", suite_area_sf=AREA)

    assert plain.market_rent_psf is None
    assert plain.market_leasing_override is None


def test_market_contracts_are_frozen_and_slotted() -> None:
    """Anchor's contract conventions: frozen, slotted, keyword-only,
    deterministic equality."""

    record = assumptions()
    resolved = resolve_market_leasing(suite("S1"), property_defaults=record)
    schedule = schedule_for()

    for value in (resolved, schedule):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, "suite_id", "mutated")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(record, "market_rent_psf", 999.0)

    assert assumptions() == assumptions()
    assert hash(record) == hash(assumptions())


def test_a_market_schedule_rejects_a_length_mismatch() -> None:
    months = build_model_months(analysis_start=JAN_START, hold_period=1)
    resolved = resolve_market_leasing(suite("S1"), property_defaults=assumptions())

    with pytest.raises(ValueError):
        MarketRentSchedule(
            suite_id="S1",
            resolved=resolved,
            months=months,
            market_rent_psf=(40.0,),
        )
