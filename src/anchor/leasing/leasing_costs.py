"""Sprint D Gate D2.4 -- tenant improvements and leasing commissions.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Section 8 and
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Sections 11 and 12 exactly; those documents govern on any discrepancy.

**The question this gate answers.** For one independently calculated successor
branch: how much TI is required, how much LC is required, and when do those
cash outflows occur. Nothing else. "What is the *expected* leasing cost" is a
probability question and belongs to D2.5.

**Both are strictly below NOI** (D0 Sections 11 and 12.2). Neither reduces
contractual base rent, cash base rent, free rent, the successor occupancy
factor, physical occupancy, EGI, NOI, DSCR, debt yield or exit NOI. This module
produces monthly cost series that sit alongside the rent series and never
modify them; the guardrail suite proves the independence in both directions.

**Neither is ever charged on an in-place D1 lease.** An existing tenant's
improvements and commission were funded by the seller before acquisition, so
charging them again is failure mode FM-11. Only a rollover successor incurs
them, which is why this module is reached only from a branch builder.

**Two homes, one formula each.** TI is ``ti_psf x leased_area_sf``; LC is
``lc_pct x`` the successor's full-term contractual face rent. The face-rent
basis itself is **not** computed here -- it comes from
``rent.contractual_face_rent_over_full_term``, which reaches the same
``monthly_base_rent`` the D1 schedule uses, so there is exactly one
contractual-rent formula in the package and no closed-form shortcut anywhere.

**Deliberately absent:** ``renewal_probability`` and every expected-value
composition (D2.5); recursion (D2.6); and every downstream integration channel
-- no ``leasing_costs_by_year``, no change to ``AcquisitionResults`` or
``OperatingProjectionLike``. D4 owns the decision about how below-NOI costs
reach the shared acquisition engine; D2.4 leaves authoritative monthly
Lease-Level outputs ready for it.
"""

from __future__ import annotations

from ..engine.contracts import ensure_finite
from .contracts import LeasingCommissionMethod, ModelMonth


def tenant_improvement_amount(*, ti_psf: float, leased_area_sf: float) -> float:
    """Return the successor's total TI allowance, in dollars.

    ```
    TI = ti_psf * leased_area_sf
    ```

    D0 Section 11. A single lump obligation triggered by commencement, and
    deliberately **not** adjusted by anything else:

    - **not** prorated by the downtime boundary factor -- the fact that
      Anchor's monthly grid recognises only 75% of a fractional first month's
      *rent* does not divide the *allowance*;
    - **not** reduced by free rent, which is a base-rent concession;
    - **not** scaled by the term, which TI does not depend on;
    - **not** weighted by any probability, which does not exist until D2.5.

    A draw schedule is not supported in D2 (D0 Section 11): a draw moves a
    below-NOI cost by a few months, crossing at most one year boundary after
    annual aggregation, which does not justify a schedule contract, its
    validation surface and its UI. It is additive later.

    ``leased_area_sf`` is the successor's own area, which equals the suite area
    in D1-D3. No rounding, no ``Decimal``; wrapped in ``ensure_finite`` like
    every other Anchor calculator.
    """

    return ensure_finite("tenant_improvement_amount", ti_psf * leased_area_sf)


def leasing_commission_amount(
    *,
    lc_pct: float,
    full_term_contractual_face_rent: float,
    method: LeasingCommissionMethod,
) -> float:
    """Return the successor's total leasing commission, in dollars.

    ```
    LC = lc_pct * full_term_contractual_face_rent
    ```

    D0 Section 12.2, D2 Section 8.2. The basis is the successor's **contractual
    face rent over its entire term**, computed by
    ``rent.contractual_face_rent_over_full_term`` and passed in. Every property
    of that basis is established there and is restated here only because the
    combination is what makes the commission right:

    | Question | Answer |
    |---|---|
    | Escalations included? | **Yes** -- the commission is on the whole contractual stream |
    | Gross of free rent? | **Yes** -- a broker earns on the lease signed, not on the landlord's concession |
    | Truncated at the hold horizon? | **No** -- the obligation is incurred in full at signing |
    | Reduced by a fractional first month from downtime? | **No** |

    **The basis is contractual face rent, never the cash Anchor recognises.**
    Passing a cash series here would understate every commission on a lease
    carrying free rent or downtime, invisibly; the guardrail suite asserts this
    module never names ``cash_rent_factor`` or ``cash_base_rent``.

    ``method`` is checked rather than ignored. D2 supports exactly one member
    (D0 Section 12.3), and an unrecognised method fails loudly instead of
    silently computing the percentage basis under another method's name -- the
    seam exists so a second method can be *added*, not so an unimplemented one
    can be *assumed*.
    """

    if method is not LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT:
        raise ValueError(
            f"leasing commission method {method!r} is not implemented; D2 "
            "supports only PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT."
        )

    return ensure_finite(
        "leasing_commission_amount", lc_pct * full_term_contractual_face_rent
    )


def leasing_cost_event_period(
    *, months: tuple[ModelMonth, ...], successor_occupancy_factor: tuple[float, ...]
) -> int | None:
    """Return the canonical period in which TI and LC are recorded, or ``None``.

    **The first canonical period with ``O_m > 0``** (D2 Section 8.1) -- the
    first period in which the successor economically occupies the suite after
    downtime.

    That period is exactly ``c = e + 1 + floor(D)``: every earlier period has
    ``O_m = 0``, and ``O_c = 1 - frac(D) > 0`` for every real ``D >= 0``. The
    two statements coincide by construction, and the ``O_m > 0`` form is used
    here because D2 Section 8.1 states it as primary -- it survives any future
    refinement of the occupancy step, whereas a hard-coded ``c`` would not.

    Returns ``None`` when no canonical period qualifies, which happens exactly
    when the successor commences beyond the projection horizon. The caller then
    records no monthly event: the timeline is **never** extended and no
    ``ModelMonth`` is fabricated to display a cost (D0 Section 8.6). The
    branch's total amounts are still computed and retained, because the
    obligation is real even where the window does not reach it.

    A zero-dollar TI or LC still yields an event period. The event month is a
    fact about timing, not about magnitude, and suppressing it because the
    amount happens to be zero would make a legitimately zero cost
    indistinguishable from a missing one.
    """

    for month, occupancy in zip(months, successor_occupancy_factor):
        if occupancy > 0.0:
            return month.period_index
    return None


def leasing_cost_event_series(
    *, months: tuple[ModelMonth, ...], event_period: int | None, amount: float
) -> tuple[float, ...]:
    """Return a monthly series carrying ``amount`` once, at ``event_period``.

    Zero in every other canonical period, and zero throughout when
    ``event_period`` is ``None``. Aligned 1:1 with the canonical timeline, like
    every other monthly series in this package.

    Recorded **in full, once** -- never prorated across months, never spread on
    a draw schedule, and never suppressed because the event falls inside the
    forward exit window. A rollover late in the hold can legitimately push its
    TI and LC into periods ``12H+1 .. 12H+12``, where D0 Section 17.4 discloses
    them without deducting them; that disclosure is a D4 concern and is not
    served by hiding the event here.
    """

    return tuple(
        amount if month.period_index == event_period else 0.0 for month in months
    )
