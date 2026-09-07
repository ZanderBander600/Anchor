"""Sprint D Gate D4.5B -- Lease-Level acquisition orchestration, end to end.

Governed by
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 5.1, 21.6 and 27.

Every case here starts from **raw Lease-Level inputs** -- a property, suites,
leases, market assumptions and operating assumptions -- and runs the complete
public path. Nothing is hand-assembled from intermediate D4 schedules, so a
break anywhere in the D1-D4.5A chain surfaces here.

The claims that fail silently if wrong:

- one authoritative chain per suite, and every suite present;
- **one** recoverable expense pool for the whole analysis;
- the annual projection handed to the engine is the one returned to the caller;
- hold-period TI/LC reach ``AcquisitionResults`` unchanged, and forward-window
  TI/LC reach nothing;
- a non-positive forward exit NOI stops the analysis **before** the shared
  engine is touched.
"""

from __future__ import annotations

import itertools
from datetime import date

import pytest

from anchor.analysis import analyze_lease_level_acquisition_with_projection
from anchor.analysis.contracts import LeaseLevelAcquisitionResults
from anchor.contracts import AcquisitionTerms
from anchor.engine.contracts import AcquisitionResults
from anchor.leasing import (
    AnnualOperatingProjection,
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseIssueCode,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseType,
    LeasingCommissionMethod,
    LeaseValidationError,
    MarketLeasingAssumptions,
    MonthlyPropertyProjection,
    RecoveryBasis,
    Suite,
)


JAN = date(2027, 1, 1)
AREA = 100_000.0
PRICE = 40_000_000.0
HOLD = 3


# =============================================================================
# Fixtures -- raw inputs only
# =============================================================================


def terms(**overrides: object) -> AcquisitionTerms:
    base: dict[str, object] = {
        "purchase_price": PRICE,
        "hold_period": HOLD,
        "exit_cap_rate": 0.065,
        "ltv": 0.60,
        "interest_rate": 0.05,
        "amortization": 30,
        "acquisition_cost_pct": 0.02,
        "financing_fee_pct": 0.01,
        "disposition_cost_pct": 0.015,
        "annual_capex_reserve": 0.0,
        "io_period": 0,
    }
    base.update(overrides)
    return AcquisitionTerms(**base)  # type: ignore[arg-type]


def property_inputs(area: float = AREA) -> LeaseLevelPropertyInputs:
    return LeaseLevelPropertyInputs(analysis_start_date=JAN, rentable_area_sf=area)


def market(**overrides: object) -> MarketLeasingAssumptions:
    base: dict[str, object] = {
        "market_rent_psf": 30.0,
        "market_rent_growth": 0.03,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.0,
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
        "renewal_probability": 0.7,
        "renewal_lease_type": LeaseType.NNN,
        "renewal_recovery_basis": None,
        "renewal_expense_stop_psf": None,
        "new_lease_type": LeaseType.NNN,
        "new_recovery_basis": None,
        "new_expense_stop_psf": None,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)  # type: ignore[arg-type]


def operating(**overrides: object) -> LeaseLevelOperatingInputs:
    """Fixed opex totals 1,200,000/yr -> 100,000/month in Year 1."""

    base: dict[str, object] = {
        "other_income": 120_000.0,
        "other_income_growth": 0.03,
        "credit_loss_pct": 0.0,
        "property_taxes": 600_000.0,
        "insurance": 120_000.0,
        "utilities": 240_000.0,
        "repairs_maintenance": 180_000.0,
        "other_operating_expenses": 60_000.0,
        "management_fee_pct": 0.03,
        "expense_growth": 0.03,
        "recoverable_expense_ratio": 1.0,
    }
    base.update(overrides)
    return LeaseLevelOperatingInputs(**base)  # type: ignore[arg-type]


def occupied_lease(
    suite: Suite,
    *,
    lease_type: LeaseType = LeaseType.NNN,
    end: date = date(2035, 12, 31),
    base_rent_psf: float = 30.0,
    recovery_basis: RecoveryBasis | None = None,
    expense_stop_psf: float | None = None,
) -> Lease:
    return Lease(
        lease_id=f"L-{suite.suite_id}",
        suite_id=suite.suite_id,
        leased_area_sf=suite.suite_area_sf,
        rent_commencement_date=date(2025, 1, 1),
        lease_expiration_date=end,
        base_rent_psf=base_rent_psf,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=lease_type,
        recovery_basis=recovery_basis,
        expense_stop_psf=expense_stop_psf,
    )


def vacant_suite(
    suite_id: str,
    area: float,
    *,
    strategy: InitialVacancyStrategy = InitialVacancyStrategy.MARKET_LEASE_UP,
    lease_up: float | None = 0.0,
) -> Suite:
    return Suite(
        suite_id=suite_id,
        suite_area_sf=area,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=strategy, initial_lease_up_months=lease_up
        ),
    )


def run(suites, leases, *, deal=None, mkt=None, ops=None):
    return analyze_lease_level_acquisition_with_projection(
        deal or terms(),
        property_inputs(),
        suites,
        leases,
        market_leasing=mkt or market(),
        operating_inputs=ops or operating(),
    )


def hexes(values):
    return [None if v is None else v.hex() for v in values]


# =============================================================================
# Golden 1 -- simple occupied NNN, hand-reconciled end to end
# =============================================================================


def _simple_nnn():
    suite = Suite(suite_id="A", suite_area_sf=AREA)
    return [suite], [occupied_lease(suite)]


def test_golden1_monthly_statement_reconciles_by_hand() -> None:
    """100,000 SF at $30.00/SF/year is 250,000/month. Fixed opex 1,200,000/year
    is 100,000/month. A 100%-recoverable NNN property whose single tenant holds
    the whole building recovers the whole pool. Other income 120,000/year is
    10,000/month."""

    suites, leases = _simple_nnn()
    monthly = run(suites, leases).monthly_projection

    assert monthly.cash_base_rent[0] == pytest.approx(250_000.0, abs=1e-9)
    assert monthly.expense_recovery[0] == pytest.approx(100_000.0, abs=1e-9)
    assert monthly.other_income[0] == pytest.approx(10_000.0, abs=1e-9)
    assert monthly.effective_gross_income[0] == pytest.approx(360_000.0, abs=1e-9)
    assert monthly.fixed_operating_expenses[0] == pytest.approx(100_000.0, abs=1e-9)
    assert monthly.management_fee[0] == pytest.approx(10_800.0, abs=1e-9)
    assert monthly.noi[0] == pytest.approx(249_200.0, abs=1e-9)


def test_golden1_annual_noi_is_the_monthly_sum() -> None:
    suites, leases = _simple_nnn()
    out = run(suites, leases)

    assert out.annual_projection.noi_by_year[0] == pytest.approx(
        sum(out.monthly_projection.noi[:12]), abs=1e-9
    )


def test_golden1_going_in_cap_is_year_one_noi_over_price() -> None:
    suites, leases = _simple_nnn()
    out = run(suites, leases)

    assert out.annual_projection.going_in_cap_rate == pytest.approx(
        out.annual_projection.noi_by_year[0] / PRICE, abs=1e-12
    )


def test_golden1_exit_noi_is_the_forward_twelve_months() -> None:
    suites, leases = _simple_nnn()
    out = run(suites, leases)

    forward = out.monthly_projection.noi[12 * HOLD :]
    assert len(forward) == 12
    assert out.annual_projection.exit_noi == pytest.approx(sum(forward), abs=1e-6)


def test_golden1_exit_value_is_forward_noi_over_the_cap_rate() -> None:
    suites, leases = _simple_nnn()
    out = run(suites, leases)

    assert out.results.exit_value == pytest.approx(
        out.annual_projection.exit_noi / 0.065, abs=1e-6
    )


def test_golden1_dscr_uses_annual_noi_over_annual_debt_service() -> None:
    suites, leases = _simple_nnn()
    out = run(suites, leases)

    for year, dscr in enumerate(out.results.dscr_by_year):
        assert dscr == pytest.approx(
            out.annual_projection.noi_by_year[year]
            / out.results.annual_debt_service[year],
            abs=1e-12,
        )


def test_golden1_returns_are_produced_and_defined() -> None:
    suites, leases = _simple_nnn()
    out = run(suites, leases)

    assert out.results.unlevered_irr is not None
    assert out.results.levered_irr is not None
    assert out.results.equity_multiple is not None
    assert out.results.noi_by_year == out.annual_projection.noi_by_year


# =============================================================================
# Golden 2 -- Gross
# =============================================================================


def test_golden2_a_gross_property_recovers_nothing() -> None:
    """The landlord bears the whole expense; the pipeline still completes."""

    suite = Suite(suite_id="A", suite_area_sf=AREA)
    out = run([suite], [occupied_lease(suite, lease_type=LeaseType.GROSS)])

    assert out.monthly_projection.expense_recovery == tuple(
        0.0 for _ in out.monthly_projection.months
    )
    assert out.monthly_projection.fixed_operating_expenses[0] == pytest.approx(
        100_000.0, abs=1e-9
    )
    # EGI = 250,000 cash + 0 recovery + 10,000 other income.
    assert out.monthly_projection.effective_gross_income[0] == pytest.approx(
        260_000.0, abs=1e-9
    )
    assert out.monthly_projection.noi[0] == pytest.approx(
        260_000.0 - 100_000.0 - 7_800.0, abs=1e-9
    )
    assert out.results.exit_value > 0.0


def test_golden2_gross_noi_is_below_the_nnn_equivalent() -> None:
    suite = Suite(suite_id="A", suite_area_sf=AREA)
    nnn = run([suite], [occupied_lease(suite, lease_type=LeaseType.NNN)])
    gross = run([suite], [occupied_lease(suite, lease_type=LeaseType.GROSS)])

    assert gross.annual_projection.noi_by_year[0] < nnn.annual_projection.noi_by_year[0]


# =============================================================================
# Golden 3 -- the mixed property
# =============================================================================


def _mixed():
    a = Suite(suite_id="A", suite_area_sf=40_000.0)
    b = vacant_suite("B", 30_000.0, lease_up=3.0)
    c = vacant_suite(
        "C", 20_000.0, strategy=InitialVacancyStrategy.HOLD_VACANT, lease_up=None
    )
    d = Suite(suite_id="D", suite_area_sf=10_000.0)
    leases = [
        occupied_lease(a, lease_type=LeaseType.NNN),
        occupied_lease(d, lease_type=LeaseType.GROSS, end=date(2029, 6, 30)),
    ]
    mkt = market(
        new_lease_type=LeaseType.MODIFIED_GROSS,
        new_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        new_expense_stop_psf=6.0,
        renewal_lease_type=LeaseType.NNN,
    )
    return [a, b, c, d], leases, mkt


def test_golden3_the_mixed_property_completes_end_to_end() -> None:
    suites, leases, mkt = _mixed()

    out = run(suites, leases, mkt=mkt)

    assert isinstance(out, LeaseLevelAcquisitionResults)
    assert isinstance(out.monthly_projection, MonthlyPropertyProjection)
    assert isinstance(out.annual_projection, AnnualOperatingProjection)
    assert isinstance(out.results, AcquisitionResults)
    assert out.annual_projection.exit_noi > 0.0


def test_golden3_every_suite_is_represented_exactly_once() -> None:
    suites, leases, mkt = _mixed()

    out = run(suites, leases, mkt=mkt)
    operating_schedule = out.monthly_projection.operating_schedule
    recovery_schedule = out.monthly_projection.recovery_schedule

    assert [p.suite_id for p in operating_schedule.suite_projections] == [
        "A",
        "B",
        "C",
        "D",
    ]
    assert [p.suite_id for p in recovery_schedule.suite_projections] == [
        "A",
        "B",
        "C",
        "D",
    ]


def test_golden3_occupancy_is_area_weighted_not_a_suite_average() -> None:
    """Month 1: A (40k) and D (10k) occupied; B (30k) in lease-up; C (20k)
    deliberately empty. 50,000 / 100,000 = 0.50 -- a suite average would be
    0.50 here too by coincidence, so month 4 is checked as well once B lets."""

    suites, leases, mkt = _mixed()
    monthly = run(suites, leases, mkt=mkt).monthly_projection

    assert monthly.occupied_area_sf[0] == pytest.approx(50_000.0, abs=1e-9)
    assert monthly.physical_occupancy[0] == pytest.approx(0.50, abs=1e-12)
    # B lets from month 4: 80,000 / 100,000 = 0.80. A suite mean would be 0.75.
    assert monthly.occupied_area_sf[3] == pytest.approx(80_000.0, abs=1e-9)
    assert monthly.physical_occupancy[3] == pytest.approx(0.80, abs=1e-12)
    assert monthly.physical_occupancy[3] != pytest.approx(0.75, abs=1e-6)


def test_golden3_area_reconciles_in_every_month() -> None:
    suites, leases, mkt = _mixed()
    monthly = run(suites, leases, mkt=mkt).monthly_projection

    for index in range(len(monthly.months)):
        assert monthly.occupied_area_sf[index] + monthly.vacant_area_sf[
            index
        ] == pytest.approx(AREA, abs=1e-9)


def test_golden3_fixed_expenses_never_scale_with_occupancy() -> None:
    suites, leases, mkt = _mixed()
    monthly = run(suites, leases, mkt=mkt).monthly_projection

    assert monthly.fixed_operating_expenses[0] == pytest.approx(100_000.0, abs=1e-9)
    assert monthly.fixed_operating_expenses[3] == pytest.approx(100_000.0, abs=1e-9)


# =============================================================================
# Golden 4 / 5 -- initial vacancy and hold-vacant
# =============================================================================


def test_golden4_market_lease_up_preserves_vacancy_then_lets() -> None:
    """Three months genuinely empty, then a market tenant -- priced at the
    market rent of its commencement month, not the analysis start."""

    suite = vacant_suite("A", AREA, lease_up=3.0)

    monthly = run([suite], []).monthly_projection

    assert monthly.cash_base_rent[:3] == (0.0, 0.0, 0.0)
    assert monthly.occupied_area_sf[:3] == (0.0, 0.0, 0.0)
    assert monthly.expense_recovery[:3] == (0.0, 0.0, 0.0)
    assert monthly.cash_base_rent[3] > 0.0
    assert monthly.occupied_area_sf[3] == pytest.approx(AREA, abs=1e-9)


def test_golden4_no_fake_lease_is_created() -> None:
    suite = vacant_suite("A", AREA, lease_up=3.0)

    out = run([suite], [])

    # The rent roll had no lease; the chain is an initial-vacancy chain.
    assert out.monthly_projection.operating_schedule.suite_projections[0].suite_id == "A"
    assert out.annual_projection.noi_by_year[0] < out.annual_projection.noi_by_year[1]


def test_golden4_a_fractional_lease_up_is_carried_through_to_noi() -> None:
    """``L = 0.25`` puts commencement in month 1 with economic responsibility
    ``0.75`` -- and physical occupancy ``1.0``."""

    suite = vacant_suite("A", AREA, lease_up=0.25)

    monthly = run([suite], []).monthly_projection

    assert monthly.contractual_base_rent[0] == pytest.approx(250_000.0, abs=1e-9)
    assert monthly.cash_base_rent[0] == pytest.approx(187_500.0, abs=1e-9)
    assert monthly.physical_occupancy[0] == pytest.approx(1.0, abs=1e-12)


def test_golden5_a_hold_vacant_suite_is_present_and_zero() -> None:
    a = Suite(suite_id="A", suite_area_sf=80_000.0)
    c = vacant_suite(
        "C", 20_000.0, strategy=InitialVacancyStrategy.HOLD_VACANT, lease_up=None
    )

    out = run([a, c], [occupied_lease(a)])
    projections = out.monthly_projection.operating_schedule.suite_projections

    assert [p.suite_id for p in projections] == ["A", "C"]
    hold_vacant = next(p for p in projections if p.suite_id == "C")
    assert hold_vacant.cash_base_rent == tuple(
        0.0 for _ in out.monthly_projection.months
    )
    assert hold_vacant.occupied_area_sf == tuple(
        0.0 for _ in out.monthly_projection.months
    )
    assert out.monthly_projection.physical_occupancy[0] == pytest.approx(0.80, abs=1e-12)


def test_golden5_a_wholly_hold_vacant_property_is_refused_at_the_boundary() -> None:
    """Fixed expenses continue, NOI is negative, the forward NOI is negative --
    and cap-rate valuation is refused rather than producing a negative value."""

    suite = vacant_suite(
        "A", AREA, strategy=InitialVacancyStrategy.HOLD_VACANT, lease_up=None
    )

    with pytest.raises(LeaseValidationError) as raised:
        run([suite], [])

    assert [issue.code for issue in raised.value.result.errors] == [
        LeaseIssueCode.NON_POSITIVE_FORWARD_EXIT_NOI
    ]


# =============================================================================
# Golden 6 / 7 -- hold-period and forward-window leasing costs
# =============================================================================


def _rollover_deal(*, expiry: date, ti_psf: float, lc_pct: float, hold: int = HOLD):
    suite = Suite(suite_id="A", suite_area_sf=AREA)
    lease = occupied_lease(suite, end=expiry)
    mkt = market(
        new_ti_psf=ti_psf,
        renewal_ti_psf=ti_psf,
        new_lc_pct=lc_pct,
        renewal_lc_pct=lc_pct,
        renewal_probability=0.5,
    )
    return [suite], [lease], mkt, terms(hold_period=hold)


def test_golden6_hold_period_leasing_costs_flow_to_the_engine_unchanged() -> None:
    """A rollover inside the hold: the costs appear monthly, aggregate into the
    right hold year, become the operating-capital schedule, and land in
    ``AcquisitionResults`` -- the same numbers throughout."""

    suites, leases, mkt, deal = _rollover_deal(
        expiry=date(2028, 12, 31), ti_psf=25.0, lc_pct=0.05
    )
    out = run(suites, leases, deal=deal, mkt=mkt)

    monthly_ti = sum(out.monthly_projection.tenant_improvements[: 12 * HOLD])
    assert monthly_ti > 0.0
    assert sum(out.annual_projection.tenant_improvements_by_year) == pytest.approx(
        monthly_ti, abs=1e-6
    )
    assert (
        out.results.tenant_improvements_by_year
        == out.annual_projection.tenant_improvements_by_year
    )
    assert (
        out.results.leasing_commissions_by_year
        == out.annual_projection.leasing_commissions_by_year
    )


def test_golden6_leasing_costs_do_not_touch_noi_or_dscr() -> None:
    suites, leases, _, deal = _rollover_deal(
        expiry=date(2028, 12, 31), ti_psf=0.0, lc_pct=0.0
    )
    without = run(
        suites, leases, deal=deal,
        mkt=market(new_ti_psf=0.0, renewal_ti_psf=0.0, new_lc_pct=0.0,
                   renewal_lc_pct=0.0, renewal_probability=0.5),
    )
    loaded = run(
        suites, leases, deal=deal,
        mkt=market(new_ti_psf=25.0, renewal_ti_psf=25.0, new_lc_pct=0.05,
                   renewal_lc_pct=0.05, renewal_probability=0.5),
    )

    assert hexes(without.annual_projection.noi_by_year) == hexes(
        loaded.annual_projection.noi_by_year
    )
    assert without.annual_projection.exit_noi.hex() == (
        loaded.annual_projection.exit_noi.hex()
    )
    assert hexes(without.results.dscr_by_year) == hexes(loaded.results.dscr_by_year)
    assert without.results.exit_value.hex() == loaded.results.exit_value.hex()
    # ... but the owner's cash flow and returns do move.
    assert loaded.results.levered_irr < without.results.levered_irr
    assert loaded.results.equity_multiple < without.results.equity_multiple


def test_golden7_forward_window_leasing_costs_reach_nothing_downstream() -> None:
    """A successor commencing after the sale date. Its rent moves exit NOI; its
    TI and LC move no seller figure at all."""

    suites, leases, mkt, deal = _rollover_deal(
        expiry=date(2030, 4, 30), ti_psf=50.0, lc_pct=0.06
    )
    out = run(suites, leases, deal=deal, mkt=mkt)

    forward_ti = sum(out.monthly_projection.tenant_improvements[12 * HOLD :])
    forward_lc = sum(out.monthly_projection.leasing_commissions[12 * HOLD :])

    assert forward_ti > 0.0, "the forward event did not occur; fixture is wrong"
    assert out.annual_projection.tenant_improvements_by_year == (0.0, 0.0, 0.0)
    assert out.annual_projection.leasing_commissions_by_year == (0.0, 0.0, 0.0)
    assert out.results.tenant_improvements_by_year == (0.0, 0.0, 0.0)
    assert out.results.leasing_commissions_by_year == (0.0, 0.0, 0.0)
    assert out.annual_projection.exit_window_leasing_costs == pytest.approx(
        forward_ti + forward_lc, abs=1e-6
    )


def test_golden8_a_forward_rollover_moves_exit_noi_through_the_monthly_model() -> None:
    """Downtime, free rent, recovery and expense growth in the forward window
    all reach exit NOI because they already reached monthly NOI."""

    suite = Suite(suite_id="A", suite_area_sf=AREA)
    lease = occupied_lease(suite, end=date(2030, 4, 30))
    quiet = market(renewal_probability=1.0, renewal_downtime_months=0.0,
                   renewal_free_rent_months=0.0)
    disrupted = market(renewal_probability=0.0, new_downtime_months=4.0,
                       new_free_rent_months=3.0)

    calm = run([suite], [lease], mkt=quiet)
    rough = run([suite], [lease], mkt=disrupted)

    assert rough.annual_projection.exit_noi < calm.annual_projection.exit_noi
    # Hold-period NOI is identical up to the expiry month, so the difference is
    # genuinely a forward-window effect.
    assert rough.annual_projection.noi_by_year[0] == pytest.approx(
        calm.annual_projection.noi_by_year[0], abs=1e-9
    )
    # And it is never Hold Year H grown.
    assert rough.annual_projection.exit_noi != pytest.approx(
        rough.annual_projection.noi_by_year[-1] * 1.03, abs=1.0
    )


# =============================================================================
# Golden 9 -- the terminal-value boundary
# =============================================================================


def test_golden9_a_negative_exit_noi_is_refused_before_the_engine(monkeypatch) -> None:
    """The engine is never invoked. Proven with a spy on the shared entry
    point."""

    import anchor.analysis.lease_level as orchestrator

    calls: list[object] = []

    def spy(*args, **kwargs):  # pragma: no cover - must never run
        calls.append(args)
        raise AssertionError("the shared acquisition engine was invoked")

    monkeypatch.setattr(
        orchestrator, "analyze_acquisition_from_operating_projection", spy
    )

    suite = vacant_suite(
        "A", AREA, strategy=InitialVacancyStrategy.HOLD_VACANT, lease_up=None
    )
    with pytest.raises(LeaseValidationError) as raised:
        run([suite], [])

    assert not calls
    assert raised.value.result.errors[0].code is (
        LeaseIssueCode.NON_POSITIVE_FORWARD_EXIT_NOI
    )


def test_golden9_calculate_exit_value_is_never_reached(monkeypatch) -> None:
    import anchor.engine.acquisition as engine

    original = engine.calculate_exit_value
    calls: list[object] = []

    def spy(**kwargs):  # pragma: no cover - must never run
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(engine, "calculate_exit_value", spy)

    suite = vacant_suite(
        "A", AREA, strategy=InitialVacancyStrategy.HOLD_VACANT, lease_up=None
    )
    with pytest.raises(LeaseValidationError):
        run([suite], [])

    assert not calls


def test_golden9_a_positive_exit_noi_hands_off_to_the_engine() -> None:
    suites, leases = _simple_nnn()

    out = run(suites, leases)

    assert out.annual_projection.exit_noi > 0.0
    assert out.results.exit_value > 0.0


def test_golden9_negative_hold_year_noi_alone_is_not_refused() -> None:
    """Only the forward NOI used for capitalization is restricted. A property
    that loses money early but recovers by the exit window is analysable."""

    suite = vacant_suite("A", AREA, lease_up=18.0)

    out = run([suite], [])

    assert out.annual_projection.noi_by_year[0] < 0.0
    assert out.annual_projection.exit_noi > 0.0
    assert out.results.exit_value > 0.0


def test_golden10_a_negative_going_in_cap_is_reported_not_refused() -> None:
    suite = vacant_suite("A", AREA, lease_up=18.0)

    out = run([suite], [])

    assert out.annual_projection.going_in_cap_rate < 0.0
    assert out.results.going_in_cap_rate == out.annual_projection.going_in_cap_rate


def test_upstream_errors_surface_before_the_terminal_check() -> None:
    """A malformed rent roll is never reported as a valuation problem."""

    suite = Suite(suite_id="A", suite_area_sf=50_000.0)  # does not reconcile

    with pytest.raises(LeaseValidationError) as raised:
        run([suite], [occupied_lease(suite)])

    codes = [issue.code for issue in raised.value.result.errors]
    assert LeaseIssueCode.NON_POSITIVE_FORWARD_EXIT_NOI not in codes
    assert LeaseIssueCode.RENTABLE_AREA_NOT_RECONCILED in codes


def test_a_vacant_suite_with_no_treatment_is_refused() -> None:
    a = Suite(suite_id="A", suite_area_sf=80_000.0)
    bare = Suite(suite_id="V", suite_area_sf=20_000.0)

    with pytest.raises(LeaseValidationError) as raised:
        run([a, bare], [occupied_lease(a)])

    assert LeaseIssueCode.MISSING_INITIAL_VACANCY_TREATMENT in [
        issue.code for issue in raised.value.result.errors
    ]


def test_two_leases_in_one_suite_are_refused_rather_than_silently_dropped() -> None:
    suite = Suite(suite_id="A", suite_area_sf=AREA)
    first = occupied_lease(suite, end=date(2028, 12, 31))
    second = Lease(
        lease_id="L-A2",
        suite_id="A",
        leased_area_sf=AREA,
        rent_commencement_date=date(2029, 1, 1),
        lease_expiration_date=date(2033, 12, 31),
        base_rent_psf=32.0,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=LeaseType.NNN,
    )

    with pytest.raises(LeaseValidationError) as raised:
        run([suite], [first, second])

    assert LeaseIssueCode.MULTIPLE_KNOWN_LEASES_IN_SUITE in [
        issue.code for issue in raised.value.result.errors
    ]


# =============================================================================
# Golden 11 / 12 -- CapEx and DSCR through the generic channel
# =============================================================================


def test_golden11_capex_and_leasing_costs_both_reduce_owner_cash_flow_once() -> None:
    suites, leases, mkt, _ = _rollover_deal(
        expiry=date(2028, 12, 31), ti_psf=25.0, lc_pct=0.05
    )
    no_capex = run(suites, leases, deal=terms(annual_capex_reserve=0.0), mkt=mkt)
    with_capex = run(
        suites, leases, deal=terms(annual_capex_reserve=100_000.0), mkt=mkt
    )

    assert with_capex.results.capex_by_year == (100_000.0,) * HOLD
    assert (
        with_capex.results.tenant_improvements_by_year
        == no_capex.results.tenant_improvements_by_year
    )
    for year in range(1, HOLD):
        assert with_capex.results.levered_cash_flows[year] == pytest.approx(
            no_capex.results.levered_cash_flows[year] - 100_000.0, abs=1e-6
        )


def test_golden12_dscr_is_unaffected_by_capex_and_leasing_costs() -> None:
    suites, leases, mkt, _ = _rollover_deal(
        expiry=date(2028, 12, 31), ti_psf=25.0, lc_pct=0.05
    )
    lean = run(suites, leases, deal=terms(annual_capex_reserve=0.0), mkt=mkt)
    heavy = run(
        suites, leases, deal=terms(annual_capex_reserve=500_000.0), mkt=mkt
    )

    assert hexes(lean.results.dscr_by_year) == hexes(heavy.results.dscr_by_year)
    assert lean.results.year_1_debt_yield.hex() == heavy.results.year_1_debt_yield.hex()


# =============================================================================
# Traceability, identity and determinism
# =============================================================================


def test_the_returned_annual_projection_is_the_one_the_engine_consumed() -> None:
    suites, leases = _simple_nnn()
    out = run(suites, leases)

    assert out.results.noi_by_year is out.annual_projection.noi_by_year
    assert out.results.exit_noi == out.annual_projection.exit_noi
    assert out.results.going_in_cap_rate == out.annual_projection.going_in_cap_rate


def test_the_monthly_projection_is_the_source_of_the_annual_one() -> None:
    suites, leases = _simple_nnn()
    out = run(suites, leases)

    assert out.annual_projection.noi_by_year[0] == pytest.approx(
        sum(out.monthly_projection.noi[:12]), abs=1e-9
    )
    assert out.monthly_projection.months[0].month_start == JAN
    assert len(out.monthly_projection.months) == 12 * HOLD + 12


def test_exactly_one_recoverable_pool_backs_the_whole_analysis(monkeypatch) -> None:
    """A four-suite property builds the pool **once**, and every suite's
    recovery consumes that one object.

    Per-suite pools would still produce plausible-looking recoveries here, so
    the count and the object identity are what make the claim falsifiable.
    """

    import anchor.analysis.lease_level as orchestrator

    pools: list[object] = []
    original_build = orchestrator.build_recoverable_expense_pool

    def counting_build(*args, **kwargs):
        pool = original_build(*args, **kwargs)
        pools.append(pool)
        return pool

    consumed: list[object] = []
    for name in (
        "build_recursive_rollover_recovery",
        "build_initial_vacancy_rollover_recovery",
    ):
        original_recovery = getattr(orchestrator, name)

        def recording(*args, __inner=original_recovery, **kwargs):
            consumed.append(kwargs["pool"])
            return __inner(*args, **kwargs)

        monkeypatch.setattr(orchestrator, name, recording)
    monkeypatch.setattr(
        orchestrator, "build_recoverable_expense_pool", counting_build
    )

    suites, leases, mkt = _mixed()
    out = run(suites, leases, mkt=mkt)

    assert len(pools) == 1, "more than one recoverable expense pool was built"
    assert len(consumed) == 4, "a suite was priced without consuming the pool"
    for pool in consumed:
        assert pool is pools[0]

    # And the pool came from the same expense schedule the projection carries.
    for projection in out.monthly_projection.recovery_schedule.suite_projections:
        assert projection.months is out.monthly_projection.months


def test_repeated_analysis_is_deterministic() -> None:
    suites, leases, mkt = _mixed()

    first = run(suites, leases, mkt=mkt)
    second = run(suites, leases, mkt=mkt)

    assert hexes(first.annual_projection.noi_by_year) == hexes(
        second.annual_projection.noi_by_year
    )
    assert first.annual_projection.exit_noi.hex() == (
        second.annual_projection.exit_noi.hex()
    )
    assert first.results.levered_irr == second.results.levered_irr


def test_suite_and_lease_order_do_not_change_the_result() -> None:
    suites, leases, mkt = _mixed()
    baseline = run(suites, leases, mkt=mkt)

    for suite_order in itertools.permutations(suites):
        candidate = run(list(suite_order), leases, mkt=mkt)
        assert hexes(candidate.annual_projection.noi_by_year) == hexes(
            baseline.annual_projection.noi_by_year
        )
        assert candidate.annual_projection.exit_noi.hex() == (
            baseline.annual_projection.exit_noi.hex()
        )

    for lease_order in itertools.permutations(leases):
        candidate = run(suites, list(lease_order), mkt=mkt)
        assert candidate.results.levered_irr == baseline.results.levered_irr


def test_the_envelope_shape_is_exactly_three_fields() -> None:
    import dataclasses

    fields = [f.name for f in dataclasses.fields(LeaseLevelAcquisitionResults)]

    assert fields == ["monthly_projection", "annual_projection", "results"]


def test_the_envelope_adds_no_lease_level_return_metric() -> None:
    import dataclasses

    fields = {f.name for f in dataclasses.fields(LeaseLevelAcquisitionResults)}

    for forbidden in (
        "levered_irr",
        "unlevered_irr",
        "equity_multiple",
        "dscr_by_year",
        "exit_value",
        "annual_debt_service",
    ):
        assert forbidden not in fields


# =============================================================================
# D4.5B closeout -- the at-most-one-known-lease-per-suite scope rule
#
# Six cases fixing the D4 boundary exactly. The rule counts *known* leases with
# no date condition, so Case E -- two sequential, non-overlapping leases -- is
# the one that proves the terminology: this is not an overlap check.
# =============================================================================


def _second_lease(
    suite_id: str,
    area: float,
    *,
    commencement: date,
    expiration: date,
    lease_id: str = "L-A2",
) -> Lease:
    return Lease(
        lease_id=lease_id,
        suite_id=suite_id,
        leased_area_sf=area,
        rent_commencement_date=commencement,
        lease_expiration_date=expiration,
        base_rent_psf=32.0,
        escalation_pct=0.0,
        escalation_basis=EscalationBasis.NONE,
        lease_type=LeaseType.NNN,
    )


def test_case_a_zero_leases_with_hold_vacant_is_valid() -> None:
    """A suite may legitimately carry no lease at all."""

    occupied = Suite(suite_id="A", suite_area_sf=80_000.0)
    empty = vacant_suite(
        "V", 20_000.0, strategy=InitialVacancyStrategy.HOLD_VACANT, lease_up=None
    )

    out = run([occupied, empty], [occupied_lease(occupied)])

    held = next(
        p
        for p in out.monthly_projection.operating_schedule.suite_projections
        if p.suite_id == "V"
    )
    assert held.cash_base_rent == tuple(0.0 for _ in out.monthly_projection.months)
    assert out.monthly_projection.physical_occupancy[0] == pytest.approx(
        0.80, abs=1e-12
    )
    assert out.results.exit_value > 0.0


def test_case_b_zero_leases_with_market_lease_up_is_valid() -> None:
    empty = vacant_suite("A", AREA, lease_up=3.0)

    out = run([empty], [])

    assert out.monthly_projection.cash_base_rent[:3] == (0.0, 0.0, 0.0)
    assert out.monthly_projection.cash_base_rent[3] > 0.0
    assert out.results.exit_value > 0.0


def test_case_c_exactly_one_known_lease_enters_the_recursive_rollover() -> None:
    """One lease is the occupied path -- and it genuinely rolls over: the lease
    expires inside the hold, and a successor prices the months after."""

    suite = Suite(suite_id="A", suite_area_sf=AREA)
    lease = occupied_lease(suite, end=date(2028, 12, 31))

    out = run([suite], [lease], mkt=market(renewal_probability=1.0))
    monthly = out.monthly_projection

    # Month 24 is the last contractual month; month 25 is the successor's.
    assert monthly.cash_base_rent[23] > 0.0
    assert monthly.cash_base_rent[24] > 0.0
    # The successor is priced off market, not off the expiring contract rent.
    assert monthly.cash_base_rent[24] != pytest.approx(
        monthly.cash_base_rent[23], abs=1e-6
    )
    assert out.results.exit_value > 0.0


def test_case_d_two_overlapping_known_leases_are_rejected() -> None:
    """Rejected -- and rejected by the *right* rule.

    Overlapping leases in one suite are a contractual defect: the rent roll
    double-counts the same square feet. That is D1's pre-existing
    ``OVERLAPPING_LEASES_IN_SUITE``, and because validation runs upstream-first
    it fires before the D4 scope rule is ever consulted. The two rules are not
    interchangeable: one says the rent roll is wrong, the other says the rent
    roll is fine but this path cannot underwrite it (Case E).
    """

    suite = Suite(suite_id="A", suite_area_sf=AREA)
    first = occupied_lease(suite, end=date(2030, 12, 31))
    overlapping = _second_lease(
        "A", AREA, commencement=date(2028, 1, 1), expiration=date(2033, 12, 31)
    )

    with pytest.raises(LeaseValidationError) as raised:
        run([suite], [first, overlapping])

    codes = [issue.code for issue in raised.value.result.errors]
    assert LeaseIssueCode.OVERLAPPING_LEASES_IN_SUITE in codes

    # The D4 rule would also have caught it, had it been reached.
    from anchor.leasing import validate_lease_level_acquisition_leases

    assert [
        issue.code
        for issue in validate_lease_level_acquisition_leases(
            [suite], [first, overlapping]
        ).errors
    ] == [LeaseIssueCode.MULTIPLE_KNOWN_LEASES_IN_SUITE]


def test_case_e_two_sequential_non_overlapping_known_leases_are_rejected() -> None:
    """**The case that proves "known" rather than "in place".**

    These two leases never coexist: the first ends 2028-12-31, the second
    commences the next day. D1 represents that rent roll perfectly well. The D4
    acquisition path still refuses it, because composing *known lease -> known
    future lease -> market recursion* needs economics no contract carries -- so
    the alternative would be to drop the signed future lease's rent, or to
    fabricate its concessions, TI, LC and commencement-gap treatment.
    """

    suite = Suite(suite_id="A", suite_area_sf=AREA)
    first = occupied_lease(suite, end=date(2028, 12, 31))
    sequential = _second_lease(
        "A", AREA, commencement=date(2029, 1, 1), expiration=date(2033, 12, 31)
    )

    assert sequential.rent_commencement_date > first.lease_expiration_date

    with pytest.raises(LeaseValidationError) as raised:
        run([suite], [first, sequential])

    errors = raised.value.result.errors
    assert [issue.code for issue in errors] == [
        LeaseIssueCode.MULTIPLE_KNOWN_LEASES_IN_SUITE
    ]
    assert "at most one known lease" in errors[0].message
    assert "sequential or committed future known leases" in errors[0].message


def test_case_e_the_rule_is_not_an_overlap_check() -> None:
    """Stated directly against the validator: identical rejection whether the
    two leases overlap or not. A date-sensitive rule would differ."""

    from anchor.leasing import validate_lease_level_acquisition_leases

    suite = Suite(suite_id="A", suite_area_sf=AREA)
    first = occupied_lease(suite, end=date(2028, 12, 31))
    overlapping = _second_lease(
        "A", AREA, commencement=date(2028, 1, 1), expiration=date(2033, 12, 31)
    )
    sequential = _second_lease(
        "A", AREA, commencement=date(2029, 1, 1), expiration=date(2033, 12, 31)
    )

    overlapping_codes = [
        issue.code
        for issue in validate_lease_level_acquisition_leases(
            [suite], [first, overlapping]
        ).errors
    ]
    sequential_codes = [
        issue.code
        for issue in validate_lease_level_acquisition_leases(
            [suite], [first, sequential]
        ).errors
    ]

    assert overlapping_codes == sequential_codes
    assert sequential_codes == [LeaseIssueCode.MULTIPLE_KNOWN_LEASES_IN_SUITE]


def test_case_e_the_error_names_every_lease_it_refused() -> None:
    """Nothing is dropped silently -- both lease ids appear in the message, so
    the analyst can see exactly what was not modelled."""

    from anchor.leasing import validate_lease_level_acquisition_leases

    suite = Suite(suite_id="A", suite_area_sf=AREA)
    first = occupied_lease(suite, end=date(2028, 12, 31))
    sequential = _second_lease(
        "A", AREA, commencement=date(2029, 1, 1), expiration=date(2033, 12, 31)
    )

    issue = validate_lease_level_acquisition_leases(
        [suite], [first, sequential]
    ).errors[0]

    assert first.lease_id in issue.message
    assert sequential.lease_id in issue.message
    assert issue.path == "suites[A]"


def test_case_f_d1_still_accepts_sequential_known_leases() -> None:
    """**D1 is unchanged.** The restriction is scoped to the acquisition path;
    the contractual layer that represents the rent roll never sees it.

    The same two leases the acquisition path rejects validate cleanly through
    the D1 rent-roll authority, and each still builds its own contractual
    schedule.
    """

    from anchor.leasing import (
        build_lease_monthly_schedule,
        build_model_months,
        validate_lease_level_inputs,
    )

    suite = Suite(suite_id="A", suite_area_sf=AREA)
    first = occupied_lease(suite, end=date(2028, 12, 31))
    sequential = _second_lease(
        "A", AREA, commencement=date(2029, 1, 1), expiration=date(2033, 12, 31)
    )

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite],
        [first, sequential],
        hold_period=HOLD,
        market_leasing=market(),
    )

    assert result.is_valid, [issue.message for issue in result.errors]
    assert LeaseIssueCode.MULTIPLE_KNOWN_LEASES_IN_SUITE not in [
        issue.code for issue in result.issues
    ]

    months = build_model_months(analysis_start=JAN, hold_period=HOLD)
    for lease in (first, sequential):
        schedule = build_lease_monthly_schedule(
            lease, analysis_start=JAN, months=months
        )
        assert any(value > 0.0 for value in schedule.contractual_base_rent)


def test_a_second_lease_in_a_different_suite_is_fine() -> None:
    """The rule is per suite, not per property -- a multi-tenant rent roll is
    the normal case, not an error."""

    a = Suite(suite_id="A", suite_area_sf=60_000.0)
    b = Suite(suite_id="B", suite_area_sf=40_000.0)

    out = run([a, b], [occupied_lease(a), occupied_lease(b)])

    assert out.monthly_projection.physical_occupancy[0] == pytest.approx(
        1.0, abs=1e-12
    )
    assert out.results.exit_value > 0.0
