"""Detailed Operating Model V2.1 Gate 2 -- the Detailed operating schedule.

Restates
``docs/detailed_operating_model_v2_1_financial_conventions.md``'s Revenue,
Vacancy and Credit Loss, Operating Expense, NOI, and Projection Horizon
conventions exactly; that document governs on any discrepancy. This module
contains no debt, exit-value, transaction-cost, or return-metric logic --
only the property-level revenue/expense build that produces
``OperatingProjection``.
"""

from __future__ import annotations

from math import inf

from ..contracts import DetailedOperatingInputs
from .contracts import OperatingProjection, ensure_finite


def _growth_factor(growth: float, exponent: int) -> float:
    """Return ``(1 + growth) ** exponent``.

    Mirrors ``engine/noi.py``'s ``_growth_factor`` exactly, for the same
    reason: CPython's ``float ** int`` raises ``OverflowError`` instead of
    returning ``inf`` when the mathematical result exceeds double precision.
    Since ``revenue_growth > -1``/``expense_growth > -1`` is already
    guaranteed by the input domain, the base is always positive, so an
    overflow can only mean the true result is unrepresentably large and
    positive; it is surfaced as ``inf`` here so ``ensure_finite`` can catch
    and reject it explicitly, exactly as the Quick NOI forecast does.
    """

    try:
        return (1 + growth) ** exponent
    except OverflowError:
        return inf


def build_detailed_operating_projection(
    detailed_inputs: DetailedOperatingInputs,
    *,
    hold_period: int,
    purchase_price: float,
) -> OperatingProjection:
    """Return the Detailed operating schedule for one ``DetailedOperatingInputs``.

    Projects Years 1 through ``hold_period + 1`` (the Projection Horizon
    convention): every ``_by_year`` field on the returned
    ``OperatingProjection`` has length ``hold_period`` (Years 1..H);
    ``exit_noi`` is the Year ``H + 1`` NOI, computed through the same
    full revenue/expense build as every other year -- never approximated by
    applying a single blended rate to ``NOI_H``.
    """

    projection_years = hold_period + 1

    gross_potential_rent_by_year: list[float] = []
    other_income_by_year: list[float] = []
    vacancy_credit_loss_by_year: list[float] = []
    effective_gross_income_by_year: list[float] = []
    property_taxes_by_year: list[float] = []
    insurance_by_year: list[float] = []
    utilities_by_year: list[float] = []
    repairs_maintenance_by_year: list[float] = []
    other_operating_expenses_by_year: list[float] = []
    management_fee_by_year: list[float] = []
    total_operating_expenses_by_year: list[float] = []
    noi_by_year: list[float] = []

    for year in range(1, projection_years + 1):
        year_index = year - 1
        revenue_factor = _growth_factor(detailed_inputs.revenue_growth, year_index)
        expense_factor = _growth_factor(detailed_inputs.expense_growth, year_index)

        gpr_y = ensure_finite(
            f"gross_potential_rent_by_year[{year_index}]",
            detailed_inputs.gross_potential_rent * revenue_factor,
        )
        other_income_y = ensure_finite(
            f"other_income_by_year[{year_index}]",
            detailed_inputs.other_income * revenue_factor,
        )
        vacancy_credit_loss_y = ensure_finite(
            f"vacancy_credit_loss_by_year[{year_index}]",
            gpr_y * detailed_inputs.vacancy_credit_loss_pct,
        )
        egi_y = ensure_finite(
            f"effective_gross_income_by_year[{year_index}]",
            gpr_y - vacancy_credit_loss_y + other_income_y,
        )

        property_taxes_y = ensure_finite(
            f"property_taxes_by_year[{year_index}]",
            detailed_inputs.property_taxes * expense_factor,
        )
        insurance_y = ensure_finite(
            f"insurance_by_year[{year_index}]",
            detailed_inputs.insurance * expense_factor,
        )
        utilities_y = ensure_finite(
            f"utilities_by_year[{year_index}]",
            detailed_inputs.utilities * expense_factor,
        )
        repairs_maintenance_y = ensure_finite(
            f"repairs_maintenance_by_year[{year_index}]",
            detailed_inputs.repairs_maintenance * expense_factor,
        )
        other_operating_expenses_y = ensure_finite(
            f"other_operating_expenses_by_year[{year_index}]",
            detailed_inputs.other_operating_expenses * expense_factor,
        )
        management_fee_y = ensure_finite(
            f"management_fee_by_year[{year_index}]",
            egi_y * detailed_inputs.management_fee_pct,
        )

        total_operating_expenses_y = ensure_finite(
            f"total_operating_expenses_by_year[{year_index}]",
            property_taxes_y
            + insurance_y
            + utilities_y
            + repairs_maintenance_y
            + other_operating_expenses_y
            + management_fee_y,
        )
        noi_y = ensure_finite(
            f"noi_by_year[{year_index}]", egi_y - total_operating_expenses_y
        )

        gross_potential_rent_by_year.append(gpr_y)
        other_income_by_year.append(other_income_y)
        vacancy_credit_loss_by_year.append(vacancy_credit_loss_y)
        effective_gross_income_by_year.append(egi_y)
        property_taxes_by_year.append(property_taxes_y)
        insurance_by_year.append(insurance_y)
        utilities_by_year.append(utilities_y)
        repairs_maintenance_by_year.append(repairs_maintenance_y)
        other_operating_expenses_by_year.append(other_operating_expenses_y)
        management_fee_by_year.append(management_fee_y)
        total_operating_expenses_by_year.append(total_operating_expenses_y)
        noi_by_year.append(noi_y)

    # Year H+1 is sale-only: it is exit_noi, never a member of noi_by_year
    # (or any other _by_year field) below.
    exit_noi = noi_by_year[-1]
    going_in_cap_rate = ensure_finite(
        "going_in_cap_rate", noi_by_year[0] / purchase_price
    )

    return OperatingProjection(
        gross_potential_rent_by_year=tuple(gross_potential_rent_by_year[:hold_period]),
        other_income_by_year=tuple(other_income_by_year[:hold_period]),
        vacancy_credit_loss_by_year=tuple(vacancy_credit_loss_by_year[:hold_period]),
        effective_gross_income_by_year=tuple(effective_gross_income_by_year[:hold_period]),
        property_taxes_by_year=tuple(property_taxes_by_year[:hold_period]),
        insurance_by_year=tuple(insurance_by_year[:hold_period]),
        utilities_by_year=tuple(utilities_by_year[:hold_period]),
        repairs_maintenance_by_year=tuple(repairs_maintenance_by_year[:hold_period]),
        other_operating_expenses_by_year=tuple(
            other_operating_expenses_by_year[:hold_period]
        ),
        management_fee_by_year=tuple(management_fee_by_year[:hold_period]),
        total_operating_expenses_by_year=tuple(
            total_operating_expenses_by_year[:hold_period]
        ),
        noi_by_year=tuple(noi_by_year[:hold_period]),
        exit_noi=exit_noi,
        going_in_cap_rate=going_in_cap_rate,
    )
