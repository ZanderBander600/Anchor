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


def test_leasing_package_contains_only_the_gate_d2_4_modules() -> None:
    """D0 Gate D1.0 files, plus D1.1's ``calendar.py``, D1.2's ``rent.py``,
    D1.3's ``aggregation.py``, D2.1's ``market.py``, D2.2/D2.3's
    ``rollover.py`` and D2.4's ``leasing_costs.py`` (D2 Section 14)."""

    assert {path.name for path in _leasing_source_files()} == {
        "__init__.py",
        "aggregation.py",
        "calendar.py",
        "contracts.py",
        "leasing_costs.py",
        "market.py",
        "rent.py",
        "rollover.py",
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


def test_no_later_gate_module_exists_at_d2_4() -> None:
    """D2 Section 14 assigns the whole rollover engine to one module, so a
    second, overlapping home for branch logic is how two rollover
    implementations start. ``composition.py`` is barred for the same reason at
    D2.5: the weighting belongs in ``rollover.py`` beside the branches it
    weights."""

    for forbidden in ("renewal.py", "downtime.py", "successor.py", "composition.py"):
        assert not (_LEASING_DIR / forbidden).exists(), (
            f"{forbidden} duplicates rollover.py or belongs to a later D2 "
            "gate, and must not exist at D2.4"
        )


#: Vocabulary each later D2 gate owns (D2 Section 12's assumption inventory).
#: None of it may appear anywhere in production code -- not as a field, not as
#: a parameter, not as a function name.
#:
#: **Narrowed at D2.4**, and only by the fields that gate delivers:
#: ``renewal_ti_psf``, ``new_ti_psf``, ``renewal_lc_pct``, ``new_lc_pct``,
#: ``leasing_commission_method`` and the ``tenant_improvements`` /
#: ``leasing_commissions`` series. Everything D2.5 owns stays, so the guardrail
#: keeps its full force against probability weighting and expected values.
#:
#: ``new_rent_psf`` stays banned permanently and deliberately: D2 Section 12
#: records its absence as correct, because a new letting prices at market by
#: definition. Its appearance would be a financial-model error, not a gate
#: violation.
#:
#: The D4 integration names are barred permanently *at this layer*: D4.0 owns
#: the decision about how below-NOI costs reach the shared acquisition engine,
#: and `anchor.leasing` must not pre-empt it by inventing a channel.
_LATER_D2_GATE_NAMES = frozenset(
    {
        # D2.5 -- probability composition
        "renewal_probability",
        "expected_occupancy",
        "expected_occupied_area_sf",
        "expected_rent_psf",
        "expected_term_months",
        "expected_ti_psf",
        "expected_lc_pct",
        # never -- a new letting prices at market (D2 Section 12)
        "new_rent_psf",
        "new_rent_spread",
        # D4 -- the downstream below-NOI channel
        "leasing_costs_by_year",
        "variable_below_noi_costs_by_year",
        "property_capital_costs_by_year",
        "BelowNoiCosts",
        "AcquisitionResults",
    }
)


def test_no_later_d2_gate_vocabulary_appears_in_production_code() -> None:
    """D2.4 builds both branches, their concessions and their leasing costs,
    and stops.

    Probability weighting is D2.5 and the downstream below-NOI channel is D4.
    Declaring any of their names now would put vocabulary into the package with
    no mechanism behind it -- the same rule D1 applied to ``Lease.origin`` and
    ``Suite.market_rent_psf``, which each waited for the gate that could
    actually produce them.
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


# =============================================================================
# D2.2 -- the renewal branch owns no rent formula, and no later gate leaked in
# =============================================================================


_ROLLOVER_MODULE = "rollover.py"


def _rollover_tree() -> ast.AST:
    module = _LEASING_DIR / _ROLLOVER_MODULE
    return ast.parse(module.read_text(encoding="utf-8"), filename=str(module))


def test_the_rollover_module_consumes_the_authoritative_market_schedule() -> None:
    """The renewal successor must price from D2.1's canonical schedule, not
    from a market rent it derived itself."""

    referenced = _referenced_names(_rollover_tree())

    assert "market_rent_psf_at_period" in referenced, (
        "rollover.py must read the market rate from the canonical schedule"
    )
    assert "MarketRentSchedule" in referenced


def test_the_rollover_module_implements_no_market_growth_formula() -> None:
    """There must never be one market-rent formula for schedules and another
    for rollover (failure mode FM-D2-12/13).

    ``rollover.py`` may *name* ``market_rent_growth`` -- it passes the rate to
    ``market.market_rent_psf_for_period`` for D0 Section 24.3's explicit
    renewal level -- but it may never perform arithmetic on it, and it may not
    exponentiate at all. Compound growth has exactly two homes: contractual
    escalation in ``rent.py`` and market step growth in ``market.py``.
    """

    module = _LEASING_DIR / _ROLLOVER_MODULE
    tree = _rollover_tree()

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            pytest.fail(
                f"{module} contains exponentiation; compound growth belongs to "
                f"{sorted(_EXPONENTIATION_PERMITTED_MODULES)}"
            )

    assert _ROLLOVER_MODULE not in _EXPONENTIATION_PERMITTED_MODULES


def test_the_rollover_module_implements_no_contractual_rent_formula() -> None:
    """A successor is an ordinary contractual lease from its commencement, so
    its monthly rent comes from ``rent.build_lease_monthly_schedule`` -- the
    one D1 formula. ``rollover.py`` constructs a ``Lease`` and hands it over.

    It therefore may never perform arithmetic on a rent-bearing field, and may
    never multiply a rent by an area or divide one by 12: that would be a
    second contractual-rent engine, free to drift from the first.
    """

    module = _LEASING_DIR / _ROLLOVER_MODULE
    tree = _rollover_tree()
    referenced = _referenced_names(tree)

    assert "build_lease_monthly_schedule" in referenced, (
        "rollover.py must build successor rent through the D1 rent engine"
    )

    area_names = {"suite_area_sf", "leased_area_sf", "rentable_area_sf"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue

        leaked = _referenced_names(node) & _RENT_BEARING_FIELDS
        assert not leaked, (
            f"{module} performs arithmetic on {sorted(leaked)}; contractual "
            f"rent calculation belongs to {_RENT_CALCULATION_MODULE}"
        )

        if not isinstance(node.op, (ast.Mult, ast.Div)):
            continue
        operands = _referenced_names(node)
        if not operands & area_names:
            continue
        literals = {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, (int, float))
        }
        assert 12 not in literals and 12.0 not in literals, (
            f"{module} converts a rate to a monthly dollar amount; that is "
            f"{_RENT_CALCULATION_MODULE}'s single formula"
        )


def test_the_rollover_module_never_recomputes_the_expiring_lease() -> None:
    """D0 Section 24.4: contractual terms always win, and D2.2 reuses the
    in-place lease's D1 schedule unchanged. ``rollover.py`` may not read a
    rent assumption off the expiring lease at all (failure mode FM-D2-20)."""

    module = _LEASING_DIR / _ROLLOVER_MODULE
    leaked = _referenced_names(_rollover_tree()) & _RENT_BEARING_FIELDS

    assert not leaked, (
        f"{module} references {sorted(leaked)}; the expiring lease's rent is "
        "reused, never recomputed"
    )


def test_the_rent_and_market_modules_are_unchanged_by_the_renewal_gate() -> None:
    """The dependency runs rollover -> {market, rent}, never the reverse.
    Neither authority may learn about rollover, which is what keeps D1 and
    D2.1 economics provably untouched."""

    for module_name in ("rent.py", "market.py", "aggregation.py", "calendar.py"):
        module = _LEASING_DIR / module_name
        names = _imported_module_names(module)
        assert "anchor.leasing.rollover" not in names, (
            f"{module} imports rollover; the rollover engine is a consumer of "
            "these modules, never a dependency of them"
        )

        referenced = _referenced_names(
            ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        )
        for forbidden in ("RenewalBranch", "build_renewal_branch", "LeaseOrigin"):
            assert forbidden not in referenced, (
                f"{module} references {forbidden!r}; rollover vocabulary must "
                "not leak into the D1/D2.1 authorities"
            )


def test_the_downtime_and_free_rent_mechanics_each_have_one_home() -> None:
    """D2.3's two mechanics live in ``rollover.py`` and nowhere else.

    A second downtime formula or a second waterfall would be free to disagree
    with the first, and the branch that used the wrong one would still look
    plausible. The check runs both ways: the mechanics must be *in*
    ``rollover.py``, and *absent* from every other module.
    """

    referenced = _referenced_names(_rollover_tree())
    for required in (
        "successor_occupancy_factors",
        "free_rent_waterfall",
        "downtime_months",
        "free_rent_months",
    ):
        assert required in referenced, (
            f"rollover.py must own {required!r}"
        )

    for source_file in _leasing_source_files():
        if source_file.name in {_ROLLOVER_MODULE, "contracts.py", "validation.py"}:
            continue
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        names = _referenced_names(tree)
        for forbidden in (
            "successor_occupancy_factors",
            "free_rent_waterfall",
            "downtime_months",
            "free_rent_months",
            "cash_rent_factor",
        ):
            assert forbidden not in names, (
                f"{source_file} references {forbidden!r}; the downtime and "
                f"free-rent mechanics belong to {_ROLLOVER_MODULE}"
            )


def test_the_free_rent_waterfall_is_sequential_not_multiplicative() -> None:
    """HD-D2-4, mechanically. The waterfall carries running state and
    subtracts; a multiplicative rule would not need either.

    Asserts the function contains a ``min`` against a running remainder and a
    subtraction from it -- the shape of the approved rule -- and that no
    product of an occupancy factor and a free-rent factor appears.
    """

    waterfall = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef) and node.name == "free_rent_waterfall"
    )
    referenced = _referenced_names(waterfall)

    assert "min" in referenced, "the waterfall must clamp against the remainder"
    assert any(
        isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Sub)
        for node in ast.walk(waterfall)
    ) or any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
        for node in ast.walk(waterfall)
    ), "the waterfall must decrement the remaining concession"

    for node in ast.walk(waterfall):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            pytest.fail(
                "free_rent_waterfall multiplies; the approved rule is "
                "sequential (HD-D2-4), never a product of independent factors"
            )


def test_no_probability_or_composition_exists_in_the_renewal_branch() -> None:
    """D2.5 owns ``renewal_probability`` and the expected-value composition.
    D2.2 is one deterministic branch; it weights, averages and blends
    nothing."""

    referenced = _referenced_names(_rollover_tree())

    for absent in (
        "renewal_probability",
        "expected_occupancy",
        "expected_occupied_area_sf",
        "expected_rent_psf",
        "weight",
        "compose",
    ):
        assert absent not in referenced, (
            f"rollover.py references {absent!r}, which belongs to D2.5"
        )


def test_each_branch_reads_only_its_own_leasing_cost_rates() -> None:
    """D2.4. Both branches exist in one module, so the guardrail that keeps
    them apart is that each builder names only its own rates.

    A renewal that read ``new_ti_psf`` would look entirely plausible and be
    silently wrong, which is what the two-branch method exists to prevent."""

    tree = _rollover_tree()

    for builder, own, foreign in (
        (
            "build_renewal_branch",
            {"renewal_ti_psf", "renewal_lc_pct"},
            {"new_ti_psf", "new_lc_pct"},
        ),
        (
            "build_new_tenant_branch",
            {"new_ti_psf", "new_lc_pct"},
            {"renewal_ti_psf", "renewal_lc_pct"},
        ),
    ):
        node = next(
            item
            for item in ast.walk(tree)
            if isinstance(item, ast.FunctionDef) and item.name == builder
        )
        referenced = _referenced_names(node)

        assert own <= referenced, f"{builder} must read {sorted(own)}"
        leaked = referenced & foreign
        assert not leaked, (
            f"{builder} reads {sorted(leaked)}; a branch never inherits the "
            "other branch's leasing-cost rates"
        )


def test_a_new_letting_has_no_rent_field_of_its_own() -> None:
    """D2 Section 12: the absence of ``new_rent_psf`` is deliberate, not a gap.

    A new letting prices at ``MarketRentPSF(c)`` by definition, while a renewal
    is negotiated relative to market and therefore carries both an explicit
    level and a spread. A ``new_rent_psf`` field would be a financial-model
    error at any gate.
    """

    for source_file in _leasing_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        names = _referenced_names(tree)
        for forbidden in ("new_rent_psf", "new_rent_spread"):
            assert forbidden not in names, (
                f"{source_file} references {forbidden!r}; a new letting prices "
                "at market by definition"
            )


def test_the_new_tenant_branch_never_reads_a_renewal_assumption() -> None:
    """Cross-branch contamination is what the two-branch method exists to
    prevent. The new-tenant pricing function may not name a renewal field."""

    pricer = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "new_tenant_starting_rent_psf"
    )
    referenced = _referenced_names(pricer)

    for forbidden in ("renewal_rent_psf", "renewal_rent_spread"):
        assert forbidden not in referenced, (
            f"new_tenant_starting_rent_psf references {forbidden!r}; a "
            "replacement tenant never inherits a renewal concession"
        )


def test_both_branches_expose_the_same_series_names() -> None:
    """D2.5 weights the two branches month by month. A composition layer that
    had to translate between two shapes would be a place for the branches to
    disagree, so the series names must match exactly."""

    import dataclasses

    from anchor.leasing import NewTenantBranch, RenewalBranch

    series = {
        "contractual_base_rent",
        "successor_occupancy_factor",
        "free_rent_abatement_months",
        "cash_rent_factor",
        "free_rent",
        "cash_base_rent",
        "occupied_area",
        "physical_occupancy",
    }
    renewal_fields = {f.name for f in dataclasses.fields(RenewalBranch)}
    new_fields = {f.name for f in dataclasses.fields(NewTenantBranch)}

    assert series <= renewal_fields
    assert series <= new_fields

    # The renewal branch carries exactly two extra fields -- its own pricing
    # assumptions -- and nothing else differs.
    assert renewal_fields - new_fields == {"renewal_rent_psf", "renewal_rent_spread"}
    assert new_fields - renewal_fields == set()


def test_face_rent_is_never_overwritten_with_cash_rent() -> None:
    """``contractual_base_rent`` is gross face rent on both branches; cash and
    the abatement live on their own series (failure modes FM-D2-10,
    FM-D2-11b). D2.4's LC basis reads face and must never see a concession.

    Asserted structurally: no assignment in ``rollover.py`` puts a
    cash-factored or abated value into the face-rent series.
    """

    tree = _rollover_tree()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "append"):
            continue
        if not (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "contractual_base_rent"
        ):
            continue
        appended = _referenced_names(node)
        for forbidden in ("cash_factor", "abatement_months", "cash_rent_factor"):
            assert forbidden not in appended, (
                "contractual_base_rent is FACE rent; a concession must never "
                "be netted into it"
            )


def test_the_renewal_branch_does_not_recurse() -> None:
    """D2.6 owns recursion to the canonical projection end (D2 HD-D2-3).

    D2.2 produces exactly one successor: no function in ``rollover.py`` calls
    itself, and none reaches for a chain, a depth or a node cap.
    """

    tree = _rollover_tree()

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        called = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        assert node.name not in called, (
            f"rollover.py's {node.name} calls itself; recursion belongs to D2.6"
        )

    referenced = _referenced_names(tree)
    for absent in ("max_depth", "depth", "chain", "node_limit", "recurse"):
        assert absent not in referenced, (
            f"rollover.py references {absent!r}, which belongs to D2.6"
        )


def test_the_composed_fractional_naming_restriction_is_respected() -> None:
    """D2 HD-D2-2's binding restriction, from the other direction: the branch's
    own occupancy is genuine and integral, so it correctly *keeps* the name
    ``physical_occupancy``. The fractional composed series does not exist yet
    and must not be named here under any spelling."""

    referenced = _referenced_names(_rollover_tree())

    assert "physical_occupancy" in referenced, (
        "the renewal branch's occupancy is a genuine integral scenario state "
        "and keeps that name"
    )
    for absent in ("expected_occupancy", "expected_occupied_area_sf"):
        assert absent not in referenced


def test_the_rollover_module_performs_no_io() -> None:
    """A pure calculator: no file, network, database or clock access."""

    referenced = _referenced_names(_rollover_tree())

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
            f"rollover.py references {forbidden!r}; the branch builder must be pure"
        )


def test_successor_provenance_is_set_by_the_engine_not_the_caller() -> None:
    """D0 Section 8.4: a successor's ``tenant_name`` is ``None`` and its
    ``origin`` is ``SUCCESSOR``. Both are set inside the builder, so a caller
    cannot produce a successor that presents as a known tenant
    (failure mode FM-D2-18)."""

    tree = _rollover_tree()

    builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_successor_lease"
    )
    parameters = {argument.arg for argument in builder.args.args} | {
        argument.arg for argument in builder.args.kwonlyargs
    }

    assert "tenant_name" not in parameters, (
        "a caller must not be able to name a tenant on a successor"
    )
    assert "origin" not in parameters, (
        "a caller must not be able to declare a successor's origin"
    )

    # ... and the builder sets both itself, on the Lease it constructs.
    lease_call = next(
        node
        for node in ast.walk(builder)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Lease"
    )
    keywords = {keyword.arg: keyword.value for keyword in lease_call.keywords}

    assert isinstance(keywords["tenant_name"], ast.Constant)
    assert keywords["tenant_name"].value is None, (
        "a successor's tenant_name must be literally None (D0 Section 8.4)"
    )
    origin = keywords["origin"]
    assert isinstance(origin, ast.Attribute) and origin.attr == "SUCCESSOR", (
        "a successor's origin must be literally LeaseOrigin.SUCCESSOR"
    )


# =============================================================================
# D2.4 -- TI and LC have one home each, sit below NOI, and use FACE rent
# =============================================================================


_LEASING_COSTS_MODULE = "leasing_costs.py"


def _leasing_costs_tree() -> ast.AST:
    module = _LEASING_DIR / _LEASING_COSTS_MODULE
    return ast.parse(module.read_text(encoding="utf-8"), filename=str(module))


def test_the_ti_and_lc_formulas_have_one_home_each() -> None:
    """Both live in ``leasing_costs.py`` and nowhere else. A second TI or LC
    formula would be free to disagree with the first, and the branch that used
    the wrong one would still look plausible."""

    referenced = _referenced_names(_leasing_costs_tree())
    for required in ("ti_psf", "lc_pct", "leased_area_sf"):
        assert required in referenced, f"leasing_costs.py must own {required!r}"

    for source_file in _leasing_source_files():
        if source_file.name in {
            _LEASING_COSTS_MODULE,
            "contracts.py",
            "validation.py",
            _ROLLOVER_MODULE,
        }:
            continue
        names = _referenced_names(
            ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        )
        for forbidden in ("ti_psf", "lc_pct", "tenant_improvement_amount",
                          "leasing_commission_amount"):
            assert forbidden not in names, (
                f"{source_file} references {forbidden!r}; leasing-cost "
                f"calculation belongs to {_LEASING_COSTS_MODULE}"
            )


def test_rollover_delegates_the_leasing_cost_formulas() -> None:
    """``rollover.py`` may pass the rates through, but must not compute either
    amount itself."""

    tree = _rollover_tree()
    referenced = _referenced_names(tree)

    assert "tenant_improvement_amount" in referenced
    assert "leasing_commission_amount" in referenced
    assert "contractual_face_rent_over_full_term" in referenced

    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
            continue
        operands = _referenced_names(node)
        assert not ({"ti_psf", "lc_pct"} & operands), (
            "rollover.py multiplies a leasing-cost rate; both formulas belong "
            f"to {_LEASING_COSTS_MODULE}"
        )


def test_the_lc_basis_is_contractual_face_rent_never_cash() -> None:
    """The commission is earned on the lease signed. Naming a cash series in an
    *amount* function would understate every commission carrying free rent or
    downtime, and would do it invisibly (failure mode FM-D2-10).

    The ban is scoped to the two amount functions rather than to the whole
    module, and the distinction is the point: ``leasing_cost_event_period``
    *must* read ``successor_occupancy_factor``, because D2 Section 8.1 defines
    the event month as the first period with ``O_m > 0``. Occupancy determines
    **when** a cost lands; it may never determine **how much**.
    """

    tree = _leasing_costs_tree()
    amount_functions = {"tenant_improvement_amount", "leasing_commission_amount"}

    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in amount_functions:
            continue
        seen.add(node.name)
        referenced = _referenced_names(node)
        for forbidden in (
            "cash_rent_factor",
            "cash_base_rent",
            "free_rent",
            "free_rent_abatement_months",
            "successor_occupancy_factor",
            "downtime_months",
            "free_rent_months",
        ):
            assert forbidden not in referenced, (
                f"{node.name} references {forbidden!r}; the LC basis is "
                "contractual FACE rent, and TI is never prorated"
            )

    assert seen == amount_functions, f"missing amount functions: {amount_functions - seen}"


def test_the_full_term_basis_reuses_the_one_contractual_rent_formula() -> None:
    """D2.4 extended ``rent.py`` additively. The extension must call the same
    ``monthly_base_rent`` and ``escalation_period_index`` the D1 schedule uses,
    so exactly one contractual-rent formula still exists."""

    module = _LEASING_DIR / _RENT_CALCULATION_MODULE
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

    helper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "contractual_face_rent_over_full_term"
    )
    referenced = _referenced_names(helper)

    assert "monthly_base_rent" in referenced, (
        "the full-term basis must call the authoritative monthly formula"
    )
    assert "escalation_period_index" in referenced, (
        "the full-term basis must use the authoritative escalation chronology"
    )

    # No closed form: the helper must iterate, and must not exponentiate.
    assert any(isinstance(node, ast.For) for node in ast.walk(helper)), (
        "the full-term basis must iterate the contractual months"
    )
    for node in ast.walk(helper):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            pytest.fail(
                "the full-term basis contains exponentiation; a geometric "
                "shortcut would be a second rent formula"
            )


def test_only_one_monthly_contractual_rent_formula_exists() -> None:
    """The compound-escalation term appears exactly once in the package -- in
    ``monthly_base_rent`` -- and every other contractual-rent path reaches it."""

    module = _LEASING_DIR / _RENT_CALCULATION_MODULE
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

    powers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
    ]
    assert len(powers) == 1, (
        f"{module} contains {len(powers)} exponentiations; the contractual "
        "escalation term must appear exactly once"
    )

    owner = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "monthly_base_rent"
    )
    assert any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
        for node in ast.walk(owner)
    ), "monthly_base_rent must hold the escalation term"


def test_the_lc_basis_never_sums_the_visible_schedule() -> None:
    """A successor term may exceed the projection, so summing
    ``successor_schedule`` would truncate the commission (failure mode FM-17).
    The basis must come from the successor ``Lease``, not from its schedule."""

    tree = _rollover_tree()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Name)
            and node.func.id == "contractual_face_rent_over_full_term"
        ):
            continue
        operands = _referenced_names(node)
        assert "successor_schedule" not in operands, (
            "the LC basis must be derived from the successor Lease, never from "
            "its truncated schedule"
        )
        assert "contractual_base_rent" not in operands


def test_leasing_costs_are_pure_and_perform_no_io() -> None:
    referenced = _referenced_names(_leasing_costs_tree())

    for forbidden in ("open", "read_text", "write_text", "connect", "now", "today"):
        assert forbidden not in referenced, (
            f"leasing_costs.py references {forbidden!r}; it must be pure"
        )


def test_leasing_costs_never_reach_the_downstream_engine() -> None:
    """D4.0 owns how below-NOI costs reach acquisition, debt and returns.
    ``anchor.leasing`` must not pre-empt that decision by inventing a channel,
    and the forbidden-import list already bars every engine calculator."""

    module = _LEASING_DIR / _LEASING_COSTS_MODULE
    names = _imported_module_names(module)

    for forbidden in _FORBIDDEN_LEASING_IMPORTS:
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}.") for name in names
        ), f"{module} must not import {forbidden}"


def test_the_commission_method_lives_on_the_assumptions_never_on_a_lease() -> None:
    """D0 Section 12.3's extension seam: adding ``PER_SF`` later must mean one
    enum member plus rate fields, with no ``Lease`` contract change and no
    lease-data migration."""

    import dataclasses

    from anchor.leasing import Lease, LeasingCommissionMethod, MarketLeasingAssumptions

    assert "leasing_commission_method" not in {
        f.name for f in dataclasses.fields(Lease)
    }
    assert "leasing_commission_method" in {
        f.name for f in dataclasses.fields(MarketLeasingAssumptions)
    }
    assert len(list(LeasingCommissionMethod)) == 1


def test_leasing_costs_are_never_added_into_a_rent_series() -> None:
    """Below NOI, structurally: no append into a rent, cash or occupancy list
    may reference a leasing-cost value."""

    tree = _rollover_tree()
    rent_series = {
        "contractual_base_rent",
        "cash_base_rent",
        "free_rent",
        "occupied_area",
        "physical_occupancy",
    }
    cost_names = {
        "ti_amount",
        "lc_amount",
        "tenant_improvements",
        "leasing_commissions",
        "full_term_face_rent",
    }

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "append"):
            continue
        if not (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id in rent_series
        ):
            continue
        leaked = _referenced_names(node) & cost_names
        assert not leaked, (
            f"{node.func.value.id} receives {sorted(leaked)}; TI and LC are "
            "strictly below NOI and never enter a rent series"
        )
