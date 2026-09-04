"""Tests for the Phase 9A AI Analyst OpenAI provider adapter
(``anchor.ai.provider``).

Every test here uses a fake client object -- never the real ``openai`` SDK
or a network call -- per the "TESTING WITHOUT API SPEND" requirement.
Covers: configurable model, ``ANCHOR_AI_MODEL`` env var, missing API key
behavior, the structured-output JSON schema supplied to the Responses API,
converting a well-formed provider response into ``AIAnalysis``, and failing
cleanly on a malformed/unexpected provider response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from anchor.ai.contracts import AIAnalysis, DealStory
from anchor.ai.provider import (
    DEFAULT_MODEL,
    AIConfigurationError,
    AIProviderError,
    OpenAIAnalystProvider,
)

VALID_ANALYSIS_JSON: dict[str, Any] = {
    "executive_summary": "Summary.",
    "investment_view": "View.",
    "strengths": ["Strength one.", "Strength two."],
    "risks": ["Risk one."],
    "return_drivers": ["Driver one."],
    "downside_analysis": "Downside.",
    "capital_structure_analysis": "Capital structure.",
    "break_even_analysis": "Break-even.",
    "questions_to_investigate": ["Question one."],
    "confidence_notes": ["Note one."],
    "deal_story": {
        "investment_view": "Owner view.",
        "key_strengths": ["Story strength one."],
        "key_risks": ["Story risk one."],
        "model_gap": "Refinance is not modeled.",
    },
}


@dataclass
class _FakeResponse:
    output_text: str


@dataclass
class _FakeResponsesResource:
    response: _FakeResponse | Exception
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@dataclass
class _FakeClient:
    responses: _FakeResponsesResource


def _fake_client(output_text: str | Exception) -> _FakeClient:
    if isinstance(output_text, Exception):
        return _FakeClient(responses=_FakeResponsesResource(response=output_text))
    return _FakeClient(
        responses=_FakeResponsesResource(response=_FakeResponse(output_text=output_text))
    )


# =============================================================================
# Model configuration
# =============================================================================


def test_default_model_is_used_when_no_override_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANCHOR_AI_MODEL", raising=False)
    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client)

    provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert client.responses.calls[0]["model"] == DEFAULT_MODEL


def test_anchor_ai_model_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANCHOR_AI_MODEL", "gpt-custom-analyst")
    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client)

    provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert client.responses.calls[0]["model"] == "gpt-custom-analyst"


def test_explicit_model_argument_overrides_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANCHOR_AI_MODEL", "gpt-from-env")
    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client, model="gpt-explicit")

    provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert client.responses.calls[0]["model"] == "gpt-explicit"


# =============================================================================
# Missing API key
# =============================================================================


def test_missing_api_key_raises_configuration_error_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIAnalystProvider()  # no fake client -- must not reach the network

    with pytest.raises(AIConfigurationError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


# =============================================================================
# Structured-output schema
# =============================================================================


def test_generate_analysis_supplies_a_strict_json_schema() -> None:
    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client)

    provider.generate_analysis(system_prompt="sys", user_prompt="user")

    call = client.responses.calls[0]
    text_format = call["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    schema = text_format["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
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


def test_generate_analysis_schema_nests_the_deal_story_object() -> None:
    """Sprint B Gate B4: the concise Deal Story is one nested object inside
    the same strict schema -- one structured response, one provider call,
    never a second request the user pays for separately."""

    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client)

    provider.generate_analysis(system_prompt="sys", user_prompt="user")

    schema = client.responses.calls[0]["text"]["format"]["schema"]
    deal_story_schema = schema["properties"]["deal_story"]
    assert deal_story_schema["type"] == "object"
    assert deal_story_schema["additionalProperties"] is False
    assert set(deal_story_schema["required"]) == {
        "investment_view",
        "key_strengths",
        "key_risks",
        "model_gap",
    }
    # ``model_gap`` must be expressible as "no gap exists" without being
    # dropped from ``required`` (OpenAI strict mode forbids that).
    assert deal_story_schema["properties"]["model_gap"]["type"] == ["string", "null"]


def test_generate_analysis_sends_system_and_user_prompts() -> None:
    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client)

    provider.generate_analysis(system_prompt="the system prompt", user_prompt="the user prompt")

    call = client.responses.calls[0]
    roles_and_content = [(item["role"], item["content"]) for item in call["input"]]
    assert ("system", "the system prompt") in roles_and_content
    assert ("user", "the user prompt") in roles_and_content


def test_generate_analysis_requests_medium_reasoning_effort() -> None:
    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client)

    provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert client.responses.calls[0]["reasoning"]["effort"] == "medium"


# =============================================================================
# Response -> AIAnalysis conversion
# =============================================================================


def test_well_formed_response_converts_to_ai_analysis() -> None:
    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client)

    analysis = provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert isinstance(analysis, AIAnalysis)
    assert analysis.executive_summary == "Summary."
    assert analysis.strengths == ("Strength one.", "Strength two.")
    assert analysis.risks == ("Risk one.",)
    assert analysis.deal_story == DealStory(
        investment_view="Owner view.",
        key_strengths=("Story strength one.",),
        key_risks=("Story risk one.",),
        model_gap="Refinance is not modeled.",
    )


def test_calling_generate_analysis_twice_calls_the_provider_twice() -> None:
    client = _fake_client(json.dumps(VALID_ANALYSIS_JSON))
    provider = OpenAIAnalystProvider(client=client)

    provider.generate_analysis(system_prompt="sys", user_prompt="user")
    provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert len(client.responses.calls) == 2


# =============================================================================
# Malformed / unexpected responses fail cleanly
# =============================================================================


def test_non_json_output_text_raises_provider_error() -> None:
    client = _fake_client("not json at all")
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


def test_json_array_instead_of_object_raises_provider_error() -> None:
    client = _fake_client(json.dumps(["not", "an", "object"]))
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


def test_missing_required_field_raises_provider_error() -> None:
    incomplete = dict(VALID_ANALYSIS_JSON)
    del incomplete["executive_summary"]
    client = _fake_client(json.dumps(incomplete))
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


def test_wrong_type_field_raises_provider_error() -> None:
    wrong_type = dict(VALID_ANALYSIS_JSON, strengths="not a list")
    client = _fake_client(json.dumps(wrong_type))
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


def test_empty_output_text_raises_provider_error() -> None:
    client = _fake_client("")
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


def test_underlying_client_exception_raises_provider_error_not_raw_exception() -> None:
    client = _fake_client(TimeoutError("boom"))
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError) as exc_info:
        provider.generate_analysis(system_prompt="sys", user_prompt="user")

    # Never leaks the raw exception message/stack -- only a sanitized class name.
    assert "boom" not in str(exc_info.value)


# =============================================================================
# Sprint B Gate B4 -- nested Deal Story parsing
# =============================================================================


def _with_deal_story(**overrides: Any) -> dict[str, Any]:
    story = dict(VALID_ANALYSIS_JSON["deal_story"], **overrides)
    return dict(VALID_ANALYSIS_JSON, deal_story=story)


def test_deal_story_null_model_gap_parses_as_none() -> None:
    client = _fake_client(json.dumps(_with_deal_story(model_gap=None)))
    provider = OpenAIAnalystProvider(client=client)

    analysis = provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert analysis.deal_story is not None
    assert analysis.deal_story.model_gap is None


def test_deal_story_blank_model_gap_normalizes_to_none() -> None:
    """A model that means "no gap" by returning an empty/whitespace string
    must not produce an empty Model Gap section in the Owner Summary."""

    client = _fake_client(json.dumps(_with_deal_story(model_gap="   ")))
    provider = OpenAIAnalystProvider(client=client)

    analysis = provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert analysis.deal_story is not None
    assert analysis.deal_story.model_gap is None


def test_deal_story_trims_an_over_long_strengths_list_to_the_cap() -> None:
    client = _fake_client(
        json.dumps(_with_deal_story(key_strengths=["One.", "Two.", "Three."]))
    )
    provider = OpenAIAnalystProvider(client=client)

    analysis = provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert analysis.deal_story is not None
    assert analysis.deal_story.key_strengths == ("One.", "Two.")


def test_deal_story_trims_an_over_long_risks_list_to_the_cap() -> None:
    client = _fake_client(json.dumps(_with_deal_story(key_risks=["One.", "Two.", "Three."])))
    provider = OpenAIAnalystProvider(client=client)

    analysis = provider.generate_analysis(system_prompt="sys", user_prompt="user")

    assert analysis.deal_story is not None
    assert analysis.deal_story.key_risks == ("One.", "Two.")


def test_missing_deal_story_object_raises_provider_error() -> None:
    """A *live* provider response must always carry a Deal Story -- the
    schema requires it. (Tolerance for a missing ``deal_story`` exists only
    on the persistence read path, for pre-B4 stored snapshots.)"""

    incomplete = dict(VALID_ANALYSIS_JSON)
    del incomplete["deal_story"]
    client = _fake_client(json.dumps(incomplete))
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


def test_deal_story_wrong_shape_raises_provider_error() -> None:
    client = _fake_client(json.dumps(dict(VALID_ANALYSIS_JSON, deal_story="not an object")))
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


def test_deal_story_non_string_model_gap_raises_provider_error() -> None:
    client = _fake_client(json.dumps(_with_deal_story(model_gap=12)))
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")


def test_deal_story_non_string_list_item_raises_provider_error() -> None:
    client = _fake_client(json.dumps(_with_deal_story(key_risks=["ok", 3])))
    provider = OpenAIAnalystProvider(client=client)

    with pytest.raises(AIProviderError):
        provider.generate_analysis(system_prompt="sys", user_prompt="user")
