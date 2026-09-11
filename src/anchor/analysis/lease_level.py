"""Sprint D Gate D4.5B -- Lease-Level acquisition orchestration.

Restates
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 5.1, 21.6 and 27 exactly; that document governs on any discrepancy.

**This module is the bridge, and it is the only one.** It is where Lease-Level
knowledge stops:

```
anchor.leasing                      produces the operating models
        |
anchor.analysis.lease_level         THIS MODULE -- selects, sequences, converts
        |
anchor.engine.acquisition           the generic, operating-mode-agnostic engine
        |
anchor.engine.debt / .returns       unchanged
```

The shared acquisition engine never learns that a Suite, a Lease, a rollover, a
recovery or a monthly projection exists. It receives an object satisfying
``OperatingProjectionLike`` and an optional generic ``OperatingCapitalSchedule``,
exactly as it would from any future producer.

**No financial formula lives here.** Every number this module returns was
computed by an authoritative builder further up: rent and escalation by
``rent.py``, market rent by ``market.py``, rollover and concessions by
``rollover.py``, recoveries by ``recoveries.py``, fixed expenses and the
recoverable pool by ``expenses.py``, property aggregation by
``aggregation.py``, the monthly statement and the annual view by
``projection.py``, and every return metric by the shared engine. This module
selects builders, passes completed contracts between them, and wraps the
result.

**One financial condition is applied here, and only here**: a cap-rate terminal
valuation requires a positive forward exit NOI (HD-D4-7). It is checked at this
boundary, before the shared engine is invoked, precisely so that the operating
projection of a distressed building stays buildable and inspectable while its
capitalization is refused.
"""

from __future__ import annotations

from typing import Iterable

from ..contracts import AcquisitionTerms
from ..engine.acquisition import analyze_acquisition_from_operating_projection
from ..engine.contracts import OperatingCapitalSchedule, OwnerCapitalSchedule
from ..leasing import (
    AnnualOperatingProjection,
    InitialVacancyRollover,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    MarketLeasingAssumptions,
    MonthlyPropertyProjection,
    RecursiveRollover,
    Suite,
    aggregate_monthly_to_annual,
    build_initial_vacancy_rollover,
    build_initial_vacancy_rollover_recovery,
    build_model_months,
    build_monthly_property_projection,
    build_property_expense_schedule,
    build_property_operating_schedule,
    build_property_recovery_schedule,
    build_recoverable_expense_pool,
    build_recursive_rollover,
    build_recursive_rollover_recovery,
    require_capitalizable_exit_noi,
    require_valid_initial_vacancy_inputs,
    require_valid_lease_level_acquisition_leases,
    require_valid_lease_level_inputs,
    require_valid_recovery_inputs,
    require_valid_successor_recovery_assumptions,
    suite_operating_projection,
    suite_recovery_projection,
)
from .contracts import LeaseLevelAcquisitionResults


def analyze_lease_level_acquisition_with_projection(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    owner_capital: OwnerCapitalSchedule | None = None,
) -> LeaseLevelAcquisitionResults:
    """Run one complete Lease-Level acquisition analysis.

    The richer Lease-Level public entry point, named symmetrically with
    ``anchor.engine.acquisition.analyze_detailed_acquisition_with_projection``.
    Twelve steps, each delegating to an authoritative builder:

    1. **Validate the rent roll** through the one D1 leasing authority --
       rentable-area reconciliation, suite/lease areas, month-aligned economic
       dates, same-suite overlap. No rule is restated here.
    2. **Validate initial vacancy** (D3.6): a suite with no lease must carry an
       explicit ``HOLD_VACANT`` or ``MARKET_LEASE_UP`` treatment. Vacant space
       is never assumed to stay vacant.
    3. **Validate suite/lease association** for this path: at most one
       *known* lease per suite, because one suite yields one authoritative
       chain. Sequential and committed future known leases are rejected too,
       not silently dropped.
    4. **Validate successor recovery terms** (D3.3) on the property default
       and on every suite's full override, through
       ``require_valid_successor_recovery_assumptions`` -- the D3 authority,
       called here rather than restated. Each record is checked on the same
       ``path`` the D1/D2 market validator already uses for its non-recovery
       fields, so one record reports under one name. Validated before any
       rollover is built, because a successor's recovery terms are an analyst
       input like any other.
    5. **Build the canonical timeline** -- ``12H + 12`` months from the one D1
       calendar builder. No month arithmetic happens in this module.
    6. **Build one full leasing chain per suite.** An occupied suite goes
       through ``build_recursive_rollover``; a suite vacant at the analysis
       start through ``build_initial_vacancy_rollover``, which covers both
       ``HOLD_VACANT`` (an explicit all-zero chain) and ``MARKET_LEASE_UP``.
       A branch, a successor contribution or a first-rollover-only result is
       never used as property authority.
    7. **Build the monthly property expense schedule** (D4.1).
    8. **Build the recoverable expense pool** from that same completed schedule
       -- **exactly one pool exists** for the whole analysis, and every suite's
       recoveries consume it.
    9. **Validate the in-place leases' recovery terms against that pool**
       (D3.1) through ``require_valid_recovery_inputs`` -- again the existing
       authority, and the precondition ``build_lease_recovery_schedule``'s own
       docstring names. It runs here rather than with the other input
       validation only because it also checks the pool's domain and its
       alignment to the canonical timeline, which requires the pool to exist.
    10. **Attach recoveries** to each chain through the matching D3 builder,
        all against that one pool.
    11. **Aggregate** the suite leasing projections (D4.2) and the suite
        recovery projections (D3.5) into their property schedules.
    12. **Compose the monthly statement** (D4.3) and **derive the annual view**
        (D4.4).
    13. **Refuse a non-positive forward exit NOI** (HD-D4-7) -- before the
        shared engine is touched.
    14. **Assemble the generic ``OperatingCapitalSchedule``** directly from the
        annual projection's hold-period TI and LC arrays, and call the shared
        engine.

    **Owner capital is passed through too (D6.2).** ``owner_capital`` is the
    generic ``OwnerCapitalSchedule`` a caller resolved from a Business Plan
    (``anchor.analysis.business_plan_analysis``). It is handed to the shared
    engine untouched; ``None`` means an empty plan. This module never sees a
    plan item and applies no owner-capital arithmetic -- project capital stays
    a channel separate from the rent roll's TI and LC.

    **The operating-capital arrays are passed through, never recomputed.** D4.4
    already produced exactly ``H`` hold-year values by a reducer that
    physically cannot reach a forward month, so a post-sale TI cheque is
    excluded structurally rather than by a filter here. The same tuples reach
    ``AcquisitionResults``, which a golden asserts by identity.

    **The objects returned are the objects used.** ``monthly_projection`` and
    ``annual_projection`` on the envelope are the very instances that produced
    the returns -- there is no presentation copy and no rebuild after the
    engine call, so the audit trail and the arithmetic cannot diverge.

    Validation order is deterministic and upstream-first: a malformed rent roll
    surfaces before an initial-vacancy defect, which surfaces before a
    suite/lease association defect, which surfaces before a successor recovery
    defect, and all of them before the terminal-value check -- so a bad lease is
    never reported as a valuation problem.

    **Every recovery builder's stated precondition is now actually met here.**
    ``recoveries.py`` documents ``require_valid_recovery_inputs`` and
    ``require_valid_successor_recovery_assumptions`` as preconditions and keeps
    a defensive ``ValueError`` for callers that ignore them. Until D5.5C this
    module ignored them: an analyst-invalid recovery contract -- a
    ``MODIFIED_GROSS`` lease with no stop, an ``NNN`` lease carrying one --
    passed every validator above and tripped that defensive guard, which the API
    surfaces as a 500 rather than as the structured issue the leasing package
    had known how to emit all along. The guards remain; they are simply no
    longer reachable from analyst input.

    Raises ``anchor.leasing.LeaseValidationError`` on any leasing-scoped
    failure, including the terminal-value refusal. Nothing partially populated
    is returned: there is no sentinel IRR and no fabricated exit value.
    """

    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)

    # --- 1-3. validation, upstream first --------------------------------
    require_valid_lease_level_inputs(
        property_inputs,
        suite_tuple,
        lease_tuple,
        hold_period=terms.hold_period,
        market_leasing=market_leasing,
    )
    require_valid_initial_vacancy_inputs(
        suite_tuple, lease_tuple, property_defaults=market_leasing
    )
    require_valid_lease_level_acquisition_leases(suite_tuple, lease_tuple)

    # --- 4. successor recovery terms, on every record that can supply them ---
    #
    # The property default and each suite's full override are both complete
    # `MarketLeasingAssumptions`, and either can carry an invalid successor
    # recovery contract. Both are checked, on the same paths
    # `validate_lease_level_inputs` already uses for the non-recovery fields of
    # the same records -- so one record reports under one name whichever
    # validator found the defect.
    #
    # Every override is validated whether or not this particular roll resolves
    # to it, exactly as the D1/D2 market validator above already does: the
    # record is a declared input of the deal, not a conditional one.
    #
    # This also covers D3.6's first tenant, which reuses the new-tenant branch
    # of whichever record its suite resolves to rather than stating recovery
    # terms of its own.
    require_valid_successor_recovery_assumptions(market_leasing)
    for index, suite in enumerate(suite_tuple):
        if suite.market_leasing_override is not None:
            require_valid_successor_recovery_assumptions(
                suite.market_leasing_override,
                path=f"suites[{index}].market_leasing_override",
            )

    # --- 5. the one canonical timeline ----------------------------------
    months = build_model_months(
        analysis_start=property_inputs.analysis_start_date,
        hold_period=terms.hold_period,
    )

    # --- 6. one authoritative full chain per suite ----------------------
    lease_for_suite = {lease.suite_id: lease for lease in lease_tuple}
    chains: list[tuple[Suite, RecursiveRollover | InitialVacancyRollover]] = []
    for suite in suite_tuple:
        in_place = lease_for_suite.get(suite.suite_id)
        if in_place is not None:
            chain: RecursiveRollover | InitialVacancyRollover = (
                build_recursive_rollover(
                    in_place,
                    suite=suite,
                    analysis_start=property_inputs.analysis_start_date,
                    months=months,
                    property_defaults=market_leasing,
                )
            )
        else:
            chain = build_initial_vacancy_rollover(
                suite,
                analysis_start=property_inputs.analysis_start_date,
                months=months,
                property_defaults=market_leasing,
            )
        chains.append((suite, chain))

    # --- 7-8. property expenses, then THE pool --------------------------
    expense_schedule = build_property_expense_schedule(
        operating_inputs, months=months
    )
    pool = build_recoverable_expense_pool(
        expense_schedule,
        recoverable_expense_ratio=operating_inputs.recoverable_expense_ratio,
    )

    # --- 9. the in-place leases' own recovery contracts ---------------------
    #
    # `build_lease_recovery_schedule` names this call as its precondition. It
    # sits here rather than with the input validation above because it also
    # checks the pool's domain and its identity against the canonical
    # timeline -- neither of which can be asked before the pool exists.
    require_valid_recovery_inputs(lease_tuple, pool, months=months)

    # --- 10. recoveries, every chain against that one pool --------------
    recovery_projections = []
    for suite, chain in chains:
        if isinstance(chain, RecursiveRollover):
            recovery = build_recursive_rollover_recovery(
                chain,
                suite=suite,
                analysis_start=property_inputs.analysis_start_date,
                property_defaults=market_leasing,
                pool=pool,
                rentable_area_sf=property_inputs.rentable_area_sf,
            )
        else:
            recovery = build_initial_vacancy_rollover_recovery(
                chain,
                suite=suite,
                analysis_start=property_inputs.analysis_start_date,
                property_defaults=market_leasing,
                pool=pool,
                rentable_area_sf=property_inputs.rentable_area_sf,
            )
        recovery_projections.append(suite_recovery_projection(recovery))

    # --- 11. property aggregation ---------------------------------------
    operating_schedule = build_property_operating_schedule(
        [suite_operating_projection(suite, chain) for suite, chain in chains],
        suite_tuple,
        months=months,
        rentable_area_sf=property_inputs.rentable_area_sf,
        leases=lease_tuple,
    )
    recovery_schedule = build_property_recovery_schedule(
        recovery_projections,
        months=months,
        rentable_area_sf=property_inputs.rentable_area_sf,
        hold_period=terms.hold_period,
        suites=suite_tuple,
        leases=lease_tuple,
    )

    # --- 10. the monthly statement, then the annual view -----------------
    monthly_projection: MonthlyPropertyProjection = (
        build_monthly_property_projection(
            operating_schedule,
            recovery_schedule,
            expense_schedule,
            operating_inputs=operating_inputs,
        )
    )
    annual_projection: AnnualOperatingProjection = aggregate_monthly_to_annual(
        monthly_projection, purchase_price=terms.purchase_price
    )

    # --- 11. the one financial condition at this boundary (HD-D4-7) ------
    # Before the shared engine, so a non-positive forward NOI is never
    # capitalized and ``calculate_exit_value`` is never reached.
    require_capitalizable_exit_noi(annual_projection.exit_noi)

    # --- 12. the generic channel, then the one shared engine -------------
    operating_capital = OperatingCapitalSchedule(
        tenant_improvements_by_year=annual_projection.tenant_improvements_by_year,
        leasing_commissions_by_year=annual_projection.leasing_commissions_by_year,
    )
    results = analyze_acquisition_from_operating_projection(
        annual_projection, terms, operating_capital, owner_capital=owner_capital
    )

    return LeaseLevelAcquisitionResults(
        monthly_projection=monthly_projection,
        annual_projection=annual_projection,
        results=results,
    )
