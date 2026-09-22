"""Excel Export 3 -- the production ledger and architecture guards.

``docs/architecture/EXCEL_EXPORT_3_LEASE_LEVEL_FORMULA_AUDIT.md``. Every git
query reads objects only (protocol 11.2). The guards hold:

1. **the production ledger** -- exactly the declared backend and frontend files
   changed between ``main`` at ``fe70d40`` (Excel Export 2 merged, PR #46) and
   this gate's own reviewed head. Re-pinned at P7.10 Stage 1 from the working
   tree to that merged, committed range, so the claim stays exactly true
   however far later gates build on it;
2. **no financial module changed** -- no engine, analysis, fingerprint,
   Business Plan, leasing, AI or ingestion module. The Lease-Level model is
   *reproduced* in Excel, never altered in Anchor;
3. **nothing depends on the export** -- no production module but the API
   imports ``anchor.exports``;
4. **the store read is read-only**, and **no schema migration was added**:
   Lease-Level keeps its deliberate absence of an ``analysis_snapshot``
   column, and this export does not introduce one;
5. **three routes**, one per supported mode, ``GET`` only;
6. **the shared base stayed shared** -- Quick and Detailed output is
   semantically unchanged, which ``test_excel_export_1_quick_audit.py`` and
   ``test_excel_export_2_detailed_audit.py`` prove in full.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from anchor.api import app

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
_ANCHOR = _SRC / "anchor"
_EXPORTS = _ANCHOR / "exports"

#: ``main`` when Excel Export 3 began: PR #46 (Excel Export 2) merged,
#: schema v14.
_BASE = "fe70d40"

#: Excel Export 3's own reviewed head: the second parent of its merge into
#: `main` (PR #47, `1afd003`).
#:
#: P7.10 Stage 1 re-pin. The backend and frontend ledgers below measured the
#: working tree, so they could only stay true while no later gate existed.
#: They now read Excel Export 3's own committed range -- the P7.9 Stage 2
#: precedent -- so each keeps proving exactly what this gate shipped, however
#: far later gates build on it. Nothing is weakened: the assertion is the same
#: equality, against the range that actually belongs to this gate.
_HEAD = "ab106171cab6f0033200a3e90ab42d4c70278b5d"

_BACKEND_FILES = frozenset(
    {
        # Excel Export 3 itself.
        "src/anchor/exports/excel/lease_level_audit.py",
        # The shared workbook base, gaining three default-preserving hooks.
        "src/anchor/exports/excel/_workbook.py",
        # Eligibility, the typed refusals and the re-run analysis.
        "src/anchor/exports/excel/source.py",
        "src/anchor/exports/excel/filenames.py",
        "src/anchor/exports/excel/__init__.py",
        # One read-only function: the Lease-Level export read.
        "src/anchor/deals/store.py",
        # The third route.
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

#: Not touched by this gate. The Lease-Level engine in particular: this export
#: reproduces it in Excel and must never adjust it to make a check pass.

#: P7.10 Stage 1 re-pin. The ratified P7.10 contract activates the existing
#: ``PctOfValue`` funding rule (decision R-E). These four Capital Structure
#: modules are the whole seam that change carries, so they leave this gate's
#: working-tree freeze and become P7.10's ledger. Nothing is weakened: the
#: assertion below still proves they were untouched from this gate through the
#: accepted baseline `9c65843`, and `tests/test_p7_10_stage_1_architecture.py`
#: proves the P7.10 change is confined to its declared definitions.
_P7_10_SEAM = tuple(
    f"src/anchor/capital_structure/{name}.py"
    for name in ("execution_contracts", "execution_validation", "funding", "execution")
)

#: The accepted repository baseline P7.10 Stage 1 starts from (PR #48).
_P7_10_BASE = "9c658437f76e8815cb228d4b71b11aaa473450d4"

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
    "src/anchor/exports/excel/quick_audit.py",
    "src/anchor/exports/excel/detailed_audit.py",
    "src/anchor/exports/excel/provenance.py",
    "web/src/convert.ts",
    "web/src/format.ts",
    "web/src/liveMetrics.ts",
    "web/src/underwrite.ts",
    "web/src/index.css",
)

_EXPORT_ROUTES = [
    (["GET"], "/deals/{deal_id}/exports/detailed-underwrite.xlsx"),
    (["GET"], "/deals/{deal_id}/exports/lease-level.xlsx"),
    (["GET"], "/deals/{deal_id}/exports/quick-underwrite.xlsx"),
]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/src/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_between(start: str, end: str, *paths: str) -> set[str]:
    """Files that differ between two commits, renames split into their removal
    and addition. Reads Git objects only."""

    return {path for path in _git("diff", "--name-only", "--no-renames", start, end, "--", *paths).split() if path}


def _source(path: Path) -> str:
    """Line endings and BOM normalised at this boundary (protocol 12)."""

    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(_SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
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


def test_excel_export_3_changes_exactly_the_declared_backend_files() -> None:
    changed = {path for path in _changes_between(_BASE, _HEAD, "src") if _is_production(path)}
    assert changed == _BACKEND_FILES


def test_excel_export_3_changes_exactly_the_declared_frontend_files() -> None:
    changed = {path for path in _changes_between(_BASE, _HEAD, "web/src") if _is_production(path)}
    assert changed == _FRONTEND_FILES


# =============================================================================
# 2. No financial module changed
# =============================================================================


def test_no_financial_or_engine_module_changed() -> None:
    """The point of an audit export is to reproduce the engine independently.
    Adjusting the engine to agree with the workbook would invert that.

    P7.10 Stage 1 re-pin: read over Excel Export 3's own committed range, so
    the claim stays exactly true. That the four P7.10 Capital Structure seam
    files were also untouched from here through the accepted baseline is
    proven separately below."""

    assert _changes_between(_BASE, _HEAD, *_UNCHANGED) == set()


@pytest.mark.parametrize("path", _P7_10_SEAM)
def test_each_p7_10_seam_module_was_unchanged_by_this_gate(path: str) -> None:
    """Excel Export 3's own claim, still proven: it left these four files
    byte-identical to its base, as did every gate through the accepted
    baseline `9c65843`."""

    assert _git("rev-parse", f"{_P7_10_BASE}:{path}").strip() == _git("rev-parse", f"{_BASE}:{path}").strip(), path


def test_the_export_never_computes_a_lease_level_financial_result() -> None:
    """The workbook module resolves market leasing through the D0 authority and
    enumerates the rollover lattice with integers. It must never call an
    analysis entry point or a leasing builder that produces dollars."""

    path = _EXPORTS / "excel" / "lease_level_audit.py"
    tree = ast.parse(_source(path))
    # Identifiers only: the module docstring names the entry points it
    # deliberately does not call, and prose is not a dependency.
    identifiers: set[str] = set(_imports(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
    for banned in (
        "build_recursive_rollover",
        "build_initial_vacancy_rollover",
        "build_lease_monthly_schedule",
        "build_monthly_property_projection",
        "build_property_expense_schedule",
        "build_recoverable_expense_pool",
        "aggregate_monthly_to_annual",
        "monthly_expense_recovery",
        "analyze_lease_level_acquisition_with_projection",
        "analyze_lease_level_acquisition_with_business_plan",
    ):
        assert banned not in identifiers, banned


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


def test_the_export_imports_no_web_framework_or_workbook_reader() -> None:
    for path in (_EXPORTS / "excel").glob("*.py"):
        names = _imports(path)
        for banned in ("fastapi", "starlette", "openpyxl", "openai", "anchor.ai"):
            assert not any(name.startswith(banned) for name in names), (path, banned)


# =============================================================================
# 4. The read is read-only, and no migration was added
# =============================================================================


def test_the_lease_level_export_read_calls_no_writer() -> None:
    """``get_lease_level_export_provenance`` selects and computes a
    fingerprint. It must not reach a function that writes."""

    tree = ast.parse(_source(_ANCHOR / "deals" / "store.py"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "get_lease_level_export_provenance"
    )
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    }
    for banned in ("executemany", "commit", "_write_lease_level_children", "_delete_lease_level_children"):
        assert banned not in called, banned
    assert "execute" not in called, "the read goes through _read_deal, not a raw execute"


def test_no_schema_migration_was_added() -> None:
    """Lease-Level Deals deliberately have no ``analysis_snapshot`` column.
    **This export** does not add one, and adds no migration of any kind.

    Measured over Excel Export 3's own committed range. Against the working tree
    it read the separately ratified P7.10 Stage 2 migration as this gate's, which
    it is not: that gate has its own ledger and its own additive-migration proof.
    The two standing claims about ``lease_level_deals`` still read the current
    tree, because they are claims about it now."""

    text = _source(_ANCHOR / "deals" / "store.py")
    assert "ALTER TABLE lease_level_deals" not in text
    assert re.search(r"lease_level_deals\s+ADD\s+COLUMN", text) is None
    added = _git("diff", _BASE, _HEAD, "--", "src/anchor/deals/store.py")
    for line in added.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        upper = line.upper()
        for banned in ("ALTER TABLE", "CREATE TABLE", "DROP TABLE", "SCHEMA_VERSION"):
            assert banned not in upper, line


# =============================================================================
# 5. The routes
# =============================================================================


def test_one_get_route_per_supported_mode() -> None:
    """**Re-pinned at P7.10 Stage 4.** Narrowed from every ``/exports/`` path to
    the workbook paths this gate is about.

    The subject has always been the formula-audit *workbooks*: one GET route per
    supported underwriting mode, each returning an ``.xlsx``. P7.10 Stage 4
    serves an Investment Committee memorandum PDF under the same word, which is
    a different artifact of a different gate."""

    routes = sorted(
        (sorted(getattr(route, "methods", None) or ()), str(getattr(route, "path", "")))
        for route in app.routes
        if "/exports/" in str(getattr(route, "path", ""))
        and str(getattr(route, "path", "")).endswith(".xlsx")
    )
    assert routes == _EXPORT_ROUTES


def test_each_export_owns_its_own_contract_version_and_refusals() -> None:
    from anchor.exports.excel import (
        DETAILED_EXPORT_CONTRACT_VERSION,
        EXPORT_CONTRACT_VERSION,
        LEASE_LEVEL_EXPORT_CONTRACT_VERSION,
    )
    from anchor.exports.excel.source import (
        DetailedAuditRefusalCode,
        LeaseLevelAuditRefusalCode,
        QuickAuditRefusalCode,
    )

    versions = {
        EXPORT_CONTRACT_VERSION,
        DETAILED_EXPORT_CONTRACT_VERSION,
        LEASE_LEVEL_EXPORT_CONTRACT_VERSION,
    }
    assert len(versions) == 3
    assert LeaseLevelAuditRefusalCode not in (DetailedAuditRefusalCode, QuickAuditRefusalCode)

    tokens = {code.value for code in LeaseLevelAuditRefusalCode}
    # Lease-Level has no saved analysis, so it has neither of these states --
    # the structural difference this export exists to handle honestly.
    assert "analysis_missing" not in tokens
    assert "analysis_stale" not in tokens
    assert {"terminal_value_not_capitalizable", "excel_capacity_exceeded"} <= tokens
    # The three shared tokens still mean the same thing on the wire.
    assert {"deal_not_found", "unsupported_operating_mode", "export_generation_failed"} <= tokens


# =============================================================================
# 6. The shared base stayed shared
# =============================================================================


def test_the_shared_base_hooks_default_to_the_published_eight_sheets() -> None:
    """Every hook added to ``_workbook.py`` must leave Quick and Detailed
    exactly as they were. The defaults are the proof at the source level; the
    two golden suites prove the output."""

    from anchor.exports.excel._workbook import SHEET_ORDER, _AuditWorkbookBase

    assert _AuditWorkbookBase.SHEETS == SHEET_ORDER
    assert _AuditWorkbookBase.OPERATING_SHEET == "Operating Projection"
    assert _AuditWorkbookBase.HAS_OPERATING_CAPITAL is False
    assert _AuditWorkbookBase._operating_capital_line(_AuditWorkbookBase) is None  # type: ignore[arg-type]


def test_quick_and_detailed_still_declare_the_published_eight() -> None:
    from anchor.exports.excel._workbook import SHEET_ORDER
    from anchor.exports.excel.detailed_audit import _DetailedAuditWorkbook
    from anchor.exports.excel.quick_audit import _QuickAuditWorkbook

    for workbook in (_QuickAuditWorkbook, _DetailedAuditWorkbook):
        assert workbook.SHEETS == SHEET_ORDER
        assert workbook.HAS_OPERATING_CAPITAL is False


def test_the_lease_level_workbook_declares_its_own_shape() -> None:
    from anchor.exports.excel import LEASE_LEVEL_SHEETS
    from anchor.exports.excel.lease_level_audit import _LeaseLevelAuditWorkbook

    assert _LeaseLevelAuditWorkbook.SHEETS == LEASE_LEVEL_SHEETS
    assert _LeaseLevelAuditWorkbook.OPERATING_SHEET == "Annual Projection"
    assert _LeaseLevelAuditWorkbook.HAS_OPERATING_CAPITAL is True
    assert "Lease-Level" in _LeaseLevelAuditWorkbook.SCOPE_NOTE
    for excluded in ("Quick Underwrite", "Partnership", "Asset Management"):
        assert excluded in _LeaseLevelAuditWorkbook.SCOPE_NOTE, excluded


def test_no_dependency_was_added() -> None:
    """XlsxWriter remains the only *workbook* writer; Excel Export 3 required
    nothing new.

    **Re-pinned at P7.10 Stage 4.** Compared across this gate's own committed
    range rather than against the working tree, so it keeps proving what Excel
    Export 3 did. P7.10 Stage 4 adds ReportLab for the Investment Committee
    memorandum PDF -- a different artifact, justified in that gate's own ledger,
    and not evidence about this one."""

    text = _git("show", f"{_HEAD}:pyproject.toml")
    baseline = _git("show", f"{_BASE}:pyproject.toml")
    assert text.replace("\r\n", "\n") == baseline.replace("\r\n", "\n")
