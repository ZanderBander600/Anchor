"""Phase 7 Gate P7.7 -- the Capital Position core: contracts, structural
validation, model-month timing, scope, priority, structural subordination and
the fail-closed executor.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3 (P-7,
P-14, P-15), 12.2, 12.3 and 15.5, and
``docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md``.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from collections.abc import Callable
from typing import Any

import pytest

from _p7_7_fixtures import (  # type: ignore[import-not-found]
    INVESTMENT,
    LOAN_UNITS,
    MEMBERS,
    analyze_unit,
    debt_terms,
    fee,
    funding,
    position,
    preferred_terms,
    structure,
    unit_scope,
    valid_positions,
)
from anchor.business_plan import BusinessPlan, CapitalItemCategory, CapitalPlanItem, resolve_business_plan
from anchor.capital_structure import (
    LEGACY_ACQUISITION_LOAN_ID_PREFIX,
    AccrualConvention,
    CapitalPosition,
    CapitalStructure,
    CapitalStructureIssueCode,
    CapitalStructureValidationError,
    ContractualClaim,
    FixedAmount,
    FundingEvent,
    HoldYearPeriod,
    ModelMonthPeriod,
    PctOfPrice,
    PctOfValue,
    PositionClass,
    PositionScope,
    PreferredEquityTerms,
    ScopeKind,
    ShortfallResolution,
    TimingBasis,
    UnsupportedCapitalPositionError,
    analyze_unit_capital_structure,
    annual_period_of_model_month,
    economic_order,
    validate_capital_structure,
)
from anchor.capital_structure import contracts as contracts_module

Code = CapitalStructureIssueCode


def _validate(capital_structure: object, **kwargs: Any) -> tuple[Any, ...]:
    kwargs.setdefault("member_unit_ids", MEMBERS)
    kwargs.setdefault("acquisition_loan_unit_ids", LOAN_UNITS)
    return validate_capital_structure(capital_structure, **kwargs)


def _replacing(target: str, **changes: Any) -> CapitalStructure:
    return structure(
        *(dataclasses.replace(p, **changes) if p.position_id == target else p for p in valid_positions())
    )


def _codes(issues: tuple[Any, ...]) -> list[tuple[Any, Any, Any]]:
    return [(issue.code, issue.position_id, issue.field) for issue in issues]


# =============================================================================
# 1. The contracts
# =============================================================================


def test_the_enumerations_have_exactly_the_ratified_members_and_wire_values() -> None:
    assert {m.name: m.value for m in PositionClass} == {
        "SENIOR_DEBT": "senior_debt",
        "MEZZANINE_DEBT": "mezzanine_debt",
        "PREFERRED_EQUITY": "preferred_equity",
        "COMMON_EQUITY": "common_equity",
    }
    assert {m.name: m.value for m in ScopeKind} == {"UNIT": "unit", "INVESTMENT": "investment"}
    assert {m.name: m.value for m in ShortfallResolution} == {
        "COMMON_EQUITY_CONTRIBUTION": "common_equity_contribution",
        "UNRESOLVED": "unresolved",
    }
    assert {m.name: m.value for m in AccrualConvention} == {"SIMPLE": "simple", "ANNUAL_COMPOUND": "annual_compound"}
    assert {m.name: m.value for m in TimingBasis} == {"MODEL_MONTH": "model_month", "HOLD_YEAR": "hold_year"}


def test_no_other_cure_mechanism_ships() -> None:
    for later in ("reserve_draw", "protective_advance", "pik", "cash_trap", "default"):
        assert later not in {m.value for m in ShortfallResolution}


def _dataclasses() -> list[type[Any]]:
    return [
        value
        for value in vars(contracts_module).values()
        if isinstance(value, type) and dataclasses.is_dataclass(value) and value.__module__ == contracts_module.__name__
    ]


def test_every_contract_is_frozen_slotted_and_keyword_only() -> None:
    classes = _dataclasses()
    assert len(classes) >= 20
    for cls in classes:
        params = cls.__dataclass_params__  # type: ignore[attr-defined]
        assert params.frozen, cls
        assert "__slots__" in vars(cls), cls
        assert all(f.kw_only for f in dataclasses.fields(cls)), cls


def test_no_shortfall_resolution_and_no_accrual_convention_has_a_default() -> None:
    """P-14 / FR-3: a resolution is always stated, never assumed; FR-4: an
    accrual convention too."""

    checked = 0
    for cls in _dataclasses():
        for field in dataclasses.fields(cls):
            if "resolution" in field.name or "convention" in field.name:
                checked += 1
                assert field.default is dataclasses.MISSING, (cls, field.name)
                assert field.default_factory is dataclasses.MISSING, (cls, field.name)
    assert checked >= 5


def test_a_position_or_claim_without_a_resolution_cannot_be_constructed() -> None:
    fields = {f.name: f for f in dataclasses.fields(CapitalPosition)}
    arguments = {name: None for name in fields if name != "shortfall_resolution"}
    with pytest.raises(TypeError, match="shortfall_resolution"):
        CapitalPosition(**arguments)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="shortfall_resolution"):
        ContractualClaim(  # type: ignore[call-arg]
            position_id="p", scope=INVESTMENT, period=HoldYearPeriod(hold_year=1), claim_due=1.0, cash_available=0.0
        )


def test_a_synthetic_position_with_no_resolution_is_invalid() -> None:
    for position_class in (PositionClass.SENIOR_DEBT, PositionClass.MEZZANINE_DEBT, PositionClass.PREFERRED_EQUITY):
        issues = _validate(structure(position("p", position_class=position_class, shortfall_resolution=None)))
        assert _codes(issues) == [(Code.MISSING_SHORTFALL_RESOLUTION, "p", "shortfall_resolution")]


def test_contracts_are_immutable() -> None:
    capital_structure = structure(*valid_positions())
    with pytest.raises(dataclasses.FrozenInstanceError):
        capital_structure.positions = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        capital_structure.positions[0].priority = 9  # type: ignore[misc]


def test_the_two_period_kinds_are_distinguishable() -> None:
    assert ModelMonthPeriod(model_month=18).basis is TimingBasis.MODEL_MONTH
    assert HoldYearPeriod(hold_year=2).basis is TimingBasis.HOLD_YEAR
    assert ModelMonthPeriod(model_month=2) != HoldYearPeriod(hold_year=2)
    assert "basis" not in {f.name for f in dataclasses.fields(ModelMonthPeriod)}


# =============================================================================
# 2. Structural validation
# =============================================================================


def test_a_structure_of_every_class_scope_and_term_is_valid() -> None:
    assert _validate(structure(*valid_positions())) == ()
    assert _validate(structure()) == ()


_Case = Callable[[], CapitalStructure]

_INVALID: dict[str, tuple[_Case, list[tuple[Any, Any, Any]]]] = {
    "bool priority": (lambda: _replacing("mezz-u1", priority=True), [(Code.INVALID_PRIORITY, "mezz-u1", "priority")]),
    "zero priority": (lambda: _replacing("mezz-u1", priority=0), [(Code.INVALID_PRIORITY, "mezz-u1", "priority")]),
    "float priority": (lambda: _replacing("mezz-u1", priority=2.0), [(Code.INVALID_PRIORITY, "mezz-u1", "priority")]),
    "blank position id": (lambda: _replacing("mezz-u1", position_id="  "), [(Code.INVALID_POSITION_ID, None, "position_id")]),
    "reserved position id": (
        lambda: _replacing("mezz-u1", position_id=f"{LEGACY_ACQUISITION_LOAN_ID_PREFIX}u1"),
        [(Code.RESERVED_IDENTITY, f"{LEGACY_ACQUISITION_LOAN_ID_PREFIX}u1", "position_id")],
    ),
    "blank name": (lambda: _replacing("mezz-u1", name=""), [(Code.INVALID_NAME, "mezz-u1", "name")]),
    "untyped class": (
        lambda: _replacing("mezz-u1", position_class="mezzanine_debt"),
        [(Code.UNKNOWN_POSITION_CLASS, "mezz-u1", "position_class")],
    ),
    "blank unit scope": (lambda: _replacing("mezz-u1", scope=unit_scope(" ")), [(Code.INVALID_SCOPE, "mezz-u1", "scope.unit_id")]),
    "investment scope with a unit": (
        lambda: _replacing("pref-inv", scope=PositionScope(kind=ScopeKind.INVESTMENT, unit_id="u1")),
        [(Code.INVALID_SCOPE, "pref-inv", "scope.unit_id")],
    ),
    "untyped scope kind": (
        lambda: _replacing("mezz-u1", scope=PositionScope(kind="unit", unit_id="u1")),  # type: ignore[arg-type]
        [(Code.INVALID_SCOPE, "mezz-u1", "scope")],
    ),
    "foreign unit": (lambda: _replacing("mezz-u1", scope=unit_scope("u9")), [(Code.FOREIGN_UNIT_SCOPE, "mezz-u1", "scope.unit_id")]),
    "mezzanine with preferred terms": (
        lambda: _replacing("mezz-u1", terms=preferred_terms()),
        [(Code.CLASS_TERMS_MISMATCH, "mezz-u1", "terms")],
    ),
    "preferred with debt terms": (lambda: _replacing("pref-inv", terms=debt_terms()), [(Code.CLASS_TERMS_MISMATCH, "pref-inv", "terms")]),
    "common equity with terms": (lambda: _replacing("common-inv", terms=debt_terms()), [(Code.CLASS_TERMS_MISMATCH, "common-inv", "terms")]),
    "senior debt without terms": (lambda: _replacing("senior-u2", terms=None), [(Code.CLASS_TERMS_MISMATCH, "senior-u2", "terms")]),
    "debt without funding": (lambda: _replacing("mezz-u1", funding=()), [(Code.INVALID_FUNDING, "mezz-u1", "funding")]),
    "common equity with funding": (
        lambda: _replacing("common-inv", funding=(funding("common-funding"),)),
        [(Code.INVALID_FUNDING, "common-inv", "funding")],
    ),
    "funding as a list": (lambda: _replacing("mezz-u1", funding=[funding("f")]), [(Code.INVALID_FUNDING, "mezz-u1", "funding")]),
    "not a funding event": (lambda: _replacing("mezz-u1", funding=("f",)), [(Code.INVALID_FUNDING_EVENT, "mezz-u1", "funding")]),
    "bool funding month": (
        lambda: _replacing("mezz-u1", funding=(funding("f", month=True),)),
        [(Code.INVALID_FUNDING_EVENT, "mezz-u1", "funding[f].model_month")],
    ),
    "negative funding month": (
        lambda: _replacing("mezz-u1", funding=(funding("f", month=-1),)),
        [(Code.INVALID_FUNDING_EVENT, "mezz-u1", "funding[f].model_month")],
    ),
    "zero sequence": (
        lambda: _replacing("mezz-u1", funding=(funding("f", sequence=0),)),
        [(Code.INVALID_FUNDING_EVENT, "mezz-u1", "funding[f].sequence")],
    ),
    "blank event id": (
        lambda: _replacing("mezz-u1", funding=(funding(""),)),
        [(Code.INVALID_FUNDING_EVENT, "mezz-u1", "funding[].event_id")],
    ),
    "reserved event id": (
        lambda: _replacing("mezz-u1", funding=(funding(f"{LEGACY_ACQUISITION_LOAN_ID_PREFIX}x"),)),
        [(Code.RESERVED_IDENTITY, "mezz-u1", f"funding[{LEGACY_ACQUISITION_LOAN_ID_PREFIX}x].event_id")],
    ),
    "zero fixed amount": (
        lambda: _replacing("mezz-u1", funding=(funding("f", rule=FixedAmount(amount=0.0)),)),
        [(Code.INVALID_AMOUNT_RULE, "mezz-u1", "funding[f].amount_rule.amount")],
    ),
    "non-finite fixed amount": (
        lambda: _replacing("mezz-u1", funding=(funding("f", rule=FixedAmount(amount=math.nan)),)),
        [(Code.INVALID_AMOUNT_RULE, "mezz-u1", "funding[f].amount_rule.amount")],
    ),
    "zero pct of price": (
        lambda: _replacing("mezz-u1", funding=(funding("f", rule=PctOfPrice(pct=0.0)),)),
        [(Code.INVALID_AMOUNT_RULE, "mezz-u1", "funding[f].amount_rule.pct")],
    ),
    "pct of price above one": (
        lambda: _replacing("mezz-u1", funding=(funding("f", rule=PctOfPrice(pct=1.5)),)),
        [(Code.INVALID_AMOUNT_RULE, "mezz-u1", "funding[f].amount_rule.pct")],
    ),
    "bool pct of price": (
        lambda: _replacing("mezz-u1", funding=(funding("f", rule=PctOfPrice(pct=True)),)),  # type: ignore[arg-type]
        [(Code.INVALID_AMOUNT_RULE, "mezz-u1", "funding[f].amount_rule.pct")],
    ),
    "blank valuation timepoint": (
        lambda: _replacing("mezz-u1", funding=(funding("f", rule=PctOfValue(timepoint_id=" ", pct=0.5)),)),
        [(Code.INVALID_AMOUNT_RULE, "mezz-u1", "funding[f].amount_rule.timepoint_id")],
    ),
    "untyped amount rule": (
        lambda: _replacing("mezz-u1", funding=(funding("f", rule=1_000_000.0),)),
        [(Code.INVALID_AMOUNT_RULE, "mezz-u1", "funding[f].amount_rule")],
    ),
    "negative interest rate": (
        lambda: _replacing("mezz-u1", terms=debt_terms(interest_rate=-0.01)),
        [(Code.INVALID_DEBT_TERMS, "mezz-u1", "terms.interest_rate")],
    ),
    "non-finite pik rate": (
        lambda: _replacing("mezz-u1", terms=debt_terms(pik_rate=math.inf)),
        [(Code.INVALID_DEBT_TERMS, "mezz-u1", "terms.pik_rate")],
    ),
    "bool current pay rate": (
        lambda: _replacing("mezz-u1", terms=debt_terms(current_pay_rate=False)),
        [(Code.INVALID_DEBT_TERMS, "mezz-u1", "terms.current_pay_rate")],
    ),
    "zero amortization": (
        lambda: _replacing("mezz-u1", terms=debt_terms(amortization=0)),
        [(Code.INVALID_DEBT_TERMS, "mezz-u1", "terms.amortization")],
    ),
    "bool io period": (
        lambda: _replacing("mezz-u1", terms=debt_terms(io_period=True)),
        [(Code.INVALID_DEBT_TERMS, "mezz-u1", "terms.io_period")],
    ),
    "zero maturity": (
        lambda: _replacing("mezz-u1", terms=debt_terms(maturity_month=0)),
        [(Code.INVALID_DEBT_TERMS, "mezz-u1", "terms.maturity_month")],
    ),
    "fees as a list": (
        lambda: _replacing("mezz-u1", terms=debt_terms(fees=[fee("x")])),
        [(Code.INVALID_DEBT_TERMS, "mezz-u1", "terms.fees")],
    ),
    "negative fee": (
        lambda: _replacing("mezz-u1", terms=debt_terms(fees=(fee("x", amount=-1.0),))),
        [(Code.INVALID_FEE, "mezz-u1", "terms.fees[x].amount")],
    ),
    "blank fee description": (
        lambda: _replacing("mezz-u1", terms=debt_terms(fees=(fee("x", description=""),))),
        [(Code.INVALID_FEE, "mezz-u1", "terms.fees[x].description")],
    ),
    "bool fee month": (
        lambda: _replacing("mezz-u1", terms=debt_terms(fees=(fee("x", month=True),))),
        [(Code.INVALID_FEE, "mezz-u1", "terms.fees[x].model_month")],
    ),
    "blank fee id": (
        lambda: _replacing("mezz-u1", terms=debt_terms(fees=(fee(""),))),
        [(Code.INVALID_FEE, "mezz-u1", "terms.fees[].fee_id")],
    ),
    "accrual without a convention": (
        lambda: _replacing("pref-inv", terms=preferred_terms(accrual_convention=None)),
        [(Code.INVALID_PREFERRED_EQUITY_TERMS, "pref-inv", "terms.accrual_convention")],
    ),
    "a convention without accrual": (
        lambda: _replacing("pref-inv", terms=preferred_terms(accrual_permitted=False)),
        [(Code.INVALID_PREFERRED_EQUITY_TERMS, "pref-inv", "terms.accrual_convention")],
    ),
    "accrual permission not a bool": (
        lambda: _replacing("pref-inv", terms=preferred_terms(accrual_permitted=1)),
        [(Code.INVALID_PREFERRED_EQUITY_TERMS, "pref-inv", "terms.accrual_permitted")],
    ),
    "zero redemption month": (
        lambda: _replacing("pref-inv", terms=preferred_terms(redemption_month=0)),
        [(Code.INVALID_PREFERRED_EQUITY_TERMS, "pref-inv", "terms.redemption_month")],
    ),
    "negative preferred rate": (
        lambda: _replacing("pref-inv", terms=preferred_terms(preferred_rate=-0.12)),
        [(Code.INVALID_PREFERRED_EQUITY_TERMS, "pref-inv", "terms.preferred_rate")],
    ),
    "missing resolution": (lambda: _replacing("mezz-u1", shortfall_resolution=None), [(Code.MISSING_SHORTFALL_RESOLUTION, "mezz-u1", "shortfall_resolution")]),
    "untyped resolution": (
        lambda: _replacing("mezz-u1", shortfall_resolution="unresolved"),
        [(Code.INVALID_SHORTFALL_RESOLUTION, "mezz-u1", "shortfall_resolution")],
    ),
    "common equity with a resolution": (
        lambda: _replacing("common-inv", shortfall_resolution=ShortfallResolution.COMMON_EQUITY_CONTRIBUTION),
        [(Code.INVALID_SHORTFALL_RESOLUTION, "common-inv", "shortfall_resolution")],
    ),
    "duplicate event order": (
        lambda: _replacing("mezz-u1", terms=debt_terms(fees=(fee("x", sequence=1),))),
        [(Code.DUPLICATE_EVENT_ORDER, "mezz-u1", "funding")],
    ),
}


@pytest.mark.parametrize("case", sorted(_INVALID))
def test_each_structural_rule_reports_exactly_its_issue(case: str) -> None:
    build, expected = _INVALID[case]
    assert _codes(_validate(build())) == expected


def test_cross_position_duplicates_are_refused() -> None:
    duplicate_id = structure(position("p", funding_events=(funding("a"),)), position("p", priority=3, funding_events=(funding("b"),)))
    assert _codes(_validate(duplicate_id)) == [(Code.DUPLICATE_POSITION_ID, "p", "position_id")]

    duplicate_priority = structure(position("p", priority=2), position("q", priority=2))
    (issue,) = _validate(duplicate_priority)
    assert issue.code is Code.DUPLICATE_PRIORITY and "'p', 'q'" in issue.message

    duplicate_event = structure(position("p", funding_events=(funding("e"),)), position("q", priority=3, funding_events=(funding("e"),)))
    assert _codes(_validate(duplicate_event)) == [(Code.DUPLICATE_EVENT_ID, None, None)]

    fee_colliding_with_event = structure(
        position("p", funding_events=(funding("e"),)), position("q", priority=3, terms=debt_terms(fees=(fee("e"),)))
    )
    assert _codes(_validate(fee_colliding_with_event)) == [(Code.DUPLICATE_EVENT_ID, None, None)]


def test_not_a_structure_and_a_mutable_position_list_are_refused() -> None:
    assert _codes(_validate(valid_positions())) == [(Code.INVALID_STRUCTURE, None, None)]
    assert _codes(_validate(CapitalStructure(positions=list(valid_positions())))) == [  # type: ignore[arg-type]
        (Code.INVALID_STRUCTURE, None, "positions")
    ]
    assert _codes(_validate(structure("not a position"))) == [(Code.INVALID_POSITION, None, None)]


def test_issue_order_never_depends_on_how_the_positions_were_listed() -> None:
    broken = (
        position("b", priority=True),
        position("a", scope=unit_scope("u9"), shortfall_resolution=None),
        position("c", position_class=PositionClass.PREFERRED_EQUITY, scope=INVESTMENT, terms=debt_terms()),
        position("d", priority=2, funding_events=(funding("e", month=-1), funding("d-funding"))),
        "garbage",
    )
    reference = _validate(structure(*broken))
    assert len(reference) >= 6
    for permutation in itertools.permutations(broken):
        assert _validate(structure(*permutation)) == reference


# =============================================================================
# 3. Model month, scope, priority and structural subordination
# =============================================================================


@pytest.mark.parametrize(
    ("month", "period"),
    [(0, 0), (1, 1), (12, 1), (13, 2), (24, 2), (25, 3), (59, 5), (60, 5), (61, 6), (84, 7)],
)
def test_the_model_month_convention_is_d6_exactly(month: int, period: int) -> None:
    assert annual_period_of_model_month(month) == period


def test_the_model_month_convention_is_the_business_plan_resolvers() -> None:
    """An independent oracle: the D6 resolver buckets a capital item at month
    ``m`` into the same hold year (and month 0 into closing)."""

    for month in (0, 1, 11, 12, 13, 24, 25, 37, 48, 59, 60):
        plan = BusinessPlan(
            capital_items=(
                CapitalPlanItem(item_id="i", description="Item", category=CapitalItemCategory.OTHER, month=month, amount=1.0),
            )
        )
        schedule = resolve_business_plan(plan, hold_period=5)
        period = annual_period_of_model_month(month)
        if period == 0:
            assert schedule.closing_project_capital == 1.0
        else:
            assert [index + 1 for index, amount in enumerate(schedule.project_capital_by_year) if amount] == [period]


@pytest.mark.parametrize(("value", "error"), [(True, TypeError), (1.0, TypeError), ("1", TypeError), (-1, ValueError)])
def test_the_model_month_convention_refuses_non_months(value: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        annual_period_of_model_month(value)


def test_contracts_carry_any_model_month_not_an_annual_period() -> None:
    monthly = structure(
        position(
            "p",
            funding_events=(funding("draw-1", month=7), funding("draw-2", month=19), funding("draw-3", month=19, sequence=2)),
            terms=debt_terms(maturity_month=43, fees=(fee("exit-fee", month=43, sequence=1),)),
        )
    )
    assert _validate(monthly) == ()


def test_the_economic_order_is_scope_then_priority_never_list_order() -> None:
    listed = (
        position("inv-1", priority=1, scope=INVESTMENT),
        position("u2-5", priority=5, scope=unit_scope("u2")),
        position("u1-3", priority=3, scope=unit_scope("u1")),
        position("u1-2", priority=2, scope=unit_scope("u1")),
        position("inv-2", priority=2, scope=INVESTMENT),
    )
    expected = ["u1-2", "u1-3", "u2-5", "inv-1", "inv-2"]
    for permutation in itertools.permutations(listed):
        assert [p.position_id for p in economic_order(permutation)] == expected


def test_priority_is_unique_within_a_scope_and_independent_across_scopes() -> None:
    per_unit = structure(
        position("u1-2", priority=2, scope=unit_scope("u1")),
        position("u2-2", priority=2, scope=unit_scope("u2")),
        position("inv-2", priority=2, scope=INVESTMENT),
    )
    assert _validate(per_unit) == ()
    same_unit = structure(position("a", priority=3, scope=unit_scope("u2")), position("b", priority=3, scope=unit_scope("u2")))
    assert [issue.code for issue in _validate(same_unit)] == [Code.DUPLICATE_PRIORITY]


def test_priority_one_of_a_unit_with_an_acquisition_loan_is_the_loans() -> None:
    at_one = structure(position("mezz", priority=1, scope=unit_scope("u1")))
    (issue,) = _validate(at_one)
    assert issue.code is Code.DUPLICATE_PRIORITY and f"{LEGACY_ACQUISITION_LOAN_ID_PREFIX}u1" in issue.message
    assert _validate(at_one, acquisition_loan_unit_ids=()) == ()
    assert _validate(structure(position("s", priority=1, scope=unit_scope("u2")))) == ()


def test_cs5_investment_senior_debt_is_refused_while_any_unit_has_an_acquisition_loan() -> None:
    senior = structure(position("inv-senior", position_class=PositionClass.SENIOR_DEBT, priority=1, scope=INVESTMENT))
    (issue,) = _validate(senior)
    assert (issue.code, issue.position_id) == (Code.INVESTMENT_SENIOR_DEBT_WITH_ACQUISITION_LOAN, "inv-senior")
    assert "u1" in issue.message and "cross-collateralization is never inferred" in issue.message
    assert _validate(senior, acquisition_loan_unit_ids=()) == ()
    junior = structure(position("inv-mezz", priority=1, scope=INVESTMENT))
    assert _validate(junior) == ()


def test_the_loan_units_are_never_assumed_empty() -> None:
    with pytest.raises(TypeError, match="acquisition_loan_unit_ids"):
        validate_capital_structure(structure())  # type: ignore[call-arg]


# =============================================================================
# 4. The executor fails closed for every authored position
# =============================================================================


@pytest.mark.parametrize("position_class", list(PositionClass))
def test_every_authored_position_class_is_refused_never_ignored(position_class: PositionClass) -> None:
    terms, results = analyze_unit("quick")
    authored = structure(position("authored", position_class=position_class, priority=2, scope=unit_scope("u1")))
    with pytest.raises(UnsupportedCapitalPositionError) as refused:
        analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=authored)
    ((code, position_id),) = [(issue.code, issue.position_id) for issue in refused.value.issues]
    assert (code, position_id) == (Code.UNSUPPORTED_POSITION, "authored")
    assert "Nothing was analysed" in str(refused.value)


def test_refusals_list_every_position_in_economic_order() -> None:
    terms, results = analyze_unit("quick")
    authored = structure(
        position("inv-pref", position_class=PositionClass.PREFERRED_EQUITY, priority=1, scope=INVESTMENT),
        position("u1-mezz", priority=2, scope=unit_scope("u1")),
    )
    with pytest.raises(UnsupportedCapitalPositionError) as refused:
        analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=authored)
    assert [issue.position_id for issue in refused.value.issues] == ["u1-mezz", "inv-pref"]


def test_an_invalid_structure_is_refused_as_invalid_first() -> None:
    terms, results = analyze_unit("quick")
    for invalid, code in (
        (structure(position("m", priority=1, scope=unit_scope("u1"))), Code.DUPLICATE_PRIORITY),
        (structure(position("m", scope=unit_scope("elsewhere"))), Code.FOREIGN_UNIT_SCOPE),
        (structure(position("s", position_class=PositionClass.SENIOR_DEBT, priority=1, scope=INVESTMENT)), Code.INVESTMENT_SENIOR_DEBT_WITH_ACQUISITION_LOAN),
    ):
        with pytest.raises(CapitalStructureValidationError) as refused:
            analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=invalid)
        assert [issue.code for issue in refused.value.issues] == [code]


def test_a_valuation_rule_is_representable_but_never_valued() -> None:
    terms, results = analyze_unit("quick", ltv=0.0)
    valued = structure(
        position(
            "inv-senior",
            position_class=PositionClass.SENIOR_DEBT,
            priority=1,
            scope=INVESTMENT,
            funding_events=(funding("f", rule=PctOfValue(timepoint_id="stabilized", pct=0.6)),),
        )
    )
    assert validate_capital_structure(valued, member_unit_ids={"u1"}, acquisition_loan_unit_ids=()) == ()
    with pytest.raises(UnsupportedCapitalPositionError):
        analyze_unit_capital_structure(unit_id="u1", terms=terms, results=results, capital_structure=valued)


def test_preferred_terms_carry_no_inferred_accrual() -> None:
    no_accrual = preferred_terms(accrual_permitted=False, accrual_convention=None)
    assert isinstance(no_accrual, PreferredEquityTerms)
    assert _validate(structure(position("p", position_class=PositionClass.PREFERRED_EQUITY, scope=INVESTMENT, priority=1, terms=no_accrual))) == ()
    assert FundingEvent.__doc__ and "never inferred from list position" in FundingEvent.__doc__
