"""Excel Export 1 -- the production ledger and architecture guards.

``docs/architecture/EXCEL_EXPORT_1_QUICK_FORMULA_AUDIT.md``. Every git query
reads objects only (protocol 11.2). The guards hold:

1. **the production ledger** -- exactly the declared backend and frontend
   files changed by Excel Export 1, now re-pinned by Excel Export 2 to its
   merged, committed range ``51c5bf1..b9437e4`` (PR #44 and the PR #45
   presentation polish). Frozen history: it describes what Export 1 changed
   and no longer moves with the working tree;
2. **no financial module changed** -- no engine, analysis, fingerprint,
   Business Plan, leasing, AI or ingestion module;
3. **nothing depends on the export** -- no production module but the API
   imports ``anchor.exports``, so no workbook formula can feed an application
   result;
4. **the export depends only on what it must** -- engine contracts and the
   pure debt functions, the stored-Deal read, the classification labels; no
   AI, no web framework, no workbook reader, no store write;
5. **the store read is read-only** and **the schema is unchanged** (v14);
6. **one route** exposes the export, and only for ``GET``.
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

#: ``main`` when Excel Export 1 began: PR #43 (Asset Types 1) merged, schema v14.
_BASE = "51c5bf1"

#: ``main`` when Excel Export 1 finished: PR #45, the header-separation polish
#: on top of PR #44. The ledger below is the diff between these two commits, so
#: it stays a record of Export 1 no matter what later gates add.
_MERGED = "b9437e4"

_BACKEND_FILES = frozenset(
    {
        "src/anchor/exports/__init__.py",
        "src/anchor/exports/excel/__init__.py",
        "src/anchor/exports/excel/filenames.py",
        "src/anchor/exports/excel/provenance.py",
        "src/anchor/exports/excel/quick_audit.py",
        "src/anchor/exports/excel/source.py",
        # One read-only function: the Quick analysis provenance read.
        "src/anchor/deals/store.py",
        # The one route, and the CORS header exposing its filename.
        "src/anchor/api.py",
    }
)

#: Every edit lands in a file the G37 list already ratifies; no new module.
_FRONTEND_FILES = frozenset(
    {
        "web/src/api.ts",
        "web/src/App.tsx",
        "web/src/components/DealHeader.tsx",
        "web/src/index.css",
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
)

#: Exactly what the export package may import from outside itself.
#:
#: Excel Export 2 moved the shared workbook machinery into ``_workbook``, so
#: the engine contracts and XlsxWriter are imported there rather than by
#: ``quick_audit``. The rule this guard exists for is unchanged: the package
#: reaches for engine *contracts* and the pure debt functions and nothing
#: else. ``test_excel_export_2_architecture`` holds the same map for the
#: package as a whole.
_EXPORT_IMPORTS = {
    "anchor.exports.excel.source": {
        # Excel Export 3 re-runs the authoritative Lease-Level analysis,
        # because a Lease-Level Deal stores none. It calls the same entry
        # point the analyze route calls and adds no second pathway.
        "anchor.analysis.business_plan_analysis",
        "anchor.asset_types",
        "anchor.business_plan",
        "anchor.contracts",
        "anchor.deals.store",
        "anchor.engine.contracts",
        "anchor.leasing",
        "anchor.leasing.validation",
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
    # Excel Export 3's module, on the same shared base. It reads the leasing
    # contracts it reproduces -- the calendar, the market-leasing resolver and
    # the enums -- and computes no financial result of its own.
    "anchor.exports.excel.lease_level_audit": {
        "anchor.leasing",
        "anchor.leasing.calendar",
        "anchor.leasing.contracts",
        "anchor.leasing.market",
    },
    "anchor.exports.excel.detailed_audit": set(),
    "anchor.exports.excel.filenames": set(),
    "anchor.exports.excel.provenance": set(),
    "anchor.exports.excel": set(),
    "anchor.exports": set(),
}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/src/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    """What Excel Export 1 changed: a diff between two commits, not against
    the working tree. Re-pinned at Excel Export 2, so a later gate's files
    cannot appear in -- or be hidden by -- this gate's ledger."""

    tracked = _git("diff", "--name-only", "--no-renames", base, _MERGED, "--", *paths).split()
    return {path for path in tracked if path}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(_SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    """Absolute names of every module ``path`` imports (relative imports
    resolved against its package)."""

    tree = ast.parse(path.read_bytes().decode("utf-8"))
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


def test_excel_export_1_changes_exactly_the_declared_backend_files() -> None:
    changed = {path for path in _changes_since(_BASE, "src") if _is_production(path)}
    assert changed == _BACKEND_FILES


def test_excel_export_1_changes_exactly_the_declared_frontend_files() -> None:
    changed = {path for path in _changes_since(_BASE, "web/src") if _is_production(path)}
    assert changed == _FRONTEND_FILES


def test_every_frontend_file_is_already_ratified_by_g37() -> None:
    from test_analysis_d4_6b_architecture import _PERMITTED_WEB  # noqa: PLC0415

    assert _FRONTEND_FILES <= _PERMITTED_WEB


# =============================================================================
# 2. No financial module changed
# =============================================================================


def test_no_financial_or_fingerprint_module_changed() -> None:
    changed = _changes_since(_BASE, *_UNCHANGED)
    assert changed == set()


# =============================================================================
# 3. Nothing depends on the export
# =============================================================================


def test_only_the_api_imports_the_export_package() -> None:
    importers = sorted(
        _module_name(path)
        for path in _production_modules()
        if _EXPORTS not in path.parents
        and any(name == "anchor.exports" or name.startswith("anchor.exports.") for name in _imports(path))
    )
    assert importers == ["anchor.api"]


def test_the_engine_does_not_load_the_export_or_a_workbook_writer() -> None:
    completed = subprocess.run(
        [
            "python",
            "-c",
            "import sys; import anchor.engine, anchor.engine.acquisition, anchor.engine.debt, "
            "anchor.engine.returns, anchor.analysis, anchor.deals, anchor.deals.store; "
            "loaded = sorted(m for m in sys.modules if m.startswith(('anchor.exports', 'xlsxwriter'))); "
            "assert not loaded, loaded",
        ],
        capture_output=True,
        cwd=_PROJECT_ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(_SRC)},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()


def test_xlsxwriter_is_used_only_by_the_export_package_and_is_declared() -> None:
    users = sorted(
        _module_name(path)
        for path in _production_modules()
        if any(name == "xlsxwriter" or name.startswith("xlsxwriter.") for name in _imports(path))
    )
    # One writer for both workbooks, in the shared module.
    assert users == ["anchor.exports.excel._workbook"]
    dependencies = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert any(dependency.lower().startswith("xlsxwriter") for dependency in dependencies)


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
    tree = ast.parse((_EXPORTS / "excel" / "source.py").read_text(encoding="utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("deals.store")
        for alias in node.names
    }
    # Excel Export 2 added the Detailed provenance read beside the Quick one,
    # and Excel Export 3 the Lease-Level one. All three are read-only
    # classifications or reads; none is a store write.
    assert names == {
        "DetailedAnalysisProvenance",
        "LeaseLevelExportProvenance",
        "QuickAnalysisProvenance",
        "QuickAnalysisState",
    }


def test_the_export_never_opens_a_workbook_or_names_ai() -> None:
    for path in _EXPORTS.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "load_workbook" not in text, path
        assert not re.search(r"\b(openai|generate_ai_analysis|AIAnalysis)\b", text), path


def test_the_export_resolves_no_business_plan() -> None:
    for path in _EXPORTS.rglob("*.py"):
        assert "resolve_business_plan" not in path.read_text(encoding="utf-8"), path


# =============================================================================
# 5. Read-only store read; schema unchanged
# =============================================================================


def _store_function(name: str) -> ast.FunctionDef:
    tree = ast.parse((_ANCHOR / "deals" / "store.py").read_bytes().decode("utf-8").replace("\r\n", "\n"))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def test_the_provenance_read_executes_only_select_and_calls_no_writer() -> None:
    function = _store_function("get_quick_analysis_provenance")
    sql = [
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.match(r"\s*[A-Z]+ ", node.value)
    ]
    assert sql and all(statement.strip().startswith("SELECT ") for statement in sql), sql
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    }
    writers = {name for name in called if name.startswith(("create_", "update_", "delete_", "put_", "set_", "_write", "_delete", "_insert"))}
    assert writers == set()


#: Excel Export 1's own reviewed head: the second parent of its merge into
#: `main` (PR #45, `b9437e4`). Named at P7.10 Stage 2 so the no-DDL guard below
#: reads this export's own committed range rather than the working tree, which a
#: later gate's migration legitimately changes.
_HEAD = "e228a3e93613b37c70c0c5bfe63fb02e0c335d46"


def test_the_schema_version_is_unchanged_and_no_ddl_was_added() -> None:
    """**This export** adds no DDL and no schema version change.

    Re-pinned at P7.10 Stage 2: measured against the working tree, the diff read
    that separately ratified gate's additive migration as this one's. It is not
    -- that gate has its own ledger and its own additive-migration proof.
    Measured over this export's own committed range, the claim is exactly what
    it always was."""

    store = (_ANCHOR / "deals" / "store.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert re.search(r"^_SCHEMA_VERSION = 17$", store, re.M)  # Refinance V1 Stage 2
    added = [
        line[1:]
        for line in _git(
            "diff", "--no-renames", "-U0", _BASE, _HEAD, "--", "src/anchor/deals/store.py"
        ).splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    assert added, "the ledger says store.py changed"
    for line in added:
        assert not re.search(r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE)\b", line), line


# =============================================================================
# 6. One route
# =============================================================================


def test_the_quick_export_is_exposed_by_exactly_one_get_route() -> None:
    """One route per mode, ``GET`` only. Excel Export 2 added the Detailed
    route beside this one; ``test_excel_export_2_architecture`` pins the whole
    set."""

    routes = sorted(
        (sorted(getattr(route, "methods", None) or ()), str(getattr(route, "path", "")))
        for route in app.routes
        if "/exports/" in str(getattr(route, "path", ""))
    )
    assert (["GET"], "/deals/{deal_id}/exports/quick-underwrite.xlsx") in routes
    assert [path for _methods, path in routes].count(
        "/deals/{deal_id}/exports/quick-underwrite.xlsx"
    ) == 1
