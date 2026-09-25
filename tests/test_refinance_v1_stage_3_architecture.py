"""Refinance & Capital Events V1 Stage 3 -- the architecture guard.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 12.5, 16.3, 20
(Stage 3) and 25. Every git query reads objects only (protocol 11.2). The
guards hold:

1. **the ledger**: Stage 3 changes exactly its declared production files since
   the accepted baseline ``bd77433`` (Stage 2 accepted; product tree
   ``879f577``);
2. **the frozen engine**: every financial authority -- the capital-structure
   executor and refinance engine, the acquisition engine, valuation,
   partnership, consolidation, the analysis layer, schema and codec -- is
   byte-identical to the baseline;
3. **no financial arithmetic**: the new report and presentation modules have
   none; every changed module keeps its baseline arithmetic exactly, except the
   enumerated Excel layout arithmetic; the audit's source computes nothing at
   all -- its eligibility is decided from typed accepted facts, and INV-5 is
   reconciled by the workbook's own formulas;
4. **the gate is gone through one seam**: ``refinance_reporting_not_available``
   is spelled nowhere in production code, and the only refinance publication
   refusal is ``refinance_result_unavailable``, fed by one function;
5. **one importer**: only ``api.py`` imports ``anchor.exports.refinance``.

This is Stage 3's own guard, measured in the working tree while the stage is
unmerged. A later gate re-pins it to Stage 3's committed range, as Stage 3
re-pinned the Stage 2 guard.
"""

from __future__ import annotations

import ast
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Accepted ``main`` when Stage 3 began: PR #61 merge, product tree ``879f577``.
_BASE = "bd77433a36f08b042ced51e9cc2c6fe086991889"
_STAGE_2_MERGE = "879f577"

_NEW_PYTHON = (
    "src/anchor/deals/refinance_presentation.py",
    "src/anchor/exports/refinance/__init__.py",
    "src/anchor/exports/refinance/audit.py",
    "src/anchor/exports/refinance/source.py",
    "src/anchor/reporting/refinance.py",
)
_CHANGED_PYTHON = (
    "src/anchor/api.py",
    "src/anchor/deals/decision_matrix.py",
    "src/anchor/deals/memo_dependencies.py",
    "src/anchor/deals/partnership_variants.py",
    "src/anchor/deals/structured_variants.py",
    "src/anchor/decision/comparison.py",
    "src/anchor/exports/excel/_workbook.py",
    "src/anchor/exports/excel/source.py",
    "src/anchor/memo/publication.py",
    "src/anchor/reporting/assembly.py",
)
_NEW_WEB = (
    "web/src/capitalEventForm.ts",
    "web/src/refinanceCatalog.ts",
    "web/src/useCapitalEventAudit.ts",
    "web/src/useCapitalEventChoices.ts",
    "web/src/useRefinancePresence.ts",
    "web/src/components/AcquisitionReference.tsx",
    "web/src/components/CapitalEventAuditAction.tsx",
    "web/src/components/CapitalEventEditor.tsx",
    "web/src/components/CapitalEventMatrixNote.tsx",
    "web/src/components/CapitalEventResults.tsx",
)
_CHANGED_WEB = (
    "web/src/App.tsx",
    "web/src/api.ts",
    "web/src/capitalStructureForm.ts",
    "web/src/capitalTypes.ts",
    "web/src/components/CapitalEconomicsSection.tsx",
    "web/src/components/CapitalStructureEditor.tsx",
    "web/src/components/CapitalStructureResults.tsx",
    "web/src/components/CapitalStructureWorkspace.tsx",
    "web/src/components/DecisionMatrixPanel.tsx",
    "web/src/components/InvestmentOverview.tsx",
    "web/src/components/InvestmentWorkspace.tsx",
    "web/src/components/LeaseLevelMetricSummary.tsx",
    "web/src/components/LiveCaseRail.tsx",
    "web/src/components/OwnerSummaryPanel.tsx",
    "web/src/components/PartnerDecisionMatrixPanel.tsx",
    "web/src/components/PartnershipResults.tsx",
    "web/src/components/PartnershipWorkspace.tsx",
    "web/src/components/PositionDecisionMatrixPanel.tsx",
    "web/src/components/ResultsSummaryPanel.tsx",
    "web/src/components/StrategyEditor.tsx",
    "web/src/index.css",
    "web/src/memoCatalog.ts",
    "web/src/partnershipTypes.ts",
    "web/src/useCapitalStructure.ts",
    "web/src/useStrategies.ts",
)

#: Every production file Stage 3 changes, exactly (Section 20, Stage 3).
_STAGE_3_PRODUCTION_FILES = frozenset((*_NEW_PYTHON, *_CHANGED_PYTHON, *_NEW_WEB, *_CHANGED_WEB))

#: Every financial authority Stage 3 consumes and must not change.
_FROZEN = (
    "src/anchor/capital_structure",
    "src/anchor/engine",
    "src/anchor/valuation",
    "src/anchor/partnership",
    "src/anchor/consolidation",
    "src/anchor/analysis",
    "src/anchor/investment",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/asset_management",
    "src/anchor/formatting.py",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/deals/store.py",
    "src/anchor/deals/capital_structure_codec.py",
    "src/anchor/deals/fingerprint.py",
    "src/anchor/deals/refinance_integration.py",
    "src/anchor/deals/capital_event_identity.py",
    "src/anchor/deals/valuation_views.py",
    "src/anchor/memo/contracts.py",
    "src/anchor/memo/availability.py",
    "src/anchor/reporting/contracts.py",
    "src/anchor/reporting/pdf.py",
    "src/anchor/reporting/artifact.py",
    "src/anchor/exports/excel/quick_audit.py",
    "src/anchor/exports/excel/detailed_audit.py",
    "src/anchor/exports/excel/lease_level_audit.py",
    "src/anchor/exports/excel/filenames.py",
)

#: The label-wrapping layout the acquisition-reference rows need (row heights
#: and label widths, in characters). No figure is computed.
_WORKBOOK_LAYOUT_ADDITIONS = Counter(
    {
        "HEADER_LINE_HEIGHT * _wrapped_lines(text, int(room * LABEL_CHARS_PER_WIDTH))": 1,
        "room * LABEL_CHARS_PER_WIDTH": 1,
        "self.column_width[sheet].get(0, DEFAULT_COLUMN_WIDTH) - 1": 1,
        "self.column_width[sheet].get(0, DEFAULT_COLUMN_WIDTH) - 1 - INDENT_CHARS": 1,
    }
)

#: Numeric calls that would let the audit source recompute or compare a figure
#: without an arithmetic operator: a total, an extreme, a tolerance or a round.
_NUMERIC_CALLS = frozenset({"abs", "sum", "min", "max", "round", "isclose", "fsum", "prod"})


#: Names the audit workbook's layout arithmetic may operate on: rows, columns,
#: periods and counts. Every financial figure in the audit is an Excel formula
#: string or a frozen Anchor value, never a Python result.
_LAYOUT_NAMES = frozenset(
    {
        "row", "hold", "t", "c0", "m", "month", "offset", "first", "last", "sale", "header_row",
        "period_columns", "label", "record_first_row", "status_rows", "len", "event", "loan", "self",
    }
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and not path.endswith((".test.ts", ".test.tsx"))


def _changes_since(base: str, *paths: str) -> set[str]:
    """Tracked changes since ``base`` in the working tree, plus new files."""

    tracked = _git("diff", "--name-only", "--no-renames", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path and "__pycache__" not in path}


def _current(path: str) -> str:
    return (_PROJECT_ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")


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


def _arithmetic_nodes(tree: ast.AST) -> list[ast.AST]:
    return [
        child
        for child in ast.walk(tree)
        if (
            isinstance(child, (ast.BinOp, ast.AugAssign))
            and isinstance(child.op, _ARITHMETIC)
            and not (isinstance(child, ast.BinOp) and (_is_text(child.left) or _is_text(child.right)))
        )
        or (isinstance(child, ast.UnaryOp) and isinstance(child.op, (ast.USub, ast.UAdd)))
    ]


def _arithmetic(tree: ast.AST) -> list[str]:
    return sorted(ast.unparse(node) for node in _arithmetic_nodes(tree))


# =============================================================================
# 1. The ledger
# =============================================================================


def test_stage_3_changes_exactly_its_declared_production_files() -> None:
    changed = {path for path in _changes_since(_BASE, "src", "web") if _is_production(path)}
    assert changed == set(_STAGE_3_PRODUCTION_FILES), (
        f"unexpected: {sorted(changed - _STAGE_3_PRODUCTION_FILES)}; missing: {sorted(_STAGE_3_PRODUCTION_FILES - changed)}"
    )


def test_the_ledger_base_is_the_accepted_stage_2_closeout() -> None:
    """``bd77433`` is PR #61's merge, and its product tree is Stage 2's
    accepted merge ``879f577``: the acceptance PR changed documentation only."""

    assert _git("diff", "--name-only", _STAGE_2_MERGE, _BASE, "--", "src", "web", "tests").split() == []


def test_the_new_modules_are_new_at_this_stage() -> None:
    for path in (*_NEW_PYTHON, *_NEW_WEB):
        assert _git("ls-tree", "--name-only", _BASE, path).strip() == "", path


def test_the_ledger_guard_has_teeth() -> None:
    """The ledger reads real changes: the accepted Stage 2 range is not empty
    under the same query."""

    assert _git("diff", "--name-only", "--no-renames", "f2b5cefa7fca3ecde7621927c5818cbc40c068cd", _BASE, "--", "src").split()


# =============================================================================
# 2. The frozen engine
# =============================================================================


@pytest.mark.parametrize("path", _FROZEN)
def test_no_financial_authority_changed(path: str) -> None:
    assert _changes_since(_BASE, path) == set(), path


def test_no_schema_change() -> None:
    """Stage 3 is presentation: the store, and so schema 17, is untouched."""

    assert "src/anchor/deals/store.py" not in _changes_since(_BASE, "src")


# =============================================================================
# 3. No financial arithmetic
# =============================================================================


@pytest.mark.parametrize(
    "path",
    ("src/anchor/deals/refinance_presentation.py", "src/anchor/reporting/refinance.py"),
)
def test_the_report_and_presentation_modules_have_no_arithmetic(path: str) -> None:
    assert _arithmetic(_code(_current(path))) == [], path


def test_the_audit_filename_joins_text_only() -> None:
    assert _arithmetic(_code(_current("src/anchor/exports/refinance/__init__.py"))) == [
        "sanitize_deal_name(investment_name) + REFINANCE_AUDIT_SUFFIX"
    ]


@pytest.mark.parametrize("path", _CHANGED_PYTHON)
def test_every_changed_module_keeps_its_baseline_arithmetic(path: str) -> None:
    added = Counter(_arithmetic(_code(_current(path)))) - Counter(_arithmetic(_code(_at(_BASE, path))))
    removed = Counter(_arithmetic(_code(_at(_BASE, path)))) - Counter(_arithmetic(_code(_current(path))))
    expected = _WORKBOOK_LAYOUT_ADDITIONS if path.endswith("_workbook.py") else Counter()

    assert (added, removed) == (expected, Counter()), path


def _numeric_calls(tree: ast.AST) -> list[str]:
    return sorted(
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in _NUMERIC_CALLS)
            or (isinstance(node.func, ast.Attribute) and node.func.attr in _NUMERIC_CALLS)
        )
    )


def test_the_audit_source_computes_nothing() -> None:
    """Stage 3 review correction: whether the audit may exist is decided from
    typed accepted facts -- the refinance exists, every event executed, Common
    Equity and its totals are reported, every position settled, the analysis is
    the saved state's, every series spans the analysis's periods -- never by a
    Python recomputation of Common Equity, proceeds, payoffs, fees or returns.
    INV-5 is reconciled by the workbook's own formulas on its Checks sheet."""

    tree = _code(_current("src/anchor/exports/refinance/source.py"))
    assert _arithmetic(tree) == []
    assert _numeric_calls(tree) == []


def test_the_audit_source_refuses_by_type_never_by_assertion_or_catch_all() -> None:
    """A missing fact is a typed ``analysis_inconsistent`` refusal, never an
    ``assert`` (which ``python -O`` removes), and no broad ``except`` may turn
    a configured Partnership that cannot run into a silently missing sheet."""

    tree = _code(_current("src/anchor/exports/refinance/source.py"))
    assert [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Assert)] == []
    broad = [
        ast.unparse(handler.type) if handler.type is not None else "bare"
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler)
        and (handler.type is None or ast.unparse(handler.type) in {"Exception", "BaseException"})
    ]
    assert broad == []


def test_the_audit_source_guard_has_teeth() -> None:
    """The removed recomputation would be caught, by operator and by call."""

    recomputation = _code(
        "def reconciles(pre, providers, third, common):\n"
        "    return abs(pre - providers - third - common) <= 1e-6\n"
    )
    assert _arithmetic(recomputation) == ["pre - providers", "pre - providers - third", "pre - providers - third - common"]
    assert _numeric_calls(recomputation) == ["abs(pre - providers - third - common)"]
    assert _numeric_calls(_code("total = sum(flows)\n")) == ["sum(flows)"]


def test_the_audit_workbook_arithmetic_is_layout_only() -> None:
    tree = _code(_current("src/anchor/exports/refinance/audit.py"))
    for node in _arithmetic_nodes(tree):
        names = {
            child.id if isinstance(child, ast.Name) else child.attr
            for child in ast.walk(node)
            if isinstance(child, (ast.Name, ast.Attribute))
        }
        names -= {"replacement", "lender_fees", "retiring_fee_lines", "third_party_costs", "closing_fees", "value"}
        constants_only = not names
        assert constants_only or names <= _LAYOUT_NAMES, (ast.unparse(node), sorted(names - _LAYOUT_NAMES))


# =============================================================================
# 4. The gate is gone through one seam
# =============================================================================


def _production_text() -> dict[str, str]:
    paths = [
        path
        for path in _git("ls-files", "src", "web/src").split()
        + _git("ls-files", "--others", "--exclude-standard", "src", "web/src").split()
        if path.endswith((".py", ".ts", ".tsx")) and _is_production(path)
    ]
    return {path: _current(path) for path in paths}


def test_the_report_gate_token_is_spelled_nowhere_in_code() -> None:
    for path, source in _production_text().items():
        code = ast.unparse(_code(source)) if path.endswith(".py") else source
        assert "refinance_reporting_not_available" not in code, path
        assert "ReportPreviewRefusedError" not in code, path


def test_the_one_refinance_refusal_is_fed_by_one_function() -> None:
    publication = _code(_current("src/anchor/memo/publication.py"))
    dependencies = _current("src/anchor/deals/memo_dependencies.py")

    assert "REFINANCE_RESULT_UNAVAILABLE" in ast.unparse(publication)
    calls = [
        node
        for node in ast.walk(_code(dependencies))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "unexecuted_refinances"
    ]
    assert len(calls) == 1
    for path, source in _production_text().items():
        if path not in {"src/anchor/deals/memo_dependencies.py", "src/anchor/memo/publication.py"}:
            assert "unexecuted_refinances" not in source, path


def test_the_preview_route_no_longer_refuses_a_refinance() -> None:
    api = _current("src/anchor/api.py")
    start = api.index("def read_memo_report_preview")
    body = api[start : api.index("\n@app.", start)]

    assert "refinance" not in re.sub(r'"""[\s\S]*?"""', "", body).lower()


# =============================================================================
# 5. One importer
# =============================================================================


def test_only_the_api_imports_the_refinance_audit() -> None:
    importers = {
        path
        for path, source in _production_text().items()
        if path.endswith(".py")
        and not path.startswith("src/anchor/exports/refinance/")
        and any("exports.refinance" in name for name in _imports(_code(source)))
    }
    assert importers == {"src/anchor/api.py"}


def test_the_refinance_audit_imports_no_writer_of_state() -> None:
    for path in ("src/anchor/exports/refinance/audit.py", "src/anchor/exports/refinance/source.py"):
        source = _current(path)
        for writer in ("put_", "set_deal_", "create_", "update_", "delete_", "publish("):
            assert not re.search(rf"\bstore\.{re.escape(writer)}", source), (path, writer)
