"""Phase 7 Gate P7.4 -- the production ledger and the architecture guards for
the Strategy engine and Strategy persistence.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3 (P-1,
P-2, P-6, P-11, P-13), 7.4 (ST-2, ST-3, ST-4, ST-6), 7.5 and 15, and the P7.4
gate's own engine-scope approval. Every git query reads objects only; none
touches the index (protocol 11.2). The guards hold:

1. **the P7.4 production ledger** -- exactly five production files, and every
   financial, Scenario, AI, ingestion and web path unchanged since ``aa96155``;
2. **resolution order** -- Strategy, then the reused P7.1 Scenario resolver,
   then validation, then the existing D6 entry points;
3. **ST-6** -- no path from a Business Plan to an operating outcome;
4. **no formula** -- no arithmetic, no reflection, and each domain writes only
   the fields it owns;
5. **financial identity** -- one authority, never reached by metadata;
6. **additive persistence** -- appended tables, an unchanged migration body, and
   P7.2 functions changed exactly as enumerated;
7. **opt-in** -- one Investment writer, validation first; reads never write;
8. **the cache** -- only the variant service; never Lease-Level, never Base x Base;
9. **no later-gate concept**, no frontend change and no case identifier.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from anchor.analysis.strategy import STRATEGY_DOMAIN_FIELDS, StrategyDomain

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.4 began: the no-ff P7.3 merge.
_P7_4_BASE = "aa96155c4c097a1b7dad3f4c791178cb26b619a5"

_STRATEGY = "src/anchor/analysis/strategy.py"
_STORE = "src/anchor/deals/store.py"
_VARIANTS = "src/anchor/deals/variants.py"
_API = "src/anchor/api.py"
_CONTRACTS = "src/anchor/deals/contracts.py"

#: Every production file P7.4 changes, exactly:
#: - ``analysis/strategy.py`` (new): the Strategy contracts, validation and
#:   resolution, composed with the P7.1 Scenario resolver;
#: - ``deals/contracts.py``: the persisted-Strategy contract and its not-found
#:   error;
#: - ``deals/store.py``: schema v9, the eight typed tables, the Strategy
#:   lifecycle and the Strategy-variant cache;
#: - ``deals/variants.py``: variant inspection, fingerprints and analysis for
#:   every ``(strategy, scenario)`` pair;
#: - ``api.py``: the Strategy and variant routes P7.5 needs.
_P7_4_PRODUCTION_FILES = frozenset({_STRATEGY, _STORE, _VARIANTS, _API, _CONTRACTS})

#: Financial truth, Scenario semantics, the fingerprint functions, AI,
#: ingestion and the frontend: P7.4 consumes them and changes none.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/leasing",
    "src/anchor/business_plan",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/analysis/scenario.py",
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
    "src/anchor/deals/__init__.py",
    "web",
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
    return sorted(changed - _P7_4_PRODUCTION_FILES), sorted(_P7_4_PRODUCTION_FILES - changed)


# =============================================================================
# 1. The P7.4 production ledger
# =============================================================================


def test_p7_4_changed_exactly_its_authorized_production_files() -> None:
    """The P7.4 production ledger. The next gate must re-pin this to P7.4's
    committed range, ``aa96155..<the P7.4 merge>``, before adding its own
    scope. Never widen this set to admit another gate's files."""

    changed = {path for path in _changes_since(_P7_4_BASE, "src", "web") if _is_production(path)}
    assert _ledger_violations(changed) == ([], [])


def test_the_p7_4_ledger_base_is_the_p7_3_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_4_BASE).split()[1:]
    assert parents == [_git("rev-parse", ref).strip() for ref in ("c6ddde0", "39d2ee1")]


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_p7_3(path: str) -> None:
    assert _changes_since(_P7_4_BASE, path) == set(), f"{path} changed at P7.4"


def test_the_ledger_rejects_any_unexpected_production_change() -> None:
    assert _ledger_violations(set(_P7_4_PRODUCTION_FILES)) == ([], [])
    for intruder in (
        "src/anchor/engine/debt.py",
        "src/anchor/engine/returns.py",
        "src/anchor/engine/acquisition.py",
        "src/anchor/analysis/scenario.py",
        "src/anchor/deals/fingerprint.py",
        "src/anchor/ai/prompts.py",
        "web/src/App.tsx",
        "web/src/index.css",
        "web/src/components/ScenarioWorkspace.tsx",
    ):
        assert _ledger_violations({*_P7_4_PRODUCTION_FILES, intruder}) == ([intruder], [])
    assert _ledger_violations(set()) == ([], sorted(_P7_4_PRODUCTION_FILES))
    assert not _is_production("tests/test_p7_4_strategy_architecture.py")


# =============================================================================
# Source helpers
# =============================================================================


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _current(path: str) -> str:
    return _lf((_PROJECT_ROOT / path).read_bytes().decode("utf-8"))


def _baseline(path: str) -> str:
    return _lf(_git("show", f"{_P7_4_BASE}:{path}"))


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
    return [
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]


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


def _added_nodes(path: str) -> list[ast.stmt]:
    """The current file's top-level statements, docstrings removed, that are
    absent from ``aa96155`` -- for a new file, all of them."""

    current = _without_docstrings(ast.parse(_current(path))).body
    if path == _STRATEGY:
        return current
    baseline = {ast.dump(node) for node in _without_docstrings(ast.parse(_baseline(path))).body}
    return [node for node in current if ast.dump(node) not in baseline]


_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod, ast.MatMult)


def _arithmetic(node: ast.AST) -> list[str]:
    return [
        ast.unparse(child)
        for child in ast.walk(node)
        if (isinstance(child, (ast.BinOp, ast.AugAssign)) and isinstance(child.op, _ARITHMETIC))
        or (isinstance(child, ast.UnaryOp) and isinstance(child.op, ast.USub))
    ]


def _strategy_tree() -> ast.Module:
    return ast.parse(_current(_STRATEGY))


# =============================================================================
# 2. Resolution order -- Strategy, then the reused P7.1 resolver
# =============================================================================

_MODES = ("quick", "detailed", "lease_level")


@pytest.mark.parametrize("mode", _MODES)
def test_each_variant_resolves_the_strategy_first_then_hands_its_result_to_p7_1(mode: str) -> None:
    function = _functions(_strategy_tree())[f"resolve_{mode}_variant"]
    (strategy_call,) = _call_nodes(function, f"resolve_{mode}_strategy")
    (scenario_call,) = _call_nodes(function, f"resolve_{mode}_scenario")

    assert strategy_call.lineno < scenario_call.lineno
    arguments = [ast.unparse(a) for a in scenario_call.args] + [
        f"{k.arg}={ast.unparse(k.value)}" for k in scenario_call.keywords
    ]
    for argument in arguments:
        name, _, value = argument.rpartition("=")
        if name in {"unit_id", "scenario"}:
            continue
        assert value.startswith("chosen."), argument
    strategy_arguments = [ast.unparse(a) for a in strategy_call.args] + [
        ast.unparse(k.value) for k in strategy_call.keywords
    ]
    assert not any(argument.startswith(("chosen", "resolved")) for argument in strategy_arguments)


def test_the_p7_1_public_resolvers_are_called_once_each_and_only_by_the_variants() -> None:
    tree = _strategy_tree()
    for mode in _MODES:
        callers = sorted(
            name for name, function in _functions(tree).items() if f"resolve_{mode}_scenario" in _calls(function)
        )
        assert callers == [f"resolve_{mode}_variant"], mode
        assert _calls(tree).count(f"resolve_{mode}_scenario") == 1


def test_outcomes_are_applied_through_the_p7_1_target_resolvers_with_set() -> None:
    functions = _functions(_strategy_tree())
    for mode, resolver in (
        ("quick", "_resolve_quick_target"),
        ("detailed", "_resolve_detailed_target"),
        ("lease_level", "_resolve_lease_level_target"),
    ):
        users = sorted(name for name, function in functions.items() if resolver in _calls(function))
        assert users == [f"_{mode}_with_outcomes"], mode
    (override,) = _call_nodes(functions["_outcome_overrides"], "ScenarioOverride")
    keywords = {k.arg: ast.unparse(k.value) for k in override.keywords}
    assert keywords == {
        "unit_id": "unit_id",
        "target": "outcome.target",
        "operation": "ScenarioOperation.SET",
        "value": "float(outcome.value)",
    }


def test_no_scenario_operation_logic_or_registry_is_duplicated() -> None:
    source = _current(_STRATEGY)
    assert "_apply_operation" not in source
    assert "SCENARIO_TARGET_REGISTRY" not in source
    assert "ScenarioTargetSpec" not in source
    classes = {node.name for node in ast.walk(_strategy_tree()) if isinstance(node, ast.ClassDef)}
    assert classes == {
        "StrategyDomain", "AcquisitionChoice", "FinancingChoice", "OperatingOutcome", "OperatingOutcomeSet",
        "DispositionChoice", "StrategyOverlay", "StrategyDefinition", "StrategyIssueStage", "StrategyIssueCode",
        "StrategyIssue", "StrategyValidationError",
    }
    assert not {name for name in classes if name.startswith("Scenario")}
    matches = [ast.unparse(node.subject) for node in ast.walk(_strategy_tree()) if isinstance(node, ast.Match)]
    assert "operation" not in matches and "override.operation" not in matches


@pytest.mark.parametrize("mode", _MODES)
def test_each_analysis_wrapper_resolves_the_variant_then_calls_its_d6_entry_point(mode: str) -> None:
    wrapper = _functions(_strategy_tree())[f"analyze_{mode}_acquisition_with_strategy"]
    entry = f"analyze_{mode}_acquisition_with_business_plan"
    assert sorted(_calls(wrapper)) == sorted([f"resolve_{mode}_variant", entry])
    (call,) = _call_nodes(wrapper, entry)
    arguments = [ast.unparse(a) for a in call.args] + [ast.unparse(k.value) for k in call.keywords]
    assert all(argument.startswith("resolved.") for argument in arguments)


def test_the_strategy_module_imports_exactly_these_names() -> None:
    names: dict[str, set[str]] = {}
    for node in _strategy_tree().body:
        if isinstance(node, ast.ImportFrom):
            names.setdefault("." * node.level + (node.module or ""), set()).update(a.name for a in node.names)
        assert not isinstance(node, ast.Import), ast.unparse(node)
    assert names == {
        "__future__": {"annotations"},
        "collections.abc": {"Iterable", "Mapping"},
        "dataclasses": {"asdict", "dataclass", "replace"},
        "enum": {"StrEnum"},
        "math": {"isfinite"},
        "types": {"MappingProxyType"},
        "typing": {"TypeVar"},
        "..business_plan": {"BusinessPlan", "validate_business_plan"},
        "..contracts": {"AcquisitionInputs", "AcquisitionTerms", "DetailedOperatingInputs", "OperatingMode"},
        "..engine.contracts": {"AcquisitionResults", "DetailedAcquisitionResults"},
        "..leasing": {
            "Lease", "LeaseLevelOperatingInputs", "LeaseLevelPropertyInputs", "LeaseValidationIssue",
            "MarketLeasingAssumptions", "Suite", "validate_lease_level_inputs",
            "validate_lease_level_operating_inputs",
        },
        "..validation": {
            "InputValidationError", "validate_acquisition_inputs", "validate_acquisition_terms",
            "validate_detailed_operating_inputs",
        },
        ".business_plan_analysis": {
            "analyze_detailed_acquisition_with_business_plan",
            "analyze_lease_level_acquisition_with_business_plan",
            "analyze_quick_acquisition_with_business_plan",
        },
        ".contracts": {"LeaseLevelAcquisitionResults"},
        ".scenario": {
            "ResolvedDetailedInputs", "ResolvedLeaseLevelInputs", "ResolvedQuickInputs", "ScenarioDefinition",
            "ScenarioOperation", "ScenarioOverride", "ScenarioTarget", "_is_nonblank_text", "_require_instance",
            "_require_unit_identity", "_resolve_detailed_target", "_resolve_lease_level_target",
            "_resolve_quick_target", "_safe_repr", "resolve_detailed_scenario", "resolve_lease_level_scenario",
            "resolve_quick_scenario",
        },
    }


# =============================================================================
# 3. ST-6 -- no inferred causality from a Business Plan
# =============================================================================

#: What a plan item is made of. The Strategy engine never opens a plan.
_PLAN_ITEM_FIELDS = frozenset(
    {"capital_items", "owner_expense_items", "item_id", "month", "amount", "annual_amount", "first_year", "last_year"}
)
_OUTCOME_FUNCTIONS = ("_outcome_overrides", "_quick_with_outcomes", "_detailed_with_outcomes", "_lease_level_with_outcomes")


def test_the_strategy_engine_never_opens_or_resolves_a_business_plan() -> None:
    tree = _strategy_tree()
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes & _PLAN_ITEM_FIELDS
    assert not {c for c in _calls(tree) if c in {"resolve_business_plan", "CapitalPlanItem", "OwnerExpenseItem"}}


def test_the_outcome_path_never_sees_a_business_plan() -> None:
    functions = _functions(_strategy_tree())
    for name in _OUTCOME_FUNCTIONS:
        function = functions[name]
        parameters = [a.arg for a in (*function.args.args, *function.args.kwonlyargs)]
        assert "business_plan" not in parameters, name
        annotations = [ast.unparse(a.annotation) for a in function.args.args if a.annotation is not None]
        assert "BusinessPlan" not in annotations, name
        source = ast.unparse(function)
        assert "business_plan" not in source and "BusinessPlan" not in source, name


def test_only_a_business_plan_overlay_writes_the_plan_and_it_writes_its_own_content() -> None:
    functions = _functions(_strategy_tree())
    writers = {
        (name, ast.unparse(keyword.value))
        for name, function in functions.items()
        for call in _call_nodes(function, "replace")
        for keyword in call.keywords
        if keyword.arg == "business_plan"
    }
    assert writers == {
        ("_apply_quick_overlay", "content"),
        ("_apply_detailed_overlay", "content"),
        ("_apply_lease_level_overlay", "content"),
    }


def test_an_outcome_value_comes_only_from_the_analysts_outcome() -> None:
    """The only value an outcome resolves to is ``float(outcome.value)``: no
    other expression can reach a Scenario-registry field through the Strategy
    layer."""

    function = _functions(_strategy_tree())["_outcome_overrides"]
    reads = {ast.unparse(node) for node in ast.walk(function) if isinstance(node, ast.Attribute)}
    assert reads <= {"outcomes.outcomes", "outcome.target", "outcome.value", "ScenarioOperation.SET"}


# =============================================================================
# 4. No formula, no reflection; each domain writes only what it owns
# =============================================================================


def test_the_strategy_engine_has_no_arithmetic_and_no_numeric_builtins() -> None:
    tree = _strategy_tree()
    assert _arithmetic(tree) == []
    numeric = {"min", "max", "sum", "round", "abs", "pow", "divmod", "fsum", "prod"}
    assert not set(_calls(tree)) & numeric


def test_the_arithmetic_guard_detects_a_smuggled_value_creation_formula() -> None:
    mutant = _current(_STRATEGY) + (
        "\n\ndef _renovation_premium(plan, rent):\n"
        "    return rent + sum(item.amount for item in plan.capital_items) / 1_000_000\n"
    )
    tree = ast.parse(mutant)
    assert _arithmetic(tree)
    assert {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} & _PLAN_ITEM_FIELDS


def test_no_reflection_eval_or_path_patching_exists() -> None:
    tree = _strategy_tree()
    forbidden = {
        "getattr", "setattr", "delattr", "hasattr", "eval", "exec", "compile", "vars", "globals", "locals",
        "__import__", "import_module", "attrgetter", "itemgetter", "loads", "fields",
    }
    assert not set(_calls(tree)) & forbidden
    assert not {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} & {"__dict__", "__setattr__", "__slots__"}


@pytest.mark.parametrize(
    ("function", "domain"),
    [
        ("_with_acquisition", StrategyDomain.ACQUISITION),
        ("_with_financing", StrategyDomain.FINANCING),
        ("_with_disposition", StrategyDomain.DISPOSITION),
    ],
)
def test_each_whole_domain_writes_exactly_its_own_fields(function: str, domain: StrategyDomain) -> None:
    (call,) = _call_nodes(_functions(_strategy_tree())[function], "replace")
    assert tuple(keyword.arg for keyword in call.keywords) == STRATEGY_DOMAIN_FIELDS[domain]


def test_replace_is_called_only_by_the_domain_writers_and_the_overlay_dispatch() -> None:
    functions = _functions(_strategy_tree())
    users = {name for name, function in functions.items() if _call_nodes(function, "replace")}
    assert users == {
        "_with_acquisition", "_with_financing", "_with_disposition",
        "_apply_quick_overlay", "_apply_detailed_overlay", "_apply_lease_level_overlay",
    }
    for name in ("_apply_quick_overlay", "_apply_detailed_overlay", "_apply_lease_level_overlay"):
        for call in _call_nodes(functions[name], "replace"):
            assert {k.arg for k in call.keywords} <= {"inputs", "terms", "business_plan"}, ast.unparse(call)


def test_strategy_identity_and_naming_are_read_only_by_the_header_check() -> None:
    tree = _strategy_tree()
    owner = {node: name for name, function in _functions(tree).items() for node in ast.walk(function)}
    readers = {
        owner.get(node, "<module>")
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"strategy_id", "name", "description"}
    }
    assert readers == {"_header_issues"}


def test_the_strategy_engine_names_modes_as_data_and_never_dispatches_on_one() -> None:
    tree = _strategy_tree()
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "OperatingMode":
            parent = parents[node]
            as_whitelist_key = isinstance(parent, ast.Dict) and node in parent.keys
            as_constant_argument = isinstance(parent, ast.Call) and _callee(parent) == "_require_resolvable"
            assert as_whitelist_key or as_constant_argument, ast.unparse(parent)
        if isinstance(node, ast.Match):
            assert "mode" not in ast.unparse(node.subject), ast.unparse(node.subject)


# =============================================================================
# 5. Financial identity -- one authority, never reached by metadata (FP-1)
# =============================================================================

_P7_4_VARIANT_FUNCTIONS = (
    "_base_inputs", "resolve_variant_inputs", "_load_variant_recipe",
    "inspect_variant_inputs", "variant_fingerprint", "analyze_variant",
)


def test_every_p7_4_fingerprint_is_the_one_authority_on_the_resolved_contracts() -> None:
    functions = _functions(ast.parse(_current(_VARIANTS)))
    for name in ("inspect_variant_inputs", "variant_fingerprint", "analyze_variant"):
        (call,) = _call_nodes(functions[name], "fingerprint_resolved_inputs")
        assert [ast.unparse(a) for a in call.args] == ["resolved"] and not call.keywords, name
    for name in _P7_4_VARIANT_FUNCTIONS:
        direct = {"fingerprint_quick_inputs", "fingerprint_detailed_inputs", "fingerprint_lease_level_inputs"}
        assert not direct & set(_calls(functions[name])), name


def test_resolution_receives_contracts_and_definitions_never_names() -> None:
    function = _functions(ast.parse(_current(_VARIANTS)))["resolve_variant_inputs"]
    attributes = {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)}
    assert not attributes & {"name", "description", "strategy_id", "scenario_id", "created_at", "updated_at"}


def test_the_variant_service_does_no_arithmetic() -> None:
    assert _arithmetic(ast.parse(_current(_VARIANTS))) == []


# =============================================================================
# 6. Persistence is additive
# =============================================================================

_P7_4_DDL = {
    "_CREATE_STRATEGIES_TABLE_SQL": "strategies",
    "_CREATE_STRATEGY_ACQUISITION_OVERLAYS_TABLE_SQL": "strategy_acquisition_overlays",
    "_CREATE_STRATEGY_FINANCING_OVERLAYS_TABLE_SQL": "strategy_financing_overlays",
    "_CREATE_STRATEGY_BUSINESS_PLAN_OVERLAYS_TABLE_SQL": "strategy_business_plan_overlays",
    "_CREATE_STRATEGY_CAPITAL_PLAN_ITEMS_TABLE_SQL": "strategy_capital_plan_items",
    "_CREATE_STRATEGY_OWNER_EXPENSE_ITEMS_TABLE_SQL": "strategy_owner_expense_items",
    "_CREATE_STRATEGY_OPERATING_OUTCOMES_TABLE_SQL": "strategy_operating_outcomes",
    "_CREATE_STRATEGY_DISPOSITION_OVERLAYS_TABLE_SQL": "strategy_disposition_overlays",
}


def _create_constants(text: str) -> dict[str, str]:
    return {
        node.targets[0].id: node.value.value
        for node in ast.parse(text).body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("_CREATE_")
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def test_every_earlier_table_definition_is_unchanged_and_eight_are_appended() -> None:
    current, baseline = _create_constants(_current(_STORE)), _create_constants(_baseline(_STORE))
    assert {name: current[name] for name in baseline} == baseline
    assert set(current) - set(baseline) == set(_P7_4_DDL)
    for name, table in _P7_4_DDL.items():
        statement = " ".join(current[name].split())
        assert statement.startswith(f"CREATE TABLE IF NOT EXISTS {table} ("), name
        assert not re.search(r"\b(ALTER|DROP|INSERT|UPDATE|DELETE)\b", statement), name


def test_each_overlay_table_holds_exactly_its_domains_typed_columns() -> None:
    current = _create_constants(_current(_STORE))

    def columns(constant: str) -> list[str]:
        body = current[constant].split("(", 1)[1]
        return [line.split()[0] for line in body.splitlines() if line.strip() and not line.strip().startswith(("PRIMARY", ")"))]

    for constant, domain in (
        ("_CREATE_STRATEGY_ACQUISITION_OVERLAYS_TABLE_SQL", StrategyDomain.ACQUISITION),
        ("_CREATE_STRATEGY_FINANCING_OVERLAYS_TABLE_SQL", StrategyDomain.FINANCING),
        ("_CREATE_STRATEGY_DISPOSITION_OVERLAYS_TABLE_SQL", StrategyDomain.DISPOSITION),
    ):
        assert columns(constant) == ["strategy_id", "unit_id", *STRATEGY_DOMAIN_FIELDS[domain]], constant
        assert "PRIMARY KEY (strategy_id, unit_id)" in current[constant]
    assert columns("_CREATE_STRATEGY_BUSINESS_PLAN_OVERLAYS_TABLE_SQL") == ["strategy_id", "unit_id"]
    assert not re.search(r"\b(json|patch|payload|blob)\b", " ".join(current[c] for c in _P7_4_DDL), re.IGNORECASE)


def test_the_migration_body_is_unchanged_and_the_version_moves_by_one() -> None:
    current, baseline = ast.parse(_current(_STORE)), ast.parse(_baseline(_STORE))
    assert ast.dump(_functions(current)["_migrate"]) == ast.dump(_functions(baseline)["_migrate"])

    def version(tree: ast.Module) -> int:
        (value,) = [
            node.value.value for node in tree.body
            if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ["_SCHEMA_VERSION"]
            and isinstance(node.value, ast.Constant)
        ]
        return int(value)  # type: ignore[arg-type]

    assert (version(baseline), version(current)) == (8, 9)


def test_connect_only_appends_the_eight_table_creations() -> None:
    def executes(text: str) -> list[str]:
        return [
            ast.unparse(node.args[0])
            for node in ast.walk(_functions(ast.parse(text))["_connect"])
            if isinstance(node, ast.Call) and _callee(node) == "execute"
        ]

    assert executes(_current(_STORE)) == executes(_baseline(_STORE)) + list(_P7_4_DDL)


#: The functions P7.4 adds to ``store.py``.
_P7_4_STORE_FUNCTIONS = frozenset(
    {
        "_require_owned_strategy", "_require_valid_strategy", "_write_strategy_business_plan",
        "_write_strategy_overlays", "_delete_strategy_overlay_rows", "_strategy_rows", "_rows_by_unit",
        "_stored_outcome_order", "_strategy_business_plan_from_rows", "_strategy_from_rows",
        "_read_strategies", "_insert_strategy", "_delete_strategy_rows", "create_strategy_for_deal",
        "create_strategy", "update_strategy", "delete_strategy", "list_strategies", "get_strategy",
        "list_deal_strategies", "_require_variant_scenario", "get_strategy_variant_snapshot",
        "put_strategy_variant_snapshot",
    }
)


def test_p7_4_added_exactly_the_enumerated_store_functions_and_changed_four() -> None:
    """``_connect`` appends the table creations; ``_wrapper_holds_no_structure``
    and ``_delete_investment_rows`` learn about Strategies;
    ``_materialize_hidden_investment`` changes its docstring only. Every other
    function, ``delete_deal`` and every P7.2 Scenario function included, is
    ``aa96155``'s exactly."""

    current = _functions(ast.parse(_current(_STORE)))
    baseline = _functions(ast.parse(_baseline(_STORE)))
    assert set(current) - set(baseline) == _P7_4_STORE_FUNCTIONS
    assert set(baseline) <= set(current)
    changed = sorted(name for name in baseline if ast.dump(current[name]) != ast.dump(baseline[name]))
    assert changed == ["_connect", "_delete_investment_rows", "_materialize_hidden_investment", "_wrapper_holds_no_structure"]

    def body(function: ast.FunctionDef) -> str:
        return ast.dump(_without_docstrings(ast.Module(body=[function], type_ignores=[])))

    assert body(current["_materialize_hidden_investment"]) == body(baseline["_materialize_hidden_investment"])


def test_the_wrapper_collapses_only_when_it_holds_neither_scenarios_nor_strategies() -> None:
    function = _functions(ast.parse(_current(_STORE)))["_wrapper_holds_no_structure"]
    selects = sorted(re.findall(r"SELECT 1 FROM (\w+) WHERE investment_id", " ".join(_strings(function))))
    assert selects == ["scenarios", "strategies"]


def test_deleting_an_investment_deletes_its_strategy_structure_and_never_a_deal() -> None:
    function = _functions(ast.parse(_current(_STORE)))["_delete_investment_rows"]
    text = ast.unparse(function)
    assert "_STRATEGY_OVERLAY_TABLES" in text and "DELETE FROM strategies WHERE investment_id" in text
    for deal_table in ("deals", "detailed_deals", "lease_level_deals", "deal_capital_plan_items"):
        assert not re.search(rf"DELETE FROM {deal_table}\b", text), deal_table


def test_no_new_code_alters_or_drops_a_table() -> None:
    assert _current(_STORE).count("ALTER TABLE") == _baseline(_STORE).count("ALTER TABLE")
    functions = _functions(ast.parse(_current(_STORE)))
    for name in _P7_4_STORE_FUNCTIONS:
        for text in _strings(functions[name]):
            assert not re.search(r"\b(ALTER|DROP)\b", text), name
    for path in (_STRATEGY, _VARIANTS, _API):
        assert not re.search(r"\b(ALTER TABLE|DROP TABLE)\b", _current(path)), path


def test_the_new_store_code_does_no_arithmetic_and_validates_with_the_p7_4_validator() -> None:
    functions = _functions(ast.parse(_current(_STORE)))
    assert {name: _arithmetic(functions[name]) for name in _P7_4_STORE_FUNCTIONS if _arithmetic(functions[name])} == {}
    validators = sorted(name for name in functions if "validate_strategy" in _calls(functions[name]))
    assert validators == ["_require_valid_strategy", "_strategy_from_rows"]
    assert "_business_plan_from_rows" in _calls(functions["_strategy_business_plan_from_rows"])


# =============================================================================
# 7. Opt-in only (Q4) -- one writer, validation first; reads never write
# =============================================================================

_WRITES = re.compile(r"\b(INSERT|UPDATE|DELETE)\b")
_P7_4_READ_FUNCTIONS = (
    "get_strategy", "list_strategies", "list_deal_strategies", "get_strategy_variant_snapshot",
    "_read_strategies", "_strategy_from_rows", "_strategy_rows", "_rows_by_unit",
    "_strategy_business_plan_from_rows", "_require_owned_strategy", "_require_variant_scenario",
)
_WRITE_HELPERS = frozenset(
    {
        "_materialize_hidden_investment", "_insert_strategy", "_write_strategy_overlays",
        "_write_strategy_business_plan", "_touch_investment", "_delete_strategy_rows",
        "_delete_strategy_overlay_rows", "_delete_investment_rows", "_insert_scenario",
        "_delete_scenario_rows", "_remove_hidden_wrapper_of_deal",
    }
)


def test_one_function_writes_an_investment_and_both_first_opt_ins_validate_before_it() -> None:
    functions = _functions(ast.parse(_current(_STORE)))
    writers = sorted(
        name for name, function in functions.items()
        if any(re.search(r"INSERT INTO (investments|investment_units)\b", text) for text in _strings(function))
    )
    assert writers == ["_materialize_hidden_investment"]
    callers = sorted(name for name, function in functions.items() if "_materialize_hidden_investment" in _calls(function))
    assert callers == ["create_scenario_for_deal", "create_strategy_for_deal"]

    create = functions["create_strategy_for_deal"]
    order = [
        name for _, name in sorted(
            (node.lineno, _callee(node)) for node in ast.walk(create)
            if isinstance(node, ast.Call)
            and _callee(node) in {"_require_valid_strategy", "_materialize_hidden_investment", "_insert_strategy"}
        )
    ]
    assert order == ["_require_valid_strategy", "_materialize_hidden_investment", "_insert_strategy"]


def test_every_p7_4_read_path_is_free_of_writes() -> None:
    functions = _functions(ast.parse(_current(_STORE)))
    for name in _P7_4_READ_FUNCTIONS:
        assert [t for t in _strings(functions[name]) if _WRITES.search(t)] == [], name
        assert not set(_calls(functions[name])) & _WRITE_HELPERS, name


def _route_functions(method: str) -> dict[str, ast.FunctionDef]:
    routes: dict[str, ast.FunctionDef] = {}
    for node in ast.parse(_current(_API)).body:
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == method and ast.unparse(decorator.func.value) == "app"
                    and isinstance(decorator.args[0], ast.Constant)
                ):
                    routes[str(decorator.args[0].value)] = node
    return routes


def test_p7_4_adds_exactly_these_routes() -> None:
    added = sorted(
        (method, path)
        for method in ("get", "post", "put", "delete")
        for path in _route_functions(method)
        if "/strategies" in path or "/variants/" in path
    )
    assert added == [
        ("delete", "/investments/{investment_id}/strategies/{strategy_id}"),
        ("get", "/deals/{deal_id}/strategies"),
        ("get", "/investments/{investment_id}/strategies"),
        ("get", "/investments/{investment_id}/strategies/{strategy_id}"),
        ("get", "/investments/{investment_id}/variants/{strategy_id}/{scenario_id}/fingerprint"),
        ("get", "/investments/{investment_id}/variants/{strategy_id}/{scenario_id}/inputs"),
        ("post", "/deals/{deal_id}/strategies"),
        ("post", "/investments/{investment_id}/strategies"),
        ("post", "/investments/{investment_id}/variants/{strategy_id}/{scenario_id}/analysis"),
        ("put", "/investments/{investment_id}/strategies/{strategy_id}"),
    ]


def test_every_p7_4_get_route_calls_only_read_functions() -> None:
    reads = {"list_deal_strategies", "list_strategies", "get_strategy", "inspect_variant_inputs", "variant_fingerprint"}
    backend = reads | {
        "create_strategy_for_deal", "create_strategy", "update_strategy", "delete_strategy", "analyze_variant",
        "put_strategy_variant_snapshot", "put_variant_snapshot",
    }
    for path, function in _route_functions("get").items():
        if "/strategies" in path or "/variants/" in path:
            used = {call for call in _calls(function) if call in backend}
            assert used and used <= reads, (path, used)


def test_api_py_changed_only_by_additions() -> None:
    current = _without_docstrings(ast.parse(_current(_API))).body
    baseline = _without_docstrings(ast.parse(_baseline(_API))).body
    current_dumps = {ast.dump(node) for node in current}
    removed = [node for node in baseline if ast.dump(node) not in current_dumps]
    assert all(isinstance(node, ast.ImportFrom) for node in removed)
    for old in removed:
        assert isinstance(old, ast.ImportFrom)
        (new,) = [n for n in current if isinstance(n, ast.ImportFrom) and n.module == old.module and n.level == old.level]
        assert {a.name for a in old.names} <= {a.name for a in new.names}, old.module
    added_code = ast.Module(body=_added_nodes(_API), type_ignores=[])
    assert _arithmetic(added_code) == []


# =============================================================================
# 8. The cache -- only the variant service; never Lease-Level, never Base x Base
# =============================================================================


def test_only_the_variant_service_reads_or_writes_the_strategy_cache() -> None:
    users = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        if path.as_posix() != (_PROJECT_ROOT / _STORE).as_posix()
        and {"get_strategy_variant_snapshot", "put_strategy_variant_snapshot"}
        & set(_calls(ast.parse(path.read_text(encoding="utf-8"))))
    )
    assert users == [_VARIANTS]


def test_the_lease_level_arm_and_base_by_base_never_touch_the_cache() -> None:
    function = _functions(ast.parse(_current(_VARIANTS)))["analyze_variant"]
    (branch,) = [
        node for node in ast.walk(function)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "recipe.strategy is None"
    ]
    assert _calls(ast.Module(body=branch.body, type_ignores=[])) == ["_analyze_resolved"]
    (match,) = [node for node in ast.walk(function) if isinstance(node, ast.Match)]
    arms = {ast.unparse(case.pattern): case for case in match.cases}
    assert set(arms) == {"OperatingMode.QUICK | OperatingMode.DETAILED", "OperatingMode.LEASE_LEVEL", "_"}
    assert _calls(ast.Module(body=arms["OperatingMode.LEASE_LEVEL"].body, type_ignores=[])) == ["_analyze_resolved"]
    cached = _calls(ast.Module(body=arms["OperatingMode.QUICK | OperatingMode.DETAILED"].body, type_ignores=[]))
    assert {"get_strategy_variant_snapshot", "put_strategy_variant_snapshot"} <= set(cached)


def test_the_store_names_no_lease_level_result_contract() -> None:
    for name in ("LeaseLevelAcquisitionResults", "MonthlyPropertyProjection", "AnnualOperatingProjection"):
        assert name not in _current(_STORE)


# =============================================================================
# 9. No later-gate concept, no frontend, no case identifier
# =============================================================================

_LATER_GATE_VOCABULARY = re.compile(
    r"consolidat|waterfall|partner|capital_position|capital_event|capital_structure|tranche|promote"
    r"|unit_selection|refinanc|recapitali|mezzanine|preferred_equity",
    re.IGNORECASE,
)


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
    return found


@pytest.mark.parametrize("path", sorted(_P7_4_PRODUCTION_FILES))
def test_p7_4_code_names_no_later_gate_concept(path: str) -> None:
    code = ast.Module(body=_added_nodes(path), type_ignores=[])
    assert {name for name in _identifiers(code) if _LATER_GATE_VOCABULARY.search(name)} == set()
    tables = {
        match.group(1)
        for text in _strings(code)
        for match in re.finditer(r"\b(?:CREATE TABLE IF NOT EXISTS|INSERT INTO|FROM)\s+(\w+)", text)
    }
    assert not {table for table in tables if _LATER_GATE_VOCABULARY.search(table)}


def test_no_later_gate_domain_is_a_member() -> None:
    assert {domain.value for domain in StrategyDomain} == {
        "acquisition", "financing", "business_plan", "operating_outcome", "disposition",
    }


def test_the_later_gate_guard_detects_a_unit_selection_domain() -> None:
    tree = ast.parse("class UnitSelectionOverlay:\n    pass\n\ndef _apply_unit_selection(units):\n    return units\n")
    assert {n for n in _identifiers(tree) if _LATER_GATE_VOCABULARY.search(n)} == {"_apply_unit_selection"}


def test_no_frontend_file_changed() -> None:
    assert _changes_since(_P7_4_BASE, "web") == set()


@pytest.mark.parametrize("path", sorted(_P7_4_PRODUCTION_FILES))
def test_no_case_or_competition_identifier(path: str) -> None:
    import test_p7_0_decision_architecture as p7_0

    assert p7_0._case_identifiers_in(_current(path)) == []
