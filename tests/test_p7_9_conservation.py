"""Phase 7 Gate P7.9 Stage 1 -- conservation and reporting identities.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 14, identities
1-17, over every ratified fixture and a deterministic sweep of generated
series. Tolerance: ``1e-6 + 1e-12 x |CECF_t|`` per period; horizon totals sum
the per-period tolerances.
"""

from __future__ import annotations

import random

import pytest

from _p7_9_fixtures import (  # type: ignore[import-not-found]
    F5_SERIES,
    Case,
    by_partner,
    by_tier,
    f1_terms,
    f4_terms,
    f5_terms,
    f7_terms,
    f8_terms,
    f10_terms,
    f12_terms,
    fixture_cases,
    run,
    ALL,
    ANY,
)
from anchor.partnership import PartnershipResult, PromoteUnavailableReason


def period_tolerance(cash_flow: float) -> float:
    return 1e-6 + 1e-12 * abs(cash_flow)


def generated_series(rng: random.Random, *, contributes_first: bool = False) -> tuple[float, ...]:
    """A 2- to 8-year series: a closing call (sometimes fully financed, unless
    ``contributes_first``), then years that are mostly distributions with
    occasional calls and zeros."""

    hold = rng.randint(1, 7)
    financed = rng.random() < 0.1 and not contributes_first
    closing = 0.0 if financed else -rng.uniform(100_000.0, 5_000_000.0)
    years = []
    for _ in range(hold):
        roll = rng.random()
        if roll < 0.2:
            years.append(-rng.uniform(1_000.0, 800_000.0))
        elif roll < 0.3:
            years.append(0.0)
        else:
            years.append(rng.uniform(1_000.0, 4_000_000.0))
    if closing == 0.0 and all(value >= 0.0 for value in years):
        years[0] = -rng.uniform(1_000.0, 800_000.0)
    return (round(closing, 2), *(round(value, 2) for value in years))


def generated_cases() -> list[Case]:
    rng = random.Random(20260916)
    terms = {
        "F1": f1_terms(),
        "F4-all": f4_terms(ALL),
        "F4-any": f4_terms(ANY),
        "F5-catch-up": f5_terms(with_catch_up=True),
        "F7": f7_terms(),
        "F8": f8_terms(),
        "F10": f10_terms(pro_rata=True),
        "F12": f12_terms(),
    }
    #: A pro-rata-by-contribution split refuses cash before any contribution
    #: (Section 6.2), so those terms are swept on series that contribute first.
    pro_rata = {"F7", "F10"}
    return [
        Case(f"{name}-gen-{index}", value, generated_series(rng, contributes_first=name in pro_rata))
        for name, value in terms.items()
        for index in range(12)
    ]


def check_identities(case: Case, result: PartnershipResult) -> None:
    cash_flows = case.cash_flows
    tolerances = [period_tolerance(value) for value in cash_flows]
    horizon = sum(tolerances)
    partners = by_partner(result)
    tiers = by_tier(result)
    participants = set(case.terms.promote_participant_ids)
    for t, cash_flow in enumerate(cash_flows):
        tol = tolerances[t]
        # 1, 2: partner contributions and distributions
        assert abs(sum(p.contributions[t] for p in partners.values()) - max(-cash_flow, 0.0)) <= tol
        assert abs(sum(p.distributions[t] for p in partners.values()) - max(cash_flow, 0.0)) <= tol
        # 3: the tiers exhaust each distribution
        assert abs(sum(tier.amounts[t] for tier in tiers.values()) - max(cash_flow, 0.0)) <= tol
        # 4: each tier's partner amounts reconcile to its cash
        for tier in tiers.values():
            assert abs(sum(amounts.amounts[t] for amounts in tier.partner_amounts) - tier.amounts[t]) <= tol
        # 5: the benchmark conserves the same cash
        assert abs(sum(p.benchmark_distributions[t] for p in partners.values()) - max(cash_flow, 0.0)) <= tol
        # 17: per-period amounts are finite and non-negative
        for p in partners.values():
            assert p.contributions[t] >= 0.0 and p.distributions[t] >= 0.0 and p.benchmark_distributions[t] >= 0.0
            assert p.contributions[t] == 0.0 or p.distributions[t] == 0.0
        for tier in tiers.values():
            assert tier.amounts[t] >= 0.0
    # 6: partner profits reconcile to Common Equity Total Profit
    assert result.common_equity_total_profit is not None
    assert abs(sum(p.profit for p in partners.values()) - result.common_equity_total_profit) <= horizon
    # 7, 9: signed differences
    assert abs(sum(p.distribution_difference for p in partners.values())) <= horizon
    assert abs(
        sum(p.capital_return_difference for p in partners.values()) + sum(p.profit_distribution_difference for p in partners.values())
    ) <= horizon
    for p in partners.values():
        # 8
        assert abs(p.distribution_difference - (p.capital_return_difference + p.profit_distribution_difference)) <= horizon
        # 10
        assert abs(p.capital_returned + p.profit_distributions - p.total_distributions) <= horizon
        assert abs(p.benchmark_capital_returned + p.benchmark_profit_distributions - p.total_benchmark_distributions) <= horizon
        assert p.capital_returned <= p.total_contributions + horizon and p.capital_returned <= p.total_distributions + horizon
        # 11
        assert abs(p.profit - (p.profit_distributions - (p.total_contributions - p.capital_returned))) <= horizon
        # 12
        assert abs(p.distribution_advantage - p.distribution_disadvantage - p.distribution_difference) <= horizon
        assert p.distribution_advantage == 0.0 or p.distribution_disadvantage == 0.0
        # 13
        if p.partner_id in participants:
            assert p.promote_earned == max(0.0, p.profit_distribution_difference)
            assert p.promote_unavailable_reason is None
        else:
            assert p.promote_earned is None and p.promote_attribution_by_tier is None
            assert p.promote_unavailable_reason is PromoteUnavailableReason.NOT_A_PROMOTE_PARTICIPANT
        # 14
        assert p.benchmark_capital_subordination == max(0.0, -p.capital_return_difference)
        # 15: tier reconciliation
        assert abs(sum(item.amount for item in p.capital_return_difference_by_tier) - p.capital_return_difference) <= horizon
        assert abs(sum(item.amount for item in p.profit_distribution_difference_by_tier) - p.profit_distribution_difference) <= horizon
        assert abs(sum(item.amount for item in p.distributions_by_tier) - p.total_distributions) <= horizon
        if p.promote_attribution_by_tier is not None:
            assert abs(sum(item.amount for item in p.promote_attribution_by_tier) - p.promote_earned) <= horizon  # type: ignore[operator]
        # 17: floors are non-negative and never negative zero
        for value in (p.distribution_advantage, p.distribution_disadvantage, p.benchmark_capital_subordination, p.promote_earned):
            if value is not None:
                assert value >= 0.0 and str(value) != "-0.0"


ALL_CASES = [*fixture_cases(), *generated_cases()]


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.name)
def test_the_section_14_identities_hold(case: Case) -> None:
    check_identities(case, run(case.terms, *case.cash_flows))


def test_a_pro_rata_split_refuses_every_generated_series_that_distributes_before_contributing() -> None:
    from anchor.partnership import PartnershipExecutionError, PartnershipExecutionIssueCode

    rng = random.Random(7)
    refused = 0
    for _ in range(400):
        cash_flows = generated_series(rng)
        first_call = next((t for t, value in enumerate(cash_flows) if value < 0.0), len(cash_flows))
        distributes_first = any(value > 0.0 for value in cash_flows[:first_call])
        if distributes_first:
            with pytest.raises(PartnershipExecutionError) as caught:
                run(f10_terms(pro_rata=True), *cash_flows)
            assert [issue.code for issue in caught.value.issues] == [PartnershipExecutionIssueCode.NO_CONTRIBUTIONS_FOR_PRO_RATA_SPLIT]
            refused += 1
        else:
            run(f10_terms(pro_rata=True), *cash_flows)
    assert refused >= 5


def test_identity_16_promote_and_subordination_are_unrelated_totals() -> None:
    partners = by_partner(run(f5_terms(), *F5_SERIES)).values()
    promote = sum(p.promote_earned or 0.0 for p in partners)
    subordination = sum(p.benchmark_capital_subordination for p in partners)
    assert promote == 0.0 and subordination == 85_000.0
    assert promote != subordination


def test_the_sweep_exercises_every_branch() -> None:
    """The generated cases are not vacuous: they reach calls after
    distributions, closed catch-up domains, subordination and promote."""

    saw_call_after_distribution = saw_closed_domain = saw_subordination = saw_promote = False
    for case in generated_cases():
        values = case.cash_flows
        if any(values[i] > 0.0 and any(v < 0.0 for v in values[i + 1:]) for i in range(len(values))):
            saw_call_after_distribution = True
        result = run(case.terms, *case.cash_flows)
        for tier in by_tier(result).values():
            if any(not record.profit_domain_open for record in tier.catch_up_records):
                saw_closed_domain = True
        for partner_result in by_partner(result).values():
            saw_subordination |= partner_result.benchmark_capital_subordination > 0.0
            saw_promote |= (partner_result.promote_earned or 0.0) > 0.0
    assert saw_call_after_distribution and saw_closed_domain and saw_subordination and saw_promote
