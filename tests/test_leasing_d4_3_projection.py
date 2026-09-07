"""Sprint D Gate D4.3 -- the canonical monthly property projection.

Governed by
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 5.3-5.6, 7, 8, 13, 14, 15 and 29.3.

D4.3 composes three completed schedules and adds six new monthly series. The
claims that fail silently if wrong:

- **EGI reads ``cash_base_rent``**, never ``contractual - free_rent``, which
  exceeds it in any fractional-downtime month by the part of the month nobody
  occupied (HD-D4-5);
- **credit loss applies to cash rent plus recovery only** -- not to contractual
  rent, not to other income, and never to physical vacancy, which is already
  inside the leasing dollars;
- **the management fee is a percentage of EGI with recoveries included**, after
  credit loss (HD-D4-2). Netting recovery against expenses would leave the same
  pre-fee NOI and a smaller fee, which is why gross presentation is
  load-bearing rather than cosmetic;
- **TI and LC never touch NOI**, in any month including the forward window;
- **NOI is never floored** -- a vacant building still pays its taxes.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.contracts import DetailedOperatingInputs
from anchor.engine.contracts import NonFiniteResultError
from anchor.engine.operating_projection import build_detailed_operating_projection
from anchor.leasing import (
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseIssueCode,
    LeaseLevelOperatingInputs,
    LeaseType,
    LeasingCommissionMethod,
    LeaseValidationError,
    MarketLeasingAssumptions,
    ModelMonth,
    MonthlyPropertyExpenseSchedule,
    MonthlyPropertyProjection,
    PropertyOperatingSchedule,
    PropertyRecoverySchedule,
    Suite,
    SuiteOperatingProjection,
    SuiteRecoveryProjection,
    annual_other_income,
    build_initial_vacancy_rollover,
    build_model_months,
    build_monthly_property_projection,
    build_property_expense_schedule,
    build_property_operating_schedule,
    build_recoverable_expense_pool,
    suite_operating_projection,
    validate_property_projection_inputs,
)


# =============================================================================
# Fixtures -- hand-specified schedules, so every golden is hand-checkable
# =============================================================================


JAN = date(2027, 1, 1)
JULY = date(2027, 7, 1)
HOLD = 1
AREA = 100_000.0

MONTHS = build_model_months(analysis_start=JAN, hold_period=HOLD)


def hexes(values: tuple[float, ...]) -> list[str]:
    return [value.hex() for value in values]


def flat(value: float, *, timeline: tuple[ModelMonth, ...] = MONTHS) -> tuple[float, ...]:
    return tuple(float(value) for _ in timeline)


def operating_schedule(
    *,
    cash: float,
    contractual: float | None = None,
    free_rent: float = 0.0,
    ti: float = 0.0,
    lc: float = 0.0,
    occupied: float | None = None,
    area: float = AREA,
    suite_ids: tuple[str, ...] = ("A",),
    timeline: tuple[ModelMonth, ...] = MONTHS,
) -> PropertyOperatingSchedule:
    contractual = cash if contractual is None else contractual
    occupied = area if occupied is None else occupied
    per_suite_area = area / len(suite_ids)
    projections = tuple(
        SuiteOperatingProjection(
            suite_id=suite_id,
            suite_area_sf=per_suite_area,
            months=timeline,
            contractual_base_rent=flat(0.0, timeline=timeline),
            cash_base_rent=flat(0.0, timeline=timeline),
            free_rent=flat(0.0, timeline=timeline),
            tenant_improvements=flat(0.0, timeline=timeline),
            leasing_commissions=flat(0.0, timeline=timeline),
            occupied_area_sf=flat(0.0, timeline=timeline),
        )
        for suite_id in suite_ids
    )
    return PropertyOperatingSchedule(
        months=timeline,
        rentable_area_sf=area,
        suite_projections=projections,
        contractual_base_rent=flat(contractual, timeline=timeline),
        cash_base_rent=flat(cash, timeline=timeline),
        free_rent=flat(free_rent, timeline=timeline),
        tenant_improvements=flat(ti, timeline=timeline),
        leasing_commissions=flat(lc, timeline=timeline),
        occupied_area_sf=flat(occupied, timeline=timeline),
        vacant_area_sf=flat(area - occupied, timeline=timeline),
        physical_occupancy=flat(occupied / area, timeline=timeline),
    )


def recovery_schedule(
    *,
    recovery: float,
    area: float = AREA,
    suite_ids: tuple[str, ...] = ("A",),
    timeline: tuple[ModelMonth, ...] = MONTHS,
    hold_period: int = HOLD,
    monthly: tuple[float, ...] | None = None,
) -> PropertyRecoverySchedule:
    series = flat(recovery, timeline=timeline) if monthly is None else monthly
    projections = tuple(
        SuiteRecoveryProjection(
            suite_id=suite_id,
            months=timeline,
            expense_recovery=flat(0.0, timeline=timeline),
        )
        for suite_id in suite_ids
    )
    return PropertyRecoverySchedule(
        months=timeline,
        rentable_area_sf=area,
        hold_period=hold_period,
        suite_projections=projections,
        expense_recovery=series,
        annual_expense_recovery=tuple(
            sum(series[year * 12 : (year + 1) * 12]) for year in range(hold_period)
        ),
        forward_exit_window_expense_recovery=sum(series[hold_period * 12 :]),
    )


def expense_schedule(
    *,
    fixed: float,
    timeline: tuple[ModelMonth, ...] = MONTHS,
    split: bool = False,
) -> MonthlyPropertyExpenseSchedule:
    """``split`` spreads the total across all five lines, to prove the total is
    what NOI consumes and the five are audit lines."""

    if split:
        parts = (fixed * 0.5, fixed * 0.2, fixed * 0.15, fixed * 0.1, fixed * 0.05)
    else:
        parts = (fixed, 0.0, 0.0, 0.0, 0.0)
    return MonthlyPropertyExpenseSchedule(
        months=timeline,
        property_taxes=flat(parts[0], timeline=timeline),
        insurance=flat(parts[1], timeline=timeline),
        utilities=flat(parts[2], timeline=timeline),
        repairs_maintenance=flat(parts[3], timeline=timeline),
        other_operating_expenses=flat(parts[4], timeline=timeline),
        fixed_operating_expenses=flat(fixed, timeline=timeline),
    )


def inputs(**overrides: object) -> LeaseLevelOperatingInputs:
    base: dict[str, object] = {
        "other_income": 0.0,
        "other_income_growth": 0.0,
        "credit_loss_pct": 0.0,
        "property_taxes": 0.0,
        "insurance": 0.0,
        "utilities": 0.0,
        "repairs_maintenance": 0.0,
        "other_operating_expenses": 0.0,
        "management_fee_pct": 0.0,
        "expense_growth": 0.0,
        "recoverable_expense_ratio": 1.0,
    }
    base.update(overrides)
    return LeaseLevelOperatingInputs(**base)  # type: ignore[arg-type]


def project(
    *,
    cash: float = 0.0,
    contractual: float | None = None,
    free_rent: float = 0.0,
    recovery: float = 0.0,
    fixed: float = 0.0,
    ti: float = 0.0,
    lc: float = 0.0,
    occupied: float | None = None,
    split_expenses: bool = False,
    **input_overrides: object,
) -> MonthlyPropertyProjection:
    return build_monthly_property_projection(
        operating_schedule(
            cash=cash,
            contractual=contractual,
            free_rent=free_rent,
            ti=ti,
            lc=lc,
            occupied=occupied,
        ),
        recovery_schedule(recovery=recovery),
        expense_schedule(fixed=fixed, split=split_expenses),
        operating_inputs=inputs(**input_overrides),
    )


# =============================================================================
# G1 / G2 -- cash base rent is the revenue authority
# =============================================================================


def test_g1_egi_reads_cash_base_rent_under_fractional_downtime() -> None:
    """The D4.2 fractional-downtime case, carried through to NOI. Contractual
    ``100,000``, no free rent, cash ``75,000`` -- EGI and NOI are ``75,000``,
    not ``100,000`` (HD-D4-5)."""

    projection = project(cash=75_000.0, contractual=100_000.0, free_rent=0.0)

    assert projection.contractual_base_rent[0] == 100_000.0
    assert projection.free_rent[0] == 0.0
    assert projection.cash_base_rent[0] == 75_000.0
    assert projection.effective_gross_income[0] == pytest.approx(75_000.0, abs=1e-9)
    assert projection.noi[0] == pytest.approx(75_000.0, abs=1e-9)


def test_g1_the_rejected_contractual_minus_free_value_does_not_appear() -> None:
    projection = project(cash=75_000.0, contractual=100_000.0, free_rent=0.0)

    rejected = projection.contractual_base_rent[0] - projection.free_rent[0]
    assert rejected == 100_000.0
    assert projection.effective_gross_income[0] != pytest.approx(rejected, abs=1e-3)


def test_g2_contractual_rent_is_an_audit_line_that_feeds_nothing() -> None:
    """Perturbing contractual rent alone -- the leasing engine cannot produce
    this, but the composition must be provably indifferent to it."""

    base = project(cash=75_000.0, contractual=100_000.0, fixed=10_000.0,
                   management_fee_pct=0.03, credit_loss_pct=0.05)
    bumped = project(cash=75_000.0, contractual=999_999.0, fixed=10_000.0,
                     management_fee_pct=0.03, credit_loss_pct=0.05)

    for name in (
        "effective_gross_income",
        "credit_loss",
        "management_fee",
        "total_operating_expenses",
        "noi",
    ):
        assert hexes(getattr(base, name)) == hexes(getattr(bumped, name)), name
    assert base.contractual_base_rent != bumped.contractual_base_rent


def test_g2_free_rent_is_an_audit_line_that_feeds_nothing() -> None:
    base = project(cash=75_000.0, contractual=100_000.0, free_rent=25_000.0,
                   fixed=10_000.0, management_fee_pct=0.03, credit_loss_pct=0.05)
    bumped = project(cash=75_000.0, contractual=100_000.0, free_rent=90_000.0,
                     fixed=10_000.0, management_fee_pct=0.03, credit_loss_pct=0.05)

    for name in (
        "effective_gross_income",
        "credit_loss",
        "management_fee",
        "noi",
    ):
        assert hexes(getattr(base, name)) == hexes(getattr(bumped, name)), name


def test_g2_free_rent_is_never_subtracted_a_second_time() -> None:
    """Its effect is already inside cash rent."""

    projection = project(cash=75_000.0, contractual=100_000.0, free_rent=25_000.0)

    assert projection.effective_gross_income[0] == pytest.approx(75_000.0, abs=1e-9)
    assert projection.effective_gross_income[0] != pytest.approx(50_000.0, abs=1e-3)


# =============================================================================
# G3 -- other income: units, growth, anniversary
# =============================================================================


def test_g3_year_one_other_income_is_the_annual_amount_over_twelve() -> None:
    projection = project(other_income=120_000.0)

    assert projection.other_income[0] == pytest.approx(10_000.0, abs=1e-9)


def test_g3_other_income_steps_on_the_july_anniversary_not_january() -> None:
    """Year-1 ``120,000`` at 10% growth, July analysis start: months 1-12 are
    ``10,000``; month 13 is ``11,000``."""

    july_months = build_model_months(analysis_start=JULY, hold_period=2)
    projection = build_monthly_property_projection(
        operating_schedule(cash=0.0, timeline=july_months),
        recovery_schedule(recovery=0.0, timeline=july_months, hold_period=2),
        expense_schedule(fixed=0.0, timeline=july_months),
        operating_inputs=inputs(other_income=120_000.0, other_income_growth=0.10),
    )

    assert projection.months[12].month_start == date(2028, 7, 1)
    assert projection.other_income[:12] == tuple(10_000.0 for _ in range(12))
    assert projection.other_income[12] == pytest.approx(11_000.0, abs=1e-9)


def test_g3_january_is_not_a_step_month_for_a_july_start() -> None:
    july_months = build_model_months(analysis_start=JULY, hold_period=2)
    projection = build_monthly_property_projection(
        operating_schedule(cash=0.0, timeline=july_months),
        recovery_schedule(recovery=0.0, timeline=july_months, hold_period=2),
        expense_schedule(fixed=0.0, timeline=july_months),
        operating_inputs=inputs(other_income=120_000.0, other_income_growth=0.10),
    )

    januaries = [
        position
        for position, month in enumerate(projection.months)
        if month.month_start.month == 1
    ]
    assert januaries
    for position in januaries:
        assert projection.other_income[position] == projection.other_income[
            position - 1
        ]


def test_g3_the_forward_window_uses_model_year_h_plus_one() -> None:
    july_months = build_model_months(analysis_start=JULY, hold_period=2)
    projection = build_monthly_property_projection(
        operating_schedule(cash=0.0, timeline=july_months),
        recovery_schedule(recovery=0.0, timeline=july_months, hold_period=2),
        expense_schedule(fixed=0.0, timeline=july_months),
        operating_inputs=inputs(other_income=120_000.0, other_income_growth=0.10),
    )

    forward = projection.other_income[24:]
    assert len(forward) == 12
    assert forward[0] == pytest.approx(120_000.0 * 1.10**2 / 12, abs=1e-9)
    assert len(set(forward)) == 1


def test_g3_other_income_does_not_compound_monthly() -> None:
    july_months = build_model_months(analysis_start=JULY, hold_period=2)
    projection = build_monthly_property_projection(
        operating_schedule(cash=0.0, timeline=july_months),
        recovery_schedule(recovery=0.0, timeline=july_months, hold_period=2),
        expense_schedule(fixed=0.0, timeline=july_months),
        operating_inputs=inputs(other_income=120_000.0, other_income_growth=0.10),
    )

    for year_start in range(0, len(projection.months), 12):
        year = projection.other_income[year_start : year_start + 12]
        assert len(set(year)) == 1


# =============================================================================
# G4 / G6 -- other income is independent of vacancy and of credit loss
# =============================================================================


def test_g4_other_income_survives_total_physical_vacancy() -> None:
    projection = project(cash=0.0, recovery=0.0, occupied=0.0, other_income=120_000.0)

    assert projection.physical_occupancy[0] == 0.0
    assert projection.other_income[0] == pytest.approx(10_000.0, abs=1e-9)
    assert projection.effective_gross_income[0] == pytest.approx(10_000.0, abs=1e-9)


def test_g4_other_income_is_not_scaled_by_occupancy() -> None:
    full = project(cash=0.0, occupied=AREA, other_income=120_000.0)
    empty = project(cash=0.0, occupied=0.0, other_income=120_000.0)

    assert hexes(full.other_income) == hexes(empty.other_income)


def test_g6_other_income_is_excluded_from_the_credit_loss_base() -> None:
    """Parking receipts are not tenant lease receivables (D0 Section 14)."""

    without = project(cash=100_000.0, recovery=20_000.0, credit_loss_pct=0.05)
    with_income = project(
        cash=100_000.0, recovery=20_000.0, credit_loss_pct=0.05,
        other_income=60_000.0,
    )

    assert hexes(without.credit_loss) == hexes(with_income.credit_loss)
    assert with_income.credit_loss[0] == pytest.approx(6_000.0, abs=1e-9)


# =============================================================================
# G5 -- the credit-loss base
# =============================================================================


def test_g5_credit_loss_is_pct_times_cash_rent_plus_recovery() -> None:
    """cash ``100,000`` + recovery ``20,000`` = base ``120,000``; at 5% that is
    ``6,000``, and EGI with ``5,000`` of other income is ``119,000``."""

    projection = project(
        cash=100_000.0, recovery=20_000.0, other_income=60_000.0,
        credit_loss_pct=0.05, management_fee_pct=0.03,
    )

    assert projection.credit_loss[0] == pytest.approx(6_000.0, abs=1e-9)
    assert projection.effective_gross_income[0] == pytest.approx(119_000.0, abs=1e-9)
    assert projection.management_fee[0] == pytest.approx(3_570.0, abs=1e-9)


def test_g5_credit_loss_uses_cash_rent_not_contractual_rent() -> None:
    """contractual ``100,000``, free ``25,000``, cash ``75,000``, recovery
    ``20,000`` -> base ``95,000``, credit loss ``9,500``, EGI ``85,500``."""

    projection = project(
        cash=75_000.0, contractual=100_000.0, free_rent=25_000.0,
        recovery=20_000.0, credit_loss_pct=0.10,
    )

    assert projection.credit_loss[0] == pytest.approx(9_500.0, abs=1e-9)
    assert projection.effective_gross_income[0] == pytest.approx(85_500.0, abs=1e-9)
    # The contractual base would have been 120,000 -> 12,000.
    assert projection.credit_loss[0] != pytest.approx(12_000.0, abs=1e-3)


def test_g5_credit_loss_includes_recovery_in_its_base() -> None:
    without = project(cash=100_000.0, recovery=0.0, credit_loss_pct=0.10)
    with_recovery = project(cash=100_000.0, recovery=20_000.0, credit_loss_pct=0.10)

    assert without.credit_loss[0] == pytest.approx(10_000.0, abs=1e-9)
    assert with_recovery.credit_loss[0] == pytest.approx(12_000.0, abs=1e-9)


def test_g5_a_zero_credit_loss_pct_is_exactly_zero() -> None:
    projection = project(cash=100_000.0, recovery=20_000.0)

    assert projection.credit_loss == flat(0.0)
    assert projection.effective_gross_income[0] == pytest.approx(120_000.0, abs=1e-9)


def test_g5_ti_and_lc_are_outside_the_credit_loss_base() -> None:
    without = project(cash=100_000.0, credit_loss_pct=0.10)
    with_costs = project(cash=100_000.0, credit_loss_pct=0.10, ti=5_000.0, lc=2_000.0)

    assert hexes(without.credit_loss) == hexes(with_costs.credit_loss)


# =============================================================================
# G7 -- the management fee
# =============================================================================


def test_g7_the_fee_is_pct_times_egi_including_recoveries() -> None:
    """cash ``100,000`` + recovery ``20,000`` + other income ``5,000`` =
    ``125,000``; at 3% the fee is ``3,750``."""

    projection = project(
        cash=100_000.0, recovery=20_000.0, other_income=60_000.0,
        management_fee_pct=0.03,
    )

    assert projection.effective_gross_income[0] == pytest.approx(125_000.0, abs=1e-9)
    assert projection.management_fee[0] == pytest.approx(3_750.0, abs=1e-9)


@pytest.mark.parametrize("rejected", [3_000.0, 3_150.0, 3_600.0])
def test_g7_the_rejected_fee_bases_do_not_appear(rejected: float) -> None:
    """``3,000`` is a fee on cash rent alone; ``3,150`` excludes recoveries;
    ``3,600`` excludes other income."""

    projection = project(
        cash=100_000.0, recovery=20_000.0, other_income=60_000.0,
        management_fee_pct=0.03,
    )

    assert projection.management_fee[0] != pytest.approx(rejected, abs=1e-3)


def test_g7_the_fee_is_calculated_after_credit_loss() -> None:
    """``3%`` of ``119,000``, not of ``125,000``."""

    projection = project(
        cash=100_000.0, recovery=20_000.0, other_income=60_000.0,
        credit_loss_pct=0.05, management_fee_pct=0.03,
    )

    assert projection.management_fee[0] == pytest.approx(3_570.0, abs=1e-9)
    assert projection.management_fee[0] != pytest.approx(3_750.0, abs=1e-3)


def test_g7_a_zero_fee_pct_produces_exactly_zero() -> None:
    projection = project(cash=100_000.0, recovery=20_000.0, fixed=50_000.0)

    assert projection.management_fee == flat(0.0)
    assert projection.total_operating_expenses[0] == pytest.approx(50_000.0, abs=1e-9)


# =============================================================================
# G8 / G9 / G13 / G14 -- reconciliation and gross presentation
# =============================================================================


def test_g8_the_hundred_percent_nnn_reconciliation() -> None:
    """cash ``100,000``; recovery ``150,000``; fixed opex ``150,000``; fee 3%.
    EGI ``250,000``, fee ``7,500``, total opex ``157,500``, NOI ``92,500``."""

    projection = project(
        cash=100_000.0, recovery=150_000.0, fixed=150_000.0, management_fee_pct=0.03
    )

    assert projection.effective_gross_income[0] == pytest.approx(250_000.0, abs=1e-9)
    assert projection.management_fee[0] == pytest.approx(7_500.0, abs=1e-9)
    assert projection.total_operating_expenses[0] == pytest.approx(157_500.0, abs=1e-9)
    assert projection.noi[0] == pytest.approx(92_500.0, abs=1e-9)


def test_g8_nnn_noi_equals_cash_rent_less_the_fee_when_expenses_fully_recover() -> None:
    """The economic reconciliation: eligible expenses and recoveries offset, so
    NOI is cash rent minus the fee -- ``100,000 - 7,500``."""

    projection = project(
        cash=100_000.0, recovery=150_000.0, fixed=150_000.0, management_fee_pct=0.03
    )

    assert projection.noi[0] == pytest.approx(
        100_000.0 - projection.management_fee[0], abs=1e-9
    )


def test_g9_the_hundred_percent_gross_reconciliation() -> None:
    """No recovery: EGI ``100,000``, fee ``3,000``, total opex ``153,000``,
    NOI ``-53,000``. The landlord bears the whole expense."""

    projection = project(
        cash=100_000.0, recovery=0.0, fixed=150_000.0, management_fee_pct=0.03
    )

    assert projection.effective_gross_income[0] == pytest.approx(100_000.0, abs=1e-9)
    assert projection.management_fee[0] == pytest.approx(3_000.0, abs=1e-9)
    assert projection.total_operating_expenses[0] == pytest.approx(153_000.0, abs=1e-9)
    assert projection.noi[0] == pytest.approx(-53_000.0, abs=1e-9)


def test_g13_recovery_is_revenue_and_expenses_stay_gross() -> None:
    """Both lines are reported at full gross; no field is a netted difference."""

    projection = project(
        cash=100_000.0, recovery=150_000.0, fixed=150_000.0, management_fee_pct=0.03
    )

    assert projection.expense_recovery[0] == 150_000.0
    assert projection.fixed_operating_expenses[0] == 150_000.0
    netted = projection.fixed_operating_expenses[0] - projection.expense_recovery[0]
    assert netted == 0.0
    assert projection.total_operating_expenses[0] != pytest.approx(netted, abs=1e-3)


def test_g14_a_net_expense_shortcut_would_change_the_fee_and_noi() -> None:
    """**The mandatory non-netting proof.** cash ``100``, recovery ``50``, fixed
    opex ``50``, fee 10%.

    Correct: EGI ``150``, fee ``15``, NOI ``85``.
    A net-expense/rent-only-fee shortcut gives fee ``10`` and NOI ``90``.
    Pre-fee NOI is ``100`` either way, which is exactly why this cannot be
    caught by looking at NOI before the fee."""

    projection = project(
        cash=100.0, recovery=50.0, fixed=50.0, management_fee_pct=0.10
    )

    assert projection.effective_gross_income[0] == pytest.approx(150.0, abs=1e-9)
    assert projection.management_fee[0] == pytest.approx(15.0, abs=1e-9)
    assert projection.noi[0] == pytest.approx(85.0, abs=1e-9)

    assert projection.management_fee[0] != pytest.approx(10.0, abs=1e-6)
    assert projection.noi[0] != pytest.approx(90.0, abs=1e-6)


# =============================================================================
# G10 -- Modified Gross recovery is consumed, not recalculated
# =============================================================================


def test_g10_a_changing_recovery_series_flows_straight_through() -> None:
    """A Modified Gross pool crossing its stop makes recovery start mid-hold.
    D4.3 consumes the changing dollars; there is no stop formula here."""

    stepped = tuple(
        0.0 if month.period_index <= 12 else 20_000.0 for month in MONTHS
    )
    projection = build_monthly_property_projection(
        operating_schedule(cash=100_000.0),
        recovery_schedule(recovery=0.0, monthly=stepped),
        expense_schedule(fixed=50_000.0),
        operating_inputs=inputs(management_fee_pct=0.03),
    )

    assert projection.expense_recovery == stepped
    assert projection.effective_gross_income[0] == pytest.approx(100_000.0, abs=1e-9)
    assert projection.effective_gross_income[12] == pytest.approx(120_000.0, abs=1e-9)


def test_g10_noi_moves_by_the_recovery_net_of_its_own_fee_effect() -> None:
    """A ``20,000`` recovery raises NOI by ``20,000 * (1 - 0.03)``."""

    stepped = tuple(
        0.0 if month.period_index <= 12 else 20_000.0 for month in MONTHS
    )
    projection = build_monthly_property_projection(
        operating_schedule(cash=100_000.0),
        recovery_schedule(recovery=0.0, monthly=stepped),
        expense_schedule(fixed=50_000.0),
        operating_inputs=inputs(management_fee_pct=0.03),
    )

    delta = projection.noi[12] - projection.noi[0]
    assert delta == pytest.approx(20_000.0 * 0.97, abs=1e-9)


# =============================================================================
# G11 / G12 -- vacancy
# =============================================================================


def test_g11_a_fully_vacant_property_has_negative_noi() -> None:
    """Fixed expenses do not disappear because occupancy is zero."""

    projection = project(
        cash=0.0, recovery=0.0, occupied=0.0, fixed=100_000.0,
        management_fee_pct=0.03,
    )

    assert projection.cash_base_rent[0] == 0.0
    assert projection.expense_recovery[0] == 0.0
    assert projection.other_income[0] == 0.0
    assert projection.credit_loss[0] == 0.0
    assert projection.effective_gross_income[0] == 0.0
    assert projection.management_fee[0] == 0.0
    assert projection.fixed_operating_expenses[0] == 100_000.0
    assert projection.noi[0] == pytest.approx(-100_000.0, abs=1e-9)


def test_g11_noi_is_never_floored_at_zero() -> None:
    projection = project(cash=0.0, occupied=0.0, fixed=100_000.0)

    assert all(value < 0.0 for value in projection.noi)


def test_g12_a_fully_vacant_property_keeps_its_other_income() -> None:
    """cash ``0``; recovery ``0``; other income ``10,000``; fee 3%; opex
    ``100,000`` -> EGI ``10,000``, fee ``300``, NOI ``-90,300``."""

    projection = project(
        cash=0.0, recovery=0.0, occupied=0.0, fixed=100_000.0,
        other_income=120_000.0, management_fee_pct=0.03,
    )

    assert projection.other_income[0] == pytest.approx(10_000.0, abs=1e-9)
    assert projection.effective_gross_income[0] == pytest.approx(10_000.0, abs=1e-9)
    assert projection.management_fee[0] == pytest.approx(300.0, abs=1e-9)
    assert projection.noi[0] == pytest.approx(-90_300.0, abs=1e-9)


# =============================================================================
# G15 / G16 -- TI and LC stay below NOI
# =============================================================================


def test_g15_g16_doubling_ti_and_lc_leaves_every_above_noi_line_identical() -> None:
    """The perturbation proof. Only the two audit series differ."""

    without = project(
        cash=100_000.0, recovery=20_000.0, fixed=50_000.0,
        other_income=60_000.0, credit_loss_pct=0.05, management_fee_pct=0.03,
        ti=0.0, lc=0.0,
    )
    with_costs = project(
        cash=100_000.0, recovery=20_000.0, fixed=50_000.0,
        other_income=60_000.0, credit_loss_pct=0.05, management_fee_pct=0.03,
        ti=1_000_000.0, lc=500_000.0,
    )

    for name in (
        "cash_base_rent",
        "expense_recovery",
        "other_income",
        "credit_loss",
        "effective_gross_income",
        "fixed_operating_expenses",
        "management_fee",
        "total_operating_expenses",
        "noi",
    ):
        assert hexes(getattr(without, name)) == hexes(getattr(with_costs, name)), name

    assert with_costs.tenant_improvements[0] == 1_000_000.0
    assert with_costs.leasing_commissions[0] == 500_000.0


def test_g15_ti_is_absent_from_total_operating_expenses() -> None:
    projection = project(fixed=50_000.0, ti=1_000_000.0, management_fee_pct=0.03)

    assert projection.total_operating_expenses[0] == pytest.approx(50_000.0, abs=1e-9)


def test_g16_lc_is_absent_from_total_operating_expenses() -> None:
    projection = project(fixed=50_000.0, lc=500_000.0, management_fee_pct=0.03)

    assert projection.total_operating_expenses[0] == pytest.approx(50_000.0, abs=1e-9)


# =============================================================================
# G17 / G18 / G29 -- occupancy is descriptive, never a factor
# =============================================================================


def test_g17_physical_occupancy_does_not_drive_noi() -> None:
    """Identical dollar series, different occupancy: every financial line is
    bit-identical. Occupancy is descriptive."""

    full = build_monthly_property_projection(
        operating_schedule(cash=100_000.0, occupied=AREA),
        recovery_schedule(recovery=20_000.0),
        expense_schedule(fixed=50_000.0),
        operating_inputs=inputs(management_fee_pct=0.03, credit_loss_pct=0.05),
    )
    half = build_monthly_property_projection(
        operating_schedule(cash=100_000.0, occupied=AREA / 2),
        recovery_schedule(recovery=20_000.0),
        expense_schedule(fixed=50_000.0),
        operating_inputs=inputs(management_fee_pct=0.03, credit_loss_pct=0.05),
    )

    assert full.physical_occupancy[0] == 1.0
    assert half.physical_occupancy[0] == 0.5
    for name in (
        "credit_loss",
        "effective_gross_income",
        "management_fee",
        "total_operating_expenses",
        "noi",
    ):
        assert hexes(getattr(full, name)) == hexes(getattr(half, name)), name


def test_g18_a_fractional_responsibility_is_not_applied_twice() -> None:
    """Cash rent and recovery both already reflect ``O = 0.75``. Neither is
    multiplied by ``0.75`` again."""

    projection = project(
        cash=75_000.0, contractual=100_000.0, recovery=15_000.0,
        management_fee_pct=0.03,
    )

    assert projection.cash_base_rent[0] == 75_000.0
    assert projection.expense_recovery[0] == 15_000.0
    assert projection.effective_gross_income[0] == pytest.approx(90_000.0, abs=1e-9)
    # 0.75 applied twice would give 56,250 + 11,250 = 67,500.
    assert projection.effective_gross_income[0] != pytest.approx(67_500.0, abs=1e-3)


def test_g29_no_generic_vacancy_percentage_exists_on_the_inputs() -> None:
    fields = {field.name for field in dataclasses.fields(LeaseLevelOperatingInputs)}

    assert "vacancy_credit_loss_pct" not in fields
    assert "vacancy_rate" not in fields
    assert "occupancy" not in fields


def test_g29_the_projection_declares_no_vacancy_loss_line() -> None:
    fields = {field.name for field in dataclasses.fields(MonthlyPropertyProjection)}

    for forbidden in ("vacancy_loss", "vacancy_credit_loss", "vacancy", "absent_rent"):
        assert forbidden not in fields


# =============================================================================
# G19 / G20 / G21 -- the source series are copied unchanged
# =============================================================================


def test_g19_the_leasing_lines_are_copied_bit_for_bit() -> None:
    operating = operating_schedule(
        cash=75_000.0, contractual=100_000.0, free_rent=25_000.0,
        ti=1_234.5, lc=678.9, occupied=AREA * 0.4,
    )
    projection = build_monthly_property_projection(
        operating,
        recovery_schedule(recovery=20_000.0),
        expense_schedule(fixed=50_000.0),
        operating_inputs=inputs(management_fee_pct=0.03),
    )

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
        assert hexes(getattr(projection, name)) == hexes(getattr(operating, name)), name
    assert projection.rentable_area_sf == operating.rentable_area_sf


def test_g20_the_monthly_recovery_series_is_copied_bit_for_bit() -> None:
    recovery = recovery_schedule(recovery=20_000.0)
    projection = build_monthly_property_projection(
        operating_schedule(cash=100_000.0),
        recovery,
        expense_schedule(fixed=50_000.0),
        operating_inputs=inputs(),
    )

    assert hexes(projection.expense_recovery) == hexes(recovery.expense_recovery)


def test_g20_the_annual_recovery_fields_are_not_consulted() -> None:
    """D3.5's annual and forward scalars belong to D3.5. Monthly is the
    authority; corrupting the annual fields must change nothing."""

    honest = recovery_schedule(recovery=20_000.0)
    corrupted = PropertyRecoverySchedule(
        months=honest.months,
        rentable_area_sf=honest.rentable_area_sf,
        hold_period=honest.hold_period,
        suite_projections=honest.suite_projections,
        expense_recovery=honest.expense_recovery,
        annual_expense_recovery=(-999_999.0,),
        forward_exit_window_expense_recovery=-999_999.0,
    )

    a = build_monthly_property_projection(
        operating_schedule(cash=100_000.0), honest,
        expense_schedule(fixed=50_000.0), operating_inputs=inputs(management_fee_pct=0.03),
    )
    b = build_monthly_property_projection(
        operating_schedule(cash=100_000.0), corrupted,
        expense_schedule(fixed=50_000.0), operating_inputs=inputs(management_fee_pct=0.03),
    )

    assert hexes(a.noi) == hexes(b.noi)


def test_g21_the_expense_lines_are_copied_bit_for_bit() -> None:
    expenses = expense_schedule(fixed=150_000.0, split=True)
    projection = build_monthly_property_projection(
        operating_schedule(cash=100_000.0),
        recovery_schedule(recovery=0.0),
        expenses,
        operating_inputs=inputs(management_fee_pct=0.03),
    )

    for name in (
        "property_taxes",
        "insurance",
        "utilities",
        "repairs_maintenance",
        "other_operating_expenses",
        "fixed_operating_expenses",
    ):
        assert hexes(getattr(projection, name)) == hexes(getattr(expenses, name)), name


def test_g21_noi_consumes_the_total_not_a_resummation_of_the_five_lines() -> None:
    """``fixed_operating_expenses`` is D4.1's completed total; the five lines
    are audit lines."""

    expenses = expense_schedule(fixed=150_000.0, split=True)
    projection = build_monthly_property_projection(
        operating_schedule(cash=200_000.0),
        recovery_schedule(recovery=0.0),
        expenses,
        operating_inputs=inputs(management_fee_pct=0.0),
    )

    assert projection.total_operating_expenses[0] == pytest.approx(150_000.0, abs=1e-9)
    assert projection.noi[0] == pytest.approx(50_000.0, abs=1e-9)


def test_the_upstream_expense_inputs_do_not_re_enter_the_projection() -> None:
    """Changing ``expense_growth`` or the five inputs while supplying the same
    completed schedule must not change a single figure -- D4.1 is the
    authority and D4.3 does not rebuild it."""

    base = project(cash=100_000.0, fixed=50_000.0, management_fee_pct=0.03)
    perturbed = project(
        cash=100_000.0, fixed=50_000.0, management_fee_pct=0.03,
        expense_growth=0.99, property_taxes=9_999_999.0, insurance=5_000.0,
        recoverable_expense_ratio=0.13,
    )

    for name in (
        "property_taxes",
        "fixed_operating_expenses",
        "total_operating_expenses",
        "effective_gross_income",
        "noi",
    ):
        assert hexes(getattr(base, name)) == hexes(getattr(perturbed, name)), name


def test_the_recoverable_ratio_cannot_change_recovery_here() -> None:
    """D4.3 consumes the supplied recovery schedule; the ratio is D4.1's."""

    base = project(cash=100_000.0, recovery=20_000.0, recoverable_expense_ratio=1.0)
    perturbed = project(cash=100_000.0, recovery=20_000.0, recoverable_expense_ratio=0.0)

    assert hexes(base.expense_recovery) == hexes(perturbed.expense_recovery)
    assert hexes(base.noi) == hexes(perturbed.noi)


# =============================================================================
# G22 / G23 / G24 -- composition refusals
# =============================================================================


def test_g22_a_recovery_month_mismatch_is_refused() -> None:
    other = build_model_months(analysis_start=date(2029, 1, 1), hold_period=HOLD)

    with pytest.raises(LeaseValidationError) as raised:
        build_monthly_property_projection(
            operating_schedule(cash=1.0),
            recovery_schedule(recovery=0.0, timeline=other),
            expense_schedule(fixed=0.0),
            operating_inputs=inputs(),
        )

    assert LeaseIssueCode.PROPERTY_RECOVERY_NOT_ALIGNED in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g22_an_expense_month_mismatch_is_refused() -> None:
    other = build_model_months(analysis_start=date(2029, 1, 1), hold_period=HOLD)

    with pytest.raises(LeaseValidationError) as raised:
        build_monthly_property_projection(
            operating_schedule(cash=1.0),
            recovery_schedule(recovery=0.0),
            expense_schedule(fixed=0.0, timeline=other),
            operating_inputs=inputs(),
        )

    assert LeaseIssueCode.PROPERTY_EXPENSE_SCHEDULE_NOT_ALIGNED in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g22_a_same_length_different_identity_timeline_is_refused() -> None:
    """Month identity, not length."""

    other = build_model_months(analysis_start=date(2031, 5, 1), hold_period=HOLD)
    assert len(other) == len(MONTHS)

    with pytest.raises(LeaseValidationError):
        build_monthly_property_projection(
            operating_schedule(cash=1.0),
            recovery_schedule(recovery=0.0, timeline=other),
            expense_schedule(fixed=0.0),
            operating_inputs=inputs(),
        )


def test_g23_a_rentable_area_mismatch_is_refused() -> None:
    with pytest.raises(LeaseValidationError) as raised:
        build_monthly_property_projection(
            operating_schedule(cash=1.0, area=100_000.0),
            recovery_schedule(recovery=0.0, area=90_000.0),
            expense_schedule(fixed=0.0),
            operating_inputs=inputs(),
        )

    assert LeaseIssueCode.PROPERTY_RECOVERY_AREA_MISMATCH in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g24_a_suite_universe_mismatch_is_refused() -> None:
    """Equal areas and equal timelines do not make one property."""

    with pytest.raises(LeaseValidationError) as raised:
        build_monthly_property_projection(
            operating_schedule(cash=1.0, suite_ids=("A", "B")),
            recovery_schedule(recovery=0.0, suite_ids=("A", "C")),
            expense_schedule(fixed=0.0),
            operating_inputs=inputs(),
        )

    assert LeaseIssueCode.PROPERTY_RECOVERY_SUITE_UNIVERSE_MISMATCH in [
        issue.code for issue in raised.value.result.errors
    ]


def test_g24_a_missing_recovery_suite_is_refused() -> None:
    with pytest.raises(LeaseValidationError):
        build_monthly_property_projection(
            operating_schedule(cash=1.0, suite_ids=("A", "B")),
            recovery_schedule(recovery=0.0, suite_ids=("A",)),
            expense_schedule(fixed=0.0),
            operating_inputs=inputs(),
        )


def test_g24_a_matching_suite_universe_in_a_different_order_is_accepted() -> None:
    projection = build_monthly_property_projection(
        operating_schedule(cash=1.0, suite_ids=("A", "B")),
        recovery_schedule(recovery=0.0, suite_ids=("B", "A")),
        expense_schedule(fixed=0.0),
        operating_inputs=inputs(),
    )

    assert projection.noi[0] == pytest.approx(1.0, abs=1e-9)


def test_an_out_of_domain_operating_input_is_refused() -> None:
    with pytest.raises(LeaseValidationError) as raised:
        build_monthly_property_projection(
            operating_schedule(cash=1.0),
            recovery_schedule(recovery=0.0),
            expense_schedule(fixed=0.0),
            operating_inputs=inputs(management_fee_pct=1.5),
        )

    assert LeaseIssueCode.MANAGEMENT_FEE_OUT_OF_DOMAIN in [
        issue.code for issue in raised.value.result.errors
    ]


def test_validation_issue_ordering_is_deterministic() -> None:
    other = build_model_months(analysis_start=date(2029, 1, 1), hold_period=HOLD)

    result = validate_property_projection_inputs(
        operating_schedule(cash=1.0, area=100_000.0, suite_ids=("A", "B")),
        recovery_schedule(
            recovery=0.0, timeline=other, area=90_000.0, suite_ids=("A", "C")
        ),
        expense_schedule(fixed=0.0, timeline=other),
        operating_inputs=inputs(credit_loss_pct=5.0),
    )

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.CREDIT_LOSS_OUT_OF_DOMAIN,
        LeaseIssueCode.PROPERTY_RECOVERY_NOT_ALIGNED,
        LeaseIssueCode.PROPERTY_EXPENSE_SCHEDULE_NOT_ALIGNED,
        LeaseIssueCode.PROPERTY_RECOVERY_AREA_MISMATCH,
        LeaseIssueCode.PROPERTY_RECOVERY_SUITE_UNIVERSE_MISMATCH,
    ]


def test_a_valid_composition_produces_no_issues() -> None:
    result = validate_property_projection_inputs(
        operating_schedule(cash=1.0),
        recovery_schedule(recovery=0.0),
        expense_schedule(fixed=0.0),
        operating_inputs=inputs(),
    )

    assert result.is_valid
    assert not result.issues


# =============================================================================
# G25 / G26 -- the forward window
# =============================================================================


def test_g25_the_projection_spans_the_full_canonical_window() -> None:
    projection = project(cash=100_000.0, fixed=50_000.0)

    assert len(projection.months) == 12 * HOLD + 12
    for name in (
        "cash_base_rent",
        "expense_recovery",
        "other_income",
        "credit_loss",
        "effective_gross_income",
        "management_fee",
        "total_operating_expenses",
        "noi",
        "tenant_improvements",
        "leasing_commissions",
        "physical_occupancy",
    ):
        assert len(getattr(projection, name)) == 12 * HOLD + 12, name


def test_g25_every_economic_line_is_live_in_the_forward_window() -> None:
    projection = project(
        cash=100_000.0, recovery=20_000.0, fixed=50_000.0,
        other_income=120_000.0, credit_loss_pct=0.05, management_fee_pct=0.03,
    )

    for position in range(12 * HOLD, len(projection.months)):
        assert projection.cash_base_rent[position] == 100_000.0
        assert projection.expense_recovery[position] == 20_000.0
        assert projection.other_income[position] > 0.0
        assert projection.credit_loss[position] > 0.0
        assert projection.management_fee[position] > 0.0
        assert projection.noi[position] != 0.0


def test_g26_forward_ti_and_lc_are_retained_and_absent_from_noi() -> None:
    forward_ti = tuple(
        1_000_000.0 if month.is_forward_exit_month else 0.0 for month in MONTHS
    )
    forward_lc = tuple(
        500_000.0 if month.is_forward_exit_month else 0.0 for month in MONTHS
    )
    operating = PropertyOperatingSchedule(
        months=MONTHS,
        rentable_area_sf=AREA,
        suite_projections=operating_schedule(cash=0.0).suite_projections,
        contractual_base_rent=flat(100_000.0),
        cash_base_rent=flat(100_000.0),
        free_rent=flat(0.0),
        tenant_improvements=forward_ti,
        leasing_commissions=forward_lc,
        occupied_area_sf=flat(AREA),
        vacant_area_sf=flat(0.0),
        physical_occupancy=flat(1.0),
    )

    projection = build_monthly_property_projection(
        operating,
        recovery_schedule(recovery=0.0),
        expense_schedule(fixed=50_000.0),
        operating_inputs=inputs(management_fee_pct=0.03),
    )

    assert projection.tenant_improvements == forward_ti
    assert projection.leasing_commissions == forward_lc
    assert len(set(projection.noi)) == 1, "forward TI/LC moved NOI"


# =============================================================================
# G27 -- determinism and shape
# =============================================================================


def test_g27_repeated_builds_are_equal_and_bit_identical() -> None:
    first = project(
        cash=100_000.0, recovery=20_000.0, fixed=50_000.0,
        other_income=60_000.0, credit_loss_pct=0.05, management_fee_pct=0.03,
    )
    second = project(
        cash=100_000.0, recovery=20_000.0, fixed=50_000.0,
        other_income=60_000.0, credit_loss_pct=0.05, management_fee_pct=0.03,
    )

    assert first == second
    assert hexes(first.noi) == hexes(second.noi)


def test_g27_the_projection_is_immutable() -> None:
    projection = project(cash=1.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        projection.noi = ()  # type: ignore[misc]


def test_g27_the_source_schedules_are_retained_not_collapsed() -> None:
    operating = operating_schedule(cash=100_000.0)
    recovery = recovery_schedule(recovery=20_000.0)
    expenses = expense_schedule(fixed=50_000.0)

    projection = build_monthly_property_projection(
        operating, recovery, expenses, operating_inputs=inputs()
    )

    assert projection.operating_schedule is operating
    assert projection.recovery_schedule is recovery
    assert projection.expense_schedule is expenses


def test_a_non_finite_result_is_refused_rather_than_propagated() -> None:
    with pytest.raises(NonFiniteResultError):
        build_monthly_property_projection(
            operating_schedule(cash=0.0),
            recovery_schedule(recovery=0.0),
            expense_schedule(fixed=0.0),
            operating_inputs=inputs(
                other_income=1e300, other_income_growth=1e300
            ),
        )


# =============================================================================
# G28 -- other-income arithmetic matches Detailed bit for bit
# =============================================================================


_AMOUNTS = (0.0, 1.0, 120_000.0, 123_456.789, 1e-9, 987_654_321.12, 7.3)
_GROWTHS = (0.0, 0.03, 0.10, 0.17, 0.9999, -0.02, -0.5, -0.999999)
_YEARS = (1, 2, 5, 10, 11, 21, 31)


@pytest.mark.parametrize("year_1_amount", _AMOUNTS)
@pytest.mark.parametrize("growth", _GROWTHS)
def test_g28_lease_level_other_income_growth_matches_detailed_bit_for_bit(
    year_1_amount: float, growth: float
) -> None:
    """The arithmetic is identical to Detailed's; the **assumptions** are not.
    Detailed reaches it through ``revenue_growth``, Lease-Level through
    ``other_income_growth`` (D4 Section 8.3)."""

    hold_period = max(_YEARS) - 1
    detailed = build_detailed_operating_projection(
        DetailedOperatingInputs(
            gross_potential_rent=0.0,
            other_income=year_1_amount,
            vacancy_credit_loss_pct=0.0,
            property_taxes=0.0,
            insurance=0.0,
            utilities=0.0,
            repairs_maintenance=0.0,
            other_operating_expenses=0.0,
            management_fee_pct=0.0,
            revenue_growth=growth,
            expense_growth=0.0,
        ),
        hold_period=hold_period,
        purchase_price=10_000_000.0,
    )

    for model_year in _YEARS:
        if model_year > hold_period:
            continue
        lease_level = annual_other_income(
            year_1_amount=year_1_amount,
            other_income_growth=growth,
            model_year=model_year,
        )
        assert lease_level.hex() == detailed.other_income_by_year[model_year - 1].hex()


def test_g28_year_one_is_the_base_year_bit_for_bit() -> None:
    for amount in _AMOUNTS:
        for growth in _GROWTHS:
            result = annual_other_income(
                year_1_amount=amount, other_income_growth=growth, model_year=1
            )
            assert result.hex() == amount.hex()


def test_g28_other_income_growth_and_expense_growth_do_not_alias() -> None:
    """Two separate assumptions. Moving one must not move the other's line."""

    base = project(cash=0.0, fixed=50_000.0, other_income=120_000.0,
                   other_income_growth=0.10, expense_growth=0.0)
    changed_expense_growth = project(
        cash=0.0, fixed=50_000.0, other_income=120_000.0,
        other_income_growth=0.10, expense_growth=0.50,
    )
    changed_other_growth = project(
        cash=0.0, fixed=50_000.0, other_income=120_000.0,
        other_income_growth=0.20, expense_growth=0.0,
    )

    assert hexes(base.other_income) == hexes(changed_expense_growth.other_income)
    assert hexes(base.other_income) != hexes(changed_other_growth.other_income)
    assert hexes(base.fixed_operating_expenses) == hexes(
        changed_other_growth.fixed_operating_expenses
    )


# =============================================================================
# End-to-end: a real chain through the whole D4.1-D4.3 stack
# =============================================================================


def test_a_real_property_composes_end_to_end() -> None:
    """One vacant suite let after three months, with real expenses and a real
    pool, through D4.1, D4.2 and D4.3."""

    timeline = build_model_months(analysis_start=JAN, hold_period=2)
    suite = Suite(
        suite_id="A",
        suite_area_sf=10_000.0,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP,
            initial_lease_up_months=3.0,
        ),
    )
    assumptions = MarketLeasingAssumptions(
        market_rent_psf=120.0,
        market_rent_growth=0.0,
        renewal_rent_psf=None,
        renewal_rent_spread=0.0,
        renewal_term_months=12,
        successor_escalation_pct=0.0,
        renewal_downtime_months=0.0,
        renewal_free_rent_months=0.0,
        new_term_months=12,
        new_downtime_months=0.0,
        new_free_rent_months=0.0,
        renewal_ti_psf=0.0,
        new_ti_psf=0.0,
        leasing_commission_method=(
            LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT
        ),
        renewal_lc_pct=0.0,
        new_lc_pct=0.0,
        renewal_probability=0.5,
        renewal_lease_type=LeaseType.NNN,
        renewal_recovery_basis=None,
        renewal_expense_stop_psf=None,
        new_lease_type=LeaseType.NNN,
        new_recovery_basis=None,
        new_expense_stop_psf=None,
    )
    chain = build_initial_vacancy_rollover(
        suite, analysis_start=JAN, months=timeline, property_defaults=assumptions
    )
    operating = build_property_operating_schedule(
        [suite_operating_projection(suite, chain)],
        [suite],
        months=timeline,
        rentable_area_sf=10_000.0,
    )

    operating_inputs = LeaseLevelOperatingInputs(
        other_income=12_000.0,
        other_income_growth=0.0,
        credit_loss_pct=0.0,
        property_taxes=600_000.0,
        insurance=0.0,
        utilities=0.0,
        repairs_maintenance=0.0,
        other_operating_expenses=0.0,
        management_fee_pct=0.03,
        expense_growth=0.0,
        recoverable_expense_ratio=1.0,
    )
    expenses = build_property_expense_schedule(operating_inputs, months=timeline)
    pool = build_recoverable_expense_pool(
        expenses, recoverable_expense_ratio=1.0
    )
    recovery = PropertyRecoverySchedule(
        months=timeline,
        rentable_area_sf=10_000.0,
        hold_period=2,
        suite_projections=(
            SuiteRecoveryProjection(
                suite_id="A",
                months=timeline,
                expense_recovery=flat(0.0, timeline=timeline),
            ),
        ),
        expense_recovery=flat(0.0, timeline=timeline),
        annual_expense_recovery=(0.0, 0.0),
        forward_exit_window_expense_recovery=0.0,
    )

    projection = build_monthly_property_projection(
        operating, recovery, expenses, operating_inputs=operating_inputs
    )

    # Months 1-3: vacant. Other income 1,000/month; expenses 50,000/month.
    assert projection.cash_base_rent[0] == 0.0
    assert projection.other_income[0] == pytest.approx(1_000.0, abs=1e-9)
    assert projection.fixed_operating_expenses[0] == pytest.approx(50_000.0, abs=1e-9)
    assert projection.noi[0] == pytest.approx(1_000.0 * 0.97 - 50_000.0, abs=1e-9)

    # Month 4: the first tenant, 10,000 SF at $120/SF/year.
    assert projection.cash_base_rent[3] == pytest.approx(100_000.0, abs=1e-9)
    assert projection.effective_gross_income[3] == pytest.approx(101_000.0, abs=1e-9)
    assert projection.noi[3] == pytest.approx(
        101_000.0 * 0.97 - 50_000.0, abs=1e-9
    )
    assert pool.recoverable_expenses[0] == pytest.approx(50_000.0, abs=1e-9)


# =============================================================================
# Scope
# =============================================================================


def test_the_projection_declares_no_later_gate_concept() -> None:
    fields = {field.name for field in dataclasses.fields(MonthlyPropertyProjection)}

    for forbidden in (
        "capex",
        "exit_noi",
        "going_in_cap_rate",
        "noi_by_year",
        "annual_noi",
        "debt_service",
        "irr",
        "dscr",
        "acquisition_costs",
        "sale_proceeds",
        "market_rent_psf",
        "recoverable_expense_pool",
    ):
        assert forbidden not in fields, f"MonthlyPropertyProjection declares {forbidden}"


def test_no_annual_series_is_produced() -> None:
    fields = {field.name for field in dataclasses.fields(MonthlyPropertyProjection)}

    assert not any(name.endswith("_by_year") for name in fields)
    assert not any(name.startswith("annual_") for name in fields)
    assert "hold_period" not in fields


def test_the_builder_takes_no_raw_leasing_or_pool_input() -> None:
    import inspect

    parameters = set(
        inspect.signature(build_monthly_property_projection).parameters
    )

    assert parameters == {"operating", "recovery", "expenses", "operating_inputs"}
