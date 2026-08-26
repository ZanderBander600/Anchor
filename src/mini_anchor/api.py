"""Minimal FastAPI adapter: HTTP request -> engine -> JSON response.

This module is a thin adapter layer, mirroring the role ``cli.py`` plays for
the terminal. It calls ``validate_acquisition_inputs`` and
``analyze_acquisition`` -- the existing, frozen Phase 2/Phase 4 functions --
and never reproduces or reimplements any financial formula or validation
rule itself. The Phase 7 sensitivity endpoints below follow the identical
pattern, delegating all sensitivity computation to
``mini_anchor.analysis.sensitivity`` -- this module does no financial math or
sensitivity math of its own.
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

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
from .engine import AcquisitionResults, analyze_acquisition
from .validation import InputValidationError, validate_acquisition_inputs

app = FastAPI(title="Mini-Anchor API")

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
# sensitivity computation to ``mini_anchor.analysis.sensitivity``. Neither
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
# Delegates all break-even solving to ``mini_anchor.analysis.break_even``;
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
# ``mini_anchor.ai.generate_ai_analysis``; this endpoint performs no
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
