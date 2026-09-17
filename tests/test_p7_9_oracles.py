"""Phase 7 Gate P7.9 Stage 1 -- independent oracles and the Common Equity seam.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 2, 3 and 16.2:

- the exact-rational oracle (``_p7_9_rational_oracle``) against every fixture
  and a generated sweep;
- the method-independent IRR look-back oracle (bisection with
  ``evaluate_irr``, never the account formula);
- one-partner neutrality and the total-profit authority, bit for bit, over
  the P7.7 / P7.8 fixture set;
- the seam: the Partnership reads the structured Common Equity Cash Flow, and
  an unresolved Funding Requirement makes it unavailable, never zero.
"""

from __future__ import annotations

import dataclasses
import random
import struct
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from _p7_7_fixtures import PARITY_CASES, parity_case  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    CEC,
    UNIT,
    UNRESOLVED,
    claim_position,
    golden_mezz,
    preferred,
    round_deal,
    round_unit,
    structure,
    visible,
)
from _p7_9_fixtures import (  # type: ignore[import-not-found]
    BENCH_90_10,
    LP_GP,
    Case,
    by_partner,
    by_tier,
    compound,
    f1_terms,
    fixture_cases,
    hurdle,
    moic,
    of_partner,
    partnership,
    residual,
    run,
    single_partner,
    split,
)
from _p7_9_rational_oracle import OracleRefusal, solve  # type: ignore[import-not-found]
from test_p7_9_conservation import generated_cases  # type: ignore[import-not-found]
from anchor.capital_structure import (
    CapitalStructureStatus,
    PositionClass,
    execute_investment_capital_structure,
    execute_unit_capital_structure,
)
from anchor.capital_structure.contracts import CommonEquityUnavailableReason
from anchor.engine.contracts import IrrStatus
from anchor.engine.returns import evaluate_irr
from anchor.partnership import (
    CashFlowCadence,
    CommonEquityCashFlowInput,
    CommonEquityUnavailable,
    PartnershipExecutionError,
    PartnershipExecutionIssueCode,
    PartnershipStatus,
    PartnershipUnavailableReason,
    PartnershipValidationError,
    common_equity_input,
    execute_partnership,
)

ORACLE_TOL = 1e-6


def bits(value: float | None) -> bytes | None:
    return None if value is None else struct.pack("<d", value)


# =============================================================================
# The exact-rational oracle
# =============================================================================


def _compare(case: Case) -> None:
    oracle = solve(case.terms, case.cash_flows)
    result = run(case.terms, *case.cash_flows)
    tiers = by_tier(result)
    partners = by_partner(result)
    assert abs(result.common_equity_total_profit - float(oracle.common_equity_total_profit)) <= ORACLE_TOL  # type: ignore[operator]
    for tier_id, amounts in oracle.tier_amounts.items():
        for actual, expected in zip(tiers[tier_id].amounts, amounts, strict=True):
            assert abs(actual - float(expected)) <= ORACLE_TOL, (case.name, tier_id)
    for (tier_id, condition_id), balances in oracle.balances.items():
        records = [record for record in tiers[tier_id].conditions if record.condition_id == condition_id]
        for record, expected in zip(records, balances, strict=True):
            assert abs(record.closing_balance - float(expected)) <= ORACLE_TOL * max(1.0, abs(float(expected)) / 1e6), (case.name, tier_id)
    for partner_id, expected in oracle.partners.items():
        actual = partners[partner_id]
        for name in (
            "total_contributions", "total_distributions", "capital_returned", "profit_distributions",
            "benchmark_capital_returned", "benchmark_profit_distributions", "distribution_difference",
            "capital_return_difference", "profit_distribution_difference", "benchmark_capital_subordination",
        ):
            assert abs(getattr(actual, name) - float(getattr(expected, name))) <= ORACLE_TOL, (case.name, partner_id, name)
        assert abs(actual.total_benchmark_distributions - float(expected.total_benchmark)) <= ORACLE_TOL
        for t, (contribution, distribution, benchmark) in enumerate(zip(expected.contributions, expected.distributions, expected.benchmark)):
            assert abs(actual.contributions[t] - float(contribution)) <= ORACLE_TOL
            assert abs(actual.distributions[t] - float(distribution)) <= ORACLE_TOL
            assert abs(actual.benchmark_distributions[t] - float(benchmark)) <= ORACLE_TOL
        assert (actual.promote_earned is None) == (expected.promote_earned is None)
        if expected.promote_earned is not None:
            assert abs(actual.promote_earned - float(expected.promote_earned)) <= ORACLE_TOL  # type: ignore[operator]
            assert expected.promote_attribution_by_tier is not None
            for item in actual.promote_attribution_by_tier:
                assert abs(item.amount - float(expected.promote_attribution_by_tier[item.tier_id])) <= ORACLE_TOL
        for item in actual.capital_return_difference_by_tier:
            assert abs(item.amount - float(expected.capital_difference_by_tier[item.tier_id])) <= ORACLE_TOL
        for item in actual.profit_distribution_difference_by_tier:
            assert abs(item.amount - float(expected.profit_difference_by_tier[item.tier_id])) <= ORACLE_TOL
        for item in actual.distributions_by_tier:
            assert abs(item.amount - float(expected.distributions_by_tier[item.tier_id])) <= ORACLE_TOL


@pytest.mark.parametrize("case", [*fixture_cases(), *generated_cases()], ids=lambda case: case.name)
def test_the_engine_matches_the_exact_rational_oracle(case: Case) -> None:
    _compare(case)


def test_the_oracle_states_the_ratified_hand_figures_exactly() -> None:
    oracle = solve(f1_terms(), (-1_000_000.0, -100_000.0, 60_000.0, 1_900_000.0))
    assert oracle.tier_amounts["catch_up"][3] == Fraction(67_888)
    assert oracle.tier_amounts["promote_1"][3] == Fraction(136_624)
    assert oracle.partners["gp"].promote_earned == Fraction("124393.6")
    assert oracle.partners["gp"].promote_attribution_by_tier == {
        "pref": 0, "catch_up": Fraction(33_944), "promote_1": Fraction("13662.4"), "promote_2": Fraction("76787.2"),
    }


def test_the_oracle_refuses_what_the_engine_refuses() -> None:
    from _p7_9_fixtures import f11_terms  # type: ignore[import-not-found]

    with pytest.raises(OracleRefusal):
        solve(f11_terms(), (0.0, 500.0, -1_000.0, 2_000.0))
    with pytest.raises(PartnershipExecutionError):
        run(f11_terms(), 0.0, 500.0, -1_000.0, 2_000.0)


# =============================================================================
# The IRR look-back oracle (method-independent)
# =============================================================================


def _subject_irr_at_least(series: list[float], rate: float) -> bool:
    irr, status = evaluate_irr(tuple(series))
    return status is IrrStatus.DEFINED and irr is not None and irr >= rate


def lookback_tier_amounts(
    cash_flows: tuple[float, ...], rate: float, *, subject_share: float, residual_share: float, commitment: float
) -> list[float]:
    """The pref tier's cash each period, found by bisection on the subject's
    IRR with ``evaluate_irr`` -- never the account formula.

    The hurdle is tested before the residual pays, so the candidate series
    holds the subject's earlier receipts (from every tier) plus only this
    period's tier cash: the least tier cash that lifts the subject's IRR
    through ``t`` to ``rate``, capped by the cash. The subject then also
    receives ``residual_share`` of what the tier leaves."""

    subject: list[float] = []
    amounts: list[float] = []
    for cash in cash_flows:
        if cash <= 0.0:
            subject.append(commitment * cash)
            amounts.append(0.0)
            continue

        def reaches(tier_cash: float) -> bool:
            return _subject_irr_at_least([*subject, subject_share * tier_cash], rate)

        if reaches(0.0):
            tier_cash = 0.0
        elif not reaches(cash):
            tier_cash = cash
        else:
            low, high = 0.0, cash
            for _ in range(200):
                middle = (low + high) / 2.0
                if reaches(middle):
                    high = middle
                else:
                    low = middle
            tier_cash = high
        subject.append(subject_share * tier_cash + residual_share * (cash - tier_cash))
        amounts.append(tier_cash)
    return amounts


def _lookback_terms(rate: float) -> Any:
    return partnership(
        LP_GP,
        (hurdle("pref", 10, of_partner("lp"), (compound("pref", rate),), split(lp=1.0, gp=0.0)), residual("residual", 20, split(lp=0.5, gp=0.5))),
        bench=BENCH_90_10,
        participants=("gp",),
    )


def _lookback_series(rng: random.Random) -> tuple[float, ...]:
    """Conventional for the subject: calls first, then distributions."""

    calls = [-rng.uniform(100_000.0, 2_000_000.0) for _ in range(rng.randint(1, 2))]
    distributions = [rng.uniform(0.0, 1_500_000.0) for _ in range(rng.randint(1, 5))]
    return (*calls, *distributions)


@pytest.mark.parametrize("seed", range(12))
def test_compound_tiers_match_the_irr_lookback_oracle(seed: int) -> None:
    rng = random.Random(seed)
    rate = rng.choice((0.06, 0.08, 0.12, 0.2))
    cash_flows = _lookback_series(rng)
    engine = by_tier(run(_lookback_terms(rate), *cash_flows))["pref"].amounts
    oracle = lookback_tier_amounts(cash_flows, rate, subject_share=1.0, residual_share=0.5, commitment=0.9)
    for actual, expected in zip(engine, oracle, strict=True):
        assert abs(actual - expected) <= 1e-3, (seed, engine, oracle)


def test_the_lookback_oracle_agrees_after_a_surplus_year() -> None:
    cash_flows = (-1_000_000.0, 1_500_000.0, 200_000.0)
    engine = by_tier(run(_lookback_terms(0.08), *cash_flows))["pref"].amounts
    oracle = lookback_tier_amounts(cash_flows, 0.08, subject_share=1.0, residual_share=0.5, commitment=0.9)
    assert engine[2] == 0.0 and oracle[2] == 0.0
    assert abs(engine[1] - oracle[1]) <= 1e-3


def test_a_compounded_surplus_absorbs_a_later_capital_call_by_hand() -> None:
    """The case a floor would get wrong. Year 1: the LP's 972,000 hurdle plus
    half of the 528,000 residual leaves a surplus of 264,000. Year 2: it
    compounds to 285,120 and absorbs the LP's 270,000 call (15,120 left).
    Year 3: 16,329.60 of surplus, so the pref pays nothing. A floored account
    would have owed 270,000 x 1.08 = 291,600 in year 3."""

    tier = by_tier(run(_lookback_terms(0.08), -1_000_000.0, 1_500_000.0, -300_000.0, 400_000.0))["pref"]
    balances = [record.closing_balance for record in tier.conditions]
    assert balances[1] == pytest.approx(-264_000.0)
    assert balances[2] == pytest.approx(-15_120.0)
    assert tier.conditions[3].opening_balance + tier.conditions[3].accrual == pytest.approx(-16_329.60)
    assert tier.amounts[3] == 0.0


def test_the_f1_lp_series_truncated_at_each_hurdle_has_the_hurdle_irr() -> None:
    lp = by_partner(run(f1_terms(), -1_000_000.0, -100_000.0, 60_000.0, 1_900_000.0))["lp"]
    pref_only = (-900_000.0, -90_000.0, 54_000.0, 1_180_396.80)
    through_promote_1 = (-900_000.0, -90_000.0, 54_000.0, 1_180_396.80 + 27_155.20 + 109_299.20)
    assert abs(evaluate_irr(pref_only)[0] - 0.08) < 1e-9  # type: ignore[operator]
    assert abs(evaluate_irr(through_promote_1)[0] - 0.12) < 1e-9  # type: ignore[operator]
    assert lp.distributions_by_tier[0].amount == pytest.approx(54_000.0 + 1_180_396.80)


def test_moic_closure() -> None:
    terms = partnership(
        LP_GP,
        (hurdle("moic", 10, of_partner("lp"), (moic("m", 1.4),), split(lp=0.9, gp=0.1)), residual("residual", 20, split(lp=0.5, gp=0.5))),
        bench=BENCH_90_10,
        participants=(),
    )
    lp = by_partner(run(terms, -1_000_000.0, 500_000.0, 1_500_000.0))["lp"]
    moic_cash = sum(item for item in by_tier(run(terms, -1_000_000.0, 500_000.0, 1_500_000.0))["moic"].amounts)
    assert moic_cash * 0.9 == pytest.approx(1.4 * lp.total_contributions)


# =============================================================================
# One-partner neutrality and the total-profit authority
# =============================================================================


def _unit_result(name: str) -> Any:
    terms, results = parity_case(name)
    return execute_unit_capital_structure(unit_id="u1", terms=terms, results=results)


def _structured_results(tmp_path: Path) -> list[tuple[str, Any]]:
    cases: list[tuple[str, Any]] = [(name, _unit_result(name)) for name in PARITY_CASES]
    terms, results = round_unit()
    cases.append(("round-mezz", execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(golden_mezz()))))
    cases.append(("round-plain", execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results)))
    db = tmp_path / "p7_9_neutral.db"
    a = round_deal(db, name="Unit A")
    b = round_deal(db, name="Unit B", ltv=0.0)
    analysis, units = visible(db, a, b)
    cases.append(("investment", execute_investment_capital_structure(units=units, consolidated=analysis.consolidated_results)))
    return cases


def test_one_partner_neutrality_and_the_total_profit_authority_bit_for_bit(tmp_path: Path) -> None:
    for name, structured in _structured_results(tmp_path):
        common = structured.common_equity
        assert common.cash_flows is not None, name
        result = execute_partnership(single_partner(), structured)
        (only,) = result.partners  # type: ignore[misc]
        assert bits(result.common_equity_total_profit) == bits(common.total_profit), name
        assert bits(only.profit) == bits(common.total_profit), name
        assert bits(only.irr) == bits(common.irr) and only.irr_status is common.irr_status, name
        assert bits(only.moic) == bits(common.equity_multiple), name
        assert bits(only.total_contributions) == bits(common.total_equity_invested), name
        assert bits(only.total_distributions) == bits(common.total_cash_returned), name
        assert only.promote_earned is None and only.benchmark_capital_subordination == 0.0
        assert only.distribution_difference == 0.0
        assert result.common_equity_cash_flows is common.cash_flows


def test_the_input_contract_carries_no_profit_to_contradict() -> None:
    assert not hasattr(CommonEquityCashFlowInput(cadence=CashFlowCadence.ANNUAL, cash_flows=(-1.0, 2.0)), "total_profit")


# =============================================================================
# The Common Equity seam
# =============================================================================


def test_the_partnership_reads_the_structured_series_not_the_levered_one() -> None:
    terms, results = round_unit()
    structured = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(golden_mezz()))
    common = structured.common_equity.cash_flows
    assert common is not None and common != results.levered_cash_flows
    source = common_equity_input(structured)
    assert isinstance(source, CommonEquityCashFlowInput)
    assert source.cash_flows is common and source.cadence is CashFlowCadence.ANNUAL
    result = execute_partnership(f1_terms(), structured)
    partners = by_partner(result)
    assert result.common_equity_cash_flows is common
    assert sum(p.profit for p in partners.values()) == pytest.approx(structured.common_equity.total_profit)
    levered_profit = sum(value for value in results.levered_cash_flows)
    assert sum(p.profit for p in partners.values()) != pytest.approx(levered_profit)


def test_an_unresolved_funding_requirement_makes_the_partnership_unavailable() -> None:
    terms, results = round_unit()
    junior = claim_position(
        "pref", position_class=PositionClass.PREFERRED_EQUITY, priority=3, resolution=CEC, amount=1_000_000.0,
        terms=preferred(preferred_rate=0.10, current_pay_rate=0.10),
    )
    structured = execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(junior, golden_mezz(UNRESOLVED))
    )
    assert structured.status is CapitalStructureStatus.UNRESOLVED_FUNDING
    source = common_equity_input(structured)
    assert source == CommonEquityUnavailable(
        reason=CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT,
        message=structured.common_equity.unavailable_message,
        requirement_ids=("mezz/hold_year/4",),
    )
    result = execute_partnership(f1_terms(), structured)
    assert result.status is PartnershipStatus.UNAVAILABLE
    assert result.unavailable_reason is PartnershipUnavailableReason.COMMON_EQUITY_UNAVAILABLE
    assert result.upstream_reason is CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
    assert result.upstream_requirement_ids == ("mezz/hold_year/4",)
    assert "mezz/hold_year/4" in result.unavailable_message  # type: ignore[operator]
    assert (result.partners, result.tiers, result.periods) == (None, None, None)
    assert (result.common_equity_cash_flows, result.common_equity_total_profit) == (None, None)
    assert result.cadence is CashFlowCadence.ANNUAL
    assert result.promote_participant_ids == ("gp",)


def test_an_invalid_contract_raises_even_when_upstream_is_unavailable() -> None:
    terms, results = round_unit()
    structured = execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results, capital_structure=structure(golden_mezz(UNRESOLVED))
    )
    with pytest.raises(PartnershipValidationError):
        execute_partnership(dataclasses.replace(f1_terms(), promote_benchmark=None), structured)


def test_a_missing_series_without_an_unresolved_reason_is_refused() -> None:
    terms, results = round_unit()
    structured = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results)
    broken = dataclasses.replace(structured, common_equity=dataclasses.replace(structured.common_equity, cash_flows=None))
    with pytest.raises(PartnershipExecutionError) as caught:
        common_equity_input(broken)
    assert [issue.code for issue in caught.value.issues] == [PartnershipExecutionIssueCode.INVALID_COMMON_EQUITY_SERIES]


def test_a_series_that_disagrees_with_the_hold_is_refused() -> None:
    terms, results = round_unit()
    structured = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results)
    broken = dataclasses.replace(structured, hold_period=structured.hold_period + 1)
    with pytest.raises(PartnershipExecutionError) as caught:
        common_equity_input(broken)
    assert [issue.code for issue in caught.value.issues] == [PartnershipExecutionIssueCode.INVALID_COMMON_EQUITY_SERIES]


def test_the_seam_leaves_the_structured_result_untouched() -> None:
    terms, results = round_unit()
    structured = execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results, capital_structure=structure(golden_mezz()))
    before = dataclasses.asdict(structured)
    execute_partnership(f1_terms(), structured)
    assert dataclasses.asdict(structured) == before
