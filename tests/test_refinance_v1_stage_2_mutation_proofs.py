"""Refinance & Capital Events V1 Stage 2 -- mutation proofs.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 13 to 16 and
18.3. Each mutant is the specific wrong thing a reviewer would worry about in
persistence, identity, fingerprints, staleness and the API -- one exact textual
edit to one real production module -- and is shown to be caught by a named
Stage 2 fixture, not asserted to be impossible.

**How a mutant runs** (the Stage 1 harness, unchanged in method). The module's
own source file in this repository is read (its path is asserted first, so the
known scratch-copy ``pythonpath`` trap cannot run a mutant against another
tree), each edit is applied exactly once, and the result is executed in-process
as a fresh module. Every function and class the mutated module defines is then
patched, for the duration of the proof only, wherever the real one is
referenced -- in the production package and in each Stage 2 test module. The
fixture must pass on the real code, fail under the mutant, and pass again once
it is withdrawn. Nothing is written to the repository.
"""

from __future__ import annotations

import inspect
import os
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

import test_refinance_v1_stage_2_api as api_tests
import test_refinance_v1_stage_2_exact_scope as scope_tests
import test_refinance_v1_stage_2_fingerprints as fingerprint_tests
import test_refinance_v1_stage_2_mixed_cause as mixed_tests
import test_refinance_v1_stage_2_persistence as persistence_tests
import test_refinance_v1_stage_2_reporting_boundary as boundary_tests
import test_refinance_v1_stage_2_strategy_identity as identity_tests
from anchor import api as api_module
from anchor.memo import publication
from anchor.reporting import assembly
from anchor.deals import (
    capital_event_identity,
    fingerprint,
    memo_dependencies,
    refinance_integration,
    store,
    structured_variants,
    valuation_views,
)

_SRC = (Path(__file__).resolve().parents[1] / "src" / "anchor").resolve()


def _referencing_modules() -> tuple[ModuleType, ...]:
    return tuple(
        module
        for name, module in sorted(sys.modules.items())
        if isinstance(module, ModuleType)
        and (
            name == "anchor"
            or name.startswith("anchor.")
            or name.startswith(
                ("test_refinance_v1_stage_2", "_refinance_v1_stage_2", "_refinance_v1_fixtures", "_p7_10_stage_2_fixtures")
            )
        )
    )


def _mutant(module: ModuleType, edits: tuple[tuple[str, str], ...]) -> ModuleType:
    path = Path(module.__file__ or "").resolve()  # type: ignore[arg-type]
    assert path.is_relative_to(_SRC), path
    source = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    for old, new in edits:
        assert source.count(old) == 1, (path.name, old)
        source = source.replace(old, new)
    mutated = ModuleType(module.__name__)
    mutated.__dict__.update({"__file__": module.__file__, "__package__": module.__package__, "__name__": module.__name__})
    exec(compile(source, str(path), "exec"), mutated.__dict__)  # noqa: S102 - a deliberate in-process mutant
    return mutated


def _install(patch: pytest.MonkeyPatch, module: ModuleType, mutated: ModuleType) -> None:
    targets = _referencing_modules()
    assert module in targets
    for name, original in vars(module).items():
        if not (inspect.isfunction(original) or inspect.isclass(original)):
            continue
        if getattr(original, "__module__", None) != module.__name__ or name not in vars(mutated):
            continue
        for target in targets:
            for attribute, value in list(vars(target).items()):
                if value is original:
                    patch.setattr(target, attribute, vars(mutated)[name])


def _killed(monkeypatch: pytest.MonkeyPatch, fixture: Callable[[], None], module: ModuleType, *edits: tuple[str, str]) -> None:
    fixture()
    with monkeypatch.context() as patch:
        _install(patch, module, _mutant(module, edits))
        # A kill is an assertion or pytest's "did not raise"; never an
        # incidental TypeError, ValueError or KeyError.
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            fixture()
    fixture()


def _db() -> Path:
    return Path(tempfile.mkdtemp(prefix="refi-s2-mutant-")) / "anchor.db"


@contextmanager
def _database() -> Iterator[Path]:
    """A fresh database the API reads too, for the duration of one fixture."""

    path = _db()
    previous = os.environ.get("ANCHOR_DB_PATH")
    os.environ["ANCHOR_DB_PATH"] = str(path)
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop("ANCHOR_DB_PATH", None)
        else:
            os.environ["ANCHOR_DB_PATH"] = previous


def _api(test: Callable[[TestClient, Path], None]) -> Callable[[], None]:
    def run() -> None:
        with _database() as db:
            test(TestClient(api_module.app), db)

    return run


def _investment(test: Callable[[Path, dict], None]) -> Callable[[], None]:
    def run() -> None:
        db = _db()
        test(db, fingerprint_tests.build_investment(db))

    return run


def _corruption(name: str) -> Callable[[], None]:
    def run() -> None:
        db = _db()
        persistence_tests.test_every_corruption_fails_closed(db, persistence_tests.save_full(db), name)

    return run


# =============================================================================
# Fingerprints (FP-1, FP-2, R-K)
# =============================================================================


def test_m1_event_payload_omitted_from_a_non_empty_fingerprint_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        fingerprint_tests.test_the_event_payload_joins_only_when_an_event_exists,
        fingerprint,
        ("    if events:\n        payload[_CAPITAL_EVENTS_KEY] = events", "    if False:\n        payload[_CAPITAL_EVENTS_KEY] = events"),
    )


def test_m2_an_empty_event_payload_added_to_an_old_fingerprint_is_killed(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    accepted = fingerprint_tests._probe(fingerprint_tests.extract_accepted_tree(tmp_path_factory.mktemp("m2_accepted")))

    def fixture() -> None:
        assert fingerprint_tests.current_probe() == accepted

    _killed(
        monkeypatch,
        fixture,
        fingerprint,
        ("    if events:\n        payload[_CAPITAL_EVENTS_KEY] = events", "    if True:\n        payload[_CAPITAL_EVENTS_KEY] = events"),
    )


def test_m3_a_label_entering_the_fingerprint_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        fingerprint_tests.test_labels_descriptions_names_and_valuation_labels_are_excluded,
        fingerprint,
        ('        "event_id": event.event_id,\n        "kind": event.kind.value,', '        "event_id": event.event_id,\n        "label": event.label,\n        "kind": event.kind.value,'),
    )


def test_m4_event_row_order_entering_the_fingerprint_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        fingerprint_tests.test_permuting_events_changes_nothing,
        fingerprint,
        ("for event in sorted(capital_structure.events, key=lambda item: item.event_id)", "for event in capital_structure.events"),
    )


def test_m4b_retirement_and_cost_order_entering_the_fingerprint_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        fingerprint_tests.test_permuting_every_collection_changes_nothing,
        fingerprint,
        ("for line in sorted(event.costs, key=lambda item: item.cost_id)", "for line in event.costs"),
    )


# =============================================================================
# Valuation dependencies: LTV only (R-C, R-R, INV-18)
# =============================================================================


def test_m5_a_dscr_only_refinance_consuming_a_valuation_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _investment(fingerprint_tests.test_f13_b_a_dscr_only_refinance_is_invariant_under_every_valuation_change),
        structured_variants,
        ("timepoint_ids=pct_of_value_timepoints(capital_structure)", "timepoint_ids=[view.timepoint_id for view in views]"),
    )


def test_m6_an_ltv_refinance_failing_to_consume_its_valuation_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _investment(fingerprint_tests.test_the_ltv_timepoint_is_consumed_and_the_dscr_structure_consumes_none),
        structured_variants,
        ("for timepoint_id, scope in refinance_valuation_scopes(capital_structure):", "for timepoint_id, scope in ():"),
    )


def test_m6b_an_ltv_identity_blind_to_the_evidence_gate_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        lambda: fingerprint_tests.test_an_unapproved_analyst_value_is_evidence_not_approved_and_approval_moves_the_identity(_db()),
        fingerprint,
        ('"evidence_blocked": scope.unit_id in blocked,', '"evidence_blocked": False,'),
    )


def test_m7_a_stale_cached_result_being_served_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A structured result reused while only the Project identity matches --
    i.e. cached on less than the complete structured fingerprint -- serves the
    pre-change refinance after its LTV valuation moved."""

    _killed(
        monkeypatch,
        _investment(fingerprint_tests.test_f13_a_the_referenced_valuation_change_stales_and_recomputes),
        structured_variants,
        ("_NO_VALUATIONS = _ValuationContext(", "_STALE: dict = {}\n_NO_VALUATIONS = _ValuationContext("),
        (
            "    result = _execute_root(root_kind, read, resolved.capital_structure, valuation.authority)\n    fields = dict(",
            "    result = _STALE.setdefault((investment_id, strategy_id, scenario_id, read.project_source_fingerprint), "
            "_execute_root(root_kind, read, resolved.capital_structure, valuation.authority))\n    fields = dict(",
        ),
    )


def test_m13_the_evidence_gate_reported_as_a_missing_timepoint_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        lambda: fingerprint_tests.test_an_unapproved_analyst_value_is_evidence_not_approved_and_approval_moves_the_identity(_db()),
        refinance_integration,
        (
            "    if cause is EvidenceCause.NONE:\n        return None\n",
            "    if True:\n        return None\n",
        ),
    )


# =============================================================================
# Strategy resolution and P-8 (ST-2, P-6, P-8)
# =============================================================================


def test_m8_strategy_events_patched_onto_the_base_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        lambda: identity_tests.test_f18_a_strategys_evented_structure_replaces_a_base_with_positions_whole(_db()),
        structured_variants,
        (
            "        capital_structure=resolve_capital_structure(base, strategy),",
            "        capital_structure=resolve_capital_structure(base, strategy) if own is None or not hasattr(own, 'events') "
            "else type(own)(positions=(*base.positions, *own.positions), events=own.events),",
        ),
    )


def test_m9_a_scope_conflict_accepted_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        lambda: identity_tests.test_p8_a_scope_conflict_is_refused_when_a_strategy_is_created(_db()),
        capital_event_identity,
        ("        if len(by_scope) > 1:", "        if False:"),
    )


def test_m9b_a_kind_conflict_accepted_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        identity_tests.test_p8_a_kind_conflict_is_reported_by_the_one_rule,
        capital_event_identity,
        ("        if len(by_kind) > 1:", "        if False:"),
    )


def test_m9c_a_lifecycle_path_skipping_event_identity_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        lambda: identity_tests.test_p8_a_scope_conflict_is_refused_when_the_base_is_replaced(_db()),
        store,
        ("    require_coherent_capital_event_identity(stated)\n", "    pass\n"),
    )


# =============================================================================
# Fail-closed decoding (Section 16.1)
# =============================================================================


def test_m10_an_orphaned_persisted_child_ignored_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _corruption("an extra orphaned child row"),
        store,
        (
            "    if orphaned:\n        raise PersistedCapitalStructureDataError(\n            f\"{where} holds retirement",
            "    if False:\n        raise PersistedCapitalStructureDataError(\n            f\"{where} holds retirement",
        ),
    )


def test_m10b_an_orphaned_proceeds_link_ignored_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _corruption("an extra orphaned proceeds link"),
        store,
        ('        if row["funding_event_id"] not in proceeds_rows:', "        if False:"),
    )


# =============================================================================
# Unavailable is not zero (INV-12), and the primary view (R-P)
# =============================================================================


def _function_killed(
    monkeypatch: pytest.MonkeyPatch, fixture: Callable[[], None], module: ModuleType, name: str, *edits: tuple[str, str]
) -> None:
    """One function of a large module, mutated alone. Re-executing all of
    ``anchor.api`` would also rebuild its response models, and a kill caused by
    that would be incidental; here only ``name`` changes."""

    function = getattr(module, name)
    path = Path(inspect.getsourcefile(function) or "").resolve()
    assert path.is_relative_to(_SRC), path
    source = inspect.getsource(function)
    for old, new in edits:
        assert source.count(old) == 1, (name, old)
        source = source.replace(old, new)
    namespace = dict(vars(module))
    exec(compile(source, str(path), "exec"), namespace)  # noqa: S102 - a deliberate in-process mutant
    fixture()
    with monkeypatch.context() as patch:
        patch.setattr(module, name, namespace[name])
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            fixture()
    fixture()


def test_m11_an_unavailable_amount_becoming_zero_on_the_wire_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request body is serialized once, before the mutant exists, so only
    the *response* can be affected by it: an unknowable amount must travel as
    ``null``."""

    import json

    import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]

    template = json.dumps(api_module._wire(fx.evented("__UNIT__", ltv=0.65, dscr=2.0)))

    def fixture() -> None:
        with _database() as db:
            client = TestClient(api_module.app)
            deal = fx.base_deal(db)
            saved = client.put(f"/deals/{deal.id}/capital-structure", json=json.loads(template.replace("__UNIT__", deal.id)))
            assert saved.status_code == 200, saved.text
            body = api_tests._analysis(client, saved.json()["investment_id"])
            (event,) = body["result"]["capital_events"]
            assert event["sizing"]["gross_proceeds"] is None
            assert event["bridge"] is None and event["funding"] is None
            assert event["sizing"]["capacities"][0]["capacity"] is None
            assert body["result"]["common_equity"]["cash_flows"] is None

    _function_killed(
        monkeypatch,
        fixture,
        api_module,
        "_wire",
        ("    return value\n", "    return 0.0 if value is None else value\n"),
    )


def test_m11b_a_withheld_capacity_restated_as_zero_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        lambda: fingerprint_tests.test_an_unapproved_analyst_value_is_evidence_not_approved_and_approval_moves_the_identity(_db()),
        refinance_integration,
        (
            "        replace(capacity, unavailable_reason=stated, unavailable_message=message) if capacity is ltv else capacity",
            "        replace(capacity, unavailable_reason=stated, unavailable_message=message, capacity=0.0) "
            "if capacity is ltv else capacity",
        ),
    )


def test_m12_acquisition_only_returns_made_primary_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _api(api_tests.test_an_executed_refinance_reports_every_typed_result_and_the_primary_view),
        refinance_integration,
        (
            "        primary_equity_namespace=ReturnNamespace.COMMON_EQUITY_AFTER_CAPITAL_STRUCTURE,",
            "        primary_equity_namespace=ReturnNamespace.ACQUISITION_FINANCING_REFERENCE,",
        ),
    )


def test_m12b_an_unavailable_refinance_reported_as_an_available_primary_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _api(api_tests.test_an_unavailable_refinance_reports_null_never_zero_and_is_the_primary_answer),
        refinance_integration,
        ("    available = equity.cash_flows is not None", "    available = True"),
    )


# =============================================================================
# Exact scope (review correction: P7.10 Section 6, R-E; Sections 8.1, 14.1,
# 14.3; F15 and INV-1) and typed propagation (Section 15.3)
# =============================================================================


def _world(test: Callable[[dict], None]) -> Callable[[], None]:
    def run() -> None:
        test(scope_tests.build(_db()))

    return run


def test_m14_whole_timepoint_evidence_withholding_restored_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _world(scope_tests.test_1_a_unit_a_ltv_refinance_executes_beside_a_blocked_unit_b),
        valuation_views,
        (
            "            gated_result(view.result, blocked_units=blocked.get(view.timepoint_id, {})) for view in views\n",
            "            view.result for view in views if view.timepoint_id not in blocked\n",
        ),
    )


def test_m15_whole_timepoint_unit_event_fingerprinting_restored_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _world(scope_tests.test_2_unit_a_is_invariant_under_every_unit_b_change),
        fingerprint,
        ("    if scope.kind is ScopeKind.UNIT:\n        instruction = next(", "    if False:\n        instruction = next("),
    )


def test_m16_timepoint_only_publication_requirements_restored_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _world(scope_tests.test_3_publication_is_not_blocked_by_an_unrelated_units_evidence),
        memo_dependencies,
        ("        if unit_id is None:  # the complete Investment value\n", "        if True:\n"),
    )


def test_m17_string_based_downstream_message_replacement_restored_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The replaced sentence is whatever Stage 1 wrote. Under reworded Stage 1
    prose a string replacement leaves the reworded text in place, which only
    typed reconstruction avoids."""

    def fixture() -> None:
        with monkeypatch.context() as inner:
            scope_tests.test_changing_stage_1_prose_changes_neither_classification_nor_downstream_messages(
                scope_tests.build(_db()), inner
            )

    _killed(
        monkeypatch,
        fixture,
        refinance_integration,
        (
            "        return replace(position, unavailable_message=_position_message(events[event_id], restated[event_id]))",
            "        return replace(position, unavailable_message=(position.unavailable_message or '').replace("
            "next(item for item in result.capital_events if item.event_id == event_id).unavailable_message or '', "
            "restated[event_id].unavailable_message or ''))",
        ),
    )


# =============================================================================
# Typed state, truthful publication and the Stage 3 boundary (second review
# correction)
# =============================================================================


def _boundary(test: Callable[[dict], None]) -> Callable[[], None]:
    """One reporting-boundary fixture on a fresh world, the API reading it too."""

    def run() -> None:
        with _database() as db:
            test(boundary_tests.build_world(db))

    return run


def test_m18_a_withheld_cell_with_a_null_reason_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_4_an_evidence_gated_cell_carries_the_typed_reason_end_to_end),
        valuation_views,
        (
            "        unavailable_reason=ValuationUnavailableReason.EVIDENCE_NOT_APPROVED,\n",
            "        unavailable_reason=None,\n",
        ),
    )


def test_m19_generic_funding_wording_for_a_refinance_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_3_no_refusal_names_an_identity_or_calls_a_refinance_a_funding),
        publication,
        (
            "    if required.reason is RequiredValuationReason.CONSUMED and ValuationConsumerKind.REFINANCE_LTV in consumers:\n",
            "    if False:\n",
        ),
    )


def test_m20_a_raw_unit_id_in_a_refusal_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_3_a_funding_refusal_keeps_the_accepted_wording_and_names_the_unit),
        memo_dependencies,
        (
            '    return "the Investment" if unit_id is None else unit_display_name(unit_id, db_path)\n',
            '    return "the Investment" if unit_id is None else f"Unit {unit_id!r}"\n',
        ),
    )


def test_m21_a_whole_view_shown_as_consumed_in_the_preview_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_6_the_report_shows_unit_a_s_cell_never_the_unavailable_investment_view),
        assembly,
        (
            "    consumed_ids = _whole_view_consumed(surface)\n",
            '    consumed_ids = set(getattr(surface, "consumed_timepoint_ids", ()))\n',
        ),
    )


def test_m21b_a_whole_view_frozen_as_consumed_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_6_the_report_shows_unit_a_s_cell_never_the_unavailable_investment_view),
        memo_dependencies,
        (
            "    consumed = whole_view_consumed_timepoints(surface)\n",
            "    consumed = set(surface.consumed_timepoint_ids)\n",
        ),
    )


def test_m22_an_unexecuted_refinance_published_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refinance V1 Stage 3 re-expression: the temporary gate this mutant once
    removed is gone; its successor, the refusal of a refinance that did not
    execute, is what must not be removable."""

    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_2_readiness_allows_an_executed_refinance_and_refuses_an_unexecuted_one),
        publication,
        (
            "    refusals.extend(refinance_result_refusal(reason) for reason in context.unexecuted_refinances)\n",
            "    pass\n",
        ),
    )


def test_m22b_an_acquisition_only_headline_restored_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refinance V1 Stage 3 re-expression: an executed refinance now previews,
    and restoring the acquisition-loan levered IRR as its headline is killed."""

    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_2_an_executed_refinance_publishes_and_previews_refinance_aware),
        assembly,
        (
            "    if selected is not None and refinance_report.refinance_bearing(analysis.structured):\n",
            "    if False:\n",
        ),
    )


def test_m23_a_cross_investment_consumption_read_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_9_a_version_is_read_only_within_its_own_investment),
        store,
        (
            """            "SELECT 1 FROM investment_memo_versions WHERE version_id = ? AND investment_id = ?",
            (version_id, investment_id),
        ).fetchone() is None:
            raise MemoVersionNotFoundError(investment_id, version_id)
        rows = connection.execute(
            "SELECT * FROM memo_version_consumed_valuations""",
            """            "SELECT 1 FROM investment_memo_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone() is None:
            raise MemoVersionNotFoundError(investment_id, version_id)
        rows = connection.execute(
            "SELECT * FROM memo_version_consumed_valuations""",
        ),
    )


def test_m24_deduplication_erasing_consumer_provenance_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _boundary(boundary_tests.test_3_both_consumers_of_one_scope_are_named_together),
        structured_variants,
        (
            "    found: dict[tuple[str, str, str, str], ValuationRequirement] = {}\n",
            "    found: dict[tuple[str, str, str], ValuationRequirement] = {}  # type: ignore[assignment]\n",
        ),
        ("        found.setdefault(requirement.key(), requirement)\n    return", "        found.setdefault(requirement.scope_key(), requirement)  # type: ignore[arg-type]\n    return"),
        (
            "                found.setdefault(requirement.key(), requirement)\n",
            "                found.setdefault(requirement.scope_key(), requirement)  # type: ignore[arg-type]\n",
        ),
    )


# =============================================================================
# Investment-scope reason precedence (third review correction)
# =============================================================================


def _mixed(test: Callable[[dict], None]) -> Callable[[], None]:
    def run() -> None:
        test(mixed_tests.build_mixed(_db()))

    return run


#: "Any evidence-blocked member makes the whole Investment evidence-not-approved."
_ANY_EVIDENCE_MEMBER = (
    "    return EvidenceCause.EVIDENCE_ONLY if len(evidence) == len(reasons) else EvidenceCause.MIXED\n",
    "    return EvidenceCause.EVIDENCE_ONLY\n",
)


def test_m25_any_evidence_member_relabelling_an_ltv_event_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _mixed(mixed_tests.test_an_investment_ltv_event_is_valuation_unavailable_not_evidence_only),
        valuation_views,
        _ANY_EVIDENCE_MEMBER,
    )


def test_m25b_any_evidence_member_relabelling_a_pct_of_value_funding_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _mixed(mixed_tests.test_an_investment_pct_of_value_follows_the_same_precedence),
        valuation_views,
        _ANY_EVIDENCE_MEMBER,
    )


def test_m26_stale_pre_gate_investment_prose_kept_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _killed(
        monkeypatch,
        _mixed(mixed_tests.test_each_member_cell_keeps_its_own_precise_reason),
        valuation_views,
        ("    if not incomplete:\n        return replace(result, unit_results=cells)\n",
         "    if True:\n        return replace(result, unit_results=cells)\n"),
    )


def test_the_mutation_harness_patches_this_repositorys_modules() -> None:
    for module in (
        fingerprint,
        store,
        structured_variants,
        capital_event_identity,
        refinance_integration,
        valuation_views,
        memo_dependencies,
        api_module,
        publication,
        assembly,
    ):
        assert Path(module.__file__ or "").resolve().is_relative_to(_SRC), module.__name__
