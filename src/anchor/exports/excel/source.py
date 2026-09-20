"""Excel Export 1 and 2 -- what an audit workbook is built from, and when a
Deal may not be exported.

A workbook represents a *saved, currently analysed* Deal: the stored inputs,
the stored Business Plan and the stored analysis snapshot whose fingerprint
matches them. Nothing here accepts client-supplied results, recomputes an
authoritative analysis, or resolves a Business Plan.

Quick and Detailed keep their own contract version, their own refusal codes
and their own source type. The codes spell the same wire tokens, deliberately:
each export owns its own published contract, and neither can be changed by
editing the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ...asset_types import ASSET_TYPE_LABELS
from ...business_plan import BusinessPlan
from ...contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from ...deals.store import (
    DetailedAnalysisProvenance,
    QuickAnalysisProvenance,
    QuickAnalysisState,
)
from ...engine.contracts import (
    AcquisitionResults,
    DetailedAcquisitionResults,
    OperatingProjection,
)

#: The workbook contract this package writes. Bump it whenever a sheet, a row
#: meaning or a check changes, so an exported file states which contract it
#: follows.
EXPORT_CONTRACT_VERSION = "anchor.excel.quick-formula-audit/1"

#: Excel Export 2's own contract, versioned independently of Quick's.
DETAILED_EXPORT_CONTRACT_VERSION = "anchor.excel.detailed-formula-audit/1"

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


# =============================================================================
# Excel Export 2 -- Detailed Underwrite
# =============================================================================


class DetailedAuditRefusalCode(Enum):
    """Stable wire tokens for every reason a Detailed export is refused."""

    DEAL_NOT_FOUND = "deal_not_found"
    UNSUPPORTED_OPERATING_MODE = "unsupported_operating_mode"
    ANALYSIS_MISSING = "analysis_missing"
    ANALYSIS_STALE = "analysis_stale"
    ANALYSIS_INCONSISTENT = "analysis_inconsistent"
    HOLD_PERIOD_EXCEEDS_EXPORT_LIMIT = "hold_period_exceeds_export_limit"
    EXPORT_GENERATION_FAILED = "export_generation_failed"


class DetailedAuditExportError(ValueError):
    """A typed refusal. ``message`` is written for the analyst: it says what to
    do, and never carries a path, an exception or an internal identifier."""

    def __init__(self, code: DetailedAuditRefusalCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class DetailedAuditSource:
    """Everything one Detailed workbook is built from -- all of it read from
    storage.

    ``operating_projection`` and ``results`` are the two halves of the saved
    ``DetailedAcquisitionResults``: the Detailed line-item schedule, and the
    unchanged ``AcquisitionResults`` the shared downstream engine produced from
    it. Both are frozen values; neither is recomputed here."""

    deal_id: str
    deal_name: str
    asset_type_label: str | None
    asset_subtype: str | None
    terms: AcquisitionTerms
    detailed_operating_inputs: DetailedOperatingInputs
    business_plan: BusinessPlan
    operating_projection: OperatingProjection
    results: AcquisitionResults
    analysis_fingerprint: str
    generated_at: datetime
    anchor_version: str
    source_commit: str | None


#: Every ``OperatingProjection`` schedule that must run Years 1..H.
_PROJECTION_SERIES = (
    "gross_potential_rent_by_year",
    "other_income_by_year",
    "vacancy_credit_loss_by_year",
    "effective_gross_income_by_year",
    "property_taxes_by_year",
    "insurance_by_year",
    "utilities_by_year",
    "repairs_maintenance_by_year",
    "other_operating_expenses_by_year",
    "management_fee_by_year",
    "total_operating_expenses_by_year",
    "noi_by_year",
)


def detailed_audit_source(
    provenance: DetailedAnalysisProvenance,
    *,
    generated_at: datetime,
    anchor_version: str,
    source_commit: str | None,
) -> DetailedAuditSource:
    """Turn a stored Detailed Deal into a workbook source, or refuse.

    Missing and stale analyses are refused with their own codes: the workbook
    freezes Anchor's results beside formulas driven by the saved inputs, and a
    snapshot that does not belong to those inputs would make every
    reconciliation row meaningless."""

    deal = provenance.deal
    if provenance.analysis_state is QuickAnalysisState.MISSING:
        raise DetailedAuditExportError(
            DetailedAuditRefusalCode.ANALYSIS_MISSING,
            "This Deal has no saved analysis. Analyze the saved inputs and save "
            "the Deal, then export again.",
        )
    if provenance.analysis_state is QuickAnalysisState.STALE:
        raise DetailedAuditExportError(
            DetailedAuditRefusalCode.ANALYSIS_STALE,
            "The saved analysis no longer matches the saved inputs. Analyze the "
            "current inputs and save the Deal, then export again.",
        )
    snapshot = deal.analysis_snapshot
    if (
        deal.terms is None
        or deal.detailed_operating_inputs is None
        or not isinstance(snapshot, DetailedAcquisitionResults)
    ):
        raise DetailedAuditExportError(
            DetailedAuditRefusalCode.ANALYSIS_INCONSISTENT,
            "The saved analysis could not be read as a Detailed Underwrite result. "
            "Analyze and save the Deal again, then export.",
        )
    if deal.terms.hold_period > MAX_EXPORT_HOLD_PERIOD:
        raise DetailedAuditExportError(
            DetailedAuditRefusalCode.HOLD_PERIOD_EXCEEDS_EXPORT_LIMIT,
            f"The audit workbook supports hold periods up to {MAX_EXPORT_HOLD_PERIOD} "
            f"years; this Deal's hold period is {deal.terms.hold_period} years.",
        )

    # The two halves of the saved envelope must describe one analysis. They are
    # written together by one engine call, so a disagreement means the stored
    # snapshot is not what it claims -- never something to paper over by
    # preferring one half.
    projection = snapshot.operating_projection
    results = snapshot.results
    hold = deal.terms.hold_period
    inconsistent = [
        any(len(getattr(projection, name)) != hold for name in _PROJECTION_SERIES),
        projection.noi_by_year != results.noi_by_year,
        projection.exit_noi != results.exit_noi,
        projection.going_in_cap_rate != results.going_in_cap_rate,
    ]
    if any(inconsistent):
        raise DetailedAuditExportError(
            DetailedAuditRefusalCode.ANALYSIS_INCONSISTENT,
            "The saved analysis could not be reconciled with the saved inputs "
            "and Business Plan. Analyze and save the Deal again, then export.",
        )

    return DetailedAuditSource(
        deal_id=deal.id,
        deal_name=deal.name,
        asset_type_label=(
            ASSET_TYPE_LABELS[deal.asset_type] if deal.asset_type is not None else None
        ),
        asset_subtype=deal.asset_subtype,
        terms=deal.terms,
        detailed_operating_inputs=deal.detailed_operating_inputs,
        business_plan=deal.business_plan,
        operating_projection=projection,
        results=results,
        analysis_fingerprint=provenance.analysis_fingerprint,
        generated_at=generated_at,
        anchor_version=anchor_version,
        source_commit=source_commit,
    )
