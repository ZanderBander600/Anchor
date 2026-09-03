"""Architecture guardrails for the Phase 9A AI Analyst layer.

Confirms the frozen engine never imports ``openai`` or ``anchor.ai``,
that ``openai`` is imported only inside ``anchor.ai.provider`` (never
elsewhere, and never anywhere under ``engine/`` or ``analysis/``), that the
``ai`` package never reproduces a financial formula (no ``math`` import),
and that the AI layer consumes deterministic outputs only by delegating to
the existing engine/analysis entry points rather than duplicating them.

Mirrors the style of ``test_analysis_architecture.py``.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from anchor.ai import analyst as ai_analyst_module
from anchor.ai import provider as ai_provider_module
from anchor.analysis import (
    build_standard_break_even_analysis,
    build_standard_detailed_break_even_analysis,
    build_standard_detailed_presets,
    build_standard_presets,
)
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.engine import analyze_acquisition, analyze_detailed_acquisition_with_projection

GOLDEN_INPUTS = AcquisitionInputs(
    purchase_price=50_000_000.0,
    current_noi=2_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.055,
    ltv=0.65,
    interest_rate=0.0525,
    amortization=30,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENGINE_DIR = _PROJECT_ROOT / "src" / "anchor" / "engine"
_ANALYSIS_DIR = _PROJECT_ROOT / "src" / "anchor" / "analysis"
_AI_DIR = Path(ai_analyst_module.__file__).parent


def _imported_module_names(source_file: Path) -> list[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def test_engine_package_has_no_openai_import() -> None:
    for source_file in _ENGINE_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(name.startswith("openai") for name in names), (
            f"{source_file} must not import openai"
        )


def test_analysis_package_has_no_openai_import() -> None:
    for source_file in _ANALYSIS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(name.startswith("openai") for name in names), (
            f"{source_file} must not import openai"
        )


def test_engine_package_does_not_import_ai_package() -> None:
    for source_file in _ENGINE_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any("anchor.ai" in name for name in names), (
            f"{source_file} must not import anchor.ai"
        )


def test_analysis_package_does_not_import_ai_package() -> None:
    for source_file in _ANALYSIS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any("anchor.ai" in name for name in names), (
            f"{source_file} must not import anchor.ai"
        )


def test_openai_is_imported_only_inside_the_provider_module() -> None:
    for source_file in _AI_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        has_openai_import = any(name.startswith("openai") for name in names)
        if source_file.name == "provider.py":
            continue
        assert not has_openai_import, f"{source_file} must not import openai directly"


def test_ai_package_reproduces_no_financial_formula() -> None:
    """No ``ai/`` module imports ``math`` -- every numeric value the AI
    layer sees is read off an already-computed engine/analysis contract,
    never derived here."""

    for source_file in _AI_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert "math" not in names, f"{source_file} must not import math"


# Detailed Operating Model V2.1 Gate 9: the exact calculation modules "AI
# may consume result contracts and presentation-format them only" forbids
# reaching into directly. Each owns a class of financial formula this
# module must never import: operating projection/NOI (engine.noi,
# engine.operating_projection), acquisition/exit/cash-flow assembly
# (engine.acquisition), debt (engine.debt), return metrics (engine.returns),
# sensitivity scenarios (analysis.sensitivity), and break-even search
# (analysis.break_even). The AI layer may only reach the public
# `anchor.engine`/`anchor.analysis` package surface (their entry points)
# and `anchor.engine.contracts`/`anchor.analysis.contracts` (pure data
# shapes, no calculation) -- never one of these modules directly.
_FORBIDDEN_CALCULATION_MODULES: tuple[str, ...] = (
    "anchor.engine.noi",
    "anchor.engine.debt",
    "anchor.engine.acquisition",
    "anchor.engine.returns",
    "anchor.engine.operating_projection",
    "anchor.analysis.sensitivity",
    "anchor.analysis.break_even",
)


def test_ai_package_never_imports_a_calculation_module_directly() -> None:
    """AST-level enforcement of "AI may consume result contracts and
    presentation-format them only": no ``ai/`` module may import
    ``engine.noi``/``engine.debt``/``engine.acquisition``/``engine.returns``/
    ``engine.operating_projection``/``analysis.sensitivity``/
    ``analysis.break_even`` -- the modules that actually contain a NOI,
    acquisition, debt, returns, sensitivity, or break-even formula. Every
    calculation the AI layer needs must come through the public
    ``anchor.engine``/``anchor.analysis`` entry points
    (``analyze_acquisition``, ``analyze_detailed_acquisition_with_projection``,
    ``build_standard_presets``, ``build_standard_detailed_presets``,
    ``build_standard_break_even_analysis``,
    ``build_standard_detailed_break_even_analysis``) instead."""

    for source_file in _AI_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        for forbidden in _FORBIDDEN_CALCULATION_MODULES:
            assert forbidden not in names, (
                f"{source_file} must not import {forbidden} directly -- "
                "route through the public anchor.engine/anchor.analysis "
                "entry points instead"
            )


def test_engine_import_does_not_pull_in_openai() -> None:
    environment = os.environ.copy()
    python_path_parts = [str(_PROJECT_ROOT / "src")]
    if existing_python_path := environment.get("PYTHONPATH"):
        python_path_parts.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import anchor.engine; assert 'openai' not in sys.modules",
        ],
        cwd=_PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


# =============================================================================
# AI layer consumes deterministic outputs only (delegation, not duplication)
# =============================================================================


def test_ai_analyst_delegates_to_the_authoritative_engine_entry_point() -> None:
    with patch(
        "anchor.ai.analyst.analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        ai_analyst_module.build_analysis_context(
            GOLDEN_INPUTS,
            target_levered_irr=0.10,
            target_equity_multiple=1.50,
            target_headline_dscr=1.20,
        )

    mock_analyze.assert_called_once_with(GOLDEN_INPUTS)


def test_ai_analyst_delegates_to_the_authoritative_analysis_entry_points() -> None:
    with (
        patch(
            "anchor.ai.analyst.build_standard_presets", wraps=build_standard_presets
        ) as mock_presets,
        patch(
            "anchor.ai.analyst.build_standard_break_even_analysis",
            wraps=build_standard_break_even_analysis,
        ) as mock_break_even,
    ):
        ai_analyst_module.build_analysis_context(
            GOLDEN_INPUTS,
            target_levered_irr=0.10,
            target_equity_multiple=1.50,
            target_headline_dscr=1.20,
        )

    mock_presets.assert_called_once_with(GOLDEN_INPUTS)
    mock_break_even.assert_called_once()


# Detailed Operating Model V2.1 Gate 9 -- Detailed counterparts of the two
# delegation tests above, proving build_detailed_analysis_context delegates
# to the authoritative Detailed engine/analysis entry points rather than
# reproducing any of their calculations.

GOLDEN_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)

GOLDEN_DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)


def test_ai_analyst_delegates_to_the_authoritative_detailed_engine_entry_point() -> None:
    with patch(
        "anchor.ai.analyst.analyze_detailed_acquisition_with_projection",
        wraps=analyze_detailed_acquisition_with_projection,
    ) as mock_analyze:
        ai_analyst_module.build_detailed_analysis_context(
            GOLDEN_TERMS,
            GOLDEN_DETAILED_OPERATING_INPUTS,
            target_levered_irr=0.10,
            target_equity_multiple=1.50,
            target_headline_dscr=1.20,
        )

    mock_analyze.assert_called_once_with(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)


def test_ai_analyst_delegates_to_the_authoritative_detailed_analysis_entry_points() -> None:
    with (
        patch(
            "anchor.ai.analyst.build_standard_detailed_presets",
            wraps=build_standard_detailed_presets,
        ) as mock_presets,
        patch(
            "anchor.ai.analyst.build_standard_detailed_break_even_analysis",
            wraps=build_standard_detailed_break_even_analysis,
        ) as mock_break_even,
    ):
        ai_analyst_module.build_detailed_analysis_context(
            GOLDEN_TERMS,
            GOLDEN_DETAILED_OPERATING_INPUTS,
            target_levered_irr=0.10,
            target_equity_multiple=1.50,
            target_headline_dscr=1.20,
        )

    mock_presets.assert_called_once_with(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS)
    mock_break_even.assert_called_once()


def test_provider_module_json_schema_never_hardcodes_a_numeric_metric_value() -> None:
    """The structured-output schema only ever describes string/array-of-
    string fields -- the AI layer is never asked to return a number."""

    for field_schema in ai_provider_module.AI_ANALYSIS_JSON_SCHEMA["properties"].values():
        assert field_schema["type"] in ("string", "array")
        if field_schema["type"] == "array":
            assert field_schema["items"]["type"] == "string"
