"""Phase 7 Gate P7.10 Stage 1 -- executing the ``PctOfValue`` funding rule.

``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Section 6 and the
ratified decision R-E.

The round-number Unit makes every expectation checkable by hand: a $10,000,000
purchase with a flat $800,000 NOI, an 8% exit cap and a $6,000,000 acquisition
loan at 5% interest-only. Its As-Is value at an 8% cap is therefore exactly
$800,000 / 0.08 = $10,000,000, and 25% of it is $2,500,000.
"""

from __future__ import annotations

import dataclasses

import pytest
from _p7_7_fixtures import INVESTMENT, unit_scope  # type: ignore[import-not-found]
from _p7_8_fixtures import UNIT, cash_pay_debt, claim_position, round_unit, structure  # type: ignore[import-not-found]

from anchor.capital_structure import (
    CapitalPosition,
    CapitalStructureError,
    FixedAmount,
    FundingEvent,
    PctOfValue,
    PositionClass,
    PositionScope,
    ScopeKind,
    ShortfallResolution,
)
from anchor.capital_structure.execution import execute_unit_capital_structure
from anchor.capital_structure.execution_contracts import (
    CapitalStructureExecutionError,
    ExecutionIssueCode,
    StructuredCapitalResult,
)
from anchor.contracts import AcquisitionTerms
from anchor.engine.contracts import AcquisitionResults
from anchor.valuation import (
    DirectCap,
    ValuationAuthority,
    ValuationAvailability,
    FundingResolutionStatus,
    ResolvedValuationFunding,
    UnitValuationInstruction,
    UnresolvedFundingReason,
    UnresolvedFundingRequirement,
    ValuationKind,
    ValuationScopeKind,
    ValuationTimepoint,
    ValuationUnavailableReason,
    resolve_investment_valuation,
    resolve_pct_of_value_funding,
    unit_inputs,
    valuation_authority,
    variant_inputs,
)

CEC = ShortfallResolution.COMMON_EQUITY_CONTRIBUTION
INVESTMENT_ID = "inv-1"
AS_IS_CAP = 0.08
#: 800,000 / 0.08, by hand.
AS_IS_VALUE = 10_000_000.0
PCT = 0.25
#: 0.25 * 10,000,000, by hand.
EXPECTED_FUNDING = 2_500_000.0


# =============================================================================
# Builders
# =============================================================================


def _as_is(*, cap_rate: float = AS_IS_CAP, unit_id: str = UNIT, investment_id: str = INVESTMENT_ID,
           model_month: int = 0) -> ValuationTimepoint:
    return ValuationTimepoint(
        timepoint_id="as-is",
        investment_id=investment_id,
        kind=ValuationKind.AS_IS if model_month == 0 else ValuationKind.CUSTOM,
        label="As-Is",
        model_month=model_month,
        unit_instructions=(UnitValuationInstruction(unit_id=unit_id, method=DirectCap(cap_rate=cap_rate)),),
    )


def _authority(
    timepoint: ValuationTimepoint, terms: AcquisitionTerms, results: AcquisitionResults, *, unit_id: str = UNIT
) -> ValuationAuthority:
    inputs = unit_inputs(unit_id=unit_id, terms=terms, results=results)
    variant = variant_inputs(investment_id=timepoint.investment_id, units=(inputs,))
    return valuation_authority(
        investment_id=timepoint.investment_id, valuations=(resolve_investment_valuation(timepoint, variant=variant),)
    )


def _valued_position(
    *, pct: float = PCT, month: int = 0, scope: PositionScope | None = None, timepoint_id: str = "as-is"
) -> CapitalPosition:
    return claim_position(
        "mezz",
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=2,
        terms=cash_pay_debt(rate=0.12, io_period=5, maturity_month=60),
        resolution=CEC,
        funding_events=(
            FundingEvent(
                event_id="mezz-funding",
                model_month=month,
                sequence=1,
                amount_rule=PctOfValue(timepoint_id=timepoint_id, pct=pct),
            ),
        ),
        scope=scope,
    )


def _fixed_position(amount: float) -> CapitalPosition:
    return claim_position(
        "mezz",
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=2,
        terms=cash_pay_debt(rate=0.12, io_period=5, maturity_month=60),
        resolution=CEC,
        amount=amount,
    )


def _execute(
    position: CapitalPosition,
    authority: ValuationAuthority | None,
    terms: AcquisitionTerms,
    results: AcquisitionResults,
) -> StructuredCapitalResult:
    return execute_unit_capital_structure(
        unit_id=UNIT,
        terms=terms,
        results=results,
        capital_structure=structure(position),
        valuations=authority,
    )


# =============================================================================
# 1. Compatibility: absent P7.10 structure changes nothing
# =============================================================================


def test_without_an_authority_the_rule_is_refused_with_its_original_reason() -> None:
    """Every pre-P7.10 caller passes no authority, so ``PctOfValue`` is refused
    exactly as P7.8 refused it -- same code, same message."""

    terms, results = round_unit()
    with pytest.raises(CapitalStructureExecutionError) as raised:
        _execute(_valued_position(), None, terms, results)
    (issue,) = raised.value.issues
    assert issue.code is ExecutionIssueCode.UNSUPPORTED_AMOUNT_RULE
    assert "valuation timepoints are not executed yet" in issue.message


def test_a_structure_without_a_pct_of_value_rule_is_identical_with_and_without_an_authority() -> None:
    """Supplying a valuation authority to an analysis that consumes none
    changes no number anywhere."""

    terms, results = round_unit()
    authority = _authority(_as_is(), terms, results)
    plain = _fixed_position(EXPECTED_FUNDING)
    assert _execute(plain, None, terms, results) == _execute(plain, authority, terms, results)


def test_an_unstructured_analysis_is_untouched_by_a_resolved_valuation() -> None:
    """A report-only valuation does not invalidate the Acquisition analysis:
    resolving one changes no completed result."""

    terms, results = round_unit()
    before = dataclasses.replace(results)
    valuation = resolve_investment_valuation(
        _as_is(), variant=variant_inputs(investment_id=INVESTMENT_ID, units=(unit_inputs(unit_id=UNIT, terms=terms, results=results),))
    )
    assert valuation.value == pytest.approx(AS_IS_VALUE)
    assert results == before
    assert execute_unit_capital_structure(unit_id=UNIT, terms=terms, results=results) == execute_unit_capital_structure(
        unit_id=UNIT, terms=terms, results=results
    )


# =============================================================================
# 2. The exact amount (R-E)
# =============================================================================


def test_the_funding_is_exactly_pct_of_the_scope_value() -> None:
    terms, results = round_unit()
    result = _execute(_valued_position(), _authority(_as_is(), terms, results), terms, results)
    (position,) = result.positions
    (event,) = position.funding
    assert event.amount == pytest.approx(EXPECTED_FUNDING)
    assert position.funded_amount == pytest.approx(EXPECTED_FUNDING)


def test_a_valuation_is_not_an_acquisition_price() -> None:
    """``price_basis`` stays ``None``: reporting a valuation as a stated
    acquisition price would be false, and the LTV metrics keep measuring
    against the price."""

    terms, results = round_unit()
    result = _execute(_valued_position(), _authority(_as_is(), terms, results), terms, results)
    (position,) = result.positions
    (event,) = position.funding
    assert event.price_basis is None
    assert isinstance(event.amount_rule, PctOfValue)
    assert position.valuation_basis.amount == 10_000_000.0


def test_a_valued_funding_matches_the_same_amount_stated_fixed() -> None:
    """Sizing from a valuation changes only the amount rule. Every other
    figure -- the schedule, the claims, the residual, the returns -- is what
    the identical fixed funding produces, so no priority, availability, fee,
    shortfall or cash-flow rule moved."""

    terms, results = round_unit()
    valued = _execute(_valued_position(), _authority(_as_is(), terms, results), terms, results)
    fixed = _execute(_fixed_position(EXPECTED_FUNDING), None, terms, results)
    assert valued.common_equity == fixed.common_equity
    assert valued.funding_requirements == fixed.funding_requirements
    assert valued.status == fixed.status
    (from_value,) = valued.positions
    (from_price,) = fixed.positions
    assert from_value.annual_cash_flows == from_price.annual_cash_flows
    assert from_value.irr == from_price.irr
    assert from_value.moic == from_price.moic
    assert from_value.debt_schedule == from_price.debt_schedule


# =============================================================================
# 3. Timing, ownership and scope (R-E)
# =============================================================================


def test_a_funding_month_that_is_not_the_valuation_month_does_not_resolve() -> None:
    """Neither is moved to the other, and no value is interpolated between
    them."""

    resolution = resolve_pct_of_value_funding(
        event_id="e",
        position_id="mezz",
        event_model_month=0,
        timepoint_id="stabilized",
        pct=PCT,
        scope_kind=ValuationScopeKind.UNIT,
        unit_id=UNIT,
        authority=_authority_for_month(24),
    )
    assert isinstance(resolution, UnresolvedFundingRequirement)
    assert resolution.reason is UnresolvedFundingReason.MODEL_MONTH_MISMATCH


def _authority_for_month(month: int) -> ValuationAuthority:
    terms, results = round_unit()
    timepoint = dataclasses.replace(
        _as_is(model_month=month), timepoint_id="stabilized", kind=ValuationKind.STABILIZED
    )
    return _authority(timepoint, terms, results)


def test_a_timepoint_of_another_investment_never_sizes_this_funding() -> None:
    terms, results = round_unit()
    foreign = _authority(_as_is(investment_id="other-investment"), terms, results)
    resolution = resolve_pct_of_value_funding(
        event_id="e",
        position_id="mezz",
        event_model_month=0,
        timepoint_id="as-is",
        pct=PCT,
        scope_kind=ValuationScopeKind.UNIT,
        unit_id=UNIT,
        authority=dataclasses.replace(foreign, investment_id=INVESTMENT_ID),
    )
    assert isinstance(resolution, UnresolvedFundingRequirement)
    assert resolution.reason is UnresolvedFundingReason.FOREIGN_INVESTMENT


def test_an_unknown_timepoint_never_falls_back_to_another() -> None:
    terms, results = round_unit()
    resolution = resolve_pct_of_value_funding(
        event_id="e",
        position_id="mezz",
        event_model_month=0,
        timepoint_id="never-authored",
        pct=PCT,
        scope_kind=ValuationScopeKind.UNIT,
        unit_id=UNIT,
        authority=_authority(_as_is(), terms, results),
    )
    assert isinstance(resolution, UnresolvedFundingRequirement)
    assert resolution.reason is UnresolvedFundingReason.TIMEPOINT_NOT_FOUND
    assert resolution.valuation_reason is ValuationUnavailableReason.NOT_AUTHORED


def test_a_unit_the_valuation_does_not_cover_never_borrows_the_investment_total() -> None:
    terms, results = round_unit()
    resolution = resolve_pct_of_value_funding(
        event_id="e",
        position_id="mezz",
        event_model_month=0,
        timepoint_id="as-is",
        pct=PCT,
        scope_kind=ValuationScopeKind.UNIT,
        unit_id="a-different-unit",
        authority=_authority(_as_is(), terms, results),
    )
    assert isinstance(resolution, UnresolvedFundingRequirement)
    assert resolution.reason is UnresolvedFundingReason.SCOPE_NOT_COVERED


def test_an_investment_scoped_funding_takes_the_investment_value() -> None:
    """And a Unit-scoped one its own Unit's: the scopes are never swapped."""

    terms, results = round_unit()
    authority = _authority(_as_is(), terms, results)
    whole = resolve_pct_of_value_funding(
        event_id="e", position_id="p", event_model_month=0, timepoint_id="as-is", pct=PCT,
        scope_kind=ValuationScopeKind.INVESTMENT, unit_id=None, authority=authority,
    )
    part = resolve_pct_of_value_funding(
        event_id="e", position_id="p", event_model_month=0, timepoint_id="as-is", pct=PCT,
        scope_kind=ValuationScopeKind.UNIT, unit_id=UNIT, authority=authority,
    )
    assert isinstance(whole, ResolvedValuationFunding) and isinstance(part, ResolvedValuationFunding)
    assert whole.scope_value == pytest.approx(AS_IS_VALUE)
    assert part.scope_value == pytest.approx(AS_IS_VALUE)
    assert whole.scope_kind is ValuationScopeKind.INVESTMENT
    assert part.scope_kind is ValuationScopeKind.UNIT


def test_an_investment_scoped_position_is_refused_inside_a_standalone_unit() -> None:
    """The existing scope rule is unchanged: a standalone Unit analysis has no
    Investment scope, whatever sizes the funding."""

    terms, results = round_unit()
    with pytest.raises(CapitalStructureExecutionError) as raised:
        _execute(_valued_position(scope=INVESTMENT), _authority(_as_is(), terms, results), terms, results)
    assert ExecutionIssueCode.UNSUPPORTED_SCOPE in {issue.code for issue in raised.value.issues}


def test_the_existing_closing_only_funding_rule_is_unchanged() -> None:
    """A later funding month is still refused, and nothing is moved to
    closing, so the only executable ``PctOfValue`` is a closing one."""

    terms, results = round_unit()
    with pytest.raises(CapitalStructureExecutionError) as raised:
        _execute(_valued_position(month=24), _authority_for_month(24), terms, results)
    assert ExecutionIssueCode.UNSUPPORTED_FUNDING_TIMING in {issue.code for issue in raised.value.issues}


# =============================================================================
# 4. Unresolved, never zero (Section 6)
# =============================================================================


def test_a_non_positive_forward_noi_leaves_the_funding_unresolved_not_zero() -> None:
    terms, results = round_unit(current_noi=0.0)
    with pytest.raises(CapitalStructureExecutionError) as raised:
        _execute(_valued_position(), _authority(_as_is(), terms, results), terms, results)
    (issue,) = raised.value.issues
    assert issue.code is ExecutionIssueCode.UNRESOLVED_VALUATION_FUNDING
    assert "never read as zero" in issue.message


def test_an_unresolved_requirement_reports_no_amount_at_all() -> None:
    """Not zero, not an estimate, not a resized figure: no amount field
    exists on the unresolved record."""

    terms, results = round_unit(current_noi=0.0)
    requirement = resolve_pct_of_value_funding(
        event_id="mezz-funding",
        position_id="mezz",
        event_model_month=0,
        timepoint_id="as-is",
        pct=PCT,
        scope_kind=ValuationScopeKind.UNIT,
        unit_id=UNIT,
        authority=_authority(_as_is(), terms, results),
    )
    assert isinstance(requirement, UnresolvedFundingRequirement)
    assert requirement.status is FundingResolutionStatus.UNRESOLVED
    assert not hasattr(requirement, "amount")
    assert requirement.reason is UnresolvedFundingReason.VALUATION_UNAVAILABLE
    assert requirement.valuation_reason is ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI
    assert requirement.requirement_id == "mezz/funding/mezz-funding"


def test_an_unresolvable_funding_is_never_scheduled() -> None:
    """The scheduler refuses it outright rather than advancing an assumed
    amount, so no debt schedule, claim or residual is built on a guess."""

    from anchor.capital_structure.funding import resolve_funding
    from anchor.capital_structure.execution_contracts import PriceBasis, PriceBasisKind

    terms, results = round_unit(current_noi=0.0)
    with pytest.raises(CapitalStructureError):
        resolve_funding(
            _valued_position(),
            price_basis=PriceBasis(kind=PriceBasisKind.UNIT_PURCHASE_PRICE, amount=10_000_000.0),
            valuations=_authority(_as_is(), terms, results),
        )


# =============================================================================
# 5. Identity: the valuation is an economic dependency (Section 6)
# =============================================================================


def test_changing_the_consumed_cap_rate_changes_the_structured_result() -> None:
    """A valuation a position consumes is an economic input to the resolved
    Capital Structure, so moving it moves the funded amount and everything
    downstream of it."""

    terms, results = round_unit()
    base = _execute(_valued_position(), _authority(_as_is(), terms, results), terms, results)
    moved = _execute(_valued_position(), _authority(_as_is(cap_rate=0.05), terms, results), terms, results)
    (from_base,) = base.positions
    (from_moved,) = moved.positions
    # 800,000 / 0.05 = 16,000,000; a quarter of it is 4,000,000.
    assert from_base.funded_amount == pytest.approx(EXPECTED_FUNDING)
    assert from_moved.funded_amount == pytest.approx(4_000_000.0)
    assert base.common_equity != moved.common_equity


def test_an_exact_semantic_revert_reproduces_the_result_exactly() -> None:
    """Moving the cap rate away and back is not a new economic state."""

    terms, results = round_unit()
    before = _execute(_valued_position(), _authority(_as_is(), terms, results), terms, results)
    _ = _execute(_valued_position(), _authority(_as_is(cap_rate=0.05), terms, results), terms, results)
    after = _execute(_valued_position(), _authority(_as_is(cap_rate=AS_IS_CAP), terms, results), terms, results)
    assert after == before


def test_a_label_rename_never_changes_a_funded_amount() -> None:
    terms, results = round_unit()
    plain = _authority(_as_is(), terms, results)
    renamed = _authority(dataclasses.replace(_as_is(), label="Going-In Value"), terms, results)
    assert _execute(_valued_position(), plain, terms, results).positions[0].funded_amount == (
        _execute(_valued_position(), renamed, terms, results).positions[0].funded_amount
    )


def test_the_scope_order_of_a_unit_position_is_by_id_not_list_position() -> None:
    terms, results = round_unit()
    authority = _authority(_as_is(), terms, results)
    first = _valued_position(scope=unit_scope(UNIT))
    assert first.scope.kind is ScopeKind.UNIT
    assert _execute(first, authority, terms, results).unit_ids == (UNIT,)


# =============================================================================
# 6. The existing PctOfValue validation is untouched (R-E)
# =============================================================================


@pytest.mark.parametrize("pct", [0.0, -0.1, 1.5, float("inf"), float("nan")])
def test_the_p7_7_pct_validation_still_refuses_an_out_of_range_share(pct: float) -> None:
    """P7.7 owns ``pct`` finite, greater than zero and at most one. P7.10
    neither repeats nor relaxes it: the structure is invalid before execution
    is ever considered."""

    from anchor.capital_structure import CapitalStructureValidationError

    terms, results = round_unit()
    with pytest.raises(CapitalStructureValidationError):
        _execute(_valued_position(pct=pct), _authority(_as_is(), terms, results), terms, results)


def test_a_full_share_of_value_is_permitted_and_sized_exactly() -> None:
    """``pct == 1`` is valid under P7.7 and sizes to the whole value."""

    terms, results = round_unit()
    resolution = resolve_pct_of_value_funding(
        event_id="mezz-funding",
        position_id="mezz",
        event_model_month=0,
        timepoint_id="as-is",
        pct=1.0,
        scope_kind=ValuationScopeKind.UNIT,
        unit_id=UNIT,
        authority=_authority(_as_is(), terms, results),
    )
    assert isinstance(resolution, ResolvedValuationFunding)
    assert resolution.amount == pytest.approx(AS_IS_VALUE)


def test_the_over_funded_closing_rule_still_refuses_a_valuation_sized_excess() -> None:
    """Sizing from a valuation is not a licence to over-fund. The $10,000,000
    As-Is value against a $4,000,000 closing equity need leaves $6,000,000 with
    no ratified destination, so the unchanged P7.8 rule refuses the structure:
    nothing is resized, rounded, reserved or distributed."""

    terms, results = round_unit()
    with pytest.raises(CapitalStructureExecutionError) as raised:
        _execute(_valued_position(pct=1.0), _authority(_as_is(), terms, results), terms, results)
    (issue,) = raised.value.issues
    assert issue.code is ExecutionIssueCode.OVERFUNDED_CLOSING
    assert "6,000,000.00" in issue.message


def test_no_second_amount_rule_shape_was_added() -> None:
    """``PctOfValue`` is activated, not replaced: the funding amount rules are
    still exactly the three P7.7 authored."""

    from anchor.capital_structure.contracts import FundingAmountRule

    assert set(FundingAmountRule.__args__) == {FixedAmount, __import__(
        "anchor.capital_structure.contracts", fromlist=["PctOfPrice"]
    ).PctOfPrice, PctOfValue}


# =============================================================================
# 7. Neutrality oracle: the default path is the pre-P7.10 path
# =============================================================================


def test_the_default_call_is_identical_to_an_explicit_absent_authority() -> None:
    """Every pre-P7.10 caller reaches the executor without naming
    ``valuations`` at all. Across the P7.8 structures, omitting the argument
    and passing ``None`` produce the same object, so the new parameter changes
    no existing behaviour by existing."""

    from _p7_8_fixtures import common_marker, golden_mezz  # type: ignore[import-not-found]

    terms, results = round_unit()
    corpus = (
        structure(),
        structure(golden_mezz()),
        structure(golden_mezz(), common_marker()),
        structure(_fixed_position(EXPECTED_FUNDING)),
    )
    for authored in corpus:
        omitted = execute_unit_capital_structure(
            unit_id=UNIT, terms=terms, results=results, capital_structure=authored
        )
        explicit = execute_unit_capital_structure(
            unit_id=UNIT, terms=terms, results=results, capital_structure=authored, valuations=None
        )
        assert omitted == explicit


def test_supplying_an_authority_changes_nothing_a_structure_does_not_consume() -> None:
    """The same corpus, with a fully resolved As-Is valuation supplied. None of
    these structures names it, so none of their numbers moves."""

    from _p7_8_fixtures import common_marker, golden_mezz  # type: ignore[import-not-found]

    terms, results = round_unit()
    authority = _authority(_as_is(), terms, results)
    for authored in (
        structure(),
        structure(golden_mezz()),
        structure(golden_mezz(), common_marker()),
        structure(_fixed_position(EXPECTED_FUNDING)),
    ):
        assert execute_unit_capital_structure(
            unit_id=UNIT, terms=terms, results=results, capital_structure=authored
        ) == execute_unit_capital_structure(
            unit_id=UNIT,
            terms=terms,
            results=results,
            capital_structure=authored,
            valuations=authority,
        )


# =============================================================================
# 8. The closing-only execution boundary (Stage 1 closeout)
# =============================================================================
#
# Stage 1 activated ``PctOfValue`` *closing* execution, not ``PctOfValue``
# generally. The valuation authority resolves As-Is, Stabilized and Custom
# timepoints alike; the existing executor funds at closing only, so a later
# timepoint is a reporting value no funding event can presently consume. That
# is a product limitation with a named reason -- never a zero, never a fallback
# to the purchase price, and never silently inferred into a later funding
# event. Supporting one needs an explicitly authorised refinancing or
# event-timing stage.


def test_a_later_valuation_resolves_but_cannot_fund_at_its_own_month() -> None:
    """The two halves of the boundary, in one place.

    A Stabilized timepoint at model month 24 resolves to a real value, so the
    valuation authority is not the limitation. Funding from it at month 24 is
    refused by the unchanged closing-only executor, and nothing is moved to
    closing to make it work."""

    terms, results = round_unit()
    authority = _authority_for_month(24)

    (valuation,) = authority.valuations
    assert valuation.model_month == 24
    assert valuation.status is ValuationAvailability.AVAILABLE
    # The round Unit's NOI is flat at $800,000, so Year 3 over the 8% cap rate
    # is the same $10,000,000 As-Is shows. The value exists; only the funding
    # is unavailable.
    assert valuation.value == pytest.approx(AS_IS_VALUE)

    with pytest.raises(CapitalStructureExecutionError) as raised:
        _execute(_valued_position(month=24, timepoint_id="stabilized"), authority, terms, results)
    assert ExecutionIssueCode.UNSUPPORTED_FUNDING_TIMING in {issue.code for issue in raised.value.issues}


def test_a_later_valuation_is_never_pulled_back_to_closing_to_fund() -> None:
    """The other direction: a closing funding event does not reach back to a
    later valuation. It is left unresolved by model month, sized neither from
    the later value nor from the purchase price."""

    resolution = resolve_pct_of_value_funding(
        event_id="mezz-funding",
        position_id="mezz",
        event_model_month=0,
        timepoint_id="stabilized",
        pct=PCT,
        scope_kind=ValuationScopeKind.UNIT,
        unit_id=UNIT,
        authority=_authority_for_month(24),
    )
    assert isinstance(resolution, UnresolvedFundingRequirement)
    assert resolution.reason is UnresolvedFundingReason.MODEL_MONTH_MISMATCH
    assert resolution.valuation_reason is None


def test_the_exit_month_is_never_a_fundable_valuation_timepoint() -> None:
    """Month ``12 * hold_period`` stays reserved for the system Exit view at
    the funding boundary too: a definition authored there has no value, so it
    sizes nothing."""

    terms, _ = round_unit()
    exit_month = terms.hold_period * 12
    assert exit_month == 60
    resolution = resolve_pct_of_value_funding(
        event_id="mezz-funding",
        position_id="mezz",
        event_model_month=exit_month,
        timepoint_id="stabilized",
        pct=PCT,
        scope_kind=ValuationScopeKind.UNIT,
        unit_id=UNIT,
        authority=_authority_for_month(exit_month),
    )
    assert isinstance(resolution, UnresolvedFundingRequirement)
    assert resolution.reason is UnresolvedFundingReason.VALUATION_UNAVAILABLE
    assert resolution.valuation_reason is ValuationUnavailableReason.RESERVED_EXIT_MONTH


_UNRESOLVED_REASONS = tuple(reason.value for reason in UnresolvedFundingReason)


def _unresolved_case(reason: str) -> UnresolvedFundingRequirement:
    """One unresolved resolution per reason the contract states."""

    terms, results = round_unit()
    common: dict[str, object] = {
        "event_id": "mezz-funding",
        "position_id": "mezz",
        "pct": PCT,
        "scope_kind": ValuationScopeKind.UNIT,
        "unit_id": UNIT,
    }
    if reason == "timepoint_not_found":
        case = resolve_pct_of_value_funding(
            **common, event_model_month=0, timepoint_id="never-authored",
            authority=_authority(_as_is(), terms, results),
        )
    elif reason == "foreign_investment":
        case = resolve_pct_of_value_funding(
            **common, event_model_month=0, timepoint_id="as-is",
            authority=dataclasses.replace(
                _authority(_as_is(investment_id="other-investment"), terms, results),
                investment_id=INVESTMENT_ID,
            ),
        )
    elif reason == "model_month_mismatch":
        case = resolve_pct_of_value_funding(
            **common, event_model_month=0, timepoint_id="stabilized",
            authority=_authority_for_month(24),
        )
    elif reason == "scope_not_covered":
        case = resolve_pct_of_value_funding(
            **{**common, "unit_id": "a-different-unit"}, event_model_month=0, timepoint_id="as-is",
            authority=_authority(_as_is(), terms, results),
        )
    elif reason == "valuation_unavailable":
        flat_terms, flat_results = round_unit(current_noi=0.0)
        case = resolve_pct_of_value_funding(
            **common, event_model_month=0, timepoint_id="as-is",
            authority=_authority(_as_is(), flat_terms, flat_results),
        )
    else:  # pragma: no cover -- the parametrisation is the enumeration
        raise AssertionError(f"no case built for {reason!r}")
    assert isinstance(case, UnresolvedFundingRequirement), reason
    assert case.reason.value == reason, reason
    return case


def test_every_unresolved_reason_is_reachable_and_distinct() -> None:
    """Each reason the contract names is reachable, and no two collapse."""

    reached = {_unresolved_case(reason).reason for reason in _UNRESOLVED_REASONS}
    assert reached == set(UnresolvedFundingReason)


@pytest.mark.parametrize("reason", _UNRESOLVED_REASONS)
def test_no_unresolved_case_carries_an_amount_a_value_or_a_price_fallback(reason: str) -> None:
    """The invariant that matters most, across every unresolved reason: the
    record states no dollars at all. There is no amount to read as zero, no
    scope value to mistake for one, and nothing equal to the purchase price or
    a percentage of it."""

    case = _unresolved_case(reason)
    names = {field.name for field in dataclasses.fields(case)}
    assert "amount" not in names
    assert "scope_value" not in names
    money = {
        getattr(case, name) for name in names if isinstance(getattr(case, name), float)
    }
    # ``pct`` is the only float it carries, and it is a share, not dollars.
    assert money == {PCT}
    assert 0.0 not in money
    assert AS_IS_VALUE not in money
    assert EXPECTED_FUNDING not in money


@pytest.mark.parametrize("reason", _UNRESOLVED_REASONS)
def test_no_unresolved_case_can_be_mistaken_for_the_p7_7_funding_requirement(reason: str) -> None:
    """P7.7's ``FundingRequirement`` reports a contractual claim the eligible
    cash could not meet, and states both the claim and the cash. This record
    reports an advance whose dollars are unknown, so it is a different type and
    shares none of those money-bearing fields. Neither can be read as the
    other."""

    from anchor.capital_structure.contracts import FundingRequirement

    case = _unresolved_case(reason)
    assert not isinstance(case, FundingRequirement)
    money_fields = {
        "claim_amount",
        "cash_available",
        "claim_paid_from_cash",
        "amount",
        "equity_contribution",
        "unpaid_claim_amount",
    }
    assert money_fields <= {field.name for field in dataclasses.fields(FundingRequirement)}
    assert money_fields & {field.name for field in dataclasses.fields(case)} == set()
