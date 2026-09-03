"""Anchor Phase 10A OM ingestion layer.

Sits beside the Phase 9A AI Analyst layer, below the FastAPI adapter
(``anchor.api``) and strictly above nothing in the deterministic
engine -- ingestion never calls, imports, or feeds ``anchor.engine``:

    Azure Document Intelligence (non-generative layout extraction, KD1)
          ^
    GPT classifier (candidate values + evidence status + provenance)
          ^
    ingestion/orchestrator (calls each provider exactly once)
          ^
        FastAPI
          ^
         React (analyst approves/edits/rejects before AcquisitionInputs)

This package performs no financial calculation. GPT never receives the raw
uploaded PDF (KD1) -- only Azure DI's flattened, anchor-addressable layout
payload (``StructuredDocument``). Every provider raises the one shared
``ExtractionError`` hierarchy defined in ``contracts.py`` (KTD10).
"""

from __future__ import annotations

from .contracts import (
    ACQUISITION_FIELD_IDS,
    DEAL_CONTEXT_FIELD_IDS,
    DETAILED_OPERATING_FIELD_IDS,
    DETAILED_TERMS_FIELD_IDS,
    DealContext,
    DetailedExtractionResult,
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
from .orchestrator import extract_detailed_om, extract_om

__all__ = [
    "ACQUISITION_FIELD_IDS",
    "DEAL_CONTEXT_FIELD_IDS",
    "DETAILED_OPERATING_FIELD_IDS",
    "DETAILED_TERMS_FIELD_IDS",
    "DealContext",
    "DetailedExtractionResult",
    "DocumentAnchor",
    "EvidenceStatus",
    "ExtractionCandidate",
    "ExtractionConfigurationError",
    "ExtractionError",
    "ExtractionProviderError",
    "ExtractionResult",
    "FieldCandidates",
    "Provenance",
    "StructuredDocument",
    "extract_detailed_om",
    "extract_om",
]
