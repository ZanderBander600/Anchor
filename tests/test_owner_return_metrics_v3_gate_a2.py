"""Owner Return Metrics V3 Gate A2 -- deterministic engine layer.

Covers ``docs/owner_return_metrics_v3_financial_conventions.md`` and
``docs/owner_return_metrics_v3_golden_case.md`` exactly; those documents
govern on any discrepancy. Proves, in one place:

1. The pure calculation functions (``anchor.engine.returns``) in isolation.
2. Exactness against the V2.1 Detailed golden bridge case.
3. Exactness against the Phase 2 Quick golden case.
4. Quick/Detailed convergence -- economically identical deals produce
   identical new-metric series regardless of which mode produced
   ``noi_by_year``.
5. Terminal-year sale-proceeds exclusion (the central Gate A2 design rule).
6. Every specified edge case: zero denominators, negative recurring cash
   flow, all-cash acquisition, one-year hold, IO vs. no-IO, financing-fee
   vs. acquisition-cost denominator treatment, explicit zero CapEx.
7. No regression to any pre-existing ``AcquisitionResults`` field.
8. No persistence of the new metrics.
9. Contract shape/serialization correctness.
"""

from __future__ import annotations

import dataclasses

import pytest

from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.deals.contracts import Deal
from anchor.engine import AcquisitionResults, analyze_acquisition, analyze_detailed_acquisition
from anchor.engine.contracts import OwnerReturnMetrics
from anchor.engine.returns import (
    calculate_cumulative_operating_distributions_by_year,
    calculate_levered_cash_on_cash_by_year,
    calculate_owner_return_metrics,
    calculate_recurring_levered_cash_flows,
    calculate_recurring_unlevered_cash_flows,
    calculate_unlevered_acquisition_basis,
    calculate_unlevered_cash_yield_by_year,
    calculate_year_1_debt_yield,
)


def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


# =============================================================================
# Golden-case fixtures (values restated from
# docs/owner_return_metrics_v3_golden_case.md, which restates them from
# docs/detailed_operating_model_v2_1_golden_case.md; reproduced locally per
# this suite's existing convention -- see
# tests/test_detailed_v2_1_gate4_golden_case_bridge.py)
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

GOLDEN_INITIAL_EQUITY = 4_260_000.0
GOLDEN_LOAN_AMOUNT = 6_000_000.0
GOLDEN_ACQUISITION_COSTS = 200_000.0
GOLDEN_NOI_BY_YEAR = (600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286)
GOLDEN_CAPEX_BY_YEAR = (50_000.0,) * 5
GOLDEN_ANNUAL_DEBT_SERVICE = (
    300_000.0,
    300_000.0,
    386_511.5685687402,
    386_511.5685687402,
    386_511.5685687402,
)

GOLDEN_RECURRING_LEVERED_CF = (
    250_000.0,
    268_000.0,
    200_028.4314312598,
    219_124.6314312598,
    238_793.7174312598,
)
GOLDEN_LEVERED_COC = (
    0.05868544600938967,
    0.06291079812206572,
    0.0469550308524084,
    0.05143770690874642,
    0.05605486324677459,
)
GOLDEN_RECURRING_UNLEVERED_CF = (
    550_000.0,
    568_000.0,
    586_540.0,
    605_636.2,
    625_305.286,
)
GOLDEN_UNLEVERED_BASIS = 10_200_000.0
GOLDEN_UNLEVERED_CASH_YIELD = (
    0.05392156862745098,
    0.05568627450980392,
    0.05750392156862745,
    0.05937609803921568,
    0.061304439803921564,
)
GOLDEN_CUMULATIVE_OPERATING_DISTRIBUTIONS = (
    250_000.0,
    518_000.0,
    718_028.4314312598,
    937_153.0628625196,
    1_175_946.7802937794,
)
GOLDEN_YEAR_1_DEBT_YIELD = 0.10

# Pre-existing V2.1 golden values -- restated from
# tests/test_detailed_v2_1_gate4_golden_case_bridge.py -- used only for the
# "no regression" section (14) below; not recomputed, not re-derived.
GOLDEN_HEADLINE_DSCR = 2.00000
GOLDEN_EXIT_VALUE = 10_700_991.4551
GOLDEN_NET_SALE_PROCEEDS = 4_712_850.99
GOLDEN_LEVERED_IRR = 0.073802
GOLDEN_UNLEVERED_IRR = 0.061388
GOLDEN_EQUITY_MULTIPLE = 1.38235
GOLDEN_LEVERED_CASH_FLOWS_TERMINAL = 4_951_644.70613  # includes net sale proceeds


# =============================================================================
# 1. Pure calculation functions, in isolation
# =============================================================================


def test_calculate_recurring_levered_cash_flows_matches_golden_case() -> None:
    result = calculate_recurring_levered_cash_flows(
        noi_by_year=GOLDEN_NOI_BY_YEAR,
        capex_by_year=GOLDEN_CAPEX_BY_YEAR,
        annual_debt_service=GOLDEN_ANNUAL_DEBT_SERVICE,
    )

    assert result == strict(GOLDEN_RECURRING_LEVERED_CF)


def test_calculate_recurring_unlevered_cash_flows_matches_golden_case() -> None:
    result = calculate_recurring_unlevered_cash_flows(
        noi_by_year=GOLDEN_NOI_BY_YEAR, capex_by_year=GOLDEN_CAPEX_BY_YEAR
    )

    assert result == strict(GOLDEN_RECURRING_UNLEVERED_CF)


def test_calculate_unlevered_acquisition_basis_excludes_financing_fee() -> None:
    basis = calculate_unlevered_acquisition_basis(
        purchase_price=10_000_000.0, acquisition_costs=200_000.0
    )

    assert basis == strict(10_200_000.0)


def test_calculate_levered_cash_on_cash_by_year_matches_golden_case() -> None:
    result = calculate_levered_cash_on_cash_by_year(
        recurring_levered_cash_flows=GOLDEN_RECURRING_LEVERED_CF,
        initial_equity=GOLDEN_INITIAL_EQUITY,
    )

    assert result == strict(GOLDEN_LEVERED_COC)


def test_calculate_levered_cash_on_cash_by_year_zero_denominator_is_none() -> None:
    result = calculate_levered_cash_on_cash_by_year(
        recurring_levered_cash_flows=(100.0, -50.0, 0.0), initial_equity=0.0
    )

    assert result == (None, None, None)


def test_calculate_unlevered_cash_yield_by_year_matches_golden_case() -> None:
    result = calculate_unlevered_cash_yield_by_year(
        recurring_unlevered_cash_flows=GOLDEN_RECURRING_UNLEVERED_CF,
        unlevered_acquisition_basis=GOLDEN_UNLEVERED_BASIS,
    )

    assert result == strict(GOLDEN_UNLEVERED_CASH_YIELD)


def test_calculate_unlevered_cash_yield_by_year_zero_denominator_is_none() -> None:
    result = calculate_unlevered_cash_yield_by_year(
        recurring_unlevered_cash_flows=(100.0, -50.0), unlevered_acquisition_basis=0.0
    )

    assert result == (None, None)


def test_calculate_cumulative_operating_distributions_by_year_matches_golden_case() -> None:
    result = calculate_cumulative_operating_distributions_by_year(
        recurring_levered_cash_flows=GOLDEN_RECURRING_LEVERED_CF
    )

    assert result == strict(GOLDEN_CUMULATIVE_OPERATING_DISTRIBUTIONS)


def test_calculate_cumulative_operating_distributions_never_floors_negative() -> None:
    result = calculate_cumulative_operating_distributions_by_year(
        recurring_levered_cash_flows=(100.0, -300.0, 50.0)
    )

    assert result == strict((100.0, -200.0, -150.0))


def test_calculate_year_1_debt_yield_matches_golden_case() -> None:
    result = calculate_year_1_debt_yield(
        year_1_noi=GOLDEN_NOI_BY_YEAR[0], loan_amount=GOLDEN_LOAN_AMOUNT
    )

    assert result == strict(GOLDEN_YEAR_1_DEBT_YIELD)


def test_calculate_year_1_debt_yield_zero_loan_amount_is_none() -> None:
    result = calculate_year_1_debt_yield(year_1_noi=600_000.0, loan_amount=0.0)

    assert result is None


def test_calculate_owner_return_metrics_orchestrator_matches_golden_case() -> None:
    result = calculate_owner_return_metrics(
        noi_by_year=GOLDEN_NOI_BY_YEAR,
        capex_by_year=GOLDEN_CAPEX_BY_YEAR,
        annual_debt_service=GOLDEN_ANNUAL_DEBT_SERVICE,
        purchase_price=10_000_000.0,
        acquisition_costs=GOLDEN_ACQUISITION_COSTS,
        initial_equity=GOLDEN_INITIAL_EQUITY,
        loan_amount=GOLDEN_LOAN_AMOUNT,
    )

    assert isinstance(result, OwnerReturnMetrics)
    assert result.levered_cash_on_cash_by_year == strict(GOLDEN_LEVERED_COC)
    assert result.unlevered_cash_yield_by_year == strict(GOLDEN_UNLEVERED_CASH_YIELD)
    assert result.cumulative_operating_distributions_by_year == strict(
        GOLDEN_CUMULATIVE_OPERATING_DISTRIBUTIONS
    )
    assert result.year_1_debt_yield == strict(GOLDEN_YEAR_1_DEBT_YIELD)


# =============================================================================
# 2. Detailed golden case exactness (end-to-end, through the real engine)
# =============================================================================


def test_detailed_golden_case_owner_return_metrics_exact() -> None:
    result = analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    assert result.initial_equity == strict(GOLDEN_INITIAL_EQUITY)
    assert result.levered_cash_on_cash_by_year == strict(GOLDEN_LEVERED_COC)
    assert result.unlevered_cash_yield_by_year == strict(GOLDEN_UNLEVERED_CASH_YIELD)
    assert result.cumulative_operating_distributions_by_year == strict(
        GOLDEN_CUMULATIVE_OPERATING_DISTRIBUTIONS
    )
    assert result.year_1_debt_yield == strict(GOLDEN_YEAR_1_DEBT_YIELD)


# =============================================================================
# 3. Quick golden case exactness (bridge case, and the independent Phase 2
#    golden case)
# =============================================================================


def test_quick_bridge_case_owner_return_metrics_exact() -> None:
    result = analyze_acquisition(GOLDEN_QUICK_INPUTS)

    assert result.initial_equity == strict(GOLDEN_INITIAL_EQUITY)
    assert result.levered_cash_on_cash_by_year == strict(GOLDEN_LEVERED_COC)
    assert result.unlevered_cash_yield_by_year == strict(GOLDEN_UNLEVERED_CASH_YIELD)
    assert result.cumulative_operating_distributions_by_year == strict(
        GOLDEN_CUMULATIVE_OPERATING_DISTRIBUTIONS
    )
    assert result.year_1_debt_yield == strict(GOLDEN_YEAR_1_DEBT_YIELD)


def test_phase_2_quick_golden_case_owner_return_metrics_exact() -> None:
    """The independent Phase 2 golden case
    (``tests/test_engine_golden_case.py``) -- no transaction costs, no
    CapEx, no IO period, exercising the neutral-defaults path with a
    completely different set of numbers than the V2.1 bridge case."""

    inputs = AcquisitionInputs(
        purchase_price=50_000_000.0,
        current_noi=2_500_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=5,
        exit_cap_rate=0.055,
        ltv=0.65,
        interest_rate=0.0525,
        amortization=30,
    )

    result = analyze_acquisition(inputs)

    assert result.loan_amount == strict(32_500_000.0)
    assert result.initial_equity == strict(17_500_000.0)
    assert result.levered_cash_on_cash_by_year == strict(
        (
            0.019794603522662633,
            0.024080317808376918,
            0.028494603522662632,
            0.033041317808376915,
            0.03772443352266265,
        )
    )
    assert result.unlevered_cash_yield_by_year == strict(
        (0.05, 0.0515, 0.053045, 0.05463635, 0.05627544050000001)
    )
    assert result.cumulative_operating_distributions_by_year == pytest.approx(
        (
            346_405.561647,
            767_811.123293,
            1_266_466.68494,
            1_844_689.746586,
            2_504_867.333233,
        ),
        rel=0.0,
        abs=1e-6,
    )
    assert result.year_1_debt_yield == strict(0.07692307692307693)


# =============================================================================
# 4. Quick/Detailed convergence
# =============================================================================


def test_quick_and_detailed_owner_return_metrics_converge_exactly() -> None:
    """The metric layer must not know or care whether ``noi_by_year`` came
    from Quick's ``NoiForecast`` or Detailed's ``OperatingProjection`` --
    an economically equivalent deal must produce identical new-metric
    series either way (floating-point-noise-only difference, same
    tolerance the existing cross-model equivalence test uses)."""

    quick_result = analyze_acquisition(GOLDEN_QUICK_INPUTS)
    detailed_result = analyze_detailed_acquisition(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert quick_result.levered_cash_on_cash_by_year == pytest.approx(
        detailed_result.levered_cash_on_cash_by_year, rel=0.0, abs=1e-9
    )
    assert quick_result.unlevered_cash_yield_by_year == pytest.approx(
        detailed_result.unlevered_cash_yield_by_year, rel=0.0, abs=1e-9
    )
    assert quick_result.cumulative_operating_distributions_by_year == pytest.approx(
        detailed_result.cumulative_operating_distributions_by_year, rel=0.0, abs=1e-9
    )
    assert quick_result.year_1_debt_yield == pytest.approx(
        detailed_result.year_1_debt_yield, rel=0.0, abs=1e-9
    )


# =============================================================================
# 5. Terminal sale-proceeds exclusion -- the central Gate A2 design rule
# =============================================================================


def test_final_year_levered_coc_excludes_net_sale_proceeds() -> None:
    result = analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    final_year_coc = result.levered_cash_on_cash_by_year[-1]
    naive_coc_if_sale_included = result.levered_cash_flows[-1] / result.initial_equity

    assert final_year_coc == strict(GOLDEN_LEVERED_COC[-1])
    assert final_year_coc < 0.10  # ~5.6%, not the >100% a sale-inclusive figure would be
    assert naive_coc_if_sale_included > 1.0  # sanity: the excluded figure IS huge
    assert final_year_coc != pytest.approx(naive_coc_if_sale_included, rel=0.0, abs=1e-6)


def test_cumulative_operating_distributions_final_year_excludes_sale_proceeds() -> None:
    result = analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    assert result.cumulative_operating_distributions_by_year[-1] == strict(
        GOLDEN_CUMULATIVE_OPERATING_DISTRIBUTIONS[-1]
    )
    # The terminal levered cash flow (which DOES include net sale proceeds)
    # is over 4x the recurring-only cumulative total -- proof the sale was
    # never added in.
    assert result.levered_cash_flows[-1] > 4 * result.cumulative_operating_distributions_by_year[-1]


# =============================================================================
# 6. IO transition behavior
# =============================================================================


def test_io_to_amortizing_transition_reflected_without_special_casing() -> None:
    result = analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    # Years 1-2 (IO): flat debt service, flat-ish CoC growth from NOI growth alone.
    assert result.annual_debt_service[0] == strict(300_000.0)
    assert result.annual_debt_service[1] == strict(300_000.0)
    # Year 3 (amortizing begins): debt service jumps, CoC drops despite NOI growth.
    assert result.annual_debt_service[2] == strict(386_511.5685687402)
    assert result.levered_cash_on_cash_by_year[2] < result.levered_cash_on_cash_by_year[1]


def test_no_io_period_fully_amortizing_from_year_one() -> None:
    terms = dataclasses.replace(GOLDEN_TERMS, io_period=0)
    result = analyze_detailed_acquisition(terms, GOLDEN_DETAILED_OPERATING_INPUTS)

    assert result.annual_debt_service[0] == strict(386_511.5685687402)
    recurring_levered_cf_1 = GOLDEN_NOI_BY_YEAR[0] - 50_000.0 - 386_511.5685687402
    assert result.levered_cash_on_cash_by_year[0] == strict(
        recurring_levered_cf_1 / GOLDEN_INITIAL_EQUITY
    )


# =============================================================================
# 7. Denominator conventions
# =============================================================================


def test_financing_fee_included_in_initial_equity_excluded_from_unlevered_basis() -> None:
    with_fee = analyze_acquisition(GOLDEN_QUICK_INPUTS)
    no_fee_inputs = dataclasses.replace(GOLDEN_QUICK_INPUTS, financing_fee_pct=0.0)
    without_fee = analyze_acquisition(no_fee_inputs)

    assert with_fee.initial_equity == strict(4_260_000.0)
    assert without_fee.initial_equity == strict(4_200_000.0)
    assert with_fee.initial_equity != without_fee.initial_equity

    # Unlevered basis (and therefore the yield series) is unaffected by
    # financing_fee_pct -- it is debt-related and deliberately excluded.
    assert with_fee.unlevered_cash_yield_by_year == strict(
        without_fee.unlevered_cash_yield_by_year
    )


def test_acquisition_costs_included_in_both_initial_equity_and_unlevered_basis() -> None:
    with_cost = analyze_acquisition(GOLDEN_QUICK_INPUTS)
    no_cost_inputs = dataclasses.replace(GOLDEN_QUICK_INPUTS, acquisition_cost_pct=0.0)
    without_cost = analyze_acquisition(no_cost_inputs)

    assert with_cost.initial_equity == strict(4_260_000.0)
    assert without_cost.initial_equity == strict(4_060_000.0)

    assert with_cost.unlevered_cash_yield_by_year[0] == strict(0.05392156862745098)
    assert without_cost.unlevered_cash_yield_by_year[0] == strict(0.055)
    assert (
        with_cost.unlevered_cash_yield_by_year != without_cost.unlevered_cash_yield_by_year
    )


# =============================================================================
# 8. Zero-denominator edge cases (engine level)
# =============================================================================


def test_zero_initial_equity_makes_every_levered_coc_year_none() -> None:
    inputs = dataclasses.replace(
        GOLDEN_QUICK_INPUTS, ltv=1.0, acquisition_cost_pct=0.0, financing_fee_pct=0.0
    )

    result = analyze_acquisition(inputs)

    assert result.initial_equity == strict(0.0)
    assert result.levered_cash_on_cash_by_year == (None, None, None, None, None)
    # Unrelated metrics remain fully defined -- the None-ing is scoped to
    # the one metric with the zero denominator.
    assert all(v is not None for v in result.unlevered_cash_yield_by_year)


def test_zero_loan_amount_makes_year_1_debt_yield_none() -> None:
    inputs = dataclasses.replace(GOLDEN_QUICK_INPUTS, ltv=0.0)

    result = analyze_acquisition(inputs)

    assert result.loan_amount == strict(0.0)
    assert result.year_1_debt_yield is None


# =============================================================================
# 9. Negative recurring cash flow
# =============================================================================


def test_negative_recurring_levered_cash_flow_not_floored_positive_unlevered() -> None:
    """Aggressive leverage: debt service exceeds NOI - CapEx, so levered
    cash flow (and CoC) is negative every year, while unlevered cash flow
    (and yield) stays positive -- proving the two series are independent
    and neither is floored at zero."""

    inputs = AcquisitionInputs(
        purchase_price=10_000_000.0,
        current_noi=600_000.0,
        occupancy=0.95,
        noi_growth=0.0,
        hold_period=5,
        exit_cap_rate=0.065,
        ltv=0.90,
        interest_rate=0.10,
        amortization=10,
        acquisition_cost_pct=0.0,
        financing_fee_pct=0.0,
        disposition_cost_pct=0.0,
        annual_capex_reserve=50_000.0,
        io_period=0,
    )

    result = analyze_acquisition(inputs)

    assert result.initial_equity == strict(1_000_000.0)
    assert result.levered_cash_on_cash_by_year == strict(
        (-0.877227958323026,) * 5
    )
    assert result.unlevered_cash_yield_by_year == strict((0.055,) * 5)
    assert all(v < 0 for v in result.levered_cash_on_cash_by_year)
    assert all(v > 0 for v in result.unlevered_cash_yield_by_year)


def test_negative_recurring_unlevered_cash_flow_reduces_cumulative_distributions() -> None:
    """CapEx exceeding NOI: both recurring series go negative, and the
    cumulative operating distributions total declines every year --
    never floored at zero."""

    inputs = AcquisitionInputs(
        purchase_price=10_000_000.0,
        current_noi=600_000.0,
        occupancy=0.95,
        noi_growth=0.0,
        hold_period=5,
        exit_cap_rate=0.065,
        ltv=0.0,
        interest_rate=0.05,
        amortization=30,
        acquisition_cost_pct=0.02,
        financing_fee_pct=0.0,
        disposition_cost_pct=0.025,
        annual_capex_reserve=700_000.0,
        io_period=0,
    )

    result = analyze_acquisition(inputs)

    assert result.unlevered_cash_yield_by_year == strict(
        (-100_000.0 / 10_200_000.0,) * 5
    )
    assert result.cumulative_operating_distributions_by_year == strict(
        (-100_000.0, -200_000.0, -300_000.0, -400_000.0, -500_000.0)
    )
    # Strictly declining -- never floored, never reset.
    distributions = result.cumulative_operating_distributions_by_year
    assert all(
        distributions[i] > distributions[i + 1] for i in range(len(distributions) - 1)
    )


# =============================================================================
# 10. All-cash acquisition
# =============================================================================


def test_all_cash_acquisition_levered_coc_equals_unlevered_cash_yield() -> None:
    inputs = dataclasses.replace(GOLDEN_QUICK_INPUTS, ltv=0.0)

    result = analyze_acquisition(inputs)

    assert result.loan_amount == strict(0.0)
    assert result.financing_fee == strict(0.0)
    assert result.annual_debt_service == strict((0.0,) * 5)
    assert result.year_1_debt_yield is None
    # No leverage and no financing fee -> Initial Equity == Unlevered Basis
    # -> the two series are identical, year for year.
    assert result.levered_cash_on_cash_by_year == strict(
        result.unlevered_cash_yield_by_year
    )
    assert result.levered_cash_on_cash_by_year == strict(
        (
            0.05392156862745098,
            0.05568627450980392,
            0.05750392156862745,
            0.05937609803921568,
            0.06130443980392158,
        )
    )


# =============================================================================
# 11. One-year hold
# =============================================================================


def test_one_year_hold_recurring_metric_excludes_terminal_sale_proceeds() -> None:
    """Year 1 is simultaneously the only year and the final year -- the
    recurring formula must not special-case this; the sale-inclusive
    ``levered_cash_flows[1]`` must remain excluded even here."""

    inputs = dataclasses.replace(GOLDEN_QUICK_INPUTS, hold_period=1, io_period=0)

    result = analyze_acquisition(inputs)

    assert len(result.levered_cash_on_cash_by_year) == 1
    assert len(result.cumulative_operating_distributions_by_year) == 1
    assert result.levered_cash_on_cash_by_year[0] == strict(0.038377566063676004)
    assert result.cumulative_operating_distributions_by_year[0] == strict(
        163_488.43143125979
    )
    # Terminal levered cash flow (sale-inclusive) is over 20x the recurring
    # figure -- proof the sale proceeds were excluded from Year 1's CoC.
    assert result.levered_cash_flows[0 + 1] > 20 * (
        result.cumulative_operating_distributions_by_year[0]
    )


# =============================================================================
# 12. Explicit zero CapEx
# =============================================================================


def test_explicit_zero_capex_flows_through_unchanged() -> None:
    inputs = dataclasses.replace(GOLDEN_QUICK_INPUTS, annual_capex_reserve=0.0)

    result = analyze_acquisition(inputs)

    assert result.capex_by_year == strict((0.0,) * 5)
    assert result.unlevered_cash_yield_by_year[0] == strict(
        GOLDEN_NOI_BY_YEAR[0] / (10_000_000.0 + GOLDEN_ACQUISITION_COSTS)
    )
    assert result.levered_cash_on_cash_by_year[0] == strict(
        (GOLDEN_NOI_BY_YEAR[0] - 300_000.0) / GOLDEN_INITIAL_EQUITY
    )


# =============================================================================
# 13. High precision / no premature rounding
# =============================================================================


def test_internal_precision_is_not_rounded() -> None:
    result = analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    # Year 3's CoC has many significant digits after the decimal -- if the
    # engine ever starts rounding internally (e.g. to 4-6 dp for
    # "presentation-friendliness"), comparing against a coarsely-rounded
    # value would still fail this assertion.
    year_3_coc = result.levered_cash_on_cash_by_year[2]
    assert year_3_coc == strict(200_028.4314312598 / 4_260_000.0)
    assert year_3_coc != round(year_3_coc, 4)
    assert result.cumulative_operating_distributions_by_year[2] == strict(
        718_028.4314312598
    )


# =============================================================================
# 14. No regression to any pre-existing AcquisitionResults field
# =============================================================================


def test_no_regression_to_existing_return_and_debt_fields() -> None:
    result = analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    assert result.headline_dscr == pytest.approx(GOLDEN_HEADLINE_DSCR, rel=0.0, abs=1e-5)
    assert result.exit_value == pytest.approx(GOLDEN_EXIT_VALUE, rel=0.0, abs=1e-3)
    assert result.net_sale_proceeds == pytest.approx(
        GOLDEN_NET_SALE_PROCEEDS, rel=0.0, abs=1e-2
    )
    assert result.levered_irr == pytest.approx(GOLDEN_LEVERED_IRR, rel=0.0, abs=1e-5)
    assert result.unlevered_irr == pytest.approx(GOLDEN_UNLEVERED_IRR, rel=0.0, abs=1e-5)
    assert result.equity_multiple == pytest.approx(
        GOLDEN_EQUITY_MULTIPLE, rel=0.0, abs=1e-5
    )
    assert result.loan_amount == strict(GOLDEN_LOAN_AMOUNT)
    assert result.acquisition_costs == strict(GOLDEN_ACQUISITION_COSTS)
    assert result.financing_fee == strict(60_000.0)
    # The pre-existing terminal levered cash flow still includes net sale
    # proceeds, unchanged -- Gate A2 added a new series, it did not touch
    # this one.
    assert result.levered_cash_flows[-1] == pytest.approx(
        GOLDEN_LEVERED_CASH_FLOWS_TERMINAL, rel=0.0, abs=1e-2
    )


# =============================================================================
# 15. No persistence of the new metrics
# =============================================================================


def test_deal_contract_has_no_results_or_owner_metric_field() -> None:
    """A ``Deal`` persists assumptions only (``inputs``/``terms``/
    ``detailed_operating_inputs``) -- structurally, it cannot carry
    ``AcquisitionResults`` or any Owner Return Metrics field. Metrics
    regenerate deterministically from persisted assumptions on every
    reopen/analysis."""

    deal_field_names = {field.name for field in dataclasses.fields(Deal)}

    assert "results" not in deal_field_names
    assert "levered_cash_on_cash_by_year" not in deal_field_names
    assert "unlevered_cash_yield_by_year" not in deal_field_names
    assert "cumulative_operating_distributions_by_year" not in deal_field_names
    assert "year_1_debt_yield" not in deal_field_names


# =============================================================================
# 16. Contract shape / serialization correctness
# =============================================================================


def test_owner_return_metrics_contract_is_frozen_slotted_kw_only() -> None:
    assert dataclasses.is_dataclass(OwnerReturnMetrics)
    assert all(field.kw_only for field in dataclasses.fields(OwnerReturnMetrics))
    assert OwnerReturnMetrics.__slots__ == (
        "levered_cash_on_cash_by_year",
        "unlevered_cash_yield_by_year",
        "cumulative_operating_distributions_by_year",
        "year_1_debt_yield",
    )

    metrics = OwnerReturnMetrics(
        levered_cash_on_cash_by_year=(0.05,),
        unlevered_cash_yield_by_year=(0.05,),
        cumulative_operating_distributions_by_year=(100.0,),
        year_1_debt_yield=0.1,
    )
    assert not hasattr(metrics, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        metrics.year_1_debt_yield = 0.2  # type: ignore[misc]


def test_acquisition_results_carries_owner_return_metrics_fields() -> None:
    result_field_names = {field.name for field in dataclasses.fields(AcquisitionResults)}

    assert {
        "levered_cash_on_cash_by_year",
        "unlevered_cash_yield_by_year",
        "cumulative_operating_distributions_by_year",
        "year_1_debt_yield",
    } <= result_field_names


def test_owner_return_metrics_equal_for_equal_inputs_hashable_shape() -> None:
    """Two independently-computed results for the same inputs produce
    equal (not merely approximately-equal) tuples -- deterministic, no
    hidden non-determinism (timestamps, object identity, etc.) leaking
    into the new fields."""

    first = analyze_acquisition(GOLDEN_QUICK_INPUTS)
    second = analyze_acquisition(GOLDEN_QUICK_INPUTS)

    assert first.levered_cash_on_cash_by_year == second.levered_cash_on_cash_by_year
    assert first.unlevered_cash_yield_by_year == second.unlevered_cash_yield_by_year
    assert (
        first.cumulative_operating_distributions_by_year
        == second.cumulative_operating_distributions_by_year
    )
    assert first.year_1_debt_yield == second.year_1_debt_yield
