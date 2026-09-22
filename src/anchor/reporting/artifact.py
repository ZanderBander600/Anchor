"""Phase 7 Gate P7.10 Stage 4 -- the immutable published report artifact.

Ratified at the Stage 4 independent review (Correction 1). A published memo
version is an immutable decision artifact, so the numbers a committee read and
the PDF they were issued must not change afterwards -- not when the underwriting
moves, not when a Strategy or Scenario changes, not when the analysis is rerun,
and not when this presentation code is edited.

**What is frozen.** At publication Anchor assembles the typed report document
once, renders the deterministic PDF once, and stores both beside the version in
one atomic operation. Every later read of that version returns the stored bytes.
Producing an updated report means publishing a *new* version.

**Why a serialized payload is allowed here.** Section 15 forbids an opaque JSON
blob becoming the authoritative contract, and this does not become one. It is a
**publication artifact**, not domain persistence and not a second financial
authority:

- it is produced exclusively from typed backend assembly;
- it carries an explicit ``report_schema_version``;
- it decodes fail-closed -- an unknown version, a missing field or a wrong type
  refuses rather than guessing;
- it is serialized canonically, so identical content is identical bytes;
- it holds no formula, no expression and nothing a reader could recalculate
  from; every figure is text the backend already formatted;
- it is never patched, partially updated, or written twice.

Nothing reads it to make a decision. The live memo domain, the fingerprints, the
staleness rules and the publication prerequisites are all exactly where Stage 2
put them, and this layer neither consults nor contradicts them.

**Current freshness lives outside the artifact.** Whether today's analysis still
matches what a version recorded is a real and useful question, and it is
answered by the Stage 2 freshness route against the dependency ledger. It is
displayed *around* the frozen report, never inside it: a stale marking painted
onto an issued document would be a change to the document.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .contracts import (
    MemoReportDisclosure,
    MemoReportEvidenceEntry,
    MemoReportMetric,
    MemoReportNarrativeItem,
    MemoReportOrigin,
    MemoReportPackage,
    MemoReportSection,
    MemoReportTable,
    MemoReportValuation,
    ReportFreshness,
    ReportUnavailable,
)

#: The report document's own schema version.
#:
#: Independent of the database schema: this says how the *payload* is shaped, so
#: a later gate that adds a report section bumps this without touching SQLite,
#: and a payload written by a newer Anchor is refused by an older one rather
#: than half-read.
REPORT_SCHEMA_VERSION = 1


class ReportArtifactError(Exception):
    """A stored report artifact that cannot be trusted.

    Raised on a payload this build cannot decode exactly: an unknown schema
    version, a missing field, a wrong type. Deliberately not a "best effort"
    decode -- a committee document rendered from a half-understood payload is
    worse than one that refuses to open.
    """


class ReportArtifactUnavailableReason(StrEnum):
    """Why a published version has no report artifact.

    One member today, and it is a *historical* condition rather than a fault:
    versions published before schema 16 were never issued a frozen report,
    because Anchor did not store one. They are still readable memo versions.
    """

    #: Published before schema 16. The migration deliberately does not backfill
    #: one, because the only way to produce it now would be to recompute today's
    #: numbers and present them as what that committee read.
    REPORT_SNAPSHOT_NOT_AVAILABLE = "report_snapshot_not_available"


#: What the analyst is told, and what to do about it.
REPORT_SNAPSHOT_NOT_AVAILABLE_MESSAGE = (
    "This version was published before Anchor began storing an immutable report "
    "with each version, so no issued report or PDF exists for it. Its memo content, "
    "evidence and recorded decision are unchanged and still readable. Publish a new "
    "version if you need a current report you can issue."
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoReportArtifact:
    """One published version's frozen report and the exact PDF it was issued as.

    One-to-one with a published version and written only by the publication
    transaction. No store or API path updates or deletes one: a published
    artifact is removed only when the whole Investment is, exactly as the
    version rows themselves are.

    ``report_hash`` covers the canonical document bytes and ``pdf_hash`` the PDF
    bytes, so a reader can confirm the file they hold is the file that was
    issued.
    """

    version_id: str
    report_schema_version: int
    #: The canonical serialization of the typed report document.
    report_document: str
    report_hash: str
    #: The exact bytes issued at publication. Repeated downloads return these.
    pdf_bytes: bytes
    pdf_hash: str
    pdf_filename: str
    page_count: int
    created_at: str

    def package(self) -> MemoReportPackage:
        """The frozen report, decoded fail-closed."""

        return decode_report_document(self.report_document, self.report_schema_version)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> str:
    """One value as canonical JSON: sorted keys, no incidental whitespace.

    The same convention ``anchor.deals.fingerprint`` uses, for the same reason:
    identical content must serialize to identical bytes, so a hash means
    something and two publications of the same report are comparable.
    """

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def encode_report_document(package: MemoReportPackage) -> tuple[str, str]:
    """One assembled report as its canonical payload and that payload's hash.

    ``dataclasses.asdict`` walks the typed tree the assembler produced, and every
    leaf is already a string, a bool, an int or ``None`` -- there is no float in
    a report package, so there is no rounding to disagree about and nothing a
    reader could recalculate from.
    """

    document = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "package": dataclasses.asdict(package),
    }
    payload = canonical_json(document)
    return payload, _digest(payload.encode("utf-8"))


# =============================================================================
# Fail-closed decoding
# =============================================================================


def _require(raw: Any, key: str, kind: type | tuple[type, ...], where: str) -> Any:
    if not isinstance(raw, dict) or key not in raw:
        raise ReportArtifactError(f"{where} is missing {key!r}.")
    value = raw[key]
    if value is not None and not isinstance(value, kind):
        raise ReportArtifactError(
            f"{where}.{key} must be {kind}, not {type(value).__qualname__}."
        )
    return value


def _text(raw: Any, key: str, where: str) -> str:
    value = _require(raw, key, str, where)
    if value is None:
        raise ReportArtifactError(f"{where}.{key} must be text.")
    return value


def _optional_text(raw: Any, key: str, where: str) -> str | None:
    return _require(raw, key, str, where)


def _flag(raw: Any, key: str, where: str) -> bool:
    value = _require(raw, key, bool, where)
    if value is None:
        raise ReportArtifactError(f"{where}.{key} must be true or false.")
    return value


def _tuple_of(raw: Any, key: str, where: str) -> tuple[Any, ...]:
    value = _require(raw, key, list, where)
    if value is None:
        raise ReportArtifactError(f"{where}.{key} must be a list.")
    return tuple(value)


def _strings(raw: Any, key: str, where: str) -> tuple[str, ...]:
    values = _tuple_of(raw, key, where)
    for entry in values:
        if not isinstance(entry, str):
            raise ReportArtifactError(f"{where}.{key} must hold only text.")
    return values  # type: ignore[return-value]


def _integers(raw: Any, key: str, where: str) -> tuple[int, ...]:
    values = _tuple_of(raw, key, where)
    for entry in values:
        if not isinstance(entry, int) or isinstance(entry, bool):
            raise ReportArtifactError(f"{where}.{key} must hold only whole numbers.")
    return values  # type: ignore[return-value]


def _unavailable(raw: Any, where: str) -> ReportUnavailable | None:
    if raw is None:
        return None
    return ReportUnavailable(
        reason_code=_text(raw, "reason_code", where),
        reason=_text(raw, "reason", where),
        label=_text(raw, "label", where),
    )


def _metric(raw: Any, where: str) -> MemoReportMetric:
    value = _optional_text(raw, "value", where)
    unavailable = _unavailable(_require(raw, "unavailable", dict, where), f"{where}.unavailable")
    if (value is None) == (unavailable is None):
        raise ReportArtifactError(
            f"{where} must carry exactly one of a value and an unavailable reason."
        )
    return MemoReportMetric(
        label=_text(raw, "label", where),
        value=value,
        unavailable=unavailable,
        note=_optional_text(raw, "note", where),
    )


def _table(raw: Any, where: str) -> MemoReportTable:
    rows = _tuple_of(raw, "rows", where)
    decoded: list[tuple[str, ...]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or any(not isinstance(cell, str) for cell in row):
            raise ReportArtifactError(f"{where}.rows[{index}] must hold only text cells.")
        decoded.append(tuple(row))
    return MemoReportTable(
        caption=_text(raw, "caption", where),
        headers=_strings(raw, "headers", where),
        rows=tuple(decoded),
        align_right=_integers(raw, "align_right", where),
        emphasize_rows=_integers(raw, "emphasize_rows", where),
        note=_optional_text(raw, "note", where),
    )


def _narrative(raw: Any, where: str) -> MemoReportNarrativeItem:
    return MemoReportNarrativeItem(
        text=_text(raw, "text", where),
        detail=_optional_text(raw, "detail", where),
        labels=_strings(raw, "labels", where),
        evidence_labels=_strings(raw, "evidence_labels", where),
        sourced=_flag(raw, "sourced", where),
    )


def _disclosure(raw: Any, where: str) -> MemoReportDisclosure:
    return MemoReportDisclosure(
        title=_text(raw, "title", where),
        detail=_text(raw, "detail", where),
        scope=_optional_text(raw, "scope", where),
    )


def _evidence(raw: Any, where: str) -> MemoReportEvidenceEntry:
    return MemoReportEvidenceEntry(
        title=_text(raw, "title", where),
        source_kind=_text(raw, "source_kind", where),
        reference=_text(raw, "reference", where),
        as_of_date=_optional_text(raw, "as_of_date", where),
        approved=_flag(raw, "approved", where),
        cited_by=_strings(raw, "cited_by", where),
    )


def _valuation(raw: Any, where: str) -> MemoReportValuation:
    return MemoReportValuation(
        label=_text(raw, "label", where),
        kind=_text(raw, "kind", where),
        timing=_text(raw, "timing", where),
        scope=_text(raw, "scope", where),
        value=_optional_text(raw, "value", where),
        unavailable=_unavailable(
            _require(raw, "unavailable", dict, where), f"{where}.unavailable"
        ),
        selected=_flag(raw, "selected", where),
        consumed=_flag(raw, "consumed", where),
        system_controlled=_flag(raw, "system_controlled", where),
        analyst_supplied=_flag(raw, "analyst_supplied", where),
    )


def _section(raw: Any, where: str) -> MemoReportSection:
    return MemoReportSection(
        title=_text(raw, "title", where),
        subtitle=_optional_text(raw, "subtitle", where),
        narrative=tuple(
            _narrative(entry, f"{where}.narrative[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "narrative", where))
        ),
        metrics=tuple(
            _metric(entry, f"{where}.metrics[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "metrics", where))
        ),
        tables=tuple(
            _table(entry, f"{where}.tables[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "tables", where))
        ),
        body=_optional_text(raw, "body", where),
        disclosures=tuple(
            _disclosure(entry, f"{where}.disclosures[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "disclosures", where))
        ),
    )


def _token(value: str, enum: type[StrEnum], where: str) -> Any:
    for member in enum:
        if member.value == value:
            return member
    raise ReportArtifactError(f"{where} is not a known {enum.__name__}: {value!r}.")


def decode_report_document(payload: str, schema_version: int) -> MemoReportPackage:
    """One stored payload back into the typed report it was written from.

    **Fail-closed at every step.** An unknown schema version, a missing field, a
    wrong type or a metric carrying both a value and an unavailable reason all
    refuse. Nothing is defaulted, coerced or skipped: the point of freezing a
    committee document is that what comes back is what went in, and a decoder
    that filled a gap would quietly break exactly that.
    """

    if schema_version != REPORT_SCHEMA_VERSION:
        raise ReportArtifactError(
            f"Report schema version {schema_version} is not version "
            f"{REPORT_SCHEMA_VERSION}, which this build writes and reads. The stored "
            "report is left exactly as it is."
        )
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ReportArtifactError(f"The stored report is not valid JSON: {error}.") from None

    stated = _require(document, "report_schema_version", int, "the report")
    if stated != schema_version:
        raise ReportArtifactError(
            f"The stored report states schema version {stated} and the row records "
            f"{schema_version}; they must agree."
        )

    raw = _require(document, "package", dict, "the report")
    where = "the report package"
    return MemoReportPackage(
        origin=_token(_text(raw, "origin", where), MemoReportOrigin, f"{where}.origin"),
        investment_id=_text(raw, "investment_id", where),
        investment_name=_text(raw, "investment_name", where),
        asset_type=_optional_text(raw, "asset_type", where),
        market=_optional_text(raw, "market", where),
        version_number=_require(raw, "version_number", int, where),
        version_id=_optional_text(raw, "version_id", where),
        published_at=_optional_text(raw, "published_at", where),
        prepared_by=_optional_text(raw, "prepared_by", where),
        generated_at=_text(raw, "generated_at", where),
        decision_ask=_text(raw, "decision_ask", where),
        analyst_recommendation=_text(raw, "analyst_recommendation", where),
        committee_decision=_optional_text(raw, "committee_decision", where),
        committee_note=_optional_text(raw, "committee_note", where),
        executive_summary=_text(raw, "executive_summary", where),
        strategy_label=_text(raw, "strategy_label", where),
        scenario_label=_text(raw, "scenario_label", where),
        perspective_label=_text(raw, "perspective_label", where),
        freshness=_token(
            _text(raw, "freshness", where), ReportFreshness, f"{where}.freshness"
        ),
        verification_code=_optional_text(raw, "verification_code", where),
        key_metrics=tuple(
            _metric(entry, f"{where}.key_metrics[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "key_metrics", where))
        ),
        valuations=tuple(
            _valuation(entry, f"{where}.valuations[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "valuations", where))
        ),
        sections=tuple(
            _section(entry, f"{where}.sections[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "sections", where))
        ),
        evidence=tuple(
            _evidence(entry, f"{where}.evidence[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "evidence", where))
        ),
        disclosures=tuple(
            _disclosure(entry, f"{where}.disclosures[{index}]")
            for index, entry in enumerate(_tuple_of(raw, "disclosures", where))
        ),
        concluding_statement=_optional_text(raw, "concluding_statement", where),
        confidentiality=_text(raw, "confidentiality", where),
    )


def build_artifact(
    version_id: str, package: MemoReportPackage, pdf_bytes: bytes, filename: str, page_count: int
) -> MemoReportArtifact:
    """One version's artifact from the report it was issued as.

    Round-tripped before it is returned: the payload this writes is decoded back
    and compared, so a package that cannot survive storage is refused at
    publication rather than discovered by the committee that tries to open it.
    """

    payload, report_hash = encode_report_document(package)
    restored = decode_report_document(payload, REPORT_SCHEMA_VERSION)
    if restored != package:
        raise ReportArtifactError(
            "The assembled report does not survive canonical serialization unchanged, "
            "so it was not published."
        )
    return MemoReportArtifact(
        version_id=version_id,
        report_schema_version=REPORT_SCHEMA_VERSION,
        report_document=payload,
        report_hash=report_hash,
        pdf_bytes=pdf_bytes,
        pdf_hash=_digest(pdf_bytes),
        pdf_filename=filename,
        page_count=page_count,
        created_at=package.generated_at,
    )
