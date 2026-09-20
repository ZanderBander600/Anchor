"""Excel Export 1, 2 and 3 -- the formula-audit workbooks.

Public surface: build a workbook from a stored, currently analysed Quick,
Detailed or Lease-Level Deal, name its download, and refuse with a typed reason otherwise.
See ``docs/architecture/EXCEL_EXPORT_1_QUICK_FORMULA_AUDIT.md`` and
``docs/architecture/EXCEL_EXPORT_2_DETAILED_FORMULA_AUDIT.md`` and
``docs/architecture/EXCEL_EXPORT_3_LEASE_LEVEL_FORMULA_AUDIT.md``.
"""

from __future__ import annotations

from ._workbook import SHEET_ORDER
from .detailed_audit import build_detailed_audit_workbook
from .lease_level_audit import (
    LEASE_LEVEL_SHEETS,
    build_lease_level_audit_workbook,
    plan_lease_level_workbook,
)
from .filenames import (
    content_disposition,
    detailed_audit_filename,
    lease_level_audit_filename,
    quick_audit_filename,
    sanitize_deal_name,
)
from .quick_audit import build_quick_audit_workbook
from .source import (
    DETAILED_EXPORT_CONTRACT_VERSION,
    EXPORT_CONTRACT_VERSION,
    LEASE_LEVEL_EXPORT_CONTRACT_VERSION,
    MAX_EXPORT_HOLD_PERIOD,
    DetailedAuditExportError,
    DetailedAuditRefusalCode,
    DetailedAuditSource,
    LeaseLevelAuditExportError,
    LeaseLevelAuditRefusalCode,
    LeaseLevelAuditSource,
    QuickAuditExportError,
    QuickAuditRefusalCode,
    QuickAuditSource,
    detailed_audit_source,
    lease_level_audit_source,
    quick_audit_source,
)

#: The ``.xlsx`` media type.
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

__all__ = [
    "DETAILED_EXPORT_CONTRACT_VERSION",
    "EXPORT_CONTRACT_VERSION",
    "LEASE_LEVEL_EXPORT_CONTRACT_VERSION",
    "LEASE_LEVEL_SHEETS",
    "MAX_EXPORT_HOLD_PERIOD",
    "SHEET_ORDER",
    "XLSX_MEDIA_TYPE",
    "DetailedAuditExportError",
    "DetailedAuditRefusalCode",
    "DetailedAuditSource",
    "LeaseLevelAuditExportError",
    "LeaseLevelAuditRefusalCode",
    "LeaseLevelAuditSource",
    "QuickAuditExportError",
    "QuickAuditRefusalCode",
    "QuickAuditSource",
    "build_detailed_audit_workbook",
    "build_lease_level_audit_workbook",
    "build_quick_audit_workbook",
    "content_disposition",
    "detailed_audit_filename",
    "detailed_audit_source",
    "lease_level_audit_filename",
    "lease_level_audit_source",
    "plan_lease_level_workbook",
    "quick_audit_filename",
    "quick_audit_source",
    "sanitize_deal_name",
]
