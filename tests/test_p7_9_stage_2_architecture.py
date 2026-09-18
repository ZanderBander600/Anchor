"""Phase 7 Gate P7.9 Stage 2 -- the production ledger and architecture guards.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 1.2, 16.5 and
17.2. Every git query reads objects only (protocol 11.2). The guards hold:

1. **the Stage 2 production ledger**, measured from ``main`` at ``1df2760``;
2. **the accepted Stage 1 package frozen** byte for byte at its merge
   ``70b92e2``, and every P7.0 / P7.7 / P7.8 financial and Project-pathway
   module unchanged; no frontend file changed;
3. **one route to the Common Equity Cash Flow** -- the variant service reaches
   the Stage 1 engine only through ``analyze_structured_variant`` and
   ``execute_partnership``;
4. **the fingerprint's layering, inclusion and exclusion**, and FP-2;
5. **whole replacement, three marker states and one partner identity** on
   every write path;
6. **nothing computed is persisted**, exactly the authorized routes exist, and
   no Stage 3 or deferred surface appears.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when Stage 2 began, and its first parent: the Stage 1 merge.
_STAGE_2_BASE = "1df2760"
_STAGE_1_MERGE = "70b92e2cdde29d2d2a1c5a19240bef91622a2219"

_PACKAGE = "src/anchor/partnership"
_STRATEGY = "src/anchor/analysis/strategy.py"
_STORE = "src/anchor/deals/store.py"
_CONTRACTS = "src/anchor/deals/contracts.py"
_FINGERPRINT = "src/anchor/deals/fingerprint.py"
_CODEC = "src/anchor/deals/partnership_codec.py"
_VARIANTS = "src/anchor/deals/partnership_variants.py"
_MATRIX = "src/anchor/deals/decision_matrix.py"
_COMPARISON = "src/anchor/decision/comparison.py"
_API = "src/anchor/api.py"

#: Every backend production file Stage 2 changes, exactly (Section 17.2):
#: - ``analysis/strategy.py``: the ``PARTNERSHIP`` root domain and its resolution;
#: - ``deals/store.py``: schema v12, the eight tables and the lifecycle;
#: - ``deals/contracts.py``: the persisted-Partnership contracts;
#: - ``deals/partnership_codec.py`` (new): the typed unions' one spelling;
#: - ``deals/partnership_variants.py`` (new): the variant service;
#: - ``deals/fingerprint.py``: the Partnership source fingerprint;
#: - ``deals/decision_matrix.py`` and ``decision/comparison.py``: the PARTNER
#:   perspective;
#: - ``api.py``: the routes.
_STAGE_2_PRODUCTION_FILES = frozenset(
    {_STRATEGY, _STORE, _CONTRACTS, _CODEC, _VARIANTS, _FINGERPRINT, _MATRIX, _COMPARISON, _API}
)

#: Consumed and never changed: every financial module of P7.0 / P7.7 / P7.8 and
#: the mature engine, and the Project and structured pathways the Partnership
#: sits downstream of.
_UNCHANGED = (
    "src/anchor/engine",
    "src/anchor/consolidation",
    "src/anchor/capital_structure",
    "src/anchor/investment",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/analysis/scenario.py",
    "src/anchor/deals/variants.py",
    "src/anchor/deals/investment_variants.py",
    "src/anchor/deals/structured_variants.py",
    "src/anchor/deals/capital_structure_codec.py",
    "src/anchor/deals/position_identity.py",
    "src/anchor/deals/__init__.py",
    "src/anchor/decision/__init__.py",
    "web",
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _tree(path: str) -> ast.Module:
    return ast.parse(_current(path))


def _functions(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


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
# 1. The ledger
# =============================================================================


def test_stage_2_changed_exactly_its_authorized_production_files() -> None:
    changed = {path for path in _changes_since(_STAGE_2_BASE, "src", "web") if _is_production(path)}
    assert sorted(changed - _STAGE_2_PRODUCTION_FILES) == []
    assert sorted(_STAGE_2_PRODUCTION_FILES - changed) == []


def test_the_ledger_base_follows_the_stage_1_merge() -> None:
    assert _git("rev-list", "--parents", "-n", "1", _STAGE_2_BASE).split()[1:] == [_STAGE_1_MERGE]


def test_the_new_modules_are_new_at_this_stage() -> None:
    for path in (_CODEC, _VARIANTS):
        assert _git("ls-tree", "--name-only", _STAGE_2_BASE, path).strip() == "", path


# =============================================================================
# 2. The frozen Stage 1 package, upstream and frontend
# =============================================================================


def _stage_1_files() -> list[str]:
    return sorted(_git("ls-tree", "-r", "--name-only", _STAGE_1_MERGE, _PACKAGE).split())


def test_the_stage_1_package_holds_exactly_its_merged_files() -> None:
    current = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / _PACKAGE).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    assert current == _stage_1_files()
    assert len(current) == 9


@pytest.mark.parametrize("path", _stage_1_files())
def test_each_stage_1_module_is_byte_identical_to_its_merge(path: str) -> None:
    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_STAGE_1_MERGE}:{path}").strip(), path


def test_the_stage_1_package_is_unchanged_since_its_merge() -> None:
    assert _changes_since(_STAGE_1_MERGE, _PACKAGE) == set()


@pytest.mark.parametrize("path", _UNCHANGED)
def test_an_upstream_or_frontend_path_is_unchanged(path: str) -> None:
    assert _changes_since(_STAGE_2_BASE, path) == set(), path


def test_the_frozen_guard_has_teeth() -> None:
    """The byte comparison reads the working tree: a changed blob is not the
    merged one."""

    first = _stage_1_files()[0]
    merged = _git("rev-parse", f"{_STAGE_1_MERGE}:{first}").strip()
    changed = subprocess.run(
        ["git", "hash-object", "--stdin"], input=_current(first) + "# changed\n",
        capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT,
    ).stdout.strip()
    assert changed != merged


# =============================================================================
# 3. One route to the Common Equity Cash Flow
# =============================================================================


def test_the_variant_service_reaches_the_engine_only_through_the_structured_variant() -> None:
    tree = _tree(_VARIANTS)
    imports = _imports(tree)
    assert "..partnership" in imports
    assert not {module for module in imports if "capital_structure" in module or module.startswith("..engine")}
    assert not {module for module in imports if module.startswith("..partnership.")}  # no engine internals
    identifiers = _identifiers(tree)
    for forbidden in (
        "levered_cash_flows", "unlevered_cash_flows", "allocate_partnership", "common_equity_input",
        "execute_unit_capital_structure", "execute_investment_capital_structure", "analyze_variant",
        "analyze_investment_variant", "CommonEquityCashFlowInput",
    ):
        assert forbidden not in identifiers, forbidden

    analysis = _functions(tree)["analyze_partnership_variant"]
    assert _calls(analysis).count("analyze_structured_variant") == 1
    (execute,) = [node for node in ast.walk(analysis) if isinstance(node, ast.Call) and _callee(node) == "execute_partnership"]
    assert [ast.unparse(argument) for argument in execute.args] == ["resolved.partnership", "structured.result"]


def test_only_the_stage_1_seam_builds_a_common_equity_input() -> None:
    """Nothing outside the Stage 1 package allocates a series of its own."""

    for path in (_PROJECT_ROOT / "src" / "anchor").rglob("*.py"):
        relative = path.relative_to(_PROJECT_ROOT).as_posix()
        if relative.startswith(_PACKAGE):
            continue
        identifiers = _identifiers(ast.parse(path.read_text(encoding="utf-8")))
        assert not {"allocate_partnership", "common_equity_input", "CommonEquityCashFlowInput"} & identifiers, relative


def test_the_partner_matrix_reads_partnership_fingerprints_and_the_other_matrices_do_not() -> None:
    matrix = _functions(_tree(_MATRIX))
    partner_cell = ast.unparse(matrix["_partner_cell"])
    assert "analyze_partnership_variant" in partner_cell and "partnership_source_fingerprint" in partner_cell
    for name in ("_cell", "_investment_cell", "_position_cell"):
        assert "partner" not in ast.unparse(matrix[name]).lower(), name


def test_the_comparison_reads_result_contracts_only() -> None:
    imports = _imports(_tree(_COMPARISON))
    assert "..partnership.contracts" in imports
    assert not {module for module in imports if module.startswith("..partnership") and module != "..partnership.contracts"}
    assert not {module for module in imports if module.startswith("..engine.") and module != "..engine.contracts"}


# =============================================================================
# 4. The fingerprint
# =============================================================================


def test_the_partnership_fingerprint_is_built_from_the_structured_one() -> None:
    function = _functions(_tree(_FINGERPRINT))["fingerprint_partnership_source"]
    text = ast.unparse(function)
    assert "structured_source_fingerprint" in text and "partnership_payload(partnership)" in text
    assert "project_source_fingerprint" not in text


def test_the_canonical_payload_excludes_names_and_roles() -> None:
    tree = _tree(_FINGERPRINT)
    functions = _functions(tree)
    for name in ("partnership_payload", "_tier_payload", "_hurdle_payload", "_catch_up_payload", "_condition_payload", "_split_payload", "_shares_payload"):
        attributes = {node.attr for node in ast.walk(functions[name]) if isinstance(node, ast.Attribute)}
        assert not {"name", "role"} & attributes, name
    payload = ast.unparse(functions["partnership_payload"])
    for included in ("partner_id", "investor_class", "commitment_share", "contribution_rule", "promote_benchmark", "promote_participant_ids"):
        assert included in payload, included
    assert "sorted(partnership.promote_participant_ids)" in payload
    assert "key=lambda item: (item.sequence, item.tier_id)" in payload


def test_no_partnership_has_no_fingerprint() -> None:
    """FP-2 as a statement about the code: the variant service returns ``None``
    rather than hashing an absence, and the fingerprint function takes no
    optional Partnership."""

    helper = _functions(_tree(_VARIANTS))["_partnership_fingerprint"]
    guard = next(node for node in helper.body if isinstance(node, ast.If))
    assert ast.unparse(guard.test) == "partnership is None"
    assert [ast.unparse(statement) for statement in guard.body] == ["return None"]
    signature = _functions(_tree(_FINGERPRINT))["fingerprint_partnership_source"].args.kwonlyargs
    annotation = next(arg.annotation for arg in signature if arg.arg == "partnership")
    assert ast.unparse(annotation) == "Partnership"


def test_the_project_and_structured_fingerprints_never_read_a_partnership() -> None:
    functions = _functions(_tree(_FINGERPRINT))
    for name in ("fingerprint_structured_source", "capital_structure_payload", "fingerprint_quick_inputs", "fingerprint_detailed_inputs", "fingerprint_lease_level_inputs"):
        assert "partner" not in ast.unparse(functions[name]).lower(), name


# =============================================================================
# 5. Whole replacement, three states, one identity
# =============================================================================


def test_the_resolution_replaces_and_never_merges() -> None:
    function = _functions(_tree(_STRATEGY))["resolve_partnership"]
    assert not [node for node in ast.walk(function) if isinstance(node, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp))]
    # A ``X | None`` annotation is not arithmetic; nothing else is a BinOp.
    assert not [
        node for node in ast.walk(function) if isinstance(node, ast.BinOp) and not isinstance(node.op, ast.BitOr)
    ]
    assert [ast.unparse(statement) for statement in function.body[-3:]] == [
        "own = strategy_partnership(strategy)",
        "if own is None:\n    return base_partnership",
        "return None if isinstance(own, NoPartnership) else own",
    ]


def test_the_project_pathway_drops_every_root_overlay() -> None:
    function = _functions(_tree(_STRATEGY))["_unit_strategy"]
    assert "replace(strategy, root_overlays=())" in ast.unparse(function)


def test_inheritance_is_the_absence_of_a_row_and_none_is_a_flagged_row() -> None:
    store = _functions(_tree(_STORE))
    writer = ast.unparse(store["_write_strategy_partnership"])
    assert "if own is None:\n        return" in writer
    assert "partnership=own if isinstance(own, Partnership) else None" in writer
    marker = ast.unparse(store["_write_partnership"])
    assert "0 if partnership is None else 1" in marker
    assert "None if partnership is None else len(partnership.promote_participant_ids)" in marker
    base = ast.unparse(store["_replace_base_partnership"])
    assert "if partnership is not None:" in base


def test_the_position_identity_rule_is_untouched() -> None:
    """P7.8B's own P-8 rule -- one ``position_id`` names one instrument -- still
    runs on every Capital Structure write path."""

    store = _functions(_tree(_STORE))
    for name in ("set_base_capital_structure", "set_deal_capital_structure"):
        assert "_require_coherent_identity" in _calls(store[name]), name
    for name in ("create_strategy", "create_strategy_for_deal", "update_strategy"):
        assert "_require_coherent_strategy_identity" in _calls(store[name]), name


def test_identity_is_the_partner_id_and_a_role_is_never_a_cross_partnership_rule() -> None:
    """P-8: the ``partner_id`` is the identity. ``role`` is reporting-only
    presentation that may differ between the Base Partnership and each
    Strategy's own, so no layer compares roles across Partnerships, refuses one,
    or holds an identity rule of its own."""

    assert not (_PROJECT_ROOT / "src/anchor/deals/partner_identity.py").exists()
    for path in sorted(_STAGE_2_PRODUCTION_FILES):
        text = _current(path)
        for forbidden in ("partner_role_conflict", "PartnerIdentity", "partner_identity", "require_coherent_partner"):
            assert forbidden not in text, (path, forbidden)
    store = _functions(_tree(_STORE))
    for name in ("set_base_partnership", "set_deal_partnership"):
        # A save reads no role at all; only the row writer copies it through.
        assert "role" not in {
            node.attr for node in ast.walk(store[name]) if isinstance(node, ast.Attribute)
        }, name
    assert "role" in {
        node.attr for node in ast.walk(store["_write_partnership_terms"]) if isinstance(node, ast.Attribute)
    }


def test_a_role_is_presentation_the_resolved_partnership_states_per_cell() -> None:
    """The perspective holds no invariant role, and each matrix cell carries the
    name and role its own Partnership gives the partner."""

    perspective = next(
        node for node in _tree(_VARIANTS).body
        if isinstance(node, ast.ClassDef) and node.name == "PartnerPerspective"
    )
    fields = {
        statement.target.id for statement in perspective.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    }
    assert fields == {"partner_id", "name", "present_in_base", "strategy_ids"}

    comparison = _tree(_COMPARISON)
    for name, expected in (
        ("PartnerDecisionCell", {"partner_name", "partner_role"}),
        ("PartnerCellInput", {"partner_name", "partner_role"}),
    ):
        node = next(item for item in comparison.body if isinstance(item, ast.ClassDef) and item.name == name)
        stated = {
            statement.target.id for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        }
        assert expected <= stated, name
    matrix = next(
        item for item in comparison.body if isinstance(item, ast.ClassDef) and item.name == "PartnerDecisionMatrix"
    )
    matrix_fields = {
        statement.target.id for statement in matrix.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    }
    assert "role" not in matrix_fields and "partner_name" in matrix_fields

    cell = _functions(_tree(_MATRIX))["_partner_cell"]
    text = ast.unparse(cell)
    assert "partner_name=None if authored is None else authored.name" in text
    assert "partner_role=None if authored is None else authored.role" in text


def test_every_lifecycle_path_removes_partnership_rows() -> None:
    store = _functions(_tree(_STORE))
    assert "_delete_investment_partnerships" in _calls(store["_delete_investment_rows"])
    assert "_delete_partnership" in _calls(store["_delete_strategy_overlay_rows"])
    collapse = " ".join(
        node.value for node in ast.walk(store["_wrapper_holds_no_structure"])
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )
    assert "FROM partnerships WHERE investment_id" in collapse


def test_no_identifier_is_regenerated() -> None:
    for path in (_VARIANTS, _CODEC, _FINGERPRINT):
        assert "uuid" not in _current(path), path
    minted = sorted(
        name for name, function in _functions(_tree(_STORE)).items()
        if "uuid4" in ast.unparse(function) and "partner" in name
    )
    assert minted == ["_write_partnership"]  # the marker row's own id


# =============================================================================
# 6. Nothing computed is persisted; exactly the authorized surface
# =============================================================================

_TABLES = {
    "partnerships",
    "partners",
    "partnership_benchmark_shares",
    "partnership_promote_participants",
    "waterfall_tiers",
    "waterfall_tier_splits",
    "waterfall_hurdle_conditions",
    "waterfall_catch_up_terms",
}


def test_the_eight_tables_hold_authored_terms_only() -> None:
    text = _current(_STORE)
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text))
    assert {table for table in created if re.search(r"partner|waterfall", table)} == _TABLES
    ddl = " ".join(
        re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\)", text, re.DOTALL).group(1)  # type: ignore[union-attr]
        for table in _TABLES
    )
    columns = set(re.findall(r"^\s*(\w+)\s+(?:TEXT|REAL|INTEGER)", ddl, re.MULTILINE))
    assert "target_profit_share" in columns  # the catch-up term itself, authored
    for forbidden in (r"irr", r"moic", r"(?<!target_)profit", r"promote_earned", r"distribution(?!_order)", r"amount", r"result", r"snapshot", r"json", r"blob"):
        assert not {column for column in columns if re.search(forbidden, column)}, forbidden
    # AM1 advanced the store to schema 13. Stage 2's eight Partnership tables
    # are unchanged by it; what this line pins is that the store still
    # declares one version, and that Stage 2's tables were added under 12.
    assert "_SCHEMA_VERSION = 13" in text


def test_the_new_services_never_write_the_store() -> None:
    for path in (_VARIANTS, _MATRIX):
        written = {
            name for name in _calls(_tree(path))
            if name.startswith(("put_", "set_", "create_", "delete_", "update_"))
        }
        assert written == set(), path


def test_exactly_the_authorized_routes_are_added() -> None:
    from anchor.api import app

    routes = {
        (method, route.path)  # type: ignore[attr-defined]
        for route in app.routes
        for method in getattr(route, "methods", ()) or ()
        if "partner" in route.path  # type: ignore[attr-defined]
    }
    assert routes == {
        ("GET", "/deals/{deal_id}/partnership"),
        ("PUT", "/deals/{deal_id}/partnership"),
        ("GET", "/investments/{investment_id}/partnership"),
        ("PUT", "/investments/{investment_id}/partnership"),
        ("GET", "/investments/{investment_id}/partnership-variants/{strategy_id}/{scenario_id}/fingerprint"),
        ("POST", "/investments/{investment_id}/partnership-variants/{strategy_id}/{scenario_id}/analysis"),
        ("GET", "/investments/{investment_id}/partner-perspectives"),
        ("POST", "/investments/{investment_id}/partner-decision-matrix/{partner_id}"),
    }


def test_the_api_adds_by_addition_and_catches_no_value_error() -> None:
    removed = [
        line for line in _git("diff", "-U0", _STAGE_2_BASE, "--", _API).splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    assert removed == [
        "-from .deals.decision_matrix import analyze_position_decision_matrix",
        '-            {"domain": overlay.domain.value, "content": _wire(overlay.content)}',
        "-    and the two travel differently all the way down.\"\"\"",
        "-        content = (",
        '-            _capital_structure_request(body["content"], f"{where}.content")',
        "-            if domain is StrategyDomain.CAPITAL_STRUCTURE",
        '-            else body["content"]',
        "-        )",
    ]
    assert _current(_API).count("except ValueError") == _git("show", f"{_STAGE_2_BASE}:{_API}").count("except ValueError")


def test_the_codec_classifies_and_computes_nothing() -> None:
    tree = _tree(_CODEC)
    assert _imports(tree) == {"__future__", "enum", "..partnership.contracts"}
    assert not [node for node in ast.walk(tree) if isinstance(node, (ast.BinOp, ast.AugAssign))]


_LATER = re.compile(r"fee\b|_fee|tax|clawback|claw_back|monthly|refinanc|recapitali|valuation|xirr|memo|template", re.IGNORECASE)


@pytest.mark.parametrize("path", [_CODEC, _VARIANTS])
def test_no_deferred_or_stage_3_identifier(path: str) -> None:
    assert not {name for name in _identifiers(_tree(path)) if _LATER.search(name)}, path


def test_the_deferred_guard_has_teeth() -> None:
    assert _LATER.search("sponsor_fee") and _LATER.search("MonthlyWaterfall") and _LATER.search("clawback")
    assert not _LATER.search("promote_earned") and not _LATER.search("partner_perspective")


@pytest.mark.parametrize("path", sorted(_STAGE_2_PRODUCTION_FILES))
def test_no_case_or_competition_identifier(path: str) -> None:
    import test_p7_0_decision_architecture as p7_0

    assert p7_0._case_identifiers_in(_current(path)) == [], path
