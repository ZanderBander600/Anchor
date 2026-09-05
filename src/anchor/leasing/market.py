"""Sprint D Gate D2.1 -- the canonical monthly market-rent schedule.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Section 9 and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 7.1-7.4 and 24.1-24.5 exactly; those documents govern on any
discrepancy.

**The one financial question this module answers.** For any canonical
``ModelMonth``: *what is the market rent of this space, in ``$/SF/year``, as
of that month?* Nothing more. It does not decide whether a lease renews,
whether a new tenant is found, when space becomes occupied, or what cash rent
is actually received. Market rent is an **assumption schedule**; it is not yet
a successor lease.

**This is the only module in ``anchor.leasing`` permitted to perform
market-rent arithmetic**, exactly as ``rent.py`` is the only one permitted to
perform contractual-rent arithmetic. Neither may touch the other's fields:
``rent.py`` never reads ``market_rent_psf`` or ``market_rent_growth``, and
this module never reads ``base_rent_psf`` or ``escalation_pct``. That boundary
is enforced by ``tests/test_leasing_architecture.py``, which exempts each
module by name for its own fields only.

**Market rent and contractual rent are different concepts with different
clocks** (D0 Section 7.2, D2 Section 10), and confusing them is failure mode
FM-6 / FM-D2-12 / FM-D2-13 / FM-D2-14:

===================  =========================  ==========================
                     Market rent                Contractual rent
===================  =========================  ==========================
What it is           A market assumption        A term of a signed lease
Anchored to          ``analysis_start_date``    ``rent_commencement_date``
                     anniversaries              anniversaries
Rate field           ``market_rent_growth``     ``escalation_pct``
Applies to           available / rolling space  the sitting tenant
===================  =========================  ==========================

Market growth never alters an existing contractual lease, and contractual
escalation never alters market rent. Setting the two rates equal makes them
numerically coincide; that is a coincidence of inputs, never an identity of
concepts.

**Deliberately absent, all of it later work:** renewal, renewal probability,
new tenants, downtime, free rent, TI, LC, probability weighting, recursion,
successor commencement, successor terms, successor contractual escalation, and
every conversion of a market rate into a dollar cash flow. D2.1 produces a
rate series and stops.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from ..engine.contracts import ensure_finite
from .contracts import (
    LeaseLevelPropertyInputs,
    MarketAssumptionSource,
    MarketLeasingAssumptions,
    MarketRentSchedule,
    ModelMonth,
    ResolvedMarketLeasing,
    Suite,
)


_MONTHS_PER_YEAR = 12


# =============================================================================
# Precedence -- resolved once per suite (D0 Section 24.5)
# =============================================================================


def resolve_market_leasing(
    suite: Suite, *, property_defaults: MarketLeasingAssumptions
) -> ResolvedMarketLeasing:
    """Return one suite's market leasing assumptions, with precedence applied.

    D0 Section 24.1, the rent level::

        Suite.market_leasing_override.market_rent_psf   (if the override is not None)
          > Suite.market_rent_psf                        (if not None)
          > MarketLeasingAssumptions.market_rent_psf     (property default)

    D0 Section 24.2, every other market leasing assumption::

        Suite.market_leasing_override.<field>   (if the override is not None)
          > MarketLeasingAssumptions.<field>    (property default)

    **The override is all-or-nothing.** When a suite supplies
    ``market_leasing_override``, that record is used in full and no field
    falls through to the property default. ``Suite.market_rent_psf`` is the
    single deliberate exception, and it applies on top of whichever record
    won -- so a suite may carry a full override *and* a rent-level override,
    in which case the rent level wins over the override's own rent.

    ``property_defaults`` is a required argument, not an optional one. D0
    Section 4.5 states the property default is always present, and a suite
    carrying only a rent-level override has no growth rate without it. Making
    it required means the "missing property default" case is impossible to
    reach here rather than being defaulted to something invented.

    **This is the only precedence implementation in the package.** The
    resolver runs once per suite and its result is recorded on the schedule
    it drives (and, from D2.2, on every ``RolloverEvent``), so "which
    assumption applied here, and where did it come from" is answerable from
    the output alone.

    Pure: reads two records, writes nothing, and computes no rent.
    """

    override = suite.market_leasing_override
    if override is None:
        base = property_defaults
        source = MarketAssumptionSource.PROPERTY_DEFAULT
    else:
        base = override
        source = MarketAssumptionSource.SUITE_OVERRIDE

    suite_level_rent = suite.market_rent_psf
    from_suite = suite_level_rent is not None

    # D0 Section 24.1 overrides the rent **level alone**: every other field is
    # kept from whichever record won above. `replace` states exactly that, and
    # -- unlike rebuilding the record field by field -- it stays correct as
    # later gates add fields to `MarketLeasingAssumptions`. Reconstructing it
    # explicitly would silently drop each newly added assumption.
    assumptions = (
        replace(base, market_rent_psf=suite_level_rent) if from_suite else base
    )

    return ResolvedMarketLeasing(
        suite_id=suite.suite_id,
        assumptions=assumptions,
        source=source,
        market_rent_psf_from_suite=from_suite,
    )


# =============================================================================
# The market-rent formula -- one implementation, no second copy
# =============================================================================


def market_growth_index(period: int) -> int:
    """Return ``k``, the number of completed analysis years at ``period``.

    ``k = floor((period - 1) / 12)`` (D0 Section 7.2, D2 Section 9.1), so
    periods 1-12 use ``k = 0``, periods 13-24 use ``k = 1``, periods 25-36 use
    ``k = 2``, and so on. Growth is held flat within each 12-period band and
    steps on the band boundary.

    Counted from the **analysis start**, never from a lease anniversary and
    never from the calendar year. With ``analysis_start = 2027-07-01`` the
    step falls on 2028-07-01, not 2028-01-01: market rent is a market fact
    anchored to the analysis date, and a mid-year lease does not move the
    market clock (failure mode FM-D2-13).

    The parameter is deliberately named ``period`` -- the canonical 1-based
    ``ModelMonth.period_index`` -- and the returned ``k`` is a completed-year
    count, not a month index. The two are never interchangeable, which is the
    same distinction ``rent.escalation_period_index`` maintains on the
    contractual side.

    Periods below 1 are rejected. Market rent is defined from Month 1 onward;
    "the market rent before the analysis start" is not a concept this model
    has, and silently extrapolating backwards through a negative exponent
    would invent one.
    """

    if isinstance(period, bool) or not isinstance(period, int):
        raise TypeError(
            f"period must be a canonical 1-based model month index; "
            f"got {period!r}."
        )
    if period < 1:
        raise ValueError(
            f"period must be at least 1; got {period!r}. Market rent is "
            "defined from Month 1 (the analysis start) onward."
        )

    return (period - 1) // _MONTHS_PER_YEAR


def market_rent_psf_for_period(
    *, market_rent_psf: float, market_rent_growth: float, period: int
) -> float:
    """Return the market rent in ``$/SF/year`` for one canonical period.

    **The authoritative market-rent formula** (D0 Section 7.2, D2
    Section 9.1)::

        MarketRentPSF(m) = market_rent_psf * (1 + market_rent_growth) ** floor((m - 1) / 12)

    ``market_rent_psf`` is the rent as of ``analysis_start_date`` -- the
    Month 1 market rent. Growth applies in **annual steps on anniversaries of
    the analysis start**, held flat within each band.

    Two things this explicitly is **not** (D0 Section 7.2):

    - **Not monthly-compounded.** ``(1 + g) ** ((m - 1) / 12)`` is smoother
      but departs from Anchor's frozen annual-growth timing convention and
      buys precision a market-rent assumption does not possess
      (failure mode FM-D2-12).
    - **Not reset on a lease anniversary.** Market rent is anchored to the
      analysis date; contractual escalation is anchored to the lease
      (failure mode FM-D2-13).

    No rounding, no quantization, no ``Decimal``; the operation order is fixed
    so the same inputs always produce the same bits. A zero
    ``market_rent_psf`` yields exactly ``0.0`` in every period -- zero is a
    real market rent, never vacancy, missing data, or free rent. A negative
    ``market_rent_growth`` in ``(-1, 0)`` yields a declining series, exactly
    as every other Anchor compounding rate permits.

    Wrapped in ``ensure_finite``, so growth that overflows to infinity fails
    loudly rather than propagating a silent ``inf`` -- the same convention
    every other Anchor calculator uses.

    **D2.2 and D2.3 price a successor commencing in period ``c`` by calling
    this function, or by reading the schedule it built** -- never by
    re-deriving the formula. There must never be one market-rent formula for
    schedules and another for rollover.
    """

    growth_factor = (1 + market_rent_growth) ** market_growth_index(period)
    return ensure_finite(
        "market_rent_psf_for_period", market_rent_psf * growth_factor
    )


# =============================================================================
# The canonical monthly schedule
# =============================================================================


def build_market_rent_schedule(
    suite: Suite,
    *,
    property_defaults: MarketLeasingAssumptions,
    months: tuple[ModelMonth, ...],
) -> MarketRentSchedule:
    """Return one suite's market rent for every canonical month.

    **Precondition: the inputs are already validated.** This follows the
    boundary ``rent.build_lease_monthly_schedule`` already established -- call
    ``anchor.leasing.validation.require_valid_lease_level_inputs`` with the
    market assumptions first. Re-validating here would create a second
    validation authority whose behaviour could drift from the first.

    The schedule spans exactly the ``months`` supplied -- the **canonical D1
    timeline**, built once by ``calendar.build_model_months`` and passed in.
    This function never builds a second calendar and never invents a period
    beyond the ones given.

    **Market rent runs through the entire canonical timeline**, hold years
    ``1 .. H`` *and* the twelve forward exit months ``12H+1 .. 12H+12``
    (D2 Section 11). Growth is not frozen at the sale month and a step falling
    inside the forward window happens normally, because rollover stays fully
    live in that window and a successor commencing there must be priced from a
    market rent that kept growing.

    Every value is a ``$/SF/year`` **rate**. Nothing here multiplies by
    ``suite_area_sf`` or divides by 12: that conversion needs a commencement
    period, a term, downtime and free rent, none of which exist at D2.1.

    Pure and deterministic -- no I/O, no network, no database, no mutation.
    The same inputs always produce a value-equal schedule.
    """

    resolved = resolve_market_leasing(suite, property_defaults=property_defaults)
    assumptions = resolved.assumptions

    return MarketRentSchedule(
        suite_id=suite.suite_id,
        resolved=resolved,
        months=months,
        market_rent_psf=tuple(
            market_rent_psf_for_period(
                market_rent_psf=assumptions.market_rent_psf,
                market_rent_growth=assumptions.market_rent_growth,
                period=month.period_index,
            )
            for month in months
        ),
    )


def build_property_market_rent_schedules(
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    *,
    property_defaults: MarketLeasingAssumptions,
    months: tuple[ModelMonth, ...],
) -> tuple[MarketRentSchedule, ...]:
    """Return one ``MarketRentSchedule`` per suite, in declared suite order.

    A thin, deterministic fan-out over ``build_market_rent_schedule``. It adds
    no formula of its own and performs no aggregation: market rent is a
    per-suite **rate**, and summing or averaging rates across suites of
    different sizes would be meaningless. A property-level market figure, if
    one is ever wanted, is an area-weighted presentation concern and not a
    D2.1 output.

    ``property_inputs`` carries the analysis anchor, and this function checks
    that ``months`` was actually built from it: Month 1's ``month_start`` must
    equal ``analysis_start_date``. Market rent is anchored to the analysis
    date and to nothing else, so a timeline built from a *different* anchor
    would silently shift every growth band -- the whole of failure mode
    FM-D2-13 -- while every individual value still looked plausible. The
    schedule is never rebuilt here to fix a mismatch; there is one canonical
    timeline (``calendar.build_model_months``) and a mismatch is a
    programming error that fails loudly.

    This is a construction-boundary assertion, in the same spirit as
    ``calendar.projection_month_count``'s guard, not a second validation
    authority: it re-checks no domain that
    ``require_valid_lease_level_inputs`` owns.

    Suites are processed in declared order and nothing iterates a ``set`` or
    ``dict``, so repeated runs produce byte-identical results.
    """

    if not months:
        raise ValueError(
            "months must be the canonical ModelMonth timeline; got an empty "
            "sequence."
        )
    anchor_month = months[0]
    if (
        anchor_month.period_index != 1
        or anchor_month.month_start != property_inputs.analysis_start_date
    ):
        raise ValueError(
            "months must be built from the same analysis start as "
            f"property_inputs: expected period 1 at "
            f"{property_inputs.analysis_start_date.isoformat()}, got period "
            f"{anchor_month.period_index} at "
            f"{anchor_month.month_start.isoformat()}."
        )

    return tuple(
        build_market_rent_schedule(
            suite, property_defaults=property_defaults, months=months
        )
        for suite in suites
    )


# =============================================================================
# Lookup -- the single path D2.2 / D2.3 will use
# =============================================================================


def market_rent_psf_at_period(schedule: MarketRentSchedule, period: int) -> float:
    """Return the market rent recorded for canonical ``period``.

    **The authoritative lookup path for rollover.** D2.2 and D2.3 need "the
    market rent applicable in the successor's commencement month"; they read
    it from here rather than recomputing it, so a schedule and a successor can
    never disagree about the same month.

    D2 Section 9.2 fixes the rule at a fractional-downtime boundary month: use
    the canonical period ``c`` exactly as for any other period. The downtime
    boundary factor scales the rent *recognised* in period ``c``; it does not
    shift which 12-period growth band ``c`` falls in, and it introduces no day
    count. That factor is applied by the rollover engine, never here.

    The lookup is by ``period_index`` rather than by array position, so a
    caller holding a period number cannot silently be off by one. A period
    outside the schedule raises rather than clamping to the nearest end: a
    successor commencing past the horizon is a real modelling question for
    D2.6, not something to answer with the last month's rent.
    """

    if not schedule.months:
        raise ValueError(
            f"market rent for period {period!r} was requested from an empty "
            "schedule."
        )

    first = schedule.months[0].period_index
    last = schedule.months[-1].period_index
    if not first <= period <= last:
        raise ValueError(
            f"period {period!r} lies outside the schedule for suite "
            f"{schedule.suite_id!r}, which covers periods {first}-{last}."
        )

    # ModelMonth sequences are contiguous and 1-based ascending by
    # construction (calendar.build_model_months), so the offset is exact.
    return schedule.market_rent_psf[period - first]
