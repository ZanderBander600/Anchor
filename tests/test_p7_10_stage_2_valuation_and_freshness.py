"""Phase 7 Gate P7.10 Stage 2 -- resolved valuation views, the layered
fingerprints, and precise stale reasons.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 5, 6, 6.1, 6.2,
8, 9, 10 and 16, and ratified decisions R-B, R-D, R-E and R-H.

The four required directional proofs live here:

1. an authorized dependency change invalidates the published-current status, and
   names *which* class moved;
2. a presentation-only change creates no financial invalidation;
3. a missing valuation never becomes zero, the purchase price, or an
   amount-bearing funding requirement;
4. a valid later valuation stays reportable and still cannot create a later
   financing event.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]
from anchor.deals import memo_dependencies as deps
from anchor.deals import store
from anchor.deals.fingerprint import (
    fingerprint_structured_source,
    fingerprint_valuation_definitions,
)
from anchor.deals.structured_variants import (
    analyze_structured_valuations,
    analyze_structured_variant,
    structured_variant_fingerprint,
)
from anchor.memo.availability import AvailabilityStatus, UnavailableReasonCode, UnavailableState
from anchor.memo.contracts import (
    FINANCIAL_DEPENDENCY_CLASSES,
    MemoDependencyClass,
    MemoFreshness,
)
from anchor.valuation.contracts import ValuationKind

BASE, BASE_SCENARIO = fx.BASE, fx.BASE_SCENARIO

#: Year 1 NOI of the fixture Deal, and the As-Is value it capitalises to.
#: ``current_noi`` is already the in-place NOI the engine projects forward,
#: so Year 1 is exactly it -- no occupancy factor is applied on top.
YEAR_ONE_NOI = fx.QUICK_INPUTS.current_noi
AS_IS_VALUE = YEAR_ONE_NOI / fx.AS_IS_CAP_RATE


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def _views(db: Path, investment_id: str):
    return analyze_structured_valuations(investment_id, BASE, BASE_SCENARIO, db_path=db)


# =============================================================================
# 1. Resolution reads Stage 1 and reproduces nothing
# =============================================================================


def test_an_as_is_direct_cap_is_exactly_year_one_noi_over_the_cap_rate(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    (view,) = _views(db, investment_id).views

    assert view.status is AvailabilityStatus.AVAILABLE
    assert view.kind is ValuationKind.AS_IS
    assert view.model_month == 0
    unit = view.unit_views[0]
    assert unit.forward_noi == pytest.approx(YEAR_ONE_NOI)
    assert unit.cap_rate == fx.AS_IS_CAP_RATE
    assert view.value == pytest.approx(unit.forward_noi / unit.cap_rate)
    assert unit.analyst_supplied is False


def test_an_analyst_supplied_value_is_always_labelled_as_one(db: Path) -> None:
    """Section 5.4: no presentation layer can show an analyst's own number as an
    Anchor valuation."""

    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id)
    store.create_valuation_timepoint(
        investment_id,
        fx.analyst_value_timepoint(deal.id, kind=ValuationKind.CUSTOM, model_month=12),
        db_path=db,
    )
    view = next(v for v in _views(db, investment_id).views if v.timepoint_id == "analyst")
    assert view.status is AvailabilityStatus.AVAILABLE
    assert view.value == 12_500_000.0
    unit = view.unit_views[0]
    assert unit.analyst_supplied is True
    assert unit.forward_noi is None and unit.cap_rate is None
    assert unit.evidence_id == "ev-1"


def test_the_exit_month_is_reserved_and_never_resolves_as_a_stored_definition(db: Path) -> None:
    """R-B: a stored definition at the exit month would be a second terminal
    value able to drift from D6's."""

    deal, investment_id = fx.opted_in_deal(db)
    store.create_valuation_timepoint(
        investment_id,
        fx.stabilized_timepoint(deal.id, timepoint_id="at-exit", model_month=60),
        db_path=db,
    )
    view = next(v for v in _views(db, investment_id).views if v.timepoint_id == "at-exit")
    assert view.status is AvailabilityStatus.UNAVAILABLE
    assert view.value is None
    # The Unit carries the specific reason; the Investment has no value because
    # a member Unit has none (Section 5.5), and names it.
    assert view.unit_views[0].unavailable.reason_code is UnavailableReasonCode.RESERVED_EXIT_MONTH
    assert view.unavailable.reason_code is UnavailableReasonCode.INCOMPLETE_UNITS
    assert "reserved_exit_month" in view.unavailable.reason


def test_a_month_beyond_the_hold_is_outside_the_horizon(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.create_valuation_timepoint(
        investment_id,
        fx.stabilized_timepoint(deal.id, timepoint_id="too-late", model_month=120),
        db_path=db,
    )
    view = next(v for v in _views(db, investment_id).views if v.timepoint_id == "too-late")
    assert view.unit_views[0].unavailable.reason_code is UnavailableReasonCode.OUTSIDE_HOLD_HORIZON
    assert view.unavailable.reason_code is UnavailableReasonCode.INCOMPLETE_UNITS
    assert view.value is None


# =============================================================================
# 2. The evidence gate (Section 8; R-D)
# =============================================================================


def test_an_unapproved_source_yields_no_value_and_never_reports_the_amount(db: Path) -> None:
    """The stated amount is deliberately absent: presenting an unsourced
    external value as a valuation is the "silently upgraded to a fact"
    Section 8 forbids."""

    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, approved=False)
    store.create_valuation_timepoint(
        investment_id,
        fx.analyst_value_timepoint(deal.id, kind=ValuationKind.CUSTOM, model_month=12),
        db_path=db,
    )
    surface = _views(db, investment_id)
    view = next(v for v in surface.views if v.timepoint_id == "analyst")

    assert view.status is AvailabilityStatus.UNAVAILABLE
    assert view.value is None
    assert view.unavailable.reason_code is UnavailableReasonCode.EVIDENCE_NOT_APPROVED
    assert "12500000" not in str(view.unavailable)
    assert "12,500,000" not in view.unavailable.reason
    assert surface.evidence_blocked[0].timepoint_id == "analyst"
    assert surface.evidence_blocked[0].units[0].detail == "the analyst has not approved"


def test_a_missing_source_and_an_unapproved_one_stay_distinct(db: Path) -> None:
    """Collapsing them would tell an analyst to approve something that is not
    there."""

    deal, investment_id = fx.opted_in_deal(db)
    store.create_valuation_timepoint(
        investment_id,
        fx.analyst_value_timepoint(
            deal.id, evidence_id="never-created", kind=ValuationKind.CUSTOM, model_month=12
        ),
        db_path=db,
    )
    surface = _views(db, investment_id)
    assert surface.evidence_blocked[0].units[0].detail == "this Investment does not hold"


def test_approving_the_source_resolves_the_value(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, approved=False)
    store.create_valuation_timepoint(
        investment_id,
        fx.analyst_value_timepoint(deal.id, kind=ValuationKind.CUSTOM, model_month=12),
        db_path=db,
    )
    assert next(v for v in _views(db, investment_id).views if v.timepoint_id == "analyst").value is None

    fx.with_approved_evidence(db, investment_id, approved=True)
    view = next(v for v in _views(db, investment_id).views if v.timepoint_id == "analyst")
    assert view.status is AvailabilityStatus.AVAILABLE
    assert view.value == 12_500_000.0


# =============================================================================
# 3. `PctOfValue` execution, and the closing-only boundary (Sections 6, 6.1)
# =============================================================================


def test_a_closing_pct_of_value_funds_exactly_the_percentage_of_the_resolved_value(
    db: Path,
) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.set_deal_capital_structure(deal.id, fx.pct_of_value_structure(deal.id), db_path=db)

    analysis = analyze_structured_variant(investment_id, BASE, BASE_SCENARIO, db_path=db)
    senior = next(p for p in analysis.result.positions if p.position_id == "senior")
    assert senior.funded_amount == pytest.approx(0.6 * AS_IS_VALUE)


def test_a_missing_valuation_never_becomes_zero_or_the_purchase_price(db: Path) -> None:
    """Required proof 4. The named timepoint is not defined at all, so the
    advance is unknown.

    Two surfaces, both honest. The Stage 2 valuation surface reports the funding
    as unavailable with the specific reason and **no amount**; the accepted
    Stage 1 executor still refuses to run the analysis, with its own typed
    execution issue. Neither invents a number, and neither is a generic error."""

    from anchor.capital_structure.execution_contracts import CapitalStructureExecutionError

    deal = fx.create_deal(db)
    investment_id, _ = store.create_deal_valuation_timepoint(
        deal.id, fx.as_is_timepoint(deal.id, timepoint_id="other"), db_path=db
    )
    store.set_deal_capital_structure(
        deal.id, fx.pct_of_value_structure(deal.id, timepoint_id="as-is"), db_path=db
    )

    (state,) = _views(db, investment_id).funding_states
    assert state.status is AvailabilityStatus.UNAVAILABLE
    assert state.amount is None
    assert state.unavailable.reason_code is UnavailableReasonCode.FUNDING_REQUIREMENT_UNRESOLVED
    assert "does not define" in state.unavailable.reason
    # Never zero, never the purchase price, never a percentage of it.
    for forbidden in ("0.0", str(fx.QUICK_INPUTS.purchase_price), str(0.6 * fx.QUICK_INPUTS.purchase_price)):
        assert forbidden not in str(state.amount)

    # The unavailable state has nowhere to put a number even if a caller tried.
    assert not any(
        field.name in {"value", "amount", "scope_value", "estimate"}
        for field in dataclasses.fields(UnavailableState)
    )

    with pytest.raises(CapitalStructureExecutionError):
        analyze_structured_variant(investment_id, BASE, BASE_SCENARIO, db_path=db)


def test_a_later_valuation_is_reportable_and_creates_no_later_financing_event(
    db: Path,
) -> None:
    """Required proof 5, and Section 6.1 exactly: the valuation authority
    resolves a Stabilized timepoint to a real value, and the capital execution
    seam still cannot consume it, because the P7.8 closing-only funding window
    is unchanged. The limitation is a named reason -- never a zero, and never a
    fallback to the acquisition price."""

    from anchor.capital_structure.execution_contracts import CapitalStructureExecutionError

    deal, investment_id = fx.opted_in_deal(db)
    store.create_valuation_timepoint(
        investment_id, fx.stabilized_timepoint(deal.id, model_month=24), db_path=db
    )

    stabilized = next(v for v in _views(db, investment_id).views if v.timepoint_id == "stabilized")
    assert stabilized.status is AvailabilityStatus.AVAILABLE
    assert stabilized.value is not None and stabilized.value > 0
    assert stabilized.model_month == 24

    # A closing funding event naming that later timepoint does not resolve: the
    # two model months are never moved to meet.
    store.set_deal_capital_structure(
        deal.id, fx.pct_of_value_structure(deal.id, timepoint_id="stabilized"), db_path=db
    )
    (state,) = _views(db, investment_id).funding_states
    assert state.status is AvailabilityStatus.UNAVAILABLE
    assert state.amount is None
    assert state.unavailable.funding_reason.value == "model_month_mismatch"
    assert "neither is moved to the other" in state.unavailable.reason

    with pytest.raises(CapitalStructureExecutionError):
        analyze_structured_variant(investment_id, BASE, BASE_SCENARIO, db_path=db)


# =============================================================================
# 4. Identity (Section 10)
# =============================================================================


def test_a_label_rename_moves_no_valuation_identity(db: Path) -> None:
    """Required proof 3, at the identity layer. Section 5.2: a label change is
    presentation-only."""

    deal, investment_id = fx.opted_in_deal(db)
    before = _views(db, investment_id)

    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal.id), label="Renamed view")
    after = _views(db, investment_id)

    assert after.valuation_definition_fingerprint == before.valuation_definition_fingerprint
    assert after.valuation_result_fingerprint == before.valuation_result_fingerprint
    assert after.views[0].label == "Renamed view"


def test_reordering_the_definitions_moves_no_identity(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.create_valuation_timepoint(
        investment_id, fx.stabilized_timepoint(deal.id), db_path=db
    )
    before = _views(db, investment_id)

    store.reorder_valuation_timepoints(investment_id, ("stabilized", "as-is"), db_path=db)
    after = _views(db, investment_id)

    assert after.valuation_definition_fingerprint == before.valuation_definition_fingerprint
    assert after.valuation_result_fingerprint == before.valuation_result_fingerprint


def test_a_cap_rate_change_moves_both_valuation_identities(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    before = _views(db, investment_id)

    fx.replace_timepoint(
        db,
        investment_id,
        fx.as_is_timepoint(deal.id, cap_rate=0.05),
    )
    after = _views(db, investment_id)

    assert after.valuation_definition_fingerprint != before.valuation_definition_fingerprint
    assert after.valuation_result_fingerprint != before.valuation_result_fingerprint


def test_an_exact_revert_restores_the_fingerprint(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    original = _views(db, investment_id).valuation_definition_fingerprint

    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal.id, cap_rate=0.05))
    assert _views(db, investment_id).valuation_definition_fingerprint != original

    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal.id))
    assert _views(db, investment_id).valuation_definition_fingerprint == original


def test_a_report_only_valuation_never_moves_the_structured_identity(db: Path) -> None:
    """Section 6: a valuation no position consumes changes valuation and memo
    freshness, and deliberately not the underlying Acquisition analysis."""

    deal, investment_id = fx.opted_in_deal(db)
    store.set_deal_capital_structure(
        deal.id, fx.pct_of_value_structure(deal.id, timepoint_id="as-is"), db_path=db
    )
    before = structured_variant_fingerprint(
        investment_id, BASE, BASE_SCENARIO, db_path=db
    ).structured_source_fingerprint

    store.create_valuation_timepoint(
        investment_id, fx.stabilized_timepoint(deal.id), db_path=db
    )
    after = structured_variant_fingerprint(
        investment_id, BASE, BASE_SCENARIO, db_path=db
    ).structured_source_fingerprint
    assert after == before


def test_a_consumed_valuation_does_move_the_structured_identity(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.set_deal_capital_structure(
        deal.id, fx.pct_of_value_structure(deal.id, timepoint_id="as-is"), db_path=db
    )
    before = structured_variant_fingerprint(
        investment_id, BASE, BASE_SCENARIO, db_path=db
    ).structured_source_fingerprint

    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal.id, cap_rate=0.05))
    after = structured_variant_fingerprint(
        investment_id, BASE, BASE_SCENARIO, db_path=db
    ).structured_source_fingerprint
    assert after != before


def test_a_structure_with_no_pct_of_value_hashes_exactly_what_it_did_before(db: Path) -> None:
    """FP-2 preserved: ``consumed_valuations`` joins the payload only when
    non-empty, so every structured digest that existed before this gate is
    byte-identical."""

    import hashlib
    import json

    from anchor.deals.fingerprint import capital_structure_payload

    deal, investment_id = fx.opted_in_deal(db)
    structure = fx.pct_of_value_structure(deal.id)
    project = "a" * 64
    legacy_payload = {
        "project_source_fingerprint": project,
        "capital_structure": capital_structure_payload(structure),
    }
    legacy = hashlib.sha256(
        json.dumps(legacy_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    for consumed in (None, {}):
        assert (
            fingerprint_structured_source(
                project_source_fingerprint=project,
                capital_structure=structure,
                consumed_valuations=consumed,
            )
            == legacy
        )


def test_both_fingerprint_doors_agree(db: Path) -> None:
    """A variant's identity must not differ by which door the caller came
    through, or the P7.5 coherence check and the P7.9 Partnership fingerprint
    built on top of it would be reading a different variant than they thought."""

    deal, investment_id = fx.opted_in_deal(db)
    store.set_deal_capital_structure(deal.id, fx.pct_of_value_structure(deal.id), db_path=db)

    quick = structured_variant_fingerprint(investment_id, BASE, BASE_SCENARIO, db_path=db)
    full = analyze_structured_variant(investment_id, BASE, BASE_SCENARIO, db_path=db)
    surface = _views(db, investment_id)
    assert quick.structured_source_fingerprint == full.structured_source_fingerprint
    assert surface.structured_source_fingerprint == full.structured_source_fingerprint


# =============================================================================
# 5. Freshness and precise stale reasons (Section 9)
# =============================================================================


def _publish(db: Path, investment_id: str):
    return deps.publish(investment_id, db_path=db)


def _published(db: Path):
    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id)
    store.put_memo_draft(
        investment_id, fx.memo_draft(investment_id, evidence_ids=("ev-1",)), db_path=db
    )
    return deal, investment_id, _publish(db, investment_id)


def test_a_freshly_published_version_is_current(db: Path) -> None:
    deal, investment_id, version = _published(db)
    report = deps.version_freshness(investment_id, version, db_path=db)
    assert report.freshness is MemoFreshness.CURRENT
    assert report.stale_dependencies == ()


def test_the_ledger_records_every_computable_dependency_class(db: Path) -> None:
    deal, investment_id, version = _published(db)
    recorded = {entry.dependency_class for entry in version.dependencies}
    # Every class except PARTNERSHIP, which this Investment has none of (FP-2).
    expected = set(MemoDependencyClass) - {MemoDependencyClass.PARTNERSHIP}
    assert recorded == expected


@pytest.mark.parametrize(
    "change, expected",
    [
        ("cap_rate", {MemoDependencyClass.VALUATION_DEFINITIONS, MemoDependencyClass.VALUATION_RESULTS}),
        ("evidence", {MemoDependencyClass.EVIDENCE, MemoDependencyClass.MEMO_CONTENT}),
        ("memo", {MemoDependencyClass.MEMO_CONTENT}),
    ],
)
def test_a_dependency_change_names_which_class_moved(
    db: Path, change: str, expected: set[MemoDependencyClass]
) -> None:
    """Required proof 1: an authorized dependency change invalidates the
    published-current status, and says *which* class moved rather than only
    "stale"."""

    deal, investment_id, version = _published(db)

    if change == "cap_rate":
        fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal.id, cap_rate=0.05))
    elif change == "evidence":
        fx.with_approved_evidence(db, investment_id, title="A different source")
    else:
        store.put_memo_draft(
            investment_id,
            fx.memo_draft(investment_id, evidence_ids=("ev-1",), decision_ask="A revised ask."),
            db_path=db,
        )

    report = deps.version_freshness(investment_id, version, db_path=db)
    assert report.freshness is MemoFreshness.STALE
    assert set(report.stale_classes) == expected
    assert all(entry.reason for entry in report.stale_dependencies)


def test_a_business_plan_change_is_named_specifically(db: Path) -> None:
    """The finer statement leads: "the Business Plan changed", not only "the
    underwriting changed"."""

    from anchor.business_plan import BusinessPlan, CapitalItemCategory, CapitalPlanItem

    deal, investment_id, version = _published(db)
    store.update_deal(
        deal.id,
        deal.name,
        fx.QUICK_INPUTS,
        business_plan=BusinessPlan(
            capital_items=(
                CapitalPlanItem(
                    item_id="capex-1",
                    description="Roof replacement",
                    category=CapitalItemCategory.DEFERRED_MAINTENANCE,
                    month=1,
                    amount=250_000.0,
                ),
            )
        ),
        db_path=db,
    )
    report = deps.version_freshness(investment_id, version, db_path=db)
    assert report.freshness is MemoFreshness.STALE
    assert report.stale_classes[0] is MemoDependencyClass.BUSINESS_PLAN
    assert MemoDependencyClass.PROJECT_VARIANT in report.stale_classes


def test_a_presentation_only_change_creates_no_financial_invalidation(db: Path) -> None:
    """Required proof 2, stated precisely: a valuation label rename and a
    valuation reorder move no financial dependency class at all."""

    deal, investment_id, version = _published(db)
    store.create_valuation_timepoint(
        investment_id, fx.stabilized_timepoint(deal.id), db_path=db
    )
    baseline = deps.version_freshness(investment_id, version, db_path=db)
    financial_before = set(baseline.stale_classes) & FINANCIAL_DEPENDENCY_CLASSES

    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal.id), label="Renamed")
    store.reorder_valuation_timepoints(investment_id, ("stabilized", "as-is"), db_path=db)

    after = deps.version_freshness(investment_id, version, db_path=db)
    assert set(after.stale_classes) & FINANCIAL_DEPENDENCY_CLASSES == financial_before


def test_a_deleted_strategy_is_stale_with_a_named_condition_not_an_error(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    strategy = store.create_strategy_for_deal(
        deal.id, name="Hold longer", description="Seven-year hold.", db_path=db
    ).strategy
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected=fx.project_cell(strategy_id=strategy.strategy_id)),
        db_path=db,
    )
    version = _publish(db, investment_id)

    store.delete_strategy(investment_id, strategy.strategy_id, db_path=db)

    report = deps.version_freshness(investment_id, version, db_path=db)
    assert report.freshness is MemoFreshness.STALE
    assert any(entry.current_fingerprint is None for entry in report.stale_dependencies)
    # The version itself stays readable and unchanged.
    assert store.get_memo_version(investment_id, version.version_id, db_path=db) == version


def test_a_financial_change_leaves_history_intact(db: Path) -> None:
    """Required proof 2 of the prompt's list: a financial dependency change
    makes the current package stale but destroys no historical version."""

    deal, investment_id, v1 = _published(db)
    fx.replace_timepoint(db, investment_id, fx.as_is_timepoint(deal.id, cap_rate=0.05))

    assert deps.version_freshness(investment_id, v1, db_path=db).freshness is MemoFreshness.STALE
    assert store.get_memo_version(investment_id, v1.version_id, db_path=db) == v1
    assert v1.valuations[0].value == pytest.approx(AS_IS_VALUE)
