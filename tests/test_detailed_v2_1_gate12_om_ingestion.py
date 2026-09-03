"""Detailed Operating Model V2.1 Gate 12 -- Detailed OM ingestion.

Mirrors ``test_ingestion_contracts.py``/``test_ingestion_classifier_provider.py``/
``test_ingestion_orchestrator.py``'s style, over the Detailed field set
(``DetailedExtractionResult``: the eleven ``AcquisitionTerms`` fields plus
the eleven ``DetailedOperatingInputs`` fields a document may support).
Every test here uses a fake client/provider -- never a real Azure/OpenAI
call.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from typing import Any

import pytest

from anchor.ingestion.classifier_provider import (
    DETAILED_CLASSIFICATION_JSON_SCHEMA,
    GPTClassifierProvider,
)
from anchor.ingestion.contracts import (
    DETAILED_OPERATING_FIELD_IDS,
    DETAILED_TERMS_FIELD_IDS,
    DetailedExtractionResult,
    DocumentAnchor,
    EvidenceStatus,
    ExtractionCandidate,
    ExtractionConfigurationError,
    ExtractionProviderError,
    FieldCandidates,
    Provenance,
    StructuredDocument,
)
from anchor.ingestion.orchestrator import extract_detailed_om

_ALL_FIELD_IDS = (*DETAILED_TERMS_FIELD_IDS, *DETAILED_OPERATING_FIELD_IDS)


# =============================================================================
# 1. Contract shape
# =============================================================================


def test_detailed_extraction_result_supports_all_22_detailed_target_fields() -> None:
    field_names = set(DetailedExtractionResult.__dataclass_fields__)
    assert field_names == set(_ALL_FIELD_IDS)


def test_detailed_extraction_result_carries_no_current_noi_or_deal_context() -> None:
    """NOI discipline (Section 6/9 of the gate brief): there is no field on
    this contract an analyst could even attempt to approve a reported NOI,
    current_noi, noi_growth, or occupancy into -- the contract simply
    offers none of them. Also carries no deal_context (out of this gate's
    target-field scope)."""

    field_names = set(DetailedExtractionResult.__dataclass_fields__)
    assert "current_noi" not in field_names
    assert "noi_growth" not in field_names
    assert "occupancy" not in field_names
    assert "deal_context" not in field_names


def test_detailed_extraction_result_never_carries_calculated_fields() -> None:
    field_names = set(DetailedExtractionResult.__dataclass_fields__)
    for calculated in (
        "noi_by_year",
        "exit_noi",
        "operating_projection",
        "results",
        "levered_irr",
        "equity_multiple",
        "dscr_by_year",
    ):
        assert calculated not in field_names


# =============================================================================
# Classifier provider fixtures
# =============================================================================


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


def _empty_response(overrides: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {field_id: [] for field_id in _ALL_FIELD_IDS}
    if overrides:
        body.update(overrides)
    return body


DOCUMENT = StructuredDocument(
    anchors=(
        DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $10,000,000"),
        DocumentAnchor(anchor="paragraph:1", page=31, text="Potential Base Rent: $800,000"),
        DocumentAnchor(anchor="paragraph:2", page=32, text="Real Estate Taxes: $60,000"),
        DocumentAnchor(anchor="paragraph:3", page=33, text="Reported NOI: $500,000"),
        DocumentAnchor(anchor="paragraph:4", page=34, text="Current Occupancy: 95%"),
        DocumentAnchor(
            anchor="paragraph:5", page=35, text="Management Fee Expense: $40,000"
        ),
    )
)


# =============================================================================
# 2. Complete extraction maps values correctly
# =============================================================================


def test_stated_candidate_verifies_and_maps_to_the_correct_detailed_field() -> None:
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "10000000", "status": "stated", "anchor": "paragraph:0"}
            ],
            "gross_potential_rent": [
                {"value": "800000", "status": "stated", "anchor": "paragraph:1"}
            ],
            "property_taxes": [
                {"value": "60000", "status": "stated", "anchor": "paragraph:2"}
            ],
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    assert isinstance(result, DetailedExtractionResult)
    assert len(result.purchase_price.candidates) == 1
    assert result.purchase_price.candidates[0].value == "10000000"
    assert result.purchase_price.candidates[0].status is EvidenceStatus.STATED
    assert result.gross_potential_rent.candidates[0].value == "800000"
    assert result.property_taxes.candidates[0].value == "60000"


# =============================================================================
# 3/4. Missing fields remain unresolved, not zero; explicit zero stays
# distinguishable from missing.
# =============================================================================


def test_unsupplied_fields_are_missing_not_zero() -> None:
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "10000000", "status": "stated", "anchor": "paragraph:0"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    assert result.insurance.candidates == ()
    assert result.revenue_growth.candidates == ()
    assert result.vacancy_credit_loss_pct.candidates == ()


def test_explicit_zero_value_is_a_real_candidate_not_confused_with_missing() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=5, text="Other Income: $0"),)
    )
    raw = _empty_response(
        {"other_income": [{"value": "0", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=document
    )

    assert len(result.other_income.candidates) == 1
    assert result.other_income.candidates[0].value == "0"
    assert result.other_income.candidates[0].status is EvidenceStatus.STATED


# =============================================================================
# 5. Evidence/source survives into the Detailed response.
# =============================================================================


def test_evidence_provenance_survives_into_the_detailed_response() -> None:
    raw = _empty_response(
        {
            "gross_potential_rent": [
                {"value": "800000", "status": "stated", "anchor": "paragraph:1"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    provenance = result.gross_potential_rent.candidates[0].provenance
    assert provenance == Provenance(
        page=31, anchor="paragraph:1", snippet="Potential Base Rent: $800,000"
    )


# =============================================================================
# 6/7. Gross Potential Rent / expense extraction does not calculate
# EGI/NOI/Total Opex -- there is no such field on the contract for the
# classifier to populate, and a proposed value must independently verify
# against its own cited anchor (never derived from combining fields).
# =============================================================================


def test_gross_potential_rent_and_property_taxes_never_derive_from_each_other() -> None:
    raw = _empty_response(
        {
            "gross_potential_rent": [
                {"value": "800000", "status": "stated", "anchor": "paragraph:1"}
            ],
            "property_taxes": [
                {"value": "60000", "status": "stated", "anchor": "paragraph:2"}
            ],
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    # Each field's candidate cites its own anchor; the contract has no NOI/
    # EGI/total-opex field for a calculated value to occupy in the first
    # place (test 1 above already proves that structurally).
    assert result.gross_potential_rent.candidates[0].provenance.anchor == "paragraph:1"
    assert result.property_taxes.candidates[0].provenance.anchor == "paragraph:2"


def test_a_value_not_numerically_present_in_its_cited_anchor_is_unverifiable() -> None:
    """A candidate whose proposed value does not literally appear in its
    cited anchor's text fails KTD12 verification and is downgraded to
    unverifiable -- it never becomes a verified, engine-eligible value,
    regardless of which anchor was cited (e.g. the Reported NOI sentence
    supports "500000", never "650000")."""

    raw = _empty_response(
        {
            "gross_potential_rent": [
                {"value": "650000", "status": "stated", "anchor": "paragraph:3"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    assert result.gross_potential_rent.candidates[0].status is EvidenceStatus.UNVERIFIABLE


def test_deterministic_verification_cannot_tell_gross_potential_rent_from_a_same_numbered_noi_statement() -> None:
    """Documents the real boundary of KTD12's deterministic verification:
    it checks that a proposed value is numerically present in its cited
    anchor, not that the anchor is semantically the right kind of fact for
    the field. A candidate that (incorrectly) cites the Reported NOI
    sentence for gross_potential_rent, using that same number, therefore
    verifies -- this is exactly why the Detailed system prompt (Section 9,
    ``prompts.DETAILED_SYSTEM_PROMPT``) explicitly instructs the model
    never to treat a reported NOI as evidence for any Detailed field; the
    deterministic layer cannot enforce that semantic distinction on its
    own."""

    raw = _empty_response(
        {
            "gross_potential_rent": [
                {"value": "500000", "status": "stated", "anchor": "paragraph:3"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    assert result.gross_potential_rent.candidates[0].status is EvidenceStatus.STATED


# =============================================================================
# 8. Reported OM NOI does not replace deterministic Detailed NOI -- there is
# no field on the contract for it to occupy at all.
# =============================================================================


def test_no_field_exists_for_a_reported_om_noi_to_populate() -> None:
    assert "current_noi" not in _ALL_FIELD_IDS
    assert not hasattr(DetailedExtractionResult, "current_noi")


# =============================================================================
# 9. No current_noi/noi_growth fabricated for Detailed mode.
# =============================================================================


def test_classify_detailed_response_object_has_no_current_noi_or_noi_growth_attribute() -> None:
    raw = _empty_response()
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    assert not hasattr(result, "current_noi")
    assert not hasattr(result, "noi_growth")


# =============================================================================
# 10. Occupancy does not become a second economic vacancy mechanism -- there
# is no occupancy field on the Detailed contract, so even a document that
# states occupancy cannot have it verify vacancy_credit_loss_pct (different
# underlying fact/anchor text).
# =============================================================================


def test_occupancy_statement_does_not_verify_a_vacancy_credit_loss_candidate() -> None:
    raw = _empty_response(
        {
            "vacancy_credit_loss_pct": [
                {"value": "5", "status": "stated", "anchor": "paragraph:4"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    # paragraph:4 is "Current Occupancy: 95%" -- 5 does not numerically
    # match 95 (nor 0.05 vs 95 under the percent-scale equivalence), so this
    # candidate fails verification rather than silently passing as if
    # occupancy were interchangeable evidence for vacancy_credit_loss_pct.
    assert result.vacancy_credit_loss_pct.candidates[0].status is EvidenceStatus.UNVERIFIABLE


def test_occupancy_is_not_a_detailed_target_field_at_all() -> None:
    assert "occupancy" not in _ALL_FIELD_IDS


# =============================================================================
# 11. Management fee dollars are not silently converted into a percentage --
# a dollar-only candidate for management_fee_pct fails the numeric-domain
# verification against its own cited (dollar) anchor text in exactly the
# way it would for any other field; nothing in this layer ever computes a
# percentage from a dollar amount and a revenue figure.
# =============================================================================


def test_a_dollar_value_cited_for_management_fee_pct_does_not_verify_as_a_percentage() -> None:
    raw = _empty_response(
        {
            "management_fee_pct": [
                {"value": "5", "status": "stated", "anchor": "paragraph:5"}
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    # paragraph:5 is "Management Fee Expense: $40,000" -- 5 (or 0.05 under
    # the percent-scale equivalence) does not numerically match 40000, so
    # this fails verification; nothing here reverse-computes 5% from
    # $40,000 and some revenue figure.
    assert result.management_fee_pct.candidates[0].status is EvidenceStatus.UNVERIFIABLE


# =============================================================================
# 12. Revenue/expense growth are not invented without source support --
# simply omitting them from the model's response leaves them missing, and
# there is no mechanism anywhere in this layer that fills them in.
# =============================================================================


def test_revenue_and_expense_growth_are_missing_when_the_model_supplies_no_candidate() -> None:
    raw = _empty_response()
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=DOCUMENT
    )

    assert result.revenue_growth.candidates == ()
    assert result.expense_growth.candidates == ()


# =============================================================================
# Conflicting / percent-scale equivalence -- the shared verification core,
# exercised through the Detailed domain.
# =============================================================================


def test_two_differing_detailed_candidates_are_marked_conflicting() -> None:
    document = StructuredDocument(
        anchors=(
            DocumentAnchor(anchor="paragraph:0", page=2, text="Purchase Price: $10,000,000"),
            DocumentAnchor(
                anchor="paragraph:1", page=4, text="Purchase Price (Summary): $10,500,000"
            ),
        )
    )
    raw = _empty_response(
        {
            "purchase_price": [
                {"value": "10000000", "status": "stated", "anchor": "paragraph:0"},
                {"value": "10500000", "status": "stated", "anchor": "paragraph:1"},
            ]
        }
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=document
    )

    assert len(result.purchase_price.candidates) == 2
    assert all(c.status is EvidenceStatus.CONFLICTING for c in result.purchase_price.candidates)


def test_detailed_percent_scale_equivalence_applies_to_exit_cap_rate() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=2, text="Exit Cap Rate: 6.5%"),)
    )
    raw = _empty_response(
        {"exit_cap_rate": [{"value": "0.065", "status": "interpreted", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=document
    )

    assert result.exit_cap_rate.candidates[0].status is EvidenceStatus.INTERPRETED


def test_detailed_percent_scale_equivalence_does_not_apply_to_purchase_price() -> None:
    """An absolute-magnitude Detailed field must never get percent-scale
    leniency: a cited "30" can never verify a proposed "3000"."""

    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=2, text="Hold Period: 5 years"),)
    )
    raw = _empty_response(
        {"purchase_price": [{"value": "500", "status": "stated", "anchor": "paragraph:0"}]}
    )
    client = _fake_client(json.dumps(raw))
    provider = GPTClassifierProvider(client=client)

    result = provider.classify_detailed(
        system_prompt="sys", user_prompt="user", document=document
    )

    assert result.purchase_price.candidates[0].status is EvidenceStatus.UNVERIFIABLE


# =============================================================================
# Malformed responses / configuration failures fail cleanly (mirrors Quick).
# =============================================================================


def test_missing_api_key_raises_configuration_error_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = GPTClassifierProvider()

    with pytest.raises(ExtractionConfigurationError):
        provider.classify_detailed(system_prompt="sys", user_prompt="user", document=DOCUMENT)


def test_non_json_response_raises_provider_error() -> None:
    client = _fake_client("not json at all")
    provider = GPTClassifierProvider(client=client)

    with pytest.raises(ExtractionProviderError):
        provider.classify_detailed(system_prompt="sys", user_prompt="user", document=DOCUMENT)


def test_request_uses_the_detailed_json_schema() -> None:
    client = _fake_client(json.dumps(_empty_response()))
    provider = GPTClassifierProvider(client=client)

    provider.classify_detailed(system_prompt="sys", user_prompt="user", document=DOCUMENT)

    call = client.responses.calls[0]
    assert call["text"]["format"]["schema"] == DETAILED_CLASSIFICATION_JSON_SCHEMA
    assert call["text"]["format"]["name"] == "detailed_om_classification"


# =============================================================================
# Orchestrator -- extract_detailed_om
# =============================================================================


class _FakeDiProvider:
    def __init__(self, *, document: StructuredDocument = DOCUMENT) -> None:
        self.calls: list[bytes] = []
        self._document = document

    def analyze(self, pdf_bytes: bytes) -> StructuredDocument:
        self.calls.append(pdf_bytes)
        return self._document


class _FailingDiProvider:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def analyze(self, pdf_bytes: bytes) -> StructuredDocument:
        raise self._error


def _missing_detailed_field(field_id: str) -> FieldCandidates:
    return FieldCandidates(field_id=field_id)


def _stated_detailed_purchase_price() -> DetailedExtractionResult:
    candidate = ExtractionCandidate(
        value="10000000",
        status=EvidenceStatus.STATED,
        provenance=Provenance(page=1, anchor="paragraph:0", snippet="Purchase Price: $10,000,000"),
    )
    fields = {field_id: _missing_detailed_field(field_id) for field_id in _ALL_FIELD_IDS}
    fields["purchase_price"] = FieldCandidates(
        field_id="purchase_price", candidates=(candidate,)
    )
    return DetailedExtractionResult(**fields)


class _FakeDetailedClassifierProvider:
    def __init__(self, *, result: DetailedExtractionResult | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._result = result if result is not None else _stated_detailed_purchase_price()

    def classify_detailed(
        self, *, system_prompt: str, user_prompt: str, document: StructuredDocument
    ) -> DetailedExtractionResult:
        self.calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "document": document}
        )
        return self._result


class _FailingDetailedClassifierProvider:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def classify_detailed(
        self, *, system_prompt: str, user_prompt: str, document: StructuredDocument
    ) -> DetailedExtractionResult:
        raise self._error


def test_extract_detailed_om_calls_di_then_classifier_exactly_once_each() -> None:
    di_provider = _FakeDiProvider()
    classifier_provider = _FakeDetailedClassifierProvider()

    result = extract_detailed_om(
        b"%PDF-1.4 fake bytes", di_provider=di_provider, classifier_provider=classifier_provider
    )

    assert len(di_provider.calls) == 1
    assert len(classifier_provider.calls) == 1
    assert isinstance(result, DetailedExtractionResult)


def test_extract_detailed_om_passes_only_the_di_providers_return_value_to_the_classifier() -> None:
    document = StructuredDocument(
        anchors=(DocumentAnchor(anchor="paragraph:0", page=1, text="unique marker text"),)
    )
    di_provider = _FakeDiProvider(document=document)
    classifier_provider = _FakeDetailedClassifierProvider()

    extract_detailed_om(
        b"%PDF-1.4 fake bytes", di_provider=di_provider, classifier_provider=classifier_provider
    )

    assert classifier_provider.calls[0]["document"] is document


def test_pdf_bytes_are_not_reachable_from_the_returned_detailed_extraction_result() -> None:
    pdf_bytes = b"%PDF-1.4 a very specific unique marker payload 99999"
    di_provider = _FakeDiProvider()
    classifier_provider = _FakeDetailedClassifierProvider()

    result = extract_detailed_om(
        pdf_bytes, di_provider=di_provider, classifier_provider=classifier_provider
    )

    serialized = pickle.dumps(result)
    assert pdf_bytes not in serialized


def test_detailed_di_configuration_error_propagates_unchanged() -> None:
    di_provider = _FailingDiProvider(ExtractionConfigurationError("Azure DI not configured."))
    classifier_provider = _FakeDetailedClassifierProvider()

    with pytest.raises(ExtractionConfigurationError):
        extract_detailed_om(
            b"%PDF-1.4", di_provider=di_provider, classifier_provider=classifier_provider
        )


def test_detailed_classifier_provider_error_propagates_unchanged() -> None:
    di_provider = _FakeDiProvider()
    classifier_provider = _FailingDetailedClassifierProvider(
        ExtractionProviderError("Classifier call failed.")
    )

    with pytest.raises(ExtractionProviderError):
        extract_detailed_om(
            b"%PDF-1.4", di_provider=di_provider, classifier_provider=classifier_provider
        )
