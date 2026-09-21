"""Phase 7 Gate P7.8B -- the Capital Structure routes.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 12, 14.1
and 15.1, and ``docs/architecture/P7_8_PRODUCT_INTEGRATION.md``.

The claims under test:

- **Opt-in through the door the analyst is already at.** A Deal's GET never
  materializes an Investment; its first non-empty PUT does, and clearing it
  releases the Deal again. A Unit of a visible Investment is a 409 that says
  where its structure lives.
- **The authoring surface is the executable subset.** Valuation-based funding,
  a later funding or fee month, debt PIK and a split current-pay rate are
  refused at the door, with P7.8A's own stable execution codes -- never stored
  as an analysis nobody can run.
- **Kinds are explicit on the wire.** Every typed variant carries a ``kind``, so
  a reader never infers a funding rule from which fields happen to be present.
- **One authority per refusal.** A structural problem is a structural 422; an
  invalid contract carries the P7.7 issues; an unexecutable one carries the
  P7.8A execution issues; a cross-structure identity clash carries its own.
- **A Strategy that states no structure answers exactly as it always did**: no
  ``root_overlays`` key at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from _p7_8_fixtures import round_deal  # type: ignore[import-not-found]
from anchor import api as api_module

UNRESOLVED = "unresolved"
CEC = "common_equity_contribution"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


@pytest.fixture
def client(db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    return TestClient(api_module.app)


def wire_mezz(unit_id: str, **overrides: Any) -> dict[str, Any]:
    stated: dict[str, Any] = {
        "position_id": "mezz-a",
        "name": "Mezzanine",
        "position_class": "mezzanine_debt",
        "priority": 2,
        "scope": {"kind": "unit", "unit_id": unit_id},
        "funding": [
            {
                "event_id": "mezz-f",
                "model_month": 0,
                "sequence": 1,
                "amount_rule": {"kind": "fixed_amount", "amount": 1_500_000.0},
            }
        ],
        "terms": {
            "kind": "debt",
            "interest_rate": 0.12,
            "amortization": 25,
            "io_period": 1,
            "maturity_month": 48,
            "fees": [
                {
                    "fee_id": "mezz-fee",
                    "description": "Origination fee",
                    "amount": 15_000.0,
                    "model_month": 0,
                    "sequence": 2,
                }
            ],
            "current_pay_rate": 0.12,
            "pik_rate": 0.0,
        },
        "shortfall_resolution": CEC,
    }
    stated.update(overrides)
    return stated


def wire_marker(unit_id: str | None) -> dict[str, Any]:
    return {
        "position_id": "common-a",
        "name": "Common Equity",
        "position_class": "common_equity",
        "priority": 9,
        "scope": {"kind": "unit", "unit_id": unit_id} if unit_id else {"kind": "investment", "unit_id": None},
        "funding": [],
        "terms": None,
        "shortfall_resolution": None,
    }


def body(*positions: dict[str, Any]) -> dict[str, Any]:
    return {"positions": list(positions)}


# =============================================================================
# The Deal door: opt-in, and never before
# =============================================================================


def test_reading_a_standalone_deals_structure_creates_nothing(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")

    response = client.get(f"/deals/{deal.id}/capital-structure")

    assert response.status_code == 200
    assert response.json() == {
        "deal_id": deal.id,
        "investment_id": None,
        "capital_structure": {"positions": []},
    }
    assert client.get("/investments").json() == []


def test_the_first_non_empty_save_materializes_the_hidden_investment(
    client: TestClient, db: Path
) -> None:
    deal = round_deal(db, name="Deal")

    saved = client.put(
        f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id), wire_marker(deal.id))
    )

    assert saved.status_code == 200
    investment_id = saved.json()["investment_id"]
    assert investment_id is not None
    # The wrapper is storage, never chrome: no visible Investment appears.
    assert client.get("/investments").json() == []
    reread = client.get(f"/deals/{deal.id}/capital-structure").json()
    assert reread == saved.json()
    assert [position["position_id"] for position in reread["capital_structure"]["positions"]] == [
        "mezz-a",
        "common-a",
    ]


def test_every_typed_variant_carries_its_kind_on_the_wire(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")
    client.put(f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id)))

    (position,) = client.get(f"/deals/{deal.id}/capital-structure").json()["capital_structure"][
        "positions"
    ]

    assert position["funding"][0]["amount_rule"]["kind"] == "fixed_amount"
    assert position["terms"]["kind"] == "debt"
    assert position["scope"] == {"kind": "unit", "unit_id": deal.id}


def test_a_percentage_funding_round_trips_as_a_percentage(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")
    priced = wire_mezz(
        deal.id,
        funding=[
            {
                "event_id": "mezz-f",
                "model_month": 0,
                "sequence": 1,
                "amount_rule": {"kind": "pct_of_price", "pct": 0.15},
            }
        ],
    )

    client.put(f"/deals/{deal.id}/capital-structure", json=body(priced))

    (position,) = client.get(f"/deals/{deal.id}/capital-structure").json()["capital_structure"][
        "positions"
    ]
    assert position["funding"][0]["amount_rule"] == {"kind": "pct_of_price", "pct": 0.15}


def test_clearing_the_structure_releases_the_deal(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")
    client.put(f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id)))

    cleared = client.put(f"/deals/{deal.id}/capital-structure", json=body())

    assert cleared.status_code == 200
    assert cleared.json()["investment_id"] is None
    assert client.get(f"/deals/{deal.id}/capital-structure").json()["investment_id"] is None


def test_a_unit_of_a_visible_investment_is_told_where_its_structure_lives(
    client: TestClient, db: Path
) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)

    refused = client.get(f"/deals/{first.id}/capital-structure")

    assert refused.status_code == 409
    assert "visible Investment" in refused.json()["detail"]
    assert client.get(f"/investments/{investment.id}/capital-structure").status_code == 200


def test_an_unknown_deal_is_a_404(client: TestClient) -> None:
    assert client.get("/deals/nobody/capital-structure").status_code == 404
    assert client.put("/deals/nobody/capital-structure", json=body()).status_code == 404


# =============================================================================
# The Investment door
# =============================================================================


def test_the_investment_routes_read_and_replace_the_base_structure(
    client: TestClient, db: Path
) -> None:
    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    investment = create_investment(db, first, second)

    empty = client.get(f"/investments/{investment.id}/capital-structure")
    saved = client.put(
        f"/investments/{investment.id}/capital-structure",
        json=body(wire_mezz(first.id), wire_marker(None)),
    )

    assert empty.json()["capital_structure"] == {"positions": []}
    assert saved.status_code == 200
    assert [p["position_id"] for p in saved.json()["capital_structure"]["positions"]] == [
        "mezz-a",
        "common-a",
    ]
    assert client.put(
        f"/investments/{investment.id}/capital-structure", json=body()
    ).json()["capital_structure"] == {"positions": []}


# =============================================================================
# The authoring surface is the executable subset
# =============================================================================


def test_a_valuation_based_funding_is_now_authorable_and_still_executes_no_amount(
    client: TestClient, db: Path
) -> None:
    """P7.10 Stage 2 activated the rule P7.7 always represented, so the
    authoring door accepts it.

    What has *not* changed is the money: naming a timepoint this Investment does
    not define stores the rule and resolves no amount at all. The analysis
    refuses with the Stage 1 funding reason rather than funding zero, the
    purchase price, or a percentage of either."""

    deal = round_deal(db, name="Deal")
    rule = {
        "funding": [
            {
                "event_id": "mezz-f",
                "model_month": 0,
                "sequence": 1,
                "amount_rule": {"kind": "pct_of_value", "timepoint_id": "stabilized", "pct": 0.2},
            }
        ]
    }

    saved = client.put(f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id, **rule)))
    assert saved.status_code == 200
    stored = next(
        p for p in saved.json()["capital_structure"]["positions"] if p["position_id"] == "mezz-a"
    )
    assert stored["funding"][0]["amount_rule"] == {
        "kind": "pct_of_value",
        "timepoint_id": "stabilized",
        "pct": 0.2,
    }

    investment_id = client.get(f"/deals/{deal.id}/capital-structure").json()["investment_id"]
    states = client.post(f"/investments/{investment_id}/valuation-views/base/base").json()[
        "funding_states"
    ]
    assert [s["status"] for s in states] == ["unavailable"]
    assert states[0]["amount"] is None
    assert states[0]["unavailable"]["reason_code"] == "funding_requirement_unresolved"


@pytest.mark.parametrize(
    ("label", "position", "code"),
    [
        # Re-pinned at P7.10 Stage 2: "valuation-based funding" is no longer an
        # unexecutable convention. This gate's own refusal said PctOfValue
        # "arrives with valuation timepoints", and they have arrived, so the rule
        # is authorable and the refusal is retired rather than relaxed. That a
        # rule naming an undefined or unresolvable timepoint still yields no
        # amount is proved by the P7.10 Stage 2 suites; the case below covers it
        # from this gate's side.
        (
            "a later funding month",
            {
                "funding": [
                    {
                        "event_id": "mezz-f",
                        "model_month": 12,
                        "sequence": 1,
                        "amount_rule": {"kind": "fixed_amount", "amount": 100.0},
                    }
                ]
            },
            "unsupported_funding_timing",
        ),
    ],
)
def test_a_funding_convention_p7_8_does_not_execute_is_refused_at_the_door(
    client: TestClient, db: Path, label: str, position: dict[str, Any], code: str
) -> None:
    deal = round_deal(db, name="Deal")

    refused = client.put(
        f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id, **position))
    )

    assert refused.status_code == 422, label
    assert [issue["code"] for issue in refused.json()["detail"]] == [code]
    assert client.get(f"/deals/{deal.id}/capital-structure").json()["investment_id"] is None


@pytest.mark.parametrize(
    ("label", "terms", "code"),
    [
        ("debt PIK", {"pik_rate": 0.02}, "unsupported_debt_pik"),
        ("a split coupon", {"current_pay_rate": 0.08}, "unsupported_debt_current_pay"),
        ("a later fee", {"fees": [
            {"fee_id": "f", "description": "Exit fee", "amount": 1.0, "model_month": 48, "sequence": 1}
        ]}, "unsupported_fee_timing"),
    ],
)
def test_a_debt_convention_p7_8_does_not_execute_is_refused_at_the_door(
    client: TestClient, db: Path, label: str, terms: dict[str, Any], code: str
) -> None:
    deal = round_deal(db, name="Deal")
    position = wire_mezz(deal.id)
    position["terms"] = {**position["terms"], **terms}

    refused = client.put(f"/deals/{deal.id}/capital-structure", json=body(position))

    assert refused.status_code == 422, label
    assert [issue["code"] for issue in refused.json()["detail"]] == [code]


def test_an_unknown_or_missing_field_is_a_structural_refusal(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")
    position = wire_mezz(deal.id)
    position["rate"] = 0.12

    unknown = client.put(f"/deals/{deal.id}/capital-structure", json=body(position))
    missing = client.put(
        f"/deals/{deal.id}/capital-structure",
        json=body({key: value for key, value in wire_mezz(deal.id).items() if key != "priority"}),
    )
    stray = client.put(f"/deals/{deal.id}/capital-structure", json={"positions": [], "note": "x"})

    assert unknown.status_code == 422 and "rate" in unknown.json()["detail"]
    assert missing.status_code == 422 and "priority" in missing.json()["detail"]
    assert stray.status_code == 422 and "note" in stray.json()["detail"]


# =============================================================================
# One authority per refusal
# =============================================================================


def test_an_invalid_contract_carries_the_p7_7_issues(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")

    refused = client.put(
        f"/deals/{deal.id}/capital-structure",
        json=body(wire_mezz(deal.id), wire_mezz(deal.id, priority=3)),
    )

    assert refused.status_code == 422
    issue = refused.json()["detail"][0]
    assert set(issue) == {"code", "message", "position_id", "field"}
    assert issue["code"] == "duplicate_position_id" and issue["position_id"] == "mezz-a"


def test_an_unexecutable_structure_is_refused_when_it_is_analysed(
    client: TestClient, db: Path
) -> None:
    """Over-funding the closing is not a contract error -- the structure is well
    formed -- so it is refused by the analysis, with the executor's own code."""

    deal = round_deal(db, name="Deal")
    over = wire_mezz(
        deal.id,
        funding=[
            {
                "event_id": "mezz-f",
                "model_month": 0,
                "sequence": 1,
                "amount_rule": {"kind": "fixed_amount", "amount": 9_000_000.0},
            }
        ],
    )
    saved = client.put(f"/deals/{deal.id}/capital-structure", json=body(over))
    investment_id = saved.json()["investment_id"]

    refused = client.post(
        f"/investments/{investment_id}/structured-variants/base/base/analysis"
    )

    assert saved.status_code == 200
    assert refused.status_code == 422
    assert [issue["code"] for issue in refused.json()["detail"]] == ["overfunded_closing"]


def test_a_cross_structure_identity_clash_is_its_own_refusal(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")
    saved = client.put(f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id)))
    investment_id = saved.json()["investment_id"]
    recut = wire_mezz(deal.id)
    recut["position_class"] = "preferred_equity"
    recut["terms"] = {
        "kind": "preferred_equity",
        "preferred_rate": 0.12,
        "current_pay_rate": 0.12,
        "accrual_permitted": False,
        "accrual_convention": None,
        "redemption_month": 60,
    }

    refused = client.post(
        f"/investments/{investment_id}/strategies",
        json={
            "name": "Recut",
            "description": None,
            "root_overlays": [{"domain": "capital_structure", "content": body(recut)}],
        },
    )

    assert refused.status_code == 422
    assert [issue["code"] for issue in refused.json()["detail"]] == ["position_class_conflict"]


# =============================================================================
# Strategies on the wire
# =============================================================================


def test_a_strategy_that_states_no_structure_answers_exactly_as_it_always_did(
    client: TestClient, db: Path
) -> None:
    """No ``root_overlays`` key at all: an empty one would change every existing
    Strategy response and make inheriting look like a stated choice."""

    deal = round_deal(db, name="Deal")

    created = client.post(
        f"/deals/{deal.id}/strategies", json={"name": "Base case", "description": None}
    )

    assert created.status_code == 200
    assert set(created.json()["strategy"]) == {"strategy_id", "name", "description", "overlays"}
    listed = client.get(f"/deals/{deal.id}/strategies").json()
    assert "root_overlays" not in listed["strategies"][0]["strategy"]


def test_a_strategys_own_structure_round_trips_with_its_kinds(
    client: TestClient, db: Path
) -> None:
    deal = round_deal(db, name="Deal")
    saved = client.put(f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id)))
    investment_id = saved.json()["investment_id"]

    created = client.post(
        f"/investments/{investment_id}/strategies",
        json={
            "name": "Stretch",
            "description": None,
            "root_overlays": [{"domain": "capital_structure", "content": body(wire_mezz(deal.id, priority=4))}],
        },
    )

    assert created.status_code == 200
    (overlay,) = created.json()["strategy"]["root_overlays"]
    assert overlay["domain"] == "capital_structure"
    assert overlay["content"]["positions"][0]["terms"]["kind"] == "debt"
    strategy_id = created.json()["strategy"]["strategy_id"]
    assert client.get(f"/investments/{investment_id}/strategies/{strategy_id}").json() == created.json()


def test_a_strategy_may_state_an_explicitly_empty_structure(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")
    saved = client.put(f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id)))
    investment_id = saved.json()["investment_id"]

    created = client.post(
        f"/investments/{investment_id}/strategies",
        json={
            "name": "No structured capital",
            "description": None,
            "root_overlays": [{"domain": "capital_structure", "content": {"positions": []}}],
        },
    )

    (overlay,) = created.json()["strategy"]["root_overlays"]
    assert overlay["content"] == {"positions": []}


def test_a_root_domain_stated_as_a_unit_overlay_is_refused(client: TestClient, db: Path) -> None:
    deal = round_deal(db, name="Deal")

    refused = client.post(
        f"/deals/{deal.id}/strategies",
        json={
            "name": "Wrong address",
            "description": None,
            "overlays": [
                {"unit_id": deal.id, "domain": "capital_structure", "content": {"positions": []}}
            ],
        },
    )

    assert refused.status_code == 422
    assert [issue["code"] for issue in refused.json()["detail"]] == ["root_domain_on_unit"]


# =============================================================================
# Structured variants, perspectives and the Position matrix
# =============================================================================


@pytest.fixture
def structured(client: TestClient, db: Path) -> tuple[str, str]:
    deal = round_deal(db, name="Deal")
    saved = client.put(
        f"/deals/{deal.id}/capital-structure", json=body(wire_mezz(deal.id), wire_marker(deal.id))
    )
    return saved.json()["investment_id"], deal.id


def test_the_fingerprint_route_reports_both_layers(
    client: TestClient, structured: tuple[str, str]
) -> None:
    investment_id, _ = structured

    payload = client.get(
        f"/investments/{investment_id}/structured-variants/base/base/fingerprint"
    ).json()

    assert payload["root_kind"] == "hidden_unit"
    assert payload["capital_structure_source"] == "base"
    assert payload["project_source_fingerprint"] != payload["structured_source_fingerprint"]


def test_the_analysis_route_reports_the_position_and_the_residual(
    client: TestClient, structured: tuple[str, str]
) -> None:
    investment_id, _ = structured

    response = client.post(f"/investments/{investment_id}/structured-variants/base/base/analysis")

    assert response.status_code == 200
    payload = response.json()
    (position,) = payload["result"]["positions"]
    assert position["position_id"] == "mezz-a" and position["status"] == "complete"
    assert position["funded_amount"] == 1_500_000.0
    assert position["attachment_ltv"] == 0.6
    assert payload["result"]["common_equity"]["position_id"] == "common-a"
    assert payload["project_cache_status"] in {"hit", "miss", "bypassed"}


def test_the_perspective_route_lists_addressable_positions_by_name(
    client: TestClient, structured: tuple[str, str]
) -> None:
    investment_id, _ = structured

    payload = client.get(f"/investments/{investment_id}/position-perspectives").json()

    assert [entry["position_id"] for entry in payload["positions"]] == ["mezz-a", "common-a"]
    assert payload["positions"][0]["name"] == "Mezzanine"
    assert payload["positions"][1]["is_common_equity_marker"] is True


def test_the_position_matrix_route_answers_for_a_known_position_only(
    client: TestClient, structured: tuple[str, str]
) -> None:
    investment_id, _ = structured

    matrix = client.post(f"/investments/{investment_id}/position-decision-matrix/mezz-a")
    unknown = client.post(f"/investments/{investment_id}/position-decision-matrix/nobody")

    assert matrix.status_code == 200
    payload = matrix.json()["matrix"]
    assert payload["perspective"] == "position" and payload["position_id"] == "mezz-a"
    assert [cell["applicability"] for cell in payload["cells"]] == ["present"]
    assert unknown.status_code == 404
