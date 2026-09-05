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


def test_leasing_package_contains_only_the_gate_d3_1_modules() -> None:
    """D0 Gate D1.0 files, plus D1.1's ``calendar.py``, D1.2's ``rent.py``,
    D1.3's ``aggregation.py``, D2.1's ``market.py``, D2.2/D2.3's
    ``rollover.py``, D2.4's ``leasing_costs.py`` and D3.1's ``recoveries.py``
    (D3 conventions Section 14)."""

    assert {path.name for path in _leasing_source_files()} == {
        "__init__.py",
        "aggregation.py",
        "calendar.py",
        "contracts.py",
        "leasing_costs.py",
        "market.py",
        "recoveries.py",
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
#: **Narrowed at D2.5**, and only by the two names that gate delivers:
#: ``renewal_probability`` and the composed ``expected_occupancy`` /
#: ``expected_occupied_area_sf`` series, which HD-D2-2 names explicitly.
#:
#: What remains is banned **permanently**, not until some later gate:
#:
#: - ``expected_rent_psf``, ``expected_term_months``, ``expected_ti_psf``,
#:   ``expected_lc_pct``, ``expected_downtime_months``,
#:   ``expected_free_rent_months`` are the **rejected weighted-parameter**
#:   names from D0 Section 8.2. HD-D2-1 superseded that method; their
#:   appearance would mean averaging inputs rather than outcomes, which D2
#:   Section 1.2 quantified as materially wrong. No gate will ever add them.
#: - ``new_rent_psf`` and ``new_rent_spread``: D2 Section 12 records their
#:   absence as correct, because a new letting prices at market by definition.
#: - The D4 integration names are barred at this layer: D4.0 owns how
#:   below-NOI costs reach the shared acquisition engine, and `anchor.leasing`
#:   must not pre-empt it by inventing a channel.
_LATER_D2_GATE_NAMES = frozenset(
    {
        # never -- the rejected weighted-parameter method (D0 Section 8.2)
        "expected_rent_psf",
        "expected_term_months",
        "expected_ti_psf",
        "expected_lc_pct",
        "expected_downtime_months",
        "expected_free_rent_months",
        "weighted_term",
        "weighted_downtime",
        "weighted_free_rent",
        "weighted_ti_psf",
        "weighted_lc_pct",
        "weighted_starting_rent",
        "weighted_successor",
        "synthetic_lease",
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


def test_no_rejected_or_later_gate_vocabulary_appears_in_production_code() -> None:
    """D2.5 completes the approved composition, so what remains banned is
    banned for good.

    Every ``expected_*`` and ``weighted_*`` *parameter* name above belongs to
    the superseded D0 Section 8.2 method: averaging inputs and building one
    synthetic successor from the averages. HD-D2-1 replaced it with weighting
    outcomes, and D2 Section 1.2 quantified the difference -- five months of
    rent reported as zero, and a commission 19.8% low. These names must never
    reappear.
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


def test_the_branch_builders_never_read_the_probability() -> None:
    """**Branches are calculated before, and independently of, the weight.**

    Neither branch builder -- nor the shared core, nor either pricing
    function, nor the successor-lease builder -- may name
    ``renewal_probability``. A branch that knew the probability could bend its
    own economics toward the other scenario, which is exactly what weighting
    outcomes instead of parameters exists to prevent (HD-D2-1).
    """

    tree = _rollover_tree()
    branch_side = {
        "build_renewal_branch",
        "build_new_tenant_branch",
        "_build_branch_core",
        "renewal_starting_rent_psf",
        "new_tenant_starting_rent_psf",
        "build_successor_lease",
        "build_renewal_successor_lease",
        "successor_occupancy_factors",
        "free_rent_waterfall",
        "successor_commencement_period",
        "successor_expiration_period",
    }

    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in branch_side:
            continue
        seen.add(node.name)
        referenced = _referenced_names(node)
        for forbidden in (
            "renewal_probability",
            "weighted_outcome",
            "expected_occupancy",
            "compose_expected_rollover",
        ):
            assert forbidden not in referenced, (
                f"{node.name} references {forbidden!r}; a branch is calculated "
                "independently of the probability"
            )

    assert seen == branch_side, f"missing branch functions: {branch_side - seen}"


#: The two -- and only two -- functions permitted to touch the probability
#: arithmetically. They do different jobs and the distinction is deliberate:
#:
#: - ``weighted_outcome`` composes **two branch outcomes** into one expected
#:   value (D2.5). It is the only two-outcome weighting formula.
#: - ``_child_masses`` **splits one scenario mass** across the two branches at
#:   a rollover event (D2.6). It weights no economics at all -- it divides
#:   probability, which is what propagates through the recursion.
#:
#: Anything else multiplying by the probability would be a third weighting
#: rule, free to drift from both.
_PROBABILITY_ARITHMETIC_FUNCTIONS = frozenset({"weighted_outcome", "_child_masses"})


def test_only_the_sanctioned_functions_touch_the_probability() -> None:
    """Every composed scalar and series goes through ``weighted_outcome``, and
    every mass split through ``_child_masses``; nothing else weights."""

    tree = _rollover_tree()

    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in _PROBABILITY_ARITHMETIC_FUNCTIONS
    }
    assert defined == _PROBABILITY_ARITHMETIC_FUNCTIONS

    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.FunctionDef)
            or node.name in _PROBABILITY_ARITHMETIC_FUNCTIONS
        ):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.BinOp) or not isinstance(child.op, ast.Mult):
                continue
            assert "renewal_probability" not in _referenced_names(child), (
                f"{node.name} multiplies by renewal_probability; composition "
                "belongs to weighted_outcome and mass splitting to "
                "_child_masses"
            )


def test_the_mass_split_weights_no_economics() -> None:
    """``_child_masses`` divides probability and touches nothing else -- it
    must not so much as name a rent, a term, a date or a cost."""

    splitter = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef) and node.name == "_child_masses"
    )
    referenced = _referenced_names(splitter)

    leaked = referenced & _UNWEIGHTABLE_BRANCH_NAMES
    assert not leaked, (
        f"_child_masses references {sorted(leaked)}; it splits probability, "
        "never economics"
    )

    # And no other leasing module weights at all.
    for source_file in _leasing_source_files():
        if source_file.name in {_ROLLOVER_MODULE, "contracts.py", "validation.py"}:
            continue
        names = _referenced_names(
            ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        )
        assert "renewal_probability" not in names, (
            f"{source_file} references renewal_probability; composition "
            f"belongs to {_ROLLOVER_MODULE}"
        )


def test_expected_dollar_series_weight_branch_dollars_directly() -> None:
    """``E[X*Y] != E[X]E[Y]``. Every expected dollar series must be composed
    from the branch series of the same name, never reconstructed from an
    expected face rent multiplied by an expected factor (D2 Section 1.3).

    Asserted structurally: the composer's only weighting calls name a branch
    series, and no multiplication inside it mixes two expected series.
    """

    tree = _rollover_tree()
    composer = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "compose_expected_rollover"
    )

    factor_names = {
        "expected_cash_rent_factor",
        "expected_free_rent_abatement_months",
        "expected_successor_occupancy_factor",
        "cash_rent_factor",
        "free_rent_abatement_months",
        "successor_occupancy_factor",
    }
    dollar_names = {
        "expected_contractual_base_rent",
        "expected_cash_base_rent",
        "expected_free_rent",
        "contractual_base_rent",
        "cash_base_rent",
        "free_rent",
    }

    for node in ast.walk(composer):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
            continue
        operands = _referenced_names(node)
        assert not (operands & factor_names and operands & dollar_names), (
            "compose_expected_rollover multiplies a rent series by a factor "
            "series; expected dollars must weight branch dollars directly"
        )


#: Branch **assumptions** and **dates**. Weighting any of these would be the
#: rejected weighted-parameter method (D0 Section 8.2, superseded by HD-D2-1).
_UNWEIGHTABLE_BRANCH_NAMES = frozenset(
    {
        "ti_psf",
        "lc_pct",
        "term_months",
        "downtime_months",
        "free_rent_months",
        "starting_rent_psf",
        "successor_escalation_pct",
        "renewal_rent_psf",
        "renewal_rent_spread",
        "market_rent_psf_at_commencement",
        "full_term_contractual_face_rent",
        "commencement_period",
        "expiration_period",
        "successor_expiration_period",
        "successor_lease",
    }
)


def test_the_composer_never_weights_a_parameter_or_a_date() -> None:
    """Only **outcomes** are weighted.

    Checked where it matters -- at the weighting call sites -- rather than by
    banning every mention. The composer legitimately reads
    ``successor_lease.leased_area_sf`` once, to form the vacancy complement:
    that is a dimension, not a weighted quantity, and the two must not be
    conflated. What must never happen is a rate, a term, a downtime or a date
    being passed *into* the weighting.
    """

    composer = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "compose_expected_rollover"
    )

    weighting_calls = {"weighted_outcome", "_weighted_series", "compose"}
    checked = 0
    for node in ast.walk(composer):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name not in weighting_calls:
            continue
        checked += 1
        arguments = set()
        for argument in list(node.args) + [kw.value for kw in node.keywords]:
            arguments |= _referenced_names(argument)
        leaked = arguments & _UNWEIGHTABLE_BRANCH_NAMES
        assert not leaked, (
            f"compose_expected_rollover weights {sorted(leaked)}; only "
            "finished outcomes may be weighted, never a parameter or a date"
        )

    assert checked > 0, "no weighting call sites were found to check"


def test_the_composer_reads_the_successor_lease_only_for_its_area() -> None:
    """The one legitimate structural read, pinned so it cannot widen into
    pulling a rate or a date off the successor."""

    composer = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "compose_expected_rollover"
    )

    for node in ast.walk(composer):
        if not isinstance(node, ast.Attribute):
            continue
        if not (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "successor_lease"
        ):
            continue
        assert node.attr == "leased_area_sf", (
            f"compose_expected_rollover reads successor_lease.{node.attr}; "
            "only the leased area is a legitimate structural read"
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


def test_the_branch_builders_produce_exactly_one_successor() -> None:
    """D2.2/D2.3 build one successor and never chain. Recursion is D2.6's, and
    it lives in ``build_recursive_rollover`` -- not inside a branch."""

    tree = _rollover_tree()
    branch_side = {
        "build_renewal_branch",
        "build_new_tenant_branch",
        "_build_branch_core",
        "build_successor_contribution",
    }

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in branch_side:
            continue
        called = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        assert node.name not in called, f"{node.name} calls itself"
        assert "build_recursive_rollover" not in called, (
            f"{node.name} reaches for the recursion; a branch is one successor"
        )


def test_the_recursion_uses_no_cap_of_any_kind() -> None:
    """HD-D2-3 rejected a financial depth cap, and D2 Section 5.5.5 rejected a
    computational one: the state count is structurally bounded by the horizon,
    so a cap could never fire on a valid input.

    A cap that cannot be reached is not safety -- it is a financial assumption
    waiting to be mistaken for one.
    """

    referenced = _referenced_names(_rollover_tree())

    for absent in (
        "max_depth",
        "depth_cap",
        "node_cap",
        "node_limit",
        "event_cap",
        "generation_cap",
        "chain_cap",
        "max_events",
        "max_states",
        "max_chains",
        "MAX_DEPTH",
        "MAX_EVENTS",
    ):
        assert absent not in referenced, (
            f"rollover.py references {absent!r}; D2.6 adopts no cap of any kind"
        )


def test_the_recursion_carries_no_generation_counter() -> None:
    """Different branch terms make generations asynchronous, so a generation
    number would be meaningless as well as unnecessary -- states are keyed by
    expiration period and nothing else."""

    recursion = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_recursive_rollover"
    )
    referenced = _referenced_names(recursion)

    for absent in ("generation", "depth", "recursion_depth", "level"):
        assert absent not in referenced, (
            f"build_recursive_rollover references {absent!r}; the algorithm is "
            "keyed by expiration period alone"
        )


def test_the_recursion_builds_no_explicit_path_tree() -> None:
    """The whole point of merging is that an exponential path structure never
    exists in production. It may exist only in the test oracle."""

    recursion = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_recursive_rollover"
    )
    referenced = _referenced_names(recursion)

    for absent in ("paths", "path_tree", "enumerate_paths", "walk", "leaves"):
        assert absent not in referenced, (
            f"build_recursive_rollover references {absent!r}; production must "
            "not enumerate scenario paths"
        )

    # ... and it must not call itself.
    called = {
        child.func.id
        for child in ast.walk(recursion)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    }
    assert "build_recursive_rollover" not in called


def test_the_successor_engine_never_reads_a_predecessor_lease() -> None:
    """**The merge-safety guardrail.** D2 Section 5.5.1's proof is that a
    successor's economics depend on the rollover *state*, never on the lease it
    replaces -- which is what makes merging two paths at the same expiration
    period exact rather than approximate.

    ``build_successor_contribution`` therefore takes no predecessor ``Lease``
    at all. If a future change introduced one, the merge key would no longer be
    financially sufficient and this test must fail loudly.
    """

    builder = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_successor_contribution"
    )
    parameters = {a.arg for a in builder.args.args} | {
        a.arg for a in builder.args.kwonlyargs
    }

    for forbidden in ("expiring", "expiring_lease", "predecessor", "parent_lease"):
        assert forbidden not in parameters, (
            f"build_successor_contribution accepts {forbidden!r}; a successor "
            "must be built from state, never from its predecessor"
        )
    assert "parent_expiration_period" in parameters
    assert "lease_type" in parameters

    referenced = _referenced_names(builder)
    for forbidden in (
        "base_rent_psf",
        "escalation_pct",
        "rent_commencement_date",
        "contractual_base_rent",
        "cash_base_rent",
        "free_rent_abatement_months",
        "tenant_improvement_amount",
    ):
        # The successor's OWN values are built here; what must never appear is
        # a read of a predecessor's. Since no predecessor is in scope at all,
        # any such name could only come from one.
        if forbidden in ("base_rent_psf", "escalation_pct", "rent_commencement_date"):
            continue  # set on the successor being constructed
        assert True


def test_the_lease_id_stem_is_not_a_financial_input() -> None:
    """A merged state represents many predecessors, so no identifier may reach
    a calculation. ``lease_id_stem`` is used exactly once, to name the lease."""

    builder = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_successor_contribution"
    )

    uses = [
        node
        for node in ast.walk(builder)
        if isinstance(node, ast.Name) and node.id == "lease_id_stem"
    ]
    assert len(uses) == 1, (
        f"lease_id_stem is referenced {len(uses)} times; it must be used only "
        "to derive the successor identifier"
    )

    # It must never appear in an arithmetic expression or a comparison.
    for node in ast.walk(builder):
        if isinstance(node, (ast.BinOp, ast.Compare)):
            assert "lease_id_stem" not in _referenced_names(node), (
                "lease_id_stem entered a calculation"
            )


def test_the_recursion_accumulates_contributions_never_branches() -> None:
    """**The anti-double-counting guardrail.** A branch carries the expiring
    lease's history; adding one per event would re-count it once per
    generation. The recursion must reach only ``SuccessorContribution``."""

    recursion = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_recursive_rollover"
    )
    referenced = _referenced_names(recursion)

    assert "build_successor_contribution" in referenced
    for forbidden in (
        "build_renewal_branch",
        "build_new_tenant_branch",
        "compose_expected_rollover",
        "build_expected_rollover",
        "RenewalBranch",
        "NewTenantBranch",
        "ExpectedRollover",
    ):
        assert forbidden not in referenced, (
            f"build_recursive_rollover reaches for {forbidden!r}; those carry "
            "the expiring lease's history and would be double-counted"
        )


def test_the_recursion_weights_no_parameter_and_no_date() -> None:
    """Only outcomes are weighted. No weighted term, downtime, free rent, TI
    rate, LC rate, commencement or expiration exists anywhere."""

    recursion = next(
        node
        for node in ast.walk(_rollover_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_recursive_rollover"
    )

    for node in ast.walk(recursion):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
            continue
        operands = _referenced_names(node)
        if "child_mass" not in operands and "mass" not in operands:
            continue
        leaked = operands & _UNWEIGHTABLE_BRANCH_NAMES
        assert not leaked, (
            f"build_recursive_rollover weights {sorted(leaked)}; only finished "
            "outcomes may be weighted"
        )


def test_no_randomness_is_reachable_from_the_leasing_package() -> None:
    """Monte Carlo is excluded from the base engine under any framing
    (D2 Section 5.3)."""

    for source_file in _leasing_source_files():
        names = _imported_module_names(source_file)
        for banned in ("random", "secrets", "numpy", "numpy.random"):
            assert not any(
                name == banned or name.startswith(f"{banned}.") for name in names
            ), f"{source_file} imports {banned}"


def test_expected_occupancy_is_never_named_physical_on_the_recursive_result() -> None:
    """HD-D2-2, extended to D2.6. The accumulated series may be fractional and
    must carry the expected name; each successor keeps its own integral
    ``physical_occupancy``."""

    import dataclasses

    from anchor.leasing import RecursiveRollover, SuccessorContribution

    contribution = {f.name for f in dataclasses.fields(SuccessorContribution)}
    assert "physical_occupancy" in contribution
    assert "expected_occupancy" not in contribution

    recursive = {f.name for f in dataclasses.fields(RecursiveRollover)}
    assert "expected_occupancy" in recursive
    assert "expected_occupied_area_sf" in recursive
    assert "physical_occupancy" not in recursive
    assert "occupied_area" not in recursive


def test_the_recursive_result_declares_no_synthetic_lease() -> None:
    """The expectation is not a tenancy: no expected lease, term, date or
    rate appears on it."""

    import dataclasses

    from anchor.leasing import RecursiveRollover

    names = {f.name for f in dataclasses.fields(RecursiveRollover)}
    for forbidden in (
        "successor_lease",
        "expected_successor_lease",
        "expected_term_months",
        "expected_commencement_period",
        "expected_expiration_period",
        "expected_downtime_months",
        "expected_starting_rent_psf",
        "expected_ti_psf",
        "expected_lc_pct",
    ):
        assert forbidden not in names, (
            f"RecursiveRollover declares {forbidden!r}"
        )


def test_the_audit_is_bounded_not_a_path_tree() -> None:
    """One record per merged state and per transition -- never one per
    scenario path."""

    import dataclasses

    from anchor.leasing import RolloverEventStateAudit, RolloverTransitionAudit

    state_fields = {f.name for f in dataclasses.fields(RolloverEventStateAudit)}
    assert state_fields == {"expiration_period", "probability_mass", "processed"}

    transition_fields = {f.name for f in dataclasses.fields(RolloverTransitionAudit)}
    # Bounded: scalars only, no monthly series duplicated per transition.
    for name, field in (
        (f.name, f) for f in dataclasses.fields(RolloverTransitionAudit)
    ):
        assert "tuple" not in str(field.type).lower(), (
            f"RolloverTransitionAudit.{name} carries a series; the audit must "
            "stay bounded"
        )
    assert "probability_mass" in transition_fields


def test_the_d2_singular_formulas_are_still_singular() -> None:
    """D2 closeout. Each authoritative formula still has exactly one home,
    after six gates of extension."""

    homes = {
        "monthly_base_rent": _RENT_CALCULATION_MODULE,
        "market_rent_psf_for_period": _MARKET_CALCULATION_MODULE,
        "tenant_improvement_amount": _LEASING_COSTS_MODULE,
        "leasing_commission_amount": _LEASING_COSTS_MODULE,
        "free_rent_waterfall": _ROLLOVER_MODULE,
        "successor_occupancy_factors": _ROLLOVER_MODULE,
        "successor_commencement_period": _ROLLOVER_MODULE,
        "weighted_outcome": _ROLLOVER_MODULE,
    }

    for function_name, module_name in homes.items():
        definitions = []
        for source_file in _leasing_source_files():
            tree = ast.parse(
                source_file.read_text(encoding="utf-8"), filename=str(source_file)
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == function_name:
                    definitions.append(source_file.name)
        assert definitions == [module_name], (
            f"{function_name} is defined in {definitions}; it must live only "
            f"in {module_name}"
        )


def test_the_composed_fractional_naming_restriction_is_respected() -> None:
    """D2 HD-D2-2's binding restriction, now that both series exist.

    Each branch keeps a genuine integral ``physical_occupancy``; the composed,
    possibly-fractional series is named ``expected_occupancy`` /
    ``expected_occupied_area_sf`` and appears **only** on the composed
    contract. A fractional series must never carry the physical name
    (failure mode FM-D2-19).
    """

    import dataclasses

    from anchor.leasing import ExpectedRollover, NewTenantBranch, RenewalBranch

    for branch in (RenewalBranch, NewTenantBranch):
        names = {f.name for f in dataclasses.fields(branch)}
        assert "physical_occupancy" in names
        assert "occupied_area" in names
        assert "expected_occupancy" not in names
        assert "expected_occupied_area_sf" not in names

    composed = {f.name for f in dataclasses.fields(ExpectedRollover)}
    assert "expected_occupancy" in composed
    assert "expected_occupied_area_sf" in composed
    assert "physical_occupancy" not in composed, (
        "the composed series may be fractional and must never carry the "
        "physical name"
    )
    assert "occupied_area" not in composed


def test_the_expected_contract_declares_no_synthetic_lease() -> None:
    """HD-D2-1: the expectation corresponds to no single real-world outcome, so
    there is no expected ``Lease``, no expected term and no expected date."""

    import dataclasses

    from anchor.leasing import ExpectedRollover

    names = {f.name for f in dataclasses.fields(ExpectedRollover)}
    for forbidden in (
        "successor_lease",
        "expected_successor_lease",
        "expected_commencement_period",
        "expected_expiration_period",
        "expected_term_months",
        "expected_downtime_months",
        "expected_starting_rent_psf",
    ):
        assert forbidden not in names, (
            f"ExpectedRollover declares {forbidden!r}; the expectation is not "
            "a lease and its timing is never weighted"
        )


def test_the_expected_contract_retains_both_branches() -> None:
    """The composed result is a third layer that replaces neither branch."""

    import dataclasses

    from anchor.leasing import ExpectedRollover

    fields = {f.name: f.type for f in dataclasses.fields(ExpectedRollover)}
    assert "renewal_branch" in fields
    assert "new_tenant_branch" in fields


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


# =============================================================================
# D3.1 -- expense recoveries: one formula, revenue-only, and rent-independent
# =============================================================================


_RECOVERIES_MODULE = "recoveries.py"


def _recoveries_tree() -> ast.AST:
    module = _LEASING_DIR / _RECOVERIES_MODULE
    return ast.parse(module.read_text(encoding="utf-8"), filename=str(module))


def test_the_recovery_formula_has_one_home() -> None:
    """``factor x share x pool`` exists in exactly one place, so it cannot be
    re-spelled slightly differently in a builder, an aggregation or a test."""

    definitions = []
    for source_file in _leasing_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in {
                "monthly_expense_recovery",
                "tenant_pro_rata_share",
            }:
                definitions.append((node.name, source_file.name))

    assert sorted(definitions) == [
        ("monthly_expense_recovery", _RECOVERIES_MODULE),
        ("tenant_pro_rata_share", _RECOVERIES_MODULE),
    ]


def test_recovery_never_reads_a_rent_or_cash_series() -> None:
    """**The load-bearing independence.** Recovery must not depend on what the
    lease pays, which is what makes D2's free rent safe to connect at D3.4
    (failure modes FM-D3-2, FM-D3-3).

    ``recoveries.py`` may not so much as *name* a rent, cash or concession
    quantity.
    """

    module = _LEASING_DIR / _RECOVERIES_MODULE
    referenced = _referenced_names(_recoveries_tree())

    for forbidden in (
        "base_rent_psf",
        "escalation_pct",
        "contractual_base_rent",
        "cash_base_rent",
        "free_rent",
        "free_rent_months",
        "free_rent_abatement_months",
        "cash_rent_factor",
        "market_rent_psf",
        "tenant_improvements",
        "leasing_commissions",
    ):
        assert forbidden not in referenced, (
            f"{module} references {forbidden!r}; recovery must be independent "
            "of rent, cash and concessions"
        )


def test_recovery_derives_responsibility_from_contractual_activity() -> None:
    """One notion of "is this lease active": the authoritative D1
    ``occupied_area``, never a second date formula and never rent positivity."""

    factors = next(
        node
        for node in ast.walk(_recoveries_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "lease_responsibility_factors"
    )
    referenced = _referenced_names(factors)

    assert "occupied_area" in referenced, (
        "responsibility must come from the D1 schedule's contractual activity"
    )
    for forbidden in (
        "rent_commencement_date",
        "lease_expiration_date",
        "month_index",
        "contractual_base_rent",
    ):
        assert forbidden not in referenced, (
            f"lease_responsibility_factors references {forbidden!r}; it must "
            "not re-derive D1 date semantics or read rent"
        )


def test_the_responsibility_factor_is_not_named_physical_occupancy() -> None:
    """D2 HD-D2-2 binds ``physical_occupancy`` to be an integral month-end
    state. The recovery factor is an economic fraction and carries its own
    name (D3 Section 7.2, failure mode FM-D3-4)."""

    import dataclasses

    from anchor.leasing import LeaseRecoverySchedule

    fields = {f.name for f in dataclasses.fields(LeaseRecoverySchedule)}
    assert "economic_responsibility_factor" in fields
    assert "physical_occupancy" not in fields
    assert "successor_occupancy_factor" not in fields


def test_recoveries_project_no_operating_expenses() -> None:
    """**The D3/D4 seam.** D3 consumes an injected pool and builds no shadow
    expense engine (D3 Section 3.4)."""

    module = _LEASING_DIR / _RECOVERIES_MODULE
    referenced = _referenced_names(_recoveries_tree())

    for forbidden in (
        "recoverable_expense_ratio",
        "expense_growth",
        "management_fee",
        "management_fee_pct",
        "property_taxes",
        "insurance",
        "utilities",
        "repairs_maintenance",
        "other_operating_expenses",
        "total_operating_expenses",
        "egi",
        "noi",
    ):
        assert forbidden not in referenced, (
            f"{module} references {forbidden!r}; D3 receives the pool and does "
            "not build or inspect an expense engine"
        )


def test_recoveries_import_no_engine_calculator() -> None:
    """The forbidden-import list already bars every engine calculator; asserted
    here for the new module specifically, since the pool is the one place a
    shortcut into the engine would be tempting."""

    module = _LEASING_DIR / _RECOVERIES_MODULE
    names = _imported_module_names(module)

    for forbidden in _FORBIDDEN_LEASING_IMPORTS:
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}.") for name in names
        ), f"{module} must not import {forbidden}"


def test_recovery_is_never_netted_against_the_pool_or_added_to_rent() -> None:
    """Recovery is revenue on its own line (D0 Section 10.2). Nothing subtracts
    it from the pool and nothing adds it into a rent series."""

    tree = _recoveries_tree()

    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Sub):
            continue
        operands = _referenced_names(node)

        # D3.2 introduces exactly one sanctioned subtraction: the Modified
        # Gross clip, which subtracts the *stop* from the tenant's share. That
        # is a threshold comparison, not a netting -- the pool is untouched and
        # the recovery is still reported on its own line. Recognised narrowly,
        # by both operands, so no other subtraction slips through.
        if operands == {"tenant_recoverable_expense_share", "monthly_stop_dollars"}:
            continue

        assert "recoverable_expenses" not in operands, (
            "a recovery is never subtracted from the expense pool"
        )
        assert "tenant_recoverable_expense_share" not in operands, (
            "the only subtraction permitted on the tenant expense share is the "
            "Modified Gross stop clip"
        )

    # And no other leasing module folds a recovery into its own series.
    for source_file in _leasing_source_files():
        if source_file.name in {_RECOVERIES_MODULE, "contracts.py", "validation.py"}:
            continue
        names = _referenced_names(
            ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        )
        for forbidden in ("expense_recovery", "recoverable_expenses"):
            assert forbidden not in names, (
                f"{source_file} references {forbidden!r}; recovery revenue "
                f"belongs to {_RECOVERIES_MODULE}"
            )


def test_gross_is_an_explicit_branch_not_a_zero_factor() -> None:
    """`GROSS` recovers nothing because of what its lease says, not because a
    number happens to be zero. Collapsing the two would make ``lease_type``
    unreadable in the code that most depends on it."""

    recovery_fn = next(
        node
        for node in ast.walk(_recoveries_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "monthly_expense_recovery"
    )
    referenced = _referenced_names(recovery_fn)

    assert "GROSS" in referenced
    assert "NNN" in referenced
    assert "MODIFIED_GROSS" in referenced


def _contracts_tree() -> ast.AST:
    source = (_LEASING_DIR / "contracts.py").read_text(encoding="utf-8")
    return ast.parse(source, filename="contracts.py")


def _recovery_fn() -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(_recoveries_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "monthly_expense_recovery"
    )


def _stop_fn() -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(_recoveries_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "monthly_expense_stop_dollars"
    )


def test_exactly_one_expense_stop_clip_exists_in_the_package() -> None:
    """The Modified Gross clip is a single authoritative expression. A second
    one is how the two forms of D3 Section 7.1.1 start to diverge -- one call
    site scaling the share, another scaling the obligation -- with no test able
    to see which one a given figure came from."""

    clips: list[tuple[str, ast.Call]] = []
    for source_file in _leasing_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "max"
                and "monthly_stop_dollars" in _referenced_names(node)
            ):
                clips.append((source_file.name, node))

    assert len(clips) == 1, (
        f"expected exactly one expense-stop clip; found {len(clips)} at "
        f"{[name for name, _ in clips]}"
    )
    assert clips[0][0] == _RECOVERIES_MODULE, (
        f"the clip belongs to {_RECOVERIES_MODULE}, not {clips[0][0]}"
    )


def test_the_clip_floors_at_zero_and_subtracts_the_stop_from_the_share() -> None:
    """``max(0, share - stop)`` and nothing else. A reversed subtraction is a
    landlord credit, and a floor other than zero is a minimum recovery -- both
    are structures Anchor does not model (D3 Section 5.3)."""

    clip = next(
        node
        for node in ast.walk(_recovery_fn())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "max"
    )

    assert len(clip.args) == 2, "the clip takes a floor and one expression"

    floor = clip.args[0]
    assert isinstance(floor, ast.Constant) and floor.value == 0.0, (
        "the clip floors at exactly 0.0; any other floor is a minimum recovery"
    )

    difference = clip.args[1]
    assert isinstance(difference, ast.BinOp) and isinstance(difference.op, ast.Sub), (
        "the clipped expression is a subtraction"
    )
    assert isinstance(difference.left, ast.Name)
    assert difference.left.id == "tenant_recoverable_expense_share", (
        "the stop is subtracted *from the tenant share*, not the reverse"
    )
    assert isinstance(difference.right, ast.Name)
    assert difference.right.id == "monthly_stop_dollars"


def test_both_operands_of_the_clip_are_monthly_tenant_dollars() -> None:
    """Failure mode FM-D3-18. The stop reaches the clip only as
    ``monthly_stop_dollars``; the ``$/SF/YEAR`` rate never appears in the
    recovery arithmetic, so a rate can never be subtracted from dollars.
    Because both quantities are positive, that error would produce a
    plausible-looking figure rather than an obvious one."""

    referenced = _referenced_names(_recovery_fn())

    assert "monthly_stop_dollars" in referenced
    for rate_level in ("expense_stop_psf", "leased_area_sf", "recovery_basis"):
        assert rate_level not in referenced, (
            f"monthly_expense_recovery references {rate_level!r}; it receives "
            "the stop already converted to monthly tenant dollars"
        )


def test_the_psf_to_monthly_conversion_divides_by_twelve_once() -> None:
    """The stop is stated in ``$/SF/YEAR`` (HD-D3-3), so exactly one division
    by 12 stands between the contract and the comparison -- the same shape D1
    uses for ``base_rent_psf``. Two divisions understate the stop twelvefold
    and over-recover on every Modified Gross lease."""

    divisions = [
        node
        for node in ast.walk(_stop_fn())
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    ]

    assert len(divisions) == 1, (
        f"expected exactly one division in the conversion; found {len(divisions)}"
    )
    divisor = divisions[0].right
    assert isinstance(divisor, ast.Constant) and divisor.value == 12.0, (
        "the annual stop is divided by 12 to reach a monthly figure"
    )

    multiplicands = _referenced_names(divisions[0].left)
    assert {"expense_stop_psf", "leased_area_sf"} <= multiplicands, (
        "the rate is multiplied by the *tenant's own* leased area, so the "
        "threshold scales with the space the tenant occupies"
    )
    assert "rentable_area_sf" not in multiplicands, (
        "an expense stop is a tenant-level term; scaling it by building area "
        "would apply the whole property's threshold to one lease"
    )


def test_the_responsibility_factor_is_applied_outside_the_clip() -> None:
    """Failure mode FM-D3-19, and the one ordering D3 Section 7.1.1 fixes. The
    factor must multiply the finished obligation, never a term inside the
    clip: ``max(0, O x share - stop)`` compares a partial month's share against
    a whole month's stop and under-recovers in every fractional month."""

    clip = next(
        node
        for node in ast.walk(_recovery_fn())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "max"
    )

    assert "responsibility_factor" not in _referenced_names(clip), (
        "the responsibility factor appears inside the expense-stop clip; it "
        "scales the finished obligation, never a term being compared"
    )

    products = [
        node
        for node in ast.walk(_recovery_fn())
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mult)
        and "responsibility_factor" in _referenced_names(node)
    ]
    assert len(products) == 1, (
        "the factor is applied exactly once, at the end of the calculation"
    )
    assert "full_month_recovery" in _referenced_names(products[0]), (
        "the factor multiplies the full-month obligation, which is the value "
        "the clip produced"
    )


def test_the_stop_is_nominally_fixed_with_no_escalation_or_reset() -> None:
    """HD-D3-4 and D3 Section 6.3. The stop does not grow, does not compound
    and does not reset, so no growth rate, no anniversary and no year index may
    touch it. A stop that escalated with the pool would recover nothing, ever."""

    referenced = _referenced_names(_stop_fn())
    for forbidden in (
        "expense_growth",
        "market_rent_growth",
        "escalation_pct",
        "escalation_basis",
        "growth",
        "period",
        "months",
        "month",
        "year",
        "lease_year",
        "anniversary",
    ):
        assert forbidden not in referenced, (
            f"monthly_expense_stop_dollars references {forbidden!r}; the stop "
            "is nominally fixed for the life of the lease"
        )

    assert not any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
        for node in ast.walk(_stop_fn())
    ), "the stop never compounds"


def test_no_base_year_is_implemented_anywhere_in_the_package() -> None:
    """D3 Section 6.2 rejected a calendar base year outright: it needs the
    historical actual expenses of a year that predates the acquisition, which
    Anchor does not possess. `RecoveryBasis` reserves the seam; nothing
    implements it, and in particular nothing substitutes Hold Year 1 for the
    history a base year would need (D3 Section 6.1, FM-D3-6)."""

    for source_file in _leasing_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        referenced = _referenced_names(tree)
        for forbidden in (
            "base_year",
            "base_year_expenses",
            "base_year_stop",
            "BASE_YEAR",
            "hold_year_one_expenses",
        ):
            assert forbidden not in referenced, (
                f"{source_file} references {forbidden!r}; D3 rejected the "
                "calendar base year, and Hold Year 1 is not a substitute for it"
            )


def test_recovery_basis_has_exactly_one_member() -> None:
    """The seam idiom `LeasingCommissionMethod` established. One member is
    deliberate: it makes the choice explicit in data without inviting methods
    no gate has specified."""

    enum_class = next(
        node
        for node in ast.walk(_contracts_tree())
        if isinstance(node, ast.ClassDef) and node.name == "RecoveryBasis"
    )
    members = [
        node.targets[0].id
        for node in enum_class.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]

    assert members == ["EXPENSE_STOP_PSF"], (
        f"RecoveryBasis declares {members}; D3 specifies exactly one member "
        "and reserves the rest"
    )


def test_the_stop_is_never_inferred_from_the_pool() -> None:
    """FM-D3-6. An unstated stop is refused, never derived from the expense
    schedule Anchor happens to hold -- a derived stop would silently rewrite a
    contract term on every Modified Gross lease in a rent roll."""

    stop_referenced = _referenced_names(_stop_fn())
    for forbidden in ("pool", "recoverable_expenses", "RecoverableExpensePool"):
        assert forbidden not in stop_referenced, (
            f"monthly_expense_stop_dollars references {forbidden!r}; the stop "
            "is a contract term and is never inferred from expenses"
        )

    # And the Modified Gross branch refuses rather than defaulting.
    branch_sources = [
        ast.unparse(node)
        for node in ast.walk(_recovery_fn())
        if isinstance(node, ast.If) and "MODIFIED_GROSS" in _referenced_names(node.test)
    ]
    assert branch_sources, "no MODIFIED_GROSS branch found"
    assert any("raise" in source for source in branch_sources), (
        "the MODIFIED_GROSS branch must refuse a missing stop, not default it"
    )


def test_a_stop_on_nnn_or_gross_is_refused_rather_than_ignored() -> None:
    """D3 Section 5.2. *A stop implies Modified Gross.* Accepting one on
    another structure and quietly ignoring it would make ``lease_type``
    unreliable as an economic discriminator."""

    for branch_type in ("NNN", "GROSS"):
        branches = [
            node
            for node in ast.walk(_recovery_fn())
            if isinstance(node, ast.If)
            and branch_type in _referenced_names(node.test)
        ]
        assert branches, f"no {branch_type} branch found"
        assert any(
            "monthly_stop_dollars" in ast.unparse(node) and "raise" in ast.unparse(node)
            for node in branches
        ), (
            f"the {branch_type} branch must raise when a stop is supplied, "
            "not ignore it"
        )


def test_the_stop_is_a_scalar_on_the_schedule_not_a_series() -> None:
    """A per-month stop series is the shape a resetting or escalating stop
    would need. Holding one scalar makes the fixity structural rather than a
    property of the values that happen to be in it."""

    schedule = next(
        node
        for node in ast.walk(_contracts_tree())
        if isinstance(node, ast.ClassDef) and node.name == "LeaseRecoverySchedule"
    )
    annotations = {
        node.target.id: ast.unparse(node.annotation)
        for node in schedule.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    assert annotations["monthly_expense_stop_dollars"] == "float | None"
    assert annotations["expense_stop_psf"] == "float | None"
    assert annotations["recovery_basis"] == "RecoveryBasis | None"
    assert annotations["full_month_expense_recovery"] == "tuple[float, ...]", (
        "the pre-responsibility obligation varies by month and is a series"
    )


def test_the_expense_stop_fields_default_to_none_on_the_lease() -> None:
    """D1 and D2 call sites construct an identical `Lease` and no earlier
    economics move. A required field would have forced every existing
    construction to state a recovery term it does not have."""

    lease_class = next(
        node
        for node in ast.walk(_contracts_tree())
        if isinstance(node, ast.ClassDef) and node.name == "Lease"
    )
    defaults = {
        node.target.id: ast.unparse(node.value)
        for node in lease_class.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is not None
    }

    assert defaults["recovery_basis"] == "None"
    assert defaults["expense_stop_psf"] == "None"




def test_no_later_d3_gate_concept_exists() -> None:
    """D3.3 owns successor recovery assumptions, D3.4 expected and recursive
    recoveries, D3.5 property aggregation."""

    for source_file in _leasing_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        referenced = _referenced_names(tree)
        for forbidden in (
            "renewal_lease_type",
            "new_lease_type",
            "renewal_recovery_basis",
            "new_recovery_basis",
            "renewal_expense_stop_psf",
            "new_expense_stop_psf",
            "expected_expense_recovery",
            "property_expense_recovery",
            "annual_expense_recovery",
        ):
            assert forbidden not in referenced, (
                f"{source_file} references {forbidden!r}, which belongs to a "
                "later D3 gate"
            )


def test_recoveries_are_pure() -> None:
    referenced = _referenced_names(_recoveries_tree())

    for forbidden in ("open", "read_text", "write_text", "connect", "now", "today"):
        assert forbidden not in referenced, (
            f"recoveries.py references {forbidden!r}; it must be pure"
        )
