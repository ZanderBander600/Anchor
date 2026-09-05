"""Sprint D Gates D2.2/D2.3 -- the deterministic rollover branches.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Sections 4.2, 6, 7, 9.1, 9.2, 10 and 14, and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 8.1, 8.4-8.6 and 24.3 exactly; those documents govern on any
discrepancy.

**The two questions this module answers.** For one expiring lease:

- *if the tenant renews with certainty* -- when does the successor begin, what
  does it pay, when does it expire (D2.2);
- *if the tenant does not renew* -- how long is the suite vacant, when does the
  replacement begin, what market rent applies then, and how much rent is
  actually collected once concessions are consumed (D2.3).

**These are the two branches of the approved composition** (D2 HD-D2-1). A
rollover is two independent, complete branch schedules weighted only at the
monthly *output* level. They are conceptually the ``p = 1`` and ``p = 0``
endpoints, but **no probability exists here**: the weight arrives at D2.5,
which must reproduce each branch bit-identically at its own endpoint. Nothing
in this module weights, averages, blends or rounds anything.

**Three formulas this module deliberately does not own.**

1. **Market rent.** ``market.py`` is the single authority. A successor's
   starting rent is read from the canonical market-rent schedule through
   ``market_rent_psf_at_period``, or -- for D0 Section 24.3's explicit renewal
   level -- computed by calling ``market.market_rent_psf_for_period`` with a
   different base. There is no second growth formula here.
2. **Contractual rent.** ``rent.py`` is the single authority. A successor is an
   *ordinary contractual lease* from its commencement (D2 Section 10), so its
   monthly face rent comes from ``rent.build_lease_monthly_schedule`` -- the
   exact D1 formula, on the successor's own contractual chronology. This
   module constructs a ``Lease`` and hands it over; it never multiplies a rent
   rate by an area.
3. **The expiring lease's rent.** It is reused unchanged. D2 never recomputes
   an in-place lease, and no market assumption may touch one (D0 Section 24.4).

**The two clocks** (D2 Section 10): market growth prices a successor's
*starting* rent **once**, at commencement ``c``; from ``c`` onward the
successor escalates on **its own** anniversaries at
``successor_escalation_pct``. Market rent keeps growing in the background for
the *next* rollover and has no further effect on this lease. Setting the two
rates equal makes them numerically coincide; that is a coincidence of inputs,
never an identity of concepts (failure mode FM-D2-14).

**Face rent and cash rent are different series and both are kept.** Downtime
and free rent reduce the rent *recognised*; neither reduces contractual face
rent. D2.4's LC basis is computed on face (failure modes FM-D2-10, FM-D2-11b),
so collapsing the two would silently understate every commission.

**Downtime and free rent are different concepts** (D2 Section 7.4) and are
never collapsed into one concession factor: downtime means *no tenant is in
possession*, drives branch physical occupancy to zero and stops D3 recoveries;
free rent means *a tenant is in possession but is not paying base rent*, leaves
occupancy untouched, and leaves recoveries to the lease's own structure. They
are sequential stages of one waterfall, not competing multiplicative factors.

**Leasing costs are computed but never mixed in.** D2.4 adds each branch's own
TI and LC, from ``leasing_costs.py``, on a basis from
``rent.contractual_face_rent_over_full_term``. Both are strictly below NOI and
this module never lets either touch a rent, cash or occupancy series -- they
travel as their own monthly outputs alongside.

**Deliberately absent, all of it later work:** ``renewal_probability`` and
every expected-value composition (D2.5); the second and later rollovers,
recursion and any computational limit (D2.6). Each branch here produces exactly
one successor and never rolls it over.
"""

from __future__ import annotations

from datetime import date
from math import floor, isfinite

from .calendar import last_day_of_month, month_start_for_index
from .contracts import (
    EscalationBasis,
    Lease,
    LeaseMonthlySchedule,
    LeaseOrigin,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    MarketRentSchedule,
    ModelMonth,
    NewTenantBranch,
    RenewalBranch,
    ResolvedMarketLeasing,
    Suite,
)
from .leasing_costs import (
    leasing_commission_amount,
    leasing_cost_event_period,
    leasing_cost_event_series,
    tenant_improvement_amount,
)
from .market import (
    build_market_rent_schedule,
    market_rent_psf_at_period,
    market_rent_psf_for_period,
)
from .rent import (
    build_lease_monthly_schedule,
    contractual_face_rent_over_full_term,
    lease_rent_periods,
)


#: Suffixes appended to the expiring lease's id to name each branch's
#: successor. Deterministic and derived, so the same rent roll always produces
#: the same successor ids and a rollover log is reproducible run to run. The
#: two differ so a renewal successor and a new-tenant successor for the same
#: suite are never confused in an audit trail.
_RENEWAL_SUCCESSOR_SUFFIX = "::renewal"
_NEW_TENANT_SUCCESSOR_SUFFIX = "::new"


# =============================================================================
# Successor timing -- D2 Section 6.1
# =============================================================================


def _require_downtime(downtime_months: float) -> float:
    if isinstance(downtime_months, bool) or not isinstance(
        downtime_months, (int, float)
    ):
        raise TypeError(
            f"downtime_months must be a number of months; got {downtime_months!r}."
        )
    if not isfinite(downtime_months):
        raise ValueError("downtime_months must be a finite number of months.")
    if downtime_months < 0:
        raise ValueError(
            f"downtime_months must be greater than or equal to 0; "
            f"got {downtime_months!r}."
        )
    return float(downtime_months)


def successor_commencement_period(
    *, expiration_period: int, downtime_months: float
) -> int:
    """Return the successor's rent commencement period ``c``.

    D2 Section 6.1 / D0 Section 8.5, exactly::

        c = e + 1 + floor(D)

    The periods ``e+1 … c-1`` are **fully vacant** -- exactly ``floor(D)`` of
    them -- and period ``c`` carries the boundary factor ``1 - frac(D)``. When
    ``D`` is a whole number the factor is ``1.00`` and ``c`` is an ordinary
    full month, so the rule degenerates with no special case. ``D = 0`` gives
    ``c = e + 1``, the immediate-commencement case D2.2 proved.

    ``e`` is the expiring lease's **raw, unclamped** last rent period, from
    ``rent.lease_rent_periods``. Using the window-clamped
    ``LeaseMonthlySchedule.last_rent_period`` instead would silently roll a
    lease at the projection horizon rather than at its real expiration --
    exactly the clamping trap failure mode FM-5 exists to guard on the
    contractual side.

    **Fractional downtime never produces a fractional date.** ``c`` is a whole
    canonical period and the successor's contractual dates stay month-aligned,
    as D1 requires; the fraction is carried entirely by the occupancy factor
    below (D2 Section 6.4). There is no day count and no mid-month lease date.

    Pure integer arithmetic on canonical period indices.
    """

    if isinstance(expiration_period, bool) or not isinstance(expiration_period, int):
        raise TypeError(
            "expiration_period must be a canonical model month index; "
            f"got {expiration_period!r}."
        )

    return expiration_period + 1 + floor(_require_downtime(downtime_months))


def renewal_commencement_period(expiration_period: int) -> int:
    """Return ``e + 1`` -- the zero-downtime commencement period.

    Retained from D2.2, where a pure renewal had no downtime concept at all.
    It now delegates to ``successor_commencement_period`` with ``D = 0`` rather
    than restating ``e + 1``, so there is exactly one commencement formula in
    the package and this name cannot drift from it.
    """

    return successor_commencement_period(
        expiration_period=expiration_period, downtime_months=0.0
    )


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

    **Fractional downtime never extends the term.** A successor that recognises
    only ``1 - frac(D)`` of its first month still occupies exactly
    ``term_months`` canonical periods; the shortfall is a cash-recognition
    artifact of the monthly model, not a contractual extension.

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
# Step 1 of the waterfall -- downtime sets occupancy (D2 Section 7.1)
# =============================================================================


def successor_occupancy_factors(
    *,
    months: tuple[ModelMonth, ...],
    commencement_period: int,
    last_rent_period: int,
    downtime_months: float,
) -> tuple[float, ...]:
    """Return the successor's month-equivalent rent-eligibility factor ``O_m``.

    D2 Section 7.1, Step 1::

        O_m = 0                   before c, and after the successor's term
        O_m = 1 - frac(D)         at the commencement period c
        O_m = 1                   for every full successor period thereafter

    **What ``O_m`` is.** A *month-equivalent economic exposure* fraction: the
    portion of that calendar period for which the successor is economically
    present under Anchor's monthly model. ``O_September = 0.75`` after 2.25
    months of downtime means the successor is present for three-quarters of
    September -- **not** that three-quarters of the suite exists, and not that
    three-quarters of it is leased at month-end.

    **What ``O_m`` is not.** It is emphatically not branch physical occupancy.
    D2 HD-D2-2 binds branch physical occupancy to be **integral** and to keep
    the name ``physical_occupancy``; in the boundary month the successor is in
    possession by month-end, so branch physical occupancy there is ``1``. The
    two series are different quantities, carry different names, and failure
    mode FM-D2-19 exists to catch anyone publishing a fractional series under
    the physical name.

    **The identity that anchors the rule**: total rent-eligible
    month-equivalents forgone between expiry and full occupancy equals exactly
    ``D``, for every real ``D >= 0`` -- ``floor(D)`` fully vacant periods
    contributing ``1.0`` each plus ``frac(D)`` at the boundary
    (D2 Section 6.2). Off-by-one forms such as ``e + floor(D)`` or
    ``e + 1 + ceil(D)`` break it, which is failure mode FM-D2-5.

    Periods outside the successor's term are ``0`` because the successor is not
    there -- before ``c`` it has not commenced and after ``last_rent_period``
    its term has ended. That zero is not vacancy of the *suite*: the expiring
    lease may still be in possession before ``c``, which the branch's own
    physical-occupancy series records.
    """

    boundary = 1.0 - (
        _require_downtime(downtime_months) - floor(_require_downtime(downtime_months))
    )

    factors: list[float] = []
    for month in months:
        period = month.period_index
        if period < commencement_period or period > last_rent_period:
            factors.append(0.0)
        elif period == commencement_period:
            factors.append(boundary)
        else:
            factors.append(1.0)
    return tuple(factors)


# =============================================================================
# Step 2 of the waterfall -- free rent is consumed against occupancy
# =============================================================================


def free_rent_waterfall(
    occupancy_factors: tuple[float, ...], *, free_rent_months: float
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return ``(free_abatement_m, cash_rent_factor_m)`` month by month.

    D2 Section 7.1, Step 2 -- **sequential**, walking the periods
    chronologically and carrying ``remaining_free_rent_months``::

        free_abatement_m    = min(O_m, remaining_free_rent_months)
        cash_rent_factor_m  = O_m - free_abatement_m
        remaining          -= free_abatement_m

    **Why sequential and not multiplicative** (HD-D2-4, the rejected method).
    Multiplying an independent downtime factor by an independent free-rent
    factor consumed a *whole* free month in a fractional commencement period
    while abating only a *fraction* of a month's rent -- silently
    shortchanging the concession. The waterfall makes ``free_rent_months``
    mean what it says: a count of full month-equivalents of base rent abated.

    **Free rent is consumed only while the successor is economically
    present.** During a fully vacant downtime period ``O_m`` is ``0``, so
    ``min(0, remaining)`` is ``0`` and nothing is consumed -- the concession is
    preserved for the months the tenant is actually there. That falls out of
    the formula rather than needing a special case, which is the point of
    ordering the two steps.

    **Guarantee**: ``sum(free_abatement_m) == free_rent_months`` exactly,
    subject to validation's over-grant rule (D2 Section 7.5) and to ordinary
    floating-point representation. Failure mode FM-D2-7c is the test of it.

    Free rent never touches ``O_m``: an abated month is a fully occupied month
    whose base rent happens to be zero. That distinction is load-bearing for D3
    recoveries, where a tenant in possession keeps reimbursing operating
    expenses while paying no base rent (D2 Section 7.3).
    """

    if isinstance(free_rent_months, bool) or not isinstance(
        free_rent_months, (int, float)
    ):
        raise TypeError(
            f"free_rent_months must be a number of months; got {free_rent_months!r}."
        )
    if not isfinite(free_rent_months):
        raise ValueError("free_rent_months must be a finite number of months.")
    if free_rent_months < 0:
        raise ValueError(
            f"free_rent_months must be greater than or equal to 0; "
            f"got {free_rent_months!r}."
        )

    remaining = float(free_rent_months)
    abatement: list[float] = []
    cash_factor: list[float] = []

    for occupancy in occupancy_factors:
        consumed = min(occupancy, remaining)
        abatement.append(consumed)
        cash_factor.append(occupancy - consumed)
        remaining -= consumed

    return tuple(abatement), tuple(cash_factor)


def maximum_consumable_free_rent_months(
    *, term_months: int, downtime_months: float
) -> float:
    """Return the largest concession the successor's term can absorb.

    D2 Section 7.5::

        max = term_months - frac(downtime_months)

    The waterfall can absorb at most ``sum(O_m)`` month-equivalents over the
    successor's contract term: the first period contributes ``1 - frac(D)`` and
    the remaining ``T - 1`` periods contribute ``1.0`` each.

    **Measured over the FULL contractual term, never the visible projection.**
    A 60-month successor of which only eight months fall inside the canonical
    window can still legitimately carry a twelve-month concession; the schedule
    simply ends with free rent still being consumed. Validating against the
    visible portion would reject valid underwriting because of where the hold
    period happens to end.
    """

    downtime = _require_downtime(downtime_months)
    return term_months - (downtime - floor(downtime))


# =============================================================================
# Successor pricing
# =============================================================================


def renewal_starting_rent_psf(
    *,
    assumptions: MarketLeasingAssumptions,
    market_rent_psf_at_commencement: float,
    commencement_period: int,
) -> float:
    """Return a **renewal** successor's starting rent in ``$/SF/year`` at ``c``.

    D0 Section 24.3, exactly, in its stated precedence order::

        renewal_rent_psf, grown from analysis_start_date to c   (if not None)
          > MarketRentPSF(c) * (1 + renewal_rent_spread)

    **The explicit level wins when supplied.** ``renewal_rent_psf`` is measured
    on the *same* temporal anchor as ``market_rent_psf`` -- as of
    ``analysis_start_date`` -- so it must be grown to the commencement period
    before use::

        RenewalRentPSF(c) = renewal_rent_psf * (1 + market_rent_growth) ** floor((c - 1) / 12)

    That growth is performed by ``market.market_rent_psf_for_period``, the one
    authoritative implementation, applied to a different base. This module does
    not restate the formula. The phrase "today's dollars" is deliberately never
    used: "today" is neither the analysis start nor the rollover date.

    **Otherwise the successor prices off market.** ``renewal_rent_spread`` is a
    discount or premium **to market at commencement**, so ``0.0`` renews at
    market, ``-0.05`` renews 5% below it and ``+0.05`` 5% above.

    ``c`` already reflects the branch's own downtime, so a renewal delayed
    across a market-growth anniversary prices in the later band -- the rate is
    read at the delayed commencement, never at expiry (D2 Section 9.2).

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


def new_tenant_starting_rent_psf(*, market_rent_psf_at_commencement: float) -> float:
    """Return a **new tenant's** starting rent in ``$/SF/year`` at ``c``.

    A new letting *is* market, so the rate is ``MarketRentPSF(c)`` and nothing
    else. There is deliberately no ``new_rent_psf`` field and no new-tenant
    spread: a renewal is negotiated *relative* to market and therefore needs
    both an explicit level and a spread, while a replacement tenant is let at
    the prevailing rate. D2 Section 12 records the asymmetry as correct rather
    than as a gap in D0.

    ``renewal_rent_spread`` and ``renewal_rent_psf`` are **never** consulted
    here. Applying a renewal concession to a replacement tenant is precisely
    the cross-branch contamination the two-branch method exists to prevent.

    The function exists rather than the identity being inlined so the pricing
    rule has a name, one home and one test, symmetrically with
    ``renewal_starting_rent_psf``. ``c`` already reflects the branch's own
    downtime, so a market step during a vacancy is priced in (D2 Section 9.2,
    failure mode FM-18).
    """

    return market_rent_psf_at_commencement


# =============================================================================
# The successor lease
# =============================================================================


def build_successor_lease(
    expiring: Lease,
    *,
    suite: Suite,
    analysis_start: date,
    commencement_period: int,
    term_months: int,
    starting_rent_psf: float,
    successor_escalation_pct: float,
    lease_id_suffix: str,
) -> Lease:
    """Return a rollover successor as an ordinary contractual ``Lease``.

    **The successor is an assumption, not a known tenant** (D0 Section 8.4).
    Two properties are mandatory and are set here rather than left to a
    caller: ``tenant_name`` is ``None``, and ``origin`` is
    ``LeaseOrigin.SUCCESSOR``. Together they make failure mode FM-D2-18 --
    presenting a modelled successor as a signed tenancy -- unrepresentable
    rather than merely discouraged.

    **Why it is a plain ``Lease``.** D2 Section 10: from commencement the
    successor *is* an ordinary contractual lease. Making it one means its face
    rent runs through the single D1 formula in ``rent.py``, on its own
    contractual chronology, with ``EscalationBasis.LEASE_ANNIVERSARY`` counting
    from its own commencement. No successor-specific rent engine exists, so
    none can drift from the contractual one.

    **Dates stay month-aligned.** ``rent_commencement_date`` is the first day
    of canonical month ``c``; ``lease_expiration_date`` is the **last day** of
    canonical month ``c + term - 1``, inclusive, exactly as D1 requires. Both
    come from the canonical calendar helpers, never from day arithmetic.
    Fractional downtime does **not** move these dates -- it is carried entirely
    by the occupancy factor (D2 Section 6.4), because a non-month-aligned
    contractual date remains a D1 validation ERROR and D2 does not blur the
    two.

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

    ``lease_id_suffix`` distinguishes the two branches' successors for the same
    expiring lease, so a rollover log can never confuse them.
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
        lease_id=f"{expiring.lease_id}{lease_id_suffix}",
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
    """Return the **renewal** successor lease. See ``build_successor_lease``.

    Retained from D2.2 as the renewal-side name; it adds nothing but the
    branch's id suffix, so the two branches cannot construct successors by
    different rules.
    """

    return build_successor_lease(
        expiring,
        suite=suite,
        analysis_start=analysis_start,
        commencement_period=commencement_period,
        term_months=term_months,
        starting_rent_psf=starting_rent_psf,
        successor_escalation_pct=successor_escalation_pct,
        lease_id_suffix=_RENEWAL_SUCCESSOR_SUFFIX,
    )


# =============================================================================
# The shared branch core
# =============================================================================


class _BranchCore:
    """The fields every rollover branch shares, computed once.

    A plain internal carrier, not a contract. Both public builders assemble
    their frozen result from one of these, so the timing, the occupancy
    factors, the free-rent waterfall, the face/cash split and the physical
    occupancy series are computed by **one** implementation for both branches
    (D2 Section 4.2: each branch is calculated independently and completely,
    but by the same rules).
    """

    __slots__ = (
        "expiration_period",
        "commencement_period",
        "last_period",
        "within",
        "market_rate",
        "starting_rent",
        "successor",
        "expiring_schedule",
        "successor_schedule",
        "contractual_base_rent",
        "occupancy_factor",
        "abatement_months",
        "cash_factor",
        "free_rent",
        "cash_base_rent",
        "occupied_area",
        "physical_occupancy",
        "full_term_face_rent",
        "ti_amount",
        "lc_amount",
        "tenant_improvements",
        "leasing_commissions",
    )


def _resolve_market_schedule(
    suite: Suite,
    *,
    months: tuple[ModelMonth, ...],
    property_defaults: MarketLeasingAssumptions,
    market_schedule: MarketRentSchedule | None,
) -> MarketRentSchedule:
    if market_schedule is None:
        return build_market_rent_schedule(
            suite, property_defaults=property_defaults, months=months
        )
    if market_schedule.suite_id != suite.suite_id:
        raise ValueError(
            f"market_schedule belongs to suite {market_schedule.suite_id!r}, "
            f"not to {suite.suite_id!r}; a rollover branch must price from its "
            "own suite's market rent."
        )
    if market_schedule.months != months:
        raise ValueError(
            "market_schedule was built against a different month sequence; a "
            "rollover branch must share one canonical timeline."
        )
    return market_schedule


def _build_branch_core(
    expiring: Lease,
    *,
    suite: Suite,
    analysis_start: date,
    months: tuple[ModelMonth, ...],
    market_schedule: MarketRentSchedule,
    term_months: int,
    downtime_months: float,
    free_rent_months: float,
    successor_escalation_pct: float,
    price_successor,
    lease_id_suffix: str,
    ti_psf: float,
    lc_pct: float,
    leasing_commission_method: LeasingCommissionMethod,
) -> _BranchCore:
    """Compute one branch end to end. Shared by both public builders."""

    assumptions = market_schedule.resolved.assumptions

    _, expiration_period = lease_rent_periods(expiring, analysis_start=analysis_start)
    commencement_period = successor_commencement_period(
        expiration_period=expiration_period, downtime_months=downtime_months
    )
    last_period = successor_expiration_period(
        commencement_period=commencement_period, term_months=term_months
    )

    if commencement_period < 1:
        # Only reachable from an input validation already rejects: a lease that
        # expired before the analysis start raises
        # LEASE_EXPIRED_BEFORE_ANALYSIS_START. Market rent is undefined before
        # Month 1, so this refuses rather than clamping `c` to 1 -- a silent
        # normalisation would price the successor off the wrong growth band and
        # report a plausible number for an unrepresentable scenario.
        raise ValueError(
            f"lease {expiring.lease_id!r} expires at period {expiration_period} "
            f"with {downtime_months!r} months of downtime, so its successor "
            f"would commence at period {commencement_period}, before the "
            "analysis start. Market rent is undefined there; validate inputs "
            "before building a rollover branch."
        )

    first_period = months[0].period_index if months else 1
    horizon_period = months[-1].period_index if months else 0
    within = first_period <= commencement_period <= horizon_period

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

    starting_rent = price_successor(market_rate, commencement_period)

    successor = build_successor_lease(
        expiring,
        suite=suite,
        analysis_start=analysis_start,
        commencement_period=commencement_period,
        term_months=term_months,
        starting_rent_psf=starting_rent,
        successor_escalation_pct=successor_escalation_pct,
        lease_id_suffix=lease_id_suffix,
    )

    expiring_schedule = build_lease_monthly_schedule(
        expiring, analysis_start=analysis_start, months=months
    )
    successor_schedule = build_lease_monthly_schedule(
        successor, analysis_start=analysis_start, months=months
    )

    occupancy_factor = successor_occupancy_factors(
        months=months,
        commencement_period=commencement_period,
        last_rent_period=last_period,
        downtime_months=downtime_months,
    )
    abatement_months, cash_factor = free_rent_waterfall(
        occupancy_factor, free_rent_months=free_rent_months
    )

    suite_area = suite.suite_area_sf
    contractual_base_rent: list[float] = []
    free_rent: list[float] = []
    cash_base_rent: list[float] = []
    occupied_area: list[float] = []
    physical_occupancy: list[float] = []

    for position in range(len(months)):
        expiring_face = expiring_schedule.contractual_base_rent[position]
        successor_face = successor_schedule.contractual_base_rent[position]

        # FACE rent -- gross, reduced by neither downtime nor free rent. The
        # successor's own schedule is already zero before commencement and
        # after expiration, so downtime needs no subtraction here; the
        # boundary month carries a FULL month of face rent and only its cash
        # recognition is scaled (failure mode FM-D2-11b).
        contractual_base_rent.append(expiring_face + successor_face)

        # The abatement line, and the cash actually collected. The expiring
        # lease is a signed in-place lease: it collects its face rent in full,
        # and neither concession applies to it.
        free_rent.append(successor_face * abatement_months[position])
        cash_base_rent.append(
            expiring_face + successor_face * cash_factor[position]
        )

        # INTEGRAL branch physical occupancy (D2 HD-D2-2). Derived from
        # contractual activity, never from dollars and never from the
        # fractional occupancy factor: in the boundary month the successor is
        # in possession by month-end, so the suite is occupied. Fully vacant
        # downtime periods have neither lease active and are genuinely 0.
        occupied = (
            expiring_schedule.occupied_area[position]
            + successor_schedule.occupied_area[position]
        )
        occupied_area.append(occupied)
        physical_occupancy.append(occupied / suite_area)

    # --- leasing costs, strictly below NOI (D2.4) ---
    #
    # Computed from the successor lease and the branch's own rates, and never
    # from any series above: the loop that produced rent, cash and occupancy
    # has already finished, and nothing below writes back into it.
    #
    # The LC basis is the successor's FULL contractual term, which may run past
    # the projection horizon, so it comes from the successor `Lease` rather
    # than from `successor_schedule` -- summing the visible schedule would
    # silently truncate the commission (failure mode FM-17).
    full_term_face_rent = contractual_face_rent_over_full_term(successor)
    ti_amount = tenant_improvement_amount(
        ti_psf=ti_psf, leased_area_sf=successor.leased_area_sf
    )
    lc_amount = leasing_commission_amount(
        lc_pct=lc_pct,
        full_term_contractual_face_rent=full_term_face_rent,
        method=leasing_commission_method,
    )
    event_period = leasing_cost_event_period(
        months=months, successor_occupancy_factor=occupancy_factor
    )

    core = _BranchCore()
    core.full_term_face_rent = full_term_face_rent
    core.ti_amount = ti_amount
    core.lc_amount = lc_amount
    core.tenant_improvements = leasing_cost_event_series(
        months=months, event_period=event_period, amount=ti_amount
    )
    core.leasing_commissions = leasing_cost_event_series(
        months=months, event_period=event_period, amount=lc_amount
    )
    core.expiration_period = expiration_period
    core.commencement_period = commencement_period
    core.last_period = last_period
    core.within = within
    core.market_rate = market_rate
    core.starting_rent = starting_rent
    core.successor = successor
    core.expiring_schedule = expiring_schedule
    core.successor_schedule = successor_schedule
    core.contractual_base_rent = tuple(contractual_base_rent)
    core.occupancy_factor = occupancy_factor
    core.abatement_months = abatement_months
    core.cash_factor = cash_factor
    core.free_rent = tuple(free_rent)
    core.cash_base_rent = tuple(cash_base_rent)
    core.occupied_area = tuple(occupied_area)
    core.physical_occupancy = tuple(physical_occupancy)
    return core


# =============================================================================
# The two public branch builders
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
    boundary the other builders established -- call
    ``validation.require_valid_lease_level_inputs`` with the market
    assumptions first. Re-validating here would create a second validation
    authority whose behaviour could drift from the first.

    Pricing follows D0 Section 24.3 (explicit level, else market at ``c``
    adjusted by the spread); timing, the occupancy factors, the free-rent
    waterfall and the face/cash split are the shared mechanics documented
    above.

    **Renewal downtime is typically zero** -- a renewing tenant does not vacate
    -- and at ``renewal_downtime_months = 0.0`` with
    ``renewal_free_rent_months = 0.0`` this reproduces the accepted D2.2 result
    exactly: ``c = e + 1``, no vacant month, every occupancy and cash factor
    ``1.0`` inside the term, and ``cash_base_rent == contractual_base_rent``.
    Non-zero renewal downtime delays ``c``, which correctly reprices the
    renewal in a later market band if it crosses an anniversary.

    **One rollover only.** The successor is not itself rolled over when it
    expires; recursion to the canonical projection end is D2.6's subject
    (D2 HD-D2-3).

    Pure and deterministic: no I/O, no mutation.
    """

    schedule = _resolve_market_schedule(
        suite,
        months=months,
        property_defaults=property_defaults,
        market_schedule=market_schedule,
    )
    resolved: ResolvedMarketLeasing = schedule.resolved
    assumptions = resolved.assumptions

    core = _build_branch_core(
        expiring,
        suite=suite,
        analysis_start=analysis_start,
        months=months,
        market_schedule=schedule,
        term_months=assumptions.renewal_term_months,
        downtime_months=assumptions.renewal_downtime_months,
        free_rent_months=assumptions.renewal_free_rent_months,
        successor_escalation_pct=assumptions.successor_escalation_pct,
        price_successor=lambda rate, period: renewal_starting_rent_psf(
            assumptions=assumptions,
            market_rent_psf_at_commencement=rate,
            commencement_period=period,
        ),
        lease_id_suffix=_RENEWAL_SUCCESSOR_SUFFIX,
        ti_psf=assumptions.renewal_ti_psf,
        lc_pct=assumptions.renewal_lc_pct,
        leasing_commission_method=assumptions.leasing_commission_method,
    )

    return RenewalBranch(
        suite_id=suite.suite_id,
        expiring_lease_id=expiring.lease_id,
        successor_lease_id=core.successor.lease_id,
        expiration_period=core.expiration_period,
        commencement_period=core.commencement_period,
        successor_expiration_period=core.last_period,
        commences_within_projection=core.within,
        resolved=resolved,
        market_rent_psf_at_commencement=core.market_rate,
        renewal_rent_psf=assumptions.renewal_rent_psf,
        renewal_rent_spread=assumptions.renewal_rent_spread,
        starting_rent_psf=core.starting_rent,
        term_months=assumptions.renewal_term_months,
        successor_escalation_pct=assumptions.successor_escalation_pct,
        downtime_months=assumptions.renewal_downtime_months,
        free_rent_months=assumptions.renewal_free_rent_months,
        successor_lease=core.successor,
        months=months,
        expiring_schedule=core.expiring_schedule,
        successor_schedule=core.successor_schedule,
        contractual_base_rent=core.contractual_base_rent,
        successor_occupancy_factor=core.occupancy_factor,
        free_rent_abatement_months=core.abatement_months,
        cash_rent_factor=core.cash_factor,
        free_rent=core.free_rent,
        cash_base_rent=core.cash_base_rent,
        occupied_area=core.occupied_area,
        physical_occupancy=core.physical_occupancy,
        ti_psf=assumptions.renewal_ti_psf,
        lc_pct=assumptions.renewal_lc_pct,
        leasing_commission_method=assumptions.leasing_commission_method,
        full_term_contractual_face_rent=core.full_term_face_rent,
        tenant_improvement_amount=core.ti_amount,
        leasing_commission_amount=core.lc_amount,
        tenant_improvements=core.tenant_improvements,
        leasing_commissions=core.leasing_commissions,
    )


def build_new_tenant_branch(
    expiring: Lease,
    *,
    suite: Suite,
    analysis_start: date,
    months: tuple[ModelMonth, ...],
    property_defaults: MarketLeasingAssumptions,
    market_schedule: MarketRentSchedule | None = None,
) -> NewTenantBranch:
    """Return the complete pure new-tenant scenario for one expiring lease.

    **Precondition: the inputs are already validated**, exactly as for the
    renewal branch.

    The sequence, each step delegating to the module that owns it:

    1. Resolve the suite's market leasing assumptions once (``market.py``,
       D0 Section 24.5), or reuse a schedule the caller already built.
    2. ``e`` = the expiring lease's raw last rent period;
       ``c = e + 1 + floor(new_downtime_months)``.
    3. Read ``MarketRentPSF(c)`` from the canonical market-rent schedule --
       the rate at the **delayed** commencement, so a market step occurring
       during the vacancy is priced in (failure mode FM-18).
    4. Price at that rate. A new letting *is* market: no renewal spread and no
       explicit renewal level is ever consulted.
    5. Construct the successor ``Lease`` and build its face-rent schedule
       through the D1 rent engine.
    6. Apply the downtime occupancy factors, then the free-rent waterfall, and
       derive cash from face.

    **The suite is genuinely vacant during downtime.** Periods ``e+1 … c-1``
    have neither lease active, so branch physical occupancy is ``0`` there --
    a real vacancy, not an abatement. In the boundary period ``c`` the
    successor is in possession by month-end, so physical occupancy is ``1``
    while only ``1 - frac(D)`` of the month's rent is recognised.

    **One rollover only.** Recursion is D2.6's subject.

    Pure and deterministic: no I/O, no mutation.
    """

    schedule = _resolve_market_schedule(
        suite,
        months=months,
        property_defaults=property_defaults,
        market_schedule=market_schedule,
    )
    resolved: ResolvedMarketLeasing = schedule.resolved
    assumptions = resolved.assumptions

    core = _build_branch_core(
        expiring,
        suite=suite,
        analysis_start=analysis_start,
        months=months,
        market_schedule=schedule,
        term_months=assumptions.new_term_months,
        downtime_months=assumptions.new_downtime_months,
        free_rent_months=assumptions.new_free_rent_months,
        successor_escalation_pct=assumptions.successor_escalation_pct,
        price_successor=lambda rate, period: new_tenant_starting_rent_psf(
            market_rent_psf_at_commencement=rate
        ),
        lease_id_suffix=_NEW_TENANT_SUCCESSOR_SUFFIX,
        ti_psf=assumptions.new_ti_psf,
        lc_pct=assumptions.new_lc_pct,
        leasing_commission_method=assumptions.leasing_commission_method,
    )

    return NewTenantBranch(
        suite_id=suite.suite_id,
        expiring_lease_id=expiring.lease_id,
        successor_lease_id=core.successor.lease_id,
        expiration_period=core.expiration_period,
        commencement_period=core.commencement_period,
        successor_expiration_period=core.last_period,
        commences_within_projection=core.within,
        resolved=resolved,
        market_rent_psf_at_commencement=core.market_rate,
        starting_rent_psf=core.starting_rent,
        term_months=assumptions.new_term_months,
        successor_escalation_pct=assumptions.successor_escalation_pct,
        downtime_months=assumptions.new_downtime_months,
        free_rent_months=assumptions.new_free_rent_months,
        successor_lease=core.successor,
        months=months,
        expiring_schedule=core.expiring_schedule,
        successor_schedule=core.successor_schedule,
        contractual_base_rent=core.contractual_base_rent,
        successor_occupancy_factor=core.occupancy_factor,
        free_rent_abatement_months=core.abatement_months,
        cash_rent_factor=core.cash_factor,
        free_rent=core.free_rent,
        cash_base_rent=core.cash_base_rent,
        occupied_area=core.occupied_area,
        physical_occupancy=core.physical_occupancy,
        ti_psf=assumptions.new_ti_psf,
        lc_pct=assumptions.new_lc_pct,
        leasing_commission_method=assumptions.leasing_commission_method,
        full_term_contractual_face_rent=core.full_term_face_rent,
        tenant_improvement_amount=core.ti_amount,
        leasing_commission_amount=core.lc_amount,
        tenant_improvements=core.tenant_improvements,
        leasing_commissions=core.leasing_commissions,
    )
