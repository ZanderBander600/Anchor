"""Tests for the Phase 10A GPT classification provider adapter
(``mini_anchor.ingestion.classifier_provider``).

Every test here uses a fake client object -- never the real ``openai`` SDK
or a network call, per AGENTS.md's "no real Azure/OpenAI calls in automated
tests" rule. Covers: well-formed responses converting to ``ExtractionResult``
with correct missing/conflicting handling, the KTD12 deterministic
provenance/value verification (never a second model call), and malformed
responses / provider failures failing cleanly and sanitized.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from mini_anchor.ingestion.classifier_provider import GPTClassifierProvider
from mini_anchor.ingestion.contracts import (
    DocumentAnchor,
    EvidenceStatus,
    ExtractionConfigurationError,
    ExtractionProviderError,
    ExtractionResult,
    StructuredDocument,
)


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


_ALL_FIELD_IDS = (
    "purchase_price",
    "current_noi",
    "occupancy",
    "noi_growth",
    "hold_period",
    "exit_cap_rate",
    "ltv",
    "interest_rate",
    "amortization",
    "property_name",
    "address",
    "property_type",
    "unit_count_or_building_area",
    "year_built",
)


def _empty_response(overrides: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {field_id: [] for field_id in _ALL_FIELD_IDS}
    if overrides:
        body.update(overrides)
    return body


DOCUMENT = StructuredDocument(
    anchors=(
        DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $1,000,000"),
        DocumentAnchor(anchor="paragraph:1", page=2, text="Purchase Price (financial summary): $1,250,000"),
        DocumentAnchor(anchor="paragraph:2", page=1, text="Current NOI: $75,000"),
    )
)


# =============================================================================
# Missing configuration
# =============================================================================


def test_missing_api_key_raises_configuration_error_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = GPTClassifierProvider()  # no fake client -- must not reach the network

    with pytest.raises(ExtractionConfigurationError):
        provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)


# =============================================================================
# Happy path: missing fields, stated candidates
# =============================================================================


def test_stated_candidate_verifies_and_other_fields_are_missing() -> None:
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "1000000", "status": "stated", "anchor": "paragraph:0"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)

    assert isinstance(result, ExtractionResult)
    assert len(result.purchase_price.candidates) == 1
    candidate = result.purchase_price.candidates[0]
    assert candidate.status is EvidenceStatus.STATED
    assert candidate.provenance is not None
    assert candidate.provenance.anchor == "paragraph:0"
    assert result.current_noi.candidates == ()
    assert result.hold_period.candidates == ()
    assert result.deal_context.property_name.candidates == ()


# =============================================================================
# Conflicting candidates (R8)
# =============================================================================


def test_two_differing_candidates_are_marked_conflicting_and_both_retained() -> None:
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "1000000", "status": "stated", "anchor": "paragraph:0"},
                {"value": "1250000", "status": "stated", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)

    assert len(result.purchase_price.candidates) == 2
    assert all(c.status is EvidenceStatus.CONFLICTING for c in result.purchase_price.candidates)
    assert {c.value for c in result.purchase_price.candidates} == {"1000000", "1250000"}


def test_two_candidates_with_the_same_value_are_not_marked_conflicting() -> None:
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "1000000", "status": "stated", "anchor": "paragraph:0"},
                {"value": "1000000", "status": "interpreted", "anchor": "paragraph:0"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)

    assert all(c.status is not EvidenceStatus.CONFLICTING for c in result.purchase_price.candidates)


# =============================================================================
# KTD12 -- deterministic anchor/value verification
# =============================================================================


def test_candidate_citing_a_nonexistent_anchor_is_downgraded_to_unverifiable() -> None:
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "1000000", "status": "stated", "anchor": "paragraph:99"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)

    candidate = result.purchase_price.candidates[0]
    assert candidate.status is EvidenceStatus.UNVERIFIABLE
    assert candidate.provenance is None


def test_candidate_whose_anchor_text_does_not_support_the_value_is_unverifiable() -> None:
    raw = _empty_response(
        {
            "purchase_price": [
                # paragraph:0 states $1,000,000, not $980,000.
                {"value": "980000", "status": "stated", "anchor": "paragraph:0"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)

    candidate = result.purchase_price.candidates[0]
    assert candidate.status is EvidenceStatus.UNVERIFIABLE
    assert candidate.provenance is not None  # the real anchor text is still shown


def test_candidate_value_in_an_equivalent_normalized_format_is_verified() -> None:
    raw = _empty_response(
        {
            "purchase_price": [
                # paragraph:0's text is "Purchase Price: $1,000,000".
                {"value": "1000000", "status": "stated", "anchor": "paragraph:0"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)

    assert result.purchase_price.candidates[0].status is EvidenceStatus.STATED


def test_percent_vs_decimal_fraction_representation_is_verified() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Exit Cap Rate: 5.50%"),)
    )
    raw = _empty_response(
        {
            "exit_cap_rate": [
                {"value": "0.055", "status": "interpreted", "anchor": "paragraph:0"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.exit_cap_rate.candidates[0].status is EvidenceStatus.INTERPRETED


# =============================================================================
# Percent-scale equivalence is scoped to rate/percentage fields only --
# never applied to absolute-magnitude fields (purchase_price, current_noi,
# hold_period, amortization, year_built, unit_count_or_building_area).
# =============================================================================


def test_percent_representation_verifies_exit_cap_rate_decimal_fraction() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Exit Cap Rate: 5.5%"),)
    )
    raw = _empty_response(
        {"exit_cap_rate": [{"value": "0.055", "status": "interpreted", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.exit_cap_rate.candidates[0].status is EvidenceStatus.INTERPRETED


def test_percent_representation_verifies_occupancy_decimal_fraction() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Occupancy: 95%"),)
    )
    raw = _empty_response(
        {"occupancy": [{"value": "0.95", "status": "interpreted", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.occupancy.candidates[0].status is EvidenceStatus.INTERPRETED


def test_currency_formatted_snippet_verifies_matching_purchase_price() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $50,000,000"),)
    )
    raw = _empty_response(
        {"purchase_price": [{"value": "50000000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.purchase_price.candidates[0].status is EvidenceStatus.STATED


def test_purchase_price_does_not_get_percent_scale_equivalence() -> None:
    """An absolute-magnitude field must match at the same scale -- a cited
    $500,000 must never verify a proposed $50,000,000, even though that is
    exactly a x100 relationship (the kind of scale difference that *is*
    tolerated for percentage/rate fields)."""

    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $500,000"),)
    )
    raw = _empty_response(
        {"purchase_price": [{"value": "50000000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.purchase_price.candidates[0].status is EvidenceStatus.UNVERIFIABLE


def test_amortization_does_not_get_percent_scale_equivalence() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Amortization: 3000 years"),)
    )
    raw = _empty_response(
        {"amortization": [{"value": "30", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.amortization.candidates[0].status is EvidenceStatus.UNVERIFIABLE


def test_year_built_does_not_get_percent_scale_equivalence() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Year Built: 20.26"),)
    )
    raw = _empty_response(
        {"year_built": [{"value": "2026", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.deal_context.year_built.candidates[0].status is EvidenceStatus.UNVERIFIABLE


def test_text_field_uses_normalized_substring_match() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Address: 123 Main Street"),)
    )
    raw = _empty_response(
        {"address": [{"value": "123 Main Street", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.deal_context.address.candidates[0].status is EvidenceStatus.STATED


def test_text_field_value_not_present_in_snippet_is_unverifiable() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Address: 123 Main Street"),)
    )
    raw = _empty_response(
        {"address": [{"value": "456 Other Ave", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.deal_context.address.candidates[0].status is EvidenceStatus.UNVERIFIABLE


# =============================================================================
# Malformed / unexpected responses fail cleanly
# =============================================================================


def test_non_json_output_text_raises_provider_error() -> None:
    client = _fake_client("not json at all")
    provider = GPTClassifierProvider(client=client)

    with pytest.raises(ExtractionProviderError):
        provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)


def test_json_array_instead_of_object_raises_provider_error() -> None:
    client = _fake_client(json.dumps(["not", "an", "object"]))
    provider = GPTClassifierProvider(client=client)

    with pytest.raises(ExtractionProviderError):
        provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)


def test_missing_required_field_raises_provider_error() -> None:
    incomplete = _empty_response()
    del incomplete["purchase_price"]
    client = _fake_client(json.dumps(incomplete))
    provider = GPTClassifierProvider(client=client)

    with pytest.raises(ExtractionProviderError):
        provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)


def test_wrong_shaped_field_raises_provider_error() -> None:
    wrong_shape = _empty_response({"purchase_price": "not a list"})  # type: ignore[dict-item]
    client = _fake_client(json.dumps(wrong_shape))
    provider = GPTClassifierProvider(client=client)

    with pytest.raises(ExtractionProviderError):
        provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)


def test_candidate_missing_required_key_raises_provider_error() -> None:
    raw = _empty_response({"purchase_price": [{"value": "1000000", "status": "stated"}]})
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    with pytest.raises(ExtractionProviderError):
        provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)


def test_empty_output_text_raises_provider_error() -> None:
    client = _fake_client("")
    provider = GPTClassifierProvider(client=client)

    with pytest.raises(ExtractionProviderError):
        provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)


def test_underlying_client_exception_raises_provider_error_not_raw_exception() -> None:
    client = _fake_client(TimeoutError("boom"))
    provider = GPTClassifierProvider(client=client)

    with pytest.raises(ExtractionProviderError) as exc_info:
        provider.classify(system_prompt="sys", user_prompt="user", document=DOCUMENT)

    assert "boom" not in str(exc_info.value)


# =============================================================================
# KD1 -- the raw PDF never reaches the classifier call
# =============================================================================


def test_classify_call_input_contains_only_the_supplied_prompt_strings() -> None:
    """``classify`` has no ``pdf_bytes`` parameter and sends exactly the two
    prompt strings supplied -- the raw PDF can never reach this call."""

    raw = _empty_response()
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    provider.classify(system_prompt="the system prompt", user_prompt="the user prompt", document=DOCUMENT)

    call = client.responses.calls[0]
    roles_and_content = [(item["role"], item["content"]) for item in call["input"]]
    assert roles_and_content == [
        ("system", "the system prompt"),
        ("user", "the user prompt"),
    ]
