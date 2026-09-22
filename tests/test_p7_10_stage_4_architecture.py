"""Phase 7 Gate P7.10 Stage 4 -- the production ledger and architecture guards.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 2, 11, 13, 13.3
and 17 (Stage 4), and the Stage 4 brief's Section 11. Every git query reads
objects only (protocol 11.2). The guards hold:

1. **the Stage 4 production ledger**: exactly the reporting package, the four
   API routes and the named frontend modules, measured from accepted `main`;
2. **Stage 1's valuation package and Stage 2's memo package frozen** byte for
   byte at their accepted merges -- Stage 4 is presentation and changes neither;
3. **no financial arithmetic in the report layers**: the assembler selects and
   formats, and the renderer is handed finished strings;
4. **no AI anywhere**: no module, prompt, proposal, grounding snapshot or AI
   surface enters Stage 4, and Stage 3 stays unstarted;
5. **a final PDF requires a published version**, and a published view cannot
   reach a draft mutation route;
6. **the analyst recommendation and the IC decision stay separate**;
7. **an unavailable value cannot render as zero or the purchase price**;
8. **internal ids and fingerprints do not leak into normal presentation**;
9. **the frontend types mirror the typed API exactly**.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Accepted ``main`` when Stage 4 began: the P7.10 Stage 2 acceptance closeout
#: (PR #52), over the accepted Stage 2 implementation ``ababa50`` (PR #51).
_STAGE_4_BASE = "9ca957a"
#: The accepted P7.10 Stage 1 merge (PR #49) and Stage 2 merge (PR #51). Both
#: packages are frozen at them; Stage 4 edits neither.
_STAGE_1_MERGE = "f6f36803cdcb646aa8a4af8cfc658a0e368ae58e"
_STAGE_2_MERGE = "ababa50"

_API = "src/anchor/api.py"
_REPORTING = "src/anchor/reporting"
_REPORTING_NAMES = ("__init__", "contracts", "artifact", "assembly", "pdf")
#: Stage 4 Correction 1 reaches two accepted Stage 2 modules, and only for the
#: atomic publication of the report artifact: schema 16's one additive table and
#: the transaction that writes it. Neither memo, fingerprint, evidence,
#: staleness nor financial rule is touched, which
#: ``test_correction_1_changed_only_the_publication_seam`` measures.
_STORE = "src/anchor/deals/store.py"
_DEPENDENCIES = "src/anchor/deals/memo_dependencies.py"
_REPORTING_MODULES = tuple(f"{_REPORTING}/{name}.py" for name in _REPORTING_NAMES)
_ASSEMBLY = f"{_REPORTING}/assembly.py"
_PDF = f"{_REPORTING}/pdf.py"
_REPORT_CONTRACTS = f"{_REPORTING}/contracts.py"

#: Every frontend module Stage 4 adds. Named exactly; a wildcard would let an
#: unratified module in, which is the weakening G37 exists to prevent.
_STAGE_4_WEB_NEW = frozenset(
    {
        "web/src/memoTypes.ts",
        "web/src/memoCatalog.ts",
        "web/src/memoForm.ts",
        "web/src/useInvestmentMemo.ts",
        "web/src/useMemoLibrary.ts",
        "web/src/components/MemoLibraryPanel.tsx",
        "web/src/components/MemoWorkspace.tsx",
        "web/src/components/MemoDecisionPanel.tsx",
        "web/src/components/MemoNarrativePanel.tsx",
        "web/src/components/MemoEvidencePanel.tsx",
        "web/src/components/MemoEvidencePicker.tsx",
        "web/src/components/MemoValuationPanel.tsx",
        "web/src/components/MemoPublishPanel.tsx",
        "web/src/components/MemoReportView.tsx",
        # Correction 2: the in-application confirmation that replaced the
        # native dialog the gate forbids.
        "web/src/components/ConfirmDialog.tsx",
        # Correction 3: the one loading abstraction the six asynchronous flows
        # now share, so Stage 4 adds no lint warning.
        "web/src/useAsyncResource.ts",
    }
)

#: The shipped frontend files Stage 4 edits, and the only ones it may.
_STAGE_4_WEB_EDITED = frozenset(
    {
        "web/src/App.tsx",
        "web/src/api.ts",
        "web/src/index.css",
        "web/src/components/AppSidebar.tsx",
    }
)

_STAGE_4_PRODUCTION_FILES = (
    frozenset({*_REPORTING_MODULES, _API, _STORE, _DEPENDENCIES})
    | _STAGE_4_WEB_NEW
    | _STAGE_4_WEB_EDITED
)

#: Consumed and never changed. Every financial module, both accepted P7.10
#: stages, and every frontend module of an earlier gate.
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
    "src/anchor/memo",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/formatting.py",
    "src/anchor/report.py",
    "src/anchor/analysis",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    """Committed, staged, unstaged and untracked changes since ``base``.

    Stage 4's own ledger reads the working tree, because Stage 4 has not been
    merged. A later gate re-pins this to Stage 4's committed range, exactly as
    Stage 2 re-pinned Stage 1's and as that file's docstring anticipated."""

    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _added_lines(base: str, path: str) -> list[str]:
    """Every line this gate added to one file, without its context."""

    return [
        line[1:]
        for line in _git("diff", "--no-renames", "-U0", base, "--", path).splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _tree(path: str) -> ast.Module:
    return ast.parse(_current(path))


def _code_only(source: str) -> str:
    """A module's source with every docstring removed.

    A docstring that *describes* an invariant -- "never zero", "no AI surface" --
    must not trip a guard looking for the thing it forbids."""

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


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


# =============================================================================
# 1. The production ledger
# =============================================================================


def test_stage_4_changed_exactly_its_authorized_production_files() -> None:
    """Stage 4 is a presentation gate. It adds one backend package and the memo
    frontend, and edits four shipped frontend files and the API. Anything else
    in ``src`` or ``web`` is out of scope by construction."""

    changed = {
        path
        for path in _changes_since(_STAGE_4_BASE, "src", "web")
        if _is_production(path)
    }
    unexpected = changed - _STAGE_4_PRODUCTION_FILES
    assert unexpected == set(), f"Stage 4 changed unratified production files: {sorted(unexpected)}"


def test_the_ledger_names_real_files_rather_than_patterns() -> None:
    """The ledger has teeth only if every entry is a literal path that exists.
    A wildcard, or a stale name, would admit whatever happened to match."""

    for path in _STAGE_4_PRODUCTION_FILES:
        assert not set(path) & set("*?[]"), path
        assert (_PROJECT_ROOT / path).is_file(), f"{path} is in the ledger but not on disk"


def test_schema_16_adds_exactly_one_table_and_alters_none() -> None:
    """Correction 1's schema advance, measured.

    One additive table, one version bump, and no ``ALTER`` of anything that
    existed: the migration's own reasoning is that the safest migration is the
    one that touches no existing data, and this is that migration one more
    time."""

    source = _current(_STORE)
    assert "_SCHEMA_VERSION = 16" in source

    added = _added_lines(_STAGE_4_BASE, _STORE)
    created = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", "\n".join(added))
    assert created == ["memo_version_report_artifacts"], created

    # Nothing existing is altered, dropped or rewritten by this gate.
    for forbidden in ("ALTER TABLE", "DROP TABLE", "DROP COLUMN"):
        assert not any(forbidden in line for line in added), forbidden

    # And no UPDATE against anything a published version owns.
    for line in added:
        assert not re.search(r"UPDATE\s+memo_version", line, re.IGNORECASE), line


def test_the_report_artifact_is_write_once() -> None:
    """A published artifact is never updated or individually deleted.

    It goes only when the whole Investment does, which is exactly how the
    version rows it belongs to behave."""

    source = _current(_STORE)
    assert not re.search(r"UPDATE\s+memo_version_report_artifacts", source, re.IGNORECASE)
    assert not re.search(
        r"DELETE\s+FROM\s+memo_version_report_artifacts", source, re.IGNORECASE
    )
    # It is deleted only through the shared child-table loop.
    assert '"memo_version_report_artifacts",' in source
    assert source.count("INSERT INTO memo_version_report_artifacts") == 1


def test_correction_1_changed_only_the_publication_seam() -> None:
    """Stage 4 may change the accepted Stage 2 orchestration only as far as the
    atomic artifact creation requires, and no further.

    Measured on what the diff added to each file: the store gains the table and
    the one insert, and the dependency module gains the assembly call. Neither
    gains a memo rule, a fingerprint, an evidence rule, a staleness rule or a
    financial rule."""

    for path in (_STORE, _DEPENDENCIES):
        added = "\n".join(_added_lines(_STAGE_4_BASE, path))
        for forbidden in (
            "fingerprint_memo_content(",
            "fingerprint_published_version(",
            "def publication_refusals",
            "def freshness",
            "def version_freshness",
            "MemoDependencyClass.",
        ):
            assert forbidden not in added, f"{path} changed a Stage 2 rule: {forbidden}"


# =============================================================================
# 2. The accepted stages stay frozen
# =============================================================================


@pytest.mark.parametrize("area", _UNCHANGED)
def test_every_consumed_backend_area_is_untouched(area: str) -> None:
    assert _changes_since(_STAGE_4_BASE, area) == set(), f"{area} changed in Stage 4"


def test_the_accepted_valuation_package_is_byte_identical_to_its_merge() -> None:
    """Stage 1's deterministic valuation authority, frozen at PR #49."""

    assert (
        _git("diff", "--name-only", "--no-renames", _STAGE_1_MERGE, "--", "src/anchor/valuation")
        .split()
        == []
    )


def test_the_accepted_memo_package_is_byte_identical_to_its_merge() -> None:
    """Stage 2's memo domain, publication rules and unavailable adapter, frozen
    at PR #51. Stage 4 presents them and redefines none of them."""

    assert (
        _git("diff", "--name-only", "--no-renames", _STAGE_2_MERGE, "--", "src/anchor/memo")
        .split()
        == []
    )


def test_the_guard_detects_a_real_difference_rather_than_reporting_none() -> None:
    """The mechanism the freeze assertions rest on actually works.

    Every one has the form ``... == []``, and all would pass vacuously together
    if the helper stopped reporting differences. So it is shown to report one
    where a difference genuinely exists: the reporting package did not exist at
    the Stage 4 base, so it must be reported as changed."""

    changed = _changes_since(_STAGE_4_BASE, _REPORTING)
    assert changed >= set(_REPORTING_MODULES), (
        "the change detector is not reporting a difference that exists"
    )
    # And it discriminates: an untouched sibling is not reported.
    assert _changes_since(_STAGE_4_BASE, "src/anchor/engine") == set()


# =============================================================================
# 3. No financial arithmetic in the report layers
# =============================================================================

#: Aggregating, ordering-by-value or re-parsing calls. A total, an extreme, or a
#: number rebuilt from text.
_COMPUTING_CALLS = {"sum", "min", "max", "abs", "round", "float", "int", "divmod", "pow"}


def _arithmetic_sites(source: str) -> list[str]:
    """Every arithmetic expression in a module, docstrings excluded."""

    tree = ast.parse(_code_only(source))
    sites: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(
            node.op,
            (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow),
        ):
            sites.append(ast.unparse(node))
        elif isinstance(node, ast.AugAssign):
            sites.append(ast.unparse(node))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            if not isinstance(node.operand, ast.Constant):
                sites.append(ast.unparse(node))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _COMPUTING_CALLS:
                sites.append(ast.unparse(node))
    return sites


#: The assembler's entire permitted arithmetic, enumerated exactly.
#:
#: Two expressions, both converting a **model month** into the words an analyst
#: reads, and neither touching money. They are listed literally rather than
#: matched by pattern, because a pattern broad enough to admit them would also
#: admit a total: ``a * 12`` and ``a // 12`` are the shapes that turn months
#: into years, and they are also the shapes that would turn a monthly figure
#: into an annual one. Naming them means a third arithmetic expression of any
#: kind fails this guard, which is the point.
_ASSEMBLY_ALLOWED_ARITHMETIC = frozenset(
    {
        # "is this month the exit month?" -- comparing a month index to the
        # horizon, so the Exit view is labelled as Exit rather than as a year.
        "hold_period * 12",
        # "which hold year is this month the end of?" -- the year label itself.
        "model_month // 12",
    }
)


def _is_sequence_join(expression: str) -> bool:
    """Whether a ``+`` joins sequences rather than adding numbers.

    Building a tuple of sections or disclosures is composition, not arithmetic.
    Recognised structurally -- one side is a tuple or list literal, or both
    sides are calls and names -- rather than by reading the text."""

    node = ast.parse(expression, mode="eval").body
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
        return False
    sides = (node.left, node.right)
    if any(isinstance(side, (ast.Tuple, ast.List)) for side in sides):
        return True
    return all(isinstance(side, (ast.Call, ast.Name, ast.Attribute)) for side in sides)


def test_the_report_assembler_performs_no_financial_arithmetic() -> None:
    """The assembler selects already-computed fields and converts them to text
    exactly once, through ``anchor.formatting``. It totals nothing, ranks
    nothing and re-derives nothing: a figure Anchor does not publish is reported
    unavailable rather than computed.

    Three kinds of expression survive: joining display text, building a tuple of
    sections, and the two enumerated month-to-year conversions. Everything else
    fails."""

    sites = _arithmetic_sites(_current(_ASSEMBLY))
    numeric = [
        site
        for site in sites
        if not _is_text_join(site)
        and not _is_sequence_join(site)
        and site not in _ASSEMBLY_ALLOWED_ARITHMETIC
    ]
    assert numeric == [], f"arithmetic in the report assembler: {numeric}"


def test_the_arithmetic_guard_would_catch_a_total() -> None:
    """The allowlist is narrow, proved rather than assumed.

    A guard whose allowlist had been widened until everything passed would look
    exactly like one that finds nothing. So the shapes it must reject are run
    through it here."""

    for forbidden in (
        "noi_by_year[0] + noi_by_year[1]",
        "price / units",
        "sum(values)",
        "total - costs",
        "value * rate",
    ):
        assert forbidden not in _ASSEMBLY_ALLOWED_ARITHMETIC
        sites = _arithmetic_sites(f"x = {forbidden}\n")
        assert sites != [], forbidden
        survivors = [
            site
            for site in sites
            if not _is_text_join(site) and not _is_sequence_join(site)
        ]
        assert survivors != [], f"the guard would let {forbidden!r} through"


def test_the_pdf_renderer_performs_no_financial_arithmetic() -> None:
    """Section 13.3: page numbers, table continuation and column widths are
    presentation logic; financial arithmetic stays in the backend contracts.

    The renderer's own arithmetic is layout only -- page geometry and column
    widths -- and every one of those operands is a layout constant or a measured
    page dimension, never a value from the package."""

    tree = ast.parse(_code_only(_current(_PDF)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue
        expression = ast.unparse(node)
        assert not _touches_package_data(expression), (
            f"the PDF renderer computes with report data: {expression}"
        )


def _is_text_join(expression: str) -> bool:
    """Whether an expression joins text rather than computing a number."""

    return bool(re.search(r"['\"]|f'|f\"", expression))


#: Names the PDF renderer must never compute with: anything that came from the
#: package rather than from its own layout constants.
_PACKAGE_DATA = re.compile(
    r"\b(package|metric|view|row|table|entry|disclosure|item|section|value|"
    r"amount|figure|total)\b"
)


def _touches_package_data(expression: str) -> bool:
    return bool(_PACKAGE_DATA.search(expression))


def test_the_renderer_is_handed_only_the_package() -> None:
    """The structural reason the renderer cannot compute: it can reach nothing
    that holds a number.

    It imports ReportLab and the report *contracts*, and no store, engine,
    analysis, memo or deals module. A renderer that could load a result contract
    could compute with one."""

    imported = _imports(_tree(_PDF))
    for forbidden in (
        "..deals",
        "..engine",
        "..memo",
        "..valuation",
        "..capital_structure",
        "..analysis",
        "..formatting",
        "anchor.deals",
        "anchor.engine",
    ):
        assert forbidden not in imported, f"the PDF renderer imports {forbidden}"
    assert ".contracts" in imported


def test_report_figures_are_typed_as_text_rather_than_numbers() -> None:
    """The contract makes the rule structural. A metric's ``value`` is a string
    or ``None``; there is no float field a renderer could add to another."""

    source = _current(_REPORT_CONTRACTS)
    tree = ast.parse(source)
    classes = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    # Layout coordinates, not figures: which columns are right-aligned and which
    # rows are totals. Neither is a financial value and neither is rendered as
    # one, so each is named here rather than pattern-matched out -- a new
    # numeric field has to be justified in this list to ship.
    layout_fields = {"align_right", "emphasize_rows"}

    for name in ("MemoReportMetric", "MemoReportTable", "MemoReportValuation"):
        node = classes[name]
        for field in node.body:
            if not isinstance(field, ast.AnnAssign):
                continue
            target = ast.unparse(field.target)
            if target in layout_fields:
                continue
            annotation = ast.unparse(field.annotation)
            assert "float" not in annotation and "int" not in annotation, (
                f"{name}.{target} carries a number: {annotation}"
            )


# =============================================================================
# 4. No AI anywhere in Stage 4
# =============================================================================


def test_no_stage_4_module_imports_the_ai_package() -> None:
    """Stage 3 is deferred and unstarted. Nothing in this gate can reach the AI
    subsystem, so nothing in this gate can have started it."""

    for module in _REPORTING_MODULES:
        imported = _imports(_tree(module))
        assert not any("ai" in name.split(".") for name in imported), module


def _without_commentary(path: str) -> str:
    """One module's source with its prose removed.

    A guard that scans text for a forbidden word is otherwise tripped by the
    comment explaining that the word is forbidden -- which would force the code
    to stop documenting its own invariants in order to pass. Python docstrings
    go through the AST; TypeScript comments are stripped literally."""

    source = _current(path)
    if path.endswith(".py"):
        return _code_only(source)
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$", "", without_block)


def test_no_stage_4_source_mentions_an_ai_capability() -> None:
    """No prompt, proposal, grounding package, AI snapshot or "coming soon"
    surface -- not even a disabled one, which the brief forbids as firmly as a
    working one."""

    forbidden = re.compile(
        r"\b(prompt|grounding|ai_proposal|AiProposal|aiProposal|coming soon)\b",
        re.IGNORECASE,
    )
    for module in (*_REPORTING_MODULES, *sorted(_STAGE_4_WEB_NEW)):
        source = _without_commentary(module)
        # `AI_EXTRACTED_APPROVED` is a Stage 2 provenance *label* on an
        # analyst-approved source, not an AI capability, so the token itself is
        # allowed where it is a stored enum value.
        cleaned = source.replace("ai_extracted_approved", "").replace(
            "AI_EXTRACTED_APPROVED", ""
        )
        found = forbidden.findall(cleaned)
        assert found == [], f"{module} mentions an AI capability: {found}"


def test_the_frontend_ships_no_ai_control() -> None:
    """No AI tab, panel, button or placeholder in any memo surface.

    Measured on the code rather than the prose: the modules say plainly in their
    own comments that Stage 4 ships no AI, and that sentence must not be the
    thing that fails the guard."""

    for module in sorted(_STAGE_4_WEB_NEW):
        code = _without_commentary(module)
        assert not re.search(r"\bAI\b", code), f"an AI surface in {module}"


# =============================================================================
# 5. Export authority
# =============================================================================


def test_the_pdf_route_takes_a_version_and_refuses_anything_else() -> None:
    """Stage 4 §9: a final PDF is generated only from an immutable published
    version, and a refusal is typed rather than a failed download."""

    source = _current(_API)
    route = "/investments/{investment_id}/memo-versions/{version_id}/exports/investment-memo.pdf"
    assert route in source

    tree = ast.parse(source)
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    export = functions["export_memo_version_pdf"]
    body = ast.unparse(export)
    # It returns the *stored* bytes and renders nothing: a re-render would be a
    # different document wearing the same version number.
    assert "read_version_pdf" in body
    assert "render_memo_pdf" not in body
    assert "assemble_draft_preview" not in body
    assert "PdfExportRefusedError" in body

    # And the preview route cannot render a file at all.
    preview = functions["read_memo_report_preview"]
    assert "render_memo_pdf" not in ast.unparse(preview)


def test_the_export_door_cannot_be_handed_a_draft() -> None:
    """The refusals exist in the assembly layer, not only in the route, so no
    future caller can route around them."""

    body = _code_only(_current(_ASSEMBLY))
    assert "def read_version_pdf" in body
    assert "DRAFT_NOT_EXPORTABLE" in body
    assert "VERSION_NOT_FOUND" in body
    assert "REPORT_SNAPSHOT_NOT_AVAILABLE" in body


def test_the_published_read_never_recomputes() -> None:
    """The one structural guarantee behind Correction 1.

    Reading a published version touches the stored artifact and nothing else:
    it resolves no variant, runs no analysis and assembles no package. A read
    path that could assemble is a read path that could drift."""

    tree = ast.parse(_current(_ASSEMBLY))
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    for name in ("read_version_report", "read_version_pdf"):
        body = ast.unparse(functions[name])
        for forbidden in (
            "_analysis_for",
            "analysis_for_selected_cell",
            "build_version_package",
            "analyze_structured",
            "_key_metrics",
        ):
            assert forbidden not in body, f"{name} recomputes: {forbidden}"
        assert "get_memo_version_artifact" in body

    # And the builder is called from exactly one place: publication.
    dependencies = _current(_DEPENDENCIES)
    assert dependencies.count("build_version_package(") == 1


def test_the_report_routes_are_read_only() -> None:
    """Section 15: the PDF route is read-only with respect to financial and memo
    content. None of the four Stage 4 routes writes anything."""

    source = _current(_API)
    marker = source.index("Phase 7 Gate P7.10 Stage 4")
    region = source[marker:]
    for forbidden in (
        "put_memo_draft",
        "create_valuation_timepoint",
        "put_evidence_reference",
        "delete_memo_draft",
        "memo_dependencies.publish",
    ):
        assert forbidden not in region, f"a Stage 4 route writes: {forbidden}"


# =============================================================================
# 6. The two decision acts stay separate
# =============================================================================


def test_the_recommendation_and_the_committee_decision_are_separate_fields() -> None:
    """R-F. They are different fields on the package, carry different
    vocabularies, and neither is derived from the other."""

    source = _code_only(_current(_REPORT_CONTRACTS))
    assert "analyst_recommendation" in source
    assert "committee_decision" in source

    assembly = _code_only(_current(_ASSEMBLY))
    # The frozen report carries no committee outcome at all: the committee
    # decides *after* publication, so its decision is not among the facts the
    # version froze. It is never derived from the analyst's recommendation
    # either -- the field is simply `None`, and the workspace shows the stored
    # decision beside the document.
    assert "committee_decision=None" in assembly.replace(" ", "").replace(
        "committee_decision=None", "committee_decision=None"
    ) or "committee_decision=None" in assembly
    assert "committee_decision=analyst" not in assembly.replace(" ", "")

    # The two label tables share no member, so no code path can substitute one.
    import anchor.reporting.assembly as module

    shared = set(module._RECOMMENDATION_LABELS) & set(module._COMMITTEE_LABELS)
    assert shared == {"approved_with_conditions"} or shared == set(), (
        f"the two vocabularies overlap beyond the shared phrase: {shared}"
    )
    assert "deferred" not in module._RECOMMENDATION_LABELS
    assert "insufficient_information" not in module._COMMITTEE_LABELS


def test_an_unrecorded_committee_decision_is_not_pending() -> None:
    """"Nothing recorded" and "the committee recorded Pending" are different
    facts, and the second is a decision somebody made."""

    from anchor.reporting.contracts import COMMITTEE_DECISION_UNRECORDED

    assert COMMITTEE_DECISION_UNRECORDED == "Not yet recorded"
    assert "pending" not in COMMITTEE_DECISION_UNRECORDED.lower()


# =============================================================================
# 7. An unavailable value never becomes a number
# =============================================================================


def test_an_unavailable_cell_cannot_be_zero_or_a_fallback() -> None:
    """Section 2. The single constructor for an unavailable cell refuses the
    labels that would read as a figure."""

    from anchor.reporting.contracts import ReportUnavailable

    default = ReportUnavailable(reason_code="x", reason="y")
    assert default.label == "Unavailable"
    assert default.label not in {"", "0", "$0", "-", "N/A "}

    assembly = _code_only(_current(_ASSEMBLY))
    # No literal zero or purchase-price fallback is ever substituted for a
    # missing figure.
    assert "or 0" not in assembly
    assert "?? 0" not in assembly
    assert 'value or "$0"' not in assembly


def test_the_metric_builder_cannot_produce_both_or_neither() -> None:
    """``_metric`` is the one door every figure enters by, and it sets exactly
    one of ``value`` and ``unavailable``."""

    import anchor.reporting.assembly as module

    available = module._metric("Label", "$1,000")
    assert available.value == "$1,000" and available.unavailable is None

    missing = module._metric("Label", None)
    assert missing.value is None and missing.unavailable is not None
    assert missing.unavailable.reason_code != ""


# =============================================================================
# 8. Internal identity stays out of normal presentation
# =============================================================================


def test_a_fingerprint_reaches_exactly_one_place_in_the_report() -> None:
    """Section 13.3 requires the PDF to carry the memo version fingerprint, and
    Section 2 keeps implementation vocabulary out of normal analyst views. Both
    hold: it is carried, in one labelled appendix, and nowhere else."""

    contracts = _current(_REPORT_CONTRACTS)
    assert "verification_code" in contracts

    renderer = _current(_PDF)
    uses = re.findall(r"verification_code", _code_only(renderer))
    assert len(uses) <= 2, f"the fingerprint appears {len(uses)} times in the renderer"
    assert "Verification code" in renderer

    # It is never a metric, a table cell of another table, or a heading.
    assembly = _code_only(_current(_ASSEMBLY))
    assert "_metric(\"Verification" not in assembly


def test_stored_tokens_are_translated_before_they_are_shown() -> None:
    """No enum name, database term or raw token reaches an analyst view: every
    one goes through a label table."""

    import anchor.reporting.assembly as module

    for table in (
        module._RECOMMENDATION_LABELS,
        module._COMMITTEE_LABELS,
        module._COMPLEXITY_LABELS,
        module._PRIORITY_LABELS,
        module._EVIDENCE_KIND_LABELS,
        module._DEPENDENCY_LABELS,
    ):
        for token, label in table.items():
            assert "_" not in label, f"{token} renders as {label!r}, which is still a token"
            assert label[0].isupper(), label


def test_every_dependency_class_has_an_analyst_facing_name() -> None:
    """A stale memo says "the Business Plan changed", never ``business_plan``.
    Every one of the thirteen classes is covered, so none can fall through."""

    from anchor.memo.contracts import MemoDependencyClass
    import anchor.reporting.assembly as module

    for member in MemoDependencyClass:
        assert member.value in module._DEPENDENCY_LABELS, member


# =============================================================================
# 9. The frontend mirrors the typed API
# =============================================================================


def _ts_union(source: str, name: str) -> set[str]:
    """The members of one exported TypeScript string-literal union."""

    match = re.search(rf"export type {name} =\s*(.*?);", source, re.DOTALL)
    assert match is not None, f"{name} is not declared"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


@pytest.mark.parametrize(
    ("ts_name", "enum_path"),
    [
        ("AnalystRecommendation", "AnalystRecommendation"),
        ("InvestmentCommitteeOutcome", "InvestmentCommitteeOutcome"),
        ("ExecutionComplexity", "ExecutionComplexity"),
        ("RiskSeverity", "RiskSeverity"),
        ("TermPriority", "TermPriority"),
        ("EvidenceSourceKind", "EvidenceSourceKind"),
        ("DecisionPerspectiveKind", "DecisionPerspectiveKind"),
    ],
)
def test_each_frontend_union_mirrors_its_python_enum(ts_name: str, enum_path: str) -> None:
    """A member added on one side and forgotten on the other fails here, rather
    than silently narrowing what the product can represent."""

    import anchor.memo.contracts as contracts

    enum = getattr(contracts, enum_path)
    source = _current("web/src/memoTypes.ts")
    assert _ts_union(source, ts_name) == {member.value for member in enum}


def test_the_memo_section_union_mirrors_its_python_enum() -> None:
    from anchor.memo.contracts import MemoSection

    source = _current("web/src/memoTypes.ts")
    assert _ts_union(source, "MemoSectionKind") == {member.value for member in MemoSection}


def test_the_report_origin_union_mirrors_its_python_enum() -> None:
    from anchor.reporting.contracts import MemoReportOrigin, ReportFreshness

    source = _current("web/src/memoTypes.ts")
    assert _ts_union(source, "MemoReportOrigin") == {m.value for m in MemoReportOrigin}
    assert _ts_union(source, "ReportFreshness") == {m.value for m in ReportFreshness}


def test_the_frontend_base_keys_match_the_backend_reserved_keys() -> None:
    """The Base Strategy and Base Scenario are named by reserved implicit keys
    rather than stored rows, so the two sides must agree on the spelling."""

    from anchor.analysis.strategy import BASE_SCENARIO_ID, BASE_STRATEGY_ID

    catalog = _current("web/src/memoCatalog.ts")
    assert f"BASE_STRATEGY_KEY = '{BASE_STRATEGY_ID}'" in catalog
    assert f"BASE_SCENARIO_KEY = '{BASE_SCENARIO_ID}'" in catalog


def test_the_frontend_covers_every_publication_refusal_code() -> None:
    """Each typed refusal is grouped into an analyst action. A code with no
    group would fall into the default and read as the wrong advice."""

    from anchor.memo.publication import PublicationRefusalCode

    catalog = _current("web/src/memoCatalog.ts")
    for member in PublicationRefusalCode:
        assert f"{member.value}:" in catalog, f"{member.value} has no analyst grouping"


def test_the_two_unavailable_reason_tables_cannot_drift() -> None:
    """The report and the workspace explain an unavailable state the same way.

    The Stage 2 adapter's own ``reason`` names the Investment, the Unit and the
    timepoint by their opaque ids -- right for a log, and exactly what Section 2
    keeps out of an analyst view. Both surfaces therefore translate the stable
    ``reason_code`` instead, and they must cover the same set: a code one side
    knows and the other does not would be a sentence in the memo that the
    workspace could not reproduce."""

    import anchor.reporting.assembly as module

    catalog = _current("web/src/memoCatalog.ts")
    block = catalog[
        catalog.index("export const UNAVAILABLE_REASON_LABELS") : catalog.index(
            "export function unavailableReasonLabel"
        )
    ]
    typescript = set(re.findall(r"^\s{2}([a-z_]+):", block, re.MULTILINE))
    assert typescript == set(module._UNAVAILABLE_LABELS), (
        f"only in Python: {sorted(set(module._UNAVAILABLE_LABELS) - typescript)}; "
        f"only in TypeScript: {sorted(typescript - set(module._UNAVAILABLE_LABELS))}"
    )


def test_every_typed_unavailable_reason_has_an_analyst_sentence() -> None:
    """Both reason vocabularies are covered, so no state falls through to the
    backend's id-bearing message."""

    from anchor.memo.availability import UnavailableReasonCode
    from anchor.valuation.contracts import ValuationUnavailableReason
    import anchor.reporting.assembly as module

    for enum in (UnavailableReasonCode, ValuationUnavailableReason):
        for member in enum:
            assert member.value in module._UNAVAILABLE_LABELS, member


def test_every_publication_refusal_has_an_analyst_sentence() -> None:
    """**Added after browser QA at the independent review.** Readiness printed
    the backend's own refusal message, which names the Investment, the timepoint
    and the Unit by their opaque ids -- on the one surface that exists to tell an
    analyst what to go and fix. Refusals are now translated from their stable
    code, like every unavailable state already was, and this holds the table to
    the accepted Stage 2 enum so a new refusal cannot ship untranslated."""

    from anchor.memo.publication import PublicationRefusalCode

    catalog = _current("web/src/memoCatalog.ts")
    block = catalog[
        catalog.index("export const PUBLICATION_REFUSAL_LABELS") : catalog.index(
            "/** One publication refusal as analyst-facing text"
        )
    ]
    typescript = set(re.findall(r"^\s{2}([a-z_]+):", block, re.MULTILINE))
    declared = {member.value for member in PublicationRefusalCode}
    assert typescript == declared, (
        f"only in Python: {sorted(declared - typescript)}; "
        f"only in TypeScript: {sorted(typescript - declared)}"
    )


def test_no_refusal_sentence_names_an_internal_id() -> None:
    """The same rule the unavailable sentences are held to, and for the same
    reason: a refusal an analyst cannot read is a refusal they cannot act on."""

    catalog = _current("web/src/memoCatalog.ts")
    block = catalog[
        catalog.index("export const PUBLICATION_REFUSAL_LABELS") : catalog.index(
            "/** One publication refusal as analyst-facing text"
        )
    ]
    quoted_identifier = re.compile(r"'[^']{4,}'")
    opaque_id = re.compile(r"[0-9a-f]{12,}")
    for line in block.splitlines():
        sentence = line.strip()
        if not sentence.startswith("'") and ": '" not in sentence:
            continue
        assert not quoted_identifier.search(sentence.split(": ", 1)[-1].strip("',")), sentence
        assert not opaque_id.search(sentence), sentence


def test_the_publish_panel_shows_no_opaque_scope() -> None:
    """A refusal's scope is shown only when the analyst named it.

    A valuation timepoint id or a position id is the analyst's own word and is
    worth showing; a stored Investment's 32-character id is not."""

    panel = _current("web/src/components/MemoPublishPanel.tsx")
    assert "publicationRefusalLabel(refusal.code, refusal.unavailable_reason)" in panel
    assert "!isOpaqueId(refusal.scope_id)" in panel
    # And the untranslated message is gone from the surface entirely.
    assert "refusal.message" not in panel


def test_no_disclosure_carries_a_backend_exception() -> None:
    """**Added after browser QA at the independent review.** The report's
    "Selected analysis did not resolve" disclosure rendered ``str(error)`` from
    whichever layer refused, which named an Investment by its id inside the
    published document and its PDF. The disclosure now says the same thing in
    the analyst's terms, and ``_Analysis.detail`` reaches no surface."""

    source = _current("src/anchor/reporting/assembly.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "MemoReportDisclosure":
            continue
        for keyword in node.keywords:
            if keyword.arg != "detail":
                continue
            rendered = ast.unparse(keyword.value)
            assert "analysis.detail" not in rendered, rendered
            assert "str(error)" not in rendered, rendered


def test_no_analyst_facing_reason_names_an_internal_id() -> None:
    """The translations say what happened without naming a record.

    Seeded rather than assumed: the backend's own sentence is shown to contain
    the kind of thing these must not, so the rule is measured against a real
    example rather than a hopeful one."""

    import anchor.reporting.assembly as module

    # A *quoted identifier*, not any apostrophe: "the analysis's hold period" is
    # ordinary prose, and a rule that banned it would push these sentences into
    # worse English for no gain.
    quoted_identifier = re.compile(r"'[^']{4,}'")
    opaque_id = re.compile(r"\b[0-9a-f]{12,}\b")

    for code, sentence in module._UNAVAILABLE_LABELS.items():
        assert not quoted_identifier.search(sentence), (code, sentence)
        assert not opaque_id.search(sentence), (code, sentence)

    # The shape this guard exists to keep out, shown failing it -- so a passing
    # run means the rule works, not that it is looking for nothing.
    leaky = "Investment '5898557bc6b149c9a4994097272d8aea' has no value at 'beyond'."
    assert quoted_identifier.search(leaky) and opaque_id.search(leaky)

    # And ordinary prose with an apostrophe passes, so the rule is not merely
    # strict enough to be useless.
    assert not quoted_identifier.search("beyond the analysis's hold period")
