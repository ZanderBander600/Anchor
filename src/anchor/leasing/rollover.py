"""Sprint D Gate D2.2 -- the pure renewal rollover path.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Sections 4.2, 9.1, 10 and 14, and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 8.1, 8.4-8.6 and 24.3 exactly; those documents govern on any
discrepancy.

**The one financial question this gate answers.** If the sitting tenant renews
with certainty: when does the successor begin, what market rent applies at that
moment, what renewal pricing adjustment applies, what does it pay each month,
when does it expire, and how does occupancy behave. Nothing else.

**This is the renewal branch of the approved composition** (D2 HD-D2-1). A
rollover is two independent, complete branch schedules weighted only at the
monthly *output* level. D2.2 builds one of them. It is conceptually the
``p = 1`` endpoint, but **no probability exists here**: the weight arrives at
D2.5, which must reproduce this branch bit-identically at ``p = 1``. Nothing in
this module weights, averages, blends or rounds anything.

**Three formulas this module deliberately does not own.**

1. **Market rent.** ``market.py`` is the single authority. The renewal
   successor's starting rent is read from the canonical market-rent schedule
   through ``market_rent_psf_at_period``, or -- for D0 Section 24.3's explicit
   renewal level -- computed by calling ``market.market_rent_psf_for_period``
   with a different base. There is deliberately no second growth formula here;
   a schedule and a successor can never disagree about the same month.
2. **Contractual rent.** ``rent.py`` is the single authority. A successor is an
   *ordinary contractual lease* from its commencement (D2 Section 10), so its
   monthly rent comes from ``rent.build_lease_monthly_schedule`` -- the exact
   D1 formula, on the successor's own contractual chronology. This module
   constructs a ``Lease`` and hands it over; it never multiplies a rent by an
   area.
3. **The expiring lease's rent.** It is reused unchanged. D2.2 never recomputes
   an in-place lease, and no market assumption may touch one (D0
   Section 24.4).

**The two clocks, which are the whole point of this gate** (D2 Section 10):
market growth prices the successor's *starting* rent **once**, at commencement
``c``; from ``c`` onward the successor escalates on **its own** anniversaries
at ``successor_escalation_pct``. Market rent keeps growing in the background
for the *next* rollover and has no further effect on this lease. Setting the
two rates equal makes them numerically coincide; that is a coincidence of
inputs, never an identity of concepts (failure mode FM-D2-14).

**Deliberately absent, all of it later work:** the new-tenant branch, downtime,
fractional commencement, free rent (D2.3); TI and LC (D2.4);
``renewal_probability`` and every expected-value composition (D2.5); the second
and later rollovers, recursion and any computational limit (D2.6). A pure
renewal has no downtime by construction -- the successor commences the month
after expiry -- so this gate needs no vacancy concept at all.
"""

from __future__ import annotations

from datetime import date

from .calendar import last_day_of_month, month_start_for_index
from .contracts import (
    EscalationBasis,
    Lease,
    LeaseOrigin,
    MarketLeasingAssumptions,
    MarketRentSchedule,
    ModelMonth,
    RenewalBranch,
    ResolvedMarketLeasing,
    Suite,
)
from .market import (
    build_market_rent_schedule,
    market_rent_psf_at_period,
    market_rent_psf_for_period,
)
from .rent import build_lease_monthly_schedule, lease_rent_periods


#: Suffix appended to the expiring lease's id to name its renewal successor.
#: Deterministic and derived, so the same rent roll always produces the same
#: successor id and a rollover log is reproducible run to run.
_RENEWAL_SUCCESSOR_SUFFIX = "::renewal"


# =============================================================================
# Successor timing
# =============================================================================


def renewal_commencement_period(expiration_period: int) -> int:
    """Return the renewal successor's commencement period ``c``.

    ``c = e + 1``: a pure renewal has **no downtime**, so the successor
    commences in the canonical month immediately after the expiring lease's
    last paying month. There is no vacant period and no overlap -- the expiry
    month belongs to the expiring lease alone, and period ``c`` to the
    successor alone.

    ``e`` is the expiring lease's **raw, unclamped** last rent period, from
    ``rent.lease_rent_periods``. Using the window-clamped
    ``LeaseMonthlySchedule.last_rent_period`` instead would silently roll a
    lease at the projection horizon rather than at its real expiration --
    exactly the clamping trap failure mode FM-5 exists to guard on the
    contractual side.

    D0 Section 8.5's general form is ``c = e + 1 + floor(D)``. D2.2 has no
    downtime concept, so ``D`` does not appear here at all rather than
    appearing as a hard-coded zero: the term is introduced by D2.3, which owns
    downtime and the fractional-boundary rule.

    Pure integer arithmetic on canonical period indices. No day count, no
    ``timedelta``, no calendar arithmetic -- a financial month is a calendar
    month, and month identity is ``calendar.py``'s job.
    """

    if isinstance(expiration_period, bool) or not isinstance(expiration_period, int):
        raise TypeError(
            "expiration_period must be a canonical model month index; "
            f"got {expiration_period!r}."
        )

    return expiration_period + 1


def successor_expiration_period(*, commencement_period: int, term_months: int) -> int:
    """Return the successor's last contractual rent period.

    ``last = c + term_months - 1`` (D0 Section 8.5). The term is a count of
    canonical months the successor occupies, so a 12-month term commencing at
    ``c`` runs through ``c + 11`` inclusive -- the expiration month is a paying
    month, exactly as ``Lease.lease_expiration_date`` is inclusive in D1.

    Exact integer arithmetic. The term is never converted to years, never
    rounded, never day-counted and never averaged with another branch's term:
    under the approved composition each branch keeps its own integer term, so
    no fractional term can arise (D2 HD-D2-1).

    The result is **untruncated** -- it may lie beyond the projection horizon.
    That is deliberate: the contractual term is a real obligation whose full
    length D2.4's LC basis needs (D0 Section 12.2, failure mode FM-D2-11).
    Truncation is a property of the monthly *series*, never of the assumption.
    """

    if isinstance(term_months, bool) or not isinstance(term_months, int):
        raise TypeError(f"term_months must be a whole number; got {term_months!r}.")
    if term_months < 1:
        raise ValueError(f"term_months must be at least 1; got {term_months!r}.")

    return commencement_period + term_months - 1


# =============================================================================
# Successor pricing -- D0 Section 24.3
# =============================================================================


def renewal_starting_rent_psf(
    *,
    assumptions: MarketLeasingAssumptions,
    market_rent_psf_at_commencement: float,
    commencement_period: int,
) -> float:
    """Return the successor's starting rent in ``$/SF/year``, at period ``c``.

    D0 Section 24.3, exactly, in its stated precedence order::

        renewal_rent_psf, grown from analysis_start_date to c   (if not None)
          > MarketRentPSF(c) * (1 + renewal_rent_spread)

    **The explicit level wins when supplied.** ``renewal_rent_psf`` is an
    explicit renewal-rent assumption measured on the *same* temporal anchor as
    ``market_rent_psf`` -- as of ``analysis_start_date`` -- so it must be grown
    to the commencement period before use::

        RenewalRentPSF(c) = renewal_rent_psf * (1 + market_rent_growth) ** floor((c - 1) / 12)

    That growth is performed by ``market.market_rent_psf_for_period``, the one
    authoritative implementation, applied to a different base. This module does
    not restate the formula. The phrase "today's dollars" is deliberately never
    used: "today" is neither the analysis start nor the rollover date.

    **Otherwise the successor prices off market.** ``renewal_rent_spread`` is a
    discount or premium **to market at commencement**, so ``0.0`` renews at
    market, ``-0.05`` renews 5% below it and ``+0.05`` 5% above. The market
    figure is the one already read from the canonical schedule at period ``c``
    -- never at the expiration period, and never recomputed here.

    Both paths yield a rate in ``$/SF/year``. Nothing here multiplies by an
    area or divides by 12; that is ``rent.py``'s job, once, when the
    successor's monthly schedule is built.
    """

    explicit_level = assumptions.renewal_rent_psf
    if explicit_level is not None:
        return market_rent_psf_for_period(
            market_rent_psf=explicit_level,
            market_rent_growth=assumptions.market_rent_growth,
            period=commencement_period,
        )

    spread = assumptions.renewal_rent_spread
    return market_rent_psf_at_commencement * (1 + spread)


# =============================================================================
# The successor lease
# =============================================================================


def build_renewal_successor_lease(
    expiring: Lease,
    *,
    suite: Suite,
    analysis_start: date,
    commencement_period: int,
    term_months: int,
    starting_rent_psf: float,
    successor_escalation_pct: float,
) -> Lease:
    """Return the renewal successor as an ordinary contractual ``Lease``.

    **The successor is an assumption, not a known tenant** (D0 Section 8.4).
    Two properties are mandatory and are set here rather than left to a
    caller: ``tenant_name`` is ``None``, and ``origin`` is
    ``LeaseOrigin.SUCCESSOR``. Together they make failure mode FM-D2-18 --
    presenting a modelled successor as a signed tenancy -- unrepresentable
    rather than merely discouraged.

    **Why it is a plain ``Lease``.** D2 Section 10: from commencement the
    successor *is* an ordinary contractual lease. Making it one means its rent
    runs through the single D1 formula in ``rent.py``, on its own contractual
    chronology, with ``EscalationBasis.LEASE_ANNIVERSARY`` counting from its
    own commencement. No successor-specific rent engine exists, so none can
    drift from the contractual one.

    **Dates.** ``rent_commencement_date`` is the first day of canonical month
    ``c``; ``lease_expiration_date`` is the **last day** of canonical month
    ``c + term - 1``, inclusive, exactly as D1 requires. Both are derived from
    the canonical calendar helpers, never by day arithmetic, so month lengths
    and leap years cannot affect a result.

    **Area.** The successor covers the full ``suite_area_sf`` (D0
    Section 8.1). D1-D3 require ``leased_area_sf == suite_area_sf``, so this is
    also the expiring lease's area; taking it from the suite states the
    intent -- what rolls over is the *space*.

    ``lease_type`` is inherited from the expiring lease (D0 Section 8.2): the
    recovery structure is a property of how the building leases, not of which
    tenant is in it. It stays economically inert until D3.

    ``lease_start_date`` is deliberately left ``None``. A possession date is
    informational and never enters an economic calculation; inventing one for
    a lease that does not exist would be fabricated documentary detail.
    """

    commencement = month_start_for_index(
        commencement_period, analysis_start=analysis_start
    )
    last_period = successor_expiration_period(
        commencement_period=commencement_period, term_months=term_months
    )
    expiration = last_day_of_month(
        month_start_for_index(last_period, analysis_start=analysis_start)
    )

    return Lease(
        lease_id=f"{expiring.lease_id}{_RENEWAL_SUCCESSOR_SUFFIX}",
        suite_id=suite.suite_id,
        tenant_name=None,
        leased_area_sf=suite.suite_area_sf,
        rent_commencement_date=commencement,
        lease_expiration_date=expiration,
        base_rent_psf=starting_rent_psf,
        escalation_pct=successor_escalation_pct,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY,
        lease_type=expiring.lease_type,
        origin=LeaseOrigin.SUCCESSOR,
    )


# =============================================================================
# The branch
# =============================================================================


def build_renewal_branch(
    expiring: Lease,
    *,
    suite: Suite,
    analysis_start: date,
    months: tuple[ModelMonth, ...],
    property_defaults: MarketLeasingAssumptions,
    market_schedule: MarketRentSchedule | None = None,
) -> RenewalBranch:
    """Return the complete pure-renewal scenario for one expiring lease.

    **Precondition: the inputs are already validated.** This follows the
    boundary ``rent.build_lease_monthly_schedule`` and
    ``market.build_market_rent_schedule`` already established -- call
    ``validation.require_valid_lease_level_inputs`` with the market
    assumptions first. Re-validating here would create a second validation
    authority whose behaviour could drift from the first.

    The sequence, each step delegating to the module that owns it:

    1. Resolve the suite's market leasing assumptions once (``market.py``,
       D0 Section 24.5), or reuse a schedule the caller already built.
    2. ``e`` = the expiring lease's raw last rent period; ``c = e + 1``.
    3. Read ``MarketRentPSF(c)`` from the canonical market-rent schedule.
    4. Price the successor by D0 Section 24.3.
    5. Construct the successor ``Lease`` and build its monthly schedule
       through the D1 rent engine.
    6. Sum the two schedules month by month.

    ``market_schedule`` is optional. When supplied it must be this suite's own
    schedule, and it is used as-is -- the caller has usually built one already
    and rebuilding it would be wasteful. When omitted one is built here from
    ``property_defaults``. Either way the market rent comes from the canonical
    schedule; there is no path through this function that computes a market
    rent independently.

    **No gap and no overlap.** The expiring lease is active through ``e`` and
    the successor from ``c = e + 1``, so exactly one of them is contractually
    active in any period from commencement onward, and none is active in both.
    The summed series is therefore exact, and ``occupied_area`` never
    double-counts. There is no vacant month between them: a pure renewal has
    no downtime.

    **Occupancy is integral branch physical occupancy** and keeps that name
    (D2 HD-D2-2). Within this scenario the suite is occupied or it is not.

    **The horizon truncates the series, never the assumption** (D0
    Section 8.6). If the successor commences beyond the projection its monthly
    values are simply all zero -- ``build_lease_monthly_schedule`` computes a
    lease only where the timeline reaches -- while
    ``successor_expiration_period`` and the successor ``Lease`` keep their true
    contractual dates. ``commences_within_projection`` records which case
    applies. Nothing is fabricated past the horizon and the projection is never
    extended.

    **The forward exit window is not special-cased.** Rollover is fully live in
    periods ``12H+1 .. 12H+12`` (D2 Section 11); a renewal commencing there is
    modelled by the identical rules, with no smoothing to stabilise terminal
    value.

    **One rollover only.** The successor is not itself rolled over when it
    expires. Recursion to the canonical projection end is D2.6's subject
    (D2 HD-D2-3), and this gate deliberately produces a single successor so the
    branch economics can be reviewed on their own.

    Pure and deterministic: no I/O, no mutation. The expiring ``Lease``, the
    ``Suite`` and the assumptions are read and never written, and the same
    inputs always produce a value-equal branch.
    """

    if market_schedule is None:
        market_schedule = build_market_rent_schedule(
            suite, property_defaults=property_defaults, months=months
        )
    elif market_schedule.suite_id != suite.suite_id:
        raise ValueError(
            f"market_schedule belongs to suite {market_schedule.suite_id!r}, "
            f"not to {suite.suite_id!r}; a renewal branch must price from its "
            "own suite's market rent."
        )
    if market_schedule.months != months:
        raise ValueError(
            "market_schedule was built against a different month sequence; a "
            "renewal branch must share one canonical timeline."
        )

    resolved: ResolvedMarketLeasing = market_schedule.resolved
    assumptions = resolved.assumptions

    _, expiration_period = lease_rent_periods(expiring, analysis_start=analysis_start)
    commencement_period = renewal_commencement_period(expiration_period)
    term_months = assumptions.renewal_term_months
    last_period = successor_expiration_period(
        commencement_period=commencement_period, term_months=term_months
    )

    first_period = months[0].period_index if months else 1
    horizon_period = months[-1].period_index if months else 0
    within = first_period <= commencement_period <= horizon_period

    if commencement_period < 1:
        # Only reachable from an input validation already rejects: a lease
        # that expired before the analysis start raises
        # LEASE_EXPIRED_BEFORE_ANALYSIS_START. Market rent is undefined before
        # Month 1, so this refuses rather than clamping `c` to 1 -- a silent
        # normalisation would price the successor off the wrong growth band
        # and report a plausible number for an unrepresentable scenario.
        raise ValueError(
            f"lease {expiring.lease_id!r} expires at period {expiration_period}, "
            f"so its renewal would commence at period {commencement_period}, "
            "before the analysis start. Market rent is undefined there; "
            "validate inputs before building a rollover branch."
        )

    # The market rate at `c`. Read from the canonical schedule whenever `c`
    # lies inside it; otherwise computed by the same authoritative function,
    # because a successor commencing past the horizon still has a real
    # contractual rent that D2.4's LC basis will need.
    if within:
        market_rate = market_rent_psf_at_period(market_schedule, commencement_period)
    else:
        market_rate = market_rent_psf_for_period(
            market_rent_psf=assumptions.market_rent_psf,
            market_rent_growth=assumptions.market_rent_growth,
            period=commencement_period,
        )

    starting_rent = renewal_starting_rent_psf(
        assumptions=assumptions,
        market_rent_psf_at_commencement=market_rate,
        commencement_period=commencement_period,
    )

    successor = build_renewal_successor_lease(
        expiring,
        suite=suite,
        analysis_start=analysis_start,
        commencement_period=commencement_period,
        term_months=term_months,
        starting_rent_psf=starting_rent,
        successor_escalation_pct=assumptions.successor_escalation_pct,
    )

    expiring_schedule = build_lease_monthly_schedule(
        expiring, analysis_start=analysis_start, months=months
    )
    successor_schedule = build_lease_monthly_schedule(
        successor, analysis_start=analysis_start, months=months
    )

    suite_area = suite.suite_area_sf
    contractual_base_rent: list[float] = []
    occupied_area: list[float] = []
    physical_occupancy: list[float] = []

    for position in range(len(months)):
        contractual_base_rent.append(
            expiring_schedule.contractual_base_rent[position]
            + successor_schedule.contractual_base_rent[position]
        )
        occupied = (
            expiring_schedule.occupied_area[position]
            + successor_schedule.occupied_area[position]
        )
        occupied_area.append(occupied)
        # suite_area_sf > 0 is guaranteed by validation, so this is defined.
        # The sum never exceeds one suite area, because the no-overlap
        # invariant means at most one schedule is active in any period --
        # which is what keeps this series integral (D2 HD-D2-2).
        physical_occupancy.append(occupied / suite_area)

    return RenewalBranch(
        suite_id=suite.suite_id,
        expiring_lease_id=expiring.lease_id,
        successor_lease_id=successor.lease_id,
        expiration_period=expiration_period,
        commencement_period=commencement_period,
        successor_expiration_period=last_period,
        commences_within_projection=within,
        resolved=resolved,
        market_rent_psf_at_commencement=market_rate,
        renewal_rent_psf=assumptions.renewal_rent_psf,
        renewal_rent_spread=assumptions.renewal_rent_spread,
        starting_rent_psf=starting_rent,
        term_months=term_months,
        successor_escalation_pct=assumptions.successor_escalation_pct,
        successor_lease=successor,
        months=months,
        expiring_schedule=expiring_schedule,
        successor_schedule=successor_schedule,
        contractual_base_rent=tuple(contractual_base_rent),
        occupied_area=tuple(occupied_area),
        physical_occupancy=tuple(physical_occupancy),
    )
