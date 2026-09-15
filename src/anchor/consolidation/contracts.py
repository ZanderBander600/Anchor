"""Phase 7 Gate P7.6 -- the consolidation contracts.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
9 (CON-1 to CON-3, the additive and derived lists, the never-consolidated
list), 10, 11 and 14; that document governs on any discrepancy. Like
``anchor.engine.contracts``, this module performs no calculation of its own.

**A new, downstream contract.** ``ConsolidatedResults`` is the project economics
of one Analysis Variant of a visible Investment. It is deliberately **not**
``AcquisitionResults``: that contract carries one purchase price and one loan,
which is not true of an Investment, and nothing is appended to it (Section
4.5). Every Unit keeps its own complete result envelope beside this one; a
consolidated figure never alters a Unit's.

**Names say what a figure is.** ``aggregate_dscr_by_year`` is consolidated NOI
over consolidated acquisition-loan debt service -- never a Unit's DSCR, an
average of Unit DSCRs or the lowest Unit DSCR. ``implied_exit_cap_rate`` is a
reporting ratio of consolidated exit NOI to consolidated exit value, and never an
input. ``allocated_purchase_price`` is the sum of the Units' engine prices, and
``transaction_price`` the Investment's stated price, which reaches no cash flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..engine.contracts import AcquisitionResults, IrrStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsolidationUnit:
    """One Unit's completed result, as consolidation receives it.

    - ``unit_id``: the Deal's id, the canonical order of every sum (CON-3).
    - ``purchase_price`` and ``hold_period``: the Unit's *resolved* inputs --
      what its engine ran with. The price is its allocation (PP-1).
    - ``results``: the Unit's completed ``AcquisitionResults``, whichever mode
      produced it. Consolidation reads only the fields it sums.
    - ``occupied_area_at_year_end`` / ``vacant_area_at_year_end``: the Unit's
      own year-end area state, when its result contract exposes one (a
      Lease-Level Unit's annual projection); ``None`` otherwise. Nothing is
      invented for a Unit that has no rentable area (Q11).

    There is deliberately no ``unit_kind``, label or ordinal here: presentation
    never reaches a calculation."""

    unit_id: str
    purchase_price: float
    hold_period: int
    results: AcquisitionResults
    occupied_area_at_year_end: tuple[float, ...] | None = None
    vacant_area_at_year_end: tuple[float, ...] | None = None


class AreaMetricReason(StrEnum):
    """Why an area-weighted consolidated figure is not reported (P-9, Q11)."""

    UNIT_WITHOUT_AREA_MEASURE = "unit_without_area_measure"


class ConsolidationError(RuntimeError):
    """Consolidation was handed an incoherent set of Units -- mismatched
    horizons, an unreconciled allocation, an unsupported cost. The variant
    pathway validates all of these first, so reaching this is a programming
    error, never an analyst finding; it is not a ``ValueError`` so no caller
    can mistake it for an invalid variant."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsolidatedResults:
    """The consolidated project economics of one Analysis Variant (Section 9).

    Every additive figure is the ascending-``unit_id`` sum of the Units'
    figures, with the Investment-level channels applied once, at this layer
    only. Every ratio and return is derived from the consolidated series with
    the existing ``anchor.engine.returns`` functions -- never averaged.

    **Closing.** ``transaction_price`` is reporting and validation only;
    ``allocated_purchase_price`` is the Units' prices summed, the figure the
    cash flows used; ``allocation_variance`` is the exact difference PP-2
    tested. ``investment_transaction_costs`` and
    ``investment_closing_project_capital`` are the Investment-level closing
    uses; ``closing_project_capital`` adds the Units' own. ``initial_equity``,
    ``total_closing_uses`` and ``total_closing_sources`` include both, and
    ``unlevered_project_basis`` is the consolidated unlevered cost at closing,
    ``-unlevered_cash_flows[0]``.

    **Annual (Years 1..H).** Operating and property lines are Unit sums; the
    Investment-level plan reaches only ``project_capital_by_year``,
    ``owner_expenses_by_year`` and the two owner cash-flow series, and never
    Property Cash Flow, NOI or debt service. The ``investment_*`` series show
    the Investment-level share of each.

    **Exit (at the common horizon H).** Unit sums, never averages.
    ``post_hold_project_capital`` is disclosure only.

    **Derived.** IRRs with their ``IrrStatus``, the Equity Cash Flow totals,
    the Equity Multiple and the Net Additional Equity Requirement come from
    the consolidated series through ``calculate_return_metrics``; Aggregate DSCR
    is consolidated NOI over consolidated debt service; cash-on-cash, cash yield
    and cumulative operating distributions read the consolidated owner series.

    **Area.** ``physical_occupancy_at_year_end`` is reported only when every
    Unit exposes its year-end occupied and vacant area; otherwise it is
    ``None`` with a deterministic reason. There is no partial weighted average
    over the Units that have an area (Q11), and no consolidated rent per square
    foot or operating statement is produced here: no definition common to every
    mode exists, and a Quick Unit reports NOI only."""

    unit_ids: tuple[str, ...]
    hold_period: int

    transaction_price: float
    allocated_purchase_price: float
    allocation_variance: float
    acquisition_costs: float
    financing_fees: float
    investment_transaction_costs: float
    investment_closing_project_capital: float
    closing_project_capital: float
    loan_amount: float
    initial_equity: float
    total_closing_uses: float
    total_closing_sources: float
    unlevered_project_basis: float

    noi_by_year: tuple[float, ...]
    capex_by_year: tuple[float, ...]
    tenant_improvements_by_year: tuple[float, ...]
    leasing_commissions_by_year: tuple[float, ...]
    property_cash_flow_by_year: tuple[float, ...]
    investment_project_capital_by_year: tuple[float, ...]
    investment_owner_expenses_by_year: tuple[float, ...]
    project_capital_by_year: tuple[float, ...]
    owner_expenses_by_year: tuple[float, ...]
    unlevered_owner_cash_flow_by_year: tuple[float, ...]
    annual_debt_service: tuple[float, ...]
    levered_owner_cash_flow_by_year: tuple[float, ...]

    remaining_loan_balance: float
    exit_noi: float
    exit_value: float
    disposition_costs: float
    net_sale_proceeds: float
    investment_post_hold_project_capital: float
    post_hold_project_capital: float
    implied_exit_cap_rate: float | None

    unlevered_cash_flows: tuple[float, ...]
    levered_cash_flows: tuple[float, ...]

    unlevered_irr: float | None
    unlevered_irr_status: IrrStatus
    levered_irr: float | None
    levered_irr_status: IrrStatus
    total_equity_invested: float
    total_cash_returned: float
    total_profit: float
    equity_multiple: float | None
    net_additional_equity_requirement_by_year: tuple[float, ...]

    aggregate_dscr_by_year: tuple[float | None, ...]
    headline_aggregate_dscr: float | None
    min_aggregate_dscr: float | None
    going_in_cap_rate: float
    year_1_debt_yield: float | None
    levered_cash_on_cash_by_year: tuple[float | None, ...]
    unlevered_cash_yield_by_year: tuple[float | None, ...]
    cumulative_operating_distributions_by_year: tuple[float, ...]

    physical_occupancy_at_year_end: tuple[float, ...] | None
    physical_occupancy_reason: AreaMetricReason | None
    physical_occupancy_message: str | None
