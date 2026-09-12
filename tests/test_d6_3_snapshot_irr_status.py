"""D6.3 closeout -- IrrStatus rehydration from persisted analysis snapshots.

D6.3 made ``unlevered_irr_status`` and ``levered_irr_status`` enum-valued
required result fields. A snapshot stores each as its string token; before this
closeout the decoder handed that token back as a bare ``str``, so a restored
result violated its own contract and Pydantic warned ("Expected `enum`") when a
deal response re-serialised it. ``StrEnum`` equality hid the defect, so every
type assertion here is ``type(...) is IrrStatus`` / ``is <member>``, never ``==``.

The invariants:

- **Type.** A current Quick or Detailed snapshot decodes to real ``IrrStatus``
  members -- through the store's own write and read paths.
- **JSON unchanged.** enum -> token -> enum -> the same token; no payload moves.
- **Strict.** An unknown token is invalid data: refused on a write
  (``SnapshotValidationError``), treated as an absent cache on a read -- never a
  default, never passed through.
- **No fabrication.** A snapshot missing the D6 fields is still absent.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import sqlite3
import warnings

import pytest
from pydantic import TypeAdapter

from anchor.analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.deals import store as deals_store
from anchor.deals.contracts import Deal
from anchor.deals.fingerprint import fingerprint_detailed_inputs, fingerprint_quick_inputs
from anchor.deals.store import (
    _ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
    SnapshotValidationError,
    _decode_snapshot,
    _detailed_analysis_snapshot_from_dict,
    _quick_analysis_snapshot_from_dict,
)
from anchor.engine.contracts import AcquisitionResults, IrrStatus

from test_d6_2_owner_cash_flow_engine import (
    DETAILED_OPERATING,
    DETAILED_TERMS,
    QUICK,
    bits,
    capital,
    plan,
)

D6_3_FIELDS = (
    "net_additional_equity_requirement_by_year",
    "total_equity_invested",
    "total_cash_returned",
    "total_profit",
    "unlevered_irr_status",
    "levered_irr_status",
)
D6_FIELDS = D6_3_FIELDS + (
    "closing_project_capital",
    "project_capital_by_year",
    "post_hold_project_capital",
    "owner_expenses_by_year",
    "property_cash_flow_by_year",
    "unlevered_owner_cash_flow_by_year",
    "levered_owner_cash_flow_by_year",
    "total_closing_uses",
    "total_closing_sources",
)

# A Year 2 deficit makes the levered IRR unavailable, so the snapshots carry a
# non-default status. The store checks provenance by the inputs' fingerprint
# only, so which Business Plan produced a result is irrelevant to decoding.
QUICK_RESULTS = analyze_quick_acquisition_with_business_plan(
    QUICK, business_plan=plan(capital(18, 2_500_000.0))
)
DETAILED_ENVELOPE = analyze_detailed_acquisition_with_business_plan(
    DETAILED_TERMS, DETAILED_OPERATING, business_plan=plan(capital(18, 1_000_000.0))
)


def as_json(value: object) -> dict:
    """A genuine JSON round trip -- what the API hands the store."""

    return json.loads(json.dumps(dataclasses.asdict(value)))


def canonical(value: object) -> str:
    return json.dumps(dataclasses.asdict(value), sort_keys=True)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "d6-3-snapshots.db"


def save_quick(db_path: Path, snapshot: dict) -> Deal:
    deal = deals_store.create_deal("Quick D6.3", QUICK, db_path=db_path)
    return deals_store.update_analysis_snapshot(
        deal.id,
        snapshot,
        financial_input_fingerprint=fingerprint_quick_inputs(QUICK),
        db_path=db_path,
    )


def save_detailed(db_path: Path, snapshot: dict) -> Deal:
    deal = deals_store.create_detailed_deal(
        "Detailed D6.3", DETAILED_TERMS, DETAILED_OPERATING, db_path=db_path
    )
    return deals_store.update_analysis_snapshot(
        deal.id,
        snapshot,
        financial_input_fingerprint=fingerprint_detailed_inputs(DETAILED_TERMS, DETAILED_OPERATING),
        db_path=db_path,
    )


def overwrite_stored_snapshot(db_path: Path, table: str, deal_id: str, snapshot: dict) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            f"UPDATE {table} SET analysis_snapshot = ? WHERE id = ?",
            (json.dumps(snapshot), deal_id),
        )
        connection.commit()
    finally:
        connection.close()


def assert_status_types(results: AcquisitionResults) -> None:
    assert type(results.unlevered_irr_status) is IrrStatus
    assert type(results.levered_irr_status) is IrrStatus


def test_the_fixtures_carry_a_non_default_status() -> None:
    assert QUICK_RESULTS.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES
    assert DETAILED_ENVELOPE.results.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES


# =============================================================================
# Type -- through the store's own write and read paths
# =============================================================================


def test_a_quick_snapshot_rehydrates_irr_status_members(db_path: Path) -> None:
    payload = as_json(QUICK_RESULTS)
    assert payload["levered_irr_status"] == "multiple_sign_changes"

    deal = save_quick(db_path, payload)
    written = deal.analysis_snapshot
    restored = deals_store.get_deal(deal.id, db_path=db_path).analysis_snapshot

    for snapshot in (written, restored):
        assert isinstance(snapshot, AcquisitionResults)
        assert_status_types(snapshot)
        assert snapshot.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES
        assert snapshot.unlevered_irr_status is QUICK_RESULTS.unlevered_irr_status
        # Every D6.3 field, and every other field, exactly as analysed.
        for name in D6_3_FIELDS:
            assert bits(getattr(snapshot, name)) == bits(getattr(QUICK_RESULTS, name)), name
        assert snapshot == QUICK_RESULTS
        # enum -> token -> enum -> the same token.
        assert canonical(snapshot) == canonical(QUICK_RESULTS)
        assert json.loads(canonical(snapshot)) == payload


def test_a_detailed_snapshot_rehydrates_irr_status_members(db_path: Path) -> None:
    payload = as_json(DETAILED_ENVELOPE)

    written = save_detailed(db_path, payload)
    restored = deals_store.get_deal(written.id, db_path=db_path)

    for deal in (written, restored):
        envelope = deal.analysis_snapshot
        assert_status_types(envelope.results)
        assert envelope.results.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES
        for name in D6_3_FIELDS:
            assert bits(getattr(envelope.results, name)) == bits(
                getattr(DETAILED_ENVELOPE.results, name)
            ), name
        assert envelope == DETAILED_ENVELOPE
        assert json.loads(canonical(envelope)) == payload


@pytest.mark.parametrize("member", list(IrrStatus), ids=lambda m: m.value)
def test_every_status_token_decodes_to_its_member(member: IrrStatus) -> None:
    quick = {**as_json(QUICK_RESULTS), "levered_irr_status": member.value}
    detailed = as_json(DETAILED_ENVELOPE)
    detailed["results"]["unlevered_irr_status"] = member.value

    assert _quick_analysis_snapshot_from_dict(quick).levered_irr_status is member
    assert (
        _detailed_analysis_snapshot_from_dict(detailed).results.unlevered_irr_status is member
    )


# =============================================================================
# Serialisation -- the Pydantic warning is gone because the type is right
# =============================================================================


def dump_without_warnings(adapter: TypeAdapter, value: object) -> bytes:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return adapter.dump_json(value)


def test_restored_deals_serialise_without_warnings_and_without_changing_json(
    db_path: Path,
) -> None:
    quick_deal = deals_store.get_deal(save_quick(db_path, as_json(QUICK_RESULTS)).id, db_path=db_path)
    detailed_deal = deals_store.get_deal(
        save_detailed(db_path, as_json(DETAILED_ENVELOPE)).id, db_path=db_path
    )

    adapter = TypeAdapter(Deal)
    for deal, original in ((quick_deal, QUICK_RESULTS), (detailed_deal, DETAILED_ENVELOPE)):
        body = json.loads(dump_without_warnings(adapter, deal))
        snapshot = body["analysis_snapshot"]
        results = snapshot.get("results", snapshot)
        expected = as_json(original)
        expected_results = expected.get("results", expected)
        assert results["levered_irr_status"] == "multiple_sign_changes"
        for name in D6_3_FIELDS:
            assert results[name] == expected_results[name], name


def test_the_warning_oracle_detects_the_old_str_shape() -> None:
    """Self-test: a result carrying the bare ``str`` the decoder used to return
    does warn -- and serialises to the very same JSON -- so the check above is
    proving the type, not passing vacuously."""

    adapter = TypeAdapter(AcquisitionResults)
    as_str = dataclasses.replace(
        QUICK_RESULTS,
        levered_irr_status="multiple_sign_changes",  # type: ignore[arg-type]
        unlevered_irr_status=str(QUICK_RESULTS.unlevered_irr_status),  # type: ignore[arg-type]
    )

    with pytest.warns(UserWarning, match="Expected `enum`"):
        str_json = adapter.dump_json(as_str)
    assert json.loads(str_json) == json.loads(dump_without_warnings(adapter, QUICK_RESULTS))


# =============================================================================
# Strict -- unknown tokens are invalid data; old shapes stay absent
# =============================================================================


@pytest.mark.parametrize("token", ["not_a_real_status", "DEFINED", "", 7])
def test_an_unknown_status_is_refused_on_write(db_path: Path, token: object) -> None:
    quick = {**as_json(QUICK_RESULTS), "levered_irr_status": token}
    detailed = as_json(DETAILED_ENVELOPE)
    detailed["results"]["unlevered_irr_status"] = token

    with pytest.raises(SnapshotValidationError, match="IrrStatus"):
        _quick_analysis_snapshot_from_dict(quick)
    with pytest.raises(SnapshotValidationError, match="IrrStatus"):
        _detailed_analysis_snapshot_from_dict(detailed)
    with pytest.raises(SnapshotValidationError):
        save_quick(db_path, quick)


def test_an_unknown_stored_status_is_an_absent_cache(db_path: Path) -> None:
    quick_deal = save_quick(db_path, as_json(QUICK_RESULTS))
    detailed_deal = save_detailed(db_path, as_json(DETAILED_ENVELOPE))

    bad_quick = {**as_json(QUICK_RESULTS), "levered_irr_status": "not_a_real_status"}
    bad_detailed = as_json(DETAILED_ENVELOPE)
    bad_detailed["results"]["levered_irr_status"] = "not_a_real_status"
    overwrite_stored_snapshot(db_path, "deals", quick_deal.id, bad_quick)
    overwrite_stored_snapshot(db_path, "detailed_deals", detailed_deal.id, bad_detailed)

    # Deal Open still works; the cache is simply unavailable, to be recomputed.
    assert deals_store.get_deal(quick_deal.id, db_path=db_path).analysis_snapshot is None
    assert deals_store.get_deal(detailed_deal.id, db_path=db_path).analysis_snapshot is None


def test_a_snapshot_missing_the_d6_fields_is_still_absent(db_path: Path) -> None:
    quick_deal = save_quick(db_path, as_json(QUICK_RESULTS))
    detailed_deal = save_detailed(db_path, as_json(DETAILED_ENVELOPE))

    legacy_quick = {k: v for k, v in as_json(QUICK_RESULTS).items() if k not in D6_FIELDS}
    only_statuses_missing = {
        k: v
        for k, v in as_json(QUICK_RESULTS).items()
        if k not in ("unlevered_irr_status", "levered_irr_status")
    }
    legacy_detailed = as_json(DETAILED_ENVELOPE)
    legacy_detailed["results"] = {
        k: v for k, v in legacy_detailed["results"].items() if k not in D6_FIELDS
    }

    for raw in (legacy_quick, only_statuses_missing):
        assert (
            _decode_snapshot(
                raw_json=json.dumps(raw),
                stored_schema_version=_ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
                current_schema_version=_ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
                stored_fingerprint="same",
                expected_fingerprint="same",
                decoder=_quick_analysis_snapshot_from_dict,
            )
            is None
        )
    overwrite_stored_snapshot(db_path, "deals", quick_deal.id, legacy_quick)
    overwrite_stored_snapshot(db_path, "detailed_deals", detailed_deal.id, legacy_detailed)
    assert deals_store.get_deal(quick_deal.id, db_path=db_path).analysis_snapshot is None
    assert deals_store.get_deal(detailed_deal.id, db_path=db_path).analysis_snapshot is None
    assert _ANALYSIS_SNAPSHOT_SCHEMA_VERSION == 1
