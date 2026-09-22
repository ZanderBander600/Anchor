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
from anchor.memo.contracts import (
    DecisionPerspectiveKind,
    InvestmentCommitteeDecision,
    InvestmentCommitteeOutcome,
    SelectedDecision,
)
from anchor.reporting.assembly import (
    MemoReportError,
    PdfExportRefusalCode,
    PdfExportRefusedError,
    assemble_draft_preview,
    export_filename,
    read_version_pdf,
    read_version_report,
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


def _frozen(investment_id: str, version_id: str, db: Path):
    """The frozen report one version was issued as.

    Every published assertion below reads the stored artifact rather than a
    fresh assembly, which is the point of Correction 1: what a test sees is
    what the committee was issued."""

    package = read_version_report(investment_id, version_id, db_path=db)
    assert package is not None, "the published version has no stored report"
    return package


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
    before = _frozen(investment_id, version_id, db)

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

    after = _frozen(investment_id, version_id, db)
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


def test_a_stale_dependency_leaves_the_published_report_untouched(db: Path) -> None:
    """Section 9, as Correction 1 settles it.

    Moving a valuation definition after publication changes the *current*
    analysis and nothing about the issued document. The full immutability
    matrix -- every dependency class, the stored bytes, repeated downloads --
    is `tests/test_p7_10_stage_4_immutability.py`; this keeps the claim beside
    the rest of the report's behaviour."""

    deal_id, investment_id, version_id = _published(db)
    fresh = _frozen(investment_id, version_id, db)
    assert fresh.freshness is ReportFreshness.CURRENT
    frozen_values = [view.value for view in fresh.valuations]
    frozen_pdf, _ = read_version_pdf(investment_id, version_id, db_path=db)

    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal_id, cap_rate=0.07))

    after = _frozen(investment_id, version_id, db)
    assert after == fresh
    assert [view.value for view in after.valuations] == frozen_values
    assert read_version_pdf(investment_id, version_id, db_path=db)[0] == frozen_pdf

    # The document is never marked stale: it says what it said when issued.
    assert after.status_line == "PUBLISHED"
    assert "SUPERSEDED" not in _pdf_text(frozen_pdf)


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
    report = _frozen(investment_id, version.version_id, db)

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
    report = _frozen(investment_id, version_id, db)

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
    report = _frozen(investment_id, version_id, db)

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
    report = _frozen(investment_id, version_id, db)
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
    report = _frozen(investment_id, version_id, db)

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
    report = _frozen(investment_id, version_id, db)

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
        read_version_pdf(investment_id, "no-such-version", db_path=db)
    assert missing.value.code is PdfExportRefusalCode.VERSION_NOT_FOUND

    # A rendered draft preview is unmistakable on every page.
    assert "DRAFT" in _pdf_text(render_memo_pdf(preview))


def test_a_published_export_is_reproducible_and_named_for_its_version(db: Path) -> None:
    """Stage 4 §9: repeated export of the same version is semantically
    identical, and the filename carries the Investment and the version."""

    _, investment_id, version_id = _published(db)

    first, name = read_version_pdf(investment_id, version_id, db_path=db)
    second, _ = read_version_pdf(investment_id, version_id, db_path=db)
    assert first == second, "the same version must return the same stored bytes"

    assert name.endswith("-investment-memo-v1.pdf")
    assert "/" not in name and "\\" not in name

    text = _pdf_text(first)
    assert "Confidential" in text
    assert "Page 1" in text
    assert "Investment Committee" in text


# =============================================================================
# 9. The two decision acts stay separate, and the report says so
# =============================================================================


def test_the_committee_decision_is_separate_and_outside_the_frozen_report(
    db: Path,
) -> None:
    """R-F, and what Correction 1 makes of it.

    The committee decides **after** publication, so its outcome is not one of
    the facts frozen when the version was issued -- and the issued document
    therefore never carries one. That is the same reasoning Section 10 already
    applies to the published-version fingerprint: recording an outcome must not
    alter the identity of what was decided on, and it must not alter the
    document either.

    The decision is a real, stored record; the workspace shows it beside the
    frozen report, and the Stage 2 route remains its authority."""

    _, investment_id, version_id = _published(db)
    before = _frozen(investment_id, version_id, db)
    pdf_before, _ = read_version_pdf(investment_id, version_id, db_path=db)

    assert before.analyst_recommendation == "Approve with Conditions"
    assert before.committee_decision is None
    assert "Not yet recorded" in _pdf_text(pdf_before)

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

    # The stored record exists and is readable.
    recorded = store.get_committee_decision(investment_id, version_id, db_path=db)
    assert recorded is not None
    assert recorded.decision is InvestmentCommitteeOutcome.DEFERRED

    # And the issued document is untouched by it, bytes included.
    after = _frozen(investment_id, version_id, db)
    assert after == before
    assert read_version_pdf(investment_id, version_id, db_path=db)[0] == pdf_before

    # The two vocabularies still cannot be confused: `Deferred` is a committee
    # outcome with no analyst counterpart.
    text = _pdf_text(pdf_before)
    assert "Analyst Recommendation" in text
    assert "Investment Committee Decision" in text


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
    report = _frozen(investment_id, version_id, db)

    for section in report.rendered_sections():
        assert not section.is_empty
    titles = {section.title for section in report.sections}
    # The fixture authors no structural protections or dealbreakers.
    assert "Structural Protections" not in titles
    assert "Dealbreakers" not in titles


# =============================================================================
# The purchase price is the analyst's stored price, never a closing total
# =============================================================================


def test_the_purchase_price_metric_is_the_stored_acquisition_price(db: Path) -> None:
    """Section 2, from the other direction.

    The rule that an unavailable figure must never render as the purchase price
    has a twin: a figure that is *not* the purchase price must never render
    under that name. A standalone Deal's ``AcquisitionResults`` carries no
    ``transaction_price``, and the first implementation fell back to
    ``total_closing_uses`` -- which includes acquisition costs, financing fees
    and closing project capital, and is a different number wearing the wrong
    label.

    The fixture is built so the two genuinely differ: without transaction costs
    they coincide, and the test would pass while proving nothing."""

    deal = fx.create_deal(db, name="Priced deal")
    # Give the Deal real transaction costs, so total closing uses is strictly
    # greater than the price the analyst agreed.
    priced = dataclasses.replace(fx.QUICK_INPUTS, ltv=0.6)
    store.update_deal(deal.id, name=deal.name, inputs=priced, db_path=db)
    investment_id, _ = store.create_deal_valuation_timepoint(
        deal.id, fx.as_is_timepoint(deal.id), db_path=db
    )
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("as-is",)),
        db_path=db,
    )
    version = deps.publish(investment_id, db_path=db)
    report = _frozen(investment_id, version.version_id, db)

    price = next(metric for metric in report.key_metrics if metric.label == "Purchase Price")
    assert price.value == "$10,000,000", price
    # And it is the *stored* price rather than whatever the closing totals came
    # to: the Sources & Uses table reports those separately, under their names.
    capital = next(
        section for section in report.sections if section.title == "Capital Structure"
    )
    uses = next(table for table in capital.tables if table.caption.startswith("Sources"))
    totals = {row[0]: row[1] for row in uses.rows}
    assert totals["Total Uses"] != price.value or totals["Loan Amount"] != price.value


def test_an_unreadable_purchase_price_is_unavailable_rather_than_substituted(
    db: Path,
) -> None:
    """Where no stored price can be read, the metric says so. Nothing borrows a
    closing total, an exit value or a valuation to fill the space."""

    import anchor.reporting.assembly as module

    metric = module._metric("Purchase Price", None)
    assert metric.value is None
    assert metric.unavailable is not None
    assert metric.unavailable.label == "Unavailable"


# =============================================================================
# 8. What cross-mode browser QA found (Correction 4)
# =============================================================================


def _disclosures(package) -> tuple:
    """Every disclosure in the package, which the assembly groups into its own
    section rather than hanging off the package."""

    for section in package.sections:
        if section.title == "Disclosures":
            return section.disclosures
    return ()


def _partnership_memo(db: Path) -> tuple[str, str]:
    """A Deal with a real Partnership, and a memo written from the LP's seat."""

    import _p7_9_fixtures as pfx  # type: ignore[import-not-found]

    deal, investment_id = fx.opted_in_deal(db)
    store.set_base_partnership(investment_id, pfx.f1_terms(), db_path=db)
    fx.with_approved_evidence(db, investment_id, evidence_id="ev-1", approved=True)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(
            investment_id,
            selected=SelectedDecision(
                strategy_id=fx.BASE,
                scenario_id=fx.BASE_SCENARIO,
                perspective=DecisionPerspectiveKind.PARTNER,
                position_id=None,
                partner_id="lp",
            ),
            evidence_ids=("ev-1",),
            selected_valuation_timepoint_ids=("as-is",),
        ),
        db_path=db,
    )
    return deal.id, investment_id


def test_a_partner_memo_reports_that_partner_s_returns(db: Path) -> None:
    """Found by cross-mode browser QA at the independent review.

    Every Partner-perspective memo reported **no** partner returns, beneath a
    disclosure saying the Investment resolved no Partnership -- on an Investment
    that plainly had one. Two silent faults pointed the same way: the
    Partnership was read from the structured capital result, which carries no
    such field, and the partner totals were named by fields the P7.9 contract
    does not define. Backend tests passed throughout, because the disclosure
    they asserted was exactly the wrong one that always fired."""

    _, investment_id = _partnership_memo(db)
    package = assemble_draft_preview(investment_id, db_path=db)

    returns = next(section for section in package.sections if section.title == "Returns")
    labels = {metric.label: metric for metric in returns.metrics}
    assert set(labels) == {
        "Capital Contributed",
        "Partner IRR",
        "Partner Multiple",
        "Total Distributions",
        "Profit",
    }, labels
    # Real figures, not an empty section and not zeros.
    for metric in returns.metrics:
        assert metric.unavailable is None, metric
        assert metric.value not in ("", "$0", "0.00%"), metric

    # And the "no Partnership" disclosure is gone, because there is one.
    titles = [disclosure.title for disclosure in _disclosures(package)]
    assert "Partnership" not in titles, titles

    # The cover names the partner the way its Partnership does.
    assert package.perspective_label == "Partner – LP", package.perspective_label


def test_an_investment_with_no_partnership_still_discloses_the_absence(db: Path) -> None:
    """The disclosure was wrong, not unwanted. It must still appear where it is
    true -- otherwise the fix would have traded a false statement for silence."""

    _, investment_id, _ = _published(db)
    package = assemble_draft_preview(investment_id, db_path=db)

    partnership = [d for d in _disclosures(package) if d.title == "Partnership"]
    assert len(partnership) == 1, _disclosures(package)
    assert "absence, not a zero" in partnership[0].detail


def test_no_disclosure_repeats_a_backend_sentence_about_a_record(db: Path) -> None:
    """Also found by browser QA: the "did not resolve" disclosure rendered the
    raising layer's own message, which named an Investment by its 32-character
    id -- inside the published report and its PDF."""

    import re

    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="ev-1", approved=True)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(
            investment_id,
            selected=SelectedDecision(
                strategy_id="a-strategy-that-is-gone",
                scenario_id=fx.BASE_SCENARIO,
                perspective=DecisionPerspectiveKind.PROJECT,
                position_id=None,
                partner_id=None,
            ),
            evidence_ids=("ev-1",),
        ),
        db_path=db,
    )
    package = assemble_draft_preview(investment_id, db_path=db)

    unresolved = [
        d for d in _disclosures(package) if d.title == "Selected analysis did not resolve"
    ]
    assert len(unresolved) == 1, _disclosures(package)
    detail = unresolved[0].detail
    assert investment_id not in detail, detail
    assert deal.id not in detail, detail
    assert not re.search(r"\b[0-9a-f]{12,}\b", detail), detail
    assert not re.search(r"'[^']{4,}'", detail), detail
