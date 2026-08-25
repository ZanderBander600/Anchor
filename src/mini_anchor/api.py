"""Minimal FastAPI adapter: HTTP request -> engine -> JSON response.

This module is a thin adapter layer, mirroring the role ``cli.py`` plays for
the terminal. It calls ``validate_acquisition_inputs`` and
``analyze_acquisition`` -- the existing, frozen Phase 2/Phase 4 functions --
and never reproduces or reimplements any financial formula or validation
rule itself.
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

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


@app.post("/analyze", response_model=AcquisitionResults)
def analyze(payload: dict[str, Any] = Body(...)) -> AcquisitionResults:
    try:
        inputs = validate_acquisition_inputs(payload)
    except InputValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[
                {
                    "field_id": issue.field_id,
                    "category": issue.category.value,
                    "message": issue.message,
                }
                for issue in error.issues
            ],
        ) from None

    return analyze_acquisition(inputs)
