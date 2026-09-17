"""Phase 7 Gate P7.9 Stage 2 -- the ``PARTNERSHIP`` Investment-root Strategy
domain.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 17.2 and
``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 7.4
(ST-2, P-4, P-6). The claims:

- ``PARTNERSHIP`` joins ``INVESTMENT_STRATEGY_DOMAINS`` without another
  representation, and is refused on a Unit overlay;
- its content is the Stage 1 ``Partnership`` or the explicit ``NoPartnership``,
  judged by the Stage 1 validator, whose findings are wrapped unchanged;
- resolution is whole-domain replacement with three distinct states --
  inherit, replace, explicitly none -- and removing the overlay restores Base;
- the Project pathway never sees it: resolved inputs, validity and the Project
  fingerprint are identical with and without a Partnership overlay.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import _p7_9_fixtures as f  # type: ignore[import-not-found]
from _p7_2_fixtures import create_deal  # type: ignore[import-not-found]
from _p7_9_stage_2_fixtures import (  # type: ignore[import-not-found]
    no_partnership_overlay,
    partnership_overlay,
)
from anchor.analysis.strategy import (
    INVESTMENT_STRATEGY_DOMAINS,
    UNIT_STRATEGY_DOMAINS,
    InvestmentStrategyOverlay,
    NoPartnership,
    StrategyDefinition,
    StrategyDomain,
    StrategyIssueCode,
    StrategyOverlay,
    resolve_partnership,
    strategy_partnership,
    validate_investment_strategy,
    validate_strategy,
)
from anchor.capital_structure import CapitalStructure
from anchor.contracts import OperatingMode
from anchor.deals import store
from anchor.deals.variants import inspect_variant_inputs, variant_fingerprint
from anchor.partnership import PartnershipIssueCode

UNIT = "u1"


def strategy(*root_overlays: InvestmentStrategyOverlay, overlays: tuple[StrategyOverlay, ...] = ()) -> StrategyDefinition:
    return StrategyDefinition(strategy_id="s1", name="S", overlays=overlays, root_overlays=root_overlays)


def issues(definition: StrategyDefinition):  # type: ignore[no-untyped-def]
    return validate_strategy(definition, operating_mode=OperatingMode.QUICK, unit_id=UNIT)


def test_partnership_is_the_second_investment_root_domain() -> None:
    assert INVESTMENT_STRATEGY_DOMAINS == (StrategyDomain.CAPITAL_STRUCTURE, StrategyDomain.PARTNERSHIP)
    assert StrategyDomain.PARTNERSHIP not in UNIT_STRATEGY_DOMAINS
    assert StrategyDomain.PARTNERSHIP.value == "partnership"
    assert list(StrategyDomain)[-1] is StrategyDomain.PARTNERSHIP


@pytest.mark.parametrize("content", [f.f1_terms(), f.f11_terms(), NoPartnership()])
def test_a_partnership_or_an_explicit_none_is_a_valid_root_overlay(content: object) -> None:
    definition = strategy(InvestmentStrategyOverlay(domain=StrategyDomain.PARTNERSHIP, content=content))  # type: ignore[arg-type]

    assert issues(definition) == ()
    assert validate_investment_strategy(definition, unit_modes={UNIT: OperatingMode.QUICK, "u2": OperatingMode.DETAILED}) == ()


def test_a_partnership_on_a_unit_overlay_is_a_root_domain_in_the_wrong_place() -> None:
    definition = strategy(
        overlays=(StrategyOverlay(unit_id=UNIT, domain=StrategyDomain.PARTNERSHIP, content=f.f1_terms()),)  # type: ignore[arg-type]
    )

    (issue,) = issues(definition)
    assert issue.code is StrategyIssueCode.ROOT_DOMAIN_ON_UNIT
    assert issue.domain is StrategyDomain.PARTNERSHIP and issue.unit_id == UNIT


@pytest.mark.parametrize("content", [CapitalStructure(positions=()), None, "partnership", {}])
def test_partnership_content_must_be_a_partnership_or_no_partnership(content: object) -> None:
    (issue,) = issues(strategy(InvestmentStrategyOverlay(domain=StrategyDomain.PARTNERSHIP, content=content)))  # type: ignore[arg-type]

    assert issue.code is StrategyIssueCode.INVALID_CONTENT
    assert issue.domain is StrategyDomain.PARTNERSHIP


def test_a_capital_structure_overlay_still_refuses_partnership_content() -> None:
    (issue,) = issues(strategy(InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=f.f1_terms())))

    assert issue.code is StrategyIssueCode.INVALID_CONTENT
    assert issue.domain is StrategyDomain.CAPITAL_STRUCTURE


def test_two_partnership_overlays_are_a_duplicate_domain() -> None:
    (issue,) = issues(strategy(partnership_overlay(f.f1_terms()), no_partnership_overlay()))

    assert issue.code is StrategyIssueCode.DUPLICATE_DOMAIN
    assert issue.domain is StrategyDomain.PARTNERSHIP


def test_the_stage_1_findings_are_wrapped_unchanged_and_located() -> None:
    invalid = dataclasses.replace(
        f.f1_terms(),
        promote_participant_ids=("ghost",),
        tiers=(dataclasses.replace(f.f1_terms().tiers[0], split=None),) + f.f1_terms().tiers[1:],
    )
    from anchor.partnership import validate_partnership

    stage_1 = validate_partnership(invalid)
    found = issues(strategy(partnership_overlay(invalid)))

    assert [issue.code for issue in found] == [StrategyIssueCode.INVALID_PARTNERSHIP] * len(stage_1)
    assert [issue.source_code for issue in found] == [issue.code.value for issue in stage_1]
    assert [issue.message for issue in found] == [f"partnership: {issue.message}" for issue in stage_1]
    assert {issue.source_code for issue in found} >= {
        PartnershipIssueCode.UNKNOWN_PROMOTE_PARTICIPANT.value,
        PartnershipIssueCode.MISSING_SPLIT.value,
    }
    fields = {issue.source_code: issue.field for issue in found}
    assert fields[PartnershipIssueCode.MISSING_SPLIT.value] == "partnership.tiers[pref].split"
    assert fields[PartnershipIssueCode.UNKNOWN_PROMOTE_PARTICIPANT.value] == (
        "partnership.partners[ghost].promote_participant_ids"
    )
    assert all(issue.domain is StrategyDomain.PARTNERSHIP for issue in found)


# =============================================================================
# Resolution: whole replacement, three states
# =============================================================================


def test_the_three_states_are_three_answers() -> None:
    assert strategy_partnership(None) is None
    assert strategy_partnership(strategy()) is None
    assert strategy_partnership(strategy(no_partnership_overlay())) == NoPartnership()
    assert strategy_partnership(strategy(partnership_overlay(f.f7_terms()))) == f.f7_terms()


@pytest.mark.parametrize("base", [None, f.f1_terms()])
def test_resolution_replaces_whole_and_never_merges(base: object) -> None:
    assert resolve_partnership(base, None) == base  # type: ignore[arg-type]
    assert resolve_partnership(base, strategy()) == base  # type: ignore[arg-type]
    assert resolve_partnership(base, strategy(no_partnership_overlay())) is None  # type: ignore[arg-type]
    replaced = resolve_partnership(base, strategy(partnership_overlay(f.f12_terms())))  # type: ignore[arg-type]
    assert replaced == f.f12_terms()
    assert not {partner.partner_id for partner in replaced.partners} & ({"gp"} if base else set())


def test_removing_the_overlay_restores_base_exactly() -> None:
    with_overlay = strategy(partnership_overlay(f.f12_terms()))
    without = dataclasses.replace(with_overlay, root_overlays=())

    base = f.f1_terms()
    assert resolve_partnership(base, with_overlay) == f.f12_terms()
    assert resolve_partnership(base, without) is base


def test_a_capital_structure_overlay_does_not_state_a_partnership() -> None:
    definition = strategy(InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=CapitalStructure(positions=())))

    assert strategy_partnership(definition) is None
    assert resolve_partnership(f.f1_terms(), definition) == f.f1_terms()


def test_the_base_must_be_a_partnership() -> None:
    with pytest.raises(TypeError):
        resolve_partnership(NoPartnership(), None)  # type: ignore[arg-type]


# =============================================================================
# The Project pathway never sees it (P-4)
# =============================================================================


@pytest.mark.parametrize("mode", ["quick", "detailed", "lease_level"])
def test_a_partnership_overlay_changes_no_project_input_or_fingerprint(tmp_path: Path, mode: str) -> None:
    db = tmp_path / "anchor.db"
    deal = create_deal(mode, db)
    investment_id = store.create_scenario_for_deal(deal.id, name="S", db_path=db).investment_id
    store.set_base_partnership(investment_id, f.f1_terms(), db_path=db)
    plain = store.create_strategy(investment_id, name="Plain", db_path=db)
    own = store.create_strategy(
        investment_id, name="Own", root_overlays=(partnership_overlay(f.f12_terms()),), db_path=db
    )
    none = store.create_strategy(
        investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db
    )

    base_inputs = inspect_variant_inputs(investment_id, plain.strategy.strategy_id, "base", db_path=db)
    for record in (own, none):
        inputs = inspect_variant_inputs(investment_id, record.strategy.strategy_id, "base", db_path=db)
        assert inputs.resolved == base_inputs.resolved
        assert inputs.source_fingerprint == base_inputs.source_fingerprint
        assert (
            variant_fingerprint(investment_id, record.strategy.strategy_id, "base", db_path=db).source_fingerprint
            == base_inputs.source_fingerprint
        )
    assert base_inputs.source_fingerprint == variant_fingerprint(investment_id, "base", "base", db_path=db).source_fingerprint
