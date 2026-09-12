"""Phase 6 Gate D6.5 -- architecture guardrails for Business Plan persistence,
fingerprints and the API.

1. **API omission guard.** Every plan-aware call ``api.py`` makes passes
   ``business_plan=business_plan`` by name, and that name is bound only by
   ``_optional_business_plan(payload)`` in the same function and ``case`` arm --
   so the D6.4 ``BusinessPlan()`` compatibility defaults are never relied on, no
   plan is substituted, dropped or ``None``, and no plan-free engine entry point
   is imported. Mutant self-tests prove each rule bites.
2. **Store omission guard.** Every fingerprint, row builder and create call in
   ``deals/store.py`` receives the deal's plan explicitly; row builders require
   it; every write validates, and every replacement deletes before it writes;
   delete removes the plan rows. Mutant self-tests again.
3. **Fingerprint inclusion guard -- behavioural.** The real fingerprint module,
   and mutants of it loaded the same way, are checked by what they compute:
   every mode's empty-plan digest equals the pinned legacy digest, every field
   of every item moves it, and row order never does.
4. **D6.3 typing.** ``_coerce_snapshot_value`` is byte-identical to 93636ee.
5. **Scope.** D6.5 changed exactly its authorized production files; engine,
   leasing, analysis, AI, the resolver, the validator and the web are untouched.

Every git query runs against a private copy of the index (protocol 11.2).
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import os
import shutil
import subprocess
import tempfile
import types
from enum import Enum
from pathlib import Path

import pytest

from anchor.business_plan import BusinessPlan, CapitalPlanItem, OwnerExpenseItem

from _d6_5_fixtures import (  # type: ignore[import-not-found]
    MATERIAL,
    MODES,
    PRE_D6_5_DIGESTS,
    edit_item,
    fingerprint_with,
    reversed_plan,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_API = "src/anchor/api.py"
_STORE = "src/anchor/deals/store.py"
_FINGERPRINT = "src/anchor/deals/fingerprint.py"
#: ``main`` after D6.4, immediately before D6.5.
_D6_4_MERGE = "93636ee"


def _git_bytes(arguments: list[str]) -> bytes:
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
            cwd=_PROJECT_ROOT,
            env={**os.environ, "GIT_INDEX_FILE": str(private_index)},
        )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return completed.stdout


def _files_changed_since(commit: str, repo_relative: str) -> list[str]:
    tracked = _git_bytes(["diff", "--name-only", commit, "--", repo_relative]).decode()
    untracked = _git_bytes(
        ["ls-files", "--others", "--exclude-standard", "--", repo_relative]
    ).decode()
    return sorted(
        {line.strip() for line in (*tracked.splitlines(), *untracked.splitlines()) if line.strip()}
    )


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _current(path: str) -> str:
    return _lf((_PROJECT_ROOT / path).read_bytes().decode("utf-8"))


def _at(commit: str, path: str) -> str:
    return _lf(_git_bytes(["show", f"{commit}:{path}"]).decode("utf-8"))


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_empty_plan(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and _callee(node) == "BusinessPlan"
        and not node.args
        and not node.keywords
    )


def _top_level_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _mutate(source: str, old: str, new: str, *, label: str) -> str:
    assert old in source, f"{label}: the mutation site no longer exists"
    mutated = source.replace(old, new, 1)
    ast.parse(mutated)  # a real, parseable mutant -- not a syntax error
    return mutated


# =============================================================================
# 1. The API omission guard
# =============================================================================

_PLAN_READER = "_optional_business_plan"

#: Plan-aware functions ``api.py`` calls. Each takes ``business_plan``.
_API_PLAN_TAKERS = frozenset(
    {
        "analyze_quick_acquisition_with_business_plan",
        "analyze_detailed_acquisition_with_business_plan",
        "analyze_lease_level_acquisition_with_business_plan",
        "run_one_way_sensitivity",
        "run_two_way_sensitivity",
        "run_detailed_one_way_sensitivity",
        "run_detailed_two_way_sensitivity",
        "run_lease_level_one_way_sensitivity",
        "run_lease_level_two_way_sensitivity",
        "build_standard_presets",
        "build_standard_detailed_presets",
        "build_standard_break_even_analysis",
        "build_standard_detailed_break_even_analysis",
        "generate_ai_analysis",
        "generate_detailed_ai_analysis",
        "fingerprint_quick_inputs",
        "fingerprint_detailed_inputs",
        "fingerprint_lease_level_inputs",
        "create_deal",
        "create_detailed_deal",
        "create_lease_level_deal",
        "update_deal",
        "update_detailed_deal",
        "update_lease_level_deal",
    }
)
_STORE_NAMES = frozenset(
    {
        "create_deal",
        "create_detailed_deal",
        "create_lease_level_deal",
        "update_deal",
        "update_detailed_deal",
        "update_lease_level_deal",
    }
)

#: Engine entry points that cannot carry a plan -- the API must use none.
_PLANLESS_ENTRY_POINTS = frozenset(
    {
        "analyze_acquisition",
        "analyze_detailed_acquisition",
        "analyze_detailed_acquisition_with_projection",
        "analyze_lease_level_acquisition_with_projection",
        "analyze_acquisition_from_operating_projection",
    }
)

#: Every plan-aware call the API makes, by ``(route helper, callee)``.
_API_PLAN_CALLS = sorted(
    [
        ("_analyze_detailed", "analyze_detailed_acquisition_with_business_plan"),
        ("_analyze_quick", "analyze_quick_acquisition_with_business_plan"),
        ("_analyze_lease_level", "analyze_lease_level_acquisition_with_business_plan"),
        ("_sensitivity_detailed", "run_detailed_two_way_sensitivity"),
        ("_sensitivity_quick", "run_two_way_sensitivity"),
        ("_sensitivity_lease_level", "run_lease_level_two_way_sensitivity"),
        ("_one_way_quick", "run_one_way_sensitivity"),
        ("_one_way_detailed", "run_detailed_one_way_sensitivity"),
        ("_one_way_lease_level", "run_lease_level_one_way_sensitivity"),
        ("_sensitivity_presets_detailed", "build_standard_detailed_presets"),
        ("_sensitivity_presets_quick", "build_standard_presets"),
        ("_break_even_detailed", "build_standard_detailed_break_even_analysis"),
        ("_break_even_quick", "build_standard_break_even_analysis"),
        ("_ai_analysis_detailed", "generate_detailed_ai_analysis"),
        ("_ai_analysis_quick", "generate_ai_analysis"),
        ("_ai_analysis_lease_level", "analyze_lease_level_acquisition_with_business_plan"),
        ("create_deal", "create_deal"),
        ("create_deal", "create_detailed_deal"),
        ("create_deal", "create_lease_level_deal"),
        ("update_deal", "update_deal"),
        ("update_deal", "update_detailed_deal"),
        ("update_deal", "update_lease_level_deal"),
        ("deal_fingerprint", "fingerprint_quick_inputs"),
        ("deal_fingerprint", "fingerprint_detailed_inputs"),
        ("deal_fingerprint", "fingerprint_lease_level_inputs"),
    ]
)


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    return {
        id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }


def _scope(node: ast.AST, parents: dict[int, ast.AST], function: ast.FunctionDef) -> ast.AST:
    """The ``case`` arm ``node`` sits in, or the function itself."""

    current = node
    while id(current) in parents and current is not function:
        current = parents[id(current)]
        if isinstance(current, ast.match_case):
            return current
    return function


def _binds_business_plan(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.Assign):
        targets: list[ast.AST] = list(node.targets)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr, ast.For, ast.comprehension)):
        targets = [node.target]
    elif isinstance(node, ast.With):
        targets = [item.optional_vars for item in node.items if item.optional_vars]
    else:
        return []
    return [
        target
        for target in targets
        if any(isinstance(name, ast.Name) and name.id == "business_plan" for name in ast.walk(target))
    ]


def _is_plan_read(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "business_plan"
        and isinstance(node.value, ast.Call)
        and _callee(node.value) == _PLAN_READER
        and [ast.unparse(argument) for argument in node.value.args] == ["payload"]
        and not node.value.keywords
    )


def _api_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    parents = _parents(tree)
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _PLANLESS_ENTRY_POINTS:
                    violations.append(f"api imports {alias.name}, which cannot carry a plan")
        elif isinstance(node, ast.Call):
            name = _callee(node)
            if name == "BusinessPlan":
                violations.append(f"api constructs a BusinessPlan (line {node.lineno})")
            if name in _PLANLESS_ENTRY_POINTS:
                violations.append(f"api calls {name}, which cannot carry a plan")
            for keyword in node.keywords:
                if keyword.arg == "business_plan" and not (
                    isinstance(keyword.value, ast.Name) and keyword.value.id == "business_plan"
                ):
                    violations.append(
                        f"api passes business_plan={ast.unparse(keyword.value)} to {name}"
                    )

    for function in _top_level_functions(tree).values():
        where = f"api.{function.name}"
        nodes = [node for statement in function.body for node in ast.walk(statement)]
        reads = [node for node in nodes if _is_plan_read(node)]
        for node in nodes:
            if _binds_business_plan(node) and not _is_plan_read(node):
                violations.append(f"{where} binds business_plan other than from {_PLAN_READER}(payload)")
        for node in nodes:
            if not (isinstance(node, ast.Call) and _callee(node) in _API_PLAN_TAKERS):
                continue
            name = _callee(node)
            if "business_plan" not in {keyword.arg for keyword in node.keywords}:
                violations.append(f"{where} calls {name} without business_plan=")
            scope = _scope(node, parents, function)
            if not any(
                read.lineno < node.lineno and _scope(read, parents, function) in (scope, function)
                for read in reads
            ):
                violations.append(f"{where} calls {name} with no plan read from its own request")

    reader = _top_level_functions(tree).get(_PLAN_READER)
    parses = [
        node
        for node in ast.walk(reader) if isinstance(node, ast.Call) and _callee(node) == "parse_business_plan"
    ] if reader else []
    if [ast.unparse(node) for node in parses] != ["parse_business_plan(payload.get(_BUSINESS_PLAN_KEY))"]:
        violations.append(f"{_PLAN_READER} reads something other than the business_plan key")
    keys = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_BUSINESS_PLAN_KEY" for target in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    if keys != ["business_plan"]:
        violations.append("_BUSINESS_PLAN_KEY is not exactly 'business_plan'")
    return violations


def test_the_api_passes_the_request_plan_to_every_plan_aware_call() -> None:
    assert _api_violations(_current(_API)) == []


def test_the_api_guard_inspects_every_plan_aware_call() -> None:
    tree = ast.parse(_current(_API))
    found = sorted(
        (function.name, _callee(node))
        for function in _top_level_functions(tree).values()
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _callee(node) in _API_PLAN_TAKERS
    )
    assert found == _API_PLAN_CALLS


def test_every_listed_plan_taker_really_takes_the_plan() -> None:
    """The taker list is checked against the callables the API actually
    resolves, so it cannot drift into guarding names that take no plan."""

    import anchor.api as api_module
    from anchor.deals import store

    for name in _API_PLAN_TAKERS:
        target = getattr(store if name in _STORE_NAMES else api_module, name)
        assert "business_plan" in inspect.signature(target).parameters, name


_API_MUTANTS = {
    "quick-analyze-uses-the-plan-free-engine": (
        "    return analyze_quick_acquisition_with_business_plan(\n"
        "        inputs, business_plan=business_plan\n    )",
        "    return analyze_acquisition(inputs)",
        "calls analyze_acquisition, which cannot carry a plan",
    ),
    "one-way-falls-back-to-the-neutral-default": (
        '        metric=payload["metric"],\n        business_plan=business_plan,\n'
        "    )\n\n\ndef _one_way_detailed",
        '        metric=payload["metric"],\n    )\n\n\ndef _one_way_detailed',
        "api._one_way_quick calls run_one_way_sensitivity without business_plan=",
    ),
    "presets-substitute-the-empty-plan": (
        "return build_standard_presets(inputs, business_plan=business_plan)",
        "return build_standard_presets(inputs, business_plan=BusinessPlan())",
        "passes business_plan=BusinessPlan()",
    ),
    "break-even-passes-none": (
        "            detailed_operating_inputs,\n"
        "            target_levered_irr=target_levered_irr,\n"
        "            target_headline_dscr=target_headline_dscr,\n"
        "            target_equity_multiple=target_equity_multiple,\n"
        "            return_hurdle_metric=return_hurdle_metric,\n"
        "            business_plan=business_plan,\n",
        "            detailed_operating_inputs,\n"
        "            target_levered_irr=target_levered_irr,\n"
        "            target_headline_dscr=target_headline_dscr,\n"
        "            target_equity_multiple=target_equity_multiple,\n"
        "            return_hurdle_metric=return_hurdle_metric,\n"
        "            business_plan=None,\n",
        "passes business_plan=None",
    ),
    "lease-level-ai-drops-the-plan": (
        "            operating_inputs=lease_level_inputs.operating_inputs,\n"
        "            business_plan=business_plan,\n",
        "            operating_inputs=lease_level_inputs.operating_inputs,\n",
        "api._ai_analysis_lease_level calls analyze_lease_level_acquisition_with_business_plan "
        "without business_plan=",
    ),
    "fingerprint-endpoint-drops-the-plan": (
        "            financial_input_fingerprint = fingerprint_quick_inputs(\n"
        "                inputs, business_plan=business_plan\n            )",
        "            financial_input_fingerprint = fingerprint_quick_inputs(inputs)",
        "api.deal_fingerprint calls fingerprint_quick_inputs without business_plan=",
    ),
    "update-route-neutralises-the-plan": (
        "                inputs = _require_deal_inputs(payload)\n"
        "                business_plan = _optional_business_plan(payload)\n"
        "                return deals_store.update_deal(",
        "                inputs = _require_deal_inputs(payload)\n"
        "                business_plan = BusinessPlan()\n"
        "                return deals_store.update_deal(",
        "api.update_deal binds business_plan other than from _optional_business_plan(payload)",
    ),
    "plan-dropped-in-one-case-arm": (
        "            business_plan = _optional_business_plan(payload)\n"
        "            return deals_store.create_lease_level_deal(",
        "            return deals_store.create_lease_level_deal(",
        "api.create_deal calls create_lease_level_deal with no plan read from its own request",
    ),
    "reader-reads-another-key": (
        "return parse_business_plan(payload.get(_BUSINESS_PLAN_KEY))",
        'return parse_business_plan(payload.get("plan"))',
        "_optional_business_plan reads something other than the business_plan key",
    ),
    "a-variable-other-than-the-read-plan": (
        "    return build_standard_detailed_presets(\n"
        "        terms, detailed_operating_inputs, business_plan=business_plan\n    )",
        "    return build_standard_detailed_presets(\n"
        "        terms, detailed_operating_inputs, business_plan=plan\n    )",
        "passes business_plan=plan",
    ),
}


@pytest.mark.parametrize("mutant", sorted(_API_MUTANTS))
def test_the_api_guard_rejects_a_real_omission(mutant: str) -> None:
    old, new, expected = _API_MUTANTS[mutant]
    violations = _api_violations(_mutate(_current(_API), old, new, label=mutant))
    assert any(expected in violation for violation in violations), violations


def test_the_api_guard_rejects_a_new_unthreaded_route() -> None:
    shortcut = (
        "\n\ndef _two_way_shortcut(payload):\n"
        "    inputs = _require_deal_inputs(payload)\n"
        "    return run_two_way_sensitivity(inputs, **payload)\n"
    )
    violations = _api_violations(_current(_API) + shortcut)
    assert "api._two_way_shortcut calls run_two_way_sensitivity without business_plan=" in violations
    assert (
        "api._two_way_shortcut calls run_two_way_sensitivity with no plan read from its own request"
        in violations
    )


#: What a plan item is made of; the API holds the plan opaquely. (``category``
#: and ``description`` are omitted -- generic names the API's own issue
#: rendering already uses.)
_PLAN_ITEM_ATTRIBUTES = frozenset(
    {"capital_items", "owner_expense_items", "item_id", "month", "amount", "annual_amount",
     "first_year", "last_year"}
)


def test_the_api_never_reads_a_plan_item() -> None:
    tree = ast.parse(_current(_API))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes & _PLAN_ITEM_ATTRIBUTES


# =============================================================================
# 2. The store omission guard
# =============================================================================

_STORE_TAKERS = frozenset(
    {
        "fingerprint_quick_inputs",
        "fingerprint_detailed_inputs",
        "fingerprint_lease_level_inputs",
        "_row_to_deal",
        "_row_to_detailed_deal",
        "_row_to_lease_level_deal",
        "create_deal",
        "create_detailed_deal",
        "create_lease_level_deal",
    }
)
_ROW_BUILDERS = ("_row_to_deal", "_row_to_detailed_deal", "_row_to_lease_level_deal")
#: Public write functions; ``True`` for the ones that replace an existing plan.
_WRITERS = {
    "create_deal": False,
    "create_detailed_deal": False,
    "create_lease_level_deal": False,
    "update_deal": True,
    "update_detailed_deal": True,
    "update_lease_level_deal": True,
}
_STORE_PLAN_CALLS = sorted(
    [
        ("_lease_level_input_fingerprint", "_row_to_lease_level_deal"),
        ("_lease_level_input_fingerprint", "fingerprint_lease_level_inputs"),
        ("_row_to_lease_level_deal", "fingerprint_lease_level_inputs"),
        ("_row_to_deal", "fingerprint_quick_inputs"),
        ("_row_to_detailed_deal", "fingerprint_detailed_inputs"),
        ("get_deal", "_row_to_deal"),
        ("get_deal", "_row_to_lease_level_deal"),
        ("get_deal", "_row_to_detailed_deal"),
        ("list_deals", "_row_to_lease_level_deal"),
        ("list_deals", "_row_to_deal"),
        ("list_deals", "_row_to_detailed_deal"),
        ("duplicate_deal", "create_deal"),
        ("duplicate_deal", "fingerprint_quick_inputs"),
        ("duplicate_deal", "create_detailed_deal"),
        ("duplicate_deal", "fingerprint_detailed_inputs"),
        ("duplicate_deal", "create_lease_level_deal"),
        ("duplicate_deal", "fingerprint_lease_level_inputs"),
        ("update_analysis_snapshot", "fingerprint_quick_inputs"),
        ("update_analysis_snapshot", "fingerprint_detailed_inputs"),
        ("update_ai_snapshot", "fingerprint_quick_inputs"),
        ("update_ai_snapshot", "fingerprint_detailed_inputs"),
    ]
)


def _plan_parameter(function: ast.FunctionDef) -> tuple[ast.arg, ast.expr | None] | None:
    for argument, default in zip(function.args.kwonlyargs, function.args.kw_defaults):
        if argument.arg == "business_plan":
            return argument, default
    return None


def _calls(function: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [
        node for node in ast.walk(function) if isinstance(node, ast.Call) and _callee(node) == name
    ]


def _store_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    functions = _top_level_functions(tree)
    violations: list[str] = []
    permitted_empty_plans: set[int] = set()

    for name, replaces in _WRITERS.items():
        function = functions[name]
        parameter = _plan_parameter(function)
        if parameter is None or not _is_empty_plan(parameter[1]):
            violations.append(f"store.{name} must take business_plan keyword-only, defaulting to BusinessPlan()")
        else:
            permitted_empty_plans.add(id(parameter[1]))
        validations = [
            call for call in _calls(function, "require_valid_business_plan")
            if [ast.unparse(a) for a in call.args] == ["business_plan"]
        ]
        connects = _calls(function, "_connect")
        if not validations or not connects or validations[0].lineno > connects[0].lineno:
            violations.append(f"store.{name} writes a plan it never validated")
        writes = [
            call for call in _calls(function, "_write_business_plan")
            if [ast.unparse(a) for a in call.args] == ["connection", "deal_id", "business_plan"]
        ]
        if len(writes) != 1:
            violations.append(f"store.{name} does not write the plan exactly once")
        if replaces:
            deletes = _calls(function, "_delete_business_plan")
            if not deletes or not writes or deletes[0].lineno > writes[0].lineno:
                violations.append(f"store.{name} writes the plan without first deleting the old one")

    for name in _ROW_BUILDERS:
        parameter = _plan_parameter(functions[name])
        if parameter is None or parameter[1] is not None:
            violations.append(f"store.{name} must require business_plan")

    if not _calls(functions["delete_deal"], "_delete_business_plan"):
        violations.append("store.delete_deal never deletes the plan rows")

    for function in functions.values():
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            name = _callee(node)
            if name == "BusinessPlan":
                if _is_empty_plan(node) and id(node) not in permitted_empty_plans:
                    violations.append(f"store.{function.name} constructs an empty BusinessPlan()")
                elif not _is_empty_plan(node) and function.name != "_business_plan_from_rows":
                    violations.append(f"store.{function.name} builds a plan outside the codec")
            if name in _STORE_TAKERS:
                keywords = {k.arg: k.value for k in node.keywords}
                if "business_plan" not in keywords:
                    violations.append(f"store.{function.name} calls {name} without business_plan=")
                else:
                    value = keywords["business_plan"]
                    if (isinstance(value, ast.Constant) and value.value is None) or (
                        isinstance(value, ast.Call) and _callee(value) == "BusinessPlan"
                    ):
                        violations.append(
                            f"store.{function.name} passes business_plan={ast.unparse(value)} to {name}"
                        )
    return violations


def test_the_store_threads_the_stored_plan_everywhere() -> None:
    assert _store_violations(_current(_STORE)) == []


def test_the_store_guard_inspects_every_plan_aware_call() -> None:
    tree = ast.parse(_current(_STORE))
    found = sorted(
        (function.name, _callee(node))
        for function in _top_level_functions(tree).values()
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _callee(node) in _STORE_TAKERS
    )
    assert found == _STORE_PLAN_CALLS


_STORE_MUTANTS = {
    "duplicate-omits-the-plan": (
        "                original.inputs,\n"
        "                deal_context=original.deal_context,\n"
        "                business_plan=original.business_plan,\n",
        "                original.inputs,\n"
        "                deal_context=original.deal_context,\n",
        "store.duplicate_deal calls create_deal without business_plan=",
    ),
    "reopen-hands-the-deal-an-empty-plan": (
        "            return _row_to_deal(\n"
        "                quick_row, business_plan=_read_business_plan(connection, deal_id)\n"
        "            )",
        "            return _row_to_deal(quick_row, business_plan=BusinessPlan())",
        "store.get_deal passes business_plan=BusinessPlan() to _row_to_deal",
    ),
    "provenance-ignores-the-plan": (
        "            expected_fingerprint = fingerprint_quick_inputs(\n"
        "                _inputs_from_row(quick_row),\n"
        "                business_plan=_read_business_plan(connection, deal_id),\n"
        "            )",
        "            expected_fingerprint = fingerprint_quick_inputs(_inputs_from_row(quick_row))",
        "store.update_analysis_snapshot calls fingerprint_quick_inputs without business_plan=",
    ),
    "update-leaves-ghost-rows": (
        "            raise DealNotFoundError(deal_id)\n\n"
        "        _delete_business_plan(connection, deal_id)\n"
        "        _write_business_plan(connection, deal_id, business_plan)\n",
        "            raise DealNotFoundError(deal_id)\n\n"
        "        _write_business_plan(connection, deal_id, business_plan)\n",
        "store.update_deal writes the plan without first deleting the old one",
    ),
    "delete-orphans-the-plan": (
        "        _delete_business_plan(connection, deal_id)\n\n"
        '        cursor = connection.execute("DELETE FROM deals WHERE id = ?", (deal_id,))',
        '        cursor = connection.execute("DELETE FROM deals WHERE id = ?", (deal_id,))',
        "store.delete_deal never deletes the plan rows",
    ),
    "row-builder-gains-a-default": (
        "    row: sqlite3.Row, *, business_plan: BusinessPlan, include_snapshots: bool = True\n"
        ") -> Deal:",
        "    row: sqlite3.Row, *, business_plan: BusinessPlan = BusinessPlan(),\n"
        "    include_snapshots: bool = True\n) -> Deal:",
        "store._row_to_deal must require business_plan",
    ),
    "write-skips-validation": (
        "    require_valid_business_plan(business_plan)\n    deal_id = uuid.uuid4().hex\n",
        "    deal_id = uuid.uuid4().hex\n",
        "store.create_deal writes a plan it never validated",
    ),
}


@pytest.mark.parametrize("mutant", sorted(_STORE_MUTANTS))
def test_the_store_guard_rejects_a_real_omission(mutant: str) -> None:
    old, new, expected = _STORE_MUTANTS[mutant]
    violations = _store_violations(_mutate(_current(_STORE), old, new, label=mutant))
    assert any(expected in violation for violation in violations), violations


def test_only_the_store_codec_reads_plan_items() -> None:
    reading = {
        function.name
        for function in _top_level_functions(ast.parse(_current(_STORE))).values()
        if {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)}
        & {"capital_items", "owner_expense_items", "annual_amount", "first_year", "last_year"}
    }
    assert reading == {"_write_business_plan"}


# =============================================================================
# 3. The fingerprint inclusion guard -- behavioural
# =============================================================================


def _probe(source: str) -> types.ModuleType:
    """Load fingerprint source as a module of ``anchor.deals`` -- the real file
    or a mutant of it -- so its behaviour, not its text, is what is checked."""

    module = types.ModuleType("anchor.deals._d6_5_fingerprint_probe")
    module.__package__ = "anchor.deals"
    exec(compile(source, "<fingerprint probe>", "exec"), module.__dict__)
    return module


def _field_edits() -> list[tuple[str, BusinessPlan]]:
    """One edit per field of each item type, generated from the contracts so a
    field added to either one is covered the day it is added."""

    edits: list[tuple[str, BusinessPlan]] = []
    for collection, contract in (
        ("capital_items", CapitalPlanItem),
        ("owner_expense_items", OwnerExpenseItem),
    ):
        item = getattr(MATERIAL, collection)[0]
        for field in dataclasses.fields(contract):
            value = getattr(item, field.name)
            if isinstance(value, Enum):
                changed: object = next(member for member in type(value) if member is not value)
            elif isinstance(value, str):
                changed = value + " (edited)"
            elif value is None:
                changed = 9
            elif isinstance(value, int):
                changed = value + 1
            else:
                changed = value + 1.0
            edits.append(
                (f"{collection}.{field.name}", edit_item(MATERIAL, collection, 0, **{field.name: changed}))
            )
    return edits


def _fingerprint_violations(module: types.ModuleType) -> list[str]:
    violations: list[str] = []
    for mode in MODES:
        def digest(plan: BusinessPlan | None) -> str:
            return fingerprint_with(module, mode, plan)

        if digest(BusinessPlan()) != PRE_D6_5_DIGESTS[mode] or digest(None) != PRE_D6_5_DIGESTS[mode]:
            violations.append(f"{mode}: the empty plan moved the legacy digest")
        base = digest(MATERIAL)
        if base == digest(BusinessPlan()):
            violations.append(f"{mode}: the plan does not reach the fingerprint")
        for field, edited in _field_edits():
            if digest(edited) == base:
                violations.append(f"{mode}: {field} does not reach the fingerprint")
        for reordered in (
            reversed_plan(MATERIAL),
            dataclasses.replace(MATERIAL, capital_items=tuple(reversed(MATERIAL.capital_items))),
            dataclasses.replace(
                MATERIAL, owner_expense_items=tuple(reversed(MATERIAL.owner_expense_items))
            ),
        ):
            if digest(reordered) != base:
                violations.append(f"{mode}: row order reaches the fingerprint")
    return violations


def test_the_real_fingerprint_includes_the_plan_canonically() -> None:
    assert _fingerprint_violations(_probe(_current(_FINGERPRINT))) == []


def test_every_public_fingerprint_takes_the_plan_keyword_only() -> None:
    from anchor.deals import fingerprint

    for name in ("fingerprint_quick_inputs", "fingerprint_detailed_inputs", "fingerprint_lease_level_inputs"):
        parameter = inspect.signature(getattr(fingerprint, name)).parameters["business_plan"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default == BusinessPlan(), name


_FINGERPRINT_MUTANTS = {
    "quick-drops-the-plan": (
        "    return _fingerprint_json(\n"
        "        _with_business_plan(dataclasses.asdict(inputs), business_plan)\n    )",
        "    return _fingerprint_json(dataclasses.asdict(inputs))",
        "quick: the plan does not reach the fingerprint",
    ),
    "detailed-drops-the-plan": (
        "            business_plan,\n        )\n    )\n\n\ndef fingerprint_ai(",
        "            BusinessPlan(),\n        )\n    )\n\n\ndef fingerprint_ai(",
        "detailed: the plan does not reach the fingerprint",
    ),
    "lease-level-drops-the-plan": (
        "                }\n            },\n            business_plan,\n",
        "                }\n            },\n            BusinessPlan(),\n",
        "lease_level: the plan does not reach the fingerprint",
    ),
    "hashes-raw-tuple-order": (
        "for item in sorted(business_plan.capital_items, key=lambda item: item.item_id)",
        "for item in business_plan.capital_items",
        "row order reaches the fingerprint",
    ),
    "hashes-the-ordinal": (
        "                dataclasses.asdict(item)\n"
        "                for item in sorted(business_plan.capital_items, key=lambda item: item.item_id)",
        '                {**dataclasses.asdict(item), "ordinal": ordinal}\n'
        "                for ordinal, item in enumerate(business_plan.capital_items)",
        "row order reaches the fingerprint",
    ),
    "empty-plan-adds-a-key": (
        "    if not business_plan.capital_items and not business_plan.owner_expense_items:\n"
        "        return payload\n",
        "",
        "the empty plan moved the legacy digest",
    ),
    "ignores-the-capital-amount": (
        "                dataclasses.asdict(item)\n"
        "                for item in sorted(business_plan.capital_items",
        '                {key: value for key, value in dataclasses.asdict(item).items() if key != "amount"}\n'
        "                for item in sorted(business_plan.capital_items",
        "capital_items.amount does not reach the fingerprint",
    ),
    "ignores-the-owner-expense-last-year": (
        "                dataclasses.asdict(item)\n"
        "                for item in sorted(\n"
        "                    business_plan.owner_expense_items",
        '                {key: value for key, value in dataclasses.asdict(item).items() if key != "last_year"}\n'
        "                for item in sorted(\n"
        "                    business_plan.owner_expense_items",
        "owner_expense_items.last_year does not reach the fingerprint",
    ),
}


@pytest.mark.parametrize("mutant", sorted(_FINGERPRINT_MUTANTS))
def test_the_fingerprint_guard_rejects_a_real_mutant(mutant: str) -> None:
    old, new, expected = _FINGERPRINT_MUTANTS[mutant]
    module = _probe(_mutate(_current(_FINGERPRINT), old, new, label=mutant))
    violations = _fingerprint_violations(module)
    assert any(expected in violation for violation in violations), violations


# =============================================================================
# 4. Contracts: one mode-agnostic plan per deal, and D6.3 typing intact
# =============================================================================


def test_the_deal_carries_exactly_one_mode_agnostic_plan() -> None:
    from anchor.deals.contracts import Deal

    fields = {field.name: field for field in dataclasses.fields(Deal)}
    assert fields["business_plan"].default == BusinessPlan()
    assert [name for name in fields if "plan" in name] == ["business_plan"]


def test_no_operating_contract_carries_a_business_plan_field() -> None:
    from anchor.analysis import (
        Lease,
        LeaseLevelOperatingInputs,
        LeaseLevelPropertyInputs,
        MarketLeasingAssumptions,
        Suite,
    )
    from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs

    for contract in (
        AcquisitionInputs,
        AcquisitionTerms,
        DetailedOperatingInputs,
        LeaseLevelPropertyInputs,
        LeaseLevelOperatingInputs,
        MarketLeasingAssumptions,
        Suite,
        Lease,
    ):
        names = {field.name for field in dataclasses.fields(contract)}
        assert not names & {"business_plan", "capital_items", "owner_expense_items"}, contract


def test_the_irr_status_rehydration_is_byte_identical_to_d6_4() -> None:
    def coerce(source: str) -> str:
        return ast.dump(
            _top_level_functions(ast.parse(source))["_coerce_snapshot_value"]
        )

    assert coerce(_current(_STORE)) == coerce(_at(_D6_4_MERGE, _STORE))


# =============================================================================
# 5. Scope -- D6.5 changed exactly its authorized production files
# =============================================================================

_D6_5_PRODUCTION_FILES = frozenset(
    {
        "src/anchor/api.py",
        "src/anchor/deals/contracts.py",
        "src/anchor/deals/fingerprint.py",
        "src/anchor/deals/store.py",
        "src/anchor/business_plan/__init__.py",
        "src/anchor/business_plan/parsing.py",
    }
)

#: Financial truth D6.5 must carry, never create: every one is unchanged.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/leasing",
    "src/anchor/analysis",
    "src/anchor/ai",
    "src/anchor/business_plan/contracts.py",
    "src/anchor/business_plan/resolver.py",
    "src/anchor/business_plan/validation.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/deals/__init__.py",
    "web",
)


def test_d6_5_changed_exactly_its_authorized_production_files() -> None:
    changed = set(_files_changed_since(_D6_4_MERGE, "src")) | set(
        _files_changed_since(_D6_4_MERGE, "web")
    )
    assert changed == _D6_5_PRODUCTION_FILES, (
        f"unexpected: {sorted(changed - _D6_5_PRODUCTION_FILES)}; "
        f"missing: {sorted(_D6_5_PRODUCTION_FILES - changed)}"
    )


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_d6_4(path: str) -> None:
    assert _files_changed_since(_D6_4_MERGE, path) == [], f"{path} changed at D6.5"


def test_the_parser_restates_no_domain_rule() -> None:
    """The wire parser may name structure only: every domain refusal comes
    from the validation authority. It raises no domain code except the one
    finite-number case a whole-number amount too large for a float forces."""

    tree = ast.parse(_current("src/anchor/business_plan/parsing.py"))
    codes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "BusinessPlanIssueCode"
    }
    assert codes == {"MALFORMED_FIELD", "NON_FINITE_VALUE"}
    called = {_callee(node) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert "require_valid_business_plan" in called
    assert not called & {"resolve_business_plan", "isfinite"}
