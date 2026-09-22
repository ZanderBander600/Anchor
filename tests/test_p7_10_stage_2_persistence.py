"""Phase 7 Gate P7.10 Stage 2 -- persistence, the memo lifecycle and
immutability.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 5, 7, 8, 9 and
15, and ratified decisions R-B, R-D, R-F and R-H.

Every claim is measured against the database, not asserted by the code that
makes it: the tables are read directly, and round trips are compared with ``==``
on the contracts themselves.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]
from _p7_2_fixtures import P7_10_TABLES, table_names  # type: ignore[import-not-found]
from anchor.deals import store
from anchor.deals.contracts import (
    EvidenceInUseError,
    EvidenceReferenceNotFoundError,
    InvestmentStructureError,
    MemoNotFoundError,
    MemoVersionNotFoundError,
    ValuationTimepointNotFoundError,
)
from anchor.memo.contracts import (
    AnalystRecommendation,
    InvestmentCommitteeDecision,
    InvestmentCommitteeOutcome,
    MemoSection,
    RiskSeverity,
)
from anchor.memo.validation import MemoValidationError
from anchor.valuation.contracts import (
    AnalystValue,
    DirectCap,
    UnitValuationInstruction,
    ValuationKind,
    ValuationTimepoint,
    ValuationValidationError,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


# =============================================================================
# Schema
# =============================================================================


def test_a_fresh_store_is_current_with_stage_2s_nineteen_empty_p7_10_tables(
    db: Path,
) -> None:
    store.list_deals(db_path=db)
    connection = sqlite3.connect(db)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    # **Re-pinned at P7.10 Stage 4.** A fresh store is at *the current* schema
    # version, not at a number this file freezes: Stage 2's claim is that its
    # own nineteen tables are created empty, and that is asserted below by name.
    assert version == store._SCHEMA_VERSION
    assert set(P7_10_TABLES) <= table_names(db)
    assert len(P7_10_TABLES) == 19
    assert {table: fx.row_count(db, table) for table in P7_10_TABLES} == dict.fromkeys(
        P7_10_TABLES, 0
    )


def test_exit_is_unstorable_at_the_database_itself(db: Path) -> None:
    """R-B as a constraint, not a convention: the reserved system Exit view has
    no row shape to occupy, so no code path -- present or future -- can store a
    second terminal value that could drift from D6's."""

    deal, investment_id = fx.opted_in_deal(db)
    connection = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO valuation_timepoints "
                "(timepoint_id, investment_id, kind, label, model_month, display_order, created_at, updated_at) "
                "VALUES ('x', ?, 'exit', 'Exit', 60, 0, 'now', 'now')",
                (investment_id,),
            )
    finally:
        connection.close()


def test_one_draft_per_investment_is_unwritable_otherwise(db: Path) -> None:
    """R-H in the schema: a second mutable draft is not merely refused by a
    check a future write path could forget -- it cannot be written."""

    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    connection = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO investment_memo_drafts "
                "(memo_id, investment_id, prepared_by, decision_ask, analyst_recommendation, "
                "executive_summary, execution_complexity, return_on_time_notes, created_at, updated_at) "
                "VALUES ('second', ?, NULL, 'x', 'approve', '', 'low', '', 'now', 'now')",
                (investment_id,),
            )
    finally:
        connection.close()


def test_no_update_statement_can_rewrite_a_published_version() -> None:
    """R-H structurally: immutability is not a rule enforced at a boundary --
    there is no SQL in the store capable of updating a ``memo_version`` row."""

    import re

    source = Path("src/anchor/deals/store.py").read_bytes().decode("utf-8")
    updates = re.findall(r"UPDATE\s+(\w+)", source, re.IGNORECASE)
    for table in updates:
        assert not table.startswith("memo_version"), table
        assert table != "investment_memo_versions", table


# =============================================================================
# Valuation definitions (Section 5)
# =============================================================================


def test_a_valuation_definition_round_trips_exactly(db: Path) -> None:
    deal = fx.create_deal(db)
    timepoint = fx.as_is_timepoint(deal.id)
    investment_id, saved = store.create_deal_valuation_timepoint(deal.id, timepoint, db_path=db)

    assert saved.investment_id == investment_id
    assert store.get_valuation_timepoint(investment_id, "as-is", db_path=db) == saved
    assert store.list_valuation_timepoints(investment_id, db_path=db) == (saved,)


def test_both_methods_round_trip_with_their_own_columns(db: Path) -> None:
    """The union is stored under its explicit discriminator, and each row states
    exactly the columns its token requires."""

    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id)
    analyst = store.create_valuation_timepoint(
        investment_id, fx.analyst_value_timepoint(deal.id, kind=ValuationKind.CUSTOM, model_month=12), db_path=db
    )
    assert store.get_valuation_timepoint(investment_id, "analyst", db_path=db) == analyst

    stored = {row[0]: row for row in fx.rows(db, "valuation_unit_instructions")}
    direct = next(row for row in stored.values() if row[3] == "direct_cap")
    supplied = next(row for row in stored.values() if row[3] == "analyst_value")
    assert (direct[4], direct[5], direct[6]) == (fx.AS_IS_CAP_RATE, None, None)
    assert (supplied[4], supplied[5], supplied[6]) == (None, 12_500_000.0, "ev-1")


def test_the_first_save_materializes_the_hidden_investment_and_never_alters_the_deal(
    db: Path,
) -> None:
    """Q4 and Section 7.1: opting a Deal into a valuation materializes its
    hidden one-unit Investment and changes nothing about the Deal."""

    deal = fx.create_deal(db)
    before = store.get_deal(deal.id, db_path=db)
    assert store.read_deal_valuation_timepoints(deal.id, db_path=db) == (None, ())

    investment_id, _ = store.create_deal_valuation_timepoint(
        deal.id, fx.as_is_timepoint(deal.id), db_path=db
    )

    assert store.get_deal(deal.id, db_path=db) == before
    assert store.get_investment(investment_id, db_path=db).hidden is True


def test_reading_materializes_nothing(db: Path) -> None:
    deal = fx.create_deal(db)
    store.read_deal_valuation_timepoints(deal.id, db_path=db)
    store.read_deal_memo_draft(deal.id, db_path=db)
    assert fx.row_count(db, "investments") == 0


def test_a_unit_of_a_visible_investment_is_refused(db: Path) -> None:
    """A memo belongs to the Investment that holds the Unit; a Unit never holds
    one of its own, which is what keeps two memos from describing one decision."""

    from anchor.business_plan import BusinessPlan
    from anchor.investment.contracts import InvestmentUnitMembership, UnitKind

    deal = fx.create_deal(db)
    investment = store.create_visible_investment(
        name="Portfolio",
        transaction_price=fx.QUICK_INPUTS.purchase_price,
        units=(
            InvestmentUnitMembership(
                unit_id=deal.id,
                label="Unit",
                unit_kind=UnitKind.PROPERTY,
                ordinal=0,
                acquisition_month=0,
                disposition_month=None,
            ),
        ),
        business_plan=BusinessPlan(),
        transaction_costs=(),
        db_path=db,
    )
    with pytest.raises(InvestmentStructureError, match="Unit of a visible Investment"):
        store.read_deal_valuation_timepoints(deal.id, db_path=db)
    with pytest.raises(InvestmentStructureError, match="Unit of a visible Investment"):
        store.read_deal_memo_draft(deal.id, db_path=db)
    assert store.list_valuation_timepoints(investment.id, db_path=db) == ()


def test_an_instructed_unit_must_belong_to_the_investment(db: Path) -> None:
    """The one rule the store adds to the Stage 1 contract: a definition naming
    a Unit the Investment does not hold is an authoring fault, refused at the
    door rather than stored as a definition that can never resolve."""

    deal, investment_id = fx.opted_in_deal(db)
    stranger = fx.create_deal(db, name="Someone else")
    with pytest.raises(ValuationValidationError, match="not a Unit of Investment"):
        store.create_valuation_timepoint(
            investment_id, fx.as_is_timepoint(stranger.id, timepoint_id="foreign"), db_path=db
        )


def test_a_duplicate_timepoint_id_is_refused_rather_than_overwriting(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    with pytest.raises(InvestmentStructureError, match="already exists"):
        store.create_valuation_timepoint(investment_id, fx.as_is_timepoint(deal.id), db_path=db)
    assert len(store.list_valuation_timepoints(investment_id, db_path=db)) == 1


def test_an_inside_year_month_is_refused(db: Path) -> None:
    """R-A: an initial timepoint is closing or a hold-year end. An inside-year
    month has no forward NOI in this contract and is never interpolated."""

    deal, investment_id = fx.opted_in_deal(db)
    with pytest.raises(ValuationValidationError, match="multiple of 12"):
        store.create_valuation_timepoint(
            investment_id,
            dataclasses.replace(
                fx.stabilized_timepoint(deal.id, timepoint_id="mid"), model_month=7
            ),
            db_path=db,
        )


def test_as_is_is_month_zero_and_stabilized_is_not(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    with pytest.raises(ValuationValidationError, match="always model month 0"):
        store.create_valuation_timepoint(
            investment_id,
            dataclasses.replace(fx.as_is_timepoint(deal.id, timepoint_id="late"), model_month=24),
            db_path=db,
        )
    with pytest.raises(ValuationValidationError, match="stabilization at closing is As-Is"):
        store.create_valuation_timepoint(
            investment_id,
            dataclasses.replace(
                fx.stabilized_timepoint(deal.id, timepoint_id="zero"), model_month=0
            ),
            db_path=db,
        )


def test_a_definition_is_replaced_whole_and_never_diffed(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    two_units = dataclasses.replace(
        fx.as_is_timepoint(deal.id),
        investment_id=investment_id,
        unit_instructions=(
            UnitValuationInstruction(unit_id=deal.id, method=DirectCap(cap_rate=0.05)),
        ),
    )
    store.update_valuation_timepoint(investment_id, two_units, db_path=db)
    stored = store.get_valuation_timepoint(investment_id, "as-is", db_path=db)
    assert len(stored.unit_instructions) == 1
    assert stored.unit_instructions[0].method == DirectCap(cap_rate=0.05)
    assert fx.row_count(db, "valuation_unit_instructions") == 1


def test_reordering_is_the_only_write_that_touches_display_order(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.create_valuation_timepoint(
        investment_id, fx.stabilized_timepoint(deal.id), db_path=db
    )
    assert [t.timepoint_id for t in store.list_valuation_timepoints(investment_id, db_path=db)] == [
        "as-is",
        "stabilized",
    ]

    reordered = store.reorder_valuation_timepoints(
        investment_id, ("stabilized", "as-is"), db_path=db
    )
    assert [t.timepoint_id for t in reordered] == ["stabilized", "as-is"]

    # A partial ordering is refused: it would silently leave a timepoint's order
    # undefined relative to the rest.
    with pytest.raises(InvestmentStructureError, match="exactly once"):
        store.reorder_valuation_timepoints(investment_id, ("as-is",), db_path=db)


def test_a_foreign_timepoint_is_reported_missing(db: Path) -> None:
    """Fails closed on a foreign id (Section 15): an id never discloses another
    Investment's state."""

    first_deal, first = fx.opted_in_deal(db)
    second_deal = fx.create_deal(db, name="Second")
    second, _ = store.create_deal_valuation_timepoint(
        second_deal.id, fx.as_is_timepoint(second_deal.id, timepoint_id="other"), db_path=db
    )
    with pytest.raises(ValuationTimepointNotFoundError):
        store.get_valuation_timepoint(first, "other", db_path=db)


def test_a_corrupt_method_row_fails_closed(db: Path) -> None:
    """A ``direct_cap`` row with no cap rate is corrupt. Reading a missing rate
    as a default is exactly the fabrication Section 5.3 forbids."""

    from anchor.deals.store import PersistedDealDataError

    deal, investment_id = fx.opted_in_deal(db)
    connection = sqlite3.connect(db)
    try:
        connection.execute("UPDATE valuation_unit_instructions SET cap_rate = NULL")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(PersistedDealDataError, match="never defaulted"):
        store.list_valuation_timepoints(investment_id, db_path=db)


# =============================================================================
# Evidence (Section 8)
# =============================================================================


def test_an_evidence_reference_round_trips_including_its_approval(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    saved = fx.with_approved_evidence(
        db, investment_id, approved=False, as_of_date=date(2026, 6, 30)
    )
    assert store.list_evidence_references(investment_id, db_path=db) == (saved,)
    assert saved.approved is False
    assert saved.as_of_date == date(2026, 6, 30)

    approved = fx.with_approved_evidence(db, investment_id, approved=True)
    assert store.get_evidence_reference(investment_id, "ev-1", db_path=db) == approved
    assert fx.row_count(db, "memo_evidence_references") == 1


def test_evidence_still_in_use_is_refused_and_names_what_to_detach(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id)
    store.create_valuation_timepoint(
        investment_id, fx.analyst_value_timepoint(deal.id, kind=ValuationKind.CUSTOM, model_month=12), db_path=db
    )
    with pytest.raises(EvidenceInUseError) as caught:
        store.delete_evidence_reference(investment_id, "ev-1", db_path=db)
    assert caught.value.valuation_timepoint_ids == ("analyst",)
    assert caught.value.cited_by_draft is False
    assert store.get_evidence_reference(investment_id, "ev-1", db_path=db) is not None


def test_a_memo_citing_an_unknown_reference_is_refused(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    with pytest.raises(EvidenceReferenceNotFoundError):
        store.put_memo_draft(
            investment_id, fx.memo_draft(investment_id, evidence_ids=("nope",)), db_path=db
        )
    assert store.get_memo_draft(investment_id, db_path=db) is None


# =============================================================================
# The memo draft (Section 7)
# =============================================================================


def test_a_memo_draft_round_trips_exactly(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id)
    saved = store.put_memo_draft(
        investment_id, fx.memo_draft(investment_id, evidence_ids=("ev-1",)), db_path=db
    )
    assert store.get_memo_draft(investment_id, db_path=db) == saved
    assert saved.evidence_ids == ("ev-1",)
    assert {item.section for item in saved.items} == {
        MemoSection.THESIS,
        MemoSection.CONDITION_TO_APPROVAL,
    }
    assert saved.risk_items[0].severity is RiskSeverity.MODERATE


def test_the_draft_keeps_one_identity_across_edits(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    first = store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    second = store.put_memo_draft(
        investment_id, fx.memo_draft(investment_id, decision_ask="Revised ask."), db_path=db
    )
    assert second.memo_id == first.memo_id
    assert second.created_at == first.created_at
    assert second.decision_ask == "Revised ask."
    assert fx.row_count(db, "investment_memo_drafts") == 1


def test_a_collection_is_replaced_whole(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    assert fx.row_count(db, "memo_items") == 2

    trimmed = dataclasses.replace(fx.memo_draft(investment_id), items=())
    saved = store.put_memo_draft(investment_id, trimmed, db_path=db)
    assert saved.items == ()
    assert fx.row_count(db, "memo_items") == 0


def test_nothing_is_defaulted(db: Path) -> None:
    """A missing recommendation is an issue, not ``INSUFFICIENT_INFORMATION``.
    Both are real analyst statements, and Anchor makes neither on their behalf."""

    deal, investment_id = fx.opted_in_deal(db)
    with pytest.raises(MemoValidationError, match="never defaulted"):
        store.put_memo_draft(
            investment_id,
            dataclasses.replace(fx.memo_draft(investment_id), analyst_recommendation=None),  # type: ignore[arg-type]
            db_path=db,
        )


def test_deleting_a_draft_leaves_published_versions(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    version = _publish(db, investment_id)

    store.delete_memo_draft(investment_id, db_path=db)
    assert store.get_memo_draft(investment_id, db_path=db) is None
    assert store.get_memo_version(investment_id, version.version_id, db_path=db) == version


def test_the_wrapper_never_collapses_while_it_holds_a_published_version(db: Path) -> None:
    """Collapsing a wrapper that still holds an immutable decision record would
    delete history as a side effect of tidying an empty workspace."""

    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    _publish(db, investment_id)

    store.delete_valuation_timepoint(investment_id, "as-is", db_path=db)
    store.delete_memo_draft(investment_id, db_path=db)

    assert store.get_investment(investment_id, db_path=db) is not None
    assert len(store.list_memo_versions(investment_id, db_path=db)) == 1


# =============================================================================
# Publication and immutability (Section 9; R-H)
# =============================================================================


def _publish(db: Path, investment_id: str):
    from anchor.deals import memo_dependencies

    return memo_dependencies.publish(investment_id, db_path=db)


def test_publishing_copies_and_never_consumes_the_draft(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    draft = store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    version = _publish(db, investment_id)

    assert store.get_memo_draft(investment_id, db_path=db) == draft
    assert version.version_number == 1
    assert version.decision_ask == draft.decision_ask
    assert version.dependencies, "a version records its dependency ledger"


def test_version_n_is_unchanged_after_the_draft_moves_and_n_plus_1_is_published(
    db: Path,
) -> None:
    """The required proof: a later edit and a later publication leave an earlier
    version exactly as its committee read it."""

    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    v1 = _publish(db, investment_id)

    store.put_memo_draft(
        investment_id,
        fx.memo_draft(
            investment_id,
            decision_ask="Decline: basis no longer supported.",
            recommendation=AnalystRecommendation.DECLINE,
        ),
        db_path=db,
    )
    assert store.get_memo_version(investment_id, v1.version_id, db_path=db) == v1

    v2 = _publish(db, investment_id)
    assert v2.version_number == 2
    assert v2.analyst_recommendation is AnalystRecommendation.DECLINE
    assert store.get_memo_version(investment_id, v1.version_id, db_path=db) == v1
    assert v1.analyst_recommendation is AnalystRecommendation.APPROVE_WITH_CONDITIONS
    assert [v.version_number for v in store.list_memo_versions(investment_id, db_path=db)] == [1, 2]


def test_version_numbers_never_repeat(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    numbers = [_publish(db, investment_id).version_number for _ in range(3)]
    assert numbers == [1, 2, 3]

    connection = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO investment_memo_versions "
                "(version_id, investment_id, version_number, decision_ask, analyst_recommendation, "
                "executive_summary, execution_complexity, return_on_time_notes, selected_strategy_id, "
                "selected_scenario_id, perspective, memo_content_fingerprint, published_fingerprint, created_at) "
                "VALUES ('dup', ?, 1, 'x', 'approve', '', 'low', '', 'base', 'base', 'project', 'a', 'b', 'now')",
                (investment_id,),
            )
    finally:
        connection.close()


def test_a_published_version_freezes_its_evidence_content(db: Path) -> None:
    """A version states the source as it stood when the committee read it; a
    later edit to the live reference changes freshness and never rewrites
    history."""

    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, title="Original title")
    store.put_memo_draft(
        investment_id, fx.memo_draft(investment_id, evidence_ids=("ev-1",)), db_path=db
    )
    version = _publish(db, investment_id)
    assert version.evidence[0].title == "Original title"

    fx.with_approved_evidence(db, investment_id, title="Revised title")
    assert store.get_memo_version(investment_id, version.version_id, db_path=db) == version
    assert store.get_memo_version(investment_id, version.version_id, db_path=db).evidence[0].title == (
        "Original title"
    )


def test_a_version_of_another_investment_is_reported_missing(db: Path) -> None:
    deal_a, first = fx.opted_in_deal(db)
    store.put_memo_draft(first, fx.memo_draft(first), db_path=db)
    version = _publish(db, first)

    deal_b = fx.create_deal(db, name="Second")
    second, _ = store.create_deal_valuation_timepoint(
        deal_b.id, fx.as_is_timepoint(deal_b.id, timepoint_id="b"), db_path=db
    )
    with pytest.raises(MemoVersionNotFoundError):
        store.get_memo_version(second, version.version_id, db_path=db)


# =============================================================================
# The Investment Committee decision (Section 7.5; R-F)
# =============================================================================


def test_the_ic_decision_is_separate_from_the_analyst_recommendation(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    version = _publish(db, investment_id)

    assert store.get_committee_decision(investment_id, version.version_id, db_path=db) is None

    recorded = store.put_committee_decision(
        investment_id,
        version.version_id,
        InvestmentCommitteeDecision(
            memo_version_id=version.version_id,
            decision=InvestmentCommitteeOutcome.DEFERRED,
            decision_note="Deferred pending a site visit.",
            decided_at="2026-09-20",
        ),
        db_path=db,
    )
    assert recorded.decision is InvestmentCommitteeOutcome.DEFERRED

    after = store.get_memo_version(investment_id, version.version_id, db_path=db)
    assert after == version
    assert after.published_fingerprint == version.published_fingerprint
    assert after.analyst_recommendation is AnalystRecommendation.APPROVE_WITH_CONDITIONS


def test_no_committee_decision_attaches_to_a_draft(db: Path) -> None:
    """A committee decides on something immutable, or it has not decided. There
    is no route to record one against a draft."""

    deal, investment_id = fx.opted_in_deal(db)
    draft = store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    with pytest.raises(MemoVersionNotFoundError):
        store.put_committee_decision(
            investment_id,
            draft.memo_id,
            InvestmentCommitteeDecision(
                memo_version_id=draft.memo_id,
                decision=InvestmentCommitteeOutcome.APPROVED,
                decision_note=None,
                decided_at=None,
            ),
            db_path=db,
        )


def test_recording_a_decision_twice_updates_one_row(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    version = _publish(db, investment_id)

    for outcome in (InvestmentCommitteeOutcome.PENDING, InvestmentCommitteeOutcome.APPROVED):
        store.put_committee_decision(
            investment_id,
            version.version_id,
            InvestmentCommitteeDecision(
                memo_version_id=version.version_id,
                decision=outcome,
                decision_note=None,
                decided_at=None,
            ),
            db_path=db,
        )
    assert fx.row_count(db, "investment_committee_decisions") == 1
    assert store.get_committee_decision(
        investment_id, version.version_id, db_path=db
    ).decision is InvestmentCommitteeOutcome.APPROVED


# =============================================================================
# Deleting the Investment
# =============================================================================


def test_deleting_the_deal_removes_every_p7_10_row_and_never_another_deal(db: Path) -> None:
    deal, investment_id = fx.opted_in_deal(db)
    other = fx.create_deal(db, name="Untouched")
    fx.with_approved_evidence(db, investment_id)
    store.put_memo_draft(
        investment_id, fx.memo_draft(investment_id, evidence_ids=("ev-1",)), db_path=db
    )
    _publish(db, investment_id)

    store.delete_deal(deal.id, db_path=db)

    for table in P7_10_TABLES:
        assert fx.row_count(db, table) == 0, table
    assert store.get_deal(other.id, db_path=db).id == other.id
