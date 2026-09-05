"""Sprint D Gate D2.4 -- tenant improvements and leasing commissions.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Section 8 and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 11 and 12, that each branch computes its own TI and LC with exact
monthly timing and a full-term contractual face-rent basis.

The financial claims that matter most:

- the LC basis is the **full contractual term**, not the portion visible inside
  the projection (Golden 10 -- failure mode FM-17 / FM-D2-11);
- it is **gross of free rent** (Golden 4 -- failure mode FM-D2-10) and
  **unreduced by a fractional first month** from downtime (Golden 5 -- failure
  mode FM-D2-11b);
- it **includes every escalation** (Golden 3);
- TI and LC land in full in the first period with ``O_m > 0``, never prorated
  (Goldens 6, 7 -- failure mode FM-D2-9);
- both are **below NOI**: adding or doubling them leaves every rent, cash and
  occupancy series bit-identical (Goldens 13, 14 -- the G-3 perturbation).

Every expected value below is hand-calculable from the D1 rent formula.
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
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    Suite,
    build_lease_monthly_schedule,
    build_model_months,
    build_new_tenant_branch,
    build_renewal_branch,
    contractual_face_rent_over_full_term,
    lease_contractual_term_months,
    leasing_commission_amount,
    leasing_cost_event_period,
    leasing_cost_event_series,
    tenant_improvement_amount,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    validate_lease_level_inputs,
)


JAN_START = date(2027, 1, 1)
AREA = 12_000.0
METHOD = LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT

#: The expiring lease expires 2028-06-30, which is period 18 from a January
#: 2027 analysis start.
EXPIRY_PERIOD = 18


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    """Market $24/SF flat, so face rent is a round $24,000/month on 12,000 SF."""

    base: dict[str, object] = {
        "market_rent_psf": 24.0,
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
        "new_ti_psf": 50.0,
        "leasing_commission_method": METHOD,
        "renewal_lc_pct": 0.0,
        "new_lc_pct": 0.05,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)  # type: ignore[arg-type]


def suite(suite_id: str = "S1") -> Suite:
    return Suite(suite_id=suite_id, suite_area_sf=AREA)


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


def new_branch(*, hold_period: int = 6, lease: Lease | None = None, **overrides: object):
    return build_new_tenant_branch(
        lease if lease is not None else expiring_lease(),
        suite=suite(),
        analysis_start=JAN_START,
        months=build_model_months(analysis_start=JAN_START, hold_period=hold_period),
        property_defaults=assumptions(**overrides),
    )


def renewal_branch(*, hold_period: int = 6, lease: Lease | None = None, **overrides: object):
    return build_renewal_branch(
        lease if lease is not None else expiring_lease(),
        suite=suite(),
        analysis_start=JAN_START,
        months=build_model_months(analysis_start=JAN_START, hold_period=hold_period),
        property_defaults=assumptions(**overrides),
    )


def successor(*, term_months: int, base_rent_psf: float = 24.0, escalation_pct: float = 0.0) -> Lease:
    """A standalone successor lease, for testing the full-term helper directly."""

    commencement = date(2028, 7, 1)
    total = commencement.year * 12 + (commencement.month - 1) + term_months - 1
    year, month = divmod(total, 12)
    last_start = date(year, month + 1, 1)
    import calendar as _cal

    expiration = date(year, month + 1, _cal.monthrange(year, month + 1)[1])
    assert last_start <= expiration
    return Lease(
        lease_id="SUCC",
        suite_id="S1",
        tenant_name=None,
        leased_area_sf=AREA,
        rent_commencement_date=commencement,
        lease_expiration_date=expiration,
        base_rent_psf=base_rent_psf,
        escalation_pct=escalation_pct,
        escalation_basis=(
            EscalationBasis.LEASE_ANNIVERSARY if escalation_pct else EscalationBasis.NONE
        ),
        lease_type=LeaseType.NNN,
    )


# =============================================================================
# The full-term contractual face-rent basis
# =============================================================================


@pytest.mark.parametrize(
    "term", [1, 2, 11, 12, 13, 23, 24, 25, 60, 120, 240]
)
def test_the_full_term_helper_counts_exactly_term_months(term: int) -> None:
    """No off-by-one: a ``T``-month lease contributes exactly ``T`` months of
    face rent, at a flat $24/SF on 12,000 SF -- $24,000 a month."""

    lease = successor(term_months=term)

    assert lease_contractual_term_months(lease) == term
    assert contractual_face_rent_over_full_term(lease) == strict(24_000.0 * term)


@pytest.mark.parametrize(
    ("term", "escalation", "expected"),
    [
        (12, 0.05, 288_000.0),
        (24, 0.05, 288_000.0 + 302_400.0),
        (13, 0.05, 288_000.0 + 25_200.0),
        (36, 0.05, 288_000.0 + 302_400.0 + 317_520.0),
        (24, 0.0, 576_000.0),
        (24, -0.10, 288_000.0 + 259_200.0),
    ],
)
def test_the_full_term_helper_applies_contractual_escalation(
    term: int, escalation: float, expected: float
) -> None:
    """Escalation steps on the lease's own anniversaries, so a 13-month term
    carries twelve months at the first step and one at the second."""

    lease = successor(term_months=term, escalation_pct=escalation)

    assert contractual_face_rent_over_full_term(lease) == strict(expected)


def test_the_full_term_helper_agrees_with_the_d1_schedule_when_both_fit() -> None:
    """The basis is not a parallel calculation. Where the projection is long
    enough to contain the whole term, summing the authoritative D1 schedule
    gives the identical figure -- bit for bit."""

    for term, escalation in ((12, 0.0), (24, 0.05), (60, 0.03), (36, -0.02)):
        lease = successor(term_months=term, escalation_pct=escalation)
        months = build_model_months(analysis_start=JAN_START, hold_period=30)
        schedule = build_lease_monthly_schedule(
            lease, analysis_start=JAN_START, months=months
        )

        assert contractual_face_rent_over_full_term(lease) == strict(
            sum(schedule.contractual_base_rent)
        )


def test_a_zero_rent_successor_has_a_zero_basis() -> None:
    lease = successor(term_months=60, base_rent_psf=0.0)

    assert contractual_face_rent_over_full_term(lease) == 0.0


def test_the_full_term_helper_needs_no_analysis_anchor() -> None:
    """The basis is a property of the contract, identical whatever deal the
    lease is acquired in -- so no second calendar and no ModelMonth beyond the
    property horizon is ever constructed."""

    import inspect

    parameters = set(inspect.signature(contractual_face_rent_over_full_term).parameters)
    assert parameters == {"lease"}
    assert "analysis_start" not in parameters
    assert "months" not in parameters


# =============================================================================
# GOLDEN 1 -- simple TI
# =============================================================================


def test_golden_1_simple_ti() -> None:
    """12,000 SF at $50/SF is $600,000, recorded in full at commencement."""

    assert tenant_improvement_amount(ti_psf=50.0, leased_area_sf=AREA) == strict(
        600_000.0
    )

    branch = new_branch()
    c = branch.commencement_period

    assert branch.tenant_improvement_amount == strict(600_000.0)
    assert branch.tenant_improvements[c - 1] == strict(600_000.0)
    assert sum(branch.tenant_improvements) == strict(600_000.0)


# =============================================================================
# GOLDEN 2 -- simple LC
# =============================================================================


def test_golden_2_simple_lc() -> None:
    """A 12-month successor at $24,000/month is a $288,000 basis; 5% of it is
    $14,400."""

    branch = new_branch()
    c = branch.commencement_period

    assert branch.full_term_contractual_face_rent == strict(288_000.0)
    assert branch.leasing_commission_amount == strict(14_400.0)
    assert branch.leasing_commissions[c - 1] == strict(14_400.0)
    assert sum(branch.leasing_commissions) == strict(14_400.0)


# =============================================================================
# GOLDEN 3 -- escalating 24-month LC
# =============================================================================


def test_golden_3_escalating_twenty_four_month_lc() -> None:
    """12,000 SF, $24/SF starting, 5% successor escalation, 24-month term.

    Year 1 is ``24,000 x 12 = 288,000``; year 2 is ``25,200 x 12 = 302,400``;
    the basis is ``590,400`` and 5% of it is ``29,520``."""

    branch = new_branch(new_term_months=24, successor_escalation_pct=0.05)

    assert branch.full_term_contractual_face_rent == strict(590_400.0)
    assert branch.leasing_commission_amount == strict(29_520.0)

    # And the two years are exactly the stated figures.
    c = branch.commencement_period
    year_one = sum(branch.successor_schedule.contractual_base_rent[c - 1 : c + 11])
    year_two = sum(branch.successor_schedule.contractual_base_rent[c + 11 : c + 23])
    assert year_one == strict(288_000.0)
    assert year_two == strict(302_400.0)


# =============================================================================
# GOLDEN 4 -- free rent does not reduce LC
# =============================================================================


def test_golden_4_free_rent_does_not_reduce_the_lc_basis() -> None:
    """A 12-month lease at $10,000/month face with six months free.

    The basis is the full $120,000 and the commission is $6,000 -- **not** 5%
    of the $60,000 actually collected. A broker earns on the lease signed, not
    on the landlord's concession (failure mode FM-D2-10)."""

    branch = new_branch(
        market_rent_psf=10.0, new_free_rent_months=6.0, new_term_months=12
    )
    c = branch.commencement_period

    assert branch.contractual_base_rent[c - 1] == strict(10_000.0)
    assert branch.full_term_contractual_face_rent == strict(120_000.0)
    assert branch.leasing_commission_amount == strict(6_000.0)

    collected = sum(branch.cash_base_rent[c - 1 : c + 11])
    assert collected == strict(60_000.0)
    assert branch.leasing_commission_amount != strict(0.05 * collected)


@pytest.mark.parametrize("free_rent", [0.0, 1.0, 2.5, 6.0, 11.0])
def test_the_lc_basis_is_bit_identical_with_and_without_free_rent(
    free_rent: float,
) -> None:
    """Stronger than Golden 4: the basis does not move by a single bit as the
    concession varies."""

    baseline = new_branch(new_free_rent_months=0.0)
    with_free = new_branch(new_free_rent_months=free_rent)

    assert (
        with_free.full_term_contractual_face_rent.hex()
        == baseline.full_term_contractual_face_rent.hex()
    )
    assert (
        with_free.leasing_commission_amount.hex()
        == baseline.leasing_commission_amount.hex()
    )


# =============================================================================
# GOLDEN 5 -- fractional downtime does not reduce LC
# =============================================================================


def test_golden_5_fractional_downtime_does_not_reduce_the_lc_basis() -> None:
    """With ``D = 2.25`` Anchor recognises ``0.75`` of a month's *cash* in the
    boundary period -- but the lease still says twelve full months.

    The boundary factor is a cash-recognition artifact of the monthly grid and
    never enters the LC basis (failure mode FM-D2-11b)."""

    branch = new_branch(new_downtime_months=2.25, new_term_months=12)
    c = branch.commencement_period

    assert branch.successor_occupancy_factor[c - 1] == strict(0.75)
    # Twelve FULL contractual months, not 11.75.
    assert branch.full_term_contractual_face_rent == strict(288_000.0)
    assert branch.leasing_commission_amount == strict(14_400.0)
    assert branch.full_term_contractual_face_rent != strict(24_000.0 * 11.75)


@pytest.mark.parametrize("downtime", [0.0, 0.25, 1.0, 2.25, 5.5, 6.0])
def test_the_lc_basis_is_bit_identical_across_every_downtime(
    downtime: float,
) -> None:
    baseline = new_branch(hold_period=8, new_downtime_months=0.0)
    delayed = new_branch(hold_period=8, new_downtime_months=downtime)

    assert (
        delayed.full_term_contractual_face_rent.hex()
        == baseline.full_term_contractual_face_rent.hex()
    )
    assert (
        delayed.leasing_commission_amount.hex()
        == baseline.leasing_commission_amount.hex()
    )


# =============================================================================
# GOLDENS 6 and 7 -- TI and LC timing with fractional downtime
# =============================================================================


def test_goldens_6_and_7_ti_and_lc_land_in_september() -> None:
    """Lease expires June 30, downtime 2.25 months.

    July vacant, August vacant, September is ``c`` with rent factor ``0.75`` --
    and **September** carries the full TI and the full LC. Not July, not
    August, not October, and not spread across months (D2 Section 8.1)."""

    branch = new_branch(new_downtime_months=2.25)
    by_month = {month.month_start: month.period_index for month in branch.months}

    july = by_month[date(2028, 7, 1)]
    august = by_month[date(2028, 8, 1)]
    september = by_month[date(2028, 9, 1)]
    october = by_month[date(2028, 10, 1)]

    assert branch.commencement_period == september
    assert branch.successor_occupancy_factor[september - 1] == strict(0.75)

    for period in (july, august, october):
        assert branch.tenant_improvements[period - 1] == 0.0
        assert branch.leasing_commissions[period - 1] == 0.0

    assert branch.tenant_improvements[september - 1] == strict(600_000.0)
    assert branch.leasing_commissions[september - 1] == strict(14_400.0)

    # Recorded exactly once each.
    assert sum(1 for v in branch.tenant_improvements if v) == 1
    assert sum(1 for v in branch.leasing_commissions if v) == 1


def test_ti_is_never_prorated_by_the_boundary_factor() -> None:
    """The allowance is a lump obligation triggered by commencement; the fact
    that the grid recognises 75% of September's rent does not divide it."""

    branch = new_branch(new_downtime_months=2.25)
    c = branch.commencement_period

    assert branch.tenant_improvements[c - 1] == strict(600_000.0)
    assert branch.tenant_improvements[c - 1] != strict(600_000.0 * 0.75)


def test_the_event_period_is_the_first_period_with_positive_occupancy() -> None:
    """D2 Section 8.1 states the ``O_m > 0`` form as primary, and it coincides
    with ``c = e + 1 + floor(D)`` by construction. Both are asserted, across a
    range of downtimes, so a future refinement of the occupancy step cannot
    silently separate them."""

    for downtime in (0.0, 0.25, 1.0, 2.25, 3.0, 5.5, 6.0):
        branch = new_branch(hold_period=8, new_downtime_months=downtime)
        event = leasing_cost_event_period(
            months=branch.months,
            successor_occupancy_factor=branch.successor_occupancy_factor,
        )
        assert event == branch.commencement_period, downtime
        assert branch.successor_occupancy_factor[event - 1] > 0.0
        if event > 1:
            assert branch.successor_occupancy_factor[event - 2] == 0.0


# =============================================================================
# GOLDENS 8 and 9 -- branch isolation
# =============================================================================


def test_golden_8_each_branch_uses_only_its_own_ti_rate() -> None:
    """Renewal $10/SF, new tenant $80/SF, same suite."""

    overrides = {"renewal_ti_psf": 10.0, "new_ti_psf": 80.0}
    renewal = renewal_branch(**overrides)
    new_tenant = new_branch(**overrides)

    assert renewal.ti_psf == 10.0
    assert renewal.tenant_improvement_amount == strict(120_000.0)
    assert new_tenant.ti_psf == 80.0
    assert new_tenant.tenant_improvement_amount == strict(960_000.0)


def test_golden_9_each_branch_uses_only_its_own_lc_rate() -> None:
    """Renewal 2%, new tenant 6%, on the same $288,000 basis."""

    overrides = {"renewal_lc_pct": 0.02, "new_lc_pct": 0.06}
    renewal = renewal_branch(**overrides)
    new_tenant = new_branch(**overrides)

    assert renewal.lc_pct == 0.02
    assert renewal.full_term_contractual_face_rent == strict(288_000.0)
    assert renewal.leasing_commission_amount == strict(5_760.0)

    assert new_tenant.lc_pct == 0.06
    assert new_tenant.full_term_contractual_face_rent == strict(288_000.0)
    assert new_tenant.leasing_commission_amount == strict(17_280.0)


def test_changing_one_branch_rate_never_moves_the_other() -> None:
    baseline_renewal = renewal_branch()
    baseline_new = new_branch()

    moved = {"new_ti_psf": 999.0, "new_lc_pct": 0.9}
    assert renewal_branch(**moved).tenant_improvement_amount == (
        baseline_renewal.tenant_improvement_amount
    )
    assert renewal_branch(**moved).leasing_commission_amount == (
        baseline_renewal.leasing_commission_amount
    )

    moved = {"renewal_ti_psf": 999.0, "renewal_lc_pct": 0.9}
    assert new_branch(**moved).tenant_improvement_amount == (
        baseline_new.tenant_improvement_amount
    )
    assert new_branch(**moved).leasing_commission_amount == (
        baseline_new.leasing_commission_amount
    )


def test_each_branch_has_its_own_term_and_therefore_its_own_basis() -> None:
    """The bases differ because the terms differ -- nothing is shared or
    averaged between branches."""

    renewal = renewal_branch(
        hold_period=10, renewal_term_months=36, new_term_months=120
    )
    new_tenant = new_branch(
        hold_period=10, renewal_term_months=36, new_term_months=120
    )

    assert renewal.full_term_contractual_face_rent == strict(24_000.0 * 36)
    assert new_tenant.full_term_contractual_face_rent == strict(24_000.0 * 120)


# =============================================================================
# GOLDEN 10 -- the full term beyond the projection
# =============================================================================


def test_golden_10_lc_uses_the_full_term_not_the_visible_months() -> None:
    """**The mandatory rule.** A 60-month successor of which only nine months
    fall inside the canonical projection.

    LC is computed on all 60 contractual months -- $1,440,000 -- not on the
    $216,000 the schedule shows. Summing only the visible successor schedule
    would report $10,800 instead of $72,000 (failure mode FM-17)."""

    # hold 2 -> 36 canonical months; e = 18, D = 9 -> c = 28, so 9 visible.
    branch = new_branch(hold_period=2, new_term_months=60, new_downtime_months=9.0)

    visible_months = sum(
        1 for value in branch.successor_schedule.contractual_base_rent if value
    )
    visible_total = sum(branch.successor_schedule.contractual_base_rent)

    assert len(branch.months) == 36
    assert visible_months == 9
    assert branch.term_months == 60
    assert branch.successor_expiration_period == 87  # far beyond the horizon

    assert visible_total == strict(216_000.0)
    assert branch.full_term_contractual_face_rent == strict(1_440_000.0)
    assert branch.leasing_commission_amount == strict(72_000.0)
    assert branch.leasing_commission_amount != strict(0.05 * visible_total)


@pytest.mark.parametrize("term", [13, 24, 60, 120, 240])
def test_the_basis_is_independent_of_the_projection_length(term: int) -> None:
    """The same successor produces the same basis whatever the hold period --
    the projection is a viewing window, not a term."""

    bases = {
        new_branch(hold_period=hold, new_term_months=term).full_term_contractual_face_rent
        for hold in (1, 2, 5, 10, 25)
    }

    assert len(bases) == 1
    assert bases.pop() == strict(24_000.0 * term)


def test_a_successor_commencing_past_the_horizon_records_no_monthly_event() -> None:
    """The timeline is never extended to display a cost, but the obligation is
    real and its totals are retained."""

    # hold 2 -> 36 months; e = 18, D = 18 -> c = 37, one past the horizon.
    branch = new_branch(hold_period=2, new_downtime_months=18.0)

    assert branch.commences_within_projection is False
    assert len(branch.months) == 36
    assert all(value == 0.0 for value in branch.tenant_improvements)
    assert all(value == 0.0 for value in branch.leasing_commissions)

    # ... yet the amounts exist and are correct.
    assert branch.tenant_improvement_amount == strict(600_000.0)
    assert branch.leasing_commission_amount == strict(14_400.0)
    assert branch.full_term_contractual_face_rent == strict(288_000.0)


# =============================================================================
# GOLDEN 11 -- zero TI and zero LC
# =============================================================================


def test_golden_11_zero_ti_and_lc_produce_exact_zeros() -> None:
    branch = new_branch(new_ti_psf=0.0, new_lc_pct=0.0)
    c = branch.commencement_period

    assert branch.tenant_improvement_amount == 0.0
    assert branch.leasing_commission_amount == 0.0
    assert branch.tenant_improvements[c - 1] == 0.0
    assert branch.leasing_commissions[c - 1] == 0.0
    # The basis is still computed and auditable.
    assert branch.full_term_contractual_face_rent == strict(288_000.0)


def test_a_zero_cost_still_has_an_event_period() -> None:
    """The event month is a fact about timing, not magnitude. Suppressing it
    because the amount is zero would make a legitimately zero cost
    indistinguishable from a missing one."""

    branch = new_branch(new_ti_psf=0.0, new_lc_pct=0.0, new_downtime_months=2.25)
    event = leasing_cost_event_period(
        months=branch.months,
        successor_occupancy_factor=branch.successor_occupancy_factor,
    )

    assert event == branch.commencement_period


def test_zero_costs_leave_rent_and_occupancy_untouched() -> None:
    with_costs = new_branch(new_ti_psf=75.0, new_lc_pct=0.06)
    without = new_branch(new_ti_psf=0.0, new_lc_pct=0.0)

    assert with_costs.contractual_base_rent == without.contractual_base_rent
    assert with_costs.cash_base_rent == without.cash_base_rent
    assert with_costs.physical_occupancy == without.physical_occupancy


# =============================================================================
# GOLDEN 12 -- an event inside the forward exit window
# =============================================================================


def test_golden_12_ti_and_lc_appear_in_the_forward_exit_window() -> None:
    """Rollover stays live in periods ``12H+1 .. 12H+12``, and a cost falling
    there is recorded normally. D0 Section 17.4 discloses it without deducting
    it, which is a D4 concern -- not a reason to hide the event here."""

    # hold 2 -> hold months 1-24, forward window 25-36. e = 18, D = 8 -> c = 27.
    branch = new_branch(hold_period=2, new_downtime_months=8.0)
    c = branch.commencement_period

    assert c == 27
    assert branch.months[c - 1].is_forward_exit_month is True
    assert branch.tenant_improvements[c - 1] == strict(600_000.0)
    assert branch.leasing_commissions[c - 1] == strict(14_400.0)


# =============================================================================
# GOLDENS 13 and 14 -- the below-NOI perturbation
# =============================================================================


def test_golden_13_leasing_costs_never_alter_rent_or_occupancy() -> None:
    """**The G-3 perturbation.** Doubling TI and LC must leave every rent, cash
    and occupancy series bit-identical -- the mechanical statement of "below
    NOI" (D0 Sections 11 and 12.2, failure mode FM-D2-16)."""

    for downtime, free_rent in ((0.0, 0.0), (2.25, 2.5), (5.5, 1.0)):
        base = new_branch(
            hold_period=8,
            new_downtime_months=downtime,
            new_free_rent_months=free_rent,
            new_ti_psf=0.0,
            new_lc_pct=0.0,
        )
        loaded = new_branch(
            hold_period=8,
            new_downtime_months=downtime,
            new_free_rent_months=free_rent,
            new_ti_psf=500.0,
            new_lc_pct=1.0,
        )

        for series in (
            "contractual_base_rent",
            "cash_base_rent",
            "free_rent",
            "successor_occupancy_factor",
            "physical_occupancy",
            "occupied_area",
        ):
            left = getattr(base, series)
            right = getattr(loaded, series)
            assert [v.hex() for v in left] == [v.hex() for v in right], (
                series,
                downtime,
                free_rent,
            )

        assert loaded.starting_rent_psf == base.starting_rent_psf
        assert loaded.commencement_period == base.commencement_period
        assert loaded.successor_expiration_period == base.successor_expiration_period


def test_golden_14_leasing_costs_never_alter_the_free_rent_waterfall() -> None:
    base = new_branch(new_downtime_months=2.25, new_free_rent_months=2.5,
                      new_ti_psf=0.0, new_lc_pct=0.0)
    loaded = new_branch(new_downtime_months=2.25, new_free_rent_months=2.5,
                        new_ti_psf=500.0, new_lc_pct=1.0)

    assert loaded.free_rent_abatement_months == base.free_rent_abatement_months
    assert loaded.cash_rent_factor == base.cash_rent_factor


def test_leasing_costs_are_not_added_into_any_rent_series() -> None:
    """A $600,000 TI must appear on its own line and nowhere else."""

    branch = new_branch()
    c = branch.commencement_period

    assert branch.tenant_improvements[c - 1] == strict(600_000.0)
    assert branch.contractual_base_rent[c - 1] == strict(24_000.0)
    assert branch.cash_base_rent[c - 1] == strict(24_000.0)
    assert branch.free_rent[c - 1] == 0.0


# =============================================================================
# GOLDEN 15 -- the D2.3 mandatory case still holds
# =============================================================================


def test_golden_15_the_d2_3_mandatory_waterfall_is_unchanged() -> None:
    """The Section 7.2 reference case must survive D2.4 exactly: Sep cash 0,
    Oct cash 0, Nov factor 0.25, Dec factor 1."""

    branch = new_branch(new_downtime_months=2.25, new_free_rent_months=2.5)
    by_month = {month.month_start: month.period_index for month in branch.months}

    expected = [
        (date(2028, 9, 1), 0.75, 0.75, 0.00, 0.0),
        (date(2028, 10, 1), 1.00, 1.00, 0.00, 0.0),
        (date(2028, 11, 1), 1.00, 0.75, 0.25, 6_000.0),
        (date(2028, 12, 1), 1.00, 0.00, 1.00, 24_000.0),
    ]
    for month, occupancy, abatement, cash_factor, cash in expected:
        period = by_month[month]
        assert branch.successor_occupancy_factor[period - 1] == strict(occupancy), month
        assert branch.free_rent_abatement_months[period - 1] == strict(abatement), month
        assert branch.cash_rent_factor[period - 1] == strict(cash_factor), month
        assert branch.cash_base_rent[period - 1] == strict(cash), month

    assert sum(branch.free_rent_abatement_months) == strict(2.5)


# =============================================================================
# Adversarial full-term cases
# =============================================================================


@pytest.mark.parametrize(
    "commencement_month", [1, 2, 3, 6, 7, 9, 11, 12]
)
def test_a_non_january_commencement_does_not_shift_the_basis(
    commencement_month: int,
) -> None:
    """Escalation runs on the successor's own anniversaries, so the basis
    depends on the term and the rate, never on the calendar month it starts
    in."""

    import calendar as _cal

    year = 2028
    last_month = commencement_month + 23  # 24-month term
    end_year, end_month = divmod(last_month - 1, 12)
    end_year += year
    end_month += 1
    lease = Lease(
        lease_id="SUCC",
        suite_id="S1",
        tenant_name=None,
        leased_area_sf=AREA,
        rent_commencement_date=date(year, commencement_month, 1),
        lease_expiration_date=date(
            end_year, end_month, _cal.monthrange(end_year, end_month)[1]
        ),
        base_rent_psf=24.0,
        escalation_pct=0.05,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        lease_type=LeaseType.NNN,
    )

    assert lease_contractual_term_months(lease) == 24
    assert contractual_face_rent_over_full_term(lease) == strict(590_400.0)


def test_a_leap_year_term_counts_whole_months() -> None:
    """A financial month is a calendar month: February 29 is a full month."""

    lease = Lease(
        lease_id="SUCC",
        suite_id="S1",
        tenant_name=None,
        leased_area_sf=AREA,
        rent_commencement_date=date(2027, 3, 1),
        lease_expiration_date=date(2028, 2, 29),
        base_rent_psf=24.0,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=LeaseType.NNN,
    )

    assert lease_contractual_term_months(lease) == 12
    assert contractual_face_rent_over_full_term(lease) == strict(288_000.0)


def test_a_very_long_term_far_beyond_the_projection() -> None:
    """A 20-year successor inside a one-year hold still values in full."""

    branch = new_branch(hold_period=1, new_term_months=240)

    assert len(branch.months) == 24
    assert branch.term_months == 240
    assert branch.full_term_contractual_face_rent == strict(24_000.0 * 240)


def test_repeated_build_is_value_equal() -> None:
    first = new_branch(new_downtime_months=2.25, new_free_rent_months=2.5)
    second = new_branch(new_downtime_months=2.25, new_free_rent_months=2.5)

    assert first == second
    assert (
        first.leasing_commission_amount.hex()
        == second.leasing_commission_amount.hex()
    )


def test_the_branch_leasing_cost_fields_are_frozen() -> None:
    branch = new_branch()

    with pytest.raises(dataclasses.FrozenInstanceError):
        branch.tenant_improvement_amount = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        branch.full_term_contractual_face_rent = 1.0  # type: ignore[misc]


def test_a_branch_rejects_a_mismatched_cost_series_length() -> None:
    branch = new_branch()

    with pytest.raises(ValueError):
        dataclasses.replace(branch, tenant_improvements=(0.0,))


# =============================================================================
# The event series and the method seam
# =============================================================================


def test_the_event_series_carries_the_amount_exactly_once() -> None:
    months = build_model_months(analysis_start=JAN_START, hold_period=2)

    series = leasing_cost_event_series(months=months, event_period=7, amount=1_234.5)
    assert series[6] == 1_234.5
    assert sum(series) == 1_234.5
    assert len(series) == 36

    none_series = leasing_cost_event_series(
        months=months, event_period=None, amount=1_234.5
    )
    assert all(value == 0.0 for value in none_series)


def test_an_unsupported_commission_method_is_refused() -> None:
    """The seam exists so a second method can be *added*, not so an
    unimplemented one can be silently *assumed*."""

    with pytest.raises(ValueError, match="not implemented"):
        leasing_commission_amount(
            lc_pct=0.05,
            full_term_contractual_face_rent=100_000.0,
            method="per_sf",  # type: ignore[arg-type]
        )


def test_the_method_is_recorded_on_each_branch() -> None:
    assert new_branch().leasing_commission_method is METHOD
    assert renewal_branch().leasing_commission_method is METHOD


def test_the_method_lives_on_the_assumptions_not_on_the_lease() -> None:
    """D0 Section 12.3: adding ``PER_SF`` later must not change the ``Lease``
    contract."""

    lease_fields = {f.name for f in dataclasses.fields(Lease)}
    assumption_fields = {f.name for f in dataclasses.fields(MarketLeasingAssumptions)}

    assert "leasing_commission_method" not in lease_fields
    assert "leasing_commission_method" in assumption_fields
    assert {member.value for member in LeasingCommissionMethod} == {
        "pct_of_total_contractual_base_rent"
    }


# =============================================================================
# Validation
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


@pytest.mark.parametrize("field", ["renewal_ti_psf", "new_ti_psf"])
@pytest.mark.parametrize("bad", [-0.01, -50.0])
def test_a_negative_ti_is_an_error(field: str, bad: float) -> None:
    result = validate(**{field: bad})
    assert LeaseIssueCode.TI_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("field", ["renewal_lc_pct", "new_lc_pct"])
@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0])
def test_an_lc_rate_outside_zero_to_one_is_an_error(field: str, bad: float) -> None:
    """The upper bound is D0 Section 4.5's ``0 <= x <= 1``, not invented here."""

    result = validate(**{field: bad})
    assert LeaseIssueCode.LC_PCT_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("value", [0.0, 0.02, 0.5, 1.0])
def test_an_lc_rate_inside_the_domain_is_valid(value: float) -> None:
    assert validate(new_lc_pct=value).is_valid  # type: ignore[attr-defined]


@pytest.mark.parametrize("value", [0.0, 10.0, 250.0])
def test_a_non_negative_ti_is_valid(value: float) -> None:
    assert validate(new_ti_psf=value).is_valid  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "field", ["renewal_ti_psf", "new_ti_psf", "renewal_lc_pct", "new_lc_pct"]
)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_leasing_costs_are_errors(field: str, bad: float) -> None:
    result = validate(**{field: bad})
    assert LeaseIssueCode.NON_FINITE_VALUE in codes(result)


def test_an_unrecognised_method_is_a_validation_error() -> None:
    result = validate(leasing_commission_method="per_sf")
    assert LeaseIssueCode.UNSUPPORTED_LEASING_COMMISSION_METHOD in codes(result)


def test_leasing_cost_issues_are_errors_never_warnings() -> None:
    result = validate(new_ti_psf=-1.0, new_lc_pct=2.0, renewal_ti_psf=-1.0)

    for issue in result.issues:  # type: ignore[attr-defined]
        assert issue.severity is LeaseIssueSeverity.ERROR


def test_a_suite_override_is_checked_against_the_d2_4_domains() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [
            Suite(
                suite_id="S1",
                suite_area_sf=AREA,
                market_leasing_override=assumptions(new_lc_pct=1.5),
            )
        ],
        [],
        market_leasing=assumptions(),
    )

    issue = next(
        item
        for item in result.issues
        if item.code is LeaseIssueCode.LC_PCT_OUT_OF_DOMAIN
    )
    assert issue.path == "suites[0].market_leasing_override.new_lc_pct"


def test_an_incomplete_assumption_record_cannot_be_constructed() -> None:
    complete = {
        "market_rent_psf": 24.0,
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
        "new_ti_psf": 50.0,
        "leasing_commission_method": METHOD,
        "renewal_lc_pct": 0.0,
        "new_lc_pct": 0.05,
    }
    for omitted in (
        "renewal_ti_psf",
        "new_ti_psf",
        "leasing_commission_method",
        "renewal_lc_pct",
        "new_lc_pct",
    ):
        fields = dict(complete)
        del fields[omitted]
        with pytest.raises(TypeError):
            MarketLeasingAssumptions(**fields)  # type: ignore[arg-type]
