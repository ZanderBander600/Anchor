"""Phase 7 Gate P7.9 -- structural validation of a Partnership.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 4 and 5.1
(ratified); that document governs on any discrepancy. Pure: no I/O, clock or
randomness, and no knowledge of storage, routes or upstream results. Its only
arithmetic is the share-sum check.

``validate_partnership`` returns ``()`` for a valid contract and never repairs,
coerces, reorders or defaults anything. Issues come in a deterministic order
that never depends on list order: partners by id, then the contribution rule
and benchmark, then promote participants, then tiers by sequence (tier id
breaking ties), then the cross-tier issues.

It also resolves the members of hurdle subjects and catch-up recipients, and
gives the canonical orders the executor uses.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from math import isfinite

from .contracts import (
    AccrualConvention,
    SHARE_SUM_TOLERANCE,
    CatchUpRecipient,
    CatchUpRecipientKind,
    CatchUpTerms,
    ContributionRule,
    EconomicAccount,
    ExplicitSplit,
    HurdleCombinator,
    HurdleSubject,
    HurdleSubjectKind,
    HurdleTerms,
    IrrHurdle,
    MoicHurdle,
    Partner,
    PartnerRole,
    Partnership,
    PartnershipIssue,
    PartnershipIssueCode,
    PartnershipValidationError,
    ProRataByContribution,
    PromoteBenchmark,
    SimpleDistributionOrder,
    TierKind,
    WaterfallTier,
)

Code = PartnershipIssueCode

_MAX_REPR = 200


def _repr(value: object) -> str:
    try:
        text = repr(value)
    except Exception:
        return f"<{type(value).__qualname__}>"
    return text if len(text) <= _MAX_REPR else f"<{type(value).__qualname__}>"


def _is_text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_number(value: object) -> bool:
    """A finite ``int`` or ``float``; ``bool`` is not a number here."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(float(value))
    except OverflowError:
        return False


def _is_share(value: object) -> bool:
    return _is_number(value) and 0.0 <= float(value) <= 1.0  # type: ignore[arg-type]


def _is_whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _share_sum(shares: Iterable[tuple[str, float]]) -> float:
    """The canonical-order (partner id) sum of a share table."""

    total = 0.0
    for _, share in sorted(shares, key=lambda item: item[0]):
        total = total + float(share)
    return total


def _sums_to_one(shares: Iterable[tuple[str, float]]) -> bool:
    return abs(_share_sum(shares) - 1.0) <= SHARE_SUM_TOLERANCE


def _issue(code: Code, message: str, *, partner_id: str | None = None, tier_id: str | None = None, field: str | None = None) -> PartnershipIssue:
    return PartnershipIssue(code=code, message=message, partner_id=partner_id, tier_id=tier_id, field=field)


# =============================================================================
# Canonical orders and member resolution
# =============================================================================


def partner_ids(partnership: Partnership) -> tuple[str, ...]:
    """Partners in canonical order: by ``partner_id``."""

    return tuple(sorted(partner.partner_id for partner in partnership.partners))


def ordered_tiers(partnership: Partnership) -> tuple[WaterfallTier, ...]:
    """Tiers in economic order: by ``sequence`` (P-7). List order never
    participates."""

    return tuple(sorted(partnership.tiers, key=lambda tier: (tier.sequence, tier.tier_id)))


def subject_members(partnership: Partnership, subject: HurdleSubject) -> tuple[str, ...]:
    """The partners whose flows a hurdle subject aggregates, in canonical order."""

    partners = sorted(partnership.partners, key=lambda partner: partner.partner_id)
    if subject.kind is HurdleSubjectKind.PARTNER:
        return tuple(partner.partner_id for partner in partners if partner.partner_id == subject.partner_id)
    if subject.kind is HurdleSubjectKind.INVESTOR_CLASS:
        return tuple(partner.partner_id for partner in partners if partner.investor_class == subject.investor_class)
    return tuple(partner.partner_id for partner in partners)


def recipient_members(partnership: Partnership, recipient: CatchUpRecipient) -> tuple[str, ...]:
    """The partners a catch-up recipient aggregates, in canonical order."""

    partners = sorted(partnership.partners, key=lambda partner: partner.partner_id)
    if recipient.kind is CatchUpRecipientKind.PARTNER:
        return tuple(partner.partner_id for partner in partners if partner.partner_id == recipient.partner_id)
    return tuple(partner.partner_id for partner in partners if partner.investor_class == recipient.investor_class)


def explicit_shares(split: ExplicitSplit) -> dict[str, float]:
    return {share.partner_id: float(share.share) for share in split.shares}


def members_share(shares: dict[str, float], members: Iterable[str]) -> float:
    """The canonical-order sum of the members' shares."""

    total = 0.0
    for partner_id in sorted(members):
        total = total + shares[partner_id]
    return total


# =============================================================================
# Partners, benchmark, participants
# =============================================================================


def _partner_issues(partners: object) -> tuple[list[PartnershipIssue], set[str]]:
    issues: list[PartnershipIssue] = []
    if not isinstance(partners, tuple):
        return [_issue(Code.INVALID_PARTNERSHIP, "partners must be a tuple of Partner.", field="partners")], set()
    if not partners:
        return [_issue(Code.NO_PARTNERS, "A Partnership needs at least one partner.", field="partners")], set()
    typed = [partner for partner in partners if isinstance(partner, Partner)]
    if len(typed) != len(partners):
        issues.append(_issue(Code.INVALID_PARTNER, "Every partner must be a Partner.", field="partners"))
    ids = [partner.partner_id for partner in typed]
    counts = Counter(partner_id for partner_id in ids if _is_text(partner_id))
    known = set(counts)
    for partner in sorted(typed, key=lambda item: _repr(item.partner_id)):
        pid = partner.partner_id if _is_text(partner.partner_id) else None
        if pid is None:
            issues.append(_issue(Code.BLANK_PARTNER_ID, f"Partner id {_repr(partner.partner_id)} must be nonblank text.", field="partner_id"))
            continue
        if not isinstance(partner.role, PartnerRole):
            issues.append(_issue(Code.INVALID_ROLE, f"Partner {pid} has an unknown role {_repr(partner.role)}.", partner_id=pid, field="role"))
        if partner.investor_class is not None and not _is_text(partner.investor_class):
            issues.append(_issue(Code.INVALID_INVESTOR_CLASS, f"Partner {pid}'s investor_class must be nonblank text or None.", partner_id=pid, field="investor_class"))
        if not _is_share(partner.commitment_share):
            issues.append(_issue(Code.INVALID_SHARE, f"Partner {pid}'s commitment_share {_repr(partner.commitment_share)} must be a finite number in [0, 1].", partner_id=pid, field="commitment_share"))
    for pid in sorted(partner_id for partner_id, count in counts.items() if count > 1):
        issues.append(_issue(Code.DUPLICATE_PARTNER_ID, f"Partner id {pid} is used more than once.", partner_id=pid, field="partner_id"))
    if not issues:
        if not _sums_to_one((partner.partner_id, partner.commitment_share) for partner in typed):
            issues.append(_issue(Code.SHARES_DO_NOT_SUM_TO_ONE, "Commitment shares must sum to 1.", field="commitment_share"))
    return issues, known


def _table_issues(
    rows: object, known: set[str], *, what: str, mismatch: Code, tier_id: str | None = None
) -> list[PartnershipIssue]:
    """A share table: exactly one finite share in [0, 1] per partner, summing
    to 1."""

    if not isinstance(rows, tuple):
        return [_issue(Code.INVALID_SPLIT if tier_id else Code.INVALID_BENCHMARK, f"The {what} shares must be a tuple.", tier_id=tier_id, field="shares")]
    issues: list[PartnershipIssue] = []
    stated = [getattr(row, "partner_id", None) for row in rows]
    for row in rows:
        if not _is_share(getattr(row, "share", None)):
            issues.append(_issue(Code.INVALID_SHARE, f"The {what} share of {_repr(getattr(row, 'partner_id', None))} must be a finite number in [0, 1].", tier_id=tier_id, field="share"))
    if Counter(stated) != Counter(known):
        issues.append(_issue(mismatch, f"The {what} must state exactly one share for each partner.", tier_id=tier_id, field="shares"))
    if not issues and not _sums_to_one((row.partner_id, row.share) for row in rows):  # type: ignore[attr-defined]
        issues.append(_issue(Code.SHARES_DO_NOT_SUM_TO_ONE, f"The {what} shares must sum to 1.", tier_id=tier_id, field="shares"))
    return issues


def _benchmark_issues(benchmark: object, known: set[str]) -> list[PartnershipIssue]:
    if not isinstance(benchmark, PromoteBenchmark):
        return [_issue(Code.INVALID_BENCHMARK, "promote_benchmark must be a PromoteBenchmark; there is no default.", field="promote_benchmark")]
    return _table_issues(benchmark.shares, known, what="promote benchmark", mismatch=Code.BENCHMARK_PARTNER_SET_MISMATCH)


def _participant_issues(participants: object, known: set[str]) -> list[PartnershipIssue]:
    if not isinstance(participants, tuple) or not all(isinstance(item, str) for item in participants):
        return [_issue(Code.INVALID_PROMOTE_PARTICIPANTS, "promote_participant_ids must be a tuple of partner ids (it may be empty).", field="promote_participant_ids")]
    issues: list[PartnershipIssue] = []
    counts = Counter(participants)
    for pid in sorted(counts):
        if pid not in known:
            issues.append(_issue(Code.UNKNOWN_PROMOTE_PARTICIPANT, f"Promote participant {_repr(pid)} is not a partner.", partner_id=pid, field="promote_participant_ids"))
        if counts[pid] > 1:
            issues.append(_issue(Code.DUPLICATE_PROMOTE_PARTICIPANT, f"Promote participant {pid} is named more than once.", partner_id=pid, field="promote_participant_ids"))
    return issues


# =============================================================================
# Tiers
# =============================================================================


def _subject_issues(subject: object, partnership: Partnership, tier_id: str) -> tuple[list[PartnershipIssue], tuple[str, ...]]:
    if subject is None:
        return [_issue(Code.MISSING_HURDLE_SUBJECT, f"Tier {tier_id} must name its hurdle subject; there is no default.", tier_id=tier_id, field="hurdle_subject")], ()
    if not isinstance(subject, HurdleSubject) or not isinstance(subject.kind, HurdleSubjectKind):
        return [_issue(Code.INVALID_HURDLE_SUBJECT, f"Tier {tier_id}'s hurdle subject is not a HurdleSubject.", tier_id=tier_id, field="hurdle_subject")], ()
    kind = subject.kind
    shaped = (
        (kind is HurdleSubjectKind.PARTNER and _is_text(subject.partner_id) and subject.investor_class is None and subject.account is None)
        or (kind is HurdleSubjectKind.INVESTOR_CLASS and _is_text(subject.investor_class) and subject.partner_id is None and subject.account is None)
        or (kind is HurdleSubjectKind.ECONOMIC_ACCOUNT and isinstance(subject.account, EconomicAccount) and subject.partner_id is None and subject.investor_class is None)
    )
    if not shaped:
        return [_issue(Code.INVALID_HURDLE_SUBJECT, f"Tier {tier_id}'s {kind.value} subject must state exactly the field of its kind.", tier_id=tier_id, field="hurdle_subject")], ()
    members = subject_members(partnership, subject)
    if not members:
        code = Code.UNKNOWN_SUBJECT_PARTNER if kind is HurdleSubjectKind.PARTNER else Code.EMPTY_INVESTOR_CLASS
        return [_issue(code, f"Tier {tier_id}'s hurdle subject resolves to no partner.", tier_id=tier_id, field="hurdle_subject")], ()
    return [], members


def _condition_issues(conditions: object, tier_id: str) -> list[PartnershipIssue]:
    if not isinstance(conditions, tuple):
        return [_issue(Code.INVALID_CONDITION, f"Tier {tier_id}'s conditions must be a tuple.", tier_id=tier_id, field="conditions")]
    if not conditions:
        return [_issue(Code.NO_CONDITIONS, f"Tier {tier_id} needs at least one hurdle condition.", tier_id=tier_id, field="conditions")]
    issues: list[PartnershipIssue] = []
    ids = [getattr(condition, "condition_id", None) for condition in conditions]
    for condition in sorted(conditions, key=lambda item: _repr(getattr(item, "condition_id", None))):
        if not isinstance(condition, (IrrHurdle, MoicHurdle)) or not _is_text(condition.condition_id):
            issues.append(_issue(Code.INVALID_CONDITION, f"Tier {tier_id} has a condition that is not an IrrHurdle or MoicHurdle with a nonblank id.", tier_id=tier_id, field="conditions"))
            continue
        cid = condition.condition_id
        if isinstance(condition, MoicHurdle):
            if not (_is_number(condition.multiple) and float(condition.multiple) >= 1.0):
                issues.append(_issue(Code.INVALID_MULTIPLE, f"Condition {cid}'s multiple {_repr(condition.multiple)} must be a finite number >= 1.", tier_id=tier_id, field="multiple"))
            continue
        if not (_is_number(condition.rate) and float(condition.rate) >= 0.0):
            issues.append(_issue(Code.INVALID_RATE, f"Condition {cid}'s rate {_repr(condition.rate)} must be a finite number >= 0.", tier_id=tier_id, field="rate"))
        convention = condition.accrual_convention
        if convention is None:
            issues.append(_issue(Code.MISSING_ACCRUAL_CONVENTION, f"Condition {cid} must state its accrual convention; none is assumed.", tier_id=tier_id, field="accrual_convention"))
            continue
        if not isinstance(convention, AccrualConvention):
            issues.append(_issue(Code.INVALID_CONDITION, f"Condition {cid} has an unknown accrual convention {_repr(convention)}.", tier_id=tier_id, field="accrual_convention"))
            continue
        order = condition.simple_distribution_order
        if convention is AccrualConvention.SIMPLE:
            if order is None:
                issues.append(_issue(Code.MISSING_SIMPLE_DISTRIBUTION_ORDER, f"SIMPLE condition {cid} must state its distribution order; there is no default.", tier_id=tier_id, field="simple_distribution_order"))
            elif not isinstance(order, SimpleDistributionOrder):
                issues.append(_issue(Code.INVALID_CONDITION, f"Condition {cid} has an unknown distribution order {_repr(order)}.", tier_id=tier_id, field="simple_distribution_order"))
        elif order is not None:
            issues.append(_issue(Code.UNEXPECTED_SIMPLE_DISTRIBUTION_ORDER, f"Condition {cid} is not SIMPLE and may not state a distribution order.", tier_id=tier_id, field="simple_distribution_order"))
    for cid in sorted(str(item) for item, count in Counter(ids).items() if count > 1 and _is_text(item)):
        issues.append(_issue(Code.DUPLICATE_CONDITION_ID, f"Tier {tier_id} uses condition id {cid} more than once.", tier_id=tier_id, field="condition_id"))
    return issues


def _hurdle_issues(tier: WaterfallTier, partnership: Partnership, split_ok: bool) -> list[PartnershipIssue]:
    terms = tier.hurdle
    tid = tier.tier_id
    if not isinstance(terms, HurdleTerms):
        return [_issue(Code.KIND_TERMS_MISMATCH, f"Hurdle tier {tid} must state HurdleTerms.", tier_id=tid, field="hurdle")]
    issues, members = _subject_issues(terms.hurdle_subject, partnership, tid)
    issues.extend(_condition_issues(terms.conditions, tid))
    if not isinstance(terms.combinator, HurdleCombinator):
        issues.append(_issue(Code.INVALID_COMBINATOR, f"Tier {tid} must state ALL or ANY.", tier_id=tid, field="combinator"))
    if members and split_ok and isinstance(tier.split, ExplicitSplit):
        if members_share(explicit_shares(tier.split), members) <= 0.0:
            issues.append(_issue(Code.HURDLE_SUBJECT_HAS_NO_SHARE_IN_TIER, f"Tier {tid}'s hurdle subject has no share in the tier's split, so the hurdle could never be reached.", tier_id=tid, field="split"))
    return issues


def _catch_up_issues(tier: WaterfallTier, partnership: Partnership, split_ok: bool) -> list[PartnershipIssue]:
    terms = tier.catch_up
    tid = tier.tier_id
    if not isinstance(terms, CatchUpTerms):
        return [_issue(Code.KIND_TERMS_MISMATCH, f"Catch-up tier {tid} must state CatchUpTerms.", tier_id=tid, field="catch_up")]
    issues: list[PartnershipIssue] = []
    recipient = terms.recipient
    members: tuple[str, ...] = ()
    if not isinstance(recipient, CatchUpRecipient):
        issues.append(_issue(Code.INVALID_CATCH_UP_RECIPIENT, f"Tier {tid}'s recipient is not a CatchUpRecipient.", tier_id=tid, field="recipient"))
    elif not isinstance(recipient.kind, CatchUpRecipientKind):
        issues.append(_issue(Code.UNSUPPORTED_CATCH_UP_RECIPIENT, f"Tier {tid}'s recipient kind {_repr(recipient.kind)} is not supported: a catch-up recipient is a partner or an investor class, never an economic account.", tier_id=tid, field="recipient"))
    else:
        shaped = (
            (recipient.kind is CatchUpRecipientKind.PARTNER and _is_text(recipient.partner_id) and recipient.investor_class is None)
            or (recipient.kind is CatchUpRecipientKind.INVESTOR_CLASS and _is_text(recipient.investor_class) and recipient.partner_id is None)
        )
        if not shaped:
            issues.append(_issue(Code.INVALID_CATCH_UP_RECIPIENT, f"Tier {tid}'s {recipient.kind.value} recipient must state exactly the field of its kind.", tier_id=tid, field="recipient"))
        else:
            members = recipient_members(partnership, recipient)
            if not members:
                code = Code.UNKNOWN_SUBJECT_PARTNER if recipient.kind is CatchUpRecipientKind.PARTNER else Code.EMPTY_INVESTOR_CLASS
                issues.append(_issue(code, f"Tier {tid}'s catch-up recipient resolves to no partner.", tier_id=tid, field="recipient"))
    target = terms.target_profit_share
    target_ok = _is_number(target) and 0.0 < float(target) < 1.0  # type: ignore[arg-type]
    if not target_ok:
        issues.append(_issue(Code.INVALID_TARGET_PROFIT_SHARE, f"Tier {tid}'s target_profit_share {_repr(target)} must lie in (0, 1).", tier_id=tid, field="target_profit_share"))
    if isinstance(tier.split, ProRataByContribution):
        issues.append(_issue(Code.CATCH_UP_REQUIRES_EXPLICIT_SPLIT, f"Catch-up tier {tid} must use an explicit split, so its rate is a stated term.", tier_id=tid, field="split"))
    elif members and target_ok and split_ok and isinstance(tier.split, ExplicitSplit):
        rate = members_share(explicit_shares(tier.split), members)
        if rate <= float(target):  # type: ignore[arg-type]
            issues.append(_issue(Code.CATCH_UP_RATE_NOT_ABOVE_TARGET, f"Tier {tid}'s catch-up rate {rate!r} must exceed its target {target!r}, or the catch-up could never finish.", tier_id=tid, field="split"))
    return issues


def _tier_issues(tier: WaterfallTier, partnership: Partnership, known: set[str]) -> list[PartnershipIssue]:
    tid = tier.tier_id
    issues: list[PartnershipIssue] = []
    if not _is_whole(tier.sequence) or tier.sequence < 1:
        issues.append(_issue(Code.INVALID_SEQUENCE, f"Tier {tid}'s sequence {_repr(tier.sequence)} must be a whole number >= 1.", tier_id=tid, field="sequence"))
    if not isinstance(tier.kind, TierKind):
        return [*issues, _issue(Code.INVALID_TIER, f"Tier {tid} has an unknown kind {_repr(tier.kind)}.", tier_id=tid, field="kind")]
    split = tier.split
    split_ok = False
    if split is None:
        issues.append(_issue(Code.MISSING_SPLIT, f"Tier {tid} must state its split rule; there is no default.", tier_id=tid, field="split"))
    elif isinstance(split, ExplicitSplit):
        split_issues = _table_issues(split.shares, known, what=f"tier {tid} split", mismatch=Code.SPLIT_PARTNER_SET_MISMATCH, tier_id=tid)
        issues.extend(split_issues)
        split_ok = not split_issues
    elif isinstance(split, ProRataByContribution):
        split_ok = True
    else:
        issues.append(_issue(Code.INVALID_SPLIT, f"Tier {tid}'s split must be ExplicitSplit or ProRataByContribution.", tier_id=tid, field="split"))
    if tier.kind is TierKind.HURDLE:
        if tier.catch_up is not None:
            issues.append(_issue(Code.KIND_TERMS_MISMATCH, f"Hurdle tier {tid} may not state catch-up terms.", tier_id=tid, field="catch_up"))
        if tier.hurdle is None:
            issues.append(_issue(Code.MISSING_HURDLE_SUBJECT, f"Hurdle tier {tid} must state its hurdle and subject; there is no default.", tier_id=tid, field="hurdle"))
        else:
            issues.extend(_hurdle_issues(tier, partnership, split_ok))
    elif tier.kind is TierKind.CATCH_UP:
        if tier.hurdle is not None:
            issues.append(_issue(Code.KIND_TERMS_MISMATCH, f"Catch-up tier {tid} may not state hurdle terms.", tier_id=tid, field="hurdle"))
        issues.extend(_catch_up_issues(tier, partnership, split_ok))
    else:
        if tier.hurdle is not None or tier.catch_up is not None:
            issues.append(_issue(Code.KIND_TERMS_MISMATCH, f"Residual tier {tid} states no hurdle or catch-up terms.", tier_id=tid, field="kind"))
    return issues


def _tiers_issues(tiers: object, partnership: Partnership, known: set[str]) -> list[PartnershipIssue]:
    if not isinstance(tiers, tuple):
        return [_issue(Code.INVALID_PARTNERSHIP, "tiers must be a tuple of WaterfallTier.", field="tiers")]
    if not tiers:
        return [_issue(Code.NO_TIERS, "A Partnership needs at least one tier.", field="tiers")]
    if not all(isinstance(tier, WaterfallTier) and _is_text(tier.tier_id) for tier in tiers):
        return [_issue(Code.INVALID_TIER, "Every tier must be a WaterfallTier with a nonblank tier_id.", field="tiers")]
    issues: list[PartnershipIssue] = []
    orderable = all(_is_whole(tier.sequence) for tier in tiers)
    ordered = sorted(tiers, key=(lambda tier: (tier.sequence, tier.tier_id)) if orderable else (lambda tier: ("", tier.tier_id)))
    for tier in ordered:
        issues.extend(_tier_issues(tier, partnership, known))
    for tid in sorted(tid for tid, count in Counter(tier.tier_id for tier in tiers).items() if count > 1):
        issues.append(_issue(Code.DUPLICATE_TIER_ID, f"Tier id {tid} is used more than once.", tier_id=tid, field="tier_id"))
    sequences = Counter(tier.sequence for tier in tiers if _is_whole(tier.sequence))
    for sequence in sorted(value for value, count in sequences.items() if count > 1):
        issues.append(_issue(Code.DUPLICATE_SEQUENCE, f"Sequence {sequence} is used by more than one tier.", field="sequence"))
    residuals = [tier for tier in tiers if tier.kind is TierKind.RESIDUAL]
    if len(residuals) != 1:
        issues.append(_issue(Code.RESIDUAL_COUNT, f"A Partnership needs exactly one RESIDUAL tier; it has {len(residuals)}.", field="kind"))
    elif orderable and ordered[-1] is not residuals[0]:
        issues.append(_issue(Code.RESIDUAL_NOT_LAST, f"Residual tier {residuals[0].tier_id} must hold the greatest sequence.", tier_id=residuals[0].tier_id, field="sequence"))
    return issues


# =============================================================================
# Entry points
# =============================================================================


def validate_partnership(partnership: object) -> tuple[PartnershipIssue, ...]:
    """Every structural issue of ``partnership``, deterministically ordered;
    ``()`` when it is valid."""

    if not isinstance(partnership, Partnership):
        return (_issue(Code.INVALID_PARTNERSHIP, f"Expected a Partnership, got {type(partnership).__qualname__}."),)
    issues, known = _partner_issues(partnership.partners)
    if not isinstance(partnership.contribution_rule, ContributionRule):
        issues.append(_issue(Code.INVALID_CONTRIBUTION_RULE, "contribution_rule must be a ContributionRule; there is no default.", field="contribution_rule"))
    if issues:
        return tuple(issues)
    issues.extend(_benchmark_issues(partnership.promote_benchmark, known))
    issues.extend(_participant_issues(partnership.promote_participant_ids, known))
    issues.extend(_tiers_issues(partnership.tiers, partnership, known))
    return tuple(issues)


def require_valid_partnership(partnership: object) -> Partnership:
    """``partnership`` itself when valid; otherwise ``PartnershipValidationError``."""

    issues = validate_partnership(partnership)
    if issues:
        raise PartnershipValidationError(issues)
    return partnership  # type: ignore[return-value]
