"""Phase 7 Gate P7.6 -- the Investment-level contracts and their validation.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 8.2, 9.1
(CON-1), 10 (BP-7) and 11 (PP-2 to PP-4, TC-1 to TC-5); the P7.6 decisions on
Unit timing and the transaction-cost contract. Pure: no store, no engine.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

import pytest

from anchor.business_plan import BusinessPlan, CapitalItemCategory, CapitalPlanItem
from anchor.contracts import OperatingMode
from anchor.investment import (
    ALLOCATION_TOLERANCE,
    InvestmentIssue,
    InvestmentIssueCode,
    InvestmentTransactionCost,
    InvestmentUnitMembership,
    InvestmentValidationError,
    TransactionCostCategory,
    UnitEconomicFacts,
    UnitKind,
    allocation_variance,
    validate_allocation,
    validate_common_timeline,
    validate_investment_business_plan,
    validate_investment_details,
    validate_investment_inputs,
    validate_transaction_costs,
    validate_unit_memberships,
    validate_variant_economics,
)

from _p7_6_fixtures import cost, member  # type: ignore[import-not-found]

Code = InvestmentIssueCode


def _codes(issues: tuple[InvestmentIssue, ...]) -> list[InvestmentIssueCode]:
    return [issue.code for issue in issues]


# =============================================================================
# The contracts
# =============================================================================


def test_unit_kind_is_three_reporting_members_with_lower_case_wire_values() -> None:
    assert [(kind.name, kind.value) for kind in UnitKind] == [
        ("PROPERTY", "property"), ("COMPONENT", "component"), ("PHASE", "phase"),
    ]


def test_transaction_cost_categories_are_exactly_the_five_reporting_members() -> None:
    assert [(category.name, category.value) for category in TransactionCostCategory] == [
        ("ACQUISITION_FEE", "acquisition_fee"),
        ("DUE_DILIGENCE", "due_diligence"),
        ("LEGAL", "legal"),
        ("PORTFOLIO_TRANSACTION_COST", "portfolio_transaction_cost"),
        ("OTHER", "other"),
    ]
    assert not {c.value for c in TransactionCostCategory} & {"financing_fee", "origination_fee", "refinancing_fee"}


def test_the_transaction_cost_and_membership_contracts_hold_exactly_their_fields() -> None:
    assert [f.name for f in dataclasses.fields(InvestmentTransactionCost)] == [
        "cost_id", "description", "category", "amount", "model_month",
    ]
    assert [f.name for f in dataclasses.fields(InvestmentUnitMembership)] == [
        "unit_id", "ordinal", "label", "unit_kind", "acquisition_month", "disposition_month",
    ]
    assert ALLOCATION_TOLERANCE == "0.01"


def test_the_error_requires_issues() -> None:
    with pytest.raises(ValueError):
        InvestmentValidationError([])
    error = InvestmentValidationError([InvestmentIssue(code=Code.NO_UNITS, message="m")])
    assert isinstance(error, ValueError) and error.issues[0].code is Code.NO_UNITS


# =============================================================================
# Details
# =============================================================================


@pytest.mark.parametrize(
    ("name", "price", "expected"),
    [
        ("Portfolio", 1.0, []),
        ("", 1.0, [Code.INVALID_NAME]),
        ("   ", 1.0, [Code.INVALID_NAME]),
        (None, 1.0, [Code.INVALID_NAME]),
        ("P", 0.0, [Code.INVALID_TRANSACTION_PRICE]),
        ("P", -1.0, [Code.INVALID_TRANSACTION_PRICE]),
        ("P", float("nan"), [Code.INVALID_TRANSACTION_PRICE]),
        ("P", float("inf"), [Code.INVALID_TRANSACTION_PRICE]),
        ("P", True, [Code.INVALID_TRANSACTION_PRICE]),
        ("P", "100", [Code.INVALID_TRANSACTION_PRICE]),
        ("", -1.0, [Code.INVALID_NAME, Code.INVALID_TRANSACTION_PRICE]),
    ],
)
def test_the_name_is_required_and_the_price_is_finite_and_positive(name: object, price: object, expected: list[InvestmentIssueCode]) -> None:
    assert _codes(validate_investment_details(name=name, transaction_price=price)) == expected


# =============================================================================
# Memberships -- presentation metadata and CON-1 timing
# =============================================================================


def test_a_valid_membership_set_has_no_issue() -> None:
    assert validate_unit_memberships((member("a"), member("b", ordinal=1, label="Retail", kind=UnitKind.COMPONENT))) == ()


@pytest.mark.parametrize(
    ("memberships", "expected"),
    [
        ([member("a")], [Code.INVALID_UNITS]),
        ((), [Code.NO_UNITS]),
        ((member("a"), "b"), [Code.INVALID_UNITS]),
        ((member(" "),), [Code.INVALID_UNIT_ID]),
        ((member("a"), member("a", ordinal=1)), [Code.DUPLICATE_UNIT]),
        ((member("a", ordinal=-1),), [Code.INVALID_ORDINAL]),
        ((member("a", ordinal=True),), [Code.INVALID_ORDINAL]),  # type: ignore[arg-type]
        ((member("a", label="  "),), [Code.INVALID_LABEL]),
        ((member("a", kind="building"),), [Code.UNKNOWN_UNIT_KIND]),
        ((member("a", acquisition_month=-1),), [Code.INVALID_ACQUISITION_MONTH]),
        ((member("a", acquisition_month=1.0),), [Code.INVALID_ACQUISITION_MONTH]),
        ((member("a", acquisition_month=12),), [Code.UNSUPPORTED_ACQUISITION_MONTH]),
        ((member("a", disposition_month=0),), [Code.INVALID_DISPOSITION_MONTH]),
        ((member("a", disposition_month=60),), [Code.UNSUPPORTED_DISPOSITION_MONTH]),
    ],
)
def test_every_membership_rule(memberships: object, expected: list[InvestmentIssueCode]) -> None:
    assert _codes(validate_unit_memberships(memberships)) == expected


def test_membership_issues_are_reported_in_unit_order_whatever_the_display_order() -> None:
    forward = validate_unit_memberships((member("a", acquisition_month=3), member("b", disposition_month=24)))
    backward = validate_unit_memberships((member("b", ordinal=0, disposition_month=24), member("a", ordinal=1, acquisition_month=3)))
    assert [issue.unit_id for issue in forward] == [issue.unit_id for issue in backward] == ["a", "b"]
    assert _codes(forward) == [Code.UNSUPPORTED_ACQUISITION_MONTH, Code.UNSUPPORTED_DISPOSITION_MONTH]


def test_label_kind_and_ordinal_are_reporting_only_and_every_kind_is_valid() -> None:
    for kind in UnitKind:
        assert validate_unit_memberships((member("a", kind=kind, label=None, ordinal=7),)) == ()


# =============================================================================
# Transaction costs -- TC-1, TC-2
# =============================================================================


def test_valid_costs_include_a_zero_placeholder() -> None:
    assert validate_transaction_costs((cost("c1", 100_000.0), cost("c2", 0.0, category=TransactionCostCategory.OTHER))) == ()


@pytest.mark.parametrize(
    ("costs", "expected"),
    [
        ([cost("c", 1.0)], [Code.INVALID_TRANSACTION_COSTS]),
        ((cost("c", 1.0), 3), [Code.INVALID_TRANSACTION_COSTS]),
        ((cost("", 1.0),), [Code.INVALID_COST_ID]),
        ((cost("c", 1.0), cost("c", 2.0)), [Code.DUPLICATE_COST_ID]),
        ((cost("c", 1.0, description=" "),), [Code.INVALID_COST_DESCRIPTION]),
        ((cost("c", 1.0, category="loan_origination"),), [Code.UNKNOWN_COST_CATEGORY]),
        ((cost("c", -0.01),), [Code.INVALID_COST_AMOUNT]),
        ((cost("c", float("nan")),), [Code.INVALID_COST_AMOUNT]),
        ((cost("c", float("inf")),), [Code.INVALID_COST_AMOUNT]),
        ((cost("c", True),), [Code.INVALID_COST_AMOUNT]),
        ((cost("c", 1.0, model_month=-1),), [Code.INVALID_COST_MONTH]),
        ((cost("c", 1.0, model_month=1.5),), [Code.INVALID_COST_MONTH]),
        ((cost("c", 1.0, model_month=12),), [Code.UNSUPPORTED_COST_MONTH]),
    ],
)
def test_every_transaction_cost_rule(costs: object, expected: list[InvestmentIssueCode]) -> None:
    assert _codes(validate_transaction_costs(costs)) == expected


def test_cost_issues_are_in_cost_id_order_whatever_the_row_order() -> None:
    rows = (cost("z", -1.0), cost("a", 1.0, model_month=12))
    assert [issue.field for issue in validate_transaction_costs(rows)] == [
        "transaction_costs[1].model_month", "transaction_costs[0].amount",
    ]


def test_the_investment_plan_is_judged_by_the_d6_validator_with_its_code() -> None:
    duplicate = CapitalPlanItem(item_id="x", description="d", category=CapitalItemCategory.OTHER, month=0, amount=1.0)
    issues = validate_investment_business_plan(BusinessPlan(capital_items=(duplicate, duplicate)))
    assert issues and {issue.code for issue in issues} == {Code.INVALID_BUSINESS_PLAN}
    assert all(issue.source_code and issue.field and issue.field.startswith("business_plan") for issue in issues)
    assert validate_investment_business_plan(BusinessPlan()) == ()


def test_the_whole_input_order_is_details_units_plan_costs() -> None:
    duplicate = CapitalPlanItem(item_id="x", description="d", category=CapitalItemCategory.OTHER, month=0, amount=1.0)
    issues = validate_investment_inputs(
        name="",
        transaction_price=1.0,
        memberships=(member("a", acquisition_month=1),),
        business_plan=BusinessPlan(capital_items=(duplicate, duplicate)),
        transaction_costs=(cost("c", -1.0),),
    )
    assert _codes(issues)[0] is Code.INVALID_NAME
    assert _codes(issues)[1] is Code.UNSUPPORTED_ACQUISITION_MONTH
    assert _codes(issues)[-1] is Code.INVALID_COST_AMOUNT
    assert Code.INVALID_BUSINESS_PLAN in _codes(issues)


# =============================================================================
# PP-2 -- the $0.01 allocation rule, on the wire dollar values
# =============================================================================


@pytest.mark.parametrize("base", [100.0, 100_000.0, 1_000_000.0, 123_456_789.0, 2_500_000_000.0])
def test_exactly_one_cent_reconciles_at_every_magnitude(base: float) -> None:
    """The float difference of ``base + 0.01`` and ``base`` is sometimes a
    hair above 0.01; the rule is about the cents written, not binary noise."""

    assert validate_allocation(unit_prices=[("a", base + 0.01)], transaction_price=base) == ()
    assert validate_allocation(unit_prices=[("a", base)], transaction_price=base + 0.01) == ()


@pytest.mark.parametrize("base", [100.0, 100_000.0, 1_000_000.0, 123_456_789.0])
def test_more_than_one_cent_is_refused_never_rescaled(base: float) -> None:
    for gap in (0.02, 0.011, -0.011):
        issues = validate_allocation(unit_prices=[("a", base + gap)], transaction_price=base)
        assert _codes(issues) == [Code.ALLOCATION_MISMATCH], gap


def test_the_variance_is_exact_and_canonical() -> None:
    prices = [("b", 6_000_000.005), ("a", 9_999_999.995), ("c", 0.01)]
    assert allocation_variance(unit_prices=prices, transaction_price=16_000_000.0) == Decimal("0.010")
    assert allocation_variance(unit_prices=list(reversed(prices)), transaction_price=16_000_000.0) == Decimal("0.010")
    assert validate_allocation(unit_prices=prices, transaction_price=16_000_000.0) == ()
    assert validate_allocation(unit_prices=prices, transaction_price=15_999_999.98) != ()


def test_the_mismatch_names_the_units_and_the_gap() -> None:
    (issue,) = validate_allocation(unit_prices=[("b", 7.0), ("a", 4.0)], transaction_price=10.0)
    assert issue.field == "transaction_price"
    assert issue.message.index("a: 4.0") < issue.message.index("b: 7.0")
    assert "1.0" in issue.message


# =============================================================================
# CON-1 -- the common timeline
# =============================================================================


def _fact(unit: str, mode: OperatingMode, price: float, hold: int, start: date | None = None) -> UnitEconomicFacts:
    return UnitEconomicFacts(unit_id=unit, operating_mode=mode, purchase_price=price, hold_period=hold, analysis_start_date=start)


def test_mixed_modes_on_one_hold_and_one_calendar_anchor_are_valid() -> None:
    facts = [
        _fact("q", OperatingMode.QUICK, 1.0, 5),
        _fact("d", OperatingMode.DETAILED, 2.0, 5),
        _fact("l1", OperatingMode.LEASE_LEVEL, 3.0, 5, date(2027, 1, 1)),
        _fact("l2", OperatingMode.LEASE_LEVEL, 4.0, 5, date(2027, 1, 1)),
    ]
    assert validate_common_timeline(facts) == ()
    assert validate_variant_economics(facts, transaction_price=10.0) == ()


def test_different_holds_are_refused_never_padded_or_truncated() -> None:
    issues = validate_common_timeline([_fact("a", OperatingMode.QUICK, 1.0, 5), _fact("b", OperatingMode.DETAILED, 1.0, 7)])
    assert _codes(issues) == [Code.HOLD_PERIOD_MISMATCH]
    assert "a: 5 years, b: 7 years" in issues[0].message


def test_lease_level_units_must_share_one_analysis_start_date() -> None:
    issues = validate_common_timeline([
        _fact("a", OperatingMode.LEASE_LEVEL, 1.0, 5, date(2027, 1, 1)),
        _fact("b", OperatingMode.LEASE_LEVEL, 1.0, 5, date(2027, 7, 1)),
    ])
    assert _codes(issues) == [Code.ANALYSIS_START_DATE_MISMATCH]


def test_the_variant_rules_run_timeline_then_allocation() -> None:
    issues = validate_variant_economics(
        [_fact("a", OperatingMode.QUICK, 1.0, 5), _fact("b", OperatingMode.QUICK, 1.0, 7)], transaction_price=5.0
    )
    assert _codes(issues) == [Code.HOLD_PERIOD_MISMATCH, Code.ALLOCATION_MISMATCH]
