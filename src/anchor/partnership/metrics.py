"""Phase 7 Gate P7.9 -- partner returns and Common Equity Total Profit.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 3 and 12
(ratified); that document governs on any discrepancy.

**Existing authorities, reused unchanged (P-3).** This is the package's only
importer of ``anchor.engine.returns``. A partner's IRR is ``evaluate_irr`` on
its net annual series (D10; no second solver, no XIRR); its totals are
``calculate_project_return_totals`` and its MOIC ``calculate_equity_multiple``
on the same series. Because every annual period is one-signed for every
partner (PW-4), the sign split of the net series is exactly its contributions
and its distributions.

**One authority for Common Equity Total Profit.** It is derived from the
Common Equity Cash Flow with ``calculate_project_return_totals``, the function
``capital_structure.metrics.common_equity_metrics`` applies to the same series.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engine.contracts import IrrStatus, ensure_finite
from ..engine.returns import calculate_equity_multiple, calculate_project_return_totals, evaluate_irr
from .contracts import MoicUnavailableReason


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnerReturns:
    net_cash_flows: tuple[float, ...]
    total_contributions: float
    total_distributions: float
    profit: float
    irr: float | None
    irr_status: IrrStatus
    moic: float | None
    moic_unavailable_reason: MoicUnavailableReason | None


def common_equity_total_profit(cash_flows: tuple[float, ...]) -> float:
    """Common Equity Total Profit of the series itself."""

    _, _, total_profit = calculate_project_return_totals(levered_cash_flows=cash_flows)
    return total_profit


def net_cash_flows(contributions: tuple[float, ...], distributions: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(
        ensure_finite(f"net_cash_flows[{period}]", distributed - contributed)
        for period, (contributed, distributed) in enumerate(zip(contributions, distributions, strict=True))
    )


def partner_returns(contributions: tuple[float, ...], distributions: tuple[float, ...]) -> PartnerReturns:
    """A partner's returns on its net series, with the existing functions."""

    net = net_cash_flows(contributions, distributions)
    total_distributions, total_contributions, profit = calculate_project_return_totals(levered_cash_flows=net)
    irr, irr_status = evaluate_irr(net)
    moic = calculate_equity_multiple(levered_cash_flows=net)
    return PartnerReturns(
        net_cash_flows=net,
        total_contributions=total_contributions,
        total_distributions=total_distributions,
        profit=profit,
        irr=irr,
        irr_status=irr_status,
        moic=moic,
        moic_unavailable_reason=MoicUnavailableReason.NO_CONTRIBUTIONS if total_contributions == 0.0 else None,
    )
