"""Gate AM1 -- the production ledger and architecture guards.

``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`` Sections 1.2 and
10. Every git query reads objects only (protocol 11.2). The guards hold:

1. **the AM1 production ledger**, measured over AM1's own committed range
   ``63c2ac0..366b31b`` (the feature, merged as ``3048976``, and its deletion
   extension, merged as ``60be780``) -- never against the working tree, which
   later accepted work legitimately changes;
2. **no AM1 financial arithmetic in TypeScript** -- every total, variance,
   percentage and assessment is computed in Python;
3. **a Managed Asset is not a Deal**, and no AM1 module imports an acquisition
   engine, a Scenario, a Strategy, a Capital Structure or a Partnership;
4. **monthly reporting cannot mutate acquisition underwriting** -- no AM1 write
   path touches a deal table;
5. **the budget is frozen by construction**, not merely by a check: no SQL in
   the store can move a ``budget_*`` column after the INSERT;
6. **no AM1 module imports or invokes AI**;
7. **no P7.9 engine or Partnership module changed**, and no financial module of
   any earlier gate changed.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when AM1 began: P7.9 Stage 3 merged, schema v12.
_AM1_BASE = "63c2ac0"

#: AM1's committed production history ends at the deletion extension's reviewed
#: head, merged by PR #39 as ``60be780`` (parents ``7ec824c`` and ``366b31b``);
#: the feature itself merged by PR #38 as ``3048976`` (parents ``63c2ac0`` and
#: ``1e7fe3d``). Re-pinned at the P7.9 closeout: measured against the working
#: tree, the ledger read any later accepted frontend change as an AM1 change.
_AM1_HEAD = "366b31bc615bc00deb152505b3f4e2137c262ecb"
_AM1_FEATURE_MERGE = "3048976d66d9804f262bce65bd0ae348299560f0"
_AM1_FEATURE_HEAD = "1e7fe3ddc084c889a289200e1b7d7ee99ee38672"
_AM1_DELETION_MERGE = "60be780c3bfb0b37311f04710f97069b2f13a7b1"

#: A committed range that is genuinely not AM1: P7.9 Stage 3's reviewed branch
#: (PR #36, merged as ``3f23ba4``). The ledger must reject it.
_STAGE_3_BASE = "825a60a84185b978a001ed4f8c648f40ef6d7491"
_STAGE_3_HEAD = "ce70d79bdf5f1503f4b4a09faa98c1b102f3dd1d"

_PACKAGE = "src/anchor/asset_management"
_STORE = "src/anchor/deals/store.py"
_API = "src/anchor/api.py"

#: Every backend production file AM1 changes, exactly (Section 1.2):
#: - ``asset_management/`` (new): the contracts, validation and the engine;
#: - ``deals/store.py``: schema v13, the two tables and the lifecycle;
#: - ``api.py``: the routes.
_AM1_BACKEND_FILES = frozenset(
    {
        f"{_PACKAGE}/__init__.py",
        f"{_PACKAGE}/contracts.py",
        f"{_PACKAGE}/performance.py",
        f"{_PACKAGE}/validation.py",
        _STORE,
        _API,
    }
)

#: Every frontend production file AM1 changes, exactly.
_AM1_FRONTEND_FILES = frozenset(
    {
        "web/src/assetManagementTypes.ts",
        "web/src/assetManagementFormat.ts",
        "web/src/assetManagementFixture.ts",
        "web/src/useManagedAssets.ts",
        "web/src/api.ts",
        "web/src/App.tsx",
        "web/src/index.css",
        "web/src/components/AppSidebar.tsx",
        "web/src/components/AssetManagementShell.tsx",
        "web/src/components/ManagedAssetWorkspace.tsx",
        "web/src/components/MonthlyPerformancePanel.tsx",
        "web/src/components/MonthlyReportEditor.tsx",
        "web/src/components/NoiTrendChart.tsx",
        "web/src/components/CreateManagedAssetPanel.tsx",
    }
)

#: Consumed and never changed: every financial module of every earlier gate,
#: and in particular the whole P7.9 Partnership package and engine.
_UNCHANGED = (
    "src/anchor/engine",
    "src/anchor/partnership",
    "src/anchor/capital_structure",
    "src/anchor/consolidation",
    "src/anchor/investment",
    "src/anchor/business_plan",
    "src/anchor/leasing",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/analysis",
    "src/anchor/decision",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
    "src/anchor/formatting.py",
    "src/anchor/report.py",
    "src/anchor/deals/contracts.py",
    "src/anchor/deals/fingerprint.py",
    "src/anchor/deals/variants.py",
    "src/anchor/deals/investment_variants.py",
    "src/anchor/deals/structured_variants.py",
    "src/anchor/deals/partnership_variants.py",
    "src/anchor/deals/partnership_codec.py",
    "src/anchor/deals/capital_structure_codec.py",
    "src/anchor/deals/position_identity.py",
    "src/anchor/deals/decision_matrix.py",
    "src/anchor/deals/__init__.py",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


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


def _am1_package_sources() -> dict[str, str]:
    return {
        name: _current(f"{_PACKAGE}/{name}")
        for name in ("__init__.py", "contracts.py", "performance.py", "validation.py")
    }


# =============================================================================
# 1. The production ledger
# =============================================================================


def _changes_between(base: str, head: str, *paths: str) -> set[str]:
    """The paths a committed range changed. Objects only: no working tree, no
    index (protocol 11.2)."""
    return {
        path
        for path in _git("diff", "--name-only", "--no-renames", base, head, "--", *paths).split()
        if path
    }


def test_am1_changes_exactly_the_declared_backend_files() -> None:
    changed = {path for path in _changes_between(_AM1_BASE, _AM1_HEAD, "src") if _is_production(path)}
    assert changed == _AM1_BACKEND_FILES


def test_am1_changes_exactly_the_declared_frontend_files() -> None:
    changed = {
        path for path in _changes_between(_AM1_BASE, _AM1_HEAD, "web/src") if _is_production(path)
    }
    assert changed == _AM1_FRONTEND_FILES


def _parents(commit: str) -> list[str]:
    return _git("rev-list", "--parents", "-n", "1", commit).split()[1:]


def test_the_ledger_range_is_exactly_am1s_merged_history() -> None:
    assert _parents(_AM1_FEATURE_MERGE) == [_git("rev-parse", _AM1_BASE).strip(), _AM1_FEATURE_HEAD]
    assert _parents(_AM1_DELETION_MERGE)[1] == _AM1_HEAD
    # The deletion extension descends from the feature merge, so the range is
    # one continuous AM1 history, and it is the history this repository holds.
    for ancestor, descendant in ((_AM1_FEATURE_MERGE, _AM1_HEAD), (_AM1_DELETION_MERGE, "HEAD")):
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant], check=True, cwd=_PROJECT_ROOT
        )
    # Nothing between the range's end and the deletion merge touched production.
    assert _changes_between(_AM1_HEAD, _AM1_DELETION_MERGE, "src", "web") == set()


def test_the_ledger_rejects_a_production_file_am1_did_not_declare() -> None:
    declared = _AM1_BACKEND_FILES | _AM1_FRONTEND_FILES
    stage_3 = {
        path for path in _changes_between(_STAGE_3_BASE, _STAGE_3_HEAD, "src", "web/src") if _is_production(path)
    }
    assert "web/src/components/PartnershipResults.tsx" in stage_3 - declared


@pytest.mark.parametrize("path", _UNCHANGED)
def test_no_earlier_financial_module_changed(path: str) -> None:
    """Including every P7.9 Partnership module and the Stage 1 engine.

    Measured over AM1's own committed range, like the ledger above. Against the
    working tree it read a later gate's legitimate change -- Asset Types 1 adds
    two metadata fields to ``deals/contracts.py`` -- as an AM1 change."""

    assert _changes_between(_AM1_BASE, _AM1_HEAD, path) == set()


# =============================================================================
# 2. No AM1 financial arithmetic in TypeScript
# =============================================================================

#: The TypeScript files that carry AM1 product logic. `index.css` and the
#: fixture are excluded: one is style, the other is a recorded engine response.
_AM1_TS_LOGIC = (
    "web/src/assetManagementTypes.ts",
    "web/src/useManagedAssets.ts",
    "web/src/components/AssetManagementShell.tsx",
    "web/src/components/ManagedAssetWorkspace.tsx",
    "web/src/components/MonthlyPerformancePanel.tsx",
    "web/src/components/MonthlyReportEditor.tsx",
)

#: Every figure AM1 reports. None of these names may be produced by an
#: arithmetic expression in TypeScript -- each must arrive from the engine.
_COMPUTED_NAMES = (
    "total_revenue",
    "total_operating_expenses",
    "net_operating_income",
    "cash_flow_after_capex",
    "net_cash_flow",
    "noi_margin",
    "variance_pct",
)


@pytest.mark.parametrize("path", _AM1_TS_LOGIC)
def test_no_am1_financial_arithmetic_in_typescript(path: str) -> None:
    """No TypeScript file that carries AM1 product logic may add, subtract,
    multiply or divide two financial figures.

    Scanned line by line for an arithmetic operator applied to a figure this
    contract names. The engine is the sole authority; a second implementation
    here is precisely the drift this guard exists to prevent.
    """

    source = _current(path)
    for number, line in enumerate(source.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith(("*", "//", "/*")):
            continue
        for name in _COMPUTED_NAMES:
            if name not in line:
                continue
            # A read (`period.actual.net_operating_income`), a type declaration
            # or an object key is fine. An arithmetic operator on the same line
            # as one of these names is not.
            assert not re.search(
                rf"{name}\s*[-+*/]\s*\w|\w\s*[-+*/]\s*[\w.]*{name}", line
            ), f"{path}:{number} computes {name}: {stripped}"


def test_the_frontend_never_recomputes_a_variance_or_an_assessment() -> None:
    """Favorability is declared once, in Python, and carried on every line as
    ``direction``/``assessment``. The frontend must never decide it from a
    line's name or from the sign of a figure.

    Two things would signal that it had started to: a helper that classifies a
    line, and a literal set of expense line names used as a lookup. Neither may
    appear in a file that carries AM1 product logic.
    """

    for path in _AM1_TS_LOGIC:
        source = _current(path)
        assert not re.search(
            r"\b(isExpense|isFavorable|favorabilityOf|assessmentFor|directionOf)\s*\(", source
        ), path
        # A list of line names is fine -- the editor needs one, in statement
        # order. What is forbidden is pairing a line name with a favorability
        # verdict, which is the frontend deciding what the engine already
        # decided. So: no expense line name may appear near one of the
        # favorability tokens.
        for match in re.finditer(
            r"'(property_taxes|insurance|utilities|repairs_and_maintenance|payroll"
            r"|management_fees|other_operating_expenses)'",
            source,
        ):
            window = source[max(0, match.start() - 160) : match.end() + 160]
            assert not re.search(
                r"'(favorable|unfavorable|lower_is_favorable|higher_is_favorable)'", window
            ), f"{path} pairs {match.group(1)} with a favorability verdict"


def test_the_frontend_fixture_is_the_engines_own_output() -> None:
    """Every float in the frontend's demo fixture is a value the engine actually
    produces, spelled exactly as JSON would encode it.

    The fixture claims to be a recorded engine response, and the frontend tests
    assert the screen against it -- so if it drifted, those tests would keep
    passing while agreeing with nothing. It did drift once: a hand-transcribed
    ``variance_pct`` differed from the engine's in its last two digits, which is
    precisely the failure this guard now prevents.
    """

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from anchor.api import _wire
    from anchor.asset_management import analyze_asset_performance

    import _am1_fixtures as am  # type: ignore[import-not-found]

    result = _wire(
        analyze_asset_performance(
            managed_asset_id="asset-1", reporting_month=am.MARCH, reports=[am.report()]
        )
    )

    def floats(node: object, path: str = "") -> list[tuple[str, str]]:
        if isinstance(node, dict):
            return [item for key, value in node.items() for item in floats(value, f"{path}.{key}")]
        if isinstance(node, list):
            return [item for i, value in enumerate(node) for item in floats(value, f"{path}[{i}]")]
        if isinstance(node, float):
            return [(path, repr(node))]
        return []

    fixture = _current("web/src/assetManagementFixture.ts")
    # Only the long values are checked: a short one like `0.95` appears for many
    # unrelated reasons and proves nothing.
    drifted = [
        (path, value) for path, value in floats(result) if len(value) > 8 and value not in fixture
    ]
    assert drifted == []


def test_the_formatter_only_formats() -> None:
    """`assetManagementFormat.ts` converts scales and picks labels. It must not
    combine two figures."""

    source = _current("web/src/assetManagementFormat.ts")
    assert not re.search(r"\w+\s*[-+]\s*\w+\.(budget|actual|variance)", source)
    assert "variance_pct" not in source.replace("line.variance_pct", "").replace(
        "value: number | null", ""
    ) or "formatVariancePct" in source


# =============================================================================
# 3. A Managed Asset is not a Deal
# =============================================================================


def test_the_am1_package_imports_no_acquisition_or_downstream_module() -> None:
    """The engine, the Scenario/Strategy layers, the Capital Structure and the
    Partnership are all unreachable from Asset Management: a Managed Asset is
    a different thing from the Deal it came from, and monthly reporting is
    downstream of an acquisition rather than part of one."""

    forbidden = (
        "engine",
        "analysis",
        "leasing",
        "business_plan",
        "capital_structure",
        "partnership",
        "investment",
        "consolidation",
        "decision",
        "deals",
        "ingestion",
        "ai",
    )
    for name, source in _am1_package_sources().items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.lstrip(".").split(".")[0]
                assert root not in forbidden, f"{name} imports {module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("anchor."), f"{name} imports {alias.name}"


def test_the_am1_package_declares_no_deal_contract() -> None:
    """No AM1 contract carries an acquisition assumption. `source_deal_id` and
    the fingerprint are provenance strings, and that is deliberately all."""

    contracts = _am1_package_sources()["contracts.py"]
    for absent in (
        "purchase_price",
        "exit_cap_rate",
        "hold_period",
        "AcquisitionInputs",
        "AcquisitionTerms",
        "OperatingMode",
    ):
        assert absent not in contracts, absent


def test_the_managed_asset_has_its_own_identity() -> None:
    """Its own id, not the Deal's."""

    tree = _tree(f"{_PACKAGE}/contracts.py")
    asset = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "ManagedAsset"
    )
    fields = [
        node.target.id
        for node in asset.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    assert fields[0] == "id"
    assert "source_deal_id" in fields
    assert "acquisition_fingerprint" in fields


# =============================================================================
# 4. Monthly reporting cannot mutate acquisition underwriting
# =============================================================================

#: Every AM1 write path in the store.
_AM1_WRITE_FUNCTIONS = (
    "create_managed_asset",
    "delete_managed_asset",
    "create_monthly_report",
    "update_monthly_report_actuals",
    "update_monthly_report_commentary",
)

#: The tables an acquisition lives in. No AM1 write path may name one in an
#: UPDATE, INSERT or DELETE.
_DEAL_TABLES = ("deals", "detailed_deals", "detailed_operating_inputs", "lease_level_deals")


def _function(path: str, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _sql_strings(node: ast.AST) -> list[str]:
    return [
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


@pytest.mark.parametrize("name", _AM1_WRITE_FUNCTIONS)
def test_no_am1_write_path_mutates_a_deal_table(name: str) -> None:
    for sql in _sql_strings(_function(_STORE, name)):
        upper = sql.upper()
        if not any(verb in upper for verb in ("INSERT", "UPDATE", "DELETE")):
            continue
        for table in _DEAL_TABLES:
            assert not re.search(
                rf"\b(INTO|UPDATE|FROM)\s+{table}\b", sql, flags=re.IGNORECASE
            ), f"{name} writes {table}: {sql}"


def test_creating_an_asset_only_reads_the_deal() -> None:
    """It captures the Deal's fingerprint and writes the asset row, into
    ``managed_assets`` -- and, since Asset Types 1, the snapshot of the Deal's
    classification into ``managed_asset_classifications``. Both are inserts
    into asset-owned tables; nothing is updated or deleted."""

    writes = [
        sql
        for sql in _sql_strings(_function(_STORE, "create_managed_asset"))
        if any(verb in sql.upper() for verb in ("INSERT", "UPDATE", "DELETE"))
    ]
    assert len(writes) == 2
    assert "INSERT INTO managed_assets" in writes[0]
    assert writes[1].startswith("INSERT INTO managed_asset_classifications")


def test_deleting_an_asset_explicitly_removes_reports_then_the_asset() -> None:
    delete = _function(_STORE, "delete_managed_asset")
    deletes = [sql for sql in _sql_strings(delete) if "DELETE FROM" in sql.upper()]
    assert deletes == [
        "DELETE FROM monthly_asset_reports WHERE managed_asset_id = ?",
        # Asset Types 1: the asset's own classification snapshot.
        "DELETE FROM managed_asset_classifications WHERE managed_asset_id = ?",
        "DELETE FROM managed_assets WHERE id = ?",
    ]


# =============================================================================
# 5. The budget is frozen by construction
# =============================================================================


def test_only_the_create_path_writes_a_budget_column() -> None:
    """Not merely refused at the contract boundary: there is no SQL in the
    store capable of moving a ``budget_*`` column after the INSERT."""

    source = _current(_STORE)
    update = _function(_STORE, "update_monthly_report_actuals")
    for sql in _sql_strings(update):
        assert "budget_" not in sql, sql
    # The only statement that names budget columns builds them from the shared
    # field list, in the create path.
    assert source.count('_figure_values(budget, "budget")') == 1
    assert 'UPDATE monthly_asset_reports' in source


def test_the_update_path_sets_only_actuals_commentary_and_timestamp() -> None:
    update = _function(_STORE, "update_monthly_report_actuals")
    source = ast.unparse(update)
    assert '_figure_values(actual, \'actual\')' in source
    assert '_figure_values(budget' not in source


def test_a_budget_change_raises_the_typed_conflict_not_a_validation_error() -> None:
    update = _function(_STORE, "update_monthly_report_actuals")
    raised = {
        node.exc.func.id
        for node in ast.walk(update)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
    }
    assert "BudgetImmutableError" in raised
    assert "AssetReportValidationError" not in raised


def test_budget_immutable_error_is_not_a_value_error() -> None:
    """A caller that catches every validation failure must not silently swallow
    an authority refusal."""

    tree = _tree(f"{_PACKAGE}/contracts.py")
    error = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "BudgetImmutableError"
    )
    bases = {base.id for base in error.bases if isinstance(base, ast.Name)}
    assert bases == {"Exception"}


# =============================================================================
# 6. Zero-budget percentages, expense direction and neutral lines
# =============================================================================


def test_zero_budget_and_zero_revenue_return_none_not_zero() -> None:
    source = _am1_package_sources()["performance.py"]
    margin = _function(f"{_PACKAGE}/performance.py", "noi_margin")
    pct = _function(f"{_PACKAGE}/performance.py", "variance_pct")
    for node in (margin, pct):
        returns = [
            item
            for item in ast.walk(node)
            if isinstance(item, ast.Return)
            and isinstance(item.value, ast.Constant)
            and item.value.value is None
        ]
        assert returns, ast.unparse(node)
    assert "return 0.0" not in source


def test_every_expense_line_is_lower_is_favorable_and_capex_is_neutral() -> None:
    """Read from the declaration itself, so a future edit that flipped one
    direction fails here even if no test exercised that line."""

    from anchor.asset_management.contracts import OPERATING_EXPENSE_FIELDS, FinancialLine
    from anchor.asset_management.performance import _LINE_DIRECTION
    from anchor.asset_management.contracts import VarianceDirection

    for field in OPERATING_EXPENSE_FIELDS:
        assert _LINE_DIRECTION[FinancialLine(field)] is VarianceDirection.LOWER_IS_FAVORABLE
    assert (
        _LINE_DIRECTION[FinancialLine.TOTAL_OPERATING_EXPENSES]
        is VarianceDirection.LOWER_IS_FAVORABLE
    )
    for neutral in (
        FinancialLine.CAPITAL_EXPENDITURES,
        FinancialLine.DEBT_SERVICE,
        FinancialLine.CASH_FLOW_AFTER_CAPEX,
    ):
        assert _LINE_DIRECTION[neutral] is VarianceDirection.NO_DIRECTION
    for favorable in (
        FinancialLine.OCCUPANCY,
        FinancialLine.TOTAL_REVENUE,
        FinancialLine.NET_OPERATING_INCOME,
        FinancialLine.NET_CASH_FLOW,
    ):
        assert _LINE_DIRECTION[favorable] is VarianceDirection.HIGHER_IS_FAVORABLE


def test_every_reportable_line_declares_a_direction() -> None:
    """A line with no declared direction would fall through to a KeyError at
    report time; this catches it at build time instead."""

    from anchor.asset_management.contracts import FinancialLine
    from anchor.asset_management.performance import _LINE_DIRECTION

    assert set(_LINE_DIRECTION) == set(FinancialLine)


def _code_only(source: str) -> str:
    """``source`` with every docstring and comment removed.

    The guards below are about what the code *does*, and AM1's prose
    deliberately discusses the very things they forbid ("never derived from an
    annual forecast"). Scanning the raw text would make the explanation of a
    rule trip the rule.
    """

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body.pop(0)
                if not node.body:
                    node.body.append(ast.Pass())
    return ast.unparse(ast.fix_missing_locations(tree))


def test_no_monthly_figure_is_derived_from_an_annual_one() -> None:
    """Never divide an annual underwriting result by twelve, and never take an
    annual figure as an input at all.

    Measured over executable code only: the package's prose explains this rule,
    and the explanation must not be what satisfies the check.
    """

    for name, source in _am1_package_sources().items():
        code = _code_only(source)
        assert "/ 12" not in code, name
        assert "/12" not in code, name
        assert "annual" not in code.lower(), name
        assert "12" not in re.findall(r"/\s*(\d+)", code), name


# =============================================================================
# 7. No AI anywhere in AM1
# =============================================================================


def test_no_am1_module_imports_or_invokes_ai() -> None:
    for name, source in _am1_package_sources().items():
        lowered = source.lower()
        for token in ("openai", "anchor.ai", "from ..ai", "llm", "gpt", "prompt"):
            assert token not in lowered, f"{name} mentions {token}"


def test_no_am1_route_reaches_an_ai_module() -> None:
    """The AM1 route section names no AI symbol, and attention items are
    derived from the deterministic result rather than generated."""

    source = _current(_API)
    start = source.index("# Gate AM1 -- Managed Assets and Monthly Performance.")
    section = source[start:]
    for token in ("ai_analysis", "AIAnalysis", "openai", "_ai_"):
        assert token not in section, token
    assert "analyze_asset_performance" in section


def test_the_am1_routes_are_exactly_the_authorized_surface() -> None:
    """Ten routes: one bounded asset DELETE and no report DELETE. The tenth, the
    commentary-only PUT, was added by the second P7.9 / AM1 QA pass so a
    commentary save cannot overwrite actual results; it carries no figures and
    is held to that in ``tests/test_am1_commentary_update.py``."""

    source = _current(_API)
    start = source.index("# Gate AM1 -- Managed Assets and Monthly Performance.")
    section = source[start:]
    routes = set(re.findall(r'@app\.(get|post|put|delete|patch)\(\s*"([^"]+)"', section))
    assert routes == {
        ("post", "/managed-assets"),
        ("get", "/managed-assets"),
        ("get", "/managed-assets/{managed_asset_id}"),
        ("delete", "/managed-assets/{managed_asset_id}"),
        ("get", "/managed-assets/{managed_asset_id}/reports"),
        ("get", "/managed-assets/{managed_asset_id}/reports/{reporting_month}"),
        ("post", "/managed-assets/{managed_asset_id}/reports"),
        ("put", "/managed-assets/{managed_asset_id}/reports/{reporting_month}"),
        ("put", "/managed-assets/{managed_asset_id}/reports/{reporting_month}/commentary"),
        ("get", "/managed-assets/{managed_asset_id}/performance/{reporting_month}"),
    }
    assert {path for verb, path in routes if verb == "delete"} == {
        "/managed-assets/{managed_asset_id}"
    }


def test_the_store_has_no_independent_report_delete_function() -> None:
    source = _current(_STORE)
    assert "def delete_managed_asset" in source
    assert "def delete_monthly_report" not in source


# =============================================================================
# 8. The migration is additive
# =============================================================================


def test_the_schema_is_v13_and_the_migration_adds_no_alter() -> None:
    # AM1 introduced schema 13; Asset Types 1 later moved the store to 14 with
    # two more additive tables. The pin is AM1's own, so it is read at AM1's
    # committed head; the no-ALTER rule below still holds for today's source.
    assert "_SCHEMA_VERSION = 13" in _git("show", f"{_AM1_HEAD}:{_STORE}")
    source = _current(_STORE)
    assert "_SCHEMA_VERSION = 14" in source

    migrate = _function(_STORE, "_migrate")
    for sql in _sql_strings(migrate):
        if "ALTER TABLE" in sql.upper():
            # The only ALTERs are the pre-existing pre-V2 column additions; none
            # may name an AM1 table.
            assert "managed_assets" not in sql and "monthly_asset_reports" not in sql


def test_the_two_tables_are_created_idempotently_by_connect() -> None:
    source = _current(_STORE)
    for table in ("managed_assets", "monthly_asset_reports"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source
    assert "_CREATE_MANAGED_ASSETS_TABLE_SQL" in source
    assert "_CREATE_MONTHLY_ASSET_REPORTS_TABLE_SQL" in source
    connect = _function(_STORE, "_connect")
    executed = ast.unparse(connect)
    assert "_CREATE_MANAGED_ASSETS_TABLE_SQL" in executed
    assert "_CREATE_MONTHLY_ASSET_REPORTS_TABLE_SQL" in executed


def test_nothing_computed_has_a_column() -> None:
    source = _current(_STORE)
    start = source.index("_CREATE_MONTHLY_ASSET_REPORTS_TABLE_SQL")
    ddl = source[start : source.index('"""', source.index('f"""', start) + 4)]
    for computed in (
        "total_revenue",
        "net_operating_income",
        "noi_margin",
        "variance",
        "assessment",
    ):
        assert computed not in ddl, computed
