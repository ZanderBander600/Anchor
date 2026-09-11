"""D5.4 -- Lease-Level deals over HTTP, and the save/reload/re-analyze oracle.

The acceptance test for the whole gate is ``test_a_saved_deal_reanalyzes_
identically``: analyze a deal, save it, reload it, rebuild the analyze request
**from the reloaded inputs alone**, analyze again, and require the two result
envelopes to be byte-identical after canonical serialization.

That single assertion subsumes a long list of things that could go wrong -- a
dropped field, a coerced float, a date snapped, an enum defaulted, a suite lost,
an override flattened -- without needing a separate test to imagine each one. If
persisted inputs are genuinely the source of truth, it passes; if anything at
all is lossy, it fails.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from anchor.api import app
from anchor.deals import store as deals_store

# =============================================================================
# A wire-shaped deal covering the mechanics persistence must carry
# =============================================================================

TERMS: dict[str, Any] = {
    "purchase_price": 50_000_000.0,
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

OPERATING: dict[str, Any] = {
    "other_income": 50_000.0,
    "other_income_growth": 0.03,
    "credit_loss_pct": 0.01,
    "property_taxes": 600_000.0,
    "insurance": 90_000.0,
    "utilities": 140_000.0,
    "repairs_maintenance": 110_000.0,
    "other_operating_expenses": 60_000.0,
    "management_fee_pct": 0.03,
    "expense_growth": 0.03,
    "recoverable_expense_ratio": 0.85,
}


def market(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "market_rent_psf": 34.0,
        "market_rent_growth": 0.03,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.03,
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 1.0,
        "new_term_months": 60,
        "new_downtime_months": 6.0,
        "new_free_rent_months": 3.0,
        "renewal_ti_psf": 15.0,
        "new_ti_psf": 45.0,
        "leasing_commission_method": "pct_of_total_contractual_base_rent",
        "renewal_lc_pct": 0.03,
        "new_lc_pct": 0.06,
        "renewal_probability": 0.7,
        "renewal_lease_type": "nnn",
        "renewal_recovery_basis": None,
        "renewal_expense_stop_psf": None,
        "new_lease_type": "nnn",
        "new_recovery_basis": None,
        "new_expense_stop_psf": None,
    }
    base.update(overrides)
    return base


#: Occupied + lease-up + held vacant, with an override, a modified-gross lease
#: carrying an expense stop, and a rollover inside the hold window that produces
#: TI and LC. Deliberately not a one-suite demo.
INPUTS: dict[str, Any] = {
    "property_inputs": {
        "analysis_start_date": "2027-01-01",
        "rentable_area_sf": 120_000.0,
    },
    "operating_inputs": OPERATING,
    "market_leasing": market(),
    "suites": [
        {"suite_id": "101", "suite_area_sf": 60_000.0, "suite_label": "Ground"},
        {
            "suite_id": "201",
            "suite_area_sf": 35_000.0,
            "market_rent_psf": 36.5,
            "market_leasing_override": market(
                market_rent_psf=41.5,
                renewal_rent_psf=39.25,
                renewal_probability=0.55,
                renewal_lease_type="modified_gross",
                renewal_recovery_basis="expense_stop_psf",
                renewal_expense_stop_psf=8.75,
                new_lease_type="gross",
            ),
            "initial_vacancy": {
                "strategy": "market_lease_up",
                "initial_lease_up_months": 6.0,
            },
        },
        {
            "suite_id": "301",
            "suite_area_sf": 25_000.0,
            "initial_vacancy": {"strategy": "hold_vacant"},
        },
    ],
    "leases": [
        {
            "lease_id": "L-101",
            "suite_id": "101",
            "leased_area_sf": 60_000.0,
            "rent_commencement_date": "2024-03-01",
            "lease_expiration_date": "2028-12-31",
            "base_rent_psf": 32.5,
            "escalation_pct": 0.03,
            "escalation_basis": "lease_anniversary",
            "lease_type": "modified_gross",
            "tenant_name": "Anchor Tenant",
            "lease_start_date": "2024-02-01",
            "origin": "in_place",
            "recovery_basis": "expense_stop_psf",
            "expense_stop_psf": 7.25,
        }
    ],
}


def analyze_body() -> dict[str, Any]:
    # Deep-copied: these bodies are nested, and a test that pokes a suite must
    # not leave that suite poked for every test after it.
    return deepcopy({"operating_mode": "lease_level", "terms": TERMS, **INPUTS})


def create_body(name: str = "Rolling Rent Roll") -> dict[str, Any]:
    return deepcopy(
        {"operating_mode": "lease_level", "name": name, "terms": TERMS, **INPUTS}
    )


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "d5-4-api.db"))
    return TestClient(app)


def canonical(value: Any) -> Any:
    return json.loads(json.dumps(jsonable_encoder(value), sort_keys=True))


# =============================================================================
# 1. The acceptance oracle
# =============================================================================


def test_a_saved_deal_reanalyzes_identically(client: TestClient) -> None:
    """analyze -> save -> reload -> rebuild -> analyze, byte for byte.

    The request for the second analysis is rebuilt from the *reloaded* deal and
    nothing else, so anything persistence lost or altered shows up as a
    different envelope rather than as a passing test.
    """

    first = client.post("/analyze", json=analyze_body())
    assert first.status_code == 200, first.text

    created = client.post("/deals", json=create_body())
    assert created.status_code == 200, created.text
    deal_id = created.json()["id"]

    reloaded = client.get(f"/deals/{deal_id}")
    assert reloaded.status_code == 200
    stored = reloaded.json()

    rebuilt = {
        "operating_mode": "lease_level",
        "terms": stored["terms"],
        "property_inputs": stored["property_inputs"],
        "operating_inputs": stored["operating_inputs"],
        "market_leasing": stored["market_leasing"],
        "suites": stored["suites"],
        "leases": stored["leases"],
    }
    second = client.post("/analyze", json=rebuilt)
    assert second.status_code == 200, second.text

    assert second.json() == first.json(), (
        "a deal re-analyzed from its persisted inputs produced different "
        "economics -- persistence is lossy"
    )


def test_the_rebuilt_request_needs_no_field_the_response_did_not_carry(
    client: TestClient,
) -> None:
    """The reloaded deal is *sufficient*: nothing had to be remembered.

    Proven by rebuilding from the response alone above; asserted here as the
    property that makes it meaningful -- every input object round-tripped.
    """

    created = client.post("/deals", json=create_body())
    stored = client.get(f"/deals/{created.json()['id']}").json()

    for part in ("terms", "property_inputs", "operating_inputs", "market_leasing"):
        assert stored[part] is not None, part
    assert len(stored["suites"]) == 3
    assert len(stored["leases"]) == 1
    assert stored["suites"][1]["market_leasing_override"] is not None
    assert stored["suites"][1]["initial_vacancy"]["strategy"] == "market_lease_up"
    assert stored["suites"][2]["initial_vacancy"]["strategy"] == "hold_vacant"


def test_editing_an_input_changes_the_fingerprint_and_the_results(
    client: TestClient,
) -> None:
    """Stale-result safety, end to end.

    Because Lease-Level results are recomputed rather than cached, an economic
    edit must move both the fingerprint and the numbers. If either stood still,
    an analyst could be shown an answer to the deal they used to have.
    """

    before_fp = client.post("/deals/fingerprint", json=analyze_body()).json()
    before_results = client.post("/analyze", json=analyze_body()).json()

    edited = analyze_body()
    edited["market_leasing"] = market(renewal_probability=0.2)

    after_fp = client.post("/deals/fingerprint", json=edited).json()
    after_results = client.post("/analyze", json=edited).json()

    assert after_fp["financial_input_fingerprint"] != before_fp["financial_input_fingerprint"]
    assert after_results["results"] != before_results["results"]


# =============================================================================
# 2. The deal endpoints
# =============================================================================


def test_create_returns_an_honest_lease_level_deal(client: TestClient) -> None:
    created = client.post("/deals", json=create_body())

    assert created.status_code == 200, created.text
    deal = created.json()
    assert deal["operating_mode"] == "lease_level"
    assert deal["inputs"] is None
    assert deal["detailed_operating_inputs"] is None
    assert deal["analysis_snapshot"] is None
    assert deal["name"] == "Rolling Rent Roll"


def test_list_labels_the_mode_correctly(client: TestClient) -> None:
    client.post("/deals", json=create_body())
    listed = client.get("/deals").json()

    assert [deal["operating_mode"] for deal in listed] == ["lease_level"]


def test_update_replaces_the_rent_roll(client: TestClient) -> None:
    deal_id = client.post("/deals", json=create_body()).json()["id"]

    body = create_body(name="Renamed")
    body["suites"] = [{"suite_id": "101", "suite_area_sf": 120_000.0}]
    body["leases"] = []
    updated = client.put(f"/deals/{deal_id}", json=body)

    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed"
    assert [suite["suite_id"] for suite in updated.json()["suites"]] == ["101"]
    assert updated.json()["leases"] == []


def test_delete_removes_the_deal(client: TestClient) -> None:
    deal_id = client.post("/deals", json=create_body()).json()["id"]

    assert client.delete(f"/deals/{deal_id}").status_code == 204
    assert client.get(f"/deals/{deal_id}").status_code == 404


def test_duplicate_keeps_the_mode(client: TestClient) -> None:
    deal_id = client.post("/deals", json=create_body()).json()["id"]

    copy = client.post(f"/deals/{deal_id}/duplicate", json={})

    assert copy.status_code == 200, copy.text
    assert copy.json()["operating_mode"] == "lease_level"
    assert copy.json()["id"] != deal_id
    assert copy.json()["suites"] == client.get(f"/deals/{deal_id}").json()["suites"]


def test_fingerprint_needs_no_persisted_deal(client: TestClient) -> None:
    """A provenance token is a function of the inputs, not of a stored row."""

    response = client.post("/deals/fingerprint", json=analyze_body())

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["financial_input_fingerprint"]) == 64
    assert len(body["ai_context_fingerprint"]) == 64
    assert client.get("/deals").json() == []


def test_the_fingerprint_endpoint_matches_the_stored_deal(client: TestClient) -> None:
    endpoint = client.post("/deals/fingerprint", json=analyze_body()).json()
    deal_id = client.post("/deals", json=create_body()).json()["id"]

    from anchor.deals.fingerprint import fingerprint_lease_level_inputs

    deal = deals_store.get_deal(deal_id)
    assert (
        fingerprint_lease_level_inputs(
            deal.terms, deal.property_inputs, deal.suites, deal.leases,
            market_leasing=deal.market_leasing, operating_inputs=deal.operating_inputs,
        )
        == endpoint["financial_input_fingerprint"]
    )


def test_reordering_the_rent_roll_does_not_change_the_fingerprint(
    client: TestClient,
) -> None:
    natural = client.post("/deals/fingerprint", json=analyze_body()).json()

    reordered = analyze_body()
    reordered["suites"] = list(reversed(reordered["suites"]))
    shuffled = client.post("/deals/fingerprint", json=reordered).json()

    assert shuffled == natural


# =============================================================================
# 3. Refusals and unknown-field safety survive the wiring
# =============================================================================


def test_an_unknown_field_still_reaches_the_parser_on_create(
    client: TestClient,
) -> None:
    """The adapter must not narrow the body before parsing.

    ``/deals`` carries ``name`` and ``deal_context`` beside the inputs, and those
    are declared as owned by a literal tuple in ``api.py``. Everything else is
    still checked, so a typo is reported rather than dropped.
    """

    body = create_body()
    body["suites"][0]["suite_are_sf"] = 999.0

    response = client.post("/deals", json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["code"] == "UNKNOWN_FIELD"
    assert detail[0]["path"] == "suites[0].suite_are_sf"
    assert client.get("/deals").json() == [], "a rejected create must persist nothing"


def test_a_domain_invalid_deal_is_still_saveable_but_refused_by_analyze(
    client: TestClient,
) -> None:
    """Persistence stores *approved inputs*; it is not a second validator.

    A mid-month analysis start parses and stores, and is refused by the engine
    on analysis with its own code -- the same phase separation D5.2 established,
    now visible across a save.
    """

    body = create_body()
    body["property_inputs"]["analysis_start_date"] = "2027-01-15"

    created = client.post("/deals", json=body)
    assert created.status_code == 200, created.text

    analysis = client.post("/analyze", json={**analyze_body(), "property_inputs": body["property_inputs"]})
    assert analysis.status_code == 422
    codes = {issue["code"] for issue in analysis.json()["detail"]}
    assert "ANALYSIS_START_NOT_MONTH_ALIGNED" in codes


def test_creating_with_an_analysis_snapshot_field_is_refused(client: TestClient) -> None:
    """There is no way to smuggle a cached financial result into storage.

    ``/deals`` has never accepted a snapshot for any mode; for Lease-Level the
    key is not even a known field, so it is reported rather than ignored.
    """

    body = create_body()
    body["analysis_snapshot"] = {"levered_irr": 0.99}

    response = client.post("/deals", json=body)

    assert response.status_code == 422
    assert response.json()["detail"][0]["code"] == "UNKNOWN_FIELD"


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("/sensitivity/presets", {}),
        ("/break-even", {"target_levered_irr": 0.1, "target_headline_dscr": 1.2,
                         "target_equity_multiple": 1.5}),
    ],
    ids=["presets", "break-even"],
)
def test_the_remaining_refusals_are_untouched(
    client: TestClient, path: str, extra: dict[str, Any]
) -> None:
    """``/ai/analysis`` left this list at D5.8, the gate that wired it; the two
    that remain are refused for the whole of D5."""

    response = client.post(path, json={**analyze_body(), **extra})

    assert response.status_code == 422
    assert "not supported by" in str(response.json()["detail"])
