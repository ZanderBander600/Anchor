"""Phase 7 Gate P7.10 Stage 1 -- the deterministic valuation layer.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 5.2 to 5.6
and the ratified decisions R-A to R-D.

Every golden expectation is arithmetic the reader can check: an NOI stated in
``_p7_10_fixtures`` or compounded there, divided by a capitalisation rate
written in the test. No expected value is produced by ``anchor.valuation``.
"""

from __future__ import annotations

from math import isclose

import pytest
from _p7_10_fixtures import (  # type: ignore[import-not-found]
    BASE_NOI,
    EXIT_CAP,
    GROWTH,
    HOLD,
    INVESTMENT_ID,
    cap,
    hand_exit_noi,
    instruction,
    stabilized,
    stated,
    timepoint,
    unit,
    variant,
)
from _p7_7_fixtures import analyze_unit  # type: ignore[import-not-found]

from anchor.valuation import (
    ValuationAvailability,
    ValuationError,
    ValuationKind,
    ValuationMethodKind,
    ValuationScopeKind,
    ValuationUnavailableReason,
    forward_noi_at,
    resolve_investment_valuation,
    resolve_unit_valuation,
    timepoint_month_reason,
    unit_exit_view,
    unit_inputs,
    variant_inputs,
)

AVAILABLE = ValuationAvailability.AVAILABLE
UNAVAILABLE = ValuationAvailability.UNAVAILABLE


def _value(result: object) -> float:
    value = getattr(result, "value")
    assert value is not None
    return float(value)


# =============================================================================
# 1. Timing: month 0 and every supported hold-year mapping (R-A)
# =============================================================================


def test_closing_capitalises_year_1_noi() -> None:
    """Model month 0 is the forward Year 1 NOI, not a trailing or annualised
    figure."""

    assert forward_noi_at(unit(), model_month=0) == pytest.approx(BASE_NOI)


@pytest.mark.parametrize("year", range(1, HOLD))
def test_each_hold_year_end_capitalises_the_following_year_noi(year: int) -> None:
    """Hold-year end ``12y`` capitalises Year ``y + 1``: the NOI the buyer at
    that date would earn forward, compounded by hand here."""

    expected = BASE_NOI * (1.0 + GROWTH) ** year
    assert forward_noi_at(unit(), model_month=12 * year) == pytest.approx(expected)


def test_the_exit_month_is_reserved_for_the_system_exit_view() -> None:
    """A stored definition never occupies the exit month: its value there is
    the D6 terminal result, and a second one could drift from it (R-B)."""

    assert timepoint_month_reason(12 * HOLD, hold_period=HOLD) is ValuationUnavailableReason.RESERVED_EXIT_MONTH


def test_a_month_beyond_the_hold_is_outside_this_variant_horizon() -> None:
    assert (
        timepoint_month_reason(12 * (HOLD + 1), hold_period=HOLD)
        is ValuationUnavailableReason.OUTSIDE_HOLD_HORIZON
    )


@pytest.mark.parametrize("month", [0, *(12 * year for year in range(1, HOLD))])
def test_every_storable_month_resolves(month: int) -> None:
    assert timepoint_month_reason(month, hold_period=HOLD) is None


def test_no_inside_year_month_has_a_forward_noi() -> None:
    """There is no monthly forward-NOI convention, so month 6 is not valued by
    interpolation, annualisation or the nearest year (R-A)."""

    with pytest.raises(ValuationError):
        forward_noi_at(unit(), model_month=6)


def test_a_reserved_or_outside_month_reports_a_typed_unavailable_result() -> None:
    result = resolve_unit_valuation(instruction(), unit=unit(), model_month=12 * HOLD)
    assert result.status is UNAVAILABLE
    assert result.unavailable_reason is ValuationUnavailableReason.RESERVED_EXIT_MONTH
    assert result.value is None


# =============================================================================
# 2. Direct capitalisation (R-D)
# =============================================================================


def test_direct_cap_divides_the_forward_noi_by_the_cap_rate() -> None:
    """800,000 / 0.05 = 16,000,000, by hand."""

    result = resolve_unit_valuation(instruction(method=cap(0.05)), unit=unit(), model_month=0)
    assert result.status is AVAILABLE
    assert result.method_kind is ValuationMethodKind.DIRECT_CAP
    assert result.analyst_supplied is False
    assert _value(result) == pytest.approx(16_000_000.0)
    assert result.forward_noi == pytest.approx(BASE_NOI)
    assert result.cap_rate == 0.05
    assert result.evidence_id is None


def test_a_stabilized_year_2_end_capitalises_year_3_noi() -> None:
    """968,000 / 0.055 = 17,600,000, by hand."""

    result = resolve_unit_valuation(instruction(method=cap(0.055)), unit=unit(), model_month=24)
    assert _value(result) == pytest.approx(BASE_NOI * 1.1 * 1.1 / 0.055)
    assert _value(result) == pytest.approx(17_600_000.0, rel=1e-9)


@pytest.mark.parametrize("rate", [0.0, -0.05, float("inf"), float("nan")])
def test_an_invalid_cap_rate_is_refused_before_it_is_ever_divided_by(rate: float) -> None:
    """A non-positive or non-finite rate is a malformed definition, refused by
    validation -- never a value, and never a divide."""

    from anchor.valuation import ValuationIssueCode, validate_valuation_timepoint

    issues = validate_valuation_timepoint(timepoint(instructions=(instruction(method=cap(rate)),)))
    assert [issue.code for issue in issues] == [ValuationIssueCode.INVALID_CAP_RATE]


@pytest.mark.parametrize("noi", [0.0, -250_000.0])
def test_a_non_positive_forward_noi_is_unavailable_not_floored(noi: float) -> None:
    """The NOI is not floored at zero, replaced by a stabilised figure or
    divided by the cap rate; the value simply does not exist."""

    flat = unit(noi_by_year=(noi,) * HOLD)
    result = resolve_unit_valuation(instruction(method=cap(0.06)), unit=flat, model_month=0)
    assert result.status is UNAVAILABLE
    assert result.unavailable_reason is ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI
    assert result.value is None
    assert result.forward_noi is None


# =============================================================================
# 3. Analyst-supplied value (R-D)
# =============================================================================


def test_an_analyst_value_is_its_stated_amount_and_says_so() -> None:
    result = resolve_unit_valuation(instruction(method=stated(12_500_000.0)), unit=unit(), model_month=0)
    assert result.status is AVAILABLE
    assert result.method_kind is ValuationMethodKind.ANALYST_VALUE
    assert result.analyst_supplied is True
    assert _value(result) == 12_500_000.0
    assert result.evidence_id == "ev-1"
    assert result.forward_noi is None and result.cap_rate is None


def test_an_analyst_value_is_constant_across_variants() -> None:
    """It is the definition's own stated amount, so a different Strategy or
    Scenario -- here, a materially different NOI path -- never moves it."""

    lean = unit(noi_by_year=(400_000.0,) * HOLD)
    rich = unit(noi_by_year=(2_000_000.0,) * HOLD)
    method = stated(9_000_000.0)
    assert _value(resolve_unit_valuation(instruction(method=method), unit=lean, model_month=0)) == 9_000_000.0
    assert _value(resolve_unit_valuation(instruction(method=method), unit=rich, model_month=0)) == 9_000_000.0


def test_an_analyst_value_of_zero_is_a_value_not_an_absence() -> None:
    """Zero is non-negative and therefore a stated value. It is still labelled
    analyst supplied, so it is never read as an unavailable Anchor result."""

    result = resolve_unit_valuation(instruction(method=stated(0.0)), unit=unit(), model_month=0)
    assert result.status is AVAILABLE
    assert _value(result) == 0.0
    assert result.analyst_supplied is True


# =============================================================================
# 4. The reserved system Exit view equals the existing D6 result (R-B)
# =============================================================================


@pytest.mark.parametrize("mode", ["quick", "detailed", "lease_level"])
def test_the_exit_view_is_the_existing_d6_terminal_result(mode: str) -> None:
    """In all three underwriting modes: every Exit figure is the completed
    result's own, read and never recomputed."""

    terms, results = analyze_unit(mode)
    view = unit_exit_view(unit_inputs(unit_id="u1", terms=terms, results=results))
    assert view.scope_kind is ValuationScopeKind.UNIT
    assert view.model_month == terms.hold_period * 12
    assert view.exit_noi == results.exit_noi
    assert view.exit_value == results.exit_value
    assert view.exit_cap_rate == terms.exit_cap_rate
    assert view.disposition_costs == results.disposition_costs
    assert view.net_sale_proceeds == results.net_sale_proceeds


@pytest.mark.parametrize("mode", ["quick", "detailed", "lease_level"])
def test_capitalising_the_exit_noi_would_reproduce_the_exit_value(mode: str) -> None:
    """The Exit view is read rather than recomputed, and the arithmetic it
    would have used agrees with D6's -- so reading it introduces no drift."""

    terms, results = analyze_unit(mode)
    assert isclose(results.exit_noi / terms.exit_cap_rate, results.exit_value, rel_tol=1e-12)


def test_the_exit_view_of_the_round_unit_is_its_stated_terminal_value() -> None:
    """1,288,408 / 0.08 = 16,105,100, by hand."""

    view = unit_exit_view(unit())
    assert view.exit_noi == pytest.approx(hand_exit_noi())
    assert view.exit_value == pytest.approx(hand_exit_noi() / EXIT_CAP)
    assert view.model_month == 60


# =============================================================================
# 5. Investment aggregation (Section 5.5)
# =============================================================================


def test_a_complete_multi_unit_investment_sums_its_units() -> None:
    """800,000/0.05 + 400,000/0.05 = 16,000,000 + 8,000,000."""

    first = unit("u1")
    second = unit("u2", noi_by_year=(400_000.0,) * HOLD)
    result = resolve_investment_valuation(
        timepoint(instructions=(instruction("u1", cap(0.05)), instruction("u2", cap(0.05)))),
        variant=variant(first, second),
    )
    assert result.status is AVAILABLE
    assert result.scope_kind is ValuationScopeKind.INVESTMENT
    assert _value(result) == pytest.approx(24_000_000.0)
    assert [unit_result.unit_id for unit_result in result.unit_results] == ["u1", "u2"]


def test_one_invalid_unit_makes_the_investment_value_unavailable() -> None:
    """No partial portfolio sum is ever presented as the Investment value."""

    good = unit("u1")
    bad = unit("u2", noi_by_year=(0.0,) * HOLD)
    result = resolve_investment_valuation(
        timepoint(instructions=(instruction("u1", cap(0.05)), instruction("u2", cap(0.05)))),
        variant=variant(good, bad),
    )
    assert result.status is UNAVAILABLE
    assert result.value is None
    assert result.unavailable_reason is ValuationUnavailableReason.INCOMPLETE_UNITS
    assert "u2" in (result.unavailable_message or "")
    by_id = {item.unit_id: item for item in result.unit_results}
    assert by_id["u1"].status is AVAILABLE
    assert by_id["u2"].unavailable_reason is ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI


def test_a_unit_the_definition_omits_makes_the_investment_value_unavailable() -> None:
    result = resolve_investment_valuation(
        timepoint(instructions=(instruction("u1", cap(0.05)),)),
        variant=variant(unit("u1"), unit("u2")),
    )
    assert result.status is UNAVAILABLE
    by_id = {item.unit_id: item for item in result.unit_results}
    assert by_id["u2"].unavailable_reason is ValuationUnavailableReason.UNIT_NOT_VALUED


def test_a_unit_the_variant_does_not_hold_makes_the_investment_value_unavailable() -> None:
    result = resolve_investment_valuation(
        timepoint(instructions=(instruction("u1", cap(0.05)), instruction("ghost", cap(0.05)))),
        variant=variant(unit("u1")),
    )
    assert result.status is UNAVAILABLE
    by_id = {item.unit_id: item for item in result.unit_results}
    assert by_id["ghost"].unavailable_reason is ValuationUnavailableReason.UNIT_NOT_IN_VARIANT


def test_the_unit_order_is_canonical_and_never_the_list_order() -> None:
    """Economically meaningful order comes from the stable ids, so permuting
    the instructions or the variant's Units changes nothing at all."""

    units = (unit("u3"), unit("u1", noi_by_year=(500_000.0,) * HOLD), unit("u2"))
    instructions = (instruction("u2", cap(0.05)), instruction("u3", cap(0.05)), instruction("u1", cap(0.05)))
    forward = resolve_investment_valuation(timepoint(instructions=instructions), variant=variant(*units))
    backward = resolve_investment_valuation(
        timepoint(instructions=tuple(reversed(instructions))), variant=variant(*reversed(units))
    )
    assert [item.unit_id for item in forward.unit_results] == ["u1", "u2", "u3"]
    assert forward == backward


def test_a_hidden_one_unit_investment_follows_the_same_contract() -> None:
    """Its Investment value equals its one Unit's value, and the two stay
    separately labelled scopes."""

    only = unit("u1")
    result = resolve_investment_valuation(
        timepoint(instructions=(instruction("u1", cap(0.05)),)), variant=variant(only)
    )
    (single,) = result.unit_results
    assert result.scope_kind is ValuationScopeKind.INVESTMENT
    assert _value(result) == _value(single)
    assert _value(result) == pytest.approx(16_000_000.0)


def test_a_definition_is_never_valued_against_another_investment() -> None:
    with pytest.raises(ValuationError):
        resolve_investment_valuation(
            timepoint(investment_id="other"), variant=variant(unit("u1"), investment_id=INVESTMENT_ID)
        )


def test_variant_inputs_canonicalise_and_require_one_common_hold() -> None:
    built = variant_inputs(investment_id=INVESTMENT_ID, units=(unit("u2"), unit("u1")))
    assert [member.unit_id for member in built.units] == ["u1", "u2"]
    assert built.hold_period == HOLD
    with pytest.raises(ValuationError):
        variant_inputs(investment_id=INVESTMENT_ID, units=(unit("u1"), unit("u2", hold=7)))


# =============================================================================
# 6. All three underwriting modes resolve against their own completed results
# =============================================================================


@pytest.mark.parametrize("mode", ["quick", "detailed", "lease_level"])
def test_direct_cap_reads_each_mode_own_forward_noi(mode: str) -> None:
    """The mode changes the NOI, never the valuation arithmetic: the value is
    always that mode's own ``noi_by_year`` entry over the stated cap rate."""

    terms, results = analyze_unit(mode)
    inputs = unit_inputs(unit_id="u1", terms=terms, results=results)
    for year in range(0, terms.hold_period):
        month = 12 * year
        if timepoint_month_reason(month, hold_period=terms.hold_period) is not None:
            continue
        resolved = resolve_unit_valuation(instruction(method=cap(0.07)), unit=inputs, model_month=month)
        expected = results.noi_by_year[year] / 0.07
        if results.noi_by_year[year] > 0.0:
            assert _value(resolved) == pytest.approx(expected)
        else:
            assert resolved.status is UNAVAILABLE


@pytest.mark.parametrize("mode", ["quick", "detailed", "lease_level"])
def test_a_stabilized_definition_resolves_in_each_mode(mode: str) -> None:
    terms, results = analyze_unit(mode)
    inputs = unit_inputs(unit_id="u1", terms=terms, results=results)
    built = variant_inputs(investment_id=INVESTMENT_ID, units=(inputs,))
    result = resolve_investment_valuation(
        stabilized(model_month=12, instructions=(instruction("u1", cap(0.065)),)), variant=built
    )
    assert result.kind is ValuationKind.STABILIZED
    assert result.model_month == 12
    if results.noi_by_year[1] > 0.0:
        assert _value(result) == pytest.approx(results.noi_by_year[1] / 0.065)
    else:
        assert result.status is UNAVAILABLE
