"""Underwriting V2 Gate 1 -- the enforced backward-compatibility guarantee.

``docs/underwriting_v2_financial_conventions.md`` states that the V2
financial conventions are *designed* so that, at the five new inputs'
neutral defaults, every formula reduces to the exact, unmodified V1
formula -- but that this was a design claim, not yet a proven property of
any implementation, until a permanent V1-neutral regression test exists.

This module is that test. It is the one required by that document's
"Backward-Compatibility Design Goal" section and by the Gate 1 acceptance
criteria: an original nine-input reference deal (the existing, frozen V1
golden case from ``docs/phase_2_deterministic_engine.md``, the same one
``tests/test_engine_golden_case.py`` pins -- reproduced locally here per
this suite's existing convention of each test module defining its own
golden-case constants rather than cross-importing them) and the same deal
explicitly supplying all five V2 inputs at their neutral value must
produce identical results, at every layer the deal actually passes
through -- the dataclass, the deterministic engine directly, and the full
HTTP ``/analyze`` round trip.

The engine itself is not modified at Gate 1 (docs/underwriting_v2_financial
_conventions.md's implementation sequence reaches engine changes only at
Phase 2+); this test is expected to keep passing unmodified through every
later engine gate, since the guarantee it enforces is that neutral-default
V2 inputs never change V1 output, not that V2 inputs are inert forever.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from anchor.api import app
from anchor.contracts import AcquisitionInputs
from anchor.engine import analyze_acquisition

GOLDEN_PAYLOAD: dict[str, Any] = {
    "purchase_price": 50_000_000,
    "current_noi": 2_500_000,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.055,
    "ltv": 0.65,
    "interest_rate": 0.0525,
    "amortization": 30,
}

EXPLICIT_NEUTRAL_V2_FIELDS: dict[str, Any] = {
    "acquisition_cost_pct": 0,
    "financing_fee_pct": 0,
    "disposition_cost_pct": 0,
    "annual_capex_reserve": 0,
    "io_period": 0,
}


def make_golden_inputs() -> AcquisitionInputs:
    """The same frozen V1 golden case ``tests/test_engine_golden_case.py``
    pins, constructed with only the original nine keyword arguments."""

    return AcquisitionInputs(
        purchase_price=50_000_000.0,
        current_noi=2_500_000.0,
        occupancy=0.95,
        noi_growth=0.03,
        hold_period=5,
        exit_cap_rate=0.055,
        ltv=0.65,
        interest_rate=0.0525,
        amortization=30,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_nine_kwarg_and_explicit_neutral_v2_construction_produce_an_equal_dataclass() -> None:
    implicit = make_golden_inputs()
    explicit = AcquisitionInputs(
        purchase_price=50_000_000.0,
        current_noi=2_500_000.0,
        occupancy=0.95,
        noi_growth=0.03,
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
    )

    assert implicit == explicit


def test_v1_neutral_regression_engine_results_are_identical() -> None:
    """The core guarantee, called directly against the unmodified engine
    entry point -- not merely approximately equal, but field-for-field
    identical, since the engine does not read the five new fields at all."""

    implicit_inputs = make_golden_inputs()
    explicit_inputs = AcquisitionInputs(
        purchase_price=implicit_inputs.purchase_price,
        current_noi=implicit_inputs.current_noi,
        occupancy=implicit_inputs.occupancy,
        noi_growth=implicit_inputs.noi_growth,
        hold_period=implicit_inputs.hold_period,
        exit_cap_rate=implicit_inputs.exit_cap_rate,
        ltv=implicit_inputs.ltv,
        interest_rate=implicit_inputs.interest_rate,
        amortization=implicit_inputs.amortization,
        acquisition_cost_pct=0.0,
        financing_fee_pct=0.0,
        disposition_cost_pct=0.0,
        annual_capex_reserve=0.0,
        io_period=0,
    )

    implicit_results = analyze_acquisition(implicit_inputs)
    explicit_results = analyze_acquisition(explicit_inputs)

    assert implicit_results == explicit_results


def test_v1_neutral_regression_matches_the_frozen_golden_case_values() -> None:
    """Ties the guarantee to the actual frozen V1 golden-case numbers
    (docs/phase_2_deterministic_engine.md), not just internal
    self-consistency between the two constructions above."""

    results = analyze_acquisition(make_golden_inputs())

    assert results.levered_irr == pytest.approx(0.07913030056780745, rel=0.0, abs=1e-9)
    assert results.unlevered_irr == pytest.approx(0.062414943980353854, rel=0.0, abs=1e-9)
    assert results.equity_multiple == pytest.approx(1.44288913123241, rel=0.0, abs=1e-9)
    assert results.headline_dscr == pytest.approx(1.1608499518189, rel=0.0, abs=1e-9)
    assert results.loan_amount == 32_500_000.0
    assert results.initial_equity == 17_500_000.0


def test_old_nine_field_analyze_payload_still_accepted(client: TestClient) -> None:
    response = client.post("/analyze", json=GOLDEN_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    expected = analyze_acquisition(make_golden_inputs())
    assert body["levered_irr"] == pytest.approx(expected.levered_irr)
    assert body["equity_multiple"] == pytest.approx(expected.equity_multiple)


def test_analyze_payload_with_explicit_neutral_v2_fields_matches_the_nine_field_payload(
    client: TestClient,
) -> None:
    """The full HTTP-round-trip form of the Gate 1 guarantee: an old
    nine-field payload and the same payload with the five V2 fields
    explicitly present at their neutral value must analyze identically."""

    nine_field_response = client.post("/analyze", json=GOLDEN_PAYLOAD)
    fourteen_field_response = client.post(
        "/analyze", json=GOLDEN_PAYLOAD | EXPLICIT_NEUTRAL_V2_FIELDS
    )

    assert nine_field_response.status_code == 200
    assert fourteen_field_response.status_code == 200
    assert nine_field_response.json() == fourteen_field_response.json()


def test_analyze_payload_missing_v2_fields_does_not_raise_missing_field_error(
    client: TestClient,
) -> None:
    """A 422 here would mean the five V2 fields were accidentally made
    required at the API boundary -- the one failure mode Gate 1's API
    compatibility requirement exists to prevent."""

    response = client.post("/analyze", json=GOLDEN_PAYLOAD)

    assert response.status_code == 200
