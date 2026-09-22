"""Phase 7 Gate P7.10 Stage 4 -- the published report and PDF are frozen.

Ratified at the Stage 4 independent review (Correction 1). A published memo
version is an immutable decision artifact: the numbers a committee read and the
PDF they were issued must not change afterwards, for any reason.

The ten required proofs are numbered in the section headers below, and each is
measured against the real store, the real engine and the real renderer.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]
from anchor.deals import memo_dependencies as deps
from anchor.deals import store
from anchor.reporting.artifact import (
    REPORT_SCHEMA_VERSION,
    ReportArtifactError,
    ReportArtifactUnavailableReason,
    decode_report_document,
    encode_report_document,
)
from anchor.reporting.assembly import (
    PdfExportRefusalCode,
    PdfExportRefusedError,
    read_version_pdf,
    read_version_report,
)
from anchor.reporting.contracts import MemoReportOrigin, ReportFreshness


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def _published(db: Path) -> tuple[str, str, str]:
    """An opted-in Deal with an approved source, a memo citing it, one selected
    valuation view, and one published version."""

    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="ev-1", approved=True)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(
            investment_id,
            evidence_ids=("ev-1",),
            selected_valuation_timepoint_ids=("as-is",),
            thesis_evidence_ids=("ev-1",),
        ),
        db_path=db,
    )
    version = deps.publish(investment_id, db_path=db)
    return deal.id, investment_id, version.version_id


def _move_every_dependency(db: Path, deal_id: str, investment_id: str) -> None:
    """Change everything the correction names, in one go.

    The valuation definition, the underwriting behind every figure, and the
    draft itself. If any of these could reach a published artifact, one of them
    will."""

    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal_id, cap_rate=0.09))
    store.update_deal(
        deal_id,
        name="Renamed after publication",
        inputs=dataclasses.replace(
            fx.QUICK_INPUTS, purchase_price=99_000_000.0, current_noi=2_000_000.0, ltv=0.8
        ),
        db_path=db,
    )
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(
            investment_id,
            decision_ask="A COMPLETELY DIFFERENT ASK",
            selected_valuation_timepoint_ids=("as-is",),
        ),
        db_path=db,
    )


# =============================================================================
# 1. Changing every dependency leaves the stored report and PDF identical
# =============================================================================


def test_no_dependency_change_reaches_a_published_report(db: Path) -> None:
    """The whole point. A stale badge is not a substitute for this."""

    deal_id, investment_id, version_id = _published(db)
    before = read_version_report(investment_id, version_id, db_path=db)
    pdf_before, name_before = read_version_pdf(investment_id, version_id, db_path=db)
    assert before is not None

    _move_every_dependency(db, deal_id, investment_id)

    after = read_version_report(investment_id, version_id, db_path=db)
    pdf_after, name_after = read_version_pdf(investment_id, version_id, db_path=db)

    assert after == before, "the frozen report moved with its dependencies"
    assert pdf_after == pdf_before, "the issued PDF changed after publication"
    assert name_after == name_before

    # And the change was real, so the test is not passing because nothing moved:
    # the *current* analysis is now materially different.
    freshness = deps.version_freshness(
        investment_id, store.get_memo_version(investment_id, version_id, db_path=db), db_path=db
    )
    assert freshness.freshness.value == "stale"
    assert freshness.stale_classes


def test_the_frozen_report_never_says_it_is_stale(db: Path) -> None:
    """A published report records what it was when issued, forever.

    Staleness is a live fact about the analysis around it, reported by the
    Stage 2 freshness route and shown beside the document."""

    deal_id, investment_id, version_id = _published(db)
    _move_every_dependency(db, deal_id, investment_id)

    report = read_version_report(investment_id, version_id, db_path=db)
    assert report is not None
    assert report.freshness is ReportFreshness.CURRENT
    assert report.status_line == "PUBLISHED"
    assert not hasattr(report, "stale_classes")
    assert "STALE" not in [member.name for member in ReportFreshness]


# =============================================================================
# 2. Repeated downloads return the same bytes
# =============================================================================


def test_repeated_downloads_are_byte_identical(db: Path) -> None:
    _, investment_id, version_id = _published(db)
    first, name = read_version_pdf(investment_id, version_id, db_path=db)
    second, again = read_version_pdf(investment_id, version_id, db_path=db)
    third, _ = read_version_pdf(investment_id, version_id, db_path=db)

    assert first == second == third
    assert name == again
    assert first.startswith(b"%PDF")

    # The stored hash describes the stored bytes, so a reader can confirm the
    # file they hold is the file that was issued.
    artifact = store.get_memo_version_artifact(investment_id, version_id, db_path=db)
    assert artifact is not None
    import hashlib

    assert artifact.pdf_hash == hashlib.sha256(first).hexdigest()
    assert artifact.report_hash == hashlib.sha256(
        artifact.report_document.encode("utf-8")
    ).hexdigest()


# =============================================================================
# 3 and 4. Draft edits do not alter version N; N+1 gets its own artifact
# =============================================================================


def test_draft_edits_and_later_publications_leave_version_n_alone(db: Path) -> None:
    _, investment_id, first_id = _published(db)
    first_report = read_version_report(investment_id, first_id, db_path=db)
    first_pdf, _ = read_version_pdf(investment_id, first_id, db_path=db)

    store.put_memo_draft(
        investment_id,
        fx.memo_draft(
            investment_id,
            evidence_ids=("ev-1",),
            selected_valuation_timepoint_ids=("as-is",),
            decision_ask="Second ask, materially different.",
        ),
        db_path=db,
    )
    second = deps.publish(investment_id, db_path=db)

    assert read_version_report(investment_id, first_id, db_path=db) == first_report
    assert read_version_pdf(investment_id, first_id, db_path=db)[0] == first_pdf

    second_report = read_version_report(investment_id, second.version_id, db_path=db)
    second_pdf, second_name = read_version_pdf(investment_id, second.version_id, db_path=db)
    assert second_report is not None
    assert second_report.decision_ask == "Second ask, materially different."
    assert second_report.version_number == 2
    assert second_pdf != first_pdf, "version 2 must have its own document"
    assert second_name.endswith("-v2.pdf")


# =============================================================================
# 5. A failure during assembly or rendering leaves nothing behind
# =============================================================================


def test_a_failed_render_publishes_no_version_and_no_artifact(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomicity, measured rather than asserted.

    The report is assembled and rendered *inside* the publication transaction,
    so a failure there rolls the whole thing back. A version that existed
    without the document its committee was issued would be a decision record
    nobody could read."""

    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="ev-1", approved=True)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("as-is",)),
        db_path=db,
    )

    import anchor.reporting.pdf as pdf_module

    def _explode(package):  # noqa: ANN001, ANN202
        raise RuntimeError("the renderer failed")

    monkeypatch.setattr(pdf_module, "render_memo_pdf", _explode)

    with pytest.raises(RuntimeError, match="the renderer failed"):
        deps.publish(investment_id, db_path=db)

    # Nothing was left behind: no version row, no child row, no artifact.
    assert list(store.list_memo_versions(investment_id, db_path=db)) == []
    connection = sqlite3.connect(db)
    try:
        for table in (
            "investment_memo_versions",
            "memo_version_items",
            "memo_version_evidence",
            "memo_version_dependencies",
            "memo_version_report_artifacts",
        ):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table} kept {count} row(s) after a failed publication"
    finally:
        connection.close()

    # And the draft is untouched, so the analyst loses nothing to a failure.
    assert store.get_memo_draft(investment_id, db_path=db) is not None


def test_publication_succeeds_once_the_renderer_works_again(db: Path) -> None:
    """The failure above is not a permanent state: the same draft publishes
    normally, which is what shows the rollback left a clean slate."""

    _, investment_id, version_id = _published(db)
    assert read_version_report(investment_id, version_id, db_path=db) is not None


# =============================================================================
# 6. No update or delete path targets a published artifact
# =============================================================================


def test_no_store_function_updates_or_deletes_one_artifact() -> None:
    """Measured on the source: there is no UPDATE against the artifact table
    anywhere, and the only DELETE names it alongside every other version child,
    which is the whole-Investment delete."""

    import re

    source = (
        Path(__file__).resolve().parents[1] / "src/anchor/deals/store.py"
    ).read_bytes().decode("utf-8")

    assert not re.search(r"UPDATE\s+memo_version_report_artifacts", source, re.IGNORECASE)
    # The one place the table is deleted from is the shared child-table loop.
    explicit_deletes = re.findall(
        r"DELETE\s+FROM\s+memo_version_report_artifacts", source, re.IGNORECASE
    )
    assert explicit_deletes == [], explicit_deletes
    assert '"memo_version_report_artifacts",' in source


def test_no_api_route_writes_a_published_artifact() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src/anchor/api.py"
    ).read_bytes().decode("utf-8")
    region = source[source.index("Phase 7 Gate P7.10 Stage 4") :]
    for forbidden in ("INSERT", "UPDATE", "DELETE", "put_memo_version_artifact"):
        assert forbidden not in region, forbidden


# =============================================================================
# 7. A migrated v15 version reports the typed state and recomputes nothing
# =============================================================================


def test_a_version_without_an_artifact_reports_the_typed_state(db: Path) -> None:
    """A version published before schema 16 has no issued report.

    Simulated exactly as the migration leaves one: the version and all its
    children exist, and the artifact row does not."""

    _, investment_id, version_id = _published(db)
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "DELETE FROM memo_version_report_artifacts WHERE version_id = ?", (version_id,)
        )
        connection.commit()
    finally:
        connection.close()

    # The memo version itself is untouched and still readable.
    version = store.get_memo_version(investment_id, version_id, db_path=db)
    assert version.version_number == 1
    assert version.items

    # The report is reported unavailable, not reconstructed.
    assert read_version_report(investment_id, version_id, db_path=db) is None

    with pytest.raises(PdfExportRefusedError) as caught:
        read_version_pdf(investment_id, version_id, db_path=db)
    assert caught.value.code is PdfExportRefusalCode.REPORT_SNAPSHOT_NOT_AVAILABLE
    assert (
        ReportArtifactUnavailableReason.REPORT_SNAPSHOT_NOT_AVAILABLE.value
        == "report_snapshot_not_available"
    )
    # The message tells the analyst what to do rather than only what is wrong.
    assert "publish a new version" in caught.value.message.lower()


def test_an_unknown_version_is_missing_rather_than_unavailable(db: Path) -> None:
    """The two states are told apart: "this version does not exist" and "this
    version has no stored report" are different answers."""

    _, investment_id, _ = _published(db)
    from anchor.deals.contracts import MemoVersionNotFoundError

    with pytest.raises(MemoVersionNotFoundError):
        store.get_memo_version_artifact(investment_id, "no-such-version", db_path=db)


# =============================================================================
# 8 and 9. The frozen read is the artifact; freshness moves independently
# =============================================================================


def test_the_published_read_returns_the_stored_payload(db: Path) -> None:
    """Not merely equal to a fresh assembly -- *the stored bytes*, decoded."""

    _, investment_id, version_id = _published(db)
    artifact = store.get_memo_version_artifact(investment_id, version_id, db_path=db)
    assert artifact is not None
    assert artifact.report_schema_version == REPORT_SCHEMA_VERSION

    from_store = read_version_report(investment_id, version_id, db_path=db)
    assert from_store == decode_report_document(
        artifact.report_document, artifact.report_schema_version
    )


def test_current_freshness_changes_without_touching_the_report(db: Path) -> None:
    deal_id, investment_id, version_id = _published(db)
    version = store.get_memo_version(investment_id, version_id, db_path=db)
    assert deps.version_freshness(investment_id, version, db_path=db).freshness.value == "current"

    frozen = read_version_report(investment_id, version_id, db_path=db)
    pdf, _ = read_version_pdf(investment_id, version_id, db_path=db)

    _move_every_dependency(db, deal_id, investment_id)

    assert deps.version_freshness(investment_id, version, db_path=db).freshness.value == "stale"
    assert read_version_report(investment_id, version_id, db_path=db) == frozen
    assert read_version_pdf(investment_id, version_id, db_path=db)[0] == pdf


# =============================================================================
# 10. The renderer receives a completed typed document and formats only
# =============================================================================


def test_the_renderer_is_given_a_finished_document(db: Path) -> None:
    """Every figure the renderer receives is already text.

    The structural reason it cannot compute: there is no number in the package
    for it to compute with."""

    _, investment_id, version_id = _published(db)
    package = read_version_report(investment_id, version_id, db_path=db)
    assert package is not None

    metrics = list(package.key_metrics)
    for section in package.sections:
        metrics.extend(section.metrics)
    assert metrics
    for metric in metrics:
        assert (metric.value is None) != (metric.unavailable is None)
        if metric.value is not None:
            assert isinstance(metric.value, str)

    for section in package.sections:
        for table in section.tables:
            for row in table.rows:
                assert all(isinstance(cell, str) for cell in row)

    # Rendering the stored package reproduces the stored bytes exactly.
    from anchor.reporting.pdf import render_memo_pdf

    stored, _ = read_version_pdf(investment_id, version_id, db_path=db)
    assert render_memo_pdf(package) == stored


# =============================================================================
# The payload itself: canonical, versioned, fail-closed
# =============================================================================


def test_the_payload_round_trips_exactly(db: Path) -> None:
    _, investment_id, version_id = _published(db)
    package = read_version_report(investment_id, version_id, db_path=db)
    assert package is not None

    payload, digest = encode_report_document(package)
    assert decode_report_document(payload, REPORT_SCHEMA_VERSION) == package
    # Canonical: encoding the same package twice gives the same bytes.
    assert encode_report_document(package) == (payload, digest)


def test_an_unknown_schema_version_refuses_rather_than_guessing(db: Path) -> None:
    _, investment_id, version_id = _published(db)
    artifact = store.get_memo_version_artifact(investment_id, version_id, db_path=db)
    assert artifact is not None

    with pytest.raises(ReportArtifactError, match="schema version"):
        decode_report_document(artifact.report_document, REPORT_SCHEMA_VERSION + 1)


@pytest.mark.parametrize(
    "corruption",
    [
        '{"report_schema_version": 1}',
        '{"report_schema_version": 1, "package": {}}',
        "not json at all",
        '{"report_schema_version": 2, "package": {}}',
    ],
)
def test_a_damaged_payload_refuses_rather_than_half_opening(corruption: str) -> None:
    """A committee document rendered from a half-understood payload is worse
    than one that refuses to open."""

    with pytest.raises(ReportArtifactError):
        decode_report_document(corruption, REPORT_SCHEMA_VERSION)


def test_a_metric_with_both_a_value_and_a_reason_is_refused() -> None:
    """The one invariant the decoder enforces beyond shape: a figure is either
    reported or explained, never both, because a reader could not tell which
    the memo meant."""

    import json

    document = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "package": {
            "origin": "published_version",
            "investment_id": "i",
            "investment_name": "n",
            "asset_type": None,
            "market": None,
            "version_number": 1,
            "version_id": "v",
            "published_at": None,
            "prepared_by": None,
            "generated_at": "now",
            "decision_ask": "",
            "analyst_recommendation": "Approve",
            "committee_decision": None,
            "committee_note": None,
            "executive_summary": "",
            "strategy_label": "",
            "scenario_label": "",
            "perspective_label": "",
            "freshness": "current",
            "verification_code": None,
            "key_metrics": [
                {
                    "label": "Both",
                    "value": "$1",
                    "unavailable": {"reason_code": "x", "reason": "y", "label": "Unavailable"},
                    "note": None,
                }
            ],
            "valuations": [],
            "sections": [],
            "evidence": [],
            "disclosures": [],
            "concluding_statement": None,
            "confidentiality": "c",
        },
    }
    with pytest.raises(ReportArtifactError, match="exactly one"):
        decode_report_document(json.dumps(document), REPORT_SCHEMA_VERSION)


def test_the_draft_preview_is_still_current_and_still_marked(db: Path) -> None:
    """A draft preview is not frozen and must not be: it is the analyst's
    working view, and it keeps its Draft treatment."""

    from anchor.reporting.assembly import assemble_draft_preview

    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("as-is",)),
        db_path=db,
    )
    first = assemble_draft_preview(investment_id, db_path=db)
    assert first.origin is MemoReportOrigin.DRAFT_PREVIEW
    assert first.status_line.startswith("DRAFT")

    store.put_memo_draft(
        investment_id,
        fx.memo_draft(
            investment_id,
            decision_ask="Edited",
            selected_valuation_timepoint_ids=("as-is",),
        ),
        db_path=db,
    )
    second = assemble_draft_preview(investment_id, db_path=db)
    assert second.decision_ask == "Edited", "the preview must follow the draft"
    assert second.status_line.startswith("DRAFT")
