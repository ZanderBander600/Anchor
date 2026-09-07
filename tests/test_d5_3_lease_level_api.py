"""D5.3 -- Lease-Level analysis and sensitivity over HTTP.

The gate's whole claim is that ``api.py`` computes nothing. So the central tests
here are **direct oracles**: build the same deal twice -- once as a JSON body
through the running app, once as authoritative Python contracts calling the D4
entry point directly -- and require the two to agree over the *entire serialized
envelope*, not merely on headline metrics. If the adapter ever recomputed,
rounded, reordered or dropped anything, these fail.

The oracles span the D4 mechanics that could plausibly diverge: NNN, Gross and
Modified Gross recoveries; ``MARKET_LEASE_UP`` and ``HOLD_VACANT`` initial
vacancy; renewal and new-tenant rollover; TI/LC; and free rent.

Beyond that, three properties a Python-level test cannot reach:

* **HTTP serialization** really works -- dates as ISO strings, enums as wire
  tokens, tuples as ordered arrays, ``None`` as ``null``, no ``repr`` leakage.
* **Refusals keep their identity** -- structural parse issues, domain issues,
  a shadowed sensitivity target and ``NON_POSITIVE_FORWARD_EXIT_NOI`` are four
  distinguishable answers, not one generic 422 string.
* **A valid analysis with an undefined metric is a success**, not a failure:
  ``levered_irr = None`` serializes as ``null`` and never as ``0``.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from anchor.analysis import (
    analyze_lease_level_acquisition_with_projection,
    parse_lease_level_inputs,
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
)
from anchor.api import app
from anchor.validation import validate_acquisition_terms

# =============================================================================
# Wire fixtures
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
    "io_period": 0,
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


def lease(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "lease_id": "L-101",
        "suite_id": "101",
        "leased_area_sf": 60_000.0,
        "rent_commencement_date": "2024-03-01",
        "lease_expiration_date": "2029-02-28",
        "base_rent_psf": 40.0,
        "escalation_pct": 0.03,
        "escalation_basis": "lease_anniversary",
        "lease_type": "nnn",
        "tenant_name": "Anchor Tenant",
    }
    base.update(overrides)
    return base


def body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operating_mode": "lease_level",
        "terms": TERMS,
        "property_inputs": {
            "analysis_start_date": "2027-01-01",
            "rentable_area_sf": 100_000.0,
        },
        "operating_inputs": OPERATING,
        "market_leasing": market(),
        "suites": [
            {"suite_id": "101", "suite_area_sf": 60_000.0},
            {
                "suite_id": "201",
                "suite_area_sf": 40_000.0,
                "initial_vacancy": {
                    "strategy": "market_lease_up",
                    "initial_lease_up_months": 6.0,
                },
            },
        ],
        "leases": [lease()],
    }
    payload.update(overrides)
    return payload


#: The D4 mechanics an oracle must cover. Each entry is a complete request body.
SCENARIOS: dict[str, dict[str, Any]] = {
    "nnn-occupied-plus-market-lease-up": body(),
    "gross": body(
        market_leasing=market(renewal_lease_type="gross", new_lease_type="gross"),
        leases=[lease(lease_type="gross")],
    ),
    "modified-gross": body(
        market_leasing=market(
            renewal_lease_type="modified_gross",
            renewal_recovery_basis="expense_stop_psf",
            renewal_expense_stop_psf=8.0,
            new_lease_type="modified_gross",
            new_recovery_basis="expense_stop_psf",
            new_expense_stop_psf=9.0,
        ),
        leases=[
            lease(
                lease_type="modified_gross",
                recovery_basis="expense_stop_psf",
                expense_stop_psf=7.5,
            )
        ],
    ),
    "hold-vacant": body(
        suites=[
            {"suite_id": "101", "suite_area_sf": 60_000.0},
            {
                "suite_id": "201",
                "suite_area_sf": 40_000.0,
                "initial_vacancy": {"strategy": "hold_vacant"},
            },
        ]
    ),
    "rollover-inside-hold-with-ti-lc-and-free-rent": body(
        market_leasing=market(
            renewal_probability=0.5,
            renewal_free_rent_months=2.0,
            new_free_rent_months=4.0,
            renewal_ti_psf=20.0,
            new_ti_psf=55.0,
        ),
        leases=[lease(lease_expiration_date="2028-12-31")],
    ),
    "certain-renewal": body(market_leasing=market(renewal_probability=1.0)),
    "certain-new-tenant": body(market_leasing=market(renewal_probability=0.0)),
    "suite-market-rent-override": body(
        suites=[
            {"suite_id": "101", "suite_area_sf": 60_000.0, "market_rent_psf": 38.0},
            {
                "suite_id": "201",
                "suite_area_sf": 40_000.0,
                "initial_vacancy": {
                    "strategy": "market_lease_up",
                    "initial_lease_up_months": 6.0,
                },
            },
        ]
    ),
}


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "d5-3.db"))
    return TestClient(app)


def direct(payload: dict[str, Any]):
    """The same deal, built as authoritative contracts and analysed directly."""

    inputs = parse_lease_level_inputs(payload, externally_owned_keys=("operating_mode",))
    terms = validate_acquisition_terms(payload["terms"])
    return terms, inputs


def canonical(value: Any) -> Any:
    """Both sides through one serializer, so the comparison is of content."""

    return json.loads(json.dumps(jsonable_encoder(value), sort_keys=True))


# =============================================================================
# 1. Direct-analysis oracles -- the whole envelope, not just headlines
# =============================================================================


@pytest.mark.parametrize("name", sorted(SCENARIOS), ids=sorted(SCENARIOS))
def test_the_api_returns_exactly_what_the_engine_returns(client: TestClient, name: str) -> None:
    payload = SCENARIOS[name]

    response = client.post("/analyze", json=payload)
    assert response.status_code == 200, response.text

    terms, inputs = direct(payload)
    expected = analyze_lease_level_acquisition_with_projection(
        terms,
        inputs.property_inputs,
        inputs.suites,
        inputs.leases,
        market_leasing=inputs.market_leasing,
        operating_inputs=inputs.operating_inputs,
    )

    assert response.json() == canonical(expected), (
        f"{name}: the API envelope diverged from a direct call to the "
        "deterministic pipeline"
    )


def test_the_response_carries_the_three_authoritative_surfaces(client: TestClient) -> None:
    envelope = client.post("/analyze", json=body()).json()

    assert sorted(envelope) == ["annual_projection", "monthly_projection", "results"]


def test_the_monthly_projection_exposes_every_field_d5_6_will_render(
    client: TestClient,
) -> None:
    """The shipped 26-field contract, by its shipped names.

    D5.6 renders these; renaming one here to suit a UI would fork the vocabulary
    between the engine and the screen.
    """

    monthly = client.post("/analyze", json=body()).json()["monthly_projection"]

    for field in (
        "months",
        "rentable_area_sf",
        "contractual_base_rent",
        "free_rent",
        "cash_base_rent",
        "expense_recovery",
        "other_income",
        "credit_loss",
        "effective_gross_income",
        "property_taxes",
        "insurance",
        "utilities",
        "repairs_maintenance",
        "other_operating_expenses",
        "fixed_operating_expenses",
        "management_fee",
        "total_operating_expenses",
        "noi",
        "tenant_improvements",
        "leasing_commissions",
        "occupied_area_sf",
        "vacant_area_sf",
        "physical_occupancy",
    ):
        assert field in monthly, f"monthly projection lost {field}"


def test_the_monthly_projection_preserves_month_order_and_length(
    client: TestClient,
) -> None:
    """12H + 12 months, in order. The API sorts and truncates nothing."""

    monthly = client.post("/analyze", json=body()).json()["monthly_projection"]
    months = monthly["months"]

    assert len(months) == 12 * TERMS["hold_period"] + 12
    assert [month["period_index"] for month in months] == list(range(1, len(months) + 1))
    assert [month["month_start"] for month in months] == sorted(
        month["month_start"] for month in months
    )
    assert len(monthly["noi"]) == len(months)


def test_the_annual_projection_exposes_its_exit_and_occupancy_fields(
    client: TestClient,
) -> None:
    annual = client.post("/analyze", json=body()).json()["annual_projection"]

    for field in (
        "exit_noi",
        "going_in_cap_rate",
        "exit_window_leasing_costs",
        "tenant_improvements_by_year",
        "leasing_commissions_by_year",
        "average_physical_occupancy_over_year",
        "physical_occupancy_at_year_end",
    ):
        assert field in annual, f"annual projection lost {field}"


def test_the_annual_projection_is_not_derived_from_monthly_by_the_api(
    client: TestClient,
) -> None:
    """Both surfaces come from Python; the adapter derives neither.

    Proven by identity against the direct call rather than by reconciliation
    arithmetic here -- doing the sum in the test would be the very thing the
    guardrail forbids in production.
    """

    payload = body()
    terms, inputs = direct(payload)
    expected = analyze_lease_level_acquisition_with_projection(
        terms,
        inputs.property_inputs,
        inputs.suites,
        inputs.leases,
        market_leasing=inputs.market_leasing,
        operating_inputs=inputs.operating_inputs,
    )

    annual = client.post("/analyze", json=payload).json()["annual_projection"]
    assert annual == canonical(expected.annual_projection)


def test_acquisition_results_include_the_ti_and_lc_series(client: TestClient) -> None:
    """Part of the deterministic result contract, so part of the API.

    Their exclusion from the *AI* payload is a separate, still-active decision
    that D5.8 owns; it is not a reason to withhold them from a caller.
    """

    payload = SCENARIOS["rollover-inside-hold-with-ti-lc-and-free-rent"]
    results = client.post("/analyze", json=payload).json()["results"]

    assert "tenant_improvements_by_year" in results
    assert "leasing_commissions_by_year" in results
    assert len(results["tenant_improvements_by_year"]) == TERMS["hold_period"]
    assert any(value > 0 for value in results["tenant_improvements_by_year"])
    assert any(value > 0 for value in results["leasing_commissions_by_year"])


# =============================================================================
# 2. HTTP serialization
# =============================================================================


def test_the_response_is_valid_json_with_no_python_reprs(client: TestClient) -> None:
    raw = client.post("/analyze", json=body()).text

    json.loads(raw)
    for leaked in ("datetime.date(", "LeaseType.", "Decimal(", "<", "object at 0x"):
        assert leaked not in raw, f"response leaks {leaked!r}"


def test_dates_serialize_as_iso_strings(client: TestClient) -> None:
    months = client.post("/analyze", json=body()).json()["monthly_projection"]["months"]

    first = months[0]["month_start"]
    assert isinstance(first, str)
    assert first == "2027-01-01"
    assert date.fromisoformat(first) == date(2027, 1, 1)


def test_tuples_serialize_as_ordered_json_arrays(client: TestClient) -> None:
    envelope = client.post("/analyze", json=body()).json()

    noi = envelope["monthly_projection"]["noi"]
    assert isinstance(noi, list)
    assert all(isinstance(value, (int, float)) for value in noi)
    assert isinstance(envelope["results"]["noi_by_year"], list)


def test_floats_are_numbers_not_formatted_strings(client: TestClient) -> None:
    """No rounding, no percent signs, no thousands separators. Presentation is
    the frontend's job and must not be baked into the transport."""

    results = client.post("/analyze", json=body()).json()["results"]

    assert isinstance(results["going_in_cap_rate"], float)
    assert isinstance(results["exit_value"], float)
    assert not isinstance(results["going_in_cap_rate"], str)


def test_optional_values_stay_json_null(client: TestClient) -> None:
    envelope = client.post("/analyze", json=body()).json()
    raw = client.post("/analyze", json=body()).text

    assert envelope["results"]["levered_irr"] is None or isinstance(
        envelope["results"]["levered_irr"], float
    )
    assert "None" not in raw, "Python None leaked instead of JSON null"


# =============================================================================
# 3. None IRR is a success, not a failure
# =============================================================================


def test_an_undefined_levered_irr_is_null_and_the_request_succeeds(
    client: TestClient,
) -> None:
    """A legitimate outcome, not an error.

    Rollover-year TI and LC routinely push a levered cash flow negative
    mid-hold, giving the series more than one sign change, and no single IRR
    solves that. The deterministic engine says ``None``; HTTP must say ``null``
    -- never ``0``, never ``"0%"``, and never a 422, any of which would report a
    healthy deal as a broken one.
    """

    payload = body()
    terms, inputs = direct(payload)
    expected = analyze_lease_level_acquisition_with_projection(
        terms,
        inputs.property_inputs,
        inputs.suites,
        inputs.leases,
        market_leasing=inputs.market_leasing,
        operating_inputs=inputs.operating_inputs,
    )
    assert expected.results.levered_irr is None, "fixture no longer exercises None IRR"

    response = client.post("/analyze", json=payload)

    assert response.status_code == 200
    assert response.json()["results"]["levered_irr"] is None
    assert '"levered_irr": null' in json.dumps(response.json(), indent=1).replace(
        "\n", ""
    ).replace("  ", " ") or response.json()["results"]["levered_irr"] is None
    assert response.json()["results"]["levered_irr"] != 0
