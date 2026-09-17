"""Phase 7 Gate P7.9 -- the partnership waterfall.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 5.2, 6
to 10 and 12 to 14 (ratified); that document governs on any discrepancy.

**Period ordering (Section 7).** For each period ``t`` of the input: open every
hurdle account; accrue (``t >= 1``); contribute ``max(-CECF_t, 0)`` by
commitment share; distribute ``max(CECF_t, 0)`` through the tiers in
``sequence`` order, posting each subject member's receipt to every account
that contains it before the next tier; benchmark the same distribution by the
stated benchmark shares; close. Tiers are re-entered every period.

**Catch-up (Section 9).** Capacity is zero while partnership profit is not
positive; otherwise ``max(0, (tau x P - Pr) / (c - tau))``, where ``c`` is the
recipient's aggregate share of the explicit split.

The engine reads one annual series and nothing else: it imports neither the
Capital Structure results nor any store or route.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from . import accounts, allocation, attribution, metrics
from .contracts import (
    AccrualConvention,
    CommonEquityUnavailableReason,
    WATERFALL_AMOUNT_TOLERANCE,
    CashFlowCadence,
    CommonEquityCashFlowInput,
    ContributionRule,
    ExplicitSplit,
    HurdleAccountRecord,
    HurdleCondition,
    HurdleTerms,
    IrrHurdle,
    CatchUpPeriodRecord,
    CatchUpTerms,
    PartnerPeriodAmounts,
    PartnerResult,
    PartnerShare,
    PartnerTierAmount,
    Partnership,
    PartnershipExecutionError,
    PartnershipExecutionIssue,
    PartnershipExecutionIssueCode,
    PartnershipResult,
    PartnershipStatus,
    PartnershipUnavailableReason,
    PeriodRecord,
    PeriodShares,
    SplitRule,
    TierKind,
    TierRemaining,
    TierResult,
    WaterfallTier,
)
from .validation import (
    explicit_shares,
    members_share,
    ordered_tiers,
    partner_ids,
    recipient_members,
    require_valid_partnership,
    subject_members,
)

ExecCode = PartnershipExecutionIssueCode

#: The conventions, contribution rules and cadences v1 executes.
SUPPORTED_ACCRUAL_CONVENTIONS = frozenset({AccrualConvention.SIMPLE, AccrualConvention.ANNUAL_COMPOUND})
SUPPORTED_CONTRIBUTION_RULES = frozenset({ContributionRule.PRO_RATA_BY_COMMITMENT})
SUPPORTED_CADENCES = frozenset({CashFlowCadence.ANNUAL})


def _refuse(code: ExecCode, message: str, *, tier_id: str | None = None, period: int | None = None) -> PartnershipExecutionError:
    return PartnershipExecutionError((PartnershipExecutionIssue(code=code, message=message, tier_id=tier_id, period=period),))


# =============================================================================
# Execution checks
# =============================================================================


def require_executable_contract(partnership: Partnership) -> None:
    """Refuse a valid contract that v1 does not execute (Section 5.2)."""

    issues: list[PartnershipExecutionIssue] = []
    if partnership.contribution_rule not in SUPPORTED_CONTRIBUTION_RULES:
        issues.append(PartnershipExecutionIssue(
            code=ExecCode.UNSUPPORTED_CONTRIBUTION_RULE,
            message=f"Contribution rule {partnership.contribution_rule.value} is not executed by v1.",
        ))
    for tier in ordered_tiers(partnership):
        if tier.hurdle is None:
            continue
        for condition in sorted(tier.hurdle.conditions, key=lambda item: item.condition_id):
            if isinstance(condition, IrrHurdle) and condition.accrual_convention not in SUPPORTED_ACCRUAL_CONVENTIONS:
                issues.append(PartnershipExecutionIssue(
                    code=ExecCode.UNSUPPORTED_ACCRUAL_CONVENTION,
                    message=f"Condition {condition.condition_id} uses an accrual convention v1 does not execute.",
                    tier_id=tier.tier_id,
                ))
    if issues:
        raise PartnershipExecutionError(issues)


def require_executable_series(common_equity: CommonEquityCashFlowInput) -> tuple[float, ...]:
    if not isinstance(common_equity, CommonEquityCashFlowInput):
        raise _refuse(ExecCode.INVALID_COMMON_EQUITY_SERIES, "Expected a CommonEquityCashFlowInput.")
    if common_equity.cadence not in SUPPORTED_CADENCES:
        raise _refuse(ExecCode.UNSUPPORTED_CADENCE, f"Cadence {common_equity.cadence!r} is not executed by v1; only annual.")
    series = common_equity.cash_flows
    valid = (
        isinstance(series, tuple)
        and len(series) >= 2
        and all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) for value in series)
    )
    if not valid:
        raise _refuse(ExecCode.INVALID_COMMON_EQUITY_SERIES, "The Common Equity Cash Flow must be a tuple of at least two finite numbers.")
    return tuple(float(value) for value in series)


# =============================================================================
# Tier helpers
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class _Tier:
    tier: WaterfallTier
    subject: tuple[str, ...]
    recipient: tuple[str, ...]
    explicit: dict[str, float] | None


def _conditions(tier: WaterfallTier) -> tuple[HurdleCondition, ...]:
    assert isinstance(tier.hurdle, HurdleTerms)
    return tuple(sorted(tier.hurdle.conditions, key=lambda condition: condition.condition_id))


def tier_shares(
    tier: _Tier, cumulative_contributions: dict[str, float], period: int
) -> dict[str, float]:
    """The shares a tier applies in ``period``: its explicit split, or the
    cumulative-contribution shares, refused when nothing has been contributed."""

    if tier.explicit is not None:
        return tier.explicit
    shares = allocation.pro_rata_by_contribution_shares(cumulative_contributions)
    if shares is None:
        raise _refuse(
            ExecCode.NO_CONTRIBUTIONS_FOR_PRO_RATA_SPLIT,
            f"Tier {tier.tier.tier_id} splits pro rata by contribution, but nothing has been contributed "
            f"when it must distribute cash in period {period}.",
            tier_id=tier.tier.tier_id,
            period=period,
        )
    return shares


def partnership_profit(distributed: dict[str, float], contributed: dict[str, float], members: tuple[str, ...]) -> float:
    """Cumulative distributions less contributions of ``members``, in canonical
    order."""

    total = 0.0
    for partner_id in sorted(members):
        total = total + (distributed[partner_id] - contributed[partner_id])
    return total


def catch_up_capacity(*, profit: float, recipient_profit: float, rate: float, target: float) -> float:
    """Section 9: zero while partnership profit is not positive; otherwise the
    closed form."""

    if profit <= WATERFALL_AMOUNT_TOLERANCE:
        return 0.0
    capacity = max(0.0, (target * profit - recipient_profit) / (rate - target))
    return 0.0 if capacity <= WATERFALL_AMOUNT_TOLERANCE else capacity


def subject_flow(amounts: dict[str, float], members: tuple[str, ...]) -> float:
    """The subject's aggregate flow: its members' amounts, in canonical order."""

    total = 0.0
    for partner_id in sorted(members):
        total = total + amounts[partner_id]
    return total


# =============================================================================
# The period loop
# =============================================================================


def allocate_partnership(partnership: Partnership, common_equity: CommonEquityCashFlowInput) -> PartnershipResult:
    """Allocate ``common_equity`` under ``partnership`` (Sections 7-11).

    Raises ``PartnershipValidationError`` for an invalid contract and
    ``PartnershipExecutionError`` for one v1 does not execute."""

    require_valid_partnership(partnership)
    require_executable_contract(partnership)
    series = require_executable_series(common_equity)
    periods = len(series)
    ids = partner_ids(partnership)
    commitment = allocation.commitment_shares(partnership)
    benchmark = allocation.benchmark_shares(partnership)
    participants = frozenset(partnership.promote_participant_ids)

    tiers = tuple(
        _Tier(
            tier=tier,
            subject=subject_members(partnership, tier.hurdle.hurdle_subject) if tier.hurdle is not None else (),
            recipient=recipient_members(partnership, tier.catch_up.recipient) if tier.catch_up is not None else (),
            explicit=explicit_shares(tier.split) if isinstance(tier.split, ExplicitSplit) else None,
        )
        for tier in ordered_tiers(partnership)
    )
    account_keys = tuple(
        (index, condition) for index, tier in enumerate(tiers) if tier.tier.kind is TierKind.HURDLE for condition in _conditions(tier.tier)
    )
    states = {(index, condition.condition_id): accounts.open_account() for index, condition in account_keys}
    records: dict[tuple[int, str], list[HurdleAccountRecord]] = {key: [] for key in states}
    catch_up_records: dict[int, list[CatchUpPeriodRecord]] = {index: [] for index in range(len(tiers))}
    shares_applied: dict[int, list[PeriodShares]] = {index: [] for index in range(len(tiers))}

    contributions = {partner_id: [0.0] * periods for partner_id in ids}
    tier_partner = {index: {partner_id: [0.0] * periods for partner_id in ids} for index in range(len(tiers))}
    tier_amounts = {index: [0.0] * periods for index in range(len(tiers))}
    benchmark_by_period = {partner_id: [0.0] * periods for partner_id in ids}
    benchmark_entries = {partner_id: [] for partner_id in ids}  # type: dict[str, list[attribution.Entry]]
    actual_entries = {partner_id: [] for partner_id in ids}  # type: dict[str, list[attribution.Entry]]
    contributed = {partner_id: 0.0 for partner_id in ids}
    distributed = {partner_id: 0.0 for partner_id in ids}
    period_records: list[PeriodRecord] = []

    for period, cash_flow in enumerate(series):
        opening: dict[tuple[int, str], float] = {}
        accrued: dict[tuple[int, str], float] = {}
        subject_contrib: dict[tuple[int, str], float] = {}
        flows = {key: [0.0, 0.0, 0.0] for key in states}  # before / from / after the account's tier
        capacity_at_entry: dict[tuple[int, str], float | None] = {key: None for key in states}
        for index, condition in account_keys:
            key = (index, condition.condition_id)
            opening[key] = states[key].balance
            if period >= 1:
                states[key], accrued[key] = accounts.accrue(states[key], condition)
            else:
                accrued[key] = 0.0
            subject_contrib[key] = 0.0

        call = max(-cash_flow, 0.0)
        if cash_flow < 0.0:
            called = allocation.allocate(call, commitment)
            for partner_id in ids:
                contributions[partner_id][period] = called[partner_id]
                contributed[partner_id] = contributed[partner_id] + called[partner_id]
            for index, condition in account_keys:
                key = (index, condition.condition_id)
                amount = subject_flow(called, tiers[index].subject)
                subject_contrib[key] = amount
                states[key] = accounts.apply_contribution(states[key], condition, amount)

        distribution = max(cash_flow, 0.0)
        remaining_after: list[TierRemaining] = []
        remaining = distribution
        if cash_flow > 0.0:
            for index, tier in enumerate(tiers):
                if remaining <= 0.0:
                    break
                kind = tier.tier.kind
                shares: dict[str, float] | None = None
                catch_up_entry: tuple[float, float, float, float] | None = None
                if kind is TierKind.HURDLE:
                    assert tier.tier.hurdle is not None
                    capacities: list[float] = []
                    for condition in _conditions(tier.tier):
                        key = (index, condition.condition_id)
                        balance = states[key].balance
                        if accounts.is_satisfied(balance):
                            capacity = 0.0
                        else:
                            shares = tier_shares(tier, contributed, period)
                            subject_share = members_share(shares, tier.subject)
                            if subject_share <= 0.0:
                                raise _refuse(
                                    ExecCode.SUBJECT_WITHOUT_SPLIT_SHARE,
                                    f"Tier {tier.tier.tier_id}'s subject is owed {balance!r} but has no share in the split in period {period}.",
                                    tier_id=tier.tier.tier_id,
                                    period=period,
                                )
                            capacity = accounts.condition_capacity(balance, subject_share)
                        capacity_at_entry[key] = capacity
                        capacities.append(capacity)
                    paid = min(remaining, accounts.combine_capacities(tuple(capacities), tier.tier.hurdle.combinator))
                elif kind is TierKind.CATCH_UP:
                    assert isinstance(tier.tier.catch_up, CatchUpTerms) and tier.explicit is not None
                    rate = members_share(tier.explicit, tier.recipient)
                    target = tier.tier.catch_up.target_profit_share
                    profit = partnership_profit(distributed, contributed, ids)
                    recipient_profit = partnership_profit(distributed, contributed, tier.recipient)
                    capacity = catch_up_capacity(profit=profit, recipient_profit=recipient_profit, rate=rate, target=target)
                    catch_up_entry = (profit, recipient_profit, capacity, target)
                    paid = min(remaining, capacity)
                else:
                    paid = remaining

                if paid > 0.0:
                    if shares is None:
                        shares = tier_shares(tier, contributed, period)
                    allocated = allocation.allocate(paid, shares)
                    shares_applied[index].append(PeriodShares(
                        period=period,
                        shares=tuple(PartnerShare(partner_id=partner_id, share=shares[partner_id]) for partner_id in ids),
                    ))
                    tier_amounts[index][period] = paid
                    for partner_id in ids:
                        tier_partner[index][partner_id][period] = allocated[partner_id]
                        distributed[partner_id] = distributed[partner_id] + allocated[partner_id]
                        actual_entries[partner_id].append((period, tier.tier.sequence, tier.tier.tier_id, allocated[partner_id]))
                    for account_index, condition in account_keys:
                        key = (account_index, condition.condition_id)
                        amount = subject_flow(allocated, tiers[account_index].subject)
                        position = 0 if index < account_index else (1 if index == account_index else 2)
                        flows[key][position] = flows[key][position] + amount
                        states[key] = accounts.apply_distribution(states[key], condition, amount)
                    benchmark_slice = allocation.allocate(paid, benchmark)
                    for partner_id in ids:
                        benchmark_entries[partner_id].append((period, tier.tier.sequence, tier.tier.tier_id, benchmark_slice[partner_id]))

                if catch_up_entry is not None:
                    entry_profit, entry_recipient_profit, entry_capacity, target = catch_up_entry
                    exit_profit = partnership_profit(distributed, contributed, ids)
                    exit_recipient_profit = partnership_profit(distributed, contributed, tier.recipient)
                    catch_up_records[index].append(CatchUpPeriodRecord(
                        period=period,
                        partnership_profit_at_entry=entry_profit,
                        recipient_profit_at_entry=entry_recipient_profit,
                        profit_domain_open=entry_profit > WATERFALL_AMOUNT_TOLERANCE,
                        capacity_at_entry=entry_capacity,
                        paid=paid,
                        partnership_profit_at_exit=exit_profit,
                        recipient_profit_at_exit=exit_recipient_profit,
                        caught_up=exit_profit > WATERFALL_AMOUNT_TOLERANCE
                        and exit_recipient_profit >= target * exit_profit - WATERFALL_AMOUNT_TOLERANCE,
                    ))
                remaining = 0.0 if kind is TierKind.RESIDUAL else remaining - paid
                remaining_after.append(TierRemaining(tier_id=tier.tier.tier_id, sequence=tier.tier.sequence, remaining=remaining))

        benchmark_period = allocation.allocate(distribution, benchmark)
        for partner_id in ids:
            benchmark_by_period[partner_id][period] = benchmark_period[partner_id]

        for index, condition in account_keys:
            key = (index, condition.condition_id)
            state = states[key]
            simple = isinstance(condition, IrrHurdle) and condition.accrual_convention is AccrualConvention.SIMPLE
            records[key].append(HurdleAccountRecord(
                condition_id=condition.condition_id,
                period=period,
                opening_balance=opening[key],
                accrual=accrued[key],
                subject_contributions=subject_contrib[key],
                subject_distributions_before_tier=flows[key][0],
                subject_distributions_from_tier=flows[key][1],
                subject_distributions_after_tier=flows[key][2],
                closing_balance=state.balance,
                capacity_at_entry=capacity_at_entry[key],
                satisfied_at_close=accounts.is_satisfied(state.balance),
                simple_distribution_order=condition.simple_distribution_order if simple else None,  # type: ignore[union-attr]
                outstanding_capital=state.outstanding_capital if simple else None,
                accrued_return=state.accrued_return if simple else None,
            ))
        period_records.append(PeriodRecord(
            period=period,
            common_equity_cash_flow=cash_flow,
            total_contributions=call,
            total_distributions=distribution,
            remaining_after_tier=tuple(remaining_after),
        ))

    tier_keys = tuple((tier.tier.tier_id, tier.tier.sequence) for tier in tiers)
    partner_results = tuple(
        _partner_result(
            partnership,
            partner_id,
            contributions=tuple(contributions[partner_id]),
            tier_partner=tier_partner,
            tiers=tiers,
            benchmark_by_period=tuple(benchmark_by_period[partner_id]),
            tier_keys=tier_keys,
            actual_entries=tuple(actual_entries[partner_id]),
            benchmark_entries=tuple(benchmark_entries[partner_id]),
            is_participant=partner_id in participants,
            benchmark_share=benchmark[partner_id],
        )
        for partner_id in ids
    )
    tier_results = tuple(
        _tier_result(
            tier,
            ids=ids,
            amounts=tuple(tier_amounts[index]),
            partner_amounts=tier_partner[index],
            shares=tuple(shares_applied[index]),
            conditions=tuple(
                record
                for condition in (_conditions(tier.tier) if tier.tier.kind is TierKind.HURDLE else ())
                for record in records[(index, condition.condition_id)]
            ),
            catch_up=tuple(catch_up_records[index]),
        )
        for index, tier in enumerate(tiers)
    )
    return PartnershipResult(
        status=PartnershipStatus.COMPLETE,
        unavailable_reason=None,
        unavailable_message=None,
        upstream_reason=None,
        upstream_requirement_ids=(),
        cadence=common_equity.cadence,
        promote_participant_ids=tuple(sorted(partnership.promote_participant_ids)),
        common_equity_cash_flows=common_equity.cash_flows,
        common_equity_total_profit=metrics.common_equity_total_profit(common_equity.cash_flows),
        partners=partner_results,
        tiers=tier_results,
        periods=tuple(period_records),
    )


def _partner_result(
    partnership: Partnership,
    partner_id: str,
    *,
    contributions: tuple[float, ...],
    tier_partner: dict[int, dict[str, list[float]]],
    tiers: tuple[_Tier, ...],
    benchmark_by_period: tuple[float, ...],
    tier_keys: tuple[tuple[str, int], ...],
    actual_entries: tuple[attribution.Entry, ...],
    benchmark_entries: tuple[attribution.Entry, ...],
    is_participant: bool,
    benchmark_share: float,
) -> PartnerResult:
    partner = next(item for item in partnership.partners if item.partner_id == partner_id)
    periods = len(contributions)
    distributions = [0.0] * periods
    for index in range(len(tiers)):
        for period in range(periods):
            distributions[period] = distributions[period] + tier_partner[index][partner_id][period]
    returns = metrics.partner_returns(contributions, tuple(distributions))
    total_benchmark = 0.0
    for amount in benchmark_by_period:
        total_benchmark = total_benchmark + amount
    figures = attribution.attribute(
        tiers=tier_keys,
        total_contributions=returns.total_contributions,
        total_distributions=returns.total_distributions,
        total_benchmark_distributions=total_benchmark,
        actual_entries=actual_entries,
        benchmark_entries=benchmark_entries,
        is_participant=is_participant,
    )
    by_tier = []
    for index, (tier_id, sequence) in enumerate(tier_keys):
        total = 0.0
        for amount in tier_partner[index][partner_id]:
            total = total + amount
        by_tier.append(PartnerTierAmount(tier_id=tier_id, sequence=sequence, amount=total))
    return PartnerResult(
        partner_id=partner_id,
        name=partner.name,
        role=partner.role,
        investor_class=partner.investor_class,
        commitment_share=partner.commitment_share,
        benchmark_share=benchmark_share,
        benchmark_equals_commitment=float(partner.commitment_share) == benchmark_share,
        is_promote_participant=is_participant,
        contributions=contributions,
        distributions=tuple(distributions),
        net_cash_flows=returns.net_cash_flows,
        total_contributions=returns.total_contributions,
        total_distributions=returns.total_distributions,
        profit=returns.profit,
        irr=returns.irr,
        irr_status=returns.irr_status,
        moic=returns.moic,
        moic_unavailable_reason=returns.moic_unavailable_reason,
        benchmark_distributions=benchmark_by_period,
        total_benchmark_distributions=total_benchmark,
        capital_returned=figures.capital_returned,
        profit_distributions=figures.profit_distributions,
        benchmark_capital_returned=figures.benchmark_capital_returned,
        benchmark_profit_distributions=figures.benchmark_profit_distributions,
        distribution_difference=figures.distribution_difference,
        distribution_advantage=figures.distribution_advantage,
        distribution_disadvantage=figures.distribution_disadvantage,
        capital_return_difference=figures.capital_return_difference,
        profit_distribution_difference=figures.profit_distribution_difference,
        promote_earned=figures.promote_earned,
        promote_unavailable_reason=figures.promote_unavailable_reason,
        benchmark_capital_subordination=figures.benchmark_capital_subordination,
        distributions_by_tier=tuple(by_tier),
        capital_return_difference_by_tier=figures.capital_return_difference_by_tier,
        profit_distribution_difference_by_tier=figures.profit_distribution_difference_by_tier,
        promote_attribution_by_tier=figures.promote_attribution_by_tier,
    )


def _tier_result(
    tier: _Tier,
    *,
    ids: tuple[str, ...],
    amounts: tuple[float, ...],
    partner_amounts: dict[str, list[float]],
    shares: tuple[PeriodShares, ...],
    conditions: tuple[HurdleAccountRecord, ...],
    catch_up: tuple[CatchUpPeriodRecord, ...],
) -> TierResult:
    authored = tier.tier
    is_hurdle = authored.kind is TierKind.HURDLE
    is_catch_up = authored.kind is TierKind.CATCH_UP
    return TierResult(
        tier_id=authored.tier_id,
        name=authored.name,
        sequence=authored.sequence,
        kind=authored.kind,
        split_rule=SplitRule.EXPLICIT if tier.explicit is not None else SplitRule.PRO_RATA_BY_CONTRIBUTION,
        shares_by_period=shares,
        hurdle_subject=authored.hurdle.hurdle_subject if is_hurdle and authored.hurdle is not None else None,
        subject_partner_ids=tier.subject if is_hurdle else None,
        combinator=authored.hurdle.combinator if is_hurdle and authored.hurdle is not None else None,
        catch_up_recipient=authored.catch_up.recipient if is_catch_up and authored.catch_up is not None else None,
        recipient_partner_ids=tier.recipient if is_catch_up else None,
        catch_up_rate=members_share(tier.explicit, tier.recipient) if is_catch_up and tier.explicit is not None else None,
        target_profit_share=authored.catch_up.target_profit_share if is_catch_up and authored.catch_up is not None else None,
        amounts=amounts,
        partner_amounts=tuple(PartnerPeriodAmounts(partner_id=partner_id, amounts=tuple(partner_amounts[partner_id])) for partner_id in ids),
        conditions=conditions,
        catch_up_records=catch_up,
    )


def unavailable_partnership_result(
    partnership: Partnership,
    *,
    upstream_reason: CommonEquityUnavailableReason,
    upstream_message: str,
    requirement_ids: tuple[str, ...],
) -> PartnershipResult:
    """The Partnership when upstream Common Equity is not reported. The
    contract is still validated and checked; every figure is ``None``."""

    require_valid_partnership(partnership)
    require_executable_contract(partnership)
    return PartnershipResult(
        status=PartnershipStatus.UNAVAILABLE,
        unavailable_reason=PartnershipUnavailableReason.COMMON_EQUITY_UNAVAILABLE,
        unavailable_message=(
            "The Partnership is not reported: the Common Equity Cash Flow is unavailable "
            f"({upstream_reason.value}; Funding Requirement(s) {', '.join(requirement_ids) or 'none named'}). "
            f"{upstream_message}"
        ),
        upstream_reason=upstream_reason,
        upstream_requirement_ids=requirement_ids,
        cadence=None,
        promote_participant_ids=tuple(sorted(partnership.promote_participant_ids)),
        common_equity_cash_flows=None,
        common_equity_total_profit=None,
        partners=None,
        tiers=None,
        periods=None,
    )
