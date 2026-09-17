"""Phase 7 Gate P7.9 Stage 1 -- contracts and structural validation.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 3, 4, 5 and 12:
frozen, slotted, keyword-only shapes; no default on any economic field; one
authority for the catch-up rate and Common Equity Total Profit; and every
Section 5.1 / 5.2 code reached by a test, in a deterministic order.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from _p7_9_fixtures import (  # type: ignore[import-not-found]
    ALL_EQUITY,
    BENCH_90_10,
    COMPOUND,
    F1_SERIES,
    LP_GP,
    PRO_RATA,
    benchmark,
    catch_up,
    compound,
    f1_terms,
    hurdle,
    moic,
    of_class,
    of_partner,
    partner,
    partnership,
    residual,
    run,
    simple,
    split,
    to_partner,
    ACCRUED_FIRST,
)
from anchor.capital_structure.contracts import AccrualConvention
from anchor.partnership import contracts
from anchor.partnership import (
    BenchmarkShare,
    CatchUpTerms,
    CommonEquityCashFlowInput,
    ContributionRule,
    EconomicAccount,
    HurdleCombinator,
    HurdleSubject,
    HurdleSubjectKind,
    IrrHurdle,
    Partnership,
    PartnershipExecutionError,
    PartnershipExecutionIssue,
    PartnershipExecutionIssueCode,
    PartnershipIssue,
    PartnershipIssueCode,
    PartnershipValidationError,
    PromoteBenchmark,
    SimpleDistributionOrder,
    SplitShare,
    TierKind,
    WaterfallTier,
    allocate_partnership,
    require_valid_partnership,
    validate_partnership,
)

Code = PartnershipIssueCode

#: The authored and input contracts: every field is economic or identifying,
#: and none may default.
AUTHORED = (
    contracts.CommonEquityCashFlowInput,
    contracts.Partner,
    contracts.BenchmarkShare,
    contracts.PromoteBenchmark,
    contracts.SplitShare,
    contracts.ExplicitSplit,
    contracts.HurdleSubject,
    contracts.IrrHurdle,
    contracts.MoicHurdle,
    contracts.HurdleTerms,
    contracts.CatchUpRecipient,
    contracts.CatchUpTerms,
    contracts.WaterfallTier,
    contracts.Partnership,
)


def codes(terms: object) -> list[PartnershipIssueCode]:
    return [issue.code for issue in validate_partnership(terms)]


def replace_tier(terms: Partnership, index: int, **changes: Any) -> Partnership:
    tiers = list(terms.tiers)
    tiers[index] = dataclasses.replace(tiers[index], **changes)
    return dataclasses.replace(terms, tiers=tuple(tiers))


def replace_hurdle(terms: Partnership, index: int, **changes: Any) -> Partnership:
    tier = terms.tiers[index]
    assert tier.hurdle is not None
    return replace_tier(terms, index, hurdle=dataclasses.replace(tier.hurdle, **changes))


# =============================================================================
# Shapes
# =============================================================================


def test_every_contract_is_a_frozen_slotted_keyword_only_dataclass() -> None:
    classes = [
        value for value in vars(contracts).values()
        if isinstance(value, type) and dataclasses.is_dataclass(value) and value.__module__ == contracts.__name__
    ]
    assert len(classes) == 29
    for cls in classes:
        params = cls.__dataclass_params__  # type: ignore[attr-defined]
        assert params.frozen, cls.__name__
        assert params.kw_only, cls.__name__
        assert "__slots__" in vars(cls), cls.__name__


@pytest.mark.parametrize("cls", AUTHORED, ids=lambda cls: cls.__name__)
def test_no_authored_field_has_a_default(cls: type) -> None:
    for field in dataclasses.fields(cls):
        assert field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING, (cls.__name__, field.name)


def test_promote_participants_cannot_be_omitted() -> None:
    with pytest.raises(TypeError):
        Partnership(  # type: ignore[call-arg]
            partners=LP_GP, contribution_rule=ContributionRule.PRO_RATA_BY_COMMITMENT, promote_benchmark=BENCH_90_10, tiers=()
        )


def test_one_authority_for_the_catch_up_rate_and_the_common_equity_profit() -> None:
    assert {field.name for field in dataclasses.fields(CatchUpTerms)} == {"recipient", "target_profit_share"}
    assert {field.name for field in dataclasses.fields(CommonEquityCashFlowInput)} == {"cadence", "cash_flows"}
    assert "catch_up_rate" in {field.name for field in dataclasses.fields(contracts.TierResult)}


def test_ratified_result_names() -> None:
    names = {field.name for field in dataclasses.fields(contracts.PartnerResult)}
    assert {"benchmark_capital_subordination", "promote_attribution_by_tier", "promote_earned"} <= names
    assert not {"subordination", "promote_earned_by_tier"} & names


def test_wire_values_are_lower_case() -> None:
    for enum in (
        contracts.CashFlowCadence, contracts.PartnerRole, contracts.ContributionRule, contracts.TierKind,
        contracts.HurdleSubjectKind, contracts.EconomicAccount, contracts.HurdleCombinator,
        contracts.SimpleDistributionOrder, contracts.CatchUpRecipientKind, contracts.SplitRule,
        contracts.PartnershipStatus, contracts.PartnershipUnavailableReason, contracts.PromoteUnavailableReason,
        contracts.MoicUnavailableReason, PartnershipIssueCode, PartnershipExecutionIssueCode,
    ):
        for member in enum:
            assert member.value == member.name.lower(), member


def test_the_supported_sets_are_exactly_the_ratified_v1_members() -> None:
    assert [member.value for member in contracts.CashFlowCadence] == ["annual"]
    assert [member.value for member in ContributionRule] == ["pro_rata_by_commitment"]
    assert [member.value for member in EconomicAccount] == ["all_common_equity"]
    assert [member.value for member in contracts.CatchUpRecipientKind] == ["partner", "investor_class"]
    assert contracts.AccrualConvention is AccrualConvention
    assert contracts.SHARE_SUM_TOLERANCE == 1e-9 and contracts.WATERFALL_AMOUNT_TOLERANCE == 1e-6


def test_errors_require_their_own_issues() -> None:
    with pytest.raises(ValueError):
        PartnershipValidationError(())
    with pytest.raises(TypeError):
        PartnershipValidationError(("x",))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        PartnershipExecutionError(())
    with pytest.raises(TypeError):
        PartnershipExecutionError(("x",))  # type: ignore[arg-type]
    issue = PartnershipIssue(code=Code.NO_TIERS, message="m")
    assert str(issue) == "m" and str(PartnershipValidationError((issue,))) == "m"
    execution = PartnershipExecutionIssue(code=PartnershipExecutionIssueCode.UNSUPPORTED_CADENCE, message="e")
    assert str(execution) == "e"


# =============================================================================
# Validation: valid contracts
# =============================================================================


def test_the_ratified_fixtures_are_valid() -> None:
    assert validate_partnership(f1_terms()) == ()
    assert require_valid_partnership(f1_terms()) == f1_terms()


def test_shares_within_the_tolerance_are_accepted() -> None:
    terms = dataclasses.replace(f1_terms(), promote_benchmark=benchmark(lp=0.9 + 5e-10, gp=0.1))
    assert codes(terms) == []


def test_three_way_shares_that_do_not_sum_exactly_in_binary_are_accepted() -> None:
    terms = partnership(
        (partner("a", 0.7), partner("b", 0.2), partner("c", 0.1)),
        (residual("residual", 10, split(a=0.7, b=0.2, c=0.1)),),
        bench=benchmark(a=0.7, b=0.2, c=0.1),
        participants=(),
    )
    assert 0.7 + 0.2 + 0.1 != 1.0
    assert codes(terms) == []


# =============================================================================
# Validation: every structural code
# =============================================================================


def test_not_a_partnership() -> None:
    assert codes("partnership") == [Code.INVALID_PARTNERSHIP]


def test_partner_issues() -> None:
    assert codes(dataclasses.replace(f1_terms(), partners=())) == [Code.NO_PARTNERS]
    assert codes(dataclasses.replace(f1_terms(), partners=list(LP_GP))) == [Code.INVALID_PARTNERSHIP]
    assert codes(dataclasses.replace(f1_terms(), partners=(*LP_GP, "x"))) == [Code.INVALID_PARTNER]
    assert codes(dataclasses.replace(f1_terms(), partners=(LP_GP[0], dataclasses.replace(LP_GP[1], partner_id=" ")))) == [Code.BLANK_PARTNER_ID]
    assert codes(dataclasses.replace(f1_terms(), partners=(LP_GP[0], dataclasses.replace(LP_GP[1], partner_id="lp")))) == [Code.DUPLICATE_PARTNER_ID]
    assert codes(dataclasses.replace(f1_terms(), partners=(LP_GP[0], dataclasses.replace(LP_GP[1], role="sponsor")))) == [Code.INVALID_ROLE]
    assert codes(dataclasses.replace(f1_terms(), partners=(LP_GP[0], dataclasses.replace(LP_GP[1], investor_class="")))) == [Code.INVALID_INVESTOR_CLASS]


@pytest.mark.parametrize("share", [-0.1, 1.1, float("nan"), float("inf"), True, "0.1", None])
def test_an_invalid_commitment_share(share: object) -> None:
    terms = dataclasses.replace(f1_terms(), partners=(LP_GP[0], dataclasses.replace(LP_GP[1], commitment_share=share)))
    assert codes(terms) == [Code.INVALID_SHARE]


def test_commitments_must_sum_to_one() -> None:
    terms = dataclasses.replace(f1_terms(), partners=(LP_GP[0], dataclasses.replace(LP_GP[1], commitment_share=0.1 + 2e-9)))
    assert codes(terms) == [Code.SHARES_DO_NOT_SUM_TO_ONE]


def test_a_contribution_rule_is_required() -> None:
    assert codes(dataclasses.replace(f1_terms(), contribution_rule=None)) == [Code.INVALID_CONTRIBUTION_RULE]


def test_benchmark_issues() -> None:
    assert codes(dataclasses.replace(f1_terms(), promote_benchmark=None)) == [Code.INVALID_BENCHMARK]
    assert codes(dataclasses.replace(f1_terms(), promote_benchmark=PromoteBenchmark(shares=[]))) == [Code.INVALID_BENCHMARK]
    assert codes(dataclasses.replace(f1_terms(), promote_benchmark=benchmark(lp=1.0))) == [Code.BENCHMARK_PARTNER_SET_MISMATCH]
    doubled = PromoteBenchmark(shares=(BenchmarkShare(partner_id="lp", share=0.5), BenchmarkShare(partner_id="lp", share=0.5)))
    assert codes(dataclasses.replace(f1_terms(), promote_benchmark=doubled)) == [Code.BENCHMARK_PARTNER_SET_MISMATCH]
    assert codes(dataclasses.replace(f1_terms(), promote_benchmark=benchmark(lp=0.9, gp=0.1 + 2e-9))) == [Code.SHARES_DO_NOT_SUM_TO_ONE]
    assert codes(dataclasses.replace(f1_terms(), promote_benchmark=benchmark(lp=1.2, gp=-0.2))) == [Code.INVALID_SHARE, Code.INVALID_SHARE]


def test_a_benchmark_equal_to_commitments_is_still_required() -> None:
    assert codes(dataclasses.replace(f1_terms(), promote_benchmark=benchmark(lp=0.9, gp=0.1))) == []
    assert codes(dataclasses.replace(f1_terms(), promote_benchmark=None)) == [Code.INVALID_BENCHMARK]


def test_promote_participant_issues() -> None:
    assert codes(dataclasses.replace(f1_terms(), promote_participant_ids=None)) == [Code.INVALID_PROMOTE_PARTICIPANTS]
    assert codes(dataclasses.replace(f1_terms(), promote_participant_ids=["gp"])) == [Code.INVALID_PROMOTE_PARTICIPANTS]
    assert codes(dataclasses.replace(f1_terms(), promote_participant_ids=("nobody",))) == [Code.UNKNOWN_PROMOTE_PARTICIPANT]
    assert codes(dataclasses.replace(f1_terms(), promote_participant_ids=("gp", "gp"))) == [Code.DUPLICATE_PROMOTE_PARTICIPANT]
    assert codes(dataclasses.replace(f1_terms(), promote_participant_ids=())) == []
    assert codes(dataclasses.replace(f1_terms(), promote_participant_ids=("gp", "lp"))) == []


def test_tier_list_issues() -> None:
    assert codes(dataclasses.replace(f1_terms(), tiers=())) == [Code.NO_TIERS]
    assert codes(dataclasses.replace(f1_terms(), tiers=list(f1_terms().tiers))) == [Code.INVALID_PARTNERSHIP]
    assert codes(dataclasses.replace(f1_terms(), tiers=(*f1_terms().tiers, "tier"))) == [Code.INVALID_TIER]
    assert codes(replace_tier(f1_terms(), 1, tier_id="pref")) == [Code.DUPLICATE_TIER_ID]
    assert codes(replace_tier(f1_terms(), 1, sequence=10)) == [Code.DUPLICATE_SEQUENCE]
    assert codes(replace_tier(f1_terms(), 1, sequence=0)) == [Code.INVALID_SEQUENCE]
    assert codes(replace_tier(f1_terms(), 1, sequence=True)) == [Code.INVALID_SEQUENCE]
    assert codes(replace_tier(f1_terms(), 1, kind="bonus")) == [Code.INVALID_TIER]


def test_exactly_one_residual_holding_the_last_sequence() -> None:
    terms = f1_terms()
    assert codes(replace_tier(terms, 3, sequence=5)) == [Code.RESIDUAL_NOT_LAST]
    no_residual = dataclasses.replace(terms, tiers=terms.tiers[:3])
    assert codes(no_residual) == [Code.RESIDUAL_COUNT]
    two = dataclasses.replace(terms, tiers=(*terms.tiers, residual("again", 50, split(lp=0.5, gp=0.5))))
    assert codes(two) == [Code.RESIDUAL_COUNT]


def test_kind_and_terms_must_agree() -> None:
    terms = f1_terms()
    assert codes(replace_tier(terms, 3, hurdle=terms.tiers[0].hurdle)) == [Code.KIND_TERMS_MISMATCH]
    assert codes(replace_tier(terms, 0, catch_up=terms.tiers[1].catch_up)) == [Code.KIND_TERMS_MISMATCH]
    assert codes(replace_tier(terms, 1, catch_up="terms")) == [Code.KIND_TERMS_MISMATCH]
    assert codes(replace_tier(terms, 0, hurdle="terms")) == [Code.KIND_TERMS_MISMATCH]


def test_split_issues() -> None:
    terms = f1_terms()
    assert codes(replace_tier(terms, 0, split=None)) == [Code.MISSING_SPLIT]
    assert codes(replace_tier(terms, 0, split={"lp": 0.9, "gp": 0.1})) == [Code.INVALID_SPLIT]
    assert codes(replace_tier(terms, 0, split=split(lp=1.0))) == [Code.SPLIT_PARTNER_SET_MISMATCH]
    assert codes(replace_tier(terms, 0, split=split(lp=0.9, gp=0.2))) == [Code.SHARES_DO_NOT_SUM_TO_ONE]
    assert codes(replace_tier(terms, 3, split=PRO_RATA)) == []


def test_a_hurdle_subject_is_required_and_must_resolve() -> None:
    terms = f1_terms()
    assert codes(replace_tier(terms, 0, hurdle=None)) == [Code.MISSING_HURDLE_SUBJECT]
    assert codes(replace_hurdle(terms, 0, hurdle_subject=None)) == [Code.MISSING_HURDLE_SUBJECT]
    assert codes(replace_hurdle(terms, 0, hurdle_subject="lp")) == [Code.INVALID_HURDLE_SUBJECT]
    wrong_fields = HurdleSubject(kind=HurdleSubjectKind.PARTNER, partner_id="lp", investor_class="a", account=None)
    assert codes(replace_hurdle(terms, 0, hurdle_subject=wrong_fields)) == [Code.INVALID_HURDLE_SUBJECT]
    no_account = HurdleSubject(kind=HurdleSubjectKind.ECONOMIC_ACCOUNT, partner_id=None, investor_class=None, account=None)
    assert codes(replace_hurdle(terms, 0, hurdle_subject=no_account)) == [Code.INVALID_HURDLE_SUBJECT]
    assert codes(replace_hurdle(terms, 0, hurdle_subject=of_partner("nobody"))) == [Code.UNKNOWN_SUBJECT_PARTNER]
    assert codes(replace_hurdle(terms, 0, hurdle_subject=of_class("nobody"))) == [Code.EMPTY_INVESTOR_CLASS]
    assert codes(replace_hurdle(terms, 0, hurdle_subject=ALL_EQUITY)) == []


def test_an_explicit_subject_needs_a_share_in_its_tier() -> None:
    assert codes(replace_tier(f1_terms(), 0, split=split(lp=0.0, gp=1.0))) == [Code.HURDLE_SUBJECT_HAS_NO_SHARE_IN_TIER]


def test_condition_issues() -> None:
    terms = f1_terms()
    assert codes(replace_hurdle(terms, 0, conditions=())) == [Code.NO_CONDITIONS]
    assert codes(replace_hurdle(terms, 0, conditions=[compound("a", 0.08)])) == [Code.INVALID_CONDITION]
    assert codes(replace_hurdle(terms, 0, conditions=("irr",))) == [Code.INVALID_CONDITION]
    assert codes(replace_hurdle(terms, 0, conditions=(compound("a", 0.08), moic("a", 1.5)))) == [Code.DUPLICATE_CONDITION_ID]
    assert codes(replace_hurdle(terms, 0, conditions=(compound("a", -0.01),))) == [Code.INVALID_RATE]
    assert codes(replace_hurdle(terms, 0, conditions=(compound("a", float("nan")),))) == [Code.INVALID_RATE]
    assert codes(replace_hurdle(terms, 0, conditions=(moic("a", 0.99),))) == [Code.INVALID_MULTIPLE]
    assert codes(replace_hurdle(terms, 0, conditions=(moic("a", True),))) == [Code.INVALID_MULTIPLE]
    assert codes(replace_hurdle(terms, 0, combinator="all")) == [Code.INVALID_COMBINATOR]


def test_an_accrual_convention_is_never_assumed() -> None:
    missing = IrrHurdle(condition_id="a", rate=0.08, accrual_convention=None, simple_distribution_order=None)  # type: ignore[arg-type]
    assert codes(replace_hurdle(f1_terms(), 0, conditions=(missing,))) == [Code.MISSING_ACCRUAL_CONVENTION]
    unknown = IrrHurdle(condition_id="a", rate=0.08, accrual_convention="monthly", simple_distribution_order=None)  # type: ignore[arg-type]
    assert codes(replace_hurdle(f1_terms(), 0, conditions=(unknown,))) == [Code.INVALID_CONDITION]


def test_the_simple_distribution_order_is_required_on_simple_only() -> None:
    no_order = IrrHurdle(condition_id="a", rate=0.08, accrual_convention=AccrualConvention.SIMPLE, simple_distribution_order=None)
    assert codes(replace_hurdle(f1_terms(), 0, conditions=(no_order,))) == [Code.MISSING_SIMPLE_DISTRIBUTION_ORDER]
    bad_order = IrrHurdle(condition_id="a", rate=0.08, accrual_convention=AccrualConvention.SIMPLE, simple_distribution_order="first")  # type: ignore[arg-type]
    assert codes(replace_hurdle(f1_terms(), 0, conditions=(bad_order,))) == [Code.INVALID_CONDITION]
    on_compound = IrrHurdle(condition_id="a", rate=0.08, accrual_convention=COMPOUND, simple_distribution_order=SimpleDistributionOrder.CAPITAL_FIRST)
    assert codes(replace_hurdle(f1_terms(), 0, conditions=(on_compound,))) == [Code.UNEXPECTED_SIMPLE_DISTRIBUTION_ORDER]
    assert codes(replace_hurdle(f1_terms(), 0, conditions=(simple("a", 0.08, ACCRUED_FIRST),))) == []
    assert "simple_distribution_order" not in {field.name for field in dataclasses.fields(contracts.MoicHurdle)}


def test_issues_are_ordered_deterministically_whatever_the_list_order() -> None:
    terms = f1_terms()
    broken = dataclasses.replace(
        terms,
        promote_benchmark=benchmark(lp=1.0),
        promote_participant_ids=("nobody",),
        tiers=(
            dataclasses.replace(terms.tiers[0], split=split(lp=0.9, gp=0.2)),
            dataclasses.replace(terms.tiers[2], hurdle=None),
            terms.tiers[1],
            terms.tiers[3],
        ),
    )
    reordered = dataclasses.replace(broken, tiers=tuple(reversed(broken.tiers)), partners=tuple(reversed(broken.partners)))
    assert validate_partnership(broken) == validate_partnership(reordered)
    assert codes(broken) == [
        Code.BENCHMARK_PARTNER_SET_MISMATCH,
        Code.UNKNOWN_PROMOTE_PARTICIPANT,
        Code.SHARES_DO_NOT_SUM_TO_ONE,
        Code.MISSING_HURDLE_SUBJECT,
    ]
    assert [issue.tier_id for issue in validate_partnership(broken)][2:] == ["pref", "promote_1"]


def test_an_invalid_contract_is_never_allocated_even_over_a_valid_series() -> None:
    with pytest.raises(PartnershipValidationError) as caught:
        allocate_partnership(dataclasses.replace(f1_terms(), promote_benchmark=None), __import__("_p7_9_fixtures").series(*F1_SERIES))
    assert [issue.code for issue in caught.value.issues] == [Code.INVALID_BENCHMARK]


# =============================================================================
# Execution refusals of the contract
# =============================================================================


def test_a_future_contribution_rule_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from anchor.partnership import waterfall

    monkeypatch.setattr(waterfall, "SUPPORTED_CONTRIBUTION_RULES", frozenset())
    with pytest.raises(PartnershipExecutionError) as caught:
        run(f1_terms(), *F1_SERIES)
    assert [issue.code for issue in caught.value.issues] == [PartnershipExecutionIssueCode.UNSUPPORTED_CONTRIBUTION_RULE]


def test_a_future_accrual_convention_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from anchor.partnership import waterfall

    monkeypatch.setattr(waterfall, "SUPPORTED_ACCRUAL_CONVENTIONS", frozenset({AccrualConvention.SIMPLE}))
    with pytest.raises(PartnershipExecutionError) as caught:
        run(f1_terms(), *F1_SERIES)
    assert [(issue.code, issue.tier_id) for issue in caught.value.issues] == [
        (PartnershipExecutionIssueCode.UNSUPPORTED_ACCRUAL_CONVENTION, "pref"),
        (PartnershipExecutionIssueCode.UNSUPPORTED_ACCRUAL_CONVENTION, "promote_1"),
    ]


def test_builders_state_every_field() -> None:
    tier = catch_up("c", 1, to_partner("gp"), 0.2, split(lp=0.5, gp=0.5))
    assert isinstance(tier, WaterfallTier) and tier.kind is TierKind.CATCH_UP and tier.hurdle is None
    assert hurdle("h", 1, of_partner("lp"), (compound("x", 0.1),), split(lp=1.0, gp=0.0)).hurdle.combinator is HurdleCombinator.ALL  # type: ignore[union-attr]
    assert SplitShare(partner_id="a", share=1.0).share == 1.0
    assert isinstance(LP_GP, tuple) and partnership is not None
