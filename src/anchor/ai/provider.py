"""Phase 9A AI Analyst OpenAI provider adapter.

The only module in this package (and the only module in Anchor) that
imports the ``openai`` SDK or talks to the OpenAI Responses API. Isolated
here so a different provider/model could be introduced later without
touching ``anchor.ai.analyst``, ``anchor.ai.prompts``, or any
financial code. This module performs no financial calculation: it only
sends two already-built prompt strings to the model and converts the
model's structured JSON reply into ``AIAnalysis`` (including the nested
Sprint B Gate B4 ``DealStory`` that same single reply carries -- one
provider call still produces both the full report and the concise owner
Deal Story).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from .contracts import AIAnalysis, DealStory

DEFAULT_MODEL = "gpt-5.6-terra"
_MODEL_ENV_VAR = "ANCHOR_AI_MODEL"
_API_KEY_ENV_VAR = "OPENAI_API_KEY"

# Field-shape split mirrors ``AIAnalysis``'s ten full-report fields in
# ``contracts.py`` exactly -- five prose fields, five tuple-of-prose
# fields. Used to build both the strict Responses API JSON schema and the
# response parser from one place, so the two can never drift apart. The
# eleventh field, the nested ``deal_story`` object, is declared just below
# under the same one-declaration-drives-both rule.
_STRING_FIELDS: tuple[str, ...] = (
    "executive_summary",
    "investment_view",
    "downside_analysis",
    "capital_structure_analysis",
    "break_even_analysis",
)
_TUPLE_FIELDS: tuple[str, ...] = (
    "strengths",
    "risks",
    "return_drivers",
    "questions_to_investigate",
    "confidence_notes",
)


# Sprint B Gate B4: the nested ``deal_story`` object -- the concise
# owner-level ``DealStory`` the same single response carries alongside the
# ten full-report fields above. Split the same way for the same reason: one
# declaration drives both the strict schema and the parser.
_DEAL_STORY_STRING_FIELDS: tuple[str, ...] = ("investment_view",)
_DEAL_STORY_TUPLE_FIELDS: tuple[str, ...] = ("key_strengths", "key_risks")
_DEAL_STORY_NULLABLE_STRING_FIELDS: tuple[str, ...] = ("model_gap",)
_DEAL_STORY_FIELD = "deal_story"


def _build_deal_story_json_schema() -> dict[str, Any]:
    """The nested ``deal_story`` sub-schema. ``model_gap`` is declared
    ``["string", "null"]`` rather than omitted from ``required``: OpenAI
    strict structured output requires every property to be listed in
    ``required``, so an explicitly nullable type is the only way to let the
    model say "no material model gap exists" without inventing filler."""

    properties: dict[str, Any] = {}
    for field_name in _DEAL_STORY_STRING_FIELDS:
        properties[field_name] = {"type": "string"}
    for field_name in _DEAL_STORY_TUPLE_FIELDS:
        properties[field_name] = {"type": "array", "items": {"type": "string"}}
    for field_name in _DEAL_STORY_NULLABLE_STRING_FIELDS:
        properties[field_name] = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": properties,
        "required": [
            *_DEAL_STORY_STRING_FIELDS,
            *_DEAL_STORY_TUPLE_FIELDS,
            *_DEAL_STORY_NULLABLE_STRING_FIELDS,
        ],
        "additionalProperties": False,
    }


def _build_json_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field_name in _STRING_FIELDS:
        properties[field_name] = {"type": "string"}
    for field_name in _TUPLE_FIELDS:
        properties[field_name] = {"type": "array", "items": {"type": "string"}}
    properties[_DEAL_STORY_FIELD] = _build_deal_story_json_schema()
    return {
        "type": "object",
        "properties": properties,
        "required": [*_STRING_FIELDS, *_TUPLE_FIELDS, _DEAL_STORY_FIELD],
        "additionalProperties": False,
    }


AI_ANALYSIS_JSON_SCHEMA: dict[str, Any] = _build_json_schema()


class AIError(RuntimeError):
    """Base class for Phase 9A AI Analyst layer errors."""


class AIConfigurationError(AIError):
    """Raised when the AI Analyst layer is not configured -- currently
    only when ``OPENAI_API_KEY`` is absent from the process environment."""


class AIProviderError(AIError):
    """Raised when the OpenAI provider call itself fails, times out, or
    returns a response that cannot be converted to ``AIAnalysis``.

    The message is always a short, sanitized description -- never a raw
    provider stack trace, request/response body, or secret.
    """


def _resolve_model(model: str | None) -> str:
    if model:
        return model
    return os.environ.get(_MODEL_ENV_VAR) or DEFAULT_MODEL


def _resolve_api_key() -> str:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise AIConfigurationError(
            f"{_API_KEY_ENV_VAR} is not configured. Set it in the process "
            "environment (see .env.example) before requesting an AI Analysis."
        )
    return api_key


def _parse_ai_analysis(raw: Mapping[str, Any]) -> AIAnalysis:
    """Convert one parsed provider JSON object into ``AIAnalysis``.

    Raises ``AIProviderError`` -- never a raw ``KeyError``/``TypeError`` --
    for any missing field or field of the wrong shape, so a malformed or
    unexpected provider response always fails cleanly.
    """

    values: dict[str, Any] = {}
    for field_name in _STRING_FIELDS:
        value = raw.get(field_name)
        if not isinstance(value, str):
            raise AIProviderError(
                f"AI provider response field {field_name!r} must be a string."
            )
        values[field_name] = value
    for field_name in _TUPLE_FIELDS:
        value = raw.get(field_name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise AIProviderError(
                f"AI provider response field {field_name!r} must be a list of strings."
            )
        values[field_name] = tuple(value)

    values[_DEAL_STORY_FIELD] = _parse_deal_story(raw.get(_DEAL_STORY_FIELD))

    return AIAnalysis(**values)


def _normalize_model_gap(value: Any) -> str | None:
    """``model_gap`` is nullable by design (Gate B4: never manufacture a
    gap to fill the field). A model that says "no gap" by returning an
    empty or whitespace-only string means exactly what ``null`` means, so
    both normalize to ``None`` -- the Owner Summary then omits the section
    rather than rendering a blank one."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise AIProviderError(
            "AI provider response field 'deal_story.model_gap' must be a string or null."
        )
    stripped = value.strip()
    return stripped or None


def _parse_deal_story(raw: Any) -> DealStory:
    """Convert the nested ``deal_story`` object into ``DealStory``.

    ``key_strengths``/``key_risks`` are trimmed to
    ``DealStory.MAX_STORY_ITEMS`` here rather than rejected: the cap is a
    presentation invariant the Owner Summary depends on, and a model that
    returns a third bullet should cost the user a trimmed list, never a
    failed AI request. The contract itself still enforces the cap, so no
    other caller can bypass it.
    """

    if not isinstance(raw, dict):
        raise AIProviderError("AI provider response field 'deal_story' must be an object.")

    values: dict[str, Any] = {}
    for field_name in _DEAL_STORY_STRING_FIELDS:
        value = raw.get(field_name)
        if not isinstance(value, str):
            raise AIProviderError(
                f"AI provider response field 'deal_story.{field_name}' must be a string."
            )
        values[field_name] = value
    for field_name in _DEAL_STORY_TUPLE_FIELDS:
        value = raw.get(field_name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise AIProviderError(
                f"AI provider response field 'deal_story.{field_name}' "
                "must be a list of strings."
            )
        values[field_name] = tuple(value[: DealStory.MAX_STORY_ITEMS])
    for field_name in _DEAL_STORY_NULLABLE_STRING_FIELDS:
        values[field_name] = _normalize_model_gap(raw.get(field_name))

    return DealStory(**values)


class OpenAIAnalystProvider:
    """Thin adapter over the OpenAI Responses API.

    Isolates every OpenAI-specific detail (client construction, model
    resolution, structured-output schema, response parsing) behind one
    ``generate_analysis`` method, so ``anchor.ai.analyst`` never needs
    to know the Responses API shape. A test may pass a fake ``client`` (any
    object exposing ``.responses.create(...)``) to exercise this class
    without making a real network call.
    """

    def __init__(self, *, client: Any = None, model: str | None = None) -> None:
        self._client = client
        self._model = _resolve_model(model)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        api_key = _resolve_api_key()
        from openai import OpenAI  # local import: only needed for a real call

        self._client = OpenAI(api_key=api_key)
        return self._client

    def generate_analysis(self, *, system_prompt: str, user_prompt: str) -> AIAnalysis:
        """Call the Responses API once with strict structured output and
        return the parsed ``AIAnalysis``."""

        client = self._get_client()

        try:
            response = client.responses.create(
                model=self._model,
                reasoning={"effort": "medium"},
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "ai_analysis",
                        "schema": AI_ANALYSIS_JSON_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except Exception as error:
            raise AIProviderError(
                f"The AI provider request failed ({error.__class__.__name__})."
            ) from error

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise AIProviderError("The AI provider returned an empty response.")

        try:
            raw = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise AIProviderError("The AI provider response was not valid JSON.") from error

        if not isinstance(raw, dict):
            raise AIProviderError("The AI provider response was not a JSON object.")

        return _parse_ai_analysis(raw)
