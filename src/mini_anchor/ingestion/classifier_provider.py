"""Phase 10A GPT classification provider adapter.

The only module in this package (and, alongside ``mini_anchor.ai.provider``,
one of only two modules in Mini-Anchor) that imports the ``openai`` SDK.
Receives only Azure DI's flattened ``StructuredDocument`` (never the raw
PDF -- KD1) and maps it to per-field candidates, each carrying an evidence
status and a citation. This module performs no financial calculation.

Every non-``missing`` candidate's citation is verified deterministically
against the ``StructuredDocument`` actually sent -- never via a second
model call (KTD12): the cited anchor id must exist in that document, and
its text must literally/numerically support the proposed value. A
candidate that fails either check is downgraded to ``unverifiable`` before
it is returned. A field where two or more verified candidates propose
differing values has every verified candidate relabeled ``conflicting``
(R8).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Any

from .contracts import (
    ACQUISITION_FIELD_IDS,
    DEAL_CONTEXT_FIELD_IDS,
    DealContext,
    EvidenceStatus,
    ExtractionCandidate,
    ExtractionConfigurationError,
    ExtractionProviderError,
    ExtractionResult,
    FieldCandidates,
    Provenance,
    StructuredDocument,
)

DEFAULT_MODEL = "gpt-5.6-terra"
_MODEL_ENV_VAR = "ANCHOR_INGESTION_MODEL"
_API_KEY_ENV_VAR = "OPENAI_API_KEY"

_ALL_FIELD_IDS: tuple[str, ...] = (*ACQUISITION_FIELD_IDS, *DEAL_CONTEXT_FIELD_IDS)
_MODEL_STATUS_VALUES = ("stated", "interpreted")

# KTD12: the 9 numeric AcquisitionInputs fields, plus year_built -- every
# other field (deal-context text fields) is verified as text.
_NUMERIC_FIELD_IDS = frozenset({*ACQUISITION_FIELD_IDS, "year_built"})
_HYBRID_FIELD_ID = "unit_count_or_building_area"

# Percentage/rate-oriented fields where OM narrative text commonly states a
# percentage (e.g. "5.5%") while AcquisitionInputs stores the equivalent
# decimal fraction (0.055) -- the only fields where a x100 / /100 scale
# difference is treated as the same underlying evidence. Absolute-magnitude
# fields (purchase_price, current_noi, hold_period, amortization,
# year_built, and the hybrid unit_count_or_building_area) never get this
# equivalence: 30 must never verify a cited 3000, and 2026 must never
# verify a cited 20.26.
_PERCENT_SCALE_FIELD_IDS = frozenset(
    {"occupancy", "noi_growth", "exit_cap_rate", "ltv", "interest_rate"}
)


def _candidate_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
            "status": {"type": "string", "enum": list(_MODEL_STATUS_VALUES)},
            "anchor": {"type": "string"},
        },
        "required": ["value", "status", "anchor"],
        "additionalProperties": False,
    }


def _build_json_schema() -> dict[str, Any]:
    candidate_array = {"type": "array", "items": _candidate_schema()}
    return {
        "type": "object",
        "properties": {field_id: candidate_array for field_id in _ALL_FIELD_IDS},
        "required": list(_ALL_FIELD_IDS),
        "additionalProperties": False,
    }


CLASSIFICATION_JSON_SCHEMA: dict[str, Any] = _build_json_schema()


def _resolve_model(model: str | None) -> str:
    if model:
        return model
    return os.environ.get(_MODEL_ENV_VAR) or DEFAULT_MODEL


def _resolve_api_key() -> str:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise ExtractionConfigurationError(
            f"{_API_KEY_ENV_VAR} is not configured. Set it in the process "
            "environment before requesting OM classification."
        )
    return api_key


# =============================================================================
# KTD12: deterministic provenance/value verification -- no second model call.
# =============================================================================


def _parse_numeric(text: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _isclose(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _numeric_match(field_id: str, value_number: float, snippet_number: float) -> bool:
    """Literal numeric comparison (KTD12) -- same magnitude always
    verifies. Percent-vs-fraction equivalence (e.g. "5.5%" verifying a
    proposed "0.055") is applied only for ``_PERCENT_SCALE_FIELD_IDS`` --
    an absolute-magnitude field must match at the same scale, subject only
    to ordinary formatting normalization (commas, currency symbols, etc.,
    already stripped by ``_parse_numeric``)."""

    if _isclose(value_number, snippet_number):
        return True
    if field_id not in _PERCENT_SCALE_FIELD_IDS:
        return False
    return _isclose(value_number * 100, snippet_number) or _isclose(
        value_number, snippet_number * 100
    )


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _value_supported_by_snippet(field_id: str, value: str, snippet: str) -> bool:
    if field_id in _NUMERIC_FIELD_IDS:
        value_number = _parse_numeric(value)
        snippet_number = _parse_numeric(snippet)
        if value_number is None or snippet_number is None:
            return False
        return _numeric_match(field_id, value_number, snippet_number)

    if field_id == _HYBRID_FIELD_ID:
        value_number = _parse_numeric(value)
        snippet_number = _parse_numeric(snippet)
        if value_number is not None and snippet_number is not None and _numeric_match(
            field_id, value_number, snippet_number
        ):
            return True
        return _normalize_text(value) in _normalize_text(snippet)

    return _normalize_text(value) in _normalize_text(snippet)


def _parse_candidate(
    field_id: str, raw_candidate: Any, anchors_by_id: Mapping[str, Any]
) -> ExtractionCandidate:
    if not isinstance(raw_candidate, Mapping):
        raise ExtractionProviderError(
            f"Classifier response for field {field_id!r} contained a non-object candidate."
        )

    value = raw_candidate.get("value")
    status_raw = raw_candidate.get("status")
    anchor_id = raw_candidate.get("anchor")
    if not isinstance(value, str) or not value.strip():
        raise ExtractionProviderError(
            f"Classifier response for field {field_id!r} had a non-string or empty value."
        )
    if status_raw not in _MODEL_STATUS_VALUES:
        raise ExtractionProviderError(
            f"Classifier response for field {field_id!r} had an invalid status {status_raw!r}."
        )
    if not isinstance(anchor_id, str) or not anchor_id:
        raise ExtractionProviderError(
            f"Classifier response for field {field_id!r} had a missing or invalid anchor citation."
        )

    anchor = anchors_by_id.get(anchor_id)
    if anchor is None:
        # R6/AE4: the cited anchor does not exist in the payload actually sent.
        return ExtractionCandidate(value=value, status=EvidenceStatus.UNVERIFIABLE, provenance=None)

    provenance = Provenance(page=anchor.page, anchor=anchor.anchor, snippet=anchor.text)
    if not _value_supported_by_snippet(field_id, value, anchor.text):
        # R6/AE4: the anchor exists but its text does not support the value.
        return ExtractionCandidate(
            value=value, status=EvidenceStatus.UNVERIFIABLE, provenance=provenance
        )

    status = EvidenceStatus.STATED if status_raw == "stated" else EvidenceStatus.INTERPRETED
    return ExtractionCandidate(value=value, status=status, provenance=provenance)


def _resolve_conflicts(
    candidates: tuple[ExtractionCandidate, ...],
) -> tuple[ExtractionCandidate, ...]:
    """R8: when two or more verified (stated/interpreted) candidates for one
    field propose differing values, every verified candidate is relabeled
    ``conflicting``. Unverifiable candidates are left as-is -- they were
    never confirmed as a document-stated value in the first place."""

    verified = [
        candidate
        for candidate in candidates
        if candidate.status in (EvidenceStatus.STATED, EvidenceStatus.INTERPRETED)
    ]
    distinct_values = {candidate.value for candidate in verified}
    if len(distinct_values) <= 1:
        return candidates

    resolved: list[ExtractionCandidate] = []
    for candidate in candidates:
        if candidate.status in (EvidenceStatus.STATED, EvidenceStatus.INTERPRETED):
            resolved.append(
                ExtractionCandidate(
                    value=candidate.value,
                    status=EvidenceStatus.CONFLICTING,
                    provenance=candidate.provenance,
                )
            )
        else:
            resolved.append(candidate)
    return tuple(resolved)


def _parse_field(
    field_id: str, raw: Mapping[str, Any], anchors_by_id: Mapping[str, Any]
) -> FieldCandidates:
    raw_candidates = raw.get(field_id)
    if not isinstance(raw_candidates, list):
        raise ExtractionProviderError(
            f"Classifier response field {field_id!r} must be a list of candidates."
        )
    candidates = tuple(
        _parse_candidate(field_id, raw_candidate, anchors_by_id) for raw_candidate in raw_candidates
    )
    return FieldCandidates(field_id=field_id, candidates=_resolve_conflicts(candidates))


def _parse_classification(raw: Mapping[str, Any], document: StructuredDocument) -> ExtractionResult:
    anchors_by_id = {anchor.anchor: anchor for anchor in document.anchors}
    fields = {
        field_id: _parse_field(field_id, raw, anchors_by_id) for field_id in _ALL_FIELD_IDS
    }

    deal_context = DealContext(
        **{field_id: fields[field_id] for field_id in DEAL_CONTEXT_FIELD_IDS}
    )
    return ExtractionResult(
        **{field_id: fields[field_id] for field_id in ACQUISITION_FIELD_IDS},
        deal_context=deal_context,
    )


class GPTClassifierProvider:
    """Thin adapter over the OpenAI Responses API for OM classification.

    Isolates every OpenAI-specific detail (client construction, model
    resolution, structured-output schema, response parsing, and the
    KTD12 deterministic verification pass) behind one ``classify`` method.
    A test may pass a fake ``client`` (any object exposing
    ``.responses.create(...)``) to exercise this class without making a
    real network call.
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

    def classify(
        self, *, system_prompt: str, user_prompt: str, document: StructuredDocument
    ) -> ExtractionResult:
        """Call the Responses API once with strict structured output, then
        deterministically verify every candidate's citation against
        ``document`` (KTD12) before returning the assembled
        ``ExtractionResult``."""

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
                        "name": "om_classification",
                        "schema": CLASSIFICATION_JSON_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except Exception as error:
            raise ExtractionProviderError(
                f"The OM classification request failed ({error.__class__.__name__})."
            ) from error

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise ExtractionProviderError("The OM classifier returned an empty response.")

        try:
            raw = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise ExtractionProviderError(
                "The OM classifier response was not valid JSON."
            ) from error

        if not isinstance(raw, dict):
            raise ExtractionProviderError("The OM classifier response was not a JSON object.")

        return _parse_classification(raw, document)
