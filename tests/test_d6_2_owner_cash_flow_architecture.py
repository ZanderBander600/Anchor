"""Phase 6 Gate D6.2 -- architecture guardrails for the owner cash-flow bridge.

Governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 2,
12, 13 and 20.

D6.2 is the first gate allowed to change engine *logic* since D4.5A, so the old
whole-file byte-identity guardrails (G33, G37) no longer describe the rule for
``engine/acquisition.py``. They are narrowed by exactly that file and replaced,
here, by claims that are stronger where it matters and remain fail-closed:

1. **Source regions.** Every byte of ``engine/acquisition.py`` outside an
   enumerated D6.2 surface -- four changed functions, two import statements and
   one new block of ten enumerated functions -- is identical to the pre-D6.2
   module (7e67cde). Exit value, disposition costs, net sale proceeds, the
   reserve, the TI/LC total, the legacy cash-flow builder, the Quick-only
   convenience path and ``analyze_detailed_acquisition`` are therefore
   provably untouched, including their comments and blank lines.
2. **The authorized changes are the ones D6.2 needed.** Inside the four
   changed functions, every capital-stack, debt, exit, reserve, TI/LC and
   DSCR/IRR call is the pre-D6.2 call verbatim.
3. **Reach.** Owner capital never appears in NOI, debt, exit or lender code,
   is subtracted once per series, and post-hold capital is never an operand.
4. **The bridge.** The engine and the Lease-Level bridge take the generic
   ``OwnerCapitalSchedule``; one module resolves a ``BusinessPlan``.
5. **The ledger.** D6.2 changed exactly its authorized production files.

``debt.py``, ``returns.py``, ``noi.py``, ``operating_projection.py`` and the
engine ``__init__.py`` stay under the unmodified byte-identity guardrails.

Every git query runs against a private copy of the index (protocol Section
11.2). Source text is compared CRLF-normalised to LF and nothing else.
"""

from __future__ import annotations

import ast
import collections
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
_ANCHOR_DIR = _SRC_DIR / "anchor"
_ENGINE_DIR = _ANCHOR_DIR / "engine"

#: ``main`` after D6.1, immediately before D6.2.
_D6_1_MERGE = "7e67cde"

_ACQUISITION = "src/anchor/engine/acquisition.py"
_LEASE_LEVEL = "src/anchor/analysis/lease_level.py"
_ENTRY_POINTS = "src/anchor/analysis/business_plan_analysis.py"

_GUARDRAIL_FAILURE = "engine/acquisition.py changed outside D6.2's authorized surface"

#: The pre-existing top-level regions D6.2 is authorized to change.
_AUTHORIZED_REGIONS = frozenset(
    {
        "def calculate_levered_cash_flows",
        "def analyze_acquisition_from_operating_projection",
        "def analyze_acquisition",
        "def analyze_detailed_acquisition_with_projection",
        "from .contracts",
        "from .returns",
    }
)

#: The one block D6.2 adds, in order, directly before
#: ``calculate_acquisition_cash_flows``.
_NEW_FUNCTIONS = (
    "calculate_owner_capital_schedule",
    "calculate_initial_equity_requirement",
    "calculate_unlevered_project_basis",
    "calculate_total_closing_uses",
    "calculate_total_closing_sources",
    "calculate_property_cash_flow_by_year",
    "calculate_unlevered_owner_cash_flow_by_year",
    "calculate_levered_owner_cash_flow_by_year",
    "calculate_unlevered_project_cash_flows",
    "calculate_owner_cash_flow_return_metrics",
)
_BLOCK_MARKER = "# Phase 6 Gate D6.2 -- the owner cash-flow chain"

_D6_2_RESULT_FIELDS = (
    "closing_project_capital",
    "project_capital_by_year",
    "post_hold_project_capital",
    "owner_expenses_by_year",
    "property_cash_flow_by_year",
    "unlevered_owner_cash_flow_by_year",
    "levered_owner_cash_flow_by_year",
    "total_closing_uses",
    "total_closing_sources",
)

#: Identifiers that carry owner-level (Business Plan) capital inside the engine.
_OWNER_CAPITAL_NAMES = frozenset(
    {
        "owner_capital",
        "owner_capital_schedule",
        "OwnerCapitalSchedule",
        "closing_project_capital",
        "project_capital_by_year",
        "project_capital",
        "owner_expenses_by_year",
        "owner_expenses",
        "post_hold_project_capital",
    }
)
_PROJECT_CAPITAL = frozenset({"project_capital_by_year", "project_capital"})
_OWNER_EXPENSES = frozenset({"owner_expenses_by_year", "owner_expenses"})


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
    return _lf(_git_bytes(["show", f"{_D6_1_MERGE}:{path}"]).decode("utf-8"))


def _current(path: str) -> str:
    return _lf((_PROJECT_ROOT / path).read_bytes().decode("utf-8"))


def _names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
    return names


def _top_level_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _calls(function: ast.AST) -> list[ast.Call]:
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    return sorted(calls, key=lambda call: (call.lineno, call.col_offset))


def _the_call(function: ast.AST, callee: str) -> ast.Call:
    matches = [call for call in _calls(function) if _callee(call) == callee]
    assert len(matches) == 1, f"{callee} is called {len(matches)} times"
    return matches[0]


def _keywords(call: ast.Call) -> dict[str, str]:
    return {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg}


# =============================================================================
# 1. Source regions -- nothing outside the enumerated surface moved
# =============================================================================


def _top_level_spans(source: str) -> dict[str, tuple[int, int]]:
    """0-based ``[first, end)`` line spans of each function and each relative
    ``from`` import, decorators included."""

    spans: dict[str, tuple[int, int]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            key = f"def {node.name}"
        elif isinstance(node, ast.ImportFrom):
            key = f"from {'.' * node.level}{node.module or ''}"
        else:
            continue
        assert key not in spans, f"{_GUARDRAIL_FAILURE}: {key} appears twice"
        first = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        assert node.end_lineno is not None
        spans[key] = (first - 1, node.end_lineno)
    return spans


def _with_placeholders(source: str, keys: frozenset[str]) -> str:
    """``source`` with each authorized region collapsed to one placeholder line."""

    lines = source.split("\n")
    spans = _top_level_spans(source)
    missing = keys - set(spans)
    assert not missing, f"{_GUARDRAIL_FAILURE}: authorized regions missing: {sorted(missing)}"
    for key in sorted(keys, key=lambda k: spans[k][0], reverse=True):
        first, end = spans[key]
        lines[first:end] = [f"<<{key}>>"]
    return "\n".join(lines)


def _without_d6_2_block(source: str) -> str:
    """``source`` with the D6.2 block removed, after proving the block holds the
    enumerated functions -- in order -- and otherwise only comments and blank
    lines. The block runs from its banner to ``calculate_acquisition_cash_flows``."""

    lines = source.split("\n")
    assert lines.count(_BLOCK_MARKER) == 1, f"{_GUARDRAIL_FAILURE}: the D6.2 block marker"
    start = lines.index(_BLOCK_MARKER) - 1
    assert lines[start].startswith("# ===="), f"{_GUARDRAIL_FAILURE}: the D6.2 banner"
    stop = _top_level_spans(source)["def calculate_acquisition_cash_flows"][0]
    assert start < stop, f"{_GUARDRAIL_FAILURE}: the D6.2 block is misplaced"

    block_lines = lines[start:stop]
    block = ast.parse("\n".join(block_lines))
    defined = [node.name for node in block.body if isinstance(node, ast.FunctionDef)]
    assert defined == list(_NEW_FUNCTIONS) and len(block.body) == len(defined), (
        f"{_GUARDRAIL_FAILURE}: the D6.2 block defines {defined}, not exactly "
        f"{list(_NEW_FUNCTIONS)}"
    )
    covered: set[int] = set()
    for node in block.body:
        assert node.end_lineno is not None
        covered.update(range(node.lineno - 1, node.end_lineno))
    for index, line in enumerate(block_lines):
        if index not in covered:
            assert line == "" or line.startswith("#"), (
                f"{_GUARDRAIL_FAILURE}: the D6.2 block carries {line!r} outside a function"
            )
    return "\n".join(lines[:start] + lines[stop:])


def _assert_only_authorized_changes(baseline: str, current: str) -> None:
    remainder = _with_placeholders(_without_d6_2_block(current), _AUTHORIZED_REGIONS)
    expected = _with_placeholders(baseline, _AUTHORIZED_REGIONS)
    assert remainder == expected, (
        f"{_GUARDRAIL_FAILURE}:\n"
        + "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                remainder.splitlines(keepends=True),
                "7e67cde",
                "current (authorized regions collapsed)",
                n=1,
            )
        )
    )


def test_acquisition_changed_only_inside_the_authorized_d6_2_surface() -> None:
    baseline = _baseline(_ACQUISITION)
    assert _BLOCK_MARKER not in baseline

    _assert_only_authorized_changes(baseline, _current(_ACQUISITION))


_TAMPERS = [
    pytest.param(
        "    exit_value = exit_noi / exit_cap_rate\n",
        "    exit_value = exit_noi / exit_cap_rate * 1.0\n",
        id="exit-value-formula",
    ),
    pytest.param(
        "    disposition_costs = exit_value * disposition_cost_pct\n",
        "    disposition_costs = exit_value * (disposition_cost_pct)\n",
        id="disposition-costs",
    ),
    pytest.param(
        "        ucf_y = noi_by_year[year - 1] - capex[year - 1] - operating_capital[year - 1]\n",
        "        ucf_y = noi_by_year[year - 1] - operating_capital[year - 1] - capex[year - 1]\n",
        id="legacy-unlevered-builder-regrouped",
    ),
    pytest.param(
        "# Phase 2E / Detailed Operating Model V2.1 Gate 3 -- final orchestration",
        "# Phase 2E -- final orchestration",
        id="comment-outside-the-surface",
    ),
    pytest.param(
        "    return analyze_detailed_acquisition_with_projection(terms, detailed_inputs).results",
        "    return analyze_detailed_acquisition_with_projection(\n"
        "        terms, detailed_inputs\n"
        "    ).results",
        id="pinned-detailed-wrapper",
    ),
    pytest.param(
        "def calculate_acquisition_cash_flows(",
        "def calculate_shadow_owner_cash_flow() -> None:\n"
        "    return None\n"
        "\n"
        "\n"
        "def calculate_acquisition_cash_flows(",
        id="unenumerated-function-in-the-block",
    ),
    pytest.param(None, "\n\ndef unrelated_helper() -> None:\n    return None\n", id="function-appended"),
]


@pytest.mark.parametrize(("old", "new"), _TAMPERS)
def test_the_source_region_guardrail_rejects_an_unauthorized_change(
    old: str | None, new: str
) -> None:
    """Self-test: the guardrail has teeth, in memory, on the real files."""

    baseline = _baseline(_ACQUISITION)
    current = _current(_ACQUISITION)
    if old is None:
        tampered = current + new
    else:
        assert current.count(old) == 1, old
        tampered = current.replace(old, new)

    with pytest.raises(AssertionError, match=_GUARDRAIL_FAILURE):
        _assert_only_authorized_changes(baseline, tampered)


def test_the_source_region_guardrail_accepts_crlf() -> None:
    current = _current(_ACQUISITION)
    _assert_only_authorized_changes(
        _baseline(_ACQUISITION), _lf(current.replace("\n", "\r\n"))
    )


# =============================================================================
# 2. Inside the authorized functions, only what D6.2 needed changed
# =============================================================================


def _base_and_current_functions() -> tuple[dict[str, ast.FunctionDef], dict[str, ast.FunctionDef]]:
    return (
        _top_level_functions(ast.parse(_baseline(_ACQUISITION))),
        _top_level_functions(ast.parse(_current(_ACQUISITION))),
    )


#: Calls whose source must be the pre-D6.2 call verbatim: the capital stack
#: (loan sizing), the debt schedule, exit value, disposition costs, net sale
#: proceeds, the reserve, the TI/LC total and DSCR/IRR/equity multiple.
_VERBATIM_ORCHESTRATOR_CALLS = (
    "calculate_capital_stack",
    "calculate_debt_schedule",
    "calculate_exit_value",
    "calculate_disposition_costs",
    "calculate_net_sale_proceeds",
    "calculate_capex_by_year",
    "calculate_operating_capital_by_year",
    "calculate_return_metrics",
)


def test_the_orchestrator_keeps_every_lender_exit_and_return_call_verbatim() -> None:
    baseline, current = _base_and_current_functions()
    name = "analyze_acquisition_from_operating_projection"
    base_fn, cur_fn = baseline[name], current[name]

    for callee in _VERBATIM_ORCHESTRATOR_CALLS:
        assert ast.unparse(_the_call(cur_fn, callee)) == ast.unparse(
            _the_call(base_fn, callee)
        ), f"{callee} is no longer called exactly as before D6.2"

    base_callees = {_callee(call) for call in _calls(base_fn)}
    cur_callees = {_callee(call) for call in _calls(cur_fn)}
    assert base_callees - cur_callees == {
        "calculate_unlevered_cash_flows",
        "calculate_owner_return_metrics",
    }
    assert cur_callees - base_callees == set(_NEW_FUNCTIONS)


def test_the_result_contract_changed_only_by_initial_equity_and_the_d6_2_fields() -> None:
    baseline, current = _base_and_current_functions()
    name = "analyze_acquisition_from_operating_projection"
    base_kw = _keywords(_the_call(baseline[name], "AcquisitionResults"))
    cur_kw = _keywords(_the_call(current[name], "AcquisitionResults"))

    assert set(cur_kw) == set(base_kw) | set(_D6_2_RESULT_FIELDS)
    for field, value in base_kw.items():
        if field == "initial_equity":
            # The Initial Equity Requirement: the capital stack's figure plus
            # closing project capital (calculate_initial_equity_requirement).
            assert value == "capital_stack.initial_equity"
            assert cur_kw[field] == "initial_equity"
        else:
            assert cur_kw[field] == value, field


def test_the_equity_cash_flow_builder_only_gained_the_two_owner_series() -> None:
    baseline, current = _base_and_current_functions()
    name = "calculate_levered_cash_flows"

    def parameters(function: ast.FunctionDef) -> list[tuple[str, str | None]]:
        args = function.args.kwonlyargs
        defaults = [None if d is None else ast.unparse(d) for d in function.args.kw_defaults]
        return list(zip((a.arg for a in args), defaults))

    assert parameters(current[name]) == parameters(baseline[name]) + [
        ("project_capital_by_year", "()"),
        ("owner_expenses_by_year", "()"),
    ]

    orchestrator = "analyze_acquisition_from_operating_projection"
    base_call = _keywords(_the_call(baseline[orchestrator], name))
    cur_call = _keywords(_the_call(current[orchestrator], name))
    assert set(cur_call) - set(base_call) == {"project_capital_by_year", "owner_expenses_by_year"}
    for keyword, value in base_call.items():
        expected = "initial_equity" if keyword == "initial_equity" else value
        assert cur_call[keyword] == expected, keyword


@pytest.mark.parametrize(
    "name", ["analyze_acquisition", "analyze_detailed_acquisition_with_projection"]
)
def test_the_mode_entry_points_only_pass_owner_capital_through(name: str) -> None:
    baseline, current = _base_and_current_functions()
    base_fn, cur_fn = baseline[name], current[name]

    assert [a.arg for a in cur_fn.args.args] == [a.arg for a in base_fn.args.args]
    assert [a.arg for a in base_fn.args.kwonlyargs] == []
    assert [a.arg for a in cur_fn.args.kwonlyargs] == ["owner_capital"]
    assert [_callee(call) for call in _calls(cur_fn)] == [
        _callee(call) for call in _calls(base_fn)
    ]

    engine = "analyze_acquisition_from_operating_projection"
    base_call, cur_call = _the_call(base_fn, engine), _the_call(cur_fn, engine)
    assert [ast.unparse(a) for a in cur_call.args] == [ast.unparse(a) for a in base_call.args]
    assert _keywords(base_call) == {}
    assert _keywords(cur_call) == {"owner_capital": "owner_capital"}


# =============================================================================
# 3. Reach -- below NOI only, once per series, post-hold never an operand
# =============================================================================


@pytest.mark.parametrize(
    "module", ["debt.py", "returns.py", "noi.py", "operating_projection.py", "__init__.py"]
)
def test_no_other_engine_module_names_owner_capital(module: str) -> None:
    leaked = _names(ast.parse((_ENGINE_DIR / module).read_text(encoding="utf-8")))
    assert not leaked & _OWNER_CAPITAL_NAMES, f"{module} names {sorted(leaked & _OWNER_CAPITAL_NAMES)}"


#: acquisition.py functions that are above, or beside, the owner layer.
_OWNER_CAPITAL_FREE_FUNCTIONS = (
    "calculate_exit_value",
    "calculate_disposition_costs",
    "calculate_net_sale_proceeds",
    "calculate_capex_by_year",
    "calculate_operating_capital_by_year",
    "calculate_unlevered_cash_flows",
    "calculate_acquisition_cash_flows",
    "calculate_property_cash_flow_by_year",
    "calculate_levered_owner_cash_flow_by_year",
    "calculate_unlevered_project_cash_flows",
    "calculate_total_closing_sources",
    "calculate_owner_cash_flow_return_metrics",
)


@pytest.mark.parametrize("name", _OWNER_CAPITAL_FREE_FUNCTIONS)
def test_noi_exit_reserve_and_leasing_code_never_sees_owner_capital(name: str) -> None:
    function = _top_level_functions(ast.parse(_current(_ACQUISITION)))[name]
    leaked = _names(function) & _OWNER_CAPITAL_NAMES
    assert not leaked, f"{name} references {sorted(leaked)}"


def _subtraction_sites(names: frozenset[str]) -> dict[str, int]:
    sites: dict[str, int] = {}
    for name, function in _top_level_functions(ast.parse(_current(_ACQUISITION))).items():
        count = sum(
            1
            for node in ast.walk(function)
            if isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Sub)
            and _names(node.right) & names
        )
        if count:
            sites[name] = count
    return sites


@pytest.mark.parametrize(
    "channel", [_PROJECT_CAPITAL, _OWNER_EXPENSES], ids=["project-capital", "owner-expenses"]
)
def test_each_owner_channel_is_subtracted_once_per_series(channel: frozenset[str]) -> None:
    """Once from the owner chain (Unlevered Owner Cash Flow) and once from each
    branch of the Equity Cash Flow -- never from Property Cash Flow, never from
    NOI, never twice (Section 20)."""

    assert _subtraction_sites(channel) == {
        "calculate_unlevered_owner_cash_flow_by_year": 1,
        "calculate_levered_cash_flows": 2,
    }


def test_the_reserve_and_ti_lc_are_subtracted_once_in_property_cash_flow() -> None:
    assert _subtraction_sites(frozenset({"capex_by_year", "capex"})) == {
        "calculate_unlevered_cash_flows": 2,
        "calculate_levered_cash_flows": 2,
        "calculate_property_cash_flow_by_year": 1,
    }
    assert _subtraction_sites(frozenset({"operating_capital_by_year", "operating_capital"})) == {
        "calculate_unlevered_cash_flows": 2,
        "calculate_levered_cash_flows": 2,
        "calculate_property_cash_flow_by_year": 1,
    }


def test_closing_capital_is_added_only_to_equity_the_basis_and_uses() -> None:
    sites: dict[str, int] = {}
    tree = ast.parse(_current(_ACQUISITION))
    for name, function in _top_level_functions(tree).items():
        for node in ast.walk(function):
            if isinstance(node, ast.BinOp) and "closing_project_capital" in _names(node.right):
                assert isinstance(node.op, ast.Add), f"{name} does not add closing capital"
                sites[name] = sites.get(name, 0) + 1

    assert sites == {
        "calculate_initial_equity_requirement": 1,
        "calculate_unlevered_project_basis": 1,
        "calculate_total_closing_uses": 1,
    }


def test_post_hold_capital_is_disclosed_and_never_an_operand() -> None:
    for source_file in sorted(_ENGINE_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(source_file.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.BinOp, ast.AugAssign, ast.Compare, ast.UnaryOp)):
                assert "post_hold_project_capital" not in _names(node), (
                    f"{source_file.name} computes with post-hold capital"
                )

    tree = ast.parse(_current(_ACQUISITION))
    references = [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Attribute) and node.attr == "post_hold_project_capital")
        or (isinstance(node, ast.Name) and node.id == "post_hold_project_capital")
    ]
    orchestrator = _top_level_functions(tree)["analyze_acquisition_from_operating_projection"]
    disclosure = _the_call(orchestrator, "AcquisitionResults")
    disclosed = next(k.value for k in disclosure.keywords if k.arg == "post_hold_project_capital")
    assert references == [disclosed], "post-hold capital is read somewhere besides its disclosure"


def test_the_unlevered_project_cash_flow_is_built_from_owner_cash_flow_only() -> None:
    function = _top_level_functions(ast.parse(_current(_ACQUISITION)))[
        "calculate_unlevered_project_cash_flows"
    ]
    names = _names(function)

    assert {"unlevered_owner_cash_flow_by_year", "unlevered_project_basis", "exit_value", "disposition_costs"} <= names
    assert not names & {
        "noi_by_year",
        "capex_by_year",
        "operating_capital_by_year",
        "annual_debt_service",
        *_OWNER_CAPITAL_NAMES,
    }
    source = ast.unparse(function)
    assert "unlevered_owner_cash_flow_by_year[hold_period - 1] + exit_value - disposition_costs" in source


def test_lender_metrics_read_noi_only() -> None:
    function = _top_level_functions(ast.parse(_current(_ACQUISITION)))[
        "calculate_owner_cash_flow_return_metrics"
    ]
    debt_yield = _the_call(function, "calculate_year_1_debt_yield")
    assert _keywords(debt_yield) == {"year_1_noi": "noi_by_year[0]", "loan_amount": "loan_amount"}
    # NOI reaches this function for the debt yield and nothing else.
    uses = [n for n in ast.walk(function) if isinstance(n, ast.Name) and n.id == "noi_by_year"]
    assert len(uses) == 1

    new_readers_of_noi = sorted(
        name
        for name, fn in _top_level_functions(ast.parse(_current(_ACQUISITION))).items()
        if name in _NEW_FUNCTIONS and "noi_by_year" in _names(fn)
    )
    assert new_readers_of_noi == [
        "calculate_owner_cash_flow_return_metrics",
        "calculate_property_cash_flow_by_year",
    ]


#: Business Plan vocabulary the engine must never name (Section 13).
_PLAN_VOCABULARY = frozenset(
    {
        "BusinessPlan",
        "CapitalPlanItem",
        "OwnerExpenseItem",
        "CapitalItemCategory",
        "OwnerExpenseCategory",
        "OwnerExpenseHoldTreatment",
        "resolve_business_plan",
        "business_plan",
        "item_id",
        "description",
        "category",
        "first_year",
        "last_year",
    }
)


@pytest.mark.parametrize("source_file", sorted(_ENGINE_DIR.glob("*.py")), ids=lambda p: p.name)
def test_the_engine_names_no_business_plan_concept(source_file: Path) -> None:
    names = _names(ast.parse(source_file.read_text(encoding="utf-8")))
    vocabulary = set(_PLAN_VOCABULARY)
    if source_file.name in ("acquisition.py", "contracts.py"):
        # ``debt.py`` legitimately counts loan months; the owner layer does not.
        vocabulary.add("month")
    assert not names & vocabulary, f"{source_file.name} names {sorted(names & vocabulary)}"


# =============================================================================
# 4. The bridge -- one module resolves a plan; the Lease-Level bridge passes through
# =============================================================================

_EXPECTED_ENTRY_POINTS = {
    "analyze_quick_acquisition_with_business_plan": ("analyze_acquisition", "inputs"),
    "analyze_detailed_acquisition_with_business_plan": (
        "analyze_detailed_acquisition_with_projection",
        "terms",
    ),
    "analyze_lease_level_acquisition_with_business_plan": (
        "analyze_lease_level_acquisition_with_projection",
        "terms",
    ),
}


def test_each_business_plan_entry_point_resolves_once_and_delegates_once() -> None:
    tree = ast.parse(_current(_ENTRY_POINTS))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert [f.name for f in functions] == list(_EXPECTED_ENTRY_POINTS)
    assert not [n for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign, ast.ClassDef))]

    for function in functions:
        entry_point, hold_owner = _EXPECTED_ENTRY_POINTS[function.name]
        statements = function.body[1:]  # after the docstring
        assert len(statements) == 1 and isinstance(statements[0], ast.Return), function.name
        delegated = statements[0].value
        assert isinstance(delegated, ast.Call) and _callee(delegated) == entry_point

        resolve = _the_call(function, "resolve_business_plan")
        assert [ast.unparse(a) for a in resolve.args] == ["business_plan"]
        assert _keywords(resolve) == {"hold_period": f"{hold_owner}.hold_period"}
        owner_capital = next(k.value for k in delegated.keywords if k.arg == "owner_capital")
        assert owner_capital is resolve, f"{function.name} passes something else as owner_capital"
        assert {_callee(c) for c in _calls(function)} == {entry_point, "resolve_business_plan"}

    for node in ast.walk(tree):
        assert not isinstance(node, (ast.BinOp, ast.AugAssign)), "the entry points compute"
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, (int, float)) or isinstance(node.value, bool)


def test_a_business_plan_is_resolved_in_exactly_one_module() -> None:
    resolvers = sorted(
        str(path.relative_to(_SRC_DIR)).replace("\\", "/")
        for path in _ANCHOR_DIR.rglob("*.py")
        if "business_plan" not in path.relative_to(_ANCHOR_DIR).parts[:1]
        and any(
            isinstance(node, ast.Call) and _callee(node) == "resolve_business_plan"
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    )
    assert resolvers == ["anchor/analysis/business_plan_analysis.py"]


def test_the_lease_level_bridge_only_passes_owner_capital_through() -> None:
    """Against the pre-D6.2 bridge: the same builder calls in the same order,
    one new keyword-only parameter, and that parameter handed to the shared
    engine as-is. The bridge still defines one function and computes nothing
    (D4.5B G7-G12)."""

    name = "analyze_lease_level_acquisition_with_projection"
    base_fn = _top_level_functions(ast.parse(_baseline(_LEASE_LEVEL)))[name]
    cur_fn = _top_level_functions(ast.parse(_current(_LEASE_LEVEL)))[name]

    assert [_callee(c) for c in _calls(cur_fn)] == [_callee(c) for c in _calls(base_fn)]
    assert [a.arg for a in cur_fn.args.args] == [a.arg for a in base_fn.args.args]
    assert [a.arg for a in cur_fn.args.kwonlyargs] == [
        a.arg for a in base_fn.args.kwonlyargs
    ] + ["owner_capital"]

    engine = "analyze_acquisition_from_operating_projection"
    base_call, cur_call = _the_call(base_fn, engine), _the_call(cur_fn, engine)
    assert [ast.unparse(a) for a in cur_call.args] == [ast.unparse(a) for a in base_call.args]
    assert _keywords(base_call) == {}
    assert _keywords(cur_call) == {"owner_capital": "owner_capital"}


# =============================================================================
# 5. The ledger -- D6.2 changed exactly its authorized production files
# =============================================================================

_D6_2_PRODUCTION_FILES = frozenset(
    {
        "src/anchor/engine/acquisition.py",
        "src/anchor/engine/contracts.py",
        "src/anchor/analysis/lease_level.py",
        "src/anchor/analysis/business_plan_analysis.py",
        "src/anchor/analysis/__init__.py",
        "src/anchor/ai/presentation.py",
    }
)


def test_d6_2_changed_exactly_its_authorized_production_files() -> None:
    """No debt, returns, NOI, leasing, sensitivity, break-even, API,
    persistence, fingerprint, prompt or frontend file moved since D6.1."""

    changed = set(_files_changed_since(_D6_1_MERGE, "src")) | set(
        _files_changed_since(_D6_1_MERGE, "web")
    )
    assert changed == _D6_2_PRODUCTION_FILES, (
        f"unexpected: {sorted(changed - _D6_2_PRODUCTION_FILES)}; "
        f"missing: {sorted(_D6_2_PRODUCTION_FILES - changed)}"
    )


def test_the_ledger_detects_a_real_difference() -> None:
    """The helper reports a file that genuinely changed and omits siblings that
    did not -- so the ledger above cannot pass vacuously."""

    engine = _files_changed_since(_D6_1_MERGE, "src/anchor/engine")
    assert engine == ["src/anchor/engine/acquisition.py", "src/anchor/engine/contracts.py"]
    assert collections.Counter(engine)["src/anchor/engine/debt.py"] == 0
