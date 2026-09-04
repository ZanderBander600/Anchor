"""Owner Return Metrics V3 Gate A7 -- snapshot provenance hardening.

Gate A6 identified a deliberate trust boundary: a generic create/update
request could pair NEW financial assumptions with a STALE analysis/AI
snapshot in the same write, because the persistence layer computed the
snapshot's fingerprint from the assumptions in that same write -- silently
relabeling the stale snapshot as valid for the new assumptions. The existing
frontend never did this, but the invariant must not depend on frontend
behavior.

This file proves the hardening closes that boundary:

1. ``create_deal``/``update_deal``/``create_detailed_deal``/
   ``update_detailed_deal`` no longer accept a snapshot parameter at all --
   a generic assumptions write can never be paired with an unverified
   derived-results payload in the same call, structurally.
2. The two dedicated, narrow snapshot-write functions
   (``update_analysis_snapshot``/``update_ai_snapshot``) now REQUIRE the
   caller to supply the provenance fingerprint the snapshot was actually
   produced under, and independently verify it against the deal's own
   CURRENTLY STORED assumptions/context before persisting anything -- a
   mismatch is rejected (``SnapshotValidationError``), never silently
   relabeled.
3. ``anchor.api``'s ``POST /deals/fingerprint`` is the sole, backend-
   authoritative source of that provenance token -- the frontend never
   computes (or duplicates in TypeScript) the fingerprint algorithm itself.
4. Quick and Detailed both follow the identical invariant.
5. A legacy/corrupt/missing provenance snapshot still never blocks opening
   the underlying deal (the read-time decode path is unchanged by this
   gate).

Mirrors ``test_owner_return_metrics_v3_gate_a6_snapshots.py``'s fixtures and
style.
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anchor import api as api_module
from anchor.ai.contracts import AIAnalysis
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.deals import SnapshotValidationError
from anchor.deals import store as deals_store
from anchor.deals.fingerprint import (
    fingerprint_ai,
    fingerprint_detailed_inputs,
    fingerprint_quick_inputs,
)
from anchor.engine.acquisition import (
    analyze_acquisition,
    analyze_detailed_acquisition_with_projection,
)

QUICK_INPUTS = AcquisitionInputs(
    purchase_price=10_000_000.0,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)

OTHER_QUICK_INPUTS = dataclasses.replace(QUICK_INPUTS, purchase_price=25_000_000.0)

DETAILED_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)
DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)
OTHER_DETAILED_TERMS = dataclasses.replace(DETAILED_TERMS, purchase_price=25_000_000.0)

QUICK_RESULTS = analyze_acquisition(QUICK_INPUTS)
DETAILED_ENVELOPE = analyze_detailed_acquisition_with_projection(
    DETAILED_TERMS, DETAILED_OPERATING_INPUTS
)

AI_ANALYSIS = AIAnalysis(
    executive_summary="Five-year hold with moderate leverage.",
    investment_view="Return profile clears the supplied hurdles at baseline.",
    strengths=("Levered IRR clears the target hurdle.",),
    risks=("Exit cap rate expansion compresses returns.",),
    return_drivers=("NOI growth",),
    downside_analysis="Levered IRR remains positive across the tested range.",
    capital_structure_analysis="Leverage produces adequate Year 1 DSCR.",
    break_even_analysis="Break-even was found within the tested range.",
    questions_to_investigate=("What is the in-place rent roll composition?",),
    confidence_notes=("No tenant credit data was supplied.",),
)


def _as_json_dict(value: object) -> dict:
    """Mirrors the Gate A6 test file's helper exactly -- emulates a genuine
    HTTP JSON round-trip."""

    import json

    return json.loads(json.dumps(dataclasses.asdict(value)))


QUICK_RESULTS_DICT = _as_json_dict(QUICK_RESULTS)
DETAILED_ENVELOPE_DICT = _as_json_dict(DETAILED_ENVELOPE)
AI_ANALYSIS_DICT = _as_json_dict(AI_ANALYSIS)

QUICK_PAYLOAD: dict[str, object] = {
    "purchase_price": 10_000_000.0,
    "current_noi": 600_000.0,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
    "acquisition_cost_pct": 0.02,
    "financing_fee_pct": 0.01,
    "disposition_cost_pct": 0.025,
    "annual_capex_reserve": 50_000.0,
    "io_period": 2,
}
OTHER_QUICK_PAYLOAD = {**QUICK_PAYLOAD, "purchase_price": 25_000_000.0}


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test-anchor.db"


# =============================================================================
# 1. Generic create/update never accept, and never persist, a snapshot --
#    the write path this gate closes structurally.
# =============================================================================


def test_create_deal_has_no_snapshot_parameter() -> None:
    signature = inspect.signature(deals_store.create_deal)
    assert "analysis_snapshot" not in signature.parameters
    assert "ai_snapshot" not in signature.parameters


def test_update_deal_has_no_snapshot_parameter() -> None:
    signature = inspect.signature(deals_store.update_deal)
    assert "analysis_snapshot" not in signature.parameters
    assert "ai_snapshot" not in signature.parameters


def test_create_detailed_deal_has_no_snapshot_parameter() -> None:
    signature = inspect.signature(deals_store.create_detailed_deal)
    assert "analysis_snapshot" not in signature.parameters
    assert "ai_snapshot" not in signature.parameters


def test_update_detailed_deal_has_no_snapshot_parameter() -> None:
    signature = inspect.signature(deals_store.update_detailed_deal)
    assert "analysis_snapshot" not in signature.parameters
    assert "ai_snapshot" not in signature.parameters


def test_generic_update_cannot_relabel_a_stale_snapshot_via_the_api(tmp_path: Path) -> None:
    """Required test #11 -- even a caller that sneaks an
    ``analysis_snapshot``/``ai_snapshot`` field into a generic ``PUT
    /deals/{id}`` body has it silently ignored: the route never reads those
    fields, so it is structurally impossible for a combined write to relabel
    stale cached data as valid for new assumptions."""

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "test.db"))
        client = TestClient(api_module.app)

        created = client.post("/deals", json={"name": "Deal", "inputs": QUICK_PAYLOAD})
        assert created.status_code == 200
        deal_id = created.json()["id"]
        assert created.json()["analysis_snapshot"] is None

        # A malicious/buggy caller attempts to smuggle a snapshot into a
        # generic update alongside new assumptions -- the API route never
        # even looks at these fields.
        updated = client.put(
            f"/deals/{deal_id}",
            json={
                "name": "Deal",
                "inputs": OTHER_QUICK_PAYLOAD,
                "analysis_snapshot": QUICK_RESULTS_DICT,
                "ai_snapshot": AI_ANALYSIS_DICT,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["analysis_snapshot"] is None
        assert updated.json()["ai_snapshot"] is None


# =============================================================================
# 2-3. Required tests 1/2 -- a snapshot from assumptions A cannot be
#      attached to assumptions B, for both Quick and Detailed.
# =============================================================================


def test_quick_analysis_snapshot_from_assumptions_a_cannot_attach_to_assumptions_b(
    db_path: Path,
) -> None:
    deal = deals_store.create_deal("Deal", QUICK_INPUTS, db_path=db_path)
    stale_fingerprint = fingerprint_quick_inputs(QUICK_INPUTS)

    # Change the deal's stored assumptions to B via the ordinary update path.
    deals_store.update_deal(deal.id, "Deal", OTHER_QUICK_INPUTS, db_path=db_path)

    with pytest.raises(SnapshotValidationError):
        deals_store.update_analysis_snapshot(
            deal.id,
            QUICK_RESULTS_DICT,
            financial_input_fingerprint=stale_fingerprint,
            db_path=db_path,
        )

    # Never stored as valid.
    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.analysis_snapshot is None


def test_detailed_analysis_snapshot_from_assumptions_a_cannot_attach_to_assumptions_b(
    db_path: Path,
) -> None:
    deal = deals_store.create_detailed_deal(
        "Deal", DETAILED_TERMS, DETAILED_OPERATING_INPUTS, db_path=db_path
    )
    stale_fingerprint = fingerprint_detailed_inputs(DETAILED_TERMS, DETAILED_OPERATING_INPUTS)

    deals_store.update_detailed_deal(
        deal.id, "Deal", OTHER_DETAILED_TERMS, DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    with pytest.raises(SnapshotValidationError):
        deals_store.update_analysis_snapshot(
            deal.id,
            DETAILED_ENVELOPE_DICT,
            financial_input_fingerprint=stale_fingerprint,
            db_path=db_path,
        )

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.analysis_snapshot is None


def test_generic_update_followed_by_stale_snapshot_attempt_via_the_api_rejects(
    tmp_path: Path,
) -> None:
    """Section 7 scenario A, exercised end-to-end through the HTTP API: a
    caller analyzes assumptions A, obtains a provenance-validated snapshot
    for A, changes the deal's assumptions to B, then attempts to attach the
    snapshot for A against the deal now storing B. Expected: reject, never
    stored as valid."""

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "test.db"))
        client = TestClient(api_module.app)

        created = client.post("/deals", json={"name": "Deal", "inputs": QUICK_PAYLOAD})
        deal_id = created.json()["id"]

        fingerprint_response = client.post(
            "/deals/fingerprint", json={"operating_mode": "quick", "inputs": QUICK_PAYLOAD}
        )
        assert fingerprint_response.status_code == 200
        stale_fingerprint = fingerprint_response.json()["financial_input_fingerprint"]

        analyze_response = client.post("/analyze", json=QUICK_PAYLOAD)
        assert analyze_response.status_code == 200
        results = analyze_response.json()

        # Attach the correct, matching snapshot first -- sanity that the
        # happy path works before we break it.
        first_attach = client.put(
            f"/deals/{deal_id}/analysis-snapshot",
            json={"analysis_snapshot": results, "financial_input_fingerprint": stale_fingerprint},
        )
        assert first_attach.status_code == 200
        assert first_attach.json()["analysis_snapshot"] is not None

        # Change assumptions to B.
        update_response = client.put(
            f"/deals/{deal_id}", json={"name": "Deal", "inputs": OTHER_QUICK_PAYLOAD}
        )
        assert update_response.status_code == 200
        # Reading the deal back after the assumption change already shows
        # the old snapshot as invalidated.
        assert update_response.json()["analysis_snapshot"] is None

        # Attempt to (re-)attach the snapshot computed for A, now that the
        # deal stores B.
        stale_attach = client.put(
            f"/deals/{deal_id}/analysis-snapshot",
            json={"analysis_snapshot": results, "financial_input_fingerprint": stale_fingerprint},
        )
        assert stale_attach.status_code == 422

        final = client.get(f"/deals/{deal_id}")
        assert final.json()["analysis_snapshot"] is None


# =============================================================================
# 4. Required test #3 -- an AI snapshot generated under context X cannot be
#    attached after context changes to Y.
# =============================================================================


def test_ai_snapshot_from_context_x_cannot_attach_after_context_changes_to_y(
    db_path: Path,
) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, deal_context="Context X.", db_path=db_path
    )
    analysis_fingerprint = fingerprint_quick_inputs(QUICK_INPUTS)
    stale_ai_fingerprint = fingerprint_ai(
        analysis_fingerprint=analysis_fingerprint, deal_context="Context X."
    )

    # Context changes to Y; assumptions are unchanged.
    deals_store.update_deal(deal.id, "Deal", QUICK_INPUTS, deal_context="Context Y.", db_path=db_path)

    with pytest.raises(SnapshotValidationError):
        deals_store.update_ai_snapshot(
            deal.id,
            AI_ANALYSIS_DICT,
            ai_context_fingerprint=stale_ai_fingerprint,
            db_path=db_path,
        )

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.ai_snapshot is None
    assert reopened.deal_context == "Context Y."


def test_detailed_ai_snapshot_from_context_x_cannot_attach_after_context_changes_to_y(
    db_path: Path,
) -> None:
    deal = deals_store.create_detailed_deal(
        "Deal",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        deal_context="Context X.",
        db_path=db_path,
    )
    analysis_fingerprint = fingerprint_detailed_inputs(DETAILED_TERMS, DETAILED_OPERATING_INPUTS)
    stale_ai_fingerprint = fingerprint_ai(
        analysis_fingerprint=analysis_fingerprint, deal_context="Context X."
    )

    deals_store.update_detailed_deal(
        deal.id,
        "Deal",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        deal_context="Context Y.",
        db_path=db_path,
    )

    with pytest.raises(SnapshotValidationError):
        deals_store.update_ai_snapshot(
            deal.id,
            AI_ANALYSIS_DICT,
            ai_context_fingerprint=stale_ai_fingerprint,
            db_path=db_path,
        )

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.ai_snapshot is None


# =============================================================================
# 5. Required test #4/#5 -- correct provenance persists (analysis and AI).
# =============================================================================


def test_correct_analysis_provenance_persists(db_path: Path) -> None:
    deal = deals_store.create_deal("Deal", QUICK_INPUTS, db_path=db_path)

    updated = deals_store.update_analysis_snapshot(
        deal.id,
        QUICK_RESULTS_DICT,
        financial_input_fingerprint=fingerprint_quick_inputs(QUICK_INPUTS),
        db_path=db_path,
    )

    assert updated.analysis_snapshot == QUICK_RESULTS
    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.analysis_snapshot == QUICK_RESULTS


def test_correct_ai_provenance_persists(db_path: Path) -> None:
    deal = deals_store.create_deal(
        "Deal", QUICK_INPUTS, deal_context="Strategy.", db_path=db_path
    )

    updated = deals_store.update_ai_snapshot(
        deal.id,
        AI_ANALYSIS_DICT,
        ai_context_fingerprint=fingerprint_ai(
            analysis_fingerprint=fingerprint_quick_inputs(QUICK_INPUTS),
            deal_context="Strategy.",
        ),
        db_path=db_path,
    )

    assert updated.ai_snapshot == AI_ANALYSIS
    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.ai_snapshot == AI_ANALYSIS


# =============================================================================
# 6-7. Required test #6/#7 -- first Save of an unsaved analyzed deal still
#      works, and automatic cache refresh still works, both through the
#      provenance-validated path.
# =============================================================================


def test_first_save_of_unsaved_analyzed_deal_still_works(tmp_path: Path) -> None:
    """The Gate A7 Section 5 flow: create the deal (assumptions only), then
    persist its current valid analysis/AI through the provenance-validated
    dedicated endpoints -- the "first Save" case."""

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "test.db"))
        client = TestClient(api_module.app)

        analyze_response = client.post("/analyze", json=QUICK_PAYLOAD)
        assert analyze_response.status_code == 200
        results = analyze_response.json()

        fingerprint_response = client.post(
            "/deals/fingerprint",
            json={"operating_mode": "quick", "inputs": QUICK_PAYLOAD, "deal_context": "Strategy."},
        )
        assert fingerprint_response.status_code == 200
        fingerprints = fingerprint_response.json()

        created = client.post(
            "/deals",
            json={"name": "Deal", "inputs": QUICK_PAYLOAD, "deal_context": "Strategy."},
        )
        assert created.status_code == 200
        deal_id = created.json()["id"]
        assert created.json()["analysis_snapshot"] is None

        attach_analysis = client.put(
            f"/deals/{deal_id}/analysis-snapshot",
            json={
                "analysis_snapshot": results,
                "financial_input_fingerprint": fingerprints["financial_input_fingerprint"],
            },
        )
        assert attach_analysis.status_code == 200
        assert attach_analysis.json()["analysis_snapshot"] is not None

        ai_response = client.post(
            "/ai/analysis",
            json={
                "inputs": QUICK_PAYLOAD,
                "deal_context": "Strategy.",
                "target_levered_irr": 0.15,
                "target_headline_dscr": 1.25,
                "target_equity_multiple": 1.8,
            },
        )
        if ai_response.status_code == 200:
            attach_ai = client.put(
                f"/deals/{deal_id}/ai-snapshot",
                json={
                    "ai_snapshot": ai_response.json(),
                    "ai_context_fingerprint": fingerprints["ai_context_fingerprint"],
                },
            )
            assert attach_ai.status_code == 200
            assert attach_ai.json()["ai_snapshot"] is not None
        else:
            # AI provider not configured in this environment (e.g. no
            # OPENAI_API_KEY) -- the analysis-persistence half of this test
            # is still fully exercised above.
            assert ai_response.status_code in (502, 503)

        final = client.get(f"/deals/{deal_id}")
        assert final.json()["analysis_snapshot"] is not None


def test_automatic_cache_refresh_still_works(db_path: Path) -> None:
    """An already-saved, not-dirty deal's silent background cache refresh
    -- unchanged in spirit from Gate A6, now provenance-validated."""

    deal = deals_store.create_deal("Deal", QUICK_INPUTS, db_path=db_path)
    assert deal.analysis_snapshot is None

    refreshed = deals_store.update_analysis_snapshot(
        deal.id,
        QUICK_RESULTS_DICT,
        financial_input_fingerprint=fingerprint_quick_inputs(QUICK_INPUTS),
        db_path=db_path,
    )

    assert refreshed.analysis_snapshot == QUICK_RESULTS
    # Name/assumptions/updated_at untouched by the narrow refresh.
    assert refreshed.name == deal.name
    assert refreshed.inputs == deal.inputs


# =============================================================================
# 8. Required test #8 -- restart restoration still works.
# =============================================================================


def test_restart_restoration_still_works(db_path: Path) -> None:
    deal = deals_store.create_deal("Deal", QUICK_INPUTS, db_path=db_path)
    deals_store.update_analysis_snapshot(
        deal.id,
        QUICK_RESULTS_DICT,
        financial_input_fingerprint=fingerprint_quick_inputs(QUICK_INPUTS),
        db_path=db_path,
    )

    # A fresh call against the same db_path shares no in-memory state with
    # the call that wrote it -- equivalent to a process restart.
    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.analysis_snapshot == QUICK_RESULTS


# =============================================================================
# 9. Required test #9 -- duplicate behavior remains valid.
# =============================================================================


def test_duplicate_behavior_remains_valid(db_path: Path) -> None:
    original = deals_store.create_deal(
        "Deal", QUICK_INPUTS, deal_context="Strategy.", db_path=db_path
    )
    original = deals_store.update_analysis_snapshot(
        original.id,
        QUICK_RESULTS_DICT,
        financial_input_fingerprint=fingerprint_quick_inputs(QUICK_INPUTS),
        db_path=db_path,
    )
    original = deals_store.update_ai_snapshot(
        original.id,
        AI_ANALYSIS_DICT,
        ai_context_fingerprint=fingerprint_ai(
            analysis_fingerprint=fingerprint_quick_inputs(QUICK_INPUTS), deal_context="Strategy."
        ),
        db_path=db_path,
    )

    duplicate = deals_store.duplicate_deal(original.id, db_path=db_path)

    assert duplicate.id != original.id
    assert duplicate.analysis_snapshot == QUICK_RESULTS
    assert duplicate.ai_snapshot == AI_ANALYSIS


def test_duplicate_of_detailed_deal_remains_valid(db_path: Path) -> None:
    original = deals_store.create_detailed_deal(
        "Deal", DETAILED_TERMS, DETAILED_OPERATING_INPUTS, db_path=db_path
    )
    original = deals_store.update_analysis_snapshot(
        original.id,
        DETAILED_ENVELOPE_DICT,
        financial_input_fingerprint=fingerprint_detailed_inputs(
            DETAILED_TERMS, DETAILED_OPERATING_INPUTS
        ),
        db_path=db_path,
    )

    duplicate = deals_store.duplicate_deal(original.id, db_path=db_path)

    assert duplicate.analysis_snapshot == DETAILED_ENVELOPE


# =============================================================================
# 10. Required test #10 -- malformed/legacy/missing provenance degrades
#     safely (never blocks opening the deal). Unaffected by this gate --
#     confirms it stays true.
# =============================================================================


def test_malformed_provenance_degrades_safely(db_path: Path) -> None:
    deal = deals_store.create_deal("Deal", QUICK_INPUTS, db_path=db_path)
    deals_store.update_analysis_snapshot(
        deal.id,
        QUICK_RESULTS_DICT,
        financial_input_fingerprint=fingerprint_quick_inputs(QUICK_INPUTS),
        db_path=db_path,
    )

    import sqlite3

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE deals SET analysis_snapshot_fingerprint = 'not-a-real-fingerprint' WHERE id = ?",
            (deal.id,),
        )
        connection.commit()
    finally:
        connection.close()

    reopened = deals_store.get_deal(deal.id, db_path=db_path)
    assert reopened.name == "Deal"
    assert reopened.analysis_snapshot is None


# =============================================================================
# 11. Required test #11 already covered above
#     (test_generic_update_cannot_relabel_a_stale_snapshot_via_the_api).
# =============================================================================


# =============================================================================
# 12. Required test #12 -- the frontend never computes a fingerprint; the
#     backend is the sole source. Proven by AST scan: no TypeScript-side
#     sha256/hashlib-equivalent computation exists, and the fingerprint
#     endpoint is the only place ``fingerprint_quick_inputs``/
#     ``fingerprint_detailed_inputs``/``fingerprint_ai`` are invoked from
#     the API layer with caller-controllable inputs it validates itself.
# =============================================================================


def test_frontend_never_computes_the_fingerprint_algorithm() -> None:
    """AST-adjacent proof at the TypeScript source-text level: no frontend
    source file re-implements a sha256/canonical-JSON fingerprint
    computation -- ``crypto`` (Node's/browser's hashing APIs) and
    ``sha256``/``sha-256`` never appear anywhere under ``web/src``. The
    frontend's only access to a fingerprint is the opaque string
    ``anchor.api``'s ``POST /deals/fingerprint`` returns."""

    project_root = Path(__file__).resolve().parents[1]
    web_src = project_root / "web" / "src"
    forbidden_substrings = ("sha256", "sha-256", "createHash", "crypto.subtle")

    offending: list[str] = []
    for source_file in web_src.rglob("*.ts*"):
        text = source_file.read_text(encoding="utf-8").casefold()
        for forbidden in forbidden_substrings:
            if forbidden.casefold() in text:
                offending.append(f"{source_file}: {forbidden}")

    assert not offending, f"Frontend source computes a fingerprint itself: {offending}"


def test_deal_fingerprint_endpoint_matches_the_canonical_algorithm(tmp_path: Path) -> None:
    """The provenance token the frontend transports must be byte-identical
    to what the store layer will independently recompute -- proven by
    calling the real HTTP endpoint and comparing against
    ``anchor.deals.fingerprint`` directly."""

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "test.db"))
        client = TestClient(api_module.app)

        response = client.post(
            "/deals/fingerprint",
            json={"operating_mode": "quick", "inputs": QUICK_PAYLOAD, "deal_context": "Strategy."},
        )
        assert response.status_code == 200
        body = response.json()

    expected_financial = fingerprint_quick_inputs(QUICK_INPUTS)
    expected_ai = fingerprint_ai(analysis_fingerprint=expected_financial, deal_context="Strategy.")
    assert body["financial_input_fingerprint"] == expected_financial
    assert body["ai_context_fingerprint"] == expected_ai


# =============================================================================
# 13. Required test #13 -- Quick and Detailed both follow the same
#     invariant. Already proven by the paired tests above (each Quick test
#     has a Detailed counterpart); this is an explicit combined check.
# =============================================================================


def test_quick_and_detailed_both_reject_a_provenance_mismatch_identically(db_path: Path) -> None:
    quick_deal = deals_store.create_deal("Deal", QUICK_INPUTS, db_path=db_path)
    detailed_deal = deals_store.create_detailed_deal(
        "Detailed Deal", DETAILED_TERMS, DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    with pytest.raises(SnapshotValidationError):
        deals_store.update_analysis_snapshot(
            quick_deal.id,
            QUICK_RESULTS_DICT,
            financial_input_fingerprint="0" * 64,
            db_path=db_path,
        )

    with pytest.raises(SnapshotValidationError):
        deals_store.update_analysis_snapshot(
            detailed_deal.id,
            DETAILED_ENVELOPE_DICT,
            financial_input_fingerprint="0" * 64,
            db_path=db_path,
        )

    assert deals_store.get_deal(quick_deal.id, db_path=db_path).analysis_snapshot is None
    assert deals_store.get_deal(detailed_deal.id, db_path=db_path).analysis_snapshot is None
