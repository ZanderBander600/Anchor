"""Excel Export 2 -- the production ledger and architecture guards.

``docs/architecture/EXCEL_EXPORT_2_DETAILED_FORMULA_AUDIT.md``. Every git query
reads objects only (protocol 11.2). The guards hold:

1. **the production ledger** -- exactly the declared backend and frontend
   files changed since ``main`` at ``b9437e4`` (Excel Export 1 merged, PR #45).
   Measured against the working tree while the gate is open, untracked files
   included; the next gate re-pins it to the merged, committed range;
2. **no financial module changed** -- no engine, analysis, fingerprint,
   Business Plan, leasing, AI or ingestion module. The Detailed operating
   model is *reproduced* in Excel, never altered in Anchor;
3. **nothing depends on the export** -- no production module but the API
   imports ``anchor.exports``, so no workbook formula can feed an application
   result;
4. **the export depends only on what it must** -- engine contracts and the
   pure debt functions, the stored-Deal read, the classification labels; no
   AI, no web framework, no workbook reader, no store write;
5. **the store reads are read-only** and **the schema is unchanged** (v14);
6. **two routes**, one per supported mode, ``GET`` only;
7. **the package does not broaden** into Lease-Level or any later export.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from pathlib import Path

from anchor.api import app

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
_ANCHOR = _SRC / "anchor"
_EXPORTS = _ANCHOR / "exports"

#: ``main`` when Excel Export 2 began: PR #45 (Excel Export 1 presentation
#: polish) merged, schema v14.
_BASE = "b9437e4"

_BACKEND_FILES = frozenset(
    {
        # The shared workbook machinery both exports are built on.
        "src/anchor/exports/excel/_workbook.py",
        # Excel Export 2 itself.
        "src/anchor/exports/excel/detailed_audit.py",
        # Quick, now expressed on the shared base -- byte-identical output.
        "src/anchor/exports/excel/quick_audit.py",
        "src/anchor/exports/excel/source.py",
        "src/anchor/exports/excel/filenames.py",
        "src/anchor/exports/excel/__init__.py",
        # One read-only function: the Detailed analysis provenance read.
        "src/anchor/deals/store.py",
        # The second route.
        "src/anchor/api.py",
    }
)

#: Every edit lands in a file the G37 list already ratifies; no new module.
_FRONTEND_FILES = frozenset(
    {
        "web/src/api.ts",
        "web/src/App.tsx",
    }
)

_UNCHANGED = (
    "src/anchor/engine",
    "src/anchor/analysis",
    "src/anchor/leasing",
    "src/anchor/business_plan",
    "src/anchor/capital_structure",
    "src/anchor/partnership",
    "src/anchor/consolidation",
    "src/anchor/investment",
    "src/anchor/decision",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/asset_management",
    "src/anchor/asset_types.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/excel_reader.py",
    "src/anchor/detailed_excel_reader.py",
    "src/anchor/deals/__init__.py",
    "src/anchor/deals/contracts.py",
    "src/anchor/deals/fingerprint.py",
    "src/anchor/deals/variants.py",
    "src/anchor/deals/investment_variants.py",
    "src/anchor/deals/decision_matrix.py",
    "web/src/convert.ts",
    "web/src/format.ts",
    "web/src/liveMetrics.ts",
    "web/src/underwrite.ts",
    "web/src/components/DealHeader.tsx",
    "web/src/index.css",
)

#: Exactly what the export package may import from outside itself.
_EXPORT_IMPORTS = {
    "anchor.exports.excel.source": {
        "anchor.asset_types",
        "anchor.business_plan",
        "anchor.contracts",
        "anchor.deals.store",
        "anchor.engine.contracts",
    },
    "anchor.exports.excel._workbook": {
        "anchor.engine.contracts",
        "anchor.engine.debt",
        "xlsxwriter",
        "xlsxwriter.format",
        "xlsxwriter.utility",
        "xlsxwriter.worksheet",
    },
    "anchor.exports.excel.quick_audit": set(),
    "anchor.exports.excel.detailed_audit": set(),
    "anchor.exports.excel.filenames": set(),
    "anchor.exports.excel.provenance": set(),
    "anchor.exports.excel": set(),
    "anchor.exports": set(),
}

_EXPORT_ROUTES = [
    (["GET"], "/deals/{deal_id}/exports/detailed-underwrite.xlsx"),
    (["GET"], "/deals/{deal_id}/exports/quick-underwrite.xlsx"),
]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/src/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(_SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _source(path: Path) -> str:
    """Source text, line endings and BOM normalised at this boundary
    (protocol 12), so a Windows checkout parses like any other."""

    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def _imports(path: Path) -> set[str]:
    """Absolute names of every module ``path`` imports (relative imports
    resolved against its package)."""

    tree = ast.parse(_source(path))
    package = _module_name(path).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                name = ".".join([*base, node.module] if node.module else base)
            else:
                name = node.module or ""
            found.add(name)
    return found


def _production_modules() -> list[Path]:
    return sorted(path for path in _ANCHOR.rglob("*.py") if "__pycache__" not in path.parts)


# =============================================================================
# 1. The production ledger
# =============================================================================


def test_excel_export_2_changes_exactly_the_declared_backend_files() -> None:
    changed = {path for path in _changes_since(_BASE, "src") if _is_production(path)}
    assert changed == _BACKEND_FILES


def test_excel_export_2_changes_exactly_the_declared_frontend_files() -> None:
    changed = {path for path in _changes_since(_BASE, "web/src") if _is_production(path)}
    assert changed == _FRONTEND_FILES


def test_every_frontend_file_is_already_ratified_by_g37() -> None:
    from test_analysis_d4_6b_architecture import _PERMITTED_WEB  # noqa: PLC0415

    assert _FRONTEND_FILES <= _PERMITTED_WEB


def test_no_source_file_carries_a_byte_order_mark() -> None:
    """A BOM makes a Python file unparseable to ``ast`` and invisible in a
    normal diff. Every file this gate touched is checked."""

    for path in sorted(_BACKEND_FILES | _FRONTEND_FILES):
        data = (_PROJECT_ROOT / path).read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf"), path


# =============================================================================
# 2. No financial module changed
# =============================================================================


def test_no_financial_or_fingerprint_module_changed() -> None:
    changed = _changes_since(_BASE, *_UNCHANGED)
    assert changed == set()


def test_the_detailed_operating_engine_is_untouched() -> None:
    """The workbook reproduces this module's conventions independently. If the
    gate had changed it, the reconciliation would be comparing Anchor with
    itself."""

    changed = _git(
        "diff",
        "--name-only",
        "--no-renames",
        _BASE,
        "--",
        "src/anchor/engine/operating_projection.py",
        "src/anchor/engine/noi.py",
        "src/anchor/engine/acquisition.py",
        "src/anchor/engine/debt.py",
        "src/anchor/engine/returns.py",
        "src/anchor/engine/contracts.py",
    ).split()
    assert changed == []


# =============================================================================
# 3. Nothing depends on the export
# =============================================================================


def test_only_the_api_imports_the_export_package() -> None:
    importers = sorted(
        _module_name(path)
        for path in _production_modules()
        if _EXPORTS not in path.parents
        and any(
            name == "anchor.exports" or name.startswith("anchor.exports.")
            for name in _imports(path)
        )
    )
    assert importers == ["anchor.api"]


def test_the_engine_does_not_load_the_export_or_a_workbook_writer() -> None:
    completed = subprocess.run(
        [
            "python",
            "-c",
            "import sys; import anchor.engine, anchor.engine.acquisition, anchor.engine.debt, "
            "anchor.engine.returns, anchor.engine.operating_projection, anchor.analysis, "
            "anchor.deals, anchor.deals.store; "
            "loaded = sorted(m for m in sys.modules if m.startswith(('anchor.exports', 'xlsxwriter'))); "
            "assert not loaded, loaded",
        ],
        capture_output=True,
        cwd=_PROJECT_ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(_SRC)},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()


def test_xlsxwriter_is_used_only_by_the_shared_workbook_module_and_is_declared() -> None:
    users = sorted(
        _module_name(path)
        for path in _production_modules()
        if any(name == "xlsxwriter" or name.startswith("xlsxwriter.") for name in _imports(path))
    )
    assert users == ["anchor.exports.excel._workbook"]
    dependencies = tomllib.loads(
        (_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["dependencies"]
    assert any(dependency.lower().startswith("xlsxwriter") for dependency in dependencies)


def test_no_new_dependency_was_introduced() -> None:
    added = [
        line[1:]
        for line in _git("diff", "--no-renames", "-U0", _BASE, "--", "pyproject.toml").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    assert added == []


# =============================================================================
# 4. The export depends only on what it must
# =============================================================================


def test_the_export_package_imports_exactly_the_declared_modules() -> None:
    found: dict[str, set[str]] = {}
    for path in sorted(_EXPORTS.rglob("*.py")):
        module = _module_name(path)
        external = {
            name
            for name in _imports(path)
            if name.startswith(("anchor.", "xlsxwriter", "openpyxl", "openai", "fastapi", "starlette"))
            and not name.startswith("anchor.exports")
        }
        found[module] = external
    assert found == _EXPORT_IMPORTS


def test_the_export_reads_the_store_only_through_the_provenance_types() -> None:
    tree = ast.parse(_source(_EXPORTS / "excel" / "source.py"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("deals.store")
        for alias in node.names
    }
    assert names == {
        "DetailedAnalysisProvenance",
        "QuickAnalysisProvenance",
        "QuickAnalysisState",
    }


def test_the_export_never_opens_a_workbook_or_names_ai() -> None:
    for path in _EXPORTS.rglob("*.py"):
        text = _source(path)
        assert "load_workbook" not in text, path
        assert not re.search(r"\b(openai|generate_ai_analysis|AIAnalysis)\b", text), path


def test_the_export_resolves_no_business_plan() -> None:
    """The D6.2 single-resolver invariant: the workbook shows the annual totals
    the saved analysis already holds, and never resolves a plan itself."""

    for path in _EXPORTS.rglob("*.py"):
        assert "resolve_business_plan" not in _source(path), path


def test_the_export_never_runs_an_authoritative_analysis() -> None:
    """No ``analyze_*`` entry point anywhere in the package: an export that
    recomputed Anchor's answer would be reconciling a number with itself."""

    for path in _EXPORTS.rglob("*.py"):
        text = _source(path)
        for forbidden in (
            "analyze_acquisition",
            "analyze_detailed_acquisition",
            "analyze_quick_acquisition",
            "build_detailed_operating_projection",
        ):
            assert forbidden not in text, (path, forbidden)


# =============================================================================
# 5. Read-only store reads; schema unchanged
# =============================================================================


def _store_function(name: str) -> ast.FunctionDef:
    tree = ast.parse(_source(_ANCHOR / "deals" / "store.py"))
    return next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_the_detailed_provenance_read_executes_only_select_and_calls_no_writer() -> None:
    function = _store_function("get_detailed_analysis_provenance")
    sql = [
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.match(r"\s*[A-Z]+ ", node.value)
    ]
    assert sql and all(statement.strip().startswith("SELECT ") for statement in sql), sql
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    }
    writers = {
        name
        for name in called
        if name.startswith(("create_", "update_", "delete_", "put_", "set_", "_write", "_delete", "_insert"))
    }
    assert writers == set()


def test_the_schema_version_is_unchanged_and_no_ddl_was_added() -> None:
    store = _source(_ANCHOR / "deals" / "store.py")
    assert re.search(r"^_SCHEMA_VERSION = 14$", store, re.M)
    added = [
        line[1:]
        for line in _git(
            "diff", "--no-renames", "-U0", _BASE, "--", "src/anchor/deals/store.py"
        ).splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    assert added, "the ledger says store.py changed"
    for line in added:
        assert not re.search(r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE)\b", line), line


def test_no_migration_was_added() -> None:
    added = [
        line[1:]
        for line in _git(
            "diff", "--no-renames", "-U0", _BASE, "--", "src/anchor/deals/store.py"
        ).splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    for line in added:
        assert "_migrate" not in line, line
        assert "PRAGMA user_version" not in line, line


# =============================================================================
# 6. Routes
# =============================================================================


def test_exactly_two_get_routes_expose_an_export() -> None:
    routes = sorted(
        (sorted(getattr(route, "methods", None) or ()), str(getattr(route, "path", "")))
        for route in app.routes
        if "/exports/" in str(getattr(route, "path", ""))
    )
    assert routes == _EXPORT_ROUTES


# =============================================================================
# 7. The package does not broaden
# =============================================================================


#: Vocabulary from the domains this export deliberately excludes. Matched
#: against *code* -- imports and identifiers -- never against prose, because
#: the workbook's own scope note names these domains in order to say they are
#: not exported.
_EXCLUDED_VOCABULARY = (
    "lease_level",
    "LeaseLevel",
    "rent_roll",
    "Suite",
    "Lease",
    "Investment",
    "Scenario",
    "Strategy",
    "CapitalStructure",
    "Partnership",
    "Waterfall",
    "ManagedAsset",
)


def _code_identifiers(path: Path) -> set[str]:
    """Every name this module imports, defines or reads -- string literals,
    comments and docstrings excluded."""

    tree = ast.parse(_source(path))
    names: set[str] = set(_imports(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def test_the_export_package_covers_only_quick_and_detailed() -> None:
    """No Lease-Level, Investment, Scenario, Strategy, Capital Structure,
    Partnership or Asset Management export has leaked in."""

    for path in _EXPORTS.rglob("*.py"):
        identifiers = _code_identifiers(path)
        for excluded in _EXCLUDED_VOCABULARY:
            offenders = {name for name in identifiers if excluded in name}
            assert offenders == set(), (path, excluded, offenders)


def test_the_scope_note_still_names_what_is_excluded() -> None:
    """The guard above reads code only, so the *prose* promise is pinned here:
    each workbook tells the analyst which modes it does not cover."""

    from anchor.exports.excel.detailed_audit import _DetailedAuditWorkbook
    from anchor.exports.excel.quick_audit import _QuickAuditWorkbook

    assert "Detailed Underwrite" in _QuickAuditWorkbook.SCOPE_NOTE
    assert "Lease-Level" in _QuickAuditWorkbook.SCOPE_NOTE
    for excluded in ("Quick Underwrite", "Lease-Level", "Partnership", "Asset Management"):
        assert excluded in _DetailedAuditWorkbook.SCOPE_NOTE, excluded


def test_the_export_package_holds_only_the_declared_modules() -> None:
    modules = sorted(
        path.name for path in (_EXPORTS / "excel").glob("*.py") if path.name != "__init__.py"
    )
    assert modules == [
        "_workbook.py",
        "detailed_audit.py",
        "filenames.py",
        "provenance.py",
        "quick_audit.py",
        "source.py",
    ]


def test_each_export_owns_its_own_contract_version_and_refusals() -> None:
    from anchor.exports.excel import DETAILED_EXPORT_CONTRACT_VERSION, EXPORT_CONTRACT_VERSION
    from anchor.exports.excel.source import DetailedAuditRefusalCode, QuickAuditRefusalCode

    assert EXPORT_CONTRACT_VERSION != DETAILED_EXPORT_CONTRACT_VERSION
    assert DetailedAuditRefusalCode is not QuickAuditRefusalCode
    # The same wire tokens, so one client vocabulary covers both.
    assert {code.value for code in DetailedAuditRefusalCode} == {
        code.value for code in QuickAuditRefusalCode
    }
