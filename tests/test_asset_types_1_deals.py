"""Asset Types 1 -- Deal classification through the store and the API, in all
three operating modes, and the proof that classification is non-economic.

``docs/architecture/ASSET_TYPES_1_CLASSIFICATION.md`` Sections 3, 4 and 6.
Every claim here is measured through the public ``/deals`` routes or the
database itself, never asserted by the code that makes it.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
import _p7_2_fixtures as f2  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.ai.contracts import AIAnalysis, DealStory
from anchor.asset_types import (
    ASSET_TYPE_LABELS,
    MAX_ASSET_SUBTYPE_LENGTH,
    AssetClassification,
    AssetClassificationError,
    AssetType,
)
from anchor.contracts import OperatingMode
from anchor.deals import store
from anchor.deals.contracts import Deal
from anchor.deals.fingerprint import fingerprint_ai
from anchor.deals.store import PersistedDealDataError

MODES = ("quick", "detailed", "lease_level")

AI = AIAnalysis(
    executive_summary="A stabilised asset.",
    investment_view="Proceed, subject to diligence.",
    strengths=("Durable coverage.",),
    risks=("Exit cap sensitivity.",),
    return_drivers=("Exit cap rate.",),
    downside_analysis="Coverage holds.",
    capital_structure_analysis="Modest leverage.",
    break_even_analysis="Not supplied.",
    questions_to_investigate=("Confirm market rent.",),
    confidence_notes=("None.",),
    deal_story=DealStory(
        investment_view="Income-led.", key_strengths=("Coverage.",), key_risks=("Exit cap.",), model_gap=None
    ),
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "asset_types_1.db"
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


def _body(stored: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A ``/deals`` write body rebuilt from a stored Deal's own response -- the
    same round trip the product performs on Update Deal."""

    mode = stored["operating_mode"]
    body: dict[str, Any] = {
        "name": stored["name"],
        "operating_mode": mode,
        "deal_context": stored["deal_context"],
        "business_plan": stored["business_plan"],
    }
    if mode == "quick":
        body["inputs"] = stored["inputs"]
    elif mode == "detailed":
        body["terms"] = stored["terms"]
        body["detailed_operating_inputs"] = stored["detailed_operating_inputs"]
    else:
        for part in ("terms", "property_inputs", "operating_inputs", "market_leasing", "suites", "leases"):
            body[part] = stored[part]
    body.update(extra)
    return body


def _analysis_request(stored: dict[str, Any]) -> dict[str, Any]:
    """The ``/analyze`` request for a stored Deal. Quick's inputs are flat."""

    body = _body(stored)
    body.pop("name")
    body.pop("deal_context")
    if stored["operating_mode"] == "quick":
        body.update(body.pop("inputs"))
    return body


def _fingerprint_request(stored: dict[str, Any]) -> dict[str, Any]:
    body = _body(stored)
    body.pop("name")
    return body


def _template(db: Path, mode: str) -> dict[str, Any]:
    """A saved Deal of ``mode`` read back as JSON, to build bodies from."""

    deal = f2.create_deal(mode, db, name=f"{mode} template")
    return TestClient(api_module.app).get(f"/deals/{deal.id}").json()


def _create(client: TestClient, db: Path, mode: str, **classification: Any) -> dict[str, Any]:
    template = _template(db, mode)
    response = client.post("/deals", json=_body(template, name=f"{mode} deal", **classification))
    assert response.status_code == 200, response.text
    return response.json()


def _stored_classification(db: Path, deal_id: str) -> list[tuple[Any, ...]]:
    return _rows(
        db, "SELECT asset_type, asset_subtype FROM deal_asset_classifications WHERE deal_id = ?", (deal_id,)
    )


# =============================================================================
# Create, read, list -- every mode
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_a_deal_is_created_with_a_type_and_an_authored_subtype(
    mode: str, client: TestClient, db: Path
) -> None:
    created = _create(client, db, mode, asset_type="industrial", asset_subtype="Last-mile warehouse")
    assert (created["asset_type"], created["asset_subtype"]) == ("industrial", "Last-mile warehouse")
    assert created["operating_mode"] == mode

    read = client.get(f"/deals/{created['id']}").json()
    assert (read["asset_type"], read["asset_subtype"]) == ("industrial", "Last-mile warehouse")
    listed = next(deal for deal in client.get("/deals").json() if deal["id"] == created["id"])
    assert (listed["asset_type"], listed["asset_subtype"]) == ("industrial", "Last-mile warehouse")
    # One canonical representation: the database holds the wire value itself.
    assert _stored_classification(db, created["id"]) == [("industrial", "Last-mile warehouse")]


@pytest.mark.parametrize("asset_type", [member.value for member in AssetType])
def test_every_controlled_type_round_trips(asset_type: str, client: TestClient, db: Path) -> None:
    subtype = "Described by the analyst" if asset_type == "other" else None
    created = _create(client, db, "quick", asset_type=asset_type, asset_subtype=subtype)
    read = client.get(f"/deals/{created['id']}").json()
    assert (read["asset_type"], read["asset_subtype"]) == (asset_type, subtype)
    assert _stored_classification(db, created["id"]) == [(asset_type, subtype)]


@pytest.mark.parametrize("mode", MODES)
def test_the_subtype_is_trimmed_and_otherwise_preserved_exactly(
    mode: str, client: TestClient, db: Path
) -> None:
    created = _create(client, db, mode, asset_type="office", asset_subtype="  Medical office -- Class B+  ")
    assert created["asset_subtype"] == "Medical office -- Class B+"
    # Capitalization and wording are the analyst's; nothing is mapped.
    created = _create(client, db, mode, asset_type="multifamily", asset_subtype="gARDEN apartments")
    assert created["asset_subtype"] == "gARDEN apartments"


@pytest.mark.parametrize("subtype", ["", "   ", "\t  ", None])
def test_a_blank_subtype_means_absent(subtype: Any, client: TestClient, db: Path) -> None:
    created = _create(client, db, "quick", asset_type="retail", asset_subtype=subtype)
    assert created["asset_subtype"] is None
    assert _stored_classification(db, created["id"]) == [("retail", None)]


def test_a_deal_created_without_classification_keys_is_not_specified(
    client: TestClient, db: Path
) -> None:
    """A client that predates classification states nothing, and nothing is
    inferred: no row, and both fields null."""

    template = _template(db, "quick")
    response = client.post("/deals", json=_body(template, name="Older client"))
    assert response.status_code == 200
    assert (response.json()["asset_type"], response.json()["asset_subtype"]) == (None, None)
    assert _stored_classification(db, response.json()["id"]) == []


def test_a_legacy_deal_with_no_row_reads_not_specified_and_reading_writes_nothing(
    client: TestClient, db: Path
) -> None:
    deal = f2.create_deal("detailed", db, name="Legacy")
    for _ in range(2):
        assert client.get(f"/deals/{deal.id}").json()["asset_type"] is None
        client.get("/deals")
    assert _rows(db, "SELECT * FROM deal_asset_classifications") == []


# =============================================================================
# Refusals
# =============================================================================


@pytest.mark.parametrize(
    "asset_type",
    ["Multifamily", "MULTIFAMILY", " multifamily", "multi-family", "condo", "", 7, True, ["office"]],
)
def test_an_uncontrolled_type_is_refused_with_a_typed_422(
    asset_type: Any, client: TestClient, db: Path
) -> None:
    template = _template(db, "quick")
    response = client.post("/deals", json=_body(template, asset_type=asset_type))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert [issue["code"] for issue in detail] == ["invalid_asset_type"]
    assert detail[0]["field_id"] == "asset_type"
    assert "multifamily" in detail[0]["message"]  # it names what is allowed
    assert _rows(db, "SELECT * FROM deal_asset_classifications") == []


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("subtype", [None, "", "    "])
def test_other_without_a_meaningful_subtype_is_refused(
    mode: str, subtype: Any, client: TestClient, db: Path
) -> None:
    template = _template(db, mode)
    response = client.post("/deals", json=_body(template, asset_type="other", asset_subtype=subtype))
    assert response.status_code == 422
    assert [issue["code"] for issue in response.json()["detail"]] == ["asset_subtype_required"]


def test_other_with_a_subtype_is_accepted(client: TestClient, db: Path) -> None:
    created = _create(client, db, "quick", asset_type="other", asset_subtype="Cold storage campus")
    assert (created["asset_type"], created["asset_subtype"]) == ("other", "Cold storage campus")


def test_the_subtype_length_limit_is_measured_after_trimming(client: TestClient, db: Path) -> None:
    limit = "x" * MAX_ASSET_SUBTYPE_LENGTH
    assert _create(client, db, "quick", asset_type="office", asset_subtype=f"  {limit}  ")[
        "asset_subtype"
    ] == limit

    template = _template(db, "quick")
    response = client.post("/deals", json=_body(template, asset_type="office", asset_subtype=limit + "x"))
    assert response.status_code == 422
    assert [issue["code"] for issue in response.json()["detail"]] == ["asset_subtype_too_long"]


@pytest.mark.parametrize("subtype", ["Garden\napartments", "Tab\there", 12, ["x"]])
def test_a_subtype_that_is_not_one_line_of_text_is_refused(
    subtype: Any, client: TestClient, db: Path
) -> None:
    template = _template(db, "quick")
    response = client.post("/deals", json=_body(template, asset_type="office", asset_subtype=subtype))
    assert response.status_code == 422
    assert [issue["code"] for issue in response.json()["detail"]] == ["invalid_asset_subtype"]


def test_a_subtype_without_a_type_is_refused(client: TestClient, db: Path) -> None:
    template = _template(db, "quick")
    response = client.post("/deals", json=_body(template, asset_subtype="Garden apartments"))
    assert response.status_code == 422
    assert [issue["code"] for issue in response.json()["detail"]] == ["asset_subtype_without_type"]


def test_both_fields_are_reported_in_one_round_trip(client: TestClient, db: Path) -> None:
    template = _template(db, "quick")
    response = client.post(
        "/deals", json=_body(template, asset_type="Hotel", asset_subtype="x" * (MAX_ASSET_SUBTYPE_LENGTH + 1))
    )
    assert response.status_code == 422
    assert sorted(issue["code"] for issue in response.json()["detail"]) == [
        "asset_subtype_too_long",
        "invalid_asset_type",
    ]


@pytest.mark.parametrize("mode", MODES)
def test_a_refused_update_changes_nothing(mode: str, client: TestClient, db: Path) -> None:
    created = _create(client, db, mode, asset_type="retail", asset_subtype="Grocery-anchored center")
    before = client.get(f"/deals/{created['id']}").json()
    response = client.put(f"/deals/{created['id']}", json=_body(before, name="Renamed", asset_type="other"))
    assert response.status_code == 422
    assert client.get(f"/deals/{created['id']}").json() == before


# =============================================================================
# Update
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_update_changes_the_classification(mode: str, client: TestClient, db: Path) -> None:
    created = _create(client, db, mode, asset_type="office", asset_subtype="Suburban office")
    response = client.put(
        f"/deals/{created['id']}",
        json=_body(created, asset_type="mixed_use", asset_subtype="Retail podium with residential"),
    )
    assert response.status_code == 200, response.text
    assert (response.json()["asset_type"], response.json()["asset_subtype"]) == (
        "mixed_use",
        "Retail podium with residential",
    )
    assert _stored_classification(db, created["id"]) == [("mixed_use", "Retail podium with residential")]


@pytest.mark.parametrize("mode", MODES)
def test_an_update_that_omits_classification_keeps_it(mode: str, client: TestClient, db: Path) -> None:
    """Explicit compatibility: an older client or saved fixture that never heard
    of classification cannot erase one by leaving the keys out."""

    created = _create(client, db, mode, asset_type="hospitality", asset_subtype="Select-service hotel")
    body = _body(created, name="Renamed by an older client")
    assert "asset_type" not in body and "asset_subtype" not in body
    response = client.put(f"/deals/{created['id']}", json=body)
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed by an older client"
    assert (response.json()["asset_type"], response.json()["asset_subtype"]) == (
        "hospitality",
        "Select-service hotel",
    )


def test_an_update_naming_only_one_key_states_the_whole_classification(
    client: TestClient, db: Path
) -> None:
    created = _create(client, db, "quick", asset_type="office", asset_subtype="Medical office")
    body = _body(created, asset_type="office")  # no asset_subtype key: it is absent
    response = client.put(f"/deals/{created['id']}", json=body)
    assert response.status_code == 200
    assert (response.json()["asset_type"], response.json()["asset_subtype"]) == ("office", None)


def test_an_explicit_null_type_records_not_specified(client: TestClient, db: Path) -> None:
    created = _create(client, db, "quick", asset_type="office")
    response = client.put(f"/deals/{created['id']}", json=_body(created, asset_type=None, asset_subtype=None))
    assert response.status_code == 200
    assert response.json()["asset_type"] is None
    assert _stored_classification(db, created["id"]) == []


@pytest.mark.parametrize("mode", MODES)
def test_a_classification_only_update_rewrites_no_unrelated_state(
    mode: str, client: TestClient, db: Path
) -> None:
    created = _create(client, db, mode, asset_type="retail")
    before = client.get(f"/deals/{created['id']}").json()
    response = client.put(
        f"/deals/{created['id']}", json=_body(before, asset_type="retail", asset_subtype="Power center")
    )
    after = response.json()
    changed = {key for key in before if before[key] != after[key]}
    assert changed == {"asset_subtype", "updated_at"}


# =============================================================================
# Duplicate and delete
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_duplicate_copies_the_classification_exactly(mode: str, client: TestClient, db: Path) -> None:
    created = _create(client, db, mode, asset_type="self_storage", asset_subtype="Climate-controlled")
    copy = client.post(f"/deals/{created['id']}/duplicate", json={}).json()
    assert copy["id"] != created["id"]
    assert (copy["asset_type"], copy["asset_subtype"]) == ("self_storage", "Climate-controlled")
    # The copy owns its own row: reclassifying one leaves the other alone.
    client.put(f"/deals/{copy['id']}", json=_body(copy, asset_type="industrial", asset_subtype=None))
    assert client.get(f"/deals/{created['id']}").json()["asset_type"] == "self_storage"


def test_duplicating_an_unclassified_deal_stays_not_specified(client: TestClient, db: Path) -> None:
    deal = f2.create_deal("quick", db, name="Legacy")
    copy = client.post(f"/deals/{deal.id}/duplicate", json={}).json()
    assert copy["asset_type"] is None
    assert _rows(db, "SELECT * FROM deal_asset_classifications") == []


@pytest.mark.parametrize("mode", MODES)
def test_delete_removes_the_classification_row(mode: str, client: TestClient, db: Path) -> None:
    created = _create(client, db, mode, asset_type="land_development", asset_subtype="Entitled parcel")
    assert client.delete(f"/deals/{created['id']}").status_code == 204
    assert _stored_classification(db, created["id"]) == []


def test_deleting_an_unknown_deal_rolls_back_and_touches_no_classification(
    client: TestClient, db: Path
) -> None:
    kept = _create(client, db, "quick", asset_type="office")
    assert client.delete("/deals/no-such-deal").status_code == 404
    assert _stored_classification(db, kept["id"]) == [("office", None)]


# =============================================================================
# Stored data the vocabulary no longer recognises is raised, never softened
# =============================================================================


@pytest.mark.parametrize(
    ("asset_type", "asset_subtype"),
    [("condo", None), ("Multifamily", None), ("other", None), ("office", "  padded  ")],
)
def test_an_unreadable_stored_classification_is_raised(
    asset_type: str, asset_subtype: str | None, db: Path
) -> None:
    deal = f2.create_deal("quick", db, name="Hand-edited")
    f2.execute(
        db,
        "INSERT INTO deal_asset_classifications (deal_id, asset_type, asset_subtype) VALUES (?, ?, ?)",
        (deal.id, asset_type, asset_subtype),
    )
    with pytest.raises(PersistedDealDataError):
        store.get_deal(deal.id, db_path=db)
    with pytest.raises(PersistedDealDataError):
        store.list_deals(db_path=db)


# =============================================================================
# Classification is non-economic: no result, fingerprint or snapshot moves
# =============================================================================


def _reclassify(client: TestClient, deal_id: str, **classification: Any) -> dict[str, Any]:
    current = client.get(f"/deals/{deal_id}").json()
    response = client.put(f"/deals/{deal_id}", json=_body(current, **classification))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("mode", MODES)
def test_the_analysis_is_identical_before_and_after_reclassification(
    mode: str, client: TestClient, db: Path
) -> None:
    created = _create(client, db, mode, asset_type="office")
    first = client.post("/analyze", json=_analysis_request(client.get(f"/deals/{created['id']}").json()))
    assert first.status_code == 200, first.text

    for classification in (
        {"asset_type": "other", "asset_subtype": "Data center"},
        {"asset_type": None, "asset_subtype": None},
        {"asset_type": "multifamily", "asset_subtype": "Garden apartments"},
    ):
        reloaded = _reclassify(client, created["id"], **classification)
        second = client.post("/analyze", json=_analysis_request(reloaded))
        assert second.json() == first.json()


@pytest.mark.parametrize("mode", MODES)
def test_the_financial_and_ai_fingerprints_ignore_classification(
    mode: str, client: TestClient, db: Path
) -> None:
    created = _create(client, db, mode, asset_type="office")
    before = client.post("/deals/fingerprint", json=_fingerprint_request(created)).json()
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        stored_before = store._deal_analysis_fingerprint(connection, created["id"])

    reclassified = _reclassify(client, created["id"], asset_type="retail", asset_subtype="Strip center")
    after = client.post("/deals/fingerprint", json=_fingerprint_request(reclassified)).json()
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        stored_after = store._deal_analysis_fingerprint(connection, created["id"])

    assert after == before
    assert stored_after == stored_before


@pytest.mark.parametrize("mode", ["quick", "detailed"])
def test_classification_is_not_a_fingerprint_input_even_when_sent(
    mode: str, client: TestClient, db: Path
) -> None:
    """Quick and Detailed fingerprint bodies have always ignored keys they do
    not read; classification is one of them and moves nothing."""

    created = _create(client, db, mode, asset_type="office")
    plain = client.post("/deals/fingerprint", json=_fingerprint_request(created)).json()
    with_classification = client.post(
        "/deals/fingerprint",
        json={**_fingerprint_request(created), "asset_type": "retail", "asset_subtype": "Outlet"},
    ).json()
    assert with_classification == plain


def test_a_lease_level_fingerprint_request_refuses_classification_as_unknown(
    client: TestClient, db: Path
) -> None:
    """The Lease-Level parser owns every key a body carries. ``/deals`` declares
    the classification keys; ``/deals/fingerprint`` does not, because they are
    not a fingerprint input -- so it reports them rather than ignoring them."""

    created = _create(client, db, "lease_level", asset_type="retail")
    response = client.post(
        "/deals/fingerprint", json={**_fingerprint_request(created), "asset_type": "retail"}
    )
    assert response.status_code == 422
    assert "asset_type" in response.text


@pytest.mark.parametrize("mode", ["quick", "detailed"])
def test_saved_analysis_and_ai_survive_a_classification_change(mode: str, db: Path, client: TestClient) -> None:
    deal = f2.create_deal(mode, db, name="Analyzed")
    financial = f2.deal_fingerprint(deal)
    store.update_analysis_snapshot(
        deal.id, dataclasses.asdict(f2.analyze_deal(deal)), financial_input_fingerprint=financial, db_path=db
    )
    store.update_ai_snapshot(
        deal.id,
        dataclasses.asdict(AI),
        ai_context_fingerprint=fingerprint_ai(analysis_fingerprint=financial, deal_context=deal.deal_context),
        db_path=db,
    )
    before = client.get(f"/deals/{deal.id}").json()
    assert before["analysis_snapshot"] is not None and before["ai_snapshot"] is not None

    after = _reclassify(client, deal.id, asset_type="industrial", asset_subtype="Flex")
    assert after["analysis_snapshot"] == before["analysis_snapshot"]
    assert after["ai_snapshot"] == before["ai_snapshot"]


def test_scenario_and_investment_fingerprints_ignore_classification(client: TestClient, db: Path) -> None:
    """The P7 structured fingerprints -- a Scenario variant's and a visible
    Investment's Base -- are unchanged when only a Unit's classification is."""

    scenario_deal = f2.create_deal("detailed", db, name="With a Scenario")
    scenario = client.post(
        f"/deals/{scenario_deal.id}/scenarios",
        json={
            "name": "Downside",
            "overrides": [
                {"unit_id": scenario_deal.id, "target": "exit_cap_rate", "operation": "set", "value": 0.07}
            ],
        },
    ).json()
    variant_path = (
        f"/investments/{scenario['investment_id']}/variants/base/{scenario['scenario']['scenario_id']}/fingerprint"
    )
    variant_before = client.get(variant_path).json()

    first = f2.create_deal("quick", db, name="Unit A")
    second = store.create_deal("Unit B", fx.quick_inputs(), db_path=db)
    investment = client.post(
        "/investments",
        json={
            "name": "Two assets",
            "transaction_price": 2 * fx.quick_inputs().purchase_price,
            "units": [
                {"unit_id": first.id, "label": "A", "unit_kind": "property"},
                {"unit_id": second.id, "label": "B", "unit_kind": "property"},
            ],
        },
    )
    assert investment.status_code == 200, investment.text
    investment_id = investment.json()["id"]
    investment_path = f"/investments/{investment_id}/investment-variants/base/base/fingerprint"
    investment_before = client.get(investment_path).json()

    _reclassify(client, scenario_deal.id, asset_type="office", asset_subtype="Medical office")
    _reclassify(client, first.id, asset_type="multifamily")
    _reclassify(client, second.id, asset_type="retail", asset_subtype="Neighborhood center")

    assert client.get(variant_path).json() == variant_before
    assert client.get(investment_path).json() == investment_before
    # An Investment states no classification of its own: none is manufactured
    # from its Units, which may differ.
    details = client.get(f"/investments/{investment_id}/details").json()
    assert "asset_type" not in details and "asset_subtype" not in details
    assert {client.get(f"/deals/{unit['unit_id']}").json()["asset_type"] for unit in details["units"]} == {
        "multifamily",
        "retail",
    }


# =============================================================================
# The contract itself
# =============================================================================


def test_the_vocabulary_is_exactly_the_ten_ratified_types() -> None:
    assert [(member.value, ASSET_TYPE_LABELS[member]) for member in AssetType] == [
        ("multifamily", "Multifamily"),
        ("office", "Office"),
        ("industrial", "Industrial"),
        ("retail", "Retail"),
        ("hospitality", "Hospitality"),
        ("self_storage", "Self-Storage"),
        ("manufactured_housing", "Manufactured Housing"),
        ("mixed_use", "Mixed-Use"),
        ("land_development", "Land/Development"),
        ("other", "Other"),
    ]


def _quick_deal(asset_type: AssetType | None = None, asset_subtype: str | None = None) -> Deal:
    moment = datetime(2026, 1, 1)
    return Deal(
        id="x",
        name="x",
        operating_mode=OperatingMode.QUICK,
        inputs=fx.quick_inputs(),
        terms=None,
        detailed_operating_inputs=None,
        asset_type=asset_type,
        asset_subtype=asset_subtype,
        deal_context=None,
        analysis_snapshot=None,
        ai_snapshot=None,
        created_at=moment,
        updated_at=moment,
    )


def test_a_deal_refuses_an_inconsistent_classification_pair() -> None:
    assert _quick_deal().classification is None
    assert _quick_deal(AssetType.OTHER, "Marina").classification == AssetClassification(
        asset_type=AssetType.OTHER, asset_subtype="Marina"
    )
    with pytest.raises(ValueError, match="must not carry an 'asset_subtype'"):
        _quick_deal(None, "Orphan subtype")
    with pytest.raises(AssetClassificationError, match="subtype is required"):
        _quick_deal(AssetType.OTHER)
    with pytest.raises(AssetClassificationError):
        _quick_deal(AssetType.OFFICE, "  untrimmed")
