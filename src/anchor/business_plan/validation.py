"""Phase 6 Gate D6.1 -- Business Plan validation.

Restates ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 3, 5
and 18; that document governs on any discrepancy.

Follows the ``anchor.leasing.validation`` precedent for domain input
contracts: ``validate_business_plan`` reports every issue at once as an
ordered, path-addressed ``BusinessPlanValidationResult``, and
``require_valid_business_plan`` raises ``BusinessPlanValidationError`` (a
``ValueError``, like every other refusal contract here) carrying that result.
It deliberately does not import ``anchor.validation``, whose issue contract is
shaped for workbook fields, nor ``anchor.leasing``, which is a different
domain.

There is no warning severity: D6.1 has no rule that lets a questionable input
proceed, and a severity level is not invented merely to exist.

**No coercion.** No value is stripped, rounded, converted or defaulted. A
``bool`` is refused wherever an integer or a dollar figure is required, a
float is refused where a whole number is required, and a raw string is refused
where a category enum member is required. Validation may inspect the trimmed
content of an identifier or description, but the supplied string is kept.

**No operational limits.** The core financial contract sets no maximum item
count, month, year or amount (Section 18). Practical payload limits belong to
a later operational gate and must not change financial semantics.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import TypeGuard

from .contracts import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)


class BusinessPlanIssueCode(StrEnum):
    """Stable, machine-readable Business Plan issue codes.

    Declared as an enum so a code cannot be misspelled at a call site and the
    D6.1 rule set is enumerable by a test.
    """

    # --- structure ---
    MALFORMED_FIELD = "MALFORMED_FIELD"

    # --- identity (Section 3, decision D17) ---
    EMPTY_ITEM_ID = "EMPTY_ITEM_ID"
    DUPLICATE_ITEM_ID = "DUPLICATE_ITEM_ID"

    # --- reporting metadata ---
    EMPTY_DESCRIPTION = "EMPTY_DESCRIPTION"
    UNSUPPORTED_CATEGORY = "UNSUPPORTED_CATEGORY"

    # --- timing (Sections 4 and 5) ---
    NON_WHOLE_NUMBER_MONTH = "NON_WHOLE_NUMBER_MONTH"
    MONTH_OUT_OF_DOMAIN = "MONTH_OUT_OF_DOMAIN"
    NON_WHOLE_NUMBER_YEAR = "NON_WHOLE_NUMBER_YEAR"
    FIRST_YEAR_OUT_OF_DOMAIN = "FIRST_YEAR_OUT_OF_DOMAIN"
    LAST_YEAR_BEFORE_FIRST_YEAR = "LAST_YEAR_BEFORE_FIRST_YEAR"

    # --- dollars ---
    NON_FINITE_VALUE = "NON_FINITE_VALUE"
    AMOUNT_OUT_OF_DOMAIN = "AMOUNT_OUT_OF_DOMAIN"


@dataclass(frozen=True, slots=True, kw_only=True)
class BusinessPlanValidationIssue:
    """One deterministic Business Plan validation finding.

    ``path`` locates the finding in the submitted plan, for example
    ``"capital_items[3].month"`` or ``"owner_expense_items[0].item_id"``.
    """

    code: BusinessPlanIssueCode
    path: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BusinessPlanValidationResult:
    """The complete outcome of validating one Business Plan.

    ``issues`` is already in the canonical order described on
    ``validate_business_plan``. Every issue is an error.
    """

    issues: tuple[BusinessPlanValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.issues


class BusinessPlanValidationError(ValueError):
    """Raised when Business Plan validation found at least one issue.

    Carries the whole ``BusinessPlanValidationResult`` so a caller never has to
    re-run validation to see every issue. Mirrors
    ``anchor.leasing.validation.LeaseValidationError`` without importing it.
    """

    def __init__(self, result: BusinessPlanValidationResult) -> None:
        if not result.issues:
            raise ValueError(
                "BusinessPlanValidationError requires a result with at least "
                "one issue."
            )
        self.result = result
        super().__init__("\n".join(issue.message for issue in result.issues))


# =============================================================================
# Field rules
# =============================================================================


def _issue(
    code: BusinessPlanIssueCode, path: str, message: str
) -> BusinessPlanValidationIssue:
    return BusinessPlanValidationIssue(code=code, path=path, message=message)


def _is_whole_number(value: object) -> bool:
    """An ``int`` that is not a ``bool``. A float is refused even when it is
    integral: ``12.0`` is not silently read as month 12."""

    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    """The same numeric rule ``anchor.leasing.validation`` applies: an ``int``
    or ``float``, never a ``bool``, and finite."""

    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def _validate_text(
    value: object,
    *,
    path: str,
    label: str,
    empty_code: BusinessPlanIssueCode,
) -> list[BusinessPlanValidationIssue]:
    if not isinstance(value, str):
        return [
            _issue(
                BusinessPlanIssueCode.MALFORMED_FIELD,
                path,
                f"{label} must be a string; got {type(value).__name__}.",
            )
        ]
    if not value.strip():
        return [_issue(empty_code, path, f"{label} must be nonempty.")]
    return []


def _validate_category(
    value: object,
    *,
    path: str,
    category_type: type[StrEnum],
) -> list[BusinessPlanValidationIssue]:
    """The value must be a member of exactly ``category_type``.

    A raw string is refused even when it equals a member's value, and so is a
    member of the *other* category enum: ``OwnerExpenseCategory.OTHER`` and
    ``CapitalItemCategory.OTHER`` compare equal as strings, and accepting one
    for the other would let the two vocabularies silently merge.
    """

    if isinstance(value, category_type):
        return []
    return [
        _issue(
            BusinessPlanIssueCode.UNSUPPORTED_CATEGORY,
            path,
            f"category must be a {category_type.__name__} member; got "
            f"{value!r}.",
        )
    ]


def _validate_dollars(
    value: object, *, path: str, label: str
) -> list[BusinessPlanValidationIssue]:
    """Finite and ``>= 0``. Zero is valid."""

    if not _is_finite_number(value):
        return [
            _issue(
                BusinessPlanIssueCode.NON_FINITE_VALUE,
                path,
                f"{label} must be a finite number; got {value!r}.",
            )
        ]
    if value < 0:
        return [
            _issue(
                BusinessPlanIssueCode.AMOUNT_OUT_OF_DOMAIN,
                path,
                f"{label} {value!r} must be greater than or equal to 0.",
            )
        ]
    return []


def _validate_item_id(
    value: object,
    *,
    path: str,
    first_path_by_id: dict[str, str],
) -> list[BusinessPlanValidationIssue]:
    """Nonempty, and unique across the **whole** Business Plan.

    One shared namespace (decision D17): a capital item and an owner-expense
    item may not share an ID even though their types differ.
    ``first_path_by_id`` is shared by both collections for exactly that
    reason. The first declaration in canonical order keeps the ID; every later
    one is reported at its own path. IDs are opaque, so they are compared
    exactly as supplied.
    """

    issues = _validate_text(
        value,
        path=path,
        label="item_id",
        empty_code=BusinessPlanIssueCode.EMPTY_ITEM_ID,
    )
    if issues:
        return issues

    assert isinstance(value, str)
    first_path = first_path_by_id.get(value)
    if first_path is not None:
        return [
            _issue(
                BusinessPlanIssueCode.DUPLICATE_ITEM_ID,
                path,
                f"item_id {value!r} is already used by {first_path}; item IDs "
                "are unique across the whole Business Plan, capital and "
                "owner-expense items together.",
            )
        ]
    first_path_by_id[value] = path
    return []


# =============================================================================
# Item rules
# =============================================================================


def _validate_capital_item(
    item: CapitalPlanItem,
    *,
    path: str,
    first_path_by_id: dict[str, str],
) -> list[BusinessPlanValidationIssue]:
    """One capital item, fields in declared order."""

    issues = _validate_item_id(
        item.item_id, path=f"{path}.item_id", first_path_by_id=first_path_by_id
    )
    issues += _validate_text(
        item.description,
        path=f"{path}.description",
        label="description",
        empty_code=BusinessPlanIssueCode.EMPTY_DESCRIPTION,
    )
    issues += _validate_category(
        item.category,
        path=f"{path}.category",
        category_type=CapitalItemCategory,
    )

    month = item.month
    if not _is_whole_number(month):
        issues.append(
            _issue(
                BusinessPlanIssueCode.NON_WHOLE_NUMBER_MONTH,
                f"{path}.month",
                f"month must be a whole-number model-month index; got "
                f"{month!r}.",
            )
        )
    elif month < 0:
        issues.append(
            _issue(
                BusinessPlanIssueCode.MONTH_OUT_OF_DOMAIN,
                f"{path}.month",
                f"month {month!r} must be greater than or equal to 0; month 0 "
                "is closing.",
            )
        )

    issues += _validate_dollars(item.amount, path=f"{path}.amount", label="amount")
    return issues


def _validate_owner_expense_item(
    item: OwnerExpenseItem,
    *,
    path: str,
    first_path_by_id: dict[str, str],
) -> list[BusinessPlanValidationIssue]:
    """One owner-expense item, fields in declared order."""

    issues = _validate_item_id(
        item.item_id, path=f"{path}.item_id", first_path_by_id=first_path_by_id
    )
    issues += _validate_text(
        item.description,
        path=f"{path}.description",
        label="description",
        empty_code=BusinessPlanIssueCode.EMPTY_DESCRIPTION,
    )
    issues += _validate_category(
        item.category,
        path=f"{path}.category",
        category_type=OwnerExpenseCategory,
    )
    issues += _validate_dollars(
        item.annual_amount, path=f"{path}.annual_amount", label="annual_amount"
    )

    first_year = item.first_year
    first_year_valid = False
    if not _is_whole_number(first_year):
        issues.append(
            _issue(
                BusinessPlanIssueCode.NON_WHOLE_NUMBER_YEAR,
                f"{path}.first_year",
                f"first_year must be a whole-number hold year; got "
                f"{first_year!r}.",
            )
        )
    elif first_year < 1:
        issues.append(
            _issue(
                BusinessPlanIssueCode.FIRST_YEAR_OUT_OF_DOMAIN,
                f"{path}.first_year",
                f"first_year {first_year!r} must be greater than or equal to 1; "
                "there is no Year-0 owner expense.",
            )
        )
    else:
        first_year_valid = True

    last_year = item.last_year
    if last_year is not None:
        if not _is_whole_number(last_year):
            issues.append(
                _issue(
                    BusinessPlanIssueCode.NON_WHOLE_NUMBER_YEAR,
                    f"{path}.last_year",
                    f"last_year must be a whole-number hold year or None; got "
                    f"{last_year!r}.",
                )
            )
        elif first_year_valid and last_year < first_year:
            issues.append(
                _issue(
                    BusinessPlanIssueCode.LAST_YEAR_BEFORE_FIRST_YEAR,
                    f"{path}.last_year",
                    f"last_year {last_year!r} must be greater than or equal to "
                    f"first_year {first_year!r}.",
                )
            )

    return issues


def _validate_collection(
    items: object,
    *,
    path: str,
    item_type: type,
    validate_item: Callable[..., list[BusinessPlanValidationIssue]],
    first_path_by_id: dict[str, str],
) -> list[BusinessPlanValidationIssue]:
    """A tuple of ``item_type``. A list is refused rather than copied: the
    plan is an immutable contract, and an item of the other kind in the wrong
    collection is refused rather than reinterpreted."""

    if not isinstance(items, tuple):
        return [
            _issue(
                BusinessPlanIssueCode.MALFORMED_FIELD,
                path,
                f"{path} must be a tuple of {item_type.__name__}; got "
                f"{type(items).__name__}.",
            )
        ]

    issues: list[BusinessPlanValidationIssue] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if not isinstance(item, item_type):
            issues.append(
                _issue(
                    BusinessPlanIssueCode.MALFORMED_FIELD,
                    item_path,
                    f"{item_path} must be a {item_type.__name__}; got "
                    f"{type(item).__name__}.",
                )
            )
            continue
        issues += validate_item(
            item, path=item_path, first_path_by_id=first_path_by_id
        )
    return issues


# =============================================================================
# Entry points
# =============================================================================


def validate_business_plan(
    business_plan: BusinessPlan,
) -> BusinessPlanValidationResult:
    """Validate one Business Plan, deterministically.

    Returns a ``BusinessPlanValidationResult`` whether or not issues were
    found; ``require_valid_business_plan`` is the variant that raises.

    **Issue ordering** is fixed and reproducible: capital items in declared
    order, then owner-expense items in declared order, each item's fields in
    declared field order. Item IDs are checked in that same single pass over
    one shared namespace, so a cross-type duplicate is reported at the
    owner-expense item that repeats a capital item's ID. Nothing here iterates
    a ``set`` or ``dict`` to produce output, so repeated runs emit identical
    sequences.

    The hold period is not an input: every rule here holds at any hold, and
    owner-expense years beyond the hold are valid (Section 5).
    """

    if not isinstance(business_plan, BusinessPlan):
        return BusinessPlanValidationResult(
            issues=(
                _issue(
                    BusinessPlanIssueCode.MALFORMED_FIELD,
                    "business_plan",
                    "business_plan must be a BusinessPlan; got "
                    f"{type(business_plan).__name__}.",
                ),
            )
        )

    first_path_by_id: dict[str, str] = {}
    issues = _validate_collection(
        business_plan.capital_items,
        path="capital_items",
        item_type=CapitalPlanItem,
        validate_item=_validate_capital_item,
        first_path_by_id=first_path_by_id,
    )
    issues += _validate_collection(
        business_plan.owner_expense_items,
        path="owner_expense_items",
        item_type=OwnerExpenseItem,
        validate_item=_validate_owner_expense_item,
        first_path_by_id=first_path_by_id,
    )
    return BusinessPlanValidationResult(issues=tuple(issues))


def require_valid_business_plan(
    business_plan: BusinessPlan,
) -> BusinessPlanValidationResult:
    """Validate and raise ``BusinessPlanValidationError`` on any issue."""

    result = validate_business_plan(business_plan)
    if result.issues:
        raise BusinessPlanValidationError(result)
    return result
