"""Sprint D Gate D4.5A -- the generic operating-capital cash-flow channel.

Governed by
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 17.2-17.6 and 22 (HD-D4-3, HD-1).

The channel is **generic**. The engine receives an ``OperatingCapitalSchedule``
and subtracts it; it never learns that the dollars are tenant improvements and
leasing commissions produced by a rollover model. The claims that fail silently
if wrong:

- **absent means absent** -- Quick and Detailed pass nothing and their
  economics are bit-identical to the pre-channel engine;
- **it is below NOI** -- ``noi_by_year``, ``exit_noi``, ``exit_value``, the
  debt schedule, DSCR and debt yield are all untouched, because a lender's
  coverage test is an NOI test;
- **it is separate from CapEx** -- the two are additive, never merged;
- **it reaches returns through the authoritative cash flows only** -- IRR,
  equity multiple and the owner-return series move because the cash flows
  moved, never because a metric was patched.
"""

from __future__ import annotations

import dataclasses

import pytest

from anchor.contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    acquisition_terms_from_inputs,
)
from anchor.engine.acquisition import (
    analyze_acquisition,
    analyze_acquisition_from_operating_projection,
    analyze_detailed_acquisition_with_projection,
    calculate_levered_cash_flows,
    calculate_operating_capital_by_year,
    calculate_unlevered_cash_flows,
)
from anchor.engine.contracts import (
    AcquisitionResults,
    NonFiniteResultError,
    OperatingCapitalSchedule,
)
from anchor.engine.debt import calculate_debt_schedule
from anchor.engine.returns import (
    calculate_owner_return_metrics,
    calculate_recurring_levered_cash_flows,
    calculate_recurring_unlevered_cash_flows,
)


# =============================================================================
# Fixtures
# =============================================================================


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _StubProjection:
    """A structural ``OperatingProjectionLike``.

    Proves the channel is genuinely mode-agnostic: the engine accepts any
    object carrying the three protocol fields, with no import of
    ``anchor.leasing`` and no Detailed-only field fabricated.
    """

    noi_by_year: tuple[float, ...]
    exit_noi: float
    going_in_cap_rate: float


HOLD = 3
PRICE = 10_000.0


def terms(**overrides: object) -> AcquisitionTerms:
    base: dict[str, object] = {
        "purchase_price": PRICE,
        "hold_period": HOLD,
        "exit_cap_rate": 0.10,
        "ltv": 0.60,
        "interest_rate": 0.05,
        "amortization": 30,
        "acquisition_cost_pct": 0.02,
        "financing_fee_pct": 0.01,
        "disposition_cost_pct": 0.015,
        "annual_capex_reserve": 20.0,
        "io_period": 0,
    }
    base.update(overrides)
    return AcquisitionTerms(**base)  # type: ignore[arg-type]


def projection(noi: float = 120.0, *, hold_period: int = HOLD) -> _StubProjection:
    return _StubProjection(
        noi_by_year=tuple(noi for _ in range(hold_period)),
        exit_noi=noi,
        going_in_cap_rate=noi / PRICE,
    )


def schedule(ti: float, lc: float, *, hold_period: int = HOLD) -> OperatingCapitalSchedule:
    return OperatingCapitalSchedule(
        tenant_improvements_by_year=tuple(ti for _ in range(hold_period)),
        leasing_commissions_by_year=tuple(lc for _ in range(hold_period)),
    )


def hexes(values) -> list[str | None]:
    return [None if value is None else value.hex() for value in values]


def quick_inputs(**overrides: object) -> AcquisitionInputs:
    base: dict[str, object] = {
        "purchase_price": 40_000_000.0,
        "current_noi": 2_600_000.0,
        "occupancy": 0.93,
        "noi_growth": 0.03,
        "hold_period": 5,
        "exit_cap_rate": 0.065,
        "ltv": 0.65,
        "interest_rate": 0.055,
        "amortization": 30,
        "acquisition_cost_pct": 0.02,
        "financing_fee_pct": 0.01,
        "disposition_cost_pct": 0.015,
        "annual_capex_reserve": 120_000.0,
        "io_period": 1,
    }
    base.update(overrides)
    return AcquisitionInputs(**base)  # type: ignore[arg-type]


#: Every float-bearing field of ``AcquisitionResults`` that predates D4.5A.
#: The two new fields are excluded because they did not exist to compare.
_PRE_D4_5A_FIELDS = tuple(
    name
    for name in (field.name for field in dataclasses.fields(AcquisitionResults))
    if name not in {"tenant_improvements_by_year", "leasing_commissions_by_year"}
)


def snapshot(results: AcquisitionResults) -> dict[str, object]:
    """Every pre-D4.5A result value, encoded as ``float.hex()``."""

    encoded: dict[str, object] = {}
    for name in _PRE_D4_5A_FIELDS:
        value = getattr(results, name)
        if isinstance(value, float):
            encoded[name] = value.hex()
        elif isinstance(value, tuple):
            encoded[name] = hexes(value)
        else:
            encoded[name] = value
    return encoded


# =============================================================================
# G1 / G2 -- absence and explicit zero preserve the prior engine exactly
# =============================================================================


def test_g1_omitting_the_schedule_preserves_every_prior_result() -> None:
    """The default path is the old path. Nothing about the new parameter's
    existence may move a number."""

    without = analyze_acquisition_from_operating_projection(projection(), terms())
    explicit_none = analyze_acquisition_from_operating_projection(
        projection(), terms(), None
    )

    assert snapshot(without) == snapshot(explicit_none)


def test_g2_an_explicit_all_zero_schedule_equals_the_absent_case() -> None:
    """``x - 0.0 == x`` exactly in IEEE-754, so materialising zeros cannot
    drift. Asserted, not assumed."""

    without = analyze_acquisition_from_operating_projection(projection(), terms())
    zeros = analyze_acquisition_from_operating_projection(
        projection(), terms(), schedule(0.0, 0.0)
    )

    assert snapshot(without) == snapshot(zeros)


@pytest.mark.parametrize("hold_period", [1, 2, 3, 5, 10])
@pytest.mark.parametrize("ltv", [0.0, 0.65])
@pytest.mark.parametrize("noi", [0.0, 120.0, -50.0])
def test_g2_zero_equals_absent_across_a_matrix(
    hold_period: int, ltv: float, noi: float
) -> None:
    deal_terms = terms(hold_period=hold_period, ltv=ltv)
    stub = projection(noi, hold_period=hold_period)

    without = analyze_acquisition_from_operating_projection(stub, deal_terms)
    zeros = analyze_acquisition_from_operating_projection(
        stub, deal_terms, schedule(0.0, 0.0, hold_period=hold_period)
    )

    assert snapshot(without) == snapshot(zeros)


def test_g1_the_new_result_fields_are_zeros_when_no_schedule_is_supplied() -> None:
    results = analyze_acquisition_from_operating_projection(projection(), terms())

    assert results.tenant_improvements_by_year == (0.0, 0.0, 0.0)
    assert results.leasing_commissions_by_year == (0.0, 0.0, 0.0)


# =============================================================================
# G3-G7 -- the authoritative cash-flow arithmetic
# =============================================================================


def test_g3_recurring_unlevered_cash_flow_falls_by_the_operating_capital() -> None:
    """NOI 120, CapEx 20 -> 100 before operating capital. With 30 of capital,
    70."""

    before = calculate_recurring_unlevered_cash_flows(
        noi_by_year=(120.0,), capex_by_year=(20.0,)
    )
    after = calculate_recurring_unlevered_cash_flows(
        noi_by_year=(120.0,), capex_by_year=(20.0,), operating_capital_by_year=(30.0,)
    )

    assert before == (100.0,)
    assert after == (70.0,)


def test_g4_recurring_levered_cash_flow_falls_by_the_operating_capital() -> None:
    """NOI 120, CapEx 20, debt service 40 -> 60 before. With 30, 30. The debt
    service term itself is untouched."""

    before = calculate_recurring_levered_cash_flows(
        noi_by_year=(120.0,), capex_by_year=(20.0,), annual_debt_service=(40.0,)
    )
    after = calculate_recurring_levered_cash_flows(
        noi_by_year=(120.0,),
        capex_by_year=(20.0,),
        annual_debt_service=(40.0,),
        operating_capital_by_year=(30.0,),
    )

    assert before == (60.0,)
    assert after == (30.0,)


def test_g5_the_component_total_is_ti_plus_lc_once() -> None:
    """TI 20 + LC 10 is a 30 reduction -- not 20, not 10, and not 60."""

    total = calculate_operating_capital_by_year(
        operating_capital=schedule(20.0, 10.0, hold_period=1), hold_period=1
    )

    assert total == (30.0,)


def test_g5_the_reduction_is_the_component_total_end_to_end() -> None:
    baseline = analyze_acquisition_from_operating_projection(projection(), terms())
    with_capital = analyze_acquisition_from_operating_projection(
        projection(), terms(), schedule(20.0, 10.0)
    )

    for year in range(HOLD):
        assert with_capital.unlevered_cash_flows[year + 1] == pytest.approx(
            baseline.unlevered_cash_flows[year + 1] - 30.0, abs=1e-9
        )


def test_g6_capex_and_operating_capital_are_additive_and_distinct() -> None:
    """CapEx 20 and operating capital 30 burden the year by 50 -- never 20
    alone, never 30 alone, and never a merged or double-counted figure."""

    recurring = calculate_recurring_unlevered_cash_flows(
        noi_by_year=(120.0,), capex_by_year=(20.0,), operating_capital_by_year=(30.0,)
    )

    assert recurring == (70.0,)
    assert 120.0 - recurring[0] == pytest.approx(50.0, abs=1e-9)


def test_g6_capex_by_year_still_reports_the_reserve_alone() -> None:
    """The two channels never merge: ``capex_by_year`` keeps reporting
    ``annual_capex_reserve`` and nothing else."""

    results = analyze_acquisition_from_operating_projection(
        projection(), terms(annual_capex_reserve=20.0), schedule(1_000.0, 500.0)
    )

    assert results.capex_by_year == (20.0, 20.0, 20.0)


def test_g7_final_year_operating_capital_survives_alongside_the_sale() -> None:
    """A final-year TI cheque is still the seller's, even though the sale
    happens that year. It reduces the recurring portion and never the sale
    proceeds."""

    baseline = analyze_acquisition_from_operating_projection(projection(), terms())
    with_capital = analyze_acquisition_from_operating_projection(
        projection(), terms(), schedule(15.0, 10.0)
    )

    assert with_capital.unlevered_cash_flows[HOLD] == pytest.approx(
        baseline.unlevered_cash_flows[HOLD] - 25.0, abs=1e-9
    )
    assert with_capital.levered_cash_flows[HOLD] == pytest.approx(
        baseline.levered_cash_flows[HOLD] - 25.0, abs=1e-9
    )
    # The sale itself is untouched.
    assert with_capital.exit_value.hex() == baseline.exit_value.hex()
    assert with_capital.net_sale_proceeds.hex() == baseline.net_sale_proceeds.hex()


def test_g7_final_year_capital_is_not_taken_out_of_sale_proceeds() -> None:
    """Recurring ownership and terminal sale stay conceptually separate."""

    with_capital = analyze_acquisition_from_operating_projection(
        projection(), terms(), schedule(15.0, 10.0)
    )

    assert with_capital.net_sale_proceeds == pytest.approx(
        with_capital.exit_value
        - with_capital.disposition_costs
        - with_capital.remaining_loan_balance,
        abs=1e-9,
    )


def test_the_unlevered_series_reduces_every_hold_year_exactly_once() -> None:
    baseline = calculate_unlevered_cash_flows(
        purchase_price=PRICE,
        noi_by_year=(120.0, 120.0, 120.0),
        exit_value=1_200.0,
        capex_by_year=(20.0, 20.0, 20.0),
    )
    with_capital = calculate_unlevered_cash_flows(
        purchase_price=PRICE,
        noi_by_year=(120.0, 120.0, 120.0),
        exit_value=1_200.0,
        capex_by_year=(20.0, 20.0, 20.0),
        operating_capital_by_year=(30.0, 30.0, 30.0),
    )

    assert with_capital[0] == baseline[0]
    for year in (1, 2, 3):
        assert with_capital[year] == pytest.approx(baseline[year] - 30.0, abs=1e-9)


def test_the_levered_series_reduces_every_hold_year_exactly_once() -> None:
    baseline = calculate_levered_cash_flows(
        initial_equity=4_000.0,
        noi_by_year=(120.0, 120.0, 120.0),
        annual_debt_service=(40.0, 40.0, 40.0),
        net_sale_proceeds=800.0,
        capex_by_year=(20.0, 20.0, 20.0),
    )
    with_capital = calculate_levered_cash_flows(
        initial_equity=4_000.0,
        noi_by_year=(120.0, 120.0, 120.0),
        annual_debt_service=(40.0, 40.0, 40.0),
        net_sale_proceeds=800.0,
        capex_by_year=(20.0, 20.0, 20.0),
        operating_capital_by_year=(30.0, 30.0, 30.0),
    )

    assert with_capital[0] == baseline[0]
    for year in (1, 2, 3):
        assert with_capital[year] == pytest.approx(baseline[year] - 30.0, abs=1e-9)


# =============================================================================
# G8-G11 / G15 -- inertness above NOI and at the sale
# =============================================================================


def _pair(ti: float = 500.0, lc: float = 250.0):
    baseline = analyze_acquisition_from_operating_projection(projection(), terms())
    loaded = analyze_acquisition_from_operating_projection(
        projection(), terms(), schedule(ti, lc)
    )
    return baseline, loaded


#: A deal whose returns are actually defined -- an 8% going-in cap with modest
#: leverage -- so the IRR and equity-multiple goldens measure the channel
#: rather than a degenerate cash-flow series.
def _healthy_pair(ti: float = 60.0, lc: float = 40.0):
    healthy_terms = terms(exit_cap_rate=0.08)
    healthy = _StubProjection(
        noi_by_year=(800.0, 800.0, 800.0),
        exit_noi=850.0,
        going_in_cap_rate=0.08,
    )
    baseline = analyze_acquisition_from_operating_projection(healthy, healthy_terms)
    loaded = analyze_acquisition_from_operating_projection(
        healthy, healthy_terms, schedule(ti, lc)
    )
    return baseline, loaded


def test_g8_dscr_is_bit_identical_under_large_operating_capital() -> None:
    """A lender's coverage test is an NOI test (D4 Section 22)."""

    baseline, loaded = _pair()

    assert hexes(baseline.dscr_by_year) == hexes(loaded.dscr_by_year)
    assert baseline.headline_dscr.hex() == loaded.headline_dscr.hex()
    assert baseline.min_dscr.hex() == loaded.min_dscr.hex()


def test_g9_debt_yield_is_bit_identical() -> None:
    baseline, loaded = _pair()

    assert baseline.year_1_debt_yield.hex() == loaded.year_1_debt_yield.hex()


def test_g10_the_debt_schedule_is_bit_identical() -> None:
    """Operating capital is an equity outflow: no new borrowing, no larger
    balance, no changed payment."""

    baseline, loaded = _pair(ti=1_000_000.0, lc=500_000.0)

    assert baseline.loan_amount.hex() == loaded.loan_amount.hex()
    assert baseline.monthly_debt_service.hex() == loaded.monthly_debt_service.hex()
    assert hexes(baseline.annual_debt_service) == hexes(loaded.annual_debt_service)
    assert (
        baseline.remaining_loan_balance.hex() == loaded.remaining_loan_balance.hex()
    )


def test_g10_the_debt_schedule_is_a_function_of_terms_alone() -> None:
    """Proven directly against the debt module, which never sees the channel."""

    deal_terms = terms()
    direct = calculate_debt_schedule(deal_terms)
    loaded = analyze_acquisition_from_operating_projection(
        projection(), deal_terms, schedule(1_000.0, 500.0)
    )

    assert hexes(direct.annual_debt_service) == hexes(loaded.annual_debt_service)
    assert direct.remaining_loan_balance.hex() == loaded.remaining_loan_balance.hex()


def test_g11_exit_noi_and_exit_value_are_bit_identical() -> None:
    baseline, loaded = _pair(ti=1_000_000.0, lc=500_000.0)

    assert baseline.exit_noi.hex() == loaded.exit_noi.hex()
    assert baseline.exit_value.hex() == loaded.exit_value.hex()
    assert baseline.disposition_costs.hex() == loaded.disposition_costs.hex()
    assert baseline.net_sale_proceeds.hex() == loaded.net_sale_proceeds.hex()


def test_noi_is_never_reduced_by_operating_capital() -> None:
    baseline, loaded = _pair(ti=1_000_000.0, lc=500_000.0)

    assert hexes(baseline.noi_by_year) == hexes(loaded.noi_by_year)
    assert baseline.going_in_cap_rate.hex() == loaded.going_in_cap_rate.hex()


def test_g15_t0_acquisition_costs_and_financing_fee_are_bit_identical() -> None:
    """A Year-1 TI cheque is not a T0 acquisition cost. D4.4 already supplied
    annual timing."""

    baseline, loaded = _pair(ti=1_000_000.0, lc=500_000.0)

    assert baseline.acquisition_costs.hex() == loaded.acquisition_costs.hex()
    assert baseline.financing_fee.hex() == loaded.financing_fee.hex()
    assert baseline.initial_equity.hex() == loaded.initial_equity.hex()
    assert baseline.unlevered_cash_flows[0].hex() == loaded.unlevered_cash_flows[0].hex()
    assert baseline.levered_cash_flows[0].hex() == loaded.levered_cash_flows[0].hex()


# =============================================================================
# G12-G14 -- returns move, through the authoritative cash flows
# =============================================================================


def test_g12_positive_operating_capital_lowers_both_irrs() -> None:
    baseline, loaded = _healthy_pair()

    assert baseline.unlevered_irr is not None
    assert loaded.unlevered_irr is not None
    assert loaded.unlevered_irr < baseline.unlevered_irr

    assert baseline.levered_irr is not None
    assert loaded.levered_irr is not None
    assert loaded.levered_irr < baseline.levered_irr


def test_g13_positive_operating_capital_lowers_the_equity_multiple() -> None:
    baseline, loaded = _healthy_pair()

    assert baseline.equity_multiple is not None
    assert loaded.equity_multiple is not None
    assert loaded.equity_multiple < baseline.equity_multiple


def test_g14_owner_recurring_distributions_fall_by_the_annual_amount() -> None:
    """HD-D4-3: TI and LC reduce the owner-return series where CapEx already
    does. Same NOI, same debt service, same CapEx; 30 more capital means 30
    fewer dollars distributed each year."""

    baseline = calculate_owner_return_metrics(
        noi_by_year=(120.0, 120.0),
        capex_by_year=(20.0, 20.0),
        annual_debt_service=(40.0, 40.0),
        purchase_price=1_000.0,
        acquisition_costs=0.0,
        initial_equity=400.0,
        loan_amount=600.0,
    )
    loaded = calculate_owner_return_metrics(
        noi_by_year=(120.0, 120.0),
        capex_by_year=(20.0, 20.0),
        annual_debt_service=(40.0, 40.0),
        purchase_price=1_000.0,
        acquisition_costs=0.0,
        initial_equity=400.0,
        loan_amount=600.0,
        operating_capital_by_year=(30.0, 30.0),
    )

    assert baseline.cumulative_operating_distributions_by_year == (60.0, 120.0)
    assert loaded.cumulative_operating_distributions_by_year == (30.0, 60.0)


def test_g14_cash_on_cash_falls_on_an_unchanged_denominator() -> None:
    """The denominator convention is untouched: initial equity is fixed."""

    baseline = calculate_owner_return_metrics(
        noi_by_year=(120.0,),
        capex_by_year=(20.0,),
        annual_debt_service=(40.0,),
        purchase_price=1_000.0,
        acquisition_costs=0.0,
        initial_equity=400.0,
        loan_amount=600.0,
    )
    loaded = calculate_owner_return_metrics(
        noi_by_year=(120.0,),
        capex_by_year=(20.0,),
        annual_debt_service=(40.0,),
        purchase_price=1_000.0,
        acquisition_costs=0.0,
        initial_equity=400.0,
        loan_amount=600.0,
        operating_capital_by_year=(30.0,),
    )

    assert baseline.levered_cash_on_cash_by_year == (60.0 / 400.0,)
    assert loaded.levered_cash_on_cash_by_year == (30.0 / 400.0,)
    assert baseline.unlevered_cash_yield_by_year == (100.0 / 1_000.0,)
    assert loaded.unlevered_cash_yield_by_year == (70.0 / 1_000.0,)


def test_g14_year_1_debt_yield_is_untouched() -> None:
    """An NOI metric, deliberately excluded from the change."""

    baseline = calculate_owner_return_metrics(
        noi_by_year=(120.0,),
        capex_by_year=(20.0,),
        annual_debt_service=(40.0,),
        purchase_price=1_000.0,
        acquisition_costs=0.0,
        initial_equity=400.0,
        loan_amount=600.0,
    )
    loaded = calculate_owner_return_metrics(
        noi_by_year=(120.0,),
        capex_by_year=(20.0,),
        annual_debt_service=(40.0,),
        purchase_price=1_000.0,
        acquisition_costs=0.0,
        initial_equity=400.0,
        loan_amount=600.0,
        operating_capital_by_year=(1_000.0,),
    )

    assert baseline.year_1_debt_yield.hex() == loaded.year_1_debt_yield.hex()


def test_returns_are_not_patched_independently_of_the_cash_flows() -> None:
    """The metrics move because the series moved. Recomputing the equity
    multiple from the reported levered cash flows reproduces the reported
    metric exactly."""

    _, loaded = _healthy_pair()

    positive = sum(cf for cf in loaded.levered_cash_flows if cf > 0.0)
    negative = sum(cf for cf in loaded.levered_cash_flows if cf < 0.0)

    assert loaded.equity_multiple == pytest.approx(
        positive / abs(negative), abs=1e-12
    )


# =============================================================================
# G16-G18 -- contract domain
# =============================================================================


def test_g16_a_schedule_shorter_than_the_hold_period_is_refused() -> None:
    with pytest.raises(ValueError, match="annual figures"):
        analyze_acquisition_from_operating_projection(
            projection(), terms(), schedule(1.0, 1.0, hold_period=HOLD - 1)
        )


def test_g16_a_schedule_longer_than_the_hold_period_is_refused() -> None:
    """An ``H + 1`` schedule is exactly the forward-window mistake: a
    post-sale capital event is not a seller cash flow."""

    with pytest.raises(ValueError, match="annual figures"):
        analyze_acquisition_from_operating_projection(
            projection(), terms(), schedule(1.0, 1.0, hold_period=HOLD + 1)
        )


def test_g16_mismatched_component_lengths_are_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="per hold year"):
        OperatingCapitalSchedule(
            tenant_improvements_by_year=(1.0, 2.0),
            leasing_commissions_by_year=(1.0,),
        )


@pytest.mark.parametrize("amount", [-0.01, -1_000.0])
def test_g17_a_negative_outflow_is_refused(amount: float) -> None:
    """A negative outflow would be capital income, for which there is no
    convention."""

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        OperatingCapitalSchedule(
            tenant_improvements_by_year=(amount,),
            leasing_commissions_by_year=(0.0,),
        )
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        OperatingCapitalSchedule(
            tenant_improvements_by_year=(0.0,),
            leasing_commissions_by_year=(amount,),
        )


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), float("-inf")])
def test_g18_a_non_finite_amount_is_refused(amount: float) -> None:
    with pytest.raises(NonFiniteResultError):
        OperatingCapitalSchedule(
            tenant_improvements_by_year=(amount,),
            leasing_commissions_by_year=(0.0,),
        )


def test_zero_is_a_valid_outflow() -> None:
    assert OperatingCapitalSchedule(
        tenant_improvements_by_year=(0.0,), leasing_commissions_by_year=(0.0,)
    ).tenant_improvements_by_year == (0.0,)


def test_the_schedule_is_immutable() -> None:
    contract = schedule(1.0, 2.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.tenant_improvements_by_year = ()  # type: ignore[misc]


# =============================================================================
# Quick / Detailed bit-identity through the public entry points
# =============================================================================


_QUICK_MATRIX = [
    {},
    {"ltv": 0.0},
    {"current_noi": 0.0},
    {"noi_growth": -0.02},
    {"hold_period": 1, "io_period": 0},
    {"hold_period": 10},
    {"annual_capex_reserve": 0.0},
    {"acquisition_cost_pct": 0.0, "financing_fee_pct": 0.0, "disposition_cost_pct": 0.0},
]


@pytest.mark.parametrize("overrides", _QUICK_MATRIX, ids=range(len(_QUICK_MATRIX)))
def test_quick_never_supplies_a_schedule_and_is_unchanged(
    overrides: dict[str, object],
) -> None:
    """Quick's public entry point takes no operating capital and constructs no
    synthetic zero schedule -- it simply does not pass the argument."""

    inputs = quick_inputs(**overrides)

    public = analyze_acquisition(inputs)
    manual = analyze_acquisition_from_operating_projection(
        __import__(
            "anchor.engine.noi", fromlist=["build_quick_operating_projection"]
        ).build_quick_operating_projection(inputs),
        acquisition_terms_from_inputs(inputs),
    )

    assert snapshot(public) == snapshot(manual)
    assert public.tenant_improvements_by_year == tuple(
        0.0 for _ in range(inputs.hold_period)
    )


def test_detailed_never_supplies_a_schedule_and_is_unchanged() -> None:
    deal_terms = terms(hold_period=5, ltv=0.65, annual_capex_reserve=120_000.0)
    detailed = DetailedOperatingInputs(
        gross_potential_rent=3_000_000.0,
        other_income=120_000.0,
        vacancy_credit_loss_pct=0.07,
        property_taxes=600_000.0,
        insurance=120_000.0,
        utilities=240_000.0,
        repairs_maintenance=180_000.0,
        other_operating_expenses=60_000.0,
        management_fee_pct=0.03,
        revenue_growth=0.03,
        expense_growth=0.03,
    )

    envelope = analyze_detailed_acquisition_with_projection(deal_terms, detailed)

    assert envelope.results.tenant_improvements_by_year == (0.0,) * 5
    assert envelope.results.leasing_commissions_by_year == (0.0,) * 5

    manual = analyze_acquisition_from_operating_projection(
        envelope.operating_projection, deal_terms
    )
    assert snapshot(envelope.results) == snapshot(manual)


def test_the_stub_projection_proves_the_channel_is_mode_agnostic() -> None:
    """A plain object carrying the three protocol fields is enough. The engine
    imports no leasing module and needs no Detailed-only field."""

    results = analyze_acquisition_from_operating_projection(
        _StubProjection(
            noi_by_year=(120.0, 120.0, 120.0),
            exit_noi=140.0,
            going_in_cap_rate=0.012,
        ),
        terms(),
        schedule(5.0, 5.0),
    )

    assert results.noi_by_year == (120.0, 120.0, 120.0)
    assert results.exit_noi == 140.0
    assert results.going_in_cap_rate == 0.012


# =============================================================================
# The single authority
# =============================================================================


def test_the_operating_capital_total_has_one_authority() -> None:
    """``calculate_operating_capital_by_year`` is the only place TI is added to
    LC. Every consumer subtracts its completed output."""

    total = calculate_operating_capital_by_year(
        operating_capital=schedule(20.0, 10.0), hold_period=HOLD
    )

    assert total == (30.0, 30.0, 30.0)

    unlevered = calculate_recurring_unlevered_cash_flows(
        noi_by_year=(120.0, 120.0, 120.0),
        capex_by_year=(20.0, 20.0, 20.0),
        operating_capital_by_year=total,
    )
    levered = calculate_recurring_levered_cash_flows(
        noi_by_year=(120.0, 120.0, 120.0),
        capex_by_year=(20.0, 20.0, 20.0),
        annual_debt_service=(0.0, 0.0, 0.0),
        operating_capital_by_year=total,
    )

    assert unlevered == levered


def test_absence_materialises_zeros_of_the_right_length() -> None:
    assert calculate_operating_capital_by_year(
        operating_capital=None, hold_period=4
    ) == (0.0, 0.0, 0.0, 0.0)


def test_the_result_reports_the_components_it_was_given() -> None:
    results = analyze_acquisition_from_operating_projection(
        projection(), terms(), schedule(20.0, 10.0)
    )

    assert results.tenant_improvements_by_year == (20.0, 20.0, 20.0)
    assert results.leasing_commissions_by_year == (10.0, 10.0, 10.0)
