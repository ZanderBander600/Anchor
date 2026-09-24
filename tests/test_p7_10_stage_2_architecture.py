"""Phase 7 Gate P7.10 Stage 2 -- the production ledger and architecture guards.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 2, 6.1, 6.2, 7,
9, 10, 15, 17 (Stage 2) and 18.2. Every git query reads objects only
(protocol 11.2). The guards hold:

1. **the Stage 2 production ledger**: exactly thirteen backend files and no
   frontend file, measured from the accepted Stage 1 baseline ``46650a7``;
2. **the accepted Stage 1 valuation package frozen** byte for byte at its merge,
   and every upstream financial module unchanged;
3. **no Stage 3 or Stage 4 surface**: no AI, prompt, grounding, PDF or report
   layout anywhere in this gate;
4. **Exit stays system-owned**, and Stage 2 implements no refinancing;
5. **no P7.10 financial arithmetic in the API**, and none in the frontend;
6. **published versions are immutable**, and a draft cannot be confused with
   one;
7. **the analyst recommendation and the IC decision stay separate**;
8. **an expected unavailable state cannot become an error, a zero, or a
   purchase-price fallback**;
9. **the schema advances exactly once**.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"

#: ``main`` when Stage 2 began: the P7.10 Stage 1 acceptance closeout (PR #50),
#: whose first parent is the accepted Stage 1 merge.
_STAGE_2_BASE = "46650a7"
#: The accepted P7.10 Stage 1 merge (PR #49). The valuation package is frozen at
#: it, and Stage 2 edits none of it.
_STAGE_1_MERGE = "f6f36803cdcb646aa8a4af8cfc658a0e368ae58e"
#: **Re-pinned at P7.10 Stage 4.** Stage 2's own merge (PR #51). Until Stage 4
#: this file measured the working tree, because Stage 2 was the gate in
#: progress; now that it is merged and accepted, its ledger measures its own
#: committed range ``46650a7..ababa50`` instead.
#:
#: The claim is unchanged and in fact stronger: it was "Stage 2 has changed only
#: these files so far", and it is now "Stage 2 changed exactly these files",
#: which no later gate can move. Nothing was weakened to accommodate Stage 4 --
#: Stage 4's own ledger is ``tests/test_p7_10_stage_4_architecture.py``, and it
#: is what holds Stage 4 to its scope.
_STAGE_2_MERGE = "ababa50"

_API = "src/anchor/api.py"
_STORE = "src/anchor/deals/store.py"
_FINGERPRINT = "src/anchor/deals/fingerprint.py"
_CONTRACTS = "src/anchor/deals/contracts.py"
_CODEC = "src/anchor/deals/valuation_codec.py"
_VIEWS = "src/anchor/deals/valuation_views.py"
_DEPENDENCIES = "src/anchor/deals/memo_dependencies.py"
_STRUCTURED = "src/anchor/deals/structured_variants.py"

_MEMO_PACKAGE = "src/anchor/memo"
_MEMO_NAMES = ("__init__", "contracts", "validation", "availability", "publication")
_MEMO_MODULES = tuple(f"{_MEMO_PACKAGE}/{name}.py" for name in _MEMO_NAMES)
_CONTRACTS_MEMO = f"{_MEMO_PACKAGE}/contracts.py"
_VALIDATION = f"{_MEMO_PACKAGE}/validation.py"
_PUBLICATION = f"{_MEMO_PACKAGE}/publication.py"

#: The accepted Stage 1 package. Consumed by Stage 2 and edited by none of it.
_VALUATION_PACKAGE = "src/anchor/valuation"

#: Every production file Stage 2 changes, exactly (Section 17, Stage 2):
#: - ``memo/*`` (new): the Investment Memo domain, its validation, the
#:   unavailable adapter and the publication rules;
#: - ``deals/valuation_codec.py`` (new): the method union's one spelling;
#: - ``deals/valuation_views.py`` (new): persisted definitions meet the Stage 1
#:   authority;
#: - ``deals/memo_dependencies.py`` (new): the dependency ledger and freshness;
#: - ``deals/store.py``: schema v15, the nineteen tables and the lifecycle;
#: - ``deals/contracts.py``: the P7.10 lookups and refusals;
#: - ``deals/fingerprint.py``: the Section 10 identities;
#: - ``deals/structured_variants.py``: the funding-authority seam;
#: - ``api.py``: the routes.
_STAGE_2_PRODUCTION_FILES = frozenset(
    {
        *_MEMO_MODULES,
        _CODEC,
        _VIEWS,
        _DEPENDENCIES,
        _STORE,
        _CONTRACTS,
        _FINGERPRINT,
        _STRUCTURED,
        _API,
    }
)

_NEW_MODULES = (*_MEMO_MODULES, _CODEC, _VIEWS, _DEPENDENCIES)

#: Consumed and never changed: every financial module of the mature engine and
#: of P7.0 / P7.7 / P7.8 / P7.9, the Project and consolidation pathways, and the
#: whole frontend.
_UNCHANGED = (
    "src/anchor/engine",
    "src/anchor/consolidation",
    "src/anchor/capital_structure",
    "src/anchor/partnership",
    "src/anchor/investment",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/asset_management",
    "src/anchor/exports",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/decision",
    "src/anchor/valuation",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/asset_types.py",
    "src/anchor/report.py",
    "src/anchor/cli.py",
    "src/anchor/analysis",
    "src/anchor/deals/variants.py",
    "src/anchor/deals/investment_variants.py",
    "src/anchor/deals/partnership_variants.py",
    "src/anchor/deals/decision_matrix.py",
    "src/anchor/deals/capital_structure_codec.py",
    "src/anchor/deals/partnership_codec.py",
    "src/anchor/deals/position_identity.py",
    "src/anchor/deals/__init__.py",
    "web",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    """Every path Stage 2 changed, measured across its own committed range.

    **Re-pinned at P7.10 Stage 4.** This read the working tree while Stage 2 was
    the gate in progress; it now reads ``46650a7..ababa50``, so it keeps proving
    what Stage 2 changed however later gates move the tree. The untracked sweep
    is gone with it: a merged range has nothing untracked in it."""

    return {
        path
        for path in _git(
            "diff", "--name-only", "--no-renames", base, _STAGE_2_MERGE, "--", *paths
        ).split()
        if path
    }


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _as_merged(path: str) -> str:
    """The file as Stage 2 merged it, at ``ababa50``.

    **Added at P7.10 Stage 4.** A handful of guards below make claims about what
    *Stage 2's own migration and modules* did -- how far the schema advanced,
    which tables that advance created, which libraries this gate reached for.
    Those are historical facts about a merged gate, and reading the working tree
    for them turns them into claims about whatever gate is in progress, which is
    not what they were written to prove. They read Stage 2's merge instead, so
    they keep proving exactly what they always proved. Stage 4's own additions
    are held by ``tests/test_p7_10_stage_4_architecture.py``."""

    return _git("show", f"{_STAGE_2_MERGE}:{path}").replace("\r\n", "\n")


def _tree(path: str) -> ast.Module:
    return ast.parse(_current(path))


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _functions(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


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
    return found


def _code(node: ast.AST) -> str:
    """One definition's source with its docstring removed.

    A docstring that *describes* an invariant -- "the committee decision is
    deliberately absent", "``ValuationError`` stays an error" -- must not trip a
    guard looking for the thing it forbids."""

    stripped = ast.parse(ast.unparse(node)).body[0]
    body = getattr(stripped, "body", [])
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        stripped.body = body[1:] or [ast.Pass()]  # type: ignore[attr-defined]
    return ast.unparse(stripped)


def _code_only(source: str) -> str:
    """A whole module's source with every docstring removed."""

    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]  # type: ignore[attr-defined]
    return ast.unparse(tree)


def _region_nodes(path: str) -> list[ast.AST]:
    """Every AST node at or below the P7.10 Stage 2 marker's line.

    Slicing the *text* at the marker leaves an unparseable fragment (the marker
    sits inside a comment block), so the region is taken by line number from the
    whole module's tree instead."""

    source = _current(path)
    marker_line = source[: source.index("Phase 7 Gate P7.10 Stage 2")].count("\n") + 1
    return [
        node
        for node in ast.walk(ast.parse(source))
        if getattr(node, "lineno", 0) >= marker_line
    ]


def _p7_10_region(source: str) -> str:
    """Only the P7.10 Stage 2 section of a pre-existing file.

    ``api.py`` and ``store.py`` are large modules this gate appends to; a guard
    that read the whole file would be measuring nine earlier gates' code."""

    marker = "Phase 7 Gate P7.10 Stage 2"
    index = source.find(marker)
    assert index != -1, "the P7.10 Stage 2 section marker is missing"
    return source[index:]


# =============================================================================
# 1. The ledger
# =============================================================================


def test_stage_2_changes_exactly_the_declared_production_files() -> None:
    changed = {path for path in _changes_since(_STAGE_2_BASE, "src", "web") if _is_production(path)}
    assert sorted(changed - _STAGE_2_PRODUCTION_FILES) == []
    assert sorted(_STAGE_2_PRODUCTION_FILES - changed) == []


def test_the_ledger_base_follows_the_accepted_stage_1_merge() -> None:
    assert _git("rev-list", "--parents", "-n", "1", _STAGE_2_BASE).split()[1] == _STAGE_1_MERGE


def test_no_frontend_file_changed() -> None:
    """Stage 2 is backend only. Stage 4 builds the Memo workspace; a changed
    frontend file here is a scope violation, not a guard to update."""

    assert _changes_since(_STAGE_2_BASE, "web") == set()


def test_the_new_modules_are_new_at_this_stage() -> None:
    for path in _NEW_MODULES:
        assert _git("ls-tree", "--name-only", _STAGE_2_BASE, path).strip() == "", path


@pytest.mark.parametrize("path", _UNCHANGED)
def test_an_upstream_or_frontend_path_is_unchanged(path: str) -> None:
    assert _changes_since(_STAGE_2_BASE, path) == set(), path


# =============================================================================
# 2. The accepted Stage 1 package is frozen
# =============================================================================


def _stage_1_files() -> list[str]:
    return sorted(_git("ls-tree", "-r", "--name-only", _STAGE_1_MERGE, _VALUATION_PACKAGE).split())


@pytest.mark.parametrize("path", _stage_1_files())
def test_each_stage_1_module_is_byte_identical_to_its_merge(path: str) -> None:
    """Stage 2 consumes the accepted valuation authority and edits none of it.
    Every value, forward NOI and typed unavailable reason still comes from the
    code the human accepted."""

    assert _git("hash-object", path).strip() == _git("rev-parse", f"{_STAGE_1_MERGE}:{path}").strip(), path


def test_the_stage_1_package_holds_exactly_its_merged_files() -> None:
    current = sorted(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in (_PROJECT_ROOT / _VALUATION_PACKAGE).rglob("*.py")
    )
    assert current == _stage_1_files()
    assert len(current) == 5


def test_the_frozen_guard_has_teeth() -> None:
    first = _stage_1_files()[0]
    merged = _git("rev-parse", f"{_STAGE_1_MERGE}:{first}").strip()
    changed = subprocess.run(
        ["git", "hash-object", "--stdin"],
        input=_current(first) + "# changed\n",
        capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT,
    ).stdout.strip()
    assert changed != merged


# =============================================================================
# 3. No Stage 3 or Stage 4 surface
# =============================================================================

#: Vocabulary belonging to a later stage. Checked against the code's own
#: identifiers, not its prose: a docstring may name what Stage 2 excludes and
#: why; nothing Stage 2 *executes* may.
_LATER_STAGE = re.compile(
    r"prompt|grounding|completion|openai|anthropic|llm|pdf|reportlab|weasyprint"
    r"|render|stylesheet|page_break|watermark|appendix",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", sorted(_STAGE_2_PRODUCTION_FILES))
def test_no_stage_3_or_stage_4_identifier(path: str) -> None:
    source = _current(path)
    # **Re-pinned at P7.10 Stage 4.** The region runs from Stage 2's own marker
    # to Stage 4's, where there is one: ``api.py`` now carries both gates, and a
    # slice that ran to end-of-file would read Stage 4's PDF routes as Stage 2
    # identifiers. Stage 4's own guard holds Stage 4's region.
    region = (
        _p7_10_region(source)
        if path in {_API, _STORE, _FINGERPRINT, _CONTRACTS, _STRUCTURED}
        else source
    )
    # **Re-pinned at P7.10 Stage 4 (Correction 1).** The region stops at Stage
    # 4's own marker wherever one appears: `api.py`, `store.py` and
    # `memo_dependencies.py` now carry both gates, and a slice that ran to
    # end-of-file would read Stage 4's report and PDF identifiers as Stage 2's.
    # Stage 4's own guard holds Stage 4's region.
    for stage_4_marker in (
        "Phase 7 Gate P7.10 Stage 4",
        "P7.10 Stage 4",
        "Stage 4 Correction 1",
    ):
        if stage_4_marker in region:
            region = region[: region.index(stage_4_marker)]
    offenders = sorted(
        name for name in _identifiers(ast.parse(source)) if _LATER_STAGE.search(name)
    )
    # ``ast`` reads the whole module, so a pre-existing identifier in a large
    # shared file is filtered by whether it appears in this gate's own region.
    assert [name for name in offenders if name in region] == [], (path, offenders)


def test_the_later_stage_guard_has_teeth() -> None:
    assert _LATER_STAGE.search("build_prompt") and _LATER_STAGE.search("render_pdf")
    assert not _LATER_STAGE.search("publication_refusals")
    assert not _LATER_STAGE.search("memo_content_fingerprint")


def test_no_stage_2_module_imports_an_ai_or_document_library() -> None:
    forbidden = re.compile(
        r"^(openai|anthropic|reportlab|weasyprint|jinja2|markdown|pypdf|fpdf)"
        r"|(^|\.)ai(\.|$)|(^|\.)ingestion(\.|$)"
    )
    for path in _NEW_MODULES:
        # **Re-pinned at P7.10 Stage 4.** ``memo_dependencies.py`` is the one
        # Stage 2 module Stage 4's ratified publication seam reaches: publishing
        # now generates the immutable report and PDF inside the same
        # transaction, so the module function-locally imports
        # ``anchor.reporting``, which reaches ReportLab and pypdf. That is Stage
        # 4 document *generation* at publication, not a Stage 2 import, and
        # Stage 4's own guards hold it -- so this guard reads the module as
        # Stage 2 merged it and keeps proving that *Stage 2* reached for no such
        # library. Every other module is still measured in the working tree.
        source = _as_merged(path) if path == _DEPENDENCIES else _current(path)
        imported = _imports(ast.parse(source))
        assert not {module for module in imported if forbidden.search(module)}, path


def test_the_memo_package_names_no_ai_proposal_shape() -> None:
    """Stage 3 owns AI proposals. Stage 2 stores none, and declares no shape one
    could arrive through -- not even an unused field."""

    # ``AI_EXTRACTED_APPROVED`` is a ratified *evidence source kind* (Section 8):
    # a provenance label on a reference a human approved, not an AI capability.
    ratified = {"ai_extracted_approved"}
    for path in _MEMO_MODULES:
        identifiers = {name.lower() for name in _identifiers(_tree(path))} - ratified
        for forbidden in ("proposal", "proposed_text", "ai_", "model_metadata", "generation"):
            assert not [name for name in identifiers if forbidden in name], (path, forbidden)


# =============================================================================
# 4. Exit stays system-owned; no refinancing
# =============================================================================


def test_exit_is_unstorable_in_the_schema() -> None:
    """R-B in the DDL: the CHECK constraint admits the three storable kinds and
    no fourth, so no code path can store a second terminal value."""

    ddl = re.search(
        r"CREATE TABLE IF NOT EXISTS valuation_timepoints \((.*?)\n\)", _current(_STORE), re.DOTALL
    )
    assert ddl is not None
    assert "kind IN ('as_is', 'stabilized', 'custom')" in ddl.group(1)
    assert "exit" not in ddl.group(1).lower()


def test_no_stage_2_module_implements_a_later_funding_event() -> None:
    """Section 6.1: supporting a later funding event needs an explicitly
    authorized refinancing or event-timing stage. Stage 2 adds neither."""

    forbidden = re.compile(r"refinanc|recapitali|payoff_event|redraw|second_draw|paydown", re.IGNORECASE)
    # Refinance & Capital Events V1 Stage 2 re-pin: that separately ratified
    # stage *is* the authorized refinancing stage Section 6.1 names, and it
    # extends several of these files. The claim is about what P7.10 Stage 2's own
    # modules added, so it reads them as Stage 2 merged them -- where it holds
    # unchanged. Refinance persistence is held by its own guard,
    # ``tests/test_refinance_v1_stage_2_architecture.py``.
    for path in sorted(_STAGE_2_PRODUCTION_FILES):
        source = _as_merged(path)
        region = _p7_10_region(source) if path in {_API, _STORE, _FINGERPRINT, _CONTRACTS, _STRUCTURED} else source
        offenders = sorted(name for name in _identifiers(ast.parse(source)) if forbidden.search(name))
        assert [name for name in offenders if name in region] == [], (path, offenders)


def test_the_closing_only_executor_rule_is_untouched() -> None:
    """The P7.8 executor still funds positions at closing only. Stage 2 supplies
    an authority; it does not widen the window."""

    execution = "src/anchor/capital_structure/execution.py"
    assert _changes_since(_STAGE_2_BASE, execution) == set()


# =============================================================================
# 5. No P7.10 financial arithmetic in the API
# =============================================================================


def test_the_api_section_performs_no_arithmetic() -> None:
    """Section 15: financial calculations, fingerprint construction, publication
    validation and domain decisions stay outside ``api.py``. This gate's own
    section contains no arithmetic operator at all."""

    operators = [
        node
        for node in _region_nodes(_API)
        if isinstance(node, (ast.BinOp, ast.AugAssign))
        and not isinstance(getattr(node, "op", None), ast.BitOr)
    ]
    assert operators == [], [ast.unparse(node) for node in operators]


def test_the_api_section_builds_no_fingerprint_and_makes_no_publication_decision() -> None:
    region = _p7_10_region(_current(_API))
    for forbidden in ("fingerprint_", "hashlib", "sha256", "publication_refusals(", "require_publishable"):
        assert forbidden not in region, forbidden


def test_the_view_service_performs_no_money_arithmetic() -> None:
    """``valuation_views`` reads Stage 1 and adds the evidence gate. It never
    adds, multiplies or divides a money value -- there is no operator on one."""

    tree = _tree(_VIEWS)
    operators = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign))
        and not isinstance(getattr(node, "op", None), ast.BitOr)
    ]
    assert operators == [], [ast.unparse(node) for node in operators]


def test_the_store_computes_nothing(context: None = None) -> None:
    """The P7.10 store section imports no calculation module: it persists
    authored definitions and reads them back."""

    tree = _tree(_STORE)
    modules = _imports(tree)
    for forbidden in ("..valuation.engine", "..valuation.funding", "..engine.acquisition", "..engine.returns"):
        assert forbidden not in modules, forbidden


# =============================================================================
# 6. Immutable versions; a draft is never a version
# =============================================================================


def test_no_update_statement_names_a_published_version_table() -> None:
    """R-H structurally. Immutability is not a rule enforced at a boundary:
    there is no SQL in the store capable of rewriting a published version."""

    for table in re.findall(r"UPDATE\s+(\w+)", _current(_STORE), re.IGNORECASE):
        assert not table.startswith("memo_version"), table
        assert table != "investment_memo_versions", table


def test_the_store_exposes_no_function_that_edits_a_version() -> None:
    names = {
        node.name
        for node in ast.parse(_current(_STORE)).body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    for forbidden in ("update_memo_version", "edit_memo_version", "delete_memo_version"):
        assert forbidden not in names, forbidden
    assert "publish_memo_version" in names


def test_a_draft_and_a_version_are_separate_tables_and_separate_contracts() -> None:
    store = _current(_STORE)
    assert "CREATE TABLE IF NOT EXISTS investment_memo_drafts" in store
    assert "CREATE TABLE IF NOT EXISTS investment_memo_versions" in store

    contracts = {
        node.name
        for node in ast.parse(_current(f"{_MEMO_PACKAGE}/contracts.py")).body
        if isinstance(node, ast.ClassDef)
    }
    assert {"InvestmentMemoDraft", "InvestmentMemoVersion"} <= contracts


def test_publishing_copies_and_never_consumes_the_draft() -> None:
    publish = _functions(_tree(_DEPENDENCIES))["publish"]
    text = ast.unparse(publish)
    assert "delete_memo_draft" not in text
    assert "publish_memo_version" in text


# =============================================================================
# 7. The analyst recommendation and the IC decision stay separate
# =============================================================================


def test_the_two_decisions_are_different_vocabularies() -> None:
    """R-F. Deliberately not one enum: ``DEFERRED`` is a committee outcome and
    ``INSUFFICIENT_INFORMATION`` an analyst recommendation, so no code path and
    no reader can substitute one for the other."""

    from anchor.memo.contracts import AnalystRecommendation, InvestmentCommitteeOutcome

    analyst = {member.value for member in AnalystRecommendation}
    committee = {member.value for member in InvestmentCommitteeOutcome}
    assert analyst != committee
    assert "deferred" in committee and "deferred" not in analyst
    assert "insufficient_information" in analyst and "insufficient_information" not in committee


def test_no_write_path_touches_both_records() -> None:
    store = _functions(_tree(_STORE))
    decision = _code(store["put_committee_decision"])
    assert "analyst_recommendation" not in decision
    assert "memo_items" not in decision and "investment_memo_drafts" not in decision

    for name in ("put_memo_draft", "put_deal_memo_draft"):
        draft = _code(store[name])
        assert "investment_committee_decisions" not in draft, name


def test_the_committee_decision_attaches_only_to_a_published_version() -> None:
    decision = ast.unparse(_functions(_tree(_STORE))["put_committee_decision"])
    assert "FROM investment_memo_versions WHERE version_id = ? AND investment_id = ?" in decision
    assert "MemoVersionNotFoundError" in decision


def test_the_published_fingerprint_excludes_the_ic_decision() -> None:
    function = _functions(_tree(_FINGERPRINT))["fingerprint_published_version"]
    text = _code(function).lower()
    for forbidden in ("decision", "committee", "decided_at"):
        assert forbidden not in text, forbidden


# =============================================================================
# 8. An expected unavailable state is never an error, a zero, or a fallback
# =============================================================================


def test_the_unavailable_state_declares_no_numeric_field() -> None:
    """The strongest guard this gate carries. A fabricated amount, a zero
    collapse and a purchase-price fallback are not merely forbidden in an
    unavailable state -- they are unrepresentable."""

    import dataclasses

    from anchor.memo.availability import UnavailableState

    fields = {field.name for field in dataclasses.fields(UnavailableState)}
    for forbidden in ("value", "amount", "scope_value", "estimate", "price", "basis", "fallback"):
        assert forbidden not in fields, forbidden
    assert {"status", "reason_code", "reason"} <= fields


def test_every_stage_1_valuation_reason_has_an_analyst_facing_code() -> None:
    """Total by construction: an unmapped reason raises rather than falling back
    to a vaguer code, so a new Stage 1 condition can never reach an analyst as an
    existing, wrong explanation."""

    from anchor.memo.availability import UnavailableAdapterError, valuation_reason_code
    from anchor.valuation.contracts import ValuationUnavailableReason

    for reason in ValuationUnavailableReason:
        assert valuation_reason_code(reason) is not None

    class _Unknown:
        pass

    with pytest.raises(UnavailableAdapterError):
        valuation_reason_code(_Unknown())  # type: ignore[arg-type]


def test_the_adapter_never_reads_a_price_or_defaults_a_number() -> None:
    source = _current(f"{_MEMO_PACKAGE}/availability.py")
    for forbidden in ("purchase_price", "transaction_price", "or 0", "or 0.0", "0.0)"):
        assert forbidden not in source, forbidden


def test_a_real_defect_is_not_routed_through_the_adapter() -> None:
    """``ValuationError`` and ``PersistedDealDataError`` stay errors. Turning a
    programming fault into an ordinary N/A would hide it from the analyst."""

    availability = _code_only(_current(f"{_MEMO_PACKAGE}/availability.py"))
    assert "ValuationError" not in availability
    assert "PersistedDealDataError" not in availability
    assert not [
        node
        for node in ast.walk(ast.parse(_current(f"{_MEMO_PACKAGE}/availability.py")))
        if isinstance(node, (ast.Try, ast.ExceptHandler))
    ], "the adapter catches nothing: a real defect stays a defect"


def test_the_api_reports_an_unavailable_valuation_with_a_200() -> None:
    """Section 6.2: never a generic server error. The views route raises only
    typed refusals -- 404 for a missing id, 409 for a conflict, 422 for an
    invalid variant -- and returns the unavailable state otherwise."""

    region = _p7_10_region(_current(_API))
    route = region[region.index("def read_valuation_views("):]
    route = route[: route.index("\n# ---")]
    assert "HTTP_500" not in route
    for expected in ("_not_found", "_investment_structure_conflict", "_structured_conflict"):
        assert expected in route, expected


# =============================================================================
# 9. The schema advances exactly once
# =============================================================================


def test_the_store_declared_exactly_one_schema_version_and_it_was_fifteen() -> None:
    """**Re-pinned at P7.10 Stage 4.** Stage 2 advanced the schema from 14 to
    15, exactly once, and it still did: the claim is measured at Stage 2's
    merge, where it is settled, rather than in a tree later gates advance.
    Stage 4's own single advance to 16 is proved by
    ``test_schema_16_adds_exactly_one_table_and_alters_none``."""

    store = _as_merged(_STORE)
    versions = re.findall(r"^_SCHEMA_VERSION = (\d+)$", store, re.MULTILINE)
    assert versions == ["15"]
    assert "_SCHEMA_VERSION = 14" in _git("show", f"{_STAGE_2_BASE}:{_STORE}")


def test_the_migration_alters_and_drops_nothing_new() -> None:
    """Purely additive: this gate's diff adds no ALTER and no DROP, and every
    new table is created through the unconditional ``CREATE TABLE IF NOT
    EXISTS`` path.

    **Re-pinned at P7.10 Stage 4**, like the ledger above: measured across
    ``46650a7..ababa50``, so it proves what Stage 2's migration did rather than
    what the working tree's does."""

    added = [
        line
        for line in _git("diff", _STAGE_2_BASE, _STAGE_2_MERGE, "--", _STORE).splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    for line in added:
        upper = line.upper()
        assert "ALTER TABLE" not in upper, line
        assert "DROP TABLE" not in upper, line
        assert "DROP COLUMN" not in upper, line
    # Count the DDL itself, not a sentence that happens to name it: only a
    # ``CREATE TABLE IF NOT EXISTS <name> (`` line declares a table.
    creates = [
        line for line in added if re.search(r"CREATE TABLE IF NOT EXISTS (\w+) \(", line)
    ]
    assert len(creates) == 19, creates
    # Any other line naming CREATE TABLE is prose explaining the migration, not
    # DDL: it must be a comment.
    assert all(
        line.lstrip("+").lstrip().startswith("#")
        for line in added
        if "CREATE TABLE" in line.upper() and line not in creates
    )


def test_every_new_table_is_registered_on_the_connection() -> None:
    """A table created only in a migration branch would be missing from a fresh
    database. Every one is created unconditionally, like every table since
    version 2.

    **Re-pinned at P7.10 Stage 4**, which appends a twentieth table to the same
    P7.10 region of ``store.py``. Read at Stage 2's merge, this still counts
    Stage 2's nineteen; Stage 4's table is registered the same way and proved by
    its own guard."""

    store = _as_merged(_STORE)
    connect = store[store.index("def _connect("):store.index("def _utc_now_iso(")]
    declared = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _p7_10_region(store)))
    assert len(declared) == 19
    for table in sorted(declared):
        constant = f"_CREATE_{table.upper()}_TABLE_SQL"
        assert constant in connect, table


# =============================================================================
# 10. Dependency direction
# =============================================================================


def test_the_memo_package_is_pure() -> None:
    """No I/O, no storage, no wire, no clock, no identity: persistence lives in
    the store, identity in the fingerprint module, resolution in the services,
    and the wire in the API."""

    forbidden = re.compile(
        r"sqlite3|fastapi|pydantic|hashlib|^(os|pathlib|random|uuid|logging|secrets)$"
        r"|(^|\.)(deals|api|analysis|engine|consolidation|capital_structure|partnership)(\.|$)"
    )
    for path in _MEMO_MODULES:
        offenders = {module for module in _imports(_tree(path)) if forbidden.search(module)}
        assert offenders == set(), (path, offenders)


def test_the_memo_package_reads_only_the_valuation_shapes() -> None:
    """``availability`` adapts Stage 1's typed reasons and never resolves one:
    it imports the contracts and neither the engine nor the funding layer."""

    for path in _MEMO_MODULES:
        modules = _imports(_tree(path))
        assert "..valuation.engine" not in modules, path
        assert "..valuation.funding" not in modules, path


def test_the_valuation_view_service_never_reads_the_capital_structure() -> None:
    """The dependency runs one way, as P7.10 Stage 1 established: Capital
    Structure reads valuation. The structured variant service is where the two
    meet, and it is the only place that imports both."""

    assert not any("capital_structure" in module for module in _imports(_tree(_VIEWS)))
    structured = _imports(_tree(_STRUCTURED))
    assert any("capital_structure" in module for module in structured)
    assert any("valuation" in module for module in structured)


def test_no_upstream_layer_imports_the_memo_package() -> None:
    for layer in ("engine", "consolidation", "capital_structure", "partnership", "investment",
                  "business_plan", "leasing", "ai", "ingestion", "exports", "valuation"):
        for path in (_SRC / "anchor" / layer).rglob("*.py"):
            modules = _imports(ast.parse(path.read_text(encoding="utf-8")))
            assert not any("memo" in module for module in modules), path


def test_exactly_the_authorized_routes_are_added() -> None:
    from anchor.api import app

    # **Re-pinned at P7.10 Stage 4.** Stage 4 added four read-only presentation
    # routes over the same nouns -- the library, the draft preview, one
    # version's report and the PDF. They are named here and excluded, so this
    # guard keeps proving *Stage 2's* twenty-four routes exactly rather than
    # being widened into a list of whatever the app happens to serve. Stage 4's
    # own routes are held by ``tests/test_p7_10_stage_4_architecture.py``.
    stage_4_routes = {
        "/memo-library",
        "/investments/{investment_id}/memo/report-preview",
        "/investments/{investment_id}/memo-versions/{version_id}/report",
        "/investments/{investment_id}/memo-versions/{version_id}"
        "/exports/investment-memo.pdf",
    }
    routes = {
        (method, route.path)  # type: ignore[attr-defined]
        for route in app.routes
        for method in getattr(route, "methods", ()) or ()
        if any(
            word in str(getattr(route, "path", ""))
            for word in ("valuation-timepoint", "valuation-views", "evidence-references", "/memo")
        )
        and str(getattr(route, "path", "")) not in stage_4_routes
    }
    assert routes == {
        ("GET", "/investments/{investment_id}/valuation-timepoints"),
        ("POST", "/investments/{investment_id}/valuation-timepoints"),
        ("GET", "/investments/{investment_id}/valuation-timepoints/{timepoint_id}"),
        ("PUT", "/investments/{investment_id}/valuation-timepoints/{timepoint_id}"),
        ("DELETE", "/investments/{investment_id}/valuation-timepoints/{timepoint_id}"),
        ("POST", "/investments/{investment_id}/valuation-timepoint-order"),
        ("GET", "/deals/{deal_id}/valuation-timepoints"),
        ("POST", "/deals/{deal_id}/valuation-timepoints"),
        ("GET", "/investments/{investment_id}/evidence-references"),
        ("PUT", "/investments/{investment_id}/evidence-references/{evidence_id}"),
        ("DELETE", "/investments/{investment_id}/evidence-references/{evidence_id}"),
        ("POST", "/investments/{investment_id}/valuation-views/{strategy_id}/{scenario_id}"),
        ("GET", "/investments/{investment_id}/memo"),
        ("PUT", "/investments/{investment_id}/memo"),
        ("DELETE", "/investments/{investment_id}/memo"),
        ("GET", "/deals/{deal_id}/memo"),
        ("PUT", "/deals/{deal_id}/memo"),
        ("GET", "/investments/{investment_id}/memo/publication-readiness"),
        ("POST", "/investments/{investment_id}/memo/publish"),
        ("GET", "/investments/{investment_id}/memo-versions"),
        ("GET", "/investments/{investment_id}/memo-versions/{version_id}"),
        ("GET", "/investments/{investment_id}/memo-versions/{version_id}/freshness"),
        ("GET", "/investments/{investment_id}/memo-versions/{version_id}/decision"),
        ("PUT", "/investments/{investment_id}/memo-versions/{version_id}/decision"),
    }


def test_no_case_or_competition_identifier() -> None:
    import test_p7_0_decision_architecture as p7_0

    for path in sorted(_STAGE_2_PRODUCTION_FILES):
        source = _current(path)
        region = _p7_10_region(source) if path in {_API, _STORE, _FINGERPRINT, _CONTRACTS, _STRUCTURED} else source
        assert p7_0._case_identifiers_in(region) == [], path


# =============================================================================
# 11. The two ratified corrections (Section 22.6, 22.7)
# =============================================================================


def test_publication_judges_only_the_valuations_the_package_depends_on() -> None:
    """Correction 1, structurally. The rule reads one collection -- the required
    valuations the dependency layer handed it -- and has no way to reach the
    Investment's whole authored list, so an exploratory definition cannot block
    a publication even by accident."""

    source = _code_only(_current(_PUBLICATION))
    tree = ast.parse(_current(_PUBLICATION))
    rule = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_valuation_refusals"
    )
    body = _code_only(_code(rule))
    assert "context.required_valuations" in body
    for forbidden in ("list_valuation_timepoints", "surface", "views", "timepoints"):
        assert forbidden not in body, forbidden
    # The context offers nothing else to iterate: the superseded whole-surface
    # map is gone, not merely unused.
    assert "cited_valuations_available" not in source


def test_the_selection_is_an_explicit_relationship_and_never_an_inference() -> None:
    """Section 22.6: selection is a stored typed relationship. The dependency
    layer reads it from the draft's own field, and nothing in the P7.10 region
    derives it from display order, existence or recency."""

    dependencies = _code_only(_current(_DEPENDENCIES))
    assert "draft.selected_valuation_timepoint_ids" in dependencies
    assert re.search(r"CREATE TABLE IF NOT EXISTS memo_selected_valuations \(", _current(_STORE))

    required = next(
        node
        for node in ast.walk(ast.parse(_current(_DEPENDENCIES)))
        if isinstance(node, ast.FunctionDef) and node.name == "_required_valuations"
    )
    body = _code_only(_code(required))
    for forbidden in ("display_order", "created_at", "updated_at", "[0]", "[-1]"):
        assert forbidden not in body, forbidden


def test_a_claim_evidence_link_is_a_normalized_row_not_a_blob() -> None:
    """Correction 2: the relationship is a table with real columns on both
    sides, for the draft and for the frozen snapshot alike. A JSON column would
    make "what does this risk rest on" unanswerable without parsing."""

    store_source = _current(_STORE)
    for table in ("memo_claim_evidence", "memo_version_claim_evidence"):
        match = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n *\)", store_source, re.S)
        assert match is not None, table
        ddl = match.group(1)
        for column in ("claim_kind", "item_id", "evidence_id", "ordinal"):
            assert column in ddl, (table, column)
        for forbidden in ("JSON", "BLOB", "_json"):
            assert forbidden not in ddl.upper().replace("_JSON", "_json"), (table, forbidden)


def test_no_write_path_can_edit_a_frozen_claim_evidence_row() -> None:
    """The snapshot is covered by the same absolute rule as the rest of a
    published version: there is no UPDATE and no DELETE naming its table
    anywhere, so no supported operation can reach it."""

    source = _current(_STORE).upper()
    for statement in ("UPDATE MEMO_VERSION_CLAIM_EVIDENCE", "DELETE FROM MEMO_VERSION_CLAIM_EVIDENCE"):
        assert statement not in source, statement


def test_evidence_is_traceable_and_never_mandatory() -> None:
    """R-G's boundary. Every claim-bearing item declares the link with an empty
    default, so citing nothing is a legitimate state the type system permits --
    and no validation rule demands a citation for any field."""

    contracts = _current(_CONTRACTS_MEMO)
    for shape in ("class MemoItem", "class MemoRiskItem", "class MemoTermItem"):
        declaration = contracts[contracts.index(shape):]
        declaration = declaration[: declaration.index("@dataclass", 1)] if "@dataclass" in declaration[1:] else declaration
        assert "evidence_ids: tuple[str, ...] = ()" in declaration, shape

    validation = _code_only(_current(_VALIDATION))
    for forbidden in ("requires evidence", "must cite", "at least one evidence"):
        assert forbidden not in validation.lower(), forbidden
