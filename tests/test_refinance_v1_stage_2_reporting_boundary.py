"""Refinance & Capital Events V1 Stage 2 -- typed state, truthful publication
and the temporary Stage 2/Stage 3 report boundary (second review correction).

One visible two-Unit Investment shares its timepoints (the exact-scope world):
Unit A has an available direct-cap value, Unit B an analyst-supplied value
whose evidence is unapproved.

1. **The temporary Stage 3 report gate.** A selected Capital Structure that
   configures a capital event is neither published nor previewed as a report
   (R-P, Sections 12.5 and 16.3): readiness, the publish route and the draft
   preview all state ``refinance_reporting_not_available``, and the exact-scope
   valuation findings are still reported beside it.
2. **The typed unavailable invariant.** A gated Unit cell carries
   ``EVIDENCE_NOT_APPROVED`` (the additive P7.10 amendment); every consumer
   reads it from the cell it consumed, and no amount appears anywhere.
3. **Typed consumers and truthful wording.** A refinance's refusal says a
   refinance consumes the value, a funding's keeps the accepted wording, and
   neither names an opaque identity.
4. **Exact-scope reports.** A Unit-scoped ``PctOfValue`` publishes on its own
   cell and the report shows that cell, never the unavailable Investment view.
5. **The frozen consumption record** is typed, owned and fail-closed.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _p7_10_stage_2_fixtures as memo_fx  # type: ignore[import-not-found]
import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.analysis.strategy import InvestmentStrategyOverlay, StrategyDomain
from anchor.capital_structure.contracts import PctOfValue
from anchor.capital_structure.funding import resolve_valuation_funding
from anchor.capital_structure.refinance_contracts import RefinanceStatus, RefinanceUnavailableReason
from anchor.deals import memo_dependencies as deps
from anchor.deals import store
from anchor.deals.contracts import MemoVersionNotFoundError
from anchor.deals.store import PersistedDealDataError
from anchor.deals.structured_variants import analyze_structured_valuations, analyze_structured_variant
from anchor.deals.valuation_views import funding_authority
from anchor.formatting import format_currency
from anchor.memo.availability import UnavailableReasonCode, unit_unavailable, valuation_reason_code
from anchor.memo.contracts import ValuationConsumerKind
from anchor.memo.publication import PublicationRefusedError, ReportPreviewRefusedError
from anchor.reporting.assembly import assemble_draft_preview, unit_display_name
from anchor.valuation.contracts import (
    UnresolvedFundingRequirement,
    ValuationAvailability,
    ValuationMethodKind,
    ValuationUnavailableReason,
)
from test_refinance_v1_stage_2_exact_scope import (  # type: ignore[import-not-found]
    AS_IS,
    EVIDENCE,
    INVESTMENT_SCOPE,
    TIMEPOINT,
    _approve,
    _senior,
    build,
)

GATE = "refinance_reporting_not_available"
VALUATION = "valuation_unavailable_for_required_view"
#: Unit A's direct-cap value at every shared timepoint: 800,000 / 0.064.
A_VALUE = 12_500_000.0


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    return build_world(tmp_path / "anchor.db")


def build_world(db: Path) -> dict[str, Any]:
    """The exact-scope world plus an Investment-scoped ``PctOfValue`` Strategy."""

    world = build(db)
    world["pct_inv"] = store.create_strategy(
        world["investment_id"],
        name="Value-sized portfolio",
        root_overlays=(
            InvestmentStrategyOverlay(
                domain=StrategyDomain.CAPITAL_STRUCTURE,
                content=fx.plain(_senior("sen-pi", INVESTMENT_SCOPE, 0.0, PctOfValue(timepoint_id=AS_IS, pct=0.4))),
            ),
        ),
        db_path=world["db"],
    ).strategy.strategy_id
    return world


def _draft(world: dict[str, Any], strategy: str, *, selected_views: tuple[str, ...] = ()) -> None:
    investment_id = world["investment_id"]
    store.put_memo_draft(
        investment_id,
        memo_fx.memo_draft(
            investment_id,
            selected=memo_fx.project_cell(strategy_id=strategy),
            selected_valuation_timepoint_ids=selected_views,
        ),
        db_path=world["db"],
    )


def _refusals(world: dict[str, Any], strategy: str, **draft: Any) -> list[Any]:
    _draft(world, strategy, **draft)
    investment_id, db = world["investment_id"], world["db"]
    stored = store.get_memo_draft(investment_id, db_path=db)
    assert stored is not None and stored.selected_decision is not None
    return list(
        deps.publication_refusals_for(
            investment_id, stored, deps.dependency_set(investment_id, stored.selected_decision, draft=stored, db_path=db), db_path=db
        )
    )


def _opaque_identities(world: dict[str, Any]) -> tuple[str, ...]:
    """Every opaque identity no analyst-facing refusal may print."""

    return (
        world["a"],
        world["b"],
        world["investment_id"],
        EVIDENCE,
        "event-a",
        "event-b",
        "event-inv",
        "refi-a",
        "refi-b",
        "refi-inv",
        "sen-a",
        "sen-b",
        "sen-inv",
    )


def _gated(world: dict[str, Any], strategy: str) -> Any:
    surface = analyze_structured_valuations(world["investment_id"], strategy, "base", db_path=world["db"])
    blocked = {record.timepoint_id: {unit.unit_id: unit.detail for unit in record.units} for record in surface.evidence_blocked}
    return funding_authority(investment_id=world["investment_id"], views=surface.views, blocked=blocked)


def _client(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(world["db"]))
    return TestClient(api_module.app)


# =============================================================================
# 1. Unit A stays economically correct at exact scope
# =============================================================================


def test_1_unit_a_exact_scope_refinance_is_economically_correct(world: dict[str, Any]) -> None:
    (event,) = analyze_structured_variant(world["investment_id"], world["unit_a"], "base", db_path=world["db"]).result.capital_events
    assert event.status is RefinanceStatus.EXECUTED
    dependency = event.value_dependency
    assert dependency is not None and dependency.timepoint_id == TIMEPOINT
    assert dependency.method is ValuationMethodKind.DIRECT_CAP and dependency.analyst_supplied is False
    assert dependency.valuation_unavailable_reason is None and fx.rf.close(dependency.value, A_VALUE)
    assert fx.rf.close(event.sizing.gross_proceeds, 0.65 * A_VALUE)


# =============================================================================
# 2-3. The temporary Stage 3 report gate, with truthful refusals
# =============================================================================


def test_2_readiness_refuses_every_refinance_bearing_selection_with_the_gate(world: dict[str, Any]) -> None:
    """The gate is stated for every evented structure -- executed, blocked or
    DSCR-only -- and the exact-scope valuation findings are stated beside it."""

    assert [item.code.value for item in _refusals(world, world["unit_a"])] == [GATE]
    assert [item.code.value for item in _refusals(world, world["dscr_a"])] == [GATE]
    assert [item.code.value for item in _refusals(world, world["unit_b"])] == [VALUATION, GATE]
    assert [item.code.value for item in _refusals(world, world["portfolio"])] == [VALUATION, GATE]
    # A structure with no capital event is never gated.
    assert GATE not in [item.code.value for item in _refusals(world, world["pct_a"])]


def test_2_publish_and_preview_enforce_the_same_refusal_and_write_nothing(world: dict[str, Any]) -> None:
    _draft(world, world["unit_a"])
    with pytest.raises(PublicationRefusedError) as published:
        deps.publish(world["investment_id"], db_path=world["db"])
    with pytest.raises(ReportPreviewRefusedError) as previewed:
        assemble_draft_preview(world["investment_id"], db_path=world["db"])
    assert published.value.refusals == previewed.value.refusals
    (refusal,) = previewed.value.refusals
    assert refusal.code.value == GATE and refusal.field == "capital_structure" and refusal.scope_id is None
    assert store.list_memo_versions(world["investment_id"], db_path=world["db"]) == ()


def test_2_the_routes_state_the_gate_in_the_established_refusal_shape(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(world, monkeypatch)
    _draft(world, world["unit_b"])
    investment_id = world["investment_id"]
    readiness = client.get(f"/investments/{investment_id}/memo/publication-readiness").json()
    assert readiness["publishable"] is False
    assert [item["code"] for item in readiness["refusals"]] == [VALUATION, GATE]
    published = client.post(f"/investments/{investment_id}/memo/publish")
    preview = client.get(f"/investments/{investment_id}/memo/report-preview")
    assert published.status_code == preview.status_code == 422
    assert [item["code"] for item in published.json()["detail"]] == [VALUATION, GATE]
    assert preview.json()["detail"] == [readiness["refusals"][-1]]
    assert client.get(f"/investments/{investment_id}/memo-versions").json()["memo_versions"] == []


def test_3_no_refusal_names_an_identity_or_calls_a_refinance_a_funding(world: dict[str, Any]) -> None:
    for strategy in ("unit_a", "unit_b", "portfolio", "dscr_a"):
        for refusal in _refusals(world, world[strategy]):
            text = f"{refusal.message} {refusal.unavailable_reason or ''}"
            for identity in (*_opaque_identities(world), TIMEPOINT):
                assert identity not in text, (strategy, identity, text)
            assert "percentage-of-value" not in text and "PctOfValue" not in text, text
            assert "12,500,000" not in text and "12500000" not in text, text
    (refusal, _) = _refusals(world, world["unit_b"])
    assert "the selected refinance sizes its LTV capacity from it" in refusal.message
    assert "The value required is that of the Unit 'B'." in refusal.message
    assert "The valuation 'Year-2 value'" in refusal.message
    (portfolio, _) = _refusals(world, world["portfolio"])
    assert "The value required is that of the Investment." in portfolio.message


def test_3_a_funding_refusal_keeps_the_accepted_wording_and_names_the_unit(world: dict[str, Any]) -> None:
    (refusal,) = _refusals(world, world["pct_b"])
    assert refusal.code.value == VALUATION and refusal.field == "capital_structure"
    assert "a percentage-of-value funding of the selected variant is sized from it" in refusal.message
    assert "The value required is that of the Unit 'B'." in refusal.message
    for identity in _opaque_identities(world):
        assert identity not in refusal.message, identity


def test_3_both_consumers_of_one_scope_are_named_together(world: dict[str, Any]) -> None:
    """A scope a funding and a refinance both read keeps both provenances."""

    structure = dataclasses.replace(
        store.get_strategy(world["investment_id"], world["unit_b"], db_path=world["db"]).strategy.root_overlays[0].content,
    )
    structure = dataclasses.replace(
        structure,
        positions=(
            *structure.positions,
            dataclasses.replace(
                _senior("sen-pb2", fx.scope(world["b"]), 0.0, PctOfValue(timepoint_id=TIMEPOINT, pct=0.1)), priority=3
            ),
        ),
    )
    both = store.create_strategy(
        world["investment_id"],
        name="Both on B",
        root_overlays=(InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=structure),),
        db_path=world["db"],
    ).strategy.strategy_id
    surface = analyze_structured_valuations(world["investment_id"], both, "base", db_path=world["db"])
    assert [(item.unit_id, item.consumer) for item in surface.consumed_requirements if item.timepoint_id == TIMEPOINT] == [
        (world["b"], ValuationConsumerKind.PCT_OF_VALUE),
        (world["b"], ValuationConsumerKind.REFINANCE_LTV),
    ]
    (refusal,) = [item for item in _refusals(world, both) if item.code.value == VALUATION]
    assert "sizes both a percentage-of-value funding and a refinance's LTV capacity from it" in refusal.message


def test_3_a_unit_whose_record_is_gone_is_named_honestly() -> None:
    assert unit_display_name("no-such-deal", None) == "the selected Unit (no longer available)"


# =============================================================================
# 4. The typed unavailable reason, end to end
# =============================================================================


def test_4_an_evidence_gated_cell_carries_the_typed_reason_end_to_end(world: dict[str, Any]) -> None:
    authority = _gated(world, world["unit_b"])
    valuation = next(item for item in authority.valuations if item.timepoint_id == TIMEPOINT)
    cells = {cell.unit_id: cell for cell in valuation.unit_results}
    blocked, available = cells[world["b"]], cells[world["a"]]
    assert blocked.status is ValuationAvailability.UNAVAILABLE and blocked.value is None
    assert blocked.unavailable_reason is ValuationUnavailableReason.EVIDENCE_NOT_APPROVED
    assert available.status is ValuationAvailability.AVAILABLE and fx.rf.close(available.value, A_VALUE)
    # The Investment is incomplete; its member cell keeps the precise reason.
    assert valuation.value is None and valuation.unavailable_reason is ValuationUnavailableReason.INCOMPLETE_UNITS
    # The P7.10 adapter now represents the cell instead of treating it as impossible.
    state = unit_unavailable(blocked, timepoint_id=TIMEPOINT)
    assert state.reason_code is UnavailableReasonCode.EVIDENCE_NOT_APPROVED
    assert state.valuation_reason is ValuationUnavailableReason.EVIDENCE_NOT_APPROVED
    assert valuation_reason_code(ValuationUnavailableReason.EVIDENCE_NOT_APPROVED) is UnavailableReasonCode.EVIDENCE_NOT_APPROVED

    # The refinance's ValueDependency and the PctOfValue requirement both carry it.
    (event,) = analyze_structured_variant(world["investment_id"], world["unit_b"], "base", db_path=world["db"]).result.capital_events
    assert event.unavailable_reason is RefinanceUnavailableReason.EVIDENCE_NOT_APPROVED
    assert event.value_dependency is not None and event.value_dependency.value is None
    assert event.value_dependency.valuation_unavailable_reason is ValuationUnavailableReason.EVIDENCE_NOT_APPROVED
    structure = store.get_strategy(world["investment_id"], world["pct_b"], db_path=world["db"]).strategy.root_overlays[0].content
    (position,) = structure.positions
    (funding,) = position.funding
    requirement = resolve_valuation_funding(position, funding, funding.amount_rule, authority=_gated(world, world["pct_b"]))
    assert isinstance(requirement, UnresolvedFundingRequirement)
    assert requirement.valuation_reason is ValuationUnavailableReason.EVIDENCE_NOT_APPROVED
    # Unit B's typed amount is absent everywhere a consumer could read it. (Unit
    # A's own direct-cap value happens to be the same number, so B's records
    # are inspected, never the Investment's.)
    assert "12500000" not in repr(blocked) and "12500000" not in repr(event) and "12500000" not in repr(requirement)


def test_4_classification_reads_the_typed_dependency_not_the_blocked_map(world: dict[str, Any]) -> None:
    """With the cell's typed reason removed, the same blocked-Unit facts no
    longer classify the event: the dependency reason is the authority."""

    from anchor.deals import refinance_integration

    analysis = analyze_structured_variant(world["investment_id"], world["unit_b"], "base", db_path=world["db"])
    (event,) = analysis.result.capital_events
    structure = store.get_strategy(world["investment_id"], world["unit_b"], db_path=world["db"]).strategy.root_overlays[0].content
    (authored,) = structure.events
    untyped = dataclasses.replace(
        event, value_dependency=dataclasses.replace(event.value_dependency, valuation_unavailable_reason=None)
    )
    from anchor.deals.valuation_views import EvidenceCause

    authority = _gated(world, world["unit_b"])
    assert refinance_integration._evidence_cause(event, authored, authority) is EvidenceCause.EVIDENCE_ONLY
    assert refinance_integration._evidence_cause(untyped, authored, authority) is EvidenceCause.NONE


# =============================================================================
# 5-8. Exact-scope consumption, published and presented truthfully
# =============================================================================


def _publish(world: dict[str, Any], strategy: str, **draft: Any) -> Any:
    _draft(world, strategy, **draft)
    return deps.publish(world["investment_id"], db_path=world["db"])


def _rows(package: Any) -> list[tuple[str, str, str | None, bool, bool]]:
    return [
        (row.label, row.scope, row.value, row.selected, row.consumed)
        for row in package.valuations
        if not row.system_controlled
    ]


def test_5_a_unit_pct_of_value_publishes_on_its_own_available_cell(world: dict[str, Any]) -> None:
    assert _refusals(world, world["pct_a"]) == []
    version = _publish(world, world["pct_a"])
    consumed = store.list_memo_version_consumed_valuations(world["investment_id"], version.version_id, db_path=world["db"])
    assert [(item.timepoint_id, item.scope_kind.value, item.unit_id, item.consumer) for item in consumed] == [
        (AS_IS, "unit", world["a"], ValuationConsumerKind.PCT_OF_VALUE)
    ]


def test_6_the_report_shows_unit_a_s_cell_never_the_unavailable_investment_view(world: dict[str, Any]) -> None:
    _draft(world, world["pct_a"])
    preview = assemble_draft_preview(world["investment_id"], db_path=world["db"])
    unit_row = ("As-Is", "Unit – A", format_currency(A_VALUE), False, True)
    # Only the consumed Unit cell: the Investment view was neither selected nor consumed.
    assert _rows(preview) == [unit_row]

    version = deps.publish(world["investment_id"], db_path=world["db"])
    frozen = {row.timepoint_id: row for row in version.valuations}
    assert frozen[AS_IS].consumed is False and frozen[AS_IS].value is None  # never claimed as consumed
    artifact = store.get_memo_version_artifact(world["investment_id"], version.version_id, db_path=world["db"])
    assert artifact is not None
    issued = _rows(artifact.package())
    assert unit_row in issued
    # The whole views the version froze are reference rows, never "consumed", never valued.
    assert [row for row in issued if row[1] == "Investment"] == [
        ("As-Is", "Investment", None, False, False),
        ("Year-2 value", "Investment", None, False, False),
    ]
    assert not [row for row in issued if row[2] == format_currency(0.0)]


def test_7_a_selected_whole_view_and_a_consumed_unit_cell_stay_distinct(world: dict[str, Any]) -> None:
    _draft(world, world["pct_a"], selected_views=(AS_IS,))
    preview = assemble_draft_preview(world["investment_id"], db_path=world["db"])
    assert _rows(preview) == [
        ("As-Is", "Investment", None, True, False),
        ("As-Is", "Unit – A", format_currency(A_VALUE), False, True),
    ]
    (whole,) = [row for row in preview.valuations if row.scope == "Investment" and not row.system_controlled]
    assert whole.unavailable is not None and whole.unavailable.reason_code == "evidence_not_approved"


def test_8_an_investment_scope_consumption_requires_and_shows_the_aggregate(world: dict[str, Any]) -> None:
    (refusal,) = _refusals(world, world["pct_inv"])
    assert refusal.code.value == VALUATION and "The value required is that of the Investment." in refusal.message
    _approve(world)
    _draft(world, world["pct_inv"])
    preview = assemble_draft_preview(world["investment_id"], db_path=world["db"])
    total = format_currency(A_VALUE + 12_500_000.0)
    assert _rows(preview) == [("As-Is", "Investment", total, False, True)]
    version = deps.publish(world["investment_id"], db_path=world["db"])
    assert {row.timepoint_id: row.consumed for row in version.valuations} == {AS_IS: True, TIMEPOINT: False}
    consumed = store.list_memo_version_consumed_valuations(world["investment_id"], version.version_id, db_path=world["db"])
    assert [(item.scope_kind.value, item.unit_id) for item in consumed] == [("investment", None)]


# =============================================================================
# 9. The frozen consumption record: owned, typed, fail-closed
# =============================================================================


def _raw(db: Path, sql: str, parameters: tuple[Any, ...] = ()) -> None:
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(sql, parameters)


def test_9_a_version_is_read_only_within_its_own_investment(world: dict[str, Any]) -> None:
    version = _publish(world, world["pct_a"])
    other = create_investment(world["db"], fx.base_deal(world["db"], name="C"), fx.base_deal(world["db"], name="D"))
    with pytest.raises(MemoVersionNotFoundError):
        store.list_memo_version_consumed_valuations(other.id, version.version_id, db_path=world["db"])
    with pytest.raises(MemoVersionNotFoundError):
        store.list_memo_version_consumed_valuations(world["investment_id"], "no-such-version", db_path=world["db"])


@pytest.mark.parametrize(
    "corruption",
    [
        "UPDATE memo_version_consumed_valuations SET consumer_kind = 'appraisal'",
        "UPDATE memo_version_consumed_valuations SET scope_kind = 'portfolio'",
        "UPDATE memo_version_consumed_valuations SET unit_id = ''",
        "UPDATE memo_version_consumed_valuations SET scope_kind = 'investment'",
        "UPDATE memo_version_consumed_valuations SET timepoint_id = 'never-frozen'",
    ],
)
def test_9_a_corrupt_consumption_record_fails_closed(world: dict[str, Any], corruption: str) -> None:
    version = _publish(world, world["pct_a"])
    _raw(world["db"], corruption)
    with pytest.raises(PersistedDealDataError):
        store.list_memo_version_consumed_valuations(world["investment_id"], version.version_id, db_path=world["db"])


def test_9_the_schema_refuses_a_malformed_row_at_write(world: dict[str, Any]) -> None:
    version = _publish(world, world["pct_a"])
    with sqlite3.connect(world["db"]) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO memo_version_consumed_valuations VALUES (?, ?, 'unit', '', 'pct_of_value')",
            (version.version_id, AS_IS),
        )


def test_9_the_record_goes_only_with_the_investment(world: dict[str, Any]) -> None:
    _publish(world, world["pct_a"])
    assert fx.rows(world["db"], "memo_version_consumed_valuations")
    store.delete_investment(world["investment_id"], db_path=world["db"])
    assert fx.rows(world["db"], "memo_version_consumed_valuations") == []
