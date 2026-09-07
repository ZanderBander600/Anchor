"""D5.2 -- structural parsing of Lease-Level request bodies.

Three properties, in the order they matter:

1. **Round trip.** Every supported contract survives
   ``dataclass -> JSON-compatible mapping -> parser -> dataclass`` unchanged.
   Built from ``dataclasses.asdict`` on real instances rather than hand-typed
   fixtures, so a field added to a contract is exercised automatically instead
   of silently escaping the suite.
2. **Refusal.** Unknown keys, missing required fields and malformed values are
   reported with a stable code, a located path and ERROR severity -- never a
   leaked Python exception message.
3. **Phase separation.** Structurally-valid but economically-invalid payloads
   *parse*, and the existing downstream validators then raise the exact domain
   codes they always did. This is the property the whole gate exists for: the
   parser must not become a second, unreviewed underwriting authority.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import pytest

from anchor.leasing.contracts import (
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecoveryBasis,
    Suite,
)
from anchor.leasing.parsing import ParsedLeaseLevelRequest, parse_lease_level_request
from anchor.leasing.validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
)

# =============================================================================
# Fixtures -- real contracts, so wire fixtures are derived rather than typed
# =============================================================================

PROPERTY_INPUTS = LeaseLevelPropertyInputs(
    analysis_start_date=date(2027, 1, 1), rentable_area_sf=120_000.0
)

OPERATING_INPUTS = LeaseLevelOperatingInputs(
    other_income=50_000.0,
    other_income_growth=0.03,
    credit_loss_pct=0.01,
    property_taxes=600_000.0,
    insurance=90_000.0,
    utilities=140_000.0,
    repairs_maintenance=110_000.0,
    other_operating_expenses=60_000.0,
    management_fee_pct=0.03,
    expense_growth=0.03,
    recoverable_expense_ratio=0.85,
)

MARKET_LEASING = MarketLeasingAssumptions(
    market_rent_psf=34.0,
    market_rent_growth=0.03,
    renewal_rent_psf=None,
    renewal_rent_spread=0.0,
    renewal_term_months=60,
    successor_escalation_pct=0.03,
    renewal_downtime_months=0.0,
    renewal_free_rent_months=1.0,
    new_term_months=60,
    new_downtime_months=6.0,
    new_free_rent_months=3.0,
    renewal_ti_psf=15.0,
    new_ti_psf=45.0,
    leasing_commission_method=LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
    renewal_lc_pct=0.03,
    new_lc_pct=0.06,
    renewal_probability=0.7,
    renewal_lease_type=LeaseType.NNN,
    renewal_recovery_basis=None,
    renewal_expense_stop_psf=None,
    new_lease_type=LeaseType.NNN,
    new_recovery_basis=None,
    new_expense_stop_psf=None,
)

OCCUPIED_SUITE = Suite(suite_id="101", suite_area_sf=70_000.0, suite_label="Ground")

VACANT_SUITE = Suite(
    suite_id="201",
    suite_area_sf=50_000.0,
    market_rent_psf=36.0,
    initial_vacancy=InitialVacancyAssumptions(
        strategy=InitialVacancyStrategy.MARKET_LEASE_UP, initial_lease_up_months=6.0
    ),
)

IN_PLACE_LEASE = Lease(
    lease_id="L-101",
    suite_id="101",
    leased_area_sf=70_000.0,
    rent_commencement_date=date(2024, 3, 1),
    lease_expiration_date=date(2029, 2, 28),
    base_rent_psf=32.5,
    escalation_pct=0.03,
    escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
    lease_type=LeaseType.NNN,
    tenant_name="Anchor Tenant",
)


def _wire(value: Any) -> Any:
    """A contract as JSON would carry it: dates as ISO strings, enums as their
    wire tokens, nested dataclasses as objects."""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _wire(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (LeaseType, RecoveryBasis, EscalationBasis, LeaseOrigin,
                          LeasingCommissionMethod, InitialVacancyStrategy)):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


def request_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "property_inputs": _wire(PROPERTY_INPUTS),
        "operating_inputs": _wire(OPERATING_INPUTS),
        "market_leasing": _wire(MARKET_LEASING),
        "suites": [_wire(OCCUPIED_SUITE), _wire(VACANT_SUITE)],
        "leases": [_wire(IN_PLACE_LEASE)],
    }
    payload.update(overrides)
    return payload


def issues_of(payload: dict[str, Any]):
    with pytest.raises(LeaseValidationError) as excinfo:
        parse_lease_level_request(payload)
    return excinfo.value.result.issues


# =============================================================================
# 1. Round trip
# =============================================================================


def test_the_whole_request_round_trips() -> None:
    parsed = parse_lease_level_request(request_payload())

    assert parsed == ParsedLeaseLevelRequest(
        property_inputs=PROPERTY_INPUTS,
        operating_inputs=OPERATING_INPUTS,
        market_leasing=MARKET_LEASING,
        suites=(OCCUPIED_SUITE, VACANT_SUITE),
        leases=(IN_PLACE_LEASE,),
    )


@pytest.mark.parametrize(
    "original",
    [
        PROPERTY_INPUTS,
        OPERATING_INPUTS,
        MARKET_LEASING,
        OCCUPIED_SUITE,
        VACANT_SUITE,
        IN_PLACE_LEASE,
    ],
    ids=lambda value: type(value).__name__ + ("-vacant" if getattr(value, "initial_vacancy", None) else ""),
)
def test_every_contract_round_trips_field_for_field(original: Any) -> None:
    """Each contract, through the real request, compared field by field.

    Field-by-field rather than only ``==`` so a failure names the field.
    """

    field_name = {
        LeaseLevelPropertyInputs: "property_inputs",
        LeaseLevelOperatingInputs: "operating_inputs",
        MarketLeasingAssumptions: "market_leasing",
    }.get(type(original))

    if field_name is not None:
        parsed = getattr(parse_lease_level_request(request_payload()), field_name)
        # Re-parse with this exact instance to prove *this* value round-tripped.
        parsed = getattr(
            parse_lease_level_request(request_payload(**{field_name: _wire(original)})),
            field_name,
        )
    elif isinstance(original, Suite):
        parsed = parse_lease_level_request(request_payload(suites=[_wire(original)])).suites[0]
    else:
        parsed = parse_lease_level_request(request_payload(leases=[_wire(original)])).leases[0]

    for field in dataclasses.fields(original):
        assert getattr(parsed, field.name) == getattr(original, field.name), field.name
    assert parsed == original


def test_nested_initial_vacancy_becomes_the_frozen_contract() -> None:
    parsed = parse_lease_level_request(request_payload()).suites[1]

    assert isinstance(parsed.initial_vacancy, InitialVacancyAssumptions)
    assert parsed.initial_vacancy.strategy is InitialVacancyStrategy.MARKET_LEASE_UP
    assert parsed.initial_vacancy.initial_lease_up_months == 6.0


def test_nested_market_leasing_override_becomes_the_frozen_contract() -> None:
    suite = _wire(OCCUPIED_SUITE) | {"market_leasing_override": _wire(MARKET_LEASING)}
    parsed = parse_lease_level_request(request_payload(suites=[suite])).suites[0]

    assert isinstance(parsed.market_leasing_override, MarketLeasingAssumptions)
    assert parsed.market_leasing_override == MARKET_LEASING


def test_an_absent_override_stays_none_rather_than_a_partial_record() -> None:
    parsed = parse_lease_level_request(request_payload()).suites[0]

    assert parsed.market_leasing_override is None
    assert parsed.initial_vacancy is None


def test_explicit_null_override_is_none() -> None:
    suite = _wire(OCCUPIED_SUITE) | {"market_leasing_override": None}
    parsed = parse_lease_level_request(request_payload(suites=[suite])).suites[0]

    assert parsed.market_leasing_override is None


def test_collections_become_tuples_in_request_order() -> None:
    parsed = parse_lease_level_request(request_payload())

    assert isinstance(parsed.suites, tuple)
    assert isinstance(parsed.leases, tuple)
    assert [suite.suite_id for suite in parsed.suites] == ["101", "201"]


def test_collections_are_neither_sorted_nor_deduplicated() -> None:
    """Ordering and duplicates are downstream questions, not transport ones."""

    duplicate = _wire(OCCUPIED_SUITE)
    parsed = parse_lease_level_request(
        request_payload(suites=[_wire(VACANT_SUITE), duplicate, duplicate])
    )

    assert [suite.suite_id for suite in parsed.suites] == ["201", "101", "101"]


def test_an_empty_collection_parses() -> None:
    parsed = parse_lease_level_request(request_payload(suites=[], leases=[]))

    assert parsed.suites == ()
    assert parsed.leases == ()


# =============================================================================
# 2. Contract defaults apply; the parser invents none
# =============================================================================


def test_an_omitted_defaulted_field_takes_the_contracts_default() -> None:
    lease = _wire(IN_PLACE_LEASE)
    del lease["origin"]
    del lease["recovery_basis"]

    parsed = parse_lease_level_request(request_payload(leases=[lease])).leases[0]

    assert parsed.origin is LeaseOrigin.IN_PLACE
    assert parsed.recovery_basis is None


def test_an_omitted_defaulted_operating_field_takes_the_contracts_default() -> None:
    operating = _wire(OPERATING_INPUTS)
    del operating["credit_loss_pct"]

    parsed = parse_lease_level_request(request_payload(operating_inputs=operating))

    assert parsed.operating_inputs.credit_loss_pct == 0.0


def test_a_required_nullable_field_still_has_to_be_supplied() -> None:
    """``renewal_rent_psf`` is ``float | None`` *and* required.

    "Stated as absent" and "not stated" are different facts on this contract, so
    omitting the key is a structural failure even though ``null`` is a legal
    value for it.
    """

    market = _wire(MARKET_LEASING)
    del market["renewal_rent_psf"]

    issues = issues_of(request_payload(market_leasing=market))

    assert [issue.path for issue in issues] == ["market_leasing.renewal_rent_psf"]
    assert issues[0].code is LeaseIssueCode.MALFORMED_FIELD


# =============================================================================
# 3. Unknown fields
# =============================================================================


@pytest.mark.parametrize(
    ("payload_builder", "expected_path"),
    [
        (lambda: request_payload(rental_roll=[]), "rental_roll"),
        (
            lambda: request_payload(
                property_inputs=_wire(PROPERTY_INPUTS) | {"rentable_are_sf": 1.0}
            ),
            "property_inputs.rentable_are_sf",
        ),
        (
            lambda: request_payload(
                operating_inputs=_wire(OPERATING_INPUTS) | {"insurance_pct": 1.0}
            ),
            "operating_inputs.insurance_pct",
        ),
        (
            lambda: request_payload(
                market_leasing=_wire(MARKET_LEASING) | {"renewal_probabilty": 0.7}
            ),
            "market_leasing.renewal_probabilty",
        ),
        (
            lambda: request_payload(suites=[_wire(OCCUPIED_SUITE) | {"suite_are_sf": 999.0}]),
            "suites[0].suite_are_sf",
        ),
        (
            lambda: request_payload(leases=[_wire(IN_PLACE_LEASE) | {"tenant": "x"}]),
            "leases[0].tenant",
        ),
        (
            lambda: request_payload(
                suites=[
                    _wire(VACANT_SUITE)
                    | {
                        "initial_vacancy": _wire(VACANT_SUITE.initial_vacancy)
                        | {"lease_up_months": 6.0}
                    }
                ]
            ),
            "suites[0].initial_vacancy.lease_up_months",
        ),
        (
            lambda: request_payload(
                suites=[
                    _wire(OCCUPIED_SUITE)
                    | {"market_leasing_override": _wire(MARKET_LEASING) | {"nope": 1.0}}
                ]
            ),
            "suites[0].market_leasing_override.nope",
        ),
    ],
    ids=[
        "top-level",
        "property_inputs",
        "operating_inputs",
        "market_leasing",
        "suite",
        "lease",
        "initial_vacancy",
        "market_leasing_override",
    ],
)
def test_an_unknown_key_is_reported_at_its_path(payload_builder, expected_path: str) -> None:
    """A typo must never be silently discarded -- that is the whole point.

    ``suite_are_sf`` beside ``suite_area_sf`` would otherwise vanish, and the
    suite would be underwritten with a stale area nobody typed.
    """

    issues = issues_of(payload_builder())
    unknown = [issue for issue in issues if issue.code is LeaseIssueCode.UNKNOWN_FIELD]

    assert [issue.path for issue in unknown] == [expected_path]
    assert unknown[0].severity is LeaseIssueSeverity.ERROR


def test_the_api_owned_top_level_keys_are_not_unknown() -> None:
    """``operating_mode`` and ``terms`` belong to the API adapter and to
    ``validate_acquisition_terms``; the parser must not report them as typos."""

    payload = request_payload(operating_mode="lease_level", terms={"purchase_price": 1.0})

    parse_lease_level_request(payload)  # does not raise


# =============================================================================
# 4. Malformed fields
# =============================================================================


@pytest.mark.parametrize(
    ("payload_builder", "expected_path"),
    [
        (
            lambda: request_payload(
                property_inputs=_wire(PROPERTY_INPUTS) | {"rentable_area_sf": "120000"}
            ),
            "property_inputs.rentable_area_sf",
        ),
        (
            lambda: request_payload(
                property_inputs=_wire(PROPERTY_INPUTS) | {"analysis_start_date": "01/15/2027"}
            ),
            "property_inputs.analysis_start_date",
        ),
        (
            lambda: request_payload(
                property_inputs=_wire(PROPERTY_INPUTS) | {"analysis_start_date": "2027-13-01"}
            ),
            "property_inputs.analysis_start_date",
        ),
        (
            lambda: request_payload(leases=[_wire(IN_PLACE_LEASE) | {"lease_type": "triple net"}]),
            "leases[0].lease_type",
        ),
        (
            lambda: request_payload(
                market_leasing=_wire(MARKET_LEASING) | {"renewal_term_months": 60.5}
            ),
            "market_leasing.renewal_term_months",
        ),
        (
            lambda: request_payload(
                market_leasing=_wire(MARKET_LEASING) | {"market_rent_psf": True}
            ),
            "market_leasing.market_rent_psf",
        ),
        (
            lambda: request_payload(
                property_inputs=_wire(PROPERTY_INPUTS) | {"rentable_area_sf": None}
            ),
            "property_inputs.rentable_area_sf",
        ),
        (lambda: request_payload(suites={"suite_id": "101"}), "suites"),
        (lambda: request_payload(property_inputs=[1, 2]), "property_inputs"),
        (lambda: request_payload(suites=["not-an-object"]), "suites[0]"),
        (lambda: request_payload(leases=[None]), "leases[0]"),
        (
            lambda: request_payload(
                suites=[_wire(VACANT_SUITE) | {"initial_vacancy": "market_lease_up"}]
            ),
            "suites[0].initial_vacancy",
        ),
        (
            lambda: request_payload(
                suites=[_wire(VACANT_SUITE) | {"initial_vacancy": {"strategy": "sell_it"}}]
            ),
            "suites[0].initial_vacancy.strategy",
        ),
    ],
    ids=[
        "numeric-string",
        "us-date",
        "impossible-date",
        "enum-alias",
        "fractional-int",
        "boolean-as-number",
        "null-into-non-nullable",
        "object-where-array",
        "array-where-object",
        "non-object-suite-element",
        "null-lease-element",
        "string-where-nested-object",
        "invalid-nested-enum",
    ],
)
def test_a_malformed_value_is_reported_at_its_path(payload_builder, expected_path: str) -> None:
    issues = issues_of(payload_builder())
    malformed = [issue for issue in issues if issue.code is LeaseIssueCode.MALFORMED_FIELD]

    assert expected_path in [issue.path for issue in malformed]
    assert all(issue.severity is LeaseIssueSeverity.ERROR for issue in issues)


def test_no_python_exception_text_leaks_into_a_message() -> None:
    """Messages are Anchor's, not the standard library's.

    ``date.fromisoformat`` says "Invalid isoformat string: '01/15/2027'"; leaking
    that would put a Python concept, a quoted echo of user input, and a message
    that changes between interpreter versions into an API response.
    """

    payloads = [
        request_payload(property_inputs=_wire(PROPERTY_INPUTS) | {"analysis_start_date": "01/15/2027"}),
        request_payload(leases=[_wire(IN_PLACE_LEASE) | {"lease_type": "triple net"}]),
        request_payload(suites=[_wire(OCCUPIED_SUITE) | {"suite_area_sf": "big"}]),
    ]
    for payload in payloads:
        for issue in issues_of(payload):
            lowered = issue.message.lower()
            for leaked in ("isoformat", "traceback", "typeerror", "valueerror",
                           "keyerror", "__init__", "unexpected keyword", "nonetype"):
                assert leaked not in lowered, issue.message


def test_a_missing_top_level_part_is_reported() -> None:
    payload = request_payload()
    del payload["market_leasing"]

    issues = issues_of(payload)

    assert [issue.path for issue in issues] == ["market_leasing"]
    assert issues[0].code is LeaseIssueCode.MALFORMED_FIELD


def test_a_non_mapping_payload_is_refused() -> None:
    issues = issues_of([])  # type: ignore[arg-type]

    assert issues[0].code is LeaseIssueCode.MALFORMED_FIELD


# =============================================================================
# 5. Numeric semantics -- following anchor.validation's shipped precedent
# =============================================================================


def test_a_json_integer_satisfies_a_float_field() -> None:
    """Widening, exactly as ``_normalize_field_value`` does with ``float(value)``."""

    parsed = parse_lease_level_request(
        request_payload(property_inputs={"analysis_start_date": "2027-01-01", "rentable_area_sf": 120_000})
    )

    assert parsed.property_inputs.rentable_area_sf == 120_000.0
    assert isinstance(parsed.property_inputs.rentable_area_sf, float)


def test_an_integral_float_satisfies_an_int_field() -> None:
    """Mirrors the ``is_integer()`` gate ``validation.py`` applies to year fields."""

    parsed = parse_lease_level_request(
        request_payload(market_leasing=_wire(MARKET_LEASING) | {"renewal_term_months": 60.0})
    )

    assert parsed.market_leasing.renewal_term_months == 60
    assert isinstance(parsed.market_leasing.renewal_term_months, int)


def test_a_boolean_is_never_a_number() -> None:
    """``bool`` subclasses ``int``; ``validation.py:240`` rejects it explicitly
    and so does this parser, or ``true`` would silently underwrite as ``1``."""

    for field, container in (("renewal_term_months", "market_leasing"), ("market_rent_psf", "market_leasing")):
        issues = issues_of(request_payload(market_leasing=_wire(MARKET_LEASING) | {field: True}))
        assert [issue.path for issue in issues] == [f"{container}.{field}"]


def test_a_non_finite_number_is_refused() -> None:
    issues = issues_of(
        request_payload(market_leasing=_wire(MARKET_LEASING) | {"market_rent_psf": float("inf")})
    )

    assert [issue.path for issue in issues] == ["market_leasing.market_rent_psf"]


# =============================================================================
# 6. Deterministic ordering
# =============================================================================


def _mixed_payload(ordering: str) -> dict[str, Any]:
    """One payload carrying an unknown key, a missing required field and a
    malformed value, buildable with two different key insertion orders."""

    suite = {
        "suite_id": "101",
        "suite_area_sf": "seventy thousand",  # malformed
        "suite_lable": "Ground",  # unknown
        # suite_area_sf present but malformed; nothing missing here
    }
    market = _wire(MARKET_LEASING)
    del market["renewal_probability"]  # missing

    payload = request_payload(suites=[suite], market_leasing=market)
    if ordering == "reversed":
        payload = dict(reversed(list(payload.items())))
        payload["suites"] = [dict(reversed(list(suite.items())))]
        payload["market_leasing"] = dict(reversed(list(market.items())))
    return payload


def test_issues_are_ordered_unknown_then_missing_then_malformed() -> None:
    issues = issues_of(_mixed_payload("natural"))
    codes = [issue.code for issue in issues]

    assert codes[0] is LeaseIssueCode.UNKNOWN_FIELD
    assert issues[0].path == "suites[0].suite_lable"
    assert [issue.path for issue in issues[1:]] == [
        "market_leasing.renewal_probability",
        "suites[0].suite_area_sf",
    ]


def test_ordering_does_not_depend_on_key_insertion_order() -> None:
    natural = issues_of(_mixed_payload("natural"))
    reversed_ = issues_of(_mixed_payload("reversed"))

    assert [(issue.code, issue.path) for issue in natural] == [
        (issue.code, issue.path) for issue in reversed_
    ]


def test_every_issue_in_a_multi_error_payload_is_reported_at_once() -> None:
    """Collect, do not short-circuit: an analyst fixing a rent roll should see
    every malformed row in one response."""

    suites = [
        _wire(OCCUPIED_SUITE) | {"suite_area_sf": "a"},
        _wire(VACANT_SUITE) | {"suite_area_sf": "b"},
        _wire(OCCUPIED_SUITE) | {"suite_area_sf": "c"},
    ]
    issues = issues_of(request_payload(suites=suites))

    assert [issue.path for issue in issues] == [
        "suites[0].suite_area_sf",
        "suites[1].suite_area_sf",
        "suites[2].suite_area_sf",
    ]


# =============================================================================
# 7. Phase separation -- the property the gate exists for
# =============================================================================


def test_renewal_probability_above_one_parses_and_is_refused_downstream() -> None:
    from anchor.leasing.validation import require_valid_lease_level_inputs

    payload = request_payload(
        market_leasing=_wire(MARKET_LEASING) | {"renewal_probability": 1.2}
    )
    parsed = parse_lease_level_request(payload)

    assert parsed.market_leasing.renewal_probability == 1.2

    with pytest.raises(LeaseValidationError) as excinfo:
        require_valid_lease_level_inputs(
            parsed.property_inputs,
            parsed.suites,
            parsed.leases,
            hold_period=5,
            market_leasing=parsed.market_leasing,
        )

    codes = {issue.code for issue in excinfo.value.result.errors}
    assert LeaseIssueCode.RENEWAL_PROBABILITY_OUT_OF_DOMAIN in codes


def test_a_mid_month_analysis_start_parses_and_is_refused_downstream() -> None:
    from anchor.leasing.validation import require_valid_lease_level_inputs

    payload = request_payload(
        property_inputs=_wire(PROPERTY_INPUTS) | {"analysis_start_date": "2027-01-15"}
    )
    parsed = parse_lease_level_request(payload)

    assert parsed.property_inputs.analysis_start_date == date(2027, 1, 15)

    with pytest.raises(LeaseValidationError) as excinfo:
        require_valid_lease_level_inputs(
            parsed.property_inputs,
            parsed.suites,
            parsed.leases,
            hold_period=5,
            market_leasing=parsed.market_leasing,
        )

    codes = {issue.code for issue in excinfo.value.result.errors}
    assert LeaseIssueCode.ANALYSIS_START_NOT_MONTH_ALIGNED in codes


def test_a_negative_rentable_area_parses_and_is_refused_downstream() -> None:
    from anchor.leasing.validation import require_valid_lease_level_inputs

    payload = request_payload(
        property_inputs=_wire(PROPERTY_INPUTS) | {"rentable_area_sf": -100.0}
    )
    parsed = parse_lease_level_request(payload)

    assert parsed.property_inputs.rentable_area_sf == -100.0

    with pytest.raises(LeaseValidationError) as excinfo:
        require_valid_lease_level_inputs(
            parsed.property_inputs,
            parsed.suites,
            parsed.leases,
            hold_period=5,
            market_leasing=parsed.market_leasing,
        )

    codes = {issue.code for issue in excinfo.value.result.errors}
    assert LeaseIssueCode.RENTABLE_AREA_OUT_OF_DOMAIN in codes


def test_two_leases_on_one_suite_parse_and_are_refused_downstream() -> None:
    from anchor.leasing.validation import require_valid_lease_level_acquisition_leases

    second = _wire(IN_PLACE_LEASE) | {
        "lease_id": "L-101B",
        "rent_commencement_date": "2029-03-01",
        "lease_expiration_date": "2034-02-28",
    }
    parsed = parse_lease_level_request(
        request_payload(leases=[_wire(IN_PLACE_LEASE), second])
    )

    assert len(parsed.leases) == 2

    with pytest.raises(LeaseValidationError) as excinfo:
        require_valid_lease_level_acquisition_leases(parsed.suites, parsed.leases)

    codes = {issue.code for issue in excinfo.value.result.errors}
    assert LeaseIssueCode.MULTIPLE_KNOWN_LEASES_IN_SUITE in codes


def test_a_fully_valid_request_passes_both_phases() -> None:
    """The positive control: parsing and domain validation agree on a good deal."""

    from anchor.leasing.validation import require_valid_lease_level_inputs

    parsed = parse_lease_level_request(request_payload())
    result = require_valid_lease_level_inputs(
        parsed.property_inputs,
        parsed.suites,
        parsed.leases,
        hold_period=5,
        market_leasing=parsed.market_leasing,
    )

    assert result.errors == ()
