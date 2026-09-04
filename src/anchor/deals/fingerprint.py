"""Owner Return Metrics V3 Gate A7 -- canonical financial-input/AI-context
fingerprints.

Extracted from ``store.py`` (where these algorithms originated in Gate A6)
into their own module so both the storage layer and the API layer
(``anchor.api``'s ``POST /deals/fingerprint`` provenance-lookup endpoint) can
call the exact same implementation -- a fingerprint is never computed twice
by two different pieces of code that could drift apart, and it is never
duplicated in TypeScript on the frontend (see ``anchor.api``'s module
docstring for how the frontend obtains one).

Pure functions only: no I/O, no ``sqlite3``, no dependency on ``anchor.deals
.store`` or any calculation module -- these are hashes of already-validated
assumption/context values, not financial calculations, so importing this
module from ``anchor.api`` does not pull storage or engine code along with
it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

from ..contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs


def _fingerprint_json(value: dict[str, Any]) -> str:
    """A stable sha256 fingerprint of a JSON-serializable dict: canonical
    (sorted-key, no whitespace) serialization first, so semantically
    identical input always fingerprints identically regardless of field
    insertion order."""

    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_quick_inputs(inputs: AcquisitionInputs) -> str:
    """The authoritative financial-input fingerprint for a Quick deal --
    every ``AcquisitionInputs`` field, nothing else. Deliberately excludes
    ``deal_context`` (Gate A4): Deal Context never affects deterministic
    calculation, so it never affects analysis-snapshot validity."""

    return _fingerprint_json(dataclasses.asdict(inputs))


def fingerprint_detailed_inputs(
    terms: AcquisitionTerms, detailed_operating_inputs: DetailedOperatingInputs
) -> str:
    """The authoritative financial-input fingerprint for a Detailed deal --
    every ``AcquisitionTerms`` and ``DetailedOperatingInputs`` field (the
    complete deterministic-engine input set for Detailed Underwrite),
    nothing else. Excludes ``deal_context`` for the same reason as the
    Quick fingerprint above."""

    return _fingerprint_json(
        {
            "terms": dataclasses.asdict(terms),
            "detailed_operating_inputs": dataclasses.asdict(detailed_operating_inputs),
        }
    )


def fingerprint_ai(*, analysis_fingerprint: str, deal_context: str | None) -> str:
    """The AI-snapshot/AI-context fingerprint: a function of the
    deterministic analysis fingerprint (so any financial-assumption change
    invalidates the AI snapshot too, transitively -- no separate check
    needed) plus ``deal_context`` itself (so an AI result is invalidated the
    moment the stated strategy it interpreted changes), per Gate A4/A6's AI
    staleness rules."""

    return _fingerprint_json(
        {"analysis_fingerprint": analysis_fingerprint, "deal_context": deal_context}
    )
