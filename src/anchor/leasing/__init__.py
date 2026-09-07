"""Anchor Lease-Level underwriting -- contractual lease domain.

Sprint D, Gate D1.0. Governed by
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``,
which is authoritative on any discrepancy.

Lease-Level is Anchor's third operating producer, alongside Quick
(``anchor.engine.noi``) and Detailed
(``anchor.engine.operating_projection``). It derives property operating
economics from individual suites and leases rather than from a single NOI
figure or a property-level revenue build.

**This package is deliberately isolated.** It imports nothing from
``anchor.engine.acquisition``, ``anchor.engine.debt``, ``anchor.engine.noi``,
``anchor.engine.returns``, ``anchor.engine.operating_projection``,
``anchor.ai``, ``anchor.deals``, ``anchor.ingestion``, or ``anchor.analysis``,
and nothing outside it imports this package yet. The connection into the
downstream acquisition/debt/returns engine is made at D4, in that direction
only. The boundary is enforced by ``tests/test_leasing_architecture.py``.

**What exists at D1.0: vocabulary and invariants.** This gate establishes
what a contractual lease *is* and when one is valid. It computes nothing --
no month index, no monthly rent, no annual aggregate, no NOI, no return. A
reader should be able to answer "what is a valid contractual lease in Anchor"
from this package without encountering a single rent calculation.

D1.1 adds the canonical monthly calendar: ``ModelMonth`` plus
``build_model_months``, which together give one trusted, auditable
representation of every modeled lease month -- sequential index, real calendar
month, hold year, and the twelve forward exit-NOI months, in a single
projection. Still no rent: calendar arithmetic is in scope, financial
arithmetic is not.

D1.2 adds the contractual base-rent monthly timeline: for one validated
lease, the exact dollar rent in every canonical month, on the lease's true
contractual chronology. ``rent.py`` is the only module permitted to perform
rent arithmetic.

D1.3 adds the property rent-roll schedule -- many leases across many suites
combined into one canonical monthly series, with occupied and vacant rentable
area derived from contractual activity -- and the annual aggregation derived
solely from those monthly values. There is no independent annual rent engine.

D2.1 adds the canonical monthly market-rent schedule: for each suite, the
market rent in ``$/SF/year`` in every canonical month, growing in annual steps
on ``analysis_start_date`` anniversaries, with the property-default /
suite-override precedence resolved once per suite. ``market.py`` is the only
module permitted to perform market-rent arithmetic, exactly as ``rent.py`` is
the only one permitted to perform contractual-rent arithmetic; neither reads
the other's fields. Market rent is an assumption **rate** about available
space -- it is not a successor lease, and nothing at D2.1 converts it into a
dollar cash flow. Rollover, renewal, downtime, free rent, TI, LC and
probability composition are D2.2 and later.

D2.2 adds the pure renewal rollover path: an expiring lease produces exactly
one renewal successor commencing the month after expiry, priced from the
canonical market-rent schedule at that month by D0 Section 24.3, with its own
integer term and its own contractual escalation running from its own
commencement. ``rollover.py`` owns the renewal branch but owns no rent
formula: market rent comes from ``market.py`` and contractual rent from
``rent.py``, because a successor is an ordinary contractual lease from the
moment it commences. This is conceptually the ``p = 1`` endpoint, but no
probability exists yet -- the new-tenant branch, downtime and free rent are
D2.3, TI and LC are D2.4, ``renewal_probability`` and expected-value
composition are D2.5, and recursion is D2.6.

D2.3 adds the pure new-tenant branch and the concession mechanics both
branches share. Downtime sets the successor's month-equivalent occupancy
factor -- ``floor(D)`` fully vacant periods, then ``1 - frac(D)`` at
commencement -- and free rent is then consumed against that occupancy by a
sequential waterfall, never as an independent multiplicative factor. Face rent
and cash rent are kept as separate series: neither concession reduces
contractual face rent, which D2.4's LC basis reads. Branch physical occupancy
stays integral and keeps that name; the fractional
``successor_occupancy_factor`` is a different quantity under a different name.
The renewal branch gains the same mechanics, and at zero downtime and zero free
rent reproduces the accepted D2.2 result exactly.

D2.4 adds each branch's tenant improvements and leasing commissions, both
strictly below NOI and neither touching a rent or occupancy series. TI is
``ti_psf x leased_area_sf``, recorded in full in the first canonical month with
``successor_occupancy_factor > 0``. LC is ``lc_pct`` times the successor's
**full-term** contractual face rent -- including escalations, gross of free
rent, untruncated by the projection horizon and unreduced by a fractional first
month -- recorded in the same month. That basis comes from
``rent.contractual_face_rent_over_full_term``, which reaches the one D1
monthly-rent formula, so no second escalation formula and no closed-form
shortcut exists anywhere.

D2.5 composes the two complete branches into their expected economics:
``Expected[m] = p * Renewal[m] + (1 - p) * NewTenant[m]``, applied **last**, to
finished monthly outcomes. No input parameter is ever weighted, no synthetic
successor lease exists, and no timing is averaged -- where the branches place a
cost in different months, both weighted events stand at their own real months.
Every expected dollar series is weighted from the corresponding branch dollar
series directly, never reconstructed from expected factors, because
``E[X * Y] != E[X] * E[Y]`` for branch-correlated quantities. Branch
``physical_occupancy`` stays integral; the composed fractional series is
``expected_occupancy`` / ``expected_occupied_area_sf``. Recursion is D2.6, and
the downstream below-NOI channel is D4.

D3.1 adds tenant expense-recovery revenue for known `NNN` and `GROSS` leases.
Given an injected ``RecoverableExpensePool`` -- D3 projects no operating
expenses and builds no shadow expense engine, which is the D3/D4 seam --
``recoveries.py`` computes ``factor x share x pool`` through one authoritative
formula. The pro-rata share is leased area over rentable area on D1's exact
basis; the economic responsibility factor comes from D1 contractual activity,
never from rent dollars, so a zero-rent lease still recovers in full. `GROSS`
is an explicit zero rather than a zero factor, and `MODIFIED_GROSS` is refused
rather than silently zeroed -- it needs an explicit contractual basis, which is
D3.2. Successor recoveries are D3.3, expected and recursive recoveries D3.4,
and property aggregation D3.5.

D4.2 aggregates the completed leasing economics of the whole property.
``suite_operating_projection`` is the one extraction seam: it copies an
authoritative **full-chain** result -- ``RecursiveRollover`` for an occupied
suite, ``InitialVacancyRollover`` for one vacant at the analysis start,
including the explicit all-zero `HOLD_VACANT` chain -- onto a neutral
``SuiteOperatingProjection``, and computes nothing.
``build_property_operating_schedule`` then sums those finished dollars and
areas once, deterministically, with every suite present exactly once. Cash base
rent is **carried**, never rebuilt as contractual minus free rent, because in a
fractional-downtime month those differ by the part of the month nobody
occupied. Property occupancy is computed once from areas -- suite-level ratios
are not published, so averaging them is unavailable rather than merely
discouraged. Recoveries, property expenses, other income, credit loss, the
management fee, EGI and NOI are all later gates.

D4.1 closes the D3/D4 seam. ``expenses.py`` projects the five fixed property
operating expense lines onto the canonical monthly timeline -- annual step
growth on analysis-start anniversaries, then a level ``/ 12`` inside each model
year -- and builds the ``RecoverableExpensePool`` D3 has consumed as an
injected input since D3.1 (HD-D3-8, resolved: D3 injects, D4 supplies). The
pool is ``recoverable_expense_ratio`` times the completed five-line total, and
the management fee is structurally absent from that total, which is what makes
the whole property build one deterministic pass with no fixed-point solve. The
builder takes no suite, lease, area or occupancy, so a fully vacant building
incurs exactly the same fixed expenses as a fully leased one. Revenue, credit
loss, the management fee, EGI and NOI are D4.3; nothing here computes tenant
recovery revenue, which remains D3's.

D4.3 composes the three completed monthly schedules into
``MonthlyPropertyProjection``, the statement a Lease-Level deal is read from.
``projection.py`` recalculates nothing: it copies the leasing lines, the
recovery revenue and the five fixed expense lines, and adds exactly six new
series -- other income, credit loss, EGI, the management fee, total operating
expenses and NOI. EGI reads ``cash_base_rent`` **directly**, never
``contractual - free_rent``, which differs from it in any fractional-downtime
month; contractual rent and free rent stay audit lines feeding nothing. Credit
loss applies to cash rent plus recovery only, the management fee is a
percentage of EGI with recoveries included, recovery stays revenue while
expenses stay gross, and TI and LC stay below NOI in every month including the
forward window. Because the fee is excluded from the recoverable pool, the
whole statement resolves in one pass with no solver. NOI is never floored.
Annual aggregation, exit NOI and the going-in cap rate are D4.4's.

D4.4 derives the annual view. ``aggregate_monthly_to_annual`` reduces the
canonical monthly projection through the three D1.3 reducers and nothing else:
every ``_by_year`` flow is the chronological sum of its twelve months, every
annual state carries its semantics in its name, and ``exit_noi`` is the sum of
monthly NOI over months ``12H+1..12H+12`` -- never Hold Year H grown. Annual
NOI is summed from monthly NOI, not rebuilt from annual EGI less annual
expenses, so the figure every downstream return depends on has one arithmetic
path. Hold-year TI/LC arrays are length H and physically cannot reach a
forward month; the forward window's leasing costs are disclosed once, as a
scalar that nothing deducts. The result satisfies
``OperatingProjectionLike`` structurally, without fabricating a single
Detailed-only field. A non-positive ``exit_noi`` is constructed faithfully:
refusing to capitalize it belongs to the integration boundary at D4.5.
"""

from __future__ import annotations

from .aggregation import (
    aggregate_flow_over_forward_exit_window,
    aggregate_flow_to_annual,
    average_state_over_year,
    build_property_operating_schedule,
    build_property_rent_roll_schedule,
    build_property_recovery_schedule,
    suite_operating_projection,
    suite_recovery_projection,
    snapshot_state_at_year_end,
)
from .calendar import (
    build_model_months,
    is_first_day_of_month,
    is_last_day_of_month,
    last_day_of_month,
    month_index,
    month_start_for_index,
    projection_month_count,
)
from .contracts import (
    AnnualOperatingProjection,
    EscalationBasis,
    ExpectedRollover,
    ExpectedRolloverRecovery,
    InitialVacancyAssumptions,
    InitialVacancyRollover,
    InitialVacancyRolloverRecovery,
    InitialVacancyStrategy,
    RecursiveRollover,
    RecursiveRolloverRecovery,
    RolloverBranchKind,
    RolloverEventStateAudit,
    RolloverTransitionAudit,
    SuccessorContribution,
    SuccessorRecoverySchedule,
    SuiteOperatingProjection,
    SuiteRecoveryProjection,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseMonthlySchedule,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketAssumptionSource,
    MarketLeasingAssumptions,
    MarketRentSchedule,
    LeaseRecoverySchedule,
    ModelMonth,
    MonthlyPropertyExpenseSchedule,
    MonthlyPropertyProjection,
    NewTenantBranch,
    PropertyOperatingSchedule,
    PropertyRentRollSchedule,
    PropertyRecoverySchedule,
    RecoverableExpensePool,
    RecoveryContributionAudit,
    RecoveryBasis,
    RenewalBranch,
    ResolvedMarketLeasing,
    Suite,
)
from .expenses import (
    FIXED_EXPENSE_LINES,
    annual_expense_amount,
    build_property_expense_schedule,
    build_recoverable_expense_pool,
)
from .market import (
    build_market_rent_schedule,
    build_property_market_rent_schedules,
    market_growth_index,
    market_rent_psf_at_period,
    market_rent_psf_for_period,
    resolve_market_leasing,
)
from .leasing_costs import (
    leasing_commission_amount,
    leasing_cost_event_period,
    leasing_cost_event_series,
    tenant_improvement_amount,
)
from .recoveries import (
    build_lease_recovery_schedule,
    build_successor_recovery_schedule,
    build_expected_rollover_recovery,
    build_recursive_rollover_recovery,
    build_initial_vacancy_rollover_recovery,
    lease_responsibility_factors,
    monthly_expense_recovery,
    monthly_expense_stop_dollars,
    tenant_pro_rata_share,
)
from .projection import (
    aggregate_monthly_to_annual,
    annual_other_income,
    build_monthly_property_projection,
)
from .rent import (
    build_lease_monthly_schedule,
    contractual_face_rent_over_full_term,
    lease_contractual_term_months,
)
from .rollover import (
    build_expected_rollover,
    build_recursive_rollover,
    build_initial_vacancy_rollover,
    build_successor_contribution,
    successor_state_lease_id_stem,
    build_new_tenant_branch,
    compose_expected_rollover,
    build_renewal_branch,
    build_renewal_successor_lease,
    build_successor_lease,
    free_rent_waterfall,
    maximum_consumable_free_rent_months,
    new_tenant_starting_rent_psf,
    renewal_commencement_period,
    renewal_starting_rent_psf,
    successor_commencement_period,
    successor_expiration_period,
    successor_occupancy_factors,
    weighted_outcome,
)
from .validation import (
    require_valid_annual_adapter_inputs,
    validate_annual_adapter_inputs,
    require_valid_property_projection_inputs,
    validate_property_projection_inputs,
    require_valid_property_operating_inputs,
    validate_property_operating_inputs,
    require_valid_lease_level_operating_inputs,
    require_valid_recoverable_expense_ratio,
    validate_lease_level_operating_inputs,
    validate_recoverable_expense_ratio,
    require_valid_recovery_inputs,
    require_valid_property_recovery_inputs,
    require_valid_initial_vacancy_inputs,
    require_valid_successor_recovery_assumptions,
    validate_recovery_inputs,
    validate_property_recovery_inputs,
    validate_initial_vacancy_inputs,
    validate_successor_recovery_assumptions,
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
    LeaseValidationIssue,
    LeaseValidationResult,
    require_valid_lease_level_inputs,
    validate_lease_level_inputs,
)

__all__ = [
    # calendar (D1.1)
    "ModelMonth",
    "build_model_months",
    "projection_month_count",
    "month_index",
    "month_start_for_index",
    "is_first_day_of_month",
    "is_last_day_of_month",
    "last_day_of_month",
    # rent (D1.2)
    "LeaseMonthlySchedule",
    "build_lease_monthly_schedule",
    # property aggregation (D1.3)
    "PropertyRentRollSchedule",
    "PropertyRecoverySchedule",
    "build_property_rent_roll_schedule",
    "build_property_recovery_schedule",
    "suite_recovery_projection",
    "aggregate_flow_to_annual",
    "aggregate_flow_over_forward_exit_window",
    "snapshot_state_at_year_end",
    "average_state_over_year",
    # market rent (D2.1)
    "MarketLeasingAssumptions",
    "MarketAssumptionSource",
    "ResolvedMarketLeasing",
    "MarketRentSchedule",
    "resolve_market_leasing",
    "market_growth_index",
    "market_rent_psf_for_period",
    "build_market_rent_schedule",
    "build_property_market_rent_schedules",
    "market_rent_psf_at_period",
    # renewal rollover (D2.2)
    "LeaseOrigin",
    "RenewalBranch",
    "renewal_commencement_period",
    "successor_expiration_period",
    "renewal_starting_rent_psf",
    "build_renewal_successor_lease",
    "build_renewal_branch",
    # new-tenant branch, downtime and free rent (D2.3)
    "NewTenantBranch",
    "build_new_tenant_branch",
    "build_successor_lease",
    "new_tenant_starting_rent_psf",
    "successor_commencement_period",
    "successor_occupancy_factors",
    "free_rent_waterfall",
    "maximum_consumable_free_rent_months",
    # leasing costs (D2.4)
    "LeasingCommissionMethod",
    "tenant_improvement_amount",
    "leasing_commission_amount",
    "leasing_cost_event_period",
    "leasing_cost_event_series",
    "contractual_face_rent_over_full_term",
    "lease_contractual_term_months",
    # expected-value composition (D2.5)
    "ExpectedRollover",
    "ExpectedRolloverRecovery",
    "InitialVacancyAssumptions",
    "InitialVacancyRollover",
    "InitialVacancyRolloverRecovery",
    "InitialVacancyStrategy",
    "weighted_outcome",
    "compose_expected_rollover",
    "build_expected_rollover",
    # recursive rollover (D2.6)
    "RolloverBranchKind",
    "SuccessorContribution",
    "SuccessorRecoverySchedule",
    "SuiteRecoveryProjection",
    "RolloverEventStateAudit",
    "RolloverTransitionAudit",
    "RecursiveRollover",
    "RecursiveRolloverRecovery",
    "build_successor_contribution",
    "successor_state_lease_id_stem",
    "build_recursive_rollover",
    "build_initial_vacancy_rollover",
    # expense recoveries (D3.1)
    "RecoverableExpensePool",
    "RecoveryContributionAudit",
    "RecoveryBasis",
    "LeaseRecoverySchedule",
    "tenant_pro_rata_share",
    "lease_responsibility_factors",
    "monthly_expense_recovery",
    "monthly_expense_stop_dollars",
    "build_lease_recovery_schedule",
    "build_successor_recovery_schedule",
    "build_expected_rollover_recovery",
    "build_recursive_rollover_recovery",
    "build_initial_vacancy_rollover_recovery",
    # annual operating adapter (D4.4)
    "AnnualOperatingProjection",
    "aggregate_monthly_to_annual",
    "validate_annual_adapter_inputs",
    "require_valid_annual_adapter_inputs",
    # monthly property projection (D4.3)
    "MonthlyPropertyProjection",
    "build_monthly_property_projection",
    "annual_other_income",
    "validate_property_projection_inputs",
    "require_valid_property_projection_inputs",
    # property leasing aggregation (D4.2)
    "SuiteOperatingProjection",
    "PropertyOperatingSchedule",
    "suite_operating_projection",
    "build_property_operating_schedule",
    "validate_property_operating_inputs",
    "require_valid_property_operating_inputs",
    # property operating expenses and the recoverable pool (D4.1)
    "LeaseLevelOperatingInputs",
    "MonthlyPropertyExpenseSchedule",
    "FIXED_EXPENSE_LINES",
    "annual_expense_amount",
    "build_property_expense_schedule",
    "build_recoverable_expense_pool",
    "validate_lease_level_operating_inputs",
    "require_valid_lease_level_operating_inputs",
    "validate_recoverable_expense_ratio",
    "require_valid_recoverable_expense_ratio",
    # contracts
    "EscalationBasis",
    "Lease",
    "LeaseLevelPropertyInputs",
    "LeaseType",
    "Suite",
    # validation
    "LeaseIssueCode",
    "LeaseIssueSeverity",
    "LeaseValidationError",
    "LeaseValidationIssue",
    "LeaseValidationResult",
    "require_valid_lease_level_inputs",
    "validate_lease_level_inputs",
    "require_valid_recovery_inputs",
    "require_valid_property_recovery_inputs",
    "require_valid_initial_vacancy_inputs",
    "require_valid_successor_recovery_assumptions",
    "validate_recovery_inputs",
    "validate_property_recovery_inputs",
    "validate_initial_vacancy_inputs",
    "validate_successor_recovery_assumptions",
]
