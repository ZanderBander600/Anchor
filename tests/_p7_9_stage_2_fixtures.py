"""P7.9 Stage 2 test fixtures (not a test module).

Builders shared by the Stage 2 persistence, fingerprint, variant, matrix and
route tests: every Stage 1 fixture Partnership (F1-F12 and the neutral cases),
the root-overlay shapes a Strategy states, a real hidden-Deal Investment with a
mezzanine position (so the Common Equity Cash Flow differs from the project's
levered series), and a Strategy whose Funding Requirement is unresolved.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import _p7_9_fixtures as f  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    cash_pay_debt,
    claim_position,
    golden_mezz,
    round_deal,
    structure,
)
from anchor.analysis.strategy import InvestmentStrategyOverlay, NoPartnership, StrategyDomain
from anchor.capital_structure import CapitalStructure, PositionClass, PositionScope, ScopeKind, ShortfallResolution
from anchor.deals import store
from anchor.partnership import Partner, Partnership, PartnerRole

BASE = "base"


def all_fixture_partnerships() -> tuple[tuple[str, Partnership], ...]:
    """Every Stage 1 fixture Partnership, by name -- together they state every
    typed union: explicit and pro-rata splits; partner, class and account
    subjects; SIMPLE (both orders), ANNUAL_COMPOUND and MOIC conditions; ALL
    and ANY; partner and class catch-up recipients; zero, one and two promote
    participants."""

    named = [(case.name, case.terms) for case in f.fixture_cases()]
    named.extend(
        [
            ("f2_simple", f.f2_terms(f.SIMPLE)),
            ("f3_capital_first", f.f3_terms(f.CAPITAL_FIRST)),
            ("f4_any", f.f4_terms(f.ANY)),
            ("f5_all_equity", f.f5_terms(f.ALL_EQUITY)),
            ("f11_no_participants", f.f11_terms()),
            ("f12_class_catch_up", f.f12_terms()),
            ("class_subject", class_subject_terms()),
        ]
    )
    unique: dict[str, Partnership] = {}
    for name, terms in named:
        unique.setdefault(name, terms)
    return tuple(unique.items())


def class_subject_terms() -> Partnership:
    """A hurdle on an investor class (the one subject kind no Stage 1 fixture
    states), with a MOIC condition beside a SIMPLE one under ``ANY``."""

    return f.partnership(
        (
            f.partner("lp", 0.9, investor_class="limited"),
            f.partner("gp", 0.1, role=PartnerRole.GP, investor_class="sponsor"),
        ),
        (
            f.hurdle(
                "pref",
                10,
                f.of_class("limited"),
                (f.simple("pref-8", 0.08, f.ACCRUED_FIRST), f.moic("moic-15", 1.5)),
                f.split(lp=0.9, gp=0.1),
                combinator=f.ANY,
            ),
            f.residual("residual", 20, f.split(lp=0.8, gp=0.2)),
        ),
        bench=f.BENCH_90_10,
        participants=("gp",),
    )


def partnership_overlay(partnership: Partnership) -> InvestmentStrategyOverlay:
    return InvestmentStrategyOverlay(domain=StrategyDomain.PARTNERSHIP, content=partnership)


def no_partnership_overlay() -> InvestmentStrategyOverlay:
    return InvestmentStrategyOverlay(domain=StrategyDomain.PARTNERSHIP, content=NoPartnership())


def capital_overlay(capital_structure: CapitalStructure) -> InvestmentStrategyOverlay:
    return InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=capital_structure)


def unit_scope(unit_id: str) -> PositionScope:
    return PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id)


def mezz_structure(deal_id: str) -> CapitalStructure:
    """The P7.8 golden mezzanine loan, scoped to ``deal_id``."""

    return structure(dataclasses.replace(golden_mezz(), scope=unit_scope(deal_id)))


def unresolved_structure(deal_id: str) -> CapitalStructure:
    """A mezzanine balloon in hold year 2 that the levered cash cannot pay, left
    unresolved: the Common Equity Cash Flow is then unavailable."""

    return structure(
        claim_position(
            "mezz",
            position_class=PositionClass.MEZZANINE_DEBT,
            priority=2,
            terms=cash_pay_debt(rate=0.12, amortization=30, io_period=2, maturity_month=24),
            resolution=ShortfallResolution.UNRESOLVED,
            amount=1_500_000.0,
            scope=unit_scope(deal_id),
        )
    )


def structured_deal(db: Path, partnership: Partnership | None = None) -> tuple[Any, str]:
    """A real Quick Deal with the golden mezzanine loan (materializing its hidden
    Investment) and, when given, a Base Partnership. Returns the Deal and the
    Investment id."""

    deal = round_deal(db, name="Structured")
    investment_id, _ = store.set_deal_capital_structure(deal.id, mezz_structure(deal.id), db_path=db)
    assert investment_id is not None
    if partnership is not None:
        store.set_base_partnership(investment_id, partnership, db_path=db)
    return deal, investment_id


def with_partner(partnership: Partnership, partner_id: str, **changes: Any) -> Partnership:
    """``partnership`` with one partner's fields replaced."""

    return dataclasses.replace(
        partnership,
        partners=tuple(
            dataclasses.replace(partner, **changes) if partner.partner_id == partner_id else partner
            for partner in partnership.partners
        ),
    )


def renamed(partnership: Partnership, suffix: str = " (renamed)") -> Partnership:
    """``partnership`` with every partner and tier renamed -- presentation only."""

    return dataclasses.replace(
        partnership,
        partners=tuple(dataclasses.replace(p, name=p.name + suffix) for p in partnership.partners),
        tiers=tuple(dataclasses.replace(t, name=t.name + suffix) for t in partnership.tiers),
    )


def gp_as_lp(partnership: Partnership) -> Partnership:
    """``partnership`` with its ``gp`` partner described as an LP: the same
    investor (P-8: the ``partner_id`` is the identity) under a different
    reporting-only role."""

    return with_partner(partnership, "gp", role=PartnerRole.LP)


__all__ = [
    "BASE",
    "Partner",
    "all_fixture_partnerships",
    "capital_overlay",
    "gp_as_lp",
    "mezz_structure",
    "no_partnership_overlay",
    "partnership_overlay",
    "renamed",
    "structured_deal",
    "unit_scope",
    "unresolved_structure",
    "with_partner",
]
