"""Owner Return Metrics V3 Gate A3 -- API serialization.

Covers ``docs/owner_return_metrics_v3_financial_conventions.md``. The four
Gate A2 fields (``levered_cash_on_cash_by_year``,
``unlevered_cash_yield_by_year``, ``cumulative_operating_distributions_by_year``,
``year_1_debt_yield``) are already flattened onto ``AcquisitionResults``, so
``POST /analyze`` already serializes them automatically for both operating
modes -- this module proves that (no backend transformation code was added
in Gate A3), that ``None`` serializes as JSON ``null`` (never coerced to
``0``), and that both modes expose exactly the same field set.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from anchor.api import app
from anchor.contracts import AcquisitionInputs
from anchor.engine import AcquisitionResults, analyze_acquisition, analyze_detailed_acquisition

# Phase 2 Quick golden case (tests/test_api.py) -- reused here to prove the
# API layer performs no calculation of its own for the new fields either.
QUICK_GOLDEN_PAYLOAD: dict[str, Any] = {
    "purchase_price": 50_000_000,
    "current_noi": 2_500_000,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.055,
    "ltv": 0.65,
    "interest_rate": 0.0525,
    "amortization": 30,
}
QUICK_GOLDEN_INPUTS = AcquisitionInputs(
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

# V2.1 Detailed bridge golden case (tests/test_owner_return_metrics_v3_gate_a2.py)
DETAILED_TERMS_PAYLOAD: dict[str, Any] = {
    "purchase_price": 10_000_000,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
    "acquisition_cost_pct": 0.02,
    "financing_fee_pct": 0.01,
    "disposition_cost_pct": 0.025,
    "annual_capex_reserve": 50_000,
    "io_period": 2,
}
DETAILED_OPERATING_PAYLOAD: dict[str, Any] = {
    "gross_potential_rent": 800_000,
    "other_income": 20_000,
    "vacancy_credit_loss_pct": 0.05,
    "property_taxes": 60_000,
    "insurance": 20_000,
    "utilities": 25_000,
    "repairs_maintenance": 20_000,
    "other_operating_expenses": 16_000,
    "management_fee_pct": 0.05,
    "revenue_growth": 0.03,
    "expense_growth": 0.03,
}

_OWNER_RETURN_FIELDS = (
    "levered_cash_on_cash_by_year",
    "unlevered_cash_yield_by_year",
    "cumulative_operating_distributions_by_year",
    "year_1_debt_yield",
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# =============================================================================
# Both modes expose the same field set
# =============================================================================


def test_quick_analyze_returns_all_owner_return_fields(client: TestClient) -> None:
    response = client.post("/analyze", json=QUICK_GOLDEN_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    for field in _OWNER_RETURN_FIELDS:
        assert field in body


def test_detailed_analyze_returns_all_owner_return_fields(client: TestClient) -> None:
    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": DETAILED_TERMS_PAYLOAD,
            "detailed_operating_inputs": DETAILED_OPERATING_PAYLOAD,
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    for field in _OWNER_RETURN_FIELDS:
        assert field in results


def test_quick_and_detailed_expose_identical_owner_return_field_set(
    client: TestClient,
) -> None:
    quick_body = client.post("/analyze", json=QUICK_GOLDEN_PAYLOAD).json()
    detailed_body = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": DETAILED_TERMS_PAYLOAD,
            "detailed_operating_inputs": DETAILED_OPERATING_PAYLOAD,
        },
    ).json()["results"]

    quick_fields = {f for f in _OWNER_RETURN_FIELDS if f in quick_body}
    detailed_fields = {f for f in _OWNER_RETURN_FIELDS if f in detailed_body}

    assert quick_fields == detailed_fields == set(_OWNER_RETURN_FIELDS)


# =============================================================================
# Golden values reconcile through the API layer (no recalculation)
# =============================================================================


def test_quick_analyze_owner_return_values_reconcile_with_engine(
    client: TestClient,
) -> None:
    response = client.post("/analyze", json=QUICK_GOLDEN_PAYLOAD)
    body = response.json()

    expected = analyze_acquisition(QUICK_GOLDEN_INPUTS)

    assert body["levered_cash_on_cash_by_year"] == pytest.approx(
        expected.levered_cash_on_cash_by_year, rel=0.0, abs=1e-9
    )
    assert body["unlevered_cash_yield_by_year"] == pytest.approx(
        expected.unlevered_cash_yield_by_year, rel=0.0, abs=1e-9
    )
    assert body["cumulative_operating_distributions_by_year"] == pytest.approx(
        expected.cumulative_operating_distributions_by_year, rel=0.0, abs=1e-9
    )
    assert body["year_1_debt_yield"] == pytest.approx(
        expected.year_1_debt_yield, rel=0.0, abs=1e-9
    )


def test_quick_analyze_owner_return_values_match_golden_case(client: TestClient) -> None:
    response = client.post("/analyze", json=QUICK_GOLDEN_PAYLOAD)
    body = response.json()

    assert body["levered_cash_on_cash_by_year"] == pytest.approx(
        (
            0.019794603522662633,
            0.024080317808376918,
            0.028494603522662632,
            0.033041317808376915,
            0.03772443352266265,
        ),
        rel=0.0,
        abs=1e-9,
    )
    assert body["year_1_debt_yield"] == pytest.approx(0.07692307692307693, rel=0.0, abs=1e-9)


def test_detailed_analyze_owner_return_values_reconcile_with_engine(
    client: TestClient,
) -> None:
    from anchor.contracts import AcquisitionTerms, DetailedOperatingInputs

    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": DETAILED_TERMS_PAYLOAD,
            "detailed_operating_inputs": DETAILED_OPERATING_PAYLOAD,
        },
    )
    results = response.json()["results"]

    terms = AcquisitionTerms(
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
    detailed_inputs = DetailedOperatingInputs(
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
    expected = analyze_detailed_acquisition(terms, detailed_inputs)

    assert results["levered_cash_on_cash_by_year"] == pytest.approx(
        expected.levered_cash_on_cash_by_year, rel=0.0, abs=1e-9
    )
    assert results["cumulative_operating_distributions_by_year"] == pytest.approx(
        expected.cumulative_operating_distributions_by_year, rel=0.0, abs=1e-9
    )
    assert results["year_1_debt_yield"] == pytest.approx(0.10, rel=0.0, abs=1e-9)


# =============================================================================
# None serializes as JSON null, never coerced to 0
# =============================================================================


def test_all_cash_deal_year_1_debt_yield_serializes_as_null(client: TestClient) -> None:
    payload = QUICK_GOLDEN_PAYLOAD | {"ltv": 0.0}

    response = client.post("/analyze", json=payload)
    body = response.json()

    assert body["year_1_debt_yield"] is None
    assert body["loan_amount"] == pytest.approx(0.0)


def test_zero_initial_equity_levered_coc_serializes_as_all_null(
    client: TestClient,
) -> None:
    payload = QUICK_GOLDEN_PAYLOAD | {
        "ltv": 1.0,
        "acquisition_cost_pct": 0.0,
        "financing_fee_pct": 0.0,
    }

    response = client.post("/analyze", json=payload)
    body = response.json()

    assert body["initial_equity"] == pytest.approx(0.0)
    assert body["levered_cash_on_cash_by_year"] == [None] * 5
    # A None value must never be silently coerced to 0 anywhere in the chain.
    assert 0 not in body["levered_cash_on_cash_by_year"]
    assert 0.0 not in body["levered_cash_on_cash_by_year"]


# =============================================================================
# No API-layer calculation
# =============================================================================


def test_analyze_result_fields_include_owner_return_fields_dynamically() -> None:
    """``AcquisitionResults.__dataclass_fields__`` already governs the
    response shape (``api.py`` uses ``response_model=AcquisitionResults |
    DetailedAcquisitionResults`` with no manual field list) -- proving the
    new fields required zero API-layer code, only the Gate A2 contract
    change."""

    result_fields = set(AcquisitionResults.__dataclass_fields__)

    assert set(_OWNER_RETURN_FIELDS) <= result_fields
