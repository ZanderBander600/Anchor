"""Architecture guardrails for the Excel ingestion layer (Quick's
``excel_reader.py``, Detailed Operating Model V2.1 Gate 10's
``detailed_excel_reader.py``, and the workbook-schema module they share).

Mirrors ``test_ingestion_architecture.py``'s AST-import-boundary style:
confirms Excel ingestion never imports the deterministic calculation
modules (``engine/``, ``analysis/``) or any AI/document-ingestion package,
and reproduces no financial formula (no ``math`` import) -- it produces
proposed assumptions only, per Gate 10's brief. Per the migration-risk
note in ``docs/detailed_operating_model_v2_1_architecture.md`` ("Excel
workbook format proliferation"), this guardrail file is added on the same
PR that introduces the second workbook format.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src" / "anchor"
_ENGINE_DIR = _SRC_DIR / "engine"
_ANALYSIS_DIR = _SRC_DIR / "analysis"

_EXCEL_INGESTION_MODULES = (
    _SRC_DIR / "excel_reader.py",
    _SRC_DIR / "detailed_excel_reader.py",
    _SRC_DIR / "workbook_schema.py",
)


def _imported_module_names(source_file: Path) -> list[str]:
    """Every module name a file imports, with relative imports (every
    Excel-ingestion/engine/analysis module uses only sibling-level relative
    imports, e.g. ``from .excel_reader import ...`` or ``from . import
    contracts``) resolved against the ``anchor`` package -- so an
    ``anchor.engine``/``anchor.analysis`` dependency can't hide behind a
    bare relative dot."""

    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    names.append(f"anchor.{node.module}")
                else:
                    names.extend(f"anchor.{alias.name}" for alias in node.names)
            elif node.module:
                names.append(node.module)
    return names


def test_excel_ingestion_modules_never_import_engine_or_analysis() -> None:
    for source_file in _EXCEL_INGESTION_MODULES:
        names = _imported_module_names(source_file)
        assert not any(name.startswith("anchor.engine") for name in names), (
            f"{source_file} must not import anchor.engine"
        )
        assert not any(name.startswith("anchor.analysis") for name in names), (
            f"{source_file} must not import anchor.analysis"
        )


def test_excel_ingestion_modules_never_import_ai_or_ingestion_packages() -> None:
    for source_file in _EXCEL_INGESTION_MODULES:
        names = _imported_module_names(source_file)
        assert not any(name.startswith("anchor.ai") for name in names), (
            f"{source_file} must not import anchor.ai"
        )
        assert not any(name == "anchor.ingestion" or name.startswith("anchor.ingestion.") for name in names), (
            f"{source_file} must not import anchor.ingestion"
        )


def test_excel_ingestion_modules_reproduce_no_financial_formula() -> None:
    for source_file in _EXCEL_INGESTION_MODULES:
        names = _imported_module_names(source_file)
        assert "math" not in names, f"{source_file} must not import math"


def test_engine_and_analysis_packages_do_not_import_excel_ingestion() -> None:
    """The dependency direction is one-way: Excel ingestion may import
    ``contracts``/``validation``, but nothing downstream ever imports back
    into an Excel reader."""

    for directory in (_ENGINE_DIR, _ANALYSIS_DIR):
        for source_file in directory.glob("*.py"):
            names = _imported_module_names(source_file)
            assert not any(
                name in ("anchor.excel_reader", "anchor.detailed_excel_reader", "anchor.workbook_schema")
                for name in names
            ), f"{source_file} must not import an Excel ingestion module"


def test_detailed_excel_reader_workbook_schema_is_the_sole_new_dependency() -> None:
    """Detailed Operating Model V2.1 Gate 10: the Detailed reader's only new
    intra-package dependency beyond ``contracts``/``validation`` (which
    Quick's reader already depends on) is the shared ``workbook_schema``
    module and ``excel_reader`` itself (for the handful of generic,
    field-agnostic helpers it reuses) -- never a second, parallel
    implementation of Quick's table-scanning primitives, and never a new
    dependency on ``openpyxl`` internals beyond what Quick's reader already
    uses."""

    names = set(_imported_module_names(_SRC_DIR / "detailed_excel_reader.py"))
    allowed_prefixes = ("anchor.contracts", "anchor.validation", "anchor.excel_reader", "anchor.workbook_schema")
    anchor_imports = {name for name in names if name.startswith("anchor.")}
    disallowed = {
        name
        for name in anchor_imports
        if not any(name == prefix or name.startswith(prefix + ".") for prefix in allowed_prefixes)
    }
    assert not disallowed, f"unexpected anchor-package dependency: {disallowed}"
