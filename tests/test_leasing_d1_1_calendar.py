"""Sprint D Gate D1.1 -- the canonical Lease-Level monthly calendar.

Proves, per
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 4.7, 5.2, 5.3, 17.1 and Gate D1.1:

1. ``ModelMonth`` carries both sequential and calendar identity, immutably.
2. ``month_index`` / ``month_start_for_index`` are exact inverses, total, and
   never use a day count.
3. Hold year is derived from the sequential index, never the calendar year.
4. The forward exit window is exactly the final twelve months.
5. ``projection_month_count(H) == 12H + 12``.
6. Calendar goldens A, B and C hold exactly.

No rent is calculated anywhere in this gate.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from anchor.leasing import (
    ModelMonth,
    build_model_months,
    is_first_day_of_month,
    is_last_day_of_month,
    last_day_of_month,
    month_index,
    month_start_for_index,
    projection_month_count,
)
from anchor.leasing.calendar import hold_year_for_index


# =============================================================================
# ModelMonth contract
# =============================================================================


def test_model_month_is_immutable_and_slotted() -> None:
    month = ModelMonth(
        period_index=1,
        month_start=date(2027, 1, 1),
        hold_year=1,
        is_forward_exit_month=False,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        month.period_index = 2  # type: ignore[misc]

    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        month.label = "Jan-27"  # type: ignore[attr-defined]


def test_model_month_compares_by_value() -> None:
    def build() -> ModelMonth:
        return ModelMonth(
            period_index=13,
            month_start=date(2028, 1, 1),
            hold_year=2,
            is_forward_exit_month=False,
        )

    assert build() == build()
    assert build() != dataclasses.replace(build(), period_index=14)


def test_model_month_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        ModelMonth(1, date(2027, 1, 1), 1, False)  # type: ignore[misc]


def test_model_month_declares_exactly_the_four_d0_fields() -> None:
    assert [f.name for f in dataclasses.fields(ModelMonth)] == [
        "period_index",
        "month_start",
        "hold_year",
        "is_forward_exit_month",
    ]


def test_month_start_is_a_plain_date_never_a_timestamp() -> None:
    """D0: the financial domain model carries a `date`, never a timezone-aware
    datetime, a locale string, or a display label."""

    month = build_model_months(analysis_start=date(2027, 1, 1), hold_period=1)[0]

    assert type(month.month_start) is date
    assert not hasattr(month.month_start, "tzinfo")


# =============================================================================
# month_index / month_start_for_index
# =============================================================================


def test_month_index_of_the_analysis_start_is_one() -> None:
    """Period numbering is 1-based; zero-based financial periods are never
    exposed."""

    start = date(2027, 1, 1)
    assert month_index(start, analysis_start=start) == 1


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (date(2027, 1, 1), 1),
        (date(2027, 2, 1), 2),
        (date(2027, 12, 1), 12),
        (date(2028, 1, 1), 13),
        (date(2031, 12, 1), 60),
        (date(2032, 1, 1), 61),
    ],
)
def test_month_index_matches_the_d0_worked_example(target: date, expected: int) -> None:
    """The Section 5.3 worked example for ``s = 2027-01-01``."""

    assert month_index(target, analysis_start=date(2027, 1, 1)) == expected


def test_month_index_is_month_granular() -> None:
    """Every date within a calendar month maps to the same index -- exactly
    what D1's whole-month economics require."""

    start = date(2026, 1, 1)
    for day in (1, 2, 15, 28, 31):
        assert month_index(date(2026, 3, day), analysis_start=start) == 3


def test_month_index_is_total_and_negative_before_the_analysis_start() -> None:
    """An in-place lease commenced years before acquisition must yield a raw,
    unclamped index rather than an exception (D0 Section 6.4)."""

    start = date(2026, 1, 1)

    assert month_index(date(2025, 12, 1), analysis_start=start) == 0
    assert month_index(date(2024, 1, 1), analysis_start=start) == -23
    assert month_index(date(2016, 1, 1), analysis_start=start) == -119


@pytest.mark.parametrize("k", list(range(-120, 241)))
def test_month_index_and_month_start_for_index_round_trip(k: int) -> None:
    start = date(2027, 1, 1)

    assert month_index(month_start_for_index(k, analysis_start=start), analysis_start=start) == k


def test_month_start_for_index_always_returns_a_first_of_month() -> None:
    start = date(2027, 7, 1)

    for k in range(-24, 121):
        assert month_start_for_index(k, analysis_start=start).day == 1


def test_month_index_is_monotone_non_decreasing() -> None:
    start = date(2027, 1, 1)
    previous = month_index(date(2020, 1, 1), analysis_start=start)

    for year in range(2020, 2041):
        for month in range(1, 13):
            current = month_index(date(year, month, 1), analysis_start=start)
            assert current >= previous
            previous = current


def test_calendar_module_uses_no_day_arithmetic() -> None:
    """D0's Gate D1.1 stop condition: needing a ``timedelta`` or a day count
    would mean the whole-month convention had leaked.

    Checked against the parsed AST rather than the raw text, so that prose
    explaining *why* these constructs are absent does not itself trip the
    assertion.
    """

    import ast
    from pathlib import Path

    tree = ast.parse(
        (
            Path(__file__).resolve().parents[1]
            / "src"
            / "anchor"
            / "leasing"
            / "calendar.py"
        ).read_text(encoding="utf-8")
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id != "timedelta", "calendar must not use timedelta"
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"timedelta", "days", "toordinal"}, (
                f"calendar must not use day arithmetic ({node.attr})"
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            assert node.value not in {365, 365.25, 30, 30.4375}, (
                f"calendar must not approximate a month ({node.value})"
            )
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            imported = {alias.name for alias in node.names}
            assert imported == {"date"}, (
                f"calendar must import only `date` from datetime; got {imported}"
            )


# =============================================================================
# Month advancement -- December rollover, leap years, long holds
# =============================================================================


def test_december_rolls_over_into_january() -> None:
    months = build_model_months(analysis_start=date(2027, 12, 1), hold_period=1)

    assert months[0].month_start == date(2027, 12, 1)
    assert months[1].month_start == date(2028, 1, 1)


def test_leap_february_is_advanced_exactly() -> None:
    """Calendar Golden C -- a timeline crossing February 2028, a leap year."""

    months = build_model_months(analysis_start=date(2028, 1, 1), hold_period=1)
    by_index = {m.period_index: m.month_start for m in months}

    assert by_index[1] == date(2028, 1, 1)
    assert by_index[2] == date(2028, 2, 1)
    assert by_index[3] == date(2028, 3, 1)
    # A 29-day February advances to March exactly like any other month: month
    # advancement never counts days.
    assert by_index[14] == date(2029, 2, 1)
    assert by_index[15] == date(2029, 3, 1)


def test_a_long_hold_advances_every_month_with_no_gap_or_repeat() -> None:
    months = build_model_months(analysis_start=date(2027, 3, 1), hold_period=10)

    assert len(months) == 132
    for earlier, later in zip(months, months[1:]):
        expected_year = earlier.month_start.year + (1 if earlier.month_start.month == 12 else 0)
        expected_month = 1 if earlier.month_start.month == 12 else earlier.month_start.month + 1
        assert later.month_start == date(expected_year, expected_month, 1)


# =============================================================================
# build_model_months invariants
# =============================================================================


@pytest.mark.parametrize("hold_period", [1, 2, 3, 5, 7, 10, 30])
def test_build_model_months_satisfies_every_d0_invariant(hold_period: int) -> None:
    start = date(2027, 1, 1)
    months = build_model_months(analysis_start=start, hold_period=hold_period)

    assert len(months) == projection_month_count(hold_period)

    for position, month in enumerate(months):
        assert month.period_index == position + 1
        assert month.month_start == month_start_for_index(
            month.period_index, analysis_start=start
        )
        assert month.hold_year == (month.period_index - 1) // 12 + 1
        assert month.is_forward_exit_month == (month.period_index > 12 * hold_period)


def test_output_is_chronological_and_index_complete() -> None:
    months = build_model_months(analysis_start=date(2027, 5, 1), hold_period=3)

    indices = [m.period_index for m in months]
    starts = [m.month_start for m in months]

    assert indices == list(range(1, len(months) + 1))
    assert len(set(indices)) == len(indices)
    assert starts == sorted(starts)
    assert len(set(starts)) == len(starts)


def test_repeated_builds_are_value_equal() -> None:
    first = build_model_months(analysis_start=date(2027, 1, 1), hold_period=5)

    for _ in range(50):
        assert build_model_months(analysis_start=date(2027, 1, 1), hold_period=5) == first


def test_build_model_months_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        build_model_months(date(2027, 1, 1), 5)  # type: ignore[misc]


# =============================================================================
# Hold year -- derived from the index, never the calendar year
# =============================================================================


def test_months_1_to_12_are_hold_year_1_and_13_to_24_are_hold_year_2() -> None:
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=3)
    by_index = {m.period_index: m.hold_year for m in months}

    assert {by_index[i] for i in range(1, 13)} == {1}
    assert {by_index[i] for i in range(13, 25)} == {2}
    assert {by_index[i] for i in range(25, 37)} == {3}


def test_a_non_january_analysis_start_groups_by_analysis_year_not_calendar_year() -> None:
    """Calendar Golden B's core assertion. With a July start, Hold Year 1 runs
    Jul-2027 through Jun-2028 and spans a calendar-year boundary without
    changing hold year (failure mode FM-4)."""

    months = build_model_months(analysis_start=date(2027, 7, 1), hold_period=2)
    by_index = {m.period_index: m for m in months}

    assert by_index[1].month_start == date(2027, 7, 1)
    assert by_index[6].month_start == date(2027, 12, 1)
    assert by_index[7].month_start == date(2028, 1, 1)
    assert by_index[12].month_start == date(2028, 6, 1)

    # The calendar year changes between months 6 and 7; the hold year does not.
    assert by_index[6].hold_year == 1
    assert by_index[7].hold_year == 1
    assert by_index[12].hold_year == 1
    assert by_index[13].hold_year == 2
    assert by_index[13].month_start == date(2028, 7, 1)


def test_hold_year_never_tracks_the_calendar_year() -> None:
    months = build_model_months(analysis_start=date(2027, 7, 1), hold_period=3)

    calendar_years = {m.month_start.year for m in months if m.hold_year == 1}
    assert calendar_years == {2027, 2028}, (
        "Hold Year 1 must span two calendar years for a mid-year start"
    )


@pytest.mark.parametrize(
    ("index", "expected"), [(1, 1), (12, 1), (13, 2), (24, 2), (25, 3), (132, 11)]
)
def test_hold_year_for_index_matches_the_d0_formula(index: int, expected: int) -> None:
    assert hold_year_for_index(index) == expected


@pytest.mark.parametrize("hold_period", [1, 2, 5, 10])
def test_forward_months_carry_hold_year_h_plus_one(hold_period: int) -> None:
    """D0 Section 4.7: ``hold_year == ((period_index - 1) // 12) + 1``, which
    makes every forward exit month Hold Year ``H + 1``."""

    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=hold_period)
    forward = [m for m in months if m.is_forward_exit_month]

    assert {m.hold_year for m in forward} == {hold_period + 1}


# =============================================================================
# Forward exit window
# =============================================================================


@pytest.mark.parametrize("hold_period", [1, 2, 3, 5, 10, 30])
def test_exactly_twelve_forward_exit_months(hold_period: int) -> None:
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=hold_period)

    assert sum(1 for m in months if m.is_forward_exit_month) == 12


@pytest.mark.parametrize("hold_period", [1, 2, 3, 5, 10])
def test_the_forward_window_is_exactly_months_12h_plus_1_through_12h_plus_12(
    hold_period: int,
) -> None:
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=hold_period)
    forward = [m.period_index for m in months if m.is_forward_exit_month]
    sale_month = 12 * hold_period

    assert forward == list(range(sale_month + 1, sale_month + 13))
    assert forward[0] == sale_month + 1
    assert forward[-1] == sale_month + 12


@pytest.mark.parametrize("hold_period", [1, 2, 5, 10])
def test_the_sale_month_is_not_a_forward_month_and_the_next_one_is(
    hold_period: int,
) -> None:
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=hold_period)
    by_index = {m.period_index: m for m in months}
    sale_month = 12 * hold_period

    assert by_index[sale_month].is_forward_exit_month is False
    assert by_index[sale_month + 1].is_forward_exit_month is True


@pytest.mark.parametrize("hold_period", [1, 2, 5, 10])
def test_no_month_before_the_sale_boundary_is_forward(hold_period: int) -> None:
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=hold_period)
    sale_month = 12 * hold_period

    assert not any(
        m.is_forward_exit_month for m in months if m.period_index <= sale_month
    )


def test_forward_months_remain_chronological_and_contiguous() -> None:
    months = build_model_months(analysis_start=date(2027, 7, 1), hold_period=2)
    forward = [m for m in months if m.is_forward_exit_month]

    assert [m.month_start for m in forward] == sorted(m.month_start for m in forward)
    assert forward[0].month_start == date(2029, 7, 1)
    assert forward[-1].month_start == date(2030, 6, 1)


def test_there_is_one_projection_not_a_second_terminal_timeline() -> None:
    """Guardrail G-M12: the forward exit months live inside the same canonical
    projection, so the exit NOI an analyst inspects is the one the valuation
    used."""

    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=5)

    assert len(months) == 72
    assert months[59].period_index == 60 and not months[59].is_forward_exit_month
    assert months[60].period_index == 61 and months[60].is_forward_exit_month
    # Contiguous: no gap between the hold and the forward window.
    assert months[60].month_start == date(2032, 1, 1)


# =============================================================================
# projection_month_count
# =============================================================================


@pytest.mark.parametrize(
    ("hold_period", "expected"), [(1, 24), (2, 36), (3, 48), (5, 72), (10, 132), (30, 372)]
)
def test_projection_month_count(hold_period: int, expected: int) -> None:
    assert projection_month_count(hold_period) == expected


@pytest.mark.parametrize("hold_period", [1, 2, 5, 10])
def test_sequence_length_equals_the_helper_result(hold_period: int) -> None:
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=hold_period)

    assert len(months) == projection_month_count(hold_period)


@pytest.mark.parametrize("hold_period", [0, -1, -12])
def test_a_hold_period_below_one_year_is_rejected(hold_period: int) -> None:
    """Anchor's existing acquisition convention: a whole number of years, at
    least 1 (``anchor.validation._YEAR_FIELD_MINIMUM``). This gate respects
    that domain rather than redefining or widening it."""

    with pytest.raises(ValueError):
        projection_month_count(hold_period)


@pytest.mark.parametrize("hold_period", [5.0, 5.5, "5", None, True])
def test_a_non_integer_hold_period_is_rejected(hold_period: object) -> None:
    with pytest.raises(TypeError):
        projection_month_count(hold_period)  # type: ignore[arg-type]


# =============================================================================
# Date predicates (moved here from validation at D1.1)
# =============================================================================


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2027, 1, 1), True),
        (date(2027, 1, 2), False),
        (date(2027, 1, 31), False),
        (date(2028, 2, 1), True),
    ],
)
def test_is_first_day_of_month(value: date, expected: bool) -> None:
    assert is_first_day_of_month(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2027, 1, 31), True),
        (date(2027, 1, 30), False),
        (date(2027, 4, 30), True),
        (date(2027, 4, 29), False),
        (date(2028, 2, 29), True),   # leap February
        (date(2027, 2, 28), True),   # non-leap February
        (date(2028, 2, 28), False),  # leap year: the 28th is NOT the month end
    ],
)
def test_is_last_day_of_month(value: date, expected: bool) -> None:
    assert is_last_day_of_month(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2027, 1, 15), date(2027, 1, 31)),
        (date(2027, 4, 1), date(2027, 4, 30)),
        (date(2028, 2, 1), date(2028, 2, 29)),
        (date(2027, 2, 1), date(2027, 2, 28)),
    ],
)
def test_last_day_of_month(value: date, expected: date) -> None:
    assert last_day_of_month(value) == expected


# =============================================================================
# Calendar golden cases
# =============================================================================


def test_calendar_golden_a_one_year_hold_from_january() -> None:
    months = build_model_months(analysis_start=date(2027, 1, 1), hold_period=1)
    by_index = {m.period_index: m for m in months}

    assert len(months) == 24

    assert by_index[1].month_start == date(2027, 1, 1)
    assert by_index[1].hold_year == 1
    assert by_index[1].is_forward_exit_month is False

    assert by_index[12].month_start == date(2027, 12, 1)
    assert by_index[12].hold_year == 1
    assert by_index[12].is_forward_exit_month is False

    assert by_index[13].month_start == date(2028, 1, 1)
    assert by_index[13].hold_year == 2
    assert by_index[13].is_forward_exit_month is True

    assert by_index[24].month_start == date(2028, 12, 1)
    assert by_index[24].hold_year == 2
    assert by_index[24].is_forward_exit_month is True


def test_calendar_golden_b_two_year_hold_from_july() -> None:
    months = build_model_months(analysis_start=date(2027, 7, 1), hold_period=2)
    by_index = {m.period_index: m for m in months}

    assert len(months) == 36

    expected_starts = {
        1: date(2027, 7, 1),
        6: date(2027, 12, 1),
        7: date(2028, 1, 1),
        12: date(2028, 6, 1),
        13: date(2028, 7, 1),
        24: date(2029, 6, 1),
        25: date(2029, 7, 1),
        36: date(2030, 6, 1),
    }
    for index, expected in expected_starts.items():
        assert by_index[index].month_start == expected, f"month {index}"

    assert by_index[24].is_forward_exit_month is False
    assert by_index[25].is_forward_exit_month is True
    assert by_index[36].is_forward_exit_month is True
    assert by_index[25].hold_year == 3


def test_calendar_golden_c_timeline_crossing_february_2028() -> None:
    """February 2028 has 29 days. Month advancement must be exact across it,
    and the sequence must contain every intervening month once."""

    months = build_model_months(analysis_start=date(2027, 11, 1), hold_period=1)
    by_index = {m.period_index: m.month_start for m in months}

    assert by_index[1] == date(2027, 11, 1)
    assert by_index[2] == date(2027, 12, 1)
    assert by_index[3] == date(2028, 1, 1)
    assert by_index[4] == date(2028, 2, 1)
    assert by_index[5] == date(2028, 3, 1)
    assert by_index[12] == date(2028, 10, 1)
    assert by_index[13] == date(2028, 11, 1)
    assert by_index[24] == date(2029, 10, 1)

    assert last_day_of_month(by_index[4]) == date(2028, 2, 29)
