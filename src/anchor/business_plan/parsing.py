"""Phase 6 Gate D6.5 -- the Business Plan wire parser.

Turns an untrusted, JSON-decoded ``business_plan`` request value into the D6.1
``BusinessPlan`` contract and hands it to the one validation authority,
``require_valid_business_plan``. It is the Business Plan counterpart of
``anchor.leasing.parsing``: structure is this module's question, every domain
rule stays in ``anchor.business_plan.validation`` and is not restated here.

**The wire shape is the contract's own shape** -- the same field names, with
each category spelled as its enum token::

    {
      "capital_items": [
        {"item_id", "description", "category", "month", "amount"}, ...
      ],
      "owner_expense_items": [
        {"item_id", "description", "category", "annual_amount",
         "first_year", "last_year"}, ...
      ]
    }

It is exactly what a saved deal's ``business_plan`` serialises to, so a
response can be sent back unchanged.

**Absent means empty.** ``None`` -- the key absent or JSON ``null`` -- is
``BusinessPlan()``, and so is ``{}``: both collections default to empty and
``last_year`` defaults to ``None``, as they do on the contract. Every other
field is required.

**Type reconstruction, not coercion.** A category token becomes its member,
and a whole-number dollar amount becomes the ``float`` every other Anchor wire
parser produces, so a plan fingerprints identically whether it arrived as
``250000`` or ``250000.0`` and after it round-trips through a ``REAL`` column.
Nothing else is converted: a month or year that is not an integer, a boolean,
a string or a non-finite amount is handed to the validator exactly as sent so
it can name it.

A structural problem -- a value that is not an object or an array, a missing
or unknown field -- is reported as a ``MALFORMED_FIELD`` issue through the same
``BusinessPlanValidationError`` the validator raises, so a caller handles one
refusal with one issue shape. Paths are relative to the plan
(``capital_items[2].month``), exactly as the validator's are.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum

from .contracts import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from .validation import (
    BusinessPlanIssueCode,
    BusinessPlanValidationError,
    BusinessPlanValidationIssue,
    BusinessPlanValidationResult,
    require_valid_business_plan,
)

_CAPITAL_FIELDS = ("item_id", "description", "category", "month", "amount")
_OWNER_EXPENSE_FIELDS = (
    "item_id",
    "description",
    "category",
    "annual_amount",
    "first_year",
    "last_year",
)
#: Fields the contract itself defaults; everything else is required.
_OPTIONAL_OWNER_EXPENSE_FIELDS = frozenset({"last_year"})
_PLAN_FIELDS = ("capital_items", "owner_expense_items")


def _malformed(path: str, message: str) -> BusinessPlanValidationIssue:
    return BusinessPlanValidationIssue(
        code=BusinessPlanIssueCode.MALFORMED_FIELD, path=path, message=message
    )


def _category(value: object, category_type: type[StrEnum]) -> object:
    """The member whose token ``value`` is, or ``value`` unchanged so the
    validator reports it as an unsupported category."""

    if isinstance(value, str):
        for member in category_type:
            if member.value == value:
                return member
    return value


def _dollars(
    value: object, path: str, issues: list[BusinessPlanValidationIssue]
) -> object:
    """A whole-number amount as the ``float`` it denotes; anything else
    unchanged for the validator."""

    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return float(value)
        except OverflowError:
            issues.append(
                BusinessPlanValidationIssue(
                    code=BusinessPlanIssueCode.NON_FINITE_VALUE,
                    path=path,
                    message=f"{path.rsplit('.', 1)[-1]} is too large to be a "
                    "finite number.",
                )
            )
    return value


def _fields(
    raw: object,
    *,
    path: str,
    names: tuple[str, ...],
    optional: frozenset[str],
    issues: list[BusinessPlanValidationIssue],
) -> dict[str, object] | None:
    """The object at ``path`` as a field mapping, or ``None`` after reporting
    why it is not one."""

    if not isinstance(raw, Mapping):
        issues.append(_malformed(path, f"{path} must be an object."))
        return None

    found = len(issues)
    for key in raw:
        if key not in names:
            issues.append(_malformed(f"{path}.{key}", f"{key!r} is not a known field."))
    for name in names:
        if name not in raw and name not in optional:
            issues.append(_malformed(f"{path}.{name}", f"{name!r} is required."))
    if len(issues) > found:
        return None
    return {name: raw[name] for name in names if name in raw}


def _capital_item(
    raw: object, path: str, issues: list[BusinessPlanValidationIssue]
) -> CapitalPlanItem | None:
    fields = _fields(
        raw, path=path, names=_CAPITAL_FIELDS, optional=frozenset(), issues=issues
    )
    if fields is None:
        return None
    return CapitalPlanItem(
        item_id=fields["item_id"],  # type: ignore[arg-type]
        description=fields["description"],  # type: ignore[arg-type]
        category=_category(fields["category"], CapitalItemCategory),  # type: ignore[arg-type]
        month=fields["month"],  # type: ignore[arg-type]
        amount=_dollars(fields["amount"], f"{path}.amount", issues),  # type: ignore[arg-type]
    )


def _owner_expense_item(
    raw: object, path: str, issues: list[BusinessPlanValidationIssue]
) -> OwnerExpenseItem | None:
    fields = _fields(
        raw,
        path=path,
        names=_OWNER_EXPENSE_FIELDS,
        optional=_OPTIONAL_OWNER_EXPENSE_FIELDS,
        issues=issues,
    )
    if fields is None:
        return None
    return OwnerExpenseItem(
        item_id=fields["item_id"],  # type: ignore[arg-type]
        description=fields["description"],  # type: ignore[arg-type]
        category=_category(fields["category"], OwnerExpenseCategory),  # type: ignore[arg-type]
        annual_amount=_dollars(  # type: ignore[arg-type]
            fields["annual_amount"], f"{path}.annual_amount", issues
        ),
        first_year=fields["first_year"],  # type: ignore[arg-type]
        last_year=fields.get("last_year"),  # type: ignore[arg-type]
    )


def _collection(
    raw: object,
    *,
    path: str,
    parse_item: Callable[[object, str, list[BusinessPlanValidationIssue]], object],
    issues: list[BusinessPlanValidationIssue],
) -> tuple:
    if not isinstance(raw, (list, tuple)):
        issues.append(_malformed(path, f"{path} must be an array."))
        return ()
    return tuple(
        item
        for index, element in enumerate(raw)
        if (item := parse_item(element, f"{path}[{index}]", issues)) is not None
    )


def parse_business_plan(payload: object) -> BusinessPlan:
    """Parse one request's ``business_plan`` value and validate it.

    Returns the validated ``BusinessPlan``. Raises
    ``BusinessPlanValidationError`` carrying every structural issue, or -- when
    the structure is sound -- every issue the validation authority finds.
    """

    if payload is None:
        return BusinessPlan()

    issues: list[BusinessPlanValidationIssue] = []
    if not isinstance(payload, Mapping):
        issues.append(_malformed("business_plan", "business_plan must be an object."))
        raise BusinessPlanValidationError(BusinessPlanValidationResult(issues=tuple(issues)))

    for key in payload:
        if key not in _PLAN_FIELDS:
            issues.append(_malformed(str(key), f"{key!r} is not a known field."))

    capital_items = _collection(
        payload.get("capital_items", ()),
        path="capital_items",
        parse_item=_capital_item,
        issues=issues,
    )
    owner_expense_items = _collection(
        payload.get("owner_expense_items", ()),
        path="owner_expense_items",
        parse_item=_owner_expense_item,
        issues=issues,
    )
    if issues:
        raise BusinessPlanValidationError(BusinessPlanValidationResult(issues=tuple(issues)))

    business_plan = BusinessPlan(
        capital_items=capital_items,  # type: ignore[arg-type]
        owner_expense_items=owner_expense_items,  # type: ignore[arg-type]
    )
    require_valid_business_plan(business_plan)
    return business_plan
