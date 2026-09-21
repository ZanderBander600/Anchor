"""Phase 7 Gate P7.9 Stage 1 -- the production ledger and architecture guards.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 1.2, 2, 3, 12,
16.5 and 17.1. Every git query reads objects only (protocol 11.2). The guards
hold:

1. **the Stage 1 production ledger**: exactly the new ``anchor.partnership``
   package, measured from ``main`` at ``5cb327d``;
2. **the frozen upstream**, byte for byte, and every protected path unchanged;
3. **the seam and the dependency direction**: only ``common_equity`` reads
   Capital Structure results, only ``contracts`` imports two calculation-free
   shapes from it, only ``metrics`` imports ``anchor.engine.returns``, and
   nothing upstream imports the package;
4. **no role inference, no duplicate authority, no default**;
5. **no second solver, no I/O and no later-stage surface**.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when Stage 1 began: the P7.9 contract ratification merge (PR #33).
_P7_9_BASE = "5cb327d010a96eb84a9dbf9e8c7764abf23eec55"
_P7_9_BASE_PARENTS = ["79cb52461705e0acf4d9fe8d8682bf9cafc93b41", "2443c8218025d8195c10430d8e7f990796094637"]

#: Stage 1's reviewed head, merged into ``main`` as the second parent of the
#: Stage 1 merge (PR #34). Re-pinned at Stage 2: the ledger and the protected
#: paths below read Stage 1's own committed range ``5cb327d..c9dd78d``, so the
#: Stage 2 files never read as Stage 1 changes while every Stage 1 claim stays
#: proven. Stage 2's own ledger and freeze are
#: ``tests/test_p7_9_stage_2_architecture.py``.
_STAGE_1_HEAD = "c9dd78dd9f254fa9aec8dd3a33f61c29eb1e6cec"
_STAGE_1_MERGE = "70b92e2cdde29d2d2a1c5a19240bef91622a2219"

_PACKAGE = "src/anchor/partnership"
_NAMES = ("__init__", "contracts", "validation", "allocation", "accounts", "waterfall", "attribution", "metrics", "common_equity")
_MODULES = tuple(f"{_PACKAGE}/{name}.py" for name in _NAMES)

#: Every production file Stage 1 changes, exactly (Section 17.1).
_STAGE_1_PRODUCTION_FILES = frozenset(_MODULES)

#: The frozen upstream (Section 1.2): byte-identical to the base.
_FROZEN = (
    "src/anchor/engine/debt.py",
    "src/anchor/engine/acquisition.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/returns.py",
    "src/anchor/consolidation/engine.py",
    "src/anchor/deals/structured_variants.py",
    *(
        f"src/anchor/capital_structure/{name}.py"
        for name in (
            "__init__", "contracts", "validation", "legacy", "foundation", "debt_position", "preferred", "metrics",
        )
    ),
)

#: P7.10 Stage 1 re-pin. The ratified P7.10 contract activates the existing
#: ``PctOfValue`` funding rule (decision R-E), which this gate's own guards
#: predate. These four Capital Structure modules are the whole seam that
#: change carries, so they leave this gate's working-tree freeze and become
#: P7.10's ledger. Nothing is weakened: the assertion below still proves they
#: were untouched from this gate through the accepted baseline `9c65843`, and
#: `tests/test_p7_10_stage_1_architecture.py` proves the P7.10 change is
#: confined to its declared definitions -- no settlement, residual, debt,
#: preferred, return or metric formula moved.
_P7_10_SEAM = tuple(
    f"src/anchor/capital_structure/{name}.py"
    for name in ("execution_contracts", "execution_validation", "funding", "execution")
)

#: The accepted repository baseline P7.10 Stage 1 starts from (PR #48).
_P7_10_BASE = "9c658437f76e8815cb228d4b71b11aaa473450d4"


@pytest.mark.parametrize("path", _P7_10_SEAM)
def test_each_p7_10_seam_module_was_frozen_through_the_accepted_baseline(path: str) -> None:
    """P7.9 Stage 1's claim, still proven: these four files were byte-identical
    to this gate's base from P7.9 through the accepted baseline `9c65843`. Only
    the separately ratified P7.10 Stage 1 changes them."""

    assert _git("rev-parse", f"{_P7_10_BASE}:{path}").strip() == _git("rev-parse", f"{_P7_9_BASE}:{path}").strip(), path

#: Stage 2 and Stage 3 surfaces, and everything upstream: unchanged.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/consolidation",
    "src/anchor/capital_structure",
    "src/anchor/investment",
    "src/anchor/deals",
    "src/anchor/decision",
    "src/anchor/analysis",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/api.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/__init__.py",
    "web",
)

#: The exact imports of each module (Section 16.5).
_IMPORTS: dict[str, set[str]] = {
    "__init__": {"__future__", ".common_equity", ".contracts", ".validation", ".waterfall"},
    "contracts": {"__future__", "collections.abc", "dataclasses", "enum", "..capital_structure.contracts", "..engine.contracts"},
    "validation": {"__future__", "collections", "collections.abc", "math", ".contracts"},
    "allocation": {"__future__", "collections.abc", ".contracts"},
    "accounts": {"__future__", "dataclasses", ".contracts"},
    "waterfall": {"__future__", "dataclasses", "math", ".", ".contracts", ".validation"},
    "attribution": {"__future__", "collections.abc", "dataclasses", ".contracts"},
    "metrics": {"__future__", "dataclasses", "..engine.contracts", "..engine.returns", ".contracts"},
    "common_equity": {
        "__future__", "..capital_structure.contracts", "..capital_structure.execution_contracts", ".contracts", ".waterfall",
    },
}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_between(start: str, end: str, *paths: str) -> set[str]:
    """Files that differ between two commits, renames split into their removal
    and addition. Reads Git objects only."""

    return {path for path in _git("diff", "--name-only", "--no-renames", start, end, "--", *paths).split() if path}


def _changes_since(base: str, *paths: str) -> set[str]:
    """Committed, staged, unstaged and untracked changes since ``base``, with
    renames split into their removal and addition."""

    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


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


def _enclosing_functions(tree: ast.Module) -> dict[ast.AST, str]:
    owners: dict[ast.AST, str] = {}
    for function in ast.walk(tree):
        if isinstance(function, ast.FunctionDef):
            for node in ast.walk(function):
                owners.setdefault(node, function.name)
    return owners


# =============================================================================
# 1. The ledger
# =============================================================================


def test_stage_1_changed_exactly_the_partnership_package() -> None:
    changed = {path for path in _changes_between(_P7_9_BASE, _STAGE_1_HEAD, "src", "web") if _is_production(path)}
    assert sorted(changed - _STAGE_1_PRODUCTION_FILES) == []
    assert sorted(_STAGE_1_PRODUCTION_FILES - changed) == []


def test_the_ledger_base_is_the_contract_ratification_merge() -> None:
    assert _git("rev-list", "--parents", "-n", "1", _P7_9_BASE).split()[1:] == _P7_9_BASE_PARENTS


def test_the_ledger_head_is_the_second_parent_of_the_stage_1_merge() -> None:
    assert _git("rev-list", "--parents", "-n", "1", _STAGE_1_MERGE).split()[1:] == [_P7_9_BASE, _STAGE_1_HEAD]


def test_the_package_is_new_at_this_gate() -> None:
    assert _git("ls-tree", "-r", "--name-only", _P7_9_BASE, _PACKAGE).split() == []


# =============================================================================
# 2. The frozen upstream
# =============================================================================


@pytest.mark.parametrize("path", _FROZEN)
def test_each_frozen_module_is_byte_identical_to_the_base(path: str) -> None:
    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_P7_9_BASE}:{path}").strip(), path


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged(path: str) -> None:
    """Within Stage 1's own committed range (re-pinned at Stage 2, whose
    persistence, API and matrix surfaces are these paths)."""

    assert _changes_between(_P7_9_BASE, _STAGE_1_HEAD, path) == set(), path


# =============================================================================
# 3. The seam and the dependency direction
# =============================================================================


@pytest.mark.parametrize("name", _NAMES)
def test_each_module_imports_exactly_what_it_needs(name: str) -> None:
    assert _imports(_tree(_module(name))) == _IMPORTS[name], name


def test_only_the_seam_reads_capital_structure_results() -> None:
    readers = {
        name for name in _NAMES
        if any("capital_structure" in module for module in _imports(_tree(_module(name))))
    }
    assert readers == {"contracts", "common_equity"}
    assert _imported_names(_tree(_module("contracts")), "..capital_structure.contracts") == {
        "AccrualConvention", "CommonEquityUnavailableReason",
    }
    assert _imported_names(_tree(_module("common_equity")), "..capital_structure.execution_contracts") == {"StructuredCapitalResult"}


def test_the_seam_never_reads_a_project_levered_series() -> None:
    for name in _NAMES:
        tree = _tree(_module(name))
        # ``levered_cash_flows=`` is the unchanged returns functions' own
        # keyword; it may be passed, never read.
        identifiers = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if isinstance(node, (ast.Name, ast.Attribute))
        }
        assert not {"levered_cash_flows", "unlevered_cash_flows", "AcquisitionResults", "ConsolidatedResults"} & identifiers, name
    seam = _tree(_module("common_equity"))
    reads = {node.attr for node in ast.walk(seam) if isinstance(node, ast.Attribute)}
    assert {"common_equity", "cash_flows", "funding_requirements", "hold_period"} <= reads


def test_only_metrics_imports_the_returns_functions() -> None:
    importers = {name for name in _NAMES if "..engine.returns" in _imports(_tree(_module(name)))}
    assert importers == {"metrics"}
    assert _imported_names(_tree(_module("metrics")), "..engine.returns") == {
        "calculate_equity_multiple", "calculate_project_return_totals", "evaluate_irr",
    }


#: Exactly the modules outside the package that import it. Stage 1 had none;
#: Stage 2 (Section 17.2) connects it to the Strategy root overlay, the
#: Partnership persistence, codec, fingerprint and variant service, the
#: PARTNER comparison and matrix, and the routes -- and to nothing that
#: calculates project, structured or position economics.
_PARTNERSHIP_IMPORTERS = [
    "src/anchor/analysis/strategy.py",
    "src/anchor/api.py",
    "src/anchor/deals/contracts.py",
    "src/anchor/deals/decision_matrix.py",
    "src/anchor/deals/fingerprint.py",
    "src/anchor/deals/partnership_codec.py",
    "src/anchor/deals/partnership_variants.py",
    "src/anchor/deals/store.py",
    "src/anchor/decision/comparison.py",
]


def test_only_the_named_stage_2_layers_import_the_partnership() -> None:
    """Nothing imported the package at Stage 1. Stage 2 connects exactly these
    layers (re-pinned from "no importer at all")."""

    importers = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        if "partnership" not in path.relative_to(_PROJECT_ROOT / "src" / "anchor").parts[:1]
        and any(
            module.lstrip(".").split(".")[0] == "partnership" or module.startswith(("anchor.partnership", "..partnership"))
            for module in _imports(ast.parse(path.read_text(encoding="utf-8")))
        )
    )
    assert importers == _PARTNERSHIP_IMPORTERS


def test_no_upstream_engine_layer_imports_the_partnership() -> None:
    for layer in ("engine", "consolidation", "capital_structure", "investment", "business_plan", "leasing", "ai", "ingestion"):
        for path in (_PROJECT_ROOT / "src" / "anchor" / layer).rglob("*.py"):
            modules = _imports(ast.parse(path.read_text(encoding="utf-8")))
            assert not any("partnership" in module for module in modules), path


def test_the_waterfall_engine_never_reaches_the_seam() -> None:
    for name in ("validation", "allocation", "accounts", "waterfall", "attribution", "metrics"):
        assert ".common_equity" not in _imports(_tree(_module(name))), name


# =============================================================================
# 4. No role inference, no duplicate authority, no default
# =============================================================================


def test_a_role_is_only_validated_and_copied() -> None:
    uses: set[tuple[str, str]] = set()
    for name in _NAMES:
        tree = _tree(_module(name))
        owners = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "role":
                uses.add((name, owners.get(node, "<module>")))
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "PartnerRole":
                uses.add((name, f"PartnerRole.{node.attr}"))
    assert uses == {("validation", "_partner_issues"), ("waterfall", "_partner_result")}
    copied = [
        keyword for node in ast.walk(_tree(_module("waterfall")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "PartnerResult"
        for keyword in node.keywords if keyword.arg == "role"
    ]
    assert [ast.unparse(keyword.value) for keyword in copied] == ["partner.role"]


def test_participation_comes_only_from_the_stated_ids() -> None:
    waterfall = _current(_module("waterfall"))
    assert "frozenset(partnership.promote_participant_ids)" in waterfall
    assert "is_participant=partner_id in participants" in waterfall


def test_no_duplicate_authority_fields() -> None:
    contracts = _tree(_module("contracts"))
    classes = {node.name: node for node in contracts.body if isinstance(node, ast.ClassDef)}
    fields = {
        name: {statement.target.id for statement in node.body if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)}
        for name, node in classes.items()
    }
    assert fields["CatchUpTerms"] == {"recipient", "target_profit_share"}
    assert fields["CommonEquityCashFlowInput"] == {"cadence", "cash_flows"}
    assert "total_profit" not in fields["PartnershipResult"]


def test_no_authored_contract_field_is_defaulted_in_source() -> None:
    contracts = _tree(_module("contracts"))
    authored = {
        "CommonEquityCashFlowInput", "Partner", "BenchmarkShare", "PromoteBenchmark", "SplitShare", "ExplicitSplit",
        "HurdleSubject", "IrrHurdle", "MoicHurdle", "HurdleTerms", "CatchUpRecipient", "CatchUpTerms",
        "WaterfallTier", "Partnership",
    }
    for node in contracts.body:
        if isinstance(node, ast.ClassDef) and node.name in authored:
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign):
                    assert statement.value is None, (node.name, ast.unparse(statement))


def test_classes_live_only_where_expected() -> None:
    allowed = {"contracts": None, "accounts": {"HurdleAccountState"}, "waterfall": {"_Tier"}, "attribution": {"Attribution"}, "metrics": {"PartnerReturns"}}
    for name in _NAMES:
        classes = {node.name for node in _tree(_module(name)).body if isinstance(node, ast.ClassDef)}
        if name == "contracts":
            continue
        assert classes == allowed.get(name, set()), name


def test_every_internal_record_is_frozen() -> None:
    for name, cls in (("accounts", "HurdleAccountState"), ("waterfall", "_Tier"), ("attribution", "Attribution"), ("metrics", "PartnerReturns")):
        (node,) = [item for item in _tree(_module(name)).body if isinstance(item, ast.ClassDef) and item.name == cls]
        (decorator,) = node.decorator_list
        assert ast.unparse(decorator) == "dataclass(frozen=True, slots=True, kw_only=True)", cls


# =============================================================================
# 5. No second solver, no I/O, no later-stage surface
# =============================================================================


_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _arithmetic(tree: ast.AST) -> list[ast.AST]:
    """Arithmetic nodes; a ``X | Y`` type union is not arithmetic."""

    return [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, _ARITHMETIC)
    ]


def test_contracts_and_validation_calculate_nothing_but_share_sums() -> None:
    assert _arithmetic(_tree(_module("contracts"))) == []
    tree = _tree(_module("validation"))
    owners = _enclosing_functions(tree)
    arithmetic = {owners.get(node, "<module>") for node in _arithmetic(tree)}
    assert arithmetic == {"_share_sum", "_sums_to_one", "members_share"}


def test_no_power_operator_and_no_second_irr_solver() -> None:
    for name in _NAMES:
        tree = _tree(_module(name))
        assert not [node for node in ast.walk(tree) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)], name
        assert not [node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) in {"pow", "math.pow"}], name
        functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        assert not {function for function in functions if "irr" in function or "npv" in function or "discount" in function}, name
    calls = {ast.unparse(node.func) for node in ast.walk(_tree(_module("metrics"))) if isinstance(node, ast.Call)}
    assert "evaluate_irr" in calls


_FORBIDDEN_CALLS = {"open", "print", "input", "eval", "exec", "compile", "__import__"}
_FORBIDDEN_MODULES = re.compile(r"sqlite|store|api|fastapi|datetime|time|random|os|pathlib|json|requests|deals|decision|analysis", re.IGNORECASE)


@pytest.mark.parametrize("name", _NAMES)
def test_no_io_clock_randomness_or_later_stage_import(name: str) -> None:
    tree = _tree(_module(name))
    assert not {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)} & _FORBIDDEN_CALLS, name
    for module in _imports(tree):
        assert not _FORBIDDEN_MODULES.search(module.replace("capital_structure", "")), (name, module)


_LATER = re.compile(r"fee|tax|clawback|claw_back|monthly|refinanc|recapitali|valuation|xirr|fingerprint|schema|route|matrix|perspective", re.IGNORECASE)


@pytest.mark.parametrize("name", _NAMES)
def test_no_deferred_scope_identifier(name: str) -> None:
    assert not {identifier for identifier in _identifiers(_tree(_module(name))) if _LATER.search(identifier)}, name


def test_the_deferred_scope_guard_has_teeth() -> None:
    assert _LATER.search("sponsor_fee") and _LATER.search("MONTHLY") and _LATER.search("clawback_amount")
    assert not _LATER.search("promote_earned") and not _LATER.search("catch_up_rate")


@pytest.mark.parametrize("name", _NAMES)
def test_no_case_or_competition_identifier(name: str) -> None:
    import test_p7_0_decision_architecture as p7_0

    assert p7_0._case_identifiers_in(_current(_module(name))) == []


def test_the_ratified_result_names_are_used() -> None:
    contracts = _current(_module("contracts"))
    assert "benchmark_capital_subordination: float" in contracts
    assert "promote_attribution_by_tier: tuple[PartnerTierAmount, ...] | None" in contracts
    for name in _NAMES:
        text = _current(_module(name))
        assert not re.search(r"\bpromote_earned_by_tier\b|(?<![_\w])subordination:", text), name


def test_only_the_partner_total_promote_is_floored() -> None:
    attribution = _tree(_module("attribution"))
    functions = {node.name: node for node in attribution.body if isinstance(node, ast.FunctionDef)}
    floor = ast.unparse(functions["promote_earned_value"])
    assert "max(0.0, profit_distribution_difference)" in floor
    attribute = ast.unparse(functions["attribute"])
    assert "promote_by_tier = tuple(profit_by_tier)" in attribute
    assert "max(" not in ast.unparse([node for node in ast.walk(functions["attribute"]) if isinstance(node, ast.For)][0])
