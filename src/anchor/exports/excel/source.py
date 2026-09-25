"""Excel Export 1, 2 and 3 -- what an audit workbook is built from, and when a
Deal may not be exported.

For **Quick and Detailed**, a workbook represents a *saved, currently analysed*
Deal: the stored inputs, the stored Business Plan and the stored analysis
snapshot whose fingerprint matches them. Neither accepts client-supplied
results, recomputes an authoritative analysis, or resolves a Business Plan.

**Lease-Level is different, deliberately.** ``lease_level_deals`` has no
``analysis_snapshot`` column -- an accepted design decision, not an oversight --
so there is no stored result to be missing or stale. That export reads the
saved Deal and its typed records in one consistent read and re-runs the
**existing authoritative** entry point over exactly those inputs. It introduces
no second analysis pathway, caches nothing, and writes nothing.

Each mode keeps its own contract version, its own refusal codes and its own
source type. Where the codes spell the same wire tokens they do so
deliberately: each export owns its published contract, and none can be changed
by editing another.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ...analysis.business_plan_analysis import (
    analyze_lease_level_acquisition_with_business_plan,
)
from ...asset_types import ASSET_TYPE_LABELS
from ...business_plan import BusinessPlan
from ...contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from ...deals.store import (
    DetailedAnalysisProvenance,
    LeaseLevelExportProvenance,
    QuickAnalysisProvenance,
    QuickAnalysisState,
)
from ...engine.contracts import (
    AcquisitionResults,
    DetailedAcquisitionResults,
    OperatingProjection,
)
from ...leasing import (
    AnnualOperatingProjection,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseValidationError,
    MarketLeasingAssumptions,
    MonthlyPropertyProjection,
    Suite,
)
from ...leasing.validation import LeaseIssueCode

#: The workbook contract this package writes. Bump it whenever a sheet, a row
#: meaning or a check changes, so an exported file states which contract it
#: follows.
EXPORT_CONTRACT_VERSION = "anchor.excel.quick-formula-audit/1"

#: Excel Export 2's own contract, versioned independently of Quick's.
DETAILED_EXPORT_CONTRACT_VERSION = "anchor.excel.detailed-formula-audit/1"

#: Excel Export 3's own contract, versioned independently of the other two.
LEASE_LEVEL_EXPORT_CONTRACT_VERSION = "anchor.excel.lease-level-formula-audit/1"

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
    #: Refinance V1 Stage 3: whether the Deal's Base Capital Structure configures
    #: a refinance. When it does, the Summary names the acquisition-loan levered
    #: figures as the acquisition-financing reference and points to the
    #: refinance audit workbook. ``False`` -- every Deal without one -- builds
    #: exactly the workbook it always did.
    refinance_configured: bool = False


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
    #: Refinance V1 Stage 3: whether the Deal's Base Capital Structure configures
    #: a refinance. When it does, the Summary names the acquisition-loan levered
    #: figures as the acquisition-financing reference and points to the
    #: refinance audit workbook. ``False`` -- every Deal without one -- builds
    #: exactly the workbook it always did.
    refinance_configured: bool = False


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


# =============================================================================
# Excel Export 3 -- Lease-Level Underwrite
#
# **The one structural difference from Quick and Detailed.** Lease-Level Deals
# deliberately carry no ``analysis_snapshot`` column, so there is no stored
# result for this export to find current, missing or stale. The server reads
# the saved Deal and its typed records in one consistent read and re-runs the
# **existing authoritative** Lease-Level analysis over exactly those inputs;
# that result is the frozen Anchor side of the workbook. Nothing is written,
# no schema changes, and no snapshot is introduced.
#
# The refusal vocabulary therefore has no `analysis_missing` and no
# `analysis_stale`: neither state exists here. It gains two of its own --
# invalid saved inputs, and a forward exit NOI the existing typed Lease-Level
# validation refuses to capitalize.
# =============================================================================


class LeaseLevelAuditRefusalCode(Enum):
    """Stable wire tokens for every reason a Lease-Level export is refused.

    Its own enum, spelling its own contract. Three tokens coincide with
    Quick's and Detailed's because they mean the same thing on the wire; the
    rest are Lease-Level's alone, and neither export can be changed by editing
    another."""

    DEAL_NOT_FOUND = "deal_not_found"
    UNSUPPORTED_OPERATING_MODE = "unsupported_operating_mode"
    #: The saved rent roll does not satisfy the D1-D3 leasing contracts, so no
    #: projection can be built from it.
    LEASE_LEVEL_INPUTS_INVALID = "lease_level_inputs_invalid"
    #: HD-D4-7: a cap-rate terminal valuation requires a positive forward exit
    #: NOI. Reported separately from ordinary input defects because it is a
    #: *modelled outcome* of a valid rent roll, not a malformed input.
    #:
    #: Named for the refusal rather than for the series that causes it, so the
    #: API adapter -- which maps this code to an HTTP status -- never names a
    #: financial series (``tests/test_d5_3_lease_level_api_errors.py``). The
    #: analyst-facing message below still says exactly which figure it is.
    TERMINAL_VALUE_NOT_CAPITALIZABLE = "terminal_value_not_capitalizable"
    #: The Deal is larger than an Excel worksheet can hold.
    EXCEL_CAPACITY_EXCEEDED = "excel_capacity_exceeded"
    EXPORT_GENERATION_FAILED = "export_generation_failed"


class LeaseLevelAuditExportError(ValueError):
    """A typed refusal. ``message`` is written for the analyst: it says what to
    do, and never carries a path, an exception or an internal identifier."""

    def __init__(self, code: LeaseLevelAuditRefusalCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseLevelAuditSource:
    """Everything one Lease-Level workbook is built from.

    The inputs are read from storage. ``monthly``, ``annual`` and ``results``
    are the three parts of the analysis the export re-ran over exactly those
    inputs -- the same objects one engine call produced, never rebuilt or
    re-derived, so the audit trail and the arithmetic cannot diverge."""

    deal_id: str
    deal_name: str
    asset_type_label: str | None
    asset_subtype: str | None
    terms: AcquisitionTerms
    property_inputs: LeaseLevelPropertyInputs
    operating_inputs: LeaseLevelOperatingInputs
    market_leasing: MarketLeasingAssumptions
    suites: tuple[Suite, ...]
    leases: tuple[Lease, ...]
    business_plan: BusinessPlan
    monthly: MonthlyPropertyProjection
    annual: AnnualOperatingProjection
    results: AcquisitionResults
    analysis_fingerprint: str
    generated_at: datetime
    anchor_version: str
    source_commit: str | None
    #: Refinance V1 Stage 3: whether the Deal's Base Capital Structure configures
    #: a refinance. When it does, the Summary names the acquisition-loan levered
    #: figures as the acquisition-financing reference and points to the
    #: refinance audit workbook. ``False`` -- every Deal without one -- builds
    #: exactly the workbook it always did.
    refinance_configured: bool = False


def lease_level_audit_source(
    provenance: LeaseLevelExportProvenance,
    *,
    generated_at: datetime,
    anchor_version: str,
    source_commit: str | None,
) -> LeaseLevelAuditSource:
    """Turn a stored Lease-Level Deal into a workbook source, or refuse.

    The analysis is re-run here rather than read, because Lease-Level stores
    none. It runs through
    ``analyze_lease_level_acquisition_with_business_plan`` -- the same entry
    point the analyze route uses -- so the frozen Anchor side of the workbook
    is produced by the authoritative engine and by nothing else. No second
    analysis pathway is introduced and no result is cached.

    Every leasing-scoped failure arrives as one ``LeaseValidationError``. The
    non-positive forward exit NOI is separated from it by its own issue code,
    because it is the one condition that is a modelled outcome of a *valid*
    rent roll: telling an analyst their inputs are malformed when the building
    simply does not cover its costs would be wrong."""

    deal = provenance.deal
    if (
        deal.terms is None
        or deal.property_inputs is None
        or deal.operating_inputs is None
        or deal.market_leasing is None
        or deal.suites is None
        or deal.leases is None
    ):
        raise LeaseLevelAuditExportError(
            LeaseLevelAuditRefusalCode.LEASE_LEVEL_INPUTS_INVALID,
            "This Deal's saved Lease-Level inputs are incomplete. Open the Deal, "
            "complete the rent roll and save it, then export again.",
        )

    try:
        analysis = analyze_lease_level_acquisition_with_business_plan(
            deal.terms,
            deal.property_inputs,
            deal.suites,
            deal.leases,
            market_leasing=deal.market_leasing,
            operating_inputs=deal.operating_inputs,
            business_plan=deal.business_plan,
        )
    except LeaseValidationError as error:
        if any(
            issue.code is LeaseIssueCode.NON_POSITIVE_FORWARD_EXIT_NOI
            for issue in error.result.errors
        ):
            raise LeaseLevelAuditExportError(
                LeaseLevelAuditRefusalCode.TERMINAL_VALUE_NOT_CAPITALIZABLE,
                "The forward exit NOI is not positive, so the sale cannot be valued "
                "at a cap rate and the workbook has no returns to audit. Review the "
                "rent roll, the leasing assumptions and the operating expenses.",
            ) from None
        raise LeaseLevelAuditExportError(
            LeaseLevelAuditRefusalCode.LEASE_LEVEL_INPUTS_INVALID,
            "This Deal's saved Lease-Level inputs could not be analyzed. Open the "
            "Deal, correct the rent roll and leasing assumptions it reports, and "
            "save it, then export again.",
        ) from None

    return LeaseLevelAuditSource(
        deal_id=deal.id,
        deal_name=deal.name,
        asset_type_label=(
            ASSET_TYPE_LABELS[deal.asset_type] if deal.asset_type is not None else None
        ),
        asset_subtype=deal.asset_subtype,
        terms=deal.terms,
        property_inputs=deal.property_inputs,
        operating_inputs=deal.operating_inputs,
        market_leasing=deal.market_leasing,
        suites=deal.suites,
        leases=deal.leases,
        business_plan=deal.business_plan,
        monthly=analysis.monthly_projection,
        annual=analysis.annual_projection,
        results=analysis.results,
        analysis_fingerprint=provenance.analysis_fingerprint,
        generated_at=generated_at,
        anchor_version=anchor_version,
        source_commit=source_commit,
    )
