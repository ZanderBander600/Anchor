"""Phase 7 Gate P7.9 Stage 1 -- the catch-up.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 9 and fixtures F1,
F8, F9 and F12: the closed form, the positive-profit domain, the derived rate,
partner and investor-class recipients, and re-entry.
"""

from __future__ import annotations

import pytest

from _p7_9_fixtures import (  # type: ignore[import-not-found]
    BENCH_90_10,
    F1_SERIES,
    F8_SERIES,
    F9_SERIES,
    F12_SERIES,
    LP_GP,
    PRO_RATA,
    by_partner,
    by_tier,
    catch_up,
    close,
    compound,
    f1_series,
    f1_terms,
    f5_terms,
    f8_terms,
    f12_terms,
    hurdle,
    moic,
    of_partner,
    partnership,
    residual,
    run,
    split,
    to_class,
    to_partner,
)
from anchor.partnership import (
    WATERFALL_AMOUNT_TOLERANCE,
    CatchUpRecipient,
    CatchUpRecipientKind,
    HurdleSubjectKind,
    PartnershipIssueCode,
    PartnershipValidationError,
    allocate_partnership,
    validate_partnership,
)
from anchor.partnership.waterfall import catch_up_capacity


def test_f1_catch_up_is_the_closed_form() -> None:
    tier = by_tier(run(f1_terms(), *F1_SERIES))["catch_up"]
    (record,) = tier.catch_up_records
    assert record.period == 3 and record.profit_domain_open
    assert close(record.partnership_profit_at_entry, 271_552.0)
    assert close(record.recipient_profit_at_entry, 27_155.20)
    assert close(record.capacity_at_entry, 67_888.0) and close(record.paid, 67_888.0)
    assert close(record.recipient_profit_at_exit, 67_888.0)
    assert close(record.partnership_profit_at_exit, 339_440.0)
    assert record.caught_up
    assert tier.catch_up_rate == 0.6 and tier.target_profit_share == 0.2
    assert tier.recipient_partner_ids == ("gp",)
    assert tier.catch_up_recipient == to_partner("gp")


def test_a_partial_catch_up_is_not_caught_up() -> None:
    tier = by_tier(run(f1_terms(), *f1_series(1_340_000.0)))["catch_up"]
    (record,) = tier.catch_up_records
    assert close(record.paid, 28_448.0) and close(record.capacity_at_entry, 67_888.0)
    assert not record.caught_up
    partners = by_partner(run(f1_terms(), *f1_series(1_340_000.0)))
    assert close(partners["gp"].distributions_by_tier[1].amount, 17_068.80)
    assert close(partners["lp"].distributions_by_tier[1].amount, 11_379.20)


def test_f9_no_catch_up_while_partnership_profit_is_not_positive() -> None:
    result = run(f5_terms(with_catch_up=True), *F9_SERIES)
    tiers = by_tier(result)
    (record,) = tiers["catch_up"].catch_up_records
    assert close(record.partnership_profit_at_entry, -100_000.0)
    assert close(record.recipient_profit_at_entry, -100_000.0)
    assert not record.profit_domain_open and record.capacity_at_entry == 0.0 and record.paid == 0.0
    assert not record.caught_up
    assert close(tiers["residual"].amounts[2], 50_000.0)
    partners = by_partner(result)
    assert close(partners["lp"].total_distributions, 940_000.0) and close(partners["gp"].total_distributions, 10_000.0)


@pytest.mark.parametrize(
    ("profit", "expected"),
    [
        (-100_000.0, 0.0),
        (0.0, 0.0),
        (WATERFALL_AMOUNT_TOLERANCE, 0.0),
        (-1e-12, 0.0),
    ],
)
def test_the_domain_is_closed_at_and_below_zero_profit(profit: float, expected: float) -> None:
    # the recipient is far "behind" in every case
    assert catch_up_capacity(profit=profit, recipient_profit=-1_000_000.0, rate=1.0, target=0.2) == expected


def test_the_domain_opens_just_above_the_tolerance() -> None:
    capacity = catch_up_capacity(profit=1.0, recipient_profit=-1_000.0, rate=1.0, target=0.2)
    assert close(capacity, (0.2 * 1.0 + 1_000.0) / 0.8)


def test_a_recipient_already_caught_up_is_skipped() -> None:
    assert catch_up_capacity(profit=1_000.0, recipient_profit=300.0, rate=0.6, target=0.2) == 0.0


def test_f8_a_full_catch_up_to_a_promote_only_sponsor() -> None:
    tier = by_tier(run(f8_terms(), *F8_SERIES))["catch_up"]
    (record,) = tier.catch_up_records
    assert close(record.partnership_profit_at_entry, 166_400.0) and record.recipient_profit_at_entry == 0.0
    assert close(record.paid, 41_600.0) and tier.catch_up_rate == 1.0
    assert close(record.recipient_profit_at_exit, 0.2 * record.partnership_profit_at_exit)


def test_f12_a_class_recipient_is_one_aggregate() -> None:
    result = run(f12_terms(), *F12_SERIES)
    tier = by_tier(result)["catch_up"]
    (record,) = tier.catch_up_records
    assert tier.recipient_partner_ids == ("g1", "g2") and tier.catch_up_rate == 1.0
    assert close(record.partnership_profit_at_entry, 166_400.0)
    assert close(record.recipient_profit_at_entry, 16_640.0)
    assert close(record.paid, 20_800.0)
    assert close(record.recipient_profit_at_exit, 37_440.0) and close(record.partnership_profit_at_exit, 187_200.0)
    assert close(by_tier(result)["residual"].amounts[2], 312_800.0)
    partners = by_partner(result)
    for sponsor in ("g1", "g2"):
        assert close(partners[sponsor].total_distributions, 100_000.0)
        assert close(partners[sponsor].distributions_by_tier[1].amount, 10_400.0)


def test_the_catch_up_is_retested_every_period_and_resumes_when_the_recipient_falls_behind() -> None:
    # year 1 catches the GP up; a year-2 capital call and the year-3 pref at
    # 90 / 10 dilute it below 20%, so year 3 resumes the catch-up
    tier = by_tier(run(f1_terms(), -1_000_000.0, 1_100_000.0, -200_000.0, 1_500_000.0))["catch_up"]
    first, resumed = tier.catch_up_records
    assert first.period == 1 and close(first.paid, 20_000.0) and first.caught_up
    assert close(first.partnership_profit_at_entry, 80_000.0) and close(first.recipient_profit_at_entry, 8_000.0)
    assert resumed.period == 3
    assert close(resumed.partnership_profit_at_entry, 105_632.0) and close(resumed.recipient_profit_at_entry, 20_563.20)
    assert close(resumed.paid, (0.2 * 105_632.0 - 20_563.20) / 0.4)
    assert close(resumed.recipient_profit_at_exit, 0.2 * resumed.partnership_profit_at_exit) and resumed.caught_up


def test_a_caught_up_recipient_is_retested_and_paid_nothing() -> None:
    tier = by_tier(run(f1_terms(), -1_000_000.0, 1_200_000.0, 500_000.0))["catch_up"]
    first, second = tier.catch_up_records
    assert close(first.paid, 20_000.0)
    assert second.period == 2 and second.capacity_at_entry == 0.0 and second.paid == 0.0 and second.caught_up


def test_a_catch_up_is_never_paid_twice_for_the_same_profit() -> None:
    tier = by_tier(run(f1_terms(), -1_000_000.0, 1_600_000.0, 0.0, 100.0))["catch_up"]
    later = [record for record in tier.catch_up_records if record.period == 3]
    assert later and all(record.paid == 0.0 for record in later)


# =============================================================================
# Validation of the catch-up terms
# =============================================================================


def _catch_up_terms(**overrides: object) -> object:
    stated = {"recipient": to_partner("gp"), "target": 0.2, "split": split(lp=0.4, gp=0.6)}
    stated.update(overrides)
    return partnership(
        LP_GP,
        (
            hurdle("pref", 10, of_partner("lp"), (compound("p", 0.08),), split(lp=0.9, gp=0.1)),
            catch_up("catch_up", 20, stated["recipient"], stated["target"], stated["split"]),  # type: ignore[arg-type]
            residual("residual", 30, split(lp=0.8, gp=0.2)),
        ),
        bench=BENCH_90_10,
        participants=("gp",),
    )


def _codes(terms: object) -> list[PartnershipIssueCode]:
    return [issue.code for issue in validate_partnership(terms)]


def test_the_rate_must_exceed_the_target() -> None:
    assert _codes(_catch_up_terms(split=split(lp=0.8, gp=0.2))) == [PartnershipIssueCode.CATCH_UP_RATE_NOT_ABOVE_TARGET]
    assert _codes(_catch_up_terms(split=split(lp=0.79, gp=0.21))) == []


def test_an_account_recipient_is_unsupported() -> None:
    recipient = CatchUpRecipient(kind=HurdleSubjectKind.ECONOMIC_ACCOUNT, partner_id=None, investor_class=None)  # type: ignore[arg-type]
    assert _codes(_catch_up_terms(recipient=recipient)) == [PartnershipIssueCode.UNSUPPORTED_CATCH_UP_RECIPIENT]
    assert "economic_account" not in {member.value for member in CatchUpRecipientKind}


def test_a_catch_up_requires_an_explicit_split() -> None:
    assert _codes(_catch_up_terms(split=PRO_RATA)) == [PartnershipIssueCode.CATCH_UP_REQUIRES_EXPLICIT_SPLIT]


@pytest.mark.parametrize(
    ("recipient", "code"),
    [
        (to_partner("nobody"), PartnershipIssueCode.UNKNOWN_SUBJECT_PARTNER),
        (to_class("nobody"), PartnershipIssueCode.EMPTY_INVESTOR_CLASS),
        (CatchUpRecipient(kind=CatchUpRecipientKind.PARTNER, partner_id="gp", investor_class="x"), PartnershipIssueCode.INVALID_CATCH_UP_RECIPIENT),
        (CatchUpRecipient(kind=CatchUpRecipientKind.INVESTOR_CLASS, partner_id=None, investor_class=" "), PartnershipIssueCode.INVALID_CATCH_UP_RECIPIENT),
        ("gp", PartnershipIssueCode.INVALID_CATCH_UP_RECIPIENT),
    ],
)
def test_a_recipient_must_resolve(recipient: object, code: PartnershipIssueCode) -> None:
    assert _codes(_catch_up_terms(recipient=recipient)) == [code]


@pytest.mark.parametrize("target", [0.0, 1.0, -0.1, float("nan"), True, "0.2"])
def test_the_target_lies_strictly_between_zero_and_one(target: object) -> None:
    assert _codes(_catch_up_terms(target=target)) == [PartnershipIssueCode.INVALID_TARGET_PROFIT_SHARE]


def test_an_invalid_catch_up_is_never_allocated() -> None:
    with pytest.raises(PartnershipValidationError):
        allocate_partnership(_catch_up_terms(split=split(lp=0.8, gp=0.2)), __import__("_p7_9_fixtures").series(*F1_SERIES))  # type: ignore[arg-type]


def test_a_hurdle_tier_rejects_catch_up_terms_and_the_reverse() -> None:
    import dataclasses

    terms = _catch_up_terms()
    tiers = terms.tiers  # type: ignore[attr-defined]
    swapped = (dataclasses.replace(tiers[0], catch_up=tiers[1].catch_up), dataclasses.replace(tiers[1], hurdle=tiers[0].hurdle), tiers[2])
    codes = _codes(dataclasses.replace(terms, tiers=swapped))  # type: ignore[type-var]
    assert codes == [PartnershipIssueCode.KIND_TERMS_MISMATCH, PartnershipIssueCode.KIND_TERMS_MISMATCH]


def test_moic_catch_up_fixture_is_unused_helper_guard() -> None:
    assert moic("m", 1.0).multiple == 1.0
