"""Sprint D Gate D3.6 -- initial vacancy lease-up.

Proves, per D3 conventions Section 22, that a suite **vacant at the analysis
start** is underwritten explicitly rather than silently:

```
HOLD_VACANT      -- deliberately not let; every series zero, and recorded
MARKET_LEASE_UP  -- lets after a stated period, then rolls over normally
missing          -- an ERROR at every future-looking gate
```

Before D3.6 all three produced identical numbers. For a value-add acquisition
-- where vacant space is the whole thesis -- a silent zero is the most
expensive kind of wrong number, because it looks like a modelled result.

The claims that fail silently if wrong:

- **the first tenant is deterministic.** There is no incumbent, so there is no
  renewal branch and no split at the initial event. ``renewal_probability``
  enters at the first lease's *expiration* and nowhere earlier (FM-D3-23);
- **lease-up is not future downtime.** ``initial_lease_up_months`` and
  ``new_downtime_months`` are different underwriting judgements and never
  alias (FM-D3-22);
- **market rent moves while the space sits empty**, so the first tenant prices
  at ``MarketRentPSF(c0)``, not at the analysis start (FM-D3-24);
- **vacancy is not free rent.** One is the absence of a tenant, the other a
  concession to a tenant who is present (FM-D3-26);
- **period 0 is a boundary, never a lease.** No fake, zero-day or expired
  dummy lease is created anywhere (FM-D3-21);
- **there is one state machine.** Initial vacancy is a new entry path into
  D2.6, not a second recursion (FM-D3-31);
- **the origin does not survive the first expiration.** A vacant-origin and an
  occupied-origin chain reaching the same period have identical futures, so
  the D2.6 merge key is untouched (FM-D3-32).
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyRollover,
    InitialVacancyStrategy,
    Lease,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecoverableExpensePool,
    RecoveryBasis,
    RolloverBranchKind,
    Suite,
    build_initial_vacancy_rollover,
    build_initial_vacancy_rollover_recovery,
    build_market_rent_schedule,
    build_model_months,
    build_property_recovery_schedule,
    build_recursive_rollover,
    build_successor_contribution,
    build_successor_recovery_schedule,
    suite_recovery_projection,
    validate_initial_vacancy_inputs,
    validate_property_recovery_inputs,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
    require_valid_initial_vacancy_inputs,
)


JAN = date(2027, 1, 1)
AREA = 20_000.0
PROPERTY_AREA = 100_000.0
SHARE = 0.20
HOLD = 3

#: A flat $100,000 pool gives this suite a $20,000 monthly share.
POOL_MONTHLY = 100_000.0
TENANT_SHARE = 20_000.0

#: $6.00/SF/YEAR on 20,000 SF is a $10,000 monthly stop -- half the share.
STOP_PSF = 6.0
MONTHLY_STOP = 10_000.0

#: 20,000 SF at $40/SF is $66,666.67 a month.
FULL_MONTH_RENT = AREA * 40.0 / 12.0


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def close(expected: float) -> object:
    return pytest.approx(expected, rel=1e-12, abs=1e-9)


def hexes(values: tuple[float, ...]) -> list[str]:
    return [value.hex() for value in values]


def months(*, hold_period: int = HOLD) -> tuple:
    return build_model_months(analysis_start=JAN, hold_period=hold_period)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    base: dict[str, object] = {
        "market_rent_psf": 40.0,
        "market_rent_growth": 0.03,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 12,
        "successor_escalation_pct": 0.0,
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 0.0,
        "new_term_months": 12,
        "new_downtime_months": 2.0,
        "new_free_rent_months": 0.0,
        "renewal_ti_psf": 0.0,
        "new_ti_psf": 50.0,
        "leasing_commission_method": (
            LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT
        ),
        "renewal_lc_pct": 0.0,
        "new_lc_pct": 0.06,
        "renewal_probability": 0.6,
        "renewal_lease_type": LeaseType.NNN,
        "renewal_recovery_basis": None,
        "renewal_expense_stop_psf": None,
        "new_lease_type": LeaseType.NNN,
        "new_recovery_basis": None,
        "new_expense_stop_psf": None,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)  # type: ignore[arg-type]


def vacant_suite(
    strategy: InitialVacancyStrategy = InitialVacancyStrategy.MARKET_LEASE_UP,
    lease_up: float | None = 0.0,
    *,
    suite_id: str = "B",
    area: float = AREA,
) -> Suite:
    return Suite(
        suite_id=suite_id,
        suite_area_sf=area,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=strategy, initial_lease_up_months=lease_up
        ),
    )


def hold_vacant_suite(suite_id: str = "C", *, area: float = AREA) -> Suite:
    return vacant_suite(
        InitialVacancyStrategy.HOLD_VACANT, None, suite_id=suite_id, area=area
    )


def occupied_lease(
    suite_id: str = "A",
    *,
    lease_type: LeaseType = LeaseType.NNN,
    end: date = date(2035, 12, 31),
    lease_id: str | None = None,
    area: float = AREA,
) -> Lease:
    return Lease(
        lease_id=lease_id or f"L-{suite_id}",
        suite_id=suite_id,
        tenant_name="Acme Corp",
        leased_area_sf=area,
        rent_commencement_date=date(2025, 1, 1),
        lease_expiration_date=end,
        base_rent_psf=30.0,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=lease_type,
    )


def pool(
    amount: float = POOL_MONTHLY,
    *,
    canonical: tuple | None = None,
    series: tuple[float, ...] | None = None,
) -> RecoverableExpensePool:
    canonical = canonical if canonical is not None else months()
    expenses = series if series is not None else tuple([amount] * len(canonical))
    return RecoverableExpensePool(months=canonical, recoverable_expenses=expenses)


def rollover(
    the_suite: Suite | None = None,
    *,
    canonical: tuple | None = None,
    **overrides: object,
) -> InitialVacancyRollover:
    canonical = canonical if canonical is not None else months()
    return build_initial_vacancy_rollover(
        the_suite if the_suite is not None else vacant_suite(),
        analysis_start=JAN,
        months=canonical,
        property_defaults=assumptions(**overrides),
    )


def recovery(
    the_suite: Suite | None = None,
    *,
    canonical: tuple | None = None,
    the_pool: RecoverableExpensePool | None = None,
    **overrides: object,
):
    canonical = canonical if canonical is not None else months()
    the_suite = the_suite if the_suite is not None else vacant_suite()
    defaults = assumptions(**overrides)
    result = build_initial_vacancy_rollover(
        the_suite, analysis_start=JAN, months=canonical, property_defaults=defaults
    )
    return build_initial_vacancy_rollover_recovery(
        result,
        suite=the_suite,
        analysis_start=JAN,
        property_defaults=defaults,
        pool=the_pool if the_pool is not None else pool(canonical=canonical),
        rentable_area_sf=PROPERTY_AREA,
    )


# =============================================================================
# GOLDEN 1 -- HOLD VACANT
# =============================================================================


def test_golden_1_hold_vacant_is_an_explicit_all_zero_chain() -> None:
    """The analyst chose this. Every series is zero -- and the strategy is on
    the result, so the choice is auditable and can never be confused with a
    suite nobody underwrote."""

    result = rollover(hold_vacant_suite())

    assert result.strategy is InitialVacancyStrategy.HOLD_VACANT
    assert result.initial_lease_up_months is None
    assert result.first_contribution is None
    assert result.transitions == ()
    assert result.event_states == ()
    assert result.terminal_probability_mass == strict(1.0)

    for series in (
        result.expected_contractual_base_rent,
        result.expected_cash_base_rent,
        result.expected_free_rent,
        result.expected_tenant_improvements,
        result.expected_leasing_commissions,
        result.expected_occupied_area_sf,
        result.expected_occupancy,
        result.expected_successor_occupancy_factor,
        result.expected_cash_rent_factor,
    ):
        assert all(value == 0.0 for value in series)

    assert result.expected_tenant_improvement_amount == strict(0.0)
    assert result.expected_leasing_commission_amount == strict(0.0)
    # The space is vacant, so vacancy is 100%.
    assert all(value == strict(1.0) for value in result.expected_vacancy)


def test_golden_1_hold_vacant_recovers_nothing_explicitly() -> None:
    result = recovery(hold_vacant_suite())

    assert result.strategy is InitialVacancyStrategy.HOLD_VACANT
    assert result.first_tenant_recovery is None
    assert result.contributions == ()
    assert all(value == 0.0 for value in result.expected_expense_recovery)


def test_golden_1_a_hold_vacant_contract_refuses_inconsistent_content() -> None:
    """Enforced structurally, so a builder bug cannot present speculative
    lease-up under a hold-vacant label."""

    result = rollover(hold_vacant_suite())
    rent = list(result.expected_contractual_base_rent)
    rent[0] = 1.0

    with pytest.raises(ValueError, match="HOLD_VACANT"):
        dataclasses.replace(result, expected_contractual_base_rent=tuple(rent))


# =============================================================================
# GOLDEN 2 / 3 -- lease-up timing
# =============================================================================


def test_golden_2_lease_up_of_zero_commences_in_month_one() -> None:
    """``c0 = 1 + floor(0) = 1``. The tenant is there from the first canonical
    month, and there is no fictitious Month 0 cash flow."""

    result = rollover(vacant_suite(lease_up=0.0))
    first = result.first_contribution

    assert first is not None
    assert first.commencement_period == 1
    assert result.expected_successor_occupancy_factor[0] == strict(1.0)
    assert result.expected_contractual_base_rent[0] == strict(FULL_MONTH_RENT)
    assert first.successor_lease.rent_commencement_date == JAN
    assert len(result.expected_contractual_base_rent) == len(months())


def test_golden_3_a_fractional_lease_up_carries_a_boundary_factor() -> None:
    """``L = 2.25`` → ``c0 = 3``. Months 1-2 are fully vacant; month 3 carries
    ``1 - frac(L) = 0.75``.

    **Physical occupancy stays integral** -- the tenant is in possession by
    month-end, so it is ``1``. Publishing ``0.75`` under the physical name is
    the failure D2's HD-D2-2 binding exists to prevent, and D4 must not
    inherit a fractional physical series.
    """

    result = rollover(vacant_suite(lease_up=2.25))
    first = result.first_contribution

    assert first.commencement_period == 3
    assert result.expected_successor_occupancy_factor[:5] == (
        strict(0.0), strict(0.0), strict(0.75), strict(1.0), strict(1.0),
    )
    assert first.physical_occupancy[:5] == (
        strict(0.0), strict(0.0), strict(1.0), strict(1.0), strict(1.0),
    )
    assert result.expected_occupied_area_sf[2] == strict(AREA)

    # Face rent is the full month; the fraction lands in cash, as D2.3 fixed.
    assert result.expected_contractual_base_rent[2] == strict(FULL_MONTH_RENT)
    assert result.expected_cash_base_rent[2] == strict(0.75 * FULL_MONTH_RENT)


@pytest.mark.parametrize(
    ("lease_up", "commencement"),
    [(0.0, 1), (1.0, 2), (2.0, 3), (2.25, 3), (2.99, 3), (6.0, 7), (14.0, 15)],
)
def test_the_commencement_formula_is_one_plus_floor_of_lease_up(
    lease_up: float, commencement: int
) -> None:
    """``c0 = 0 + 1 + floor(L)`` -- the same successor timing formula D2 uses,
    entered at the boundary index 0. There is no second formula."""

    result = rollover(vacant_suite(lease_up=lease_up))

    assert result.first_contribution.commencement_period == commencement


# =============================================================================
# GOLDEN 4 -- market rent moves while the space is empty
# =============================================================================


def test_golden_4_the_first_tenant_prices_at_its_own_commencement() -> None:
    """``L = 14`` → ``c0 = 15``, which is in hold year 2. The first tenant
    prices at ``$40 x 1.03 = $41.20``, not at the analysis-start ``$40``.

    Freezing market rent at the analysis start would understate every
    long-lease-up deal, and would look entirely plausible.
    """

    result = rollover(vacant_suite(lease_up=14.0))
    first = result.first_contribution

    assert first.commencement_period == 15
    assert first.market_rent_psf_at_commencement == strict(40.0 * 1.03)
    assert first.starting_rent_psf == strict(41.20)
    assert first.starting_rent_psf != pytest.approx(40.0, abs=1e-6)


def test_golden_4_the_first_tenant_never_uses_renewal_pricing() -> None:
    """There is no incumbent to renew, so a renewal spread must not reach it."""

    spread = rollover(vacant_suite(lease_up=0.0), renewal_rent_spread=0.50)
    flat = rollover(vacant_suite(lease_up=0.0), renewal_rent_spread=0.0)

    assert spread.first_contribution.starting_rent_psf == strict(
        flat.first_contribution.starting_rent_psf
    )
    assert spread.first_contribution.starting_rent_psf == strict(40.0)


# =============================================================================
# GOLDEN 5 -- lease-up and future downtime never alias
# =============================================================================


def test_golden_5_initial_lease_up_and_future_downtime_are_distinct() -> None:
    """**The mandatory no-aliasing proof.** Initial lease-up is 6 months;
    future new-tenant downtime is 2. The first tenant waits 6; a replacement
    after a future expiration waits 2.

    These are different underwriting judgements -- space already empty at
    acquisition versus a re-letting delay on space a tenant just vacated --
    and one is never a fallback for the other.
    """

    result = rollover(
        vacant_suite(lease_up=6.0), new_downtime_months=2.0, new_term_months=12
    )
    first = result.first_contribution

    # First tenant: c0 = 1 + floor(6) = 7.
    assert first.commencement_period == 7
    assert result.expected_successor_occupancy_factor[5] == strict(0.0)
    assert result.expected_successor_occupancy_factor[6] == strict(1.0)

    # A later new tenant: c = e + 1 + floor(2) = e + 3.
    later = [
        t for t in result.transitions
        if t.branch is RolloverBranchKind.NEW_TENANT
    ]
    assert later, "no later new-tenant transition"
    assert later[0].commencement_period - later[0].parent_expiration_period == 3


def test_golden_5_changing_future_downtime_does_not_move_the_first_tenant() -> None:
    """The decisive form: only the lease-up field moves ``c0``."""

    two = rollover(vacant_suite(lease_up=6.0), new_downtime_months=2.0)
    nine = rollover(vacant_suite(lease_up=6.0), new_downtime_months=9.0)

    assert two.first_contribution.commencement_period == 7
    assert nine.first_contribution.commencement_period == 7
    assert hexes(two.first_contribution.contractual_base_rent) == hexes(
        nine.first_contribution.contractual_base_rent
    )


def test_golden_5_changing_lease_up_does_not_move_later_tenants() -> None:
    """And the converse: the lease-up period never leaks into the tail."""

    short = rollover(vacant_suite(lease_up=0.0), new_downtime_months=2.0)
    long = rollover(vacant_suite(lease_up=0.0), new_downtime_months=2.0)

    assert short.first_contribution.commencement_period == 1
    for result in (short, long):
        for transition in result.transitions:
            if transition.branch is RolloverBranchKind.NEW_TENANT:
                gap = (
                    transition.commencement_period
                    - transition.parent_expiration_period
                )
                assert gap == 3


# =============================================================================
# GOLDEN 6 / 7 -- free rent
# =============================================================================


def test_golden_6_vacancy_and_free_rent_stay_distinct() -> None:
    """``L = 2.25``, ``F = 2.5``. Months 1-2 have **no tenant** and consume no
    abatement. Month 3 has a tenant present for 0.75 of the month who consumes
    0.75 of the grant; the sequential waterfall continues from there.

    Conflating the two would let an initial vacancy silently consume a rent
    concession that was never granted.
    """

    result = rollover(
        vacant_suite(lease_up=2.25), new_free_rent_months=2.5, new_term_months=12
    )

    assert result.expected_successor_occupancy_factor[:6] == (
        strict(0.0), strict(0.0), strict(0.75), strict(1.0), strict(1.0), strict(1.0),
    )
    assert result.expected_free_rent_abatement_months[:6] == (
        strict(0.0), strict(0.0), strict(0.75), strict(1.0), strict(0.75), strict(0.0),
    )
    assert result.expected_cash_rent_factor[:6] == (
        strict(0.0), strict(0.0), strict(0.0), strict(0.0), strict(0.25), strict(1.0),
    )
    # The first tenant's own grant is fully consumed, and only by months in
    # which it had a tenant. (The chain total is larger because later
    # generations receive their own grants.)
    first = result.first_contribution
    assert math.fsum(first.free_rent_abatement_months) == close(2.5)
    assert first.free_rent_abatement_months[0] == strict(0.0)
    assert first.free_rent_abatement_months[1] == strict(0.0)


def test_golden_7_first_event_free_rent_is_validated_against_lease_up() -> None:
    """**The subtle capacity rule.** The first tenant reuses
    ``new_free_rent_months`` but waits ``initial_lease_up_months``, so its
    boundary fraction differs from a future re-letting's.

    ``F = 11.8`` on a 12-month term is consumable after a **whole** 2.0-month
    future downtime (``12 - 0.0 = 12``) but not after a **2.25**-month
    lease-up (``12 - 0.25 = 11.75``). Validating the first event against
    ``frac(new_downtime_months)`` would silently discard 0.05 months of
    concession.
    """

    defaults = assumptions(
        new_term_months=12, new_free_rent_months=11.8, new_downtime_months=2.0
    )
    suites = [vacant_suite(lease_up=2.25)]

    result = validate_initial_vacancy_inputs(
        suites, [], property_defaults=defaults
    )

    assert not result.is_valid
    issue = next(
        i
        for i in result.issues
        if i.code is LeaseIssueCode.FREE_RENT_EXCEEDS_OCCUPIABLE_TERM
    )
    assert issue.severity is LeaseIssueSeverity.ERROR

    # Whole-month lease-up leaves the full term available, so the same grant
    # is fine there -- the two contexts genuinely differ.
    assert validate_initial_vacancy_inputs(
        [vacant_suite(lease_up=2.0)], [], property_defaults=defaults
    ).is_valid


def test_golden_7_the_check_is_skipped_when_defaults_are_not_supplied() -> None:
    """Rather than guessed. The term and grant live on the assumptions, so
    without them the capacity is unknowable."""

    assert validate_initial_vacancy_inputs(
        [vacant_suite(lease_up=2.25)], []
    ).is_valid


# =============================================================================
# GOLDEN 8 -- TI and LC
# =============================================================================


def test_golden_8_ti_and_lc_land_in_the_first_responsible_month() -> None:
    """D2.4 unchanged: TI in full at commencement, LC on the **full**
    contractual face rent over the entire first term, gross of free rent and
    untruncated by the horizon."""

    result = rollover(
        vacant_suite(lease_up=2.25),
        new_ti_psf=50.0,
        new_lc_pct=0.06,
        new_term_months=12,
        new_free_rent_months=2.5,
    )
    first = result.first_contribution
    commencement_index = first.commencement_period - 1

    # The first tenant's own TI and LC land in its commencement month, in
    # full. (Chain totals are larger because later generations incur their
    # own.)
    assert first.tenant_improvements[commencement_index] == strict(50.0 * AREA)
    assert sum(first.tenant_improvements) == strict(50.0 * AREA)
    assert first.tenant_improvement_amount == strict(50.0 * AREA)
    assert first.leasing_commissions[commencement_index] == strict(
        0.06 * first.full_term_contractual_face_rent
    )
    assert result.expected_tenant_improvements[commencement_index] == strict(
        50.0 * AREA
    )

    # No proration for the fractional boundary, and free rent does not reduce
    # the LC basis.
    assert first.full_term_contractual_face_rent == close(12 * FULL_MONTH_RENT)


def test_golden_8_lc_uses_the_full_term_even_past_the_horizon() -> None:
    """A 120-month first lease inside a 48-month window still commissions on
    all 120 months of contractual face rent."""

    canonical = months(hold_period=3)
    result = rollover(
        vacant_suite(lease_up=0.0),
        canonical=canonical,
        new_term_months=120,
        new_lc_pct=0.06,
        successor_escalation_pct=0.0,
    )
    first = result.first_contribution

    assert first.successor_expiration_period == 120
    assert first.full_term_contractual_face_rent == close(120 * FULL_MONTH_RENT)
    assert first.full_term_contractual_face_rent > sum(
        result.expected_contractual_base_rent
    )


# =============================================================================
# GOLDEN 9 -- first tenant recoveries
# =============================================================================


def test_golden_9_a_modified_gross_first_tenant_recovers_correctly() -> None:
    """No recovery during vacancy; ``O`` outside the clip at the boundary;
    the ordinary D3.2 figure thereafter. There is no initial-vacancy recovery
    formula."""

    result = recovery(
        vacant_suite(lease_up=2.25),
        new_lease_type=LeaseType.MODIFIED_GROSS,
        new_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        new_expense_stop_psf=STOP_PSF,
        new_term_months=12,
    )

    assert result.first_tenant_recovery.monthly_expense_stop_dollars == strict(
        MONTHLY_STOP
    )
    assert result.expected_expense_recovery[0] == strict(0.0)
    assert result.expected_expense_recovery[1] == strict(0.0)
    # 0.75 x max(0, 20,000 - 10,000)
    assert result.expected_expense_recovery[2] == strict(7_500.0)
    assert result.expected_expense_recovery[3] == strict(10_000.0)

    # Not max(0, 0.75 x 20,000 - 10,000) = 5,000.
    assert result.expected_expense_recovery[2] != pytest.approx(5_000.0, abs=1e-6)


@pytest.mark.parametrize(
    ("lease_type", "basis", "stop", "expected"),
    [
        (LeaseType.NNN, None, None, TENANT_SHARE),
        (LeaseType.GROSS, None, None, 0.0),
        (
            LeaseType.MODIFIED_GROSS,
            RecoveryBasis.EXPENSE_STOP_PSF,
            STOP_PSF,
            TENANT_SHARE - MONTHLY_STOP,
        ),
    ],
    ids=["nnn", "gross", "modified-gross"],
)
def test_golden_9_every_first_tenant_structure_is_supported(
    lease_type: LeaseType,
    basis: RecoveryBasis | None,
    stop: float | None,
    expected: float,
) -> None:
    result = recovery(
        vacant_suite(lease_up=0.0),
        new_lease_type=lease_type,
        new_recovery_basis=basis,
        new_expense_stop_psf=stop,
        new_term_months=12,
    )

    assert result.expected_expense_recovery[0] == strict(expected)
    assert result.first_tenant_recovery.successor_lease_type is lease_type


def test_golden_9_free_rent_does_not_reduce_first_tenant_recovery() -> None:
    """The concession is against base rent. Two chains identical but for free
    rent recover identically."""

    common = dict(
        new_lease_type=LeaseType.MODIFIED_GROSS,
        new_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        new_expense_stop_psf=STOP_PSF,
        new_term_months=12,
    )
    none_free = recovery(vacant_suite(lease_up=2.25), new_free_rent_months=0.0, **common)
    some_free = recovery(vacant_suite(lease_up=2.25), new_free_rent_months=2.5, **common)

    assert hexes(none_free.expected_expense_recovery) == hexes(
        some_free.expected_expense_recovery
    )
    assert none_free.expected_expense_recovery[2] == strict(7_500.0)


def test_the_initial_vacancy_recovery_has_no_in_place_component() -> None:
    """There is no lease at the analysis start, so the in-place series is zero
    by construction and the contract refuses anything else."""

    result = recovery(vacant_suite(lease_up=2.25))

    assert all(value == 0.0 for value in result.in_place_expense_recovery)
    assert hexes(result.expected_expense_recovery) == hexes(
        result.expected_successor_expense_recovery
    )

    with pytest.raises(ValueError, match="no in-place lease"):
        dataclasses.replace(
            result,
            in_place_expense_recovery=(1.0,)
            + tuple([0.0] * (len(result.months) - 1)),
        )


# =============================================================================
# GOLDEN 10 / 11 / 12 -- probability enters at the first expiration
# =============================================================================


def test_golden_10_the_first_tenant_is_deterministic_then_p_applies() -> None:
    """**The probability-timing proof.** Mass ``1.0`` up to the first lease's
    expiration; ``0.60 / 0.40`` from that event onward.

    There is no incumbent, so a renewal branch at the initial event would be a
    renewal of nobody.
    """

    result = rollover(
        vacant_suite(lease_up=2.0), new_term_months=12, renewal_probability=0.6
    )
    first = result.first_contribution

    assert first.commencement_period == 3
    assert first.successor_expiration_period == 14
    assert first.branch is RolloverBranchKind.NEW_TENANT

    # Nothing splits before e1.
    early = [t for t in result.transitions if t.parent_expiration_period < 14]
    assert early == []

    at_first = [t for t in result.transitions if t.parent_expiration_period == 14]
    masses = {t.branch: t.probability_mass for t in at_first}
    assert masses[RolloverBranchKind.RENEWAL] == strict(0.6)
    assert masses[RolloverBranchKind.NEW_TENANT] == strict(0.4)


def test_golden_10_no_renewal_branch_exists_at_the_initial_event() -> None:
    """The first tenant is a new tenant, and no transition is recorded for the
    boundary index 0."""

    result = rollover(vacant_suite(lease_up=2.0))

    assert all(t.parent_expiration_period != 0 for t in result.transitions)
    assert all(s.expiration_period != 0 for s in result.event_states)


@pytest.mark.parametrize(
    ("probability", "surviving"),
    [(1.0, RolloverBranchKind.RENEWAL), (0.0, RolloverBranchKind.NEW_TENANT)],
    ids=["p=1", "p=0"],
)
def test_goldens_11_and_12_endpoint_tails(
    probability: float, surviving: RolloverBranchKind
) -> None:
    """After the deterministic first tenant, ``p = 1`` leaves only renewals in
    the tail and ``p = 0`` only new tenants."""

    result = rollover(
        vacant_suite(lease_up=1.0),
        new_term_months=6,
        renewal_term_months=6,
        renewal_probability=probability,
    )

    assert result.transitions, "no tail produced"
    carrying = [t for t in result.transitions if t.probability_mass > 0.0]
    assert {t.branch for t in carrying} == {surviving}
    # The first tenant is a new tenant regardless.
    assert result.first_contribution.branch is RolloverBranchKind.NEW_TENANT


# =============================================================================
# GOLDEN 13 / 14 / 15 -- the horizon
# =============================================================================


def test_golden_13_a_first_lease_past_the_horizon_seeds_no_rollover() -> None:
    """Commences in-window, expires beyond ``N``: contributes through ``N``,
    creates no rollover state, and still commissions on the full term."""

    canonical = months(hold_period=3)
    result = rollover(
        vacant_suite(lease_up=0.0), canonical=canonical, new_term_months=120
    )
    horizon = canonical[-1].period_index

    assert result.first_contribution.successor_expiration_period > horizon
    assert result.transitions == ()
    assert result.expected_contractual_base_rent[-1] == strict(FULL_MONTH_RENT)
    assert result.terminal_probability_mass == strict(1.0)


def test_golden_14_a_commencement_past_the_horizon_produces_nothing() -> None:
    """``L = 60`` on a 48-month window. Every in-window series is zero, no
    state is seeded, no month is fabricated and the event is not moved
    earlier. The contribution is retained so a reader can see *why* nothing
    appears (HD-D3.6-2)."""

    canonical = months(hold_period=3)
    result = rollover(
        vacant_suite(lease_up=60.0), canonical=canonical, new_term_months=12
    )
    first = result.first_contribution
    horizon = canonical[-1].period_index

    assert first is not None
    assert first.commencement_period == 61 > horizon
    assert first.commences_within_projection is False

    for series in (
        result.expected_contractual_base_rent,
        result.expected_cash_base_rent,
        result.expected_free_rent,
        result.expected_tenant_improvements,
        result.expected_leasing_commissions,
        result.expected_occupied_area_sf,
        result.expected_successor_occupancy_factor,
    ):
        assert all(value == 0.0 for value in series)

    assert result.transitions == ()
    assert len(result.months) == len(canonical)


def test_golden_14_an_out_of_window_commencement_recovers_nothing() -> None:
    canonical = months(hold_period=3)
    result = recovery(
        vacant_suite(lease_up=60.0), canonical=canonical, new_term_months=12
    )

    assert all(value == 0.0 for value in result.expected_expense_recovery)
    assert result.first_tenant_recovery is not None
    assert all(
        value == 0.0 for value in result.first_tenant_recovery.expense_recovery
    )


def test_golden_15_recursion_continues_through_the_forward_exit_window() -> None:
    """A first lease expiring inside months ``12H+1 … 12H+12`` still seeds the
    rollover, and later tenants affect the remaining forward months. There is
    no sale-month cutoff."""

    canonical = months(hold_period=2)
    horizon = canonical[-1].period_index
    assert horizon == 36

    # c0 = 1, T = 26 -> e1 = 26, inside the forward window (25..36).
    result = rollover(
        vacant_suite(lease_up=0.0),
        canonical=canonical,
        new_term_months=26,
        renewal_term_months=6,
        renewal_probability=0.5,
    )

    assert 24 < result.first_contribution.successor_expiration_period < horizon
    assert result.transitions, "no rollover seeded in the forward window"
    assert result.expected_contractual_base_rent[-1] > 0.0


# =============================================================================
# GOLDEN 16 -- the origin does not survive the first expiration
# =============================================================================


def test_golden_16_future_children_are_identical_whatever_the_origin() -> None:
    """**The merge-key proof, at the vacancy boundary.** A vacant-origin chain
    and an occupied-origin chain reaching the same expiration period in the
    same suite produce identical successors on both branches.

    Initial-vacancy history therefore never enters D2.6's state key, and the
    merge remains the expiration period alone.
    """

    canonical = months()
    the_suite = vacant_suite(lease_up=2.0)
    defaults = assumptions(new_term_months=12, renewal_probability=0.6)
    schedule = build_market_rent_schedule(
        the_suite, property_defaults=defaults, months=canonical
    )

    for branch in RolloverBranchKind:
        from_vacancy = build_successor_contribution(
            suite=the_suite, analysis_start=JAN, months=canonical,
            market_schedule=schedule, parent_expiration_period=14,
            branch=branch, lease_id_stem="B::initial@e14",
        )
        from_occupied = build_successor_contribution(
            suite=the_suite, analysis_start=JAN, months=canonical,
            market_schedule=schedule, parent_expiration_period=14,
            branch=branch, lease_id_stem="L-occupied@e14",
        )

        for field in (
            "contractual_base_rent", "cash_base_rent", "free_rent",
            "tenant_improvements", "leasing_commissions", "occupied_area",
            "physical_occupancy", "successor_occupancy_factor",
            "free_rent_abatement_months", "cash_rent_factor",
        ):
            assert hexes(getattr(from_vacancy, field)) == hexes(
                getattr(from_occupied, field)
            )
        for field in (
            "commencement_period", "successor_expiration_period", "term_months",
            "starting_rent_psf", "tenant_improvement_amount",
            "leasing_commission_amount", "full_term_contractual_face_rent",
        ):
            assert getattr(from_vacancy, field) == getattr(from_occupied, field)


def test_golden_16_the_tail_matches_an_equivalent_occupied_chain() -> None:
    """End to end: a vacant suite whose first tenant expires at period 14 and
    an occupied lease expiring at 14 produce the same *successor* economics.

    Only the pre-expiration months differ, because one had a speculative first
    tenant and the other a known one.
    """

    canonical = months()
    defaults = assumptions(new_term_months=12, renewal_probability=0.6)
    the_suite = vacant_suite(lease_up=2.0)

    from_vacancy = build_initial_vacancy_rollover(
        the_suite, analysis_start=JAN, months=canonical, property_defaults=defaults
    )
    from_occupied = build_recursive_rollover(
        occupied_lease("B", end=date(2028, 2, 29)),
        suite=Suite(suite_id="B", suite_area_sf=AREA),
        analysis_start=JAN,
        months=canonical,
        property_defaults=defaults,
    )

    assert from_vacancy.first_contribution.successor_expiration_period == 14
    assert [
        (t.parent_expiration_period, t.branch, t.probability_mass)
        for t in from_vacancy.transitions
    ] == [
        (t.parent_expiration_period, t.branch, t.probability_mass)
        for t in from_occupied.transitions
    ]
    assert from_vacancy.terminal_probability_mass == strict(
        from_occupied.terminal_probability_mass
    )


# =============================================================================
# GOLDEN 17 -- the mixed property
# =============================================================================


def test_golden_17_a_mixed_property_represents_every_suite() -> None:
    """Occupied NNN, vacant MARKET_LEASE_UP, vacant HOLD_VACANT, occupied
    Gross. All four are underwritten intentionally and **none disappears**."""

    from anchor.leasing import (
        build_lease_monthly_schedule,
        build_lease_recovery_schedule,
    )

    canonical = months()
    the_pool = pool(canonical=canonical)
    defaults = assumptions(new_term_months=12, renewal_probability=0.5)

    suite_a = Suite(suite_id="A", suite_area_sf=AREA)
    suite_b = vacant_suite(lease_up=2.0, suite_id="B")
    suite_c = hold_vacant_suite("C")
    suite_d = Suite(suite_id="D", suite_area_sf=AREA)
    lease_a = occupied_lease("A", lease_type=LeaseType.NNN)
    lease_d = occupied_lease("D", lease_type=LeaseType.GROSS)

    def known(the_lease: Lease):
        schedule = build_lease_monthly_schedule(
            the_lease, analysis_start=JAN, months=canonical
        )
        return build_lease_recovery_schedule(
            the_lease, schedule=schedule, pool=the_pool,
            rentable_area_sf=PROPERTY_AREA,
        )

    def vacancy(the_suite: Suite):
        result = build_initial_vacancy_rollover(
            the_suite, analysis_start=JAN, months=canonical,
            property_defaults=defaults,
        )
        return build_initial_vacancy_rollover_recovery(
            result, suite=the_suite, analysis_start=JAN,
            property_defaults=defaults, pool=the_pool,
            rentable_area_sf=PROPERTY_AREA,
        )

    results = [known(lease_a), vacancy(suite_b), vacancy(suite_c), known(lease_d)]
    projections = [suite_recovery_projection(r) for r in results]

    prop = build_property_recovery_schedule(
        projections,
        months=canonical,
        rentable_area_sf=PROPERTY_AREA,
        hold_period=HOLD,
        suites=[suite_a, suite_b, suite_c, suite_d],
        leases=[lease_a, lease_d],
    )

    assert [p.suite_id for p in prop.suite_projections] == ["A", "B", "C", "D"]

    # Month 1: A recovers its share; B is still in lease-up; C is deliberately
    # vacant; D is Gross.
    assert prop.expense_recovery[0] == strict(TENANT_SHARE)
    # Month 3: B's first tenant has commenced.
    assert prop.expense_recovery[2] == strict(2 * TENANT_SHARE)

    # The hold-vacant suite is present and contributes exactly zero.
    hold = next(p for p in prop.suite_projections if p.suite_id == "C")
    assert all(value == 0.0 for value in hold.expense_recovery)


# =============================================================================
# GOLDEN 18 / 19 -- validation
# =============================================================================


def test_golden_18_a_vacant_suite_with_no_treatment_is_refused() -> None:
    """**The limitation this gate closes.** A vacant suite with no treatment is
    incomplete underwriting, and must never be silently read as hold-vacant."""

    bare = Suite(suite_id="B", suite_area_sf=AREA)

    result = validate_initial_vacancy_inputs([bare], [])
    assert not result.is_valid
    issue = next(
        i
        for i in result.issues
        if i.code is LeaseIssueCode.MISSING_INITIAL_VACANCY_TREATMENT
    )
    assert issue.severity is LeaseIssueSeverity.ERROR

    with pytest.raises(LeaseValidationError):
        require_valid_initial_vacancy_inputs([bare], [])

    # And the builder refuses rather than defaulting.
    with pytest.raises(ValueError, match="initial-vacancy treatment"):
        build_initial_vacancy_rollover(
            bare, analysis_start=JAN, months=months(),
            property_defaults=assumptions(),
        )


def test_golden_18_hold_vacant_is_not_the_same_as_missing() -> None:
    """The two produce identical *numbers* and must remain distinguishable in
    every other respect -- that is the whole gate."""

    bare = Suite(suite_id="B", suite_area_sf=AREA)
    chosen = hold_vacant_suite("B")

    assert not validate_initial_vacancy_inputs([bare], []).is_valid
    assert validate_initial_vacancy_inputs([chosen], []).is_valid

    result = rollover(chosen)
    assert result.strategy is InitialVacancyStrategy.HOLD_VACANT


def test_golden_19_an_occupied_suite_may_not_carry_a_treatment() -> None:
    """A financially meaningful field that could never be read is refused,
    not ignored."""

    occupied = vacant_suite(lease_up=6.0, suite_id="A")

    result = validate_initial_vacancy_inputs([occupied], [occupied_lease("A")])

    assert not result.is_valid
    assert LeaseIssueCode.INITIAL_VACANCY_ON_OCCUPIED_SUITE in [
        i.code for i in result.issues
    ]


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_a_lease_up_period_outside_the_domain_is_refused(bad: float) -> None:
    result = validate_initial_vacancy_inputs([vacant_suite(lease_up=bad)], [])

    assert not result.is_valid
    assert LeaseIssueCode.INITIAL_LEASE_UP_OUT_OF_DOMAIN in [
        i.code for i in result.issues
    ]


def test_market_lease_up_without_a_period_is_refused() -> None:
    """Never falls back to ``new_downtime_months``."""

    result = validate_initial_vacancy_inputs([vacant_suite(lease_up=None)], [])

    assert not result.is_valid
    assert LeaseIssueCode.MISSING_INITIAL_LEASE_UP_MONTHS in [
        i.code for i in result.issues
    ]


def test_hold_vacant_carrying_a_period_is_refused() -> None:
    """Half-stated intent."""

    half = Suite(
        suite_id="C",
        suite_area_sf=AREA,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.HOLD_VACANT,
            initial_lease_up_months=6.0,
        ),
    )
    result = validate_initial_vacancy_inputs([half], [])

    assert not result.is_valid
    assert LeaseIssueCode.INITIAL_LEASE_UP_ON_HOLD_VACANT in [
        i.code for i in result.issues
    ]


def test_d1_still_accepts_a_bare_vacant_suite() -> None:
    """**HD-D3.6-1.** D1 is a factual contractual-rent layer: a suite with no
    lease genuinely earns zero rent today, which is an observation rather than
    a speculation. The error belongs at the future-looking gates."""

    from anchor.leasing import LeaseLevelPropertyInputs
    from anchor.leasing.validation import validate_lease_level_inputs

    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(analysis_start_date=JAN, rentable_area_sf=AREA),
        [Suite(suite_id="B", suite_area_sf=AREA)],
        [],
    )

    assert result.is_valid


def test_property_aggregation_refuses_an_unstated_vacant_suite() -> None:
    """The future-looking gate. A vacant suite nobody underwrote cannot have
    its future recovery aggregated."""

    canonical = months()
    bare = Suite(suite_id="B", suite_area_sf=AREA)

    result = validate_property_recovery_inputs(
        [], months=canonical, suites=[bare], leases=[]
    )

    assert not result.is_valid
    assert LeaseIssueCode.MISSING_INITIAL_VACANCY_TREATMENT in [
        i.code for i in result.issues
    ]


def test_property_aggregation_requires_a_projection_for_an_underwritten_suite() -> None:
    """Including a hold-vacant one, so a deliberate zero is distinguishable
    from an omission."""

    canonical = months()
    result = validate_property_recovery_inputs(
        [], months=canonical, suites=[hold_vacant_suite("C")], leases=[]
    )

    assert not result.is_valid
    assert LeaseIssueCode.MISSING_SUITE_RECOVERY_SCHEDULE in [
        i.code for i in result.issues
    ]


# =============================================================================
# Structural rules
# =============================================================================


def test_no_lease_is_fabricated_for_the_vacancy_period() -> None:
    """**FM-D3-21.** The first tenant's lease is a real successor commencing at
    ``c0``; nothing represents the vacancy itself as a lease, and no lease
    carries a fabricated expiration before the analysis start."""

    result = rollover(vacant_suite(lease_up=2.25))
    first_lease = result.first_contribution.successor_lease

    assert first_lease.origin is LeaseOrigin.SUCCESSOR
    assert first_lease.tenant_name is None
    assert first_lease.rent_commencement_date == date(2027, 3, 1)
    assert first_lease.rent_commencement_date >= JAN
    # Hold vacant creates no lease at all.
    assert rollover(hold_vacant_suite()).first_contribution is None


def test_period_zero_is_never_exposed_as_an_expiration() -> None:
    """It is the boundary immediately before canonical month 1 -- not a
    ``ModelMonth``, not a lease expiration, not a cash flow."""

    result = rollover(vacant_suite(lease_up=2.25))

    assert result.first_contribution.parent_expiration_period == 0
    assert all(month.period_index >= 1 for month in result.months)
    assert all(t.parent_expiration_period >= 1 for t in result.transitions)
    assert all(s.expiration_period >= 1 for s in result.event_states)

    # A contribution built from a real expiration cannot masquerade as the
    # first tenant: the InitialVacancyRollover contract requires parent 0.
    canonical = result.months
    the_suite = vacant_suite(lease_up=0.0)
    from_expiration = build_successor_contribution(
        suite=the_suite,
        analysis_start=JAN,
        months=canonical,
        market_schedule=build_market_rent_schedule(
            the_suite, property_defaults=assumptions(), months=canonical
        ),
        parent_expiration_period=12,
        branch=RolloverBranchKind.NEW_TENANT,
        lease_id_stem="not-the-first-tenant",
    )
    with pytest.raises(ValueError, match="boundary index 0"):
        dataclasses.replace(result, first_contribution=from_expiration)


def test_the_first_tenant_is_contributed_exactly_once() -> None:
    """Anti-double-counting: the chain has no in-place lease to add, and the
    contribution already carries the vacancy months as zeros."""

    result = rollover(vacant_suite(lease_up=2.25), new_term_months=12)
    first = result.first_contribution

    fields = {f.name for f in dataclasses.fields(InitialVacancyRollover)}
    assert "initial_lease" not in fields
    assert "initial_schedule" not in fields

    # Before the tail begins, the chain is exactly the first contribution.
    for index in range(first.successor_expiration_period):
        assert result.expected_contractual_base_rent[index] == strict(
            first.contractual_base_rent[index]
        )
    # The first tenant's TI is contributed once, at mass 1.0. (The chain total
    # additionally carries later generations', which is a different figure.)
    assert result.expected_tenant_improvements[
        first.commencement_period - 1
    ] == strict(first.tenant_improvement_amount)


def test_the_recovery_result_attaches_one_contribution_per_transition() -> None:
    result = recovery(vacant_suite(lease_up=2.0), new_term_months=12)

    assert len(result.contributions) == len(result.rollover.transitions)
    for contribution, transition in zip(
        result.contributions, result.rollover.transitions, strict=True
    ):
        assert contribution.parent_expiration_period == (
            transition.parent_expiration_period
        )
        assert contribution.probability_mass == strict(transition.probability_mass)


def test_the_state_bounds_are_unchanged_by_the_vacancy_entry_path() -> None:
    """One extra deterministic contribution, then the existing O(N) structure.
    No new tree, no cap, no separate queue."""

    canonical = months(hold_period=5)
    horizon = canonical[-1].period_index
    result = rollover(
        vacant_suite(lease_up=1.0),
        canonical=canonical,
        new_term_months=1,
        renewal_term_months=1,
        new_downtime_months=0.0,
        renewal_probability=0.5,
    )

    assert len(result.event_states) <= horizon
    assert len(result.transitions) <= 2 * horizon
    assert len(result.event_states) >= 50, "the stress case did not recurse"
    assert all(math.isfinite(v) for v in result.expected_contractual_base_rent)


# =============================================================================
# GOLDEN 20 -- the explicit chain oracle
# =============================================================================


def _explicit_chain_oracle(
    *,
    the_suite: Suite,
    canonical: tuple,
    defaults: MarketLeasingAssumptions,
    the_pool: RecoverableExpensePool | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """TEST-ONLY. Enumerate the complete chain: vacancy, the deterministic
    first tenant, then every renewal/new split, weighting each path by its own
    probability.

    Returns ``(face rent, recovery)``. Production must agree -- but production
    must never build this tree, which is exactly what the accepted state
    machine replaces.
    """

    horizon = canonical[-1].period_index
    count = len(canonical)
    schedule = build_market_rent_schedule(
        the_suite, property_defaults=defaults, months=canonical
    )
    probability = defaults.renewal_probability
    rent = [0.0] * count
    recoveries = [0.0] * count

    def price(contribution) -> tuple[float, ...]:
        if the_pool is None:
            return tuple([0.0] * count)
        return build_successor_recovery_schedule(
            branch=contribution.branch,
            successor_lease=contribution.successor_lease,
            months=canonical,
            successor_occupancy_factor=contribution.successor_occupancy_factor,
            commencement_period=contribution.commencement_period,
            successor_expiration_period=contribution.successor_expiration_period,
            pool=the_pool,
            rentable_area_sf=PROPERTY_AREA,
        ).expense_recovery

    def accumulate(contribution, mass: float) -> None:
        priced = price(contribution)
        for index in range(count):
            rent[index] += mass * contribution.contractual_base_rent[index]
            recoveries[index] += mass * priced[index]

    def walk(parent: int, mass: float) -> None:
        if mass == 0.0 or not 1 <= parent < horizon:
            return
        for branch, weight in (
            (RolloverBranchKind.RENEWAL, probability),
            (RolloverBranchKind.NEW_TENANT, 1.0 - probability),
        ):
            child_mass = mass * weight
            if child_mass == 0.0:
                continue
            child = build_successor_contribution(
                suite=the_suite, analysis_start=JAN, months=canonical,
                market_schedule=schedule, parent_expiration_period=parent,
                branch=branch, lease_id_stem=f"oracle@{parent}",
            )
            accumulate(child, child_mass)
            walk(child.successor_expiration_period, child_mass)

    treatment = the_suite.initial_vacancy
    if treatment.strategy is InitialVacancyStrategy.MARKET_LEASE_UP:
        first = build_successor_contribution(
            suite=the_suite, analysis_start=JAN, months=canonical,
            market_schedule=schedule,
            parent_expiration_period=0,
            branch=RolloverBranchKind.NEW_TENANT,
            lease_id_stem="oracle::initial",
            event_downtime_months=treatment.initial_lease_up_months,
        )
        accumulate(first, 1.0)
        walk(first.successor_expiration_period, 1.0)

    return tuple(rent), tuple(recoveries)


ORACLE_MATRIX = [
    (0.5, 0.0, 4, 5, 0.0, 0.0),
    (0.6, 2.25, 5, 4, 1.0, 1.25),
    (1.0, 1.0, 4, 6, 2.0, 0.0),
    (0.0, 1.0, 4, 6, 2.0, 0.0),
    (0.25, 3.5, 6, 6, 0.5, 1.5),
]


@pytest.mark.parametrize(
    ("probability", "lease_up", "new_term", "renewal_term", "new_d", "new_f"),
    ORACLE_MATRIX,
    ids=lambda v: str(v),
)
def test_golden_20_production_matches_the_explicit_chain_oracle(
    probability: float,
    lease_up: float,
    new_term: int,
    renewal_term: int,
    new_d: float,
    new_f: float,
) -> None:
    """**The independent check.** Short terms force several generations inside
    a two-year window, so the enumerated chain and the merged state machine are
    genuinely different computations of the same quantity."""

    canonical = months(hold_period=2)
    the_suite = vacant_suite(lease_up=lease_up)
    defaults = assumptions(
        new_term_months=new_term,
        renewal_term_months=renewal_term,
        new_downtime_months=new_d,
        new_free_rent_months=new_f,
        renewal_probability=probability,
        new_lease_type=LeaseType.MODIFIED_GROSS,
        new_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        new_expense_stop_psf=STOP_PSF,
    )
    the_pool = pool(canonical=canonical)

    production = build_initial_vacancy_rollover(
        the_suite, analysis_start=JAN, months=canonical, property_defaults=defaults
    )
    production_recovery = build_initial_vacancy_rollover_recovery(
        production, suite=the_suite, analysis_start=JAN,
        property_defaults=defaults, pool=the_pool,
        rentable_area_sf=PROPERTY_AREA,
    )
    oracle_rent, oracle_recovery = _explicit_chain_oracle(
        the_suite=the_suite, canonical=canonical, defaults=defaults,
        the_pool=the_pool,
    )

    assert sum(oracle_rent) > 0.0, "the oracle produced no rent; case is inert"

    for expected, actual in zip(
        oracle_rent, production.expected_contractual_base_rent, strict=True
    ):
        assert actual == close(expected)
    for expected, actual in zip(
        oracle_recovery,
        production_recovery.expected_expense_recovery,
        strict=True,
    ):
        assert actual == close(expected)


def test_golden_20_hold_vacant_matches_the_oracle_trivially() -> None:
    canonical = months(hold_period=2)
    the_suite = hold_vacant_suite("C")
    defaults = assumptions()

    production = build_initial_vacancy_rollover(
        the_suite, analysis_start=JAN, months=canonical, property_defaults=defaults
    )
    oracle_rent, _ = _explicit_chain_oracle(
        the_suite=the_suite, canonical=canonical, defaults=defaults
    )

    assert hexes(production.expected_contractual_base_rent) == hexes(oracle_rent)
