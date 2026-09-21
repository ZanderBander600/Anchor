"""Phase 7 Gate P7.10 Stage 2 -- the two ratified contract corrections.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 8, 9, 10 and
16, and ratified decisions R-G and R-H, as Section 22 records them after review.

**Correction 1 -- publication validates the dependencies, not the workspace.**
A memo must resolve every valuation view it *selected* for inclusion and every
valuation a selected Capital Structure *consumed*. An authored definition the
analyst is still working out, selected by nothing and consumed by nothing, is
not a dependency and must not block the package.

**Correction 2 -- evidence is traceable to the individual claim.** A structured
claim references zero or more Evidence References explicitly, publication
freezes those relationships, and nothing an analyst does to the draft afterwards
can reach the frozen copy.

The twelve required proofs are numbered in the section headers below.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]
from anchor.deals import memo_dependencies as deps
from anchor.deals import store
from anchor.deals.fingerprint import fingerprint_memo_content
from anchor.memo.availability import UnavailableReasonCode
from anchor.memo.contracts import (
    InvestmentCommitteeDecision,
    InvestmentCommitteeOutcome,
    MemoClaimKind,
    MemoDependencyClass,
    MemoFreshness,
)
from anchor.memo.publication import (
    PublicationRefusalCode,
    PublicationRefusedError,
    RequiredValuationReason,
)

BASE, BASE_SCENARIO = fx.BASE, fx.BASE_SCENARIO


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


# =============================================================================
# Setting up an Investment that holds an unavailable valuation definition
# =============================================================================


def _with_unresolvable_definition(db: Path) -> tuple[str, str]:
    """An opted-in Deal whose second valuation definition cannot resolve.

    The definition is an analyst-supplied value citing an Evidence Reference the
    analyst has **not** approved, which Section 5.4 refuses to present as a
    sourced amount. It is a real, authored, unavailable view -- exactly the
    working state Correction 1 says must not block an unrelated publication."""

    deal, investment_id = fx.opted_in_deal(db)
    store.put_evidence_reference(
        investment_id, fx.evidence(investment_id, evidence_id="draft-appraisal", approved=False), db_path=db
    )
    store.create_valuation_timepoint(
        investment_id,
        fx.analyst_value_timepoint(deal.id, timepoint_id="appraised", evidence_id="draft-appraisal"),
        db_path=db,
    )
    return deal.id, investment_id


def _refusals(db: Path, investment_id: str) -> tuple:
    draft = store.get_memo_draft(investment_id, db_path=db)
    assert draft is not None
    selected = draft.selected_decision
    assert selected is not None
    dependency_set = deps.dependency_set(investment_id, selected, draft=draft, db_path=db)
    return deps.publication_refusals_for(investment_id, draft, dependency_set, db_path=db)


def _valuation_refusals(refusals: tuple) -> list:
    return [
        refusal
        for refusal in refusals
        if refusal.code is PublicationRefusalCode.VALUATION_UNAVAILABLE_FOR_REQUIRED_VIEW
    ]


# =============================================================================
# Correction 1, proof 1: an exploratory definition blocks nothing
# =============================================================================


def test_an_unavailable_definition_the_memo_never_selected_does_not_block_publication(
    db: Path,
) -> None:
    """The correction itself. An analyst may hold an appraisal they have not
    approved yet and still publish a memo that leans on neither it nor anything
    it feeds."""

    _, investment_id = _with_unresolvable_definition(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)

    assert _valuation_refusals(_refusals(db, investment_id)) == []
    version = deps.publish(investment_id, db_path=db)
    assert version.version_number == 1


# =============================================================================
# Correction 1, proof 2: selecting it does block, with the typed reason
# =============================================================================


def test_selecting_that_same_definition_blocks_with_its_own_structured_reason(db: Path) -> None:
    """Selection is the switch, and only selection. The same Investment, the
    same unapproved appraisal, one explicit relationship added -- and the
    package now refuses, quoting the valuation's own reason code rather than a
    generic failure."""

    _, investment_id = _with_unresolvable_definition(db)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("appraised",)),
        db_path=db,
    )

    (refusal,) = _valuation_refusals(_refusals(db, investment_id))
    assert refusal.scope_id == "appraised"
    assert refusal.field == "selected_valuation_timepoint_ids"
    assert refusal.unavailable_reason == UnavailableReasonCode.EVIDENCE_NOT_APPROVED.value
    assert "the memo selects it for inclusion" in refusal.message

    with pytest.raises(PublicationRefusedError):
        deps.publish(investment_id, db_path=db)


def test_selection_is_explicit_and_never_inferred_from_order_or_existence(db: Path) -> None:
    """Section 22's wording, as a behaviour: two definitions exist, one is
    first, one is most recently written -- and neither fact selects anything.
    Only the stated relationship does."""

    _, investment_id = _with_unresolvable_definition(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    draft = store.get_memo_draft(investment_id, db_path=db)
    assert draft is not None
    assert draft.selected_valuation_timepoint_ids == ()

    timepoints = store.list_valuation_timepoints(investment_id, db_path=db)
    assert {timepoint.timepoint_id for timepoint in timepoints} == {"as-is", "appraised"}
    assert _valuation_refusals(_refusals(db, investment_id)) == []


# =============================================================================
# Correction 1, proof 3: consumed but never displayed still blocks
# =============================================================================


def test_a_consumed_valuation_blocks_publication_even_when_the_memo_shows_it_nowhere(
    db: Path,
) -> None:
    """The funding cannot be sized without it, so the whole structured result
    rests on it whether or not a page ever prints it.

    Note what this proves about the dependency layer: the variant's *execution*
    refuses here, and the valuation surface survives that refusal, so the
    refusal still carries the specific reason instead of collapsing into "the
    selected cell does not resolve"."""

    deal_id, investment_id = _with_unresolvable_definition(db)
    store.set_deal_capital_structure(
        deal_id, fx.pct_of_value_structure(deal_id, timepoint_id="appraised"), db_path=db
    )
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)

    draft = store.get_memo_draft(investment_id, db_path=db)
    assert draft is not None
    assert draft.selected_valuation_timepoint_ids == ()  # displayed by nothing

    (refusal,) = _valuation_refusals(_refusals(db, investment_id))
    assert refusal.scope_id == "appraised"
    assert refusal.field == "capital_structure"
    assert "percentage-of-value funding" in refusal.message
    assert refusal.unavailable_reason == UnavailableReasonCode.EVIDENCE_NOT_APPROVED.value

    with pytest.raises(PublicationRefusedError):
        deps.publish(investment_id, db_path=db)


def test_the_two_reasons_stay_distinguishable(db: Path) -> None:
    """A view that is both selected and consumed is reported once, as selected:
    the analyst's own action is the one they can act on."""

    deal_id, investment_id = _with_unresolvable_definition(db)
    store.set_deal_capital_structure(
        deal_id, fx.pct_of_value_structure(deal_id, timepoint_id="appraised"), db_path=db
    )
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("appraised",)),
        db_path=db,
    )

    (refusal,) = _valuation_refusals(_refusals(db, investment_id))
    assert refusal.field == "selected_valuation_timepoint_ids"
    assert set(RequiredValuationReason) == {
        RequiredValuationReason.SELECTED,
        RequiredValuationReason.CONSUMED,
    }


# =============================================================================
# Correction 1, proof 4: changing the selection moves the memo's identity only
# =============================================================================


def test_removing_a_view_from_the_selection_moves_the_memo_identity_and_no_history(
    db: Path,
) -> None:
    """Which views a memo includes is memo *content*, so it moves the memo
    content fingerprint -- and nothing else. The valuation definitions did not
    change, so their identity does not move, and the version already published
    is not rewritten by any of it."""

    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("as-is",)),
        db_path=db,
    )
    published = deps.publish(investment_id, db_path=db)
    before = published.memo_content_fingerprint
    assert [view.timepoint_id for view in published.required_valuations] == ["as-is"]

    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    draft = store.get_memo_draft(investment_id, db_path=db)
    assert draft is not None
    evidence = store.list_evidence_references(investment_id, db_path=db)
    assert fingerprint_memo_content(draft, evidence=evidence) != before

    # The valuation definitions themselves did not move.
    selected = published.selected_decision
    assert selected is not None
    ledger = deps.dependency_set(investment_id, selected, draft=draft, db_path=db).by_key()
    frozen = {
        (entry.dependency_class, entry.scope_id): entry.fingerprint
        for entry in published.dependencies
    }
    key = (MemoDependencyClass.VALUATION_DEFINITIONS, "")
    assert ledger[key] == frozen[key]

    # And the published version is exactly as it was.
    reread = store.get_memo_version(investment_id, published.version_id, db_path=db)
    assert reread == published
    assert [view.timepoint_id for view in reread.required_valuations] == ["as-is"]
    assert deal.id


# =============================================================================
# Correction 1, proof 5: an unavailable required value is never substituted
# =============================================================================


def test_no_path_reads_an_unavailable_required_valuation_as_zero_or_the_price(
    db: Path,
) -> None:
    """Section 16 has no numeric escape. The refusal names the timepoint and its
    reason; the frozen row for an unavailable view carries SQL NULL, not 0.0;
    and no message quotes the purchase price."""

    deal_id, investment_id = _with_unresolvable_definition(db)
    store.put_memo_draft(
        investment_id,
        fx.memo_draft(investment_id, selected_valuation_timepoint_ids=("appraised",)),
        db_path=db,
    )
    price = fx.QUICK_INPUTS.purchase_price
    (refusal,) = _valuation_refusals(_refusals(db, investment_id))
    for forbidden in ("0.0", str(price), str(0.6 * price)):
        assert forbidden not in refusal.message

    # Approve the source, publish, then withdraw approval: the frozen row for
    # the now-unavailable view states no value at all.
    store.put_evidence_reference(
        investment_id,
        fx.evidence(investment_id, evidence_id="draft-appraisal", approved=True),
        db_path=db,
    )
    version = deps.publish(investment_id, db_path=db)
    frozen = {view.timepoint_id: view for view in version.valuations}
    assert frozen["appraised"].value is not None

    store.put_evidence_reference(
        investment_id,
        fx.evidence(investment_id, evidence_id="draft-appraisal", approved=False),
        db_path=db,
    )
    with pytest.raises(PublicationRefusedError):
        deps.publish(investment_id, db_path=db)

    connection = sqlite3.connect(db)
    try:
        values = connection.execute(
            "SELECT timepoint_id, value, status FROM memo_version_valuations WHERE version_id = ?",
            (version.version_id,),
        ).fetchall()
    finally:
        connection.close()
    for _, value, status in values:
        if status != "available":
            assert value is None
            assert value != 0.0


# =============================================================================
# Correction 2, proof 1: a claim references zero or more sources, explicitly
# =============================================================================


def _linked_draft(db: Path, investment_id: str, **links: tuple[str, ...]):
    return store.put_memo_draft(
        investment_id, fx.memo_draft(investment_id, **links), db_path=db
    )


def test_a_claim_carries_its_own_sources_and_round_trips_exactly(db: Path) -> None:
    _, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-a")
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-b", display_order=1)

    saved = _linked_draft(
        db,
        investment_id,
        thesis_evidence_ids=("comp-b", "comp-a"),
        risk_evidence_ids=("comp-a",),
    )
    reread = store.get_memo_draft(investment_id, db_path=db)
    assert reread == saved

    thesis = next(item for item in reread.items if item.item_id == "thesis-1")
    condition = next(item for item in reread.items if item.item_id == "condition-1")
    # Authored order is preserved exactly, not sorted into id order.
    assert thesis.evidence_ids == ("comp-b", "comp-a")
    assert condition.evidence_ids == ()  # zero is a legitimate answer
    assert reread.risk_items[0].evidence_ids == ("comp-a",)
    assert reread.term_items[0].evidence_ids == ()
    assert reread.claim_links() == (
        (MemoClaimKind.ITEM.value, "thesis-1", "comp-a"),
        (MemoClaimKind.ITEM.value, "thesis-1", "comp-b"),
        (MemoClaimKind.RISK.value, "risk-1", "comp-a"),
    )


def test_the_relationship_is_normalized_rather_than_an_opaque_blob(db: Path) -> None:
    """One row per link, queryable, with the claim's kind and id as real
    columns -- not a JSON list nobody can join against."""

    _, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-a")
    _linked_draft(db, investment_id, thesis_evidence_ids=("comp-a",), term_evidence_ids=("comp-a",))

    connection = sqlite3.connect(db)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(memo_claim_evidence)").fetchall()
        }
        rows = connection.execute(
            "SELECT claim_kind, item_id, evidence_id FROM memo_claim_evidence ORDER BY claim_kind"
        ).fetchall()
    finally:
        connection.close()
    assert {"memo_id", "claim_kind", "item_id", "evidence_id", "ordinal"} <= columns
    assert rows == [("item", "thesis-1", "comp-a"), ("term", "term-1", "comp-a")]


# =============================================================================
# Correction 2, proofs 2 and 3: foreign and nonexistent references are refused
# =============================================================================


def test_a_claim_citing_a_reference_this_investment_does_not_hold_is_refused(db: Path) -> None:
    from anchor.deals.contracts import EvidenceReferenceNotFoundError

    _, investment_id = fx.opted_in_deal(db)
    with pytest.raises(EvidenceReferenceNotFoundError):
        _linked_draft(db, investment_id, risk_evidence_ids=("no-such-source",))


def test_a_claim_citing_another_investments_reference_is_refused(db: Path) -> None:
    """Scoped to the same Investment, exactly as the register is. A second
    Investment's approved appraisal is not a source this memo may reach."""

    from anchor.deals.contracts import EvidenceReferenceNotFoundError

    _, first = fx.opted_in_deal(db)
    other_deal = fx.create_deal(db, name="Second deal")
    second, _ = store.create_deal_valuation_timepoint(
        other_deal.id, fx.as_is_timepoint(other_deal.id, timepoint_id="as-is-2"), db_path=db
    )
    fx.with_approved_evidence(db, second, evidence_id="theirs")

    with pytest.raises(EvidenceReferenceNotFoundError):
        _linked_draft(db, first, thesis_evidence_ids=("theirs",))


def test_a_reference_a_claim_still_cites_cannot_be_deleted_out_from_under_it(db: Path) -> None:
    """The link is a use. Deleting the source would leave the claim pointing at
    nothing, so the deletion is refused and names what to detach."""

    from anchor.deals.contracts import EvidenceInUseError

    _, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-a")
    _linked_draft(db, investment_id, risk_evidence_ids=("comp-a",))

    with pytest.raises(EvidenceInUseError):
        store.delete_evidence_reference(investment_id, "comp-a", db_path=db)


# =============================================================================
# Correction 2, proof 4: publication snapshots the relationships
# =============================================================================


def test_publishing_freezes_the_item_to_evidence_relationships(db: Path) -> None:
    _, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-a")
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-b", display_order=1)
    _linked_draft(
        db, investment_id, thesis_evidence_ids=("comp-a",), risk_evidence_ids=("comp-b", "comp-a")
    )

    version = deps.publish(investment_id, db_path=db)
    assert version.evidence_for(MemoClaimKind.ITEM, "thesis-1") == ("comp-a",)
    assert version.evidence_for(MemoClaimKind.RISK, "risk-1") == ("comp-b", "comp-a")
    assert version.evidence_for(MemoClaimKind.TERM, "term-1") == ()
    # The frozen items carry the same relationships the snapshot records.
    assert next(item for item in version.items if item.item_id == "thesis-1").evidence_ids == (
        "comp-a",
    )
    # And the sources themselves were frozen, including one cited only by a claim.
    assert {item.evidence_id for item in version.evidence} == {"comp-a", "comp-b"}


# =============================================================================
# Correction 2, proof 5: later draft edits never reach a published version
# =============================================================================


def test_relinking_unlinking_and_deleting_leave_the_published_snapshot_alone(db: Path) -> None:
    _, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-a")
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-b", display_order=1)
    _linked_draft(db, investment_id, thesis_evidence_ids=("comp-a",), risk_evidence_ids=("comp-a",))
    version = deps.publish(investment_id, db_path=db)
    frozen = version.claim_evidence

    # Re-point one claim, unlink another, and remove the source entirely.
    _linked_draft(db, investment_id, thesis_evidence_ids=("comp-b",))
    store.delete_evidence_reference(investment_id, "comp-a", db_path=db)

    reread = store.get_memo_version(investment_id, version.version_id, db_path=db)
    assert reread.claim_evidence == frozen
    assert reread.evidence_for(MemoClaimKind.ITEM, "thesis-1") == ("comp-a",)
    assert reread.evidence_for(MemoClaimKind.RISK, "risk-1") == ("comp-a",)
    assert reread == version
    # The deleted source is still readable as the version's own frozen copy.
    assert {item.evidence_id for item in reread.evidence} == {"comp-a"}
    assert "comp-a" not in {
        item.evidence_id for item in store.list_evidence_references(investment_id, db_path=db)
    }


def test_no_supported_operation_mutates_a_published_claim_evidence_snapshot(db: Path) -> None:
    """Every store operation that writes memo state, run against an Investment
    that already holds a published version, and the version's frozen rows
    compared byte for byte afterwards.

    Publishing again is included deliberately: republication is the one
    operation that *should* record new relationships, and it must record them on
    a **new** version rather than by editing the earlier one."""

    deal, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-a")
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-b", display_order=1)
    _linked_draft(db, investment_id, thesis_evidence_ids=("comp-a",))
    version = deps.publish(investment_id, db_path=db)

    def snapshot() -> list[tuple]:
        connection = sqlite3.connect(db)
        try:
            return list(
                connection.execute(
                    "SELECT * FROM memo_version_claim_evidence WHERE version_id = ? "
                    "ORDER BY claim_kind, item_id, ordinal",
                    (version.version_id,),
                )
            ) + list(
                connection.execute(
                    "SELECT * FROM memo_version_items WHERE version_id = ? ORDER BY item_id",
                    (version.version_id,),
                )
            )
        finally:
            connection.close()

    before = snapshot()
    assert before

    _linked_draft(db, investment_id, thesis_evidence_ids=("comp-b",), term_evidence_ids=("comp-a",))
    store.put_evidence_reference(
        investment_id, fx.evidence(investment_id, evidence_id="comp-a", title="Renamed"), db_path=db
    )
    store.create_valuation_timepoint(
        investment_id, fx.stabilized_timepoint(deal.id, timepoint_id="later"), db_path=db
    )
    store.put_committee_decision(
        investment_id,
        version.version_id,
        InvestmentCommitteeDecision(
            memo_version_id=version.version_id,
            decision=InvestmentCommitteeOutcome.APPROVED,
            decision_note=None,
            decided_at=None,
        ),
        db_path=db,
    )
    second = deps.publish(investment_id, db_path=db)
    assert second.version_id != version.version_id
    assert second.evidence_for(MemoClaimKind.ITEM, "thesis-1") == ("comp-b",)

    assert snapshot() == before
    store.delete_memo_draft(investment_id, db_path=db)
    assert snapshot() == before
    assert store.get_memo_version(investment_id, version.version_id, db_path=db) == version


# =============================================================================
# Correction 2, proof 6: a link change moves the fingerprint and stales the version
# =============================================================================


def test_an_evidence_link_change_moves_the_memo_fingerprint_and_stales_the_version(
    db: Path,
) -> None:
    """Nothing else changes: the same words, the same register, the same
    sources. Only which claim rests on which source. That is a content change,
    and the published version is no longer current against it."""

    _, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-a")
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-b", display_order=1)
    _linked_draft(
        db, investment_id, evidence_ids=("comp-a", "comp-b"), thesis_evidence_ids=("comp-a",)
    )
    version = deps.publish(investment_id, db_path=db)
    assert deps.version_freshness(investment_id, version, db_path=db).freshness is MemoFreshness.CURRENT

    _linked_draft(
        db, investment_id, evidence_ids=("comp-a", "comp-b"), thesis_evidence_ids=("comp-b",)
    )
    draft = store.get_memo_draft(investment_id, db_path=db)
    assert draft is not None
    evidence = store.list_evidence_references(investment_id, db_path=db)
    assert fingerprint_memo_content(draft, evidence=evidence) != version.memo_content_fingerprint

    report = deps.version_freshness(investment_id, version, db_path=db)
    assert report.freshness is not MemoFreshness.CURRENT
    assert MemoDependencyClass.MEMO_CONTENT in report.stale_classes


def test_reordering_one_claims_sources_is_a_content_change_too(db: Path) -> None:
    """Authored order, not presentation: the order a reader is asked to follow
    the support in is part of what the claim says."""

    _, investment_id = fx.opted_in_deal(db)
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-a")
    fx.with_approved_evidence(db, investment_id, evidence_id="comp-b", display_order=1)

    def digest(order: tuple[str, ...]) -> str:
        _linked_draft(db, investment_id, thesis_evidence_ids=order)
        draft = store.get_memo_draft(investment_id, db_path=db)
        assert draft is not None
        return fingerprint_memo_content(
            draft, evidence=store.list_evidence_references(investment_id, db_path=db)
        )

    first = digest(("comp-a", "comp-b"))
    assert digest(("comp-b", "comp-a")) != first
    assert digest(("comp-a", "comp-b")) == first


# =============================================================================
# Correction 2, proof 7: evidence is never required, only traceable
# =============================================================================


def test_a_memo_with_no_claim_links_at_all_publishes(db: Path) -> None:
    """R-G asks that a claim *can* be traced, never that it must be sourced.
    A recommendation, an execution-complexity judgement and a decision ask are
    the analyst's own, and no citation is demanded of them."""

    _, investment_id = fx.opted_in_deal(db)
    saved = store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    assert saved.claim_links() == ()

    version = deps.publish(investment_id, db_path=db)
    assert version.claim_evidence == ()
    assert version.analyst_recommendation is saved.analyst_recommendation
    assert _valuation_refusals(_refusals(db, investment_id)) == []


def test_an_unapproved_source_is_refused_even_when_only_one_claim_cites_it(db: Path) -> None:
    """The claim-level link is held to the register's standard, not a lower one:
    a reviewer following a risk to its source must reach something the analyst
    stood behind."""

    _, investment_id = fx.opted_in_deal(db)
    store.put_evidence_reference(
        investment_id, fx.evidence(investment_id, evidence_id="unapproved", approved=False), db_path=db
    )
    _linked_draft(db, investment_id, risk_evidence_ids=("unapproved",))

    codes = {refusal.code for refusal in _refusals(db, investment_id)}
    assert PublicationRefusalCode.EVIDENCE_NOT_APPROVED in codes
    with pytest.raises(PublicationRefusedError):
        deps.publish(investment_id, db_path=db)
