"""Phase 7 Gate P7.6 -- consolidation: completed Unit results into Investment
project economics.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
3 (P-1, P-3, P-4, P-9), 9, 10 (BP-2 to BP-4), 11 (PP-2, PP-3, TC-1, TC-2) and
the Section 21 record (Q6, Q7, Q8, Q9, Q11); that document governs on any
discrepancy. P7.6 carries the one Q16 engine-scope approval for this layer:
deterministic consolidation of completed Unit results; Investment-level returns
and ratios derived from the consolidated series with the existing
``anchor.engine.returns`` functions; and the Investment-level Business Plan and
transaction costs applied here, once. No Unit formula, debt formula, exit
formula, D6 convention or the IRR algorithm moves.

**Downstream and one-way (P-3, P-4).** This module consumes completed
``AcquisitionResults`` -- the existing engine's output for each Unit -- and
never re-derives an operating, debt or exit figure the engine produced. It
calls no engine entry point, writes nothing upstream, and knows no mode, no
Unit kind, no label and no display order. It never allocates: every dollar
here already belongs to one Unit, or to the Investment.

**Canonical order (CON-3).** Units are sorted by ``unit_id`` once, and every
additive figure is summed left to right in that order, starting from the first
Unit's own value. Floating-point addition is not associative, so the result is
bit-reproducible whatever order the Units were supplied or displayed in; and a
one-Unit Investment reproduces its Unit's figures bit for bit, because a sum of
one value is that value and subtracting ``0.0`` is exact.

**The Investment-level channels, one subtraction site each (BP-3, TC-1):**

- the Investment Business Plan, resolved by the caller with the existing
  ``resolve_business_plan`` for the common hold ``H``: closing project capital
  raises Initial Equity, Total Closing Uses and the unlevered basis, and is
  subtracted from both ``t = 0`` cash flows; annual project capital and owner
  expenses reduce both owner cash-flow series and both project cash-flow
  series in their years. They never reach NOI, Property Cash Flow, debt
  service, exit value or any Unit's result. Post-hold capital is disclosed;
- transaction costs, at closing: they raise Initial Equity, Total Closing
  Uses and the unlevered basis, and are subtracted from both ``t = 0`` cash
  flows. They never reach a Unit's price, loan, costs, NOI or debt service.

Unit Business Plans are already inside each Unit's results and are never
subtracted again. The transaction price is never a cash flow (PP-3): the
consolidated purchase price is the Units' allocated prices, summed.

**Derived after consolidation, never averaged (Section 9.3).** The IRRs and
their statuses, TEI, TCR, Total Profit, the Equity Multiple and NAER come from
``calculate_return_metrics`` over the final consolidated series -- so NAER and
TEI are read off the consolidated Equity Cash Flow, where one Unit's negative
year can offset another's positive year, and are never Unit sums. Aggregate
DSCR, debt yield, cash-on-cash, cash yield and cumulative distributions use the
same ``returns`` functions the engine uses.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from math import fsum

from ..engine.contracts import AcquisitionResults, OwnerCapitalSchedule, ensure_finite
from ..engine.returns import (
    calculate_cumulative_operating_distributions_by_year,
    calculate_levered_cash_on_cash_by_year,
    calculate_return_metrics,
    calculate_unlevered_cash_yield_by_year,
    calculate_year_1_debt_yield,
)
from ..investment.contracts import InvestmentTransactionCost
from ..investment.validation import (
    allocation_variance,
    validate_allocation,
    validate_transaction_costs,
)
from .contracts import (
    AreaMetricReason,
    ConsolidatedResults,
    ConsolidationError,
    ConsolidationUnit,
)


def _canonical_sum(values: Sequence[float], field: str) -> float:
    """The left-to-right sum of ``values``, already in canonical Unit order,
    starting from the first value itself -- so a single value is returned bit
    for bit."""

    total = values[0]
    for value in values[1:]:
        total = total + value
    return ensure_finite(field, total)


def _unit_sum(
    units: Sequence[ConsolidationUnit], read: Callable[[AcquisitionResults], float], field: str
) -> float:
    return _canonical_sum([read(unit.results) for unit in units], field)


def _unit_series(
    units: Sequence[ConsolidationUnit],
    read: Callable[[AcquisitionResults], tuple[float, ...]],
    field: str,
) -> tuple[float, ...]:
    length = len(read(units[0].results))
    return tuple(
        _canonical_sum([read(unit.results)[index] for unit in units], f"{field}[{index}]")
        for index in range(length)
    )


def _require_coherent(units: Sequence[ConsolidationUnit]) -> int:
    """The common hold ``H``, or ``ConsolidationError``: at least one Unit,
    each named once, each with the same hold, and each result's series of the
    lengths that hold implies."""

    if not units:
        raise ConsolidationError("Consolidation needs at least one Unit.")
    for unit in units:
        if not isinstance(unit, ConsolidationUnit):
            raise ConsolidationError(f"Not a ConsolidationUnit: {type(unit).__qualname__}.")
    unit_ids = [unit.unit_id for unit in units]
    if len(set(unit_ids)) != len(unit_ids):
        raise ConsolidationError("A Unit is given more than once.")
    holds = {unit.hold_period for unit in units}
    if len(holds) != 1:
        raise ConsolidationError(
            f"The Units do not share one hold period ({sorted(holds)}); CON-1 is validated "
            "before consolidation."
        )
    (hold_period,) = holds
    for unit in units:
        results = unit.results
        annual = (
            results.noi_by_year,
            results.capex_by_year,
            results.tenant_improvements_by_year,
            results.leasing_commissions_by_year,
            results.property_cash_flow_by_year,
            results.project_capital_by_year,
            results.owner_expenses_by_year,
            results.unlevered_owner_cash_flow_by_year,
            results.annual_debt_service,
            results.levered_owner_cash_flow_by_year,
        )
        if any(len(series) != hold_period for series in annual) or any(
            len(series) != hold_period + 1
            for series in (results.unlevered_cash_flows, results.levered_cash_flows)
        ):
            raise ConsolidationError(
                f"Unit {unit.unit_id!r}'s results do not span its {hold_period}-year hold."
            )
    return hold_period


def _investment_schedule(
    owner_capital: OwnerCapitalSchedule | None, hold_period: int
) -> OwnerCapitalSchedule:
    """The Investment-level plan for the common hold: the all-zero schedule
    when there is none, and a schedule resolved for another hold refused."""

    if owner_capital is None:
        zeros = tuple(0.0 for _ in range(hold_period))
        return OwnerCapitalSchedule(
            closing_project_capital=0.0,
            project_capital_by_year=zeros,
            owner_expenses_by_year=zeros,
            post_hold_project_capital=0.0,
        )
    if len(owner_capital.project_capital_by_year) != hold_period:
        raise ConsolidationError(
            f"The Investment Business Plan was resolved for "
            f"{len(owner_capital.project_capital_by_year)} years; the Investment holds for "
            f"{hold_period}."
        )
    return owner_capital


def _closing_transaction_costs(costs: tuple[InvestmentTransactionCost, ...]) -> float:
    """The closing total of the transaction costs: an exact, order-independent
    ``fsum`` of their amounts. Their descriptions and categories are never
    read."""

    issues = validate_transaction_costs(costs)
    if issues:
        raise ConsolidationError(
            "Transaction costs are validated before consolidation: "
            + "; ".join(issue.message for issue in issues)
        )
    return ensure_finite(
        "investment_transaction_costs",
        fsum(cost.amount for cost in sorted(costs, key=lambda cost: cost.cost_id)),
    )


def _year_end_occupancy(
    units: Sequence[ConsolidationUnit], hold_period: int
) -> tuple[tuple[float, ...] | None, AreaMetricReason | None, str | None]:
    """Area-weighted year-end physical occupancy: the Units' occupied area over
    their occupied plus vacant area, summed -- only when **every** Unit exposes
    both. Otherwise ``None``, with the Units that do not, and never a partial
    weighted average over the Units that do (Q11)."""

    without = [
        unit.unit_id
        for unit in units
        if unit.occupied_area_at_year_end is None or unit.vacant_area_at_year_end is None
    ]
    if without:
        return (
            None,
            AreaMetricReason.UNIT_WITHOUT_AREA_MEASURE,
            "Consolidated occupancy is not reported: Unit(s) "
            f"{', '.join(without)} expose no rentable-area measure, and occupancy is never "
            "averaged over only the Units that do.",
        )
    occupancy: list[float] = []
    for index in range(hold_period):
        occupied: list[float] = []
        rentable: list[float] = []
        for unit in units:
            assert unit.occupied_area_at_year_end is not None
            assert unit.vacant_area_at_year_end is not None
            if len(unit.occupied_area_at_year_end) != hold_period or len(unit.vacant_area_at_year_end) != hold_period:
                raise ConsolidationError(f"Unit {unit.unit_id!r}'s area state does not span the hold.")
            occupied.append(unit.occupied_area_at_year_end[index])
            rentable.append(unit.occupied_area_at_year_end[index] + unit.vacant_area_at_year_end[index])
        total_rentable = _canonical_sum(rentable, f"rentable_area_at_year_end[{index}]")
        if total_rentable <= 0.0:
            raise ConsolidationError("A consolidated rentable area must be positive.")
        occupancy.append(
            ensure_finite(
                f"physical_occupancy_at_year_end[{index}]",
                _canonical_sum(occupied, f"occupied_area_at_year_end[{index}]") / total_rentable,
            )
        )
    return tuple(occupancy), None, None


def consolidate(
    units: Iterable[ConsolidationUnit],
    *,
    transaction_price: float,
    investment_owner_capital: OwnerCapitalSchedule | None = None,
    transaction_costs: Iterable[InvestmentTransactionCost] = (),
) -> ConsolidatedResults:
    """Consolidate one Analysis Variant's completed Unit results.

    ``units`` may arrive in any order; they are summed in ascending ``unit_id``
    order. ``investment_owner_capital`` is the Investment-level Business Plan
    resolved for the common hold (``None`` for the empty plan).
    ``transaction_costs`` are the Investment's closing costs.

    Raises ``ConsolidationError`` for an incoherent input -- no Units, a
    repeated Unit, differing holds, a result that does not span the hold, an
    unreconciled allocation or an unsupported cost. Nothing is ever padded,
    truncated, rescaled or averaged."""

    ordered = tuple(sorted(units, key=lambda unit: unit.unit_id))
    hold_period = _require_coherent(ordered)
    costs = tuple(transaction_costs)

    unit_prices = [(unit.unit_id, unit.purchase_price) for unit in ordered]
    allocation_issues = validate_allocation(unit_prices=unit_prices, transaction_price=transaction_price)
    if allocation_issues:
        raise ConsolidationError(allocation_issues[0].message)
    investment = _investment_schedule(investment_owner_capital, hold_period)
    transaction_cost_total = _closing_transaction_costs(costs)
    investment_closing_capital = investment.closing_project_capital
    investment_capital = investment.project_capital_by_year
    investment_expenses = investment.owner_expenses_by_year

    # --- closing ------------------------------------------------------------
    allocated_purchase_price = _canonical_sum(
        [unit.purchase_price for unit in ordered], "allocated_purchase_price"
    )
    loan_amount = _unit_sum(ordered, lambda r: r.loan_amount, "loan_amount")
    initial_equity = ensure_finite(
        "initial_equity",
        _unit_sum(ordered, lambda r: r.initial_equity, "initial_equity")
        + investment_closing_capital
        + transaction_cost_total,
    )
    total_closing_uses = ensure_finite(
        "total_closing_uses",
        _unit_sum(ordered, lambda r: r.total_closing_uses, "total_closing_uses")
        + investment_closing_capital
        + transaction_cost_total,
    )

    # --- annual, Years 1..H -------------------------------------------------
    noi_by_year = _unit_series(ordered, lambda r: r.noi_by_year, "noi_by_year")
    annual_debt_service = _unit_series(ordered, lambda r: r.annual_debt_service, "annual_debt_service")
    unit_project_capital = _unit_series(ordered, lambda r: r.project_capital_by_year, "project_capital_by_year")
    unit_owner_expenses = _unit_series(ordered, lambda r: r.owner_expenses_by_year, "owner_expenses_by_year")
    unit_unlevered_owner = _unit_series(
        ordered, lambda r: r.unlevered_owner_cash_flow_by_year, "unlevered_owner_cash_flow_by_year"
    )
    unit_levered_owner = _unit_series(
        ordered, lambda r: r.levered_owner_cash_flow_by_year, "levered_owner_cash_flow_by_year"
    )
    years = range(hold_period)
    unlevered_owner_cash_flow_by_year = tuple(
        ensure_finite(
            f"unlevered_owner_cash_flow_by_year[{y}]",
            unit_unlevered_owner[y] - investment_capital[y] - investment_expenses[y],
        )
        for y in years
    )
    levered_owner_cash_flow_by_year = tuple(
        ensure_finite(
            f"levered_owner_cash_flow_by_year[{y}]",
            unit_levered_owner[y] - investment_capital[y] - investment_expenses[y],
        )
        for y in years
    )

    # --- the project cash flows, t = 0..H ----------------------------------
    unit_unlevered = _unit_series(ordered, lambda r: r.unlevered_cash_flows, "unlevered_cash_flows")
    unit_levered = _unit_series(ordered, lambda r: r.levered_cash_flows, "levered_cash_flows")
    unlevered_cash_flows = (
        ensure_finite(
            "unlevered_cash_flows[0]",
            unit_unlevered[0] - investment_closing_capital - transaction_cost_total,
        ),
        *(
            ensure_finite(
                f"unlevered_cash_flows[{t}]",
                unit_unlevered[t] - investment_capital[t - 1] - investment_expenses[t - 1],
            )
            for t in range(1, hold_period + 1)
        ),
    )
    levered_cash_flows = (
        ensure_finite(
            "levered_cash_flows[0]",
            unit_levered[0] - investment_closing_capital - transaction_cost_total,
        ),
        *(
            ensure_finite(
                f"levered_cash_flows[{t}]",
                unit_levered[t] - investment_capital[t - 1] - investment_expenses[t - 1],
            )
            for t in range(1, hold_period + 1)
        ),
    )

    # --- exit, at the common horizon ----------------------------------------
    exit_noi = _unit_sum(ordered, lambda r: r.exit_noi, "exit_noi")
    exit_value = _unit_sum(ordered, lambda r: r.exit_value, "exit_value")

    # --- derived from the consolidated series, never averaged ---------------
    return_metrics = calculate_return_metrics(
        noi_by_year=noi_by_year,
        annual_debt_service=annual_debt_service,
        unlevered_cash_flows=unlevered_cash_flows,
        levered_cash_flows=levered_cash_flows,
    )
    unlevered_project_basis = ensure_finite("unlevered_project_basis", -unlevered_cash_flows[0])
    occupancy, occupancy_reason, occupancy_message = _year_end_occupancy(ordered, hold_period)

    return ConsolidatedResults(
        unit_ids=tuple(unit.unit_id for unit in ordered),
        hold_period=hold_period,
        transaction_price=float(transaction_price),
        allocated_purchase_price=allocated_purchase_price,
        allocation_variance=float(
            allocation_variance(unit_prices=unit_prices, transaction_price=transaction_price)
        ),
        acquisition_costs=_unit_sum(ordered, lambda r: r.acquisition_costs, "acquisition_costs"),
        financing_fees=_unit_sum(ordered, lambda r: r.financing_fee, "financing_fees"),
        investment_transaction_costs=transaction_cost_total,
        investment_closing_project_capital=investment_closing_capital,
        closing_project_capital=ensure_finite(
            "closing_project_capital",
            _unit_sum(ordered, lambda r: r.closing_project_capital, "closing_project_capital")
            + investment_closing_capital,
        ),
        loan_amount=loan_amount,
        initial_equity=initial_equity,
        total_closing_uses=total_closing_uses,
        total_closing_sources=ensure_finite("total_closing_sources", loan_amount + initial_equity),
        unlevered_project_basis=unlevered_project_basis,
        noi_by_year=noi_by_year,
        capex_by_year=_unit_series(ordered, lambda r: r.capex_by_year, "capex_by_year"),
        tenant_improvements_by_year=_unit_series(
            ordered, lambda r: r.tenant_improvements_by_year, "tenant_improvements_by_year"
        ),
        leasing_commissions_by_year=_unit_series(
            ordered, lambda r: r.leasing_commissions_by_year, "leasing_commissions_by_year"
        ),
        property_cash_flow_by_year=_unit_series(
            ordered, lambda r: r.property_cash_flow_by_year, "property_cash_flow_by_year"
        ),
        investment_project_capital_by_year=investment_capital,
        investment_owner_expenses_by_year=investment_expenses,
        project_capital_by_year=tuple(
            ensure_finite(f"project_capital_by_year[{y}]", unit_project_capital[y] + investment_capital[y])
            for y in years
        ),
        owner_expenses_by_year=tuple(
            ensure_finite(f"owner_expenses_by_year[{y}]", unit_owner_expenses[y] + investment_expenses[y])
            for y in years
        ),
        unlevered_owner_cash_flow_by_year=unlevered_owner_cash_flow_by_year,
        annual_debt_service=annual_debt_service,
        levered_owner_cash_flow_by_year=levered_owner_cash_flow_by_year,
        remaining_loan_balance=_unit_sum(ordered, lambda r: r.remaining_loan_balance, "remaining_loan_balance"),
        exit_noi=exit_noi,
        exit_value=exit_value,
        disposition_costs=_unit_sum(ordered, lambda r: r.disposition_costs, "disposition_costs"),
        net_sale_proceeds=_unit_sum(ordered, lambda r: r.net_sale_proceeds, "net_sale_proceeds"),
        investment_post_hold_project_capital=investment.post_hold_project_capital,
        post_hold_project_capital=ensure_finite(
            "post_hold_project_capital",
            _unit_sum(ordered, lambda r: r.post_hold_project_capital, "post_hold_project_capital")
            + investment.post_hold_project_capital,
        ),
        implied_exit_cap_rate=(
            None if exit_value == 0.0 else ensure_finite("implied_exit_cap_rate", exit_noi / exit_value)
        ),
        unlevered_cash_flows=unlevered_cash_flows,
        levered_cash_flows=levered_cash_flows,
        unlevered_irr=return_metrics.unlevered_irr,
        unlevered_irr_status=return_metrics.unlevered_irr_status,
        levered_irr=return_metrics.levered_irr,
        levered_irr_status=return_metrics.levered_irr_status,
        total_equity_invested=return_metrics.total_equity_invested,
        total_cash_returned=return_metrics.total_cash_returned,
        total_profit=return_metrics.total_profit,
        equity_multiple=return_metrics.equity_multiple,
        net_additional_equity_requirement_by_year=return_metrics.net_additional_equity_requirement_by_year,
        aggregate_dscr_by_year=return_metrics.dscr_by_year,
        headline_aggregate_dscr=return_metrics.headline_dscr,
        min_aggregate_dscr=return_metrics.min_dscr,
        going_in_cap_rate=ensure_finite("going_in_cap_rate", noi_by_year[0] / allocated_purchase_price),
        year_1_debt_yield=calculate_year_1_debt_yield(year_1_noi=noi_by_year[0], loan_amount=loan_amount),
        levered_cash_on_cash_by_year=calculate_levered_cash_on_cash_by_year(
            recurring_levered_cash_flows=levered_owner_cash_flow_by_year, initial_equity=initial_equity
        ),
        unlevered_cash_yield_by_year=calculate_unlevered_cash_yield_by_year(
            recurring_unlevered_cash_flows=unlevered_owner_cash_flow_by_year,
            unlevered_acquisition_basis=unlevered_project_basis,
        ),
        cumulative_operating_distributions_by_year=calculate_cumulative_operating_distributions_by_year(
            recurring_levered_cash_flows=levered_owner_cash_flow_by_year
        ),
        physical_occupancy_at_year_end=occupancy,
        physical_occupancy_reason=occupancy_reason,
        physical_occupancy_message=occupancy_message,
    )
