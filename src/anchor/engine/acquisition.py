"""Phase 2C exit value, net sale proceeds, and cash-flow assembly.

Restates ``docs/financial_conventions.md`` "Exit value" / "Cash-Flow Timing"
and ``docs/phase_2_deterministic_engine.md`` "Phase 2C -- Exit Value" /
"Unlevered Cash Flows" / "Levered Cash Flows" exactly; those documents govern
on any discrepancy. This module contains no formula of its own beyond
assembling values already computed by ``noi.py`` and ``debt.py`` -- no NOI
forecasting, no debt-schedule machinery, and no return-metric logic belongs
here.
"""

from __future__ import annotations

from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    acquisition_terms_from_inputs,
)
from .contracts import (
    AcquisitionCashFlows,
    AcquisitionResults,
    DetailedAcquisitionResults,
    OperatingCapitalSchedule,
    OperatingProjectionLike,
    OwnerCapitalSchedule,
    OwnerReturnMetrics,
    ensure_finite,
)
from .debt import calculate_capital_stack, calculate_debt_schedule
from .noi import build_quick_operating_projection, forecast_noi
from .operating_projection import build_detailed_operating_projection
from .returns import (
    calculate_cumulative_operating_distributions_by_year,
    calculate_levered_cash_on_cash_by_year,
    calculate_return_metrics,
    calculate_unlevered_acquisition_basis,
    calculate_unlevered_cash_yield_by_year,
    calculate_year_1_debt_yield,
)


def calculate_exit_value(*, exit_noi: float, exit_cap_rate: float) -> float:
    """Return ``Exit Value = Exit NOI / Exit Cap Rate`` -- the gross,
    unmodified market-value estimate.

    ``exit_cap_rate > 0`` is already guaranteed by the input domain, so this
    division is always defined. Underwriting V2 Gate 2's disposition costs
    are never folded into this value; see ``calculate_disposition_costs``
    and ``calculate_net_sale_proceeds`` below, which deduct them only when
    deriving the *net* sale figure.
    """

    exit_value = exit_noi / exit_cap_rate
    return ensure_finite("exit_value", exit_value)


def calculate_disposition_costs(
    *, exit_value: float, disposition_cost_pct: float
) -> float:
    """Underwriting V2 Gate 2: ``disposition_costs = exit_value *
    disposition_cost_pct`` -- a percentage of the gross sale price.
    ``exit_value`` itself (``calculate_exit_value``) is never reduced by
    this; it stays the gross market-value estimate."""

    disposition_costs = exit_value * disposition_cost_pct
    return ensure_finite("disposition_costs", disposition_costs)


def calculate_capex_by_year(
    *, annual_capex_reserve: float, hold_period: int
) -> tuple[float, ...]:
    """Underwriting V2 Gate 3: return ``(CapEx_1, .., CapEx_H)``, length
    ``hold_period``, each entry equal to the constant nominal-dollar
    ``annual_capex_reserve``. Modeled strictly below NOI -- this series is
    computed independently of ``noi_by_year`` and never modifies it; it is
    reused directly by both cash-flow series below rather than
    recomputed."""

    return tuple(
        ensure_finite(f"capex_by_year[{year}]", annual_capex_reserve)
        for year in range(hold_period)
    )


def calculate_operating_capital_by_year(
    *, operating_capital: OperatingCapitalSchedule | None, hold_period: int
) -> tuple[float, ...]:
    """Return ``(OpCap_1, .., OpCap_H)`` -- the total below-NOI operating
    capital outflow in each hold year (D4 Section 17.4).

    ``OpCap_y = TI_y + LC_y``. **The single authority for that total.** The
    components are summed once, here, in one order, so every consumer -- both
    cash-flow series and both recurring owner-return series -- subtracts the
    identical completed figure and no two of them can disagree. Nothing
    downstream re-adds ``tenant_improvements_by_year`` to
    ``leasing_commissions_by_year``.

    ``operating_capital is None`` means no variable below-NOI capital, and
    materialises as all zeros of length ``hold_period`` -- exactly the shape
    and the neutrality ``calculate_capex_by_year`` already has. Subtracting
    ``0.0`` from a finite float is exact in IEEE-754, so every caller's prior
    arithmetic is preserved bit for bit; that identity is asserted directly
    against the pre-channel results rather than assumed.

    A schedule whose length disagrees with ``hold_period`` is rejected: it
    would otherwise be zipped short and silently drop a year's capital. The
    schedule's own domain (finite, ``>= 0``) is enforced by
    ``OperatingCapitalSchedule`` at construction, so it is not re-checked here.

    This is generic. It knows the dollars are below NOI and annual, and
    nothing else -- not that they are leasing costs, and not what produced
    them.
    """

    if operating_capital is None:
        return tuple(0.0 for _ in range(hold_period))

    tenant_improvements = operating_capital.tenant_improvements_by_year
    leasing_commissions = operating_capital.leasing_commissions_by_year
    if len(tenant_improvements) != hold_period:
        raise ValueError(
            f"an OperatingCapitalSchedule for a {hold_period}-year hold "
            f"requires {hold_period} annual figures; got "
            f"{len(tenant_improvements)}. Hold years 1..H only -- a "
            "forward-window capital event is not a seller cash flow and is "
            "excluded before the engine boundary."
        )

    return tuple(
        ensure_finite(
            f"operating_capital_by_year[{year}]",
            tenant_improvements[year] + leasing_commissions[year],
        )
        for year in range(hold_period)
    )


def calculate_net_sale_proceeds(
    *,
    exit_value: float,
    remaining_loan_balance: float,
    disposition_costs: float = 0.0,
) -> float:
    """Return the levered net sale proceeds: ``Exit Value - Disposition
    Costs - Remaining Loan Balance``. At the Gate 2 neutral default
    (``disposition_costs = 0.0``), this reduces to exactly the V1 formula
    ``Exit Value - Remaining Loan Balance``."""

    net_sale_proceeds = exit_value - disposition_costs - remaining_loan_balance
    return ensure_finite("net_sale_proceeds", net_sale_proceeds)


def calculate_unlevered_cash_flows(
    *,
    purchase_price: float,
    noi_by_year: tuple[float, ...],
    exit_value: float,
    acquisition_costs: float = 0.0,
    disposition_costs: float = 0.0,
    capex_by_year: tuple[float, ...] = (),
    operating_capital_by_year: tuple[float, ...] = (),
) -> tuple[float, ...]:
    """Return ``(UCF_0, UCF_1, ..., UCF_H)``, length ``H + 1``.

    ``UCF_0 = -(purchase_price + acquisition_costs)``; ``UCF_y = NOI_y -
    CapEx_y - OpCap_y`` for ``1 <= y < H``; ``UCF_H = NOI_H - CapEx_H -
    OpCap_H + exit_value - disposition_costs``. At the Gate 2/3 and D4.5A
    neutral defaults (all cost terms ``0.0``, ``capex_by_year`` and
    ``operating_capital_by_year`` empty/all-zero), this reduces to exactly the
    V1 formulas. No debt term appears anywhere in this series (a financing
    fee, being debt-related, never appears in the unlevered series
    either), and ``exit_noi`` (already folded into ``exit_value``) is never
    added again as a separate operating cash flow. CapEx may exceed NOI in
    any year, producing a negative entry -- it is never capped or
    rejected.

    D4.5A: ``operating_capital_by_year`` is the completed ``TI + LC`` total
    from ``calculate_operating_capital_by_year``, subtracted **once**, beside
    CapEx and never merged with it. It is a recurring hold-period property
    outflow, so it reduces the final year's cash flow as well -- alongside the
    sale, never out of the sale proceeds, which are a separate terminal
    event.
    """

    hold_period = len(noi_by_year)
    capex = capex_by_year or tuple(0.0 for _ in range(hold_period))
    operating_capital = operating_capital_by_year or tuple(
        0.0 for _ in range(hold_period)
    )

    cash_flows = [
        ensure_finite(
            "unlevered_cash_flows[0]", -(purchase_price + acquisition_costs)
        )
    ]
    for year in range(1, hold_period):
        ucf_y = noi_by_year[year - 1] - capex[year - 1] - operating_capital[year - 1]
        cash_flows.append(ensure_finite(f"unlevered_cash_flows[{year}]", ucf_y))

    ucf_h = (
        noi_by_year[hold_period - 1]
        - capex[hold_period - 1]
        - operating_capital[hold_period - 1]
        + exit_value
        - disposition_costs
    )
    cash_flows.append(ensure_finite(f"unlevered_cash_flows[{hold_period}]", ucf_h))

    return tuple(cash_flows)


def calculate_levered_cash_flows(
    *,
    initial_equity: float,
    noi_by_year: tuple[float, ...],
    annual_debt_service: tuple[float, ...],
    net_sale_proceeds: float,
    capex_by_year: tuple[float, ...] = (),
    operating_capital_by_year: tuple[float, ...] = (),
    project_capital_by_year: tuple[float, ...] = (),
    owner_expenses_by_year: tuple[float, ...] = (),
) -> tuple[float, ...]:
    """Return ``(LCF_0, LCF_1, ..., LCF_H)``, length ``H + 1``.

    ``LCF_0 = -initial_equity``; ``LCF_y = NOI_y - ADS_y - CapEx_y -
    OpCap_y - PC_y - OE_y`` for ``1 <= y < H``; ``LCF_H = NOI_H - ADS_H -
    CapEx_H - OpCap_H - PC_H - OE_H + net_sale_proceeds``.

    Phase 6 Gate D6.2: this is the **Equity Cash Flow** (D6 conventions Section
    6), ``-Initial Equity Requirement`` at closing and Levered Owner Cash Flow
    in each hold year, plus net sale proceeds in the last. Project capital
    (``PC``) and owner expenses (``OE``) are equity outflows subtracted once
    each, after operating capital. It deliberately keeps its own D5 grouping
    -- debt service subtracted *before* the reserve -- rather than reading
    ``levered_owner_cash_flow_by_year``, which subtracts debt service last.
    The two are algebraically equal but can differ in the last bit, and this
    series must reproduce the D5 bits exactly when both new terms are zero
    (subtracting ``0.0`` is exact). Compare it with the owner cash-flow chain
    within tolerance, never bitwise. The already-computed ``net_sale_proceeds``
    (Phase 2C) is used directly for the sale component of ``LCF_H`` rather
    than re-expanding ``exit_value - remaining_loan_balance`` inline, so the
    single computed value is reused rather than recomputed. At the Gate 3 and
    D4.5A neutral defaults (``capex_by_year`` and ``operating_capital_by_year``
    empty/all-zero), this reduces to exactly the prior formulas. CapEx may
    exceed the year's operating cash flow, producing a negative entry -- it is
    never capped or rejected.

    D4.5A: operating capital is an **equity** outflow, never financed. It
    reduces the levered cash flow directly and changes no debt term: the
    annual debt service, the amortization schedule and the remaining balance
    are all functions of ``AcquisitionTerms`` alone and are untouched by it.
    """

    hold_period = len(noi_by_year)
    capex = capex_by_year or tuple(0.0 for _ in range(hold_period))
    operating_capital = operating_capital_by_year or tuple(
        0.0 for _ in range(hold_period)
    )
    project_capital = project_capital_by_year or tuple(
        0.0 for _ in range(hold_period)
    )
    owner_expenses = owner_expenses_by_year or tuple(0.0 for _ in range(hold_period))

    cash_flows = [ensure_finite("levered_cash_flows[0]", -initial_equity)]
    for year in range(1, hold_period):
        lcf_y = (
            noi_by_year[year - 1]
            - annual_debt_service[year - 1]
            - capex[year - 1]
            - operating_capital[year - 1]
            - project_capital[year - 1]
            - owner_expenses[year - 1]
        )
        cash_flows.append(ensure_finite(f"levered_cash_flows[{year}]", lcf_y))

    lcf_h = (
        noi_by_year[hold_period - 1]
        - annual_debt_service[hold_period - 1]
        - capex[hold_period - 1]
        - operating_capital[hold_period - 1]
        - project_capital[hold_period - 1]
        - owner_expenses[hold_period - 1]
        + net_sale_proceeds
    )
    cash_flows.append(ensure_finite(f"levered_cash_flows[{hold_period}]", lcf_h))

    return tuple(cash_flows)


# =============================================================================
# Phase 6 Gate D6.2 -- the owner cash-flow chain
#
# ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 4, 6, 8, 10 and
# 12. NOI is the operating mode's; everything here is below it:
#
#     Property Cash Flow_y        = NOI_y - Reserve_y - OpCap_y     (OpCap = TI + LC)
#     Unlevered Owner Cash Flow_y = Property Cash Flow_y - PC_y - OE_y
#     Levered Owner Cash Flow_y   = Unlevered Owner Cash Flow_y - DS_y
#
# Each series is computed once, here, and consumed by everything downstream of
# it: the Unlevered Project Cash Flow is built from Unlevered Owner Cash Flow,
# and cash-on-cash, cash yield and cumulative operating distributions read the
# two owner series directly. Evaluated left to right, these are exactly the D5
# ``calculate_recurring_*`` groupings, so with no project capital and no owner
# expenses every one of those D5 results is reproduced to the bit. The Equity
# Cash Flow keeps its own D5 grouping instead -- see
# ``calculate_levered_cash_flows``.
#
# Nothing here reads ``noi_by_year`` except the Property Cash Flow and the Year 1
# Debt Yield (a lender metric: NOI over the loan), and nothing here changes NOI,
# the debt schedule, exit value, disposition costs or net sale proceeds.
# =============================================================================


def calculate_owner_capital_schedule(
    *, owner_capital: OwnerCapitalSchedule | None, hold_period: int
) -> OwnerCapitalSchedule:
    """Return the ``OwnerCapitalSchedule`` the engine applies for a
    ``hold_period``-year hold.

    ``owner_capital is None`` means an empty Business Plan and materialises, in
    this one place, as the all-zero schedule: no closing capital, ``H`` zero
    years in each series and no post-hold capital. Subtracting and adding
    those zeros is exact for every figure the engine produces, which is why the
    neutral path reproduces the pre-D6.2 engine bit for bit; that is asserted
    against the 7e67cde engine rather than assumed.

    A schedule resolved for a different hold is rejected rather than zipped
    short: it would silently drop a year's capital, or charge a year that is
    not in this hold. The schedule's own domain (finite, ``>= 0``, equal-length
    series) is enforced by ``OwnerCapitalSchedule`` at construction.

    Generic, like ``calculate_operating_capital_by_year``: the engine knows the
    figures are owner-level closing and annual dollars, and nothing about the
    plan items, categories or months that produced them.
    """

    if owner_capital is None:
        zeros = tuple(0.0 for _ in range(hold_period))
        return OwnerCapitalSchedule(
            closing_project_capital=0.0,
            project_capital_by_year=zeros,
            owner_expenses_by_year=zeros,
            post_hold_project_capital=0.0,
        )

    if len(owner_capital.project_capital_by_year) != hold_period:
        raise ValueError(
            f"an OwnerCapitalSchedule for a {hold_period}-year hold requires "
            f"{hold_period} annual figures; got "
            f"{len(owner_capital.project_capital_by_year)}. Resolve the "
            "Business Plan for the hold period being analysed -- capital after "
            "the hold is disclosed separately and never enters a hold year."
        )
    return owner_capital


def calculate_initial_equity_requirement(
    *, acquisition_equity: float, closing_project_capital: float
) -> float:
    """``Initial Equity Requirement = Purchase Price - Loan + Acquisition Costs
    + Financing Fee + Closing Project Capital`` (D6 conventions Sections 4 and
    10, decision D7).

    ``acquisition_equity`` is ``CapitalStack.initial_equity`` -- the unchanged
    D5 ``purchase_price - loan_amount + acquisition_costs + financing_fee``
    from ``debt.py``. Adding closing capital to that completed figure is the
    same left-to-right evaluation as the full expression, and adding ``0.0`` to
    it leaves it unchanged.

    Closing project capital is **equity-funded**: it is added here and nowhere
    near the loan. ``loan_amount`` stays ``purchase_price * ltv``; there is no
    loan-to-cost sizing."""

    return ensure_finite(
        "initial_equity", acquisition_equity + closing_project_capital
    )


def calculate_unlevered_project_basis(
    *, purchase_price: float, acquisition_costs: float, closing_project_capital: float
) -> float:
    """``Purchase Price + Acquisition Costs + Closing Project Capital`` -- the
    unlevered cost basis at closing (D6 conventions Sections 6 and 8).

    One figure, two consumers: the Unlevered Project Cash Flow's ``t = 0`` is
    its negative, and it is the Unlevered Cash Yield's denominator. It extends
    the Owner Return Metrics V3 basis (``calculate_unlevered_acquisition_basis``)
    rather than restating it, so the financing fee stays outside it, as before.
    Future project capital never enters it: the basis is fixed at closing."""

    return ensure_finite(
        "unlevered_project_basis",
        calculate_unlevered_acquisition_basis(
            purchase_price=purchase_price, acquisition_costs=acquisition_costs
        )
        + closing_project_capital,
    )


def calculate_total_closing_uses(
    *,
    purchase_price: float,
    acquisition_costs: float,
    financing_fee: float,
    closing_project_capital: float,
) -> float:
    """``Total Closing Uses = Purchase Price + Acquisition Costs + Financing
    Fees + Closing Project Capital`` (D6 conventions Section 10). Future and
    post-hold project capital are not closing uses."""

    return ensure_finite(
        "total_closing_uses",
        purchase_price + acquisition_costs + financing_fee + closing_project_capital,
    )


def calculate_total_closing_sources(
    *, loan_amount: float, initial_equity: float
) -> float:
    """``Total Closing Sources = Acquisition Debt + Initial Equity`` (D6
    conventions Section 10). Algebraically equal to
    ``calculate_total_closing_uses``; the two group their additions
    differently, so they are compared within tolerance, never bitwise."""

    return ensure_finite("total_closing_sources", loan_amount + initial_equity)


def calculate_property_cash_flow_by_year(
    *,
    noi_by_year: tuple[float, ...],
    capex_by_year: tuple[float, ...],
    operating_capital_by_year: tuple[float, ...],
) -> tuple[float, ...]:
    """Return ``(PCF_1, .., PCF_H)``: ``PCF_y = NOI_y - Reserve_y - OpCap_y``.

    The recurring CapEx reserve and the completed TI + LC total (the one sum
    ``calculate_operating_capital_by_year`` makes) are each subtracted once.
    Project capital and owner expenses are not property cash flow and never
    appear here. Never floored; a negative year is reported as-is."""

    return tuple(
        ensure_finite(
            f"property_cash_flow_by_year[{year}]",
            noi_by_year[year] - capex_by_year[year] - operating_capital_by_year[year],
        )
        for year in range(len(noi_by_year))
    )


def calculate_unlevered_owner_cash_flow_by_year(
    *,
    property_cash_flow_by_year: tuple[float, ...],
    project_capital_by_year: tuple[float, ...],
    owner_expenses_by_year: tuple[float, ...],
) -> tuple[float, ...]:
    """Return ``(UOCF_1, .., UOCF_H)``: ``UOCF_y = PCF_y - PC_y - OE_y``.

    Project capital and owner expenses are each subtracted once, here, from
    the completed Property Cash Flow -- so the reserve and TI/LC cannot be
    subtracted twice. Never floored."""

    return tuple(
        ensure_finite(
            f"unlevered_owner_cash_flow_by_year[{year}]",
            property_cash_flow_by_year[year]
            - project_capital_by_year[year]
            - owner_expenses_by_year[year],
        )
        for year in range(len(property_cash_flow_by_year))
    )


def calculate_levered_owner_cash_flow_by_year(
    *,
    unlevered_owner_cash_flow_by_year: tuple[float, ...],
    annual_debt_service: tuple[float, ...],
) -> tuple[float, ...]:
    """Return ``(LOCF_1, .., LOCF_H)``: ``LOCF_y = UOCF_y - DS_y``. Never
    floored: a negative year is negative owner cash flow."""

    return tuple(
        ensure_finite(
            f"levered_owner_cash_flow_by_year[{year}]",
            unlevered_owner_cash_flow_by_year[year] - annual_debt_service[year],
        )
        for year in range(len(unlevered_owner_cash_flow_by_year))
    )


def calculate_unlevered_project_cash_flows(
    *,
    unlevered_project_basis: float,
    unlevered_owner_cash_flow_by_year: tuple[float, ...],
    exit_value: float,
    disposition_costs: float,
) -> tuple[float, ...]:
    """Return the Unlevered Project Cash Flow ``(UCF_0, .., UCF_H)`` -- the
    unlevered IRR series (D6 conventions Section 6):

    - ``UCF_0 = -(Purchase Price + Acquisition Costs + Closing Project
      Capital)``;
    - ``UCF_y = UOCF_y`` for ``1 <= y < H``;
    - ``UCF_H = UOCF_H + Exit Value - Disposition Costs``.

    Built from the authoritative Unlevered Owner Cash Flow rather than from NOI
    again, so it cannot disagree with it. Final-year capital and owner expenses
    are therefore deducted once, inside ``UOCF_H``, and the sale is added
    separately -- never netted against them. With neither present this is
    ``calculate_unlevered_cash_flows``'s D5 result to the bit (same operations,
    same order); that builder remains for its existing direct callers."""

    hold_period = len(unlevered_owner_cash_flow_by_year)

    cash_flows = [ensure_finite("unlevered_cash_flows[0]", -unlevered_project_basis)]
    for year in range(1, hold_period):
        cash_flows.append(
            ensure_finite(
                f"unlevered_cash_flows[{year}]",
                unlevered_owner_cash_flow_by_year[year - 1],
            )
        )

    ucf_h = (
        unlevered_owner_cash_flow_by_year[hold_period - 1]
        + exit_value
        - disposition_costs
    )
    cash_flows.append(ensure_finite(f"unlevered_cash_flows[{hold_period}]", ucf_h))

    return tuple(cash_flows)


def calculate_owner_cash_flow_return_metrics(
    *,
    noi_by_year: tuple[float, ...],
    unlevered_owner_cash_flow_by_year: tuple[float, ...],
    levered_owner_cash_flow_by_year: tuple[float, ...],
    unlevered_project_basis: float,
    initial_equity: float,
    loan_amount: float,
) -> OwnerReturnMetrics:
    """The Owner Return Metrics V3 results, fed the D6 owner cash-flow series
    (D6 conventions Section 8, decision D18).

    Every metric formula is the unchanged ``returns.py`` one; only its inputs
    moved:

    - Levered Cash-on-Cash = Levered Owner Cash Flow / Initial Equity
      Requirement. Still a return on **initial** equity: closing capital
      raises the denominator, future capital does not.
    - Unlevered Cash Yield = Unlevered Owner Cash Flow / (Purchase Price +
      Acquisition Costs + Closing Project Capital).
    - Cumulative operating distributions (legacy name) = running sum of
      Levered Owner Cash Flow. It can fall below zero; that is negative owner
      cash flow, not a "negative distribution".
    - Year 1 Debt Yield = Year 1 **NOI** / loan amount -- a lender metric, so no
      owner series reaches it.

    ``returns.py`` names the two series parameters ``recurring_*``, which
    predates D6; the series passed are the authoritative owner cash flows,
    which may contain non-recurring capital."""

    return OwnerReturnMetrics(
        levered_cash_on_cash_by_year=calculate_levered_cash_on_cash_by_year(
            recurring_levered_cash_flows=levered_owner_cash_flow_by_year,
            initial_equity=initial_equity,
        ),
        unlevered_cash_yield_by_year=calculate_unlevered_cash_yield_by_year(
            recurring_unlevered_cash_flows=unlevered_owner_cash_flow_by_year,
            unlevered_acquisition_basis=unlevered_project_basis,
        ),
        cumulative_operating_distributions_by_year=(
            calculate_cumulative_operating_distributions_by_year(
                recurring_levered_cash_flows=levered_owner_cash_flow_by_year
            )
        ),
        year_1_debt_yield=calculate_year_1_debt_yield(
            year_1_noi=noi_by_year[0], loan_amount=loan_amount
        ),
    )


def calculate_acquisition_cash_flows(inputs: AcquisitionInputs) -> AcquisitionCashFlows:
    """Compute the Phase 2C exit value, net sale proceeds, and cash-flow
    tuples for one ``AcquisitionInputs``, built on top of the Phase 2A NOI
    forecast and Phase 2B debt schedule.

    Quick-only convenience/testing entry point -- public signature
    unchanged by Detailed Operating Model V2.1 Gate 3. Internally now
    derives ``terms`` via ``acquisition_terms_from_inputs`` and passes it to
    ``calculate_capital_stack``/``calculate_debt_schedule`` (both retyped to
    ``AcquisitionTerms`` at this gate); every value read below is otherwise
    identical to before this gate.
    """

    noi_forecast = forecast_noi(inputs)
    terms = acquisition_terms_from_inputs(inputs)
    capital_stack = calculate_capital_stack(terms)
    debt_schedule = calculate_debt_schedule(terms)

    exit_value = calculate_exit_value(
        exit_noi=noi_forecast.exit_noi, exit_cap_rate=terms.exit_cap_rate
    )
    disposition_costs = calculate_disposition_costs(
        exit_value=exit_value, disposition_cost_pct=terms.disposition_cost_pct
    )
    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=exit_value,
        remaining_loan_balance=debt_schedule.remaining_loan_balance,
        disposition_costs=disposition_costs,
    )
    capex_by_year = calculate_capex_by_year(
        annual_capex_reserve=terms.annual_capex_reserve,
        hold_period=terms.hold_period,
    )

    unlevered_cash_flows = calculate_unlevered_cash_flows(
        purchase_price=terms.purchase_price,
        noi_by_year=noi_forecast.noi_by_year,
        exit_value=exit_value,
        acquisition_costs=capital_stack.acquisition_costs,
        disposition_costs=disposition_costs,
        capex_by_year=capex_by_year,
    )
    levered_cash_flows = calculate_levered_cash_flows(
        initial_equity=capital_stack.initial_equity,
        noi_by_year=noi_forecast.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        net_sale_proceeds=net_sale_proceeds,
        capex_by_year=capex_by_year,
    )

    return AcquisitionCashFlows(
        exit_value=exit_value,
        disposition_costs=disposition_costs,
        net_sale_proceeds=net_sale_proceeds,
        capex_by_year=capex_by_year,
        unlevered_cash_flows=unlevered_cash_flows,
        levered_cash_flows=levered_cash_flows,
    )


# =============================================================================
# Phase 2E / Detailed Operating Model V2.1 Gate 3 -- final orchestration
# =============================================================================


def analyze_acquisition_from_operating_projection(
    operating_projection: OperatingProjectionLike,
    terms: AcquisitionTerms,
    operating_capital: OperatingCapitalSchedule | None = None,
    *,
    owner_capital: OwnerCapitalSchedule | None = None,
) -> AcquisitionResults:
    """The single authoritative downstream acquisition/debt/returns
    calculation path (``docs/detailed_operating_model_v2_1_architecture.md``
    Section 3.1/3.2).

    Phase 6 Gate D6.2: ``owner_capital`` is the resolved Business Plan
    (``OwnerCapitalSchedule``), keyword-only, ``None`` meaning an empty plan.
    It is consumed below NOI and nowhere else -- the capital stack's loan, the
    debt schedule, exit value, disposition costs, net sale proceeds, DSCR and
    debt yield are computed exactly as before and never read it. Closing
    capital raises the Initial Equity Requirement and the unlevered basis; the
    annual series flow through the owner cash-flow chain into both cash-flow
    series and every owner return metric.

    Extracted from ``analyze_acquisition``'s prior body with zero formula
    change: every calculation below is exactly what ``analyze_acquisition``
    already performed, now reading ``noi_by_year``/``exit_noi``/
    ``going_in_cap_rate`` off ``operating_projection`` (either the Quick
    ``NoiForecast`` or the Detailed ``OperatingProjection`` -- both satisfy
    ``OperatingProjectionLike``) and every acquisition/debt/exit assumption
    off ``terms`` (``AcquisitionTerms``), rather than off a
    ``forecast_noi(inputs)`` call and an ``AcquisitionInputs`` instance
    directly.

    Called by both ``analyze_acquisition`` (Quick) and
    ``analyze_detailed_acquisition`` (Detailed) below -- neither duplicates
    any line of this function; both converge here exactly once. This
    function never reads ``current_noi``, ``noi_growth``, or ``occupancy``
    -- none of the three exists on either of its parameter types.
    """

    capital_stack = calculate_capital_stack(terms)
    debt_schedule = calculate_debt_schedule(terms)

    exit_value = calculate_exit_value(
        exit_noi=operating_projection.exit_noi, exit_cap_rate=terms.exit_cap_rate
    )
    disposition_costs = calculate_disposition_costs(
        exit_value=exit_value, disposition_cost_pct=terms.disposition_cost_pct
    )
    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=exit_value,
        remaining_loan_balance=debt_schedule.remaining_loan_balance,
        disposition_costs=disposition_costs,
    )
    capex_by_year = calculate_capex_by_year(
        annual_capex_reserve=terms.annual_capex_reserve,
        hold_period=terms.hold_period,
    )
    operating_capital_by_year = calculate_operating_capital_by_year(
        operating_capital=operating_capital, hold_period=terms.hold_period
    )

    # D6.2 -- the resolved Business Plan, below NOI only.
    owner_capital_schedule = calculate_owner_capital_schedule(
        owner_capital=owner_capital, hold_period=terms.hold_period
    )
    initial_equity = calculate_initial_equity_requirement(
        acquisition_equity=capital_stack.initial_equity,
        closing_project_capital=owner_capital_schedule.closing_project_capital,
    )
    unlevered_project_basis = calculate_unlevered_project_basis(
        purchase_price=terms.purchase_price,
        acquisition_costs=capital_stack.acquisition_costs,
        closing_project_capital=owner_capital_schedule.closing_project_capital,
    )
    property_cash_flow_by_year = calculate_property_cash_flow_by_year(
        noi_by_year=operating_projection.noi_by_year,
        capex_by_year=capex_by_year,
        operating_capital_by_year=operating_capital_by_year,
    )
    unlevered_owner_cash_flow_by_year = calculate_unlevered_owner_cash_flow_by_year(
        property_cash_flow_by_year=property_cash_flow_by_year,
        project_capital_by_year=owner_capital_schedule.project_capital_by_year,
        owner_expenses_by_year=owner_capital_schedule.owner_expenses_by_year,
    )
    levered_owner_cash_flow_by_year = calculate_levered_owner_cash_flow_by_year(
        unlevered_owner_cash_flow_by_year=unlevered_owner_cash_flow_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
    )

    unlevered_cash_flows = calculate_unlevered_project_cash_flows(
        unlevered_project_basis=unlevered_project_basis,
        unlevered_owner_cash_flow_by_year=unlevered_owner_cash_flow_by_year,
        exit_value=exit_value,
        disposition_costs=disposition_costs,
    )
    levered_cash_flows = calculate_levered_cash_flows(
        initial_equity=initial_equity,
        noi_by_year=operating_projection.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        net_sale_proceeds=net_sale_proceeds,
        capex_by_year=capex_by_year,
        operating_capital_by_year=operating_capital_by_year,
        project_capital_by_year=owner_capital_schedule.project_capital_by_year,
        owner_expenses_by_year=owner_capital_schedule.owner_expenses_by_year,
    )

    return_metrics = calculate_return_metrics(
        noi_by_year=operating_projection.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        unlevered_cash_flows=unlevered_cash_flows,
        levered_cash_flows=levered_cash_flows,
    )
    owner_return_metrics = calculate_owner_cash_flow_return_metrics(
        noi_by_year=operating_projection.noi_by_year,
        unlevered_owner_cash_flow_by_year=unlevered_owner_cash_flow_by_year,
        levered_owner_cash_flow_by_year=levered_owner_cash_flow_by_year,
        unlevered_project_basis=unlevered_project_basis,
        initial_equity=initial_equity,
        loan_amount=capital_stack.loan_amount,
    )
    total_closing_uses = calculate_total_closing_uses(
        purchase_price=terms.purchase_price,
        acquisition_costs=capital_stack.acquisition_costs,
        financing_fee=capital_stack.financing_fee,
        closing_project_capital=owner_capital_schedule.closing_project_capital,
    )
    total_closing_sources = calculate_total_closing_sources(
        loan_amount=capital_stack.loan_amount, initial_equity=initial_equity
    )

    return AcquisitionResults(
        going_in_cap_rate=operating_projection.going_in_cap_rate,
        loan_amount=capital_stack.loan_amount,
        acquisition_costs=capital_stack.acquisition_costs,
        financing_fee=capital_stack.financing_fee,
        initial_equity=initial_equity,
        monthly_debt_service=debt_schedule.monthly_debt_service,
        annual_debt_service=debt_schedule.annual_debt_service,
        remaining_loan_balance=debt_schedule.remaining_loan_balance,
        noi_by_year=operating_projection.noi_by_year,
        capex_by_year=capex_by_year,
        tenant_improvements_by_year=(
            operating_capital.tenant_improvements_by_year
            if operating_capital is not None
            else tuple(0.0 for _ in range(terms.hold_period))
        ),
        leasing_commissions_by_year=(
            operating_capital.leasing_commissions_by_year
            if operating_capital is not None
            else tuple(0.0 for _ in range(terms.hold_period))
        ),
        exit_noi=operating_projection.exit_noi,
        exit_value=exit_value,
        disposition_costs=disposition_costs,
        net_sale_proceeds=net_sale_proceeds,
        unlevered_cash_flows=unlevered_cash_flows,
        levered_cash_flows=levered_cash_flows,
        unlevered_irr=return_metrics.unlevered_irr,
        levered_irr=return_metrics.levered_irr,
        equity_multiple=return_metrics.equity_multiple,
        dscr_by_year=return_metrics.dscr_by_year,
        headline_dscr=return_metrics.headline_dscr,
        min_dscr=return_metrics.min_dscr,
        levered_cash_on_cash_by_year=owner_return_metrics.levered_cash_on_cash_by_year,
        unlevered_cash_yield_by_year=owner_return_metrics.unlevered_cash_yield_by_year,
        cumulative_operating_distributions_by_year=(
            owner_return_metrics.cumulative_operating_distributions_by_year
        ),
        year_1_debt_yield=owner_return_metrics.year_1_debt_yield,
        closing_project_capital=owner_capital_schedule.closing_project_capital,
        project_capital_by_year=owner_capital_schedule.project_capital_by_year,
        post_hold_project_capital=owner_capital_schedule.post_hold_project_capital,
        owner_expenses_by_year=owner_capital_schedule.owner_expenses_by_year,
        property_cash_flow_by_year=property_cash_flow_by_year,
        unlevered_owner_cash_flow_by_year=unlevered_owner_cash_flow_by_year,
        levered_owner_cash_flow_by_year=levered_owner_cash_flow_by_year,
        total_closing_uses=total_closing_uses,
        total_closing_sources=total_closing_sources,
    )


def analyze_acquisition(
    inputs: AcquisitionInputs, *, owner_capital: OwnerCapitalSchedule | None = None
) -> AcquisitionResults:
    """Convert one ``AcquisitionInputs`` into one ``AcquisitionResults``.

    Phase 6 Gate D6.2: ``owner_capital`` is passed straight through to the
    shared engine; omitted, it is the empty Business Plan and the result is
    exactly the pre-D6.2 one. A ``BusinessPlan`` is resolved into it outside the
    engine (``anchor.analysis.business_plan_analysis``).

    The sole public Quick engine entry point
    (``docs/phase_2_deterministic_engine.md`` "Public Engine Entry Point"),
    unchanged in behavior by Detailed Operating Model V2.1 Gate 3. This
    function performs no calculation of its own: it builds the Quick
    operating projection and the shared ``AcquisitionTerms``, exactly once
    each, then delegates the entire downstream acquisition/debt/returns
    calculation to ``analyze_acquisition_from_operating_projection`` --
    the identical function ``analyze_detailed_acquisition`` (below) also
    calls.

    ``calculate_acquisition_cash_flows`` is intentionally not called here --
    it independently recomputes the NOI forecast, capital stack, and debt
    schedule internally, which would duplicate the calculations already
    performed by this function.
    """

    operating_projection = build_quick_operating_projection(inputs)
    terms = acquisition_terms_from_inputs(inputs)
    return analyze_acquisition_from_operating_projection(
        operating_projection, terms, owner_capital=owner_capital
    )


def analyze_detailed_acquisition_with_projection(
    terms: AcquisitionTerms,
    detailed_inputs: DetailedOperatingInputs,
    *,
    owner_capital: OwnerCapitalSchedule | None = None,
) -> DetailedAcquisitionResults:
    """Convert one ``AcquisitionTerms`` + ``DetailedOperatingInputs`` into
    one ``DetailedAcquisitionResults`` (Gate 4: the operating projection,
    exposed for downstream consumers, alongside the unchanged
    ``AcquisitionResults``).

    Phase 6 Gate D6.2: ``owner_capital`` is passed straight through to the
    shared engine, exactly as in ``analyze_acquisition``; omitted, it is the
    empty Business Plan. ``analyze_detailed_acquisition`` below deliberately
    does not take it -- its signature is pinned -- so a Detailed Business Plan
    analysis goes through this envelope entry point.

    The richer Detailed public engine entry point
    (``docs/detailed_operating_model_v2_1_architecture.md`` Section 4). No
    ``AcquisitionInputs`` instance is constructed, read, or required
    anywhere in this call -- ``current_noi``, ``noi_growth``, and
    ``occupancy`` simply do not exist in this path. Builds the Detailed
    operating projection exactly once and reuses it for both the
    ``AcquisitionResults`` calculation (via
    ``analyze_acquisition_from_operating_projection`` -- the identical
    function ``analyze_acquisition`` above also calls) and the returned
    envelope's ``operating_projection`` field -- never recomputed. Neither
    entry point duplicates any debt, exit-valuation, transaction-cost,
    CapEx, IRR, equity-multiple, DSCR, sensitivity, or break-even logic.
    """

    operating_projection = build_detailed_operating_projection(
        detailed_inputs,
        hold_period=terms.hold_period,
        purchase_price=terms.purchase_price,
    )
    results = analyze_acquisition_from_operating_projection(
        operating_projection, terms, owner_capital=owner_capital
    )
    return DetailedAcquisitionResults(
        operating_projection=operating_projection, results=results
    )


def analyze_detailed_acquisition(
    terms: AcquisitionTerms,
    detailed_inputs: DetailedOperatingInputs,
) -> AcquisitionResults:
    """Convert one ``AcquisitionTerms`` + ``DetailedOperatingInputs`` into
    one ``AcquisitionResults`` -- unchanged public behavior/signature since
    Gate 3. A thin wrapper around
    ``analyze_detailed_acquisition_with_projection`` (Gate 4): the operating
    projection is still computed exactly once, this function simply
    discards the richer envelope's extra field for a caller that only wants
    the acquisition results."""

    return analyze_detailed_acquisition_with_projection(terms, detailed_inputs).results
