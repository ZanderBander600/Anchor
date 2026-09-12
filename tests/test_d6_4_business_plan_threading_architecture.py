"""Phase 6 Gate D6.4 -- architecture guardrails for Business Plan threading.

Governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Section 16 and
decision D13: the Business Plan is threaded as a required keyword argument, and
an AST guardrail enforces it.

D6.4 edits four plan-aware modules -- ``analysis/sensitivity.py``,
``analysis/break_even.py``, ``analysis/lease_level_sensitivity.py`` and
``ai/analyst.py``. Their byte-identity guardrails (D4.6B G36/G37 and the D6.1
unchanged-path list) no longer state the rule, so they are narrowed by exactly
those files and replaced here by claims that are stronger where it matters:

1. **The omission guard.** Inside those modules no candidate can reach the
   engine without the resolved plan. Every engine entry-point call passes
   ``owner_capital=owner_capital`` -- a required keyword-only parameter, or the
   one resolution of the invocation's own ``business_plan`` for the base hold
   period. Every call to a plan-aware function passes ``business_plan`` or
   ``owner_capital`` explicitly, by name. ``BusinessPlan()`` exists only as the
   default of an enumerated public compatibility boundary, and nothing is ever
   passed ``None``. Self-tests prove each rule rejects a real mutant.
2. **Threading only.** With the threaded keywords, parameters and resolution
   statements removed and docstrings ignored, each module is AST-identical to
   ba804ca -- the two renamed search bodies included. No target, metric,
   tolerance, bound, preset offset, bisection step or ``_meets_hurdle`` rule
   moved.
3. **Resolve once is exact.** No sensitivity or break-even target is the hold
   period, and the engine refuses a schedule resolved for a different hold.
4. **The boundary.** Only the enumerated modules import
   ``anchor.business_plan``, each only the names it needs, and none of them
   reads a plan item.
5. **The ledger.** D6.4 changed exactly its authorized production files.

Every git query runs against a private copy of the index (protocol Section
11.2). Source text is compared CRLF-normalised to LF and nothing else.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import os
from collections.abc import Mapping
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
_ANCHOR_DIR = _SRC_DIR / "anchor"

#: ``main`` after D6.3, immediately before D6.4.
_D6_3_MERGE = "ba804ca"

_MODULES = {
    "sensitivity": "src/anchor/analysis/sensitivity.py",
    "break_even": "src/anchor/analysis/break_even.py",
    "lease_level_sensitivity": "src/anchor/analysis/lease_level_sensitivity.py",
    "analyst": "src/anchor/ai/analyst.py",
}
_ENTRY_POINTS = "src/anchor/analysis/business_plan_analysis.py"

_THREADED = ("business_plan", "owner_capital")

#: The engine entry points a candidate may reach. Each takes the resolved
#: schedule as the keyword-only ``owner_capital``.
_ENGINE_ENTRY_POINTS = frozenset(
    {
        "analyze_acquisition",
        "analyze_detailed_acquisition_with_projection",
        "analyze_lease_level_acquisition_with_projection",
        "analyze_acquisition_from_operating_projection",
    }
)
#: An engine entry point whose pinned signature cannot carry a plan at all.
_PLANLESS_ENTRY_POINTS = frozenset({"analyze_detailed_acquisition"})
#: The D6.2 Business Plan entry points; each requires ``business_plan``.
_PLAN_ENTRY_POINTS = frozenset(
    {
        "analyze_quick_acquisition_with_business_plan",
        "analyze_detailed_acquisition_with_business_plan",
        "analyze_lease_level_acquisition_with_business_plan",
    }
)

#: The outermost compatibility boundary -- the public functions an existing
#: caller (the API, until D6.5) still calls with no plan. Exactly these may
#: default ``business_plan``, and only to ``BusinessPlan()``.
_PUBLIC_BOUNDARY = {
    "sensitivity": frozenset(
        {
            "run_one_way_sensitivity",
            "run_two_way_sensitivity",
            "build_exit_cap_noi_growth_preset",
            "build_purchase_price_exit_cap_preset",
            "build_interest_rate_ltv_preset",
            "build_standard_presets",
            "run_detailed_one_way_sensitivity",
            "run_detailed_two_way_sensitivity",
            "build_detailed_purchase_price_exit_cap_preset",
            "build_detailed_interest_rate_ltv_preset",
            "build_standard_detailed_presets",
        }
    ),
    "break_even": frozenset(
        {
            "solve_break_even_threshold",
            "solve_max_purchase_price",
            "solve_max_exit_cap_rate",
            "solve_min_noi_growth",
            "solve_max_interest_rate",
            "solve_min_current_noi",
            "build_standard_break_even_analysis",
            "solve_detailed_break_even_threshold",
            "solve_detailed_max_purchase_price",
            "solve_detailed_max_exit_cap_rate",
            "solve_detailed_max_interest_rate",
            "build_standard_detailed_break_even_analysis",
        }
    ),
    "lease_level_sensitivity": frozenset(
        {"run_lease_level_one_way_sensitivity", "run_lease_level_two_way_sensitivity"}
    ),
    "analyst": frozenset(
        {
            "build_analysis_context",
            "build_detailed_analysis_context",
            "generate_ai_analysis",
            "generate_detailed_ai_analysis",
        }
    ),
}

#: The plan-aware internal path: required keyword-only, never defaulted.
_PRIVATE_TAKERS = {
    "sensitivity": {"_analyze_detailed_scenario": "owner_capital"},
    "break_even": {
        "_evaluate_candidate": "owner_capital",
        "_resolve_undefined_favorable_endpoint": "owner_capital",
        "_solve_break_even_threshold": "owner_capital",
        "_build_break_even_result": "business_plan",
        "_evaluate_detailed_candidate": "owner_capital",
        "_resolve_undefined_favorable_endpoint_detailed": "owner_capital",
        "_solve_detailed_break_even_threshold": "owner_capital",
        "_build_detailed_break_even_result": "business_plan",
    },
    "lease_level_sensitivity": {"_scenario_metric": "owner_capital"},
    "analyst": {},
}

#: Where a plan is resolved: once per invocation, for the base hold period.
_RESOLUTION_SITES = {
    "sensitivity": {
        "run_one_way_sensitivity",
        "run_two_way_sensitivity",
        "run_detailed_one_way_sensitivity",
        "run_detailed_two_way_sensitivity",
    },
    "break_even": {
        "solve_break_even_threshold",
        "_build_break_even_result",
        "solve_detailed_break_even_threshold",
        "_build_detailed_break_even_result",
    },
    "lease_level_sensitivity": {
        "run_lease_level_one_way_sensitivity",
        "run_lease_level_two_way_sensitivity",
    },
    "analyst": set(),
}

#: Every analysis these modules run, by ``(calling function, entry point)``.
_ANALYSIS_CALLS = {
    "sensitivity": [
        ("_analyze_detailed_scenario", "analyze_detailed_acquisition_with_projection"),
        ("run_one_way_sensitivity", "analyze_acquisition"),
        ("run_one_way_sensitivity", "analyze_acquisition"),
        ("run_two_way_sensitivity", "analyze_acquisition"),
        ("run_two_way_sensitivity", "analyze_acquisition"),
    ],
    "break_even": [
        ("_build_break_even_result", "analyze_acquisition"),
        ("_build_detailed_break_even_result", "analyze_detailed_acquisition_with_projection"),
        ("_evaluate_candidate", "analyze_acquisition"),
        ("_evaluate_detailed_candidate", "analyze_detailed_acquisition_with_projection"),
    ],
    "lease_level_sensitivity": [
        ("_scenario_metric", "analyze_lease_level_acquisition_with_projection"),
    ],
    "analyst": [
        ("build_analysis_context", "analyze_quick_acquisition_with_business_plan"),
        ("build_detailed_analysis_context", "analyze_detailed_acquisition_with_business_plan"),
    ],
}


# =============================================================================
# Helpers
# =============================================================================


def _git_bytes(arguments: list[str]) -> bytes:
    """One read-only git query against a private copy of the index."""

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


def _baseline(path: str) -> str:
    return _lf(_git_bytes(["show", f"{_D6_3_MERGE}:{path}"]).decode("utf-8"))


def _current(path: str) -> str:
    return _lf((_PROJECT_ROOT / path).read_bytes().decode("utf-8"))


def _sources() -> dict[str, str]:
    return {label: _current(path) for label, path in _MODULES.items()}


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _functions(tree: ast.AST) -> list[ast.FunctionDef]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]


def _threaded_parameters(function: ast.FunctionDef) -> list[tuple[ast.arg, ast.expr | None, bool]]:
    """``(parameter, default, keyword_only)`` for each threaded parameter."""

    found: list[tuple[ast.arg, ast.expr | None, bool]] = [
        (arg, None, False)
        for arg in (*function.args.posonlyargs, *function.args.args)
        if arg.arg in _THREADED
    ]
    found.extend(
        (arg, default, True)
        for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults)
        if arg.arg in _THREADED
    )
    return found


def _is_empty_plan(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and _callee(node) == "BusinessPlan"
        and not node.args
        and not node.keywords
    )


def _is_resolution(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and _callee(node.value) == "resolve_business_plan"
    )


# =============================================================================
# 1. The omission guard
# =============================================================================


def _threading_violations(sources: Mapping[str, str]) -> list[str]:
    """Every way a plan-aware module could drop, replace or neutralise the plan.

    Returns human-readable violations; an empty list means the threading holds.
    """

    trees = {label: ast.parse(source) for label, source in sources.items()}

    takes: dict[str, str] = {name: "owner_capital" for name in _ENGINE_ENTRY_POINTS}
    takes.update({name: "business_plan" for name in _PLAN_ENTRY_POINTS})
    for tree in trees.values():
        for function in _functions(tree):
            parameters = _threaded_parameters(function)
            if len(parameters) == 1:
                takes[function.name] = parameters[0][0].arg

    violations: list[str] = []
    for label, tree in trees.items():
        boundary = _PUBLIC_BOUNDARY[label]
        permitted_defaults: set[int] = set()
        checked_calls: set[int] = set()

        for function in _functions(tree):
            where = f"{label}.{function.name}"
            parameters = _threaded_parameters(function)
            if len(parameters) > 1:
                violations.append(f"{where} takes both a plan and a schedule")
            parameter = parameters[0][0].arg if parameters else None

            # -- the parameter: required keyword-only, defaulted only at the boundary
            if function.name in boundary:
                _, default, keyword_only = parameters[0] if parameters else (None, None, False)
                if parameter != "business_plan" or not keyword_only or not _is_empty_plan(default):
                    violations.append(
                        f"{where} is a public boundary and must take business_plan "
                        "keyword-only, defaulting to BusinessPlan()"
                    )
                else:
                    permitted_defaults.add(id(default))
            elif parameters:
                _, default, keyword_only = parameters[0]
                if not keyword_only:
                    violations.append(f"{where} takes {parameter} positionally")
                if default is not None:
                    violations.append(
                        f"{where} defaults {parameter}; only the public boundary may"
                    )

            body = [node for statement in function.body for node in ast.walk(statement)]

            # -- resolution: once, of this function's own plan, for the base hold
            resolutions = [node for node in body if _is_resolution(node)]
            for node in body:
                if (
                    isinstance(node, ast.Call)
                    and _callee(node) == "resolve_business_plan"
                    and not any(node is resolution.value for resolution in resolutions)
                ):
                    violations.append(f"{where} resolves a plan other than into owner_capital")
            for resolution in resolutions:
                call = resolution.value
                target = resolution.targets
                if not (len(target) == 1 and isinstance(target[0], ast.Name) and target[0].id == "owner_capital"):
                    violations.append(f"{where} resolves a plan into something other than owner_capital")
                if parameter != "business_plan" or [ast.unparse(a) for a in call.args] != ["business_plan"]:
                    violations.append(f"{where} resolves something other than its own business_plan")
                hold = {keyword.arg: keyword.value for keyword in call.keywords}
                if set(hold) != {"hold_period"} or not (
                    isinstance(hold["hold_period"], ast.Attribute)
                    and hold["hold_period"].attr == "hold_period"
                    and isinstance(hold["hold_period"].value, ast.Name)
                ):
                    violations.append(f"{where} resolves for something other than the base hold")
            if len(resolutions) > 1:
                violations.append(f"{where} resolves the plan more than once")

            # -- a threaded name is never rebound
            for node in body:
                if isinstance(node, ast.Assign) and not _is_resolution(node):
                    targets = node.targets
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr, ast.For)):
                    targets = [node.target]
                elif isinstance(node, ast.comprehension):
                    targets = [node.target]
                else:
                    continue
                for target in targets:
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name) and name.id in _THREADED:
                            violations.append(f"{where} rebinds {name.id}")

            in_scope = {parameter} if parameter else set()
            if resolutions:
                in_scope.add("owner_capital")

            # -- every call that reaches an analysis carries the plan, by name
            for node in body:
                if not isinstance(node, ast.Call):
                    continue
                checked_calls.add(id(node))
                name = _callee(node)
                keywords = {k.arg: k.value for k in node.keywords if k.arg is not None}
                for keyword, value in keywords.items():
                    if keyword in _THREADED and not (
                        isinstance(value, ast.Name) and value.id == keyword
                    ):
                        violations.append(f"{where} passes {keyword}={ast.unparse(value)} to {name}")
                if name in _PLANLESS_ENTRY_POINTS:
                    violations.append(f"{where} calls {name}, which cannot carry a plan")
                if name in takes:
                    needed = takes[name]
                    if needed not in keywords:
                        violations.append(f"{where} calls {name} without {needed}=")
                    if needed not in in_scope:
                        violations.append(f"{where} calls {name} with no {needed} of its own")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _callee(node) == "BusinessPlan" and id(node) not in permitted_defaults:
                violations.append(
                    f"{label} constructs BusinessPlan() outside a public boundary default "
                    f"(line {node.lineno})"
                )
            if id(node) not in checked_calls and _callee(node) in takes | {
                name: "" for name in _PLANLESS_ENTRY_POINTS
            }:
                violations.append(f"{label} runs {_callee(node)} outside any function")

        missing = boundary - {function.name for function in _functions(tree)}
        if missing:
            violations.append(f"{label} lost its boundary functions {sorted(missing)}")

    return violations


def test_the_plan_cannot_be_omitted_from_any_secondary_analysis() -> None:
    assert _threading_violations(_sources()) == []


def test_the_guard_inspects_the_actual_analysis_calls() -> None:
    """The guard is not vacuous: these are every analysis the four modules run,
    and each is one the guard checked."""

    for label, source in _sources().items():
        found = sorted(
            (function.name, _callee(node))
            for function in _functions(ast.parse(source))
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and _callee(node) in _ENGINE_ENTRY_POINTS | _PLAN_ENTRY_POINTS | _PLANLESS_ENTRY_POINTS
        )
        assert found == sorted(_ANALYSIS_CALLS[label]), label


def test_the_threaded_parameters_are_exactly_the_boundary_and_the_private_path() -> None:
    for label, source in _sources().items():
        declared = {
            function.name: _threaded_parameters(function)[0][0].arg
            for function in _functions(ast.parse(source))
            if _threaded_parameters(function)
        }
        expected = {name: "business_plan" for name in _PUBLIC_BOUNDARY[label]}
        expected.update(_PRIVATE_TAKERS[label])
        assert declared == expected, label

        resolving = {
            function.name
            for function in _functions(ast.parse(source))
            if any(_is_resolution(node) for node in ast.walk(function))
        }
        assert resolving == _RESOLUTION_SITES[label], label


def test_the_boundary_defaults_and_the_private_path_requires_at_runtime() -> None:
    """The same claim through ``inspect``: the boundary's default is the empty
    plan, and the private path has no default to fall back on."""

    from anchor.ai import analyst
    from anchor.analysis import break_even, lease_level_sensitivity, sensitivity
    from anchor.business_plan import BusinessPlan

    modules = {
        "sensitivity": sensitivity,
        "break_even": break_even,
        "lease_level_sensitivity": lease_level_sensitivity,
        "analyst": analyst,
    }
    for label, module in modules.items():
        for name in _PUBLIC_BOUNDARY[label]:
            parameter = inspect.signature(getattr(module, name)).parameters["business_plan"]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default == BusinessPlan(), name
        for name, threaded in _PRIVATE_TAKERS[label].items():
            parameter = inspect.signature(getattr(module, name)).parameters[threaded]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default is inspect.Parameter.empty, name


# -- the guard's self-tests (gate Part T) --------------------------------------

_MUTANTS = {
    "quick-scenario-omits-owner-capital": (
        "sensitivity",
        "analyze_acquisition(scenario_inputs, owner_capital=owner_capital)",
        "analyze_acquisition(scenario_inputs)",
        "calls analyze_acquisition without owner_capital=",
    ),
    "detailed-preset-omits-business-plan": (
        "sensitivity",
        'detailed_operating_inputs,\n        row_assumption="purchase_price",\n'
        "        row_values=purchase_price_values,\n"
        '        column_assumption="exit_cap_rate",\n'
        "        column_values=exit_cap_values,\n"
        '        metric="levered_irr",\n'
        "        business_plan=business_plan,\n",
        'detailed_operating_inputs,\n        row_assumption="purchase_price",\n'
        "        row_values=purchase_price_values,\n"
        '        column_assumption="exit_cap_rate",\n'
        "        column_values=exit_cap_values,\n"
        '        metric="levered_irr",\n',
        "calls run_detailed_two_way_sensitivity without business_plan=",
    ),
    "quick-preset-substitutes-the-empty-plan": (
        "sensitivity",
        "        business_plan=business_plan,\n",
        "        business_plan=BusinessPlan(),\n",
        "passes business_plan=BusinessPlan()",
    ),
    "detailed-evaluator-switches-to-the-planless-entry-point": (
        "sensitivity",
        "    return analyze_detailed_acquisition_with_projection(\n"
        "        terms, detailed_operating_inputs, owner_capital=owner_capital\n"
        "    ).results",
        "    return analyze_detailed_acquisition(terms, detailed_operating_inputs)",
        "calls analyze_detailed_acquisition, which cannot carry a plan",
    ),
    "lease-level-seam-passes-none": (
        "lease_level_sensitivity",
        "operating_inputs=scenario_operating,\n            owner_capital=owner_capital,",
        "operating_inputs=scenario_operating,\n            owner_capital=None,",
        "passes owner_capital=None",
    ),
    "lease-level-runner-resolves-the-empty-plan": (
        "lease_level_sensitivity",
        "owner_capital = resolve_business_plan(business_plan, hold_period=terms.hold_period)",
        "owner_capital = resolve_business_plan(BusinessPlan(), hold_period=terms.hold_period)",
        "resolves something other than its own business_plan",
    ),
    "break-even-candidates-use-the-empty-plan": (
        "break_even",
        "    owner_capital = resolve_business_plan(business_plan, hold_period=inputs.hold_period)\n"
        "\n    baseline_assumption_value = getattr(inputs, assumption)",
        "    owner_capital = resolve_business_plan(BusinessPlan(), hold_period=inputs.hold_period)\n"
        "\n    baseline_assumption_value = getattr(inputs, assumption)",
        "constructs BusinessPlan() outside a public boundary default",
    ),
    "break-even-resolves-for-another-hold": (
        "break_even",
        "resolve_business_plan(business_plan, hold_period=inputs.hold_period)",
        "resolve_business_plan(business_plan, hold_period=5)",
        "resolves for something other than the base hold",
    ),
    "break-even-candidate-omits-owner-capital": (
        "break_even",
        "scenario_results = analyze_acquisition(scenario_inputs, owner_capital=owner_capital)",
        "scenario_results = analyze_acquisition(scenario_inputs)",
        "calls analyze_acquisition without owner_capital=",
    ),
    "break-even-solver-omits-business-plan": (
        "break_even",
        "        business_plan=business_plan,\n        break_even_type=BreakEvenType.MAX_PURCHASE_PRICE,",
        "        break_even_type=BreakEvenType.MAX_PURCHASE_PRICE,",
        "calls _build_break_even_result without business_plan=",
    ),
    "break-even-bundle-substitutes-the-empty-plan": (
        "break_even",
        "inputs, **return_hurdle_kwargs, business_plan=business_plan\n",
        "inputs, **return_hurdle_kwargs, business_plan=BusinessPlan()\n",
        "passes business_plan=BusinessPlan()",
    ),
    "break-even-private-path-gains-a-default": (
        "break_even",
        "    owner_capital: OwnerCapitalSchedule,\n    assumption: str,\n    metric: str,\n"
        "    candidate_value: float,\n",
        "    owner_capital: OwnerCapitalSchedule | None = None,\n    assumption: str,\n"
        "    metric: str,\n    candidate_value: float,\n",
        "defaults owner_capital; only the public boundary may",
    ),
    "break-even-builder-defaults-to-the-empty-plan": (
        "break_even",
        "    business_plan: BusinessPlan,\n    break_even_type: BreakEvenType,",
        "    business_plan: BusinessPlan = BusinessPlan(),\n    break_even_type: BreakEvenType,",
        "defaults business_plan; only the public boundary may",
    ),
    "ai-presets-omit-business-plan": (
        "analyst",
        "sensitivities = build_standard_presets(inputs, business_plan=business_plan)",
        "sensitivities = build_standard_presets(inputs)",
        "calls build_standard_presets without business_plan=",
    ),
    "ai-base-analysis-passes-a-fresh-empty-plan": (
        "analyst",
        "        inputs, business_plan=business_plan\n    )\n    sensitivities",
        "        inputs, business_plan=BusinessPlan()\n    )\n    sensitivities",
        "passes business_plan=BusinessPlan()",
    ),
    "ai-boundary-loses-its-plan": (
        "analyst",
        "    deal_context: str | None = None,\n    business_plan: BusinessPlan = BusinessPlan(),\n"
        ") -> AnalysisContext:\n    \"\"\"Assemble one deterministic ``AnalysisContext`` for ``inputs``",
        "    deal_context: str | None = None,\n"
        ") -> AnalysisContext:\n    \"\"\"Assemble one deterministic ``AnalysisContext`` for ``inputs``",
        "is a public boundary and must take business_plan",
    ),
}


@pytest.mark.parametrize("mutant", sorted(_MUTANTS))
def test_the_guard_rejects_a_real_omission(mutant: str) -> None:
    label, old, new, expected = _MUTANTS[mutant]
    sources = _sources()
    assert old in sources[label], f"{mutant}: the mutation site no longer exists"

    mutated = {**sources, label: sources[label].replace(old, new, 1)}
    ast.parse(mutated[label])  # a real, importable mutant -- not a syntax error

    violations = _threading_violations(mutated)
    assert any(expected in violation for violation in violations), violations


def test_the_guard_rejects_a_new_unthreaded_candidate_path() -> None:
    """A future helper that runs a candidate with no plan in scope at all."""

    sources = _sources()
    shortcut = (
        "\n\ndef _quick_shortcut(inputs):\n"
        "    return analyze_acquisition(inputs)\n"
    )
    violations = _threading_violations(
        {**sources, "sensitivity": sources["sensitivity"] + shortcut}
    )
    assert "sensitivity._quick_shortcut calls analyze_acquisition without owner_capital=" in (
        violations
    )
    assert "sensitivity._quick_shortcut calls analyze_acquisition with no owner_capital of its own" in (
        violations
    )


# =============================================================================
# 2. Threading only -- every module is ba804ca once the threading is undone
# =============================================================================

#: Current name -> the ba804ca name whose body it carries.
_RENAMES = {
    "sensitivity": {},
    "break_even": {
        "_solve_break_even_threshold": "solve_break_even_threshold",
        "_solve_detailed_break_even_threshold": "solve_detailed_break_even_threshold",
    },
    "lease_level_sensitivity": {},
    "analyst": {
        "analyze_quick_acquisition_with_business_plan": "analyze_acquisition",
        "analyze_detailed_acquisition_with_business_plan": (
            "analyze_detailed_acquisition_with_projection"
        ),
    },
}
#: The two public solvers that became resolve-once wrappers around the search.
_NEW_WRAPPERS = {
    "break_even": {"solve_break_even_threshold", "solve_detailed_break_even_threshold"},
}

#: ``(level, module, name)`` imports D6.4 added and removed, per module.
_IMPORT_CHANGES = {
    "sensitivity": (
        {(2, "business_plan", "BusinessPlan"), (2, "business_plan", "resolve_business_plan"),
         (2, "engine.contracts", "OwnerCapitalSchedule")},
        set(),
    ),
    "break_even": (
        {(2, "business_plan", "BusinessPlan"), (2, "business_plan", "resolve_business_plan"),
         (2, "engine.contracts", "OwnerCapitalSchedule")},
        set(),
    ),
    "lease_level_sensitivity": (
        {(2, "business_plan", "BusinessPlan"), (2, "business_plan", "resolve_business_plan"),
         (2, "engine.contracts", "OwnerCapitalSchedule")},
        set(),
    ),
    "analyst": (
        {(2, "analysis", "analyze_quick_acquisition_with_business_plan"),
         (2, "analysis", "analyze_detailed_acquisition_with_business_plan"),
         (2, "business_plan", "BusinessPlan")},
        {(2, "engine", "analyze_acquisition"),
         (2, "engine", "analyze_detailed_acquisition_with_projection")},
    ),
}


def _strip_docstring(node: ast.Module | ast.ClassDef | ast.FunctionDef) -> None:
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        node.body = node.body[1:] or [ast.Pass()]


class _UndoThreading(ast.NodeTransformer):
    """Remove exactly what D6.4 adds: the threaded keyword arguments and
    parameters, the one resolution statement, and the renames. Docstrings and
    imports are set aside (imports are compared on their own)."""

    def __init__(self, renames: Mapping[str, str]) -> None:
        self.renames = renames

    def visit_Module(self, node: ast.Module) -> ast.Module:
        _strip_docstring(node)
        node.body = [s for s in node.body if not isinstance(s, (ast.Import, ast.ImportFrom))]
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        _strip_docstring(node)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        _strip_docstring(node)
        node.name = self.renames.get(node.name, node.name)
        kept = [
            (arg, default)
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
            if arg.arg not in _THREADED
        ]
        node.args.kwonlyargs = [arg for arg, _ in kept]
        node.args.kw_defaults = [default for _, default in kept]
        node.body = [s for s in node.body if not _is_resolution(s)] or [ast.Pass()]
        self.generic_visit(node)
        return node

    def visit_Call(self, node: ast.Call) -> ast.Call:
        self.generic_visit(node)
        node.keywords = [k for k in node.keywords if k.arg not in _THREADED]
        if isinstance(node.func, ast.Name):
            node.func.id = self.renames.get(node.func.id, node.func.id)
        return node


def _undone(source: str, label: str, *, current: bool) -> str:
    """The module with D6.4's threading removed. The new wrappers and the
    renames exist only in today's tree, so only today's side drops and renames;
    the ba804ca side is normalised (docstrings, imports) and nothing else."""

    tree = ast.parse(source)
    renames: Mapping[str, str] = {}
    if current:
        tree.body = [
            statement
            for statement in tree.body
            if not (
                isinstance(statement, ast.FunctionDef)
                and statement.name in _NEW_WRAPPERS.get(label, set())
            )
        ]
        renames = _RENAMES[label]
    return ast.dump(_UndoThreading(renames).visit(tree))


def _imports(source: str) -> set[tuple[int, str, str]]:
    return {
        (node.level, node.module or "", alias.name)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


@pytest.mark.parametrize("label", sorted(_MODULES))
def test_each_module_is_ba804ca_once_the_threading_is_undone(label: str) -> None:
    """Undo the threading and the module is AST-identical to ba804ca: every
    target list, metric extractor, tolerance, default bound, preset offset,
    validation order, bisection step and ``_meets_hurdle`` -- unchanged."""

    baseline = _baseline(_MODULES[label])
    current = _current(_MODULES[label])
    assert _undone(current, label, current=True) == _undone(baseline, label, current=False)


@pytest.mark.parametrize("label", sorted(_MODULES))
def test_each_module_changed_its_imports_by_exactly_the_threading(label: str) -> None:
    baseline, current = _imports(_baseline(_MODULES[label])), _imports(_current(_MODULES[label]))
    added, removed = _IMPORT_CHANGES[label]
    assert current - baseline == added
    assert baseline - current == removed


@pytest.mark.parametrize(
    "old, new",
    [
        # A search constant.
        ("_MAX_ITERATIONS = 100", "_MAX_ITERATIONS = 99"),
        # ``_meets_hurdle``: an undefined metric would start qualifying.
        (
            "return metric_value is not None and metric_value >= target",
            "return metric_value is None or metric_value >= target",
        ),
        # Inside the renamed Quick search body itself.
        (
            "return unfavorable_value, unfavorable_metric, BreakEvenStatus.SOLVED",
            "return favorable_value, unfavorable_metric, BreakEvenStatus.SOLVED",
        ),
    ],
    ids=["search-constant", "meets-hurdle", "renamed-search-body"],
)
def test_the_undo_is_not_vacuous(old: str, new: str) -> None:
    """The normaliser removes the threading and nothing else: a real change to
    break-even policy survives it."""

    current = _current(_MODULES["break_even"])
    mutated = current.replace(old, new, 1)
    assert mutated != current
    assert _undone(mutated, "break_even", current=True) != _undone(
        _baseline(_MODULES["break_even"]), "break_even", current=False
    )


@pytest.mark.parametrize(
    "wrapper, search, positional",
    [
        ("solve_break_even_threshold", "_solve_break_even_threshold", ["inputs"]),
        (
            "solve_detailed_break_even_threshold",
            "_solve_detailed_break_even_threshold",
            ["terms", "detailed_operating_inputs"],
        ),
    ],
)
def test_the_public_threshold_solvers_resolve_once_and_delegate_everything(
    wrapper: str, search: str, positional: list[str]
) -> None:
    function = next(
        f for f in _functions(ast.parse(_current(_MODULES["break_even"]))) if f.name == wrapper
    )
    resolution, delegation = function.body[1:]  # after the docstring
    assert _is_resolution(resolution)
    assert isinstance(delegation, ast.Return) and isinstance(delegation.value, ast.Call)
    call = delegation.value
    assert _callee(call) == search
    assert [ast.unparse(a) for a in call.args] == positional
    parameters = [a.arg for a in function.args.kwonlyargs if a.arg != "business_plan"]
    assert {k.arg: ast.unparse(k.value) for k in call.keywords} == {
        "owner_capital": "owner_capital",
        **{name: name for name in parameters},
    }


def test_business_plan_analysis_changed_only_its_docstring() -> None:
    def without_docstrings(source: str) -> str:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                _strip_docstring(node)
        return ast.dump(tree)

    assert without_docstrings(_current(_ENTRY_POINTS)) == without_docstrings(
        _baseline(_ENTRY_POINTS)
    )


def test_the_target_and_metric_surfaces_are_unchanged() -> None:
    from anchor.analysis import (
        DETAILED_SUPPORTED_ASSUMPTIONS,
        LEASE_LEVEL_SUPPORTED_ASSUMPTIONS,
        LEASE_LEVEL_SUPPORTED_METRICS,
        SUPPORTED_ASSUMPTIONS,
        SUPPORTED_METRICS,
    )
    from anchor.analysis.break_even import _ASSUMPTION_TOLERANCES, _METRIC_EXTRACTORS

    assert SUPPORTED_ASSUMPTIONS == (
        "purchase_price", "current_noi", "noi_growth", "exit_cap_rate", "ltv", "interest_rate",
    )
    assert DETAILED_SUPPORTED_ASSUMPTIONS == (
        "purchase_price", "exit_cap_rate", "ltv", "interest_rate",
    )
    assert LEASE_LEVEL_SUPPORTED_ASSUMPTIONS == (
        "purchase_price", "exit_cap_rate", "ltv", "interest_rate",
        "market_rent_psf", "renewal_probability", "expense_growth",
        "recoverable_expense_ratio",
    )
    # No D6.3 project-return metric joined the sensitivity surface.
    assert SUPPORTED_METRICS == LEASE_LEVEL_SUPPORTED_METRICS == (
        "levered_irr", "unlevered_irr", "equity_multiple", "headline_dscr", "exit_value",
    )
    assert set(_METRIC_EXTRACTORS) == {"levered_irr", "headline_dscr", "equity_multiple"}
    assert set(_ASSUMPTION_TOLERANCES) == {
        "purchase_price", "exit_cap_rate", "noi_growth", "interest_rate", "current_noi",
    }


# =============================================================================
# 3. Resolve once is exact
# =============================================================================


def test_no_secondary_analysis_target_is_the_hold_period() -> None:
    """The precondition for resolving once per invocation (gate Part D): every
    candidate shares the base hold, so the schedule resolved for it is the one
    each candidate would resolve for itself."""

    from anchor.analysis import (
        DETAILED_SUPPORTED_ASSUMPTIONS,
        LEASE_LEVEL_SUPPORTED_ASSUMPTIONS,
        SUPPORTED_ASSUMPTIONS,
    )
    from anchor.analysis.break_even import _ASSUMPTION_TOLERANCES

    for surface in (
        SUPPORTED_ASSUMPTIONS,
        DETAILED_SUPPORTED_ASSUMPTIONS,
        LEASE_LEVEL_SUPPORTED_ASSUMPTIONS,
        tuple(_ASSUMPTION_TOLERANCES),
    ):
        assert "hold_period" not in surface


def test_a_schedule_resolved_for_another_hold_is_refused_not_zipped() -> None:
    """Fail-closed if a future target ever varied the hold: the engine refuses
    a schedule resolved for a different hold instead of reusing it."""

    from anchor.business_plan import BusinessPlan, resolve_business_plan
    from anchor.contracts import AcquisitionInputs
    from anchor.engine import analyze_acquisition

    inputs = AcquisitionInputs(
        purchase_price=50_000_000.0, current_noi=2_500_000.0, occupancy=0.95,
        noi_growth=0.03, hold_period=7, exit_cap_rate=0.055, ltv=0.65,
        interest_rate=0.0525, amortization=30,
    )
    five_year = resolve_business_plan(BusinessPlan(), hold_period=5)
    with pytest.raises(ValueError, match="7-year hold requires 7 annual figures"):
        analyze_acquisition(inputs, owner_capital=five_year)
    assert dataclasses.replace(inputs, hold_period=5).hold_period == 5


# =============================================================================
# 4. The Business Plan boundary
# =============================================================================

#: Every module outside the package that imports ``anchor.business_plan``, and
#: exactly what it imports. The secondary modules name the contract and call the
#: one resolver; the AI Analyst only names the contract.
_BUSINESS_PLAN_IMPORTS = {
    "anchor/analysis/business_plan_analysis.py": {"BusinessPlan", "resolve_business_plan"},
    "anchor/analysis/sensitivity.py": {"BusinessPlan", "resolve_business_plan"},
    "anchor/analysis/break_even.py": {"BusinessPlan", "resolve_business_plan"},
    "anchor/analysis/lease_level_sensitivity.py": {"BusinessPlan", "resolve_business_plan"},
    "anchor/ai/analyst.py": {"BusinessPlan"},
}

#: What a plan item is made of. The plan-aware modules hold the plan opaquely.
_PLAN_ITEM_FIELDS = frozenset(
    {
        "capital_items",
        "owner_expense_items",
        "item_id",
        "description",
        "category",
        "month",
        "amount",
        "annual_amount",
        "first_year",
        "last_year",
    }
)


def _business_plan_imports(path: Path) -> set[str]:
    package = path.relative_to(_SRC_DIR).parts[:-1]
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(
                "*" for alias in node.names if alias.name.startswith("anchor.business_plan")
            )
        elif isinstance(node, ast.ImportFrom):
            base = list(package[: len(package) - node.level + 1]) if node.level else []
            module = ".".join([*base, *(node.module.split(".") if node.module else [])])
            if module == "anchor.business_plan" or module.startswith("anchor.business_plan."):
                names.update(alias.name for alias in node.names)
    return names


def test_only_the_enumerated_modules_import_the_business_plan() -> None:
    found = {
        path.relative_to(_SRC_DIR).as_posix(): names
        for path in sorted(_ANCHOR_DIR.rglob("*.py"))
        if "business_plan" != path.relative_to(_ANCHOR_DIR).parts[0]
        and (names := _business_plan_imports(path))
    }
    assert found == _BUSINESS_PLAN_IMPORTS


@pytest.mark.parametrize("label", sorted(_MODULES))
def test_no_plan_aware_module_reads_a_plan_item(label: str) -> None:
    tree = ast.parse(_current(_MODULES[label]))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes & _PLAN_ITEM_FIELDS


# =============================================================================
# 5. The ledger
# =============================================================================

_D6_4_PRODUCTION_FILES = frozenset(
    {
        "src/anchor/analysis/sensitivity.py",
        "src/anchor/analysis/break_even.py",
        "src/anchor/analysis/lease_level_sensitivity.py",
        "src/anchor/ai/analyst.py",
        # Docstring only -- see test_business_plan_analysis_changed_only_its_docstring.
        "src/anchor/analysis/business_plan_analysis.py",
    }
)

#: Named for the report: every one of these is inside the ledger's complement.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/analysis/contracts.py",
    "src/anchor/analysis/lease_level.py",
    "src/anchor/analysis/__init__.py",
    "src/anchor/ai/__init__.py",
    "src/anchor/ai/contracts.py",
    "src/anchor/ai/presentation.py",
    "src/anchor/ai/prompts.py",
    "src/anchor/ai/provider.py",
    "src/anchor/api.py",
    "src/anchor/deals",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "web",
)


def test_d6_4_changed_exactly_its_authorized_production_files() -> None:
    changed = set(_files_changed_since(_D6_3_MERGE, "src")) | set(
        _files_changed_since(_D6_3_MERGE, "web")
    )
    assert changed == _D6_4_PRODUCTION_FILES, (
        f"unexpected: {sorted(changed - _D6_4_PRODUCTION_FILES)}; "
        f"missing: {sorted(_D6_4_PRODUCTION_FILES - changed)}"
    )


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_d6_3(path: str) -> None:
    assert _files_changed_since(_D6_3_MERGE, path) == [], f"{path} changed at D6.4"
