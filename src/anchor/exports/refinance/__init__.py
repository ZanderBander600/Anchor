"""Refinance & Capital Events V1 Stage 3 -- the separate Refinance & Capital
Structure Audit workbook (contract Section 25.1).

A package of its own, beside Excel Exports 1-3 rather than inside them: those
three audit a Deal's acquisition analysis and model nothing of the Capital
Structure, and their package, routes and outputs stay exactly as accepted. This
workbook reuses their presentation and reconciliation vocabulary through
``anchor.exports.excel._workbook``. No production module other than the API
route imports it, so no workbook formula can feed an application result.
"""

from __future__ import annotations

from ..excel.filenames import sanitize_deal_name

REFINANCE_AUDIT_SUFFIX = " - Refinance & Capital Structure Audit.xlsx"


def refinance_audit_filename(investment_name: str) -> str:
    """``<Name> - Refinance & Capital Structure Audit.xlsx``, sanitized exactly
    as Exports 1-3 sanitize a Deal name."""

    return sanitize_deal_name(investment_name) + REFINANCE_AUDIT_SUFFIX


__all__ = ["REFINANCE_AUDIT_SUFFIX", "refinance_audit_filename"]
