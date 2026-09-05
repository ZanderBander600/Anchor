"""Sprint D Gate D2.6 -- recursive rollover by probability-mass propagation.

Proves, per
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md``
Section 5 (especially 5.5) and HD-D2-3, that rollover recursion runs to the
canonical projection end and stops only there.

The claims that matter most:

- **state merging is exact** -- the production algorithm agrees with an
  explicit path enumeration across a matrix of probabilities, terms, downtimes
  and concessions (the oracle below);
- a successor **never contributes to a period at or before its parent
  expired**, so history is counted once (the anti-double-counting invariant);
- expiration **strictly advances**, which is what terminates the recursion
  without any depth counter (HD-D2-3);
- the state count is **structurally bounded by the horizon**, so no cap of any
  kind is needed -- 131 states where an explicit tree has ``2**131`` paths;
- ``p = 1`` and ``p = 0`` produce single-scenario chains exactly;
- with no in-horizon second rollover, ``RecursiveRollover`` reproduces D2.5's
  ``ExpectedRollover`` exactly.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date

import pytest

from anchor.leasing import (
    EscalationBasis,
    Lease,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecursiveRollover,
    RolloverBranchKind,
    Suite,
    build_expected_rollover,
    build_market_rent_schedule,
    build_model_months,
    build_recursive_rollover,
    build_successor_contribution,
)


JAN_START = date(2027, 1, 1)
AREA = 10_000.0
METHOD = LeasingCommissionMethod.PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT

#: Probability masses are bounded in [0, 1]; this tolerance suits that
#: magnitude and is deliberately NOT used for dollar reconciliation.
MASS_REL, MASS_ABS = 1e-12, 1e-15

#: Dollars and areas, compared between two differently-grouped float sums.
MONEY_REL, MONEY_ABS = 1e-12, 1e-9


def close(actual: float, expected: float, *, rel: float, abs_: float) -> bool:
    return math.isclose(actual, expected, rel_tol=rel, abs_tol=abs_)


def assumptions(**overrides: object) -> MarketLeasingAssumptions:
    base: dict[str, object] = {
        "market_rent_psf": 24.0,
        "market_rent_growth": 0.0,
        "renewal_rent_psf": None,
        "renewal_rent_spread": 0.0,
        "renewal_term_months": 6,
        "successor_escalation_pct": 0.0,
        "renewal_downtime_months": 0.0,
        "renewal_free_rent_months": 0.0,
        "new_term_months": 6,
        "new_downtime_months": 0.0,
        "new_free_rent_months": 0.0,
        "renewal_ti_psf": 0.0,
        "new_ti_psf": 0.0,
        "leasing_commission_method": METHOD,
        "renewal_lc_pct": 0.0,
        "new_lc_pct": 0.0,
        "renewal_probability": 0.5,
    }
    base.update(overrides)
    return MarketLeasingAssumptions(**base)  # type: ignore[arg-type]


def suite(suite_id: str = "S1") -> Suite:
    return Suite(suite_id=suite_id, suite_area_sf=AREA)


def expiring_lease(
    *, expiry: date = date(2027, 1, 31), lease_id: str = "L1", **overrides: object
) -> Lease:
    base: dict[str, object] = {
        "lease_id": lease_id,
        "suite_id": "S1",
        "tenant_name": "Acme Corp",
        "leased_area_sf": AREA,
        "rent_commencement_date": date(2026, 1, 1),
        "lease_expiration_date": expiry,
        "base_rent_psf": 30.0,
        "escalation_pct": 0.0,
        "escalation_basis": EscalationBasis.NONE,
        "lease_type": LeaseType.NNN,
    }
    base.update(overrides)
    return Lease(**base)  # type: ignore[arg-type]


def recursive(
    *,
    hold_period: int = 1,
    lease: Lease | None = None,
    **overrides: object,
) -> RecursiveRollover:
    return build_recursive_rollover(
        lease if lease is not None else expiring_lease(),
        suite=suite(),
        analysis_start=JAN_START,
        months=build_model_months(analysis_start=JAN_START, hold_period=hold_period),
        property_defaults=assumptions(**overrides),
    )


#: The ten monthly series the recursion accumulates.
_SERIES = (
    "expected_contractual_base_rent",
    "expected_cash_base_rent",
    "expected_free_rent",
    "expected_tenant_improvements",
    "expected_leasing_commissions",
    "expected_occupied_area_sf",
    "expected_occupancy",
    "expected_successor_occupancy_factor",
    "expected_free_rent_abatement_months",
    "expected_cash_rent_factor",
)


# =============================================================================
# The explicit-tree oracle -- TEST ONLY, never production
# =============================================================================


def enumerate_paths(
    expiring: Lease,
    *,
    the_suite: Suite,
    months: tuple,
    defaults: MarketLeasingAssumptions,
    path_cap: int = 200_000,
) -> dict[str, tuple[float, ...]]:
    """Accumulate expected economics by walking **every** scenario path.

    The oracle for state merging. It shares ``build_successor_contribution``
    with production -- the per-successor economics are already proven by
    D2.2-D2.4 and are not what is under test here -- but it performs **no
    merging whatsoever**: every path is walked separately to its own end, and
    contributions are accumulated per path.

    If merging by expiration period were unsound, this would disagree with the
    production algorithm. It must never be production logic, and it is
    exponential by construction, so callers keep the horizon tiny.
    """

    from anchor.leasing.rent import build_lease_monthly_schedule
    from anchor.leasing.rollover import _resolve_market_schedule

    schedule = _resolve_market_schedule(
        the_suite, months=months, property_defaults=defaults, market_schedule=None
    )
    horizon = months[-1].period_index
    count = len(months)
    p = defaults.renewal_probability
    area = the_suite.suite_area_sf

    initial = build_lease_monthly_schedule(
        expiring, analysis_start=JAN_START, months=months
    )
    totals = {
        "expected_contractual_base_rent": list(initial.contractual_base_rent),
        "expected_cash_base_rent": list(initial.contractual_base_rent),
        "expected_free_rent": [0.0] * count,
        "expected_tenant_improvements": [0.0] * count,
        "expected_leasing_commissions": [0.0] * count,
        "expected_occupied_area_sf": list(initial.occupied_area),
        "expected_successor_occupancy_factor": [0.0] * count,
        "expected_free_rent_abatement_months": [0.0] * count,
        "expected_cash_rent_factor": [0.0] * count,
    }
    walked = 0

    def walk(parent_e: int, mass: float) -> None:
        nonlocal walked
        if not (1 <= parent_e < horizon) or mass == 0.0:
            return
        walked += 1
        assert walked <= path_cap, "oracle horizon too large -- shrink the case"

        if p == 1.0:
            children = ((RolloverBranchKind.RENEWAL, mass),)
        elif p == 0.0:
            children = ((RolloverBranchKind.NEW_TENANT, mass),)
        else:
            children = (
                (RolloverBranchKind.RENEWAL, mass * p),
                (RolloverBranchKind.NEW_TENANT, mass * (1.0 - p)),
            )

        for branch, child_mass in children:
            contribution = build_successor_contribution(
                suite=the_suite,
                analysis_start=JAN_START,
                months=months,
                market_schedule=schedule,
                parent_expiration_period=parent_e,
                lease_type=expiring.lease_type,
                branch=branch,
                lease_id_stem=f"oracle@{parent_e}",
            )
            for index in range(count):
                totals["expected_contractual_base_rent"][index] += (
                    child_mass * contribution.contractual_base_rent[index]
                )
                totals["expected_cash_base_rent"][index] += (
                    child_mass * contribution.cash_base_rent[index]
                )
                totals["expected_free_rent"][index] += (
                    child_mass * contribution.free_rent[index]
                )
                totals["expected_tenant_improvements"][index] += (
                    child_mass * contribution.tenant_improvements[index]
                )
                totals["expected_leasing_commissions"][index] += (
                    child_mass * contribution.leasing_commissions[index]
                )
                totals["expected_occupied_area_sf"][index] += (
                    child_mass * contribution.occupied_area[index]
                )
                totals["expected_successor_occupancy_factor"][index] += (
                    child_mass * contribution.successor_occupancy_factor[index]
                )
                totals["expected_free_rent_abatement_months"][index] += (
                    child_mass * contribution.free_rent_abatement_months[index]
                )
                totals["expected_cash_rent_factor"][index] += (
                    child_mass * contribution.cash_rent_factor[index]
                )
            walk(contribution.successor_expiration_period, child_mass)

    from anchor.leasing.rent import lease_rent_periods

    _, e0 = lease_rent_periods(expiring, analysis_start=JAN_START)
    walk(e0, 1.0)

    result = {name: tuple(values) for name, values in totals.items()}
    result["expected_occupancy"] = tuple(
        value / area for value in result["expected_occupied_area_sf"]
    )
    return result


ORACLE_MATRIX = [
    pytest.param(p, tr, tn, dr, dn, fr, fn, ti_r, ti_n, lc_r, lc_n,
                 id=f"p{p}-T{tr}v{tn}-D{dr}v{dn}-F{fr}v{fn}")
    for p, tr, tn, dr, dn, fr, fn, ti_r, ti_n, lc_r, lc_n in [
        (0.25, 6, 6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (0.50, 6, 6, 0.0, 0.0, 0.0, 0.0, 10.0, 60.0, 0.02, 0.06),
        (0.65, 4, 6, 0.0, 1.0, 0.0, 0.0, 10.0, 60.0, 0.02, 0.06),
        (0.90, 3, 5, 0.0, 2.0, 1.0, 2.0, 5.0, 40.0, 0.03, 0.05),
        (0.50, 3, 3, 0.0, 0.0, 0.5, 1.5, 12.0, 80.0, 0.02, 0.06),
        (0.65, 5, 4, 1.0, 2.25, 0.0, 1.25, 10.0, 70.0, 0.025, 0.055),
        (0.25, 4, 7, 0.5, 0.0, 1.5, 0.0, 8.0, 50.0, 0.02, 0.04),
        (1.00, 4, 9, 0.0, 3.0, 0.0, 2.0, 10.0, 60.0, 0.02, 0.06),
        (0.00, 4, 9, 0.0, 3.0, 0.0, 2.0, 10.0, 60.0, 0.02, 0.06),
    ]
]


@pytest.mark.parametrize(
    ("p", "t_r", "t_n", "d_r", "d_n", "f_r", "f_n", "ti_r", "ti_n", "lc_r", "lc_n"),
    ORACLE_MATRIX,
)
def test_state_merging_matches_explicit_path_enumeration(
    p: float, t_r: int, t_n: int, d_r: float, d_n: float,
    f_r: float, f_n: float, ti_r: float, ti_n: float, lc_r: float, lc_n: float,
) -> None:
    """**The central proof.** Merging by expiration period preserves economics
    exactly, across probabilities, differing terms, downtime, fractional
    downtime, free rent and differing TI/LC rates."""

    defaults = assumptions(
        renewal_probability=p,
        renewal_term_months=t_r, new_term_months=t_n,
        renewal_downtime_months=d_r, new_downtime_months=d_n,
        renewal_free_rent_months=f_r, new_free_rent_months=f_n,
        renewal_ti_psf=ti_r, new_ti_psf=ti_n,
        renewal_lc_pct=lc_r, new_lc_pct=lc_n,
        market_rent_psf=40.0, market_rent_growth=0.03,
        successor_escalation_pct=0.02,
    )
    months = build_model_months(analysis_start=JAN_START, hold_period=1)
    lease = expiring_lease()

    production = build_recursive_rollover(
        lease, suite=suite(), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )
    oracle = enumerate_paths(
        lease, the_suite=suite(), months=months, defaults=defaults
    )

    for name in _SERIES:
        got = getattr(production, name)
        want = oracle[name]
        for index, (a, b) in enumerate(zip(got, want)):
            assert close(a, b, rel=MONEY_REL, abs_=MONEY_ABS), (name, index, a, b)


@pytest.mark.parametrize("p", [0.0, 1.0])
def test_the_endpoints_match_the_oracle_exactly(p: float) -> None:
    """At an endpoint there is one scenario, so agreement is exact, not
    merely close."""

    defaults = assumptions(
        renewal_probability=p, renewal_term_months=4, new_term_months=9,
        new_downtime_months=3.0, renewal_ti_psf=10.0, new_ti_psf=60.0,
        renewal_lc_pct=0.02, new_lc_pct=0.06, market_rent_psf=40.0,
    )
    months = build_model_months(analysis_start=JAN_START, hold_period=1)
    lease = expiring_lease()

    production = build_recursive_rollover(
        lease, suite=suite(), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )
    oracle = enumerate_paths(
        lease, the_suite=suite(), months=months, defaults=defaults
    )

    for name in _SERIES:
        assert [v.hex() for v in getattr(production, name)] == [
            v.hex() for v in oracle[name]
        ], name


# =============================================================================
# The anti-double-counting invariant
# =============================================================================


def test_a_contribution_is_zero_at_or_before_its_parent_expiration() -> None:
    """**The primary anti-double-counting invariant**, asserted directly on the
    contract and over a sweep of shapes."""

    months = build_model_months(analysis_start=JAN_START, hold_period=2)
    schedule = build_market_rent_schedule(
        suite(), property_defaults=assumptions(), months=months
    )

    for parent_e in (1, 5, 12, 23):
        for branch in RolloverBranchKind:
            for downtime in (0.0, 2.25, 5.0):
                contribution = build_successor_contribution(
                    suite=suite(),
                    analysis_start=JAN_START,
                    months=months,
                    market_schedule=build_market_rent_schedule(
                        suite(),
                        property_defaults=assumptions(
                            renewal_downtime_months=downtime,
                            new_downtime_months=downtime,
                        ),
                        months=months,
                    ),
                    parent_expiration_period=parent_e,
                    lease_type=LeaseType.NNN,
                    branch=branch,
                    lease_id_stem="X",
                )
                for series_name in (
                    "contractual_base_rent", "cash_base_rent", "free_rent",
                    "tenant_improvements", "leasing_commissions", "occupied_area",
                    "physical_occupancy", "successor_occupancy_factor",
                    "free_rent_abatement_months", "cash_rent_factor",
                ):
                    for month, value in zip(months, getattr(contribution, series_name)):
                        if month.period_index <= parent_e:
                            assert value == 0.0, (series_name, month.period_index)
    assert schedule is not None


def test_the_contract_refuses_a_contribution_that_reaches_back() -> None:
    """The invariant is structural, not merely observed."""

    months = build_model_months(analysis_start=JAN_START, hold_period=1)
    schedule = build_market_rent_schedule(
        suite(), property_defaults=assumptions(), months=months
    )
    good = build_successor_contribution(
        suite=suite(), analysis_start=JAN_START, months=months,
        market_schedule=schedule, parent_expiration_period=6,
        lease_type=LeaseType.NNN, branch=RolloverBranchKind.RENEWAL,
        lease_id_stem="X",
    )
    reaching_back = list(good.contractual_base_rent)
    reaching_back[2] = 1.0  # period 3, before the parent expired

    with pytest.raises(ValueError, match="at or before its parent"):
        dataclasses.replace(good, contractual_base_rent=tuple(reaching_back))


def test_the_contract_refuses_a_non_advancing_successor() -> None:
    """Time progression is guarded structurally, not merely implied by the
    arithmetic.

    ``e' = e + floor(D) + T`` cannot violate it while ``D >= 0`` and
    ``T >= 1``, so no valid input exercises the guard -- which is precisely why
    it needs a test of its own. Without one, deleting the check would go
    unnoticed until some future change made a non-advancing transition
    reachable, and the recursion would then not terminate.
    """

    months = build_model_months(analysis_start=JAN_START, hold_period=1)
    schedule = build_market_rent_schedule(
        suite(), property_defaults=assumptions(), months=months
    )
    good = build_successor_contribution(
        suite=suite(), analysis_start=JAN_START, months=months,
        market_schedule=schedule, parent_expiration_period=6,
        lease_type=LeaseType.NNN, branch=RolloverBranchKind.RENEWAL,
        lease_id_stem="X",
    )

    for stalled in (6, 5, 0, -1):
        with pytest.raises(ValueError, match="strictly later"):
            dataclasses.replace(good, successor_expiration_period=stalled)


def test_the_known_lease_contributes_exactly_once() -> None:
    """History before the first expiration is deterministic and unweighted."""

    for p in (0.0, 0.35, 0.65, 1.0):
        result = recursive(hold_period=2, renewal_probability=p,
                           lease=expiring_lease(expiry=date(2027, 12, 31)))
        for period in range(1, 13):
            index = period - 1
            assert result.expected_contractual_base_rent[index].hex() == (
                result.initial_schedule.contractual_base_rent[index].hex()
            )
            assert result.expected_cash_base_rent[index].hex() == (
                result.initial_schedule.contractual_base_rent[index].hex()
            )
            assert result.expected_occupancy[index] == 1.0
            assert result.expected_tenant_improvements[index] == 0.0
            assert result.expected_leasing_commissions[index] == 0.0


# =============================================================================
# Time progression and termination
# =============================================================================


def test_every_transition_advances_time_strictly() -> None:
    """``e' = e + floor(D) + T >= e + 1``, since ``D >= 0`` and ``T >= 1``.
    This is what terminates the recursion, with no depth counter."""

    for t_r, t_n, d_r, d_n in ((1, 1, 0.0, 0.0), (6, 12, 0.0, 9.0),
                               (3, 4, 0.5, 2.25), (1, 2, 0.999, 0.0)):
        result = recursive(
            hold_period=3, renewal_term_months=t_r, new_term_months=t_n,
            renewal_downtime_months=d_r, new_downtime_months=d_n,
        )
        for transition in result.transitions:
            assert transition.successor_expiration_period > (
                transition.parent_expiration_period
            )
            assert transition.commencement_period > transition.parent_expiration_period


def test_event_states_are_processed_in_ascending_order() -> None:
    result = recursive(hold_period=3, renewal_term_months=4, new_term_months=7)

    periods = [state.expiration_period for state in result.event_states]
    assert periods == sorted(periods)
    assert len(periods) == len(set(periods)), "states must be merged, not duplicated"

    parents = [t.parent_expiration_period for t in result.transitions]
    assert parents == sorted(parents)


def test_no_state_is_processed_at_or_beyond_the_horizon() -> None:
    result = recursive(hold_period=2, renewal_term_months=5, new_term_months=5)
    horizon = result.months[-1].period_index

    for state in result.event_states:
        if state.processed:
            assert 1 <= state.expiration_period < horizon
        else:
            assert state.expiration_period >= horizon


# =============================================================================
# Probability conservation
# =============================================================================


def test_child_masses_sum_exactly_to_their_parent() -> None:
    result = recursive(hold_period=3, renewal_probability=0.65,
                       renewal_term_months=4, new_term_months=7)

    by_parent: dict[int, list[float]] = {}
    for transition in result.transitions:
        by_parent.setdefault(transition.parent_expiration_period, []).append(
            transition.probability_mass
        )
    processed = {
        s.expiration_period: s.probability_mass
        for s in result.event_states
        if s.processed
    }

    assert set(by_parent) == set(processed)
    for period, masses in by_parent.items():
        assert close(math.fsum(masses), processed[period],
                     rel=MASS_REL, abs_=MASS_ABS), period


@pytest.mark.parametrize("p", [0.0, 0.25, 0.5, 0.65, 0.9, 1.0])
def test_terminal_mass_reconciles_to_one(p: float) -> None:
    """Mass is neither created nor destroyed by a split or a merge."""

    for hold, t_r, t_n, d_n in ((1, 6, 6, 0.0), (2, 4, 9, 3.0), (3, 1, 1, 0.0)):
        result = recursive(hold_period=hold, renewal_probability=p,
                           renewal_term_months=t_r, new_term_months=t_n,
                           new_downtime_months=d_n)
        assert close(result.terminal_probability_mass, 1.0,
                     rel=MASS_REL, abs_=MASS_ABS), (p, hold)


def test_expected_occupancy_stays_within_zero_and_one() -> None:
    """Occupancy is an economic state, not scenario mass: dark scenarios make
    it less than 1, and that is correct rather than a lost path."""

    result = recursive(hold_period=2, renewal_probability=0.6,
                       renewal_term_months=4, new_term_months=6,
                       new_downtime_months=3.0)

    for value in result.expected_occupancy:
        assert -1e-15 <= value <= 1.0 + 1e-15
    assert any(value < 1.0 for value in result.expected_occupancy), (
        "the chosen case must actually go dark somewhere"
    )


# =============================================================================
# Endpoints
# =============================================================================


def test_p_equals_one_produces_only_renewal_transitions() -> None:
    result = recursive(hold_period=3, renewal_probability=1.0,
                       renewal_term_months=6, new_term_months=9,
                       new_downtime_months=2.0)

    assert result.transitions
    assert {t.branch for t in result.transitions} == {RolloverBranchKind.RENEWAL}
    assert all(t.probability_mass == 1.0 for t in result.transitions)
    assert all(s.probability_mass == 1.0 for s in result.event_states)
    assert result.terminal_probability_mass == 1.0


def test_p_equals_zero_produces_only_new_tenant_transitions() -> None:
    result = recursive(hold_period=3, renewal_probability=0.0,
                       renewal_term_months=6, new_term_months=9,
                       new_downtime_months=2.0)

    assert result.transitions
    assert {t.branch for t in result.transitions} == {RolloverBranchKind.NEW_TENANT}
    assert all(t.probability_mass == 1.0 for t in result.transitions)


def test_an_endpoint_creates_no_zero_mass_state_or_transition() -> None:
    for p in (0.0, 1.0):
        result = recursive(hold_period=3, renewal_probability=p,
                           renewal_term_months=6, new_term_months=9)
        assert all(t.probability_mass > 0.0 for t in result.transitions)
        assert all(s.probability_mass > 0.0 for s in result.event_states)


# =============================================================================
# The one-month stress case
# =============================================================================


def test_one_month_terms_over_a_ten_year_hold_stay_linear() -> None:
    """**The case that motivates state merging.** Renewal and new-tenant terms
    of one month with no downtime over a 132-month horizon: an explicit tree
    has ``2**131`` paths, and the algorithm uses one merged state per period."""

    result = recursive(hold_period=10, renewal_probability=0.5,
                       renewal_term_months=1, new_term_months=1)
    horizon = len(result.months)

    assert horizon == 132
    assert len(result.event_states) == 131
    assert len(result.transitions) == 262
    assert len(result.event_states) <= horizon
    assert len(result.transitions) <= 2 * horizon

    # Every path is on a lease every month, so every state carries the whole
    # mass and the suite is never dark.
    for state in result.event_states:
        assert close(state.probability_mass, 1.0, rel=MASS_REL, abs_=MASS_ABS)
    for value in result.expected_occupancy:
        assert close(value, 1.0, rel=MASS_REL, abs_=MASS_ABS)
    assert close(result.terminal_probability_mass, 1.0, rel=MASS_REL, abs_=MASS_ABS)


def test_the_six_month_worked_case_merges_every_period() -> None:
    """Hand-checkable. Expiry at P1, one-month terms, no downtime, ``p = 0.5``.

    Both branches expire one month later, so their masses merge at the same
    next event period every time: one state per period, each carrying the full
    mass, and two transitions out of each."""

    result = recursive(hold_period=1, renewal_probability=0.5,
                       renewal_term_months=1, new_term_months=1)

    states = {s.expiration_period: s for s in result.event_states}
    for period in range(1, 7):
        assert period in states, period
        assert close(states[period].probability_mass, 1.0,
                     rel=MASS_REL, abs_=MASS_ABS)

    for period in range(1, 7):
        out = [t for t in result.transitions if t.parent_expiration_period == period]
        assert len(out) == 2
        assert {t.branch for t in out} == set(RolloverBranchKind)
        for transition in out:
            assert transition.probability_mass == 0.5
            assert transition.commencement_period == period + 1
            assert transition.successor_expiration_period == period + 1

    # In-place lease pays $30/SF in P1; every successor pays market $24/SF.
    assert result.expected_cash_base_rent[0] == pytest.approx(25_000.0, abs=1e-9)
    for index in range(1, 6):
        assert result.expected_cash_base_rent[index] == pytest.approx(
            20_000.0, abs=1e-9
        )
    for index in range(6):
        assert result.expected_occupancy[index] == pytest.approx(1.0, abs=1e-12)


# =============================================================================
# Different terms, and state convergence
# =============================================================================


def test_different_terms_roll_asynchronously() -> None:
    """Case 18 timing. Renewal 60 months with no downtime expires at ``e+60``;
    new tenant 120 months with 9 months downtime expires at ``e+129``. One
    scenario can roll again while the other is still on its first successor --
    there are no synchronised generations."""

    # hold 8 -> N = 108, so the renewal chain rolls again in-horizon and the
    # new-tenant chain does not: the contrast is unambiguous.
    result = recursive(hold_period=8, renewal_probability=0.65,
                       renewal_term_months=60, new_term_months=120,
                       renewal_downtime_months=0.0, new_downtime_months=9.0,
                       market_rent_psf=44.0, renewal_rent_psf=40.0,
                       renewal_ti_psf=10.0, new_ti_psf=80.0,
                       renewal_lc_pct=0.02, new_lc_pct=0.06,
                       lease=expiring_lease(expiry=date(2027, 12, 31)))

    first = [t for t in result.transitions if t.parent_expiration_period == 12]
    by_branch = {t.branch: t for t in first}

    # Exactly the Case 18 dates.
    assert by_branch[RolloverBranchKind.RENEWAL].successor_expiration_period == 72
    assert by_branch[RolloverBranchKind.NEW_TENANT].successor_expiration_period == 141
    assert by_branch[RolloverBranchKind.RENEWAL].term_months == 60
    assert by_branch[RolloverBranchKind.NEW_TENANT].term_months == 120

    # Asynchronous: the renewal chain rolls again at 72, while the new-tenant
    # chain is still on its first successor and never rolls in-horizon.
    assert any(t.parent_expiration_period == 72 for t in result.transitions)
    assert not any(t.parent_expiration_period == 141 for t in result.transitions)
    # 72 becomes an event state and rolls; 141 lies beyond the N=108 horizon,
    # so it is terminal and correctly never becomes one.
    states = {s.expiration_period for s in result.event_states}
    assert {12, 72} <= states
    assert 141 not in states
    assert 141 in {t.successor_expiration_period for t in result.transitions}

    # No weighted term exists: every transition carries one branch's own term.
    assert {t.term_months for t in result.transitions} == {60, 120}
    # ... and 0.65*60 + 0.35*120 = 81 is never one of them.
    assert 81 not in {t.term_months for t in result.transitions}


def test_two_paths_converging_on_one_period_are_merged() -> None:
    """Renewal (12 months, no downtime) and new tenant (9 months, 3 months
    downtime) both expire 12 periods after their parent, so their masses merge
    into **one** state that is processed **once**."""

    result = recursive(hold_period=4, renewal_probability=0.6,
                       renewal_term_months=12, new_term_months=9,
                       new_downtime_months=3.0, market_rent_psf=40.0,
                       renewal_rent_spread=-0.10,
                       market_rent_growth=0.03, successor_escalation_pct=0.02,
                       lease=expiring_lease(expiry=date(2027, 6, 30)))

    first = [t for t in result.transitions if t.parent_expiration_period == 6]
    assert len(first) == 2
    assert {t.successor_expiration_period for t in first} == {18}
    # The two paths are priced and termed differently -- $36 on a 12-month
    # renewal versus $40 on a 9-month new letting after three months dark --
    # and still converge on period 18.
    rents = {t.branch: t.starting_rent_psf for t in first}
    assert rents[RolloverBranchKind.RENEWAL] == pytest.approx(36.0, abs=1e-9)
    assert rents[RolloverBranchKind.NEW_TENANT] == pytest.approx(40.0, abs=1e-9)

    converged = [s for s in result.event_states if s.expiration_period == 18]
    assert len(converged) == 1, "the two paths must merge into one state"
    assert close(converged[0].probability_mass, 1.0, rel=MASS_REL, abs_=MASS_ABS)

    out = [t for t in result.transitions if t.parent_expiration_period == 18]
    assert len(out) == 2, "the merged state is processed exactly once"


def test_a_merged_state_matches_weighting_the_paths_separately() -> None:
    """The convergence case against the oracle, which walks the two paths
    separately and weights them."""

    defaults = assumptions(
        renewal_probability=0.6, renewal_term_months=12, new_term_months=9,
        new_downtime_months=3.0, market_rent_psf=40.0, market_rent_growth=0.03,
        successor_escalation_pct=0.02, renewal_ti_psf=10.0, new_ti_psf=60.0,
        renewal_lc_pct=0.02, new_lc_pct=0.06,
    )
    months = build_model_months(analysis_start=JAN_START, hold_period=1)
    lease = expiring_lease(expiry=date(2027, 6, 30))

    production = build_recursive_rollover(
        lease, suite=suite(), analysis_start=JAN_START,
        months=months, property_defaults=defaults,
    )
    oracle = enumerate_paths(
        lease, the_suite=suite(), months=months, defaults=defaults
    )

    for name in _SERIES:
        for a, b in zip(getattr(production, name), oracle[name]):
            assert close(a, b, rel=MONEY_REL, abs_=MONEY_ABS), name


def test_lease_id_never_affects_a_financial_result() -> None:
    """A merged state represents many predecessors; whichever identifier is
    derived must not change a number."""

    kwargs = dict(hold_period=4, renewal_term_months=7, new_term_months=11,
                  renewal_probability=0.65, renewal_ti_psf=10.0, new_ti_psf=60.0,
                  renewal_lc_pct=0.02, new_lc_pct=0.06)
    left = recursive(lease=expiring_lease(lease_id="AAA"), **kwargs)
    right = recursive(lease=expiring_lease(lease_id="ZZZ-completely-different"),
                      **kwargs)

    for name in _SERIES:
        assert [v.hex() for v in getattr(left, name)] == [
            v.hex() for v in getattr(right, name)
        ], name
    assert left.expected_tenant_improvement_amount.hex() == (
        right.expected_tenant_improvement_amount.hex()
    )
    assert left.expected_leasing_commission_amount.hex() == (
        right.expected_leasing_commission_amount.hex()
    )


def test_the_successor_engine_ignores_the_lease_id_stem() -> None:
    months = build_model_months(analysis_start=JAN_START, hold_period=2)
    schedule = build_market_rent_schedule(
        suite(), property_defaults=assumptions(), months=months
    )
    common = dict(
        suite=suite(), analysis_start=JAN_START, months=months,
        market_schedule=schedule, parent_expiration_period=8,
        lease_type=LeaseType.NNN, branch=RolloverBranchKind.RENEWAL,
    )
    a = build_successor_contribution(lease_id_stem="one", **common)
    b = build_successor_contribution(lease_id_stem="two-different", **common)

    assert a.successor_lease.lease_id != b.successor_lease.lease_id
    assert a.starting_rent_psf.hex() == b.starting_rent_psf.hex()
    assert a.contractual_base_rent == b.contractual_base_rent
    assert a.cash_base_rent == b.cash_base_rent
    assert a.successor_expiration_period == b.successor_expiration_period
    assert a.tenant_improvement_amount == b.tenant_improvement_amount
    assert a.leasing_commission_amount == b.leasing_commission_amount


# =============================================================================
# Horizon behaviour
# =============================================================================


def test_a_term_beyond_the_horizon_contributes_and_stops() -> None:
    """The successor begins inside the projection and expires past it: it
    contributes through the horizon, its LC still uses the full contractual
    term, and it is not re-enqueued."""

    result = recursive(hold_period=1, renewal_term_months=60, new_term_months=60,
                       renewal_lc_pct=0.05, new_lc_pct=0.05, market_rent_psf=24.0)
    horizon = len(result.months)

    assert len(result.transitions) == 2
    for transition in result.transitions:
        assert transition.successor_expiration_period > horizon
        assert transition.commences_within_projection is True
        # LC on 60 full contractual months at $24/SF on 10,000 SF.
        assert transition.leasing_commission_amount == pytest.approx(
            0.05 * 60 * 20_000.0, abs=1e-6
        )
    assert not any(
        s.processed and s.expiration_period > horizon for s in result.event_states
    )


def test_a_commencement_beyond_the_horizon_leaves_the_suite_dark() -> None:
    """Downtime pushes ``c`` past the window. No positive contribution, no
    TI/LC event, and the post-expiration months are genuinely vacant."""

    result = recursive(hold_period=1, renewal_downtime_months=30.0,
                       new_downtime_months=30.0, renewal_ti_psf=50.0,
                       new_ti_psf=50.0, renewal_lc_pct=0.05, new_lc_pct=0.05,
                       lease=expiring_lease(expiry=date(2027, 6, 30)))

    assert all(
        t.commences_within_projection is False for t in result.transitions
    )
    for period in range(7, len(result.months) + 1):
        index = period - 1
        assert result.expected_cash_base_rent[index] == 0.0
        assert result.expected_occupancy[index] == 0.0
        assert result.expected_vacant_area_sf[index] == AREA
        assert result.expected_tenant_improvements[index] == 0.0
        assert result.expected_leasing_commissions[index] == 0.0

    assert close(result.terminal_probability_mass, 1.0, rel=MASS_REL, abs_=MASS_ABS)
    assert len(result.months) == 24  # no ModelMonth fabricated beyond the window


def test_recursion_stays_live_through_the_forward_exit_window() -> None:
    """A successor expiring inside ``12H+1 .. 12H+12`` rolls again when the
    remaining canonical months can still be affected. No stop at the sale
    month."""

    # hold 1 -> hold months 1-12, forward window 13-24.
    result = recursive(hold_period=1, renewal_term_months=4, new_term_months=4,
                       lease=expiring_lease(expiry=date(2027, 10, 31)))

    forward_parents = [
        t.parent_expiration_period
        for t in result.transitions
        if t.parent_expiration_period > 12
    ]
    assert forward_parents, "a rollover must occur inside the forward window"

    forward_months = {m.period_index for m in result.months if m.is_forward_exit_month}
    assert any(
        result.expected_cash_base_rent[period - 1] > 0.0 for period in forward_months
    )


def test_fractional_downtime_recurses_under_the_d2_3_rules() -> None:
    """A later-generation rollover reuses the accepted mechanics unchanged: two
    fully vacant periods, a ``0.75`` boundary factor, month-aligned dates, and
    a full-term LC denominator."""

    result = recursive(hold_period=3, renewal_term_months=6, new_term_months=6,
                       renewal_downtime_months=2.25, new_downtime_months=2.25,
                       renewal_probability=1.0, renewal_lc_pct=0.05,
                       market_rent_psf=24.0)

    second = [t for t in result.transitions if t.parent_expiration_period > 1]
    assert second, "the case must reach a later generation"
    transition = second[0]

    parent = transition.parent_expiration_period
    assert transition.commencement_period == parent + 3
    assert transition.successor_expiration_period == parent + 8

    index = transition.commencement_period - 1
    assert result.expected_successor_occupancy_factor[index] == pytest.approx(
        0.75, abs=1e-12
    )
    assert result.expected_occupancy[parent] == 0.0  # first vacant month
    # LC on six FULL contractual months, unreduced by the boundary factor.
    assert transition.leasing_commission_amount == pytest.approx(
        0.05 * 6 * 20_000.0, abs=1e-6
    )


# =============================================================================
# D2.5 compatibility
# =============================================================================


def test_with_no_second_rollover_it_reproduces_expected_rollover() -> None:
    """**The compatibility proof.** When no first successor expires inside the
    horizon, the recursion is one rollover -- and must agree with D2.5's
    authoritative single-rollover composition, exactly."""

    defaults = assumptions(
        renewal_term_months=120, new_term_months=120, renewal_probability=0.65,
        market_rent_psf=40.0, market_rent_growth=0.03,
        successor_escalation_pct=0.02, new_downtime_months=3.0,
        new_free_rent_months=2.5, renewal_free_rent_months=1.0,
        renewal_ti_psf=10.0, new_ti_psf=80.0,
        renewal_lc_pct=0.02, new_lc_pct=0.06,
    )
    months = build_model_months(analysis_start=JAN_START, hold_period=2)
    lease = expiring_lease(expiry=date(2027, 12, 31))
    common = dict(
        suite=suite(), analysis_start=JAN_START, months=months,
        property_defaults=defaults,
    )

    composed = build_expected_rollover(lease, **common)
    recursed = build_recursive_rollover(lease, **common)

    assert len(recursed.transitions) == 2
    for name in _SERIES:
        assert [v.hex() for v in getattr(recursed, name)] == [
            v.hex() for v in getattr(composed, name)
        ], name
    assert recursed.expected_tenant_improvement_amount == pytest.approx(
        composed.expected_tenant_improvement_amount, abs=1e-9
    )
    assert recursed.expected_leasing_commission_amount == pytest.approx(
        composed.expected_leasing_commission_amount, abs=1e-9
    )


# =============================================================================
# Determinism, bounds and the result contract
# =============================================================================


def test_repeated_builds_are_value_and_order_equal() -> None:
    kwargs = dict(hold_period=4, renewal_probability=0.65,
                  renewal_term_months=7, new_term_months=11,
                  new_downtime_months=2.25, new_free_rent_months=1.5)
    first = recursive(**kwargs)
    second = recursive(**kwargs)

    assert first == second
    assert first.event_states == second.event_states
    assert first.transitions == second.transitions


def test_transitions_are_ordered_by_parent_then_branch() -> None:
    result = recursive(hold_period=3, renewal_probability=0.5,
                       renewal_term_months=4, new_term_months=4)

    order = [
        (t.parent_expiration_period, list(RolloverBranchKind).index(t.branch))
        for t in result.transitions
    ]
    assert order == sorted(order)


@pytest.mark.parametrize("hold", [1, 2, 5, 10])
def test_state_and_transition_counts_stay_within_the_structural_bounds(
    hold: int,
) -> None:
    """Consequences of the algorithm, never configurable limits."""

    for t_r, t_n, d_n in ((1, 1, 0.0), (2, 3, 0.0), (4, 7, 2.25), (60, 120, 9.0)):
        result = recursive(hold_period=hold, renewal_term_months=t_r,
                           new_term_months=t_n, new_downtime_months=d_n)
        horizon = len(result.months)
        assert len(result.event_states) <= horizon
        assert len(result.transitions) <= 2 * horizon


def test_the_result_is_frozen() -> None:
    result = recursive()

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.renewal_probability = 0.1  # type: ignore[misc]


def test_expected_occupied_area_reconciles_to_area_times_occupancy() -> None:
    result = recursive(hold_period=2, renewal_probability=0.6,
                       renewal_term_months=4, new_term_months=6,
                       new_downtime_months=3.0)

    for index in range(len(result.months)):
        assert close(result.expected_occupied_area_sf[index],
                     AREA * result.expected_occupancy[index],
                     rel=MONEY_REL, abs_=MONEY_ABS)
        assert close(
            result.expected_occupied_area_sf[index]
            + result.expected_vacant_area_sf[index],
            AREA, rel=MONEY_REL, abs_=MONEY_ABS,
        )


def test_a_lease_expiring_before_the_analysis_start_is_refused() -> None:
    """The initial rollover event is always representable on the canonical
    timeline: such a lease is a validation ERROR, and the boundary refuses it
    independently rather than inventing pre-analysis history."""

    stale = expiring_lease(
        expiry=date(2026, 6, 30), lease_id="OLD",
        rent_commencement_date=date(2024, 1, 1),
    )

    with pytest.raises(ValueError, match="before the analysis start"):
        recursive(hold_period=2, lease=stale)


def test_a_lease_expiring_at_or_beyond_the_horizon_never_rolls() -> None:
    result = recursive(hold_period=1, lease=expiring_lease(expiry=date(2029, 12, 31)))

    assert result.transitions == ()
    assert close(result.terminal_probability_mass, 1.0, rel=MASS_REL, abs_=MASS_ABS)
    for index in range(len(result.months)):
        assert result.expected_cash_base_rent[index].hex() == (
            result.initial_schedule.contractual_base_rent[index].hex()
        )
