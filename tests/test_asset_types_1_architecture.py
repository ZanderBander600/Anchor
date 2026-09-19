"""Asset Types 1 -- the production ledger and architecture guards.

``docs/architecture/ASSET_TYPES_1_CLASSIFICATION.md`` Sections 6 and 8. Every
git query reads objects only (protocol 11.2). The guards hold:

1. **the Asset Types 1 production ledger** -- exactly the declared backend and
   frontend files changed since ``main`` at ``2e6ca8e``. Measured against the
   working tree while the gate is open, including untracked files; the next
   gate re-pins it to the merged, committed range exactly as the AM1 ledger was
   re-pinned at the P7.9 closeout;
2. **no financial module changed** -- no engine, analysis, leasing, Business
   Plan, Capital Structure, Partnership, consolidation, Investment, decision,
   AI, ingestion or fingerprint module, and not the AM1 performance engine;
3. **classification is outside every fingerprint and the AI grounding** -- no
   fingerprint, variant, engine or AI module names it, and the fingerprint
   route owns no classification key;
4. **the Managed Asset snapshot is frozen by construction** -- no SQL in the
   store can update a Managed Asset's classification after the INSERT;
5. **the vocabulary has one canonical representation** -- the frontend's wire
   values and labels are the backend's;
6. **the classification modules compute nothing and reach no AI**.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from anchor.asset_types import ASSET_TYPE_LABELS, MAX_ASSET_SUBTYPE_LENGTH, AssetType

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when Asset Types 1 began: PR #42 merged, schema v13.
_BASE = "2e6ca8e"

_STORE = "src/anchor/deals/store.py"
_API = "src/anchor/api.py"
_MODULE = "src/anchor/asset_types.py"

#: Every backend production file Asset Types 1 changes, exactly:
#: - ``asset_types.py`` (new): the vocabulary, the subtype rules, the parser;
#: - ``deals/contracts.py``: two metadata fields on ``Deal``;
#: - ``deals/store.py``: schema v14, the two classification tables, their I/O;
#: - ``api.py``: classification on ``/deals`` and the retired property type;
#: - ``asset_management/contracts.py`` and ``validation.py``: the snapshot
#:   fields on ``ManagedAsset`` and the retirement of the hand-typed field.
_BACKEND_FILES = frozenset(
    {
        _MODULE,
        "src/anchor/deals/contracts.py",
        _STORE,
        _API,
        "src/anchor/asset_management/contracts.py",
        "src/anchor/asset_management/validation.py",
    }
)

#: Every frontend production file Asset Types 1 changes, exactly. Two are new
#: (``assetTypes.ts``, ``components/AssetClassification.tsx``); the rest thread
#: classification through surfaces that already exist. ``hiddenIssuesFixture.ts``
#: is production-named test data (the G37 list names it for the same reason).
_FRONTEND_FILES = frozenset(
    {
        "web/src/assetTypes.ts",
        "web/src/components/AssetClassification.tsx",
        "web/src/App.tsx",
        "web/src/api.ts",
        "web/src/types.ts",
        "web/src/index.css",
        "web/src/useLeaseLevelDeal.ts",
        "web/src/useManagedAssets.ts",
        "web/src/assetManagementTypes.ts",
        "web/src/assetManagementFixture.ts",
        "web/src/hiddenIssuesFixture.ts",
        "web/src/components/UnderwriteWorkspace.tsx",
        "web/src/components/LeaseLevelWorkspace.tsx",
        "web/src/components/DealLibraryPanel.tsx",
        "web/src/components/InvestmentLibraryPanel.tsx",
        "web/src/components/InvestmentUnitsPanel.tsx",
        "web/src/components/AssetManagementShell.tsx",
        "web/src/components/ManagedAssetWorkspace.tsx",
        "web/src/components/CreateManagedAssetPanel.tsx",
    }
)

#: Consumed and never changed by a classification gate.
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
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/report.py",
    "src/anchor/formatting.py",
    "src/anchor/asset_management/performance.py",
    "src/anchor/asset_management/__init__.py",
    "src/anchor/deals/__init__.py",
    "src/anchor/deals/fingerprint.py",
    "src/anchor/deals/variants.py",
    "src/anchor/deals/investment_variants.py",
    "src/anchor/deals/structured_variants.py",
    "src/anchor/deals/partnership_variants.py",
    "src/anchor/deals/partnership_codec.py",
    "src/anchor/deals/capital_structure_codec.py",
    "src/anchor/deals/position_identity.py",
    "src/anchor/deals/decision_matrix.py",
    "web/src/convert.ts",
    "web/src/leaseLevelConvert.ts",
    "web/src/format.ts",
    "web/src/liveMetrics.ts",
    "web/src/ownerSummary.ts",
    "web/src/components/AiAnalystPanel.tsx",
)


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


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _function(path: str, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(ast.parse(_current(path)))
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


_SQL_VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")


def _sql_strings(node: ast.AST) -> list[str]:
    """Every string constant that is a SQL statement -- docstrings and comments
    that merely mention a table are not."""

    return [
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant)
        and isinstance(item.value, str)
        # Upper-case, as every statement in the store is: a docstring that
        # begins "Create the Managed Asset" is prose, not SQL.
        and item.value.strip().startswith(tuple(f"{verb} " for verb in _SQL_VERBS))
    ]


# =============================================================================
# 1. The production ledger
# =============================================================================


def test_asset_types_1_changes_exactly_the_declared_backend_files() -> None:
    changed = {path for path in _changes_since(_BASE, "src") if _is_production(path)}
    assert changed == _BACKEND_FILES


def test_asset_types_1_changes_exactly_the_declared_frontend_files() -> None:
    changed = {path for path in _changes_since(_BASE, "web/src") if _is_production(path)}
    assert changed == _FRONTEND_FILES


def test_the_ledger_would_reject_an_undeclared_file() -> None:
    """The comparison is exact, so a neighbouring module could not slip in."""

    intruder = "src/anchor/asset_type_benchmarks.py"
    assert intruder not in _BACKEND_FILES
    assert ({*_BACKEND_FILES, intruder} == _BACKEND_FILES) is False


@pytest.mark.parametrize("path", _UNCHANGED)
def test_no_financial_or_ai_module_changed(path: str) -> None:
    assert _changes_since(_BASE, path) == set()


# =============================================================================
# 2. Classification is outside every fingerprint, engine and AI input
# =============================================================================

_CLASSIFICATION_NAMES = re.compile(r"asset_type|asset_subtype|AssetType|AssetClassification|asset_types")


@pytest.mark.parametrize(
    "path",
    [
        "src/anchor/deals/fingerprint.py",
        "src/anchor/deals/variants.py",
        "src/anchor/deals/investment_variants.py",
        "src/anchor/deals/structured_variants.py",
        "src/anchor/deals/partnership_variants.py",
        "src/anchor/deals/decision_matrix.py",
        "src/anchor/asset_management/performance.py",
    ],
)
def test_no_fingerprint_variant_or_performance_module_names_classification(path: str) -> None:
    assert not _CLASSIFICATION_NAMES.search(_current(path)), path


@pytest.mark.parametrize("package", ["engine", "analysis", "leasing", "ai", "business_plan"])
def test_no_engine_or_ai_package_names_classification(package: str) -> None:
    for source in sorted((_PROJECT_ROOT / "src" / "anchor" / package).rglob("*.py")):
        text = source.read_bytes().decode("utf-8")
        assert not _CLASSIFICATION_NAMES.search(text), source


def test_the_fingerprint_route_reads_no_classification() -> None:
    route = ast.unparse(_function(_API, "deal_fingerprint"))
    assert "_deal_classification" not in route
    assert "_DEAL_WRITE_FIELDS" not in route
    assert "asset_type" not in route


def test_the_fingerprint_route_owns_no_classification_key() -> None:
    """``_DEAL_FIELDS`` -- what ``/deals/fingerprint`` declares beside the
    Lease-Level inputs -- stays exactly as it was; only the write routes' own
    ``_DEAL_WRITE_FIELDS`` names the classification keys."""

    tree = ast.parse(_current(_API))
    values = {
        target.id: ast.literal_eval(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in ("_DEAL_FIELDS", "_DEAL_WRITE_FIELDS")
    }
    assert values["_DEAL_FIELDS"] == ("name", "deal_context")
    assert values["_DEAL_WRITE_FIELDS"] == ("name", "deal_context", "asset_type", "asset_subtype")


def test_classification_is_read_by_no_row_converter_fingerprint() -> None:
    """The three row converters build the fingerprint from inputs and plan
    only; the classification is attached to the ``Deal`` and never passed to
    a ``fingerprint_*`` call."""

    for name in ("_row_to_deal", "_row_to_detailed_deal", "_row_to_lease_level_deal"):
        function = _function(_STORE, name)
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id.startswith("fingerprint_")
            ):
                assert "classification" not in ast.unparse(node), (name, ast.unparse(node))


# =============================================================================
# 3. Storage: additive, typed, and a frozen snapshot
# =============================================================================


def test_the_schema_is_v14_and_the_migration_alters_nothing() -> None:
    source = _current(_STORE)
    assert "_SCHEMA_VERSION = 14" in source
    for sql in _sql_strings(_function(_STORE, "_migrate")):
        if "ALTER TABLE" in sql.upper():
            assert "classification" not in sql and "managed_assets" not in sql, sql
    connect = ast.unparse(_function(_STORE, "_connect"))
    assert "_CREATE_DEAL_ASSET_CLASSIFICATIONS_TABLE_SQL" in connect
    assert "_CREATE_MANAGED_ASSET_CLASSIFICATIONS_TABLE_SQL" in connect


def test_no_sql_can_rewrite_a_managed_assets_classification() -> None:
    """Frozen by construction, like the budget: the only statements that name
    the snapshot table are the create path's INSERT, the reads and the owned
    delete."""

    statements = [
        sql
        for sql in _sql_strings(ast.parse(_current(_STORE)))
        if "managed_asset_classifications" in sql and not sql.strip().upper().startswith("CREATE TABLE")
    ]
    verbs = sorted(sql.strip().split()[0].upper() for sql in statements)
    assert verbs == ["DELETE", "INSERT", "SELECT", "SELECT"], statements
    inserts = [sql for sql in statements if sql.strip().upper().startswith("INSERT")]
    create = ast.unparse(_function(_STORE, "create_managed_asset"))
    assert all(sql.split("(")[0].strip() in create for sql in inserts)


def test_the_deal_classification_is_written_in_one_place() -> None:
    writes = [
        sql
        for sql in _sql_strings(ast.parse(_current(_STORE)))
        if "deal_asset_classifications" in sql and sql.strip().split()[0].upper() in ("INSERT", "UPDATE", "DELETE")
    ]
    writer = ast.unparse(_function(_STORE, "_write_deal_classification"))
    assert len(writes) == 2
    assert all(sql in writer for sql in writes)


# =============================================================================
# 4. One canonical vocabulary
# =============================================================================


def test_the_frontend_vocabulary_is_the_backends() -> None:
    source = _current("web/src/assetTypes.ts")
    values = re.search(r"export const ASSET_TYPES = \[(.*?)\] as const;", source, re.DOTALL)
    assert values is not None
    assert re.findall(r"'([a-z_]+)'", values.group(1)) == [member.value for member in AssetType]

    labels = re.search(r"export const ASSET_TYPE_LABELS: Record<AssetType, string> = \{(.*?)\};", source, re.DOTALL)
    assert labels is not None
    assert dict(re.findall(r"([a-z_]+): '([^']+)'", labels.group(1))) == {
        member.value: label for member, label in ASSET_TYPE_LABELS.items()
    }
    assert f"ASSET_SUBTYPE_MAX_LENGTH = {MAX_ASSET_SUBTYPE_LENGTH};" in source


# =============================================================================
# 5. The classification modules compute nothing and reach no AI
# =============================================================================


def test_the_backend_module_imports_only_the_standard_library() -> None:
    tree = ast.parse(_current(_MODULE))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported == {"__future__", "unicodedata", "dataclasses", "enum"}
    # ``X | None`` in an annotation is a ``BitOr``; any other operator would be
    # arithmetic this module has no business doing.
    arithmetic = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AugAssign)
        or (isinstance(node, ast.BinOp) and not isinstance(node.op, ast.BitOr))
    ]
    assert arithmetic == []


@pytest.mark.parametrize("path", ["web/src/assetTypes.ts", "web/src/components/AssetClassification.tsx"])
def test_the_frontend_modules_compute_no_figure_and_reach_no_ai(path: str) -> None:
    source = _current(path)
    code = "\n".join(
        line for line in source.split("\n") if not line.strip().startswith(("*", "/*", "//"))
    )
    # Copy is not code: "Land/Development" is a label, not a division.
    code = re.sub(r"'[^'\n]*'|`[^`]*`|\"[^\"\n]*\"", "''", code)
    # String concatenation for copy is the only `+` allowed; no figure is
    # multiplied, divided or subtracted.
    assert not re.search(r"[\w)\]]\s*[*/]\s*[\w(]", code.replace("*/", "")), path
    assert not re.search(r"\w\s+-\s+\w", code), path
    for token in ("analyze", "fingerprint", "/ai/", "openai", "purchase_price", "noi"):
        assert token not in code.lower(), (path, token)


def test_no_ai_prompt_or_grounding_mentions_classification() -> None:
    for source in sorted((_PROJECT_ROOT / "src" / "anchor" / "ai").rglob("*.py")):
        assert "asset type" not in source.read_bytes().decode("utf-8").lower(), source
