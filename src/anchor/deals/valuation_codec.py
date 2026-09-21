"""Phase 7 Gate P7.10 Stage 2 -- the one spelling of a valuation method.

A unit valuation instruction's method is a typed union,
``DIRECT_CAP(cap_rate) | ANALYST_VALUE(amount, evidence_id)``
(``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Section 5.1; R-D).
Python tells the two apart by their class; a database row, a JSON payload and a
fingerprint cannot, so each needs an explicit discriminator.

This module is that discriminator's only home. Storage
(``anchor.deals.store``), the valuation fingerprints
(``anchor.deals.fingerprint``) and the routes (``anchor.api``) all read it, so
one method has one token everywhere.

It reuses the Stage 1 ``ValuationMethodKind`` tokens rather than declaring a
parallel spelling: the engine, the row, the wire and the digest all say
``direct_cap`` and ``analyst_value``, and a rename would have exactly one place
to happen.

It classifies and nothing else: no I/O, no arithmetic, no validation, and no
construction of a contract. In particular it never chooses a method for an
instruction that states none -- a missing method is refused by the Stage 1
validator, never defaulted to direct capitalisation.
"""

from __future__ import annotations

from ..valuation.contracts import AnalystValue, DirectCap, ValuationMethod, ValuationMethodKind


class UnknownValuationMethodError(TypeError):
    """A value reached the codec that is not one of the contract's two methods.

    Raised rather than defaulted, for the reason every decoder in this package
    fails closed: storing or hashing an unknown method as though it were a
    direct capitalisation would produce a valuation nobody authored -- and an
    analyst-supplied value silently read as an Anchor conclusion is precisely
    what Section 5.4 forbids."""

    def __init__(self, value: object) -> None:
        self.offending_type = type(value).__name__
        super().__init__(
            f"{value!r} is not a supported valuation method; its type {self.offending_type!r} has no stable "
            "token. The initial methods are direct capitalisation and an explicitly labelled analyst-supplied "
            "value (R-D). Add an explicit variant rather than defaulting to another."
        )


def valuation_method_kind(method: ValuationMethod) -> ValuationMethodKind:
    """The token for one valuation method. Explicit per variant: no reflection,
    and no fallback."""

    match method:
        case DirectCap():
            return ValuationMethodKind.DIRECT_CAP
        case AnalystValue():
            return ValuationMethodKind.ANALYST_VALUE
        case _:
            raise UnknownValuationMethodError(method)


def is_analyst_supplied(method: ValuationMethod) -> bool:
    """Whether this method states an external value the analyst supplied rather
    than one Anchor concluded (Section 5.4).

    Derived from the token, not from a stored flag, so the two can never
    disagree: there is one fact and one place it is decided."""

    return valuation_method_kind(method) is ValuationMethodKind.ANALYST_VALUE
