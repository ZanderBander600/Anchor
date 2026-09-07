"""Sprint D Gate D4.3 -- the canonical monthly property projection.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 5.3, 5.5, 5.6, 7, 8, 13 and 14 exactly; that document governs on any
discrepancy.

**This is a composition layer.** It receives three completed monthly schedules
-- the property's leasing economics (D4.2), its expense-recovery revenue (D3.5)
and its fixed operating expenses (D4.1) -- and combines them into the one
monthly statement a Lease-Level deal is read from. It recalculates none of
them. No rent, no escalation, no market rent, no downtime, no free-rent
waterfall, no rollover probability, no initial vacancy, no TI, no LC, no
occupied area, no fixed expense, no recoverable pool and no tenant recovery is
computed here; every one of those has exactly one owner further up and is final
before it arrives.

**Six new monthly figures, and only six**: other income, credit loss, effective
gross income, the management fee, total operating expenses, and NOI.

The per-month order is forced, not chosen (D0 Section 16.4, D4 Section 13):

```
cash base rent, free rent, other income      (independent)
the five fixed expense lines                 (independent, from D4.1)
recoverable pool -> tenant recovery          (already done, by D4.1 and D3)
credit loss                                  (from cash rent and recovery)
EGI                                          (from cash rent, recovery, other income, credit loss)
management fee                               (from EGI)
total operating expenses, then NOI           (from the fixed lines, EGI and the fee)
```

Because the management fee is excluded from the recoverable pool, no arrow
returns from the fee to the pool: the graph is acyclic and the whole statement
resolves in one deterministic pass, with no fixed-point solve, no iteration and
no convergence tolerance anywhere.

**Deliberately absent, all of it later work:** annual aggregation, exit NOI,
the going-in cap rate, CapEx, the below-NOI owner-capital channel, and every
acquisition, debt and return integration. Monthly is canonical; D4.4 owns the
annual adapter.
"""

from __future__ import annotations

from math import inf

from ..engine.contracts import ensure_finite
from .aggregation import (
    aggregate_flow_over_forward_exit_window,
    aggregate_flow_to_annual,
    average_state_over_year,
    snapshot_state_at_year_end,
)
from .contracts import (
    AnnualOperatingProjection,
    LeaseLevelOperatingInputs,
    MonthlyPropertyExpenseSchedule,
    MonthlyPropertyProjection,
    PropertyOperatingSchedule,
    PropertyRecoverySchedule,
)
from .validation import (
    require_valid_annual_adapter_inputs,
    require_valid_property_projection_inputs,
)


_MONTHS_PER_YEAR = 12


def _growth_factor(growth: float, exponent: int) -> float:
    """Return ``(1 + growth) ** exponent``.

    **Mirrors ``anchor.engine.operating_projection._growth_factor`` exactly**,
    as ``anchor.leasing.expenses`` does, for the same reason: CPython's
    ``float ** int`` raises ``OverflowError`` instead of returning ``inf`` when
    the mathematical result exceeds double precision. Since
    ``other_income_growth > -1`` is guaranteed by the input domain, the base is
    always positive, so an overflow can only mean the true result is
    unrepresentably large and positive; it is surfaced as ``inf`` here so
    ``ensure_finite`` can reject it explicitly.

    **This is a separate mirror from ``expenses.py``'s, deliberately.** The two
    serve different assumptions -- ``expense_growth`` and
    ``other_income_growth`` -- and D4 Section 8.3 is explicit that they must
    never alias: parking income does not move because a tax bill did. Sharing
    one helper across the two would be the first step toward sharing one rate.
    The arithmetic is identical and is proven bit/hex identical to Detailed's
    (``tests/test_leasing_d4_3_projection.py``); the *inputs* are what stay
    apart.
    """

    try:
        return (1 + growth) ** exponent
    except OverflowError:
        return inf


def annual_other_income(
    *, year_1_amount: float, other_income_growth: float, model_year: int
) -> float:
    """Return the property's other income for ``model_year``.

    ```
    AnnualOtherIncome_y = Year1OtherIncome * (1 + other_income_growth) ** (y - 1)
    ```

    ``model_year`` is ``ModelMonth.hold_year`` -- ``1..H`` for hold months and
    ``H + 1`` for the twelve forward exit months -- so growth steps on
    **analysis-start anniversaries**, never on calendar January. With a July
    analysis start, model month 13 is the following July and is the first month
    at the Year-2 rate.

    Year 1 is the base year: the exponent is ``0``, the factor is exactly
    ``1.0``, and the result is ``year_1_amount`` bit for bit.

    **The single Lease-Level implementation of other-income growth.** It is
    separate from ``expenses.annual_expense_amount`` because it consumes a
    different assumption, and it is never applied to rent: base rent already
    carries its contractual escalation and its market-rent growth at rollover,
    and a generic revenue growth on top would grow it twice (D4 Section 11).

    Operand order mirrors ``anchor.engine.operating_projection``'s
    ``detailed_inputs.other_income * revenue_factor`` exactly -- the same
    single multiplication of the same two operands in the same order -- which
    is why the two are bit/hex identical rather than merely close. Detailed
    reaches it through ``revenue_growth``; Lease-Level reaches it through
    ``other_income_growth``. **The arithmetic matches; the assumptions must
    not alias.**
    """

    return year_1_amount * _growth_factor(other_income_growth, model_year - 1)


def build_monthly_property_projection(
    operating: PropertyOperatingSchedule,
    recovery: PropertyRecoverySchedule,
    expenses: MonthlyPropertyExpenseSchedule,
    *,
    operating_inputs: LeaseLevelOperatingInputs,
) -> MonthlyPropertyProjection:
    """Compose three completed schedules into the canonical monthly statement.

    **Validates first, then calculates.**
    ``require_valid_property_projection_inputs`` is the single authority for
    month alignment across the three schedules, for the property-area identity
    between the leasing and recovery schedules, for their suite universes
    agreeing, and for the operating-input domains. This function adds no rule
    of its own.

    **The leasing schedule defines the timeline.** ``PropertyOperatingSchedule``
    is the accepted property-level authority (D4.2), so its ``months`` is the
    canonical sequence the other two must match. Nothing here builds a calendar.

    For each canonical month ``m``:

    ```
    other_income_m  = annual_other_income(..., model_year = months[m].hold_year) / 12
    credit_loss_m   = credit_loss_pct * (cash_base_rent_m + expense_recovery_m)
    EGI_m           = cash_base_rent_m + expense_recovery_m + other_income_m
                      - credit_loss_m
    management_fee_m = EGI_m * management_fee_pct
    total_operating_expenses_m = fixed_operating_expenses_m + management_fee_m
    NOI_m           = EGI_m - total_operating_expenses_m
    ```

    **Cash base rent enters EGI directly** (HD-D4-5). It is copied from the
    leasing schedule, never rebuilt as ``contractual_base_rent - free_rent``:
    in a fractional-downtime month those differ by the part of the month during
    which nobody was in economic possession, and rebuilding would recognise
    that part as collected revenue. ``contractual_base_rent`` and ``free_rent``
    ride through as **audit lines that feed nothing**.

    **No vacancy factor exists.** Physical vacancy is already inside the
    completed leasing dollars -- a vacant suite contributed zero rent, zero
    recovery and zero occupied area -- so nothing here is multiplied by
    occupancy or by ``1 - vacancy``. ``physical_occupancy`` is copied and is
    descriptive: it drives no revenue and no expense.

    **Credit loss is one formula, not two.** The base is summed first and the
    percentage applied once, so the float grouping is fixed. Other income is
    outside the base (D0 Section 14): parking receipts and antenna licences are
    not tenant lease receivables. Contractual rent, free rent, TI and LC are
    outside it too.

    **The management fee is a percentage of EGI, recoveries included**, after
    credit loss -- the one Anchor convention, identical in wording to
    Detailed's (HD-D4-2). Recovery stays a **revenue** line and the fixed
    expenses stay **gross**: netting them would leave the same pre-fee NOI but a
    smaller EGI, and therefore a smaller fee and a larger NOI, which is why the
    non-netting rule is load-bearing rather than presentational.

    **TI and LC are copied and stay below NOI.** They appear in no EGI, fee,
    expense or NOI arithmetic, in any month, under any input -- including the
    twelve forward months, where they are retained as leasing-event audit lines
    whose owner-cash-flow treatment is D4.4/D4.5's question.

    **NOI is never floored.** A vacant building still incurs its fixed
    expenses, so a negative monthly NOI is a correct result and is reported as
    one.

    The whole ``12H + 12`` window is projected. No annual figure, no exit NOI
    and no going-in cap rate is produced here.

    Pure and deterministic: no I/O, no mutation, no ``set`` or ``dict``
    iteration contributing to any figure.
    """

    require_valid_property_projection_inputs(
        operating, recovery, expenses, operating_inputs=operating_inputs
    )

    months = operating.months
    credit_loss_pct = operating_inputs.credit_loss_pct
    management_fee_pct = operating_inputs.management_fee_pct

    other_income: list[float] = []
    credit_loss: list[float] = []
    effective_gross_income: list[float] = []
    management_fee: list[float] = []
    total_operating_expenses: list[float] = []
    noi: list[float] = []

    for position, month in enumerate(months):
        period = month.period_index

        annual = ensure_finite(
            f"other_income[{period}] annual",
            annual_other_income(
                year_1_amount=operating_inputs.other_income,
                other_income_growth=operating_inputs.other_income_growth,
                model_year=month.hold_year,
            ),
        )
        other_income_m = ensure_finite(
            f"other_income[{period}]", annual / _MONTHS_PER_YEAR
        )

        cash_base_rent_m = operating.cash_base_rent[position]
        expense_recovery_m = recovery.expense_recovery[position]

        credit_loss_m = ensure_finite(
            f"credit_loss[{period}]",
            credit_loss_pct * (cash_base_rent_m + expense_recovery_m),
        )
        egi_m = ensure_finite(
            f"effective_gross_income[{period}]",
            cash_base_rent_m + expense_recovery_m + other_income_m - credit_loss_m,
        )
        management_fee_m = ensure_finite(
            f"management_fee[{period}]", egi_m * management_fee_pct
        )
        total_operating_expenses_m = ensure_finite(
            f"total_operating_expenses[{period}]",
            expenses.fixed_operating_expenses[position] + management_fee_m,
        )
        noi_m = ensure_finite(
            f"noi[{period}]", egi_m - total_operating_expenses_m
        )

        other_income.append(other_income_m)
        credit_loss.append(credit_loss_m)
        effective_gross_income.append(egi_m)
        management_fee.append(management_fee_m)
        total_operating_expenses.append(total_operating_expenses_m)
        noi.append(noi_m)

    return MonthlyPropertyProjection(
        months=months,
        rentable_area_sf=operating.rentable_area_sf,
        # --- revenue, above NOI ---
        contractual_base_rent=operating.contractual_base_rent,
        free_rent=operating.free_rent,
        cash_base_rent=operating.cash_base_rent,
        expense_recovery=recovery.expense_recovery,
        other_income=tuple(other_income),
        credit_loss=tuple(credit_loss),
        effective_gross_income=tuple(effective_gross_income),
        # --- expenses, above NOI ---
        property_taxes=expenses.property_taxes,
        insurance=expenses.insurance,
        utilities=expenses.utilities,
        repairs_maintenance=expenses.repairs_maintenance,
        other_operating_expenses=expenses.other_operating_expenses,
        fixed_operating_expenses=expenses.fixed_operating_expenses,
        management_fee=tuple(management_fee),
        total_operating_expenses=tuple(total_operating_expenses),
        noi=tuple(noi),
        # --- below NOI ---
        tenant_improvements=operating.tenant_improvements,
        leasing_commissions=operating.leasing_commissions,
        # --- state ---
        occupied_area_sf=operating.occupied_area_sf,
        vacant_area_sf=operating.vacant_area_sf,
        physical_occupancy=operating.physical_occupancy,
        # --- retained sources, not collapsed ---
        operating_schedule=operating,
        recovery_schedule=recovery,
        expense_schedule=expenses,
    )


# =============================================================================
# D4.4 -- the annual operating adapter
#
# A derivation over a derivation. Every figure below comes from one of the
# three D1.3 reducers applied to a canonical monthly series, and from nothing
# else. There is no annual growth rate here, no stabilization, no second NOI
# formula, and no annual model of any kind.
# =============================================================================


#: Every monthly flow line that becomes an annual line, in statement order. One
#: tuple, one loop, one reducer -- so ``noi_by_year`` and
#: ``tenant_improvements_by_year`` cannot come to be summed by different code
#: with different float grouping. The annual field is always the monthly name
#: plus ``_by_year``, which is what lets the reconciliation test be mechanical
#: rather than one assertion per line.
_ANNUAL_FLOW_LINES: tuple[str, ...] = (
    "contractual_base_rent",
    "cash_base_rent",
    "free_rent",
    "expense_recovery",
    "other_income",
    "credit_loss",
    "effective_gross_income",
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "other_operating_expenses",
    "fixed_operating_expenses",
    "management_fee",
    "total_operating_expenses",
    "noi",
    "tenant_improvements",
    "leasing_commissions",
)


def aggregate_monthly_to_annual(
    monthly: MonthlyPropertyProjection,
    *,
    purchase_price: float,
) -> AnnualOperatingProjection:
    """Derive the annual operating view from the canonical monthly projection.

    **Validates first, then derives.** ``require_valid_annual_adapter_inputs``
    is the single authority for the hold/forward partition and for the
    valuation denominator; this function adds no rule of its own.

    **The hold period is read, not guessed.** It comes from
    ``monthly.recovery_schedule.hold_period`` -- authoritative metadata carried
    since D3.5 -- and is then checked against the calendar: the projection must
    hold exactly ``12H + 12`` months and exactly the last twelve must be
    flagged forward. Deriving ``H`` as ``len(months) / 12`` would silently
    treat the forward year as a hold year, which is the one arithmetic mistake
    that would put a post-sale month into a seller cash flow.

    Flows, for ``y`` in ``1..H``:

    ```
    annual_X_by_year[y-1] = sum of monthly X_m for m in 12(y-1)+1 .. 12y
    ```

    through the existing ``aggregate_flow_to_annual``, in strictly ascending
    period order. **One reducer for every line** -- ``noi_by_year`` and
    ``tenant_improvements_by_year`` are produced by the same call in the same
    loop, so no two annual figures can disagree about float grouping. Each
    tuple has length exactly ``H``: the reducer stops at month ``12H`` by
    construction, so no forward-window dollar can reach a hold-year array.

    **``noi_by_year`` is the sum of monthly NOI.** It is never rebuilt from
    annual EGI minus annual expenses. Those reconcile to within IEEE-754
    grouping and a golden asserts it, but the monthly series is the authority,
    and a second path to the figure every downstream return depends on is
    exactly what this layer exists not to create.

    States, with their semantics in their names (G-M6):

    ```
    occupied_area_at_year_end            = snapshot_state_at_year_end(...)
    vacant_area_at_year_end              = snapshot_state_at_year_end(...)
    physical_occupancy_at_year_end       = snapshot_state_at_year_end(...)
    average_physical_occupancy_over_year = average_state_over_year(...)
    ```

    The headline annual occupancy is the **average** of the twelve monthly
    property-level values (accepted at D4.0 human review). Those monthly values
    were already computed once, from areas, at the property level by D4.2, so
    nothing here returns to suite data and nothing averages a suite percentage.

    Exit figures:

    ```
    exit_noi                  = sum of monthly noi over months 12H+1 .. 12H+12
    exit_window_leasing_costs = the same window's TI + LC
    going_in_cap_rate         = noi_by_year[0] / purchase_price
    ```

    ``exit_noi`` comes from the same canonical series an analyst can inspect
    (G-M12). It is never Hold Year ``H`` grown, never ``12x`` a single month,
    never stabilized and never gross of free rent -- whatever the forward
    twelve months contain is already inside monthly NOI. TI and LC never
    entered ``noi``, so they cannot reach ``exit_noi``; the exclusion is
    structural rather than a subtraction anyone must remember not to make.

    ``exit_window_leasing_costs`` is a **disclosed diagnostic, never deducted
    from anything** (D0 Section 17.4), read by no engine calculation.

    ``exit_noi`` may be positive, zero or negative, and all three are returned
    faithfully. Cap-rate terminal valuation is refused for a non-positive
    forward NOI at the Lease-Level acquisition/integration boundary (HD-D4-7),
    which is D4.5's; refusing it here would make a distressed building's
    operating projection unbuildable, which is what the accepted decision
    deliberately avoids.

    ``going_in_cap_rate`` is Year-1 NOI over price -- the one Anchor
    convention, identical to Quick's and Detailed's (D4 Section 20.4). Year-1
    NOI is a *modeled* result, so it may be zero or negative for a heavily
    vacant building; unlike ``exit_noi`` it capitalizes nothing, so it is
    reported as modeled rather than refused.

    **This is not acquisition integration.** ``purchase_price`` is a scalar
    denominator, taken exactly as
    ``build_detailed_operating_projection(..., purchase_price=...)`` already
    takes it. No exit value, no disposition cost, no debt, no return metric and
    no ``AcquisitionTerms`` appears here or anywhere in ``anchor.leasing``.

    Pure and deterministic: no I/O, no mutation, no ``set`` or ``dict``
    iteration contributing to any figure.
    """

    hold_period = monthly.recovery_schedule.hold_period

    require_valid_annual_adapter_inputs(
        monthly, hold_period=hold_period, purchase_price=purchase_price
    )

    annual: dict[str, tuple[float, ...]] = {
        name: aggregate_flow_to_annual(
            getattr(monthly, name), hold_period=hold_period
        )
        for name in _ANNUAL_FLOW_LINES
    }

    exit_noi = ensure_finite(
        "exit_noi",
        aggregate_flow_over_forward_exit_window(
            monthly.noi, hold_period=hold_period
        ),
    )
    exit_window_leasing_costs = ensure_finite(
        "exit_window_leasing_costs",
        aggregate_flow_over_forward_exit_window(
            monthly.tenant_improvements, hold_period=hold_period
        )
        + aggregate_flow_over_forward_exit_window(
            monthly.leasing_commissions, hold_period=hold_period
        ),
    )
    going_in_cap_rate = ensure_finite(
        "going_in_cap_rate", annual["noi"][0] / purchase_price
    )

    return AnnualOperatingProjection(
        contractual_base_rent_by_year=annual["contractual_base_rent"],
        cash_base_rent_by_year=annual["cash_base_rent"],
        free_rent_by_year=annual["free_rent"],
        expense_recovery_by_year=annual["expense_recovery"],
        other_income_by_year=annual["other_income"],
        credit_loss_by_year=annual["credit_loss"],
        effective_gross_income_by_year=annual["effective_gross_income"],
        property_taxes_by_year=annual["property_taxes"],
        insurance_by_year=annual["insurance"],
        utilities_by_year=annual["utilities"],
        repairs_maintenance_by_year=annual["repairs_maintenance"],
        other_operating_expenses_by_year=annual["other_operating_expenses"],
        fixed_operating_expenses_by_year=annual["fixed_operating_expenses"],
        management_fee_by_year=annual["management_fee"],
        total_operating_expenses_by_year=annual["total_operating_expenses"],
        noi_by_year=annual["noi"],
        tenant_improvements_by_year=annual["tenant_improvements"],
        leasing_commissions_by_year=annual["leasing_commissions"],
        occupied_area_at_year_end=snapshot_state_at_year_end(
            monthly.occupied_area_sf, hold_period=hold_period
        ),
        vacant_area_at_year_end=snapshot_state_at_year_end(
            monthly.vacant_area_sf, hold_period=hold_period
        ),
        physical_occupancy_at_year_end=snapshot_state_at_year_end(
            monthly.physical_occupancy, hold_period=hold_period
        ),
        average_physical_occupancy_over_year=average_state_over_year(
            monthly.physical_occupancy, hold_period=hold_period
        ),
        exit_noi=exit_noi,
        going_in_cap_rate=going_in_cap_rate,
        exit_window_leasing_costs=exit_window_leasing_costs,
    )
