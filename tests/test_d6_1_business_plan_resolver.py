"""Gate D6.1 -- the Business Plan resolver.

Governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 4,
5, 13 and 19. Test oracles U1-U12 from the D6.1 gate specification are named
where they appear. Every expected value is stated literally rather than
recomputed with the resolver's own formula.
"""

from __future__ import annotations

from dataclasses import replace
import math
import random

import pytest

from anchor.business_plan import (
    BusinessPlan,
    BusinessPlanValidationError,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseHoldTreatment,
    OwnerExpenseItem,
    owner_expense_hold_treatments,
    resolve_business_plan,
)
from anchor.engine.contracts import NonFiniteResultError, OwnerCapitalSchedule

INSIDE = OwnerExpenseHoldTreatment.FULLY_INSIDE_HOLD
PARTIAL = OwnerExpenseHoldTreatment.PARTIALLY_OUTSIDE_HOLD
OUTSIDE = OwnerExpenseHoldTreatment.FULLY_OUTSIDE_HOLD


def _capital(item_id: str, month: int, amount: float, **overrides: object) -> CapitalPlanItem:
    values: dict[str, object] = {
        "item_id": item_id,
        "description": f"Capital {item_id}",
        "category": CapitalItemCategory.VALUE_ADD_RENOVATION,
        "month": month,
        "amount": amount,
    }
    values.update(overrides)
    return CapitalPlanItem(**values)  # type: ignore[arg-type]


def _expense(
    item_id: str,
    annual_amount: float,
    first_year: int,
    last_year: int | None = None,
    **overrides: object,
) -> OwnerExpenseItem:
    values: dict[str, object] = {
        "item_id": item_id,
        "description": f"Expense {item_id}",
        "category": OwnerExpenseCategory.ASSET_MANAGEMENT,
        "annual_amount": annual_amount,
        "first_year": first_year,
        "last_year": last_year,
    }
    values.update(overrides)
    return OwnerExpenseItem(**values)  # type: ignore[arg-type]


def _resolve(*, hold_period: int = 5, capital=(), expenses=()) -> OwnerCapitalSchedule:
    return resolve_business_plan(
        BusinessPlan(capital_items=tuple(capital), owner_expense_items=tuple(expenses)),
        hold_period=hold_period,
    )


# =============================================================================
# U1 / U10 -- the neutral plan
# =============================================================================


def test_u1_empty_plan_resolves_to_the_neutral_schedule() -> None:
    schedule = resolve_business_plan(BusinessPlan(), hold_period=5)

    assert schedule == OwnerCapitalSchedule(
        closing_project_capital=0.0,
        project_capital_by_year=(0.0, 0.0, 0.0, 0.0, 0.0),
        owner_expenses_by_year=(0.0, 0.0, 0.0, 0.0, 0.0),
        post_hold_project_capital=0.0,
    )
    for value in (
        schedule.closing_project_capital,
        schedule.post_hold_project_capital,
        *schedule.project_capital_by_year,
        *schedule.owner_expenses_by_year,
    ):
        assert type(value) is float


@pytest.mark.parametrize("hold_period", [1, 2, 7, 30])
def test_empty_plan_has_one_zero_per_hold_year(hold_period: int) -> None:
    schedule = resolve_business_plan(BusinessPlan(), hold_period=hold_period)

    assert schedule.project_capital_by_year == (0.0,) * hold_period
    assert schedule.owner_expenses_by_year == (0.0,) * hold_period


def test_u10_zero_dollar_items_are_accepted_and_neutral() -> None:
    schedule = _resolve(
        capital=[
            _capital("c0", 0, 0.0),
            _capital("c1", 13, 0.0),
            _capital("c2", 61, 0.0),
        ],
        expenses=[_expense("e1", 0.0, 1), _expense("e2", 0.0, 4, 8)],
    )

    assert schedule == resolve_business_plan(BusinessPlan(), hold_period=5)


def test_integer_amounts_resolve_to_float_totals() -> None:
    schedule = _resolve(capital=[_capital("c", 1, 100)], expenses=[_expense("e", 7, 1)])

    assert schedule.project_capital_by_year[0] == 100.0
    assert type(schedule.project_capital_by_year[0]) is float
    assert schedule.owner_expenses_by_year == (7.0, 7.0, 7.0, 7.0, 7.0)


# =============================================================================
# U2 / U9 -- capital month bucketing (Section 4) and post-hold (Section 19)
# =============================================================================


@pytest.mark.parametrize(
    ("month", "closing", "by_year", "post_hold"),
    [
        (0, 100.0, (0.0, 0.0, 0.0, 0.0, 0.0), 0.0),
        (1, 0.0, (100.0, 0.0, 0.0, 0.0, 0.0), 0.0),
        (12, 0.0, (100.0, 0.0, 0.0, 0.0, 0.0), 0.0),
        (13, 0.0, (0.0, 100.0, 0.0, 0.0, 0.0), 0.0),
        (24, 0.0, (0.0, 100.0, 0.0, 0.0, 0.0), 0.0),
        (25, 0.0, (0.0, 0.0, 100.0, 0.0, 0.0), 0.0),
        (49, 0.0, (0.0, 0.0, 0.0, 0.0, 100.0), 0.0),
        (60, 0.0, (0.0, 0.0, 0.0, 0.0, 100.0), 0.0),  # 12H
        (61, 0.0, (0.0, 0.0, 0.0, 0.0, 0.0), 100.0),  # 12H + 1
        (10**12, 0.0, (0.0, 0.0, 0.0, 0.0, 0.0), 100.0),
    ],
    ids=lambda value: str(value) if isinstance(value, int) else None,
)
def test_u2_capital_month_boundaries_at_hold_five(
    month: int, closing: float, by_year: tuple[float, ...], post_hold: float
) -> None:
    schedule = _resolve(capital=[_capital("c", month, 100.0)])

    assert schedule.closing_project_capital == closing
    assert schedule.project_capital_by_year == by_year
    assert schedule.post_hold_project_capital == post_hold
    assert schedule.owner_expenses_by_year == (0.0, 0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("hold_period", "month", "by_year", "post_hold"),
    [
        (1, 12, (100.0,), 0.0),
        (1, 13, (0.0,), 100.0),
        (3, 36, (0.0, 0.0, 100.0), 0.0),
        (3, 37, (0.0, 0.0, 0.0), 100.0),
    ],
)
def test_u2_the_hold_boundary_moves_with_the_hold_period(
    hold_period: int, month: int, by_year: tuple[float, ...], post_hold: float
) -> None:
    schedule = _resolve(hold_period=hold_period, capital=[_capital("c", month, 100.0)])

    assert schedule.project_capital_by_year == by_year
    assert schedule.post_hold_project_capital == post_hold


def test_u9_post_hold_capital_is_disclosed_and_never_enters_a_hold_year() -> None:
    base = _resolve(capital=[_capital("final", 60, 1_000.0)])
    with_post_hold = _resolve(
        capital=[_capital("final", 60, 1_000.0), _capital("after", 61, 1_000_000.0)]
    )

    assert with_post_hold.post_hold_project_capital == 1_000_000.0
    assert with_post_hold.project_capital_by_year == base.project_capital_by_year
    assert with_post_hold.project_capital_by_year == (0.0, 0.0, 0.0, 0.0, 1_000.0)
    assert with_post_hold.closing_project_capital == base.closing_project_capital == 0.0


def test_capital_in_every_bucket_aggregates_per_bucket() -> None:
    schedule = _resolve(
        capital=[
            _capital("t0a", 0, 10.0),
            _capital("t0b", 0, 5.0),
            _capital("y1", 7, 1.0),
            _capital("y2a", 13, 2.0),
            _capital("y2b", 20, 3.0),
            _capital("y5", 60, 4.0),
            _capital("ph1", 61, 100.0),
            _capital("ph2", 500, 200.0),
        ]
    )

    assert schedule == OwnerCapitalSchedule(
        closing_project_capital=15.0,
        project_capital_by_year=(1.0, 5.0, 0.0, 0.0, 4.0),
        owner_expenses_by_year=(0.0, 0.0, 0.0, 0.0, 0.0),
        post_hold_project_capital=300.0,
    )


def test_changing_the_hold_period_reclassifies_capital() -> None:
    plan = BusinessPlan(capital_items=(_capital("c", 61, 50.0),))

    five = resolve_business_plan(plan, hold_period=5)
    six = resolve_business_plan(plan, hold_period=6)

    assert five.post_hold_project_capital == 50.0
    assert six.post_hold_project_capital == 0.0
    assert six.project_capital_by_year == (0.0, 0.0, 0.0, 0.0, 0.0, 50.0)


# =============================================================================
# U5 / U6 / U7 -- owner-expense active years (Section 5, D16)
# =============================================================================


def test_u5_none_last_year_runs_through_the_hold() -> None:
    schedule = _resolve(expenses=[_expense("oe", 100.0, 2, None)])

    assert schedule.owner_expenses_by_year == (0.0, 100.0, 100.0, 100.0, 100.0)
    assert owner_expense_hold_treatments(
        BusinessPlan(owner_expense_items=(_expense("oe", 100.0, 2, None),)),
        hold_period=5,
    ) == (("oe", INSIDE),)


def test_u6_an_explicit_range_past_the_hold_is_clipped() -> None:
    item = _expense("oe", 100.0, 4, 8)
    schedule = _resolve(expenses=[item])

    assert schedule.owner_expenses_by_year == (0.0, 0.0, 0.0, 100.0, 100.0)
    assert owner_expense_hold_treatments(
        BusinessPlan(owner_expense_items=(item,)), hold_period=5
    ) == (("oe", PARTIAL),)


def test_u7_an_item_entirely_after_the_hold_has_no_financial_effect() -> None:
    item = _expense("oe", 100.0, 7, 10)
    schedule = _resolve(expenses=[item])

    assert schedule == resolve_business_plan(BusinessPlan(), hold_period=5)
    assert owner_expense_hold_treatments(
        BusinessPlan(owner_expense_items=(item,)), hold_period=5
    ) == (("oe", OUTSIDE),)


def test_owner_expenses_produce_no_post_hold_dollars() -> None:
    schedule = _resolve(expenses=[_expense("a", 100.0, 4, 8), _expense("b", 100.0, 7, 10)])

    assert schedule.post_hold_project_capital == 0.0
    assert schedule.closing_project_capital == 0.0


@pytest.mark.parametrize(
    ("first_year", "last_year", "expected"),
    [
        (1, None, (100.0, 100.0, 100.0, 100.0, 100.0)),
        (5, None, (0.0, 0.0, 0.0, 0.0, 100.0)),
        (6, None, (0.0, 0.0, 0.0, 0.0, 0.0)),
        (1, 1, (100.0, 0.0, 0.0, 0.0, 0.0)),
        (2, 3, (0.0, 100.0, 100.0, 0.0, 0.0)),
        (5, 5, (0.0, 0.0, 0.0, 0.0, 100.0)),
        (1, 5, (100.0, 100.0, 100.0, 100.0, 100.0)),
        (1, 6, (100.0, 100.0, 100.0, 100.0, 100.0)),
        (5, 6, (0.0, 0.0, 0.0, 0.0, 100.0)),
        (6, 6, (0.0, 0.0, 0.0, 0.0, 0.0)),
    ],
)
def test_owner_expense_active_year_boundaries(
    first_year: int, last_year: int | None, expected: tuple[float, ...]
) -> None:
    schedule = _resolve(expenses=[_expense("oe", 100.0, first_year, last_year)])

    assert schedule.owner_expenses_by_year == expected


@pytest.mark.parametrize(
    ("first_year", "last_year", "treatment"),
    [
        (1, None, INSIDE),
        (5, None, INSIDE),
        (6, None, OUTSIDE),
        (1, 5, INSIDE),
        (5, 5, INSIDE),
        (5, 6, PARTIAL),
        (1, 100, PARTIAL),
        (6, 6, OUTSIDE),
        (7, 10, OUTSIDE),
    ],
)
def test_owner_expense_hold_treatment_boundaries(
    first_year: int, last_year: int | None, treatment: OwnerExpenseHoldTreatment
) -> None:
    plan = BusinessPlan(owner_expense_items=(_expense("oe", 1.0, first_year, last_year),))

    assert owner_expense_hold_treatments(plan, hold_period=5) == (("oe", treatment),)


def test_none_ended_item_is_never_partially_outside_hold_at_any_hold() -> None:
    plan = BusinessPlan(owner_expense_items=(_expense("oe", 1.0, 1, None),))

    for hold_period in range(1, 16):
        assert owner_expense_hold_treatments(plan, hold_period=hold_period) == (
            ("oe", INSIDE),
        )


def test_hold_treatments_follow_declared_order_and_empty_plan_is_empty() -> None:
    plan = BusinessPlan(
        capital_items=(_capital("cap", 1, 1.0),),
        owner_expense_items=(
            _expense("z", 1.0, 7, 9),
            _expense("a", 1.0, 1),
            _expense("m", 1.0, 3, 6),
        ),
    )

    assert owner_expense_hold_treatments(plan, hold_period=5) == (
        ("z", OUTSIDE),
        ("a", INSIDE),
        ("m", PARTIAL),
    )
    assert owner_expense_hold_treatments(BusinessPlan(), hold_period=5) == ()


def test_changing_the_hold_period_re_resolves_owner_expenses() -> None:
    """Section 5: a ``None``-ended item extends through the new hold."""

    plan = BusinessPlan(
        owner_expense_items=(_expense("open", 10.0, 2), _expense("fixed", 1.0, 4, 8))
    )

    assert resolve_business_plan(plan, hold_period=3).owner_expenses_by_year == (
        0.0,
        10.0,
        10.0,
    )
    assert resolve_business_plan(plan, hold_period=7).owner_expenses_by_year == (
        0.0,
        10.0,
        10.0,
        11.0,
        11.0,
        11.0,
        11.0,
    )
    assert owner_expense_hold_treatments(plan, hold_period=8) == (
        ("open", INSIDE),
        ("fixed", INSIDE),
    )


def test_overlapping_owner_expenses_sum_per_year() -> None:
    schedule = _resolve(
        expenses=[
            _expense("a", 100.0, 1),
            _expense("b", 25.0, 2, 3),
            _expense("c", 5.0, 3, 9),
        ]
    )

    assert schedule.owner_expenses_by_year == (100.0, 125.0, 130.0, 105.0, 105.0)


# =============================================================================
# U3 / U4 -- order independence and reporting-metadata invariance
# =============================================================================


def _mixed_items() -> tuple[tuple[CapitalPlanItem, ...], tuple[OwnerExpenseItem, ...]]:
    capital = (
        _capital("c1", 0, 0.1),
        _capital("c2", 0, 0.2),
        _capital("c3", 13, 1e16),
        _capital("c4", 14, 1.0),
        _capital("c5", 15, 1.0),
        _capital("c6", 24, 0.3),
        _capital("c7", 61, 7.7),
        _capital("c8", 1, 0.7),
    )
    expenses = (
        _expense("e1", 0.1, 1),
        _expense("e2", 0.2, 1, 3),
        _expense("e3", 1e16, 2, 9),
        _expense("e4", 1.0, 2),
        _expense("e5", 0.3, 6, 7),
    )
    return capital, expenses


def test_u3_item_order_does_not_change_the_resolved_schedule() -> None:
    """Values chosen so a naive left-to-right float sum *does* depend on
    order (``1e16 + 1.0 + 1.0`` loses both ones; ``1.0 + 1.0 + 1e16`` does
    not). The schedule must still compare exactly equal."""

    capital, expenses = _mixed_items()
    reference = _resolve(capital=capital, expenses=expenses)

    assert (1e16 + 1.0) + 1.0 != (1.0 + 1.0) + 1e16  # the trap is real

    for arrangement in (
        (capital[::-1], expenses[::-1]),
        (capital[3:] + capital[:3], expenses[2:] + expenses[:2]),
        (tuple(sorted(capital, key=lambda item: -item.amount)), expenses),
    ):
        assert _resolve(capital=arrangement[0], expenses=arrangement[1]) == reference

    # The correctly rounded exact sums (1e16 + 2.3 and 1e16 + 1.3), which a
    # naive sum in declared order gets wrong (it returns 1e16 for both).
    assert reference.project_capital_by_year[1] == 1.0000000000000002e16
    assert reference.owner_expenses_by_year[1] == 1.0000000000000002e16


def test_u4_description_and_category_do_not_change_the_schedule() -> None:
    capital, expenses = _mixed_items()
    reference = _resolve(capital=capital, expenses=expenses)

    relabelled_capital = tuple(
        replace(
            item,
            description=f"Relabelled {index}",
            category=list(CapitalItemCategory)[index % len(CapitalItemCategory)],
        )
        for index, item in enumerate(capital)
    )
    relabelled_expenses = tuple(
        replace(
            item,
            description="Something else entirely",
            category=OwnerExpenseCategory.OTHER,
        )
        for item in expenses
    )

    assert _resolve(capital=relabelled_capital, expenses=relabelled_expenses) == reference


@pytest.mark.parametrize(
    ("field", "value"),
    [("month", 30), ("amount", 999.0)],
)
def test_economic_capital_fields_do_change_the_schedule(field: str, value: object) -> None:
    item = _capital("c", 6, 100.0)
    changed = replace(item, **{field: value})

    assert _resolve(capital=[changed]) != _resolve(capital=[item])


@pytest.mark.parametrize(
    ("field", "value"),
    [("annual_amount", 999.0), ("first_year", 3), ("last_year", 2)],
)
def test_economic_expense_fields_do_change_the_schedule(field: str, value: object) -> None:
    item = _expense("e", 100.0, 1, None)
    changed = replace(item, **{field: value})

    assert _resolve(expenses=[changed]) != _resolve(expenses=[item])


def test_item_ids_do_not_change_the_schedule() -> None:
    capital, expenses = _mixed_items()
    reference = _resolve(capital=capital, expenses=expenses)

    renamed = _resolve(
        capital=[replace(item, item_id=f"x-{item.item_id}") for item in capital],
        expenses=[replace(item, item_id=f"y-{item.item_id}") for item in expenses],
    )

    assert renamed == reference


# =============================================================================
# U12 -- many items
# =============================================================================


def test_u12_many_items_resolve_deterministically_and_order_independently() -> None:
    generator = random.Random(20260911)
    hold_period = 10
    capital = tuple(
        _capital(
            f"c{index}",
            generator.randint(0, 12 * hold_period + 24),
            round(generator.uniform(0.0, 5_000_000.0), 2),
        )
        for index in range(3_000)
    )
    expenses = tuple(
        _expense(
            f"e{index}",
            round(generator.uniform(0.0, 250_000.0), 2),
            generator.randint(1, hold_period + 3),
            None if index % 3 == 0 else hold_period + generator.randint(-5, 5),
        )
        for index in range(1_000)
    )
    expenses = tuple(
        replace(item, last_year=max(item.last_year, item.first_year))
        if item.last_year is not None
        else item
        for item in expenses
    )

    reference = _resolve(hold_period=hold_period, capital=capital, expenses=expenses)
    assert _resolve(hold_period=hold_period, capital=capital, expenses=expenses) == reference

    shuffled_capital, shuffled_expenses = list(capital), list(expenses)
    generator.shuffle(shuffled_capital)
    generator.shuffle(shuffled_expenses)
    assert (
        _resolve(
            hold_period=hold_period,
            capital=shuffled_capital,
            expenses=shuffled_expenses,
        )
        == reference
    )

    # Conservation: every capital dollar lands in exactly one bucket.
    assert math.fsum(
        (
            reference.closing_project_capital,
            *reference.project_capital_by_year,
            reference.post_hold_project_capital,
        )
    ) == pytest.approx(math.fsum(item.amount for item in capital), rel=1e-12)
    assert len(reference.project_capital_by_year) == hold_period


# =============================================================================
# hold_period and plan validation at the resolver boundary
# =============================================================================


@pytest.mark.parametrize("hold_period", [True, False, 5.0, "5", None])
def test_non_integer_hold_period_is_a_type_error(hold_period: object) -> None:
    with pytest.raises(TypeError, match="whole number of years"):
        resolve_business_plan(BusinessPlan(), hold_period=hold_period)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="whole number of years"):
        owner_expense_hold_treatments(BusinessPlan(), hold_period=hold_period)  # type: ignore[arg-type]


@pytest.mark.parametrize("hold_period", [0, -1])
def test_hold_period_below_one_is_a_value_error(hold_period: int) -> None:
    with pytest.raises(ValueError, match="at least 1 year"):
        resolve_business_plan(BusinessPlan(), hold_period=hold_period)
    with pytest.raises(ValueError, match="at least 1 year"):
        owner_expense_hold_treatments(BusinessPlan(), hold_period=hold_period)


def test_hold_period_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        resolve_business_plan(BusinessPlan(), 5)  # type: ignore[misc]


def test_the_resolver_refuses_an_invalid_plan() -> None:
    plan = BusinessPlan(
        capital_items=(_capital("abc", 1, 1.0),),
        owner_expense_items=(_expense("abc", 1.0, 1),),
    )

    with pytest.raises(BusinessPlanValidationError):
        resolve_business_plan(plan, hold_period=5)
    with pytest.raises(BusinessPlanValidationError):
        owner_expense_hold_treatments(plan, hold_period=5)


def test_the_resolver_refuses_invalid_numerics_rather_than_coercing() -> None:
    for plan in (
        BusinessPlan(capital_items=(_capital("c", True, 1.0),)),  # type: ignore[arg-type]
        BusinessPlan(capital_items=(_capital("c", 1, float("nan")),)),
        BusinessPlan(owner_expense_items=(_expense("e", -1.0, 1),)),
        BusinessPlan(owner_expense_items=(_expense("e", 1.0, True),)),  # type: ignore[arg-type]
    ):
        with pytest.raises(BusinessPlanValidationError):
            resolve_business_plan(plan, hold_period=5)


def test_a_total_that_overflows_is_refused_as_non_finite() -> None:
    """Each amount is finite and valid; their sum is not representable. The
    resolver fails explicitly through the engine's non-finite convention."""

    plan = BusinessPlan(
        capital_items=(_capital("a", 3, 1.7e308), _capital("b", 4, 1.7e308)),
    )

    with pytest.raises(NonFiniteResultError) as raised:
        resolve_business_plan(plan, hold_period=5)
    assert raised.value.field_name == "project_capital_by_year[0]"
