"""Detailed Operating Model V2.1 Gate 3 -- Quick/Detailed convergence.

Proves, per ``docs/detailed_operating_model_v2_1_architecture.md`` Section
3.1/3.2 and Section 11's Gate 3 acceptance criteria:

1. ``analyze_acquisition``'s output is bit-for-bit unchanged by the
   refactor (the existing V2 golden case, reproduced locally per this
   suite's convention).
2. ``analyze_acquisition(inputs)`` and
   ``analyze_acquisition_from_operating_projection(build_quick_operating_projection(inputs),
   acquisition_terms_from_inputs(inputs))`` produce identical results, for a
   range of inputs -- the refactor's own delegation proof.
3. ``analyze_detailed_acquisition``'s signature contains no
   ``AcquisitionInputs``/``current_noi``/``noi_growth``/``occupancy``
   parameter.
4. ``analyze_detailed_acquisition`` is callable end-to-end for the Detailed
   golden case (output not yet asserted against the V2 golden case -- that
   is Gate 4).
5. Both entry points converge on the identical
   ``analyze_acquisition_from_operating_projection``, called exactly once
   each.
6. ``calculate_capital_stack``/``calculate_debt_schedule`` genuinely accept
   a real ``AcquisitionTerms`` instance (the Section 2.2.2 signature
   narrowing), not merely an ``AcquisitionInputs`` duck-typed past it.
"""

from __future__ import annotations

import inspect
import typing
from unittest.mock import patch

import pytest

from anchor.contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    acquisition_terms_from_inputs,
)
from anchor.engine import AcquisitionResults, analyze_acquisition, analyze_detailed_acquisition
from anchor.engine import acquisition as acquisition_module
from anchor.engine.acquisition import analyze_acquisition_from_operating_projection
from anchor.engine.debt import calculate_capital_stack, calculate_debt_schedule
from anchor.engine.noi import build_quick_operating_projection


def strict(expected: object) -> object:
    return pytest.approx(expected, rel=0.0, abs=1e-9)


# =============================================================================
# 1. analyze_acquisition output is unchanged by the refactor -- V2 golden case
# =============================================================================

GOLDEN_V2_INPUTS = AcquisitionInputs(
    purchase_price=10_000_000.0,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
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


def test_analyze_acquisition_v2_golden_case_unchanged_by_gate_3_refactor() -> None:
    result = analyze_acquisition(GOLDEN_V2_INPUTS)

    assert result.loan_amount == strict(6_000_000.0)
    assert result.acquisition_costs == strict(200_000.0)
    assert result.financing_fee == strict(60_000.0)
    assert result.initial_equity == strict(4_260_000.0)
    assert result.noi_by_year == strict(
        (600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286)
    )
    assert result.exit_noi == pytest.approx(695_564.44458, rel=0.0, abs=1e-5)
    assert result.exit_value == pytest.approx(10_700_991.4551, rel=0.0, abs=1e-3)
    assert result.disposition_costs == pytest.approx(267_524.7864, rel=0.0, abs=1e-3)
    assert result.remaining_loan_balance == pytest.approx(
        5_720_615.68, rel=0.0, abs=1e-2
    )
    assert result.headline_dscr == pytest.approx(2.0, rel=0.0, abs=1e-5)
    assert result.min_dscr == pytest.approx(1.64688, rel=0.0, abs=1e-5)
    assert result.unlevered_irr == pytest.approx(0.061388, rel=0.0, abs=1e-6)
    assert result.levered_irr == pytest.approx(0.073802, rel=0.0, abs=1e-6)
    assert result.equity_multiple == pytest.approx(1.38235, rel=0.0, abs=1e-5)


# =============================================================================
# 2. analyze_acquisition == manual convergence call, for a range of inputs
# =============================================================================


def _variant_inputs() -> list[AcquisitionInputs]:
    return [
        GOLDEN_V2_INPUTS,
        AcquisitionInputs(  # V1-neutral, nine-field construction
            purchase_price=50_000_000.0,
            current_noi=2_500_000.0,
            occupancy=0.95,
            noi_growth=0.03,
            hold_period=5,
            exit_cap_rate=0.055,
            ltv=0.65,
            interest_rate=0.0525,
            amortization=30,
        ),
        AcquisitionInputs(  # zero leverage
            purchase_price=10_000_000.0,
            current_noi=600_000.0,
            occupancy=0.95,
            noi_growth=0.03,
            hold_period=5,
            exit_cap_rate=0.065,
            ltv=0.0,
            interest_rate=0.05,
            amortization=30,
        ),
        AcquisitionInputs(  # full leverage, IO period equal to hold period
            purchase_price=10_000_000.0,
            current_noi=600_000.0,
            occupancy=0.95,
            noi_growth=0.03,
            hold_period=5,
            exit_cap_rate=0.065,
            ltv=1.0,
            interest_rate=0.05,
            amortization=30,
            io_period=5,
        ),
    ]


@pytest.mark.parametrize("inputs", _variant_inputs())
def test_analyze_acquisition_equals_manual_convergence_call(
    inputs: AcquisitionInputs,
) -> None:
    via_analyze_acquisition = analyze_acquisition(inputs)

    operating_projection = build_quick_operating_projection(inputs)
    terms = acquisition_terms_from_inputs(inputs)
    via_manual_convergence = analyze_acquisition_from_operating_projection(
        operating_projection, terms
    )

    assert via_analyze_acquisition == via_manual_convergence


# =============================================================================
# 3. analyze_detailed_acquisition's signature excludes AcquisitionInputs and
#    current_noi/noi_growth/occupancy
# =============================================================================


def test_analyze_detailed_acquisition_signature_has_no_forbidden_parameter() -> None:
    signature = inspect.signature(analyze_detailed_acquisition)
    parameter_names = set(signature.parameters)

    assert parameter_names == {"terms", "detailed_inputs"}
    assert "current_noi" not in parameter_names
    assert "noi_growth" not in parameter_names
    assert "occupancy" not in parameter_names
    assert "inputs" not in parameter_names

    type_hints = typing.get_type_hints(analyze_detailed_acquisition)
    assert type_hints["terms"] is AcquisitionTerms
    assert type_hints["detailed_inputs"] is DetailedOperatingInputs
    assert AcquisitionInputs not in type_hints.values()


# =============================================================================
# 4. analyze_detailed_acquisition callable end-to-end for the Detailed
#    golden case (not yet asserted against the V2 golden case -- Gate 4)
# =============================================================================

GOLDEN_DETAILED_TERMS = AcquisitionTerms(
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


def test_analyze_detailed_acquisition_is_callable_end_to_end() -> None:
    result = analyze_detailed_acquisition(
        GOLDEN_DETAILED_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert isinstance(result, AcquisitionResults)
    assert len(result.noi_by_year) == 5
    assert result.noi_by_year[0] == strict(600_000.0)


# =============================================================================
# 5. Both entry points converge on analyze_acquisition_from_operating_projection
# =============================================================================


def test_analyze_acquisition_calls_the_shared_convergence_function_exactly_once() -> None:
    with patch.object(
        acquisition_module,
        "analyze_acquisition_from_operating_projection",
        wraps=acquisition_module.analyze_acquisition_from_operating_projection,
    ) as mock_convergence:
        analyze_acquisition(GOLDEN_V2_INPUTS)

    assert mock_convergence.call_count == 1


def test_analyze_detailed_acquisition_calls_the_shared_convergence_function_exactly_once() -> (
    None
):
    with patch.object(
        acquisition_module,
        "analyze_acquisition_from_operating_projection",
        wraps=acquisition_module.analyze_acquisition_from_operating_projection,
    ) as mock_convergence:
        analyze_detailed_acquisition(
            GOLDEN_DETAILED_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
        )

    assert mock_convergence.call_count == 1


# =============================================================================
# 6. calculate_capital_stack / calculate_debt_schedule genuinely accept a
#    real AcquisitionTerms instance -- the Section 2.2.2 signature narrowing
# =============================================================================


def test_calculate_capital_stack_accepts_a_real_acquisition_terms_instance() -> None:
    capital_stack = calculate_capital_stack(GOLDEN_DETAILED_TERMS)

    assert capital_stack.loan_amount == strict(6_000_000.0)
    assert capital_stack.acquisition_costs == strict(200_000.0)
    assert capital_stack.financing_fee == strict(60_000.0)
    assert capital_stack.initial_equity == strict(4_260_000.0)


def test_calculate_debt_schedule_accepts_a_real_acquisition_terms_instance() -> None:
    debt_schedule = calculate_debt_schedule(GOLDEN_DETAILED_TERMS)

    assert debt_schedule.annual_debt_service[0] == strict(300_000.0)
    assert debt_schedule.remaining_loan_balance == pytest.approx(
        5_720_615.68, rel=0.0, abs=1e-2
    )


def test_capital_stack_identical_whether_built_from_inputs_or_terms_directly() -> None:
    """The type narrowing changes nothing about the value produced -- an
    AcquisitionTerms built via the adapter and one built directly with the
    same numbers must produce identical CapitalStack/DebtSchedule results."""

    from_adapter = acquisition_terms_from_inputs(GOLDEN_V2_INPUTS)

    assert calculate_capital_stack(from_adapter) == calculate_capital_stack(
        GOLDEN_DETAILED_TERMS
    )
    assert calculate_debt_schedule(from_adapter) == calculate_debt_schedule(
        GOLDEN_DETAILED_TERMS
    )
