"""Phase 7 Gate P7.2 -- the resolved-input financial fingerprint.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.4 and
Q15: **fingerprint the resolved inputs, not the recipe.** A persisted
Scenario's variant fingerprint is the existing unit fingerprint function
applied to the contracts P7.1 resolution produces, so for every mode:

1. a neutral Scenario fingerprints exactly as today's Deal;
2. two recipes that resolve to the same inputs share a fingerprint;
3. / 4. a rename or a new description changes nothing;
5. override insertion order changes nothing;
6. an economic change moves it;
7. an exact semantic revert restores it exactly.

Plus: the Business Plan enters exactly as D6.5 defines, the Investment and
Scenario ids never enter, a base edit moves every dependent variant, and an
independent hand-resolved oracle agrees.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from anchor.analysis.scenario import ScenarioIssueStage, ScenarioValidationError
from anchor.business_plan import BusinessPlan
from anchor.contracts import OperatingMode
from anchor.deals import store, variants
from anchor.deals.fingerprint import (
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from _p7_2_fixtures import (  # type: ignore[import-not-found]
    MODES,
    create_deal,
    deal_fingerprint,
    economic_override,
    override,
    second_override,
    update_deal,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "p7_2.db"


def _fingerprint(record: store.InvestmentScenario, db: Path) -> str:  # type: ignore[name-defined]
    return variants.scenario_variant_fingerprint(
        record.investment_id, record.scenario.scenario_id, db_path=db
    ).source_fingerprint


# =============================================================================
# 1. Neutral == today's Deal
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("with_plan", [False, True], ids=["empty-plan", "material-plan"])
def test_a_neutral_scenario_fingerprints_exactly_as_the_deal(db: Path, mode: str, with_plan: bool) -> None:
    plan = fx.business_plan() if with_plan else BusinessPlan()
    deal = create_deal(mode, db, business_plan=plan)
    record = store.create_scenario_for_deal(deal.id, name="Neutral", db_path=db)

    reported = variants.scenario_variant_fingerprint(record.investment_id, record.scenario.scenario_id, db_path=db)

    assert reported.source_fingerprint == deal_fingerprint(deal)
    assert (reported.investment_id, reported.unit_id, reported.operating_mode) == (
        record.investment_id, deal.id, OperatingMode(mode),
    )


@pytest.mark.parametrize("mode", MODES)
def test_no_op_recipes_resolve_to_the_base_and_fingerprint_as_the_deal(db: Path, mode: str) -> None:
    """``ADD 0``, ``SCALE 1`` and a ``CAP_AT`` above the current value are all
    recipes; none changes an input, so none changes the fingerprint."""

    deal = create_deal(mode, db)
    recipes = [
        (override(deal.id, "interest_rate", "add", 0.0),),
        (override(deal.id, "exit_cap_rate", "scale", 1.0),),
        (override(deal.id, "ltv", "cap_at", 0.95),),
    ]
    for overrides in recipes:
        record = store.create_scenario_for_deal(deal.id, name="No-op", overrides=overrides, db_path=db)
        assert _fingerprint(record, db) == deal_fingerprint(deal), overrides


# =============================================================================
# 2. Equivalent recipes share a fingerprint
# =============================================================================


def _base_exit_cap(mode: str) -> float:
    return fx.quick_inputs().exit_cap_rate if mode == "quick" else (
        fx.detailed_terms() if mode == "detailed" else fx.lease_level_terms()
    ).exit_cap_rate


@pytest.mark.parametrize("mode", MODES)
def test_two_different_recipes_that_resolve_identically_share_a_fingerprint(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    base = _base_exit_cap(mode)
    added = store.create_scenario_for_deal(
        deal.id, name="Add", overrides=(override(deal.id, "exit_cap_rate", "add", 0.005),), db_path=db
    )
    set_to = store.create_scenario_for_deal(
        deal.id, name="Set", overrides=(override(deal.id, "exit_cap_rate", "set", base + 0.005),), db_path=db
    )

    assert _fingerprint(added, db) == _fingerprint(set_to, db) != deal_fingerprint(deal)


def test_the_same_inputs_on_two_deals_share_a_fingerprint_whatever_their_ids(db: Path) -> None:
    """The Deal id, the Investment id and the Scenario id never reach the
    financial fingerprint: two Deals with identical inputs, each in its own
    wrapper, fingerprint identically under the same recipe."""

    first, second = create_deal("quick", db), create_deal("quick", db)
    a = store.create_scenario_for_deal(first.id, name="A", overrides=(economic_override("quick", first.id),), db_path=db)
    b = store.create_scenario_for_deal(second.id, name="B", overrides=(economic_override("quick", second.id),), db_path=db)

    assert a.investment_id != b.investment_id
    assert a.scenario.scenario_id != b.scenario.scenario_id
    assert _fingerprint(a, db) == _fingerprint(b, db)


# =============================================================================
# 3-5. Display metadata and order never reach financial identity
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_renaming_redescribing_and_reordering_leave_the_fingerprint_unchanged(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    overrides = (economic_override(mode, deal.id), second_override(mode, deal.id))
    record = store.create_scenario_for_deal(deal.id, name="Downside", overrides=overrides, db_path=db)
    original = _fingerprint(record, db)
    key = (record.investment_id, record.scenario.scenario_id)

    store.update_scenario(*key, name="Recession 2027", overrides=overrides, db_path=db)
    assert _fingerprint(record, db) == original  # 3. rename
    store.update_scenario(*key, name="Recession 2027", description="Rates up.", overrides=overrides, db_path=db)
    assert _fingerprint(record, db) == original  # 4. description
    store.update_scenario(*key, name="Recession 2027", description="Rates up.", overrides=tuple(reversed(overrides)), db_path=db)
    assert _fingerprint(record, db) == original  # 5. insertion order


# =============================================================================
# 6-7. Economics move it; an exact revert restores it
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_an_economic_change_moves_the_fingerprint_and_an_exact_revert_restores_it(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    record = store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override(mode, deal.id),), db_path=db)
    key = (record.investment_id, record.scenario.scenario_id)
    original = _fingerprint(record, db)

    store.update_scenario(*key, name="S", overrides=(economic_override(mode, deal.id), second_override(mode, deal.id)), db_path=db)
    changed = _fingerprint(record, db)
    store.update_scenario(*key, name="S", overrides=(economic_override(mode, deal.id),), db_path=db)
    reverted = _fingerprint(record, db)
    store.update_scenario(*key, name="S", overrides=(), db_path=db)
    emptied = _fingerprint(record, db)

    assert original != deal_fingerprint(deal)
    assert changed != original
    assert reverted == original
    assert emptied == deal_fingerprint(deal)


@pytest.mark.parametrize("mode", MODES)
def test_a_base_edit_moves_every_dependent_variant(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    record = store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override(mode, deal.id),), db_path=db)
    before = _fingerprint(record, db)

    update_deal(deal, db, purchase_price=12_345_678.0)

    assert _fingerprint(record, db) != before


# =============================================================================
# The Business Plan -- exactly as D6.5 defines it
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_business_plan_enters_the_variant_fingerprint_exactly_as_it_enters_the_deals(db: Path, mode: str) -> None:
    deal = create_deal(mode, db)
    record = store.create_scenario_for_deal(deal.id, name="S", overrides=(economic_override(mode, deal.id),), db_path=db)
    without_plan = _fingerprint(record, db)

    planned = update_deal(deal, db, business_plan=fx.business_plan())
    with_plan = _fingerprint(record, db)
    update_deal(planned, db, business_plan=BusinessPlan())
    reverted = _fingerprint(record, db)

    assert with_plan != without_plan
    assert reverted == without_plan
    neutral = store.create_scenario_for_deal(deal.id, name="N", db_path=db)
    assert _fingerprint(neutral, db) == deal_fingerprint(store.get_deal(deal.id, db_path=db))


# =============================================================================
# An independent, hand-resolved oracle
# =============================================================================


def test_the_variant_fingerprint_is_the_existing_fingerprint_of_the_hand_resolved_inputs(db: Path) -> None:
    """Every mode, resolved by hand with ``dataclasses.replace`` -- the same
    assumption typed in directly -- and fingerprinted by the existing D6.5
    functions."""

    plan = fx.business_plan()
    quick = create_deal("quick", db, business_plan=plan)
    q = store.create_scenario_for_deal(quick.id, name="Q", overrides=(override(quick.id, "noi_growth", "set", 0.01),), db_path=db)
    assert _fingerprint(q, db) == fingerprint_quick_inputs(
        dataclasses.replace(fx.quick_inputs(), noi_growth=0.01), business_plan=plan
    )

    detailed = create_deal("detailed", db)
    d = store.create_scenario_for_deal(detailed.id, name="D", overrides=(override(detailed.id, "revenue_growth", "set", 0.0),), db_path=db)
    assert _fingerprint(d, db) == fingerprint_detailed_inputs(
        fx.detailed_terms(), dataclasses.replace(fx.detailed_operating(), revenue_growth=0.0),
        business_plan=BusinessPlan(),
    )

    lease_level = create_deal("lease_level", db)
    ll = store.create_scenario_for_deal(lease_level.id, name="L", overrides=(override(lease_level.id, "ltv", "cap_at", 0.5),), db_path=db)
    suites, leases = fx.rent_roll()
    assert _fingerprint(ll, db) == fingerprint_lease_level_inputs(
        dataclasses.replace(fx.lease_level_terms(), ltv=0.5), fx.lease_level_property(), suites, leases,
        market_leasing=fx.market(), operating_inputs=fx.lease_level_operating(), business_plan=BusinessPlan(),
    )


# =============================================================================
# An invalid variant has no fingerprint
# =============================================================================


def test_a_saved_scenario_whose_resolution_is_invalid_reports_the_validators_reason(db: Path) -> None:
    """Stage 1 accepts the recipe; resolving it over the current inputs does
    not (SC-4). The variant is invalid, with the existing validator's reason,
    and is never fingerprinted as if it were valid."""

    deal = create_deal("lease_level", db)
    record = store.create_scenario_for_deal(
        deal.id, name="Too high", overrides=(override(deal.id, "renewal_probability", "add", 0.5),), db_path=db
    )

    with pytest.raises(ScenarioValidationError) as raised:
        variants.scenario_variant_fingerprint(record.investment_id, record.scenario.scenario_id, db_path=db)

    assert {issue.stage for issue in raised.value.issues} == {ScenarioIssueStage.RESOLVED_INPUTS}
