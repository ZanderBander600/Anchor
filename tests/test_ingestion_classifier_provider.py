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
# Conflict determination compares normalized semantic values, not raw
# strings (live-pipeline regression: $45,000,000 and $45.0 million were
# wrongly surfaced as conflicting). Each pair below cites distinct,
# non-redundant anchors so dedup never collapses them -- both candidates
# must survive as separate, non-conflicting evidence.
# =============================================================================


def test_equivalent_purchase_price_in_different_magnitude_representations_is_not_conflicting() -> None:
    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=2, text="Purchase Price: $45,000,000"),
            DocumentAnchor(
                anchor="paragraph:1",
                page=4,
                text="Purchase Price (Financial Summary): $45.0 million",
            ),
        )
    )
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "45000000", "status": "stated", "anchor": "paragraph:0"},
                {"value": "$45.0 million", "status": "stated", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.purchase_price.candidates) == 2
    assert all(c.status is EvidenceStatus.STATED for c in result.purchase_price.candidates)


def test_equivalent_current_noi_in_different_magnitude_representations_is_not_conflicting() -> None:
    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=2, text="Current NOI: $2,500,000"),
            DocumentAnchor(anchor="paragraph:1", page=4, text="In-Place NOI: $2.50 million"),
        )
    )
    raw = _empty_response(
        {
            "current_noi": [
                {"value": "2500000", "status": "stated", "anchor": "paragraph:0"},
                {"value": "$2.50 million", "status": "stated", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.current_noi.candidates) == 2
    assert all(c.status is EvidenceStatus.STATED for c in result.current_noi.candidates)


def test_equivalent_percent_and_decimal_fraction_is_not_conflicting() -> None:
    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=2, text="Current Occupancy: 95%"),
            DocumentAnchor(anchor="paragraph:1", page=4, text="Stabilized occupancy assumption: 0.95"),
        )
    )
    raw = _empty_response(
        {
            "occupancy": [
                {"value": "95%", "status": "stated", "anchor": "paragraph:0"},
                {"value": "0.95", "status": "interpreted", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.occupancy.candidates) == 2
    assert all(c.status is not EvidenceStatus.CONFLICTING for c in result.occupancy.candidates)


def test_genuinely_differing_percent_values_are_still_conflicting() -> None:
    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=2, text="Current Occupancy: 95%"),
            DocumentAnchor(anchor="paragraph:1", page=6, text="Current Occupancy: 94%"),
        )
    )
    raw = _empty_response(
        {
            "occupancy": [
                {"value": "95%", "status": "stated", "anchor": "paragraph:0"},
                {"value": "94%", "status": "stated", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.occupancy.candidates) == 2
    assert all(c.status is EvidenceStatus.CONFLICTING for c in result.occupancy.candidates)


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
# Deterministic candidate deduplication -- same field, same normalized
# value, same evidence status, and equivalent/redundant source evidence
# (one physical fact flattened into more than one Azure DI anchor).
# =============================================================================


def test_identical_value_from_two_redundant_anchors_is_deduplicated() -> None:
    """The exact bug report shape: the same fact restated in a paragraph
    and in a table cell produces two 'stated' candidates for the same
    value -- these collapse to one."""

    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $45,000,000"),
            DocumentAnchor(anchor="table:0:cell:1:1", page=2, text="Purchase Price: $45,000,000"),
        )
    )
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "45000000", "status": "stated", "anchor": "paragraph:0"},
                {"value": "45000000", "status": "stated", "anchor": "table:0:cell:1:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.purchase_price.candidates) == 1
    assert result.purchase_price.candidates[0].status is EvidenceStatus.STATED


def test_equivalent_value_in_a_different_representation_is_deduplicated() -> None:
    """Deduplication compares normalized values, not literal strings: a
    percent-scale field's literal-percent and decimal-fraction
    representations of the same evidence still collapse."""

    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=1, text="Occupancy: 95.0%"),
            DocumentAnchor(anchor="table:0:cell:0:0", page=1, text="Occupancy: 95.0%"),
        )
    )
    raw = _empty_response(
        {
            "occupancy": [
                {"value": "0.95", "status": "interpreted", "anchor": "paragraph:0"},
                {"value": "95.0", "status": "interpreted", "anchor": "table:0:cell:0:0"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.occupancy.candidates) == 1


def test_same_value_but_different_status_is_not_deduplicated() -> None:
    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $45,000,000"),
            DocumentAnchor(anchor="paragraph:1", page=1, text="Purchase Price: $45,000,000"),
        )
    )
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "45000000", "status": "stated", "anchor": "paragraph:0"},
                {"value": "45000000", "status": "interpreted", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.purchase_price.candidates) == 2


def test_same_value_but_non_redundant_evidence_is_not_deduplicated() -> None:
    """Two genuinely distinct statements of the same figure, from
    unrelated evidence text, are corroboration -- not the Azure DI
    duplicate-anchor artifact dedup exists to remove -- so both stay."""

    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=1, text="Asking Price: $45,000,000"),
            DocumentAnchor(
                anchor="paragraph:1",
                page=5,
                text="The seller's broker opinion of value is $45,000,000.",
            ),
        )
    )
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "45000000", "status": "stated", "anchor": "paragraph:0"},
                {"value": "45000000", "status": "stated", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.purchase_price.candidates) == 2


def test_genuinely_conflicting_candidates_are_never_deduplicated() -> None:
    """R8: differing values for the same field are never collapsed by
    dedup, even when both cite anchors on the same page/section."""

    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=1, text="Current Occupancy: 95.0%"),
            DocumentAnchor(
                anchor="paragraph:1", page=1, text="Trailing Twelve-Month Occupancy: 94.0%"
            ),
        )
    )
    raw = _empty_response(
        {
            "occupancy": [
                {"value": "95.0", "status": "stated", "anchor": "paragraph:0"},
                {"value": "94.0", "status": "stated", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.occupancy.candidates) == 2
    assert all(c.status is EvidenceStatus.CONFLICTING for c in result.occupancy.candidates)
    assert {c.value for c in result.occupancy.candidates} == {"95.0", "94.0"}


def test_unverifiable_candidates_with_no_provenance_are_never_deduplicated() -> None:
    """A candidate with no citation to compare (nonexistent anchor) is
    never treated as redundant with another, even if the values match."""

    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $45,000,000"),)
    )
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "45000000", "status": "stated", "anchor": "paragraph:99"},
                {"value": "45000000", "status": "stated", "anchor": "paragraph:98"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.purchase_price.candidates) == 2
    assert all(c.status is EvidenceStatus.UNVERIFIABLE for c in result.purchase_price.candidates)


# =============================================================================
# Human-readable magnitude normalization (K/thousand, M/million, B/billion)
# -- representation normalization only, never a financial calculation.
# =============================================================================


def test_million_word_suffix_verifies_the_full_numeric_value() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $45.0 million"),)
    )
    raw = _empty_response(
        {"purchase_price": [{"value": "45000000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.purchase_price.candidates[0].status is EvidenceStatus.STATED


def test_million_word_suffix_with_decimal_verifies_the_full_numeric_value() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Current NOI: $2.50 million"),)
    )
    raw = _empty_response(
        {"current_noi": [{"value": "2500000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.current_noi.candidates[0].status is EvidenceStatus.STATED


def test_m_suffix_with_no_space_verifies_the_full_numeric_value() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $45M"),)
    )
    raw = _empty_response(
        {"purchase_price": [{"value": "45000000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.purchase_price.candidates[0].status is EvidenceStatus.STATED


def test_k_suffix_verifies_the_full_numeric_value() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Current NOI: $150K"),)
    )
    raw = _empty_response(
        {"current_noi": [{"value": "150000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.current_noi.candidates[0].status is EvidenceStatus.STATED


def test_thousand_word_suffix_verifies_the_full_numeric_value() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Current NOI: $150 thousand"),)
    )
    raw = _empty_response(
        {"current_noi": [{"value": "150000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.current_noi.candidates[0].status is EvidenceStatus.STATED


def test_billion_word_suffix_verifies_the_full_numeric_value() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $1.2 billion"),)
    )
    raw = _empty_response(
        {"purchase_price": [{"value": "1200000000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.purchase_price.candidates[0].status is EvidenceStatus.STATED


def test_b_suffix_verifies_the_full_numeric_value() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $1.2B"),)
    )
    raw = _empty_response(
        {"purchase_price": [{"value": "1200000000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.purchase_price.candidates[0].status is EvidenceStatus.STATED


def test_magnitude_normalization_does_not_break_a_genuine_mismatch() -> None:
    """A cited $45 thousand must still never verify a proposed $45,000,000
    -- magnitude parsing is representation normalization, not license to
    match any figure at any scale."""

    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $45 thousand"),)
    )
    raw = _empty_response(
        {"purchase_price": [{"value": "45000000", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.purchase_price.candidates[0].status is EvidenceStatus.UNVERIFIABLE


def test_unrelated_hyphenated_word_in_snippet_does_not_corrupt_the_match() -> None:
    """Root cause of the 'expected occupancy conflict not surfaced' report:
    a snippet's own unrelated hyphenated qualifier (T-12 is common OM
    shorthand for trailing-twelve-months) must never be misread as part of
    the cited number -- verification must find 94.0 among the snippet's
    numbers, not seize on the unrelated "-12" from "T-12" and reject it."""

    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="T-12 Occupancy: 94.0%"),)
    )
    raw = _empty_response(
        {"occupancy": [{"value": "94.0", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.occupancy.candidates[0].status is EvidenceStatus.STATED


def test_magnitude_suffix_does_not_apply_outside_numeric_or_hybrid_fields() -> None:
    """A text field's value must still be matched by normalized substring,
    unaffected by magnitude-word parsing (e.g. a property named containing
    the word "Million")."""

    document = StructuredDocument(
        anchors=(
            DocumentAnchor(
                anchor="paragraph:0", page=1, text="Property Name: Million Oaks Apartments"
            ),
        )
    )
    raw = _empty_response(
        {
            "property_name": [
                {"value": "Million Oaks Apartments", "status": "stated", "anchor": "paragraph:0"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert result.deal_context.property_name.candidates[0].status is EvidenceStatus.STATED


# =============================================================================
# Diagnostic regression for the "expected occupancy conflict not surfaced"
# report: proves the deterministic stages downstream of the GPT response
# (anchor/value verification, conflict resolution, dedup) never drop a
# second, distinctly-anchored, distinctly-valued occupancy candidate. If a
# live extraction ever shows only one occupancy candidate again, this test
# passing means the cause is upstream of this module -- either Azure DI
# never produced a separate anchor for the second value, or the GPT
# response itself omitted the second candidate.
# =============================================================================


def test_two_distinctly_anchored_occupancy_values_both_survive_end_to_end() -> None:
    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=1, text="Current Occupancy: 95.0%"),
            DocumentAnchor(
                anchor="paragraph:1",
                page=1,
                text="Trailing Twelve-Month (T-12) Occupancy: 94.0%",
            ),
        )
    )
    raw = _empty_response(
        {
            "occupancy": [
                {"value": "95.0", "status": "stated", "anchor": "paragraph:0"},
                {"value": "94.0", "status": "stated", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify(system_prompt="sys", user_prompt="user", document=document)

    assert len(result.occupancy.candidates) == 2
    values_by_status = {c.value: c.status for c in result.occupancy.candidates}
    assert values_by_status == {
        "95.0": EvidenceStatus.CONFLICTING,
        "94.0": EvidenceStatus.CONFLICTING,
    }
    assert all(c.provenance is not None for c in result.occupancy.candidates)


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
