"""Phase 6 Gate D6.8 -- AI Business Plan & Capital Economics grounding.

Context and prompt tests only. Every assertion is about what Anchor *supplies*
to the model -- the evidence payload and the system prompt -- never about what a
live model writes, and no test makes a network call.

Covered here (gate Parts C-X, AA, AB, AI and AJ):

- C1-C10: empty plan; closing, future and post-hold capital; owner expense;
  Lease-Level TI/LC beside Project Capital; the Net Additional Equity
  Requirement; multiple sign changes; Sources & Uses; no value attribution.
- Every ``IrrStatus`` explained, and explained even when there is no plan.
- Every D6 figure is the engine's own field, formatted, shown in exactly one
  place -- never also by ``_format_results``' generic reflection.
- Each item's timing is the bucket the resolver chose.
- The same plan is grounded identically in all three modes.
- The API hands every mode's request plan to the model.
"""

from __future__ import annotations

import dataclasses
import json
import re
from functools import lru_cache
from typing import Any

import pytest

from anchor.ai import AIAnalysis, AnalysisContext
from anchor.ai.analyst import (
    build_analysis_context,
    build_detailed_analysis_context,
    build_lease_level_analysis_context,
)
from anchor.ai.presentation import (
    INTENTIONALLY_EXCLUDED_RESULT_FIELDS,
    _IRR_STATUS_EXPLANATIONS,
    _capital_item_timing,
    _format_irr_status,
    build_presentation_payload,
    format_metric_value,
)
from anchor.ai.prompts import build_system_prompt
from anchor.analysis import ParsedLeaseLevelInputs
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from anchor.engine.contracts import IrrStatus

from _d6_5_fixtures import (  # type: ignore[import-not-found]
    MATERIAL,
    MODES,
    analysis_envelope,
    deal_request,
)
from test_d6_2_owner_cash_flow_engine import (  # type: ignore[import-not-found]
    DETAILED_OPERATING,
    DETAILED_TERMS,
    HOLD,
    LL_LEASES,
    LL_MARKET,
    LL_OPERATING,
    LL_PROPERTY,
    LL_SUITES,
    LL_TERMS,
    QUICK,
)

HURDLES: dict[str, Any] = dict(
    target_levered_irr=0.10, target_equity_multiple=1.50, target_headline_dscr=1.20
)
LL_INPUTS = ParsedLeaseLevelInputs(
    property_inputs=LL_PROPERTY,
    operating_inputs=LL_OPERATING,
    market_leasing=LL_MARKET,
    suites=LL_SUITES,
    leases=LL_LEASES,
)
SECTION = "business_plan_and_capital_economics"
IRR = "irr_status"

#: The fifteen D6 result fields, and where each is shown -- its one authority.
D6_FIELD_HOMES: dict[str, tuple[str, str]] = {
    "closing_project_capital": ("project_capital", "closing_project_capital"),
    "project_capital_by_year": ("project_capital", "project_capital_by_year"),
    "post_hold_project_capital": ("project_capital", "post_hold_project_capital"),
    "owner_expenses_by_year": ("owner_expenses", "owner_expenses_by_year"),
    "property_cash_flow_by_year": ("owner_cash_flow", "property_cash_flow_by_year"),
    "unlevered_owner_cash_flow_by_year": (
        "owner_cash_flow",
        "unlevered_owner_cash_flow_by_year",
    ),
    "levered_owner_cash_flow_by_year": ("owner_cash_flow", "levered_owner_cash_flow_by_year"),
    "total_closing_uses": ("sources_and_uses_at_closing", "total_closing_uses"),
    "total_closing_sources": ("sources_and_uses_at_closing", "total_closing_sources"),
    "net_additional_equity_requirement_by_year": (
        "equity_requirements",
        "net_additional_equity_requirement_by_year",
    ),
    "total_equity_invested": ("project_returns", "total_equity_invested"),
    "total_cash_returned": ("project_returns", "total_cash_returned"),
    "total_profit": ("project_returns", "total_profit"),
}
D6_STATUS_FIELDS = {"levered_irr_status", "unlevered_irr_status"}

#: Lender and exit figures D6 capital and owner expenses never touch (Part S).
LENDER_AND_EXIT_FIELDS = (
    "noi_by_year",
    "dscr_by_year",
    "headline_dscr",
    "min_dscr",
    "year_1_debt_yield",
    "loan_amount",
    "annual_debt_service",
    "remaining_loan_balance",
    "exit_noi",
    "exit_value",
    "disposition_costs",
    "net_sale_proceeds",
)


# =============================================================================
# Plans and contexts
# =============================================================================


def cap(
    month: int,
    amount: float,
    *,
    description: str = "Capital item",
    category: CapitalItemCategory = CapitalItemCategory.OTHER,
) -> CapitalPlanItem:
    return CapitalPlanItem(
        item_id=f"cap-{month}-{amount}-{category.value}",
        description=description,
        category=category,
        month=month,
        amount=amount,
    )


def expense(amount: float, first: int, last: int | None = None) -> OwnerExpenseItem:
    return OwnerExpenseItem(
        item_id=f"oe-{first}-{last}-{amount}",
        description="Asset management fee",
        category=OwnerExpenseCategory.ASSET_MANAGEMENT,
        annual_amount=amount,
        first_year=first,
        last_year=last,
    )


def plan(*items: CapitalPlanItem | OwnerExpenseItem) -> BusinessPlan:
    return BusinessPlan(
        capital_items=tuple(i for i in items if isinstance(i, CapitalPlanItem)),
        owner_expense_items=tuple(i for i in items if isinstance(i, OwnerExpenseItem)),
    )


EMPTY = BusinessPlan()
CLOSING = plan(
    cap(0, 1_000_000.0, description="Lobby renovation", category=CapitalItemCategory.VALUE_ADD_RENOVATION)
)
FUTURE = plan(
    cap(18, 1_000_000.0, description="HVAC replacement", category=CapitalItemCategory.BUILDING_SYSTEMS)
)
OWNER_EXPENSE = plan(expense(150_000.0, 1))
POST_HOLD = plan(
    cap(
        12 * HOLD + 6,
        2_000_000.0,
        description="Facade after the sale",
        category=CapitalItemCategory.EXTERIOR_COMMON_AREA,
    )
)
#: A value-add repositioning big enough to turn Year 2 equity cash flow negative.
DEFICIT = plan(
    cap(
        18,
        6_000_000.0,
        description="Value-add repositioning",
        category=CapitalItemCategory.VALUE_ADD_RENOVATION,
    )
)


@lru_cache(maxsize=None)
def context(mode: str, business_plan: BusinessPlan) -> AnalysisContext:
    if mode == "quick":
        return build_analysis_context(QUICK, business_plan=business_plan, **HURDLES)
    if mode == "detailed":
        return build_detailed_analysis_context(
            DETAILED_TERMS, DETAILED_OPERATING, business_plan=business_plan, **HURDLES
        )
    return build_lease_level_analysis_context(
        LL_TERMS,
        LL_INPUTS,
        analysis_envelope("lease_level", business_plan),
        business_plan=business_plan,
        **HURDLES,
    )


def payload(mode: str, business_plan: BusinessPlan) -> dict[str, Any]:
    return build_presentation_payload(context(mode, business_plan))


def section(mode: str, business_plan: BusinessPlan) -> dict[str, Any]:
    return payload(mode, business_plan)[SECTION]


def formatted(field: str, values: tuple[float, ...]) -> tuple[str, ...]:
    return tuple(format_metric_value(field, value) for value in values)


# =============================================================================
# Text helpers
# =============================================================================


def flat(text: str) -> str:
    return " ".join(text.split())


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in strings(item)]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in strings(item)]
    return []


def keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [*value, *(k for item in value.values() for k in keys(item))]
    if isinstance(value, (list, tuple)):
        return [k for item in value for k in keys(item)]
    return []


_NEGATION = re.compile(r"\b(never|not|no|nor|none|without|neither)\b|n't", re.IGNORECASE)


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;:!?])\s+", flat(text)) if s]


def unnegated(text: str, phrase: str) -> list[str]:
    """Sentences that use ``phrase`` without any negation -- the affirmative
    uses a grounding must never contain."""

    return [
        s for s in sentences(text) if phrase.lower() in s.lower() and not _NEGATION.search(s)
    ]


def everything_the_model_reads(mode: str, business_plan: BusinessPlan) -> str:
    return flat(build_system_prompt()) + " " + " ".join(strings(payload(mode, business_plan)))


# =============================================================================
# C1 -- the empty plan
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_c1_an_empty_plan_adds_no_business_plan_section(mode: str) -> None:
    ctx = context(mode, EMPTY)
    body = build_presentation_payload(ctx)

    assert SECTION not in body
    both_reported = (
        ctx.results.levered_irr_status is IrrStatus.DEFINED
        and ctx.results.unlevered_irr_status is IrrStatus.DEFINED
    )
    # The only thing an empty plan can add is the reason an IRR is N/A.
    assert (IRR in body) is (not both_reported)
    assert not set(body["base_results"]) & INTENTIONALLY_EXCLUDED_RESULT_FIELDS


def test_c1_the_fixture_deals_cover_both_empty_plan_outcomes() -> None:
    """Quick and Detailed report both IRRs, so their empty-plan payload is
    exactly the pre-D6.8 one (``tests/test_d6_8_empty_plan_oracle.py``). The
    Lease-Level fixture's lease-up capital already makes its equity cash flow
    change sign twice, so it gains only ``irr_status``."""

    for mode in ("quick", "detailed"):
        assert set(payload(mode, EMPTY)) & {SECTION, IRR} == set()
    body = payload("lease_level", EMPTY)
    assert SECTION not in body
    assert body[IRR]["levered_irr"]["status"] == "multiple_sign_changes"


# =============================================================================
# C2 -- closing capital
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_c2_closing_capital_is_grounded_as_equity_funded_t0(mode: str) -> None:
    body = payload(mode, CLOSING)
    s = body[SECTION]
    results = context(mode, CLOSING).results
    base = context(mode, EMPTY).results

    assert s["capital_plan_items"] == (
        {
            "description": "Lobby renovation",
            "category": "value_add_renovation",
            "model_month": 0,
            "timing": "closing (T0)",
            "amount": "$1.0M",
        },
    )
    assert s["project_capital"]["closing_project_capital"] == "$1.0M"
    assert s["sources_and_uses_at_closing"]["business_plan_at_closing"] == {
        "closing_project_capital": "$1.0M"
    }
    assert (
        s["equity_requirements"]["initial_equity_requirement"]
        == body["base_results"]["initial_equity"]
        == format_metric_value("initial_equity", results.initial_equity)
    )

    # The engine facts the grounding states: equity up, the loan unchanged.
    assert results.initial_equity > base.initial_equity
    assert results.loan_amount == base.loan_amount
    assert (
        s["sources_and_uses_at_closing"]["closing_sources"]["acquisition_debt"]
        == payload(mode, EMPTY)["base_results"]["loan_amount"]
    )

    note = flat(s["project_capital"]["closing_note"])
    for phrase in (
        "paid at closing (T0) with equity",
        "part of the Initial Equity Requirement",
        "part of the unlevered cost basis",
        "does not increase the acquisition loan",
        "not financed by it",
    ):
        assert phrase in note
    assert unnegated(everything_the_model_reads(mode, CLOSING), "financed by the acquisition loan") == []


# =============================================================================
# C3 -- future capital
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_c3_future_capital_lands_in_its_hold_year_and_off_closing(mode: str) -> None:
    body = payload(mode, FUTURE)
    s = body[SECTION]
    results = context(mode, FUTURE).results
    base = context(mode, EMPTY).results

    (item,) = s["capital_plan_items"]
    assert (item["model_month"], item["timing"], item["amount"]) == (18, "hold year 2", "$1.0M")
    assert s["project_capital"]["project_capital_by_year"] == formatted(
        "project_capital_by_year", results.project_capital_by_year
    )
    assert s["project_capital"]["project_capital_by_year"][1] == "$1.0M"

    # Not a closing use: closing uses and closing equity are the empty plan's.
    assert s["sources_and_uses_at_closing"]["business_plan_at_closing"] == {
        "closing_project_capital": "$0"
    }
    assert results.total_closing_uses == base.total_closing_uses
    assert results.initial_equity == base.initial_equity

    # Owner cash flow carries it; the engine's own series are what is shown.
    assert s["owner_cash_flow"]["unlevered_owner_cash_flow_by_year"] == formatted(
        "unlevered_owner_cash_flow_by_year", results.unlevered_owner_cash_flow_by_year
    )
    assert results.unlevered_owner_cash_flow_by_year[1] < base.unlevered_owner_cash_flow_by_year[1]

    note = flat(s["project_capital"]["future_note"])
    assert "It is not a closing use." in note
    assert (
        "It does not directly change NOI, DSCR, debt yield, exit NOI, exit value or "
        "net sale proceeds." in note
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("plan_name", ["FUTURE", "OWNER_EXPENSE", "MATERIAL", "DEFICIT"])
def test_lender_and_exit_figures_the_model_sees_are_the_empty_plans(
    mode: str, plan_name: str
) -> None:
    """Part S: the model is shown lender coverage and the exit valuation
    exactly as they are with no plan, and told why."""

    business_plan = {"FUTURE": FUTURE, "OWNER_EXPENSE": OWNER_EXPENSE, "MATERIAL": MATERIAL, "DEFICIT": DEFICIT}[plan_name]
    planned, empty = payload(mode, business_plan), payload(mode, EMPTY)

    for name in LENDER_AND_EXIT_FIELDS:
        assert planned["base_results"][name] == empty["base_results"][name], name
    assert planned["hurdle_evaluation"]["headline_dscr_vs_target"] == (
        empty["hurdle_evaluation"]["headline_dscr_vs_target"]
    )
    note = planned[SECTION]["lender_and_exit_note"]
    for name in LENDER_AND_EXIT_FIELDS:
        assert name in note
    assert "not lender coverage or the exit valuation" in note


# =============================================================================
# C4 -- owner expense only
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_c4_owner_expenses_are_below_noi_owner_costs(mode: str) -> None:
    body = payload(mode, OWNER_EXPENSE)
    s = body[SECTION]
    results = context(mode, OWNER_EXPENSE).results
    empty = payload(mode, EMPTY)

    assert s["capital_plan_items"] == ()
    assert s["owner_expense_items"] == (
        {
            "description": "Asset management fee",
            "category": "asset_management",
            "annual_amount": "$150.0K",
            "first_year": "Year 1",
            "last_year": f"through the current hold (Year {HOLD})",
            "hold_treatment": "fully_inside_hold",
        },
    )
    assert s["owner_expenses"]["owner_expenses_by_year"] == ("$150.0K",) * HOLD
    assert s["owner_expenses"]["owner_expenses_by_year"] == formatted(
        "owner_expenses_by_year", results.owner_expenses_by_year
    )
    assert s["project_capital"]["project_capital_by_year"] == ("$0",) * HOLD

    # NOI and every operating-expense line the model sees are unchanged.
    assert body["base_results"]["noi_by_year"] == empty["base_results"]["noi_by_year"]
    statement = {"detailed": "operating_projection", "lease_level": "annual_operating_projection"}
    if mode in statement:
        assert body[statement[mode]] == empty[statement[mode]]

    note = flat(s["owner_expenses"]["note"])
    for phrase in (
        "below NOI",
        "reduce Unlevered and Levered Owner Cash Flow and project returns",
        "not property operating expenses",
        "not the property management fee",
        "not recoverable from tenants",
        "they do not change NOI",
    ):
        assert phrase in note
    prompt = flat(build_system_prompt())
    assert "Owner Expenses are owner-level costs below NOI." in prompt
    assert "never say operating expenses rose because of one." in prompt


# =============================================================================
# C5 -- Lease-Level TI / LC and Project Capital in the same year
# =============================================================================


def test_c5_leasing_capital_and_project_capital_stay_separate_figures() -> None:
    base = context("lease_level", EMPTY).results
    year = next(
        index
        for index, (ti, lc) in enumerate(
            zip(base.tenant_improvements_by_year, base.leasing_commissions_by_year)
        )
        if ti > 0 and lc > 0
    )
    same_year = plan(
        cap(12 * year + 6, 1_000_000.0, description="Roof replacement", category=CapitalItemCategory.BUILDING_SYSTEMS)
    )
    ctx = context("lease_level", same_year)
    results = ctx.results
    body = build_presentation_payload(ctx)
    empty = payload("lease_level", EMPTY)
    s = body[SECTION]

    assert s["capital_plan_items"][0]["timing"] == f"hold year {year + 1}"
    # Three figures, three authorities, none merged into another.
    assert s["project_capital"]["project_capital_by_year"][year] == "$1.0M"
    assert results.project_capital_by_year[year] == 1_000_000.0
    for name in ("tenant_improvements_by_year", "leasing_commissions_by_year", "capex_by_year"):
        assert getattr(results, name) == getattr(base, name), name
        assert body["base_results"][name] == empty["base_results"][name], name
    assert body["leasing_and_capital_costs"] == empty["leasing_and_capital_costs"]
    # Property Cash Flow carries TI/LC but not Project Capital.
    assert results.property_cash_flow_by_year == base.property_cash_flow_by_year
    assert s["owner_cash_flow"]["property_cash_flow_by_year"] == formatted(
        "property_cash_flow_by_year", results.property_cash_flow_by_year
    )

    channels = s["capital_channels"]
    assert "Not Project Capital." in channels["leasing_capital"]
    assert "Not a reserve, not TI, not LC." in channels["project_capital"]
    assert "Never merge them or quote a combined capital figure" in channels["note"]
    assert (
        "When one year carries several (for example TI, LC and Project Capital in "
        "the same Lease-Level year), name each component with its own supplied "
        "value." in flat(build_system_prompt())
    )


# =============================================================================
# C6 -- post-hold capital
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_c6_post_hold_capital_is_disclosed_and_seller_neutral(mode: str) -> None:
    body = payload(mode, POST_HOLD)
    s = body[SECTION]
    results = context(mode, POST_HOLD).results
    base = context(mode, EMPTY).results

    (item,) = s["capital_plan_items"]
    assert (item["model_month"], item["timing"]) == (
        12 * HOLD + 6,
        "after the hold period (post-hold)",
    )
    assert s["project_capital"]["post_hold_project_capital"] == "$2.0M"
    assert s["project_capital"]["closing_project_capital"] == "$0"
    assert s["project_capital"]["project_capital_by_year"] == ("$0",) * HOLD

    # The seller's economics are the empty plan's -- to the bit, and as shown.
    for name in (
        "levered_cash_flows",
        "unlevered_cash_flows",
        "levered_irr",
        "unlevered_irr",
        "equity_multiple",
        "total_equity_invested",
        "total_cash_returned",
        "total_profit",
        "total_closing_uses",
        "exit_value",
        "net_sale_proceeds",
    ):
        assert getattr(results, name) == getattr(base, name), name
    assert body["base_results"] == payload(mode, EMPTY)["base_results"]

    note = flat(s["project_capital"]["post_hold_note"])
    assert "disclosure only" in note
    assert "the seller in this underwriting does not bear it" in note

    # Nothing the model reads tells it to take post-hold capital off anything.
    for sentence in sentences(everything_the_model_reads(mode, POST_HOLD)):
        if re.search(r"post-hold|post_hold|beyond the current hold|after the current hold", sentence, re.I) and re.search(
            r"\b(reduc|subtract|deduct|lower)", sentence, re.I
        ):
            assert _NEGATION.search(sentence), sentence


# =============================================================================
# C7 / Part R -- the Net Additional Equity Requirement, and C8 -- sign changes
# =============================================================================


@pytest.mark.parametrize("mode", ("quick", "detailed"))
def test_c7_the_additional_equity_requirement_uses_the_approved_wording(mode: str) -> None:
    body = payload(mode, DEFICIT)
    s = body[SECTION]
    results = context(mode, DEFICIT).results

    assert results.net_additional_equity_requirement_by_year[1] > 0
    assert s["equity_requirements"]["net_additional_equity_requirement_by_year"] == formatted(
        "net_additional_equity_requirement_by_year",
        results.net_additional_equity_requirement_by_year,
    )
    note = flat(s["equity_requirements"]["note"])
    for phrase in (
        "annual NET requirement",
        "not a peak or intra-year need",
        "not a partnership event",
        "net additional equity requirement or a modeled annual equity deficit",
        "never a capital call",
    ):
        assert phrase in note

    prompt = flat(build_system_prompt())
    for approved in (
        '"net additional equity requirement"',
        '"additional equity requirement"',
        '"modeled annual equity deficit"',
    ):
        assert approved in prompt
    text = everything_the_model_reads(mode, DEFICIT)
    for label in ("capital call", "GP contribution", "partner funding obligation"):
        assert unnegated(text, label) == [], label
    assert not [key for key in keys(body) if "capital_call" in key or "contribution" in key]


@pytest.mark.parametrize(
    "mode, business_plan",
    [("quick", DEFICIT), ("detailed", DEFICIT), ("lease_level", EMPTY)],
    ids=["quick-value-add", "detailed-value-add", "lease-level-lease-up"],
)
def test_c8_multiple_sign_changes_are_explained_never_replaced(
    mode: str, business_plan: BusinessPlan
) -> None:
    body = payload(mode, business_plan)
    results = context(mode, business_plan).results

    assert results.levered_irr is None
    assert results.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES
    assert body["base_results"]["levered_irr"] == "N/A"
    assert body["hurdle_evaluation"]["levered_irr_vs_target"] == (
        "N/A (metric not defined for this scenario)"
    )

    levered = body[IRR]["levered_irr"]
    assert levered["status"] == "multiple_sign_changes"
    assert levered["series"] == "Equity Cash Flow (base_results.levered_cash_flows)"
    assert "The modeled cash-flow pattern changes sign more than once" in levered["explanation"]
    assert "does not report a unique IRR under its current convention" in levered["explanation"]
    assert "does not by itself make the project invalid" in levered["explanation"]
    # No alternative IRR anywhere in the IRR grounding.
    assert re.search(r"\d%", " ".join(strings(body[IRR]))) is None

    if business_plan is DEFICIT:
        # Part R: the value-add profile's other returns are all supplied.
        s = body[SECTION]
        assert results.total_equity_invested > results.initial_equity
        assert s["project_returns"] == {
            "total_equity_invested": format_metric_value("total_equity_invested", results.total_equity_invested),
            "total_cash_returned": format_metric_value("total_cash_returned", results.total_cash_returned),
            "total_profit": format_metric_value("total_profit", results.total_profit),
            "note": s["project_returns"]["note"],
        }
        assert body["base_results"]["equity_multiple"] == format_metric_value(
            "equity_multiple", results.equity_multiple
        )
        assert results.equity_multiple is not None

    prompt = flat(build_system_prompt())
    assert 'never say the deal "has no IRR"' in prompt
    assert "never select one of several possible roots" in prompt
    assert "An unavailable IRR does not by itself make the project invalid or unattractive" in prompt
    assert (
        '"the modeled cash-flow pattern changes sign more than once, so Anchor does '
        'not report a unique IRR under its current convention."' in prompt
    )


#: A phrase each explanation must carry -- faithful to ``evaluate_irr``.
_STATUS_PHRASES = {
    IrrStatus.DEFINED: "Anchor reports this IRR under its deterministic convention.",
    IrrStatus.NO_NONZERO_CASH_FLOW: "Every cash flow in the series is zero",
    IrrStatus.FIRST_NONZERO_NOT_NEGATIVE: "The first nonzero cash flow is positive",
    IrrStatus.NO_POSITIVE_CASH_FLOW: "no period returns cash",
    IrrStatus.MULTIPLE_SIGN_CHANGES: "changes sign more than once",
    IrrStatus.ROOT_OUTSIDE_SEARCH_DOMAIN: "did not find the root within its supported search domain",
    IrrStatus.NUMERICAL_FAILURE: "encountered a numerical failure",
}


def test_the_explanations_cover_the_enum_exactly() -> None:
    assert set(_IRR_STATUS_EXPLANATIONS) == set(IrrStatus) == set(_STATUS_PHRASES)


@pytest.mark.parametrize("status", list(IrrStatus), ids=lambda status: status.value)
def test_every_irr_status_is_explained_faithfully(status: IrrStatus) -> None:
    entry = _format_irr_status(status, series="S", value_field="F")

    assert entry == {
        "series": "S",
        "reported_value": "F",
        "status": status.value,
        "explanation": _IRR_STATUS_EXPLANATIONS[status],
    }
    explanation = entry["explanation"]
    assert _STATUS_PHRASES[status] in explanation
    if status is not IrrStatus.DEFINED:
        assert "Anchor does not report" in explanation
    assert "has no irr" not in explanation.lower()
    # No IRR figure, ever; the only percentage is the -100% bound itself.
    assert re.findall(r"-?\d+(?:\.\d+)?%", explanation) in ([], ["-100%"])


@pytest.mark.parametrize(
    "status",
    [status for status in IrrStatus if status is not IrrStatus.DEFINED],
    ids=lambda status: status.value,
)
def test_an_unreported_irr_reaches_the_model_with_its_reason_even_with_no_plan(
    status: IrrStatus,
) -> None:
    ctx = context("quick", EMPTY)
    results = dataclasses.replace(ctx.results, levered_irr=None, levered_irr_status=status)
    body = build_presentation_payload(dataclasses.replace(ctx, results=results))

    assert SECTION not in body
    assert body["base_results"]["levered_irr"] == "N/A"
    assert body[IRR]["levered_irr"]["status"] == status.value
    assert body[IRR]["levered_irr"]["explanation"] == _IRR_STATUS_EXPLANATIONS[status]
    assert body[IRR]["unlevered_irr"]["status"] == "defined"


# =============================================================================
# C9 -- Sources & Uses
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_c9_sources_and_uses_carry_closing_capital_and_never_future_capital(mode: str) -> None:
    closing_item = cap(0, 750_000.0, description="Closing works")
    mixed = plan(closing_item, cap(18, 2_000_000.0), cap(12 * HOLD + 1, 500_000.0))
    body = payload(mode, mixed)
    su = body[SECTION]["sources_and_uses_at_closing"]
    results = context(mode, mixed).results
    closing_only = context(mode, plan(closing_item)).results
    assumptions = body.get("base_inputs") or body["base_terms"]

    assert su["acquisition_uses"] == {
        "purchase_price": assumptions["purchase_price"],
        "acquisition_costs": body["base_results"]["acquisition_costs"],
        "financing_fees": body["base_results"]["financing_fee"],
    }
    assert su["business_plan_at_closing"] == {"closing_project_capital": "$750.0K"}
    assert su["total_closing_uses"] == format_metric_value("total_closing_uses", results.total_closing_uses)
    assert su["closing_sources"] == {
        "acquisition_debt": body["base_results"]["loan_amount"],
        "initial_equity": body["base_results"]["initial_equity"],
    }
    assert su["total_closing_sources"] == format_metric_value(
        "total_closing_sources", results.total_closing_sources
    )
    # Only the closing item is a closing use -- the engine says so, bit for bit.
    assert results.total_closing_uses == closing_only.total_closing_uses
    assert results.initial_equity == closing_only.initial_equity
    assert "Future and post-hold Project Capital are not closing uses" in su["note"]
    assert (
        "Future and post-hold Project Capital are never closing uses and never "
        "part of closing equity." in flat(build_system_prompt())
    )


# =============================================================================
# C10 -- capital without value attribution; Part X -- categories
# =============================================================================


def test_c10_the_prompt_forbids_attributing_value_to_capital_spend() -> None:
    prompt = flat(build_system_prompt())

    assert "Capital spend is not evidence of value creation by itself." in prompt
    assert (
        "Anchor attributes no NOI, rent, occupancy, exit value or profit to Project "
        "Capital" in prompt
    )
    assert "never compute a return on it, a value created per dollar or a yield on cost" in prompt
    assert '"the model does not attribute that value to the capital spend"' in prompt


@pytest.mark.parametrize("mode", MODES)
def test_c10_the_section_repeats_it_beside_the_numbers(mode: str) -> None:
    s = section(mode, MATERIAL)

    assert "Capital spend is not evidence of value creation by itself" in s["note"]
    assert "no category changes how Anchor treats an item or implies value creation" in s["items_note"]
    text = everything_the_model_reads(mode, MATERIAL)
    for phrase in ("creates value", "created value", "create value", "value creation", "unlocks"):
        assert unnegated(text, phrase) == [], phrase


@pytest.mark.parametrize("mode", MODES)
def test_a_category_changes_a_label_and_nothing_else(mode: str) -> None:
    renovation = plan(cap(18, 1_000_000.0, category=CapitalItemCategory.VALUE_ADD_RENOVATION))
    maintenance = plan(cap(18, 1_000_000.0, category=CapitalItemCategory.DEFERRED_MAINTENANCE))

    assert context(mode, renovation).results == context(mode, maintenance).results
    a, b = section(mode, renovation), section(mode, maintenance)
    assert a["capital_plan_items"][0]["category"] == "value_add_renovation"
    assert b["capital_plan_items"][0]["category"] == "deferred_maintenance"
    relabelled = {**a, "capital_plan_items": ({**a["capital_plan_items"][0], "category": "deferred_maintenance"},)}
    assert relabelled == b


# =============================================================================
# Part AB -- no calculation; Part AA -- one authority per D6 figure
# =============================================================================


def test_the_no_calculation_rule_is_in_the_prompt_and_the_section() -> None:
    prompt = flat(build_system_prompt())
    assert (
        "Use the deterministic values provided. Do not calculate, recompute, estimate "
        "or derive any financial metric or Business Plan total yourself" in prompt
    )
    assert "Never sum item amounts, net one series against another, or rebuild a total" in prompt
    assert (
        "If a figure you would need is not supplied, say the model does not provide "
        "it -- never fill the gap with arithmetic." in prompt
    )
    s = section("quick", MATERIAL)
    assert "Do not calculate, recompute, estimate or derive any total or metric" in s["note"]
    assert "never recompute them from the annual series" in s["project_returns"]["note"]


@pytest.mark.parametrize("mode", MODES)
def test_every_d6_figure_is_the_engines_own_field_formatted(mode: str) -> None:
    ctx = context(mode, MATERIAL)
    results = ctx.results
    body = build_presentation_payload(ctx)
    s = body[SECTION]

    for field, (subsection, key) in D6_FIELD_HOMES.items():
        value = getattr(results, field)
        expected = (
            formatted(field, value) if isinstance(value, tuple) else format_metric_value(field, value)
        )
        assert s[subsection][key] == expected, field
    assert body[IRR]["levered_irr"]["status"] == results.levered_irr_status.value
    assert body[IRR]["unlevered_irr"]["status"] == results.unlevered_irr_status.value


def _paths_of(value: Any, names: set[str], path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in names:
                found.append((*path, key))
            found.extend(_paths_of(item, names, (*path, key)))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_paths_of(item, names, path))
    return found


@pytest.mark.parametrize("mode", MODES)
def test_each_d6_field_is_shown_in_exactly_its_one_home(mode: str) -> None:
    body = payload(mode, MATERIAL)
    found = sorted(_paths_of(body, set(D6_FIELD_HOMES) | D6_STATUS_FIELDS))

    expected = sorted(
        [(SECTION, *home) for home in D6_FIELD_HOMES.values()]
        # The Sources & Uses table lists closing capital as a closing use: the
        # same field, the same formatted string (asserted in C2).
        + [(SECTION, "sources_and_uses_at_closing", "business_plan_at_closing", "closing_project_capital")]
    )
    assert found == expected
    assert not set(body["base_results"]) & (set(D6_FIELD_HOMES) | D6_STATUS_FIELDS)


_SECTION_SHAPE = {
    "note": None,
    "capital_channels": {"recurring_capex_reserve", "leasing_capital", "project_capital", "owner_expenses", "note"},
    "capital_plan_items": None,
    "owner_expense_items": None,
    "items_note": None,
    "project_capital": {
        "closing_project_capital",
        "closing_note",
        "project_capital_by_year",
        "future_note",
        "post_hold_project_capital",
        "post_hold_note",
    },
    "owner_expenses": {"owner_expenses_by_year", "note"},
    "owner_cash_flow": {
        "property_cash_flow_by_year",
        "unlevered_owner_cash_flow_by_year",
        "levered_owner_cash_flow_by_year",
        "note",
    },
    "sources_and_uses_at_closing": {
        "acquisition_uses",
        "business_plan_at_closing",
        "total_closing_uses",
        "closing_sources",
        "total_closing_sources",
        "note",
    },
    "equity_requirements": {"initial_equity_requirement", "net_additional_equity_requirement_by_year", "note"},
    "project_returns": {"total_equity_invested", "total_cash_returned", "total_profit", "note"},
    "lender_and_exit_note": None,
}


def test_the_section_supplies_no_figure_beyond_the_engines() -> None:
    """The exact shape: no combined capital total, no derived ratio, no key the
    engine has no field for could slip in."""

    s = section("quick", MATERIAL)
    assert set(s) == set(_SECTION_SHAPE)
    for key, members in _SECTION_SHAPE.items():
        if members is not None:
            assert set(s[key]) == members, key


# =============================================================================
# Timing, vocabulary and the three-mode oracle
# =============================================================================


@pytest.mark.parametrize("hold_period", [1, 3, HOLD])
def test_each_items_timing_is_the_bucket_the_conventions_define(hold_period: int) -> None:
    """Section 4's table, restated here as the oracle; the implementation asks
    the resolver. Zero-dollar placeholders are placed too."""

    for month in range(0, 12 * hold_period + 14):
        if month == 0:
            expected = "closing (T0)"
        elif month > 12 * hold_period:
            expected = "after the hold period (post-hold)"
        else:
            expected = f"hold year {(month - 1) // 12 + 1}"
        for amount in (0.0, 250_000.0):
            assert _capital_item_timing(cap(month, amount), hold_period=hold_period) == expected, (month, amount)
    assert _capital_item_timing(cap(12, 1.0), hold_period=hold_period) in (
        "hold year 1",
        "after the hold period (post-hold)",
    )


def test_the_month_twelve_boundary_is_the_resolvers() -> None:
    assert _capital_item_timing(cap(12, 1.0), hold_period=HOLD) == "hold year 1"
    assert _capital_item_timing(cap(13, 1.0), hold_period=HOLD) == "hold year 2"
    assert _capital_item_timing(cap(12 * HOLD, 1.0), hold_period=HOLD) == f"hold year {HOLD}"
    assert _capital_item_timing(cap(12 * HOLD + 1, 1.0), hold_period=HOLD) == (
        "after the hold period (post-hold)"
    )


def test_the_d6_vocabulary_is_used_and_the_legacy_names_are_not() -> None:
    text = " ".join(strings(section("lease_level", MATERIAL)))
    for term in (
        "Property Cash Flow",
        "Unlevered Owner Cash Flow",
        "Levered Owner Cash Flow",
        "Equity Cash Flow",
        "Initial Equity Requirement",
        "Net Additional Equity Requirement",
        "Total Equity Invested",
        "Total Cash Returned",
        "Total Profit",
        "Closing Project Capital",
    ):
        assert term in text, term
    prompt = flat(build_system_prompt())
    new_rules = prompt.split("BUSINESS PLAN & CAPITAL ECONOMICS RULES (mandatory")[1].split(
        "Return only the structured fields"
    )[0]
    for legacy in ("recurring levered cash flow", "successor capital", "value created by renovation", "negative distribution"):
        assert legacy not in text.lower(), legacy
        assert legacy not in new_rules.lower(), legacy


def _definitions(value: Any, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    """Every piece of meaning in a section that is not a mode's own figure."""

    found: dict[tuple[str, ...], str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            found.update(_definitions(item, (*path, key)))
    elif isinstance(value, str) and (path[-1].endswith("note") or path[0] == "capital_channels"):
        found[path] = value
    return found


def test_the_same_plan_is_grounded_identically_in_every_mode() -> None:
    """Part AJ. Mode-specific NOI and operations differ; the Business Plan's
    definitions, items and resolved plan amounts do not."""

    sections = {mode: section(mode, MATERIAL) for mode in MODES}
    reference = sections["quick"]
    for mode, s in sections.items():
        assert set(s) == set(reference), mode
        assert _definitions(s) == _definitions(reference), mode
        assert s["capital_plan_items"] == reference["capital_plan_items"], mode
        assert s["owner_expense_items"] == reference["owner_expense_items"], mode
        for key in ("closing_project_capital", "project_capital_by_year", "post_hold_project_capital"):
            assert s["project_capital"][key] == reference["project_capital"][key], (mode, key)
        assert s["owner_expenses"]["owner_expenses_by_year"] == reference["owner_expenses"]["owner_expenses_by_year"]
        assert payload(mode, MATERIAL)[IRR]["note"] == payload("quick", MATERIAL)[IRR]["note"]
    # And the mode-specific figures really do differ -- the comparison is not vacuous.
    assert sections["quick"]["owner_cash_flow"] != sections["detailed"]["owner_cash_flow"]


# =============================================================================
# The Lease-Level arm and the API
# =============================================================================


def test_the_lease_level_arm_cannot_be_built_without_naming_its_plan() -> None:
    with pytest.raises(TypeError, match="business_plan"):
        build_lease_level_analysis_context(  # type: ignore[call-arg]
            LL_TERMS, LL_INPUTS, analysis_envelope("lease_level", EMPTY), **HURDLES
        )
    with pytest.raises(ValueError, match="business_plan"):
        dataclasses.replace(context("quick", EMPTY), business_plan=None)  # type: ignore[arg-type]


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def generate_analysis(self, *, system_prompt: str, user_prompt: str) -> AIAnalysis:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return AIAnalysis(
            executive_summary="Summary.",
            investment_view="View.",
            strengths=("Strength.",),
            risks=("Risk.",),
            return_drivers=("Driver.",),
            downside_analysis="Downside.",
            capital_structure_analysis="Capital.",
            break_even_analysis="Break-even.",
            questions_to_investigate=("Question.",),
            confidence_notes=("Note.",),
        )


_GENERATORS = {
    "quick": "generate_ai_analysis",
    "detailed": "generate_detailed_ai_analysis",
    "lease_level": "generate_lease_level_ai_analysis",
}


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from anchor.api import app

    monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "d6-8.db"))
    return TestClient(app)


@pytest.mark.parametrize("mode", MODES)
def test_the_api_grounds_the_requests_own_plan_in_every_mode(
    client, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    import anchor.api as api_module

    real = getattr(api_module, _GENERATORS[mode])
    captured: dict[str, Any] = {}

    def _recording(*args: Any, **kwargs: Any) -> AIAnalysis:
        provider = _RecordingProvider()
        result = real(*args, provider=provider, **kwargs)
        captured.update(provider.calls[0])
        captured["business_plan"] = kwargs["business_plan"]
        return result

    monkeypatch.setattr(api_module, _GENERATORS[mode], _recording)

    response = client.post("/ai/analysis", json=deal_request(mode, MATERIAL, **HURDLES))

    assert response.status_code == 200, response.text
    assert captured["business_plan"] == MATERIAL
    user_prompt = captured["user_prompt"]
    shown = json.loads(user_prompt[user_prompt.index("{"):])
    assert [item["description"] for item in shown[SECTION]["capital_plan_items"]] == [
        item.description for item in MATERIAL.capital_items
    ]
    # Exactly the payload the direct path builds for the same deal and plan.
    assert shown == json.loads(json.dumps(payload(mode, MATERIAL)))
    assert "BUSINESS PLAN & CAPITAL ECONOMICS RULES" in captured["system_prompt"]
    assert "IRR STATUS RULES" in captured["system_prompt"]
