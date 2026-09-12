"""Phase 6 Gate D6.4 -- the Business Plan threaded through secondary analysis.

Governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Section 16:
every sensitivity cell and every break-even candidate uses the **same** Business
Plan as the base deal, and D6 adds no Business Plan sensitivity target. Project
capital and owner expenses are absolute scheduled dollars; nothing scales them
with a candidate's price, NOI or rent.

**The oracle is the independent analysis** (gate Part K). A cell is never
merely shown to differ from a plan-less run: it is compared, bit for bit, with
a direct call to the mode's D6.2 Business Plan entry point on the same
candidate assumptions and the same plan. Materiality is then asserted
separately, so an omitted plan cannot hide behind a metric the plan happens not
to move.

Reference cases R1-R12 and Part W of the gate specification. The neutral bit
oracle against the ba804ca tree is
``tests/test_d6_4_neutral_secondary_analysis_oracle.py``; the omission guard is
``tests/test_d6_4_business_plan_threading_architecture.py``.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
from collections.abc import Callable
from enum import Enum
from unittest.mock import patch

import pytest

from anchor.ai import analyst
from anchor.ai.prompts import build_user_prompt
from anchor.analysis import (
    DETAILED_SUPPORTED_ASSUMPTIONS,
    SUPPORTED_METRICS,
    BreakEvenDirection,
    BreakEvenStatus,
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
    build_detailed_interest_rate_ltv_preset,
    build_detailed_purchase_price_exit_cap_preset,
    build_exit_cap_noi_growth_preset,
    build_interest_rate_ltv_preset,
    build_purchase_price_exit_cap_preset,
    build_standard_break_even_analysis,
    build_standard_detailed_break_even_analysis,
    build_standard_detailed_presets,
    build_standard_presets,
    run_detailed_one_way_sensitivity,
    run_detailed_two_way_sensitivity,
    run_lease_level_one_way_sensitivity,
    run_lease_level_two_way_sensitivity,
    run_one_way_sensitivity,
    run_two_way_sensitivity,
    solve_break_even_threshold,
    solve_detailed_break_even_threshold,
    solve_detailed_max_exit_cap_rate,
    solve_detailed_max_interest_rate,
    solve_detailed_max_purchase_price,
    solve_max_exit_cap_rate,
    solve_max_interest_rate,
    solve_max_purchase_price,
    solve_min_current_noi,
    solve_min_noi_growth,
)
from anchor.analysis import break_even as break_even_module
from anchor.analysis import lease_level_sensitivity as lease_level_module
from anchor.analysis import sensitivity as sensitivity_module
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
    resolve_business_plan,
)
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.engine.contracts import AcquisitionResults, IrrStatus
from anchor.validation import validate_acquisition_inputs, validate_acquisition_terms
from tests.test_analysis_d4_6b_lease_level_sensitivity import (
    operating as lease_level_operating,
    property_inputs as lease_level_property,
    rollover_deal,
    terms as lease_level_terms,
)

# =============================================================================
# Plans
# =============================================================================


def cap(
    item_id: str,
    month: int,
    amount: float,
    *,
    description: str = "Renovation",
    category: CapitalItemCategory = CapitalItemCategory.VALUE_ADD_RENOVATION,
) -> CapitalPlanItem:
    return CapitalPlanItem(
        item_id=item_id, description=description, category=category, month=month, amount=amount
    )


def expense(
    item_id: str,
    annual_amount: float,
    *,
    description: str = "Asset management",
    category: OwnerExpenseCategory = OwnerExpenseCategory.ASSET_MANAGEMENT,
) -> OwnerExpenseItem:
    return OwnerExpenseItem(
        item_id=item_id,
        description=description,
        category=category,
        annual_amount=annual_amount,
        first_year=1,
    )


#: Gate Part M's deliberately material plan: closing capital, a Year-2
#: expenditure and a recurring owner expense.
MATERIAL = BusinessPlan(
    capital_items=(cap("closing", 0, 250_000.0), cap("year-2", 18, 1_000_000.0)),
    owner_expense_items=(expense("asset-management", 50_000.0),),
)
#: Material for the three-year Lease-Level fixture, with project capital in the
#: rollover year -- the same year as the rent roll's TI and LC (reference case 5).
LL_MATERIAL = BusinessPlan(
    capital_items=(
        cap("closing", 0, 250_000.0),
        cap("year-2", 18, 1_000_000.0),
        cap("rollover-year", 25, 750_000.0),
    ),
    owner_expense_items=(expense("asset-management", 50_000.0),),
)
#: R9 -- an owner expense and no project capital at all.
OWNER_EXPENSE_ONLY = BusinessPlan(owner_expense_items=(expense("asset-management", 50_000.0),))
#: R10 -- capital scheduled only after a five-year hold (month 61) ...
POST_HOLD_ONLY = BusinessPlan(capital_items=(cap("after-sale", 61, 2_000_000.0),))
#: ... and after the three-year Lease-Level hold (month 37).
LL_POST_HOLD_ONLY = BusinessPlan(capital_items=(cap("after-sale", 37, 2_000_000.0),))
#: R12 -- a Year-2 deficit that gives the equity cash flow multiple sign changes.
IRR_UNDEFINED = BusinessPlan(capital_items=(cap("year-2-deficit", 18, 2_500_000.0),))

# =============================================================================
# Deals
# =============================================================================

#: Levered IRR stays defined under ``MATERIAL`` across every Quick grid used
#: below (probed before the goldens were written), so the plan's effect on it
#: is a real number, not a flip to ``None``.
QUICK = AcquisitionInputs(
    purchase_price=20_000_000.0,
    current_noi=1_500_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.40,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)
TERMS = AcquisitionTerms(
    purchase_price=20_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.40,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)
DETAILED = DetailedOperatingInputs(
    gross_potential_rent=2_400_000.0,
    other_income=60_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=180_000.0,
    insurance=60_000.0,
    utilities=75_000.0,
    repairs_maintenance=60_000.0,
    other_operating_expenses=48_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)
#: R12: under ``IRR_UNDEFINED`` every candidate price leaves Year 2 negative.
SMALL_QUICK = dataclasses.replace(
    QUICK, purchase_price=10_000_000.0, current_noi=600_000.0, ltv=0.60
)

LL_SUITES, LL_LEASES, LL_MARKET = rollover_deal()
LL_HOLD = lease_level_terms().hold_period

AI_TARGETS = {
    "target_levered_irr": 0.10,
    "target_equity_multiple": 1.6,
    "target_headline_dscr": 1.25,
}

# =============================================================================
# Helpers
# =============================================================================


def bits(value: float | None) -> str | None:
    return None if value is None else value.hex()


def encode(value: object) -> object:
    """Bit-exact structural encoding: floats by ``float.hex`` (the last bit and
    the sign of zero are visible), dataclasses by field."""

    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot encode {type(value).__name__}")


def quick_candidate(changes: dict[str, float], base: AcquisitionInputs = QUICK) -> AcquisitionInputs:
    return validate_acquisition_inputs(dataclasses.asdict(dataclasses.replace(base, **changes)))


def quick_with_plan(
    changes: dict[str, float], plan: BusinessPlan, base: AcquisitionInputs = QUICK
) -> AcquisitionResults:
    """The independent oracle: a direct D6.2 Quick Business Plan analysis."""

    return analyze_quick_acquisition_with_business_plan(
        quick_candidate(changes, base), business_plan=plan
    )


def detailed_with_plan(changes: dict[str, float], plan: BusinessPlan) -> AcquisitionResults:
    candidate = validate_acquisition_terms(
        dataclasses.asdict(dataclasses.replace(TERMS, **changes))
    )
    return analyze_detailed_acquisition_with_business_plan(
        candidate, DETAILED, business_plan=plan
    ).results


_LL_TERMS_TARGETS = frozenset({"purchase_price", "exit_cap_rate", "ltv", "interest_rate"})
_LL_MARKET_TARGETS = frozenset({"market_rent_psf", "renewal_probability"})


def lease_level_with_plan(changes: dict[str, float], plan: BusinessPlan) -> AcquisitionResults:
    """The independent Lease-Level oracle: the candidate replacement applied in
    the test itself, then one direct D6.2 Business Plan analysis."""

    deal, market, operating = lease_level_terms(), LL_MARKET, lease_level_operating()
    terms_changes = {k: v for k, v in changes.items() if k in _LL_TERMS_TARGETS}
    market_changes = {k: v for k, v in changes.items() if k in _LL_MARKET_TARGETS}
    operating_changes = {
        k: v for k, v in changes.items() if k not in _LL_TERMS_TARGETS | _LL_MARKET_TARGETS
    }
    if terms_changes:
        deal = validate_acquisition_terms(
            dataclasses.asdict(dataclasses.replace(deal, **terms_changes))
        )
    if market_changes:
        market = dataclasses.replace(market, **market_changes)
    if operating_changes:
        operating = dataclasses.replace(operating, **operating_changes)
    return analyze_lease_level_acquisition_with_business_plan(
        deal,
        lease_level_property(),
        LL_SUITES,
        LL_LEASES,
        market_leasing=market,
        operating_inputs=operating,
        business_plan=plan,
    ).results


def lease_level_one_way(**kwargs: object):
    return run_lease_level_one_way_sensitivity(
        lease_level_terms(),
        lease_level_property(),
        LL_SUITES,
        LL_LEASES,
        market_leasing=LL_MARKET,
        operating_inputs=lease_level_operating(),
        **kwargs,
    )


def lease_level_two_way(**kwargs: object):
    return run_lease_level_two_way_sensitivity(
        lease_level_terms(),
        lease_level_property(),
        LL_SUITES,
        LL_LEASES,
        market_leasing=LL_MARKET,
        operating_inputs=lease_level_operating(),
        **kwargs,
    )


def assert_one_way_is_independent(result, analysis: Callable[[dict], AcquisitionResults]) -> None:
    expected = [
        bits(getattr(analysis({result.assumption: value}), result.metric))
        for value in result.assumption_values
    ]
    assert [bits(value) for value in result.metric_values] == expected
    assert bits(result.baseline_metric_value) == bits(getattr(analysis({}), result.metric))


def assert_matrix_is_independent(result, analysis: Callable[[dict], AcquisitionResults]) -> None:
    for row_value, row in zip(result.row_values, result.matrix, strict=True):
        for column_value, cell in zip(result.column_values, row, strict=True):
            changes = {result.row_assumption: row_value, result.column_assumption: column_value}
            assert bits(cell) == bits(getattr(analysis(changes), result.metric)), changes
    assert bits(result.baseline_metric_value) == bits(getattr(analysis({}), result.metric))


def all_cells(result) -> list[float | None]:
    return [cell for row in result.matrix for cell in row]


@dataclasses.dataclass
class _Call:
    args: tuple
    kwargs: dict
    result: object


def recording(function: Callable) -> tuple[Callable, list[_Call]]:
    """A pass-through that records each call and what it returned."""

    calls: list[_Call] = []

    def wrapper(*args: object, **kwargs: object) -> object:
        result = function(*args, **kwargs)
        calls.append(_Call(args, kwargs, result))
        return result

    return wrapper, calls


def engine_calls(module: object, name: str, run: Callable[[], object]) -> list[_Call]:
    wrapper, calls = recording(getattr(module, name))
    with patch.object(module, name, wrapper):
        run()
    return calls


def assert_one_schedule(calls: list[_Call], plan: BusinessPlan, hold_period: int) -> None:
    """Every engine call of one invocation received the same schedule object --
    resolved once, for the base hold -- and it is exactly this plan's."""

    assert calls
    schedule = calls[0].kwargs["owner_capital"]
    assert all(call.kwargs["owner_capital"] is schedule for call in calls)
    assert schedule == resolve_business_plan(plan, hold_period=hold_period)


# =============================================================================
# R1 -- Quick one-way
# =============================================================================

_QUICK_ONE_WAY = {
    "purchase_price": (18_000_000.0, 20_000_000.0, 22_000_000.0),
    "exit_cap_rate": (0.055, 0.065, 0.075),
    "ltv": (0.30, 0.35, 0.40),
    "interest_rate": (0.045, 0.05, 0.055),
}


@pytest.mark.parametrize("metric", ("levered_irr", "unlevered_irr", "equity_multiple"))
@pytest.mark.parametrize("assumption", sorted(_QUICK_ONE_WAY))
def test_r1_quick_one_way_cell_is_the_independent_plan_aware_analysis(
    assumption: str, metric: str
) -> None:
    values = _QUICK_ONE_WAY[assumption]
    result = run_one_way_sensitivity(
        QUICK, assumption=assumption, values=values, metric=metric, business_plan=MATERIAL
    )

    assert_one_way_is_independent(result, lambda changes: quick_with_plan(changes, MATERIAL))

    # Material: every cell is defined and every cell is moved by the plan.
    unplanned = run_one_way_sensitivity(QUICK, assumption=assumption, values=values, metric=metric)
    assert None not in result.metric_values
    assert all(
        a != b for a, b in zip(result.metric_values, unplanned.metric_values, strict=True)
    )


def test_r1_purchase_price_candidates_keep_project_capital_absolute() -> None:
    """Gate Part E: at a 12M price the Year-2 capital is still 1M, never 1.2M."""

    calls = engine_calls(
        sensitivity_module,
        "analyze_acquisition",
        lambda: run_one_way_sensitivity(
            QUICK,
            assumption="purchase_price",
            values=(10_000_000.0, 12_000_000.0),
            metric="equity_multiple",
            business_plan=MATERIAL,
        ),
    )

    assert [call.args[0].purchase_price for call in calls] == [
        20_000_000.0,
        10_000_000.0,
        12_000_000.0,
    ]
    assert_one_schedule(calls, MATERIAL, QUICK.hold_period)
    for call in calls:
        results = call.result
        assert results.closing_project_capital == 250_000.0
        assert results.project_capital_by_year == (0.0, 1_000_000.0, 0.0, 0.0, 0.0)
        assert results.owner_expenses_by_year == (50_000.0,) * 5


# =============================================================================
# R2 -- Quick two-way, and the Quick preset bundle (Part H)
# =============================================================================


@pytest.mark.parametrize("metric", ("levered_irr", "equity_multiple"))
def test_r2_quick_two_way_every_cell_is_the_independent_plan_aware_analysis(metric: str) -> None:
    grid = {
        "row_assumption": "purchase_price",
        "row_values": (18_000_000.0, 20_000_000.0, 22_000_000.0),
        "column_assumption": "exit_cap_rate",
        "column_values": (0.055, 0.075),
        "metric": metric,
    }
    result = run_two_way_sensitivity(QUICK, **grid, business_plan=MATERIAL)

    assert_matrix_is_independent(result, lambda changes: quick_with_plan(changes, MATERIAL))

    unplanned = run_two_way_sensitivity(QUICK, **grid)
    assert None not in all_cells(result)
    assert all(a != b for a, b in zip(all_cells(result), all_cells(unplanned), strict=True))


def test_r2_quick_financing_grid_holds_the_plan() -> None:
    result = run_two_way_sensitivity(
        QUICK,
        row_assumption="interest_rate",
        row_values=(0.045, 0.055),
        column_assumption="ltv",
        column_values=(0.30, 0.40),
        metric="levered_irr",
        business_plan=MATERIAL,
    )

    assert_matrix_is_independent(result, lambda changes: quick_with_plan(changes, MATERIAL))
    assert None not in all_cells(result)


def test_h_quick_standard_presets_hold_the_plan_in_every_cell() -> None:
    calls = engine_calls(
        sensitivity_module,
        "analyze_acquisition",
        lambda: build_standard_presets(QUICK, business_plan=MATERIAL),
    )
    # No preset cell silently represents the deal before its D6 capital.
    expected = resolve_business_plan(MATERIAL, hold_period=QUICK.hold_period)
    assert calls and all(call.kwargs["owner_capital"] == expected for call in calls)

    presets = build_standard_presets(QUICK, business_plan=MATERIAL)
    matrices = (
        presets.exit_cap_noi_growth,
        presets.purchase_price_exit_cap,
        presets.interest_rate_ltv,
        presets.interest_rate_ltv_dscr,
    )
    for matrix in matrices:
        assert_matrix_is_independent(matrix, lambda changes: quick_with_plan(changes, MATERIAL))

    unplanned = build_standard_presets(QUICK)
    assert presets.exit_cap_noi_growth.matrix != unplanned.exit_cap_noi_growth.matrix
    assert presets.purchase_price_exit_cap.matrix != unplanned.purchase_price_exit_cap.matrix
    assert presets.interest_rate_ltv.matrix != unplanned.interest_rate_ltv.matrix
    # The plan sits below NOI: the DSCR matrix is bit-identical with or without it.
    assert encode(presets.interest_rate_ltv_dscr) == encode(unplanned.interest_rate_ltv_dscr)


def test_h_each_quick_preset_builder_threads_the_plan_on_its_own() -> None:
    for build in (
        build_exit_cap_noi_growth_preset,
        build_purchase_price_exit_cap_preset,
        build_interest_rate_ltv_preset,
    ):
        assert_matrix_is_independent(
            build(QUICK, business_plan=MATERIAL),
            lambda changes: quick_with_plan(changes, MATERIAL),
        )


# =============================================================================
# R3 / R4 -- Detailed one-way, two-way and preset bundle
# =============================================================================

_DETAILED_ONE_WAY = {
    "purchase_price": (16_000_000.0, 20_000_000.0, 24_000_000.0),
    "exit_cap_rate": (0.055, 0.065, 0.075),
    "ltv": (0.30, 0.40, 0.50),
    "interest_rate": (0.045, 0.055),
}


@pytest.mark.parametrize("metric", ("levered_irr", "unlevered_irr", "equity_multiple"))
@pytest.mark.parametrize("assumption", sorted(_DETAILED_ONE_WAY))
def test_r3_detailed_one_way_cell_is_the_independent_plan_aware_analysis(
    assumption: str, metric: str
) -> None:
    values = _DETAILED_ONE_WAY[assumption]
    result = run_detailed_one_way_sensitivity(
        TERMS, DETAILED, assumption=assumption, values=values, metric=metric,
        business_plan=MATERIAL,
    )

    assert_one_way_is_independent(result, lambda changes: detailed_with_plan(changes, MATERIAL))

    unplanned = run_detailed_one_way_sensitivity(
        TERMS, DETAILED, assumption=assumption, values=values, metric=metric
    )
    assert None not in result.metric_values
    assert all(
        a != b for a, b in zip(result.metric_values, unplanned.metric_values, strict=True)
    )


def test_r3_detailed_cells_carry_one_plan_beside_unchanged_operations() -> None:
    """Every Detailed engine call receives the same schedule -- same closing
    capital, same Capital Plan, same timing, same Owner Expenses -- beside the
    caller's own ``DetailedOperatingInputs``. The Detailed target surface has no
    operating assumption to vary (Gate 8), so NOI is the operating model's at
    every candidate and the plan never reaches it."""

    assert DETAILED_SUPPORTED_ASSUMPTIONS == (
        "purchase_price",
        "exit_cap_rate",
        "ltv",
        "interest_rate",
    )

    calls = engine_calls(
        sensitivity_module,
        "analyze_detailed_acquisition_with_projection",
        lambda: run_detailed_one_way_sensitivity(
            TERMS, DETAILED, assumption="purchase_price",
            values=(16_000_000.0, 24_000_000.0), metric="equity_multiple",
            business_plan=MATERIAL,
        ),
    )

    assert len(calls) == 3
    assert_one_schedule(calls, MATERIAL, TERMS.hold_period)
    for call in calls:
        assert call.args[1] is DETAILED
        results = call.result.results
        assert results.closing_project_capital == 250_000.0
        assert results.project_capital_by_year == (0.0, 1_000_000.0, 0.0, 0.0, 0.0)
        assert results.owner_expenses_by_year == (50_000.0,) * 5
        bare = detailed_with_plan({"purchase_price": call.args[0].purchase_price}, BusinessPlan())
        assert encode(results.noi_by_year) == encode(bare.noi_by_year)


@pytest.mark.parametrize("metric", ("levered_irr", "equity_multiple"))
def test_r4_detailed_two_way_every_cell_is_the_independent_plan_aware_analysis(
    metric: str,
) -> None:
    grid = {
        "row_assumption": "purchase_price",
        "row_values": (16_000_000.0, 24_000_000.0),
        "column_assumption": "exit_cap_rate",
        "column_values": (0.055, 0.075),
        "metric": metric,
    }
    result = run_detailed_two_way_sensitivity(TERMS, DETAILED, **grid, business_plan=MATERIAL)

    assert_matrix_is_independent(result, lambda changes: detailed_with_plan(changes, MATERIAL))

    unplanned = run_detailed_two_way_sensitivity(TERMS, DETAILED, **grid)
    assert all(a != b for a, b in zip(all_cells(result), all_cells(unplanned), strict=True))


def test_h_detailed_standard_presets_hold_the_plan_in_every_cell() -> None:
    presets = build_standard_detailed_presets(TERMS, DETAILED, business_plan=MATERIAL)
    for matrix in (
        presets.purchase_price_exit_cap,
        presets.interest_rate_ltv,
        presets.interest_rate_ltv_dscr,
    ):
        assert_matrix_is_independent(matrix, lambda changes: detailed_with_plan(changes, MATERIAL))

    for build in (
        build_detailed_purchase_price_exit_cap_preset,
        build_detailed_interest_rate_ltv_preset,
    ):
        assert_matrix_is_independent(
            build(TERMS, DETAILED, business_plan=MATERIAL),
            lambda changes: detailed_with_plan(changes, MATERIAL),
        )

    unplanned = build_standard_detailed_presets(TERMS, DETAILED)
    assert presets.purchase_price_exit_cap.matrix != unplanned.purchase_price_exit_cap.matrix
    assert presets.interest_rate_ltv.matrix != unplanned.interest_rate_ltv.matrix
    assert encode(presets.interest_rate_ltv_dscr) == encode(unplanned.interest_rate_ltv_dscr)


# =============================================================================
# R5 / R6 -- Lease-Level one-way and two-way
# =============================================================================

_LL_ONE_WAY = {
    "market_rent_psf": (30.0, 36.0, 42.0),
    "renewal_probability": (0.2, 0.8),
    "purchase_price": (36_000_000.0, 44_000_000.0),
    "exit_cap_rate": (0.06, 0.07),
}


@pytest.mark.parametrize("assumption", sorted(_LL_ONE_WAY))
def test_r5_lease_level_one_way_cell_is_the_independent_plan_aware_analysis(
    assumption: str,
) -> None:
    values = _LL_ONE_WAY[assumption]
    result = lease_level_one_way(
        assumption=assumption, values=values, metric="equity_multiple",
        business_plan=LL_MATERIAL,
    )

    assert_one_way_is_independent(
        result, lambda changes: lease_level_with_plan(changes, LL_MATERIAL)
    )

    unplanned = lease_level_one_way(assumption=assumption, values=values, metric="equity_multiple")
    assert all(
        a != b for a, b in zip(result.metric_values, unplanned.metric_values, strict=True)
    )


def test_r5_lease_level_levered_irr_cells_hold_the_plan() -> None:
    result = lease_level_one_way(
        assumption="market_rent_psf", values=(30.0, 42.0), metric="levered_irr",
        business_plan=LL_MATERIAL,
    )
    assert_one_way_is_independent(
        result, lambda changes: lease_level_with_plan(changes, LL_MATERIAL)
    )
    assert None not in result.metric_values


def test_r5_project_capital_stays_a_separate_channel_from_ti_and_lc() -> None:
    """Reference case 5: project capital in the rollover year, beside that
    year's TI and LC. Both reach owner cash flow; neither is merged into the
    other, and the rent roll's TI/LC are bit-identical whatever the plan holds."""

    name = "analyze_lease_level_acquisition_with_projection"
    run = {"assumption": "market_rent_psf", "values": (30.0, 42.0), "metric": "equity_multiple"}
    planned = engine_calls(
        lease_level_module, name, lambda: lease_level_one_way(**run, business_plan=LL_MATERIAL)
    )
    bare = engine_calls(lease_level_module, name, lambda: lease_level_one_way(**run))

    assert_one_schedule(planned, LL_MATERIAL, LL_HOLD)
    assert planned[0].kwargs["owner_capital"].project_capital_by_year == (
        0.0,
        1_000_000.0,
        750_000.0,
    )
    for with_plan, without in zip(planned, bare, strict=True):
        results, reference = with_plan.result.results, without.result.results
        # The rent roll's leasing capital, untouched by the plan.
        assert encode(results.tenant_improvements_by_year) == encode(
            reference.tenant_improvements_by_year
        )
        assert encode(results.leasing_commissions_by_year) == encode(
            reference.leasing_commissions_by_year
        )
        assert results.tenant_improvements_by_year[2] > 0.0
        assert results.leasing_commissions_by_year[2] > 0.0
        # Project capital in the same year, on its own channel.
        assert results.project_capital_by_year == (0.0, 1_000_000.0, 750_000.0)
        assert reference.project_capital_by_year == (0.0, 0.0, 0.0)
        # TI and LC live in property cash flow; the plan never does.
        assert encode(results.noi_by_year) == encode(reference.noi_by_year)
        assert encode(results.property_cash_flow_by_year) == encode(
            reference.property_cash_flow_by_year
        )
        for year in range(LL_HOLD):
            assert results.unlevered_owner_cash_flow_by_year[year] == pytest.approx(
                reference.unlevered_owner_cash_flow_by_year[year]
                - results.project_capital_by_year[year]
                - results.owner_expenses_by_year[year],
                abs=1e-6,
            )


@pytest.mark.parametrize(
    "row, column",
    [
        (("renewal_probability", (0.2, 0.8)), ("exit_cap_rate", (0.06, 0.07))),
        (("market_rent_psf", (30.0, 42.0)), ("purchase_price", (36_000_000.0, 44_000_000.0))),
    ],
    ids=["renewal-x-exit-cap", "market-rent-x-price"],
)
def test_r6_lease_level_two_way_every_cell_is_the_independent_plan_aware_analysis(
    row: tuple, column: tuple
) -> None:
    grid = {
        "row_assumption": row[0],
        "row_values": row[1],
        "column_assumption": column[0],
        "column_values": column[1],
        "metric": "equity_multiple",
    }
    result = lease_level_two_way(**grid, business_plan=LL_MATERIAL)

    assert_matrix_is_independent(
        result, lambda changes: lease_level_with_plan(changes, LL_MATERIAL)
    )

    unplanned = lease_level_two_way(**grid)
    assert all(a != b for a, b in zip(all_cells(result), all_cells(unplanned), strict=True))


# =============================================================================
# R7 -- Quick break-even
# =============================================================================


def _assert_quick_candidates_are_independent(calls: list[_Call], plan: BusinessPlan) -> None:
    for call in calls:
        (candidate,) = call.args
        independent = analyze_quick_acquisition_with_business_plan(candidate, business_plan=plan)
        assert encode(call.result) == encode(independent)


def test_r7_quick_break_even_evaluates_every_candidate_with_the_plan() -> None:
    calls = engine_calls(
        break_even_module,
        "analyze_acquisition",
        lambda: solve_max_purchase_price(QUICK, target_equity_multiple=1.6, business_plan=MATERIAL),
    )
    result = solve_max_purchase_price(QUICK, target_equity_multiple=1.6, business_plan=MATERIAL)

    assert result.status is BreakEvenStatus.SOLVED
    assert len(calls) > 10  # the baseline, both bounds and the bisection
    assert_one_schedule(calls, MATERIAL, QUICK.hold_period)
    _assert_quick_candidates_are_independent(calls, MATERIAL)

    assert bits(result.baseline_metric_value) == bits(quick_with_plan({}, MATERIAL).equity_multiple)
    assert bits(result.solved_metric_value) == bits(
        quick_with_plan({"purchase_price": result.solved_assumption_value}, MATERIAL).equity_multiple
    )
    unplanned = solve_max_purchase_price(QUICK, target_equity_multiple=1.6)
    assert result.solved_assumption_value < unplanned.solved_assumption_value


def test_r7_quick_exit_cap_break_even_holds_the_plan_under_an_irr_hurdle() -> None:
    calls = engine_calls(
        break_even_module,
        "analyze_acquisition",
        lambda: solve_max_exit_cap_rate(QUICK, target_levered_irr=0.10, business_plan=MATERIAL),
    )
    result = solve_max_exit_cap_rate(QUICK, target_levered_irr=0.10, business_plan=MATERIAL)

    assert result.status is BreakEvenStatus.SOLVED
    assert_one_schedule(calls, MATERIAL, QUICK.hold_period)
    _assert_quick_candidates_are_independent(calls, MATERIAL)
    assert bits(result.solved_metric_value) == bits(
        quick_with_plan({"exit_cap_rate": result.solved_assumption_value}, MATERIAL).levered_irr
    )
    unplanned = solve_max_exit_cap_rate(QUICK, target_levered_irr=0.10)
    assert result.solved_assumption_value < unplanned.solved_assumption_value


def test_r7_the_public_quick_threshold_solver_holds_the_plan_too() -> None:
    search = {
        "assumption": "exit_cap_rate",
        "metric": "equity_multiple",
        "target": 1.6,
        "direction": BreakEvenDirection.MAXIMUM,
        "lower_bound": 0.05,
        "upper_bound": 0.10,
    }
    calls = engine_calls(
        break_even_module,
        "analyze_acquisition",
        lambda: solve_break_even_threshold(QUICK, **search, business_plan=MATERIAL),
    )
    solved_value, solved_metric, status = solve_break_even_threshold(
        QUICK, **search, business_plan=MATERIAL
    )

    assert status is BreakEvenStatus.SOLVED
    assert_one_schedule(calls, MATERIAL, QUICK.hold_period)
    _assert_quick_candidates_are_independent(calls, MATERIAL)
    assert bits(solved_metric) == bits(
        quick_with_plan({"exit_cap_rate": solved_value}, MATERIAL).equity_multiple
    )


def test_r7_the_quick_bundle_hands_every_question_the_plan() -> None:
    bundle = build_standard_break_even_analysis(
        QUICK, target_levered_irr=0.10, target_headline_dscr=1.25, business_plan=MATERIAL
    )

    assert bundle.max_purchase_price == solve_max_purchase_price(
        QUICK, target_levered_irr=0.10, business_plan=MATERIAL
    )
    assert bundle.max_exit_cap_rate == solve_max_exit_cap_rate(
        QUICK, target_levered_irr=0.10, business_plan=MATERIAL
    )
    assert bundle.min_noi_growth == solve_min_noi_growth(
        QUICK, target_levered_irr=0.10, business_plan=MATERIAL
    )
    assert bundle.max_interest_rate == solve_max_interest_rate(
        QUICK, target_headline_dscr=1.25, business_plan=MATERIAL
    )
    assert bundle.min_current_noi == solve_min_current_noi(
        QUICK, target_headline_dscr=1.25, business_plan=MATERIAL
    )

    unplanned = build_standard_break_even_analysis(
        QUICK, target_levered_irr=0.10, target_headline_dscr=1.25
    )
    assert bundle.max_exit_cap_rate != unplanned.max_exit_cap_rate
    assert bundle.min_noi_growth != unplanned.min_noi_growth
    # The DSCR questions: the plan never reaches DSCR, so their answers stand.
    assert bundle.max_interest_rate == unplanned.max_interest_rate
    assert bundle.min_current_noi == unplanned.min_current_noi

    by_multiple = build_standard_break_even_analysis(
        QUICK,
        target_levered_irr=0.10,
        target_headline_dscr=1.25,
        target_equity_multiple=1.6,
        return_hurdle_metric=analyst.ReturnHurdleMetric.EQUITY_MULTIPLE,
        business_plan=MATERIAL,
    )
    assert by_multiple.max_purchase_price == solve_max_purchase_price(
        QUICK, target_equity_multiple=1.6, business_plan=MATERIAL
    )


# =============================================================================
# R8 -- Detailed break-even
# =============================================================================


def _assert_detailed_candidates_are_independent(calls: list[_Call], plan: BusinessPlan) -> None:
    for call in calls:
        candidate_terms, operating = call.args
        assert operating is DETAILED
        independent = analyze_detailed_acquisition_with_business_plan(
            candidate_terms, operating, business_plan=plan
        )
        assert encode(call.result.results) == encode(independent.results)


def test_r8_detailed_break_even_evaluates_every_candidate_with_the_plan() -> None:
    def solve():
        return solve_detailed_max_purchase_price(
            TERMS, DETAILED, target_levered_irr=0.15, business_plan=MATERIAL
        )

    calls = engine_calls(break_even_module, "analyze_detailed_acquisition_with_projection", solve)
    result = solve()

    assert result.status is BreakEvenStatus.SOLVED
    assert len(calls) > 10
    assert_one_schedule(calls, MATERIAL, TERMS.hold_period)
    _assert_detailed_candidates_are_independent(calls, MATERIAL)
    assert bits(result.baseline_metric_value) == bits(detailed_with_plan({}, MATERIAL).levered_irr)
    assert bits(result.solved_metric_value) == bits(
        detailed_with_plan({"purchase_price": result.solved_assumption_value}, MATERIAL).levered_irr
    )
    unplanned = solve_detailed_max_purchase_price(TERMS, DETAILED, target_levered_irr=0.15)
    assert result.solved_assumption_value < unplanned.solved_assumption_value


def test_r8_the_public_detailed_threshold_solver_holds_the_plan_too() -> None:
    search = {
        "assumption": "exit_cap_rate",
        "metric": "levered_irr",
        "target": 0.15,
        "direction": BreakEvenDirection.MAXIMUM,
        "lower_bound": 0.05,
        "upper_bound": 0.12,
    }
    calls = engine_calls(
        break_even_module,
        "analyze_detailed_acquisition_with_projection",
        lambda: solve_detailed_break_even_threshold(
            TERMS, DETAILED, **search, business_plan=MATERIAL
        ),
    )
    solved_value, solved_metric, status = solve_detailed_break_even_threshold(
        TERMS, DETAILED, **search, business_plan=MATERIAL
    )

    assert status is BreakEvenStatus.SOLVED
    assert_one_schedule(calls, MATERIAL, TERMS.hold_period)
    _assert_detailed_candidates_are_independent(calls, MATERIAL)
    assert bits(solved_metric) == bits(
        detailed_with_plan({"exit_cap_rate": solved_value}, MATERIAL).levered_irr
    )


def test_r8_the_detailed_bundle_hands_every_question_the_plan() -> None:
    bundle = build_standard_detailed_break_even_analysis(
        TERMS, DETAILED, target_levered_irr=0.15, target_headline_dscr=1.25,
        business_plan=MATERIAL,
    )

    assert bundle.max_purchase_price == solve_detailed_max_purchase_price(
        TERMS, DETAILED, target_levered_irr=0.15, business_plan=MATERIAL
    )
    assert bundle.max_exit_cap_rate == solve_detailed_max_exit_cap_rate(
        TERMS, DETAILED, target_levered_irr=0.15, business_plan=MATERIAL
    )
    assert bundle.max_interest_rate == solve_detailed_max_interest_rate(
        TERMS, DETAILED, target_headline_dscr=1.25, business_plan=MATERIAL
    )

    unplanned = build_standard_detailed_break_even_analysis(
        TERMS, DETAILED, target_levered_irr=0.15, target_headline_dscr=1.25
    )
    assert bundle.max_purchase_price != unplanned.max_purchase_price
    assert bundle.max_exit_cap_rate != unplanned.max_exit_cap_rate
    assert bundle.max_interest_rate == unplanned.max_interest_rate


# =============================================================================
# R9 -- owner expense alone (no project capital)
# =============================================================================


@pytest.mark.parametrize("metric", ("levered_irr", "unlevered_irr", "equity_multiple"))
def test_r9_an_owner_expense_alone_moves_the_returns_in_every_cell(metric: str) -> None:
    result = run_one_way_sensitivity(
        QUICK, assumption="exit_cap_rate", values=(0.055, 0.075), metric=metric,
        business_plan=OWNER_EXPENSE_ONLY,
    )

    assert_one_way_is_independent(
        result, lambda changes: quick_with_plan(changes, OWNER_EXPENSE_ONLY)
    )
    unplanned = run_one_way_sensitivity(
        QUICK, assumption="exit_cap_rate", values=(0.055, 0.075), metric=metric
    )
    assert all(
        a != b for a, b in zip(result.metric_values, unplanned.metric_values, strict=True)
    )


@pytest.mark.parametrize("metric", ("headline_dscr", "exit_value"))
def test_r9_an_owner_expense_never_moves_dscr_or_exit_valuation(metric: str) -> None:
    run = {"assumption": "exit_cap_rate", "values": (0.055, 0.075), "metric": metric}

    assert encode(run_one_way_sensitivity(QUICK, **run, business_plan=OWNER_EXPENSE_ONLY)) == (
        encode(run_one_way_sensitivity(QUICK, **run))
    )
    assert encode(
        run_detailed_one_way_sensitivity(TERMS, DETAILED, **run, business_plan=OWNER_EXPENSE_ONLY)
    ) == encode(run_detailed_one_way_sensitivity(TERMS, DETAILED, **run))


def test_r9_every_rerun_carries_the_expense_into_cash_on_cash_and_never_into_noi() -> None:
    """Threading by more than moving a capital array: with no project capital
    at all, each cell's owner expense reaches IRR, the equity multiple,
    Cash-on-Cash and Cash Yield exactly as the direct analysis does, and never
    NOI, DSCR or exit value."""

    calls = engine_calls(
        sensitivity_module,
        "analyze_acquisition",
        lambda: run_two_way_sensitivity(
            QUICK,
            row_assumption="purchase_price",
            row_values=(18_000_000.0, 22_000_000.0),
            column_assumption="exit_cap_rate",
            column_values=(0.055, 0.075),
            metric="equity_multiple",
            business_plan=OWNER_EXPENSE_ONLY,
        ),
    )

    assert_one_schedule(calls, OWNER_EXPENSE_ONLY, QUICK.hold_period)
    for call in calls:
        (candidate,) = call.args
        results = call.result
        assert encode(results) == encode(
            analyze_quick_acquisition_with_business_plan(
                candidate, business_plan=OWNER_EXPENSE_ONLY
            )
        )
        bare = analyze_quick_acquisition_with_business_plan(candidate, business_plan=BusinessPlan())
        assert results.closing_project_capital == 0.0
        assert results.project_capital_by_year == (0.0,) * 5
        assert results.owner_expenses_by_year == (50_000.0,) * 5
        assert encode(results.noi_by_year) == encode(bare.noi_by_year)
        assert encode(results.dscr_by_year) == encode(bare.dscr_by_year)
        assert bits(results.exit_value) == bits(bare.exit_value)
        assert results.levered_cash_on_cash_by_year != bare.levered_cash_on_cash_by_year
        assert results.unlevered_cash_yield_by_year != bare.unlevered_cash_yield_by_year
        assert results.equity_multiple < bare.equity_multiple


def test_r9_an_owner_expense_alone_threads_through_break_even() -> None:
    result = solve_max_purchase_price(
        QUICK, target_equity_multiple=1.6, business_plan=OWNER_EXPENSE_ONLY
    )
    assert bits(result.solved_metric_value) == bits(
        quick_with_plan(
            {"purchase_price": result.solved_assumption_value}, OWNER_EXPENSE_ONLY
        ).equity_multiple
    )
    unplanned = solve_max_purchase_price(QUICK, target_equity_multiple=1.6)
    assert result.solved_assumption_value < unplanned.solved_assumption_value

    detailed = solve_detailed_max_purchase_price(
        TERMS, DETAILED, target_equity_multiple=1.8, business_plan=OWNER_EXPENSE_ONLY
    )
    detailed_unplanned = solve_detailed_max_purchase_price(
        TERMS, DETAILED, target_equity_multiple=1.8
    )
    assert detailed.solved_assumption_value < detailed_unplanned.solved_assumption_value

    # DSCR-driven questions are untouched by an owner expense.
    assert solve_max_interest_rate(
        QUICK, target_headline_dscr=1.25, business_plan=OWNER_EXPENSE_ONLY
    ) == solve_max_interest_rate(QUICK, target_headline_dscr=1.25)
    assert solve_detailed_max_interest_rate(
        TERMS, DETAILED, target_headline_dscr=1.25, business_plan=OWNER_EXPENSE_ONLY
    ) == solve_detailed_max_interest_rate(TERMS, DETAILED, target_headline_dscr=1.25)


def test_r9_an_owner_expense_alone_threads_through_lease_level_sensitivity() -> None:
    run = {"assumption": "exit_cap_rate", "values": (0.06, 0.07)}
    result = lease_level_one_way(**run, metric="equity_multiple", business_plan=OWNER_EXPENSE_ONLY)

    assert_one_way_is_independent(
        result, lambda changes: lease_level_with_plan(changes, OWNER_EXPENSE_ONLY)
    )
    assert all(
        a != b
        for a, b in zip(
            result.metric_values,
            lease_level_one_way(**run, metric="equity_multiple").metric_values,
            strict=True,
        )
    )
    assert encode(lease_level_one_way(**run, metric="exit_value", business_plan=OWNER_EXPENSE_ONLY)) == (
        encode(lease_level_one_way(**run, metric="exit_value"))
    )


# =============================================================================
# R10 -- post-hold capital only
# =============================================================================


@pytest.mark.parametrize("metric", SUPPORTED_METRICS)
def test_r10_post_hold_capital_is_neutral_in_quick_and_detailed_sensitivity(metric: str) -> None:
    one_way = {"assumption": "purchase_price", "values": (18_000_000.0, 22_000_000.0), "metric": metric}
    two_way = {
        "row_assumption": "purchase_price",
        "row_values": (18_000_000.0, 22_000_000.0),
        "column_assumption": "ltv",
        "column_values": (0.30, 0.50),
        "metric": metric,
    }

    assert encode(run_one_way_sensitivity(QUICK, **one_way, business_plan=POST_HOLD_ONLY)) == (
        encode(run_one_way_sensitivity(QUICK, **one_way))
    )
    assert encode(run_two_way_sensitivity(QUICK, **two_way, business_plan=POST_HOLD_ONLY)) == (
        encode(run_two_way_sensitivity(QUICK, **two_way))
    )
    assert encode(
        run_detailed_one_way_sensitivity(TERMS, DETAILED, **one_way, business_plan=POST_HOLD_ONLY)
    ) == encode(run_detailed_one_way_sensitivity(TERMS, DETAILED, **one_way))


def test_r10_post_hold_capital_is_neutral_in_presets_and_break_even() -> None:
    assert encode(build_standard_presets(QUICK, business_plan=POST_HOLD_ONLY)) == encode(
        build_standard_presets(QUICK)
    )
    assert encode(build_standard_detailed_presets(TERMS, DETAILED, business_plan=POST_HOLD_ONLY)) == (
        encode(build_standard_detailed_presets(TERMS, DETAILED))
    )
    targets = {"target_levered_irr": 0.10, "target_headline_dscr": 1.25, "target_equity_multiple": 1.6}
    for hurdle in (analyst.ReturnHurdleMetric.LEVERED_IRR, analyst.ReturnHurdleMetric.EQUITY_MULTIPLE):
        assert encode(
            build_standard_break_even_analysis(
                QUICK, **targets, return_hurdle_metric=hurdle, business_plan=POST_HOLD_ONLY
            )
        ) == encode(build_standard_break_even_analysis(QUICK, **targets, return_hurdle_metric=hurdle))
        assert encode(
            build_standard_detailed_break_even_analysis(
                TERMS, DETAILED, **targets, return_hurdle_metric=hurdle,
                business_plan=POST_HOLD_ONLY,
            )
        ) == encode(
            build_standard_detailed_break_even_analysis(
                TERMS, DETAILED, **targets, return_hurdle_metric=hurdle
            )
        )

    # Only the disclosure moves.
    assert quick_with_plan({}, POST_HOLD_ONLY).post_hold_project_capital == 2_000_000.0


@pytest.mark.parametrize("metric", ("levered_irr", "equity_multiple"))
def test_r10_post_hold_capital_is_neutral_in_lease_level_sensitivity(metric: str) -> None:
    run = {"assumption": "renewal_probability", "values": (0.2, 0.8), "metric": metric}
    assert encode(lease_level_one_way(**run, business_plan=LL_POST_HOLD_ONLY)) == encode(
        lease_level_one_way(**run)
    )
    assert lease_level_with_plan({}, LL_POST_HOLD_ONLY).post_hold_project_capital == 2_000_000.0


# =============================================================================
# R11 -- the empty plan reproduces every legacy call, in process
# (the ba804ca comparison is tests/test_d6_4_neutral_secondary_analysis_oracle.py)
# =============================================================================

_TWO_WAY = {
    "row_assumption": "purchase_price",
    "row_values": (18_000_000.0, 22_000_000.0),
    "column_assumption": "exit_cap_rate",
    "column_values": (0.055, 0.075),
    "metric": "levered_irr",
}
_SEARCH = {
    "assumption": "exit_cap_rate",
    "metric": "levered_irr",
    "target": 0.12,
    "direction": BreakEvenDirection.MAXIMUM,
    "lower_bound": 0.05,
    "upper_bound": 0.10,
}
_BUNDLE = {"target_levered_irr": 0.10, "target_headline_dscr": 1.25}

_NEUTRAL_CALLS: dict[str, Callable[..., object]] = {
    "run_one_way_sensitivity": lambda **kw: run_one_way_sensitivity(
        QUICK, assumption="exit_cap_rate", values=(0.055, 0.075), metric="levered_irr", **kw
    ),
    "run_two_way_sensitivity": lambda **kw: run_two_way_sensitivity(QUICK, **_TWO_WAY, **kw),
    "build_exit_cap_noi_growth_preset": lambda **kw: build_exit_cap_noi_growth_preset(QUICK, **kw),
    "build_purchase_price_exit_cap_preset": lambda **kw: build_purchase_price_exit_cap_preset(
        QUICK, **kw
    ),
    "build_interest_rate_ltv_preset": lambda **kw: build_interest_rate_ltv_preset(
        QUICK, metric="headline_dscr", **kw
    ),
    "build_standard_presets": lambda **kw: build_standard_presets(QUICK, **kw),
    "run_detailed_one_way_sensitivity": lambda **kw: run_detailed_one_way_sensitivity(
        TERMS, DETAILED, assumption="ltv", values=(0.3, 0.5), metric="equity_multiple", **kw
    ),
    "run_detailed_two_way_sensitivity": lambda **kw: run_detailed_two_way_sensitivity(
        TERMS, DETAILED, **_TWO_WAY, **kw
    ),
    "build_detailed_purchase_price_exit_cap_preset": (
        lambda **kw: build_detailed_purchase_price_exit_cap_preset(TERMS, DETAILED, **kw)
    ),
    "build_detailed_interest_rate_ltv_preset": (
        lambda **kw: build_detailed_interest_rate_ltv_preset(TERMS, DETAILED, **kw)
    ),
    "build_standard_detailed_presets": lambda **kw: build_standard_detailed_presets(
        TERMS, DETAILED, **kw
    ),
    "run_lease_level_one_way_sensitivity": lambda **kw: lease_level_one_way(
        assumption="expense_growth", values=(0.02, 0.04), metric="levered_irr", **kw
    ),
    "run_lease_level_two_way_sensitivity": lambda **kw: lease_level_two_way(
        row_assumption="market_rent_psf", row_values=(30.0, 42.0),
        column_assumption="recoverable_expense_ratio", column_values=(0.8, 1.0),
        metric="equity_multiple", **kw,
    ),
    "solve_break_even_threshold": lambda **kw: solve_break_even_threshold(QUICK, **_SEARCH, **kw),
    "solve_max_purchase_price": lambda **kw: solve_max_purchase_price(
        QUICK, target_levered_irr=0.12, **kw
    ),
    "solve_max_exit_cap_rate": lambda **kw: solve_max_exit_cap_rate(
        QUICK, target_equity_multiple=1.6, **kw
    ),
    "solve_min_noi_growth": lambda **kw: solve_min_noi_growth(QUICK, target_levered_irr=0.12, **kw),
    "solve_max_interest_rate": lambda **kw: solve_max_interest_rate(
        QUICK, target_headline_dscr=1.25, **kw
    ),
    "solve_min_current_noi": lambda **kw: solve_min_current_noi(
        QUICK, target_headline_dscr=1.25, **kw
    ),
    "build_standard_break_even_analysis": lambda **kw: build_standard_break_even_analysis(
        QUICK, **_BUNDLE, **kw
    ),
    "solve_detailed_break_even_threshold": lambda **kw: solve_detailed_break_even_threshold(
        TERMS, DETAILED, **_SEARCH, **kw
    ),
    "solve_detailed_max_purchase_price": lambda **kw: solve_detailed_max_purchase_price(
        TERMS, DETAILED, target_levered_irr=0.15, **kw
    ),
    "solve_detailed_max_exit_cap_rate": lambda **kw: solve_detailed_max_exit_cap_rate(
        TERMS, DETAILED, target_equity_multiple=1.8, **kw
    ),
    "solve_detailed_max_interest_rate": lambda **kw: solve_detailed_max_interest_rate(
        TERMS, DETAILED, target_headline_dscr=1.25, **kw
    ),
    "build_standard_detailed_break_even_analysis": (
        lambda **kw: build_standard_detailed_break_even_analysis(TERMS, DETAILED, **_BUNDLE, **kw)
    ),
    "build_analysis_context": lambda **kw: analyst.build_analysis_context(
        QUICK, **AI_TARGETS, **kw
    ),
    "build_detailed_analysis_context": lambda **kw: analyst.build_detailed_analysis_context(
        TERMS, DETAILED, **AI_TARGETS, **kw
    ),
}


@pytest.mark.parametrize("name", sorted(_NEUTRAL_CALLS))
def test_r11_the_empty_plan_reproduces_the_legacy_call_bit_for_bit(name: str) -> None:
    call = _NEUTRAL_CALLS[name]
    assert encode(call(business_plan=BusinessPlan())) == encode(call())


def test_r11_the_neutral_table_covers_every_plan_aware_public_function() -> None:
    """Each public function that now takes ``business_plan`` is exercised by
    the table above, so no neutral path goes unchecked."""

    import anchor.analysis as analysis_package

    plan_aware = {
        name
        for name in analysis_package.__all__
        if callable(function := getattr(analysis_package, name))
        and not isinstance(function, type)
        and "business_plan" in inspect.signature(function).parameters
        and not name.endswith("_with_business_plan")
    }
    plan_aware |= {
        name
        for name in ("build_analysis_context", "build_detailed_analysis_context")
        if "business_plan" in inspect.signature(getattr(analyst, name)).parameters
    }
    assert plan_aware == set(_NEUTRAL_CALLS)


@pytest.mark.parametrize(
    "name", ("build_analysis_context", "build_detailed_analysis_context")
)
def test_r11_the_ai_prompt_is_unchanged_for_a_caller_with_no_plan(name: str) -> None:
    call = _NEUTRAL_CALLS[name]
    assert build_user_prompt(call(business_plan=BusinessPlan())) == build_user_prompt(call())


# =============================================================================
# R12 -- an undefined IRR stays undefined; break-even policy is unchanged
# =============================================================================


def test_r12_the_plan_leaves_every_sensitivity_cell_irr_undefined() -> None:
    values = (7_500_000.0, 10_000_000.0, 12_500_000.0)
    result = run_one_way_sensitivity(
        SMALL_QUICK, assumption="purchase_price", values=values, metric="levered_irr",
        business_plan=IRR_UNDEFINED,
    )

    assert result.baseline_metric_value is None
    assert result.metric_values == (None, None, None)
    for value in values:
        independent = quick_with_plan({"purchase_price": value}, IRR_UNDEFINED, base=SMALL_QUICK)
        assert independent.levered_irr is None
        assert independent.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES

    # The undefined IRR is the plan's: without it every cell is defined.
    assert None not in run_one_way_sensitivity(
        SMALL_QUICK, assumption="purchase_price", values=values, metric="levered_irr"
    ).metric_values

    grid = run_two_way_sensitivity(
        SMALL_QUICK,
        row_assumption="purchase_price",
        row_values=values,
        column_assumption="exit_cap_rate",
        column_values=(0.055, 0.075),
        metric="levered_irr",
        business_plan=IRR_UNDEFINED,
    )
    assert set(all_cells(grid)) == {None}

    # The equity multiple is still defined, and still the independent analysis.
    multiple = run_one_way_sensitivity(
        SMALL_QUICK, assumption="purchase_price", values=values, metric="equity_multiple",
        business_plan=IRR_UNDEFINED,
    )
    assert_one_way_is_independent(
        multiple, lambda changes: quick_with_plan(changes, IRR_UNDEFINED, base=SMALL_QUICK)
    )


def test_r12_an_undefined_irr_is_never_a_qualifying_break_even_candidate() -> None:
    """``_meets_hurdle(None)`` is unchanged: a candidate whose IRR the plan's
    multiple sign changes leave undefined fails the hurdle, so an IRR question
    over a range where every candidate is undefined is NO_SOLUTION_IN_RANGE --
    no new status, no reinterpretation."""

    calls = engine_calls(
        break_even_module,
        "analyze_acquisition",
        lambda: solve_max_purchase_price(
            SMALL_QUICK, target_levered_irr=0.05, business_plan=IRR_UNDEFINED
        ),
    )
    result = solve_max_purchase_price(
        SMALL_QUICK, target_levered_irr=0.05, business_plan=IRR_UNDEFINED
    )

    assert result.status is BreakEvenStatus.NO_SOLUTION_IN_RANGE
    assert result.solved_assumption_value is None
    assert result.solved_metric_value is None
    assert result.baseline_metric_value is None
    assert_one_schedule(calls, IRR_UNDEFINED, SMALL_QUICK.hold_period)
    for call in calls:
        assert call.result.levered_irr is None
        assert call.result.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES

    # Without the plan the same question is answered ...
    assert solve_max_purchase_price(SMALL_QUICK, target_levered_irr=0.05).status is (
        BreakEvenStatus.SOLVED
    )
    # ... and under the plan an equity-multiple hurdle still is.
    assert solve_max_purchase_price(
        SMALL_QUICK, target_equity_multiple=1.2, business_plan=IRR_UNDEFINED
    ).status is BreakEvenStatus.SOLVED

    detailed = solve_detailed_max_purchase_price(
        TERMS, DETAILED, target_levered_irr=0.05, business_plan=IRR_UNDEFINED
    )
    assert detailed.status is BreakEvenStatus.NO_SOLUTION_IN_RANGE
    assert detailed.solved_assumption_value is None


def test_r12_lease_level_cells_carry_the_undefined_irr_too() -> None:
    result = lease_level_one_way(
        assumption="market_rent_psf", values=(30.0, 42.0), metric="levered_irr",
        business_plan=IRR_UNDEFINED,
    )
    assert result.metric_values == (None, None)
    independent = lease_level_with_plan({"market_rent_psf": 30.0}, IRR_UNDEFINED)
    assert independent.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES


# =============================================================================
# Part W -- the plan is constant across every candidate and never mutated
# =============================================================================

#: Capital Item A at month 18 for 1M, Owner Expense B at 50k a year.
PLAN_A_B = BusinessPlan(
    capital_items=(cap("A", 18, 1_000_000.0),),
    owner_expense_items=(expense("B", 50_000.0),),
)
#: The same economics under different identifiers, descriptions and categories.
PLAN_A_B_RELABELLED = BusinessPlan(
    capital_items=(
        cap(
            "roof-2028",
            18,
            1_000_000.0,
            description="Roof replacement",
            category=CapitalItemCategory.BUILDING_SYSTEMS,
        ),
    ),
    owner_expense_items=(
        expense(
            "legal",
            50_000.0,
            description="Partnership legal",
            category=OwnerExpenseCategory.LEGAL_PARTNERSHIP,
        ),
    ),
)

_PATHS = {
    "quick-two-way": (
        sensitivity_module,
        "analyze_acquisition",
        QUICK.hold_period,
        lambda plan: run_two_way_sensitivity(QUICK, **_TWO_WAY, business_plan=plan),
    ),
    "detailed-one-way": (
        sensitivity_module,
        "analyze_detailed_acquisition_with_projection",
        TERMS.hold_period,
        lambda plan: run_detailed_one_way_sensitivity(
            TERMS, DETAILED, assumption="exit_cap_rate", values=(0.055, 0.075),
            metric="equity_multiple", business_plan=plan,
        ),
    ),
    "lease-level-one-way": (
        lease_level_module,
        "analyze_lease_level_acquisition_with_projection",
        LL_HOLD,
        lambda plan: lease_level_one_way(
            assumption="renewal_probability", values=(0.2, 0.8), metric="equity_multiple",
            business_plan=plan,
        ),
    ),
    "quick-break-even": (
        break_even_module,
        "analyze_acquisition",
        QUICK.hold_period,
        lambda plan: solve_max_purchase_price(QUICK, target_equity_multiple=1.6, business_plan=plan),
    ),
    "detailed-break-even": (
        break_even_module,
        "analyze_detailed_acquisition_with_projection",
        TERMS.hold_period,
        lambda plan: solve_detailed_max_exit_cap_rate(
            TERMS, DETAILED, target_equity_multiple=1.8, business_plan=plan
        ),
    ),
}


@pytest.mark.parametrize("path", sorted(_PATHS))
def test_w_every_candidate_carries_month_18_one_million_and_fifty_thousand(path: str) -> None:
    module, name, hold_period, run = _PATHS[path]
    before = copy.deepcopy(PLAN_A_B)

    calls = engine_calls(module, name, lambda: run(PLAN_A_B))

    assert len(calls) > 1
    assert_one_schedule(calls, PLAN_A_B, hold_period)
    schedule = calls[0].kwargs["owner_capital"]
    assert schedule.closing_project_capital == 0.0
    assert schedule.post_hold_project_capital == 0.0
    # Month 18 is Year 2, at 1M, in every candidate.
    assert schedule.project_capital_by_year == tuple(
        1_000_000.0 if year == 2 else 0.0 for year in range(1, hold_period + 1)
    )
    assert schedule.owner_expenses_by_year == (50_000.0,) * hold_period
    # No candidate mutated the plan.
    assert PLAN_A_B == before


@pytest.mark.parametrize("path", sorted(_PATHS))
def test_w_identifiers_descriptions_and_categories_move_nothing(path: str) -> None:
    _, _, _, run = _PATHS[path]
    assert encode(run(PLAN_A_B)) == encode(run(PLAN_A_B_RELABELLED))


# =============================================================================
# AI -- mechanical threading only (D6.8 owns grounding)
# =============================================================================


def test_ai_the_quick_context_carries_one_plan_into_every_calculation() -> None:
    context = analyst.build_analysis_context(QUICK, **AI_TARGETS, business_plan=MATERIAL)

    assert context.results == analyze_quick_acquisition_with_business_plan(
        QUICK, business_plan=MATERIAL
    )
    assert context.sensitivities == build_standard_presets(QUICK, business_plan=MATERIAL)
    assert context.break_even == build_standard_break_even_analysis(
        QUICK,
        target_levered_irr=0.10,
        target_headline_dscr=1.25,
        target_equity_multiple=1.6,
        business_plan=MATERIAL,
    )

    bare = analyst.build_analysis_context(QUICK, **AI_TARGETS)
    assert context.results != bare.results
    assert context.sensitivities != bare.sensitivities
    assert context.break_even != bare.break_even


def test_ai_the_detailed_context_carries_one_plan_into_every_calculation() -> None:
    context = analyst.build_detailed_analysis_context(
        TERMS, DETAILED, **AI_TARGETS, business_plan=MATERIAL
    )
    envelope = analyze_detailed_acquisition_with_business_plan(
        TERMS, DETAILED, business_plan=MATERIAL
    )

    assert context.results == envelope.results
    assert context.operating_projection == envelope.operating_projection
    assert context.sensitivities == build_standard_detailed_presets(
        TERMS, DETAILED, business_plan=MATERIAL
    )
    assert context.break_even == build_standard_detailed_break_even_analysis(
        TERMS,
        DETAILED,
        target_levered_irr=0.10,
        target_headline_dscr=1.25,
        target_equity_multiple=1.6,
        business_plan=MATERIAL,
    )

    bare = analyst.build_detailed_analysis_context(TERMS, DETAILED, **AI_TARGETS)
    assert context.results != bare.results
    assert context.sensitivities != bare.sensitivities
    assert context.break_even != bare.break_even


def test_ai_an_owner_expense_reaches_the_contexts_cash_on_cash_and_not_its_noi() -> None:
    context = analyst.build_analysis_context(QUICK, **AI_TARGETS, business_plan=OWNER_EXPENSE_ONLY)
    bare = analyst.build_analysis_context(QUICK, **AI_TARGETS)

    assert context.results.levered_cash_on_cash_by_year != bare.results.levered_cash_on_cash_by_year
    assert context.results.noi_by_year == bare.results.noi_by_year
    assert context.results.dscr_by_year == bare.results.dscr_by_year
    assert context.sensitivities.interest_rate_ltv_dscr == bare.sensitivities.interest_rate_ltv_dscr


@pytest.mark.parametrize(
    "generate, build, args",
    [
        (analyst.generate_ai_analysis, analyst.build_analysis_context, (QUICK,)),
        (
            analyst.generate_detailed_ai_analysis,
            analyst.build_detailed_analysis_context,
            (TERMS, DETAILED),
        ),
    ],
    ids=["quick", "detailed"],
)
def test_ai_generate_hands_its_plan_to_the_context(generate, build, args) -> None:
    with patch.object(
        analyst,
        "_generate_from_context",
        side_effect=lambda context, provider=None: context,
    ):
        produced = generate(*args, **AI_TARGETS, business_plan=MATERIAL)

    assert produced == build(*args, **AI_TARGETS, business_plan=MATERIAL)


def test_ai_the_lease_level_arm_still_runs_no_analysis_and_names_its_plan() -> None:
    """Lease-Level AI interprets the already-computed result the analyst
    approved, so there is no analysis to thread a plan through (D5.8, D6.4).

    **D6.8** grounds the model in that result's Business Plan, so the arm now
    takes the plan -- required and keyword-only, because only the caller knows
    which plan produced the results it hands over. It still runs no analysis:
    the plan is carried to the context, never used to compute anything here."""

    for function in (
        analyst.build_lease_level_analysis_context,
        analyst.generate_lease_level_ai_analysis,
    ):
        parameter = inspect.signature(function).parameters["business_plan"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty

    tree = ast.parse(inspect.getsource(analyst.build_lease_level_analysis_context))
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert called == {"AnalysisContext"}
