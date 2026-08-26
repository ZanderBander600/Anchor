"""Architecture guardrails for the Phase 9A AI Analyst layer.

Confirms the frozen engine never imports ``openai`` or ``mini_anchor.ai``,
that ``openai`` is imported only inside ``mini_anchor.ai.provider`` (never
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

from mini_anchor.ai import analyst as ai_analyst_module
from mini_anchor.ai import provider as ai_provider_module
from mini_anchor.analysis import build_standard_break_even_analysis, build_standard_presets
from mini_anchor.contracts import AcquisitionInputs
from mini_anchor.engine import analyze_acquisition

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
_ENGINE_DIR = _PROJECT_ROOT / "src" / "mini_anchor" / "engine"
_ANALYSIS_DIR = _PROJECT_ROOT / "src" / "mini_anchor" / "analysis"
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
        assert not any("mini_anchor.ai" in name for name in names), (
            f"{source_file} must not import mini_anchor.ai"
        )


def test_analysis_package_does_not_import_ai_package() -> None:
    for source_file in _ANALYSIS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any("mini_anchor.ai" in name for name in names), (
            f"{source_file} must not import mini_anchor.ai"
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
            "import sys; import mini_anchor.engine; assert 'openai' not in sys.modules",
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
        "mini_anchor.ai.analyst.analyze_acquisition", wraps=analyze_acquisition
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
            "mini_anchor.ai.analyst.build_standard_presets", wraps=build_standard_presets
        ) as mock_presets,
        patch(
            "mini_anchor.ai.analyst.build_standard_break_even_analysis",
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


def test_provider_module_json_schema_never_hardcodes_a_numeric_metric_value() -> None:
    """The structured-output schema only ever describes string/array-of-
    string fields -- the AI layer is never asked to return a number."""

    for field_schema in ai_provider_module.AI_ANALYSIS_JSON_SCHEMA["properties"].values():
        assert field_schema["type"] in ("string", "array")
        if field_schema["type"] == "array":
            assert field_schema["items"]["type"] == "string"
