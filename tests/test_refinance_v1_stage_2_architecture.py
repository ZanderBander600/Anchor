"""Refinance & Capital Events V1 Stage 2 -- the architecture guard.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 14, 16, 19 and 20
(Stage 2). Every git query reads objects only (protocol 11.2). The guards hold:

1. **the ledger**: Stage 2 changes exactly its declared production files since
   the accepted baseline ``f2b5cef``, each named, and no frontend, report,
   export, memo-layout or decision-matrix file (Stage 3);
2. **the Stage 1 byte freeze**: every production file of the accepted Stage 1
   engine (PR #57, ``2e1f84a..6de7644``) is byte-identical to its accepted
   merge, and every engine and upstream package is unchanged since ``f2b5cef``;
3. **schema ownership**: schema 17 adds exactly six typed, relational tables --
   no JSON blob, no ALTER, and ``capital_funding_events`` untouched;
4. **one codec, one fingerprint authority**: each capital-event token is spelled
   in the codec alone, and the structured fingerprint has one definition;
5. **LTV-only valuation consumption and FP-2** in the source itself;
6. **no financial arithmetic**: the new modules have none, and every changed
   module's arithmetic is exactly its baseline's.

This is Stage 2's own guard, measured in the working tree while the stage is
unmerged. A later gate re-pins it to Stage 2's committed range, as the Stage 1
guard is re-pinned here.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Accepted ``main`` when Stage 2 began (PR #59 merge; product tree ``6de7644``).
_BASE = "f2b5cefa7fca3ecde7621927c5818cbc40c068cd"
#: The accepted Stage 1 engine: PR #57, from the contract merge to its merge.
_STAGE_1_BASE = "2e1f84aaa7c93b3247e8dbc6ded8b4397124d36b"
_STAGE_1_MERGE = "6de7644"

_DEALS = "src/anchor/deals"
_API = "src/anchor/api.py"
_STORE = f"{_DEALS}/store.py"
_CODEC = f"{_DEALS}/capital_structure_codec.py"
_FINGERPRINT = f"{_DEALS}/fingerprint.py"
_STRUCTURED = f"{_DEALS}/structured_variants.py"
_PARTNERSHIP = f"{_DEALS}/partnership_variants.py"
_IDENTITY = f"{_DEALS}/capital_event_identity.py"
_INTEGRATION = f"{_DEALS}/refinance_integration.py"
#: Review correction: the exact-scope evidence authority and the exact-scope
#: publication requirement live in P7.10 Stage 2's own seams.
_VALUATION_VIEWS = f"{_DEALS}/valuation_views.py"
_MEMO_DEPENDENCIES = f"{_DEALS}/memo_dependencies.py"

#: Second review correction: the additive P7.10 amendment (the typed
#: ``EVIDENCE_NOT_APPROVED`` valuation reason and its wire mapping), the typed
#: consumer of a consumed value, the temporary Stage 3 report gate, and the
#: exact-scope presentation of a consumed Unit cell. Every other file of these
#: packages stays frozen.
_VALUATION_CONTRACTS = "src/anchor/valuation/contracts.py"
_AVAILABILITY = "src/anchor/memo/availability.py"
_MEMO_CONTRACTS = "src/anchor/memo/contracts.py"
_PUBLICATION = "src/anchor/memo/publication.py"
_ASSEMBLY = "src/anchor/reporting/assembly.py"
#: The workspace's refusal catalog: the one frontend edit, so the new gate
#: refusal reads as its own analyst sentence rather than the default grouping.
_MEMO_CATALOG = "web/src/memoCatalog.ts"
_P7_10_AMENDED = (_VALUATION_CONTRACTS, _AVAILABILITY, _MEMO_CONTRACTS, _PUBLICATION, _ASSEMBLY)
#: Non-Python production files, kept out of the AST guards below.
_FRONTEND = (_MEMO_CATALOG,)

_NEW = (_IDENTITY, _INTEGRATION)
_CHANGED = (
    _API,
    _STORE,
    _CODEC,
    _FINGERPRINT,
    _STRUCTURED,
    _PARTNERSHIP,
    _VALUATION_VIEWS,
    _MEMO_DEPENDENCIES,
    *_P7_10_AMENDED,
)

#: Every production file Stage 2 changes, exactly (Section 20, Stage 2).
_STAGE_2_PRODUCTION_FILES = frozenset((*_NEW, *_CHANGED, *_FRONTEND))

#: Stage 3 surfaces and every upstream Stage 2 consumes: none changes.
_PROTECTED = (
    "web",
    "src/anchor/capital_structure",
    "src/anchor/engine",
    "src/anchor/valuation",
    "src/anchor/partnership",
    "src/anchor/consolidation",
    "src/anchor/analysis",
    "src/anchor/memo",
    "src/anchor/reporting",
    "src/anchor/exports",
    "src/anchor/decision",
    "src/anchor/investment",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/asset_management",
    f"{_DEALS}/decision_matrix.py",
    f"{_DEALS}/variants.py",
    f"{_DEALS}/investment_variants.py",
    f"{_DEALS}/position_identity.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
)

#: The six capital-event tables schema 17 adds, each a Capital Structure child.
_TABLES = frozenset(
    {
        "capital_events",
        "capital_event_retirements",
        "capital_event_constraints",
        "capital_event_valuation_refs",
        "capital_event_costs",
        "capital_refinance_proceeds",
    }
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and not path.endswith((".test.ts", ".test.tsx"))


def _changes_since(base: str, *paths: str) -> set[str]:
    """Committed, staged, unstaged and untracked changes since ``base``."""

    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path and "__pycache__" not in path}


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _at(commit: str, path: str) -> str:
    return _git("show", f"{commit}:{path}").replace("\r\n", "\n")


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


def _code(source: str) -> ast.Module:
    return _without_docstrings(ast.parse(source))


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod, ast.MatMult)


def _is_text(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str))


def _arithmetic(tree: ast.AST) -> list[str]:
    return sorted(
        ast.unparse(child)
        for child in ast.walk(tree)
        if (
            isinstance(child, (ast.BinOp, ast.AugAssign))
            and isinstance(child.op, _ARITHMETIC)
            and not (isinstance(child, ast.BinOp) and (_is_text(child.left) or _is_text(child.right)))
        )
        or (isinstance(child, ast.UnaryOp) and isinstance(child.op, (ast.USub, ast.UAdd)))
    )


# =============================================================================
# 1. The ledger
# =============================================================================


def test_stage_2_changes_exactly_its_declared_production_files() -> None:
    changed = {path for path in _changes_since(_BASE, "src", "web") if _is_production(path)}
    assert changed == set(_STAGE_2_PRODUCTION_FILES), (
        f"unexpected: {sorted(changed - _STAGE_2_PRODUCTION_FILES)}; missing: {sorted(_STAGE_2_PRODUCTION_FILES - changed)}"
    )


def test_the_ledger_base_is_the_accepted_stage_1_closeout() -> None:
    """``f2b5cef`` is PR #59's merge, and its product tree is Stage 1's
    accepted merge ``6de7644``: the two closeout PRs changed documentation only."""

    parents = _git("rev-list", "--parents", "-n", "1", _BASE).split()[1:]
    assert [parent[:7] for parent in parents] == ["4f00d4b", "e8b0844"]
    assert _git("diff", "--name-only", _STAGE_1_MERGE, _BASE, "--", "src", "web", "tests").split() == []


def test_the_new_modules_are_new_at_this_stage() -> None:
    for path in _NEW:
        assert _git("ls-tree", "--name-only", _BASE, path).strip() == "", path


@pytest.mark.parametrize("path", _PROTECTED)
def test_no_stage_3_path_and_no_upstream_changed(path: str) -> None:
    """Nothing under a protected path changes except the five named P7.10
    amendment files, each of which its own guard below holds to exactly its
    declared change."""

    assert _changes_since(_BASE, path) - set(_P7_10_AMENDED) - set(_FRONTEND) == set(), path


def _top_level(tree: ast.Module) -> dict[str, str]:
    """Every top-level statement, by the name it binds, as source."""

    found: dict[str, str] = {}
    for index, node in enumerate(tree.body):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        else:
            name = f"<statement {index}: {type(node).__name__}>"
        found[name] = ast.unparse(node)
    return found


def _members(source: str, class_name: str) -> list[str]:
    (node,) = [item for item in _code(source).body if isinstance(item, ast.ClassDef) and item.name == class_name]
    return [ast.unparse(item) for item in node.body if isinstance(item, ast.Assign)]


def test_the_p7_10_valuation_amendment_adds_one_reason_and_nothing_else() -> None:
    """``ValuationUnavailableReason`` gains ``EVIDENCE_NOT_APPROVED``, appended;
    no other statement of the valuation contracts changes."""

    current, base = _current(_VALUATION_CONTRACTS), _at(_BASE, _VALUATION_CONTRACTS)
    assert _members(current, "ValuationUnavailableReason") == [
        *_members(base, "ValuationUnavailableReason"),
        "EVIDENCE_NOT_APPROVED = 'evidence_not_approved'",
    ]
    now, then = _top_level(_code(current)), _top_level(_code(base))
    assert now.keys() == then.keys()
    assert {name for name in now if now[name] != then[name]} == {"ValuationUnavailableReason"}


def test_the_p7_10_wire_amendment_maps_the_new_reason_explicitly() -> None:
    current, base = _current(_AVAILABILITY), _at(_BASE, _AVAILABILITY)
    now, then = _top_level(_code(current)), _top_level(_code(base))
    assert now.keys() == then.keys()
    assert {name for name in now if now[name] != then[name]} == {"_VALUATION_REASON_CODES"}
    assert (
        "ValuationUnavailableReason.EVIDENCE_NOT_APPROVED: UnavailableReasonCode.EVIDENCE_NOT_APPROVED"
        in now["_VALUATION_REASON_CODES"]
    )


#: Exactly what the refusal catalog gains: one grouping and one sentence for the
#: new code. Nothing else in the frontend changes.
_CATALOG_ADDITIONS = (
    "  refinance_reporting_not_available: 'decision',\n",
    "  refinance_reporting_not_available:\n"
    "    'The selected Capital Structure includes a refinance, and refinance reporting is not available yet. "
    "Select a Strategy whose Capital Structure has no refinance to publish now.',\n",
)


def test_the_frontend_gains_only_the_gate_refusal_in_its_catalog() -> None:
    current = _current(_MEMO_CATALOG)
    for addition in _CATALOG_ADDITIONS:
        assert current.count(addition) == 1, addition
        current = current.replace(addition, "")
    assert current == _at(_BASE, _MEMO_CATALOG)
    assert {path for path in _changes_since(_BASE, "web")} == {_MEMO_CATALOG}


def test_the_memo_contracts_gain_only_the_typed_consumer() -> None:
    current, base = _current(_MEMO_CONTRACTS), _at(_BASE, _MEMO_CONTRACTS)
    now, then = _top_level(_code(current)), _top_level(_code(base))
    assert now.keys() - then.keys() == {"ValuationConsumerKind"} and then.keys() <= now.keys()
    assert {name for name in then if now[name] != then[name]} == set()
    assert _members(current, "ValuationConsumerKind") == [
        "PCT_OF_VALUE = 'pct_of_value'",
        "REFINANCE_LTV = 'refinance_ltv'",
    ]


def test_the_ledger_guard_has_teeth() -> None:
    assert _changes_since(_BASE, _IDENTITY) == {_IDENTITY}
    assert _changes_since(_BASE, "src/anchor/engine/debt.py") == set()


# =============================================================================
# 2. The Stage 1 byte freeze
# =============================================================================


def _stage_1_production_files() -> list[str]:
    changed = _git("diff", "--name-only", "--no-renames", _STAGE_1_BASE, _STAGE_1_MERGE, "--", "src", "web").split()
    return sorted(path for path in changed if _is_production(path))


def test_the_stage_1_production_set_is_the_accepted_one() -> None:
    assert len(_stage_1_production_files()) == 12
    assert "src/anchor/capital_structure/refinance_execution.py" in _stage_1_production_files()


@pytest.mark.parametrize("path", _stage_1_production_files())
def test_every_stage_1_production_file_is_byte_identical_to_its_accepted_merge(path: str) -> None:
    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_STAGE_1_MERGE}:{path}").strip(), path


# =============================================================================
# 3. Schema ownership: six typed tables, no blob, no ALTER
# =============================================================================


def _created(source: str) -> set[str]:
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \(", source))


def _ddl(source: str, table: str) -> str:
    """One table's whole DDL, from its CREATE to the end of its SQL constant."""

    found = re.search(rf'CREATE TABLE IF NOT EXISTS {table} \((.*?)"""', source, re.DOTALL)
    assert found is not None, table
    return found.group(1)


def test_schema_17_adds_exactly_the_six_tables() -> None:
    store, base = _current(_STORE), _at(_BASE, _STORE)
    assert "_SCHEMA_VERSION = 17" in store and "_SCHEMA_VERSION = 16" in base
    assert _created(store) - _created(base) == _TABLES | {_MEMO_TABLE}
    assert _created(base) <= _created(store)


#: Review correction: the frozen exact-scope record of what a published memo
#: version consumed. Keyed by the version, typed, and never updated.
_MEMO_TABLE = "memo_version_consumed_valuations"


def test_the_memo_consumption_record_is_typed_scoped_and_append_only() -> None:
    store = _current(_STORE)
    ddl = _ddl(store, _MEMO_TABLE)
    assert "PRIMARY KEY (version_id, timepoint_id, scope_kind, unit_id, consumer_kind)" in ddl
    assert "CHECK (scope_kind IN ('unit', 'investment'))" in ddl
    assert "CHECK (consumer_kind IN ('pct_of_value', 'refinance_ltv'))" in ddl
    assert "CHECK ((scope_kind = 'unit') = (unit_id <> ''))" in ddl
    # An audit record of *what* was consumed, never of an amount: exactly these
    # typed text columns, and no value, amount, blob or payload column.
    columns = re.findall(r"^\s*(\w+)\s+(TEXT|REAL|INTEGER|BLOB|JSON)\b", ddl, re.MULTILINE)
    assert columns == [
        ("version_id", "TEXT"),
        ("timepoint_id", "TEXT"),
        ("scope_kind", "TEXT"),
        ("unit_id", "TEXT"),
        ("consumer_kind", "TEXT"),
    ]
    assert not re.search(r"json|blob|payload|amount", ddl, re.IGNORECASE)
    assert not re.search(rf"UPDATE\s+{_MEMO_TABLE}", store, re.IGNORECASE)


def test_the_memo_consumption_record_is_a_canonical_version_child() -> None:
    """Deleted through the canonical version-child inventory, never by a
    one-off list, so it can never outlive its version."""

    tree = _code(_current(_STORE))
    (inventory,) = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "_MEMO_VERSION_CHILD_TABLES"
    ]
    assert f"'{_MEMO_TABLE}'" in ast.unparse(inventory.value)
    (deleter,) = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_delete_investment_memos"]
    assert f"'{_MEMO_TABLE}'" not in ast.unparse(deleter)


def test_no_accepted_table_is_altered_or_redefined() -> None:
    store, base = _current(_STORE), _at(_BASE, _STORE)
    assert store.count("ALTER TABLE") == base.count("ALTER TABLE")
    for table in _created(base):
        assert _ddl(store, table) == _ddl(base, table), table
    assert "capital_funding_events" not in {name for name in _TABLES}


def test_the_six_tables_are_typed_and_relational_never_a_blob() -> None:
    store = _current(_STORE)
    for table in _TABLES:
        ddl = _ddl(store, table)
        columns = re.findall(r"^\s*(\w+)\s+(TEXT|REAL|INTEGER|BLOB|JSON)\b", ddl, re.MULTILINE)
        assert columns and all(kind in {"TEXT", "REAL", "INTEGER"} for _, kind in columns), table
        assert "structure_id" in {name for name, _ in columns}, table
        assert not re.search(r"json|blob|payload|document|reserve|holdback|escrow", ddl, re.IGNORECASE), table
        assert "PRIMARY KEY (structure_id" in ddl, table


def test_event_rows_are_deleted_explicitly_with_their_structure() -> None:
    store = _code(_current(_STORE))
    for name in ("_delete_capital_structure", "_delete_investment_capital_structures"):
        (function,) = [node for node in store.body if isinstance(node, ast.FunctionDef) and node.name == name]
        assert "_CAPITAL_EVENT_TABLES" in ast.unparse(function), name


# =============================================================================
# 4. One codec, one fingerprint authority
# =============================================================================


_TOKENS = ("refinance_proceeds", "authored_position", "legacy_acquisition_loan")


def test_each_capital_event_token_is_spelled_by_the_codec_alone() -> None:
    """Storage, the fingerprint and the routes read the codec's members; none
    spells a token as its own literal (a SQL column value compared in the store
    reads the member's ``.value``)."""

    for path in (*_CHANGED, *_NEW):
        if path == _CODEC:
            continue
        literals = {
            node.value
            for node in ast.walk(_code(_current(path)))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in _TOKENS
        }
        assert literals == set(), (path, literals)
    codec = _current(_CODEC)
    assert all(f'"{token}"' in codec for token in _TOKENS)


def test_the_structured_fingerprint_has_one_definition() -> None:
    defining = {
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name in {"fingerprint_structured_source", "capital_events_payload"}
    }
    assert defining == {_FINGERPRINT}
    for path in (*_NEW, _STRUCTURED, _PARTNERSHIP):
        assert "hashlib" not in _imports(ast.parse(_current(path))), path


# =============================================================================
# 5. FP-2 and LTV-only consumption in the source
# =============================================================================


def test_the_event_payload_joins_only_when_events_exist() -> None:
    (function,) = [
        node
        for node in _code(_current(_FINGERPRINT)).body
        if isinstance(node, ast.FunctionDef) and node.name == "fingerprint_structured_source"
    ]
    joins = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.If) and "_CAPITAL_EVENTS_KEY" in ast.unparse(node) and ast.unparse(node.test) == "events"
    ]
    assert len(joins) == 1


def test_only_an_ltv_enabled_event_names_a_consumed_valuation() -> None:
    (function,) = [
        node
        for node in _code(_current(_INTEGRATION)).body
        if isinstance(node, ast.FunctionDef) and node.name == "refinance_valuation_scopes"
    ]
    assert "event.sizing.max_ltv is not None" in ast.unparse(function)


def test_the_refinance_adapter_never_rewrites_a_message_as_text() -> None:
    """Review correction (Section 15.3): typed objects decide meaning, and
    prose is never parsed, searched or edited. ``refinance_integration`` calls
    no ``str`` method that reads or rewrites text -- ``replace``, ``split``,
    ``find``, ``startswith`` and the rest -- and tests no substring with
    ``in`` against a message. ``dataclasses.replace`` (a bare name) rebuilds a
    typed object and is the only ``replace`` it calls."""

    tree = _code(_current(_INTEGRATION))
    text_methods = {
        "replace", "split", "rsplit", "partition", "rpartition", "find", "rfind", "index", "rindex",
        "startswith", "endswith", "removeprefix", "removesuffix", "count", "strip", "lstrip", "rstrip", "sub",
    }
    called = sorted(
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in text_methods
    )
    assert called == [], called
    assert "re" not in _imports(tree)
    messages_tested = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
        and "message" in ast.unparse(node)
    ]
    assert messages_tested == [], messages_tested


def test_the_message_guard_would_see_a_string_replacement() -> None:
    injected = _current(_INTEGRATION) + "\n\ndef _restated(message, old, new):\n    return message.replace(old, new)\n"
    tree = _code(injected)
    assert [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "replace"]


def test_the_evidence_authority_offers_every_timepoint_exact_scope() -> None:
    """Review correction (P7.10 Section 6, R-E): the authority withholds cells,
    never whole timepoints -- every view is offered, through ``gated_result``."""

    (function,) = [
        node
        for node in _code(_current(_VALUATION_VIEWS)).body
        if isinstance(node, ast.FunctionDef) and node.name == "funding_authority"
    ]
    source = ast.unparse(function)
    assert "gated_result(" in source and "not in blocked" not in source


def test_no_readiness_route_or_stage_3_surface_is_added() -> None:
    api = _code(_current(_API))
    routes = {
        ast.unparse(decorator.args[0])
        for node in ast.walk(api)
        if isinstance(node, ast.FunctionDef)
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call) and decorator.args and ast.unparse(decorator.func).startswith("app.")
    }
    base_routes = {
        ast.unparse(decorator.args[0])
        for node in ast.walk(_code(_at(_BASE, _API)))
        if isinstance(node, ast.FunctionDef)
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call) and decorator.args and ast.unparse(decorator.func).startswith("app.")
    }
    assert routes == base_routes


# =============================================================================
# 6. No financial arithmetic outside the accepted engine
# =============================================================================


@pytest.mark.parametrize("path", _NEW)
def test_each_new_module_has_no_arithmetic(path: str) -> None:
    assert _arithmetic(_code(_current(path))) == [], path


#: The only operators Stage 2 adds to an accepted module, none of them on money:
#: the store's orphan check is a set difference over stored identities.
_ADDED_NON_FINANCIAL = {
    _STORE: ["(set(retirements) | set(constraints) | set(valuations) | set(costs)) - known"],
}


@pytest.mark.parametrize("path", _CHANGED)
def test_each_changed_module_keeps_exactly_its_baseline_arithmetic(path: str) -> None:
    assert _arithmetic(_code(_current(path))) == sorted(
        _arithmetic(_code(_at(_BASE, path))) + _ADDED_NON_FINANCIAL.get(path, [])
    ), path


def test_the_arithmetic_guard_would_see_a_second_formula() -> None:
    injected = _current(_INTEGRATION) + "\n\ndef _net(gross, payoff):\n    return gross - payoff\n"
    assert _arithmetic(_code(injected)) != []


def test_the_deals_modules_that_read_the_refinance_layer_are_exactly_named() -> None:
    """Stage 2 connects the persisted analysis to the accepted refinance
    contracts in these deals modules and nowhere else. The refinance *engine*
    (plan, execution, validation) is reached only through the P7.8 executor."""

    readers = {
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / _DEALS).rglob("*.py")
        if {
            module
            for module in _imports(ast.parse(path.read_text(encoding="utf-8")))
            if "refinance" in module or module.endswith(".events") or "event_validation" in module
        }
    }
    # ``memo_dependencies`` reads only ``has_capital_events``, for the
    # temporary Stage 3 report gate (second review correction).
    assert readers == {
        _STORE, _CODEC, _FINGERPRINT, _IDENTITY, _INTEGRATION, _STRUCTURED, _PARTNERSHIP, _MEMO_DEPENDENCIES,
    }
    engine = re.compile(r"capital_structure\.(refinance|refinance_execution|event_validation)$")
    for path in (_PROJECT_ROOT / _DEALS).rglob("*.py"):
        assert not {module for module in _imports(ast.parse(path.read_text(encoding="utf-8"))) if engine.search(module)}, path


# =============================================================================
# 7. The temporary Stage 3 report gate and truthful refusals (second review
#    correction)
# =============================================================================


def _function(path: str, name: str) -> ast.FunctionDef:
    (found,) = [
        node for node in ast.walk(_code(_current(path))) if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    return found


def test_one_gate_serves_readiness_publication_and_preview() -> None:
    """The readiness route and ``publish`` both judge through
    ``publication_context``, which reads ``capital_events_selected``; the draft
    preview reads the same function and raises the same refusal. There is no
    second test of "does this structure carry an event"."""

    assert "capital_events_selected(" in ast.unparse(_function(_MEMO_DEPENDENCIES, "publication_context"))
    assert "has_capital_events(" in ast.unparse(_function(_MEMO_DEPENDENCIES, "capital_events_selected"))
    preview = ast.unparse(_function(_ASSEMBLY, "assemble_draft_preview"))
    assert "capital_events_selected(" in preview and "refinance_reporting_refusal()" in preview
    refusals = ast.unparse(_function(_PUBLICATION, "publication_refusals"))
    assert "refinance_reporting_refusal()" in refusals
    route = ast.unparse(_function(_API, "read_memo_report_preview"))
    assert "except PublicationRefusedError" in route and "_publication_refused_response(" in route
    defining = [
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name in {"has_capital_events", "refinance_reporting_refusal"}
    ]
    assert sorted(defining) == sorted([_INTEGRATION, _PUBLICATION])


def test_the_gate_message_names_no_identity() -> None:
    """The gate's sentence is a constant: nothing is interpolated into it."""

    tree = _code(_current(_PUBLICATION))
    (constant,) = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "REFINANCE_REPORTING_NOT_AVAILABLE_MESSAGE"
    ]
    assert not [node for node in ast.walk(constant.value) if isinstance(node, ast.JoinedStr)]
    assert "percentage-of-value" not in ast.unparse(constant.value)


def test_a_consumed_refusal_detail_quotes_no_upstream_prose() -> None:
    """A consumed requirement's detail is rebuilt from typed facts -- the scope's
    analyst-facing name and the reason code's analyst sentence. It never quotes
    an ``UnavailableState.reason`` (whose P7.10 prose names opaque ids) and never
    formats a Unit id."""

    function = _function(_MEMO_DEPENDENCIES, "_required_valuations")
    (loop,) = [node for node in function.body if isinstance(node, ast.For) and "_consumed_scopes" in ast.unparse(node.iter)]
    attributes = {node.attr for node in ast.walk(loop) if isinstance(node, ast.Attribute)}
    assert "reason" not in attributes
    assert "unit_id!r" not in ast.unparse(loop)
    scope_text = ast.unparse(_function(_MEMO_DEPENDENCIES, "_scope_text"))
    assert "unit_display_name(" in scope_text and "!r" not in scope_text


def test_a_refinance_refusal_is_worded_from_its_typed_consumer() -> None:
    wording = ast.unparse(_function(_PUBLICATION, "_required_valuation_message"))
    assert "ValuationConsumerKind.REFINANCE_LTV" in wording and "ValuationConsumerKind.PCT_OF_VALUE" in wording
    assert "required.consumers" in wording


def test_whole_view_consumption_is_claimed_only_at_investment_scope() -> None:
    frozen = ast.unparse(_function(_MEMO_DEPENDENCIES, "_version_valuations"))
    assert "whole_view_consumed_timepoints(" in frozen and "consumed_timepoint_ids" not in frozen
    assert "requirement.unit_id is None" in ast.unparse(_function(_MEMO_DEPENDENCIES, "whole_view_consumed_timepoints"))
    preview = ast.unparse(_function(_ASSEMBLY, "_draft_valuations"))
    assert "_whole_view_consumed(" in preview and "consumed_timepoint_ids" not in preview
