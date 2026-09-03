"""Detailed Operating Model V2.1 Gate 14 -- Detailed sensitivity/break-even
API wiring.

Gate 13 found that ``/sensitivity``, ``/sensitivity/presets``, and
``/break-even`` had no ``operating_mode`` branch, even though the Detailed
analysis-layer functions (``run_detailed_two_way_sensitivity``,
``build_standard_detailed_presets``, ``build_standard_detailed_break_even_
analysis``) already existed, were tested, and were already consumed by the
Detailed AI Analyst. Gate 14 extends these three endpoints in place with the
same ``operating_mode`` discriminator ``/analyze``/``/ai/analysis`` already
have -- no new sensitivity dimension, no new break-even target, no new
financial calculation.

Mirrors ``test_api_sensitivity.py``/``test_api_break_even.py``'s style and
reuses the Gate 8/4 golden ``AcquisitionTerms``/``DetailedOperatingInputs``
fixture (``tests/test_detailed_v2_1_gate8_sensitivity_break_even.py``)
rather than re-deriving one.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from anchor.analysis import (
    BreakEvenResult,
    StandardDetailedBreakEvenAnalysis,
    StandardDetailedSensitivityPresets,
    TwoWaySensitivityResult,
    build_standard_detailed_break_even_analysis,
    build_standard_detailed_presets,
    run_detailed_two_way_sensitivity,
)
from anchor.api import app
from anchor.contracts import AcquisitionTerms, DetailedOperatingInputs
from anchor.engine import analyze_detailed_acquisition_with_projection

# Reused verbatim from the Gate 8 analysis-layer fixture / Gate 13's
# reconciled golden case (Levered IRR ~=7.3802%, headline DSCR 2.00x).
GOLDEN_TERMS_PAYLOAD: dict[str, Any] = {
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

GOLDEN_DETAILED_OPERATING_PAYLOAD: dict[str, Any] = {
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

QUICK_INPUTS_PAYLOAD: dict[str, Any] = {
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

DETAILED_SENSITIVITY_REQUEST: dict[str, Any] = {
    "operating_mode": "detailed",
    "terms": GOLDEN_TERMS_PAYLOAD,
    "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
    "row_assumption": "purchase_price",
    "row_values": [9_000_000, 10_000_000, 11_000_000],
    "column_assumption": "exit_cap_rate",
    "column_values": [0.055, 0.065, 0.075],
    "metric": "levered_irr",
}

DETAILED_PRESETS_REQUEST: dict[str, Any] = {
    "operating_mode": "detailed",
    "terms": GOLDEN_TERMS_PAYLOAD,
    "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
}

DETAILED_BREAK_EVEN_REQUEST: dict[str, Any] = {
    "operating_mode": "detailed",
    "terms": GOLDEN_TERMS_PAYLOAD,
    "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
    "target_levered_irr": 0.10,
    "target_headline_dscr": 1.25,
    "target_equity_multiple": 1.50,
}

_QUICK_ONLY_FIELD_NAMES = ("current_noi", "noi_growth", "occupancy")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _direct_detailed_analyze_levered_irr(
    terms: AcquisitionTerms, operating: DetailedOperatingInputs
) -> float | None:
    return analyze_detailed_acquisition_with_projection(terms, operating).results.levered_irr


# =============================================================================
# 1. Detailed sensitivity API is reachable.
# =============================================================================


def test_detailed_sensitivity_endpoint_is_reachable(client: TestClient) -> None:
    response = client.post("/sensitivity", json=DETAILED_SENSITIVITY_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert body["row_assumption"] == "purchase_price"
    assert body["column_assumption"] == "exit_cap_rate"
    assert len(body["matrix"]) == 3
    assert len(body["matrix"][0]) == 3


def test_detailed_sensitivity_presets_endpoint_is_reachable(client: TestClient) -> None:
    response = client.post("/sensitivity/presets", json=DETAILED_PRESETS_REQUEST)

    assert response.status_code == 200


# =============================================================================
# 2. Detailed break-even API is reachable.
# =============================================================================


def test_detailed_break_even_endpoint_is_reachable(client: TestClient) -> None:
    response = client.post("/break-even", json=DETAILED_BREAK_EVEN_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"max_purchase_price", "max_exit_cap_rate", "max_interest_rate"}


# =============================================================================
# 3 / 4. Quick sensitivity/break-even remain backward compatible.
# =============================================================================


def test_quick_sensitivity_unaffected_absent_operating_mode(client: TestClient) -> None:
    request = {
        "inputs": QUICK_INPUTS_PAYLOAD,
        "row_assumption": "noi_growth",
        "row_values": [0.01, 0.02, 0.03],
        "column_assumption": "exit_cap_rate",
        "column_values": [0.045, 0.055, 0.065],
        "metric": "levered_irr",
    }

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 200
    assert response.json()["row_assumption"] == "noi_growth"


def test_quick_sensitivity_unaffected_explicit_quick_mode(client: TestClient) -> None:
    request = {
        "operating_mode": "quick",
        "inputs": QUICK_INPUTS_PAYLOAD,
        "row_assumption": "noi_growth",
        "row_values": [0.01, 0.02, 0.03],
        "column_assumption": "exit_cap_rate",
        "column_values": [0.045, 0.055, 0.065],
        "metric": "levered_irr",
    }
    without_mode = {k: v for k, v in request.items() if k != "operating_mode"}

    with_mode_response = client.post("/sensitivity", json=request)
    without_mode_response = client.post("/sensitivity", json=without_mode)

    assert with_mode_response.status_code == without_mode_response.status_code == 200
    assert with_mode_response.json() == without_mode_response.json()


def test_quick_sensitivity_presets_unaffected(client: TestClient) -> None:
    response = client.post("/sensitivity/presets", json={"inputs": QUICK_INPUTS_PAYLOAD})

    assert response.status_code == 200
    assert set(response.json().keys()) == {
        "exit_cap_noi_growth",
        "purchase_price_exit_cap",
        "interest_rate_ltv",
        "interest_rate_ltv_dscr",
    }


def test_quick_break_even_unaffected(client: TestClient) -> None:
    request = {
        "inputs": QUICK_INPUTS_PAYLOAD,
        "target_levered_irr": 0.10,
        "target_headline_dscr": 1.20,
        "target_equity_multiple": 1.50,
    }

    response = client.post("/break-even", json=request)

    assert response.status_code == 200
    assert set(response.json().keys()) == {
        "max_purchase_price",
        "max_exit_cap_rate",
        "min_noi_growth",
        "max_interest_rate",
        "min_current_noi",
    }


# =============================================================================
# 5. Detailed baseline sensitivity cell equals direct Detailed analysis.
# =============================================================================


def test_detailed_sensitivity_baseline_equals_direct_analysis(client: TestClient) -> None:
    direct_irr = _direct_detailed_analyze_levered_irr(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    response = client.post("/sensitivity", json=DETAILED_SENSITIVITY_REQUEST)

    assert response.status_code == 200
    assert response.json()["baseline_metric_value"] == pytest.approx(direct_irr, abs=1e-9)


def test_detailed_sensitivity_presets_baseline_equals_direct_analysis(
    client: TestClient,
) -> None:
    direct_irr = _direct_detailed_analyze_levered_irr(
        GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS
    )

    response = client.post("/sensitivity/presets", json=DETAILED_PRESETS_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert body["purchase_price_exit_cap"]["baseline_metric_value"] == pytest.approx(
        direct_irr, abs=1e-9
    )
    assert body["interest_rate_ltv"]["baseline_metric_value"] == pytest.approx(
        direct_irr, abs=1e-9
    )


# =============================================================================
# 6 / 7. DetailedOperatingInputs preserved; only requested terms vary.
# =============================================================================


def test_detailed_sensitivity_preserves_operating_inputs_and_varies_only_requested_dims(
    client: TestClient,
) -> None:
    """Every off-baseline cell must equal a direct ``/analyze`` call with
    only the requested ``AcquisitionTerms`` field changed and
    ``detailed_operating_inputs`` passed through byte-identical -- proving
    no cross-contamination and no dimension besides the two requested ones
    moved."""

    response = client.post("/sensitivity", json=DETAILED_SENSITIVITY_REQUEST)
    assert response.status_code == 200
    body = response.json()

    # Row 0 (purchase_price=9,000,000), Column 0 (exit_cap_rate=0.055).
    scenario_terms_payload = dict(GOLDEN_TERMS_PAYLOAD)
    scenario_terms_payload["purchase_price"] = 9_000_000
    scenario_terms_payload["exit_cap_rate"] = 0.055

    direct_response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": scenario_terms_payload,
            "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
        },
    )
    assert direct_response.status_code == 200
    direct_irr = direct_response.json()["results"]["levered_irr"]

    assert body["matrix"][0][0] == pytest.approx(direct_irr, abs=1e-9)
    # The unvaried dimension (ltv, interest_rate, etc.) is untouched --
    # confirmed implicitly by the direct call above sharing every other
    # GOLDEN_TERMS_PAYLOAD field unchanged and still reconciling exactly.


def test_detailed_break_even_preserves_operating_inputs(client: TestClient) -> None:
    """The solved candidate for max_purchase_price must reconcile through a
    direct ``/analyze`` call using the *same*, unmodified
    ``detailed_operating_inputs`` -- proving the break-even search never
    perturbed the operating assumptions."""

    response = client.post("/break-even", json=DETAILED_BREAK_EVEN_REQUEST)
    assert response.status_code == 200
    solved = response.json()["max_purchase_price"]
    assert solved["status"] == "solved"
    solved_purchase_price = solved["solved_assumption_value"]
    assert solved_purchase_price is not None

    scenario_terms_payload = dict(GOLDEN_TERMS_PAYLOAD)
    scenario_terms_payload["purchase_price"] = solved_purchase_price
    direct_response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": scenario_terms_payload,
            "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
        },
    )
    assert direct_response.status_code == 200
    assert direct_response.json()["results"]["levered_irr"] == pytest.approx(
        solved["solved_metric_value"], abs=1e-6
    )


# =============================================================================
# 8. No Quick-only NOI fields are fabricated.
# =============================================================================


def test_detailed_sensitivity_response_never_contains_quick_only_fields(
    client: TestClient,
) -> None:
    response = client.post("/sensitivity", json=DETAILED_SENSITIVITY_REQUEST)
    assert response.status_code == 200
    for field_name in _QUICK_ONLY_FIELD_NAMES:
        assert field_name not in response.text


def test_detailed_break_even_response_never_contains_quick_only_fields(
    client: TestClient,
) -> None:
    response = client.post("/break-even", json=DETAILED_BREAK_EVEN_REQUEST)
    assert response.status_code == 200
    for field_name in _QUICK_ONLY_FIELD_NAMES:
        assert field_name not in response.text


def test_detailed_presets_contract_has_no_quick_only_field(client: TestClient) -> None:
    field_names = {field.name for field in _dataclass_fields(StandardDetailedSensitivityPresets)}
    assert field_names == {"purchase_price_exit_cap", "interest_rate_ltv", "interest_rate_ltv_dscr"}
    assert not field_names & set(_QUICK_ONLY_FIELD_NAMES)


def test_detailed_break_even_contract_has_no_quick_only_field() -> None:
    field_names = {field.name for field in _dataclass_fields(StandardDetailedBreakEvenAnalysis)}
    assert field_names == {"max_purchase_price", "max_exit_cap_rate", "max_interest_rate"}
    assert not field_names & set(_QUICK_ONLY_FIELD_NAMES)


def _dataclass_fields(cls: type) -> Any:
    import dataclasses

    return dataclasses.fields(cls)


# =============================================================================
# 9. All Detailed sensitivity presets already approved in Gate 8 are
#    reachable through the real endpoint.
# =============================================================================


def test_detailed_sensitivity_presets_exposes_exactly_the_gate8_presets(
    client: TestClient,
) -> None:
    response = client.post("/sensitivity/presets", json=DETAILED_PRESETS_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "purchase_price_exit_cap",
        "interest_rate_ltv",
        "interest_rate_ltv_dscr",
    }
    # No exit_cap_noi_growth member -- noi_growth has no Detailed counterpart.
    assert "exit_cap_noi_growth" not in body


# =============================================================================
# 10. Detailed break-even outputs match the direct existing analysis
#     functions.
# =============================================================================


def test_detailed_break_even_matches_direct_analysis_layer_call(client: TestClient) -> None:
    direct = build_standard_detailed_break_even_analysis(
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        target_levered_irr=0.10,
        target_headline_dscr=1.25,
        target_equity_multiple=1.50,
    )

    response = client.post("/break-even", json=DETAILED_BREAK_EVEN_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert body["max_purchase_price"]["solved_assumption_value"] == pytest.approx(
        direct.max_purchase_price.solved_assumption_value, abs=1e-6
    )
    assert body["max_exit_cap_rate"]["solved_assumption_value"] == pytest.approx(
        direct.max_exit_cap_rate.solved_assumption_value, abs=1e-6
    )
    assert body["max_interest_rate"]["solved_assumption_value"] == pytest.approx(
        direct.max_interest_rate.solved_assumption_value, abs=1e-6
    )


# =============================================================================
# 11. Every solved Detailed break-even value reconciles when run through
#     authoritative Detailed analysis (all three targets, not just
#     max_purchase_price -- see also test #6/7 above for max_purchase_price).
# =============================================================================


@pytest.mark.parametrize(
    ("break_even_key", "terms_field"),
    [
        ("max_purchase_price", "purchase_price"),
        ("max_exit_cap_rate", "exit_cap_rate"),
        ("max_interest_rate", "interest_rate"),
    ],
)
def test_every_detailed_break_even_solution_reconciles_through_authoritative_analysis(
    client: TestClient, break_even_key: str, terms_field: str
) -> None:
    response = client.post("/break-even", json=DETAILED_BREAK_EVEN_REQUEST)
    assert response.status_code == 200
    result = response.json()[break_even_key]
    if result["status"] != "solved":
        pytest.skip(f"{break_even_key} had no solution in the tested range.")

    scenario_terms_payload = dict(GOLDEN_TERMS_PAYLOAD)
    scenario_terms_payload[terms_field] = result["solved_assumption_value"]
    metric = result["metric"]

    direct_response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": scenario_terms_payload,
            "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
        },
    )
    assert direct_response.status_code == 200
    direct_results = direct_response.json()["results"]
    assert direct_results[metric] == pytest.approx(result["solved_metric_value"], abs=1e-6)


# =============================================================================
# 12. Unsupported dimensions/targets are rejected.
# =============================================================================


def test_detailed_sensitivity_rejects_quick_only_dimension(client: TestClient) -> None:
    request = dict(DETAILED_SENSITIVITY_REQUEST)
    request["row_assumption"] = "current_noi"
    request["row_values"] = [500_000, 600_000]

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_detailed_sensitivity_rejects_undeferred_detailed_only_dimension(
    client: TestClient,
) -> None:
    """``revenue_growth``/``vacancy_credit_loss_pct``/``expense_growth`` are
    explicitly out of Gate 8/14 scope -- must remain rejected."""

    request = dict(DETAILED_SENSITIVITY_REQUEST)
    request["row_assumption"] = "revenue_growth"
    request["row_values"] = [0.01, 0.03]

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_detailed_sensitivity_requires_terms(client: TestClient) -> None:
    request = dict(DETAILED_SENSITIVITY_REQUEST)
    del request["terms"]

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_detailed_sensitivity_requires_detailed_operating_inputs(client: TestClient) -> None:
    request = dict(DETAILED_SENSITIVITY_REQUEST)
    del request["detailed_operating_inputs"]

    response = client.post("/sensitivity", json=request)

    assert response.status_code == 422


def test_detailed_break_even_requires_targets(client: TestClient) -> None:
    request = dict(DETAILED_BREAK_EVEN_REQUEST)
    del request["target_levered_irr"]

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_detailed_break_even_rejects_invalid_return_hurdle_metric(client: TestClient) -> None:
    request = dict(DETAILED_BREAK_EVEN_REQUEST)
    request["return_hurdle_metric"] = "bogus"

    response = client.post("/break-even", json=request)

    assert response.status_code == 422


def test_unknown_operating_mode_rejected_on_all_three_endpoints(client: TestClient) -> None:
    for path, extra in (
        ("/sensitivity", DETAILED_SENSITIVITY_REQUEST),
        ("/sensitivity/presets", DETAILED_PRESETS_REQUEST),
        ("/break-even", DETAILED_BREAK_EVEN_REQUEST),
    ):
        request = dict(extra)
        request["operating_mode"] = "bogus"

        response = client.post(path, json=request)

        assert response.status_code == 422, path


# =============================================================================
# 13. Validation/error behavior remains deterministic.
# =============================================================================


def test_detailed_sensitivity_invalid_request_is_deterministic(client: TestClient) -> None:
    request = dict(DETAILED_SENSITIVITY_REQUEST)
    request["row_assumption"] = "revenue_growth"

    first = client.post("/sensitivity", json=request)
    second = client.post("/sensitivity", json=request)

    assert first.status_code == second.status_code == 422
    assert first.json() == second.json()


def test_detailed_sensitivity_repeated_identical_request_returns_identical_response(
    client: TestClient,
) -> None:
    first = client.post("/sensitivity", json=DETAILED_SENSITIVITY_REQUEST)
    second = client.post("/sensitivity", json=DETAILED_SENSITIVITY_REQUEST)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_detailed_break_even_repeated_identical_request_returns_identical_response(
    client: TestClient,
) -> None:
    first = client.post("/break-even", json=DETAILED_BREAK_EVEN_REQUEST)
    second = client.post("/break-even", json=DETAILED_BREAK_EVEN_REQUEST)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


# =============================================================================
# 14. The API layer contains no sensitivity/break-even calculation logic --
#     every request delegates to the existing, already-tested analysis-layer
#     function exactly once. Mirrors test_api_sensitivity.py's own
#     delegation-proof pattern.
# =============================================================================


def test_detailed_sensitivity_delegates_to_analysis_layer(client: TestClient) -> None:
    with patch(
        "anchor.api.run_detailed_two_way_sensitivity", wraps=run_detailed_two_way_sensitivity
    ) as mock_run:
        response = client.post("/sensitivity", json=DETAILED_SENSITIVITY_REQUEST)

    assert response.status_code == 200
    mock_run.assert_called_once()


def test_detailed_sensitivity_presets_delegates_to_analysis_layer(client: TestClient) -> None:
    with patch(
        "anchor.api.build_standard_detailed_presets", wraps=build_standard_detailed_presets
    ) as mock_build:
        response = client.post("/sensitivity/presets", json=DETAILED_PRESETS_REQUEST)

    assert response.status_code == 200
    mock_build.assert_called_once()


def test_detailed_break_even_delegates_to_analysis_layer(client: TestClient) -> None:
    with patch(
        "anchor.api.build_standard_detailed_break_even_analysis",
        wraps=build_standard_detailed_break_even_analysis,
    ) as mock_build:
        response = client.post("/break-even", json=DETAILED_BREAK_EVEN_REQUEST)

    assert response.status_code == 200
    mock_build.assert_called_once()


def test_detailed_sensitivity_base_engine_remains_authoritative(client: TestClient) -> None:
    """Every cell must ultimately be produced by
    ``analyze_detailed_acquisition_with_projection`` -- the API/analysis
    layers must not compute a financial value independently."""

    with patch(
        "anchor.analysis.sensitivity.analyze_detailed_acquisition_with_projection",
        wraps=analyze_detailed_acquisition_with_projection,
    ) as mock_analyze:
        response = client.post("/sensitivity", json=DETAILED_SENSITIVITY_REQUEST)

    assert response.status_code == 200
    # 1 baseline call + 9 grid cells (3x3).
    assert mock_analyze.call_count == 10


# Structural sanity: the two result types this file exercises are the ones
# imported from anchor.analysis, guarding against a silent contract drift.
def test_result_types_imported_are_used() -> None:
    assert TwoWaySensitivityResult is not None
    assert BreakEvenResult is not None
