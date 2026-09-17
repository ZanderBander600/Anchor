"""Phase 7 Gate P7.9 Stage 1 -- mutation proofs M1-M10.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 16.6. Each mutant
is the specific wrong thing a reviewer would worry about, applied to the
**real** engine in-process (the P7.8B precedent) and shown to be caught by the
named fixture -- not asserted to be impossible.

Applying mutants by patching the imported modules, rather than on scratch
copies, removes the known ``pythonpath`` trap: every mutant first asserts the
module it patches is this repository's ``src/anchor/partnership``, and every
proof first checks the fixture passes unmutated.

The one equivalent mutant is recorded, not claimed as a kill: under v1's only
contribution rule, a pro-rata split that reads commitment shares instead of
cumulative contributions changes nothing (proven below).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from _p7_9_fixtures import (  # type: ignore[import-not-found]
    ACCRUED_FIRST,
    CAPITAL_FIRST,
    COMPOUND,
    SIMPLE,
    ALL_EQUITY,
    F1_SERIES,
    F2_SERIES,
    F3_SERIES,
    F5_SERIES,
    F6_SERIES,
    F9_SERIES,
    F10_SERIES,
    by_partner,
    by_tier,
    close,
    f1_terms,
    f2_terms,
    f3_terms,
    f5_terms,
    f7_terms,
    f10_terms,
    f11_terms,
    run,
)
from anchor.capital_structure.contracts import AccrualConvention
from anchor.partnership import (
    PartnerRole,
    PartnershipExecutionError,
    PartnershipExecutionIssueCode,
    SimpleDistributionOrder,
    accounts,
    allocation,
    attribution,
    waterfall,
)
from anchor.partnership.accounts import HurdleAccountState

_PACKAGE_DIR = (Path(__file__).resolve().parents[1] / "src" / "anchor" / "partnership").resolve()


def mutate(monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str, replacement: Any) -> None:
    assert Path(module.__file__).resolve().parent == _PACKAGE_DIR, module.__file__  # type: ignore[arg-type]
    assert hasattr(module, name), name
    monkeypatch.setattr(module, name, replacement)


def killed(
    monkeypatch: pytest.MonkeyPatch, fixture: Callable[[], None], module: ModuleType, name: str, replacement: Any
) -> None:
    """``fixture`` passes on the real engine, fails under the mutant, and
    passes again once the mutant is withdrawn."""

    fixture()
    with monkeypatch.context() as patch:
        mutate(patch, module, name, replacement)
        # a fixture fails by assertion, by an unexpected refusal, or -- for a
        # refusal fixture -- by pytest's own "did not raise"
        with pytest.raises((AssertionError, PartnershipExecutionError, pytest.fail.Exception)):
            fixture()
    fixture()


# =============================================================================
# Fixtures used as kill conditions
# =============================================================================


def f1_holds() -> None:
    tiers = by_tier(run(f1_terms(), *F1_SERIES))
    assert close(tiers["pref"].amounts[3], 1_311_552.0)
    assert close(tiers["catch_up"].amounts[3], 67_888.0)
    assert close(tiers["promote_1"].amounts[3], 136_624.0)
    assert close(by_partner(run(f1_terms(), *F1_SERIES))["gp"].promote_earned, 124_393.60)


def f2_holds() -> None:
    assert close(by_tier(run(f2_terms(SIMPLE), *F2_SERIES))["pref"].amounts[2], 1_160_000.0)
    assert close(by_tier(run(f2_terms(COMPOUND), *F2_SERIES))["pref"].amounts[2], 1_166_400.0)


def f3_holds() -> None:
    assert close(by_tier(run(f3_terms(ACCRUED_FIRST), *F3_SERIES))["pref"].amounts[3], 1_190_000.0)
    capital_first = by_tier(run(f3_terms(CAPITAL_FIRST), *F3_SERIES))["pref"]
    assert close(capital_first.conditions[2].accrual, 68_400.0)
    assert close(capital_first.amounts[3], 1_182_000.0)


def f6_holds() -> None:
    assert close(by_tier(run(f5_terms(), *F6_SERIES))["roc"].amounts[2], 900_000.0)
    assert close(by_tier(run(f5_terms(ALL_EQUITY), *F6_SERIES))["roc"].amounts[2], 1_000_000.0)


def catch_up_closes() -> None:
    record = by_tier(run(f1_terms(), *F1_SERIES))["catch_up"].catch_up_records[0]
    assert close(record.recipient_profit_at_exit, 0.2 * record.partnership_profit_at_exit)


def f9_holds() -> None:
    tiers = by_tier(run(f5_terms(with_catch_up=True), *F9_SERIES))
    assert tiers["catch_up"].amounts[2] == 0.0
    assert close(tiers["residual"].amounts[2], 50_000.0)


def f5_and_f7_loss_hold() -> None:
    assert by_partner(run(f5_terms(), *F5_SERIES))["gp"].promote_earned == 0.0
    assert by_partner(run(f7_terms(), -1_000_000.0, 0.0, 800_000.0))["gp"].promote_earned == 0.0


def non_participant_gp_holds() -> None:
    gp = by_partner(run(f1_terms(participants=()), *F1_SERIES))["gp"]
    assert gp.role is PartnerRole.GP
    assert gp.promote_earned is None and gp.promote_attribution_by_tier is None


def f7_holds() -> None:
    gp = by_partner(run(f7_terms(), -1_000_000.0, 0.0, 1_500_000.0))["gp"]
    assert close(gp.total_benchmark_distributions, 75_000.0)
    assert close(gp.promote_earned, 50_000.0)


def f11_refuses() -> None:
    with pytest.raises(PartnershipExecutionError) as caught:
        run(f11_terms(), 0.0, 500.0, -1_000.0, 2_000.0)
    assert [issue.code for issue in caught.value.issues] == [PartnershipExecutionIssueCode.NO_CONTRIBUTIONS_FOR_PRO_RATA_SPLIT]


# =============================================================================
# The mutants
# =============================================================================


def test_m1_cash_accrues_in_its_own_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: accrual timing matches ``evaluate_irr``. The mutant lets a
    contribution earn a year in the period it is made."""

    real = accounts.apply_contribution

    def mutant(state: HurdleAccountState, condition: Any, amount: float) -> HurdleAccountState:
        rate = getattr(condition, "rate", 0.0)
        return real(state, condition, amount * (1.0 + rate))

    killed(monkeypatch, f1_holds, accounts, "apply_contribution", mutant)


def test_m2_simple_compounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: SIMPLE never accrues on accrued return (PW-3)."""

    real = accounts.accrue

    def mutant(state: HurdleAccountState, condition: Any) -> tuple[HurdleAccountState, float]:
        if getattr(condition, "accrual_convention", None) is AccrualConvention.SIMPLE:
            accrual = condition.rate * max(0.0, state.outstanding_capital + state.accrued_return)
            accrued = state.accrued_return + accrual
            return HurdleAccountState(
                balance=state.outstanding_capital + accrued,
                outstanding_capital=state.outstanding_capital,
                accrued_return=accrued,
                cumulative_contributions=state.cumulative_contributions,
                cumulative_distributions=state.cumulative_distributions,
            ), accrual
        return real(state, condition)

    killed(monkeypatch, f2_holds, accounts, "accrue", mutant)


def test_m3_capital_first_executes_as_accrued_return_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: the stated SIMPLE distribution order governs."""

    real = accounts.apply_simple_distribution

    def mutant(capital: float, accrued: float, amount: float, order: SimpleDistributionOrder) -> tuple[float, float]:
        return real(capital, accrued, amount, SimpleDistributionOrder.ACCRUED_RETURN_FIRST)

    killed(monkeypatch, f3_holds, accounts, "apply_simple_distribution", mutant)


def test_m4_the_subject_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: the hurdle subject (Q20). The mutant aggregates every
    partner's flows whatever the subject."""

    def mutant(amounts: dict[str, float], members: tuple[str, ...]) -> float:
        return sum(amounts[partner_id] for partner_id in sorted(amounts))

    killed(monkeypatch, f6_holds, waterfall, "subject_flow", mutant)


def test_m5_the_catch_up_divides_by_its_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: the catch-up closed form divides by ``c - tau`` (Q4)."""

    def mutant(*, profit: float, recipient_profit: float, rate: float, target: float) -> float:
        if profit <= 0.0:
            return 0.0
        return max(0.0, (target * profit - recipient_profit) / rate)

    killed(monkeypatch, f1_holds, waterfall, "catch_up_capacity", mutant)
    killed(monkeypatch, catch_up_closes, waterfall, "catch_up_capacity", mutant)


def test_m6_the_positive_profit_domain_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: no catch-up while partnership profit is not positive."""

    def mutant(*, profit: float, recipient_profit: float, rate: float, target: float) -> float:
        return max(0.0, (target * profit - recipient_profit) / (rate - target))

    killed(monkeypatch, f9_holds, waterfall, "catch_up_capacity", mutant)


def test_m7_promote_includes_returned_capital(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: Promote Earned excludes returned capital (Q23, R-B). The
    mutant treats every distribution as profit, so Promote Earned becomes the
    distribution difference."""

    def mutant(total_distributions: float, total_contributions: float) -> tuple[float, float]:
        return 0.0, total_distributions

    killed(monkeypatch, f5_and_f7_loss_hold, attribution, "capital_and_profit", mutant)


def test_m8_a_gp_role_implies_participation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: no role inference. The mutant reports promote for any GP."""

    real = waterfall._partner_result

    def mutant(partnership: Any, partner_id: str, **kwargs: Any) -> Any:
        partner = next(item for item in partnership.partners if item.partner_id == partner_id)
        if partner.role is PartnerRole.GP:
            kwargs["is_participant"] = True
        return real(partnership, partner_id, **kwargs)

    killed(monkeypatch, non_participant_gp_holds, waterfall, "_partner_result", mutant)


def test_m9_the_benchmark_reads_the_commitments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: the benchmark is the stated table, independent of
    commitments (Q2, R-A)."""

    killed(monkeypatch, f7_holds, allocation, "benchmark_shares", allocation.commitment_shares)


def test_m10_a_zero_denominator_falls_back_to_equal_shares(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant: a deterministic refusal, never a silent substitute."""

    real = allocation.pro_rata_by_contribution_shares

    def mutant(cumulative: dict[str, float]) -> dict[str, float] | None:
        shares = real(cumulative)
        if shares is None:
            return {partner_id: 1.0 / len(cumulative) for partner_id in cumulative}
        return shares

    killed(monkeypatch, f11_refuses, allocation, "pro_rata_by_contribution_shares", mutant)


def test_the_commitment_reading_pro_rata_mutant_is_equivalent_under_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recorded, not claimed: with ``PRO_RATA_BY_COMMITMENT`` contributions, a
    pro-rata split read from commitment shares is the same split (within
    floating-point residue). No fixture can kill it until a second contribution
    rule exists."""

    baseline = by_partner(run(f10_terms(pro_rata=True), *F10_SERIES))

    def mutant(cumulative: dict[str, float]) -> dict[str, float] | None:
        if sum(cumulative.values()) <= 0.0:
            return None
        return {"gp": 0.1, "lp": 0.9}

    mutate(monkeypatch, allocation, "pro_rata_by_contribution_shares", mutant)
    mutated = by_partner(run(f10_terms(pro_rata=True), *F10_SERIES))
    for partner_id in ("lp", "gp"):
        assert abs(mutated[partner_id].total_distributions - baseline[partner_id].total_distributions) <= 1e-6


def test_every_mutant_targets_a_real_engine_function() -> None:
    for module, name in (
        (accounts, "apply_contribution"), (accounts, "accrue"), (accounts, "apply_simple_distribution"),
        (waterfall, "subject_flow"), (waterfall, "catch_up_capacity"), (waterfall, "_partner_result"),
        (attribution, "capital_and_profit"), (allocation, "benchmark_shares"), (allocation, "pro_rata_by_contribution_shares"),
    ):
        assert Path(module.__file__).resolve().parent == _PACKAGE_DIR  # type: ignore[arg-type]
        assert callable(getattr(module, name))
