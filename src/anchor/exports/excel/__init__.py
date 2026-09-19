"""Excel Export 1 -- the Quick Underwrite formula-audit workbook.

Public surface: build a workbook from a stored, currently analysed Quick
Deal, name its download, and refuse with a typed reason otherwise. See
``docs/architecture/EXCEL_EXPORT_1_QUICK_FORMULA_AUDIT.md``.
"""

from __future__ import annotations

from .filenames import content_disposition, quick_audit_filename, sanitize_deal_name
from .quick_audit import SHEET_ORDER, build_quick_audit_workbook
from .source import (
    EXPORT_CONTRACT_VERSION,
    MAX_EXPORT_HOLD_PERIOD,
    QuickAuditExportError,
    QuickAuditRefusalCode,
    QuickAuditSource,
    quick_audit_source,
)

#: The ``.xlsx`` media type.
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

__all__ = [
    "EXPORT_CONTRACT_VERSION",
    "MAX_EXPORT_HOLD_PERIOD",
    "SHEET_ORDER",
    "XLSX_MEDIA_TYPE",
    "QuickAuditExportError",
    "QuickAuditRefusalCode",
    "QuickAuditSource",
    "build_quick_audit_workbook",
    "content_disposition",
    "quick_audit_filename",
    "quick_audit_source",
    "sanitize_deal_name",
]
