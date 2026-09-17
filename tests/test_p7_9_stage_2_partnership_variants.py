"""Phase 7 Gate P7.9 Stage 2 -- the Partnership variant service.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 2, 13, 16.2 and
17.2. The claims:

- **One route to the Common Equity Cash Flow.** A Partnership variant is
  ``analyze_structured_variant`` then the accepted Stage 1
  ``execute_partnership`` -- its result is bit-identical to calling the two
  directly -- for both analysis roots. With a mezzanine position the Common
  Equity series differs from the project's levered series, and the partner
  totals reconcile to the former (the Stage 2 seam oracle).
- **Unavailable is a result.** An unresolved Funding Requirement yields an
  ``UNAVAILABLE`` Partnership with the upstream reason and requirement ids, and
  no partner figure.
- **No Partnership, no result, no key.**
- **Refusals stay in their layer**, and a Partnership never changes an upstream
  analysis (P-4).
- **§17.3 fixture 2, the waterfall half** (``portfolio_property_debt_jv``):
  three property units with their own mortgages, the Section 15 terms over the
  consolidated Common Equity, against a frozen expected table and the
  exact-rational oracle.
"""

from __future__ import annotations

import dataclasses
import struct
from fractions import Fraction
from pathlib import Path

import pytest

import _p7_9_fixtures as f  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from _p7_9_rational_oracle import solve  # type: ignore[import-not-found]
from _p7_9_stage_2_fixtures import (  # type: ignore[import-not-found]
    capital_overlay,
    no_partnership_overlay,
    partnership_overlay,
    structured_deal,
    unresolved_structure,
)
from anchor.analysis.strategy import StrategyValidationError
from anchor.capital_structure import CapitalStructure
from anchor.capital_structure.contracts import CommonEquityUnavailableReason
from anchor.deals import partnership_variants as service
from anchor.deals import store
from anchor.deals.investment_variants import analyze_investment_variant
from anchor.deals.partnership_variants import (
    PartnershipSource,
    analyze_partnership_variant,
    partner_perspective,
    partner_perspectives,
    partnership_variant_fingerprint,
    resolve_variant_partnership,
)
from anchor.deals.structured_variants import StructuredRootKind, analyze_structured_variant
from anchor.deals.variants import analyze_variant
from anchor.partnership import (
    PartnerRole,
    PartnershipExecutionError,
    PartnershipStatus,
    PartnershipUnavailableReason,
    execute_partnership,
)

BASE = "base"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def _bits(values: tuple[float, ...] | None) -> list[bytes]:
    assert values is not None
    return [struct.pack("<d", value) for value in values]


def _asdict(value: object) -> object:
    return dataclasses.asdict(value)  # type: ignore[call-overload]


# =============================================================================
# One route, both roots
# =============================================================================


def test_a_hidden_deal_partnership_is_the_structured_variant_then_the_stage_1_engine(db: Path) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())

    analysis = analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)
    structured = analyze_structured_variant(investment_id, BASE, BASE, db_path=db)
    direct = execute_partnership(f.f1_terms(), structured.result)

    assert analysis.root_kind is StructuredRootKind.HIDDEN_UNIT
    assert analysis.partnership == f.f1_terms() and analysis.partnership_source is PartnershipSource.BASE
    assert analysis.result is not None and analysis.result.status is PartnershipStatus.COMPLETE
    assert _asdict(analysis.result) == _asdict(direct)
    assert analysis.structured_source_fingerprint == structured.structured_source_fingerprint
    assert analysis.project_source_fingerprint == structured.project_source_fingerprint
    assert analysis.hold_period == structured.hold_period
    assert analysis.unit_ids == structured.unit_ids


def test_the_seam_is_the_common_equity_series_never_the_levered_one(db: Path) -> None:
    """With the golden mezzanine loan the two series differ; the partners
    allocate the Common Equity one, period by period."""

    _, investment_id = structured_deal(db, f.f1_terms())

    analysis = analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)
    levered = analyze_variant(investment_id, BASE, BASE, db_path=db).results.levered_cash_flows  # type: ignore[union-attr]
    common_equity = analyze_structured_variant(investment_id, BASE, BASE, db_path=db).result.common_equity

    assert analysis.result is not None and analysis.result.partners is not None
    assert tuple(levered) != common_equity.cash_flows
    assert _bits(analysis.result.common_equity_cash_flows) == _bits(common_equity.cash_flows)
    assert analysis.result.common_equity_total_profit == common_equity.total_profit
    for t, flow in enumerate(common_equity.cash_flows or ()):
        contributed = sum(partner.contributions[t] for partner in analysis.result.partners)
        distributed = sum(partner.distributions[t] for partner in analysis.result.partners)
        assert abs(contributed - max(-flow, 0.0)) <= 1e-6 + 1e-12 * abs(flow)
        assert abs(distributed - max(flow, 0.0)) <= 1e-6 + 1e-12 * abs(flow)


def test_a_visible_investment_partnership_allocates_the_investment_residual(db: Path) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)
    store.set_base_partnership(investment.id, f.f12_terms(), db_path=db)

    analysis = analyze_partnership_variant(investment.id, BASE, BASE, db_path=db)
    structured = analyze_structured_variant(investment.id, BASE, BASE, db_path=db)
    consolidated = analyze_investment_variant(investment.id, BASE, BASE, db_path=db).consolidated_results

    assert analysis.root_kind is StructuredRootKind.VISIBLE_INVESTMENT
    assert analysis.unit_ids == tuple(sorted((first.id, second.id)))
    assert analysis.result is not None
    assert _asdict(analysis.result) == _asdict(execute_partnership(f.f12_terms(), structured.result))
    # No authored position: the residual is the consolidated levered series itself.
    assert _bits(analysis.result.common_equity_cash_flows) == _bits(tuple(consolidated.levered_cash_flows))


def test_an_unresolved_funding_requirement_is_an_unavailable_partnership_not_an_error(db: Path) -> None:
    deal, investment_id = structured_deal(db, f.f1_terms())
    starved = store.create_strategy(
        investment_id,
        name="Balloon",
        root_overlays=(capital_overlay(unresolved_structure(deal.id)),),
        db_path=db,
    )

    analysis = analyze_partnership_variant(investment_id, starved.strategy.strategy_id, BASE, db_path=db)
    structured = analyze_structured_variant(investment_id, starved.strategy.strategy_id, BASE, db_path=db)

    result = analysis.result
    assert result is not None
    assert result.status is PartnershipStatus.UNAVAILABLE
    assert result.unavailable_reason is PartnershipUnavailableReason.COMMON_EQUITY_UNAVAILABLE
    assert result.upstream_reason is CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
    unresolved = tuple(
        requirement.requirement_id
        for requirement in structured.result.funding_requirements
        if requirement.status.value == "unresolved"
    )
    assert result.upstream_requirement_ids == unresolved and unresolved
    assert (result.partners, result.tiers, result.periods, result.common_equity_cash_flows) == (None, None, None, None)
    assert result.common_equity_total_profit is None
    assert analysis.partnership_source_fingerprint is not None


# =============================================================================
# No Partnership, and the three resolution states
# =============================================================================


def test_no_partnership_is_no_result_and_no_key(db: Path) -> None:
    _, investment_id = structured_deal(db)

    analysis = analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)

    assert (analysis.partnership, analysis.result, analysis.partnership_source_fingerprint) == (None, None, None)
    assert analysis.partnership_source is PartnershipSource.BASE
    assert partner_perspectives(investment_id, db_path=db) == ()


def test_inherit_replace_and_explicit_none_resolve_differently(db: Path) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())
    inherit = store.create_strategy(investment_id, name="Inherit", db_path=db).strategy.strategy_id
    replace = store.create_strategy(
        investment_id, name="Replace", root_overlays=(partnership_overlay(f.f12_terms()),), db_path=db
    ).strategy.strategy_id
    none = store.create_strategy(
        investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db
    ).strategy.strategy_id

    resolved = {sid: resolve_variant_partnership(investment_id, sid, db_path=db) for sid in (BASE, inherit, replace, none)}

    assert (resolved[BASE].partnership, resolved[BASE].source) == (f.f1_terms(), PartnershipSource.BASE)
    assert (resolved[inherit].partnership, resolved[inherit].source) == (f.f1_terms(), PartnershipSource.BASE)
    assert (resolved[replace].partnership, resolved[replace].source) == (f.f12_terms(), PartnershipSource.STRATEGY)
    assert (resolved[none].partnership, resolved[none].source) == (None, PartnershipSource.STRATEGY)
    assert analyze_partnership_variant(investment_id, none, BASE, db_path=db).result is None
    replaced = analyze_partnership_variant(investment_id, replace, BASE, db_path=db).result
    assert replaced is not None and replaced.partners is not None
    assert {partner.partner_id for partner in replaced.partners} == {"lp", "g1", "g2"}

    # Removing the overlay restores Base exactly (P-6).
    store.update_strategy(investment_id, replace, name="Replace", db_path=db)
    assert resolve_variant_partnership(investment_id, replace, db_path=db).partnership == f.f1_terms()


def test_perspectives_are_the_union_with_where_each_partner_is_present(db: Path) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())
    inherit = store.create_strategy(investment_id, name="Inherit", db_path=db).strategy.strategy_id
    replace = store.create_strategy(
        investment_id,
        name="Replace",
        root_overlays=(partnership_overlay(dataclasses.replace(f.f12_terms())),),
        db_path=db,
    ).strategy.strategy_id
    store.create_strategy(investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db)

    perspectives = {p.partner_id: p for p in partner_perspectives(investment_id, db_path=db)}

    assert list(perspectives) == ["g1", "g2", "gp", "lp"]
    assert perspectives["gp"].present_in_base and perspectives["gp"].strategy_ids == (inherit,)
    assert perspectives["gp"].role is PartnerRole.GP and perspectives["gp"].name == "GP"
    assert perspectives["lp"].strategy_ids == tuple(sorted((inherit, replace)))
    assert not perspectives["g1"].present_in_base and perspectives["g1"].strategy_ids == (replace,)
    assert partner_perspective(investment_id, "g2", db_path=db) == perspectives["g2"]
    assert partner_perspective(investment_id, "nobody", db_path=db) is None


# =============================================================================
# Refusals stay in their layer, and nothing upstream moves
# =============================================================================


def test_a_project_refusal_propagates_unchanged(db: Path) -> None:
    from anchor.analysis.strategy import AcquisitionChoice, StrategyDomain, StrategyOverlay

    deal, investment_id = structured_deal(db, f.f1_terms())
    bad = store.create_strategy(
        investment_id,
        name="Bad bid",
        overlays=(
            StrategyOverlay(
                unit_id=deal.id,
                domain=StrategyDomain.ACQUISITION,
                content=AcquisitionChoice(purchase_price=-1.0, acquisition_cost_pct=0.02),
            ),
        ),
        db_path=db,
    )
    with pytest.raises(StrategyValidationError):
        analyze_partnership_variant(investment_id, bad.strategy.strategy_id, BASE, db_path=db)


def test_an_engine_execution_refusal_propagates(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from anchor.partnership import PartnershipExecutionIssue, PartnershipExecutionIssueCode

    _, investment_id = structured_deal(db, f.f11_terms())

    def refuse(partnership: object, structured: object) -> None:
        raise PartnershipExecutionError(
            (
                PartnershipExecutionIssue(
                    code=PartnershipExecutionIssueCode.NO_CONTRIBUTIONS_FOR_PRO_RATA_SPLIT,
                    message="No contributions to divide by.",
                    tier_id="residual",
                    period=1,
                ),
            )
        )

    monkeypatch.setattr(service, "execute_partnership", refuse)
    with pytest.raises(PartnershipExecutionError):
        analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)
    # The fingerprint executes nothing.
    assert partnership_variant_fingerprint(investment_id, BASE, BASE, db_path=db).partnership == f.f11_terms()


def test_an_unknown_strategy_or_scenario_is_not_found(db: Path) -> None:
    from anchor.deals.contracts import ScenarioNotFoundError, StrategyNotFoundError

    _, investment_id = structured_deal(db, f.f1_terms())
    with pytest.raises(StrategyNotFoundError):
        analyze_partnership_variant(investment_id, "zzz-missing", BASE, db_path=db)
    with pytest.raises(ScenarioNotFoundError):
        analyze_partnership_variant(investment_id, BASE, "zzz-missing", db_path=db)


def test_a_partnership_never_changes_an_upstream_analysis(db: Path) -> None:
    _, investment_id = structured_deal(db)
    before_structured = _asdict(analyze_structured_variant(investment_id, BASE, BASE, db_path=db))
    before_project = _asdict(analyze_variant(investment_id, BASE, BASE, db_path=db))

    store.set_base_partnership(investment_id, f.f1_terms(), db_path=db)
    analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)

    after_structured = _asdict(analyze_structured_variant(investment_id, BASE, BASE, db_path=db))
    after_project = _asdict(analyze_variant(investment_id, BASE, BASE, db_path=db))
    for before, after in ((before_structured, after_structured), (before_project, after_project)):
        assert isinstance(before, dict) and isinstance(after, dict)
        for operational in ("project_cache_status", "cache_status"):
            before.pop(operational, None)
            after.pop(operational, None)
        assert after == before


def test_a_structure_change_reaches_the_partnership_through_the_seam(db: Path) -> None:
    deal, investment_id = structured_deal(db, f.f1_terms())
    with_mezz = analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)

    store.set_deal_capital_structure(deal.id, CapitalStructure(positions=()), db_path=db)
    without = analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)
    levered = analyze_variant(investment_id, BASE, BASE, db_path=db).results.levered_cash_flows  # type: ignore[union-attr]

    assert with_mezz.result is not None and without.result is not None
    assert with_mezz.result.common_equity_cash_flows != without.result.common_equity_cash_flows
    assert _bits(without.result.common_equity_cash_flows) == _bits(tuple(levered))
    assert without.structured_source_fingerprint == without.project_source_fingerprint


# =============================================================================
# §17.3 fixture 2 -- portfolio_property_debt_jv, the waterfall half
# =============================================================================

#: The frozen expected table: the Section 15 terms over this portfolio's
#: consolidated Common Equity, stated from the exact-rational oracle (never the
#: float engine), to the cent.
_JV_TIERS_FINAL_YEAR = {
    "pref": 14_780_705.96,
    "catch_up": 1_329_320.45,
    "promote_1": 3_124_305.65,
    "promote_2": 1_705_433.03,
}
_JV_GP_PROMOTE = 1_318_177.40
_JV_GP_PROMOTE_BY_TIER = {"pref": 0.0, "catch_up": 664_660.22, "promote_1": 312_430.56, "promote_2": 341_086.61}


def _portfolio(db: Path) -> tuple[str, tuple[object, ...]]:
    deals = (
        quick_deal(db, name="Property A", purchase_price=10_000_000.0, current_noi=700_000.0, ltv=0.60),
        quick_deal(db, name="Property B", purchase_price=8_000_000.0, current_noi=560_000.0, ltv=0.65),
        quick_deal(db, name="Property C", purchase_price=12_000_000.0, current_noi=780_000.0, ltv=0.55),
    )
    investment = create_investment(db, *deals, name="Portfolio JV")
    store.set_base_partnership(investment.id, f.f1_terms(), db_path=db)
    return investment.id, deals


def test_portfolio_property_debt_jv_waterfall(db: Path) -> None:
    investment_id, deals = _portfolio(db)

    analysis = analyze_partnership_variant(investment_id, BASE, BASE, db_path=db)
    consolidated = analyze_investment_variant(investment_id, BASE, BASE, db_path=db).consolidated_results
    result = analysis.result

    # Three property units, each with its own acquisition mortgage.
    assert len(deals) == 3
    assert all(unit.results.loan_amount > 0 for unit in analyze_investment_variant(investment_id, BASE, BASE, db_path=db).unit_results)  # type: ignore[union-attr]
    assert result is not None and result.status is PartnershipStatus.COMPLETE
    assert result.tiers is not None and result.partners is not None
    assert _bits(result.common_equity_cash_flows) == _bits(tuple(consolidated.levered_cash_flows))

    # The frozen table, to the cent.
    final = {tier.tier_id: tier.amounts[-1] for tier in result.tiers}
    assert {key: round(value, 2) for key, value in final.items()} == _JV_TIERS_FINAL_YEAR
    gp = next(partner for partner in result.partners if partner.partner_id == "gp")
    lp = next(partner for partner in result.partners if partner.partner_id == "lp")
    assert gp.promote_earned is not None and round(gp.promote_earned, 2) == _JV_GP_PROMOTE
    assert gp.promote_attribution_by_tier is not None
    assert {item.tier_id: round(item.amount, 2) for item in gp.promote_attribution_by_tier} == _JV_GP_PROMOTE_BY_TIER
    assert lp.promote_earned is None  # LP is not a stated participant
    assert abs(sum(item.amount for item in gp.promote_attribution_by_tier) - gp.promote_earned) <= 1e-6

    # And the exact-rational oracle agrees with the engine throughout.
    oracle = solve(f.f1_terms(), result.common_equity_cash_flows or ())
    for tier in result.tiers:
        for engine, exact in zip(tier.amounts, oracle.tier_amounts[tier.tier_id], strict=True):
            assert abs(Fraction(engine) - exact) <= Fraction(1, 10**5)
    assert abs(Fraction(gp.promote_earned) - (oracle.partners["gp"].promote_earned or 0)) <= Fraction(1, 10**5)
    # Cash reaches the residual tier, so the LP's 12% hurdle (Section 8.1's
    # look-back) is met: its IRR is above 12%.
    assert lp.irr is not None and lp.irr > 0.12
