"""D5.6 -- the two result surfaces the UI renders reconcile with each other.

**Why this file exists when D4.4 already has 59 tests.**
``tests/test_leasing_d4_4_annual_adapter.py`` proves the adapter's rules on
hand-built projections: that a flow line is its monthly sum, that TI and LC are,
that the exit split falls at the right month. That is unit coverage of the
reducer.

This is the *surface* coverage D5.6 needs, and it is a different question: for a
real analysis run end to end through
``analyze_lease_level_acquisition_with_projection`` -- the exact envelope the API
serialises and the UI renders -- does every line D5.6 puts on screen agree
between the monthly view and the annual view? The frontend renders each from its
own authoritative array and never derives one from the other, so if the two ever
disagreed the analyst would see two different truths depending on a toggle. That
is the risk this file closes.

Nothing here is a new rule. Each assertion restates the shipped convention --
flows sum, states average or snapshot -- against the shipped output.
"""

from __future__ import annotations

from datetime import date

import pytest

from anchor.analysis import analyze_lease_level_acquisition_with_projection
from anchor.contracts import AcquisitionTerms
from anchor.leasing import (
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    Suite,
)

MONTHS_PER_YEAR = 12
HOLD_PERIOD = 5

TERMS = AcquisitionTerms(
    purchase_price=6_000_000.0,
    hold_period=HOLD_PERIOD,
    exit_cap_rate=0.065,
    ltv=0.5,
    interest_rate=0.055,
    amortization=30,
    acquisition_cost_pct=0.0,
    financing_fee_pct=0.0,
    disposition_cost_pct=0.0,
    annual_capex_reserve=50_000.0,
    io_period=0,
)

PROPERTY = LeaseLevelPropertyInputs(
    analysis_start_date=date(2027, 1, 1), rentable_area_sf=20_000.0
)

OPERATING = LeaseLevelOperatingInputs(
    other_income=50_000.0,
    other_income_growth=0.02,
    credit_loss_pct=0.01,
    property_taxes=200_000.0,
    insurance=30_000.0,
    utilities=60_000.0,
    repairs_maintenance=40_000.0,
    other_operating_expenses=20_000.0,
    management_fee_pct=0.03,
    expense_growth=0.03,
    recoverable_expense_ratio=0.8,
)

MARKET = MarketLeasingAssumptions(
    market_rent_psf=30.0,
    market_rent_growth=0.03,
    renewal_rent_psf=None,
    renewal_rent_spread=0.0,
    renewal_term_months=60,
    successor_escalation_pct=0.03,
    renewal_downtime_months=2.0,
    renewal_free_rent_months=1.0,
    new_term_months=60,
    new_downtime_months=6.0,
    new_free_rent_months=2.0,
    renewal_ti_psf=20.0,
    new_ti_psf=40.0,
    leasing_commission_method=LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
    renewal_lc_pct=0.03,
    new_lc_pct=0.06,
    renewal_probability=0.7,
    renewal_lease_type=LeaseType.NNN,
    renewal_recovery_basis=None,
    renewal_expense_stop_psf=None,
    new_lease_type=LeaseType.NNN,
    new_recovery_basis=None,
    new_expense_stop_psf=None,
)

# A rent roll with something actually happening in it: one lease that expires
# mid-hold and rolls over (so TI and LC are non-zero and spiky), and one suite
# that starts vacant and leases up (so occupancy moves).
SUITES = (
    Suite(suite_id="100", suite_area_sf=12_000.0),
    Suite(
        suite_id="200",
        suite_area_sf=8_000.0,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP,
            initial_lease_up_months=6.0,
        ),
    ),
)

LEASES = (
    Lease(
        lease_id="L-100",
        suite_id="100",
        leased_area_sf=12_000.0,
        rent_commencement_date=date(2024, 1, 1),
        lease_expiration_date=date(2029, 6, 30),
        base_rent_psf=28.0,
        escalation_pct=0.03,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        lease_type=LeaseType.NNN,
        tenant_name="Anchor Tenant",
    ),
)


@pytest.fixture(scope="module")
def analysis():
    return analyze_lease_level_acquisition_with_projection(
        TERMS,
        PROPERTY,
        SUITES,
        LEASES,
        market_leasing=MARKET,
        operating_inputs=OPERATING,
    )


def hold_year_slice(monthly: tuple[float, ...], year: int) -> tuple[float, ...]:
    """The twelve canonical months of one hold year, 1-indexed."""

    start = (year - 1) * MONTHS_PER_YEAR
    return monthly[start : start + MONTHS_PER_YEAR]


# =============================================================================
# 1. The fixture is worth reconciling
# =============================================================================


def test_the_fixture_exercises_rollover_and_lease_up(analysis) -> None:
    """A reconciliation over an all-zero projection proves nothing."""

    monthly = analysis.monthly_projection
    assert any(value > 0 for value in monthly.tenant_improvements)
    assert any(value > 0 for value in monthly.leasing_commissions)
    # Occupancy genuinely moves: the vacant suite lets, and the lease rolls.
    assert len(set(monthly.physical_occupancy)) > 1
    assert len(monthly.months) == MONTHS_PER_YEAR * HOLD_PERIOD + MONTHS_PER_YEAR


# =============================================================================
# 2. Every flow line the UI renders sums from months to its year
# =============================================================================

FLOW_LINES = [
    ("contractual_base_rent", "contractual_base_rent_by_year"),
    ("free_rent", "free_rent_by_year"),
    ("cash_base_rent", "cash_base_rent_by_year"),
    ("expense_recovery", "expense_recovery_by_year"),
    ("other_income", "other_income_by_year"),
    ("credit_loss", "credit_loss_by_year"),
    ("effective_gross_income", "effective_gross_income_by_year"),
    ("property_taxes", "property_taxes_by_year"),
    ("insurance", "insurance_by_year"),
    ("utilities", "utilities_by_year"),
    ("repairs_maintenance", "repairs_maintenance_by_year"),
    ("other_operating_expenses", "other_operating_expenses_by_year"),
    ("fixed_operating_expenses", "fixed_operating_expenses_by_year"),
    ("management_fee", "management_fee_by_year"),
    ("total_operating_expenses", "total_operating_expenses_by_year"),
    ("noi", "noi_by_year"),
    ("tenant_improvements", "tenant_improvements_by_year"),
    ("leasing_commissions", "leasing_commissions_by_year"),
]


@pytest.mark.parametrize("monthly_field,annual_field", FLOW_LINES)
def test_every_rendered_flow_line_reconciles(analysis, monthly_field, annual_field) -> None:
    """The Monthly and Annual views must not tell the analyst two stories.

    Each is rendered from its own array with no client-side derivation, so this
    is what makes the toggle safe: for every year, the twelve monthly values sum
    to the annual value the other view shows.
    """

    monthly = getattr(analysis.monthly_projection, monthly_field)
    annual = getattr(analysis.annual_projection, annual_field)

    assert len(annual) == HOLD_PERIOD
    for year in range(1, HOLD_PERIOD + 1):
        assert sum(hold_year_slice(monthly, year)) == pytest.approx(
            annual[year - 1], rel=1e-9, abs=1e-6
        ), f"{annual_field} year {year}"


def test_the_rendered_flow_list_covers_every_annual_flow_field(analysis) -> None:
    """A line added to the contract must not escape the check above.

    Driven off the annual dataclass rather than a hand list: the only
    `*_by_year` fields absent from `FLOW_LINES` are the occupancy states, which
    reconcile by a different rule and are checked separately.
    """

    import dataclasses

    annual_flow_fields = {
        field.name
        for field in dataclasses.fields(analysis.annual_projection)
        if field.name.endswith("_by_year")
    }
    covered = {annual for _, annual in FLOW_LINES}
    assert annual_flow_fields == covered


# =============================================================================
# 3. Occupancy follows its own rule, and the UI labels it accordingly
# =============================================================================


def test_average_occupancy_is_the_mean_of_the_year(analysis) -> None:
    monthly = analysis.monthly_projection.physical_occupancy
    annual = analysis.annual_projection.average_physical_occupancy_over_year

    for year in range(1, HOLD_PERIOD + 1):
        window = hold_year_slice(monthly, year)
        assert annual[year - 1] == pytest.approx(
            sum(window) / MONTHS_PER_YEAR, rel=1e-9
        ), f"average occupancy year {year}"


@pytest.mark.parametrize(
    "monthly_field,annual_field",
    [
        ("physical_occupancy", "physical_occupancy_at_year_end"),
        ("occupied_area_sf", "occupied_area_at_year_end"),
        ("vacant_area_sf", "vacant_area_at_year_end"),
    ],
)
def test_year_end_state_is_the_final_month_of_the_year(
    analysis, monthly_field, annual_field
) -> None:
    monthly = getattr(analysis.monthly_projection, monthly_field)
    annual = getattr(analysis.annual_projection, annual_field)

    for year in range(1, HOLD_PERIOD + 1):
        assert annual[year - 1] == pytest.approx(
            hold_year_slice(monthly, year)[-1], rel=1e-9
        ), f"{annual_field} year {year}"


def test_average_and_year_end_occupancy_actually_differ(analysis) -> None:
    """The reason the UI must label them separately.

    If they were interchangeable the distinction would be pedantry. On a roll
    with a lease-up they are not: a year that ends full can have averaged far
    less, and quoting one as the other misstates the year.
    """

    average = analysis.annual_projection.average_physical_occupancy_over_year
    year_end = analysis.annual_projection.physical_occupancy_at_year_end
    assert any(a != pytest.approx(b) for a, b in zip(average, year_end))


# =============================================================================
# 4. Exit NOI is the forward window, not the last hold year
# =============================================================================


def test_exit_noi_is_the_twelve_forward_months(analysis) -> None:
    """D4's rule, restated against the surface the UI reads.

    The summary card shows `results.exit_noi` and says it covers the twelve
    months after the hold. This proves that claim.
    """

    monthly = analysis.monthly_projection
    forward = [
        value
        for value, month in zip(monthly.noi, monthly.months)
        if month.is_forward_exit_month
    ]
    assert len(forward) == MONTHS_PER_YEAR
    assert analysis.annual_projection.exit_noi == pytest.approx(sum(forward), rel=1e-9)
    assert analysis.results.exit_noi == pytest.approx(sum(forward), rel=1e-9)


def test_exit_noi_is_not_the_final_hold_year_noi(analysis) -> None:
    """The mutant the UI could otherwise ship without anyone noticing.

    Reading the last column of the annual NOI row is the obvious wrong way to
    fill an "Exit NOI" tile, and on a growing rent roll it produces a plausible
    number. These two genuinely differ.
    """

    final_hold_year = analysis.annual_projection.noi_by_year[-1]
    assert analysis.results.exit_noi != pytest.approx(final_hold_year, rel=1e-6)


def test_the_forward_window_is_excluded_from_every_hold_year(analysis) -> None:
    """A forward month must not leak into the annual table the UI renders."""

    monthly = analysis.monthly_projection
    hold_months = [
        value
        for value, month in zip(monthly.noi, monthly.months)
        if not month.is_forward_exit_month
    ]
    assert len(hold_months) == MONTHS_PER_YEAR * HOLD_PERIOD
    assert sum(hold_months) == pytest.approx(
        sum(analysis.annual_projection.noi_by_year), rel=1e-9
    )


def test_exit_window_leasing_costs_are_disclosed_not_deducted(analysis) -> None:
    """The summary shows this figure and says it is excluded. Proving it."""

    monthly = analysis.monthly_projection
    forward_ti_lc = sum(
        ti + lc
        for ti, lc, month in zip(
            monthly.tenant_improvements, monthly.leasing_commissions, monthly.months
        )
        if month.is_forward_exit_month
    )
    assert analysis.annual_projection.exit_window_leasing_costs == pytest.approx(
        forward_ti_lc, rel=1e-9
    )
    # And none of it reached the hold-period arrays the annual table shows.
    assert sum(analysis.annual_projection.tenant_improvements_by_year) + sum(
        analysis.annual_projection.leasing_commissions_by_year
    ) == pytest.approx(
        sum(
            ti + lc
            for ti, lc, month in zip(
                monthly.tenant_improvements, monthly.leasing_commissions, monthly.months
            )
            if not month.is_forward_exit_month
        ),
        rel=1e-9,
    )


# =============================================================================
# 5. The envelope carries what D5.6 renders, and no monthly debt or capex
# =============================================================================


def test_the_headline_metrics_the_summary_renders_are_all_present(analysis) -> None:
    results = analysis.results
    for field in (
        "levered_irr",
        "unlevered_irr",
        "equity_multiple",
        "going_in_cap_rate",
        "headline_dscr",
        "min_dscr",
        "year_1_debt_yield",
        "loan_amount",
        "initial_equity",
        "acquisition_costs",
        "financing_fee",
        "exit_noi",
        "exit_value",
        "disposition_costs",
        "net_sale_proceeds",
    ):
        assert hasattr(results, field), field


def test_there_is_no_monthly_debt_or_capex_series(analysis) -> None:
    """Why the monthly view shows neither.

    Debt service and the CapEx reserve are annual on the authoritative result;
    the monthly projection carries no such series. The UI therefore shows them
    on the annual view only. Producing a monthly figure would mean dividing an
    annual one by twelve, which is a schedule the engine never computed.
    """

    import dataclasses

    monthly_fields = {field.name for field in dataclasses.fields(analysis.monthly_projection)}
    assert not any("debt" in name for name in monthly_fields)
    assert not any("capex" in name for name in monthly_fields)

    # They exist annually, which is what the annual view renders.
    assert len(analysis.results.annual_debt_service) >= HOLD_PERIOD
    assert len(analysis.results.capex_by_year) >= HOLD_PERIOD


def test_going_in_cap_rate_agrees_across_both_surfaces(analysis) -> None:
    """The summary reads it off `results`; the annual projection carries it too.

    They must be the same number, or the tile and the statement would disagree.
    """

    assert analysis.results.going_in_cap_rate == pytest.approx(
        analysis.annual_projection.going_in_cap_rate, rel=1e-12
    )
