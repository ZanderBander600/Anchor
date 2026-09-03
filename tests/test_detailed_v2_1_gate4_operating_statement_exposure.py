"""Detailed Operating Model V2.1 Gate 4 -- Results + Operating Statement
Exposure.

Covers ``docs/detailed_operating_model_v2_1_architecture.md`` Section 2.1
and the Gate 4 instruction: expose the deterministic ``OperatingProjection``
to downstream consumers, via a higher-level ``DetailedAcquisitionResults``
envelope rather than contaminating ``AcquisitionResults`` with Detailed-only
line items. Quick's ``AcquisitionResults`` shape and ``analyze_acquisition``
are untouched. ``analyze_detailed_acquisition`` (Gate 3's public entry
point) keeps its exact prior signature and output -- now implemented as a
thin wrapper over the richer
``analyze_detailed_acquisition_with_projection`` (new, Gate 4), which
computes the operating projection exactly once and reuses it for both the
acquisition results and the envelope's own field.
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import patch

import pytest

from anchor.contracts import AcquisitionTerms, DetailedOperatingInputs
from anchor.engine import (
    AcquisitionResults,
    DetailedAcquisitionResults,
    analyze_detailed_acquisition,
    analyze_detailed_acquisition_with_projection,
)
from anchor.engine import acquisition as acquisition_module
from anchor.engine.contracts import OperatingProjection

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


def test_detailed_acquisition_results_contract_shape() -> None:
    contract_fields = fields(DetailedAcquisitionResults)

    assert tuple(field.name for field in contract_fields) == (
        "operating_projection",
        "results",
    )
    assert all(field.kw_only for field in contract_fields)
    assert DetailedAcquisitionResults.__slots__ == ("operating_projection", "results")


def test_with_projection_returns_both_operating_projection_and_results() -> None:
    envelope = analyze_detailed_acquisition_with_projection(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert isinstance(envelope, DetailedAcquisitionResults)
    assert isinstance(envelope.operating_projection, OperatingProjection)
    assert isinstance(envelope.results, AcquisitionResults)


def test_with_projection_operating_projection_matches_gate_2_golden_case() -> None:
    envelope = analyze_detailed_acquisition_with_projection(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert envelope.operating_projection.noi_by_year == pytest.approx(
        (600_000.0, 618_000.0, 636_540.0, 655_636.2, 675_305.286), rel=0.0, abs=1e-9
    )
    assert envelope.operating_projection.gross_potential_rent_by_year[0] == pytest.approx(
        800_000.0, rel=0.0, abs=1e-9
    )
    assert envelope.operating_projection.effective_gross_income_by_year[0] == pytest.approx(
        780_000.0, rel=0.0, abs=1e-9
    )
    assert envelope.operating_projection.exit_noi == pytest.approx(
        695_564.44458, rel=0.0, abs=1e-4
    )


def test_with_projection_results_matches_the_existing_v2_golden_case() -> None:
    envelope = analyze_detailed_acquisition_with_projection(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert envelope.results.loan_amount == pytest.approx(6_000_000.0)
    assert envelope.results.headline_dscr == pytest.approx(2.0, abs=1e-5)
    assert envelope.results.levered_irr == pytest.approx(0.073802, abs=1e-6)


def test_analyze_detailed_acquisition_is_unchanged_and_matches_the_envelope_results() -> (
    None
):
    """Gate 3's public entry point keeps its exact prior output -- it is
    now a thin wrapper, not a reimplementation."""

    direct_results = analyze_detailed_acquisition(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )
    envelope = analyze_detailed_acquisition_with_projection(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    assert direct_results == envelope.results


def test_analyze_detailed_acquisition_delegates_to_with_projection_exactly_once() -> None:
    with patch.object(
        acquisition_module,
        "analyze_detailed_acquisition_with_projection",
        wraps=acquisition_module.analyze_detailed_acquisition_with_projection,
    ) as mock_with_projection:
        analyze_detailed_acquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)

    assert mock_with_projection.call_count == 1


def test_with_projection_computes_the_operating_projection_exactly_once() -> None:
    """No duplicated computation between the envelope's own
    operating_projection field and the one analyze_acquisition_from_operating_projection
    consumes internally to produce results -- both must be the identical
    object, not two independently computed instances."""

    with patch.object(
        acquisition_module,
        "build_detailed_operating_projection",
        wraps=acquisition_module.build_detailed_operating_projection,
    ) as mock_build_projection:
        envelope = analyze_detailed_acquisition_with_projection(
            GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
        )

    assert mock_build_projection.call_count == 1
    # The results' own noi_by_year/exit_noi must be the same values the
    # envelope's operating_projection carries -- proof they came from one
    # shared computation, not two.
    assert envelope.results.noi_by_year == envelope.operating_projection.noi_by_year
    assert envelope.results.exit_noi == envelope.operating_projection.exit_noi
