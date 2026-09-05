"""Sprint D Gate D2.5 -- probability-weighted outcome composition.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
HD-D2-1, HD-D2-2 and Sections 1.2, 4.2 and 14, that the expected rollover is
``p * Renewal + (1 - p) * NewTenant`` applied to **finished branch outcomes**.

The financial claims that matter most:

- ``p = 1`` reproduces the renewal branch and ``p = 0`` the new-tenant branch
  **bit-identically** (failure mode FM-D2-2 -- the key safety property);
- every expected dollar series weights branch **dollars**, never a product of
  expected factors, because ``E[X*Y] != E[X]E[Y]`` for branch-correlated
  quantities (D2 Section 1.3);
- nothing about **timing** is weighted: two branches with costs in different
  months produce two weighted events, never one at a synthetic date;
- ``expected_occupancy`` may be fractional and is never called
  ``physical_occupancy`` (HD-D2-2, failure mode FM-D2-19);
- the D2 Section 1.2 review example that rejected the weighted-parameter
  method now computes correctly, to the cent.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    ExpectedRollover,
    Lease,
    LeaseLevelPropertyInputs,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    Suite,
    build_expected_rollover,
    build_model_months,
    build_new_tenant_branch,
    build_renewal_branch,
    compose_expected_rollover,
    weighted_outcome,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    validate_lease_level_inputs,
)


JAN_START = date(2027, 1, 1)
AREA = 10_000.0
METHOD = LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT

#: The expiring lease expires 2027-12-31, which is period 12. "Month k after
#: expiry" is therefore period ``12 + k``.
EXPIRY_PERIOD = 12


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def cents(expected: float) -> object:
    """Tolerance for a figure the D2 document states to the cent."""

    return pytest.approx(expected, rel=0.0, abs=1e-6)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    """The D2 Section 1.2 review example, expressed in the approved schema.

    Market sits at $44 with zero growth, so the new tenant prices at exactly
    $44 and the explicit ``renewal_rent_psf`` grows to exactly $40 -- the
    example's two rents, with no reintroduced rejected field.
    """

    base: dict[str, object] = {
        "market_rent_psf": 44.0,
        "market_rent_growth": 0.0,
        "renewal_rent_psf": 40.0,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.0,
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 0.0,
        "new_term_months": 120,
        "new_downtime_months": 9.0,
        "new_free_rent_months": 6.0,
        "renewal_ti_psf": 10.0,
        "new_ti_psf": 80.0,
        "leasing_commission_method": METHOD,
        "renewal_lc_pct": 0.02,
        "new_lc_pct": 0.06,
        "renewal_probability": 0.65,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)  # type: ignore[arg-type]


def suite(suite_id: str = "S1", area: float = AREA) -> Suite:
    return Suite(suite_id=suite_id, suite_area_sf=area)


def expiring_lease(**overrides: object) -> Lease:
    base: dict[str, object] = {
        "lease_id": "L1",
        "suite_id": "S1",
        "tenant_name": "Acme Corp",
        "leased_area_sf": AREA,
        "rent_commencement_date": date(2026, 1, 1),
        "lease_expiration_date": date(2027, 12, 31),
        "base_rent_psf": 35.0,
        "escalation_pct": 0.0,
        "escalation_basis": EscalationBasis.NONE,
        "lease_type": LeaseType.NNN,
    }
    base.update(overrides)
    return Lease(**base)  # type: ignore[arg-type]


def expected(
    *, hold_period: int = 15, lease: Lease | None = None, **overrides: object
) -> ExpectedRollover:
    return build_expected_rollover(
        lease if lease is not None else expiring_lease(),
        suite=suite(),
        analysis_start=JAN_START,
        months=build_model_months(analysis_start=JAN_START, hold_period=hold_period),
        property_defaults=assumptions(**overrides),
    )


def branches(*, hold_period: int = 15, **overrides: object):
    months = build_model_months(analysis_start=JAN_START, hold_period=hold_period)
    defaults = assumptions(**overrides)
    common = dict(
        suite=suite(),
        analysis_start=JAN_START,
        months=months,
        property_defaults=defaults,
    )
    return (
        build_renewal_branch(expiring_lease(), **common),
        build_new_tenant_branch(expiring_lease(), **common),
    )


#: Every composed monthly series, paired with the branch series it weights.
_COMPOSED_SERIES = (
    ("expected_contractual_base_rent", "contractual_base_rent"),
    ("expected_cash_base_rent", "cash_base_rent"),
    ("expected_free_rent", "free_rent"),
    ("expected_tenant_improvements", "tenant_improvements"),
    ("expected_leasing_commissions", "leasing_commissions"),
    ("expected_occupied_area_sf", "occupied_area"),
    ("expected_occupancy", "physical_occupancy"),
    ("expected_successor_occupancy_factor", "successor_occupancy_factor"),
    ("expected_free_rent_abatement_months", "free_rent_abatement_months"),
    ("expected_cash_rent_factor", "cash_rent_factor"),
)


# =============================================================================
# The weighting primitive
# =============================================================================


@pytest.mark.parametrize(
    ("renewal", "new_tenant", "p", "result"),
    [
        (20_000.0, 0.0, 0.5, 10_000.0),
        (20_000.0, 30_000.0, 0.5, 25_000.0),
        (100.0, 200.0, 0.25, 175.0),
        (100.0, 200.0, 0.75, 125.0),
        (0.0, 0.0, 0.5, 0.0),
        (33_333.33, 0.0, 0.65, 21_666.6645),
    ],
)
def test_the_primitive_computes_the_approved_weighting(
    renewal: float, new_tenant: float, p: float, result: float
) -> None:
    assert weighted_outcome(
        renewal, new_tenant, renewal_probability=p
    ) == strict(result)


@pytest.mark.parametrize("value", [0.0, 1.0, -5.0, 1e12, 1e-9])
def test_the_primitive_returns_the_endpoint_unchanged(value: float) -> None:
    """``p = 1`` and ``p = 0`` return their branch's value **untouched**, not a
    product that happens to equal it."""

    assert weighted_outcome(value, 999.0, renewal_probability=1.0) is value or (
        weighted_outcome(value, 999.0, renewal_probability=1.0) == value
    )
    assert weighted_outcome(999.0, value, renewal_probability=0.0) == value


def test_the_endpoints_do_not_consult_the_other_branch() -> None:
    """A pure endpoint never reads the other scenario, so a non-finite value
    there cannot contaminate it. ``1.0 * x + 0.0 * inf`` would be NaN."""

    assert weighted_outcome(
        5.0, float("inf"), renewal_probability=1.0
    ) == 5.0
    assert weighted_outcome(
        float("nan"), 7.0, renewal_probability=0.0
    ) == 7.0


@pytest.mark.parametrize("p", [0.0, 0.1, 0.3, 0.5, 0.65, 0.9, 1.0])
def test_identical_branch_values_survive_exactly(p: float) -> None:
    """``p * x + (1 - p) * x`` is ``x`` in exact arithmetic but can land one
    ULP away in IEEE-754. The short circuit keeps shared history clean."""

    for value in (0.1, 1 / 3, 33_333.333333333336, 1e-8, 12_345.678):
        assert weighted_outcome(
            value, value, renewal_probability=p
        ).hex() == value.hex()


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_the_primitive_refuses_a_probability_outside_zero_to_one(bad: float) -> None:
    with pytest.raises(ValueError):
        weighted_outcome(1.0, 2.0, renewal_probability=bad)


def test_the_weights_sum_to_one_at_this_depth() -> None:
    """Failure mode FM-D2-22 at depth 1: the two branch probabilities are ``p``
    and ``1 - p``, and there is deliberately no second input that could
    disagree."""

    assert "new_tenant_probability" not in {
        f.name for f in dataclasses.fields(MarketLeasingAssumptions)
    }
    for p in (0.0, 0.25, 0.65, 1.0):
        assert p + (1.0 - p) == 1.0


# =============================================================================
# Endpoint identity -- the key safety property
# =============================================================================


def test_p_equals_one_reproduces_the_renewal_branch_bit_identically() -> None:
    """Branches differing in rent, downtime, free rent, term, TI and LC. At
    ``p = 1`` every composed series must equal the renewal branch **exactly**
    (failure mode FM-D2-2)."""

    renewal, new_tenant = branches()
    composed = compose_expected_rollover(
        renewal, new_tenant, renewal_probability=1.0
    )

    for composed_name, branch_name in _COMPOSED_SERIES:
        left = getattr(composed, composed_name)
        right = getattr(renewal, branch_name)
        assert [v.hex() for v in left] == [v.hex() for v in right], composed_name

    assert composed.expected_tenant_improvement_amount.hex() == (
        renewal.tenant_improvement_amount.hex()
    )
    assert composed.expected_leasing_commission_amount.hex() == (
        renewal.leasing_commission_amount.hex()
    )


def test_p_equals_zero_reproduces_the_new_tenant_branch_bit_identically() -> None:
    renewal, new_tenant = branches()
    composed = compose_expected_rollover(
        renewal, new_tenant, renewal_probability=0.0
    )

    for composed_name, branch_name in _COMPOSED_SERIES:
        left = getattr(composed, composed_name)
        right = getattr(new_tenant, branch_name)
        assert [v.hex() for v in left] == [v.hex() for v in right], composed_name

    assert composed.expected_tenant_improvement_amount.hex() == (
        new_tenant.tenant_improvement_amount.hex()
    )
    assert composed.expected_leasing_commission_amount.hex() == (
        new_tenant.leasing_commission_amount.hex()
    )


def test_the_endpoints_hold_through_the_public_builder_too() -> None:
    for p, attribute in ((1.0, "renewal_branch"), (0.0, "new_tenant_branch")):
        result = expected(renewal_probability=p)
        branch = getattr(result, attribute)
        assert [v.hex() for v in result.expected_cash_base_rent] == [
            v.hex() for v in branch.cash_base_rent
        ]


# =============================================================================
# Common history -- shared months must not drift
# =============================================================================


def test_pre_rollover_months_are_hex_identical_to_both_branches() -> None:
    """Every month before the expiring lease rolls is shared history: both
    scenarios are the same signed lease. No probability should touch it."""

    for p in (0.1, 0.5, 0.65, 0.9):
        result = expected(renewal_probability=p)
        renewal = result.renewal_branch
        new_tenant = result.new_tenant_branch

        for period in range(1, EXPIRY_PERIOD + 1):
            index = period - 1
            assert renewal.cash_base_rent[index] == new_tenant.cash_base_rent[index]
            assert result.expected_cash_base_rent[index].hex() == (
                renewal.cash_base_rent[index].hex()
            )
            assert result.expected_contractual_base_rent[index].hex() == (
                renewal.contractual_base_rent[index].hex()
            )
            assert result.expected_occupancy[index] == 1.0
            assert result.expected_occupied_area_sf[index] == AREA


# =============================================================================
# Simple weighting goldens
# =============================================================================


def test_a_month_where_only_the_renewal_branch_pays() -> None:
    """Renewal $20,000, new tenant $0, ``p = 0.5`` -> $10,000."""

    assert weighted_outcome(20_000.0, 0.0, renewal_probability=0.5) == strict(10_000.0)


def test_a_month_where_both_branches_pay_different_amounts() -> None:
    """Renewal $20,000, new tenant $30,000, ``p = 0.5`` -> $25,000."""

    assert weighted_outcome(
        20_000.0, 30_000.0, renewal_probability=0.5
    ) == strict(25_000.0)


def test_every_composed_series_equals_the_hand_weighted_branch_values() -> None:
    """The general invariant, over every series and every month."""

    for p in (0.0, 0.25, 0.5, 0.65, 1.0):
        result = expected(renewal_probability=p)
        renewal = result.renewal_branch
        new_tenant = result.new_tenant_branch

        for composed_name, branch_name in _COMPOSED_SERIES:
            composed_series = getattr(result, composed_name)
            renewal_series = getattr(renewal, branch_name)
            new_series = getattr(new_tenant, branch_name)
            for index in range(len(result.months)):
                assert composed_series[index] == strict(
                    p * renewal_series[index] + (1 - p) * new_series[index]
                ), (composed_name, index, p)


# =============================================================================
# The D2 Section 1.2 rejected-method regression
# =============================================================================


def test_the_review_example_first_fifteen_months_are_not_zero() -> None:
    """**The defect that motivated Option B.** The rejected synthetic successor
    reported *zero* rent for the first five months after expiration, because
    its weighted downtime pushed commencement past them.

    In reality there is a 65% chance the sitting tenant simply renewed with no
    downtime and is paying full rent throughout. Each of those months is worth
    ``21,666.67`` in expectation, and D2 Section 1.2 quantifies the error as
    ``-21,666.67`` per month."""

    result = expected()

    # $40/SF on 10,000 SF is $33,333.33 a month; 65% of it is $21,666.67.
    for k in range(1, 16):
        period = EXPIRY_PERIOD + k
        assert result.expected_cash_base_rent[period - 1] == cents(21_666.666666666668), k
        assert result.expected_cash_base_rent[period - 1] > 0.0


def test_the_review_example_first_twenty_four_months_of_rent() -> None:
    """D2 Section 1.2: the true expectation is ``635,500.00``; the rejected
    method reported ``652,050.00``, an error of +2.6%."""

    result = expected()
    first_24 = sum(result.expected_cash_base_rent[EXPIRY_PERIOD : EXPIRY_PERIOD + 24])

    assert first_24 == cents(635_500.00)
    assert first_24 != cents(652_050.00)


def test_the_review_example_leasing_commission() -> None:
    """D2 Section 1.2: the true expectation is ``118,400.00``; the rejected
    method reported ``95,013.00``, an error of -19.8%.

    Each branch computes its own commission on its own full-term basis first,
    and only then are the two weighted:

    - renewal: 2% x 60 months x $33,333.33 = $40,000, weighted 0.65 -> $26,000
    - new: 6% x 120 months x $36,666.67 = $264,000, weighted 0.35 -> $92,400
    """

    result = expected()
    renewal = result.renewal_branch
    new_tenant = result.new_tenant_branch

    assert renewal.leasing_commission_amount == cents(40_000.00)
    assert new_tenant.leasing_commission_amount == cents(264_000.00)
    assert result.expected_leasing_commission_amount == cents(118_400.00)

    # The rejected shape -- a weighted rate on a weighted basis -- is materially
    # different, because a commission is a product of two branch-correlated
    # quantities and E[XY] != E[X]E[Y].
    weighted_rate = 0.65 * 0.02 + 0.35 * 0.06
    weighted_basis = (
        0.65 * renewal.full_term_contractual_face_rent
        + 0.35 * new_tenant.full_term_contractual_face_rent
    )
    assert weighted_rate * weighted_basis == cents(96_560.00)
    assert result.expected_leasing_commission_amount != cents(96_560.00)


def test_the_review_example_next_rollover_is_two_real_dates() -> None:
    """D2 Section 1.2: the rejected method produced a next-rollover date of
    ``m84`` -- "a date that occurs in neither scenario". Each branch keeps its
    own expiration instead."""

    result = expected()

    assert result.renewal_branch.successor_expiration_period == 72
    assert result.new_tenant_branch.successor_expiration_period == 141
    assert 84 not in {
        result.renewal_branch.successor_expiration_period,
        result.new_tenant_branch.successor_expiration_period,
    }

    # And no weighted-timing field exists on the composed result at all.
    composed_fields = {f.name for f in dataclasses.fields(ExpectedRollover)}
    for forbidden in (
        "expected_commencement_period",
        "expected_expiration_period",
        "expected_term_months",
        "expected_downtime_months",
        "successor_lease",
    ):
        assert forbidden not in composed_fields


def test_the_review_example_keeps_both_branch_paths_inspectable() -> None:
    """HD-D2-1: both branch assumption sets and both branch *results* are
    preserved for audit."""

    result = expected()
    renewal = result.renewal_branch
    new_tenant = result.new_tenant_branch

    assert renewal.starting_rent_psf == strict(40.0)
    assert renewal.term_months == 60
    assert renewal.downtime_months == 0.0
    assert renewal.free_rent_months == 0.0
    assert renewal.ti_psf == 10.0
    assert renewal.lc_pct == 0.02

    assert new_tenant.starting_rent_psf == strict(44.0)
    assert new_tenant.term_months == 120
    assert new_tenant.downtime_months == 9.0
    assert new_tenant.free_rent_months == 6.0
    assert new_tenant.ti_psf == 80.0
    assert new_tenant.lc_pct == 0.06


# =============================================================================
# Different terms and different event timing
# =============================================================================


def test_different_branch_terms_are_never_averaged() -> None:
    """``0.65 x 60 + 0.35 x 120`` is 81 months -- an expiration belonging to
    neither scenario, and not expressible under D1's month-aligned contract
    without rounding that silently moves the next rollover."""

    result = expected()

    assert result.renewal_branch.term_months == 60
    assert result.new_tenant_branch.term_months == 120
    assert not hasattr(result, "expected_term_months")


def test_costs_in_different_months_produce_two_weighted_events() -> None:
    """Renewal TI at its commencement, new-tenant TI nine months later. Both
    weighted events stand at their own real months; nothing moves to a
    synthetic intermediate date."""

    result = expected()
    renewal_event = result.renewal_branch.commencement_period
    new_event = result.new_tenant_branch.commencement_period

    assert renewal_event == 13
    assert new_event == 22

    # $10/SF x 10,000 x 0.65 = $65,000; $80/SF x 10,000 x 0.35 = $280,000.
    assert result.expected_tenant_improvements[renewal_event - 1] == strict(65_000.0)
    assert result.expected_tenant_improvements[new_event - 1] == strict(280_000.0)

    non_zero = [
        (index + 1, value)
        for index, value in enumerate(result.expected_tenant_improvements)
        if value
    ]
    assert [period for period, _ in non_zero] == [renewal_event, new_event]


def test_the_illustrative_two_event_ti_case() -> None:
    """Renewal $100,000 in one month, new tenant $600,000 in another, at
    ``p = 0.6`` -> $60,000 and $240,000, never $300,000 at one synthetic
    date."""

    assert weighted_outcome(100_000.0, 0.0, renewal_probability=0.6) == strict(60_000.0)
    assert weighted_outcome(0.0, 600_000.0, renewal_probability=0.6) == strict(240_000.0)


def test_expected_lc_events_also_stay_at_their_own_months() -> None:
    result = expected()
    renewal_event = result.renewal_branch.commencement_period
    new_event = result.new_tenant_branch.commencement_period

    assert result.expected_leasing_commissions[renewal_event - 1] == cents(26_000.0)
    assert result.expected_leasing_commissions[new_event - 1] == cents(92_400.0)
    assert sum(result.expected_leasing_commissions) == cents(118_400.0)


def test_a_branch_event_outside_the_projection_contributes_nothing() -> None:
    """One branch commences inside the window and the other beyond it. The
    in-window event is unaffected, and nothing is fabricated for the other."""

    # hold 1 -> 24 months. Renewal c = 13; new tenant D = 24 -> c = 37.
    result = expected(hold_period=1, new_downtime_months=24.0)

    assert result.renewal_branch.commences_within_projection is True
    assert result.new_tenant_branch.commences_within_projection is False
    assert len(result.months) == 24

    assert result.expected_tenant_improvements[12] == strict(65_000.0)
    assert sum(result.expected_tenant_improvements) == strict(65_000.0)
    assert sum(result.expected_leasing_commissions) == cents(26_000.0)


# =============================================================================
# The nonlinearity guardrails
# =============================================================================


def test_expected_cash_is_not_expected_face_times_expected_cash_factor() -> None:
    """**Mandatory.** ``E[Face x Factor] != E[Face] x E[Factor]`` whenever the
    two are branch-correlated -- which they always are here.

    The branches differ in both face rent ($40 vs $44) and cash factor (1.0 vs
    0.0 during the new tenant's downtime and free rent), so the invalid
    shortcut differs materially from the authoritative figure."""

    result = expected()
    renewal = result.renewal_branch
    new_tenant = result.new_tenant_branch
    p = 0.65

    differing = 0
    for index in range(len(result.months)):
        authoritative = result.expected_cash_base_rent[index]
        shortcut = (
            result.expected_contractual_base_rent[index]
            * result.expected_cash_rent_factor[index]
        )
        hand = (
            p * renewal.cash_base_rent[index]
            + (1 - p) * new_tenant.cash_base_rent[index]
        )

        assert authoritative == strict(hand), index
        if abs(authoritative - shortcut) > 1e-6:
            differing += 1

    assert differing > 0, (
        "the chosen case must actually exercise the nonlinearity"
    )


def test_the_nonlinear_cash_gap_is_material_in_a_named_month() -> None:
    """One month asserted by hand, so the size of the error is visible.

    Period 22 is the new tenant's commencement: it carries a full month of
    $36,666.67 face rent but collects nothing, because six months of free rent
    begin there. The renewal branch collects its full $33,333.33."""

    result = expected()
    index = 21  # period 22

    assert result.renewal_branch.cash_base_rent[index] == cents(33_333.333333333336)
    assert result.new_tenant_branch.cash_base_rent[index] == 0.0
    assert result.expected_cash_base_rent[index] == cents(21_666.666666666668)

    # Expected face is 0.65 x 33,333.33 + 0.35 x 36,666.67 = 34,500.00 and the
    # expected cash factor is 0.65 x 1 + 0.35 x 0 = 0.65, whose product is
    # 22,425.00 -- materially above the true 21,666.67.
    assert result.expected_contractual_base_rent[index] == cents(34_500.0)
    assert result.expected_cash_rent_factor[index] == strict(0.65)
    shortcut = (
        result.expected_contractual_base_rent[index]
        * result.expected_cash_rent_factor[index]
    )
    assert shortcut == cents(22_425.0)
    assert result.expected_cash_base_rent[index] != cents(22_425.0)


def test_expected_free_rent_dollars_are_not_reconstructed_from_factors() -> None:
    result = expected()
    renewal = result.renewal_branch
    new_tenant = result.new_tenant_branch
    p = 0.65

    differing = 0
    for index in range(len(result.months)):
        authoritative = result.expected_free_rent[index]
        shortcut = (
            result.expected_contractual_base_rent[index]
            * result.expected_free_rent_abatement_months[index]
        )
        hand = p * renewal.free_rent[index] + (1 - p) * new_tenant.free_rent[index]

        assert authoritative == strict(hand), index
        if abs(authoritative - shortcut) > 1e-6:
            differing += 1

    assert differing > 0


def test_expected_lc_is_not_a_weighted_rate_on_a_weighted_basis() -> None:
    """**Mandatory.** Each branch computes its commission on its own full-term
    basis first; only the results are weighted."""

    result = expected()
    renewal = result.renewal_branch
    new_tenant = result.new_tenant_branch
    p = 0.65

    authoritative = result.expected_leasing_commission_amount
    hand = (
        p * renewal.leasing_commission_amount
        + (1 - p) * new_tenant.leasing_commission_amount
    )
    shortcut = (p * renewal.lc_pct + (1 - p) * new_tenant.lc_pct) * (
        p * renewal.full_term_contractual_face_rent
        + (1 - p) * new_tenant.full_term_contractual_face_rent
    )

    assert authoritative == strict(hand)
    assert abs(authoritative - shortcut) > 20_000.0, (
        "the chosen case must make the product-of-averages error obvious"
    )


# =============================================================================
# Expected occupancy -- HD-D2-2
# =============================================================================


def test_expected_occupancy_may_be_fractional_and_is_named_accordingly() -> None:
    """During a full new-tenant downtime month the renewal branch is occupied
    and the new-tenant branch is dark, so the expectation is ``p`` -- a
    genuinely fractional figure that must never carry the physical name."""

    result = expected(renewal_probability=0.6)
    period = EXPIRY_PERIOD + 1

    assert result.renewal_branch.physical_occupancy[period - 1] == 1.0
    assert result.new_tenant_branch.physical_occupancy[period - 1] == 0.0
    assert result.expected_occupancy[period - 1] == strict(0.6)
    assert result.expected_occupied_area_sf[period - 1] == strict(6_000.0)

    assert not hasattr(result, "physical_occupancy")
    assert not hasattr(result, "occupied_area")


def test_branch_physical_occupancy_stays_integral_under_composition() -> None:
    """HD-D2-2: composition adds a third series; it never makes either branch's
    own occupancy fractional."""

    result = expected()

    assert set(result.renewal_branch.physical_occupancy) <= {0.0, 1.0}
    assert set(result.new_tenant_branch.physical_occupancy) <= {0.0, 1.0}
    assert any(0.0 < value < 1.0 for value in result.expected_occupancy)


def test_expected_occupancy_and_the_occupancy_factor_are_distinct() -> None:
    """**The mandatory distinction case.** In the new tenant's fractional
    boundary month the suite is physically occupied (factor ``1``) but only
    ``0.75`` of the month's rent is eligible.

    With the renewal branch fully occupied and ``p = 0.5``:
    ``expected_occupancy = 1.0`` while
    ``expected_successor_occupancy_factor = 0.875``."""

    result = expected(
        renewal_probability=0.5, new_downtime_months=9.25, new_free_rent_months=0.0
    )
    boundary = result.new_tenant_branch.commencement_period
    index = boundary - 1

    assert result.new_tenant_branch.physical_occupancy[index] == 1.0
    assert result.new_tenant_branch.successor_occupancy_factor[index] == strict(0.75)
    assert result.renewal_branch.physical_occupancy[index] == 1.0
    assert result.renewal_branch.successor_occupancy_factor[index] == 1.0

    assert result.expected_occupancy[index] == strict(1.0)
    assert result.expected_successor_occupancy_factor[index] == strict(0.875)
    assert result.expected_occupancy[index] != result.expected_successor_occupancy_factor[index]


def test_expected_vacancy_is_the_complement_of_expected_occupancy() -> None:
    result = expected(renewal_probability=0.6)

    for index in range(len(result.months)):
        assert result.expected_vacancy[index] == strict(
            1.0 - result.expected_occupancy[index]
        )
        assert result.expected_vacant_area_sf[index] == strict(
            AREA - result.expected_occupied_area_sf[index]
        )
        # The area invariant survives composition: the weights sum to one.
        assert (
            result.expected_occupied_area_sf[index]
            + result.expected_vacant_area_sf[index]
        ) == strict(AREA)


def test_expected_occupied_area_reconciles_to_area_times_occupancy() -> None:
    result = expected(renewal_probability=0.6)

    for index in range(len(result.months)):
        assert result.expected_occupied_area_sf[index] == strict(
            AREA * result.expected_occupancy[index]
        )


def test_expected_occupancy_is_positive_wherever_expected_rent_is() -> None:
    """Failure mode FM-D2-21: a period showing rent but zero expected
    occupancy, or the reverse, is incoherent."""

    for p in (0.0, 0.35, 0.65, 1.0):
        result = expected(renewal_probability=p)
        for index in range(len(result.months)):
            if result.expected_cash_base_rent[index] > 0.0:
                assert result.expected_occupancy[index] > 0.0, (p, index)


# =============================================================================
# Branch compatibility
# =============================================================================


def test_composing_branches_for_different_suites_is_refused() -> None:
    months = build_model_months(analysis_start=JAN_START, hold_period=15)
    defaults = assumptions()
    renewal = build_renewal_branch(
        expiring_lease(), suite=suite("S1"), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )
    other = build_new_tenant_branch(
        expiring_lease(suite_id="S2"), suite=suite("S2"), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )

    with pytest.raises(ValueError, match="different suites"):
        compose_expected_rollover(renewal, other, renewal_probability=0.5)


def test_composing_branches_for_different_leases_is_refused() -> None:
    months = build_model_months(analysis_start=JAN_START, hold_period=15)
    defaults = assumptions()
    renewal = build_renewal_branch(
        expiring_lease(), suite=suite(), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )
    other = build_new_tenant_branch(
        expiring_lease(lease_id="L2"), suite=suite(), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )

    with pytest.raises(ValueError, match="different expiring leases"):
        compose_expected_rollover(renewal, other, renewal_probability=0.5)


def test_composing_branches_on_different_timelines_is_refused() -> None:
    defaults = assumptions()
    renewal = build_renewal_branch(
        expiring_lease(), suite=suite(), analysis_start=JAN_START,
        months=build_model_months(analysis_start=JAN_START, hold_period=15),
        property_defaults=defaults,
    )
    other = build_new_tenant_branch(
        expiring_lease(), suite=suite(), analysis_start=JAN_START,
        months=build_model_months(analysis_start=JAN_START, hold_period=5),
        property_defaults=defaults,
    )

    with pytest.raises(ValueError, match="different month sequences"):
        compose_expected_rollover(renewal, other, renewal_probability=0.5)


def test_composing_branches_with_different_expirations_is_refused() -> None:
    months = build_model_months(analysis_start=JAN_START, hold_period=15)
    defaults = assumptions()
    renewal = build_renewal_branch(
        expiring_lease(), suite=suite(), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )
    other = build_new_tenant_branch(
        expiring_lease(
            lease_expiration_date=date(2028, 6, 30), lease_id="L1"
        ),
        suite=suite(), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )

    with pytest.raises(ValueError, match="different expiration periods"):
        compose_expected_rollover(renewal, other, renewal_probability=0.5)


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0])
def test_composition_refuses_a_probability_outside_the_domain(bad: float) -> None:
    renewal, new_tenant = branches()

    with pytest.raises(ValueError):
        compose_expected_rollover(renewal, new_tenant, renewal_probability=bad)


# =============================================================================
# Determinism, immutability, and the forward window
# =============================================================================


def test_repeated_composition_is_value_equal() -> None:
    first = expected()
    second = expected()

    assert first == second
    for left, right in zip(
        first.expected_cash_base_rent, second.expected_cash_base_rent
    ):
        assert left.hex() == right.hex()


def test_the_expected_result_is_frozen() -> None:
    result = expected()

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.renewal_probability = 0.1  # type: ignore[misc]


def test_a_mismatched_series_length_is_refused() -> None:
    result = expected()

    with pytest.raises(ValueError):
        dataclasses.replace(result, expected_cash_base_rent=(0.0,))


def test_no_random_module_is_reachable() -> None:
    """Monte Carlo is excluded from the base engine under any framing
    (D2 Section 5.3)."""

    import anchor.leasing.rollover as rollover_module

    source = __import__("pathlib").Path(rollover_module.__file__).read_text(
        encoding="utf-8"
    )
    assert "import random" not in source
    assert "numpy" not in source


def test_the_forward_exit_window_is_composed_normally() -> None:
    """No terminal smoothing and no sale-date probability logic."""

    # hold 1 -> hold months 1-12, forward window 13-24.
    result = expected(hold_period=1)

    forward = [m for m in result.months if m.is_forward_exit_month]
    assert len(forward) == 12
    for month in forward:
        index = month.period_index - 1
        assert result.expected_cash_base_rent[index] == strict(
            0.65 * result.renewal_branch.cash_base_rent[index]
            + 0.35 * result.new_tenant_branch.cash_base_rent[index]
        )


def test_a_branch_whose_successor_has_expired_contributes_its_own_values() -> None:
    """Before D2.6, a branch whose first successor has expired simply
    contributes what it is actually doing -- which may be zero. No second
    successor is generated."""

    # Renewal term 12 -> expires period 24; new tenant runs far past it.
    result = expected(hold_period=15, renewal_term_months=12)
    renewal = result.renewal_branch

    assert renewal.successor_expiration_period == 24
    after = 25
    assert renewal.cash_base_rent[after - 1] == 0.0
    assert renewal.physical_occupancy[after - 1] == 0.0
    assert result.expected_cash_base_rent[after - 1] == strict(
        0.35 * result.new_tenant_branch.cash_base_rent[after - 1]
    )


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


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_a_probability_outside_zero_to_one_is_an_error(bad: float) -> None:
    result = validate(renewal_probability=bad)

    assert not result.is_valid  # type: ignore[attr-defined]
    assert LeaseIssueCode.RENEWAL_PROBABILITY_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_probability_is_an_error(bad: float) -> None:
    result = validate(renewal_probability=bad)
    assert LeaseIssueCode.NON_FINITE_VALUE in codes(result)


@pytest.mark.parametrize("p", [0.0, 0.25, 0.65, 1.0])
def test_a_probability_inside_the_domain_is_valid(p: float) -> None:
    assert validate(renewal_probability=p).is_valid  # type: ignore[attr-defined]


@pytest.mark.parametrize("p", [0.01, 0.5, 0.65, 0.99])
def test_a_blended_probability_raises_the_weighted_rollover_warning(p: float) -> None:
    """D0 Section 8.4 / failure mode FM-D2-18: at ``0 < p < 1`` the composed
    result corresponds to no single real-world outcome, and an interface must
    never present it as a known tenancy."""

    result = validate(renewal_probability=p)

    assert result.is_valid  # type: ignore[attr-defined]
    assert LeaseIssueCode.WEIGHTED_ROLLOVER_APPLIED in codes(result)
    warning = next(
        issue
        for issue in result.issues  # type: ignore[attr-defined]
        if issue.code is LeaseIssueCode.WEIGHTED_ROLLOVER_APPLIED
    )
    assert warning.severity is LeaseIssueSeverity.WARNING


@pytest.mark.parametrize("p", [0.0, 1.0])
def test_an_endpoint_probability_raises_no_warning(p: float) -> None:
    """At an endpoint the result *is* a single scenario, so the caution does
    not apply."""

    result = validate(renewal_probability=p)

    assert result.is_valid  # type: ignore[attr-defined]
    assert LeaseIssueCode.WEIGHTED_ROLLOVER_APPLIED not in codes(result)


def test_a_suite_override_is_checked_against_the_probability_domain() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [
            Suite(
                suite_id="S1",
                suite_area_sf=AREA,
                market_leasing_override=assumptions(renewal_probability=1.5),
            )
        ],
        [],
        market_leasing=assumptions(renewal_probability=0.0),
    )

    issue = next(
        item
        for item in result.issues
        if item.code is LeaseIssueCode.RENEWAL_PROBABILITY_OUT_OF_DOMAIN
    )
    assert issue.path == "suites[0].market_leasing_override.renewal_probability"


def test_an_incomplete_assumption_record_cannot_be_constructed() -> None:
    complete = {
        f.name: getattr(assumptions(), f.name)
        for f in dataclasses.fields(MarketLeasingAssumptions)
    }
    fields = dict(complete)
    del fields["renewal_probability"]

    with pytest.raises(TypeError):
        MarketLeasingAssumptions(**fields)  # type: ignore[arg-type]
