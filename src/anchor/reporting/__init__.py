"""Phase 7 Gate P7.10 Stage 4 -- the institutional Investment Committee report.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Section 13
under the ratified P7 authority; that document governs on any discrepancy.

**Presentation only.** Nothing in this package calculates a financial value.
``contracts`` holds the assembled report's shapes, ``assembly`` selects already
-computed backend figures into them, and ``pdf`` renders them. Every amount,
rate, return, valuation and availability state arrives from an accepted engine,
persistence or Stage 2 contract; this package selects, labels, orders and
formats, and does nothing else.

**Stage 4 ships no AI.** There is no proposal, prompt, grounding package or
narrative generator here, and no module in this package imports ``anchor.ai``.
Stage 3 remains deferred and unstarted; a later explicitly authorized Stage 3
may add proposals to the memo draft without changing this package's authority.
"""

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
    ReportUnavailable,
)
from .artifact import (
    REPORT_SCHEMA_VERSION,
    REPORT_SNAPSHOT_NOT_AVAILABLE_MESSAGE,
    MemoReportArtifact,
    ReportArtifactError,
    ReportArtifactUnavailableReason,
)
from .assembly import (
    MemoReportError,
    PdfExportRefusalCode,
    PdfExportRefusedError,
    assemble_draft_preview,
    build_version_package,
    export_filename,
    read_version_pdf,
    read_version_report,
)
from .pdf import render_memo_pdf

__all__ = [
    "MemoReportArtifact",
    "MemoReportDisclosure",
    "MemoReportError",
    "MemoReportEvidenceEntry",
    "MemoReportMetric",
    "MemoReportNarrativeItem",
    "MemoReportOrigin",
    "MemoReportPackage",
    "MemoReportSection",
    "MemoReportTable",
    "MemoReportValuation",
    "PdfExportRefusalCode",
    "PdfExportRefusedError",
    "REPORT_SCHEMA_VERSION",
    "REPORT_SNAPSHOT_NOT_AVAILABLE_MESSAGE",
    "ReportArtifactError",
    "ReportArtifactUnavailableReason",
    "ReportUnavailable",
    "assemble_draft_preview",
    "build_version_package",
    "export_filename",
    "read_version_pdf",
    "read_version_report",
    "render_memo_pdf",
]
