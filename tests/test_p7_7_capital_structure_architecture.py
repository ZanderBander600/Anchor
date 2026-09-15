"""Phase 7 Gate P7.7 -- the production ledger and the architecture guards for
the Capital Structure foundation.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3 (P-1,
P-3, P-4, P-14), 12 and 22.5, and the P7.7 gate's own Q16 engine-scope approval:
downstream Capital Structure contracts, structural validation, claim settlement
and Funding Requirement reporting, the read-only legacy acquisition-loan adapter
and the neutral facade -- and nothing else. Every git query reads objects only
(protocol 11.2). The guards hold:

1. **the P7.7 production ledger**, and every protected path -- the mature
   engine, consolidation, persistence, routes, the Decision Matrix and the
   frontend -- unchanged, the mature financial modules byte for byte;
2. **downstream and read only** -- the package imports completed contracts,
   never an engine, a debt function or a returns function, and nothing
   upstream imports it; the adapter reads the enumerated result fields; the
   package's arithmetic is exactly the enumerated claim composition, timing
   and settlement;
3. **neutrality and the handoff** -- the Common Equity Cash Flow is the
   existing levered series passed through, and no Investment-scope authority
   reads the consolidated unlevered series;
4. **no implicit cure** -- two resolutions, no default, and common-equity
   contribution named only by the adapter and its one settlement branch;
5. **no later-gate economics** -- no position cash flow or return, no accrual,
   refinancing, partnership, persistence, route, Strategy domain or AI.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from anchor.analysis.strategy import StrategyDomain
from anchor.capital_structure import ShortfallResolution
from anchor.deals import store

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.7 began: the no-ff P7.6 merge.
_P7_7_BASE = "fbaa07bfe546b05d104e4e6335f8501ca9293558"
#: The P7.7 merge (PR #27; parents ``fbaa07b`` and ``6abdeb8``). Pinned at P7.8:
#: the ledger, the protected paths and the byte identity prove exactly what
#: P7.7's committed range ``fbaa07b..a9f9b09`` changed, however later gates move
#: the tree. P7.8's own ledger is
#: ``tests/test_p7_8_structured_position_architecture.py``.
_P7_7_MERGE = "a9f9b09fd71940cfdc079c109e9261187a041261"

_PACKAGE = "src/anchor/capital_structure"
_INIT = f"{_PACKAGE}/__init__.py"
_CONTRACTS = f"{_PACKAGE}/contracts.py"
_VALIDATION = f"{_PACKAGE}/validation.py"
_LEGACY = f"{_PACKAGE}/legacy.py"
_FOUNDATION = f"{_PACKAGE}/foundation.py"
_MODULES = (_INIT, _CONTRACTS, _VALIDATION, _LEGACY, _FOUNDATION)

#: Every production file P7.7 changes, exactly: the new
#: ``anchor/capital_structure`` package -- the contracts, their structural
#: validation, the read-only legacy acquisition-loan adapter and the neutral
#: facade. No existing production file changes.
_P7_7_PRODUCTION_FILES = frozenset(_MODULES)

#: Everything P7.7 consumes and changes none of: the mature engine,
#: consolidation, the Investment inputs, persistence and variants, the
#: Decision Matrix, analysis, the Business Plan, leasing, AI, ingestion, the
#: routes and every frontend file.
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
)

#: The mature financial modules the gate names: byte-identical to ``fbaa07b``.
_MATURE = (
    "src/anchor/engine/debt.py",
    "src/anchor/engine/acquisition.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/returns.py",
    "src/anchor/consolidation/engine.py",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_between(start: str, end: str, *paths: str) -> set[str]:
    """Files that differ between two commits, renames split into removal and
    addition. Reads Git objects only; it never touches the index."""

    changed = _git("diff", "--name-only", "--no-renames", start, end, "--", *paths).split()
    return {path for path in changed if path}


def _ledger_violations(changed: set[str]) -> tuple[list[str], list[str]]:
    return sorted(changed - _P7_7_PRODUCTION_FILES), sorted(_P7_7_PRODUCTION_FILES - changed)


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


def _strings(tree: ast.AST) -> list[str]:
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod, ast.MatMult)


def _is_text(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str))


def _arithmetic(node: ast.AST) -> set[str]:
    """Every numeric operation, unparsed. String concatenation (a message) is
    not arithmetic."""

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
# 1. The P7.7 production ledger and the protected paths
# =============================================================================


def test_p7_7_changed_exactly_its_authorized_production_files() -> None:
    """The P7.7 production ledger, pinned at P7.8 to P7.7's committed range
    ``fbaa07b..a9f9b09``, so it keeps proving exactly what P7.7 changed however
    later gates move the tree (the P7.6 ledger precedent). Never widen this set
    to admit another gate's files."""

    changed = {path for path in _changes_between(_P7_7_BASE, _P7_7_MERGE, "src", "web") if _is_production(path)}
    assert _ledger_violations(changed) == ([], [])


def test_the_p7_7_ledger_base_is_the_p7_6_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_7_BASE).split()[1:]
    assert parents == [_git("rev-parse", ref).strip() for ref in ("6cade62", "91f1c27")]


def test_the_p7_7_ledger_boundary_is_the_p7_7_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_7_MERGE).split()[1:]
    assert parents == [_P7_7_BASE, _git("rev-parse", "6abdeb8").strip()]


def test_the_ledger_rejects_any_unexpected_production_change() -> None:
    assert _ledger_violations(set(_P7_7_PRODUCTION_FILES)) == ([], [])
    for intruder in (*_MATURE, "src/anchor/engine/contracts.py", "src/anchor/deals/store.py", "src/anchor/api.py", "web/src/api.ts"):
        assert _ledger_violations({*_P7_7_PRODUCTION_FILES, intruder}) == ([intruder], [])


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_by_p7_7(path: str) -> None:
    assert _changes_between(_P7_7_BASE, _P7_7_MERGE, path) == set(), f"{path} changed at P7.7"


@pytest.mark.parametrize("path", _MATURE)
def test_each_mature_financial_module_is_byte_identical_across_p7_7(path: str) -> None:
    assert _git("rev-parse", f"{_P7_7_MERGE}:{path}").strip() == _git("rev-parse", f"{_P7_7_BASE}:{path}").strip(), path


def test_no_frontend_production_file_changed() -> None:
    assert _changes_between(_P7_7_BASE, _P7_7_MERGE, "web") == set()


# =============================================================================
# 2. Downstream and read only
# =============================================================================

_EXPECTED_IMPORTS = {
    # P7.8 extends the package's exports with its executor; its own guards
    # (tests/test_p7_8_structured_position_architecture.py) hold those modules.
    _INIT: {
        "__future__", ".contracts", ".execution", ".execution_contracts", ".execution_validation", ".foundation",
        ".legacy", ".validation",
    },
    _CONTRACTS: {"__future__", "collections.abc", "dataclasses", "enum", "typing", "..contracts", "..engine.contracts"},
    _VALIDATION: {"__future__", "collections", "collections.abc", "math", ".contracts"},
    _LEGACY: {"__future__", "math", "..contracts", "..engine.contracts", ".contracts"},
    _FOUNDATION: {
        "__future__", "collections.abc", "math", "..consolidation.contracts", "..contracts",
        "..engine.contracts", ".contracts", ".legacy", ".validation",
    },
}

_CALCULATING = re.compile(
    r"(^|\.)(acquisition|debt|noi|operating_projection|returns|analysis|leasing|business_plan|deals|store|api|ai"
    r"|decision|investment|ingestion)(\.|$)|consolidation\.engine|sqlite3|fastapi"
)


@pytest.mark.parametrize("path", _MODULES)
def test_the_package_imports_completed_contracts_never_an_engine(path: str) -> None:
    imports = _imports(_tree(path))
    assert imports == _EXPECTED_IMPORTS[path]
    assert not {name for name in imports if _CALCULATING.search(name)}, path


def test_only_calculation_free_names_are_imported_from_upstream() -> None:
    for path in _MODULES:
        tree = _tree(path)
        assert _imported_names(tree, "..engine.contracts") <= {"AcquisitionResults", "ensure_finite"}, path
        assert _imported_names(tree, "..consolidation.contracts") <= {"ConsolidatedResults"}, path
        assert _imported_names(tree, "..contracts") <= {"AcquisitionTerms"}, path


def test_nothing_upstream_imports_the_capital_structure() -> None:
    importers = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        if "capital_structure" not in path.relative_to(_PROJECT_ROOT / "src" / "anchor").parts[:1]
        and any("capital_structure" in name for name in _imports(ast.parse(path.read_text(encoding="utf-8"))))
    )
    assert importers == []


def _debt_functions() -> set[str]:
    tree = _tree("src/anchor/engine/debt.py")
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_the_package_names_no_debt_function_and_duplicates_no_debt_formula() -> None:
    debt_functions = _debt_functions()
    assert {"calculate_loan_amount", "calculate_financing_fee", "calculate_monthly_debt_service",
            "calculate_annual_debt_service", "calculate_remaining_loan_balance",
            "calculate_amortization_schedule"} <= debt_functions
    for path in _MODULES:
        code = _code(path)
        names = _identifiers(code)
        assert not names & debt_functions, path
        assert not {name for name in names if name.startswith("calculate_")}, path
        assert not names & {"expm1", "log1p", "pow", "isclose"}, path
        assert not [node for node in ast.walk(code) if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Pow, ast.Div))], path


def test_the_legacy_adapter_reads_only_the_enumerated_result_and_term_fields() -> None:
    adapt = _functions(_tree(_LEGACY))["adapt_legacy_acquisition_loan"]

    def read(owner: str) -> set[str]:
        return {
            node.attr for node in ast.walk(adapt)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == owner
        }

    assert read("results") == {"loan_amount", "financing_fee", "annual_debt_service", "remaining_loan_balance"}
    assert read("terms") == {"hold_period", "interest_rate", "amortization", "io_period"}
    forbidden = {"purchase_price", "ltv", "financing_fee_pct", "acquisition_cost_pct", "exit_cap_rate", "disposition_cost_pct"}
    assert not {node.attr for node in ast.walk(_code(_LEGACY)) if isinstance(node, ast.Attribute)} & forbidden


def test_the_claims_read_the_units_own_pre_debt_authority_only() -> None:
    claims = _functions(_tree(_LEGACY))["legacy_acquisition_loan_claims"]
    authority = {
        node.attr for node in ast.walk(claims)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "cash_authority"
    }
    assert authority == {"unit_id", "pre_acquisition_debt_cash_flows"}
    text = ast.unparse(claims)
    assert text.index("if cash_authority.unit_id != loan.scope.unit_id") < text.index("claims: list[ContractualClaim] = []")
    assert "cash_available=available if available > 0.0 else 0.0" in text


#: Every numeric operation in the package: the legacy loan's claim (debt service
#: plus the final balance), its modeled payoff month and hold-length indexing;
#: the D6 month-to-period convention; and one settlement subtraction. Nothing
#: else -- in particular no second subtraction of any acquisition-loan figure.
_PACKAGE_ARITHMETIC = {
    _INIT: set(),
    _CONTRACTS: set(),
    _VALIDATION: set(),
    _LEGACY: {
        "hold_period + 1",
        "MONTHS_PER_HOLD_YEAR * terms.hold_period",
        "year - 1",
        "due + loan.remaining_loan_balance",
    },
    _FOUNDATION: {
        "(model_month - 1) // MONTHS_PER_HOLD_YEAR + 1",
        "(model_month - 1) // MONTHS_PER_HOLD_YEAR",
        "model_month - 1",
        "due - available",
    },
}


@pytest.mark.parametrize("path", _MODULES)
def test_the_package_has_exactly_the_enumerated_arithmetic(path: str) -> None:
    assert _arithmetic(_code(path)) == _PACKAGE_ARITHMETIC[path]


def test_the_arithmetic_guard_would_see_a_recomputation_or_a_second_subtraction() -> None:
    allowed = set().union(*_PACKAGE_ARITHMETIC.values())
    for mutant in (
        "loan = terms.purchase_price * terms.ltv\n",
        "fee = results.loan_amount * terms.financing_fee_pct\n",
        "cash = tuple(cf - ds for cf, ds in zip(results.levered_cash_flows, results.annual_debt_service))\n",
        "t0 = results.levered_cash_flows[0] - results.financing_fee\n",
    ):
        assert _arithmetic(ast.parse(mutant)) - allowed, mutant


def test_the_timing_convention_is_d6s() -> None:
    assert "MONTHS_PER_HOLD_YEAR = 12" in _current(_CONTRACTS)
    function = ast.unparse(_functions(_tree(_FOUNDATION))["annual_period_of_model_month"])
    assert "if model_month == 0:\n        return 0" in function
    assert "return (model_month - 1) // MONTHS_PER_HOLD_YEAR + 1" in function


# =============================================================================
# 3. Neutrality and the handoff
# =============================================================================


def test_common_equity_neutrality_is_pinned_to_the_existing_levered_series() -> None:
    functions = _functions(_tree(_FOUNDATION))
    (unit_outcome,) = _call_nodes(functions["analyze_unit_capital_structure"], "common_equity_outcome")
    assert _keywords(unit_outcome)["residual_cash_flows"] == "authority.post_acquisition_debt_cash_flows"
    (investment_outcome,) = _call_nodes(functions["analyze_investment_capital_structure"], "common_equity_outcome")
    assert _keywords(investment_outcome)["residual_cash_flows"] == "investment_authority.cash_flows_after_unit_positions"

    (unit_authority,) = _call_nodes(functions["unit_cash_authority"], "UnitCashAuthority")
    assert _keywords(unit_authority) == {
        "unit_id": "unit_id",
        "pre_acquisition_debt_cash_flows": "results.unlevered_cash_flows",
        "post_acquisition_debt_cash_flows": "results.levered_cash_flows",
        "owner_cash_flow_after_acquisition_debt_by_year": "results.levered_owner_cash_flow_by_year",
        "net_sale_proceeds_after_acquisition_debt": "results.net_sale_proceeds",
    }
    (investment_authority,) = _call_nodes(functions["investment_scope_cash_authority"], "InvestmentScopeCashAuthority")
    assert _keywords(investment_authority) == {
        "unit_ids": "consolidated.unit_ids",
        "cash_flows_after_unit_positions": "consolidated.levered_cash_flows",
        "owner_cash_flow_after_unit_positions_by_year": "consolidated.levered_owner_cash_flow_by_year",
        "net_sale_proceeds_after_unit_positions": "consolidated.net_sale_proceeds",
    }
    outcomes = [_keywords(call)["common_equity_cash_flows"] for call in _call_nodes(functions["common_equity_outcome"], "CommonEquityOutcome")]
    assert sorted(outcomes) == ["None", "residual_cash_flows"]


def test_no_authority_reads_the_consolidated_unlevered_series() -> None:
    for path in _MODULES:
        for node in ast.walk(_code(path)):
            if isinstance(node, ast.Attribute) and "unlevered" in node.attr:
                assert node.attr == "unlevered_cash_flows", (path, ast.unparse(node))
                assert isinstance(node.value, ast.Name) and node.value.id == "results", (path, ast.unparse(node))
    consolidated_reads = {
        node.attr for node in ast.walk(_code(_FOUNDATION))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "consolidated"
    }
    assert consolidated_reads == {"unit_ids", "hold_period", "levered_cash_flows", "levered_owner_cash_flow_by_year", "net_sale_proceeds"}


# =============================================================================
# 4. No implicit cure
# =============================================================================


def test_a_funding_requirement_has_no_implicit_cure() -> None:
    assert [member.value for member in ShortfallResolution] == ["common_equity_contribution", "unresolved"]
    for node in ast.walk(_tree(_CONTRACTS)):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if "resolution" in node.target.id or "convention" in node.target.id:
                assert node.value is None, ast.unparse(node)
    for path in _MODULES:
        code = _code(path)
        for function in (node for node in ast.walk(code) if isinstance(node, ast.FunctionDef)):
            defaults = [*function.args.defaults, *(d for d in function.args.kw_defaults if d is not None)]
            assert not [d for d in defaults if "ShortfallResolution" in ast.unparse(d)], (path, function.name)

    def named(path: str) -> int:
        return sum(
            isinstance(node, ast.Attribute) and node.attr == "COMMON_EQUITY_CONTRIBUTION" for node in ast.walk(_code(path))
        )

    assert {path: named(path) for path in _MODULES} == {_INIT: 0, _CONTRACTS: 0, _VALIDATION: 0, _LEGACY: 1, _FOUNDATION: 1}
    settle = _functions(_tree(_FOUNDATION))["settle_claim"]
    assert named_in(settle) == 1
    text = ast.unparse(settle)
    assert "if resolution is ShortfallResolution.COMMON_EQUITY_CONTRIBUTION:" in text
    assert "elif resolution is ShortfallResolution.UNRESOLVED:" in text
    assert "else:\n        raise CapitalStructureError(" in text


def named_in(node: ast.AST) -> int:
    return sum(isinstance(child, ast.Attribute) and child.attr == "COMMON_EQUITY_CONTRIBUTION" for child in ast.walk(node))


def test_the_adapter_states_the_legacy_resolution_itself() -> None:
    (loan,) = _call_nodes(_functions(_tree(_LEGACY))["adapt_legacy_acquisition_loan"], "LegacyAcquisitionLoan")
    keywords = _keywords(loan)
    assert keywords["shortfall_resolution"] == "ShortfallResolution.COMMON_EQUITY_CONTRIBUTION"
    assert keywords["priority"] == "LEGACY_ACQUISITION_LOAN_PRIORITY"
    assert keywords["position_class"] == "PositionClass.SENIOR_DEBT"
    assert keywords["scope"] == "PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id)"


# =============================================================================
# 5. No later-gate economics or surface
# =============================================================================

_LATER_FUNCTIONS = re.compile(
    r"irr|moic|multiple|profit|dscr|debt_yield|attachment|detachment|last_dollar|coverage|accru|pik|redemption"
    r"|amortiz|debt_service|refinanc|recapitali|waterfall|partner|promote|valuat",
    re.IGNORECASE,
)
_LATER_IDENTIFIERS = re.compile(r"refinanc|recapitali|waterfall|partner|promote|hurdle|catch_up|(^|_)irr(_|$)|moic", re.IGNORECASE)


@pytest.mark.parametrize("path", _MODULES)
def test_no_position_return_accrual_refinancing_or_partnership_economics(path: str) -> None:
    code = _code(path)
    functions = {node.name for node in ast.walk(code) if isinstance(node, ast.FunctionDef)}
    assert not {name for name in functions if _LATER_FUNCTIONS.search(name)}, path
    assert not {name for name in _identifiers(code) if _LATER_IDENTIFIERS.search(name)}, path
    assert not set(_calls(code)) & {
        "evaluate_irr", "calculate_irr", "calculate_return_metrics", "calculate_equity_multiple",
        "calculate_project_return_totals", "calculate_dscr_by_year", "resolve_business_plan", "consolidate",
    }, path


def test_the_later_gate_guards_have_teeth() -> None:
    assert _LATER_FUNCTIONS.search("calculate_position_irr") and _LATER_FUNCTIONS.search("_accrue_preferred")
    assert _LATER_IDENTIFIERS.search("RefinanceEvent") and _LATER_IDENTIFIERS.search("position_irr")
    assert not _LATER_IDENTIFIERS.search("first_nonzero_index")


def test_no_persistence_schema_or_sql() -> None:
    assert store._SCHEMA_VERSION == 10
    for path in _MODULES:
        text = " ".join(_strings(_code(path)))
        assert not re.search(r"\b(CREATE|INSERT|SELECT|UPDATE|DELETE|ALTER|DROP)\b", text), path
        assert not {name for name in _imports(_tree(path)) if "sqlite" in name or "store" in name}, path


def test_no_route_serves_the_capital_structure() -> None:
    api = _current("src/anchor/api.py")
    assert "capital_structure" not in api and "capital-position" not in api and "capital-structure" not in api


def test_no_strategy_capital_structure_domain_is_wired() -> None:
    assert {domain.value for domain in StrategyDomain} == {
        "acquisition", "financing", "business_plan", "operating_outcome", "disposition",
    }


def test_the_p7_6_decision_matrix_is_untouched() -> None:
    assert _changes_between(
        _P7_7_BASE,
        _P7_7_MERGE,
        "src/anchor/decision",
        "src/anchor/deals/decision_matrix.py",
        "src/anchor/deals/investment_variants.py",
    ) == set()


def test_every_contract_is_a_frozen_slotted_keyword_only_dataclass() -> None:
    classes = [node for node in _tree(_CONTRACTS).body if isinstance(node, ast.ClassDef)]
    exempt = {"StrEnum", "ValueError", "RuntimeError"}
    checked = 0
    for node in classes:
        if {ast.unparse(base) for base in node.bases} & exempt:
            continue
        (decorator,) = node.decorator_list
        assert isinstance(decorator, ast.Call) and _callee(decorator) == "dataclass", node.name
        assert _keywords(decorator) == {"frozen": "True", "slots": "True", "kw_only": "True"}, node.name
        checked += 1
    assert checked >= 20
    for path in (_VALIDATION, _LEGACY, _FOUNDATION, _INIT):
        assert not [node for node in _tree(path).body if isinstance(node, ast.ClassDef)], path


@pytest.mark.parametrize("path", _MODULES)
def test_no_case_or_competition_identifier(path: str) -> None:
    import test_p7_0_decision_architecture as p7_0

    assert p7_0._case_identifiers_in(_current(path)) == []
