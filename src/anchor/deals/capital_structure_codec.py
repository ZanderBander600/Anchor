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
)


class FundingAmountRuleKind(StrEnum):
    """Which amount rule funds a position, as a row, a payload and a digest
    spell it. The tokens follow the codebase's lower-case wire convention.

    ``PCT_OF_VALUE`` is representable because P7.7's contract is (valuation
    timepoints are P7.10's), so a structure that holds one round-trips exactly.
    Nothing here values it, and the P7.8 executor still refuses it."""

    FIXED_AMOUNT = "fixed_amount"
    PCT_OF_PRICE = "pct_of_price"
    PCT_OF_VALUE = "pct_of_value"


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
        case _:
            raise UnknownCapitalVariantError(rule, what="funding amount rule")


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
