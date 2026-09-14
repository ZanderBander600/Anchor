"""Phase 7 Gate P7.5 -- the production ledger and the architecture guards for
the Strategy x Scenario Decision Matrix (backend half).

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` P-5, DC-1 to
DC-7, Q19 and Q22, and the P7.5 gate's own Tier 1 scope approval: Delta vs Base
Scenario, Worst Case and Range across Scenarios, from completed results, and
nothing else. Every git query reads objects only (protocol 11.2). The guards
hold:

1. **the P7.5 production ledger** and the protected paths;
2. **the decision module is read-only financially** -- result contracts only,
   no engine calculation module, no store, no route, and exactly the approved
   cross-cell subtractions;
3. **one engine path** -- the service runs every cell through the P7.4
   variant authority and swallows only the three typed validation errors;
4. **the routes** -- exactly two, each delegating, computing nothing;
5. **no expected value, no ranking, no schema change**.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.5 began: the no-ff P7.4 merge.
_P7_5_BASE = "5f04d3775152494cd717c86ea7318161908494be"

_COMPARISON = "src/anchor/decision/comparison.py"
_DECISION_INIT = "src/anchor/decision/__init__.py"
_SERVICE = "src/anchor/deals/decision_matrix.py"
_API = "src/anchor/api.py"

#: Every production file P7.5 changes, exactly:
#: - ``anchor/decision`` (new): the read-only cross-cell comparison;
#: - ``deals/decision_matrix.py`` (new): the service that runs each cell through
#:   the P7.4 variant authority;
#: - ``api.py``: ``GET /strategy-targets`` and the decision-matrix route;
#: - the web client, types, hooks and components of the Strategy manager, the
#:   Strategy editor and the Decision Matrix, the Risk navigation in
#:   ``App.tsx``, the styles, and the retirement of the P7.3 Scenario
#:   Comparison (``scenarioComparison.ts`` and ``ScenarioComparisonMatrix.tsx``
#:   removed, their responsibility moved to the Decision Matrix);
#: - ``BusinessPlanEditor.tsx``: an optional id prefix and heading so the one
#:   Business Plan editor can also edit a Strategy's replacement plan.
_P7_5_BACKEND_FILES = frozenset({_COMPARISON, _DECISION_INIT, _SERVICE, _API})
_P7_5_WEB_FILES = frozenset(
    {
        "web/src/api.ts",
        "web/src/App.tsx",
        "web/src/index.css",
        "web/src/strategyTypes.ts",
        "web/src/strategyCatalog.ts",
        "web/src/strategyForm.ts",
        "web/src/useStrategies.ts",
        "web/src/decisionTypes.ts",
        "web/src/decisionMatrix.ts",
        "web/src/useDecisionMatrix.ts",
        "web/src/useScenarios.ts",
        "web/src/scenarioComparison.ts",
        "web/src/components/ScenarioComparisonMatrix.tsx",
        "web/src/components/ScenarioWorkspace.tsx",
        "web/src/components/RiskDecisionWorkspace.tsx",
        "web/src/components/DecisionMatrixPanel.tsx",
        "web/src/components/StrategyManager.tsx",
        "web/src/components/StrategyEditor.tsx",
        "web/src/components/BusinessPlanEditor.tsx",
    }
)
_P7_5_PRODUCTION_FILES = _P7_5_BACKEND_FILES | _P7_5_WEB_FILES

#: Financial truth, Scenario and Strategy semantics, persistence, fingerprints,
#: AI and ingestion: P7.5 consumes them and changes none.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/leasing",
    "src/anchor/business_plan",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/analysis",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/deals/store.py",
    "src/anchor/deals/variants.py",
    "src/anchor/deals/contracts.py",
    "src/anchor/deals/fingerprint.py",
    "src/anchor/deals/__init__.py",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    """Committed, staged, unstaged and untracked changes since ``base``, with
    renames split into their removal and addition."""

    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _ledger_violations(changed: set[str]) -> tuple[list[str], list[str]]:
    return sorted(changed - _P7_5_PRODUCTION_FILES), sorted(_P7_5_PRODUCTION_FILES - changed)


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _current(path: str) -> str:
    return _lf((_PROJECT_ROOT / path).read_bytes().decode("utf-8"))


def _baseline(path: str) -> str:
    return _lf(_git("show", f"{_P7_5_BASE}:{path}"))


def _tree(path: str) -> ast.Module:
    return ast.parse(_current(path))


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ast.unparse(func)


def _calls(node: ast.AST) -> list[str]:
    return [_callee(child) for child in ast.walk(node) if isinstance(child, ast.Call)]


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _without_docstrings(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return tree


_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod, ast.MatMult)


def _arithmetic(node: ast.AST) -> list[str]:
    return [
        ast.unparse(child)
        for child in ast.walk(node)
        if (isinstance(child, (ast.BinOp, ast.AugAssign)) and isinstance(child.op, _ARITHMETIC))
        or (isinstance(child, ast.UnaryOp) and isinstance(child.op, (ast.USub, ast.UAdd)))
    ]


def _imports(tree: ast.Module) -> set[str]:
    """Every module a file imports, relative imports spelled with their
    leading dots."""

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


# =============================================================================
# 1. The P7.5 production ledger
# =============================================================================


def test_p7_5_changed_exactly_its_authorized_production_files() -> None:
    """The P7.5 production ledger. The next gate must re-pin this to P7.5's
    committed range, ``5f04d37..<the P7.5 merge>``, before adding its own
    scope. Never widen this set to admit another gate's files."""

    changed = {path for path in _changes_since(_P7_5_BASE, "src", "web") if _is_production(path)}
    assert _ledger_violations(changed) == ([], [])


def test_the_p7_5_ledger_base_is_the_p7_4_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_5_BASE).split()[1:]
    assert parents == [_git("rev-parse", ref).strip() for ref in ("aa96155", "ecf1f71")]


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_p7_4(path: str) -> None:
    assert _changes_since(_P7_5_BASE, path) == set(), f"{path} changed at P7.5"


def test_the_ledger_rejects_any_unexpected_production_change() -> None:
    assert _ledger_violations(set(_P7_5_PRODUCTION_FILES)) == ([], [])
    for intruder in (
        "src/anchor/engine/returns.py",
        "src/anchor/engine/debt.py",
        "src/anchor/engine/acquisition.py",
        "src/anchor/analysis/scenario.py",
        "src/anchor/analysis/strategy.py",
        "src/anchor/deals/fingerprint.py",
        "src/anchor/deals/store.py",
        "src/anchor/ai/prompts.py",
        "web/src/capitalEconomics.ts",
    ):
        assert _ledger_violations({*_P7_5_PRODUCTION_FILES, intruder}) == ([intruder], [])
    assert not _is_production("tests/test_p7_5_decision_architecture.py")


# =============================================================================
# 2. The decision module is read-only financially (P-5, DC-1)
# =============================================================================

#: The engine's calculation modules. The decision layer reads their results
#: and never calls them.
_ENGINE_CALCULATION = re.compile(r"(^|\.)(engine\.)?(acquisition|debt|returns|noi|operating_projection)$")


def test_the_decision_module_imports_result_contracts_and_the_standard_library_only() -> None:
    assert _imports(_tree(_COMPARISON)) == {
        "__future__", "hashlib", "json", "collections.abc", "dataclasses", "enum", "..engine.contracts",
    }
    assert _imports(_tree(_DECISION_INIT)) == {"__future__"}


def test_no_decision_module_reaches_the_engine_a_store_or_a_route() -> None:
    for path in (_PROJECT_ROOT / "src" / "anchor" / "decision").rglob("*.py"):
        text = _lf(path.read_text(encoding="utf-8"))
        imports = _imports(ast.parse(text))
        assert not {name for name in imports if _ENGINE_CALCULATION.search(name)}, path
        assert not {name for name in imports if re.search(r"deals|api|store|sqlite3|fastapi|analysis", name)}, path
        assert not re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE)\b", text), path


def test_the_engine_import_guard_would_see_a_smuggled_irr_call() -> None:
    tree = ast.parse("from ..engine.returns import evaluate_irr\nfrom anchor.engine import debt\n")
    assert {n for n in _imports(tree) if _ENGINE_CALCULATION.search(n)} == {"..engine.returns"}
    assert _ENGINE_CALCULATION.search("anchor.engine.debt")


def test_the_decision_module_has_exactly_the_approved_cross_cell_arithmetic() -> None:
    """Two subtractions and nothing else: the Delta (a cell less the same
    Strategy's Base Scenario cell) and the Range (maximum less minimum)."""

    assert _arithmetic(_tree(_COMPARISON)) == ["target.value - reference.value", "high[0] - low[0]"]
    delta = _functions(_tree(_COMPARISON))["_delta"]
    assert _arithmetic(delta) == ["target.value - reference.value"]
    source = ast.unparse(delta)
    assert "reference = values[base_cell.strategy_id, base_cell.scenario_id]" in source
    assert "target = values[cell.strategy_id, cell.scenario_id]" in source


def test_the_decision_module_aggregates_nothing() -> None:
    calls = set(_calls(_tree(_COMPARISON)))
    assert not calls & {"sum", "min", "max", "mean", "fsum", "median", "average", "prod", "round", "abs"}
    sorts = [ast.unparse(c) for c in ast.walk(_tree(_COMPARISON)) if isinstance(c, ast.Call) and _callee(c) == "sorted"]
    # Sorting is by stable identity (and the distinct hold periods), never by a
    # financial value.
    assert all("_canonical_key" in s or "hold_period" in s or "identities" in s for s in sorts), sorts


def test_the_arithmetic_guard_would_see_a_smuggled_expected_value() -> None:
    tree = ast.parse("def ev(a, b):\n    return 0.5 * a + 0.5 * b\n")
    assert _arithmetic(tree) == ["0.5 * a + 0.5 * b", "0.5 * a", "0.5 * b"]


def test_each_metric_reads_its_own_field_explicitly() -> None:
    reported = _functions(_tree(_COMPARISON))["_reported"]
    attributes = sorted(
        {node.attr for node in ast.walk(reported) if isinstance(node, ast.Attribute) and ast.unparse(node.value) == "results"}
    )
    assert attributes == sorted(
        {
            "levered_irr", "levered_irr_status", "unlevered_irr", "unlevered_irr_status", "equity_multiple",
            "total_profit", "total_equity_invested", "exit_value", "min_dscr",
        }
    )
    assert not {"getattr", "setattr", "eval", "exec"} & set(_calls(_tree(_COMPARISON)))


# =============================================================================
# 3. One engine path -- the service is the P7.4 variant authority, per cell
# =============================================================================


def test_the_service_runs_every_cell_through_the_p7_4_variant_authority() -> None:
    tree = _tree(_SERVICE)
    functions = _functions(tree)
    assert _calls(functions["_cell"]).count("analyze_variant") == 1
    assert _calls(functions["_cell"]).count("inspect_variant_inputs") == 1
    assert "analyze_variant" not in _calls(functions["analyze_decision_matrix"])
    assert _calls(functions["analyze_decision_matrix"]).count("_cell") == 1
    assert "compare_decision_matrix" in _calls(functions["analyze_decision_matrix"])
    engine_entries = {c for c in _calls(tree) if re.search(r"with_business_plan|with_strategy|with_scenario|_analyze_resolved|^resolve_", c)}
    assert engine_entries == set()
    imports = _imports(tree)
    assert not {name for name in imports if _ENGINE_CALCULATION.search(name) or "business_plan_analysis" in name}
    assert _arithmetic(tree) == []


def test_the_service_turns_only_the_typed_validation_errors_into_invalid_cells() -> None:
    handlers = [
        ast.unparse(handler.type) if handler.type is not None else "<bare>"
        for node in ast.walk(_tree(_SERVICE))
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]
    assert handlers == [
        "StrategyValidationError",
        "ScenarioValidationError",
        "LeaseValidationError",
        "(StrategyValidationError, ScenarioValidationError)",
    ]
    assert "except Exception" not in _current(_SERVICE) and "except ValueError" not in _current(_SERVICE)


def test_the_whole_matrix_is_bracketed_by_one_economic_state_token() -> None:
    """DC-7: the source state is read before the first cell and after the
    last, and a difference is a conflict. The token reads ids, overlays,
    overrides, membership and the Base fingerprint through the existing
    variant authority -- never a name, a description or a timestamp."""

    functions = _functions(_tree(_SERVICE))
    run = ast.unparse(functions["analyze_decision_matrix"])
    assert _calls(functions["analyze_decision_matrix"]).count("_source_state") == 2
    assert (
        run.index("before = _source_state(")
        < run.index("_cell(")
        < run.index("after = _source_state(")
        < run.index("if after.token != before.token:")
        < run.index("raise DecisionMatrixConflictError(")
    )
    token = functions["economic_state_token"]
    read = {node.attr for node in ast.walk(token) if isinstance(node, ast.Attribute)}
    assert {"strategy_id", "overlays", "scenario_id", "overrides"} <= read
    assert not read & {"name", "description", "created_at", "updated_at"}
    assert "variant_fingerprint" in _calls(functions["_source_state"])
    assert not {c for c in _calls(functions["_source_state"]) if "fingerprint_" in c and c != "variant_fingerprint"}


def test_the_service_stores_nothing() -> None:
    calls = set(_calls(_tree(_SERVICE)))
    assert not {c for c in calls if c.startswith(("put_", "create_", "update_", "delete_", "_write", "_insert"))}
    assert calls & {"get_investment", "list_strategies", "list_scenarios", "get_deal"} == {
        "get_investment", "list_strategies", "list_scenarios", "get_deal",
    }


# =============================================================================
# 4. The routes
# =============================================================================


def _route_functions(tree: ast.Module) -> dict[tuple[str, str], ast.FunctionDef]:
    routes: dict[tuple[str, str], ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and ast.unparse(decorator.func.value) == "app"
                    and decorator.args
                ):
                    routes[(decorator.func.attr, ast.unparse(decorator.args[0]))] = node
    return routes


def test_p7_5_adds_exactly_two_routes() -> None:
    added = set(_route_functions(_tree(_API))) - set(_route_functions(ast.parse(_baseline(_API))))
    assert added == {("get", "'/strategy-targets'"), ("post", "'/investments/{investment_id}/decision-matrix'")}


def test_api_py_changed_only_by_additions_that_compute_nothing() -> None:
    current = _without_docstrings(ast.parse(_current(_API))).body
    baseline = _without_docstrings(ast.parse(_baseline(_API))).body
    current_dumps = {ast.dump(node) for node in current}
    baseline_dumps = {ast.dump(node) for node in baseline}
    removed = [node for node in baseline if ast.dump(node) not in current_dumps]
    assert [type(node).__name__ for node in removed] == ["ImportFrom"]
    (old,) = removed
    assert isinstance(old, ast.ImportFrom) and old.module == "analysis.strategy"
    added = [node for node in current if ast.dump(node) not in baseline_dumps]
    assert [(type(n).__name__, getattr(n, "name", getattr(n, "module", None))) for n in added] == [
        ("ImportFrom", "analysis.strategy"),
        ("ImportFrom", "deals.decision_matrix"),
        ("ClassDef", "_StrategyTargetEntry"),
        ("FunctionDef", "strategy_target_catalog"),
        ("FunctionDef", "analyze_investment_decision_matrix"),
    ]
    assert _arithmetic(ast.Module(body=added, type_ignores=[])) == []


def _body(function: ast.FunctionDef) -> ast.Module:
    """A route's body without its decorator."""

    return ast.Module(body=function.body, type_ignores=[])


def test_the_matrix_route_only_delegates() -> None:
    function = _route_functions(_tree(_API))[("post", "'/investments/{investment_id}/decision-matrix'")]
    assert set(_calls(_body(function))) == {
        "analyze_decision_matrix", "_not_found", "_investment_structure_conflict", "HTTPException", "str",
    }


def test_the_strategy_target_catalog_projects_the_whitelist_and_touches_no_store() -> None:
    function = _route_functions(_tree(_API))[("get", "'/strategy-targets'")]
    names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
    assert {"STRATEGY_OUTCOME_TARGETS", "SCENARIO_TARGET_REGISTRY"} <= names
    assert not {"investment_store", "deals_store", "store"} & names
    assert set(_calls(_body(function))) == {"_StrategyTargetEntry"}


def test_the_registry_is_named_only_by_the_two_catalogs_and_the_import() -> None:
    text = _current(_API)
    segments = [
        ast.get_source_segment(text, function)
        for function in _functions(ast.parse(text)).values()
        if function.name in {"scenario_target_catalog", "strategy_target_catalog"}
    ]
    assert len(segments) == 2
    for segment in segments:
        assert segment is not None
        text = text.replace(segment, "")
    assert re.findall(r"\bSCENARIO_TARGET_REGISTRY\b", text) == ["SCENARIO_TARGET_REGISTRY"]


# =============================================================================
# 5. No expected value, no ranking, no schema change, no later gate
# =============================================================================

_FORBIDDEN_DECISION_VOCABULARY = re.compile(
    r"probabilit|expected_?value|expected_?(irr|profit|return)|weighted|monte_?carlo|score|\brank|ranking"
    r"|recommend|winner|best_strategy",
    re.IGNORECASE,
)


def _identifiers_and_strings(tree: ast.AST) -> set[str]:
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
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
    return found


@pytest.mark.parametrize("path", sorted(_P7_5_BACKEND_FILES - {_API}))
def test_no_p7_5_backend_code_names_an_expected_value_or_a_ranking(path: str) -> None:
    code = _without_docstrings(_tree(path))
    assert {t for t in _identifiers_and_strings(code) if _FORBIDDEN_DECISION_VOCABULARY.search(t)} == set()


def test_no_p7_5_api_addition_names_an_expected_value_or_a_ranking() -> None:
    baseline = {ast.dump(n) for n in _without_docstrings(ast.parse(_baseline(_API))).body}
    added = [n for n in _without_docstrings(_tree(_API)).body if ast.dump(n) not in baseline]
    assert {t for t in _identifiers_and_strings(ast.Module(body=added, type_ignores=[])) if _FORBIDDEN_DECISION_VOCABULARY.search(t)} == set()


def test_the_vocabulary_guard_has_teeth() -> None:
    tree = ast.parse("expected_value = 1\ndef rank_strategies(scores):\n    return 'Scenario probability'\n")
    assert {t for t in _identifiers_and_strings(tree) if _FORBIDDEN_DECISION_VOCABULARY.search(t)} == {
        "expected_value", "rank_strategies", "scores", "Scenario probability",
    }


_LATER_GATE_VOCABULARY = re.compile(
    r"consolidat|waterfall|partner|capital_position|capital_event|capital_structure|tranche|promote"
    r"|unit_selection|refinanc|recapitali|mezzanine|preferred_equity",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", sorted(_P7_5_BACKEND_FILES - {_API}))
def test_no_p7_5_backend_code_names_a_later_gate_concept(path: str) -> None:
    code = _without_docstrings(_tree(path))
    assert {t for t in _identifiers_and_strings(code) if _LATER_GATE_VOCABULARY.search(t)} == set()


def test_the_schema_version_and_every_table_are_unchanged() -> None:
    assert _current("src/anchor/deals/store.py") == _baseline("src/anchor/deals/store.py")
    assert re.search(r"^_SCHEMA_VERSION = 9$", _current("src/anchor/deals/store.py"), re.MULTILINE)


@pytest.mark.parametrize("path", sorted(_P7_5_BACKEND_FILES))
def test_no_case_or_competition_identifier(path: str) -> None:
    import test_p7_0_decision_architecture as p7_0

    assert p7_0._case_identifiers_in(_current(path)) == []
