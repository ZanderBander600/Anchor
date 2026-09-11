"""Gate D6.1 -- Business Plan contracts, validation and the engine's
``OwnerCapitalSchedule`` contract.

Governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 3,
5, 13 and 18. Resolver arithmetic is covered by
``tests/test_d6_1_business_plan_resolver.py``.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import math

import pytest

from anchor.business_plan import (
    BusinessPlan,
    BusinessPlanIssueCode,
    BusinessPlanValidationError,
    BusinessPlanValidationResult,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseHoldTreatment,
    OwnerExpenseItem,
    require_valid_business_plan,
    validate_business_plan,
)
from anchor.engine.contracts import NonFiniteResultError, OwnerCapitalSchedule


def _capital(**overrides: object) -> CapitalPlanItem:
    values: dict[str, object] = {
        "item_id": "cap-1",
        "description": "Roof replacement",
        "category": CapitalItemCategory.BUILDING_SYSTEMS,
        "month": 6,
        "amount": 250_000.0,
    }
    values.update(overrides)
    return CapitalPlanItem(**values)  # type: ignore[arg-type]


def _expense(**overrides: object) -> OwnerExpenseItem:
    values: dict[str, object] = {
        "item_id": "oe-1",
        "description": "Asset management",
        "category": OwnerExpenseCategory.ASSET_MANAGEMENT,
        "annual_amount": 50_000.0,
        "first_year": 1,
        "last_year": None,
    }
    values.update(overrides)
    return OwnerExpenseItem(**values)  # type: ignore[arg-type]


def _codes(plan: BusinessPlan) -> list[tuple[BusinessPlanIssueCode, str]]:
    return [(issue.code, issue.path) for issue in validate_business_plan(plan).issues]


# =============================================================================
# Enums -- exact ratified membership, reporting only
# =============================================================================


def test_capital_item_category_has_exactly_the_five_ratified_members() -> None:
    assert [member.name for member in CapitalItemCategory] == [
        "VALUE_ADD_RENOVATION",
        "DEFERRED_MAINTENANCE",
        "BUILDING_SYSTEMS",
        "EXTERIOR_COMMON_AREA",
        "OTHER",
    ]
    assert [member.value for member in CapitalItemCategory] == [
        "value_add_renovation",
        "deferred_maintenance",
        "building_systems",
        "exterior_common_area",
        "other",
    ]


@pytest.mark.parametrize(
    "excluded", ["CONTINGENCY", "RECURRING_REPLACEMENT", "RESERVE", "TI", "LC"]
)
def test_capital_item_category_excludes_double_count_categories(excluded: str) -> None:
    """Section 3 / Section 20: structural double-count protection."""

    assert excluded not in CapitalItemCategory.__members__
    assert excluded.lower() not in {member.value for member in CapitalItemCategory}


def test_owner_expense_category_has_exactly_the_three_ratified_members() -> None:
    assert [member.name for member in OwnerExpenseCategory] == [
        "ASSET_MANAGEMENT",
        "LEGAL_PARTNERSHIP",
        "OTHER",
    ]
    assert [member.value for member in OwnerExpenseCategory] == [
        "asset_management",
        "legal_partnership",
        "other",
    ]
    for name in OwnerExpenseCategory.__members__:
        assert "MANAGEMENT_FEE" not in name and "PROPERTY" not in name


def test_owner_expense_hold_treatment_has_exactly_three_members() -> None:
    assert [member.name for member in OwnerExpenseHoldTreatment] == [
        "FULLY_INSIDE_HOLD",
        "PARTIALLY_OUTSIDE_HOLD",
        "FULLY_OUTSIDE_HOLD",
    ]


# =============================================================================
# Contract shapes
# =============================================================================


@pytest.mark.parametrize(
    ("contract", "expected"),
    [
        (
            CapitalPlanItem,
            ["item_id", "description", "category", "month", "amount"],
        ),
        (
            OwnerExpenseItem,
            [
                "item_id",
                "description",
                "category",
                "annual_amount",
                "first_year",
                "last_year",
            ],
        ),
        (BusinessPlan, ["capital_items", "owner_expense_items"]),
        (
            OwnerCapitalSchedule,
            [
                "closing_project_capital",
                "project_capital_by_year",
                "owner_expenses_by_year",
                "post_hold_project_capital",
            ],
        ),
    ],
    ids=lambda value: getattr(value, "__name__", ""),
)
def test_contracts_have_exact_fields_and_are_frozen_slotted_keyword_only(
    contract: type, expected: list[str]
) -> None:
    assert [field.name for field in fields(contract)] == expected
    assert all(field.kw_only for field in fields(contract))
    assert contract.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert hasattr(contract, "__slots__")


def test_contracts_are_immutable() -> None:
    plan = BusinessPlan(capital_items=(_capital(),))
    with pytest.raises(FrozenInstanceError):
        plan.capital_items = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.capital_items[0].amount = 1.0  # type: ignore[misc]


def test_contracts_reject_positional_construction() -> None:
    with pytest.raises(TypeError):
        CapitalPlanItem(  # type: ignore[misc]
            "id", "desc", CapitalItemCategory.OTHER, 0, 0.0
        )


def test_empty_business_plan_is_a_valid_first_class_state() -> None:
    plan = BusinessPlan()

    assert plan.capital_items == ()
    assert plan.owner_expense_items == ()
    assert validate_business_plan(plan).is_valid
    assert require_valid_business_plan(plan) == BusinessPlanValidationResult()


def test_business_plan_defaults_are_immutable_tuples_not_shared_lists() -> None:
    first, second = BusinessPlan(), BusinessPlan()
    assert isinstance(first.capital_items, tuple)
    assert isinstance(first.owner_expense_items, tuple)
    assert first == second and hash(first) == hash(second)


def test_owner_expense_last_year_defaults_to_none() -> None:
    item = OwnerExpenseItem(
        item_id="oe",
        description="Legal",
        category=OwnerExpenseCategory.LEGAL_PARTNERSHIP,
        annual_amount=1.0,
        first_year=1,
    )
    assert item.last_year is None


def test_construction_stores_supplied_strings_unmodified() -> None:
    """Validation may inspect trimmed content; it never mutates the value."""

    item = _capital(item_id="  cap-1  ", description="  Roof  ")
    plan = BusinessPlan(capital_items=(item,))

    assert validate_business_plan(plan).is_valid
    assert plan.capital_items[0].item_id == "  cap-1  "
    assert plan.capital_items[0].description == "  Roof  "


# =============================================================================
# Valid inputs, including zero and unbounded values
# =============================================================================


def test_a_fully_populated_plan_is_valid() -> None:
    plan = BusinessPlan(
        capital_items=(
            _capital(item_id="c0", month=0),
            _capital(item_id="c1", month=1, amount=0.0),
            _capital(item_id="c2", month=10**9, amount=7),
        ),
        owner_expense_items=(
            _expense(item_id="e1"),
            _expense(item_id="e2", first_year=4, last_year=8, annual_amount=0.0),
            _expense(item_id="e3", first_year=7, last_year=7),
        ),
    )

    assert validate_business_plan(plan).issues == ()


def test_uuid_format_is_not_required_for_item_ids() -> None:
    plan = BusinessPlan(
        capital_items=(_capital(item_id="x"),),
        owner_expense_items=(_expense(item_id="550e8400-e29b-41d4-a716-446655440000"),),
    )
    assert validate_business_plan(plan).is_valid


# =============================================================================
# CapitalPlanItem validation (Part P)
# =============================================================================


@pytest.mark.parametrize(
    ("overrides", "code", "field"),
    [
        ({"item_id": ""}, BusinessPlanIssueCode.EMPTY_ITEM_ID, "item_id"),
        ({"item_id": "   \t"}, BusinessPlanIssueCode.EMPTY_ITEM_ID, "item_id"),
        ({"item_id": 7}, BusinessPlanIssueCode.MALFORMED_FIELD, "item_id"),
        ({"description": ""}, BusinessPlanIssueCode.EMPTY_DESCRIPTION, "description"),
        ({"description": "  "}, BusinessPlanIssueCode.EMPTY_DESCRIPTION, "description"),
        ({"description": None}, BusinessPlanIssueCode.MALFORMED_FIELD, "description"),
        ({"category": "other"}, BusinessPlanIssueCode.UNSUPPORTED_CATEGORY, "category"),
        (
            {"category": OwnerExpenseCategory.OTHER},
            BusinessPlanIssueCode.UNSUPPORTED_CATEGORY,
            "category",
        ),
        ({"month": True}, BusinessPlanIssueCode.NON_WHOLE_NUMBER_MONTH, "month"),
        ({"month": False}, BusinessPlanIssueCode.NON_WHOLE_NUMBER_MONTH, "month"),
        ({"month": 12.0}, BusinessPlanIssueCode.NON_WHOLE_NUMBER_MONTH, "month"),
        ({"month": "12"}, BusinessPlanIssueCode.NON_WHOLE_NUMBER_MONTH, "month"),
        ({"month": -1}, BusinessPlanIssueCode.MONTH_OUT_OF_DOMAIN, "month"),
        ({"amount": math.nan}, BusinessPlanIssueCode.NON_FINITE_VALUE, "amount"),
        ({"amount": math.inf}, BusinessPlanIssueCode.NON_FINITE_VALUE, "amount"),
        ({"amount": -math.inf}, BusinessPlanIssueCode.NON_FINITE_VALUE, "amount"),
        ({"amount": True}, BusinessPlanIssueCode.NON_FINITE_VALUE, "amount"),
        ({"amount": "100"}, BusinessPlanIssueCode.NON_FINITE_VALUE, "amount"),
        ({"amount": -0.01}, BusinessPlanIssueCode.AMOUNT_OUT_OF_DOMAIN, "amount"),
    ],
)
def test_invalid_capital_item_fields_are_rejected(
    overrides: dict[str, object], code: BusinessPlanIssueCode, field: str
) -> None:
    plan = BusinessPlan(capital_items=(_capital(**overrides),))

    assert _codes(plan) == [(code, f"capital_items[0].{field}")]
    with pytest.raises(BusinessPlanValidationError) as raised:
        require_valid_business_plan(plan)
    assert isinstance(raised.value, ValueError)
    assert [issue.code for issue in raised.value.result.issues] == [code]


def test_invalid_values_are_kept_exactly_as_supplied() -> None:
    """No coercion: an invalid month stays the supplied object."""

    item = _capital(month=12.0)
    plan = BusinessPlan(capital_items=(item,))

    assert not validate_business_plan(plan).is_valid
    assert type(plan.capital_items[0].month) is float


# =============================================================================
# OwnerExpenseItem validation (Part P)
# =============================================================================


@pytest.mark.parametrize(
    ("overrides", "code", "field"),
    [
        ({"item_id": ""}, BusinessPlanIssueCode.EMPTY_ITEM_ID, "item_id"),
        ({"item_id": " "}, BusinessPlanIssueCode.EMPTY_ITEM_ID, "item_id"),
        ({"description": ""}, BusinessPlanIssueCode.EMPTY_DESCRIPTION, "description"),
        ({"description": "\n"}, BusinessPlanIssueCode.EMPTY_DESCRIPTION, "description"),
        (
            {"category": "asset_management"},
            BusinessPlanIssueCode.UNSUPPORTED_CATEGORY,
            "category",
        ),
        (
            {"category": CapitalItemCategory.OTHER},
            BusinessPlanIssueCode.UNSUPPORTED_CATEGORY,
            "category",
        ),
        ({"annual_amount": math.nan}, BusinessPlanIssueCode.NON_FINITE_VALUE, "annual_amount"),
        ({"annual_amount": math.inf}, BusinessPlanIssueCode.NON_FINITE_VALUE, "annual_amount"),
        ({"annual_amount": -math.inf}, BusinessPlanIssueCode.NON_FINITE_VALUE, "annual_amount"),
        ({"annual_amount": False}, BusinessPlanIssueCode.NON_FINITE_VALUE, "annual_amount"),
        ({"annual_amount": -1.0}, BusinessPlanIssueCode.AMOUNT_OUT_OF_DOMAIN, "annual_amount"),
        ({"first_year": True}, BusinessPlanIssueCode.NON_WHOLE_NUMBER_YEAR, "first_year"),
        ({"first_year": 2.0}, BusinessPlanIssueCode.NON_WHOLE_NUMBER_YEAR, "first_year"),
        ({"first_year": 0}, BusinessPlanIssueCode.FIRST_YEAR_OUT_OF_DOMAIN, "first_year"),
        ({"first_year": -3}, BusinessPlanIssueCode.FIRST_YEAR_OUT_OF_DOMAIN, "first_year"),
        ({"last_year": True}, BusinessPlanIssueCode.NON_WHOLE_NUMBER_YEAR, "last_year"),
        ({"last_year": 5.0}, BusinessPlanIssueCode.NON_WHOLE_NUMBER_YEAR, "last_year"),
        (
            {"first_year": 3, "last_year": 2},
            BusinessPlanIssueCode.LAST_YEAR_BEFORE_FIRST_YEAR,
            "last_year",
        ),
    ],
)
def test_invalid_owner_expense_fields_are_rejected(
    overrides: dict[str, object], code: BusinessPlanIssueCode, field: str
) -> None:
    plan = BusinessPlan(owner_expense_items=(_expense(**overrides),))

    assert _codes(plan) == [(code, f"owner_expense_items[0].{field}")]
    with pytest.raises(BusinessPlanValidationError):
        require_valid_business_plan(plan)


def test_last_year_equal_to_first_year_is_valid() -> None:
    plan = BusinessPlan(owner_expense_items=(_expense(first_year=3, last_year=3),))
    assert validate_business_plan(plan).is_valid


def test_last_year_is_not_compared_against_an_invalid_first_year() -> None:
    """One defect, one issue: a bad first_year is not also blamed on
    last_year."""

    plan = BusinessPlan(owner_expense_items=(_expense(first_year=0, last_year=-5),))

    assert _codes(plan) == [
        (BusinessPlanIssueCode.FIRST_YEAR_OUT_OF_DOMAIN, "owner_expense_items[0].first_year")
    ]


def test_owner_expense_years_beyond_any_hold_are_valid() -> None:
    """Section 5 / Section 18: accepted; the hold is not a validation input."""

    plan = BusinessPlan(
        owner_expense_items=(_expense(first_year=40, last_year=10**6),)
    )
    assert validate_business_plan(plan).is_valid


# =============================================================================
# BusinessPlan structure and the shared ID namespace (Part H, U8)
# =============================================================================


def test_duplicate_capital_item_ids_are_rejected() -> None:
    plan = BusinessPlan(
        capital_items=(_capital(item_id="a"), _capital(item_id="b"), _capital(item_id="a"))
    )

    assert _codes(plan) == [(BusinessPlanIssueCode.DUPLICATE_ITEM_ID, "capital_items[2].item_id")]


def test_duplicate_owner_expense_item_ids_are_rejected() -> None:
    plan = BusinessPlan(
        owner_expense_items=(_expense(item_id="a"), _expense(item_id="a"))
    )

    assert _codes(plan) == [
        (BusinessPlanIssueCode.DUPLICATE_ITEM_ID, "owner_expense_items[1].item_id")
    ]


def test_u8_a_cross_type_duplicate_id_is_rejected() -> None:
    """**U8 / decision D17.** One namespace across both collections, even
    though the item types differ."""

    plan = BusinessPlan(
        capital_items=(_capital(item_id="abc"),),
        owner_expense_items=(_expense(item_id="abc"),),
    )

    result = validate_business_plan(plan)

    assert [(issue.code, issue.path) for issue in result.issues] == [
        (BusinessPlanIssueCode.DUPLICATE_ITEM_ID, "owner_expense_items[0].item_id")
    ]
    assert "capital_items[0]" in result.issues[0].message
    with pytest.raises(BusinessPlanValidationError):
        require_valid_business_plan(plan)


def test_item_ids_are_opaque_and_compared_exactly() -> None:
    plan = BusinessPlan(
        capital_items=(_capital(item_id="abc"),),
        owner_expense_items=(_expense(item_id="ABC"), _expense(item_id="abc ")),
    )
    assert validate_business_plan(plan).is_valid


def test_blank_ids_are_not_also_reported_as_duplicates() -> None:
    plan = BusinessPlan(capital_items=(_capital(item_id=""), _capital(item_id="")))

    assert _codes(plan) == [
        (BusinessPlanIssueCode.EMPTY_ITEM_ID, "capital_items[0].item_id"),
        (BusinessPlanIssueCode.EMPTY_ITEM_ID, "capital_items[1].item_id"),
    ]


@pytest.mark.parametrize(
    ("plan", "path"),
    [
        (BusinessPlan(capital_items=[_capital()]), "capital_items"),  # type: ignore[arg-type]
        (BusinessPlan(owner_expense_items=[_expense()]), "owner_expense_items"),  # type: ignore[arg-type]
        (BusinessPlan(capital_items=(_expense(),)), "capital_items[0]"),  # type: ignore[arg-type]
        (BusinessPlan(owner_expense_items=(_capital(),)), "owner_expense_items[0]"),  # type: ignore[arg-type]
    ],
    ids=["capital-list", "expense-list", "expense-in-capital", "capital-in-expense"],
)
def test_malformed_collections_are_rejected_not_reinterpreted(
    plan: BusinessPlan, path: str
) -> None:
    assert _codes(plan) == [(BusinessPlanIssueCode.MALFORMED_FIELD, path)]


def test_a_non_business_plan_is_rejected() -> None:
    assert _codes({"capital_items": ()}) == [  # type: ignore[arg-type]
        (BusinessPlanIssueCode.MALFORMED_FIELD, "business_plan")
    ]


def test_issue_order_is_deterministic_and_follows_declared_order() -> None:
    """Capital items first, then owner-expense items, each in declared order,
    each item's fields in declared field order; repeated runs are identical."""

    plan = BusinessPlan(
        capital_items=(
            _capital(item_id="dup", month=-1, amount=math.nan),
            _capital(item_id="ok", description=" ", category="other"),
        ),
        owner_expense_items=(
            _expense(item_id="dup", annual_amount=-2.0, first_year=True, last_year=0.5),
        ),
    )

    expected = [
        (BusinessPlanIssueCode.MONTH_OUT_OF_DOMAIN, "capital_items[0].month"),
        (BusinessPlanIssueCode.NON_FINITE_VALUE, "capital_items[0].amount"),
        (BusinessPlanIssueCode.EMPTY_DESCRIPTION, "capital_items[1].description"),
        (BusinessPlanIssueCode.UNSUPPORTED_CATEGORY, "capital_items[1].category"),
        (BusinessPlanIssueCode.DUPLICATE_ITEM_ID, "owner_expense_items[0].item_id"),
        (BusinessPlanIssueCode.AMOUNT_OUT_OF_DOMAIN, "owner_expense_items[0].annual_amount"),
        (BusinessPlanIssueCode.NON_WHOLE_NUMBER_YEAR, "owner_expense_items[0].first_year"),
        (BusinessPlanIssueCode.NON_WHOLE_NUMBER_YEAR, "owner_expense_items[0].last_year"),
    ]
    assert _codes(plan) == expected
    assert validate_business_plan(plan) == validate_business_plan(plan)

    with pytest.raises(BusinessPlanValidationError) as raised:
        require_valid_business_plan(plan)
    assert [(issue.code, issue.path) for issue in raised.value.result.issues] == expected


def test_validation_error_requires_at_least_one_issue() -> None:
    with pytest.raises(ValueError):
        BusinessPlanValidationError(BusinessPlanValidationResult())


# =============================================================================
# OwnerCapitalSchedule -- the generic engine contract (Part I)
# =============================================================================


def _schedule(**overrides: object) -> OwnerCapitalSchedule:
    values: dict[str, object] = {
        "closing_project_capital": 0.0,
        "project_capital_by_year": (0.0, 0.0),
        "owner_expenses_by_year": (0.0, 0.0),
        "post_hold_project_capital": 0.0,
    }
    values.update(overrides)
    return OwnerCapitalSchedule(**values)  # type: ignore[arg-type]


def test_owner_capital_schedule_accepts_a_valid_shape() -> None:
    schedule = _schedule(
        closing_project_capital=1.0,
        project_capital_by_year=(2.0, 3.0),
        owner_expenses_by_year=(4.0, 0.0),
        post_hold_project_capital=5.0,
    )
    assert schedule.project_capital_by_year == (2.0, 3.0)


def test_owner_capital_schedule_requires_aligned_series() -> None:
    with pytest.raises(ValueError, match="per hold year"):
        _schedule(project_capital_by_year=(0.0, 0.0, 0.0))


def test_owner_capital_schedule_requires_at_least_one_hold_year() -> None:
    with pytest.raises(ValueError, match="at least one hold year"):
        _schedule(project_capital_by_year=(), owner_expenses_by_year=())


@pytest.mark.parametrize(
    "overrides",
    [
        {"closing_project_capital": math.nan},
        {"project_capital_by_year": (0.0, math.inf)},
        {"owner_expenses_by_year": (-math.inf, 0.0)},
        {"post_hold_project_capital": math.inf},
    ],
)
def test_owner_capital_schedule_rejects_non_finite_figures(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(NonFiniteResultError):
        _schedule(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"closing_project_capital": -1.0},
        {"project_capital_by_year": (0.0, -0.5)},
        {"owner_expenses_by_year": (-1e-9, 0.0)},
        {"post_hold_project_capital": -2.0},
    ],
)
def test_owner_capital_schedule_rejects_negative_figures(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        _schedule(**overrides)
