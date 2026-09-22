"""Phase 7 Gate P7.10 Stage 4 -- the institutional report and the PDF.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 9, 12, 13 and
13.3, and the Stage 4 brief's own Section 9 (PDF authority and reproducibility).

The nine claims the gate must prove are numbered in the section headers below.
Each is measured against the real store, the real engine and the real renderer:
nothing here stubs the thing it is asserting about.
"""

from __future__ import annotations

import dataclasses
import io
from pathlib import Path

import pytest
from pypdf import PdfReader

import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]
from anchor.deals import memo_dependencies as deps
from anchor.deals import store
from anchor.memo.contracts import InvestmentCommitteeDecision, InvestmentCommitteeOutcome
from anchor.reporting.assembly import (
    MemoReportError,
    PdfExportRefusalCode,
    PdfExportRefusedError,
    assemble_draft_preview,
    assemble_version_report,
    assemble_version_report_for_export,
    export_filename,
)
from anchor.reporting.contracts import (
    UNSOURCED_CLAIM_LABEL,
    MemoReportOrigin,
    ReportFreshness,
)
from anchor.reporting.pdf import render_memo_pdf


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


def _pdf_text(document: bytes) -> str:
    reader = PdfReader(io.BytesIO(document))
    return "\n".join(page.extract_text() for page in reader.pages)


# =============================================================================
# 1. A published memo remains unchanged after draft edits
# =============================================================================


def test_draft_edits_never_reach_a_published_version(db: Path) -> None:
    """The whole point of an immutable version (R-H).

    The draft is rewritten wholesale -- a different ask, a different
    recommendation, different narrative -- and the published report is compared
    field by field against what it said before. A report that recomputed its
    content from the draft would fail here, and so would one that re-read the
    draft's evidence."""

    _, investment_id, version_id = _published(db)
    before = assemble_version_report(investment_id, version_id, db_path=db)

    store.put_memo_draft(
        investment_id,
        dataclasses.replace(
            fx.memo_draft(
                investment_id,
                evidence_ids=("ev-1",),
                selected_valuation_timepoint_ids=("as-is",),
                decision_ask="A COMPLETELY DIFFERENT ASK",
            ),
            executive_summary="Rewritten after publication.",
        ),
        db_path=db,
    )

    after = assemble_version_report(investment_id, version_id, db_path=db)
    assert after.decision_ask == before.decision_ask
    assert after.executive_summary == before.executive_summary
    assert after.analyst_recommendation == before.analyst_recommendation
    assert [item.text for item in after.sections[0].narrative] == [
        item.text for item in before.sections[0].narrative
    ]
    assert after.decision_ask != "A COMPLETELY DIFFERENT ASK"

    # And the draft preview does move, so the test is not passing because
    # nothing changed at all.
    preview = assemble_draft_preview(investment_id, db_path=db)
    assert preview.decision_ask == "A COMPLETELY DIFFERENT ASK"


# =============================================================================
# 2. A stale dependency is visible but does not rewrite history
# =============================================================================


def test_a_stale_dependency_is_reported_without_rewriting_the_version(db: Path) -> None:
    """Section 9: reopening a stale version is allowed; presenting it as current
    is not. The frozen valuation keeps the value it froze, the package is marked
    stale and names the classes that moved, and the PDF carries the marking."""

    deal_id, investment_id, version_id = _published(db)
    fresh = assemble_version_report(investment_id, version_id, db_path=db)
    assert fresh.freshness is ReportFreshness.CURRENT
    frozen_values = [view.value for view in fresh.valuations]

    # Move a valuation definition the version recorded.
    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal_id, cap_rate=0.07))

    stale = assemble_version_report(investment_id, version_id, db_path=db)
    assert stale.freshness is ReportFreshness.STALE
    assert stale.is_stale
    assert "Valuation definitions" in stale.stale_classes
    assert "ANALYSIS HAS CHANGED SINCE PUBLICATION" in stale.status_line
    assert stale.status_line.startswith("PUBLISHED")
    assert stale.disclosures != ()

    # History is described, never edited: the frozen figures are untouched.
    assert [view.value for view in stale.valuations] == frozen_values

    text = _pdf_text(render_memo_pdf(stale))
    assert "SUPERSEDED" in text
    assert "ANALYSIS HAS CHANGED SINCE PUBLICATION" in text


# =============================================================================
# 3. An exploratory unavailable valuation does not block publication
# =============================================================================


def test_an_exploratory_unavailable_valuation_never_reaches_the_report(db: Path) -> None:
    """Section 22.6, Correction 1. A definition the memo neither selected nor a
    funding consumed is working state: it publishes fine and is not presented as
    a dependency of the package."""

    deal, investment_id = fx.opted_in_deal(db)
    # A second definition that genuinely cannot resolve: month 72 is a storable
    # hold-year end, but it lies beyond this variant's five-year horizon, so it
    # resolves to a typed unavailable rather than a value. Month 48 would *not*
    # do -- it is the end of Year 4 and resolves perfectly well, which would
    # make this test pass while proving nothing.
    store.create_valuation_timepoint(
        investment_id,
        fx.stabilized_timepoint(deal.id, timepoint_id="exploratory", model_month=72),
        db_path=db,
    )
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("as-is",)),
        db_path=db,
    )

    version = deps.publish(investment_id, db_path=db)
    report = assemble_version_report(investment_id, version.version_id, db_path=db)

    included = {view.label for view in report.valuations}
    assert "As-Is" in included
    # The exploratory definition is not a dependency and is not presented as one.
    assert not any(view.selected and view.label == "Stabilized" for view in report.valuations)


# =============================================================================
# 4. A selected unavailable valuation blocks publication with its own reason
# =============================================================================


def test_a_selected_unavailable_valuation_refuses_publication_with_its_reason(
    db: Path,
) -> None:
    """The other half of Correction 1: selecting a view makes it a dependency,
    and its *own* structured reason is carried on the refusal rather than a
    generic failure."""

    deal, investment_id = fx.opted_in_deal(db)
    # Beyond this variant's five-year horizon: storable, and unresolvable here.
    store.create_valuation_timepoint(
        investment_id,
        fx.stabilized_timepoint(deal.id, timepoint_id="unreachable", model_month=72),
        db_path=db,
    )
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(
            investment_id, selected_valuation_timepoint_ids=("as-is", "unreachable")
        ),
        db_path=db,
    )

    from anchor.memo.publication import PublicationRefusalCode, PublicationRefusedError

    with pytest.raises(PublicationRefusedError) as caught:
        deps.publish(investment_id, db_path=db)

    refusals = caught.value.refusals
    valuation_refusals = [
        refusal
        for refusal in refusals
        if refusal.code is PublicationRefusalCode.VALUATION_UNAVAILABLE_FOR_REQUIRED_VIEW
    ]
    assert valuation_refusals, f"expected a valuation refusal, got {refusals}"
    # The valuation's own reason code travels through, never flattened.
    assert valuation_refusals[0].unavailable_reason is not None
    assert valuation_refusals[0].scope_id == "unreachable"


# =============================================================================
# 5. Claim-level evidence is visible in the workspace package and the report
# =============================================================================


def test_claim_level_evidence_reaches_the_report_and_the_pdf(db: Path) -> None:
    """R-G. The source a *particular* claim rests on is printed against that
    claim, and the register says which claims rest on each source, so the
    relationship is legible in both directions."""

    _, investment_id, version_id = _published(db)
    report = assemble_version_report(investment_id, version_id, db_path=db)

    thesis = next(section for section in report.sections if section.title == "Investment Thesis")
    sourced = thesis.narrative[0]
    assert sourced.sourced is True
    assert "Q3 sales comparables" in sourced.evidence_labels

    entry = next(item for item in report.evidence if item.title == "Q3 sales comparables")
    assert entry.approved is True
    assert entry.cited_by, "the register must say which claims rest on this source"

    text = _pdf_text(render_memo_pdf(report))
    assert "Q3 sales comparables" in text
    assert "Source Register" in text or "Source register" in text


def test_a_claim_with_no_source_is_labelled_an_analyst_assertion(db: Path) -> None:
    """Section 8: an unsupported statement is never silently upgraded to a
    sourced fact. The fixture's condition item cites nothing."""

    _, investment_id, version_id = _published(db)
    report = assemble_version_report(investment_id, version_id, db_path=db)

    conditions = next(
        section for section in report.sections if section.title == "Conditions to Approval"
    )
    assert conditions.narrative[0].sourced is False
    assert conditions.narrative[0].evidence_labels == ()

    assert UNSOURCED_CLAIM_LABEL in _pdf_text(render_memo_pdf(report))


# =============================================================================
# 6. AI functionality is absent
# =============================================================================


def test_stage_4_ships_no_ai_surface(db: Path) -> None:
    """Stage 3 is deferred and unstarted. No report field, section, disclosure or
    rendered word offers, mentions or reserves an AI capability."""

    _, investment_id, version_id = _published(db)
    report = assemble_version_report(investment_id, version_id, db_path=db)
    text = _pdf_text(render_memo_pdf(report)).lower()

    for forbidden in (
        "ai ",
        "generated by",
        "proposal",
        "coming soon",
        "suggested",
    ):
        assert forbidden not in text, f"{forbidden!r} appears in the rendered memo"


# =============================================================================
# 7. No renderer calculation can diverge from Anchor
# =============================================================================


def test_every_report_figure_is_a_string_the_backend_formatted(db: Path) -> None:
    """The structural reason the renderer cannot compute: it is handed finished
    text, not numbers. A metric holds either a formatted string or a typed
    unavailable -- never a float, and never both."""

    _, investment_id, version_id = _published(db)
    report = assemble_version_report(investment_id, version_id, db_path=db)

    metrics = list(report.key_metrics)
    for section in report.sections:
        metrics.extend(section.metrics)
    assert metrics

    for metric in metrics:
        assert (metric.value is None) != (metric.unavailable is None), metric
        if metric.value is not None:
            assert isinstance(metric.value, str)
        else:
            assert metric.unavailable is not None
            assert metric.unavailable.reason_code != ""
            assert metric.unavailable.label not in {"", "0", "$0", "-"}

    for section in report.sections:
        for table in section.tables:
            for row in table.rows:
                for cell in row:
                    assert isinstance(cell, str)


def test_an_unavailable_figure_is_never_zero_or_the_purchase_price(db: Path) -> None:
    """Section 2. The fixture has no debt, so DSCR has no value; it must read as
    unavailable rather than borrowing another number."""

    _, investment_id, version_id = _published(db)
    report = assemble_version_report(investment_id, version_id, db_path=db)

    dscr = next(metric for metric in report.key_metrics if metric.label.startswith("DSCR"))
    assert dscr.value is None
    assert dscr.unavailable is not None
    assert dscr.unavailable.label == "Unavailable"

    purchase = next(metric for metric in report.key_metrics if metric.label == "Purchase Price")
    assert dscr.unavailable.label != purchase.value


# =============================================================================
# 8. A final PDF cannot be generated from a mutable draft
# =============================================================================


def test_a_draft_preview_is_marked_and_cannot_be_exported(db: Path) -> None:
    """Stage 4 §9: no final PDF from a mutable draft.

    Two doors are proved. The package itself is marked ``DRAFT_PREVIEW`` and
    refuses to produce a filename, and the export entry point cannot be reached
    with anything that is not a published version."""

    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("as-is",)),
        db_path=db,
    )

    preview = assemble_draft_preview(investment_id, db_path=db)
    assert preview.origin is MemoReportOrigin.DRAFT_PREVIEW
    assert preview.is_draft
    assert preview.version_number is None
    assert preview.status_line.startswith("DRAFT")
    assert "NOT PUBLISHED" in preview.status_line

    with pytest.raises(PdfExportRefusedError) as caught:
        export_filename(preview)
    assert caught.value.code is PdfExportRefusalCode.DRAFT_NOT_EXPORTABLE

    # The export door refuses a version id that does not exist, with a typed
    # reason rather than a failed download.
    with pytest.raises(PdfExportRefusedError) as missing:
        assemble_version_report_for_export(investment_id, "no-such-version", db_path=db)
    assert missing.value.code is PdfExportRefusalCode.VERSION_NOT_FOUND

    # A rendered draft preview is unmistakable on every page.
    assert "DRAFT" in _pdf_text(render_memo_pdf(preview))


def test_a_published_export_is_reproducible_and_named_for_its_version(db: Path) -> None:
    """Stage 4 §9: repeated export of the same version is semantically
    identical, and the filename carries the Investment and the version."""

    _, investment_id, version_id = _published(db)
    package = assemble_version_report_for_export(investment_id, version_id, db_path=db)

    first = render_memo_pdf(package)
    second = render_memo_pdf(package)
    assert first == second, "the same package must render the same bytes"

    name = export_filename(package)
    assert name.endswith("-investment-memo-v1.pdf")
    assert "/" not in name and "\\" not in name

    text = _pdf_text(first)
    assert "Confidential" in text
    assert "Page 1" in text
    assert "Investment Committee" in text


# =============================================================================
# 9. The two decision acts stay separate, and the report says so
# =============================================================================


def test_the_committee_decision_is_separate_from_the_recommendation(db: Path) -> None:
    """R-F. Before the committee records anything the report says so in words
    that are not a recommendation, and recording an outcome changes the memo's
    content not at all."""

    _, investment_id, version_id = _published(db)
    before = assemble_version_report(investment_id, version_id, db_path=db)
    assert before.committee_decision is None
    assert before.analyst_recommendation == "Approve with Conditions"
    assert "Not yet recorded" in _pdf_text(render_memo_pdf(before))

    store.put_committee_decision(
        investment_id,
        version_id,
        InvestmentCommitteeDecision(
            memo_version_id=version_id,
            decision=InvestmentCommitteeOutcome.DEFERRED,
            decision_note="Revisit after the environmental report.",
            decided_at=None,
        ),
        db_path=db,
    )

    after = assemble_version_report(investment_id, version_id, db_path=db)
    assert after.committee_decision == "Deferred"
    # Deferred is a committee outcome with no analyst counterpart, so the two
    # vocabularies cannot be confused.
    assert after.analyst_recommendation == before.analyst_recommendation
    assert after.decision_ask == before.decision_ask
    assert after.verification_code == before.verification_code

    text = _pdf_text(render_memo_pdf(after))
    assert "Analyst Recommendation" in text
    assert "Investment Committee Decision" in text
    assert "Deferred" in text


# =============================================================================
# Cross-cutting: the draft preview, and a memo with nothing in it
# =============================================================================


def test_a_draft_with_no_selected_cell_previews_rather_than_failing(db: Path) -> None:
    """A memo an analyst has only started is a real state. The preview reports
    the context as not selected and omits the sections it has no data for; it
    does not raise, and it does not manufacture figures."""

    _, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(
        investment_id,
        dataclasses.replace(fx.memo_draft(investment_id), selected_decision=None),
        db_path=db,
    )

    preview = assemble_draft_preview(investment_id, db_path=db)
    assert preview.strategy_label == "Not selected"
    assert preview.scenario_label == "Not selected"
    assert preview.perspective_label == "Not selected"
    assert preview.key_metrics == ()
    assert preview.valuations == ()
    # It still renders, so an analyst can see the shape of what they are writing.
    assert render_memo_pdf(preview)


def test_a_missing_draft_is_a_named_condition_not_a_crash(db: Path) -> None:
    _, investment_id = fx.opted_in_deal(db)
    with pytest.raises(MemoReportError):
        assemble_draft_preview(investment_id, db_path=db)


def test_empty_sections_are_omitted_rather_than_printed_empty(db: Path) -> None:
    """Section 13.2: no empty appendix is generated, and nothing is filled with
    demo copy to avoid one."""

    _, investment_id, version_id = _published(db)
    report = assemble_version_report(investment_id, version_id, db_path=db)

    for section in report.rendered_sections():
        assert not section.is_empty
    titles = {section.title for section in report.sections}
    # The fixture authors no structural protections or dealbreakers.
    assert "Structural Protections" not in titles
    assert "Dealbreakers" not in titles
