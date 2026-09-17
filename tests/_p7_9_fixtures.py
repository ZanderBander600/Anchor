"""P7.9 Stage 1 -- Partnership builders and the ratified hand fixtures.

Every fixture restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md``
Sections 15 and 16.1 (F1-F12). Builders state every economic field explicitly;
nothing here supplies a default the contract does not have.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from anchor.capital_structure.contracts import AccrualConvention
from anchor.partnership import (
    BenchmarkShare,
    CashFlowCadence,
    CatchUpRecipient,
    CatchUpRecipientKind,
    CatchUpTerms,
    CommonEquityCashFlowInput,
    ContributionRule,
    EconomicAccount,
    ExplicitSplit,
    HurdleCombinator,
    HurdleSubject,
    HurdleSubjectKind,
    HurdleTerms,
    IrrHurdle,
    MoicHurdle,
    Partner,
    PartnerRole,
    Partnership,
    PartnershipResult,
    ProRataByContribution,
    PromoteBenchmark,
    SimpleDistributionOrder,
    SplitShare,
    TierKind,
    WaterfallTier,
    allocate_partnership,
)

COMPOUND = AccrualConvention.ANNUAL_COMPOUND
SIMPLE = AccrualConvention.SIMPLE
ACCRUED_FIRST = SimpleDistributionOrder.ACCRUED_RETURN_FIRST
CAPITAL_FIRST = SimpleDistributionOrder.CAPITAL_FIRST
ALL = HurdleCombinator.ALL
ANY = HurdleCombinator.ANY
PRO_RATA = ProRataByContribution()

#: Hand-fixture tolerance: the ratified figures are exact decimals; the float
#: engine must agree to well within a cent.
TOL = 1e-6


# =============================================================================
# Builders
# =============================================================================


def partner(partner_id: str, share: float, *, role: PartnerRole = PartnerRole.LP, investor_class: str | None = None) -> Partner:
    return Partner(partner_id=partner_id, name=partner_id.upper(), role=role, investor_class=investor_class, commitment_share=share)


def split(**shares: float) -> ExplicitSplit:
    return ExplicitSplit(shares=tuple(SplitShare(partner_id=key, share=value) for key, value in shares.items()))


def benchmark(**shares: float) -> PromoteBenchmark:
    return PromoteBenchmark(shares=tuple(BenchmarkShare(partner_id=key, share=value) for key, value in shares.items()))


def of_partner(partner_id: str) -> HurdleSubject:
    return HurdleSubject(kind=HurdleSubjectKind.PARTNER, partner_id=partner_id, investor_class=None, account=None)


def of_class(investor_class: str) -> HurdleSubject:
    return HurdleSubject(kind=HurdleSubjectKind.INVESTOR_CLASS, partner_id=None, investor_class=investor_class, account=None)


ALL_EQUITY = HurdleSubject(
    kind=HurdleSubjectKind.ECONOMIC_ACCOUNT, partner_id=None, investor_class=None, account=EconomicAccount.ALL_COMMON_EQUITY
)


def compound(condition_id: str, rate: float) -> IrrHurdle:
    return IrrHurdle(condition_id=condition_id, rate=rate, accrual_convention=COMPOUND, simple_distribution_order=None)


def simple(condition_id: str, rate: float, order: SimpleDistributionOrder) -> IrrHurdle:
    return IrrHurdle(condition_id=condition_id, rate=rate, accrual_convention=SIMPLE, simple_distribution_order=order)


def moic(condition_id: str, multiple: float) -> MoicHurdle:
    return MoicHurdle(condition_id=condition_id, multiple=multiple)


def hurdle(tier_id: str, sequence: int, subject: HurdleSubject, conditions: Iterable[Any], tier_split: Any, *, combinator: HurdleCombinator = ALL) -> WaterfallTier:
    return WaterfallTier(
        tier_id=tier_id,
        name=tier_id.replace("_", " ").title(),
        sequence=sequence,
        kind=TierKind.HURDLE,
        split=tier_split,
        hurdle=HurdleTerms(hurdle_subject=subject, conditions=tuple(conditions), combinator=combinator),
        catch_up=None,
    )


def to_partner(partner_id: str) -> CatchUpRecipient:
    return CatchUpRecipient(kind=CatchUpRecipientKind.PARTNER, partner_id=partner_id, investor_class=None)


def to_class(investor_class: str) -> CatchUpRecipient:
    return CatchUpRecipient(kind=CatchUpRecipientKind.INVESTOR_CLASS, partner_id=None, investor_class=investor_class)


def catch_up(tier_id: str, sequence: int, recipient: CatchUpRecipient, target: float, tier_split: Any) -> WaterfallTier:
    return WaterfallTier(
        tier_id=tier_id,
        name=tier_id.replace("_", " ").title(),
        sequence=sequence,
        kind=TierKind.CATCH_UP,
        split=tier_split,
        hurdle=None,
        catch_up=CatchUpTerms(recipient=recipient, target_profit_share=target),
    )


def residual(tier_id: str, sequence: int, tier_split: Any) -> WaterfallTier:
    return WaterfallTier(
        tier_id=tier_id, name=tier_id.replace("_", " ").title(), sequence=sequence, kind=TierKind.RESIDUAL,
        split=tier_split, hurdle=None, catch_up=None,
    )


def partnership(
    partners: Iterable[Partner],
    tiers: Iterable[WaterfallTier],
    *,
    bench: PromoteBenchmark,
    participants: tuple[str, ...],
    rule: ContributionRule = ContributionRule.PRO_RATA_BY_COMMITMENT,
) -> Partnership:
    return Partnership(
        partners=tuple(partners),
        contribution_rule=rule,
        promote_benchmark=bench,
        promote_participant_ids=participants,
        tiers=tuple(tiers),
    )


def series(*cash_flows: float) -> CommonEquityCashFlowInput:
    return CommonEquityCashFlowInput(cadence=CashFlowCadence.ANNUAL, cash_flows=tuple(float(value) for value in cash_flows))


def run(terms: Partnership, *cash_flows: float) -> PartnershipResult:
    return allocate_partnership(terms, series(*cash_flows))


def by_partner(result: PartnershipResult) -> dict[str, Any]:
    assert result.partners is not None
    return {item.partner_id: item for item in result.partners}


def by_tier(result: PartnershipResult) -> dict[str, Any]:
    assert result.tiers is not None
    return {item.tier_id: item for item in result.tiers}


def tier_values(amounts: Iterable[Any]) -> dict[str, float]:
    return {item.tier_id: item.amount for item in amounts}


def close(actual: float | None, expected: float, tol: float = TOL) -> bool:
    return actual is not None and abs(actual - expected) <= tol


def all_close(actual: Iterable[float], expected: Iterable[float], tol: float = TOL) -> bool:
    left, right = tuple(actual), tuple(expected)
    return len(left) == len(right) and all(abs(a - b) <= tol for a, b in zip(left, right))


def dict_close(actual: Mapping[str, float], expected: Mapping[str, float], tol: float = TOL) -> bool:
    return set(actual) == set(expected) and all(abs(actual[key] - expected[key]) <= tol for key in expected)


# =============================================================================
# The ratified fixtures
# =============================================================================

LP_GP = (partner("lp", 0.9), partner("gp", 0.1, role=PartnerRole.GP))
BENCH_90_10 = benchmark(lp=0.9, gp=0.1)


def f1_terms(*, participants: tuple[str, ...] = ("gp",)) -> Partnership:
    """Section 15: 8% compound pref, 60% GP catch-up to 20%, 80/20 to a 12% LP
    IRR, 70/30 residual."""

    return partnership(
        LP_GP,
        (
            hurdle("pref", 10, of_partner("lp"), (compound("pref-8", 0.08),), split(lp=0.9, gp=0.1)),
            catch_up("catch_up", 20, to_partner("gp"), 0.2, split(lp=0.4, gp=0.6)),
            hurdle("promote_1", 30, of_partner("lp"), (compound("irr-12", 0.12),), split(lp=0.8, gp=0.2)),
            residual("promote_2", 40, split(lp=0.7, gp=0.3)),
        ),
        bench=BENCH_90_10,
        participants=participants,
    )


F1_SERIES = (-1_000_000.0, -100_000.0, 60_000.0, 1_900_000.0)


def f1_series(t3: float = 1_900_000.0) -> tuple[float, ...]:
    return (-1_000_000.0, -100_000.0, 60_000.0, t3)


def f2_terms(convention: AccrualConvention) -> Partnership:
    condition = compound("pref-8", 0.08) if convention is COMPOUND else simple("pref-8", 0.08, ACCRUED_FIRST)
    return partnership(
        LP_GP,
        (hurdle("pref", 10, of_partner("lp"), (condition,), split(lp=0.9, gp=0.1)), residual("residual", 20, split(lp=0.8, gp=0.2))),
        bench=BENCH_90_10,
        participants=("gp",),
    )


F2_SERIES = (-1_000_000.0, 0.0, 1_300_000.0)


def f3_terms(order: SimpleDistributionOrder) -> Partnership:
    return partnership(
        LP_GP,
        (hurdle("pref", 10, of_partner("lp"), (simple("pref-8", 0.08, order),), split(lp=0.9, gp=0.1)), residual("residual", 20, split(lp=0.8, gp=0.2))),
        bench=BENCH_90_10,
        participants=("gp",),
    )


F3_SERIES = (-1_000_000.0, 50_000.0, 0.0, 1_300_000.0)


def f4_terms(combinator: HurdleCombinator) -> Partnership:
    return partnership(
        LP_GP,
        (
            hurdle("greater_lesser", 10, of_partner("lp"), (compound("irr-10", 0.10), moic("moic-15", 1.5)), split(lp=0.9, gp=0.1), combinator=combinator),
            residual("residual", 20, split(lp=0.8, gp=0.2)),
        ),
        bench=BENCH_90_10,
        participants=("gp",),
    )


F4_SERIES = (-1_000_000.0, 0.0, 2_000_000.0)


def f5_terms(subject: HurdleSubject | None = None, *, with_catch_up: bool = False) -> Partnership:
    """Downside subordination: return of capital to the LP first."""

    tiers = [hurdle("roc", 10, of_partner("lp") if subject is None else subject, (moic("roc-1", 1.0),), split(lp=1.0, gp=0.0))]
    if with_catch_up:
        tiers.append(catch_up("catch_up", 20, to_partner("gp"), 0.2, split(lp=0.0, gp=1.0)))
    tiers.append(residual("residual", 30, split(lp=0.8, gp=0.2)))
    return partnership(LP_GP, tiers, bench=BENCH_90_10, participants=("gp",))


F5_SERIES = (-1_000_000.0, 0.0, 950_000.0)
F6_SERIES = (-1_000_000.0, 0.0, 1_500_000.0)


def f7_terms() -> Partnership:
    """Commitment 90/10, benchmark 95/5, a single pro-rata-by-contribution residual."""

    return partnership(LP_GP, (residual("residual", 10, PRO_RATA),), bench=benchmark(lp=0.95, gp=0.05), participants=("gp",))


def f8_terms() -> Partnership:
    """A promote-only sponsor with a zero commitment."""

    return partnership(
        (partner("lp", 1.0), partner("sp", 0.0, role=PartnerRole.GP)),
        (
            hurdle("pref", 10, of_partner("lp"), (compound("pref-8", 0.08),), split(lp=1.0, sp=0.0)),
            catch_up("catch_up", 20, to_partner("sp"), 0.2, split(lp=0.0, sp=1.0)),
            residual("residual", 30, split(lp=0.8, sp=0.2)),
        ),
        bench=benchmark(lp=1.0, sp=0.0),
        participants=("sp",),
    )


F8_SERIES = (-1_000_000.0, 0.0, 1_500_000.0)
F9_SERIES = F5_SERIES


def f10_terms(*, pro_rata: bool) -> Partnership:
    tier_split = PRO_RATA if pro_rata else split(lp=0.9, gp=0.1)
    return partnership(
        LP_GP,
        (hurdle("pref", 10, of_partner("lp"), (compound("pref-8", 0.08),), tier_split), residual("residual", 20, tier_split)),
        bench=BENCH_90_10,
        participants=("gp",),
    )


F10_SERIES = (-1_000_000.0, -50_000.0, 30_000.0, 1_400_000.0)


def f11_terms(*, pro_rata: bool = True) -> Partnership:
    return partnership(
        LP_GP, (residual("residual", 10, PRO_RATA if pro_rata else split(lp=0.9, gp=0.1)),), bench=BENCH_90_10, participants=()
    )


def f12_terms() -> Partnership:
    """A catch-up to an investor class of two sponsors."""

    return partnership(
        (partner("lp", 0.9), partner("g1", 0.05, role=PartnerRole.GP, investor_class="sponsor"), partner("g2", 0.05, role=PartnerRole.GP, investor_class="sponsor")),
        (
            hurdle("pref", 10, of_partner("lp"), (compound("pref-8", 0.08),), split(lp=0.9, g1=0.05, g2=0.05)),
            catch_up("catch_up", 20, to_class("sponsor"), 0.2, split(lp=0.0, g1=0.5, g2=0.5)),
            residual("residual", 30, split(lp=0.8, g1=0.1, g2=0.1)),
        ),
        bench=benchmark(lp=0.9, g1=0.05, g2=0.05),
        participants=("g1", "g2"),
    )


F12_SERIES = (-1_000_000.0, 0.0, 1_500_000.0)


def pari_passu(*, bench: PromoteBenchmark = BENCH_90_10, participants: tuple[str, ...] = ("gp",), tier_split: Any = None) -> Partnership:
    return partnership(
        LP_GP, (residual("residual", 10, split(lp=0.9, gp=0.1) if tier_split is None else tier_split),), bench=bench, participants=participants
    )


def single_partner() -> Partnership:
    """One partner holding everything, no promote participant: neutral."""

    return partnership(
        (partner("only", 1.0),),
        (residual("residual", 10, split(only=1.0)),),
        bench=benchmark(only=1.0),
        participants=(),
    )


@dataclass(frozen=True)
class Case:
    """A named partnership and series for the conservation and oracle sweeps."""

    name: str
    terms: Partnership
    cash_flows: tuple[float, ...]


def fixture_cases() -> tuple[Case, ...]:
    return (
        Case("F1", f1_terms(), F1_SERIES),
        Case("F1-partial", f1_terms(), f1_series(1_340_000.0)),
        Case("F1-pref-not-met", f1_terms(), f1_series(1_100_000.0)),
        Case("F2-simple", f2_terms(SIMPLE), F2_SERIES),
        Case("F2-compound", f2_terms(COMPOUND), F2_SERIES),
        Case("F3-accrued-first", f3_terms(ACCRUED_FIRST), F3_SERIES),
        Case("F3-capital-first", f3_terms(CAPITAL_FIRST), F3_SERIES),
        Case("F4-all", f4_terms(ALL), F4_SERIES),
        Case("F4-any", f4_terms(ANY), F4_SERIES),
        Case("F5", f5_terms(), F5_SERIES),
        Case("F6-lp", f5_terms(), F6_SERIES),
        Case("F6-all-equity", f5_terms(ALL_EQUITY), F6_SERIES),
        Case("F7-loss", f7_terms(), (-1_000_000.0, 0.0, 800_000.0)),
        Case("F7-gain", f7_terms(), (-1_000_000.0, 0.0, 1_500_000.0)),
        Case("F8", f8_terms(), F8_SERIES),
        Case("F9", f5_terms(with_catch_up=True), F9_SERIES),
        Case("F10-pro-rata", f10_terms(pro_rata=True), F10_SERIES),
        Case("F10-explicit", f10_terms(pro_rata=False), F10_SERIES),
        Case("F11-late-call", f11_terms(), (0.0, 0.0, -1_000.0, 2_000.0)),
        Case("F12", f12_terms(), F12_SERIES),
        Case("pari-passu", pari_passu(), (-1_000_000.0, 100_000.0, 1_200_000.0)),
        Case("surplus-then-call", f1_terms(), (-1_000_000.0, 1_500_000.0, -400_000.0, 900_000.0)),
    )
