"""Sprint D Gate D1.1 -- the canonical Lease-Level monthly calendar.

Restates
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 5.2, 5.3 and Gate D1.1 exactly; that document governs on any
discrepancy.

This module owns the one trusted representation of every modeled lease month.
It answers, deterministically: what is Model Month 1, what calendar month is
it, which hold year contains it, which months are inside the acquisition hold,
and which twelve months form the forward exit-NOI window.

**It calculates no rent.** Calendar arithmetic is in scope here; financial
arithmetic is not. No base rent, no annual rent, no escalation, no occupancy,
no NOI.

**A financial month is a calendar month.** Every function below is pure
integer arithmetic over ``(year, month)``. There is no ``timedelta``, no day
count, no 30-day month, and no ``365 / 12`` anywhere -- so leap years, month
lengths, and timezones cannot affect a single result. ``datetime.date`` is
used only to carry a month's identity, never to do arithmetic on.

Note the deliberate module name shadowing: this is ``anchor.leasing.calendar``,
not the standard library's ``calendar``. ``from __future__ import annotations``
plus absolute imports keep the two unambiguous, and the stdlib module is
imported here under an explicit alias.
"""

from __future__ import annotations

import calendar as _stdlib_calendar
from datetime import date

from .contracts import ModelMonth


_MONTHS_PER_YEAR = 12

#: The forward exit-NOI window is always exactly twelve months long
#: (D0 Section 17.1): months ``12H+1 .. 12H+12``.
FORWARD_EXIT_WINDOW_MONTHS = 12


# =============================================================================
# Date predicates
#
# Moved here from ``validation.py`` at D1.1, unchanged in behavior, so that
# month-boundary logic lives in exactly one place. ``validation`` imports them
# from this module rather than keeping a second copy.
# =============================================================================


def is_first_day_of_month(value: date) -> bool:
    """``True`` when ``value`` is the first calendar day of its own month."""

    return value.day == 1


def last_day_of_month(value: date) -> date:
    """Return the final calendar day of ``value``'s own month.

    Calendar-aware by construction: February resolves to the 29th in a leap
    year and the 28th in a common year, with no special case here.
    """

    _, final_day = _stdlib_calendar.monthrange(value.year, value.month)
    return date(value.year, value.month, final_day)


def is_last_day_of_month(value: date) -> bool:
    """``True`` when ``value`` is the final calendar day of its own month.

    February 29 is the last day of February in a leap year; February 28 is the
    last day only in a common year, and is *not* a month end in a leap year --
    the trap D1-G10c pins.
    """

    return value.day == _stdlib_calendar.monthrange(value.year, value.month)[1]


# =============================================================================
# Month identity
# =============================================================================


def _absolute_month_ordinal(value: date) -> int:
    """A strictly increasing, calendar-origin-independent month ordinal.

    ``year * 12 + month``. Collision-free for every representable date, and
    order-isomorphic to the calendar, so comparing two ordinals answers
    "same month / earlier / later" exactly.

    Private: it is an implementation detail of ``month_index`` below, which is
    the public, analysis-anchored form every caller should use. D0 lists no
    public absolute-ordinal helper, and exposing one would invite a second,
    unanchored notion of "which month" alongside ``period_index``.
    """

    return value.year * _MONTHS_PER_YEAR + value.month


def month_index(target: date, *, analysis_start: date) -> int:
    """Return ``target``'s 1-based sequential model month.

    ``month_index(analysis_start, analysis_start=analysis_start) == 1``.

    The result is **month-granular**: every date within a calendar month maps
    to the same index, which is exactly what D1's whole-month economics
    require (D0 Section 5.4). It is total and never raises -- a date before
    the analysis start yields zero or a negative index rather than an error,
    which is what an in-place lease commenced years before acquisition needs
    (D0 Section 6.4). That raw, unclamped value is what D1.2 will use to place
    such a lease on its correct contractual escalation step, so it must never
    be clamped here.
    """

    return (
        _absolute_month_ordinal(target)
        - _absolute_month_ordinal(analysis_start)
        + 1
    )


def month_start_for_index(index: int, *, analysis_start: date) -> date:
    """Return the first calendar day of the month at 1-based ``index``.

    The exact inverse of ``month_index`` at month granularity:
    ``month_index(month_start_for_index(k)) == k`` for every integer ``k``,
    including zero and negatives.

    ``analysis_start`` is expected to be a first-of-month date (enforced by
    ``anchor.leasing.validation``); the returned date always has ``day == 1``,
    so no invalid calendar date can be constructed regardless of the input's
    day-of-month.
    """

    total = (
        analysis_start.year * _MONTHS_PER_YEAR
        + (analysis_start.month - 1)
        + (index - 1)
    )
    year, month_offset = divmod(total, _MONTHS_PER_YEAR)
    return date(year, month_offset + 1, 1)


# =============================================================================
# The canonical projection window
# =============================================================================


def projection_month_count(hold_period: int) -> int:
    """Return ``12 * hold_period + 12`` -- the canonical projection length.

    The window is the acquisition hold (months ``1 .. 12H``) **plus** the
    twelve forward exit-NOI months (``12H+1 .. 12H+12``, D0 Section 17.1).
    Both live in one projection: Anchor never builds a second terminal-value
    timeline, which is what guarantees the exit NOI an analyst inspects is the
    same one the valuation used (guardrail G-M12).

    ``hold_period`` follows Anchor's existing, unmodified acquisition
    convention -- a whole number of years, at least 1
    (``anchor.validation._YEAR_FIELD_MINIMUM``). It arrives already validated
    on ``AcquisitionTerms``; the guard here is a construction-boundary
    assertion against a programming error, not a second validation authority,
    and it deliberately does not redefine or widen that domain.
    """

    if isinstance(hold_period, bool) or not isinstance(hold_period, int):
        raise TypeError(
            f"hold_period must be a whole number of years; got {hold_period!r}."
        )
    if hold_period < 1:
        raise ValueError(
            f"hold_period must be at least 1 year; got {hold_period!r}."
        )

    return _MONTHS_PER_YEAR * hold_period + FORWARD_EXIT_WINDOW_MONTHS


def hold_year_for_index(index: int) -> int:
    """Return the 1-based hold year containing model month ``index``.

    ``hold_year == ((period_index - 1) // 12) + 1`` (D0 Section 4.7), so
    months 1-12 are Hold Year 1, months 13-24 are Hold Year 2, and the twelve
    forward exit months are Hold Year ``H + 1``.

    **Derived from the sequential index, never from the calendar year.** With
    an analysis start of 2027-07-01, Hold Year 1 runs Jul-2027 through
    Jun-2028 and spans a calendar-year boundary without changing hold year --
    the distinction failure mode FM-4 exists to catch.
    """

    return (index - 1) // _MONTHS_PER_YEAR + 1


def build_model_months(
    *, analysis_start: date, hold_period: int
) -> tuple[ModelMonth, ...]:
    """Return the complete canonical monthly timeline, in chronological order.

    Length is exactly ``projection_month_count(hold_period)``. Every entry
    satisfies the D0 Section 4.7 invariants:

    - ``period_index == array position + 1`` (1-based, no gaps, no duplicates)
    - ``month_start == analysis_start + (period_index - 1) months``
    - ``hold_year == ((period_index - 1) // 12) + 1``
    - ``is_forward_exit_month == (period_index > 12 * hold_period)``

    Exactly twelve entries are forward exit months, and they are the final
    twelve.

    Pure and deterministic: the same arguments always produce a value-equal
    tuple. This function attaches no lease, computes no rent, and reads no
    lease input -- it describes time and nothing else.

    ``analysis_start`` is expected to be month-aligned; that is enforced by
    ``anchor.leasing.validation``, which owns the input-validation boundary.
    This builder deliberately does **not** silently normalize a mid-month
    date, since doing so would convert a rejected input into a quietly
    different timeline (D0 Section 5.5).
    """

    total_months = projection_month_count(hold_period)
    last_hold_month = _MONTHS_PER_YEAR * hold_period

    return tuple(
        ModelMonth(
            period_index=index,
            month_start=month_start_for_index(index, analysis_start=analysis_start),
            hold_year=hold_year_for_index(index),
            is_forward_exit_month=index > last_hold_month,
        )
        for index in range(1, total_months + 1)
    )
