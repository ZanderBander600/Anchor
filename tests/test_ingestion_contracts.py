"""Tests for the Phase 10A OM ingestion contracts
(``anchor.ingestion.contracts``).

Mirrors the style of ``test_ai_contracts.py``: construction/frozen checks
for every dataclass, the exact five-member ``EvidenceStatus`` enum, and the
zero/one/many candidate shapes ``FieldCandidates`` must support (R8).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from anchor.ingestion.contracts import (
    ACQUISITION_FIELD_IDS,
    DEAL_CONTEXT_FIELD_IDS,
    DealContext,
    DocumentAnchor,
    EvidenceStatus,
    ExtractionCandidate,
    ExtractionConfigurationError,
    ExtractionError,
    ExtractionProviderError,
    ExtractionResult,
    FieldCandidates,
    Provenance,
    StructuredDocument,
)


def _field_candidates(field_id: str, *candidates: ExtractionCandidate) -> FieldCandidates:
    return FieldCandidates(field_id=field_id, candidates=candidates)


def _missing_deal_context() -> DealContext:
    return DealContext(
        **{field_id: _field_candidates(field_id) for field_id in DEAL_CONTEXT_FIELD_IDS}
    )


def _missing_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        **{field_id: _field_candidates(field_id) for field_id in ACQUISITION_FIELD_IDS},
        deal_context=_missing_deal_context(),
    )


# =============================================================================
# EvidenceStatus
# =============================================================================


def test_evidence_status_has_exactly_five_members() -> None:
    assert {member.value for member in EvidenceStatus} == {
        "stated",
        "interpreted",
        "conflicting",
        "unverifiable",
        "missing",
    }


def test_evidence_status_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        EvidenceStatus("guessed")


# =============================================================================
# DocumentAnchor / StructuredDocument
# =============================================================================


def test_document_anchor_constructs_and_is_frozen() -> None:
    anchor = DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $1,000,000")

    assert anchor.anchor == "paragraph:0"
    assert anchor.page == 1
    with pytest.raises(FrozenInstanceError):
        anchor.page = 2  # type: ignore[misc]


def test_structured_document_constructs_and_is_frozen() -> None:
    anchor = DocumentAnchor(anchor="paragraph:0", page=1, text="text")
    document = StructuredDocument(anchors=(anchor,))

    assert document.anchors == (anchor,)
    with pytest.raises(FrozenInstanceError):
        document.anchors = ()  # type: ignore[misc]


# =============================================================================
# Provenance / ExtractionCandidate
# =============================================================================


def test_provenance_constructs_and_is_frozen() -> None:
    provenance = Provenance(page=1, anchor="paragraph:0", snippet="Purchase Price: $1,000,000")

    assert provenance.page == 1
    with pytest.raises(FrozenInstanceError):
        provenance.snippet = "other"  # type: ignore[misc]


def test_extraction_candidate_constructs_with_provenance_and_is_frozen() -> None:
    provenance = Provenance(page=1, anchor="paragraph:0", snippet="$1,000,000")
    candidate = ExtractionCandidate(
        value="1000000", status=EvidenceStatus.STATED, provenance=provenance
    )

    assert candidate.value == "1000000"
    assert candidate.status is EvidenceStatus.STATED
    assert candidate.provenance is provenance
    with pytest.raises(FrozenInstanceError):
        candidate.value = "2000000"  # type: ignore[misc]


def test_extraction_candidate_provenance_defaults_to_none() -> None:
    candidate = ExtractionCandidate(value="unverified", status=EvidenceStatus.UNVERIFIABLE)

    assert candidate.provenance is None


# =============================================================================
# FieldCandidates -- zero, one, or many candidates (R8)
# =============================================================================


def test_field_candidates_accepts_empty_tuple_for_a_missing_field() -> None:
    field = FieldCandidates(field_id="purchase_price", candidates=())

    assert field.candidates == ()


def test_field_candidates_defaults_to_empty_tuple() -> None:
    field = FieldCandidates(field_id="purchase_price")

    assert field.candidates == ()


def test_field_candidates_accepts_two_or_more_candidates_for_a_conflicting_field() -> None:
    first = ExtractionCandidate(value="1000000", status=EvidenceStatus.CONFLICTING)
    second = ExtractionCandidate(value="1250000", status=EvidenceStatus.CONFLICTING)

    field = FieldCandidates(field_id="purchase_price", candidates=(first, second))

    assert len(field.candidates) == 2


def test_field_candidates_is_frozen() -> None:
    field = FieldCandidates(field_id="purchase_price", candidates=())

    with pytest.raises(FrozenInstanceError):
        field.field_id = "current_noi"  # type: ignore[misc]


# =============================================================================
# DealContext / ExtractionResult
# =============================================================================


def test_deal_context_constructs_with_all_five_fields_and_is_frozen() -> None:
    context = _missing_deal_context()

    for field_id in DEAL_CONTEXT_FIELD_IDS:
        assert getattr(context, field_id).field_id == field_id
    with pytest.raises(FrozenInstanceError):
        context.property_name = _field_candidates("property_name")  # type: ignore[misc]


def test_extraction_result_constructs_with_nine_fields_plus_deal_context() -> None:
    result = _missing_extraction_result()

    for field_id in ACQUISITION_FIELD_IDS:
        assert getattr(result, field_id).field_id == field_id
    assert isinstance(result.deal_context, DealContext)


def test_extraction_result_is_frozen() -> None:
    result = _missing_extraction_result()

    with pytest.raises(FrozenInstanceError):
        result.purchase_price = _field_candidates("purchase_price")  # type: ignore[misc]


def test_acquisition_field_ids_match_the_nine_engine_inputs() -> None:
    assert ACQUISITION_FIELD_IDS == (
        "purchase_price",
        "current_noi",
        "occupancy",
        "noi_growth",
        "hold_period",
        "exit_cap_rate",
        "ltv",
        "interest_rate",
        "amortization",
    )


def test_deal_context_field_ids_are_the_five_fixed_read_only_fields() -> None:
    assert DEAL_CONTEXT_FIELD_IDS == (
        "property_name",
        "address",
        "property_type",
        "unit_count_or_building_area",
        "year_built",
    )


# =============================================================================
# Exception hierarchy (KTD10)
# =============================================================================


def test_extraction_configuration_error_is_an_extraction_error() -> None:
    assert issubclass(ExtractionConfigurationError, ExtractionError)


def test_extraction_provider_error_is_an_extraction_error() -> None:
    assert issubclass(ExtractionProviderError, ExtractionError)


def test_extraction_error_is_a_runtime_error() -> None:
    assert issubclass(ExtractionError, RuntimeError)
