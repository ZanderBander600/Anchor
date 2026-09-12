"""D5.8A -- a completed analytical result belongs to the Deal that produced it.

Human review found two product-state defects: a Lease-Level AI report and a
Lease-Level sensitivity run both vanished when the analyst opened another deal
and came back. Navigation is not an underwriting change, so neither should have.

This file is the persistence half of the fix. It proves, at the repository
layer:

* the latest successful AI report and the latest successful one-way and two-way
  sensitivity runs are **durable** -- they survive a reload, a fresh service
  instance, and a fresh process;
* each is bound to the exact underwriting state that produced it, through the
  existing canonical D5.4 fingerprint, so a stale one is never handed back as
  current;
* the three are **independent** -- writing one never disturbs another;
* a **failure** never destroys a good snapshot;
* duplication does not inherit them and deletion removes them.

The frontend half -- deal switching, refresh, the Generate/Regenerate control
and the product-language polish -- lives in
``web/src/leaseLevelAnalysisPersistence.test.tsx``.

**No fake restore anywhere.** Nothing here re-runs an analysis to produce a
restored value. Every restored artifact is compared to the exact object that was
stored, by ``==`` on frozen dataclasses, which is exact for every float it
holds.
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from anchor.ai.contracts import AIAnalysis, DealStory
from anchor.analysis.contracts import OneWaySensitivityResult, TwoWaySensitivityResult
from anchor.contracts import OperatingMode, UnsupportedOperatingModeError
from anchor.deals import store as deals_store
from anchor.deals.contracts import (
    OneWaySensitivityConfiguration,
    OneWaySensitivitySnapshot,
    TwoWaySensitivityConfiguration,
    TwoWaySensitivitySnapshot,
)
from anchor.deals.fingerprint import fingerprint_ai, fingerprint_lease_level_inputs
from anchor.deals.store import SnapshotValidationError

from tests.test_d5_4_lease_level_persistence import (
    LEASES,
    MARKET_LEASING,
    OPERATING_INPUTS,
    PROPERTY_INPUTS,
    SUITES,
    TERMS,
    store_deal,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "d5-8a.db"


def fresh_store_module():
    """A genuinely independent instance of the store module.

    Executed from source under its own name, so ``sys.modules`` is left exactly
    as it was and every class identity the rest of the suite depends on is
    untouched. ``importlib.reload`` would have been shorter and wrong: it
    replaces ``SnapshotValidationError`` itself, so a later ``pytest.raises``
    would be watching for a class the code no longer raises.

    The name is placed inside ``anchor.deals`` so the module's relative imports
    resolve exactly as they do in production.
    """

    location = _SRC_DIR / "anchor" / "deals" / "store.py"
    spec = importlib.util.spec_from_file_location(
        "anchor.deals._d5_8a_fresh_store", location
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =============================================================================
# Fixtures -- the three analytical artifacts
#
# Each is deliberately awkward: a ``None`` metric that must not become a zero, a
# candidate order that is not sorted, a non-square matrix that cannot survive a
# transpose unnoticed, and an AI report carrying its optional nested Deal Story.
# =============================================================================

AI_ANALYSIS = AIAnalysis(
    executive_summary="A stabilised asset with staggered rollover.",
    investment_view="Proceed, subject to diligence on the 2028 expiry.",
    strengths=("Staggered expiries limit any single-year rollover.",),
    risks=("Year 1 levered cash flow is negative on lease-up capital.",),
    return_drivers=("Exit cap rate is the dominant driver.",),
    downside_analysis="Coverage holds above the supplied hurdle throughout.",
    capital_structure_analysis="Modest leverage with two interest-only years.",
    break_even_analysis="Break-even was not supplied for this analysis.",
    questions_to_investigate=("Confirm the market rent against comparables.",),
    confidence_notes=("No standardized sensitivity bundle was supplied.",),
    deal_story=DealStory(
        investment_view="Income-led, with the exit carrying the balance.",
        key_strengths=("Durable in-place coverage.",),
        key_risks=("Exit cap sensitivity.",),
        model_gap=None,
    ),
)

#: Candidate values in the analyst's order, which is deliberately NOT sorted --
#: a restore that quietly sorted them would change which row is which.
ONE_WAY_VALUES = ("6.75", "6.25", "6.5", "5.75", "7")

ONE_WAY = OneWaySensitivitySnapshot(
    configuration=OneWaySensitivityConfiguration(
        metric="levered_irr",
        assumption="exit_cap_rate",
        values=ONE_WAY_VALUES,
    ),
    result=OneWaySensitivityResult(
        assumption="exit_cap_rate",
        metric="levered_irr",
        baseline_assumption_value=0.065,
        baseline_metric_value=0.1183456789012345,
        assumption_values=(0.0675, 0.0625, 0.065, 0.0575, 0.07),
        # The third entry is ``None``: the scenario was fully underwritten and
        # the metric is not uniquely defined for it. It is not a zero, not an
        # error and not a skipped cell, and no serialization step may make it
        # one.
        metric_values=(0.1044, 0.1327, None, 0.1701, 0.0912),
    ),
)

#: 3 rows x 2 columns. Non-square on purpose: a transpose in either direction
#: would be a shape error rather than a silent reorientation.
TWO_WAY = TwoWaySensitivitySnapshot(
    configuration=TwoWaySensitivityConfiguration(
        metric="equity_multiple",
        row_assumption="exit_cap_rate",
        row_values=("6.75", "6.25", "6.5"),
        column_assumption="purchase_price",
        column_values=("52000000", "48000000"),
    ),
    result=TwoWaySensitivityResult(
        row_assumption="exit_cap_rate",
        column_assumption="purchase_price",
        metric="equity_multiple",
        baseline_row_value=0.065,
        baseline_column_value=50_000_000.0,
        baseline_metric_value=1.7512345678901234,
        row_values=(0.0675, 0.0625, 0.065),
        column_values=(52_000_000.0, 48_000_000.0),
        matrix=(
            (1.61, 1.83),
            (1.72, 1.95),
            (None, 1.89),
        ),
    ),
)


def as_dict(value: Any) -> dict[str, Any]:
    """The payload shape every writer takes: a plain dict, exactly as the JSON a
    prior response produced would decode to."""

    return json.loads(json.dumps(dataclasses.asdict(value)))


def input_fingerprint(**overrides: Any) -> str:
    parts: dict[str, Any] = {
        "terms": TERMS,
        "property_inputs": PROPERTY_INPUTS,
        "suites": SUITES,
        "leases": LEASES,
        "market_leasing": MARKET_LEASING,
        "operating_inputs": OPERATING_INPUTS,
    }
    parts.update(overrides)
    return fingerprint_lease_level_inputs(
        parts["terms"],
        parts["property_inputs"],
        parts["suites"],
        parts["leases"],
        market_leasing=parts["market_leasing"],
        operating_inputs=parts["operating_inputs"],
    )


def ai_fingerprint(deal_context: str | None = None, **overrides: Any) -> str:
    return fingerprint_ai(
        analysis_fingerprint=input_fingerprint(**overrides), deal_context=deal_context
    )


def store_all(db: Path, **deal_overrides: Any):
    """One saved Lease-Level deal carrying all three analytical artifacts."""

    deal = store_deal(db, **deal_overrides)
    context = deal_overrides.get("deal_context")
    deals_store.update_ai_snapshot(
        deal.id,
        as_dict(AI_ANALYSIS),
        ai_context_fingerprint=ai_fingerprint(context),
        db_path=db,
    )
    deals_store.update_one_way_sensitivity_snapshot(
        deal.id,
        as_dict(ONE_WAY),
        financial_input_fingerprint=input_fingerprint(),
        db_path=db,
    )
    return deals_store.update_two_way_sensitivity_snapshot(
        deal.id,
        as_dict(TWO_WAY),
        financial_input_fingerprint=input_fingerprint(),
        db_path=db,
    )


# =============================================================================
# 1-4, 7-8. The AI report is persisted, and belongs to one deal in one mode
# =============================================================================


def test_1_a_successful_lease_level_ai_report_is_persisted(db: Path) -> None:
    """**Required test 1, and M1.**

    Before this gate ``update_ai_snapshot`` looked in ``deals`` and then
    ``detailed_deals`` and raised ``DealNotFoundError`` for a Lease-Level id --
    so the report existed only in React state and could not survive anything.
    """

    deal = store_deal(db)
    updated = deals_store.update_ai_snapshot(
        deal.id,
        as_dict(AI_ANALYSIS),
        ai_context_fingerprint=ai_fingerprint(),
        db_path=db,
    )

    assert updated.ai_snapshot == AI_ANALYSIS


def test_2_and_3_the_report_is_bound_to_this_deal_and_this_mode(db: Path) -> None:
    """**Required tests 2 and 3.** The mode is not a stored discriminator that
    could disagree with anything: the row lives in ``lease_level_deals``, which
    is what makes it a Lease-Level report."""

    deal = store_all(db)
    reloaded = deals_store.get_deal(deal.id, db_path=db)

    assert reloaded.id == deal.id
    assert reloaded.operating_mode is OperatingMode.LEASE_LEVEL
    assert reloaded.ai_snapshot == AI_ANALYSIS

    connection = sqlite3.connect(db)
    stored = connection.execute(
        "SELECT ai_snapshot FROM lease_level_deals WHERE id = ?", (deal.id,)
    ).fetchone()
    connection.close()
    assert stored is not None and stored[0] is not None


def test_4_the_source_fingerprint_is_persisted_beside_every_artifact(db: Path) -> None:
    """**Required test 4, and M5.** Without a stored fingerprint there is no
    staleness check to perform, so the columns are asserted directly rather than
    only through the behaviour they enable."""

    deal = store_all(db)

    connection = sqlite3.connect(db)
    stored_fingerprint, version = connection.execute(
        "SELECT ai_snapshot_fingerprint, ai_snapshot_schema_version "
        "FROM lease_level_deals WHERE id = ?",
        (deal.id,),
    ).fetchone()
    rows = connection.execute(
        "SELECT analysis_kind, source_fingerprint, schema_version "
        "FROM deal_sensitivity_snapshots WHERE deal_id = ? ORDER BY analysis_kind",
        (deal.id,),
    ).fetchall()
    connection.close()

    assert stored_fingerprint == ai_fingerprint()
    assert version == 1
    assert [row[0] for row in rows] == ["one_way", "two_way"]
    assert all(row[1] == input_fingerprint() for row in rows)
    assert all(row[2] == 1 for row in rows)


def test_7_a_fresh_repository_instance_restores_every_artifact(db: Path) -> None:
    """**Required tests 7, 22 and 36 -- the durability claim itself.**

    A browser refresh, a second service instance and an application restart are
    all the same question at this layer: does the artifact come back when
    nothing is holding it in memory? ``deals_store`` opens a short-lived
    connection per call and caches nothing, so re-importing the module is a
    genuinely fresh instance rather than a warm one wearing a new name.
    """

    deal = store_all(db)

    restored = fresh_store_module().get_deal(deal.id, db_path=db)

    assert restored.ai_snapshot == AI_ANALYSIS
    assert restored.one_way_sensitivity_snapshot == ONE_WAY
    assert restored.two_way_sensitivity_snapshot == TWO_WAY


def test_a_separate_process_restores_every_artifact(db: Path) -> None:
    """**The application-restart test, done for real.**

    A fresh interpreter shares no module state, no connection and no cache with
    this one, so anything it can read came off disk.
    """

    deal = store_all(db)

    environment = os.environ.copy()
    parts = [str(_SRC_DIR), str(_PROJECT_ROOT)]
    if existing := environment.get("PYTHONPATH"):
        parts.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(parts)

    program = (
        "import json;"
        "from pathlib import Path;"
        "from anchor.deals import store;"
        f"deal = store.get_deal({deal.id!r}, db_path=Path({str(db)!r}));"
        "print(json.dumps({"
        "'ai': deal.ai_snapshot.executive_summary,"
        "'one_way': list(deal.one_way_sensitivity_snapshot.result.metric_values),"
        "'two_way': [list(row) for row in deal.two_way_sensitivity_snapshot.result.matrix],"
        "'values': list(deal.one_way_sensitivity_snapshot.configuration.values),"
        "}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, env=environment
    )
    assert completed.returncode == 0, completed.stderr.decode()
    payload = json.loads(completed.stdout.decode())

    assert payload["ai"] == AI_ANALYSIS.executive_summary
    assert payload["one_way"] == list(ONE_WAY.result.metric_values)
    assert payload["two_way"] == [list(row) for row in TWO_WAY.result.matrix]
    assert payload["values"] == list(ONE_WAY_VALUES)


# =============================================================================
# 5, 6, 46. Deals do not see each other's analysis
# =============================================================================


def test_5_and_6_and_46_two_deals_keep_their_own_analysis(db: Path) -> None:
    """**Required tests 5, 6 and 46, and M4.**

    "Deal A -> Deal B -> Deal A" is, at this layer, exactly "read A, read B,
    read A" -- the store is what the frontend re-fetches on every open, so if it
    keeps them apart, no navigation can mix them.
    """

    deal_a = store_all(db, name="Deal A")
    deal_b = store_deal(db, name="Deal B")

    assert deals_store.get_deal(deal_a.id, db_path=db).ai_snapshot == AI_ANALYSIS
    # Deal B has run nothing. Every slot is empty -- not "left over from A".
    b = deals_store.get_deal(deal_b.id, db_path=db)
    assert b.ai_snapshot is None
    assert b.one_way_sensitivity_snapshot is None
    assert b.two_way_sensitivity_snapshot is None
    # And returning to A finds A's work exactly as it was left.
    a = deals_store.get_deal(deal_a.id, db_path=db)
    assert a.ai_snapshot == AI_ANALYSIS
    assert a.one_way_sensitivity_snapshot == ONE_WAY
    assert a.two_way_sensitivity_snapshot == TWO_WAY


def test_a_second_deal_s_analysis_never_overwrites_the_first(db: Path) -> None:
    """Two deals, both analyzed, with different results. Neither row is keyed on
    anything global."""

    deal_a = store_all(db, name="Deal A")
    deal_b = store_deal(db, name="Deal B")

    other = dataclasses.replace(AI_ANALYSIS, executive_summary="A different deal.")
    deals_store.update_ai_snapshot(
        deal_b.id,
        as_dict(other),
        ai_context_fingerprint=ai_fingerprint(),
        db_path=db,
    )

    assert deals_store.get_deal(deal_a.id, db_path=db).ai_snapshot == AI_ANALYSIS
    assert deals_store.get_deal(deal_b.id, db_path=db).ai_snapshot == other


# =============================================================================
# 9, 10, 11, 27, 41. Staleness -- the fingerprint decides, nothing else
# =============================================================================


def _edited_terms():
    return dataclasses.replace(TERMS, purchase_price=51_000_000.0)


def test_10_and_M20_an_underwriting_edit_invalidates_every_artifact(db: Path) -> None:
    """**Required tests 10, 27 and 41, and M20.**

    One field, changed once. Everything downstream stops being presented as
    current, with no separate invalidation step: the fingerprint recomputed on
    read simply stops matching the fingerprint that was stored.
    """

    deal = store_all(db)
    deals_store.update_lease_level_deal(
        deal.id,
        deal.name,
        _edited_terms(),
        PROPERTY_INPUTS,
        OPERATING_INPUTS,
        MARKET_LEASING,
        SUITES,
        LEASES,
        db_path=db,
    )

    edited = deals_store.get_deal(deal.id, db_path=db)
    assert edited.ai_snapshot is None
    assert edited.one_way_sensitivity_snapshot is None
    assert edited.two_way_sensitivity_snapshot is None


def test_9_and_M6_and_M7_a_mismatched_fingerprint_is_never_restored(db: Path) -> None:
    """**Required tests 9, 27, 41 and mutants M6/M7.**

    Structural, not behavioural: the stored fingerprint is corrupted in the
    database directly, leaving the payload itself perfectly readable. If the
    check were removed, the snapshot would decode and be returned; because it is
    there, all three come back absent.
    """

    deal = store_all(db)

    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE lease_level_deals SET ai_snapshot_fingerprint = 'not-the-fingerprint' "
        "WHERE id = ?",
        (deal.id,),
    )
    connection.execute(
        "UPDATE deal_sensitivity_snapshots SET source_fingerprint = 'not-the-fingerprint' "
        "WHERE deal_id = ?",
        (deal.id,),
    )
    connection.commit()
    connection.close()

    stale = deals_store.get_deal(deal.id, db_path=db)
    assert stale.ai_snapshot is None
    assert stale.one_way_sensitivity_snapshot is None
    assert stale.two_way_sensitivity_snapshot is None


def test_11_reverting_to_the_original_assumptions_restores_the_analysis(db: Path) -> None:
    """**Required test 11 -- and the reason a stale snapshot is not deleted.**

    Edit, then undo. The snapshot was never destroyed by the edit; it stopped
    matching, and it matches again. Nothing is recomputed to bring it back.
    """

    deal = store_all(db)
    deals_store.update_lease_level_deal(
        deal.id,
        deal.name,
        _edited_terms(),
        PROPERTY_INPUTS,
        OPERATING_INPUTS,
        MARKET_LEASING,
        SUITES,
        LEASES,
        db_path=db,
    )
    assert deals_store.get_deal(deal.id, db_path=db).ai_snapshot is None

    deals_store.update_lease_level_deal(
        deal.id,
        deal.name,
        TERMS,
        PROPERTY_INPUTS,
        OPERATING_INPUTS,
        MARKET_LEASING,
        SUITES,
        LEASES,
        db_path=db,
    )

    reverted = deals_store.get_deal(deal.id, db_path=db)
    assert reverted.ai_snapshot == AI_ANALYSIS
    assert reverted.one_way_sensitivity_snapshot == ONE_WAY
    assert reverted.two_way_sensitivity_snapshot == TWO_WAY


def test_deal_context_invalidates_the_ai_report_but_not_the_sensitivities(db: Path) -> None:
    """The two staleness rules are genuinely different, because the two
    analyses depend on different things.

    A sensitivity run reads no Deal Context -- it re-underwrites the deal with
    one assumption moved -- so editing the stated strategy leaves a saved matrix
    exactly as valid as it was. The AI report interpreted that strategy, so the
    same edit invalidates it. Collapsing the two would throw away a valid matrix
    for a prose edit.
    """

    deal = store_all(db)
    deals_store.update_lease_level_deal(
        deal.id,
        deal.name,
        TERMS,
        PROPERTY_INPUTS,
        OPERATING_INPUTS,
        MARKET_LEASING,
        SUITES,
        LEASES,
        deal_context="Now a refinance-and-hold plan.",
        db_path=db,
    )

    after = deals_store.get_deal(deal.id, db_path=db)
    assert after.ai_snapshot is None
    assert after.one_way_sensitivity_snapshot == ONE_WAY
    assert after.two_way_sensitivity_snapshot == TWO_WAY


def test_a_write_whose_provenance_does_not_match_is_refused(db: Path) -> None:
    """**M5, on the write side.** A caller cannot certify a snapshot against
    assumptions the deal does not actually hold -- the store recomputes the
    fingerprint itself, and the caller's token only ever unlocks a write it
    already agrees with."""

    deal = store_deal(db)

    for write in (
        lambda: deals_store.update_ai_snapshot(
            deal.id, as_dict(AI_ANALYSIS), ai_context_fingerprint="wrong", db_path=db
        ),
        lambda: deals_store.update_one_way_sensitivity_snapshot(
            deal.id, as_dict(ONE_WAY), financial_input_fingerprint="wrong", db_path=db
        ),
        lambda: deals_store.update_two_way_sensitivity_snapshot(
            deal.id, as_dict(TWO_WAY), financial_input_fingerprint="wrong", db_path=db
        ),
    ):
        with pytest.raises(SnapshotValidationError):
            write()

    untouched = deals_store.get_deal(deal.id, db_path=db)
    assert untouched.ai_snapshot is None
    assert untouched.one_way_sensitivity_snapshot is None
    assert untouched.two_way_sensitivity_snapshot is None


# =============================================================================
# 12, 13. Regeneration replaces; failure destroys nothing
# =============================================================================


def test_12_regeneration_replaces_the_latest_snapshot_and_appends_no_history(
    db: Path,
) -> None:
    """**Required test 12.** One latest report per deal, not a list of them."""

    deal = store_all(db)
    second = dataclasses.replace(AI_ANALYSIS, investment_view="Revised view.")
    deals_store.update_ai_snapshot(
        deal.id, as_dict(second), ai_context_fingerprint=ai_fingerprint(), db_path=db
    )

    assert deals_store.get_deal(deal.id, db_path=db).ai_snapshot == second

    connection = sqlite3.connect(db)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(lease_level_deals)")}
    rows = connection.execute(
        "SELECT COUNT(*) FROM deal_sensitivity_snapshots WHERE deal_id = ?", (deal.id,)
    ).fetchone()[0]
    connection.close()
    assert not any("history" in column or "version_id" in column for column in columns)
    # Two rows, one per analysis kind, however many times either was re-run.
    assert rows == 2


def test_13_a_failed_regeneration_leaves_the_last_good_report_in_place(db: Path) -> None:
    """**Required test 13, and M8.**

    Only a SUCCESSFUL report ever reaches a writer, so there is nothing a
    failure could write. The claim is that no other path clears the column
    either -- proved by driving the failure the way it actually happens (a
    refused write) and then reading the deal back.
    """

    deal = store_all(db)

    with pytest.raises(SnapshotValidationError):
        deals_store.update_ai_snapshot(
            deal.id,
            {"executive_summary": "half a report"},
            ai_context_fingerprint=ai_fingerprint(),
            db_path=db,
        )

    assert deals_store.get_deal(deal.id, db_path=db).ai_snapshot == AI_ANALYSIS


def test_26_and_40_a_failed_sensitivity_write_leaves_the_last_good_run_in_place(
    db: Path,
) -> None:
    """**Required tests 26 and 40, and M9.**"""

    deal = store_all(db)

    with pytest.raises(SnapshotValidationError):
        deals_store.update_one_way_sensitivity_snapshot(
            deal.id,
            {"configuration": {"metric": "levered_irr"}},
            financial_input_fingerprint=input_fingerprint(),
            db_path=db,
        )
    with pytest.raises(SnapshotValidationError):
        deals_store.update_two_way_sensitivity_snapshot(
            deal.id,
            as_dict(ONE_WAY),
            financial_input_fingerprint=input_fingerprint(),
            db_path=db,
        )

    after = deals_store.get_deal(deal.id, db_path=db)
    assert after.one_way_sensitivity_snapshot == ONE_WAY
    assert after.two_way_sensitivity_snapshot == TWO_WAY


# =============================================================================
# 14, 15. Duplication and deletion
# =============================================================================


def test_14_and_M12_a_duplicated_lease_level_deal_inherits_no_analysis(db: Path) -> None:
    """**Required test 14, and M12.**

    Duplicate copies the underwriting. An AI report and a sensitivity matrix are
    analytical outputs associated with the deal instance that produced them, and
    a copy that silently arrived carrying them would read as work the analyst
    had done on it.
    """

    deal = store_all(db)
    copy = deals_store.duplicate_deal(deal.id, db_path=db)

    assert copy.id != deal.id
    assert copy.terms == deal.terms
    assert copy.suites == deal.suites
    assert copy.ai_snapshot is None
    assert copy.one_way_sensitivity_snapshot is None
    assert copy.two_way_sensitivity_snapshot is None
    # And the original is completely unaffected.
    assert deals_store.get_deal(deal.id, db_path=db).ai_snapshot == AI_ANALYSIS


def test_duplication_writes_no_sensitivity_row_for_any_mode(db: Path) -> None:
    """The rule stated structurally: duplication creates no row in the derived
    table at all, so it cannot be widened by accident into copying one."""

    deal = store_all(db)
    copy = deals_store.duplicate_deal(deal.id, db_path=db)

    connection = sqlite3.connect(db)
    rows = connection.execute(
        "SELECT COUNT(*) FROM deal_sensitivity_snapshots WHERE deal_id = ?", (copy.id,)
    ).fetchone()[0]
    connection.close()
    assert rows == 0


def test_15_and_M13_deleting_a_deal_removes_its_derived_analysis(db: Path) -> None:
    """**Required test 15, and M13.** No orphan rows -- checked in the table
    itself, because a repository that merely stopped *returning* them would
    still be leaking rows, and a later deal could not be proved not to inherit
    one."""

    deal = store_all(db)
    deals_store.delete_deal(deal.id, db_path=db)

    connection = sqlite3.connect(db)
    orphans = connection.execute(
        "SELECT COUNT(*) FROM deal_sensitivity_snapshots WHERE deal_id = ?", (deal.id,)
    ).fetchone()[0]
    parents = connection.execute(
        "SELECT COUNT(*) FROM lease_level_deals WHERE id = ?", (deal.id,)
    ).fetchone()[0]
    connection.close()

    assert orphans == 0
    assert parents == 0


def test_deleting_one_deal_leaves_another_deal_s_analysis_alone(db: Path) -> None:
    keep = store_all(db, name="Keep")
    remove = store_all(db, name="Remove")

    deals_store.delete_deal(remove.id, db_path=db)

    kept = deals_store.get_deal(keep.id, db_path=db)
    assert kept.one_way_sensitivity_snapshot == ONE_WAY
    assert kept.two_way_sensitivity_snapshot == TWO_WAY


# =============================================================================
# 16-25, 28-39. The sensitivity snapshots themselves
# =============================================================================


def test_16_to_20_and_23_the_one_way_run_round_trips_exactly(db: Path) -> None:
    """**Required tests 16-20 and 23, and M15.**

    Field by field rather than by one ``==``, so a failure names what drifted.
    The candidate order is asserted as a sequence, not as a set: the values were
    submitted unsorted on purpose.
    """

    deal = store_all(db)
    restored = deals_store.get_deal(deal.id, db_path=db).one_way_sensitivity_snapshot

    assert restored is not None
    assert restored.configuration.metric == "levered_irr"
    assert restored.configuration.assumption == "exit_cap_rate"
    assert restored.configuration.values == ONE_WAY_VALUES
    assert list(restored.configuration.values) != sorted(ONE_WAY_VALUES)
    assert restored.result == ONE_WAY.result
    assert restored.result.assumption_values == ONE_WAY.result.assumption_values
    assert restored == ONE_WAY


def test_24_and_39_the_baseline_the_backend_returned_is_preserved(db: Path) -> None:
    """**Required tests 24 and 39.** The baseline is the backend's, carried
    verbatim: nothing here re-derives which candidate is the base, and the
    stored value is a full-precision float rather than anything rounded for
    display."""

    deal = store_all(db)
    reloaded = deals_store.get_deal(deal.id, db_path=db)
    one_way = reloaded.one_way_sensitivity_snapshot
    two_way = reloaded.two_way_sensitivity_snapshot

    assert one_way is not None and two_way is not None
    assert one_way.result.baseline_assumption_value == 0.065
    assert one_way.result.baseline_metric_value == 0.1183456789012345
    assert two_way.result.baseline_row_value == 0.065
    assert two_way.result.baseline_column_value == 50_000_000.0
    assert two_way.result.baseline_metric_value == 1.7512345678901234


def test_25_and_M16_an_undefined_metric_stays_undefined(db: Path) -> None:
    """**Required test 25, and M16.**

    ``None`` means the scenario was fully underwritten and the metric is not
    uniquely defined for it. Turning it into ``0.0`` anywhere in serialization
    would turn a healthy deal into a broken-looking one, so it is asserted as
    ``is None`` -- ``== 0`` would not distinguish the two, and a stored zero
    would render as a real metric rather than as ``N/A``.
    """

    deal = store_all(db)
    restored = deals_store.get_deal(deal.id, db_path=db)

    one_way = restored.one_way_sensitivity_snapshot
    two_way = restored.two_way_sensitivity_snapshot
    assert one_way is not None and two_way is not None
    assert one_way.result.metric_values[2] is None
    assert two_way.result.matrix[2][0] is None
    # And nothing turned into a zero on the way through.
    assert 0.0 not in one_way.result.metric_values


def test_28_to_34_and_37_38_the_two_way_run_round_trips_exactly(db: Path) -> None:
    """**Required tests 28-34, 37 and 38, and M14.**

    The matrix is compared as a tuple of tuples, in row-major order, against a
    non-square fixture: a transpose would change the shape, and a row/column
    swap that preserved the shape would still fail the element comparison.
    """

    deal = store_all(db)
    restored = deals_store.get_deal(deal.id, db_path=db).two_way_sensitivity_snapshot

    assert restored is not None
    assert restored.configuration.metric == "equity_multiple"
    assert restored.configuration.row_assumption == "exit_cap_rate"
    assert restored.configuration.column_assumption == "purchase_price"
    assert restored.configuration.row_values == ("6.75", "6.25", "6.5")
    assert restored.configuration.column_values == ("52000000", "48000000")

    matrix = restored.result.matrix
    assert len(matrix) == 3, "rows stopped being rows"
    assert all(len(row) == 2 for row in matrix), "columns stopped being columns"
    assert matrix == TWO_WAY.result.matrix
    assert restored == TWO_WAY


def test_M14_a_transposed_matrix_is_a_different_value() -> None:
    """The comparison above has teeth: a transpose of this fixture really is
    unequal to it, so a passing round trip is not passing vacuously."""

    transposed = tuple(zip(*TWO_WAY.result.matrix))
    assert transposed != TWO_WAY.result.matrix


def test_the_matrix_rows_decode_as_tuples_not_lists(db: Path) -> None:
    """The decoder converts a JSON array back into a tuple at every depth.

    Left as lists, the restored matrix would compare unequal to the one that was
    stored while looking identical when printed -- the exact shape of drift a
    round-trip oracle exists to catch.
    """

    deal = store_all(db)
    restored = deals_store.get_deal(deal.id, db_path=db).two_way_sensitivity_snapshot

    assert restored is not None
    assert isinstance(restored.result.matrix, tuple)
    assert all(isinstance(row, tuple) for row in restored.result.matrix)


# =============================================================================
# 42-45. The three artifacts are independent
# =============================================================================


def test_42_and_M10_running_one_way_does_not_erase_two_way(db: Path) -> None:
    """**Required test 42, and M10.**"""

    deal = store_all(db)
    replacement = dataclasses.replace(
        ONE_WAY,
        configuration=dataclasses.replace(ONE_WAY.configuration, metric="exit_value"),
    )
    deals_store.update_one_way_sensitivity_snapshot(
        deal.id,
        as_dict(replacement),
        financial_input_fingerprint=input_fingerprint(),
        db_path=db,
    )

    after = deals_store.get_deal(deal.id, db_path=db)
    assert after.one_way_sensitivity_snapshot == replacement
    assert after.two_way_sensitivity_snapshot == TWO_WAY


def test_43_and_M11_running_two_way_does_not_erase_one_way(db: Path) -> None:
    """**Required test 43, and M11.**"""

    deal = store_all(db)
    replacement = dataclasses.replace(
        TWO_WAY,
        configuration=dataclasses.replace(TWO_WAY.configuration, metric="headline_dscr"),
    )
    deals_store.update_two_way_sensitivity_snapshot(
        deal.id,
        as_dict(replacement),
        financial_input_fingerprint=input_fingerprint(),
        db_path=db,
    )

    after = deals_store.get_deal(deal.id, db_path=db)
    assert after.two_way_sensitivity_snapshot == replacement
    assert after.one_way_sensitivity_snapshot == ONE_WAY


def test_44_and_45_ai_and_sensitivity_do_not_disturb_each_other(db: Path) -> None:
    """**Required tests 44 and 45.**"""

    deal = store_all(db)

    regenerated = dataclasses.replace(AI_ANALYSIS, executive_summary="Regenerated.")
    deals_store.update_ai_snapshot(
        deal.id, as_dict(regenerated), ai_context_fingerprint=ai_fingerprint(), db_path=db
    )
    after_ai = deals_store.get_deal(deal.id, db_path=db)
    assert after_ai.one_way_sensitivity_snapshot == ONE_WAY
    assert after_ai.two_way_sensitivity_snapshot == TWO_WAY

    deals_store.update_one_way_sensitivity_snapshot(
        deal.id,
        as_dict(ONE_WAY),
        financial_input_fingerprint=input_fingerprint(),
        db_path=db,
    )
    after_sensitivity = deals_store.get_deal(deal.id, db_path=db)
    assert after_sensitivity.ai_snapshot == regenerated


# =============================================================================
# The persistence round-trip oracle
# =============================================================================


def test_the_round_trip_oracle_is_exact_across_a_destroyed_repository(db: Path) -> None:
    """**The gate's explicit oracle.**

    Persist all three, destroy and recreate the repository instance, reload, and
    require exact identity -- no float drift, no string drift, no reordering, no
    reshaping. ``==`` on frozen dataclasses is exact for floats (IEEE-754
    binary64 in, binary64 out) and for the tuple structure around them, so this
    is one assertion per artifact rather than a field-by-field survey that could
    omit the one field that drifted.
    """

    deal = store_all(db)
    original = deals_store.get_deal(deal.id, db_path=db)

    # A genuinely new instance: the module executed again from source, sharing
    # no state with the one that wrote the rows, and every connection this
    # process held closed by construction (``_connect`` closes in a ``finally``).
    restored = fresh_store_module().get_deal(deal.id, db_path=db)

    assert restored.ai_snapshot == original.ai_snapshot == AI_ANALYSIS
    assert restored.one_way_sensitivity_snapshot == original.one_way_sensitivity_snapshot
    assert restored.one_way_sensitivity_snapshot == ONE_WAY
    assert restored.two_way_sensitivity_snapshot == original.two_way_sensitivity_snapshot
    assert restored.two_way_sensitivity_snapshot == TWO_WAY

    # Float identity, spelled out: the exact bits, not "close enough".
    one_way = restored.one_way_sensitivity_snapshot
    two_way = restored.two_way_sensitivity_snapshot
    assert one_way is not None and two_way is not None
    assert one_way.result.baseline_metric_value == 0.1183456789012345
    assert two_way.result.matrix[1][1] == 1.95

    # String identity for the analyst's own candidate values.
    assert one_way.configuration.values == ONE_WAY_VALUES

    # And the fingerprint that certifies all of it.
    connection = sqlite3.connect(db)
    fingerprints = {
        row[0]
        for row in connection.execute(
            "SELECT source_fingerprint FROM deal_sensitivity_snapshots WHERE deal_id = ?",
            (deal.id,),
        )
    }
    connection.close()
    assert fingerprints == {input_fingerprint()}


# =============================================================================
# Schema versioning and graceful degradation
# =============================================================================


def test_an_incompatible_snapshot_version_is_ignored_rather_than_fatal(db: Path) -> None:
    """A stored payload from a future (or past) serialization contract must make
    the artifact unavailable, never make the deal unopenable."""

    deal = store_all(db)

    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE deal_sensitivity_snapshots SET schema_version = 99 WHERE deal_id = ?",
        (deal.id,),
    )
    connection.execute(
        "UPDATE lease_level_deals SET ai_snapshot_schema_version = 99 WHERE id = ?",
        (deal.id,),
    )
    connection.commit()
    connection.close()

    reloaded = deals_store.get_deal(deal.id, db_path=db)
    assert reloaded.ai_snapshot is None
    assert reloaded.one_way_sensitivity_snapshot is None
    assert reloaded.two_way_sensitivity_snapshot is None
    # The deal itself opens completely intact.
    assert reloaded.terms == TERMS
    assert reloaded.suites == SUITES


def test_a_corrupt_snapshot_payload_is_ignored_rather_than_fatal(db: Path) -> None:
    deal = store_all(db)

    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE deal_sensitivity_snapshots SET snapshot = '{not json' WHERE deal_id = ?",
        (deal.id,),
    )
    connection.commit()
    connection.close()

    reloaded = deals_store.get_deal(deal.id, db_path=db)
    assert reloaded.one_way_sensitivity_snapshot is None
    assert reloaded.two_way_sensitivity_snapshot is None
    assert reloaded.ai_snapshot == AI_ANALYSIS


def test_an_unknown_analysis_kind_is_ignored(db: Path) -> None:
    """A row this build does not recognise is skipped, not guessed at."""

    deal = store_all(db)

    connection = sqlite3.connect(db)
    connection.execute(
        "INSERT INTO deal_sensitivity_snapshots "
        "(deal_id, analysis_kind, snapshot, schema_version, source_fingerprint, generated_at) "
        "VALUES (?, 'three_way', '{}', 1, ?, '2027-01-01T00:00:00+00:00')",
        (deal.id, input_fingerprint()),
    )
    connection.commit()
    connection.close()

    reloaded = deals_store.get_deal(deal.id, db_path=db)
    assert reloaded.one_way_sensitivity_snapshot == ONE_WAY
    assert reloaded.two_way_sensitivity_snapshot == TWO_WAY


def test_a_pre_gate_database_opens_and_starts_empty(tmp_path: Path) -> None:
    """The migration requirement: an existing database opens, keeps every deal,
    and simply has no derived analysis yet."""

    path = tmp_path / "pre-gate.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE deals (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "purchase_price REAL NOT NULL, current_noi REAL NOT NULL, occupancy REAL NOT NULL, "
        "noi_growth REAL NOT NULL, hold_period INTEGER NOT NULL, exit_cap_rate REAL NOT NULL, "
        "ltv REAL NOT NULL, interest_rate REAL NOT NULL, amortization INTEGER NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO deals VALUES ('legacy', 'Legacy Deal', 50000000, 2500000, 0.95, 0.03, "
        "5, 0.055, 0.65, 0.0525, 30, '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00')"
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    deals = deals_store.list_deals(db_path=path)
    assert [deal.name for deal in deals] == ["Legacy Deal"]

    legacy = deals_store.get_deal("legacy", db_path=path)
    assert legacy.one_way_sensitivity_snapshot is None
    assert legacy.two_way_sensitivity_snapshot is None

    connection = sqlite3.connect(path)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    empty = connection.execute(
        "SELECT COUNT(*) FROM deal_sensitivity_snapshots"
    ).fetchone()[0]
    connection.close()
    assert version == 7  # D6.5 adds the two Business Plan tables on top of D5.8A's
    assert empty == 0


# =============================================================================
# Mode dispatch -- this surface is Lease-Level's
# =============================================================================


@pytest.mark.parametrize("mode", ["quick", "detailed"])
def test_a_quick_or_detailed_deal_is_refused_by_name(db: Path, mode: str) -> None:
    """D5.1A's rule. A deal of another mode is refused as unsupported, not
    reported as missing -- Quick and Detailed recompute their standardized
    preset bundle on every Analyze and have no analyst-configured sensitivity to
    keep."""

    from anchor.contracts import (
        AcquisitionInputs,
        AcquisitionTerms,
        DetailedOperatingInputs,
    )

    if mode == "quick":
        deal = deals_store.create_deal(
            "Quick",
            AcquisitionInputs(
                purchase_price=50_000_000.0,
                current_noi=2_500_000.0,
                occupancy=0.95,
                noi_growth=0.03,
                hold_period=5,
                exit_cap_rate=0.055,
                ltv=0.65,
                interest_rate=0.0525,
                amortization=30,
            ),
            db_path=db,
        )
    else:
        deal = deals_store.create_detailed_deal(
            "Detailed",
            AcquisitionTerms(
                purchase_price=50_000_000.0,
                hold_period=5,
                exit_cap_rate=0.055,
                ltv=0.65,
                interest_rate=0.0525,
                amortization=30,
                acquisition_cost_pct=0.0,
                financing_fee_pct=0.0,
                disposition_cost_pct=0.0,
                annual_capex_reserve=0.0,
                io_period=0,
            ),
            DetailedOperatingInputs(
                gross_potential_rent=5_000_000.0,
                other_income=100_000.0,
                vacancy_credit_loss_pct=0.05,
                property_taxes=600_000.0,
                insurance=90_000.0,
                utilities=140_000.0,
                repairs_maintenance=110_000.0,
                other_operating_expenses=60_000.0,
                management_fee_pct=0.03,
                revenue_growth=0.03,
                expense_growth=0.03,
            ),
            db_path=db,
        )

    with pytest.raises(UnsupportedOperatingModeError):
        deals_store.update_one_way_sensitivity_snapshot(
            deal.id, as_dict(ONE_WAY), financial_input_fingerprint="anything", db_path=db
        )


def test_an_unknown_deal_id_is_reported_as_missing(db: Path) -> None:
    from anchor.deals import DealNotFoundError

    with pytest.raises(DealNotFoundError):
        deals_store.update_two_way_sensitivity_snapshot(
            "no-such-deal",
            as_dict(TWO_WAY),
            financial_input_fingerprint="anything",
            db_path=db,
        )


# =============================================================================
# Security / privacy -- persisting AI output creates durable user data
# =============================================================================


def test_no_provider_secret_or_internal_reaches_storage(db: Path) -> None:
    """The stored AI payload is exactly the user-facing structured report.

    ``AIAnalysis`` has no field for a key, a prompt or provider metadata, so
    this is a structural guarantee rather than a filter -- and it is checked on
    the raw stored bytes, which is where a leak would actually be visible.
    """

    deal = store_all(db)

    connection = sqlite3.connect(db)
    stored = connection.execute(
        "SELECT ai_snapshot FROM lease_level_deals WHERE id = ?", (deal.id,)
    ).fetchone()[0]
    connection.close()

    payload = json.loads(stored)
    assert set(payload) == {field.name for field in dataclasses.fields(AIAnalysis)}
    lowered = stored.lower()
    for forbidden in (
        "api_key",
        "apikey",
        "openai",
        "sk-",
        "authorization",
        "system_prompt",
        "user_prompt",
        "temperature",
    ):
        assert forbidden not in lowered, f"stored AI snapshot leaks {forbidden!r}"


# =============================================================================
# Performance -- the persisted state must be tiny relative to the deal
# =============================================================================


def test_the_persisted_analysis_is_small_and_hydration_is_fast(db: Path) -> None:
    """Measured rather than asserted about. No arbitrary size limit is imposed;
    the bounds below are generous sanity ceilings that would only fail if
    something started storing a whole projection here."""

    deal = store_all(db)

    connection = sqlite3.connect(db)
    ai_bytes = len(
        connection.execute(
            "SELECT ai_snapshot FROM lease_level_deals WHERE id = ?", (deal.id,)
        ).fetchone()[0]
    )
    sizes = dict(
        connection.execute(
            "SELECT analysis_kind, LENGTH(snapshot) FROM deal_sensitivity_snapshots "
            "WHERE deal_id = ?",
            (deal.id,),
        ).fetchall()
    )
    connection.close()

    started = time.perf_counter()
    for _ in range(10):
        deals_store.get_deal(deal.id, db_path=db)
    hydration_ms = (time.perf_counter() - started) * 100.0

    print(
        f"\nD5.8A persisted sizes: ai={ai_bytes}B one_way={sizes['one_way']}B "
        f"two_way={sizes['two_way']}B; hydration={hydration_ms:.1f}ms per get_deal"
    )

    assert ai_bytes < 16_384
    assert sizes["one_way"] < 4_096
    assert sizes["two_way"] < 4_096
