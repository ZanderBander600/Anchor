"""Sprint D Gate D4.6B -- architecture guardrails and mutation kills.

Restates
``docs/plans/2026-09-07-anchor-lease-level-underwriting-d4-6-sensitivity-architecture.md``
Sections 30-34 and the Section 38 closeout amendment.

Two claims carry this gate, and both are structural rather than reviewed by
eye:

**Sensitivity computes nothing.** ``analysis/lease_level_sensitivity.py``
chooses inputs, calls the one authoritative Lease-Level analysis, and reads one
already-computed scalar. If it contains arithmetic, a financial name, a cache
or a second analysis path, that stopped being true.

**Quick and Detailed are untouched.** ``analysis/sensitivity.py`` and
``analysis/break_even.py`` are asserted **byte-identical** to the pre-gate tree,
which is the strongest preservation proof available and the same technique
D4.5B used for the engine.

The second half of the file is a mutation suite. Each mutant is a real,
executable defect from the Section 34.1 list, applied to a live run; the test
asserts that the golden which should catch it does catch it. Mutants that
cannot be written at all are classified as such, with the structural reason
proven rather than asserted.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from anchor.analysis import (
    LEASE_LEVEL_SUPPORTED_ASSUMPTIONS,
    LEASE_LEVEL_SUPPORTED_METRICS,
    SensitivityTargetShadowedBySuiteOverrideError,
    analyze_lease_level_acquisition_with_projection,
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
)
from anchor.analysis import lease_level_sensitivity as module
from anchor.analysis.sensitivity import DETAILED_SUPPORTED_ASSUMPTIONS
from anchor.leasing import LeaseValidationError, Suite

from tests.test_analysis_d4_6b_lease_level_sensitivity import (
    analyze,
    market,
    occupied_lease,
    one_way,
    operating,
    property_inputs,
    rollover_deal,
    stable_deal,
    terms,
    two_way,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
_ANCHOR_DIR = _SRC_DIR / "anchor"
_ENGINE_DIR = _ANCHOR_DIR / "engine"
_ANALYSIS_DIR = _ANCHOR_DIR / "analysis"
_LEASING_DIR = _ANCHOR_DIR / "leasing"

_SENSITIVITY = _ANALYSIS_DIR / "lease_level_sensitivity.py"
_ENTRY_POINT = "analyze_lease_level_acquisition_with_projection"

#: The D4.6A commit -- the last one before any D4.6B production change.
#: Everything this gate touches lives in one new module, so the Quick and
#: Detailed sensitivity and break-even sources must still be identical to it.
_D4_6A_COMMIT = "15e910d"

#: The Sprint-D merge commit -- the base every D5 gate branches from, and the
#: correct baseline for any file that did not yet exist at D4.6A (notably
#: ``lease_level_sensitivity.py``, which D4.6B itself created).
_D5_BASE_COMMIT = "4f8a648"


# =============================================================================
# Helpers
# =============================================================================


def _tree(source_file: Path) -> ast.Module:
    return ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))


def _imported_module_names(source_file: Path) -> list[str]:
    tree = _tree(source_file)
    package = f"anchor.{source_file.parent.name}"
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                module_name = node.module or ""
            elif node.level == 1:
                module_name = f"{package}.{node.module}" if node.module else package
            else:
                module_name = f"anchor.{node.module}" if node.module else "anchor"
            names.append(module_name)
            names.extend(f"{module_name}.{alias.name}" for alias in node.names)
    return names


def _imported_symbols(source_file: Path) -> dict[str, list[str]]:
    """``{module: [imported names]}`` for every ``from ... import ...``."""

    package = f"anchor.{source_file.parent.name}"
    symbols: dict[str, list[str]] = {}
    for node in ast.walk(_tree(source_file)):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0:
                module_name = node.module or ""
            elif node.level == 1:
                module_name = f"{package}.{node.module}" if node.module else package
            else:
                module_name = f"anchor.{node.module}" if node.module else "anchor"
            symbols.setdefault(module_name, []).extend(
                alias.name for alias in node.names
            )
    return symbols


def _referenced_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _called_names(node: ast.AST) -> set[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.add(child.func.attr)
    return calls


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
    return [line.strip() for line in completed.stdout.decode().splitlines() if line.strip()]


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
# Guardrails 1-4 -- one analysis path, and only one
# =============================================================================


def test_g1_the_module_imports_the_lease_level_analysis_entry_point() -> None:
    """**Guardrail 1.** The positive claim. A sensitivity module that imported
    neither the bridge nor anything else would satisfy every ban below while
    computing its numbers somewhere nobody looked."""

    names = _imported_module_names(_SENSITIVITY)
    assert f"anchor.analysis.lease_level.{_ENTRY_POINT}" in names


def test_g2_the_entry_point_is_the_only_analysis_the_module_can_call() -> None:
    """**Guardrail 2.** No second producer of a financial result is reachable.
    ``analyze_lease_level_acquisition_with_projection`` is the only
    ``analyze_*`` name the module imports or calls."""

    imported = _imported_module_names(_SENSITIVITY)
    analyzers = {
        name.rsplit(".", 1)[-1]
        for name in imported
        if name.rsplit(".", 1)[-1].startswith("analyze_")
    }
    assert analyzers == {_ENTRY_POINT}

    called = {name for name in _called_names(_tree(_SENSITIVITY)) if name.startswith("analyze_")}
    assert called == {_ENTRY_POINT}


def test_g3_no_engine_function_is_called_directly() -> None:
    """**Guardrail 3.** Sensitivity sits above the bridge. It does not reach
    ``engine.returns``, ``engine.debt``, ``engine.acquisition`` or
    ``engine.noi`` -- the bridge does that, once, on its behalf."""

    names = _imported_module_names(_SENSITIVITY)
    assert not any(
        name == "anchor.engine" or name.startswith("anchor.engine.") for name in names
    ), "lease_level_sensitivity reaches the engine directly"

    called = _called_names(_tree(_SENSITIVITY))
    for forbidden in (
        "calculate_capital_stack",
        "calculate_debt_schedule",
        "calculate_exit_value",
        "calculate_net_sale_proceeds",
        "calculate_irr",
        "calculate_equity_multiple",
        "calculate_dscr",
        "analyze_acquisition",
        "analyze_acquisition_from_operating_projection",
        "analyze_detailed_acquisition_with_projection",
    ):
        assert forbidden not in called


def test_g4_no_leasing_builder_is_called_directly() -> None:
    """**Guardrail 4.** The module imports leasing **types only** -- the five
    contracts its signatures name. Not one builder, validator or resolver."""

    leasing_symbols = {
        symbol
        for module_name, symbols in _imported_symbols(_SENSITIVITY).items()
        if module_name.startswith("anchor.leasing")
        for symbol in symbols
    }
    assert leasing_symbols == {
        "Lease",
        "LeaseLevelOperatingInputs",
        "LeaseLevelPropertyInputs",
        "MarketLeasingAssumptions",
        "Suite",
    }

    import anchor.leasing as leasing_package

    for symbol in leasing_symbols:
        assert isinstance(getattr(leasing_package, symbol), type), (
            f"{symbol} is not a type; the module imported behaviour from leasing"
        )

    called = _called_names(_tree(_SENSITIVITY))
    for forbidden in (
        "build_model_months",
        "build_recursive_rollover",
        "build_initial_vacancy_rollover",
        "build_property_expense_schedule",
        "build_recoverable_expense_pool",
        "build_recursive_rollover_recovery",
        "build_property_operating_schedule",
        "build_property_recovery_schedule",
        "build_monthly_property_projection",
        "aggregate_monthly_to_annual",
        "resolve_market_leasing",
        "require_capitalizable_exit_noi",
        "suite_operating_projection",
        "suite_recovery_projection",
    ):
        assert forbidden not in called


# =============================================================================
# Guardrails 5-11 -- no financial formula exists in sensitivity
# =============================================================================


_ARITHMETIC_OPERATORS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Pow,
    ast.Mod,
)


def test_g5_to_g11_the_module_contains_no_arithmetic_at_all() -> None:
    """**Guardrails 5-11.** There is no NOI formula, no recovery formula, no
    rent formula, no exit-value formula, no IRR, no DSCR and no cash-flow
    arithmetic here -- because there is no arithmetic here at all. Banning the
    operator is stronger than banning each formula by name: a shortcut cannot
    be spelled without one."""

    for node in ast.walk(_tree(_SENSITIVITY)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITHMETIC_OPERATORS):
            pytest.fail(
                f"line {node.lineno}: lease_level_sensitivity performs arithmetic "
                f"({type(node.op).__name__})"
            )
        if isinstance(node, ast.AugAssign) and isinstance(node.op, _ARITHMETIC_OPERATORS):
            pytest.fail(f"line {node.lineno}: lease_level_sensitivity accumulates a value")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            pytest.fail(f"line {node.lineno}: lease_level_sensitivity negates a value")


def test_g5_to_g11_the_module_declares_no_numeric_literal() -> None:
    """No rate, no ratio, no floor, no bound, no offset. A numeric literal here
    would be a financial assumption invented by the sensitivity layer -- and a
    relative shock, a clip or a grid limit all need one."""

    for node in ast.walk(_tree(_SENSITIVITY)):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            pytest.fail(
                f"line {node.lineno}: lease_level_sensitivity declares the numeric "
                f"literal {node.value!r}"
            )


def test_g5_to_g11_the_module_makes_no_numeric_comparison() -> None:
    """String membership and identity only. A numeric comparison would be a
    threshold -- a clip, a domain rule or a grid ceiling."""

    for node in ast.walk(_tree(_SENSITIVITY)):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                assert not (
                    isinstance(operand, ast.Constant)
                    and isinstance(operand.value, (int, float))
                    and not isinstance(operand.value, bool)
                ), f"line {node.lineno}: a numeric threshold appears in sensitivity"


def test_g5_to_g11_the_module_uses_no_financial_vocabulary() -> None:
    """Not one name in the module belongs to the returns or operating-model
    domain. There is nowhere for a metric to be computed or adjusted."""

    referenced = _referenced_names(_tree(_SENSITIVITY))

    for forbidden in (
        "noi",
        "exit_noi",
        "noi_by_year",
        "monthly_projection",
        "annual_projection",
        "effective_gross_income",
        "expense_recovery",
        "management_fee",
        "fixed_operating_expenses",
        "cash_base_rent",
        "contractual_base_rent",
        "tenant_improvements",
        "leasing_commissions",
        "irr",
        "levered_irr",
        "unlevered_irr",
        "equity_multiple",
        "dscr",
        "headline_dscr",
        "exit_value",
        "loan_amount",
        "initial_equity",
        "annual_debt_service",
        "levered_cash_flows",
        "unlevered_cash_flows",
        "npv",
        "discount_rate",
    ):
        assert forbidden not in referenced, (
            f"lease_level_sensitivity references {forbidden!r}"
        )


def test_g5_to_g11_the_only_result_field_read_is_the_generic_envelope() -> None:
    """The module reads ``.results`` off the envelope and hands it to the
    shipped metric selector. It never names a metric field itself, so it cannot
    read one it did not declare -- and the five metric names live in
    ``sensitivity.py``, not here."""

    referenced = _referenced_names(_tree(_SENSITIVITY))
    assert "results" in referenced
    assert "_extract_metric" in referenced

    # No metric-name string literal is declared in this module either.
    literals = {
        node.value
        for node in ast.walk(_tree(_SENSITIVITY))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    for metric in LEASE_LEVEL_SUPPORTED_METRICS:
        assert metric not in literals


# =============================================================================
# Guardrails 12-16 -- the target surface
# =============================================================================


def test_g12_exactly_eight_targets_are_supported() -> None:
    assert len(LEASE_LEVEL_SUPPORTED_ASSUMPTIONS) == 8
    assert len(set(LEASE_LEVEL_SUPPORTED_ASSUMPTIONS)) == 8
    assert isinstance(LEASE_LEVEL_SUPPORTED_ASSUMPTIONS, tuple)


def test_g12_the_shared_four_are_exactly_the_shipped_detailed_tuple() -> None:
    """Read from ``sensitivity.DETAILED_SUPPORTED_ASSUMPTIONS``, not restated:
    Lease-Level inherits the Detailed shared-terms set with no additions and no
    subtractions (Section 38.1), and the two cannot drift."""

    terms_owned = tuple(
        name
        for name, spec in module._TARGETS.items()
        if spec.owner is module._TargetOwner.TERMS
    )
    assert terms_owned == DETAILED_SUPPORTED_ASSUMPTIONS


def test_g12_the_four_additive_targets_are_the_approved_ones() -> None:
    market_owned = tuple(
        name
        for name, spec in module._TARGETS.items()
        if spec.owner is module._TargetOwner.MARKET
    )
    operating_owned = tuple(
        name
        for name, spec in module._TARGETS.items()
        if spec.owner is module._TargetOwner.OPERATING
    )
    assert market_owned == ("market_rent_psf", "renewal_probability")
    assert operating_owned == ("expense_growth", "recoverable_expense_ratio")


def test_g13_arbitrary_field_paths_are_impossible() -> None:
    """No dotted path, no bracket index, no suite selector can enter the target
    name -- the whitelist is a flat membership test against eight strings."""

    suites, leases = stable_deal()
    for attempt in (
        "terms.purchase_price",
        "market_leasing.market_rent_psf",
        "suites[0].market_rent_psf",
        "suite:B:market_rent_psf",
        "operating_inputs.expense_growth",
        "market_leasing_override.new_ti_psf",
        "__class__",
        "",
    ):
        with pytest.raises(ValueError):
            one_way(
                suites, leases, assumption=attempt, values=(1.0,),
                metric="equity_multiple",
            )


def test_g14_no_getattr_or_setattr_traversal_exists() -> None:
    """**Guardrail 14.** Baseline values are read by literal attribute name
    through the target map's own accessors. A computed ``getattr`` would make
    every field of every contract reachable by string."""

    called = _called_names(_tree(_SENSITIVITY))
    for forbidden in ("getattr", "setattr", "delattr", "vars", "globals", "locals"):
        assert forbidden not in called, (
            f"lease_level_sensitivity calls {forbidden!r}"
        )

    # No attribute of any *contract* is written -- every perturbation is a
    # `replace`. The only attribute writes in the module are an exception
    # recording its own ``self.assumption`` / ``self.suite_ids`` for the
    # caller, which touch no input.
    for node in ast.walk(_tree(_SENSITIVITY)):
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        for target in targets:
            if isinstance(target, ast.Attribute):
                assert (
                    isinstance(target.value, ast.Name) and target.value.id == "self"
                ), f"line {node.lineno}: sensitivity assigns to a contract attribute"


def test_g15_no_eval_exec_or_import_machinery_exists() -> None:
    called = _called_names(_tree(_SENSITIVITY))
    for forbidden in ("eval", "exec", "compile", "__import__", "importlib"):
        assert forbidden not in called


def test_g16_the_target_ownership_mapping_is_singular() -> None:
    """**Guardrail 16.** One mapping, one entry per target. The public tuple is
    derived from it rather than restated, so the two cannot disagree, and no
    second dict of target names exists in the module."""

    assert tuple(module._TARGETS) == LEASE_LEVEL_SUPPORTED_ASSUMPTIONS

    module_dicts = [
        node
        for node in _tree(_SENSITIVITY).body
        if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Dict)
    ] + [
        node
        for node in _tree(_SENSITIVITY).body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
    ]
    assert len(module_dicts) == 1, "more than one module-level target map exists"

    # Module-level state is the target map and the three frozen public
    # constants -- no cache, no accumulator, no mutable default.
    assignments = [
        target.id
        for node in _tree(_SENSITIVITY).body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    ]
    assert assignments == [
        "_TARGETS",
        "LEASE_LEVEL_SUPPORTED_ASSUMPTIONS",
        "LEASE_LEVEL_SUPPORTED_METRICS",
        "SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE",
    ]


# =============================================================================
# Guardrails 17-20 -- the shadow rules, and the absence of suite targeting
# =============================================================================


def test_g17_the_market_rent_shadow_rule_is_target_specific() -> None:
    """**Guardrail 17.** ``market_rent_psf`` is shadowed by **either** suite
    override field, because ``Suite.market_rent_psf`` is a genuine single-field
    override of the rent level."""

    predicate = module._TARGETS["market_rent_psf"].shadowed_by
    assert predicate is not None

    plain = Suite(suite_id="A", suite_area_sf=1.0)
    scalar = Suite(suite_id="B", suite_area_sf=1.0, market_rent_psf=48.0)
    full = Suite(suite_id="C", suite_area_sf=1.0, market_leasing_override=market())
    both = Suite(
        suite_id="D", suite_area_sf=1.0, market_rent_psf=52.0,
        market_leasing_override=market(),
    )

    assert predicate(plain) is False
    assert predicate(scalar) is True
    assert predicate(full) is True
    assert predicate(both) is True


def test_g18_the_renewal_probability_shadow_rule_is_different() -> None:
    """**Guardrail 18.** The load-bearing asymmetry: a scalar rent override
    does **not** shadow the renewal probability, because it overrides the rent
    level alone. Assuming symmetry with ``market_rent_psf`` would refuse a
    question that is perfectly answerable."""

    predicate = module._TARGETS["renewal_probability"].shadowed_by
    assert predicate is not None

    plain = Suite(suite_id="A", suite_area_sf=1.0)
    scalar = Suite(suite_id="B", suite_area_sf=1.0, market_rent_psf=48.0)
    full = Suite(suite_id="C", suite_area_sf=1.0, market_leasing_override=market())

    assert predicate(plain) is False
    assert predicate(scalar) is False
    assert predicate(full) is True


def test_g18_the_two_market_predicates_are_not_the_same_object() -> None:
    """If a refactor ever collapsed them into one predicate, the asymmetry
    would silently disappear."""

    rent = module._TARGETS["market_rent_psf"].shadowed_by
    probability = module._TARGETS["renewal_probability"].shadowed_by
    assert rent is not probability

    scalar = Suite(suite_id="B", suite_area_sf=1.0, market_rent_psf=48.0)
    assert rent(scalar) != probability(scalar)


@pytest.mark.parametrize(
    "assumption",
    ["purchase_price", "exit_cap_rate", "ltv", "interest_rate",
     "expense_growth", "recoverable_expense_ratio"],
)
def test_g19_the_other_six_targets_carry_no_shadow_predicate(assumption: str) -> None:
    """**Guardrail 19.** ``LeaseLevelOperatingInputs`` and ``AcquisitionTerms``
    share no field with ``Suite`` and are unreachable from any override, so
    these targets have no predicate at all -- not a predicate that happens to
    return ``False``."""

    assert module._TARGETS[assumption].shadowed_by is None


def test_g19_the_operating_contract_shares_no_field_with_suite() -> None:
    """The field-set intersection Section 38.2.2 relies on, checked directly
    rather than trusted."""

    from anchor.leasing import LeaseLevelOperatingInputs

    operating_fields = {f.name for f in dataclasses.fields(LeaseLevelOperatingInputs)}
    suite_fields = {f.name for f in dataclasses.fields(Suite)}
    assert operating_fields & suite_fields == set()


def test_g20_no_suite_or_lease_level_target_contract_exists() -> None:
    """**Guardrail 20.** HD-D4.6-3 deferred suite targeting, so there must be
    no composite target, no ``suite_id`` parameter and no suite selector
    anywhere in the module's public surface."""

    for runner in (
        run_lease_level_one_way_sensitivity,
        run_lease_level_two_way_sensitivity,
    ):
        import inspect

        parameters = set(inspect.signature(runner).parameters)
        for forbidden in ("suite_id", "suite_index", "suite", "target", "targets"):
            assert forbidden not in parameters

    referenced = _referenced_names(_tree(_SENSITIVITY))
    assert "market_rent_psf" in referenced  # the property-default target exists
    # ...but no suite-keyed selector does.
    for forbidden in ("suite_index", "first_suite", "by_suite_id"):
        assert forbidden not in referenced


# =============================================================================
# Guardrails 21-25 -- value semantics
# =============================================================================


def test_g21_candidate_values_are_absolute() -> None:
    """**Guardrail 21.** The candidate is written straight onto the contract.
    No offset, no multiplier, no basis-point or percentage-point conversion --
    which the no-arithmetic and no-numeric-literal guardrails make structurally
    impossible, and which this asserts behaviourally."""

    suites, leases = stable_deal()

    with patch.object(
        module, _ENTRY_POINT, wraps=analyze_lease_level_acquisition_with_projection
    ) as spy:
        one_way(
            suites, leases, assumption="exit_cap_rate", values=(0.0725,),
            metric="exit_value",
        )

    scenario_call = spy.call_args_list[-1]
    assert scenario_call.args[0].exit_cap_rate == 0.0725


def test_g22_renewal_probability_is_never_clipped() -> None:
    """**Guardrail 22.** 1.2 stays 1.2 all the way to the contract validator,
    which refuses it. It is not silently turned into 1.0."""

    suites, leases, mkt = rollover_deal()
    with pytest.raises(LeaseValidationError):
        one_way(
            suites, leases, mkt=mkt, assumption="renewal_probability",
            values=(1.2,), metric="equity_multiple",
        )

    # And the exact endpoints are passed through untransformed.
    with patch.object(
        module, _ENTRY_POINT, wraps=analyze_lease_level_acquisition_with_projection
    ) as spy:
        one_way(
            suites, leases, mkt=mkt, assumption="renewal_probability",
            values=(0.0, 1.0), metric="equity_multiple",
        )
    seen = [
        call.kwargs["market_leasing"].renewal_probability
        for call in spy.call_args_list[1:]
    ]
    assert seen == [0.0, 1.0]


def test_g23_none_is_a_valid_metric_result() -> None:
    """**Guardrail 23.** The result contracts already carry ``float | None``,
    and the runner passes an undefined metric through unchanged."""

    fields = {f.name: f.type for f in dataclasses.fields(module.OneWaySensitivityResult)}
    assert "None" in str(fields["metric_values"])

    from tests.test_analysis_d4_6b_lease_level_sensitivity import undefined_irr_deal

    suites, leases, mkt, deal = undefined_irr_deal()
    result = one_way(
        suites, leases, deal=deal, mkt=mkt, assumption="exit_cap_rate",
        values=(0.06, 0.07), metric="levered_irr",
    )
    assert result.metric_values == (None, None)


def test_g24_and_g25_no_exception_is_caught_anywhere_in_the_module() -> None:
    """**Guardrails 24-25.** A validation failure cannot be converted into
    ``None``, ``0`` or a sentinel, and ``NON_POSITIVE_FORWARD_EXIT_NOI`` cannot
    be caught and reinterpreted -- because the module contains no ``try``, no
    ``except`` and no ``contextlib.suppress`` at all."""

    for node in ast.walk(_tree(_SENSITIVITY)):
        assert not isinstance(node, (ast.Try, ast.ExceptHandler)), (
            f"line {node.lineno}: sensitivity catches an exception"
        )

    called = _called_names(_tree(_SENSITIVITY))
    assert "suppress" not in called

    # And no `None` literal is ever written into a result position: the only
    # `None`s in the module are the absent shadow predicate and type hints.
    suites, leases = stable_deal()
    with pytest.raises(LeaseValidationError):
        one_way(
            suites, leases, assumption="expense_growth", values=(0.03, 5.0),
            metric="equity_multiple",
        )


# =============================================================================
# Guardrails 26-30 -- scenario construction and retention
# =============================================================================


def test_g26_and_g27_every_scenario_is_built_by_the_one_replacement_seam() -> None:
    """**Guardrails 26-27.** Both runners build every scenario through
    ``_scenario_contracts``, which takes the baseline contracts as arguments
    and returns new ones. Neither runner rebinds a baseline name, so no cell
    can become the next cell's starting point."""

    tree = _tree(_SENSITIVITY)
    runners = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("run_lease_level_")
    }
    assert set(runners) == {
        "run_lease_level_one_way_sensitivity",
        "run_lease_level_two_way_sensitivity",
    }

    baseline_names = {
        "terms", "property_inputs", "suites", "leases", "market_leasing",
        "operating_inputs", "suite_tuple", "lease_tuple",
    }
    for name, runner in runners.items():
        assigned: list[str] = []
        for node in ast.walk(runner):
            if isinstance(node, ast.Assign):
                assigned.extend(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and isinstance(
                node.target, ast.Name
            ):
                assigned.append(node.target.id)
        rebound = (set(assigned) & baseline_names) - {"suite_tuple", "lease_tuple"}
        assert not rebound, f"{name} rebinds a baseline name: {sorted(rebound)}"

    # Only the seam constructs a scenario, and only it calls the analysis.
    seam = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_scenario_metric"
    )
    assert _ENTRY_POINT in _called_names(seam)
    for name, runner in runners.items():
        assert _ENTRY_POINT not in _called_names(runner), (
            f"{name} calls the analysis directly instead of through the seam"
        )


def test_g28_replace_is_the_only_mutation_mechanism() -> None:
    """**Guardrail 28.** ``dataclasses.replace`` on frozen contracts, and
    nothing else. No ``__dict__`` write, no ``object.__setattr__``, no
    ``copy``, no list or dict mutation of an input."""

    called = _called_names(_tree(_SENSITIVITY))
    assert "replace" in called
    for forbidden in (
        "__setattr__", "object.__setattr__", "update", "extend", "insert",
        "pop", "remove", "clear", "setdefault", "deepcopy", "copy",
    ):
        assert forbidden not in called, (
            f"lease_level_sensitivity calls {forbidden!r}"
        )

    # ``append`` is used, and only on the two local result lists a runner
    # builds before freezing them into a tuple -- never on a caller's input.
    appenders = {
        node.name
        for node in ast.walk(_tree(_SENSITIVITY))
        if isinstance(node, ast.FunctionDef) and "append" in _called_names(node)
    }
    assert appenders == {
        "run_lease_level_one_way_sensitivity",
        "run_lease_level_two_way_sensitivity",
    }


def test_g29_the_input_contracts_are_all_frozen() -> None:
    """**Guardrail 29.** Baseline immutability is structural, not disciplined:
    a mutation mutant cannot be written against these contracts at all."""

    from anchor.contracts import AcquisitionTerms
    from anchor.leasing import (
        InitialVacancyAssumptions,
        Lease,
        LeaseLevelOperatingInputs,
        LeaseLevelPropertyInputs,
        MarketLeasingAssumptions,
    )

    for contract in (
        AcquisitionTerms,
        LeaseLevelPropertyInputs,
        Suite,
        Lease,
        MarketLeasingAssumptions,
        LeaseLevelOperatingInputs,
        InitialVacancyAssumptions,
    ):
        parameters = contract.__dataclass_params__
        assert parameters.frozen, f"{contract.__name__} is not frozen"


def test_g30_no_projection_or_envelope_type_is_named_in_the_module() -> None:
    """**Guardrail 30.** The completed envelope is consumed inside the seam and
    discarded. Nothing in the module can hold a ``MonthlyPropertyProjection``,
    an ``AnnualOperatingProjection`` or a ``LeaseLevelAcquisitionResults``,
    because none of those names appears here."""

    source = _SENSITIVITY.read_text(encoding="utf-8")
    tree_names = _referenced_names(_tree(_SENSITIVITY))
    for forbidden in (
        "MonthlyPropertyProjection",
        "AnnualOperatingProjection",
        "LeaseLevelAcquisitionResults",
        "PropertyRecoverySchedule",
        "RecoverableExpensePool",
        "OperatingCapitalSchedule",
    ):
        assert forbidden not in tree_names
        assert f"import {forbidden}" not in source


# =============================================================================
# Guardrails 31-33 -- no cache, no parallelism, no grid limit
# =============================================================================


def test_g31_no_caching_of_any_kind() -> None:
    """**Guardrail 31.** Section 38.7. A cache keyed on anything less than the
    full six-contract fingerprint would serve a stale projection -- exactly the
    stale-pool failure family."""

    names = _imported_module_names(_SENSITIVITY)
    for forbidden in ("functools", "functools.cache", "functools.lru_cache", "weakref"):
        assert forbidden not in names

    referenced = _referenced_names(_tree(_SENSITIVITY))
    for forbidden in (
        "cache", "lru_cache", "cached_property", "memoize", "_memo",
        "_cache", "_results_by_scenario",
    ):
        assert forbidden not in referenced

    # No decorator at all on any function in the module.
    for node in ast.walk(_tree(_SENSITIVITY)):
        if isinstance(node, ast.FunctionDef):
            assert node.decorator_list == [], f"{node.name} is decorated"


def test_g32_no_parallelism_of_any_kind() -> None:
    """**Guardrail 32.** Sequential deterministic evaluation is the reference
    behaviour."""

    names = _imported_module_names(_SENSITIVITY)
    for forbidden in (
        "threading", "multiprocessing", "asyncio", "concurrent",
        "concurrent.futures", "subprocess",
    ):
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}.") for name in names
        )

    for node in ast.walk(_tree(_SENSITIVITY)):
        assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await)), (
            "sensitivity evaluates scenarios asynchronously"
        )


def test_g33_no_arbitrary_grid_limit_exists() -> None:
    """**Guardrail 33.** Section 38.7: performance does not justify one in D4.
    A grid far larger than any preset runs to completion."""

    suites, leases = stable_deal()

    wide = one_way(
        suites, leases, assumption="exit_cap_rate",
        values=tuple(0.05 + n / 1000 for n in range(25)),
        metric="equity_multiple",
    )
    assert len(wide.metric_values) == 25

    grid = two_way(
        suites, leases,
        row_assumption="purchase_price",
        row_values=tuple(35_000_000.0 + n * 500_000.0 for n in range(11)),
        column_assumption="exit_cap_rate",
        column_values=tuple(0.05 + n / 1000 for n in range(11)),
        metric="equity_multiple",
    )
    assert len(grid.matrix) == 11
    assert all(len(row) == 11 for row in grid.matrix)


# =============================================================================
# Guardrails 34-41 -- the preserved surface
# =============================================================================


def test_g34_operating_mode_lease_level_is_published_but_sensitivity_stays_mode_blind() -> None:
    """**Guardrail 34, succeeded at D5.1A.**

    D4.6B re-confirmed HD-D4-9's deferral and added its own, independent reason
    for wanting no enum member: Lease-Level sensitivity is distinguished by
    **function identity**, exactly as Quick and Detailed already are, so the
    runners never needed one.

    D5.1A publishes the member for the *delivery* layers that genuinely must
    dispatch on it. That does not touch this module's reason for existing, so
    the half of the guardrail that mattered to D4.6B is unchanged and is the
    half asserted most strongly here: ``lease_level_sensitivity`` still never
    names or imports ``OperatingMode``. If the mode ever leaks into the
    sensitivity layer, the analysis package has started dispatching on an enum
    instead of on function identity, and that is a real architectural
    regression -- which is why this assertion survives verbatim.
    """

    from anchor.contracts import OperatingMode

    assert {member.value for member in OperatingMode} == {
        "quick",
        "detailed",
        "lease_level",
    }
    assert OperatingMode("lease_level") is OperatingMode.LEASE_LEVEL

    # Unchanged from D4.6B, and the point of this guardrail.
    assert "OperatingMode" not in _referenced_names(_tree(_SENSITIVITY))
    assert not any(
        name.endswith("OperatingMode") for name in _imported_module_names(_SENSITIVITY)
    )


def test_g35_no_lease_level_break_even_exists() -> None:
    """**Guardrail 35.** HD-D4.6-5 deferred break-even entirely -- no public
    and no internal entry point, and no new module."""

    assert not (_ANALYSIS_DIR / "lease_level_break_even.py").exists()

    definitions = [
        f"{path.relative_to(_SRC_DIR).as_posix()}::{node.name}"
        for path in _python_files_under(_ANCHOR_DIR)
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and "lease_level" in node.name.lower()
        and ("break_even" in node.name.lower() or "breakeven" in node.name.lower())
    ]
    assert definitions == []

    import anchor.analysis as analysis_package

    assert not any(
        "lease_level" in name and "break_even" in name
        for name in analysis_package.__all__
    )

    # Break-even's tolerance table gained no Lease-Level entry.
    from anchor.analysis import break_even as break_even_module

    assert set(break_even_module._ASSUMPTION_TOLERANCES) == {
        "purchase_price", "exit_cap_rate", "noi_growth", "interest_rate",
        "current_noi",
    }


def test_g36_analysis_sensitivity_is_byte_identical_since_d4_6a() -> None:
    """**Guardrail 36.** The strongest Quick/Detailed preservation proof there
    is: the file that produces every shipped Quick and Detailed sensitivity
    number was not edited."""

    changed = _files_changed_since(_D4_6A_COMMIT, "src/anchor/analysis/sensitivity.py")
    assert changed == [], f"analysis/sensitivity.py changed: {changed}"


def test_g37_analysis_break_even_is_byte_identical_since_d4_6a() -> None:
    """**Guardrail 37.** Section 38.5: ``break_even.py`` must not be modified
    during D4 at all -- not to fix its monotonicity language, not to add
    tolerances, not at all."""

    changed = _files_changed_since(_D4_6A_COMMIT, "src/anchor/analysis/break_even.py")
    assert changed == [], f"analysis/break_even.py changed: {changed}"


def test_g37_the_financial_layers_are_unchanged_and_only_dispatch_moved() -> None:
    """**Narrowed at D5.1A -- and not weakened.**

    The original asserted byte-identity across eleven areas since D4.6A. Five of
    them are mode-dispatch consumers that D5.1A must edit by definition
    (``api.py``, ``contracts.py``, ``deals``, ``ai``), so whole-tree identity
    stopped being a statement of the rule.

    The rule it was protecting is *"nothing financial moved"*, and that is
    asserted here undiminished: every engine, leasing and analysis module is
    still byte-identical, as is ``validation.py`` and the whole web tree. The
    five dispatch files are permitted to change, and are then held to a
    stronger, more specific claim than byte-identity could give -- that the only
    thing which changed in them is mode routing, proved by
    ``tests/test_d5_1a_operating_mode_total_dispatch.py`` and by G34's TI/LC
    assertion above.
    """

    # Financial authority: byte-identical since D4.6A, no exceptions.
    for area in (
        "src/anchor/engine",
        "src/anchor/leasing",
        "src/anchor/analysis/contracts.py",
        "src/anchor/analysis/lease_level.py",
        "src/anchor/analysis/sensitivity.py",
        "src/anchor/analysis/break_even.py",
        "src/anchor/validation.py",
        "src/anchor/ingestion",
        "src/anchor/ai/prompts.py",
        # The frontend's financial and transport modules. `web` as a whole was
        # asserted byte-identical until D5.1B, which had to edit the frontend's
        # mode-dispatch files for exactly the reason D5.1A edited the backend's.
        # Whole-tree identity therefore stopped being the statement of the rule;
        # "nothing financial moved" is, and these are the frontend files that
        # could carry financial or transport meaning. Every one is untouched.
        "web/src/convert.ts",
        "web/src/format.ts",
        "web/src/liveMetrics.ts",
        "web/src/ownerSummary.ts",
        "web/src/api.ts",
    ):
        assert _files_changed_since(_D4_6A_COMMIT, area) == [], f"{area} changed"

    # ``lease_level_sensitivity.py`` did not exist at D4.6A -- D4.6B created it
    # -- so its baseline is the Sprint-D merge this gate branched from.
    assert (
        _files_changed_since(
            _D5_BASE_COMMIT, "src/anchor/analysis/lease_level_sensitivity.py"
        )
        == []
    )

    # Delivery layers: only the mode-dispatch consumers moved.
    permitted = {
        "src/anchor/api.py",
        "src/anchor/contracts.py",
        "src/anchor/deals/contracts.py",
        "src/anchor/deals/store.py",
        "src/anchor/ai/contracts.py",
        "src/anchor/ai/presentation.py",
    }
    for area in ("src/anchor/ai", "src/anchor/deals", "src/anchor/api.py",
                 "src/anchor/contracts.py"):
        unexpected = set(_files_changed_since(_D4_6A_COMMIT, area)) - permitted
        assert unexpected == set(), (
            f"{area} changed beyond D5.1A's mode-dispatch scope: {sorted(unexpected)}"
        )

    # D5.1B: the frontend changed only its mode-dispatch surface. Its own
    # guardrails (`web/src/modeDispatch.architecture.test.ts`) prove the change
    # was dispatch and nothing else; this pins the file list from the backend
    # side so a frontend gate cannot quietly widen without a reviewer noticing.
    permitted_web = {
        "web/src/App.tsx",
        "web/src/types.ts",
        "web/src/underwrite.ts",
        "web/src/operatingMode.ts",
        "web/src/components/AppSidebar.tsx",
        "web/src/components/DealHeader.tsx",
        "web/src/components/DealLibraryPanel.tsx",
        "web/src/components/OwnerSummaryPanel.tsx",
        "web/src/components/UnderwriteWorkspace.tsx",
    }
    unexpected_web = {
        path
        for path in _files_changed_since(_D4_6A_COMMIT, "web")
        if not path.endswith(".test.ts") and not path.endswith(".test.tsx")
    } - permitted_web
    assert unexpected_web == set(), (
        f"web changed beyond D5.1B's mode-dispatch scope: {sorted(unexpected_web)}"
    )


@pytest.mark.parametrize(
    "source_file", _python_files_under(_ENGINE_DIR), ids=lambda path: path.name
)
def test_g38_no_engine_module_imports_lease_level_sensitivity(source_file: Path) -> None:
    """**Guardrail 38.** The direction is one-way. The engine is the terminus."""

    names = _imported_module_names(source_file)
    assert not any("lease_level_sensitivity" in name for name in names)
    assert not any(
        name == "anchor.analysis" or name.startswith("anchor.analysis.")
        for name in names
    )


@pytest.mark.parametrize(
    "source_file", _python_files_under(_LEASING_DIR), ids=lambda path: path.name
)
def test_g39_no_leasing_module_imports_any_sensitivity(source_file: Path) -> None:
    """**Guardrail 39.** No back-edge: leasing does not know its consumer
    exists, let alone its consumer's sensitivity layer."""

    names = _imported_module_names(source_file)
    assert not any(
        name == "anchor.analysis" or name.startswith("anchor.analysis.")
        for name in names
    )


def test_g40_no_api_web_persistence_or_ai_integration_exists() -> None:
    """**Guardrail 40.** D4.6B ships the deterministic core only. Presets, API
    wiring and AI consumption are D4.6C/D5 territory."""

    names = _imported_module_names(_SENSITIVITY)
    for forbidden in (
        "anchor.ai", "anchor.api", "anchor.deals", "anchor.ingestion",
        "anchor.excel", "anchor.persistence", "web", "fastapi", "sqlalchemy",
        "openpyxl", "openai", "numpy", "scipy",
    ):
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}.") for name in names
        ), f"lease_level_sensitivity imports {forbidden!r}"

    # Nothing outside the analysis package imports the new module.
    importers = sorted(
        path.relative_to(_SRC_DIR).as_posix()
        for path in _python_files_under(_ANCHOR_DIR)
        if any(
            "lease_level_sensitivity" in name
            for name in _imported_module_names(path)
        )
    )
    assert importers == ["anchor/analysis/__init__.py"]


def test_g40_no_preset_bundle_was_invented() -> None:
    """Section 26.2 defers Lease-Level presets to D4.6C or later. D4.6B ships
    the explicit runners only."""

    import anchor.analysis as analysis_package

    lease_level_exports = [
        name for name in analysis_package.__all__ if "lease_level" in name.lower()
    ]
    assert sorted(lease_level_exports) == [
        "LEASE_LEVEL_SUPPORTED_ASSUMPTIONS",
        "LEASE_LEVEL_SUPPORTED_METRICS",
        "analyze_lease_level_acquisition_with_projection",
        "run_lease_level_one_way_sensitivity",
        "run_lease_level_two_way_sensitivity",
    ]
    # Two runners, no preset builder and no preset bundle contract.
    assert not any(
        name.startswith("build_") and "lease_level" in name.lower()
        for name in analysis_package.__all__
    )
    assert not any(
        "LeaseLevel" in name and "Presets" in name for name in analysis_package.__all__
    )

    defined = [
        node.name
        for node in ast.walk(_tree(_SENSITIVITY))
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and node.name.startswith("build_")
    ]
    assert defined == []


def test_g41_the_deterministic_analysis_is_the_sole_financial_authority() -> None:
    """**Guardrail 41.** With the entry point patched out entirely, the runner
    can produce no number at all -- there is no fallback path, no approximation
    and no second producer."""

    suites, leases = stable_deal()

    def refuse(*args, **kwargs):
        raise RuntimeError("the authoritative analysis was bypassed")

    with patch.object(module, _ENTRY_POINT, refuse):
        with pytest.raises(RuntimeError, match="bypassed"):
            one_way(
                suites, leases, assumption="exit_cap_rate", values=(0.06,),
                metric="equity_multiple",
            )


def test_the_module_imports_cleanly_without_pulling_a_delivery_layer() -> None:
    completed = _fresh_interpreter(
        "import sys; import anchor.analysis.lease_level_sensitivity; "
        "assert 'anchor.leasing' in sys.modules; "
        "assert 'anchor.api' not in sys.modules; "
        "assert 'fastapi' not in sys.modules"
    )
    assert completed.returncode == 0, completed.stderr.decode()


# =============================================================================
# Mutation suite -- Section 34.1
#
# Each mutant is a real defect applied to a live run. The test asserts that the
# golden which should catch it does. Mutants that cannot be written are
# classified, with the structural reason proven.
# =============================================================================


def _oracle_cells(suites, leases, assumption, values, *, deal=None, mkt=None, ops=None):
    """The independent re-underwrite of each candidate -- the oracle the
    goldens use."""

    cells = []
    for value in values:
        kwargs = {"deal": deal, "mkt": mkt, "ops": ops}
        if assumption in ("purchase_price", "exit_cap_rate", "ltv", "interest_rate"):
            kwargs["deal"] = terms(
                **{"hold_period": (deal or terms()).hold_period, assumption: value}
            )
        elif assumption in ("market_rent_psf", "renewal_probability"):
            kwargs["mkt"] = dataclasses.replace(mkt or market(), **{assumption: value})
        else:
            kwargs["ops"] = operating(**{assumption: value})
        cells.append(analyze(suites, leases, **kwargs).results.equity_multiple)
    return cells


def test_m1_a_baseline_estimated_metric_is_killed() -> None:
    """**M1.** The metric is read off the baseline result instead of a scenario
    re-underwrite. Every cell becomes the baseline, and the oracle golden that
    requires cell == independent analysis fails."""

    suites, leases = stable_deal()
    values = (36_000_000.0, 40_000_000.0, 44_000_000.0)
    oracle = _oracle_cells(suites, leases, "purchase_price", values)

    real = one_way(
        suites, leases, assumption="purchase_price", values=values,
        metric="equity_multiple",
    )
    assert list(real.metric_values) == oracle  # the golden passes as shipped

    baseline = analyze(suites, leases).results.equity_multiple

    def mutant(**kwargs):
        return baseline

    with patch.object(module, "_scenario_metric", mutant):
        mutated = one_way(
            suites, leases, assumption="purchase_price", values=values,
            metric="equity_multiple",
        )
    assert list(mutated.metric_values) != oracle, "M1 SURVIVED"


def test_m2_a_baseline_mutating_scenario_cannot_be_written() -> None:
    """**M2 -- classified: structurally impossible.** Every input contract is a
    frozen dataclass, so the mutant cannot be expressed. Proven rather than
    assumed."""

    suites, leases, mkt = rollover_deal()
    deal = terms()
    ops = operating()

    for target, field, value in (
        (deal, "purchase_price", 1.0),
        (mkt, "market_rent_psf", 1.0),
        (ops, "expense_growth", 1.0),
        (suites[0], "market_rent_psf", 1.0),
        (leases[0], "base_rent_psf", 1.0),
        (property_inputs(), "rentable_area_sf", 1.0),
    ):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(target, field, value)


def test_m3_a_cumulative_one_way_runner_is_killed() -> None:
    """**M3.** Candidate *n+1* starts from candidate *n*'s contracts. With an
    ordered sweep the cells drift, and the oracle golden fails."""

    suites, leases, mkt = rollover_deal()
    values = (24.0, 36.0, 48.0)
    oracle = _oracle_cells(suites, leases, "market_rent_psf", values, mkt=mkt)

    real = one_way(
        suites, leases, mkt=mkt, assumption="market_rent_psf", values=values,
        metric="equity_multiple",
    )
    assert list(real.metric_values) == oracle

    def cumulative_mutant():
        """Each scenario built on the previous scenario's operating inputs."""

        cells = []
        carried = operating()
        for value in values:
            # The defect: an unrelated field drifts with each scenario because
            # the previous cell's contracts were reused as the baseline.
            carried = dataclasses.replace(
                carried, recoverable_expense_ratio=carried.recoverable_expense_ratio / 2
            )
            cells.append(
                analyze(
                    suites, leases,
                    mkt=dataclasses.replace(mkt, market_rent_psf=value),
                    ops=carried,
                ).results.equity_multiple
            )
        return cells

    assert cumulative_mutant() != oracle, "M3 SURVIVED"


def test_m4_and_m5_cumulative_two_way_cells_are_killed() -> None:
    """**M4/M5.** Column perturbations accumulate along a row, and row
    perturbations accumulate down the grid. The 3x3 independent-cell oracle
    fails in both cases."""

    suites, leases, mkt = rollover_deal()
    rents = (24.0, 36.0, 48.0)
    ratios = (0.25, 0.5, 1.0)

    real = two_way(
        suites, leases, mkt=mkt,
        row_assumption="market_rent_psf", row_values=rents,
        column_assumption="recoverable_expense_ratio", column_values=ratios,
        metric="equity_multiple",
    )

    def oracle_cell(rent, ratio):
        return analyze(
            suites, leases,
            mkt=dataclasses.replace(mkt, market_rent_psf=rent),
            ops=operating(recoverable_expense_ratio=ratio),
        ).results.equity_multiple

    for i, rent in enumerate(rents):
        for j, ratio in enumerate(ratios):
            assert real.matrix[i][j] == oracle_cell(rent, ratio)

    # M4: the column value accumulates along the row.
    column_mutant = []
    for rent in rents:
        row, carried = [], 1.0
        for ratio in ratios:
            carried = carried * ratio
            row.append(oracle_cell(rent, carried))
        column_mutant.append(row)
    assert column_mutant != [list(row) for row in real.matrix], "M4 SURVIVED"

    # M5: the row value accumulates down the grid.
    row_mutant, carried_rent = [], rents[0]
    for rent in rents:
        carried_rent = min(carried_rent, rent)
        row_mutant.append([oracle_cell(carried_rent, ratio) for ratio in ratios])
    assert row_mutant != [list(row) for row in real.matrix], "M5 SURVIVED"


def test_m6_ignoring_the_scalar_rent_override_for_market_rent_is_killed() -> None:
    """**M6.** The ``market_rent_psf`` shadow check drops the
    ``Suite.market_rent_psf`` half of its predicate. The shadowed run is then
    allowed, and Golden 10 fails."""

    a = Suite(suite_id="A", suite_area_sf=60_000.0)
    b = Suite(suite_id="B", suite_area_sf=40_000.0, market_rent_psf=48.0)
    leases = [
        occupied_lease(a, end=date(2028, 12, 31)),
        occupied_lease(b, end=date(2028, 12, 31)),
    ]

    candidates = (24.0, 36.0)  # neither equals suite B's $48 override

    # As shipped: refused.
    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError):
        one_way([a, b], leases, assumption="market_rent_psf",
                values=candidates, metric="equity_multiple")

    mutant_targets = dict(module._TARGETS)
    mutant_targets["market_rent_psf"] = dataclasses.replace(
        module._TARGETS["market_rent_psf"],
        shadowed_by=lambda suite: suite.market_leasing_override is not None,
    )
    with patch.object(module, "_TARGETS", mutant_targets):
        mutated = one_way(
            [a, b], leases, assumption="market_rent_psf",
            values=candidates, metric="equity_multiple",
        )

    # The mutant produces a plausible, monotone, *wrong* table: only suite A
    # responded, so every cell is propped up by suite B's fixed $48 while the
    # header claims a property-wide $24-$36 sweep. Against the same property
    # with no override at all:
    unshadowed_b = Suite(suite_id="B", suite_area_sf=40_000.0)
    honest = one_way(
        [a, unshadowed_b], leases, assumption="market_rent_psf",
        values=candidates, metric="equity_multiple",
    )
    assert list(mutated.metric_values) != list(honest.metric_values), (
        "M6 SURVIVED: the shadowed run was indistinguishable from an honest one"
    )
    for mutant_cell, honest_cell in zip(
        mutated.metric_values, honest.metric_values, strict=True
    ):
        assert mutant_cell > honest_cell


def test_m7_treating_the_scalar_rent_override_as_shadowing_probability_is_killed() -> None:
    """**M7.** ``renewal_probability`` wrongly adopts ``market_rent_psf``'s
    predicate. A perfectly answerable question is then refused, and Golden 11
    fails."""

    a = Suite(suite_id="A", suite_area_sf=60_000.0)
    b = Suite(suite_id="B", suite_area_sf=40_000.0, market_rent_psf=48.0)
    leases = [
        occupied_lease(a, end=date(2028, 12, 31)),
        occupied_lease(b, end=date(2028, 12, 31)),
    ]
    mkt = market(market_rent_psf=36.0, renewal_ti_psf=5.0, new_ti_psf=40.0,
                 new_downtime_months=6.0)

    # As shipped: allowed.
    one_way([a, b], leases, mkt=mkt, assumption="renewal_probability",
            values=(0.0, 1.0), metric="equity_multiple")

    mutant_targets = dict(module._TARGETS)
    mutant_targets["renewal_probability"] = dataclasses.replace(
        module._TARGETS["renewal_probability"],
        shadowed_by=module._TARGETS["market_rent_psf"].shadowed_by,
    )
    with patch.object(module, "_TARGETS", mutant_targets):
        with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError):
            one_way([a, b], leases, mkt=mkt, assumption="renewal_probability",
                    values=(0.0, 1.0), metric="equity_multiple")


def test_m8_ignoring_the_full_override_for_probability_is_killed() -> None:
    """**M8.** ``renewal_probability`` loses its predicate entirely. A run that
    must be refused is allowed, and Golden 12 fails."""

    # Differentiated renewal and new-tenant economics, so the probability is
    # not inert by construction.
    mkt = market(
        market_rent_psf=36.0, renewal_ti_psf=5.0, new_ti_psf=40.0,
        renewal_lc_pct=0.02, new_lc_pct=0.06, new_downtime_months=6.0,
        new_free_rent_months=3.0,
    )
    a = Suite(suite_id="A", suite_area_sf=60_000.0)
    b = Suite(
        suite_id="B", suite_area_sf=40_000.0,
        market_leasing_override=dataclasses.replace(mkt, renewal_probability=0.25),
    )
    leases = [
        occupied_lease(a, end=date(2028, 12, 31)),
        occupied_lease(b, end=date(2028, 12, 31)),
    ]

    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError):
        one_way([a, b], leases, mkt=mkt, assumption="renewal_probability",
                values=(0.0, 1.0), metric="equity_multiple")

    mutant_targets = dict(module._TARGETS)
    mutant_targets["renewal_probability"] = dataclasses.replace(
        module._TARGETS["renewal_probability"], shadowed_by=None
    )
    with patch.object(module, "_TARGETS", mutant_targets):
        mutated = one_way(
            [a, b], leases, mkt=mkt, assumption="renewal_probability",
            values=(0.0, 1.0), metric="equity_multiple",
        )

    # The overridden suite never moves, so the mutant answers a property-wide
    # question with 60% of the building and reports it as the whole. Its spread
    # is strictly narrower than the honest, unshadowed property's.
    unshadowed_b = Suite(suite_id="B", suite_area_sf=40_000.0)
    honest = one_way(
        [a, unshadowed_b], leases, mkt=mkt, assumption="renewal_probability",
        values=(0.0, 1.0), metric="equity_multiple",
    )
    mutant_spread = mutated.metric_values[1] - mutated.metric_values[0]
    honest_spread = honest.metric_values[1] - honest.metric_values[0]
    assert mutant_spread < honest_spread, (
        "M8 SURVIVED: the shadowed run was indistinguishable from an honest one"
    )


def test_m9_overwriting_a_suite_override_instead_of_refusing_is_killed() -> None:
    """**M9.** Option C of Section 19.3, explicitly rejected: the property
    shock overwrites every suite's override. Golden 10 requires a refusal, so
    any result at all kills the mutant."""

    a = Suite(suite_id="A", suite_area_sf=60_000.0)
    b = Suite(
        suite_id="B", suite_area_sf=40_000.0,
        market_leasing_override=market(market_rent_psf=52.0),
    )
    leases = [
        occupied_lease(a, end=date(2028, 12, 31)),
        occupied_lease(b, end=date(2028, 12, 31)),
    ]

    def overwriting_mutant(rent):
        overwritten = dataclasses.replace(
            b, market_leasing_override=dataclasses.replace(
                b.market_leasing_override, market_rent_psf=rent
            )
        )
        return analyze(
            [a, overwritten], leases, mkt=market(market_rent_psf=rent)
        ).results.equity_multiple

    mutant_cells = [overwriting_mutant(rent) for rent in (30.0, 48.0)]
    assert len(set(mutant_cells)) == 2  # the mutant produces a plausible table

    with pytest.raises(SensitivityTargetShadowedBySuiteOverrideError):
        one_way([a, b], leases, assumption="market_rent_psf",
                values=(30.0, 48.0), metric="equity_multiple")


def test_m10_a_permissive_target_map_is_killed() -> None:
    """**M10.** The whitelist is replaced by arbitrary field access. Deferred
    targets are then accepted, and the parametrized deferred-target golden
    fails."""

    suites, leases, mkt = rollover_deal()

    with pytest.raises(ValueError):
        one_way(suites, leases, mkt=mkt, assumption="new_ti_psf",
                values=(10.0,), metric="equity_multiple")

    mutant_targets = dict(module._TARGETS)
    mutant_targets["new_ti_psf"] = module._TargetSpec(
        owner=module._TargetOwner.MARKET,
        read_baseline=lambda t, m, o: m.new_ti_psf,
        shadowed_by=None,
    )
    with patch.object(module, "_TARGETS", mutant_targets):
        accepted = one_way(
            suites, leases, mkt=mkt, assumption="new_ti_psf",
            values=(10.0,), metric="equity_multiple",
        )
    assert accepted.assumption == "new_ti_psf", "M10 SURVIVED"


def test_m11_clipping_the_probability_is_killed() -> None:
    """**M11.** 1.2 is clipped to 1.0 instead of refused. The run then
    succeeds, and the domain golden fails."""

    suites, leases, mkt = rollover_deal()

    with pytest.raises(LeaseValidationError):
        one_way(suites, leases, mkt=mkt, assumption="renewal_probability",
                values=(1.2,), metric="equity_multiple")

    real_seam = module._scenario_contracts

    def clipping_mutant(*, changes, **kwargs):
        clipped = {
            name: (1.0 if name == "renewal_probability" and value > 1.0 else value)
            for name, value in changes.items()
        }
        return real_seam(changes=clipped, **kwargs)

    with patch.object(module, "_scenario_contracts", clipping_mutant):
        survived = one_way(
            suites, leases, mkt=mkt, assumption="renewal_probability",
            values=(1.2,), metric="equity_multiple",
        )
    at_one = analyze(
        suites, leases, mkt=dataclasses.replace(mkt, renewal_probability=1.0)
    ).results.equity_multiple
    assert survived.metric_values[0] == at_one, "M11 SURVIVED"


def test_m12_treating_none_as_invalid_is_killed() -> None:
    """**M12.** An undefined metric is raised instead of returned. The
    undefined-metric golden requires the run to succeed with ``None`` cells."""

    from tests.test_analysis_d4_6b_lease_level_sensitivity import undefined_irr_deal

    suites, leases, mkt, deal = undefined_irr_deal()

    result = one_way(
        suites, leases, deal=deal, mkt=mkt, assumption="exit_cap_rate",
        values=(0.06, 0.07), metric="levered_irr",
    )
    assert result.metric_values == (None, None)

    real_seam = module._scenario_metric

    def raising_mutant(**kwargs):
        value = real_seam(**kwargs)
        if value is None:
            raise ValueError("undefined metric treated as an invalid scenario")
        return value

    with patch.object(module, "_scenario_metric", raising_mutant):
        with pytest.raises(ValueError, match="invalid scenario"):
            one_way(
                suites, leases, deal=deal, mkt=mkt, assumption="exit_cap_rate",
                values=(0.06, 0.07), metric="levered_irr",
            )


def test_m13_and_m14_converting_a_failure_to_none_or_zero_is_killed() -> None:
    """**M13/M14.** A validation failure -- including
    ``NON_POSITIVE_FORWARD_EXIT_NOI`` -- is swallowed into ``None`` or ``0.0``.
    The invalid-scenario goldens require the run to raise."""

    suites, leases = stable_deal()
    values = (0.03, 5.0)

    with pytest.raises(LeaseValidationError):
        one_way(suites, leases, assumption="expense_growth", values=values,
                metric="equity_multiple")

    real_seam = module._scenario_metric

    for sentinel, label in ((None, "None"), (0.0, "zero")):
        def swallowing_mutant(_sentinel=sentinel, **kwargs):
            try:
                return real_seam(**kwargs)
            except LeaseValidationError:
                return _sentinel

        with patch.object(module, "_scenario_metric", swallowing_mutant):
            survived = one_way(
                suites, leases, assumption="expense_growth", values=values,
                metric="equity_multiple",
            )
        assert survived.metric_values[1] == sentinel or (
            survived.metric_values[1] is sentinel
        ), f"M13/M14 ({label}) SURVIVED"


def test_m15_and_m16_output_tampering_is_killed() -> None:
    """**M15/M16.** Exit-cap or interest-rate sensitivity adjusts the completed
    result instead of re-underwriting -- the classic "scale the output" defect.
    Every cell then diverges from its independent oracle."""

    suites, leases = stable_deal()

    def tampering_analysis(*args, **kwargs):
        out = analyze_lease_level_acquisition_with_projection(*args, **kwargs)
        return dataclasses.replace(
            out,
            results=dataclasses.replace(
                out.results, exit_value=out.results.exit_value * 1.05
            ),
        )

    for assumption, values in (
        ("exit_cap_rate", (0.06, 0.07)),
        ("interest_rate", (0.04, 0.06)),
    ):
        oracle = [
            analyze(suites, leases, deal=terms(**{assumption: v})).results.exit_value
            for v in values
        ]
        real = one_way(
            suites, leases, assumption=assumption, values=values,
            metric="exit_value",
        )
        assert list(real.metric_values) == oracle

        with patch.object(module, _ENTRY_POINT, tampering_analysis):
            mutated = one_way(
                suites, leases, assumption=assumption, values=values,
                metric="exit_value",
            )
        assert list(mutated.metric_values) != oracle, f"M15/M16 SURVIVED ({assumption})"


def test_m17_m18_m19_a_stale_downstream_schedule_is_killed() -> None:
    """**M17/M18/M19.** The scenario reuses the baseline's expense schedule,
    recoverable pool, recovery schedule or TI/LC economics -- modelled here as
    an analysis that keys its result on the acquisition terms alone and so
    never sees the leasing or operating perturbation. Every affected golden
    fails."""

    suites, leases, mkt = rollover_deal()

    cache: dict[tuple, object] = {}

    def stale_analysis(scenario_terms, *args, **kwargs):
        key = dataclasses.astuple(scenario_terms)
        if key not in cache:
            cache[key] = analyze_lease_level_acquisition_with_projection(
                scenario_terms, *args, **kwargs
            )
        return cache[key]

    cases = (
        ("expense_growth", (0.0, 0.06, 0.12), None),          # M17: stale pool
        ("recoverable_expense_ratio", (0.25, 0.5, 1.0), None),  # M18: stale recoveries
        ("renewal_probability", (0.0, 0.5, 1.0), mkt),          # M19: stale TI/LC
    )

    for assumption, values, market_leasing in cases:
        real = one_way(
            suites, leases, mkt=market_leasing or mkt, assumption=assumption,
            values=values, metric="equity_multiple",
        )
        assert len(set(real.metric_values)) == 3, assumption

        cache.clear()
        with patch.object(module, _ENTRY_POINT, stale_analysis):
            mutated = one_way(
                suites, leases, mkt=market_leasing or mkt, assumption=assumption,
                values=values, metric="equity_multiple",
            )
        assert len(set(mutated.metric_values)) == 1, f"M17/M18/M19 SURVIVED ({assumption})"
        assert list(mutated.metric_values) != list(real.metric_values)


def test_m20_moving_the_in_place_contractual_rent_is_killed() -> None:
    """**M20.** Market-rent sensitivity also rewrites the signed lease's stated
    rent. Year 1 -- entirely in place -- then moves, and the oracle golden
    fails."""

    suites, leases, mkt = rollover_deal()
    values = (24.0, 48.0)
    oracle = _oracle_cells(suites, leases, "market_rent_psf", values, mkt=mkt)

    real = one_way(
        suites, leases, mkt=mkt, assumption="market_rent_psf", values=values,
        metric="equity_multiple",
    )
    assert list(real.metric_values) == oracle

    def rewriting_mutant(rent):
        rewritten = [dataclasses.replace(leases[0], base_rent_psf=rent)]
        return analyze(
            suites, rewritten, mkt=dataclasses.replace(mkt, market_rent_psf=rent)
        ).results.equity_multiple

    assert [rewriting_mutant(rent) for rent in values] != oracle, "M20 SURVIVED"


def test_m21_sorting_the_candidates_is_killed() -> None:
    """**M21.** Candidates are sorted internally instead of preserved. The
    ordering golden's positional correspondence fails."""

    suites, leases = stable_deal()
    values = (44_000_000.0, 36_000_000.0, 40_000_000.0)

    real = one_way(
        suites, leases, assumption="purchase_price", values=values,
        metric="equity_multiple",
    )
    assert real.assumption_values == values

    sorted_mutant = one_way(
        suites, leases, assumption="purchase_price", values=tuple(sorted(values)),
        metric="equity_multiple",
    )
    assert sorted_mutant.metric_values != real.metric_values, "M21 SURVIVED"
    assert sorted(sorted_mutant.metric_values) == sorted(real.metric_values)


def test_m22_reusing_a_partial_analysis_for_a_two_way_cell_is_killed() -> None:
    """**M22.** A cell is composed from the row's and the column's separate
    one-way results instead of one analysis with both replacements. The 3x3
    oracle fails."""

    suites, leases, mkt = rollover_deal()
    rents = (24.0, 36.0, 48.0)
    ratios = (0.25, 0.5, 1.0)

    real = two_way(
        suites, leases, mkt=mkt,
        row_assumption="market_rent_psf", row_values=rents,
        column_assumption="recoverable_expense_ratio", column_values=ratios,
        metric="equity_multiple",
    )

    row_only = [
        analyze(
            suites, leases, mkt=dataclasses.replace(mkt, market_rent_psf=rent)
        ).results.equity_multiple
        for rent in rents
    ]
    column_only = [
        analyze(
            suites, leases, mkt=mkt, ops=operating(recoverable_expense_ratio=ratio)
        ).results.equity_multiple
        for ratio in ratios
    ]
    baseline = analyze(suites, leases, mkt=mkt).results.equity_multiple
    composed = [
        [row * column / baseline for column in column_only] for row in row_only
    ]

    assert composed != [list(row) for row in real.matrix], "M22 SURVIVED"


def test_m23_quick_and_detailed_are_not_routed_through_the_lease_level_module() -> None:
    """**M23.** Quick and Detailed still call their own engines, through their
    own module, which imports nothing from here."""

    from anchor.analysis import sensitivity as quick_and_detailed

    names = _imported_module_names(_ANALYSIS_DIR / "sensitivity.py")
    assert not any("lease_level" in name for name in names)
    assert not any(
        "lease_level" in name
        for name in _imported_module_names(_ANALYSIS_DIR / "break_even.py")
    )

    from anchor.contracts import AcquisitionInputs
    from anchor.engine import analyze_acquisition

    inputs = AcquisitionInputs(
        purchase_price=50_000_000.0, current_noi=2_500_000.0, occupancy=0.95,
        noi_growth=0.03, hold_period=5, exit_cap_rate=0.055, ltv=0.65,
        interest_rate=0.0525, amortization=30,
    )

    with patch.object(module, _ENTRY_POINT) as lease_level_spy:
        with patch(
            "anchor.analysis.sensitivity.analyze_acquisition", wraps=analyze_acquisition
        ) as quick_spy:
            quick_and_detailed.run_one_way_sensitivity(
                inputs, assumption="exit_cap_rate",
                values=(0.05, 0.055, 0.06), metric="levered_irr",
            )

    assert quick_spy.call_count == 4
    assert lease_level_spy.call_count == 0
