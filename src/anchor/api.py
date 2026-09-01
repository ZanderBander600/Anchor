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

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from io import BytesIO
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .ai import (
    AIAnalysis,
    AIConfigurationError,
    AIProviderError,
    generate_ai_analysis,
)
from .analysis import (
    InvalidBreakEvenTargetError,
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
    StandardSensitivityPresets,
    TwoWaySensitivityResult,
    UnknownAssumptionError,
    UnknownMetricError,
    build_standard_break_even_analysis,
    build_standard_presets,
    run_two_way_sensitivity,
)
from .contracts import AcquisitionInputs
from .engine import AcquisitionResults, analyze_acquisition
from .excel_reader import read_acquisition_inputs_from_bytes
from .ingestion import (
    ExtractionConfigurationError,
    ExtractionProviderError,
    ExtractionResult,
    extract_om,
)
from .validation import InputValidationError, validate_acquisition_inputs

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
_PDF_PARSE_TIMEOUT_SECONDS = 5  # KTD11 -- bounds the local pypdf page-count parse.
_PDF_SIGNATURE = b"%PDF-"

_EXCEL_INGESTION_PATH = "/ingestion/excel"
_MAX_EXCEL_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB -- a structured input workbook is small.
_XLSX_SIGNATURE = b"PK\x03\x04"  # .xlsx is a zip archive (OOXML).


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
        _EXCEL_INGESTION_PATH: _MAX_EXCEL_UPLOAD_BYTES,
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


@app.post("/analyze", response_model=AcquisitionResults)
def analyze(payload: dict[str, Any] = Body(...)) -> AcquisitionResults:
    try:
        inputs = validate_acquisition_inputs(payload)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None

    return analyze_acquisition(inputs)


# =============================================================================
# Phase 7 -- sensitivity analysis
#
# Both endpoints below validate the nested ``inputs`` object with the same
# ``validate_acquisition_inputs`` used by ``/analyze``, then delegate all
# sensitivity computation to ``anchor.analysis.sensitivity``. Neither
# endpoint performs financial or sensitivity math itself.
# =============================================================================


@app.post("/sensitivity", response_model=TwoWaySensitivityResult)
def sensitivity(payload: dict[str, Any] = Body(...)) -> TwoWaySensitivityResult:
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


@app.post("/sensitivity/presets", response_model=StandardSensitivityPresets)
def sensitivity_presets(
    payload: dict[str, Any] = Body(...),
) -> StandardSensitivityPresets:
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

    return build_standard_presets(inputs)


# =============================================================================
# Phase 8 -- break-even analysis
#
# Delegates all break-even solving to ``anchor.analysis.break_even``;
# this endpoint performs no financial math and no threshold search itself.
# =============================================================================


def _numeric_target(payload: dict[str, Any], field: str) -> float:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} must be a numeric value.",
        )
    return float(value)


@app.post("/break-even", response_model=StandardBreakEvenAnalysis)
def break_even(payload: dict[str, Any] = Body(...)) -> StandardBreakEvenAnalysis:
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
        )
    except InvalidBreakEvenTargetError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None


# =============================================================================
# Phase 9A -- AI Analyst
#
# Delegates all context assembly and the provider call to
# ``anchor.ai.generate_ai_analysis``; this endpoint performs no
# financial math, sensitivity math, break-even search, or OpenAI call of
# its own.
# =============================================================================


@app.post("/ai/analysis", response_model=AIAnalysis)
def ai_analysis(payload: dict[str, Any] = Body(...)) -> AIAnalysis:
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
        return generate_ai_analysis(
            inputs,
            target_levered_irr=target_levered_irr,
            target_equity_multiple=target_equity_multiple,
            target_headline_dscr=target_headline_dscr,
            return_hurdle_metric=return_hurdle_metric,
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
# Phase 10B -- Excel ingestion (web upload)
#
# Reuses the exact same deterministic workbook reader the CLI has always
# used (``read_acquisition_inputs_from_bytes``, sharing its parsing/
# validation implementation with the path-based ``read_acquisition_inputs``)
# -- this endpoint performs no workbook parsing, financial validation, or
# financial math of its own, and never calls the deterministic engine.
# Unlike ``/ingestion/om``, there is no external provider and no partial/
# candidate result: a workbook is either fully valid (200, the nine
# validated inputs) or it isn't (422, the same ordered issue list
# ``/analyze`` already returns for a bad payload).
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


@app.post(_EXCEL_INGESTION_PATH, response_model=AcquisitionInputs)
def ingest_excel(file: UploadFile = File(...)) -> AcquisitionInputs:
    _validate_xlsx_filename(file)

    workbook_bytes = _read_upload_bytes(file, max_bytes=_MAX_EXCEL_UPLOAD_BYTES)
    _validate_xlsx_signature(workbook_bytes)

    try:
        return read_acquisition_inputs_from_bytes(workbook_bytes)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(error),
        ) from None
