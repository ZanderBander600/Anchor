"""Phase 6 Gate D6.2 -- the Business Plan entry points for all three operating
modes.

Restates ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Section 13; that
document governs on any discrepancy.

**This module is where a Business Plan becomes an engine input, and it is the
only one.** The dependency direction is::

    BusinessPlan
        |
    resolve_business_plan(..., hold_period=<this analysis's hold>)
        |
    OwnerCapitalSchedule                  generic: closing and annual dollars
        |
    the mode's existing entry point       Quick / Detailed / Lease-Level
        |
    analyze_acquisition_from_operating_projection   the one shared engine

The operating mode decides NOI; the Business Plan decides owner-level capital
economics. Each function below therefore does exactly two things -- resolve
the plan once, for the hold period of the analysis it is about to run, and hand
the resulting generic schedule to that mode's unchanged entry point. There is
no owner-capital arithmetic here and none in any mode: the engine subtracts the
schedule in one place for all three.

**Why the plan is resolved here, per call.** Resolution depends on the hold
period: capital is bucketed into hold years, a ``None``-ended owner expense runs
"through the current hold", and anything scheduled after the hold is disclosed
rather than paid (Sections 4, 5 and 19). Resolving at the moment of analysis,
against that analysis's own terms, is what keeps a hold-period change from ever
reusing a schedule resolved for a different hold.

**The engine never sees a plan item.** Identifiers, descriptions, categories and
model months stop at the resolver; ``anchor.engine`` and ``anchor.leasing`` do
not import ``anchor.business_plan``. Callers with no Business Plan keep calling
the mode entry points directly, which is exactly the empty plan.

**Secondary analysis (D6.4).** Sensitivity and break-even evaluate many
candidates of one deal and hold its plan fixed across all of them. They call
the same resolver once per run, for the base hold period, and hand that one
schedule to every candidate's engine call -- so they do not route each
candidate through these functions, which resolve per call. The API and
persistence are deliberately not wired yet (D6.5).
"""

from __future__ import annotations

from typing import Iterable

from ..business_plan import BusinessPlan, resolve_business_plan
from ..contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from ..engine.acquisition import (
    analyze_acquisition,
    analyze_detailed_acquisition_with_projection,
)
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults
from ..leasing.contracts import (
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    MarketLeasingAssumptions,
    Suite,
)
from .contracts import LeaseLevelAcquisitionResults
from .lease_level import analyze_lease_level_acquisition_with_projection


def analyze_quick_acquisition_with_business_plan(
    inputs: AcquisitionInputs, *, business_plan: BusinessPlan
) -> AcquisitionResults:
    """Quick Underwrite with a Business Plan: resolve the plan for
    ``inputs.hold_period``, then run ``analyze_acquisition`` with it.

    ``BusinessPlan()`` reproduces ``analyze_acquisition(inputs)`` exactly."""

    return analyze_acquisition(
        inputs,
        owner_capital=resolve_business_plan(
            business_plan, hold_period=inputs.hold_period
        ),
    )


def analyze_detailed_acquisition_with_business_plan(
    terms: AcquisitionTerms,
    detailed_inputs: DetailedOperatingInputs,
    *,
    business_plan: BusinessPlan,
) -> DetailedAcquisitionResults:
    """Detailed Underwrite with a Business Plan: resolve the plan for
    ``terms.hold_period``, then run
    ``analyze_detailed_acquisition_with_projection`` with it.

    ``BusinessPlan()`` reproduces
    ``analyze_detailed_acquisition_with_projection(terms, detailed_inputs)``
    exactly."""

    return analyze_detailed_acquisition_with_projection(
        terms,
        detailed_inputs,
        owner_capital=resolve_business_plan(
            business_plan, hold_period=terms.hold_period
        ),
    )


def analyze_lease_level_acquisition_with_business_plan(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    business_plan: BusinessPlan,
) -> LeaseLevelAcquisitionResults:
    """Lease-Level underwriting with a Business Plan: resolve the plan for
    ``terms.hold_period``, then run
    ``analyze_lease_level_acquisition_with_projection`` with it.

    The plan is resolved before the rent roll is validated. A plan the resolver
    refuses therefore surfaces as a Business Plan error rather than being
    reported after, or as, a leasing problem.

    ``BusinessPlan()`` reproduces the Lease-Level analysis exactly. Project
    capital stays a separate channel from the rent roll's TI and LC: both
    reach owner cash flow, neither is merged into the other."""

    return analyze_lease_level_acquisition_with_projection(
        terms,
        property_inputs,
        suites,
        leases,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        owner_capital=resolve_business_plan(
            business_plan, hold_period=terms.hold_period
        ),
    )
