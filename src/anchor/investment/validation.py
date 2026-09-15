"""Phase 7 Gate P7.6 -- the Investment-level validation authority.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
9.1 (CON-1), 10 (BP-7) and 11 (PP-2 to PP-4, TC-1 to TC-5); that document
governs on any discrepancy. Pure: no I/O, no clock, no randomness, and no
knowledge of storage, routes or the engine.

Two layers, as for Scenarios and Strategies:

- **The Investment's own inputs** (``validate_investment_inputs``): its name,
  transaction price, Unit memberships, Investment-level Business Plan and
  transaction costs -- what may be stored. The Business Plan is judged by the
  one D6 validator, never restated.
- **A variant's Unit economics** (``validate_variant_economics``): the common
  timeline (CON-1) and the price allocation (PP-2), over the Units' *resolved*
  inputs. The Base inputs, a Strategy and a Scenario can each change a Unit's
  hold or price, so this is asked of every variant, never only on save.

Every function returns ``()`` for valid input and never repairs, rescales,
rounds, pads, truncates or reorders anything. Issue order is deterministic and
never depends on how a collection was stored or displayed.

**The allocation rule (PP-2, Q6).** ``|sum of allocated Unit prices -
transaction price| <= $0.01``, with the Units taken in ascending ``unit_id``
order (CON-3). The comparison is made on the **wire dollar values** exactly:
each price is read as the decimal it was written as (the shortest decimal that
round-trips its float) and the difference is computed in exact decimal
arithmetic. A binary floating-point difference would refuse ``$100,000.01``
against ``$100,000.00`` (their float difference is ``0.0100000000093``) while
accepting the same one-cent gap at ``$1,000,000``; the ratified rule is about
cents, not about the spacing of binary floats. This is a validity predicate,
never a financial figure: the consolidated purchase price stays the float
canonical sum the Unit engines ran with.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import isfinite

from ..business_plan import BusinessPlan, validate_business_plan
from ..contracts import OperatingMode
from .contracts import (
    ALLOCATION_TOLERANCE,
    SUPPORTED_ACQUISITION_MONTH,
    SUPPORTED_TRANSACTION_COST_MONTH,
    InvestmentIssue,
    InvestmentIssueCode,
    InvestmentTransactionCost,
    InvestmentUnitMembership,
    TransactionCostCategory,
    UnitKind,
)

_MAX_SAFE_REPR_LENGTH = 200


def _safe_repr(value: object) -> str:
    try:
        representation = repr(value)
    except Exception:
        return f"<{type(value).__qualname__}>"
    if len(representation) > _MAX_SAFE_REPR_LENGTH:
        return f"<{type(value).__qualname__}>"
    return representation


def _is_nonblank_text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_finite_number(value: object) -> bool:
    """A finite ``int`` or ``float``; ``bool`` is not a number here."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(float(value))
    except OverflowError:
        return False


def _is_whole_number(value: object) -> bool:
    """An ``int`` that is not a ``bool``."""

    return isinstance(value, int) and not isinstance(value, bool)


def _issue(
    code: InvestmentIssueCode,
    message: str,
    *,
    unit_id: str | None = None,
    field: str | None = None,
    source_code: str | None = None,
) -> InvestmentIssue:
    return InvestmentIssue(
        code=code, message=message, unit_id=unit_id, field=field, source_code=source_code
    )


# =============================================================================
# The Investment's own inputs
# =============================================================================


def validate_investment_details(*, name: object, transaction_price: object) -> tuple[InvestmentIssue, ...]:
    """A visible Investment's name (required, nonblank) and transaction price
    (a finite number greater than zero). The price is validation and reporting
    only: it never enters a cash flow (PP-3)."""

    issues: list[InvestmentIssue] = []
    if not _is_nonblank_text(name):
        issues.append(
            _issue(
                InvestmentIssueCode.INVALID_NAME,
                f"name {_safe_repr(name)} must be a nonblank string.",
                field="name",
            )
        )
    if not _is_finite_number(transaction_price) or float(transaction_price) <= 0.0:  # type: ignore[arg-type]
        issues.append(
            _issue(
                InvestmentIssueCode.INVALID_TRANSACTION_PRICE,
                f"transaction_price {_safe_repr(transaction_price)} must be a finite number "
                "greater than 0.",
                field="transaction_price",
            )
        )
    return tuple(issues)


def _membership_issues(
    membership: InvestmentUnitMembership, unit_id: str, where: str
) -> list[InvestmentIssue]:
    issues: list[InvestmentIssue] = []
    if not _is_whole_number(membership.ordinal) or membership.ordinal < 0:
        issues.append(
            _issue(
                InvestmentIssueCode.INVALID_ORDINAL,
                f"ordinal {_safe_repr(membership.ordinal)} must be a whole number >= 0; it "
                "orders presentation only.",
                unit_id=unit_id,
                field=f"{where}.ordinal",
            )
        )
    if membership.label is not None and not _is_nonblank_text(membership.label):
        issues.append(
            _issue(
                InvestmentIssueCode.INVALID_LABEL,
                f"label {_safe_repr(membership.label)} must be a nonblank string or None.",
                unit_id=unit_id,
                field=f"{where}.label",
            )
        )
    if not isinstance(membership.unit_kind, UnitKind):
        issues.append(
            _issue(
                InvestmentIssueCode.UNKNOWN_UNIT_KIND,
                f"unit_kind {_safe_repr(membership.unit_kind)} is not one of: "
                f"{', '.join(kind.value for kind in UnitKind)}.",
                unit_id=unit_id,
                field=f"{where}.unit_kind",
            )
        )
    acquisition_month = membership.acquisition_month
    if not _is_whole_number(acquisition_month) or acquisition_month < 0:
        issues.append(
            _issue(
                InvestmentIssueCode.INVALID_ACQUISITION_MONTH,
                f"acquisition_month {_safe_repr(acquisition_month)} must be a whole model "
                "month >= 0.",
                unit_id=unit_id,
                field=f"{where}.acquisition_month",
            )
        )
    elif acquisition_month != SUPPORTED_ACQUISITION_MONTH:
        issues.append(
            _issue(
                InvestmentIssueCode.UNSUPPORTED_ACQUISITION_MONTH,
                f"acquisition_month {acquisition_month} is not supported: every Unit closes "
                "at the Investment's closing (model month 0). Staggered acquisitions are "
                "not modelled; the Unit is refused, never shifted.",
                unit_id=unit_id,
                field=f"{where}.acquisition_month",
            )
        )
    disposition_month = membership.disposition_month
    if disposition_month is not None:
        if not _is_whole_number(disposition_month) or disposition_month < 1:
            issues.append(
                _issue(
                    InvestmentIssueCode.INVALID_DISPOSITION_MONTH,
                    f"disposition_month {_safe_repr(disposition_month)} must be a whole model "
                    "month >= 1, or None.",
                    unit_id=unit_id,
                    field=f"{where}.disposition_month",
                )
            )
        else:
            issues.append(
                _issue(
                    InvestmentIssueCode.UNSUPPORTED_DISPOSITION_MONTH,
                    f"disposition_month {disposition_month} is not supported: every Unit exits "
                    "through its own Deal's hold at the common Investment horizon "
                    "(disposition_month None). A Unit sale before the horizon is not "
                    "modelled; nothing is padded or truncated.",
                    unit_id=unit_id,
                    field=f"{where}.disposition_month",
                )
            )
    return issues


def validate_unit_memberships(memberships: object) -> tuple[InvestmentIssue, ...]:
    """The Unit memberships of a visible Investment: at least one; each an
    ``InvestmentUnitMembership`` naming a Unit exactly once; each with a valid
    ordinal, label and kind; and each with the P7.6 CON-1 timing
    (``acquisition_month = 0``, ``disposition_month = None``).

    Whether each Unit is a saved, standalone Deal is a fact of storage, checked
    by the store in the same transaction as the write."""

    if not isinstance(memberships, tuple):
        return (
            _issue(
                InvestmentIssueCode.INVALID_UNITS,
                f"units must be a tuple of InvestmentUnitMembership; got "
                f"{type(memberships).__qualname__}.",
                field="units",
            ),
        )
    if not memberships:
        return (
            _issue(
                InvestmentIssueCode.NO_UNITS,
                "A visible Investment holds at least one Unit.",
                field="units",
            ),
        )

    issues: list[InvestmentIssue] = []
    for index, membership in enumerate(memberships):
        if not isinstance(membership, InvestmentUnitMembership):
            issues.append(
                _issue(
                    InvestmentIssueCode.INVALID_UNITS,
                    f"units[{index}] must be an InvestmentUnitMembership; got "
                    f"{type(membership).__qualname__}.",
                    field=f"units[{index}]",
                )
            )
    typed = [
        (index, membership)
        for index, membership in enumerate(memberships)
        if isinstance(membership, InvestmentUnitMembership)
    ]
    for index, membership in typed:
        if not _is_nonblank_text(membership.unit_id):
            issues.append(
                _issue(
                    InvestmentIssueCode.INVALID_UNIT_ID,
                    f"units[{index}].unit_id {_safe_repr(membership.unit_id)} must be a "
                    "nonblank string naming a saved Deal.",
                    field=f"units[{index}].unit_id",
                )
            )

    by_unit: dict[str, list[tuple[int, InvestmentUnitMembership]]] = {}
    for index, membership in typed:
        if _is_nonblank_text(membership.unit_id):
            by_unit.setdefault(membership.unit_id, []).append((index, membership))
    for unit_id in sorted(by_unit):
        occurrences = by_unit[unit_id]
        if len(occurrences) > 1:
            issues.append(
                _issue(
                    InvestmentIssueCode.DUPLICATE_UNIT,
                    f"Unit {_safe_repr(unit_id)} is listed {len(occurrences)} times; a Deal is "
                    "a Unit of an Investment at most once.",
                    unit_id=unit_id,
                    field="units",
                )
            )
            continue
        index, membership = occurrences[0]
        issues.extend(_membership_issues(membership, unit_id, f"units[{index}]"))
    return tuple(issues)


def validate_transaction_costs(costs: object) -> tuple[InvestmentIssue, ...]:
    """The Investment's transaction costs (TC-1, TC-2): each a nonblank
    ``cost_id`` used once, a nonblank description, a known category, a finite
    amount ``>= 0`` and a whole model month -- which P7.6 accepts only at
    closing (month 0). Costs are reported in ``cost_id`` order."""

    if not isinstance(costs, tuple):
        return (
            _issue(
                InvestmentIssueCode.INVALID_TRANSACTION_COSTS,
                "transaction_costs must be a tuple of InvestmentTransactionCost; got "
                f"{type(costs).__qualname__}.",
                field="transaction_costs",
            ),
        )

    issues: list[InvestmentIssue] = []
    for index, cost in enumerate(costs):
        if not isinstance(cost, InvestmentTransactionCost):
            issues.append(
                _issue(
                    InvestmentIssueCode.INVALID_TRANSACTION_COSTS,
                    f"transaction_costs[{index}] must be an InvestmentTransactionCost; got "
                    f"{type(cost).__qualname__}.",
                    field=f"transaction_costs[{index}]",
                )
            )
    typed = [
        (index, cost) for index, cost in enumerate(costs) if isinstance(cost, InvestmentTransactionCost)
    ]
    for index, cost in typed:
        if not _is_nonblank_text(cost.cost_id):
            issues.append(
                _issue(
                    InvestmentIssueCode.INVALID_COST_ID,
                    f"transaction_costs[{index}].cost_id {_safe_repr(cost.cost_id)} must be a "
                    "nonblank string.",
                    field=f"transaction_costs[{index}].cost_id",
                )
            )

    by_id: dict[str, list[tuple[int, InvestmentTransactionCost]]] = {}
    for index, cost in typed:
        if _is_nonblank_text(cost.cost_id):
            by_id.setdefault(cost.cost_id, []).append((index, cost))
    for cost_id in sorted(by_id):
        occurrences = by_id[cost_id]
        if len(occurrences) > 1:
            issues.append(
                _issue(
                    InvestmentIssueCode.DUPLICATE_COST_ID,
                    f"cost_id {_safe_repr(cost_id)} is used {len(occurrences)} times; each "
                    "transaction cost has its own id.",
                    field="transaction_costs",
                )
            )
            continue
        index, cost = occurrences[0]
        where = f"transaction_costs[{index}]"
        if not _is_nonblank_text(cost.description):
            issues.append(
                _issue(
                    InvestmentIssueCode.INVALID_COST_DESCRIPTION,
                    f"{cost_id}: description {_safe_repr(cost.description)} must be a "
                    "nonblank string.",
                    field=f"{where}.description",
                )
            )
        if not isinstance(cost.category, TransactionCostCategory):
            issues.append(
                _issue(
                    InvestmentIssueCode.UNKNOWN_COST_CATEGORY,
                    f"{cost_id}: category {_safe_repr(cost.category)} is not one of: "
                    f"{', '.join(category.value for category in TransactionCostCategory)}.",
                    field=f"{where}.category",
                )
            )
        if not _is_finite_number(cost.amount) or float(cost.amount) < 0.0:
            issues.append(
                _issue(
                    InvestmentIssueCode.INVALID_COST_AMOUNT,
                    f"{cost_id}: amount {_safe_repr(cost.amount)} must be finite nominal "
                    "dollars >= 0.",
                    field=f"{where}.amount",
                )
            )
        if not _is_whole_number(cost.model_month) or cost.model_month < 0:
            issues.append(
                _issue(
                    InvestmentIssueCode.INVALID_COST_MONTH,
                    f"{cost_id}: model_month {_safe_repr(cost.model_month)} must be a whole "
                    "model month >= 0.",
                    field=f"{where}.model_month",
                )
            )
        elif cost.model_month != SUPPORTED_TRANSACTION_COST_MONTH:
            issues.append(
                _issue(
                    InvestmentIssueCode.UNSUPPORTED_COST_MONTH,
                    f"{cost_id}: model_month {cost.model_month} is not supported: an "
                    "Investment transaction cost is a closing use (model month 0).",
                    field=f"{where}.model_month",
                )
            )
    return tuple(issues)


def validate_investment_business_plan(business_plan: BusinessPlan) -> tuple[InvestmentIssue, ...]:
    """The Investment-level Business Plan, judged by the one D6 validator with
    its own item-ID namespace (BP-7). Each D6 finding is reported with its D6
    code and wording."""

    result = validate_business_plan(business_plan)
    return tuple(
        _issue(
            InvestmentIssueCode.INVALID_BUSINESS_PLAN,
            issue.message,
            field=f"business_plan.{issue.path}" if issue.path != "business_plan" else "business_plan",
            source_code=issue.code.value,
        )
        for issue in result.issues
    )


def validate_investment_inputs(
    *,
    name: object,
    transaction_price: object,
    memberships: object,
    business_plan: BusinessPlan,
    transaction_costs: object,
) -> tuple[InvestmentIssue, ...]:
    """Every issue in a visible Investment's own inputs, in one deterministic
    order: details, Units, Business Plan, transaction costs."""

    return (
        *validate_investment_details(name=name, transaction_price=transaction_price),
        *validate_unit_memberships(memberships),
        *validate_investment_business_plan(business_plan),
        *validate_transaction_costs(transaction_costs),
    )


# =============================================================================
# A variant's Unit economics -- CON-1 and PP-2
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitEconomicFacts:
    """The resolved facts of one Unit that the Investment-level rules read: its
    allocated purchase price, its hold, and -- for a Lease-Level Unit -- its
    calendar anchor. ``analysis_start_date`` is ``None`` for Quick and Detailed,
    which align by model-year index and have no calendar date to fabricate."""

    unit_id: str
    operating_mode: OperatingMode
    purchase_price: float
    hold_period: int
    analysis_start_date: date | None


def _wire_dollars(value: float) -> Decimal:
    """``value`` as the decimal it was written as: the shortest decimal string
    that round-trips the float."""

    return Decimal(repr(float(value)))


def allocation_variance(*, unit_prices: Iterable[tuple[str, float]], transaction_price: float) -> Decimal:
    """The exact decimal difference between the sum of the allocated Unit
    prices, taken in ascending ``unit_id`` order, and the transaction price.
    Never rounded."""

    total = Decimal(0)
    for _, price in sorted(unit_prices, key=lambda entry: entry[0]):
        total += _wire_dollars(price)
    return total - _wire_dollars(transaction_price)


def validate_allocation(
    *, unit_prices: Iterable[tuple[str, float]], transaction_price: float
) -> tuple[InvestmentIssue, ...]:
    """PP-2: the allocated Unit prices must reconcile to the transaction price
    within ``ALLOCATION_TOLERANCE``. A larger difference is refused, never
    rescaled, spread, pushed into one Unit or rounded away; nothing here
    allocates."""

    prices = tuple(unit_prices)
    variance = allocation_variance(unit_prices=prices, transaction_price=transaction_price)
    if abs(variance) <= Decimal(ALLOCATION_TOLERANCE):
        return ()
    listed = ", ".join(f"{unit_id}: {price!r}" for unit_id, price in sorted(prices, key=lambda e: e[0]))
    return (
        _issue(
            InvestmentIssueCode.ALLOCATION_MISMATCH,
            f"The Units' allocated purchase prices ({listed}) sum to "
            f"{sum((_wire_dollars(price) for _, price in prices), Decimal(0))}, which differs "
            f"from the transaction price {_wire_dollars(transaction_price)} by {variance}; "
            f"they must reconcile within ${ALLOCATION_TOLERANCE}. Nothing is rescaled or "
            "reallocated: change a Unit's purchase price or the transaction price.",
            field="transaction_price",
        ),
    )


def validate_common_timeline(facts: Iterable[UnitEconomicFacts]) -> tuple[InvestmentIssue, ...]:
    """CON-1: every Unit shares one hold period, and every Lease-Level Unit one
    ``analysis_start_date``. A mismatch is refused, never padded, truncated or
    aligned by guess. Quick and Detailed Units align by model-year index."""

    ordered = sorted(facts, key=lambda fact: fact.unit_id)
    issues: list[InvestmentIssue] = []
    if len({fact.hold_period for fact in ordered}) > 1:
        listed = ", ".join(f"{fact.unit_id}: {fact.hold_period} years" for fact in ordered)
        issues.append(
            _issue(
                InvestmentIssueCode.HOLD_PERIOD_MISMATCH,
                f"The Units' hold periods differ ({listed}). Every Unit of an Investment "
                "shares one hold period; nothing is padded or truncated.",
                field="hold_period",
            )
        )
    anchored = [fact for fact in ordered if fact.analysis_start_date is not None]
    if len({fact.analysis_start_date for fact in anchored}) > 1:
        listed = ", ".join(
            f"{fact.unit_id}: {fact.analysis_start_date.isoformat()}"  # type: ignore[union-attr]
            for fact in anchored
        )
        issues.append(
            _issue(
                InvestmentIssueCode.ANALYSIS_START_DATE_MISMATCH,
                f"The Lease-Level Units' analysis start dates differ ({listed}). Every "
                "Lease-Level Unit of an Investment shares one analysis_start_date.",
                field="property_inputs.analysis_start_date",
            )
        )
    return tuple(issues)


def validate_variant_economics(
    facts: Iterable[UnitEconomicFacts], *, transaction_price: float
) -> tuple[InvestmentIssue, ...]:
    """Every Investment-level rule over one variant's resolved Units: the
    common timeline, then the price allocation."""

    ordered = tuple(sorted(facts, key=lambda fact: fact.unit_id))
    return (
        *validate_common_timeline(ordered),
        *validate_allocation(
            unit_prices=[(fact.unit_id, fact.purchase_price) for fact in ordered],
            transaction_price=transaction_price,
        ),
    )
