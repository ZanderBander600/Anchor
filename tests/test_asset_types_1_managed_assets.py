"""Asset Types 1 -- the Managed Asset classification snapshot, the retirement of
the hand-typed property type, and the classification parser itself.

``docs/architecture/ASSET_TYPES_1_CLASSIFICATION.md`` Sections 2 and 5.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _am1_fixtures as am  # type: ignore[import-not-found]
import _p7_2_fixtures as f2  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.asset_types import (
    MAX_ASSET_SUBTYPE_LENGTH,
    NOT_SPECIFIED_LABEL,
    AssetClassification,
    AssetClassificationError,
    AssetClassificationIssueCode as Code,
    AssetType,
    asset_type_label,
    parse_asset_classification,
)
from anchor.asset_management import ManagedAsset, analyze_asset_performance
from anchor.deals import store
from anchor.deals.store import PersistedDealDataError

MODES = ("quick", "detailed", "lease_level")


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "asset_types_1_am.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db: Path) -> TestClient:
    return TestClient(api_module.app)


def _rows(db: Path, sql: str, parameters: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(db)
    try:
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _analyzed(db: Path, mode: str, classification: AssetClassification | None) -> Any:
    deal = f2.create_deal(mode, db, name=f"{mode} acquisition")
    if classification is not None:
        current = store.get_deal(deal.id, db_path=db)
        _update(db, current, classification)
    if mode != "lease_level":
        store.update_analysis_snapshot(
            deal.id,
            dataclasses.asdict(f2.analyze_deal(deal)),
            financial_input_fingerprint=f2.deal_fingerprint(deal),
            db_path=db,
        )
    return store.get_deal(deal.id, db_path=db)


def _update(db: Path, deal: Any, classification: AssetClassification | None) -> Any:
    """Reclassify a Deal through the store's own update, in its own mode,
    rewriting nothing else."""

    if deal.operating_mode.value == "quick":
        return store.update_deal(
            deal.id, deal.name, deal.inputs, deal_context=deal.deal_context,
            business_plan=deal.business_plan, classification=classification, db_path=db,
        )
    if deal.operating_mode.value == "detailed":
        return store.update_detailed_deal(
            deal.id, deal.name, deal.terms, deal.detailed_operating_inputs,
            deal_context=deal.deal_context, business_plan=deal.business_plan,
            classification=classification, db_path=db,
        )
    return store.update_lease_level_deal(
        deal.id, deal.name, deal.terms, deal.property_inputs, deal.operating_inputs,
        deal.market_leasing, deal.suites, deal.leases, deal_context=deal.deal_context,
        business_plan=deal.business_plan, classification=classification, db_path=db,
    )


GARDEN = AssetClassification(asset_type=AssetType.MULTIFAMILY, asset_subtype="Garden apartments")


# =============================================================================
# The snapshot
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_creation_copies_the_deals_classification(mode: str, db: Path) -> None:
    deal = _analyzed(db, mode, GARDEN)
    asset = store.create_managed_asset(source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db)
    assert (asset.asset_type, asset.asset_subtype) == (AssetType.MULTIFAMILY, "Garden apartments")
    assert asset.property_type is None
    assert _rows(db, "SELECT * FROM managed_asset_classifications") == [
        (asset.id, "multifamily", "Garden apartments")
    ]
    assert store.get_managed_asset(asset.id, db_path=db) == asset
    assert store.list_managed_assets(db_path=db) == [asset]


@pytest.mark.parametrize("mode", MODES)
def test_a_later_deal_edit_never_rewrites_the_asset(mode: str, db: Path) -> None:
    deal = _analyzed(db, mode, GARDEN)
    asset = store.create_managed_asset(source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db)

    for later in (
        AssetClassification(asset_type=AssetType.OTHER, asset_subtype="Student housing"),
        None,
        AssetClassification(asset_type=AssetType.MIXED_USE),
    ):
        _update(db, store.get_deal(deal.id, db_path=db), later)
        assert store.get_deal(deal.id, db_path=db).classification == later
        assert store.get_managed_asset(asset.id, db_path=db) == asset


def test_an_unclassified_deal_yields_an_unclassified_asset(db: Path) -> None:
    deal = _analyzed(db, "quick", None)
    asset = store.create_managed_asset(source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db)
    assert (asset.asset_type, asset.asset_subtype, asset.property_type) == (None, None, None)
    assert _rows(db, "SELECT * FROM managed_asset_classifications") == []
    # Classifying the Deal afterwards does not reach the asset either.
    _update(db, store.get_deal(deal.id, db_path=db), GARDEN)
    assert store.get_managed_asset(asset.id, db_path=db).asset_type is None


def test_creating_an_asset_writes_no_deal_state(db: Path) -> None:
    deal = _analyzed(db, "quick", GARDEN)
    before = f2.legacy_rows(db)
    store.create_managed_asset(source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db)
    after = f2.legacy_rows(db)
    # ``legacy_rows`` covers every Deal table and the classification tables
    # (AM1's own tables are measured separately): only the snapshot moved.
    changed = {table for table in after if after[table] != before.get(table)}
    assert changed == {"managed_asset_classifications"}
    assert len(_rows(db, "SELECT id FROM managed_assets")) == 1


def test_deleting_an_asset_removes_its_snapshot_and_keeps_the_deals(db: Path) -> None:
    deal = _analyzed(db, "detailed", GARDEN)
    asset = store.create_managed_asset(source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db)
    store.delete_managed_asset(asset.id, db_path=db)
    assert _rows(db, "SELECT * FROM managed_asset_classifications") == []
    assert _rows(db, "SELECT deal_id, asset_type FROM deal_asset_classifications") == [(deal.id, "multifamily")]


def test_an_unreadable_snapshot_is_raised(db: Path) -> None:
    deal = _analyzed(db, "quick", None)
    asset = store.create_managed_asset(source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db)
    f2.execute(
        db,
        "INSERT INTO managed_asset_classifications (managed_asset_id, asset_type, asset_subtype) VALUES (?, ?, ?)",
        (asset.id, "Multifamily", None),
    )
    with pytest.raises(PersistedDealDataError):
        store.get_managed_asset(asset.id, db_path=db)
    with pytest.raises(PersistedDealDataError):
        store.list_managed_assets(db_path=db)


def test_a_legacy_property_type_is_read_back_verbatim_and_never_mapped(db: Path) -> None:
    """A row written before Asset Types 1 carried hand-typed text. It stays, and
    it is not a classification."""

    deal = _analyzed(db, "quick", GARDEN)
    asset = store.create_managed_asset(source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db)
    other_deal = _analyzed(db, "detailed", None)
    f2.execute(
        db,
        "INSERT INTO managed_assets (id, source_deal_id, name, acquisition_date, property_type, market, "
        "acquisition_fingerprint, created_at, updated_at) VALUES ('legacy', ?, 'Legacy', '2025-01-01', "
        "'multifamily', NULL, 'fp', '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00')",
        (other_deal.id,),
    )
    legacy = store.get_managed_asset("legacy", db_path=db)
    assert legacy.property_type == "multifamily"
    assert (legacy.asset_type, legacy.asset_subtype) == (None, None)
    assert {item.id for item in store.list_managed_assets(db_path=db)} == {asset.id, "legacy"}


def test_classification_changes_no_monthly_result(db: Path) -> None:
    """The performance engine takes reports only; an asset's classification is
    not among its inputs, so two identically-reported assets of different types
    produce identical results."""

    report = am.report()
    first = analyze_asset_performance(managed_asset_id="a", reporting_month=am.MARCH, reports=[report])
    second = analyze_asset_performance(managed_asset_id="a", reporting_month=am.MARCH, reports=[report])
    assert first == second
    import inspect

    assert "asset_type" not in inspect.signature(analyze_asset_performance).parameters


def test_the_managed_asset_contract_refuses_an_inconsistent_pair() -> None:
    fields = dict(
        id="a", source_deal_id="d", name="n", acquisition_date=date(2026, 1, 1), property_type=None,
        market=None, acquisition_fingerprint="fp", created_at=am.MARCH, updated_at=am.MARCH,
    )
    with pytest.raises(ValueError):
        ManagedAsset(**fields, asset_subtype="Orphan")  # type: ignore[arg-type]
    with pytest.raises(AssetClassificationError):
        ManagedAsset(**fields, asset_type=AssetType.OTHER)  # type: ignore[arg-type]


# =============================================================================
# The API: the property type is retired, the snapshot is exposed
# =============================================================================


def _create_body(deal_id: str, **extra: Any) -> dict[str, Any]:
    return {"source_deal_id": deal_id, "name": None, "acquisition_date": "2026-10-01", "market": None, **extra}


def test_the_api_exposes_the_snapshot(client: TestClient, db: Path) -> None:
    deal = _analyzed(db, "quick", AssetClassification(asset_type=AssetType.OTHER, asset_subtype="Marina"))
    response = client.post("/managed-assets", json=_create_body(deal.id))
    assert response.status_code == 200, response.text
    asset = response.json()
    assert (asset["asset_type"], asset["asset_subtype"], asset["property_type"]) == ("other", "Marina", None)
    assert client.get(f"/managed-assets/{asset['id']}").json() == asset
    assert client.get("/managed-assets").json() == [asset]


def test_a_stated_property_type_is_refused_rather_than_dropped(client: TestClient, db: Path) -> None:
    deal = _analyzed(db, "quick", GARDEN)
    response = client.post("/managed-assets", json=_create_body(deal.id, property_type="Multifamily"))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert [(issue["code"], issue["field"]) for issue in detail] == [("property_type_retired", "property_type")]
    assert _rows(db, "SELECT * FROM managed_assets") == []


def test_a_null_property_type_from_an_older_client_is_accepted(client: TestClient, db: Path) -> None:
    deal = _analyzed(db, "quick", GARDEN)
    response = client.post("/managed-assets", json=_create_body(deal.id, property_type=None))
    assert response.status_code == 200
    assert response.json()["asset_type"] == "multifamily"


def test_the_body_cannot_state_a_classification_of_its_own(client: TestClient, db: Path) -> None:
    """One classification source: the Deal. A body that tries to author one is
    refused as carrying unknown fields."""

    deal = _analyzed(db, "quick", GARDEN)
    response = client.post("/managed-assets", json=_create_body(deal.id, asset_type="office"))
    assert response.status_code == 422
    assert _rows(db, "SELECT * FROM managed_assets") == []


# =============================================================================
# The parser
# =============================================================================


def test_not_specified_is_the_absence_of_a_type() -> None:
    assert parse_asset_classification(None, None) is None
    assert parse_asset_classification(None, "   ") is None
    assert asset_type_label(None) == NOT_SPECIFIED_LABEL == "Not specified"
    assert asset_type_label(AssetType.SELF_STORAGE) == "Self-Storage"


@pytest.mark.parametrize("member", list(AssetType))
def test_every_value_parses_to_its_member(member: AssetType) -> None:
    subtype = "Described" if member is AssetType.OTHER else None
    parsed = parse_asset_classification(member.value, subtype)
    assert parsed == AssetClassification(asset_type=member, asset_subtype=subtype)


def _codes(asset_type: object, asset_subtype: object) -> list[str]:
    with pytest.raises(AssetClassificationError) as raised:
        parse_asset_classification(asset_type, asset_subtype)
    return [issue.code.value for issue in raised.value.issues]


def test_the_parser_refusals_are_typed() -> None:
    assert _codes("Office", None) == [Code.INVALID_ASSET_TYPE]
    assert _codes("office", "x" * (MAX_ASSET_SUBTYPE_LENGTH + 1)) == [Code.ASSET_SUBTYPE_TOO_LONG]
    assert _codes("other", "  ") == [Code.ASSET_SUBTYPE_REQUIRED]
    assert _codes(None, "Garden") == [Code.ASSET_SUBTYPE_WITHOUT_TYPE]
    assert _codes("office", "line\nbreak") == [Code.INVALID_ASSET_SUBTYPE]
    assert _codes("office", 3) == [Code.INVALID_ASSET_SUBTYPE]


def test_the_refusal_is_not_a_value_error() -> None:
    """A caller that catches every validation failure by base class must not
    silently swallow a classification refusal."""

    assert not issubclass(AssetClassificationError, ValueError)


def test_the_limit_counts_characters_not_bytes() -> None:
    accented = "é" * MAX_ASSET_SUBTYPE_LENGTH
    assert parse_asset_classification("office", accented) == AssetClassification(
        asset_type=AssetType.OFFICE, asset_subtype=accented
    )
