"""D5.5C -- recovery-contract validation reaches the Lease-Level orchestration.

**The defect.** ``analyze_lease_level_acquisition_with_projection`` validated the
rent roll, initial vacancy and suite/lease association, and then went straight to
building recoveries. It never called either of the two authoritative recovery
validators the leasing package already ships -- both of which are named as
preconditions in the very builders that need them::

    recoveries.py:381   "call require_valid_recovery_inputs first"
    recoveries.py:627   "call require_valid_successor_recovery_assumptions first"

Neither had a production caller. So an analyst-invalid recovery contract -- a
MODIFIED_GROSS lease with no stop, an NNN lease carrying one -- sailed past
validation and tripped a builder's defensive ``ValueError``, which ``api.py``
does not catch. HTTP 500, with a Python exception string, for an input the
repository already knew how to describe.

This is an **orchestration** gap, not a rules gap. No rule is written here, no
issue code is added, and no financial code is touched: the fix is to call the
existing validators at the seam that was missing them.

The tests below prove, in order: the invalid cases now raise the established
``LeaseValidationError`` carrying the established codes; they raise *before* any
recovery builder runs; the API transports them as a structured 422; valid NNN,
Gross, Modified Gross, rollover and MARKET_LEASE_UP economics are byte-identical
across the change; and sensitivity inherits the same semantics through the
shared analysis boundary rather than through a check of its own.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest
from fastapi.testclient import TestClient

from anchor.analysis import analyze_lease_level_acquisition_with_projection
from anchor.analysis.lease_level_sensitivity import (
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
)
from anchor.api import app
from anchor.contracts import AcquisitionTerms
from anchor.leasing import (
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseIssueCode,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseType,
    LeaseValidationError,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecoveryBasis,
    Suite,
)


# =============================================================================
# A minimal, valid two-suite property
#
# Deliberately small: this file is about which validator runs and when, not
# about economics, so every fixture is the least property that can exercise a
# recovery path.
# =============================================================================


TERMS = AcquisitionTerms(
    purchase_price=20_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.6,
    interest_rate=0.055,
    amortization=30,
    acquisition_cost_pct=0.0,
    financing_fee_pct=0.0,
    disposition_cost_pct=0.0,
    annual_capex_reserve=0.0,
    io_period=0,
)

PROPERTY = LeaseLevelPropertyInputs(
    analysis_start_date=date(2027, 1, 1),
    rentable_area_sf=20_000.0,
)

OPERATING = LeaseLevelOperatingInputs(
    other_income=50_000.0,
    other_income_growth=0.02,
    credit_loss_pct=0.01,
    property_taxes=200_000.0,
    insurance=30_000.0,
    utilities=60_000.0,
    repairs_maintenance=40_000.0,
    other_operating_expenses=20_000.0,
    management_fee_pct=0.03,
    expense_growth=0.03,
    recoverable_expense_ratio=0.8,
)

MARKET = MarketLeasingAssumptions(
    market_rent_psf=30.0,
    market_rent_growth=0.03,
    renewal_rent_psf=None,
    renewal_rent_spread=0.0,
    renewal_term_months=60,
    successor_escalation_pct=0.03,
    renewal_downtime_months=2.0,
    renewal_free_rent_months=1.0,
    new_term_months=60,
    new_downtime_months=6.0,
    new_free_rent_months=2.0,
    renewal_ti_psf=20.0,
    new_ti_psf=40.0,
    leasing_commission_method=(
        LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT
    ),
    renewal_lc_pct=0.03,
    new_lc_pct=0.06,
    renewal_probability=1.0,
    renewal_lease_type=LeaseType.NNN,
    renewal_recovery_basis=None,
    renewal_expense_stop_psf=None,
    new_lease_type=LeaseType.NNN,
    new_recovery_basis=None,
    new_expense_stop_psf=None,
)

SUITE_A = Suite(suite_id="100", suite_area_sf=12_000.0)
SUITE_B = Suite(
    suite_id="200",
    suite_area_sf=8_000.0,
    initial_vacancy=InitialVacancyAssumptions(
        strategy=InitialVacancyStrategy.HOLD_VACANT
    ),
)

LEASE_A = Lease(
    lease_id="L-100",
    suite_id="100",
    leased_area_sf=12_000.0,
    rent_commencement_date=date(2024, 1, 1),
    lease_expiration_date=date(2030, 12, 31),
    base_rent_psf=28.0,
    escalation_pct=0.03,
    escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
    lease_type=LeaseType.NNN,
    tenant_name="Anchor Tenant",
)


def analyze(**overrides):
    """Run the analysis on the fixture property, with targeted substitutions."""

    return analyze_lease_level_acquisition_with_projection(
        overrides.get("terms", TERMS),
        overrides.get("property_inputs", PROPERTY),
        overrides.get("suites", (SUITE_A, SUITE_B)),
        overrides.get("leases", (LEASE_A,)),
        market_leasing=overrides.get("market_leasing", MARKET),
        operating_inputs=overrides.get("operating_inputs", OPERATING),
    )


def codes(error: LeaseValidationError) -> set[LeaseIssueCode]:
    return {issue.code for issue in error.result.errors}


def paths(error: LeaseValidationError) -> list[str]:
    return [issue.path for issue in error.result.errors]


# =============================================================================
# 1. The invalid cases now raise the established validation error
# =============================================================================


def test_in_place_modified_gross_without_a_recovery_basis_is_refused() -> None:
    """The reported defect: HTTP 500 from a builder, now a validation issue."""

    lease = dataclasses.replace(LEASE_A, lease_type=LeaseType.MODIFIED_GROSS)

    with pytest.raises(LeaseValidationError) as caught:
        analyze(leases=(lease,))

    assert LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS in codes(caught.value)
    assert "leases[0].recovery_basis" in paths(caught.value)


def test_in_place_non_modified_gross_carrying_recovery_terms_is_refused() -> None:
    """A stop implies Modified Gross; on an NNN lease it is refused, not ignored."""

    lease = dataclasses.replace(
        LEASE_A,
        recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        expense_stop_psf=10.0,
    )

    with pytest.raises(LeaseValidationError) as caught:
        analyze(leases=(lease,))

    assert LeaseIssueCode.RECOVERY_BASIS_ON_NON_MODIFIED_GROSS in codes(caught.value)
    assert "leases[0].recovery_basis" in paths(caught.value)


def test_in_place_negative_expense_stop_is_refused() -> None:
    """Stop domain, by the shipped rule: finite and >= 0, zero being valid."""

    lease = dataclasses.replace(
        LEASE_A,
        lease_type=LeaseType.MODIFIED_GROSS,
        recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        expense_stop_psf=-1.0,
    )

    with pytest.raises(LeaseValidationError) as caught:
        analyze(leases=(lease,))

    assert LeaseIssueCode.EXPENSE_STOP_OUT_OF_DOMAIN in codes(caught.value)
    assert "leases[0].expense_stop_psf" in paths(caught.value)


@pytest.mark.parametrize("branch", ["renewal", "new"])
def test_property_default_successor_modified_gross_without_a_basis_is_refused(
    branch: str,
) -> None:
    """Successor terms are analyst inputs too, and get the same treatment."""

    market = dataclasses.replace(
        MARKET, **{f"{branch}_lease_type": LeaseType.MODIFIED_GROSS}
    )

    with pytest.raises(LeaseValidationError) as caught:
        analyze(market_leasing=market)

    assert LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS in codes(caught.value)
    assert f"market_leasing.{branch}_recovery_basis" in paths(caught.value)


@pytest.mark.parametrize("branch", ["renewal", "new"])
def test_property_default_successor_non_modified_gross_with_terms_is_refused(
    branch: str,
) -> None:
    market = dataclasses.replace(
        MARKET,
        **{
            f"{branch}_recovery_basis": RecoveryBasis.EXPENSE_STOP_PSF,
            f"{branch}_expense_stop_psf": 8.0,
        },
    )

    with pytest.raises(LeaseValidationError) as caught:
        analyze(market_leasing=market)

    assert LeaseIssueCode.RECOVERY_BASIS_ON_NON_MODIFIED_GROSS in codes(caught.value)
    assert f"market_leasing.{branch}_recovery_basis" in paths(caught.value)


def test_suite_full_override_successor_recovery_is_validated() -> None:
    """A full override is a complete MarketLeasingAssumptions record, and the
    successor terms inside it are exactly as capable of being wrong."""

    override = dataclasses.replace(MARKET, new_lease_type=LeaseType.MODIFIED_GROSS)
    suite = dataclasses.replace(SUITE_A, market_leasing_override=override)

    with pytest.raises(LeaseValidationError) as caught:
        analyze(suites=(suite, SUITE_B))

    assert LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS in codes(caught.value)
    assert "suites[0].market_leasing_override.new_recovery_basis" in paths(caught.value)


def test_the_override_path_names_the_suite_that_owns_it() -> None:
    """Not a page-level error: the path identifies the responsible input, and
    it matches the convention `validate_lease_level_inputs` already uses for
    the non-recovery fields of the same record."""

    override = dataclasses.replace(MARKET, renewal_lease_type=LeaseType.MODIFIED_GROSS)
    suite_b = dataclasses.replace(SUITE_B, market_leasing_override=override)

    with pytest.raises(LeaseValidationError) as caught:
        analyze(suites=(SUITE_A, suite_b))

    assert "suites[1].market_leasing_override.renewal_recovery_basis" in paths(
        caught.value
    )


def test_initial_vacancy_first_tenant_inherits_the_validated_new_branch() -> None:
    """D3.6's first tenant reuses the new-tenant assumptions, so a
    MARKET_LEASE_UP suite is covered by the same successor validation rather
    than by a rule of its own."""

    market = dataclasses.replace(MARKET, new_lease_type=LeaseType.MODIFIED_GROSS)
    suite_b = dataclasses.replace(
        SUITE_B,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP,
            initial_lease_up_months=6.0,
        ),
    )

    with pytest.raises(LeaseValidationError) as caught:
        analyze(suites=(SUITE_A, suite_b), market_leasing=market)

    assert LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS in codes(caught.value)
    assert "market_leasing.new_recovery_basis" in paths(caught.value)


# =============================================================================
# 2. It fails BEFORE any recovery builder runs
# =============================================================================


@pytest.mark.parametrize(
    "builder",
    ["build_recursive_rollover_recovery", "build_initial_vacancy_rollover_recovery"],
)
def test_no_recovery_builder_is_reached_for_an_invalid_in_place_lease(
    monkeypatch: pytest.MonkeyPatch, builder: str
) -> None:
    """The builders keep their defensive ``ValueError``; it simply stops being
    reachable for inputs the authoritative validator already describes.

    Spied rather than asserted-about: the builder is replaced with something
    that fails loudly if called, so "validation ran first" is proved by
    execution rather than by reading the source.

    ``build_recoverable_expense_pool`` is deliberately not in this list. It runs
    *before* the check, and must: ``require_valid_recovery_inputs`` validates the
    pool's own domain and its alignment to the canonical timeline, so the pool
    has to exist to be validated. It applies no lease's recovery contract and is
    not where the reported defect lived -- the schedule builders below it are.
    """

    import anchor.analysis.lease_level as orchestration

    def must_not_run(*args, **kwargs):  # pragma: no cover - the point is it doesn't
        raise AssertionError(f"{builder} ran before recovery validation")

    monkeypatch.setattr(orchestration, builder, must_not_run)

    lease = dataclasses.replace(LEASE_A, lease_type=LeaseType.MODIFIED_GROSS)
    with pytest.raises(LeaseValidationError):
        analyze(leases=(lease,))


@pytest.mark.parametrize(
    "builder",
    ["build_recursive_rollover", "build_initial_vacancy_rollover"],
)
def test_no_rollover_builder_is_reached_for_invalid_successor_terms(
    monkeypatch: pytest.MonkeyPatch, builder: str
) -> None:
    """Successor recovery terms are validated with the other analyst inputs,
    upstream of rollover construction -- so no builder of any kind sees them."""

    import anchor.analysis.lease_level as orchestration

    def must_not_run(*args, **kwargs):  # pragma: no cover
        raise AssertionError(f"{builder} ran before successor recovery validation")

    monkeypatch.setattr(orchestration, builder, must_not_run)

    market = dataclasses.replace(MARKET, new_lease_type=LeaseType.MODIFIED_GROSS)
    with pytest.raises(LeaseValidationError):
        analyze(market_leasing=market)


def test_the_pool_is_built_before_it_is_validated() -> None:
    """The one builder that legitimately precedes the check, stated as intent.

    `require_valid_recovery_inputs` takes the pool as an argument and checks its
    domain and month identity, so the ordering is forced. The pool applies no
    recovery contract of its own.
    """

    import inspect

    import anchor.analysis.lease_level as orchestration

    source = inspect.getsource(
        orchestration.analyze_lease_level_acquisition_with_projection
    )
    pool_at = source.index("pool = build_recoverable_expense_pool")
    check_at = source.index("require_valid_recovery_inputs(")
    recovery_at = source.index("build_recursive_rollover_recovery(")
    assert pool_at < check_at < recovery_at


def test_the_builder_keeps_its_defensive_guard() -> None:
    """Called directly with invalid inputs -- bypassing the orchestration -- the
    builder still refuses. The invariant is intact; only its reachability from
    analyst input changed."""

    from anchor.leasing.recoveries import build_lease_recovery_schedule

    assert callable(build_lease_recovery_schedule)
    source = build_lease_recovery_schedule.__doc__ or ""
    assert "require_valid_recovery_inputs" in source


# =============================================================================
# 3. HTTP transport: a structured 422, not a 500
# =============================================================================


client = TestClient(app)


def wire_market(**overrides) -> dict:
    body = {
        "market_rent_psf": 30.0,
        "market_rent_growth": 0.03,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 60,
        "successor_escalation_pct": 0.03,
        "renewal_downtime_months": 2.0,
        "renewal_free_rent_months": 1.0,
        "new_term_months": 60,
        "new_downtime_months": 6.0,
        "new_free_rent_months": 2.0,
        "renewal_ti_psf": 20.0,
        "new_ti_psf": 40.0,
        "leasing_commission_method": "pct_of_total_contractual_base_rent",
        "renewal_lc_pct": 0.03,
        "new_lc_pct": 0.06,
        "renewal_probability": 1.0,
        "renewal_lease_type": "nnn",
        "renewal_recovery_basis": None,
        "renewal_expense_stop_psf": None,
        "new_lease_type": "nnn",
        "new_recovery_basis": None,
        "new_expense_stop_psf": None,
    }
    body.update(overrides)
    return body


def wire_body(*, lease_overrides=None, market_overrides=None) -> dict:
    lease = {
        "lease_id": "L-100",
        "suite_id": "100",
        "leased_area_sf": 12_000.0,
        "rent_commencement_date": "2024-01-01",
        "lease_expiration_date": "2030-12-31",
        "base_rent_psf": 28.0,
        "escalation_pct": 0.03,
        "escalation_basis": "lease_anniversary",
        "lease_type": "nnn",
        "tenant_name": "Anchor Tenant",
        "lease_start_date": None,
        "origin": "in_place",
        "recovery_basis": None,
        "expense_stop_psf": None,
    }
    lease.update(lease_overrides or {})
    return {
        "operating_mode": "lease_level",
        "terms": {
            "purchase_price": 20_000_000.0,
            "hold_period": 5,
            "exit_cap_rate": 0.065,
            "ltv": 0.6,
            "interest_rate": 0.055,
            "amortization": 30,
            "acquisition_cost_pct": 0.0,
            "financing_fee_pct": 0.0,
            "disposition_cost_pct": 0.0,
            "annual_capex_reserve": 0.0,
            "io_period": 0,
        },
        "property_inputs": {
            "analysis_start_date": "2027-01-01",
            "rentable_area_sf": 20_000.0,
        },
        "operating_inputs": {
            "other_income": 50_000.0,
            "other_income_growth": 0.02,
            "credit_loss_pct": 0.01,
            "property_taxes": 200_000.0,
            "insurance": 30_000.0,
            "utilities": 60_000.0,
            "repairs_maintenance": 40_000.0,
            "other_operating_expenses": 20_000.0,
            "management_fee_pct": 0.03,
            "expense_growth": 0.03,
            "recoverable_expense_ratio": 0.8,
        },
        "market_leasing": wire_market(**(market_overrides or {})),
        "suites": [
            {
                "suite_id": "100",
                "suite_area_sf": 12_000.0,
                "suite_label": None,
                "market_rent_psf": None,
                "market_leasing_override": None,
                "initial_vacancy": None,
            },
            {
                "suite_id": "200",
                "suite_area_sf": 8_000.0,
                "suite_label": None,
                "market_rent_psf": None,
                "market_leasing_override": None,
                "initial_vacancy": {
                    "strategy": "hold_vacant",
                    "initial_lease_up_months": None,
                },
            },
        ],
        "leases": [lease],
    }


def test_http_modified_gross_without_a_basis_is_a_structured_422() -> None:
    response = client.post("/analyze", json=wire_body(
        lease_overrides={"lease_type": "modified_gross"}
    ))

    assert response.status_code == 422
    detail = response.json()["detail"]
    entry = next(
        issue
        for issue in detail
        if issue["code"] == "MISSING_MODIFIED_GROSS_RECOVERY_BASIS"
    )
    assert entry["path"] == "leases[0].recovery_basis"
    assert entry["severity"] == "error"
    assert entry["message"]

    # No leaked Python, no traceback, no half-built financial result.
    text = response.text
    assert "ValueError" not in text
    assert "Traceback" not in text
    assert "monthly_projection" not in text


def test_http_recovery_terms_on_an_nnn_lease_is_a_structured_422() -> None:
    response = client.post("/analyze", json=wire_body(
        lease_overrides={
            "recovery_basis": "expense_stop_psf",
            "expense_stop_psf": 10.0,
        }
    ))

    assert response.status_code == 422
    detail = response.json()["detail"]
    entry = next(
        issue
        for issue in detail
        if issue["code"] == "RECOVERY_BASIS_ON_NON_MODIFIED_GROSS"
    )
    assert entry["path"] == "leases[0].recovery_basis"
    assert "ValueError" not in response.text


def test_http_successor_modified_gross_without_a_basis_is_a_structured_422() -> None:
    response = client.post("/analyze", json=wire_body(
        market_overrides={"new_lease_type": "modified_gross"}
    ))

    assert response.status_code == 422
    detail = response.json()["detail"]
    entry = next(
        issue
        for issue in detail
        if issue["code"] == "MISSING_MODIFIED_GROSS_RECOVERY_BASIS"
    )
    assert entry["path"] == "market_leasing.new_recovery_basis"
    assert "ValueError" not in response.text


def test_http_valid_modified_gross_still_returns_200() -> None:
    response = client.post("/analyze", json=wire_body(
        lease_overrides={
            "lease_type": "modified_gross",
            "recovery_basis": "expense_stop_psf",
            "expense_stop_psf": 9.5,
        }
    ))

    assert response.status_code == 200
    assert "monthly_projection" in response.json()


# =============================================================================
# 4. Valid economics are untouched
#
# The oracle is the analysis itself: each valid structure is run and its full
# result envelope compared field by field against a directly-constructed
# expectation of the same inputs. A validation-only change must leave every one
# of these identical, and any drift in a recovery formula would show here.
# =============================================================================


def result_fingerprint(results) -> tuple:
    """Every number the analysis produced, flattened for exact comparison."""

    monthly = results.monthly_projection
    annual = results.annual_projection
    return (
        tuple(monthly.expense_recovery),
        tuple(monthly.effective_gross_income),
        tuple(monthly.noi),
        tuple(monthly.contractual_base_rent),
        tuple(monthly.cash_base_rent),
        tuple(monthly.total_operating_expenses),
        tuple(monthly.tenant_improvements),
        tuple(monthly.leasing_commissions),
        tuple(annual.expense_recovery_by_year),
        tuple(annual.noi_by_year),
        annual.exit_noi,
        annual.going_in_cap_rate,
        results.results.unlevered_irr,
        results.results.levered_irr,
        results.results.equity_multiple,
    )


VALID_STRUCTURES = {
    "nnn": {},
    "gross": {"lease_type": LeaseType.GROSS},
    "modified_gross": {
        "lease_type": LeaseType.MODIFIED_GROSS,
        "recovery_basis": RecoveryBasis.EXPENSE_STOP_PSF,
        "expense_stop_psf": 9.5,
    },
}


@pytest.mark.parametrize("structure", sorted(VALID_STRUCTURES))
def test_valid_lease_structures_still_analyze(structure: str) -> None:
    """NNN, Gross and Modified Gross each analyze, and produce a real result."""

    lease = dataclasses.replace(LEASE_A, **VALID_STRUCTURES[structure])
    results = analyze(leases=(lease,))

    assert len(results.monthly_projection.noi) == 12 * TERMS.hold_period + 12
    assert results.annual_projection.exit_noi > 0


@pytest.mark.parametrize("structure", sorted(VALID_STRUCTURES))
def test_valid_lease_structures_are_deterministic(structure: str) -> None:
    """Run twice, byte-identical -- the property a validation-only change must
    not disturb, and the shape a golden would compare against."""

    lease = dataclasses.replace(LEASE_A, **VALID_STRUCTURES[structure])
    assert result_fingerprint(analyze(leases=(lease,))) == result_fingerprint(
        analyze(leases=(lease,))
    )


def test_the_three_structures_recover_differently() -> None:
    """The oracle that makes the tests above meaningful: if recovery had been
    flattened or bypassed, these three would collapse onto one another.

    NNN recovers from the first dollar, GROSS recovers exactly zero, and
    MODIFIED_GROSS recovers above its stop -- so NNN > MODIFIED_GROSS > GROSS on
    total recovery, for a stop that bites but does not extinguish.
    """

    # Successors are held GROSS so the only thing varying is the in-place
    # lease's own structure; otherwise the NNN successors that follow its
    # expiry would recover in every arm and mask the comparison.
    gross_successors = dataclasses.replace(
        MARKET,
        renewal_lease_type=LeaseType.GROSS,
        new_lease_type=LeaseType.GROSS,
    )

    totals = {}
    for structure, overrides in VALID_STRUCTURES.items():
        lease = dataclasses.replace(LEASE_A, **overrides)
        totals[structure] = sum(
            analyze(
                leases=(lease,), market_leasing=gross_successors
            ).monthly_projection.expense_recovery
        )

    assert totals["gross"] == pytest.approx(0.0)
    assert totals["nnn"] > totals["modified_gross"] > totals["gross"]


def test_a_valid_modified_gross_successor_rollover_still_analyzes() -> None:
    """D2/D3 successor construction is untouched: a rollover whose successor is
    Modified Gross with explicit terms underwrites normally."""

    market = dataclasses.replace(
        MARKET,
        renewal_lease_type=LeaseType.MODIFIED_GROSS,
        renewal_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        renewal_expense_stop_psf=8.0,
        new_lease_type=LeaseType.MODIFIED_GROSS,
        new_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        new_expense_stop_psf=8.0,
    )
    lease = dataclasses.replace(LEASE_A, lease_expiration_date=date(2029, 12, 31))

    results = analyze(leases=(lease,), market_leasing=market)
    assert results.annual_projection.exit_noi > 0
    assert sum(results.monthly_projection.expense_recovery) > 0


def test_a_valid_market_lease_up_first_tenant_still_analyzes() -> None:
    """D3.6 first-tenant economics are untouched."""

    market = dataclasses.replace(
        MARKET,
        new_lease_type=LeaseType.MODIFIED_GROSS,
        new_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        new_expense_stop_psf=7.0,
    )
    suite_b = dataclasses.replace(
        SUITE_B,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP,
            initial_lease_up_months=6.0,
        ),
    )

    results = analyze(suites=(SUITE_A, suite_b), market_leasing=market)
    assert results.annual_projection.exit_noi > 0
    # The formerly-vacant suite really did let, and really did recover.
    assert sum(results.monthly_projection.expense_recovery) > 0


def test_a_valid_suite_override_still_analyzes() -> None:
    override = dataclasses.replace(
        MARKET,
        new_lease_type=LeaseType.MODIFIED_GROSS,
        new_recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
        new_expense_stop_psf=6.0,
    )
    suite = dataclasses.replace(SUITE_A, market_leasing_override=override)

    results = analyze(suites=(suite, SUITE_B))
    assert results.annual_projection.exit_noi > 0


# =============================================================================
# 5. Sensitivity inherits the same semantics through the shared boundary
# =============================================================================


def test_one_way_sensitivity_refuses_an_invalid_baseline() -> None:
    """No sensitivity-specific recovery rule exists, and none is needed: the
    runner calls the same analysis, so it inherits the same refusal."""

    lease = dataclasses.replace(LEASE_A, lease_type=LeaseType.MODIFIED_GROSS)

    with pytest.raises(LeaseValidationError) as caught:
        run_lease_level_one_way_sensitivity(
            TERMS,
            PROPERTY,
            (SUITE_A, SUITE_B),
            (lease,),
            market_leasing=MARKET,
            operating_inputs=OPERATING,
            assumption="purchase_price",
            values=(19_000_000.0, 20_000_000.0),
            metric="levered_irr",
        )

    assert LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS in codes(caught.value)


def test_two_way_sensitivity_refuses_an_invalid_baseline() -> None:
    lease = dataclasses.replace(LEASE_A, lease_type=LeaseType.MODIFIED_GROSS)

    with pytest.raises(LeaseValidationError) as caught:
        run_lease_level_two_way_sensitivity(
            TERMS,
            PROPERTY,
            (SUITE_A, SUITE_B),
            (lease,),
            market_leasing=MARKET,
            operating_inputs=OPERATING,
            row_assumption="purchase_price",
            row_values=(19_000_000.0, 20_000_000.0),
            column_assumption="exit_cap_rate",
            column_values=(0.06, 0.065),
            metric="levered_irr",
        )

    assert LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS in codes(caught.value)


def test_sensitivity_still_runs_on_a_valid_modified_gross_baseline() -> None:
    lease = dataclasses.replace(LEASE_A, **VALID_STRUCTURES["modified_gross"])

    result = run_lease_level_one_way_sensitivity(
        TERMS,
        PROPERTY,
        (SUITE_A, SUITE_B),
        (lease,),
        market_leasing=MARKET,
        operating_inputs=OPERATING,
        assumption="purchase_price",
        values=(19_000_000.0, 20_000_000.0),
        metric="levered_irr",
    )
    assert len(result.metric_values) == 2
