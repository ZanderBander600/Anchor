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
    OperatingProjectionLike,
    ensure_finite,
)
from .debt import calculate_capital_stack, calculate_debt_schedule
from .noi import build_quick_operating_projection, forecast_noi
from .operating_projection import build_detailed_operating_projection
from .returns import calculate_return_metrics


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
) -> tuple[float, ...]:
    """Return ``(UCF_0, UCF_1, ..., UCF_H)``, length ``H + 1``.

    ``UCF_0 = -(purchase_price + acquisition_costs)``; ``UCF_y = NOI_y -
    CapEx_y`` for ``1 <= y < H``; ``UCF_H = NOI_H - CapEx_H + exit_value -
    disposition_costs``. At the Gate 2/3 neutral defaults (all cost terms
    ``0.0``, ``capex_by_year`` empty/all-zero), this reduces to exactly the
    V1 formulas. No debt term appears anywhere in this series (a financing
    fee, being debt-related, never appears in the unlevered series
    either), and ``exit_noi`` (already folded into ``exit_value``) is never
    added again as a separate operating cash flow. CapEx may exceed NOI in
    any year, producing a negative entry -- it is never capped or
    rejected.
    """

    hold_period = len(noi_by_year)
    capex = capex_by_year or tuple(0.0 for _ in range(hold_period))

    cash_flows = [
        ensure_finite(
            "unlevered_cash_flows[0]", -(purchase_price + acquisition_costs)
        )
    ]
    for year in range(1, hold_period):
        ucf_y = noi_by_year[year - 1] - capex[year - 1]
        cash_flows.append(ensure_finite(f"unlevered_cash_flows[{year}]", ucf_y))

    ucf_h = (
        noi_by_year[hold_period - 1]
        - capex[hold_period - 1]
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
) -> tuple[float, ...]:
    """Return ``(LCF_0, LCF_1, ..., LCF_H)``, length ``H + 1``.

    ``LCF_0 = -initial_equity``; ``LCF_y = NOI_y - ADS_y - CapEx_y`` for
    ``1 <= y < H``; ``LCF_H = NOI_H - ADS_H - CapEx_H + net_sale_proceeds``.
    The already-computed ``net_sale_proceeds`` (Phase 2C) is used directly
    for the sale component of ``LCF_H`` rather than re-expanding
    ``exit_value - remaining_loan_balance`` inline, so the single computed
    value is reused rather than recomputed. At the Gate 3 neutral default
    (``capex_by_year`` empty/all-zero), this reduces to exactly the prior
    formulas. CapEx may exceed the year's operating cash flow, producing a
    negative entry -- it is never capped or rejected.
    """

    hold_period = len(noi_by_year)
    capex = capex_by_year or tuple(0.0 for _ in range(hold_period))

    cash_flows = [ensure_finite("levered_cash_flows[0]", -initial_equity)]
    for year in range(1, hold_period):
        lcf_y = noi_by_year[year - 1] - annual_debt_service[year - 1] - capex[year - 1]
        cash_flows.append(ensure_finite(f"levered_cash_flows[{year}]", lcf_y))

    lcf_h = (
        noi_by_year[hold_period - 1]
        - annual_debt_service[hold_period - 1]
        - capex[hold_period - 1]
        + net_sale_proceeds
    )
    cash_flows.append(ensure_finite(f"levered_cash_flows[{hold_period}]", lcf_h))

    return tuple(cash_flows)


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
) -> AcquisitionResults:
    """The single authoritative downstream acquisition/debt/returns
    calculation path (``docs/detailed_operating_model_v2_1_architecture.md``
    Section 3.1/3.2).

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
    unlevered_cash_flows = calculate_unlevered_cash_flows(
        purchase_price=terms.purchase_price,
        noi_by_year=operating_projection.noi_by_year,
        exit_value=exit_value,
        acquisition_costs=capital_stack.acquisition_costs,
        disposition_costs=disposition_costs,
        capex_by_year=capex_by_year,
    )
    levered_cash_flows = calculate_levered_cash_flows(
        initial_equity=capital_stack.initial_equity,
        noi_by_year=operating_projection.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        net_sale_proceeds=net_sale_proceeds,
        capex_by_year=capex_by_year,
    )

    return_metrics = calculate_return_metrics(
        noi_by_year=operating_projection.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        unlevered_cash_flows=unlevered_cash_flows,
        levered_cash_flows=levered_cash_flows,
    )

    return AcquisitionResults(
        going_in_cap_rate=operating_projection.going_in_cap_rate,
        loan_amount=capital_stack.loan_amount,
        acquisition_costs=capital_stack.acquisition_costs,
        financing_fee=capital_stack.financing_fee,
        initial_equity=capital_stack.initial_equity,
        monthly_debt_service=debt_schedule.monthly_debt_service,
        annual_debt_service=debt_schedule.annual_debt_service,
        remaining_loan_balance=debt_schedule.remaining_loan_balance,
        noi_by_year=operating_projection.noi_by_year,
        capex_by_year=capex_by_year,
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
    )


def analyze_acquisition(inputs: AcquisitionInputs) -> AcquisitionResults:
    """Convert one ``AcquisitionInputs`` into one ``AcquisitionResults``.

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
    return analyze_acquisition_from_operating_projection(operating_projection, terms)


def analyze_detailed_acquisition(
    terms: AcquisitionTerms,
    detailed_inputs: DetailedOperatingInputs,
) -> AcquisitionResults:
    """Convert one ``AcquisitionTerms`` + ``DetailedOperatingInputs`` into
    one ``AcquisitionResults``.

    The Detailed public engine entry point
    (``docs/detailed_operating_model_v2_1_architecture.md`` Section 4). No
    ``AcquisitionInputs`` instance is constructed, read, or required
    anywhere in this call -- ``current_noi``, ``noi_growth``, and
    ``occupancy`` simply do not exist in this path. Builds the Detailed
    operating projection, exactly once, then delegates the entire
    downstream acquisition/debt/returns calculation to
    ``analyze_acquisition_from_operating_projection`` -- the identical
    function ``analyze_acquisition`` (above) also calls. Neither entry
    point duplicates any debt, exit-valuation, transaction-cost, CapEx,
    IRR, equity-multiple, DSCR, sensitivity, or break-even logic.
    """

    operating_projection = build_detailed_operating_projection(
        detailed_inputs,
        hold_period=terms.hold_period,
        purchase_price=terms.purchase_price,
    )
    return analyze_acquisition_from_operating_projection(operating_projection, terms)
