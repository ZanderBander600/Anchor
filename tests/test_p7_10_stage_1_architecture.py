"""Phase 7 Gate P7.10 Stage 1 -- the production ledger and architecture guards.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 2, 5, 6, 17
and 18.1. Every git query reads objects only (protocol 11.2). The guards hold:

1. **the Stage 1 production ledger**: exactly the new ``anchor.valuation``
   package and the four Capital Structure modules the ``PctOfValue`` seam
   touches, measured from ``main`` at ``9c65843``;
2. **the frozen upstream**, byte for byte, and every protected path unchanged;
3. **the four touched modules changed only at the declared seam** -- every
   other definition in them is identical to the accepted baseline's, so no
   debt, preferred, settlement, residual, return or metric formula moved;
4. **the dependency direction**: Capital Structure reads valuation, valuation
   reads the engine, and valuation never reads Capital Structure;
5. **no duplicated authority, no cash flow, and no later-stage surface** --
   no persistence, migration, schema version, route, memo, AI, PDF or
   frontend belongs to Stage 1.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.10 began: the 2026-09-20 acceptance-closeout merge (PR #48),
#: and the accepted repository baseline this gate starts from.
_P7_10_BASE = "9c658437f76e8815cb228d4b71b11aaa473450d4"
_P7_10_BASE_PARENTS = [
    "1afd003fa2b35df6f4ad50060d3fa5ae587fd1d7",
    "2e98937f8871392f7348aaa6bb8cf8e2728504ce",
]

_PACKAGE = "src/anchor/valuation"
_NAMES = ("__init__", "contracts", "validation", "engine", "funding")
_MODULES = tuple(f"{_PACKAGE}/{name}.py" for name in _NAMES)

_CAPITAL = "src/anchor/capital_structure"
#: The four Capital Structure modules the ``PctOfValue`` seam touches, and the
#: only pre-existing production files Stage 1 changes.
_SEAM_MODULES = tuple(
    f"{_CAPITAL}/{name}.py" for name in ("execution_contracts", "execution_validation", "funding", "execution")
)

#: Every production file Stage 1 changes, exactly (Section 17, Stage 1).
_STAGE_1_PRODUCTION_FILES = frozenset((*_MODULES, *_SEAM_MODULES))

#: The Capital Structure modules Stage 1 does not touch: the P7.7 contract and
#: foundation, and the P7.8 financial core -- the debt and preferred formulas,
#: the settlement metrics. Byte-identical to the accepted baseline.
_CAPITAL_FROZEN = tuple(
    f"{_CAPITAL}/{name}.py"
    for name in ("__init__", "contracts", "validation", "legacy", "foundation", "debt_position", "preferred", "metrics")
)

#: The upstream Stage 1 reads and changes none of.
_FROZEN = (
    "src/anchor/engine/debt.py",
    "src/anchor/engine/acquisition.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/returns.py",
    "src/anchor/engine/contracts.py",
    "src/anchor/engine/operating_projection.py",
    "src/anchor/consolidation/engine.py",
    "src/anchor/consolidation/contracts.py",
    "src/anchor/contracts.py",
    *(f"src/anchor/partnership/{name}.py" for name in ("contracts", "waterfall", "allocation", "accounts", "metrics")),
    *_CAPITAL_FROZEN,
)

#: Stage 2, 3 and 4 surfaces, and everything else upstream: unchanged.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/consolidation",
    "src/anchor/partnership",
    "src/anchor/investment",
    "src/anchor/deals",
    "src/anchor/decision",
    "src/anchor/analysis",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/asset_management",
    "src/anchor/exports",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/api.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/asset_types.py",
    "src/anchor/report.py",
    "src/anchor/cli.py",
    "src/anchor/__init__.py",
    "web",
)

#: The exact imports of each new module.
_IMPORTS: dict[str, set[str]] = {
    "__init__": {"__future__", ".contracts", ".engine", ".funding", ".validation"},
    "contracts": {"__future__", "dataclasses", "enum", "typing"},
    "validation": {"__future__", "collections", "math", ".contracts"},
    "engine": {"__future__", "..consolidation.contracts", "..contracts", "..engine.contracts", ".contracts", ".validation"},
    "funding": {"__future__", "dataclasses", "..engine.contracts", ".contracts"},
}

#: Exactly the top-level definitions of each seam module whose source P7.10
#: Stage 1 changes. Everything else in those four files is the accepted
#: baseline's, character for character.
_SEAM_CHANGES: dict[str, set[str]] = {
    f"{_CAPITAL}/execution_contracts.py": {"ExecutionIssueCode", "ResolvedFundingEvent"},
    f"{_CAPITAL}/execution_validation.py": {"_funding_issues", "_claim_issues", "validate_structured_execution"},
    f"{_CAPITAL}/funding.py": {"valuation_scope", "resolve_valuation_funding", "resolve_funding"},
    f"{_CAPITAL}/execution.py": {
        "_executable_positions",
        "schedule_position",
        "execute_unit_capital_structure",
        "execute_investment_capital_structure",
    },
}

#: Nothing Stage 1 writes may reach persistence, the wire, a document, a model
#: or the clock: it is a pure deterministic layer.
_FORBIDDEN_IMPORTS = re.compile(
    r"(^|\.)(api|store|deals|ai|ingestion|decision|analysis|investment|asset_management|exports|leasing"
    r"|business_plan|partnership)(\.|$)"
    r"|sqlite3|fastapi|pydantic|openai|httpx|requests|reportlab|weasyprint|openpyxl|xlsxwriter"
    r"|^(os|sys|pathlib|datetime|time|random|uuid|json|logging|secrets)$"
)

#: Vocabulary no Stage 1 module may contain: a later stage's surface, or a
#: causal attribution Section 5.6 forbids until a ratified decomposition
#: calculates one.
_FORBIDDEN_VOCABULARY = (
    "memo",
    "evidence_reference",
    "publish",
    "pdf",
    "prompt",
    "grounding",
    "schema_version",
    "migration",
    "fingerprint",
    "value_creation",
    "rent_growth",
    "renovation",
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    """Committed, staged, unstaged and untracked changes since ``base``, with
    renames split into their removal and addition.

    Stage 1's own ledger reads the working tree, because Stage 1 has not been
    merged. Stage 2 re-pins this to Stage 1's committed range, exactly as P7.9
    Stage 2 re-pinned P7.9 Stage 1's."""

    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _at_base(path: str) -> str:
    return _git("show", f"{_P7_10_BASE}:{path}").replace("\r\n", "\n")


def _tree(path: str) -> ast.Module:
    return ast.parse(_current(path))


def _module(name: str) -> str:
    return f"{_PACKAGE}/{name}.py"


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _imported_names(tree: ast.Module, module: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and "." * node.level + (node.module or "") == module
        for alias in node.names
    }


def _definitions(source: str) -> dict[str, str]:
    """Every top-level function and class, by name, as normalised source."""

    tree = ast.parse(source)
    return {
        node.name: ast.unparse(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _identifiers(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
    return found


# =============================================================================
# 1. The ledger
# =============================================================================


def test_stage_1_changes_exactly_the_declared_production_files() -> None:
    changed = {path for path in _changes_since(_P7_10_BASE, "src", "web") if _is_production(path)}
    assert sorted(changed - _STAGE_1_PRODUCTION_FILES) == []
    assert sorted(_STAGE_1_PRODUCTION_FILES - changed) == []


def test_the_ledger_base_is_the_accepted_closeout_merge() -> None:
    assert _git("rev-list", "--parents", "-n", "1", _P7_10_BASE).split()[1:] == _P7_10_BASE_PARENTS


def test_the_valuation_package_is_new_at_this_gate() -> None:
    assert _git("ls-tree", "-r", "--name-only", _P7_10_BASE, _PACKAGE).split() == []


def test_no_frontend_file_changed() -> None:
    """Stage 1 is backend only. A changed frontend file is a scope violation,
    not a guard to update."""

    assert _changes_since(_P7_10_BASE, "web") == set()


# =============================================================================
# 2. The frozen upstream
# =============================================================================


@pytest.mark.parametrize("path", _FROZEN)
def test_each_frozen_module_is_byte_identical_to_the_base(path: str) -> None:
    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_P7_10_BASE}:{path}").strip(), path


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged(path: str) -> None:
    assert _changes_since(_P7_10_BASE, path) == set(), path


# =============================================================================
# 3. The four seam modules changed only at the declared seam
# =============================================================================


@pytest.mark.parametrize("path", _SEAM_MODULES)
def test_each_seam_module_changed_only_its_declared_definitions(path: str) -> None:
    """The strongest guard this gate carries. The four Capital Structure
    modules are no longer byte-frozen, so this proves the change is confined:
    every top-level definition outside the declared seam is exactly the
    accepted baseline's, and none is added or removed beyond them."""

    before = _definitions(_at_base(path))
    after = _definitions(_current(path))
    declared = _SEAM_CHANGES[path]
    changed = {name for name in before.keys() & after.keys() if before[name] != after[name]}
    added = after.keys() - before.keys()
    removed = before.keys() - after.keys()
    assert removed == set(), path
    assert changed | added == declared, path


def test_no_settlement_residual_or_return_formula_moved() -> None:
    """Named explicitly: the functions that decide who is paid, in what order,
    out of what cash, and what they earned."""

    execution = _definitions(_current(f"{_CAPITAL}/execution.py"))
    baseline = _definitions(_at_base(f"{_CAPITAL}/execution.py"))
    for name in (
        "_settle_position",
        "_settle_scope",
        "_apply_closing",
        "_apply_settled",
        "_requirements",
        "_require_funded_closing",
        "_layers",
        "_position_returns",
        "_common_equity",
    ):
        assert execution[name] == baseline[name], name


# =============================================================================
# 4. The dependency direction
# =============================================================================


@pytest.mark.parametrize("name", _NAMES)
def test_each_module_imports_exactly_what_it_needs(name: str) -> None:
    imports = _imports(_tree(_module(name)))
    assert imports == _IMPORTS[name], name
    assert not {found for found in imports if _FORBIDDEN_IMPORTS.search(found)}, name


def test_the_valuation_package_never_reads_the_capital_structure() -> None:
    """The dependency runs one way. Capital Structure reads valuation; the
    valuation layer knows nothing about positions, priorities or claims, so no
    cycle and no second Capital Structure authority can appear."""

    for name in _NAMES:
        assert not any("capital_structure" in found for found in _imports(_tree(_module(name)))), name


def test_only_the_seam_modules_read_the_valuation_package() -> None:
    importers = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        if path.relative_to(_PROJECT_ROOT / "src" / "anchor").parts[0] != "valuation"
        and any(
            found.lstrip(".").split(".")[0] == "valuation" or found.startswith(("anchor.valuation", "..valuation"))
            for found in _imports(ast.parse(path.read_text(encoding="utf-8")))
        )
    )
    assert importers == [f"{_CAPITAL}/execution.py", f"{_CAPITAL}/execution_validation.py", f"{_CAPITAL}/funding.py"]


def test_upstream_names_are_calculation_free_contracts_and_one_named_helper() -> None:
    """``ensure_finite`` is the one upstream function the package calls, and
    it computes nothing: it raises on a non-finite result."""

    for name in _NAMES:
        tree = _tree(_module(name))
        assert _imported_names(tree, "..engine.contracts") <= {"AcquisitionResults", "ensure_finite"}, name
        assert _imported_names(tree, "..consolidation.contracts") <= {"ConsolidatedResults"}, name
        assert _imported_names(tree, "..contracts") <= {"AcquisitionTerms"}, name


# =============================================================================
# 5. No duplicated authority, no cash flow, no later-stage surface
# =============================================================================


def test_the_package_reproduces_no_upstream_engine() -> None:
    """It reads completed results. It never touches a cash-flow series, a
    debt schedule, an IRR, a Strategy, a Scenario or a consolidation."""

    forbidden = {
        "levered_cash_flows",
        "unlevered_cash_flows",
        "levered_owner_cash_flow_by_year",
        "annual_debt_service",
        "remaining_loan_balance",
        "irr",
        "unlevered_irr",
        "levered_irr",
        "equity_multiple",
        "initial_equity",
        "loan_amount",
        "transaction_price",
        "purchase_price",
    }
    for name in _NAMES:
        assert not forbidden & _identifiers(_tree(_module(name))), name


def test_only_exit_reports_sale_economics() -> None:
    """``disposition_costs`` and ``net_sale_proceeds`` appear only on the
    reserved Exit view, so no As-Is, Stabilized or Custom valuation can be
    read as producing sale proceeds."""

    for name in _NAMES:
        source = _current(_module(name))
        for word in ("disposition_costs", "net_sale_proceeds"):
            if word not in source:
                continue
            assert name in {"contracts", "engine", "__init__"}, name


def test_no_module_names_a_later_stage_surface() -> None:
    """Checked against the code's own vocabulary -- every identifier, argument
    and attribute -- not its prose. A docstring may name what Stage 1 excludes
    and why; nothing Stage 1 executes may."""

    for name in _NAMES:
        vocabulary = {identifier.lower() for identifier in _identifiers(_tree(_module(name)))}
        for word in _FORBIDDEN_VOCABULARY:
            offenders = sorted(found for found in vocabulary if word in found)
            assert offenders == [], (name, word, offenders)


def test_the_package_states_no_schema_version() -> None:
    assert _changes_since(_P7_10_BASE, "src/anchor/deals/store.py") == set()


def test_stage_1_adds_no_test_only_production_shim() -> None:
    """Every public name the package exports is used by the package itself or
    by the Capital Structure seam -- Stage 1 ships no surface that exists only
    for a later stage."""

    exported = {
        element.value
        for node in ast.walk(_tree("__init__".join((_PACKAGE + "/", ".py"))))
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        and isinstance(node.value, ast.List)
        for element in node.value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    defined: set[str] = set()
    for name in _NAMES:
        if name == "__init__":
            continue
        defined |= set(_definitions(_current(_module(name))))
    assert exported <= defined | {"ValuationMethod", "ValuationFundingResolution"}
