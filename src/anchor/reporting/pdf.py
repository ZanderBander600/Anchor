"""Phase 7 Gate P7.10 Stage 4 -- rendering one report package to PDF.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Section 13.3;
that document governs on any discrepancy.

**Formatting only, and structurally so.** This module is handed a
``MemoReportPackage`` and nothing else -- no store, no engine, no analysis
function, no raw result contract. Every figure it receives is already a string,
so it cannot compute one even by accident. Page numbers, table continuation and
column widths are presentation logic, exactly as Section 13.3 permits; financial
arithmetic stays in the backend contracts, which this layer cannot reach.

**Deterministic bytes.** The document is built with ReportLab's ``invariant``
mode, which fixes the document id and creation date, so two exports of the same
package are byte-identical rather than merely semantically identical. The one
field that legitimately differs between exports -- the generation timestamp --
is part of the package, so identical input really does mean identical output.

**A draft and a stale version cannot pass as current.** ``status_line`` is
printed in the masthead, repeated in the footer of every page, and a draft or
stale package additionally carries a diagonal watermark across each page. The
export route refuses a draft before reaching this module; the watermark exists
so a *preview* rendered here is unmistakable too.

**Nothing is invented.** There is no photograph, map, market statistic,
demographic figure, analyst name or narrative conclusion in this file. A section
the package did not fill is not printed, and a figure the package marked
unavailable prints its reason.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .contracts import (
    ANALYST_RECOMMENDATION_LABEL,
    COMMITTEE_DECISION_LABEL,
    COMMITTEE_DECISION_UNRECORDED,
    UNSOURCED_CLAIM_LABEL,
    MemoReportPackage,
    MemoReportSection,
    MemoReportTable,
)

# =============================================================================
# Visual system
#
# The restrained navy/teal palette of the accepted concept. Institutional rather
# than consumer: one accent, generous rules, no gradients, no decorative panels
# that hold nothing.
# =============================================================================

NAVY = colors.HexColor("#1B2A41")
NAVY_LIGHT = colors.HexColor("#33455F")
TEAL = colors.HexColor("#1F6F78")
INK = colors.HexColor("#1D2733")
MUTED = colors.HexColor("#5C6B7A")
RULE = colors.HexColor("#C9D4DF")
PANEL = colors.HexColor("#EEF3F7")
PANEL_EDGE = colors.HexColor("#D8E2EB")
BAND = colors.HexColor("#F6F9FB")
WARNING = colors.HexColor("#8A5A00")
WARNING_PANEL = colors.HexColor("#FBF3E4")

#: Body text never goes below this. Section 13.3: a wide table repeats its
#: headers and is never shrunk below the readable minimum merely to force one
#: page. Where a table is too wide it wraps inside its cells instead.
MIN_BODY_SIZE = 8.0

PAGE_WIDTH, PAGE_HEIGHT = LETTER
MARGIN_X = 0.62 * inch
MARGIN_TOP = 0.95 * inch
MARGIN_BOTTOM = 0.78 * inch
CONTENT_WIDTH = PAGE_WIDTH - (MARGIN_X * 2)


def _style(
    name: str,
    *,
    size: float,
    leading: float,
    font: str = "Helvetica",
    color: colors.Color = INK,
    space_before: float = 0,
    space_after: float = 0,
    alignment: Any = TA_LEFT,
) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName=font,
        fontSize=size,
        leading=leading,
        textColor=color,
        spaceBefore=space_before,
        spaceAfter=space_after,
        alignment=alignment,
    )


DISPLAY = _style("display", size=23, leading=26, font="Times-Bold", color=NAVY)
SUBJECT = _style("subject", size=16, leading=19, font="Times-Roman", color=NAVY_LIGHT)
CLASSIFICATION = _style("classification", size=9.5, leading=12, color=MUTED, space_after=2)
SECTION_TITLE = _style(
    "sectionTitle", size=12.5, leading=15, font="Times-Bold", color=NAVY, space_before=13,
    space_after=3,
)
SECTION_SUBTITLE = _style("sectionSubtitle", size=8.6, leading=11, color=MUTED, space_after=5)
BODY = _style("body", size=9.4, leading=13, space_after=4)
BODY_TIGHT = _style("bodyTight", size=9.4, leading=12.6)
CLAIM = _style("claim", size=9.4, leading=13, color=INK)
CLAIM_DETAIL = _style("claimDetail", size=8.8, leading=12, color=MUTED, space_before=1)
CLAIM_SOURCE = _style("claimSource", size=8.0, leading=10.5, color=TEAL, space_before=1)
CLAIM_UNSOURCED = _style("claimUnsourced", size=8.0, leading=10.5, color=MUTED, space_before=1)
LABEL = _style("label", size=7.4, leading=9.5, color=MUTED)
METRIC_LABEL = _style("metricLabel", size=7.0, leading=9, color=MUTED, alignment=1)
METRIC_VALUE = _style("metricValue", size=12.5, leading=15, font="Times-Bold", color=NAVY, alignment=1)
METRIC_UNAVAILABLE = _style(
    "metricUnavailable", size=8.6, leading=11, font="Helvetica-Oblique", color=MUTED, alignment=1
)
METRIC_NOTE = _style("metricNote", size=6.6, leading=8.4, color=MUTED, alignment=1)
TABLE_HEAD = _style("tableHead", size=8.2, leading=10.4, font="Helvetica-Bold", color=colors.white)
TABLE_HEAD_RIGHT = _style(
    "tableHeadRight", size=8.2, leading=10.4, font="Helvetica-Bold", color=colors.white,
    alignment=TA_RIGHT,
)
TABLE_CELL = _style("tableCell", size=8.4, leading=11)
TABLE_CELL_RIGHT = _style("tableCellRight", size=8.4, leading=11, alignment=TA_RIGHT)
TABLE_CELL_BOLD = _style("tableCellBold", size=8.4, leading=11, font="Helvetica-Bold")
TABLE_CELL_BOLD_RIGHT = _style(
    "tableCellBoldRight", size=8.4, leading=11, font="Helvetica-Bold", alignment=TA_RIGHT
)
TABLE_CAPTION = _style(
    "tableCaption", size=9.2, leading=12, font="Helvetica-Bold", color=NAVY, space_before=7,
    space_after=3,
)
TABLE_NOTE = _style("tableNote", size=7.6, leading=10, color=MUTED, space_before=3)
DISCLOSURE_TITLE = _style(
    "disclosureTitle", size=8.8, leading=11.5, font="Helvetica-Bold", color=WARNING
)
DISCLOSURE_BODY = _style("disclosureBody", size=8.6, leading=11.5, color=INK)
DECISION_LABEL = _style("decisionLabel", size=7.2, leading=9.5, color=MUTED)
DECISION_VALUE = _style("decisionValue", size=13, leading=16, font="Times-Bold", color=NAVY)
SUMMARY_BODY = _style("summaryBody", size=9.6, leading=13.4, color=INK)


def _escape(text: str) -> str:
    """Analyst text as ReportLab paragraph markup.

    ReportLab reads a small XML dialect, so an ampersand or angle bracket in an
    analyst's own sentence would otherwise be read as markup and could break the
    document. Escaping is also the reason no analyst text can inject styling,
    which is the report-side half of "no formula-like user text execution".
    """

    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_escape(text), style)


# =============================================================================
# Page furniture
# =============================================================================


class _MemoDocument(BaseDocTemplate):
    """The page frame: masthead rule, footer, and the draft/stale watermark.

    Every page carries the confidentiality marking, the page number, the
    Investment and the version identity, so a page separated from the document
    still says what it belongs to and whether it is current.
    """

    def __init__(self, buffer: io.BytesIO, package: MemoReportPackage) -> None:
        super().__init__(
            buffer,
            pagesize=LETTER,
            leftMargin=MARGIN_X,
            rightMargin=MARGIN_X,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            title=f"{package.title} -- {package.investment_name}",
            author="Anchor",
            subject=package.decision_ask or package.title,
            invariant=1,
        )
        self.package = package
        frame = Frame(
            MARGIN_X,
            MARGIN_BOTTOM,
            CONTENT_WIDTH,
            PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="body",
        )
        self.addPageTemplates([PageTemplate(id="memo", frames=[frame], onPage=self._decorate)])

    def _decorate(self, canvas, _doc) -> None:  # noqa: ANN001 -- ReportLab callback
        canvas.saveState()
        self._header(canvas)
        self._footer(canvas)
        if self.package.is_draft or self.package.is_stale:
            self._watermark(canvas)
        canvas.restoreState()

    def _header(self, canvas) -> None:  # noqa: ANN001
        top = PAGE_HEIGHT - (MARGIN_TOP * 0.58)
        canvas.setFillColor(NAVY)
        canvas.setFont("Times-Bold", 10.5)
        canvas.drawString(MARGIN_X, top, "ANCHOR")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.2)
        canvas.drawString(MARGIN_X + 46, top + 0.6, "REAL ASSETS. REAL OPPORTUNITIES.")
        canvas.setFont("Helvetica-Bold", 7.2)
        canvas.drawRightString(PAGE_WIDTH - MARGIN_X, top + 0.6, self.package.status_line)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN_X, top - 7, PAGE_WIDTH - MARGIN_X, top - 7)

    def _footer(self, canvas) -> None:  # noqa: ANN001
        base = MARGIN_BOTTOM * 0.52
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN_X, base + 13, PAGE_WIDTH - MARGIN_X, base + 13)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.0)
        canvas.drawString(MARGIN_X, base, self.package.confidentiality)
        canvas.drawCentredString(PAGE_WIDTH / 2, base, self._identity())
        canvas.drawRightString(PAGE_WIDTH - MARGIN_X, base, f"Page {canvas.getPageNumber()}")

    def _identity(self) -> str:
        """The centre footer: what this document is a version of.

        A version number, not a fingerprint: the audit identity belongs in the
        closing appendix, and a hash across every page would be exactly the
        implementation vocabulary Section 2 keeps out of analyst views.
        """

        if self.package.version_number is None:
            return f"{self.package.investment_name} -- Draft"
        return f"{self.package.investment_name} -- Version {self.package.version_number}"

    def _watermark(self, canvas) -> None:  # noqa: ANN001
        """A diagonal marking a reader cannot miss and cannot mistake.

        Drawn under nothing -- it is the last thing painted -- but at low alpha,
        so the page stays readable while being unmistakably not a current
        published memo.
        """

        canvas.saveState()
        canvas.setFillColor(NAVY)
        try:
            canvas.setFillAlpha(0.07)
        except AttributeError:  # pragma: no cover -- older backends
            pass
        canvas.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
        canvas.rotate(38)
        canvas.setFont("Helvetica-Bold", 58)
        canvas.drawCentredString(0, 0, "DRAFT" if self.package.is_draft else "SUPERSEDED")
        canvas.restoreState()


# =============================================================================
# Blocks
# =============================================================================


def _panel(rows: list[list[Any]], widths: list[float], *, fill=PANEL, edge=PANEL_EDGE) -> Table:
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), fill),
                ("BOX", (0, 0), (-1, -1), 0.6, edge),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _masthead(package: MemoReportPackage) -> list[Any]:
    """The first page's identity block.

    Carries the report title, the Investment, its classification where Anchor
    records one, and the two decision acts side by side. No location line: the
    product stores no market or address, and inventing one is exactly what the
    contract forbids.
    """

    identity: list[Any] = [
        _para(package.title, DISPLAY),
        _para(package.investment_name, SUBJECT),
    ]
    if package.asset_type:
        identity.append(_para(package.asset_type, CLASSIFICATION))

    meta_rows: list[list[Any]] = []
    if package.published_at:
        meta_rows.append([_para("Published", LABEL), _para(package.published_at, BODY_TIGHT)])
    if package.version_number is not None:
        meta_rows.append(
            [_para("Version", LABEL), _para(str(package.version_number), BODY_TIGHT)]
        )
    meta_rows.append([_para("Generated", LABEL), _para(package.generated_at, BODY_TIGHT)])
    if package.prepared_by:
        meta_rows.append([_para("Prepared by", LABEL), _para(package.prepared_by, BODY_TIGHT)])

    meta = Table(meta_rows, colWidths=[0.85 * inch, 1.45 * inch], hAlign="RIGHT")
    meta.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
            ]
        )
    )

    head = Table(
        [[identity, meta]], colWidths=[CONTENT_WIDTH * 0.62, CONTENT_WIDTH * 0.38], hAlign="LEFT"
    )
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (0, 0), "TOP"),
                ("VALIGN", (1, 0), (1, 0), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [head, Spacer(1, 10)]


def _decision_block(package: MemoReportPackage) -> list[Any]:
    """The two decision acts, side by side and visibly different (R-F).

    The analyst's recommendation and the committee's decision are separate
    records with separate lifecycles, so they are separate cards with separate
    labels. A committee outcome nobody has recorded reads "Not yet recorded" --
    never "Pending", which is an outcome a committee chose, and never the
    analyst's recommendation echoed back.
    """

    recommendation = _panel(
        [
            [_para(ANALYST_RECOMMENDATION_LABEL, DECISION_LABEL)],
            [_para(package.analyst_recommendation, DECISION_VALUE)],
        ],
        [CONTENT_WIDTH * 0.485],
    )
    committee_text = package.committee_decision or COMMITTEE_DECISION_UNRECORDED
    committee = _panel(
        [
            [_para(COMMITTEE_DECISION_LABEL, DECISION_LABEL)],
            [_para(committee_text, DECISION_VALUE)],
        ],
        [CONTENT_WIDTH * 0.485],
        fill=BAND,
    )
    pair = Table(
        [[recommendation, committee]],
        colWidths=[CONTENT_WIDTH * 0.5, CONTENT_WIDTH * 0.5],
        hAlign="LEFT",
    )
    pair.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    blocks: list[Any] = [pair, Spacer(1, 4)]
    if package.committee_note:
        blocks.append(_para(f"Committee note: {package.committee_note}", CLAIM_DETAIL))
        blocks.append(Spacer(1, 4))
    return blocks


def _context_strip(package: MemoReportPackage) -> list[Any]:
    """The decision context: which cell the recommendation is made from.

    Strategy, Scenario and perspective, named rather than keyed. The selection
    identifies a cell; it changes nothing, and the report says so by presenting
    it as context rather than as a control.
    """

    rows = [
        [
            _para("Strategy", LABEL),
            _para("Scenario", LABEL),
            _para("Decision perspective", LABEL),
        ],
        [
            _para(package.strategy_label, BODY_TIGHT),
            _para(package.scenario_label, BODY_TIGHT),
            _para(package.perspective_label, BODY_TIGHT),
        ],
    ]
    third = CONTENT_WIDTH / 3
    table = Table(rows, colWidths=[third, third, third], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, RULE),
                ("LINEBELOW", (0, -1), (-1, -1), 0.6, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return [table, Spacer(1, 9)]


def _metric_cards(metrics: tuple, columns: int = 5) -> list[Any]:
    """The key figures as aligned cards.

    A card whose figure is unavailable prints the unavailable label in place of
    the number, in the same cell, at the same alignment. It never prints ``$0``,
    never borrows the purchase price and never collapses to an empty card that
    would read as a figure of zero.
    """

    if not metrics:
        return []

    cells: list[list[Any]] = []
    for metric in metrics:
        body: list[Any] = [_para(metric.label, METRIC_LABEL)]
        if metric.is_available:
            body.append(_para(metric.value, METRIC_VALUE))
        else:
            body.append(_para(metric.unavailable.label, METRIC_UNAVAILABLE))
        if metric.note:
            body.append(_para(metric.note, METRIC_NOTE))
        cells.append(body)

    width = CONTENT_WIDTH / columns
    rows: list[list[Any]] = []
    for start in range(0, len(cells), columns):
        chunk = cells[start : start + columns]
        while len(chunk) < columns:
            chunk.append([])
        rows.append(list(chunk))

    table = Table(rows, colWidths=[width] * columns, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), BAND),
                ("BOX", (0, 0), (-1, -1), 0.6, PANEL_EDGE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, PANEL_EDGE),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return [table, Spacer(1, 6)]


def _financial_table(spec: MemoReportTable) -> list[Any]:
    """One financial table, with its header repeated on every page it spans.

    Column widths are proportional to the header count, and every cell is a
    wrapping paragraph, so a long position name wraps inside its column instead
    of pushing the table off the page. Section 13.3's "never shrink below the
    readable minimum" is honoured by wrapping rather than scaling.
    """

    right = set(spec.align_right)
    emphasized = set(spec.emphasize_rows)

    header = [
        _para(text, TABLE_HEAD_RIGHT if index in right else TABLE_HEAD)
        for index, text in enumerate(spec.headers)
    ]
    body: list[list[Any]] = [header]
    for row_index, row in enumerate(spec.rows):
        bold = row_index in emphasized
        body.append(
            [
                _para(
                    cell,
                    (TABLE_CELL_BOLD_RIGHT if bold else TABLE_CELL_RIGHT)
                    if index in right
                    else (TABLE_CELL_BOLD if bold else TABLE_CELL),
                )
                for index, cell in enumerate(row)
            ]
        )

    widths = _column_widths(len(spec.headers), right)
    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("BOX", (0, 0), (-1, -1), 0.6, PANEL_EDGE),
    ]
    for row_index in range(1, len(body)):
        if row_index % 2 == 0:
            style.append(("BACKGROUND", (0, row_index), (-1, row_index), BAND))
    for row_index in emphasized:
        style.append(("BACKGROUND", (0, row_index + 1), (-1, row_index + 1), PANEL))
    table.setStyle(TableStyle(style))

    blocks: list[Any] = [_para(spec.caption, TABLE_CAPTION), table]
    if spec.note:
        blocks.append(_para(spec.note, TABLE_NOTE))
    blocks.append(Spacer(1, 5))
    return blocks


def _column_widths(count: int, right: set[int]) -> list[float]:
    """Wider first column, even figure columns.

    The first column carries names and the figure columns carry formatted
    numbers of similar length, so this gives the label column the slack and
    splits the rest evenly. It is a layout ratio and reads none of the data.
    """

    if count == 1:
        return [CONTENT_WIDTH]
    label_share = 0.34 if count <= 3 else 0.26
    label_width = CONTENT_WIDTH * label_share
    rest = (CONTENT_WIDTH - label_width) / (count - 1)
    return [label_width] + [rest] * (count - 1)


def _narrative_block(item) -> KeepTogether:  # noqa: ANN001 -- MemoReportNarrativeItem
    """One authored claim, its qualifiers, and what it rests on.

    Kept together so a claim never separates from its own sources across a page
    break -- a citation on the following page is a citation a reader may not
    connect. An unsourced claim carries the Section 8 label rather than nothing,
    so "no source attached" is visible rather than merely absent.
    """

    blocks: list[Any] = [_para(f"•  {item.text}", CLAIM)]
    if item.labels:
        blocks.append(_para("  ".join(item.labels), LABEL))
    if item.detail:
        blocks.append(_para(f"Mitigant: {item.detail}", CLAIM_DETAIL))
    if item.sourced:
        blocks.append(_para(f"Source: {'; '.join(item.evidence_labels)}", CLAIM_SOURCE))
    else:
        blocks.append(_para(UNSOURCED_CLAIM_LABEL, CLAIM_UNSOURCED))
    blocks.append(Spacer(1, 4))
    return KeepTogether(blocks)


def _disclosure_block(disclosure) -> KeepTogether:  # noqa: ANN001 -- MemoReportDisclosure
    title = disclosure.title
    if disclosure.scope:
        title = f"{title} ({disclosure.scope})"
    inner = _panel(
        [[_para(title, DISCLOSURE_TITLE)], [_para(disclosure.detail, DISCLOSURE_BODY)]],
        [CONTENT_WIDTH],
        fill=WARNING_PANEL,
        edge=colors.HexColor("#E7D6B4"),
    )
    return KeepTogether([inner, Spacer(1, 5)])


def _section_blocks(section: MemoReportSection) -> list[Any]:
    blocks: list[Any] = [_para(section.title, SECTION_TITLE)]
    if section.subtitle:
        blocks.append(_para(section.subtitle, SECTION_SUBTITLE))
    if section.body:
        blocks.append(_para(section.body, BODY))
    for item in section.narrative:
        blocks.append(_narrative_block(item))
    if section.metrics:
        blocks.extend(_metric_cards(section.metrics, columns=3))
    for spec in section.tables:
        blocks.extend(_financial_table(spec))
    for disclosure in section.disclosures:
        blocks.append(_disclosure_block(disclosure))
    return blocks


def _valuation_table(package: MemoReportPackage) -> list[Any]:
    """The valuation views the package includes.

    Each row says what the view is, when it is struck, its scope, and why it is
    in this memo -- Included, Consumed by funding, or System-derived. An
    unavailable view prints its reason in the value column, because a reader
    scanning that column must never find a blank where a value would be.
    """

    if not package.valuations:
        return []

    rows: list[tuple[str, ...]] = []
    for view in package.valuations:
        if view.system_controlled:
            basis = "System-derived (Exit)"
        elif view.selected and view.consumed:
            basis = "Included; consumed by funding"
        elif view.consumed:
            basis = "Consumed by funding"
        elif view.selected:
            basis = "Included in this memo"
        else:
            basis = "Reference only"
        value = view.value if view.value is not None else _unavailable_text(view)
        label = f"{view.label} (Analyst-Supplied Value)" if view.analyst_supplied else view.label
        rows.append((label, view.kind, view.timing, view.scope, basis, value))

    return _financial_table(
        MemoReportTable(
            caption="Views included in this memo",
            headers=("View", "Basis", "Timing", "Scope", "Role in this memo", "Value"),
            rows=tuple(rows),
            align_right=(5,),
            note=(
                "Exit is the system-derived terminal value of the selected analysis and is not an "
                "editable valuation. As-Is, Stabilized and Custom views are reporting values; only "
                "a view a PctOfValue funding consumes affects the capital structure."
            ),
        )
    )


def _unavailable_text(view) -> str:  # noqa: ANN001 -- MemoReportValuation
    if view.unavailable is None:
        return "Unavailable"
    return f"{view.unavailable.label} -- {view.unavailable.reason}"


def _evidence_table(package: MemoReportPackage) -> list[Any]:
    """The source register, with what each source supports.

    Approval is its own column. A reader can see that a source is attached, that
    the analyst has or has not approved it, and which claims rest on it -- three
    separate facts the contract requires to stay separate.
    """

    if not package.evidence:
        return []
    rows = tuple(
        (
            entry.title,
            entry.source_kind,
            entry.reference,
            entry.as_of_date or "Not stated",
            "Approved" if entry.approved else "Not approved",
            "; ".join(entry.cited_by) if entry.cited_by else "Register only",
        )
        for entry in package.evidence
    )
    return _financial_table(
        MemoReportTable(
            caption="Source Register",
            headers=("Source", "Kind", "Reference", "As of", "Approval", "Supports"),
            rows=rows,
            note=(
                "Approval is the analyst's own. Anchor does not verify a source, and attaching "
                "one does not make a claim an Anchor conclusion."
            ),
        )
    )


def _version_appendix(package: MemoReportPackage) -> list[Any]:
    """The closing audit block: what this version is, and whether it is current.

    The only place a fingerprint appears, labelled as a verification code and
    printed for a committee reader who needs to confirm they are reading the
    same package somebody else read.
    """

    if package.version_number is None:
        return []

    rows: list[tuple[str, ...]] = [
        ("Version", str(package.version_number)),
        ("Published", package.published_at or "Not recorded"),
        ("Status", package.status_line),
        ("Report generated", package.generated_at),
    ]
    if package.stale_classes:
        rows.append(("Changed since publication", "; ".join(package.stale_classes)))
    if package.verification_code:
        rows.append(("Verification code", package.verification_code))

    return _financial_table(
        MemoReportTable(
            caption="Version and Dependencies",
            headers=("Field", "Value"),
            rows=tuple(rows),
            note=(
                "A published version is immutable. Where the analysis has moved since "
                "publication, this package reports the change and leaves the published version "
                "exactly as it was."
            ),
        )
    )


# =============================================================================
# The renderer
# =============================================================================


def render_memo_pdf(package: MemoReportPackage) -> bytes:
    """One report package as PDF bytes.

    The only input is the package, so every figure printed was selected and
    formatted by ``assembly`` from an accepted backend contract. Rendering the
    same package twice produces the same bytes.

    A draft package renders -- the workspace previews one -- and is watermarked
    and labelled on every page. The authority to turn a package into a *final*
    exported file belongs to the route, which refuses a draft before it reaches
    this function.
    """

    buffer = io.BytesIO()
    document = _MemoDocument(buffer, package)

    story: list[Any] = []
    story.extend(_masthead(package))
    story.extend(_decision_block(package))
    story.extend(_context_strip(package))

    if package.decision_ask:
        story.append(_para("Decision Requested", SECTION_TITLE))
        story.append(_para(package.decision_ask, SUMMARY_BODY))

    if package.executive_summary:
        story.append(_para("Executive Summary", SECTION_TITLE))
        story.append(
            _panel([[_para(package.executive_summary, SUMMARY_BODY)]], [CONTENT_WIDTH])
        )
        story.append(Spacer(1, 6))

    if package.key_metrics:
        story.append(_para("Key Decision Metrics", SECTION_TITLE))
        story.extend(_metric_cards(package.key_metrics))

    for disclosure in package.disclosures:
        story.append(_disclosure_block(disclosure))

    for section in package.rendered_sections():
        story.extend(_section_blocks(section))

    valuation_blocks = _valuation_table(package)
    if valuation_blocks:
        story.append(_para("Valuation Views", SECTION_TITLE))
        story.extend(valuation_blocks)

    evidence_blocks = _evidence_table(package)
    if evidence_blocks:
        story.append(_para("Evidence and Sources", SECTION_TITLE))
        story.extend(evidence_blocks)

    if package.concluding_statement:
        story.append(_para("Recommendation", SECTION_TITLE))
        story.append(
            _panel([[_para(package.concluding_statement, SUMMARY_BODY)]], [CONTENT_WIDTH])
        )

    appendix = _version_appendix(package)
    if appendix:
        story.append(PageBreak())
        story.append(_para("Version Record", SECTION_TITLE))
        story.extend(appendix)

    document.build(story)
    return buffer.getvalue()
