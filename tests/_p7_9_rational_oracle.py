"""P7.9 Stage 1 -- the exact-rational oracle.

An independent restatement of ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md``
Sections 6 to 11 in ``fractions.Fraction``. It reads only the contract
*shapes* and never imports an engine module of ``anchor.partnership``: every
account, capacity, catch-up, allocation and attribution rule is written again
here, from the document, in exact arithmetic.

Floats enter through their shortest decimal spelling (``Fraction(repr(x))``),
so ``0.9`` is exactly nine tenths and a hand fixture stays a hand fixture.
Exact arithmetic needs no remainder partner and no tolerance, except that the
catch-up domain keeps the document's ``P > 0`` test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from anchor.capital_structure.contracts import AccrualConvention
from anchor.partnership.contracts import (
    CatchUpRecipientKind,
    ExplicitSplit,
    HurdleCombinator,
    HurdleSubjectKind,
    MoicHurdle,
    Partnership,
    SimpleDistributionOrder,
    TierKind,
)

Q = Fraction
ZERO = Fraction(0)


class OracleRefusal(Exception):
    """The oracle's own statement of a deterministic refusal."""


def q(value: float) -> Fraction:
    return Fraction(repr(float(value)))


@dataclass
class Account:
    kind: str
    rate: Fraction
    multiple: Fraction
    order: SimpleDistributionOrder | None
    balance: Fraction = ZERO
    capital: Fraction = ZERO
    accrued: Fraction = ZERO
    contributed: Fraction = ZERO
    distributed: Fraction = ZERO
    history: list[Fraction] = field(default_factory=list)

    def accrue(self) -> None:
        if self.kind == "compound":
            self.balance = self.balance * (1 + self.rate)
        elif self.kind == "simple":
            self.accrued += self.rate * max(ZERO, self.capital)
            self.balance = self.capital + self.accrued

    def contribute(self, amount: Fraction) -> None:
        self.contributed += amount
        if self.kind == "compound":
            self.balance += amount
        elif self.kind == "simple":
            self.capital += amount
            self.balance = self.capital + self.accrued
        else:
            self.balance = self.multiple * self.contributed - self.distributed

    def distribute(self, amount: Fraction) -> None:
        self.distributed += amount
        if self.kind == "compound":
            self.balance -= amount
        elif self.kind == "simple":
            if self.order is SimpleDistributionOrder.ACCRUED_RETURN_FIRST:
                on_accrued = min(amount, self.accrued)
                self.accrued -= on_accrued
                self.capital -= amount - on_accrued
            else:
                on_capital = min(amount, max(ZERO, self.capital))
                self.capital -= on_capital
                on_accrued = min(amount - on_capital, self.accrued)
                self.accrued -= on_accrued
                self.capital -= amount - on_capital - on_accrued
            self.balance = self.capital + self.accrued
        else:
            self.balance = self.multiple * self.contributed - self.distributed


@dataclass
class OraclePartner:
    contributions: list[Fraction]
    distributions: list[Fraction]
    benchmark: list[Fraction]
    total_contributions: Fraction = ZERO
    total_distributions: Fraction = ZERO
    total_benchmark: Fraction = ZERO
    capital_returned: Fraction = ZERO
    profit_distributions: Fraction = ZERO
    benchmark_capital_returned: Fraction = ZERO
    benchmark_profit_distributions: Fraction = ZERO
    distribution_difference: Fraction = ZERO
    capital_return_difference: Fraction = ZERO
    profit_distribution_difference: Fraction = ZERO
    promote_earned: Fraction | None = None
    benchmark_capital_subordination: Fraction = ZERO
    distributions_by_tier: dict[str, Fraction] = field(default_factory=dict)
    capital_difference_by_tier: dict[str, Fraction] = field(default_factory=dict)
    profit_difference_by_tier: dict[str, Fraction] = field(default_factory=dict)
    promote_attribution_by_tier: dict[str, Fraction] | None = None


@dataclass
class OracleResult:
    tier_amounts: dict[str, list[Fraction]]
    partners: dict[str, OraclePartner]
    balances: dict[tuple[str, str], list[Fraction]]
    common_equity_total_profit: Fraction


def _members(terms: Partnership, kind: object, partner_id: str | None, investor_class: str | None) -> list[str]:
    if kind in (HurdleSubjectKind.PARTNER, CatchUpRecipientKind.PARTNER):
        return [p.partner_id for p in terms.partners if p.partner_id == partner_id]
    if kind in (HurdleSubjectKind.INVESTOR_CLASS, CatchUpRecipientKind.INVESTOR_CLASS):
        return [p.partner_id for p in terms.partners if p.investor_class == investor_class]
    return [p.partner_id for p in terms.partners]


def solve(terms: Partnership, cash_flows: tuple[float, ...]) -> OracleResult:
    ids = sorted(p.partner_id for p in terms.partners)
    commit = {p.partner_id: q(p.commitment_share) for p in terms.partners}
    bench = {row.partner_id: q(row.share) for row in terms.promote_benchmark.shares}
    tiers = sorted(terms.tiers, key=lambda tier: tier.sequence)
    flows = [q(value) for value in cash_flows]
    n = len(flows)

    accounts: dict[tuple[str, str], Account] = {}
    subjects: dict[str, list[str]] = {}
    for tier in tiers:
        if tier.kind is TierKind.HURDLE:
            assert tier.hurdle is not None
            subject = tier.hurdle.hurdle_subject
            subjects[tier.tier_id] = _members(terms, subject.kind, subject.partner_id, subject.investor_class)
            for condition in tier.hurdle.conditions:
                if isinstance(condition, MoicHurdle):
                    account = Account("moic", ZERO, q(condition.multiple), None)
                elif condition.accrual_convention is AccrualConvention.ANNUAL_COMPOUND:
                    account = Account("compound", q(condition.rate), ZERO, None)
                else:
                    account = Account("simple", q(condition.rate), ZERO, condition.simple_distribution_order)
                accounts[(tier.tier_id, condition.condition_id)] = account

    contributions = {p: [ZERO] * n for p in ids}
    entries: dict[str, list[tuple[int, int, str, Fraction]]] = {p: [] for p in ids}
    bench_entries: dict[str, list[tuple[int, int, str, Fraction]]] = {p: [] for p in ids}
    amounts = {tier.tier_id: [ZERO] * n for tier in tiers}

    def cumulative(p: str) -> Fraction:
        return sum(contributions[p], ZERO)

    def distributed(p: str) -> Fraction:
        return sum((entry[3] for entry in entries[p]), ZERO)

    def post(amounts_by_partner: dict[str, Fraction], contribution: bool) -> None:
        for (tier_id, _), account in accounts.items():
            flow = sum((amounts_by_partner[p] for p in subjects[tier_id]), ZERO)
            if contribution:
                account.contribute(flow)
            else:
                account.distribute(flow)

    for t, cash in enumerate(flows):
        if t >= 1:
            for account in accounts.values():
                account.accrue()
        if cash < 0:
            called = {p: commit[p] * -cash for p in ids}
            for p in ids:
                contributions[p][t] = called[p]
            post(called, True)
        remaining = max(ZERO, cash)
        for tier in tiers:
            if remaining == 0:
                break

            def shares_now() -> dict[str, Fraction]:
                if isinstance(tier.split, ExplicitSplit):
                    return {row.partner_id: q(row.share) for row in tier.split.shares}
                total = sum((cumulative(p) for p in ids), ZERO)
                if total == 0:
                    raise OracleRefusal("no_contributions_for_pro_rata_split")
                return {p: cumulative(p) / total for p in ids}

            if tier.kind is TierKind.HURDLE:
                assert tier.hurdle is not None
                capacities = []
                for condition in tier.hurdle.conditions:
                    balance = accounts[(tier.tier_id, condition.condition_id)].balance
                    if balance <= 0:
                        capacities.append(ZERO)
                    else:
                        sigma = sum((shares_now()[p] for p in subjects[tier.tier_id]), ZERO)
                        capacities.append(balance / sigma)
                capacity = max(capacities) if tier.hurdle.combinator is HurdleCombinator.ALL else min(capacities)
            elif tier.kind is TierKind.CATCH_UP:
                assert tier.catch_up is not None
                recipient = tier.catch_up.recipient
                members = _members(terms, recipient.kind, recipient.partner_id, recipient.investor_class)
                shares = shares_now()
                rate = sum((shares[p] for p in members), ZERO)
                target = q(tier.catch_up.target_profit_share)
                profit = sum((distributed(p) - cumulative(p) for p in ids), ZERO)
                recipient_profit = sum((distributed(p) - cumulative(p) for p in members), ZERO)
                capacity = ZERO if profit <= 0 else max(ZERO, (target * profit - recipient_profit) / (rate - target))
            else:
                capacity = remaining
            paid = min(remaining, capacity)
            if paid > 0:
                shares = shares_now()
                given = {p: shares[p] * paid for p in ids}
                for p in ids:
                    entries[p].append((t, tier.sequence, tier.tier_id, given[p]))
                    bench_entries[p].append((t, tier.sequence, tier.tier_id, bench[p] * paid))
                post(given, False)
                amounts[tier.tier_id][t] += paid
                remaining -= paid
        for account in accounts.values():
            account.history.append(account.balance)

    partners: dict[str, OraclePartner] = {}
    participants = set(terms.promote_participant_ids)
    for p in ids:
        dist = [sum((e[3] for e in entries[p] if e[0] == t), ZERO) for t in range(n)]
        benchmark_series = [bench[p] * max(ZERO, cash) for cash in flows]
        record = OraclePartner(contributions=contributions[p], distributions=dist, benchmark=benchmark_series)
        record.total_contributions = sum(contributions[p], ZERO)
        record.total_distributions = sum(dist, ZERO)
        record.total_benchmark = sum(benchmark_series, ZERO)
        record.capital_returned = min(record.total_distributions, record.total_contributions)
        record.profit_distributions = record.total_distributions - record.capital_returned
        record.benchmark_capital_returned = min(record.total_benchmark, record.total_contributions)
        record.benchmark_profit_distributions = record.total_benchmark - record.benchmark_capital_returned
        record.distribution_difference = record.total_distributions - record.total_benchmark
        record.capital_return_difference = record.capital_returned - record.benchmark_capital_returned
        record.profit_distribution_difference = record.profit_distributions - record.benchmark_profit_distributions
        record.benchmark_capital_subordination = max(ZERO, -record.capital_return_difference)

        def split_by_tier(rows: list[tuple[int, int, str, Fraction]], capital: Fraction) -> dict[str, tuple[Fraction, Fraction]]:
            out: dict[str, tuple[Fraction, Fraction]] = {}
            left = capital
            for _, _, tier_id, amount in sorted(rows, key=lambda row: (row[0], row[1])):
                as_capital = min(amount, left)
                left -= as_capital
                held = out.get(tier_id, (ZERO, ZERO))
                out[tier_id] = (held[0] + as_capital, held[1] + amount - as_capital)
            return out

        actual = split_by_tier(entries[p], record.capital_returned)
        benchmark_split = split_by_tier(bench_entries[p], record.benchmark_capital_returned)
        for tier in tiers:
            a = actual.get(tier.tier_id, (ZERO, ZERO))
            b = benchmark_split.get(tier.tier_id, (ZERO, ZERO))
            record.distributions_by_tier[tier.tier_id] = sum((e[3] for e in entries[p] if e[2] == tier.tier_id), ZERO)
            record.capital_difference_by_tier[tier.tier_id] = a[0] - b[0]
            record.profit_difference_by_tier[tier.tier_id] = a[1] - b[1]
        if p in participants:
            record.promote_earned = max(ZERO, record.profit_distribution_difference)
            record.promote_attribution_by_tier = (
                dict(record.profit_difference_by_tier)
                if record.promote_earned > 0
                else {tier.tier_id: ZERO for tier in tiers}
            )
        partners[p] = record

    positive = sum((cash for cash in flows if cash > 0), ZERO)
    negative = sum((cash for cash in flows if cash < 0), ZERO)
    return OracleResult(
        tier_amounts=amounts,
        partners=partners,
        balances={key: account.history for key, account in accounts.items()},
        common_equity_total_profit=positive - abs(negative),
    )
