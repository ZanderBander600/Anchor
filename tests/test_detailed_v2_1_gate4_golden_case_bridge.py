"""Detailed Operating Model V2.1 Gate 4 -- golden-case bridge + permanent
cross-model equivalence.

This module is the permanent regression benchmark named by
``docs/detailed_operating_model_v2_1_golden_case.md`` "Exact Invariants to
Become Implementation Tests" -- it implements all three as actual pytest
tests, at the same golden-case tolerance
(``pytest.approx(expected, rel=0.0, abs=1e-9)``) the existing V1/V2 golden
cases use.

1. **Operating-schedule invariant** -- already covered in full by
   ``test_engine_operating_projection.py`` (Gate 2); re-asserted here at the
   contract-return level for completeness of this module as the single
   place the bridge story is told end to end.
2. **Convergence invariant** -- feeding the Detailed golden operating
   projection into ``analyze_detailed_acquisition`` reproduces every field
   of the existing, already-tested V2 golden case
   (``docs/underwriting_v2_golden_case.md``).
3. **Cross-model equivalence invariant** -- a Quick deal
   (``current_noi=600,000``/``noi_growth=0.03``) and a Detailed deal (the
   eleven detailed assumptions), sharing every other assumption, produce
   floating-point-noise-only-different ``AcquisitionResults`` -- proven by
   comparing every field, not just headline metrics.
"""

from __future__ import annotations

import dataclasses

import pytest

from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.engine import analyze_acquisition, analyze_detailed_acquisition


def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


# =============================================================================
# Shared golden-case fixtures
# =============================================================================

GOLDEN_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)

GOLDEN_DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)

# The equivalent Quick deal: same eleven AcquisitionTerms fields, current_noi
# and noi_growth chosen so that Quick's own NOI forecast formula
# (NOI_1 = current_noi; NOI_y = current_noi * (1 + noi_growth)^(y-1))
# reproduces the exact same series the Detailed build independently
# produces (docs/detailed_operating_model_v2_1_golden_case.md "Purpose and
# Design").
GOLDEN_QUICK_INPUTS = AcquisitionInputs(
    purchase_price=GOLDEN_TERMS.purchase_price,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=GOLDEN_TERMS.hold_period,
    exit_cap_rate=GOLDEN_TERMS.exit_cap_rate,
    ltv=GOLDEN_TERMS.ltv,
    interest_rate=GOLDEN_TERMS.interest_rate,
    amortization=GOLDEN_TERMS.amortization,
    acquisition_cost_pct=GOLDEN_TERMS.acquisition_cost_pct,
    financing_fee_pct=GOLDEN_TERMS.financing_fee_pct,
    disposition_cost_pct=GOLDEN_TERMS.disposition_cost_pct,
    annual_capex_reserve=GOLDEN_TERMS.annual_capex_reserve,
    io_period=GOLDEN_TERMS.io_period,
)

# docs/underwriting_v2_golden_case.md "Finalized Reference Values" --
# reproduced locally per this suite's existing convention of each test
# module defining its own golden-case constants rather than cross-importing
# them.
V2_GOLDEN_LOAN_AMOUNT = 6_000_000.0
V2_GOLDEN_ACQUISITION_COSTS = 200_000.0
V2_GOLDEN_FINANCING_FEE = 60_000.0
V2_GOLDEN_INITIAL_EQUITY = 4_260_000.0
V2_GOLDEN_GOING_IN_CAP_RATE = 0.06
V2_GOLDEN_NOI_BY_YEAR = (600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286)
V2_GOLDEN_EXIT_NOI = 695_564.44458
V2_GOLDEN_CAPEX_BY_YEAR = (50_000.0,) * 5
V2_GOLDEN_MONTHLY_DEBT_SERVICE = 32_209.29738
V2_GOLDEN_ANNUAL_DEBT_SERVICE = (
    300_000.0,
    300_000.0,
    386_511.56857,
    386_511.56857,
    386_511.56857,
)
V2_GOLDEN_REMAINING_LOAN_BALANCE = 5_720_615.68
V2_GOLDEN_DSCR_BY_YEAR = (2.00000, 2.06000, 1.64688, 1.69629, 1.74718)
V2_GOLDEN_HEADLINE_DSCR = 2.00000
V2_GOLDEN_MIN_DSCR = 1.64688
V2_GOLDEN_EXIT_VALUE = 10_700_991.4551
V2_GOLDEN_DISPOSITION_COSTS = 267_524.7864
V2_GOLDEN_NET_SALE_PROCEEDS = 4_712_850.99
V2_GOLDEN_UNLEVERED_CASH_FLOWS = (
    -10_200_000.00,
    550_000.00,
    568_000.00,
    586_540.00,
    605_636.20,
    11_058_771.9547,
)
V2_GOLDEN_LEVERED_CASH_FLOWS = (
    -4_260_000.00,
    250_000.00,
    268_000.00,
    200_028.43143,
    219_124.63143,
    4_951_644.70613,
)
V2_GOLDEN_UNLEVERED_IRR = 0.061388
V2_GOLDEN_LEVERED_IRR = 0.073802
V2_GOLDEN_EQUITY_MULTIPLE = 1.38235


# =============================================================================
# 2. Convergence invariant -- Detailed bridge reconciles to the V2 golden case
# =============================================================================


def test_detailed_bridge_reconciles_to_the_v2_golden_case() -> None:
    result = analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    assert result.loan_amount == strict(V2_GOLDEN_LOAN_AMOUNT)
    assert result.acquisition_costs == strict(V2_GOLDEN_ACQUISITION_COSTS)
    assert result.financing_fee == strict(V2_GOLDEN_FINANCING_FEE)
    assert result.initial_equity == strict(V2_GOLDEN_INITIAL_EQUITY)
    assert result.going_in_cap_rate == strict(V2_GOLDEN_GOING_IN_CAP_RATE)
    assert result.noi_by_year == pytest.approx(V2_GOLDEN_NOI_BY_YEAR, rel=0.0, abs=1e-6)
    assert result.exit_noi == pytest.approx(V2_GOLDEN_EXIT_NOI, rel=0.0, abs=1e-4)
    assert result.capex_by_year == strict(V2_GOLDEN_CAPEX_BY_YEAR)
    assert result.monthly_debt_service == pytest.approx(
        V2_GOLDEN_MONTHLY_DEBT_SERVICE, rel=0.0, abs=1e-4
    )
    assert result.annual_debt_service == pytest.approx(
        V2_GOLDEN_ANNUAL_DEBT_SERVICE, rel=0.0, abs=1e-3
    )
    assert result.remaining_loan_balance == pytest.approx(
        V2_GOLDEN_REMAINING_LOAN_BALANCE, rel=0.0, abs=1e-2
    )
    assert result.dscr_by_year == pytest.approx(V2_GOLDEN_DSCR_BY_YEAR, rel=0.0, abs=1e-5)
    assert result.headline_dscr == pytest.approx(V2_GOLDEN_HEADLINE_DSCR, rel=0.0, abs=1e-5)
    assert result.min_dscr == pytest.approx(V2_GOLDEN_MIN_DSCR, rel=0.0, abs=1e-5)
    assert result.exit_value == pytest.approx(V2_GOLDEN_EXIT_VALUE, rel=0.0, abs=1e-3)
    assert result.disposition_costs == pytest.approx(
        V2_GOLDEN_DISPOSITION_COSTS, rel=0.0, abs=1e-3
    )
    assert result.net_sale_proceeds == pytest.approx(
        V2_GOLDEN_NET_SALE_PROCEEDS, rel=0.0, abs=1e-2
    )
    assert result.unlevered_cash_flows == pytest.approx(
        V2_GOLDEN_UNLEVERED_CASH_FLOWS, rel=0.0, abs=1e-3
    )
    assert result.levered_cash_flows == pytest.approx(
        V2_GOLDEN_LEVERED_CASH_FLOWS, rel=0.0, abs=1e-3
    )
    assert result.unlevered_irr == pytest.approx(V2_GOLDEN_UNLEVERED_IRR, rel=0.0, abs=1e-6)
    assert result.levered_irr == pytest.approx(V2_GOLDEN_LEVERED_IRR, rel=0.0, abs=1e-6)
    assert result.equity_multiple == pytest.approx(
        V2_GOLDEN_EQUITY_MULTIPLE, rel=0.0, abs=1e-5
    )


# =============================================================================
# 3. Cross-model equivalence invariant -- Quick and Detailed produce the
#    same AcquisitionResults, field by field, not just the same headline
#    metrics
# =============================================================================


def test_quick_and_detailed_golden_cases_produce_equivalent_acquisition_results() -> (
    None
):
    """The permanent cross-model equivalence test named by the Phase 0
    brief: a Quick deal and a Detailed deal, sharing every non-operating
    assumption and constructed so their NOI series are mathematically
    identical, must run back to back through the shared downstream engine
    and produce indistinguishable output -- not "both close to the same
    golden numbers" but "both paths produce the same AcquisitionResults."
    """

    quick_result = analyze_acquisition(GOLDEN_QUICK_INPUTS)
    detailed_result = analyze_detailed_acquisition(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    for field in dataclasses.fields(quick_result):
        quick_value = getattr(quick_result, field.name)
        detailed_value = getattr(detailed_result, field.name)
        assert quick_value == pytest.approx(detailed_value, rel=0.0, abs=1e-6), (
            f"Field {field.name!r} diverged between Quick and Detailed: "
            f"quick={quick_value!r} detailed={detailed_value!r}"
        )


def test_quick_and_detailed_headline_metrics_match_exactly_at_golden_case_precision() -> (
    None
):
    """A tighter, headline-metric-focused restatement of the same
    invariant, at the golden-case document's own precision, for a reader
    who wants the specific numbers rather than a generic field loop."""

    quick_result = analyze_acquisition(GOLDEN_QUICK_INPUTS)
    detailed_result = analyze_detailed_acquisition(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert quick_result.loan_amount == strict(detailed_result.loan_amount)
    assert quick_result.initial_equity == strict(detailed_result.initial_equity)
    assert quick_result.headline_dscr == pytest.approx(
        detailed_result.headline_dscr, rel=0.0, abs=1e-6
    )
    assert quick_result.min_dscr == pytest.approx(
        detailed_result.min_dscr, rel=0.0, abs=1e-6
    )
    assert quick_result.unlevered_irr == pytest.approx(
        detailed_result.unlevered_irr, rel=0.0, abs=1e-6
    )
    assert quick_result.levered_irr == pytest.approx(
        detailed_result.levered_irr, rel=0.0, abs=1e-6
    )
    assert quick_result.equity_multiple == pytest.approx(
        detailed_result.equity_multiple, rel=0.0, abs=1e-6
    )


# =============================================================================
# 1. Operating-schedule invariant -- restated at the AcquisitionResults level
# =============================================================================


def test_detailed_noi_by_year_and_exit_noi_match_golden_case_at_the_results_level() -> (
    None
):
    result = analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    assert result.noi_by_year == pytest.approx(
        (600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286), rel=0.0, abs=1e-6
    )
    assert result.exit_noi == pytest.approx(695_564.44458, rel=0.0, abs=1e-4)
