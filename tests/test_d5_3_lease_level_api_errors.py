"""D5.3 -- sensitivity over HTTP, error transport, and the refusal ledger.

Three groups:

1. **Sensitivity oracles.** One-way and two-way, for all three modes, compared
   against direct calls to the shipped runners. Absolute candidate values,
   ``1 + N`` and ``1 + R*C`` complete re-underwrites, no caching, no shortcut.
2. **Error transport.** The eight categories D5.3 must keep distinguishable --
   an unparseable mode, an unsupported mode, a structural parse issue, a domain
   issue, an unknown target, a shadowed target, a non-positive forward exit NOI,
   and a valid result with an undefined metric. Collapsing any pair into the
   same 422 string would make a UI unable to tell an analyst what to fix.
3. **Mutation kills**, applied rather than asserted impossible.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from anchor.analysis import (
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
)
from anchor.api import app
from test_d5_3_lease_level_api import (  # type: ignore[import-not-found]
    OPERATING,
    TERMS,
    body,
    canonical,
    direct,
    lease,
    market,
)

QUICK_INPUTS: dict[str, Any] = {
    "purchase_price": 10_000_000,
    "current_noi": 600_000,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
}

DETAILED_OPERATING: dict[str, Any] = {
    "gross_potential_rent": 800_000,
    "other_income": 20_000,
    "vacancy_credit_loss_pct": 0.05,
    "property_taxes": 60_000,
    "insurance": 20_000,
    "utilities": 25_000,
    "repairs_maintenance": 20_000,
    "other_operating_expenses": 16_000,
    "management_fee_pct": 0.05,
    "revenue_growth": 0.03,
    "expense_growth": 0.03,
}

DETAILED_TERMS: dict[str, Any] = {**TERMS, "purchase_price": 10_000_000.0}


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "d5-3-err.db"))
    return TestClient(app)


def detail_of(response) -> Any:
    return response.json()["detail"]


# =============================================================================
# 1. Sensitivity oracles
# =============================================================================

_TWO_WAY = {
    "row_assumption": "exit_cap_rate",
    "row_values": [0.06, 0.065, 0.07],
    "column_assumption": "market_rent_psf",
    "column_values": [32.0, 34.0],
    "metric": "equity_multiple",
}


@pytest.mark.parametrize(
    "assumption",
    [
        "purchase_price",
        "exit_cap_rate",
        "ltv",
        "interest_rate",
        "market_rent_psf",
        "renewal_probability",
        "expense_growth",
        "recoverable_expense_ratio",
    ],
)
def test_one_way_matches_the_runner_for_every_supported_target(
    client: TestClient, assumption: str
) -> None:
    """All eight approved targets, each against a direct runner call.

    Includes the four additive Lease-Level targets, which is where an adapter
    could most plausibly mis-route a value into the wrong contract.
    """

    values = {
        "purchase_price": [45_000_000.0, 50_000_000.0],
        "exit_cap_rate": [0.06, 0.07],
        "ltv": [0.55, 0.65],
        "interest_rate": [0.045, 0.055],
        "market_rent_psf": [32.0, 36.0],
        "renewal_probability": [0.0, 0.5, 1.0],
        "expense_growth": [0.02, 0.04],
        "recoverable_expense_ratio": [0.75, 0.95],
    }[assumption]

    payload = body()
    request = {**payload, "assumption": assumption, "values": values, "metric": "equity_multiple"}
    response = client.post("/sensitivity/one-way", json=request)
    assert response.status_code == 200, response.text

    terms, inputs = direct(payload)
    expected = run_lease_level_one_way_sensitivity(
        terms,
        inputs.property_inputs,
        inputs.suites,
        inputs.leases,
        market_leasing=inputs.market_leasing,
        operating_inputs=inputs.operating_inputs,
        assumption=assumption,
        values=values,
        metric="equity_multiple",
    )

    assert response.json() == canonical(expected)


def test_two_way_matches_the_runner(client: TestClient) -> None:
    payload = body()
    response = client.post("/sensitivity", json={**payload, **_TWO_WAY})
    assert response.status_code == 200, response.text

    terms, inputs = direct(payload)
    expected = run_lease_level_two_way_sensitivity(
        terms,
        inputs.property_inputs,
        inputs.suites,
        inputs.leases,
        market_leasing=inputs.market_leasing,
        operating_inputs=inputs.operating_inputs,
        row_assumption=_TWO_WAY["row_assumption"],
        row_values=_TWO_WAY["row_values"],
        column_assumption=_TWO_WAY["column_assumption"],
        column_values=_TWO_WAY["column_values"],
        metric=_TWO_WAY["metric"],
    )

    assert response.json() == canonical(expected)
    assert len(response.json()["matrix"]) == 3
    assert all(len(row) == 2 for row in response.json()["matrix"])


def test_candidate_values_are_absolute_not_relative(client: TestClient) -> None:
    """``values=[0.0, 1.0]`` for ``renewal_probability`` means 0% and 100%
    renewal, not a shock applied to the baseline 70%."""

    payload = body()
    response = client.post(
        "/sensitivity/one-way",
        json={
            **payload,
            "assumption": "renewal_probability",
            "values": [0.0, 1.0],
            "metric": "equity_multiple",
        },
    )
    result = response.json()

    assert result["assumption_values"] == [0.0, 1.0]
    assert result["baseline_assumption_value"] == 0.7

    certain_new = client.post("/analyze", json=body(market_leasing=market(renewal_probability=0.0)))
    certain_renewal = client.post(
        "/analyze", json=body(market_leasing=market(renewal_probability=1.0))
    )

    assert result["metric_values"][0] == certain_new.json()["results"]["equity_multiple"]
    assert result["metric_values"][1] == certain_renewal.json()["results"]["equity_multiple"]


def test_every_cell_is_a_complete_re_underwrite(client: TestClient) -> None:
    """``1 + R*C`` full analyses, no caching, no interpolation."""

    payload = body()
    with patch(
        "anchor.analysis.lease_level_sensitivity."
        "analyze_lease_level_acquisition_with_projection",
        wraps=run_lease_level_two_way_sensitivity.__globals__[
            "analyze_lease_level_acquisition_with_projection"
        ],
    ) as spy:
        client.post("/sensitivity", json={**payload, **_TWO_WAY})

    assert spy.call_count == 1 + 3 * 2


def test_one_way_runs_one_plus_n_analyses(client: TestClient) -> None:
    payload = body()
    with patch(
        "anchor.analysis.lease_level_sensitivity."
        "analyze_lease_level_acquisition_with_projection",
        wraps=run_lease_level_one_way_sensitivity.__globals__[
            "analyze_lease_level_acquisition_with_projection"
        ],
    ) as spy:
        client.post(
            "/sensitivity/one-way",
            json={
                **payload,
                "assumption": "exit_cap_rate",
                "values": [0.06, 0.065, 0.07, 0.075],
                "metric": "levered_irr",
            },
        )

    assert spy.call_count == 1 + 4


# =============================================================================
# 2. One-way serves all three modes (D5.0 decision D3)
# =============================================================================


def test_one_way_serves_quick(client: TestClient) -> None:
    from anchor.analysis import run_one_way_sensitivity
    from anchor.validation import validate_acquisition_inputs

    response = client.post(
        "/sensitivity/one-way",
        json={
            "inputs": QUICK_INPUTS,
            "assumption": "exit_cap_rate",
            "values": [0.06, 0.07],
            "metric": "levered_irr",
        },
    )

    assert response.status_code == 200, response.text
    expected = run_one_way_sensitivity(
        validate_acquisition_inputs(QUICK_INPUTS),
        assumption="exit_cap_rate",
        values=[0.06, 0.07],
        metric="levered_irr",
    )
    assert response.json() == canonical(expected)


def test_one_way_serves_detailed(client: TestClient) -> None:
    from anchor.analysis import run_detailed_one_way_sensitivity
    from anchor.validation import (
        validate_acquisition_terms,
        validate_detailed_operating_inputs,
    )

    response = client.post(
        "/sensitivity/one-way",
        json={
            "operating_mode": "detailed",
            "terms": DETAILED_TERMS,
            "detailed_operating_inputs": DETAILED_OPERATING,
            "assumption": "interest_rate",
            "values": [0.045, 0.05],
            "metric": "equity_multiple",
        },
    )

    assert response.status_code == 200, response.text
    expected = run_detailed_one_way_sensitivity(
        validate_acquisition_terms(DETAILED_TERMS),
        validate_detailed_operating_inputs(DETAILED_OPERATING),
        assumption="interest_rate",
        values=[0.045, 0.05],
        metric="equity_multiple",
    )
    assert response.json() == canonical(expected)


def test_one_way_refuses_an_unparseable_mode(client: TestClient) -> None:
    response = client.post(
        "/sensitivity/one-way",
        json={"inputs": QUICK_INPUTS, "operating_mode": "leaselevel",
              "assumption": "ltv", "values": [0.6], "metric": "levered_irr"},
    )

    assert response.status_code == 422
    assert "must be one of" in str(detail_of(response))


# =============================================================================
# 3. Error transport -- eight distinguishable categories
# =============================================================================


def test_a_structural_parse_issue_keeps_its_path_code_and_severity(
    client: TestClient,
) -> None:
    payload = body()
    payload["suites"][0]["suite_are_sf"] = 999.0  # typo beside suite_area_sf

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    detail = detail_of(response)
    assert isinstance(detail, list)
    assert detail[0] == {
        "code": "UNKNOWN_FIELD",
        "path": "suites[0].suite_are_sf",
        "message": "is not a field of this object",
        "severity": "error",
    }


def test_a_malformed_field_keeps_its_path(client: TestClient) -> None:
    payload = body()
    payload["leases"][0]["lease_type"] = "triple net"

    detail = detail_of(client.post("/analyze", json=payload))

    assert [issue["path"] for issue in detail] == ["leases[0].lease_type"]
    assert detail[0]["code"] == "MALFORMED_FIELD"


def test_a_downstream_domain_issue_reaches_the_caller_with_its_code(
    client: TestClient,
) -> None:
    """Parsing succeeds; D1 refuses. The two phases stay distinguishable by
    ``code`` while sharing one response shape."""

    payload = body()
    payload["property_inputs"]["analysis_start_date"] = "2027-01-15"

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    codes = {issue["code"] for issue in detail_of(response)}
    assert "ANALYSIS_START_NOT_MONTH_ALIGNED" in codes


def test_non_positive_forward_exit_noi_is_refused_by_name(client: TestClient) -> None:
    """HD-D4-7 survives the trip through HTTP.

    The engine refuses to capitalise a non-positive forward NOI rather than
    flooring it, so a distressed building is refused by name instead of being
    handed an invented exit value.
    """

    payload = body(
        operating_inputs={**OPERATING, "property_taxes": 20_000_000.0},
    )

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    codes = {issue["code"] for issue in detail_of(response)}
    assert "NON_POSITIVE_FORWARD_EXIT_NOI" in codes
    assert "exit_value" not in response.text


def test_an_unknown_sensitivity_target_is_refused_with_the_supported_list(
    client: TestClient,
) -> None:
    response = client.post(
        "/sensitivity/one-way",
        json={**body(), "assumption": "noi_growth", "values": [0.03], "metric": "levered_irr"},
    )

    assert response.status_code == 422
    assert "Unknown Lease-Level sensitivity assumption" in str(detail_of(response))
    assert "renewal_probability" in str(detail_of(response))


@pytest.mark.parametrize(
    ("override_key", "shadowed", "unshadowed"),
    [
        ("market_rent_psf", "market_rent_psf", "renewal_probability"),
        ("market_leasing_override", "market_rent_psf", None),
    ],
    ids=["scalar-rent-override", "full-override"],
)
def test_a_shadowed_target_refuses_the_whole_run(
    client: TestClient, override_key: str, shadowed: str, unshadowed: str | None
) -> None:
    """D4.6B's asymmetry, preserved exactly.

    A scalar ``Suite.market_rent_psf`` shadows the rent level only; a full
    ``market_leasing_override`` shadows everything. Perturbing a property
    default that some suite overrides would produce a table that does not
    describe the property it appears to, so the run is refused rather than
    partially executed.
    """

    suite: dict[str, Any] = {"suite_id": "101", "suite_area_sf": 60_000.0}
    suite[override_key] = 38.0 if override_key == "market_rent_psf" else market()
    payload = body(
        suites=[
            suite,
            {
                "suite_id": "201",
                "suite_area_sf": 40_000.0,
                "initial_vacancy": {
                    "strategy": "market_lease_up",
                    "initial_lease_up_months": 6.0,
                },
            },
        ]
    )

    refused = client.post(
        "/sensitivity/one-way",
        json={**payload, "assumption": shadowed, "values": [34.0, 36.0], "metric": "equity_multiple"},
    )
    assert refused.status_code == 422
    assert "SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE" in str(detail_of(refused))
    assert "101" in str(detail_of(refused)), "the refusal should name the shadowing suite"
    assert "matrix" not in refused.text
    assert "metric_values" not in refused.text

    if unshadowed is not None:
        allowed = client.post(
            "/sensitivity/one-way",
            json={**payload, "assumption": unshadowed, "values": [0.5], "metric": "equity_multiple"},
        )
        assert allowed.status_code == 200, (
            "a scalar rent override must not shadow renewal_probability"
        )


def test_an_invalid_scenario_fails_the_run_rather_than_becoming_a_null_cell(
    client: TestClient,
) -> None:
    """A candidate that makes the deal unanalysable is an error, not a gap.

    Distinct from a *valid* scenario whose metric is undefined, which is a
    ``null`` cell. Conflating them would hide a broken assumption inside a table
    that looks merely incomplete.
    """

    response = client.post(
        "/sensitivity/one-way",
        json={
            **body(),
            "assumption": "exit_cap_rate",
            "values": [0.065, -0.01],
            "metric": "equity_multiple",
        },
    )

    assert response.status_code == 422
    assert "metric_values" not in response.text


def test_a_valid_scenario_with_an_undefined_metric_is_a_null_cell(
    client: TestClient,
) -> None:
    response = client.post(
        "/sensitivity/one-way",
        json={
            **body(),
            "assumption": "renewal_probability",
            "values": [0.0, 0.5, 1.0],
            "metric": "levered_irr",
        },
    )

    assert response.status_code == 200
    values = response.json()["metric_values"]
    assert None in values, "fixture no longer exercises an undefined metric"
    assert all(value is None or isinstance(value, float) for value in values)
    assert 0 not in values


def test_a_terms_error_keeps_the_shared_validation_shape(client: TestClient) -> None:
    """Terms remain owned by ``anchor.validation``, so their errors keep that
    stream's ``field_id``/``category`` shape rather than being rewritten into a
    leasing issue for cosmetic uniformity."""

    payload = body(terms={**TERMS, "ltv": 1.5})

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    detail = detail_of(response)
    assert isinstance(detail, list)
    assert set(detail[0]) == {"field_id", "category", "message"}
    assert detail[0]["field_id"] == "ltv"


def test_a_missing_terms_object_names_the_lease_level_mode(client: TestClient) -> None:
    payload = body()
    del payload["terms"]

    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    assert "lease_level" in str(detail_of(response))


def test_detailed_terms_errors_are_unchanged(client: TestClient) -> None:
    """The shared helper gained a mode label; Detailed's wording did not move."""

    response = client.post(
        "/analyze",
        json={"operating_mode": "detailed", "detailed_operating_inputs": DETAILED_OPERATING},
    )

    assert response.status_code == 422
    assert detail_of(response) == (
        "A 'detailed' operating_mode request must include a 'terms' object."
    )


# =============================================================================
# 4. The refusal ledger -- what D5.3 deliberately did not wire
# =============================================================================


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("/sensitivity/presets", {}),
        ("/break-even", {"target_levered_irr": 0.1, "target_headline_dscr": 1.2,
                         "target_equity_multiple": 1.5}),
    ],
    ids=["presets", "break-even"],
)
def test_the_gates_that_still_own_lease_level_keep_refusing(
    client: TestClient, path: str, extra: dict[str, Any]
) -> None:
    """What no D5 gate wires.

    Presets and break-even are refused for the whole of D5: there is no
    Lease-Level preset bundle, and guardrail G35 forbids a Lease-Level
    break-even. ``/deals`` and ``/deals/fingerprint`` left this list at D5.4,
    and ``/ai/analysis`` at D5.8 -- each wired by the gate that owned it.

    The presets refusal is narrower than it looks and must not be read as
    "Lease-Level has no sensitivity". D5.7 ships analyst-directed one-way and
    two-way Lease-Level sensitivity on its own endpoints; what this endpoint
    refuses is the fixed Quick/Detailed *preset bundle*, which this mode does
    not have.

    Each body is a *complete, valid* Lease-Level request, so the refusal can
    only be about the endpoint rather than about a missing field.
    """

    response = client.post(path, json={**body(), **extra})

    assert response.status_code == 422, f"{path} unexpectedly served Lease-Level"
    assert "not supported by" in str(detail_of(response))
    for marker in ("levered_irr", "equity_multiple", "matrix", "financial_input_fingerprint"):
        assert marker not in response.text


def test_updating_an_unknown_deal_is_a_404_not_a_mode_refusal(
    client: TestClient,
) -> None:
    """**Superseded at D5.4**, which wired ``PUT /deals/{id}`` for Lease-Level.

    The mode is served now, so an unknown id must be reported as an unknown id.
    Returning a mode refusal here would tell an analyst their whole workflow is
    unsupported when in fact they mistyped a deal id.
    """

    response = client.put("/deals/does-not-exist", json={**body(), "name": "x"})

    assert response.status_code == 404
    assert "not supported by" not in str(detail_of(response))


# =============================================================================
# 5. Quick and Detailed are untouched
# =============================================================================


def test_quick_analyze_is_unchanged(client: TestClient) -> None:
    import dataclasses

    from anchor.engine import analyze_acquisition
    from anchor.validation import validate_acquisition_inputs

    response = client.post("/analyze", json=QUICK_INPUTS)

    assert response.status_code == 200
    expected = dataclasses.asdict(
        analyze_acquisition(validate_acquisition_inputs(QUICK_INPUTS))
    )
    assert response.json() == json.loads(json.dumps(jsonable_encoder(expected)))


def test_detailed_analyze_is_unchanged(client: TestClient) -> None:
    import dataclasses

    from anchor.engine import analyze_detailed_acquisition_with_projection
    from anchor.validation import (
        validate_acquisition_terms,
        validate_detailed_operating_inputs,
    )

    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": DETAILED_TERMS,
            "detailed_operating_inputs": DETAILED_OPERATING,
        },
    )

    assert response.status_code == 200
    expected = dataclasses.asdict(
        analyze_detailed_acquisition_with_projection(
            validate_acquisition_terms(DETAILED_TERMS),
            validate_detailed_operating_inputs(DETAILED_OPERATING),
        )
    )
    assert response.json() == json.loads(json.dumps(jsonable_encoder(expected)))


def test_the_three_mode_union_does_not_confuse_response_shapes(
    client: TestClient,
) -> None:
    """``/analyze``'s response model is now a three-member union.

    Each mode must still get its own envelope: a flat ``AcquisitionResults`` for
    Quick, ``operating_projection`` + ``results`` for Detailed, and the
    three-surface Lease-Level envelope. A union that coerced one into another
    would silently change a shipped contract.
    """

    quick = client.post("/analyze", json=QUICK_INPUTS).json()
    detailed = client.post(
        "/analyze",
        json={"operating_mode": "detailed", "terms": DETAILED_TERMS,
              "detailed_operating_inputs": DETAILED_OPERATING},
    ).json()
    lease_level = client.post("/analyze", json=body()).json()

    assert "levered_irr" in quick and "results" not in quick
    assert sorted(detailed) == ["operating_projection", "results"]
    assert sorted(lease_level) == ["annual_projection", "monthly_projection", "results"]


# =============================================================================
# 6. Mutation kills
# =============================================================================


def test_m2_m3_lease_level_never_reaches_the_quick_or_detailed_runner(
    client: TestClient,
) -> None:
    """The oracles above prove the *right* runner ran; this proves the wrong
    ones did not, which a value comparison alone cannot."""

    # D6.5: each mode reaches the engine through its Business Plan entry point.
    with patch("anchor.api.analyze_quick_acquisition_with_business_plan") as quick_runner, patch(
        "anchor.api.analyze_detailed_acquisition_with_business_plan"
    ) as detailed_runner:
        response = client.post("/analyze", json=body())

    assert response.status_code == 200
    quick_runner.assert_not_called()
    detailed_runner.assert_not_called()


def test_m4_the_api_calls_the_approved_entry_point_exactly_once(
    client: TestClient,
) -> None:
    """M4: no hand-rolled pipeline. One call to the D4.5B bridge per request.

    D6.5: the API reaches that bridge through the D6.2 Business Plan entry
    point, which calls it exactly once, so the spy sits on the entry point."""

    import anchor.api as api_module

    with patch.object(
        api_module,
        "analyze_lease_level_acquisition_with_business_plan",
        wraps=api_module.analyze_lease_level_acquisition_with_business_plan,
    ) as spy:
        assert client.post("/analyze", json=body()).status_code == 200

    assert spy.call_count == 1


def test_m5_terms_go_through_the_shared_validator(client: TestClient) -> None:
    import anchor.api as api_module

    with patch.object(
        api_module, "validate_acquisition_terms", wraps=api_module.validate_acquisition_terms
    ) as spy:
        client.post("/analyze", json=body())

    spy.assert_called_once_with(TERMS)


def test_m6_lease_level_inputs_go_through_the_ratified_parser(
    client: TestClient,
) -> None:
    import anchor.api as api_module

    with patch.object(
        api_module, "parse_lease_level_inputs", wraps=api_module.parse_lease_level_inputs
    ) as spy:
        client.post("/analyze", json=body())

    assert spy.call_count == 1


def test_m7_the_adapter_does_not_pre_filter_unknown_keys(client: TestClient) -> None:
    """The parser must see the whole body.

    Handing it a narrowed dict would drop a typo instead of reporting it, which
    is exactly the safety D5.2 exists to provide.
    """

    payload = body()
    payload["market_leasing"]["renewal_probabilty"] = 0.7

    detail = detail_of(client.post("/analyze", json=payload))

    assert [issue["path"] for issue in detail] == ["market_leasing.renewal_probabilty"]
    assert detail[0]["code"] == "UNKNOWN_FIELD"


def test_m21_relative_interpretation_would_change_the_baseline(
    client: TestClient,
) -> None:
    """Guards the absolute-value semantics from the other direction.

    If ``values`` were treated as shocks, a candidate equal to the baseline
    would not reproduce the baseline analysis. It does.
    """

    payload = body()
    one_way = client.post(
        "/sensitivity/one-way",
        json={**payload, "assumption": "exit_cap_rate", "values": [TERMS["exit_cap_rate"]],
              "metric": "equity_multiple"},
    ).json()

    baseline = client.post("/analyze", json=payload).json()["results"]["equity_multiple"]
    assert one_way["metric_values"][0] == baseline
    assert one_way["baseline_metric_value"] == baseline


# =============================================================================
# 7. The adapter computes nothing
#
# The behavioural oracles prove the API returned the engine's numbers today.
# These prove it has no *capacity* to have produced them itself, which is the
# property that survives a refactor nobody re-runs the oracles against.
# =============================================================================


def _api_code_only() -> str:
    """``api.py``'s executable text, docstrings and comments stripped.

    The module legitimately *describes* the economics it refuses to perform;
    prose is not behaviour, and a guardrail that read it would forbid explaining
    the boundary.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "anchor" / "api.py"
    ).read_text(encoding="utf-8")
    stripped = ast.parse(ast.unparse(ast.parse(source)))
    for node in ast.walk(stripped):
        node_body = getattr(node, "body", None)
        if isinstance(node_body, list):
            node_body[:] = [
                statement
                for statement in node_body
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                )
            ]
    return ast.unparse(stripped)


def test_the_api_reproduces_no_lease_level_financial_vocabulary() -> None:
    code = _api_code_only().lower()

    for forbidden in (
        "base_rent",
        "free_rent",
        "escalation",
        "rollover",
        "downtime",
        "recovery",
        "expense_stop",
        "tenant_improvement",
        "leasing_commission",
        "exit_noi",
        "physical_occupancy",
        "noi_by_year",
        "cash_base_rent",
        "effective_gross_income",
    ):
        assert forbidden not in code, (
            f"api.py names {forbidden!r}; the adapter turns JSON into arguments "
            "and must not touch a financial series"
        )


def test_the_api_derives_no_annual_value_from_a_monthly_one() -> None:
    """M22. Both surfaces already come from Python, derived canonically in
    ``leasing/projection.py``; an adapter-side rollup would be a second,
    unreviewed derivation of the same numbers."""

    code = _api_code_only()

    for forbidden in ("/ 12", "* 12", "monthly_projection.", "annual_projection.", "sum("):
        assert forbidden not in code, f"api.py performs {forbidden!r}"


def test_the_api_reads_no_field_of_a_lease_level_result() -> None:
    """The envelope is returned whole. Reading a field would be the first step
    toward reshaping one."""

    code = _api_code_only()

    for forbidden in (".results.", ".monthly_projection", ".annual_projection"):
        assert forbidden not in code, f"api.py inspects {forbidden!r}"


def test_the_api_calls_no_leasing_builder() -> None:
    """M4, structurally: composition happens through the one D4.5B bridge."""

    code = _api_code_only()

    for forbidden in (
        "build_model_months",
        "build_recursive_rollover",
        "build_initial_vacancy_rollover",
        "build_property_expense_schedule",
        "build_recoverable_expense_pool",
        "build_monthly_property_projection",
        "aggregate_monthly_to_annual",
        "require_valid_lease_level_inputs",
        "Suite(",
        "Lease(",
        "MarketLeasingAssumptions(",
    ):
        assert forbidden not in code, f"api.py reaches {forbidden}"
