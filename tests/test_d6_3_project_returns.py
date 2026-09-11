"""Phase 6 Gate D6.3 -- project returns, equity requirements and IRR status.

Governed by ``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Sections 7-9
and ``docs/financial_conventions.md`` "IRR validity" / "IRR numerical
solution"; those documents govern on any discrepancy.

What fails silently if wrong, and is therefore asserted here:

- **Every summary figure is read off the Equity Cash Flow, by sign.** Net
  Additional Equity is the *net* deficit of a year, whatever caused it --
  project capital, an owner expense or the rent roll's TI/LC -- never the
  gross spend (Part G).
- **The Equity Multiple and the summary share one decomposition.** Whenever
  the multiple is reported it is ``TCR / TEI`` to the bit.
- **The IRR is unchanged and now explained.** ``evaluate_irr`` returns exactly
  ``calculate_irr``'s value; every outcome of the frozen procedure has one
  status, and every status has a row in the branch matrix below.

Bit identity of IRR and equity multiple against b828956 is proved separately
by ``tests/test_d6_3_baseline_oracle.py``.
"""

from __future__ import annotations

import dataclasses
import json
from typing import NamedTuple

import pytest

from anchor.engine import returns as returns_module
from anchor.engine.contracts import AcquisitionResults, IrrStatus, ReturnMetrics
from anchor.engine.returns import (
    calculate_equity_multiple,
    calculate_irr,
    calculate_net_additional_equity_requirement_by_year,
    calculate_project_return_totals,
    calculate_return_metrics,
    evaluate_irr,
)

# The three operating-mode fixtures and the plan helpers are D6.2's, reused so
# both gates reason about the same deals.
from test_d6_2_owner_cash_flow_engine import (
    HOLD,
    LENDER_EXIT_AND_PROPERTY_FIELDS,
    MODES,
    bits,
    capital,
    expense,
    field_bits,
    plan,
    run,
)

#: The six result fields D6.3 adds.
D6_3_FIELDS = (
    "net_additional_equity_requirement_by_year",
    "total_equity_invested",
    "total_cash_returned",
    "total_profit",
    "unlevered_irr_status",
    "levered_irr_status",
)


def summary(levered_cash_flows: tuple[float, ...]) -> dict[str, object]:
    total_cash_returned, total_equity_invested, total_profit = (
        calculate_project_return_totals(levered_cash_flows=levered_cash_flows)
    )
    return {
        "tcr": total_cash_returned,
        "tei": total_equity_invested,
        "profit": total_profit,
        "naer": calculate_net_additional_equity_requirement_by_year(
            levered_cash_flows=levered_cash_flows
        ),
        "em": calculate_equity_multiple(levered_cash_flows=levered_cash_flows),
    }


# =============================================================================
# R1 / R2 -- the two reference profiles, on the return helpers directly
# =============================================================================


def test_r1_a_single_investment_profile() -> None:
    flows = (-10.0, 0.6, 0.6, 10.6)
    result = summary(flows)

    assert result["tei"] == 10.0
    assert result["tcr"] == pytest.approx(11.8, abs=1e-12)
    assert result["profit"] == result["tcr"] - result["tei"]
    assert result["profit"] == pytest.approx(1.8, abs=1e-12)
    assert result["naer"] == (0.0, 0.0, 0.0)
    assert result["em"] == result["tcr"] / result["tei"]
    assert result["em"] == pytest.approx(1.18, abs=1e-12)

    irr, status = evaluate_irr(flows)
    assert status is IrrStatus.DEFINED
    assert irr is not None and irr == calculate_irr(flows)


def test_r2_the_value_add_profile_has_a_multiple_and_no_irr() -> None:
    """(-10, +0.6, -0.4, +10.6): Year 2 needs 0.4 of additional equity, the
    multiple is 11.2 / 10.4, and -- although this profile has one economic
    root -- two sign changes mean the frozen convention reports no IRR. D6.3
    explains that; it does not change it."""

    flows = (-10.0, 0.6, -0.4, 10.6)
    result = summary(flows)

    assert result["naer"] == (0.0, 0.4, 0.0)
    assert result["tei"] == pytest.approx(10.4, abs=1e-12)
    assert result["tcr"] == pytest.approx(11.2, abs=1e-12)
    assert result["profit"] == result["tcr"] - result["tei"]
    assert result["profit"] == pytest.approx(0.8, abs=1e-12)
    assert result["em"] == result["tcr"] / result["tei"]
    assert result["em"] == pytest.approx(11.2 / 10.4, abs=1e-12)

    assert calculate_irr(flows) is None
    assert evaluate_irr(flows) == (None, IrrStatus.MULTIPLE_SIGN_CHANGES)


# =============================================================================
# Part M -- the IRR status branch matrix: every status, every None path
# =============================================================================


class Row(NamedTuple):
    cash_flows: tuple[float, ...]
    status: IrrStatus
    why: str


BRANCH_MATRIX = {
    "defined-conventional": Row(
        (-100.0, 60.0, 60.0), IrrStatus.DEFINED, "valid series; bisection converges"
    ),
    "defined-exact-root-at-x-1": Row(
        (-100.0, 100.0), IrrStatus.DEFINED, "F(1) == 0 exactly; returned before bisection"
    ),
    "defined-exact-root-at-the-bound": Row(
        (-1e12, 1.0), IrrStatus.DEFINED, "the 1e12 boundary is evaluated and is an exact root"
    ),
    "defined-after-leading-zero": Row(
        (0.0, -100.0, 150.0), IrrStatus.DEFINED, "t0 is the first nonzero period"
    ),
    "defined-after-leading-signed-zero": Row(
        (-0.0, -5.0, 6.0), IrrStatus.DEFINED, "-0.0 is zero, so t0 is period 1"
    ),
    "no-nonzero-all-zero": Row(
        (0.0, 0.0, 0.0), IrrStatus.NO_NONZERO_CASH_FLOW, "no first nonzero index"
    ),
    "no-nonzero-empty": Row((), IrrStatus.NO_NONZERO_CASH_FLOW, "no periods at all"),
    "no-nonzero-signed-zeros": Row(
        (-0.0, 0.0), IrrStatus.NO_NONZERO_CASH_FLOW, "-0.0 != 0.0 is False"
    ),
    "first-nonzero-positive": Row(
        (100.0, -60.0, -60.0),
        IrrStatus.FIRST_NONZERO_NOT_NEGATIVE,
        "cash_flows[t0] >= 0.0 is the first validity check",
    ),
    "first-nonzero-positive-no-negative-at-all": Row(
        (100.0, 50.0, 20.0),
        IrrStatus.FIRST_NONZERO_NOT_NEGATIVE,
        "an all-positive series fails the first check before any other",
    ),
    "first-nonzero-positive-after-leading-zero": Row(
        (0.0, 100.0, -50.0, -60.0),
        IrrStatus.FIRST_NONZERO_NOT_NEGATIVE,
        "leading zeros are skipped; the first nonzero is positive",
    ),
    "first-nonzero-positive-despite-two-sign-changes": Row(
        (5.0, -3.0, 4.0),
        IrrStatus.FIRST_NONZERO_NOT_NEGATIVE,
        "checks run in order: the first-nonzero rule fails before sign changes are counted",
    ),
    "no-positive": Row(
        (-100.0, -50.0, -20.0), IrrStatus.NO_POSITIVE_CASH_FLOW, "has_positive stays False"
    ),
    "no-positive-trailing-zero": Row(
        (-5.0, 0.0), IrrStatus.NO_POSITIVE_CASH_FLOW, "zeros are ignored for the sign rules"
    ),
    "multiple-sign-changes-value-add": Row(
        (-10.0, 0.6, -0.4, 10.6), IrrStatus.MULTIPLE_SIGN_CHANGES, "sign_changes == 3"
    ),
    "multiple-sign-changes-classic": Row(
        (-100.0, 50.0, -20.0, 90.0), IrrStatus.MULTIPLE_SIGN_CHANGES, "sign_changes == 3"
    ),
    "root-outside-search-domain": Row(
        (-1.0, 1e-13),
        IrrStatus.ROOT_OUTSIDE_SEARCH_DOMAIN,
        "root at x = 1e13; F(1e12) < 0 and x_high >= 1e12 ends the expansion",
    ),
    "numerical-failure-overflow": Row(
        (-1e308, 1e308, 1e308),
        IrrStatus.NUMERICAL_FAILURE,
        "F(1) overflows to inf: a non-finite Horner evaluation",
    ),
}


@pytest.mark.parametrize("name", sorted(BRANCH_MATRIX))
def test_the_branch_matrix(name: str) -> None:
    row = BRANCH_MATRIX[name]
    value, status = evaluate_irr(row.cash_flows)

    assert status is row.status, row.why
    # The status never describes a different computation from the value.
    assert value == calculate_irr(row.cash_flows)
    assert (value is not None) == (status is IrrStatus.DEFINED)


def test_every_status_has_a_row_and_every_row_a_status() -> None:
    assert {row.status for row in BRANCH_MATRIX.values()} == set(IrrStatus)
    assert [member.value for member in IrrStatus] == [
        "defined",
        "no_nonzero_cash_flow",
        "first_nonzero_not_negative",
        "no_positive_cash_flow",
        "multiple_sign_changes",
        "root_outside_search_domain",
        "numerical_failure",
    ]


def test_the_conversion_guard_reports_numerical_failure(monkeypatch) -> None:
    """The defensive guard after the solver: if a root ever failed to convert
    to a finite rate, the value is ``None`` and the status says so. Forced,
    because with finite inputs the frozen solver cannot reach it."""

    monkeypatch.setattr(returns_module, "_convert_x_star_to_irr", lambda x_star: None)

    assert evaluate_irr((-100.0, 60.0, 60.0)) == (None, IrrStatus.NUMERICAL_FAILURE)
    assert calculate_irr((-100.0, 60.0, 60.0)) is None


# =============================================================================
# R10 / Part I -- zero and sign semantics
# =============================================================================


def test_zero_periods_count_on_neither_side() -> None:
    result = summary((-10.0, 0.0, 12.0, 0.0))

    assert (result["tei"], result["tcr"]) == (10.0, 12.0)
    assert result["naer"] == (0.0, 0.0, 0.0)


def test_a_negative_zero_year_is_no_requirement_and_is_positive_zero() -> None:
    result = summary((-10.0, -0.0, 12.0))

    assert result["tei"] == 10.0
    assert [value.hex() for value in result["naer"]] == [(0.0).hex(), (0.0).hex()]


@pytest.mark.parametrize(
    ("flows", "tcr", "tei", "em", "naer", "status"),
    [
        pytest.param(
            (5.0, 6.0), 11.0, 0.0, None, (0.0,), IrrStatus.FIRST_NONZERO_NOT_NEGATIVE, id="all-positive"
        ),
        pytest.param(
            (-5.0, -6.0), 0.0, 11.0, 0.0, (6.0,), IrrStatus.NO_POSITIVE_CASH_FLOW, id="all-negative"
        ),
        pytest.param(
            (0.0, 0.0), 0.0, 0.0, None, (0.0,), IrrStatus.NO_NONZERO_CASH_FLOW, id="all-zero"
        ),
        pytest.param(
            (5.0, -3.0, 4.0), 9.0, 3.0, 3.0, (3.0, 0.0), IrrStatus.FIRST_NONZERO_NOT_NEGATIVE,
            id="positive-t0-counted-as-returned",
        ),
    ],
)
def test_degenerate_profiles(flows, tcr, tei, em, naer, status) -> None:
    result = summary(flows)

    assert (result["tcr"], result["tei"], result["em"], result["naer"]) == (tcr, tei, em, naer)
    assert result["profit"] == tcr - tei
    assert isinstance(result["tcr"], float) and isinstance(result["tei"], float)
    assert evaluate_irr(flows)[1] is status


# =============================================================================
# Part K -- identities
# =============================================================================

#: Every non-empty branch-matrix series whose signed sums stay finite, plus a
#: few more. The one overflowing series is handled on its own below.
IDENTITY_SERIES = [
    row.cash_flows
    for name, row in BRANCH_MATRIX.items()
    if row.cash_flows and name != "numerical-failure-overflow"
] + [
    (-10.0, 0.6, 0.6, 10.6),
    (-3.0, -1.0, 2.0, -0.5, 9.0),
    (0.0, -7.0, 0.0, 8.5),
]


def test_a_non_finite_total_is_refused_not_reported() -> None:
    """(-1e308, +1e308, +1e308): the positive sum overflows. The Equity
    Multiple -- an optional figure -- has always reported ``None`` here and
    still does. Total Cash Returned is a required figure, so, like every other
    required engine figure, it is refused with ``NonFiniteResultError`` rather
    than reported as infinity (the Phase 2A non-finite rule). No engine deal
    reaches this: cash flows of that size overflow earlier calculations."""

    from anchor.engine.contracts import NonFiniteResultError

    flows = (-1e308, 1e308, 1e308)
    assert calculate_equity_multiple(levered_cash_flows=flows) is None
    with pytest.raises(NonFiniteResultError, match="total_cash_returned"):
        calculate_project_return_totals(levered_cash_flows=flows)


@pytest.mark.parametrize("flows", IDENTITY_SERIES, ids=str)
def test_the_summary_identities_hold_on_the_return_helpers(flows) -> None:
    result = summary(flows)

    assert result["tei"] >= 0.0 and result["tcr"] >= 0.0
    assert result["profit"] == result["tcr"] - result["tei"]
    if result["em"] is not None:
        assert result["em"] == result["tcr"] / result["tei"]
    if result["tei"] == 0.0:
        assert result["em"] is None
    assert len(result["naer"]) == len(flows) - 1
    assert all(value >= 0.0 for value in result["naer"])


@pytest.mark.parametrize(
    "plan_name", ["empty", "year_2_deficit", "final_year_deficit", "owner_expense_deficit"]
)
@pytest.mark.parametrize("mode", MODES)
def test_total_equity_invested_is_initial_plus_net_additional_equity(
    mode: str, plan_name: str
) -> None:
    """Ratified in Section 8 as a tolerance identity. It holds for engine results
    because the Equity Cash Flow's ``T0`` is ``-initial_equity``, never
    positive. It is not a property of arbitrary series -- see
    ``positive-t0-counted-as-returned`` above -- so it is asserted only here."""

    results = run(mode, ENGINE_PLANS[plan_name](mode))

    assert results.levered_cash_flows[0] == -results.initial_equity
    assert results.total_equity_invested == pytest.approx(
        results.initial_equity + sum(results.net_additional_equity_requirement_by_year),
        rel=1e-12,
        abs=1e-6,
    )
    if results.equity_multiple is not None:
        assert results.equity_multiple == (
            results.total_cash_returned / results.total_equity_invested
        )
    assert results.total_profit == results.total_cash_returned - results.total_equity_invested


# =============================================================================
# Part O -- one authority: ReturnMetrics, threaded unchanged
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_result_fields_are_return_metrics_threaded_unchanged(mode: str) -> None:
    results = run(mode, ENGINE_PLANS["year_2_deficit"](mode))
    metrics = calculate_return_metrics(
        noi_by_year=results.noi_by_year,
        annual_debt_service=results.annual_debt_service,
        unlevered_cash_flows=results.unlevered_cash_flows,
        levered_cash_flows=results.levered_cash_flows,
    )

    assert isinstance(metrics, ReturnMetrics)
    for name in D6_3_FIELDS + ("equity_multiple", "levered_irr", "unlevered_irr"):
        assert bits(getattr(results, name)) == bits(getattr(metrics, name)), name
    assert (results.levered_irr, results.levered_irr_status) == evaluate_irr(
        results.levered_cash_flows
    )
    assert (results.unlevered_irr, results.unlevered_irr_status) == evaluate_irr(
        results.unlevered_cash_flows
    )
    assert len(results.net_additional_equity_requirement_by_year) == HOLD


# =============================================================================
# Engine reference cases R3-R9
# =============================================================================


def _plan_year_2_deficit(mode: str):
    base = run(mode)
    return plan(capital(18, base.levered_cash_flows[2] + 250_000.0))


def _plan_final_year_deficit(mode: str):
    base = run(mode)
    return plan(capital(12 * HOLD, base.levered_cash_flows[HOLD] + 1_000_000.0))


def _plan_owner_expense_deficit(mode: str):
    """An owner expense in Year 3 that leaves that year 50,000 short. The
    Lease-Level deal's Year 3 is already short (TI/LC), so only the positive
    part of the year is offset there -- the expense is never negative."""

    base = run(mode)
    return plan(expense(max(base.levered_cash_flows[3], 0.0) + 50_000.0, 3, 3))


ENGINE_PLANS = {
    "empty": lambda mode: plan(),
    "year_2_deficit": _plan_year_2_deficit,
    "final_year_deficit": _plan_final_year_deficit,
    "owner_expense_deficit": _plan_owner_expense_deficit,
}


@pytest.mark.parametrize("mode", ["quick", "detailed"])
def test_the_base_deals_need_no_additional_equity(mode: str) -> None:
    results = run(mode)

    assert all(flow > 0.0 for flow in results.levered_cash_flows[1:])
    assert results.net_additional_equity_requirement_by_year == (0.0,) * HOLD
    assert results.total_equity_invested == results.initial_equity
    assert results.levered_irr_status is IrrStatus.DEFINED
    assert results.unlevered_irr_status is IrrStatus.DEFINED


@pytest.mark.parametrize("mode", ["quick", "detailed"])
def test_r3_closing_capital_raises_equity_invested_and_no_annual_requirement(
    mode: str,
) -> None:
    amount = 1_000_000.0
    base, results = run(mode), run(mode, plan(capital(0, amount)))

    assert results.initial_equity == base.initial_equity + amount
    assert results.total_equity_invested == results.initial_equity
    assert results.total_equity_invested - base.total_equity_invested == pytest.approx(
        amount, abs=1e-6
    )
    assert results.net_additional_equity_requirement_by_year == (0.0,) * HOLD
    assert bits(results.total_cash_returned) == bits(base.total_cash_returned)


@pytest.mark.parametrize("mode", MODES)
def test_r4_project_capital_covered_by_operations_needs_no_additional_equity(
    mode: str,
) -> None:
    base = run(mode)
    assert base.levered_cash_flows[2] > 0.0
    amount = base.levered_cash_flows[2] / 2.0
    results = run(mode, plan(capital(18, amount)))

    assert results.project_capital_by_year[1] == amount
    assert results.levered_cash_flows[2] > 0.0
    # Net, not gross: the year still nets positive, so Year 2 needs nothing.
    assert results.net_additional_equity_requirement_by_year[1] == 0.0
    assert bits(results.net_additional_equity_requirement_by_year) == bits(
        base.net_additional_equity_requirement_by_year
    )
    assert bits(results.total_equity_invested) == bits(base.total_equity_invested)
    assert base.total_cash_returned - results.total_cash_returned == pytest.approx(
        amount, abs=1e-6
    )


@pytest.mark.parametrize("mode", MODES)
def test_r5_project_capital_beyond_cash_generation_needs_the_deficit_only(
    mode: str,
) -> None:
    base = run(mode)
    results = run(mode, ENGINE_PLANS["year_2_deficit"](mode))
    gross = results.project_capital_by_year[1]

    assert results.levered_cash_flows[2] < 0.0
    assert results.net_additional_equity_requirement_by_year[1] == -results.levered_cash_flows[2]
    assert results.net_additional_equity_requirement_by_year[1] == pytest.approx(
        250_000.0, abs=1e-6
    )
    assert results.net_additional_equity_requirement_by_year[1] < gross
    # The other years are exactly the base deal's.
    for year in (0, 2, 3, 4):
        assert bits(results.net_additional_equity_requirement_by_year[year]) == bits(
            base.net_additional_equity_requirement_by_year[year]
        )
    # Quick and Detailed were positive every year, so the deficit adds two sign
    # changes and the IRR becomes unavailable. The Lease-Level deal was already
    # short in Years 1 and 3 (TI/LC); a Year 2 deficit between them adds no
    # sign change, so its IRR stays defined -- the requirement is reported
    # either way.
    expected = {
        "quick": IrrStatus.MULTIPLE_SIGN_CHANGES,
        "detailed": IrrStatus.MULTIPLE_SIGN_CHANGES,
        "lease_level": IrrStatus.DEFINED,
    }[mode]
    assert results.levered_irr_status is expected
    assert (results.levered_irr is None) == (expected is not IrrStatus.DEFINED)


@pytest.mark.parametrize("mode", ["quick", "detailed"])
def test_r6_an_owner_expense_deficit_is_additional_equity(mode: str) -> None:
    results = run(mode, ENGINE_PLANS["owner_expense_deficit"](mode))

    assert results.project_capital_by_year == (0.0,) * HOLD
    assert results.owner_expenses_by_year[2] > 0.0
    assert results.levered_cash_flows[3] < 0.0
    assert results.net_additional_equity_requirement_by_year == (
        0.0,
        0.0,
        -results.levered_cash_flows[3],
        0.0,
        0.0,
    )
    assert results.net_additional_equity_requirement_by_year[2] == pytest.approx(
        50_000.0, abs=1e-6
    )


def test_r7_lease_level_ti_lc_deficits_are_additional_equity() -> None:
    """The Lease-Level fixture needs additional equity with no Business Plan at
    all: its lease-up and rollover TI/LC outrun operations in two years. The
    metric reports those deficits, and nothing calls them project capital."""

    results = run("lease_level")

    assert results.project_capital_by_year == (0.0,) * HOLD
    assert results.owner_expenses_by_year == (0.0,) * HOLD
    deficit_years = [
        year for year in range(HOLD) if results.levered_cash_flows[year + 1] < 0.0
    ]
    assert deficit_years, "the fixture must have a TI/LC-driven deficit"
    for year in range(HOLD):
        expected = -results.levered_cash_flows[year + 1] if year in deficit_years else 0.0
        assert results.net_additional_equity_requirement_by_year[year] == expected
    for year in deficit_years:
        assert (
            results.tenant_improvements_by_year[year] + results.leasing_commissions_by_year[year]
            > 0.0
        )
    assert results.total_equity_invested > results.initial_equity
    assert results.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES


@pytest.mark.parametrize("mode", MODES)
def test_r8_a_final_year_can_need_equity_even_with_the_sale(mode: str) -> None:
    base = run(mode)
    results = run(mode, ENGINE_PLANS["final_year_deficit"](mode))

    assert bits(results.exit_value) == bits(base.exit_value)
    assert bits(results.net_sale_proceeds) == bits(base.net_sale_proceeds)
    assert results.levered_cash_flows[HOLD] < 0.0
    assert results.net_additional_equity_requirement_by_year[-1] == (
        -results.levered_cash_flows[HOLD]
    )
    assert results.net_additional_equity_requirement_by_year[-1] == pytest.approx(
        1_000_000.0, abs=1e-6
    )
    assert results.total_equity_invested == pytest.approx(
        results.initial_equity + sum(results.net_additional_equity_requirement_by_year),
        rel=1e-12,
        abs=1e-6,
    )
    assert results.levered_irr is None
    assert results.levered_irr_status is IrrStatus.MULTIPLE_SIGN_CHANGES


@pytest.mark.parametrize("mode", MODES)
def test_r9_post_hold_capital_moves_no_project_return_figure(mode: str) -> None:
    base = run(mode)
    results = run(mode, plan(capital(12 * HOLD + 1, 5_000_000.0)))

    for name in D6_3_FIELDS:
        assert bits(getattr(results, name)) == bits(getattr(base, name)), name
    assert field_bits(results, exclude=frozenset({"post_hold_project_capital"})) == field_bits(
        base, exclude=frozenset({"post_hold_project_capital"})
    )


# =============================================================================
# Part Q -- a narrow lender and exit regression
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_project_returns_move_nothing_a_lender_or_the_sale_computes(mode: str) -> None:
    base = run(mode)
    results = run(mode, ENGINE_PLANS["final_year_deficit"](mode))

    for name in LENDER_EXIT_AND_PROPERTY_FIELDS:
        assert bits(getattr(results, name)) == bits(getattr(base, name)), name


# =============================================================================
# Part R / Part T -- AI exclusion and snapshot behaviour
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_the_project_return_fields_do_not_reach_the_ai_analyst(mode: str) -> None:
    from anchor.ai.presentation import INTENTIONALLY_EXCLUDED_RESULT_FIELDS, _format_results

    formatted = _format_results(run(mode, ENGINE_PLANS["year_2_deficit"](mode)))

    assert not set(formatted) & set(D6_3_FIELDS)
    assert set(D6_3_FIELDS) <= INTENTIONALLY_EXCLUDED_RESULT_FIELDS


def test_a_pre_d6_3_snapshot_decodes_as_absent_and_a_current_one_round_trips() -> None:
    from anchor.deals.store import (
        _ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
        _decode_snapshot,
        _quick_analysis_snapshot_from_dict,
    )

    def decode(raw: dict) -> object:
        return _decode_snapshot(
            raw_json=json.dumps(raw),
            stored_schema_version=_ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
            current_schema_version=_ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
            stored_fingerprint="unchanged-assumptions",
            expected_fingerprint="unchanged-assumptions",
            decoder=_quick_analysis_snapshot_from_dict,
        )

    results = run("quick")
    current = json.loads(json.dumps(dataclasses.asdict(results)))
    pre_d6_3 = {name: value for name, value in current.items() if name not in D6_3_FIELDS}

    # An older stored result lacks the D6.3 fields: absent, never fabricated.
    assert decode(pre_d6_3) is None
    # A current one round-trips. The statuses serialise as their string values
    # and, because ``IrrStatus`` is a ``StrEnum``, compare equal on the way back.
    assert current["levered_irr_status"] == "defined"
    decoded = decode(current)
    assert decoded == results
    assert decoded.levered_irr_status == IrrStatus.DEFINED  # type: ignore[union-attr]
    assert _ANALYSIS_SNAPSHOT_SCHEMA_VERSION == 1

    for field in dataclasses.fields(AcquisitionResults):
        if field.name in D6_3_FIELDS:
            assert field.default is dataclasses.MISSING, field.name
