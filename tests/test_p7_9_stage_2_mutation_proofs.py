"""Phase 7 Gate P7.9 Stage 2 -- focused mutation proofs S1-S8.

Each mutant is one specific wrong thing a reviewer would worry about in the
Stage 2 integration, applied in-process to this repository's real modules
(the P7.8B and P7.9 Stage 1 method) and shown to be caught by a named kill
condition. For every mutant: the patched module is asserted to live in this
repository's ``src/anchor``; the kill condition passes before the mutation,
fails under it (inside its own ``MonkeyPatch`` context), and passes again once
it is withdrawn.

| # | Mutant | Invariant |
|---|---|---|
| S1 | a missing participant count reads as the empty set | missing is never "none" |
| S2 | an explicit "no Partnership" resolves as inheritance | three marker states |
| S3 | the fingerprint omits the promote participants | participants are economic |
| S4 | the fingerprint includes ``role`` | role is excluded (FP-1) |
| S5 | a variant with no Partnership gets the structured fingerprint as its key | FP-2 |
| S6 | a non-participant's Promote Earned is reported as 0.0 | N/A, never zero (R-E) |
| S7 | deleting a Strategy leaves its Partnership rows | lifecycle |
| S8 | one Strategy's role labels every matrix cell | per-cell presentation |
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import _p7_9_fixtures as f  # type: ignore[import-not-found]
from _p7_2_fixtures import create_deal, execute, rows  # type: ignore[import-not-found]
from _p7_9_stage_2_fixtures import (  # type: ignore[import-not-found]
    gp_as_lp,
    no_partnership_overlay,
    partnership_overlay,
    structured_deal,
)
from anchor.analysis import strategy as strategy_module
from anchor.decision import comparison
from anchor.deals import fingerprint as fingerprint_module
from anchor.deals import partnership_variants
from anchor.deals import decision_matrix as matrix_module
from anchor.deals import store
from anchor.deals.decision_matrix import analyze_partner_decision_matrix
from anchor.deals.partnership_variants import analyze_partnership_variant, resolve_variant_partnership
from anchor.decision.comparison import FigureReason, PartnerMetric
from anchor.partnership import PartnerRole

_SRC = (Path(__file__).resolve().parents[1] / "src" / "anchor").resolve()


def mutate(monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str, replacement: Any) -> None:
    assert Path(module.__file__).resolve().is_relative_to(_SRC), module.__file__  # type: ignore[arg-type]
    assert hasattr(module, name), name
    monkeypatch.setattr(module, name, replacement)


def killed(
    monkeypatch: pytest.MonkeyPatch, condition: Callable[[], None], module: ModuleType, name: str, replacement: Any
) -> None:
    condition()
    with monkeypatch.context() as patch:
        mutate(patch, module, name, replacement)
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            condition()
    condition()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def _hidden(db: Path, partnership: Any) -> str:
    deal = create_deal("quick", db)
    investment_id = store.create_scenario_for_deal(deal.id, name="S", db_path=db).investment_id
    store.set_base_partnership(investment_id, partnership, db_path=db)
    return investment_id


# =============================================================================
# S1 -- a missing participant set is corrupt, never empty
# =============================================================================


def test_s1_a_missing_participant_count_read_as_empty_is_killed(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    investment_id = _hidden(db, f.f1_terms(participants=()))
    execute(db, "UPDATE partnerships SET promote_participant_count = NULL")

    def refuses() -> None:
        with pytest.raises(store.PersistedPartnershipDataError):
            store.get_base_partnership(investment_id, db_path=db)

    real = store._read_participant_ids

    def lenient(row: Any, participant_rows: Any, *, where: str) -> tuple[str, ...]:
        if row["promote_participant_count"] is None:
            return ()
        return real(row, participant_rows, where=where)

    killed(monkeypatch, refuses, store, "_read_participant_ids", lenient)


# =============================================================================
# S2 -- an explicit "no Partnership" is not inheritance
# =============================================================================


def test_s2_explicit_none_resolved_as_inheritance_is_killed(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())
    none = store.create_strategy(
        investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db
    ).strategy.strategy_id

    def has_none() -> None:
        assert resolve_variant_partnership(investment_id, none, db_path=db).partnership is None
        assert analyze_partnership_variant(investment_id, none, "base", db_path=db).result is None

    def inherits(base: Any, strategy: Any) -> Any:
        own = strategy_module.strategy_partnership(strategy)
        return base if own is None or isinstance(own, strategy_module.NoPartnership) else own

    killed(monkeypatch, has_none, partnership_variants, "resolve_partnership", inherits)


# =============================================================================
# S3, S4 -- the fingerprint's inclusion and exclusion
# =============================================================================


def _digest(partnership: Any) -> str:
    return fingerprint_module.fingerprint_partnership_source(
        structured_source_fingerprint="a" * 64, partnership=partnership
    )


def test_s3_a_fingerprint_without_the_participants_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def participants_move_it() -> None:
        assert _digest(f.f1_terms()) != _digest(f.f1_terms(participants=()))

    real = fingerprint_module.partnership_payload

    def without_participants(partnership: Any) -> dict[str, Any]:
        payload = real(partnership)
        payload.pop("promote_participant_ids")
        return payload

    killed(monkeypatch, participants_move_it, fingerprint_module, "partnership_payload", without_participants)


def test_s4_a_fingerprint_that_reads_role_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def role_does_not_move_it() -> None:
        assert _digest(f.f1_terms()) == _digest(gp_as_lp(f.f1_terms()))

    real = fingerprint_module.partnership_payload

    def with_role(partnership: Any) -> dict[str, Any]:
        payload = real(partnership)
        roles = {partner.partner_id: partner.role.value for partner in partnership.partners}
        for partner in payload["partners"]:
            partner["role"] = roles[partner["partner_id"]]
        return payload

    killed(monkeypatch, role_does_not_move_it, fingerprint_module, "partnership_payload", with_role)


# =============================================================================
# S5 -- no Partnership, no key
# =============================================================================


def test_s5_a_key_for_an_absent_partnership_is_killed(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, investment_id = structured_deal(db)

    def no_key() -> None:
        assert (
            partnership_variants.partnership_variant_fingerprint(
                investment_id, "base", "base", db_path=db
            ).partnership_source_fingerprint
            is None
        )

    real = partnership_variants._partnership_fingerprint

    def always_keyed(structured_source_fingerprint: str, partnership: Any) -> str | None:
        if partnership is None:
            return structured_source_fingerprint
        return real(structured_source_fingerprint, partnership)

    killed(monkeypatch, no_key, partnership_variants, "_partnership_fingerprint", always_keyed)


# =============================================================================
# S6 -- a non-participant's Promote Earned is N/A, never zero
# =============================================================================


def test_s6_zero_promote_for_a_non_participant_is_killed(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, investment_id = structured_deal(db, f.f1_terms())

    def not_applicable() -> None:
        report = analyze_partner_decision_matrix(investment_id, "lp", db_path=db)
        promote = next(v for v in report.matrix.cells[0].metrics if v.metric is PartnerMetric.PROMOTE_EARNED)
        assert promote.value is None and promote.reason is FigureReason.NOT_APPLICABLE_TO_PERSPECTIVE

    real = comparison._partner_metric_value

    def zero_filled(cell: Any, spec: Any) -> Any:
        if spec.metric is PartnerMetric.PROMOTE_EARNED and cell.partner is not None and cell.partner.promote_earned is None:
            return comparison.MetricValue(metric=spec.metric, value=0.0, irr_status=None, reason=None, message=None)
        return real(cell, spec)

    killed(monkeypatch, not_applicable, comparison, "_partner_metric_value", zero_filled)


# =============================================================================
# S7 -- deleting a Strategy removes its Partnership rows
# =============================================================================


def test_s7_orphaned_strategy_partnership_rows_are_killed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = iter(range(3))

    def strategy_rows_go() -> None:
        # A fresh database per run, so a mutant's leftovers never reach the next.
        db = tmp_path / f"s7-{next(runs)}.db"
        investment_id = _hidden(db, f.f1_terms())
        created = store.create_strategy(
            investment_id, name="Own", root_overlays=(partnership_overlay(f.f12_terms()),), db_path=db
        )
        store.delete_strategy(investment_id, created.strategy.strategy_id, db_path=db)
        assert [row[3] for row in rows(db, "partnerships")] == [investment_id]
        assert {row[1] for row in rows(db, "partners")} == {"lp", "gp"}

    real = store._delete_partnership

    def keeps_strategy_rows(connection: Any, owner_kind: str, owner_id: str) -> None:
        if owner_kind == store._STRATEGY_OWNER_KIND:
            return
        real(connection, owner_kind, owner_id)

    killed(monkeypatch, strategy_rows_go, store, "_delete_partnership", keeps_strategy_rows)


# =============================================================================
# S8 -- every cell is described by its own Partnership
# =============================================================================


def test_s8_one_strategys_role_labelling_every_cell_is_killed(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``partner_id`` may be the GP under one Strategy and an LP under the
    next (P-8: the id is the identity). A matrix that labelled every cell from
    one Partnership would mislabel the others."""

    _, investment_id = structured_deal(db, f.f1_terms())
    recast = store.create_strategy(
        investment_id,
        name="GP as LP",
        root_overlays=(partnership_overlay(gp_as_lp(f.f1_terms())),),
        db_path=db,
    ).strategy.strategy_id

    def each_cell_states_its_own() -> None:
        report = analyze_partner_decision_matrix(investment_id, "gp", db_path=db)
        described = {cell.strategy_id: cell.partner_role for cell in report.matrix.cells}
        assert described["base"] is PartnerRole.GP
        assert described[recast] is PartnerRole.LP

    real = matrix_module._partner_cell

    def labelled_from_the_base(
        investment: str, strategy_id: str, scenario_id: str, partner_id: str, db_path: object
    ) -> object:
        cell = real(investment, strategy_id, scenario_id, partner_id, db_path)  # type: ignore[arg-type]
        if cell.partner_role is None:
            return cell
        return dataclasses.replace(cell, partner_role=PartnerRole.GP)

    killed(monkeypatch, each_cell_states_its_own, matrix_module, "_partner_cell", labelled_from_the_base)


def test_every_mutant_targets_a_real_function() -> None:
    for module, name in (
        (store, "_read_participant_ids"),
        (partnership_variants, "resolve_partnership"),
        (fingerprint_module, "partnership_payload"),
        (partnership_variants, "_partnership_fingerprint"),
        (comparison, "_partner_metric_value"),
        (store, "_delete_partnership"),
        (matrix_module, "_partner_cell"),
    ):
        assert callable(getattr(module, name)), name
        assert Path(module.__file__).resolve().is_relative_to(_SRC)  # type: ignore[arg-type]
