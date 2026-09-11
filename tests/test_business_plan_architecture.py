"""Architecture guardrails for the Phase 6 ``anchor.business_plan`` layer.

Gate D6.1, governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md``
Section 13. The dependency direction is::

    anchor.business_plan  ->  anchor.engine.contracts

and never the reverse. The engine will consume only the resolved
``OwnerCapitalSchedule``; it must never learn what a plan item, identifier,
description, category or model month is.

D6.1 is **unwired**: no acquisition-analysis path consumes a Business Plan, so
no D5 financial output can move. These tests are the mechanical proof. D6.2
owns the engine bridge and is expected to narrow the "unwired" and
"unchanged" clauses below by exactly what its own scope requires.

Mirrors ``test_leasing_architecture.py``: AST-parsed import graphs rather than
runtime imports, plus fresh-interpreter checks. Every git query runs against a
private copy of the index (protocol Section 11.2), so nothing here writes the
developer's index.
"""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
_ANCHOR_DIR = _SRC_DIR / "anchor"
_BUSINESS_PLAN_DIR = _ANCHOR_DIR / "business_plan"
_ENGINE_CONTRACTS = "src/anchor/engine/contracts.py"

#: ``main`` immediately before D6.1 -- the ratified D6 conventions merge.
_D6_BASE_COMMIT = "908499c"
#: The baselines of the two pre-existing whole-engine byte-identity guardrails
#: (G33 in ``test_analysis_d4_5b_architecture.py``, G37 in
#: ``test_analysis_d4_6b_architecture.py``), which D6.1 narrows by exactly
#: ``engine/contracts.py`` and which the additive-only claim below backs.
_D4_5A_COMMIT = "964c9a7"
_D4_6A_COMMIT = "15e910d"

#: The D5 production financial paths D6.1 must leave untouched (gate
#: specification Part W). ``src/anchor/engine`` as a whole is here except
#: ``contracts.py``, which is held to the stronger additive-only claim below.
_UNCHANGED_FINANCIAL_PATHS = (
    "src/anchor/engine/__init__.py",
    "src/anchor/engine/acquisition.py",
    "src/anchor/engine/returns.py",
    "src/anchor/engine/debt.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/operating_projection.py",
    "src/anchor/leasing",
    "src/anchor/analysis",
    "src/anchor/ai",
    "src/anchor/deals",
    "src/anchor/api.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "web",
)


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _imported_module_names(source_file: Path) -> list[str]:
    """Absolute and relative import targets declared in one module, relative
    ones resolved against the module's own package."""

    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    package_parts = source_file.resolve().relative_to(_SRC_DIR).parts[:-1]

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(package_parts)
                if node.level > 1:
                    base = base[: -(node.level - 1)]
                names.append(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                names.append(node.module)
    return names


def _referenced_names(node: ast.AST) -> set[str]:
    """Every identifier and attribute a node references (docstrings excluded)."""

    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            names.add(child.target.id)
    return names


def _git(arguments: list[str]) -> str:
    """One read-only git query against a private copy of the index."""

    index_path = subprocess.run(
        ["git", "rev-parse", "--git-path", "index"],
        capture_output=True,
        text=True,
        check=True,
        cwd=_PROJECT_ROOT,
    ).stdout.strip()
    with tempfile.TemporaryDirectory() as scratch:
        private_index = Path(scratch) / "index"
        shutil.copyfile(_PROJECT_ROOT / index_path, private_index)
        completed = subprocess.run(
            ["git", *arguments],
            capture_output=True,
            text=True,
            cwd=_PROJECT_ROOT,
            env={**os.environ, "GIT_INDEX_FILE": str(private_index)},
        )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _files_changed_since(commit: str, repo_relative: str) -> list[str]:
    """Tracked paths differing from ``commit`` plus untracked, unignored
    paths -- the same two questions G37 asks."""

    tracked = _git(["diff", "--name-only", commit, "--", repo_relative])
    untracked = _git(["ls-files", "--others", "--exclude-standard", "--", repo_relative])
    return sorted(
        {line.strip() for line in (*tracked.splitlines(), *untracked.splitlines()) if line.strip()}
    )


def _fresh_interpreter(statement: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    parts = [str(_SRC_DIR)]
    if existing := environment.get("PYTHONPATH"):
        parts.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(parts)
    return subprocess.run(
        [sys.executable, "-c", statement], capture_output=True, env=environment
    )


# =============================================================================
# 1. anchor.business_plan may depend only on the generic engine contracts
# =============================================================================


def test_business_plan_package_has_the_expected_modules() -> None:
    assert [path.name for path in _python_files(_BUSINESS_PLAN_DIR)] == [
        "__init__.py",
        "contracts.py",
        "resolver.py",
        "validation.py",
    ]


def test_business_plan_imports_only_stdlib_its_own_modules_and_engine_contracts() -> None:
    for source_file in _python_files(_BUSINESS_PLAN_DIR):
        for name in _imported_module_names(source_file):
            if not name.startswith("anchor"):
                continue
            assert name.startswith("anchor.business_plan") or name == "anchor.engine.contracts", (
                f"{source_file.name} imports {name}; anchor.business_plan may import "
                "only its own modules and anchor.engine.contracts"
            )


def test_business_plan_imports_no_external_package() -> None:
    """Pure domain logic: standard library only."""

    stdlib = sys.stdlib_module_names
    for source_file in _python_files(_BUSINESS_PLAN_DIR):
        for name in _imported_module_names(source_file):
            if name.startswith("anchor"):
                continue
            assert name.split(".")[0] in stdlib, f"{source_file.name} imports {name}"


def test_only_the_resolver_imports_the_engine_contract() -> None:
    """Contracts and validation are engine-free vocabulary; the resolver is
    the one bridge to the engine contract."""

    importers = sorted(
        source_file.name
        for source_file in _python_files(_BUSINESS_PLAN_DIR)
        if "anchor.engine.contracts" in _imported_module_names(source_file)
    )
    assert importers == ["resolver.py"]


# =============================================================================
# 2 / 3. Nothing else depends on anchor.business_plan -- engine and leasing
#        included
# =============================================================================


def test_no_module_outside_the_package_imports_anchor_business_plan() -> None:
    """Stated over the whole source tree, so an importer cannot appear in a
    package nobody thought to list. This covers acquisition, debt, returns,
    the rest of the engine, ``anchor.leasing``, analysis, deals, AI, the API
    and every top-level module."""

    importers = sorted(
        str(source_file.relative_to(_SRC_DIR)).replace("\\", "/")
        for source_file in _python_files(_ANCHOR_DIR)
        if _BUSINESS_PLAN_DIR not in source_file.parents
        and any(
            name == "anchor.business_plan" or name.startswith("anchor.business_plan.")
            for name in _imported_module_names(source_file)
        )
    )

    assert importers == [], f"anchor.business_plan is imported by {importers}"


def test_importing_the_engine_and_leasing_does_not_pull_in_the_business_plan() -> None:
    completed = _fresh_interpreter(
        "import sys; "
        "import anchor.engine, anchor.engine.acquisition, anchor.engine.debt, "
        "anchor.engine.returns, anchor.engine.contracts, anchor.leasing, "
        "anchor.analysis; "
        "assert 'anchor.business_plan' not in sys.modules, "
        "sorted(m for m in sys.modules if m.startswith('anchor.business_plan'))"
    )
    assert completed.returncode == 0, completed.stderr.decode()


# =============================================================================
# OwnerCapitalSchedule is a generic engine contract
# =============================================================================


#: Business Plan vocabulary the engine contract must never name.
_BUSINESS_PLAN_NAMES = frozenset(
    {
        "BusinessPlan",
        "CapitalPlanItem",
        "OwnerExpenseItem",
        "CapitalItemCategory",
        "OwnerExpenseCategory",
        "OwnerExpenseHoldTreatment",
        "item_id",
        "description",
        "category",
        "month",
        "first_year",
        "last_year",
        "business_plan",
    }
)


def _class_node(source: str, class_name: str) -> ast.ClassDef:
    return next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )


def test_owner_capital_schedule_lives_in_the_engine_contracts_module() -> None:
    from anchor.engine.contracts import OwnerCapitalSchedule

    assert OwnerCapitalSchedule.__module__ == "anchor.engine.contracts"
    assert list(OwnerCapitalSchedule.__dataclass_fields__) == [
        "closing_project_capital",
        "project_capital_by_year",
        "owner_expenses_by_year",
        "post_hold_project_capital",
    ]


def test_owner_capital_schedule_names_no_business_plan_concept() -> None:
    node = _class_node(
        (_PROJECT_ROOT / _ENGINE_CONTRACTS).read_text(encoding="utf-8"),
        "OwnerCapitalSchedule",
    )
    leaked = _referenced_names(node) & _BUSINESS_PLAN_NAMES
    assert not leaked, f"OwnerCapitalSchedule references {sorted(leaked)}"


def test_the_business_plan_package_does_not_re_export_the_engine_contract() -> None:
    import anchor.business_plan as business_plan

    assert "OwnerCapitalSchedule" not in business_plan.__all__


# =============================================================================
# 4. The Business Plan is not wired into acquisition analysis yet
# =============================================================================


def test_owner_capital_schedule_is_referenced_only_by_its_contract_and_resolver() -> None:
    """No engine calculator, analysis orchestrator, API or persistence module
    names the new contract. D6.2 owns the first consumer."""

    def mentions(source_file: Path) -> bool:
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        names = _referenced_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.alias):
                names.add(node.asname or node.name)
        return "OwnerCapitalSchedule" in names

    referencing = sorted(
        str(source_file.relative_to(_SRC_DIR)).replace("\\", "/")
        for source_file in _python_files(_ANCHOR_DIR)
        if mentions(source_file)
    )

    assert referencing == [
        "anchor/business_plan/resolver.py",
        "anchor/engine/contracts.py",
    ]


def test_acquisition_entry_points_take_no_business_plan() -> None:
    from anchor.analysis import lease_level
    from anchor.engine import acquisition

    assert list(
        inspect.signature(
            acquisition.analyze_acquisition_from_operating_projection
        ).parameters
    ) == ["operating_projection", "terms", "operating_capital"]
    for module in (acquisition, lease_level):
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("analyze"):
                continue
            for parameter in inspect.signature(function).parameters:
                assert "business_plan" not in parameter and "owner_capital" not in parameter, (
                    f"{module.__name__}.{name} takes {parameter!r}; D6.1 is unwired"
                )


# =============================================================================
# 5 / 6. No D5 production financial path, and no frontend file, changed
# =============================================================================


@pytest.mark.parametrize("path", _UNCHANGED_FINANCIAL_PATHS)
def test_d5_financial_paths_are_unchanged_since_the_d6_base(path: str) -> None:
    assert _files_changed_since(_D6_BASE_COMMIT, path) == [], f"{path} changed at D6.1"


def test_the_frontend_contains_no_business_plan_implementation() -> None:
    for source_file in sorted((_PROJECT_ROOT / "web" / "src").rglob("*")):
        if not source_file.is_file() or source_file.suffix not in {".ts", ".tsx"}:
            continue
        text = source_file.read_text(encoding="utf-8")
        for vocabulary in ("BusinessPlan", "business_plan", "OwnerCapitalSchedule", "ownerCapital"):
            assert vocabulary not in text, f"{source_file.name} mentions {vocabulary}"


@pytest.mark.parametrize(
    "baseline", [_D6_BASE_COMMIT, _D4_6A_COMMIT, _D4_5A_COMMIT], ids=["d6-base", "d4.6a", "d4.5a"]
)
def test_engine_contracts_changed_only_by_adding_owner_capital_schedule(baseline: str) -> None:
    """The stronger claim that replaces byte-identity for ``engine/contracts.py``.

    Removing the ``OwnerCapitalSchedule`` class from today's module must
    reproduce the baseline module's AST exactly: not one existing import,
    class, field, docstring or function was touched, and nothing else was
    added. This backs the D6.1 narrowing of G33 and G37.
    """

    baseline_tree = ast.parse(_git(["show", f"{baseline}:{_ENGINE_CONTRACTS}"]))
    current_tree = ast.parse((_PROJECT_ROOT / _ENGINE_CONTRACTS).read_text(encoding="utf-8"))

    def class_names(tree: ast.Module) -> list[str]:
        return [node.name for node in tree.body if isinstance(node, ast.ClassDef)]

    assert "OwnerCapitalSchedule" not in class_names(baseline_tree)
    assert class_names(current_tree).count("OwnerCapitalSchedule") == 1

    without_addition = ast.Module(
        body=[
            node
            for node in current_tree.body
            if not (isinstance(node, ast.ClassDef) and node.name == "OwnerCapitalSchedule")
        ],
        type_ignores=[],
    )
    assert ast.dump(without_addition) == ast.dump(baseline_tree), (
        f"engine/contracts.py changed by more than adding OwnerCapitalSchedule since {baseline}"
    )
