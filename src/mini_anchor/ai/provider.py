"""Phase 9A AI Analyst OpenAI provider adapter.

The only module in this package (and the only module in Mini-Anchor) that
imports the ``openai`` SDK or talks to the OpenAI Responses API. Isolated
here so a different provider/model could be introduced later without
touching ``mini_anchor.ai.analyst``, ``mini_anchor.ai.prompts``, or any
financial code. This module performs no financial calculation: it only
sends two already-built prompt strings to the model and converts the
model's structured JSON reply into ``AIAnalysis``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from .contracts import AIAnalysis

DEFAULT_MODEL = "gpt-5.6-terra"
_MODEL_ENV_VAR = "ANCHOR_AI_MODEL"
_API_KEY_ENV_VAR = "OPENAI_API_KEY"

# Field-shape split mirrors ``AIAnalysis`` in ``contracts.py`` exactly --
# five prose fields, five tuple-of-prose fields. Used to build both the
# strict Responses API JSON schema and the response parser from one place,
# so the two can never drift apart.
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


def _build_json_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field_name in _STRING_FIELDS:
        properties[field_name] = {"type": "string"}
    for field_name in _TUPLE_FIELDS:
        properties[field_name] = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "properties": properties,
        "required": [*_STRING_FIELDS, *_TUPLE_FIELDS],
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

    return AIAnalysis(**values)


class OpenAIAnalystProvider:
    """Thin adapter over the OpenAI Responses API.

    Isolates every OpenAI-specific detail (client construction, model
    resolution, structured-output schema, response parsing) behind one
    ``generate_analysis`` method, so ``mini_anchor.ai.analyst`` never needs
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
