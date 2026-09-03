"""Phase 9A / Detailed Operating Model V2.1 Gate 9 deterministic
presentation layer for the AI Analyst prompt.

This module performs no financial calculation. It only reformats values
already produced by the frozen Phase 2/7/8 engine and analysis layers (and,
for Detailed Underwrite, the Detailed Operating Model V2.1 Gate 2/8 engine
and analysis layers) into human-readable strings ($/K/M currency,
percentages, "x" multiples), and labels a metric's relationship to an
already-supplied hurdle target using the same ``>=``-style comparison
``analysis/break_even.py`` itself already uses to decide a qualifying value
(see ``_meets_hurdle`` there). No number here is derived, estimated, or
algebraically combined with another -- every formatted value is read
unchanged from one field of ``AnalysisContext``, and every hurdle label is
a plain three-way comparison (above/at/below) between two already-trusted
numbers.

``build_presentation_payload`` is the only entry point ``anchor.ai.
prompts`` needs: it turns one ``AnalysisContext`` into a fully
JSON-serializable, presentation-formatted evidence payload for the model
-facing user prompt, branching only on ``context.operating_mode`` to decide
*which* already-computed fields to include (Quick's ``base_inputs`` vs.
Detailed's ``base_terms``/``base_detailed_operating_inputs``/
``operating_projection``) -- never introducing a new calculation for either
mode. The raw ``AnalysisContext`` (and therefore every raw decimal) remains
available unchanged wherever else it is needed -- this module only changes
what the model is shown, never what Anchor stores or computes.
"""

from __future__ import annotations

from typing import Any

from ..analysis.contracts import BreakEvenResult, BreakEvenStatus, TwoWaySensitivityResult
from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
)
from ..engine.contracts import AcquisitionResults, OperatingProjection
from .contracts import AnalysisContext

# =============================================================================
# Field -> presentation-kind classification
# =============================================================================

_PERCENT_FIELDS: frozenset[str] = frozenset(
    {
        "occupancy",
        "noi_growth",
        "exit_cap_rate",
        "ltv",
        "interest_rate",
        "going_in_cap_rate",
        "levered_irr",
        "unlevered_irr",
        # Underwriting V2 Gate 7: acquisition_cost_pct is a percentage of
        # purchase price, financing_fee_pct of loan amount, and
        # disposition_cost_pct of gross exit value.
        "acquisition_cost_pct",
        "financing_fee_pct",
        "disposition_cost_pct",
        # Detailed Operating Model V2.1 Gate 9: vacancy_credit_loss_pct is a
        # percentage of Gross Potential Rent; management_fee_pct is a
        # percentage of Effective Gross Income; revenue_growth/
        # expense_growth are the Detailed model's two independent annual
        # growth rates (never a single blended noi_growth in this path).
        "vacancy_credit_loss_pct",
        "management_fee_pct",
        "revenue_growth",
        "expense_growth",
    }
)
_MULTIPLE_FIELDS: frozenset[str] = frozenset(
    {
        "equity_multiple",
        "headline_dscr",
        # Underwriting V2 Gate 7: the minimum DSCR during the hold --
        # independently represented from headline_dscr (Year 1 DSCR).
        "min_dscr",
    }
)
_CURRENCY_FIELDS: frozenset[str] = frozenset(
    {
        "purchase_price",
        "current_noi",
        "loan_amount",
        "initial_equity",
        "monthly_debt_service",
        "annual_debt_service",
        "remaining_loan_balance",
        "noi_by_year",
        "exit_noi",
        "exit_value",
        "net_sale_proceeds",
        "unlevered_cash_flows",
        "levered_cash_flows",
        # Underwriting V2 Gate 7 dollar results/reserve, all already
        # computed by the deterministic engine -- never derived here.
        "acquisition_costs",
        "financing_fee",
        "disposition_costs",
        "capex_by_year",
        "annual_capex_reserve",
        # Detailed Operating Model V2.1 Gate 9: AcquisitionTerms carries no
        # new currency field beyond the ones already listed above (it is a
        # strict subset of AcquisitionInputs' field names). DetailedOperatingInputs'
        # dollar assumptions:
        "gross_potential_rent",
        "other_income",
        "property_taxes",
        "insurance",
        "utilities",
        "repairs_maintenance",
        "other_operating_expenses",
        # OperatingProjection's dollar schedules -- each already computed
        # by build_detailed_operating_projection, never re-derived here:
        "gross_potential_rent_by_year",
        "other_income_by_year",
        "vacancy_credit_loss_by_year",
        "effective_gross_income_by_year",
        "property_taxes_by_year",
        "insurance_by_year",
        "utilities_by_year",
        "repairs_maintenance_by_year",
        "other_operating_expenses_by_year",
        "management_fee_by_year",
        "total_operating_expenses_by_year",
    }
)
_YEAR_FIELDS: frozenset[str] = frozenset(
    {
        "hold_period",
        "amortization",
        # Underwriting V2 Gate 7: whole years of interest-only debt before
        # scheduled principal amortization begins.
        "io_period",
    }
)

# =============================================================================
# Deliberate-omission allowlist (Gate 8 architecture guardrail, extended by
# Detailed Operating Model V2.1 Gate 9 for the three new Detailed contracts)
#
# A future field on any of these five dataclasses that is *not* supposed to
# reach the AI Analyst belongs in the matching allowlist, named and reasoned
# about explicitly. The corresponding reflection test fails loudly if any
# field is missing from both its formatter function and its allowlist -- so
# a field can only ever go unseen by the model on purpose, never by
# accident. Empty today: every current field of all five dataclasses is
# presented.
# =============================================================================

INTENTIONALLY_EXCLUDED_INPUT_FIELDS: frozenset[str] = frozenset()
INTENTIONALLY_EXCLUDED_RESULT_FIELDS: frozenset[str] = frozenset()
INTENTIONALLY_EXCLUDED_TERMS_FIELDS: frozenset[str] = frozenset()
INTENTIONALLY_EXCLUDED_DETAILED_OPERATING_FIELDS: frozenset[str] = frozenset()
INTENTIONALLY_EXCLUDED_OPERATING_PROJECTION_FIELDS: frozenset[str] = frozenset()

# A hurdle-relevant metric maps to the ``AnalysisContext`` attribute holding
# its user-supplied hurdle target. Only these three metrics have a hurdle in
# the frozen Phase 9A spec.
_METRIC_TO_TARGET_ATTR: dict[str, str] = {
    "levered_irr": "target_levered_irr",
    "equity_multiple": "target_equity_multiple",
    "headline_dscr": "target_headline_dscr",
}


class UnknownPresentationFieldError(ValueError):
    """Raised for a field/metric identifier with no known presentation
    formatting rule -- signals a presentation-layer gap, never silently
    formatted with a guessed convention."""

    def __init__(self, field_name: object) -> None:
        self.field_name = field_name
        super().__init__(f"No presentation formatting rule for field {field_name!r}.")


# =============================================================================
# Primitive formatters
# =============================================================================


def format_currency(value: float) -> str:
    """Format a dollar amount as ``$X.XM``/``$X.XK``/``$X,XXX`` -- sensible
    $, commas, and M/K presentation, never a raw float."""

    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{sign}${magnitude / 1_000_000:,.1f}M"
    if magnitude >= 1_000:
        return f"{sign}${magnitude / 1_000:,.1f}K"
    return f"{sign}${magnitude:,.0f}"


def format_percent(value: float, *, max_decimals: int = 2) -> str:
    """Format a decimal fraction (0.055 -> "5.50%") at up to
    ``max_decimals`` decimal places, trimming trailing zeros so a round
    value like 0.6 reads "60%" rather than "60.00%"."""

    formatted = f"{value * 100:.{max_decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return f"{formatted}%"


def format_multiple(value: float, *, decimals: int = 2) -> str:
    """Format an equity-multiple/DSCR value as ``X.XXx``."""

    return f"{value:.{decimals}f}x"


def format_metric_value(field_name: str, value: float | int | None) -> str:
    """Format one raw value per the presentation convention for
    ``field_name`` (an ``AcquisitionInputs``/``AcquisitionResults``/
    ``AcquisitionTerms``/``DetailedOperatingInputs``/``OperatingProjection``
    field name, or a sensitivity/break-even assumption or metric name).

    Returns ``"N/A"`` for a legitimately absent metric (e.g. ``headline_dscr``
    under zero leverage) rather than fabricating a value.
    """

    if value is None:
        return "N/A"
    if field_name in _YEAR_FIELDS:
        return f"{int(value)} years"
    if field_name in _PERCENT_FIELDS:
        return format_percent(value)
    if field_name in _MULTIPLE_FIELDS:
        return format_multiple(value)
    if field_name in _CURRENCY_FIELDS:
        return format_currency(value)
    raise UnknownPresentationFieldError(field_name)


_DISAMBIGUATION_MAX_DECIMALS = 6


def _format_with_decimals(metric: str, value: float, decimals: int) -> str:
    """Reformat ``value`` for ``metric`` at an explicit decimal precision
    (percent/multiple fields only -- the two presentation kinds that ever
    round a value flush with its hurdle target)."""

    if metric in _PERCENT_FIELDS:
        return format_percent(value, max_decimals=decimals)
    return format_multiple(value, decimals=decimals)


def _disambiguate_from_target(
    metric: str, value: float, target: float, formatted_value: str
) -> str:
    """If default rounding made ``value`` read identical to ``target`` even
    though the underlying deterministic values are not equal, step
    displayed precision up just enough to preserve the already-decided
    above/below distinction. Currency/year fields (never hurdle-relevant
    in the frozen Phase 9A spec) and any case where the default formatting
    is already unambiguous pass through untouched.

    At each precision step both ``value`` and ``target`` are reformatted
    together (not compared against the fixed base-precision target label)
    so a case like 1.2004 vs a 1.20 target -- which still reads "1.200x"
    vs "1.200x" at three decimals -- keeps climbing until the two actually
    look different (four decimals: "1.2004x" vs "1.2000x"). Only the
    ``value`` side of that winning precision is returned; the target label
    itself is always shown at its normal, un-stepped precision.
    """

    if metric not in _PERCENT_FIELDS and metric not in _MULTIPLE_FIELDS:
        return formatted_value

    decimals = 2
    candidate = formatted_value
    while decimals < _DISAMBIGUATION_MAX_DECIMALS:
        target_at_precision = _format_with_decimals(metric, target, decimals)
        candidate = _format_with_decimals(metric, value, decimals)
        if candidate != target_at_precision:
            break
        decimals += 1
    return candidate


def format_hurdle_relationship(metric: str, value: float | None, target: float) -> str:
    """Return e.g. ``"1.22x -- above 1.20x target"`` (em dash), using the
    plain ``>`` / ``<`` / ``==`` relationship between two already-trusted
    numbers -- never a magnitude the model would have to derive itself.

    When normal rounding would display ``value`` as equal to ``target``
    despite the underlying deterministic values actually differing (e.g.
    raw DSCR 1.1977... vs a 1.20x target), displayed precision for
    ``value`` is stepped up just enough to keep the label visually
    consistent with the already-decided relation -- e.g. ``"1.198x --
    below 1.20x target"`` instead of the contradictory ``"1.20x -- below
    1.20x target"``. The comparison and relation themselves are unchanged;
    only the string shown for ``value`` gains precision.

    Returns a clear "not defined" statement (never a fabricated relation)
    when ``value`` is ``None``.
    """

    if value is None:
        return "N/A (metric not defined for this scenario)"

    formatted_value = format_metric_value(metric, value)
    formatted_target = format_metric_value(metric, target)
    if value > target:
        relation = "above"
    elif value < target:
        relation = "below"
    else:
        relation = "at"

    if relation != "at":
        formatted_value = _disambiguate_from_target(metric, value, target, formatted_value)

    return f"{formatted_value} — {relation} {formatted_target} target"


def _resolve_target_for_metric(context: AnalysisContext, metric: str) -> float | None:
    target_attr = _METRIC_TO_TARGET_ATTR.get(metric)
    if target_attr is None:
        return None
    return getattr(context, target_attr)


# =============================================================================
# Section builders
# =============================================================================


def _format_tuple(field_name: str, values: tuple[float | None, ...]) -> tuple[str, ...]:
    return tuple(format_metric_value(field_name, value) for value in values)


def _format_inputs(inputs: AcquisitionInputs) -> dict[str, Any]:
    return {
        "purchase_price": format_metric_value("purchase_price", inputs.purchase_price),
        "current_noi": format_metric_value("current_noi", inputs.current_noi),
        "occupancy": format_metric_value("occupancy", inputs.occupancy),
        "noi_growth": format_metric_value("noi_growth", inputs.noi_growth),
        "hold_period": format_metric_value("hold_period", inputs.hold_period),
        "exit_cap_rate": format_metric_value("exit_cap_rate", inputs.exit_cap_rate),
        "ltv": format_metric_value("ltv", inputs.ltv),
        "interest_rate": format_metric_value("interest_rate", inputs.interest_rate),
        "amortization": format_metric_value("amortization", inputs.amortization),
        # Underwriting V2 Gate 7 -- see SYSTEM_PROMPT for the semantic
        # definition of each (percentage base, reserve treatment, timing).
        "acquisition_cost_pct": format_metric_value(
            "acquisition_cost_pct", inputs.acquisition_cost_pct
        ),
        "financing_fee_pct": format_metric_value(
            "financing_fee_pct", inputs.financing_fee_pct
        ),
        "disposition_cost_pct": format_metric_value(
            "disposition_cost_pct", inputs.disposition_cost_pct
        ),
        "annual_capex_reserve": format_metric_value(
            "annual_capex_reserve", inputs.annual_capex_reserve
        ),
        "io_period": format_metric_value("io_period", inputs.io_period),
    }


def _format_terms(terms: AcquisitionTerms) -> dict[str, Any]:
    """Detailed Operating Model V2.1 Gate 9: the 11 acquisition/debt/exit
    assumptions shared by both modes -- the Detailed counterpart of the
    Quick-only fields ``_format_inputs`` presents. No ``current_noi``/
    ``occupancy``/``noi_growth`` entry exists here -- ``AcquisitionTerms``
    has no such field."""

    return {
        "purchase_price": format_metric_value("purchase_price", terms.purchase_price),
        "hold_period": format_metric_value("hold_period", terms.hold_period),
        "exit_cap_rate": format_metric_value("exit_cap_rate", terms.exit_cap_rate),
        "ltv": format_metric_value("ltv", terms.ltv),
        "interest_rate": format_metric_value("interest_rate", terms.interest_rate),
        "amortization": format_metric_value("amortization", terms.amortization),
        "acquisition_cost_pct": format_metric_value(
            "acquisition_cost_pct", terms.acquisition_cost_pct
        ),
        "financing_fee_pct": format_metric_value(
            "financing_fee_pct", terms.financing_fee_pct
        ),
        "disposition_cost_pct": format_metric_value(
            "disposition_cost_pct", terms.disposition_cost_pct
        ),
        "annual_capex_reserve": format_metric_value(
            "annual_capex_reserve", terms.annual_capex_reserve
        ),
        "io_period": format_metric_value("io_period", terms.io_period),
    }


def _format_detailed_operating_inputs(
    detailed_operating_inputs: DetailedOperatingInputs,
) -> dict[str, Any]:
    """Detailed Operating Model V2.1 Gate 9: the 11 Year-1 revenue/expense/
    growth assumptions that produce the Detailed operating projection --
    presented as underwriting assumptions, exactly as supplied, never as
    market evidence (see SYSTEM_PROMPT's data-gap discipline rule)."""

    return {
        "gross_potential_rent": format_metric_value(
            "gross_potential_rent", detailed_operating_inputs.gross_potential_rent
        ),
        "other_income": format_metric_value(
            "other_income", detailed_operating_inputs.other_income
        ),
        "vacancy_credit_loss_pct": format_metric_value(
            "vacancy_credit_loss_pct", detailed_operating_inputs.vacancy_credit_loss_pct
        ),
        "property_taxes": format_metric_value(
            "property_taxes", detailed_operating_inputs.property_taxes
        ),
        "insurance": format_metric_value("insurance", detailed_operating_inputs.insurance),
        "utilities": format_metric_value("utilities", detailed_operating_inputs.utilities),
        "repairs_maintenance": format_metric_value(
            "repairs_maintenance", detailed_operating_inputs.repairs_maintenance
        ),
        "other_operating_expenses": format_metric_value(
            "other_operating_expenses", detailed_operating_inputs.other_operating_expenses
        ),
        "management_fee_pct": format_metric_value(
            "management_fee_pct", detailed_operating_inputs.management_fee_pct
        ),
        "revenue_growth": format_metric_value(
            "revenue_growth", detailed_operating_inputs.revenue_growth
        ),
        "expense_growth": format_metric_value(
            "expense_growth", detailed_operating_inputs.expense_growth
        ),
    }


def _format_operating_projection(operating_projection: OperatingProjection) -> dict[str, Any]:
    """Detailed Operating Model V2.1 Gate 9: the full deterministic
    Detailed operating schedule -- every value already computed by
    ``build_detailed_operating_projection``, never re-derived here. NOI
    (``noi_by_year``/``exit_noi``) is presented from this authoritative
    schedule, not assumed, distinguishing it from Quick's directly-supplied
    ``current_noi``/``noi_growth`` (see SYSTEM_PROMPT's NOI-terminology
    rule)."""

    return {
        "gross_potential_rent_by_year": _format_tuple(
            "gross_potential_rent_by_year", operating_projection.gross_potential_rent_by_year
        ),
        "other_income_by_year": _format_tuple(
            "other_income_by_year", operating_projection.other_income_by_year
        ),
        "vacancy_credit_loss_by_year": _format_tuple(
            "vacancy_credit_loss_by_year", operating_projection.vacancy_credit_loss_by_year
        ),
        "effective_gross_income_by_year": _format_tuple(
            "effective_gross_income_by_year",
            operating_projection.effective_gross_income_by_year,
        ),
        "property_taxes_by_year": _format_tuple(
            "property_taxes_by_year", operating_projection.property_taxes_by_year
        ),
        "insurance_by_year": _format_tuple(
            "insurance_by_year", operating_projection.insurance_by_year
        ),
        "utilities_by_year": _format_tuple(
            "utilities_by_year", operating_projection.utilities_by_year
        ),
        "repairs_maintenance_by_year": _format_tuple(
            "repairs_maintenance_by_year", operating_projection.repairs_maintenance_by_year
        ),
        "other_operating_expenses_by_year": _format_tuple(
            "other_operating_expenses_by_year",
            operating_projection.other_operating_expenses_by_year,
        ),
        "management_fee_by_year": _format_tuple(
            "management_fee_by_year", operating_projection.management_fee_by_year
        ),
        "total_operating_expenses_by_year": _format_tuple(
            "total_operating_expenses_by_year",
            operating_projection.total_operating_expenses_by_year,
        ),
        "noi_by_year": _format_tuple("noi_by_year", operating_projection.noi_by_year),
        "exit_noi": format_metric_value("exit_noi", operating_projection.exit_noi),
        "going_in_cap_rate": format_metric_value(
            "going_in_cap_rate", operating_projection.going_in_cap_rate
        ),
    }


def _format_results(results: AcquisitionResults) -> dict[str, Any]:
    return {
        "going_in_cap_rate": format_metric_value("going_in_cap_rate", results.going_in_cap_rate),
        "loan_amount": format_metric_value("loan_amount", results.loan_amount),
        "acquisition_costs": format_metric_value("acquisition_costs", results.acquisition_costs),
        "financing_fee": format_metric_value("financing_fee", results.financing_fee),
        "initial_equity": format_metric_value("initial_equity", results.initial_equity),
        "monthly_debt_service": format_metric_value(
            "monthly_debt_service", results.monthly_debt_service
        ),
        "annual_debt_service": _format_tuple("annual_debt_service", results.annual_debt_service),
        "remaining_loan_balance": format_metric_value(
            "remaining_loan_balance", results.remaining_loan_balance
        ),
        "noi_by_year": _format_tuple("noi_by_year", results.noi_by_year),
        "capex_by_year": _format_tuple("capex_by_year", results.capex_by_year),
        "exit_noi": format_metric_value("exit_noi", results.exit_noi),
        "exit_value": format_metric_value("exit_value", results.exit_value),
        "disposition_costs": format_metric_value("disposition_costs", results.disposition_costs),
        "net_sale_proceeds": format_metric_value("net_sale_proceeds", results.net_sale_proceeds),
        "unlevered_cash_flows": _format_tuple(
            "unlevered_cash_flows", results.unlevered_cash_flows
        ),
        "levered_cash_flows": _format_tuple("levered_cash_flows", results.levered_cash_flows),
        "unlevered_irr": format_metric_value("unlevered_irr", results.unlevered_irr),
        "levered_irr": format_metric_value("levered_irr", results.levered_irr),
        "equity_multiple": format_metric_value("equity_multiple", results.equity_multiple),
        "dscr_by_year": _format_tuple("headline_dscr", results.dscr_by_year),
        "headline_dscr": format_metric_value("headline_dscr", results.headline_dscr),
        "min_dscr": format_metric_value("min_dscr", results.min_dscr),
    }


def _format_hurdle_evaluation(context: AnalysisContext) -> dict[str, str]:
    """The primary, deterministic above/at/below labels for the three
    headline hurdle-relevant metrics against their user-supplied targets --
    exactly the comparison the model must defer to instead of judging a
    hurdle relationship from a raw number itself. Reads ``context.results``
    only, which is present and identically shaped for both modes."""

    return {
        "levered_irr_vs_target": format_hurdle_relationship(
            "levered_irr", context.results.levered_irr, context.target_levered_irr
        ),
        "equity_multiple_vs_target": format_hurdle_relationship(
            "equity_multiple", context.results.equity_multiple, context.target_equity_multiple
        ),
        "headline_dscr_vs_target": format_hurdle_relationship(
            "headline_dscr", context.results.headline_dscr, context.target_headline_dscr
        ),
    }


def _format_two_way(result: TwoWaySensitivityResult, *, target: float | None) -> dict[str, Any]:
    if target is None:
        formatted_matrix = tuple(
            tuple(format_metric_value(result.metric, cell) for cell in row)
            for row in result.matrix
        )
        baseline_metric_value = format_metric_value(result.metric, result.baseline_metric_value)
    else:
        formatted_matrix = tuple(
            tuple(format_hurdle_relationship(result.metric, cell, target) for cell in row)
            for row in result.matrix
        )
        baseline_metric_value = format_hurdle_relationship(
            result.metric, result.baseline_metric_value, target
        )

    return {
        "row_assumption": result.row_assumption,
        "column_assumption": result.column_assumption,
        "metric": result.metric,
        "row_values": tuple(
            format_metric_value(result.row_assumption, value) for value in result.row_values
        ),
        "column_values": tuple(
            format_metric_value(result.column_assumption, value)
            for value in result.column_values
        ),
        "baseline_row_value": format_metric_value(
            result.row_assumption, result.baseline_row_value
        ),
        "baseline_column_value": format_metric_value(
            result.column_assumption, result.baseline_column_value
        ),
        "baseline_metric_value": baseline_metric_value,
        "matrix": formatted_matrix,
    }


def _format_break_even_result(result: BreakEvenResult) -> dict[str, Any]:
    if result.status is BreakEvenStatus.SOLVED:
        solved_result = (
            f"{format_metric_value(result.assumption, result.solved_assumption_value)} "
            f"(metric {format_metric_value(result.metric, result.solved_metric_value)})"
        )
    else:
        solved_result = (
            "no_solution_in_range -- no qualifying value was found inside the "
            "documented search bounds below for this question (this does not "
            "mean no solution exists outside that range)"
        )

    return {
        "break_even_type": result.break_even_type.value,
        "assumption": result.assumption,
        "metric": result.metric,
        "target_metric_value": format_metric_value(result.metric, result.target_metric_value),
        "baseline_assumption_value": format_metric_value(
            result.assumption, result.baseline_assumption_value
        ),
        "baseline_metric_value_vs_target": format_hurdle_relationship(
            result.metric, result.baseline_metric_value, result.target_metric_value
        ),
        "search_bounds": (
            f"{format_metric_value(result.assumption, result.lower_search_bound)} to "
            f"{format_metric_value(result.assumption, result.upper_search_bound)}"
        ),
        "status": result.status.value,
        "solved_result": solved_result,
    }


# =============================================================================
# Top-level payload
# =============================================================================


def _format_quick_sensitivities(context: AnalysisContext) -> dict[str, Any]:
    sensitivities = context.sensitivities
    return {
        "exit_cap_noi_growth": _format_two_way(
            sensitivities.exit_cap_noi_growth,
            target=_resolve_target_for_metric(context, sensitivities.exit_cap_noi_growth.metric),
        ),
        "purchase_price_exit_cap": _format_two_way(
            sensitivities.purchase_price_exit_cap,
            target=_resolve_target_for_metric(
                context, sensitivities.purchase_price_exit_cap.metric
            ),
        ),
        "interest_rate_ltv": _format_two_way(
            sensitivities.interest_rate_ltv,
            target=_resolve_target_for_metric(context, sensitivities.interest_rate_ltv.metric),
        ),
        "interest_rate_ltv_dscr": _format_two_way(
            sensitivities.interest_rate_ltv_dscr,
            target=_resolve_target_for_metric(
                context, sensitivities.interest_rate_ltv_dscr.metric
            ),
        ),
    }


def _format_detailed_sensitivities(context: AnalysisContext) -> dict[str, Any]:
    sensitivities = context.sensitivities
    return {
        "purchase_price_exit_cap": _format_two_way(
            sensitivities.purchase_price_exit_cap,
            target=_resolve_target_for_metric(
                context, sensitivities.purchase_price_exit_cap.metric
            ),
        ),
        "interest_rate_ltv": _format_two_way(
            sensitivities.interest_rate_ltv,
            target=_resolve_target_for_metric(context, sensitivities.interest_rate_ltv.metric),
        ),
        "interest_rate_ltv_dscr": _format_two_way(
            sensitivities.interest_rate_ltv_dscr,
            target=_resolve_target_for_metric(
                context, sensitivities.interest_rate_ltv_dscr.metric
            ),
        ),
    }


def _format_quick_break_even(context: AnalysisContext) -> dict[str, Any]:
    break_even = context.break_even
    return {
        "max_purchase_price": _format_break_even_result(break_even.max_purchase_price),
        "max_exit_cap_rate": _format_break_even_result(break_even.max_exit_cap_rate),
        "min_noi_growth": _format_break_even_result(break_even.min_noi_growth),
        "max_interest_rate": _format_break_even_result(break_even.max_interest_rate),
        "min_current_noi": _format_break_even_result(break_even.min_current_noi),
    }


def _format_detailed_break_even(context: AnalysisContext) -> dict[str, Any]:
    break_even = context.break_even
    return {
        "max_purchase_price": _format_break_even_result(break_even.max_purchase_price),
        "max_exit_cap_rate": _format_break_even_result(break_even.max_exit_cap_rate),
        "max_interest_rate": _format_break_even_result(break_even.max_interest_rate),
    }


def build_presentation_payload(context: AnalysisContext) -> dict[str, Any]:
    """Return the complete presentation-formatted, JSON-serializable
    evidence payload for ``context`` -- currency in $/K/M, rates/IRRs as
    percentages, equity multiple/DSCR as "x" multiples, years left as-is,
    and every hurdle-relevant metric already labeled above/at/below its
    target. Every value is read from ``context`` unchanged; only its string
    presentation and (for hurdle-relevant metrics) an already-computed
    above/at/below label are added here.

    Branches only on ``context.operating_mode`` to decide which
    already-computed base-assumption fields to include: Quick's
    ``base_inputs`` (the fourteen ``AcquisitionInputs`` fields), or
    Detailed's ``base_terms`` (the eleven shared ``AcquisitionTerms``
    fields) + ``base_detailed_operating_inputs`` (the eleven
    ``DetailedOperatingInputs`` fields) + ``operating_projection`` (the
    full Detailed schedule). ``base_results``, ``hurdle_targets``, and
    ``hurdle_evaluation`` are identical in shape for both modes -- they are
    never mode-specific. Detailed's ``sensitivities``/``break_even``
    sections have three members instead of Quick's four/five (no Detailed
    counterpart exists for ``exit_cap_noi_growth``/``min_noi_growth``/
    ``min_current_noi`` -- see ``StandardDetailedSensitivityPresets``/
    ``StandardDetailedBreakEvenAnalysis``).
    """

    payload: dict[str, Any] = {
        "operating_mode": context.operating_mode.value,
        "base_results": _format_results(context.results),
        "hurdle_targets": {
            "target_levered_irr": format_metric_value("levered_irr", context.target_levered_irr),
            "target_equity_multiple": format_metric_value(
                "equity_multiple", context.target_equity_multiple
            ),
            "target_headline_dscr": format_metric_value(
                "headline_dscr", context.target_headline_dscr
            ),
            "return_hurdle_metric": context.return_hurdle_metric.value,
        },
        "hurdle_evaluation": _format_hurdle_evaluation(context),
    }

    if context.operating_mode is OperatingMode.QUICK:
        assert context.inputs is not None
        payload["base_inputs"] = _format_inputs(context.inputs)
        payload["sensitivities"] = _format_quick_sensitivities(context)
        payload["break_even"] = _format_quick_break_even(context)
    else:
        assert context.terms is not None
        assert context.detailed_operating_inputs is not None
        assert context.operating_projection is not None
        payload["base_terms"] = _format_terms(context.terms)
        payload["base_detailed_operating_inputs"] = _format_detailed_operating_inputs(
            context.detailed_operating_inputs
        )
        payload["operating_projection"] = _format_operating_projection(
            context.operating_projection
        )
        payload["sensitivities"] = _format_detailed_sensitivities(context)
        payload["break_even"] = _format_detailed_break_even(context)

    return payload
