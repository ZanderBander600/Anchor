"""Architecture guardrails for the Phase 6 ``anchor.business_plan`` layer.

Gate D6.1, governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md``
Section 13. The dependency direction is::

    anchor.business_plan  ->  anchor.engine.contracts

and never the reverse. The engine will consume only the resolved
``OwnerCapitalSchedule``; it must never learn what a plan item, identifier,
description, category or model month is.

D6.1 is **unwired**: no acquisition-analysis path consumes a Business Plan, so
no D5 financial output can move. These tests are the mechanical proof. D6.2
owns the engine bridge and is expected to narrow the "unwired" and
"unchanged" clauses below by exactly what its own scope requires.

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
_UNCHANGED_FINANCIAL_PATHS = (
    "src/anchor/engine/__init__.py",
    "src/anchor/engine/acquisition.py",
    "src/anchor/engine/returns.py",
    "src/anchor/engine/debt.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/operating_projection.py",
    "src/anchor/leasing",
    "src/anchor/analysis",
    "src/anchor/ai",
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


def test_no_module_outside_the_package_imports_anchor_business_plan() -> None:
    """Stated over the whole source tree, so an importer cannot appear in a
    package nobody thought to list. This covers acquisition, debt, returns,
    the rest of the engine, ``anchor.leasing``, analysis, deals, AI, the API
    and every top-level module."""

    importers = sorted(
        str(source_file.relative_to(_SRC_DIR)).replace("\\", "/")
        for source_file in _python_files(_ANCHOR_DIR)
        if _BUSINESS_PLAN_DIR not in source_file.parents
        and any(
            name == "anchor.business_plan" or name.startswith("anchor.business_plan.")
            for name in _imported_module_names(source_file)
        )
    )

    assert importers == [], f"anchor.business_plan is imported by {importers}"


def test_importing_the_engine_and_leasing_does_not_pull_in_the_business_plan() -> None:
    completed = _fresh_interpreter(
        "import sys; "
        "import anchor.engine, anchor.engine.acquisition, anchor.engine.debt, "
        "anchor.engine.returns, anchor.engine.contracts, anchor.leasing, "
        "anchor.analysis; "
        "assert 'anchor.business_plan' not in sys.modules, "
        "sorted(m for m in sys.modules if m.startswith('anchor.business_plan'))"
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


def test_owner_capital_schedule_is_referenced_only_by_its_contract_and_resolver() -> None:
    """No engine calculator, analysis orchestrator, API or persistence module
    names the new contract. D6.2 owns the first consumer."""

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
        "anchor/business_plan/resolver.py",
        "anchor/engine/contracts.py",
    ]


def test_acquisition_entry_points_take_no_business_plan() -> None:
    from anchor.analysis import lease_level
    from anchor.engine import acquisition

    assert list(
        inspect.signature(
            acquisition.analyze_acquisition_from_operating_projection
        ).parameters
    ) == ["operating_projection", "terms", "operating_capital"]
    for module in (acquisition, lease_level):
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("analyze"):
                continue
            for parameter in inspect.signature(function).parameters:
                assert "business_plan" not in parameter and "owner_capital" not in parameter, (
                    f"{module.__name__}.{name} takes {parameter!r}; D6.1 is unwired"
                )


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


_CONTRACTS_GUARDRAIL_FAILURE = "engine/contracts.py changed by more than adding OwnerCapitalSchedule"


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


def _assert_only_owner_capital_schedule_added(baseline: str, current: str) -> None:
    """Both arguments already LF-normalised. The comparison is ``==`` on text."""

    remainder = _without_owner_capital_schedule(current)
    assert remainder == baseline, (
        f"{_CONTRACTS_GUARDRAIL_FAILURE}:\n"
        + "".join(
            difflib.unified_diff(
                baseline.splitlines(keepends=True),
                remainder.splitlines(keepends=True),
                "baseline",
                "current without OwnerCapitalSchedule",
                n=1,
            )
        )
    )


@pytest.mark.parametrize(
    "baseline", [_D6_BASE_COMMIT, _D4_6A_COMMIT, _D4_5A_COMMIT], ids=["d6-base", "d4.6a", "d4.5a"]
)
def test_engine_contracts_changed_only_by_adding_owner_capital_schedule(baseline: str) -> None:
    """The stronger claim that replaces byte-identity for ``engine/contracts.py``.

    Cutting the ``OwnerCapitalSchedule`` class's exact source span out of
    today's file must leave the baseline file's source text exactly, CRLF
    normalised to LF and nothing else: not one existing import, class, field,
    docstring, function, blank line or byte of whitespace was touched, and
    nothing else was added. This backs the D6.1 narrowing of G33 (D4.5A
    baseline) and G37 (D4.6A baseline); each baseline is compared on its own.

    Hardened at D6.1 closeout. The first version compared ASTs, which cannot
    see comments, blank lines or formatting.
    """

    baseline_source = _baseline_engine_contracts(baseline)
    assert "OwnerCapitalSchedule" not in baseline_source

    _assert_only_owner_capital_schedule_added(baseline_source, _current_engine_contracts())


# --- Self-tests: the guardrail above has teeth --------------------------------
#
# Each runs the guardrail's own helpers over the real files, in memory: the
# current ``engine/contracts.py`` as the working tree holds it, and the
# pre-D6.1 module as ``908499c`` holds it. (D4.5A, D4.6A and 908499c hold the
# same bytes for that file.) Nothing is written to disk.


def test_the_line_ending_normalisation_rewrites_crlf_and_nothing_else() -> None:
    assert _lf("a\r\nb\rc\n  \n# d\t\n") == "a\nb\rc\n  \n# d\t\n"


def test_the_contracts_guardrail_accepts_owner_capital_schedule_alone() -> None:
    """Self-test A. The committed D6.1 addition passes -- whether the working
    tree checks the file out with LF or CRLF."""

    baseline = _baseline_engine_contracts(_D6_BASE_COMMIT)
    current = _current_engine_contracts()

    _assert_only_owner_capital_schedule_added(baseline, current)
    _assert_only_owner_capital_schedule_added(baseline, _lf(current.replace("\n", "\r\n")))

    removed_lines = len(current.split("\n")) - len(baseline.split("\n"))
    class_source = ast.get_source_segment(current, _class_node(current, "OwnerCapitalSchedule"))
    assert class_source is not None
    # The ``class`` statement, its one decorator line and its two separator
    # lines, and no more.
    assert removed_lines == len(class_source.split("\n")) + 1 + 2


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
        _assert_only_owner_capital_schedule_added(baseline, tampered)

    old_oracle_passes = ast.dump(ast.parse(_without_owner_capital_schedule(tampered))) == ast.dump(
        ast.parse(baseline)
    )
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
        _assert_only_owner_capital_schedule_added(baseline, tampered)
