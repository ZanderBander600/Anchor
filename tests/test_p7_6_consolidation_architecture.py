"""Phase 7 Gate P7.6 -- the production ledger and the architecture guards for
multi-unit Investments and consolidation (Session A, backend; Session B, the
Investment workspace UI, whose frontend guards live in
``web/src/investmentArchitecture.test.ts``).

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3 (P-1,
P-3, P-4, P-9, P-10), 8, 9, 10, 11 and 15, and the P7.6 gate's own Q16
engine-scope approval: consolidation of completed Unit results, returns derived
with the existing ``anchor.engine.returns`` functions, the Investment Business
Plan and transaction costs applied once at consolidation, multi-unit variant
orchestration, and the Investment fingerprint -- and nothing else. Every git
query reads objects only (protocol 11.2). The guards hold:

1. **the P7.6 production ledger** and every protected path;
2. **one engine, downstream** -- consolidation imports result contracts, the
   returns functions and the Investment contracts; it knows no mode, kind or
   label; its arithmetic is exactly the enumerated sums, channel subtractions
   and derived ratios;
3. **canonical order** and **the transaction price is never a cash flow**;
4. **the variant pathway** -- the existing per-Unit resolution and entry
   points, one consolidation, one Investment-plan resolution, never cached;
5. **additive persistence** -- five appended tables, an unchanged migration
   body, enumerated store changes, validation before every write;
6. **P7.2 - P7.5 compatibility** -- every baseline route and the one-unit matrix
   service unchanged, the comparison changed only as enumerated;
7. **no later-gate concept**, no AI, no case identifier -- and a frontend that
   changes only the enumerated Session B files.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from anchor.analysis.strategy import StrategyDomain
from anchor.decision.comparison import (
    INVESTMENT_PROJECT_METRIC_CATALOG,
    PROJECT_METRIC_CATALOG,
    DecisionMetric,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.6 began: the no-ff P7.5 merge.
_P7_6_BASE = "6cade6279ff9f071d672f68889585065a829fb2c"

_CONSOLIDATION_ENGINE = "src/anchor/consolidation/engine.py"
_CONSOLIDATION_CONTRACTS = "src/anchor/consolidation/contracts.py"
_CONSOLIDATION_INIT = "src/anchor/consolidation/__init__.py"
_INVESTMENT_CONTRACTS = "src/anchor/investment/contracts.py"
_INVESTMENT_VALIDATION = "src/anchor/investment/validation.py"
_INVESTMENT_INIT = "src/anchor/investment/__init__.py"
_VARIANTS = "src/anchor/deals/investment_variants.py"
_STORE = "src/anchor/deals/store.py"
_CONTRACTS = "src/anchor/deals/contracts.py"
_SERVICE = "src/anchor/deals/decision_matrix.py"
_COMPARISON = "src/anchor/decision/comparison.py"
_SCENARIO = "src/anchor/analysis/scenario.py"
_STRATEGY = "src/anchor/analysis/strategy.py"
_API = "src/anchor/api.py"

#: Every production file P7.6 Session A changes, exactly:
#: - ``anchor/investment`` (new): the Investment-level input contracts
#:   (``UnitKind``, memberships with economic timing, transaction costs) and
#:   their validation, with the CON-1 timeline and PP-2 allocation rules;
#: - ``anchor/consolidation`` (new): ``ConsolidatedResults`` and the one
#:   consolidation layer, downstream of the engine;
#: - ``deals/investment_variants.py`` (new): the visible Investment variant
#:   pathway and its fingerprint;
#: - ``deals/store.py``: schema v10, five sidecar tables, the visible lifecycle,
#:   and Scenario / Strategy ownership generalized to a member set;
#: - ``deals/contracts.py``: ``VisibleInvestment`` and its not-found error;
#: - ``deals/decision_matrix.py``: the visible Investment matrix;
#: - ``decision/comparison.py``: a cell may read ``ConsolidatedResults``;
#: - ``analysis/scenario.py`` and ``analysis/strategy.py``: Unit addressing
#:   generalized to an Investment's member set, nothing else;
#: - ``api.py``: the visible Investment routes.
_P7_6_BACKEND_FILES = frozenset(
    {
        _CONSOLIDATION_ENGINE, _CONSOLIDATION_CONTRACTS, _CONSOLIDATION_INIT,
        _INVESTMENT_CONTRACTS, _INVESTMENT_VALIDATION, _INVESTMENT_INIT,
        _VARIANTS, _STORE, _CONTRACTS, _SERVICE, _COMPARISON, _SCENARIO, _STRATEGY, _API,
    }
)

#: Every frontend production file P7.6 Session B changes, exactly:
#: - the typed client (``api.ts``, additions only) and the wire contracts
#:   (``investmentTypes.ts``; ``decisionTypes.ts`` gains the Investment issue
#:   source the backend already emits);
#: - the Investment's presentation, draft boundary and state hooks, and its
#:   Library, builder, workspace, Overview, Units, transaction-cost editor and
#:   return bar;
#: - the P7.3 / P7.5 Strategy, Scenario and Decision Matrix modules, generalized
#:   to an explicit Investment scope (one implementation, two scopes);
#: - global navigation (``App.tsx``, ``AppSidebar.tsx``) and the styles.
_P7_6_WEB_FILES = frozenset(
    {
        "web/src/api.ts",
        "web/src/App.tsx",
        "web/src/index.css",
        "web/src/decisionTypes.ts",
        "web/src/decisionMatrix.ts",
        "web/src/strategyForm.ts",
        "web/src/useStrategies.ts",
        "web/src/useScenarios.ts",
        "web/src/useDecisionMatrix.ts",
        "web/src/investmentTypes.ts",
        "web/src/investmentCatalog.ts",
        "web/src/investmentForm.ts",
        "web/src/useInvestments.ts",
        "web/src/useInvestmentWorkspace.ts",
        "web/src/useInvestmentAnalysis.ts",
        "web/src/useNewInvestment.ts",
        "web/src/components/AppSidebar.tsx",
        "web/src/components/RiskDecisionWorkspace.tsx",
        "web/src/components/DecisionMatrixPanel.tsx",
        "web/src/components/StrategyManager.tsx",
        "web/src/components/StrategyEditor.tsx",
        "web/src/components/ScenarioWorkspace.tsx",
        "web/src/components/ScenarioEditor.tsx",
        "web/src/components/InvestmentIssueList.tsx",
        "web/src/components/InvestmentLibraryPanel.tsx",
        "web/src/components/NewInvestmentPanel.tsx",
        "web/src/components/TransactionCostEditor.tsx",
        "web/src/components/InvestmentOverview.tsx",
        "web/src/components/InvestmentUnitsPanel.tsx",
        "web/src/components/InvestmentWorkspace.tsx",
        "web/src/components/InvestmentReturnBar.tsx",
    }
)
_P7_6_PRODUCTION_FILES = _P7_6_BACKEND_FILES | _P7_6_WEB_FILES

#: The mature engine, leasing, the D6 Business Plan, AI, ingestion, the one-unit
#: variant service, the fingerprint functions, and the frontend's financial,
#: formatting, contract and Business Plan modules: P7.6 consumes them and
#: changes none. ``engine/returns.py`` is called, never modified; the frontend
#: formats backend figures with the shipped formatters and derives none.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/leasing",
    "src/anchor/business_plan",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/analysis/business_plan_analysis.py",
    "src/anchor/analysis/lease_level.py",
    "src/anchor/analysis/sensitivity.py",
    "src/anchor/analysis/lease_level_sensitivity.py",
    "src/anchor/analysis/break_even.py",
    "src/anchor/analysis/contracts.py",
    "src/anchor/analysis/__init__.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/deals/fingerprint.py",
    "src/anchor/deals/variants.py",
    "src/anchor/deals/__init__.py",
    "src/anchor/decision/__init__.py",
    "web/src/convert.ts",
    "web/src/format.ts",
    "web/src/liveMetrics.ts",
    "web/src/ownerSummary.ts",
    "web/src/capitalEconomics.ts",
    "web/src/businessPlan.ts",
    "web/src/useBusinessPlan.ts",
    "web/src/types.ts",
    "web/src/leaseLevelTypes.ts",
    "web/src/scenarioTypes.ts",
    "web/src/scenarioCatalog.ts",
    "web/src/strategyTypes.ts",
    "web/src/strategyCatalog.ts",
    "web/src/operatingMode.ts",
    "web/src/components/BusinessPlanEditor.tsx",
    "web/src/components/CapitalEconomicsSection.tsx",
    "web/src/components/NumericInput.tsx",
    "web/src/components/UnderwriteWorkspace.tsx",
    "web/src/components/LeaseLevelWorkspace.tsx",
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
    return sorted(changed - _P7_6_PRODUCTION_FILES), sorted(_P7_6_PRODUCTION_FILES - changed)


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _current(path: str) -> str:
    return _lf((_PROJECT_ROOT / path).read_bytes().decode("utf-8"))


def _baseline(path: str) -> str:
    return _lf(_git("show", f"{_P7_6_BASE}:{path}"))


def _tree(path: str) -> ast.Module:
    return ast.parse(_current(path))


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ast.unparse(func)


def _calls(node: ast.AST) -> list[str]:
    return [_callee(child) for child in ast.walk(node) if isinstance(child, ast.Call)]


def _call_nodes(node: ast.AST, name: str) -> list[ast.Call]:
    return sorted(
        (child for child in ast.walk(node) if isinstance(child, ast.Call) and _callee(child) == name),
        key=lambda call: (call.lineno, call.col_offset),
    )


def _strings(node: ast.AST) -> list[str]:
    return [child.value for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)]


def _attributes(node: ast.AST) -> set[str]:
    return {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


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


def _is_text(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str))


def _arithmetic(node: ast.AST) -> list[str]:
    """Every numeric operation, unparsed. String concatenation (a message) is
    not arithmetic."""

    return [
        ast.unparse(child)
        for child in ast.walk(node)
        if (
            isinstance(child, (ast.BinOp, ast.AugAssign))
            and isinstance(child.op, _ARITHMETIC)
            and not (isinstance(child, ast.BinOp) and (_is_text(child.left) or _is_text(child.right)))
        )
        or (isinstance(child, ast.UnaryOp) and isinstance(child.op, ast.USub))
    ]


def _added_nodes(path: str) -> list[ast.stmt]:
    """The current file's top-level statements, docstrings removed, that are
    absent from the P7.6 base -- for a new file, all of them."""

    current = _without_docstrings(ast.parse(_current(path))).body
    try:
        baseline_text = _baseline(path)
    except subprocess.CalledProcessError:
        return current
    baseline = {ast.dump(node) for node in _without_docstrings(ast.parse(baseline_text)).body}
    return [node for node in current if ast.dump(node) not in baseline]


def _changed_functions(path: str) -> tuple[set[str], set[str]]:
    """``(added, changed)`` top-level functions of ``path`` versus the base."""

    current, baseline = _functions(_tree(path)), _functions(ast.parse(_baseline(path)))
    assert set(baseline) <= set(current), sorted(set(baseline) - set(current))
    return set(current) - set(baseline), {n for n in baseline if ast.dump(current[n]) != ast.dump(baseline[n])}


# =============================================================================
# 1. The P7.6 production ledger
# =============================================================================


def test_p7_6_changed_exactly_its_authorized_production_files() -> None:
    """The P7.6 production ledger. The next gate must re-pin this to P7.6's
    committed range, ``6cade62..<the P7.6 merge>``, before adding its own scope.
    Never widen this set to admit another gate's files."""

    changed = {path for path in _changes_since(_P7_6_BASE, "src", "web") if _is_production(path)}
    assert _ledger_violations(changed) == ([], [])


def test_the_p7_6_ledger_base_is_the_p7_5_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_6_BASE).split()[1:]
    assert parents == [_git("rev-parse", ref).strip() for ref in ("5f04d37", "fddecc2")]


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_p7_5(path: str) -> None:
    assert _changes_since(_P7_6_BASE, path) == set(), f"{path} changed at P7.6"


def test_the_ledger_rejects_any_unexpected_production_change() -> None:
    assert _ledger_violations(set(_P7_6_PRODUCTION_FILES)) == ([], [])
    for intruder in (
        "src/anchor/engine/acquisition.py",
        "src/anchor/engine/debt.py",
        "src/anchor/engine/noi.py",
        "src/anchor/engine/returns.py",
        "src/anchor/deals/variants.py",
        "src/anchor/deals/fingerprint.py",
        "src/anchor/ai/prompts.py",
        "web/src/convert.ts",
        "web/src/capitalEconomics.ts",
    ):
        assert _ledger_violations({*_P7_6_PRODUCTION_FILES, intruder}) == ([intruder], [])
    assert not _is_production("tests/test_p7_6_consolidation_architecture.py")


# =============================================================================
# 2. One engine, downstream: consolidation consumes completed results
# =============================================================================

_ENGINE_CALCULATION = re.compile(r"(^|\.)(engine\.)?(acquisition|debt|noi|operating_projection)$")


def test_consolidation_imports_result_contracts_returns_and_investment_inputs_only() -> None:
    assert _imports(_tree(_CONSOLIDATION_ENGINE)) == {
        "__future__", "collections.abc", "math", "..engine.contracts", "..engine.returns",
        "..investment.contracts", "..investment.validation", ".contracts",
    }
    assert _imports(_tree(_CONSOLIDATION_CONTRACTS)) == {"__future__", "dataclasses", "enum", "..engine.contracts"}
    assert _imports(_tree(_CONSOLIDATION_INIT)) == {"__future__", ".contracts", ".engine"}
    for path in (_PROJECT_ROOT / "src" / "anchor" / "consolidation").rglob("*.py"):
        imports = _imports(ast.parse(path.read_text(encoding="utf-8")))
        assert not {name for name in imports if _ENGINE_CALCULATION.search(name)}, path
        assert not {name for name in imports if re.search(r"deals|api|store|sqlite3|fastapi|analysis|leasing|business_plan|\.ai", name)}, path


def test_the_investment_package_is_pure() -> None:
    for path in (_INVESTMENT_CONTRACTS, _INVESTMENT_VALIDATION, _INVESTMENT_INIT):
        imports = _imports(_tree(path))
        assert not {name for name in imports if re.search(r"engine|deals|api|store|sqlite3|fastapi|analysis|leasing|\.ai|consolidation", name)}, path
    assert _imports(_tree(_INVESTMENT_VALIDATION)) >= {"..business_plan", "..contracts", ".contracts"}


def test_consolidation_derives_every_return_with_the_existing_returns_functions() -> None:
    consolidate = _functions(_tree(_CONSOLIDATION_ENGINE))["consolidate"]
    calls = _calls(consolidate)
    for function in (
        "calculate_return_metrics", "calculate_year_1_debt_yield", "calculate_levered_cash_on_cash_by_year",
        "calculate_unlevered_cash_yield_by_year", "calculate_cumulative_operating_distributions_by_year",
    ):
        assert calls.count(function) == 1, function
    tree = _tree(_CONSOLIDATION_ENGINE)
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert not {name for name in defined if re.search(r"irr|dscr|multiple|npv", name, re.IGNORECASE)}
    assert not {"evaluate_irr", "calculate_irr", "calculate_dscr_by_year"} & set(_calls(tree))


#: Every numeric operation in consolidation: the canonical left-to-right sum,
#: the Investment-level channels (one addition or subtraction each), the
#: ``t = 0`` basis, the area weighting, and the derived ratios. Nothing else --
#: in particular no average and no transaction price.
_CONSOLIDATION_ARITHMETIC = {
    "total + value",
    "hold_period + 1",
    "t - 1",
    "-unlevered_cash_flows[0]",
    "loan_amount + initial_equity",
    "exit_noi / exit_value",
    "noi_by_year[0] / allocated_purchase_price",
    "unit.occupied_area_at_year_end[index] + unit.vacant_area_at_year_end[index]",
    "_canonical_sum(occupied, f'occupied_area_at_year_end[{index}]') / total_rentable",
    "_unit_sum(ordered, lambda r: r.initial_equity, 'initial_equity') + investment_closing_capital",
    "_unit_sum(ordered, lambda r: r.initial_equity, 'initial_equity') + investment_closing_capital + transaction_cost_total",
    "_unit_sum(ordered, lambda r: r.total_closing_uses, 'total_closing_uses') + investment_closing_capital",
    "_unit_sum(ordered, lambda r: r.total_closing_uses, 'total_closing_uses') + investment_closing_capital + transaction_cost_total",
    "_unit_sum(ordered, lambda r: r.closing_project_capital, 'closing_project_capital') + investment_closing_capital",
    "_unit_sum(ordered, lambda r: r.post_hold_project_capital, 'post_hold_project_capital') + investment.post_hold_project_capital",
    "unit_project_capital[y] + investment_capital[y]",
    "unit_owner_expenses[y] + investment_expenses[y]",
    "unit_unlevered_owner[y] - investment_capital[y]",
    "unit_unlevered_owner[y] - investment_capital[y] - investment_expenses[y]",
    "unit_levered_owner[y] - investment_capital[y]",
    "unit_levered_owner[y] - investment_capital[y] - investment_expenses[y]",
    "unit_unlevered[0] - investment_closing_capital",
    "unit_unlevered[0] - investment_closing_capital - transaction_cost_total",
    "unit_levered[0] - investment_closing_capital",
    "unit_levered[0] - investment_closing_capital - transaction_cost_total",
    "unit_unlevered[t] - investment_capital[t - 1]",
    "unit_unlevered[t] - investment_capital[t - 1] - investment_expenses[t - 1]",
    "unit_levered[t] - investment_capital[t - 1]",
    "unit_levered[t] - investment_capital[t - 1] - investment_expenses[t - 1]",
}


def test_consolidation_has_exactly_the_enumerated_arithmetic() -> None:
    assert set(_arithmetic(_tree(_CONSOLIDATION_ENGINE))) == _CONSOLIDATION_ARITHMETIC
    assert _arithmetic(_tree(_CONSOLIDATION_CONTRACTS)) == []


def test_the_arithmetic_guard_would_see_an_average_or_a_price_outflow() -> None:
    average = ast.parse("irr = sum(u.results.levered_irr for u in ordered) / len(ordered)\n")
    outflow = ast.parse("t0 = unit_levered[0] - transaction_price\n")
    assert set(_arithmetic(average)) - _CONSOLIDATION_ARITHMETIC
    assert set(_arithmetic(outflow)) - _CONSOLIDATION_ARITHMETIC


def test_consolidation_knows_no_mode_kind_label_or_display_order() -> None:
    for path in (_CONSOLIDATION_ENGINE, _CONSOLIDATION_CONTRACTS):
        code = _without_docstrings(_tree(path))
        names = {node.id for node in ast.walk(code) if isinstance(node, ast.Name)} | _attributes(code)
        assert not names & {"unit_kind", "UnitKind", "label", "ordinal", "description", "category", "operating_mode", "OperatingMode", "name"}, path


# =============================================================================
# 3. Canonical order; the transaction price is never a cash flow
# =============================================================================


def test_units_are_ordered_by_unit_id_once_and_costs_by_cost_id() -> None:
    tree = _tree(_CONSOLIDATION_ENGINE)
    keys = [ast.unparse(keyword.value) for call in _call_nodes(tree, "sorted") for keyword in call.keywords if keyword.arg == "key"]
    assert keys == ["lambda cost: cost.cost_id", "lambda unit: unit.unit_id"]
    consolidate = _functions(tree)["consolidate"]
    (first,) = [node for node in consolidate.body if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "ordered"]
    assert ast.unparse(first.value) == "tuple(sorted(units, key=lambda unit: unit.unit_id))"
    assert "total = values[0]" in ast.unparse(_functions(tree)["_canonical_sum"])


def test_the_transaction_price_enters_no_sum_and_no_cash_flow() -> None:
    tree = _tree(_CONSOLIDATION_ENGINE)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            assert "transaction_price" not in {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}, ast.unparse(node)
    consolidate = _functions(tree)["consolidate"]
    users = sorted(
        _callee(call) for call in ast.walk(consolidate) if isinstance(call, ast.Call)
        and any(isinstance(n, ast.Name) and n.id == "transaction_price" for n in (*call.args, *(k.value for k in call.keywords)))
    )
    assert users == ["allocation_variance", "float", "validate_allocation"]


def test_occupancy_is_refused_before_any_weighting_when_a_unit_has_no_area() -> None:
    function = _functions(_tree(_CONSOLIDATION_ENGINE))["_year_end_occupancy"]
    statements = [ast.unparse(node) for node in function.body if not isinstance(node, ast.Expr)]
    assert statements[0].startswith("without = [unit.unit_id for unit in units if unit.occupied_area_at_year_end is None or")
    assert statements[1].startswith("if without:\n    return (None, AreaMetricReason.UNIT_WITHOUT_AREA_MEASURE")


# =============================================================================
# 4. The variant pathway -- the existing per-Unit resolution, one consolidation
# =============================================================================


def test_the_pathway_reuses_the_per_unit_authority_and_calls_no_engine_itself() -> None:
    tree = _tree(_VARIANTS)
    imports = _imports(tree)
    assert not {name for name in imports if _ENGINE_CALCULATION.search(name) or "returns" in name or "business_plan_analysis" in name}
    calls = _calls(tree)
    assert calls.count("_analyze_resolved") == 1 and calls.count("consolidate") == 1
    assert calls.count("resolve_business_plan") == 1
    # ``_with_business_plan`` is the D6.5 fingerprint helper, not an entry point.
    assert not {c for c in calls if re.search(r"^analyze_\w*_with_(business_plan|strategy|scenario)$|^resolve_(quick|detailed|lease_level)_", c)}
    (analyze,) = _call_nodes(tree, "_analyze_resolved")
    assert [ast.unparse(a) for a in analyze.args] == ["unit.resolved"] and not analyze.keywords
    (plan,) = _call_nodes(tree, "resolve_business_plan")
    (consolidation,) = _call_nodes(tree, "consolidate")
    owner_capital = {k.arg: k.value for k in consolidation.keywords}["investment_owner_capital"]
    assert owner_capital is plan
    assert _arithmetic(tree) == []


def test_investment_channels_reach_only_consolidation_the_fingerprint_and_validation() -> None:
    tree = _tree(_VARIANTS)
    functions = _functions(tree)
    readers = sorted(
        name for name, function in functions.items()
        if "transaction_costs" in _attributes(function) or "business_plan" in _attributes(function)
    )
    assert readers == ["_resolve_units", "_source_fingerprint", "analyze_investment_variant", "inspect_investment_variant_inputs"]
    for call in (*_call_nodes(tree, "resolve_variant_inputs"), *_call_nodes(tree, "_analyze_resolved")):
        assert not {"transaction_costs", "business_plan", "transaction_price"} & _attributes(call), ast.unparse(call)


def test_the_fingerprint_reads_only_economic_fields() -> None:
    function = _functions(_tree(_VARIANTS))["fingerprint_investment_variant"]
    assert _attributes(function) == {"unit_id", "acquisition_month", "disposition_month", "model_month", "amount"}
    assert {"_fingerprint_json", "_with_business_plan"} <= set(_calls(function))


def test_a_visible_investment_is_never_cached() -> None:
    assert not {c for c in _calls(_tree(_VARIANTS)) if "variant_snapshot" in c}
    assert "VariantCacheStatus.BYPASSED" in _current(_VARIANTS)
    assert not re.search(r"VariantCacheStatus\.(HIT|MISS)", _current(_VARIANTS))
    store = _functions(_tree(_STORE))
    for name in ("get_variant_snapshot", "put_variant_snapshot", "put_strategy_variant_snapshot"):
        assert name not in _changed_functions(_STORE)[1], name
    assert "_require_hidden_wrapper" in _calls(store["put_strategy_variant_snapshot"])
    for name in ("promote_hidden_investment", "add_investment_unit", "remove_investment_unit"):
        assert "DELETE FROM variant_snapshots WHERE root_id = ?" in _strings(store[name]), name


def test_unit_kind_label_and_ordinal_never_reach_a_calculation_or_the_fingerprint() -> None:
    for path in (_VARIANTS, _CONSOLIDATION_ENGINE):
        code = _without_docstrings(_tree(path))
        assert not _attributes(code) & {"unit_kind", "label", "ordinal", "category", "description"}, path
    economic = _functions(_tree(_INVESTMENT_VALIDATION))
    for name in ("allocation_variance", "validate_allocation", "validate_common_timeline", "validate_variant_economics"):
        assert not _attributes(economic[name]) & {"unit_kind", "label", "ordinal", "category", "description"}, name


# =============================================================================
# 5. Additive persistence
# =============================================================================


def _create_constants(text: str) -> dict[str, str]:
    return {
        node.targets[0].id: node.value.value
        for node in ast.parse(text).body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("_CREATE_") and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }


_P7_6_DDL = {
    "_CREATE_INVESTMENT_DETAILS_TABLE_SQL": "investment_details",
    "_CREATE_INVESTMENT_UNIT_DETAILS_TABLE_SQL": "investment_unit_details",
    "_CREATE_INVESTMENT_CAPITAL_PLAN_ITEMS_TABLE_SQL": "investment_capital_plan_items",
    "_CREATE_INVESTMENT_OWNER_EXPENSE_ITEMS_TABLE_SQL": "investment_owner_expense_items",
    "_CREATE_INVESTMENT_TRANSACTION_COSTS_TABLE_SQL": "investment_transaction_costs",
}


def test_every_earlier_table_is_unchanged_and_five_sidecars_are_appended() -> None:
    current, baseline = _create_constants(_current(_STORE)), _create_constants(_baseline(_STORE))
    assert {name: current[name] for name in baseline} == baseline
    assert set(current) - set(baseline) == set(_P7_6_DDL)
    for name, table in _P7_6_DDL.items():
        statement = " ".join(current[name].split())
        assert statement.startswith(f"CREATE TABLE IF NOT EXISTS {table} ("), name
        assert not re.search(r"\b(ALTER|DROP|INSERT|UPDATE|DELETE)\b", statement), name
    assert _current(_STORE).count("ALTER TABLE") == _baseline(_STORE).count("ALTER TABLE")


def test_the_migration_body_is_unchanged_and_the_version_moves_to_10() -> None:
    current, baseline = _tree(_STORE), ast.parse(_baseline(_STORE))
    assert ast.dump(_functions(current)["_migrate"]) == ast.dump(_functions(baseline)["_migrate"])
    assert re.search(r"^_SCHEMA_VERSION = 10$", _current(_STORE), re.MULTILINE)
    assert re.search(r"^_SCHEMA_VERSION = 9$", _baseline(_STORE), re.MULTILINE)

    def executes(tree: ast.Module) -> list[str]:
        return [ast.unparse(node.args[0]) for node in _call_nodes(_functions(tree)["_connect"], "execute")]

    assert executes(current) == executes(baseline) + list(_P7_6_DDL)


#: The functions P7.6 adds to ``store.py``.
_P7_6_STORE_FUNCTIONS = {
    "_read_deal", "_require_structure_owner", "_scenario_contract_issues", "_strategy_contract_issues",
    "_visible_details_row", "_require_visible_units", "_membership_from_row", "_transaction_cost_from_row",
    "_read_investment_business_plan", "_read_visible_investment", "_write_visible_details", "_write_membership",
    "_replace_investment_business_plan", "_replace_transaction_costs", "_require_standalone_deal",
    "_unit_economic_facts", "_require_valid_investment_inputs", "_require_reconciled_base", "_structure_references",
    "get_visible_investment", "list_visible_investments", "create_visible_investment", "promote_hidden_investment",
    "update_visible_investment", "add_investment_unit", "update_investment_unit", "remove_investment_unit",
}

#: The P7.2 / P7.4 functions P7.6 changes: ``get_deal`` reads through
#: ``_read_deal``; ``_connect`` appends the sidecars; the Scenario and Strategy
#: functions take the structure owner (the hidden wrapper's one Unit, exactly as
#: before, or a visible Investment's member set) and a visible Investment never
#: collapses; deleting an Investment deletes its sidecars; a Deal of a visible
#: Investment is refused with the P7.6 reason. Every other function --
#: ``delete_deal``, ``_require_hidden_wrapper``, ``_materialize_hidden_investment``
#: and every variant-cache function included -- is the base's exactly.
_P7_6_CHANGED_STORE_FUNCTIONS = {
    "_connect", "get_deal", "_delete_investment_rows", "_remove_hidden_wrapper_of_deal",
    "_require_valid_scenario", "_scenario_from_rows", "_read_scenarios", "create_scenario_for_deal",
    "create_scenario", "update_scenario", "delete_scenario", "delete_investment", "list_scenarios",
    "get_scenario", "list_deal_scenarios", "_require_valid_strategy", "_strategy_from_rows", "_read_strategies",
    "create_strategy_for_deal", "create_strategy", "update_strategy", "delete_strategy", "list_strategies",
    "get_strategy", "list_deal_strategies",
}


def test_p7_6_added_and_changed_exactly_the_enumerated_store_functions() -> None:
    added, changed = _changed_functions(_STORE)
    assert added == _P7_6_STORE_FUNCTIONS
    assert changed == _P7_6_CHANGED_STORE_FUNCTIONS


def test_the_hidden_wrapper_keeps_its_exact_p7_2_contract() -> None:
    functions = _functions(_tree(_STORE))
    owner = ast.unparse(functions["_require_structure_owner"])
    assert "unit_id, operating_mode = _require_hidden_wrapper(connection, investment_id)" in owner
    for name in ("_scenario_contract_issues", "_strategy_contract_issues"):
        text = ast.unparse(functions[name])
        assert "if owner.hidden:" in text and re.search(r"return validate_(scenario|strategy)\(", text), name
    for name in ("delete_scenario", "delete_strategy"):
        assert "if owner.hidden and _wrapper_holds_no_structure(connection, investment_id):" in ast.unparse(functions[name])


def test_the_new_store_code_does_no_arithmetic_but_a_display_ordinal() -> None:
    functions = _functions(_tree(_STORE))
    found = {name: _arithmetic(functions[name]) for name in _P7_6_STORE_FUNCTIONS if _arithmetic(functions[name])}
    assert found == {"add_investment_unit": ["max((existing.ordinal for existing in current.units)) + 1"]}


def test_every_write_is_validated_first() -> None:
    functions = _functions(_tree(_STORE))
    validations = {"_require_valid_investment_inputs", "_require_standalone_deal", "_require_reconciled_base"}
    writes = {"execute", "_write_membership", "_write_visible_details", "_replace_investment_business_plan",
              "_replace_transaction_costs", "_touch_investment"}
    for name in (
        "create_visible_investment", "promote_hidden_investment", "update_visible_investment",
        "add_investment_unit", "remove_investment_unit",
    ):
        calls = sorted((node.lineno, _callee(node)) for node in ast.walk(functions[name]) if isinstance(node, ast.Call))
        checked = [line for line, callee in calls if callee in validations]
        written = [line for line, callee in calls if callee in writes]
        assert checked and written and max(checked) < min(written), name
    investment_writers = sorted(
        name for name, function in functions.items() if any("INSERT INTO investments " in text for text in _strings(function))
    )
    assert investment_writers == ["_materialize_hidden_investment", "create_visible_investment"]
    visible_flips = sorted(name for name, function in functions.items() if any("SET is_hidden = 0" in t for t in _strings(function)))
    assert visible_flips == ["promote_hidden_investment"]


def test_every_visible_read_path_is_free_of_writes() -> None:
    functions = _functions(_tree(_STORE))
    for name in ("get_visible_investment", "list_visible_investments", "_read_visible_investment", "_require_visible_units",
                 "_visible_details_row", "_read_investment_business_plan", "_structure_references", "_require_structure_owner"):
        assert [t for t in _strings(functions[name]) if re.search(r"\b(INSERT|UPDATE|DELETE)\b", t)] == [], name
        assert not {c for c in _calls(functions[name]) if c.startswith(("_write", "_replace", "_insert", "_touch", "_delete"))}, name


def test_a_deal_in_a_visible_investment_is_refused_before_anything_is_deleted() -> None:
    function = _functions(_tree(_STORE))["_remove_hidden_wrapper_of_deal"]
    text = ast.unparse(function)
    assert text.index("raise InvestmentStructureError(") < text.index("_delete_investment_rows(connection, investment_id)")
    assert ast.dump(_functions(_tree(_STORE))["delete_deal"]) == ast.dump(_functions(ast.parse(_baseline(_STORE)))["delete_deal"])


# =============================================================================
# 6. P7.2 - P7.5 compatibility
# =============================================================================


def test_every_baseline_api_node_is_unchanged_and_the_additions_compute_nothing() -> None:
    current = {ast.dump(node) for node in ast.parse(_current(_API)).body}
    removed = [node for node in ast.parse(_baseline(_API)).body if ast.dump(node) not in current]
    assert removed == []
    assert _arithmetic(ast.Module(body=_added_nodes(_API), type_ignores=[])) == []


def _routes(text: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and ast.unparse(decorator.func.value) == "app" and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                ):
                    found.add((decorator.func.attr, str(decorator.args[0].value)))
    return found


def test_p7_6_adds_exactly_these_routes() -> None:
    variant = "/investments/{investment_id}/investment-variants/{strategy_id}/{scenario_id}"
    assert _routes(_current(_API)) - _routes(_baseline(_API)) == {
        ("get", "/investments"),
        ("post", "/investments"),
        ("get", "/investments/{investment_id}/details"),
        ("put", "/investments/{investment_id}/details"),
        ("post", "/investments/{investment_id}/promote"),
        ("post", "/investments/{investment_id}/units"),
        ("put", "/investments/{investment_id}/units/{unit_id}"),
        ("delete", "/investments/{investment_id}/units/{unit_id}"),
        ("get", f"{variant}/inputs"),
        ("get", f"{variant}/fingerprint"),
        ("post", f"{variant}/analysis"),
        ("post", "/investments/{investment_id}/investment-decision-matrix"),
    }


def test_no_api_name_is_defined_twice() -> None:
    """A later ``def`` silently shadows an import of the same name -- how a P7.6
    route first reached a P7.4 route function. Every top-level name is bound
    once."""

    names: list[str] = []
    for node in ast.parse(_current(_API)).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend(alias.asname or alias.name for alias in node.names)
    assert sorted({name for name in names if names.count(name) > 1}) == []


def test_the_one_unit_matrix_service_only_gained_the_visible_refusal() -> None:
    added, changed = _changed_functions(_SERVICE)
    assert added == {"_unit_located", "_investment_cell", "_investment_source_state", "analyze_investment_decision_matrix"}
    assert changed == {"analyze_decision_matrix"}
    current = _functions(_tree(_SERVICE))["analyze_decision_matrix"].body
    baseline = _functions(ast.parse(_baseline(_SERVICE)))["analyze_decision_matrix"].body
    refusal = current[1]
    assert isinstance(refusal, ast.If) and "raise InvestmentStructureError(" in ast.unparse(refusal)
    assert [ast.dump(node) for node in [current[0], *current[2:]]] == [ast.dump(node) for node in baseline]
    handlers = [
        ast.unparse(h.type) for node in ast.walk(_functions(_tree(_SERVICE))["_investment_cell"])
        if isinstance(node, ast.Try) for h in node.handlers if h.type is not None
    ]
    assert handlers == ["InvestmentVariantValidationError", "InvestmentVariantValidationError"]


def test_the_comparison_changed_only_to_read_consolidated_results() -> None:
    added, changed = _changed_functions(_COMPARISON)
    assert (added, changed) == (set(), {"_applicable_metrics", "_reported", "compare_decision_matrix"})
    assert _imports(_tree(_COMPARISON)) == _imports(ast.parse(_baseline(_COMPARISON))) | {"..consolidation.contracts"}
    assert _arithmetic(_tree(_COMPARISON)) == ["target.value - reference.value", "high[0] - low[0]"]
    reported = _functions(_tree(_COMPARISON))["_reported"]
    baseline = _functions(ast.parse(_baseline(_COMPARISON)))["_reported"]
    assert _attributes(reported) - _attributes(baseline) == {"min_aggregate_dscr"}
    assert [(s.metric, s.unit, s.direction, s.horizon_dependent) for s in INVESTMENT_PROJECT_METRIC_CATALOG] == [
        (s.metric, s.unit, s.direction, s.horizon_dependent) for s in PROJECT_METRIC_CATALOG
    ]
    assert [s.label for s in INVESTMENT_PROJECT_METRIC_CATALOG if s.label != next(p.label for p in PROJECT_METRIC_CATALOG if p.metric is s.metric)] == [
        "Minimum Aggregate DSCR"
    ]
    assert next(s for s in PROJECT_METRIC_CATALOG if s.metric is DecisionMetric.MIN_DSCR).label == "Minimum DSCR"


def test_the_scenario_and_strategy_engines_generalized_only_unit_addressing() -> None:
    for path, public in ((_SCENARIO, "validate_scenario"), (_STRATEGY, "validate_strategy")):
        added, changed = _changed_functions(path)
        assert added == {"_contract_issues", "_foreign_unit_message", f"validate_investment_{public.split('_')[1]}"}, path
        assert changed == {public}, path
        body = _functions(_tree(path))[public].body
        assert ast.unparse(body[-1]).startswith("return _contract_issues(") and "{unit_id: operating_mode}" in ast.unparse(body[-1])
        assert _arithmetic(_functions(_tree(path))["_contract_issues"]) == []


# =============================================================================
# 7. No later-gate concept, no AI, no frontend, no case identifier
# =============================================================================

_LATER_GATE_VOCABULARY = re.compile(
    r"waterfall|partner|capital_position|capital_event|capital_structure|tranche|promote_earned|refinanc|recapitali"
    r"|mezzanine|preferred_equity|unit_selection|valuation_timepoint|as_is|stabiliz|funding_requirement",
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


@pytest.mark.parametrize("path", sorted(_P7_6_BACKEND_FILES))
def test_no_p7_6_code_names_a_later_gate_concept(path: str) -> None:
    code = ast.Module(body=_added_nodes(path), type_ignores=[])
    assert {t for t in _identifiers_and_strings(code) if _LATER_GATE_VOCABULARY.search(t)} == set()


def _added_web_text(path: str) -> str:
    """Every line P7.6 added to a frontend file that already existed at the
    base."""

    diff = _git("diff", "-U0", _P7_6_BASE, "--", path)
    return "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))


def _is_new_web_file(path: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{_P7_6_BASE}:{path}"], capture_output=True, cwd=_PROJECT_ROOT
    ).returncode != 0


@pytest.mark.parametrize("path", sorted(_P7_6_WEB_FILES))
def test_no_p7_6_frontend_addition_names_a_later_gate_concept(path: str) -> None:
    """Session B adds no Capital Structure, Partnership, waterfall, refinancing,
    valuation-timepoint, funding-requirement or Unit-selection surface."""

    text = _current(path) if _is_new_web_file(path) else _added_web_text(path)
    assert sorted({match.group(0) for match in _LATER_GATE_VOCABULARY.finditer(text)}) == []


def test_the_vocabulary_guard_has_teeth() -> None:
    tree = ast.parse("capital_structure = 1\ndef waterfall(): return 'UNIT_SELECTION'\n")
    assert {t for t in _identifiers_and_strings(tree) if _LATER_GATE_VOCABULARY.search(t)} == {
        "capital_structure", "waterfall", "UNIT_SELECTION",
    }


def test_no_unit_selection_domain_ships() -> None:
    assert {domain.value for domain in StrategyDomain} == {
        "acquisition", "financing", "business_plan", "operating_outcome", "disposition",
    }


def test_no_p7_6_module_reaches_the_ai() -> None:
    for path in sorted(_P7_6_BACKEND_FILES - {_API, _STORE, _CONTRACTS}):
        assert not {name for name in _imports(_tree(path)) if re.search(r"(^|\.)ai(\.|$)", name)}, path


@pytest.mark.parametrize("path", sorted(_P7_6_PRODUCTION_FILES))
def test_no_case_or_competition_identifier(path: str) -> None:
    import test_p7_0_decision_architecture as p7_0

    assert p7_0._case_identifiers_in(_current(path)) == []
