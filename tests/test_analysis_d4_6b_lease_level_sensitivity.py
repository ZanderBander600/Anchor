"""Sprint D Gate D4.6B -- Lease-Level sensitivity, end to end.

Governed by
``docs/plans/2026-09-07-anchor-lease-level-underwriting-d4-6-sensitivity-architecture.md``,
Section 34's golden plan and the Section 38 closeout amendment.

Every case starts from **raw Lease-Level inputs** and runs the public
sensitivity runners. The claim under test throughout is that a sensitivity cell
is a genuine full re-underwrite of a perturbed input -- not an adjustment of a
baseline output -- so the goldens repeatedly compare a sensitivity cell against
an **independent direct call** to
``analyze_lease_level_acquisition_with_projection`` with the same immutable
replacement applied in the test itself.

The claims that fail silently if wrong:

- a candidate equal to the baseline reproduces the baseline **bit for bit**;
- each of the eight targets reaches its complete dependent economics;
- a suite override **refuses** a property-default market target instead of
  producing a flat, plausible, wrong table -- and the refusal rule differs
  between ``market_rent_psf`` and ``renewal_probability``;
- ``None`` (valid scenario, undefined metric) and a validation failure stay
  distinguishable;
- no cell is derived from another cell.
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import date
from unittest.mock import patch

import pytest

from anchor.analysis import (
    LEASE_LEVEL_SUPPORTED_ASSUMPTIONS,
    LEASE_LEVEL_SUPPORTED_METRICS,
    SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE,
    OneWaySensitivityResult,
    SensitivityTargetShadowedBySuiteOverrideError,
    TwoWaySensitivityResult,
    UnknownLeaseLevelAssumptionError,
    analyze_lease_level_acquisition_with_projection,
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
)
from anchor.analysis import lease_level_sensitivity as module
from anchor.analysis.sensitivity import UnknownAssumptionError, UnknownMetricError
from anchor.contracts import AcquisitionTerms
from anchor.leasing import (
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
    Suite,
)
from anchor.validation import InputValidationError

JAN = date(2027, 1, 1)
AREA = 100_000.0
PRICE = 40_000_000.0
HOLD = 3


# =============================================================================
# Fixtures -- raw inputs only, mirroring the D4.5B golden fixtures
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
    end: date = date(2035, 12, 31),
    base_rent_psf: float = 30.0,
    lease_type: LeaseType = LeaseType.NNN,
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
    )


#: A single suite holding the whole building, its lease running past the hold.
#: No rollover, so market-leasing targets are inert here by construction --
#: which is exactly what makes it the right fixture for the acquisition-terms
#: and operating targets.
def stable_deal() -> tuple[list[Suite], list[Lease]]:
    suite = Suite(suite_id="A", suite_area_sf=AREA)
    return [suite], [occupied_lease(suite)]


#: A rollover inside the hold with **differentiated** renewal and new-tenant
#: economics -- different TI, different LC, downtime and free rent on the new
#: branch only, and a different successor lease type. Without that
#: differentiation ``renewal_probability`` would be inert and its goldens would
#: pass while proving nothing.
def rollover_deal() -> tuple[list[Suite], list[Lease], MarketLeasingAssumptions]:
    suite = Suite(suite_id="A", suite_area_sf=AREA)
    lease = occupied_lease(suite, end=date(2028, 12, 31))
    mkt = market(
        market_rent_psf=36.0,
        renewal_ti_psf=5.0,
        new_ti_psf=40.0,
        renewal_lc_pct=0.02,
        new_lc_pct=0.06,
        renewal_downtime_months=0.0,
        new_downtime_months=6.0,
        new_free_rent_months=3.0,
        renewal_lease_type=LeaseType.NNN,
        new_lease_type=LeaseType.GROSS,
        renewal_probability=0.5,
    )
    return [suite], [lease], mkt


#: The Section 20.1 cash-flow shape: rollover-year TI/LC exceed that year's
#: cash flow after debt service, giving three sign changes, so a levered IRR
#: does not exist while the equity multiple stays perfectly well defined.
def undefined_irr_deal() -> tuple[
    list[Suite], list[Lease], MarketLeasingAssumptions, AcquisitionTerms
]:
    suite = Suite(suite_id="A", suite_area_sf=AREA)
    lease = occupied_lease(suite, end=date(2029, 12, 31))
    mkt = market(
        renewal_ti_psf=35.0,
        new_ti_psf=35.0,
        renewal_lc_pct=0.06,
        new_lc_pct=0.06,
        renewal_probability=0.5,
    )
    return [suite], [lease], mkt, terms(hold_period=5)


def analyze(
    suites,
    leases,
    *,
    deal: AcquisitionTerms | None = None,
    mkt: MarketLeasingAssumptions | None = None,
    ops: LeaseLevelOperatingInputs | None = None,
):
    """One direct, independent Lease-Level re-underwrite -- the oracle every
    sensitivity cell is measured against."""

    return analyze_lease_level_acquisition_with_projection(
        deal or terms(),
        property_inputs(),
        suites,
        leases,
        market_leasing=mkt or market(),
        operating_inputs=ops or operating(),
    )


def one_way(suites, leases, *, deal=None, mkt=None, ops=None, **kwargs):
    return run_lease_level_one_way_sensitivity(
        deal or terms(),
        property_inputs(),
        suites,
        leases,
        market_leasing=mkt or market(),
        operating_inputs=ops or operating(),
        **kwargs,
    )


def two_way(suites, leases, *, deal=None, mkt=None, ops=None, **kwargs):
    return run_lease_level_two_way_sensitivity(
        deal or terms(),
        property_inputs(),
        suites,
        leases,
        market_leasing=mkt or market(),
        operating_inputs=ops or operating(),
        **kwargs,
    )


def metric_of(results, metric: str):
    """Read the same already-computed field the sensitivity layer reads. All
    five supported metric names are ``AcquisitionResults`` field names."""

    return getattr(results, metric)


def hexes(values):
    return [None if v is None else v.hex() for v in values]


# =============================================================================
# The approved surface
# =============================================================================


def test_exactly_eight_targets_are_supported() -> None:
    assert LEASE_LEVEL_SUPPORTED_ASSUMPTIONS == (
        "purchase_price",
        "exit_cap_rate",
        "ltv",
        "interest_rate",
        "market_rent_psf",
        "renewal_probability",
        "expense_growth",
        "recoverable_expense_ratio",
    )
    assert len(LEASE_LEVEL_SUPPORTED_ASSUMPTIONS) == 8


def test_the_metric_surface_is_the_shipped_five() -> None:
    assert LEASE_LEVEL_SUPPORTED_METRICS == (
        "levered_irr",
        "unlevered_irr",
        "equity_multiple",
        "headline_dscr",
        "exit_value",
    )


@pytest.mark.parametrize(
    "assumption",
    [
        "market_rent_growth",
        "renewal_downtime_months",
        "new_downtime_months",
        "renewal_free_rent_months",
        "new_free_rent_months",
        "renewal_ti_psf",
        "new_ti_psf",
        "renewal_lc_pct",
        "new_lc_pct",
        "successor_escalation_pct",
        "renewal_rent_spread",
        "property_taxes",
        "insurance",
        "other_income",
        "other_income_growth",
        "credit_loss_pct",
        "management_fee_pct",
        "annual_capex_reserve",
        "acquisition_cost_pct",
        "financing_fee_pct",
        "disposition_cost_pct",
        "renewal_term_months",
        "new_term_months",
        "hold_period",
        "amortization",
        "io_period",
        "analysis_start_date",
        "rentable_area_sf",
        "suite_area_sf",
        "base_rent_psf",
        "escalation_pct",
        "lease_type",
        "recovery_basis",
        "initial_vacancy",
        "suite_id",
        "market_leasing_override",
        "current_noi",
        "noi_growth",
        "occupancy",
    ],
)
def test_a_deferred_assumption_is_refused_explicitly(assumption: str) -> None:
    """Every deferred target raises rather than being silently ignored, and
    rather than reaching an arbitrary field through ``setattr``."""

    suites, leases = stable_deal()
    with pytest.raises(UnknownLeaseLevelAssumptionError) as excinfo:
        one_way(
            suites, leases, assumption=assumption, values=(1.0,),
            metric="equity_multiple",
        )
    assert assumption in str(excinfo.value)
    # The framework's existing convention for this failure still catches it.
    assert isinstance(excinfo.value, UnknownAssumptionError)


def test_the_unsupported_target_message_names_the_lease_level_set() -> None:
    suites, leases = stable_deal()
    with pytest.raises(UnknownAssumptionError) as excinfo:
        one_way(
            suites, leases, assumption="noi_growth", values=(0.03,),
            metric="equity_multiple",
        )
    message = str(excinfo.value)
    for name in LEASE_LEVEL_SUPPORTED_ASSUMPTIONS:
        assert name in message
    assert "current_noi" not in message


def test_an_unsupported_metric_is_refused() -> None:
    suites, leases = stable_deal()
    with pytest.raises(UnknownMetricError):
        one_way(
            suites, leases, assumption="exit_cap_rate", values=(0.065,),
            metric="going_in_cap_rate",
        )


def test_two_way_refuses_the_same_target_on_both_axes() -> None:
    """Mirrors the shipped framework's rule for Quick and Detailed rather than
    inventing Lease-Level-only semantics."""

    suites, leases = stable_deal()
    with pytest.raises(ValueError, match="must differ"):
        two_way(
            suites, leases,
            row_assumption="exit_cap_rate", row_values=(0.06, 0.07),
            column_assumption="exit_cap_rate", column_values=(0.06, 0.07),
            metric="equity_multiple",
        )


# =============================================================================
# G1 -- baseline-value identity
# =============================================================================


@pytest.mark.parametrize(
    "assumption, baseline_value",
    [
        ("purchase_price", PRICE),
        ("exit_cap_rate", 0.065),
        ("ltv", 0.60),
        ("interest_rate", 0.05),
        ("expense_growth", 0.03),
        ("recoverable_expense_ratio", 1.0),
    ],
)
def test_g1_a_candidate_equal_to_the_baseline_reproduces_it_bit_for_bit(
    assumption: str, baseline_value: float
) -> None:
    """**Golden 1.** The proof that sensitivity itself changes no economics: a
    scenario whose candidate *is* the baseline value must produce exactly what
    a direct analysis of the untouched baseline produces -- compared by
    ``float.hex()``, not by tolerance."""

    suites, leases = stable_deal()
    direct = analyze(suites, leases)

    result = one_way(
        suites, leases, assumption=assumption,
        values=(baseline_value,), metric="equity_multiple",
    )

    assert result.baseline_assumption_value == baseline_value
    assert result.metric_values[0].hex() == direct.results.equity_multiple.hex()
    assert result.baseline_metric_value.hex() == direct.results.equity_multiple.hex()


def test_g1_the_market_targets_reproduce_the_baseline_too() -> None:
    suites, leases, mkt = rollover_deal()
    direct = analyze(suites, leases, mkt=mkt)

    for assumption, baseline_value in (
        ("market_rent_psf", 36.0),
        ("renewal_probability", 0.5),
    ):
        result = one_way(
            suites, leases, mkt=mkt, assumption=assumption,
            values=(baseline_value,), metric="equity_multiple",
        )
        assert result.baseline_assumption_value == baseline_value
        assert result.metric_values[0].hex() == direct.results.equity_multiple.hex()


def test_g1_the_baseline_metric_is_its_own_call_not_the_first_cell() -> None:
    """``baseline_metric_value`` is the untouched baseline, even when no
    candidate equals it."""

    suites, leases = stable_deal()
    direct = analyze(suites, leases)

    result = one_way(
        suites, leases, assumption="purchase_price",
        values=(30_000_000.0, 50_000_000.0), metric="equity_multiple",
    )

    assert result.baseline_metric_value.hex() == direct.results.equity_multiple.hex()
    assert result.baseline_metric_value not in result.metric_values


# =============================================================================
# G2-G5 -- the four shared acquisition targets, proven by full re-underwrite
# =============================================================================


def test_g2_purchase_price_reaches_the_complete_dependent_economics() -> None:
    """**Golden 2.** Price moves the going-in cap, the equity cheque, the debt
    principal (LTV applies to price) and the returns -- and leaves property NOI
    alone, because nothing in the operating model depends on what was paid."""

    suites, leases = stable_deal()
    candidates = (36_000_000.0, 40_000_000.0, 44_000_000.0)

    result = one_way(
        suites, leases, assumption="purchase_price",
        values=candidates, metric="equity_multiple",
    )

    directs = [analyze(suites, leases, deal=terms(purchase_price=p)) for p in candidates]

    assert hexes(result.metric_values) == hexes(
        [d.results.equity_multiple for d in directs]
    )
    # Monotone decreasing in price.
    assert result.metric_values[0] > result.metric_values[1] > result.metric_values[2]
    # NOI and exit NOI are untouched by the price paid...
    assert len({d.annual_projection.exit_noi.hex() for d in directs}) == 1
    assert len({hexes(d.annual_projection.noi_by_year)[0] for d in directs}) == 1
    # ...while the going-in cap, the debt and the equity all move.
    assert len({d.annual_projection.going_in_cap_rate for d in directs}) == 3
    assert len({d.results.loan_amount for d in directs}) == 3
    assert len({d.results.initial_equity for d in directs}) == 3


def test_g3_exit_cap_moves_exit_value_and_never_exit_noi() -> None:
    """**Golden 3.** The classic silent-wrongness check: a sensitivity that
    scaled exit *NOI* instead of capitalising it would still produce a
    plausible monotone table."""

    suites, leases = stable_deal()
    candidates = (0.055, 0.065, 0.075)

    values = one_way(
        suites, leases, assumption="exit_cap_rate",
        values=candidates, metric="exit_value",
    )
    directs = [analyze(suites, leases, deal=terms(exit_cap_rate=c)) for c in candidates]

    assert hexes(values.metric_values) == hexes([d.results.exit_value for d in directs])
    # Exit NOI is bit-identical across every cell; only its capitalisation moves.
    assert len({d.annual_projection.exit_noi.hex() for d in directs}) == 1
    assert len({hexes(d.annual_projection.noi_by_year)[0] for d in directs}) == 1
    assert len({hexes(d.monthly_projection.noi)[0] for d in directs}) == 1
    assert values.metric_values[0] > values.metric_values[1] > values.metric_values[2]


def test_g4_ltv_flows_through_the_existing_debt_structure_only() -> None:
    """**Golden 4.** NOI, exit NOI and exit value are untouched; the loan, the
    equity, the DSCR and the levered return all move."""

    suites, leases = stable_deal()
    candidates = (0.50, 0.60, 0.70)

    result = one_way(
        suites, leases, assumption="ltv",
        values=candidates, metric="headline_dscr",
    )
    directs = [analyze(suites, leases, deal=terms(ltv=c)) for c in candidates]

    assert hexes(result.metric_values) == hexes(
        [d.results.headline_dscr for d in directs]
    )
    assert len({d.annual_projection.exit_noi.hex() for d in directs}) == 1
    assert len({hexes(d.annual_projection.noi_by_year)[0] for d in directs}) == 1
    assert len({d.results.exit_value.hex() for d in directs}) == 1
    assert len({d.results.loan_amount for d in directs}) == 3
    assert len({d.results.initial_equity for d in directs}) == 3
    assert result.metric_values[0] > result.metric_values[1] > result.metric_values[2]


def test_g5_interest_rate_moves_debt_service_and_never_noi() -> None:
    """**Golden 5.** NOI is computed before debt exists, so it must be
    bit-identical across the whole row."""

    suites, leases = stable_deal()
    candidates = (0.04, 0.05, 0.06)

    result = one_way(
        suites, leases, assumption="interest_rate",
        values=candidates, metric="headline_dscr",
    )
    directs = [analyze(suites, leases, deal=terms(interest_rate=c)) for c in candidates]

    assert hexes(result.metric_values) == hexes(
        [d.results.headline_dscr for d in directs]
    )
    assert len({d.annual_projection.exit_noi.hex() for d in directs}) == 1
    assert len({hexes(d.annual_projection.noi_by_year)[0] for d in directs}) == 1
    assert len({d.results.exit_value.hex() for d in directs}) == 1
    # Debt service rises, so DSCR falls and the levered return falls with it.
    assert result.metric_values[0] > result.metric_values[1] > result.metric_values[2]
    assert (
        directs[0].results.equity_multiple > directs[2].results.equity_multiple
    )


# =============================================================================
# G6 -- market rent
# =============================================================================


def test_g6_market_rent_rebuilds_the_full_lease_level_pipeline() -> None:
    """**Golden 6.** On a property with no shadowing override and a rollover
    inside the hold, the property-default market rent must reach the successor
    contractual rent, the LC basis, NOI, exit NOI and the returns together."""

    suites, leases, mkt = rollover_deal()
    candidates = (24.0, 36.0, 48.0)

    result = one_way(
        suites, leases, mkt=mkt, assumption="market_rent_psf",
        values=candidates, metric="equity_multiple",
    )
    directs = [
        analyze(suites, leases, mkt=dataclasses.replace(mkt, market_rent_psf=c))
        for c in candidates
    ]

    assert hexes(result.metric_values) == hexes(
        [d.results.equity_multiple for d in directs]
    )
    assert result.metric_values[0] < result.metric_values[1] < result.metric_values[2]

    # The dependent economics all moved together.
    assert len({d.annual_projection.exit_noi for d in directs}) == 3
    assert len({sum(d.annual_projection.leasing_commissions_by_year) for d in directs}) == 3
    assert len({d.results.exit_value for d in directs}) == 3
    assert len({sum(d.monthly_projection.cash_base_rent) for d in directs}) == 3


def test_g6_market_rent_leaves_the_in_place_contractual_rent_alone() -> None:
    """The in-place lease is a signed contract. Its rent must not move because
    the market moved -- only the successor's does. Year 1 is entirely in-place
    here (the lease runs to 2028-12-31), so its NOI must be bit-identical."""

    suites, leases, mkt = rollover_deal()
    low = analyze(suites, leases, mkt=dataclasses.replace(mkt, market_rent_psf=24.0))
    high = analyze(suites, leases, mkt=dataclasses.replace(mkt, market_rent_psf=48.0))

    assert (
        low.annual_projection.noi_by_year[0].hex()
        == high.annual_projection.noi_by_year[0].hex()
    )
    assert (
        low.monthly_projection.cash_base_rent[0].hex()
        == high.monthly_projection.cash_base_rent[0].hex()
    )
    # ...but the successor's economics did move.
    assert low.annual_projection.exit_noi != high.annual_projection.exit_noi


# =============================================================================
# G7 -- renewal probability, including the exact D2 endpoints
# =============================================================================


def test_g7_renewal_probability_endpoints_reach_d2_untransformed() -> None:
    """**Golden 7.** ``p = 0`` and ``p = 1`` are exact D2 branch endpoints, not
    limits. Both must be reachable as candidates and both must equal a direct
    analysis at that exact value -- no nudging to 0.001/0.999, no clipping, no
    probability weighting invented in the sensitivity layer."""

    suites, leases, mkt = rollover_deal()
    candidates = (0.0, 0.5, 1.0)

    result = one_way(
        suites, leases, mkt=mkt, assumption="renewal_probability",
        values=candidates, metric="equity_multiple",
    )
    directs = [
        analyze(suites, leases, mkt=dataclasses.replace(mkt, renewal_probability=p))
        for p in candidates
    ]

    assert result.assumption_values == (0.0, 0.5, 1.0)
    assert hexes(result.metric_values) == hexes(
        [d.results.equity_multiple for d in directs]
    )
    assert result.metric_values[0] < result.metric_values[1] < result.metric_values[2]


def test_g7_renewal_probability_rebuilds_ti_lc_recoveries_and_noi() -> None:
    """The whole dependent chain, not just a blended return."""

    suites, leases, mkt = rollover_deal()
    at_zero = analyze(suites, leases, mkt=dataclasses.replace(mkt, renewal_probability=0.0))
    at_one = analyze(suites, leases, mkt=dataclasses.replace(mkt, renewal_probability=1.0))

    for reader in (
        lambda out: sum(out.annual_projection.tenant_improvements_by_year),
        lambda out: sum(out.annual_projection.leasing_commissions_by_year),
        lambda out: sum(out.monthly_projection.expense_recovery),
        lambda out: out.annual_projection.exit_noi,
        lambda out: out.results.equity_multiple,
    ):
        assert reader(at_zero) != reader(at_one)


def test_g7_a_probability_outside_the_domain_is_never_clipped() -> None:
    """1.2 is invalid, not 1.0. The contract's own validator refuses it and the
    whole run fails."""

    suites, leases, mkt = rollover_deal()
    with pytest.raises(LeaseValidationError) as excinfo:
        one_way(
            suites, leases, mkt=mkt, assumption="renewal_probability",
            values=(0.5, 1.2), metric="equity_multiple",
        )
    assert LeaseIssueCode.RENEWAL_PROBABILITY_OUT_OF_DOMAIN in {
        issue.code for issue in excinfo.value.result.issues
    }


# =============================================================================
# G8-G9 -- the two property operating targets
# =============================================================================


def test_g8_expense_growth_rebuilds_expenses_pool_recoveries_fee_and_noi() -> None:
    """**Golden 8.** The deepest rebuild chain of any target. A stale expense
    schedule or a stale recoverable pool would leave recoveries or the
    management fee frozen while the expense line moved."""

    suites, leases = stable_deal()
    candidates = (0.00, 0.03, 0.10)

    result = one_way(
        suites, leases, assumption="expense_growth",
        values=candidates, metric="equity_multiple",
    )
    directs = [
        analyze(suites, leases, ops=operating(expense_growth=g)) for g in candidates
    ]

    assert hexes(result.metric_values) == hexes(
        [d.results.equity_multiple for d in directs]
    )

    # Every dependent stage rebuilt -- three distinct values, not one repeated.
    for reader in (
        lambda out: sum(out.monthly_projection.fixed_operating_expenses),
        lambda out: sum(out.monthly_projection.expense_recovery),
        lambda out: sum(out.monthly_projection.management_fee),
        lambda out: sum(out.monthly_projection.effective_gross_income),
        lambda out: sum(out.monthly_projection.noi),
        lambda out: out.annual_projection.exit_noi,
    ):
        assert len({reader(d) for d in directs}) == 3, reader


def test_g9_recoverable_ratio_rebuilds_the_pool_and_never_the_gross_expenses() -> None:
    """**Golden 9.** The ratio changes what is *recoverable*, not what is
    *spent*: the gross fixed expense line must be bit-identical across cells
    while recoveries, the fee, EGI, NOI and exit NOI all move. An
    ``NOI += delta recovery`` shortcut would move NOI without moving the fee."""

    suites, leases = stable_deal()
    candidates = (0.0, 0.5, 1.0)

    result = one_way(
        suites, leases, assumption="recoverable_expense_ratio",
        values=candidates, metric="equity_multiple",
    )
    directs = [
        analyze(suites, leases, ops=operating(recoverable_expense_ratio=r))
        for r in candidates
    ]

    assert hexes(result.metric_values) == hexes(
        [d.results.equity_multiple for d in directs]
    )
    assert result.metric_values[0] < result.metric_values[1] < result.metric_values[2]

    # Gross fixed expenses: unchanged.
    assert len({
        tuple(hexes(d.monthly_projection.fixed_operating_expenses)) for d in directs
    }) == 1
    # Everything downstream of the pool: rebuilt.
    for reader in (
        lambda out: sum(out.monthly_projection.expense_recovery),
        lambda out: sum(out.monthly_projection.management_fee),
        lambda out: sum(out.monthly_projection.effective_gross_income),
        lambda out: out.annual_projection.exit_noi,
        lambda out: out.results.exit_value,
    ):
        assert len({reader(d) for d in directs}) == 3, reader
    # A zero ratio recovers nothing at all.
    assert sum(directs[0].monthly_projection.expense_recovery) == 0.0


# =============================================================================
# G10-G12 -- the suite-override shadow rules (mandatory, Section 38.9)
# =============================================================================


def _two_suites(
    *, scalar_rent: float | None = None, override: MarketLeasingAssumptions | None = None
) -> tuple[list[Suite], list[Lease]]:
    """Suite A takes the property default; suite B carries whichever override
    the case under test needs. Both roll over inside the hold."""

    a = Suite(suite_id="A", suite_area_sf=60_000.0)
    b = Suite(
        suite_id="B",
        suite_area_sf=40_000.0,
        market_rent_psf=scalar_rent,
        market_leasing_override=override,
    )
    return [a, b], [
        occupied_lease(a, end=date(2028, 12, 31)),
        occupied_lease(b, end=date(2028, 12, 31)),
    ]


def test_g10_a_scalar_suite_rent_override_refuses_market_rent_sensitivity() -> None:
    """**Golden 10 / Section 38.9.1.** Not four identical cells. Not a silent
    no-op. Not an override overwrite. An explicit refusal, raised before any
    scenario runs."""

    suites, leases = _two_suites(scalar_rent=48.0)

    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError) as excinfo:
        one_way(
            suites, leases, assumption="market_rent_psf",
            values=(30.0, 36.0, 42.0, 48.0), metric="equity_multiple",
        )

    error = excinfo.value
    assert error.code == SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE
    assert error.assumption == "market_rent_psf"
    assert error.suite_ids == ("B",)
    assert "market_rent_psf" in str(error)
    assert "B" in str(error)


def test_g10_a_full_override_refuses_market_rent_sensitivity_too() -> None:
    suites, leases = _two_suites(override=market(market_rent_psf=52.0))

    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError) as excinfo:
        one_way(
            suites, leases, assumption="market_rent_psf",
            values=(30.0, 48.0), metric="equity_multiple",
        )
    assert excinfo.value.suite_ids == ("B",)


def test_g10_the_refusal_names_every_shadowing_suite() -> None:
    a = Suite(suite_id="A", suite_area_sf=50_000.0, market_rent_psf=44.0)
    b = Suite(
        suite_id="B", suite_area_sf=50_000.0,
        market_leasing_override=market(market_rent_psf=52.0),
    )
    leases = [
        occupied_lease(a, end=date(2028, 12, 31)),
        occupied_lease(b, end=date(2028, 12, 31)),
    ]

    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError) as excinfo:
        one_way(
            [a, b], leases, assumption="market_rent_psf",
            values=(30.0,), metric="equity_multiple",
        )
    assert excinfo.value.suite_ids == ("A", "B")


def test_g10_the_refusal_precedes_every_scenario() -> None:
    """No misleading table is assembled, and no re-underwrite is spent
    discovering a structural refusal."""

    suites, leases = _two_suites(scalar_rent=48.0)

    with patch.object(
        module,
        "analyze_lease_level_acquisition_with_projection",
        wraps=analyze_lease_level_acquisition_with_projection,
    ) as spy:
        with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError):
            one_way(
                suites, leases, assumption="market_rent_psf",
                values=(30.0, 36.0, 42.0), metric="equity_multiple",
            )

    assert spy.call_count == 0


def test_g10_the_rent_roll_itself_remains_perfectly_analysable() -> None:
    """The refusal is a sensitivity-layer judgement, not a leasing defect. The
    identical inputs still underwrite."""

    suites, leases = _two_suites(scalar_rent=48.0)
    out = analyze(suites, leases)
    assert out.results.equity_multiple > 0.0


def test_g10_the_shadow_error_is_not_a_lease_validation_error() -> None:
    """Section 38.2.3: this must never become a ``LeaseIssueCode``."""

    assert not issubclass(
        SensitivityTargetShadowedBySuiteOverrideError, LeaseValidationError
    )
    assert SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE not in {
        code.value for code in LeaseIssueCode
    }


def test_g11_a_scalar_rent_override_does_not_shadow_renewal_probability() -> None:
    """**Golden 11 / Section 38.9.2, case A.** The measured asymmetry:
    ``Suite.market_rent_psf`` is a single-field override of the rent *level*
    alone, so the property default's renewal probability still reaches that
    suite. The run must proceed -- and must actually move."""

    suites, leases = _two_suites(scalar_rent=48.0)
    candidates = (0.0, 0.5, 1.0)

    result = one_way(
        suites, leases,
        mkt=market(
            market_rent_psf=36.0, renewal_ti_psf=5.0, new_ti_psf=40.0,
            renewal_lc_pct=0.02, new_lc_pct=0.06, new_downtime_months=6.0,
        ),
        assumption="renewal_probability", values=candidates,
        metric="equity_multiple",
    )

    assert len(result.metric_values) == 3
    assert len(set(result.metric_values)) == 3, (
        "the property default did not reach the rent-override suite"
    )


def test_g12_a_full_override_shadows_renewal_probability() -> None:
    """**Golden 12 / Section 38.9.2, case B.** A whole-record override is
    all-or-nothing, so it *does* shadow the probability. Assuming symmetry with
    ``market_rent_psf`` in either direction would be wrong."""

    suites, leases = _two_suites(override=market(renewal_probability=0.25))

    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError) as excinfo:
        one_way(
            suites, leases, assumption="renewal_probability",
            values=(0.0, 0.5, 1.0), metric="equity_multiple",
        )
    assert excinfo.value.assumption == "renewal_probability"
    assert excinfo.value.suite_ids == ("B",)


@pytest.mark.parametrize(
    "assumption, values",
    [
        ("expense_growth", (0.0, 0.03, 0.06)),
        ("recoverable_expense_ratio", (0.0, 0.5, 1.0)),
    ],
)
def test_g12c_operating_targets_are_never_shadowed_by_any_suite_shape(
    assumption: str, values: tuple[float, ...]
) -> None:
    """**Golden 14c.** ``LeaseLevelOperatingInputs`` shares no field with
    ``Suite`` and is unreachable from any override, so a property carrying
    *every* available suite override must still run these two."""

    a = Suite(
        suite_id="A", suite_area_sf=60_000.0, market_rent_psf=44.0,
        market_leasing_override=market(market_rent_psf=52.0, renewal_probability=0.25),
    )
    b = Suite(
        suite_id="B", suite_area_sf=40_000.0, market_rent_psf=39.0,
        market_leasing_override=market(market_rent_psf=41.0, renewal_probability=0.9),
    )
    leases = [
        occupied_lease(a, end=date(2028, 12, 31)),
        occupied_lease(b, end=date(2028, 12, 31)),
    ]

    result = one_way(
        [a, b], leases, assumption=assumption, values=values,
        metric="equity_multiple",
    )

    assert len(result.metric_values) == 3
    assert len(set(result.metric_values)) == 3


@pytest.mark.parametrize(
    "assumption", ["purchase_price", "exit_cap_rate", "ltv", "interest_rate"]
)
def test_g12d_acquisition_targets_are_never_shadowed_either(assumption: str) -> None:
    a = Suite(
        suite_id="A", suite_area_sf=AREA, market_rent_psf=44.0,
        market_leasing_override=market(market_rent_psf=52.0),
    )
    baseline = {
        "purchase_price": (36_000_000.0, 44_000_000.0),
        "exit_cap_rate": (0.06, 0.07),
        "ltv": (0.5, 0.7),
        "interest_rate": (0.04, 0.06),
    }[assumption]

    result = one_way(
        [a], [occupied_lease(a, end=date(2028, 12, 31))],
        assumption=assumption, values=baseline, metric="equity_multiple",
    )
    assert len(result.metric_values) == 2


def test_the_shadow_check_applies_to_both_axes_of_a_two_way_run() -> None:
    suites, leases = _two_suites(scalar_rent=48.0)

    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError) as row_error:
        two_way(
            suites, leases,
            row_assumption="market_rent_psf", row_values=(30.0, 40.0),
            column_assumption="exit_cap_rate", column_values=(0.06, 0.07),
            metric="equity_multiple",
        )
    assert row_error.value.assumption == "market_rent_psf"

    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError) as column_error:
        two_way(
            suites, leases,
            row_assumption="exit_cap_rate", row_values=(0.06, 0.07),
            column_assumption="market_rent_psf", column_values=(30.0, 40.0),
            metric="equity_multiple",
        )
    assert column_error.value.assumption == "market_rent_psf"


# =============================================================================
# G13-G15 -- None, invalid, and the terminal-value refusal
# =============================================================================


def test_g13_an_undefined_metric_is_none_and_the_run_still_succeeds() -> None:
    """**Golden 13 / Section 38.9.3.** A *valid*, fully underwritten scenario
    whose levered IRR does not exist (three sign changes from rollover-year
    TI/LC). The cell is ``None``, the run succeeds, and the equity multiple
    stays defined for the very same scenarios."""

    suites, leases, mkt, deal = undefined_irr_deal()
    candidates = (38_000_000.0, 40_000_000.0, 42_000_000.0)

    irr = one_way(
        suites, leases, deal=deal, mkt=mkt, assumption="purchase_price",
        values=candidates, metric="levered_irr",
    )
    em = one_way(
        suites, leases, deal=deal, mkt=mkt, assumption="purchase_price",
        values=candidates, metric="equity_multiple",
    )

    assert isinstance(irr, OneWaySensitivityResult)
    assert irr.metric_values == (None, None, None)
    assert irr.baseline_metric_value is None
    # Never converted into a fabricated number.
    assert 0.0 not in irr.metric_values
    assert all(value is not None and value > 0.0 for value in em.metric_values)

    # And it agrees with an independent direct analysis of each scenario.
    directs = [analyze(suites, leases, deal=terms(hold_period=5, purchase_price=p), mkt=mkt) for p in candidates]
    assert [d.results.levered_irr for d in directs] == [None, None, None]
    assert hexes(em.metric_values) == hexes([d.results.equity_multiple for d in directs])


def test_g13_none_also_survives_a_two_way_grid() -> None:
    suites, leases, mkt, deal = undefined_irr_deal()

    result = two_way(
        suites, leases, deal=deal, mkt=mkt,
        row_assumption="purchase_price", row_values=(38_000_000.0, 42_000_000.0),
        column_assumption="exit_cap_rate", column_values=(0.06, 0.07),
        metric="levered_irr",
    )

    assert result.matrix == ((None, None), (None, None))


@pytest.mark.parametrize(
    "assumption, values",
    [
        ("exit_cap_rate", (0.065, 0.0)),
        ("exit_cap_rate", (0.065, -0.01)),
        ("ltv", (0.6, 1.5)),
        ("ltv", (0.6, -0.1)),
        ("interest_rate", (0.05, -0.01)),
        ("purchase_price", (PRICE, 0.0)),
    ],
)
def test_g14_one_invalid_candidate_fails_the_entire_run(
    assumption: str, values: tuple[float, ...]
) -> None:
    """**Golden 14.** Explicit-run semantics, preserved exactly: the run
    raises. No partial result, no ``None`` cell, no zero."""

    suites, leases = stable_deal()
    with pytest.raises(InputValidationError):
        one_way(
            suites, leases, assumption=assumption, values=values,
            metric="equity_multiple",
        )


def test_g14_an_invalid_leasing_candidate_fails_the_entire_run() -> None:
    suites, leases, mkt = rollover_deal()
    with pytest.raises(LeaseValidationError):
        one_way(
            suites, leases, mkt=mkt, assumption="renewal_probability",
            values=(0.5, -0.2), metric="equity_multiple",
        )


def test_g14_an_invalid_cell_fails_a_two_way_run_too() -> None:
    suites, leases = stable_deal()
    with pytest.raises(InputValidationError):
        two_way(
            suites, leases,
            row_assumption="ltv", row_values=(0.6, 1.4),
            column_assumption="exit_cap_rate", column_values=(0.06, 0.07),
            metric="equity_multiple",
        )


def test_g15_a_non_positive_forward_exit_noi_fails_the_whole_run() -> None:
    """**Golden 15 / Section 38.4.2.** ``expense_growth = 5.0`` is a perfectly
    valid *input* -- the domain is ``> -1`` with no upper bound -- that drives
    the forward exit NOI non-positive. The refusal is raised by the analysis
    itself and must propagate untouched: not caught, not floored, not
    capitalised, not converted to ``None`` or zero, and not skipped."""

    suites, leases = stable_deal()

    # The candidate really is valid as an input, and really does break the
    # terminal value -- otherwise this golden would be testing nothing.
    assert analyze(suites, leases, ops=operating(expense_growth=3.0)).results

    with pytest.raises(LeaseValidationError) as excinfo:
        one_way(
            suites, leases, assumption="expense_growth",
            values=(0.03, 3.0, 5.0), metric="equity_multiple",
        )

    assert LeaseIssueCode.NON_POSITIVE_FORWARD_EXIT_NOI in {
        issue.code for issue in excinfo.value.result.issues
    }


def test_g15_the_terminal_refusal_is_not_swallowed_in_a_grid() -> None:
    suites, leases = stable_deal()
    with pytest.raises(LeaseValidationError) as excinfo:
        two_way(
            suites, leases,
            row_assumption="expense_growth", row_values=(0.03, 5.0),
            column_assumption="exit_cap_rate", column_values=(0.06, 0.07),
            metric="equity_multiple",
        )
    assert LeaseIssueCode.NON_POSITIVE_FORWARD_EXIT_NOI in {
        issue.code for issue in excinfo.value.result.issues
    }


def test_none_and_invalid_are_different_outcomes_on_one_fixture() -> None:
    """The distinction the whole ``None`` channel rests on, shown side by side
    on the same property: one run returns ``None`` cells and succeeds; the
    other raises."""

    suites, leases, mkt, deal = undefined_irr_deal()

    valid = one_way(
        suites, leases, deal=deal, mkt=mkt, assumption="exit_cap_rate",
        values=(0.06, 0.07), metric="levered_irr",
    )
    assert valid.metric_values == (None, None)

    with pytest.raises(InputValidationError):
        one_way(
            suites, leases, deal=deal, mkt=mkt, assumption="exit_cap_rate",
            values=(0.06, 0.0), metric="levered_irr",
        )


# =============================================================================
# G16-G18 -- ordering, determinism, immutability
# =============================================================================


def test_g16_candidate_order_is_the_callers_order() -> None:
    """**Golden 16.** No sorting by value, by metric or by validity, and no
    deduplication -- the shipped framework does none of those."""

    suites, leases = stable_deal()
    candidates = (44_000_000.0, 36_000_000.0, 40_000_000.0, 36_000_000.0)

    result = one_way(
        suites, leases, assumption="purchase_price",
        values=candidates, metric="equity_multiple",
    )

    assert result.assumption_values == candidates
    # Positional correspondence with an independent per-candidate analysis.
    assert hexes(result.metric_values) == hexes([
        analyze(suites, leases, deal=terms(purchase_price=c)).results.equity_multiple
        for c in candidates
    ])
    # The repeated candidate produced the same cell in both positions.
    assert result.metric_values[1] == result.metric_values[3]


def test_g16_a_reversed_request_reverses_the_cells_and_nothing_else() -> None:
    """Scenario evaluation order cannot contaminate a result."""

    suites, leases = stable_deal()
    forward = (36_000_000.0, 40_000_000.0, 44_000_000.0)

    ascending = one_way(
        suites, leases, assumption="purchase_price", values=forward,
        metric="equity_multiple",
    )
    descending = one_way(
        suites, leases, assumption="purchase_price", values=tuple(reversed(forward)),
        metric="equity_multiple",
    )

    assert hexes(descending.metric_values) == list(
        reversed(hexes(ascending.metric_values))
    )


def test_g17_repeated_runs_are_bit_identical() -> None:
    """**Golden 17.** No RNG, no clock, no cache, no shared mutable state."""

    suites, leases, mkt = rollover_deal()
    kwargs = dict(
        assumption="market_rent_psf", values=(24.0, 36.0, 48.0),
        metric="equity_multiple",
    )

    first = one_way(suites, leases, mkt=mkt, **kwargs)
    second = one_way(suites, leases, mkt=mkt, **kwargs)

    assert hexes(first.metric_values) == hexes(second.metric_values)
    assert first == second


@pytest.mark.parametrize(
    "assumption, values",
    [
        ("purchase_price", (36_000_000.0, 44_000_000.0)),
        ("exit_cap_rate", (0.06, 0.07)),
        ("ltv", (0.5, 0.7)),
        ("interest_rate", (0.04, 0.06)),
        ("market_rent_psf", (24.0, 48.0)),
        ("renewal_probability", (0.0, 1.0)),
        ("expense_growth", (0.0, 0.06)),
        ("recoverable_expense_ratio", (0.0, 1.0)),
    ],
)
def test_g18_no_caller_input_is_mutated_by_any_target(
    assumption: str, values: tuple[float, ...]
) -> None:
    """**Golden 18.** Every one of the six input contracts -- including nested
    suite overrides and initial-vacancy assumptions -- compares equal to a
    pre-run deep copy."""

    a = Suite(suite_id="A", suite_area_sf=60_000.0)
    b = Suite(
        suite_id="B",
        suite_area_sf=40_000.0,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP,
            initial_lease_up_months=3.0,
        ),
    )
    suites = [a, b]
    leases = [occupied_lease(a, end=date(2028, 12, 31))]
    deal = terms()
    prop_inputs = property_inputs()
    mkt = market(market_rent_psf=36.0, new_ti_psf=20.0, new_lc_pct=0.05)
    ops = operating()

    before = copy.deepcopy((deal, prop_inputs, suites, leases, mkt, ops))

    run_lease_level_one_way_sensitivity(
        deal, prop_inputs, suites, leases, market_leasing=mkt,
        operating_inputs=ops, assumption=assumption, values=values,
        metric="equity_multiple",
    )

    assert (deal, prop_inputs, suites, leases, mkt, ops) == before
    # The suite objects themselves, not just equal copies.
    assert suites[0] is a and suites[1] is b
    assert b.initial_vacancy == before[2][1].initial_vacancy


def test_g18_a_two_way_run_mutates_nothing_either() -> None:
    suites, leases, mkt = rollover_deal()
    deal = terms()
    prop_inputs = property_inputs()
    ops = operating()
    before = copy.deepcopy((deal, prop_inputs, suites, leases, mkt, ops))

    run_lease_level_two_way_sensitivity(
        deal, prop_inputs, suites, leases, market_leasing=mkt,
        operating_inputs=ops,
        row_assumption="market_rent_psf", row_values=(24.0, 48.0),
        column_assumption="expense_growth", column_values=(0.0, 0.06),
        metric="equity_multiple",
    )

    assert (deal, prop_inputs, suites, leases, mkt, ops) == before


def test_generators_are_accepted_and_consumed_exactly_once() -> None:
    """Suites and leases are declared ``Iterable``. A generator must not be
    exhausted by the baseline call, leaving every scenario an empty property."""

    suites, leases = stable_deal()
    result = one_way(
        (suite for suite in suites), (lease for lease in leases),
        assumption="exit_cap_rate", values=(0.06, 0.07), metric="equity_multiple",
    )
    assert all(value is not None for value in result.metric_values)
    assert result.metric_values[0] != result.metric_values[1]


# =============================================================================
# G19-G23 -- two-way
# =============================================================================


@pytest.mark.parametrize(
    "row_assumption, row_values, column_assumption, column_values, fixture",
    [
        ("purchase_price", (36_000_000.0, 44_000_000.0),
         "exit_cap_rate", (0.06, 0.07), "stable"),
        ("interest_rate", (0.04, 0.06), "ltv", (0.5, 0.7), "stable"),
        ("market_rent_psf", (24.0, 48.0), "exit_cap_rate", (0.06, 0.07), "rollover"),
        ("renewal_probability", (0.0, 1.0),
         "expense_growth", (0.0, 0.06), "rollover"),
        ("recoverable_expense_ratio", (0.25, 1.0),
         "market_rent_psf", (24.0, 48.0), "rollover"),
    ],
    ids=["g19_price_x_cap", "g20_rate_x_ltv", "g21_rent_x_cap",
         "g22_prob_x_growth", "g23_ratio_x_rent"],
)
def test_g19_to_g23_every_cell_equals_an_independent_re_underwrite(
    row_assumption, row_values, column_assumption, column_values, fixture
) -> None:
    """**Goldens 19-23.** Each cell is compared against a direct
    ``analyze_lease_level_acquisition_with_projection`` call built in the test
    with the same two immutable replacements applied to the same baseline."""

    if fixture == "stable":
        suites, leases = stable_deal()
        mkt = market()
    else:
        suites, leases, mkt = rollover_deal()

    result = two_way(
        suites, leases, mkt=mkt,
        row_assumption=row_assumption, row_values=row_values,
        column_assumption=column_assumption, column_values=column_values,
        metric="equity_multiple",
    )

    assert isinstance(result, TwoWaySensitivityResult)
    assert result.row_values == row_values
    assert result.column_values == column_values

    changes = {
        "purchase_price": "terms", "exit_cap_rate": "terms", "ltv": "terms",
        "interest_rate": "terms", "market_rent_psf": "market",
        "renewal_probability": "market", "expense_growth": "operating",
        "recoverable_expense_ratio": "operating",
    }

    for row_index, row_value in enumerate(row_values):
        for column_index, column_value in enumerate(column_values):
            term_changes, market_changes, operating_changes = {}, {}, {}
            for name, value in (
                (row_assumption, row_value), (column_assumption, column_value)
            ):
                {"terms": term_changes, "market": market_changes,
                 "operating": operating_changes}[changes[name]][name] = value

            direct = analyze(
                suites, leases,
                deal=terms(**term_changes),
                mkt=dataclasses.replace(mkt, **market_changes),
                ops=operating(**operating_changes),
            )
            cell = result.matrix[row_index][column_index]
            assert cell.hex() == direct.results.equity_multiple.hex(), (
                f"cell ({row_index}, {column_index})"
            )


def test_the_independent_cell_oracle_on_a_full_three_by_three_grid() -> None:
    """The mandatory non-trivial oracle. Nine cells, each re-underwritten
    independently in the test, all nine required to match exactly. Cumulative
    mutation along a row or down a column cannot survive this."""

    suites, leases, mkt = rollover_deal()
    rents = (24.0, 36.0, 48.0)
    ratios = (0.25, 0.5, 1.0)

    result = two_way(
        suites, leases, mkt=mkt,
        row_assumption="market_rent_psf", row_values=rents,
        column_assumption="recoverable_expense_ratio", column_values=ratios,
        metric="equity_multiple",
    )

    for row_index, rent in enumerate(rents):
        for column_index, ratio in enumerate(ratios):
            direct = analyze(
                suites, leases,
                mkt=dataclasses.replace(mkt, market_rent_psf=rent),
                ops=operating(recoverable_expense_ratio=ratio),
            )
            assert (
                result.matrix[row_index][column_index].hex()
                == direct.results.equity_multiple.hex()
            )

    # The grid genuinely varies in both directions -- nine distinct cells.
    flat = [cell for row in result.matrix for cell in row]
    assert len(set(flat)) == 9


def test_permuting_a_two_way_grid_moves_cells_without_changing_them() -> None:
    """Golden 12 of the plan: cell (i, j) is a function of its two candidate
    values alone, never of where it sits in the evaluation order."""

    suites, leases, mkt = rollover_deal()
    rents = (24.0, 36.0, 48.0)
    caps = (0.06, 0.065, 0.07)

    forward = two_way(
        suites, leases, mkt=mkt,
        row_assumption="market_rent_psf", row_values=rents,
        column_assumption="exit_cap_rate", column_values=caps,
        metric="equity_multiple",
    )
    reversed_grid = two_way(
        suites, leases, mkt=mkt,
        row_assumption="market_rent_psf", row_values=tuple(reversed(rents)),
        column_assumption="exit_cap_rate", column_values=tuple(reversed(caps)),
        metric="equity_multiple",
    )

    for row_index in range(3):
        for column_index in range(3):
            assert (
                forward.matrix[row_index][column_index]
                == reversed_grid.matrix[2 - row_index][2 - column_index]
            )


def test_the_axes_are_transposable_without_changing_a_cell() -> None:
    suites, leases = stable_deal()
    prices = (36_000_000.0, 44_000_000.0)
    caps = (0.06, 0.07)

    normal = two_way(
        suites, leases,
        row_assumption="purchase_price", row_values=prices,
        column_assumption="exit_cap_rate", column_values=caps,
        metric="equity_multiple",
    )
    transposed = two_way(
        suites, leases,
        row_assumption="exit_cap_rate", row_values=caps,
        column_assumption="purchase_price", column_values=prices,
        metric="equity_multiple",
    )

    for i in range(2):
        for j in range(2):
            assert normal.matrix[i][j] == transposed.matrix[j][i]


def test_two_way_baselines_are_recorded_from_their_own_contracts() -> None:
    suites, leases, mkt = rollover_deal()
    result = two_way(
        suites, leases, mkt=mkt,
        row_assumption="renewal_probability", row_values=(0.0, 1.0),
        column_assumption="recoverable_expense_ratio", column_values=(0.5, 1.0),
        metric="equity_multiple",
    )

    assert result.baseline_row_value == 0.5  # market_leasing.renewal_probability
    assert result.baseline_column_value == 1.0  # operating.recoverable_expense_ratio
    assert result.baseline_metric_value.hex() == (
        analyze(suites, leases, mkt=mkt).results.equity_multiple.hex()
    )


# =============================================================================
# Call counts -- every scenario is a real full analysis
# =============================================================================


def test_one_way_runs_exactly_one_plus_n_full_analyses() -> None:
    suites, leases = stable_deal()
    values = (0.055, 0.06, 0.065, 0.07, 0.075)

    with patch.object(
        module,
        "analyze_lease_level_acquisition_with_projection",
        wraps=analyze_lease_level_acquisition_with_projection,
    ) as spy:
        one_way(
            suites, leases, assumption="exit_cap_rate", values=values,
            metric="equity_multiple",
        )

    assert spy.call_count == 1 + len(values)


def test_two_way_runs_exactly_one_plus_r_times_c_full_analyses() -> None:
    suites, leases = stable_deal()
    rows = (36_000_000.0, 40_000_000.0, 44_000_000.0)
    columns = (0.06, 0.065, 0.07, 0.075)

    with patch.object(
        module,
        "analyze_lease_level_acquisition_with_projection",
        wraps=analyze_lease_level_acquisition_with_projection,
    ) as spy:
        two_way(
            suites, leases,
            row_assumption="purchase_price", row_values=rows,
            column_assumption="exit_cap_rate", column_values=columns,
            metric="equity_multiple",
        )

    assert spy.call_count == 1 + (len(rows) * len(columns))


def test_a_repeated_candidate_is_re_underwritten_not_reused() -> None:
    """No memoization: four candidates with only two distinct values still
    cost four analyses."""

    suites, leases = stable_deal()
    values = (0.06, 0.07, 0.06, 0.07)

    with patch.object(
        module,
        "analyze_lease_level_acquisition_with_projection",
        wraps=analyze_lease_level_acquisition_with_projection,
    ) as spy:
        one_way(
            suites, leases, assumption="exit_cap_rate", values=values,
            metric="equity_multiple",
        )

    assert spy.call_count == 1 + 4


def test_every_scenario_call_receives_the_full_input_set() -> None:
    """A scenario that dropped an input -- the leases, say -- would still
    produce numbers. Every call must carry all six contracts."""

    suites, leases, mkt = rollover_deal()

    with patch.object(
        module,
        "analyze_lease_level_acquisition_with_projection",
        wraps=analyze_lease_level_acquisition_with_projection,
    ) as spy:
        one_way(
            suites, leases, mkt=mkt, assumption="market_rent_psf",
            values=(24.0, 48.0), metric="equity_multiple",
        )

    for call in spy.call_args_list:
        scenario_terms, scenario_property, scenario_suites, scenario_leases = call.args
        assert isinstance(scenario_terms, AcquisitionTerms)
        assert isinstance(scenario_property, LeaseLevelPropertyInputs)
        assert tuple(scenario_suites) == tuple(suites)
        assert tuple(scenario_leases) == tuple(leases)
        assert isinstance(call.kwargs["market_leasing"], MarketLeasingAssumptions)
        assert isinstance(
            call.kwargs["operating_inputs"], LeaseLevelOperatingInputs
        )


def test_each_scenario_perturbs_exactly_one_contract_from_the_baseline() -> None:
    """The anti-cumulative-mutation proof at the call boundary: for a
    market-rent run, every scenario's terms and operating inputs are the
    caller's own objects, and each scenario's market record differs from the
    baseline only in the target field."""

    suites, leases, mkt = rollover_deal()
    deal = terms()
    ops = operating()

    with patch.object(
        module,
        "analyze_lease_level_acquisition_with_projection",
        wraps=analyze_lease_level_acquisition_with_projection,
    ) as spy:
        run_lease_level_one_way_sensitivity(
            deal, property_inputs(), suites, leases, market_leasing=mkt,
            operating_inputs=ops, assumption="market_rent_psf",
            values=(24.0, 36.0, 48.0), metric="equity_multiple",
        )

    baseline_call, *scenario_calls = spy.call_args_list
    assert baseline_call.kwargs["market_leasing"] is mkt

    for call, expected_rent in zip(scenario_calls, (24.0, 36.0, 48.0), strict=True):
        assert call.args[0] is deal
        assert call.kwargs["operating_inputs"] is ops
        scenario_market = call.kwargs["market_leasing"]
        assert scenario_market.market_rent_psf == expected_rent
        assert scenario_market == dataclasses.replace(
            mkt, market_rent_psf=expected_rent
        )


def test_two_way_cells_all_start_from_the_same_baseline_contracts() -> None:
    suites, leases, mkt = rollover_deal()
    deal = terms()
    ops = operating()

    with patch.object(
        module,
        "analyze_lease_level_acquisition_with_projection",
        wraps=analyze_lease_level_acquisition_with_projection,
    ) as spy:
        run_lease_level_two_way_sensitivity(
            deal, property_inputs(), suites, leases, market_leasing=mkt,
            operating_inputs=ops,
            row_assumption="market_rent_psf", row_values=(24.0, 48.0),
            column_assumption="expense_growth", column_values=(0.0, 0.06),
            metric="equity_multiple",
        )

    _, *cells = spy.call_args_list
    expected = [(24.0, 0.0), (24.0, 0.06), (48.0, 0.0), (48.0, 0.06)]
    for call, (rent, growth) in zip(cells, expected, strict=True):
        assert call.args[0] is deal
        assert call.kwargs["market_leasing"] == dataclasses.replace(
            mkt, market_rent_psf=rent
        )
        assert call.kwargs["operating_inputs"] == operating(expense_growth=growth)


# =============================================================================
# Result retention -- scalars only
# =============================================================================


def test_a_result_cell_holds_a_scalar_and_nothing_else() -> None:
    """Section 38.8. The completed envelope exists during evaluation and is
    then reduced to one float; no projection or audit tree survives into the
    result."""

    suites, leases, mkt = rollover_deal()

    one = one_way(
        suites, leases, mkt=mkt, assumption="market_rent_psf",
        values=(24.0, 48.0), metric="equity_multiple",
    )
    two = two_way(
        suites, leases, mkt=mkt,
        row_assumption="market_rent_psf", row_values=(24.0, 48.0),
        column_assumption="exit_cap_rate", column_values=(0.06, 0.07),
        metric="equity_multiple",
    )

    for value in one.metric_values:
        assert value is None or isinstance(value, float)
    for row in two.matrix:
        for cell in row:
            assert cell is None or isinstance(cell, float)

    assert {field.name for field in dataclasses.fields(one)} == {
        "assumption", "metric", "baseline_assumption_value",
        "baseline_metric_value", "assumption_values", "metric_values",
    }
    assert {field.name for field in dataclasses.fields(two)} == {
        "row_assumption", "column_assumption", "metric", "baseline_row_value",
        "baseline_column_value", "baseline_metric_value", "row_values",
        "column_values", "matrix",
    }
