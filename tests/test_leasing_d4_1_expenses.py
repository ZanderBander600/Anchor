"""Sprint D Gate D4.1 -- canonical monthly property expenses and the pool.

Governed by
``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
Sections 10, 11, 12 and 31 (and D0 Section 13.2).

Sixteen goldens (G1-G16), the HD-D4-1 bit/hex equivalence matrix, the
adversarial domain set, and the inertness proofs that show the four contract
fields D4.1 does not consume cannot move a D4.1 number.
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import date

import pytest

from anchor.contracts import DetailedOperatingInputs
from anchor.engine.contracts import NonFiniteResultError
from anchor.engine.operating_projection import build_detailed_operating_projection
from anchor.leasing import (
    FIXED_EXPENSE_LINES,
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseLevelOperatingInputs,
    LeaseValidationError,
    ModelMonth,
    MonthlyPropertyExpenseSchedule,
    RecoverableExpensePool,
    annual_expense_amount,
    build_model_months,
    build_property_expense_schedule,
    build_recoverable_expense_pool,
    validate_lease_level_operating_inputs,
    validate_recoverable_expense_ratio,
)


# =============================================================================
# Shared fixtures -- the D4 Section 31.1 golden property
# =============================================================================


_ANALYSIS_START = date(2027, 1, 1)
_JULY_START = date(2027, 7, 1)
_HOLD_PERIOD = 5


def _inputs(**overrides: object) -> LeaseLevelOperatingInputs:
    """The standard D4.1 operating inputs, with per-test overrides.

    Year-1 annual dollars chosen so every golden lands on a round monthly
    figure: taxes ``100,000``/month, insurance ``10,000``, utilities
    ``20,000``, repairs ``15,000``, other ``5,000`` -- ``150,000``/month of
    fixed operating expense (D4 golden G4).
    """

    base = dict(
        other_income=60_000.0,
        other_income_growth=0.03,
        credit_loss_pct=0.0,
        property_taxes=1_200_000.0,
        insurance=120_000.0,
        utilities=240_000.0,
        repairs_maintenance=180_000.0,
        other_operating_expenses=60_000.0,
        management_fee_pct=0.03,
        expense_growth=0.0,
        recoverable_expense_ratio=1.0,
    )
    base.update(overrides)
    return LeaseLevelOperatingInputs(**base)  # type: ignore[arg-type]


def _months(
    *, analysis_start: date = _ANALYSIS_START, hold_period: int = _HOLD_PERIOD
) -> tuple[ModelMonth, ...]:
    return build_model_months(analysis_start=analysis_start, hold_period=hold_period)


def _schedule(**overrides: object) -> MonthlyPropertyExpenseSchedule:
    return build_property_expense_schedule(_inputs(**overrides), months=_months())


# =============================================================================
# G1 -- zero growth
# =============================================================================


def test_g1_zero_growth_holds_every_month_at_the_year_one_rate() -> None:
    """Year-1 annual tax ``1,200,000`` at zero growth is ``100,000`` in every
    canonical month, hold and forward alike."""

    schedule = _schedule(expense_growth=0.0)

    assert schedule.property_taxes == tuple(100_000.0 for _ in schedule.months)


def test_g1_zero_growth_leaves_the_total_flat_too() -> None:
    schedule = _schedule(expense_growth=0.0)

    assert schedule.fixed_operating_expenses == tuple(
        150_000.0 for _ in schedule.months
    )


# =============================================================================
# G2 -- the 3% anniversary step
# =============================================================================


def test_g2_year_one_months_are_all_at_the_year_one_rate() -> None:
    schedule = _schedule(expense_growth=0.03)

    assert schedule.property_taxes[:12] == tuple(100_000.0 for _ in range(12))


def test_g2_the_step_lands_on_month_thirteen() -> None:
    """``1,200,000 * 1.03 / 12 == 103,000`` exactly."""

    schedule = _schedule(expense_growth=0.03)

    assert schedule.property_taxes[12:24] == tuple(103_000.0 for _ in range(12))


def test_g2_month_twelve_and_month_thirteen_straddle_the_step() -> None:
    schedule = _schedule(expense_growth=0.03)

    assert schedule.property_taxes[11] == 100_000.0
    assert schedule.property_taxes[12] == 103_000.0


def test_g2_every_month_of_a_hold_year_carries_one_identical_figure() -> None:
    """Level allocation inside each model year: no seasonality anywhere."""

    schedule = _schedule(expense_growth=0.03)

    for year_start in range(0, len(schedule.months), 12):
        year_slice = schedule.property_taxes[year_start : year_start + 12]
        assert len(set(year_slice)) == 1


# =============================================================================
# G3 -- non-January analysis start
# =============================================================================


def test_g3_july_start_steps_in_july_not_january() -> None:
    """The growth step is a **model** anniversary. With a July 2027 start,
    month 13 is July 2028 and is the first month at the Year-2 rate; the
    January in between changes nothing (FM-D4-12)."""

    schedule = build_property_expense_schedule(
        _inputs(expense_growth=0.03), months=_months(analysis_start=_JULY_START)
    )

    assert schedule.months[12].month_start == date(2028, 7, 1)
    assert schedule.property_taxes[11] == 100_000.0
    assert schedule.property_taxes[12] == 103_000.0


def test_g3_january_is_not_a_step_month_for_a_july_start() -> None:
    """January 2028 is model month 7 -- inside Hold Year 1 and unchanged."""

    schedule = build_property_expense_schedule(
        _inputs(expense_growth=0.03), months=_months(analysis_start=_JULY_START)
    )

    january_positions = [
        position
        for position, month in enumerate(schedule.months)
        if month.month_start.month == 1
    ]
    assert january_positions
    for position in january_positions:
        assert schedule.property_taxes[position] == schedule.property_taxes[
            position - 1
        ]


def test_g3_a_january_start_produces_the_same_economics_as_july() -> None:
    """The anniversary rule is anchored to the analysis start, so the two
    schedules differ only in their calendar labels."""

    january = build_property_expense_schedule(
        _inputs(expense_growth=0.03), months=_months(analysis_start=_ANALYSIS_START)
    )
    july = build_property_expense_schedule(
        _inputs(expense_growth=0.03), months=_months(analysis_start=_JULY_START)
    )

    assert january.property_taxes == july.property_taxes
    assert january.fixed_operating_expenses == july.fixed_operating_expenses


# =============================================================================
# G4 -- multiple expense lines
# =============================================================================


def test_g4_each_line_projects_to_its_own_monthly_figure() -> None:
    schedule = _schedule()

    assert schedule.property_taxes[0] == 100_000.0
    assert schedule.insurance[0] == 10_000.0
    assert schedule.utilities[0] == 20_000.0
    assert schedule.repairs_maintenance[0] == 15_000.0
    assert schedule.other_operating_expenses[0] == 5_000.0


def test_g4_the_total_is_the_sum_of_exactly_the_five_lines() -> None:
    schedule = _schedule()

    assert schedule.fixed_operating_expenses[0] == 150_000.0


def test_g4_the_total_reconciles_in_every_month_under_growth() -> None:
    schedule = _schedule(expense_growth=0.03)

    for position in range(len(schedule.months)):
        assert schedule.fixed_operating_expenses[position] == pytest.approx(
            schedule.property_taxes[position]
            + schedule.insurance[position]
            + schedule.utilities[position]
            + schedule.repairs_maintenance[position]
            + schedule.other_operating_expenses[position],
            abs=1e-9,
        )


# =============================================================================
# G5 / G6 / G7 -- the recoverable ratio
# =============================================================================


def test_g5_ratio_of_one_recovers_the_whole_eligible_pool() -> None:
    schedule = _schedule()

    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=1.0)

    assert pool.recoverable_expenses[0] == 150_000.0


def test_g6_ratio_of_sixty_percent_recovers_ninety_thousand() -> None:
    schedule = _schedule()

    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.60)

    assert pool.recoverable_expenses[0] == 90_000.0


def test_g7_ratio_of_zero_produces_an_empty_pool() -> None:
    schedule = _schedule()

    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.0)

    assert pool.recoverable_expenses == tuple(0.0 for _ in schedule.months)


def test_g7_a_zero_ratio_does_not_zero_the_expenses() -> None:
    """The landlord still pays them; they are simply not reimbursed."""

    schedule = _schedule()

    build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.0)

    assert schedule.fixed_operating_expenses[0] == 150_000.0


# =============================================================================
# G8 -- the forward exit year
# =============================================================================


def test_g8_forward_months_belong_to_model_year_h_plus_one() -> None:
    schedule = _schedule(expense_growth=0.03)

    forward = schedule.months[12 * _HOLD_PERIOD :]
    assert len(forward) == 12
    assert all(month.hold_year == _HOLD_PERIOD + 1 for month in forward)
    assert all(month.is_forward_exit_month for month in forward)


def test_g8_forward_months_receive_genuinely_grown_expenses() -> None:
    """``1,200,000 * 1.03**5 / 12``, not a frozen Hold-Year-5 figure."""

    schedule = _schedule(expense_growth=0.03)

    expected = 1_200_000.0 * (1.03**5) / 12
    assert schedule.property_taxes[60] == pytest.approx(expected, abs=1e-9)


def test_g8_forward_months_are_strictly_above_the_final_hold_year() -> None:
    """The mutation "forward months freeze at Hold Year H" must be visible."""

    schedule = _schedule(expense_growth=0.03)

    assert schedule.property_taxes[60] > schedule.property_taxes[59]
    assert schedule.property_taxes[60] != schedule.property_taxes[48]


def test_g8_all_twelve_forward_months_share_one_figure() -> None:
    schedule = _schedule(expense_growth=0.03)

    forward = schedule.property_taxes[60:]
    assert len(set(forward)) == 1


# =============================================================================
# G9 -- vacancy independence, proved structurally
# =============================================================================


_OCCUPANCY_PARAMETERS = frozenset(
    {
        "suite",
        "suites",
        "lease",
        "leases",
        "occupancy",
        "physical_occupancy",
        "occupied_area",
        "occupied_area_sf",
        "vacant_area",
        "vacant_area_sf",
        "rentable_area_sf",
        "cash_base_rent",
        "rent_roll",
    }
)


def test_g9_the_expense_builder_admits_no_occupancy_input() -> None:
    """A fully vacant building still pays its taxes. The independence is
    structural: there is no parameter through which occupancy could enter
    (D4 Section 25.2, FM-D4-14)."""

    parameters = set(
        inspect.signature(build_property_expense_schedule).parameters
    )

    assert not parameters & _OCCUPANCY_PARAMETERS


def test_g9_the_pool_builder_admits_no_occupancy_input() -> None:
    parameters = set(inspect.signature(build_recoverable_expense_pool).parameters)

    assert not parameters & _OCCUPANCY_PARAMETERS


def test_g9_the_operating_input_contract_declares_no_occupancy_field() -> None:
    """G-M14 applied to the property operating contract: no ``occupancy`` and
    no ``vacancy_credit_loss_pct`` exists to be applied to an expense."""

    fields = {field.name for field in dataclasses.fields(LeaseLevelOperatingInputs)}

    assert "occupancy" not in fields
    assert "vacancy_credit_loss_pct" not in fields
    assert not fields & _OCCUPANCY_PARAMETERS


def test_g9_the_expense_schedule_declares_no_occupancy_field() -> None:
    fields = {
        field.name for field in dataclasses.fields(MonthlyPropertyExpenseSchedule)
    }

    assert not fields & _OCCUPANCY_PARAMETERS


# =============================================================================
# G10 / G11 / G12 -- the four fields D4.1 does not consume are inert
# =============================================================================


_INERT_FIELD_PERTURBATIONS = (
    ("management_fee_pct", 0.03, 0.95),
    ("other_income", 60_000.0, 9_999_999.0),
    ("other_income_growth", 0.03, 0.75),
    ("credit_loss_pct", 0.0, 0.08),
)


@pytest.mark.parametrize(
    "field_name, baseline, perturbed",
    _INERT_FIELD_PERTURBATIONS,
    ids=[entry[0] for entry in _INERT_FIELD_PERTURBATIONS],
)
def test_g10_g11_g12_inert_fields_cannot_move_the_expense_schedule(
    field_name: str, baseline: object, perturbed: object
) -> None:
    """D4.1 consumes the five expense lines, ``expense_growth`` and
    ``recoverable_expense_ratio`` and nothing else. The management fee is
    D4.3's, other income is D4.3's, credit loss is D4.3's."""

    before = _schedule(expense_growth=0.03, **{field_name: baseline})
    after = _schedule(expense_growth=0.03, **{field_name: perturbed})

    assert before == after


@pytest.mark.parametrize(
    "field_name, baseline, perturbed",
    _INERT_FIELD_PERTURBATIONS,
    ids=[entry[0] for entry in _INERT_FIELD_PERTURBATIONS],
)
def test_g10_g11_g12_inert_fields_cannot_move_the_pool(
    field_name: str, baseline: object, perturbed: object
) -> None:
    before = build_recoverable_expense_pool(
        _schedule(expense_growth=0.03, **{field_name: baseline}),
        recoverable_expense_ratio=0.6,
    )
    after = build_recoverable_expense_pool(
        _schedule(expense_growth=0.03, **{field_name: perturbed}),
        recoverable_expense_ratio=0.6,
    )

    assert before == after


def test_g10_the_management_fee_is_not_a_fixed_expense_line() -> None:
    assert "management_fee" not in FIXED_EXPENSE_LINES
    assert "management_fee_pct" not in FIXED_EXPENSE_LINES
    assert len(FIXED_EXPENSE_LINES) == 5


def test_g10_the_expense_schedule_has_no_management_fee_field() -> None:
    fields = {
        field.name for field in dataclasses.fields(MonthlyPropertyExpenseSchedule)
    }

    assert not any("management" in name or "fee" in name for name in fields)


def test_g10_a_ninety_five_percent_fee_leaves_the_pool_untouched() -> None:
    """The starkest form: a fee that would dominate every other line changes
    no pool dollar, because D4.1 computes no fee at all."""

    schedule = _schedule(management_fee_pct=0.95)

    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=1.0)

    assert pool.recoverable_expenses[0] == 150_000.0


# =============================================================================
# G13 -- HD-D4-1 bit/hex equivalence with the Detailed annual amount
# =============================================================================


_EQUIVALENCE_AMOUNTS = (
    0.0,
    1.0,
    1_200_000.0,
    123_456.789,
    1e-9,
    987_654_321.12,
    7.3,
)
_EQUIVALENCE_GROWTHS = (0.0, 0.03, 0.17, 0.9999, -0.02, -0.5, -0.999999)
_EQUIVALENCE_YEARS = (1, 2, 5, 10, 11, 21, 31)


def _detailed_annual_expense(
    *, year_1_amount: float, expense_growth: float, hold_period: int
) -> tuple[float, ...]:
    """The Detailed annual property-tax series, straight from the shipped
    producer. Every other Detailed input is neutral so the tax line is
    isolated."""

    detailed_inputs = DetailedOperatingInputs(
        gross_potential_rent=0.0,
        other_income=0.0,
        vacancy_credit_loss_pct=0.0,
        property_taxes=year_1_amount,
        insurance=0.0,
        utilities=0.0,
        repairs_maintenance=0.0,
        other_operating_expenses=0.0,
        management_fee_pct=0.0,
        revenue_growth=0.0,
        expense_growth=expense_growth,
    )
    projection = build_detailed_operating_projection(
        detailed_inputs, hold_period=hold_period, purchase_price=10_000_000.0
    )
    return projection.property_taxes_by_year


@pytest.mark.parametrize("year_1_amount", _EQUIVALENCE_AMOUNTS)
@pytest.mark.parametrize("expense_growth", _EQUIVALENCE_GROWTHS)
def test_g13_lease_level_annual_growth_is_bit_identical_to_detailed(
    year_1_amount: float, expense_growth: float
) -> None:
    """**The HD-D4-1 condition.** Mirroring rather than extracting was approved
    only on the guarantee that the mirror never drifts, so the comparison is
    ``float.hex()`` -- exact, and a failure shows the differing bits.

    Compared at the **annual growth formula output**, which is the equivalence
    target: the twelve monthly values are deliberately not summed and compared,
    because repeated division and addition group floats differently and would
    test IEEE-754 associativity rather than the formula.
    """

    hold_period = max(_EQUIVALENCE_YEARS) - 1
    detailed = _detailed_annual_expense(
        year_1_amount=year_1_amount,
        expense_growth=expense_growth,
        hold_period=hold_period,
    )

    for model_year in _EQUIVALENCE_YEARS:
        if model_year > hold_period:
            continue
        lease_level = annual_expense_amount(
            year_1_amount=year_1_amount,
            expense_growth=expense_growth,
            model_year=model_year,
        )
        assert lease_level.hex() == detailed[model_year - 1].hex(), (
            f"drift at amount={year_1_amount!r} growth={expense_growth!r} "
            f"year={model_year}"
        )


def test_g13_the_forward_h_plus_one_index_is_bit_identical_too() -> None:
    """Detailed slices ``_by_year`` to ``H``, so its Year ``H+1`` expense is
    visible only through ``exit_noi``. With every revenue line zero and a zero
    fee, ``exit_noi`` is exactly the negated Year-``H+1`` tax."""

    detailed_inputs = DetailedOperatingInputs(
        gross_potential_rent=0.0,
        other_income=0.0,
        vacancy_credit_loss_pct=0.0,
        property_taxes=1_200_000.0,
        insurance=0.0,
        utilities=0.0,
        repairs_maintenance=0.0,
        other_operating_expenses=0.0,
        management_fee_pct=0.0,
        revenue_growth=0.0,
        expense_growth=0.03,
    )
    projection = build_detailed_operating_projection(
        detailed_inputs, hold_period=_HOLD_PERIOD, purchase_price=10_000_000.0
    )

    detailed_year_six = -projection.exit_noi
    lease_level_year_six = annual_expense_amount(
        year_1_amount=1_200_000.0,
        expense_growth=0.03,
        model_year=_HOLD_PERIOD + 1,
    )

    assert lease_level_year_six.hex() == detailed_year_six.hex()


def test_g13_year_one_is_the_base_year_bit_for_bit() -> None:
    """Exponent ``0``, factor exactly ``1.0``, so Year 1 is the input itself."""

    for amount in _EQUIVALENCE_AMOUNTS:
        for growth in _EQUIVALENCE_GROWTHS:
            result = annual_expense_amount(
                year_1_amount=amount, expense_growth=growth, model_year=1
            )
            assert result.hex() == amount.hex()


# =============================================================================
# G14 -- the expanded pool reconciliation
# =============================================================================


@pytest.mark.parametrize("ratio", [0.0, 0.25, 0.5, 0.6, 0.9, 1.0])
def test_g14_the_pool_equals_the_ratio_times_the_five_expanded_lines(
    ratio: float,
) -> None:
    """The accepted authority is the **expanded** five-line form, never a
    ``total operating expenses - management fee`` shortcut (D4 Section 12.1).
    No management fee exists at this gate to subtract."""

    schedule = _schedule(expense_growth=0.03)
    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=ratio)

    for position in range(len(schedule.months)):
        expanded = ratio * (
            schedule.property_taxes[position]
            + schedule.insurance[position]
            + schedule.utilities[position]
            + schedule.repairs_maintenance[position]
            + schedule.other_operating_expenses[position]
        )
        assert pool.recoverable_expenses[position] == pytest.approx(
            expanded, abs=1e-9
        )


def test_g14_the_pool_never_exceeds_the_eligible_expenses() -> None:
    schedule = _schedule(expense_growth=0.03)
    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=1.0)

    for position in range(len(schedule.months)):
        assert (
            pool.recoverable_expenses[position]
            <= schedule.fixed_operating_expenses[position] + 1e-9
        )


def test_g14_every_pool_figure_is_non_negative() -> None:
    """``RecoverableExpensePool``'s own domain, satisfied automatically."""

    schedule = _schedule(expense_growth=0.03)
    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.6)

    assert all(amount >= 0.0 for amount in pool.recoverable_expenses)


# =============================================================================
# G15 -- canonical length and month identity
# =============================================================================


@pytest.mark.parametrize("hold_period", [1, 2, 5, 10, 30])
def test_g15_the_schedule_spans_the_whole_canonical_projection(
    hold_period: int,
) -> None:
    months = _months(hold_period=hold_period)

    schedule = build_property_expense_schedule(_inputs(), months=months)

    expected = 12 * hold_period + 12
    assert len(months) == expected
    for series in (
        schedule.property_taxes,
        schedule.insurance,
        schedule.utilities,
        schedule.repairs_maintenance,
        schedule.other_operating_expenses,
        schedule.fixed_operating_expenses,
    ):
        assert len(series) == expected


def test_g15_the_schedule_carries_the_canonical_months_by_reference() -> None:
    """One timeline. The pool must share month *identity* with every lease
    schedule, or ``recoveries.py``'s alignment checks would pass on length
    alone."""

    months = _months()

    schedule = build_property_expense_schedule(_inputs(), months=months)
    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.6)

    assert schedule.months is months
    assert pool.months is months


def test_g15_the_pool_length_matches_the_schedule() -> None:
    schedule = _schedule()

    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.6)

    assert len(pool.recoverable_expenses) == len(schedule.months)


def test_g15_the_pool_is_the_existing_d3_contract() -> None:
    """D4 constructs the input D3 already knows how to consume; no parallel
    pool type exists (HD-D3-8)."""

    pool = build_recoverable_expense_pool(
        _schedule(), recoverable_expense_ratio=0.6
    )

    assert type(pool) is RecoverableExpensePool


# =============================================================================
# G16 -- determinism and immutability
# =============================================================================


def test_g16_repeated_builds_are_equal() -> None:
    first = _schedule(expense_growth=0.03)
    second = _schedule(expense_growth=0.03)

    assert first == second


def test_g16_repeated_pool_builds_are_equal() -> None:
    schedule = _schedule(expense_growth=0.03)

    first = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.6)
    second = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.6)

    assert first == second


def test_g16_repeated_builds_are_bit_identical() -> None:
    """Equality is not enough for a financial series; assert the bits."""

    first = _schedule(expense_growth=0.03)
    second = _schedule(expense_growth=0.03)

    assert [value.hex() for value in first.fixed_operating_expenses] == [
        value.hex() for value in second.fixed_operating_expenses
    ]


def test_g16_the_schedule_is_immutable() -> None:
    schedule = _schedule()

    with pytest.raises(dataclasses.FrozenInstanceError):
        schedule.property_taxes = ()  # type: ignore[misc]


def test_g16_the_operating_inputs_are_immutable() -> None:
    operating_inputs = _inputs()

    with pytest.raises(dataclasses.FrozenInstanceError):
        operating_inputs.property_taxes = 0.0  # type: ignore[misc]


def test_g16_the_series_are_tuples_not_lists() -> None:
    schedule = _schedule()

    assert isinstance(schedule.property_taxes, tuple)
    assert isinstance(schedule.fixed_operating_expenses, tuple)


# =============================================================================
# Adversarial -- amounts
# =============================================================================


@pytest.mark.parametrize("line", FIXED_EXPENSE_LINES)
def test_a_single_zero_line_is_valid_and_drops_out_of_the_total(
    line: str,
) -> None:
    """A building with no separately metered utilities carries ``0.0``."""

    schedule = _schedule(**{line: 0.0})

    assert getattr(schedule, line)[0] == 0.0
    assert schedule.fixed_operating_expenses[0] == 150_000.0 - {
        "property_taxes": 100_000.0,
        "insurance": 10_000.0,
        "utilities": 20_000.0,
        "repairs_maintenance": 15_000.0,
        "other_operating_expenses": 5_000.0,
    }[line]


def test_all_lines_zero_produces_a_zero_schedule_and_zero_pool() -> None:
    overrides = {line: 0.0 for line in FIXED_EXPENSE_LINES}

    schedule = _schedule(expense_growth=0.03, **overrides)
    pool = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=1.0)

    assert schedule.fixed_operating_expenses == tuple(0.0 for _ in schedule.months)
    assert pool.recoverable_expenses == tuple(0.0 for _ in schedule.months)


def test_a_very_small_finite_expense_survives_the_division() -> None:
    schedule = _schedule(property_taxes=1.2e-6)

    assert schedule.property_taxes[0] == pytest.approx(1.0e-7, rel=1e-12)


def test_a_large_cre_expense_projects_without_overflow() -> None:
    schedule = _schedule(property_taxes=9.87654321e8, expense_growth=0.03)

    assert schedule.property_taxes[0] == pytest.approx(
        9.87654321e8 / 12, rel=1e-12
    )
    assert all(
        value == value for value in schedule.property_taxes
    )  # no NaN anywhere


def test_negative_expense_growth_shrinks_the_schedule() -> None:
    """``> -1`` permits negative growth -- a successful tax appeal is
    ordinary."""

    schedule = _schedule(expense_growth=-0.02)

    assert schedule.property_taxes[12] == pytest.approx(98_000.0, abs=1e-9)
    assert schedule.property_taxes[12] < schedule.property_taxes[0]


def test_an_overflowing_growth_rate_is_refused_rather_than_returning_inf() -> None:
    """The mirrored ``_growth_factor`` surfaces ``OverflowError`` as ``inf`` so
    ``ensure_finite`` can reject it explicitly, exactly as both engine
    producers do."""

    with pytest.raises(NonFiniteResultError):
        build_property_expense_schedule(
            _inputs(property_taxes=1e300, expense_growth=1e300),
            months=_months(hold_period=30),
        )


# =============================================================================
# Adversarial -- validation domains
# =============================================================================


@pytest.mark.parametrize("line", FIXED_EXPENSE_LINES)
def test_a_negative_expense_line_is_an_error(line: str) -> None:
    result = validate_lease_level_operating_inputs(_inputs(**{line: -1.0}))

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.PROPERTY_EXPENSE_OUT_OF_DOMAIN
    ]
    assert result.errors[0].path == f"operating_inputs.{line}"


@pytest.mark.parametrize("line", FIXED_EXPENSE_LINES)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_expense_line_is_an_error(line: str, bad: float) -> None:
    result = validate_lease_level_operating_inputs(_inputs(**{line: bad}))

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.NON_FINITE_VALUE
    ]


@pytest.mark.parametrize("growth", [-1.0, -1.5, -2.0])
def test_expense_growth_at_or_below_minus_one_is_an_error(growth: float) -> None:
    """The exact Detailed domain: strictly greater than ``-1``."""

    result = validate_lease_level_operating_inputs(_inputs(expense_growth=growth))

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.EXPENSE_GROWTH_OUT_OF_DOMAIN
    ]


@pytest.mark.parametrize("growth", [-0.999999, -0.5, 0.0, 0.03, 5.0, 1e6])
def test_expense_growth_above_minus_one_is_valid_with_no_upper_bound(
    growth: float,
) -> None:
    result = validate_lease_level_operating_inputs(_inputs(expense_growth=growth))

    assert result.is_valid


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_expense_growth_is_an_error(bad: float) -> None:
    result = validate_lease_level_operating_inputs(_inputs(expense_growth=bad))

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.NON_FINITE_VALUE
    ]


@pytest.mark.parametrize("ratio", [-0.01, -1.0, 1.01, 60.0])
def test_a_recoverable_ratio_outside_zero_to_one_is_an_error(
    ratio: float,
) -> None:
    """No silent clipping: ``60`` meaning 60% is refused, never clamped to
    ``1.0``."""

    result = validate_lease_level_operating_inputs(
        _inputs(recoverable_expense_ratio=ratio)
    )

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.RECOVERABLE_EXPENSE_RATIO_OUT_OF_DOMAIN
    ]


@pytest.mark.parametrize("ratio", [0.0, 0.5, 1.0])
def test_both_recoverable_ratio_endpoints_are_valid(ratio: float) -> None:
    assert validate_lease_level_operating_inputs(
        _inputs(recoverable_expense_ratio=ratio)
    ).is_valid
    assert validate_recoverable_expense_ratio(ratio).is_valid


@pytest.mark.parametrize("ratio", [-0.01, 1.01, float("nan")])
def test_the_pool_builder_refuses_an_out_of_domain_ratio(ratio: float) -> None:
    schedule = _schedule()

    with pytest.raises(LeaseValidationError):
        build_recoverable_expense_pool(schedule, recoverable_expense_ratio=ratio)


def test_the_expense_builder_refuses_invalid_operating_inputs() -> None:
    with pytest.raises(LeaseValidationError):
        build_property_expense_schedule(
            _inputs(property_taxes=-1.0), months=_months()
        )


def test_validation_error_ordering_is_deterministic_and_canonical() -> None:
    """Fixed rule order: the five expense lines in schedule order, then
    ``expense_growth``, then the ratio, then the revenue and rate fields."""

    result = validate_lease_level_operating_inputs(
        _inputs(
            property_taxes=-1.0,
            insurance=-1.0,
            utilities=-1.0,
            repairs_maintenance=-1.0,
            other_operating_expenses=-1.0,
            expense_growth=-2.0,
            recoverable_expense_ratio=5.0,
            other_income=-1.0,
            other_income_growth=-3.0,
            management_fee_pct=9.0,
            credit_loss_pct=9.0,
        )
    )

    assert [issue.path for issue in result.errors] == [
        "operating_inputs.property_taxes",
        "operating_inputs.insurance",
        "operating_inputs.utilities",
        "operating_inputs.repairs_maintenance",
        "operating_inputs.other_operating_expenses",
        "operating_inputs.expense_growth",
        "operating_inputs.recoverable_expense_ratio",
        "operating_inputs.other_income",
        "operating_inputs.other_income_growth",
        "operating_inputs.management_fee_pct",
        "operating_inputs.credit_loss_pct",
    ]


def test_validation_error_ordering_is_stable_across_runs() -> None:
    inputs = _inputs(property_taxes=-1.0, utilities=-1.0, expense_growth=-2.0)

    first = validate_lease_level_operating_inputs(inputs)
    second = validate_lease_level_operating_inputs(inputs)

    assert [issue.path for issue in first.issues] == [
        issue.path for issue in second.issues
    ]


# =============================================================================
# Adversarial -- the inert fields are still validated
# =============================================================================


def test_a_negative_other_income_is_an_error_even_though_it_is_inert() -> None:
    """Validating a value is not calculating with it. An accepted field that
    nothing checks is a hole."""

    result = validate_lease_level_operating_inputs(_inputs(other_income=-1.0))

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.OTHER_INCOME_OUT_OF_DOMAIN
    ]


@pytest.mark.parametrize("pct", [-0.01, 1.01])
def test_a_management_fee_pct_outside_zero_to_one_is_an_error(pct: float) -> None:
    result = validate_lease_level_operating_inputs(_inputs(management_fee_pct=pct))

    assert [issue.code for issue in result.errors] == [
        LeaseIssueCode.MANAGEMENT_FEE_OUT_OF_DOMAIN
    ]


@pytest.mark.parametrize("pct", [-0.01, 1.01])
def test_a_credit_loss_pct_outside_zero_to_one_is_an_error(pct: float) -> None:
    result = validate_lease_level_operating_inputs(_inputs(credit_loss_pct=pct))

    assert LeaseIssueCode.CREDIT_LOSS_OUT_OF_DOMAIN in [
        issue.code for issue in result.errors
    ]


def test_credit_loss_above_ten_percent_warns_but_stays_valid() -> None:
    """Lease-Level credit loss is bad debt only; physical vacancy is already
    modeled per suite per month, so a Detailed blended figure carried across
    is the likely cause (D0 Section 15.4)."""

    result = validate_lease_level_operating_inputs(_inputs(credit_loss_pct=0.12))

    assert result.is_valid
    assert [issue.code for issue in result.warnings] == [
        LeaseIssueCode.UNUSUALLY_HIGH_CREDIT_LOSS
    ]
    assert result.warnings[0].severity is LeaseIssueSeverity.WARNING


@pytest.mark.parametrize("pct", [0.0, 0.05, 0.10])
def test_credit_loss_at_or_below_ten_percent_does_not_warn(pct: float) -> None:
    result = validate_lease_level_operating_inputs(_inputs(credit_loss_pct=pct))

    assert not result.warnings


def test_an_out_of_domain_credit_loss_does_not_also_warn() -> None:
    """One finding per defect: the domain error is the report."""

    result = validate_lease_level_operating_inputs(_inputs(credit_loss_pct=5.0))

    assert not result.warnings


def test_the_credit_loss_warning_does_not_block_the_expense_build() -> None:
    schedule = build_property_expense_schedule(
        _inputs(credit_loss_pct=0.12), months=_months()
    )

    assert schedule.fixed_operating_expenses[0] == 150_000.0


# =============================================================================
# Adversarial -- the canonical month guard
# =============================================================================


def test_an_empty_month_tuple_is_refused() -> None:
    with pytest.raises(ValueError, match="canonical ModelMonth timeline"):
        build_property_expense_schedule(_inputs(), months=())


def test_a_repeated_month_object_is_refused() -> None:
    """A duplicated month would zip cleanly and shift every growth step."""

    months = _months()
    broken = (months[0],) + months[:-1]

    with pytest.raises(ValueError, match="period_index"):
        build_property_expense_schedule(_inputs(), months=broken)


def test_a_reordered_month_tuple_is_refused() -> None:
    months = _months()
    broken = months[1:2] + months[0:1] + months[2:]

    with pytest.raises(ValueError, match="period_index"):
        build_property_expense_schedule(_inputs(), months=broken)


def test_a_truncated_month_tuple_is_refused_when_indices_do_not_start_at_one() -> None:
    months = _months()

    with pytest.raises(ValueError, match="period_index"):
        build_property_expense_schedule(_inputs(), months=months[1:])


def test_a_month_whose_hold_year_contradicts_its_index_is_refused() -> None:
    """``hold_year`` drives the growth step, so a hand-built month claiming the
    wrong year would silently move an expense step."""

    months = _months()
    broken = (
        dataclasses.replace(months[0], hold_year=4),
    ) + months[1:]

    with pytest.raises(ValueError, match="hold_year"):
        build_property_expense_schedule(_inputs(), months=broken)


@pytest.mark.parametrize("hold_period", [1, 2])
def test_short_hold_periods_project_correctly(hold_period: int) -> None:
    months = _months(hold_period=hold_period)

    schedule = build_property_expense_schedule(
        _inputs(expense_growth=0.03), months=months
    )

    assert len(schedule.months) == 12 * hold_period + 12
    assert schedule.property_taxes[0] == 100_000.0
    assert schedule.property_taxes[-1] == pytest.approx(
        1_200_000.0 * (1.03**hold_period) / 12, abs=1e-9
    )


def test_a_long_hold_period_projects_every_anniversary() -> None:
    months = _months(hold_period=30)

    schedule = build_property_expense_schedule(
        _inputs(expense_growth=0.03), months=months
    )

    for model_year in range(1, 32):
        position = (model_year - 1) * 12
        assert schedule.property_taxes[position] == pytest.approx(
            1_200_000.0 * (1.03 ** (model_year - 1)) / 12, abs=1e-9
        )


# =============================================================================
# The one-way dependency, asserted behaviourally
# =============================================================================


def test_the_pool_is_a_pure_function_of_the_completed_schedule() -> None:
    """Two different operating inputs that happen to produce the same monthly
    expense schedule produce the same pool -- the pool sees the schedule and
    nothing else, so no growth calculation of its own can drift (FM-D4-40)."""

    left = _schedule(
        property_taxes=1_200_000.0,
        insurance=120_000.0,
        utilities=240_000.0,
        repairs_maintenance=180_000.0,
        other_operating_expenses=60_000.0,
    )
    right = _schedule(
        property_taxes=600_000.0,
        insurance=720_000.0,
        utilities=240_000.0,
        repairs_maintenance=180_000.0,
        other_operating_expenses=60_000.0,
    )

    assert left.fixed_operating_expenses == right.fixed_operating_expenses
    assert build_recoverable_expense_pool(
        left, recoverable_expense_ratio=0.6
    ).recoverable_expenses == build_recoverable_expense_pool(
        right, recoverable_expense_ratio=0.6
    ).recoverable_expenses


def test_the_pool_scales_linearly_with_the_ratio() -> None:
    """No hidden threshold, floor, cap or category weighting."""

    schedule = _schedule(expense_growth=0.03)

    half = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=0.5)
    full = build_recoverable_expense_pool(schedule, recoverable_expense_ratio=1.0)

    for position in range(len(schedule.months)):
        assert half.recoverable_expenses[position] == pytest.approx(
            full.recoverable_expenses[position] / 2, abs=1e-9
        )


def test_the_pool_responds_to_every_eligible_line() -> None:
    """Each of the five lines must reach the pool; omitting one is the D4.1
    mutation "one eligible fixed expense line is omitted from the pool"."""

    baseline = build_recoverable_expense_pool(
        _schedule(), recoverable_expense_ratio=1.0
    )

    for line in FIXED_EXPENSE_LINES:
        bumped = build_recoverable_expense_pool(
            _schedule(**{line: getattr(_inputs(), line) + 120_000.0}),
            recoverable_expense_ratio=1.0,
        )
        assert bumped.recoverable_expenses[0] == pytest.approx(
            baseline.recoverable_expenses[0] + 10_000.0, abs=1e-9
        ), f"{line} does not reach the recoverable pool"
