"""Phase 7 Gate P7.9 -- the benchmark decomposition, Promote Earned, benchmark
capital subordination and tier attribution.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 11
(ratified; R-A to R-E); that document governs on any discrepancy.

**Whole-hold decomposition (R-C).** For a partner with total contributions
``C``, actual distributions ``D`` and benchmark distributions ``M``::

    capital_returned           = min(D, C)    profit_distributions           = D - capital_returned
    benchmark_capital_returned = min(M, C)    benchmark_profit_distributions = M - benchmark_capital_returned

Returned own capital is excluded from profit on both sides, and the ordinary
no-promote ownership is excluded by subtracting the benchmark's profit.

**Promote Earned** is ``max(profit_distribution_difference, 0)`` for an
explicitly designated promote participant only; for anyone else it is not
applicable (R-E). **Benchmark capital subordination** is
``max(-capital_return_difference, 0)`` (R-B). The two are unrelated totals.

**Earliest-first capital attribution.** A partner's entries are ordered by
(period, tier sequence); the first ``capital_returned`` dollars are capital and
the rest profit. The benchmark's per-tier slices are split the same way at
``benchmark_capital_returned``. Per-tier differences are signed -- an
individual ``promote_attribution_by_tier`` value may be negative -- and each
family sums to its partner total; only ``promote_earned`` is floored.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .contracts import PartnerTierAmount, PromoteUnavailableReason

#: One distribution entry: (period, tier sequence, tier id, amount).
Entry = tuple[int, int, str, float]


@dataclass(frozen=True, slots=True, kw_only=True)
class Attribution:
    capital_returned: float
    profit_distributions: float
    benchmark_capital_returned: float
    benchmark_profit_distributions: float
    distribution_difference: float
    distribution_advantage: float
    distribution_disadvantage: float
    capital_return_difference: float
    profit_distribution_difference: float
    promote_earned: float | None
    promote_unavailable_reason: PromoteUnavailableReason | None
    benchmark_capital_subordination: float
    capital_return_difference_by_tier: tuple[PartnerTierAmount, ...]
    profit_distribution_difference_by_tier: tuple[PartnerTierAmount, ...]
    promote_attribution_by_tier: tuple[PartnerTierAmount, ...] | None


def capital_and_profit(total_distributions: float, total_contributions: float) -> tuple[float, float]:
    """``(capital_returned, profit_distributions)`` over the whole hold."""

    capital = min(total_distributions, total_contributions)
    return capital, total_distributions - capital


def split_entries(entries: Iterable[Entry], capital: float, total: float) -> dict[str, tuple[float, float]]:
    """Per tier id, ``(capital, profit)`` with the first ``capital`` dollars of
    the (period, sequence)-ordered entries counted as capital. When every
    dollar is capital (``capital == total``), no residue is labelled profit."""

    by_tier: dict[str, tuple[float, float]] = {}
    left = capital
    all_capital = capital == total
    for _, _, tier_id, amount in sorted(entries, key=lambda entry: (entry[0], entry[1])):
        if all_capital:
            as_capital = amount
        else:
            as_capital = min(amount, max(0.0, left))
            left = left - as_capital
        held_capital, held_profit = by_tier.get(tier_id, (0.0, 0.0))
        by_tier[tier_id] = (held_capital + as_capital, held_profit + (amount - as_capital))
    return by_tier


def promote_earned_value(profit_distribution_difference: float, is_participant: bool) -> float | None:
    """Promote Earned: participants only, floored at zero."""

    if not is_participant:
        return None
    return max(0.0, profit_distribution_difference)


def benchmark_capital_subordination_value(capital_return_difference: float) -> float:
    return max(0.0, -capital_return_difference)


def attribute(
    *,
    tiers: tuple[tuple[str, int], ...],
    total_contributions: float,
    total_distributions: float,
    total_benchmark_distributions: float,
    actual_entries: tuple[Entry, ...],
    benchmark_entries: tuple[Entry, ...],
    is_participant: bool,
) -> Attribution:
    """The Section 11 figures of one partner. ``tiers`` is ``(tier_id,
    sequence)`` in economic order."""

    capital, profit = capital_and_profit(total_distributions, total_contributions)
    benchmark_capital, benchmark_profit = capital_and_profit(total_benchmark_distributions, total_contributions)
    difference = total_distributions - total_benchmark_distributions
    capital_difference = capital - benchmark_capital
    profit_difference = profit - benchmark_profit
    promote = promote_earned_value(profit_difference, is_participant)

    actual = split_entries(actual_entries, capital, total_distributions)
    benchmark = split_entries(benchmark_entries, benchmark_capital, total_benchmark_distributions)
    capital_by_tier: list[PartnerTierAmount] = []
    profit_by_tier: list[PartnerTierAmount] = []
    for tier_id, sequence in tiers:
        actual_capital, actual_profit = actual.get(tier_id, (0.0, 0.0))
        benchmark_tier_capital, benchmark_tier_profit = benchmark.get(tier_id, (0.0, 0.0))
        capital_by_tier.append(PartnerTierAmount(tier_id=tier_id, sequence=sequence, amount=actual_capital - benchmark_tier_capital))
        profit_by_tier.append(PartnerTierAmount(tier_id=tier_id, sequence=sequence, amount=actual_profit - benchmark_tier_profit))

    promote_by_tier: tuple[PartnerTierAmount, ...] | None
    if promote is None:
        promote_by_tier = None
    elif promote > 0.0:
        promote_by_tier = tuple(profit_by_tier)
    else:
        promote_by_tier = tuple(PartnerTierAmount(tier_id=tier_id, sequence=sequence, amount=0.0) for tier_id, sequence in tiers)

    return Attribution(
        capital_returned=capital,
        profit_distributions=profit,
        benchmark_capital_returned=benchmark_capital,
        benchmark_profit_distributions=benchmark_profit,
        distribution_difference=difference,
        distribution_advantage=max(0.0, difference),
        distribution_disadvantage=max(0.0, -difference),
        capital_return_difference=capital_difference,
        profit_distribution_difference=profit_difference,
        promote_earned=promote,
        promote_unavailable_reason=None if is_participant else PromoteUnavailableReason.NOT_A_PROMOTE_PARTICIPANT,
        benchmark_capital_subordination=benchmark_capital_subordination_value(capital_difference),
        capital_return_difference_by_tier=tuple(capital_by_tier),
        profit_distribution_difference_by_tier=tuple(profit_by_tier),
        promote_attribution_by_tier=promote_by_tier,
    )
