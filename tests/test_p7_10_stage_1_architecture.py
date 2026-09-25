"""Phase 7 Gate P7.10 Stage 1 -- the production ledger and architecture guards.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 2, 5, 6, 17
and 18.1. Every git query reads objects only (protocol 11.2). The guards hold:

Stage 1 activates ``PctOfValue`` **closing** execution, not ``PctOfValue``
generally (contract Section 6.1). Nothing below should be read as proving the
rule universally executable: the P7.8 closing-only funding window is unchanged,
and a later timepoint stays a reporting value.

1. **the Stage 1 production ledger**: exactly the new ``anchor.valuation``
   package and the four Capital Structure modules the ``PctOfValue`` seam
   touches, measured from ``main`` at ``9c65843``;
2. **the frozen upstream**, byte for byte, and every protected path unchanged;
3. **the four touched modules changed only at the declared seam** -- every
   other definition in them is identical to the accepted baseline's, so no
   debt, preferred, settlement, residual, return or metric formula moved;
4. **the dependency direction**: Capital Structure reads valuation, valuation
   reads the engine, and valuation never reads Capital Structure;
5. **no duplicated authority, no cash flow, and no later-stage surface** --
   no persistence, migration, schema version, route, memo, AI, PDF or
   frontend belongs to Stage 1;
6. **no public API or wire contract changed** -- no Capital Structure
   dataclass gained or lost a field, ``api.py`` is byte-identical, and nothing
   routes to the valuation layer.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.10 began: the 2026-09-20 acceptance-closeout merge (PR #48),
#: and the accepted repository baseline this gate starts from.
_P7_10_BASE = "9c658437f76e8815cb228d4b71b11aaa473450d4"
_P7_10_BASE_PARENTS = [
    "1afd003fa2b35df6f4ad50060d3fa5ae587fd1d7",
    "2e98937f8871392f7348aaa6bb8cf8e2728504ce",
]

#: Stage 1's reviewed head, merged into ``main`` as the second parent of the
#: Stage 1 merge (PR #49) and human accepted there. **Re-pinned at Stage 2**,
#: exactly as this module's own docstring said it would be: the ledger, the
#: protected paths and the API freeze below read Stage 1's committed range
#: ``9c65843..7237d7a`` rather than the working tree, so Stage 2's files never
#: read as Stage 1 changes while every Stage 1 claim stays proven against real
#: history. Stage 2's own ledger and freeze are
#: ``tests/test_p7_10_stage_2_architecture.py``.
_STAGE_1_HEAD = "7237d7a8c77967529a9c277ffda581fef112a792"
_STAGE_1_MERGE = "f6f36803cdcb646aa8a4af8cfc658a0e368ae58e"
_STAGE_1_COMMITS = ("7fb5fff", "8c35057", "f388fe2", "7237d7a")

_PACKAGE = "src/anchor/valuation"
_NAMES = ("__init__", "contracts", "validation", "engine", "funding")
_MODULES = tuple(f"{_PACKAGE}/{name}.py" for name in _NAMES)

_CAPITAL = "src/anchor/capital_structure"
#: The four Capital Structure modules the ``PctOfValue`` seam touches, and the
#: only pre-existing production files Stage 1 changes.
_SEAM_MODULES = tuple(
    f"{_CAPITAL}/{name}.py" for name in ("execution_contracts", "execution_validation", "funding", "execution")
)

#: Every production file Stage 1 changes, exactly (Section 17, Stage 1).
_STAGE_1_PRODUCTION_FILES = frozenset((*_MODULES, *_SEAM_MODULES))

#: The Capital Structure modules Stage 1 does not touch: the P7.7 contract and
#: foundation, and the P7.8 financial core -- the debt and preferred formulas,
#: the settlement metrics. Byte-identical to the accepted baseline.
_CAPITAL_FROZEN = tuple(
    f"{_CAPITAL}/{name}.py"
    for name in ("__init__", "contracts", "validation", "legacy", "foundation", "debt_position", "preferred", "metrics")
)

#: The upstream Stage 1 reads and changes none of.
_FROZEN = (
    "src/anchor/engine/debt.py",
    "src/anchor/engine/acquisition.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/returns.py",
    "src/anchor/engine/contracts.py",
    "src/anchor/engine/operating_projection.py",
    "src/anchor/consolidation/engine.py",
    "src/anchor/consolidation/contracts.py",
    "src/anchor/contracts.py",
    *(f"src/anchor/partnership/{name}.py" for name in ("contracts", "waterfall", "allocation", "accounts", "metrics")),
    *_CAPITAL_FROZEN,
)

#: Stage 2, 3 and 4 surfaces, and everything else upstream: unchanged.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/consolidation",
    "src/anchor/partnership",
    "src/anchor/investment",
    "src/anchor/deals",
    "src/anchor/decision",
    "src/anchor/analysis",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/asset_management",
    "src/anchor/exports",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/api.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/asset_types.py",
    "src/anchor/report.py",
    "src/anchor/cli.py",
    "src/anchor/__init__.py",
    "web",
)

#: The exact imports of each new module.
_IMPORTS: dict[str, set[str]] = {
    "__init__": {"__future__", ".contracts", ".engine", ".funding", ".validation"},
    "contracts": {"__future__", "dataclasses", "enum", "typing"},
    "validation": {"__future__", "collections", "math", ".contracts"},
    "engine": {"__future__", "..consolidation.contracts", "..contracts", "..engine.contracts", ".contracts", ".validation"},
    "funding": {"__future__", "dataclasses", "..engine.contracts", ".contracts"},
}

#: Exactly the top-level definitions of each seam module whose source P7.10
#: Stage 1 changes. Everything else in those four files is the accepted
#: baseline's, character for character.
_SEAM_CHANGES: dict[str, set[str]] = {
    f"{_CAPITAL}/execution_contracts.py": {"ExecutionIssueCode", "ResolvedFundingEvent"},
    f"{_CAPITAL}/execution_validation.py": {"_funding_issues", "_claim_issues", "validate_structured_execution"},
    f"{_CAPITAL}/funding.py": {"valuation_scope", "resolve_valuation_funding", "resolve_funding"},
    f"{_CAPITAL}/execution.py": {
        "_executable_positions",
        "schedule_position",
        "execute_unit_capital_structure",
        "execute_investment_capital_structure",
    },
}

#: Nothing Stage 1 writes may reach persistence, the wire, a document, a model
#: or the clock: it is a pure deterministic layer.
_FORBIDDEN_IMPORTS = re.compile(
    r"(^|\.)(api|store|deals|ai|ingestion|decision|analysis|investment|asset_management|exports|leasing"
    r"|business_plan|partnership)(\.|$)"
    r"|sqlite3|fastapi|pydantic|openai|httpx|requests|reportlab|weasyprint|openpyxl|xlsxwriter"
    r"|^(os|sys|pathlib|datetime|time|random|uuid|json|logging|secrets)$"
)

#: Vocabulary no Stage 1 module may contain: a later stage's surface, or a
#: causal attribution Section 5.6 forbids until a ratified decomposition
#: calculates one.
_FORBIDDEN_VOCABULARY = (
    "memo",
    "evidence_reference",
    "publish",
    "pdf",
    "prompt",
    "grounding",
    "schema_version",
    "migration",
    "fingerprint",
    "value_creation",
    "rent_growth",
    "renovation",
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    """The paths Stage 1's committed range changed. Objects only: no working
    tree and no index (protocol 11.2).

    Re-pinned at Stage 2, as this module's docstring always said it would be.
    Measured against the working tree it read Stage 2's persistence, API and
    resolution files as unauthorized Stage 1 changes; measured over
    ``9c65843..7237d7a`` it proves what Stage 1 actually shipped."""

    return {
        path
        for path in _git(
            "diff", "--name-only", "--no-renames", base, _STAGE_1_HEAD, "--", *paths
        ).split()
        if path
    }


def _working_tree_changes_since(base: str, *paths: str) -> set[str]:
    """The paths the working tree differs in from ``base``. Used only where the
    claim really is "and it is still unchanged now", not merely "Stage 1 did not
    change it"."""

    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _at_base(path: str) -> str:
    return _git("show", f"{_P7_10_BASE}:{path}").replace("\r\n", "\n")


def _tree(path: str) -> ast.Module:
    return ast.parse(_current(path))


def _module(name: str) -> str:
    return f"{_PACKAGE}/{name}.py"


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


def _definitions(source: str) -> dict[str, str]:
    """Every top-level function and class, by name, as normalised source."""

    tree = ast.parse(source)
    return {
        node.name: ast.unparse(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


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
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
    return found


# =============================================================================
# 1. The ledger
# =============================================================================


def test_stage_1_changes_exactly_the_declared_production_files() -> None:
    changed = {path for path in _changes_since(_P7_10_BASE, "src", "web") if _is_production(path)}
    assert sorted(changed - _STAGE_1_PRODUCTION_FILES) == []
    assert sorted(_STAGE_1_PRODUCTION_FILES - changed) == []


def test_the_ledger_base_is_the_accepted_closeout_merge() -> None:
    assert _git("rev-list", "--parents", "-n", "1", _P7_10_BASE).split()[1:] == _P7_10_BASE_PARENTS


def test_the_ledger_range_is_exactly_the_merged_stage_1_branch() -> None:
    """The re-pinned range is real history, is neither empty nor stretched over
    a later gate, and is the one ``main`` was built from."""

    # PR #49's merge joins the ledger base (first parent) and the ledger head.
    assert _git("rev-list", "--parents", "-n", "1", _STAGE_1_MERGE).split()[1:] == [
        _P7_10_BASE,
        _STAGE_1_HEAD,
    ]
    commits = _git("rev-list", "--reverse", "--abbrev-commit", f"{_P7_10_BASE}..{_STAGE_1_HEAD}").split()
    assert tuple(commits) == _STAGE_1_COMMITS
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", _STAGE_1_MERGE, "HEAD"], check=True, cwd=_PROJECT_ROOT
    )


def test_the_ledger_range_is_not_a_no_op() -> None:
    """Every authorized file really changes inside the range, so the ledger is
    measuring real history rather than an empty diff."""

    assert _changes_since(_P7_10_BASE, "src", "web") == set(_STAGE_1_PRODUCTION_FILES)


#: Refinance & Capital Events V1 Stage 2 re-pin (second review correction).
#: The additive P7.10 amendment -- ``ValuationUnavailableReason.EVIDENCE_NOT_APPROVED``
#: and its explicit wire mapping -- plus the typed consumer and the temporary
#: Stage 3 report gate, amend these accepted files and nothing else. In
#: ``tests/test_refinance_v1_stage_2_architecture.py`` the valuation, wire and
#: memo-contract changes are each held to their exact diff, and the
#: publication changes (the gate refusal and consumer-aware wording) by named
#: guards. The freeze here excludes exactly these paths and still holds every
#: other file of the package byte for byte.
_REFINANCE_V1_STAGE_2_AMENDED = frozenset(
    {
        "src/anchor/valuation/contracts.py",
        "src/anchor/memo/availability.py",
        "src/anchor/memo/contracts.py",
        "src/anchor/memo/publication.py",
    }
)


def _amendment_guards_exist() -> None:
    guard = (_PROJECT_ROOT / "tests" / "test_refinance_v1_stage_2_architecture.py").read_text(encoding="utf-8")
    for name in (
        "test_the_p7_10_valuation_amendment_adds_one_reason_and_nothing_else",
        "test_the_p7_10_wire_amendment_maps_the_new_reason_explicitly",
        "test_the_memo_contracts_gain_only_the_typed_consumer",
    ):
        assert f"def {name}(" in guard, name


def test_the_accepted_stage_1_package_is_still_byte_identical_to_its_merge() -> None:
    """A *stronger* claim than the one this file could make before Stage 1 was
    merged: the accepted valuation package is unchanged in the working tree,
    now, not merely unchanged during Stage 1. Stage 2 consumes it and edits
    none of it -- except the one named, guarded amendment."""

    _amendment_guards_exist()
    merged = sorted(_git("ls-tree", "-r", "--name-only", _STAGE_1_MERGE, _PACKAGE).split())
    assert merged == sorted(_MODULES)
    for path in merged:
        if path in _REFINANCE_V1_STAGE_2_AMENDED:
            continue
        assert _git("hash-object", path).strip() == _git("rev-parse", f"{_STAGE_1_MERGE}:{path}").strip(), path
    assert _working_tree_changes_since(_STAGE_1_MERGE, _PACKAGE) - _REFINANCE_V1_STAGE_2_AMENDED == set()


def test_the_valuation_package_is_new_at_this_gate() -> None:
    assert _git("ls-tree", "-r", "--name-only", _P7_10_BASE, _PACKAGE).split() == []


def test_no_frontend_file_changed() -> None:
    """Stage 1 is backend only. A changed frontend file is a scope violation,
    not a guard to update."""

    assert _changes_since(_P7_10_BASE, "web") == set()


# =============================================================================
# 2. The frozen upstream
# =============================================================================


#: Refinance & Capital Events V1 Stage 1 re-pin. The ratified refinance
#: contract extends two P7.7 modules this gate froze (``contracts.py`` and
#: ``validation.py``) and three of this gate's own seam modules
#: (``execution_contracts.py``, ``execution_validation.py``, ``execution.py``).
#: Stage 1's claims about them are its own, so they are judged through the
#: accepted baseline ``2e1f84a``, the last tree before refinancing existed; the
#: refinance change is held by ``tests/test_refinance_v1_stage_1_architecture.py``.
_REFINANCE_V1_BASE = "2e1f84aaa7c93b3247e8dbc6ded8b4397124d36b"
_REFINANCE_V1_FROZEN = tuple(f"{_CAPITAL}/{name}.py" for name in ("contracts", "validation"))
_REFINANCE_V1_SEAM = tuple(f"{_CAPITAL}/{name}.py" for name in ("execution_contracts", "execution_validation", "execution"))


@pytest.mark.parametrize("path", _REFINANCE_V1_FROZEN)
def test_each_refinance_seam_module_was_frozen_through_the_accepted_baseline(path: str) -> None:
    assert _git("rev-parse", f"{_REFINANCE_V1_BASE}:{path}").strip() == _git("rev-parse", f"{_P7_10_BASE}:{path}").strip(), path


@pytest.mark.parametrize("path", tuple(path for path in _FROZEN if path not in _REFINANCE_V1_FROZEN))
def test_each_frozen_module_is_byte_identical_to_the_base(path: str) -> None:
    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_P7_10_BASE}:{path}").strip(), path


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged(path: str) -> None:
    assert _changes_since(_P7_10_BASE, path) == set(), path


# =============================================================================
# 3. The four seam modules changed only at the declared seam
# =============================================================================


@pytest.mark.parametrize("path", _SEAM_MODULES)
def test_each_seam_module_changed_only_its_declared_definitions(path: str) -> None:
    """The strongest guard this gate carries. The four Capital Structure
    modules are no longer byte-frozen, so this proves the change is confined:
    every top-level definition outside the declared seam is exactly the
    accepted baseline's, and none is added or removed beyond them."""

    before = _definitions(_at_base(path))
    after = _definitions(
        _git("show", f"{_REFINANCE_V1_BASE}:{path}").replace("\r\n", "\n")
        if path in _REFINANCE_V1_SEAM
        else _current(path)
    )
    declared = _SEAM_CHANGES[path]
    changed = {name for name in before.keys() & after.keys() if before[name] != after[name]}
    added = after.keys() - before.keys()
    removed = before.keys() - after.keys()
    assert removed == set(), path
    assert changed | added == declared, path


def test_no_settlement_residual_or_return_formula_moved() -> None:
    """Named explicitly: the functions that decide who is paid, in what order,
    out of what cash, and what they earned."""

    execution = _definitions(_current(f"{_CAPITAL}/execution.py"))
    baseline = _definitions(_at_base(f"{_CAPITAL}/execution.py"))
    for name in (
        "_settle_position",
        "_settle_scope",
        "_apply_closing",
        "_apply_settled",
        "_requirements",
        "_require_funded_closing",
        "_layers",
        "_position_returns",
        "_common_equity",
    ):
        assert execution[name] == baseline[name], name


# =============================================================================
# 4. The dependency direction
# =============================================================================


@pytest.mark.parametrize("name", _NAMES)
def test_each_module_imports_exactly_what_it_needs(name: str) -> None:
    imports = _imports(_tree(_module(name)))
    assert imports == _IMPORTS[name], name
    assert not {found for found in imports if _FORBIDDEN_IMPORTS.search(found)}, name


def test_the_valuation_package_never_reads_the_capital_structure() -> None:
    """The dependency runs one way. Capital Structure reads valuation; the
    valuation layer knows nothing about positions, priorities or claims, so no
    cycle and no second Capital Structure authority can appear."""

    for name in _NAMES:
        assert not any("capital_structure" in found for found in _imports(_tree(_module(name)))), name


#: At Stage 1 only the three Capital Structure seam modules read the valuation
#: package. Stage 2 connects exactly these further layers, and no others:
#: persistence, the two identity/codec modules, the resolution service, the
#: structured variant that supplies the funding authority, the unavailable
#: adapter, and the routes. The memo dependency ledger is deliberately absent:
#: it reaches valuation only through those services. Re-pinned from
#: "only the seam reads it" -- the Stage 1 claim it supersedes is that nothing
#: *outside* this named list does.
_VALUATION_READERS = [
    "src/anchor/api.py",
    f"{_CAPITAL}/execution.py",
    f"{_CAPITAL}/execution_validation.py",
    f"{_CAPITAL}/funding.py",
    # Refinance & Capital Events V1 Stage 1: an LTV-enabled refinance consumes
    # the referenced valuation cell, and DSCR reads forward NOI through the
    # valuation package's own ``forward_noi_at`` (R-C). Same direction: Capital
    # Structure reads valuation, never the reverse.
    f"{_CAPITAL}/refinance.py",
    f"{_CAPITAL}/refinance_contracts.py",
    f"{_CAPITAL}/refinance_execution.py",
    "src/anchor/deals/fingerprint.py",
    # Refinance & Capital Events V1 Stage 2 (second review correction): the
    # refinance adapter classifies ``evidence_not_approved`` from the typed
    # ``ValuationUnavailableReason`` on the cell and the gated authority it was
    # read from. Same direction: deals reads valuation, never the reverse.
    "src/anchor/deals/refinance_integration.py",
    "src/anchor/deals/store.py",
    "src/anchor/deals/structured_variants.py",
    "src/anchor/deals/valuation_codec.py",
    "src/anchor/deals/valuation_views.py",
    "src/anchor/memo/availability.py",
]


def test_only_the_named_layers_read_the_valuation_package() -> None:
    importers = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        if path.relative_to(_PROJECT_ROOT / "src" / "anchor").parts[0] != "valuation"
        and any(
            found.lstrip(".").split(".")[0] == "valuation" or found.startswith(("anchor.valuation", "..valuation"))
            for found in _imports(ast.parse(path.read_text(encoding="utf-8")))
        )
    )
    assert importers == _VALUATION_READERS


def test_no_upstream_engine_layer_reads_the_valuation_package() -> None:
    """The Stage 1 direction is unchanged by Stage 2: the engine, consolidation,
    leasing, Business Plan, Partnership, ingestion and AI layers still know
    nothing about valuation, so no cycle and no second authority can appear."""

    for layer in ("engine", "consolidation", "partnership", "investment", "business_plan", "leasing", "ai", "ingestion", "exports"):
        for path in (_PROJECT_ROOT / "src" / "anchor" / layer).rglob("*.py"):
            modules = _imports(ast.parse(path.read_text(encoding="utf-8")))
            assert not any("valuation" in module for module in modules), path


def test_upstream_names_are_calculation_free_contracts_and_one_named_helper() -> None:
    """``ensure_finite`` is the one upstream function the package calls, and
    it computes nothing: it raises on a non-finite result."""

    for name in _NAMES:
        tree = _tree(_module(name))
        assert _imported_names(tree, "..engine.contracts") <= {"AcquisitionResults", "ensure_finite"}, name
        assert _imported_names(tree, "..consolidation.contracts") <= {"ConsolidatedResults"}, name
        assert _imported_names(tree, "..contracts") <= {"AcquisitionTerms"}, name


# =============================================================================
# 5. No duplicated authority, no cash flow, no later-stage surface
# =============================================================================


def test_the_package_reproduces_no_upstream_engine() -> None:
    """It reads completed results. It never touches a cash-flow series, a
    debt schedule, an IRR, a Strategy, a Scenario or a consolidation."""

    forbidden = {
        "levered_cash_flows",
        "unlevered_cash_flows",
        "levered_owner_cash_flow_by_year",
        "annual_debt_service",
        "remaining_loan_balance",
        "irr",
        "unlevered_irr",
        "levered_irr",
        "equity_multiple",
        "initial_equity",
        "loan_amount",
        "transaction_price",
        "purchase_price",
    }
    for name in _NAMES:
        assert not forbidden & _identifiers(_tree(_module(name))), name


def test_only_exit_reports_sale_economics() -> None:
    """``disposition_costs`` and ``net_sale_proceeds`` appear only on the
    reserved Exit view, so no As-Is, Stabilized or Custom valuation can be
    read as producing sale proceeds."""

    for name in _NAMES:
        source = _current(_module(name))
        for word in ("disposition_costs", "net_sale_proceeds"):
            if word not in source:
                continue
            assert name in {"contracts", "engine", "__init__"}, name


def test_no_module_names_a_later_stage_surface() -> None:
    """Checked against the code's own vocabulary -- every identifier, argument
    and attribute -- not its prose. A docstring may name what Stage 1 excludes
    and why; nothing Stage 1 executes may."""

    for name in _NAMES:
        vocabulary = {identifier.lower() for identifier in _identifiers(_tree(_module(name)))}
        for word in _FORBIDDEN_VOCABULARY:
            offenders = sorted(found for found in vocabulary if word in found)
            assert offenders == [], (name, word, offenders)


def test_stage_1_stated_no_schema_version() -> None:
    """Stage 1 adds no persistence, migration or schema version change. Stage 2
    advances the schema exactly once, which is its own ledger's claim."""

    assert _changes_since(_P7_10_BASE, "src/anchor/deals/store.py") == set()


def test_stage_1_adds_no_test_only_production_shim() -> None:
    """Every public name the package exports is used by the package itself or
    by the Capital Structure seam -- Stage 1 ships no surface that exists only
    for a later stage."""

    exported = {
        element.value
        for node in ast.walk(_tree("__init__".join((_PACKAGE + "/", ".py"))))
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        and isinstance(node.value, ast.List)
        for element in node.value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    defined: set[str] = set()
    for name in _NAMES:
        if name == "__init__":
            continue
        defined |= set(_definitions(_current(_module(name))))
    assert exported <= defined | {"ValuationMethod", "ValuationFundingResolution"}


# =============================================================================
# 6. No public API or wire contract changed (Stage 1 closeout)
# =============================================================================


def _dataclass_fields(source: str) -> dict[str, list[str]]:
    """Every top-level dataclass in ``source``, by name, with its annotated
    field names in declaration order. ``ClassVar`` is excluded: it is not a
    dataclass field and never reaches the wire."""

    found: dict[str, list[str]] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields = [
            item.target.id
            for item in node.body
            if isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and "ClassVar" not in ast.unparse(item.annotation)
        ]
        if fields:
            found[node.name] = fields
    return found


@pytest.mark.parametrize("path", _SEAM_MODULES)
def test_no_seam_dataclass_gained_or_lost_a_wire_field(path: str) -> None:
    """``anchor.api._wire`` serialises a contract by its dataclass fields, in
    order, so adding or removing one changes every existing response.

    Stage 1 changes no field of any Capital Structure contract. It widens
    ``ResolvedFundingEvent.amount_rule`` to admit the ``PctOfValue`` rule P7.7
    already represented -- a type annotation, not a field -- and deliberately
    threads the valuation operands nowhere: reporting them on this record is
    Stage 2 work precisely because a new field would be a wire change."""

    before = _dataclass_fields(_at_base(path))
    after = _dataclass_fields(_current(path))
    assert set(after) == set(before), path
    for name, fields in before.items():
        assert after[name] == fields, f"{path}::{name}"


def test_the_api_module_was_byte_identical_across_stage_1() -> None:
    """The routes, their methods, their payloads and the wire serialiser are
    all in ``api.py``. **Stage 1** adds no route and changes no response.

    Measured over Stage 1's committed range, because Stage 2 does add routes --
    which is its job. The claim this proves is unchanged and still exact: the
    accepted Stage 1 tree's ``api.py`` is the baseline's, byte for byte."""

    path = "src/anchor/api.py"
    assert _git("rev-parse", f"{_STAGE_1_HEAD}:{path}").strip() == _git(
        "rev-parse", f"{_P7_10_BASE}:{path}"
    ).strip()


def test_the_valuation_package_was_not_reachable_from_the_stage_1_api() -> None:
    """Stage 1 is a pure engine layer: nothing routed to it, so no unresolved
    valuation state could reach a client at all -- there was no path to one.

    Measured over the accepted Stage 1 tree. Stage 2 deliberately *does* reach
    it, because translating those states into the established structured
    unavailable / N/A representation is precisely the Stage 2 obligation
    Section 6.2 names. That neither state becomes a generic server error is
    proven by Stage 2's own suites, not relaxed here."""

    api = ast.parse(_git("show", f"{_STAGE_1_HEAD}:src/anchor/api.py"))
    assert not any("valuation" in found for found in _imports(api))
