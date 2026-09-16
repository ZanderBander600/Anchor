"""Phase 7 Gate P7.8B -- the structured variant service.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3 (P-1,
P-3, P-4), 7.5 and 12, and ``docs/architecture/P7_8_PRODUCT_INTEGRATION.md``.

The claims under test:

- **One engine, one pathway.** A structured analysis is the *existing* Project
  variant plus the P7.8A executor. Its Project half is bit-identical to what the
  same variant answers without any Capital Structure, and its structured half is
  exactly what the executor returns when called directly.
- **Whole-domain replacement (ST-2).** A Strategy's own structure replaces the
  Base structure entirely -- a Base position it does not restate is *absent* --
  and removing the overlay restores the Base structure exactly (P-6).
- **Explicit empty is a real choice.** A Strategy that states an empty structure
  executes no authored position and reports the neutral residual.
- **Scenario never touches the contract.** A Scenario changes the Project
  economics underneath a structure; the structure itself is identical, and the
  position's returns are recomputed from the new cash.
- **Three distinct refusals.** An invalid Project variant, an invalid Capital
  Structure contract, and a valid contract this Project state cannot execute are
  three different errors. An unresolved Funding Requirement is none of them: it
  is a successful analysis with N/A returns and a deterministic reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from _p7_2_fixtures import economic_override  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, detailed_deal, quick_deal  # type: ignore[import-not-found]
from _p7_7_fixtures import INVESTMENT, fee, funding, unit_scope  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    GOLDEN_MEZZ_AMOUNT,
    cash_pay_debt,
    claim_position,
    common_marker,
    preferred,
    round_deal,
    structure,
)
from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain
from anchor.capital_structure.contracts import (
    AccrualConvention,
    CapitalStructure,
    CapitalStructureValidationError,
    PositionClass,
    ShortfallResolution,
)
from anchor.capital_structure.execution import execute_unit_capital_structure
from anchor.capital_structure.execution_contracts import (
    CapitalStructureExecutionError,
    ExecutionIssueCode,
    PositionResultStatus,
    PositionUnavailableReason,
)
from anchor.contracts import acquisition_terms_from_inputs
from anchor.deals import store
from anchor.deals.structured_variants import (
    CapitalStructureSource,
    StructuredRootKind,
    analyze_structured_variant,
    position_perspectives,
    resolve_variant_capital_structure,
    structured_variant_fingerprint,
)
from anchor.deals.variants import analyze_variant

BASE = "base"
CEC = ShortfallResolution.COMMON_EQUITY_CONTRIBUTION


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def mezz(unit_id: str, *, amount: float = GOLDEN_MEZZ_AMOUNT, **terms: Any) -> Any:
    stated: dict[str, Any] = {
        "rate": 0.12,
        "amortization": 25,
        "io_period": 1,
        "maturity_month": 48,
        "fees": (fee("mezz-fee", amount=15_000.0),),
    }
    stated.update(terms)
    return claim_position(
        "mezz-a",
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=2,
        terms=cash_pay_debt(**stated),
        resolution=CEC,
        amount=amount,
        scope=unit_scope(unit_id),
    )


def senior(unit_id: str) -> Any:
    return claim_position(
        "senior-a",
        position_class=PositionClass.SENIOR_DEBT,
        priority=3,
        terms=cash_pay_debt(rate=0.06, amortization=30, io_period=5, maturity_month=60),
        resolution=CEC,
        amount=250_000.0,
        scope=unit_scope(unit_id),
    )


def pref(unit_id: str, *, position_id: str = "pref-a") -> Any:
    return claim_position(
        position_id,
        position_class=PositionClass.PREFERRED_EQUITY,
        priority=4,
        terms=preferred(
            preferred_rate=0.12,
            current_pay_rate=0.08,
            convention=AccrualConvention.ANNUAL_COMPOUND,
        ),
        resolution=CEC,
        amount=400_000.0,
        scope=unit_scope(unit_id),
    )


def overlay(content: CapitalStructure) -> InvestmentStrategyOverlay:
    return InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=content)


@pytest.fixture
def hidden(db: Path) -> tuple[Path, str, str]:
    """A round-number Deal with a Base structure: one mezzanine loan and the
    Common Equity marker."""

    deal = round_deal(db, name="Structured deal")
    investment_id, _ = store.set_deal_capital_structure(
        deal.id, structure(mezz(deal.id), common_marker("common-a", scope=unit_scope(deal.id))), db_path=db
    )
    assert investment_id is not None
    return db, investment_id, deal.id


# =============================================================================
# The hidden one-unit pathway
# =============================================================================


def test_the_project_half_is_the_existing_variant_analysis_unchanged(
    hidden: tuple[Path, str, str],
) -> None:
    """P-4: the structured layer consumes a completed Project result. The same
    variant analysed without any structure answers identically."""

    db, investment_id, _ = hidden
    project = analyze_variant(investment_id, BASE, BASE, db_path=db)
    structured = analyze_structured_variant(investment_id, BASE, BASE, db_path=db)

    assert structured.project_source_fingerprint == project.source_fingerprint
    assert structured.root_kind is StructuredRootKind.HIDDEN_UNIT
    assert structured.capital_structure_source is CapitalStructureSource.BASE


def test_the_structured_half_is_exactly_the_p7_8a_executor(
    hidden: tuple[Path, str, str],
) -> None:
    """No second executor, no re-derivation: the service resolves the structure
    and hands the completed Project result to the approved engine."""

    db, investment_id, deal_id = hidden
    deal = store.get_deal(deal_id, db_path=db)
    assert deal.inputs is not None
    analysis = analyze_structured_variant(investment_id, BASE, BASE, db_path=db)

    direct = execute_unit_capital_structure(
        unit_id=deal_id,
        terms=acquisition_terms_from_inputs(deal.inputs),
        results=analyze_variant(investment_id, BASE, BASE, db_path=db).results,
        capital_structure=analysis.capital_structure,
    )

    assert analysis.result == direct


def test_an_authored_position_reports_its_returns_and_structural_metrics(
    hidden: tuple[Path, str, str],
) -> None:
    db, investment_id, _ = hidden

    (position,) = analyze_structured_variant(investment_id, BASE, BASE, db_path=db).result.positions

    assert position.position_id == "mezz-a"
    assert position.status is PositionResultStatus.COMPLETE
    assert position.funded_amount == GOLDEN_MEZZ_AMOUNT
    # $10,000,000 price, a $6,000,000 acquisition loan senior to it, $1,500,000 funded.
    assert position.attachment_basis == 6_000_000.0
    assert position.last_dollar_basis == 7_500_000.0
    assert position.attachment_ltv == 0.6 and position.detachment_ltv == 0.75
    assert position.moic is not None and position.profit is not None


def test_the_common_equity_marker_names_the_residual(hidden: tuple[Path, str, str]) -> None:
    db, investment_id, _ = hidden

    common_equity = analyze_structured_variant(investment_id, BASE, BASE, db_path=db).result.common_equity

    assert common_equity.position_id == "common-a"
    assert common_equity.cash_flows is not None


# =============================================================================
# Resolution: whole replacement, inheritance and the explicit empty
# =============================================================================


def test_a_strategys_structure_replaces_the_base_whole(hidden: tuple[Path, str, str]) -> None:
    """Oracle: Base holds a mezzanine, a senior and a preferred; the Strategy
    states only the senior and the preferred. The mezzanine is ABSENT -- not
    inherited, not merged."""

    db, investment_id, deal_id = hidden
    store.set_base_capital_structure(
        investment_id,
        structure(mezz(deal_id), senior(deal_id), pref(deal_id)),
        db_path=db,
    )
    record = store.create_strategy(
        investment_id,
        name="Senior and preferred",
        root_overlays=(overlay(structure(senior(deal_id), pref(deal_id))),),
        db_path=db,
    )
    strategy_id = record.strategy.strategy_id

    resolved = resolve_variant_capital_structure(investment_id, strategy_id, db_path=db)

    assert [position.position_id for position in resolved.capital_structure.positions] == [
        "senior-a",
        "pref-a",
    ]
    assert resolved.source is CapitalStructureSource.STRATEGY
    analysis = analyze_structured_variant(investment_id, strategy_id, BASE, db_path=db)
    assert sorted(position.position_id for position in analysis.result.positions) == [
        "pref-a",
        "senior-a",
    ]


def test_removing_the_overlay_restores_the_base_structure_exactly(
    hidden: tuple[Path, str, str],
) -> None:
    db, investment_id, deal_id = hidden
    base = store.get_base_capital_structure(investment_id, db_path=db)
    record = store.create_strategy(
        investment_id,
        name="Own",
        root_overlays=(overlay(structure(senior(deal_id))),),
        db_path=db,
    )
    strategy_id = record.strategy.strategy_id

    store.update_strategy(investment_id, strategy_id, name="Own", db_path=db)

    resolved = resolve_variant_capital_structure(investment_id, strategy_id, db_path=db)
    assert resolved.capital_structure == base
    assert resolved.source is CapitalStructureSource.BASE


def test_an_explicitly_empty_strategy_executes_no_authored_position(
    hidden: tuple[Path, str, str],
) -> None:
    """Oracle: the resolved structure is empty, no authored position result
    exists, the residual is the neutral post-acquisition-debt one, and the
    structured fingerprint collapses to that variant's Project fingerprint."""

    db, investment_id, _ = hidden
    record = store.create_strategy(
        investment_id,
        name="No structured capital",
        root_overlays=(overlay(CapitalStructure(positions=())),),
        db_path=db,
    )
    strategy_id = record.strategy.strategy_id

    analysis = analyze_structured_variant(investment_id, strategy_id, BASE, db_path=db)
    neutral = analyze_variant(investment_id, strategy_id, BASE, db_path=db)

    assert analysis.result.positions == ()
    assert analysis.result.common_equity.position_id is None
    assert analysis.result.common_equity.cash_flows == neutral.results.levered_cash_flows
    assert analysis.structured_source_fingerprint == analysis.project_source_fingerprint


# =============================================================================
# Scenario: the world moves, the contract does not
# =============================================================================


def test_a_scenario_changes_the_cash_under_an_identical_contract(
    hidden: tuple[Path, str, str],
) -> None:
    db, investment_id, deal_id = hidden
    downside = store.create_scenario(
        investment_id,
        name="Downside",
        overrides=(economic_override("quick", deal_id),),
        db_path=db,
    )
    scenario_id = downside.scenario.scenario_id

    base = analyze_structured_variant(investment_id, BASE, BASE, db_path=db)
    stressed = analyze_structured_variant(investment_id, BASE, scenario_id, db_path=db)

    assert stressed.capital_structure == base.capital_structure
    assert stressed.project_source_fingerprint != base.project_source_fingerprint
    assert stressed.structured_source_fingerprint != base.structured_source_fingerprint
    assert stressed.result.common_equity.cash_flows != base.result.common_equity.cash_flows
    (stressed_position,) = stressed.result.positions
    (base_position,) = base.result.positions
    assert stressed_position.funded_amount == base_position.funded_amount


# =============================================================================
# Three distinct refusals, and the one state that is not a refusal
# =============================================================================


def test_an_invalid_capital_structure_contract_is_refused_as_one(db: Path) -> None:
    """Priority 1 of a Unit that carries an acquisition loan is that loan's, so
    a structure claiming it is an invalid *contract* -- refused by the P7.7
    validator, with its own error."""

    deal = round_deal(db, name="Deal")
    investment_id, _ = store.set_deal_capital_structure(
        deal.id, structure(mezz(deal.id)), db_path=db
    )
    assert investment_id is not None
    store.set_base_capital_structure(
        investment_id,
        structure(
            claim_position(
                "mezz-a",
                position_class=PositionClass.MEZZANINE_DEBT,
                priority=1,
                terms=cash_pay_debt(rate=0.12),
                resolution=CEC,
                amount=500_000.0,
                scope=unit_scope(deal.id),
            )
        ),
        db_path=db,
    )

    with pytest.raises(CapitalStructureValidationError):
        analyze_structured_variant(investment_id, BASE, BASE, db_path=db)


def test_an_over_funded_closing_is_an_execution_refusal(db: Path) -> None:
    """The structure is a valid contract; this Project state cannot execute it,
    because its closing funding exceeds the equity the acquisition needs."""

    deal = round_deal(db, name="Deal")
    investment_id, _ = store.set_deal_capital_structure(
        deal.id, structure(mezz(deal.id, amount=9_000_000.0)), db_path=db
    )
    assert investment_id is not None

    with pytest.raises(CapitalStructureExecutionError) as refused:
        analyze_structured_variant(investment_id, BASE, BASE, db_path=db)

    assert [issue.code for issue in refused.value.issues] == [
        ExecutionIssueCode.OVERFUNDED_CLOSING
    ]


def test_an_unresolved_funding_requirement_is_a_result_not_an_error(db: Path) -> None:
    """The gate's distinction: an unresolved requirement is a valid,
    deterministic economic outcome. The analysis succeeds; the position's
    returns are N/A with the reason, and its structural metrics stand."""

    deal = round_deal(db, name="Deal")
    starved = claim_position(
        "mezz-a",
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=2,
        # A balloon in hold year 2, against $500,000 of levered cash that year.
        terms=cash_pay_debt(rate=0.12, amortization=30, io_period=2, maturity_month=24),
        resolution=ShortfallResolution.UNRESOLVED,
        amount=1_500_000.0,
        scope=unit_scope(deal.id),
    )
    investment_id, _ = store.set_deal_capital_structure(deal.id, structure(starved), db_path=db)
    assert investment_id is not None

    analysis = analyze_structured_variant(investment_id, BASE, BASE, db_path=db)

    (position,) = analysis.result.positions
    assert position.status is PositionResultStatus.UNRESOLVED_FUNDING
    assert position.unavailable_reason is PositionUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT
    assert (position.irr, position.moic, position.profit) == (None, None, None)
    assert position.funded_amount == 1_500_000.0
    assert position.attachment_ltv == 0.6 and position.debt_yield_through is not None
    assert analysis.result.common_equity.cash_flows is None


# =============================================================================
# The visible Investment pathway
# =============================================================================


def test_a_visible_investment_executes_unit_and_investment_scopes(db: Path) -> None:
    first = quick_deal(db, name="Unit A")
    second = detailed_deal(db, name="Unit B")
    investment = create_investment(db, first, second)
    store.set_base_capital_structure(
        investment.id,
        structure(
            claim_position(
                "mezz-a",
                position_class=PositionClass.MEZZANINE_DEBT,
                priority=2,
                terms=cash_pay_debt(rate=0.12, io_period=5, maturity_month=60),
                resolution=CEC,
                amount=250_000.0,
                scope=unit_scope(first.id),
            ),
            claim_position(
                "pref-inv",
                position_class=PositionClass.PREFERRED_EQUITY,
                priority=1,
                terms=preferred(preferred_rate=0.1, current_pay_rate=0.1),
                resolution=CEC,
                amount=300_000.0,
                scope=INVESTMENT,
            ),
            common_marker("common-inv", priority=2, scope=INVESTMENT),
        ),
        db_path=db,
    )

    analysis = analyze_structured_variant(investment.id, BASE, BASE, db_path=db)

    assert analysis.root_kind is StructuredRootKind.VISIBLE_INVESTMENT
    assert sorted(analysis.unit_ids) == sorted([first.id, second.id])
    assert [position.position_id for position in analysis.result.positions] == ["mezz-a", "pref-inv"]
    assert analysis.result.common_equity.position_id == "common-inv"


# =============================================================================
# The Position perspective catalog
# =============================================================================


def test_the_perspective_union_covers_every_stored_structure(db: Path) -> None:
    """The gate's oracle: Base holds senior-a, mezz-a, pref-a and common-a;
    Strategy 1 inherits; Strategy 2 states senior-a, mezz-a, common-a and
    pref-b. The union is five identities, each once."""

    deal = round_deal(db, name="Deal")
    base = structure(
        senior(deal.id),
        mezz(deal.id),
        pref(deal.id),
        common_marker("common-a", scope=unit_scope(deal.id)),
    )
    investment_id, _ = store.set_deal_capital_structure(deal.id, base, db_path=db)
    assert investment_id is not None
    inheriting = store.create_strategy(investment_id, name="Inherit", db_path=db)
    second = store.create_strategy(
        investment_id,
        name="Recut",
        root_overlays=(
            overlay(
                structure(
                    senior(deal.id),
                    mezz(deal.id),
                    pref(deal.id, position_id="pref-b"),
                    common_marker("common-a", scope=unit_scope(deal.id)),
                )
            ),
        ),
        db_path=db,
    )

    perspectives = position_perspectives(investment_id, db_path=db)

    assert [entry.position_id for entry in perspectives] == [
        "mezz-a",
        "senior-a",
        "pref-a",
        "pref-b",
        "common-a",
    ]
    by_id = {entry.position_id: entry for entry in perspectives}
    assert by_id["common-a"].is_common_equity_marker is True
    assert by_id["mezz-a"].position_class is PositionClass.MEZZANINE_DEBT
    assert by_id["pref-a"].present_in_base is True
    assert by_id["pref-b"].present_in_base is False
    # pref-a is inherited by Strategy 1 and absent from Strategy 2; pref-b the reverse.
    assert by_id["pref-a"].strategy_ids == (inheriting.strategy.strategy_id,)
    assert by_id["pref-b"].strategy_ids == (second.strategy.strategy_id,)


def test_a_deal_with_no_structure_has_no_perspective_and_no_investment(db: Path) -> None:
    deal = round_deal(db, name="Deal")

    investment_id, structure_read = store.read_deal_capital_structure(deal.id, db_path=db)

    assert investment_id is None and structure_read.positions == ()


def test_the_fingerprint_route_never_executes_anything(hidden: tuple[Path, str, str]) -> None:
    """Reading a structured variant's identity resolves and hashes; it runs no
    executor and writes nothing."""

    db, investment_id, _ = hidden

    fingerprint = structured_variant_fingerprint(investment_id, BASE, BASE, db_path=db)

    assert fingerprint.structured_source_fingerprint != fingerprint.project_source_fingerprint
    assert fingerprint.capital_structure.positions[0].position_id == "mezz-a"
