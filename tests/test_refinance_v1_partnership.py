"""Refinance & Capital Events V1 Stage 1 -- the Partnership after a refinance.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 12.3 (R-I, R-O) and
fixtures F16 and F17; invariant INV-8. The refinance reaches partners only
through the unchanged Common Equity seam and the unchanged annual waterfall:
there is no refinance tier, and every P7.9 period identity holds in the event
year, for a distribution and for a contribution.
"""

from __future__ import annotations

from typing import Any

import pytest
from _p7_9_fixtures import f1_terms  # type: ignore[import-not-found]
from _refinance_v1_fixtures import (  # type: ignore[import-not-found]
    base_structure,
    base_unit,
    close,
    lender_fee,
    run_unit,
    third_party,
)

from anchor.capital_structure.contracts import CapitalStructureStatus, CommonEquityUnavailableReason
from anchor.partnership.common_equity import common_equity_input, execute_partnership
from anchor.partnership.contracts import (
    CommonEquityUnavailable,
    PartnershipExecutionError,
    PartnershipStatus,
    PartnershipUnavailableReason,
)

F5_COSTS = {"replacement_fees": (lender_fee(80_000.0),), "costs": (third_party(40_000.0),)}


def _refinanced(**sizing: Any) -> Any:
    return run_unit(base_structure(**{"ltv": 0.70, "dscr": 2.0, **F5_COSTS, **sizing}))


def _tolerance(amount: float) -> float:
    return 1e-6 + 1e-12 * abs(amount)


def _assert_period_conservation(result: Any, cash_flows: tuple[float, ...]) -> None:
    """P7.9 Section 14 identities 1 to 4, 6 and 7 in every period."""

    assert result.status is PartnershipStatus.COMPLETE
    for t, cash in enumerate(cash_flows):
        contributions = sum(partner.contributions[t] for partner in result.partners)
        distributions = sum(partner.distributions[t] for partner in result.partners)
        benchmark = sum(partner.benchmark_distributions[t] for partner in result.partners)
        assert abs(contributions - max(-cash, 0.0)) <= _tolerance(cash), t
        assert abs(distributions - max(cash, 0.0)) <= _tolerance(cash), t
        assert abs(benchmark - max(cash, 0.0)) <= _tolerance(cash), t
        tiers = sum(amount for tier in result.tiers for amount in (tier.amounts[t],))
        assert abs(tiers - max(cash, 0.0)) <= _tolerance(cash), t
    profit = sum(partner.profit for partner in result.partners)
    assert abs(profit - result.common_equity_total_profit) <= 1e-5
    assert abs(sum(partner.distribution_difference for partner in result.partners)) <= 1e-5


# =============================================================================
# F16: conservation in the event period, both signs
# =============================================================================


def test_f16_a_distribution_year_conserves_through_the_ordinary_tiers() -> None:
    structured = _refinanced()
    series = structured.common_equity.cash_flows
    assert close(series[2], 560_000 + 2_360_000)
    result = execute_partnership(f1_terms(), structured)
    assert result.common_equity_cash_flows == series
    _assert_period_conservation(result, series)


def test_f16_a_contribution_year_is_a_capital_call_by_commitment() -> None:
    """F5's costs with a binding $4,000,000 cap: N = -1,640,000, which exceeds
    year 2's operating Common Equity cash of 560,000, so the year is a net
    capital call netted inside its annual period."""

    structured = _refinanced(fixed=4_000_000.0)
    series = structured.common_equity.cash_flows
    assert close(structured.capital_events[0].bridge.net_event_cash, -1_640_000)
    assert close(series[2], 560_000 - 1_640_000) and series[2] < 0
    result = execute_partnership(f1_terms(), structured)
    _assert_period_conservation(result, series)
    by_id = {partner.partner_id: partner for partner in result.partners}
    assert close(by_id["lp"].contributions[2], 0.9 * 1_080_000) and close(by_id["gp"].contributions[2], 0.1 * 1_080_000)
    assert by_id["lp"].distributions[2] == 0.0 and by_id["gp"].distributions[2] == 0.0


def test_there_is_no_refinance_tier() -> None:
    result = execute_partnership(f1_terms(), _refinanced())
    assert [tier.tier_id for tier in result.tiers] == ["pref", "catch_up", "promote_1", "promote_2"]


# =============================================================================
# F17: partner returns change only through the Common Equity seam
# =============================================================================


def test_f17_the_partner_cash_difference_is_exactly_the_common_equity_difference() -> None:
    refinanced = _refinanced()
    neutral = run_unit(None)
    with_event = execute_partnership(f1_terms(), refinanced)
    without = execute_partnership(f1_terms(), neutral)
    for t in range(6):
        delta_partners = sum(p.net_cash_flows[t] for p in with_event.partners) - sum(p.net_cash_flows[t] for p in without.partners)
        delta_equity = refinanced.common_equity.cash_flows[t] - neutral.common_equity.cash_flows[t]
        assert abs(delta_partners - delta_equity) <= 1e-5, t
    changed = {p.partner_id: (p.irr, p.moic, p.promote_earned) for p in with_event.partners}
    before = {p.partner_id: (p.irr, p.moic, p.promote_earned) for p in without.partners}
    assert changed != before
    # Promote stays attributable to the ordinary tiers (PW-6).
    for partner in with_event.partners:
        if partner.promote_earned is not None:
            assert partner.promote_earned >= 0.0


# =============================================================================
# R-O: exactly one more accepted upstream reason, and no other
# =============================================================================


def test_an_unavailable_refinance_makes_the_partnership_unavailable_with_its_reason() -> None:
    structured = run_unit(base_structure(ltv=0.65), with_valuation=False)
    assert structured.common_equity.status is CapitalStructureStatus.REFINANCE_UNAVAILABLE
    source = common_equity_input(structured)
    assert isinstance(source, CommonEquityUnavailable)
    assert source.reason is CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE and source.requirement_ids == ()
    result = execute_partnership(f1_terms(), structured)
    assert result.status is PartnershipStatus.UNAVAILABLE
    assert result.unavailable_reason is PartnershipUnavailableReason.COMMON_EQUITY_UNAVAILABLE
    assert result.upstream_reason is CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE
    assert result.partners is None and result.common_equity_cash_flows is None


def test_any_other_missing_series_is_still_refused() -> None:
    import dataclasses

    structured = run_unit(base_structure(ltv=0.65), with_valuation=False)
    mismatched = dataclasses.replace(
        structured,
        common_equity=dataclasses.replace(structured.common_equity, status=CapitalStructureStatus.COMPLETE),
    )
    with pytest.raises(PartnershipExecutionError):
        common_equity_input(mismatched)
    unreasoned = dataclasses.replace(
        structured, common_equity=dataclasses.replace(structured.common_equity, unavailable_reason=None)
    )
    with pytest.raises(PartnershipExecutionError):
        common_equity_input(unreasoned)


def test_the_waterfall_reads_the_final_series_not_the_recurring_one() -> None:
    structured = _refinanced()
    source = common_equity_input(structured)
    assert source.cash_flows == structured.common_equity.cash_flows != structured.common_equity.recurring_cash_flows
    _, results = base_unit()
    assert source.cash_flows != results.levered_cash_flows
