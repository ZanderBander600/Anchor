"""Architecture guardrails for the Phase 6 ``anchor.business_plan`` layer.

Gate D6.1, governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md``
Section 13. The dependency direction is::

    anchor.business_plan  ->  anchor.engine.contracts

and never the reverse. The engine will consume only the resolved
``OwnerCapitalSchedule``; it must never learn what a plan item, identifier,
description, category or model month is.

D6.1 was **unwired**: no acquisition-analysis path consumed a Business Plan,
so no D5 financial output could move. D6.2 wires it, and narrows the "unwired"
and "unchanged" clauses below by exactly what its own scope requires: one
module outside the package imports the plan
(``anchor/analysis/business_plan_analysis.py``), the engine and the
Lease-Level bridge take the resolved ``OwnerCapitalSchedule`` -- never a
plan -- and ``engine/contracts.py`` gains the enumerated D6.2
``AcquisitionResults`` fields. ``tests/test_d6_2_owner_cash_flow_architecture.py``
holds the D6.2-specific claims.

Mirrors ``test_leasing_architecture.py``: AST-parsed import graphs rather than
runtime imports, plus fresh-interpreter checks. Every git query runs against a
private copy of the index (protocol Section 11.2), so nothing here writes the
developer's index.
"""

from __future__ import annotations

import ast
import difflib
import inspect
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
_ANCHOR_DIR = _SRC_DIR / "anchor"
_BUSINESS_PLAN_DIR = _ANCHOR_DIR / "business_plan"
_ENGINE_CONTRACTS = "src/anchor/engine/contracts.py"

#: ``main`` immediately before D6.1 -- the ratified D6 conventions merge.
_D6_BASE_COMMIT = "908499c"
#: The baselines of the two pre-existing whole-engine byte-identity guardrails
#: (G33 in ``test_analysis_d4_5b_architecture.py``, G37 in
#: ``test_analysis_d4_6b_architecture.py``), which D6.1 narrows by exactly
#: ``engine/contracts.py`` and which the additive-only claim below backs.
_D4_5A_COMMIT = "964c9a7"
_D4_6A_COMMIT = "15e910d"

#: The D5 production financial paths D6.1 must leave untouched (gate
#: specification Part W). ``src/anchor/engine`` as a whole is here except
#: ``contracts.py``, which is held to the stronger additive-only claim below.
#:
#: **Narrowed at D6.2** by exactly its authorized production files --
#: ``engine/acquisition.py``, ``analysis/lease_level.py``, the new
#: ``analysis/business_plan_analysis.py``, ``analysis/__init__.py`` and
#: ``ai/presentation.py`` -- each held to its own, more specific claim in
#: ``tests/test_d6_2_owner_cash_flow_architecture.py``, whose ledger pins the
#: complete D6.2 file set. Every path still listed is byte-identical to the D6
#: base, including sensitivity, break-even, persistence, the API and the web.
_UNCHANGED_FINANCIAL_PATHS = (
    "src/anchor/engine/__init__.py",
    "src/anchor/engine/returns.py",
    "src/anchor/engine/debt.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/operating_projection.py",
    "src/anchor/leasing",
    "src/anchor/analysis/contracts.py",
    "src/anchor/analysis/sensitivity.py",
    "src/anchor/analysis/break_even.py",
    "src/anchor/analysis/lease_level_sensitivity.py",
    "src/anchor/ai/__init__.py",
    "src/anchor/ai/analyst.py",
    "src/anchor/ai/contracts.py",
    "src/anchor/ai/prompts.py",
    "src/anchor/ai/provider.py",
    "src/anchor/deals",
    "src/anchor/api.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "web",
)


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _imported_module_names(source_file: Path) -> list[str]:
    """Absolute and relative import targets declared in one module, relative
    ones resolved against the module's own package."""

    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    package_parts = source_file.resolve().relative_to(_SRC_DIR).parts[:-1]

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(package_parts)
                if node.level > 1:
                    base = base[: -(node.level - 1)]
                names.append(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                names.append(node.module)
    return names


def _referenced_names(node: ast.AST) -> set[str]:
    """Every identifier and attribute a node references (docstrings excluded)."""

    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            names.add(child.target.id)
    return names


def _git_bytes(arguments: list[str]) -> bytes:
    """One read-only git query against a private copy of the index, returning
    git's output undecoded and untranslated."""

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


def _git(arguments: list[str]) -> str:
    """One read-only git query against a private copy of the index."""

    return _git_bytes(arguments).decode("utf-8")


def _files_changed_since(commit: str, repo_relative: str) -> list[str]:
    """Tracked paths differing from ``commit`` plus untracked, unignored
    paths -- the same two questions G37 asks."""

    tracked = _git(["diff", "--name-only", commit, "--", repo_relative])
    untracked = _git(["ls-files", "--others", "--exclude-standard", "--", repo_relative])
    return sorted(
        {line.strip() for line in (*tracked.splitlines(), *untracked.splitlines()) if line.strip()}
    )


def _fresh_interpreter(statement: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    parts = [str(_SRC_DIR)]
    if existing := environment.get("PYTHONPATH"):
        parts.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(parts)
    return subprocess.run(
        [sys.executable, "-c", statement], capture_output=True, env=environment
    )


# =============================================================================
# 1. anchor.business_plan may depend only on the generic engine contracts
# =============================================================================


def test_business_plan_package_has_the_expected_modules() -> None:
    assert [path.name for path in _python_files(_BUSINESS_PLAN_DIR)] == [
        "__init__.py",
        "contracts.py",
        "resolver.py",
        "validation.py",
    ]


def test_business_plan_imports_only_stdlib_its_own_modules_and_engine_contracts() -> None:
    for source_file in _python_files(_BUSINESS_PLAN_DIR):
        for name in _imported_module_names(source_file):
            if not name.startswith("anchor"):
                continue
            assert name.startswith("anchor.business_plan") or name == "anchor.engine.contracts", (
                f"{source_file.name} imports {name}; anchor.business_plan may import "
                "only its own modules and anchor.engine.contracts"
            )


def test_business_plan_imports_no_external_package() -> None:
    """Pure domain logic: standard library only."""

    stdlib = sys.stdlib_module_names
    for source_file in _python_files(_BUSINESS_PLAN_DIR):
        for name in _imported_module_names(source_file):
            if name.startswith("anchor"):
                continue
            assert name.split(".")[0] in stdlib, f"{source_file.name} imports {name}"


def test_only_the_resolver_imports_the_engine_contract() -> None:
    """Contracts and validation are engine-free vocabulary; the resolver is
    the one bridge to the engine contract."""

    importers = sorted(
        source_file.name
        for source_file in _python_files(_BUSINESS_PLAN_DIR)
        if "anchor.engine.contracts" in _imported_module_names(source_file)
    )
    assert importers == ["resolver.py"]


# =============================================================================
# 2 / 3. Nothing else depends on anchor.business_plan -- engine and leasing
#        included
# =============================================================================


def test_exactly_one_module_outside_the_package_imports_anchor_business_plan() -> None:
    """Stated over the whole source tree, so an importer cannot appear in a
    package nobody thought to list. This covers acquisition, debt, returns,
    the rest of the engine, ``anchor.leasing``, analysis, deals, AI, the API
    and every top-level module.

    **Narrowed at D6.2 -- by exactly one named file.** D6.2 wires the plan into
    analysis, and it does so in one place:
    ``anchor/analysis/business_plan_analysis.py`` resolves a plan and hands the
    generic ``OwnerCapitalSchedule`` to a mode's entry point. The engine, the
    Lease-Level bridge, leasing, sensitivity, break-even, deals, AI and the API
    still import nothing from ``anchor.business_plan`` (D6.4 and D6.5 own the
    next consumers)."""

    importers = sorted(
        str(source_file.relative_to(_SRC_DIR)).replace("\\", "/")
        for source_file in _python_files(_ANCHOR_DIR)
        if _BUSINESS_PLAN_DIR not in source_file.parents
        and any(
            name == "anchor.business_plan" or name.startswith("anchor.business_plan.")
            for name in _imported_module_names(source_file)
        )
    )

    assert importers == ["anchor/analysis/business_plan_analysis.py"], (
        f"anchor.business_plan is imported by {importers}"
    )


def test_importing_the_engine_and_leasing_does_not_pull_in_the_business_plan() -> None:
    """**Narrowed at D6.2.** ``anchor.analysis`` now carries the Business Plan
    entry points, so importing it legitimately loads the plan package; that
    half is dropped and asserted positively below. The engine and the leasing
    layer -- the two the conventions name (Section 13) -- still must not."""

    completed = _fresh_interpreter(
        "import sys; "
        "import anchor.engine, anchor.engine.acquisition, anchor.engine.debt, "
        "anchor.engine.returns, anchor.engine.contracts, anchor.leasing; "
        "assert 'anchor.business_plan' not in sys.modules, "
        "sorted(m for m in sys.modules if m.startswith('anchor.business_plan'))"
    )
    assert completed.returncode == 0, completed.stderr.decode()


def test_the_business_plan_entry_points_depend_on_the_plan_and_the_engine() -> None:
    """The positive half: the D6.2 entry-point module is a real bridge, pulling
    in both the plan package and the shared engine."""

    completed = _fresh_interpreter(
        "import sys; import anchor.analysis.business_plan_analysis; "
        "assert 'anchor.business_plan' in sys.modules; "
        "assert 'anchor.engine.acquisition' in sys.modules"
    )
    assert completed.returncode == 0, completed.stderr.decode()


# =============================================================================
# OwnerCapitalSchedule is a generic engine contract
# =============================================================================


#: Business Plan vocabulary the engine contract must never name.
_BUSINESS_PLAN_NAMES = frozenset(
    {
        "BusinessPlan",
        "CapitalPlanItem",
        "OwnerExpenseItem",
        "CapitalItemCategory",
        "OwnerExpenseCategory",
        "OwnerExpenseHoldTreatment",
        "item_id",
        "description",
        "category",
        "month",
        "first_year",
        "last_year",
        "business_plan",
    }
)


def _class_node(source: str, class_name: str) -> ast.ClassDef:
    return next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )


def test_owner_capital_schedule_lives_in_the_engine_contracts_module() -> None:
    from anchor.engine.contracts import OwnerCapitalSchedule

    assert OwnerCapitalSchedule.__module__ == "anchor.engine.contracts"
    assert list(OwnerCapitalSchedule.__dataclass_fields__) == [
        "closing_project_capital",
        "project_capital_by_year",
        "owner_expenses_by_year",
        "post_hold_project_capital",
    ]


def test_owner_capital_schedule_names_no_business_plan_concept() -> None:
    node = _class_node(
        (_PROJECT_ROOT / _ENGINE_CONTRACTS).read_text(encoding="utf-8"),
        "OwnerCapitalSchedule",
    )
    leaked = _referenced_names(node) & _BUSINESS_PLAN_NAMES
    assert not leaked, f"OwnerCapitalSchedule references {sorted(leaked)}"


def test_the_business_plan_package_does_not_re_export_the_engine_contract() -> None:
    import anchor.business_plan as business_plan

    assert "OwnerCapitalSchedule" not in business_plan.__all__


# =============================================================================
# 4. The Business Plan is not wired into acquisition analysis yet
# =============================================================================


def test_owner_capital_schedule_is_referenced_only_by_its_producer_and_consumers() -> None:
    """**Narrowed at D6.2 -- by exactly two named files.** The contract is
    produced by the resolver and consumed by the engine's acquisition module;
    the Lease-Level bridge names it only to pass it through. No debt, returns,
    NOI, sensitivity, break-even, API, AI or persistence module names it."""

    def mentions(source_file: Path) -> bool:
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        names = _referenced_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.alias):
                names.add(node.asname or node.name)
        return "OwnerCapitalSchedule" in names

    referencing = sorted(
        str(source_file.relative_to(_SRC_DIR)).replace("\\", "/")
        for source_file in _python_files(_ANCHOR_DIR)
        if mentions(source_file)
    )

    assert referencing == [
        "anchor/analysis/lease_level.py",
        "anchor/business_plan/resolver.py",
        "anchor/engine/acquisition.py",
        "anchor/engine/contracts.py",
    ]


#: The D6.2 owner-capital surface: every engine or bridge entry point that takes
#: the resolved schedule, and nothing else. Each takes it keyword-only, named
#: ``owner_capital``, defaulting to ``None`` (the empty plan).
_OWNER_CAPITAL_ENTRY_POINTS = frozenset(
    {
        "anchor.engine.acquisition.analyze_acquisition_from_operating_projection",
        "anchor.engine.acquisition.analyze_acquisition",
        "anchor.engine.acquisition.analyze_detailed_acquisition_with_projection",
        "anchor.analysis.lease_level.analyze_lease_level_acquisition_with_projection",
    }
)


def test_the_engine_and_the_bridge_take_owner_capital_never_a_business_plan() -> None:
    """**Succeeds D6.1's "unwired" test at D6.2 -- and is not weakened.**

    D6.1 asserted no entry point took either name. D6.2 wires exactly one of
    them, at exactly the enumerated entry points: the generic, resolved
    ``OwnerCapitalSchedule``. The other half is unchanged -- no engine or
    Lease-Level bridge function accepts a ``BusinessPlan``, so plan items never
    reach either. ``analyze_detailed_acquisition`` keeps its pinned
    ``(terms, detailed_inputs)`` signature and takes neither."""

    from anchor.analysis import lease_level
    from anchor.engine import acquisition

    assert list(
        inspect.signature(
            acquisition.analyze_acquisition_from_operating_projection
        ).parameters
    ) == ["operating_projection", "terms", "operating_capital", "owner_capital"]

    takers: set[str] = set()
    for module in (acquisition, lease_level):
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ != module.__name__ or not name.startswith("analyze"):
                continue
            for parameter_name, parameter in inspect.signature(function).parameters.items():
                assert "business_plan" not in parameter_name, (
                    f"{module.__name__}.{name} takes {parameter_name!r}; the engine "
                    "and the bridge consume only the resolved OwnerCapitalSchedule"
                )
                if "owner_capital" in parameter_name:
                    assert parameter_name == "owner_capital"
                    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
                    assert parameter.default is None
                    takers.add(f"{module.__name__}.{name}")

    assert takers == _OWNER_CAPITAL_ENTRY_POINTS
    assert list(inspect.signature(acquisition.analyze_detailed_acquisition).parameters) == [
        "terms",
        "detailed_inputs",
    ]


def test_the_business_plan_entry_points_require_the_plan() -> None:
    """The three D6.2 Business Plan entry points take ``business_plan`` as a
    required keyword -- a plan is never silently defaulted there. A caller
    with no plan uses the mode's own entry point, which is the empty plan."""

    from anchor.analysis import business_plan_analysis

    functions = {
        name: function
        for name, function in inspect.getmembers(business_plan_analysis, inspect.isfunction)
        if function.__module__ == business_plan_analysis.__name__
    }
    assert sorted(functions) == [
        "analyze_detailed_acquisition_with_business_plan",
        "analyze_lease_level_acquisition_with_business_plan",
        "analyze_quick_acquisition_with_business_plan",
    ]
    for name, function in functions.items():
        parameter = inspect.signature(function).parameters["business_plan"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is inspect.Parameter.empty, name


# =============================================================================
# 5 / 6. No D5 production financial path, and no frontend file, changed
# =============================================================================


@pytest.mark.parametrize("path", _UNCHANGED_FINANCIAL_PATHS)
def test_d5_financial_paths_are_unchanged_since_the_d6_base(path: str) -> None:
    assert _files_changed_since(_D6_BASE_COMMIT, path) == [], f"{path} changed at D6.1"


def test_the_frontend_contains_no_business_plan_implementation() -> None:
    for source_file in sorted((_PROJECT_ROOT / "web" / "src").rglob("*")):
        if not source_file.is_file() or source_file.suffix not in {".ts", ".tsx"}:
            continue
        text = source_file.read_text(encoding="utf-8")
        for vocabulary in ("BusinessPlan", "business_plan", "OwnerCapitalSchedule", "ownerCapital"):
            assert vocabulary not in text, f"{source_file.name} mentions {vocabulary}"


# =============================================================================
# engine/contracts.py changed only by adding OwnerCapitalSchedule -- as source
# text, not merely as an AST
# =============================================================================


# Used as a ``pytest.raises(match=...)`` pattern by the self-tests, so it holds
# no regex metacharacters beyond the harmless ``.`` in the file name.
_CONTRACTS_GUARDRAIL_FAILURE = (
    "engine/contracts.py changed beyond the authorized D6 additions -- "
    "D6.1 OwnerCapitalSchedule and D6.2 AcquisitionResults fields"
)


def _lf(text: str) -> str:
    """CRLF -> LF, and nothing else.

    The D5.9 source-reading convention (``web/src/testSourceText.ts``), applied
    at the test boundary: blobs are stored with LF and this working tree
    checks out CRLF, so the line terminator is the one thing that may differ.
    No other character is touched -- a lone ``\\r``, trailing whitespace, a
    blank line and a comment all still count.
    """

    return text.replace("\r\n", "\n")


def _baseline_engine_contracts(commit: str) -> str:
    return _lf(_git_bytes(["show", f"{commit}:{_ENGINE_CONTRACTS}"]).decode("utf-8"))


def _current_engine_contracts() -> str:
    # ``read_bytes`` rather than ``read_text``: universal-newline decoding
    # would also rewrite a lone ``\r``, which is more normalisation than _lf
    # grants.
    return _lf((_PROJECT_ROOT / _ENGINE_CONTRACTS).read_bytes().decode("utf-8"))


def _without_owner_capital_schedule(source: str) -> str:
    """``source`` with the ``OwnerCapitalSchedule`` addition cut out as text.

    The AST is used only to *locate* the class. It is never the equality
    oracle, and no source is regenerated from it. The removal rule is exactly:

    * every line from the class's first decorator (its ``class`` line, if it
      has none) through its last line, inclusive; and
    * the two blank lines immediately after it -- the PEP 8 separator the
      addition brought with it. Both must be empty, so anything placed there
      fails here rather than being swept up with the class.

    Nothing above the decorator is removed: a comment introducing the class
    is not part of the class, is not authorised, and is left behind to fail
    the comparison.
    """

    matches = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == "OwnerCapitalSchedule"
    ]
    assert len(matches) == 1, f"expected one OwnerCapitalSchedule, found {len(matches)}"
    (node,) = matches
    assert node.end_lineno is not None

    lines = source.split("\n")
    first = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)]) - 1
    after = node.end_lineno  # index of the first line after the class
    separator = lines[after : after + 2]
    assert separator == ["", ""], (
        f"{_CONTRACTS_GUARDRAIL_FAILURE}: the class must be followed by exactly "
        f"its two blank separator lines, found {separator!r}"
    )

    # The span is the class and only the class: parsed on its own it is one
    # top-level statement, that ClassDef.
    removed = ast.parse("\n".join(lines[first : after + 2])).body
    assert [(type(statement), getattr(statement, "name", None)) for statement in removed] == [
        (ast.ClassDef, "OwnerCapitalSchedule")
    ]

    return "\n".join(lines[:first] + lines[after + 2 :])


#: ``main`` after D6.1, immediately before D6.2.
_D6_1_MERGE = "7e67cde"

#: D6.2's additions to ``AcquisitionResults``, exactly as they must read:
#: appended after every pre-existing field, in the conventions' order, and with
#: no default -- an old stored result must decode as absent, never with
#: fabricated zeros (D6 conventions Section 14).
_D6_2_RESULT_FIELD_LINES = [
    "    closing_project_capital: float",
    "    project_capital_by_year: tuple[float, ...]",
    "    post_hold_project_capital: float",
    "    owner_expenses_by_year: tuple[float, ...]",
    "    property_cash_flow_by_year: tuple[float, ...]",
    "    unlevered_owner_cash_flow_by_year: tuple[float, ...]",
    "    levered_owner_cash_flow_by_year: tuple[float, ...]",
    "    total_closing_uses: float",
    "    total_closing_sources: float",
]


def _class_lines(source: str, class_name: str) -> tuple[int, int, int]:
    """0-based ``(first, docstring_close, end)`` for a class: its first line
    (decorator included), the line holding its docstring's closing quotes, and
    the index just past its last line."""

    node = _class_node(source, class_name)
    first = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)]) - 1
    docstring = node.body[0]
    assert (
        isinstance(docstring, ast.Expr)
        and isinstance(docstring.value, ast.Constant)
        and isinstance(docstring.value.value, str)
        and docstring.end_lineno is not None
        and node.end_lineno is not None
    )
    return first, docstring.end_lineno - 1, node.end_lineno


def _with_baseline_acquisition_results(source: str, baseline: str) -> str:
    """``source`` with ``AcquisitionResults`` put back to the baseline's text,
    after proving D6.2 changed that class in exactly two ways, as text:

    * prose appended to the end of its docstring -- every existing docstring
      line, the decorator and the ``class`` line are unchanged; and
    * exactly the nine ``_D6_2_RESULT_FIELD_LINES`` appended after its last
      existing field -- every existing field keeps its name, annotation, order
      and whitespace, and nothing else is added.

    The AST only locates the class and its docstring. The comparisons are
    ``==`` on source lines."""

    lines, baseline_lines = source.split("\n"), baseline.split("\n")
    first, close, end = _class_lines(source, "AcquisitionResults")
    base_first, base_close, base_end = _class_lines(baseline, "AcquisitionResults")
    current_class = lines[first:end]
    baseline_class = baseline_lines[base_first:base_end]
    kept = base_close - base_first  # lines before the docstring's closing quotes

    assert current_class[:kept] == baseline_class[:kept], (
        f"{_CONTRACTS_GUARDRAIL_FAILURE}: an existing line of AcquisitionResults' "
        "header or docstring changed"
    )
    appended = current_class[kept : close - first]
    assert all('"""' not in line for line in appended)
    assert current_class[close - first :] == baseline_class[kept:] + _D6_2_RESULT_FIELD_LINES, (
        f"{_CONTRACTS_GUARDRAIL_FAILURE}: AcquisitionResults' fields changed by more "
        "than appending the nine D6.2 fields"
    )
    return "\n".join(lines[:first] + baseline_class + lines[end:])


def _without_authorized_additions(source: str, baseline: str) -> str:
    """``source`` minus D6.1's ``OwnerCapitalSchedule`` and with D6.2's
    ``AcquisitionResults`` additions reverted -- each only after it is proved
    to be exactly the authorized addition."""

    return _with_baseline_acquisition_results(_without_owner_capital_schedule(source), baseline)


def _assert_only_authorized_additions(baseline: str, current: str) -> None:
    """Both arguments already LF-normalised. The comparison is ``==`` on text."""

    remainder = _without_authorized_additions(current, baseline)
    assert remainder == baseline, (
        f"{_CONTRACTS_GUARDRAIL_FAILURE}:\n"
        + "".join(
            difflib.unified_diff(
                baseline.splitlines(keepends=True),
                remainder.splitlines(keepends=True),
                "baseline",
                "current without the authorized D6 additions",
                n=1,
            )
        )
    )


@pytest.mark.parametrize(
    "baseline", [_D6_BASE_COMMIT, _D4_6A_COMMIT, _D4_5A_COMMIT], ids=["d6-base", "d4.6a", "d4.5a"]
)
def test_engine_contracts_changed_only_by_the_authorized_d6_additions(baseline: str) -> None:
    """The stronger claim that replaces byte-identity for ``engine/contracts.py``.

    Cutting the ``OwnerCapitalSchedule`` class's exact source span out of
    today's file, and reverting D6.2's proven ``AcquisitionResults`` additions,
    must leave the baseline file's source text exactly, CRLF normalised to LF
    and nothing else: not one other import, class, field, docstring, function,
    blank line or byte of whitespace was touched, and nothing else was added.
    This backs the D6.1 and D6.2 narrowings of G33 (D4.5A baseline) and G37
    (D4.6A baseline); each baseline is compared on its own.

    Hardened at D6.1 closeout (the first version compared ASTs, which cannot
    see comments, blank lines or formatting). **Extended at D6.2** by exactly
    one more authorized surface -- the result-contract additions -- with its
    own text-level proof, rather than by exempting the file.
    """

    baseline_source = _baseline_engine_contracts(baseline)
    assert "OwnerCapitalSchedule" not in baseline_source
    assert "closing_project_capital" not in baseline_source

    _assert_only_authorized_additions(baseline_source, _current_engine_contracts())


def test_since_d6_1_contracts_changed_only_in_acquisition_results_and_a_docstring() -> None:
    """Against the D6.1 merge itself: D6.2's only changes to the module are the
    ``AcquisitionResults`` additions and ``OwnerCapitalSchedule``'s docstring,
    which now says the contract is wired. The schedule's fields and validation
    are unchanged since D6.1."""

    baseline = _baseline_engine_contracts(_D6_1_MERGE)
    current = _current_engine_contracts()

    remainder = _with_baseline_acquisition_results(
        _without_owner_capital_schedule(current), _without_owner_capital_schedule(baseline)
    )
    assert remainder == _without_owner_capital_schedule(baseline), _CONTRACTS_GUARDRAIL_FAILURE

    def without_docstring(source: str) -> str:
        node = _class_node(source, "OwnerCapitalSchedule")
        return ast.dump(ast.Module(body=node.body[1:], type_ignores=[])) + ast.dump(
            ast.Module(body=[ast.Expr(d) for d in node.decorator_list], type_ignores=[])
        )

    assert without_docstring(current) == without_docstring(baseline)


# --- Self-tests: the guardrail above has teeth --------------------------------
#
# Each runs the guardrail's own helpers over the real files, in memory: the
# current ``engine/contracts.py`` as the working tree holds it, and the
# pre-D6.1 module as ``908499c`` holds it. (D4.5A, D4.6A and 908499c hold the
# same bytes for that file.) Nothing is written to disk.


def test_the_line_ending_normalisation_rewrites_crlf_and_nothing_else() -> None:
    assert _lf("a\r\nb\rc\n  \n# d\t\n") == "a\nb\rc\n  \n# d\t\n"


def test_the_contracts_guardrail_accepts_the_authorized_additions() -> None:
    """Self-test A. The committed D6.1 and D6.2 additions pass -- whether the
    working tree checks the file out with LF or CRLF -- and they account for
    every added line."""

    baseline = _baseline_engine_contracts(_D6_BASE_COMMIT)
    current = _current_engine_contracts()

    _assert_only_authorized_additions(baseline, current)
    _assert_only_authorized_additions(baseline, _lf(current.replace("\n", "\r\n")))

    added_lines = len(current.split("\n")) - len(baseline.split("\n"))
    class_source = ast.get_source_segment(current, _class_node(current, "OwnerCapitalSchedule"))
    assert class_source is not None
    first, close, _ = _class_lines(current, "AcquisitionResults")
    base_first, base_close, _ = _class_lines(baseline, "AcquisitionResults")
    appended_prose = (close - first) - (base_close - base_first)
    # D6.1: the ``class`` statement, its one decorator line and its two
    # separator lines. D6.2: the docstring prose and the nine fields. No more.
    assert added_lines == (
        len(class_source.split("\n")) + 1 + 2 + appended_prose + len(_D6_2_RESULT_FIELD_LINES)
    )


#: Edits to pre-D6.1 source outside the class: ``(old, new, ast_visible)``.
#: ``ast_visible=False`` marks an edit the superseded AST oracle accepted.
_EDITS_TO_EXISTING_SOURCE = [
    pytest.param(
        '"one leasing-commission figure per hold year; got "',
        '"one leasing-commission value per hold year; got "',
        True,
        id="existing-code-line",
    ),
    pytest.param(
        '"""Underwriting V2 Gate 2 adds ``disposition_costs``.',
        '"""Underwriting V2 Gate 2 added ``disposition_costs``.',
        True,
        id="existing-docstring",
    ),
    pytest.param(
        "from math import isfinite\n",
        "from math import isfinite, isnan\n",
        True,
        id="existing-import",
    ),
    pytest.param(
        "        for name, series in (\n"
        '            ("tenant_improvements_by_year",',
        "        # tampered\n"
        "        for name, series in (\n"
        '            ("tenant_improvements_by_year",',
        False,
        id="comment-in-existing-class",
    ),
    pytest.param(
        "from dataclasses import dataclass\n",
        "from dataclasses import dataclass \n",
        False,
        id="trailing-whitespace",
    ),
    pytest.param(
        "from typing import Protocol\n",
        "from typing import Protocol\n\n",
        False,
        id="reformatted-blank-line",
    ),
]


@pytest.mark.parametrize(("old", "new", "ast_visible"), _EDITS_TO_EXISTING_SOURCE)
def test_the_contracts_guardrail_rejects_an_edit_to_existing_source(
    old: str, new: str, ast_visible: bool
) -> None:
    """Self-test B. Changing one pre-D6.1 line fails the guardrail -- including
    the comment, whitespace and blank-line edits an AST comparison cannot see."""

    baseline = _baseline_engine_contracts(_D6_BASE_COMMIT)
    current = _current_engine_contracts()
    # The edited text is pre-D6.1 source, present once, and not in the class.
    assert baseline.count(old) == 1 and current.count(old) == 1
    tampered = current.replace(old, new)

    with pytest.raises(AssertionError, match=_CONTRACTS_GUARDRAIL_FAILURE):
        _assert_only_authorized_additions(baseline, tampered)

    old_oracle_passes = ast.dump(
        ast.parse(_without_authorized_additions(tampered, baseline))
    ) == ast.dump(ast.parse(baseline))
    assert old_oracle_passes is not ast_visible


_UNRELATED_DATACLASS = (
    "@dataclass(frozen=True, slots=True, kw_only=True)\n"
    "class UnrelatedSchedule:\n"
    "    amount: float\n"
    "\n"
    "\n"
)
_OWNER_CAPITAL_DECORATOR = "@dataclass(frozen=True, slots=True, kw_only=True)\nclass OwnerCapitalSchedule:"
_NEXT_CLASS = "@dataclass(frozen=True, slots=True, kw_only=True)\nclass AcquisitionCashFlows:"

#: Unrelated additions: ``(anchor, replacement)``, or ``(None, appended)``.
_UNRELATED_ADDITIONS = [
    pytest.param(None, "\n\nUNRELATED_LIMIT = 1.0\n", id="constant"),
    pytest.param(None, "\n\ndef unrelated_helper() -> None:\n    return None\n", id="function"),
    pytest.param(_NEXT_CLASS, _UNRELATED_DATACLASS + _NEXT_CLASS, id="class-beside-the-addition"),
    pytest.param(
        "from typing import Protocol\n",
        "from typing import Protocol\nfrom os import environ\n",
        id="import",
    ),
    pytest.param(
        _OWNER_CAPITAL_DECORATOR,
        "# Introduced at D6.1.\n" + _OWNER_CAPITAL_DECORATOR,
        id="comment-above-the-addition",
    ),
    pytest.param(
        "\n\n\n" + _NEXT_CLASS,
        "\n# End of D6.1.\n\n\n" + _NEXT_CLASS,
        id="comment-below-the-addition",
    ),
]


@pytest.mark.parametrize(("anchor", "replacement"), _UNRELATED_ADDITIONS)
def test_the_contracts_guardrail_rejects_an_unrelated_addition(
    anchor: str | None, replacement: str
) -> None:
    """Self-test C. Adding anything beside ``OwnerCapitalSchedule`` fails the
    guardrail -- including a comment or class placed immediately next to it,
    where a loose removal rule would sweep it up with the class."""

    baseline = _baseline_engine_contracts(_D6_BASE_COMMIT)
    current = _current_engine_contracts()
    if anchor is None:
        tampered = current + replacement
    else:
        assert current.count(anchor) == 1
        tampered = current.replace(anchor, replacement)

    with pytest.raises(AssertionError, match=_CONTRACTS_GUARDRAIL_FAILURE):
        _assert_only_authorized_additions(baseline, tampered)


#: Changes to ``AcquisitionResults`` beyond D6.2's exact authorization:
#: ``(old, new)``, each ``old`` present once in the current module.
_UNAUTHORIZED_RESULT_CHANGES = [
    pytest.param(
        "    total_closing_sources: float\n",
        "    total_closing_sources: float\n    total_equity_invested: float\n",
        id="d6-3-field-added-early",
    ),
    pytest.param(
        "    total_closing_sources: float\n",
        "    total_closing_sources: float = 0.0\n",
        id="field-given-a-default",
    ),
    pytest.param(
        "    total_closing_uses: float\n    total_closing_sources: float\n",
        "    total_closing_sources: float\n    total_closing_uses: float\n",
        id="fields-reordered",
    ),
    pytest.param(
        "    year_1_debt_yield: float | None\n    closing_project_capital: float\n",
        "    closing_project_capital: float\n    year_1_debt_yield: float | None\n",
        id="inserted-before-an-existing-field",
    ),
    pytest.param(
        "    year_1_debt_yield: float | None\n    closing_project_capital: float\n",
        "    year_1_debt_yield: float\n    closing_project_capital: float\n",
        id="existing-annotation-changed",
    ),
    pytest.param(
        "    modeled strictly below NOI, in the cash-flow series only.\n",
        "    modelled strictly below NOI, in the cash-flow series only.\n",
        id="existing-docstring-line-edited",
    ),
    pytest.param(
        "    post_hold_project_capital: float\n    owner_expenses_by_year: tuple[float, ...]\n",
        "    owner_expenses_by_year: tuple[float, ...]\n",
        id="d6-2-field-missing",
    ),
    pytest.param(
        "    closing_project_capital: float\n    project_capital_by_year: tuple[float, ...]\n"
        "    post_hold_project_capital",
        "    closing_project_capital: float\n    project_capital_by_year: tuple[float | None, ...]\n"
        "    post_hold_project_capital",
        id="d6-2-field-retyped",
    ),
]


@pytest.mark.parametrize(("old", "new"), _UNAUTHORIZED_RESULT_CHANGES)
def test_the_contracts_guardrail_rejects_an_unauthorized_result_change(old: str, new: str) -> None:
    """Self-test D (D6.2). The result-contract authorization is exact: a D6.3
    field, a default, a reorder, an insertion among the existing fields, an
    edited existing annotation or docstring line, a missing or retyped D6.2
    field -- each fails."""

    baseline = _baseline_engine_contracts(_D6_BASE_COMMIT)
    current = _current_engine_contracts()
    assert current.count(old) == 1, old

    with pytest.raises(AssertionError, match=_CONTRACTS_GUARDRAIL_FAILURE):
        _assert_only_authorized_additions(baseline, current.replace(old, new))
