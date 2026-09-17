"""Phase 7 Gate P7.9 Stage 1 -- benchmark decomposition, Promote Earned,
benchmark capital subordination and tier attribution.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 11 (R-A to R-E)
and fixtures F1, F5, F7, F8 and F12.
"""

from __future__ import annotations

import dataclasses

from _p7_9_fixtures import (  # type: ignore[import-not-found]
    BENCH_90_10,
    F1_SERIES,
    F5_SERIES,
    F8_SERIES,
    F12_SERIES,
    LP_GP,
    benchmark,
    by_partner,
    close,
    dict_close,
    f1_series,
    f1_terms,
    f5_terms,
    f7_terms,
    f8_terms,
    f12_terms,
    pari_passu,
    partner,
    partnership,
    residual,
    run,
    split,
    tier_values,
)
from anchor.partnership import PartnerRole, PromoteUnavailableReason
from anchor.partnership.attribution import split_entries


def test_f1_gp_promote_is_its_profit_above_the_benchmark() -> None:
    gp = by_partner(run(f1_terms(), *F1_SERIES))["gp"]
    assert gp.is_promote_participant
    assert close(gp.capital_returned, 110_000.0) and close(gp.profit_distributions, 210_393.60)
    assert close(gp.benchmark_capital_returned, 110_000.0) and close(gp.benchmark_profit_distributions, 86_000.0)
    assert close(gp.distribution_difference, 124_393.60) and close(gp.capital_return_difference, 0.0)
    assert close(gp.profit_distribution_difference, 124_393.60)
    assert close(gp.promote_earned, 124_393.60) and gp.promote_unavailable_reason is None
    assert close(gp.distribution_advantage, 124_393.60) and gp.distribution_disadvantage == 0.0
    assert gp.benchmark_capital_subordination == 0.0
    assert dict_close(
        tier_values(gp.promote_attribution_by_tier),
        {"pref": 0.0, "catch_up": 33_944.0, "promote_1": 13_662.40, "promote_2": 76_787.20},
    )
    assert dict_close(tier_values(gp.capital_return_difference_by_tier), {"pref": 0.0, "catch_up": 0.0, "promote_1": 0.0, "promote_2": 0.0})


def test_f1_the_lp_bears_the_promote_without_subordination() -> None:
    lp = by_partner(run(f1_terms(), *F1_SERIES))["lp"]
    assert not lp.is_promote_participant
    assert lp.promote_earned is None and lp.promote_attribution_by_tier is None
    assert lp.promote_unavailable_reason is PromoteUnavailableReason.NOT_A_PROMOTE_PARTICIPANT
    assert close(lp.profit_distribution_difference, -124_393.60) and close(lp.distribution_disadvantage, 124_393.60)
    assert lp.benchmark_capital_subordination == 0.0
    assert close(lp.total_benchmark_distributions, 1_764_000.0)
    assert dict_close(
        tier_values(lp.profit_distribution_difference_by_tier),
        {"pref": 0.0, "catch_up": -33_944.0, "promote_1": -13_662.40, "promote_2": -76_787.20},
    )


def test_f1_variations_promote() -> None:
    partial = by_partner(run(f1_terms(), *f1_series(1_340_000.0)))["gp"]
    assert close(partial.promote_earned, 14_224.0)
    assert dict_close(tier_values(partial.promote_attribution_by_tier), {"pref": 0.0, "catch_up": 14_224.0, "promote_1": 0.0, "promote_2": 0.0})
    not_met = by_partner(run(f1_terms(), *f1_series(1_100_000.0)))["gp"]
    assert not_met.promote_earned == 0.0
    assert all(item.amount == 0.0 for item in not_met.promote_attribution_by_tier)


def test_f5_returned_capital_is_never_promote() -> None:
    partners = by_partner(run(f5_terms(), *F5_SERIES))
    lp, gp = partners["lp"], partners["gp"]
    assert close(lp.distribution_difference, 85_000.0)
    assert close(lp.capital_return_difference, 45_000.0) and close(lp.profit_distribution_difference, 40_000.0)
    assert lp.promote_earned is None
    assert close(gp.capital_returned, 10_000.0) and close(gp.benchmark_capital_returned, 95_000.0)
    assert close(gp.capital_return_difference, -85_000.0) and close(gp.profit_distribution_difference, 0.0)
    assert gp.promote_earned == 0.0
    assert close(gp.benchmark_capital_subordination, 85_000.0)
    assert dict_close(tier_values(gp.capital_return_difference_by_tier), {"roc": -90_000.0, "residual": 5_000.0})
    assert dict_close(tier_values(lp.capital_return_difference_by_tier), {"roc": 90_000.0, "residual": -45_000.0})
    assert dict_close(tier_values(lp.profit_distribution_difference_by_tier), {"roc": 0.0, "residual": 40_000.0})


def test_f5_there_is_no_promote_equals_subordination_identity() -> None:
    partners = by_partner(run(f5_terms(), *F5_SERIES)).values()
    total_promote = sum(item.promote_earned or 0.0 for item in partners)
    total_subordination = sum(item.benchmark_capital_subordination for item in partners)
    assert total_promote == 0.0 and close(total_subordination, 85_000.0)


def test_f7_loss_a_sponsor_advantage_of_returned_capital_is_not_promote() -> None:
    partners = by_partner(run(f7_terms(), -1_000_000.0, 0.0, 800_000.0))
    gp, lp = partners["gp"], partners["lp"]
    assert close(gp.total_benchmark_distributions, 40_000.0)
    assert close(gp.distribution_difference, 40_000.0) and close(gp.capital_return_difference, 40_000.0)
    assert close(gp.profit_distribution_difference, 0.0)
    assert gp.promote_earned == 0.0 and close(gp.distribution_advantage, 40_000.0)
    assert close(lp.benchmark_capital_subordination, 40_000.0)
    assert not gp.benchmark_equals_commitment and gp.benchmark_share == 0.05


def test_f7_gain_the_ratified_period_by_period_benchmark_governs() -> None:
    gp = by_partner(run(f7_terms(), -1_000_000.0, 0.0, 1_500_000.0))["gp"]
    assert close(gp.total_distributions, 150_000.0) and close(gp.total_benchmark_distributions, 75_000.0)
    assert close(gp.capital_return_difference, 25_000.0) and close(gp.profit_distribution_difference, 50_000.0)
    assert close(gp.promote_earned, 50_000.0)
    assert dict_close(tier_values(gp.promote_attribution_by_tier), {"residual": 50_000.0})


def test_f8_a_promote_only_sponsor() -> None:
    partners = by_partner(run(f8_terms(), *F8_SERIES))
    sponsor = partners["sp"]
    assert sponsor.total_contributions == 0.0 and close(sponsor.total_distributions, 100_000.0)
    assert sponsor.capital_returned == 0.0 and close(sponsor.profit_distributions, 100_000.0)
    assert sponsor.total_benchmark_distributions == 0.0
    assert close(sponsor.promote_earned, 100_000.0)
    assert dict_close(tier_values(sponsor.promote_attribution_by_tier), {"pref": 0.0, "catch_up": 41_600.0, "residual": 58_400.0})
    assert close(partners["lp"].profit_distribution_difference, -100_000.0)


def test_f12_two_participants_are_measured_separately() -> None:
    partners = by_partner(run(f12_terms(), *F12_SERIES))
    for sponsor in ("g1", "g2"):
        assert close(partners[sponsor].promote_earned, 25_000.0)
        assert dict_close(tier_values(partners[sponsor].promote_attribution_by_tier), {"pref": 0.0, "catch_up": 9_360.0, "residual": 15_640.0})
    assert close(partners["lp"].profit_distribution_difference, -50_000.0)


def test_zero_participants_report_promote_as_not_applicable_for_everyone() -> None:
    partners = by_partner(run(f1_terms(participants=()), *F1_SERIES))
    for item in partners.values():
        assert item.promote_earned is None and item.promote_attribution_by_tier is None
        assert item.promote_unavailable_reason is PromoteUnavailableReason.NOT_A_PROMOTE_PARTICIPANT
    assert close(partners["gp"].profit_distribution_difference, 124_393.60)


def test_a_gp_role_never_implies_participation_and_an_lp_may_participate() -> None:
    partners = by_partner(run(f1_terms(participants=("lp",)), *F1_SERIES))
    assert partners["gp"].role is PartnerRole.GP and partners["gp"].promote_earned is None
    assert partners["lp"].role is PartnerRole.LP and partners["lp"].promote_earned == 0.0
    assert all(item.amount == 0.0 for item in partners["lp"].promote_attribution_by_tier)


def test_a_negative_tier_attribution_sits_inside_a_positive_promote() -> None:
    """A tier that pays the participant below its benchmark share carries a
    negative attribution; only the partner total is floored."""

    terms = partnership(
        LP_GP,
        (
            __import__("_p7_9_fixtures").hurdle(
                "roc", 10, __import__("_p7_9_fixtures").of_partner("lp"),
                (__import__("_p7_9_fixtures").moic("m", 1.2),), split(lp=1.0, gp=0.0),
            ),
            residual("residual", 20, split(lp=0.5, gp=0.5)),
        ),
        bench=BENCH_90_10,
        participants=("gp",),
    )
    gp = by_partner(run(terms, -1_000_000.0, 2_000_000.0))["gp"]
    attribution = tier_values(gp.promote_attribution_by_tier)
    assert attribution["roc"] < 0.0 < gp.promote_earned  # type: ignore[operator]
    assert close(sum(attribution.values()), gp.promote_earned)  # type: ignore[arg-type]
    # LP 1,080,000 in the MOIC tier; the 920,000 residual at 50 / 50 gives the GP
    # 460,000, of which its own 100,000 is capital. The benchmark's 10% slice of
    # the MOIC tier (108,000) holds 8,000 of profit the GP did not receive there.
    assert close(gp.capital_returned, 100_000.0) and close(gp.profit_distributions, 360_000.0)
    assert close(gp.benchmark_profit_distributions, 100_000.0)
    assert close(gp.promote_earned, 260_000.0)
    assert dict_close(attribution, {"roc": -8_000.0, "residual": 268_000.0})


def test_pari_passu_has_no_promote_or_subordination() -> None:
    for item in by_partner(run(pari_passu(), -1_000_000.0, 100_000.0, 1_200_000.0)).values():
        assert item.distribution_difference == 0.0 and item.benchmark_capital_subordination == 0.0
        assert item.promote_earned in (None, 0.0)
        assert item.benchmark_equals_commitment


def test_the_benchmark_is_read_from_the_stated_table_even_when_it_matches_nothing() -> None:
    terms = pari_passu(bench=benchmark(lp=0.5, gp=0.5))
    partners = by_partner(run(terms, -1_000_000.0, 1_500_000.0))
    assert close(partners["gp"].total_benchmark_distributions, 750_000.0)
    assert not partners["gp"].benchmark_equals_commitment


def test_earliest_first_capital_splits_an_entry_at_the_boundary() -> None:
    # ordered (1, a 60), (1, b 20), (2, a 30), (2, b 50): the 90th dollar falls
    # inside period 2's "a" entry, whatever order the entries were listed in
    entries = ((1, 10, "a", 60.0), (2, 10, "a", 30.0), (2, 20, "b", 50.0), (1, 20, "b", 20.0))
    assert split_entries(entries, 90.0, 160.0) == {"a": (70.0, 20.0), "b": (20.0, 50.0)}
    assert split_entries(entries, 160.0, 160.0) == {"a": (90.0, 0.0), "b": (70.0, 0.0)}
    assert split_entries(entries, 0.0, 160.0) == {"a": (0.0, 90.0), "b": (0.0, 70.0)}


def test_the_whole_hold_basis_ignores_timing_of_profit_before_a_later_call() -> None:
    """R-C: a profit distribution followed by a capital call is capital over
    the hold when the partner never earns a profit."""

    terms = partnership(
        (partner("only", 1.0),),
        (residual("residual", 10, split(only=1.0)),),
        bench=benchmark(only=1.0),
        participants=("only",),
    )
    only = by_partner(run(terms, -100.0, 150.0, -100.0, 50.0))["only"]
    assert only.profit == 0.0 and only.profit_distributions == 0.0 and only.capital_returned == 200.0
    assert only.promote_earned == 0.0


def test_participants_are_reported_in_canonical_order() -> None:
    result = run(dataclasses.replace(f12_terms(), promote_participant_ids=("g2", "g1")), *F12_SERIES)
    assert result.promote_participant_ids == ("g1", "g2")
    assert LP_GP[1].role is PartnerRole.GP
