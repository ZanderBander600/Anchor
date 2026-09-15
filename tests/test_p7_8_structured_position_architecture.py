"""Phase 7 Gate P7.8 -- the production ledger and the architecture guards for
structured position execution.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3 (P-1,
P-3, P-4, P-7, P-14), 12, 14 and 22.5, and the P7.8 Q16 engine-scope approval
(``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md`` Section 1). Every
git query reads objects only (protocol 11.2). The guards hold:

1. **the P7.8 production ledger**, and every protected path -- the mature
   engine, consolidation, persistence, routes, the Decision Matrix, the
   frontend and the four P7.7 modules -- unchanged, the mature financial
   modules byte for byte;
2. **reuse, never duplication** -- the debt helpers and the returns functions
   each enter through one module, by name; no second IRR solver, NOI engine,
   shortfall engine or loan sizing exists; the arithmetic is exactly the
   enumerated set;
3. **the legacy loan read only** -- no P7.8 module reads its balance or fee or
   an unlevered series, and every residual starts from a post-acquisition-debt
   authority;
4. **no implicit cure** -- no P7.8 module names a resolution; each claim
   carries its own position's;
5. **scope isolation and economic order**;
6. **no later-gate economics or surface** -- valuation, draws, PIK,
   refinancing, partnership, persistence, routes, the Strategy domain.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from anchor.analysis.strategy import StrategyDomain
from anchor.deals import store

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.8 began: the P7.7 merge (PR #27).
_P7_8_BASE = "a9f9b09fd71940cfdc079c109e9261187a041261"
_P7_7_BASE = "fbaa07bfe546b05d104e4e6335f8501ca9293558"

_PACKAGE = "src/anchor/capital_structure"
_INIT = f"{_PACKAGE}/__init__.py"
_EXEC_CONTRACTS = f"{_PACKAGE}/execution_contracts.py"
_EXEC_VALIDATION = f"{_PACKAGE}/execution_validation.py"
_FUNDING = f"{_PACKAGE}/funding.py"
_DEBT_POSITION = f"{_PACKAGE}/debt_position.py"
_PREFERRED = f"{_PACKAGE}/preferred.py"
_METRICS = f"{_PACKAGE}/metrics.py"
_EXECUTION = f"{_PACKAGE}/execution.py"
_NEW = (_EXEC_CONTRACTS, _EXEC_VALIDATION, _FUNDING, _DEBT_POSITION, _PREFERRED, _METRICS, _EXECUTION)
_P7_8_MODULES = (_INIT, *_NEW)

#: Every production file P7.8 Session A changes, exactly: the seven new
#: modules and the package's exports. No other production file changes.
_P7_8_PRODUCTION_FILES = frozenset(_P7_8_MODULES)

#: The P7.7 modules P7.8 executes on and changes none of.
_P7_7_MODULES = tuple(f"{_PACKAGE}/{name}.py" for name in ("contracts", "validation", "legacy", "foundation"))

#: Everything P7.8 consumes and changes none of.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/consolidation",
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
    *_P7_7_MODULES,
)

_MATURE = (
    "src/anchor/engine/debt.py",
    "src/anchor/engine/acquisition.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/returns.py",
    "src/anchor/consolidation/engine.py",
)

#: The unchanged ``anchor.engine.debt`` helpers, reached only by ``debt_position``.
_DEBT_HELPERS = {
    "calculate_scheduled_payment_count",
    "calculate_monthly_rate",
    "calculate_io_months",
    "calculate_io_payment",
    "calculate_monthly_debt_service",
    "calculate_monthly_payment",
    "calculate_amortization_schedule",
}

#: The unchanged ``anchor.engine.returns`` functions, reached only by ``metrics``.
_RETURNS_FUNCTIONS = {
    "evaluate_irr",
    "calculate_equity_multiple",
    "calculate_project_return_totals",
    "calculate_dscr_by_year",
    "calculate_headline_dscr",
    "calculate_min_dscr",
    "calculate_year_1_debt_yield",
}


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
    return sorted(changed - _P7_8_PRODUCTION_FILES), sorted(_P7_8_PRODUCTION_FILES - changed)


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


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
    return [child for child in ast.walk(node) if isinstance(child, ast.Call) and _callee(child) == name]


def _keywords(call: ast.Call) -> dict[str, str]:
    return {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg is not None}


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


def _code(path: str) -> ast.Module:
    return _without_docstrings(_tree(path))


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
        elif isinstance(node, ast.alias):
            found.add(node.asname or node.name)
    return found


def _attributes(tree: ast.AST) -> set[str]:
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def _strings(tree: ast.AST) -> list[str]:
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod, ast.MatMult)


def _is_text(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str))


def _arithmetic(node: ast.AST) -> set[str]:
    """Every numeric operation, unparsed. String concatenation is not
    arithmetic."""

    return {
        ast.unparse(child)
        for child in ast.walk(node)
        if (
            isinstance(child, (ast.BinOp, ast.AugAssign))
            and isinstance(child.op, _ARITHMETIC)
            and not (isinstance(child, ast.BinOp) and (_is_text(child.left) or _is_text(child.right)))
        )
        or (isinstance(child, ast.UnaryOp) and isinstance(child.op, (ast.USub, ast.UAdd)))
    }


# =============================================================================
# 1. The P7.8 production ledger and the protected paths
# =============================================================================


def test_p7_8_changed_exactly_its_authorized_production_files() -> None:
    """The P7.8 production ledger. P7.8 Session B continues on the same branch
    and must extend this set explicitly; the next gate re-pins it to P7.8's
    committed range. Never widen it to admit another gate's files."""

    changed = {path for path in _changes_since(_P7_8_BASE, "src", "web") if _is_production(path)}
    assert _ledger_violations(changed) == ([], [])


def test_the_p7_8_ledger_base_is_the_p7_7_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_8_BASE).split()[1:]
    assert parents == [_P7_7_BASE, _git("rev-parse", "6abdeb8").strip()]


def test_the_ledger_rejects_any_unexpected_production_change() -> None:
    assert _ledger_violations(set(_P7_8_PRODUCTION_FILES)) == ([], [])
    for intruder in (
        *_MATURE, *_P7_7_MODULES, "src/anchor/engine/contracts.py", "src/anchor/consolidation/contracts.py",
        "src/anchor/deals/store.py", "src/anchor/api.py", "web/src/api.ts",
    ):
        assert _ledger_violations({*_P7_8_PRODUCTION_FILES, intruder}) == ([intruder], [])


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_p7_7(path: str) -> None:
    assert _changes_since(_P7_8_BASE, path) == set(), f"{path} changed at P7.8"


@pytest.mark.parametrize("path", (*_MATURE, *_P7_7_MODULES))
def test_each_mature_module_is_byte_identical_to_the_p7_7_merge(path: str) -> None:
    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_P7_8_BASE}:{path}").strip(), path


def test_the_package_init_changes_only_by_its_exports() -> None:
    """``__init__`` keeps every P7.7 export and adds only imports and names:
    no statement other than its docstring, imports and ``__all__``."""

    current = _tree(_INIT)
    baseline = ast.parse(_git("show", f"{_P7_8_BASE}:{_INIT}"))
    assert {type(node) for node in current.body} <= {ast.Expr, ast.ImportFrom, ast.Assign}

    def exported(tree: ast.Module) -> set[str]:
        (assignment,) = [node for node in tree.body if isinstance(node, ast.Assign)]
        return set(ast.literal_eval(assignment.value))

    assert exported(baseline) < exported(current)
    for module in _imports(baseline):
        assert _imported_names(baseline, module) <= _imported_names(current, module), module


# =============================================================================
# 2. Reuse, never duplication
# =============================================================================

_EXPECTED_IMPORTS = {
    _INIT: {
        "__future__", ".contracts", ".execution", ".execution_contracts", ".execution_validation", ".foundation",
        ".legacy", ".validation",
    },
    _EXEC_CONTRACTS: {"__future__", "collections.abc", "dataclasses", "enum", "..engine.contracts", ".contracts"},
    _EXEC_VALIDATION: {"__future__", ".contracts", ".execution_contracts", ".preferred", ".validation"},
    _FUNDING: {"__future__", "..consolidation.contracts", "..contracts", "..engine.contracts", ".contracts", ".execution_contracts"},
    _DEBT_POSITION: {"__future__", "..engine.debt", ".contracts", ".execution_contracts"},
    _PREFERRED: {"__future__", ".contracts", ".execution_contracts"},
    _METRICS: {"__future__", "collections.abc", "..engine.contracts", "..engine.returns", ".execution_contracts", ".foundation"},
    _EXECUTION: {
        "__future__", "collections", "collections.abc", "..consolidation.contracts", "..contracts", "..engine.contracts",
        ".contracts", ".debt_position", ".execution_contracts", ".execution_validation", ".foundation", ".funding",
        ".metrics", ".preferred", ".validation",
    },
}

_FORBIDDEN_IMPORTS = re.compile(
    r"(^|\.)(acquisition|noi|operating|operating_projection|analysis|leasing|business_plan|deals|store|api|ai"
    r"|decision|investment|ingestion)(\.|$)|consolidation\.engine|sqlite3|fastapi|numpy|scipy"
)


@pytest.mark.parametrize("path", _P7_8_MODULES)
def test_each_module_imports_exactly_what_it_needs(path: str) -> None:
    imports = _imports(_tree(path))
    assert imports == _EXPECTED_IMPORTS[path]
    assert not {name for name in imports if _FORBIDDEN_IMPORTS.search(name)}, path


def test_upstream_names_are_calculation_free_contracts_except_the_two_named_authorities() -> None:
    for path in _P7_8_MODULES:
        tree = _tree(path)
        assert _imported_names(tree, "..engine.contracts") <= {"AcquisitionResults", "IrrStatus", "ensure_finite"}, path
        assert _imported_names(tree, "..consolidation.contracts") <= {"ConsolidatedResults"}, path
        assert _imported_names(tree, "..contracts") <= {"AcquisitionTerms"}, path
        assert bool(_imported_names(tree, "..engine.debt")) is (path == _DEBT_POSITION), path
        assert bool(_imported_names(tree, "..engine.returns")) is (path == _METRICS), path
    assert _imported_names(_tree(_DEBT_POSITION), "..engine.debt") == _DEBT_HELPERS
    assert _imported_names(_tree(_METRICS), "..engine.returns") == _RETURNS_FUNCTIONS


def test_the_debt_helpers_are_called_not_copied() -> None:
    debt = _tree("src/anchor/engine/debt.py")
    debt_functions = {node.name for node in debt.body if isinstance(node, ast.FunctionDef)}
    assert _DEBT_HELPERS <= debt_functions
    code = _code(_DEBT_POSITION)
    assert _DEBT_HELPERS <= set(_calls(code))
    for path in _P7_8_MODULES:
        code = _code(path)
        names = _identifiers(code)
        allowed = _DEBT_HELPERS if path == _DEBT_POSITION else set()
        assert names & debt_functions <= allowed, path
        assert not names & {"expm1", "log1p", "pow", "isclose", "exp", "log"}, path
        assert not [node for node in ast.walk(code) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)], path
        # No loan is sized: the authored principal is the resolved funding.
        assert not set(_calls(code)) & {
            "calculate_capital_stack", "calculate_debt_schedule", "calculate_loan_amount", "calculate_financing_fee",
            "calculate_initial_equity", "AcquisitionTerms",
        }, path
    assert not [node for node in ast.walk(_code(_DEBT_POSITION)) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)]


def test_every_irr_is_evaluate_irr_and_no_second_solver_exists() -> None:
    solver_like = re.compile(
        r"(^|_)(solve|solver|horner|bisect|bisection|newton|secant|find_root|npv|xirr|discount)(_|$)", re.IGNORECASE
    )
    assert solver_like.search("_solve_x_star") and solver_like.search("npv_at") and not solver_like.search("resolve_funding")
    for path in _P7_8_MODULES:
        code = _code(path)
        calls = _calls(code)
        assert ("evaluate_irr" in calls) is (path == _METRICS), path
        assert "calculate_irr" not in calls and "calculate_return_metrics" not in calls, path
        functions = {node.name for node in ast.walk(code) if isinstance(node, ast.FunctionDef)}
        assert not {name for name in functions if solver_like.search(name)}, path
        assert not [node for node in ast.walk(code) if isinstance(node, ast.While)], path
    metrics = _functions(_tree(_METRICS))
    assert [name for name, function in metrics.items() if "evaluate_irr" in _calls(function)] == [
        "position_irr", "common_equity_metrics",
    ]


def test_no_second_project_noi_or_owner_cash_flow_engine_exists() -> None:
    """Capital Structure consumes completed results: it never reads, derives or
    re-states rent, vacancy, expenses, exit value, the unlevered series or the
    owner cash-flow chain."""

    forbidden = {
        "exit_value", "exit_noi", "exit_cap_rate", "disposition_costs", "capex_by_year", "unlevered_cash_flows",
        "unlevered_owner_cash_flow_by_year", "property_cash_flow_by_year", "levered_owner_cash_flow_by_year",
        "remaining_loan_balance", "financing_fee", "net_sale_proceeds", "project_capital_by_year",
        "owner_expenses_by_year", "tenant_improvements_by_year", "leasing_commissions_by_year",
        "gross_potential_rent", "vacancy_credit_loss_pct", "current_noi", "noi_growth",
    }
    for path in _P7_8_MODULES:
        assert not _attributes(_code(path)) & forbidden, path


#: Every numeric operation of each P7.8 module: funding resolution and signs;
#: the debt wrapper's payoff month and indexing (no debt formula); the ratified
#: preferred formulas; annual aggregation, MOIC, profit and loan-to-price; and
#: the residual settlement, claim sums and cumulative layers. Nothing else --
#: in particular no subtraction of any acquisition-loan figure.
_P7_8_ARITHMETIC = {
    _INIT: set(),
    _EXEC_CONTRACTS: set(),
    _EXEC_VALIDATION: set(),
    _FUNDING: {"-event.amount", "rule.pct * price_basis.amount", "total + event.amount"},
    _DEBT_POSITION: {"-1", "MONTHS_PER_HOLD_YEAR * hold_period", "payoff_month + 1"},
    _PREFERRED: {
        "(principal + accrued) * accrual_rate",
        "MONTHS_PER_HOLD_YEAR * hold_period",
        "MONTHS_PER_HOLD_YEAR * year",
        "accrued + accrual",
        "payoff_month // MONTHS_PER_HOLD_YEAR",
        "payoff_month // MONTHS_PER_HOLD_YEAR + 1",
        "principal * accrual_rate",
        "principal + accrued",
        "redemption_month % MONTHS_PER_HOLD_YEAR",
        "terms.current_pay_rate * principal",
        "terms.preferred_rate - terms.current_pay_rate",
    },
    _METRICS: {
        "basis / price_basis.amount",
        "hold_period + 1",
        "received + event.amount",
        "received - funded_amount",
        "received / funded_amount",
        "totals[period] + event.amount",
        "totals[year - 1] + event.amount",
        "year - 1",
    },
    _EXECUTION: {
        "attachment + position.funded_amount",
        "claim_due + event.amount",
        "hold_period + 1",
        "residual[0] - event.amount",
        "residual[claim.hold_year] - claim.settlement.claim_paid",
        "residual[year] - settlement.claim_paid",
        "total + mine",
    },
}


@pytest.mark.parametrize("path", _P7_8_MODULES)
def test_each_module_has_exactly_the_enumerated_arithmetic(path: str) -> None:
    assert _arithmetic(_code(path)) == _P7_8_ARITHMETIC[path]


def test_the_arithmetic_guard_would_see_a_second_subtraction_a_netted_fee_or_a_cure() -> None:
    allowed = set().union(*_P7_8_ARITHMETIC.values())
    for mutant in (
        "residual[year] = residual[year] - results.annual_debt_service[year - 1]\n",
        "cash = unit.results.levered_cash_flows[year] - unit.results.remaining_loan_balance\n",
        "moic = received / (funded_amount - fee)\n",
        "accrued = accrued + settlement.unpaid_claim_amount\n",
        "accrual = principal * accrual_rate * (1 + accrual_rate)\n",
        "residual[year] = residual[year] - settlement.claim_paid_from_cash\n",
    ):
        assert _arithmetic(ast.parse(mutant)) - allowed, mutant


# =============================================================================
# 3. The legacy loan is read only; every residual starts from a post-debt authority
# =============================================================================


def test_the_foundation_runs_first_and_every_residual_starts_from_a_post_acquisition_debt_authority() -> None:
    functions = _functions(_tree(_EXECUTION))
    unit = functions["execute_unit_capital_structure"]
    (unit_foundation,) = _call_nodes(unit, "analyze_unit_capital_structure")
    assert set(_keywords(unit_foundation)) == {"unit_id", "terms", "results"}
    unit_text = ast.unparse(unit)
    assert "source = foundation.cash_authority.post_acquisition_debt_cash_flows" in unit_text
    assert "residual = list(source)" in unit_text

    investment = functions["execute_investment_capital_structure"]
    (investment_foundation,) = _call_nodes(investment, "analyze_investment_capital_structure")
    assert set(_keywords(investment_foundation)) == {"units", "consolidated"}
    investment_text = ast.unparse(investment)
    assert "source = foundation.investment_cash_authority.cash_flows_after_unit_positions" in investment_text
    assert "investment_residual = list(source)" in investment_text
    assert "unit_residual = list(unit.results.levered_cash_flows)" in investment_text
    lists = [ast.unparse(call.args[0]) for call in _call_nodes(_code(_EXECUTION), "list")]
    assert sorted(lists) == ["source", "source", "unit.results.levered_cash_flows"]


def test_the_acquisition_loan_figures_only_seed_the_structural_layers() -> None:
    """``loan_amount`` and ``annual_debt_service`` are read only as the capital
    and the service senior to the first authored position of a scope -- for
    attachment and coverage -- and never enter a cash flow."""

    code = _code(_EXECUTION)
    reads = {
        ast.unparse(node) for node in ast.walk(code)
        if isinstance(node, ast.Attribute) and node.attr in {"loan_amount", "annual_debt_service"}
    }
    seeded = {
        value for call in _call_nodes(code, "_layers")
        for key, value in _keywords(call).items() if key in {"senior_capital", "senior_service"}
    }
    assert reads == {
        "results.loan_amount", "results.annual_debt_service", "unit.results.loan_amount",
        "unit.results.annual_debt_service", "consolidated.loan_amount", "consolidated.annual_debt_service",
    }
    assert reads <= seeded


# =============================================================================
# 4. No implicit cure
# =============================================================================


def test_no_p7_8_module_names_a_resolution_and_each_claim_carries_its_positions_own() -> None:
    """``__init__`` only re-exports P7.7's ``ShortfallResolution``; no executing
    module names a resolution at all."""

    for path in _NEW:
        names = _identifiers(_code(path))
        assert not names & {"ShortfallResolution", "COMMON_EQUITY_CONTRIBUTION"}, path
        assert "FundingRequirement" not in _calls(_code(path)), path
    settle = ast.unparse(_functions(_tree(_EXECUTION))["_settle_position"])
    assert "resolution = position.shortfall_resolution" in settle
    assert "shortfall_resolution=resolution" in settle
    assert "cash_available=available if available > 0.0 else 0.0" in settle
    assert "residual[year] = residual[year] - settlement.claim_paid" in settle
    code = _code(_EXECUTION)
    assert _calls(code).count("settle_claim") == 1 and _calls(code).count("common_equity_outcome") == 1


# =============================================================================
# 5. Scope isolation and economic order
# =============================================================================


def test_structural_subordination_is_scope_then_priority() -> None:
    functions = _functions(_tree(_EXECUTION))
    assert "return economic_order(structure.positions)" in ast.unparse(functions["_executable_positions"])
    sorts = _call_nodes(_code(_EXECUTION), "sorted")
    keys = sorted(_keywords(call).get("key", "") for call in sorts)
    assert keys == ["", "event_order_key", "lambda unit: unit.unit_id"]
    # The one keyless sort orders duplicated event ids for a refusal message only.
    (keyless,) = [call for call in sorts if "key" not in _keywords(call)]
    assert ast.unparse(keyless.args[0]).startswith("(identity for identity, count in Counter(")


def test_a_unit_scope_is_settled_against_its_own_units_cash_only() -> None:
    investment = _functions(_tree(_EXECUTION))["execute_investment_capital_structure"]
    settles = [_keywords(call) for call in _call_nodes(investment, "_settle_scope")]
    assert {(kw["residual"], kw["blocking"]) for kw in settles} == {
        ("unit_residual", "()"), ("investment_residual", "tuple(unit_blocking)"),
    }
    loop = next(node for node in ast.walk(investment) if isinstance(node, ast.For) and ast.unparse(node.iter) == "ordered")
    text = ast.unparse(loop)
    assert "_unit_id(position.position) == unit.unit_id" in text
    assert "unit_residual = list(unit.results.levered_cash_flows)" in text


# =============================================================================
# 6. No later-gate economics or surface
# =============================================================================

_LATER = re.compile(
    r"refinanc|recapitali|waterfall|partner|promote|hurdle|catch_up|valuation_timepoint|as_is|stabiliz|xirr"
    r"|capital_call|draw_schedule",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", _P7_8_MODULES)
def test_no_refinancing_partnership_or_valuation_timepoint_economics(path: str) -> None:
    assert not {name for name in _identifiers(_code(path)) if _LATER.search(name)}, path


def test_the_later_gate_guard_has_teeth() -> None:
    assert _LATER.search("RefinanceEvent") and _LATER.search("partner_share") and _LATER.search("as_is_value")
    assert not _LATER.search("timepoint_id")


def test_pct_of_value_is_never_valued() -> None:
    resolve = _functions(_tree(_FUNDING))["resolve_funding"]
    (case,) = [
        case for node in ast.walk(resolve) if isinstance(node, ast.Match) for case in node.cases
        if ast.unparse(case.pattern) == "PctOfValue()"
    ]
    assert [type(statement) for statement in case.body] == [ast.Raise]


def test_later_funding_months_and_fees_are_refused_never_moved_to_closing() -> None:
    validation = _current(_EXEC_VALIDATION)
    assert "if event.model_month != 0:" in validation and "if fee.model_month != 0" in validation
    for path in (_FUNDING, _EXECUTION):
        assert "model_month=0" not in ast.unparse(_code(path)), path


def test_debt_pik_is_never_executed() -> None:
    for path in _P7_8_MODULES:
        assert ("pik_rate" in _attributes(_code(path))) is (path == _EXEC_VALIDATION), path
    schedule = _functions(_tree(_DEBT_POSITION))["schedule_debt_position"]
    reads = {node.attr for node in ast.walk(schedule) if isinstance(node, ast.Attribute) and ast.unparse(node.value) == "terms"}
    assert reads == {"amortization", "interest_rate", "io_period", "maturity_month"}


def test_preferred_accrual_follows_only_the_explicit_contract() -> None:
    schedule = _functions(_tree(_PREFERRED))["schedule_preferred_position"]
    reads = {node.attr for node in ast.walk(schedule) if isinstance(node, ast.Attribute) and ast.unparse(node.value) == "terms"}
    assert reads == {"accrual_convention", "current_pay_rate", "preferred_rate", "redemption_month"}
    text = ast.unparse(schedule)
    assert "elif terms.accrual_convention is AccrualConvention.SIMPLE:" in text
    assert "elif terms.accrual_convention is AccrualConvention.ANNUAL_COMPOUND:" in text
    assert not _attributes(_code(_PREFERRED)) & {"unpaid_claim_amount", "funding_requirement", "settlement", "claim_paid"}


def test_no_persistence_schema_or_sql() -> None:
    assert store._SCHEMA_VERSION == 10
    for path in _P7_8_MODULES:
        text = " ".join(_strings(_code(path)))
        assert not re.search(r"\b(CREATE|INSERT|SELECT|UPDATE|DELETE|ALTER|DROP)\b", text), path


def test_no_route_serves_the_executor() -> None:
    api = _current("src/anchor/api.py")
    assert "execute_unit_capital_structure" not in api and "execute_investment_capital_structure" not in api
    assert "capital_structure" not in api


def test_no_strategy_capital_structure_domain_is_wired() -> None:
    assert {domain.value for domain in StrategyDomain} == {
        "acquisition", "financing", "business_plan", "operating_outcome", "disposition",
    }


def test_nothing_upstream_imports_the_capital_structure() -> None:
    importers = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        if "capital_structure" not in path.relative_to(_PROJECT_ROOT / "src" / "anchor").parts[:1]
        and any("capital_structure" in name for name in _imports(ast.parse(path.read_text(encoding="utf-8"))))
    )
    assert importers == []


def test_every_new_contract_is_a_frozen_slotted_keyword_only_dataclass() -> None:
    classes = [node for node in _tree(_EXEC_CONTRACTS).body if isinstance(node, ast.ClassDef)]
    exempt = {"StrEnum", "ValueError"}
    checked = 0
    for node in classes:
        if {ast.unparse(base) for base in node.bases} & exempt:
            continue
        (decorator,) = node.decorator_list
        assert isinstance(decorator, ast.Call) and _callee(decorator) == "dataclass", node.name
        assert _keywords(decorator) == {"frozen": "True", "slots": "True", "kw_only": "True"}, node.name
        checked += 1
    assert checked == 12
    for path in (_EXEC_VALIDATION, _FUNDING, _DEBT_POSITION, _PREFERRED, _METRICS, _EXECUTION, _INIT):
        assert not [node for node in _tree(path).body if isinstance(node, ast.ClassDef)], path


@pytest.mark.parametrize("path", _P7_8_MODULES)
def test_no_case_or_competition_identifier(path: str) -> None:
    import test_p7_0_decision_architecture as p7_0

    assert p7_0._case_identifiers_in(_current(path)) == []
