"""D6.4 neutral secondary-analysis oracle runner (not a test module; see
``tests/test_d6_4_neutral_secondary_analysis_oracle.py``).

Usage: ``python _d6_4_oracle_cases.py <repo_root> <out.json>``

Runs a fixed Quick / Detailed / Lease-Level corpus of sensitivity runs, preset
bundles, break-even searches and AI Analyst contexts (with their user prompts)
against ``<repo_root>/src`` -- never against whatever ``anchor`` happens to be
installed -- and writes every result encoded bit-exactly with ``float.hex`` (so
the last bit and the sign of zero are visible).

When the tree's secondary-analysis functions take ``business_plan`` (D6.4),
each case is also run with ``business_plan=BusinessPlan()`` and stored as
``<case>#bp``. The runner imports only names that existed at ba804ca, so it runs
unchanged against the pre-D6.4 tree.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import sys
from collections.abc import Callable
from datetime import date
from enum import Enum
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2])
sys.path.insert(0, str(root / "src"))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from anchor.ai import analyst  # noqa: E402
from anchor.ai.prompts import build_user_prompt  # noqa: E402
from anchor.analysis import (  # noqa: E402
    DETAILED_SUPPORTED_ASSUMPTIONS,
    LEASE_LEVEL_SUPPORTED_ASSUMPTIONS,
    SUPPORTED_ASSUMPTIONS,
    SUPPORTED_METRICS,
    BreakEvenDirection,
    ReturnHurdleMetric,
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
)
from anchor.business_plan import BusinessPlan  # noqa: E402
from anchor.contracts import (  # noqa: E402
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
)
from anchor.leasing import (  # noqa: E402
    EscalationBasis,
    InitialVacancyAssumptions,
    InitialVacancyStrategy,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    Suite,
)

HAS_BP = "business_plan" in inspect.signature(run_one_way_sensitivity).parameters


def encode(value: object) -> object:
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return repr(value)


# =============================================================================
# Fixtures (the D6.2 oracle's deals)
# =============================================================================


def quick(**overrides: object) -> AcquisitionInputs:
    base: dict[str, object] = dict(
        purchase_price=50_000_000.0, current_noi=2_500_000.0, occupancy=0.95,
        noi_growth=0.03, hold_period=5, exit_cap_rate=0.055, ltv=0.65,
        interest_rate=0.0525, amortization=30, acquisition_cost_pct=0.0,
        financing_fee_pct=0.0, disposition_cost_pct=0.0, annual_capex_reserve=0.0,
        io_period=0,
    )
    base.update(overrides)
    return AcquisitionInputs(**base)  # type: ignore[arg-type]


def terms(**overrides: object) -> AcquisitionTerms:
    base: dict[str, object] = dict(
        purchase_price=10_000_000.0, hold_period=5, exit_cap_rate=0.065, ltv=0.60,
        interest_rate=0.05, amortization=30, acquisition_cost_pct=0.02,
        financing_fee_pct=0.01, disposition_cost_pct=0.025, annual_capex_reserve=50_000.0,
        io_period=2,
    )
    base.update(overrides)
    return AcquisitionTerms(**base)  # type: ignore[arg-type]


DETAILED_OPERATING = DetailedOperatingInputs(
    gross_potential_rent=800_000.0, other_income=20_000.0, vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0, insurance=20_000.0, utilities=25_000.0,
    repairs_maintenance=20_000.0, other_operating_expenses=16_000.0,
    management_fee_pct=0.05, revenue_growth=0.03, expense_growth=0.03,
)

LL_TERMS = AcquisitionTerms(
    purchase_price=6_000_000.0, hold_period=5, exit_cap_rate=0.065, ltv=0.5,
    interest_rate=0.055, amortization=30, acquisition_cost_pct=0.02, financing_fee_pct=0.01,
    disposition_cost_pct=0.02, annual_capex_reserve=50_000.0, io_period=1,
)
LL_PROPERTY = LeaseLevelPropertyInputs(
    analysis_start_date=date(2027, 1, 1), rentable_area_sf=20_000.0
)
LL_OPERATING = LeaseLevelOperatingInputs(
    other_income=50_000.0, other_income_growth=0.02, credit_loss_pct=0.01,
    property_taxes=200_000.0, insurance=30_000.0, utilities=60_000.0,
    repairs_maintenance=40_000.0, other_operating_expenses=20_000.0,
    management_fee_pct=0.03, expense_growth=0.03, recoverable_expense_ratio=0.8,
)
LL_MARKET = MarketLeasingAssumptions(
    market_rent_psf=30.0, market_rent_growth=0.03, renewal_rent_psf=None,
    renewal_rent_spread=0.0, renewal_term_months=60, successor_escalation_pct=0.03,
    renewal_downtime_months=2.0, renewal_free_rent_months=1.0, new_term_months=60,
    new_downtime_months=6.0, new_free_rent_months=2.0, renewal_ti_psf=20.0,
    new_ti_psf=40.0,
    leasing_commission_method=LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT,
    renewal_lc_pct=0.03, new_lc_pct=0.06, renewal_probability=0.7,
    renewal_lease_type=LeaseType.NNN, renewal_recovery_basis=None,
    renewal_expense_stop_psf=None, new_lease_type=LeaseType.NNN,
    new_recovery_basis=None, new_expense_stop_psf=None,
)
LL_SUITES = (
    Suite(suite_id="100", suite_area_sf=12_000.0),
    Suite(
        suite_id="200",
        suite_area_sf=8_000.0,
        initial_vacancy=InitialVacancyAssumptions(
            strategy=InitialVacancyStrategy.MARKET_LEASE_UP, initial_lease_up_months=6.0
        ),
    ),
)
LL_LEASES = (
    Lease(
        lease_id="L-100", suite_id="100", leased_area_sf=12_000.0,
        rent_commencement_date=date(2024, 1, 1), lease_expiration_date=date(2029, 6, 30),
        base_rent_psf=28.0, escalation_pct=0.03,
        escalation_basis=EscalationBasis.LEASE_ANNIVERSARY, lease_type=LeaseType.NNN,
        tenant_name="Anchor Tenant",
    ),
)

QUICK_CASES = {
    "Q1_golden": quick(),
    "Q2_costs_capex_io": quick(
        purchase_price=10_000_000.0, current_noi=600_000.0, exit_cap_rate=0.065, ltv=0.60,
        interest_rate=0.05, acquisition_cost_pct=0.02, financing_fee_pct=0.01,
        disposition_cost_pct=0.025, annual_capex_reserve=50_000.0, io_period=2,
    ),
    "Q4_neg_growth_zero_rate_hold10": quick(
        hold_period=10, noi_growth=-0.02, interest_rate=0.0, amortization=25, ltv=0.8,
        financing_fee_pct=0.0125, disposition_cost_pct=0.02, annual_capex_reserve=333_333.33,
        io_period=1,
    ),
}
DETAILED_CASES = {
    "D1_costs_capex_io": terms(),
    "D2_hold7_all_cash": terms(hold_period=7, ltv=0.0, io_period=0),
}

# =============================================================================
# The corpus
# =============================================================================

CASES: dict[str, Callable[..., object]] = {}


def case(name: str, run: Callable[..., object]) -> None:
    assert name not in CASES, name
    CASES[name] = run


_MULTIPLIERS = (0.9, 1.0, 1.1)

for name, inputs in QUICK_CASES.items():
    for assumption in SUPPORTED_ASSUMPTIONS:
        values = tuple(getattr(inputs, assumption) * m for m in _MULTIPLIERS)
        for metric in SUPPORTED_METRICS:
            case(
                f"quick/{name}/one_way/{assumption}/{metric}",
                lambda i=inputs, a=assumption, v=values, m=metric, **kw: run_one_way_sensitivity(
                    i, assumption=a, values=v, metric=m, **kw
                ),
            )
    for metric in ("levered_irr", "equity_multiple", "headline_dscr"):
        case(
            f"quick/{name}/two_way/price_x_exit_cap/{metric}",
            lambda i=inputs, m=metric, **kw: run_two_way_sensitivity(
                i,
                row_assumption="purchase_price",
                row_values=(i.purchase_price * 0.9, i.purchase_price * 1.1),
                column_assumption="exit_cap_rate",
                column_values=(i.exit_cap_rate - 0.005, i.exit_cap_rate + 0.005),
                metric=m,
                **kw,
            ),
        )
    case(f"quick/{name}/presets", lambda i=inputs, **kw: build_standard_presets(i, **kw))
    for hurdle in ReturnHurdleMetric:
        case(
            f"quick/{name}/break_even/{hurdle.value}",
            lambda i=inputs, h=hurdle, **kw: build_standard_break_even_analysis(
                i,
                target_levered_irr=0.08,
                target_headline_dscr=1.25,
                target_equity_multiple=1.5,
                return_hurdle_metric=h,
                **kw,
            ),
        )
    case(
        f"quick/{name}/threshold",
        lambda i=inputs, **kw: solve_break_even_threshold(
            i,
            assumption="exit_cap_rate",
            metric="equity_multiple",
            target=1.3,
            direction=BreakEvenDirection.MAXIMUM,
            lower_bound=max(0.005, i.exit_cap_rate - 0.02),
            upper_bound=i.exit_cap_rate + 0.04,
            **kw,
        ),
    )
    case(
        f"quick/{name}/ai_context",
        lambda i=inputs, **kw: analyst.build_analysis_context(
            i, target_levered_irr=0.10, target_equity_multiple=1.5, target_headline_dscr=1.2, **kw
        ),
    )
    case(
        f"quick/{name}/ai_user_prompt",
        lambda i=inputs, **kw: build_user_prompt(
            analyst.build_analysis_context(
                i, target_levered_irr=0.10, target_equity_multiple=1.5,
                target_headline_dscr=1.2, **kw,
            )
        ),
    )

for name, case_terms in DETAILED_CASES.items():
    for assumption in DETAILED_SUPPORTED_ASSUMPTIONS:
        values = tuple(getattr(case_terms, assumption) * m for m in _MULTIPLIERS)
        for metric in SUPPORTED_METRICS:
            case(
                f"detailed/{name}/one_way/{assumption}/{metric}",
                lambda t=case_terms, a=assumption, v=values, m=metric, **kw: (
                    run_detailed_one_way_sensitivity(
                        t, DETAILED_OPERATING, assumption=a, values=v, metric=m, **kw
                    )
                ),
            )
    for metric in ("levered_irr", "equity_multiple"):
        case(
            f"detailed/{name}/two_way/price_x_exit_cap/{metric}",
            lambda t=case_terms, m=metric, **kw: run_detailed_two_way_sensitivity(
                t,
                DETAILED_OPERATING,
                row_assumption="purchase_price",
                row_values=(t.purchase_price * 0.9, t.purchase_price * 1.1),
                column_assumption="exit_cap_rate",
                column_values=(t.exit_cap_rate - 0.005, t.exit_cap_rate + 0.005),
                metric=m,
                **kw,
            ),
        )
    case(
        f"detailed/{name}/presets",
        lambda t=case_terms, **kw: build_standard_detailed_presets(t, DETAILED_OPERATING, **kw),
    )
    for hurdle in ReturnHurdleMetric:
        case(
            f"detailed/{name}/break_even/{hurdle.value}",
            lambda t=case_terms, h=hurdle, **kw: build_standard_detailed_break_even_analysis(
                t,
                DETAILED_OPERATING,
                target_levered_irr=0.08,
                target_headline_dscr=1.25,
                target_equity_multiple=1.5,
                return_hurdle_metric=h,
                **kw,
            ),
        )
    case(
        f"detailed/{name}/threshold",
        lambda t=case_terms, **kw: solve_detailed_break_even_threshold(
            t,
            DETAILED_OPERATING,
            assumption="purchase_price",
            metric="levered_irr",
            target=0.08,
            direction=BreakEvenDirection.MAXIMUM,
            lower_bound=t.purchase_price * 0.5,
            upper_bound=t.purchase_price * 1.5,
            **kw,
        ),
    )
    case(
        f"detailed/{name}/ai_context",
        lambda t=case_terms, **kw: analyst.build_detailed_analysis_context(
            t, DETAILED_OPERATING, target_levered_irr=0.10, target_equity_multiple=1.5,
            target_headline_dscr=1.2, **kw,
        ),
    )
    case(
        f"detailed/{name}/ai_user_prompt",
        lambda t=case_terms, **kw: build_user_prompt(
            analyst.build_detailed_analysis_context(
                t, DETAILED_OPERATING, target_levered_irr=0.10, target_equity_multiple=1.5,
                target_headline_dscr=1.2, **kw,
            )
        ),
    )


def _lease_level_baseline(assumption: str) -> float:
    for record in (LL_TERMS, LL_MARKET, LL_OPERATING):
        if hasattr(record, assumption):
            return getattr(record, assumption)
    raise KeyError(assumption)


_LL_COMMON = dict(market_leasing=LL_MARKET, operating_inputs=LL_OPERATING)
for assumption in LEASE_LEVEL_SUPPORTED_ASSUMPTIONS:
    baseline = _lease_level_baseline(assumption)
    values = (baseline * 0.9, baseline * 1.1)
    for metric in ("levered_irr", "equity_multiple"):
        case(
            f"lease_level/one_way/{assumption}/{metric}",
            lambda a=assumption, v=values, m=metric, **kw: run_lease_level_one_way_sensitivity(
                LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES, **_LL_COMMON,
                assumption=a, values=v, metric=m, **kw,
            ),
        )
case(
    "lease_level/two_way/market_rent_x_expense_growth/equity_multiple",
    lambda **kw: run_lease_level_two_way_sensitivity(
        LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES, **_LL_COMMON,
        row_assumption="market_rent_psf", row_values=(27.0, 33.0),
        column_assumption="expense_growth", column_values=(0.02, 0.04),
        metric="equity_multiple", **kw,
    ),
)
case(
    "lease_level/two_way/price_x_renewal/levered_irr",
    lambda **kw: run_lease_level_two_way_sensitivity(
        LL_TERMS, LL_PROPERTY, LL_SUITES, LL_LEASES, **_LL_COMMON,
        row_assumption="purchase_price", row_values=(5_400_000.0, 6_600_000.0),
        column_assumption="renewal_probability", column_values=(0.4, 0.9),
        metric="levered_irr", **kw,
    ),
)


def run_case(run: Callable[..., object], **kwargs: object) -> object:
    try:
        return encode(run(**kwargs))
    except Exception as error:  # an input the corpus cannot underwrite fails identically
        return {"raises": type(error).__name__, "message": str(error)}


output: dict[str, object] = {"_has_bp": HAS_BP}
for name, run in CASES.items():
    output[name] = run_case(run)
    if HAS_BP:
        output[name + "#bp"] = run_case(run, business_plan=BusinessPlan())

out_path.write_text(json.dumps(output, sort_keys=True), encoding="utf-8")
