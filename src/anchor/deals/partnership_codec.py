"""Phase 7 Gate P7.9 Stage 2 -- the one spelling of a Partnership's typed
variants.

A tier's split rule and a hurdle's condition are typed unions, and a hurdle's
subject and a catch-up's recipient are kind-tagged shapes
(``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 4). Python tells
the union members apart by their class; a database row, a JSON payload and a
fingerprint cannot, so each needs an explicit discriminator.

This module is that discriminator's only home. Storage
(``anchor.deals.store``), the Partnership fingerprint
(``anchor.deals.fingerprint``) and the routes (``anchor.api``) all read it, so
one variant has one token everywhere. It classifies and nothing else: no I/O,
no arithmetic, no validation, and no construction of a contract.

The split rule reuses the Stage 1 ``SplitRule`` tokens, and the subject and
recipient kinds are the Stage 1 ``HurdleSubjectKind`` and
``CatchUpRecipientKind`` tokens: one extensible enum each, never a parallel
spelling. Only the condition needs a token Stage 1 does not define.
"""

from __future__ import annotations

from enum import StrEnum

from ..partnership.contracts import (
    CatchUpRecipient,
    CatchUpRecipientKind,
    ExplicitSplit,
    HurdleCondition,
    HurdleSubject,
    HurdleSubjectKind,
    IrrHurdle,
    MoicHurdle,
    ProRataByContribution,
    SplitRule,
    TierSplit,
)


class HurdleConditionKind(StrEnum):
    """Which hurdle condition a tier states, as a row, a payload and a digest
    spell it. The tokens follow the codebase's lower-case wire convention."""

    IRR = "irr"
    MOIC = "moic"


class UnknownPartnershipVariantError(TypeError):
    """A value reached the codec that is not one of the contract's variants.

    Raised rather than defaulted, for the reason every decoder in this package
    fails closed: storing, hashing or serializing an unknown split rule as
    though it were an explicit one would produce a waterfall nobody authored."""

    def __init__(self, value: object, *, what: str) -> None:
        self.offending_type = type(value).__name__
        super().__init__(
            f"{value!r} is not a supported {what}; its type {self.offending_type!r} has no "
            "stable token. Add an explicit variant rather than defaulting to another."
        )


def split_rule_kind(split: TierSplit) -> SplitRule:
    """The token for one tier split rule. Explicit per variant: no reflection,
    and no fallback."""

    match split:
        case ExplicitSplit():
            return SplitRule.EXPLICIT
        case ProRataByContribution():
            return SplitRule.PRO_RATA_BY_CONTRIBUTION
        case _:
            raise UnknownPartnershipVariantError(split, what="tier split rule")


def condition_kind(condition: HurdleCondition) -> HurdleConditionKind:
    """The token for one hurdle condition."""

    match condition:
        case IrrHurdle():
            return HurdleConditionKind.IRR
        case MoicHurdle():
            return HurdleConditionKind.MOIC
        case _:
            raise UnknownPartnershipVariantError(condition, what="hurdle condition")


def subject_kind(subject: HurdleSubject) -> HurdleSubjectKind:
    """The token for one hurdle subject: its own stated kind, which must be a
    member of the Stage 1 enum."""

    if not isinstance(subject, HurdleSubject) or not isinstance(subject.kind, HurdleSubjectKind):
        raise UnknownPartnershipVariantError(subject, what="hurdle subject")
    return subject.kind


def recipient_kind(recipient: CatchUpRecipient) -> CatchUpRecipientKind:
    """The token for one catch-up recipient: its own stated kind, which must be
    a member of the Stage 1 enum (never an economic account)."""

    if not isinstance(recipient, CatchUpRecipient) or not isinstance(
        recipient.kind, CatchUpRecipientKind
    ):
        raise UnknownPartnershipVariantError(recipient, what="catch-up recipient")
    return recipient.kind
