"""Detailed Operating Model V2.1 Gate 2 -- ``build_detailed_operating_projection``.

The golden-case test below reproduces
``docs/detailed_operating_model_v2_1_golden_case.md``'s Years 1-6 operating
schedule exactly, at the same ``pytest.approx(expected, rel=0.0, abs=1e-9)``
tolerance the existing V1/V2 golden-case tests use
(``docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md``
item 4). The edge-case tests below it are the explicit boundary coverage
named in the Gate 2 implementation instructions.

This module tests ``build_detailed_operating_projection`` in isolation --
no acquisition/debt/returns wiring exists yet (Gate 3).
"""

from __future__ import annotations

import pytest

from anchor.contracts import DetailedOperatingInputs
from anchor.engine.contracts import OperatingProjection
from anchor.engine.operating_projection import build_detailed_operating_projection

GOLDEN_DETAILED_INPUTS = DetailedOperatingInputs(
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

GOLDEN_HOLD_PERIOD = 5
GOLDEN_PURCHASE_PRICE = 10_000_000.0

# docs/detailed_operating_model_v2_1_golden_case.md "Years 1-6 Full
# Operating Schedule (full precision)" -- Years 1-5 only (Year 6 is
# exit-NOI-only, asserted separately as `exit_noi` below).
GOLDEN_GPR_BY_YEAR = (
    800_000.0,
    824_000.0,
    848_720.0,
    874_181.6,
    900_407.048,
)
GOLDEN_OTHER_INCOME_BY_YEAR = (
    20_000.0,
    20_600.0,
    21_218.0,
    21_854.54,
    22_510.1762,
)
GOLDEN_VACANCY_CREDIT_LOSS_BY_YEAR = (
    40_000.0,
    41_200.0,
    42_436.0,
    43_709.08,
    45_020.3524,
)
GOLDEN_EGI_BY_YEAR = (
    780_000.0,
    803_400.0,
    827_502.0,
    852_327.06,
    877_896.8718,
)
GOLDEN_PROPERTY_TAXES_BY_YEAR = (
    60_000.0,
    61_800.0,
    63_654.0,
    65_563.62,
    67_530.5286,
)
GOLDEN_INSURANCE_BY_YEAR = (
    20_000.0,
    20_600.0,
    21_218.0,
    21_854.54,
    22_510.1762,
)
GOLDEN_UTILITIES_BY_YEAR = (
    25_000.0,
    25_750.0,
    26_522.5,
    27_318.175,
    28_137.72025,
)
GOLDEN_REPAIRS_MAINTENANCE_BY_YEAR = (
    20_000.0,
    20_600.0,
    21_218.0,
    21_854.54,
    22_510.1762,
)
GOLDEN_OTHER_OPERATING_EXPENSES_BY_YEAR = (
    16_000.0,
    16_480.0,
    16_974.4,
    17_483.632,
    18_008.14096,
)
GOLDEN_MANAGEMENT_FEE_BY_YEAR = (
    39_000.0,
    40_170.0,
    41_375.1,
    42_616.353,
    43_894.84359,
)
GOLDEN_TOTAL_OPERATING_EXPENSES_BY_YEAR = (
    180_000.0,
    185_400.0,
    190_962.0,
    196_690.86,
    202_591.5858,
)
GOLDEN_NOI_BY_YEAR = (
    600_000.0,
    618_000.0,
    636_540.0,
    655_636.2,
    675_305.286,
)
GOLDEN_EXIT_NOI = 695_564.44458
GOLDEN_GOING_IN_CAP_RATE = 0.06


def build_golden_projection() -> OperatingProjection:
    return build_detailed_operating_projection(
        GOLDEN_DETAILED_INPUTS,
        hold_period=GOLDEN_HOLD_PERIOD,
        purchase_price=GOLDEN_PURCHASE_PRICE,
    )


def test_golden_case_years_1_to_5_reconcile_exactly() -> None:
    projection = build_golden_projection()

    assert projection.gross_potential_rent_by_year == pytest.approx(
        GOLDEN_GPR_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.other_income_by_year == pytest.approx(
        GOLDEN_OTHER_INCOME_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.vacancy_credit_loss_by_year == pytest.approx(
        GOLDEN_VACANCY_CREDIT_LOSS_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.effective_gross_income_by_year == pytest.approx(
        GOLDEN_EGI_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.property_taxes_by_year == pytest.approx(
        GOLDEN_PROPERTY_TAXES_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.insurance_by_year == pytest.approx(
        GOLDEN_INSURANCE_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.utilities_by_year == pytest.approx(
        GOLDEN_UTILITIES_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.repairs_maintenance_by_year == pytest.approx(
        GOLDEN_REPAIRS_MAINTENANCE_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.other_operating_expenses_by_year == pytest.approx(
        GOLDEN_OTHER_OPERATING_EXPENSES_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.management_fee_by_year == pytest.approx(
        GOLDEN_MANAGEMENT_FEE_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.total_operating_expenses_by_year == pytest.approx(
        GOLDEN_TOTAL_OPERATING_EXPENSES_BY_YEAR, rel=0.0, abs=1e-9
    )
    assert projection.noi_by_year == pytest.approx(GOLDEN_NOI_BY_YEAR, rel=0.0, abs=1e-9)


def test_golden_case_exit_noi_is_year_six_not_a_member_of_noi_by_year() -> None:
    projection = build_golden_projection()

    assert projection.exit_noi == pytest.approx(GOLDEN_EXIT_NOI, rel=0.0, abs=1e-5)
    assert len(projection.noi_by_year) == GOLDEN_HOLD_PERIOD
    assert projection.exit_noi not in projection.noi_by_year


def test_golden_case_exit_noi_equals_the_existing_v2_golden_case_exit_noi() -> None:
    """Because revenue_growth == expense_growth == noi_growth (3%) and
    vacancy/management percentages are constant, this proves the Detailed
    model's exit_noi equals the existing V2 golden case's
    current_noi * (1 + noi_growth)^hold_period exactly."""

    projection = build_golden_projection()
    v2_golden_exit_noi = 600_000.0 * 1.03**5

    assert projection.exit_noi == pytest.approx(v2_golden_exit_noi, rel=0.0, abs=1e-6)


def test_golden_case_going_in_cap_rate() -> None:
    projection = build_golden_projection()

    assert projection.going_in_cap_rate == pytest.approx(
        GOLDEN_GOING_IN_CAP_RATE, rel=0.0, abs=1e-9
    )


def test_year_one_reconciles_by_hand() -> None:
    """Independent reconciliation of the Year 1 arithmetic, mirroring the
    golden-case document's hand-worked derivation, not just a comparison
    against pre-computed constants."""

    projection = build_golden_projection()

    gpr_1 = 800_000.0
    vacancy_1 = 40_000.0
    other_income_1 = 20_000.0
    egi_1 = gpr_1 - vacancy_1 + other_income_1
    fixed_opex_1 = 60_000.0 + 20_000.0 + 25_000.0 + 20_000.0 + 16_000.0
    management_fee_1 = egi_1 * 0.05
    total_opex_1 = fixed_opex_1 + management_fee_1
    noi_1 = egi_1 - total_opex_1

    assert egi_1 == 780_000.0
    assert total_opex_1 == 180_000.0
    assert noi_1 == 600_000.0
    assert projection.noi_by_year[0] == pytest.approx(noi_1, rel=0.0, abs=1e-9)


# =============================================================================
# Edge cases
# =============================================================================


def _detailed_inputs(**overrides: float) -> DetailedOperatingInputs:
    base = {
        "gross_potential_rent": 800_000.0,
        "other_income": 20_000.0,
        "vacancy_credit_loss_pct": 0.05,
        "property_taxes": 60_000.0,
        "insurance": 20_000.0,
        "utilities": 25_000.0,
        "repairs_maintenance": 20_000.0,
        "other_operating_expenses": 16_000.0,
        "management_fee_pct": 0.05,
        "revenue_growth": 0.03,
        "expense_growth": 0.03,
    }
    base.update(overrides)
    return DetailedOperatingInputs(**base)


def test_zero_vacancy() -> None:
    projection = build_detailed_operating_projection(
        _detailed_inputs(vacancy_credit_loss_pct=0.0),
        hold_period=5,
        purchase_price=10_000_000.0,
    )

    assert projection.vacancy_credit_loss_by_year == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert projection.effective_gross_income_by_year[0] == pytest.approx(
        820_000.0, rel=0.0, abs=1e-9
    )  # GPR + Other Income, no deduction


def test_hundred_percent_vacancy() -> None:
    projection = build_detailed_operating_projection(
        _detailed_inputs(vacancy_credit_loss_pct=1.0),
        hold_period=5,
        purchase_price=10_000_000.0,
    )

    assert projection.vacancy_credit_loss_by_year[0] == pytest.approx(
        800_000.0, rel=0.0, abs=1e-9
    )
    # EGI_1 = GPR_1 - VacancyCreditLoss_1 + OtherIncome_1 = 800,000 - 800,000 + 20,000
    assert projection.effective_gross_income_by_year[0] == pytest.approx(
        20_000.0, rel=0.0, abs=1e-9
    )


def test_zero_other_income() -> None:
    projection = build_detailed_operating_projection(
        _detailed_inputs(other_income=0.0),
        hold_period=5,
        purchase_price=10_000_000.0,
    )

    assert projection.other_income_by_year == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert projection.effective_gross_income_by_year[0] == pytest.approx(
        760_000.0, rel=0.0, abs=1e-9
    )  # GPR_1 - Vacancy_1


def test_zero_management_fee() -> None:
    projection = build_detailed_operating_projection(
        _detailed_inputs(management_fee_pct=0.0),
        hold_period=5,
        purchase_price=10_000_000.0,
    )

    assert projection.management_fee_by_year == (0.0, 0.0, 0.0, 0.0, 0.0)
    # Total opex is now only the five fixed lines: 60,000+20,000+25,000+20,000+16,000
    assert projection.total_operating_expenses_by_year[0] == pytest.approx(
        141_000.0, rel=0.0, abs=1e-9
    )


def test_zero_expenses() -> None:
    projection = build_detailed_operating_projection(
        _detailed_inputs(
            property_taxes=0.0,
            insurance=0.0,
            utilities=0.0,
            repairs_maintenance=0.0,
            other_operating_expenses=0.0,
            management_fee_pct=0.0,
        ),
        hold_period=5,
        purchase_price=10_000_000.0,
    )

    assert projection.total_operating_expenses_by_year == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert projection.noi_by_year == pytest.approx(
        projection.effective_gross_income_by_year, rel=0.0, abs=1e-9
    )


def test_zero_growth() -> None:
    projection = build_detailed_operating_projection(
        _detailed_inputs(revenue_growth=0.0, expense_growth=0.0),
        hold_period=5,
        purchase_price=10_000_000.0,
    )

    assert projection.noi_by_year == pytest.approx(
        (600_000.0,) * 5, rel=0.0, abs=1e-9
    )
    assert projection.exit_noi == pytest.approx(600_000.0, rel=0.0, abs=1e-9)


def test_revenue_growth_differs_from_expense_growth() -> None:
    """The exact scenario the financial-conventions document flags as
    load-bearing for the "actual Year H+1 projection, never approximated"
    rule: once the two growth rates diverge, a single blended-rate
    approximation of exit_noi would silently drift from this."""

    projection = build_detailed_operating_projection(
        _detailed_inputs(revenue_growth=0.05, expense_growth=0.02),
        hold_period=3,
        purchase_price=10_000_000.0,
    )

    # Year 2 hand check: revenue lines grow 5%, expense lines grow 2%,
    # independently.
    gpr_2 = 800_000.0 * 1.05
    other_income_2 = 20_000.0 * 1.05
    vacancy_2 = gpr_2 * 0.05
    egi_2 = gpr_2 - vacancy_2 + other_income_2
    fixed_opex_2 = (60_000.0 + 20_000.0 + 25_000.0 + 20_000.0 + 16_000.0) * 1.02
    management_fee_2 = egi_2 * 0.05
    noi_2 = egi_2 - fixed_opex_2 - management_fee_2

    assert projection.noi_by_year[1] == pytest.approx(noi_2, rel=0.0, abs=1e-6)

    # A single-blended-rate approximation using noi_growth-style compounding
    # from Year 1 NOI would NOT reproduce the true Year 3 (exit) NOI here --
    # confirms the two growth rates are genuinely independent in the engine,
    # not silently collapsed to one effective rate.
    year_1_noi = projection.noi_by_year[0]
    naive_single_rate = (projection.noi_by_year[1] / year_1_noi) - 1.0
    approximated_exit_noi = year_1_noi * (1 + naive_single_rate) ** 3
    assert projection.exit_noi != pytest.approx(
        approximated_exit_noi, rel=0.0, abs=1e-2
    )


def test_negative_noi_allowed_when_expenses_exceed_revenue() -> None:
    projection = build_detailed_operating_projection(
        _detailed_inputs(
            gross_potential_rent=100_000.0,
            other_income=0.0,
            vacancy_credit_loss_pct=0.0,
            property_taxes=200_000.0,
            insurance=0.0,
            utilities=0.0,
            repairs_maintenance=0.0,
            other_operating_expenses=0.0,
            management_fee_pct=0.0,
        ),
        hold_period=2,
        purchase_price=10_000_000.0,
    )

    assert projection.noi_by_year[0] == pytest.approx(-100_000.0, rel=0.0, abs=1e-9)


def test_one_year_hold() -> None:
    projection = build_detailed_operating_projection(
        GOLDEN_DETAILED_INPUTS, hold_period=1, purchase_price=GOLDEN_PURCHASE_PRICE
    )

    assert len(projection.noi_by_year) == 1
    assert projection.noi_by_year[0] == pytest.approx(600_000.0, rel=0.0, abs=1e-9)
    # exit_noi is the Year 2 (H+1) figure, distinct from Year 1's noi_by_year[0].
    assert projection.exit_noi == pytest.approx(618_000.0, rel=0.0, abs=1e-6)
    assert projection.exit_noi != projection.noi_by_year[0]


def test_year_h_plus_one_is_computed_through_the_full_build_not_approximated() -> None:
    """Directly proves exit_noi is produced by running the entire
    revenue/expense build one further year, not by multiplying NOI_H by
    (1 + some rate) -- verified by hand-computing the Year 6 (H+1) figure
    from every line item independently, for a case where revenue/expense
    growth diverge (so a naive single-rate shortcut would visibly differ)."""

    projection = build_detailed_operating_projection(
        _detailed_inputs(revenue_growth=0.04, expense_growth=0.01),
        hold_period=5,
        purchase_price=10_000_000.0,
    )

    year = 6
    revenue_factor = 1.04**(year - 1)
    expense_factor = 1.01**(year - 1)
    gpr_6 = 800_000.0 * revenue_factor
    other_income_6 = 20_000.0 * revenue_factor
    vacancy_6 = gpr_6 * 0.05
    egi_6 = gpr_6 - vacancy_6 + other_income_6
    fixed_opex_6 = (60_000.0 + 20_000.0 + 25_000.0 + 20_000.0 + 16_000.0) * expense_factor
    management_fee_6 = egi_6 * 0.05
    noi_6 = egi_6 - fixed_opex_6 - management_fee_6

    assert projection.exit_noi == pytest.approx(noi_6, rel=0.0, abs=1e-6)
