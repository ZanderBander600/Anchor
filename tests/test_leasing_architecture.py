"""Architecture guardrails for the Lease-Level ``anchor.leasing`` layer.

Guardrail **G-1** of
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Section 30: Lease-Level must not leak into any other layer, and must not reach
into the downstream financial engine. The connection into
acquisition/debt/returns is made at D4, from ``anchor.engine`` toward
``anchor.leasing``, never the reverse.

Also enforces the D1-wide isolation criterion (D0 Section 28.3): D1 modifies no
pre-existing production file, and in particular does not begin a global
validation refactor (guardrail for HD-6).

Mirrors the style of ``test_ai_architecture.py`` and
``test_deals_architecture.py``: AST-parsed import graphs rather than runtime
imports (a runtime import can succeed even when a forbidden dependency exists
but is unused on that path), plus a fresh-subprocess check.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
_LEASING_DIR = _SRC_DIR / "anchor" / "leasing"
_ENGINE_DIR = _SRC_DIR / "anchor" / "engine"
_ANALYSIS_DIR = _SRC_DIR / "anchor" / "analysis"
_DEALS_DIR = _SRC_DIR / "anchor" / "deals"
_AI_DIR = _SRC_DIR / "anchor" / "ai"
_INGESTION_DIR = _SRC_DIR / "anchor" / "ingestion"

#: The exact forbidden import set from D0 Section 3.5 / Gate D1.4.
_FORBIDDEN_LEASING_IMPORTS = (
    "anchor.engine.acquisition",
    "anchor.engine.debt",
    "anchor.engine.noi",
    "anchor.engine.returns",
    "anchor.engine.operating_projection",
    "anchor.ai",
    "anchor.deals",
    "anchor.ingestion",
    "anchor.analysis",
)


def _leasing_source_files() -> list[Path]:
    files = sorted(_LEASING_DIR.glob("*.py"))
    assert files, "anchor.leasing must contain at least one module"
    return files


def _imported_module_names(source_file: Path) -> list[str]:
    """Absolute and relative import targets declared in one module.

    A relative import (``from .contracts import Lease``) is resolved against
    the module's own package so that ``from ..engine.debt import x`` is caught
    as ``anchor.engine.debt`` rather than slipping past an absolute-name
    check.
    """

    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    package_parts = source_file.resolve().relative_to(_SRC_DIR).parts[:-1]

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(package_parts)
                if node.level > 1:
                    base = base[: -(node.level - 1)]
                resolved = base + ([node.module] if node.module else [])
                names.append(".".join(resolved))
            elif node.module:
                names.append(node.module)
    return names


# =============================================================================
# G-1 -- anchor.leasing does not reach into the downstream engine or any
#        adjacent layer
# =============================================================================


@pytest.mark.parametrize("forbidden", _FORBIDDEN_LEASING_IMPORTS)
def test_leasing_package_never_imports_a_forbidden_module(forbidden: str) -> None:
    for source_file in _leasing_source_files():
        names = _imported_module_names(source_file)
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}.") for name in names
        ), f"{source_file} must not import {forbidden}"


def test_leasing_package_imports_no_external_sdk() -> None:
    """The leasing layer is pure domain logic -- no OpenAI, no Azure, no HTTP
    client, no database driver."""

    for source_file in _leasing_source_files():
        names = _imported_module_names(source_file)
        for banned_prefix in ("openai", "azure", "sqlite3", "fastapi", "httpx", "requests"):
            assert not any(
                name == banned_prefix or name.startswith(f"{banned_prefix}.")
                for name in names
            ), f"{source_file} must not import {banned_prefix}"


#: The only non-leasing ``anchor`` modules D0 Section 3.5 permits the leasing
#: package to import: ``anchor.engine.contracts`` for ``ensure_finite`` /
#: ``NonFiniteResultError`` (D1.2 uses it so the package shares Anchor's one
#: non-finite convention rather than growing a parallel one), and
#: ``anchor.contracts`` for ``AcquisitionTerms`` from D4. Both are
#: calculation-free contract modules.
_PERMITTED_ANCHOR_IMPORTS = frozenset({"anchor.engine.contracts", "anchor.contracts"})


def test_leasing_package_imports_only_stdlib_its_own_modules_and_contracts() -> None:
    """The package stays free of every calculation module.

    It may reach for a calculation-*free* contract module that D0 Section 3.5
    explicitly sanctions, and nothing else under ``anchor``. The forbidden
    list above still bars every engine calculator by name.
    """

    for source_file in _leasing_source_files():
        for name in _imported_module_names(source_file):
            if not name.startswith("anchor"):
                continue
            if name.startswith("anchor.leasing"):
                continue
            assert name in _PERMITTED_ANCHOR_IMPORTS, (
                f"{source_file} imports {name}; anchor.leasing may import only "
                f"its own modules plus {sorted(_PERMITTED_ANCHOR_IMPORTS)}"
            )


# =============================================================================
# G-1 -- no existing layer imports anchor.leasing yet
# =============================================================================


@pytest.mark.parametrize(
    "package_dir",
    [_ENGINE_DIR, _ANALYSIS_DIR, _DEALS_DIR, _AI_DIR, _INGESTION_DIR],
    ids=["engine", "analysis", "deals", "ai", "ingestion"],
)
def test_no_existing_package_imports_anchor_leasing(package_dir: Path) -> None:
    """Integration is a D4 concern, in the direction ``anchor.engine`` ->
    ``anchor.leasing``. Nothing may depend on the leasing layer before then."""

    for source_file in package_dir.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(
            name == "anchor.leasing" or name.startswith("anchor.leasing.")
            for name in names
        ), f"{source_file} must not import anchor.leasing at D1"


def test_top_level_anchor_modules_do_not_import_anchor_leasing() -> None:
    for source_file in (_SRC_DIR / "anchor").glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(
            name == "anchor.leasing" or name.startswith("anchor.leasing.")
            for name in names
        ), f"{source_file} must not import anchor.leasing at D1"


def test_importing_anchor_engine_does_not_pull_in_anchor_leasing() -> None:
    """A fresh-interpreter check: the frozen engine package must not acquire a
    leasing dependency even transitively."""

    environment = os.environ.copy()
    python_path_parts = [str(_SRC_DIR)]
    if existing_python_path := environment.get("PYTHONPATH"):
        python_path_parts.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import anchor.engine; "
            "assert 'anchor.leasing' not in sys.modules",
        ],
        capture_output=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr.decode()


# =============================================================================
# HD-6 -- D1 did not begin a global validation refactor
# =============================================================================


def test_global_validation_module_was_not_given_a_severity_concept() -> None:
    """D0 Section 19.1 / HD-6: Lease-Level's ERROR/WARNING distinction is
    introduced locally in ``anchor.leasing.validation``. Whether Anchor's
    global validator should later gain severity is a separate architectural
    decision, and D1 is not coupled to it.

    This is the mechanical proof that the decision was honored."""

    source = (_SRC_DIR / "anchor" / "validation.py").read_text(encoding="utf-8")

    assert "severity" not in source.lower()
    assert "IssueSeverity" not in source


def test_leasing_validation_does_not_import_global_validation() -> None:
    for source_file in _leasing_source_files():
        names = _imported_module_names(source_file)
        assert "anchor.validation" not in names, (
            f"{source_file} must not import anchor.validation"
        )


# =============================================================================
# D1.0 scope -- the package computes nothing yet
# =============================================================================


#: Fields whose arithmetic *is* rent arithmetic. Area arithmetic is
#: deliberately absent from this set: reconciling suite areas against
#: ``rentable_area_sf`` is legitimate, reviewed D1.0 behaviour.
_RENT_BEARING_FIELDS = frozenset({"base_rent_psf", "escalation_pct"})


def _referenced_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


#: The one module permitted to perform rent arithmetic. Keeping this a single
#: named file -- rather than a blanket exemption for ``anchor.leasing`` -- is
#: what makes the financial boundary visible and enforceable: rent math has
#: exactly one home, and a stray calculation in ``validation.py`` or
#: ``calendar.py`` still fails.
_RENT_CALCULATION_MODULE = "rent.py"


def test_rent_arithmetic_is_confined_to_the_authoritative_rent_module() -> None:
    """Money is computed in exactly one place; every other module computes
    time, shape, or validity.

    Two semantic checks, replacing D1.0's raw-text bans on the substrings
    ``**`` and ``/ 12``. Those were blunt in both directions: they tripped on
    prose that merely *mentioned* the forbidden form, and would have blocked
    legitimate calendar arithmetic while saying nothing about whether a rent
    field was actually involved.

    1. No exponentiation outside ``rent.py`` -- that is compound escalation
       (D0 Section 6.1).
    2. No arithmetic expression outside ``rent.py`` may reference a
       rent-bearing field. ``base_rent_psf * leased_area_sf / 12`` is the
       D1.2 formula and belongs to one module only.

    Area arithmetic stays permitted everywhere: reconciling suite areas
    against ``rentable_area_sf`` is reviewed D1.0 behaviour, not rent math.
    """

    for source_file in _leasing_source_files():
        if source_file.name == _RENT_CALCULATION_MODULE:
            continue
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp):
                continue
            if isinstance(node.op, ast.Pow):
                pytest.fail(
                    f"{source_file} contains exponentiation; compound "
                    f"escalation belongs to {_RENT_CALCULATION_MODULE}"
                )
            leaked = _referenced_names(node) & _RENT_BEARING_FIELDS
            assert not leaked, (
                f"{source_file} performs arithmetic on {sorted(leaked)}; "
                f"rent calculation belongs to {_RENT_CALCULATION_MODULE}"
            )


def test_the_rent_module_is_the_only_one_that_touches_rent_fields() -> None:
    """The exemption above is meaningful only if ``rent.py`` genuinely holds
    the rent formula -- otherwise the boundary could be satisfied by an empty
    exempt file while the math lived elsewhere."""

    rent_module = _LEASING_DIR / _RENT_CALCULATION_MODULE
    assert rent_module.exists(), "the authoritative rent module must exist"

    tree = ast.parse(rent_module.read_text(encoding="utf-8"), filename=str(rent_module))
    referenced = _referenced_names(tree)

    assert _RENT_BEARING_FIELDS <= referenced, (
        f"{rent_module} must reference {sorted(_RENT_BEARING_FIELDS)}"
    )
    assert any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
        for node in ast.walk(tree)
    ), f"{rent_module} must contain the compound-escalation term"


def test_leasing_package_contains_only_the_gate_d1_2_modules() -> None:
    """D0 Gate D1.0 files, plus D1.1's ``calendar.py`` and D1.2's ``rent.py``.
    The aggregation module (D1.3) arrives at its own gate."""

    assert {path.name for path in _leasing_source_files()} == {
        "__init__.py",
        "calendar.py",
        "contracts.py",
        "rent.py",
        "validation.py",
    }
