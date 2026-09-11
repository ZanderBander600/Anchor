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
from collections.abc import Iterable
from datetime import date
from enum import Enum
from typing import Any

from ..contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from ..analysis import (
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    MarketLeasingAssumptions,
    Suite,
)


class UnfingerprintableValueError(TypeError):
    """A value reached canonical serialization that has no defined stable
    representation.

    Raised rather than stringified. ``default=str`` would make *every* future
    type silently fingerprintable via its ``repr`` -- which is unstable across
    Python versions, and which would let two economically different values
    share a digest (or the same value produce two digests) without anyone
    noticing. A fingerprint whose failure mode is silence is worse than no
    fingerprint, because a stale analysis snapshot would be served as current.
    """

    def __init__(self, value: object) -> None:
        self.offending_type = type(value).__name__
        super().__init__(
            f"No canonical fingerprint representation for a value of type "
            f"{self.offending_type!r}. Add an explicit rule rather than "
            "relying on its string form."
        )


def _canonical(value: object) -> object:
    """The explicit, type-aware canonical form of one value.

    Called only for values ``json`` cannot encode natively, so the primitives it
    already handles -- ``str``, ``bool``, ``int``, ``float``, ``None``, ``list``,
    ``dict`` -- keep byte-identical output and every pre-existing digest is
    preserved unchanged.

    Two rules, and no catch-all:

    * ``date`` -> ISO-8601. Chosen because it is already the wire and storage
      representation, so one value has one spelling everywhere.
    * ``Enum`` -> its ``value``, which is the wire token. Fingerprinting the
      member *name* instead would make a token rename invisible.

    Anything else raises.
    """

    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise UnfingerprintableValueError(value)


def _fingerprint_json(value: dict[str, Any]) -> str:
    """A stable sha256 fingerprint of a JSON-serializable dict: canonical
    (sorted-key, no whitespace) serialization first, so semantically
    identical input always fingerprints identically regardless of field
    insertion order.

    D5.4 adds ``default=_canonical`` for the ``date`` and ``Enum`` values every
    Lease-Level contract carries -- previously a hard ``TypeError`` deep inside
    ``json``. Quick and Detailed inputs contain neither, so ``default`` is never
    consulted for them and their digests are byte-identical to before; a test
    pins the exact pre-D5.4 hashes.
    """

    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=_canonical
    )
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


def fingerprint_lease_level_inputs(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
) -> str:
    """The authoritative financial-input fingerprint for a Lease-Level deal.

    Every field of every contract the deterministic pipeline reads -- the same
    six arguments ``analyze_lease_level_acquisition_with_projection`` takes,
    which is what makes "the fingerprint covers the analysis" checkable rather
    than asserted. Built from ``dataclasses.asdict``, so a field added to
    ``Suite`` or ``Lease`` is covered the day it is added; nothing here lists
    field names, and there is no allowlist to forget to update.

    **Canonical over economics, not over presentation.** Suites and leases are
    sorted by id before hashing, and the display ``ordinal`` is not a contract
    field so it never reaches this function at all. The engine addresses both
    collections by id -- ``lease_for_suite``, the suite/lease association rules
    -- so reordering a rent roll changes no number, and a fingerprint that moved
    would invalidate a still-valid snapshot for a purely cosmetic edit.

    Sorting is emphatically *not* deduplication. Two suites sharing an id remain
    two entries here and are refused downstream by ``DUPLICATE_SUITE_ID``;
    collapsing them would let an invalid rent roll fingerprint as a valid one.

    Excludes ``deal_context`` for the same reason the Quick and Detailed
    fingerprints do (Gate A4): it never reaches a calculation. Excludes the deal
    id, name and timestamps for the same reason.

    Keyed under ``"lease_level"``, mirroring how the Detailed fingerprint nests
    its two contracts, so no two modes can collide on a digest.
    """

    return _fingerprint_json(
        {
            "lease_level": {
                "terms": dataclasses.asdict(terms),
                "property_inputs": dataclasses.asdict(property_inputs),
                "operating_inputs": dataclasses.asdict(operating_inputs),
                "market_leasing": dataclasses.asdict(market_leasing),
                "suites": [
                    dataclasses.asdict(suite)
                    for suite in sorted(suites, key=lambda suite: suite.suite_id)
                ],
                "leases": [
                    dataclasses.asdict(lease)
                    for lease in sorted(leases, key=lambda lease: lease.lease_id)
                ],
            }
        }
    )
