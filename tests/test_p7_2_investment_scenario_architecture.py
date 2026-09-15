"""Phase 7 Gate P7.2 -- the production ledger and the architecture guards for
the Investment shell and Scenario persistence.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 7.5,
15.1-15.5 and the Section 21 record (Q3, Q4, Q14, Q15) govern. P7.2 persists
the P7.1 Scenario layer around the unchanged engine; it is not a Strategy,
consolidation, capital-structure, UI or AI gate.

1. **The P7.2 production ledger** -- established before any production edit.
   Exactly four production files change, and every financial, AI and web path
   stays byte-identical to ``58f862d``.
2. **The schema is additive.** Every legacy table definition and the migration
   body are exactly ``58f862d``'s; five new ``CREATE TABLE IF NOT EXISTS``
   tables are appended, and nothing ALTERs or DROPs anything.
3. **Opt-in only.** One function writes an Investment, and only the first
   Scenario of a Deal reaches it; every read path and every GET route is free
   of writes.
4. **The P7.1 authority is reused, never duplicated.** Resolution is the P7.1
   resolvers; validation is the P7.1 validator; no P7.2 file defines a scenario
   contract, names a target member or does arithmetic.
5. **Financial identity excludes display metadata.** The one fingerprint
   authority receives only the resolved contracts.
6. **Lease-Level is never cached**, and only the variant service touches the
   cache.
7. **No Strategy, consolidation, capital structure or partnership**, and no
   case identifiers.

Every git query reads objects only; none touches the index (protocol 11.2).
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from anchor.analysis.scenario import (
    ResolvedDetailedInputs,
    ResolvedLeaseLevelInputs,
    ResolvedQuickInputs,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.2 began: the P7.1 merge.
_P7_2_BASE = "58f862ddd8e96173d6732dc371ebda01c1a8c395"

#: Every production file P7.2 changes, exactly:
#: - ``deals/contracts.py``: the Investment, membership and persisted-Scenario
#:   contracts;
#: - ``deals/store.py``: schema v8, the five additive tables, the lifecycle and
#:   the fingerprint-guarded variant cache;
#: - ``deals/variants.py`` (new): the one resolved-input fingerprint authority
#:   and the variant analysis service over the P7.1 resolvers and the D6 entry
#:   points;
#: - ``api.py``: the routes P7.3 needs.
_P7_2_PRODUCTION_FILES = frozenset(
    {
        "src/anchor/api.py",
        "src/anchor/deals/contracts.py",
        "src/anchor/deals/store.py",
        "src/anchor/deals/variants.py",
    }
)

#: Financial truth, AI and the frontend: P7.2 carries them and changes none.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/leasing",
    "src/anchor/analysis",
    "src/anchor/business_plan",
    "src/anchor/ai",
    "src/anchor/ingestion",
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
    """Committed, staged, unstaged and untracked changes since ``base``."""

    tracked = _git("diff", "--name-only", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _production_changes_since(base: str) -> set[str]:
    return {path for path in _changes_since(base, "src", "web") if _is_production(path)}


def _ledger_violations(changed: set[str]) -> tuple[list[str], list[str]]:
    return sorted(changed - _P7_2_PRODUCTION_FILES), sorted(_P7_2_PRODUCTION_FILES - changed)


# =============================================================================
# 1. The P7.2 production ledger
# =============================================================================


#: ``main`` after P7.2 -- the no-ff merge of
#: ``feature/p7-2-investment-scenario-persistence``, and the end of P7.2's
#: committed range.
_P7_2_MERGE = "c6ddde074cbd7fd4f3f4cf10e29d4f44eed6cf83"


def _changes_between(start: str, end: str, *paths: str) -> set[str]:
    """Files that differ between two commits. Reads Git only; it never touches
    the index (protocol 11.2)."""

    return {path for path in _git("diff", "--name-only", start, end, "--", *paths).split() if path}


def test_p7_2_changed_exactly_its_authorized_production_files() -> None:
    """The P7.2 production ledger.

    Pinned at P7.3 to P7.2's own committed range, ``58f862d..c6ddde0``, so it
    keeps proving exactly what P7.2 changed however later gates move the tree.
    That is the P7.1 / D6 ledger precedent. P7.3's own ledger is
    ``tests/test_p7_3_scenario_ui_architecture.py``. Never widen this set to
    admit another gate's files."""

    changed = {
        path
        for path in _changes_between(_P7_2_BASE, _P7_2_MERGE, "src", "web")
        if _is_production(path)
    }
    assert _ledger_violations(changed) == ([], [])


def test_the_p7_2_ledger_base_is_the_p7_1_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_2_BASE).split()[1:]
    assert parents == [_git("rev-parse", ref).strip() for ref in ("f234e4c", "5aa7bd6")]


def test_the_p7_2_ledger_end_is_the_p7_2_merge() -> None:
    """``c6ddde0`` is the P7.2 merge: its first parent is the P7.1 merge this
    ledger starts from, and its second is the reviewed P7.2 head."""

    parents = _git("rev-list", "--parents", "-n", "1", _P7_2_MERGE).split()[1:]
    assert parents == [_git("rev-parse", ref).strip() for ref in (_P7_2_BASE, "8e589c8")]


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_p7_1(path: str) -> None:
    """Within P7.2's own committed range. What later gates may change is their
    own ledgers' business."""

    assert _changes_between(_P7_2_BASE, _P7_2_MERGE, path) == set(), f"{path} changed at P7.2"


def test_the_ledger_rejects_any_unexpected_production_change() -> None:
    assert _ledger_violations(set(_P7_2_PRODUCTION_FILES)) == ([], [])
    for intruder in (
        "src/anchor/engine/debt.py",
        "src/anchor/engine/returns.py",
        "src/anchor/engine/acquisition.py",
        "src/anchor/analysis/scenario.py",
        "src/anchor/deals/fingerprint.py",
        "src/anchor/ai/prompts.py",
        "web/src/App.tsx",
    ):
        assert _ledger_violations({*_P7_2_PRODUCTION_FILES, intruder}) == ([intruder], [])
    assert _ledger_violations(set()) == ([], sorted(_P7_2_PRODUCTION_FILES))
    assert not _is_production("web/src/businessPlan.test.ts")
    assert not _is_production("tests/test_p7_2_investment_scenario_architecture.py")


# =============================================================================
# Source helpers
# =============================================================================

_STORE = "src/anchor/deals/store.py"
_VARIANTS = "src/anchor/deals/variants.py"
_API = "src/anchor/api.py"
_CONTRACTS = "src/anchor/deals/contracts.py"


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _current(path: str) -> str:
    return _lf((_PROJECT_ROOT / path).read_bytes().decode("utf-8"))


def _baseline(path: str) -> str:
    return _lf(_git("show", f"{_P7_2_BASE}:{path}"))


def _merged(path: str) -> str:
    """``path`` as P7.2 left it, at the P7.2 merge.

    Re-pinned at P7.4: the guards that describe what P7.2 *added* read P7.2's
    own committed code rather than the moving tree, exactly as its ledger does.
    P7.4 extends the same store, variant service, contracts and API, and its own
    guards pin those additions (``tests/test_p7_4_strategy_architecture.py``).
    Every guard that states a standing rule -- read paths free of writes, one
    fingerprint authority, no arithmetic, Lease-Level never cached -- still
    reads the current tree."""

    return _lf(_git("show", f"{_P7_2_MERGE}:{path}"))


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


def _strings(node: ast.AST) -> list[str]:
    return [
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]


def _module_constants(tree: ast.Module) -> dict[str, str]:
    return {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def _without_docstrings(tree: ast.Module) -> ast.Module:
    """``tree`` with every docstring removed, so a guard reads code only."""

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


#: The functions P7.2 adds to ``store.py``.
_P7_2_STORE_FUNCTIONS = frozenset(
    {
        "_decode_hidden_flag", "_investment_row", "_unit_rows", "_investment_of_deal",
        "_require_hidden_wrapper", "_require_owned_scenario", "_require_valid_scenario",
        "_stored_token", "_override_order", "_scenario_from_rows", "_read_scenarios",
        "_write_scenario_overrides", "_touch_investment", "_insert_scenario",
        "_materialize_hidden_investment", "_delete_scenario_rows", "_delete_investment_rows",
        "_wrapper_holds_no_structure", "_remove_hidden_wrapper_of_deal",
        "create_scenario_for_deal", "create_scenario", "update_scenario", "delete_scenario",
        "delete_investment", "get_investment", "list_scenarios", "get_scenario",
        "list_deal_scenarios", "get_variant_snapshot", "put_variant_snapshot",
    }
)


def test_p7_2_added_exactly_the_enumerated_store_functions() -> None:
    """Two pre-existing store functions change, each by exactly one kind of
    statement: ``_connect`` appends the five table creations (held by
    ``test_connect_only_appends_the_five_table_creations``) and ``delete_deal``
    gains one call, proven below. Every other baseline function is ``58f862d``'s
    AST exactly."""

    current = _functions(ast.parse(_merged(_STORE)))
    baseline = _functions(ast.parse(_baseline(_STORE)))
    assert set(current) - set(baseline) == _P7_2_STORE_FUNCTIONS
    assert set(baseline) <= set(current)
    changed = sorted(
        name for name in baseline if ast.dump(current[name]) != ast.dump(baseline[name])
    )
    assert changed == ["_connect", "delete_deal"]

    def without_wrapper_removal(function: ast.FunctionDef) -> str:
        clone = ast.parse(ast.unparse(function)).body[0]
        for node in ast.walk(clone):
            if isinstance(node, ast.With):
                node.body = [
                    statement for statement in node.body
                    if not (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Call)
                        and _callee(statement.value) == "_remove_hidden_wrapper_of_deal"
                    )
                ]
        return ast.dump(clone)

    assert without_wrapper_removal(current["delete_deal"]) == without_wrapper_removal(
        baseline["delete_deal"]
    )


# =============================================================================
# 2. The schema is additive
# =============================================================================

_P7_2_DDL = {
    "_CREATE_INVESTMENTS_TABLE_SQL": "investments",
    "_CREATE_INVESTMENT_UNITS_TABLE_SQL": "investment_units",
    "_CREATE_SCENARIOS_TABLE_SQL": "scenarios",
    "_CREATE_SCENARIO_OVERRIDES_TABLE_SQL": "scenario_overrides",
    "_CREATE_VARIANT_SNAPSHOTS_TABLE_SQL": "variant_snapshots",
}


def test_every_legacy_table_definition_is_unchanged_and_five_are_appended() -> None:
    current = {k: v for k, v in _module_constants(ast.parse(_merged(_STORE))).items() if k.startswith("_CREATE_")}
    baseline = {k: v for k, v in _module_constants(ast.parse(_baseline(_STORE))).items() if k.startswith("_CREATE_")}

    assert {name: current[name] for name in baseline} == baseline
    assert set(current) - set(baseline) == set(_P7_2_DDL)
    for name, table in _P7_2_DDL.items():
        statement = " ".join(current[name].split())
        assert statement.startswith(f"CREATE TABLE IF NOT EXISTS {table} ("), name
        assert not re.search(r"\b(ALTER|DROP|INSERT|UPDATE|DELETE)\b", statement), name


def test_the_migration_body_is_unchanged_and_the_version_moves_by_one() -> None:
    current, baseline = ast.parse(_merged(_STORE)), ast.parse(_baseline(_STORE))
    assert ast.dump(_functions(current)["_migrate"]) == ast.dump(_functions(baseline)["_migrate"])

    def version(tree: ast.Module) -> int:
        (value,) = [
            node.value.value for node in tree.body
            if isinstance(node, ast.Assign)
            and [ast.unparse(t) for t in node.targets] == ["_SCHEMA_VERSION"]
            and isinstance(node.value, ast.Constant)
        ]
        return int(value)  # type: ignore[arg-type]

    assert (version(baseline), version(current)) == (7, 8)


def test_connect_only_appends_the_five_table_creations() -> None:
    def executes(tree: ast.Module) -> list[str]:
        return [
            ast.unparse(node.args[0])
            for node in ast.walk(_functions(tree)["_connect"])
            if isinstance(node, ast.Call) and _callee(node) == "execute"
        ]

    current, baseline = executes(ast.parse(_merged(_STORE))), executes(ast.parse(_baseline(_STORE)))
    assert current == baseline + list(_P7_2_DDL)


def test_no_new_code_alters_or_drops_a_table() -> None:
    assert _current(_STORE).count("ALTER TABLE") == _baseline(_STORE).count("ALTER TABLE")
    tree = ast.parse(_current(_STORE))
    for name in _P7_2_STORE_FUNCTIONS:
        for text in _strings(_functions(tree)[name]):
            assert not re.search(r"\b(ALTER|DROP)\b", text), name
    for path in (_VARIANTS, _API):
        assert not re.search(r"\b(ALTER TABLE|DROP TABLE)\b", _current(path)), path


# =============================================================================
# 3. Opt-in only (Q4)
# =============================================================================

_WRITES = re.compile(r"\b(INSERT|UPDATE|DELETE)\b")


def _writes_of(function: ast.FunctionDef) -> list[str]:
    return [text for text in _strings(function) if _WRITES.search(text)]


def test_one_function_writes_an_investment_and_only_the_first_scenario_reaches_it() -> None:
    """P7.2's own code, at the P7.2 merge. P7.4 adds the Deal's first Strategy
    as the one other caller, validated first in the same way
    (``tests/test_p7_4_strategy_architecture.py``)."""

    tree = ast.parse(_merged(_STORE))
    functions = _functions(tree)
    writers = sorted(
        name for name, function in functions.items()
        if any(re.search(r"INSERT INTO (investments|investment_units)\b", text) for text in _strings(function))
    )
    assert writers == ["_materialize_hidden_investment"]
    callers = sorted(name for name, function in functions.items() if "_materialize_hidden_investment" in _calls(function))
    assert callers == ["create_scenario_for_deal"]

    create = functions["create_scenario_for_deal"]
    order = [
        name
        for _, name in sorted(
            (node.lineno, _callee(node))
            for node in ast.walk(create)
            if isinstance(node, ast.Call)
            and _callee(node) in {"_require_valid_scenario", "_materialize_hidden_investment", "_insert_scenario"}
        )
    ]
    assert order == ["_require_valid_scenario", "_materialize_hidden_investment", "_insert_scenario"]


_READ_FUNCTIONS = (
    "get_investment", "list_scenarios", "get_scenario", "list_deal_scenarios",
    "get_variant_snapshot", "_read_scenarios", "_scenario_from_rows", "_investment_of_deal",
    "_require_hidden_wrapper", "_unit_rows", "_investment_row",
)
_WRITE_HELPERS = frozenset(
    {
        "_materialize_hidden_investment", "_insert_scenario", "_write_scenario_overrides",
        "_touch_investment", "_delete_scenario_rows", "_delete_investment_rows",
        "_remove_hidden_wrapper_of_deal",
    }
)


def test_every_read_path_is_free_of_writes() -> None:
    functions = _functions(ast.parse(_current(_STORE)))
    for name in _READ_FUNCTIONS:
        assert _writes_of(functions[name]) == [], name
        assert not set(_calls(functions[name])) & _WRITE_HELPERS, name


def _route_functions(tree: ast.Module, method: str) -> dict[str, ast.FunctionDef]:
    routes: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == method
                    and ast.unparse(decorator.func.value) == "app"
                ):
                    routes[str(ast.literal_eval(decorator.args[0]))] = node
    return routes


def test_every_p7_2_get_route_calls_only_read_functions() -> None:
    routes = _route_functions(ast.parse(_merged(_API)), "get")
    p7_2 = {path: function for path, function in routes.items() if "/scenarios" in path or path.startswith("/investments")}
    assert sorted(p7_2) == [
        "/deals/{deal_id}/scenarios",
        "/investments/{investment_id}",
        "/investments/{investment_id}/scenarios",
        "/investments/{investment_id}/scenarios/{scenario_id}",
        "/investments/{investment_id}/scenarios/{scenario_id}/fingerprint",
    ]
    reads = {"list_deal_scenarios", "get_investment", "list_scenarios", "get_scenario", "scenario_variant_fingerprint"}
    for path, function in p7_2.items():
        backend = {call for call in _calls(function) if call in reads | {
            "create_scenario_for_deal", "create_scenario", "update_scenario", "delete_scenario",
            "delete_investment", "analyze_scenario_variant", "put_variant_snapshot",
        }}
        assert backend and backend <= reads, (path, backend)


def test_the_fingerprint_service_never_writes() -> None:
    functions = _functions(ast.parse(_current(_VARIANTS)))
    for name in ("scenario_variant_fingerprint", "_load_variant_source", "resolve_scenario_inputs", "fingerprint_resolved_inputs"):
        assert "put_variant_snapshot" not in _calls(functions[name]), name


# =============================================================================
# 4. The P7.1 authority is reused, never duplicated
# =============================================================================

_P7_2_FILES = (_STORE, _VARIANTS, _API, _CONTRACTS)
_SCENARIO_CONTRACT_NAMES = {
    "ScenarioDefinition", "ScenarioOverride", "ScenarioOperation", "ScenarioTarget",
    "ScenarioTargetSpec", "ScenarioIssue", "ScenarioValidationError",
}


@pytest.mark.parametrize("path", _P7_2_FILES)
def test_no_p7_2_file_defines_a_scenario_contract_or_names_a_target_member(path: str) -> None:
    tree = ast.parse(_current(path))
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert not classes & _SCENARIO_CONTRACT_NAMES
    members = [
        ast.unparse(node) for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"ScenarioTarget", "ScenarioOperation"}
    ]
    assert members == []
    assert "SCENARIO_TARGET_REGISTRY" not in _without_the_p7_3_catalog(_current(path))
    assert "_apply_operation" not in _current(path)


def _without_the_p7_3_catalog(text: str) -> str:
    """The file minus the read-only target catalogs and the one name they
    import.

    P7.3 was authorized to add ``GET /scenario-targets`` to ``api.py``: it
    projects the registry for the Scenario editor, so the UI holds no target
    list of its own. P7.5 was authorized, the same way, to add
    ``GET /strategy-targets``, which projects the Strategy whitelist with the
    registry's units. ``tests/test_p7_3_scenario_ui_architecture.py`` and
    ``tests/test_p7_5_decision_architecture.py`` prove they are the only code
    that names the registry, and that they compute and store nothing.
    Everything else in every P7.2 file still never names the registry."""

    # Every segment is read off the original text before any is removed: a
    # removal shifts the offsets of every later function.
    segments = [
        ast.get_source_segment(text, node)
        for node in ast.parse(text).body
        if isinstance(node, ast.FunctionDef) and node.name in {"scenario_target_catalog", "strategy_target_catalog"}
    ]
    for segment in segments:
        assert segment is not None
        text = text.replace(segment, "")
    return re.sub(r"^\s*SCENARIO_TARGET_REGISTRY,\r?\n", "", text, count=1, flags=re.MULTILINE)


def test_resolution_is_the_p7_1_resolvers_and_validation_the_p7_1_validator() -> None:
    variants_calls = _calls(ast.parse(_current(_VARIANTS)))
    for resolver in ("resolve_quick_scenario", "resolve_detailed_scenario", "resolve_lease_level_scenario"):
        assert variants_calls.count(resolver) == 1, resolver
    assert "validate_scenario" not in variants_calls
    assert not {c for c in variants_calls if c.startswith(("validate_acquisition", "validate_lease", "validate_detailed"))}

    # Re-pinned at P7.6 to the P7.2 merge: P7.6 routes the same validator
    # through ``_scenario_contract_issues`` (the hidden wrapper's one Unit, or a
    # visible Investment's member set), pinned by
    # ``tests/test_p7_6_consolidation_architecture.py``.
    store_functions = _functions(ast.parse(_merged(_STORE)))
    validators = sorted(
        name for name in _P7_2_STORE_FUNCTIONS if "validate_scenario" in _calls(store_functions[name])
    )
    assert validators == ["_require_valid_scenario", "_scenario_from_rows"]


_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod, ast.MatMult)


def _arithmetic(node: ast.AST) -> list[str]:
    return [
        ast.unparse(child) for child in ast.walk(node)
        if (isinstance(child, (ast.BinOp, ast.AugAssign)) and isinstance(child.op, _ARITHMETIC))
        or (isinstance(child, ast.UnaryOp) and isinstance(child.op, ast.USub))
    ]


def test_the_variant_service_and_the_new_store_code_do_no_arithmetic() -> None:
    assert _arithmetic(ast.parse(_current(_VARIANTS))) == []
    functions = _functions(ast.parse(_current(_STORE)))
    # String concatenation of one error message is the only ``+``; it sits in
    # the error class, not in a P7.2 function.
    assert {name: _arithmetic(functions[name]) for name in _P7_2_STORE_FUNCTIONS if _arithmetic(functions[name])} == {}


def test_the_variant_service_imports_exactly_these_names() -> None:
    names: dict[str, set[str]] = {}
    for node in ast.parse(_merged(_VARIANTS)).body:
        if isinstance(node, ast.ImportFrom):
            names.setdefault("." * node.level + (node.module or ""), set()).update(a.name for a in node.names)
    assert names == {
        "__future__": {"annotations"},
        "dataclasses": {"dataclass"},
        "enum": {"StrEnum"},
        "pathlib": {"Path"},
        "..analysis.business_plan_analysis": {
            "analyze_detailed_acquisition_with_business_plan",
            "analyze_lease_level_acquisition_with_business_plan",
            "analyze_quick_acquisition_with_business_plan",
        },
        "..analysis.contracts": {"LeaseLevelAcquisitionResults"},
        "..analysis.scenario": {
            "ResolvedDetailedInputs", "ResolvedLeaseLevelInputs", "ResolvedQuickInputs",
            "ScenarioDefinition", "resolve_detailed_scenario", "resolve_lease_level_scenario",
            "resolve_quick_scenario",
        },
        "..contracts": {"OperatingMode", "UnsupportedOperatingModeError"},
        "..engine.contracts": {"AcquisitionResults", "DetailedAcquisitionResults"},
        ".": {"store"},
        ".contracts": {"Deal"},
        ".fingerprint": {
            "fingerprint_detailed_inputs", "fingerprint_lease_level_inputs", "fingerprint_quick_inputs",
        },
    }


# =============================================================================
# 5. Financial identity excludes display metadata (FP-1, Q15)
# =============================================================================

_RESOLVED_FIELDS = {
    field
    for contract in (ResolvedQuickInputs, ResolvedDetailedInputs, ResolvedLeaseLevelInputs)
    for field in contract.__dataclass_fields__
}


def test_the_one_fingerprint_authority_reads_only_the_resolved_contracts() -> None:
    function = _functions(ast.parse(_current(_VARIANTS)))["fingerprint_resolved_inputs"]
    assert [a.arg for a in function.args.args] == ["resolved"]
    assert not function.args.kwonlyargs and not function.args.vararg and not function.args.kwarg
    attributes = {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)}
    assert attributes - {"__qualname__"} <= _RESOLVED_FIELDS
    assert not attributes & {"name", "description", "scenario_id", "id", "investment_id", "created_at", "updated_at"}
    assert set(_calls(function)) == {
        "fingerprint_quick_inputs", "fingerprint_detailed_inputs", "fingerprint_lease_level_inputs",
        "ResolvedQuickInputs", "ResolvedDetailedInputs", "ResolvedLeaseLevelInputs",
        "TypeError", "type",
    } - {"ResolvedQuickInputs", "ResolvedDetailedInputs", "ResolvedLeaseLevelInputs"}


def test_every_variant_fingerprint_is_computed_by_the_one_authority_from_resolved_inputs() -> None:
    functions = _functions(ast.parse(_current(_VARIANTS)))
    for name in ("scenario_variant_fingerprint", "analyze_scenario_variant"):
        (call,) = [
            node for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and _callee(node) == "fingerprint_resolved_inputs"
        ]
        assert [ast.unparse(a) for a in call.args] == ["resolved"] and not call.keywords, name
    direct = sorted(
        name for name, function in functions.items() if name != "fingerprint_resolved_inputs"
        and {"fingerprint_quick_inputs", "fingerprint_detailed_inputs", "fingerprint_lease_level_inputs"} & set(_calls(function))
    )
    assert direct == []


# =============================================================================
# 6. Lease-Level is never cached; only the variant service touches the cache
# =============================================================================


def test_the_lease_level_arm_never_touches_the_cache() -> None:
    function = _functions(ast.parse(_current(_VARIANTS)))["analyze_scenario_variant"]
    (match,) = [node for node in ast.walk(function) if isinstance(node, ast.Match)]
    arms = {ast.unparse(case.pattern): case for case in match.cases}
    assert set(arms) == {"OperatingMode.QUICK | OperatingMode.DETAILED", "OperatingMode.LEASE_LEVEL", "_"}
    lease_level = arms["OperatingMode.LEASE_LEVEL"]
    assert _calls(ast.Module(body=lease_level.body, type_ignores=[])) == ["_analyze_resolved"]
    cached = _calls(ast.Module(body=arms["OperatingMode.QUICK | OperatingMode.DETAILED"].body, type_ignores=[]))
    assert {"get_variant_snapshot", "put_variant_snapshot"} <= set(cached)


def test_only_the_variant_service_reads_or_writes_the_cache() -> None:
    users = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        if path.as_posix() != (_PROJECT_ROOT / _STORE).as_posix()
        and {"get_variant_snapshot", "put_variant_snapshot"} & set(_calls(ast.parse(path.read_text(encoding="utf-8"))))
    )
    assert users == [_VARIANTS]


def test_the_store_names_no_lease_level_result_contract() -> None:
    source = _current(_STORE)
    for name in ("LeaseLevelAcquisitionResults", "MonthlyPropertyProjection", "AnnualOperatingProjection"):
        assert name not in source


# =============================================================================
# 7. No Strategy, consolidation, capital structure or partnership; no case names
# =============================================================================

_LATER_GATE_VOCABULARY = re.compile(
    r"strateg|consolidat|waterfall|partner|capital_position|capital_event|tranche|promote",
    re.IGNORECASE,
)
#: The one Strategy-dimension key the variant cache carries, as ratified in
#: Section 7.5: the reserved Base token and its column. No Strategy entity.
_PERMITTED_STRATEGY_IDENTIFIERS = {"_BASE_STRATEGY_ID", "strategy_id"}


def _identifiers(tree: ast.Module) -> set[str]:
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


def _added_code(path: str) -> ast.Module:
    """The current file's code, docstrings removed. For files P7.2 extends,
    only definitions absent from ``58f862d`` are kept."""

    current = _without_docstrings(ast.parse(_merged(path)))
    if path == _VARIANTS:
        return current
    baseline = {ast.dump(node) for node in _without_docstrings(ast.parse(_baseline(path))).body}
    return ast.Module(body=[node for node in current.body if ast.dump(node) not in baseline], type_ignores=[])


@pytest.mark.parametrize("path", _P7_2_FILES)
def test_p7_2_code_names_no_later_gate_concept(path: str) -> None:
    code = _added_code(path)
    identifiers = {name for name in _identifiers(code) if _LATER_GATE_VOCABULARY.search(name)}
    assert identifiers <= _PERMITTED_STRATEGY_IDENTIFIERS
    tables = {
        match.group(1)
        for text in _strings(code)
        for match in re.finditer(r"\b(?:CREATE TABLE IF NOT EXISTS|INSERT INTO|FROM)\s+(\w+)", text)
    }
    assert not {table for table in tables if _LATER_GATE_VOCABULARY.search(table)}


def test_the_later_gate_guard_detects_a_strategy_entity() -> None:
    tree = ast.parse("class StrategyOverlay:\n    pass\n\ndef consolidate_units(units):\n    return units\n")
    assert {n for n in _identifiers(tree) if _LATER_GATE_VOCABULARY.search(n)} == {
        "StrategyOverlay", "consolidate_units",
    }


@pytest.mark.parametrize("path", _P7_2_FILES)
def test_no_case_or_competition_identifier(path: str) -> None:
    import test_p7_0_decision_architecture as p7_0

    assert p7_0._case_identifiers_in(_current(path)) == []
