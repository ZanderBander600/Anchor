"""Phase 7 Gate P7.10 Stage 1 -- the valuation definition contract.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 5.1 to 5.4 and
the ratified decisions R-A, R-C and R-D.

Structural faults of a definition are issues; faults that depend on a variant
never are. A definition with any issue is refused whole.
"""

from __future__ import annotations

import pytest
from _p7_10_fixtures import (  # type: ignore[import-not-found]
    cap,
    instruction,
    stated,
    timepoint,
    unit,
    variant,
)

from anchor.valuation import (
    ValuationAvailability,
    ValuationIssueCode,
    ValuationKind,
    ValuationMethodKind,
    ValuationScopeKind,
    ValuationValidationError,
    require_valid_valuation_timepoint,
    resolve_investment_valuation,
    validate_valuation_timepoint,
)


def _codes(**kwargs: object) -> list[ValuationIssueCode]:
    return [issue.code for issue in validate_valuation_timepoint(timepoint(**kwargs))]  # type: ignore[arg-type]


# =============================================================================
# 1. The enumerations
# =============================================================================


def test_the_valuation_kinds_are_exactly_the_three_stored_kinds() -> None:
    """``EXIT`` is deliberately absent: it is reserved and system derived, and
    is never stored as a definition (R-B)."""

    assert [member.value for member in ValuationKind] == ["as_is", "stabilized", "custom"]


def test_the_initial_methods_are_exactly_two() -> None:
    """No DCF, appraisal, comparable-sales or AI-estimated method (R-D)."""

    assert [member.value for member in ValuationMethodKind] == ["direct_cap", "analyst_value"]


def test_the_scope_kinds_are_unit_and_investment() -> None:
    assert [member.value for member in ValuationScopeKind] == ["unit", "investment"]


# =============================================================================
# 2. Identity and labels
# =============================================================================


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_timepoint_id_is_refused(blank: str) -> None:
    assert ValuationIssueCode.BLANK_TIMEPOINT_ID in _codes(timepoint_id=blank)


@pytest.mark.parametrize("blank", ["", "  "])
def test_a_blank_investment_id_is_refused(blank: str) -> None:
    assert ValuationIssueCode.BLANK_INVESTMENT_ID in _codes(investment_id=blank)


@pytest.mark.parametrize("blank", ["", "\t"])
def test_a_blank_label_is_refused(blank: str) -> None:
    assert ValuationIssueCode.BLANK_LABEL in _codes(label=blank)


def test_a_label_is_presentation_only_and_never_changes_a_value() -> None:
    """Renaming a definition is presentation; moving its model month is a
    different valuation (Section 5.2)."""

    only = unit("u1")
    first = resolve_investment_valuation(
        timepoint(label="As-Is", instructions=(instruction("u1", cap(0.05)),)), variant=variant(only)
    )
    renamed = resolve_investment_valuation(
        timepoint(label="Going-In Value", instructions=(instruction("u1", cap(0.05)),)), variant=variant(only)
    )
    assert first.value == renamed.value
    assert first.label != renamed.label


# =============================================================================
# 3. Timing (R-A, R-C)
# =============================================================================


@pytest.mark.parametrize("month", [-12, 1, 6, 13, 18, 25])
def test_an_inside_year_or_negative_month_is_refused(month: int) -> None:
    assert _codes(kind=ValuationKind.CUSTOM, model_month=month) == [ValuationIssueCode.INVALID_MODEL_MONTH]


def test_as_is_must_be_closing() -> None:
    assert _codes(kind=ValuationKind.AS_IS, model_month=24) == [ValuationIssueCode.KIND_MONTH_MISMATCH]


def test_stabilized_must_not_be_closing() -> None:
    """Anchor never infers stabilization; the analyst declares its month, and
    stabilization at closing is As-Is (R-C)."""

    assert _codes(kind=ValuationKind.STABILIZED, model_month=0) == [ValuationIssueCode.KIND_MONTH_MISMATCH]


@pytest.mark.parametrize("month", [0, 12, 24, 36])
def test_custom_may_be_closing_or_any_hold_year_end(month: int) -> None:
    assert _codes(kind=ValuationKind.CUSTOM, model_month=month) == []


def test_the_horizon_is_not_a_definition_fault() -> None:
    """A month beyond a variant's hold is a typed unavailable result, not a
    malformed definition: the same definition may resolve under a longer
    hold."""

    far = timepoint("late", kind=ValuationKind.CUSTOM, model_month=12 * 9, instructions=(instruction("u1"),))
    assert validate_valuation_timepoint(far) == ()
    assert resolve_investment_valuation(far, variant=variant(unit("u1"))).status is ValuationAvailability.UNAVAILABLE


# =============================================================================
# 4. Instructions (Section 5.1)
# =============================================================================


def test_a_definition_with_no_instruction_is_refused() -> None:
    assert _codes(instructions=()) == [ValuationIssueCode.NO_UNIT_INSTRUCTION]


def test_two_instructions_for_one_unit_are_refused() -> None:
    """Exactly one instruction values a Unit; no instruction overrides
    another, and list position never decides which wins."""

    doubled = (instruction("u1", cap(0.05)), instruction("u1", cap(0.09)))
    assert ValuationIssueCode.DUPLICATE_UNIT_INSTRUCTION in _codes(instructions=doubled)


def test_a_blank_unit_id_is_refused() -> None:
    assert ValuationIssueCode.BLANK_UNIT_ID in _codes(instructions=(instruction("  ", cap(0.05)),))


# =============================================================================
# 5. Methods (R-D)
# =============================================================================


@pytest.mark.parametrize("rate", [0.0, -0.01, float("inf"), float("-inf"), float("nan")])
def test_a_cap_rate_is_finite_and_greater_than_zero(rate: float) -> None:
    assert _codes(instructions=(instruction("u1", cap(rate)),)) == [ValuationIssueCode.INVALID_CAP_RATE]


@pytest.mark.parametrize("amount", [-1.0, float("inf"), float("nan")])
def test_an_analyst_amount_is_finite_and_non_negative(amount: float) -> None:
    assert _codes(instructions=(instruction("u1", stated(amount)),)) == [
        ValuationIssueCode.INVALID_ANALYST_AMOUNT
    ]


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_analyst_value_requires_a_nonblank_evidence_identifier(blank: str) -> None:
    """Stage 1 validates the identifier structurally; evidence persistence and
    approval are Stage 2 (R-D, R-G)."""

    assert _codes(instructions=(instruction("u1", stated(1.0, blank)),)) == [
        ValuationIssueCode.BLANK_EVIDENCE_ID
    ]


def test_an_unsupported_method_object_is_refused() -> None:
    assert _codes(instructions=(instruction("u1", object()),)) == [  # type: ignore[arg-type]
        ValuationIssueCode.UNSUPPORTED_METHOD
    ]


# =============================================================================
# 6. Refused whole
# =============================================================================


def test_a_definition_with_any_issue_is_never_partially_resolved() -> None:
    broken = timepoint(instructions=(instruction("u1", cap(0.05)), instruction("u2", cap(0.0))))
    with pytest.raises(ValuationValidationError) as raised:
        resolve_investment_valuation(broken, variant=variant(unit("u1"), unit("u2")))
    assert [issue.code for issue in raised.value.issues] == [ValuationIssueCode.INVALID_CAP_RATE]


def test_require_returns_a_well_formed_definition_unchanged() -> None:
    good = timepoint()
    assert require_valid_valuation_timepoint(good) is good


def test_issues_are_reported_in_canonical_unit_order_not_list_order() -> None:
    forward = validate_valuation_timepoint(
        timepoint(instructions=(instruction("u2", cap(0.0)), instruction("u1", cap(-1.0))))
    )
    backward = validate_valuation_timepoint(
        timepoint(instructions=(instruction("u1", cap(-1.0)), instruction("u2", cap(0.0))))
    )
    assert [issue.unit_id for issue in forward] == ["u1", "u2"]
    assert forward == backward
