"""Phase 10A GPT classification provider adapter.

The only module in this package (and, alongside ``anchor.ai.provider``,
one of only two modules in Anchor) that imports the ``openai`` SDK.
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
(R8). Finally, a candidate that is a deterministic duplicate of one
already kept for that field -- same normalized value, same evidence
status, and equivalent/redundant source evidence -- is collapsed before
the field's candidates are returned, so one physical fact flattened into
more than one Azure DI anchor is never shown as repeated candidates; a
genuine conflict is never collapsed this way.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import (
    ACQUISITION_FIELD_IDS,
    DEAL_CONTEXT_FIELD_IDS,
    DETAILED_OPERATING_FIELD_IDS,
    DETAILED_TERMS_FIELD_IDS,
    DealContext,
    DetailedExtractionResult,
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


@dataclass(frozen=True, slots=True, kw_only=True)
class _FieldDomain:
    """Detailed Operating Model V2.1 Gate 12: the field-set-specific
    verification config every extraction domain (Quick, Detailed) supplies
    to the shared, otherwise field-agnostic verification/conflict/dedup
    core below -- which fields are purely numeric (KTD12), which of those
    are percent/rate-scale (eligible for the OM-narrative x100 equivalence,
    e.g. "5.5%" verifying a proposed "0.055"), and which single field (if
    any) accepts either a numeric or a text match. Introduced so that core
    exactly once, for the Detailed domain, rather than duplicating it
    verbatim over a second field set."""

    numeric_field_ids: frozenset[str]
    percent_scale_field_ids: frozenset[str]
    hybrid_field_id: str | None = None


# KTD12: the 9 numeric AcquisitionInputs fields, plus year_built -- every
# other field (deal-context text fields) is verified as text.
_QUICK_NUMERIC_FIELD_IDS = frozenset({*ACQUISITION_FIELD_IDS, "year_built"})
_QUICK_HYBRID_FIELD_ID = "unit_count_or_building_area"

# Percentage/rate-oriented fields where OM narrative text commonly states a
# percentage (e.g. "5.5%") while AcquisitionInputs stores the equivalent
# decimal fraction (0.055) -- the only fields where a x100 / /100 scale
# difference is treated as the same underlying evidence. Absolute-magnitude
# fields (purchase_price, current_noi, hold_period, amortization,
# year_built, and the hybrid unit_count_or_building_area) never get this
# equivalence: 30 must never verify a cited 3000, and 2026 must never
# verify a cited 20.26.
_QUICK_PERCENT_SCALE_FIELD_IDS = frozenset(
    {"occupancy", "noi_growth", "exit_cap_rate", "ltv", "interest_rate"}
)

_QUICK_DOMAIN = _FieldDomain(
    numeric_field_ids=_QUICK_NUMERIC_FIELD_IDS,
    percent_scale_field_ids=_QUICK_PERCENT_SCALE_FIELD_IDS,
    hybrid_field_id=_QUICK_HYBRID_FIELD_ID,
)

# Detailed Operating Model V2.1 Gate 12: every one of the 22 Detailed
# fields is numeric -- there is no hybrid (numeric-or-text) Detailed field,
# matching Detailed's own field set having no deal-context-style field at
# all. Percent-scale fields are exactly the rate/pct-shaped ones among the
# 22 (mirrors _QUICK_PERCENT_SCALE_FIELD_IDS's role one-for-one, over the
# Detailed field names).
_DETAILED_ALL_FIELD_IDS: tuple[str, ...] = (*DETAILED_TERMS_FIELD_IDS, *DETAILED_OPERATING_FIELD_IDS)
_DETAILED_NUMERIC_FIELD_IDS = frozenset(_DETAILED_ALL_FIELD_IDS)
_DETAILED_PERCENT_SCALE_FIELD_IDS = frozenset(
    {
        "exit_cap_rate",
        "ltv",
        "interest_rate",
        "acquisition_cost_pct",
        "financing_fee_pct",
        "disposition_cost_pct",
        "vacancy_credit_loss_pct",
        "management_fee_pct",
        "revenue_growth",
        "expense_growth",
    }
)
_DETAILED_DOMAIN = _FieldDomain(
    numeric_field_ids=_DETAILED_NUMERIC_FIELD_IDS,
    percent_scale_field_ids=_DETAILED_PERCENT_SCALE_FIELD_IDS,
    hybrid_field_id=None,
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


def _build_json_schema(field_ids: tuple[str, ...]) -> dict[str, Any]:
    candidate_array = {"type": "array", "items": _candidate_schema()}
    return {
        "type": "object",
        "properties": {field_id: candidate_array for field_id in field_ids},
        "required": list(field_ids),
        "additionalProperties": False,
    }


CLASSIFICATION_JSON_SCHEMA: dict[str, Any] = _build_json_schema(_ALL_FIELD_IDS)

# Detailed Operating Model V2.1 Gate 12: the Detailed counterpart schema,
# built the same way, over the 22 Detailed field ids -- no deal-context
# fields (out of this gate's target-field scope).
DETAILED_CLASSIFICATION_JSON_SCHEMA: dict[str, Any] = _build_json_schema(_DETAILED_ALL_FIELD_IDS)


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


# Human-readable magnitude suffixes/words (K/thousand, M/million, B/billion)
# -- representation normalization only (e.g. "$45.0 million" literally means
# 45000000), never a financial calculation. Multi-letter words are listed
# before the single-letter codes only for readability; the trailing ``\b``
# below makes the match unambiguous regardless of alternation order.
_MAGNITUDE_MULTIPLIERS: dict[str, float] = {
    "thousand": 1_000.0,
    "million": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "k": 1_000.0,
    "m": 1_000_000.0,
    "b": 1_000_000_000.0,
}
# Extracts one coherent number token per match: an optional sign directly
# attached to an optional currency symbol and the digits, then an optional
# magnitude suffix/word (K/thousand, M/million, B/billion -- representation
# normalization only, e.g. "$45.0 million" literally means 45000000, never
# a financial calculation) immediately after those same digits. Anchored to
# a single contiguous digit run rather than stripping every non-numeric
# character from the whole string and concatenating what is left -- OM text
# is full of unrelated hyphens (e.g. "Twelve-Month", "T-12", "in-place",
# "Sub-Market") that a blanket strip would otherwise misread as part of the
# number, silently corrupting its sign/magnitude.
_NUMBER_TOKEN_PATTERN = re.compile(
    r"(-)?\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)(?:\s*(thousand|million|billion|[kmb])\b)?",
    re.IGNORECASE,
)


def _numeric_tokens(text: str) -> list[float]:
    """Every number literally present in ``text``, in the order it
    appears, magnitude-suffix-aware. OM narrative text routinely states
    more than one number in the same sentence or table cell (e.g. "T-12
    Occupancy: 94.0%" -- "12" from "T-12" and "94.0" are both numbers in
    that snippet), so verification must check whether the proposed value
    matches *any* number the snippet states, never only the first one
    found."""

    tokens: list[float] = []
    for match in _NUMBER_TOKEN_PATTERN.finditer(text):
        try:
            value = float(match.group(2).replace(",", ""))
        except ValueError:
            continue
        suffix = match.group(3)
        if suffix:
            value *= _MAGNITUDE_MULTIPLIERS[suffix.lower()]
        if match.group(1):
            value = -value
        tokens.append(value)
    return tokens


def _parse_numeric(text: str) -> float | None:
    tokens = _numeric_tokens(text)
    return tokens[0] if tokens else None


def _isclose(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _numeric_match(
    domain: _FieldDomain, field_id: str, value_number: float, snippet_number: float
) -> bool:
    """Literal numeric comparison (KTD12) -- same magnitude always
    verifies. Percent-vs-fraction equivalence (e.g. "5.5%" verifying a
    proposed "0.055") is applied only for ``domain.percent_scale_field_ids``
    -- an absolute-magnitude field must match at the same scale, subject
    only to ordinary formatting normalization (commas, currency symbols,
    etc., already stripped by ``_parse_numeric``)."""

    if _isclose(value_number, snippet_number):
        return True
    if field_id not in domain.percent_scale_field_ids:
        return False
    return _isclose(value_number * 100, snippet_number) or _isclose(
        value_number, snippet_number * 100
    )


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _value_supported_by_snippet(
    domain: _FieldDomain, field_id: str, value: str, snippet: str
) -> bool:
    if field_id in domain.numeric_field_ids:
        value_number = _parse_numeric(value)
        if value_number is None:
            return False
        return any(
            _numeric_match(domain, field_id, value_number, token)
            for token in _numeric_tokens(snippet)
        )

    if field_id == domain.hybrid_field_id:
        value_number = _parse_numeric(value)
        if value_number is not None and any(
            _numeric_match(domain, field_id, value_number, token)
            for token in _numeric_tokens(snippet)
        ):
            return True
        return _normalize_text(value) in _normalize_text(snippet)

    return _normalize_text(value) in _normalize_text(snippet)


def _parse_candidate(
    domain: _FieldDomain,
    field_id: str,
    raw_candidate: Any,
    anchors_by_id: Mapping[str, Any],
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
    if not _value_supported_by_snippet(domain, field_id, value, anchor.text):
        # R6/AE4: the anchor exists but its text does not support the value.
        return ExtractionCandidate(
            value=value, status=EvidenceStatus.UNVERIFIABLE, provenance=provenance
        )

    status = EvidenceStatus.STATED if status_raw == "stated" else EvidenceStatus.INTERPRETED
    return ExtractionCandidate(value=value, status=status, provenance=provenance)


def _resolve_conflicts(
    domain: _FieldDomain, field_id: str, candidates: tuple[ExtractionCandidate, ...]
) -> tuple[ExtractionCandidate, ...]:
    """R8: when two or more verified (stated/interpreted) candidates for one
    field propose differing values, every verified candidate is relabeled
    ``conflicting``. Unverifiable candidates are left as-is -- they were
    never confirmed as a document-stated value in the first place.

    "Differing" is judged by ``_values_equivalent`` -- the same normalized
    value (including percent-scale equivalence, e.g. 95% == 0.95, and
    magnitude-suffix equivalence, e.g. $45,000,000 == $45.0 million) --
    never raw string equality, so two representations of the same
    document-stated fact are never surfaced as a conflict (only a true
    differing value, e.g. 95% vs 94%, is)."""

    verified = [
        candidate
        for candidate in candidates
        if candidate.status in (EvidenceStatus.STATED, EvidenceStatus.INTERPRETED)
    ]
    if not verified:
        return candidates
    reference_value = verified[0].value
    if all(_values_equivalent(domain, field_id, reference_value, c.value) for c in verified):
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


def _values_equivalent(domain: _FieldDomain, field_id: str, value_a: str, value_b: str) -> bool:
    """Same normalized proposed value for one field -- the same numeric
    comparison (including the percent-scale equivalence) already used to
    verify a candidate against its snippet (KTD12), or normalized text
    equality for text fields."""

    if field_id in domain.numeric_field_ids or field_id == domain.hybrid_field_id:
        number_a = _parse_numeric(value_a)
        number_b = _parse_numeric(value_b)
        if number_a is not None and number_b is not None:
            return _numeric_match(domain, field_id, number_a, number_b)
    return _normalize_text(value_a) == _normalize_text(value_b)


def _is_redundant_evidence(a: ExtractionCandidate, b: ExtractionCandidate) -> bool:
    """Equivalent/redundant source evidence: both candidates carry a real
    citation (never dedup a candidate that has none to compare), and that
    citation is either the exact same anchor or an anchor whose text is,
    once normalized, the same underlying statement -- e.g. a table cell
    and a paragraph that both flatten the same physical fact from the
    source document."""

    if a.provenance is None or b.provenance is None:
        return False
    if a.provenance.anchor == b.provenance.anchor:
        return True
    snippet_a = _normalize_text(a.provenance.snippet)
    snippet_b = _normalize_text(b.provenance.snippet)
    return snippet_a == snippet_b or snippet_a in snippet_b or snippet_b in snippet_a


def _deduplicate_candidates(
    domain: _FieldDomain, field_id: str, candidates: tuple[ExtractionCandidate, ...]
) -> tuple[ExtractionCandidate, ...]:
    """Collapses a candidate that is a deterministic duplicate of one
    already kept for this field: the same normalized proposed value, the
    same evidence status, and equivalent/redundant source evidence (see
    ``_is_redundant_evidence``). Never collapses candidates that differ in
    value or status, so a genuine conflict (R8) always survives as
    multiple candidates."""

    kept: list[ExtractionCandidate] = []
    for candidate in candidates:
        if any(
            candidate.status == existing.status
            and _values_equivalent(domain, field_id, candidate.value, existing.value)
            and _is_redundant_evidence(candidate, existing)
            for existing in kept
        ):
            continue
        kept.append(candidate)
    return tuple(kept)


def _parse_field(
    domain: _FieldDomain,
    field_id: str,
    raw: Mapping[str, Any],
    anchors_by_id: Mapping[str, Any],
) -> FieldCandidates:
    raw_candidates = raw.get(field_id)
    if not isinstance(raw_candidates, list):
        raise ExtractionProviderError(
            f"Classifier response field {field_id!r} must be a list of candidates."
        )
    candidates = tuple(
        _parse_candidate(domain, field_id, raw_candidate, anchors_by_id)
        for raw_candidate in raw_candidates
    )
    resolved = _resolve_conflicts(domain, field_id, candidates)
    return FieldCandidates(
        field_id=field_id, candidates=_deduplicate_candidates(domain, field_id, resolved)
    )


def _parse_classification(raw: Mapping[str, Any], document: StructuredDocument) -> ExtractionResult:
    anchors_by_id = {anchor.anchor: anchor for anchor in document.anchors}
    fields = {
        field_id: _parse_field(_QUICK_DOMAIN, field_id, raw, anchors_by_id)
        for field_id in _ALL_FIELD_IDS
    }

    deal_context = DealContext(
        **{field_id: fields[field_id] for field_id in DEAL_CONTEXT_FIELD_IDS}
    )
    return ExtractionResult(
        **{field_id: fields[field_id] for field_id in ACQUISITION_FIELD_IDS},
        deal_context=deal_context,
    )


def _parse_detailed_classification(
    raw: Mapping[str, Any], document: StructuredDocument
) -> DetailedExtractionResult:
    """Detailed Operating Model V2.1 Gate 12: the Detailed counterpart to
    ``_parse_classification`` -- identical verification/conflict/dedup
    pipeline (``_DETAILED_DOMAIN``), assembled into ``DetailedExtractionResult``
    instead (no nested ``deal_context`` -- Detailed OM ingestion proposes
    underwriting assumptions only)."""

    anchors_by_id = {anchor.anchor: anchor for anchor in document.anchors}
    fields = {
        field_id: _parse_field(_DETAILED_DOMAIN, field_id, raw, anchors_by_id)
        for field_id in _DETAILED_ALL_FIELD_IDS
    }
    return DetailedExtractionResult(**fields)


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

    def _request_raw_classification(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        """Calls the Responses API once with strict structured output and
        returns the parsed JSON object -- the one piece of provider-calling
        logic ``classify``/``classify_detailed`` share. Performs no
        field-specific parsing or verification of its own; that stays in
        ``_parse_classification``/``_parse_detailed_classification``."""

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
                        "name": schema_name,
                        "schema": json_schema,
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

        return raw

    def classify(
        self, *, system_prompt: str, user_prompt: str, document: StructuredDocument
    ) -> ExtractionResult:
        """Call the Responses API once with strict structured output, then
        deterministically verify every candidate's citation against
        ``document`` (KTD12) before returning the assembled
        ``ExtractionResult``."""

        raw = self._request_raw_classification(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_schema=CLASSIFICATION_JSON_SCHEMA,
            schema_name="om_classification",
        )
        return _parse_classification(raw, document)

    def classify_detailed(
        self, *, system_prompt: str, user_prompt: str, document: StructuredDocument
    ) -> DetailedExtractionResult:
        """Detailed Operating Model V2.1 Gate 12: the Detailed counterpart
        to ``classify`` -- same provider call machinery and the same
        KTD12 deterministic verification pass, over the Detailed field set
        and schema, returning ``DetailedExtractionResult`` instead."""

        raw = self._request_raw_classification(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_schema=DETAILED_CLASSIFICATION_JSON_SCHEMA,
            schema_name="detailed_om_classification",
        )
        return _parse_detailed_classification(raw, document)
