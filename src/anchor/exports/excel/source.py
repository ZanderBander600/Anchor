"""Excel Export 1 -- what a Quick Underwrite audit workbook is built from, and
when a Deal may not be exported.

The workbook represents a *saved, currently analysed* Quick Deal: the stored
inputs, the stored Business Plan and the stored analysis snapshot whose
fingerprint matches them. Nothing here accepts client-supplied results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ...asset_types import ASSET_TYPE_LABELS
from ...business_plan import BusinessPlan
from ...contracts import AcquisitionInputs
from ...deals.store import QuickAnalysisProvenance, QuickAnalysisState
from ...engine.contracts import AcquisitionResults

#: The workbook contract this package writes. Bump it whenever a sheet, a row
#: meaning or a check changes, so an exported file states which contract it
#: follows.
EXPORT_CONTRACT_VERSION = "anchor.excel.quick-formula-audit/1"

#: Largest hold period the workbook lays out. A hold of ``H`` years needs
#: ``12 * H`` monthly debt rows and ``H + 2`` period columns; Anchor's input
#: domain has no upper bound, so the export states its own.
MAX_EXPORT_HOLD_PERIOD = 100


class QuickAuditRefusalCode(Enum):
    """Stable wire tokens for every reason an export is refused."""

    DEAL_NOT_FOUND = "deal_not_found"
    UNSUPPORTED_OPERATING_MODE = "unsupported_operating_mode"
    ANALYSIS_MISSING = "analysis_missing"
    ANALYSIS_STALE = "analysis_stale"
    ANALYSIS_INCONSISTENT = "analysis_inconsistent"
    HOLD_PERIOD_EXCEEDS_EXPORT_LIMIT = "hold_period_exceeds_export_limit"
    EXPORT_GENERATION_FAILED = "export_generation_failed"


class QuickAuditExportError(ValueError):
    """A typed refusal. ``message`` is written for the analyst: it says what to
    do, and never carries a path, an exception or an internal identifier."""

    def __init__(self, code: QuickAuditRefusalCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class QuickAuditSource:
    """Everything one workbook is built from -- all of it read from storage."""

    deal_id: str
    deal_name: str
    asset_type_label: str | None
    asset_subtype: str | None
    inputs: AcquisitionInputs
    business_plan: BusinessPlan
    results: AcquisitionResults
    analysis_fingerprint: str
    generated_at: datetime
    anchor_version: str
    source_commit: str | None


def quick_audit_source(
    provenance: QuickAnalysisProvenance,
    *,
    generated_at: datetime,
    anchor_version: str,
    source_commit: str | None,
) -> QuickAuditSource:
    """Turn a stored Quick Deal into a workbook source, or refuse.

    Missing and stale analyses are refused with their own codes: the workbook
    freezes Anchor's results beside formulas driven by the saved inputs, and a
    snapshot that does not belong to those inputs would make every
    reconciliation row meaningless."""

    deal = provenance.deal
    if provenance.analysis_state is QuickAnalysisState.MISSING:
        raise QuickAuditExportError(
            QuickAuditRefusalCode.ANALYSIS_MISSING,
            "This Deal has no saved analysis. Analyze the saved inputs and save "
            "the Deal, then export again.",
        )
    if provenance.analysis_state is QuickAnalysisState.STALE:
        raise QuickAuditExportError(
            QuickAuditRefusalCode.ANALYSIS_STALE,
            "The saved analysis no longer matches the saved inputs. Analyze the "
            "current inputs and save the Deal, then export again.",
        )
    results = deal.analysis_snapshot
    if deal.inputs is None or not isinstance(results, AcquisitionResults):
        raise QuickAuditExportError(
            QuickAuditRefusalCode.ANALYSIS_INCONSISTENT,
            "The saved analysis could not be read as a Quick Underwrite result. "
            "Analyze and save the Deal again, then export.",
        )
    if deal.inputs.hold_period > MAX_EXPORT_HOLD_PERIOD:
        raise QuickAuditExportError(
            QuickAuditRefusalCode.HOLD_PERIOD_EXCEEDS_EXPORT_LIMIT,
            f"The audit workbook supports hold periods up to {MAX_EXPORT_HOLD_PERIOD} "
            f"years; this Deal's hold period is {deal.inputs.hold_period} years.",
        )

    return QuickAuditSource(
        deal_id=deal.id,
        deal_name=deal.name,
        asset_type_label=(
            ASSET_TYPE_LABELS[deal.asset_type] if deal.asset_type is not None else None
        ),
        asset_subtype=deal.asset_subtype,
        inputs=deal.inputs,
        business_plan=deal.business_plan,
        results=results,
        analysis_fingerprint=provenance.analysis_fingerprint,
        generated_at=generated_at,
        anchor_version=anchor_version,
        source_commit=source_commit,
    )
