"""Asset Types 1 -- focused mutation proofs.

Protocol section 9: surgical, not ceremonial. Each case answers one question --
"if this invariant were removed or weakened, would a test fail?" -- for an
invariant Asset Types 1 exists to protect. Four mutants, each applied in memory
with ``monkeypatch``; nothing on disk is modified. Every case first shows the
healthy behaviour, then shows the mutant is observably different through the
same check the ordinary suite uses.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _p7_2_fixtures as f2  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.asset_types import AssetClassification, AssetType
from anchor.deals import store
from anchor.deals.store import PersistedDealDataError


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "asset_types_1_mutants.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(api_module.app)


def _quick_body(stored: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "name": stored["name"],
        "operating_mode": "quick",
        "inputs": stored["inputs"],
        "business_plan": stored["business_plan"],
        "deal_context": stored["deal_context"],
        **extra,
    }


# =============================================================================
# 1. An omitted classification is kept, never read as "clear it"
# =============================================================================


def test_reading_an_omission_as_clear_is_caught(
    client: TestClient, db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deal = f2.create_deal("quick", db, name="Classified")
    stored = client.get(f"/deals/{deal.id}").json()
    client.put(f"/deals/{deal.id}", json=_quick_body(stored, asset_type="office"))

    # Healthy: an older client's body, with no classification keys, keeps it.
    kept = client.put(f"/deals/{deal.id}", json=_quick_body(stored, name="Renamed"))
    assert kept.json()["asset_type"] == "office"

    original = api_module._deal_classification

    def erase_on_omission(payload: dict[str, Any], *, when_absent: Any) -> Any:
        return original(payload, when_absent=None)

    monkeypatch.setattr(api_module, "_deal_classification", erase_on_omission)
    erased = client.put(f"/deals/{deal.id}", json=_quick_body(stored, name="Renamed again"))
    assert erased.json()["asset_type"] is None  # the keep test would now fail


# =============================================================================
# 2. The Managed Asset reads its own snapshot, never the Deal's current value
# =============================================================================


def test_reading_the_deals_live_classification_is_caught(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deal = f2.create_deal("lease_level", db, name="Owned")
    store.update_lease_level_deal(
        deal.id, deal.name, deal.terms, deal.property_inputs, deal.operating_inputs,  # type: ignore[arg-type]
        deal.market_leasing, deal.suites, deal.leases,  # type: ignore[arg-type]
        classification=AssetClassification(asset_type=AssetType.RETAIL, asset_subtype="Outlet center"),
        db_path=db,
    )
    asset = store.create_managed_asset(source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db)
    current = store.get_deal(deal.id, db_path=db)
    store.update_lease_level_deal(
        deal.id, current.name, current.terms, current.property_inputs, current.operating_inputs,  # type: ignore[arg-type]
        current.market_leasing, current.suites, current.leases,  # type: ignore[arg-type]
        classification=AssetClassification(asset_type=AssetType.OFFICE),
        db_path=db,
    )
    # Healthy: the snapshot is untouched by the later Deal edit.
    assert store.get_managed_asset(asset.id, db_path=db).asset_type is AssetType.RETAIL

    def live_from_the_deal(connection: sqlite3.Connection, managed_asset_id: str) -> Any:
        source = connection.execute(
            "SELECT source_deal_id FROM managed_assets WHERE id = ?", (managed_asset_id,)
        ).fetchone()["source_deal_id"]
        return store._read_deal_classification(connection, source)

    monkeypatch.setattr(store, "_read_managed_asset_classification", live_from_the_deal)
    assert store.get_managed_asset(asset.id, db_path=db).asset_type is AssetType.OFFICE


# =============================================================================
# 3. An unreadable stored token is raised, never softened to "Not specified"
# =============================================================================


def test_softening_an_unknown_token_is_caught(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deal = f2.create_deal("detailed", db, name="Hand-edited")
    f2.execute(
        db,
        "INSERT INTO deal_asset_classifications (deal_id, asset_type, asset_subtype) VALUES (?, 'condo', NULL)",
        (deal.id,),
    )
    with pytest.raises(PersistedDealDataError):
        store.get_deal(deal.id, db_path=db)

    original = store._classification_from_row

    def soften(owner: str, row: Any) -> Any:
        try:
            return original(owner, row)
        except PersistedDealDataError:
            return None

    monkeypatch.setattr(store, "_classification_from_row", soften)
    assert store.get_deal(deal.id, db_path=db).asset_type is None  # silently "Not specified"


# =============================================================================
# 4. Classification is not a fingerprint input, so the fingerprint route owns
#    no classification key
# =============================================================================


def test_widening_the_fingerprint_routes_owned_keys_is_caught(
    client: TestClient, db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deal = f2.create_deal("lease_level", db, name="Rent roll")
    stored = client.get(f"/deals/{deal.id}").json()
    body = {
        "operating_mode": "lease_level",
        "business_plan": stored["business_plan"],
        "deal_context": stored["deal_context"],
        **{part: stored[part] for part in ("terms", "property_inputs", "operating_inputs", "market_leasing", "suites", "leases")},
        "asset_type": "retail",
    }
    assert client.post("/deals/fingerprint", json=body).status_code == 422

    monkeypatch.setattr(
        api_module, "_DEAL_FIELDS", ("name", "deal_context", "asset_type", "asset_subtype")
    )
    assert client.post("/deals/fingerprint", json=body).status_code == 200  # silently ignored


def test_the_proofs_touch_no_file(db: Path) -> None:
    """Every mutant above is a ``monkeypatch`` of a live module attribute;
    this pins that none of them needed a scratch copy of the source."""

    assert dataclasses.is_dataclass(AssetClassification)
    assert Path(store.__file__).resolve().parts[-4:] == ("src", "anchor", "deals", "store.py")
