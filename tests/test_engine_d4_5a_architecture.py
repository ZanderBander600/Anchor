"""Sprint D Gate D4.5A -- the generic engine stays generic.

Thirty-five guardrails, restating
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 17.6, 22 and 27.4.

The channel's whole point is that the shared acquisition engine gains a
below-NOI cash-flow input **without** learning what a Suite, a Lease or a
rollover is. These tests assert that structurally, so the boundary cannot erode
by ordinary editing.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
_ENGINE_DIR = _SRC_DIR / "anchor" / "engine"
_ANALYSIS_DIR = _SRC_DIR / "anchor" / "analysis"


def _engine_source_files() -> list[Path]:
    return sorted(_ENGINE_DIR.glob("*.py"))


def _imported_module_names(source_file: Path) -> list[str]:
    """Absolute dotted names for every import, relative ones resolved."""

    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    package = f"anchor.{source_file.parent.name}"
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                module = node.module or ""
            elif node.level == 1:
                module = f"{package}.{node.module}" if node.module else package
            else:
                module = f"anchor.{node.module}" if node.module else "anchor"
            names.append(module)
            names.extend(f"{module}.{alias.name}" for alias in node.names)
    return names


def _tree(source_file: Path) -> ast.AST:
    return ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))


def _referenced_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _function(source_file: Path, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(_tree(source_file))
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


_ACQUISITION = _ENGINE_DIR / "acquisition.py"
_RETURNS = _ENGINE_DIR / "returns.py"
_DEBT = _ENGINE_DIR / "debt.py"
_CONTRACTS = _ENGINE_DIR / "contracts.py"


# =============================================================================
# Guardrails 1-6 -- the engine never learns what produced the dollars
# =============================================================================


@pytest.mark.parametrize(
    "source_file", _engine_source_files(), ids=lambda p: p.name
)
def test_no_engine_module_imports_anchor_leasing(source_file: Path) -> None:
    """**Guardrails 1 and 6.** The integration direction is
    ``anchor.analysis -> anchor.leasing``; the engine is below both."""

    names = _imported_module_names(source_file)

    assert not any(
        name == "anchor.leasing" or name.startswith("anchor.leasing.")
        for name in names
    ), f"{source_file.name} imports anchor.leasing"


def test_importing_the_engine_does_not_pull_in_leasing() -> None:
    """A fresh-interpreter check: no transitive dependency either."""

    environment = os.environ.copy()
    parts = [str(_SRC_DIR)]
    if existing := environment.get("PYTHONPATH"):
        parts.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(parts)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import anchor.engine.acquisition; "
            "assert 'anchor.leasing' not in sys.modules",
        ],
        capture_output=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr.decode()


#: Lease-level vocabulary the generic engine must never contain. The channel
#: carries dollars; what produced them is the caller's business.
_LEASE_LEVEL_NAMES = (
    "Suite",
    "suite_id",
    "suite_area_sf",
    "Lease",
    "lease_id",
    "lease_type",
    "LeaseType",
    "rollover",
    "renewal_probability",
    "market_rent_psf",
    "free_rent",
    "expense_recovery",
    "recoverable_expenses",
    "RecoverableExpensePool",
    "MonthlyPropertyProjection",
    "AnnualOperatingProjection",
    "PropertyOperatingSchedule",
    "PropertyRecoverySchedule",
    "LeaseLevelOperatingInputs",
    "ModelMonth",
    "hold_year",
    "is_forward_exit_month",
    "exit_window_leasing_costs",
)


@pytest.mark.parametrize(
    "source_file", _engine_source_files(), ids=lambda p: p.name
)
def test_no_engine_module_names_a_lease_level_concept(source_file: Path) -> None:
    """**Guardrails 2, 3, 4, 5 and 29.** Including the forward window: the
    engine receives ``H`` hold-year values and has no concept of a month after
    the sale."""

    referenced = _referenced_names(_tree(source_file))

    leaked = referenced & set(_LEASE_LEVEL_NAMES)
    assert not leaked, (
        f"{source_file.name} references {sorted(leaked)}; the shared engine is "
        "operating-mode agnostic and knows only annual dollars"
    )


# =============================================================================
# Guardrails 7-11 -- the contract is generic and absence is absence
# =============================================================================


def test_the_operating_capital_schedule_is_a_generic_engine_contract() -> None:
    """**Guardrail 7.** It lives in the engine's own contracts module and names
    only its two components."""

    from anchor.engine.contracts import OperatingCapitalSchedule

    fields = [field.name for field in dataclasses.fields(OperatingCapitalSchedule)]
    assert fields == [
        "tenant_improvements_by_year",
        "leasing_commissions_by_year",
    ]

    node = next(
        candidate
        for candidate in ast.walk(_tree(_CONTRACTS))
        if isinstance(candidate, ast.ClassDef)
        and candidate.name == "OperatingCapitalSchedule"
    )
    referenced = _referenced_names(node)
    for forbidden in ("Suite", "Lease", "ModelMonth", "hold_year"):
        assert forbidden not in referenced


def test_the_existing_entry_points_remain_callable_without_the_channel() -> None:
    """**Guardrail 8.** The new parameter is optional and last."""

    import inspect

    from anchor.engine.acquisition import (
        analyze_acquisition,
        analyze_acquisition_from_operating_projection,
        analyze_detailed_acquisition,
        analyze_detailed_acquisition_with_projection,
    )

    signature = inspect.signature(analyze_acquisition_from_operating_projection)
    parameters = list(signature.parameters.values())
    assert [p.name for p in parameters] == [
        "operating_projection",
        "terms",
        "operating_capital",
    ]
    assert parameters[-1].default is None

    # The public mode entry points take no operating capital at all.
    for entry_point in (
        analyze_acquisition,
        analyze_detailed_acquisition,
        analyze_detailed_acquisition_with_projection,
    ):
        assert "operating_capital" not in inspect.signature(entry_point).parameters


def test_absence_takes_the_zero_path_through_one_authority() -> None:
    """**Guardrail 9.** ``None`` materialises zeros in exactly one place."""

    helper = _function(_ACQUISITION, "calculate_operating_capital_by_year")
    referenced = _referenced_names(helper)

    assert "operating_capital" in referenced
    assert any(
        isinstance(node, ast.Compare)
        and any(isinstance(op, ast.Is) for op in node.ops)
        for node in ast.walk(helper)
    ), "the helper must branch on `operating_capital is None`"


@pytest.mark.parametrize(
    "entry_point", ["analyze_acquisition", "analyze_detailed_acquisition_with_projection"]
)
def test_quick_and_detailed_pass_no_synthetic_schedule(entry_point: str) -> None:
    """**Guardrails 10 and 11.** Neither mode constructs a zero schedule; they
    simply do not pass the argument."""

    function = _function(_ACQUISITION, entry_point)
    referenced = _referenced_names(function)

    assert "OperatingCapitalSchedule" not in referenced, (
        f"{entry_point} constructs an operating-capital schedule; Quick and "
        "Detailed pass nothing at all"
    )
    assert "operating_capital" not in referenced


# =============================================================================
# Guardrails 12-21 -- what the channel must not touch
# =============================================================================


def test_operating_capital_never_reaches_the_noi_series() -> None:
    """**Guardrail 12.** The engine consumes completed NOI."""

    orchestrator = _function(
        _ACQUISITION, "analyze_acquisition_from_operating_projection"
    )

    for node in ast.walk(orchestrator):
        if not isinstance(node, ast.BinOp):
            continue
        operands = _referenced_names(node)
        if "noi_by_year" in operands:
            pytest.fail("NOI is arithmetically combined with something")


def test_operating_capital_never_reaches_dscr_or_debt_yield() -> None:
    """**Guardrails 13 and 14.** A lender's coverage test is an NOI test."""

    for name in (
        "calculate_dscr_by_year",
        "calculate_headline_dscr",
        "calculate_min_dscr",
        "calculate_year_1_debt_yield",
    ):
        function = _function(_RETURNS, name)
        referenced = _referenced_names(function)
        for forbidden in (
            "operating_capital",
            "operating_capital_by_year",
            "tenant_improvements_by_year",
            "leasing_commissions_by_year",
        ):
            assert forbidden not in referenced, (
                f"{name} references {forbidden!r}; DSCR and debt yield are "
                "NOI-based by convention"
            )

    import inspect

    from anchor.engine.returns import (
        calculate_dscr_by_year,
        calculate_year_1_debt_yield,
    )

    for function in (calculate_dscr_by_year, calculate_year_1_debt_yield):
        assert "operating_capital_by_year" not in inspect.signature(function).parameters


def test_operating_capital_never_reaches_the_debt_module() -> None:
    """**Guardrail 15.** No new borrowing, no larger balance."""

    referenced = _referenced_names(_tree(_DEBT))

    for forbidden in (
        "operating_capital",
        "OperatingCapitalSchedule",
        "tenant_improvements_by_year",
        "leasing_commissions_by_year",
    ):
        assert forbidden not in referenced, f"debt.py references {forbidden!r}"


def test_operating_capital_never_reaches_the_exit_calculations() -> None:
    """**Guardrails 16, 17 and 18.** A final-year TI cheque reduces the
    seller's cash flow, never the capitalized value."""

    for name in (
        "calculate_exit_value",
        "calculate_disposition_costs",
        "calculate_net_sale_proceeds",
    ):
        referenced = _referenced_names(_function(_ACQUISITION, name))
        for forbidden in (
            "operating_capital",
            "operating_capital_by_year",
            "tenant_improvements_by_year",
            "leasing_commissions_by_year",
        ):
            assert forbidden not in referenced, f"{name} references {forbidden!r}"


def test_operating_capital_never_reaches_the_capital_stack() -> None:
    """**Guardrails 19 and 20.** A Year-1 TI cheque is not a T0 cost."""

    referenced = _referenced_names(_tree(_ENGINE_DIR / "debt.py"))
    assert "operating_capital" not in referenced

    for name in (
        "calculate_acquisition_costs",
        "calculate_financing_fee",
        "calculate_initial_equity",
        "calculate_capital_stack",
    ):
        function = _function(_DEBT, name)
        assert "operating_capital" not in _referenced_names(function)


def test_operating_capital_is_separate_from_capex() -> None:
    """**Guardrail 21.** Two channels, additive, never merged.
    ``capex_by_year`` keeps reporting the reserve alone."""

    capex = _function(_ACQUISITION, "calculate_capex_by_year")
    referenced = _referenced_names(capex)

    for forbidden in (
        "operating_capital",
        "tenant_improvements_by_year",
        "leasing_commissions_by_year",
    ):
        assert forbidden not in referenced, (
            f"calculate_capex_by_year references {forbidden!r}; the CapEx "
            "reserve is its own authority"
        )

    helper = _function(_ACQUISITION, "calculate_operating_capital_by_year")
    assert "capex" not in _referenced_names(helper)
    assert "annual_capex_reserve" not in _referenced_names(helper)


# =============================================================================
# Guardrails 22-28 -- where it does reach, and exactly once
# =============================================================================


@pytest.mark.parametrize(
    "name",
    [
        "calculate_unlevered_cash_flows",
        "calculate_levered_cash_flows",
    ],
)
def test_the_cash_flow_builders_subtract_operating_capital(name: str) -> None:
    """**Guardrails 22 and 23.**"""

    referenced = _referenced_names(_function(_ACQUISITION, name))

    assert "operating_capital_by_year" in referenced
    assert "operating_capital" in referenced


@pytest.mark.parametrize(
    "name",
    [
        "calculate_recurring_unlevered_cash_flows",
        "calculate_recurring_levered_cash_flows",
    ],
)
def test_the_recurring_series_subtract_operating_capital(name: str) -> None:
    """**Guardrail 26**, and HD-D4-3: the owner-return series."""

    referenced = _referenced_names(_function(_RETURNS, name))

    assert "operating_capital" in referenced


def test_returns_are_not_patched_independently_of_the_cash_flows() -> None:
    """**Guardrails 24 and 25.** IRR, equity multiple and the owner metrics
    consume already-assembled series; none of them names the channel."""

    for name in (
        "calculate_irr",
        "calculate_equity_multiple",
        "calculate_return_metrics",
    ):
        referenced = _referenced_names(_function(_RETURNS, name))
        for forbidden in (
            "operating_capital",
            "operating_capital_by_year",
            "OperatingCapitalSchedule",
        ):
            assert forbidden not in referenced, (
                f"{name} references {forbidden!r}; it must derive from the "
                "authoritative cash-flow series alone"
            )


def test_the_annual_total_has_exactly_one_authority() -> None:
    """**Guardrail 27.** ``TI + LC`` is summed in one place; no consumer
    re-adds the components."""

    # The components may be read under their field names or under a local
    # alias, so both spellings count as "a component" here.
    tenant_improvement_names = {"tenant_improvements_by_year", "tenant_improvements"}
    leasing_commission_names = {"leasing_commissions_by_year", "leasing_commissions"}

    offenders = []
    for source_file in (_ACQUISITION, _RETURNS):
        for node in ast.walk(_tree(source_file)):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name == "calculate_operating_capital_by_year":
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.BinOp) or not isinstance(
                    inner.op, ast.Add
                ):
                    continue
                operands = _referenced_names(inner)
                if (operands & tenant_improvement_names) and (
                    operands & leasing_commission_names
                ):
                    offenders.append((source_file.name, node.name))

    assert not offenders, (
        f"TI is added to LC outside the authoritative helper, in {offenders}; "
        "the annual total has one authority"
    )

    # And the authority itself performs exactly one addition.
    helper = _function(_ACQUISITION, "calculate_operating_capital_by_year")
    helper_additions = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
    ]
    assert len(helper_additions) == 1, (
        f"the helper performs {len(helper_additions)} additions; it sums the "
        "two components once"
    )
    operands = _referenced_names(helper_additions[0])
    assert operands & tenant_improvement_names
    assert operands & leasing_commission_names


def test_operating_capital_is_subtracted_at_most_once_per_series() -> None:
    """**Guardrail 27**, the double-count half."""

    for source_file, name in (
        (_ACQUISITION, "calculate_unlevered_cash_flows"),
        (_ACQUISITION, "calculate_levered_cash_flows"),
        (_RETURNS, "calculate_recurring_unlevered_cash_flows"),
        (_RETURNS, "calculate_recurring_levered_cash_flows"),
    ):
        function = _function(source_file, name)
        subtractions = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Sub)
            and "operating_capital" in _referenced_names(node.right)
        ]
        # The two acquisition builders have a mid-hold and a final-year branch;
        # the two recurring builders have one expression.
        expected = 2 if source_file is _ACQUISITION else 1
        assert len(subtractions) == expected, (
            f"{name} subtracts operating capital {len(subtractions)} times, "
            f"expected {expected}"
        )


def test_the_final_year_keeps_both_the_outflow_and_the_sale() -> None:
    """**Guardrail 28.** Operating capital reduces the recurring portion; the
    sale term is added separately and is never netted against it."""

    for name, sale_term in (
        ("calculate_unlevered_cash_flows", "exit_value"),
        ("calculate_levered_cash_flows", "net_sale_proceeds"),
    ):
        function = _function(_ACQUISITION, name)
        source = ast.unparse(function)
        assert "operating_capital[hold_period - 1]" in source, (
            f"{name} drops final-year operating capital"
        )
        assert sale_term in source


# =============================================================================
# Guardrails 30-35 -- nothing from a later gate leaked in
# =============================================================================


def test_no_lease_level_validation_reaches_the_engine() -> None:
    """**Guardrail 30.** The non-positive forward exit NOI rule is a
    Lease-Level integration check and is D4.5B's."""

    for source_file in _engine_source_files():
        referenced = _referenced_names(_tree(source_file))
        assert "NON_POSITIVE_FORWARD_EXIT_NOI" not in referenced


def test_calculate_exit_value_is_unchanged_in_behaviour() -> None:
    """**Guardrail 31.** No global rejection of a non-positive NOI: Quick and
    Detailed behaviour is frozen."""

    from anchor.engine.acquisition import calculate_exit_value

    assert calculate_exit_value(exit_noi=-100.0, exit_cap_rate=0.05) == -2_000.0
    assert calculate_exit_value(exit_noi=0.0, exit_cap_rate=0.05) == 0.0

    function = _function(_ACQUISITION, "calculate_exit_value")
    for node in ast.walk(function):
        if isinstance(node, ast.Compare):
            pytest.fail("calculate_exit_value branches on a value; it must not")


def test_the_lease_level_operating_mode_is_published_and_the_engine_stays_mode_blind() -> None:
    """**Guardrail 32, succeeded at D5.1A.**

    D4.5B deliberately withheld the ``OperatingMode`` member because every
    consumer branched ``is DETAILED`` / ``is QUICK`` with an implicit else, so
    publishing it would have made ``POST /analyze`` accept ``"lease_level"`` and
    silently run it as Quick. D5.1A removed that hazard first -- every audited
    backend dispatch site is now total -- and only then published the member.
    The precondition the old guardrail protected is satisfied, not waived; see
    ``tests/test_d5_1a_operating_mode_total_dispatch.py``.

    What this guardrail still asserts, and the reason it lives in the *engine*
    architecture file, is unchanged and is not about the enum's size: the shared
    acquisition engine remains **mode-blind**. It has never named an
    ``OperatingMode`` and must not start, because all three modes converge on
    one ``analyze_acquisition``/``AcquisitionResults`` -- that convergence is
    what makes a third mode an integration question rather than a financial one.
    """

    from anchor.contracts import OperatingMode

    assert {member.value for member in OperatingMode} == {
        "quick",
        "detailed",
        "lease_level",
    }

    # The engine never dispatches on, or even names, an operating mode.
    for source_file in sorted(_ENGINE_DIR.rglob("*.py")):
        if "__pycache__" in str(source_file):
            continue
        text = source_file.read_text(encoding="utf-8")
        assert "OperatingMode" not in text, (
            f"{source_file.name} names OperatingMode; the shared engine must "
            "stay mode-blind so all three modes keep converging on one "
            "acquisition calculation"
        )


def test_the_orchestration_module_is_outside_the_engine() -> None:
    """**Guardrail 33**, narrowed at D4.5B.

    The orchestration module now exists. What D4.5A asserted -- that no
    Lease-Level orchestration lives in ``anchor.engine`` -- is unchanged, and
    is now also asserted in the other direction: the bridge sits in
    ``anchor.analysis`` and the engine does not know its name.
    """

    assert (_ANALYSIS_DIR / "lease_level.py").exists()

    for source_file in _engine_source_files():
        names = _imported_module_names(source_file)
        assert not any(
            name.startswith("anchor.analysis") for name in names
        ), f"{source_file.name} imports the analysis layer"
        assert "analyze_lease_level_acquisition_with_projection" not in (
            source_file.read_text(encoding="utf-8")
        ), f"{source_file.name} names the Lease-Level orchestrator"


def test_no_monthly_return_engine_exists() -> None:
    """**Guardrail 34.** The shared returns engine is annual; D4.4 already
    performed the monthly-to-annual transformation."""

    for source_file in _engine_source_files():
        referenced = _referenced_names(_tree(source_file))
        for forbidden in ("ModelMonth", "monthly_irr", "monthly_cash_flows"):
            assert forbidden not in referenced, (
                f"{source_file.name} references {forbidden!r}"
            )

    helper = _function(_ACQUISITION, "calculate_operating_capital_by_year")
    for node in ast.walk(helper):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            pytest.fail("operating capital is divided; D4.4 supplies annual values")


def test_quick_and_detailed_producers_are_untouched() -> None:
    """**Guardrail 35.** The channel is downstream of both producers; neither
    module knows it exists."""

    for source_file in (_ENGINE_DIR / "noi.py", _ENGINE_DIR / "operating_projection.py"):
        referenced = _referenced_names(_tree(source_file))
        for forbidden in (
            "operating_capital",
            "OperatingCapitalSchedule",
            "tenant_improvements_by_year",
            "leasing_commissions_by_year",
        ):
            assert forbidden not in referenced, (
                f"{source_file.name} references {forbidden!r}"
            )
