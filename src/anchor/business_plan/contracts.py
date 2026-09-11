"""Phase 6 Gate D6.1 -- Business Plan contracts.

Restates ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 3 and
5; that document governs on any discrepancy. Like ``anchor.engine.contracts``
and ``anchor.leasing.contracts``, this module performs no calculation and no
I/O of its own -- it only describes the shape of a deal's Business Plan.

These are **input** contracts, and they follow the repository's input-contract
precedent (``Lease``, ``Suite``, ``AcquisitionInputs``): plain frozen records
that do not validate themselves. Every rule lives in
``anchor.business_plan.validation``, which reports all issues at once, in a
deterministic order, with a path a future review UI can anchor a row against.
Nothing is coerced, stripped or defaulted on construction: an invalid value is
kept exactly as supplied so validation can name it.

The Business Plan is deliberately **separate** from ``AcquisitionTerms``, from
every operating-mode input and from the Lease-Level leasing contracts
(Section 1). It does not touch ``AcquisitionTerms.annual_capex_reserve`` or
TI / LC, which stay the other two capital channels (Section 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapitalItemCategory(StrEnum):
    """What a Capital Plan item is for (Section 3, decision D4).

    **Reporting metadata only.** No category alters any financial
    calculation, and nothing may branch on one to do so.

    ``CONTINGENCY``, ``RECURRING_REPLACEMENT``, ``RESERVE``, ``TI`` and ``LC``
    are deliberately **not** members. Their absence is structural double-count
    protection (Section 20): the recurring reserve and leasing capital already
    have their own channels, and a contingency reserve is out of D6 scope.
    """

    VALUE_ADD_RENOVATION = "value_add_renovation"
    DEFERRED_MAINTENANCE = "deferred_maintenance"
    BUILDING_SYSTEMS = "building_systems"
    EXTERIOR_COMMON_AREA = "exterior_common_area"
    OTHER = "other"


class OwnerExpenseCategory(StrEnum):
    """What an owner expense is for (Section 5, decision D8).

    **Reporting metadata only.** No category alters any financial
    calculation.

    The property management fee is deliberately **not** a member: it stays a
    property operating expense above NOI and must not be duplicated here.
    """

    ASSET_MANAGEMENT = "asset_management"
    LEGAL_PARTNERSHIP = "legal_partnership"
    OTHER = "other"


class OwnerExpenseHoldTreatment(StrEnum):
    """How an owner-expense item's scheduled years relate to the current hold
    (Section 5; the reporting contract Section 25 leaves to D6.1).

    **Reporting only.** It carries no financial effect beyond the active-years
    rule, and it is deliberately not a field of the engine's
    ``OwnerCapitalSchedule``.

    - ``FULLY_INSIDE_HOLD`` -- every scheduled year is a hold year.
    - ``PARTIALLY_OUTSIDE_HOLD`` -- some scheduled years are hold years and an
      **explicit** ``last_year`` schedules further years after the hold.
    - ``FULLY_OUTSIDE_HOLD`` -- no scheduled year is a hold year, so the item
      has no financial effect at this hold period.

    ``last_year = None`` means "through the current hold", not "forever", so a
    ``None``-ended item that begins within the hold is ``FULLY_INSIDE_HOLD``.
    It is never reported as partially outside merely because the expense might
    conceptually continue after a sale.
    """

    FULLY_INSIDE_HOLD = "fully_inside_hold"
    PARTIALLY_OUTSIDE_HOLD = "partially_outside_hold"
    FULLY_OUTSIDE_HOLD = "fully_outside_hold"


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalPlanItem:
    """One scheduled, one-time project-capital expenditure (Section 3).

    ``item_id`` is stable, opaque and nonempty. It carries no financial
    meaning, need not be a UUID, and shares **one** namespace with every
    ``OwnerExpenseItem`` in the same Business Plan (decision D17).

    ``description`` is required and nonempty; it serves reporting and audit.

    ``category`` is reporting metadata only.

    ``month`` is a canonical model-month index (Section 4), an integer
    ``>= 0`` with no maximum: ``0`` is closing, ``1..12H`` falls in hold year
    ``((month - 1) // 12) + 1``, and anything later is post-hold capital. A
    model month is an index, not a calendar date.

    ``amount`` is nominal dollars, finite and ``>= 0``. Zero is valid -- an
    analyst may hold a placeholder line while editing.

    There is deliberately no recurrence flag, status, certainty, notes, draw
    schedule, escalation or funding source (Section 3, "Not in D6").
    """

    item_id: str
    description: str
    category: CapitalItemCategory
    month: int
    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerExpenseItem:
    """One fixed nominal annual owner-level expense (Section 5).

    ``item_id`` follows the ``CapitalPlanItem.item_id`` rules, in the same
    shared namespace.

    ``annual_amount`` is fixed nominal dollars per active hold year, finite
    and ``>= 0``. It does not grow and is not a percentage of anything.

    ``first_year`` is an integer hold year ``>= 1``: there is no Year-0 owner
    expense, because closing-time costs belong to closing economics.

    ``last_year`` is an integer hold year ``>= first_year``, or ``None``.
    ``None`` means "through the current underwriting hold period" -- **not**
    forever -- so changing the hold period re-resolves it. Years beyond the
    hold are accepted and have no financial effect.
    """

    item_id: str
    description: str
    category: OwnerExpenseCategory
    annual_amount: float
    first_year: int
    last_year: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BusinessPlan:
    """A deal's Business Plan: its Capital Plan and its Owner Expense Plan.

    Mode-agnostic: Quick, Detailed and Lease-Level deals all carry the same
    contract and resolve it through the same resolver (Section 13).

    Both collections are immutable tuples defaulting to empty. The empty plan,
    ``BusinessPlan()``, is a valid first-class state that resolves to an
    all-zero schedule.

    Item order carries no financial meaning: two plans holding the same items
    in different orders resolve to exactly equal schedules.
    """

    capital_items: tuple[CapitalPlanItem, ...] = ()
    owner_expense_items: tuple[OwnerExpenseItem, ...] = ()
