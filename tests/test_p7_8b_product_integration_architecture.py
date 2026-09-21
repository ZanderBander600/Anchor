"""Phase 7 Gate P7.8B -- the production ledger and the architecture guards for
the Capital Structure product integration.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3 (P-4,
P-5, P-8, P-11), 12, 14.1 and 15, and
``docs/architecture/P7_8_PRODUCT_INTEGRATION.md``. Every git query reads objects
only (protocol 11.2). The guards hold:

1. **the P7.8B production ledger**, measured from Session A's reviewed head, and
   the P7.8A financial engine frozen byte for byte inside it;
2. **the layering** -- the Project fingerprint never learns that a Capital
   Structure exists, the structured one is built from it, and an empty structure
   collapses onto it exactly;
3. **whole-domain replacement**, never a merge, and inheritance kept distinct
   from an explicit empty structure;
4. **one position identity per Investment**, checked on every write path;
5. **nothing structured is persisted as financial authority**, and no later-gate
   economics or authoring surface appears.

Session A's own ledger and freeze are
``tests/test_p7_8_structured_position_architecture.py``.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: P7.8 Session A's reviewed head: the approved financial engine, and the base
#: of Session B's own committed range.
_P7_8A_HEAD = "f5850ade0bba907b0a2b9c329fa66abe131f5c23"

#: P7.8 Session B's reviewed head, merged into ``main`` as the second parent of
#: the P7.8 merge. Re-pinned at P7.9 Stage 1: the ledger below reads Session B's
#: own committed range ``f5850ad..69af6fe``, so a later gate's new files never
#: read as P7.8B changes while every P7.8B change stays proven.
_P7_8B_HEAD = "69af6fe31a93d7781e8fdaedc889b03d959fddde"

#: The P7.8 merge (PR #28) and its first parent, the P7.7 merge.
_P7_8_MERGE = "cf403c292f19e8e0e86b2e05a6be17300db83317"
_P7_7_MERGE = "a9f9b09fd71940cfdc079c109e9261187a041261"

_PACKAGE = "src/anchor/capital_structure"
_STRATEGY = "src/anchor/analysis/strategy.py"
_STORE = "src/anchor/deals/store.py"
_FINGERPRINT = "src/anchor/deals/fingerprint.py"
_CODEC = "src/anchor/deals/capital_structure_codec.py"
_IDENTITY = "src/anchor/deals/position_identity.py"
_STRUCTURED = "src/anchor/deals/structured_variants.py"
_MATRIX = "src/anchor/deals/decision_matrix.py"
_COMPARISON = "src/anchor/decision/comparison.py"
_CONTRACTS = "src/anchor/deals/contracts.py"
_VARIANTS = "src/anchor/deals/variants.py"
_INVESTMENT_VARIANTS = "src/anchor/deals/investment_variants.py"
_API = "src/anchor/api.py"

#: Every backend production file P7.8B changes, exactly:
#: - ``analysis/strategy.py``: the Investment-root overlay, the
#:   ``CAPITAL_STRUCTURE`` domain and the resolution of a variant's structure;
#: - ``deals/capital_structure_codec.py`` (new): the one spelling of each typed
#:   variant, for storage, the fingerprint and the wire;
#: - ``deals/position_identity.py`` (new): the cross-structure identity rule;
#: - ``deals/structured_variants.py`` (new): the structured variant service;
#: - ``deals/store.py``: schema v11, the six tables and the lifecycle;
#: - ``deals/contracts.py``: the persisted-structure contracts;
#: - ``deals/fingerprint.py``: the structured source fingerprint;
#: - ``deals/decision_matrix.py`` and ``decision/comparison.py``: the POSITION
#:   perspective;
#: - ``api.py``: the routes.
#:
#: ``deals/variants.py`` and ``deals/investment_variants.py`` are deliberately
#: **not** here. The Project pathway needed no change at all: a Strategy's
#: Investment-root overlays are dropped by the Strategy resolver itself
#: (``_unit_strategy``), so resolution, validation and the Project fingerprint
#: never see a Capital Structure -- which is P-4 holding in the code rather than
#: only in a docstring.
_P7_8B_BACKEND_FILES = frozenset(
    {
        _STRATEGY,
        _CODEC,
        _IDENTITY,
        _STRUCTURED,
        _STORE,
        _CONTRACTS,
        _FINGERPRINT,
        _MATRIX,
        _COMPARISON,
        _API,
    }
)


#: P7.10 Stage 1 re-pin. The ratified P7.10 contract activates the existing
#: ``PctOfValue`` funding rule (decision R-E). These four Capital Structure
#: modules are the whole seam that change carries, so they leave this gate's
#: working-tree freeze and become P7.10's ledger. Nothing is weakened: the
#: assertion below still proves they were untouched from this gate through the
#: accepted baseline `9c65843`, and `tests/test_p7_10_stage_1_architecture.py`
#: proves the P7.10 change is confined to its declared definitions.
_P7_10_SEAM = tuple(
    f"src/anchor/capital_structure/{name}.py"
    for name in ("execution_contracts", "execution_validation", "funding", "execution")
)

#: The accepted repository baseline P7.10 Stage 1 starts from (PR #48).
_P7_10_BASE = "9c658437f76e8815cb228d4b71b11aaa473450d4"

#: The P7.8A financial engine: executed by this gate, edited by none of it.
#: P7.10 Stage 1 re-pin: the four seam modules move to the assertion above.
_P7_8A_FINANCIAL = tuple(
    f"{_PACKAGE}/{name}.py"
    for name in ("debt_position", "preferred", "metrics")
)

#: The P7.7 foundation and the mature engine: consumed, never changed.
_FROZEN = (
    *_P7_8A_FINANCIAL,
    *(f"{_PACKAGE}/{name}.py" for name in ("contracts", "validation", "legacy", "foundation")),
    f"{_PACKAGE}/__init__.py",
    "src/anchor/engine/debt.py",
    "src/anchor/engine/acquisition.py",
    "src/anchor/engine/noi.py",
    "src/anchor/engine/returns.py",
    "src/anchor/consolidation/engine.py",
)

#: Everything P7.8B consumes and changes none of.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/consolidation",
    "src/anchor/investment",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/analysis/scenario.py",
    "src/anchor/analysis/business_plan_analysis.py",
    "src/anchor/analysis/sensitivity.py",
    "src/anchor/analysis/break_even.py",
    "src/anchor/deals/variants.py",
    "src/anchor/deals/investment_variants.py",
    _PACKAGE,
)

#: Exactly the modules outside the package that may import it, and why: the
#: Strategy engine (the root overlay's content contract), the codec and the
#: identity rule (its shapes), the store (persistence), the fingerprint (the
#: canonical payload), the structured service (the executor), the comparison and
#: the matrix (its result contracts), the Deal contracts, and the routes.
_CAPITAL_STRUCTURE_IMPORTERS = [
    "anchor/analysis/strategy.py",
    "anchor/api.py",
    "anchor/deals/capital_structure_codec.py",
    "anchor/deals/contracts.py",
    "anchor/deals/decision_matrix.py",
    "anchor/deals/fingerprint.py",
    "anchor/deals/position_identity.py",
    "anchor/deals/store.py",
    "anchor/deals/structured_variants.py",
    "anchor/decision/comparison.py",
    # P7.9 Stage 1: the Common Equity seam reads the structured result, and the
    # Partnership contracts reuse two calculation-free shapes.
    "anchor/partnership/common_equity.py",
    "anchor/partnership/contracts.py",
]


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


def _changes_between(start: str, end: str, *paths: str) -> set[str]:
    """Files that differ between two commits, renames split into their removal
    and addition. Reads Git objects only."""

    return {path for path in _git("diff", "--name-only", "--no-renames", start, end, "--", *paths).split() if path}


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _tree(path: str) -> ast.Module:
    return ast.parse(_current(path))


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


def _identifiers(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found.add(node.name)
    return found


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


# =============================================================================
# 1. The ledger, and the financial freeze inside it
# =============================================================================


def test_p7_8b_changed_exactly_its_authorized_backend_files() -> None:
    """The P7.8B backend ledger: Session B's committed range, from Session A's
    reviewed head to Session B's reviewed head (re-pinned at P7.9 Stage 1).

    Never widen it to admit a financial module: P7.8B executes the approved
    engine and edits none of it."""

    changed = {
        path
        for path in _changes_between(_P7_8A_HEAD, _P7_8B_HEAD, "src")
        if _is_production(path)
    }
    assert sorted(changed - _P7_8B_BACKEND_FILES) == []
    assert sorted(_P7_8B_BACKEND_FILES - changed) == []


def test_the_p7_8b_ledger_head_is_the_second_parent_of_the_p7_8_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_8_MERGE).split()[1:]
    assert parents == [_P7_7_MERGE, _P7_8B_HEAD]


@pytest.mark.parametrize("path", _FROZEN)
def test_the_financial_engine_is_frozen_at_session_as_reviewed_head(path: str) -> None:
    """The P7.8A economics, the P7.7 foundation and the mature engine are byte
    for byte what the human review approved."""

    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_P7_8A_HEAD}:{path}").strip(), path


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged(path: str) -> None:
    """P7.10 Stage 1 re-pin: its four declared seam files are excepted, and are
    proven separately below. Every other file under every protected path is
    still unchanged."""

    assert _changes_since(_P7_8A_HEAD, path) - set(_P7_10_SEAM) == set(), f"{path} changed at P7.8B"


@pytest.mark.parametrize("path", _P7_10_SEAM)
def test_each_p7_10_seam_module_was_frozen_through_the_accepted_baseline(path: str) -> None:
    """P7.8B's claim, still proven: these four files were byte-identical to
    P7.8A's reviewed head from this gate through the accepted baseline
    `9c65843`. Only the separately ratified P7.10 Stage 1 changes them."""

    assert _git("rev-parse", f"{_P7_10_BASE}:{path}").strip() == _git("rev-parse", f"{_P7_8A_HEAD}:{path}").strip(), path


def test_only_the_named_layers_import_the_capital_structure() -> None:
    """P7.8A proved nothing outside the package imported it. P7.8B connects it
    to exactly these layers -- persistence, identity, fingerprints, the
    structured service, the comparison and the routes -- and to nothing that
    calculates project economics."""

    importers = sorted(
        path.relative_to(_PROJECT_ROOT / "src").as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        if "capital_structure" not in path.relative_to(_PROJECT_ROOT / "src" / "anchor").parts[:1]
        and any("capital_structure" in name for name in _imports(ast.parse(path.read_text(encoding="utf-8"))))
    )
    assert importers == _CAPITAL_STRUCTURE_IMPORTERS


# =============================================================================
# 2. Layering: the Project fingerprint never learns a structure exists
# =============================================================================


def test_the_project_fingerprint_path_reads_no_capital_structure() -> None:
    """P-4 in the code: the per-Unit and per-Investment resolved-input
    fingerprints are the P7.2 / P7.4 / P7.6 functions, and no Capital Structure
    reaches them."""

    for path, name in (
        (_VARIANTS, "fingerprint_resolved_inputs"),
        (_INVESTMENT_VARIANTS, "fingerprint_investment_variant"),
    ):
        function = _functions(_tree(path))[name]
        text = ast.unparse(function)
        assert "capital_structure" not in text, path
        assert "structured" not in text, path


def test_the_structured_fingerprint_is_built_from_the_project_one() -> None:
    function = _functions(_tree(_FINGERPRINT))["fingerprint_structured_source"]
    text = ast.unparse(function)
    assert "project_source_fingerprint" in text and "capital_structure_payload" in text


def test_an_empty_structure_returns_the_project_fingerprint_itself() -> None:
    """FP-2 as a statement about the code, not only about a digest: the empty
    case returns the argument, so nothing can make it a second hash."""

    function = _functions(_tree(_FINGERPRINT))["fingerprint_structured_source"]
    guard = next(
        node
        for node in function.body
        if isinstance(node, ast.If) and "capital_structure.positions" in ast.unparse(node.test)
    )
    assert ast.unparse(guard.test) == "not capital_structure.positions"
    assert [ast.unparse(statement) for statement in guard.body] == [
        "return project_source_fingerprint"
    ]


def test_the_canonical_payload_excludes_presentation() -> None:
    """FP-1: a position's name and a fee's description never reach the digest;
    the stable position id does, because POSITION(position_id) addresses it."""

    payload = _functions(_tree(_FINGERPRINT))["_position_payload"]
    text = ast.unparse(payload)
    assert "position.position_id" in text
    assert "position.name" not in text
    assert "description" not in ast.unparse(_functions(_tree(_FINGERPRINT))["_terms_payload"])


def test_the_position_matrix_reads_structured_fingerprints_and_the_project_matrix_does_not() -> None:
    matrix = _functions(_tree(_MATRIX))
    position_cell = ast.unparse(matrix["_position_cell"])
    project_cell = ast.unparse(matrix["_cell"])
    assert "structured_source_fingerprint" in position_cell
    assert "structured" not in project_cell and "capital" not in project_cell


# =============================================================================
# 3. Whole replacement, and inheritance kept distinct from an explicit empty
# =============================================================================


def test_the_resolution_replaces_and_never_merges() -> None:
    """ST-2: the resolved structure is one owner's or the other's. No loop, no
    concatenation, no field-by-field composition."""

    function = _functions(_tree(_STRATEGY))["resolve_capital_structure"]
    assert ast.unparse(function.body[-1]) == (
        "return base_capital_structure if own is None else own"
    )
    assert not [node for node in ast.walk(function) if isinstance(node, (ast.For, ast.While))]
    assert not [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
    ]


def test_inheritance_is_the_absence_of_a_structure_not_a_copy_of_one() -> None:
    """A Strategy that inherits stores no marker at all, and one that states an
    empty structure stores a marker with no position. The two are different rows
    and different answers."""

    store = _functions(_tree(_STORE))
    writer = ast.unparse(store["_write_strategy_root_overlays"])
    assert "if own is None:\n        return" in writer
    reader = ast.unparse(store["_strategy_from_rows"])
    assert "root_overlays=() if own_structure is None else" in reader
    replace = ast.unparse(store["_replace_capital_structure"])
    assert "if capital_structure.positions or owner_kind == _STRATEGY_OWNER_KIND:" in replace


# =============================================================================
# 4. One position identity per Investment, on every write path
# =============================================================================


def test_every_capital_structure_write_checks_position_identity() -> None:
    store = _functions(_tree(_STORE))
    for name in ("set_base_capital_structure", "set_deal_capital_structure"):
        assert "_require_coherent_identity" in _calls(store[name]), name
    for name in ("create_strategy", "create_strategy_for_deal", "update_strategy"):
        assert "_require_coherent_strategy_identity" in _calls(store[name]), name


def test_the_identity_rule_names_class_and_scope_and_nothing_else() -> None:
    """Terms, funding, priority, the name and the resolution are what a Strategy
    varies; only the class and the scope are identity (P-8)."""

    identity = _functions(_tree(_IDENTITY))["position_identity_issues"]
    text = ast.unparse(identity)
    assert "position.position_class" in text and "_scope_key(position.scope)" in text
    for varying in ("terms", "funding", "priority", "shortfall_resolution"):
        assert f"position.{varying}" not in text, varying


def test_no_identifier_is_regenerated_anywhere_in_the_new_backend() -> None:
    """A different economic instrument gets a new id from the analyst; the
    backend never mints one for a position, an event or a fee."""

    for path in (_IDENTITY, _STRUCTURED, _FINGERPRINT, _CODEC):
        assert "uuid" not in _current(path), path
    store_uuid_users = sorted(
        name
        for name, function in _functions(_tree(_STORE)).items()
        if "uuid4" in ast.unparse(function) and "capital" in name
    )
    assert store_uuid_users == ["_write_capital_structure"]  # the structure row's own id


# =============================================================================
# 5. Nothing structured is persisted, and no later-gate surface appears
# =============================================================================


def test_no_structured_result_is_stored() -> None:
    """A structured result is recomputed on request (Q14). The six new tables
    hold authored contracts only -- positions, funding, fees and terms -- and no
    result, series, metric or snapshot."""

    text = _current(_STORE)
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (capital_\w+)", text))
    assert created == {
        "capital_structures",
        "capital_positions",
        "capital_funding_events",
        "capital_position_fees",
        "capital_debt_terms",
        "capital_preferred_terms",
    }
    for forbidden in ("irr", "moic", "cash_flow", "snapshot", "result"):
        assert not re.search(rf"capital_\w*{forbidden}", text), forbidden


def test_the_structured_service_reads_the_store_and_never_writes_it() -> None:
    service = _tree(_STRUCTURED)
    written = {name for name in _calls(service) if name.startswith(("put_", "set_", "create_", "delete_", "update_"))}
    assert written == set()


def test_no_later_gate_economics_reach_the_new_surface() -> None:
    later = re.compile(
        r"refinanc|recapitali|waterfall|partner|promote|hurdle|catch_up|capital_call|draw_schedule",
        re.IGNORECASE,
    )
    for path in (_STRUCTURED, _IDENTITY, _CODEC):
        assert not {name for name in _identifiers(_tree(path)) if later.search(name)}, path
    # Re-scoped at P7.9 Stage 2, the gate authorized to add the Partnership
    # fingerprint to ``fingerprint.py``: the P7.8B structured fingerprint itself
    # -- every function P7.8B added there -- still names no later-gate concept.
    fingerprint = _functions(_tree(_FINGERPRINT))
    for name in (
        "_event_order",
        "_amount_rule_payload",
        "_terms_payload",
        "_position_payload",
        "capital_structure_payload",
        "fingerprint_structured_source",
    ):
        assert not {found for found in _identifiers(fingerprint[name]) if later.search(found)}, name
    assert later.search("RefinanceEvent") and later.search("partner_share")


def test_the_authoring_surface_refuses_the_unexecutable_subset() -> None:
    """Persistence can represent every P7.7 contract; the routes accept only
    what P7.8 executes, and say so with P7.8A's own stable codes.

    **Re-pinned at P7.10 Stage 2.** ``UNSUPPORTED_AMOUNT_RULE`` is gone from the
    list because the rule it refused is no longer unexecutable: this gate's own
    refusal message said ``PctOfValue`` "arrives with valuation timepoints", and
    they have arrived. The refusal is retired rather than relaxed, and every
    other unexecutable convention is refused exactly as before. That a
    ``PctOfValue`` rule naming an undefined or unresolvable timepoint still
    produces no amount -- a typed unavailable funding state instead -- is proved
    by ``tests/test_p7_10_stage_2_valuation_and_freshness.py`` and
    ``tests/test_p7_10_stage_2_api.py``."""

    api = _current(_API)
    for code in (
        "UNSUPPORTED_FUNDING_TIMING",
        "UNSUPPORTED_FEE_TIMING",
        "UNSUPPORTED_DEBT_PIK",
        "UNSUPPORTED_DEBT_CURRENT_PAY",
    ):
        assert f"ExecutionIssueCode.{code}" in api, code
    assert "PctOfValue" in api  # now named to construct it, not only to refuse it


def test_no_case_or_competition_identifier() -> None:
    import test_p7_0_decision_architecture as p7_0

    for path in sorted(_P7_8B_BACKEND_FILES):
        assert p7_0._case_identifiers_in(_current(path)) == [], path
