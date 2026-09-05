"""Sprint D Gate D3.1 -- NNN and Gross expense recoveries.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d3-recovery-conventions.md``
Sections 3, 4, 5.0-5.2 and 7, that a known lease's expense-recovery **revenue**
follows ``factor x share x pool``.

The claims that matter most:

- recovery is **independent of rent** -- a $0/SF lease and a $100/SF lease
  recover identically, which is what makes D2's free rent safe to connect at
  D3.4 (failure modes FM-D3-2, FM-D3-3);
- the responsibility factor comes from **D1 contractual activity**, never from
  rent dollars, so a zero-rent active lease still recovers (FM-D3-12);
- `GROSS` is an **explicit zero**, not `NNN` with a zero factor;
- `MODIFIED_GROSS` is **refused**, never silently zeroed (FM-D3-5);
- the pro-rata denominator is rentable area, so a vacant suite leaves its share
  of the pool **unrecovered** -- the disclosed no-gross-up consequence;
- the arithmetic already accepts a **fractional** factor, so D3.3/D3.4 can pass
  a successor's boundary factor without changing the formula.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseRecoverySchedule,
    LeaseType,
    RecoverableExpensePool,
    build_lease_monthly_schedule,
    build_lease_recovery_schedule,
    build_model_months,
    lease_responsibility_factors,
    monthly_expense_recovery,
    tenant_pro_rata_share,
    validate_recovery_inputs,
)
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
    require_valid_recovery_inputs,
)


JAN = date(2027, 1, 1)
JUL = date(2027, 7, 1)
PROPERTY_AREA = 100_000.0
SUITE_AREA = 20_000.0
POOL = 100_000.0


def strict(expected: float) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


def months(*, analysis_start: date = JAN, hold_period: int = 2) -> tuple:
    return build_model_months(analysis_start=analysis_start, hold_period=hold_period)


def lease(
    *,
    area: float = SUITE_AREA,
    lease_type: LeaseType = LeaseType.NNN,
    base_rent_psf: float = 30.0,
    lease_id: str = "L1",
    suite_id: str = "S1",
    start: date = JAN,
    end: date = date(2031, 12, 31),
) -> Lease:
    return Lease(
        lease_id=lease_id,
        suite_id=suite_id,
        tenant_name="Acme Corp",
        leased_area_sf=area,
        rent_commencement_date=start,
        lease_expiration_date=end,
        base_rent_psf=base_rent_psf,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=lease_type,
    )


def pool(
    amount: float = POOL, *, canonical: tuple | None = None
) -> RecoverableExpensePool:
    canonical = canonical if canonical is not None else months()
    return RecoverableExpensePool(
        months=canonical, recoverable_expenses=tuple([amount] * len(canonical))
    )


def recovery(
    the_lease: Lease | None = None,
    *,
    the_pool: RecoverableExpensePool | None = None,
    analysis_start: date = JAN,
    canonical: tuple | None = None,
    rentable_area_sf: float = PROPERTY_AREA,
) -> LeaseRecoverySchedule:
    canonical = canonical if canonical is not None else months(
        analysis_start=analysis_start
    )
    the_lease = the_lease if the_lease is not None else lease()
    schedule = build_lease_monthly_schedule(
        the_lease, analysis_start=analysis_start, months=canonical
    )
    return build_lease_recovery_schedule(
        the_lease,
        schedule=schedule,
        pool=the_pool if the_pool is not None else pool(canonical=canonical),
        rentable_area_sf=rentable_area_sf,
    )


# =============================================================================
# Pro-rata share
# =============================================================================


@pytest.mark.parametrize(
    ("area", "expected"),
    [
        (20_000.0, 0.20),
        (25_000.0, 0.25),
        (50_000.0, 0.50),
        (100_000.0, 1.00),
        (1_000.0, 0.01),
        (4_000.0, 0.04),
    ],
)
def test_the_share_is_leased_area_over_rentable_area(
    area: float, expected: float
) -> None:
    assert tenant_pro_rata_share(
        leased_area_sf=area, rentable_area_sf=PROPERTY_AREA
    ) == strict(expected)


def test_shares_sum_to_exactly_one_across_a_fully_leased_property() -> None:
    """D1's exact area reconciliation means the property can never recover more
    than the pool through the ordinary path."""

    shares = [
        tenant_pro_rata_share(leased_area_sf=area, rentable_area_sf=PROPERTY_AREA)
        for area in (25_000.0, 25_000.0, 50_000.0)
    ]
    assert sum(shares) == strict(1.0)


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_a_non_positive_denominator_is_refused(bad: float) -> None:
    with pytest.raises(ValueError):
        tenant_pro_rata_share(leased_area_sf=SUITE_AREA, rentable_area_sf=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_area_is_refused(bad: float) -> None:
    with pytest.raises(ValueError):
        tenant_pro_rata_share(leased_area_sf=bad, rentable_area_sf=PROPERTY_AREA)
    with pytest.raises(ValueError):
        tenant_pro_rata_share(leased_area_sf=SUITE_AREA, rentable_area_sf=bad)


def test_no_share_override_exists_at_d3_1() -> None:
    """HD-D3-6 is deferred, so the area quotient is the only denominator and
    there is no precedence rule to get wrong."""

    import inspect

    parameters = set(inspect.signature(tenant_pro_rata_share).parameters)
    assert parameters == {"leased_area_sf", "rentable_area_sf"}

    lease_fields = {f.name for f in dataclasses.fields(Lease)}
    for absent in ("pro_rata_share", "recovery_share", "cam_share"):
        assert absent not in lease_fields


# =============================================================================
# GOLDEN 1 / 2 -- basic NNN and Gross
# =============================================================================


def test_golden_1_basic_nnn() -> None:
    """20,000 SF of 100,000 SF, pool $100,000/month, fully responsible."""

    result = recovery()

    assert result.tenant_pro_rata_share == strict(0.20)
    assert result.tenant_recoverable_expense_share[0] == strict(20_000.0)
    assert result.economic_responsibility_factor[0] == 1.0
    assert result.expense_recovery[0] == strict(20_000.0)
    assert all(value == strict(20_000.0) for value in result.expense_recovery)


def test_golden_2_gross_recovers_nothing() -> None:
    """Same inputs, `GROSS`: exactly zero in every month -- while the tenant's
    arithmetic share of the pool is still reported for audit."""

    result = recovery(lease(lease_type=LeaseType.GROSS))

    assert result.tenant_pro_rata_share == strict(0.20)
    assert result.tenant_recoverable_expense_share[0] == strict(20_000.0)
    assert set(result.expense_recovery) == {0.0}


def test_gross_is_an_explicit_branch_not_a_zero_factor() -> None:
    """A Gross lease recovers nothing whatever its share, pool or
    responsibility -- because of what its lease says, not because a number
    happens to be zero."""

    for factor in (0.0, 0.25, 0.75, 1.0):
        assert monthly_expense_recovery(
            lease_type=LeaseType.GROSS,
            tenant_recoverable_expense_share=999_999.0,
            responsibility_factor=factor,
        ) == 0.0


# =============================================================================
# GOLDEN 3 -- responsibility before, during and after the lease
# =============================================================================


def test_golden_3_responsibility_follows_contractual_activity() -> None:
    """A lease active March through August inclusive: `0` before, `1` during,
    `0` after."""

    result = recovery(
        lease(start=date(2027, 3, 1), end=date(2027, 8, 31))
    )
    by_month = {
        month.month_start: index for index, month in enumerate(result.months)
    }

    for month in (date(2027, 1, 1), date(2027, 2, 1)):
        assert result.economic_responsibility_factor[by_month[month]] == 0.0
        assert result.expense_recovery[by_month[month]] == 0.0

    for month_number in range(3, 9):
        index = by_month[date(2027, month_number, 1)]
        assert result.economic_responsibility_factor[index] == 1.0
        assert result.expense_recovery[index] == strict(20_000.0)

    for month in (date(2027, 9, 1), date(2027, 10, 1), date(2028, 6, 1)):
        assert result.economic_responsibility_factor[by_month[month]] == 0.0
        assert result.expense_recovery[by_month[month]] == 0.0


def test_a_known_lease_never_has_a_fractional_responsibility_month() -> None:
    """D1 dates are month-aligned, so an in-place lease is only ever `0` or
    `1`. Fractional values are a successor concept (D3 Section 7.1)."""

    for start, end in (
        (JAN, date(2031, 12, 31)),
        (date(2027, 3, 1), date(2027, 8, 31)),
        (date(2028, 7, 1), date(2028, 7, 31)),
    ):
        result = recovery(lease(start=start, end=end))
        assert set(result.economic_responsibility_factor) <= {0.0, 1.0}


def test_responsibility_is_derived_from_the_d1_schedule() -> None:
    """One notion of "is this lease active": the authoritative D1
    ``occupied_area``, not a second commencement/expiration formula."""

    the_lease = lease(start=date(2027, 3, 1), end=date(2027, 8, 31))
    canonical = months()
    schedule = build_lease_monthly_schedule(
        the_lease, analysis_start=JAN, months=canonical
    )

    factors = lease_responsibility_factors(
        schedule, leased_area_sf=the_lease.leased_area_sf
    )
    expected = tuple(
        1.0 if occupied > 0.0 else 0.0 for occupied in schedule.occupied_area
    )

    assert factors == expected
    assert factors == recovery(the_lease).economic_responsibility_factor


# =============================================================================
# GOLDEN 4 / 5 -- the fractional seam and zero responsibility
# =============================================================================


@pytest.mark.parametrize(
    ("factor", "expected"),
    [
        (0.00, 0.0),
        (0.25, 5_000.0),
        (0.50, 10_000.0),
        (0.75, 15_000.0),
        (1.00, 20_000.0),
    ],
)
def test_golden_4_the_primitive_accepts_a_fractional_factor(
    factor: float, expected: float
) -> None:
    """**The D3.3/D3.4 seam.** The formula already takes a fractional
    responsibility factor, so a successor's downtime boundary factor can be
    passed later without changing the arithmetic. This module imports no
    rollover code to prove it."""

    assert monthly_expense_recovery(
        lease_type=LeaseType.NNN,
        tenant_recoverable_expense_share=20_000.0,
        responsibility_factor=factor,
    ) == strict(expected)


def test_golden_5_zero_responsibility_recovers_nothing() -> None:
    """How D3.3/D3.4 will represent a fully vacant downtime month: no tenant is
    responsible, so the landlord bears the expense."""

    assert monthly_expense_recovery(
        lease_type=LeaseType.NNN,
        tenant_recoverable_expense_share=999_999.0,
        responsibility_factor=0.0,
    ) == 0.0


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_a_factor_outside_zero_to_one_is_refused(bad: float) -> None:
    """It is a fraction of a month, not a multiplier."""

    with pytest.raises(ValueError, match="between 0 and 1"):
        monthly_expense_recovery(
            lease_type=LeaseType.NNN,
            tenant_recoverable_expense_share=1.0,
            responsibility_factor=bad,
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_factor_is_refused(bad: float) -> None:
    with pytest.raises(ValueError):
        monthly_expense_recovery(
            lease_type=LeaseType.NNN,
            tenant_recoverable_expense_share=1.0,
            responsibility_factor=bad,
        )


# =============================================================================
# GOLDEN 6 / 11 -- base-rent independence
# =============================================================================


def test_golden_6_a_zero_rent_lease_still_recovers_in_full() -> None:
    """An active lease paying nothing is still economically responsible. This
    is what catches an accidental dependency on rent cash (FM-D3-12)."""

    result = recovery(lease(base_rent_psf=0.0))

    assert result.economic_responsibility_factor[0] == 1.0
    assert result.expense_recovery[0] == strict(20_000.0)


def test_golden_11_recovery_is_hex_identical_across_base_rents() -> None:
    """**The mandatory proof.** Two otherwise identical NNN leases at $0/SF and
    $100/SF recover identically, bit for bit.

    It also proves in advance that a base-rent concession cannot drive recovery
    arithmetic, which is what makes D2's free rent safe to connect at D3.4."""

    zero = recovery(lease(base_rent_psf=0.0))
    hundred = recovery(lease(base_rent_psf=100.0))

    assert [v.hex() for v in zero.expense_recovery] == [
        v.hex() for v in hundred.expense_recovery
    ]
    assert [v.hex() for v in zero.tenant_recoverable_expense_share] == [
        v.hex() for v in hundred.tenant_recoverable_expense_share
    ]
    assert zero.economic_responsibility_factor == (
        hundred.economic_responsibility_factor
    )


@pytest.mark.parametrize("rent", [0.0, 1.0, 30.0, 100.0, 1_000.0])
def test_recovery_does_not_move_with_rent_at_all(rent: float) -> None:
    baseline = recovery(lease(base_rent_psf=30.0))
    moved = recovery(lease(base_rent_psf=rent))

    assert moved.expense_recovery == baseline.expense_recovery


# =============================================================================
# GOLDEN 7 -- zero pool
# =============================================================================


def test_golden_7_a_zero_pool_recovers_nothing_but_stays_responsible() -> None:
    """A zero pool is not vacancy: the lease is still active and responsible,
    there is simply nothing to reimburse."""

    result = recovery(the_pool=pool(0.0))

    assert set(result.expense_recovery) == {0.0}
    assert result.economic_responsibility_factor[0] == 1.0
    assert result.tenant_recoverable_expense_share[0] == 0.0


# =============================================================================
# GOLDEN 8 / 9 -- calendar and the forward window
# =============================================================================


def test_golden_8_a_non_january_analysis_start() -> None:
    """Responsibility follows the canonical calendar, with no January
    convention."""

    canonical = months(analysis_start=JUL)
    result = recovery(
        lease(start=date(2027, 9, 1), end=date(2028, 2, 29)),
        analysis_start=JUL,
        canonical=canonical,
        the_pool=pool(canonical=canonical),
    )
    by_month = {
        month.month_start: index for index, month in enumerate(result.months)
    }

    assert result.economic_responsibility_factor[by_month[date(2027, 7, 1)]] == 0.0
    assert result.economic_responsibility_factor[by_month[date(2027, 9, 1)]] == 1.0
    assert result.economic_responsibility_factor[by_month[date(2028, 2, 1)]] == 1.0
    assert result.economic_responsibility_factor[by_month[date(2028, 3, 1)]] == 0.0


def test_golden_9_recoveries_continue_through_the_forward_window() -> None:
    """No stop at the sale month, no terminal smoothing."""

    result = recovery()
    forward = [m.period_index for m in result.months if m.is_forward_exit_month]

    assert len(forward) == 12
    for period in forward:
        assert result.economic_responsibility_factor[period - 1] == 1.0
        assert result.expense_recovery[period - 1] == strict(20_000.0)


def test_a_lease_expiring_in_the_final_canonical_month() -> None:
    canonical = months()
    horizon = canonical[-1]
    result = recovery(
        lease(start=JAN, end=date(2029, 12, 31)), canonical=canonical
    )

    assert horizon.period_index == 36
    assert result.economic_responsibility_factor[35] == 1.0
    assert result.expense_recovery[35] == strict(20_000.0)


# =============================================================================
# GOLDEN 10 -- multiple shares, and the disclosed no-gross-up consequence
# =============================================================================


def test_golden_10_multiple_suites_and_no_gross_up() -> None:
    """25% NNN, 25% Gross, 50% vacant against a $100,000 pool.

    The NNN tenant recovers exactly its own 25%. The Gross tenant recovers
    nothing. The vacant suite has no lease and therefore no schedule -- D3.1
    never fabricates one to produce zeros.

    **$75,000 of the pool is unrecovered**, and that is intentional: without
    gross-up (HD-D3-6, deferred) the landlord bears the vacant and Gross shares.
    """

    canonical = months()
    shared_pool = pool(canonical=canonical)

    nnn = recovery(
        lease(area=25_000.0, lease_id="A", suite_id="SA"),
        canonical=canonical,
        the_pool=shared_pool,
    )
    gross = recovery(
        lease(
            area=25_000.0,
            lease_type=LeaseType.GROSS,
            lease_id="B",
            suite_id="SB",
        ),
        canonical=canonical,
        the_pool=shared_pool,
    )

    assert nnn.tenant_pro_rata_share == strict(0.25)
    assert nnn.expense_recovery[0] == strict(25_000.0)
    assert gross.tenant_pro_rata_share == strict(0.25)
    assert gross.expense_recovery[0] == 0.0

    recovered = nnn.expense_recovery[0] + gross.expense_recovery[0]
    assert recovered == strict(25_000.0)
    assert POOL - recovered == strict(75_000.0)


def test_a_vacant_suite_produces_no_schedule_at_all() -> None:
    """D1 represents vacancy as a `Suite` with no lease. D3.1's API is per
    lease, so absence of a lease naturally means absence of a schedule; nothing
    fabricates a Gross lease to emit zeros."""

    import inspect

    parameters = list(inspect.signature(build_lease_recovery_schedule).parameters)
    assert parameters[0] == "lease"
    assert "suite" not in parameters
    assert "suites" not in parameters


# =============================================================================
# GOLDEN 12 -- Modified Gross is refused
# =============================================================================


def test_golden_12_modified_gross_is_refused_by_the_arithmetic() -> None:
    """Never treated as Gross, never as NNN, never a silent zero -- a silent
    zero would under-recover every Modified Gross lease while looking like a
    computed answer."""

    with pytest.raises(ValueError, match="MODIFIED_GROSS"):
        monthly_expense_recovery(
            lease_type=LeaseType.MODIFIED_GROSS,
            tenant_recoverable_expense_share=20_000.0,
            responsibility_factor=1.0,
        )


def test_golden_12_modified_gross_is_refused_by_the_builder() -> None:
    with pytest.raises(ValueError, match="MODIFIED_GROSS"):
        recovery(lease(lease_type=LeaseType.MODIFIED_GROSS))


def test_golden_12_modified_gross_is_refused_by_validation() -> None:
    """Using the documented code, whose precondition genuinely holds at D3.1:
    no basis field exists, so the lease carries no explicit basis."""

    result = validate_recovery_inputs([lease(lease_type=LeaseType.MODIFIED_GROSS)], pool())

    assert not result.is_valid
    codes = [issue.code for issue in result.issues]
    assert LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS in codes

    with pytest.raises(LeaseValidationError):
        require_valid_recovery_inputs(
            [lease(lease_type=LeaseType.MODIFIED_GROSS)], pool()
        )


def test_no_expense_stop_or_recovery_basis_exists_at_d3_1() -> None:
    """D3.2 owns them. Declaring either now would put vocabulary into the
    package with no mechanism behind it."""

    lease_fields = {f.name for f in dataclasses.fields(Lease)}
    for absent in ("recovery_basis", "expense_stop_psf", "base_year"):
        assert absent not in lease_fields

    import anchor.leasing as leasing

    for absent in ("RecoveryBasis", "expense_stop_psf"):
        assert not hasattr(leasing, absent)


def test_modified_gross_remains_a_valid_lease_type_for_d1_and_d2() -> None:
    """The refusal is scoped to *recovery*. `MODIFIED_GROSS` has been a valid
    lease type since D1.0 and D2 carries it through rollover unchanged, so it
    must not become invalid input merely because the gate that prices it has
    not landed."""

    from anchor.leasing import LeaseLevelPropertyInputs, Suite
    from anchor.leasing.validation import validate_lease_level_inputs

    result = validate_lease_level_inputs(
        LeaseLevelPropertyInputs(
            analysis_start_date=JAN, rentable_area_sf=SUITE_AREA
        ),
        [Suite(suite_id="S1", suite_area_sf=SUITE_AREA)],
        [lease(area=SUITE_AREA, lease_type=LeaseType.MODIFIED_GROSS)],
    )

    assert result.is_valid


# =============================================================================
# The pool contract
# =============================================================================


def test_the_pool_requires_one_figure_per_month() -> None:
    canonical = months()

    with pytest.raises(ValueError, match="one recoverable_expenses figure"):
        RecoverableExpensePool(
            months=canonical, recoverable_expenses=(1.0, 2.0)
        )


def test_a_pool_built_on_another_timeline_is_refused() -> None:
    """Month **identity** is checked, not length. A pool from a different
    projection would zip cleanly and produce a plausible, wrong answer."""

    canonical = months()
    other = months(analysis_start=JUL)
    assert len(canonical) == len(other)

    the_lease = lease()
    schedule = build_lease_monthly_schedule(
        the_lease, analysis_start=JAN, months=canonical
    )

    with pytest.raises(ValueError, match="different month sequences"):
        build_lease_recovery_schedule(
            the_lease,
            schedule=schedule,
            pool=pool(canonical=other),
            rentable_area_sf=PROPERTY_AREA,
        )


def test_a_schedule_for_another_lease_is_refused() -> None:
    canonical = months()
    schedule = build_lease_monthly_schedule(
        lease(lease_id="OTHER"), analysis_start=JAN, months=canonical
    )

    with pytest.raises(ValueError, match="belongs to lease"):
        build_lease_recovery_schedule(
            lease(lease_id="L1"),
            schedule=schedule,
            pool=pool(canonical=canonical),
            rentable_area_sf=PROPERTY_AREA,
        )


def test_the_pool_stores_no_annual_ratio_or_category_data() -> None:
    """The D3/D4 seam: D3 receives final dollars and cannot infer, or
    re-police, what went into them."""

    fields = {f.name for f in dataclasses.fields(RecoverableExpensePool)}
    assert fields == {"months", "recoverable_expenses"}

    for absent in (
        "recoverable_expense_ratio",
        "expense_growth",
        "management_fee",
        "property_taxes",
        "by_year",
        "categories",
    ):
        assert absent not in fields


def test_a_pool_that_varies_month_to_month() -> None:
    canonical = months()
    varying = RecoverableExpensePool(
        months=canonical,
        recoverable_expenses=tuple(
            10_000.0 * (index + 1) for index in range(len(canonical))
        ),
    )
    result = recovery(canonical=canonical, the_pool=varying)

    for index in range(len(canonical)):
        assert result.expense_recovery[index] == strict(
            0.20 * 10_000.0 * (index + 1)
        )


# =============================================================================
# Validation
# =============================================================================


def codes(result: object) -> list[LeaseIssueCode]:
    return [issue.code for issue in result.issues]  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", [-0.01, -100_000.0])
def test_a_negative_pool_figure_is_an_error(bad: float) -> None:
    """A negative pool would be an expense credit, for which D3 has no
    convention."""

    canonical = months()
    bad_pool = RecoverableExpensePool(
        months=canonical,
        recoverable_expenses=(bad,) + tuple([POOL] * (len(canonical) - 1)),
    )
    result = validate_recovery_inputs([lease()], bad_pool)

    assert not result.is_valid
    assert LeaseIssueCode.RECOVERABLE_EXPENSES_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_pool_figure_is_an_error(bad: float) -> None:
    canonical = months()
    bad_pool = RecoverableExpensePool(
        months=canonical,
        recoverable_expenses=(bad,) + tuple([POOL] * (len(canonical) - 1)),
    )
    result = validate_recovery_inputs([lease()], bad_pool)

    assert LeaseIssueCode.NON_FINITE_VALUE in codes(result)


@pytest.mark.parametrize("value", [0.0, 1.0, 100_000.0, 1e9])
def test_a_non_negative_finite_pool_is_valid(value: float) -> None:
    assert validate_recovery_inputs([lease()], pool(value)).is_valid


def test_a_misaligned_pool_is_an_error_when_months_are_supplied() -> None:
    canonical = months()
    result = validate_recovery_inputs(
        [lease()], pool(canonical=months(analysis_start=JUL)), months=canonical
    )

    assert not result.is_valid
    assert LeaseIssueCode.RECOVERY_POOL_NOT_ALIGNED in codes(result)


def test_an_aligned_pool_raises_no_alignment_issue() -> None:
    canonical = months()
    result = validate_recovery_inputs(
        [lease()], pool(canonical=canonical), months=canonical
    )

    assert result.is_valid


def test_recovery_issues_are_errors_never_warnings() -> None:
    canonical = months()
    bad_pool = RecoverableExpensePool(
        months=canonical,
        recoverable_expenses=(-1.0,) + tuple([POOL] * (len(canonical) - 1)),
    )
    result = validate_recovery_inputs(
        [lease(lease_type=LeaseType.MODIFIED_GROSS)], bad_pool
    )

    assert result.issues
    for issue in result.issues:
        assert issue.severity is LeaseIssueSeverity.ERROR


def test_nnn_and_gross_need_no_extra_recovery_input() -> None:
    result = validate_recovery_inputs(
        [lease(lease_type=LeaseType.NNN), lease(lease_type=LeaseType.GROSS)],
        pool(),
    )

    assert result.is_valid


def test_validation_is_ordered_pool_then_alignment_then_leases() -> None:
    canonical = months()
    bad_pool = RecoverableExpensePool(
        months=months(analysis_start=JUL),
        recoverable_expenses=(-1.0,) + tuple([POOL] * (len(canonical) - 1)),
    )
    result = validate_recovery_inputs(
        [lease(lease_type=LeaseType.MODIFIED_GROSS)], bad_pool, months=canonical
    )

    assert codes(result) == [
        LeaseIssueCode.RECOVERABLE_EXPENSES_OUT_OF_DOMAIN,
        LeaseIssueCode.RECOVERY_POOL_NOT_ALIGNED,
        LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS,
    ]


# =============================================================================
# Adversarial, determinism and immutability
# =============================================================================


@pytest.mark.parametrize(
    ("area", "pool_amount", "expected"),
    [
        (1_000.0, 100_000.0, 1_000.0),
        (100_000.0, 100_000.0, 100_000.0),
        (20_000.0, 1e-6, 2e-7),
        (20_000.0, 1e9, 2e8),
    ],
)
def test_extreme_but_finite_shares_and_pools(
    area: float, pool_amount: float, expected: float
) -> None:
    result = recovery(lease(area=area), the_pool=pool(pool_amount))

    assert result.expense_recovery[0] == strict(expected)


def test_a_lease_beginning_in_month_one() -> None:
    result = recovery(lease(start=JAN))

    assert result.economic_responsibility_factor[0] == 1.0
    assert result.expense_recovery[0] == strict(20_000.0)


def test_a_lease_starting_after_the_analysis_start() -> None:
    result = recovery(lease(start=date(2028, 1, 1)))

    assert result.economic_responsibility_factor[0] == 0.0
    assert result.economic_responsibility_factor[11] == 0.0
    assert result.economic_responsibility_factor[12] == 1.0


def test_repeated_builds_are_value_equal() -> None:
    first = recovery()
    second = recovery()

    assert first == second
    for left, right in zip(first.expense_recovery, second.expense_recovery):
        assert left.hex() == right.hex()


def test_the_contracts_are_frozen() -> None:
    result = recovery()
    the_pool = pool()

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.tenant_pro_rata_share = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        the_pool.recoverable_expenses = ()  # type: ignore[misc]


def test_the_schedule_rejects_a_mismatched_series_length() -> None:
    result = recovery()

    with pytest.raises(ValueError):
        dataclasses.replace(result, expense_recovery=(0.0,))


def test_inputs_are_never_mutated() -> None:
    the_lease = lease()
    the_pool = pool()
    before_lease = dataclasses.replace(the_lease)
    before_pool = dataclasses.replace(the_pool)

    recovery(the_lease, the_pool=the_pool)

    assert the_lease == before_lease
    assert the_pool == before_pool


def test_the_schedule_carries_no_d3_2_or_later_field() -> None:
    fields = {f.name for f in dataclasses.fields(LeaseRecoverySchedule)}

    for absent in (
        "expense_stop_psf",
        "recovery_basis",
        "expected_expense_recovery",
        "property_expense_recovery",
        "annual_expense_recovery",
    ):
        assert absent not in fields
