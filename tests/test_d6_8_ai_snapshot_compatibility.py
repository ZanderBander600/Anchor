"""Phase 6 Gate D6.8 -- AI snapshot compatibility (gate Parts Y, Z and AL).

D6.8 changes what the AI Analyst is told without changing any deal input, so a
report generated before it still matches its deal's fingerprint exactly. The
AI snapshot version is what retires it: ``_AI_SNAPSHOT_SCHEMA_VERSION`` moved
from 1 to 2, and only ``ai_snapshot`` carries it.

A pre-D6.8 report is produced here the way a pre-D6.8 build produced one -- the
same writer and the same provenance fingerprint, under the version that build
wrote (1, read out of 7f52b9e itself) -- and then read by this build.

Proven:

- Part Z: same deal, same fingerprint, old report stale; a regenerated report
  is current.
- The version moves no deterministic snapshot: the analysis snapshot and both
  sensitivity snapshots stay current.
- Part AL: within one version an exact revert restores a report; across the
  version it does not.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from anchor.ai.contracts import AIAnalysis, DealStory
from anchor.analysis.contracts import OneWaySensitivityResult, TwoWaySensitivityResult
from anchor.business_plan import BusinessPlan
from anchor.deals import store as deals_store
from anchor.deals.contracts import (
    OneWaySensitivityConfiguration,
    OneWaySensitivitySnapshot,
    TwoWaySensitivityConfiguration,
    TwoWaySensitivitySnapshot,
)
from anchor.deals.fingerprint import fingerprint_ai

from _d6_5_fixtures import (  # type: ignore[import-not-found]
    MATERIAL,
    MODES,
    analysis_envelope,
    analysis_snapshot_payload,
    create,
    input_fingerprint,
    update,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_D6_5_MERGE = "7f52b9e"
_TABLES = {"quick": "deals", "detailed": "detailed_deals", "lease_level": "lease_level_deals"}


def _version_at(commit: str, name: str) -> int:
    """A snapshot-version constant as ``commit`` shipped it. ``git show`` reads
    objects only; the index is never touched."""

    source = subprocess.run(
        ["git", "show", f"{commit}:src/anchor/deals/store.py"],
        capture_output=True,
        check=True,
        cwd=_PROJECT_ROOT,
    ).stdout.decode("utf-8")
    (value,) = re.findall(rf"^{name} = (\d+)$", source, re.M)
    return int(value)


#: The AI snapshot version every build through D6.5 wrote.
PRE_D6_8_AI_SNAPSHOT_VERSION = _version_at(_D6_5_MERGE, "_AI_SNAPSHOT_SCHEMA_VERSION")

REPORT = AIAnalysis(
    executive_summary="A stabilised asset.",
    investment_view="Proceed subject to diligence.",
    strengths=("Coverage.",),
    risks=("Exit cap.",),
    return_drivers=("Exit cap rate.",),
    downside_analysis="Coverage holds.",
    capital_structure_analysis="Modest leverage.",
    break_even_analysis="Break-even cushion.",
    questions_to_investigate=("Confirm rents.",),
    confidence_notes=("Assumptions unverified.",),
    deal_story=DealStory(
        investment_view="Income-led.",
        key_strengths=("Coverage.",),
        key_risks=("Exit cap.",),
        model_gap=None,
    ),
)
ONE_WAY = OneWaySensitivitySnapshot(
    configuration=OneWaySensitivityConfiguration(
        metric="levered_irr", assumption="exit_cap_rate", values=("6.5", "7")
    ),
    result=OneWaySensitivityResult(
        assumption="exit_cap_rate",
        metric="levered_irr",
        baseline_assumption_value=0.065,
        baseline_metric_value=0.11,
        assumption_values=(0.065, 0.07),
        metric_values=(0.11, None),
    ),
)
TWO_WAY = TwoWaySensitivitySnapshot(
    configuration=TwoWaySensitivityConfiguration(
        metric="equity_multiple",
        row_assumption="exit_cap_rate",
        row_values=("6.5", "7"),
        column_assumption="purchase_price",
        column_values=("6000000",),
    ),
    result=TwoWaySensitivityResult(
        row_assumption="exit_cap_rate",
        column_assumption="purchase_price",
        metric="equity_multiple",
        baseline_row_value=0.065,
        baseline_column_value=6_000_000.0,
        baseline_metric_value=1.7,
        row_values=(0.065, 0.07),
        column_values=(6_000_000.0,),
        matrix=((1.7,), (1.6,)),
    ),
)

#: Plan B: plan A with one capital amount edited -- a real financial change.
PLAN_B = dataclasses.replace(
    MATERIAL,
    capital_items=(
        dataclasses.replace(MATERIAL.capital_items[0], amount=1_250_000.0),
        *MATERIAL.capital_items[1:],
    ),
)


def as_dict(value: Any) -> dict[str, Any]:
    return json.loads(json.dumps(dataclasses.asdict(value)))


def ai_fingerprint(mode: str, business_plan: BusinessPlan) -> str:
    return fingerprint_ai(
        analysis_fingerprint=input_fingerprint(mode, business_plan), deal_context=None
    )


def write_report(deal_id: str, db: Path, mode: str, business_plan: BusinessPlan):
    return deals_store.update_ai_snapshot(
        deal_id,
        as_dict(REPORT),
        ai_context_fingerprint=ai_fingerprint(mode, business_plan),
        db_path=db,
    )


def write_report_as_a_pre_d6_8_build(
    monkeypatch: pytest.MonkeyPatch, deal_id: str, db: Path, mode: str, business_plan: BusinessPlan
) -> None:
    """The same writer and the same fingerprint, under the version a pre-D6.8
    build wrote. It was current for the build that wrote it."""

    with monkeypatch.context() as patched:
        patched.setattr(deals_store, "_AI_SNAPSHOT_SCHEMA_VERSION", PRE_D6_8_AI_SNAPSHOT_VERSION)
        written = write_report(deal_id, db, mode, business_plan)
        assert written.ai_snapshot == REPORT
    assert deals_store._AI_SNAPSHOT_SCHEMA_VERSION != PRE_D6_8_AI_SNAPSHOT_VERSION


def stored_report_row(db: Path, mode: str, deal_id: str) -> tuple[str, int]:
    connection = sqlite3.connect(db)
    try:
        return connection.execute(
            f"SELECT ai_snapshot_fingerprint, ai_snapshot_schema_version "
            f"FROM {_TABLES[mode]} WHERE id = ?",
            (deal_id,),
        ).fetchone()
    finally:
        connection.close()


# =============================================================================
# The version itself
# =============================================================================


def test_only_the_ai_snapshot_version_moved_since_d6_5() -> None:
    assert PRE_D6_8_AI_SNAPSHOT_VERSION == 1
    assert deals_store._AI_SNAPSHOT_SCHEMA_VERSION == PRE_D6_8_AI_SNAPSHOT_VERSION + 1
    assert deals_store._ANALYSIS_SNAPSHOT_SCHEMA_VERSION == _version_at(
        _D6_5_MERGE, "_ANALYSIS_SNAPSHOT_SCHEMA_VERSION"
    )
    assert deals_store._SENSITIVITY_SNAPSHOT_SCHEMA_VERSION == _version_at(
        _D6_5_MERGE, "_SENSITIVITY_SNAPSHOT_SCHEMA_VERSION"
    )


# =============================================================================
# Part Z
# =============================================================================


@pytest.mark.parametrize("business_plan", [BusinessPlan(), MATERIAL], ids=["empty-plan", "material-plan"])
@pytest.mark.parametrize("mode", MODES)
def test_z_a_pre_d6_8_report_is_stale_though_its_fingerprint_still_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, business_plan: BusinessPlan
) -> None:
    db = tmp_path / "z.db"
    deal = create(mode, db, business_plan=business_plan)

    # 1-2. A deal and a report stored by a pre-D6.8 build.
    write_report_as_a_pre_d6_8_build(monkeypatch, deal.id, db, mode, business_plan)

    # 3-4. This build; the same inputs and the same fingerprint -- recomputed
    # now, and the one stored beside the report.
    stored_fingerprint, stored_version = stored_report_row(db, mode, deal.id)
    assert stored_version == PRE_D6_8_AI_SNAPSHOT_VERSION
    assert stored_fingerprint == ai_fingerprint(mode, business_plan)

    # 5. The old report is unavailable.
    reopened = deals_store.get_deal(deal.id, db_path=db)
    assert reopened.business_plan == business_plan
    assert reopened.ai_snapshot is None

    # 6-7. A report generated now is current.
    regenerated = write_report(deal.id, db, mode, business_plan)
    assert regenerated.ai_snapshot == REPORT
    assert deals_store.get_deal(deal.id, db_path=db).ai_snapshot == REPORT
    assert stored_report_row(db, mode, deal.id) == (
        ai_fingerprint(mode, business_plan),
        deals_store._AI_SNAPSHOT_SCHEMA_VERSION,
    )


@pytest.mark.parametrize("mode", ("quick", "detailed"))
def test_the_ai_version_leaves_the_analysis_snapshot_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    db = tmp_path / "analysis.db"
    deal = create(mode, db, business_plan=MATERIAL)
    deals_store.update_analysis_snapshot(
        deal.id,
        analysis_snapshot_payload(mode, MATERIAL),
        financial_input_fingerprint=input_fingerprint(mode, MATERIAL),
        db_path=db,
    )
    write_report_as_a_pre_d6_8_build(monkeypatch, deal.id, db, mode, MATERIAL)

    reopened = deals_store.get_deal(deal.id, db_path=db)

    assert reopened.ai_snapshot is None
    assert reopened.analysis_snapshot == analysis_envelope(mode, MATERIAL)


def test_the_ai_version_leaves_both_sensitivity_snapshots_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "sensitivity.db"
    mode = "lease_level"
    deal = create(mode, db, business_plan=MATERIAL)
    for writer, snapshot in (
        (deals_store.update_one_way_sensitivity_snapshot, ONE_WAY),
        (deals_store.update_two_way_sensitivity_snapshot, TWO_WAY),
    ):
        writer(
            deal.id,
            as_dict(snapshot),
            financial_input_fingerprint=input_fingerprint(mode, MATERIAL),
            db_path=db,
        )
    write_report_as_a_pre_d6_8_build(monkeypatch, deal.id, db, mode, MATERIAL)

    reopened = deals_store.get_deal(deal.id, db_path=db)

    assert reopened.ai_snapshot is None
    assert reopened.one_way_sensitivity_snapshot == ONE_WAY
    assert reopened.two_way_sensitivity_snapshot == TWO_WAY


# =============================================================================
# Part AL
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_al_within_d6_8_an_exact_revert_restores_the_report(tmp_path: Path, mode: str) -> None:
    db = tmp_path / "revert.db"
    deal = create(mode, db, business_plan=MATERIAL)
    write_report(deal.id, db, mode, MATERIAL)
    assert deals_store.get_deal(deal.id, db_path=db).ai_snapshot == REPORT

    assert update(mode, deal.id, db, business_plan=PLAN_B).ai_snapshot is None
    assert update(mode, deal.id, db, business_plan=MATERIAL).ai_snapshot == REPORT


@pytest.mark.parametrize("mode", MODES)
def test_al_across_the_version_an_exact_revert_does_not_restore_a_pre_d6_8_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    db = tmp_path / "revert-across.db"
    deal = create(mode, db, business_plan=MATERIAL)
    write_report_as_a_pre_d6_8_build(monkeypatch, deal.id, db, mode, MATERIAL)

    assert update(mode, deal.id, db, business_plan=PLAN_B).ai_snapshot is None
    reverted = update(mode, deal.id, db, business_plan=MATERIAL)

    assert reverted.ai_snapshot is None
    # Only the version holds it back: the stored fingerprint is plan A's again.
    assert stored_report_row(db, mode, deal.id)[0] == ai_fingerprint(mode, MATERIAL)


@pytest.mark.parametrize("mode", MODES)
def test_duplicating_a_deal_does_not_carry_a_pre_d6_8_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    db = tmp_path / "duplicate.db"
    deal = create(mode, db, business_plan=MATERIAL)
    write_report_as_a_pre_d6_8_build(monkeypatch, deal.id, db, mode, MATERIAL)

    copy = deals_store.duplicate_deal(deal.id, db_path=db)

    assert copy.business_plan == MATERIAL
    assert copy.ai_snapshot is None
