"""Phase 7 Gate P7.9 Stage 1 -- the ratified hand fixtures through the engine.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 7, 10, 15 and 16.1
(F1, F4, F6) and the Section 16.3 boundary cases of the period loop. Every
expected figure is a literal restated from the document.
"""

from __future__ import annotations

import dataclasses

import pytest

from _p7_9_fixtures import (  # type: ignore[import-not-found]
    ALL,
    ALL_EQUITY,
    ANY,
    F1_SERIES,
    F4_SERIES,
    F5_SERIES,
    F6_SERIES,
    LP_GP,
    BENCH_90_10,
    all_close,
    by_partner,
    by_tier,
    close,
    compound,
    f1_series,
    f1_terms,
    f4_terms,
    f5_terms,
    of_partner,
    pari_passu,
    partnership,
    residual,
    run,
    series,
    split,
    hurdle,
)
from anchor.engine.contracts import IrrStatus
from anchor.partnership import (
    CashFlowCadence,
    CommonEquityCashFlowInput,
    PartnershipExecutionError,
    PartnershipExecutionIssueCode,
    PartnershipStatus,
    allocate_partnership,
)


# =============================================================================
# F1: the Section 15 worked example
# =============================================================================


def test_f1_contributions_follow_the_commitments() -> None:
    partners = by_partner(run(f1_terms(), *F1_SERIES))
    assert all_close(partners["lp"].contributions, (900_000.0, 90_000.0, 0.0, 0.0))
    assert all_close(partners["gp"].contributions, (100_000.0, 10_000.0, 0.0, 0.0))


def test_f1_hurdle_accounts_match_section_15_3() -> None:
    tiers = by_tier(run(f1_terms(), *F1_SERIES))
    pref = tiers["pref"].conditions
    promote = tiers["promote_1"].conditions
    assert all_close([record.closing_balance for record in pref[:3]], (900_000.0, 1_062_000.0, 1_092_960.0))
    assert close(pref[2].opening_balance + pref[2].accrual, 1_146_960.0)
    assert close(pref[3].opening_balance + pref[3].accrual, 1_180_396.80)
    assert all_close([record.closing_balance for record in promote[:3]], (900_000.0, 1_098_000.0, 1_175_760.0))
    assert close(promote[2].opening_balance + promote[2].accrual, 1_229_760.0)
    assert close(promote[3].opening_balance + promote[3].accrual, 1_316_851.20)
    # the later tiers pay the LP beyond the pref: the surplus is kept, never floored
    assert close(pref[3].closing_balance, 1_180_396.80 - 1_585_606.40) and pref[3].satisfied_at_close
    assert close(pref[3].subject_distributions_from_tier, 1_180_396.80)
    assert close(pref[3].subject_distributions_after_tier, 27_155.20 + 109_299.20 + 268_755.20)
    assert close(promote[3].subject_distributions_before_tier, 1_180_396.80 + 27_155.20)


def test_f1_tier_amounts_match_section_15_4() -> None:
    tiers = by_tier(run(f1_terms(), *F1_SERIES))
    assert all_close(tiers["pref"].amounts, (0.0, 0.0, 60_000.0, 1_311_552.0))
    assert all_close(tiers["catch_up"].amounts, (0.0, 0.0, 0.0, 67_888.0))
    assert all_close(tiers["promote_1"].amounts, (0.0, 0.0, 0.0, 136_624.0))
    assert all_close(tiers["promote_2"].amounts, (0.0, 0.0, 0.0, 383_936.0))
    shares = {share.partner_id: share.share for share in tiers["catch_up"].shares_by_period[0].shares}
    assert shares == {"gp": 0.6, "lp": 0.4}


def test_f1_partner_results_match_section_15_5() -> None:
    result = run(f1_terms(), *F1_SERIES)
    lp, gp = by_partner(result)["lp"], by_partner(result)["gp"]
    assert all_close(lp.net_cash_flows, (-900_000.0, -90_000.0, 54_000.0, 1_585_606.40))
    assert all_close(gp.net_cash_flows, (-100_000.0, -10_000.0, 6_000.0, 314_393.60))
    assert close(lp.total_distributions, 1_639_606.40) and close(gp.total_distributions, 320_393.60)
    assert close(lp.profit, 649_606.40) and close(gp.profit, 210_393.60)
    assert close(lp.moic, 1_639_606.40 / 990_000.0) and close(gp.moic, 320_393.60 / 110_000.0)
    assert lp.irr_status is IrrStatus.DEFINED and abs(lp.irr - 0.19144775) < 1e-7  # type: ignore[operator]
    assert gp.irr_status is IrrStatus.DEFINED and abs(gp.irr - 0.44571386) < 1e-7  # type: ignore[operator]
    assert close(result.common_equity_total_profit, 860_000.0)
    assert result.status is PartnershipStatus.COMPLETE and result.cadence is CashFlowCadence.ANNUAL


@pytest.mark.parametrize(
    ("t3", "pref", "catch_up", "promote_1", "promote_2"),
    [
        (1_100_000.0, 1_100_000.0, 0.0, 0.0, 0.0),
        (1_340_000.0, 1_311_552.0, 28_448.0, 0.0, 0.0),
        (1_900_000.0, 1_311_552.0, 67_888.0, 136_624.0, 383_936.0),
    ],
)
def test_f1_variations_match_section_15_6(t3: float, pref: float, catch_up: float, promote_1: float, promote_2: float) -> None:
    tiers = by_tier(run(f1_terms(), *f1_series(t3)))
    assert all_close(
        [tiers[name].amounts[3] for name in ("pref", "catch_up", "promote_1", "promote_2")],
        (pref, catch_up, promote_1, promote_2),
    )


def test_f1_pref_not_met_gives_the_lp_its_ratified_irr() -> None:
    lp = by_partner(run(f1_terms(), *f1_series(1_100_000.0)))["lp"]
    assert abs(lp.irr - 0.01875877) < 1e-7  # type: ignore[operator]


def test_f1_period_records_trace_the_remaining_cash() -> None:
    periods = run(f1_terms(), *F1_SERIES).periods
    assert periods is not None
    assert [record.total_contributions for record in periods] == [1_000_000.0, 100_000.0, 0.0, 0.0]
    assert [record.total_distributions for record in periods] == [0.0, 0.0, 60_000.0, 1_900_000.0]
    assert periods[0].remaining_after_tier == () and periods[1].remaining_after_tier == ()
    assert [(item.tier_id, item.remaining) for item in periods[2].remaining_after_tier] == [("pref", 0.0)]
    remaining = [item.remaining for item in periods[3].remaining_after_tier]
    assert all_close(remaining, (588_448.0, 520_560.0, 383_936.0, 0.0), tol=1e-6)


# =============================================================================
# F4: ALL vs ANY; F6: the hurdle subject
# =============================================================================


def test_f4_all_is_the_greater_of_and_any_the_lesser_of() -> None:
    all_tiers = by_tier(run(f4_terms(ALL), *F4_SERIES))
    any_tiers = by_tier(run(f4_terms(ANY), *F4_SERIES))
    assert close(all_tiers["greater_lesser"].amounts[2], 1_500_000.0)
    assert close(all_tiers["residual"].amounts[2], 500_000.0)
    assert close(any_tiers["greater_lesser"].amounts[2], 1_210_000.0)
    assert close(any_tiers["residual"].amounts[2], 790_000.0)
    capacities = {record.condition_id: record.capacity_at_entry for record in all_tiers["greater_lesser"].conditions if record.period == 2}
    assert close(capacities["irr-10"], 1_089_000.0 / 0.9) and close(capacities["moic-15"], 1_500_000.0)


def test_f6_the_subject_decides_the_hurdle() -> None:
    lp_subject = by_tier(run(f5_terms(), *F6_SERIES))
    all_subject = by_tier(run(f5_terms(ALL_EQUITY), *F6_SERIES))
    assert close(lp_subject["roc"].amounts[2], 900_000.0) and close(lp_subject["residual"].amounts[2], 600_000.0)
    assert close(all_subject["roc"].amounts[2], 1_000_000.0) and close(all_subject["residual"].amounts[2], 500_000.0)
    assert all_subject["roc"].subject_partner_ids == ("gp", "lp")


def test_an_investor_class_subject_aggregates_its_members() -> None:
    from _p7_9_fixtures import benchmark, of_class, partner  # type: ignore[import-not-found]

    terms = partnership(
        (partner("a1", 0.45, investor_class="class-a"), partner("a2", 0.45, investor_class="class-a"), partner("gp", 0.1)),
        (
            hurdle("roc", 10, of_class("class-a"), (compound("irr-0", 0.0),), split(a1=0.6, a2=0.3, gp=0.1)),
            residual("residual", 20, split(a1=0.4, a2=0.4, gp=0.2)),
        ),
        bench=benchmark(a1=0.45, a2=0.45, gp=0.1),
        participants=(),
    )
    tiers = by_tier(run(terms, -1_000_000.0, 1_500_000.0))
    assert tiers["roc"].subject_partner_ids == ("a1", "a2")
    assert close(tiers["roc"].amounts[1], 900_000.0 / 0.9)
    assert close(tiers["residual"].amounts[1], 500_000.0)


# =============================================================================
# Section 16.3: the period loop's boundaries
# =============================================================================


def test_a_fully_financed_closing_is_valid() -> None:
    partners = by_partner(run(pari_passu(), 0.0, -100_000.0, 150_000.0))
    assert partners["lp"].contributions == (0.0, 90_000.0, 0.0)
    assert close(partners["lp"].distributions[2], 135_000.0)


def test_a_tiny_positive_closing_is_a_distribution_to_the_residual() -> None:
    tiers = by_tier(run(f1_terms(), 0.01, -1_000_000.0, 1_200_000.0))
    assert tiers["pref"].amounts[0] == 0.0 and tiers["catch_up"].amounts[0] == 0.0
    assert tiers["promote_2"].amounts[0] == 0.01


def test_an_all_zero_series_allocates_nothing() -> None:
    result = run(f1_terms(), 0.0, 0.0, 0.0)
    for partner_result in by_partner(result).values():
        assert partner_result.total_contributions == 0.0 and partner_result.total_distributions == 0.0
        assert partner_result.irr is None and partner_result.irr_status is IrrStatus.NO_NONZERO_CASH_FLOW
        assert partner_result.moic is None


def test_a_negative_profit_series_is_not_an_error() -> None:
    result = run(f1_terms(), -1_000_000.0, 200_000.0, 300_000.0)
    partners = by_partner(result)
    assert close(result.common_equity_total_profit, -500_000.0)
    assert close(partners["lp"].profit + partners["gp"].profit, -500_000.0)
    assert by_tier(result)["catch_up"].amounts == (0.0, 0.0, 0.0)


def test_a_capital_call_after_a_distribution_reopens_the_pref() -> None:
    tiers = by_tier(run(f1_terms(), -1_000_000.0, 50_000.0, -200_000.0, 1_600_000.0))
    records = tiers["pref"].conditions
    assert close(records[2].subject_contributions, 180_000.0)
    assert not records[2].satisfied_at_close


def test_a_tier_satisfied_one_year_is_reopened_by_accrual_the_next() -> None:
    tiers = by_tier(run(f1_terms(), -1_000_000.0, 1_500_000.0, -400_000.0, 50_000.0))
    pref = tiers["pref"].conditions
    assert close(tiers["pref"].amounts[1], 1_080_000.0) and pref[1].satisfied_at_close
    # the surplus the later tiers paid compounds a year, never floors ...
    assert pref[2].opening_balance < 0.0
    assert close(pref[2].accrual, pref[2].opening_balance * 0.08)
    # ... and absorbs part of the capital call before the pref binds again
    assert close(pref[2].closing_balance, pref[2].opening_balance * 1.08 + 360_000.0)
    assert not pref[2].satisfied_at_close
    assert tiers["pref"].amounts[3] > 0.0


def test_cash_exhausted_exactly_at_a_tier_boundary_stops_the_waterfall() -> None:
    tiers = by_tier(run(f1_terms(), -1_000_000.0, 0.0, 0.0, 1_259_712.0))
    # the LP's 900,000 at 8% for three years is 1,133,740.80: 1,259,712.00 of tier cash
    assert close(tiers["pref"].amounts[3], 1_259_712.0)
    assert tiers["catch_up"].amounts[3] == 0.0 and tiers["promote_2"].amounts[3] == 0.0


def test_a_one_year_hold_executes() -> None:
    partners = by_partner(run(f1_terms(), -1_000_000.0, 1_300_000.0))
    assert close(partners["lp"].profit + partners["gp"].profit, 300_000.0)


def test_a_multiple_sign_change_partner_series_reports_its_irr_status() -> None:
    partners = by_partner(run(pari_passu(), -1_000_000.0, 1_500_000.0, -600_000.0, 200_000.0))
    assert partners["lp"].irr is None and partners["lp"].irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES


def test_permuting_partners_and_tiers_changes_nothing() -> None:
    terms = f1_terms()
    permuted = dataclasses.replace(
        terms,
        partners=tuple(reversed(terms.partners)),
        tiers=(terms.tiers[3], terms.tiers[1], terms.tiers[0], terms.tiers[2]),
        promote_benchmark=dataclasses.replace(terms.promote_benchmark, shares=tuple(reversed(terms.promote_benchmark.shares))),
    )
    assert run(permuted, *F1_SERIES) == run(terms, *F1_SERIES)


def test_integer_cash_flows_are_read_as_their_float_values() -> None:
    integers = allocate_partnership(f1_terms(), CommonEquityCashFlowInput(cadence=CashFlowCadence.ANNUAL, cash_flows=(-1_000_000, -100_000, 60_000, 1_900_000)))
    assert by_tier(integers)["catch_up"].amounts == by_tier(run(f1_terms(), *F1_SERIES))["catch_up"].amounts


@pytest.mark.parametrize(
    "cash_flows",
    [(), (1.0,), (float("nan"), 1.0), (float("inf"), 1.0), (True, 1.0), [-1.0, 1.0], ("1", 2.0)],
)
def test_an_invalid_series_is_refused(cash_flows: object) -> None:
    with pytest.raises(PartnershipExecutionError) as caught:
        allocate_partnership(f1_terms(), CommonEquityCashFlowInput(cadence=CashFlowCadence.ANNUAL, cash_flows=cash_flows))  # type: ignore[arg-type]
    assert [issue.code for issue in caught.value.issues] == [PartnershipExecutionIssueCode.INVALID_COMMON_EQUITY_SERIES]


def test_a_non_annual_cadence_is_refused() -> None:
    with pytest.raises(PartnershipExecutionError) as caught:
        allocate_partnership(f1_terms(), CommonEquityCashFlowInput(cadence="monthly", cash_flows=F1_SERIES))  # type: ignore[arg-type]
    assert [issue.code for issue in caught.value.issues] == [PartnershipExecutionIssueCode.UNSUPPORTED_CADENCE]


def test_the_downside_fixture_uses_the_lp_first_split() -> None:
    tiers = by_tier(run(f5_terms(), *F5_SERIES))
    assert close(tiers["roc"].amounts[2], 900_000.0) and close(tiers["residual"].amounts[2], 50_000.0)


def test_series_builder_is_annual() -> None:
    assert series(1.0, 2.0).cadence is CashFlowCadence.ANNUAL
    assert LP_GP[0].partner_id == "lp" and BENCH_90_10.shares[0].share == 0.9
    assert of_partner("lp").partner_id == "lp"
