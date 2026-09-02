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
"""

from __future__ import annotations

from math import isfinite

from .contracts import ReturnMetrics, ensure_finite


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


def calculate_equity_multiple(*, levered_cash_flows: tuple[float, ...]) -> float | None:
    """Return the Equity Multiple, or ``None`` if the denominator is zero.

    ``positive_total`` sums every levered cash flow strictly greater than 0;
    ``negative_total`` sums every levered cash flow strictly less than 0. A
    cash flow of exactly ``0`` contributes to neither total. Equity Multiple
    is never reported as infinity.
    """

    positive_total = sum(cf for cf in levered_cash_flows if cf > 0.0)
    negative_total = sum(cf for cf in levered_cash_flows if cf < 0.0)

    if negative_total == 0.0:
        return None

    equity_multiple = positive_total / abs(negative_total)
    if not isfinite(equity_multiple):
        return None
    return equity_multiple


# =============================================================================
# IRR -- frozen custom bracket-and-bisection solver
# =============================================================================


def _first_nonzero_index(cash_flows: tuple[float, ...]) -> int | None:
    for index, cash_flow in enumerate(cash_flows):
        if cash_flow != 0.0:
            return index
    return None


def _is_valid_irr_series(cash_flows: tuple[float, ...], t0: int) -> bool:
    """Apply the frozen validity (sign) rules to the nonzero subsequence.

    Zero cash flows are ignored for sign-change analysis only; every cash
    flow retains its original annual time index elsewhere. The nonzero
    subsequence must have at least one negative and one positive value, its
    first nonzero entry must be negative, and it must have exactly one sign
    change.
    """

    if cash_flows[t0] >= 0.0:
        return False

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

    return has_negative and has_positive and sign_changes == 1


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


def _solve_x_star(cash_flows: tuple[float, ...], t0: int) -> float | None:
    """Run the frozen bracket-expansion and bisection procedure for ``x``."""

    max_abs_cash_flow = max(abs(cf) for cf in cash_flows)

    x_low = 0.0
    x_high = 1.0

    f_low = _evaluate_horner(cash_flows, t0, x_low)
    if f_low is None:
        return None
    f_high = _evaluate_horner(cash_flows, t0, x_high)
    if f_high is None:
        return None

    if f_high == 0.0:
        return x_high

    while f_high < 0.0:
        if x_high >= 1e12:
            return None
        x_high = min(2 * x_high, 1e12)
        f_high = _evaluate_horner(cash_flows, t0, x_high)
        if f_high is None:
            return None
        if f_high == 0.0:
            return x_high

    for _ in range(256):
        x_mid = (x_low + x_high) / 2
        f_mid = _evaluate_horner(cash_flows, t0, x_mid)
        if f_mid is None:
            return None

        if f_mid == 0.0:
            return x_mid
        if abs(f_mid) <= 1e-10 * max_abs_cash_flow:
            return x_mid
        if (x_high - x_low) <= 1e-12 * max(1.0, abs(x_mid)):
            return x_mid

        if f_mid < 0.0:
            x_low = x_mid
        else:
            x_high = x_mid

    x_star = (x_low + x_high) / 2
    if isfinite(x_star) and x_star > 0.0:
        return x_star
    return None


def _convert_x_star_to_irr(x_star: float | None) -> float | None:
    if x_star is None or x_star <= 0.0 or not isfinite(x_star):
        return None

    irr = 1.0 / x_star - 1.0
    if not isfinite(irr) or irr <= -1.0:
        return None
    return irr


def calculate_irr(cash_flows: tuple[float, ...]) -> float | None:
    """Return the annual periodic IRR for ``cash_flows``, or ``None``.

    Applies the exact frozen transformation, Horner-evaluated reduced
    polynomial, bracket-expansion, and 256-iteration bisection procedure
    specified in ``docs/financial_conventions.md`` "IRR numerical solution"
    and ``docs/phase_2_deterministic_engine.md`` "IRR". The identical
    procedure is used for both unlevered and levered cash-flow series -- no
    separate mathematical implementation exists for either.
    """

    t0 = _first_nonzero_index(cash_flows)
    if t0 is None or not _is_valid_irr_series(cash_flows, t0):
        return None

    x_star = _solve_x_star(cash_flows, t0)
    return _convert_x_star_to_irr(x_star)


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
    2B/2C outputs."""

    dscr_by_year = calculate_dscr_by_year(
        noi_by_year=noi_by_year, annual_debt_service=annual_debt_service
    )
    headline_dscr = calculate_headline_dscr(dscr_by_year=dscr_by_year)
    min_dscr = calculate_min_dscr(dscr_by_year=dscr_by_year)
    equity_multiple = calculate_equity_multiple(levered_cash_flows=levered_cash_flows)
    unlevered_irr = calculate_irr(unlevered_cash_flows)
    levered_irr = calculate_irr(levered_cash_flows)

    return ReturnMetrics(
        dscr_by_year=dscr_by_year,
        headline_dscr=headline_dscr,
        min_dscr=min_dscr,
        equity_multiple=equity_multiple,
        unlevered_irr=unlevered_irr,
        levered_irr=levered_irr,
    )
