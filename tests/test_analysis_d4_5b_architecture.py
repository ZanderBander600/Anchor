"""Sprint D Gate D4.5B -- three producers, one engine, one bridge.

Thirty-five guardrails, restating
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 27, 28 and 29.

D4.5B is the gate where Lease-Level finally reaches the acquisition engine, and
the whole design rests on that connection being made in exactly one place, by a
module that computes nothing. Two claims carry the sprint:

**One engine.** Quick, Detailed and Lease-Level converge on a single
``analyze_acquisition_from_operating_projection``. There is no Lease-Level IRR,
no Lease-Level DSCR and no second returns implementation to drift from the
first.

**No financial formula in the bridge.** ``analysis/lease_level.py`` selects
builders and passes completed contracts between them. If it contains
arithmetic, it has become a second place where money is computed -- so the
arithmetic itself is banned structurally rather than reviewed by eye.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
_ANCHOR_DIR = _SRC_DIR / "anchor"
_ENGINE_DIR = _ANCHOR_DIR / "engine"
_ANALYSIS_DIR = _ANCHOR_DIR / "analysis"
_LEASING_DIR = _ANCHOR_DIR / "leasing"

_ORCHESTRATOR = _ANALYSIS_DIR / "lease_level.py"
_ENVELOPE = _ANALYSIS_DIR / "contracts.py"

#: The D4.5A commit. Everything D4.5B touches lies above the engine, so the
#: engine and AI packages must still be identical to this tree.
_D4_5A_COMMIT = "964c9a7"

_ENTRY_POINT = "analyze_lease_level_acquisition_with_projection"


# =============================================================================
# Helpers
# =============================================================================


def _tree(source_file: Path) -> ast.Module:
    return ast.parse(
        source_file.read_text(encoding="utf-8"), filename=str(source_file)
    )


def _imported_module_names(source_file: Path) -> list[str]:
    """Absolute dotted names for every import, relative ones resolved."""

    tree = _tree(source_file)
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


def _referenced_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _called_function_names(node: ast.AST) -> list[str]:
    """Every call in source order, by the simple name being called."""

    calls: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                calls.append((child.lineno, func.id))
            elif isinstance(func, ast.Attribute):
                calls.append((child.lineno, func.attr))
    return [name for _, name in sorted(calls)]


def _first_call_line(node: ast.AST, name: str) -> int:
    lines = [
        child.lineno
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == name
    ]
    assert lines, f"{name} is never called"
    return min(lines)


def _entry_point_function() -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(_tree(_ORCHESTRATOR))
        if isinstance(node, ast.FunctionDef) and node.name == _ENTRY_POINT
    )


def _python_files_under(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _files_changed_since(commit: str, repo_relative: str) -> list[str]:
    """Paths under ``repo_relative`` that differ from ``commit``.

    ``git diff`` rather than a raw byte comparison against ``git show``: blobs
    are stored with LF and this working tree checks out CRLF, so comparing
    bytes would report every file as modified. Git applies the same
    normalisation it uses to decide whether a file is dirty, which is exactly
    the question being asked.
    """

    completed = subprocess.run(
        ["git", "diff", "--name-only", commit, "--", repo_relative],
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return [
        line.strip()
        for line in completed.stdout.decode().splitlines()
        if line.strip()
    ]


def _fresh_interpreter(statement: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    parts = [str(_SRC_DIR)]
    if existing := environment.get("PYTHONPATH"):
        parts.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(parts)
    return subprocess.run(
        [sys.executable, "-c", statement], capture_output=True, env=environment
    )


# =============================================================================
# Guardrails 1-6 -- the dependency direction (HD-D4-8)
# =============================================================================


@pytest.mark.parametrize(
    "source_file",
    _python_files_under(_ENGINE_DIR),
    ids=lambda path: path.name,
)
def test_g1_no_engine_module_imports_anchor_leasing(source_file: Path) -> None:
    """**Guardrail 1.** The direction is ``leasing -> analysis -> engine``, and
    the engine is the terminus. It never imports back."""

    names = _imported_module_names(source_file)
    assert not any(
        name == "anchor.leasing" or name.startswith("anchor.leasing.")
        for name in names
    ), f"{source_file.name} imports anchor.leasing"


def test_g2_the_engine_stays_leasing_free_in_a_fresh_interpreter() -> None:
    """**Guardrail 2.** Not just direct imports -- the engine must not acquire
    a leasing dependency transitively either."""

    completed = _fresh_interpreter(
        "import sys; import anchor.engine.acquisition, anchor.engine.returns, "
        "anchor.engine.debt; "
        "assert 'anchor.leasing' not in sys.modules, sorted(sys.modules)"
    )
    assert completed.returncode == 0, completed.stderr.decode()


def test_g3_the_bridge_depends_on_both_sides() -> None:
    """**Guardrail 3.** The positive half of the direction claim: importing the
    orchestrator pulls in leasing *and* the engine. A bridge that imported
    neither would satisfy every ban above while being no bridge at all."""

    completed = _fresh_interpreter(
        "import sys; import anchor.analysis.lease_level as m; "
        "assert 'anchor.leasing' in sys.modules; "
        "assert 'anchor.engine.acquisition' in sys.modules"
    )
    assert completed.returncode == 0, completed.stderr.decode()


@pytest.mark.parametrize(
    "source_file",
    _python_files_under(_LEASING_DIR),
    ids=lambda path: path.name,
)
def test_g4_no_leasing_module_imports_the_analysis_layer(source_file: Path) -> None:
    """**Guardrail 4.** No back-edge. The leasing package does not know its
    consumer exists."""

    names = _imported_module_names(source_file)
    assert not any(
        name == "anchor.analysis" or name.startswith("anchor.analysis.")
        for name in names
    ), f"{source_file.name} imports anchor.analysis"


def test_g5_the_bridge_reaches_no_delivery_layer() -> None:
    """**Guardrail 5.** The orchestrator is a domain module. It knows nothing
    about the web, the API, persistence, ingestion, deals or the AI analyst."""

    names = _imported_module_names(_ORCHESTRATOR)

    for forbidden in (
        "anchor.ai",
        "anchor.deals",
        "anchor.ingestion",
        "anchor.excel",
        "anchor.api",
        "anchor.persistence",
        "web",
        "fastapi",
        "sqlalchemy",
    ):
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}.") for name in names
        ), f"the orchestrator imports {forbidden!r}"


def test_g6_the_bridge_is_the_only_lease_level_orchestrator() -> None:
    """**Guardrail 6.** One bridge, not one per caller."""

    definitions = sorted(
        f"{path.relative_to(_SRC_DIR).as_posix()}::{node.name}"
        for path in _python_files_under(_ANCHOR_DIR)
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == _ENTRY_POINT
    )

    assert definitions == [f"anchor/analysis/lease_level.py::{_ENTRY_POINT}"]

    # Re-exporting it is fine; defining a second one is not. D4.6B adds one
    # legitimate consumer: Lease-Level sensitivity, whose entire correctness
    # claim is that it calls this exact entry point for every scenario rather
    # than reaching a builder or the engine directly. Importing the bridge is
    # what that guardrail *requires*, so the list is widened by exactly one
    # named file -- the ban on defining a second orchestrator is untouched.
    importers = sorted(
        path.relative_to(_SRC_DIR).as_posix()
        for path in _python_files_under(_ANCHOR_DIR)
        if any(
            name.endswith(f".{_ENTRY_POINT}")
            for name in _imported_module_names(path)
        )
    )
    # D5.3 adds the delivery layer. ``api.py`` calls the bridge exactly as
    # sensitivity does -- through the analysis facade, once per request, with no
    # builder or engine call of its own -- so it widens the *consumer* list by
    # one named file and leaves the ban on a second orchestrator untouched.
    assert importers == [
        "anchor/analysis/__init__.py",
        "anchor/analysis/lease_level_sensitivity.py",
        "anchor/api.py",
    ]


# =============================================================================
# Guardrails 7-13 -- no financial formula lives in the bridge
# =============================================================================


#: Arithmetic that would constitute a financial formula. ``ast.BitOr`` is
#: excluded deliberately: ``RecursiveRollover | InitialVacancyRollover`` is a
#: type union, not a calculation.
_ARITHMETIC_OPERATORS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Pow,
    ast.Mod,
)


def test_g7_the_bridge_contains_no_arithmetic() -> None:
    """**Guardrail 7.** The claim that carries the gate. Every number the
    orchestrator returns was computed by an authoritative builder upstream; if
    a ``+`` or ``*`` appears here, that stopped being true."""

    for node in ast.walk(_tree(_ORCHESTRATOR)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITHMETIC_OPERATORS):
            pytest.fail(
                f"line {node.lineno}: the orchestrator performs arithmetic "
                f"({type(node.op).__name__}); financial formulas belong to the "
                "builders it calls"
            )
        if isinstance(node, ast.AugAssign) and isinstance(
            node.op, _ARITHMETIC_OPERATORS
        ):
            pytest.fail(f"line {node.lineno}: the orchestrator accumulates a value")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            pytest.fail(f"line {node.lineno}: the orchestrator negates a value")


def test_g8_the_bridge_declares_no_numeric_literal() -> None:
    """**Guardrail 8.** No rate, no ratio, no month count, no divisor. A
    literal here would be an assumption invented at the integration layer."""

    for node in ast.walk(_tree(_ORCHESTRATOR)):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            pytest.fail(
                f"line {node.lineno}: the orchestrator declares the numeric "
                f"literal {node.value!r}"
            )


def test_g9_the_bridge_makes_no_numeric_comparison() -> None:
    """**Guardrail 9.** A threshold is a financial rule. The one financial
    condition at this boundary -- the exit-NOI refusal -- is delegated to
    ``require_capitalizable_exit_noi``, where it is stated once."""

    for node in ast.walk(_tree(_ORCHESTRATOR)):
        if isinstance(node, ast.Compare):
            for operator in node.ops:
                assert isinstance(operator, (ast.Is, ast.IsNot, ast.In, ast.NotIn)), (
                    f"line {node.lineno}: the orchestrator compares values with "
                    f"{type(operator).__name__}; thresholds belong in validation"
                )


def test_g10_the_bridge_uses_no_financial_vocabulary() -> None:
    """**Guardrail 10.** Not one name in the module belongs to the returns
    domain. Reading the source, there is nowhere for a return metric to be
    computed or adjusted."""

    referenced = _referenced_names(_tree(_ORCHESTRATOR))

    for forbidden in (
        "irr",
        "levered_irr",
        "unlevered_irr",
        "equity_multiple",
        "dscr",
        "dscr_by_year",
        "debt_yield",
        "exit_value",
        "loan_amount",
        "annual_debt_service",
        "cash_on_cash",
        "npv",
        "discount_rate",
    ):
        assert forbidden not in referenced, (
            f"the orchestrator references {forbidden!r}; returns are the shared "
            "engine's, computed once"
        )


def test_g11_the_bridge_defines_exactly_one_function() -> None:
    """**Guardrail 11.** No private helper, because a private helper in this
    module is where a formula would hide."""

    definitions = [
        node.name
        for node in ast.walk(_tree(_ORCHESTRATOR))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    assert definitions == [_ENTRY_POINT]


def test_g12_the_bridge_declares_no_module_level_state() -> None:
    """**Guardrail 12.** No cache, no default assumption, no mutable module
    global -- so two runs cannot differ by history."""

    assignments = [
        target.id
        for node in _tree(_ORCHESTRATOR).body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    ]

    assert assignments == [], f"the orchestrator declares module state: {assignments}"


def test_g13_no_assumption_has_a_default() -> None:
    """**Guardrail 13.** Every input is supplied by the caller. A default
    ``market_leasing`` or ``operating_inputs`` would let an analysis run on
    assumptions nobody stated."""

    from anchor.analysis import analyze_lease_level_acquisition_with_projection

    signature = inspect.signature(analyze_lease_level_acquisition_with_projection)

    for name, parameter in signature.parameters.items():
        assert parameter.default is inspect.Parameter.empty, (
            f"parameter {name!r} has the default {parameter.default!r}"
        )


# =============================================================================
# Guardrails 14-21 -- every step delegates, exactly once
# =============================================================================


#: The authoritative builder for each step, and the number of times the
#: orchestrator may invoke it. Two calls to a pool builder would mean two
#: pools; two calls to the engine would mean two answers.
_SINGLE_CALL_AUTHORITIES = (
    "build_model_months",
    "build_property_expense_schedule",
    "build_recoverable_expense_pool",
    "build_property_operating_schedule",
    "build_property_recovery_schedule",
    "build_monthly_property_projection",
    "aggregate_monthly_to_annual",
    "require_capitalizable_exit_noi",
    "analyze_acquisition_from_operating_projection",
    "OperatingCapitalSchedule",
    "LeaseLevelAcquisitionResults",
)


@pytest.mark.parametrize("authority", _SINGLE_CALL_AUTHORITIES)
def test_g14_each_authority_is_invoked_exactly_once(authority: str) -> None:
    """**Guardrail 14.**"""

    calls = _called_function_names(_entry_point_function())

    assert calls.count(authority) == 1, (
        f"{authority} is called {calls.count(authority)} times; exactly one "
        "invocation is the whole point"
    )


def test_g15_exactly_one_recoverable_pool_can_exist() -> None:
    """**Guardrail 15.** The single-pool claim, structurally: the pool builder
    is called once, outside every loop."""

    function = _entry_point_function()
    pool_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_recoverable_expense_pool"
    ]
    assert len(pool_calls) == 1

    for loop in ast.walk(function):
        if isinstance(loop, (ast.For, ast.While)):
            for node in ast.walk(loop):
                if node is pool_calls[0]:
                    pytest.fail("the recoverable pool is built inside a loop")


def test_g16_the_terminal_check_precedes_the_engine() -> None:
    """**Guardrail 16.** Ordering is the safety property: a non-positive
    forward NOI must be refused *before* anything is capitalized, not
    afterwards with the result discarded."""

    function = _entry_point_function()

    assert _first_call_line(function, "require_capitalizable_exit_noi") < (
        _first_call_line(function, "analyze_acquisition_from_operating_projection")
    )


def test_g17_validation_runs_upstream_first() -> None:
    """**Guardrail 17.** A malformed rent roll is never reported as a valuation
    problem, because the rent-roll validator runs before the timeline is even
    built."""

    function = _entry_point_function()

    rent_roll = _first_call_line(function, "require_valid_lease_level_inputs")
    vacancy = _first_call_line(function, "require_valid_initial_vacancy_inputs")
    association = _first_call_line(
        function, "require_valid_lease_level_acquisition_leases"
    )
    timeline = _first_call_line(function, "build_model_months")
    terminal = _first_call_line(function, "require_capitalizable_exit_noi")

    assert rent_roll < vacancy < association < timeline < terminal


def test_g18_the_operating_capital_schedule_is_passed_through_unaltered() -> None:
    """**Guardrail 18.** The schedule is built from the annual projection's own
    arrays, by attribute access only. Any expression there would be a second
    place TI/LC are decided -- D4.4's reducer is the first and only one."""

    construction = next(
        node
        for node in ast.walk(_entry_point_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "OperatingCapitalSchedule"
    )

    assert not construction.args, "the schedule is built positionally"
    supplied = {keyword.arg for keyword in construction.keywords}
    assert supplied == {
        "tenant_improvements_by_year",
        "leasing_commissions_by_year",
    }

    for keyword in construction.keywords:
        value = keyword.value
        assert isinstance(value, ast.Attribute), (
            f"{keyword.arg} is computed, not passed through"
        )
        assert isinstance(value.value, ast.Name), f"{keyword.arg} is derived indirectly"
        assert value.attr == keyword.arg, (
            f"{keyword.arg} is populated from {value.attr!r}; TI and LC must not "
            "be crossed or substituted"
        )


def test_g19_the_engine_receives_the_annual_projection_itself() -> None:
    """**Guardrail 19.** No adapter object, no copy, no rebuilt tuple between
    D4.4's output and the engine's input -- so what the caller inspects is what
    was priced."""

    call = next(
        node
        for node in ast.walk(_entry_point_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "analyze_acquisition_from_operating_projection"
    )

    assert isinstance(call.args[0], ast.Name), (
        "the engine is handed an expression, not the annual projection itself"
    )


def test_g20_the_envelope_returns_the_objects_that_were_used() -> None:
    """**Guardrail 20.** Every field of the returned envelope is a bare local
    name -- the same instances the pipeline ran on."""

    construction = next(
        node
        for node in ast.walk(_entry_point_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "LeaseLevelAcquisitionResults"
    )

    assert not construction.args
    for keyword in construction.keywords:
        assert isinstance(keyword.value, ast.Name), (
            f"envelope field {keyword.arg!r} is computed at assembly time"
        )


def test_g21_no_exception_is_swallowed() -> None:
    """**Guardrail 21.** A validation error must reach the caller. Nothing
    partially populated, and no sentinel result, may be returned in its
    place."""

    for node in ast.walk(_tree(_ORCHESTRATOR)):
        if isinstance(node, (ast.Try, ast.ExceptHandler)):
            pytest.fail(f"line {node.lineno}: the orchestrator catches exceptions")

    returns = [
        node
        for node in ast.walk(_entry_point_function())
        if isinstance(node, ast.Return)
    ]
    assert len(returns) == 1, "there is more than one way out of the orchestrator"


# =============================================================================
# Guardrails 22-27 -- one engine, three producers
# =============================================================================


def test_g22_all_three_producers_reach_the_same_entry_point() -> None:
    """**Guardrail 22.** The convergence claim. Quick, Detailed and Lease-Level
    each call ``analyze_acquisition_from_operating_projection``; none of them
    has a returns path of its own."""

    from anchor.engine import acquisition

    source = (_ENGINE_DIR / "acquisition.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for producer in (
        "analyze_acquisition",
        "analyze_detailed_acquisition_with_projection",
    ):
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == producer
        )
        assert "analyze_acquisition_from_operating_projection" in (
            _called_function_names(function)
        ), f"{producer} does not use the shared engine"

    assert "analyze_acquisition_from_operating_projection" in (
        _called_function_names(_entry_point_function())
    )
    assert hasattr(acquisition, "analyze_acquisition_from_operating_projection")


def test_g23_only_one_function_computes_acquisition_returns() -> None:
    """**Guardrail 23.** No second engine anywhere in the tree."""

    definitions = sorted(
        f"{path.relative_to(_SRC_DIR).as_posix()}::{node.name}"
        for path in _python_files_under(_ANCHOR_DIR)
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.FunctionDef)
        and node.name.endswith("_from_operating_projection")
    )

    assert definitions == [
        "anchor/engine/acquisition.py::analyze_acquisition_from_operating_projection"
    ]


def test_g24_the_annual_projection_satisfies_the_seam_structurally() -> None:
    """**Guardrail 24.** ``AnnualOperatingProjection`` fits
    ``OperatingProjectionLike`` without inheriting it, importing it, or naming
    it -- which is what lets the engine stay ignorant of the leasing layer."""

    from anchor.engine.contracts import OperatingProjectionLike
    from anchor.leasing.contracts import AnnualOperatingProjection

    for attribute in ("noi_by_year", "exit_noi", "going_in_cap_rate"):
        assert attribute in AnnualOperatingProjection.__annotations__, (
            f"AnnualOperatingProjection lacks {attribute!r}"
        )

    assert OperatingProjectionLike not in AnnualOperatingProjection.__mro__
    leasing_names = _referenced_names(_tree(_LEASING_DIR / "contracts.py"))
    assert "OperatingProjectionLike" not in leasing_names


@pytest.mark.parametrize(
    "producer",
    ["NoiForecast", "OperatingProjection", "AnnualOperatingProjection"],
)
def test_g25_every_producer_exposes_the_same_three_members(producer: str) -> None:
    """**Guardrail 25.** The seam is three attributes wide for all three modes.
    A mode-specific fourth member would be a fork in the engine."""

    import anchor.engine.contracts as engine_contracts
    import anchor.leasing.contracts as leasing_contracts

    contract = getattr(engine_contracts, producer, None) or getattr(
        leasing_contracts, producer
    )
    annotations = contract.__annotations__

    for attribute in ("noi_by_year", "exit_noi", "going_in_cap_rate"):
        assert attribute in annotations, f"{producer} lacks {attribute!r}"


def test_g26_the_engine_names_no_lease_level_concept() -> None:
    """**Guardrail 26.** The channel carries dollars; what produced them is the
    caller's business."""

    lease_level_vocabulary = (
        "Suite",
        "suite_id",
        "Lease",
        "lease_id",
        "LeaseType",
        "rollover",
        "renewal_probability",
        "MonthlyPropertyProjection",
        "AnnualOperatingProjection",
        "LeaseLevelAcquisitionResults",
        "ModelMonth",
        "expense_recovery",
        "recoverable_expense_ratio",
    )

    for source_file in _python_files_under(_ENGINE_DIR):
        referenced = _referenced_names(_tree(source_file))
        for forbidden in lease_level_vocabulary:
            assert forbidden not in referenced, (
                f"{source_file.name} references {forbidden!r}"
            )


def test_g27_the_envelope_carries_no_return_metric() -> None:
    """**Guardrail 27.** ``AcquisitionResults`` is not re-wrapped, re-derived or
    partially restated. The envelope adds operating models beside it."""

    from anchor.analysis.contracts import LeaseLevelAcquisitionResults

    fields = {f.name: f.type for f in dataclasses.fields(LeaseLevelAcquisitionResults)}

    assert list(fields) == ["monthly_projection", "annual_projection", "results"]
    for forbidden in (
        "levered_irr",
        "unlevered_irr",
        "equity_multiple",
        "dscr_by_year",
        "exit_value",
        "loan_amount",
        "annual_debt_service",
        "noi_by_year",
    ):
        assert forbidden not in fields

    assert LeaseLevelAcquisitionResults.__dataclass_params__.frozen
    assert getattr(LeaseLevelAcquisitionResults, "__slots__", None) is not None
    assert LeaseLevelAcquisitionResults.__dataclass_params__.kw_only

    for node in ast.walk(_tree(_ENVELOPE)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITHMETIC_OPERATORS):
            pytest.fail("the envelope module performs arithmetic")


# =============================================================================
# Guardrails 28-32 -- the terminal-value rule, stated once
# =============================================================================


def test_g28_the_terminal_rule_lives_in_exactly_one_place() -> None:
    """**Guardrail 28.**"""

    definitions = sorted(
        f"{path.relative_to(_SRC_DIR).as_posix()}::{node.name}"
        for path in _python_files_under(_ANCHOR_DIR)
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.FunctionDef)
        and node.name
        in ("validate_capitalizable_exit_noi", "require_capitalizable_exit_noi")
    )

    assert definitions == [
        "anchor/leasing/validation.py::require_capitalizable_exit_noi",
        "anchor/leasing/validation.py::validate_capitalizable_exit_noi",
    ]


def test_g29_the_rule_is_an_error_not_a_warning() -> None:
    """**Guardrail 29.** HD-D4-7, as revised by the human financial review:
    warning-only treatment was rejected. A refused analysis raises."""

    from anchor.leasing.validation import (
        LeaseIssueCode,
        validate_capitalizable_exit_noi,
    )

    result = validate_capitalizable_exit_noi(-1.0)

    assert len(result.errors) == 1
    assert result.errors[0].code is LeaseIssueCode.NON_POSITIVE_FORWARD_EXIT_NOI
    assert not result.warnings
    assert validate_capitalizable_exit_noi(0.0).errors
    assert not validate_capitalizable_exit_noi(1.0).issues


def test_g30_the_engine_applies_no_terminal_floor() -> None:
    """**Guardrail 30.** The rejected alternatives -- a floor, a clamp, or a
    branch inside ``calculate_exit_value`` -- are all absent. Quick and Detailed
    keep their exact behaviour for a negative NOI."""

    function = next(
        node
        for node in ast.walk(_tree(_ENGINE_DIR / "acquisition.py"))
        if isinstance(node, ast.FunctionDef) and node.name == "calculate_exit_value"
    )

    for node in ast.walk(function):
        assert not isinstance(node, (ast.Compare, ast.If, ast.IfExp)), (
            "calculate_exit_value branches on a value"
        )
    referenced = _referenced_names(function)
    assert "max" not in referenced and "min" not in referenced


def test_g31_no_engine_module_knows_the_terminal_rule() -> None:
    """**Guardrail 31.** The check is scoped to the Lease-Level boundary, which
    is exactly why Quick and Detailed are provably unaffected by it."""

    for source_file in _python_files_under(_ENGINE_DIR):
        text = source_file.read_text(encoding="utf-8")
        for forbidden in (
            "NON_POSITIVE_FORWARD_EXIT_NOI",
            "require_capitalizable_exit_noi",
            "validate_capitalizable_exit_noi",
        ):
            assert forbidden not in text, f"{source_file.name} mentions {forbidden}"


def test_g32_the_public_operating_mode_enum_is_published_behind_total_dispatch() -> None:
    """**Guardrail 32, succeeded at D5.1A.**

    D4.5B refused to add ``OperatingMode.LEASE_LEVEL`` because every consumer
    branched ``is DETAILED`` / ``is QUICK`` with an implicit else: the member
    would not have created a third branch, it would have joined whichever branch
    the else happened to be, and ``POST /analyze`` would have answered
    ``"lease_level"`` with Quick economics under a Lease-Level label.

    The deferral was never "this member is undesirable"; it was "this member is
    unsafe *while dispatch is exhaustive-by-omission*". D5.1A removed the
    precondition rather than the intent, in that order -- total dispatch first,
    member second -- so the guardrail now asserts the state that makes
    publication safe rather than the absence that avoided the question.

    The three original parts are preserved, each in its succeeded form: the
    enum's exact membership, that ``OperatingMode.LEASE_LEVEL`` references are
    now legitimate but only inside dispatch, and the structural reading of the
    enum declaration. Exhaustiveness itself is proved in
    ``tests/test_d5_1a_operating_mode_total_dispatch.py``, which is the file
    this guardrail now depends on rather than duplicating.
    """

    from anchor.contracts import OperatingMode

    assert {member.value for member in OperatingMode} == {
        "quick",
        "detailed",
        "lease_level",
    }
    assert hasattr(OperatingMode, "LEASE_LEVEL")
    assert OperatingMode("lease_level") is OperatingMode.LEASE_LEVEL

    # Every module that names the member must be a dispatch consumer -- the
    # member exists to be branched on, never to be imported into the financial
    # layers, which stay mode-blind.
    permitted = {"api.py", "contracts.py", "store.py", "presentation.py"}
    for source_file in _python_files_under(_ANCHOR_DIR):
        if "OperatingMode.LEASE_LEVEL" not in source_file.read_text(encoding="utf-8"):
            continue
        assert source_file.name in permitted, (
            f"{source_file.name} names OperatingMode.LEASE_LEVEL; only the mode "
            "dispatch consumers may"
        )

    operating_mode_class = next(
        node
        for node in ast.walk(_tree(_ANCHOR_DIR / "contracts.py"))
        if isinstance(node, ast.ClassDef) and node.name == "OperatingMode"
    )
    declared = [
        target.id
        for node in operating_mode_class.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    ]
    assert declared == ["QUICK", "DETAILED", "LEASE_LEVEL"], declared


def test_g33_the_whole_engine_package_is_unchanged_since_d4_5a() -> None:
    """**Guardrail 33.** Quick and Detailed are not merely "believed unchanged"
    -- the entire engine package is identical to the D4.5A tree, every file of
    it. D4.5B is additive and sits above the engine; this is the complete proof
    of that, and it subsumes any per-function claim about ``noi.py`` or
    ``operating_projection.py``.
    """

    changed = _files_changed_since(_D4_5A_COMMIT, "src/anchor/engine")

    assert changed == [], (
        f"the engine changed at D4.5B: {changed}. The engine is frozen at this "
        "gate -- Lease-Level joins at the existing seam or not at all"
    )


def test_g34_the_ai_surface_changed_only_to_make_mode_dispatch_total() -> None:
    """**Guardrail 34, narrowed at D5.1A -- and not weakened.**

    The original asserted byte-identity of the whole ``src/anchor/ai`` tree
    since D4.5A. D5.1A must edit two files in that tree -- ``contracts.py`` and
    ``presentation.py`` -- because both carried ``if QUICK: ... else:
    <Detailed>`` dispatch, which is exactly the hazard this gate exists to
    close. Byte-identity is therefore no longer the right statement of the rule.

    What the guardrail was actually protecting was never the bytes: it was that
    **no Lease-Level AI presentation is smuggled in, and the TI/LC exclusion is
    neither widened nor reversed**. Both survive verbatim, now stated directly:
    the prompt surface is still byte-identical (D5.1A changes no prompt), and
    only the two dispatch files moved. D5.8 owns the presentation decision.
    """

    changed = _files_changed_since(_D4_5A_COMMIT, "src/anchor/ai")

    assert sorted(changed) == [
        "src/anchor/ai/contracts.py",
        "src/anchor/ai/presentation.py",
    ], (
        "the AI surface changed beyond D5.1A's authorised total-dispatch "
        f"conversion: {changed}"
    )

    # The prompts are untouched: D5.1A adds no mode vocabulary to the model.
    assert _files_changed_since(_D4_5A_COMMIT, "src/anchor/ai/prompts.py") == []

    # The D4.5A TI/LC exclusion stands exactly as authorised.
    from anchor.ai.presentation import INTENTIONALLY_EXCLUDED_RESULT_FIELDS

    assert INTENTIONALLY_EXCLUDED_RESULT_FIELDS == frozenset(
        {"tenant_improvements_by_year", "leasing_commissions_by_year"}
    )


def test_g35_the_ai_exclusion_decision_is_intact() -> None:
    """**Guardrail 35.** Stated behaviourally as well as by file identity: the
    two fields remain deliberately excluded, and no Lease-Level contract has
    been handed to the AI analyst."""

    from anchor.ai.presentation import INTENTIONALLY_EXCLUDED_RESULT_FIELDS

    assert {
        "tenant_improvements_by_year",
        "leasing_commissions_by_year",
    } <= INTENTIONALLY_EXCLUDED_RESULT_FIELDS

    # The AI layer legitimately consumes ``anchor.analysis`` for sensitivity
    # and break-even. What it must not reach is the Lease-Level layer: neither
    # the leasing package, nor the orchestrator, nor its result envelope.
    for source_file in _python_files_under(_ANCHOR_DIR / "ai"):
        names = _imported_module_names(source_file)
        for name in names:
            assert not name.startswith("anchor.leasing"), (
                f"{source_file.name} imports {name!r}"
            )
            assert not name.startswith("anchor.analysis.lease_level"), (
                f"{source_file.name} imports the Lease-Level orchestrator"
            )
            assert not name.endswith(_ENTRY_POINT), (
                f"{source_file.name} imports the Lease-Level entry point"
            )
            assert not name.endswith("LeaseLevelAcquisitionResults"), (
                f"{source_file.name} imports the Lease-Level envelope"
            )


# =============================================================================
# D4.5B closeout -- HD-D4-9: public Lease-Level mode publication deferred to D5
#
# The internal deterministic Lease-Level entry point is complete and callable
# through the analysis layer. What is deferred is *publication*: making
# "lease_level" a dispatchable public ``OperatingMode``.
#
# The reason is that dispatch across this codebase is exhaustive-by-omission.
# Every consumer tests one mode and lets the other fall through an implicit
# else. Adding a third member does not create a third branch -- it silently
# joins whichever branch the else happens to be, which differs by module: Quick
# in ``api.py``, Detailed in ``ai/presentation.py`` and ``deals/contracts.py``.
# A request that parsed as Lease-Level would then be answered with Quick
# numbers, under a Lease-Level label. Rejection is the safe state until D5
# publishes the mode atomically across every one of these sites.
# =============================================================================


def test_hd_d4_9_superseded_the_mode_is_published_and_parses_as_valid() -> None:
    """**HD-D4-9, discharged at D5.1A.**

    The enum was the gate: while ``lease_level`` named no member, no payload
    could carry it and no dispatch could mis-route it. That was a holding
    position, and D5.1A discharges it in the required order -- total dispatch
    first, member second.

    The successor invariant is the one that now matters, and it is a
    *distinction* rather than a refusal: ``"lease_level"`` parses as a valid
    mode, while an unknown token still does not. Collapsing the two would tell a
    caller that ``"lease_level"`` is not a mode, which stopped being true the
    moment the member was published. Whether any given endpoint *serves* the
    mode is a separate question, asserted in the endpoint matrix below.
    """

    from anchor.contracts import OperatingMode

    assert {member.value for member in OperatingMode} == {
        "quick",
        "detailed",
        "lease_level",
    }

    assert OperatingMode("lease_level") is OperatingMode.LEASE_LEVEL

    with pytest.raises(ValueError):
        OperatingMode("leaselevel")


def test_hd_d4_9_superseded_the_api_never_answers_lease_level_with_quick() -> None:
    """**The behavioural half, discharged at D5.3.**

    Until D5.3 this asserted a flat 422: the mode parsed but no endpoint
    served it. ``POST /analyze`` now *does* serve Lease-Level, so the outcome
    under test changes -- but the failure it was written to catch does not.
    That failure was never "a 200": it was **a 200 carrying Quick results**,
    an answer to a question nobody asked.

    Stated directly now. A Quick-shaped body labelled ``lease_level`` names
    none of the five Lease-Level input objects, so it must be refused for
    saying nothing the Lease-Level engine can read -- never quietly
    underwritten with ``current_noi`` and ``noi_growth``, which that engine
    does not have.
    """

    from fastapi.testclient import TestClient

    from anchor.api import app

    payload = {
        "purchase_price": 50_000_000,
        "current_noi": 2_500_000,
        "occupancy": 0.95,
        "noi_growth": 0.03,
        "hold_period": 5,
        "exit_cap_rate": 0.055,
        "ltv": 0.65,
        "interest_rate": 0.0525,
        "amortization": 30,
        "operating_mode": "lease_level",
    }

    response = TestClient(app).post("/analyze", json=payload)

    assert response.status_code == 422, (
        f"POST /analyze answered a Quick-shaped operating_mode='lease_level' "
        f"body with {response.status_code}; it names no Lease-Level inputs, so "
        "it must be refused rather than dispatched to Quick"
    )

    # The assertion that has always mattered: no Quick economics came back.
    assert "levered_irr" not in response.text
    assert "equity_multiple" not in response.text

    # And the refusal explains what is actually wrong -- a missing terms
    # object -- rather than claiming the mode is unsupported, which it no
    # longer is.
    assert "terms" in str(response.json()["detail"])


def test_hd_d4_9_superseded_analysis_is_wired_and_the_rest_still_is_not() -> None:
    """**HD-D4-9's anti-half-wiring rule, succeeded at D5.1A.**

    The original banned the strings ``LEASE_LEVEL``/``lease_level`` anywhere in
    the API, persistence, ingestion or AI surfaces, because at D4 *any* mention
    would have been half-wiring: publication was supposed to land atomically.

    D5.1A published the **mode vocabulary** and nothing else, so the string
    ban became the wrong instrument -- refusing a mode by name requires naming
    it. The intent was restated then as the thing that actually matters: no
    capability may leak in ahead of the gate that owns it.

    **Amended at D5.3** (analysis and sensitivity) and **D5.4** (persistence).
    The rule is a ledger rather than a ban: each gate adds exactly what it owns,
    and the surfaces no gate has reached must stay unreached. D5.8 owns AI, and
    it is asserted absent below.
    """

    surfaces = [
        _ANCHOR_DIR / "api.py",
        *(
            path
            for directory in ("ai", "deals", "ingestion")
            for path in _python_files_under(_ANCHOR_DIR / directory)
        ),
    ]

    # The delivery layer must still not construct leasing contracts itself,
    # and must still not reach the leasing package directly: the dependency
    # direction HD-D4-8 fixes is leasing -> analysis -> engine, so D5.3
    # reaches the parser and the runners through the analysis facade.
    # **Narrowed at D5.4.** Until then the delivery layer named no leasing
    # contract at all, and banning the names was a fair proxy for banning the
    # dependency. D5.4 persists Lease-Level deals as *typed* contracts, so
    # ``deals`` must name ``Suite`` and ``Lease`` -- storing them as untyped rows
    # or raw dicts is precisely what the gate forbids.
    #
    # The rule that survives is the dependency direction itself: those types
    # arrive through ``anchor.analysis``, never by importing ``anchor.leasing``,
    # so the leasing layer keeps exactly one door (HD-D4-8).
    forbidden_capability = ("anchor.leasing", "from ..leasing", "from .leasing")
    for source_file in surfaces:
        text = source_file.read_text(encoding="utf-8")
        for forbidden in forbidden_capability:
            assert forbidden not in text, (
                f"{source_file.name} imports {forbidden!r}; the delivery layer "
                "reaches leasing only through the anchor.analysis facade"
            )

    # D5.8: the AI layer may *name* the mode to refuse it -- D5.1A put explicit
    # Lease-Level arms in ``ai/contracts.py`` and ``ai/presentation.py`` for
    # exactly that -- but it must reach no Lease-Level capability.
    for source_file in _python_files_under(_ANCHOR_DIR / "ai"):
        text = source_file.read_text(encoding="utf-8")
        for forbidden in (
            "analyze_lease_level_acquisition_with_projection",
            "run_lease_level_one_way_sensitivity",
            "run_lease_level_two_way_sensitivity",
            "parse_lease_level_inputs",
            "LeaseLevelAcquisitionResults",
        ):
            assert forbidden not in text, (
                f"{source_file.name} reaches {forbidden}; D5.8 owns Lease-Level AI"
            )

    # D5.4 wired persistence. What must still be absent from the store is the
    # transport parser -- storage reads its own rows, and routing them through
    # the HTTP parser would couple the database format to the wire format so
    # neither could change alone -- and any cached Lease-Level financial result.
    store = (_ANCHOR_DIR / "deals" / "store.py").read_text(encoding="utf-8")
    assert "lease_level_deals" in store, "D5.4 should persist Lease-Level deals"
    assert "parse_lease_level_inputs" not in store, (
        "store.py must not depend on the HTTP transport parser"
    )
    for cached_result in (
        "LeaseLevelAcquisitionResults",
        "MonthlyPropertyProjection",
        "AnnualOperatingProjection",
    ):
        assert cached_result not in store, (
            f"store.py references {cached_result}; Lease-Level results are "
            "recomputed on open, never persisted (D5 decision A)"
        )
    assert "_SCHEMA_VERSION = 5" in store

    # D5.3 ledger: the API reaches exactly the approved entry points.
    api_text = (_ANCHOR_DIR / "api.py").read_text(encoding="utf-8")
    assert "case OperatingMode.LEASE_LEVEL:" in api_text
    assert "_unsupported_operating_mode" in api_text
    for wired in (
        "analyze_lease_level_acquisition_with_projection",
        "run_lease_level_one_way_sensitivity",
        "run_lease_level_two_way_sensitivity",
        "parse_lease_level_inputs",
    ):
        assert wired in api_text, f"D5.3 should wire {wired}"
    for not_yet in ("build_standard_lease_level", "lease_level_break_even"):
        assert not_yet not in api_text, f"{not_yet} belongs to no D5 gate"


def test_hd_d4_9_superseded_the_exhaustive_dispatch_hazard_is_closed() -> None:
    """**The trigger D4 armed, fired and discharged at D5.1A.**

    The original counted implicit two-mode dispatch sites and required at least
    eight, with this instruction to its future reader, quoted from the D4.5B
    source: *"If someone refactors these into exhaustive dispatch (a match
    statement, or an explicit else that raises), this test starts failing and
    the deferral can be revisited."*

    That is precisely what D5.1A did, so the test fired as designed and is
    inverted here rather than deleted. The hazard it recorded -- every mode
    comparison in these four modules being an identity test against a single
    member, which is what made a third member unsafe -- must now be **absent**.

    Kept deliberately narrow and independent of
    ``tests/test_d5_1a_operating_mode_total_dispatch.py``: that file proves
    exhaustiveness over the live enum, whereas this one preserves D4's own
    framing of the danger (single-member identity tests with a live fallthrough)
    so the historical record stays executable rather than becoming a comment.
    """

    surviving: list[str] = []

    for source_file in (
        _ANCHOR_DIR / "api.py",
        _ANCHOR_DIR / "ai" / "contracts.py",
        _ANCHOR_DIR / "ai" / "presentation.py",
        _ANCHOR_DIR / "deals" / "contracts.py",
    ):
        for node in ast.walk(_tree(source_file)):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not isinstance(test, ast.Compare):
                continue
            if not any(isinstance(op, ast.Is) for op in test.ops):
                continue
            names = _referenced_names(test)
            if not ({"QUICK", "DETAILED", "LEASE_LEVEL"} & names):
                continue

            # Walk to the end of the if/elif chain. The hazard is a *live*
            # fallthrough -- an ``else`` that does something other than raise,
            # meaning "every mode I did not name behaves like this one".
            tail = node
            while (
                tail.orelse
                and len(tail.orelse) == 1
                and isinstance(tail.orelse[0], ast.If)
            ):
                tail = tail.orelse[0]
            if not tail.orelse:
                continue
            if any(
                isinstance(stmt, ast.Raise)
                for stmt in ast.walk(ast.Module(body=tail.orelse, type_ignores=[]))
            ):
                continue
            surviving.append(f"{source_file.name}:{node.lineno}")

    assert surviving == [], (
        "the exhaustive-dispatch hazard HD-D4-9 recorded is back: these sites "
        "test one OperatingMode member and let every other member fall through "
        f"into that branch's sibling behavior: {surviving}"
    )


def test_hd_d4_9_the_internal_entry_point_is_nevertheless_complete() -> None:
    """Deferring publication defers *only* publication. The deterministic
    analysis is finished and reachable through the approved analysis layer."""

    import anchor.analysis as analysis

    assert hasattr(analysis, _ENTRY_POINT)
    assert _ENTRY_POINT in analysis.__all__
    assert "LeaseLevelAcquisitionResults" in analysis.__all__
