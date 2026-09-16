"""Phase 7 Gate P7.8 -- position and common-equity metrics.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
3 (P-3, P-9), 12.6 and 14 and the P7.8 decisions of
``docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md``; those documents
govern on any discrepancy.

**Existing authorities, reused (P-3).** Every IRR is
``anchor.engine.returns.evaluate_irr`` on an annual series (D10; no second
solver, no XIRR, no monthly IRR). Common equity's Equity Multiple and totals are
``calculate_equity_multiple`` and ``calculate_project_return_totals``. Coverage
through a position is ``calculate_dscr_by_year`` over a cumulative current cash
service (``None`` when that service is zero), with ``calculate_headline_dscr``
and ``calculate_min_dscr``; debt yield through a position is
``calculate_year_1_debt_yield`` over the last-dollar basis.

**Annual aggregation.** Events are summed into D6 annual periods ``t = 0..H``
(month 0 is ``t = 0``, month ``m`` is hold year ``((m - 1) // 12) + 1``) in
canonical order: model month, then sequence, then event id.

**Position MOIC and profit** read the gross events: every positive receipt over
the gross capital advanced. A closing fee is a receipt and is never netted
against the funding, although the IRR series, being net per period, nets them.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..engine.contracts import IrrStatus, ensure_finite
from ..engine.returns import (
    calculate_dscr_by_year,
    calculate_equity_multiple,
    calculate_headline_dscr,
    calculate_min_dscr,
    calculate_project_return_totals,
    calculate_year_1_debt_yield,
    evaluate_irr,
)
from .execution_contracts import PositionCashFlowEvent, PositionCashFlowKind, PriceBasis
from .foundation import annual_period_of_model_month

#: The recurring cash service a coverage denominator counts: never a balloon, a
#: redemption, an accrued balance, a fee or a funding.
CURRENT_CASH_SERVICE_KINDS = frozenset(
    {PositionCashFlowKind.SCHEDULED_DEBT_SERVICE, PositionCashFlowKind.PREFERRED_CURRENT_PAY}
)


def event_order_key(event: PositionCashFlowEvent) -> tuple[int, int, str]:
    """Canonical event order. The event id is a non-economic tie-break only."""

    return (event.model_month, event.sequence, event.event_id)


def annual_position_cash_flows(events: Iterable[PositionCashFlowEvent], *, hold_period: int) -> tuple[float, ...]:
    """The provider cash-flow series ``t = 0..H``: each event added to its D6
    annual period in canonical order."""

    totals = [0.0 for _ in range(hold_period + 1)]
    for event in sorted(events, key=event_order_key):
        period = annual_period_of_model_month(event.model_month)
        totals[period] = totals[period] + event.amount
    return tuple(ensure_finite(f"annual_position_cash_flows[{period}]", total) for period, total in enumerate(totals))


def annual_current_cash_service(events: Iterable[PositionCashFlowEvent], *, hold_period: int) -> tuple[float, ...]:
    """The recurring current cash service of one position in each hold year
    ``1..H``: its scheduled debt payments or preferred current pay."""

    totals = [0.0 for _ in range(hold_period)]
    for event in sorted(events, key=event_order_key):
        if event.kind in CURRENT_CASH_SERVICE_KINDS:
            year = annual_period_of_model_month(event.model_month)
            totals[year - 1] = totals[year - 1] + event.amount
    return tuple(ensure_finite(f"annual_current_cash_service[{year}]", total) for year, total in enumerate(totals, start=1))


def position_receipts(events: Iterable[PositionCashFlowEvent], *, funded_amount: float) -> tuple[float, float, float]:
    """``(total_cash_received, moic, profit)``: every positive receipt, fees
    included, in canonical order; over and less the gross capital advanced."""

    received = 0.0
    for event in sorted(events, key=event_order_key):
        if event.amount > 0.0:
            received = received + event.amount
    received = ensure_finite("total_cash_received", received)
    return (
        received,
        ensure_finite("moic", received / funded_amount),
        ensure_finite("profit", received - funded_amount),
    )


def position_irr(annual_cash_flows: tuple[float, ...]) -> tuple[float | None, IrrStatus]:
    """The existing IRR procedure on the annual provider series, unchanged."""

    return evaluate_irr(annual_cash_flows)


def loan_to_price(basis: float, price_basis: PriceBasis) -> float | None:
    """``basis`` over the stated acquisition price; never capped at 100%."""

    if price_basis.amount == 0.0:
        return None
    return ensure_finite("loan_to_price", basis / price_basis.amount)


def coverage_through(
    *, noi_by_year: tuple[float, ...], cumulative_service_by_year: tuple[float, ...], outstanding_years: int
) -> tuple[tuple[float | None, ...], float | None, float | None]:
    """``(coverage_by_year, headline, minimum)``: NOI over the cumulative
    current cash service, for the years the position is outstanding, with the
    DSCR N/A rule; ``None`` for every later year."""

    defined = calculate_dscr_by_year(
        noi_by_year=noi_by_year[:outstanding_years],
        annual_debt_service=cumulative_service_by_year[:outstanding_years],
    )
    by_year = (*defined, *(None for _ in noi_by_year[outstanding_years:]))
    return by_year, calculate_headline_dscr(dscr_by_year=by_year), calculate_min_dscr(dscr_by_year=by_year)


def debt_yield_through(*, year_1_noi: float, last_dollar_basis: float) -> float | None:
    """Year-1 NOI of the scope over the last-dollar basis."""

    return calculate_year_1_debt_yield(year_1_noi=year_1_noi, loan_amount=last_dollar_basis)


def common_equity_metrics(
    cash_flows: tuple[float, ...],
) -> tuple[float | None, IrrStatus, float | None, float, float, float]:
    """``(irr, irr_status, equity_multiple, total_equity_invested,
    total_cash_returned, total_profit)`` of the final residual series."""

    irr, irr_status = evaluate_irr(cash_flows)
    equity_multiple = calculate_equity_multiple(levered_cash_flows=cash_flows)
    total_cash_returned, total_equity_invested, total_profit = calculate_project_return_totals(
        levered_cash_flows=cash_flows
    )
    return irr, irr_status, equity_multiple, total_equity_invested, total_cash_returned, total_profit
