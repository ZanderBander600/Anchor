"""Architecture guardrails for the Persistence Phase A ``anchor.deals``
layer.

Confirms ``sqlite3`` is imported in exactly one file (``store.py``), that
the frozen ``engine`` and ``analysis`` packages never import ``anchor.deals``,
that ``anchor.deals`` never imports ``anchor.engine`` (persistence cannot
become a second calculation authority even by accident), and that
``anchor.api`` validates a deal's inputs with the exact same
``validate_acquisition_inputs`` used by ``/analyze`` before ever storing
them.

Mirrors the style of ``test_ai_architecture.py``.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from anchor import api as api_module
from anchor.contracts import AcquisitionInputs
from anchor.deals.store import create_deal, get_deal
from anchor.validation import validate_acquisition_inputs

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENGINE_DIR = _PROJECT_ROOT / "src" / "anchor" / "engine"
_ANALYSIS_DIR = _PROJECT_ROOT / "src" / "anchor" / "analysis"
_DEALS_DIR = _PROJECT_ROOT / "src" / "anchor" / "deals"

GOLDEN_PAYLOAD: dict[str, object] = {
    "purchase_price": 50_000_000,
    "current_noi": 2_500_000,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.055,
    "ltv": 0.65,
    "interest_rate": 0.0525,
    "amortization": 30,
}


def _imported_module_names(source_file: Path) -> list[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def test_sqlite3_is_imported_only_inside_the_store_module() -> None:
    for source_file in _DEALS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        has_sqlite_import = any(name.startswith("sqlite3") for name in names)
        if source_file.name == "store.py":
            continue
        assert not has_sqlite_import, f"{source_file} must not import sqlite3 directly"


def test_engine_package_has_no_deals_import() -> None:
    for source_file in _ENGINE_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(name.startswith("anchor.deals") for name in names), (
            f"{source_file} must not import anchor.deals"
        )


def test_analysis_package_has_no_deals_import() -> None:
    for source_file in _ANALYSIS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(name.startswith("anchor.deals") for name in names), (
            f"{source_file} must not import anchor.deals"
        )


def test_deals_package_has_no_engine_import() -> None:
    """Persistence must never become an alternative calculation authority --
    enforced at the import-graph level, not just by convention."""

    for source_file in _DEALS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(
            name.startswith("anchor.engine") or name.startswith("..engine") or name == "engine"
            for name in names
        ), f"{source_file} must not import anchor.engine"


def test_deals_package_reproduces_no_financial_formula() -> None:
    """No ``deals/`` module imports ``math`` -- every numeric value this
    layer handles is an already-validated ``AcquisitionInputs`` field it
    stores and returns unchanged, never derives."""

    for source_file in _DEALS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert "math" not in names, f"{source_file} must not import math"


def test_engine_import_does_not_pull_in_sqlite3() -> None:
    environment = os.environ.copy()
    python_path_parts = [str(_PROJECT_ROOT / "src")]
    if existing_python_path := environment.get("PYTHONPATH"):
        python_path_parts.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import anchor.engine; assert 'anchor.deals' not in sys.modules",
        ],
        cwd=_PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


# =============================================================================
# The API layer validates before it ever persists (delegation, not a
# second, looser gate for stored data).
# =============================================================================


def test_create_deal_route_delegates_validation_to_the_authoritative_function(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "anchor.api.validate_acquisition_inputs", wraps=validate_acquisition_inputs
        ) as mock_validate,
        patch.dict(os.environ, {"ANCHOR_DB_PATH": str(tmp_path / "test.db")}),
    ):
        client = TestClient(api_module.app)
        response = client.post(
            "/deals", json={"name": "Test Deal", "inputs": GOLDEN_PAYLOAD}
        )

    assert response.status_code == 200
    mock_validate.assert_called_once_with(GOLDEN_PAYLOAD)


def test_stored_deal_inputs_are_the_same_type_analyze_uses() -> None:
    """A round-trip proof at the type level: what ``create_deal``/
    ``get_deal`` hand back is a real ``AcquisitionInputs`` instance -- the
    exact type ``/analyze`` accepts, not a dict or a parallel shape."""

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        inputs = validate_acquisition_inputs(GOLDEN_PAYLOAD)
        created = create_deal("Test Deal", inputs, db_path=db_path)
        fetched = get_deal(created.id, db_path=db_path)

    assert isinstance(fetched.inputs, AcquisitionInputs)
    assert fetched.inputs == inputs
