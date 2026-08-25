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

from ..contracts import AcquisitionInputs
from .contracts import AcquisitionCashFlows, ensure_finite
from .debt import calculate_capital_stack, calculate_debt_schedule
from .noi import forecast_noi


def calculate_exit_value(*, exit_noi: float, exit_cap_rate: float) -> float:
    """Return ``Exit Value = Exit NOI / Exit Cap Rate``.

    Sale costs are 0 (Phase 0 exclusion). ``exit_cap_rate > 0`` is already
    guaranteed by the input domain, so this division is always defined.
    """

    exit_value = exit_noi / exit_cap_rate
    return ensure_finite("exit_value", exit_value)


def calculate_net_sale_proceeds(
    *, exit_value: float, remaining_loan_balance: float
) -> float:
    """Return the levered net sale proceeds: ``Exit Value - Remaining Loan Balance``."""

    net_sale_proceeds = exit_value - remaining_loan_balance
    return ensure_finite("net_sale_proceeds", net_sale_proceeds)


def calculate_unlevered_cash_flows(
    *,
    purchase_price: float,
    noi_by_year: tuple[float, ...],
    exit_value: float,
) -> tuple[float, ...]:
    """Return ``(UCF_0, UCF_1, ..., UCF_H)``, length ``H + 1``.

    ``UCF_0 = -purchase_price``; ``UCF_y = NOI_y`` for ``1 <= y < H``;
    ``UCF_H = NOI_H + exit_value``. No debt term appears anywhere in this
    series, and ``exit_noi`` (already folded into ``exit_value``) is never
    added again as a separate operating cash flow.
    """

    hold_period = len(noi_by_year)

    cash_flows = [ensure_finite("unlevered_cash_flows[0]", -purchase_price)]
    for year in range(1, hold_period):
        ucf_y = noi_by_year[year - 1]
        cash_flows.append(ensure_finite(f"unlevered_cash_flows[{year}]", ucf_y))

    ucf_h = noi_by_year[hold_period - 1] + exit_value
    cash_flows.append(ensure_finite(f"unlevered_cash_flows[{hold_period}]", ucf_h))

    return tuple(cash_flows)


def calculate_levered_cash_flows(
    *,
    initial_equity: float,
    noi_by_year: tuple[float, ...],
    annual_debt_service: tuple[float, ...],
    net_sale_proceeds: float,
) -> tuple[float, ...]:
    """Return ``(LCF_0, LCF_1, ..., LCF_H)``, length ``H + 1``.

    ``LCF_0 = -initial_equity``; ``LCF_y = NOI_y - ADS_y`` for
    ``1 <= y < H``; ``LCF_H = NOI_H - ADS_H + net_sale_proceeds``. The
    already-computed ``net_sale_proceeds`` (Phase 2C) is used directly for
    the sale component of ``LCF_H`` rather than re-expanding
    ``exit_value - remaining_loan_balance`` inline, so the single computed
    value is reused rather than recomputed.
    """

    hold_period = len(noi_by_year)

    cash_flows = [ensure_finite("levered_cash_flows[0]", -initial_equity)]
    for year in range(1, hold_period):
        lcf_y = noi_by_year[year - 1] - annual_debt_service[year - 1]
        cash_flows.append(ensure_finite(f"levered_cash_flows[{year}]", lcf_y))

    lcf_h = (
        noi_by_year[hold_period - 1]
        - annual_debt_service[hold_period - 1]
        + net_sale_proceeds
    )
    cash_flows.append(ensure_finite(f"levered_cash_flows[{hold_period}]", lcf_h))

    return tuple(cash_flows)


def calculate_acquisition_cash_flows(inputs: AcquisitionInputs) -> AcquisitionCashFlows:
    """Compute the Phase 2C exit value, net sale proceeds, and cash-flow
    tuples for one ``AcquisitionInputs``, built on top of the Phase 2A NOI
    forecast and Phase 2B debt schedule."""

    noi_forecast = forecast_noi(inputs)
    capital_stack = calculate_capital_stack(inputs)
    debt_schedule = calculate_debt_schedule(inputs)

    exit_value = calculate_exit_value(
        exit_noi=noi_forecast.exit_noi, exit_cap_rate=inputs.exit_cap_rate
    )
    net_sale_proceeds = calculate_net_sale_proceeds(
        exit_value=exit_value,
        remaining_loan_balance=debt_schedule.remaining_loan_balance,
    )

    unlevered_cash_flows = calculate_unlevered_cash_flows(
        purchase_price=inputs.purchase_price,
        noi_by_year=noi_forecast.noi_by_year,
        exit_value=exit_value,
    )
    levered_cash_flows = calculate_levered_cash_flows(
        initial_equity=capital_stack.initial_equity,
        noi_by_year=noi_forecast.noi_by_year,
        annual_debt_service=debt_schedule.annual_debt_service,
        net_sale_proceeds=net_sale_proceeds,
    )

    return AcquisitionCashFlows(
        exit_value=exit_value,
        net_sale_proceeds=net_sale_proceeds,
        unlevered_cash_flows=unlevered_cash_flows,
        levered_cash_flows=levered_cash_flows,
    )
