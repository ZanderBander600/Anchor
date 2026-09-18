"""Minimal FastAPI adapter: HTTP request -> engine -> JSON response.

This module is a thin adapter layer, mirroring the role ``cli.py`` plays for
the terminal. It calls ``validate_acquisition_inputs`` and
``analyze_acquisition`` -- the existing, frozen Phase 2/Phase 4 functions --
and never reproduces or reimplements any financial formula or validation
rule itself. The Phase 7 sensitivity endpoints below follow the identical
pattern, delegating all sensitivity computation to
``anchor.analysis.sensitivity`` -- this module does no financial math or
sensitivity math of its own.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import date
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from io import BytesIO
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import TypeAdapter
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .ai import (
    AIAnalysis,
    AIConfigurationError,
    AIProviderError,
    generate_ai_analysis,
    generate_detailed_ai_analysis,
    generate_lease_level_ai_analysis,
)
from .analysis import (
    InvalidBreakEvenTargetError,
    LeaseLevelAcquisitionResults,
    LeaseValidationError,
    OneWaySensitivityResult,
    ParsedLeaseLevelInputs,
    SensitivityTargetShadowedBySuiteOverrideError,
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
    parse_lease_level_inputs,
    run_detailed_one_way_sensitivity,
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
    run_one_way_sensitivity,
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
    StandardDetailedBreakEvenAnalysis,
    StandardDetailedSensitivityPresets,
    StandardSensitivityPresets,
    TwoWaySensitivityResult,
    UnknownAssumptionError,
    UnknownMetricError,
    build_standard_break_even_analysis,
    build_standard_detailed_break_even_analysis,
    build_standard_detailed_presets,
    build_standard_presets,
    run_detailed_two_way_sensitivity,
    run_two_way_sensitivity,
)
from .business_plan import BusinessPlan, BusinessPlanValidationError, parse_business_plan

# Gate AM1. ``analyze_asset_performance`` is the sole authority for every AM1
# financial result; this module serializes what it returns and computes nothing
# of its own. No AI module is reachable from any AM1 route.
from .asset_management import (
    MONETARY_FIELDS as AM1_MONETARY_FIELDS,
    AssetReportValidationError,
    BudgetImmutableError,
    ManagedAssetExistsError,
    ManagedAssetNotFoundError,
    MonthlyReportExistsError,
    MonthlyReportNotFoundError,
    OperatingFigures,
    analyze_asset_performance,
    normalize_reporting_month,
    parse_iso_date,
)
from .contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
    UnsupportedOperatingModeError,
)
from .analysis.scenario import (
    SCENARIO_TARGET_REGISTRY,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    ScenarioValidationError,
)
from .analysis.strategy import (
    STRATEGY_DOMAIN_FIELDS,
    STRATEGY_OUTCOME_TARGETS,
    AcquisitionChoice,
    DispositionChoice,
    FinancingChoice,
    InvestmentStrategyOverlay,
    NoPartnership,
    OperatingOutcome,
    OperatingOutcomeSet,
    StrategyDomain,
    StrategyOverlay,
    StrategyValidationError,
)
from .capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    CapitalStructureValidationError,
    DebtTerms,
    FixedAmount,
    FundingEvent,
    HoldYearPeriod,
    ModelMonthPeriod,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    PositionFee,
    PositionScope,
    PreferredEquityTerms,
    ScopeKind,
    ShortfallResolution,
    TimingBasis,
    UnsupportedCapitalPositionError,
)
from .capital_structure.contracts import AccrualConvention as PreferredAccrualConvention
from .capital_structure.execution_contracts import (
    CapitalStructureExecutionError,
    ExecutionIssueCode,
)
from .deals.capital_structure_codec import FundingAmountRuleKind, PositionTermsKind
from .deals.partnership_codec import HurdleConditionKind
from .deals.partnership_variants import (
    analyze_partnership_variant,
    partner_perspectives,
    partnership_variant_fingerprint,
)
from .deals.position_identity import PositionIdentityConflictError
from .partnership import (
    BenchmarkShare,
    CatchUpRecipient,
    CatchUpRecipientKind,
    CatchUpTerms,
    ContributionRule,
    EconomicAccount,
    ExplicitSplit,
    HurdleCombinator,
    HurdleSubject,
    HurdleSubjectKind,
    HurdleTerms,
    IrrHurdle,
    MoicHurdle,
    Partner,
    PartnerRole,
    Partnership,
    PartnershipExecutionError,
    PartnershipValidationError,
    ProRataByContribution,
    PromoteBenchmark,
    SimpleDistributionOrder,
    SplitRule,
    SplitShare,
    TierKind,
    WaterfallTier,
)
from .deals.structured_variants import (
    analyze_structured_variant,
    position_perspectives,
    structured_variant_fingerprint,
)
from . import deals as deals_store
from .deals import Deal, DealNotFoundError, SnapshotValidationError
from .deals import store as investment_store
from .deals.variants import (
    ScenarioVariantAnalysis,
    ScenarioVariantFingerprint,
    VariantAnalysis,
    VariantFingerprint,
    VariantInputs,
    analyze_scenario_variant,
    analyze_variant,
    inspect_variant_inputs,
    scenario_variant_fingerprint,
    variant_fingerprint,
)
from .deals.decision_matrix import (
    DecisionMatrixConflictError,
    DecisionMatrixReport,
    analyze_decision_matrix,
)
# P7.6: the visible Investment services are imported under distinct names. The
# P7.4 and P7.5 route functions below are already named
# ``analyze_investment_variant``, ``investment_variant_fingerprint`` and
# ``analyze_investment_decision_matrix``, and a later ``def`` would shadow an
# import of the same name.
from .deals.decision_matrix import (
    InvestmentDecisionMatrixReport,
)
from .deals.decision_matrix import (
    analyze_investment_decision_matrix as analyze_consolidated_decision_matrix,
)
from .deals.investment_variants import (
    InvestmentVariantAnalysis,
    InvestmentVariantFingerprint,
    InvestmentVariantInputs,
    InvestmentVariantValidationError,
)
from .deals.investment_variants import (
    analyze_investment_variant as analyze_consolidated_variant,
)
from .deals.investment_variants import (
    inspect_investment_variant_inputs as inspect_consolidated_variant_inputs,
)
from .deals.investment_variants import (
    investment_variant_fingerprint as consolidated_variant_fingerprint,
)
from .deals.contracts import (
    Investment,
    InvestmentNotFoundError,
    InvestmentScenario,
    InvestmentStrategy,
    InvestmentStructureError,
    PartnerPerspectiveNotFoundError,
    PositionPerspectiveNotFoundError,
    ScenarioNotFoundError,
    StrategyNotFoundError,
)
from .deals.decision_matrix import analyze_partner_decision_matrix, analyze_position_decision_matrix
from .deals.contracts import InvestmentUnitNotFoundError, VisibleInvestment
from .investment import (
    InvestmentTransactionCost,
    InvestmentUnitMembership,
    InvestmentValidationError,
    TransactionCostCategory,
    UnitKind,
)
from .deals.fingerprint import (
    fingerprint_ai,
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)
from .engine import AcquisitionResults, DetailedAcquisitionResults
from .detailed_excel_reader import (
    DetailedExcelIntakeReport,
    read_detailed_excel_intake_from_bytes,
)
from .env import load_repo_env
from .excel_reader import ExcelIntakeReport, read_acquisition_inputs_from_bytes_with_report
from .ingestion import (
    DetailedExtractionResult,
    ExtractionConfigurationError,
    ExtractionProviderError,
    ExtractionResult,
    extract_detailed_om,
    extract_om,
)
from .validation import (
    InputValidationError,
    validate_acquisition_inputs,
    validate_acquisition_terms,
    validate_detailed_operating_inputs,
)

# Load repo-local .env (if present) before any request can resolve OpenAI /
# Azure DI credentials via os.environ -- see anchor.env for precedence rules.
load_repo_env()

app = FastAPI(title="Anchor API")

# =============================================================================
# Phase 10A/10B -- ingestion upload ceilings (KTD9)
#
# A POC-scale guard against an oversized, malformed, or spoofed upload
# reaching a paid Azure DI/OpenAI call (OM) or an expensive in-memory
# workbook parse (Excel) -- not a service-imposed limit (Azure's own
# Standard tier runs far higher: 500 MB / 2,000 pages).
# =============================================================================

_INGESTION_PATH = "/ingestion/om"
_MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
_MAX_UPLOAD_PAGES = 75

# Detailed Operating Model V2.1 Gate 12: a separate path (Option B, mirroring
# Gate 10's identical Excel-ingestion choice) rather than an optional/
# discriminated extension of the existing Quick endpoint -- the two result
# contracts and field sets differ enough that overloading _INGESTION_PATH
# would risk the existing, frozen Quick endpoint's behavior for no benefit.
_DETAILED_INGESTION_PATH = "/ingestion/om/detailed"
_PDF_PARSE_TIMEOUT_SECONDS = 5  # KTD11 -- bounds the local pypdf page-count parse.
_PDF_SIGNATURE = b"%PDF-"

_EXCEL_INGESTION_PATH = "/ingestion/excel"
_MAX_EXCEL_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB -- a structured input workbook is small.
_XLSX_SIGNATURE = b"PK\x03\x04"  # .xlsx is a zip archive (OOXML).

# Detailed Operating Model V2.1 Gate 10 -- a separate path (Option B, see the
# route below) rather than an optional/discriminated extension of the
# existing Quick endpoint: the two contracts, field sets, and error
# vocabularies differ enough that overloading _EXCEL_INGESTION_PATH would
# risk the existing, frozen Quick endpoint's behavior for no benefit -- a
# Detailed upload is never ambiguous about which endpoint it belongs to
# (the frontend's Detailed workspace calls this path exclusively).
_DETAILED_EXCEL_INGESTION_PATH = "/ingestion/excel/detailed"


class _IngestionUploadSizeGuard:
    """ASGI middleware rejecting an oversized ingestion upload by its
    declared ``Content-Length`` (KTD9(b)) before Starlette's multipart form
    parser reads any of the body.

    One instance guards every ingestion path this app exposes, each with its
    own byte ceiling (``limits``) -- this is the only point in the request
    pipeline that runs before FastAPI resolves the ``UploadFile``/``File()``
    dependency for any of them, so the declared-size check can't happen
    inside the route itself.
    """

    def __init__(self, app: ASGIApp, *, limits: Mapping[str, int]) -> None:
        self._app = app
        self._limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        max_bytes = (
            self._limits.get(scope.get("path"))
            if scope["type"] == "http" and scope.get("method") == "POST"
            else None
        )
        if max_bytes is not None:
            content_length = Headers(scope=scope).get("content-length")
            declared_bytes: int | None = None
            if content_length is not None:
                try:
                    declared_bytes = int(content_length)
                except ValueError:
                    declared_bytes = None
            if declared_bytes is not None and declared_bytes > max_bytes:
                response = PlainTextResponse(
                    f"Upload exceeds the maximum allowed size of {max_bytes} bytes.",
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


app.add_middleware(
    _IngestionUploadSizeGuard,
    limits={
        _INGESTION_PATH: _MAX_UPLOAD_BYTES,
        _DETAILED_INGESTION_PATH: _MAX_UPLOAD_BYTES,
        _EXCEL_INGESTION_PATH: _MAX_EXCEL_UPLOAD_BYTES,
        _DETAILED_EXCEL_INGESTION_PATH: _MAX_EXCEL_UPLOAD_BYTES,
    },
)

# Allows the local Vite dev server (Phase 6 web UI) to call this API from the
# browser. Pure API plumbing -- does not touch request/response semantics or
# any financial calculation.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _validation_error_detail(error: InputValidationError) -> list[dict[str, Any]]:
    return [
        {
            "field_id": issue.field_id,
            "category": issue.category.value,
            "message": issue.message,
        }
        for issue in error.issues
    ]


def _lease_validation_error_detail(error: LeaseValidationError) -> list[dict[str, Any]]:
    """D5.3: a ``LeaseValidationError`` as a structured 422 detail.

    The Lease-Level counterpart to ``_validation_error_detail`` above, and
    deliberately its own shape rather than a translation into the Quick/Detailed
    one. The two streams answer different questions and carry different
    locators: ``InputIssue`` names a flat ``field_id``, while a
    ``LeaseValidationIssue`` names a ``path`` into a nested, variable-arity rent
    roll (``suites[2].suite_area_sf``) and a stable ``code`` a UI can branch on.
    Flattening either into the other would throw away exactly the part a
    consumer needs to anchor an error to the row that caused it.

    One shape serves both structural parsing and downstream domain validation,
    per D8 -- a malformed field and an out-of-domain field reach a caller
    identically, differing only in ``code``.
    """

    return [
        {
            "code": issue.code.value,
            "path": issue.path,
            "message": issue.message,
            "severity": issue.severity.value,
        }
        for issue in error.result.issues
    ]


def _lease_validation_error_response(error: LeaseValidationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=_lease_validation_error_detail(error),
    )


# =============================================================================
# Phase 6 Gate D6.5 -- the Business Plan on the request surface
#
# Every endpoint that analyzes, fingerprints or saves a deal accepts one
# optional, mode-agnostic top-level ``business_plan`` object beside the mode's
# own inputs -- never inside ``inputs``/``terms``/the rent roll. Absent (or
# ``null``, or ``{}``) is ``BusinessPlan()``, so every pre-D6 request is
# unchanged. The value is parsed by ``anchor.business_plan.parse_business_plan``
# and validated by the D6.1 validation authority; this module restates no rule.
#
# Each endpoint reads the plan exactly once, through ``_optional_business_plan``,
# and passes that one value by name to every plan-aware call it makes, so the
# neutral ``BusinessPlan()`` defaults the analysis layer keeps for plan-free
# callers are never relied on here
# (``tests/test_d6_5_business_plan_persistence_architecture.py``).
# =============================================================================

_BUSINESS_PLAN_KEY = "business_plan"


def _business_plan_validation_error_response(
    error: BusinessPlanValidationError,
) -> HTTPException:
    """A refused Business Plan as a structured 422, in the same
    ``code``/``path``/``message`` shape the Lease-Level issue stream uses --
    there is no second D6 error envelope. Paths are rooted at the request, so a
    UI can anchor ``business_plan.capital_items[2].month`` to its row. The D6.1
    issue contract has no severity: every Business Plan issue is an error."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "path": (
                    issue.path
                    if issue.path == _BUSINESS_PLAN_KEY
                    else f"{_BUSINESS_PLAN_KEY}.{issue.path}"
                ),
                "message": issue.message,
            }
            for issue in error.result.issues
        ],
    )


def _optional_business_plan(payload: dict[str, Any]) -> BusinessPlan:
    """The request's validated Business Plan -- ``BusinessPlan()`` when the key
    is absent -- or a structured 422."""

    try:
        return parse_business_plan(payload.get(_BUSINESS_PLAN_KEY))
    except BusinessPlanValidationError as error:
        raise _business_plan_validation_error_response(error) from None


def _unsupported_operating_mode(
    operating_mode: OperatingMode, *, endpoint: str
) -> HTTPException:
    """D5.1A: the explicit refusal a *total* ``OperatingMode`` dispatch raises
    for a valid mode this endpoint has no implementation for.

    Deliberately distinct from the *unparseable*-mode error raised by
    ``_require_operating_mode`` and the two inline parse guards: that one means
    the submitted string names no ``OperatingMode`` member at all, and its
    message enumerates the members that exist. This one means the caller named a
    real, currently-valid member that this particular endpoint does not serve --
    which is exactly the state every Lease-Level surface is in until the gate
    that implements it (D5.3 analysis, D5.4 persistence, D5.8 AI). Collapsing the
    two would tell a caller that ``"lease_level"`` is not a mode, which stops
    being true the moment the member is published.

    Carries no financial knowledge, parses nothing, and dispatches nothing: it
    formats one 422 so no endpoint hand-writes the same payload, and so a mode
    becomes supported by replacing a ``case`` arm rather than by editing an
    error string.
    """

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=(
            f"operating_mode {operating_mode.value!r} is not supported by "
            f"{endpoint}."
        ),
    )


def _analyze_detailed(payload: dict[str, Any]) -> DetailedAcquisitionResults:
    """Detailed Operating Model V2.1 Gate 5 (mode routing) / Gate 4
    (response shape): the 'detailed' operating_mode branch of ``/analyze``.
    Validates 'terms' and 'detailed_operating_inputs' with the same shared
    validators every other consumer uses, then delegates -- with the request's
    Business Plan (D6.5) -- to ``analyze_detailed_acquisition_with_business_plan``,
    which runs ``analyze_detailed_acquisition_with_projection`` -- no financial
    math or validation rule of its own. Returns the richer
    ``DetailedAcquisitionResults`` envelope (operating projection +
    acquisition results) so a Detailed-mode frontend can render the
    institutional operating statement without a second round trip."""

    raw_terms = payload.get("terms")
    if not isinstance(raw_terms, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A 'detailed' operating_mode request must include a 'terms' object.",
        )
    raw_detailed_inputs = payload.get("detailed_operating_inputs")
    if not isinstance(raw_detailed_inputs, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "A 'detailed' operating_mode request must include a "
                "'detailed_operating_inputs' object."
            ),
        )

    try:
        terms = validate_acquisition_terms(raw_terms)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None

    try:
        detailed_inputs = validate_detailed_operating_inputs(raw_detailed_inputs)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None

    business_plan = _optional_business_plan(payload)
    return analyze_detailed_acquisition_with_business_plan(
        terms, detailed_inputs, business_plan=business_plan
    )


def _analyze_quick(payload: dict[str, Any]) -> AcquisitionResults:
    """D5.1A: the 'quick' operating_mode branch of ``POST /analyze``,
    extracted verbatim so the endpoint's mode dispatch can be total -- one
    explicit arm per mode -- rather than a Detailed test with an implicit
    Quick fallthrough. Behavior is unchanged: the same validator, the same
    engine call, the same bare ``AcquisitionResults`` response.
    Named symmetrically with ``_analyze_detailed``.

    D6.5: a Quick ``/analyze`` body *is* the flat inputs object, so the
    ``business_plan`` key is set aside before the inputs validator sees it --
    exactly as ``operating_mode`` is -- rather than being reported as an
    unknown Field ID."""

    try:
        inputs = validate_acquisition_inputs(
            {key: value for key, value in payload.items() if key != _BUSINESS_PLAN_KEY}
        )
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None

    business_plan = _optional_business_plan(payload)
    return analyze_quick_acquisition_with_business_plan(
        inputs, business_plan=business_plan
    )


def _require_lease_level_inputs(
    payload: dict[str, Any], *, also_owned: tuple[str, ...] = ()
) -> ParsedLeaseLevelInputs:
    """Reconstruct the five Lease-Level input contracts from the raw body.

    Hands the payload to ``parse_lease_level_inputs`` **whole**. Pre-selecting
    the keys it owns would silently discard a typo -- ``suite_are_sf`` beside
    ``suite_area_sf`` -- which is precisely the failure D5.2's unknown-field
    detection exists to catch, and the parser already knows that ``terms`` and
    ``operating_mode`` belong to other owners.

    This adapter constructs no ``Suite``, ``Lease`` or assumptions record
    itself: doing so would put a second, untested wire format beside the
    ratified one.

    ``also_owned`` names the top-level keys *this endpoint* consumes beside the
    Lease-Level inputs -- the row/column/metric controls a sensitivity body
    carries. Declaring them keeps the unknown-key check live for everything
    else, so ``row_assumtion`` is still reported rather than silently ignored.

    D6.5: ``business_plan`` is owned by every Lease-Level endpoint -- it is
    mode-agnostic deal state, parsed by ``_optional_business_plan`` -- so it is
    declared here once rather than in each endpoint's list.
    """

    try:
        return parse_lease_level_inputs(
            payload, externally_owned_keys=(*also_owned, _BUSINESS_PLAN_KEY)
        )
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None


def _analyze_lease_level(payload: dict[str, Any]) -> LeaseLevelAcquisitionResults:
    """D5.3: the 'lease_level' branch of ``/analyze``.

    Composes the two input owners -- shared ``AcquisitionTerms`` validation and
    D5.2 structural parsing -- and delegates to the D4.5B entry point. It calls
    no leasing builder, runs no month arithmetic and reads no result field: the
    deterministic pipeline remains the sole financial authority, and this
    function's whole job is to turn JSON into its arguments.

    Returns ``LeaseLevelAcquisitionResults`` unchanged -- the monthly
    projection, the annual projection derived from it, and the same generic
    ``AcquisitionResults`` Quick and Detailed produce. No transport copy is
    made, so the audit trail a caller sees is the one the engine used.

    ``LeaseValidationError`` covers both phases and both surface as a structured
    422: a malformed rent roll (D5.2) and an unanalysable one -- a mid-month
    analysis start, an unreconciled area, ``NON_POSITIVE_FORWARD_EXIT_NOI`` --
    reach the caller through one shape, distinguished by ``code``.
    """

    terms = _require_deal_terms(payload, mode_label="lease_level")
    inputs = _require_lease_level_inputs(payload)
    business_plan = _optional_business_plan(payload)

    try:
        return analyze_lease_level_acquisition_with_business_plan(
            terms,
            inputs.property_inputs,
            inputs.suites,
            inputs.leases,
            market_leasing=inputs.market_leasing,
            operating_inputs=inputs.operating_inputs,
            business_plan=business_plan,
        )
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None


@app.post(
    "/analyze",
    response_model=(
        AcquisitionResults | DetailedAcquisitionResults | LeaseLevelAcquisitionResults
    ),
)
def analyze(
    payload: dict[str, Any] = Body(...),
) -> AcquisitionResults | DetailedAcquisitionResults | LeaseLevelAcquisitionResults:
    """Detailed Operating Model V2.1 Gate 5: gains an optional
    ``operating_mode`` discriminator (``"quick"`` default / ``"detailed"``).
    A ``"quick"``/absent ``operating_mode`` request is unaffected -- the
    remaining payload is validated and analyzed exactly as before this
    gate; ``operating_mode`` itself is popped first so it is never seen by
    ``validate_acquisition_inputs`` as an unknown Field ID, and the
    response is a bare ``AcquisitionResults``, byte-for-byte the same shape
    as before this gate. A ``"detailed"`` request is delegated to
    ``_analyze_detailed`` and receives the richer
    ``DetailedAcquisitionResults`` envelope (Gate 4) -- every
    ``AcquisitionResults`` field is still present, nested under ``results``,
    plus ``operating_projection`` for the institutional operating statement.
    """

    payload = dict(payload)
    operating_mode_raw = payload.pop("operating_mode", OperatingMode.QUICK.value)
    try:
        operating_mode = OperatingMode(operating_mode_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "operating_mode must be one of "
                f"{[member.value for member in OperatingMode]}; "
                f"got {operating_mode_raw!r}."
            ),
        ) from None

    match operating_mode:
        case OperatingMode.QUICK:
            return _analyze_quick(payload)
        case OperatingMode.DETAILED:
            return _analyze_detailed(payload)
        case OperatingMode.LEASE_LEVEL:
            return _analyze_lease_level(payload)
        case _:
            raise _unsupported_operating_mode(
                operating_mode, endpoint="POST /analyze"
            )


# =============================================================================
# Phase 7 -- sensitivity analysis
#
# Both endpoints below validate the nested ``inputs`` object with the same
# ``validate_acquisition_inputs`` used by ``/analyze``, then delegate all
# sensitivity computation to ``anchor.analysis.sensitivity``. Neither
# endpoint performs financial or sensitivity math itself.
#
# Detailed Operating Model V2.1 Gate 14: both endpoints gain the same
# ``operating_mode`` discriminator ``/analyze`` and ``/ai/analysis`` already
# have (Gate 5/9). A ``"quick"``/absent request is completely unaffected --
# ``operating_mode`` is popped first, exactly as those endpoints do, so the
# remaining payload is validated and computed exactly as before this gate.
# A ``"detailed"`` request delegates to ``run_detailed_two_way_sensitivity``/
# ``build_standard_detailed_presets`` -- the same Gate 8 functions the
# Detailed AI Analyst already calls -- no sensitivity math of its own.
# =============================================================================


def _sensitivity_detailed(payload: dict[str, Any]) -> TwoWaySensitivityResult:
    terms = _require_deal_terms(payload)
    detailed_operating_inputs = _require_deal_detailed_operating_inputs(payload)
    business_plan = _optional_business_plan(payload)

    missing_fields = [
        field
        for field in (
            "row_assumption",
            "row_values",
            "column_assumption",
            "column_values",
            "metric",
        )
        if field not in payload
    ]
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Missing required field(s): {', '.join(missing_fields)}.",
        )

    try:
        return run_detailed_two_way_sensitivity(
            terms,
            detailed_operating_inputs,
            row_assumption=payload["row_assumption"],
            row_values=payload["row_values"],
            column_assumption=payload["column_assumption"],
            column_values=payload["column_values"],
            metric=payload["metric"],
            business_plan=business_plan,
        )
    except (UnknownAssumptionError, UnknownMetricError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None


def _sensitivity_quick(payload: dict[str, Any]) -> TwoWaySensitivityResult:
    """D5.1A: the 'quick' operating_mode branch of ``POST /sensitivity``,
    extracted verbatim so the endpoint's mode dispatch can be total -- one
    explicit arm per mode -- rather than a Detailed test with an implicit
    Quick fallthrough. Behavior is unchanged: the same validator and the
    same ``run_two_way_sensitivity`` call.
    Named symmetrically with ``_sensitivity_detailed``."""

    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Request body must include an 'inputs' object.",
        )

    try:
        inputs = validate_acquisition_inputs(raw_inputs)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None
    business_plan = _optional_business_plan(payload)

    missing_fields = [
        field
        for field in (
            "row_assumption",
            "row_values",
            "column_assumption",
            "column_values",
            "metric",
        )
        if field not in payload
    ]
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Missing required field(s): {', '.join(missing_fields)}.",
        )

    try:
        return run_two_way_sensitivity(
            inputs,
            row_assumption=payload["row_assumption"],
            row_values=payload["row_values"],
            column_assumption=payload["column_assumption"],
            column_values=payload["column_values"],
            metric=payload["metric"],
            business_plan=business_plan,
        )
    except (UnknownAssumptionError, UnknownMetricError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None


_TWO_WAY_FIELDS = (
    "row_assumption",
    "row_values",
    "column_assumption",
    "column_values",
    "metric",
)

_ONE_WAY_FIELDS = ("assumption", "values", "metric")

#: Top-level keys a ``/deals`` body carries beside the Lease-Level inputs.
#: A literal tuple, reviewed here: these are the keys *this endpoint family*
#: consumes, and nothing derived from the request may ever join them -- a typo
#: must never be able to excuse itself by appearing in the owned set.
_DEAL_FIELDS = ("name", "deal_context")


def _require_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Missing required field(s): {', '.join(missing)}.",
        )


def _sensitivity_lease_level(payload: dict[str, Any]) -> TwoWaySensitivityResult:
    """D5.3: the 'lease_level' branch of two-way ``/sensitivity``.

    Delegates to the shipped D4.6B runner, which re-underwrites the complete
    deterministic pipeline once per cell from the same immutable baseline. This
    adapter interpolates nothing, caches nothing and evaluates no cell itself.

    Candidate values stay **absolute**, exactly as the runner defines them --
    never a relative shock. Refusals keep their identities: an unsupported
    target, an unsupported metric, and a target shadowed by a suite override are
    three different answers, and the last one refuses the whole run rather than
    quietly perturbing a property default that some suite overrides anyway.
    """

    terms = _require_deal_terms(payload, mode_label="lease_level")
    inputs = _require_lease_level_inputs(payload, also_owned=_TWO_WAY_FIELDS)
    business_plan = _optional_business_plan(payload)
    _require_fields(payload, _TWO_WAY_FIELDS)

    try:
        return run_lease_level_two_way_sensitivity(
            terms,
            inputs.property_inputs,
            inputs.suites,
            inputs.leases,
            market_leasing=inputs.market_leasing,
            operating_inputs=inputs.operating_inputs,
            row_assumption=payload["row_assumption"],
            row_values=payload["row_values"],
            column_assumption=payload["column_assumption"],
            column_values=payload["column_values"],
            metric=payload["metric"],
            business_plan=business_plan,
        )
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None
    except SensitivityTargetShadowedBySuiteOverrideError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except (UnknownAssumptionError, UnknownMetricError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None


@app.post("/sensitivity", response_model=TwoWaySensitivityResult)
def sensitivity(payload: dict[str, Any] = Body(...)) -> TwoWaySensitivityResult:
    payload = dict(payload)
    operating_mode = _require_operating_mode(payload)

    match operating_mode:
        case OperatingMode.QUICK:
            return _sensitivity_quick(payload)
        case OperatingMode.DETAILED:
            return _sensitivity_detailed(payload)
        case OperatingMode.LEASE_LEVEL:
            return _sensitivity_lease_level(payload)
        case _:
            raise _unsupported_operating_mode(
                operating_mode, endpoint="POST /sensitivity"
            )


# =============================================================================
# D5.3 -- one-way sensitivity
#
# A new endpoint rather than a dimension flag on ``/sensitivity``: adding a
# discriminator there would change a request contract Quick and Detailed already
# depend on, to describe a differently-shaped question. The two-way contract is
# left exactly as shipped.
#
# Served for **all three** modes (D5.0 decision D3, an approved scope
# expansion). All three one-way runners already exist and are tested; an
# endpoint that refused Quick and Detailed would be advertising a limitation
# that is not real, and would read as a defect rather than a boundary.
#
# Every mode returns the same ``OneWaySensitivityResult`` the runners return --
# no per-mode response shape, and no reformatting here.
# =============================================================================


def _one_way_quick(payload: dict[str, Any]) -> OneWaySensitivityResult:
    inputs = _require_deal_inputs(payload)
    business_plan = _optional_business_plan(payload)
    _require_fields(payload, _ONE_WAY_FIELDS)
    return run_one_way_sensitivity(
        inputs,
        assumption=payload["assumption"],
        values=payload["values"],
        metric=payload["metric"],
        business_plan=business_plan,
    )


def _one_way_detailed(payload: dict[str, Any]) -> OneWaySensitivityResult:
    terms = _require_deal_terms(payload)
    detailed_operating_inputs = _require_deal_detailed_operating_inputs(payload)
    business_plan = _optional_business_plan(payload)
    _require_fields(payload, _ONE_WAY_FIELDS)
    return run_detailed_one_way_sensitivity(
        terms,
        detailed_operating_inputs,
        assumption=payload["assumption"],
        values=payload["values"],
        metric=payload["metric"],
        business_plan=business_plan,
    )


def _one_way_lease_level(payload: dict[str, Any]) -> OneWaySensitivityResult:
    terms = _require_deal_terms(payload, mode_label="lease_level")
    inputs = _require_lease_level_inputs(payload, also_owned=_ONE_WAY_FIELDS)
    business_plan = _optional_business_plan(payload)
    _require_fields(payload, _ONE_WAY_FIELDS)
    try:
        return run_lease_level_one_way_sensitivity(
            terms,
            inputs.property_inputs,
            inputs.suites,
            inputs.leases,
            market_leasing=inputs.market_leasing,
            operating_inputs=inputs.operating_inputs,
            assumption=payload["assumption"],
            values=payload["values"],
            metric=payload["metric"],
            business_plan=business_plan,
        )
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None
    except SensitivityTargetShadowedBySuiteOverrideError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None


@app.post("/sensitivity/one-way", response_model=OneWaySensitivityResult)
def sensitivity_one_way(
    payload: dict[str, Any] = Body(...),
) -> OneWaySensitivityResult:
    """Vary one approved assumption across absolute candidate values.

    Exposes the shipped one-way runners for every mode. Each performs
    ``1 + len(values)`` complete re-underwrites -- one baseline plus one per
    candidate -- with no caching and no shortcut, so a cell's value is always a
    full deterministic analysis rather than an interpolation.
    """

    payload = dict(payload)
    operating_mode = _require_operating_mode(payload)

    try:
        match operating_mode:
            case OperatingMode.QUICK:
                return _one_way_quick(payload)
            case OperatingMode.DETAILED:
                return _one_way_detailed(payload)
            case OperatingMode.LEASE_LEVEL:
                return _one_way_lease_level(payload)
            case _:
                raise _unsupported_operating_mode(
                    operating_mode, endpoint="POST /sensitivity/one-way"
                )
    except (UnknownAssumptionError, UnknownMetricError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None


def _sensitivity_presets_detailed(
    payload: dict[str, Any]
) -> StandardDetailedSensitivityPresets:
    terms = _require_deal_terms(payload)
    detailed_operating_inputs = _require_deal_detailed_operating_inputs(payload)
    business_plan = _optional_business_plan(payload)
    return build_standard_detailed_presets(
        terms, detailed_operating_inputs, business_plan=business_plan
    )


def _sensitivity_presets_quick(payload: dict[str, Any]) -> StandardSensitivityPresets:
    """D5.1A: the 'quick' operating_mode branch of ``POST /sensitivity/presets``,
    extracted verbatim so the endpoint's mode dispatch can be total -- one
    explicit arm per mode -- rather than a Detailed test with an implicit
    Quick fallthrough. Behavior is unchanged: the same validator and the
    same ``build_standard_presets`` call.
    Named symmetrically with ``_sensitivity_presets_detailed``."""

    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Request body must include an 'inputs' object.",
        )

    try:
        inputs = validate_acquisition_inputs(raw_inputs)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None

    business_plan = _optional_business_plan(payload)
    return build_standard_presets(inputs, business_plan=business_plan)


@app.post(
    "/sensitivity/presets",
    response_model=StandardSensitivityPresets | StandardDetailedSensitivityPresets,
)
def sensitivity_presets(
    payload: dict[str, Any] = Body(...),
) -> StandardSensitivityPresets | StandardDetailedSensitivityPresets:
    payload = dict(payload)
    operating_mode = _require_operating_mode(payload)

    match operating_mode:
        case OperatingMode.QUICK:
            return _sensitivity_presets_quick(payload)
        case OperatingMode.DETAILED:
            return _sensitivity_presets_detailed(payload)
        case OperatingMode.LEASE_LEVEL:
            # Lease-Level ships no preset bundle -- deliberately, per D4.6B/D5.0 decision D4.
            # This refusal is permanent for D5, not a staging placeholder.
            raise _unsupported_operating_mode(
                operating_mode, endpoint="POST /sensitivity/presets"
            )
        case _:
            raise _unsupported_operating_mode(
                operating_mode, endpoint="POST /sensitivity/presets"
            )


# =============================================================================
# Phase 8 -- break-even analysis
#
# Delegates all break-even solving to ``anchor.analysis.break_even``;
# this endpoint performs no financial math and no threshold search itself.
#
# Detailed Operating Model V2.1 Gate 14: gains the same ``operating_mode``
# discriminator ``/analyze``, ``/ai/analysis``, and ``/sensitivity`` already
# have. A "quick"/absent request is completely unaffected. A "detailed"
# request delegates to ``build_standard_detailed_break_even_analysis`` --
# the same Gate 8 function the Detailed AI Analyst already calls -- no
# break-even search of its own.
# =============================================================================


def _numeric_target(payload: dict[str, Any], field: str) -> float:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} must be a numeric value.",
        )
    return float(value)


def _break_even_detailed(payload: dict[str, Any]) -> StandardDetailedBreakEvenAnalysis:
    terms = _require_deal_terms(payload)
    detailed_operating_inputs = _require_deal_detailed_operating_inputs(payload)
    business_plan = _optional_business_plan(payload)
    (
        target_levered_irr,
        target_headline_dscr,
        target_equity_multiple,
        return_hurdle_metric,
    ) = _require_ai_hurdle_targets(payload)

    try:
        return build_standard_detailed_break_even_analysis(
            terms,
            detailed_operating_inputs,
            target_levered_irr=target_levered_irr,
            target_headline_dscr=target_headline_dscr,
            target_equity_multiple=target_equity_multiple,
            return_hurdle_metric=return_hurdle_metric,
            business_plan=business_plan,
        )
    except InvalidBreakEvenTargetError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None


def _break_even_quick(payload: dict[str, Any]) -> StandardBreakEvenAnalysis:
    """D5.1A: the 'quick' operating_mode branch of ``POST /break-even``,
    extracted verbatim so the endpoint's mode dispatch can be total -- one
    explicit arm per mode -- rather than a Detailed test with an implicit
    Quick fallthrough. Behavior is unchanged: the same validator, the same
    hurdle parsing and the same ``build_standard_break_even_analysis``
    call.
    Named symmetrically with ``_break_even_detailed``."""

    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Request body must include an 'inputs' object.",
        )

    try:
        inputs = validate_acquisition_inputs(raw_inputs)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None
    business_plan = _optional_business_plan(payload)

    missing_fields = [
        field
        for field in ("target_levered_irr", "target_headline_dscr", "target_equity_multiple")
        if field not in payload
    ]
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Missing required field(s): {', '.join(missing_fields)}.",
        )

    target_levered_irr = _numeric_target(payload, "target_levered_irr")
    target_headline_dscr = _numeric_target(payload, "target_headline_dscr")
    target_equity_multiple = _numeric_target(payload, "target_equity_multiple")

    return_hurdle_metric_raw = payload.get("return_hurdle_metric", ReturnHurdleMetric.LEVERED_IRR.value)
    try:
        return_hurdle_metric = ReturnHurdleMetric(return_hurdle_metric_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "return_hurdle_metric must be one of "
                f"{[member.value for member in ReturnHurdleMetric]}; "
                f"got {return_hurdle_metric_raw!r}."
            ),
        ) from None

    try:
        return build_standard_break_even_analysis(
            inputs,
            target_levered_irr=target_levered_irr,
            target_headline_dscr=target_headline_dscr,
            target_equity_multiple=target_equity_multiple,
            return_hurdle_metric=return_hurdle_metric,
            business_plan=business_plan,
        )
    except InvalidBreakEvenTargetError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None


@app.post(
    "/break-even",
    response_model=StandardBreakEvenAnalysis | StandardDetailedBreakEvenAnalysis,
)
def break_even(
    payload: dict[str, Any] = Body(...),
) -> StandardBreakEvenAnalysis | StandardDetailedBreakEvenAnalysis:
    payload = dict(payload)
    operating_mode = _require_operating_mode(payload)

    match operating_mode:
        case OperatingMode.QUICK:
            return _break_even_quick(payload)
        case OperatingMode.DETAILED:
            return _break_even_detailed(payload)
        case OperatingMode.LEASE_LEVEL:
            # Lease-Level break-even does not exist and is not planned for D5 (guardrail G35).
            # This refusal is permanent for D5, not a staging placeholder.
            raise _unsupported_operating_mode(
                operating_mode, endpoint="POST /break-even"
            )
        case _:
            raise _unsupported_operating_mode(
                operating_mode, endpoint="POST /break-even"
            )


# =============================================================================
# Phase 9A / Detailed Operating Model V2.1 Gate 9 -- AI Analyst
#
# Delegates all context assembly and the provider call to
# ``anchor.ai.generate_ai_analysis``/``generate_detailed_ai_analysis``; this
# endpoint performs no financial math, sensitivity math, break-even search,
# or OpenAI call of its own. Gains the same ``operating_mode`` discriminator
# as ``/analyze`` (Gate 5) -- a "quick"/absent request is unaffected.
# =============================================================================


#: The top-level keys ``POST /ai/analysis`` consumes beside a Lease-Level input
#: set. Declared so ``_require_lease_level_inputs`` keeps its unknown-key check
#: live for everything else -- a mistyped ``target_leverd_irr`` is still
#: reported rather than silently ignored (D5.2's rule, D5.8's endpoint).
#:
#: ``deal_context`` belongs here for the same reason it belongs in
#: ``_DEAL_FIELDS``: this endpoint reads it (``_optional_deal_context``) and
#: threads it to the model as the analyst's own stated strategy. Omitting it
#: would make every real request from the app fail its unknown-key check --
#: the client always sends the field, ``null`` included.
#:
#: D6.5 threaded the Business Plan to the AI Analyst mechanically -- the plan
#: the request carries is the plan its deterministic analysis uses. D6.8 grounds
#: it: every arm, Lease-Level included, hands that same plan to the context the
#: model is shown, beside the deterministic D6 results it produced.
_AI_HURDLE_FIELDS: tuple[str, ...] = (
    "target_levered_irr",
    "target_headline_dscr",
    "target_equity_multiple",
    "return_hurdle_metric",
    "deal_context",
)


def _require_ai_hurdle_targets(payload: dict[str, Any]) -> tuple[float, float, float, ReturnHurdleMetric]:
    missing_fields = [
        field
        for field in ("target_levered_irr", "target_headline_dscr", "target_equity_multiple")
        if field not in payload
    ]
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Missing required field(s): {', '.join(missing_fields)}.",
        )

    target_levered_irr = _numeric_target(payload, "target_levered_irr")
    target_headline_dscr = _numeric_target(payload, "target_headline_dscr")
    target_equity_multiple = _numeric_target(payload, "target_equity_multiple")

    return_hurdle_metric_raw = payload.get("return_hurdle_metric", ReturnHurdleMetric.LEVERED_IRR.value)
    try:
        return_hurdle_metric = ReturnHurdleMetric(return_hurdle_metric_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "return_hurdle_metric must be one of "
                f"{[member.value for member in ReturnHurdleMetric]}; "
                f"got {return_hurdle_metric_raw!r}."
            ),
        ) from None

    return target_levered_irr, target_headline_dscr, target_equity_multiple, return_hurdle_metric


def _ai_analysis_detailed(payload: dict[str, Any]) -> AIAnalysis:
    """Detailed Operating Model V2.1 Gate 9: the 'detailed' operating_mode
    branch of ``/ai/analysis``. Validates 'terms' and
    'detailed_operating_inputs' with the same shared validators every other
    Detailed consumer uses, then delegates to
    ``generate_detailed_ai_analysis`` -- no financial math, context
    assembly, or OpenAI call of its own."""

    terms = _require_deal_terms(payload)
    detailed_operating_inputs = _require_deal_detailed_operating_inputs(payload)
    business_plan = _optional_business_plan(payload)
    deal_context = _optional_deal_context(payload)
    (
        target_levered_irr,
        target_headline_dscr,
        target_equity_multiple,
        return_hurdle_metric,
    ) = _require_ai_hurdle_targets(payload)

    try:
        return generate_detailed_ai_analysis(
            terms,
            detailed_operating_inputs,
            target_levered_irr=target_levered_irr,
            target_equity_multiple=target_equity_multiple,
            target_headline_dscr=target_headline_dscr,
            return_hurdle_metric=return_hurdle_metric,
            deal_context=deal_context,
            business_plan=business_plan,
        )
    except InvalidBreakEvenTargetError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None
    except AIProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from None


def _ai_analysis_quick(payload: dict[str, Any]) -> AIAnalysis:
    """D5.1A: the 'quick' operating_mode branch of ``POST /ai/analysis``,
    extracted verbatim so the endpoint's mode dispatch can be total -- one
    explicit arm per mode -- rather than a Detailed test with an implicit
    Quick fallthrough. Behavior is unchanged: the same validator and the
    same ``generate_ai_analysis`` call.
    Named symmetrically with ``_ai_analysis_detailed``."""

    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Request body must include an 'inputs' object.",
        )

    try:
        inputs = validate_acquisition_inputs(raw_inputs)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None

    business_plan = _optional_business_plan(payload)
    deal_context = _optional_deal_context(payload)
    (
        target_levered_irr,
        target_headline_dscr,
        target_equity_multiple,
        return_hurdle_metric,
    ) = _require_ai_hurdle_targets(payload)

    try:
        return generate_ai_analysis(
            inputs,
            target_levered_irr=target_levered_irr,
            target_equity_multiple=target_equity_multiple,
            target_headline_dscr=target_headline_dscr,
            return_hurdle_metric=return_hurdle_metric,
            deal_context=deal_context,
            business_plan=business_plan,
        )
    except InvalidBreakEvenTargetError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None
    except AIProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from None


def _ai_analysis_lease_level(payload: dict[str, Any]) -> AIAnalysis:
    """D5.8: the 'lease_level' branch of ``POST /ai/analysis``.

    Same endpoint, same mode discriminator, same response model -- no second
    AI endpoint exists and none is needed. It validates with the same two
    shared validators every other Lease-Level endpoint uses
    (``_require_deal_terms`` and ``_require_lease_level_inputs``), runs the one
    authoritative analysis exactly once through
    ``analyze_lease_level_acquisition_with_business_plan`` -- with the
    request's Business Plan (D6.5) -- and hands the result to
    ``generate_lease_level_ai_analysis``.

    That single analysis call is the only financial work here, and it is the
    same call ``POST /analyze`` makes for this mode -- so the AI Analyst
    describes the deal the analyst's own Analyze produced. Nothing else is
    triggered: no sensitivity preset bundle (this mode has none, and the
    analyst-directed runs stay in Risk where they belong), no break-even search
    (this mode has none), and no alternate scenario. This endpoint reproduces
    no financial formula of its own.

    A rent roll that cannot be underwritten is refused exactly as ``/analyze``
    refuses it, through the same ``LeaseValidationError`` shape, rather than
    reaching the model as a partial context.
    """

    terms = _require_deal_terms(payload, mode_label="lease_level")
    lease_level_inputs = _require_lease_level_inputs(payload, also_owned=_AI_HURDLE_FIELDS)
    business_plan = _optional_business_plan(payload)
    deal_context = _optional_deal_context(payload)
    (
        target_levered_irr,
        target_headline_dscr,
        target_equity_multiple,
        return_hurdle_metric,
    ) = _require_ai_hurdle_targets(payload)

    try:
        lease_level_results = analyze_lease_level_acquisition_with_business_plan(
            terms,
            lease_level_inputs.property_inputs,
            lease_level_inputs.suites,
            lease_level_inputs.leases,
            market_leasing=lease_level_inputs.market_leasing,
            operating_inputs=lease_level_inputs.operating_inputs,
            business_plan=business_plan,
        )
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None

    try:
        return generate_lease_level_ai_analysis(
            terms,
            lease_level_inputs,
            lease_level_results,
            target_levered_irr=target_levered_irr,
            target_equity_multiple=target_equity_multiple,
            target_headline_dscr=target_headline_dscr,
            return_hurdle_metric=return_hurdle_metric,
            deal_context=deal_context,
            business_plan=business_plan,
        )
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None
    except AIProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from None


@app.post("/ai/analysis", response_model=AIAnalysis)
def ai_analysis(payload: dict[str, Any] = Body(...)) -> AIAnalysis:
    payload = dict(payload)
    operating_mode_raw = payload.pop("operating_mode", OperatingMode.QUICK.value)
    try:
        operating_mode = OperatingMode(operating_mode_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "operating_mode must be one of "
                f"{[member.value for member in OperatingMode]}; "
                f"got {operating_mode_raw!r}."
            ),
        ) from None

    match operating_mode:
        case OperatingMode.QUICK:
            return _ai_analysis_quick(payload)
        case OperatingMode.DETAILED:
            return _ai_analysis_detailed(payload)
        case OperatingMode.LEASE_LEVEL:
            return _ai_analysis_lease_level(payload)
        case _:
            raise _unsupported_operating_mode(
                operating_mode, endpoint="POST /ai/analysis"
            )


# =============================================================================
# Phase 10A -- OM ingestion
#
# Validates the upload (content-type, size, page count -- KTD9) then
# delegates the entire extraction/classification pipeline to
# ``anchor.ingestion.extract_om``. This endpoint performs no
# extraction, classification, or financial math of its own, and never
# calls the deterministic engine. Azure DI/OpenAI credentials are read only
# inside the ingestion package's own provider modules (R15) -- never
# accepted from or echoed to this request/response.
#
# A plain ``def`` route, not ``async def`` (KTD2): the Azure DI SDK's
# poller performs blocking I/O even from its async client, so this route
# is dispatched to FastAPI's shared threadpool like every other route in
# this file, made survivable only by the KTD11 timeouts each synchronous
# step below carries.
# =============================================================================


def _reject_upload(detail: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _validate_content_type(file: UploadFile) -> None:
    if file.content_type != "application/pdf":
        _reject_upload("Uploaded file must have content-type 'application/pdf'.")


def _read_upload_bytes(file: UploadFile, *, max_bytes: int) -> bytes:
    """Read the upload's bytes, never buffering more than ``max_bytes + 1``
    into memory regardless of what the request declared (KTD9(c)) -- a
    missing or understated ``Content-Length`` cannot bypass this guard."""

    file.file.seek(0)
    contents = file.file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        _reject_upload(f"Upload exceeds the maximum allowed size of {max_bytes} bytes.")
    return contents


def _validate_pdf_signature(pdf_bytes: bytes) -> None:
    # The client-supplied content-type header is spoofable (KTD9); this
    # confirms the bytes actually start with the PDF signature.
    if not pdf_bytes.startswith(_PDF_SIGNATURE):
        _reject_upload("Uploaded file does not appear to be a valid PDF.")


def _validate_page_count(pdf_bytes: bytes) -> None:
    """KTD9: reject a PDF pypdf cannot open at all, or one whose page count
    (once determined) exceeds the ceiling. A PDF pypdf opens but cannot
    reliably determine a page count for is *not* rejected here -- it
    proceeds to the Azure DI call, the final arbiter of processability.
    The open step is bounded by the KTD11 timeout, since it runs
    synchronously against fully attacker-controlled bytes on the same
    shared threadpool KTD2 accepts as a tradeoff."""

    import pypdf

    def _open_reader() -> Any:
        return pypdf.PdfReader(BytesIO(pdf_bytes))

    # Not a `with` block: ThreadPoolExecutor.__exit__ calls shutdown(wait=True)
    # by default, which would block on a hung worker thread and defeat the
    # timeout below (Python cannot forcibly kill a running thread). Shutting
    # down with wait=False lets this call return promptly regardless of
    # whether the submitted parse ever finishes.
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_open_reader)
    try:
        reader = future.result(timeout=_PDF_PARSE_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        executor.shutdown(wait=False)
        _reject_upload("The uploaded PDF took too long to parse locally.")
    except Exception:
        executor.shutdown(wait=False)
        _reject_upload("The uploaded file could not be opened as a PDF.")
    else:
        executor.shutdown(wait=False)

    try:
        page_count = len(reader.pages)
    except Exception:
        return  # KTD9: page-count ambiguity is not rejected here.

    if page_count > _MAX_UPLOAD_PAGES:
        _reject_upload(
            f"The uploaded PDF exceeds the maximum allowed page count of {_MAX_UPLOAD_PAGES}."
        )


@app.post(_INGESTION_PATH, response_model=ExtractionResult)
def ingest_om(file: UploadFile = File(...)) -> ExtractionResult:
    _validate_content_type(file)

    pdf_bytes = _read_upload_bytes(file, max_bytes=_MAX_UPLOAD_BYTES)
    _validate_pdf_signature(pdf_bytes)
    _validate_page_count(pdf_bytes)

    try:
        return extract_om(pdf_bytes)
    except ExtractionConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None
    except ExtractionProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from None


# =============================================================================
# Detailed Operating Model V2.1 Gate 12 -- Detailed OM ingestion.
#
# A dedicated path (Option B) reusing the exact same upload-guard helpers
# (content-type/signature/size/page-count) as the Quick route above, but
# delegating to ``extract_detailed_om`` -- the Detailed counterpart
# extraction/classification pipeline, distinct from Quick's. Returns
# proposed Detailed field candidates only -- never an ``OperatingProjection``
# or ``DetailedAcquisitionResults``; a provider failure maps to the same
# status codes as the Quick route (503 not configured, 502 provider error).
# =============================================================================


@app.post(_DETAILED_INGESTION_PATH, response_model=DetailedExtractionResult)
def ingest_detailed_om(file: UploadFile = File(...)) -> DetailedExtractionResult:
    _validate_content_type(file)

    pdf_bytes = _read_upload_bytes(file, max_bytes=_MAX_UPLOAD_BYTES)
    _validate_pdf_signature(pdf_bytes)
    _validate_page_count(pdf_bytes)

    try:
        return extract_detailed_om(pdf_bytes)
    except ExtractionConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None
    except ExtractionProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from None


# =============================================================================
# Phase 10B -- Excel ingestion (web upload)
#
# Reuses the exact same deterministic workbook reader the CLI has always
# used (``read_acquisition_inputs_from_bytes_with_report``, sharing its
# parsing/validation implementation with the path-based
# ``read_acquisition_inputs``/``read_acquisition_inputs_with_report``) --
# this endpoint performs no workbook parsing, financial validation, or
# financial math of its own, and never calls the deterministic engine.
# Unlike ``/ingestion/om``, there is no external provider and no partial/
# candidate result: a workbook is either fully valid (200, the fourteen
# validated inputs plus which V2 Field IDs were defaulted -- Underwriting V2
# Gate 5) or it isn't (422, the same ordered issue list ``/analyze`` already
# returns for a bad payload).
# =============================================================================


def _validate_xlsx_filename(file: UploadFile) -> None:
    filename = file.filename or ""
    if not filename.casefold().endswith(".xlsx"):
        _reject_upload("Uploaded file must be a .xlsx workbook.")


def _validate_xlsx_signature(data: bytes) -> None:
    # The client-supplied filename is spoofable (KTD9); this confirms the
    # bytes actually start with the .xlsx (zip/OOXML) signature.
    if not data.startswith(_XLSX_SIGNATURE):
        _reject_upload("Uploaded file does not appear to be a valid .xlsx workbook.")


@app.post(_EXCEL_INGESTION_PATH, response_model=ExcelIntakeReport)
def ingest_excel(file: UploadFile = File(...)) -> ExcelIntakeReport:
    _validate_xlsx_filename(file)

    workbook_bytes = _read_upload_bytes(file, max_bytes=_MAX_EXCEL_UPLOAD_BYTES)
    _validate_xlsx_signature(workbook_bytes)

    try:
        return read_acquisition_inputs_from_bytes_with_report(workbook_bytes)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None


# =============================================================================
# Detailed Operating Model V2.1 Gate 10 -- Detailed Excel ingestion.
#
# A dedicated path (Option B) reusing the exact same upload-guard helpers
# (filename/signature/size) as the Quick route above, but delegating to
# ``read_detailed_excel_intake_from_bytes`` -- ``anchor.detailed_excel_reader``'s
# own deterministic parsing/validation path, distinct from Quick's. Returns
# proposed ``AcquisitionTerms``/``DetailedOperatingInputs`` only -- never an
# ``OperatingProjection`` or ``DetailedAcquisitionResults``; a wrong-mode
# workbook (Quick uploaded here, or this workbook uploaded to
# ``ingest_excel``) is a schema-mismatch ``InputValidationError``, handled
# identically to any other ingestion issue below.
# =============================================================================


@app.post(_DETAILED_EXCEL_INGESTION_PATH, response_model=DetailedExcelIntakeReport)
def ingest_detailed_excel(file: UploadFile = File(...)) -> DetailedExcelIntakeReport:
    _validate_xlsx_filename(file)

    workbook_bytes = _read_upload_bytes(file, max_bytes=_MAX_EXCEL_UPLOAD_BYTES)
    _validate_xlsx_signature(workbook_bytes)

    try:
        return read_detailed_excel_intake_from_bytes(workbook_bytes)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None


# =============================================================================
# Persistence Phase A/C / Detailed Operating Model V2.1 Gate 5b -- Deal
# Library backend foundation
#
# Delegates all storage to ``anchor.deals`` (a thin SQLite adapter -- see
# ``anchor/deals/store.py``). Every create/update route validates the
# submitted assumptions with the exact same shared validators ``/analyze``
# uses *before* they ever reach the store, so a saved deal can never hold a
# value that would fail validation on reopen. Duplicate (Phase C) copies
# only already-validated assumptions via ``anchor.deals`` -- reused as-is --
# and delete removes a row (or row pair, for a Detailed deal) with no
# soft-delete/history. This module performs no financial calculation and
# never calls ``analyze_acquisition``/``analyze_detailed_acquisition`` --
# reanalyzing a reopened or duplicated deal is the existing, unmodified
# ``/analyze`` endpoint, driven by the client the same way a manually typed
# deal is.
#
# ``operating_mode`` (mirroring ``/analyze``'s discriminator exactly): a
# ``"quick"``/absent request sends ``inputs`` and is completely unaffected
# by this gate; a ``"detailed"`` request sends ``terms`` and
# ``detailed_operating_inputs`` instead.
# =============================================================================


def _require_deal_name(payload: dict[str, Any]) -> str:
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A non-empty 'name' is required.",
        )
    return name.strip()


def _optional_deal_context(payload: dict[str, Any]) -> str | None:
    """Owner Return Metrics V3 Gate A4: ``deal_context`` is optional,
    user-authored free text -- never a financial input, so never routed
    through any validator. Absent, ``None``, or whitespace-only all
    normalize to ``None`` (no fabricated default string, and a blank
    textarea never persists as an empty-but-present value); any other
    non-string value is rejected the same way every other malformed field
    already is."""

    raw_deal_context = payload.get("deal_context")
    if raw_deal_context is None:
        return None
    if not isinstance(raw_deal_context, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'deal_context' must be a string when provided.",
        )
    stripped = raw_deal_context.strip()
    return stripped if stripped else None


def _require_snapshot_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    """Owner Return Metrics V3 Gate A6/A7: ``analysis_snapshot``/
    ``ai_snapshot`` are already-computed result shapes (the exact JSON a
    prior ``/analyze``/``/ai/analysis`` response already produced, echoed
    back unchanged) -- this only checks the coarse shape (present and an
    object). Deep validation into the actual ``AcquisitionResults``/
    ``DetailedAcquisitionResults``/``AIAnalysis`` contract shape, and the
    Gate A7 provenance-fingerprint check, both happen in the store layer
    (``SnapshotValidationError``, translated to 422 by the caller), which is
    the single place that already knows each field's type and each deal's
    currently-stored assumptions/context."""

    raw_value = payload.get(key)
    if not isinstance(raw_value, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Request body must include an '{key}' object.",
        )
    return raw_value


def _require_fingerprint_string(payload: dict[str, Any], key: str) -> str:
    """Owner Return Metrics V3 Gate A7: the opaque provenance token a
    dedicated snapshot-write endpoint requires alongside its snapshot --
    obtained by the frontend from ``POST /deals/fingerprint`` and
    transported back unmodified. This only checks the coarse shape (present
    and a non-empty string); the store layer is the sole place that knows
    what value it must actually equal for a given deal."""

    raw_value = payload.get(key)
    if not isinstance(raw_value, str) or not raw_value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Request body must include a non-empty '{key}' string.",
        )
    return raw_value


def _snapshot_validation_error_response(error: SnapshotValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


def _require_operating_mode(payload: dict[str, Any]) -> OperatingMode:
    raw_operating_mode = payload.get("operating_mode", OperatingMode.QUICK.value)
    try:
        return OperatingMode(raw_operating_mode)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "operating_mode must be one of "
                f"{[member.value for member in OperatingMode]}; "
                f"got {raw_operating_mode!r}."
            ),
        ) from None


def _require_deal_inputs(payload: dict[str, Any]) -> AcquisitionInputs:
    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Request body must include an 'inputs' object.",
        )
    try:
        return validate_acquisition_inputs(raw_inputs)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None


def _require_deal_terms(
    payload: dict[str, Any], *, mode_label: str = "detailed"
) -> AcquisitionTerms:
    """The one shared ``AcquisitionTerms`` gate, used by Detailed and, from
    D5.3, by Lease-Level.

    Both modes deliberately share ``validate_acquisition_terms``: purchase
    price, LTV, amortisation and the rest mean the same thing whichever engine
    consumes them, and a Lease-Level-specific copy would be a second place for
    those rules to drift. ``mode_label`` only names the mode in the
    missing-object message, so Detailed's wording is unchanged.
    """

    raw_terms = payload.get("terms")
    if not isinstance(raw_terms, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A {mode_label!r} operating_mode request must include a 'terms' object.",
        )
    try:
        return validate_acquisition_terms(raw_terms)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None


def _require_deal_detailed_operating_inputs(
    payload: dict[str, Any]
) -> DetailedOperatingInputs:
    raw_detailed_inputs = payload.get("detailed_operating_inputs")
    if not isinstance(raw_detailed_inputs, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "A 'detailed' operating_mode request must include a "
                "'detailed_operating_inputs' object."
            ),
        )
    try:
        return validate_detailed_operating_inputs(raw_detailed_inputs)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None


@app.post("/deals", response_model=Deal)
def create_deal(payload: dict[str, Any] = Body(...)) -> Deal:
    """Owner Return Metrics V3 Gate A7: this route persists assumptions/
    Deal Context only -- it never accepts (and silently ignores, if a
    caller's payload happens to include) ``analysis_snapshot``/
    ``ai_snapshot``. A brand-new deal is created with no cached snapshot; to
    persist a *current, valid* analysis/AI for it (the "first Save of an
    unsaved, already-analyzed deal" flow), call the dedicated,
    provenance-validated ``PUT /deals/{id}/analysis-snapshot``/
    ``PUT /deals/{id}/ai-snapshot`` against the id this returns. See
    ``anchor.deals.store.create_deal``'s docstring."""

    name = _require_deal_name(payload)
    operating_mode = _require_operating_mode(payload)
    deal_context = _optional_deal_context(payload)

    match operating_mode:
        case OperatingMode.QUICK:
            inputs = _require_deal_inputs(payload)
            business_plan = _optional_business_plan(payload)
            return deals_store.create_deal(
                name, inputs, deal_context=deal_context, business_plan=business_plan
            )
        case OperatingMode.DETAILED:
            terms = _require_deal_terms(payload)
            detailed_inputs = _require_deal_detailed_operating_inputs(payload)
            business_plan = _optional_business_plan(payload)
            return deals_store.create_detailed_deal(
                name,
                terms,
                detailed_inputs,
                deal_context=deal_context,
                business_plan=business_plan,
            )
        case OperatingMode.LEASE_LEVEL:
            terms = _require_deal_terms(payload, mode_label="lease_level")
            inputs = _require_lease_level_inputs(payload, also_owned=_DEAL_FIELDS)
            business_plan = _optional_business_plan(payload)
            return deals_store.create_lease_level_deal(
                name,
                terms,
                inputs.property_inputs,
                inputs.operating_inputs,
                inputs.market_leasing,
                inputs.suites,
                inputs.leases,
                deal_context=deal_context,
                business_plan=business_plan,
            )
        case _:
            raise _unsupported_operating_mode(operating_mode, endpoint="POST /deals")


@app.get("/deals", response_model=list[Deal])
def list_deals() -> list[Deal]:
    return deals_store.list_deals()


@app.get("/deals/{deal_id}", response_model=Deal)
def get_deal(deal_id: str) -> Deal:
    try:
        return deals_store.get_deal(deal_id)
    except DealNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from None


@app.put("/deals/{deal_id}", response_model=Deal)
def update_deal(deal_id: str, payload: dict[str, Any] = Body(...)) -> Deal:
    """Owner Return Metrics V3 Gate A7: mirrors ``create_deal``'s
    never-accepts-a-snapshot contract exactly -- this route never touches
    the six cached-snapshot columns at all, so a stale snapshot can never be
    relabeled as valid for freshly-submitted assumptions in the same write
    (the Gate A6 trust boundary this gate closes). Preservation of a still-
    valid analysis snapshot across a Deal-Context-only edit, and
    invalidation of a now-stale one across an assumption edit, both happen
    for free via the unchanged read-time fingerprint check -- see
    ``anchor.deals.store.update_deal``'s docstring."""

    name = _require_deal_name(payload)
    operating_mode = _require_operating_mode(payload)
    deal_context = _optional_deal_context(payload)

    try:
        match operating_mode:
            case OperatingMode.QUICK:
                inputs = _require_deal_inputs(payload)
                business_plan = _optional_business_plan(payload)
                return deals_store.update_deal(
                    deal_id,
                    name,
                    inputs,
                    deal_context=deal_context,
                    business_plan=business_plan,
                )
            case OperatingMode.DETAILED:
                terms = _require_deal_terms(payload)
                detailed_inputs = _require_deal_detailed_operating_inputs(payload)
                business_plan = _optional_business_plan(payload)
                return deals_store.update_detailed_deal(
                    deal_id,
                    name,
                    terms,
                    detailed_inputs,
                    deal_context=deal_context,
                    business_plan=business_plan,
                )
            case OperatingMode.LEASE_LEVEL:
                terms = _require_deal_terms(payload, mode_label="lease_level")
                inputs = _require_lease_level_inputs(payload, also_owned=_DEAL_FIELDS)
                business_plan = _optional_business_plan(payload)
                return deals_store.update_lease_level_deal(
                    deal_id,
                    name,
                    terms,
                    inputs.property_inputs,
                    inputs.operating_inputs,
                    inputs.market_leasing,
                    inputs.suites,
                    inputs.leases,
                    deal_context=deal_context,
                    business_plan=business_plan,
                )
            case _:
                raise _unsupported_operating_mode(
                    operating_mode, endpoint="PUT /deals/{deal_id}"
                )
    except DealNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from None


@app.delete("/deals/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deal(deal_id: str) -> None:
    """P7.2: deleting a Deal inside the hidden Scenario wrapper removes the
    wrapper with it (``anchor.deals.store.delete_deal``). A Deal in a visible
    Investment is refused with 409 rather than orphaned (Section 15.2)."""

    try:
        deals_store.delete_deal(deal_id)
    except DealNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.post("/deals/{deal_id}/duplicate", response_model=Deal)
def duplicate_deal(deal_id: str, payload: dict[str, Any] = Body(default={})) -> Deal:
    name = payload.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'name' must be a non-empty string when provided.",
        )
    try:
        return deals_store.duplicate_deal(deal_id, name=name.strip() if name else None)
    except DealNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from None


# =============================================================================
# Owner Return Metrics V3 Gate A7 -- backend-authoritative provenance lookup
#
# A pure, side-effect-free companion to ``/analyze``/``/ai/analysis``: given
# the same assumptions (and, for the AI fingerprint, Deal Context) a caller
# just analyzed, returns the exact canonical fingerprint(s)
# ``anchor.deals.store`` will independently recompute for those same values
# at snapshot-write time. Validates through the identical shared validators
# ``/analyze`` uses, so the fingerprint returned here is guaranteed to equal
# what the store computes from the same values once persisted -- never a
# parallel or approximate computation. This is how the frontend obtains a
# provenance token to transport back on a snapshot write without ever
# computing (or duplicating) the fingerprint algorithm itself in
# TypeScript; the backend remains the sole authority on what a valid
# fingerprint is.
# =============================================================================


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _FingerprintResponse:
    financial_input_fingerprint: str
    ai_context_fingerprint: str


@app.post("/deals/fingerprint", response_model=_FingerprintResponse)
def deal_fingerprint(payload: dict[str, Any] = Body(...)) -> _FingerprintResponse:
    payload = dict(payload)
    operating_mode = _require_operating_mode(payload)
    deal_context = _optional_deal_context(payload)

    match operating_mode:
        case OperatingMode.QUICK:
            inputs = _require_deal_inputs(payload)
            business_plan = _optional_business_plan(payload)
            financial_input_fingerprint = fingerprint_quick_inputs(
                inputs, business_plan=business_plan
            )
        case OperatingMode.DETAILED:
            terms = _require_deal_terms(payload)
            detailed_inputs = _require_deal_detailed_operating_inputs(payload)
            business_plan = _optional_business_plan(payload)
            financial_input_fingerprint = fingerprint_detailed_inputs(
                terms, detailed_inputs, business_plan=business_plan
            )
        case OperatingMode.LEASE_LEVEL:
            terms = _require_deal_terms(payload, mode_label="lease_level")
            inputs = _require_lease_level_inputs(payload, also_owned=_DEAL_FIELDS)
            business_plan = _optional_business_plan(payload)
            financial_input_fingerprint = fingerprint_lease_level_inputs(
                terms,
                inputs.property_inputs,
                inputs.suites,
                inputs.leases,
                market_leasing=inputs.market_leasing,
                operating_inputs=inputs.operating_inputs,
                business_plan=business_plan,
            )
        case _:
            raise _unsupported_operating_mode(
                operating_mode, endpoint="POST /deals/fingerprint"
            )

    ai_context_fingerprint = fingerprint_ai(
        analysis_fingerprint=financial_input_fingerprint, deal_context=deal_context
    )
    return _FingerprintResponse(
        financial_input_fingerprint=financial_input_fingerprint,
        ai_context_fingerprint=ai_context_fingerprint,
    )


# =============================================================================
# Owner Return Metrics V3 Gate A6 / Gate A7 -- provenance-validated snapshot
# writes
#
# Two narrow endpoints, each updating exactly one cached snapshot column
# and nothing else (never ``name``/assumptions/``deal_context``/the other
# snapshot/``updated_at``) -- the write path for "Analyze/Generate AI
# Analysis succeeded" (background cache refresh on an already-saved, not-
# dirty deal; the deliberate first-Save-of-an-unsaved-deal path; and
# ``duplicate_deal``'s copy). Gate A7: each also now requires the caller to
# supply the provenance fingerprint the snapshot was produced under
# (obtained from ``POST /deals/fingerprint`` above) -- the store layer
# independently verifies it against the deal's own currently-stored
# assumptions/context and rejects the write (422) on any mismatch. See
# ``anchor.deals.store.update_analysis_snapshot``/``update_ai_snapshot``.
# =============================================================================


@app.put("/deals/{deal_id}/analysis-snapshot", response_model=Deal)
def update_deal_analysis_snapshot(deal_id: str, payload: dict[str, Any] = Body(...)) -> Deal:
    raw_snapshot = _require_snapshot_dict(payload, "analysis_snapshot")
    financial_input_fingerprint = _require_fingerprint_string(payload, "financial_input_fingerprint")
    try:
        return deals_store.update_analysis_snapshot(
            deal_id, raw_snapshot, financial_input_fingerprint=financial_input_fingerprint
        )
    except DealNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from None
    except SnapshotValidationError as error:
        raise _snapshot_validation_error_response(error) from None


@app.put("/deals/{deal_id}/ai-snapshot", response_model=Deal)
def update_deal_ai_snapshot(deal_id: str, payload: dict[str, Any] = Body(...)) -> Deal:
    raw_snapshot = _require_snapshot_dict(payload, "ai_snapshot")
    ai_context_fingerprint = _require_fingerprint_string(payload, "ai_context_fingerprint")
    try:
        return deals_store.update_ai_snapshot(
            deal_id, raw_snapshot, ai_context_fingerprint=ai_context_fingerprint
        )
    except DealNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from None
    except SnapshotValidationError as error:
        raise _snapshot_validation_error_response(error) from None


# =============================================================================
# Sprint D5.8A -- provenance-validated sensitivity-snapshot writes
#
# Two narrow endpoints, mirroring ``PUT /deals/{id}/ai-snapshot`` exactly: each
# updates one persisted derived-analysis row and nothing else -- never the
# assumptions, the name, Deal Context, the AI snapshot, the *other* sensitivity
# snapshot, or the deal's save timestamp -- and each requires the provenance
# fingerprint the run was performed under, which the store layer independently
# verifies against the deal's own currently-stored assumptions and rejects (422)
# on any mismatch.
#
# One endpoint per analysis kind, not one per UI component: the two exist because
# the two snapshots are genuinely independent state (running one must never
# erase the other), which is the same reason they are separate rows.
# =============================================================================


@app.put("/deals/{deal_id}/sensitivity-snapshot/one-way", response_model=Deal)
def update_deal_one_way_sensitivity_snapshot(
    deal_id: str, payload: dict[str, Any] = Body(...)
) -> Deal:
    raw_snapshot = _require_snapshot_dict(payload, "sensitivity_snapshot")
    financial_input_fingerprint = _require_fingerprint_string(
        payload, "financial_input_fingerprint"
    )
    try:
        return deals_store.update_one_way_sensitivity_snapshot(
            deal_id,
            raw_snapshot,
            financial_input_fingerprint=financial_input_fingerprint,
        )
    except DealNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from None
    except UnsupportedOperatingModeError as error:
        raise _unsupported_operating_mode(
            error.operating_mode,
            endpoint="PUT /deals/{deal_id}/sensitivity-snapshot/one-way",
        ) from None
    except SnapshotValidationError as error:
        raise _snapshot_validation_error_response(error) from None


@app.put("/deals/{deal_id}/sensitivity-snapshot/two-way", response_model=Deal)
def update_deal_two_way_sensitivity_snapshot(
    deal_id: str, payload: dict[str, Any] = Body(...)
) -> Deal:
    raw_snapshot = _require_snapshot_dict(payload, "sensitivity_snapshot")
    financial_input_fingerprint = _require_fingerprint_string(
        payload, "financial_input_fingerprint"
    )
    try:
        return deals_store.update_two_way_sensitivity_snapshot(
            deal_id,
            raw_snapshot,
            financial_input_fingerprint=financial_input_fingerprint,
        )
    except DealNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from None
    except UnsupportedOperatingModeError as error:
        raise _unsupported_operating_mode(
            error.operating_mode,
            endpoint="PUT /deals/{deal_id}/sensitivity-snapshot/two-way",
        ) from None
    except SnapshotValidationError as error:
        raise _snapshot_validation_error_response(error) from None


# =============================================================================
# Phase 7 Gate P7.2 -- the Investment shell and persisted Scenarios
#
# The backend P7.3 builds the Scenario UI on. Every route delegates: storage and
# the lifecycle to ``anchor.deals.store``, and the resolved-input fingerprint and
# variant analysis to ``anchor.deals.variants``, which resolve through the P7.1
# Scenario engine and run the existing D6 entry points. This module computes
# nothing and adds no second analysis pathway.
#
# **Opt-in only (Q4).** ``POST /deals/{deal_id}/scenarios`` is the one route that
# can materialize an Investment -- the hidden one-unit wrapper, created with the
# Deal's first Scenario in one transaction. Every GET is read-only and never
# creates a row, and no route here touches a Deal's own inputs or snapshots.
#
# **Ownership is proven, never assumed.** A Scenario is addressed through the
# Investment that owns it; an id from another Investment is a 404. Every
# override names its unit, and the P7.1 validator refuses any unit outside the
# Investment (``unit_not_in_variant``).
#
# **The request parser is structural only.** It turns the body into the P7.1
# contract without judging it: target and operation tokens become members when
# they are members and stay raw otherwise, so the P7.1 validator -- the one
# authority -- reports every contract problem, in its own deterministic order,
# as a structured 422.
# =============================================================================

#: The keys a Scenario body may carry, and the keys of one override. Literal
#: tuples, so an unknown key is always refused rather than silently ignored.
_SCENARIO_FIELDS = ("name", "description", "overrides")
_SCENARIO_OVERRIDE_FIELDS = ("unit_id", "target", "operation", "value")


def _scenario_token(token_type: type[ScenarioTarget] | type[ScenarioOperation], raw: Any) -> Any:
    """A member of ``token_type`` when ``raw`` is one of its tokens; otherwise
    ``raw`` itself, left for the P7.1 validator to refuse by name. A plain
    lookup rather than a caught enum error, so the API gains no blanket value
    error handler (``tests/test_d5_5c_recovery_validation_mutations.py``)."""

    if isinstance(raw, str):
        for member in token_type:
            if member.value == raw:
                return member
    return raw


def _scenario_request(payload: dict[str, Any]) -> tuple[Any, Any, tuple[ScenarioOverride, ...]]:
    """``(name, description, overrides)`` from a Scenario body, or a
    structural 422. No contract rule is applied here."""

    unknown = sorted(key for key in payload if key not in _SCENARIO_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Unknown scenario field(s): {', '.join(unknown)}. A scenario body holds "
                "only 'name', 'description' and 'overrides'."
            ),
        )
    raw_overrides = payload.get("overrides", [])
    if not isinstance(raw_overrides, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'overrides' must be an array of override objects.",
        )
    overrides: list[ScenarioOverride] = []
    for index, raw in enumerate(raw_overrides):
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"overrides[{index}] must be an object.",
            )
        missing = [key for key in _SCENARIO_OVERRIDE_FIELDS if key not in raw]
        extra = sorted(key for key in raw if key not in _SCENARIO_OVERRIDE_FIELDS)
        if missing or extra:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"overrides[{index}] must hold exactly 'unit_id', 'target', "
                    f"'operation' and 'value' (missing: {missing}; unknown: {extra})."
                ),
            )
        overrides.append(
            ScenarioOverride(
                unit_id=raw["unit_id"],
                target=_scenario_token(ScenarioTarget, raw["target"]),
                operation=_scenario_token(ScenarioOperation, raw["operation"]),
                value=raw["value"],
            )
        )
    return payload.get("name"), payload.get("description"), tuple(overrides)


def _scenario_validation_error_response(error: ScenarioValidationError) -> HTTPException:
    """An invalid Scenario or variant as a structured 422: the P7.1 issues, in
    the P7.1 validator's own order, each with its stage and stable code."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "stage": issue.stage.value,
                "code": issue.code.value,
                "message": issue.message,
                "target": None if issue.target is None else issue.target.value,
                "unit_id": issue.unit_id,
                "field": issue.field,
                "source_code": issue.source_code,
            }
            for issue in error.issues
        ],
    )


def _not_found(error: LookupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _investment_structure_conflict(error: InvestmentStructureError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _DealScenarios:
    """A Deal's Scenarios and the Investment that owns them -- ``None`` and no
    Scenarios for a standalone Deal."""

    deal_id: str
    investment_id: str | None
    scenarios: tuple[InvestmentScenario, ...]


@app.post("/deals/{deal_id}/scenarios", response_model=InvestmentScenario)
def create_deal_scenario(deal_id: str, payload: dict[str, Any] = Body(...)) -> InvestmentScenario:
    """Create a Scenario for the Deal ``deal_id``. Its first Scenario
    materializes the hidden one-unit Investment in the same transaction; later
    ones reuse it. An invalid Scenario leaves nothing behind."""

    name, description, overrides = _scenario_request(payload)
    try:
        return investment_store.create_scenario_for_deal(
            deal_id, name=name, description=description, overrides=overrides
        )
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None


@app.get("/deals/{deal_id}/scenarios", response_model=_DealScenarios)
def list_scenarios_of_deal(deal_id: str) -> _DealScenarios:
    """Read-only: a standalone Deal reports no Investment and no Scenarios,
    and gains neither."""

    try:
        investment_id, scenarios = investment_store.list_deal_scenarios(deal_id)
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    return _DealScenarios(
        deal_id=deal_id, investment_id=investment_id, scenarios=tuple(scenarios)
    )


@app.get("/investments/{investment_id}", response_model=Investment)
def read_investment(investment_id: str) -> Investment:
    try:
        return investment_store.get_investment(investment_id)
    except InvestmentNotFoundError as error:
        raise _not_found(error) from None


@app.delete("/investments/{investment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_investment(investment_id: str) -> None:
    """Delete the hidden wrapper and everything it owns; its Deal is released,
    unchanged (Q3)."""

    try:
        investment_store.delete_investment(investment_id)
    except InvestmentNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.get("/investments/{investment_id}/scenarios", response_model=list[InvestmentScenario])
def list_investment_scenarios(investment_id: str) -> list[InvestmentScenario]:
    try:
        return investment_store.list_scenarios(investment_id)
    except InvestmentNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.post("/investments/{investment_id}/scenarios", response_model=InvestmentScenario)
def create_investment_scenario(
    investment_id: str, payload: dict[str, Any] = Body(...)
) -> InvestmentScenario:
    name, description, overrides = _scenario_request(payload)
    try:
        return investment_store.create_scenario(
            investment_id, name=name, description=description, overrides=overrides
        )
    except InvestmentNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None


@app.get(
    "/investments/{investment_id}/scenarios/{scenario_id}", response_model=InvestmentScenario
)
def read_investment_scenario(investment_id: str, scenario_id: str) -> InvestmentScenario:
    try:
        return investment_store.get_scenario(investment_id, scenario_id)
    except (InvestmentNotFoundError, ScenarioNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.put(
    "/investments/{investment_id}/scenarios/{scenario_id}", response_model=InvestmentScenario
)
def update_investment_scenario(
    investment_id: str, scenario_id: str, payload: dict[str, Any] = Body(...)
) -> InvestmentScenario:
    """Replace the Scenario's name, description and whole override set; its
    id is kept."""

    name, description, overrides = _scenario_request(payload)
    try:
        return investment_store.update_scenario(
            investment_id, scenario_id, name=name, description=description, overrides=overrides
        )
    except (InvestmentNotFoundError, ScenarioNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None


@app.delete(
    "/investments/{investment_id}/scenarios/{scenario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_investment_scenario(investment_id: str, scenario_id: str) -> None:
    """Delete the Scenario. Deleting the wrapper's last Scenario removes the
    wrapper too, returning the Deal to a plain standalone Deal."""

    try:
        investment_store.delete_scenario(investment_id, scenario_id)
    except (InvestmentNotFoundError, ScenarioNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.get(
    "/investments/{investment_id}/scenarios/{scenario_id}/fingerprint",
    response_model=ScenarioVariantFingerprint,
)
def investment_scenario_fingerprint(
    investment_id: str, scenario_id: str
) -> ScenarioVariantFingerprint:
    """The resolved-input financial fingerprint of the Scenario's variant, from
    the one authority in ``anchor.deals.variants``. Read-only."""

    try:
        return scenario_variant_fingerprint(investment_id, scenario_id)
    except (InvestmentNotFoundError, ScenarioNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None


@app.post(
    "/investments/{investment_id}/scenarios/{scenario_id}/analysis",
    response_model=ScenarioVariantAnalysis,
)
def analyze_investment_scenario(
    investment_id: str, scenario_id: str
) -> ScenarioVariantAnalysis:
    """Analyse the Scenario's variant through the existing deterministic
    pipeline. ``cache_status`` reports whether a current Quick or Detailed
    cached result was served (``hit``), the result was computed and cached
    (``miss``), or a Lease-Level result was recomputed without any cache
    (``bypassed``)."""

    try:
        return analyze_scenario_variant(investment_id, scenario_id)
    except (InvestmentNotFoundError, ScenarioNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None


# =============================================================================
# Phase 7 Gate P7.3 -- the read-only Scenario target catalog
#
# The Scenario editor must know which targets the current operating mode
# offers, which operations each one allows, and the units a value is stated
# in. The P7.1 registry is the one authority for all three, so this route only
# projects it:
# - every entry is read from the P7.1 registry, in its declaration order;
# - each whitelist is listed in ``ScenarioOperation`` declaration order;
# - ``units`` is the registry's own text, verbatim.
#
# Nothing is added, computed, persisted or re-decided here, and the route opens
# no database. Without it the UI would need a target list of its own, which
# could drift from the registry.
# =============================================================================


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _ScenarioTargetEntry:
    """One registry target, as one operating mode offers it."""

    target: str
    allowed_operations: tuple[str, ...]
    units: str


@app.get("/scenario-targets", response_model=dict[str, list[_ScenarioTargetEntry]])
def scenario_target_catalog() -> dict[str, list[_ScenarioTargetEntry]]:
    """Each operating mode's Scenario targets, projected from the registry.
    Read-only: it touches no database and changes no Scenario semantics."""

    return {
        mode.value: [
            _ScenarioTargetEntry(
                target=spec.target.value,
                allowed_operations=tuple(
                    operation.value
                    for operation in ScenarioOperation
                    if operation in spec.allowed_operations
                ),
                units=spec.units,
            )
            for spec in SCENARIO_TARGET_REGISTRY.values()
            if mode in spec.modes
        ]
        for mode in OperatingMode
    }


# =============================================================================
# Phase 7 Gate P7.4 -- persisted Strategies and every variant of an Investment
#
# The backend P7.5 builds the Strategy x Scenario matrix on. Every route
# delegates: storage and the lifecycle to ``anchor.deals.store``, and variant
# inspection, fingerprints and analysis to ``anchor.deals.variants``, which
# resolve Base -> Strategy -> Scenario through ``anchor.analysis.strategy`` and
# the P7.1 Scenario engine and run the existing D6 entry points. This module
# computes nothing and adds no second analysis pathway.
#
# **Opt-in only (Q4).** ``POST /deals/{deal_id}/strategies`` materializes the
# hidden one-unit wrapper with a Deal's first Strategy -- or reuses the one its
# Scenarios already created. Every GET is read-only and never creates a row.
#
# **A variant is addressed by its identity (Section 7.5):**
# ``/investments/{investment_id}/variants/{strategy_id}/{scenario_id}``, where
# either key may be the reserved ``base``. Ownership is proven, never assumed:
# a Strategy or Scenario id from another Investment is a 404.
#
# **The request parser is structural only.** A known domain's content becomes
# its contract, with a missing field passed on as ``None``; an unknown domain
# carries no content. The P7.4 validator -- the one authority -- then reports
# every contract problem, incomplete domains included, as a structured 422. A
# Business Plan overlay is parsed by the D6 parser, as a Deal's plan is.
# =============================================================================

#: The keys a Strategy body may carry, one overlay, and one operating outcome.
#: Literal tuples, so an unknown key is always refused rather than ignored. A
#: whole-domain overlay's content keys are its contract's own fields
#: (``STRATEGY_DOMAIN_FIELDS``), never restated here.
_STRATEGY_FIELDS = ("name", "description", "overlays", "root_overlays")
_STRATEGY_OVERLAY_FIELDS = ("unit_id", "domain", "content")
_OPERATING_OUTCOME_CONTENT_FIELDS = ("outcomes",)
_OPERATING_OUTCOME_FIELDS = ("target", "operation", "value")


def _structural_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _strategy_domain_token(raw: Any) -> Any:
    """The ``StrategyDomain`` member ``raw`` names, or ``raw`` itself for the
    P7.4 validator to refuse by name -- a plain lookup, never a caught enum
    error (``tests/test_d5_5c_recovery_validation_mutations.py``)."""

    if isinstance(raw, str):
        for member in StrategyDomain:
            if member.value == raw:
                return member
    return raw


def _content_object(raw: Any, allowed: tuple[str, ...], where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _structural_error(f"{where} must be an object.")
    unknown = sorted(key for key in raw if key not in allowed)
    if unknown:
        raise _structural_error(
            f"{where} holds unknown field(s): {', '.join(unknown)}. It holds only "
            f"{', '.join(allowed)}."
        )
    return raw


def _strategy_business_plan_error(
    error: BusinessPlanValidationError, where: str
) -> HTTPException:
    """A refused Business Plan overlay, in the D6 ``code``/``path``/``message``
    shape, with each path rooted at the overlay's content."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "path": where if issue.path == _BUSINESS_PLAN_KEY else f"{where}.{issue.path}",
                "message": issue.message,
            }
            for issue in error.result.issues
        ],
    )


def _operating_outcome_content(raw: Any, where: str) -> OperatingOutcomeSet:
    body = _content_object(raw, _OPERATING_OUTCOME_CONTENT_FIELDS, where)
    raw_outcomes = body.get("outcomes", [])
    if not isinstance(raw_outcomes, list):
        raise _structural_error(f"{where}.outcomes must be an array of outcome objects.")
    outcomes: list[OperatingOutcome] = []
    for index, raw_outcome in enumerate(raw_outcomes):
        item = f"{where}.outcomes[{index}]"
        if not isinstance(raw_outcome, dict):
            raise _structural_error(f"{item} must be an object.")
        missing = [key for key in _OPERATING_OUTCOME_FIELDS if key not in raw_outcome]
        extra = sorted(key for key in raw_outcome if key not in _OPERATING_OUTCOME_FIELDS)
        if missing or extra:
            raise _structural_error(
                f"{item} must hold exactly 'target', 'operation' and 'value' "
                f"(missing: {missing}; unknown: {extra})."
            )
        outcomes.append(
            OperatingOutcome(
                target=_scenario_token(ScenarioTarget, raw_outcome["target"]),
                operation=_scenario_token(ScenarioOperation, raw_outcome["operation"]),
                value=raw_outcome["value"],
            )
        )
    return OperatingOutcomeSet(outcomes=tuple(outcomes))


def _stated(body: dict[str, Any], field: str) -> Any:
    """A whole-domain field exactly as sent, or ``None`` when it was not sent --
    passed on untouched for the P7.4 validator to judge (an absent field is an
    incomplete domain), never filled from anywhere else."""

    return body.get(field)


def _strategy_content(domain: Any, raw: Any, where: str) -> Any:
    """``domain``'s content contract from its wire object, structurally. A
    whole-domain field that is absent arrives as ``None``, which the validator
    refuses as an incomplete domain; nothing is taken from Base."""

    match domain:
        case StrategyDomain.ACQUISITION:
            body = _content_object(raw, STRATEGY_DOMAIN_FIELDS[domain], where)
            return AcquisitionChoice(
                purchase_price=_stated(body, "purchase_price"),
                acquisition_cost_pct=_stated(body, "acquisition_cost_pct"),
            )
        case StrategyDomain.FINANCING:
            body = _content_object(raw, STRATEGY_DOMAIN_FIELDS[domain], where)
            return FinancingChoice(
                ltv=_stated(body, "ltv"),
                interest_rate=_stated(body, "interest_rate"),
                amortization=_stated(body, "amortization"),
                io_period=_stated(body, "io_period"),
                financing_fee_pct=_stated(body, "financing_fee_pct"),
            )
        case StrategyDomain.BUSINESS_PLAN:
            try:
                return parse_business_plan(raw)
            except BusinessPlanValidationError as error:
                raise _strategy_business_plan_error(error, where) from None
        case StrategyDomain.OPERATING_OUTCOME:
            return _operating_outcome_content(raw, where)
        case StrategyDomain.DISPOSITION:
            body = _content_object(raw, STRATEGY_DOMAIN_FIELDS[domain], where)
            return DispositionChoice(hold_period=_stated(body, "hold_period"))
        case _:
            return None


def _strategy_request(
    payload: dict[str, Any],
) -> tuple[Any, Any, tuple[StrategyOverlay, ...], tuple[InvestmentStrategyOverlay, ...]]:
    """``(name, description, overlays, root_overlays)`` from a Strategy body, or
    a structural 422. No contract rule is applied here.

    ``root_overlays`` (P7.8B) carries the Strategy's Investment-root
    replacements. Omitting it is inheriting the Base Capital Structure; stating
    one whose structure has no position is the explicit "no structured
    capital"."""

    unknown = sorted(key for key in payload if key not in _STRATEGY_FIELDS)
    if unknown:
        raise _structural_error(
            f"Unknown strategy field(s): {', '.join(unknown)}. A strategy body holds "
            "only 'name', 'description', 'overlays' and 'root_overlays'."
        )
    raw_overlays = payload.get("overlays", [])
    if not isinstance(raw_overlays, list):
        raise _structural_error("'overlays' must be an array of overlay objects.")
    overlays: list[StrategyOverlay] = []
    for index, raw in enumerate(raw_overlays):
        where = f"overlays[{index}]"
        if not isinstance(raw, dict):
            raise _structural_error(f"{where} must be an object.")
        missing = [key for key in _STRATEGY_OVERLAY_FIELDS if key not in raw]
        extra = sorted(key for key in raw if key not in _STRATEGY_OVERLAY_FIELDS)
        if missing or extra:
            raise _structural_error(
                f"{where} must hold exactly 'unit_id', 'domain' and 'content' "
                f"(missing: {missing}; unknown: {extra})."
            )
        domain = _strategy_domain_token(raw["domain"])
        overlays.append(
            StrategyOverlay(
                unit_id=raw["unit_id"],
                domain=domain,
                content=_strategy_content(domain, raw["content"], f"{where}.content"),
            )
        )
    return (
        payload.get("name"),
        payload.get("description"),
        tuple(overlays),
        _strategy_root_overlays(payload),
    )


def _strategy_validation_error_response(error: StrategyValidationError) -> HTTPException:
    """An invalid Strategy or Strategy variant as a structured 422: the P7.4
    issues, in the P7.4 validator's own order, each with its stage and stable
    code."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "stage": issue.stage.value,
                "code": issue.code.value,
                "message": issue.message,
                "domain": None if issue.domain is None else issue.domain.value,
                "unit_id": issue.unit_id,
                "field": issue.field,
                "target": None if issue.target is None else issue.target.value,
                "source_code": issue.source_code,
            }
            for issue in error.issues
        ],
    )


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _DealStrategies:
    """A Deal's Strategies and the Investment that owns them -- ``None`` and no
    Strategies for a standalone Deal."""

    deal_id: str
    investment_id: str | None
    strategies: tuple[InvestmentStrategy, ...]


#: The serializers the Strategy responses shape by hand (P7.8B). A Strategy's
#: own Capital Structure is a typed union, which pydantic would serialize
#: without its ``kind`` discriminator, so those responses are built here
#: instead: the same pydantic dump for everything that existed before -- so a
#: Strategy that states no structure answers byte for byte as it always did --
#: and the explicit ``_wire`` encoding for the structure itself.
_STRATEGY_RESPONSE = TypeAdapter(InvestmentStrategy)
_DEAL_STRATEGIES_RESPONSE = TypeAdapter(_DealStrategies)


def _strategy_payload(record: InvestmentStrategy) -> dict[str, Any]:
    """One persisted Strategy on the wire.

    ``root_overlays`` appears **only when the Strategy states one**: an empty
    key would make "inherits the Base Capital Structure" and "this gate added a
    field" indistinguishable to a reader, and would change every existing
    Strategy response for a Strategy that has no structured capital at all."""

    root_overlays = record.strategy.root_overlays
    payload = _STRATEGY_RESPONSE.dump_python(
        dataclasses.replace(
            record, strategy=dataclasses.replace(record.strategy, root_overlays=())
        ),
        mode="json",
    )
    payload["strategy"].pop("root_overlays", None)
    if root_overlays:
        payload["strategy"]["root_overlays"] = [
            {"domain": overlay.domain.value, "content": _root_overlay_wire(overlay.content)}
            for overlay in root_overlays
        ]
    return payload


def _deal_strategies_payload(
    deal_id: str, investment_id: str | None, strategies: tuple[InvestmentStrategy, ...]
) -> dict[str, Any]:
    payload = _DEAL_STRATEGIES_RESPONSE.dump_python(
        _DealStrategies(deal_id=deal_id, investment_id=investment_id, strategies=()),
        mode="json",
    )
    payload["strategies"] = [_strategy_payload(record) for record in strategies]
    return payload


@app.post("/deals/{deal_id}/strategies", response_model=None)
def create_deal_strategy(deal_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create a Strategy for the Deal ``deal_id``. A Deal with no Investment
    gains the hidden one-unit wrapper in the same transaction; a Deal whose
    Scenarios already created one reuses it. An invalid Strategy leaves nothing
    behind."""

    name, description, overlays, root_overlays = _strategy_request(payload)
    try:
        return _strategy_payload(
            investment_store.create_strategy_for_deal(
                deal_id,
                name=name,
                description=description,
                overlays=overlays,
                root_overlays=root_overlays,
            )
        )
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except PositionIdentityConflictError as error:
        raise _position_identity_conflict_response(error) from None


@app.get("/deals/{deal_id}/strategies", response_model=None)
def list_strategies_of_deal(deal_id: str) -> dict[str, Any]:
    """Read-only: a standalone Deal reports no Investment and no Strategies,
    and gains neither."""

    try:
        investment_id, strategies = investment_store.list_deal_strategies(deal_id)
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    return _deal_strategies_payload(deal_id, investment_id, tuple(strategies))


@app.get("/investments/{investment_id}/strategies", response_model=None)
def list_investment_strategies(investment_id: str) -> list[dict[str, Any]]:
    try:
        return [_strategy_payload(record) for record in investment_store.list_strategies(investment_id)]
    except InvestmentNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.post("/investments/{investment_id}/strategies", response_model=None)
def create_investment_strategy(
    investment_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    name, description, overlays, root_overlays = _strategy_request(payload)
    try:
        return _strategy_payload(
            investment_store.create_strategy(
                investment_id,
                name=name,
                description=description,
                overlays=overlays,
                root_overlays=root_overlays,
            )
        )
    except InvestmentNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except PositionIdentityConflictError as error:
        raise _position_identity_conflict_response(error) from None


@app.get("/investments/{investment_id}/strategies/{strategy_id}", response_model=None)
def read_investment_strategy(investment_id: str, strategy_id: str) -> dict[str, Any]:
    try:
        return _strategy_payload(investment_store.get_strategy(investment_id, strategy_id))
    except (InvestmentNotFoundError, StrategyNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.put("/investments/{investment_id}/strategies/{strategy_id}", response_model=None)
def update_investment_strategy(
    investment_id: str, strategy_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Replace the Strategy's name, description, whole overlay set and whole
    Investment-root overlay set; its id is kept. Omitting ``root_overlays`` is
    the analyst choosing to inherit the Base Capital Structure again."""

    name, description, overlays, root_overlays = _strategy_request(payload)
    try:
        return _strategy_payload(
            investment_store.update_strategy(
                investment_id,
                strategy_id,
                name=name,
                description=description,
                overlays=overlays,
                root_overlays=root_overlays,
            )
        )
    except (InvestmentNotFoundError, StrategyNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except PositionIdentityConflictError as error:
        raise _position_identity_conflict_response(error) from None


@app.delete(
    "/investments/{investment_id}/strategies/{strategy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_investment_strategy(investment_id: str, strategy_id: str) -> None:
    """Delete the Strategy with its overlays and cached variants. When no
    Strategy and no Scenario is left, the wrapper is removed too and the Deal
    is a plain standalone Deal again."""

    try:
        investment_store.delete_strategy(investment_id, strategy_id)
    except (InvestmentNotFoundError, StrategyNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.get(
    "/investments/{investment_id}/variants/{strategy_id}/{scenario_id}/inputs",
    response_model=VariantInputs,
)
def investment_variant_inputs(
    investment_id: str, strategy_id: str, scenario_id: str
) -> VariantInputs:
    """What exactly the variant runs: the resolved existing contracts, before
    any calculation, with their fingerprint. Read-only."""

    try:
        return inspect_variant_inputs(investment_id, strategy_id, scenario_id)
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None


@app.get(
    "/investments/{investment_id}/variants/{strategy_id}/{scenario_id}/fingerprint",
    response_model=VariantFingerprint,
)
def investment_variant_fingerprint(
    investment_id: str, strategy_id: str, scenario_id: str
) -> VariantFingerprint:
    """The variant's resolved-input financial fingerprint, from the one
    authority in ``anchor.deals.variants``. Read-only."""

    try:
        return variant_fingerprint(investment_id, strategy_id, scenario_id)
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None


@app.post(
    "/investments/{investment_id}/variants/{strategy_id}/{scenario_id}/analysis",
    response_model=VariantAnalysis,
)
def analyze_investment_variant(
    investment_id: str, strategy_id: str, scenario_id: str
) -> VariantAnalysis:
    """Analyse the variant through the existing deterministic pipeline.
    ``cache_status`` reports a current Quick or Detailed cached result served
    (``hit``), a result computed and cached (``miss``), or a result recomputed
    without any cache (``bypassed``): every Lease-Level variant, and Base x
    Base, which is the Deal's own analysis."""

    try:
        return analyze_variant(investment_id, strategy_id, scenario_id)
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None

# =============================================================================
# Phase 7 Gate P7.5 -- the Strategy target catalog and the Decision Matrix
#
# ``GET /strategy-targets`` projects the operating-outcome whitelist
# (``STRATEGY_OUTCOME_TARGETS``) with each target's units taken from the P7.1
# registry, so the Strategy editor never holds a target list or a unit of its
# own. A Strategy outcome is always ``SET``, so no operation is listed. Nothing
# is added, computed, persisted or re-decided, and the route opens no database.
#
# ``POST /investments/{investment_id}/decision-matrix`` is the one matrix
# capability: every Strategy x Scenario variant of the hidden Investment
# through the P7.4 variant authority, and the read-only cross-cell figures
# from ``anchor.decision``. It delegates entirely to
# ``anchor.deals.decision_matrix`` and persists nothing. An invalid variant is
# one cell of a successful response; only a missing row, a structural refusal
# or a concurrent change fails the request.
# =============================================================================


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _StrategyTargetEntry:
    """One operating-outcome target, as one operating mode offers it."""

    target: str
    units: str


@app.get("/strategy-targets", response_model=dict[str, list[_StrategyTargetEntry]])
def strategy_target_catalog() -> dict[str, list[_StrategyTargetEntry]]:
    """Each operating mode's Strategy operating-outcome targets, in whitelist
    order, each with the registry's own units. Read-only."""

    return {
        mode.value: [
            _StrategyTargetEntry(target=target.value, units=SCENARIO_TARGET_REGISTRY[target].units)
            for target in STRATEGY_OUTCOME_TARGETS[mode]
        ]
        for mode in OperatingMode
    }


@app.post("/investments/{investment_id}/decision-matrix", response_model=DecisionMatrixReport)
def analyze_investment_decision_matrix(investment_id: str) -> DecisionMatrixReport:
    """The Strategy x Scenario Decision Matrix of the hidden Investment, derived
    on request and never stored."""

    try:
        return analyze_decision_matrix(investment_id)
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except DecisionMatrixConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None


# =============================================================================
# Phase 7 Gate P7.6 -- the visible Investment
#
# The backend P7.6B builds the Investment workspace on. Every route delegates:
# the lifecycle to ``anchor.deals.store``, the variant pathway (resolution,
# fingerprints and consolidated analysis) to ``anchor.deals.investment_variants``,
# and the matrix to ``anchor.deals.decision_matrix``. This module computes
# nothing and adds no second analysis pathway.
#
# **The hidden one-unit Investment keeps every P7.2-P7.5 route unchanged.** A
# visible Investment's variants and matrix have their own routes, because their
# result is a different contract (``ConsolidatedResults`` beside every Unit's own
# envelope); the P7.4 ``/variants`` routes and the P7.5 matrix route still refuse
# a visible Investment with 409. A visible Investment's Strategies and Scenarios
# use the existing ``/investments/{investment_id}/strategies`` and ``/scenarios``
# routes, validated against its member Units.
#
# **The request parser is structural only.** Unknown keys are refused; tokens
# become members when they are members and stay raw otherwise; the Investment
# validator -- the one authority -- then reports every contract problem, in its
# own deterministic order, as a structured 422. The Investment Business Plan is
# parsed by the D6 parser, exactly as a Deal's plan is.
# =============================================================================

_INVESTMENT_FIELDS = ("name", "transaction_price", "units", "business_plan", "transaction_costs")
_INVESTMENT_DETAILS_FIELDS = ("name", "transaction_price", "business_plan", "transaction_costs")
_INVESTMENT_UNIT_FIELDS = ("unit_id", "label", "unit_kind", "acquisition_month", "disposition_month")
_INVESTMENT_ADD_UNIT_FIELDS = (*_INVESTMENT_UNIT_FIELDS, "transaction_price")
_INVESTMENT_UNIT_DISPLAY_FIELDS = ("label", "unit_kind", "ordinal")
_TRANSACTION_COST_FIELDS = ("cost_id", "description", "category", "amount", "model_month")


def _member_token(token_type: type[UnitKind] | type[TransactionCostCategory], raw: Any) -> Any:
    """A member of ``token_type`` when ``raw`` is one of its tokens; otherwise
    ``raw`` itself, left for the Investment validator to refuse by name. A plain
    lookup, never a caught enum error."""

    if isinstance(raw, str):
        for member in token_type:
            if member.value == raw:
                return member
    return raw


def _stripped(raw: Any) -> Any:
    return raw.strip() if isinstance(raw, str) else raw


def _require_request_keys(body: dict[str, Any], keys: tuple[str, ...], where: str) -> None:
    missing = [key for key in keys if key not in body]
    if missing:
        raise _structural_error(f"{where} must hold {', '.join(keys)} (missing: {', '.join(missing)}).")


def _unit_membership_request(
    raw: Any, ordinal: int, where: str, allowed: tuple[str, ...] = _INVESTMENT_UNIT_FIELDS
) -> InvestmentUnitMembership:
    body = _content_object(raw, allowed, where)
    _require_request_keys(body, ("unit_id",), where)
    return InvestmentUnitMembership(
        unit_id=body["unit_id"],
        ordinal=ordinal,
        label=_stripped(body.get("label")),
        unit_kind=_member_token(UnitKind, body.get("unit_kind")),
        acquisition_month=body.get("acquisition_month", 0),
        disposition_month=body.get("disposition_month"),
    )


def _transaction_costs_request(raw: Any) -> tuple[InvestmentTransactionCost, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _structural_error("'transaction_costs' must be an array of transaction cost objects.")
    costs: list[InvestmentTransactionCost] = []
    for index, entry in enumerate(raw):
        body = _content_object(entry, _TRANSACTION_COST_FIELDS, f"transaction_costs[{index}]")
        # Raw values, a missing one as ``None``: the Investment validator judges
        # each and reports it by name.
        fields: dict[str, Any] = {key: body.get(key) for key in _TRANSACTION_COST_FIELDS}
        costs.append(
            InvestmentTransactionCost(
                cost_id=fields["cost_id"],
                description=_stripped(fields["description"]),
                category=_member_token(TransactionCostCategory, fields["category"]),
                amount=fields["amount"],
                model_month=body.get("model_month", 0),
            )
        )
    return tuple(costs)


def _investment_business_plan_request(raw: Any) -> BusinessPlan:
    try:
        return parse_business_plan(raw)
    except BusinessPlanValidationError as error:
        raise _business_plan_validation_error_response(error) from None


def _investment_request(payload: dict[str, Any], *, with_units: bool) -> dict[str, Any]:
    """The contract fields of a create, promote or details body, or a
    structural 422. No contract rule is applied here."""

    allowed = _INVESTMENT_FIELDS if with_units else _INVESTMENT_DETAILS_FIELDS
    body = _content_object(payload, allowed, "The request body")
    _require_request_keys(body, ("name", "transaction_price", "units") if with_units else allowed, "The request body")
    request: dict[str, Any] = {
        "name": _stripped(body["name"]),
        "transaction_price": body["transaction_price"],
        "business_plan": _investment_business_plan_request(body.get("business_plan")),
        "transaction_costs": _transaction_costs_request(body.get("transaction_costs")),
    }
    if with_units:
        raw_units = body["units"]
        if not isinstance(raw_units, list):
            raise _structural_error("'units' must be an array of unit objects.")
        request["units"] = tuple(
            _unit_membership_request(raw, index, f"units[{index}]") for index, raw in enumerate(raw_units)
        )
    return request


def _investment_validation_error_response(error: InvestmentValidationError) -> HTTPException:
    """An invalid Investment as a structured 422: the Investment issues, in the
    validator's own order, each with its stable code and the Unit it
    concerns."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "message": issue.message,
                "unit_id": issue.unit_id,
                "field": issue.field,
                "source_code": issue.source_code,
            }
            for issue in error.issues
        ],
    )


def _investment_variant_validation_error_response(
    error: InvestmentVariantValidationError,
) -> HTTPException:
    """An invalid visible Investment variant as a structured 422: every issue,
    with the layer that found it and the Unit it concerns."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "source": issue.source.value,
                "code": issue.code,
                "message": issue.message,
                "unit_id": issue.unit_id,
                "field": issue.field,
            }
            for issue in error.issues
        ],
    )


@app.get("/investments", response_model=list[VisibleInvestment])
def list_visible_investments() -> list[VisibleInvestment]:
    """Every visible Investment. Hidden one-unit wrappers are never listed."""

    return investment_store.list_visible_investments()


@app.post("/investments", response_model=VisibleInvestment)
def create_visible_investment(payload: dict[str, Any] = Body(...)) -> VisibleInvestment:
    """Create a visible Investment over one or more standalone Deals, in one
    transaction. An invalid request leaves nothing behind."""

    request = _investment_request(payload, with_units=True)
    try:
        return investment_store.create_visible_investment(**request)
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentValidationError as error:
        raise _investment_validation_error_response(error) from None


@app.get("/investments/{investment_id}/details", response_model=VisibleInvestment)
def read_visible_investment(investment_id: str) -> VisibleInvestment:
    """A visible Investment and everything it states beyond its Units.
    Read-only; a hidden wrapper is a 409 and gains nothing."""

    try:
        return investment_store.get_visible_investment(investment_id)
    except InvestmentNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None


@app.put("/investments/{investment_id}/details", response_model=VisibleInvestment)
def update_visible_investment(
    investment_id: str, payload: dict[str, Any] = Body(...)
) -> VisibleInvestment:
    """Replace the name, transaction price, Investment Business Plan and
    transaction costs as one request, in one transaction."""

    request = _investment_request(payload, with_units=False)
    try:
        return investment_store.update_visible_investment(investment_id, **request)
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentValidationError as error:
        raise _investment_validation_error_response(error) from None


@app.post("/investments/{investment_id}/promote", response_model=VisibleInvestment)
def promote_hidden_investment(
    investment_id: str, payload: dict[str, Any] = Body(...)
) -> VisibleInvestment:
    """Make a Deal's hidden wrapper a visible Investment -- the same
    Investment, its Strategies and Scenarios kept -- optionally adding
    standalone Deals as Units, in one transaction."""

    request = _investment_request(payload, with_units=True)
    try:
        return investment_store.promote_hidden_investment(investment_id, **request)
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentValidationError as error:
        raise _investment_validation_error_response(error) from None


@app.post("/investments/{investment_id}/units", response_model=VisibleInvestment)
def add_investment_unit(investment_id: str, payload: dict[str, Any] = Body(...)) -> VisibleInvestment:
    """Add a standalone Deal as a Unit. ``transaction_price`` may restate the
    Investment's price in the same request; nothing is changed automatically."""

    body = _content_object(payload, _INVESTMENT_ADD_UNIT_FIELDS, "The request body")
    unit = _unit_membership_request(
        {key: value for key, value in body.items() if key != "transaction_price"}, 0, "The request body"
    )
    try:
        return investment_store.add_investment_unit(
            investment_id, unit, transaction_price=body.get("transaction_price")
        )
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentValidationError as error:
        raise _investment_validation_error_response(error) from None


@app.put("/investments/{investment_id}/units/{unit_id}", response_model=VisibleInvestment)
def update_investment_unit(
    investment_id: str, unit_id: str, payload: dict[str, Any] = Body(...)
) -> VisibleInvestment:
    """Change one Unit's display metadata: label, kind and presentation order.
    None of them is economic."""

    body = _content_object(payload, _INVESTMENT_UNIT_DISPLAY_FIELDS, "The request body")
    _require_request_keys(body, ("unit_kind", "ordinal"), "The request body")
    try:
        return investment_store.update_investment_unit(
            investment_id,
            unit_id,
            label=_stripped(body.get("label")),
            unit_kind=_member_token(UnitKind, body["unit_kind"]),
            ordinal=body["ordinal"],
        )
    except (InvestmentNotFoundError, InvestmentUnitNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentValidationError as error:
        raise _investment_validation_error_response(error) from None


@app.delete("/investments/{investment_id}/units/{unit_id}", response_model=VisibleInvestment)
def remove_investment_unit(
    investment_id: str, unit_id: str, transaction_price: float | None = None
) -> VisibleInvestment:
    """Remove a Unit, releasing its Deal unchanged, and -- in the same
    transaction -- restate the Investment's transaction price when the query
    supplies ``transaction_price``. The remaining Units must reconcile to the
    resulting price; nothing is derived from the removed Unit's price. An
    unreconciled result is a structured 422 and nothing changes. Refused (409)
    for the last Unit and for a Unit a Strategy or Scenario still addresses."""

    try:
        return investment_store.remove_investment_unit(
            investment_id, unit_id, transaction_price=transaction_price
        )
    except (InvestmentNotFoundError, InvestmentUnitNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentValidationError as error:
        raise _investment_validation_error_response(error) from None


@app.get(
    "/investments/{investment_id}/investment-variants/{strategy_id}/{scenario_id}/inputs",
    response_model=InvestmentVariantInputs,
)
def visible_investment_variant_inputs(
    investment_id: str, strategy_id: str, scenario_id: str
) -> InvestmentVariantInputs:
    """What exactly a visible Investment variant runs: every Unit's resolved
    contracts and the Investment-level inputs, with the variant's source
    fingerprint. Read-only."""

    try:
        return inspect_consolidated_variant_inputs(investment_id, strategy_id, scenario_id)
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentVariantValidationError as error:
        raise _investment_variant_validation_error_response(error) from None


@app.get(
    "/investments/{investment_id}/investment-variants/{strategy_id}/{scenario_id}/fingerprint",
    response_model=InvestmentVariantFingerprint,
)
def visible_investment_variant_fingerprint(
    investment_id: str, strategy_id: str, scenario_id: str
) -> InvestmentVariantFingerprint:
    """A visible Investment variant's source fingerprint. Read-only."""

    try:
        return consolidated_variant_fingerprint(investment_id, strategy_id, scenario_id)
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentVariantValidationError as error:
        raise _investment_variant_validation_error_response(error) from None


@app.post(
    "/investments/{investment_id}/investment-variants/{strategy_id}/{scenario_id}/analysis",
    response_model=InvestmentVariantAnalysis,
)
def analyze_visible_investment_variant(
    investment_id: str, strategy_id: str, scenario_id: str
) -> InvestmentVariantAnalysis:
    """Analyse a visible Investment variant: every Unit through the existing
    engine, then consolidation. Always recomputed (``bypassed``)."""

    try:
        return analyze_consolidated_variant(investment_id, strategy_id, scenario_id)
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except InvestmentVariantValidationError as error:
        raise _investment_variant_validation_error_response(error) from None


@app.post(
    "/investments/{investment_id}/investment-decision-matrix",
    response_model=InvestmentDecisionMatrixReport,
)
def analyze_visible_investment_decision_matrix(investment_id: str) -> InvestmentDecisionMatrixReport:
    """The Strategy x Scenario Decision Matrix of a visible Investment, over its
    consolidated Project metrics, derived on request and never stored."""

    try:
        return analyze_consolidated_decision_matrix(investment_id)
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except DecisionMatrixConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None


# =============================================================================
# Phase 7 Gate P7.8B -- the Capital Structure surface
#
# Thin routes over ``anchor.deals.store`` (the persisted structures),
# ``anchor.deals.structured_variants`` (the resolved structure, the two
# fingerprints and the P7.8A executor) and ``anchor.deals.decision_matrix`` (the
# POSITION perspective). This module computes nothing, resolves nothing and
# adds no second analysis pathway.
#
# **One owner, two doors.** A Capital Structure belongs to an Investment
# (Section 15.1). The ``/deals`` routes are the convenience door for a standalone
# Deal: the GET never materializes anything, and the first non-empty PUT
# materializes the hidden one-unit wrapper (Q4) exactly as a first Scenario or
# Strategy does. A Deal that is a Unit of a visible Investment is refused with
# 409 and told where its structure lives.
#
# **The authoring surface is the executable subset.** Persistence can represent
# every P7.7 contract, but these routes accept only what P7.8 executes: closing
# funding, ``FixedAmount`` and ``PctOfPrice``, closing fees, cash-pay debt and
# explicit preferred terms. Anything else is refused here, with P7.8A's own
# stable execution codes, rather than stored as something no analysis can run.
#
# **Kinds are explicit on the wire.** A typed union is a class in Python and
# nothing at all in JSON, so every variant carries a ``kind`` discriminator from
# the one codec (``anchor.deals.capital_structure_codec``). Nothing is inferred
# from which fields happen to be present.
# =============================================================================

#: Every typed variant that needs a discriminator on the wire, with the token
#: the codec (or the P7.7 timing contract) already spells. A dataclass absent
#: from this map is serialized by its fields alone, because its shape is not a
#: choice between alternatives.
_CAPITAL_WIRE_KINDS: Mapping[type, str] = {
    FixedAmount: FundingAmountRuleKind.FIXED_AMOUNT.value,
    PctOfPrice: FundingAmountRuleKind.PCT_OF_PRICE.value,
    PctOfValue: FundingAmountRuleKind.PCT_OF_VALUE.value,
    DebtTerms: PositionTermsKind.DEBT.value,
    PreferredEquityTerms: PositionTermsKind.PREFERRED_EQUITY.value,
    ModelMonthPeriod: TimingBasis.MODEL_MONTH.value,
    HoldYearPeriod: TimingBasis.HOLD_YEAR.value,
    # P7.9 Stage 2: the Partnership unions, spelled by the one codec (the split
    # rule reuses the Stage 1 ``SplitRule`` tokens). A subject and a recipient
    # carry their own ``kind`` field already.
    ExplicitSplit: SplitRule.EXPLICIT.value,
    ProRataByContribution: SplitRule.PRO_RATA_BY_CONTRIBUTION.value,
    IrrHurdle: HurdleConditionKind.IRR.value,
    MoicHurdle: HurdleConditionKind.MOIC.value,
}


def _wire(value: Any) -> Any:
    """One structured contract as JSON: dataclasses become objects, enums their
    wire tokens, tuples arrays, and each typed variant carries its ``kind``.

    Explicit rather than ``response_model``: pydantic serializes a union member
    by its fields, which would put ``{"pct": 0.15}`` on the wire for a
    percentage funding and ``{"amount": 1500000.0}`` for a fixed one, leaving
    the reader to guess which rule was authored. It formats and selects; it
    computes nothing."""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {
            field.name: _wire(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
        kind = _CAPITAL_WIRE_KINDS.get(type(value))
        return fields if kind is None else {"kind": kind, **fields}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _wire(item) for key, item in value.items()}
    return value


#: The keys each Capital Structure body may carry. Literal tuples, so an unknown
#: key is always refused rather than silently ignored -- a misspelled
#: ``maturity_month`` must never read as "no maturity stated".
_CAPITAL_STRUCTURE_FIELDS = ("positions",)
_POSITION_FIELDS = (
    "position_id",
    "name",
    "position_class",
    "priority",
    "scope",
    "funding",
    "terms",
    "shortfall_resolution",
)
_SCOPE_FIELDS = ("kind", "unit_id")
_FUNDING_EVENT_FIELDS = ("event_id", "model_month", "sequence", "amount_rule")
_FEE_FIELDS = ("fee_id", "description", "amount", "model_month", "sequence")
_FIXED_AMOUNT_FIELDS = ("kind", "amount")
_PCT_OF_PRICE_FIELDS = ("kind", "pct")
_DEBT_TERMS_FIELDS = (
    "kind",
    "interest_rate",
    "amortization",
    "io_period",
    "maturity_month",
    "fees",
    "current_pay_rate",
    "pik_rate",
)
_PREFERRED_TERMS_FIELDS = (
    "kind",
    "preferred_rate",
    "current_pay_rate",
    "accrual_permitted",
    "accrual_convention",
    "redemption_month",
)
_STRATEGY_ROOT_OVERLAY_FIELDS = ("domain", "content")


def _capital_token(token_type: type[Enum], raw: Any) -> Any:
    """A wire token as its member, or ``raw`` itself for the P7.7 validator to
    refuse by name. ``None`` stays ``None``: common equity states no terms and
    no resolution, and that absence is a real answer, not a missing one."""

    if raw is None:
        return None
    if isinstance(raw, str):
        for member in token_type:
            if member.value == raw:
                return member
    return raw


def _exact_keys(raw: Any, keys: tuple[str, ...], where: str) -> dict[str, Any]:
    """``raw`` as an object stating exactly ``keys``. Every field is stated
    explicitly, including the ones that are ``null``, so nothing a position does
    not say can be filled in from anywhere else."""

    if not isinstance(raw, dict):
        raise _structural_error(f"{where} must be an object.")
    missing = [key for key in keys if key not in raw]
    extra = sorted(key for key in raw if key not in keys)
    if missing or extra:
        raise _structural_error(
            f"{where} must hold exactly {', '.join(repr(key) for key in keys)} "
            f"(missing: {missing}; unknown: {extra})."
        )
    return raw


def _unsupported_authoring(code: ExecutionIssueCode, path: str, message: str) -> HTTPException:
    """A contract P7.7 can represent and P7.8 does not execute, refused at the
    door with P7.8A's own stable code -- never stored as an analysis nobody can
    run."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"code": code.value, "path": path, "message": message}],
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_closing(month: Any, code: ExecutionIssueCode, where: str, what: str) -> None:
    """Closing only (Section 5). A month the contract can hold and the executor
    cannot schedule is refused here; a non-integer is left to the validator."""

    if isinstance(month, int) and not isinstance(month, bool) and month != 0:
        raise _unsupported_authoring(
            code,
            f"{where}.model_month",
            f"{what} is authored at closing (model month 0); month {month} arrives with "
            "scheduled draws.",
        )


def _amount_rule_request(raw: Any, where: str) -> Any:
    """One funding amount rule, by its explicit ``kind``."""

    if not isinstance(raw, dict):
        raise _structural_error(f"{where} must be an object.")
    kind = raw.get("kind")
    if kind == FundingAmountRuleKind.FIXED_AMOUNT:
        return FixedAmount(amount=_exact_keys(raw, _FIXED_AMOUNT_FIELDS, where)["amount"])
    if kind == FundingAmountRuleKind.PCT_OF_PRICE:
        return PctOfPrice(pct=_exact_keys(raw, _PCT_OF_PRICE_FIELDS, where)["pct"])
    if kind == FundingAmountRuleKind.PCT_OF_VALUE:
        raise _unsupported_authoring(
            ExecutionIssueCode.UNSUPPORTED_AMOUNT_RULE,
            where,
            "Funding as a percentage of value arrives with valuation timepoints; author a "
            "fixed amount or a percentage of price.",
        )
    raise _structural_error(
        f"{where}.kind must be {FundingAmountRuleKind.FIXED_AMOUNT.value!r} or "
        f"{FundingAmountRuleKind.PCT_OF_PRICE.value!r}; got {kind!r}."
    )


def _funding_event_request(raw: Any, where: str) -> FundingEvent:
    body = _exact_keys(raw, _FUNDING_EVENT_FIELDS, where)
    _require_closing(
        body["model_month"], ExecutionIssueCode.UNSUPPORTED_FUNDING_TIMING, where, "Funding"
    )
    return FundingEvent(
        event_id=body["event_id"],
        model_month=body["model_month"],
        sequence=body["sequence"],
        amount_rule=_amount_rule_request(body["amount_rule"], f"{where}.amount_rule"),
    )


def _fee_request(raw: Any, where: str) -> PositionFee:
    body = _exact_keys(raw, _FEE_FIELDS, where)
    _require_closing(body["model_month"], ExecutionIssueCode.UNSUPPORTED_FEE_TIMING, where, "A fee")
    return PositionFee(
        fee_id=body["fee_id"],
        description=body["description"],
        amount=body["amount"],
        model_month=body["model_month"],
        sequence=body["sequence"],
    )


def _debt_terms_request(raw: dict[str, Any], where: str) -> DebtTerms:
    """Cash-pay debt, exactly (Section 6). The request states the whole approved
    contract -- ``current_pay_rate`` equal to the coupon and ``pik_rate`` zero --
    and any other split is refused here rather than stored unexecutable."""

    body = _exact_keys(raw, _DEBT_TERMS_FIELDS, where)
    interest_rate, current_pay, pik = body["interest_rate"], body["current_pay_rate"], body["pik_rate"]
    if _is_number(pik) and pik != 0:
        raise _unsupported_authoring(
            ExecutionIssueCode.UNSUPPORTED_DEBT_PIK,
            f"{where}.pik_rate",
            "P7.8 debt is cash pay: its PIK rate is 0.",
        )
    if _is_number(interest_rate) and _is_number(current_pay) and current_pay != interest_rate:
        raise _unsupported_authoring(
            ExecutionIssueCode.UNSUPPORTED_DEBT_CURRENT_PAY,
            f"{where}.current_pay_rate",
            "P7.8 debt is cash pay: its current-pay rate is its whole interest rate.",
        )
    raw_fees = body["fees"]
    if not isinstance(raw_fees, list):
        raise _structural_error(f"{where}.fees must be an array of fee objects.")
    return DebtTerms(
        interest_rate=interest_rate,
        amortization=body["amortization"],
        io_period=body["io_period"],
        maturity_month=body["maturity_month"],
        fees=tuple(
            _fee_request(item, f"{where}.fees[{index}]") for index, item in enumerate(raw_fees)
        ),
        current_pay_rate=current_pay,
        pik_rate=pik,
    )


def _preferred_terms_request(raw: dict[str, Any], where: str) -> PreferredEquityTerms:
    body = _exact_keys(raw, _PREFERRED_TERMS_FIELDS, where)
    return PreferredEquityTerms(
        preferred_rate=body["preferred_rate"],
        current_pay_rate=body["current_pay_rate"],
        accrual_permitted=body["accrual_permitted"],
        accrual_convention=_capital_token(
            PreferredAccrualConvention, body["accrual_convention"]
        ),
        redemption_month=body["redemption_month"],
    )


def _position_terms_request(raw: Any, where: str) -> Any:
    """A position's typed terms, by explicit ``kind`` -- or ``None``, which is
    the common-equity marker's honest answer: the residual has no terms."""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _structural_error(f"{where} must be an object or null.")
    kind = raw.get("kind")
    if kind == PositionTermsKind.DEBT:
        return _debt_terms_request(raw, where)
    if kind == PositionTermsKind.PREFERRED_EQUITY:
        return _preferred_terms_request(raw, where)
    raise _structural_error(
        f"{where}.kind must be {PositionTermsKind.DEBT.value!r} or "
        f"{PositionTermsKind.PREFERRED_EQUITY.value!r}; got {kind!r}."
    )


def _scope_request(raw: Any, where: str) -> PositionScope:
    body = _exact_keys(raw, _SCOPE_FIELDS, where)
    return PositionScope(kind=_capital_token(ScopeKind, body["kind"]), unit_id=body["unit_id"])


def _capital_position_request(raw: Any, where: str) -> CapitalPosition:
    body = _exact_keys(raw, _POSITION_FIELDS, where)
    raw_funding = body["funding"]
    if not isinstance(raw_funding, list):
        raise _structural_error(f"{where}.funding must be an array of funding events.")
    return CapitalPosition(
        position_id=body["position_id"],
        name=body["name"],
        position_class=_capital_token(PositionClass, body["position_class"]),
        priority=body["priority"],
        scope=_scope_request(body["scope"], f"{where}.scope"),
        funding=tuple(
            _funding_event_request(item, f"{where}.funding[{index}]")
            for index, item in enumerate(raw_funding)
        ),
        terms=_position_terms_request(body["terms"], f"{where}.terms"),
        shortfall_resolution=_capital_token(ShortfallResolution, body["shortfall_resolution"]),
    )


def _capital_structure_request(raw: Any, where: str) -> CapitalStructure:
    """A Capital Structure from its wire object, structurally. No contract rule
    is applied here: the P7.7 validator -- the one authority -- reports every
    structural problem, in its own deterministic order, as a structured 422."""

    body = _content_object(raw, _CAPITAL_STRUCTURE_FIELDS, where)
    raw_positions = body.get("positions", [])
    if not isinstance(raw_positions, list):
        raise _structural_error(f"{where}.positions must be an array of position objects.")
    return CapitalStructure(
        positions=tuple(
            _capital_position_request(item, f"{where}.positions[{index}]")
            for index, item in enumerate(raw_positions)
        )
    )


def _strategy_root_overlays(payload: dict[str, Any]) -> tuple[InvestmentStrategyOverlay, ...]:
    """A Strategy's Investment-root overlays from its body, structurally.

    Absent or empty means the Strategy states none, which is *inherit the Base
    Capital Structure*. An overlay whose content is a structure with no position
    is the other thing entirely -- an explicit, stored "no structured capital" --
    and the two travel differently all the way down. A ``partnership`` overlay
    (P7.9 Stage 2) follows the same rule, with ``null`` content as its explicit
    "no Partnership"."""

    raw_overlays = payload.get("root_overlays", [])
    if not isinstance(raw_overlays, list):
        raise _structural_error("'root_overlays' must be an array of overlay objects.")
    overlays: list[InvestmentStrategyOverlay] = []
    for index, raw in enumerate(raw_overlays):
        where = f"root_overlays[{index}]"
        body = _exact_keys(raw, _STRATEGY_ROOT_OVERLAY_FIELDS, where)
        domain = _strategy_domain_token(body["domain"])
        content = _root_overlay_content(domain, body["content"], f"{where}.content")
        overlays.append(InvestmentStrategyOverlay(domain=domain, content=content))
    return tuple(overlays)


def _capital_structure_validation_error_response(
    error: CapitalStructureValidationError | UnsupportedCapitalPositionError,
) -> HTTPException:
    """An invalid Capital Structure as a structured 422: the P7.7 issues, in the
    validator's own order, each with its stable code and the position it
    concerns."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "message": issue.message,
                "position_id": issue.position_id,
                "field": issue.field,
            }
            for issue in error.issues
        ],
    )


def _capital_structure_execution_error_response(
    error: CapitalStructureExecutionError,
) -> HTTPException:
    """A valid Capital Structure this Project state cannot execute, as a
    structured 422 -- an over-funded closing, or a convention P7.8 does not
    schedule. Deliberately distinct from an invalid contract: the structure is
    well formed, and what it cannot do depends on the variant."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "message": issue.message,
                "position_id": issue.position_id,
                "field": issue.field,
            }
            for issue in error.issues
        ],
    )


def _position_identity_conflict_response(error: PositionIdentityConflictError) -> HTTPException:
    """One position id that would name two economic instruments in one
    Investment (P-8), as a structured 422. The analyst gives the different
    instrument its own id; no id is ever regenerated for them."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "message": issue.message,
                "position_id": issue.position_id,
                "field": issue.field,
            }
            for issue in error.issues
        ],
    )


def _structured_conflict(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@app.get("/deals/{deal_id}/capital-structure", response_model=None)
def read_deal_capital_structure(deal_id: str) -> dict[str, Any]:
    """The Deal's Base Capital Structure, and the hidden Investment that owns it
    when one exists.

    Read-only and never materializing: a Deal with no structured capital reports
    the neutral empty structure and no Investment, and asking gives it
    neither."""

    try:
        investment_id, structure = investment_store.read_deal_capital_structure(deal_id)
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    return {
        "deal_id": deal_id,
        "investment_id": investment_id,
        "capital_structure": _wire(structure),
    }


@app.put("/deals/{deal_id}/capital-structure", response_model=None)
def update_deal_capital_structure(
    deal_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Replace the Deal's Base Capital Structure whole.

    The first non-empty save materializes the hidden one-unit Investment in the
    same transaction (Q4); an empty save for a Deal that has none creates
    nothing at all, and an empty save that leaves the wrapper holding no
    Scenario, Strategy or structure removes the wrapper too. The UI keeps saying
    "Deal" throughout."""

    structure = _capital_structure_request(payload, "The request body")
    try:
        investment_id, saved = investment_store.set_deal_capital_structure(deal_id, structure)
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except (CapitalStructureValidationError, UnsupportedCapitalPositionError) as error:
        raise _capital_structure_validation_error_response(error) from None
    except PositionIdentityConflictError as error:
        raise _position_identity_conflict_response(error) from None
    return {"deal_id": deal_id, "investment_id": investment_id, "capital_structure": _wire(saved)}


@app.get("/investments/{investment_id}/capital-structure", response_model=None)
def read_investment_capital_structure(investment_id: str) -> dict[str, Any]:
    """The Investment's Base Capital Structure -- the neutral empty structure
    when it states none. Read-only."""

    try:
        structure = investment_store.get_base_capital_structure(investment_id)
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    return {"investment_id": investment_id, "capital_structure": _wire(structure)}


@app.put("/investments/{investment_id}/capital-structure", response_model=None)
def update_investment_capital_structure(
    investment_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Replace the Investment's Base Capital Structure whole; an empty structure
    clears it."""

    structure = _capital_structure_request(payload, "The request body")
    try:
        saved = investment_store.set_base_capital_structure(investment_id, structure)
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except (CapitalStructureValidationError, UnsupportedCapitalPositionError) as error:
        raise _capital_structure_validation_error_response(error) from None
    except PositionIdentityConflictError as error:
        raise _position_identity_conflict_response(error) from None
    return {"investment_id": investment_id, "capital_structure": _wire(saved)}


@app.get(
    "/investments/{investment_id}/structured-variants/{strategy_id}/{scenario_id}/fingerprint",
    response_model=None,
)
def read_structured_variant_fingerprint(
    investment_id: str, strategy_id: str, scenario_id: str
) -> dict[str, Any]:
    """Both fingerprints of one structured variant, without executing anything.

    The Project fingerprint is the existing one, untouched by the Capital
    Structure; the structured one is that fingerprint plus the resolved
    structure's economics, and *is* that fingerprint when the structure is
    empty. Either identity may be the reserved ``base``."""

    try:
        return _wire(structured_variant_fingerprint(investment_id, strategy_id, scenario_id))
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None
    except InvestmentVariantValidationError as error:
        raise _investment_variant_validation_error_response(error) from None


@app.post(
    "/investments/{investment_id}/structured-variants/{strategy_id}/{scenario_id}/analysis",
    response_model=None,
)
def analyze_structured_capital_variant(
    investment_id: str, strategy_id: str, scenario_id: str
) -> dict[str, Any]:
    """Analyse one structured variant: the existing Project analysis, then the
    P7.8A executor on its completed results.

    One route for both roots -- a hidden one-unit Deal and a visible Investment
    -- because the difference is which executor runs, not which API exists. An
    unresolved Funding Requirement is a successful analysis with N/A returns and
    a deterministic reason, never an HTTP error."""

    try:
        return _wire(analyze_structured_variant(investment_id, strategy_id, scenario_id))
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None
    except InvestmentVariantValidationError as error:
        raise _investment_variant_validation_error_response(error) from None
    except (CapitalStructureValidationError, UnsupportedCapitalPositionError) as error:
        raise _capital_structure_validation_error_response(error) from None
    except CapitalStructureExecutionError as error:
        raise _capital_structure_execution_error_response(error) from None


@app.get("/investments/{investment_id}/position-perspectives", response_model=None)
def read_position_perspectives(investment_id: str) -> dict[str, Any]:
    """Every addressable ``POSITION(position_id)`` perspective: the union of the
    stable ids the Investment's Base structure and its Strategies' own
    structures hold, with the class and scope each id keeps everywhere.

    Presentation only -- no financial figure is computed here -- so the editor
    can offer names instead of asking an analyst to choose a UUID."""

    try:
        perspectives = position_perspectives(investment_id)
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    return {"investment_id": investment_id, "positions": _wire(perspectives)}


@app.post(
    "/investments/{investment_id}/position-decision-matrix/{position_id}", response_model=None
)
def analyze_investment_position_decision_matrix(
    investment_id: str, position_id: str
) -> dict[str, Any]:
    """The Strategy x Scenario matrix of one capital position, derived on
    request and never stored.

    The Project matrix keeps its own route, its own perspective and its own
    fingerprint: this one compares a different namespace over the same
    variants."""

    try:
        return _wire(analyze_position_decision_matrix(investment_id, position_id))
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
        PositionPerspectiveNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except DecisionMatrixConflictError as error:
        raise _structured_conflict(error) from None


# =============================================================================
# Phase 7 Gate P7.9 Stage 2 -- the Partnership surface
#
# Thin routes over ``anchor.deals.store`` (the persisted Partnerships),
# ``anchor.deals.partnership_variants`` (the resolved Partnership, the layered
# fingerprints and the accepted Stage 1 engine reached through the structured
# variant) and ``anchor.deals.decision_matrix`` (the PARTNER perspective). This
# module computes nothing, resolves nothing and adds no second analysis
# pathway.
#
# **One owner, two doors**, exactly as for a Capital Structure: the ``/deals``
# routes are the convenience door for a standalone Deal (the GET materializes
# nothing; the first save of a Partnership materializes the hidden one-unit
# wrapper), and a Unit of a visible Investment is refused with 409.
#
# **Stated, never defaulted.** Every Partnership field is stated on the wire,
# ``null`` included: a missing ``promote_participant_ids`` is a structural 422,
# never an empty set, and a missing split rule, subject, accrual convention or
# SIMPLE order reaches the Stage 1 validator as absent and is refused there.
#
# **Kinds are explicit on the wire.** A tier split and a hurdle condition carry
# a ``kind`` from the one codec (``anchor.deals.partnership_codec``); a subject
# and a recipient carry their own Stage 1 ``kind``. A discriminator the codec
# does not know is refused structurally, and every other unknown token is passed
# to the Stage 1 validator, which refuses it by name. Nothing is inferred.
# =============================================================================

#: The keys each Partnership body may carry. Literal tuples, so an unknown key
#: is always refused rather than silently ignored.
_PARTNERSHIP_BODY_FIELDS = ("partnership",)
_PARTNERSHIP_FIELDS = (
    "partners",
    "contribution_rule",
    "promote_benchmark",
    "promote_participant_ids",
    "tiers",
)
_PARTNER_FIELDS = ("partner_id", "name", "role", "investor_class", "commitment_share")
_BENCHMARK_FIELDS = ("shares",)
_SHARE_FIELDS = ("partner_id", "share")
_TIER_FIELDS = ("tier_id", "name", "sequence", "kind", "split", "hurdle", "catch_up")
_EXPLICIT_SPLIT_FIELDS = ("kind", "shares")
_PRO_RATA_SPLIT_FIELDS = ("kind",)
_HURDLE_FIELDS = ("hurdle_subject", "conditions", "combinator")
_SUBJECT_FIELDS = ("kind", "partner_id", "investor_class", "account")
_IRR_CONDITION_FIELDS = (
    "kind",
    "condition_id",
    "rate",
    "accrual_convention",
    "simple_distribution_order",
)
_MOIC_CONDITION_FIELDS = ("kind", "condition_id", "multiple")
_CATCH_UP_FIELDS = ("recipient", "target_profit_share")
_RECIPIENT_FIELDS = ("kind", "partner_id", "investor_class")


def _wire_array(raw: Any, where: str) -> list[Any]:
    if not isinstance(raw, list):
        raise _structural_error(f"{where} must be an array.")
    return raw


def _share_row(raw: Any, where: str, row_type: type) -> Any:
    body = _exact_keys(raw, _SHARE_FIELDS, where)
    return row_type(partner_id=body["partner_id"], share=body["share"])


def _share_rows(raw: Any, where: str, row_type: type) -> tuple[Any, ...]:
    return tuple(
        _share_row(item, f"{where}[{index}]", row_type)
        for index, item in enumerate(_wire_array(raw, where))
    )


def _partner_request(raw: Any, where: str) -> Partner:
    body = _exact_keys(raw, _PARTNER_FIELDS, where)
    return Partner(
        partner_id=body["partner_id"],
        name=body["name"],
        role=_capital_token(PartnerRole, body["role"]),
        investor_class=body["investor_class"],
        commitment_share=body["commitment_share"],
    )


def _split_request(raw: Any, where: str) -> Any:
    """A tier split by its explicit ``kind`` -- or ``None``, which the Stage 1
    validator refuses as a missing split rule (there is no default)."""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _structural_error(f"{where} must be an object or null.")
    kind = raw.get("kind")
    if kind == SplitRule.EXPLICIT:
        body = _exact_keys(raw, _EXPLICIT_SPLIT_FIELDS, where)
        return ExplicitSplit(shares=_share_rows(body["shares"], f"{where}.shares", SplitShare))
    if kind == SplitRule.PRO_RATA_BY_CONTRIBUTION:
        _exact_keys(raw, _PRO_RATA_SPLIT_FIELDS, where)
        return ProRataByContribution()
    raise _structural_error(
        f"{where}.kind must be {SplitRule.EXPLICIT.value!r} or "
        f"{SplitRule.PRO_RATA_BY_CONTRIBUTION.value!r}; got {kind!r}."
    )


def _condition_request(raw: Any, where: str) -> Any:
    """One hurdle condition by its explicit ``kind``."""

    if not isinstance(raw, dict):
        raise _structural_error(f"{where} must be an object.")
    kind = raw.get("kind")
    if kind == HurdleConditionKind.IRR:
        body = _exact_keys(raw, _IRR_CONDITION_FIELDS, where)
        return IrrHurdle(
            condition_id=body["condition_id"],
            rate=body["rate"],
            accrual_convention=_capital_token(PreferredAccrualConvention, body["accrual_convention"]),
            simple_distribution_order=_capital_token(
                SimpleDistributionOrder, body["simple_distribution_order"]
            ),
        )
    if kind == HurdleConditionKind.MOIC:
        body = _exact_keys(raw, _MOIC_CONDITION_FIELDS, where)
        return MoicHurdle(condition_id=body["condition_id"], multiple=body["multiple"])
    raise _structural_error(
        f"{where}.kind must be {HurdleConditionKind.IRR.value!r} or "
        f"{HurdleConditionKind.MOIC.value!r}; got {kind!r}."
    )


def _hurdle_request(raw: Any, where: str) -> HurdleTerms | None:
    if raw is None:
        return None
    body = _exact_keys(raw, _HURDLE_FIELDS, where)
    raw_subject = body["hurdle_subject"]
    subject = None
    if raw_subject is not None:
        subject_body = _exact_keys(raw_subject, _SUBJECT_FIELDS, f"{where}.hurdle_subject")
        subject = HurdleSubject(
            kind=_capital_token(HurdleSubjectKind, subject_body["kind"]),
            partner_id=subject_body["partner_id"],
            investor_class=subject_body["investor_class"],
            account=_capital_token(EconomicAccount, subject_body["account"]),
        )
    return HurdleTerms(
        hurdle_subject=subject,  # type: ignore[arg-type]
        conditions=tuple(
            _condition_request(item, f"{where}.conditions[{index}]")
            for index, item in enumerate(_wire_array(body["conditions"], f"{where}.conditions"))
        ),
        combinator=_capital_token(HurdleCombinator, body["combinator"]),
    )


def _catch_up_request(raw: Any, where: str) -> CatchUpTerms | None:
    if raw is None:
        return None
    body = _exact_keys(raw, _CATCH_UP_FIELDS, where)
    recipient = _exact_keys(body["recipient"], _RECIPIENT_FIELDS, f"{where}.recipient")
    return CatchUpTerms(
        recipient=CatchUpRecipient(
            kind=_capital_token(CatchUpRecipientKind, recipient["kind"]),
            partner_id=recipient["partner_id"],
            investor_class=recipient["investor_class"],
        ),
        target_profit_share=body["target_profit_share"],
    )


def _tier_request(raw: Any, where: str) -> WaterfallTier:
    body = _exact_keys(raw, _TIER_FIELDS, where)
    return WaterfallTier(
        tier_id=body["tier_id"],
        name=body["name"],
        sequence=body["sequence"],
        kind=_capital_token(TierKind, body["kind"]),
        split=_split_request(body["split"], f"{where}.split"),
        hurdle=_hurdle_request(body["hurdle"], f"{where}.hurdle"),
        catch_up=_catch_up_request(body["catch_up"], f"{where}.catch_up"),
    )


def _partnership_request(raw: Any, where: str) -> Partnership | None:
    """A Partnership from its wire object, structurally -- or ``None`` for an
    explicit ``null``. No contract rule is applied here: the Stage 1 validator
    reports every structural problem as a structured 422."""

    if raw is None:
        return None
    body = _exact_keys(raw, _PARTNERSHIP_FIELDS, where)
    benchmark = _exact_keys(body["promote_benchmark"], _BENCHMARK_FIELDS, f"{where}.promote_benchmark")
    return Partnership(
        partners=tuple(
            _partner_request(item, f"{where}.partners[{index}]")
            for index, item in enumerate(_wire_array(body["partners"], f"{where}.partners"))
        ),
        contribution_rule=_capital_token(ContributionRule, body["contribution_rule"]),
        promote_benchmark=PromoteBenchmark(
            shares=_share_rows(benchmark["shares"], f"{where}.promote_benchmark.shares", BenchmarkShare)
        ),
        promote_participant_ids=tuple(
            _wire_array(body["promote_participant_ids"], f"{where}.promote_participant_ids")
        ),
        tiers=tuple(
            _tier_request(item, f"{where}.tiers[{index}]")
            for index, item in enumerate(_wire_array(body["tiers"], f"{where}.tiers"))
        ),
    )


def _partnership_body(payload: dict[str, Any]) -> Partnership | None:
    body = _exact_keys(payload, _PARTNERSHIP_BODY_FIELDS, "The request body")
    return _partnership_request(body["partnership"], "partnership")


def _root_overlay_content(domain: Any, raw: Any, where: str) -> Any:
    """A root overlay's content by its domain: a Capital Structure (P7.8B), or
    a Partnership, where ``null`` is the explicit "no Partnership"."""

    if domain is StrategyDomain.CAPITAL_STRUCTURE:
        return _capital_structure_request(raw, where)
    if domain is StrategyDomain.PARTNERSHIP:
        partnership = _partnership_request(raw, where)
        return NoPartnership() if partnership is None else partnership
    return raw


def _root_overlay_wire(content: Any) -> Any:
    """A root overlay's content on the wire; the explicit "no Partnership" is
    ``null``."""

    return None if isinstance(content, NoPartnership) else _wire(content)


def _partnership_validation_error_response(error: PartnershipValidationError) -> HTTPException:
    """An invalid Partnership as a structured 422: the Stage 1 issues, in the
    validator's own order, each with its stable code and location."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "message": issue.message,
                "partner_id": issue.partner_id,
                "tier_id": issue.tier_id,
                "field": issue.field,
            }
            for issue in error.issues
        ],
    )


def _partnership_execution_error_response(error: PartnershipExecutionError) -> HTTPException:
    """A valid Partnership the Stage 1 engine cannot run over this variant's
    Common Equity Cash Flow, as a structured 422 -- deliberately distinct from
    an invalid contract."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "message": issue.message,
                "tier_id": issue.tier_id,
                "period": issue.period,
            }
            for issue in error.issues
        ],
    )


@app.get("/deals/{deal_id}/partnership", response_model=None)
def read_deal_partnership(deal_id: str) -> dict[str, Any]:
    """The Deal's Base Partnership, and the hidden Investment that owns it when
    one exists. Read-only and never materializing: a Deal with no Partnership
    reports ``null`` and no Investment."""

    try:
        investment_id, partnership = investment_store.read_deal_partnership(deal_id)
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    return {"deal_id": deal_id, "investment_id": investment_id, "partnership": _wire(partnership)}


@app.put("/deals/{deal_id}/partnership", response_model=None)
def update_deal_partnership(deal_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Replace the Deal's Base Partnership whole; ``null`` clears it.

    The first save of a Partnership materializes the hidden one-unit Investment
    in the same transaction (Q4); clearing a Deal that has none creates nothing,
    and clearing one that leaves the wrapper holding no structure removes the
    wrapper."""

    partnership = _partnership_body(payload)
    try:
        investment_id, saved = investment_store.set_deal_partnership(deal_id, partnership)
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except PartnershipValidationError as error:
        raise _partnership_validation_error_response(error) from None
    return {"deal_id": deal_id, "investment_id": investment_id, "partnership": _wire(saved)}


@app.get("/investments/{investment_id}/partnership", response_model=None)
def read_investment_partnership(investment_id: str) -> dict[str, Any]:
    """The Investment's Base Partnership, or ``null`` when it states none.
    Read-only."""

    try:
        partnership = investment_store.get_base_partnership(investment_id)
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    return {"investment_id": investment_id, "partnership": _wire(partnership)}


@app.put("/investments/{investment_id}/partnership", response_model=None)
def update_investment_partnership(
    investment_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Replace the Investment's Base Partnership whole; ``null`` clears it."""

    partnership = _partnership_body(payload)
    try:
        saved = investment_store.set_base_partnership(investment_id, partnership)
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except PartnershipValidationError as error:
        raise _partnership_validation_error_response(error) from None
    return {"investment_id": investment_id, "partnership": _wire(saved)}


@app.get(
    "/investments/{investment_id}/partnership-variants/{strategy_id}/{scenario_id}/fingerprint",
    response_model=None,
)
def read_partnership_variant_fingerprint(
    investment_id: str, strategy_id: str, scenario_id: str
) -> dict[str, Any]:
    """The layered fingerprints of one Partnership variant, without executing
    anything. The Partnership fingerprint is ``null`` when the variant has no
    Partnership (FP-2)."""

    try:
        return _wire(partnership_variant_fingerprint(investment_id, strategy_id, scenario_id))
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None
    except InvestmentVariantValidationError as error:
        raise _investment_variant_validation_error_response(error) from None


@app.post(
    "/investments/{investment_id}/partnership-variants/{strategy_id}/{scenario_id}/analysis",
    response_model=None,
)
def analyze_partnership_capital_variant(
    investment_id: str, strategy_id: str, scenario_id: str
) -> dict[str, Any]:
    """Analyse one Partnership variant: the structured variant, then the
    accepted Stage 1 engine on its Common Equity Cash Flow.

    An unavailable Common Equity Cash Flow is a successful analysis with an
    ``unavailable`` Partnership result, never an HTTP error; a variant with no
    Partnership reports ``null``."""

    try:
        return _wire(analyze_partnership_variant(investment_id, strategy_id, scenario_id))
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except StrategyValidationError as error:
        raise _strategy_validation_error_response(error) from None
    except ScenarioValidationError as error:
        raise _scenario_validation_error_response(error) from None
    except LeaseValidationError as error:
        raise _lease_validation_error_response(error) from None
    except InvestmentVariantValidationError as error:
        raise _investment_variant_validation_error_response(error) from None
    except (CapitalStructureValidationError, UnsupportedCapitalPositionError) as error:
        raise _capital_structure_validation_error_response(error) from None
    except CapitalStructureExecutionError as error:
        raise _capital_structure_execution_error_response(error) from None
    except PartnershipValidationError as error:
        raise _partnership_validation_error_response(error) from None
    except PartnershipExecutionError as error:
        raise _partnership_execution_error_response(error) from None


@app.get("/investments/{investment_id}/partner-perspectives", response_model=None)
def read_partner_perspectives(investment_id: str) -> dict[str, Any]:
    """Every addressable ``PARTNER(partner_id)`` perspective: the union of the
    stable ids the Investment's Base Partnership and its Strategies' own hold,
    with the role each keeps everywhere. Presentation only."""

    try:
        perspectives = partner_perspectives(investment_id)
    except (InvestmentNotFoundError, DealNotFoundError) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    return {"investment_id": investment_id, "partners": _wire(perspectives)}


@app.post(
    "/investments/{investment_id}/partner-decision-matrix/{partner_id}", response_model=None
)
def analyze_investment_partner_decision_matrix(
    investment_id: str, partner_id: str
) -> dict[str, Any]:
    """The Strategy x Scenario matrix of one partner, derived on request and
    never stored. The Project and Position matrices keep their own routes and
    fingerprints."""

    try:
        return _wire(analyze_partner_decision_matrix(investment_id, partner_id))
    except (
        InvestmentNotFoundError,
        StrategyNotFoundError,
        ScenarioNotFoundError,
        DealNotFoundError,
        PartnerPerspectiveNotFoundError,
    ) as error:
        raise _not_found(error) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except DecisionMatrixConflictError as error:
        raise _structured_conflict(error) from None


# =============================================================================
# Gate AM1 -- Managed Assets and Monthly Performance.
#
# ``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`` Section 6.
# Eight routes, using the repository's established contracts: ``_exact_keys``
# for a body that must state every field it carries, ``_wire`` for the response,
# ``_not_found`` for a missing entity, ``_structural_error`` for a malformed
# body, a structured 422 for a contract refusal, and 409 for a conflict.
#
# **No route computes anything.** ``anchor.asset_management.performance`` is the
# sole authority for every total, variance, percentage, assessment, attention
# item and trend point; these routes read stored figures, hand them to it, and
# serialize what it returns.
#
# There is no AI route here and no paid AI call anywhere in AM1: attention items
# are derived from the deterministic result, and commentary is analyst prose
# that reaches no model.
#
# There is deliberately no DELETE for either an asset or a report (Section 8).
# =============================================================================

#: Every field a monthly statement states, exactly. A body must carry all of
#: them: a missing ``payroll`` is a body that forgot a line, never a zero.
_AM1_FIGURE_FIELDS = ("occupancy", *AM1_MONETARY_FIELDS)

_MANAGED_ASSET_FIELDS = ("source_deal_id", "name", "acquisition_date", "property_type", "market")
_MONTHLY_REPORT_FIELDS = ("reporting_month", "budget", "actual", "commentary")
_ACTUALS_FIELDS = ("actual", "commentary", "budget")


def _am1_validation_error_response(error: AssetReportValidationError) -> HTTPException:
    """A structurally invalid Managed Asset or report as a structured 422: every
    issue, in the validator's own order, each with its stable code, the
    statement it belongs to and the exact field."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "code": issue.code.value,
                "message": issue.message,
                "scope": issue.scope,
                "field": issue.field,
            }
            for issue in error.issues
        ],
    )


def _budget_immutable_response(error: BudgetImmutableError) -> HTTPException:
    """A frozen-budget conflict as a 409, deliberately not a 422.

    The submitted budget may be perfectly well-formed; what is refused is the
    authority to change it. A 422 would tell the product "fix these numbers",
    which is exactly the wrong instruction -- so the status, the code and the
    named fields all say "this is no longer yours to change" instead.
    """

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "budget_immutable",
            "message": str(error),
            "reporting_month": error.reporting_month.isoformat(),
            "changed_fields": list(error.changed_fields),
        },
    )


def _am1_date(raw: Any, where: str) -> date:
    """A calendar date from the wire.

    Parsing lives in ``anchor.asset_management.validation``, which reports a
    malformed string by returning ``None`` rather than raising. That keeps this
    module from having to catch ``ValueError`` at all: every validation error in
    the repository subclasses it, so such a catch here would be one refactor
    away from turning a typed domain refusal into a generic "bad date".
    """

    parsed = parse_iso_date(raw)
    if parsed is None:
        raise _structural_error(f"{where} must be an ISO-8601 date string.")
    return parsed


def _am1_month(raw: Any, where: str) -> date:
    """A reporting month from the wire, normalized to the first of the month."""

    return normalize_reporting_month(_am1_date(raw, where))


def _am1_figures(raw: Any, where: str) -> OperatingFigures:
    """One statement from the wire. Structure only: the range rules
    (finite, non-negative, occupancy in 0..1) belong to
    ``anchor.asset_management.validation`` and are applied by the store, so
    there is one definition of a valid figure rather than two."""

    body = _exact_keys(raw, _AM1_FIGURE_FIELDS, where)
    return OperatingFigures(**{field: body[field] for field in _AM1_FIGURE_FIELDS})


def _am1_commentary(raw: Any, where: str) -> str | None:
    if raw is None or isinstance(raw, str):
        return raw
    raise _structural_error(f"{where} must be text or null.")


@app.post("/managed-assets", response_model=None)
def create_managed_asset(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create the Managed Asset for a saved Deal.

    One per Deal. The Deal's authoritative analysis fingerprint is captured here
    as the frozen approved acquisition basis; the Deal itself is not modified,
    and no later Deal edit reaches the asset.
    """

    body = _exact_keys(payload, _MANAGED_ASSET_FIELDS, "The request body")
    try:
        asset = investment_store.create_managed_asset(
            source_deal_id=body["source_deal_id"],
            name=body["name"],
            acquisition_date=_am1_date(body["acquisition_date"], "acquisition_date"),
            property_type=body["property_type"],
            market=body["market"],
        )
    except DealNotFoundError as error:
        raise _not_found(error) from None
    except ManagedAssetExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "managed_asset_exists",
                "message": str(error),
                "managed_asset_id": error.managed_asset_id,
            },
        ) from None
    except InvestmentStructureError as error:
        raise _investment_structure_conflict(error) from None
    except AssetReportValidationError as error:
        raise _am1_validation_error_response(error) from None
    return _wire(asset)


@app.get("/managed-assets", response_model=None)
def list_managed_assets() -> list[dict[str, Any]]:
    """Every Managed Asset, most recently updated first."""

    return [_wire(asset) for asset in investment_store.list_managed_assets()]


@app.get("/managed-assets/{managed_asset_id}", response_model=None)
def read_managed_asset(managed_asset_id: str) -> dict[str, Any]:
    """One Managed Asset, including the frozen acquisition fingerprint and the
    source Deal id the product shows as provenance."""

    try:
        return _wire(investment_store.get_managed_asset(managed_asset_id))
    except ManagedAssetNotFoundError as error:
        raise _not_found(error) from None


@app.get("/managed-assets/{managed_asset_id}/reports", response_model=None)
def list_monthly_asset_reports(managed_asset_id: str) -> list[dict[str, Any]]:
    """Every saved monthly report for one asset, in month order. Figures only:
    no total, variance or assessment is included, because none is stored."""

    try:
        reports = investment_store.list_monthly_reports(managed_asset_id)
    except ManagedAssetNotFoundError as error:
        raise _not_found(error) from None
    return [_wire(report) for report in reports]


@app.get("/managed-assets/{managed_asset_id}/reports/{reporting_month}", response_model=None)
def read_monthly_asset_report(managed_asset_id: str, reporting_month: str) -> dict[str, Any]:
    """One month's saved report."""

    month = _am1_month(reporting_month, "reporting_month")
    try:
        return _wire(investment_store.get_monthly_report(managed_asset_id, month))
    except (ManagedAssetNotFoundError, MonthlyReportNotFoundError) as error:
        raise _not_found(error) from None


@app.post("/managed-assets/{managed_asset_id}/reports", response_model=None)
def create_monthly_asset_report(
    managed_asset_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Create one month's report, freezing its approved budget.

    The only route that ever writes a budget. A second create for a month that
    already has a report is a 409, never a merge -- merging would be an
    undeclared budget revision.
    """

    body = _exact_keys(payload, _MONTHLY_REPORT_FIELDS, "The request body")
    try:
        report = investment_store.create_monthly_report(
            managed_asset_id=managed_asset_id,
            reporting_month=_am1_month(body["reporting_month"], "reporting_month"),
            budget=_am1_figures(body["budget"], "budget"),
            actual=_am1_figures(body["actual"], "actual"),
            commentary=_am1_commentary(body["commentary"], "commentary"),
        )
    except ManagedAssetNotFoundError as error:
        raise _not_found(error) from None
    except MonthlyReportExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "monthly_report_exists", "message": str(error)},
        ) from None
    except AssetReportValidationError as error:
        raise _am1_validation_error_response(error) from None
    return _wire(report)


@app.put("/managed-assets/{managed_asset_id}/reports/{reporting_month}", response_model=None)
def update_monthly_asset_report_actuals(
    managed_asset_id: str, reporting_month: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Update one report's actual results and commentary.

    ``budget`` may be echoed back so a client that round-trips a whole report is
    told precisely which fields it tried to change; any difference from the
    frozen budget is a 409. Sending ``null`` asserts nothing about the budget and
    is the ordinary path.
    """

    body = _exact_keys(payload, _ACTUALS_FIELDS, "The request body")
    raw_budget = body["budget"]
    try:
        report = investment_store.update_monthly_report_actuals(
            managed_asset_id=managed_asset_id,
            reporting_month=_am1_month(reporting_month, "reporting_month"),
            actual=_am1_figures(body["actual"], "actual"),
            commentary=_am1_commentary(body["commentary"], "commentary"),
            budget=None if raw_budget is None else _am1_figures(raw_budget, "budget"),
        )
    except (ManagedAssetNotFoundError, MonthlyReportNotFoundError) as error:
        raise _not_found(error) from None
    except BudgetImmutableError as error:
        raise _budget_immutable_response(error) from None
    except AssetReportValidationError as error:
        raise _am1_validation_error_response(error) from None
    return _wire(report)


@app.get("/managed-assets/{managed_asset_id}/performance/{reporting_month}", response_model=None)
def read_monthly_asset_performance(
    managed_asset_id: str, reporting_month: str
) -> dict[str, Any]:
    """The authoritative monthly and year-to-date performance for one asset at
    one month, derived on request and never stored.

    Every number in the response comes from
    ``anchor.asset_management.performance``. Nothing here is computed, cached or
    reconciled against a second source.
    """

    month = _am1_month(reporting_month, "reporting_month")
    try:
        asset = investment_store.get_managed_asset(managed_asset_id)
        reports = investment_store.list_monthly_reports(managed_asset_id)
    except ManagedAssetNotFoundError as error:
        raise _not_found(error) from None
    try:
        result = analyze_asset_performance(
            managed_asset_id=managed_asset_id, reporting_month=month, reports=reports
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No report has been saved for {month.isoformat()}, so there is no "
                "performance to report for it."
            ),
        ) from None
    return {
        "managed_asset": _wire(asset),
        "result": _wire(result),
        "reported_months": [report.reporting_month.isoformat() for report in reports],
    }
