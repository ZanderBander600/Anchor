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
*which* already-computed fields to include (Quick's ``base_inputs``,
Detailed's ``base_terms``/``base_detailed_operating_inputs``/
``operating_projection``, or Lease-Level's rent roll, annual operating
statement, leasing capital, occupancy and exit window) -- never introducing a
new calculation for any of them.

D5.8 adds the third mode and no arithmetic with it. The Lease-Level sections
read ``annual_projection`` -- the canonical annual view the shared returns
engine itself consumed -- rather than re-aggregating the monthly projection
that produced it, so there is exactly one arithmetic path to every figure the
model is shown. The full ``12H + 12`` monthly statement is deliberately not
serialized: everything the model needs from it is already in the annual view
and the exit window, and sending it would be a second copy of the same
economics at roughly an order of magnitude more tokens. The raw ``AnalysisContext`` (and therefore every raw decimal) remains
available unchanged wherever else it is needed -- this module only changes
what the model is shown, never what Anchor stores or computes.
"""

from __future__ import annotations

from typing import Any

from ..analysis import ParsedLeaseLevelInputs
from ..analysis.contracts import (
    BreakEvenResult,
    BreakEvenStatus,
    LeaseLevelAcquisitionResults,
    TwoWaySensitivityResult,
)
from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
    UnsupportedOperatingModeError,
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
        # Owner Return Metrics V3 Gate A4: levered_cash_on_cash_by_year and
        # unlevered_cash_yield_by_year are both decimal-fraction yields,
        # formatted identically to every other percent field above.
        "levered_cash_on_cash_by_year",
        "unlevered_cash_yield_by_year",
        "year_1_debt_yield",
        # D5.8 -- Lease-Level rates. ``physical_occupancy_at_year_end`` and
        # ``average_physical_occupancy_over_year`` are two genuinely different
        # occupancy measures (a snapshot and an average) and are deliberately
        # named and presented as two, never collapsed into one figure.
        "physical_occupancy_at_year_end",
        "average_physical_occupancy_over_year",
        "credit_loss_pct",
        "other_income_growth",
        "recoverable_expense_ratio",
        "market_rent_growth",
        "renewal_rent_spread",
        "successor_escalation_pct",
        "renewal_lc_pct",
        "new_lc_pct",
        "renewal_probability",
        "escalation_pct",
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
        # Owner Return Metrics V3 Gate A4: a dollar schedule, formatted
        # identically to noi_by_year/capex_by_year above.
        "cumulative_operating_distributions_by_year",
        # Sprint D Gate D4.5A's below-NOI operating-capital channel, presented
        # from D5.8 onward -- see the allowlist note below.
        "tenant_improvements_by_year",
        "leasing_commissions_by_year",
        # D5.8 -- the Lease-Level annual operating statement's own dollar
        # lines, each read verbatim off ``AnnualOperatingProjection``.
        "contractual_base_rent_by_year",
        "cash_base_rent_by_year",
        "free_rent_by_year",
        "expense_recovery_by_year",
        "credit_loss_by_year",
        "fixed_operating_expenses_by_year",
        "exit_window_leasing_costs",
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

# D5.8 -- the Lease-Level vocabulary. Four kinds the first two modes never
# needed, because neither has a rent roll: square feet, dollars per square foot,
# months of term/downtime/free rent, and a calendar date.
#
# Every name below is a field of an already-computed Lease-Level contract. None
# of them is derived here; they are classified so that the same
# ``format_metric_value`` that refuses an unknown Quick/Detailed field keeps
# refusing an unknown Lease-Level one, rather than guessing a convention.
_AREA_FIELDS: frozenset[str] = frozenset(
    {
        "rentable_area_sf",
        "suite_area_sf",
        "leased_area_sf",
        "occupied_area_at_year_end",
        "vacant_area_at_year_end",
    }
)
_PSF_FIELDS: frozenset[str] = frozenset(
    {
        "market_rent_psf",
        "renewal_rent_psf",
        "base_rent_psf",
        "renewal_ti_psf",
        "new_ti_psf",
        "expense_stop_psf",
        "renewal_expense_stop_psf",
        "new_expense_stop_psf",
    }
)
_MONTH_FIELDS: frozenset[str] = frozenset(
    {
        "renewal_term_months",
        "new_term_months",
        "renewal_downtime_months",
        "new_downtime_months",
        "renewal_free_rent_months",
        "new_free_rent_months",
        "downtime_months",
        "free_rent_months",
        "initial_lease_up_months",
    }
)
_DATE_FIELDS: frozenset[str] = frozenset(
    {
        "analysis_start_date",
        "lease_start_date",
        "rent_commencement_date",
        "lease_expiration_date",
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
# accident.
#
# Owner Return Metrics V3 Gate A2 added four entries to
# INTENTIONALLY_EXCLUDED_RESULT_FIELDS (``levered_cash_on_cash_by_year``,
# ``unlevered_cash_yield_by_year``, ``cumulative_operating_distributions_by_year``,
# ``year_1_debt_yield``), deliberately withheld from the AI Analyst pending a
# dedicated presentation gate. Gate A4 removes all four: they are now
# formatted and presented like every other ``AcquisitionResults`` field (see
# ``_format_results`` below) -- Deal Context makes them especially useful to
# interpret, per Gate A4's charter.
#
# Sprint D Gate D4.5A re-uses that same precedent for exactly two fields.
# ``tenant_improvements_by_year`` and ``leasing_commissions_by_year`` are the
# generic below-NOI operating-capital channel the shared acquisition engine
# gained at D4.5A. They are **deliberately withheld from the AI Analyst for
# now**: D4 owns deterministic financial integration, and how leasing capital
# should be presented to, and interpreted by, the AI Analyst is a presentation
# question belonging to D5, alongside the rest of the Lease-Level surface.
#
# This is a deferral, not a judgement that the fields are uninteresting. They
# are real owner cash outflows and they already move IRR, the equity multiple
# and every recurring owner-return metric. When D5 gives them a reviewed
# presentation and the grounding rules to interpret them, both entries come
# out of this allowlist exactly as Gate A4 removed A2's four.
#
# **D5.8 removes them, on exactly those terms.** ``tenant_improvements_by_year``
# and ``leasing_commissions_by_year`` are now formatted in ``_format_results``
# like every other ``AcquisitionResults`` field, and the model is given the
# grounding rules that make them interpretable rather than merely visible: the
# LEASING-CAPITAL RULE in ``SYSTEM_PROMPT`` states that they sit **below NOI**,
# reduce owner cash flow, and touch neither NOI, DSCR, debt yield nor exit NOI.
# Presenting the numbers without that rule was the risk the deferral existed to
# avoid, and it is the rule -- not the deferral -- that retires it.
#
# The allowlist itself stays, and stays empty on purpose: a future field that
# should not reach the model still has to be named here, with a reason.
#
# **Phase 6 Gate D6.2 re-uses the precedent for exactly nine fields.** D6.2
# adds the owner cash-flow result fields to ``AcquisitionResults``
# (``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 6, 8 and 10).
# They are **deliberately withheld from the AI Analyst**: D6.8 owns AI grounding
# for the Business Plan, and presenting project capital, owner expenses, owner
# cash flow or Sources & Uses without the grounding rules that say what they are
# -- capital sits below NOI, spending capital does not create value, a negative
# owner cash flow is not a "negative distribution", post-hold capital is
# disclosure only -- is the risk this deferral exists to avoid. When D6.8 gives
# them a reviewed presentation and those rules, they come out of this allowlist
# exactly as D5.8 removed TI/LC.
# =============================================================================

INTENTIONALLY_EXCLUDED_INPUT_FIELDS: frozenset[str] = frozenset()
INTENTIONALLY_EXCLUDED_RESULT_FIELDS: frozenset[str] = frozenset(
    {
        "closing_project_capital",
        "project_capital_by_year",
        "post_hold_project_capital",
        "owner_expenses_by_year",
        "property_cash_flow_by_year",
        "unlevered_owner_cash_flow_by_year",
        "levered_owner_cash_flow_by_year",
        "total_closing_uses",
        "total_closing_sources",
    }
)
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


def format_area(value: float) -> str:
    """Square feet, grouped, with the unit. Formatting only."""

    return f"{value:,.0f} SF"


def format_psf(value: float) -> str:
    """Dollars per square foot. Formatting only -- never a rate times an area."""

    return f"${value:,.2f}/SF"


def format_months(value: float) -> str:
    """A count of months, carrying its unit so a term is never read as a year
    count or a dollar figure. Fractional months are real in this model
    (downtime is not rounded), so a non-integer value keeps one decimal."""

    if float(value).is_integer():
        return f"{value:,.0f} months"
    return f"{value:,.1f} months"


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
    # D5.8 -- the Lease-Level kinds.
    if field_name in _AREA_FIELDS:
        return format_area(value)
    if field_name in _PSF_FIELDS:
        return format_psf(value)
    if field_name in _MONTH_FIELDS:
        return format_months(value)
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
        "levered_cash_on_cash_by_year": _format_tuple(
            "levered_cash_on_cash_by_year", results.levered_cash_on_cash_by_year
        ),
        "unlevered_cash_yield_by_year": _format_tuple(
            "unlevered_cash_yield_by_year", results.unlevered_cash_yield_by_year
        ),
        "cumulative_operating_distributions_by_year": _format_tuple(
            "cumulative_operating_distributions_by_year",
            results.cumulative_operating_distributions_by_year,
        ),
        "year_1_debt_yield": format_metric_value(
            "year_1_debt_yield", results.year_1_debt_yield
        ),
        # D4.5A's below-NOI leasing capital, presented from D5.8. Shared by all
        # three modes, because the channel is the shared engine's: a Quick or
        # Detailed deal simply carries zeroes here. The rule that stops it being
        # read as an operating expense is in SYSTEM_PROMPT, and Lease-Level
        # additionally gets its own labelled section.
        "tenant_improvements_by_year": _format_tuple(
            "tenant_improvements_by_year", results.tenant_improvements_by_year
        ),
        "leasing_commissions_by_year": _format_tuple(
            "leasing_commissions_by_year", results.leasing_commissions_by_year
        ),
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
# D5.8 -- Lease-Level formatters
#
# Every function below reads one already-computed field off
# ``ParsedLeaseLevelInputs`` (the analyst's approved assumptions) or
# ``LeaseLevelAcquisitionResults`` (the authoritative envelope) and formats it.
# Nothing here sums a series, averages an occupancy, aggregates a month into a
# year, nets a cost against a revenue line, or derives a return. The annual
# operating statement the model is shown is ``annual_projection`` verbatim --
# the same object the returns were computed from -- so a figure the AI Analyst
# quotes and a figure Anchor rendered on screen cannot disagree.
# =============================================================================


def _format_date(value: object) -> str:
    """A calendar date as ISO ``YYYY-MM-DD``. Formatting only; no month
    arithmetic happens anywhere in this module."""

    return str(value)


def _format_lease_level_property_inputs(inputs: ParsedLeaseLevelInputs) -> dict[str, Any]:
    return {
        "analysis_start_date": _format_date(inputs.property_inputs.analysis_start_date),
        "rentable_area_sf": format_metric_value(
            "rentable_area_sf", inputs.property_inputs.rentable_area_sf
        ),
    }


def _format_lease_level_operating_inputs(inputs: ParsedLeaseLevelInputs) -> dict[str, Any]:
    """The property-level operating assumptions an analyst approved. The same
    eleven fields ``LeaseLevelOperatingInputs`` carries, none added."""

    operating = inputs.operating_inputs
    return {
        "other_income": format_metric_value("other_income", operating.other_income),
        "other_income_growth": format_metric_value(
            "other_income_growth", operating.other_income_growth
        ),
        "credit_loss_pct": format_metric_value("credit_loss_pct", operating.credit_loss_pct),
        "property_taxes": format_metric_value("property_taxes", operating.property_taxes),
        "insurance": format_metric_value("insurance", operating.insurance),
        "utilities": format_metric_value("utilities", operating.utilities),
        "repairs_maintenance": format_metric_value(
            "repairs_maintenance", operating.repairs_maintenance
        ),
        "other_operating_expenses": format_metric_value(
            "other_operating_expenses", operating.other_operating_expenses
        ),
        "management_fee_pct": format_metric_value(
            "management_fee_pct", operating.management_fee_pct
        ),
        "expense_growth": format_metric_value("expense_growth", operating.expense_growth),
        "recoverable_expense_ratio": format_metric_value(
            "recoverable_expense_ratio", operating.recoverable_expense_ratio
        ),
    }


def _format_market_leasing(market: Any) -> dict[str, Any]:
    """The renewal/new-tenant assumptions behind every rollover in the model.

    Supplied so the model can *discuss* rollover exposure -- renewal
    probability, downtime, free rent, the TI and LC an assumed rollover costs
    -- without reconstructing a single lease. Enum members are rendered by
    value; every number is formatted, none combined.
    """

    return {
        "market_rent_psf": format_metric_value("market_rent_psf", market.market_rent_psf),
        "market_rent_growth": format_metric_value(
            "market_rent_growth", market.market_rent_growth
        ),
        "renewal_probability": format_metric_value(
            "renewal_probability", market.renewal_probability
        ),
        "renewal_rent_psf": format_metric_value("renewal_rent_psf", market.renewal_rent_psf),
        "renewal_rent_spread": format_metric_value(
            "renewal_rent_spread", market.renewal_rent_spread
        ),
        "renewal_term_months": format_metric_value(
            "renewal_term_months", market.renewal_term_months
        ),
        "renewal_downtime_months": format_metric_value(
            "renewal_downtime_months", market.renewal_downtime_months
        ),
        "renewal_free_rent_months": format_metric_value(
            "renewal_free_rent_months", market.renewal_free_rent_months
        ),
        "renewal_ti_psf": format_metric_value("renewal_ti_psf", market.renewal_ti_psf),
        "renewal_lc_pct": format_metric_value("renewal_lc_pct", market.renewal_lc_pct),
        "renewal_lease_type": market.renewal_lease_type.value,
        "new_term_months": format_metric_value("new_term_months", market.new_term_months),
        "new_downtime_months": format_metric_value(
            "new_downtime_months", market.new_downtime_months
        ),
        "new_free_rent_months": format_metric_value(
            "new_free_rent_months", market.new_free_rent_months
        ),
        "new_ti_psf": format_metric_value("new_ti_psf", market.new_ti_psf),
        "new_lc_pct": format_metric_value("new_lc_pct", market.new_lc_pct),
        "new_lease_type": market.new_lease_type.value,
        "successor_escalation_pct": format_metric_value(
            "successor_escalation_pct", market.successor_escalation_pct
        ),
        "leasing_commission_method": market.leasing_commission_method.value,
    }


def _format_suite(suite: Any) -> dict[str, Any]:
    """One suite as the analyst approved it.

    Descriptive, not economic: an identifier, its area, whether it carries its
    own market-leasing override, and -- for a suite with no lease at the
    analysis start -- the explicit vacancy strategy that decides whether it is
    held vacant or leased up, and how long the lease-up takes. That strategy is
    what makes initial vacancy and future lease-up discussable without
    reconstructing the leasing chain.
    """

    vacancy = suite.initial_vacancy
    return {
        "suite_id": suite.suite_id,
        "suite_label": suite.suite_label,
        "suite_area_sf": format_metric_value("suite_area_sf", suite.suite_area_sf),
        "market_rent_psf": (
            format_metric_value("market_rent_psf", suite.market_rent_psf)
            if suite.market_rent_psf is not None
            else None
        ),
        "has_market_leasing_override": suite.market_leasing_override is not None,
        "initial_vacancy_strategy": (
            vacancy.strategy.value if vacancy is not None else None
        ),
        "initial_lease_up_months": (
            format_metric_value("initial_lease_up_months", vacancy.initial_lease_up_months)
            if vacancy is not None
            else None
        ),
    }


def _format_lease(lease: Any) -> dict[str, Any]:
    """One in-place lease as the analyst approved it: who, where, how much,
    and -- the field that drives every rollover -- when it expires."""

    return {
        "lease_id": lease.lease_id,
        "suite_id": lease.suite_id,
        "tenant_name": lease.tenant_name,
        "leased_area_sf": format_metric_value("leased_area_sf", lease.leased_area_sf),
        "rent_commencement_date": _format_date(lease.rent_commencement_date),
        "lease_expiration_date": _format_date(lease.lease_expiration_date),
        "base_rent_psf": format_metric_value("base_rent_psf", lease.base_rent_psf),
        "escalation_pct": format_metric_value("escalation_pct", lease.escalation_pct),
        "escalation_basis": lease.escalation_basis.value,
        "lease_type": lease.lease_type.value,
    }


def _format_rent_roll(inputs: ParsedLeaseLevelInputs) -> dict[str, Any]:
    """The approved rent roll: the suites, the in-place leases, and how many of
    each. ``len`` is a count of records, not a financial derivation -- no area,
    rent or cost is totalled here; the authoritative area totals are
    ``rentable_area_sf`` above and the occupied/vacant series below."""

    return {
        "suite_count": len(inputs.suites),
        "known_lease_count": len(inputs.leases),
        "suites": tuple(_format_suite(suite) for suite in inputs.suites),
        "known_leases": tuple(_format_lease(lease) for lease in inputs.leases),
    }


def _format_lease_level_annual_operating(
    lease_level: LeaseLevelAcquisitionResults,
) -> dict[str, Any]:
    """The Lease-Level annual operating statement, in statement order.

    Read straight off ``annual_projection`` -- the canonical annual view, and
    the same object the shared returns engine consumed. The monthly projection
    is deliberately *not* re-aggregated here: it already produced these figures,
    and summing it a second time would create a second arithmetic path for
    every line the model is about to quote.

    Line order is the operating statement's own, so the model reads revenue,
    then recoveries, then expenses, then NOI -- and finds TI and LC nowhere
    among them (they are their own section, below NOI, further down).
    """

    annual = lease_level.annual_projection
    return {
        "contractual_base_rent_by_year": _format_tuple(
            "contractual_base_rent_by_year", annual.contractual_base_rent_by_year
        ),
        "free_rent_by_year": _format_tuple("free_rent_by_year", annual.free_rent_by_year),
        "cash_base_rent_by_year": _format_tuple(
            "cash_base_rent_by_year", annual.cash_base_rent_by_year
        ),
        "expense_recovery_by_year": _format_tuple(
            "expense_recovery_by_year", annual.expense_recovery_by_year
        ),
        "other_income_by_year": _format_tuple(
            "other_income_by_year", annual.other_income_by_year
        ),
        "credit_loss_by_year": _format_tuple(
            "credit_loss_by_year", annual.credit_loss_by_year
        ),
        "effective_gross_income_by_year": _format_tuple(
            "effective_gross_income_by_year", annual.effective_gross_income_by_year
        ),
        "property_taxes_by_year": _format_tuple(
            "property_taxes_by_year", annual.property_taxes_by_year
        ),
        "insurance_by_year": _format_tuple("insurance_by_year", annual.insurance_by_year),
        "utilities_by_year": _format_tuple("utilities_by_year", annual.utilities_by_year),
        "repairs_maintenance_by_year": _format_tuple(
            "repairs_maintenance_by_year", annual.repairs_maintenance_by_year
        ),
        "other_operating_expenses_by_year": _format_tuple(
            "other_operating_expenses_by_year", annual.other_operating_expenses_by_year
        ),
        "fixed_operating_expenses_by_year": _format_tuple(
            "fixed_operating_expenses_by_year", annual.fixed_operating_expenses_by_year
        ),
        "management_fee_by_year": _format_tuple(
            "management_fee_by_year", annual.management_fee_by_year
        ),
        "total_operating_expenses_by_year": _format_tuple(
            "total_operating_expenses_by_year", annual.total_operating_expenses_by_year
        ),
        "noi_by_year": _format_tuple("noi_by_year", annual.noi_by_year),
        "going_in_cap_rate": format_metric_value(
            "going_in_cap_rate", annual.going_in_cap_rate
        ),
    }


def _format_lease_level_leasing_costs(
    lease_level: LeaseLevelAcquisitionResults,
) -> dict[str, Any]:
    """Tenant Improvements and Leasing Commissions -- the owner's leasing
    capital, presented as its own section precisely so it is never read as an
    operating expense.

    Both series are read off ``annual_projection``; the classification note
    travels with them so the numbers and their meaning cannot be separated by a
    model skimming section names. The rule it states is the shipped financial
    convention, not a presentation choice: TI and LC sit below NOI in every
    month of the model, so NOI, DSCR, debt yield and exit NOI structurally
    cannot contain them.
    """

    annual = lease_level.annual_projection
    return {
        "classification": "below_noi_owner_leasing_capital",
        "tenant_improvements_by_year": _format_tuple(
            "tenant_improvements_by_year", annual.tenant_improvements_by_year
        ),
        "leasing_commissions_by_year": _format_tuple(
            "leasing_commissions_by_year", annual.leasing_commissions_by_year
        ),
        "note": (
            "Tenant Improvements and Leasing Commissions are owner leasing "
            "capital costs incurred BELOW net operating income. They reduce "
            "owner cash flow and therefore the equity multiple and both IRRs. "
            "They are NOT operating expenses: they are not in "
            "total_operating_expenses_by_year, they do not reduce NOI, they do "
            "not affect DSCR or debt yield, and they do not enter exit NOI. "
            "They may fall in any hold year, including the final one."
        ),
    }


def _format_lease_level_occupancy(
    lease_level: LeaseLevelAcquisitionResults,
) -> dict[str, Any]:
    """Two different occupancy measures, kept two.

    ``physical_occupancy_at_year_end`` is a snapshot on the last day of each
    hold year; ``average_physical_occupancy_over_year`` is the average of that
    year's twelve monthly values. A year with a mid-year rollover can differ
    sharply between them, which is exactly the trajectory an analyst wants
    described -- so they are labelled separately and never merged into one
    "occupancy" figure.
    """

    annual = lease_level.annual_projection
    return {
        "physical_occupancy_at_year_end": _format_tuple(
            "physical_occupancy_at_year_end", annual.physical_occupancy_at_year_end
        ),
        "average_physical_occupancy_over_year": _format_tuple(
            "average_physical_occupancy_over_year",
            annual.average_physical_occupancy_over_year,
        ),
        "occupied_area_at_year_end": _format_tuple(
            "occupied_area_at_year_end", annual.occupied_area_at_year_end
        ),
        "vacant_area_at_year_end": _format_tuple(
            "vacant_area_at_year_end", annual.vacant_area_at_year_end
        ),
        "rentable_area_sf": format_metric_value(
            "rentable_area_sf", lease_level.monthly_projection.rentable_area_sf
        ),
        "note": (
            "physical_occupancy_at_year_end is a point-in-time snapshot at each "
            "hold year's end; average_physical_occupancy_over_year is that "
            "year's average across its twelve months. They are two different "
            "measures -- cite whichever you mean by name, and never present one "
            "as the other or blend them into a single occupancy figure."
        ),
    }


def _format_lease_level_exit(lease_level: LeaseLevelAcquisitionResults) -> dict[str, Any]:
    """The forward twelve-month exit valuation window.

    The single most misreadable thing about this mode, so it is stated rather
    than implied: months ``12H+1`` through ``12H+12`` are a **valuation
    window**, not a hold year. The investor does not own the asset through
    them; they exist so the terminal cap rate is applied to a forward NOI
    rather than to a trailing one.

    ``exit_window_leasing_costs`` is that window's TI plus LC. It is a
    **disclosed diagnostic and is deducted from nothing** -- not from exit NOI
    (which structurally cannot contain leasing capital), not from exit value,
    not from net sale proceeds. It is here as rollover context for an analyst
    judging what a buyer inherits, and the note says so, because a model shown
    a cost beside a valuation will otherwise subtract it.
    """

    annual = lease_level.annual_projection
    results = lease_level.results
    return {
        "window": "months 12H+1 through 12H+12, immediately after the hold period",
        "window_note": (
            "This is a VALUATION window, not an additional hold year. The "
            "investor does not own or operate the property during these twelve "
            "months and receives no cash flow from them. They exist only so the "
            "exit cap rate is applied to a forward-looking twelve-month NOI. "
            "Never describe them as Hold Year H+1, never add them to the hold "
            "period, and never treat their NOI as owner cash flow."
        ),
        "exit_noi": format_metric_value("exit_noi", annual.exit_noi),
        "exit_value": format_metric_value("exit_value", results.exit_value),
        "disposition_costs": format_metric_value(
            "disposition_costs", results.disposition_costs
        ),
        "net_sale_proceeds": format_metric_value(
            "net_sale_proceeds", results.net_sale_proceeds
        ),
        "exit_window_leasing_costs": format_metric_value(
            "exit_window_leasing_costs", annual.exit_window_leasing_costs
        ),
        "exit_window_leasing_costs_note": (
            "Disclosed as rollover audit context only. Tenant Improvements and "
            "Leasing Commissions falling in the valuation window are NOT "
            "deducted from exit NOI, exit value or net sale proceeds, and were "
            "not deducted anywhere upstream either -- leasing capital sits "
            "below NOI in every month, so exit NOI never contained it. Do not "
            "subtract this figure from any exit number."
        ),
    }


def _lease_level_sensitivity_availability() -> dict[str, Any]:
    """What ``sensitivities=None`` means for this mode, said explicitly.

    Absence of a standardized bundle is not absence of the capability. Anchor
    ships analyst-directed one-way and two-way Lease-Level sensitivity (D5.7);
    what it does not have is Quick's and Detailed's fixed preset package, so
    there is no standardized bundle to attach to this context. A model left to
    infer the reason for a missing section will report the capability as
    missing, so the reason is supplied.
    """

    return {
        "standardized_bundle_supplied": False,
        "note": (
            "No standardized sensitivity bundle was supplied with this "
            "analysis. This does NOT mean sensitivity analysis is unsupported "
            "or unavailable for a Lease-Level deal: Anchor supports "
            "analyst-directed one-way and two-way sensitivity over Lease-Level "
            "assumptions, run on demand with the analyst's own chosen values. "
            "Unlike Quick and Detailed, this mode has no fixed preset package, "
            "so no precomputed bundle accompanies this context. State that no "
            "sensitivity results were supplied here; never state that "
            "sensitivity cannot be run."
        ),
    }


def _break_even_availability_note() -> dict[str, Any]:
    """What ``break_even=None`` means for this mode.

    Deliberately **not** named ``_lease_level_break_even_*``. Guardrail G35
    (D4.6B) forbids any definition whose name pairs "lease_level" with
    "break_even", because such a name is how a Lease-Level break-even
    implementation would arrive. This function is the opposite of one -- it
    reports that no break-even exists -- and its name says so rather than
    tripping, or widening, a guardrail that is still doing its job.

    Break-even is genuinely not part of the Lease-Level model. ``None`` is the
    correct and complete answer; a zero, a placeholder threshold or a
    "not enough data" result would each be a fabrication.
    """

    return {
        "supplied": False,
        "note": (
            "Break-even analysis was not supplied for this Lease-Level "
            "analysis. Do not state, estimate or imply any break-even "
            "threshold, and do not treat its absence as a zero, a failure or a "
            "result that could not be computed. In break_even_analysis, say "
            "plainly that break-even was not supplied for this analysis and "
            "discuss downside using the supplied operating, coverage and "
            "return evidence instead."
        ),
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


def _add_quick_sections(payload: dict[str, Any], context: AnalysisContext) -> None:
    """The Quick-mode sections of the presentation payload, extracted at D5.1A
    so ``build_presentation_payload`` can resolve its mode *before* formatting
    anything. Behavior is unchanged."""

    assert context.inputs is not None
    payload["base_inputs"] = _format_inputs(context.inputs)
    payload["sensitivities"] = _format_quick_sensitivities(context)
    payload["break_even"] = _format_quick_break_even(context)


def _add_detailed_sections(payload: dict[str, Any], context: AnalysisContext) -> None:
    """The Detailed-mode sections, extracted at D5.1A alongside
    ``_add_quick_sections``. Behavior is unchanged."""

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


def _add_lease_level_sections(payload: dict[str, Any], context: AnalysisContext) -> None:
    """The Lease-Level sections (D5.8).

    Nine sections, each named for what an analyst would call it, and each read
    off one already-computed contract. The two availability sections are not
    padding: they are the only way a reader of this payload can tell a mode
    without a standardized sensitivity bundle apart from a mode where
    sensitivity does not exist -- a distinction Lease-Level depends on, because
    only one of those two is true of it.
    """

    assert context.terms is not None
    assert context.lease_level_inputs is not None
    assert context.lease_level_results is not None
    lease_level_inputs = context.lease_level_inputs
    lease_level = context.lease_level_results

    payload["base_terms"] = _format_terms(context.terms)
    payload["property"] = _format_lease_level_property_inputs(lease_level_inputs)
    payload["base_lease_level_operating_inputs"] = _format_lease_level_operating_inputs(
        lease_level_inputs
    )
    payload["market_leasing_assumptions"] = _format_market_leasing(
        lease_level_inputs.market_leasing
    )
    payload["rent_roll"] = _format_rent_roll(lease_level_inputs)
    payload["annual_operating_projection"] = _format_lease_level_annual_operating(lease_level)
    payload["leasing_and_capital_costs"] = _format_lease_level_leasing_costs(lease_level)
    payload["occupancy"] = _format_lease_level_occupancy(lease_level)
    payload["exit_window"] = _format_lease_level_exit(lease_level)
    payload["sensitivity_availability"] = _lease_level_sensitivity_availability()
    payload["break_even_availability"] = _break_even_availability_note()


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

    Owner Return Metrics V3 Gate A4: a top-level ``"deal_context"`` string
    is included only when ``context.deal_context`` is non-``None`` and
    non-blank after stripping -- an all-whitespace value is treated as "no
    context supplied," same as ``None``, so a blank textarea never produces
    a spurious payload key. This is the one payload field that is not
    engine/analysis output: it is the user's own stated investment
    strategy, read and included verbatim, never reformatted or
    interpreted here (interpretation is the model's job, governed by
    ``SYSTEM_PROMPT``'s Deal Context rules). Deliberately placed as its own
    top-level section, never merged into ``base_inputs``/``base_terms``/
    ``base_results``, so the payload shape itself keeps user-authored
    context visually and structurally distinct from authoritative
    deterministic data.
    """

    # D5.1A: mode dispatch runs FIRST, before any payload is assembled.
    #
    # Previously ``if QUICK: ... else: <Detailed sections>``, so a third mode
    # would have reached the Detailed arm and tripped an ``assert`` -- or, had
    # those asserts been absent, been described to the model under Detailed's
    # section names. Presenting one mode's economics under another mode's labels
    # is a grounding failure, not a mislabelling.
    #
    # Resolving the section builder up front (rather than branching at the end)
    # means an unsupported mode is refused before a single field is formatted.
    # That matters beyond tidiness: the shared ``base_results``/``hurdle_*``
    # block above assumes fields a mode this function cannot serve is not
    # obliged to populate, so formatting first would surface an unsupported mode
    # as an ``AttributeError`` from deep inside a formatter instead of as the
    # explicit refusal it is.
    match context.operating_mode:
        case OperatingMode.QUICK:
            add_mode_sections = _add_quick_sections
        case OperatingMode.DETAILED:
            add_mode_sections = _add_detailed_sections
        case OperatingMode.LEASE_LEVEL:
            add_mode_sections = _add_lease_level_sections
        case _:
            raise UnsupportedOperatingModeError(
                context.operating_mode, operation="build_presentation_payload"
            )

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

    if context.deal_context is not None and context.deal_context.strip():
        payload["deal_context"] = context.deal_context.strip()

    add_mode_sections(payload, context)

    return payload
