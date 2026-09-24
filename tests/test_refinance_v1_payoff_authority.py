"""Refinance & Capital Events V1 Stage 1 -- the authoritative legacy payoff (R-M).

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 10.2 and fixtures
F8 and F9b. The acquisition loan's balance after month ``m`` comes from one
engine-owned service that reuses the accepted debt functions, reconciles bit for
bit to ``AcquisitionResults`` on every call, and refuses -- never repairs -- a
mismatch. Expected balances come from an independent ``Fraction`` recurrence.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction

import pytest
from _refinance_v1_fixtures import (  # type: ignore[import-not-found]
    EVENT_MONTH,
    LEGACY_BALANCE_AT_60,
    LEGACY_MONTHLY,
    LEGACY_PAYOFF_AT_24,
    base_structure,
    base_unit,
    close,
    oracle_balance_after,
    run_unit,
)

from anchor.capital_structure.execution_contracts import CapitalStructureExecutionError, ExecutionIssueCode
from anchor.capital_structure.refinance_contracts import PayoffAuthority
from anchor.engine import acquisition_debt_balance as service
from anchor.engine.acquisition_debt_balance import (
    AcquisitionDebtBalanceReconciliationError,
    acquisition_loan_balance_after_month,
)

_CASES = [
    pytest.param({"interest_rate": 0.0, "amortization": 25, "io_period": 0}, id="zero-rate-amortizing"),
    pytest.param({"interest_rate": 0.06, "amortization": 25, "io_period": 0}, id="positive-rate-amortizing"),
    pytest.param({"interest_rate": 0.06, "amortization": 25, "io_period": 3}, id="inside-io"),
    pytest.param({"interest_rate": 0.06, "amortization": 25, "io_period": 2}, id="io-boundary"),
    pytest.param({"interest_rate": 0.045, "amortization": 30, "io_period": 1}, id="after-io"),
]


def _oracle(terms: dict[str, float], month: int) -> Fraction:
    return oracle_balance_after(
        Fraction(6_000_000),
        annual_rate=Fraction(str(terms["interest_rate"])),
        amortization_years=int(terms["amortization"]),
        io_years=int(terms["io_period"]),
        month=month,
    )


# =============================================================================
# F9b -- every debt branch against the exact recurrence
# =============================================================================


@pytest.mark.parametrize("overrides", _CASES)
@pytest.mark.parametrize("month", [12, 24, 36, 48])
def test_the_balance_matches_the_exact_recurrence(overrides: dict[str, float], month: int) -> None:
    terms, results = base_unit(**overrides)
    balance = acquisition_loan_balance_after_month(terms=terms, results=results, model_month=month)
    assert close(balance.balance_after_month, _oracle(overrides, month), rel=1e-9)
    assert balance.loan_amount == results.loan_amount
    assert balance.monthly_debt_service == results.monthly_debt_service


def test_the_zero_rate_base_case_is_exact() -> None:
    terms, results = base_unit()
    balance = acquisition_loan_balance_after_month(terms=terms, results=results, model_month=EVENT_MONTH)
    assert balance.balance_after_month == LEGACY_PAYOFF_AT_24
    assert balance.scheduled_payment_at_month == LEGACY_MONTHLY
    at_sale = acquisition_loan_balance_after_month(terms=terms, results=results, model_month=60)
    assert at_sale.balance_after_month == LEGACY_BALANCE_AT_60 == results.remaining_loan_balance


def test_inside_io_and_at_the_io_boundary_the_balance_is_the_principal() -> None:
    for io_period in (3, 2):
        terms, results = base_unit(interest_rate=0.06, amortization=25, io_period=io_period)
        balance = acquisition_loan_balance_after_month(terms=terms, results=results, model_month=24)
        assert balance.balance_after_month == 6_000_000.0
        assert close(balance.scheduled_payment_at_month, Fraction(6_000_000) * Fraction("0.06") / 12)


def test_the_payment_at_the_month_precedes_the_balance() -> None:
    """The balance is the one *after* month ``m``'s payment, never before it
    and never a month early: consecutive balances differ by exactly the
    principal repaid in month ``m``."""

    overrides = {"interest_rate": 0.06, "amortization": 25, "io_period": 0}
    terms, results = base_unit(**overrides)
    at_23 = acquisition_loan_balance_after_month(terms=terms, results=results, model_month=23).balance_after_month
    at_24 = acquisition_loan_balance_after_month(terms=terms, results=results, model_month=24)
    principal_24 = Fraction(at_24.scheduled_payment_at_month) - Fraction(at_23) * Fraction("0.06") / 12
    assert close(at_24.balance_after_month, Fraction(at_23) - principal_24, rel=1e-12)
    assert at_24.balance_after_month < at_23


def test_a_fully_amortized_loan_has_a_zero_balance() -> None:
    terms, results = base_unit(interest_rate=0.05, amortization=1, io_period=0)
    balance = acquisition_loan_balance_after_month(terms=terms, results=results, model_month=24)
    assert balance.balance_after_month == 0.0


# =============================================================================
# Reconciliation: refused, never repaired
# =============================================================================


@pytest.mark.parametrize(
    ("field", "figure"),
    [
        ("loan_amount", "loan amount"),
        ("monthly_debt_service", "monthly debt service"),
        ("annual_debt_service", "Year 1 debt service"),
        ("remaining_loan_balance", "sale-date remaining balance"),
    ],
)
def test_each_mismatch_is_refused_by_name(field: str, figure: str) -> None:
    terms, results = base_unit(interest_rate=0.06)
    value = getattr(results, field)
    tampered = (value[0] + 0.01, *value[1:]) if isinstance(value, tuple) else value + 0.01
    with pytest.raises(AcquisitionDebtBalanceReconciliationError) as raised:
        acquisition_loan_balance_after_month(
            terms=terms, results=dataclasses.replace(results, **{field: tampered}), model_month=24
        )
    assert raised.value.figure == figure


def test_terms_that_did_not_produce_the_results_are_refused() -> None:
    terms, results = base_unit(interest_rate=0.06)
    other_terms, _ = base_unit(interest_rate=0.07)
    with pytest.raises(AcquisitionDebtBalanceReconciliationError):
        acquisition_loan_balance_after_month(terms=other_terms, results=results, model_month=24)


def test_a_reconciliation_failure_refuses_the_refinance_with_its_typed_code() -> None:
    terms, results = base_unit()
    tampered = dataclasses.replace(results, remaining_loan_balance=results.remaining_loan_balance + 1.0)
    with pytest.raises(CapitalStructureExecutionError) as raised:
        run_unit(base_structure(dscr=2.0), terms=terms, results=tampered)
    assert [issue.code for issue in raised.value.issues] == [ExecutionIssueCode.LEGACY_PAYOFF_RECONCILIATION_FAILURE]


def test_a_month_outside_the_loans_modeled_life_is_a_programming_error() -> None:
    terms, results = base_unit()
    for month in (0, 61):
        with pytest.raises(ValueError):
            acquisition_loan_balance_after_month(terms=terms, results=results, model_month=month)


def test_the_service_never_mutates_its_inputs() -> None:
    terms, results = base_unit(interest_rate=0.06)
    before = (dataclasses.astuple(terms), dataclasses.astuple(results))
    acquisition_loan_balance_after_month(terms=terms, results=results, model_month=36)
    assert (dataclasses.astuple(terms), dataclasses.astuple(results)) == before


# =============================================================================
# F8 -- the refinance reads the service for the legacy payoff
# =============================================================================


@pytest.mark.parametrize("overrides", _CASES)
def test_the_refinance_payoff_is_the_services_balance(overrides: dict[str, float]) -> None:
    terms, results = base_unit(**overrides)
    result = run_unit(base_structure(fixed=1_000_000.0), terms=terms, results=results, with_valuation=False)
    (payoff,) = result.capital_events[0].payoffs
    assert payoff.payoff_authority is PayoffAuthority.ACQUISITION_DEBT_BALANCE_SERVICE
    assert payoff.payoff == acquisition_loan_balance_after_month(terms=terms, results=results, model_month=24).balance_after_month
    assert close(payoff.payoff, _oracle(overrides, 24), rel=1e-9)


def test_no_refinance_never_calls_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Section 19: a structure without a refinance never reaches the service."""

    import anchor.capital_structure.refinance as refinance

    def explode(**_: object) -> None:
        raise AssertionError("the acquisition-debt balance service ran without a refinance")

    monkeypatch.setattr(refinance, "acquisition_loan_balance_after_month", explode)
    monkeypatch.setattr(service, "acquisition_loan_balance_after_month", explode)
    run_unit(None)
    from _refinance_v1_fixtures import closing_debt, plain  # type: ignore[import-not-found]

    run_unit(plain(closing_debt("mezz", amount=1_000_000.0, priority=2, rate=0.1)))
