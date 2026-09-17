"""Phase 7 Gate P7.9 Stage 1 -- ``PRO_RATA_BY_CONTRIBUTION``.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 5.2 and 6.2 and
fixtures F7, F10 and F11: cumulative actual contributions through the period,
neutrality against the equivalent explicit split, and the deterministic
zero-denominator refusal. The split rule is never defaulted.
"""

from __future__ import annotations

import dataclasses

import pytest

from _p7_9_fixtures import (  # type: ignore[import-not-found]
    F10_SERIES,
    LP_GP,
    BENCH_90_10,
    PRO_RATA,
    by_partner,
    by_tier,
    close,
    compound,
    f7_terms,
    f10_terms,
    f11_terms,
    hurdle,
    of_partner,
    partnership,
    residual,
    run,
    split,
)
from anchor.partnership import (
    PartnershipExecutionError,
    PartnershipExecutionIssueCode,
    PartnershipIssueCode,
    SplitRule,
    validate_partnership,
)
from anchor.partnership.allocation import pro_rata_by_contribution_shares

TOL = 1e-6


def test_f10_pro_rata_by_contribution_matches_the_explicit_commitment_split() -> None:
    pro_rata = by_partner(run(f10_terms(pro_rata=True), *F10_SERIES))
    explicit = by_partner(run(f10_terms(pro_rata=False), *F10_SERIES))
    assert close(pro_rata["lp"].total_distributions, 1_287_000.0) and close(pro_rata["gp"].total_distributions, 143_000.0)
    for partner_id in ("lp", "gp"):
        for left, right in zip(pro_rata[partner_id].distributions, explicit[partner_id].distributions):
            assert abs(left - right) <= TOL
        assert abs(pro_rata[partner_id].profit - explicit[partner_id].profit) <= TOL


def test_the_applied_shares_are_the_cumulative_contribution_shares() -> None:
    tier = by_tier(run(f10_terms(pro_rata=True), *F10_SERIES))["residual"]
    assert tier.split_rule is SplitRule.PRO_RATA_BY_CONTRIBUTION
    (applied,) = tier.shares_by_period
    shares = {share.partner_id: share.share for share in applied.shares}
    assert applied.period == 3
    assert close(shares["lp"], 945_000.0 / 1_050_000.0, 1e-12) and close(shares["gp"], 105_000.0 / 1_050_000.0, 1e-12)
    assert by_tier(run(f10_terms(pro_rata=False), *F10_SERIES))["residual"].split_rule is SplitRule.EXPLICIT


def test_the_shares_follow_contributions_not_the_benchmark() -> None:
    partners = by_partner(run(f7_terms(), -1_000_000.0, 0.0, 800_000.0))
    assert close(partners["lp"].total_distributions, 720_000.0) and close(partners["gp"].total_distributions, 80_000.0)


def test_the_shares_of_zero_contributions_are_unavailable() -> None:
    assert pro_rata_by_contribution_shares({"a": 0.0, "b": 0.0}) is None
    assert pro_rata_by_contribution_shares({"a": 3.0, "b": 1.0}) == {"a": 0.75, "b": 0.25}


def test_f11_a_distribution_before_any_contribution_is_refused() -> None:
    with pytest.raises(PartnershipExecutionError) as caught:
        run(f11_terms(), 0.0, 500.0, -1_000.0, 2_000.0)
    (issue,) = caught.value.issues
    assert issue.code is PartnershipExecutionIssueCode.NO_CONTRIBUTIONS_FOR_PRO_RATA_SPLIT
    assert issue.tier_id == "residual" and issue.period == 1


def test_f11_the_same_series_executes_under_an_explicit_split() -> None:
    partners = by_partner(run(f11_terms(pro_rata=False), 0.0, 500.0, -1_000.0, 2_000.0))
    assert close(partners["lp"].total_distributions, 2_250.0) and close(partners["gp"].total_distributions, 250.0)


def test_f11_no_refusal_when_no_cash_needs_shares_before_the_first_contribution() -> None:
    partners = by_partner(run(f11_terms(), 0.0, 0.0, -1_000.0, 2_000.0))
    assert close(partners["lp"].total_distributions, 1_800.0) and close(partners["gp"].total_distributions, 200.0)


def test_a_pro_rata_hurdle_with_nothing_owed_needs_no_shares() -> None:
    terms = partnership(
        LP_GP,
        (hurdle("pref", 10, of_partner("lp"), (compound("p", 0.08),), PRO_RATA), residual("residual", 20, split(lp=0.5, gp=0.5))),
        bench=BENCH_90_10,
        participants=(),
    )
    tiers = by_tier(run(terms, 0.0, 100.0, -1_000.0, 2_000.0))
    assert tiers["pref"].amounts[1] == 0.0 and tiers["residual"].amounts[1] == 100.0
    assert tiers["pref"].amounts[3] > 0.0


def test_a_zero_commitment_subject_is_owed_nothing_under_pro_rata() -> None:
    from _p7_9_fixtures import benchmark, partner  # type: ignore[import-not-found]

    terms = partnership(
        (partner("lp", 1.0), partner("sp", 0.0)),
        (hurdle("pref", 10, of_partner("sp"), (compound("p", 0.08),), PRO_RATA), residual("residual", 20, split(lp=0.8, sp=0.2))),
        bench=benchmark(lp=1.0, sp=0.0),
        participants=(),
    )
    tiers = by_tier(run(terms, -1_000.0, 2_000.0))
    assert tiers["pref"].amounts == (0.0, 0.0) and tiers["residual"].amounts[1] == 2_000.0


def test_the_split_rule_is_never_defaulted() -> None:
    terms = f10_terms(pro_rata=True)
    missing = dataclasses.replace(terms, tiers=(dataclasses.replace(terms.tiers[0], split=None), terms.tiers[1]))
    assert [issue.code for issue in validate_partnership(missing)] == [PartnershipIssueCode.MISSING_SPLIT]
    wrong = dataclasses.replace(terms, tiers=(dataclasses.replace(terms.tiers[0], split="pro_rata_by_contribution"), terms.tiers[1]))
    assert [issue.code for issue in validate_partnership(wrong)] == [PartnershipIssueCode.INVALID_SPLIT]


def test_a_structurally_valid_pro_rata_split_always_executes_given_contributions() -> None:
    assert validate_partnership(f10_terms(pro_rata=True)) == ()
    assert by_tier(run(f10_terms(pro_rata=True), *F10_SERIES))["pref"].amounts[3] > 0.0


def test_a_subject_owed_but_without_a_split_share_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive: unreachable under PRO_RATA_BY_COMMITMENT, proven by forcing
    the shares to exclude the subject."""

    from anchor.partnership import allocation

    monkeypatch.setattr(allocation, "pro_rata_by_contribution_shares", lambda cumulative: {"lp": 0.0, "gp": 1.0})
    with pytest.raises(PartnershipExecutionError) as caught:
        run(f10_terms(pro_rata=True), *F10_SERIES)
    assert [issue.code for issue in caught.value.issues] == [PartnershipExecutionIssueCode.SUBJECT_WITHOUT_SPLIT_SHARE]
