"""Sprint D Gate D4.4 -- the annual operating adapter and forward exit NOI.

Governed by
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 20.1-20.5 and 21, and D0 Section 4.7.

D4.4 derives; it does not model. The claims that fail silently if wrong:

- **annual NOI is the sum of monthly NOI**, never rebuilt from annual EGI less
  annual expenses -- one arithmetic path to the figure every return depends on;
- **``exit_noi`` is the sum of monthly NOI over months ``12H+1..12H+12``**,
  never Hold Year H grown, never stabilized, never gross of free rent;
- **hold-year arrays have length H** and physically cannot reach a forward
  month, which is what keeps a post-sale TI cheque out of a seller cash flow;
- **annual occupancy is the average of the twelve monthly property values**,
  with the year-end snapshot beside it under its own name;
- **a non-positive ``exit_noi`` is constructed faithfully here.** Refusing to
  capitalize it is the integration boundary's job at D4.5 (HD-D4-7).
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.engine.contracts import OperatingProjectionLike
from anchor.leasing import (
    AnnualOperatingProjection,
    LeaseIssueCode,
    LeaseValidationError,
    ModelMonth,
    MonthlyPropertyExpenseSchedule,
    MonthlyPropertyProjection,
    PropertyOperatingSchedule,
    PropertyRecoverySchedule,
    SuiteOperatingProjection,
    SuiteRecoveryProjection,
    aggregate_flow_over_forward_exit_window,
    aggregate_flow_to_annual,
    aggregate_monthly_to_annual,
    average_state_over_year,
    build_model_months,
    snapshot_state_at_year_end,
    validate_annual_adapter_inputs,
)


# =============================================================================
# Fixtures -- a monthly projection assembled directly, so every golden is
# hand-checkable and the adapter is what is under test.
# =============================================================================


JAN = date(2027, 1, 1)
JULY = date(2027, 7, 1)
AREA = 100.0
PRICE = 10_000.0

#: Every monthly flow line the adapter annualises, and the annual field it
#: becomes. Drives the generalized reconciliation golden (G24).
FLOW_LINES = (
    "contractual_base_rent",
    "cash_base_rent",
    "free_rent",
    "expense_recovery",
    "other_income",
    "credit_loss",
    "effective_gross_income",
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "other_operating_expenses",
    "fixed_operating_expenses",
    "management_fee",
    "total_operating_expenses",
    "noi",
    "tenant_improvements",
    "leasing_commissions",
)


def hexes(values) -> list[str]:
    return [value.hex() for value in values]


def monthly_projection(
    *,
    hold_period: int = 1,
    analysis_start: date = JAN,
    noi: list[float] | None = None,
    ti: list[float] | None = None,
    lc: list[float] | None = None,
    occupancy: list[float] | None = None,
    egi: list[float] | None = None,
    total_opex: list[float] | None = None,
    **flows: list[float],
) -> MonthlyPropertyProjection:
    """A canonical monthly projection with hand-specified series.

    Unspecified flow lines are zero. ``egi`` defaults to ``noi`` and
    ``total_opex`` to zero, so the statement reconciles unless a test
    deliberately breaks that to prove which series is authoritative.
    """

    months = build_model_months(
        analysis_start=analysis_start, hold_period=hold_period
    )
    count = len(months)
    zeros = tuple(0.0 for _ in range(count))

    def series(values: list[float] | None) -> tuple[float, ...]:
        if values is None:
            return zeros
        assert len(values) == count, f"expected {count} values, got {len(values)}"
        return tuple(float(value) for value in values)

    noi_series = series(noi)
    ti_series = series(ti)
    lc_series = series(lc)
    egi_series = noi_series if egi is None else series(egi)
    opex_series = series(total_opex)
    occ = tuple(1.0 for _ in range(count)) if occupancy is None else series(occupancy)
    occupied = tuple(value * AREA for value in occ)
    vacant = tuple(AREA - value for value in occupied)

    extra = {name: series(flows.get(name)) for name in FLOW_LINES}

    suite_operating = SuiteOperatingProjection(
        suite_id="A",
        suite_area_sf=AREA,
        months=months,
        contractual_base_rent=extra["contractual_base_rent"],
        cash_base_rent=extra["cash_base_rent"],
        free_rent=extra["free_rent"],
        tenant_improvements=ti_series,
        leasing_commissions=lc_series,
        occupied_area_sf=occupied,
    )
    operating = PropertyOperatingSchedule(
        months=months,
        rentable_area_sf=AREA,
        suite_projections=(suite_operating,),
        contractual_base_rent=extra["contractual_base_rent"],
        cash_base_rent=extra["cash_base_rent"],
        free_rent=extra["free_rent"],
        tenant_improvements=ti_series,
        leasing_commissions=lc_series,
        occupied_area_sf=occupied,
        vacant_area_sf=vacant,
        physical_occupancy=occ,
    )
    recovery = PropertyRecoverySchedule(
        months=months,
        rentable_area_sf=AREA,
        hold_period=hold_period,
        suite_projections=(
            SuiteRecoveryProjection(
                suite_id="A", months=months, expense_recovery=extra["expense_recovery"]
            ),
        ),
        expense_recovery=extra["expense_recovery"],
        annual_expense_recovery=aggregate_flow_to_annual(
            extra["expense_recovery"], hold_period=hold_period
        ),
        forward_exit_window_expense_recovery=(
            aggregate_flow_over_forward_exit_window(
                extra["expense_recovery"], hold_period=hold_period
            )
        ),
    )
    expenses = MonthlyPropertyExpenseSchedule(
        months=months,
        property_taxes=extra["property_taxes"],
        insurance=extra["insurance"],
        utilities=extra["utilities"],
        repairs_maintenance=extra["repairs_maintenance"],
        other_operating_expenses=extra["other_operating_expenses"],
        fixed_operating_expenses=extra["fixed_operating_expenses"],
    )

    return MonthlyPropertyProjection(
        months=months,
        rentable_area_sf=AREA,
        contractual_base_rent=extra["contractual_base_rent"],
        free_rent=extra["free_rent"],
        cash_base_rent=extra["cash_base_rent"],
        expense_recovery=extra["expense_recovery"],
        other_income=extra["other_income"],
        credit_loss=extra["credit_loss"],
        effective_gross_income=egi_series,
        property_taxes=extra["property_taxes"],
        insurance=extra["insurance"],
        utilities=extra["utilities"],
        repairs_maintenance=extra["repairs_maintenance"],
        other_operating_expenses=extra["other_operating_expenses"],
        fixed_operating_expenses=extra["fixed_operating_expenses"],
        management_fee=extra["management_fee"],
        total_operating_expenses=opex_series,
        noi=noi_series,
        tenant_improvements=ti_series,
        leasing_commissions=lc_series,
        occupied_area_sf=occupied,
        vacant_area_sf=vacant,
        physical_occupancy=occ,
        operating_schedule=operating,
        recovery_schedule=recovery,
        expense_schedule=expenses,
    )


def event_at(month: int, amount: float, *, count: int) -> list[float]:
    """A single event in 1-based ``month``, zero elsewhere."""

    return [amount if index == month - 1 else 0.0 for index in range(count)]


# =============================================================================
# G1 / G23 -- the hold / forward split
# =============================================================================


def test_g1_the_hand_worked_hold_and_forward_split() -> None:
    """``H = 1``. Months 1-12 NOI ``100``; months 13-18 ``200``; months 19-24
    ``300``. Annual NOI ``[1200]``; exit NOI ``6x200 + 6x300 = 3000``."""

    monthly = monthly_projection(
        hold_period=1, noi=[100.0] * 12 + [200.0] * 6 + [300.0] * 6
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.noi_by_year == (1200.0,)
    assert annual.exit_noi == pytest.approx(3000.0, abs=1e-9)


@pytest.mark.parametrize("rejected", [2400.0, 3600.0, 1200.0])
def test_g1_the_rejected_exit_noi_values_do_not_appear(rejected: float) -> None:
    """``2400`` is twelve of the first forward rate; ``3600`` twelve of the
    second; ``1200`` is Hold Year H ungrown."""

    monthly = monthly_projection(
        hold_period=1, noi=[100.0] * 12 + [200.0] * 6 + [300.0] * 6
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.exit_noi != pytest.approx(rejected, abs=1e-6)


def test_g23_hold_period_one_produces_arrays_of_length_one() -> None:
    """24 canonical months, one hold year -- never two."""

    monthly = monthly_projection(hold_period=1, noi=[100.0] * 24)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert len(monthly.months) == 24
    for name in FLOW_LINES:
        assert len(getattr(annual, f"{name}_by_year")) == 1, name
    for name in (
        "occupied_area_at_year_end",
        "vacant_area_at_year_end",
        "physical_occupancy_at_year_end",
        "average_physical_occupancy_over_year",
    ):
        assert len(getattr(annual, name)) == 1, name


@pytest.mark.parametrize("hold_period", [1, 2, 3, 5, 10])
def test_g22_every_hold_period_partitions_12h_plus_12(hold_period: int) -> None:
    monthly = monthly_projection(
        hold_period=hold_period, noi=[1.0] * (12 * hold_period + 12)
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert len(monthly.months) == 12 * hold_period + 12
    assert len(annual.noi_by_year) == hold_period
    assert annual.exit_noi == pytest.approx(12.0, abs=1e-9)


# =============================================================================
# G2 / G4 / G24 -- monthly is authoritative
# =============================================================================


def test_g2_annual_noi_is_the_direct_monthly_noi_sum() -> None:
    monthly = monthly_projection(
        hold_period=2, noi=[10.0] * 12 + [20.0] * 12 + [30.0] * 12
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.noi_by_year == (120.0, 240.0)


def test_g4_annual_noi_is_not_reconstructed_from_egi_less_expenses() -> None:
    """**The source-authority proof.** The fixture deliberately makes
    ``EGI - opex`` differ from ``noi``. Production must report the monthly NOI
    sum; a reconstruction would report the other number."""

    monthly = monthly_projection(
        hold_period=1,
        noi=[100.0] * 24,
        egi=[500.0] * 24,
        total_opex=[300.0] * 24,
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.noi_by_year == (1200.0,)
    # EGI - opex would be 200/month -> 2400.
    assert annual.effective_gross_income_by_year == (6000.0,)
    assert annual.total_operating_expenses_by_year == (3600.0,)
    assert annual.noi_by_year[0] != pytest.approx(2400.0, abs=1e-6)


def test_g4_exit_noi_is_not_reconstructed_either() -> None:
    monthly = monthly_projection(
        hold_period=1,
        noi=[100.0] * 24,
        egi=[500.0] * 24,
        total_opex=[300.0] * 24,
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.exit_noi == pytest.approx(1200.0, abs=1e-9)
    assert annual.exit_noi != pytest.approx(2400.0, abs=1e-6)


def test_g3_g24_every_annual_flow_line_equals_its_monthly_reduction() -> None:
    """**The generalized reconciliation.** One assertion per exposed line,
    driven by the field mapping rather than eighteen hand-written tests."""

    count = 12 * 2 + 12
    monthly = monthly_projection(
        hold_period=2,
        noi=[7.5] * count,
        ti=[3.25] * count,
        lc=[1.75] * count,
        **{
            name: [float(index + 1) * 1.5 for index in range(count)]
            for name in FLOW_LINES
            if name not in {"noi", "tenant_improvements", "leasing_commissions"}
        },
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    for name in FLOW_LINES:
        expected = aggregate_flow_to_annual(
            getattr(monthly, name), hold_period=2
        )
        assert hexes(getattr(annual, f"{name}_by_year")) == hexes(expected), name


def test_g24_the_reducer_is_the_shipped_d1_3_one() -> None:
    """One canonical reducer, shared with D1.3 -- not a second summation."""

    monthly = monthly_projection(
        hold_period=2, noi=[float(index) * 0.1 for index in range(36)]
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert hexes(annual.noi_by_year) == hexes(
        aggregate_flow_to_annual(monthly.noi, hold_period=2)
    )
    assert annual.exit_noi.hex() == aggregate_flow_over_forward_exit_window(
        monthly.noi, hold_period=2
    ).hex()


def test_g24_flows_and_leasing_costs_use_the_same_reducer() -> None:
    """A different reducer for TI would give a different last bit."""

    count = 24
    values = [0.1] * count
    monthly = monthly_projection(
        hold_period=1, noi=values, ti=list(values), lc=list(values)
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.noi_by_year[0].hex() == annual.tenant_improvements_by_year[0].hex()
    assert annual.noi_by_year[0].hex() == annual.leasing_commissions_by_year[0].hex()


# =============================================================================
# G5 / G6 / G7 / G8 -- the TI / LC hold-forward boundary
# =============================================================================


def test_g5_g6_hold_period_ti_and_lc_are_the_monthly_sums() -> None:
    count = 12 * 2 + 12
    monthly = monthly_projection(
        hold_period=2,
        noi=[0.0] * count,
        ti=[100.0] * count,
        lc=[50.0] * count,
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.tenant_improvements_by_year == (1200.0, 1200.0)
    assert annual.leasing_commissions_by_year == (600.0, 600.0)


def test_g7_a_month_12h_event_lands_in_the_final_hold_year() -> None:
    """``H = 2``: month 24 is the sale month and is a seller cost."""

    count = 36
    monthly = monthly_projection(
        hold_period=2,
        noi=[100.0] * count,
        ti=event_at(24, 1_000_000.0, count=count),
        lc=event_at(24, 500_000.0, count=count),
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.tenant_improvements_by_year == (0.0, 1_000_000.0)
    assert annual.leasing_commissions_by_year == (0.0, 500_000.0)
    assert annual.exit_window_leasing_costs == 0.0


def test_g8_a_month_12h_plus_one_event_is_excluded_from_every_hold_year() -> None:
    """The same economics one month later. The buyer writes that cheque."""

    count = 36
    monthly = monthly_projection(
        hold_period=2,
        noi=[100.0] * count,
        ti=event_at(25, 1_000_000.0, count=count),
        lc=event_at(25, 500_000.0, count=count),
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.tenant_improvements_by_year == (0.0, 0.0)
    assert annual.leasing_commissions_by_year == (0.0, 0.0)
    assert annual.exit_window_leasing_costs == pytest.approx(1_500_000.0, abs=1e-9)


def test_g7_g8_the_boundary_is_exact_at_every_hold_period() -> None:
    for hold_period in (1, 2, 3):
        count = 12 * hold_period + 12
        sale_month = 12 * hold_period

        inside = aggregate_monthly_to_annual(
            monthly_projection(
                hold_period=hold_period,
                noi=[0.0] * count,
                ti=event_at(sale_month, 1_000.0, count=count),
            ),
            purchase_price=PRICE,
        )
        outside = aggregate_monthly_to_annual(
            monthly_projection(
                hold_period=hold_period,
                noi=[0.0] * count,
                ti=event_at(sale_month + 1, 1_000.0, count=count),
            ),
            purchase_price=PRICE,
        )

        assert sum(inside.tenant_improvements_by_year) == 1_000.0
        assert sum(outside.tenant_improvements_by_year) == 0.0
        assert inside.exit_window_leasing_costs == 0.0
        assert outside.exit_window_leasing_costs == 1_000.0


# =============================================================================
# G9 / G10 -- forward TI/LC and exit NOI
# =============================================================================


def test_g9_forward_ti_and_lc_do_not_affect_exit_noi() -> None:
    """Structural: they never entered ``noi``, so they cannot leave it."""

    count = 36
    without = aggregate_monthly_to_annual(
        monthly_projection(hold_period=2, noi=[100.0] * count),
        purchase_price=PRICE,
    )
    with_costs = aggregate_monthly_to_annual(
        monthly_projection(
            hold_period=2,
            noi=[100.0] * count,
            ti=event_at(27, 1_000_000.0, count=count),
            lc=event_at(27, 500_000.0, count=count),
        ),
        purchase_price=PRICE,
    )

    assert without.exit_noi.hex() == with_costs.exit_noi.hex()
    assert hexes(without.noi_by_year) == hexes(with_costs.noi_by_year)
    assert with_costs.exit_window_leasing_costs == pytest.approx(
        1_500_000.0, abs=1e-9
    )


def test_g10_forward_ti_and_lc_remain_in_the_monthly_source() -> None:
    """The audit trail survives: the annual view discloses the total, the
    monthly projection still shows the month."""

    count = 36
    monthly = monthly_projection(
        hold_period=2,
        noi=[100.0] * count,
        ti=event_at(27, 1_000_000.0, count=count),
        lc=event_at(27, 500_000.0, count=count),
    )

    aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert monthly.tenant_improvements[26] == 1_000_000.0
    assert monthly.leasing_commissions[26] == 500_000.0
    assert monthly.months[26].is_forward_exit_month


def test_g10_exit_window_leasing_costs_is_ti_plus_lc() -> None:
    count = 36
    monthly = monthly_projection(
        hold_period=2,
        noi=[0.0] * count,
        ti=[10.0 if index >= 24 else 0.0 for index in range(count)],
        lc=[5.0 if index >= 24 else 0.0 for index in range(count)],
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.exit_window_leasing_costs == pytest.approx(180.0, abs=1e-9)


def test_g10_the_disclosed_diagnostic_is_deducted_from_nothing() -> None:
    count = 36
    without = aggregate_monthly_to_annual(
        monthly_projection(hold_period=2, noi=[100.0] * count),
        purchase_price=PRICE,
    )
    with_costs = aggregate_monthly_to_annual(
        monthly_projection(
            hold_period=2,
            noi=[100.0] * count,
            ti=[999.0 if index >= 24 else 0.0 for index in range(count)],
        ),
        purchase_price=PRICE,
    )

    for name in FLOW_LINES:
        if name == "tenant_improvements":
            continue
        assert hexes(getattr(without, f"{name}_by_year")) == hexes(
            getattr(with_costs, f"{name}_by_year")
        ), name
    assert without.exit_noi.hex() == with_costs.exit_noi.hex()
    assert without.going_in_cap_rate.hex() == with_costs.going_in_cap_rate.hex()


# =============================================================================
# G11-G14 -- whatever happens in the forward window reaches exit NOI
# =============================================================================


def test_g11_a_forward_lease_up_changes_exit_noi() -> None:
    """Months 13-15 depressed while the suite sits empty, then higher from
    month 16. Exit NOI is the actual sum, not a stabilized figure."""

    monthly = monthly_projection(
        hold_period=1,
        noi=[100.0] * 12 + [-50.0] * 3 + [400.0] * 9,
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.exit_noi == pytest.approx(3 * -50.0 + 9 * 400.0, abs=1e-9)
    assert annual.exit_noi == pytest.approx(3450.0, abs=1e-9)
    # A stabilized 12 x 400 would be 4,800.
    assert annual.exit_noi != pytest.approx(4800.0, abs=1e-6)


def test_g12_forward_free_rent_lowers_exit_noi_exactly() -> None:
    """Three abated months inside the window, each reducing NOI by 60."""

    base = [100.0] * 12 + [100.0] * 12
    abated = [100.0] * 12 + [40.0] * 3 + [100.0] * 9

    full = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, noi=base), purchase_price=PRICE
    )
    concession = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, noi=abated), purchase_price=PRICE
    )

    assert full.exit_noi == pytest.approx(1200.0, abs=1e-9)
    assert concession.exit_noi == pytest.approx(1020.0, abs=1e-9)
    assert full.exit_noi - concession.exit_noi == pytest.approx(180.0, abs=1e-9)
    # Hold-year NOI is untouched by a forward concession.
    assert hexes(full.noi_by_year) == hexes(concession.noi_by_year)


def test_g13_a_forward_recovery_step_reaches_exit_noi() -> None:
    """Recovery begins in the forward window; it is already inside monthly NOI
    and D4.4 recomputes nothing."""

    recovery = [0.0] * 18 + [20.0] * 6
    noi = [100.0] * 18 + [120.0] * 6

    annual = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, noi=noi, expense_recovery=recovery),
        purchase_price=PRICE,
    )

    assert annual.exit_noi == pytest.approx(6 * 100.0 + 6 * 120.0, abs=1e-9)
    assert annual.expense_recovery_by_year == (0.0,)


def test_g14_a_forward_expense_step_reaches_exit_noi() -> None:
    """Expense growth steps in model year H+1: the whole forward window
    carries the grown figure, and no Hold-Year-H freeze occurs."""

    expenses = [50.0] * 12 + [51.5] * 12
    noi = [100.0] * 12 + [98.5] * 12

    annual = aggregate_monthly_to_annual(
        monthly_projection(
            hold_period=1,
            noi=noi,
            fixed_operating_expenses=expenses,
        ),
        purchase_price=PRICE,
    )

    assert annual.fixed_operating_expenses_by_year == (600.0,)
    assert annual.exit_noi == pytest.approx(12 * 98.5, abs=1e-9)
    assert annual.exit_noi != pytest.approx(1200.0, abs=1e-6)


# =============================================================================
# G15 -- non-January grouping
# =============================================================================


def test_g15_a_july_start_groups_on_the_model_anniversary() -> None:
    """Hold Year 1 is July 2027 - June 2028, not calendar 2027."""

    monthly = monthly_projection(
        hold_period=2,
        analysis_start=JULY,
        noi=[100.0] * 12 + [200.0] * 12 + [300.0] * 12,
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert monthly.months[0].month_start == date(2027, 7, 1)
    assert monthly.months[11].month_start == date(2028, 6, 1)
    assert monthly.months[12].month_start == date(2028, 7, 1)
    assert annual.noi_by_year == (1200.0, 2400.0)
    assert annual.exit_noi == pytest.approx(3600.0, abs=1e-9)


def test_g15_a_december_boundary_does_not_split_a_hold_year() -> None:
    """Months 6 and 7 straddle 31 December and belong to the same hold year."""

    count = 24
    monthly = monthly_projection(
        hold_period=1,
        analysis_start=JULY,
        noi=[100.0] * count,
        ti=event_at(7, 500.0, count=count),
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert monthly.months[6].month_start == date(2028, 1, 1)
    assert monthly.months[6].hold_year == 1
    assert annual.tenant_improvements_by_year == (500.0,)


def test_g15_july_and_january_starts_give_identical_economics() -> None:
    """The grouping is anchored to the analysis start, so the two differ only
    in their calendar labels."""

    noi = [100.0] * 12 + [200.0] * 12
    january = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, analysis_start=JAN, noi=noi),
        purchase_price=PRICE,
    )
    july = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, analysis_start=JULY, noi=noi),
        purchase_price=PRICE,
    )

    assert hexes(january.noi_by_year) == hexes(july.noi_by_year)
    assert january.exit_noi.hex() == july.exit_noi.hex()


# =============================================================================
# G16 / G17 / G18 -- annual occupancy
# =============================================================================


def test_g16_annual_average_occupancy_is_the_mean_of_twelve_months() -> None:
    """Six months at ``1.00`` and six at ``0.50`` average to ``0.75``."""

    occupancy = [1.0] * 6 + [0.5] * 6 + [1.0] * 12
    monthly = monthly_projection(
        hold_period=1, noi=[0.0] * 24, occupancy=occupancy
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.average_physical_occupancy_over_year == (0.75,)


def test_g17_year_end_occupancy_is_the_final_month_not_the_average() -> None:
    occupancy = [1.0] * 6 + [0.5] * 6 + [1.0] * 12
    monthly = monthly_projection(
        hold_period=1, noi=[0.0] * 24, occupancy=occupancy
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.physical_occupancy_at_year_end == (0.5,)
    assert annual.physical_occupancy_at_year_end != (0.75,)


def test_g16_g17_the_two_reducers_are_the_shipped_d1_3_ones() -> None:
    occupancy = [1.0] * 6 + [0.5] * 6 + [0.25] * 12
    monthly = monthly_projection(
        hold_period=1, noi=[0.0] * 24, occupancy=occupancy
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert hexes(annual.average_physical_occupancy_over_year) == hexes(
        average_state_over_year(monthly.physical_occupancy, hold_period=1)
    )
    assert hexes(annual.physical_occupancy_at_year_end) == hexes(
        snapshot_state_at_year_end(monthly.physical_occupancy, hold_period=1)
    )


def test_g16_occupancy_is_never_summed() -> None:
    """A state metric summed instead of averaged would give 9.0, not 0.75."""

    occupancy = [1.0] * 6 + [0.5] * 6 + [1.0] * 12
    annual = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, noi=[0.0] * 24, occupancy=occupancy),
        purchase_price=PRICE,
    )

    assert annual.average_physical_occupancy_over_year[0] <= 1.0


def test_g18_a_mixed_size_property_occupancy_is_carried_not_recomputed() -> None:
    """D4.2 already computed ``90,000 / 100,000 = 0.90`` once, from areas. The
    adapter averages that property series and never returns to suite data."""

    occupancy = [0.9] * 24
    monthly = monthly_projection(
        hold_period=1, noi=[0.0] * 24, occupancy=occupancy
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    # Twelve 0.9s summed then divided carries ordinary last-bit drift, which
    # is the documented behaviour of the shipped averaging reducer.
    assert annual.average_physical_occupancy_over_year[0] == pytest.approx(
        0.9, abs=1e-9
    )
    assert annual.physical_occupancy_at_year_end == (0.9,)
    # Never the unweighted suite mean a two-suite property would give.
    assert annual.average_physical_occupancy_over_year[0] != pytest.approx(
        0.5, abs=1e-6
    )


def test_area_snapshots_are_taken_at_year_end() -> None:
    occupancy = [1.0] * 11 + [0.25] + [1.0] * 12
    monthly = monthly_projection(
        hold_period=1, noi=[0.0] * 24, occupancy=occupancy
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.occupied_area_at_year_end == (25.0,)
    assert annual.vacant_area_at_year_end == (75.0,)


# =============================================================================
# G19 / G20 / G21 -- signs, and where the exit-NOI restriction lives
# =============================================================================


def test_g19_a_negative_hold_year_noi_is_retained() -> None:
    monthly = monthly_projection(hold_period=1, noi=[-100.0] * 24)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.noi_by_year == (-1200.0,)
    assert annual.exit_noi == pytest.approx(-1200.0, abs=1e-9)


def test_g20_a_zero_exit_noi_is_constructed_not_rejected() -> None:
    """**Gate ownership.** D4.4 builds the scalar faithfully; refusing to
    capitalize it is D4.5's, at the acquisition/integration boundary
    (HD-D4-7)."""

    monthly = monthly_projection(hold_period=1, noi=[100.0] * 12 + [0.0] * 12)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.exit_noi == 0.0
    assert annual.noi_by_year == (1200.0,)


def test_g21_a_negative_exit_noi_is_constructed_not_rejected() -> None:
    monthly = monthly_projection(hold_period=1, noi=[100.0] * 12 + [-500.0] * 12)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.exit_noi == pytest.approx(-6000.0, abs=1e-9)


def test_g21_exit_noi_is_never_floored_at_zero() -> None:
    monthly = monthly_projection(hold_period=1, noi=[0.0] * 12 + [-1.0] * 12)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.exit_noi < 0.0


def test_the_non_positive_exit_noi_rule_is_not_applied_at_this_gate() -> None:
    """HD-D4-7 assigns the validation to the D4.5 integration boundary. It must
    not have been moved upstream merely because the scalar is built here.

    Narrowed at D4.5B: the issue code now exists, declared once in
    ``leasing/validation.py`` and applied only by the acquisition orchestrator.
    What this gate still asserts is that the D4.4 adapter never reaches it --
    ``aggregate_monthly_to_annual`` returns a negative ``exit_noi`` without
    complaint, so a distressed building's operating projection stays
    buildable and inspectable.
    """

    assert hasattr(LeaseIssueCode, "NON_POSITIVE_FORWARD_EXIT_NOI")

    monthly = monthly_projection(hold_period=1, noi=[100.0] * 12 + [-500.0] * 12)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.exit_noi < 0.0


def test_a_negative_exit_noi_raises_no_validation_issue() -> None:
    monthly = monthly_projection(hold_period=1, noi=[100.0] * 12 + [-500.0] * 12)

    result = validate_annual_adapter_inputs(
        monthly, hold_period=1, purchase_price=PRICE
    )

    assert result.is_valid
    assert not result.issues


# =============================================================================
# G26 / G27 -- the going-in cap rate
# =============================================================================


def test_g26_going_in_cap_is_year_one_noi_over_purchase_price() -> None:
    monthly = monthly_projection(hold_period=1, noi=[100.0] * 12 + [999.0] * 12)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.going_in_cap_rate == pytest.approx(1200.0 / PRICE, abs=1e-12)
    assert annual.going_in_cap_rate.hex() == (annual.noi_by_year[0] / PRICE).hex()


def test_g26_going_in_cap_uses_year_one_not_the_forward_year() -> None:
    """Year 1 sums to 1,200 and the forward window to 11,988; the going-in cap
    must read the first, never the second."""

    monthly = monthly_projection(
        hold_period=1, noi=[100.0] * 12 + [999.0] * 12
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.going_in_cap_rate == pytest.approx(0.12, abs=1e-12)
    assert annual.going_in_cap_rate != pytest.approx(
        annual.exit_noi / PRICE, abs=1e-9
    )


def test_g26_the_convention_matches_quick_and_detailed() -> None:
    """Year-1 NOI over price -- the same sentence all three modes use
    (D4 Section 20.4). Verified against the Detailed producer's own formula."""

    from anchor.contracts import DetailedOperatingInputs
    from anchor.engine.operating_projection import build_detailed_operating_projection

    detailed = build_detailed_operating_projection(
        DetailedOperatingInputs(
            gross_potential_rent=1200.0,
            other_income=0.0,
            vacancy_credit_loss_pct=0.0,
            property_taxes=0.0,
            insurance=0.0,
            utilities=0.0,
            repairs_maintenance=0.0,
            other_operating_expenses=0.0,
            management_fee_pct=0.0,
            revenue_growth=0.0,
            expense_growth=0.0,
        ),
        hold_period=1,
        purchase_price=PRICE,
    )
    lease_level = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, noi=[100.0] * 24), purchase_price=PRICE
    )

    assert detailed.noi_by_year[0] == pytest.approx(1200.0, abs=1e-9)
    assert lease_level.noi_by_year[0] == pytest.approx(1200.0, abs=1e-9)
    assert lease_level.going_in_cap_rate.hex() == detailed.going_in_cap_rate.hex()


def test_g27_a_negative_year_one_noi_gives_a_negative_going_in_cap() -> None:
    """Reported as modeled. Unlike ``exit_noi`` it capitalizes nothing, so
    nothing is refused."""

    monthly = monthly_projection(hold_period=1, noi=[-100.0] * 12 + [100.0] * 12)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.going_in_cap_rate == pytest.approx(-0.12, abs=1e-12)


def test_a_zero_year_one_noi_gives_a_zero_going_in_cap() -> None:
    annual = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, noi=[0.0] * 12 + [100.0] * 12),
        purchase_price=PRICE,
    )

    assert annual.going_in_cap_rate == 0.0


@pytest.mark.parametrize("price", [0.0, -1.0])
def test_a_non_positive_purchase_price_is_refused(price: float) -> None:
    monthly = monthly_projection(hold_period=1, noi=[100.0] * 24)

    with pytest.raises(LeaseValidationError) as raised:
        aggregate_monthly_to_annual(monthly, purchase_price=price)

    assert LeaseIssueCode.PURCHASE_PRICE_OUT_OF_DOMAIN in [
        issue.code for issue in raised.value.result.errors
    ]


@pytest.mark.parametrize("price", [float("nan"), float("inf")])
def test_a_non_finite_purchase_price_is_refused(price: float) -> None:
    monthly = monthly_projection(hold_period=1, noi=[100.0] * 24)

    with pytest.raises(LeaseValidationError) as raised:
        aggregate_monthly_to_annual(monthly, purchase_price=price)

    assert LeaseIssueCode.NON_FINITE_VALUE in [
        issue.code for issue in raised.value.result.errors
    ]


# =============================================================================
# G25 -- downstream compatibility
# =============================================================================


def test_g25_the_annual_projection_satisfies_operating_projection_like() -> None:
    """Structurally, without importing the Protocol and without fabricating a
    single Detailed-only field."""

    annual = aggregate_monthly_to_annual(
        monthly_projection(hold_period=2, noi=[100.0] * 36), purchase_price=PRICE
    )

    def read(projection: OperatingProjectionLike) -> tuple[object, float, float]:
        return (
            projection.noi_by_year,
            projection.exit_noi,
            projection.going_in_cap_rate,
        )

    noi_by_year, exit_noi, going_in = read(annual)
    assert noi_by_year == (1200.0, 1200.0)
    assert exit_noi == pytest.approx(1200.0, abs=1e-9)
    assert going_in == pytest.approx(0.12, abs=1e-12)


def test_g25_the_three_protocol_fields_have_the_right_shapes() -> None:
    annual = aggregate_monthly_to_annual(
        monthly_projection(hold_period=3, noi=[1.0] * 48), purchase_price=PRICE
    )

    assert isinstance(annual.noi_by_year, tuple)
    assert len(annual.noi_by_year) == 3
    assert isinstance(annual.exit_noi, float)
    assert isinstance(annual.going_in_cap_rate, float)


def test_g25_no_detailed_only_field_is_fabricated() -> None:
    """Lease-Level has no GPR, no blended vacancy factor and no generic revenue
    growth, and invents none to look like ``OperatingProjection``."""

    fields = {field.name for field in dataclasses.fields(AnnualOperatingProjection)}

    for forbidden in (
        "gross_potential_rent_by_year",
        "vacancy_credit_loss_by_year",
        "revenue_growth",
        "occupancy",
    ):
        assert forbidden not in fields


def test_the_annual_contract_declares_no_later_gate_concept() -> None:
    fields = {field.name for field in dataclasses.fields(AnnualOperatingProjection)}

    for forbidden in (
        "capex_by_year",
        "capex",
        "exit_value",
        "disposition_costs",
        "net_sale_proceeds",
        "annual_debt_service",
        "dscr_by_year",
        "unlevered_irr",
        "levered_irr",
        "equity_multiple",
        "market_rent_psf_at_year_end",
    ):
        assert forbidden not in fields, f"AnnualOperatingProjection declares {forbidden}"


def test_every_annual_state_field_name_declares_its_semantics() -> None:
    """G-M6: a snapshot ends ``_at_year_end``, an average begins ``average_``.
    No ambiguous ``occupancy_by_year`` exists."""

    fields = [field.name for field in dataclasses.fields(AnnualOperatingProjection)]
    state = [
        name
        for name in fields
        if "occupancy" in name or "area" in name
    ]

    assert state
    for name in state:
        assert name.startswith("average_") or name.endswith("_at_year_end"), name


# =============================================================================
# Canonical-partition refusals
# =============================================================================


def test_a_hold_period_that_disagrees_with_the_month_count_is_refused() -> None:
    monthly = monthly_projection(hold_period=1, noi=[100.0] * 24)

    result = validate_annual_adapter_inputs(
        monthly, hold_period=2, purchase_price=PRICE
    )

    assert LeaseIssueCode.PROJECTION_NOT_CANONICAL in [
        issue.code for issue in result.errors
    ]


def test_a_forward_flag_that_disagrees_with_the_partition_is_refused() -> None:
    """A projection whose flags say the sale is elsewhere would still slice
    cleanly and would silently move the sale date."""

    monthly = monthly_projection(hold_period=1, noi=[100.0] * 24)
    broken_months = tuple(
        dataclasses.replace(month, is_forward_exit_month=not month.is_forward_exit_month)
        for month in monthly.months
    )
    broken = dataclasses.replace(monthly, months=broken_months)

    result = validate_annual_adapter_inputs(
        broken, hold_period=1, purchase_price=PRICE
    )

    assert LeaseIssueCode.PROJECTION_NOT_CANONICAL in [
        issue.code for issue in result.errors
    ]


def test_the_hold_period_is_read_from_authoritative_metadata() -> None:
    """Not guessed as ``len(months) / 12``, which would treat the forward year
    as a hold year."""

    monthly = monthly_projection(hold_period=2, noi=[100.0] * 36)

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert monthly.recovery_schedule.hold_period == 2
    assert len(annual.noi_by_year) == 2
    assert len(annual.noi_by_year) != len(monthly.months) // 12


def test_validation_issue_ordering_is_deterministic() -> None:
    monthly = monthly_projection(hold_period=1, noi=[100.0] * 24)

    result = validate_annual_adapter_inputs(
        monthly, hold_period=2, purchase_price=-1.0
    )

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.PROJECTION_NOT_CANONICAL,
        LeaseIssueCode.PURCHASE_PRICE_OUT_OF_DOMAIN,
    ]


def test_a_valid_adapter_input_produces_no_issues() -> None:
    monthly = monthly_projection(hold_period=2, noi=[100.0] * 36)

    result = validate_annual_adapter_inputs(
        monthly, hold_period=2, purchase_price=PRICE
    )

    assert result.is_valid
    assert not result.issues


# =============================================================================
# G28 -- determinism and shape
# =============================================================================


def test_g28_repeated_builds_are_equal_and_bit_identical() -> None:
    monthly = monthly_projection(
        hold_period=2,
        noi=[float(index) * 1.1 for index in range(36)],
        ti=[float(index) * 0.3 for index in range(36)],
    )

    first = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)
    second = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert first == second
    assert hexes(first.noi_by_year) == hexes(second.noi_by_year)
    assert first.exit_noi.hex() == second.exit_noi.hex()


def test_g28_the_annual_projection_is_immutable() -> None:
    annual = aggregate_monthly_to_annual(
        monthly_projection(hold_period=1, noi=[1.0] * 24), purchase_price=PRICE
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        annual.noi_by_year = ()  # type: ignore[misc]


def test_g28_every_annual_series_is_a_tuple() -> None:
    annual = aggregate_monthly_to_annual(
        monthly_projection(hold_period=2, noi=[1.0] * 36), purchase_price=PRICE
    )

    for field in dataclasses.fields(AnnualOperatingProjection):
        value = getattr(annual, field.name)
        if field.name in {"exit_noi", "going_in_cap_rate", "exit_window_leasing_costs"}:
            assert isinstance(value, float), field.name
        else:
            assert isinstance(value, tuple), field.name


def test_the_adapter_takes_only_a_projection_and_a_price() -> None:
    import inspect

    parameters = set(inspect.signature(aggregate_monthly_to_annual).parameters)

    assert parameters == {"monthly", "purchase_price"}
    for forbidden in ("terms", "hold_period", "exit_cap_rate", "months", "suites"):
        assert forbidden not in parameters


def test_annual_flow_order_is_chronological() -> None:
    """Year 1 first, Year H last -- never sorted by amount."""

    monthly = monthly_projection(
        hold_period=3, noi=[300.0] * 12 + [100.0] * 12 + [200.0] * 12 + [0.0] * 12
    )

    annual = aggregate_monthly_to_annual(monthly, purchase_price=PRICE)

    assert annual.noi_by_year == (3600.0, 1200.0, 2400.0)
