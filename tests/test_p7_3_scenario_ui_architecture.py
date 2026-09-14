"""Phase 7 Gate P7.3 -- Scenario UI + Scenario Comparison v0: the backend
half, and the P7.3 production ledger.

P7.3 is a frontend gate (Tier 3). Its one backend change is a read-only route,
``GET /scenario-targets``, which projects the P7.1 registry so the Scenario
editor never holds a target list of its own. This file proves:

1. the ledger: P7.3 changed exactly its authorized production files, and no
   financial, persistence, Scenario or AI module;
2. ``api.py`` changed only by the catalog -- one imported name, one response
   class and one route, and nothing else;
3. the catalog is the registry, projected: every mode, every target, each
   whitelist in declaration order, the units verbatim, and it is derived at
   request time rather than copied;
4. it is read-only: it computes nothing, calls no store function and creates
   no row;
5. the web presentation map covers exactly the registry's tokens, and each
   value kind agrees with the unit the registry states.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient

from anchor import api as api_module
from anchor.analysis.scenario import (
    SCENARIO_TARGET_REGISTRY,
    ScenarioOperation,
    ScenarioTarget,
)
from anchor.contracts import OperatingMode

from _p7_2_fixtures import EMPTY, create_deal, row_counts  # type: ignore[import-not-found]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: ``main`` when P7.3 began: the no-ff P7.2 merge.
_P7_3_BASE = "c6ddde074cbd7fd4f3f4cf10e29d4f44eed6cf83"

#: Every production file P7.3 changes, exactly:
#: - ``api.py``: the read-only ``GET /scenario-targets`` catalog;
#: - ``web/src/api.ts``: the typed Scenario client (additions only);
#: - ``App.tsx``: Risk's Scenarios view, wired per mode;
#: - ``index.css``: the Scenario styles and the Deal Context strip rename;
#: - the new Scenario modules (contracts, presentation, comparison, the hook and
#:   three components);
#: - the ``StrategyStrip`` -> ``DealContextStrip`` rename (removed, added, and
#:   its two importers);
#: - ``LeaseLevelSensitivityWorkspace.tsx``: its nested navigation takes the
#:   inline style under Risk's new Scenarios / Sensitivity navigation.
_P7_3_PRODUCTION_FILES = frozenset(
    {
        "src/anchor/api.py",
        "web/src/api.ts",
        "web/src/App.tsx",
        "web/src/index.css",
        "web/src/scenarioTypes.ts",
        "web/src/scenarioCatalog.ts",
        "web/src/scenarioComparison.ts",
        "web/src/useScenarios.ts",
        "web/src/components/ScenarioWorkspace.tsx",
        "web/src/components/ScenarioEditor.tsx",
        "web/src/components/ScenarioComparisonMatrix.tsx",
        "web/src/components/DealContextStrip.tsx",
        "web/src/components/StrategyStrip.tsx",
        "web/src/components/UnderwriteWorkspace.tsx",
        "web/src/components/LeaseLevelWorkspace.tsx",
        "web/src/components/LeaseLevelSensitivityWorkspace.tsx",
    }
)

#: Financial truth, Scenario semantics, persistence, fingerprints and AI:
#: P7.3 consumes them and changes none.
_PROTECTED = (
    "src/anchor/engine",
    "src/anchor/leasing",
    "src/anchor/analysis",
    "src/anchor/business_plan",
    "src/anchor/ai",
    "src/anchor/ingestion",
    "src/anchor/deals",
    "src/anchor/contracts.py",
    "src/anchor/validation.py",
)

_API = "src/anchor/api.py"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _changes_since(base: str, *paths: str) -> set[str]:
    """Committed, staged, unstaged and untracked changes since ``base``. Reads
    Git only; it never touches the index (protocol 11.2)."""

    tracked = _git("diff", "--name-only", base, "--", *paths).split()
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    return {path for path in (*tracked, *untracked) if path}


def _ledger_violations(changed: set[str]) -> tuple[list[str], list[str]]:
    return sorted(changed - _P7_3_PRODUCTION_FILES), sorted(_P7_3_PRODUCTION_FILES - changed)


# =============================================================================
# 1. The P7.3 production ledger
# =============================================================================


def test_p7_3_changed_exactly_its_authorized_production_files() -> None:
    """The P7.3 production ledger. The next gate must re-pin this to P7.3's
    committed range, ``c6ddde0..<the P7.3 merge>``, before adding its own
    scope. Never widen this set to admit another gate's files."""

    changed = {path for path in _changes_since(_P7_3_BASE, "src", "web") if _is_production(path)}
    assert _ledger_violations(changed) == ([], [])


def test_the_p7_3_ledger_base_is_the_p7_2_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _P7_3_BASE).split()[1:]
    assert parents == [_git("rev-parse", ref).strip() for ref in ("58f862d", "8e589c8")]


@pytest.mark.parametrize("path", _PROTECTED)
def test_a_protected_path_is_unchanged_since_p7_2(path: str) -> None:
    assert _changes_since(_P7_3_BASE, path) == set(), f"{path} changed at P7.3"


def test_the_ledger_rejects_any_unexpected_production_change() -> None:
    assert _ledger_violations(set(_P7_3_PRODUCTION_FILES)) == ([], [])
    for intruder in (
        "src/anchor/engine/returns.py",
        "src/anchor/analysis/scenario.py",
        "src/anchor/deals/store.py",
        "src/anchor/deals/variants.py",
        "src/anchor/ai/prompts.py",
        "web/src/capitalEconomics.ts",
    ):
        assert _ledger_violations({*_P7_3_PRODUCTION_FILES, intruder}) == ([intruder], [])
    assert not _is_production("web/src/scenarioWorkspace.test.tsx")
    assert not _is_production("tests/test_p7_3_scenario_ui_architecture.py")


# =============================================================================
# 2. api.py changed by the catalog alone
# =============================================================================


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _module(text: str) -> ast.Module:
    return ast.parse(_lf(text))


def _current_api() -> ast.Module:
    return _module((_PROJECT_ROOT / _API).read_text(encoding="utf-8"))


def _baseline_api() -> ast.Module:
    return _module(_git("show", f"{_P7_3_BASE}:{_API}"))


def _scenario_import(tree: ast.Module) -> ast.ImportFrom:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "analysis.scenario":
            return node
    raise AssertionError("api.py does not import the Scenario layer")


def test_api_py_changed_only_by_the_catalog() -> None:
    baseline = {ast.dump(node) for node in _baseline_api().body}
    current = {ast.dump(node) for node in _current_api().body}
    added = [node for node in _current_api().body if ast.dump(node) not in baseline]
    removed = [node for node in _baseline_api().body if ast.dump(node) not in current]

    assert [type(node).__name__ for node in removed] == ["ImportFrom"]
    assert [
        (type(node).__name__, getattr(node, "name", None)) for node in added
    ] == [
        ("ImportFrom", None),
        ("ClassDef", "_ScenarioTargetEntry"),
        ("FunctionDef", "scenario_target_catalog"),
    ]
    old_names = {alias.name for alias in _scenario_import(_baseline_api()).names}
    new_names = {alias.name for alias in _scenario_import(_current_api()).names}
    assert new_names - old_names == {"SCENARIO_TARGET_REGISTRY"}
    assert old_names <= new_names


def _catalog_function() -> ast.FunctionDef:
    for node in _current_api().body:
        if isinstance(node, ast.FunctionDef) and node.name == "scenario_target_catalog":
            return node
    raise AssertionError("no scenario_target_catalog route")


def test_the_catalog_is_one_read_only_get_route() -> None:
    function = _catalog_function()
    decorators = [ast.unparse(decorator) for decorator in function.decorator_list]
    assert decorators == [
        "app.get('/scenario-targets', response_model=dict[str, list[_ScenarioTargetEntry]])"
    ]


def test_the_catalog_computes_nothing_and_touches_no_store() -> None:
    body = ast.Module(body=_catalog_function().body, type_ignores=[])
    arithmetic = [
        ast.unparse(node)
        for node in ast.walk(body)
        if isinstance(node, (ast.BinOp, ast.AugAssign, ast.UnaryOp))
        and not isinstance(getattr(node, "op", None), ast.Not)
    ]
    assert arithmetic == []
    called = {ast.unparse(node.func) for node in ast.walk(body) if isinstance(node, ast.Call)}
    assert called == {"_ScenarioTargetEntry", "tuple", "SCENARIO_TARGET_REGISTRY.values"}
    names = {node.id for node in ast.walk(body) if isinstance(node, ast.Name)}
    assert not {"investment_store", "deals_store", "store"} & names


def test_the_registry_is_named_only_by_the_catalog() -> None:
    text = _lf((_PROJECT_ROOT / _API).read_text(encoding="utf-8"))
    catalog = ast.get_source_segment(text, _catalog_function())
    assert catalog is not None
    outside = text.replace(catalog, "")
    assert re.findall(r"\bSCENARIO_TARGET_REGISTRY\b", outside) == ["SCENARIO_TARGET_REGISTRY"]


# =============================================================================
# 3-4. The catalog is the registry, projected, and read-only
# =============================================================================


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "catalog.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(api_module.app)


def _catalog(client: TestClient) -> dict[str, list[dict[str, object]]]:
    response = client.get("/scenario-targets")
    assert response.status_code == 200, response.text
    return response.json()


def test_every_operating_mode_is_listed(client: TestClient) -> None:
    assert list(_catalog(client)) == [mode.value for mode in OperatingMode]


def test_each_mode_lists_the_registry_targets_in_declaration_order(client: TestClient) -> None:
    catalog = _catalog(client)
    assert [entry["target"] for entry in catalog["quick"]] == [
        "exit_cap_rate", "interest_rate", "ltv", "noi_growth",
    ]
    assert [entry["target"] for entry in catalog["detailed"]] == [
        "exit_cap_rate", "interest_rate", "ltv",
        "revenue_growth", "vacancy_credit_loss_pct", "expense_growth",
    ]
    assert [entry["target"] for entry in catalog["lease_level"]] == [
        "exit_cap_rate", "interest_rate", "ltv",
        "expense_growth", "market_rent_psf", "renewal_probability", "recoverable_expense_ratio",
    ]


def test_each_entry_is_the_registry_spec_verbatim(client: TestClient) -> None:
    catalog = _catalog(client)
    for mode in OperatingMode:
        expected = [
            {
                "target": target.value,
                "allowed_operations": [
                    operation.value
                    for operation in ScenarioOperation
                    if operation in spec.allowed_operations
                ],
                "units": spec.units,
            }
            for target, spec in SCENARIO_TARGET_REGISTRY.items()
            if mode in spec.modes
        ]
        assert catalog[mode.value] == expected, mode


def test_the_whitelists_are_the_ratified_ones(client: TestClient) -> None:
    by_target = {entry["target"]: entry for entry in _catalog(client)["lease_level"]}
    assert by_target["ltv"]["allowed_operations"] == ["cap_at"]
    assert by_target["exit_cap_rate"]["allowed_operations"] == ["set", "add", "scale"]
    assert by_target["market_rent_psf"]["allowed_operations"] == ["set", "add", "scale", "cap_at"]
    assert by_target["expense_growth"]["allowed_operations"] == ["set", "add"]


def test_the_catalog_is_derived_at_request_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copied list would survive a registry change; a projection cannot."""

    narrowed = MappingProxyType(
        {
            target: spec
            for target, spec in SCENARIO_TARGET_REGISTRY.items()
            if target is not ScenarioTarget.NOI_GROWTH
        }
    )
    monkeypatch.setattr(api_module, "SCENARIO_TARGET_REGISTRY", narrowed)
    assert [entry["target"] for entry in _catalog(client)["quick"]] == [
        "exit_cap_rate", "interest_rate", "ltv",
    ]


def test_reading_the_catalog_creates_nothing(client: TestClient, db: Path) -> None:
    create_deal("quick", db)
    _catalog(client)
    _catalog(client)
    assert row_counts(db) == EMPTY


def test_the_catalog_accepts_no_write(client: TestClient) -> None:
    assert client.post("/scenario-targets", json={}).status_code == 405


# =============================================================================
# 5. The web presentation map covers exactly the registry
# =============================================================================

_PRESENTATION_ENTRY = re.compile(r"^\s*(\w+): \{ label: '([^']+)', kind: '(\w+)' \},?$", re.MULTILINE)


def _web_presentation() -> dict[str, tuple[str, str]]:
    text = _lf((_PROJECT_ROOT / "web/src/scenarioCatalog.ts").read_text(encoding="utf-8"))
    start = text.index("export const SCENARIO_TARGET_PRESENTATION")
    block = text[start : text.index("};", start)]
    return {match.group(1): (match.group(2), match.group(3)) for match in _PRESENTATION_ENTRY.finditer(block)}


def test_the_web_labels_cover_exactly_the_registry_targets() -> None:
    assert set(_web_presentation()) == {target.value for target in SCENARIO_TARGET_REGISTRY}


def test_each_web_value_kind_agrees_with_the_registry_units() -> None:
    """The UI types a percentage only where the registry states a decimal
    ratio or rate, and dollars only where it states $/SF. A drift in either
    direction fails here rather than silently mis-scaling a value."""

    presentation = _web_presentation()
    for target, spec in SCENARIO_TARGET_REGISTRY.items():
        kind = presentation[target.value][1]
        if spec.units.startswith("$/SF"):
            assert kind == "rent_psf", target
        else:
            assert "%" in spec.units, target
            assert kind == "percent", target


def test_the_presentation_parser_finds_every_entry() -> None:
    assert len(_web_presentation()) == len(SCENARIO_TARGET_REGISTRY) == 10
