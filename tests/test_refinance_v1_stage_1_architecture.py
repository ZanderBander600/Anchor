"""Refinance & Capital Events V1 Stage 1 -- the architecture guard.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 10.2, 15, 19 and
20 (Stage 1). Every git query reads objects only (protocol 11.2). The guards
hold:

1. **the ledger**: Stage 1 changes exactly its declared production files since
   the accepted baseline ``2e1f84a``, and no Stage 2 or Stage 3 path -- API,
   persistence, codecs, fingerprints, memo, reporting, exports, frontend;
2. **the frozen upstream**, byte for byte: the P7.7 legacy adapter and
   foundation, the P7.8 debt, preferred, funding and metrics modules, every
   existing engine module, the valuation package and the P7.9 waterfall;
3. **each touched accepted module changed only at its declared seam**: the
   enum members appended, the dispatch prepended, the two refusals narrowed --
   every other definition identical to the baseline's;
4. **one payoff authority and one NOI authority**: exactly one amortization
   recurrence is called outside ``debt.py`` for an acquisition loan, and forward
   NOI is read only through P7.10's own function;
5. **the exact arithmetic** of every new module, so a second formula cannot
   appear unnoticed, and none in a contract module.

This is Stage 1's own guard, measured in the working tree while the stage is
unmerged. A later gate re-pins it to Stage 1's committed range, as the P7
guards were re-pinned here.

**Re-pinned at Stage 2.** Stage 2 (persistence and integration) is the gate
authorized to extend ``api.py`` and ``deals`` and to connect them to the
refinance contracts. The three claims about what *Stage 1* changed -- the
ledger, the untouched Stage 2 / Stage 3 paths, and that nothing upstream
imported the refinance layer -- now read Stage 1's committed range
``2e1f84a..6de7644`` and its merged tree, where each holds unchanged. Every
byte-freeze and seam claim below still reads the working tree, so Stage 1's
engine stays frozen through Stage 2; Stage 2's own guard is
``tests/test_refinance_v1_stage_2_architecture.py``.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when Stage 1 began: the ratified contract's merge (PR #56).
_BASE = "2e1f84aaa7c93b3247e8dbc6ded8b4397124d36b"
#: Stage 1's accepted merge (PR #57), the end of its committed range.
_STAGE_1_MERGE = "6de7644663c4f35c82296838e256ed06badb640d"

_CAPITAL = "src/anchor/capital_structure"
_ENGINE = "src/anchor/engine"

#: New modules.
_EVENTS = f"{_CAPITAL}/events.py"
_EVENT_VALIDATION = f"{_CAPITAL}/event_validation.py"
_REFINANCE = f"{_CAPITAL}/refinance.py"
_REFINANCE_CONTRACTS = f"{_CAPITAL}/refinance_contracts.py"
_REFINANCE_EXECUTION = f"{_CAPITAL}/refinance_execution.py"
_BALANCE_SERVICE = f"{_ENGINE}/acquisition_debt_balance.py"
_NEW = (_EVENTS, _EVENT_VALIDATION, _REFINANCE, _REFINANCE_CONTRACTS, _REFINANCE_EXECUTION, _BALANCE_SERVICE)

#: Accepted modules touched at a declared seam.
_CONTRACTS = f"{_CAPITAL}/contracts.py"
_VALIDATION = f"{_CAPITAL}/validation.py"
_EXEC_CONTRACTS = f"{_CAPITAL}/execution_contracts.py"
_EXEC_VALIDATION = f"{_CAPITAL}/execution_validation.py"
_EXECUTION = f"{_CAPITAL}/execution.py"
_COMMON_EQUITY = "src/anchor/partnership/common_equity.py"
_SEAM = (_CONTRACTS, _VALIDATION, _EXEC_CONTRACTS, _EXEC_VALIDATION, _EXECUTION, _COMMON_EQUITY)

#: Every production file Stage 1 changes, exactly (Section 20, Stage 1).
_STAGE_1_PRODUCTION_FILES = frozenset((*_NEW, *_SEAM))

#: Stage 2 and Stage 3 surfaces, and every upstream this stage consumes.
_PROTECTED = (
    "src/anchor/api.py",
    "src/anchor/deals",
    "src/anchor/memo",
    "src/anchor/reporting",
    "src/anchor/exports",
    "src/anchor/decision",
    "src/anchor/analysis",
    "src/anchor/consolidation",
    "src/anchor/valuation",
    "src/anchor/investment",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/asset_management",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "web",
)

#: Byte-frozen: the accepted modules this stage executes and never edits.
_FROZEN = (
    f"{_CAPITAL}/__init__.py",
    f"{_CAPITAL}/legacy.py",
    f"{_CAPITAL}/foundation.py",
    f"{_CAPITAL}/debt_position.py",
    f"{_CAPITAL}/preferred.py",
    f"{_CAPITAL}/funding.py",
    f"{_CAPITAL}/metrics.py",
    *(f"{_ENGINE}/{name}.py" for name in ("__init__", "debt", "acquisition", "noi", "returns", "contracts", "operating_projection")),
    *(
        f"src/anchor/partnership/{name}.py"
        for name in ("__init__", "contracts", "validation", "allocation", "accounts", "waterfall", "attribution", "metrics")
    ),
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and not path.endswith((".test.ts", ".test.tsx"))


def _changes_since(base: str, *paths: str) -> set[str]:
    """Committed, staged, unstaged and untracked changes since ``base``."""

    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path and "__pycache__" not in path}


def _changes_between(base: str, head: str, *paths: str) -> set[str]:
    """Committed changes in ``base..head`` only: a historical fact about a
    merged gate, which no later gate can disturb."""

    changed = _git("diff", "--name-only", "--no-renames", base, head, "--", *paths).split()
    return {path for path in changed if path and "__pycache__" not in path}


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _at_base(path: str) -> str:
    return _git("show", f"{_BASE}:{path}").replace("\r\n", "\n")


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


def _code(source: str) -> ast.Module:
    return _without_docstrings(ast.parse(source))


def _definitions(source: str) -> dict[str, str]:
    tree = _code(source)
    return {
        node.name: ast.unparse(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod, ast.MatMult)


def _is_text(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str))


def _arithmetic(tree: ast.AST) -> set[str]:
    return {
        ast.unparse(child)
        for child in ast.walk(tree)
        if (
            isinstance(child, (ast.BinOp, ast.AugAssign))
            and isinstance(child.op, _ARITHMETIC)
            and not (isinstance(child, ast.BinOp) and (_is_text(child.left) or _is_text(child.right)))
        )
        or (isinstance(child, ast.UnaryOp) and isinstance(child.op, (ast.USub, ast.UAdd)))
    }


# =============================================================================
# 1. The ledger
# =============================================================================


def test_stage_1_changes_exactly_its_declared_production_files() -> None:
    changed = {path for path in _changes_between(_BASE, _STAGE_1_MERGE, "src", "web") if _is_production(path)}
    assert changed == set(_STAGE_1_PRODUCTION_FILES), (
        f"unexpected: {sorted(changed - _STAGE_1_PRODUCTION_FILES)}; missing: {sorted(_STAGE_1_PRODUCTION_FILES - changed)}"
    )


def test_the_ledger_base_is_the_contract_ratification_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _BASE).split()[1:]
    assert parents == [_git("rev-parse", "0e9f8cc").strip(), _git("rev-parse", "017aa89").strip()]


def test_the_new_modules_are_new_at_this_stage() -> None:
    for path in _NEW:
        assert _git("ls-tree", "--name-only", _BASE, path).strip() == "", path


@pytest.mark.parametrize("path", _PROTECTED)
def test_no_stage_2_or_stage_3_path_and_no_upstream_changed(path: str) -> None:
    assert _changes_between(_BASE, _STAGE_1_MERGE, path) == set(), path


def test_the_committed_range_guard_has_teeth() -> None:
    """The committed-range reading sees Stage 1's own change, and Stage 2's
    ``deals`` work is not in it."""

    assert _changes_between(_BASE, _STAGE_1_MERGE, _REFINANCE) == {_REFINANCE}
    assert _changes_between(_BASE, _STAGE_1_MERGE, "src/anchor/deals") == set()


def test_the_ledger_guard_has_teeth() -> None:
    """The detector reports a difference that exists, and only that."""

    assert _changes_since(_BASE, _REFINANCE) == {_REFINANCE}
    assert _changes_since(_BASE, f"{_CAPITAL}/legacy.py") == set()


# =============================================================================
# 2. The frozen upstream
# =============================================================================


@pytest.mark.parametrize("path", _FROZEN)
def test_each_frozen_module_is_byte_identical_to_the_base(path: str) -> None:
    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_BASE}:{path}").strip(), path


def test_the_legacy_adapter_still_imports_no_debt_function() -> None:
    imports = _imports(ast.parse(_current(f"{_CAPITAL}/legacy.py")))
    assert not {module for module in imports if "debt" in module}


# =============================================================================
# 3. Each touched accepted module changed only at its declared seam
# =============================================================================

_SEAM_DEFINITIONS: dict[str, set[str]] = {
    # RefinanceProceeds is new; the three enums gain appended members.
    _CONTRACTS: {"RefinanceProceeds", "CapitalStructureIssueCode", "CapitalStructureStatus", "CommonEquityUnavailableReason"},
    # The rule accepted, the succession exception, the event validation called.
    _VALIDATION: {"_amount_rule_issues", "_duplicate_priorities", "validate_capital_structure"},
    # Appended members, and one widened annotation.
    _EXEC_CONTRACTS: {
        "ExecutionIssueCode", "PositionCashFlowKind", "PositionResultStatus", "PositionUnavailableReason", "ResolvedFundingEvent",
    },
    # The two narrowed refusals, the replacement predicate, the event-scope refusal.
    _EXEC_VALIDATION: {"_funding_issues", "_is_refinance_replacement", "_debt_issues", "validate_structured_execution"},
    # The dispatch prepended to both executors.
    _EXECUTION: {"execute_unit_capital_structure", "execute_investment_capital_structure"},
    # Exactly one more accepted upstream reason (R-O).
    _COMMON_EQUITY: {"common_equity_input"},
}


@pytest.mark.parametrize("path", _SEAM)
def test_each_seam_module_changed_only_its_declared_definitions(path: str) -> None:
    before = _definitions(_at_base(path))
    after = _definitions(_current(path))
    changed = {name for name in before.keys() & after.keys() if before[name] != after[name]}
    added = after.keys() - before.keys()
    assert before.keys() - after.keys() == set(), path
    assert changed | added == _SEAM_DEFINITIONS[path], path


@pytest.mark.parametrize(
    "enum_name",
    ["CapitalStructureIssueCode", "CapitalStructureStatus", "CommonEquityUnavailableReason"],
)
def test_each_contract_enum_only_appends(enum_name: str) -> None:
    def members(source: str) -> list[str]:
        (node,) = [n for n in _code(source).body if isinstance(n, ast.ClassDef) and n.name == enum_name]
        return [ast.unparse(item) for item in node.body if isinstance(item, ast.Assign)]

    before, after = members(_at_base(_CONTRACTS)), members(_current(_CONTRACTS))
    assert after[: len(before)] == before and len(after) > len(before)


@pytest.mark.parametrize(
    "enum_name", ["ExecutionIssueCode", "PositionCashFlowKind", "PositionResultStatus", "PositionUnavailableReason"]
)
def test_each_execution_enum_only_appends(enum_name: str) -> None:
    def members(source: str) -> list[str]:
        (node,) = [n for n in _code(source).body if isinstance(n, ast.ClassDef) and n.name == enum_name]
        return [ast.unparse(item) for item in node.body if isinstance(item, ast.Assign)]

    before, after = members(_at_base(_EXEC_CONTRACTS)), members(_current(_EXEC_CONTRACTS))
    assert after[: len(before)] == before and len(after) > len(before)


@pytest.mark.parametrize("name", ["execute_unit_capital_structure", "execute_investment_capital_structure"])
def test_the_executors_changed_only_by_a_prepended_dispatch(name: str) -> None:
    """Without the one leading ``if isinstance(capital_structure,
    CapitalStructureWithEvents)`` block, each executor is the baseline's,
    statement for statement: a structure without a refinance runs exactly the
    accepted path (Section 19)."""

    def body(source: str) -> list[ast.stmt]:
        (node,) = [n for n in _code(source).body if isinstance(n, ast.FunctionDef) and n.name == name]
        return node.body

    before, after = body(_at_base(_EXECUTION)), body(_current(_EXECUTION))
    dispatch = after[0]
    assert isinstance(dispatch, ast.If)
    assert ast.unparse(dispatch.test) == "isinstance(capital_structure, CapitalStructureWithEvents)"
    assert isinstance(dispatch.body[-1], ast.Return) and not dispatch.orelse
    assert [ast.unparse(stmt) for stmt in after[1:]] == [ast.unparse(stmt) for stmt in before]


def test_the_contract_seam_adds_no_arithmetic() -> None:
    for path in _SEAM:
        assert _arithmetic(_code(_current(path))) == _arithmetic(_code(_at_base(path))), path


# =============================================================================
# 4. One payoff authority, one NOI authority
# =============================================================================


def _files_calling(name: str) -> set[str]:
    found: set[str] = set()
    for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if called == name:
                    found.add(path.relative_to(_PROJECT_ROOT).as_posix())
    return found


def _files_calling_at_base(name: str) -> set[str]:
    found: set[str] = set()
    for path in _git("ls-tree", "-r", "--name-only", _BASE, "src/anchor").split():
        if not path.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(_at_base(path))):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if called == name:
                    found.add(path)
    return found


def test_the_amortization_recurrence_gains_exactly_one_caller_the_balance_service() -> None:
    """R-M: no second payoff implementation. ``debt.py`` owns the recurrence,
    and the accepted baseline's callers -- the P7.8 debt wrapper and the Excel
    audit's reconciliation -- reuse it. Stage 1 adds exactly one caller, the
    engine's balance service; no refinance, export or presentation module
    gains one, and none restates it (Section 5 below)."""

    before = _files_calling_at_base("calculate_amortization_schedule")
    assert before == {f"{_ENGINE}/debt.py", f"{_CAPITAL}/debt_position.py", "src/anchor/exports/excel/_workbook.py"}
    assert _files_calling("calculate_amortization_schedule") == before | {_BALANCE_SERVICE}


def test_no_refinance_module_reaches_the_debt_engine_directly() -> None:
    for path in (_REFINANCE, _REFINANCE_EXECUTION, _EVENT_VALIDATION, _EVENTS, _REFINANCE_CONTRACTS):
        imports = _imports(ast.parse(_current(path)))
        assert "..engine.debt" not in imports and "anchor.engine.debt" not in imports, path
    assert _imports(ast.parse(_current(_REFINANCE))) >= {"..engine.acquisition_debt_balance", ".debt_position"}


def test_the_balance_service_reuses_the_debt_functions_and_imports_nothing_else() -> None:
    assert _imports(ast.parse(_current(_BALANCE_SERVICE))) == {"__future__", "dataclasses", "..contracts", ".contracts", ".debt"}
    tree = ast.parse(_current(_BALANCE_SERVICE))
    (debt_import,) = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "debt"]
    assert {alias.name for alias in debt_import.names} == {
        "calculate_amortization_schedule",
        "calculate_debt_schedule",
        "calculate_io_months",
        "calculate_io_payment",
        "calculate_loan_amount",
        "calculate_monthly_payment",
        "calculate_monthly_rate",
        "calculate_scheduled_payment_count",
    }


def test_nothing_upstream_imports_the_refinance_layer() -> None:
    """Stage 1's claim, read at its merged tree: when Stage 1 merged, no upstream
    or later-stage layer imported the refinance layer. Stage 2 connects exactly
    the ``deals`` modules its own guard names."""

    for layer in ("engine", "valuation", "consolidation", "partnership", "deals", "decision", "memo", "reporting", "exports"):
        for path in _git("ls-tree", "-r", "--name-only", _STAGE_1_MERGE, f"src/anchor/{layer}").split():
            if not path.endswith(".py"):
                continue
            imports = _imports(ast.parse(_git("show", f"{_STAGE_1_MERGE}:{path}")))
            assert not {m for m in imports if "refinance" in m or m.endswith(".events") or "event_validation" in m}, path
    # Outside ``deals`` and ``api.py`` nothing imports it today either.
    for layer in ("engine", "valuation", "consolidation", "partnership", "decision", "memo", "reporting", "exports"):
        for source in (_PROJECT_ROOT / "src" / "anchor" / layer).rglob("*.py"):
            imports = _imports(ast.parse(source.read_text(encoding="utf-8")))
            assert not {m for m in imports if "refinance" in m or m.endswith(".events") or "event_validation" in m}, source


def test_forward_noi_has_one_definition_and_the_refinance_reads_it() -> None:
    """R-C: DSCR reads forward NOI only through P7.10's ``forward_noi_at``."""

    defining = {
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name == "forward_noi_at"
    }
    assert defining == {"src/anchor/valuation/engine.py"}
    assert _REFINANCE in _files_calling("forward_noi_at")


def test_the_refinance_reads_no_noi_series_except_the_consolidated_reconciliation() -> None:
    """The one direct NOI read in the refinance layer is the bit-for-bit
    reconciliation of the Investment's Unit sum to the consolidated NOI."""

    reads = [
        ast.unparse(node)
        for path in (_REFINANCE, _REFINANCE_EXECUTION)
        for node in ast.walk(_code(_current(path)))
        if isinstance(node, ast.Attribute) and node.attr == "noi_by_year"
    ]
    assert sorted(reads) == sorted(
        ["investment.consolidated.noi_by_year", "results.noi_by_year", "unit.results.noi_by_year", "consolidated.noi_by_year"]
    )
    refinance_reads = [
        ast.unparse(node) for node in ast.walk(_code(_current(_REFINANCE))) if isinstance(node, ast.Attribute) and node.attr == "noi_by_year"
    ]
    assert refinance_reads == ["investment.consolidated.noi_by_year"]


# =============================================================================
# 5. The exact arithmetic of every new module
# =============================================================================

_EXPECTED_ARITHMETIC: dict[str, set[str]] = {
    _EVENTS: set(),
    _REFINANCE_CONTRACTS: set(),
    _EVENT_VALIDATION: {"month % MONTHS_PER_HOLD_YEAR", "month + MINIMUM_REPLACEMENT_TERM_MONTHS"},
    _BALANCE_SERVICE: {
        "(model_month - 1) // MONTHS_PER_HOLD_YEAR",
        "(model_month - 1) // MONTHS_PER_HOLD_YEAR + 1",
        "-1",
        "MONTHS_PER_HOLD_YEAR * terms.hold_period",
        "event_year + 1",
        "io_months + n_payments",
        "min(model_month, loan_life) - 1",
        "model_month - 1",
        "year - 1",
    },
    _REFINANCE: {
        # Sizing (Section 9).
        "max_ltv * value",
        "max_ltv * value - senior_balance",
        "noi / min_dscr",
        "noi / min_dscr - senior_service",
        "service_capacity / per_dollar",
        "capacity.capacity - proceeds",
        "BINDING_TIE_RELATIVE_TOLERANCE * max(1.0, abs(proceeds))",
        # Achieved metrics and the DSCR proof (Section 9.3).
        "(proceeds + senior_balance) / scope_value",
        "proceeds + senior_balance",
        "noi / (senior_service + first_year)",
        "senior_service + first_year",
        "float(sizing.min_dscr.min_dscr) * (1.0 - ACHIEVED_DSCR_RELATIVE_TOLERANCE)",
        "1.0 - ACHIEVED_DSCR_RELATIVE_TOLERANCE",
        # The bridge (Section 11.1).
        "proceeds - payoff_total",
        "net - replacement_fees",
        "net - retiring_fees",
        "net - third_party",
        # Sums of stated amounts, and the Investment NOI reconciliation.
        "total + amount",
        "total + value",
        # The retired acquisition loan's provider series.
        "-loan.loan_amount",
        "-loan.loan_amount + loan.financing_fee.amount",
        "series[hold_year] + payoff",
        "series[hold_year] + payoff + fees",
        "loan.hold_period + 1",
        # The replacement's funding, and its schedule offset to the event month.
        "-principal",
        "terms.maturity_month - model_month",
        "hold_period - model_month // MONTHS_PER_HOLD_YEAR",
        "relative.scheduled_full_amortization_month + model_month",
        "relative.modeled_payoff_month + model_month",
        "item.model_month + model_month",
        # Months and hold years.
        "event_month(event) // MONTHS_PER_HOLD_YEAR",
        "model_month // MONTHS_PER_HOLD_YEAR",
        "MONTHS_PER_HOLD_YEAR * hold_period",
        "model_month + MONTHS_PER_HOLD_YEAR",
        "model_month + 1",
        "event_hold_year(event) + 1",
        "hold_year + 1",
        "PAYOFF_SEQUENCE + sequence",
        "year - 1",
    },
    _REFINANCE_EXECUTION: {
        # The legacy splice identity (INV-16).
        "unlevered[year] - results.annual_debt_service[year - 1]",
        "expected - results.remaining_loan_balance",
        "levered[year] - expected",
        "_SPLICE_TOLERANCE_ABSOLUTE + _SPLICE_TOLERANCE_RELATIVE * abs(levered[year])",
        "_SPLICE_TOLERANCE_RELATIVE * abs(levered[year])",
        # A retired loan's effect on the Investment residual, and its service.
        "investment_residual[year] + (source[year] - unit.results.levered_cash_flows[year])",
        "source[year] - unit.results.levered_cash_flows[year]",
        "total - unit.results.annual_debt_service[year - 1]",
        # Event cash joins the residual after settlement.
        "event_cash.get(event_hold_year(final_plan.event), 0.0) + final_plan.net_event_cash",
        "event_cash.get(year, 0.0) + investment_run.plan.net_event_cash",
        "events[year] + amount",
        "final[year] + amount",
        # Structural layers, as P7.8 states them.
        "attachment + view.funded_amount",
        "total + mine",
        # Months and years.
        "MONTHS_PER_HOLD_YEAR * hold_period",
        "MONTHS_PER_HOLD_YEAR * retired_at",
        "hold_period + 1",
        "hold_year + 1",
        "retired_in + 1",
        "year - 1",
    },
}


@pytest.mark.parametrize("path", _NEW)
def test_each_new_module_has_exactly_the_enumerated_arithmetic(path: str) -> None:
    assert _arithmetic(_code(_current(path))) == _EXPECTED_ARITHMETIC[path], path


def test_the_arithmetic_guard_would_see_a_second_amortization_recurrence() -> None:
    injected = _current(_REFINANCE) + "\n\ndef _balance(balance, rate, payment):\n    return balance - (payment - balance * rate)\n"
    assert _arithmetic(_code(injected)) != _EXPECTED_ARITHMETIC[_REFINANCE]
