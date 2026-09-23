"""Refinance & Capital Events V1 Stage 1 -- mutation proofs.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 8 to 12, 17 and
18.3. Each mutant is the specific wrong thing a reviewer would worry about --
one exact textual edit to one real production module -- and is shown to be
caught by a named fixture, not asserted to be impossible.

**How a mutant runs.** The module's own source file in this repository is read
(its path is asserted first, so the known scratch-copy ``pythonpath`` trap
cannot run a mutant against another tree), the edit is applied exactly once,
and the result is executed in-process as a fresh module. Every function and
class the mutated module defines is then patched, for the duration of the proof
only, wherever the real one is referenced -- in the module itself and in each
module that imported it by name. The fixture must pass on the real engine,
fail under the mutant, and pass again once it is withdrawn. Nothing is written
to disk.
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

import test_refinance_v1_execution as execution_tests
import test_refinance_v1_partnership as partnership_tests
import test_refinance_v1_payoff_authority as payoff_tests
import test_refinance_v1_sizing as sizing_tests
from anchor.capital_structure import refinance as cs_refinance
from anchor.capital_structure import refinance_execution as cs_refinance_execution
from anchor.capital_structure.contracts import CapitalStructureError
from anchor.capital_structure.execution_contracts import CapitalStructureExecutionError
from anchor.engine import acquisition_debt_balance as engine_balance
from anchor.partnership import common_equity as partnership_seam
from anchor.partnership.contracts import PartnershipExecutionError
from anchor.valuation.contracts import ValuationError

_SRC = (Path(__file__).resolve().parents[1] / "src" / "anchor").resolve()

def _referencing_modules() -> tuple[ModuleType, ...]:
    """Every loaded module that may hold a mutated name by reference: the
    production package, and the refinance test modules whose fixtures call
    production functions and catch production exception classes by name. A
    fixture must never keep the real function, or catch only the real class,
    while the mutant runs -- that would count a kill for the wrong reason."""

    return tuple(
        module
        for name, module in sorted(sys.modules.items())
        if isinstance(module, ModuleType)
        and (name == "anchor" or name.startswith("anchor.") or name.startswith(("test_refinance_v1", "_refinance_v1")))
    )


def _mutant(module: ModuleType, edits: tuple[tuple[str, str], ...]) -> ModuleType:
    path = Path(module.__file__ or "").resolve()  # type: ignore[arg-type]
    assert path.is_relative_to(_SRC), path
    source = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    for old, new in edits:
        assert source.count(old) == 1, (path.name, old)
        source = source.replace(old, new)
    mutated = ModuleType(module.__name__)
    mutated.__dict__.update({"__file__": module.__file__, "__package__": module.__package__, "__name__": module.__name__})
    exec(compile(source, str(path), "exec"), mutated.__dict__)  # noqa: S102 - a deliberate in-process mutant
    return mutated


def _install(patch: pytest.MonkeyPatch, module: ModuleType, mutated: ModuleType) -> None:
    targets = _referencing_modules()
    assert module in targets
    for name, original in vars(module).items():
        if not (inspect.isfunction(original) or inspect.isclass(original)):
            continue
        if getattr(original, "__module__", None) != module.__name__ or name not in vars(mutated):
            continue
        for target in targets:
            for attribute, value in list(vars(target).items()):
                if value is original:
                    patch.setattr(target, attribute, vars(mutated)[name])


def _killed(
    monkeypatch: pytest.MonkeyPatch, fixture: Callable[[], None], module: ModuleType, *edits: tuple[str, str]
) -> None:
    fixture()
    with monkeypatch.context() as patch:
        _install(patch, module, _mutant(module, edits))
        # A kill is an assertion, a typed refusal, the engine's own typed defect
        # guard, or pytest's "did not raise"; never an incidental TypeError or
        # ValueError.
        with pytest.raises(
            (
                AssertionError,
                CapitalStructureError,
                CapitalStructureExecutionError,
                PartnershipExecutionError,
                ValuationError,
                pytest.fail.Exception,
            )
        ):
            fixture()
    fixture()


def _f11() -> None:
    sizing_tests.test_f11_a_missing_timepoint_makes_ltv_unavailable_and_dscr_still_reported()


# =============================================================================
# Valuation and NOI dependencies (R-C, INV-13, INV-18)
# =============================================================================


def test_m01_a_purchase_price_fallback_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _f11,
        cs_refinance,
        (
            "value = None if reason is not None or value_dependency is None else value_dependency.value",
            "value = price_basis.amount if reason is not None or value_dependency is None else value_dependency.value",
        ),
        ("if value is None or reason is not None:", "if value is None:"),
    )


def test_m02_another_timepoint_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _f11,
        cs_refinance,
        (
            "found = None if valuations is None else valuations.find(reference.timepoint_id)",
            "found = None if valuations is None else (valuations.find(reference.timepoint_id) or (valuations.valuations[0] if valuations.valuations else None))",
        ),
    )


def test_m03_nearest_month_matching_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        sizing_tests.test_f14d_a_valuation_at_another_month_is_never_the_nearest_match,
        cs_refinance,
        ("if found.model_month != model_month:", "if False:"),
    )


def test_m04_another_scopes_value_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        sizing_tests.test_f14c_a_valuation_without_a_cell_for_this_unit_is_scope_not_covered,
        cs_refinance,
        ("if result.unit_id == event.scope.unit_id), None)", "if True), None)"),
    )


def test_m05_requiring_a_valuation_for_dscr_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        sizing_tests.test_f3b_dscr_only_executes_with_no_valuation_anywhere,
        cs_refinance,
        (
            "noi = forward_noi(event.scope, model_month=model_month, unit=unit, investment=investment)",
            "noi = forward_noi(event.scope, model_month=model_month, unit=unit, investment=investment) if valuations is not None else None",
        ),
    )


def test_m06_a_valuation_moving_a_dscr_only_result_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fixture() -> None:
        sizing_tests.test_inv_18_a_dscr_only_result_is_invariant_to_every_valuation(
            lambda terms, results: sizing_tests.unit_authority(terms, results, methods={"u1": sizing_tests.stated_value(1.0)})
        )

    _killed(
        monkeypatch,
        fixture,
        cs_refinance,
        (
            "noi = forward_noi(event.scope, model_month=model_month, unit=unit, investment=investment)",
            "noi = (valuations.valuations[0].unit_results[0].value * 0.064) if valuations is not None and valuations.valuations else forward_noi(event.scope, model_month=model_month, unit=unit, investment=investment)",
        ),
    )


# =============================================================================
# Sizing (R-D)
# =============================================================================


def test_m07_dropping_an_unavailable_constraint_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(monkeypatch, _f11, cs_refinance, ("if len(known) != len(capacities):", "if not known:"))


def test_m08_max_in_place_of_min_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fixture() -> None:
        sizing_tests.test_gross_proceeds_are_the_least_enabled_capacity(
            {"fixed": 7_500_000.0, "ltv": 0.65, "dscr": 2.0},
            {sizing_tests.FIXED: 7_500_000, sizing_tests.LTV: 8_125_000, sizing_tests.DSCR: 8_000_000},
            7_500_000,
            (sizing_tests.FIXED,),
        )

    _killed(monkeypatch, fixture, cs_refinance, ("proceeds = min(known)", "proceeds = max(known)"))


def test_m09_cross_scope_noi_and_debt_in_sizing_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        execution_tests.test_f15_another_units_noi_never_moves_this_units_event,
        cs_refinance_execution,
        (
            "unit_id=unit.unit_id, terms=unit.terms, results=unit.results, legacy_loan=loans.get(unit.unit_id)",
            "unit_id=unit.unit_id, terms=ordered[-1].terms, results=ordered[-1].results, legacy_loan=loans.get(unit.unit_id)",
        ),
    )


def test_m10_keeping_the_old_loan_on_a_non_executable_event_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        sizing_tests.test_f22a_a_non_positive_capacity_is_not_executable_and_never_keeps_the_old_loan,
        cs_refinance_execution,
        ("    elif plan is not None:\n        unavailable = plan.affected_position_ids", "    elif plan is not None:\n        unavailable = frozenset()"),
    )


# =============================================================================
# Timing and the payoff authority (R-E, R-M)
# =============================================================================


def test_m11_a_payoff_before_the_month_m_payment_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        payoff_tests.test_the_zero_rate_base_case_is_exact,
        engine_balance,
        ("balance_after_month=ending_balances[min(model_month, loan_life) - 1],", "balance_after_month=ending_balances[min(model_month, loan_life) - 2],"),
    )


def test_m12_replacement_service_at_the_event_month_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        execution_tests.test_f9_the_replacement_serves_from_month_25_and_is_repaid_at_the_sale,
        cs_refinance,
        ("            model_month=item.model_month + model_month,\n", "            model_month=item.model_month + model_month - 1,\n"),
    )


def test_m13_old_service_retained_after_the_event_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        execution_tests.test_f5_positive_net_proceeds_are_a_common_equity_distribution,
        cs_refinance_execution,
        ("return (*levered[: hold_year + 1], *unlevered[hold_year + 1 :])", "return levered"),
    )


def test_m14_a_second_amortization_outside_the_debt_authority_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fixture() -> None:
        payoff_tests.test_the_refinance_payoff_is_the_services_balance(
            {"interest_rate": 0.06, "amortization": 25, "io_period": 0}
        )

    _killed(
        monkeypatch,
        fixture,
        cs_refinance,
        ("                    payoff=balance.balance_after_month,\n", "                    payoff=unit.results.loan_amount * (1 - model_month / 300),\n"),
    )


def test_m15_bypassing_the_payoff_reconciliation_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fixture() -> None:
        payoff_tests.test_each_mismatch_is_refused_by_name("remaining_loan_balance", "sale-date remaining balance")

    _killed(
        monkeypatch,
        fixture,
        engine_balance,
        ('    _reconcile("sale-date remaining balance", ending_balances[-1], results.remaining_loan_balance)\n', ""),
    )


# =============================================================================
# Settlement and Common Equity (R-F, INV-2, INV-5, INV-12)
# =============================================================================


def test_m16_routing_the_payoff_through_the_annual_claim_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        execution_tests.test_inv_5_an_authored_retirement_conserves_every_year,
        cs_refinance_execution,
        ("if item.kind not in _EVENT_SETTLED_KINDS\n", "if item.kind is not PositionCashFlowKind.REFINANCE_FUNDING\n"),
    )


def test_m17_negative_event_cash_withheld_from_common_equity_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        execution_tests.test_f6_negative_net_cash_is_an_explicit_contribution_not_a_funding_requirement,
        cs_refinance_execution,
        (
            "event_cash={event_hold_year(event): plan.net_event_cash} if plan.executed else {},",
            "event_cash={event_hold_year(event): max(plan.net_event_cash, 0.0)} if plan.executed else {},",
        ),
    )


def test_m18_zero_filling_an_unavailable_result_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(monkeypatch, _f11, cs_refinance_execution, ("    if not_executed and not unresolved:\n", "    if False:\n"))


def test_m19_a_proceeds_cure_of_an_earlier_shortfall_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Event cash joining the residual *before* the year-``y`` claims settle
    would let proceeds cure an operating shortfall."""

    _killed(
        monkeypatch,
        execution_tests.test_proceeds_never_cure_an_earlier_operating_shortfall,
        cs_refinance_execution,
        (
            "    residual = list(authority)\n",
            "    residual = list(authority)\n    if plan is not None and plan.executed:\n        residual[event_hold_year(plan.event)] = residual[event_hold_year(plan.event)] + plan.net_event_cash\n",
        ),
    )


# =============================================================================
# Partnership (R-I, R-O, INV-8)
# =============================================================================


def test_m20_a_partnership_fed_without_the_event_cash_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        partnership_tests.test_f16_a_distribution_year_conserves_through_the_ordinary_tiers,
        partnership_seam,
        (
            "return CommonEquityCashFlowInput(cadence=CashFlowCadence.ANNUAL, cash_flows=common_equity.cash_flows)",
            "return CommonEquityCashFlowInput(cadence=CashFlowCadence.ANNUAL, cash_flows=getattr(common_equity, 'recurring_cash_flows', None) or common_equity.cash_flows)",
        ),
    )


def test_m21_refusing_the_refinance_reason_at_the_seam_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        partnership_tests.test_an_unavailable_refinance_makes_the_partnership_unavailable_with_its_reason,
        partnership_seam,
        ("        if not refinance_unavailable and (\n", "        if (\n"),
    )


def test_the_mutation_harness_patches_this_repositorys_modules() -> None:
    for module in (cs_refinance, cs_refinance_execution, engine_balance, partnership_seam):
        assert Path(module.__file__ or "").resolve().is_relative_to(_SRC), module.__file__  # type: ignore[arg-type]
