"""Phase 6 Gate D6.8 -- architecture guardrails for AI Business Plan grounding.

1. **Context inclusion.** Every ``AnalysisContext`` the analyst builds carries
   the caller's own plan by name, in all three modes; the Lease-Level arm
   requires it. Mutant self-test.
2. **One shared section.** The Business Plan and IRR-status sections are built
   once, by ``build_presentation_payload``, outside every mode arm.
3. **Deterministic authority.** The D6.8 presentation functions compute
   nothing -- the resolver probe's year index is the only arithmetic -- and
   read every D6 figure off ``results``. Mutant self-test.
4. **No reflection duplicate.** ``_format_results`` reads no D6 field.
5. **Grounding rules.** The no-calculation, no-value-attribution, capital
   channel, owner-expense, lender, post-hold, IRR, development and partnership
   rules are in the shipped prompt; "capital call" is only ever negated.
6. **Scope.** Deal fingerprints and every financial module are byte-identical
   to 7f52b9e; D6.8 changed exactly its authorized files, ``store.py`` only by
   the AI snapshot version and ``api.py`` only by one keyword.

Every git query runs against a private copy of the index (protocol 11.2).
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from anchor.ai import analyst
from anchor.ai.presentation import INTENTIONALLY_EXCLUDED_RESULT_FIELDS
from anchor.ai.prompts import build_system_prompt
from anchor.business_plan import BusinessPlan

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ANALYST = "src/anchor/ai/analyst.py"
_PRESENTATION = "src/anchor/ai/presentation.py"
_STORE = "src/anchor/deals/store.py"
_API = "src/anchor/api.py"
#: ``main`` after D6.5, immediately before D6.8.
_D6_5_MERGE = "7f52b9e"

_D6_FIELDS = frozenset(
    {
        "closing_project_capital",
        "project_capital_by_year",
        "post_hold_project_capital",
        "owner_expenses_by_year",
        "property_cash_flow_by_year",
        "unlevered_owner_cash_flow_by_year",
        "levered_owner_cash_flow_by_year",
        "total_closing_uses",
        "total_closing_sources",
        "net_additional_equity_requirement_by_year",
        "total_equity_invested",
        "total_cash_returned",
        "total_profit",
        "unlevered_irr_status",
        "levered_irr_status",
    }
)


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


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and _callee(n) == name]


def _flat(text: str) -> str:
    return " ".join(text.split())


# =============================================================================
# 1. Context inclusion
# =============================================================================

#: Each builder, and the generator that must hand it the plan.
_BUILDERS = {
    "build_analysis_context": "generate_ai_analysis",
    "build_detailed_analysis_context": "generate_detailed_ai_analysis",
    "build_lease_level_analysis_context": "generate_lease_level_ai_analysis",
}


def _passes_the_plan(call: ast.Call) -> bool:
    value = {keyword.arg: keyword.value for keyword in call.keywords}.get("business_plan")
    return isinstance(value, ast.Name) and value.id == "business_plan"


def _context_violations(source: str) -> list[str]:
    functions = _functions(ast.parse(source))
    violations: list[str] = []
    constructing = {name for name, f in functions.items() if _calls(f, "AnalysisContext")}
    if constructing != set(_BUILDERS):
        violations.append(f"AnalysisContext is built by {sorted(constructing)}")
    for builder, generator in _BUILDERS.items():
        function = functions.get(builder)
        if function is None:
            violations.append(f"{builder} is missing")
            continue
        if "business_plan" not in {arg.arg for arg in function.args.kwonlyargs}:
            violations.append(f"{builder} takes no keyword-only business_plan")
        for call in _calls(function, "AnalysisContext"):
            if not _passes_the_plan(call):
                violations.append(f"{builder} builds an AnalysisContext without its own plan")
        handed = _calls(functions.get(generator, ast.Module(body=[], type_ignores=[])), builder)
        if len(handed) != 1 or not _passes_the_plan(handed[0]):
            violations.append(f"{generator} does not hand its plan to {builder}")
    return violations


def test_every_analysis_context_carries_the_callers_own_plan() -> None:
    assert _context_violations(_current(_ANALYST)) == []


@pytest.mark.parametrize(
    "old, new, expected",
    [
        (
            "        deal_context=deal_context,\n        business_plan=business_plan,\n    )\n\n\n"
            "def build_detailed_analysis_context(",
            "        deal_context=deal_context,\n    )\n\n\ndef build_detailed_analysis_context(",
            "build_analysis_context builds an AnalysisContext without its own plan",
        ),
        (
            "        deal_context=deal_context,\n        business_plan=business_plan,\n    )\n"
            "    return _generate_from_context(context, provider=provider)\n\n\n"
            "def generate_detailed_ai_analysis(",
            "        deal_context=deal_context,\n    )\n"
            "    return _generate_from_context(context, provider=provider)\n\n\n"
            "def generate_detailed_ai_analysis(",
            "generate_ai_analysis does not hand its plan to build_analysis_context",
        ),
        (
            "    deal_context: str | None = None,\n    business_plan: BusinessPlan,\n"
            ") -> AnalysisContext:",
            "    deal_context: str | None = None,\n) -> AnalysisContext:",
            "build_lease_level_analysis_context takes no keyword-only business_plan",
        ),
    ],
    ids=["quick-context-drops-its-plan", "generator-drops-its-plan", "lease-level-arm-loses-its-plan"],
)
def test_the_context_guard_rejects_a_real_omission(old: str, new: str, expected: str) -> None:
    source = _current(_ANALYST)
    assert old in source, "the mutation site no longer exists"
    mutated = source.replace(old, new, 1)
    ast.parse(mutated)
    assert expected in _context_violations(mutated)


def test_the_lease_level_arm_requires_its_plan_and_the_others_default_only_to_the_empty_plan() -> None:
    for name in ("build_lease_level_analysis_context", "generate_lease_level_ai_analysis"):
        parameter = inspect.signature(getattr(analyst, name)).parameters["business_plan"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is inspect.Parameter.empty, name
    for name in (
        "build_analysis_context",
        "build_detailed_analysis_context",
        "generate_ai_analysis",
        "generate_detailed_ai_analysis",
    ):
        parameter = inspect.signature(getattr(analyst, name)).parameters["business_plan"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default == BusinessPlan(), name


# =============================================================================
# 2. One shared section
# =============================================================================


def test_the_grounding_is_built_once_for_every_mode_outside_the_mode_arms() -> None:
    tree = ast.parse(_current(_PRESENTATION))
    functions = _functions(tree)

    for builder in ("_format_business_plan_section", "_format_irr_status_section"):
        callers = {name for name, f in functions.items() if _calls(f, builder)}
        assert callers == {"build_presentation_payload"}, builder
        payload_builder = functions["build_presentation_payload"]
        for match in (n for n in ast.walk(payload_builder) if isinstance(n, ast.Match)):
            assert not _calls(match, builder), f"{builder} is called inside the mode dispatch"
    for arm in ("_add_quick_sections", "_add_detailed_sections", "_add_lease_level_sections"):
        names = {n.attr for n in ast.walk(functions[arm]) if isinstance(n, ast.Attribute)}
        assert "business_plan" not in names, arm


# =============================================================================
# 3. Deterministic authority
# =============================================================================

#: The D6.8 presentation functions. Only the resolver probe may do arithmetic,
#: and only to turn a bucket index into a year label.
_D6_8_FUNCTIONS = {
    "_acquisition_assumptions": [],
    "_capital_item_timing": ["placed.project_capital_by_year.index(1.0) + 1"],
    "_format_capital_item": [],
    "_format_owner_expense_item": [],
    "_business_plan_section_applies": [],
    "_format_business_plan_section": [],
    "_irr_status_section_applies": [],
    "_format_irr_status": [],
    "_format_irr_status_section": [],
}
_AGGREGATES = {"sum", "fsum", "min", "max", "abs", "round", "mean", "fmean"}


def _computation_violations(source: str) -> list[str]:
    functions = _functions(ast.parse(source))
    violations: list[str] = []
    for name, allowed in _D6_8_FUNCTIONS.items():
        function = functions.get(name)
        if function is None:
            violations.append(f"{name} is missing")
            continue
        # The body only: a ``A | B`` return annotation is a type, not arithmetic.
        body = [node for statement in function.body for node in ast.walk(statement)]
        arithmetic = [
            ast.unparse(node)
            for node in body
            if isinstance(node, (ast.BinOp, ast.AugAssign, ast.UnaryOp))
            and not (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not))
        ]
        if arithmetic != allowed:
            violations.append(f"{name} computes {arithmetic}")
        aggregates = {_callee(n) for n in body if isinstance(n, ast.Call)} & _AGGREGATES
        if aggregates:
            violations.append(f"{name} aggregates with {sorted(aggregates)}")
    read = {
        node.attr
        for name in ("_format_business_plan_section", "_format_irr_status_section")
        for node in ast.walk(functions.get(name, ast.Module(body=[], type_ignores=[])))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "results"
    }
    missing = _D6_FIELDS - read
    if missing:
        violations.append(f"the curated section does not read {sorted(missing)} off results")
    return violations


def test_the_grounding_computes_nothing_and_reads_every_d6_figure_off_results() -> None:
    assert _computation_violations(_current(_PRESENTATION)) == []


@pytest.mark.parametrize(
    "old, new, expected",
    [
        (
            '"total_profit": format_metric_value("total_profit", results.total_profit),',
            '"total_profit": format_metric_value(\n'
            '                "total_profit", results.total_cash_returned - results.total_equity_invested\n'
            "            ),",
            "_format_business_plan_section computes",
        ),
        (
            '            "project_capital_by_year": _format_tuple(\n'
            '                "project_capital_by_year", results.project_capital_by_year\n'
            "            ),",
            '            "project_capital_by_year": _format_tuple(\n'
            '                "project_capital_by_year", results.capex_by_year\n'
            "            ),",
            "does not read ['project_capital_by_year'] off results",
        ),
        (
            '    return {\n        "description": item.description,\n        "category": item.category.value,\n'
            '        "model_month": item.month,',
            '    return {\n        "total": sum([item.amount]),\n        "description": item.description,\n'
            '        "category": item.category.value,\n        "model_month": item.month,',
            "_format_capital_item aggregates with ['sum']",
        ),
    ],
    ids=["profit-recomputed", "reserve-shown-as-project-capital", "items-summed"],
)
def test_the_computation_guard_rejects_a_real_mutant(old: str, new: str, expected: str) -> None:
    source = _current(_PRESENTATION)
    assert old in source, "the mutation site no longer exists"
    mutated = source.replace(old, new, 1)
    ast.parse(mutated)
    assert any(expected in violation for violation in _computation_violations(mutated))


# =============================================================================
# 4. No reflection duplicate
# =============================================================================


def test_generic_reflection_never_duplicates_a_curated_field() -> None:
    function = _functions(ast.parse(_current(_PRESENTATION)))["_format_results"]
    read = {
        node.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "results"
    }
    assert not read & _D6_FIELDS
    assert INTENTIONALLY_EXCLUDED_RESULT_FIELDS == _D6_FIELDS


# =============================================================================
# 5. Grounding rules
# =============================================================================

_REQUIRED_RULE_TEXT = {
    "no calculation": (
        "Use the deterministic values provided. Do not calculate, recompute, estimate or "
        "derive any financial metric or Business Plan total yourself"
    ),
    "no value attribution": "Capital spend is not evidence of value creation by itself.",
    "capital channels": "Keep the capital channels separate and name the one you mean",
    "project capital is not reserve or TI/LC": "Never call Project Capital a reserve, TI or LC",
    "no combined figure": "never quote a combined capital figure -- Anchor supplies none",
    "owner expenses": "They are not property operating expenses, not the property management fee",
    "closing capital is not loan-funded": "It does not increase the acquisition loan and is not financed by it",
    "future capital insulation": "never that lender metrics fall",
    "post-hold disclosure": "It is disclosure only",
    "annual net equity": "It is annual and net",
    "lender insulation": "never say the plan lowers DSCR or debt yield",
    "no development": "construction draw schedule, construction loan, loan-to-cost, retainage, contingency",
    "no partnership": "LP or GP contributions, a waterfall, a preferred return, a promote, capital calls",
    "model month": "A model month is an index, not a calendar date.",
    "no alternative irr": "never select one of several possible roots",
    "no has-no-irr": 'never say the deal "has no IRR"',
}


@pytest.mark.parametrize("rule", sorted(_REQUIRED_RULE_TEXT))
def test_the_prompt_carries_each_grounding_rule(rule: str) -> None:
    assert _REQUIRED_RULE_TEXT[rule] in _flat(build_system_prompt())


def test_the_new_rule_blocks_are_numbered_once_each() -> None:
    prompt = build_system_prompt()
    numbers = re.findall(r"^(\d+[a-z]?)\. ", prompt, re.M)
    assert len(numbers) == len(set(numbers))
    assert [n for n in numbers if n.isdigit() and 37 <= int(n) <= 54] == [str(n) for n in range(37, 55)]
    assert "BUSINESS PLAN & CAPITAL ECONOMICS RULES" in prompt
    assert "IRR STATUS RULES" in prompt


def test_capital_call_is_never_used_as_a_label() -> None:
    """Every sentence that says "capital call" is a prohibition."""

    negation = re.compile(r"\b(never|not|no|nor)\b", re.IGNORECASE)
    prose = _flat(build_system_prompt())
    uses = [s for s in re.split(r"(?<=[.;:])\s+", prose) if "capital call" in s.lower()]
    assert uses, "the prohibition itself must be present"
    assert [s for s in uses if not negation.search(s)] == []


# =============================================================================
# 6. Scope
# =============================================================================

_D6_8_PRODUCTION_FILES = frozenset(
    {
        "src/anchor/ai/analyst.py",
        "src/anchor/ai/contracts.py",
        "src/anchor/ai/presentation.py",
        "src/anchor/ai/prompts.py",
        "src/anchor/api.py",
        "src/anchor/deals/store.py",
    }
)

#: Financial truth and state D6.8 must not touch.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/leasing",
    "src/anchor/analysis",
    "src/anchor/business_plan",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/deals/fingerprint.py",
    "src/anchor/deals/contracts.py",
    "src/anchor/deals/__init__.py",
    "src/anchor/ai/__init__.py",
    "src/anchor/ai/provider.py",
    "web",
)


def test_d6_8_changed_exactly_its_authorized_production_files() -> None:
    changed = set(_files_changed_since(_D6_5_MERGE, "src")) | set(
        _files_changed_since(_D6_5_MERGE, "web")
    )
    assert changed == _D6_8_PRODUCTION_FILES, (
        f"unexpected: {sorted(changed - _D6_8_PRODUCTION_FILES)}; "
        f"missing: {sorted(_D6_8_PRODUCTION_FILES - changed)}"
    )


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_d6_5(path: str) -> None:
    assert _files_changed_since(_D6_5_MERGE, path) == [], f"{path} changed at D6.8"


def _without_the_ai_version(source: str) -> tuple[str, list[int]]:
    tree = ast.parse(source)
    values: list[int] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and [ast.unparse(t) for t in node.targets] == ["_AI_SNAPSHOT_SCHEMA_VERSION"]
            and isinstance(node.value, ast.Constant)
        ):
            values.append(node.value.value)
            node.value = ast.Constant(None)
    return ast.dump(tree), values


def test_the_store_changed_only_its_ai_snapshot_version() -> None:
    current, (current_version,) = _without_the_ai_version(_current(_STORE))
    baseline, (baseline_version,) = _without_the_ai_version(_at(_D6_5_MERGE, _STORE))
    assert current == baseline
    assert current_version == baseline_version + 1


def test_the_api_changed_only_by_handing_the_lease_level_ai_arm_its_plan() -> None:
    tree = ast.parse(_current(_API))
    (call,) = _calls(_functions(tree)["_ai_analysis_lease_level"], "generate_lease_level_ai_analysis")
    assert _passes_the_plan(call)
    call.keywords = [keyword for keyword in call.keywords if keyword.arg != "business_plan"]
    assert ast.dump(tree) == ast.dump(ast.parse(_at(_D6_5_MERGE, _API)))
