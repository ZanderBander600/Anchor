"""Tests for the Phase 9A AI Analyst endpoint (``POST /ai/analysis``) in
``anchor.api``.

Mirrors ``test_api_break_even.py``'s style. No test in this module makes a
real OpenAI API call: the OpenAI provider is always faked, either by
patching ``anchor.api.generate_ai_analysis`` directly (for the
endpoint's own request/response contract) or by injecting a fake
``OpenAIAnalystProvider`` (to prove the endpoint builds a real,
deterministic context and calls the provider exactly once).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from anchor.ai.contracts import AIAnalysis, DealStory
from anchor.ai.provider import AIConfigurationError, AIProviderError
from anchor.api import app
from anchor.contracts import AcquisitionInputs

GOLDEN_INPUTS_PAYLOAD: dict[str, Any] = {
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

GOLDEN_INPUTS = AcquisitionInputs(
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

GENERIC_REQUEST: dict[str, Any] = {
    "inputs": GOLDEN_INPUTS_PAYLOAD,
    "target_levered_irr": 0.10,
    "target_headline_dscr": 1.20,
    "target_equity_multiple": 1.50,
}

VALID_ANALYSIS = AIAnalysis(
    executive_summary="Summary.",
    investment_view="View.",
    strengths=("Strength one.",),
    risks=("Risk one.",),
    return_drivers=("Driver one.",),
    downside_analysis="Downside.",
    capital_structure_analysis="Capital structure.",
    break_even_analysis="Break-even.",
    questions_to_investigate=("Question one.",),
    confidence_notes=("Note one.",),
    deal_story=DealStory(
        investment_view="Owner view.",
        key_strengths=("Story strength.",),
        key_risks=("Story risk.",),
        model_gap="Refinance is not modeled.",
    ),
)


class _RecordingProvider:
    """A fake provider that records every call and never touches the network."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def generate_analysis(self, *, system_prompt: str, user_prompt: str) -> AIAnalysis:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return VALID_ANALYSIS


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# =============================================================================
# Valid request / structured response
# =============================================================================


def test_ai_analysis_valid_request_returns_200(client: TestClient) -> None:
    with patch("anchor.api.generate_ai_analysis", return_value=VALID_ANALYSIS) as mock_generate:
        response = client.post("/ai/analysis", json=GENERIC_REQUEST)

    assert response.status_code == 200
    mock_generate.assert_called_once()


def test_ai_analysis_returns_the_structured_ai_analysis_shape(client: TestClient) -> None:
    with patch("anchor.api.generate_ai_analysis", return_value=VALID_ANALYSIS):
        response = client.post("/ai/analysis", json=GENERIC_REQUEST)

    body = response.json()
    assert set(body.keys()) == {
        "executive_summary",
        "investment_view",
        "strengths",
        "risks",
        "return_drivers",
        "downside_analysis",
        "capital_structure_analysis",
        "break_even_analysis",
        "questions_to_investigate",
        "confidence_notes",
        "deal_story",
    }
    assert body["executive_summary"] == "Summary."
    assert body["strengths"] == ["Strength one."]


def test_ai_analysis_response_nests_the_deal_story(client: TestClient) -> None:
    """Sprint B Gate B4: one ``/ai/analysis`` response carries both the full
    report and the concise Owner Summary Deal Story -- the frontend never
    makes (and the user never pays for) a second AI request."""

    with patch("anchor.api.generate_ai_analysis", return_value=VALID_ANALYSIS):
        response = client.post("/ai/analysis", json=GENERIC_REQUEST)

    deal_story = response.json()["deal_story"]
    assert deal_story == {
        "investment_view": "Owner view.",
        "key_strengths": ["Story strength."],
        "key_risks": ["Story risk."],
        "model_gap": "Refinance is not modeled.",
    }


def test_ai_analysis_provider_invoked_exactly_once(client: TestClient) -> None:
    with patch("anchor.api.generate_ai_analysis", return_value=VALID_ANALYSIS) as mock_generate:
        client.post("/ai/analysis", json=GENERIC_REQUEST)

    assert mock_generate.call_count == 1


def test_ai_analysis_repeated_mocked_request_is_deterministic(client: TestClient) -> None:
    with patch("anchor.api.generate_ai_analysis", return_value=VALID_ANALYSIS):
        first = client.post("/ai/analysis", json=GENERIC_REQUEST)
        second = client.post("/ai/analysis", json=GENERIC_REQUEST)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


# =============================================================================
# End-to-end deterministic context construction (real analyst/context code,
# fake OpenAI provider only)
# =============================================================================


def test_ai_analysis_builds_deterministic_context_and_calls_provider_once(
    client: TestClient,
) -> None:
    fake_provider = _RecordingProvider()

    with patch("anchor.ai.analyst.OpenAIAnalystProvider", return_value=fake_provider):
        response = client.post("/ai/analysis", json=GENERIC_REQUEST)

    assert response.status_code == 200
    assert len(fake_provider.calls) == 1

    user_prompt = fake_provider.calls[0]["user_prompt"]
    payload = json.loads(user_prompt[user_prompt.index("{") :])

    # Model-facing evidence is presentation-formatted, not raw decimals.
    assert payload["base_inputs"]["purchase_price"] == "$50.0M"
    assert payload["base_inputs"]["exit_cap_rate"] == "5.5%"
    assert payload["hurdle_targets"]["target_levered_irr"] == "10%"
    assert payload["hurdle_targets"]["target_equity_multiple"] == "1.50x"
    assert payload["hurdle_targets"]["target_headline_dscr"] == "1.20x"
    assert "levered_irr" in payload["base_results"]
    assert set(payload["break_even"].keys()) == {
        "max_purchase_price",
        "max_exit_cap_rate",
        "min_noi_growth",
        "max_interest_rate",
        "min_current_noi",
    }


# =============================================================================
# Invalid input / hurdle validation
# =============================================================================


def test_ai_analysis_invalid_acquisition_inputs_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, inputs=dict(GOLDEN_INPUTS_PAYLOAD, purchase_price=-5))

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_invalid_target_dscr_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, target_headline_dscr=0.0)

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_invalid_target_irr_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, target_levered_irr=-1.5)

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_missing_inputs_returns_422(client: TestClient) -> None:
    request = {key: value for key, value in GENERIC_REQUEST.items() if key != "inputs"}

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_missing_target_field_returns_422(client: TestClient) -> None:
    request = {key: value for key, value in GENERIC_REQUEST.items() if key != "target_headline_dscr"}

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_invalid_return_hurdle_metric_returns_422(client: TestClient) -> None:
    request = dict(GENERIC_REQUEST, return_hurdle_metric="unlevered_irr")

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


# =============================================================================
# AI configuration / provider failure
# =============================================================================


def test_ai_analysis_missing_configuration_returns_503(client: TestClient) -> None:
    with patch(
        "anchor.api.generate_ai_analysis",
        side_effect=AIConfigurationError("OPENAI_API_KEY is not configured."),
    ):
        response = client.post("/ai/analysis", json=GENERIC_REQUEST)

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_ai_analysis_provider_failure_returns_502_without_raw_stack_trace(
    client: TestClient,
) -> None:
    with patch(
        "anchor.api.generate_ai_analysis",
        side_effect=AIProviderError("The AI provider request failed (TimeoutError)."),
    ):
        response = client.post("/ai/analysis", json=GENERIC_REQUEST)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "Traceback" not in detail
    assert "api_key" not in detail.lower()


# =============================================================================
# Deterministic endpoints unaffected
# =============================================================================


def test_analyze_endpoint_still_works(client: TestClient) -> None:
    response = client.post("/analyze", json=GOLDEN_INPUTS_PAYLOAD)

    assert response.status_code == 200


def test_sensitivity_presets_endpoint_still_works(client: TestClient) -> None:
    response = client.post("/sensitivity/presets", json={"inputs": GOLDEN_INPUTS_PAYLOAD})

    assert response.status_code == 200


def test_break_even_endpoint_still_works(client: TestClient) -> None:
    request = {
        "inputs": GOLDEN_INPUTS_PAYLOAD,
        "target_levered_irr": 0.10,
        "target_headline_dscr": 1.20,
        "target_equity_multiple": 1.50,
    }

    response = client.post("/break-even", json=request)

    assert response.status_code == 200


# =============================================================================
# Detailed Operating Model V2.1 Gate 9 -- Detailed operating_mode
# =============================================================================

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

DETAILED_REQUEST: dict[str, Any] = {
    "operating_mode": "detailed",
    "terms": GOLDEN_TERMS_PAYLOAD,
    "detailed_operating_inputs": GOLDEN_DETAILED_OPERATING_PAYLOAD,
    "target_levered_irr": 0.10,
    "target_headline_dscr": 1.20,
    "target_equity_multiple": 1.50,
}


def test_ai_analysis_detailed_valid_request_returns_200(client: TestClient) -> None:
    with patch(
        "anchor.api.generate_detailed_ai_analysis", return_value=VALID_ANALYSIS
    ) as mock_generate:
        response = client.post("/ai/analysis", json=DETAILED_REQUEST)

    assert response.status_code == 200
    mock_generate.assert_called_once()


def test_ai_analysis_detailed_returns_the_same_structured_shape_as_quick(
    client: TestClient,
) -> None:
    with patch("anchor.api.generate_detailed_ai_analysis", return_value=VALID_ANALYSIS):
        detailed_response = client.post("/ai/analysis", json=DETAILED_REQUEST)
    with patch("anchor.api.generate_ai_analysis", return_value=VALID_ANALYSIS):
        quick_response = client.post("/ai/analysis", json=GENERIC_REQUEST)

    assert set(detailed_response.json().keys()) == set(quick_response.json().keys())


def test_ai_analysis_detailed_builds_deterministic_context_and_calls_provider_once(
    client: TestClient,
) -> None:
    fake_provider = _RecordingProvider()

    with patch("anchor.ai.analyst.OpenAIAnalystProvider", return_value=fake_provider):
        response = client.post("/ai/analysis", json=DETAILED_REQUEST)

    assert response.status_code == 200
    assert len(fake_provider.calls) == 1

    user_prompt = fake_provider.calls[0]["user_prompt"]
    payload = json.loads(user_prompt[user_prompt.index("{") :])

    assert payload["operating_mode"] == "detailed"
    assert payload["base_terms"]["purchase_price"] == "$10.0M"
    assert payload["base_detailed_operating_inputs"]["vacancy_credit_loss_pct"] == "5%"
    assert payload["operating_projection"]["noi_by_year"][0] == "$600.0K"
    assert "base_inputs" not in payload
    assert "current_noi" not in user_prompt
    assert '"noi_growth"' not in user_prompt


def test_ai_analysis_detailed_missing_terms_returns_422(client: TestClient) -> None:
    request = dict(DETAILED_REQUEST)
    del request["terms"]

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_detailed_missing_detailed_operating_inputs_returns_422(
    client: TestClient,
) -> None:
    request = dict(DETAILED_REQUEST)
    del request["detailed_operating_inputs"]

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_detailed_invalid_terms_field_returns_422_with_issues(
    client: TestClient,
) -> None:
    request = dict(DETAILED_REQUEST)
    request["terms"] = GOLDEN_TERMS_PAYLOAD | {"ltv": 1.5}

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(issue["field_id"] == "ltv" for issue in detail)


def test_ai_analysis_detailed_missing_target_field_returns_422(client: TestClient) -> None:
    request = dict(DETAILED_REQUEST)
    del request["target_headline_dscr"]

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_detailed_missing_configuration_returns_503(client: TestClient) -> None:
    with patch("anchor.ai.analyst.OpenAIAnalystProvider") as mock_provider_class:
        mock_provider_class.return_value.generate_analysis.side_effect = AIConfigurationError(
            "OPENAI_API_KEY is not configured."
        )
        response = client.post("/ai/analysis", json=DETAILED_REQUEST)

    assert response.status_code == 503


def test_ai_analysis_detailed_provider_failure_returns_502(client: TestClient) -> None:
    with patch("anchor.ai.analyst.OpenAIAnalystProvider") as mock_provider_class:
        mock_provider_class.return_value.generate_analysis.side_effect = AIProviderError(
            "The AI provider request failed."
        )
        response = client.post("/ai/analysis", json=DETAILED_REQUEST)

    assert response.status_code == 502


def test_ai_analysis_invalid_operating_mode_returns_422(client: TestClient) -> None:
    request = dict(DETAILED_REQUEST)
    request["operating_mode"] = "bogus"

    response = client.post("/ai/analysis", json=request)

    assert response.status_code == 422


def test_ai_analysis_quick_operating_mode_explicit_matches_absent(client: TestClient) -> None:
    with patch("anchor.api.generate_ai_analysis", return_value=VALID_ANALYSIS) as mock_generate:
        response = client.post(
            "/ai/analysis", json=GENERIC_REQUEST | {"operating_mode": "quick"}
        )

    assert response.status_code == 200
    mock_generate.assert_called_once()
