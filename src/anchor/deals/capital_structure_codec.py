"""Phase 7 Gate P7.8B -- the one spelling of a Capital Structure's typed
variants.

A ``FundingEvent``'s amount rule and a ``CapitalPosition``'s terms are typed
unions (``docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md`` Section 2).
Python tells the variants apart by their class; a database row, a JSON payload
and a fingerprint cannot, so each needs an explicit discriminator.

This module is that discriminator's only home. Storage
(``anchor.deals.store``), the structured fingerprint
(``anchor.deals.fingerprint``) and the routes (``anchor.api``) all read it, so
one variant has one token everywhere and no layer can drift into spelling it
differently. It classifies and nothing else: no I/O, no arithmetic, no
validation, and no construction of a contract.

**Refinance & Capital Events V1 Stage 2.** Two more typed unions reach storage,
the fingerprint and the wire: the ``RefinanceProceeds`` funding rule, and a
refinance event's retiring reference (an authored position, or a Unit's
acquisition loan). Their tokens are declared here beside the others, so a
capital event is spelled one way everywhere too. The legacy loan is a typed
``(kind, unit_id)`` reference; its reserved identity string is never a token.
"""

from __future__ import annotations

from enum import StrEnum

from ..capital_structure.contracts import (
    DebtTerms,
    FixedAmount,
    FundingAmountRule,
    PctOfPrice,
    PctOfValue,
    PositionTerms,
    PreferredEquityTerms,
    RefinanceProceeds,
)
from ..capital_structure.events import AuthoredPositionRef, LegacyAcquisitionLoanRef


class FundingAmountRuleKind(StrEnum):
    """Which amount rule funds a position, as a row, a payload and a digest
    spell it. The tokens follow the codebase's lower-case wire convention.

    ``PCT_OF_VALUE`` is representable because P7.7's contract is (valuation
    timepoints are P7.10's), so a structure that holds one round-trips exactly.
    Nothing here values it, and the P7.8 executor still refuses it."""

    FIXED_AMOUNT = "fixed_amount"
    PCT_OF_PRICE = "pct_of_price"
    PCT_OF_VALUE = "pct_of_value"
    # Refinance & Capital Events V1 Stage 2: a replacement's funding, sized by
    # the refinance event it names. It states no amount of its own.
    REFINANCE_PROCEEDS = "refinance_proceeds"


class RetiringRefKind(StrEnum):
    """Which debt a refinance retires, as a row, a payload and a digest spell
    it (Section 6.3): an authored position by its ``position_id``, or a Unit's
    acquisition loan by its ``unit_id``."""

    AUTHORED_POSITION = "authored_position"
    LEGACY_ACQUISITION_LOAN = "legacy_acquisition_loan"


class PositionTermsKind(StrEnum):
    """Which typed terms a claim-bearing position carries. Common equity carries
    none, which is ``None`` rather than a member: the residual has no terms at
    this layer."""

    DEBT = "debt"
    PREFERRED_EQUITY = "preferred_equity"


class UnknownCapitalVariantError(TypeError):
    """A value reached the codec that is not one of the contract's variants.

    Raised rather than defaulted, for the reason every decoder in this package
    fails closed: storing, hashing or serializing an unknown funding rule as
    though it were a fixed amount would produce a position nobody authored."""

    def __init__(self, value: object, *, what: str) -> None:
        self.offending_type = type(value).__name__
        super().__init__(
            f"{value!r} is not a supported {what}; its type {self.offending_type!r} has no "
            "stable token. Add an explicit variant rather than defaulting to another."
        )


def amount_rule_kind(rule: FundingAmountRule) -> FundingAmountRuleKind:
    """The token for one funding amount rule. Explicit per variant: no
    reflection, and no fallback."""

    match rule:
        case FixedAmount():
            return FundingAmountRuleKind.FIXED_AMOUNT
        case PctOfPrice():
            return FundingAmountRuleKind.PCT_OF_PRICE
        case PctOfValue():
            return FundingAmountRuleKind.PCT_OF_VALUE
        case RefinanceProceeds():
            return FundingAmountRuleKind.REFINANCE_PROCEEDS
        case _:
            raise UnknownCapitalVariantError(rule, what="funding amount rule")


def retiring_ref_kind(ref: object) -> RetiringRefKind:
    """The token for one retiring reference. Explicit per variant: no
    reflection, and no fallback."""

    match ref:
        case AuthoredPositionRef():
            return RetiringRefKind.AUTHORED_POSITION
        case LegacyAcquisitionLoanRef():
            return RetiringRefKind.LEGACY_ACQUISITION_LOAN
        case _:
            raise UnknownCapitalVariantError(ref, what="retiring position reference")


def retiring_ref_identity(ref: object) -> str:
    """The one id a retiring reference names: the authored ``position_id`` or
    the acquisition loan's ``unit_id``. It pairs with ``retiring_ref_kind`` as
    the reference's canonical ``(kind, id)`` (Section 6.3)."""

    match ref:
        case AuthoredPositionRef():
            return ref.position_id
        case LegacyAcquisitionLoanRef():
            return ref.unit_id
        case _:
            raise UnknownCapitalVariantError(ref, what="retiring position reference")


def terms_kind(terms: PositionTerms | None) -> PositionTermsKind | None:
    """The token for one position's terms, or ``None`` for the common-equity
    residual, which carries none."""

    match terms:
        case None:
            return None
        case DebtTerms():
            return PositionTermsKind.DEBT
        case PreferredEquityTerms():
            return PositionTermsKind.PREFERRED_EQUITY
        case _:
            raise UnknownCapitalVariantError(terms, what="position terms")
