"""Sprint D Gate D1.0 -- leasing-scoped validation.

Proves, per
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 5.5, 19 and 20:

1. Every D1 ERROR rule in Section 19.2 fires with the correct code and path.
2. Rentable area reconciles exactly; any mismatch is an ERROR.
3. Golden case **D1-G10** (all six sub-cases, Section 27) passes -- including
   the leap-February trap and the out-of-window case.
4. Golden case **D1-G9**'s month-end boundaries all validate cleanly.
5. Issue ordering is deterministic across repeated runs.
6. Nothing is coerced, rounded, defaulted, or inferred.
"""

from __future__ import annotations

from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseLevelPropertyInputs,
    LeaseType,
    LeaseValidationError,
    Suite,
    require_valid_lease_level_inputs,
    validate_lease_level_inputs,
)


ANALYSIS_START = date(2026, 1, 1)


def property_inputs(**overrides: object) -> LeaseLevelPropertyInputs:
    fields: dict[str, object] = {
        "analysis_start_date": ANALYSIS_START,
        "rentable_area_sf": 10_000.0,
    }
    fields.update(overrides)
    return LeaseLevelPropertyInputs(**fields)  # type: ignore[arg-type]


def suite(**overrides: object) -> Suite:
    fields: dict[str, object] = {"suite_id": "S1", "suite_area_sf": 10_000.0}
    fields.update(overrides)
    return Suite(**fields)  # type: ignore[arg-type]


def lease(**overrides: object) -> Lease:
    fields: dict[str, object] = {
        "lease_id": "L1",
        "suite_id": "S1",
        "leased_area_sf": 10_000.0,
        "rent_commencement_date": date(2026, 1, 1),
        "lease_expiration_date": date(2030, 12, 31),
        "base_rent_psf": 30.0,
        "escalation_pct": 0.03,
        "escalation_basis": EscalationBasis.LEASE_ANNIVERSARY,
        "lease_type": LeaseType.NNN,
    }
    fields.update(overrides)
    return Lease(**fields)  # type: ignore[arg-type]


def codes(result) -> list[LeaseIssueCode]:
    return [issue.code for issue in result.issues]


# =============================================================================
# Valid baseline
# =============================================================================


def test_a_minimal_valid_input_set_produces_no_issues() -> None:
    result = validate_lease_level_inputs(property_inputs(), [suite()], [lease()])

    assert result.is_valid
    assert result.issues == ()
    assert result.errors == ()
    assert result.warnings == ()


def test_a_valid_multi_suite_multi_lease_input_set_validates_cleanly() -> None:
    inputs = property_inputs(rentable_area_sf=10_000.0)
    suites = [
        suite(suite_id="S1", suite_area_sf=6_000.0, suite_label="Suite 100"),
        suite(suite_id="S2", suite_area_sf=4_000.0),
    ]
    leases = [
        lease(lease_id="L1", suite_id="S1", leased_area_sf=6_000.0),
        lease(
            lease_id="L2",
            suite_id="S2",
            leased_area_sf=4_000.0,
            lease_expiration_date=date(2027, 12, 31),
            escalation_basis=EscalationBasis.NONE,
            escalation_pct=0.0,
            lease_type=LeaseType.GROSS,
        ),
    ]

    result = validate_lease_level_inputs(inputs, suites, leases)

    assert result.is_valid
    assert result.issues == ()


def test_require_valid_returns_the_result_when_there_are_no_errors() -> None:
    result = require_valid_lease_level_inputs(property_inputs(), [suite()], [lease()])

    assert result.is_valid


# =============================================================================
# Property / analysis-start rules
# =============================================================================


def test_mid_month_analysis_start_date_is_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(analysis_start_date=date(2026, 1, 15)), [suite()], [lease()]
    )

    assert LeaseIssueCode.ANALYSIS_START_NOT_MONTH_ALIGNED in codes(result)
    assert not result.is_valid


@pytest.mark.parametrize("area", [0.0, -1.0])
def test_non_positive_property_area_is_an_error(area: float) -> None:
    result = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=area), [suite()], [lease()]
    )

    assert LeaseIssueCode.RENTABLE_AREA_OUT_OF_DOMAIN in codes(result)


def test_non_finite_property_area_is_a_non_finite_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=float("nan")), [suite()], [lease()]
    )

    assert LeaseIssueCode.NON_FINITE_VALUE in codes(result)


# =============================================================================
# D1-G9 -- supported month-end boundaries all validate cleanly
# =============================================================================


@pytest.mark.parametrize(
    ("commencement", "expiration", "label"),
    [
        (date(2026, 1, 1), date(2026, 12, 31), "31-day month end"),
        (date(2026, 2, 1), date(2026, 4, 30), "30-day month end"),
        (date(2027, 1, 1), date(2027, 2, 28), "non-leap February"),
        (date(2028, 1, 1), date(2028, 2, 29), "leap February"),
    ],
)
def test_d1_g9_supported_date_boundaries_validate(
    commencement: date, expiration: date, label: str
) -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(rent_commencement_date=commencement, lease_expiration_date=expiration)],
    )

    assert result.is_valid, f"{label} should validate: {codes(result)}"


# =============================================================================
# D1-G10 -- unsupported non-month-aligned dates are ERROR, never a warning
# =============================================================================


def test_d1_g10a_mid_month_rent_commencement_is_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(rent_commencement_date=date(2026, 1, 15))],
    )

    assert codes(result) == [LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED]
    assert result.issues[0].path == "leases[0].rent_commencement_date"
    assert result.issues[0].severity is LeaseIssueSeverity.ERROR


def test_d1_g10b_mid_month_expiration_is_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(lease_expiration_date=date(2028, 6, 15))],
    )

    assert codes(result) == [LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED]
    assert result.issues[0].path == "leases[0].lease_expiration_date"


def test_d1_g10c_february_28_in_a_leap_year_is_not_a_month_end() -> None:
    """2028 is a leap year, so February has 29 days and the 28th is not the
    last day. The check must be calendar-aware, not a lookup table."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(lease_expiration_date=date(2028, 2, 28))],
    )

    assert codes(result) == [LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED]
    assert result.issues[0].path == "leases[0].lease_expiration_date"


def test_d1_g10d_mid_month_analysis_start_is_its_own_error_code() -> None:
    result = validate_lease_level_inputs(
        property_inputs(analysis_start_date=date(2026, 1, 15)), [suite()], [lease()]
    )

    assert codes(result) == [LeaseIssueCode.ANALYSIS_START_NOT_MONTH_ALIGNED]
    assert result.issues[0].path == "property.analysis_start_date"


def test_d1_g10e_alignment_is_enforced_outside_the_projection_window_too() -> None:
    """D0 Section 5.5: the rule is hold-period-independent. A rule that
    depended on H would make the same rent roll validate at H=5 and fail at
    H=10 -- a surprise with no economic justification."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(
                rent_commencement_date=date(2040, 1, 15),
                lease_expiration_date=date(2045, 12, 31),
            )
        ],
    )

    assert LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED in codes(result)


def test_d1_g10f_informational_lease_start_date_is_not_alignment_validated() -> None:
    """D0 Section 4.4/5.5: ``lease_start_date`` is possession, never enters an
    economic calculation, and is therefore deliberately exempt."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(lease_start_date=date(2025, 11, 17))],
    )

    assert result.is_valid


def test_no_misaligned_date_is_ever_downgraded_to_a_warning() -> None:
    result = validate_lease_level_inputs(
        property_inputs(analysis_start_date=date(2026, 3, 10)),
        [suite()],
        [
            lease(
                rent_commencement_date=date(2026, 3, 10),
                lease_expiration_date=date(2029, 6, 14),
            )
        ],
    )

    assert result.warnings == ()
    assert all(
        issue.severity is LeaseIssueSeverity.ERROR for issue in result.issues
    )


# =============================================================================
# Other date rules
# =============================================================================


def test_expiration_before_commencement_is_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(
                rent_commencement_date=date(2028, 1, 1),
                lease_expiration_date=date(2027, 12, 31),
            )
        ],
    )

    assert LeaseIssueCode.LEASE_EXPIRES_BEFORE_COMMENCEMENT in codes(result)


def test_possession_after_rent_commencement_is_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(lease_start_date=date(2026, 2, 1))],
    )

    assert LeaseIssueCode.LEASE_POSSESSION_AFTER_RENT_START in codes(result)


def test_a_lease_expired_before_the_analysis_start_is_an_error() -> None:
    """D0 Section 6.4 / 19.2: it is not a lease of this deal."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(
                rent_commencement_date=date(2020, 1, 1),
                lease_expiration_date=date(2025, 12, 31),
            )
        ],
    )

    assert LeaseIssueCode.LEASE_EXPIRED_BEFORE_ANALYSIS_START in codes(result)


def test_a_lease_expiring_in_the_analysis_start_month_is_still_current() -> None:
    """Expiration is inclusive and month-granular: a lease ending on the last
    day of Month 1 pays Month 1 and is not 'already expired'."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(
                rent_commencement_date=date(2020, 1, 1),
                lease_expiration_date=date(2026, 1, 31),
            )
        ],
    )

    assert result.is_valid


def test_a_lease_commencing_before_the_analysis_start_is_valid() -> None:
    """An in-place lease acquired midway through its term is the normal case,
    not an error -- D1.2 places it on its correct contractual step."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(rent_commencement_date=date(2024, 1, 1))],
    )

    assert result.is_valid


def test_a_future_known_lease_is_valid() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(
                rent_commencement_date=date(2027, 4, 1),
                lease_expiration_date=date(2032, 3, 31),
            )
        ],
    )

    assert result.is_valid


# =============================================================================
# Area rules
# =============================================================================


@pytest.mark.parametrize("area", [0.0, -1.0])
def test_non_positive_suite_area_is_an_error(area: float) -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite(suite_area_sf=area)], []
    )

    assert LeaseIssueCode.SUITE_AREA_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("area", [0.0, -1.0])
def test_non_positive_leased_area_is_an_error(area: float) -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite()], [lease(leased_area_sf=area)]
    )

    assert LeaseIssueCode.LEASE_AREA_OUT_OF_DOMAIN in codes(result)


def test_leased_area_must_equal_suite_area_in_d1() -> None:
    """D0 Section 4.4.1: one suite is one leasable unit; a subdivided suite is
    modeled as two Suite rows, never as a partial lease."""

    result = validate_lease_level_inputs(
        property_inputs(), [suite(suite_area_sf=10_000.0)], [lease(leased_area_sf=5_000.0)]
    )

    assert LeaseIssueCode.LEASE_AREA_MISMATCH in codes(result)


def test_suite_areas_totalling_exactly_the_rentable_area_reconcile() -> None:
    result = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=10_000.0),
        [
            suite(suite_id="S1", suite_area_sf=6_000.0),
            suite(suite_id="S2", suite_area_sf=4_000.0),
        ],
        [],
    )

    assert result.issues == ()


def test_an_explicit_vacant_suite_completes_the_reconciliation() -> None:
    """The approved way to represent vacant space: a Suite with area and no
    lease. 40,000 leased + 35,000 leased + 25,000 vacant = 100,000 rentable."""

    result = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=100_000.0),
        [
            suite(suite_id="A", suite_area_sf=40_000.0),
            suite(suite_id="B", suite_area_sf=35_000.0),
            suite(suite_id="C", suite_area_sf=25_000.0),
        ],
        [
            lease(lease_id="L1", suite_id="A", leased_area_sf=40_000.0),
            lease(
                lease_id="L2",
                suite_id="B",
                leased_area_sf=35_000.0,
                lease_expiration_date=date(2029, 12, 31),
            ),
        ],
    )

    assert result.is_valid
    assert result.issues == ()


def test_unexplained_rentable_area_shortfall_is_an_error() -> None:
    """The same 100,000 SF property with the remaining 25,000 SF simply absent
    from the rent roll. That is an incomplete rent roll, not a description of
    common area, and it must not be a successful financial state."""

    result = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=100_000.0),
        [
            suite(suite_id="A", suite_area_sf=40_000.0),
            suite(suite_id="B", suite_area_sf=35_000.0),
        ],
        [],
    )

    assert codes(result) == [LeaseIssueCode.RENTABLE_AREA_NOT_RECONCILED]
    assert result.issues[0].severity is LeaseIssueSeverity.ERROR
    assert not result.is_valid
    assert "25000.0" in result.issues[0].message


def test_suite_areas_exceeding_the_rentable_area_is_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=10_000.0),
        [
            suite(suite_id="S1", suite_area_sf=7_000.0),
            suite(suite_id="S2", suite_area_sf=5_000.0),
        ],
        [],
    )

    assert codes(result) == [LeaseIssueCode.RENTABLE_AREA_NOT_RECONCILED]
    assert result.issues[0].severity is LeaseIssueSeverity.ERROR
    assert "exceed" in result.issues[0].message


def test_no_common_area_inference_behaviour_remains() -> None:
    """The rejected D0 convention -- treating a residual as common area under
    an ``AREA_SHORTFALL_TREATED_AS_COMMON_AREA`` warning -- must be gone, not
    merely unused."""

    assert not hasattr(LeaseIssueCode, "AREA_SHORTFALL_TREATED_AS_COMMON_AREA")
    assert not hasattr(LeaseIssueCode, "LEASED_AREA_EXCEEDS_PROPERTY_AREA")
    assert "AREA_SHORTFALL" not in {member.value for member in LeaseIssueCode}


def test_reconciliation_tolerates_only_floating_point_summation_drift() -> None:
    """Areas that reconcile on paper must reconcile in floats: summing many
    suite areas accumulates ordinary IEEE-754 last-bit drift. A genuine
    discrepancy of even a square foot must still fail."""

    thirds = [
        suite(suite_id=f"S{i}", suite_area_sf=10_000.0 / 3.0) for i in range(3)
    ]
    drifting = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=10_000.0), thirds, []
    )
    assert drifting.is_valid, codes(drifting)

    one_sf_short = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=10_000.0),
        [suite(suite_id="S1", suite_area_sf=9_999.0)],
        [],
    )
    assert LeaseIssueCode.RENTABLE_AREA_NOT_RECONCILED in codes(one_sf_short)


def test_the_severity_architecture_still_partitions_warnings() -> None:
    """D1.0 has no genuine WARNING condition left, and none is fabricated to
    exercise the enum. The partition machinery is tested directly instead, so
    the architecture is proven without inventing domain behaviour."""

    from anchor.leasing.validation import LeaseValidationIssue, LeaseValidationResult

    warning = LeaseValidationIssue(
        code=LeaseIssueCode.LEASE_AREA_MISMATCH,
        path="suites[0]",
        message="illustrative",
        severity=LeaseIssueSeverity.WARNING,
    )
    error = LeaseValidationIssue(
        code=LeaseIssueCode.LEASE_AREA_MISMATCH, path="suites[1]", message="illustrative"
    )

    assert LeaseValidationResult(issues=(warning,)).is_valid
    assert LeaseValidationResult(issues=(warning,)).warnings == (warning,)
    assert not LeaseValidationResult(issues=(warning, error)).is_valid


# =============================================================================
# Rent rules
# =============================================================================


def test_negative_base_rent_is_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite()], [lease(base_rent_psf=-1.0)]
    )

    assert LeaseIssueCode.BASE_RENT_OUT_OF_DOMAIN in codes(result)


def test_zero_base_rent_is_permitted() -> None:
    """D0 Section 4.4 domain is ``>= 0``. A genuinely rent-free lease is
    representable; only a negative rent is rejected."""

    result = validate_lease_level_inputs(
        property_inputs(), [suite()], [lease(base_rent_psf=0.0)]
    )

    assert result.is_valid


@pytest.mark.parametrize("escalation", [-1.0, -1.5, -2.0])
def test_escalation_at_or_below_minus_one_is_an_error(escalation: float) -> None:
    """Anchor's frozen compounding-rate convention: a hard floor at -1
    exclusive. At -1 the series collapses to zero; below it the rent
    alternates sign every year."""

    result = validate_lease_level_inputs(
        property_inputs(), [suite()], [lease(escalation_pct=escalation)]
    )

    assert LeaseIssueCode.ESCALATION_OUT_OF_DOMAIN in codes(result)


@pytest.mark.parametrize("escalation", [-0.999, -0.30, 0.0, 0.03, 1.0])
def test_escalation_above_minus_one_is_permitted_with_no_upper_bound(
    escalation: float,
) -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite()], [lease(escalation_pct=escalation)]
    )

    assert result.is_valid


def test_basis_none_with_zero_escalation_is_valid() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(escalation_basis=EscalationBasis.NONE, escalation_pct=0.0)],
    )

    assert result.is_valid


@pytest.mark.parametrize("escalation", [0.03, -0.02, 1.0])
def test_basis_none_with_a_non_zero_escalation_is_an_error(escalation: float) -> None:
    """"No escalation basis" and "a 3% escalation" are contradictory
    instructions. Ignoring the percentage would silently pick one reading;
    Anchor makes the analyst state which they meant."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(escalation_basis=EscalationBasis.NONE, escalation_pct=escalation)],
    )

    assert codes(result) == [
        LeaseIssueCode.ESCALATION_BASIS_REQUIRES_ZERO_ESCALATION
    ]
    assert result.issues[0].path == "leases[0].escalation_pct"
    assert result.issues[0].severity is LeaseIssueSeverity.ERROR


def test_lease_anniversary_with_zero_escalation_stays_valid() -> None:
    """Unambiguous: a flat lease whose basis is stated anyway. Only the
    NONE-plus-non-zero pairing is contradictory."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(
                escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
                escalation_pct=0.0,
            )
        ],
    )

    assert result.is_valid


def test_lease_anniversary_with_a_valid_escalation_is_accepted() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(
                escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
                escalation_pct=0.03,
            )
        ],
    )

    assert result.is_valid


def test_an_out_of_domain_escalation_reports_the_domain_error_not_the_coherence_one() -> None:
    """One field, one primary complaint: a value below -1 is malformed before
    it is incoherent."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [lease(escalation_basis=EscalationBasis.NONE, escalation_pct=-2.0)],
    )

    assert codes(result) == [LeaseIssueCode.ESCALATION_OUT_OF_DOMAIN]


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf")]
)
@pytest.mark.parametrize("field_name", ["base_rent_psf", "escalation_pct", "leased_area_sf"])
def test_non_finite_lease_numbers_are_rejected(value: float, field_name: str) -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite()], [lease(**{field_name: value})]
    )

    assert LeaseIssueCode.NON_FINITE_VALUE in codes(result)


# =============================================================================
# Identity rules
# =============================================================================


@pytest.mark.parametrize("suite_id", ["", "   "])
def test_empty_suite_id_is_an_error(suite_id: str) -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite(suite_id=suite_id)], []
    )

    assert LeaseIssueCode.EMPTY_SUITE_ID in codes(result)


@pytest.mark.parametrize("lease_id", ["", "   "])
def test_empty_lease_id_is_an_error(lease_id: str) -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite()], [lease(lease_id=lease_id)]
    )

    assert LeaseIssueCode.EMPTY_LEASE_ID in codes(result)


def test_duplicate_suite_ids_are_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [
            suite(suite_id="S1", suite_area_sf=5_000.0),
            suite(suite_id="S1", suite_area_sf=5_000.0),
        ],
        [],
    )

    assert LeaseIssueCode.DUPLICATE_SUITE_ID in codes(result)


def test_duplicate_lease_ids_are_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(lease_id="L1", lease_expiration_date=date(2027, 12, 31)),
            lease(lease_id="L1", rent_commencement_date=date(2028, 1, 1)),
        ],
    )

    assert LeaseIssueCode.DUPLICATE_LEASE_ID in codes(result)


def test_a_lease_referencing_an_unknown_suite_is_an_error() -> None:
    result = validate_lease_level_inputs(
        property_inputs(), [suite(suite_id="S1")], [lease(suite_id="S9")]
    )

    assert LeaseIssueCode.UNKNOWN_SUITE_REFERENCE in codes(result)


# =============================================================================
# Same-suite occupancy overlap
# =============================================================================


def test_overlapping_leases_in_one_suite_are_an_error() -> None:
    """Without this, two leases covering one month in one suite would both
    collect that month's rent in D1.2 -- double-counted revenue and
    physically impossible occupancy."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(lease_id="L1", lease_expiration_date=date(2028, 12, 31)),
            lease(
                lease_id="L2",
                rent_commencement_date=date(2028, 1, 1),
                lease_expiration_date=date(2030, 12, 31),
            ),
        ],
    )

    assert LeaseIssueCode.OVERLAPPING_LEASES_IN_SUITE in codes(result)


def test_back_to_back_leases_in_one_suite_are_valid() -> None:
    """Expiration 2028-03-31 and commencement 2028-04-01 are adjacent months,
    not overlapping ones."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(lease_id="L1", lease_expiration_date=date(2028, 3, 31)),
            lease(
                lease_id="L2",
                rent_commencement_date=date(2028, 4, 1),
                lease_expiration_date=date(2033, 3, 31),
            ),
        ],
    )

    assert result.is_valid


def test_two_leases_sharing_a_single_month_in_one_suite_overlap() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(lease_id="L1", lease_expiration_date=date(2028, 3, 31)),
            lease(
                lease_id="L2",
                rent_commencement_date=date(2028, 3, 1),
                lease_expiration_date=date(2033, 2, 28),
            ),
        ],
    )

    assert LeaseIssueCode.OVERLAPPING_LEASES_IN_SUITE in codes(result)


def test_leases_in_different_suites_may_overlap_freely() -> None:
    result = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=10_000.0),
        [
            suite(suite_id="S1", suite_area_sf=6_000.0),
            suite(suite_id="S2", suite_area_sf=4_000.0),
        ],
        [
            lease(lease_id="L1", suite_id="S1", leased_area_sf=6_000.0),
            lease(lease_id="L2", suite_id="S2", leased_area_sf=4_000.0),
        ],
    )

    assert result.is_valid


def test_overlap_uses_rent_dates_not_the_informational_possession_date() -> None:
    """A successor's possession may legitimately begin while the outgoing
    tenant is still paying rent; only the rent-paying periods must not
    overlap."""

    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(lease_id="L1", lease_expiration_date=date(2028, 3, 31)),
            lease(
                lease_id="L2",
                lease_start_date=date(2028, 2, 1),
                rent_commencement_date=date(2028, 4, 1),
                lease_expiration_date=date(2033, 3, 31),
            ),
        ],
    )

    assert result.is_valid


# =============================================================================
# Vacant suites
# =============================================================================


def test_a_suite_with_no_lease_is_valid() -> None:
    """D0 Section 4.3/15.1: the absence of a lease is how contractual vacancy
    is represented. No synthetic vacant-lease row, no vacancy percentage."""

    result = validate_lease_level_inputs(
        property_inputs(rentable_area_sf=10_000.0),
        [
            suite(suite_id="S1", suite_area_sf=7_000.0),
            suite(suite_id="S2", suite_area_sf=3_000.0),
        ],
        [lease(lease_id="L1", suite_id="S1", leased_area_sf=7_000.0)],
    )

    assert result.is_valid


def test_a_property_with_no_leases_at_all_is_valid() -> None:
    result = validate_lease_level_inputs(property_inputs(), [suite()], [])

    assert result.is_valid


# =============================================================================
# Determinism
# =============================================================================


def _many_issue_input() -> tuple[LeaseLevelPropertyInputs, list[Suite], list[Lease]]:
    return (
        property_inputs(analysis_start_date=date(2026, 1, 15), rentable_area_sf=1_000.0),
        [
            suite(suite_id="S1", suite_area_sf=600.0),
            suite(suite_id="S1", suite_area_sf=400.0),
            suite(suite_id="", suite_area_sf=-5.0),
        ],
        [
            lease(
                lease_id="L1",
                suite_id="S1",
                leased_area_sf=999.0,
                rent_commencement_date=date(2026, 1, 15),
                lease_expiration_date=date(2028, 6, 15),
                base_rent_psf=-2.0,
                escalation_pct=-3.0,
            ),
            lease(
                lease_id="L1",
                suite_id="S404",
                leased_area_sf=600.0,
                rent_commencement_date=date(2026, 1, 1),
                lease_expiration_date=date(2029, 12, 31),
            ),
        ],
    )


def test_issue_ordering_is_deterministic_across_repeated_runs() -> None:
    inputs, suites, leases = _many_issue_input()

    first = validate_lease_level_inputs(inputs, suites, leases)
    for _ in range(100):
        assert validate_lease_level_inputs(inputs, suites, leases).issues == first.issues


def test_issues_are_ordered_property_then_suites_then_leases() -> None:
    inputs, suites, leases = _many_issue_input()

    paths = [issue.path for issue in validate_lease_level_inputs(inputs, suites, leases).issues]

    property_positions = [i for i, p in enumerate(paths) if p.startswith("property.")]
    suite_positions = [i for i, p in enumerate(paths) if p.startswith("suites[")]
    lease_positions = [i for i, p in enumerate(paths) if p.startswith("leases[")]

    assert property_positions, paths
    assert suite_positions, paths
    assert lease_positions, paths
    # The first property issue precedes every suite issue, which precedes
    # every lease issue. (A property-level cross-record rule -- area
    # reconciliation -- is emitted last by design, so only the leading
    # property issue is ordered against the rest.)
    assert property_positions[0] < suite_positions[0] < lease_positions[0]


def test_records_are_reported_in_declared_order() -> None:
    result = validate_lease_level_inputs(
        property_inputs(),
        [suite()],
        [
            lease(lease_id="L1", leased_area_sf=-1.0, lease_expiration_date=date(2027, 12, 31)),
            lease(
                lease_id="L2",
                leased_area_sf=-2.0,
                rent_commencement_date=date(2028, 1, 1),
            ),
        ],
    )

    paths = [issue.path for issue in result.issues]
    assert paths.index("leases[0].leased_area_sf") < paths.index("leases[1].leased_area_sf")


def test_result_partitions_preserve_the_canonical_issue_order() -> None:
    inputs, suites, leases = _many_issue_input()
    result = validate_lease_level_inputs(inputs, suites, leases)

    assert list(result.errors) == [
        issue for issue in result.issues if issue.severity is LeaseIssueSeverity.ERROR
    ]
    assert list(result.warnings) == [
        issue for issue in result.issues if issue.severity is LeaseIssueSeverity.WARNING
    ]


def test_repeated_validation_returns_equal_results() -> None:
    inputs, suites, leases = _many_issue_input()

    assert validate_lease_level_inputs(inputs, suites, leases) == (
        validate_lease_level_inputs(inputs, suites, leases)
    )


# =============================================================================
# Raising behavior
# =============================================================================


def test_require_valid_raises_and_carries_the_whole_result() -> None:
    inputs, suites, leases = _many_issue_input()

    with pytest.raises(LeaseValidationError) as raised:
        require_valid_lease_level_inputs(inputs, suites, leases)

    assert raised.value.result.errors
    assert not raised.value.result.is_valid
    # The message enumerates every error, in canonical order.
    assert str(raised.value).count("\n") == len(raised.value.result.errors) - 1


def test_lease_validation_error_refuses_to_wrap_a_clean_result() -> None:
    from anchor.leasing.validation import LeaseValidationResult

    with pytest.raises(ValueError):
        raise LeaseValidationError(LeaseValidationResult(issues=()))


# =============================================================================
# No silent defaults
# =============================================================================


def test_validation_never_mutates_or_coerces_its_inputs() -> None:
    inputs = property_inputs(analysis_start_date=date(2026, 1, 15))
    original_suite = suite()
    original_lease = lease(rent_commencement_date=date(2026, 1, 15))

    validate_lease_level_inputs(inputs, [original_suite], [original_lease])

    assert inputs.analysis_start_date == date(2026, 1, 15)
    assert original_lease.rent_commencement_date == date(2026, 1, 15)
    assert original_suite == suite()
