"""Phase 7 Gate P7.9 Stage 1 -- hurdle accounts.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 8 (PW-3) and
fixtures F2 and F3: ANNUAL_COMPOUND with no floor, SIMPLE under both explicit
distribution orders, MOIC, capacity and the ALL / ANY combinator.
"""

from __future__ import annotations

import pytest

from _p7_9_fixtures import (  # type: ignore[import-not-found]
    ACCRUED_FIRST,
    ALL,
    ANY,
    CAPITAL_FIRST,
    COMPOUND,
    F2_SERIES,
    F3_SERIES,
    SIMPLE,
    all_close,
    by_partner,
    by_tier,
    close,
    compound,
    f2_terms,
    f3_terms,
    moic,
    simple,
)
from anchor.partnership import HurdleCombinator, SimpleDistributionOrder
from anchor.partnership.accounts import (
    accrue,
    apply_contribution,
    apply_distribution,
    apply_simple_distribution,
    combine_capacities,
    condition_capacity,
    is_satisfied,
    open_account,
)


# =============================================================================
# The account formulas, one step at a time
# =============================================================================


def test_compound_accrues_on_the_opening_balance() -> None:
    condition = compound("c", 0.08)
    state = apply_contribution(open_account(), condition, 900_000.0)
    state, accrual = accrue(state, condition)
    assert close(state.balance, 972_000.0) and close(accrual, 72_000.0)
    state = apply_distribution(state, condition, 1_000_000.0)
    assert close(state.balance, -28_000.0)


def test_a_compound_surplus_carries_forward_and_compounds_without_a_floor() -> None:
    condition = compound("c", 0.10)
    state = apply_contribution(open_account(), condition, 1_000.0)
    state = apply_distribution(state, condition, 1_500.0)
    assert state.balance == -500.0
    state, accrual = accrue(state, condition)
    assert close(state.balance, -550.0) and close(accrual, -50.0)
    state, _ = accrue(state, condition)
    assert close(state.balance, -605.0)
    state = apply_contribution(state, condition, 400.0)
    assert close(state.balance, -205.0) and is_satisfied(state.balance)


def test_simple_accrues_on_outstanding_capital_only() -> None:
    condition = simple("s", 0.08, ACCRUED_FIRST)
    state = apply_contribution(open_account(), condition, 900_000.0)
    for _ in range(2):
        state, accrual = accrue(state, condition)
        assert close(accrual, 72_000.0)
    assert close(state.accrued_return, 144_000.0) and close(state.balance, 1_044_000.0)


@pytest.mark.parametrize(
    ("order", "capital", "accrued"),
    [
        (SimpleDistributionOrder.ACCRUED_RETURN_FIRST, 900_000.0, 27_000.0),
        (SimpleDistributionOrder.CAPITAL_FIRST, 855_000.0, 72_000.0),
    ],
)
def test_simple_distribution_orders(order: SimpleDistributionOrder, capital: float, accrued: float) -> None:
    assert apply_simple_distribution(900_000.0, 72_000.0, 45_000.0, order) == (capital, accrued)


@pytest.mark.parametrize("order", list(SimpleDistributionOrder))
def test_an_excess_simple_distribution_drives_capital_negative(order: SimpleDistributionOrder) -> None:
    capital, accrued = apply_simple_distribution(100.0, 10.0, 150.0, order)
    assert (capital, accrued) == (-40.0, 0.0)
    condition = simple("s", 0.10, order)
    state = apply_distribution(apply_contribution(open_account(), condition, 100.0), condition, 150.0)
    state, accrual = accrue(state, condition)
    assert accrual == 0.0 and state.balance == -50.0
    state = apply_contribution(state, condition, 80.0)
    assert state.outstanding_capital == 30.0
    state, accrual = accrue(state, condition)
    assert close(accrual, 3.0)


def test_moic_is_multiple_of_contributions_less_distributions() -> None:
    condition = moic("m", 1.5)
    state = apply_contribution(open_account(), condition, 1_000.0)
    state, accrual = accrue(state, condition)
    assert accrual == 0.0 and state.balance == 1_500.0
    state = apply_distribution(state, condition, 600.0)
    assert state.balance == 900.0


def test_rate_zero_makes_simple_compound_and_return_of_capital_agree() -> None:
    conditions = (compound("c", 0.0), simple("s", 0.0, ACCRUED_FIRST), simple("t", 0.0, CAPITAL_FIRST), moic("m", 1.0))
    balances = set()
    for condition in conditions:
        state = apply_contribution(open_account(), condition, 1_000.0)
        state, _ = accrue(state, condition)
        state = apply_distribution(state, condition, 300.0)
        state, _ = accrue(state, condition)
        balances.add(state.balance)
    assert balances == {700.0}


def test_capacity_divides_by_the_subject_share_and_zeroes_satisfied_balances() -> None:
    assert condition_capacity(900.0, 0.9) == pytest.approx(1_000.0)
    assert condition_capacity(0.0, 0.9) == 0.0
    assert condition_capacity(-5.0, 0.9) == 0.0
    assert condition_capacity(5e-7, 0.9) == 0.0
    assert combine_capacities((1.0, 3.0), HurdleCombinator.ALL) == 3.0
    assert combine_capacities((1.0, 3.0), HurdleCombinator.ANY) == 1.0
    assert combine_capacities((0.0, 3.0), HurdleCombinator.ANY) == 0.0


# =============================================================================
# F2 and F3 through the engine
# =============================================================================


def test_f2_simple_and_compound_differ_on_unpaid_accrual() -> None:
    simple_tiers = by_tier(__import__("_p7_9_fixtures").run(f2_terms(SIMPLE), *F2_SERIES))
    compound_tiers = by_tier(__import__("_p7_9_fixtures").run(f2_terms(COMPOUND), *F2_SERIES))
    assert close(simple_tiers["pref"].amounts[2], 1_160_000.0) and close(simple_tiers["residual"].amounts[2], 140_000.0)
    assert close(compound_tiers["pref"].amounts[2], 1_166_400.0) and close(compound_tiers["residual"].amounts[2], 133_600.0)
    assert close(simple_tiers["pref"].conditions[2].capacity_at_entry * 0.9, 1_044_000.0)  # type: ignore[operator]
    assert close(compound_tiers["pref"].conditions[2].capacity_at_entry * 0.9, 1_049_760.0)  # type: ignore[operator]


def test_f3_the_distribution_order_changes_later_accrual() -> None:
    from _p7_9_fixtures import run  # type: ignore[import-not-found]

    accrued_first = by_tier(run(f3_terms(ACCRUED_FIRST), *F3_SERIES))["pref"]
    capital_first = by_tier(run(f3_terms(CAPITAL_FIRST), *F3_SERIES))["pref"]
    a, c = accrued_first.conditions, capital_first.conditions
    assert (a[1].outstanding_capital, a[1].accrued_return) == (900_000.0, pytest.approx(27_000.0))
    assert (c[1].outstanding_capital, c[1].accrued_return) == (855_000.0, pytest.approx(72_000.0))
    assert close(a[2].accrual, 72_000.0) and close(c[2].accrual, 68_400.0)
    assert close(a[3].accrual, 72_000.0) and close(c[3].accrual, 68_400.0)
    assert close(a[3].opening_balance + a[3].accrual, 1_071_000.0)
    assert close(c[3].opening_balance + c[3].accrual, 1_063_800.0)
    assert close(accrued_first.amounts[3], 1_190_000.0) and close(capital_first.amounts[3], 1_182_000.0)
    assert a[3].simple_distribution_order is SimpleDistributionOrder.ACCRUED_RETURN_FIRST
    assert c[3].simple_distribution_order is SimpleDistributionOrder.CAPITAL_FIRST
    accrued_partners = by_partner(run(f3_terms(ACCRUED_FIRST), *F3_SERIES))
    capital_partners = by_partner(run(f3_terms(CAPITAL_FIRST), *F3_SERIES))
    assert all_close(
        (accrued_partners["lp"].total_distributions, accrued_partners["gp"].total_distributions,
         capital_partners["lp"].total_distributions, capital_partners["gp"].total_distributions),
        (1_204_000.0, 146_000.0, 1_203_200.0, 146_800.0),
    )


def test_compound_records_state_no_simple_fields() -> None:
    from _p7_9_fixtures import run  # type: ignore[import-not-found]

    record = by_tier(run(f2_terms(COMPOUND), *F2_SERIES))["pref"].conditions[0]
    assert record.simple_distribution_order is None and record.outstanding_capital is None and record.accrued_return is None


def test_any_with_a_condition_already_met_pays_nothing() -> None:
    from _p7_9_fixtures import LP_GP, BENCH_90_10, hurdle, of_partner, partnership, residual, run, split  # type: ignore[import-not-found]

    terms = partnership(
        LP_GP,
        (
            hurdle("either", 10, of_partner("lp"), (moic("zero", 1.0), compound("irr", 0.2)), split(lp=0.9, gp=0.1), combinator=ANY),
            residual("residual", 20, split(lp=0.5, gp=0.5)),
        ),
        bench=BENCH_90_10,
        participants=(),
    )
    tiers = by_tier(run(terms, -1_000_000.0, 1_000_000.0, 500_000.0))
    assert close(tiers["either"].amounts[1], 1_000_000.0)
    assert tiers["either"].amounts[2] == 0.0 and close(tiers["residual"].amounts[2], 500_000.0)
    period_two = {record.condition_id: record.capacity_at_entry for record in tiers["either"].conditions if record.period == 2}
    assert period_two["zero"] == 0.0 and period_two["irr"] > 0.0  # type: ignore[operator]


def test_all_needs_every_condition() -> None:
    from _p7_9_fixtures import LP_GP, BENCH_90_10, hurdle, of_partner, partnership, residual, run, split  # type: ignore[import-not-found]

    terms = partnership(
        LP_GP,
        (
            hurdle("both", 10, of_partner("lp"), (moic("zero", 1.0), compound("irr", 0.2)), split(lp=0.9, gp=0.1), combinator=ALL),
            residual("residual", 20, split(lp=0.5, gp=0.5)),
        ),
        bench=BENCH_90_10,
        participants=(),
    )
    tiers = by_tier(run(terms, -1_000_000.0, 1_000_000.0, 500_000.0))
    assert tiers["both"].amounts[2] > 0.0
