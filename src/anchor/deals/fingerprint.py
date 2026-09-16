"""Owner Return Metrics V3 Gate A7 -- canonical financial-input/AI-context
fingerprints.

Extracted from ``store.py`` (where these algorithms originated in Gate A6)
into their own module so both the storage layer and the API layer
(``anchor.api``'s ``POST /deals/fingerprint`` provenance-lookup endpoint) can
call the exact same implementation -- a fingerprint is never computed twice
by two different pieces of code that could drift apart, and it is never
duplicated in TypeScript on the frontend (see ``anchor.api``'s module
docstring for how the frontend obtains one).

Pure functions only: no I/O, no ``sqlite3``, no dependency on ``anchor.deals
.store`` or any calculation module -- these are hashes of already-validated
assumption/context values, not financial calculations, so importing this
module from ``anchor.api`` does not pull storage or engine code along with
it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable
from datetime import date
from enum import Enum
from typing import Any

from ..contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from ..analysis import (
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    MarketLeasingAssumptions,
    Suite,
)
from ..business_plan import BusinessPlan
from ..capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    DebtTerms,
    FixedAmount,
    FundingEvent,
    PctOfPrice,
    PctOfValue,
    PositionFee,
    PreferredEquityTerms,
)
from ..capital_structure.validation import economic_order
from .capital_structure_codec import PositionTermsKind, amount_rule_kind

#: The top-level fingerprint key a non-empty Business Plan is recorded under.
#: No economic contract has a field of this name, so it cannot collide with one.
_BUSINESS_PLAN_KEY = "business_plan"

#: The key the resolved Capital Structure is recorded under, beside the Project
#: fingerprint it is downstream of (P7.8B). No economic contract has a field of
#: this name.
_CAPITAL_STRUCTURE_KEY = "capital_structure"

#: The key the Project source fingerprint is recorded under inside a structured
#: fingerprint's payload.
_PROJECT_FINGERPRINT_KEY = "project_source_fingerprint"


class UnfingerprintableValueError(TypeError):
    """A value reached canonical serialization that has no defined stable
    representation.

    Raised rather than stringified. ``default=str`` would make *every* future
    type silently fingerprintable via its ``repr`` -- which is unstable across
    Python versions, and which would let two economically different values
    share a digest (or the same value produce two digests) without anyone
    noticing. A fingerprint whose failure mode is silence is worse than no
    fingerprint, because a stale analysis snapshot would be served as current.
    """

    def __init__(self, value: object) -> None:
        self.offending_type = type(value).__name__
        super().__init__(
            f"No canonical fingerprint representation for a value of type "
            f"{self.offending_type!r}. Add an explicit rule rather than "
            "relying on its string form."
        )


def _canonical(value: object) -> object:
    """The explicit, type-aware canonical form of one value.

    Called only for values ``json`` cannot encode natively, so the primitives it
    already handles -- ``str``, ``bool``, ``int``, ``float``, ``None``, ``list``,
    ``dict`` -- keep byte-identical output and every pre-existing digest is
    preserved unchanged.

    Two rules, and no catch-all:

    * ``date`` -> ISO-8601. Chosen because it is already the wire and storage
      representation, so one value has one spelling everywhere.
    * ``Enum`` -> its ``value``, which is the wire token. Fingerprinting the
      member *name* instead would make a token rename invisible.

    Anything else raises.
    """

    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise UnfingerprintableValueError(value)


def _fingerprint_json(value: dict[str, Any]) -> str:
    """A stable sha256 fingerprint of a JSON-serializable dict: canonical
    (sorted-key, no whitespace) serialization first, so semantically
    identical input always fingerprints identically regardless of field
    insertion order.

    D5.4 adds ``default=_canonical`` for the ``date`` and ``Enum`` values every
    Lease-Level contract carries -- previously a hard ``TypeError`` deep inside
    ``json``. Quick and Detailed inputs contain neither, so ``default`` is never
    consulted for them and their digests are byte-identical to before; a test
    pins the exact pre-D5.4 hashes.
    """

    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=_canonical
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_business_plan(
    payload: dict[str, Any], business_plan: BusinessPlan
) -> dict[str, Any]:
    """Phase 6 Gate D6.5 -- ``payload`` with the deal's Business Plan in it.

    **The empty plan adds nothing** (decision D11). A deal with no Business
    Plan hashes exactly the payload it hashed before D6.5, so every legacy
    digest -- and every snapshot stored against one -- is preserved byte for
    byte. A non-empty plan always adds the key, so no non-empty plan can share a
    digest with the empty one.

    **Every field of every item participates**, through ``dataclasses.asdict``
    exactly as the Lease-Level rent roll does: amounts and timing because they
    move owner cash flow; descriptions and categories because the AI Analyst,
    audit and reporting read them, so an analysis must be re-run when they
    change; ``item_id`` because it is the item's identity.

    **Canonical over economics, not over presentation.** Each collection is
    sorted by ``item_id`` -- the same rule the rent roll follows -- so the
    analyst's row order, and the storage ``ordinal`` that preserves it, never
    reach the digest: reordering rows changes no number, and must not make a
    still-valid snapshot stale. Sorting is not deduplication; a duplicated ID is
    refused by the validation authority, never collapsed here.
    """

    if not isinstance(business_plan, BusinessPlan):
        raise UnfingerprintableValueError(business_plan)
    if not business_plan.capital_items and not business_plan.owner_expense_items:
        return payload
    return {
        **payload,
        _BUSINESS_PLAN_KEY: {
            "capital_items": [
                dataclasses.asdict(item)
                for item in sorted(business_plan.capital_items, key=lambda item: item.item_id)
            ],
            "owner_expense_items": [
                dataclasses.asdict(item)
                for item in sorted(
                    business_plan.owner_expense_items, key=lambda item: item.item_id
                )
            ],
        },
    }


def fingerprint_quick_inputs(
    inputs: AcquisitionInputs, *, business_plan: BusinessPlan = BusinessPlan()
) -> str:
    """The authoritative financial-input fingerprint for a Quick deal --
    every ``AcquisitionInputs`` field and the deal's Business Plan (D6.5),
    nothing else. Deliberately excludes ``deal_context`` (Gate A4): Deal
    Context never affects deterministic calculation, so it never affects
    analysis-snapshot validity.

    ``business_plan`` defaults to the empty plan only as a compatibility
    boundary for plan-free callers; every production caller passes the deal's
    own plan explicitly (``tests/test_d6_5_business_plan_persistence_architecture.py``)."""

    return _fingerprint_json(
        _with_business_plan(dataclasses.asdict(inputs), business_plan)
    )


def fingerprint_detailed_inputs(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    business_plan: BusinessPlan = BusinessPlan(),
) -> str:
    """The authoritative financial-input fingerprint for a Detailed deal --
    every ``AcquisitionTerms`` and ``DetailedOperatingInputs`` field (the
    complete deterministic-engine input set for Detailed Underwrite) and the
    deal's Business Plan (D6.5), nothing else. Excludes ``deal_context`` for
    the same reason as the Quick fingerprint above."""

    return _fingerprint_json(
        _with_business_plan(
            {
                "terms": dataclasses.asdict(terms),
                "detailed_operating_inputs": dataclasses.asdict(detailed_operating_inputs),
            },
            business_plan,
        )
    )


def fingerprint_ai(*, analysis_fingerprint: str, deal_context: str | None) -> str:
    """The AI-snapshot/AI-context fingerprint: a function of the
    deterministic analysis fingerprint (so any financial-assumption change
    invalidates the AI snapshot too, transitively -- no separate check
    needed) plus ``deal_context`` itself (so an AI result is invalidated the
    moment the stated strategy it interpreted changes), per Gate A4/A6's AI
    staleness rules."""

    return _fingerprint_json(
        {"analysis_fingerprint": analysis_fingerprint, "deal_context": deal_context}
    )


def fingerprint_lease_level_inputs(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    business_plan: BusinessPlan = BusinessPlan(),
) -> str:
    """The authoritative financial-input fingerprint for a Lease-Level deal.

    D6.5: the deal's Business Plan joins it under its own top-level key, beside
    ``"lease_level"`` rather than inside it -- the plan is mode-agnostic deal
    state, not part of the rent roll -- and only when it is non-empty.

    Every field of every contract the deterministic pipeline reads -- the same
    six arguments ``analyze_lease_level_acquisition_with_projection`` takes,
    which is what makes "the fingerprint covers the analysis" checkable rather
    than asserted. Built from ``dataclasses.asdict``, so a field added to
    ``Suite`` or ``Lease`` is covered the day it is added; nothing here lists
    field names, and there is no allowlist to forget to update.

    **Canonical over economics, not over presentation.** Suites and leases are
    sorted by id before hashing, and the display ``ordinal`` is not a contract
    field so it never reaches this function at all. The engine addresses both
    collections by id -- ``lease_for_suite``, the suite/lease association rules
    -- so reordering a rent roll changes no number, and a fingerprint that moved
    would invalidate a still-valid snapshot for a purely cosmetic edit.

    Sorting is emphatically *not* deduplication. Two suites sharing an id remain
    two entries here and are refused downstream by ``DUPLICATE_SUITE_ID``;
    collapsing them would let an invalid rent roll fingerprint as a valid one.

    Excludes ``deal_context`` for the same reason the Quick and Detailed
    fingerprints do (Gate A4): it never reaches a calculation. Excludes the deal
    id, name and timestamps for the same reason.

    Keyed under ``"lease_level"``, mirroring how the Detailed fingerprint nests
    its two contracts, so no two modes can collide on a digest.
    """

    return _fingerprint_json(
        _with_business_plan(
            {
                "lease_level": {
                    "terms": dataclasses.asdict(terms),
                    "property_inputs": dataclasses.asdict(property_inputs),
                    "operating_inputs": dataclasses.asdict(operating_inputs),
                    "market_leasing": dataclasses.asdict(market_leasing),
                    "suites": [
                        dataclasses.asdict(suite)
                        for suite in sorted(suites, key=lambda suite: suite.suite_id)
                    ],
                    "leases": [
                        dataclasses.asdict(lease)
                        for lease in sorted(leases, key=lambda lease: lease.lease_id)
                    ],
                }
            },
            business_plan,
        )
    )


# =============================================================================
# Phase 7 Gate P7.8B -- the structured source fingerprint
#
# ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.4
# (FP-1, FP-2) and P-4. The Capital Structure is a layer *downstream* of the
# Project engine, so it gets its own fingerprint rather than joining the
# Project one:
#
#     project source fingerprint      the existing per-Unit (or visible
#             |                       Investment) resolved-input fingerprint,
#             |                       UNCHANGED -- it never learns that a
#             |                       Capital Structure exists
#             v
#     structured source fingerprint = f(project fingerprint, the RESOLVED
#                                       Capital Structure's economics)
#
# Editing junior financing therefore invalidates the structured analysis and
# the Position Decision Matrix, and nothing upstream: the Project result, its
# cache and the Project Decision Matrix stay exactly as current as they were,
# because their inputs did not move.
#
# **FP-2, exactly.** With no authored position the structured fingerprint *is*
# the Project fingerprint -- the same characters, not a hash of an empty
# structure -- so a neutral Capital Structure adds nothing anywhere, and a
# Strategy that explicitly uses none collapses onto its own Project identity.
#
# **FP-1, exactly.** Only economics enter: names, fee descriptions, the storage
# row order, database ids and timestamps never do. A position's stable
# ``position_id`` *does*, because it is the identity ``POSITION(position_id)``
# addresses; an event's or a fee's id does not, because its economics are its
# timing, its sequence and its amount.
# =============================================================================


def _event_order(item: FundingEvent | PositionFee) -> tuple[int, int, str]:
    """Canonical capital-event order: model month, then the explicit sequence
    (P-7). The stable id only makes the order total; it never reaches a
    payload."""

    identity = item.event_id if isinstance(item, FundingEvent) else item.fee_id
    return item.model_month, item.sequence, identity


def _amount_rule_payload(rule: object) -> dict[str, Any]:
    """One funding amount rule, by kind. Explicit per rule: an unknown rule is
    refused rather than hashed as something else."""

    match rule:
        case FixedAmount():
            return {"kind": amount_rule_kind(rule).value, "amount": float(rule.amount)}
        case PctOfPrice():
            return {"kind": amount_rule_kind(rule).value, "pct": float(rule.pct)}
        case PctOfValue():
            return {
                "kind": amount_rule_kind(rule).value,
                "timepoint_id": rule.timepoint_id,
                "pct": float(rule.pct),
            }
        case _:
            raise UnfingerprintableValueError(rule)


def _terms_payload(terms: object) -> dict[str, Any] | None:
    """One position's typed terms, by kind. Common equity carries none, and its
    ``None`` is the payload."""

    match terms:
        case None:
            return None
        case DebtTerms():
            return {
                "kind": PositionTermsKind.DEBT.value,
                "interest_rate": float(terms.interest_rate),
                "amortization": int(terms.amortization),
                "io_period": int(terms.io_period),
                "maturity_month": int(terms.maturity_month),
                "current_pay_rate": float(terms.current_pay_rate),
                "pik_rate": float(terms.pik_rate),
                "fees": [
                    {
                        "amount": float(fee.amount),
                        "model_month": int(fee.model_month),
                        "sequence": int(fee.sequence),
                    }
                    for fee in sorted(terms.fees, key=_event_order)
                ],
            }
        case PreferredEquityTerms():
            return {
                "kind": PositionTermsKind.PREFERRED_EQUITY.value,
                "preferred_rate": float(terms.preferred_rate),
                "current_pay_rate": float(terms.current_pay_rate),
                "accrual_permitted": bool(terms.accrual_permitted),
                "accrual_convention": (
                    None if terms.accrual_convention is None else terms.accrual_convention.value
                ),
                "redemption_month": int(terms.redemption_month),
            }
        case _:
            raise UnfingerprintableValueError(terms)


def _position_payload(position: CapitalPosition) -> dict[str, Any]:
    """One authored position's economics. ``name`` is deliberately absent: it is
    analyst display text that never reaches a calculation (FP-1)."""

    return {
        "position_id": position.position_id,
        "position_class": position.position_class.value,
        "priority": int(position.priority),
        "scope": {"kind": position.scope.kind.value, "unit_id": position.scope.unit_id},
        "shortfall_resolution": (
            None if position.shortfall_resolution is None else position.shortfall_resolution.value
        ),
        "funding": [
            {
                "model_month": int(event.model_month),
                "sequence": int(event.sequence),
                "amount_rule": _amount_rule_payload(event.amount_rule),
            }
            for event in sorted(position.funding, key=_event_order)
        ],
        "terms": _terms_payload(position.terms),
    }


def capital_structure_payload(capital_structure: CapitalStructure) -> list[dict[str, Any]]:
    """The canonical economic form of a resolved Capital Structure: every
    position in economic order -- scope, then priority (``economic_order``, the
    one authority) -- so a permutation of the authored tuple, or of the rows
    that stored it, changes nothing."""

    if not isinstance(capital_structure, CapitalStructure):
        raise UnfingerprintableValueError(capital_structure)
    return [_position_payload(position) for position in economic_order(capital_structure.positions)]


def fingerprint_structured_source(
    *, project_source_fingerprint: str, capital_structure: CapitalStructure
) -> str:
    """The source fingerprint of one structured variant: the Project variant's
    own fingerprint, and the resolved Capital Structure's economics.

    **An empty structure collapses to the Project fingerprint itself** (FP-2),
    returned unchanged rather than hashed with an empty payload. That is what
    makes structured capital neutral: a Deal, a Strategy or an Investment with
    no authored position has one financial identity, not two."""

    if not isinstance(project_source_fingerprint, str) or not project_source_fingerprint:
        raise UnfingerprintableValueError(project_source_fingerprint)
    if not isinstance(capital_structure, CapitalStructure):
        raise UnfingerprintableValueError(capital_structure)
    if not capital_structure.positions:
        return project_source_fingerprint
    return _fingerprint_json(
        {
            _PROJECT_FINGERPRINT_KEY: project_source_fingerprint,
            _CAPITAL_STRUCTURE_KEY: capital_structure_payload(capital_structure),
        }
    )
