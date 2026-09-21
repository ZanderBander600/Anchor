"""Phase 7 Gate P7.10 Stage 1 -- mutation proofs M1-M5.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 5.3, 5.5, 6
and 18.1. Each mutant is the specific wrong thing a reviewer would worry about,
applied to the **real** engine in-process (the P7.8B and P7.9 precedent) and
shown to be caught by the named fixture -- not asserted to be impossible.

Mutants are applied by patching the imported modules, never on scratch copies,
so the known ``pythonpath`` trap cannot let a mutant run against a different
tree: every mutant first asserts the module it patches is this repository's
``src/anchor/valuation`` or ``src/anchor/capital_structure``, and every proof
first checks its fixture passes unmutated.

The five invariants proven here are the ones that decide money:

- **M1** the forward-NOI mapping -- a valuation date capitalises the year that
  follows it, never the year behind it;
- **M2** a non-positive forward NOI is unavailable, never floored into a value;
- **M3** a Unit without a value is never rendered as zero inside an Investment
  total;
- **M4a** an unresolved ``PctOfValue`` funding is never quietly substituted
  with a plausible amount;
- **M4b** and is never read as zero;
- **M5** the exit month stays reserved for the system Exit view.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _p7_10_fixtures import (  # type: ignore[import-not-found]
    BASE_NOI,
    GROWTH,
    HOLD,
    cap,
    instruction,
    timepoint,
    unit,
    variant,
)
from _p7_8_fixtures import round_unit  # type: ignore[import-not-found]

from anchor.capital_structure import funding as cs_funding
from anchor.capital_structure import execution_validation as cs_execution_validation
from anchor.capital_structure.execution_contracts import (
    CapitalStructureExecutionError,
    ExecutionIssueCode,
)
from anchor.valuation import engine as valuation_engine
from anchor.valuation.contracts import (
    ResolvedValuationFunding,
    ValuationError,
    UnitValuationResult,
    ValuationAvailability,
    ValuationMethodKind,
    ValuationScopeKind,
)

_SRC = (Path(__file__).resolve().parents[1] / "src" / "anchor").resolve()
_VALUATION_DIR = (_SRC / "valuation").resolve()
_CAPITAL_DIR = (_SRC / "capital_structure").resolve()


def _mutate(patch: pytest.MonkeyPatch, module: ModuleType, name: str, replacement: Any, directory: Path) -> None:
    assert Path(module.__file__).resolve().parent == directory, module.__file__  # type: ignore[arg-type]
    assert hasattr(module, name), name
    patch.setattr(module, name, replacement)


def _killed(
    monkeypatch: pytest.MonkeyPatch,
    fixture: Callable[[], None],
    mutants: tuple[tuple[ModuleType, str, Any, Path], ...],
) -> None:
    """``fixture`` passes on the real engine, fails under the mutant, and
    passes again once the mutant is withdrawn."""

    fixture()
    with monkeypatch.context() as patch:
        for module, name, replacement, directory in mutants:
            _mutate(patch, module, name, replacement, directory)
        # a fixture fails by assertion, by an unexpected refusal, or -- for a
        # refusal fixture -- by pytest's own "did not raise"
        with pytest.raises(
            (
                AssertionError,
                CapitalStructureExecutionError,
                ValuationError,
                ZeroDivisionError,
                pytest.fail.Exception,
            )
        ):
            fixture()
    fixture()


# =============================================================================
# The fixtures each mutant must break
# =============================================================================


def _forward_mapping_holds() -> None:
    """Hold-year end 24 capitalises Year 3 NOI -- 968,000 by hand -- not
    Year 2's 880,000."""

    result = valuation_engine.resolve_unit_valuation(instruction(method=cap(0.05)), unit=unit(), model_month=24)
    assert result.value == pytest.approx(BASE_NOI * (1.0 + GROWTH) ** 2 / 0.05)


def _non_positive_noi_is_unavailable() -> None:
    flat = unit(noi_by_year=(0.0,) * HOLD)
    result = valuation_engine.resolve_unit_valuation(instruction(method=cap(0.06)), unit=flat, model_month=0)
    assert result.status is ValuationAvailability.UNAVAILABLE
    assert result.value is None


def _an_incomplete_investment_has_no_value() -> None:
    result = valuation_engine.resolve_investment_valuation(
        timepoint(instructions=(instruction("u1", cap(0.05)), instruction("u2", cap(0.05)))),
        variant=variant(unit("u1"), unit("u2", noi_by_year=(0.0,) * HOLD)),
    )
    assert result.status is ValuationAvailability.UNAVAILABLE
    assert result.value is None


def _an_unresolved_funding_refuses_execution() -> None:
    """Reaches the executor through the whole P7.10 seam, so a mutant that
    silently funds zero is caught as a missing refusal."""

    from test_p7_10_pct_of_value import (  # type: ignore[import-not-found]
        _as_is,
        _authority,
        _execute,
        _valued_position,
    )

    terms, results = round_unit(current_noi=0.0)
    with pytest.raises(CapitalStructureExecutionError) as raised:
        _execute(_valued_position(), _authority(_as_is(), terms, results), terms, results)
    assert {issue.code for issue in raised.value.issues} == {ExecutionIssueCode.UNRESOLVED_VALUATION_FUNDING}


def _the_exit_month_is_reserved() -> None:
    result = valuation_engine.resolve_unit_valuation(instruction(method=cap(0.05)), unit=unit(), model_month=12 * HOLD)
    assert result.status is ValuationAvailability.UNAVAILABLE
    assert result.value is None


# =============================================================================
# M1 -- the forward-NOI mapping
# =============================================================================


def test_m1_capitalising_the_trailing_year_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worry: a valuation date reads the year *behind* it, valuing an
    asset on income its buyer will never receive."""

    def trailing(unit: Any, *, model_month: int) -> float:
        index = max(model_month // 12 - 1, 0)
        return unit.noi_by_year[index]

    _killed(
        monkeypatch,
        _forward_mapping_holds,
        ((valuation_engine, "forward_noi_at", trailing, _VALUATION_DIR),),
    )


# =============================================================================
# M2 -- a non-positive forward NOI
# =============================================================================


def test_m2_flooring_a_non_positive_noi_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worry: a zero or negative NOI is floored, smoothed or substituted
    so that a value appears where none exists."""

    def floored(unit: Any, *, model_month: int) -> float:
        index = model_month // 12
        return max(unit.noi_by_year[index], 1.0)

    _killed(
        monkeypatch,
        _non_positive_noi_is_unavailable,
        ((valuation_engine, "forward_noi_at", floored, _VALUATION_DIR),),
    )


# =============================================================================
# M3 -- a Unit without a value inside an Investment total
# =============================================================================


def test_m3_reading_a_missing_unit_value_as_zero_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worry: a Unit with no value is counted as zero, and the partial sum
    of the rest is presented as the Investment value."""

    real = valuation_engine.resolve_unit_valuation

    def zero_filled(instruction: Any, *, unit: Any, model_month: int) -> UnitValuationResult:
        result = real(instruction, unit=unit, model_month=model_month)
        if result.status is ValuationAvailability.AVAILABLE:
            return result
        return UnitValuationResult(
            unit_id=result.unit_id,
            model_month=result.model_month,
            method_kind=ValuationMethodKind.DIRECT_CAP,
            analyst_supplied=False,
            status=ValuationAvailability.AVAILABLE,
            value=0.0,
            forward_noi=None,
            cap_rate=None,
            evidence_id=None,
            unavailable_reason=None,
            unavailable_message=None,
        )

    _killed(
        monkeypatch,
        _an_incomplete_investment_has_no_value,
        ((valuation_engine, "resolve_unit_valuation", zero_filled, _VALUATION_DIR),),
    )


# =============================================================================
# M4 -- an unresolved PctOfValue funding
# =============================================================================


def _substituting(scope_value: float) -> Any:
    def resolved(position: Any, event: Any, rule: Any, *, authority: Any) -> ResolvedValuationFunding:
        return ResolvedValuationFunding(
            event_id=event.event_id,
            position_id=position.position_id,
            timepoint_id=rule.timepoint_id,
            scope_kind=ValuationScopeKind.UNIT,
            unit_id=position.scope.unit_id,
            model_month=event.model_month,
            pct=rule.pct,
            scope_value=scope_value,
            amount=rule.pct * scope_value,
        )

    return resolved


def test_m4a_substituting_a_plausible_amount_for_an_unresolved_funding_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worry: a funding whose valuation did not resolve falls back to some
    other basis -- here the $10,000,000 purchase price -- so the analysis
    succeeds on a number no valuation ever produced. The refusal disappears,
    and the fixture catches its absence."""

    substitute = _substituting(10_000_000.0)
    _killed(
        monkeypatch,
        _an_unresolved_funding_refuses_execution,
        (
            (cs_funding, "resolve_valuation_funding", substitute, _CAPITAL_DIR),
            (cs_execution_validation, "resolve_valuation_funding", substitute, _CAPITAL_DIR),
        ),
    )


def test_m4b_reading_an_unresolved_funding_as_zero_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worry: it is advanced as zero dollars instead. Nothing downstream
    is prepared for a position funded with nothing -- the structural metrics
    divide by the funded amount -- so the mutant fails loudly rather than
    reporting a capital structure that was never funded."""

    zero = _substituting(0.0)
    _killed(
        monkeypatch,
        _an_unresolved_funding_refuses_execution,
        (
            (cs_funding, "resolve_valuation_funding", zero, _CAPITAL_DIR),
            (cs_execution_validation, "resolve_valuation_funding", zero, _CAPITAL_DIR),
        ),
    )


# =============================================================================
# M5 -- the reserved exit month
# =============================================================================


def test_m5_letting_a_stored_definition_occupy_the_exit_month_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worry: a stored definition values the exit month, producing a
    second terminal value beside D6's that can drift from it (R-B)."""

    def always_storable(model_month: int, *, hold_period: int) -> None:
        return None

    _killed(
        monkeypatch,
        _the_exit_month_is_reserved,
        ((valuation_engine, "timepoint_month_reason", always_storable, _VALUATION_DIR),),
    )
