"""Phase 7 Gate P7.8B -- the layered financial fingerprints.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.4
(FP-1, FP-2) and P-4, and ``docs/architecture/P7_8_PRODUCT_INTEGRATION.md``.

The hierarchy under test::

    PROJECT source fingerprint       the existing P7.2 / P7.4 / P7.6 fingerprint,
            |                        UNCHANGED, and still the authority for the
            |                        Project variant cache and the Project matrix
            v
    STRUCTURED source fingerprint  = f(project fingerprint, the RESOLVED
                                       Capital Structure's economics)

Two rules make it safe:

- **FP-2, exactly.** An empty resolved structure is *the project fingerprint
  itself*, character for character -- not a hash of an empty payload. Neutral
  structured capital therefore adds no second identity anywhere.
- **FP-1, exactly.** Only economics enter. A position's name, a fee's
  description, the authored tuple order and the storage row order never do; its
  stable ``position_id`` does, because that is what ``POSITION(position_id)``
  addresses.

Editing a Capital Structure must never move a Project fingerprint: that is what
keeps a Project result, its cache and the Project Decision Matrix as current as
they were (P-4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from _p7_2_fixtures import create_deal, deal_fingerprint  # type: ignore[import-not-found]
from _p7_7_fixtures import fee, funding, unit_scope  # type: ignore[import-not-found]
from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain
from anchor.capital_structure.contracts import (
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    DebtTerms,
    FixedAmount,
    PctOfPrice,
    PositionClass,
    PositionScope,
    PreferredEquityTerms,
    ScopeKind,
    ShortfallResolution,
)
from anchor.deals import store
from anchor.deals.fingerprint import capital_structure_payload, fingerprint_structured_source
from anchor.deals.structured_variants import structured_variant_fingerprint
from anchor.deals.variants import variant_fingerprint

#: A project fingerprint is opaque to this layer: any stable token will do for
#: the pure oracles, and the database oracles use the real one.
PROJECT = "9" * 64
UNIT = "u1"
BASE = "base"


def debt_terms(**overrides: Any) -> DebtTerms:
    """Cash-pay mezzanine terms, as the executable P7.8 subset states them."""

    stated: dict[str, Any] = {
        "interest_rate": 0.12,
        "amortization": 25,
        "io_period": 1,
        "maturity_month": 48,
        "fees": (fee("mezz-fee", amount=15_000.0),),
        "current_pay_rate": 0.12,
        "pik_rate": 0.0,
    }
    stated.update(overrides)
    return DebtTerms(**stated)


def preferred_terms(**overrides: Any) -> PreferredEquityTerms:
    stated: dict[str, Any] = {
        "preferred_rate": 0.13,
        "current_pay_rate": 0.08,
        "accrual_permitted": True,
        "accrual_convention": AccrualConvention.ANNUAL_COMPOUND,
        "redemption_month": 60,
    }
    stated.update(overrides)
    return PreferredEquityTerms(**stated)


def mezz(**overrides: Any) -> CapitalPosition:
    stated: dict[str, Any] = {
        "position_id": "mezz-a",
        "name": "Mezzanine",
        "position_class": PositionClass.MEZZANINE_DEBT,
        "priority": 2,
        "scope": unit_scope(UNIT),
        "funding": (funding("mezz-f", rule=FixedAmount(amount=1_500_000.0)),),
        "terms": debt_terms(),
        "shortfall_resolution": ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
    }
    stated.update(overrides)
    return CapitalPosition(**stated)


def preferred(**overrides: Any) -> CapitalPosition:
    stated: dict[str, Any] = {
        "position_id": "pref-a",
        "name": "Preferred",
        "position_class": PositionClass.PREFERRED_EQUITY,
        "priority": 3,
        "scope": unit_scope(UNIT),
        "funding": (funding("pref-f", rule=PctOfPrice(pct=0.1)),),
        "terms": preferred_terms(),
        "shortfall_resolution": ShortfallResolution.UNRESOLVED,
    }
    stated.update(overrides)
    return CapitalPosition(**stated)


def structure(*positions: CapitalPosition) -> CapitalStructure:
    return CapitalStructure(positions=tuple(positions))


def digest(capital_structure: CapitalStructure, project: str = PROJECT) -> str:
    return fingerprint_structured_source(
        project_source_fingerprint=project, capital_structure=capital_structure
    )


BASE_STRUCTURE = structure(mezz(), preferred())
BASE_DIGEST = digest(BASE_STRUCTURE)


# =============================================================================
# 1. Empty adds nothing (FP-2)
# =============================================================================


def test_an_empty_structure_is_the_project_fingerprint_itself() -> None:
    """Not a hash of an empty payload: the same characters, so a Deal with no
    structured capital has one financial identity, not two."""

    assert digest(CapitalStructure(positions=())) == PROJECT


def test_a_non_empty_structure_has_its_own_fingerprint() -> None:
    assert BASE_DIGEST != PROJECT and len(BASE_DIGEST) == len(PROJECT)


# =============================================================================
# 2-4. Presentation never moves a fingerprint (FP-1)
# =============================================================================


def test_renaming_a_position_changes_nothing() -> None:
    assert digest(structure(mezz(name="Junior loan"), preferred())) == BASE_DIGEST


def test_renaming_a_fee_changes_nothing() -> None:
    renamed = mezz(
        terms=debt_terms(fees=(fee("mezz-fee", amount=15_000.0, description="Exit fee"),))
    )
    assert digest(structure(renamed, preferred())) == BASE_DIGEST


def test_reordering_the_authored_tuple_changes_nothing() -> None:
    assert digest(structure(preferred(), mezz())) == BASE_DIGEST


def test_an_event_id_is_not_economics_but_its_timing_and_amount_are() -> None:
    """A funding event's identity does not reach the digest; its month,
    sequence and amount do."""

    renamed = mezz(funding=(funding("renamed-f", rule=FixedAmount(amount=1_500_000.0)),))
    moved = mezz(funding=(funding("mezz-f", sequence=3, rule=FixedAmount(amount=1_500_000.0)),))
    assert digest(structure(renamed, preferred())) == BASE_DIGEST
    assert digest(structure(moved, preferred())) != BASE_DIGEST


# =============================================================================
# 5-10. Every economic field moves it
# =============================================================================


@pytest.mark.parametrize(
    ("label", "changed"),
    [
        ("priority", mezz(priority=5)),
        ("scope", mezz(scope=PositionScope(kind=ScopeKind.INVESTMENT, unit_id=None))),
        ("position id", mezz(position_id="mezz-b")),
        ("funding amount", mezz(funding=(funding("mezz-f", rule=FixedAmount(amount=1_500_001.0)),))),
        ("funding rule", mezz(funding=(funding("mezz-f", rule=PctOfPrice(pct=0.15)),))),
        ("interest rate", mezz(terms=debt_terms(interest_rate=0.125, current_pay_rate=0.125))),
        ("maturity", mezz(terms=debt_terms(maturity_month=60))),
        ("amortization", mezz(terms=debt_terms(amortization=30))),
        ("fee amount", mezz(terms=debt_terms(fees=(fee("mezz-fee", amount=15_001.0),)))),
        ("shortfall resolution", mezz(shortfall_resolution=ShortfallResolution.UNRESOLVED)),
    ],
)
def test_an_economic_change_moves_the_fingerprint(label: str, changed: CapitalPosition) -> None:
    assert digest(structure(changed, preferred())) != BASE_DIGEST, label


@pytest.mark.parametrize(
    ("label", "changed"),
    [
        ("preferred rate", preferred(terms=preferred_terms(preferred_rate=0.14))),
        ("current pay", preferred(terms=preferred_terms(current_pay_rate=0.09))),
        ("redemption", preferred(terms=preferred_terms(redemption_month=48))),
        (
            "accrual convention",
            preferred(terms=preferred_terms(accrual_convention=AccrualConvention.SIMPLE)),
        ),
        (
            "accrual permitted",
            preferred(
                terms=preferred_terms(
                    current_pay_rate=0.13, accrual_permitted=False, accrual_convention=None
                )
            ),
        ),
    ],
)
def test_a_preferred_term_change_moves_the_fingerprint(label: str, changed: CapitalPosition) -> None:
    assert digest(structure(mezz(), changed)) != BASE_DIGEST, label


def test_the_canonical_payload_carries_economics_and_no_presentation() -> None:
    (payload,) = capital_structure_payload(structure(mezz()))
    assert set(payload) == {
        "position_id", "position_class", "priority", "scope", "shortfall_resolution", "funding", "terms",
    }
    assert "name" not in payload
    assert set(payload["funding"][0]) == {"model_month", "sequence", "amount_rule"}
    assert set(payload["terms"]["fees"][0]) == {"amount", "model_month", "sequence"}


def test_the_payload_is_in_economic_order_whatever_the_tuple_order() -> None:
    forwards = capital_structure_payload(structure(mezz(), preferred()))
    backwards = capital_structure_payload(structure(preferred(), mezz()))
    assert forwards == backwards
    assert [entry["position_id"] for entry in forwards] == ["mezz-a", "pref-a"]


# =============================================================================
# 11-14. Base, Strategy and the Project fingerprint, over the real store
# =============================================================================


@pytest.fixture
def saved(tmp_path: Path) -> tuple[Path, str, str]:
    """A Deal with a Base Capital Structure, and its hidden Investment."""

    db = tmp_path / "anchor.db"
    deal = create_deal("quick", db)
    investment_id, _ = store.set_deal_capital_structure(
        deal.id,
        structure(mezz(scope=unit_scope(deal.id)), preferred(scope=unit_scope(deal.id))),
        db_path=db,
    )
    assert investment_id is not None
    return db, investment_id, deal.id


def structured(db: Path, investment_id: str, strategy_id: str = BASE) -> str:
    return structured_variant_fingerprint(
        investment_id, strategy_id, BASE, db_path=db
    ).structured_source_fingerprint


def project(db: Path, investment_id: str, strategy_id: str = BASE) -> str:
    return variant_fingerprint(investment_id, strategy_id, BASE, db_path=db).source_fingerprint


def test_the_project_fingerprint_is_the_deals_own_and_the_structure_never_reaches_it(
    saved: tuple[Path, str, str],
) -> None:
    db, investment_id, deal_id = saved
    deal = store.get_deal(deal_id, db_path=db)

    assert project(db, investment_id) == deal_fingerprint(deal)
    assert structured(db, investment_id) != deal_fingerprint(deal)


def test_a_strategy_that_inherits_shares_the_base_structured_fingerprint(
    saved: tuple[Path, str, str],
) -> None:
    db, investment_id, _ = saved
    inheriting = store.create_strategy(investment_id, name="Inherit", db_path=db)

    assert structured(db, investment_id, inheriting.strategy.strategy_id) == structured(
        db, investment_id
    )


def test_a_strategys_explicit_empty_structure_collapses_to_its_project_fingerprint(
    saved: tuple[Path, str, str],
) -> None:
    """Oracle 12: an explicit "no structured capital" Strategy has exactly its
    own Project identity -- the same collapse an absent structure gets."""

    db, investment_id, _ = saved
    explicit = store.create_strategy(
        investment_id,
        name="No structure",
        root_overlays=(
            InvestmentStrategyOverlay(
                domain=StrategyDomain.CAPITAL_STRUCTURE, content=CapitalStructure(positions=())
            ),
        ),
        db_path=db,
    )
    strategy_id = explicit.strategy.strategy_id

    assert structured(db, investment_id, strategy_id) == project(db, investment_id, strategy_id)


def test_removing_a_strategys_structure_reverts_exactly_to_the_base_fingerprint(
    saved: tuple[Path, str, str],
) -> None:
    """Oracle 11, and P-6: the Base structure was never changed, so removing the
    overlay restores the Base fingerprint character for character."""

    db, investment_id, deal_id = saved
    inheriting = structured(db, investment_id)
    record = store.create_strategy(
        investment_id,
        name="Own",
        root_overlays=(
            InvestmentStrategyOverlay(
                domain=StrategyDomain.CAPITAL_STRUCTURE,
                content=structure(mezz(scope=unit_scope(deal_id), priority=4)),
            ),
        ),
        db_path=db,
    )
    strategy_id = record.strategy.strategy_id
    assert structured(db, investment_id, strategy_id) != inheriting

    store.update_strategy(investment_id, strategy_id, name="Own", db_path=db)

    assert structured(db, investment_id, strategy_id) == inheriting


def test_a_base_edit_moves_only_the_strategies_that_inherit_it(
    saved: tuple[Path, str, str],
) -> None:
    """Oracles 13 and 14, and the P-4 guarantee in one: a Base Capital Structure
    edit moves the structured fingerprint of every Strategy that inherits it,
    leaves a Strategy with its own structure insulated, and moves no Project
    fingerprint at all."""

    db, investment_id, deal_id = saved
    inheriting = store.create_strategy(investment_id, name="Inherit", db_path=db)
    own = store.create_strategy(
        investment_id,
        name="Own",
        root_overlays=(
            InvestmentStrategyOverlay(
                domain=StrategyDomain.CAPITAL_STRUCTURE,
                content=structure(mezz(scope=unit_scope(deal_id), priority=4)),
            ),
        ),
        db_path=db,
    )
    inheriting_id = inheriting.strategy.strategy_id
    own_id = own.strategy.strategy_id
    before = {
        key: (structured(db, investment_id, key), project(db, investment_id, key))
        for key in (BASE, inheriting_id, own_id)
    }

    store.set_base_capital_structure(
        investment_id,
        structure(
            mezz(scope=unit_scope(deal_id), terms=debt_terms(interest_rate=0.14, current_pay_rate=0.14)),
        ),
        db_path=db,
    )

    after = {
        key: (structured(db, investment_id, key), project(db, investment_id, key))
        for key in (BASE, inheriting_id, own_id)
    }
    assert after[BASE][0] != before[BASE][0]
    assert after[inheriting_id][0] != before[inheriting_id][0]
    assert after[own_id][0] == before[own_id][0]
    assert [after[key][1] for key in after] == [before[key][1] for key in before]
