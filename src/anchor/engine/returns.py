"""Phase 2D return metrics: DSCR, Equity Multiple, and the frozen IRR solver.

Restates ``docs/financial_conventions.md`` "Return Conventions" and
``docs/phase_2_deterministic_engine.md`` "DSCR" / "Equity Multiple" / "IRR"
exactly; those documents govern on any discrepancy. This module takes
already-assembled cash-flow tuples and already-computed annual debt service
as input; it does not itself compute NOI or debt.

No third-party numerical solver (``numpy``, ``numpy_financial``, ``scipy``,
Excel ``IRR``/``XIRR``, Newton-Raphson, secant method, or any other
general-purpose solver) is used anywhere in this module. The same frozen
bracket-and-bisection IRR procedure is applied identically to the unlevered
and levered cash-flow series.

Owner Return Metrics V3 Gate A2
(``docs/owner_return_metrics_v3_financial_conventions.md``) adds annual
Levered Cash-on-Cash Return, annual Unlevered Cash Yield, Cumulative
Operating Distributions, and Year 1 Debt Yield -- same non-negotiable rule:
pure functions over already-assembled ``noi_by_year``/``capex_by_year``/
``annual_debt_service``/capital-stack values, no NOI or debt calculation of
their own, and no reconstruction of terminal cash flow -- these metrics are
built directly from the same NOI/CapEx/debt-service series the existing
recurring-flow formulas already consume, never by subtracting sale proceeds
back out of ``levered_cash_flows``/``unlevered_cash_flows``.
"""

from __future__ import annotations

from math import isfinite

from .contracts import IrrStatus, OwnerReturnMetrics, ReturnMetrics, ensure_finite


# =============================================================================
# DSCR
# =============================================================================


def calculate_dscr_by_year(
    *, noi_by_year: tuple[float, ...], annual_debt_service: tuple[float, ...]
) -> tuple[float | None, ...]:
    """Return ``DSCR_1 .. DSCR_H``.

    ``DSCR_y = NOI_y / ADS_y`` when ``ADS_y > 0``; ``DSCR_y = None`` when
    ``ADS_y == 0``, regardless of the reason (zero leverage or a hold year
    past full amortization). Zero ``NOI_y`` with positive ``ADS_y`` produces
    ``0.0``, not ``None``.
    """

    dscr_by_year: list[float | None] = []
    for year_index, (noi_y, ads_y) in enumerate(zip(noi_by_year, annual_debt_service)):
        if ads_y > 0.0:
            dscr_y = noi_y / ads_y
            dscr_by_year.append(ensure_finite(f"dscr_by_year[{year_index}]", dscr_y))
        else:
            dscr_by_year.append(None)
    return tuple(dscr_by_year)


def calculate_headline_dscr(*, dscr_by_year: tuple[float | None, ...]) -> float | None:
    """Return ``DSCR_1`` (``dscr_by_year[0]``), the headline DSCR."""

    return dscr_by_year[0]


def calculate_min_dscr(*, dscr_by_year: tuple[float | None, ...]) -> float | None:
    """Underwriting V2 Gate 4: return the minimum of the non-``None``
    entries in ``dscr_by_year``, or ``None`` if every entry is ``None``.
    Supplements ``headline_dscr`` (``DSCR_1``); does not replace it -- the
    two may coincide, e.g. when Year 1 is the covenant-tightest year."""

    defined_values = [dscr for dscr in dscr_by_year if dscr is not None]
    if not defined_values:
        return None
    return min(defined_values)


# =============================================================================
# Equity Multiple
# =============================================================================


def _equity_cash_flow_totals(
    levered_cash_flows: tuple[float, ...],
) -> tuple[float, float]:
    """The Equity Cash Flow split by sign: ``(positive_total, negative_total)``.

    Gate D6.3: the one decomposition behind both the Equity Multiple and the
    project-return summary, so the two can never disagree. ``positive_total``
    sums every cash flow strictly greater than 0 and ``negative_total`` every
    one strictly less than 0; a cash flow of exactly ``0`` -- ``-0.0``
    included -- contributes to neither. These are the Equity Multiple's own
    expressions, moved here unchanged, so no existing figure moves by a bit. A
    side with no cash flows sums to ``0``, as it always has.
    """

    positive_total = sum(cf for cf in levered_cash_flows if cf > 0.0)
    negative_total = sum(cf for cf in levered_cash_flows if cf < 0.0)
    return positive_total, negative_total


def calculate_equity_multiple(*, levered_cash_flows: tuple[float, ...]) -> float | None:
    """Return the Equity Multiple, or ``None`` if the denominator is zero.

    ``positive_total`` sums every levered cash flow strictly greater than 0;
    ``negative_total`` sums every levered cash flow strictly less than 0. A
    cash flow of exactly ``0`` contributes to neither total. Equity Multiple
    is never reported as infinity.

    Gate D6.3: both totals come from ``_equity_cash_flow_totals``, which the
    project-return summary also reads -- ``Total Cash Returned / Total Equity
    Invested`` whenever this multiple is reported.
    """

    positive_total, negative_total = _equity_cash_flow_totals(levered_cash_flows)

    if negative_total == 0.0:
        return None

    equity_multiple = positive_total / abs(negative_total)
    if not isfinite(equity_multiple):
        return None
    return equity_multiple


# =============================================================================
# Project returns -- Phase 6 Gate D6.3
#
# ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 7 and 8. Every
# figure is read off the Equity Cash Flow (``levered_cash_flows``, t = 0..H)
# by sign alone. The cause of a negative period -- closing equity, project
# capital, owner expenses, TI/LC, debt service or an operating loss -- is
# deliberately irrelevant: these are the project's *net* equity economics.
# =============================================================================


def calculate_project_return_totals(
    *, levered_cash_flows: tuple[float, ...]
) -> tuple[float, float, float]:
    """Return ``(total_cash_returned, total_equity_invested, total_profit)``.

    - ``Total Cash Returned`` = the sum of every positive Equity Cash Flow
      period.
    - ``Total Equity Invested`` = the absolute value of the sum of every
      negative period, ``T0`` included.
    - ``Total Profit`` = ``Total Cash Returned - Total Equity Invested``; it
      may be negative.

    A period of exactly ``0`` (``-0.0`` included) counts on neither side, and
    no assumption is made about the sign of ``T0``: the signs decide. Both
    totals come from ``_equity_cash_flow_totals`` -- the Equity Multiple's own
    decomposition -- so whenever the multiple is reported it equals
    ``total_cash_returned / total_equity_invested`` to the bit, and the two can
    never diverge. A side with no periods is ``0.0``.
    """

    positive_total, negative_total = _equity_cash_flow_totals(levered_cash_flows)
    total_cash_returned = ensure_finite("total_cash_returned", float(positive_total))
    total_equity_invested = ensure_finite(
        "total_equity_invested", float(abs(negative_total))
    )
    total_profit = ensure_finite(
        "total_profit", total_cash_returned - total_equity_invested
    )
    return total_cash_returned, total_equity_invested, total_profit


def calculate_net_additional_equity_requirement_by_year(
    *, levered_cash_flows: tuple[float, ...]
) -> tuple[float, ...]:
    """Return ``(NAER_1, .., NAER_H)``: ``NAER_y = max(-ECF_y, 0)`` for every
    hold year -- the deficit of a negative Equity Cash Flow year, and ``0.0``
    for any other year. ``T0`` is excluded (the Initial Equity Requirement is
    ``initial_equity``), so the tuple has length ``H``.

    An **annual net** requirement: a large expenditure and a larger receipt in
    the same year net to zero. It is not a capital call, not a peak intra-year
    funding need and not evidence of when equity must be contributed. Post-hold
    Business Plan capital never appears, because it is not in the Equity Cash
    Flow."""

    return tuple(-cf if cf < 0.0 else 0.0 for cf in levered_cash_flows[1:])


# =============================================================================
# IRR -- frozen custom bracket-and-bisection solver
# =============================================================================


def _first_nonzero_index(cash_flows: tuple[float, ...]) -> int | None:
    for index, cash_flow in enumerate(cash_flows):
        if cash_flow != 0.0:
            return index
    return None


def _irr_validity_failure(cash_flows: tuple[float, ...], t0: int) -> IrrStatus | None:
    """Apply the frozen validity (sign) rules to the nonzero subsequence and
    return the rule the series fails, or ``None`` when it is valid.

    Zero cash flows are ignored for sign-change analysis only; every cash
    flow retains its original annual time index elsewhere. The nonzero
    subsequence must have at least one negative and one positive value, its
    first nonzero entry must be negative, and it must have exactly one sign
    change.

    Gate D6.3: formerly ``_is_valid_irr_series``, returning a bool. The checks,
    their order and the sign loop are unchanged -- only the failing rule is now
    named. The first-nonzero check runs first, exactly as before, so a series
    with no negative cash flow reports ``FIRST_NONZERO_NOT_NEGATIVE``. Once it
    has passed, the loop always sees a negative entry, so a series that still
    fails either has no positive cash flow or changes sign more than once.
    """

    if cash_flows[t0] >= 0.0:
        return IrrStatus.FIRST_NONZERO_NOT_NEGATIVE

    has_negative = False
    has_positive = False
    sign_changes = 0
    previous_sign = 0

    for cash_flow in cash_flows[t0:]:
        if cash_flow == 0.0:
            continue
        sign = 1 if cash_flow > 0.0 else -1
        if sign > 0:
            has_positive = True
        else:
            has_negative = True
        if previous_sign != 0 and sign != previous_sign:
            sign_changes += 1
        previous_sign = sign

    if has_negative and has_positive and sign_changes == 1:
        return None
    if not has_positive:
        return IrrStatus.NO_POSITIVE_CASH_FLOW
    return IrrStatus.MULTIPLE_SIGN_CHANGES


def _evaluate_horner(cash_flows: tuple[float, ...], t0: int, x: float) -> float | None:
    """Evaluate the reduced polynomial ``F(x)`` via the frozen Horner order.

    Returns ``None`` immediately if the initial value or any intermediate or
    final value is non-finite -- a numerical-support failure, never a sign.
    """

    final_index = len(cash_flows) - 1
    horner_value = cash_flows[final_index]
    if not isfinite(horner_value):
        return None

    for t in range(final_index - 1, t0 - 1, -1):
        horner_value = horner_value * x + cash_flows[t]
        if not isfinite(horner_value):
            return None

    return horner_value


def _solve_x_star(
    cash_flows: tuple[float, ...], t0: int
) -> tuple[float | None, IrrStatus]:
    """Run the frozen bracket-expansion and bisection procedure for ``x``.

    Gate D6.3: every exit now also names why it was taken. The procedure --
    every evaluation, comparison, constant, bound and iteration -- is
    unchanged; only each ``return`` carries an ``IrrStatus`` beside the value
    it always returned. A found root is ``DEFINED``; exceeding the ``1e12``
    search bound is ``ROOT_OUTSIDE_SEARCH_DOMAIN``; a non-finite evaluation, or
    the defensive post-loop guard, is ``NUMERICAL_FAILURE``.
    """

    max_abs_cash_flow = max(abs(cf) for cf in cash_flows)

    x_low = 0.0
    x_high = 1.0

    f_low = _evaluate_horner(cash_flows, t0, x_low)
    if f_low is None:
        return None, IrrStatus.NUMERICAL_FAILURE
    f_high = _evaluate_horner(cash_flows, t0, x_high)
    if f_high is None:
        return None, IrrStatus.NUMERICAL_FAILURE

    if f_high == 0.0:
        return x_high, IrrStatus.DEFINED

    while f_high < 0.0:
        if x_high >= 1e12:
            return None, IrrStatus.ROOT_OUTSIDE_SEARCH_DOMAIN
        x_high = min(2 * x_high, 1e12)
        f_high = _evaluate_horner(cash_flows, t0, x_high)
        if f_high is None:
            return None, IrrStatus.NUMERICAL_FAILURE
        if f_high == 0.0:
            return x_high, IrrStatus.DEFINED

    for _ in range(256):
        x_mid = (x_low + x_high) / 2
        f_mid = _evaluate_horner(cash_flows, t0, x_mid)
        if f_mid is None:
            return None, IrrStatus.NUMERICAL_FAILURE

        if f_mid == 0.0:
            return x_mid, IrrStatus.DEFINED
        if abs(f_mid) <= 1e-10 * max_abs_cash_flow:
            return x_mid, IrrStatus.DEFINED
        if (x_high - x_low) <= 1e-12 * max(1.0, abs(x_mid)):
            return x_mid, IrrStatus.DEFINED

        if f_mid < 0.0:
            x_low = x_mid
        else:
            x_high = x_mid

    x_star = (x_low + x_high) / 2
    if isfinite(x_star) and x_star > 0.0:
        return x_star, IrrStatus.DEFINED
    return None, IrrStatus.NUMERICAL_FAILURE


def _convert_x_star_to_irr(x_star: float | None) -> float | None:
    if x_star is None or x_star <= 0.0 or not isfinite(x_star):
        return None

    irr = 1.0 / x_star - 1.0
    if not isfinite(irr) or irr <= -1.0:
        return None
    return irr


def evaluate_irr(cash_flows: tuple[float, ...]) -> tuple[float | None, IrrStatus]:
    """Run the frozen IRR procedure and return ``(irr, status)``: the IRR, or
    ``None``, and the ``IrrStatus`` that explains it (Gate D6.3).

    **This is the IRR procedure, not a classifier beside it.** ``calculate_irr``
    returns this function's first element and nothing else, so the status can
    never describe a different computation from the one that produced the
    value. The steps, in order:

    1. no nonzero cash flow -> ``NO_NONZERO_CASH_FLOW``;
    2. the frozen sign rules (``_irr_validity_failure``) -> the rule failed;
    3. the bracket-and-bisection solver (``_solve_x_star``) -> its exit;
    4. conversion of the root back to a rate; the defensive guard there reports
       ``NUMERICAL_FAILURE``.

    A value is returned only with ``DEFINED``; every other status comes with
    ``None``.
    """

    t0 = _first_nonzero_index(cash_flows)
    if t0 is None:
        return None, IrrStatus.NO_NONZERO_CASH_FLOW
    validity_failure = _irr_validity_failure(cash_flows, t0)
    if validity_failure is not None:
        return None, validity_failure

    x_star, solver_status = _solve_x_star(cash_flows, t0)
    if x_star is None:
        return None, solver_status
    irr = _convert_x_star_to_irr(x_star)
    if irr is None:
        return None, IrrStatus.NUMERICAL_FAILURE
    return irr, IrrStatus.DEFINED


def calculate_irr(cash_flows: tuple[float, ...]) -> float | None:
    """Return the annual periodic IRR for ``cash_flows``, or ``None``.

    Applies the exact frozen transformation, Horner-evaluated reduced
    polynomial, bracket-expansion, and 256-iteration bisection procedure
    specified in ``docs/financial_conventions.md`` "IRR numerical solution"
    and ``docs/phase_2_deterministic_engine.md`` "IRR". The identical
    procedure is used for both unlevered and levered cash-flow series -- no
    separate mathematical implementation exists for either.

    Gate D6.3: the procedure now lives in ``evaluate_irr``, which also reports
    why an IRR is unavailable. This function returns exactly its value -- the
    same float, or ``None``, for every series as before.
    """

    irr, _ = evaluate_irr(cash_flows)
    return irr


# =============================================================================
# Orchestration
# =============================================================================


def calculate_return_metrics(
    *,
    noi_by_year: tuple[float, ...],
    annual_debt_service: tuple[float, ...],
    unlevered_cash_flows: tuple[float, ...],
    levered_cash_flows: tuple[float, ...],
) -> ReturnMetrics:
    """Compute the Phase 2D return metrics from already-assembled Phase 2A/
    2B/2C outputs.

    Gate D6.3: each IRR comes from ``evaluate_irr`` together with its
    ``IrrStatus`` (the value is exactly ``calculate_irr``'s), and the
    project-return summary is read off ``levered_cash_flows`` -- the Equity
    Cash Flow -- once, here. This is the one authority for all of them;
    ``AcquisitionResults`` threads them unchanged."""

    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=noi_by_year, annual_debt_service=annual_debt_service
    )
    headline_dscr = calculate_headline_dscr(dscr_by_year=dscr_by_year)
    min_dscr = calculate_min_dscr(dscr_by_year=dscr_by_year)
    equity_multiple = calculate_equity_multiple(levered_cash_flows=levered_cash_flows)
    unlevered_irr, unlevered_irr_status = evaluate_irr(unlevered_cash_flows)
    levered_irr, levered_irr_status = evaluate_irr(levered_cash_flows)
    total_cash_returned, total_equity_invested, total_profit = (
        calculate_project_return_totals(levered_cash_flows=levered_cash_flows)
    )
    net_additional_equity_requirement_by_year = (
        calculate_net_additional_equity_requirement_by_year(
            levered_cash_flows=levered_cash_flows
        )
    )

    return ReturnMetrics(
        dscr_by_year=dscr_by_year,
        headline_dscr=headline_dscr,
        min_dscr=min_dscr,
        equity_multiple=equity_multiple,
        unlevered_irr=unlevered_irr,
        levered_irr=levered_irr,
        net_additional_equity_requirement_by_year=(
            net_additional_equity_requirement_by_year
        ),
        total_equity_invested=total_equity_invested,
        total_cash_returned=total_cash_returned,
        total_profit=total_profit,
        unlevered_irr_status=unlevered_irr_status,
        levered_irr_status=levered_irr_status,
    )


# =============================================================================
# Owner Return Metrics V3 Gate A2
# =============================================================================


def calculate_recurring_levered_cash_flows(
    *,
    noi_by_year: tuple[float, ...],
    capex_by_year: tuple[float, ...],
    annual_debt_service: tuple[float, ...],
    operating_capital_by_year: tuple[float, ...] = (),
) -> tuple[float, ...]:
    """Return ``(RLCF_1, .., RLCF_H)``: ``RLCF_y = NOI_y - CapEx_y -
    OpCap_y - ADS_y`` for every hold year, including the final one.

    Unlike ``calculate_levered_cash_flows`` (``acquisition.py``), this
    series never adds ``net_sale_proceeds`` to its final entry -- there is
    no terminal-year special case here at all, by construction. Never
    floored at zero; CapEx, operating capital or debt service exceeding NOI
    in a year produces a negative entry, reported as-is.

    D4.5A (HD-D4-3): operating capital joins CapEx here because this series
    answers "what did the owner actually receive this year", and a below-NOI
    capital cheque is money that left the account. Omitting it would report a
    cash-on-cash return the property did not earn. ``operating_capital_by_year``
    is the completed per-year total from
    ``acquisition.calculate_operating_capital_by_year``; empty or all-zero
    reduces this to exactly the prior formula.
    """

    hold_period = len(noi_by_year)
    operating_capital = operating_capital_by_year or tuple(
        0.0 for _ in range(hold_period)
    )

    return tuple(
        ensure_finite(
            f"recurring_levered_cash_flows[{year}]",
            noi_by_year[year]
            - capex_by_year[year]
            - operating_capital[year]
            - annual_debt_service[year],
        )
        for year in range(hold_period)
    )


def calculate_recurring_unlevered_cash_flows(
    *,
    noi_by_year: tuple[float, ...],
    capex_by_year: tuple[float, ...],
    operating_capital_by_year: tuple[float, ...] = (),
) -> tuple[float, ...]:
    """Return ``(RUCF_1, .., RUCF_H)``: ``RUCF_y = NOI_y - CapEx_y -
    OpCap_y`` for every hold year, including the final one -- no
    ``exit_value`` or ``disposition_costs`` term, ever. Never floored at zero.

    D4.5A (HD-D4-3): the same reasoning as the levered series above. Empty or
    all-zero ``operating_capital_by_year`` reduces this to exactly the prior
    formula.
    """

    hold_period = len(noi_by_year)
    operating_capital = operating_capital_by_year or tuple(
        0.0 for _ in range(hold_period)
    )

    return tuple(
        ensure_finite(
            f"recurring_unlevered_cash_flows[{year}]",
            noi_by_year[year] - capex_by_year[year] - operating_capital[year],
        )
        for year in range(hold_period)
    )


def calculate_unlevered_acquisition_basis(
    *, purchase_price: float, acquisition_costs: float
) -> float:
    """``Total Unlevered Acquisition Basis = Purchase Price + Acquisition
    Costs``. ``financing_fee`` is deliberately excluded: it is purely
    debt-related (``= loan_amount * financing_fee_pct``, always ``0`` when
    ``loan_amount`` is ``0``), and this is an unlevered basis."""

    return ensure_finite(
        "unlevered_acquisition_basis", purchase_price + acquisition_costs
    )


def calculate_levered_cash_on_cash_by_year(
    *, recurring_levered_cash_flows: tuple[float, ...], initial_equity: float
) -> tuple[float | None, ...]:
    """Return ``(CoC_1, .., CoC_H)``: ``CoC_y = RLCF_y / Initial Equity``.

    ``Initial Equity`` is fixed across the hold (computed once, never
    recomputed per year). When it is exactly ``0.0``, every year is
    ``None`` -- undefined, the same zero-denominator convention
    ``calculate_equity_multiple`` above already uses (``None``, never
    ``inf``). A negative ``RLCF_y`` produces a negative ``CoC_y``; never
    floored at zero.
    """

    if initial_equity == 0.0:
        return tuple(None for _ in recurring_levered_cash_flows)

    return tuple(
        ensure_finite(
            f"levered_cash_on_cash_by_year[{year}]", cash_flow / initial_equity
        )
        for year, cash_flow in enumerate(recurring_levered_cash_flows)
    )


def calculate_unlevered_cash_yield_by_year(
    *,
    recurring_unlevered_cash_flows: tuple[float, ...],
    unlevered_acquisition_basis: float,
) -> tuple[float | None, ...]:
    """Return ``(Yield_1, .., Yield_H)``: ``Yield_y = RUCF_y /
    Total Unlevered Acquisition Basis``, fixed across the hold. ``None``
    for every year when the basis is exactly ``0.0``; never floored at
    zero for a negative ``RUCF_y``."""

    if unlevered_acquisition_basis == 0.0:
        return tuple(None for _ in recurring_unlevered_cash_flows)

    return tuple(
        ensure_finite(
            f"unlevered_cash_yield_by_year[{year}]",
            cash_flow / unlevered_acquisition_basis,
        )
        for year, cash_flow in enumerate(recurring_unlevered_cash_flows)
    )


def calculate_cumulative_operating_distributions_by_year(
    *, recurring_levered_cash_flows: tuple[float, ...]
) -> tuple[float, ...]:
    """Return the running sum of ``recurring_levered_cash_flows`` through
    each year: ``Cum_y = RLCF_1 + .. + RLCF_y``. A negative ``RLCF_y``
    reduces the running total -- never floored at zero, and sale/refinance
    proceeds are never added at any year, including the last."""

    cumulative_by_year: list[float] = []
    running_total = 0.0
    for year, cash_flow in enumerate(recurring_levered_cash_flows):
        running_total += cash_flow
        cumulative_by_year.append(
            ensure_finite(
                f"cumulative_operating_distributions_by_year[{year}]",
                running_total,
            )
        )
    return tuple(cumulative_by_year)


def calculate_year_1_debt_yield(
    *, year_1_noi: float, loan_amount: float
) -> float | None:
    """``Year 1 Debt Yield = Year 1 NOI / Original Loan Amount``. ``None``
    when ``loan_amount`` is exactly ``0.0`` (all-cash). No annual schedule
    is computed here -- the current ``DebtSchedule`` contract exposes only
    the original and final loan balance, never a per-year balance, so an
    annual Debt Yield schedule is deferred rather than approximated."""

    if loan_amount == 0.0:
        return None

    return ensure_finite("year_1_debt_yield", year_1_noi / loan_amount)


def calculate_owner_return_metrics(
    *,
    noi_by_year: tuple[float, ...],
    capex_by_year: tuple[float, ...],
    annual_debt_service: tuple[float, ...],
    purchase_price: float,
    acquisition_costs: float,
    initial_equity: float,
    loan_amount: float,
    operating_capital_by_year: tuple[float, ...] = (),
) -> OwnerReturnMetrics:
    """Compute the Owner Return Metrics V3 Gate A2 result from
    already-assembled capital-stack and cash-flow inputs -- identical for
    Quick, Detailed and any later mode, since every parameter here is already
    mode-agnostic (``AcquisitionTerms``/``CapitalStack``/``DebtSchedule``
    fields, plus the shared ``noi_by_year``/``capex_by_year`` and, from D4.5A,
    ``operating_capital_by_year``).

    ``year_1_debt_yield`` is deliberately **not** affected by operating
    capital: it is ``NOI_1 / loan_amount``, a lender metric, and NOI is never
    reduced by a below-NOI outflow (D4 Section 22)."""

    recurring_levered_cash_flows = calculate_recurring_levered_cash_flows(
        noi_by_year=noi_by_year,
        capex_by_year=capex_by_year,
        annual_debt_service=annual_debt_service,
        operating_capital_by_year=operating_capital_by_year,
    )
    recurring_unlevered_cash_flows = calculate_recurring_unlevered_cash_flows(
        noi_by_year=noi_by_year,
        capex_by_year=capex_by_year,
        operating_capital_by_year=operating_capital_by_year,
    )
    unlevered_acquisition_basis = calculate_unlevered_acquisition_basis(
        purchase_price=purchase_price, acquisition_costs=acquisition_costs
    )

    levered_cash_on_cash_by_year = calculate_levered_cash_on_cash_by_year(
        recurring_levered_cash_flows=recurring_levered_cash_flows,
        initial_equity=initial_equity,
    )
    unlevered_cash_yield_by_year = calculate_unlevered_cash_yield_by_year(
        recurring_unlevered_cash_flows=recurring_unlevered_cash_flows,
        unlevered_acquisition_basis=unlevered_acquisition_basis,
    )
    cumulative_operating_distributions_by_year = (
        calculate_cumulative_operating_distributions_by_year(
            recurring_levered_cash_flows=recurring_levered_cash_flows
        )
    )
    year_1_debt_yield = calculate_year_1_debt_yield(
        year_1_noi=noi_by_year[0], loan_amount=loan_amount
    )

    return OwnerReturnMetrics(
        levered_cash_on_cash_by_year=levered_cash_on_cash_by_year,
        unlevered_cash_yield_by_year=unlevered_cash_yield_by_year,
        cumulative_operating_distributions_by_year=(
            cumulative_operating_distributions_by_year
        ),
        year_1_debt_yield=year_1_debt_yield,
    )
