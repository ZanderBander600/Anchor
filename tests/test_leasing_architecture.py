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


#: The one module permitted to perform contractual-rent arithmetic. Keeping
#: this a single named file -- rather than a blanket exemption for
#: ``anchor.leasing`` -- is what makes the financial boundary visible and
#: enforceable: rent math has exactly one home, and a stray calculation in
#: ``validation.py`` or ``calendar.py`` still fails.
_RENT_CALCULATION_MODULE = "rent.py"

#: Fields whose arithmetic *is* market-rent arithmetic (D2.1).
_MARKET_BEARING_FIELDS = frozenset({"market_rent_psf", "market_rent_growth"})

#: The one module permitted to perform market-rent arithmetic (D2.1), on the
#: identical principle. The two calculation modules are peers with disjoint
#: field sets: ``rent.py`` owns the contractual formula and ``market.py`` owns
#: the market formula, and neither may reach into the other's assumptions.
#: That is the mechanical form of D2 Section 10 -- two different clocks.
_MARKET_CALCULATION_MODULE = "market.py"

#: Exponentiation is compound growth, and both formulas need it: contractual
#: escalation ``(1 + escalation_pct) ** k`` and market step growth
#: ``(1 + market_rent_growth) ** k``. It stays banned everywhere else.
_EXPONENTIATION_PERMITTED_MODULES = frozenset(
    {_RENT_CALCULATION_MODULE, _MARKET_CALCULATION_MODULE}
)


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
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp):
                continue
            if (
                isinstance(node.op, ast.Pow)
                and source_file.name not in _EXPONENTIATION_PERMITTED_MODULES
            ):
                pytest.fail(
                    f"{source_file} contains exponentiation; compound growth "
                    f"belongs to {sorted(_EXPONENTIATION_PERMITTED_MODULES)}"
                )
            referenced = _referenced_names(node)

            if source_file.name != _RENT_CALCULATION_MODULE:
                leaked = referenced & _RENT_BEARING_FIELDS
                assert not leaked, (
                    f"{source_file} performs arithmetic on {sorted(leaked)}; "
                    f"contractual rent calculation belongs to "
                    f"{_RENT_CALCULATION_MODULE}"
                )

            if source_file.name != _MARKET_CALCULATION_MODULE:
                leaked = referenced & _MARKET_BEARING_FIELDS
                assert not leaked, (
                    f"{source_file} performs arithmetic on {sorted(leaked)}; "
                    f"market rent calculation belongs to "
                    f"{_MARKET_CALCULATION_MODULE}"
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


def test_leasing_package_contains_only_the_gate_d2_1_modules() -> None:
    """D0 Gate D1.0 files, plus D1.1's ``calendar.py``, D1.2's ``rent.py``,
    D1.3's ``aggregation.py`` and D2.1's ``market.py``.

    In particular ``rollover.py`` must **not** exist yet: D2 Section 14 gates
    it at D2.2, and an empty placeholder module would be rollover vocabulary
    in a gate whose scope excludes it."""

    assert {path.name for path in _leasing_source_files()} == {
        "__init__.py",
        "aggregation.py",
        "calendar.py",
        "contracts.py",
        "market.py",
        "rent.py",
        "validation.py",
    }


# =============================================================================
# D1.3 -- property aggregation is isolated from rent derivation
# =============================================================================


_AGGREGATION_MODULE = "aggregation.py"


def test_aggregation_never_references_a_rent_assumption() -> None:
    """Property aggregation must be completely agnostic to *how* a
    ``LeaseMonthlySchedule`` obtained its monthly values.

    Stronger than the arithmetic-only rule applied to the other modules: the
    aggregator may not so much as *name* ``base_rent_psf`` or
    ``escalation_pct``. That is what lets a future ``rent_anchor_date`` or an
    explicit rent-step schedule change how monthly rent is derived without
    touching a line of property aggregation -- the accepted D1.2 current-rent
    limitation is confined to ``rent.py`` by construction.
    """

    module = _LEASING_DIR / _AGGREGATION_MODULE
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    referenced = _referenced_names(tree)

    leaked = referenced & _RENT_BEARING_FIELDS
    assert not leaked, (
        f"{module} references {sorted(leaked)}; property aggregation must "
        "depend only on LeaseMonthlySchedule, never on a rent assumption"
    )


def test_aggregation_consumes_the_authoritative_lease_schedule() -> None:
    """The dependency must run aggregation -> rent, so there is exactly one
    contractual-rent formula in production code."""

    module = _LEASING_DIR / _AGGREGATION_MODULE
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    referenced = _referenced_names(tree)

    assert "build_lease_monthly_schedule" in referenced
    assert "LeaseMonthlySchedule" in referenced


def test_no_annual_figure_is_produced_from_anything_but_a_monthly_series() -> None:
    """Guardrails G-M2 and G-M3: annual values derive solely from canonical
    monthly ones, and there is no independent annual rent engine.

    Every annual-producing function takes exactly one positional data
    parameter -- the monthly series -- plus the keyword-only ``hold_period``.
    None of them can reach a ``Lease``, a ``Suite``, or a property input,
    because none of them accepts one.
    """

    module = _LEASING_DIR / _AGGREGATION_MODULE
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

    annual_producers = {
        "aggregate_flow_to_annual",
        "aggregate_flow_over_forward_exit_window",
        "snapshot_state_at_year_end",
        "average_state_over_year",
    }
    seen: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in annual_producers:
            continue
        seen.add(node.name)

        positional = [argument.arg for argument in node.args.args]
        assert positional == ["monthly"], (
            f"{node.name} must take the monthly series as its only positional "
            f"argument; got {positional}"
        )
        keyword_only = [argument.arg for argument in node.args.kwonlyargs]
        assert keyword_only == ["hold_period"], (
            f"{node.name} must take only hold_period as a keyword argument; "
            f"got {keyword_only}"
        )

    assert seen == annual_producers, f"missing annual producers: {annual_producers - seen}"


# =============================================================================
# D2.1 -- market rent is isolated, and no later D2 gate has leaked into it
# =============================================================================


def test_the_market_module_is_the_only_one_that_touches_market_fields() -> None:
    """The exemption above is meaningful only if ``market.py`` genuinely holds
    the market-rent formula -- otherwise the boundary could be satisfied by an
    empty exempt file while the math lived elsewhere."""

    module = _LEASING_DIR / _MARKET_CALCULATION_MODULE
    assert module.exists(), "the authoritative market-rent module must exist"

    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    referenced = _referenced_names(tree)

    assert _MARKET_BEARING_FIELDS <= referenced, (
        f"{module} must reference {sorted(_MARKET_BEARING_FIELDS)}"
    )
    assert any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
        for node in ast.walk(tree)
    ), f"{module} must contain the annual-step growth term"


def test_the_market_module_never_touches_a_contractual_rent_assumption() -> None:
    """D2 Section 10, mechanically: market growth prices available space and
    has no access to a signed lease's rent or escalation. Stronger than the
    arithmetic rule -- ``market.py`` may not so much as *name* them
    (failure mode FM-D2-14)."""

    module = _LEASING_DIR / _MARKET_CALCULATION_MODULE
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

    leaked = _referenced_names(tree) & _RENT_BEARING_FIELDS
    assert not leaked, (
        f"{module} references {sorted(leaked)}; market rent must never read a "
        "contractual lease assumption"
    )


@pytest.mark.parametrize(
    "module_name", ["rent.py", "aggregation.py", "calendar.py"]
)
def test_the_d1_modules_never_reference_a_market_assumption(module_name: str) -> None:
    """The converse boundary, and the mechanical form of failure mode
    FM-D2-20: D2.1 left the D1 contractual-rent formula, the property
    aggregator and the calendar completely untouched.

    Stronger than the arithmetic rule: none of the three may even *name* a
    market field. ``rent.py`` cannot reach for a market rent at expiration,
    ``aggregation.py`` cannot compute one, and ``calendar.py`` cannot either.
    """

    module = _LEASING_DIR / module_name
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

    leaked = _referenced_names(tree) & _MARKET_BEARING_FIELDS
    assert not leaked, (
        f"{module} references {sorted(leaked)}; market-rent assumptions belong "
        f"to {_MARKET_CALCULATION_MODULE}"
    )


def test_no_rollover_module_exists_at_d2_1() -> None:
    """D2 Section 14 gates ``rollover.py`` at D2.2 and ``leasing_costs.py`` at
    D2.4. Neither may exist yet, even empty."""

    for forbidden in ("rollover.py", "leasing_costs.py", "renewal.py", "downtime.py"):
        assert not (_LEASING_DIR / forbidden).exists(), (
            f"{forbidden} belongs to a later D2 gate and must not exist at D2.1"
        )


#: Vocabulary each later D2 gate owns (D2 Section 12's assumption inventory).
#: None of it may appear anywhere in D2.1 production code -- not as a field,
#: not as a parameter, not as a function name.
_LATER_D2_GATE_NAMES = frozenset(
    {
        # D2.5 -- probability composition
        "renewal_probability",
        "expected_occupancy",
        "expected_occupied_area_sf",
        # D2.2 -- the renewal branch
        "renewal_rent_psf",
        "renewal_rent_spread",
        "renewal_term_months",
        "new_term_months",
        "successor_escalation_pct",
        # D2.2 / D2.3 -- downtime and free rent
        "renewal_downtime_months",
        "new_downtime_months",
        "downtime_months",
        "renewal_free_rent_months",
        "new_free_rent_months",
        "occupancy_factor",
        # D2.4 -- TI and LC
        "renewal_ti_psf",
        "new_ti_psf",
        "renewal_lc_pct",
        "new_lc_pct",
        "leasing_commission_method",
        "tenant_improvements",
        "leasing_commissions",
    }
)


def test_no_later_d2_gate_vocabulary_appears_in_production_code() -> None:
    """D2.1 builds a market-rent rate schedule and stops.

    Renewal, new tenants, downtime, free rent, TI, LC and probability
    weighting are D2.2-D2.5. Declaring any of their names now would put
    vocabulary into the package with no mechanism behind it -- the same rule
    D1 applied to ``Lease.origin`` and ``Suite.market_rent_psf``, which each
    waited for the gate that could actually produce them.
    """

    for source_file in _leasing_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        leaked = _referenced_names(tree) & _LATER_D2_GATE_NAMES
        assert not leaked, (
            f"{source_file} names {sorted(leaked)}, which belongs to a later "
            "D2 gate"
        )


def test_market_rent_is_never_converted_into_a_cash_flow() -> None:
    """D2.1 produces a ``$/SF/year`` **rate**. Converting it to income needs a
    commencement period, a term, downtime and free rent -- none of which exist
    yet -- so no market field may be multiplied by an area or divided by 12.

    The check is precise rather than textual: it looks for a multiplication or
    division whose operands mix a market field with an area field or the
    literal 12.
    """

    module = _LEASING_DIR / _MARKET_CALCULATION_MODULE
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    area_names = {"suite_area_sf", "leased_area_sf", "rentable_area_sf"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue
        if not isinstance(node.op, (ast.Mult, ast.Div)):
            continue
        referenced = _referenced_names(node)
        if not referenced & _MARKET_BEARING_FIELDS:
            continue

        assert not referenced & area_names, (
            f"{module} multiplies a market rate by an area; converting market "
            "rent into a cash flow is D2.2/D2.3 work"
        )
        literals = {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant)
            and isinstance(child.value, (int, float))
        }
        assert 12 not in literals and 12.0 not in literals, (
            f"{module} divides a market rate by 12; market rent is an annual "
            "rate, not a monthly dollar amount"
        )


def test_the_market_module_performs_no_io() -> None:
    """A pure calculator: no file, network, database or clock access."""

    module = _LEASING_DIR / _MARKET_CALCULATION_MODULE
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    referenced = _referenced_names(tree)

    for forbidden in (
        "open",
        "read_text",
        "write_text",
        "connect",
        "now",
        "today",
        "urlopen",
    ):
        assert forbidden not in referenced, (
            f"{module} references {forbidden!r}; the market-rent builder must "
            "be pure"
        )


def test_market_precedence_is_implemented_exactly_once() -> None:
    """D0 Section 24.5: the resolver runs once per suite and its result is
    recorded. A second precedence implementation anywhere would make "which
    assumption applied" answerable two ways.

    ``market_leasing_override`` is the field the precedence rule turns on, so
    only the resolver's own module may read it -- ``contracts.py`` declares it
    and ``validation.py`` domain-checks it, neither of which resolves it.
    """

    exempt = {_MARKET_CALCULATION_MODULE, "contracts.py", "validation.py"}

    for source_file in _leasing_source_files():
        if source_file.name in exempt:
            continue
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        assert "market_leasing_override" not in _referenced_names(tree), (
            f"{source_file} reads market_leasing_override; market-rent "
            f"precedence belongs to {_MARKET_CALCULATION_MODULE}"
        )
